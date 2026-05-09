"""Dashboard web Flask para analisis de campanas Meta Ads de Heroturfs."""

import sqlite3
from datetime import date, timedelta
from pathlib import Path

from flask import Flask, jsonify, render_template, request

import db
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


def _date_range(days):
    until = date.today()
    since = until - timedelta(days=days - 1)
    return since.isoformat(), until.isoformat()


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


def _fetch_leads_by_date(conn, since, until):
    placeholders = ",".join("?" for _ in LEAD_ACTION_TYPES)
    rows = conn.execute(
        f"""
        SELECT date, SUM(value) AS leads
        FROM actions_daily
        WHERE date BETWEEN ? AND ?
          AND action_type IN ({placeholders})
        GROUP BY date
        ORDER BY date
        """,
        (since, until, *LEAD_ACTION_TYPES),
    ).fetchall()
    return {r["date"]: r["leads"] or 0 for r in rows}


@app.route("/")
def index():
    return render_template("dashboard.html")


@app.route("/api/kpis")
def api_kpis():
    days = int(request.args.get("days", 30))
    since, until = _date_range(days)
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
    """Serie diaria de gasto, clicks y leads."""
    days = int(request.args.get("days", 30))
    since, until = _date_range(days)
    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT date, SUM(spend) spend, SUM(clicks) clicks, SUM(impressions) impressions
            FROM insights_daily
            WHERE date BETWEEN ? AND ?
            GROUP BY date
            ORDER BY date
            """,
            (since, until),
        ).fetchall()
        leads_by_date = _fetch_leads_by_date(conn, since, until)

    series = []
    for r in rows:
        d = r["date"]
        series.append(
            {
                "date": d,
                "spend": round(r["spend"] or 0, 2),
                "clicks": r["clicks"] or 0,
                "impressions": r["impressions"] or 0,
                "leads": int(leads_by_date.get(d, 0)),
            }
        )
    return jsonify(series)


@app.route("/api/campaigns")
def api_campaigns():
    """Tabla de campanas con metricas agregadas en el rango."""
    days = int(request.args.get("days", 30))
    since, until = _date_range(days)
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


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=True)
