"""Dashboard web Flask para analisis de campanas Meta Ads de Heroturfs."""

import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template, request

import db
import hubspot_sync
import meta_sync
from campaign_country import SUPPORTED_COUNTRIES

# google_sync se importa lazy en el endpoint /api/google/sync para no
# fallar si las dependencias de google-ads aun no estan instaladas
# o si falta el Developer Token (en aprobacion).

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True

# Asegurar que las tablas existen (idempotente, corre migraciones si las hay).
db.init_db()

LEAD_ACTION_TYPES = (
    "lead",
    "offsite_conversion.fb_pixel_lead",
    "onsite_conversion.lead_grouped",
    "offsite_content_view_add_meta_leads",
)

# Fuentes de captacion en HubSpot
HUBSPOT_META_SOURCE = "Redes Sociales - IG/FB"
HUBSPOT_GOOGLE_SOURCE = "Web - Google Ads"


def _hubspot_period_expr(granularity):
    """Misma logica que _period_expr pero aplicada a SUBSTR(createdate,1,10) de HubSpot."""
    if granularity == "weekly":
        return ("date(SUBSTR(createdate, 1, 10), '-' || "
                "((CAST(strftime('%w', SUBSTR(createdate,1,10)) AS INTEGER) + 6) % 7) || ' days')")
    if granularity == "monthly":
        return "date(SUBSTR(createdate, 1, 10), 'start of month')"
    return "SUBSTR(createdate, 1, 10)"


def _count_hubspot_leads(conn, since_iso, until_iso, source=None, country=None):
    """Cuenta contactos HubSpot creados en el rango. Filtros opcionales."""
    sql = "SELECT COUNT(*) c FROM hubspot_contacts WHERE createdate BETWEEN ? AND ?"
    params = [since_iso, until_iso]
    if source is not None:
        sql += " AND fuentes_de_captacion_especificas = ?"
        params.append(source)
    if country:
        sql += " AND pais = ?"
        params.append(country)
    return conn.execute(sql, params).fetchone()["c"]


def _hubspot_leads_by_period(conn, since_iso, until_iso, granularity, source=None, country=None):
    """Devuelve dict {period: count} agregando contactos HubSpot por periodo."""
    period_expr = _hubspot_period_expr(granularity)
    sql = f"SELECT {period_expr} AS period, COUNT(*) c FROM hubspot_contacts WHERE createdate BETWEEN ? AND ?"
    params = [since_iso, until_iso]
    if source is not None:
        sql += " AND fuentes_de_captacion_especificas = ?"
        params.append(source)
    if country:
        sql += " AND pais = ?"
        params.append(country)
    sql += " GROUP BY period ORDER BY period"
    return {r["period"]: r["c"] for r in conn.execute(sql, params)}


def _date_to_hubspot_iso(d_str, end=False):
    """Convierte 'YYYY-MM-DD' a ISO completo para comparar contra createdate de HubSpot."""
    return d_str + ("T23:59:59.999Z" if end else "T00:00:00.000Z")


def _get_conn():
    conn = sqlite3.connect(db.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _resolve_range(days_param):
    """Resuelve el rango (since, until, days_label) segun el param.

    days_param puede ser:
    - Un entero como string ("30", "90", "365"): N dias hacia atras desde hoy
    - "all": desde el primer registro en BBDD hasta hoy
    """
    until = date.today()
    if days_param == "all":
        with _get_conn() as conn:
            r = conn.execute("SELECT MIN(date) mn FROM insights_daily").fetchone()
        if r and r["mn"]:
            since = datetime.strptime(r["mn"], "%Y-%m-%d").date()
        else:
            since = until
    else:
        try:
            days = int(days_param)
        except (TypeError, ValueError):
            days = 30
        since = until - timedelta(days=max(days - 1, 0))
    days_label = (until - since).days + 1
    return since.isoformat(), until.isoformat(), days_label


def _range_from_request():
    """Lee since/until/days de la request actual y devuelve (since, until, days_label).

    Si la request lleva 'since' y 'until' (YYYY-MM-DD), usa esos directamente.
    En caso contrario, recurre a _resolve_range con el param 'days'.
    """
    since_p = request.args.get("since")
    until_p = request.args.get("until")
    if since_p and until_p:
        try:
            s = date.fromisoformat(since_p[:10])
            u = date.fromisoformat(until_p[:10])
            if s > u:
                s, u = u, s
            return s.isoformat(), u.isoformat(), (u - s).days + 1
        except (ValueError, TypeError):
            pass
    return _resolve_range(request.args.get("days", "30"))


def _previous_range(since_iso, until_iso):
    """Devuelve (prev_since, prev_until) ISO con la misma duracion, justo antes."""
    s = date.fromisoformat(since_iso)
    u = date.fromisoformat(until_iso)
    days = (u - s).days + 1
    prev_until = s - timedelta(days=1)
    prev_since = prev_until - timedelta(days=days - 1)
    return prev_since.isoformat(), prev_until.isoformat()


def _delta_pct(current, previous):
    """Devuelve (current - previous) / previous * 100, o None si no calculable."""
    if previous is None or previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)


def _hubspot_previous_range(since_iso, until_iso):
    """Como _previous_range pero para timestamps ISO de HubSpot (con T...Z).

    Mantiene la misma duracion en dias y devuelve formato 'YYYY-MM-DDT00:00:00Z' /
    'YYYY-MM-DDT23:59:59Z' para usar en filtros createdate/lastmodifieddate.
    """
    s = date.fromisoformat(since_iso[:10])
    u = date.fromisoformat(until_iso[:10])
    days = (u - s).days + 1
    prev_until = s - timedelta(days=1)
    prev_since = prev_until - timedelta(days=days - 1)
    return (
        f"{prev_since.isoformat()}T00:00:00Z",
        f"{prev_until.isoformat()}T23:59:59Z",
    )


def _fetch_leads_by_campaign(conn, since, until):
    """Devuelve dict {campaign_id: total_leads} sumando los tipos de accion considerados leads."""
    placeholders = ",".join("?" for _ in LEAD_ACTION_TYPES)
    rows = conn.execute(
        f"""
        SELECT campaign_id, SUM(value) AS leads
        FROM actions_daily
        WHERE date BETWEEN ? AND ?
          AND action_type IN ({placeholders})
        GROUP BY campaign_id
        """,
        (since, until, *LEAD_ACTION_TYPES),
    ).fetchall()
    return {r["campaign_id"]: r["leads"] or 0 for r in rows}


def _period_expr(granularity, col="date"):
    """Devuelve la expresion SQL para agrupar por dia/semana/mes.

    `col` permite usar la expresion con un nombre de columna distinto (ej. 'bh.date')
    cuando la tabla esta calificada por alias.
    """
    if granularity == "weekly":
        # Lunes de la semana (ISO): substraer (weekday-1) dias, donde weekday: lun=1..dom=7
        return f"date({col}, '-' || ((CAST(strftime('%w', {col}) AS INTEGER) + 6) % 7) || ' days')"
    if granularity == "monthly":
        # Primer dia del mes
        return f"date({col}, 'start of month')"
    return col


def _fetch_leads_by_period(conn, since, until, granularity="daily"):
    placeholders = ",".join("?" for _ in LEAD_ACTION_TYPES)
    period_expr = _period_expr(granularity)
    rows = conn.execute(
        f"""
        SELECT {period_expr} AS period, SUM(value) AS leads
        FROM actions_daily
        WHERE date BETWEEN ? AND ?
          AND action_type IN ({placeholders})
        GROUP BY period
        ORDER BY period
        """,
        (since, until, *LEAD_ACTION_TYPES),
    ).fetchall()
    return {r["period"]: r["leads"] or 0 for r in rows}


@app.route("/")
def index():
    return render_template("dashboard.html")


def _meta_kpis(conn, since, until, country):
    """KPIs BLENDED (Meta + Google) + HubSpot todas las fuentes.
    Pese al nombre 'meta', desde que el Resumen pasa a ser blended esta
    funcion suma tambien Google. Reach se queda Meta-only (Google no expone
    reach comparable); el resto se suma.
    """
    # Meta insights
    sql_m = (
        "SELECT SUM(i.spend) spend, SUM(i.impressions) impressions, "
        "SUM(i.reach) reach, SUM(i.clicks) clicks "
        "FROM insights_daily i JOIN campaigns c ON c.id = i.campaign_id "
        "WHERE i.date BETWEEN ? AND ?"
    )
    params_m = [since, until]
    if country:
        sql_m += " AND c.country = ?"
        params_m.append(country)
    rm = conn.execute(sql_m, params_m).fetchone()
    spend_meta = rm["spend"] or 0
    impressions_meta = rm["impressions"] or 0
    reach_meta = rm["reach"] or 0  # Solo Meta
    clicks_meta = rm["clicks"] or 0

    # Google insights
    sql_g = (
        "SELECT SUM(i.cost) cost, SUM(i.impressions) impressions, SUM(i.clicks) clicks "
        "FROM google_insights_daily i JOIN google_campaigns c ON c.id = i.campaign_id "
        "WHERE i.date BETWEEN ? AND ?"
    )
    params_g = [since, until]
    if country:
        sql_g += " AND c.country = ?"
        params_g.append(country)
    rg = conn.execute(sql_g, params_g).fetchone()
    spend_google = rg["cost"] or 0
    impressions_google = rg["impressions"] or 0
    clicks_google = rg["clicks"] or 0

    # Sumas blended
    spend = spend_meta + spend_google
    impressions = impressions_meta + impressions_google
    clicks = clicks_meta + clicks_google

    # Leads HubSpot - TODAS las fuentes (no solo Meta) para coincidir con el
    # chart blended del top del Resumen.
    since_iso = _date_to_hubspot_iso(since)
    until_iso = _date_to_hubspot_iso(until, end=True)
    leads = _count_hubspot_leads(conn, since_iso, until_iso,
                                 source=None, country=country)
    return {
        "spend": round(spend, 2),
        "impressions": impressions,
        "reach": reach_meta,  # Meta-only, etiquetado en HTML
        "clicks": clicks,
        "ctr": round((clicks / impressions * 100) if impressions else 0, 2),
        "cpc": round((spend / clicks) if clicks else 0, 3),
        "cpm": round((spend / impressions * 1000) if impressions else 0, 2),
        "leads": int(leads),
        "cpl": round((spend / leads) if leads else 0, 2),
    }


@app.route("/api/kpis")
def api_kpis():
    days_param = request.args.get("days", "30")
    country = request.args.get("country") or None
    since, until, days = _range_from_request()
    prev_since, prev_until = _previous_range(since, until)

    with _get_conn() as conn:
        cur = _meta_kpis(conn, since, until, country)
        prev = _meta_kpis(conn, prev_since, prev_until, country)
        last_sync = conn.execute(
            "SELECT finished_at FROM sync_log WHERE status = 'ok' ORDER BY id DESC LIMIT 1"
        ).fetchone()

    deltas = {f"{k}_pct": _delta_pct(cur[k], prev[k]) for k in cur}

    return jsonify({
        "since": since,
        "until": until,
        "days": days,
        "country": country,
        **cur,
        "previous": {
            "since": prev_since,
            "until": prev_until,
            **prev,
        },
        "deltas": deltas,
        "last_sync": last_sync["finished_at"] if last_sync else None,
    })


@app.route("/api/timeseries")
def api_timeseries():
    """Serie de gasto, clicks y leads agregada por periodo (diario/semanal/mensual).

    Leads vienen de HubSpot (contactos atribuidos a Meta), no de Meta API.
    """
    days_param = request.args.get("days", "30")
    country = request.args.get("country") or None
    granularity = request.args.get("granularity", "daily")
    if granularity not in ("daily", "weekly", "monthly"):
        granularity = "daily"
    since, until, _days = _range_from_request()
    period_expr = _period_expr(granularity)

    sql = (
        f"SELECT {period_expr} AS period, "
        "SUM(i.spend) spend, SUM(i.clicks) clicks, SUM(i.impressions) impressions "
        "FROM insights_daily i JOIN campaigns c ON c.id = i.campaign_id "
        "WHERE i.date BETWEEN ? AND ?"
    )
    params = [since, until]
    if country:
        sql += " AND c.country = ?"
        params.append(country)
    sql += " GROUP BY period ORDER BY period"

    with _get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        # Leads diarios/semanales/mensuales desde HubSpot (atribuidos a Meta)
        since_iso = _date_to_hubspot_iso(since)
        until_iso = _date_to_hubspot_iso(until, end=True)
        leads_by_period = _hubspot_leads_by_period(
            conn, since_iso, until_iso, granularity,
            source=HUBSPOT_META_SOURCE, country=country,
        )

    series = []
    for r in rows:
        p = r["period"]
        series.append(
            {
                "period": p,
                "spend": round(r["spend"] or 0, 2),
                "clicks": r["clicks"] or 0,
                "impressions": r["impressions"] or 0,
                "leads": int(leads_by_period.get(p, 0)),
            }
        )
    return jsonify({"granularity": granularity, "data": series})


@app.route("/api/campaigns")
def api_campaigns():
    """Tabla de campanas con metricas agregadas en el rango.

    Nota: los leads y CPL aqui vienen de Meta API (no HubSpot) porque no podemos
    atribuir un contacto HubSpot a una campana Meta concreta sin UTM tracking.
    """
    days_param = request.args.get("days", "30")
    country = request.args.get("country") or None
    since, until, days = _range_from_request()

    sql = (
        "SELECT c.id, c.name, c.effective_status, c.objective, c.country, "
        "SUM(i.spend) spend, SUM(i.impressions) impressions, "
        "SUM(i.reach) reach, SUM(i.clicks) clicks "
        "FROM campaigns c "
        "LEFT JOIN insights_daily i ON i.campaign_id = c.id AND i.date BETWEEN ? AND ? "
    )
    params = [since, until]
    if country:
        sql += "WHERE c.country = ? "
        params.append(country)
    sql += "GROUP BY c.id ORDER BY spend DESC NULLS LAST"

    with _get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        leads_by_campaign = _fetch_leads_by_campaign(conn, since, until)

    out = []
    for r in rows:
        spend = r["spend"] or 0
        impressions = r["impressions"] or 0
        clicks = r["clicks"] or 0
        leads = int(leads_by_campaign.get(r["id"], 0))
        out.append(
            {
                "id": r["id"],
                "name": r["name"],
                "status": r["effective_status"],
                "objective": r["objective"],
                "country": r["country"],
                "spend": round(spend, 2),
                "impressions": impressions,
                "reach": r["reach"] or 0,
                "clicks": clicks,
                "ctr": round((clicks / impressions * 100) if impressions else 0, 2),
                "cpc": round((spend / clicks) if clicks else 0, 3),
                "leads": leads,
                "cpl": round((spend / leads) if leads else 0, 2),
            }
        )
    return jsonify(out)


