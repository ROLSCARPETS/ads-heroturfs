"""Extractor de HubSpot CRM hacia SQLite local.

Trae:
- Pipelines de deals + sus stages (con probabilidad)
- Contactos (con propiedades clave: pais, fuente de captacion, lead status)
- Deals (con amount, stage, fechas, fuente analytics)
- Asociaciones deal -> contactos

Uso:
    python hubspot_sync.py                       # full sync (todo el historico)
    python hubspot_sync.py --since 2026-01-01    # solo cambios desde fecha
    python hubspot_sync.py --days 30             # solo modificados ultimos 30 dias
"""

import argparse
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

import db

load_dotenv()

ACCESS_TOKEN = os.getenv("HUBSPOT_ACCESS_TOKEN")
BASE_URL = "https://api.hubapi.com"

CONTACT_PROPERTIES = [
    "email",
    "firstname",
    "lastname",
    "createdate",
    "lastmodifieddate",
    "lifecyclestage",
    "pais",
    "fuentes_de_captacion_especificas",
    "hs_lead_status",
    "hs_customer_agent_lead_status",
]

DEAL_PROPERTIES = [
    "dealname",
    "amount",
    "pipeline",
    "dealstage",
    "createdate",
    "closedate",
    "hs_lastmodifieddate",
    "hs_analytics_source",
    "hs_analytics_source_data_1",
    "hs_analytics_source_data_2",
]


class HubSpotAPIError(Exception):
    pass


def _headers():
    return {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}


def _get(path, params=None):
    r = requests.get(f"{BASE_URL}{path}", headers=_headers(), params=params, timeout=60)
    if r.status_code == 429:
        # Rate limit - esperar y reintentar
        retry = int(r.headers.get("X-HubSpot-RateLimit-Daily-Remaining", 1)) or 5
        time.sleep(min(retry, 10))
        return _get(path, params)
    if r.status_code != 200:
        raise HubSpotAPIError(f"GET {path} HTTP {r.status_code}: {r.text}")
    return r.json()


def _post(path, body):
    r = requests.post(f"{BASE_URL}{path}", headers=_headers(), json=body, timeout=60)
    if r.status_code == 429:
        time.sleep(5)
        return _post(path, body)
    if r.status_code not in (200, 201, 207):
        raise HubSpotAPIError(f"POST {path} HTTP {r.status_code}: {r.text}")
    return r.json()


def _to_iso_ms(dt):
    """HubSpot espera timestamps en ms epoch (UTC). dt debe ser date o datetime."""
    if isinstance(dt, date) and not isinstance(dt, datetime):
        dt = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
    return str(int(dt.timestamp() * 1000))


# ====================================================================
# Pipelines
# ====================================================================

def sync_pipelines():
    """Sincroniza pipelines y stages de deals."""
    data = _get("/crm/v3/pipelines/deals")
    count_pipelines = 0
    count_stages = 0
    with db.get_conn() as conn:
        for p in data.get("results", []):
            db.upsert_hubspot_pipeline(conn, p, "deals")
            count_pipelines += 1
            for s in p.get("stages", []):
                db.upsert_hubspot_stage(conn, p["id"], s, "deals")
                count_stages += 1
    print(f"      {count_pipelines} pipelines, {count_stages} stages")
    return count_pipelines


# ====================================================================
# Search paginado generico
# ====================================================================

def _search_paginated(object_type, properties, since=None, limit=100):
    """Itera todos los resultados del endpoint /search del object_type dado.

    Si `since` se proporciona (datetime), filtra por hs_lastmodifieddate >= since.
    """
    path = f"/crm/v3/objects/{object_type}/search"
    after = None
    total = None
    fetched = 0

    # Construir filtro de fecha si aplica
    filter_groups = []
    if since:
        date_prop = "hs_lastmodifieddate" if object_type == "deals" else "lastmodifieddate"
        filter_groups = [{"filters": [{
            "propertyName": date_prop,
            "operator": "GTE",
            "value": _to_iso_ms(since),
        }]}]

    while True:
        body = {
            "properties": properties,
            "limit": limit,
            "sorts": [{"propertyName": "createdate", "direction": "ASCENDING"}],
        }
        if filter_groups:
            body["filterGroups"] = filter_groups
        if after:
            body["after"] = after

        data = _post(path, body)
        if total is None:
            total = data.get("total", 0)
            print(f"      {total} {object_type} para sincronizar")

        for item in data.get("results", []):
            yield item
            fetched += 1

        nxt = data.get("paging", {}).get("next", {}).get("after")
        if not nxt:
            break
        after = nxt
        # Pequena pausa para evitar rate limiting agresivo
        time.sleep(0.05)

    print(f"      Procesados: {fetched}")


