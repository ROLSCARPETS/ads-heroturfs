"""Dashboard web Flask para analisis de campanas Meta Ads de Heroturfs."""

import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template, request

import db
import hubspot_sync
import meta_sync

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True

LEAD_ACTION_TYPES = (
    "lead",
    "offsite_conversion.fb_pixel_lead",
    "onsite_conversion.lead_grouped",
    "offsite_content_view_add_meta_leads",
)


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
    since, until, days = _resolve_range(days_param)
    with _get_conn() as conn:
        r = conn.execute(
            """
            SELECT SUM(spend) spend, SUM(impressions) impressions,
                   SUM(reach) reach, SUM(clicks) clicks
            FROM insights_daily
            WHERE date BETWEEN ? AND ?
            """,
            (since, until),
        ).fetchone()
        leads_total = sum(_fetch_leads_by_campaign(conn, since, until).values())

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
    """Serie de gasto, clicks y leads agregada por periodo (diario/semanal/mensual)."""
    days_param = request.args.get("days", "30")
    granularity = request.args.get("granularity", "daily")
    if granularity not in ("daily", "weekly", "monthly"):
        granularity = "daily"
    since, until, _days = _resolve_range(days_param)
    period_expr = _period_expr(granularity)

    with _get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT {period_expr} AS period,
                   SUM(spend) spend, SUM(clicks) clicks, SUM(impressions) impressions
            FROM insights_daily
            WHERE date BETWEEN ? AND ?
            GROUP BY period
            ORDER BY period
            """,
            (since, until),
        ).fetchall()
        leads_by_period = _fetch_leads_by_period(conn, since, until, granularity)

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
    """Tabla de campanas con metricas agregadas en el rango."""
    days_param = request.args.get("days", "30")
    since, until, days = _resolve_range(days_param)
    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT c.id, c.name, c.effective_status, c.objective,
                   SUM(i.spend) spend,
                   SUM(i.impressions) impressions,
                   SUM(i.reach) reach,
                   SUM(i.clicks) clicks
            FROM campaigns c
            LEFT JOIN insights_daily i
              ON i.campaign_id = c.id AND i.date BETWEEN ? AND ?
            GROUP BY c.id
            ORDER BY spend DESC NULLS LAST
            """,
            (since, until),
        ).fetchall()
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

