"""Capa de acceso a SQLite para los datos de Meta Ads."""

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
