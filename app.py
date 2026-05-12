"""Dashboard web Flask para analisis de campanas Meta Ads de Heroturfs."""

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


def _period_expr(granularity):
    """Devuelve la expresion SQL para agrupar por dia/semana/mes."""
    if granularity == "weekly":
        # Lunes de la semana (ISO): substraer (weekday-1) dias, donde weekday: lun=1..dom=7
        return "date(date, '-' || ((CAST(strftime('%w', date) AS INTEGER) + 6) % 7) || ' days')"
    if granularity == "monthly":
        # Primer dia del mes
        return "date(date, 'start of month')"
    return "date"


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


@app.route("/api/kpis")
def api_kpis():
    days_param = request.args.get("days", "30")
    country = request.args.get("country") or None
    since, until, days = _resolve_range(days_param)
    with _get_conn() as conn:
        # Spend/impr/clicks de Meta filtrados por pais (via JOIN con campaigns)
        sql = (
            "SELECT SUM(i.spend) spend, SUM(i.impressions) impressions, "
            "SUM(i.reach) reach, SUM(i.clicks) clicks "
            "FROM insights_daily i JOIN campaigns c ON c.id = i.campaign_id "
            "WHERE i.date BETWEEN ? AND ?"
        )
        params = [since, until]
        if country:
            sql += " AND c.country = ?"
            params.append(country)
        r = conn.execute(sql, params).fetchone()

        # Leads ahora vienen de HubSpot (contactos atribuidos a Meta = "Redes Sociales - IG/FB")
        # con filtro de pais opcional.
        since_iso = _date_to_hubspot_iso(since)
        until_iso = _date_to_hubspot_iso(until, end=True)
        leads_total = _count_hubspot_leads(conn, since_iso, until_iso,
                                           source=HUBSPOT_META_SOURCE, country=country)

        # Ultima sincronizacion OK
        last_sync = conn.execute(
            "SELECT finished_at FROM sync_log WHERE status = 'ok' ORDER BY id DESC LIMIT 1"
        ).fetchone()

    spend = r["spend"] or 0
    impressions = r["impressions"] or 0
    reach = r["reach"] or 0
    clicks = r["clicks"] or 0
    ctr = (clicks / impressions * 100) if impressions else 0
    cpc = (spend / clicks) if clicks else 0
    cpm = (spend / impressions * 1000) if impressions else 0
    cpl = (spend / leads_total) if leads_total else 0

    return jsonify(
        {
            "since": since,
            "until": until,
            "days": days,
            "country": country,
            "spend": round(spend, 2),
            "impressions": impressions,
            "reach": reach,
            "clicks": clicks,
            "ctr": round(ctr, 2),
            "cpc": round(cpc, 3),
            "cpm": round(cpm, 2),
            "leads": int(leads_total),
            "cpl": round(cpl, 2),
            "last_sync": last_sync["finished_at"] if last_sync else None,
        }
    )


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
    since, until, _days = _resolve_range(days_param)
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
    since, until, days = _resolve_range(days_param)

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


@app.route("/api/hubspot/kpis")
def api_hubspot_kpis():
    """KPIs principales de HubSpot en el rango (createdate del contacto). Filtro pais opcional."""
    days_param = request.args.get("days", "30")
    country = request.args.get("country") or None
    since, until = _hubspot_date_range(days_param)

    # Cuando hay filtro de pais, anadimos la condicion al WHERE de cada query
    pais_clause = " AND pais = ?" if country else ""
    pais_clause_c = " AND c.pais = ?" if country else ""
    pais_params = [country] if country else []

    with _get_conn() as conn:
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

        # Deals ganados: filtramos solo si hay pais via JOIN al contacto principal
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

        # Revenue por fuente (cruce deal -> contacto)
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

        last_sync = conn.execute(
            "SELECT finished_at FROM hubspot_sync_log WHERE status = 'ok' ORDER BY id DESC LIMIT 1"
        ).fetchone()

    revenue_meta = revenue_by_source.get(HUBSPOT_META_SOURCE, {}).get("revenue", 0)
    deals_meta = revenue_by_source.get(HUBSPOT_META_SOURCE, {}).get("deals", 0)
    revenue_google = revenue_by_source.get(HUBSPOT_GOOGLE_SOURCE, {}).get("revenue", 0)
    deals_google = revenue_by_source.get(HUBSPOT_GOOGLE_SOURCE, {}).get("deals", 0)

    return jsonify({
        "since": since[:10],
        "until": until[:10],
        "country": country,
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
        "last_sync": last_sync["finished_at"] if last_sync else None,
    })