# ====================================================================
# Contactos
# ====================================================================

def sync_contacts(since=None):
    count = 0
    with db.get_conn() as conn:
        for c in _search_paginated("contacts", CONTACT_PROPERTIES, since=since):
            db.upsert_hubspot_contact(conn, c)
            count += 1
            if count % 500 == 0:
                conn.commit()  # Flush parcial para no perder todo si peta
                print(f"        ...{count} contactos sincronizados")
    return count


# ====================================================================
# Deals
# ====================================================================

def sync_deals(since=None):
    """Sincroniza deals usando el mapa de probabilidades de stages para is_won/is_lost."""
    with db.get_conn() as conn:
        prob_map = db.stage_probability_map(conn)

    deal_ids = []
    count = 0
    with db.get_conn() as conn:
        for d in _search_paginated("deals", DEAL_PROPERTIES, since=since):
            db.upsert_hubspot_deal(conn, d, prob_map)
            deal_ids.append(d["id"])
            count += 1
    return count, deal_ids


# ====================================================================
# Asociaciones deals -> contacts (batch)
# ====================================================================

def sync_deal_contact_associations(deal_ids):
    """Para cada deal, obtiene sus contactos asociados via batch API."""
    if not deal_ids:
        return 0

    count = 0
    BATCH = 100
    with db.get_conn() as conn:
        for i in range(0, len(deal_ids), BATCH):
            chunk = deal_ids[i:i + BATCH]
            body = {"inputs": [{"id": d} for d in chunk]}
            data = _post("/crm/v4/associations/deals/contacts/batch/read", body)
            for entry in data.get("results", []):
                deal_id = entry.get("from", {}).get("id")
                # Borramos asociaciones previas y reinsertamos
                db.clear_hubspot_deal_contacts_for_deal(conn, deal_id)
                for assoc in entry.get("to", []):
                    contact_id = assoc.get("toObjectId")
                    if contact_id:
                        db.upsert_hubspot_deal_contact(conn, deal_id, str(contact_id))
                        count += 1
            time.sleep(0.05)
    return count


# ====================================================================
# Sync principal
# ====================================================================

def sync(since=None):
    if not ACCESS_TOKEN:
        print("ERROR: falta HUBSPOT_ACCESS_TOKEN en .env", file=sys.stderr)
        sys.exit(1)

    print(f"[init] DB en {db.DB_PATH}")
    if since:
        print(f"[init] Sync incremental: cambios desde {since.isoformat()}")
    else:
        print("[init] Sync completo: todos los contactos y deals")
    db.init_db()

    with db.get_conn() as conn:
        sync_id = db.log_hubspot_sync_start(conn)

    contacts = deals = pipelines = associations = 0
    try:
        print("[1/4] Pipelines y stages de deals...")
        pipelines = sync_pipelines()

        print("[2/4] Contactos...")
        contacts = sync_contacts(since=since)

        print("[3/4] Deals...")
        deals, deal_ids = sync_deals(since=since)

        print("[4/4] Asociaciones deals -> contactos...")
        associations = sync_deal_contact_associations(deal_ids)
        print(f"      {associations} asociaciones")

        with db.get_conn() as conn:
            db.log_hubspot_sync_finish(conn, sync_id, contacts, deals, pipelines, associations, "ok")
        print(f"\n[OK] Sync HubSpot completo: {contacts} contactos, {deals} deals, {associations} asociaciones")

    except Exception as e:
        with db.get_conn() as conn:
            db.log_hubspot_sync_finish(conn, sync_id, contacts, deals, pipelines, associations, "error", str(e))
        print(f"\n[ERROR] {e}", file=sys.stderr)
        raise


def _parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def main():
    parser = argparse.ArgumentParser(description="Sincroniza HubSpot CRM (contactos + deals) a SQLite local.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--since", type=_parse_date, help="Fecha inicio YYYY-MM-DD (incremental).")
    group.add_argument("--days", type=int, help="Solo registros modificados ultimos N dias.")
    args = parser.parse_args()

    since = args.since
    if args.days:
        since = datetime.now(timezone.utc) - timedelta(days=args.days)

    sync(since=since)


if __name__ == "__main__":
    main()
