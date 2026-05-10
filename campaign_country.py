"""Detector de pais para campanas Meta Ads basado en convenciones de nombre.

Reglas (en orden):
1. Sufijo `| XX` al final del nombre (ej: "20241001 | Leads form | FR" -> Francia)
2. Codigo pais entre separadores `_XX_` o ` XX ` (ej: "20260420_RMK_ FR_..." -> Francia)
3. Por defecto: Espana (la mayoria de campanas sin sufijo claro lo son)

Si en el futuro las convenciones cambian, ajustar SUFFIX_TO_COUNTRY.
"""

import re

SUFFIX_TO_COUNTRY = {
    "FR": "Francia",
    "FRA": "Francia",
    "UK": "Reino Unido",
    "GB": "Reino Unido",
    "IT": "Italia",
    "ITA": "Italia",
    "BE": "Bélgica",
    "LU": "Luxemburgo",
    "DE": "Alemania",
    "GER": "Alemania",
    "PT": "Portugal",
    "US": "Estados Unidos",
    "USA": "Estados Unidos",
    "ES": "España",
    "ESP": "España",
    "E": "España",
}

DEFAULT_COUNTRY = "España"


def country_for_campaign(name):
    """Devuelve el pais inferido del nombre de campana, o DEFAULT_COUNTRY."""
    if not name:
        return DEFAULT_COUNTRY

    # 1. Sufijo "| XX" al final
    m = re.search(r"\|\s*([A-Z]{1,3})\s*$", name)
    if m and m.group(1) in SUFFIX_TO_COUNTRY:
        return SUFFIX_TO_COUNTRY[m.group(1)]

    # 2. Codigo pais aislado entre separadores (_/espacio)
    #    Buscamos el ultimo match para no atrapar prefijos accidentales
    matches = list(re.finditer(r"[_\s]([A-Z]{2,3})[_\s]", name))
    for m in reversed(matches):
        if m.group(1) in SUFFIX_TO_COUNTRY:
            return SUFFIX_TO_COUNTRY[m.group(1)]

    return DEFAULT_COUNTRY


# Lista oficial de paises soportados (para el selector del UI)
SUPPORTED_COUNTRIES = ["España", "Francia", "Reino Unido", "Italia", "Bélgica", "Luxemburgo", "Alemania", "Portugal", "Estados Unidos"]
