"""Script de diagnostico — descubre TODOS los campos disponibles en la
ficha de un cliente Navision para identificar el campo SDR_Code (o el
nombre real que use BC14).

Uso (con VPN activa):
    python inspect_navision_customer.py C2094

Pide al endpoint ClientesAreaPriv el cliente sin $select, asi devuelve
todos los campos. Luego imprime cada (campo, valor) ordenado, con
filtros heuristicos para destacar candidatos a SDR_Code (campos con
"SDR", "Comercial", "Responsable", "Vendedor", o codigos tipo Ixx).
"""

import sys
import json
import os
from urllib.parse import quote

from dotenv import load_dotenv
load_dotenv()

import navision_sync as ns


def main():
    if len(sys.argv) < 2:
        print("Uso: python inspect_navision_customer.py <customer_no>")
        print("     ej: python inspect_navision_customer.py C2094")
        sys.exit(1)
    customer_no = sys.argv[1]

    session = ns._new_session()
    # Pedir el cliente concreto SIN $select para que devuelva TODOS los campos
    url = (
        f"{ns.BASE_URL}/{ns._company_path()}/ClientesAreaPriv"
        f"?$filter=No eq '{customer_no}'"
    )
    print(f"Fetching: {url}\n")
    r = session.get(url, timeout=30, verify=False)
    r.raise_for_status()
    data = r.json()
    items = data.get("value", [])
    if not items:
        print(f"No se encontro el cliente {customer_no}")
        sys.exit(1)

    cust = items[0]
    print(f"=== Cliente {customer_no} - TODOS los campos ===\n")

    # Palabras clave que delatan campos relevantes al SDR/comercial
    keywords = ("sdr", "comercial", "responsable", "vendedor",
                "salesperson", "agente", "consultor", "dimension")

    interesting = []
    other = []
    for k, v in sorted(cust.items()):
        if k.startswith("@") or k.startswith("OData"):
            continue
        line = f"  {k:50}: {repr(v)[:80]}"
        if any(kw in k.lower() for kw in keywords):
            interesting.append(line)
        else:
            other.append(line)

    if interesting:
        print(">>> CANDIDATOS A SDR (campos con 'sdr/comercial/responsable/...'): <<<")
        for line in interesting:
            print(line)
        print()

    print(">>> Resto de campos: <<<")
    for line in other:
        print(line)

    print(f"\nTotal: {len(interesting) + len(other)} campos")


if __name__ == "__main__":
    main()
