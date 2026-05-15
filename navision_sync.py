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


def fetch_invoices(session, since_iso, customers_country_map=None):
    """Cabeceras de facturas con Posting_Date >= since_iso.

    Pais (prioridad de fuentes):
      1. Master de cliente (Country_Region_Code en su ficha) - FUENTE DE VERDAD
      2. Sell_to_Country_Region_Code de la factura (fallback)
      3. Bill_to / Ship_to de la factura (ultimos fallbacks)

    El #1 garantiza que un cliente belga facturando en Francia se cuente
    como Belgica (caso KINAXIS). customers_country_map debe ser un dict
    {customer_no: country_code_str} pre-cargado para evitar query por factura.
    """
    customers_country_map = customers_country_map or {}
    url = f"{BASE_URL}/{_company_path()}/HistFactAreaPriv"
    params = {
        "$select": (
            "No,Order_No,Posting_Date,Sell_to_Customer_No,Sell_to_Customer_Name,"
            "Sell_to_Country_Region_Code,Bill_to_Country_Region_Code,"
            "Ship_to_Country_Region_Code,Salesperson_Code,Amount,Amount_Including_VAT,"
            "Remaining_Amount,Currency_Code"
        ),
        "$filter": f"Posting_Date ge {since_iso}",
        "$orderby": "Posting_Date asc",
    }
    out = []
    for r in _paginate(session, url, params):
        cust_no = (r.get("Sell_to_Customer_No") or "").strip()
        master_country = customers_country_map.get(cust_no)  # del master de cliente
        sell_c = (r.get("Sell_to_Country_Region_Code") or "").strip().upper()
        bill_c = (r.get("Bill_to_Country_Region_Code") or "").strip().upper()
        ship_c = (r.get("Ship_to_Country_Region_Code") or "").strip().upper()
        country_code = master_country or sell_c or bill_c or ship_c or None
        country = SUFFIX_TO_COUNTRY.get(country_code) if country_code else None
        if country_code and not country:
            country = country_code
        out.append({
            "invoice_no": r.get("No"),
            "order_no": r.get("Order_No"),
            "posting_date": r.get("Posting_Date"),
            "customer_no": cust_no,
            "customer_name": r.get("Sell_to_Customer_Name"),
            "sell_country_code": country_code,
            "sell_country": country,
            "salesperson_code": r.get("Salesperson_Code"),
            "amount": r.get("Amount"),
            "amount_with_vat": r.get("Amount_Including_VAT"),
            "remaining_amount": r.get("Remaining_Amount"),
            "currency_code": r.get("Currency_Code"),
        })
    return out


def fetch_customers(session):
    """Maestro de clientes (ClientesAreaPriv). Devuelve dict
    {customer_no: {country_code, country, name, salesperson_code, ...}}
    para uso rapido al sincronizar facturas + lista para upsert."""
    url = f"{BASE_URL}/{_company_path()}/ClientesAreaPriv"
    params = {
        "$select": "No,Name,Country_Region_Code,Salesperson_Code,Customer_Price_Group",
    }
    out = []
    for r in _paginate(session, url, params):
        country_code = (r.get("Country_Region_Code") or "").strip().upper()
        country = SUFFIX_TO_COUNTRY.get(country_code) if country_code else None
        if country_code and not country:
            country = country_code  # codigo no mapeado: usar el code raw
        out.append({
            "customer_no": (r.get("No") or "").strip(),
            "name": r.get("Name"),
            "country_code": country_code or None,
            "country": country,
            "salesperson_code": r.get("Salesperson_Code"),
            "customer_price_group": r.get("Customer_Price_Group"),
        })
    return out


def fetch_currency_rates(session):
    """Trae historico de tasas de cambio (Power_BI_Tipo_de_cambio).
    Calcula eur_per_unit = Relational_Exch_Rate_Amount / Exchange_Rate_Amount
    para que la conversion en queries sea: amount_local * eur_per_unit = amount_eur.

    BC almacena 'Exchange_Rate_Amount' = unidades de la moneda extranjera por
    cada Relational_Exch_Rate_Amount EUR. Ej: GBP rate=0.869, rel=1 -> 1 GBP
    vale 1/0.869 = 1.151 EUR.
    """
    url = f"{BASE_URL}/{_company_path()}/Power_BI_Tipo_de_cambio"
    out = []
    for r in _paginate(session, url):
        rate = r.get("Exchange_Rate_Amount")
        rel = r.get("Relational_Exch_Rate_Amount")
        if not rate or rate == 0:
            continue
        eur_per_unit = (rel or 1) / rate
        out.append({
            "currency_code": (r.get("Currency_Code") or "").strip().upper(),
            "starting_date": r.get("Starting_Date"),
            "eur_per_unit": eur_per_unit,
        })
    return out


