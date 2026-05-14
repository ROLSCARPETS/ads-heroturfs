"""Sincronizacion Navision Business Central 14 -> SQLite local.

Trae:
- workflowItems (maestro de productos, marcando is_heroturfs por categoria HT *)
- HistFactAreaPriv (cabeceras de facturas en el rango)
- HistLinFactVenAreaPriv (lineas de factura para los docs en rango, solo Type='Item')

Filtros:
- Solo company configurada (Merlot Iniciativas, S.L.)
- Por defecto ultimos SYNC_NAV_DAYS_BACK dias (2 anos = 730 default).
- Items completos (no se filtra: queremos saber tambien que items NO son HT
  porque pueden aparecer en lineas).

Uso:
    python navision_sync.py                        # ultimos 730 dias
    python navision_sync.py --days 90              # ultimos 90 dias
    python navision_sync.py --since 2025-01-01     # desde fecha
    python navision_sync.py --since 2018-01-01     # carga historica completa
"""

import argparse
import os
import sys
from datetime import date, datetime, timedelta
from urllib.parse import quote

import requests
from dotenv import load_dotenv

import db
from campaign_country import SUFFIX_TO_COUNTRY

load_dotenv()

BASE_URL = (os.getenv("NAVISION_BASE_URL") or "").rstrip("/")
COMPANY = os.getenv("NAVISION_COMPANY") or ""
USER = os.getenv("NAVISION_USER") or ""
KEY = os.getenv("NAVISION_KEY") or ""
AUTH_MODE = (os.getenv("NAVISION_AUTH") or "sspi").lower()
TIMEOUT = int(os.getenv("NAVISION_TIMEOUT", "60"))
DAYS_BACK = int(os.getenv("SYNC_NAV_DAYS_BACK", "730"))  # 2 anos por defecto


def _build_auth():
    if AUTH_MODE == "sspi":
        from requests_negotiate_sspi import HttpNegotiateAuth
        return HttpNegotiateAuth()
    if AUTH_MODE == "ntlm":
        from requests_ntlm import HttpNtlmAuth
        return HttpNtlmAuth(USER, KEY or "")
    if AUTH_MODE == "basic":
        return (USER, KEY)
    raise RuntimeError(f"NAVISION_AUTH desconocido: {AUTH_MODE}")


def _company_path():
    return f"Company('{quote(COMPANY, safe='')}')"


def _paginate(session, url, params=None):
    """Itera sobre todas las paginas de un endpoint OData V4 siguiendo
    @odata.nextLink. Yields cada item del array 'value'."""
    next_url = url
    next_params = dict(params or {})
    while next_url:
        r = session.get(next_url, params=next_params, timeout=TIMEOUT, verify=False)
        r.raise_for_status()
        data = r.json()
        for item in data.get("value", []):
            yield item
        next_url = data.get("@odata.nextLink")
        next_params = None  # nextLink ya trae los params embebidos


def _new_session():
    s = requests.Session()
    s.auth = _build_auth()
    # Suprime warnings de SSL al usar verify=False (server interno HTTP/no-HTTPS)
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass
    return s


def fetch_items(session):
    """Maestro de items: id + descripcion + categoria + UoM + precios.
    No filtra por marca (queremos saber is_heroturfs para todos)."""
    url = f"{BASE_URL}/{_company_path()}/workflowItems"
    params = {
        "$select": "number,description,itemCategoryCode,baseUnitOfMeasure,unitPrice,unitCost",
    }
    out = []
    for r in _paginate(session, url, params):
        out.append({
            "item_no": r.get("number"),
            "description": (r.get("description") or "").strip(),
            "item_category_code": (r.get("itemCategoryCode") or "").strip(),
            "base_uom": r.get("baseUnitOfMeasure"),
            "unit_price": r.get("unitPrice"),
            "unit_cost": r.get("unitCost"),
        })
    return out


def fetch_invoices(session, since_iso):
    """Cabeceras de facturas con Posting_Date >= since_iso."""
    url = f"{BASE_URL}/{_company_path()}/HistFactAreaPriv"
    params = {
        "$select": (
            "No,Order_No,Posting_Date,Sell_to_Customer_No,Sell_to_Customer_Name,"
            "Sell_to_Country_Region_Code,Salesperson_Code,Amount,Amount_Including_VAT,"
            "Remaining_Amount,Currency_Code"
        ),
        "$filter": f"Posting_Date ge {since_iso}",
        "$orderby": "Posting_Date asc",
    }
    out = []
    for r in _paginate(session, url, params):
        country_code = (r.get("Sell_to_Country_Region_Code") or "").strip().upper()
        country = SUFFIX_TO_COUNTRY.get(country_code) or country_code or None
        out.append({
            "invoice_no": r.get("No"),
            "order_no": r.get("Order_No"),
            "posting_date": r.get("Posting_Date"),
            "customer_no": r.get("Sell_to_Customer_No"),
            "customer_name": r.get("Sell_to_Customer_Name"),
            "sell_country_code": country_code or None,
            "sell_country": country,
            "salesperson_code": r.get("Salesperson_Code"),
            "amount": r.get("Amount"),
            "amount_with_vat": r.get("Amount_Including_VAT"),
            "remaining_amount": r.get("Remaining_Amount"),
            "currency_code": r.get("Currency_Code"),
        })
    return out