@app.route("/api/sync", methods=["POST"])
def api_sync():
    """Lanza una sincronizacion manual contra la API de Meta."""
    try:
        meta_sync.sync()
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


# ====================================================================
# HubSpot endpoints
# ====================================================================
# (HUBSPOT_META_SOURCE y HUBSPOT_GOOGLE_SOURCE ya definidas arriba)


def _hubspot_date_range(days_param):
    """Para HubSpot el rango va contra createdate (timestamps ISO con T y Z).

    Devuelve (since_iso, until_iso) compatibles con comparaciones SQL string contra
    `createdate` que viene en formato '2026-01-15T08:30:00.000Z'.
    """
    until = date.today()
    if days_param == "all":
        # Cogemos el minimo entre contactos y deals para tener todo
        with _get_conn() as conn:
            r1 = conn.execute("SELECT MIN(createdate) c FROM hubspot_contacts").fetchone()
            r2 = conn.execute("SELECT MIN(createdate) c FROM hubspot_deals").fetchone()
        candidates = [x["c"] for x in (r1, r2) if x and x["c"]]
        since_iso = min(candidates)[:10] if candidates else until.isoformat()
        return since_iso + "T00:00:00.000Z", until.isoformat() + "T23:59:59.999Z"
    try:
        days = int(days_param)
    except (TypeError, ValueError):
        days = 30
    since_d = until - timedelta(days=max(days - 1, 0))
    return since_d.isoformat() + "T00:00:00.000Z", until.isoformat() + "T23:59:59.999Z"


def _hubspot_range_from_request():
    """Como _hubspot_date_range pero respeta since/until custom de la request."""
    since_p = request.args.get("since")
    until_p = request.args.get("until")
    if since_p and until_p:
        try:
            s = date.fromisoformat(since_p[:10])
            u = date.fromisoformat(until_p[:10])
            if s > u:
                s, u = u, s
            return f"{s.isoformat()}T00:00:00.000Z", f"{u.isoformat()}T23:59:59.999Z"
        except (ValueError, TypeError):
            pass
    return _hubspot_date_range(request.args.get("days", "30"))


def _hubspot_kpis(conn, since, until, country):
    """Calcula KPIs HubSpot principales para un rango (returns dict)."""
    pais_clause = " AND pais = ?" if country else ""
    pais_params = [country] if country else []

    contacts_total = conn.execute(
        f"SELECT COUNT(*) c FROM hubspot_contacts WHERE createdate BETWEEN ? AND ?{pais_clause}",
        [since, until, *pais_params],
    ).fetchone()["c"]

    contacts_meta = conn.execute(
        f"SELECT COUNT(*) c FROM hubspot_contacts WHERE createdate BETWEEN ? AND ? "
        f"AND fuentes_de_captacion_especificas = ?{pais_clause}",
        [since, until, HUBSPOT_META_SOURCE, *pais_params],
    ).fetchone()["c"]
    contacts_google = conn.execute(
        f"SELECT COUNT(*) c FROM hubspot_contacts WHERE createdate BETWEEN ? AND ? "
        f"AND fuentes_de_captacion_especificas = ?{pais_clause}",
        [since, until, HUBSPOT_GOOGLE_SOURCE, *pais_params],
    ).fetchone()["c"]

    if country:
        deals_won_row = conn.execute(
            """
            SELECT COUNT(DISTINCT d.id) c, COALESCE(SUM(d.amount),0) revenue
            FROM hubspot_deals d
            JOIN hubspot_deal_contacts dc ON dc.deal_id = d.id
            JOIN hubspot_contacts c ON c.id = dc.contact_id
            WHERE d.is_won = 1 AND d.createdate BETWEEN ? AND ? AND c.pais = ?
            """,
            (since, until, country),
        ).fetchone()
    else:
        deals_won_row = conn.execute(
            "SELECT COUNT(*) c, COALESCE(SUM(amount), 0) revenue FROM hubspot_deals "
            "WHERE is_won = 1 AND createdate BETWEEN ? AND ?",
            (since, until),
        ).fetchone()

    revenue_by_source = {}
    rev_sql = """
        SELECT COALESCE(c.fuentes_de_captacion_especificas, '(sin atribucion)') src,
               COALESCE(SUM(d.amount), 0) revenue,
               COUNT(DISTINCT d.id) deals
        FROM hubspot_deals d
        LEFT JOIN hubspot_deal_contacts dc ON dc.deal_id = d.id
        LEFT JOIN hubspot_contacts c ON c.id = dc.contact_id
        WHERE d.is_won = 1 AND d.createdate BETWEEN ? AND ?
    """
    rev_params = [since, until]
    if country:
        rev_sql += " AND c.pais = ?"
        rev_params.append(country)
    rev_sql += " GROUP BY c.fuentes_de_captacion_especificas"
    for r in conn.execute(rev_sql, rev_params):
        revenue_by_source[r["src"]] = {"revenue": round(r["revenue"], 2), "deals": r["deals"]}

    revenue_meta = revenue_by_source.get(HUBSPOT_META_SOURCE, {}).get("revenue", 0)
    deals_meta = revenue_by_source.get(HUBSPOT_META_SOURCE, {}).get("deals", 0)
    revenue_google = revenue_by_source.get(HUBSPOT_GOOGLE_SOURCE, {}).get("revenue", 0)
    deals_google = revenue_by_source.get(HUBSPOT_GOOGLE_SOURCE, {}).get("deals", 0)

    return {
        "contacts_total": contacts_total,
        "contacts_meta": contacts_meta,
        "contacts_google": contacts_google,
        "deals_won": deals_won_row["c"],
        "revenue_won": round(deals_won_row["revenue"], 2),
        "revenue_meta": revenue_meta,
        "deals_meta": deals_meta,
        "revenue_google": revenue_google,
        "deals_google": deals_google,
        "revenue_by_source": revenue_by_source,
    }


@app.route("/api/hubspot/kpis")
def api_hubspot_kpis():
    """KPIs principales de HubSpot + comparativa con periodo anterior."""
    days_param = request.args.get("days", "30")
    country = request.args.get("country") or None
    since, until = _hubspot_range_from_request()
    prev_since, prev_until = _hubspot_previous_range(since, until)

    with _get_conn() as conn:
        cur = _hubspot_kpis(conn, since, until, country)
        prev = _hubspot_kpis(conn, prev_since, prev_until, country)
        last_sync = conn.execute(
            "SELECT finished_at FROM hubspot_sync_log WHERE status = 'ok' ORDER BY id DESC LIMIT 1"
        ).fetchone()

    # Solo calculamos delta para metricas escalares (no para revenue_by_source)
    scalar_keys = ["contacts_total", "contacts_meta", "contacts_google",
                   "deals_won", "revenue_won", "revenue_meta", "deals_meta",
                   "revenue_google", "deals_google"]
    deltas = {f"{k}_pct": _delta_pct(cur[k], prev[k]) for k in scalar_keys}
    prev_scalars = {k: prev[k] for k in scalar_keys}

    return jsonify({
        "since": since[:10],
        "until": until[:10],
        "country": country,
        **cur,
        "previous": {
            "since": prev_since[:10],
            "until": prev_until[:10],
            **prev_scalars,
        },
        "deltas": deltas,
        "last_sync": last_sync["finished_at"] if last_sync else None,
    })


def _hubspot_funnel(conn, since_meta, until_meta, since_hs, until_hs, country):
    """Calcula stages + ROAS/CPL_real/CAC del funnel Meta (returns dict)."""
    # Meta spend
    sql = (
        "SELECT COALESCE(SUM(i.spend),0) spend FROM insights_daily i "
        "JOIN campaigns c ON c.id = i.campaign_id WHERE i.date BETWEEN ? AND ?"
    )
    params = [since_meta, until_meta]
    if country:
        sql += " AND c.country = ?"
        params.append(country)
    meta_spend = round(conn.execute(sql, params).fetchone()["spend"], 2)

    # Meta leads de la API
    if country:
        placeholders = ",".join("?" for _ in LEAD_ACTION_TYPES)
        ml = conn.execute(
            f"""
            SELECT COALESCE(SUM(a.value),0) leads
            FROM actions_daily a
            JOIN campaigns c ON c.id = a.campaign_id
            WHERE a.date BETWEEN ? AND ? AND a.action_type IN ({placeholders}) AND c.country = ?
            """,
            (since_meta, until_meta, *LEAD_ACTION_TYPES, country),
        ).fetchone()
        meta_leads = int(ml["leads"] or 0)
    else:
        meta_leads = sum(_fetch_leads_by_campaign(conn, since_meta, until_meta).values())

    contacts_meta = _count_hubspot_leads(
        conn, since_hs, until_hs, source=HUBSPOT_META_SOURCE, country=country
    )

    sql = """
        SELECT COUNT(*) c FROM hubspot_contacts
        WHERE createdate BETWEEN ? AND ?
          AND fuentes_de_captacion_especificas = ?
          AND hs_lead_status IN (
            'Terminado | Compra Web',
            'Terminado | Proyecto ganado',
            'Terminado | Distribuidor convertido en cliente'
          )
    """
    params = [since_hs, until_hs, HUBSPOT_META_SOURCE]
    if country:
        sql += " AND pais = ?"
        params.append(country)
    contacts_meta_won = conn.execute(sql, params).fetchone()["c"]

    sql = """
        SELECT COALESCE(SUM(d.amount), 0) revenue, COUNT(DISTINCT d.id) deals
        FROM hubspot_deals d
        JOIN hubspot_deal_contacts dc ON dc.deal_id = d.id
        JOIN hubspot_contacts c ON c.id = dc.contact_id
        WHERE d.is_won = 1
          AND d.createdate BETWEEN ? AND ?
          AND c.fuentes_de_captacion_especificas = ?
    """
    params = [since_hs, until_hs, HUBSPOT_META_SOURCE]
    if country:
        sql += " AND c.pais = ?"
        params.append(country)
    rev = conn.execute(sql, params).fetchone()
    revenue_meta = round(rev["revenue"], 2)
    deals_meta = rev["deals"]

    return {
        "meta_spend": meta_spend,
        "meta_leads": meta_leads,
        "contacts_meta": contacts_meta,
        "contacts_meta_won": contacts_meta_won,
        "deals_meta": deals_meta,
        "revenue_meta": revenue_meta,
        "roas": round((revenue_meta / meta_spend) if meta_spend else 0, 2),
        "cpl_real": round((meta_spend / contacts_meta) if contacts_meta else 0, 2),
        "cac": round((meta_spend / contacts_meta_won) if contacts_meta_won else 0, 2),
    }


@app.route("/api/hubspot/funnel")
def api_hubspot_funnel():
    """Funnel completo Meta + comparativa con periodo anterior."""
    days_param = request.args.get("days", "30")
    country = request.args.get("country") or None
    since_meta, until_meta, _days = _range_from_request()
    since_hs, until_hs = _hubspot_range_from_request()
    prev_since_meta, prev_until_meta = _previous_range(since_meta, until_meta)
    prev_since_hs, prev_until_hs = _hubspot_previous_range(since_hs, until_hs)

    with _get_conn() as conn:
        cur = _hubspot_funnel(conn, since_meta, until_meta, since_hs, until_hs, country)
        prev = _hubspot_funnel(conn, prev_since_meta, prev_until_meta,
                                prev_since_hs, prev_until_hs, country)

    deltas = {f"{k}_pct": _delta_pct(cur[k], prev[k]) for k in cur}

    return jsonify({
        "since": since_meta,
        "until": until_meta,
        "country": country,
        "stages": [
            {"label": "Spend Meta", "value": cur["meta_spend"], "unit": "EUR"},
            {"label": "Leads Meta (API)", "value": cur["meta_leads"], "unit": ""},
            {"label": "Contactos HS atribuidos a Meta", "value": cur["contacts_meta"], "unit": ""},
            {"label": "Contactos Meta ganados", "value": cur["contacts_meta_won"], "unit": ""},
            {"label": "Deals ganados Meta", "value": cur["deals_meta"], "unit": ""},
            {"label": "Revenue Meta", "value": cur["revenue_meta"], "unit": "EUR"},
        ],
        "roas": cur["roas"],
        "cpl_real": cur["cpl_real"],
        "cac": cur["cac"],
        "previous": {
            "since": prev_since_meta,
            "until": prev_until_meta,
            **prev,
        },
        "deltas": deltas,
    })


@app.route("/api/hubspot/by-source")
def api_hubspot_by_source():
    """Distribucion de contactos y revenue por fuente de captacion. Filtro country opcional."""
    days_param = request.args.get("days", "30")
    country = request.args.get("country") or None
    since, until = _hubspot_range_from_request()

    pais_clause = " AND pais = ?" if country else ""
    pais_clause_c = " AND c.pais = ?" if country else ""
    pais_params = [country] if country else []

    with _get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT COALESCE(fuentes_de_captacion_especificas, '(sin atribucion)') fuente,
                   COUNT(*) contactos
            FROM hubspot_contacts
            WHERE createdate BETWEEN ? AND ?{pais_clause}
            GROUP BY fuentes_de_captacion_especificas
            ORDER BY contactos DESC
            """,
            [since, until, *pais_params],
        ).fetchall()
        contacts_by_source = {r["fuente"]: r["contactos"] for r in rows}

        rev_rows = conn.execute(
            f"""
            SELECT COALESCE(c.fuentes_de_captacion_especificas, '(sin atribucion)') fuente,
                   COALESCE(SUM(d.amount), 0) revenue,
                   COUNT(DISTINCT d.id) deals
            FROM hubspot_deals d
            LEFT JOIN hubspot_deal_contacts dc ON dc.deal_id = d.id
            LEFT JOIN hubspot_contacts c ON c.id = dc.contact_id
            WHERE d.is_won = 1 AND d.createdate BETWEEN ? AND ?{pais_clause_c}
            GROUP BY c.fuentes_de_captacion_especificas
            """,
            [since, until, *pais_params],
        ).fetchall()
        revenue_by_source = {r["fuente"]: {"revenue": round(r["revenue"], 2), "deals": r["deals"]} for r in rev_rows}

        won_rows = conn.execute(
            f"""
            SELECT COALESCE(fuentes_de_captacion_especificas, '(sin atribucion)') fuente,
                   COUNT(*) ganados
            FROM hubspot_contacts
            WHERE createdate BETWEEN ? AND ?
              AND hs_lead_status IN (
                'Terminado | Compra Web',
                'Terminado | Proyecto ganado',
                'Terminado | Distribuidor convertido en cliente'
              ){pais_clause}
            GROUP BY fuentes_de_captacion_especificas
            """,
            [since, until, *pais_params],
        ).fetchall()
        won_by_source = {r["fuente"]: r["ganados"] for r in won_rows}

    out = []
    for fuente, contactos in contacts_by_source.items():
        rev_data = revenue_by_source.get(fuente, {"revenue": 0, "deals": 0})
        ganados = won_by_source.get(fuente, 0)
        conv_rate = (ganados / contactos * 100) if contactos else 0
        out.append({
            "fuente": fuente,
            "contactos": contactos,
            "ganados": ganados,
            "deals_won": rev_data["deals"],
            "revenue": rev_data["revenue"],
            "conv_rate": round(conv_rate, 2),
        })
    return jsonify(out)


@app.route("/api/hubspot/by-status")
def api_hubspot_by_status():
    """Distribucion de contactos por hs_lead_status. Filtro country opcional."""
    days_param = request.args.get("days", "30")
    country = request.args.get("country") or None
    since, until = _hubspot_range_from_request()

    pais_clause = " AND pais = ?" if country else ""
    pais_params = [country] if country else []

    with _get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT COALESCE(hs_lead_status, '(sin estado)') estado, COUNT(*) c
            FROM hubspot_contacts
            WHERE createdate BETWEEN ? AND ?{pais_clause}
            GROUP BY hs_lead_status
            ORDER BY c DESC
            """,
            [since, until, *pais_params],
        ).fetchall()
    return jsonify([{"estado": r["estado"], "contactos": r["c"]} for r in rows])