@app.route("/api/hubspot/funnel")
def api_hubspot_funnel():
    """Funnel completo Meta: spend -> leads Meta API -> contactos HS -> ganados -> revenue.

    Si se pasa country, filtra Meta side por campaigns.country y HubSpot side por contacts.pais.
    """
    days_param = request.args.get("days", "30")
    country = request.args.get("country") or None
    since_meta, until_meta, _days = _resolve_range(days_param)
    since_hs, until_hs = _hubspot_date_range(days_param)

    with _get_conn() as conn:
        # Meta spend (filtrado por country)
        sql = (
            "SELECT COALESCE(SUM(i.spend),0) spend FROM insights_daily i "
            "JOIN campaigns c ON c.id = i.campaign_id WHERE i.date BETWEEN ? AND ?"
        )
        params = [since_meta, until_meta]
        if country:
            sql += " AND c.country = ?"
            params.append(country)
        r = conn.execute(sql, params).fetchone()
        meta_spend = round(r["spend"], 2)

        # Meta leads de la API (filtrado por country)
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

        # HubSpot - contactos atribuidos a Meta (con country opcional)
        contacts_meta = _count_hubspot_leads(
            conn, since_hs, until_hs, source=HUBSPOT_META_SOURCE, country=country
        )

        # Contactos Meta ganados (lead_status terminal positivo)
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

        # Revenue Meta (deals won asociados a contactos Meta)
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

    roas = (revenue_meta / meta_spend) if meta_spend else 0
    cpl_real = (meta_spend / contacts_meta) if contacts_meta else 0
    cac = (meta_spend / contacts_meta_won) if contacts_meta_won else 0

    return jsonify({
        "since": since_meta,
        "until": until_meta,
        "country": country,
        "stages": [
            {"label": "Spend Meta", "value": meta_spend, "unit": "EUR"},
            {"label": "Leads Meta (API)", "value": meta_leads, "unit": ""},
            {"label": "Contactos HS atribuidos a Meta", "value": contacts_meta, "unit": ""},
            {"label": "Contactos Meta ganados", "value": contacts_meta_won, "unit": ""},
            {"label": "Deals ganados Meta", "value": deals_meta, "unit": ""},
            {"label": "Revenue Meta", "value": revenue_meta, "unit": "EUR"},
        ],
        "roas": round(roas, 2),
        "cpl_real": round(cpl_real, 2),
        "cac": round(cac, 2),
    })


