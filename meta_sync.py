"""Extractor de Meta Marketing API hacia SQLite local.

Trae:
- Lista de campanas del ad account
- Insights diarios por campana (rango configurable)
- Acciones (conversiones, etc.) diarias por campana

Uso:
    python meta_sync.py                          # ultimos SYNC_DAYS_BACK dias (.env, default 90)
    python meta_sync.py --days 180               # ultimos 180 dias
    python meta_sync.py --since 2025-01-01       # desde 2025-01-01 hasta hoy
    python meta_sync.py --since 2025-01-01 --until 2025-12-31
"""

import argparse
import os
import sys
from datetime import date, datetime, timedelta

import requests
from dotenv import load_dotenv

import db
from campaign_country import country_for_campaign

load_dotenv()

ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID")
API_VERSION = os.getenv("META_API_VERSION", "v21.0")
DAYS_BACK = int(os.getenv("SYNC_DAYS_BACK", "90"))

BASE_URL = f"https://graph.facebook.com/{API_VERSION}"


class MetaAPIError(Exception):
    pass


def _get(path, params=None):
    """Llama a la Graph API y devuelve el JSON. Lanza MetaAPIError si falla."""
    params = dict(params or {})
    params["access_token"] = ACCESS_TOKEN
    url = f"{BASE_URL}/{path}"
    r = requests.get(url, params=params, timeout=120)
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
        r = requests.get(next_url, timeout=120)
        if r.status_code != 200:
            raise MetaAPIError(f"Pagination HTTP {r.status_code}: {r.text}")
        data = r.json()
        for item in data.get("data", []):
            yield item


def fetch_campaigns():
    fields = "id,name,status,effective_status,objective,daily_budget,lifetime_budget,created_time,start_time,stop_time"
    path = f"{AD_ACCOUNT_ID}/campaigns"
    return list(_paginate(path, {"fields": fields, "limit": 100}))


def fetch_insights(since, until):
    """Trae insights diarios por campana entre `since` y `until` (objetos date)."""
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


def sync(since=None, until=None):
    """Ejecuta el sync. Si no se pasan fechas, usa SYNC_DAYS_BACK del .env."""
    if not ACCESS_TOKEN or not AD_ACCOUNT_ID:
        print("ERROR: faltan META_ACCESS_TOKEN o META_AD_ACCOUNT_ID en .env", file=sys.stderr)
        sys.exit(1)

    if until is None:
        until = date.today()
    if since is None:
        since = until - timedelta(days=DAYS_BACK)

    days_span = (until - since).days

    print(f"[init] DB en {db.DB_PATH}")
    print(f"[init] Rango: {since.isoformat()} -> {until.isoformat()} ({days_span} dias)")
    db.init_db()

    with db.get_conn() as conn:
        sync_id = db.log_sync_start(conn, days_span)

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
                country = country_for_campaign(c.get("name"))
                db.upsert_campaign(conn, c, country=country)
                campaigns_count += 1

        # 2. Insights diarios
        print(f"[2/2] Trayendo insights diarios...")
        insights = fetch_insights(since, until)
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


def _parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def main():
    parser = argparse.ArgumentParser(description="Sincroniza datos de Meta Ads a SQLite local.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--days", type=int, help=f"Numero de dias hacia atras desde hoy (default: {DAYS_BACK} de .env).")
    group.add_argument("--since", type=_parse_date, help="Fecha de inicio YYYY-MM-DD.")
    parser.add_argument("--until", type=_parse_date, help="Fecha de fin YYYY-MM-DD (default: hoy).")
    args = parser.parse_args()

    until = args.until or date.today()
    if args.since:
        since = args.since
    elif args.days:
        since = until - timedelta(days=args.days)
    else:
        since = until - timedelta(days=DAYS_BACK)

    sync(since=since, until=until)


if __name__ == "__main__":
    main()