@app.route("/api/alerts")
def api_alerts():
    """Compara coste por campana entre ultimos 7 dias vs anteriores 7 dias.

    Genera alertas cuando una campana ACTIVA cae mas de un umbral (default 30%).
    Tambien detecta:
    - STOPPED: gasto bajo a 0 (estaba activa)
    - BOOST: gasto subio >100% (positivo, util saberlo)
    """
    threshold_pct = float(request.args.get("threshold", "30"))    # default 30%
    min_spend = float(request.args.get("min_spend", "30"))        # ignorar campanas con <30 EUR de gasto en semana pasada
    country = request.args.get("country") or None

    today = date.today()
    cur_since = (today - timedelta(days=6)).isoformat()       # ultimos 7 dias (incluyendo hoy)
    cur_until = today.isoformat()
    prev_since = (today - timedelta(days=13)).isoformat()     # 7 dias anteriores
    prev_until = (today - timedelta(days=7)).isoformat()

    def _campaign_spend_by_window(table_insights, table_campaigns, since_iso, until_iso):
        sql = (
            f"SELECT c.id, c.name, c.country, c.effective_status status, "
            f"SUM(i.{'spend' if 'meta' in table_insights or table_insights == 'insights_daily' else 'cost'}) sp "
            f"FROM {table_insights} i JOIN {table_campaigns} c ON c.id = i.campaign_id "
            "WHERE i.date BETWEEN ? AND ? "
        )
        params = [since_iso, until_iso]
        if country:
            sql += "AND c.country = ? "
            params.append(country)
        sql += "GROUP BY c.id"
        return sql, params

    def _ga_campaign_spend(since_iso, until_iso):
        sql = (
            "SELECT c.id, c.name, c.country, c.status, "
            "SUM(i.cost) sp FROM google_insights_daily i "
            "JOIN google_campaigns c ON c.id = i.campaign_id "
            "WHERE i.date BETWEEN ? AND ? "
        )
        params = [since_iso, until_iso]
        if country:
            sql += "AND c.country = ? "
            params.append(country)
        sql += "GROUP BY c.id"
        return sql, params

    def _meta_campaign_spend(since_iso, until_iso):
        sql = (
            "SELECT c.id, c.name, c.country, c.effective_status status, "
            "SUM(i.spend) sp FROM insights_daily i "
            "JOIN campaigns c ON c.id = i.campaign_id "
            "WHERE i.date BETWEEN ? AND ? "
        )
        params = [since_iso, until_iso]
        if country:
            sql += "AND c.country = ? "
            params.append(country)
        sql += "GROUP BY c.id"
        return sql, params

    alerts = []
    with _get_conn() as conn:
        for channel, query_fn in (("meta", _meta_campaign_spend), ("google", _ga_campaign_spend)):
            sql_cur, p_cur = query_fn(cur_since, cur_until)
            sql_prev, p_prev = query_fn(prev_since, prev_until)
            cur = {r["id"]: dict(r) for r in conn.execute(sql_cur, p_cur).fetchall()}
            prev = {r["id"]: dict(r) for r in conn.execute(sql_prev, p_prev).fetchall()}
            all_ids = set(cur) | set(prev)
            for cid in all_ids:
                row_cur = cur.get(cid, {})
                row_prev = prev.get(cid, {})
                sp_cur = row_cur.get("sp") or 0
                sp_prev = row_prev.get("sp") or 0
                # Necesitamos al menos `min_spend` en alguna ventana para evitar ruido
                if max(sp_cur, sp_prev) < min_spend:
                    continue
                # Calcular cambio
                if sp_prev == 0:
                    change = float("inf") if sp_cur > 0 else 0
                else:
                    change = (sp_cur - sp_prev) / sp_prev * 100

                meta_row = row_cur if cid in cur else row_prev
                severity = None
                alert_type = None
                if sp_cur == 0 and sp_prev >= min_spend:
                    severity = "critical"
                    alert_type = "STOPPED"
                elif change <= -50:
                    severity = "critical"
                    alert_type = "DROP"
                elif change <= -threshold_pct:
                    severity = "warning"
                    alert_type = "DROP"
                elif change >= 100 and sp_cur >= min_spend:
                    severity = "boost"
                    alert_type = "BOOST"

                if severity is None:
                    continue

                alerts.append({
                    "channel": channel,
                    "campaign_id": cid,
                    "campaign_name": meta_row.get("name") or "(sin nombre)",
                    "country": meta_row.get("country"),
                    "status": meta_row.get("status"),
                    "spend_current": round(sp_cur, 2),
                    "spend_previous": round(sp_prev, 2),
                    "change_pct": round(change, 1) if change != float("inf") else None,
                    "severity": severity,
                    "type": alert_type,
                })

    # Ordenar: critical primero, luego por cambio absoluto descendente
    severity_rank = {"critical": 0, "warning": 1, "boost": 2}
    alerts.sort(key=lambda a: (severity_rank[a["severity"]], -(abs(a["change_pct"]) if a["change_pct"] is not None else 999)))

    return jsonify({
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "current_period": f"{cur_since} - {cur_until}",
        "previous_period": f"{prev_since} - {prev_until}",
        "threshold_pct": threshold_pct,
        "min_spend": min_spend,
        "count": len(alerts),
        "alerts": alerts,
    })


@app.route("/api/countries")
def api_countries():
    """Devuelve la lista de paises disponibles (campaigns Meta + Google + hubspot_contacts)."""
    with _get_conn() as conn:
        from_meta = {r["country"] for r in conn.execute(
            "SELECT DISTINCT country FROM campaigns WHERE country IS NOT NULL AND country != ''"
        ).fetchall()}
        from_google = {r["country"] for r in conn.execute(
            "SELECT DISTINCT country FROM google_campaigns WHERE country IS NOT NULL AND country != ''"
        ).fetchall()}
        from_hubspot = {r["pais"] for r in conn.execute(
            "SELECT DISTINCT pais FROM hubspot_contacts WHERE pais IS NOT NULL AND pais != ''"
        ).fetchall()}
    available = {c for c in (from_meta | from_google | from_hubspot) if c}
    ordered = [c for c in SUPPORTED_COUNTRIES if c in available] + sorted(c for c in available if c not in SUPPORTED_COUNTRIES)
    return jsonify(ordered)