# Fuente de captacion considerada "Meta" en HubSpot
HUBSPOT_META_SOURCE = "Redes Sociales - IG/FB"
HUBSPOT_GOOGLE_SOURCE = "Web - Google Ads"


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
    """KPIs principales de HubSpot en el rango (createdate del contacto)."""
    days_param = request.args.get("days", "30")
    since, until = _hubspot_date_range(days_param)

    with _get_conn() as conn:
        # Contactos creados en el rango
        contacts_total = conn.execute(
            "SELECT COUNT(*) c FROM hubspot_contacts WHERE createdate BETWEEN ? AND ?",
            (since, until),
        ).fetchone()["c"]

        # Contactos por fuente Meta y Google
        contacts_meta = conn.execute(
            "SELECT COUNT(*) c FROM hubspot_contacts WHERE createdate BETWEEN ? AND ? "
            "AND fuentes_de_captacion_especificas = ?",
            (since, until, HUBSPOT_META_SOURCE),
        ).fetchone()["c"]
        contacts_google = conn.execute(
            "SELECT COUNT(*) c FROM hubspot_contacts WHERE createdate BETWEEN ? AND ? "
            "AND fuentes_de_captacion_especificas = ?",
            (since, until, HUBSPOT_GOOGLE_SOURCE),
        ).fetchone()["c"]

        # Deals ganados (por createdate del deal, no closedate, para alinear con el resto)
        deals_won_row = conn.execute(
            "SELECT COUNT(*) c, COALESCE(SUM(amount), 0) revenue FROM hubspot_deals "
            "WHERE is_won = 1 AND createdate BETWEEN ? AND ?",
            (since, until),
        ).fetchone()

        # Revenue por fuente (cruce deal -> contacto)
        revenue_by_source = {}
        for r in conn.execute(
            """
            SELECT COALESCE(c.fuentes_de_captacion_especificas, '(sin atribucion)') src,
                   COALESCE(SUM(d.amount), 0) revenue,
                   COUNT(DISTINCT d.id) deals
            FROM hubspot_deals d
            LEFT JOIN hubspot_deal_contacts dc ON dc.deal_id = d.id
            LEFT JOIN hubspot_contacts c ON c.id = dc.contact_id
            WHERE d.is_won = 1 AND d.createdate BETWEEN ? AND ?
            GROUP BY c.fuentes_de_captacion_especificas
            """,
            (since, until),
        ):
            revenue_by_source[r["src"]] = {"revenue": round(r["revenue"], 2), "deals": r["deals"]}

        # Ultimo sync HubSpot OK
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
    """Funnel completo Meta: spend -> leads Meta -> contactos HS -> ganados HS -> revenue."""
    days_param = request.args.get("days", "30")
    since_meta, until_meta, _days = _resolve_range(days_param)
    since_hs, until_hs = _hubspot_date_range(days_param)

    with _get_conn() as conn:
        # Meta side
        r = conn.execute(
            "SELECT COALESCE(SUM(spend),0) spend FROM insights_daily WHERE date BETWEEN ? AND ?",
            (since_meta, until_meta),
        ).fetchone()
        meta_spend = round(r["spend"], 2)

        meta_leads = sum(_fetch_leads_by_campaign(conn, since_meta, until_meta).values())

        # HubSpot side - solo Meta source
        contacts_meta = conn.execute(
            "SELECT COUNT(*) c FROM hubspot_contacts WHERE createdate BETWEEN ? AND ? "
            "AND fuentes_de_captacion_especificas = ?",
            (since_hs, until_hs, HUBSPOT_META_SOURCE),
        ).fetchone()["c"]

        # Contactos Meta ganados (lead_status terminal positivo)
        contacts_meta_won = conn.execute(
            """
            SELECT COUNT(*) c FROM hubspot_contacts
            WHERE createdate BETWEEN ? AND ?
              AND fuentes_de_captacion_especificas = ?
              AND hs_lead_status IN (
                'Terminado | Compra Web',
                'Terminado | Proyecto ganado',
                'Terminado | Distribuidor convertido en cliente'
              )
            """,
            (since_hs, until_hs, HUBSPOT_META_SOURCE),
        ).fetchone()["c"]

        # Revenue Meta (deals won asociados a contactos Meta)
        rev = conn.execute(
            """
            SELECT COALESCE(SUM(d.amount), 0) revenue, COUNT(DISTINCT d.id) deals
            FROM hubspot_deals d
            JOIN hubspot_deal_contacts dc ON dc.deal_id = d.id
            JOIN hubspot_contacts c ON c.id = dc.contact_id
            WHERE d.is_won = 1
              AND d.createdate BETWEEN ? AND ?
              AND c.fuentes_de_captacion_especificas = ?
            """,
            (since_hs, until_hs, HUBSPOT_META_SOURCE),
        ).fetchone()
        revenue_meta = round(rev["revenue"], 2)
        deals_meta = rev["deals"]

    roas = (revenue_meta / meta_spend) if meta_spend else 0
    cpl_real = (meta_spend / contacts_meta) if contacts_meta else 0
    cac = (meta_spend / contacts_meta_won) if contacts_meta_won else 0

    return jsonify({
        "since": since_meta,
        "until": until_meta,
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
    """Distribucion de contactos y revenue por fuente de captacion."""
    days_param = request.args.get("days", "30")
    since, until = _hubspot_date_range(days_param)

    with _get_conn() as conn:
        # Contactos por fuente
        rows = conn.execute(
            """
            SELECT COALESCE(fuentes_de_captacion_especificas, '(sin atribucion)') fuente,
                   COUNT(*) contactos
            FROM hubspot_contacts
            WHERE createdate BETWEEN ? AND ?
            GROUP BY fuentes_de_captacion_especificas
            ORDER BY contactos DESC
            """,
            (since, until),
        ).fetchall()
        contacts_by_source = {r["fuente"]: r["contactos"] for r in rows}

        # Revenue por fuente (deal -> contacto)
        rev_rows = conn.execute(
            """
            SELECT COALESCE(c.fuentes_de_captacion_especificas, '(sin atribucion)') fuente,
                   COALESCE(SUM(d.amount), 0) revenue,
                   COUNT(DISTINCT d.id) deals
            FROM hubspot_deals d
            LEFT JOIN hubspot_deal_contacts dc ON dc.deal_id = d.id
            LEFT JOIN hubspot_contacts c ON c.id = dc.contact_id
            WHERE d.is_won = 1 AND d.createdate BETWEEN ? AND ?
            GROUP BY c.fuentes_de_captacion_especificas
            """,
            (since, until),
        ).fetchall()
        revenue_by_source = {r["fuente"]: {"revenue": round(r["revenue"], 2), "deals": r["deals"]} for r in rev_rows}

        # Contactos ganados por fuente (estados terminales positivos)
        won_rows = conn.execute(
            """
            SELECT COALESCE(fuentes_de_captacion_especificas, '(sin atribucion)') fuente,
                   COUNT(*) ganados
            FROM hubspot_contacts
            WHERE createdate BETWEEN ? AND ?
              AND hs_lead_status IN (
                'Terminado | Compra Web',
                'Terminado | Proyecto ganado',
                'Terminado | Distribuidor convertido en cliente'
              )
            GROUP BY fuentes_de_captacion_especificas
            """,
            (since, until),
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
    """Distribucion de contactos por hs_lead_status."""
    days_param = request.args.get("days", "30")
    since, until = _hubspot_date_range(days_param)

    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT COALESCE(hs_lead_status, '(sin estado)') estado, COUNT(*) c
            FROM hubspot_contacts
            WHERE createdate BETWEEN ? AND ?
            GROUP BY hs_lead_status
            ORDER BY c DESC
            """,
            (since, until),
        ).fetchall()
    return jsonify([{"estado": r["estado"], "contactos": r["c"]} for r in rows])


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