def fetch_salespeople(session):
    """Vendedores distintos a partir de SalesOrdersBySalesPerson (es el unico
    endpoint accesible que expone code+name juntos). Vendedores historicos
    sin pedidos abiertos no aparecen aqui pero seguiran como code-only en
    las queries del dashboard (LEFT JOIN)."""
    url = f"{BASE_URL}/{_company_path()}/SalesOrdersBySalesPerson"
    params = {"$select": "SalesPersonCode,SalesPersonName"}
    seen = {}
    for r in _paginate(session, url, params):
        code = (r.get("SalesPersonCode") or "").strip()
        name = (r.get("SalesPersonName") or "").strip()
        if code and code not in seen:
            seen[code] = name or None
    return seen


def fetch_credit_memos(session, since_iso, customers_country_map=None):
    """Cabeceras de abonos (HistAbVent). Mismo shape que invoices pero con
    doc_type='credit_memo'. amount se almacena POSITIVO (como BC); el SIGN
    a la hora de netear revenue lo aplica el query."""
    customers_country_map = customers_country_map or {}
    url = f"{BASE_URL}/{_company_path()}/HistAbVent"
    params = {
        "$select": (
            "No,Posting_Date,Sell_to_Customer_No,Sell_to_Customer_Name,"
            "Sell_to_Country_Region_Code,Bill_to_Country_Region_Code,"
            "Ship_to_Country_Region_Code,Salesperson_Code,Amount,Amount_Including_VAT,"
            "Remaining_Amount,Currency_Code"
        ),
        "$filter": f"Posting_Date ge {since_iso}",
        "$orderby": "Posting_Date asc",
    }
    out = []
    for r in _paginate(session, url, params):
        cust_no = (r.get("Sell_to_Customer_No") or "").strip()
        master_country = customers_country_map.get(cust_no)
        sell_c = (r.get("Sell_to_Country_Region_Code") or "").strip().upper()
        bill_c = (r.get("Bill_to_Country_Region_Code") or "").strip().upper()
        ship_c = (r.get("Ship_to_Country_Region_Code") or "").strip().upper()
        country_code = master_country or sell_c or bill_c or ship_c or None
        country = SUFFIX_TO_COUNTRY.get(country_code) if country_code else None
        if country_code and not country:
            country = country_code
        out.append({
            "invoice_no": r.get("No"),
            "doc_type": "credit_memo",
            "order_no": None,
            "posting_date": r.get("Posting_Date"),
            "customer_no": cust_no,
            "customer_name": r.get("Sell_to_Customer_Name"),
            "sell_country_code": country_code,
            "sell_country": country,
            "salesperson_code": r.get("Salesperson_Code"),
            "amount": r.get("Amount"),
            "amount_with_vat": r.get("Amount_Including_VAT"),
            "remaining_amount": r.get("Remaining_Amount"),
            "currency_code": r.get("Currency_Code"),
        })
    return out


def fetch_credit_memo_lines_for(session, credit_memo_no):
    """Lineas de un abono concreto (HistLinAbVentAreaPriv). Misma estructura
    que invoice lines pero con doc_type='credit_memo'."""
    url = f"{BASE_URL}/{_company_path()}/HistLinAbVentAreaPriv"
    params = {
        "$select": "Document_No,Line_No,Type,No,Description,Quantity,Unit_Price,Amount",
        "$filter": f"Document_No eq '{credit_memo_no}'",
    }
    out = []
    for r in _paginate(session, url, params):
        out.append({
            "invoice_no": r.get("Document_No"),
            "doc_type": "credit_memo",
            "line_no": r.get("Line_No"),
            "type": r.get("Type"),
            "item_no": (r.get("No") or "").strip(),
            "description": (r.get("Description") or "").strip(),
            "quantity": r.get("Quantity"),
            "unit_price": r.get("Unit_Price"),
            "amount": r.get("Amount"),
        })
    return out