@app.route("/api/hubspot/by-country")
def api_hubspot_by_country():
    """Top paises por contactos."""
    days_param = request.args.get("days", "30")
    since, until = _hubspot_range_from_request()

    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT COALESCE(pais, '(sin pais)') pais, COUNT(*) c
            FROM hubspot_contacts
            WHERE createdate BETWEEN ? AND ?
            GROUP BY pais
            ORDER BY c DESC
            LIMIT 15
            """,
            (since, until),
        ).fetchall()
    return jsonify([{"pais": r["pais"], "contactos": r["c"]} for r in rows])


# ====================================================================
# Vista semanal/mensual estilo Excel - matriz completa
# ====================================================================

WON_LEAD_STATUSES = (
    "Terminado | Compra Web",
    "Terminado | Proyecto ganado",
    "Terminado | Distribuidor convertido en cliente",
)


def _period_partial_info(period_key, since_iso, until_iso, granularity):
    """Para un bucket (semana/mes), calcula si esta parcialmente cubierto por
    el rango pedido. Devuelve (is_partial, days_covered, days_total).

    Util para marcar visualmente buckets parciales cuando el rango no
    coincide con bordes naturales (ej. 90 dias = corta el primer mes).
    """
    s = date.fromisoformat(since_iso)
    u = date.fromisoformat(until_iso)
    k = date.fromisoformat(period_key)
    if granularity == "daily":
        return False, 1, 1
    if granularity == "weekly":
        natural_start = k
        natural_end = k + timedelta(days=6)
    else:  # monthly
        natural_start = k
        if k.month == 12:
            next_m = date(k.year + 1, 1, 1)
        else:
            next_m = date(k.year, k.month + 1, 1)
        natural_end = next_m - timedelta(days=1)
    covered_start = max(natural_start, s)
    covered_end = min(natural_end, u)
    if covered_end < covered_start:
        return True, 0, (natural_end - natural_start).days + 1
    days_covered = (covered_end - covered_start).days + 1
    days_total = (natural_end - natural_start).days + 1
    return days_covered < days_total, days_covered, days_total


def _periods_with_partial_info(since_iso, until_iso, granularity):
    """Como _generate_periods pero devuelve objetos dict con info de parcialidad
    para que el frontend pueda marcar visualmente los buckets incompletos."""
    out = []
    for k, l in _generate_periods(since_iso, until_iso, granularity):
        is_partial, days_cov, days_tot = _period_partial_info(k, since_iso, until_iso, granularity)
        out.append({
            "key": k,
            "label": l,
            "is_partial": is_partial,
            "days_covered": days_cov,
            "days_total": days_tot,
        })
    return out


def _generate_periods(since_iso, until_iso, granularity):
    """Genera lista [(key, label)] de periodos (lunes/primeros de mes/dias) en el rango."""
    s = date.fromisoformat(since_iso)
    u = date.fromisoformat(until_iso)
    out = []

    if granularity == "monthly":
        cur = date(s.year, s.month, 1)
        while cur <= u:
            month_names = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
            label = f"{month_names[cur.month - 1]} {cur.year}"
            out.append((cur.isoformat(), label))
            if cur.month == 12:
                cur = date(cur.year + 1, 1, 1)
            else:
                cur = date(cur.year, cur.month + 1, 1)
    elif granularity == "weekly":
        # Lunes de la semana que contiene 'since'
        cur = s - timedelta(days=s.weekday())
        while cur <= u:
            label = f"Sem {cur.strftime('%d/%m')}"
            out.append((cur.isoformat(), label))
            cur = cur + timedelta(days=7)
    else:  # daily
        cur = s
        while cur <= u:
            label = cur.strftime('%d/%m')
            out.append((cur.isoformat(), label))
            cur = cur + timedelta(days=1)

    return out


@app.route("/api/weekly")
def api_weekly():
    """Matriz semanal/mensual estilo Excel: una columna por periodo + acumulado.

    Bloques: Inversion / Leads / CPL / Cerrados / Tasa exito / CAC / Ventas / ROAS.
    Filtros: country (pais) y granularity (daily/weekly/monthly).
    """
    days_param = request.args.get("days", "30")
    country = request.args.get("country") or None
    granularity = request.args.get("granularity", "weekly")
    if granularity not in ("daily", "weekly", "monthly"):
        granularity = "weekly"

    since, until, _days = _range_from_request()
    since_hs = _date_to_hubspot_iso(since)
    until_hs = _date_to_hubspot_iso(until, end=True)

    periods = _generate_periods(since, until, granularity)
    period_keys = [p[0] for p in periods]
    period_labels = [p[1] for p in periods]
    period_idx = {k: i for i, k in enumerate(period_keys)}
    n = len(periods)

    period_expr_meta = _period_expr(granularity)
    period_expr_hs = _hubspot_period_expr(granularity)
    period_expr_hs_deal = period_expr_hs.replace("createdate", "d.createdate")

    # Inicializar buckets
    spend_meta = [0.0] * n
    spend_google = [0.0] * n
    leads_meta = [0] * n
    leads_google = [0] * n
    leads_other = [0] * n
    cerrados = [0] * n
    deals_won = [0] * n
    revenue = [0.0] * n

    pais_clause = " AND pais = ?" if country else ""
    pais_clause_c = " AND c.pais = ?" if country else ""
    pais_params = [country] if country else []

    with _get_conn() as conn:
        # 1a. Spend Meta por periodo (filtrado por country)
        sql = (
            f"SELECT {period_expr_meta} p, SUM(i.spend) s "
            "FROM insights_daily i JOIN campaigns c ON c.id = i.campaign_id "
            "WHERE i.date BETWEEN ? AND ?"
        )
        params = [since, until]
        if country:
            sql += " AND c.country = ?"
            params.append(country)
        sql += " GROUP BY p"
        for r in conn.execute(sql, params):
            i = period_idx.get(r["p"])
            if i is not None:
                spend_meta[i] = r["s"] or 0

        # 1b. Spend Google por periodo (filtrado por country)
        sql_g = (
            f"SELECT {period_expr_meta} p, SUM(i.cost) s "
            "FROM google_insights_daily i JOIN google_campaigns c ON c.id = i.campaign_id "
            "WHERE i.date BETWEEN ? AND ?"
        )
        params_g = [since, until]
        if country:
            sql_g += " AND c.country = ?"
            params_g.append(country)
        sql_g += " GROUP BY p"
        for r in conn.execute(sql_g, params_g):
            i = period_idx.get(r["p"])
            if i is not None:
                spend_google[i] = r["s"] or 0

        # 2. Leads HubSpot por periodo y fuente
        sql = (
            f"SELECT {period_expr_hs} p, fuentes_de_captacion_especificas f, COUNT(*) c "
            f"FROM hubspot_contacts WHERE createdate BETWEEN ? AND ?{pais_clause} "
            "GROUP BY p, f"
        )
        for r in conn.execute(sql, [since_hs, until_hs, *pais_params]):
            i = period_idx.get(r["p"])
            if i is None:
                continue
            f = r["f"]
            c = r["c"]
            if f == HUBSPOT_META_SOURCE:
                leads_meta[i] += c
            elif f == HUBSPOT_GOOGLE_SOURCE:
                leads_google[i] += c
            else:
                leads_other[i] += c

        # 3. Cerrados (clientes ganados) por periodo
        won_placeholders = ",".join("?" for _ in WON_LEAD_STATUSES)
        sql = (
            f"SELECT {period_expr_hs} p, COUNT(*) c FROM hubspot_contacts "
            f"WHERE createdate BETWEEN ? AND ? AND hs_lead_status IN ({won_placeholders}){pais_clause} "
            "GROUP BY p"
        )
        for r in conn.execute(sql, [since_hs, until_hs, *WON_LEAD_STATUSES, *pais_params]):
            i = period_idx.get(r["p"])
            if i is not None:
                cerrados[i] = r["c"]

        # 4. Deals won + revenue por periodo
        if country:
            sql = (
                f"SELECT {period_expr_hs_deal} p, COUNT(DISTINCT d.id) c, COALESCE(SUM(d.amount), 0) rev "
                "FROM hubspot_deals d "
                "JOIN hubspot_deal_contacts dc ON dc.deal_id = d.id "
                "JOIN hubspot_contacts c ON c.id = dc.contact_id "
                "WHERE d.is_won = 1 AND d.createdate BETWEEN ? AND ? AND c.pais = ? "
                "GROUP BY p"
            )
            params = [since_hs, until_hs, country]
        else:
            sql = (
                f"SELECT {period_expr_hs.replace('createdate', 'createdate')} p, "
                "COUNT(*) c, COALESCE(SUM(amount), 0) rev "
                "FROM hubspot_deals WHERE is_won = 1 AND createdate BETWEEN ? AND ? "
                "GROUP BY p"
            )
            params = [since_hs, until_hs]
        for r in conn.execute(sql, params):
            i = period_idx.get(r["p"])
            if i is not None:
                deals_won[i] = r["c"]
                revenue[i] = r["rev"] or 0

    # Calcular metricas derivadas
    leads_total = [leads_meta[i] + leads_google[i] + leads_other[i] for i in range(n)]
    spend_total = [spend_meta[i] + spend_google[i] for i in range(n)]
    cpl_total = [(spend_total[i] / leads_total[i]) if leads_total[i] else 0 for i in range(n)]
    cpl_meta = [(spend_meta[i] / leads_meta[i]) if leads_meta[i] else 0 for i in range(n)]
    cpl_google = [(spend_google[i] / leads_google[i]) if leads_google[i] else 0 for i in range(n)]
    tasa_exito = [(cerrados[i] / leads_total[i] * 100) if leads_total[i] else 0 for i in range(n)]
    cac = [(spend_total[i] / cerrados[i]) if cerrados[i] else 0 for i in range(n)]
    roas = [(revenue[i] / spend_total[i]) if spend_total[i] else 0 for i in range(n)]

    # Acumulados (totales del rango)
    sum_spend_meta = sum(spend_meta)
    sum_spend_google = sum(spend_google)
    sum_spend_total = sum_spend_meta + sum_spend_google
    sum_leads_meta = sum(leads_meta)
    sum_leads_google = sum(leads_google)
    sum_leads_other = sum(leads_other)
    sum_leads_total = sum(leads_total)
    sum_cerrados = sum(cerrados)
    sum_revenue = sum(revenue)
    tot_cpl_total = (sum_spend_total / sum_leads_total) if sum_leads_total else 0
    tot_cpl_meta = (sum_spend_meta / sum_leads_meta) if sum_leads_meta else 0
    tot_cpl_google = (sum_spend_google / sum_leads_google) if sum_leads_google else 0
    tot_tasa = (sum_cerrados / sum_leads_total * 100) if sum_leads_total else 0
    tot_cac = (sum_spend_total / sum_cerrados) if sum_cerrados else 0
    tot_roas = (sum_revenue / sum_spend_total) if sum_spend_total else 0

    # === Drill-down por país: cargamos por (country, period) las mismas
    # metricas y derivamos CPL/Tasa/CAC/ROAS por país. Solo aplica a los rows
    # base (no metricas derivadas) - las derivadas las calculamos a partir
    # de los bases por país.
    spend_meta_bc = {}      # {country: [n]}
    spend_google_bc = {}
    leads_meta_bc = {}
    leads_google_bc = {}
    leads_other_bc = {}
    cerrados_bc = {}
    deals_won_bc = {}
    revenue_bc = {}

    def _bc_add(d, country, idx, value):
        if not country:
            return
        if country not in d:
            d[country] = [0] * n
        d[country][idx] = (d[country][idx] or 0) + (value or 0)

    with _get_conn() as conn:
        sql = (
            f"SELECT c.country country, {period_expr_meta} p, SUM(i.spend) s "
            "FROM insights_daily i JOIN campaigns c ON c.id = i.campaign_id "
            "WHERE i.date BETWEEN ? AND ?"
        )
        params = [since, until]
        if country:
            sql += " AND c.country = ?"
            params.append(country)
        sql += " GROUP BY c.country, p"
        for r in conn.execute(sql, params):
            i = period_idx.get(r["p"])
            if i is None: continue
            _bc_add(spend_meta_bc, r["country"], i, r["s"])

        sql_g = (
            f"SELECT c.country country, {period_expr_meta} p, SUM(i.cost) s "
            "FROM google_insights_daily i JOIN google_campaigns c ON c.id = i.campaign_id "
            "WHERE i.date BETWEEN ? AND ?"
        )
        params_g = [since, until]
        if country:
            sql_g += " AND c.country = ?"
            params_g.append(country)
        sql_g += " GROUP BY c.country, p"
        for r in conn.execute(sql_g, params_g):
            i = period_idx.get(r["p"])
            if i is None: continue
            _bc_add(spend_google_bc, r["country"], i, r["s"])

        sql = (
            f"SELECT pais country, {period_expr_hs} p, fuentes_de_captacion_especificas f, COUNT(*) c "
            f"FROM hubspot_contacts WHERE createdate BETWEEN ? AND ?{pais_clause} "
            "GROUP BY pais, p, f"
        )
        for r in conn.execute(sql, [since_hs, until_hs, *pais_params]):
            i = period_idx.get(r["p"])
            if i is None: continue
            f = r["f"]
            if f == HUBSPOT_META_SOURCE:
                _bc_add(leads_meta_bc, r["country"], i, r["c"])
            elif f == HUBSPOT_GOOGLE_SOURCE:
                _bc_add(leads_google_bc, r["country"], i, r["c"])
            else:
                _bc_add(leads_other_bc, r["country"], i, r["c"])

        won_placeholders = ",".join("?" for _ in WON_LEAD_STATUSES)
        sql = (
            f"SELECT pais country, {period_expr_hs} p, COUNT(*) c FROM hubspot_contacts "
            f"WHERE createdate BETWEEN ? AND ? AND hs_lead_status IN ({won_placeholders}){pais_clause} "
            "GROUP BY pais, p"
        )
        for r in conn.execute(sql, [since_hs, until_hs, *WON_LEAD_STATUSES, *pais_params]):
            i = period_idx.get(r["p"])
            if i is None: continue
            _bc_add(cerrados_bc, r["country"], i, r["c"])

        # Deals ganados + revenue por (pais, periodo): join via contacts
        sql = (
            f"SELECT c.pais country, {period_expr_hs_deal} p, "
            "COUNT(DISTINCT d.id) c, COALESCE(SUM(d.amount), 0) rev "
            "FROM hubspot_deals d "
            "JOIN hubspot_deal_contacts dc ON dc.deal_id = d.id "
            "JOIN hubspot_contacts c ON c.id = dc.contact_id "
            "WHERE d.is_won = 1 AND d.createdate BETWEEN ? AND ?"
            + (" AND c.pais = ?" if country else "")
            + " GROUP BY c.pais, p"
        )
        params = [since_hs, until_hs] + ([country] if country else [])
        for r in conn.execute(sql, params):
            i = period_idx.get(r["p"])
            if i is None: continue
            _bc_add(deals_won_bc, r["country"], i, r["c"])
            _bc_add(revenue_bc, r["country"], i, r["rev"])

    # Conjunto de paises observados en cualquiera de las metricas
    all_countries = set()
    for d in (spend_meta_bc, spend_google_bc, leads_meta_bc, leads_google_bc,
              leads_other_bc, cerrados_bc, deals_won_bc, revenue_bc):
        all_countries.update(d.keys())

    def _vals(d, c):
        return d.get(c) or [0] * n

    # Build derived bases por pais para CPL/Tasa/CAC/ROAS por pais
    spend_total_bc = {c: [_vals(spend_meta_bc, c)[i] + _vals(spend_google_bc, c)[i] for i in range(n)] for c in all_countries}
    leads_total_bc = {c: [_vals(leads_meta_bc, c)[i] + _vals(leads_google_bc, c)[i] + _vals(leads_other_bc, c)[i] for i in range(n)] for c in all_countries}
    cpl_total_bc = {c: [(spend_total_bc[c][i] / leads_total_bc[c][i]) if leads_total_bc[c][i] else 0 for i in range(n)] for c in all_countries}
    cpl_meta_bc = {c: [(_vals(spend_meta_bc, c)[i] / _vals(leads_meta_bc, c)[i]) if _vals(leads_meta_bc, c)[i] else 0 for i in range(n)] for c in all_countries}
    cpl_google_bc = {c: [(_vals(spend_google_bc, c)[i] / _vals(leads_google_bc, c)[i]) if _vals(leads_google_bc, c)[i] else 0 for i in range(n)] for c in all_countries}
    tasa_exito_bc = {c: [(_vals(cerrados_bc, c)[i] / leads_total_bc[c][i] * 100) if leads_total_bc[c][i] else 0 for i in range(n)] for c in all_countries}
    cac_bc = {c: [(spend_total_bc[c][i] / _vals(cerrados_bc, c)[i]) if _vals(cerrados_bc, c)[i] else 0 for i in range(n)] for c in all_countries}
    roas_bc = {c: [(_vals(revenue_bc, c)[i] / spend_total_bc[c][i]) if spend_total_bc[c][i] else 0 for i in range(n)] for c in all_countries}

    def _by_country(data_bc, totals_func=None, sort_key=None):
        """Convierte un dict {country: [n]} en lista de dicts ordenada por total desc.
        totals_func opcional: si se pasa, calcula el total desde valores; si no, suma."""
        items = []
        for c in all_countries:
            vals = _vals(data_bc, c)
            total = totals_func(c) if totals_func else sum(vals)
            items.append({
                "label": c,
                "values": [round(v, 2) for v in vals],
                "total": round(total, 2),
            })
        items.sort(key=sort_key or (lambda x: -x["total"]))
        return items

    # Totales por pais para las metricas derivadas (recalculadas desde acumulado)
    def _sum_country(d):
        return lambda c: sum(_vals(d, c))
    def _ratio_country(num_d, den_d, factor=1.0):
        def fn(c):
            num_total = sum(_vals(num_d, c))
            den_total = sum(_vals(den_d, c))
            return (num_total / den_total * factor) if den_total else 0
        return fn

    cpl_total_country = _ratio_country(spend_total_bc, leads_total_bc)
    cpl_meta_country = _ratio_country(spend_meta_bc, leads_meta_bc)
    cpl_google_country = _ratio_country(spend_google_bc, leads_google_bc)
    tasa_country = _ratio_country(cerrados_bc, leads_total_bc, factor=100)
    cac_country = _ratio_country(spend_total_bc, cerrados_bc)
    roas_country = _ratio_country(revenue_bc, spend_total_bc)

    def row(label, vals, total, fmt, indent=False, header=False, note=None, by_country=None):
        return {"label": label, "values": [round(v, 2) for v in vals], "total": round(total, 2),
                "format": fmt, "indent": indent, "header": header, "note": note,
                "by_country": by_country}

    sections = [
        {
            "title": "Inversión por canales",
            "rows": [
                row("Inversión total", spend_total, sum_spend_total, "eur", header=True,
                    by_country=_by_country(spend_total_bc)),
                row("Meta Ads", spend_meta, sum_spend_meta, "eur", indent=True,
                    by_country=_by_country(spend_meta_bc)),
                row("Google Ads", spend_google, sum_spend_google, "eur", indent=True,
                    by_country=_by_country(spend_google_bc)),
            ],
        },
        {
            "title": "Número de leads nuevos",
            "rows": [
                row("Leads totales", leads_total, sum_leads_total, "int", header=True,
                    by_country=_by_country(leads_total_bc)),
                row("Meta", leads_meta, sum_leads_meta, "int", indent=True,
                    by_country=_by_country(leads_meta_bc)),
                row("Google", leads_google, sum_leads_google, "int", indent=True,
                    by_country=_by_country(leads_google_bc)),
                row("Desconocido / Otros", leads_other, sum_leads_other, "int", indent=True,
                    by_country=_by_country(leads_other_bc)),
            ],
        },
        {
            "title": "CPL (Coste por Lead)",
            "rows": [
                row("CPL total", cpl_total, tot_cpl_total, "eur", header=True,
                    by_country=_by_country(cpl_total_bc, totals_func=cpl_total_country)),
                row("Meta", cpl_meta, tot_cpl_meta, "eur", indent=True,
                    by_country=_by_country(cpl_meta_bc, totals_func=cpl_meta_country)),
                row("Google", cpl_google, tot_cpl_google, "eur", indent=True,
                    by_country=_by_country(cpl_google_bc, totals_func=cpl_google_country)),
            ],
        },
        {
            "title": "Conversion",
            "rows": [
                row("Cerrados (convertidos en cliente)", cerrados, sum_cerrados, "int",
                    by_country=_by_country(cerrados_bc)),
                row("Tasa de éxito (Lead -> Cliente)", tasa_exito, tot_tasa, "pct",
                    by_country=_by_country(tasa_exito_bc, totals_func=tasa_country)),
                row("CAC (Coste de adquisición)", cac, tot_cac, "eur",
                    by_country=_by_country(cac_bc, totals_func=cac_country)),
            ],
        },
        {
            "title": "Revenue (Ventas netas HubSpot)",
            "rows": [
                row("Ventas netas", revenue, sum_revenue, "eur", header=True,
                    by_country=_by_country(revenue_bc)),
                row("Deals ganados", deals_won, sum(deals_won), "int", indent=True,
                    by_country=_by_country(deals_won_bc)),
                row("ROAS (Revenue / Inversión)", roas, tot_roas, "x",
                    by_country=_by_country(roas_bc, totals_func=roas_country)),
            ],
        },
    ]

    return jsonify({
        "since": since,
        "until": until,
        "country": country,
        "granularity": granularity,
        "periods": _periods_with_partial_info(since, until, granularity),
        "totals_label": "Acumulado",
        "sections": sections,
    })


# ====================================================================
# Google Ads endpoints
# ====================================================================

def _google_kpis(conn, since, until, country):
    sql = (
        "SELECT SUM(i.cost) cost, SUM(i.impressions) impressions, "
        "SUM(i.clicks) clicks, SUM(i.conversions) conversions, "
        "SUM(i.conversion_value) revenue "
        "FROM google_insights_daily i JOIN google_campaigns c ON c.id = i.campaign_id "
        "WHERE i.date BETWEEN ? AND ?"
    )
    params = [since, until]
    if country:
        sql += " AND c.country = ?"
        params.append(country)
    r = conn.execute(sql, params).fetchone()
    cost = r["cost"] or 0
    impressions = r["impressions"] or 0
    clicks = r["clicks"] or 0
    conversions = r["conversions"] or 0
    revenue = r["revenue"] or 0
    return {
        "cost": round(cost, 2),
        "impressions": impressions,
        "clicks": clicks,
        "conversions": round(conversions, 2),
        "revenue": round(revenue, 2),
        "ctr": round((clicks / impressions * 100) if impressions else 0, 2),
        "cpc": round((cost / clicks) if clicks else 0, 3),
        "cpm": round((cost / impressions * 1000) if impressions else 0, 2),
        "roas": round((revenue / cost) if cost else 0, 2),
        "cpa": round((cost / conversions) if conversions else 0, 2),
    }


@app.route("/api/google/kpis")
def api_google_kpis():
    """KPIs de Google Ads + comparativa periodo anterior."""
    days_param = request.args.get("days", "30")
    country = request.args.get("country") or None
    since, until, days = _range_from_request()
    prev_since, prev_until = _previous_range(since, until)

    with _get_conn() as conn:
        cur = _google_kpis(conn, since, until, country)
        prev = _google_kpis(conn, prev_since, prev_until, country)
        last_sync = conn.execute(
            "SELECT finished_at FROM google_sync_log WHERE status='ok' ORDER BY id DESC LIMIT 1"
        ).fetchone()

    deltas = {f"{k}_pct": _delta_pct(cur[k], prev[k]) for k in cur}

    return jsonify({
        "since": since,
        "until": until,
        "days": days,
        "country": country,
        **cur,
        "previous": {"since": prev_since, "until": prev_until, **prev},
        "deltas": deltas,
        "last_sync": last_sync["finished_at"] if last_sync else None,
    })


@app.route("/api/google/campaigns")
def api_google_campaigns():
    """Tabla de campanas Google con metricas agregadas."""
    days_param = request.args.get("days", "30")
    country = request.args.get("country") or None
    since, until, _days = _range_from_request()

    sql = (
        "SELECT c.id, c.name, c.status, c.advertising_channel_type, c.country, "
        "SUM(i.cost) cost, SUM(i.impressions) impressions, "
        "SUM(i.clicks) clicks, SUM(i.conversions) conversions, "
        "SUM(i.conversion_value) revenue "
        "FROM google_campaigns c "
        "LEFT JOIN google_insights_daily i ON i.campaign_id = c.id AND i.date BETWEEN ? AND ? "
    )
    params = [since, until]
    if country:
        sql += "WHERE c.country = ? "
        params.append(country)
    sql += "GROUP BY c.id ORDER BY cost DESC NULLS LAST"

    with _get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()

    out = []
    for r in rows:
        cost = r["cost"] or 0
        impressions = r["impressions"] or 0
        clicks = r["clicks"] or 0
        conversions = r["conversions"] or 0
        revenue = r["revenue"] or 0
        out.append({
            "id": r["id"],
            "name": r["name"],
            "status": r["status"],
            "channel_type": r["advertising_channel_type"],
            "country": r["country"],
            "cost": round(cost, 2),
            "impressions": impressions,
            "clicks": clicks,
            "ctr": round((clicks / impressions * 100) if impressions else 0, 2),
            "cpc": round((cost / clicks) if clicks else 0, 3),
            "conversions": round(conversions, 2),
            "revenue": round(revenue, 2),
            "cpa": round((cost / conversions) if conversions else 0, 2),
            "roas": round((revenue / cost) if cost else 0, 2),
        })
    return jsonify(out)


def _google_channel_comparison(channel_type: str):
    """Helper compartido por Shopping y Search. Devuelve el payload JSON para
    el comparativo por pais filtrado por el canal solicitado (SHOPPING | SEARCH).
    Refactor: la logica original era especifica de Shopping; ahora se parametriza
    por channel_type para que Search reutilice el mismo codigo.
    """
    granularity = request.args.get("granularity", "weekly")
    if granularity not in ("daily", "weekly", "monthly"):
        granularity = "weekly"

    since, until, _days = _range_from_request()
    periods = _generate_periods(since, until, granularity)
    period_keys = [p[0] for p in periods]
    period_idx = {k: i for i, k in enumerate(period_keys)}
    n = len(periods)
    period_expr = _period_expr(granularity)

    with _get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT c.country country,
                   {period_expr} period,
                   SUM(i.cost) cost,
                   SUM(i.clicks) clicks,
                   SUM(i.impressions) impressions
            FROM google_insights_daily i
            JOIN google_campaigns c ON c.id = i.campaign_id
            WHERE c.advertising_channel_type = ?
              AND i.date BETWEEN ? AND ?
            GROUP BY c.country, period
            ORDER BY c.country, period
            """,
            (channel_type, since, until),
        ).fetchall()

        # Presupuesto por (pais, periodo) usando histórico
        period_expr_bh = _period_expr(granularity, "bh.date")
        budget_period_rows_ts = conn.execute(
            f"""
            SELECT c.country country,
                   {period_expr_bh} period,
                   SUM(bh.daily_budget) total_budget,
                   AVG(bh.daily_budget) avg_daily_budget,
                   COUNT(DISTINCT bh.date) days_in_period
            FROM google_budget_history bh
            JOIN google_campaigns c ON c.id = bh.campaign_id
            WHERE c.advertising_channel_type = ?
              AND c.status = 'ENABLED'
              AND bh.date BETWEEN ? AND ?
            GROUP BY c.country, period
            ORDER BY c.country, period
            """,
            (channel_type, since, until),
        ).fetchall()

        # Presupuesto diario actual total por pais (solo campañas ENABLED del canal).
        # Usado como referencia y para fallback si no hay historico.
        budget_rows = conn.execute(
            """
            SELECT country, SUM(daily_budget) daily_total
            FROM google_campaigns
            WHERE advertising_channel_type = ?
              AND status = 'ENABLED'
              AND daily_budget IS NOT NULL
            GROUP BY country
            """,
            (channel_type,),
        ).fetchall()
        budget_daily_by_country = {r["country"]: (r["daily_total"] or 0) for r in budget_rows}

        # Presupuesto REAL del periodo: suma diaria desde google_budget_history.
        # Cubre los cambios de budget aplicados durante el rango.
        # Filtramos por status=ENABLED actual: si la campaña está pausada hoy,
        # asumimos que no estaba contribuyendo presupuesto efectivo (limitacion
        # conocida: no tenemos histórico de status).
        budget_period_rows = conn.execute(
            """
            SELECT c.country, SUM(bh.daily_budget) total_budget,
                   COUNT(DISTINCT bh.date) days_covered
            FROM google_budget_history bh
            JOIN google_campaigns c ON c.id = bh.campaign_id
            WHERE c.advertising_channel_type = ?
              AND c.status = 'ENABLED'
              AND bh.date BETWEEN ? AND ?
            GROUP BY c.country
            """,
            (channel_type, since, until),
        ).fetchall()
        budget_period_by_country = {
            r["country"]: {"total": r["total_budget"] or 0, "days": r["days_covered"] or 0}
            for r in budget_period_rows
        }

    by_country = {}
    for r in rows:
        country = r["country"] or "(sin pais)"
        if country not in by_country:
            by_country[country] = {
                "cost": [0.0] * n, "clicks": [0] * n, "impressions": [0] * n,
                "daily_budget": [0.0] * n, "budget_period": [0.0] * n,
            }
        i = period_idx.get(r["period"])
        if i is None:
            continue
        by_country[country]["cost"][i] = r["cost"] or 0
        by_country[country]["clicks"][i] = r["clicks"] or 0
        by_country[country]["impressions"][i] = r["impressions"] or 0

    # Rellenar daily_budget y budget_period por (pais, periodo)
    for r in budget_period_rows_ts:
        country = r["country"] or "(sin pais)"
        if country not in by_country:
            by_country[country] = {
                "cost": [0.0] * n, "clicks": [0] * n, "impressions": [0] * n,
                "daily_budget": [0.0] * n, "budget_period": [0.0] * n,
            }
        i = period_idx.get(r["period"])
        if i is None:
            continue
        by_country[country]["daily_budget"][i] = r["avg_daily_budget"] or 0
        by_country[country]["budget_period"][i] = r["total_budget"] or 0

    # Ordenar paises por gasto total descendente
    countries = sorted(by_country.keys(), key=lambda c: -sum(by_country[c]["cost"]))

    # Numero de dias del rango (para multiplicar daily_budget)
    days_in_range = (date.fromisoformat(until) - date.fromisoformat(since)).days + 1

    series = {"cost": {}, "ctr": {}, "cpc": {}, "clicks": {}, "impressions": {},
              "daily_budget": {}, "budget_period": {}, "utilization": {}}
    totals = {}
    for c in countries:
        d = by_country[c]
        series["cost"][c] = [round(v, 2) for v in d["cost"]]
        series["clicks"][c] = d["clicks"]
        series["impressions"][c] = d["impressions"]
        series["ctr"][c] = [
            round((d["clicks"][i] / d["impressions"][i] * 100) if d["impressions"][i] else 0, 2)
            for i in range(n)
        ]
        series["cpc"][c] = [
            round((d["cost"][i] / d["clicks"][i]) if d["clicks"][i] else 0, 3)
            for i in range(n)
        ]
        series["daily_budget"][c] = [round(v, 2) for v in d["daily_budget"]]
        series["budget_period"][c] = [round(v, 2) for v in d["budget_period"]]
        series["utilization"][c] = [
            round((d["cost"][i] / d["budget_period"][i] * 100) if d["budget_period"][i] > 0 else 0, 1)
            for i in range(n)
        ]
        total_cost = sum(d["cost"])
        total_clicks = sum(d["clicks"])
        total_imp = sum(d["impressions"])
        daily_budget = budget_daily_by_country.get(c, 0) or 0
        # Presupuesto del periodo: usa historico real si hay datos suficientes,
        # sino fallback al daily_budget actual x dias del rango.
        period_data = budget_period_by_country.get(c)
        if period_data and period_data["days"] >= days_in_range * 0.5:
            # Tenemos al menos 50% de cobertura historica: usamos suma real
            budget_period = period_data["total"]
            budget_source = "historical" if period_data["days"] >= days_in_range * 0.9 else "partial_historical"
        elif daily_budget > 0:
            budget_period = daily_budget * days_in_range
            budget_source = "projected"
        else:
            budget_period = 0
            budget_source = None
        utilization = (total_cost / budget_period * 100) if budget_period > 0 else None
        totals[c] = {
            "cost": round(total_cost, 2),
            "clicks": total_clicks,
            "impressions": total_imp,
            "ctr": round((total_clicks / total_imp * 100) if total_imp else 0, 2),
            "cpc": round((total_cost / total_clicks) if total_clicks else 0, 3),
            "daily_budget": round(daily_budget, 2),
            "budget_period": round(budget_period, 2) if budget_period > 0 else None,
            "budget_source": budget_source,
            "utilization_pct": round(utilization, 1) if utilization is not None else None,
        }

    # === Comparativa con periodo anterior (misma duracion, inmediatamente antes) ===
    prev_since, prev_until = _previous_range(since, until)
    prev_days = (date.fromisoformat(prev_until) - date.fromisoformat(prev_since)).days + 1
    with _get_conn() as conn:
        prev_cost_rows = conn.execute(
            """
            SELECT c.country country,
                   SUM(i.cost) cost,
                   SUM(i.clicks) clicks,
                   SUM(i.impressions) impressions
            FROM google_insights_daily i
            JOIN google_campaigns c ON c.id = i.campaign_id
            WHERE c.advertising_channel_type = ?
              AND i.date BETWEEN ? AND ?
            GROUP BY c.country
            """,
            (channel_type, prev_since, prev_until),
        ).fetchall()
        prev_budget_rows = conn.execute(
            """
            SELECT c.country country,
                   SUM(bh.daily_budget) total_budget,
                   AVG(bh.daily_budget) avg_daily_budget,
                   COUNT(DISTINCT bh.date) days_in_period
            FROM google_budget_history bh
            JOIN google_campaigns c ON c.id = bh.campaign_id
            WHERE c.advertising_channel_type = ?
              AND c.status = 'ENABLED'
              AND bh.date BETWEEN ? AND ?
            GROUP BY c.country
            """,
            (channel_type, prev_since, prev_until),
        ).fetchall()
    prev_by_country = {r["country"]: dict(r) for r in prev_cost_rows}
    prev_budget_by_country = {r["country"]: dict(r) for r in prev_budget_rows}

    # Adjuntar previous + deltas a cada totals[country]
    totals_previous = {}
    for c in countries:
        pc = prev_by_country.get(c, {})
        pb = prev_budget_by_country.get(c, {})
        p_cost = pc.get("cost") or 0
        p_clicks = pc.get("clicks") or 0
        p_imp = pc.get("impressions") or 0
        p_daily = pb.get("avg_daily_budget") or 0
        p_days_cov = pb.get("days_in_period") or 0
        # Mismo criterio que en current: usar histórico si cubre >=50% del rango anterior
        if p_days_cov >= prev_days * 0.5:
            p_budget_period = pb.get("total_budget") or 0
        elif (budget_daily_by_country.get(c, 0) or 0) > 0:
            # Si tenemos daily actual y no hay histórico anterior, no extrapolamos (queda NULL)
            p_budget_period = 0
        else:
            p_budget_period = 0
        p_ctr = (p_clicks / p_imp * 100) if p_imp else 0
        p_cpc = (p_cost / p_clicks) if p_clicks else 0
        p_util = (p_cost / p_budget_period * 100) if p_budget_period > 0 else None
        p_totals = {
            "cost": round(p_cost, 2),
            "clicks": p_clicks,
            "impressions": p_imp,
            "ctr": round(p_ctr, 2),
            "cpc": round(p_cpc, 3),
            "daily_budget": round(p_daily, 2),
            "budget_period": round(p_budget_period, 2) if p_budget_period > 0 else None,
            "utilization_pct": round(p_util, 1) if p_util is not None else None,
        }
        totals_previous[c] = p_totals
        cur_t = totals[c]
        cur_t["previous"] = p_totals
        cur_t["deltas"] = {
            "cost_pct":            _delta_pct(cur_t["cost"], p_totals["cost"]),
            "clicks_pct":          _delta_pct(cur_t["clicks"], p_totals["clicks"]),
            "impressions_pct":     _delta_pct(cur_t["impressions"], p_totals["impressions"]),
            "ctr_pct":             _delta_pct(cur_t["ctr"], p_totals["ctr"]),
            "cpc_pct":             _delta_pct(cur_t["cpc"], p_totals["cpc"]),
            "daily_budget_pct":    _delta_pct(cur_t["daily_budget"], p_totals["daily_budget"]),
            "budget_period_pct":   _delta_pct(cur_t["budget_period"], p_totals["budget_period"]),
            "utilization_pct_pct": _delta_pct(cur_t["utilization_pct"], p_totals["utilization_pct"]),
        }

    return jsonify({
        "since": since,
        "until": until,
        "previous_since": prev_since,
        "previous_until": prev_until,
        "days_in_range": days_in_range,
        "granularity": granularity,
        "periods": [{"key": k, "label": l} for k, l in periods],
        "countries": countries,
        "series": series,
        "totals": totals,
    })


