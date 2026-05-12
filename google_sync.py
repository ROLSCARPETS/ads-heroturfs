"""Extractor de Google Ads API hacia SQLite local.

Trae:
- Lista de campanas activas/pausadas
- Insights diarios por campana (impressions, clicks, cost, conversiones)

Uso:
    python google_sync.py                           # ultimos SYNC_DAYS_BACK dias
    python google_sync.py --days 180
    python google_sync.py --since 2025-01-01
    python google_sync.py --since 2025-01-01 --until 2025-12-31

Requiere en .env:
    GOOGLE_DEVELOPER_TOKEN     (pendiente aprobacion Basic Access en Google)
    GOOGLE_CLIENT_ID
    GOOGLE_CLIENT_SECRET
    GOOGLE_REFRESH_TOKEN       (generado con _get_google_refresh_token.py)
    GOOGLE_LOGIN_CUSTOMER_ID   (MCC, sin guiones)
    GOOGLE_CUSTOMER_ID         (cuenta operativa, sin guiones)
"""

import argparse
import os
import sys
from datetime import date, datetime, timedelta

from dotenv import load_dotenv

import db
from campaign_country import country_for_campaign

load_dotenv()

DEVELOPER_TOKEN = os.getenv("GOOGLE_DEVELOPER_TOKEN")
CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("GOOGLE_REFRESH_TOKEN")
LOGIN_CUSTOMER_ID = os.getenv("GOOGLE_LOGIN_CUSTOMER_ID")
CUSTOMER_ID = os.getenv("GOOGLE_CUSTOMER_ID")
DAYS_BACK = int(os.getenv("SYNC_DAYS_BACK", "90"))


def _build_client():
    """Crea GoogleAdsClient desde variables de entorno.

    Importacion lazy para que el modulo se pueda importar sin tener
    instalado google-ads (util si solo queremos correr Meta o HubSpot).
    """
    if not DEVELOPER_TOKEN:
        raise RuntimeError(
            "Falta GOOGLE_DEVELOPER_TOKEN en .env. "
            "Solicitarlo en https://ads.google.com/aw/apicenter (Basic Access). "
            "Aprobacion 24-72h por email."
        )
    missing = [k for k, v in {
        "GOOGLE_CLIENT_ID": CLIENT_ID,
        "GOOGLE_CLIENT_SECRET": CLIENT_SECRET,
        "GOOGLE_REFRESH_TOKEN": REFRESH_TOKEN,
        "GOOGLE_LOGIN_CUSTOMER_ID": LOGIN_CUSTOMER_ID,
        "GOOGLE_CUSTOMER_ID": CUSTOMER_ID,
    }.items() if not v]
    if missing:
        raise RuntimeError(f"Faltan variables en .env: {', '.join(missing)}")

    from google.ads.googleads.client import GoogleAdsClient
    config = {
        "developer_token": DEVELOPER_TOKEN,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": REFRESH_TOKEN,
        "login_customer_id": LOGIN_CUSTOMER_ID,
        "use_proto_plus": True,
    }
    return GoogleAdsClient.load_from_dict(config)


def fetch_campaigns(client):
    """Lista campanas (incluidas pausadas) excepto las eliminadas.

    Nota: campaign.start_date y campaign.end_date se eliminaron de la API v24,
    asi que las columnas correspondientes en BBDD quedan a NULL (no se usan
    en el dashboard).
    """
    service = client.get_service("GoogleAdsService")
    query = """
        SELECT
            campaign.id,
            campaign.name,
            campaign.status,
            campaign.advertising_channel_type
        FROM campaign
        WHERE campaign.status != 'REMOVED'
        ORDER BY campaign.id
    """
    response = service.search(customer_id=CUSTOMER_ID, query=query)
    out = []
    for row in response:
        out.append({
            "id": str(row.campaign.id),
            "name": row.campaign.name,
            "status": row.campaign.status.name,
            "advertising_channel_type": row.campaign.advertising_channel_type.name,
            "start_date": None,
            "end_date": None,
        })
    return out


