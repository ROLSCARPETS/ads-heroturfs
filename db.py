"""Capa de acceso a SQLite para los datos de Meta Ads + HubSpot CRM."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).parent / "meta_ads.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS campaigns (
    id              TEXT PRIMARY KEY,
    name            TEXT,
    status          TEXT,
    effective_status TEXT,
    objective       TEXT,
    daily_budget    REAL,
    lifetime_budget REAL,
    created_time    TEXT,
    start_time      TEXT,
    stop_time       TEXT,
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS insights_daily (
    campaign_id     TEXT NOT NULL,
    date            TEXT NOT NULL,
    impressions     INTEGER,
    reach           INTEGER,
    clicks          INTEGER,
    spend           REAL,
    ctr             REAL,
    cpc             REAL,
    cpm             REAL,
    frequency       REAL,
    PRIMARY KEY (campaign_id, date)
);

CREATE TABLE IF NOT EXISTS actions_daily (
    campaign_id     TEXT NOT NULL,
    date            TEXT NOT NULL,
    action_type     TEXT NOT NULL,
    value           REAL,
    action_value    REAL,
    PRIMARY KEY (campaign_id, date, action_type)
);

CREATE TABLE IF NOT EXISTS sync_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    days_back       INTEGER,
    campaigns_count INTEGER,
    insights_count  INTEGER,
    actions_count   INTEGER,
    status          TEXT,
    error           TEXT
);

CREATE INDEX IF NOT EXISTS idx_insights_date ON insights_daily(date);
CREATE INDEX IF NOT EXISTS idx_actions_date ON actions_daily(date);
CREATE INDEX IF NOT EXISTS idx_actions_type ON actions_daily(action_type);

-- ====================================================================
-- HubSpot CRM
-- ====================================================================

CREATE TABLE IF NOT EXISTS hubspot_pipelines (
    id              TEXT NOT NULL,
    object_type     TEXT NOT NULL,        -- 'deals' o 'contacts'
    label           TEXT,
    display_order   INTEGER,
    archived        INTEGER DEFAULT 0,
    updated_at      TEXT,
    PRIMARY KEY (id, object_type)
);

CREATE TABLE IF NOT EXISTS hubspot_pipeline_stages (
    pipeline_id     TEXT NOT NULL,
    stage_id        TEXT NOT NULL,
    object_type     TEXT NOT NULL,
    label           TEXT,
    probability     REAL,                 -- 1.0 = won, 0.0 = lost, 0<x<1 = open
    display_order   INTEGER,
    archived        INTEGER DEFAULT 0,
    updated_at      TEXT,
    PRIMARY KEY (pipeline_id, stage_id)
);

CREATE TABLE IF NOT EXISTS hubspot_contacts (
    id                                  TEXT PRIMARY KEY,
    email                               TEXT,
    firstname                           TEXT,
    lastname                            TEXT,
    createdate                          TEXT,
    lastmodifieddate                    TEXT,
    lifecyclestage                      TEXT,
    pais                                TEXT,
    fuentes_de_captacion_especificas    TEXT,
    hs_lead_status                      TEXT,
    hs_customer_agent_lead_status       TEXT,
    updated_at                          TEXT
);

CREATE TABLE IF NOT EXISTS hubspot_deals (
    id                              TEXT PRIMARY KEY,
    dealname                        TEXT,
    amount                          REAL,
    pipeline                        TEXT,
    dealstage                       TEXT,
    createdate                      TEXT,
    closedate                       TEXT,
    hs_lastmodifieddate             TEXT,
    hs_analytics_source             TEXT,
    hs_analytics_source_data_1      TEXT,
    hs_analytics_source_data_2      TEXT,
    is_won                          INTEGER DEFAULT 0,
    is_lost                         INTEGER DEFAULT 0,
    updated_at                      TEXT
);

CREATE TABLE IF NOT EXISTS hubspot_deal_contacts (
    deal_id     TEXT NOT NULL,
    contact_id  TEXT NOT NULL,
    PRIMARY KEY (deal_id, contact_id)
);

CREATE TABLE IF NOT EXISTS hubspot_sync_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at          TEXT NOT NULL,
    finished_at         TEXT,
    contacts_count      INTEGER,
    deals_count         INTEGER,
    pipelines_count     INTEGER,
    associations_count  INTEGER,
    status              TEXT,
    error               TEXT
);

CREATE INDEX IF NOT EXISTS idx_hs_contacts_fuente   ON hubspot_contacts(fuentes_de_captacion_especificas);
CREATE INDEX IF NOT EXISTS idx_hs_contacts_status   ON hubspot_contacts(hs_lead_status);
CREATE INDEX IF NOT EXISTS idx_hs_contacts_pais     ON hubspot_contacts(pais);
CREATE INDEX IF NOT EXISTS idx_hs_contacts_created  ON hubspot_contacts(createdate);
CREATE INDEX IF NOT EXISTS idx_hs_deals_stage       ON hubspot_deals(dealstage);
CREATE INDEX IF NOT EXISTS idx_hs_deals_won         ON hubspot_deals(is_won);
CREATE INDEX IF NOT EXISTS idx_hs_deals_created     ON hubspot_deals(createdate);
CREATE INDEX IF NOT EXISTS idx_hs_deals_closed      ON hubspot_deals(closedate);
CREATE INDEX IF NOT EXISTS idx_hs_deal_contacts_c   ON hubspot_deal_contacts(contact_id);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def upsert_campaign(conn, c):
    conn.execute(
        """
        INSERT INTO campaigns (id, name, status, effective_status, objective,
                               daily_budget, lifetime_budget, created_time,
                               start_time, stop_time, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            status = excluded.status,
            effective_status = excluded.effective_status,
            objective = excluded.objective,
            daily_budget = excluded.daily_budget,
            lifetime_budget = excluded.lifetime_budget,
            start_time = excluded.start_time,
            stop_time = excluded.stop_time,
            updated_at = datetime('now')
        """,
        (
            c.get("id"),
            c.get("name"),
            c.get("status"),
            c.get("effective_status"),
            c.get("objective"),
            _to_float(c.get("daily_budget")),
            _to_float(c.get("lifetime_budget")),
            c.get("created_time"),
            c.get("start_time"),
            c.get("stop_time"),
        ),
    )


def upsert_insight(conn, row):
    conn.execute(
        """
        INSERT INTO insights_daily (campaign_id, date, impressions, reach,
                                    clicks, spend, ctr, cpc, cpm, frequency)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(campaign_id, date) DO UPDATE SET
            impressions = excluded.impressions,
            reach = excluded.reach,
            clicks = excluded.clicks,
            spend = excluded.spend,
            ctr = excluded.ctr,
            cpc = excluded.cpc,
            cpm = excluded.cpm,
            frequency = excluded.frequency
        """,
        (
            row["campaign_id"],
            row["date"],
            _to_int(row.get("impressions")),
            _to_int(row.get("reach")),
            _to_int(row.get("clicks")),
            _to_float(row.get("spend")),
            _to_float(row.get("ctr")),
            _to_float(row.get("cpc")),
            _to_float(row.get("cpm")),
            _to_float(row.get("frequency")),
        ),
    )


def upsert_action(conn, campaign_id, date, action_type, value, action_value):
    conn.execute(
        """
        INSERT INTO actions_daily (campaign_id, date, action_type, value, action_value)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(campaign_id, date, action_type) DO UPDATE SET
            value = excluded.value,
            action_value = excluded.action_value
        """,
        (campaign_id, date, action_type, _to_float(value), _to_float(action_value)),
    )


def log_sync_start(conn, days_back):
    cur = conn.execute(
        "INSERT INTO sync_log (started_at, days_back, status) VALUES (datetime('now'), ?, 'running')",
        (days_back,),
    )
    return cur.lastrowid


def log_sync_finish(conn, sync_id, campaigns_count, insights_count, actions_count, status, error=None):
    conn.execute(
        """
        UPDATE sync_log
        SET finished_at = datetime('now'),
            campaigns_count = ?,
            insights_count = ?,
            actions_count = ?,
            status = ?,
            error = ?
        WHERE id = ?
        """,
        (campaigns_count, insights_count, actions_count, status, error, sync_id),
    )


# ====================================================================
# HubSpot upserts
# ====================================================================

def upsert_hubspot_pipeline(conn, p, object_type):
    conn.execute(
        """
        INSERT INTO hubspot_pipelines (id, object_type, label, display_order, archived, updated_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(id, object_type) DO UPDATE SET
            label = excluded.label,
            display_order = excluded.display_order,
            archived = excluded.archived,
            updated_at = datetime('now')
        """,
        (p.get("id"), object_type, p.get("label"), p.get("displayOrder"), 1 if p.get("archived") else 0),
    )


def upsert_hubspot_stage(conn, pipeline_id, s, object_type):
    md = s.get("metadata") or {}
    conn.execute(
        """
        INSERT INTO hubspot_pipeline_stages (pipeline_id, stage_id, object_type, label,
                                              probability, display_order, archived, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(pipeline_id, stage_id) DO UPDATE SET
            label = excluded.label,
            probability = excluded.probability,
            display_order = excluded.display_order,
            archived = excluded.archived,
            updated_at = datetime('now')
        """,
        (
            pipeline_id, s.get("id"), object_type, s.get("label"),
            _to_float(md.get("probability")),
            s.get("displayOrder"),
            1 if s.get("archived") else 0,
        ),
    )


def upsert_hubspot_contact(conn, c):
    p = c.get("properties") or {}
    conn.execute(
        """
        INSERT INTO hubspot_contacts (id, email, firstname, lastname, createdate, lastmodifieddate,
                                       lifecyclestage, pais, fuentes_de_captacion_especificas,
                                       hs_lead_status, hs_customer_agent_lead_status, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(id) DO UPDATE SET
            email = excluded.email,
            firstname = excluded.firstname,
            lastname = excluded.lastname,
            createdate = excluded.createdate,
            lastmodifieddate = excluded.lastmodifieddate,
            lifecyclestage = excluded.lifecyclestage,
            pais = excluded.pais,
            fuentes_de_captacion_especificas = excluded.fuentes_de_captacion_especificas,
            hs_lead_status = excluded.hs_lead_status,
            hs_customer_agent_lead_status = excluded.hs_customer_agent_lead_status,
            updated_at = datetime('now')
        """,
        (
            c.get("id"),
            p.get("email"),
            p.get("firstname"),
            p.get("lastname"),
            p.get("createdate"),
            p.get("lastmodifieddate"),
            p.get("lifecyclestage"),
            p.get("pais"),
            p.get("fuentes_de_captacion_especificas"),
            p.get("hs_lead_status"),
            p.get("hs_customer_agent_lead_status"),
        ),
    )


def upsert_hubspot_deal(conn, d, stage_probability_map):
    """Inserta/actualiza un deal calculando is_won/is_lost desde la prob de su stage."""
    p = d.get("properties") or {}
    stage = p.get("dealstage")
    prob = stage_probability_map.get(stage)
    is_won = 1 if prob == 1.0 else 0
    is_lost = 1 if prob == 0.0 else 0

    conn.execute(
        """
        INSERT INTO hubspot_deals (id, dealname, amount, pipeline, dealstage, createdate, closedate,
                                    hs_lastmodifieddate, hs_analytics_source, hs_analytics_source_data_1,
                                    hs_analytics_source_data_2, is_won, is_lost, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(id) DO UPDATE SET
            dealname = excluded.dealname,
            amount = excluded.amount,
            pipeline = excluded.pipeline,
            dealstage = excluded.dealstage,
            createdate = excluded.createdate,
            closedate = excluded.closedate,
            hs_lastmodifieddate = excluded.hs_lastmodifieddate,
            hs_analytics_source = excluded.hs_analytics_source,
            hs_analytics_source_data_1 = excluded.hs_analytics_source_data_1,
            hs_analytics_source_data_2 = excluded.hs_analytics_source_data_2,
            is_won = excluded.is_won,
            is_lost = excluded.is_lost,
            updated_at = datetime('now')
        """,
        (
            d.get("id"),
            p.get("dealname"),
            _to_float(p.get("amount")),
            p.get("pipeline"),
            stage,
            p.get("createdate"),
            p.get("closedate"),
            p.get("hs_lastmodifieddate"),
            p.get("hs_analytics_source"),
            p.get("hs_analytics_source_data_1"),
            p.get("hs_analytics_source_data_2"),
            is_won,
            is_lost,
        ),
    )


def upsert_hubspot_deal_contact(conn, deal_id, contact_id):
    conn.execute(
        "INSERT OR IGNORE INTO hubspot_deal_contacts (deal_id, contact_id) VALUES (?, ?)",
        (deal_id, contact_id),
    )


def clear_hubspot_deal_contacts_for_deal(conn, deal_id):
    """Borra las asociaciones existentes de un deal antes de re-insertar (manejar deletes)."""
    conn.execute("DELETE FROM hubspot_deal_contacts WHERE deal_id = ?", (deal_id,))


def log_hubspot_sync_start(conn):
    cur = conn.execute(
        "INSERT INTO hubspot_sync_log (started_at, status) VALUES (datetime('now'), 'running')"
    )
    return cur.lastrowid


def log_hubspot_sync_finish(conn, sync_id, contacts, deals, pipelines, associations, status, error=None):
    conn.execute(
        """
        UPDATE hubspot_sync_log
        SET finished_at = datetime('now'),
            contacts_count = ?, deals_count = ?, pipelines_count = ?,
            associations_count = ?, status = ?, error = ?
        WHERE id = ?
        """,
        (contacts, deals, pipelines, associations, status, error, sync_id),
    )


def stage_probability_map(conn):
    """Devuelve {stage_id: probability} para resolver is_won/is_lost de cada deal."""
    rows = conn.execute(
        "SELECT stage_id, probability FROM hubspot_pipeline_stages WHERE object_type = 'deals'"
    ).fetchall()
    return {r["stage_id"]: r["probability"] for r in rows}


# ====================================================================
# Helpers
# ====================================================================

def _to_float(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_int(v):
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None