@app.route("/api/meta/country-comparison")
def api_meta_country_comparison():
    """Series temporales de campañas Meta agrupadas por pais.

    Mismo shape de respuesta que /api/google/{shopping,search}-comparison para
    que el frontend pueda reutilizar la logica de render.

    Diferencias respecto a Google:
    - Tabla insights_daily (Meta) tiene spend (no cost) y no hay channel_type.
    - daily_budget en Meta esta en centavos (Meta API standard) -> dividimos
      entre 100 para mostrar EUR.
    - No tenemos historico diario de budget para Meta: budget_period es una
      proyeccion (daily_budget actual x dias del rango), nunca historico.
    """
    granularity = request.args.get("granularity", "weekly")
    if granularity not in ("daily", "weekly", "monthly"):
        granularity = "weekly"
    # Tratamiento de "boosted posts" (campañas con objective=LINK_CLICKS,
    # como las "Publicación de Instagram" boosteadas desde la app). Tres modos:
    #   - 'hidden':        excluir de todo (default, vista mas limpia).
    #   - 'budget_hidden': excluir solo del Pres./dia, mantenerlas en metricas
    #                      y drill-down (donde se ven con su parte).
    #   - 'all':           incluir en todo.
    boosted_mode = request.args.get("boosted_mode", "hidden")
    if boosted_mode not in ("hidden", "budget_hidden", "all"):
        boosted_mode = "hidden"
    metrics_filter = " AND c.objective != 'LINK_CLICKS'" if boosted_mode == "hidden" else ""
    budget_filter = " AND c.objective != 'LINK_CLICKS'" if boosted_mode in ("hidden", "budget_hidden") else ""

    since, until, _days = _range_from_request()
    periods = _generate_periods(since, until, granularity)
    period_keys = [p[0] for p in periods]
    period_idx = {k: i for i, k in enumerate(period_keys)}
    n = len(periods)
    period_expr = _period_expr(granularity)

    with _get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT c.country country,
                   {period_expr} period,
                   SUM(i.spend) cost,
                   SUM(i.clicks) clicks,
                   SUM(i.impressions) impressions
            FROM insights_daily i
            JOIN campaigns c ON c.id = i.campaign_id
            WHERE i.date BETWEEN ? AND ?{metrics_filter}
            GROUP BY c.country, period
            ORDER BY c.country, period
            """,
            (since, until),
        ).fetchall()

        # Presupuesto diario actual por pais.
        # Calculamos un "effective daily budget" por ad set ACTIVE:
        #   - Si el ad set tiene daily_budget propio (> 0): se usa ese (ABO).
        #   - Si no, pero la campana tiene daily_budget (CBO): se reparte
        #     el budget de la campana entre sus ad sets ACTIVE (split equal).
        #   - Si no hay ni una cosa ni la otra: 0.
        # Asi el total del pais = suma de filas del drill-down (cuyo budget
        # se calcula con la misma logica en /api/meta/ad-sets).
        budget_rows = conn.execute(
            f"""
            SELECT c.country country,
                   SUM(
                     CASE
                       WHEN ads.daily_budget IS NOT NULL AND ads.daily_budget > 0 THEN ads.daily_budget
                       WHEN c.daily_budget IS NOT NULL AND c.daily_budget > 0 THEN
                         c.daily_budget * 1.0 / (
                           SELECT COUNT(*) FROM meta_ad_sets a2
                           WHERE a2.campaign_id = c.id
                             AND a2.effective_status = 'ACTIVE'
                         )
                       ELSE 0
                     END
                   ) / 100.0 daily_total
            FROM meta_ad_sets ads
            JOIN campaigns c ON c.id = ads.campaign_id
            WHERE c.effective_status = 'ACTIVE'
              AND ads.effective_status = 'ACTIVE'{budget_filter}
            GROUP BY c.country
            """,
        ).fetchall()
        budget_daily_by_country = {r["country"]: (r["daily_total"] or 0) for r in budget_rows}

    by_country = {}
    for r in rows:
        country = r["country"] or "(sin pais)"
        if country not in by_country:
            by_country[country] = {
                "cost": [0.0] * n, "clicks": [0] * n, "impressions": [0] * n,
                "daily_budget": [0.0] * n, "budget_period": [0.0] * n,
            }
        i = period_idx.get(r["period"])
        if i is None:
            continue
        by_country[country]["cost"][i] = r["cost"] or 0
        by_country[country]["clicks"][i] = r["clicks"] or 0
        by_country[country]["impressions"][i] = r["impressions"] or 0

    countries = sorted(by_country.keys(), key=lambda c: -sum(by_country[c]["cost"]))
    days_in_range = (date.fromisoformat(until) - date.fromisoformat(since)).days + 1

    series = {"cost": {}, "ctr": {}, "cpc": {}, "clicks": {}, "impressions": {},
              "daily_budget": {}, "budget_period": {}, "utilization": {},
              "leads": {}, "cpl": {}}
    totals = {}
    for c in countries:
        d = by_country[c]
        series["cost"][c] = [round(v, 2) for v in d["cost"]]
        series["clicks"][c] = d["clicks"]
        series["impressions"][c] = d["impressions"]
        series["ctr"][c] = [
            round((d["clicks"][i] / d["impressions"][i] * 100) if d["impressions"][i] else 0, 2)
            for i in range(n)
        ]
        series["cpc"][c] = [
            round((d["cost"][i] / d["clicks"][i]) if d["clicks"][i] else 0, 3)
            for i in range(n)
        ]
        # daily_budget por periodo: usamos el actual como constante (no hay historico)
        daily_budget = budget_daily_by_country.get(c, 0) or 0
        series["daily_budget"][c] = [round(daily_budget, 2)] * n
        series["budget_period"][c] = [round(daily_budget, 2)] * n  # 1 dia por bucket si daily
        series["utilization"][c] = [
            round((d["cost"][i] / daily_budget * 100) if daily_budget > 0 else 0, 1)
            for i in range(n)
        ]
        total_cost = sum(d["cost"])
        total_clicks = sum(d["clicks"])
        total_imp = sum(d["impressions"])
        # Presupuesto proyectado del periodo: daily x dias_rango.
        budget_period = daily_budget * days_in_range if daily_budget > 0 else 0
        utilization = (total_cost / budget_period * 100) if budget_period > 0 else None
        totals[c] = {
            "cost": round(total_cost, 2),
            "clicks": total_clicks,
            "impressions": total_imp,
            "ctr": round((total_clicks / total_imp * 100) if total_imp else 0, 2),
            "cpc": round((total_cost / total_clicks) if total_clicks else 0, 3),
            "daily_budget": round(daily_budget, 2),
            "budget_period": round(budget_period, 2) if budget_period > 0 else None,
            "budget_source": "projected" if budget_period > 0 else None,
            "utilization_pct": round(utilization, 1) if utilization is not None else None,
        }

    # Comparativa con periodo anterior
    prev_since, prev_until = _previous_range(since, until)
    prev_days = (date.fromisoformat(prev_until) - date.fromisoformat(prev_since)).days + 1
    with _get_conn() as conn:
        prev_cost_rows = conn.execute(
            f"""
            SELECT c.country country,
                   SUM(i.spend) cost,
                   SUM(i.clicks) clicks,
                   SUM(i.impressions) impressions
            FROM insights_daily i
            JOIN campaigns c ON c.id = i.campaign_id
            WHERE i.date BETWEEN ? AND ?{metrics_filter}
            GROUP BY c.country
            """,
            (prev_since, prev_until),
        ).fetchall()
    prev_by_country = {r["country"]: dict(r) for r in prev_cost_rows}

    for c in countries:
        pc = prev_by_country.get(c, {})
        p_cost = pc.get("cost") or 0
        p_clicks = pc.get("clicks") or 0
        p_imp = pc.get("impressions") or 0
        p_daily = budget_daily_by_country.get(c, 0) or 0  # asumimos mismo budget actual
        p_budget_period = p_daily * prev_days if p_daily > 0 else 0
        p_ctr = (p_clicks / p_imp * 100) if p_imp else 0
        p_cpc = (p_cost / p_clicks) if p_clicks else 0
        p_util = (p_cost / p_budget_period * 100) if p_budget_period > 0 else None
        p_totals = {
            "cost": round(p_cost, 2),
            "clicks": p_clicks,
            "impressions": p_imp,
            "ctr": round(p_ctr, 2),
            "cpc": round(p_cpc, 3),
            "daily_budget": round(p_daily, 2),
            "budget_period": round(p_budget_period, 2) if p_budget_period > 0 else None,
            "utilization_pct": round(p_util, 1) if p_util is not None else None,
        }
        cur_t = totals[c]
        cur_t["previous"] = p_totals
        cur_t["deltas"] = {
            "cost_pct":            _delta_pct(cur_t["cost"], p_totals["cost"]),
            "clicks_pct":          _delta_pct(cur_t["clicks"], p_totals["clicks"]),
            "impressions_pct":     _delta_pct(cur_t["impressions"], p_totals["impressions"]),
            "ctr_pct":             _delta_pct(cur_t["ctr"], p_totals["ctr"]),
            "cpc_pct":             _delta_pct(cur_t["cpc"], p_totals["cpc"]),
            "daily_budget_pct":    _delta_pct(cur_t["daily_budget"], p_totals["daily_budget"]),
            "budget_period_pct":   _delta_pct(cur_t["budget_period"], p_totals["budget_period"]),
            "utilization_pct_pct": _delta_pct(cur_t["utilization_pct"], p_totals["utilization_pct"]),
        }

    # === Leads / CPL desde HubSpot (atribuidos a Meta) ===
    # Fuente Meta en HubSpot: 'Redes Sociales - IG/FB'. Usamos LIKE %...% para
    # cubrir tambien leads multi-fuente como 'Redes Sociales - IG/FB;Web - Google Ads'.
    # Filtramos por createdate en ISO (helper _date_to_hubspot_iso) y por pais
    # exacto. Cuenta = nº de contactos creados en el rango.
    META_HS_SOURCE_LIKE = "%Redes Sociales - IG/FB%"
    hs_since = _date_to_hubspot_iso(since)
    hs_until = _date_to_hubspot_iso(until, end=True)
    hs_prev_since = _date_to_hubspot_iso(prev_since)
    hs_prev_until = _date_to_hubspot_iso(prev_until, end=True)
    period_expr_hs = _hubspot_period_expr(granularity)

    with _get_conn() as conn:
        # Totales por pais (actual)
        leads_total_rows = conn.execute(
            """
            SELECT pais country, COUNT(*) c
            FROM hubspot_contacts
            WHERE createdate BETWEEN ? AND ?
              AND fuentes_de_captacion_especificas LIKE ?
              AND pais IS NOT NULL
            GROUP BY pais
            """,
            (hs_since, hs_until, META_HS_SOURCE_LIKE),
        ).fetchall()
        # Totales por pais (periodo anterior)
        prev_leads_rows = conn.execute(
            """
            SELECT pais country, COUNT(*) c
            FROM hubspot_contacts
            WHERE createdate BETWEEN ? AND ?
              AND fuentes_de_captacion_especificas LIKE ?
              AND pais IS NOT NULL
            GROUP BY pais
            """,
            (hs_prev_since, hs_prev_until, META_HS_SOURCE_LIKE),
        ).fetchall()
        # Series por (pais, periodo) para la tabla detalle
        period_leads_rows = conn.execute(
            f"""
            SELECT pais country, {period_expr_hs} period, COUNT(*) c
            FROM hubspot_contacts
            WHERE createdate BETWEEN ? AND ?
              AND fuentes_de_captacion_especificas LIKE ?
              AND pais IS NOT NULL
            GROUP BY pais, period
            """,
            (hs_since, hs_until, META_HS_SOURCE_LIKE),
        ).fetchall()

    leads_total_by_country = {r["country"]: r["c"] for r in leads_total_rows}
    prev_leads_by_country = {r["country"]: r["c"] for r in prev_leads_rows}
    leads_by_country_period = {}
    for r in period_leads_rows:
        leads_by_country_period.setdefault(r["country"], {})[r["period"]] = r["c"]

    # Inyectar leads/cpl en totals y series
    for c in countries:
        leads = leads_total_by_country.get(c, 0)
        cur_t = totals[c]
        cpl = round(cur_t["cost"] / leads, 2) if leads > 0 else None
        cur_t["leads"] = leads
        cur_t["cpl"] = cpl
        # Previous
        p_leads = prev_leads_by_country.get(c, 0)
        p_cost = cur_t["previous"]["cost"]
        p_cpl = round(p_cost / p_leads, 2) if p_leads > 0 else None
        cur_t["previous"]["leads"] = p_leads
        cur_t["previous"]["cpl"] = p_cpl
        cur_t["deltas"]["leads_pct"] = _delta_pct(leads, p_leads)
        cur_t["deltas"]["cpl_pct"]   = _delta_pct(cpl, p_cpl)
        # Series por periodo
        pmap = leads_by_country_period.get(c, {})
        leads_series = [pmap.get(k, 0) for k in period_keys]
        cost_series = series["cost"][c]
        cpl_series = [
            round(cost_series[i] / leads_series[i], 2) if leads_series[i] > 0 else 0
            for i in range(n)
        ]
        series["leads"][c] = leads_series
        series["cpl"][c] = cpl_series

    return jsonify({
        "since": since,
        "until": until,
        "previous_since": prev_since,
        "previous_until": prev_until,
        "days_in_range": days_in_range,
        "granularity": granularity,
        "periods": [{"key": k, "label": l} for k, l in periods],
        "countries": countries,
        "series": series,
        "totals": totals,
    })


@app.route("/api/google/shopping-comparison")
def api_google_shopping_comparison():
    """Series temporales de campañas SHOPPING de Google agrupadas por pais."""
    return _google_channel_comparison("SHOPPING")


@app.route("/api/google/search-comparison")
def api_google_search_comparison():
    """Series temporales de campañas SEARCH de Google agrupadas por pais.
    Misma estructura/payload que /shopping-comparison para que el frontend
    pueda reutilizar la logica de render.
    """
    return _google_channel_comparison("SEARCH")


@app.route("/api/meta/ad-sets")
def api_meta_ad_sets():
    """Drill-down de Meta a nivel de ad set, agregado al rango actual y
    filtrable por pais. Devuelve una lista de ad sets con sus metricas y
    su daily_budget (en EUR ya convertido) para que el frontend pinche
    el pais y vea cuales rinden mejor.
    """
    since, until, _days = _range_from_request()
    country = request.args.get("country") or None
    # Solo 'hidden' (estricto) excluye boosted del drill-down; 'budget_hidden'
    # los conserva con su parte de Pres./dia visible para inspeccion.
    boosted_mode = request.args.get("boosted_mode", "hidden")
    hide_boosted = boosted_mode == "hidden"

    # Effective daily budget por ad set:
    #   - Solo aplica si el ad set sigue ACTIVE (paused -> NULL, se mostrara "-").
    #   - Si tiene daily_budget propio > 0 -> ese (ABO).
    #   - Si no, pero la campana tiene daily_budget > 0 -> campana / N_active_adsets
    #     (CBO: repartir el budget de la campana entre sus ad sets activos).
    sql = """
        SELECT ads.id ad_set_id,
               ads.name ad_set_name,
               ads.effective_status ad_set_status,
               CASE
                 WHEN ads.effective_status != 'ACTIVE' THEN NULL
                 WHEN ads.daily_budget IS NOT NULL AND ads.daily_budget > 0 THEN ads.daily_budget / 100.0
                 WHEN c.daily_budget IS NOT NULL AND c.daily_budget > 0 THEN
                   c.daily_budget * 1.0 / (
                     SELECT COUNT(*) FROM meta_ad_sets a2
                     WHERE a2.campaign_id = c.id
                       AND a2.effective_status = 'ACTIVE'
                   ) / 100.0
                 ELSE NULL
               END daily_budget_eur,
               c.id campaign_id,
               c.name campaign_name,
               c.country country,
               SUM(i.spend) cost,
               SUM(i.clicks) clicks,
               SUM(i.impressions) impressions,
               SUM(i.reach) reach
        FROM meta_ad_set_insights_daily i
        JOIN meta_ad_sets ads ON ads.id = i.ad_set_id
        JOIN campaigns c       ON c.id = ads.campaign_id
        WHERE i.date BETWEEN ? AND ?
    """
    params = [since, until]
    if country:
        sql += " AND c.country = ?"
        params.append(country)
    if hide_boosted:
        sql += " AND c.objective != 'LINK_CLICKS'"
    sql += " GROUP BY ads.id, c.id ORDER BY cost DESC"

    with _get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        # Para CPL/leads: sumamos acciones de tipo lead asociadas a la campana
        # del ad set. Como las acciones estan a nivel campaign en Meta API,
        # aproximamos: leads del ad set = leads_campana * (spend_ad_set / spend_campana).
        # Por simplicidad ahora mismo no devolvemos leads (se puede anadir despues).

    out = []
    for r in rows:
        cost = r["cost"] or 0
        clicks = r["clicks"] or 0
        imp = r["impressions"] or 0
        daily = r["daily_budget_eur"] or 0
        out.append({
            "ad_set_id": r["ad_set_id"],
            "ad_set_name": r["ad_set_name"],
            "ad_set_status": r["ad_set_status"],
            "daily_budget": round(daily, 2),
            "campaign_id": r["campaign_id"],
            "campaign_name": r["campaign_name"],
            "country": r["country"],
            "cost": round(cost, 2),
            "clicks": int(clicks),
            "impressions": int(imp),
            "reach": int(r["reach"] or 0),
            "ctr": round((clicks / imp * 100) if imp else 0, 2),
            "cpc": round((cost / clicks) if clicks else 0, 2),
        })
    return jsonify({
        "since": since,
        "until": until,
        "country": country,
        "ad_sets": out,
    })


@app.route("/api/google/search-ad-groups")
def api_google_search_ad_groups():
    """Drill-down de campañas SEARCH a nivel de ad group, agregado al rango
    actual y filtrable por pais. Devuelve una lista de ad groups con sus
    metricas para que el frontend las pinche y vea cuales rinden mejor.
    """
    since, until, _days = _range_from_request()
    country = request.args.get("country") or None

    sql = """
        SELECT ag.id ad_group_id,
               ag.name ad_group_name,
               ag.status ad_group_status,
               c.id campaign_id,
               c.name campaign_name,
               c.country country,
               SUM(i.cost) cost,
               SUM(i.clicks) clicks,
               SUM(i.impressions) impressions,
               SUM(i.conversions) conversions,
               SUM(i.conversion_value) revenue
        FROM google_ad_group_insights_daily i
        JOIN google_ad_groups ag ON ag.id = i.ad_group_id
        JOIN google_campaigns c   ON c.id = ag.campaign_id
        WHERE c.advertising_channel_type = 'SEARCH'
          AND i.date BETWEEN ? AND ?
    """
    params = [since, until]
    if country:
        sql += " AND c.country = ?"
        params.append(country)
    sql += " GROUP BY ag.id, c.id ORDER BY cost DESC"

    with _get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()

    out = []
    for r in rows:
        cost = r["cost"] or 0
        clicks = r["clicks"] or 0
        imp = r["impressions"] or 0
        conv = r["conversions"] or 0
        rev = r["revenue"] or 0
        out.append({
            "ad_group_id": r["ad_group_id"],
            "ad_group_name": r["ad_group_name"],
            "ad_group_status": r["ad_group_status"],
            "campaign_id": r["campaign_id"],
            "campaign_name": r["campaign_name"],
            "country": r["country"],
            "cost": round(cost, 2),
            "clicks": int(clicks),
            "impressions": int(imp),
            "ctr": round((clicks / imp * 100) if imp else 0, 2),
            "cpc": round((cost / clicks) if clicks else 0, 2),
            "conversions": round(conv, 2),
            "revenue": round(rev, 2),
            "roas": round((rev / cost) if cost else 0, 2),
        })
    return jsonify({
        "since": since,
        "until": until,
        "country": country,
        "ad_groups": out,
    })


@app.route("/api/resumen-comparison")
def api_resumen_comparison():
    """Datos por (pais, periodo) para los 3 charts del top del Resumen:
    - Inversion: Meta.spend + Google.cost
    - Leads: contactos HubSpot (cualquier fuente)
    - CPL: Inversion / Leads

    Respeta filtros country + rango. Granularidad propia (default weekly).
    """
    granularity = request.args.get("granularity", "weekly")
    if granularity not in ("daily", "weekly", "monthly"):
        granularity = "weekly"

    since, until, _days = _range_from_request()
    since_hs = _date_to_hubspot_iso(since)
    until_hs = _date_to_hubspot_iso(until, end=True)
    country = request.args.get("country") or None

    periods = _generate_periods(since, until, granularity)
    period_keys = [p[0] for p in periods]
    period_idx = {k: i for i, k in enumerate(period_keys)}
    n = len(periods)

    period_expr = _period_expr(granularity)
    period_expr_hs = _hubspot_period_expr(granularity)

    pais_clause = " AND pais = ?" if country else ""
    pais_params = [country] if country else []

    spend_bc = {}   # {country: [n vals]}
    leads_bc = {}   # {country: [n vals]}

    def _bc_add(d, country_val, i, v):
        if not country_val:
            return
        if country_val not in d:
            d[country_val] = [0] * n
        d[country_val][i] += v or 0

    with _get_conn() as conn:
        # Meta spend por (country, period)
        sql = (
            f"SELECT c.country country, {period_expr} p, SUM(i.spend) s "
            "FROM insights_daily i JOIN campaigns c ON c.id = i.campaign_id "
            "WHERE i.date BETWEEN ? AND ?"
        )
        params = [since, until]
        if country:
            sql += " AND c.country = ?"
            params.append(country)
        sql += " GROUP BY c.country, p"
        for r in conn.execute(sql, params):
            i = period_idx.get(r["p"])
            if i is not None:
                _bc_add(spend_bc, r["country"], i, r["s"])

        # Google spend por (country, period)
        sql_g = (
            f"SELECT c.country country, {period_expr} p, SUM(i.cost) s "
            "FROM google_insights_daily i JOIN google_campaigns c ON c.id = i.campaign_id "
            "WHERE i.date BETWEEN ? AND ?"
        )
        params_g = [since, until]
        if country:
            sql_g += " AND c.country = ?"
            params_g.append(country)
        sql_g += " GROUP BY c.country, p"
        for r in conn.execute(sql_g, params_g):
            i = period_idx.get(r["p"])
            if i is not None:
                _bc_add(spend_bc, r["country"], i, r["s"])

        # HubSpot leads por (country, period) - todas las fuentes
        sql = (
            f"SELECT pais country, {period_expr_hs} p, COUNT(*) c "
            f"FROM hubspot_contacts WHERE createdate BETWEEN ? AND ?{pais_clause} "
            "GROUP BY pais, p"
        )
        for r in conn.execute(sql, [since_hs, until_hs, *pais_params]):
            i = period_idx.get(r["p"])
            if i is not None:
                _bc_add(leads_bc, r["country"], i, r["c"])

    # Agregar a totales por periodo (suma sobre todos los paises). El Resumen
    # muestra el global, no por pais (ya se ven los desgloses en otras tabs).
    all_countries = set(spend_bc.keys()) | set(leads_bc.keys())
    cost_total = [0.0] * n
    leads_total = [0] * n
    for c in all_countries:
        vc = spend_bc.get(c) or [0] * n
        vl = leads_bc.get(c) or [0] * n
        for i in range(n):
            cost_total[i] += vc[i] or 0
            leads_total[i] += vl[i] or 0
    cpl_total = [
        round((cost_total[i] / leads_total[i]), 2) if leads_total[i] > 0 else 0
        for i in range(n)
    ]

    # === Revenue Heroturfs (Navision) por periodo + ROAS Real ===
    # Busca el revenue facturado HT por bucket usando misma logica que
    # /api/navision/sales-comparison: SUM(Amount cabecera - anticipos negativos)
    # * ratio HT * sign (facturas +1, abonos -1).
    revenue_total = [0.0] * n
    try:
        amount_eur_hdr = _navision_amount_eur_sql(
            amount_col="(i.amount - COALESCE(a.advance_amount, 0) - COALESCE(f.freight_amount, 0))",
            currency_col="i.currency_code",
        )
        period_expr_nav = _period_expr(granularity, "i.posting_date")
        with _get_conn() as conn:
            rev_rows = conn.execute(
                f"""
                {_NAV_RATIOS_CTE}
                SELECT {period_expr_nav} period,
                       SUM({amount_eur_hdr} * COALESCE(r.ht_ratio, 0) * {_NAV_DOC_SIGN_SQL}) revenue
                FROM navision_invoices i
                LEFT JOIN invoice_ratios r ON r.invoice_no = i.invoice_no
                LEFT JOIN advance_payments a ON a.invoice_no = i.invoice_no
                LEFT JOIN freight_amounts f ON f.invoice_no = i.invoice_no
                WHERE i.posting_date BETWEEN ? AND ?{(" AND i.sell_country = ?") if country else ""}
                  AND COALESCE(r.ht_ratio, 0) > 0
                GROUP BY period
                """,
                ([since, until, country] if country else [since, until]),
            ).fetchall()
        for r in rev_rows:
            i = period_idx.get(r["period"])
            if i is not None:
                revenue_total[i] += r["revenue"] or 0
    except Exception:
        # Si Navision no esta disponible, dejamos revenue=0 (chart vacio)
        pass

    # ROAS real = revenue / cost por periodo (0 cuando cost==0 para evitar div/0)
    roas_total = [
        round((revenue_total[i] / cost_total[i]), 2) if cost_total[i] > 0 else 0
        for i in range(n)
    ]

    # === Clientes nuevos (primera factura HT en el periodo) + CAC ===
    # CAC (Customer Acquisition Cost) = spend blended / nuevos clientes Heroturfs
    # del periodo. Loose attribution (asume que los nuevos del periodo P los
    # atrae el spend del mismo P).
    new_customers_total = [0] * n
    try:
        period_expr_first = _period_expr(granularity, "first_ht_date")
        country_clause = " AND cu.country = ?" if country else ""
        with _get_conn() as conn:
            new_rows = conn.execute(
                f"""
                WITH first_ht_per_customer AS (
                    SELECT i.customer_no,
                           MIN(i.posting_date) first_ht_date
                    FROM navision_invoices i
                    JOIN navision_invoice_lines l ON l.invoice_no = i.invoice_no
                    WHERE l.is_heroturfs = 1 AND i.doc_type = 'invoice'
                    GROUP BY i.customer_no
                )
                SELECT {period_expr_first} period, COUNT(*) n
                FROM first_ht_per_customer fc
                LEFT JOIN navision_customers cu ON cu.customer_no = fc.customer_no
                WHERE fc.first_ht_date BETWEEN ? AND ?{country_clause}
                GROUP BY period
                """,
                ([since, until, country] if country else [since, until]),
            ).fetchall()
        for r in new_rows:
            i = period_idx.get(r["period"])
            if i is not None:
                new_customers_total[i] += r["n"] or 0
    except Exception:
        pass

    cac_total = [
        round((cost_total[i] / new_customers_total[i]), 2) if new_customers_total[i] > 0 else 0
        for i in range(n)
    ]

    return jsonify({
        "since": since,
        "until": until,
        "granularity": granularity,
        "periods": _periods_with_partial_info(since, until, granularity),
        "series": {
            "cost": [round(v, 2) for v in cost_total],
            "leads": leads_total,
            "cpl": cpl_total,
            "revenue": [round(v, 2) for v in revenue_total],
            "roas": roas_total,
            "new_customers": new_customers_total,
            "cac": cac_total,
        },
    })


# === Conversion de divisa Navision a EUR ===
# BC no expone Amount_LCY en las paginas publicadas. Como solo hay un
# punado de facturas en moneda extranjera (GBP, ~7 facturas) usamos
# tasas fijas configurables por .env. Si en el futuro hay mas divisas
# o fluctuaciones grandes, el usuario actualiza NAVISION_RATES en el .env.
import re as _re_navision
def _navision_currency_rates():
    """Devuelve {currency_code: rate_to_eur}. Lee de NAVISION_RATES env
    (formato 'GBP:1.17,USD:0.93'). Default conservador: GBP=1.17."""
    raw = os.getenv("NAVISION_RATES", "GBP:1.17")
    rates = {}
    for pair in (raw or "").split(","):
        pair = pair.strip()
        if not pair or ":" not in pair:
            continue
        code, _, rate = pair.partition(":")
        code = code.strip().upper()
        # Validar code (solo letras) para evitar inyeccion
        if not _re_navision.fullmatch(r"[A-Z]{3}", code):
            continue
        try:
            rates[code] = float(rate)
        except ValueError:
            continue
    return rates


def _navision_amount_eur_sql(amount_col="l.amount", currency_col="i.currency_code",
                              date_col="i.posting_date"):
    """SQL fragment que convierte amount a EUR usando la tabla
    navision_currency_rates poblada desde Power_BI_Tipo_de_cambio.
    Para cada fila busca el rate de su currency_code vigente en su fecha
    (ultimo Starting_Date <= fecha). Si no hay rate (porque la BC nunca tuvo
    ese registro) cae al map de NAVISION_RATES del .env como fallback.
    EUR/vacio: amount tal cual.
    """
    fallback_rates = _navision_currency_rates()
    fallback_cases = " ".join(
        f"WHEN '{code}' THEN {amount_col} * {rate}" for code, rate in fallback_rates.items()
    ) if fallback_rates else ""
    fallback_sql = (
        f"(CASE {currency_col} {fallback_cases} ELSE {amount_col} END)"
        if fallback_cases else amount_col
    )
    # COALESCE: usa rate de BBDD si existe; si no, fallback. Si tampoco hay,
    # multiplica por 1 (lo cual es razonable como ultima red — peor que dejar
    # el amount como NULL en una agregacion).
    rate_lookup = (
        f"(SELECT eur_per_unit FROM navision_currency_rates r "
        f" WHERE r.currency_code = {currency_col} "
        f"   AND r.starting_date <= {date_col} "
        f" ORDER BY r.starting_date DESC LIMIT 1)"
    )
    return (
        f"CASE WHEN COALESCE({currency_col},'') IN ('','EUR') THEN {amount_col} "
        f"     WHEN ({rate_lookup}) IS NOT NULL THEN {amount_col} * ({rate_lookup}) "
        f"     ELSE {fallback_sql} END"
    )


# CTE 'invoice_ratios' usado en queries de revenue Heroturfs: para cada factura
# calcula que porcentaje del valor de items son Heroturfs. Asi cuando el Amount
# de cabecera (que ya incluye descuentos/portes/G-L) se multiplica por ese
# ratio, los descuentos a nivel factura se prorratean automaticamente.
# Si la factura tiene SOLO items HT -> ratio=1 -> revenue = Amount cabecera completo.
# Si es mixta -> revenue HT = Amount cabecera * (items HT / items totales).
_NAV_RATIOS_CTE = """
WITH invoice_ratios AS (
    -- Ratio HT = items HT / items totales. Solo lineas Type='Item' entran
    -- en el calculo (las G/L de descuentos/portes romperian la formula).
    SELECT invoice_no,
           CAST(SUM(CASE WHEN is_heroturfs=1 THEN amount ELSE 0 END) AS REAL) /
             NULLIF(SUM(amount), 0) AS ht_ratio,
           SUM(CASE WHEN is_heroturfs=1 THEN quantity ELSE 0 END) AS qty_ht
    FROM navision_invoice_lines
    WHERE COALESCE(type, 'Item') = 'Item'
    GROUP BY invoice_no
),
advance_payments AS (
    -- Cuentas 438xxxx = "Anticipos de clientes" en PGC esp. Lineas G/L
    -- NEGATIVAS de estas cuentas se aplican como descuento al facturar
    -- (porque ya se cobro antes). Hay que REVERTIR (sumar al amount) para
    -- obtener el revenue bruto que reporta BC en 'Importe Venta'.
    SELECT invoice_no,
           SUM(amount) AS advance_amount
    FROM navision_invoice_lines
    WHERE type = 'G/L Account'
      AND substr(COALESCE(item_no, ''), 1, 3) = '438'
      AND amount < 0
    GROUP BY invoice_no
),
freight_amounts AS (
    -- Cuenta 6240004 = "Gastos transporte recargados al cliente" (recobramos
    -- al cliente lo que pagamos por transporte). BC NO lo considera revenue.
    -- En cambio cuenta 7590001 = "Ingresos por servicios de transporte"
    -- propios SI son revenue para BC, asi que NO se restan.
    SELECT invoice_no,
           SUM(amount) AS freight_amount
    FROM navision_invoice_lines
    WHERE type = 'G/L Account'
      AND item_no = '6240004'
    GROUP BY invoice_no
)
"""

# SQL fragment que devuelve +1 para facturas y -1 para abonos. Multiplica
# el revenue para que abonos resten del neto. doc_type es columna de
# navision_invoices.
_NAV_DOC_SIGN_SQL = "(CASE i.doc_type WHEN 'credit_memo' THEN -1 ELSE 1 END)"


@app.route("/api/navision/sales-comparison")
def api_navision_sales_comparison():
    """Series temporales de revenue Heroturfs FACTURADO en Navision por
    (pais, periodo). Mismo shape que /api/google/{shopping,search}-comparison
    para reutilizar el render del frontend.

    Datos: solo lineas Type='Item' de facturas (HistFactAreaPriv) cuyas
    items tienen itemCategoryCode 'HT *' (marca Heroturfs).

    Filtros: rango de fechas + country (opcional, ya en nombre 'España'/'Francia').
    """
    granularity = request.args.get("granularity", "weekly")
    if granularity not in ("daily", "weekly", "monthly"):
        granularity = "weekly"

    since, until, _days = _range_from_request()
    country = request.args.get("country") or None

    periods = _generate_periods(since, until, granularity)
    period_keys = [p[0] for p in periods]
    period_idx = {k: i for i, k in enumerate(period_keys)}
    n = len(periods)
    # Aqui agrupamos por posting_date de la factura (campo 'date' de la query
    # debajo). _period_expr usa 'date' por defecto, asi que renombramos.
    period_expr = _period_expr(granularity, "i.posting_date")

    pais_clause = " AND i.sell_country = ?" if country else ""
    pais_params = [country] if country else []

    revenue_bc = {}     # {country: [n vals]}
    invoices_bc = {}    # {country: [n vals]} (count distintas)
    qty_bc = {}         # {country: [n vals]} (m2)

    def _bc_add(d, c, i, v):
        if not c: return
        if c not in d: d[c] = [0] * n
        d[c][i] += v or 0

    # Revenue HT = (Amount cabecera - anticipos negativos) * ratio HT.
    # Los anticipos previos al facturar se aplican como linea G/L negativa
    # 438xxxx; al restarla obtenemos el revenue REAL bruto (lo que BC
    # llama "Importe Venta").
    amount_eur_hdr = _navision_amount_eur_sql(
        amount_col="(i.amount - COALESCE(a.advance_amount, 0) - COALESCE(f.freight_amount, 0))",
        currency_col="i.currency_code",
    )
    pais_inv_clause = " AND i.sell_country = ?" if country else ""
    with _get_conn() as conn:
        rows = conn.execute(
            f"""
            {_NAV_RATIOS_CTE}
            SELECT i.sell_country country,
                   {_period_expr(granularity, "i.posting_date")} period,
                   SUM({amount_eur_hdr} * COALESCE(r.ht_ratio, 0) * {_NAV_DOC_SIGN_SQL}) revenue,
                   SUM(COALESCE(r.qty_ht, 0) * {_NAV_DOC_SIGN_SQL}) qty,
                   COUNT(DISTINCT CASE WHEN r.ht_ratio > 0 AND i.doc_type='invoice' THEN i.invoice_no END) n_inv
            FROM navision_invoices i
            LEFT JOIN invoice_ratios r ON r.invoice_no = i.invoice_no
            LEFT JOIN advance_payments a ON a.invoice_no = i.invoice_no
            LEFT JOIN freight_amounts f ON f.invoice_no = i.invoice_no
            WHERE i.posting_date BETWEEN ? AND ?{pais_inv_clause}
              AND COALESCE(r.ht_ratio, 0) > 0
            GROUP BY i.sell_country, period
            ORDER BY i.sell_country, period
            """,
            [since, until, *pais_params],
        ).fetchall()
        for r in rows:
            i = period_idx.get(r["period"])
            if i is None: continue
            _bc_add(revenue_bc, r["country"], i, r["revenue"])
            _bc_add(qty_bc, r["country"], i, r["qty"])
            _bc_add(invoices_bc, r["country"], i, r["n_inv"])

    all_countries = set(revenue_bc.keys())
    countries = sorted(all_countries, key=lambda c: -sum(revenue_bc.get(c, [0]*n)))

    # Agregado total (suma sobre paises)
    revenue_total = [0.0] * n
    qty_total = [0.0] * n
    invoices_total = [0] * n
    for c in countries:
        for i in range(n):
            revenue_total[i] += (revenue_bc.get(c) or [0]*n)[i]
            qty_total[i]     += (qty_bc.get(c) or [0]*n)[i]
            invoices_total[i] += int((invoices_bc.get(c) or [0]*n)[i])

    return jsonify({
        "since": since,
        "until": until,
        "granularity": granularity,
        "periods": _periods_with_partial_info(since, until, granularity),
        "countries": countries,
        "series": {
            "revenue": [round(v, 2) for v in revenue_total],
            "quantity": [round(v, 2) for v in qty_total],
            "invoices": invoices_total,
        },
        "by_country": {
            "revenue": {c: [round(v, 2) for v in revenue_bc.get(c, [0]*n)] for c in countries},
            "quantity": {c: [round(v, 2) for v in qty_bc.get(c, [0]*n)] for c in countries},
            "invoices": {c: [int(v) for v in invoices_bc.get(c, [0]*n)] for c in countries},
        },
    })


@app.route("/api/navision/kpis")
def api_navision_kpis():
    """KPIs Navision Heroturfs (totales del rango): revenue, # facturas,
    # clientes unicos, m2 vendidos, ticket medio. Tambien previous + deltas.
    Util para tarjetas KPI y para calcular ROAS real (revenue / spend).
    """
    since, until, _days = _range_from_request()
    prev_since, prev_until = _previous_range(since, until)
    country = request.args.get("country") or None

    def _kpis(since_, until_):
        # Revenue HT = (Amount cabecera - anticipos negativos 438xxx) * ratio HT
        amount_eur_hdr = _navision_amount_eur_sql(
            amount_col="(i.amount - COALESCE(a.advance_amount, 0) - COALESCE(f.freight_amount, 0))",
            currency_col="i.currency_code",
        )
        sql = f"""
            {_NAV_RATIOS_CTE}
            SELECT SUM({amount_eur_hdr} * COALESCE(r.ht_ratio, 0) * {_NAV_DOC_SIGN_SQL}) revenue,
                   SUM(COALESCE(r.qty_ht, 0) * {_NAV_DOC_SIGN_SQL}) qty,
                   COUNT(DISTINCT CASE WHEN r.ht_ratio > 0 AND i.doc_type='invoice' THEN i.invoice_no END) n_inv,
                   COUNT(DISTINCT CASE WHEN r.ht_ratio > 0 AND i.doc_type='invoice' THEN i.customer_no END) n_cust
            FROM navision_invoices i
            LEFT JOIN invoice_ratios r ON r.invoice_no = i.invoice_no
            LEFT JOIN advance_payments a ON a.invoice_no = i.invoice_no
            LEFT JOIN freight_amounts f ON f.invoice_no = i.invoice_no
            WHERE i.posting_date BETWEEN ? AND ?
              AND COALESCE(r.ht_ratio, 0) > 0
        """
        params = [since_, until_]
        if country:
            sql += " AND i.sell_country = ?"
            params.append(country)
        with _get_conn() as conn:
            r = conn.execute(sql, params).fetchone()
        revenue = r["revenue"] or 0
        n_inv = r["n_inv"] or 0
        return {
            "revenue": round(revenue, 2),
            "quantity": round(r["qty"] or 0, 2),
            "invoices": n_inv,
            "customers": r["n_cust"] or 0,
            "avg_ticket": round((revenue / n_inv) if n_inv else 0, 2),
        }

    cur = _kpis(since, until)
    prev = _kpis(prev_since, prev_until)
    deltas = {f"{k}_pct": _delta_pct(cur[k], prev[k]) for k in cur}

    # Last sync
    with _get_conn() as conn:
        last_sync = conn.execute(
            "SELECT finished_at FROM navision_sync_log WHERE status = 'ok' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()

    return jsonify({
        "since": since, "until": until, "country": country,
        **cur,
        "previous": {"since": prev_since, "until": prev_until, **prev},
        "deltas": deltas,
        "last_sync": last_sync["finished_at"] if last_sync else None,
    })


@app.route("/api/navision/sync", methods=["POST"])
def api_navision_sync():
    """Lanza sync incremental Navision (ultimos 90 dias)."""
    try:
        import navision_sync
        navision_sync.sync()
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/google/sync", methods=["POST"])
def api_google_sync():
    """Lanza sync de Google Ads. Devuelve error si falta Developer Token."""
    try:
        import google_sync as gs
        gs.sync()
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """Chatbot del dashboard. Recibe historial de mensajes + pais opcional."""
    import chatbot
    data = request.get_json(force=True) or {}
    messages = data.get("messages") or []
    country = data.get("country") or None
    if not messages:
        return jsonify({"error": "Falta 'messages'"}), 400
    try:
        reply, tools_used = chatbot.chat(messages, country=country)
        return jsonify({"reply": reply, "tools_used": tools_used})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/hubspot/sync", methods=["POST"])
def api_hubspot_sync():
    """Lanza un sync incremental de los ultimos 30 dias para no tardar mucho desde el dashboard."""
    try:
        since = datetime.now(timezone.utc) - timedelta(days=30)
        hubspot_sync.sync(since=since)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=True)
