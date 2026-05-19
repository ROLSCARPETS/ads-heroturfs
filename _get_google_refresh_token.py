"""Genera el Refresh Token de Google Ads via OAuth 2.0 (Desktop flow).

Uso:
    python _get_google_refresh_token.py                  # imprime el token
    python _get_google_refresh_token.py --update-env     # actualiza .env directamente

El script abrira el navegador para que autorices acceso de la app.
Tras autorizar, imprimira el refresh_token que debes copiar al .env como
GOOGLE_REFRESH_TOKEN (o lo actualiza solo si pasas --update-env).

El refresh_token vale para siempre (salvo que el usuario lo revoque o
pase mucho tiempo sin uso, o la app este en Testing mode).
"""

import json
import os
import sys
import re
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

CLIENT_SECRETS_FILE = Path(__file__).parent / "google_oauth_client.json"
ENV_FILE = Path(__file__).parent / ".env"
SCOPES = ["https://www.googleapis.com/auth/adwords"]
UPDATE_ENV = "--update-env" in sys.argv


def update_env_file(new_token):
    """Actualiza GOOGLE_REFRESH_TOKEN en el .env. Si no existe la linea,
    la anade al final. Preserva el resto del archivo intacto."""
    if not ENV_FILE.exists():
        print(f"WARN: no existe {ENV_FILE}, no se actualiza")
        return False
    content = ENV_FILE.read_text(encoding="utf-8")
    pattern = re.compile(r"^GOOGLE_REFRESH_TOKEN=.*$", re.MULTILINE)
    if pattern.search(content):
        content = pattern.sub(f"GOOGLE_REFRESH_TOKEN={new_token}", content)
    else:
        if not content.endswith("\n"):
            content += "\n"
        content += f"GOOGLE_REFRESH_TOKEN={new_token}\n"
    ENV_FILE.write_text(content, encoding="utf-8")
    return True

if not CLIENT_SECRETS_FILE.exists():
    print(f"ERROR: no encuentro {CLIENT_SECRETS_FILE}")
    print("Asegurate de tener el JSON de OAuth descargado en la carpeta del proyecto.")
    raise SystemExit(1)

print("Iniciando flujo OAuth de Google Ads...")
print("Se abrira tu navegador. Autoriza la app con la cuenta de Google que")
print("anadiste como Test User en el OAuth consent screen.")
print()

flow = InstalledAppFlow.from_client_secrets_file(
    str(CLIENT_SECRETS_FILE), SCOPES,
)

# run_local_server abre el navegador, recibe el code en localhost y lo intercambia.
# access_type=offline + prompt=consent fuerza que devuelva refresh_token.
creds = flow.run_local_server(
    port=0,  # cualquier puerto libre
    access_type="offline",
    prompt="consent",
    authorization_prompt_message=">>> Abriendo navegador para autorizar...",
    success_message="OK! Puedes cerrar esta ventana y volver a la terminal.",
    open_browser=True,
)

print()
print("=" * 70)
print("OK - Refresh Token obtenido!")
print("=" * 70)
print()

if UPDATE_ENV:
    if update_env_file(creds.refresh_token):
        print(f"OK - .env actualizado en {ENV_FILE}")
        print(f"     GOOGLE_REFRESH_TOKEN={creds.refresh_token[:20]}... (truncado)")
        print()
        print("Reinicia el servidor Flask para que tome el nuevo token.")
    else:
        print("FALLO actualizando .env. Copia manualmente:")
        print(f"GOOGLE_REFRESH_TOKEN={creds.refresh_token}")
else:
    print("Copia este valor al .env:")
    print()
    print(f"GOOGLE_REFRESH_TOKEN={creds.refresh_token}")
    print()
    print("(Tip: ejecuta con --update-env para actualizar el .env automaticamente)")
    print()
    # Tambien recordamos los demas
    with open(CLIENT_SECRETS_FILE) as f:
        secrets = json.load(f)["installed"]
    print("Y verifica que tienes tambien:")
    print(f"GOOGLE_CLIENT_ID={secrets['client_id']}")
    print(f"GOOGLE_CLIENT_SECRET={secrets['client_secret']}")
    print()
    print("(Cuando Google apruebe Basic Access tambien anade GOOGLE_DEVELOPER_TOKEN.)")