@app.route("/api/hubspot/by-source")
def api_hubspot_by_source():
    """Distribucion de contactos y revenue por fuente de captacion. Filtro country opcional."""
    days_param = request.args.get("days", "30")
    country = request.args.get("country") or None
    since, until = _hubspot_date_range(days_param)

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
    since, until = _hubspot_date_range(days_param)

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
    since, until = _hubspot_date_range(days_param)

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

    since, until, _days = _resolve_range(days_param)
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

    def row(label, vals, total, fmt, indent=False, header=False, note=None):
        return {"label": label, "values": [round(v, 2) for v in vals], "total": round(total, 2),
                "format": fmt, "indent": indent, "header": header, "note": note}

    sections = [
        {
            "title": "Inversión por canales",
            "rows": [
                row("Inversión total", spend_total, sum_spend_total, "eur", header=True),
                row("Meta Ads", spend_meta, sum_spend_meta, "eur", indent=True),
                row("Google Ads", spend_google, sum_spend_google, "eur", indent=True),
            ],
        },
        {
            "title": "Número de leads nuevos",
            "rows": [
                row("Leads totales", leads_total, sum_leads_total, "int", header=True),
                row("Meta", leads_meta, sum_leads_meta, "int", indent=True),
                row("Google", leads_google, sum_leads_google, "int", indent=True),
                row("Desconocido / Otros", leads_other, sum_leads_other, "int", indent=True),
            ],
        },
        {
            "title": "CPL (Coste por Lead)",
            "rows": [
                row("CPL total", cpl_total, tot_cpl_total, "eur", header=True),
                row("Meta", cpl_meta, tot_cpl_meta, "eur", indent=True),
                row("Google", cpl_google, tot_cpl_google, "eur", indent=True),
            ],
        },
        {
            "title": "Conversion",
            "rows": [
                row("Cerrados (convertidos en cliente)", cerrados, sum_cerrados, "int"),
                row("Tasa de éxito (Lead -> Cliente)", tasa_exito, tot_tasa, "pct"),
                row("CAC (Coste de adquisición)", cac, tot_cac, "eur"),
            ],
        },
        {
            "title": "Revenue (Ventas netas HubSpot)",
            "rows": [
                row("Ventas netas", revenue, sum_revenue, "eur", header=True),
                row("Deals ganados", deals_won, sum(deals_won), "int", indent=True),
                row("ROAS (Revenue / Inversión)", roas, tot_roas, "x"),
            ],
        },
    ]

    return jsonify({
        "since": since,
        "until": until,
        "country": country,
        "granularity": granularity,
        "periods": [{"key": k, "label": l} for k, l in periods],
        "totals_label": "Acumulado",
        "sections": sections,
    })


# ====================================================================
# Google Ads endpoints
# ====================================================================

@app.route("/api/google/kpis")
def api_google_kpis():
    """KPIs de Google Ads agregados en el rango. Filtro country opcional."""
    days_param = request.args.get("days", "30")
    country = request.args.get("country") or None
    since, until, days = _resolve_range(days_param)

    with _get_conn() as conn:
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

        last_sync = conn.execute(
            "SELECT finished_at FROM google_sync_log WHERE status='ok' ORDER BY id DESC LIMIT 1"
        ).fetchone()

    cost = r["cost"] or 0
    impressions = r["impressions"] or 0
    clicks = r["clicks"] or 0
    conversions = r["conversions"] or 0
    revenue = r["revenue"] or 0
    ctr = (clicks / impressions * 100) if impressions else 0
    cpc = (cost / clicks) if clicks else 0
    cpm = (cost / impressions * 1000) if impressions else 0
    roas = (revenue / cost) if cost else 0
    cpa = (cost / conversions) if conversions else 0

    return jsonify({
        "since": since,
        "until": until,
        "days": days,
        "country": country,
        "cost": round(cost, 2),
        "impressions": impressions,
        "clicks": clicks,
        "conversions": round(conversions, 2),
        "revenue": round(revenue, 2),
        "ctr": round(ctr, 2),
        "cpc": round(cpc, 3),
        "cpm": round(cpm, 2),
        "roas": round(roas, 2),
        "cpa": round(cpa, 2),
        "last_sync": last_sync["finished_at"] if last_sync else None,
    })


@app.route("/api/google/campaigns")
def api_google_campaigns():
    """Tabla de campanas Google con metricas agregadas."""
    days_param = request.args.get("days", "30")
    country = request.args.get("country") or None
    since, until, _days = _resolve_range(days_param)

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


@app.route("/api/google/sync", methods=["POST"])
def api_google_sync():
    """Lanza sync de Google Ads. Devuelve error si falta Developer Token."""
    try:
        import google_sync as gs
        gs.sync()
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


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
