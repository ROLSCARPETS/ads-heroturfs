"""Extractor de Meta Marketing API hacia SQLite local.

Trae:
- Lista de campanas del ad account
- Insights diarios por campana (ultimos N dias)
- Acciones (conversiones, etc.) diarias por campana

Uso:
    python meta_sync.py
"""

import os
import sys
from datetime import date, timedelta

import requests
from dotenv import load_dotenv

import db

load_dotenv()

ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID")
API_VERSION = os.getenv("META_API_VERSION", "v21.0")
DAYS_BACK = int(os.getenv("SYNC_DAYS_BACK", "30"))

BASE_URL = f"https://graph.facebook.com/{API_VERSION}"


class MetaAPIError(Exception):
    pass


def _get(path, params=None):
    """Llama a la Graph API y devuelve el JSON. Lanza MetaAPIError si falla."""
    params = dict(params or {})
    params["access_token"] = ACCESS_TOKEN
    url = f"{BASE_URL}/{path}"
    r = requests.get(url, params=params, timeout=60)
    if r.status_code != 200:
        try:
            err = r.json().get("error", {})
            msg = err.get("message", r.text)
        except Exception:
            msg = r.text
        raise MetaAPIError(f"HTTP {r.status_code}: {msg}")
    return r.json()


def _paginate(path, params=None):
    """Generador que itera todas las paginas de un endpoint."""
    data = _get(path, params)
    for item in data.get("data", []):
        yield item
    while True:
        next_url = data.get("paging", {}).get("next")
        if not next_url:
            break
        # next_url ya trae token y todos los params, llamada directa
        r = requests.get(next_url, timeout=60)
        if r.status_code != 200:
            raise MetaAPIError(f"Pagination HTTP {r.status_code}: {r.text}")
        data = r.json()
        for item in data.get("data", []):
            yield item


def fetch_campaigns():
    fields = "id,name,status,effective_status,objective,daily_budget,lifetime_budget,created_time,start_time,stop_time"
    path = f"{AD_ACCOUNT_ID}/campaigns"
    return list(_paginate(path, {"fields": fields, "limit": 100}))


def fetch_insights(days_back):
    """Trae insights diarios por campana de los ultimos N dias."""
    until = date.today()
    since = until - timedelta(days=days_back)
    fields = "campaign_id,date_start,impressions,reach,clicks,spend,ctr,cpc,cpm,frequency,actions,action_values"
    params = {
        "level": "campaign",
        "time_range": f'{{"since":"{since.isoformat()}","until":"{until.isoformat()}"}}',
        "time_increment": 1,
        "fields": fields,
        "limit": 500,
    }
    path = f"{AD_ACCOUNT_ID}/insights"
    return list(_paginate(path, params))


def sync():
    if not ACCESS_TOKEN or not AD_ACCOUNT_ID:
        print("ERROR: faltan META_ACCESS_TOKEN o META_AD_ACCOUNT_ID en .env", file=sys.stderr)
        sys.exit(1)

    print(f"[init] DB en {db.DB_PATH}")
    db.init_db()

    with db.get_conn() as conn:
        sync_id = db.log_sync_start(conn, DAYS_BACK)

    campaigns_count = 0
    insights_count = 0
    actions_count = 0

    try:
        # 1. Campanas
        print(f"[1/2] Trayendo campanas de {AD_ACCOUNT_ID}...")
        campaigns = fetch_campaigns()
        print(f"      {len(campaigns)} campanas encontradas")
        with db.get_conn() as conn:
            for c in campaigns:
                db.upsert_campaign(conn, c)
                campaigns_count += 1

        # 2. Insights diarios
        print(f"[2/2] Trayendo insights diarios (ultimos {DAYS_BACK} dias)...")
        insights = fetch_insights(DAYS_BACK)
        print(f"      {len(insights)} filas de insights")
        with db.get_conn() as conn:
            for ins in insights:
                row = {
                    "campaign_id": ins.get("campaign_id"),
                    "date": ins.get("date_start"),
                    "impressions": ins.get("impressions"),
                    "reach": ins.get("reach"),
                    "clicks": ins.get("clicks"),
                    "spend": ins.get("spend"),
                    "ctr": ins.get("ctr"),
                    "cpc": ins.get("cpc"),
                    "cpm": ins.get("cpm"),
                    "frequency": ins.get("frequency"),
                }
                db.upsert_insight(conn, row)
                insights_count += 1

                # Acciones - aplanamos por tipo
                actions_by_type = {}
                for a in ins.get("actions", []) or []:
                    actions_by_type[a["action_type"]] = {"value": a.get("value")}
                for a in ins.get("action_values", []) or []:
                    actions_by_type.setdefault(a["action_type"], {})["action_value"] = a.get("value")

                for action_type, vals in actions_by_type.items():
                    db.upsert_action(
                        conn,
                        ins["campaign_id"],
                        ins["date_start"],
                        action_type,
                        vals.get("value"),
                        vals.get("action_value"),
                    )
                    actions_count += 1

        with db.get_conn() as conn:
            db.log_sync_finish(conn, sync_id, campaigns_count, insights_count, actions_count, "ok")
        print(f"\n[OK] Sync completo: {campaigns_count} campanas, {insights_count} insights, {actions_count} acciones")

    except Exception as e:
        with db.get_conn() as conn:
            db.log_sync_finish(conn, sync_id, campaigns_count, insights_count, actions_count, "error", str(e))
        print(f"\n[ERROR] {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    sync()
