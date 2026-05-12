"""Detector de pais para campanas Meta Ads y Google Ads basado en convenciones de nombre.

Reglas en orden (devuelve la primera que matchea):
1. Sufijo `| XX` al final del nombre (ej: "20241001 | Leads form | FR" -> Francia)
2. Sufijo XX al final sin pipe (ej: "PMAX ITA" -> Italia)
3. Codigo pais entre separadores `_XX_` o ` XX ` (ej: "20260420_RMK_ FR_..." -> Francia)
4. Nombre completo en cualquier parte del nombre, case-insensitive
   (ej: "Demand Gen | Spain" -> España)
5. Por defecto: Espana

Para extender: anadir entradas a SUFFIX_TO_COUNTRY (codigo ISO 2-3 letras) o a
FULLNAME_TO_COUNTRY (nombre completo en ingles o espanol, lowercase).
"""

import re

SUFFIX_TO_COUNTRY = {
    # Mercados principales actuales
    "ES": "España", "ESP": "España", "E": "España",
    "FR": "Francia", "FRA": "Francia",
    "IT": "Italia", "ITA": "Italia",
    "UK": "Reino Unido", "GB": "Reino Unido",
    "DE": "Alemania", "GER": "Alemania",
    "BE": "Bélgica",
    "LU": "Luxemburgo",
    "NL": "Países Bajos",
    "IE": "Irlanda",
    "PT": "Portugal",
    # Otros UE
    "AT": "Austria",
    "CH": "Suiza",
    "DK": "Dinamarca",
    "FI": "Finlandia",
    "NO": "Noruega",
    "SE": "Suecia",
    "PL": "Polonia",
    "GR": "Grecia",
    "CZ": "Chequia",
    "SK": "Eslovaquia",
    "HU": "Hungría",
    "RO": "Rumanía",
    "BG": "Bulgaria",
    # Resto del mundo
    "US": "Estados Unidos", "USA": "Estados Unidos",
    "CA": "Canadá",
    "MX": "México",
    "AR": "Argentina",
    "BR": "Brasil",
    "CL": "Chile",
    "CO": "Colombia",
    "PE": "Perú",
    "AU": "Australia",
    "NZ": "Nueva Zelanda",
    "IN": "India",
    "JP": "Japón",
    # Regional / agregado
    "EU": "Multi-país",
    "EEA": "Multi-país",
}

FULLNAME_TO_COUNTRY = {
    # Mercados principales
    "spain": "España", "españa": "España", "espana": "España",
    "france": "Francia", "francia": "Francia",
    "italy": "Italia", "italia": "Italia",
    "germany": "Alemania", "alemania": "Alemania", "deutschland": "Alemania",
    "uk": "Reino Unido", "united kingdom": "Reino Unido", "england": "Reino Unido", "britain": "Reino Unido",
    "belgium": "Bélgica", "bélgica": "Bélgica", "belgica": "Bélgica",
    "luxembourg": "Luxemburgo", "luxemburgo": "Luxemburgo",
    "netherlands": "Países Bajos", "holland": "Países Bajos", "países bajos": "Países Bajos", "paises bajos": "Países Bajos",
    "ireland": "Irlanda", "irlanda": "Irlanda",
    "portugal": "Portugal",
    # Otros UE
    "austria": "Austria",
    "switzerland": "Suiza", "suiza": "Suiza",
    "denmark": "Dinamarca", "dinamarca": "Dinamarca",
    "finland": "Finlandia", "finlandia": "Finlandia",
    "norway": "Noruega", "noruega": "Noruega",
    "sweden": "Suecia", "suecia": "Suecia",
    "poland": "Polonia", "polonia": "Polonia",
    "greece": "Grecia", "grecia": "Grecia",
    # Resto del mundo
    "usa": "Estados Unidos", "united states": "Estados Unidos", "estados unidos": "Estados Unidos",
    "canada": "Canadá", "canadá": "Canadá",
    "mexico": "México", "méxico": "México",
    "argentina": "Argentina",
    "brazil": "Brasil", "brasil": "Brasil",
    # Agregado/regional
    "eu others": "Multi-país", "eu (others)": "Multi-país",
    "europe": "Multi-país", "europa": "Multi-país",
}

DEFAULT_COUNTRY = "España"


def country_for_campaign(name):
    """Devuelve el pais inferido del nombre de campana, o DEFAULT_COUNTRY."""
    if not name:
        return DEFAULT_COUNTRY

    # 1. Sufijo "| XX" al final
    m = re.search(r"\|\s*([A-Za-z]{1,3})\s*$", name)
    if m and m.group(1).upper() in SUFFIX_TO_COUNTRY:
        return SUFFIX_TO_COUNTRY[m.group(1).upper()]

    # 2. Sufijo XX al final del string sin pipe (ej: "PMAX ITA")
    m = re.search(r"(?:^|[_\s])([A-Z]{2,3})\s*$", name)
    if m and m.group(1) in SUFFIX_TO_COUNTRY:
        return SUFFIX_TO_COUNTRY[m.group(1)]

    # 3. Codigo pais entre separadores (espacios, _, |)
    #    Buscamos el ultimo match para no atrapar prefijos accidentales
    matches = list(re.finditer(r"[_\s|]([A-Z]{2,3})[_\s|]", name))
    for m in reversed(matches):
        if m.group(1) in SUFFIX_TO_COUNTRY:
            return SUFFIX_TO_COUNTRY[m.group(1)]

    # 4. Nombre completo en cualquier parte (case-insensitive)
    name_lower = name.lower()
    # Probamos nombres mas largos primero (evita que "uk" matchee dentro de otra palabra)
    for fullname in sorted(FULLNAME_TO_COUNTRY.keys(), key=len, reverse=True):
        if re.search(r"(?:^|[^a-z])" + re.escape(fullname) + r"(?:[^a-z]|$)", name_lower):
            return FULLNAME_TO_COUNTRY[fullname]

    return DEFAULT_COUNTRY


# Lista oficial de paises soportados (para el selector del UI). Se anaden al
# selector si tienen al menos una campana o contacto asociado.
SUPPORTED_COUNTRIES = [
    "España", "Francia", "Reino Unido", "Italia", "Bélgica", "Luxemburgo",
    "Alemania", "Países Bajos", "Irlanda", "Portugal", "Estados Unidos",
]
