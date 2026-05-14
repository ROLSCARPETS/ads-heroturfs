"""Test de conexion a Navision Business Central 14 via OData V4.

Soporta 3 modos de autenticacion:
  - sspi: usa el usuario Windows actual (single sign-on). Util cuando BC esta
          en Windows Auth y tu sesion ya tiene acceso (directamente o via grupo AD).
  - ntlm: NTLM explicito con dominio\\usuario + password (o password vacia).
  - basic: usuario + Web Service Access Key.

Por defecto prueba sspi -> ntlm -> basic, hasta que uno funcione.
Forzar uno: poner NAVISION_AUTH=sspi|ntlm|basic en .env.

USO:
  python test_navision_connection.py
"""
import os
import sys
from urllib.parse import quote

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("NAVISION_BASE_URL", "").rstrip("/")
COMPANY = os.getenv("NAVISION_COMPANY", "")
USER = os.getenv("NAVISION_USER", "")
KEY = os.getenv("NAVISION_KEY", "")  # Web Service Access Key o password
AUTH_MODE = os.getenv("NAVISION_AUTH", "").lower()  # sspi | ntlm | basic | "" (auto)
TIMEOUT = int(os.getenv("NAVISION_TIMEOUT", "30"))


def _check_env():
    missing = []
    if not BASE_URL: missing.append("NAVISION_BASE_URL")
    if not COMPANY:  missing.append("NAVISION_COMPANY")
    if missing:
        print(f"[ERROR] Faltan variables en .env: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)


def _company_path():
    return f"Company('{quote(COMPANY, safe='')}')"


def _build_auth(mode):
    """Devuelve el objeto auth de requests segun el modo. None si no es posible."""
    if mode == "sspi":
        try:
            from requests_negotiate_sspi import HttpNegotiateAuth
            return HttpNegotiateAuth(), "SSPI (usuario Windows actual)"
        except ImportError:
            print("  [sspi] Falta libreria. Instalala con: pip install requests-negotiate-sspi", file=sys.stderr)
            return None, None
    if mode == "ntlm":
        if not USER:
            print("  [ntlm] Falta NAVISION_USER", file=sys.stderr)
            return None, None
        try:
            from requests_ntlm import HttpNtlmAuth
            return HttpNtlmAuth(USER, KEY or ""), f"NTLM ({USER}, password {'***' if KEY else 'vacia'})"
        except ImportError:
            print("  [ntlm] Falta libreria. Instalala con: pip install requests-ntlm", file=sys.stderr)
            return None, None
    if mode == "basic":
        if not USER or not KEY:
            print("  [basic] Faltan NAVISION_USER y NAVISION_KEY", file=sys.stderr)
            return None, None
        return (USER, KEY), f"Basic ({USER}, key {'*' * min(8, len(KEY))})"
    return None, None


def _try_auth(mode):
    """Intenta una request simple con el modo dado. Devuelve True si OK."""
    auth_obj, descr = _build_auth(mode)
    if auth_obj is None:
        return False
    print(f"\n  -> Probando {descr}...")
    url = f"{BASE_URL}/Company?$top=1"
    try:
        r = requests.get(url, auth=auth_obj, timeout=TIMEOUT, verify=False)
        if r.status_code == 200:
            print(f"     OK ({r.status_code})")
            return True
        if r.status_code in (401, 403):
            print(f"     FAIL: HTTP {r.status_code} ({r.reason})")
            return False
        print(f"     FAIL: HTTP {r.status_code}. Body: {r.text[:200]}")
        return False
    except requests.exceptions.ConnectionError as e:
        print(f"     FAIL: no se puede conectar al servidor: {e}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"     FAIL: {e}", file=sys.stderr)
        return False


def _list_companies(auth_obj):
    print("\n[1/2] Listando companies disponibles...")
    url = f"{BASE_URL}/Company"
    r = requests.get(url, auth=auth_obj, timeout=TIMEOUT, verify=False)
    r.raise_for_status()
    data = r.json()
    companies = [c.get("Name") for c in data.get("value", [])]
    print(f"      OK: {len(companies)} companies encontradas")
    for c in companies[:10]:
        marker = "  <-- configurada en .env" if c == COMPANY else ""
        print(f"        - {c}{marker}")
    if COMPANY not in companies:
        print(f"\n      [WARN] La company '{COMPANY}' no aparece en la lista.")


def _read_sales(auth_obj):
    print("\n[2/2] Leyendo 5 filas de Power_BI_Sales_List...")
    url = f"{BASE_URL}/{_company_path()}/Power_BI_Sales_List"
    r = requests.get(url, auth=auth_obj, params={"$top": 5}, timeout=TIMEOUT, verify=False)
    if r.status_code == 403:
        print("      [WARN] 403 Forbidden. La conexion va bien pero el usuario "
              "no tiene permisos sobre Power_BI_Sales_List todavia.")
        return
    r.raise_for_status()
    rows = r.json().get("value", [])
    print(f"      OK: {len(rows)} filas devueltas")
    if rows:
        print(f"\n      Campos en la primera fila:")
        for k, v in list(rows[0].items())[:20]:
            print(f"        - {k:35} = {str(v)[:60]}")
        if len(rows[0]) > 20:
            print(f"        ... y {len(rows[0]) - 20} campos mas")


def main():
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass

    _check_env()
    print(f"== Test conexion Navision Business Central ==")
    print(f"BASE_URL: {BASE_URL}")
    print(f"COMPANY:  {COMPANY}")
    print(f"USER:     {USER or '(no usado en modo SSPI)'}")

    # Orden de prueba
    if AUTH_MODE in ("sspi", "ntlm", "basic"):
        modes_to_try = [AUTH_MODE]
        print(f"AUTH:     {AUTH_MODE} (forzado por NAVISION_AUTH)")
    else:
        modes_to_try = ["sspi", "ntlm", "basic"]
        print(f"AUTH:     auto (probara sspi -> ntlm -> basic)")

    winner = None
    for mode in modes_to_try:
        if _try_auth(mode):
            winner = mode
            break

    if not winner:
        print("\n[ERROR] Ningun modo de autenticacion ha funcionado.", file=sys.stderr)
        print("\nPosibles causas:", file=sys.stderr)
        print("  - El usuario IA no tiene permisos en BC", file=sys.stderr)
        print("  - El service tier de BC no acepta el modo de auth probado", file=sys.stderr)
        print("  - La maquina no llega al servidor (red/VPN)", file=sys.stderr)
        print("  - Falta instalar la libreria del modo: pip install requests-negotiate-sspi requests-ntlm", file=sys.stderr)
        sys.exit(1)

    print(f"\n[OK] Autenticacion funcional: {winner}")
    print(f"     Apunta esto en .env: NAVISION_AUTH={winner}")

    # Una vez sabemos el modo, hacemos las queries de prueba con el
    auth_obj, _ = _build_auth(winner)
    try:
        _list_companies(auth_obj)
        _read_sales(auth_obj)
        print("\n[OK] Conexion validada completamente. Listo para el siguiente paso.")
    except Exception as e:
        print(f"\n[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