def fetch_invoice_lines_for(session, invoice_no):
    """TODAS las lineas de la factura (Type='Item' + 'G/L Account' + 'Resource' + ...).
    Para revenue HT el filtro is_heroturfs se aplica solo a las Item; las demas
    son visibles para auditoria (descuentos, transportes, comisiones)."""
    url = f"{BASE_URL}/{_company_path()}/HistLinFactVenAreaPriv"
    params = {
        "$select": "Document_No,Line_No,Type,No,Description,Quantity,Unit_Price,Amount",
        "$filter": f"Document_No eq '{invoice_no}'",
    }
    out = []
    for r in _paginate(session, url, params):
        out.append({
            "invoice_no": r.get("Document_No"),
            "line_no": r.get("Line_No"),
            "type": r.get("Type"),
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
    salespeople_count = 0
    rates_count = 0
    customers_count = 0

    try:
        session = _new_session()

        print("[0/4] Trayendo dimensiones (vendedores, tipos cambio, clientes)...")
        sp = fetch_salespeople(session)
        with db.get_conn() as conn:
            for code, name in sp.items():
                db.upsert_navision_salesperson(conn, code, name)
                salespeople_count += 1
        print(f"      {salespeople_count} vendedores")
        try:
            rates = fetch_currency_rates(session)
            with db.get_conn() as conn:
                for rt in rates:
                    db.upsert_navision_rate(conn, rt["currency_code"],
                                             rt["starting_date"], rt["eur_per_unit"])
                    rates_count += 1
            print(f"      {rates_count} tipos de cambio (todas las divisas, todas las fechas)")
        except Exception as e:
            print(f"      [WARN] No se pudo traer Power_BI_Tipo_de_cambio: {e}. "
                  f"Usaremos fallback NAVISION_RATES de .env si esta definido.")
        # Clientes: maestro completo. Lo usamos para sobreescribir el pais
        # de las facturas (el cliente es la fuente de verdad).
        customers = fetch_customers(session)
        customers_country_map = {}
        with db.get_conn() as conn:
            for c in customers:
                db.upsert_navision_customer(conn, c)
                customers_count += 1
                if c.get("customer_no") and c.get("country_code"):
                    customers_country_map[c["customer_no"]] = c["country_code"]
        print(f"      {customers_count} clientes ({len(customers_country_map)} con pais asignado)")

        print("[1/4] Trayendo items (maestro completo)...")
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

        print(f"[2/4] Trayendo cabeceras de facturas (Posting_Date >= {since_iso})...")
        invoices = fetch_invoices(session, since_iso, customers_country_map=customers_country_map)
        with db.get_conn() as conn:
            for inv in invoices:
                db.upsert_navision_invoice(conn, inv)
                invoices_count += 1
        print(f"      {invoices_count} facturas")

        print(f"[3/4] Trayendo lineas de cada factura...")
        with db.get_conn() as conn:
            for i, inv in enumerate(invoices, 1):
                lines = fetch_invoice_lines_for(session, inv["invoice_no"])
                for ln in lines:
                    db.upsert_navision_invoice_line(conn, ln, ht_items_set=ht_items)
                    lines_count += 1
                if i % 100 == 0:
                    print(f"      {i}/{invoices_count} facturas procesadas | {lines_count} lineas")
        print(f"      Total lineas: {lines_count}")

        # Abonos (credit memos) - HistAbVent + lineas
        print(f"[3.5/4] Trayendo abonos (credit memos) >= {since_iso}...")
        credit_memos = fetch_credit_memos(session, since_iso, customers_country_map=customers_country_map)
        cm_count = 0
        cm_lines_count = 0
        with db.get_conn() as conn:
            for cm in credit_memos:
                db.upsert_navision_invoice(conn, cm)
                cm_count += 1
        print(f"      {cm_count} abonos cabecera")
        with db.get_conn() as conn:
            for i, cm in enumerate(credit_memos, 1):
                lines = fetch_credit_memo_lines_for(session, cm["invoice_no"])
                for ln in lines:
                    db.upsert_navision_invoice_line(conn, ln, ht_items_set=ht_items)
                    cm_lines_count += 1
                if i % 100 == 0:
                    print(f"      {i}/{cm_count} abonos procesados | {cm_lines_count} lineas")
        print(f"      Total lineas abonos: {cm_lines_count}")
        invoices_count += cm_count
        lines_count += cm_lines_count

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
