# Dashboard 360 Heroturfs - Meta Ads + HubSpot CRM

Dashboard web que cruza inversion publicitaria de Meta Ads con datos reales del CRM
(HubSpot) para medir ROAS real, CPL real, CAC y embudo completo de conversion.

## Stack

- **Python 3 + Flask** - servidor web y API
- **SQLite** - cache local de los datos extraidos
- **Meta Marketing API (Graph API)** + **HubSpot CRM API v3/v4** - fuentes de datos
- **Chart.js** - graficos en el frontend

## Estructura

```
analisis-meta-ads/
|-- app.py             # Servidor Flask con el dashboard
|-- meta_sync.py       # Extractor: Meta Marketing API -> SQLite
|-- hubspot_sync.py    # Extractor: HubSpot CRM API -> SQLite
|-- db.py              # Capa de acceso a SQLite (esquema + upserts)
|-- meta_ads.db        # Base de datos local (NO en git)
|-- .env               # Credenciales (NO en git)
|-- .env.example       # Plantilla de credenciales
|-- requirements.txt
|-- templates/         # Plantillas Jinja
|-- static/            # CSS y JS
|-- Lanzar Dashboard.bat       # Doble-click: arranca Flask + abre navegador
|-- Sincronizar Datos.bat      # Doble-click: sincroniza Meta Ads
`-- Sincronizar HubSpot.bat    # Doble-click: sincroniza HubSpot CRM
```

## Setup

1. Clonar el repo y entrar:
   ```
   git clone <url>
   cd analisis-meta-ads
   ```

2. Crear venv e instalar dependencias:
   ```
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Copiar `.env.example` a `.env` y rellenar credenciales:
   ```
   copy .env.example .env
   ```

4. Sincronizar datos por primera vez:
   ```
   python meta_sync.py --since 2025-01-01    # Meta Ads (16 meses)
   python hubspot_sync.py                     # HubSpot CRM completo
   ```

5. Levantar el dashboard:
   ```
   python app.py
   ```
   Abrir http://localhost:5001 (puerto 5001 para no chocar con el proyecto Consulta Stock Rols que usa el 5000).

## Tokens

### Meta (Marketing API)
- Generar en: https://developers.facebook.com/tools/explorer/
- Permisos: `ads_read`, `read_insights`, `business_management`
- Para produccion: System User Token desde Business Manager (no caduca).

### HubSpot (Private App)
- Generar en: HubSpot > Settings > Integrations > Private Apps > Create a private app
- Permisos minimos (todos `.read`):
  - `crm.objects.contacts.read`
  - `crm.objects.deals.read`
  - `crm.objects.companies.read`
  - `crm.schemas.contacts.read`
  - `crm.schemas.deals.read`
- Token formato `pat-eu1-...` (EU) o `pat-na1-...` (NA).

## Como funciona la atribucion

- En HubSpot, los contactos llevan la propiedad custom `fuentes_de_captacion_especificas`
  (Redes Sociales - IG/FB / Web - Google Ads / etc.).
- El extractor sincroniza contactos + deals + sus asociaciones.
- El dashboard cruza:
  - **Spend** (Meta API) -> **Leads Meta** (Meta API) -> **Contactos atribuidos** (HubSpot) ->
    **Ganados** (lead_status terminal positivo) -> **Revenue** (deals won asociados).
- Calcula automaticamente **ROAS**, **CPL real** y **CAC** por canal.

## Sincronizaciones programadas

Para automatizar, abrir Programador de tareas de Windows y crear una tarea diaria que
ejecute:
```
"C:\...\Heroturfs analisis ads\venv\Scripts\python.exe" meta_sync.py --days 7
"C:\...\Heroturfs analisis ads\venv\Scripts\python.exe" hubspot_sync.py --days 7
```
(usar `--days N` para incremental: solo trae lo modificado en los ultimos N dias).