def fetch_insights(client, since, until):
    """Insights diarios por campana entre `since` y `until` (objetos date).

    Google Ads expone metrics.cost_micros (1 EUR = 1.000.000 micros).
    """
    service = client.get_service("GoogleAdsService")
    query = f"""
        SELECT
            campaign.id,
            segments.date,
            metrics.impressions,
            metrics.clicks,
            metrics.cost_micros,
            metrics.conversions,
            metrics.conversions_value,
            metrics.ctr,
            metrics.average_cpc,
            metrics.average_cpm
        FROM campaign
        WHERE segments.date BETWEEN '{since.isoformat()}' AND '{until.isoformat()}'
          AND campaign.status != 'REMOVED'
        ORDER BY segments.date, campaign.id
    """
    response = service.search(customer_id=CUSTOMER_ID, query=query)
    out = []
    for r in response:
        m = r.metrics
        out.append({
            "campaign_id": str(r.campaign.id),
            "date": r.segments.date,
            "impressions": int(m.impressions),
            "clicks": int(m.clicks),
            "cost": (m.cost_micros or 0) / 1_000_000,
            "conversions": float(m.conversions),
            "conversion_value": float(m.conversions_value),
            "ctr": float(m.ctr) * 100,  # ctr viene como decimal (0.012 = 1.2%)
            "cpc": (m.average_cpc or 0) / 1_000_000,
            "cpm": (m.average_cpm or 0) / 1_000_000,
        })
    return out


def sync(since=None, until=None):
    if until is None:
        until = date.today()
    if since is None:
        since = until - timedelta(days=DAYS_BACK)
    days_span = (until - since).days

    print(f"[init] DB en {db.DB_PATH}")
    print(f"[init] Rango: {since.isoformat()} -> {until.isoformat()} ({days_span} dias)")
    print(f"[init] Customer: {CUSTOMER_ID} (login MCC: {LOGIN_CUSTOMER_ID})")
    db.init_db()

    with db.get_conn() as conn:
        sync_id = db.log_google_sync_start(conn, days_span)

    campaigns_count = 0
    insights_count = 0

    try:
        client = _build_client()

        print("[1/2] Trayendo campanas...")
        campaigns = fetch_campaigns(client)
        print(f"      {len(campaigns)} campanas encontradas")
        with db.get_conn() as conn:
            for c in campaigns:
                country = country_for_campaign(c.get("name"))
                db.upsert_google_campaign(conn, c, country=country)
                campaigns_count += 1

        print("[2/2] Trayendo insights diarios...")
        insights = fetch_insights(client, since, until)
        print(f"      {len(insights)} filas de insights")
        with db.get_conn() as conn:
            for row in insights:
                db.upsert_google_insight(conn, row)
                insights_count += 1

        with db.get_conn() as conn:
            db.log_google_sync_finish(conn, sync_id, campaigns_count, insights_count, "ok")
        print(f"\n[OK] Sync Google Ads completo: {campaigns_count} campanas, {insights_count} insights")

    except Exception as e:
        msg = str(e)
        # Si es GoogleAdsException, sacar mensajes mas legibles
        try:
            from google.ads.googleads.errors import GoogleAdsException
            if isinstance(e, GoogleAdsException):
                msg = "; ".join(f"{err.error_code}: {err.message}" for err in e.failure.errors)
        except ImportError:
            pass
        with db.get_conn() as conn:
            db.log_google_sync_finish(conn, sync_id, campaigns_count, insights_count, "error", msg)
        print(f"\n[ERROR] {msg}", file=sys.stderr)
        raise


def _parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def main():
    parser = argparse.ArgumentParser(description="Sincroniza Google Ads a SQLite local.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--days", type=int, help=f"Dias hacia atras (default {DAYS_BACK}).")
    group.add_argument("--since", type=_parse_date, help="Fecha YYYY-MM-DD.")
    parser.add_argument("--until", type=_parse_date, help="Fecha YYYY-MM-DD (default hoy).")
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
