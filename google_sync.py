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

    Trae tambien el presupuesto diario (campaign_budget.amount_micros).
    Nota: campaign.start_date y campaign.end_date se eliminaron de la API v24,
    asi que las columnas correspondientes en BBDD quedan a NULL.
    """
    service = client.get_service("GoogleAdsService")
    query = """
        SELECT
            campaign.id,
            campaign.name,
            campaign.status,
            campaign.advertising_channel_type,
            campaign_budget.amount_micros,
            campaign_budget.period
        FROM campaign
        WHERE campaign.status != 'REMOVED'
        ORDER BY campaign.id
    """
    response = service.search(customer_id=CUSTOMER_ID, query=query)
    out = []
    for row in response:
        amount_micros = row.campaign_budget.amount_micros if row.campaign_budget else 0
        budget_period = row.campaign_budget.period.name if row.campaign_budget else None
        out.append({
            "id": str(row.campaign.id),
            "name": row.campaign.name,
            "status": row.campaign.status.name,
            "advertising_channel_type": row.campaign.advertising_channel_type.name,
            "start_date": None,
            "end_date": None,
            "daily_budget": (amount_micros or 0) / 1_000_000,
            "budget_period": budget_period,
        })
    return out


def fetch_budget_change_events(client):
    """Trae eventos de cambio de CAMPAIGN_BUDGET de los ultimos 30 dias.

    Google Ads solo retiene change_event durante 30 dias. Cada evento incluye
    old_amount_micros y new_amount_micros, lo que nos permite reconstruir la
    timeline historica del budget.
    """
    service = client.get_service("GoogleAdsService")
    # Google Ads NO permite consultar mas de 30 dias en change_event.
    # Usamos hace 29 dias para evitar errores de borde.
    since_dt = (date.today() - timedelta(days=29)).strftime("%Y-%m-%d 00:00:00")
    until_dt = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")
    # En GAQL no se pueden seleccionar subcampos de old_resource/new_resource:
    # hay que pedir el recurso entero y parsearlo desde Python.
    # Google obliga a rango finito (since + until), no infinito.
    query = f"""
        SELECT
            change_event.change_date_time,
            change_event.resource_change_operation,
            change_event.old_resource,
            change_event.new_resource,
            change_event.campaign,
            campaign.id
        FROM change_event
        WHERE change_event.change_date_time >= '{since_dt}'
          AND change_event.change_date_time <= '{until_dt}'
          AND change_event.change_resource_type = 'CAMPAIGN_BUDGET'
        ORDER BY change_event.change_date_time DESC
        LIMIT 10000
    """
    out = []
    try:
        response = service.search(customer_id=CUSTOMER_ID, query=query)
        for row in response:
            cid = None
            if row.campaign and row.campaign.id:
                cid = str(row.campaign.id)
            else:
                cstr = str(getattr(row.change_event, "campaign", "") or "")
                if "/campaigns/" in cstr:
                    cid = cstr.split("/campaigns/")[-1]
            old_micros = 0
            new_micros = 0
            try:
                old_micros = row.change_event.old_resource.campaign_budget.amount_micros or 0
            except Exception:
                pass
            try:
                new_micros = row.change_event.new_resource.campaign_budget.amount_micros or 0
            except Exception:
                pass
            out.append({
                "campaign_id": cid,
                "change_date": str(row.change_event.change_date_time)[:10],
                "change_date_time": str(row.change_event.change_date_time),
                "old_amount_micros": old_micros,
                "new_amount_micros": new_micros,
            })
    except Exception as e:
        print(f"      [WARN] No se pudieron leer change_events (puede ser permisos limitados): {e}")
    return out


def build_budget_timeline(current_budgets, events, days_back=90):
    """Construye timeline (campaign_id, date, budget) para los ultimos `days_back` dias.

    Algoritmo:
    - rolling = budget actual de la campana
    - Iteramos dias desde hoy hacia atras
    - Eventos ordenados DESC por fecha
    - Si hay evento entre target_day+1 y today, antes del evento el budget era ev.old
      -> aplicamos: rolling = ev.old_amount_micros / 1e6
    - Si el evento ya esta en target_day o antes, ese cambio ya estaba aplicado, paramos

    Devuelve dict {(campaign_id, date_iso): daily_budget}.
    """
    today = date.today()
    since_date = today - timedelta(days=days_back)

    events_by_campaign = {}
    for ev in events:
        cid = ev.get("campaign_id")
        if not cid:
            continue
        events_by_campaign.setdefault(cid, []).append(ev)
    # Cada lista ordenada DESC por change_date_time (string ISO -> sort directo funciona)
    for cid in events_by_campaign:
        events_by_campaign[cid].sort(key=lambda e: e["change_date_time"], reverse=True)

    timeline = {}
    for cid, cur in current_budgets.items():
        events_desc = events_by_campaign.get(cid, [])
        # Para cada dia desde today hasta since_date, calcular budget
        for offset in range(days_back + 1):
            target_day = today - timedelta(days=offset)
            if target_day < since_date:
                break
            rolling = cur or 0
            for ev in events_desc:
                ev_date_str = ev["change_date"]
                # ev_date > target_day: el evento es posterior, antes el budget era old
                if ev_date_str > target_day.isoformat():
                    rolling = (ev.get("old_amount_micros") or 0) / 1_000_000
                else:
                    # ev ya esta en o antes de target_day: budget aplicado, stop
                    break
            timeline[(cid, target_day.isoformat())] = rolling
    return timeline


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

        print("[1/3] Trayendo campanas...")
        campaigns = fetch_campaigns(client)
        print(f"      {len(campaigns)} campanas encontradas")
        with db.get_conn() as conn:
            for c in campaigns:
                country = country_for_campaign(c.get("name"))
                db.upsert_google_campaign(conn, c, country=country)
                campaigns_count += 1

        # Histórico de budget: change_event + snapshot del día actual
        print("[2/3] Trayendo histórico de budget (ultimos 30 dias)...")
        events = fetch_budget_change_events(client)
        print(f"      {len(events)} eventos de cambio de budget")
        current_budgets = {c["id"]: (c.get("daily_budget") or 0) for c in campaigns}
        timeline = build_budget_timeline(current_budgets, events, days_back=90)
        # Marcamos fuente: si hay events_by_campaign para esa campana, los dias
        # post-evento son "change_event"; en cualquier caso lo guardamos para tener historico.
        with db.get_conn() as conn:
            for (cid, day), budget in timeline.items():
                source = "change_event" if events else "current"
                # El dia de hoy lo marcamos como snapshot (siempre exacto)
                if day == date.today().isoformat():
                    source = "snapshot"
                db.upsert_google_budget_history(conn, cid, day, budget, source)
        print(f"      Timeline guardada: {len(timeline)} (campana, dia) entries")

        print("[3/3] Trayendo insights diarios...")
        insights = fetch_insights(client, since, until)
        print(f"      {len(insights)} filas de insights")
        with db.get_conn() as conn:
            for row in insights:
                db.upsert_google_insight(conn, row)
                insights_count += 1

        with db.get_conn() as conn:
            db.log_google_sync_finish(conn, sync_id, campaigns_count, insights_count, "ok")
        print(f"\n[OK] Sync Google Ads completo: {campaigns_count} campanas, {insights_count} insights, {len(timeline)} entradas budget history")

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