def fetch_invoice_lines_for(session, invoice_no):
    """Lineas Type='Item' de una factura concreta. Filtra G/L Account, etc."""
    url = f"{BASE_URL}/{_company_path()}/HistLinFactVenAreaPriv"
    params = {
        "$select": "Document_No,Line_No,No,Description,Quantity,Unit_Price,Amount",
        "$filter": f"Document_No eq '{invoice_no}' and Type eq 'Item'",
    }
    out = []
    for r in _paginate(session, url, params):
        out.append({
            "invoice_no": r.get("Document_No"),
            "line_no": r.get("Line_No"),
            "item_no": (r.get("No") or "").strip(),
            "description": (r.get("Description") or "").strip(),
            "quantity": r.get("Quantity"),
            "unit_price": r.get("Unit_Price"),
            "amount": r.get("Amount"),
        })
    return out


def sync(since=None, until=None):
    """until se ignora actualmente (siempre hasta hoy). since limita el desde."""
    if since is None:
        since = date.today() - timedelta(days=DAYS_BACK)
    since_iso = since.isoformat()

    print(f"[init] DB en {db.DB_PATH}")
    print(f"[init] Auth: {AUTH_MODE} | Company: {COMPANY}")
    print(f"[init] Facturas desde: {since_iso}")
    db.init_db()

    with db.get_conn() as conn:
        sync_id = db.log_navision_sync_start(conn, days_back=(date.today() - since).days)

    items_count = 0
    invoices_count = 0
    lines_count = 0

    try:
        session = _new_session()

        print("[1/3] Trayendo items (maestro completo)...")
        items = fetch_items(session)
        ht_items = set()
        with db.get_conn() as conn:
            for it in items:
                db.upsert_navision_item(conn, it)
                cat = (it.get("item_category_code") or "").strip().upper()
                if cat.startswith("HT "):
                    ht_items.add(it["item_no"])
                items_count += 1
        print(f"      {items_count} items ({len(ht_items)} marcados como Heroturfs)")

        print(f"[2/3] Trayendo cabeceras de facturas (Posting_Date >= {since_iso})...")
        invoices = fetch_invoices(session, since_iso)
        with db.get_conn() as conn:
            for inv in invoices:
                db.upsert_navision_invoice(conn, inv)
                invoices_count += 1
        print(f"      {invoices_count} facturas")

        print(f"[3/3] Trayendo lineas de cada factura (solo Type='Item')...")
        # Una query por factura para que el filtro Document_No funcione bien.
        # Lento pero robusto. Para 3000 facturas son ~3k queries; aceptable
        # en sync nocturno. Para incremental (90 dias) son <300 facturas.
        with db.get_conn() as conn:
            for i, inv in enumerate(invoices, 1):
                lines = fetch_invoice_lines_for(session, inv["invoice_no"])
                for ln in lines:
                    db.upsert_navision_invoice_line(conn, ln, ht_items_set=ht_items)
                    lines_count += 1
                if i % 100 == 0:
                    print(f"      {i}/{invoices_count} facturas procesadas | {lines_count} lineas")
        print(f"      Total lineas Type='Item': {lines_count}")

        with db.get_conn() as conn:
            db.log_navision_sync_finish(conn, sync_id, items_count, invoices_count,
                                          lines_count, "ok")
        print(f"\n[OK] Sync Navision completo: {items_count} items, {invoices_count} "
              f"facturas, {lines_count} lineas")

    except Exception as e:
        with db.get_conn() as conn:
            db.log_navision_sync_finish(conn, sync_id, items_count, invoices_count,
                                          lines_count, "error", str(e))
        print(f"\n[ERROR] {e}", file=sys.stderr)
        raise


def _parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def main():
    parser = argparse.ArgumentParser(description="Sincroniza Navision BC14 a SQLite local.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--days", type=int, help=f"Dias hacia atras (default {DAYS_BACK}).")
    group.add_argument("--since", type=_parse_date, help="Fecha desde YYYY-MM-DD.")
    args = parser.parse_args()

    if args.since:
        since = args.since
    elif args.days:
        since = date.today() - timedelta(days=args.days)
    else:
        since = date.today() - timedelta(days=DAYS_BACK)

    sync(since=since)


if __name__ == "__main__":
    main()
