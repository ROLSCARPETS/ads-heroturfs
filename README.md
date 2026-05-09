# Analisis Meta Ads Heroturfs

Dashboard web para analizar metricas de campanas de Meta Ads (Facebook/Instagram) de Heroturfs.

## Stack

- **Python 3 + Flask** - servidor web y dashboard
- **SQLite** - cache local de los datos extraidos de Meta
- **Meta Marketing API (Graph API)** - fuente de datos
- **Chart.js** - graficos en el frontend

## Estructura

```
analisis-meta-ads/
|-- app.py             # Servidor Flask con el dashboard
|-- meta_sync.py       # Extractor: API Meta -> SQLite
|-- db.py              # Capa de acceso a SQLite
|-- meta_ads.db        # Base de datos local (NO en git)
|-- .env               # Credenciales (NO en git)
|-- .env.example       # Plantilla de credenciales
|-- requirements.txt
|-- templates/         # Plantillas Jinja
`-- static/            # CSS y JS
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

3. Copiar `.env.example` a `.env` y rellenar con tu token y ad account ID:
   ```
   copy .env.example .env
   ```

4. Sincronizar datos por primera vez:
   ```
   python meta_sync.py
   ```

5. Levantar el dashboard:
   ```
   python app.py
   ```
   Abrir http://localhost:5001 (puerto 5001 para no chocar con el proyecto Consulta Stock Rols que usa el 5000)

## Token de Meta

Para generar un Access Token con permisos correctos:
- Ir a https://developers.facebook.com/tools/explorer/
- Permisos necesarios: `ads_read`, `read_insights`, `business_management`
- Para produccion: usar System User Token desde Business Manager (no caduca)
