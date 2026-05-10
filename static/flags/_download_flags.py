"""Descarga las SVGs de banderas que usa el dashboard a static/flags/.

Solo se ejecuta una vez (o cuando se anaden paises nuevos al frontend).
Lee la lista de codigos ISO desde el JS (COUNTRY_ISO) o usa la lista
hardcodeada abajo.
"""
import sys
from pathlib import Path

import requests

ISO_CODES = [
    "es", "fr", "it", "gb", "de", "be", "lu", "pt", "us",
    "af", "al", "ad", "ar", "at", "br", "bg", "ca", "qa", "cz", "cl",
    "cy", "cr", "hr", "dk", "ae", "sk", "si", "ee", "fi", "gr", "hu",
    "in", "ie", "il", "kw", "lt", "my", "ma", "mx", "no", "nc", "nz",
    "nl", "pe", "pl", "ro", "sm", "se", "ch", "tr", "ua", "ve",
]

OUT = Path(__file__).parent

ok = 0
fail = []
for iso in ISO_CODES:
    target = OUT / f"{iso}.svg"
    if target.exists():
        ok += 1
        continue
    url = f"https://flagcdn.com/{iso}.svg"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            fail.append(f"{iso}: HTTP {r.status_code}")
            continue
        target.write_bytes(r.content)
        ok += 1
        print(f"  OK {iso}.svg ({len(r.content)} bytes)")
    except Exception as e:
        fail.append(f"{iso}: {e}")

print(f"\nDescargadas/existentes: {ok}/{len(ISO_CODES)}")
if fail:
    print(f"FALLOS ({len(fail)}):")
    for f in fail:
        print(f"  {f}")
    sys.exit(1)
