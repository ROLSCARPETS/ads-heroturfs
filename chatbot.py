"""Chatbot del dashboard usando OpenAI function calling.

El LLM tiene acceso a un conjunto de "tools" que consultan la BBDD SQLite
local para responder preguntas sobre Meta, Google y HubSpot con datos reales.

Uso desde Flask:
    import chatbot
    reply, tools_used = chatbot.chat(messages, country=None)
"""

import json
import os
import sqlite3
from datetime import date, datetime, timedelta

from dotenv import load_dotenv

import db

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


SYSTEM_PROMPT = """Eres el asistente de analytics de Heroturfs (empresa de cesped artificial para
gimnasios CrossFit y centros deportivos). Heroturfs invierte en Meta Ads (Facebook/Instagram)
y Google Ads, y usa HubSpot como CRM. Atribucion via campo `fuentes_de_captacion_especificas`
en HubSpot ("Redes Sociales - IG/FB" = Meta, "Web - Google Ads" = Google).

Paises activos: España, Francia, Italia, Reino Unido, Belgica, Luxemburgo, Alemania.
Datos historicos disponibles desde enero 2025.

Cuando el usuario pregunte algo, usa las herramientas disponibles para consultar datos REALES.
Nunca inventes numeros. Si no tienes la herramienta para responder, dilo claramente.

Responde en espanol, conciso y directo. Usa tablas markdown cuando ayuden a comparar.
Cuando muestres cifras: usa formato 1.234,56 EUR (separador miles con punto, decimal con coma).
Si la pregunta es sobre una metrica concreta, da la cifra + comparativa vs periodo anterior
si es posible. Si detectas un insight relevante (caida, oportunidad), comentalo brevemente.

Para "hoy" / "esta semana" / "este mes" usa los parametros days correspondientes:
- "esta semana" / "ultima semana" -> days=7
- "este mes" / "ultimo mes" -> days=30
- "ultimo trimestre" -> days=90
- "este ano" / "12 meses" -> days=365
- "siempre" / "todo el historico" -> days=all
"""


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_kpis",
            "description": "Devuelve los KPIs principales de un canal (Meta, Google o HubSpot) "
                           "en un rango de dias, opcionalmente filtrado por pais. Incluye "
                           "comparativa con el periodo anterior.",
            "parameters": {
                "type": "object",
                "properties": {
                    "channel": {
                        "type": "string",
                        "enum": ["meta", "google", "hubspot"],
                        "description": "Canal: meta, google o hubspot",
                    },
                    "days": {
                        "type": "string",
                        "description": "Rango de dias hacia atras: '7', '30', '90', '365' o 'all'. Default '30'.",
                    },
                    "country": {
                        "type": "string",
                        "description": "Pais para filtrar (España, Francia, Italia, Reino Unido, "
                                       "Belgica, Luxemburgo, Alemania). Vacio = todos los paises.",
                    },
                },
                "required": ["channel"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_campaigns",
            "description": "Devuelve las top N campañas ordenadas por una metrica de un canal.",
            "parameters": {
                "type": "object",
                "properties": {
                    "channel": {"type": "string", "enum": ["meta", "google"]},
                    "metric": {
                        "type": "string",
                        "enum": ["spend", "clicks", "impressions", "ctr", "leads", "conversions", "revenue", "roas", "cpl", "cpc"],
                        "description": "Metrica para ordenar.",
                    },
                    "order": {"type": "string", "enum": ["desc", "asc"], "description": "desc (mas alto) o asc (mas bajo). Default desc."},
                    "limit": {"type": "integer", "description": "Numero de campañas a devolver. Default 5."},
                    "days": {"type": "string", "description": "Rango de dias. Default '30'."},
                    "country": {"type": "string", "description": "Pais opcional."},
                },
                "required": ["channel", "metric"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_alerts",
            "description": "Devuelve las alertas actuales (campañas que han caido >30% semana vs semana, "
                           "se han parado o han subido >100%).",
            "parameters": {
                "type": "object",
                "properties": {
                    "country": {"type": "string", "description": "Pais opcional."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_overview_by_country",
            "description": "Tabla resumen por pais (inversion total Meta+Google, leads, ganados, revenue, ROAS) "
                           "para evaluar performance comparada entre mercados.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "string", "description": "Rango de dias. Default '30'."},
                },
            },
        },
    },
]


# ====================================================================
# Implementacion de las tools (consultas a SQLite)
# ====================================================================

def _get_conn():
    conn = sqlite3.connect(db.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _resolve_range(days_param):
    until = date.today()
    if str(days_param) == "all":
        with _get_conn() as conn:
            r = conn.execute(
                "SELECT MIN(date) mn FROM (SELECT date FROM insights_daily UNION SELECT date FROM google_insights_daily)"
            ).fetchone()
        since = date.fromisoformat(r["mn"]) if r and r["mn"] else until
    else:
        try:
            days = int(days_param or 30)
        except (TypeError, ValueError):
            days = 30
        since = until - timedelta(days=max(days - 1, 0))
    return since.isoformat(), until.isoformat()


def _previous_range(since_iso, until_iso):
    s = date.fromisoformat(since_iso)
    u = date.fromisoformat(until_iso)
    days = (u - s).days + 1
    prev_until = s - timedelta(days=1)
    prev_since = prev_until - timedelta(days=days - 1)
    return prev_since.isoformat(), prev_until.isoformat()


def _delta_pct(current, previous):
    if previous is None or previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)


def tool_get_kpis(channel, days="30", country=None):
    country = country or None
    since, until = _resolve_range(days)
    prev_since, prev_until = _previous_range(since, until)

    def calc(since, until, channel, country):
        with _get_conn() as conn:
            if channel == "meta":
                sql = ("SELECT SUM(i.spend) spend, SUM(i.impressions) impressions, "
                       "SUM(i.clicks) clicks "
                       "FROM insights_daily i JOIN campaigns c ON c.id = i.campaign_id "
                       "WHERE i.date BETWEEN ? AND ?")
                params = [since, until]
                if country:
                    sql += " AND c.country = ?"; params.append(country)
                r = conn.execute(sql, params).fetchone()
                spend = r["spend"] or 0
                impressions = r["impressions"] or 0
                clicks = r["clicks"] or 0
                return {
                    "channel": "meta",
                    "spend_eur": round(spend, 2),
                    "impressions": impressions,
                    "clicks": clicks,
                    "ctr_pct": round((clicks / impressions * 100) if impressions else 0, 2),
                    "cpc_eur": round((spend / clicks) if clicks else 0, 3),
                }
            elif channel == "google":
                sql = ("SELECT SUM(i.cost) cost, SUM(i.impressions) impressions, "
                       "SUM(i.clicks) clicks, SUM(i.conversions) conv, "
                       "SUM(i.conversion_value) revenue "
                       "FROM google_insights_daily i JOIN google_campaigns c ON c.id = i.campaign_id "
                       "WHERE i.date BETWEEN ? AND ?")
                params = [since, until]
                if country:
                    sql += " AND c.country = ?"; params.append(country)
                r = conn.execute(sql, params).fetchone()
                cost = r["cost"] or 0
                impressions = r["impressions"] or 0
                clicks = r["clicks"] or 0
                conv = r["conv"] or 0
                rev = r["revenue"] or 0
                return {
                    "channel": "google",
                    "cost_eur": round(cost, 2),
                    "impressions": impressions,
                    "clicks": clicks,
                    "ctr_pct": round((clicks / impressions * 100) if impressions else 0, 2),
                    "cpc_eur": round((cost / clicks) if clicks else 0, 3),
                    "conversions": round(conv, 1),
                    "revenue_eur": round(rev, 2),
                    "roas": round((rev / cost) if cost else 0, 2),
                }
            elif channel == "hubspot":
                since_iso = since + "T00:00:00Z"
                until_iso = until + "T23:59:59Z"
                pais_clause = " AND pais = ?" if country else ""
                pais_params = [country] if country else []
                contacts = conn.execute(
                    f"SELECT COUNT(*) c FROM hubspot_contacts WHERE createdate BETWEEN ? AND ?{pais_clause}",
                    [since_iso, until_iso, *pais_params],
                ).fetchone()["c"]
                if country:
                    deals = conn.execute("""
                        SELECT COUNT(DISTINCT d.id) c, COALESCE(SUM(d.amount),0) revenue
                        FROM hubspot_deals d
                        JOIN hubspot_deal_contacts dc ON dc.deal_id = d.id
                        JOIN hubspot_contacts c ON c.id = dc.contact_id
                        WHERE d.is_won = 1 AND d.createdate BETWEEN ? AND ? AND c.pais = ?
                    """, (since_iso, until_iso, country)).fetchone()
                else:
                    deals = conn.execute(
                        "SELECT COUNT(*) c, COALESCE(SUM(amount),0) revenue FROM hubspot_deals "
                        "WHERE is_won = 1 AND createdate BETWEEN ? AND ?",
                        (since_iso, until_iso),
                    ).fetchone()
                return {
                    "channel": "hubspot",
                    "contactos_creados": contacts,
                    "deals_ganados": deals["c"],
                    "revenue_eur": round(deals["revenue"] or 0, 2),
                }
            return {"error": "Canal desconocido"}

    cur = calc(since, until, channel, country)
    prev = calc(prev_since, prev_until, channel, country)
    deltas = {}
    for k, v in cur.items():
        if isinstance(v, (int, float)) and k in prev and isinstance(prev[k], (int, float)):
            deltas[f"{k}_pct_change"] = _delta_pct(v, prev[k])
    return {
        "period": f"{since} a {until}",
        "previous_period": f"{prev_since} a {prev_until}",
        "country": country or "todos",
        "current": cur,
        "previous": prev,
        "deltas_pct": deltas,
    }


def tool_get_top_campaigns(channel, metric, order="desc", limit=5, days="30", country=None):
    country = country or None
    since, until = _resolve_range(days)
    direction = "DESC" if order == "desc" else "ASC"

    with _get_conn() as conn:
        if channel == "meta":
            metric_map = {
                "spend": "SUM(i.spend)",
                "impressions": "SUM(i.impressions)",
                "clicks": "SUM(i.clicks)",
                "ctr": "(SUM(i.clicks)*100.0 / NULLIF(SUM(i.impressions),0))",
                "cpc": "(SUM(i.spend) / NULLIF(SUM(i.clicks),0))",
            }
            if metric not in metric_map:
                return {"error": f"Metrica '{metric}' no disponible para Meta. Disponibles: {list(metric_map)}"}
            sql = (f"SELECT c.id, c.name, c.country, c.effective_status status, "
                   f"SUM(i.spend) spend, SUM(i.impressions) impressions, SUM(i.clicks) clicks, "
                   f"{metric_map[metric]} as metric_val "
                   "FROM campaigns c JOIN insights_daily i ON i.campaign_id = c.id "
                   "WHERE i.date BETWEEN ? AND ?")
            params = [since, until]
            if country:
                sql += " AND c.country = ?"; params.append(country)
            sql += f" GROUP BY c.id HAVING metric_val IS NOT NULL ORDER BY metric_val {direction} LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            out = []
            for r in rows:
                spend = r["spend"] or 0
                clicks = r["clicks"] or 0
                out.append({
                    "campaign_name": r["name"],
                    "country": r["country"],
                    "status": r["status"],
                    "spend_eur": round(spend, 2),
                    "clicks": clicks,
                    "cpc_eur": round((spend / clicks) if clicks else 0, 3),
                    "metric_value": round(r["metric_val"] or 0, 3),
                })
            return {"channel": "meta", "metric": metric, "order": order, "period": f"{since} a {until}", "results": out}

        elif channel == "google":
            metric_map = {
                "spend": "SUM(i.cost)",
                "clicks": "SUM(i.clicks)",
                "impressions": "SUM(i.impressions)",
                "ctr": "(SUM(i.clicks)*100.0 / NULLIF(SUM(i.impressions),0))",
                "cpc": "(SUM(i.cost) / NULLIF(SUM(i.clicks),0))",
                "conversions": "SUM(i.conversions)",
                "revenue": "SUM(i.conversion_value)",
                "roas": "(SUM(i.conversion_value) / NULLIF(SUM(i.cost),0))",
            }
            if metric not in metric_map:
                return {"error": f"Metrica '{metric}' no disponible para Google. Disponibles: {list(metric_map)}"}
            sql = (f"SELECT c.id, c.name, c.country, c.status, c.advertising_channel_type tipo, "
                   f"SUM(i.cost) cost, SUM(i.clicks) clicks, SUM(i.conversions) conv, "
                   f"SUM(i.conversion_value) revenue, {metric_map[metric]} as metric_val "
                   "FROM google_campaigns c JOIN google_insights_daily i ON i.campaign_id = c.id "
                   "WHERE i.date BETWEEN ? AND ?")
            params = [since, until]
            if country:
                sql += " AND c.country = ?"; params.append(country)
            sql += f" GROUP BY c.id HAVING metric_val IS NOT NULL ORDER BY metric_val {direction} LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            out = []
            for r in rows:
                cost = r["cost"] or 0
                rev = r["revenue"] or 0
                out.append({
                    "campaign_name": r["name"],
                    "country": r["country"],
                    "type": r["tipo"],
                    "cost_eur": round(cost, 2),
                    "conversions": round(r["conv"] or 0, 1),
                    "revenue_eur": round(rev, 2),
                    "roas": round((rev / cost) if cost else 0, 2),
                    "metric_value": round(r["metric_val"] or 0, 3),
                })
            return {"channel": "google", "metric": metric, "order": order, "period": f"{since} a {until}", "results": out}

    return {"error": "Canal desconocido"}


def tool_get_alerts(country=None):
    country = country or None
    today = date.today()
    cur_since = (today - timedelta(days=6)).isoformat()
    cur_until = today.isoformat()
    prev_since = (today - timedelta(days=13)).isoformat()
    prev_until = (today - timedelta(days=7)).isoformat()
    MIN_SPEND = 30
    THRESHOLD = 30  # %

    alerts = []
    with _get_conn() as conn:
        # Meta
        for channel, (insight, camp, cost_col) in [
            ("meta", ("insights_daily", "campaigns", "spend")),
            ("google", ("google_insights_daily", "google_campaigns", "cost")),
        ]:
            base_sql = (f"SELECT c.id, c.name, c.country, SUM(i.{cost_col}) sp "
                        f"FROM {insight} i JOIN {camp} c ON c.id = i.campaign_id "
                        "WHERE i.date BETWEEN ? AND ?")
            extra = ""; extra_p = []
            if country:
                extra = " AND c.country = ?"; extra_p = [country]
            sql_cur = base_sql + extra + " GROUP BY c.id"
            sql_prev = sql_cur
            cur = {r["id"]: dict(r) for r in conn.execute(sql_cur, [cur_since, cur_until, *extra_p]).fetchall()}
            prev = {r["id"]: dict(r) for r in conn.execute(sql_prev, [prev_since, prev_until, *extra_p]).fetchall()}
            for cid in set(cur) | set(prev):
                sp_cur = (cur.get(cid, {}) or {}).get("sp") or 0
                sp_prev = (prev.get(cid, {}) or {}).get("sp") or 0
                if max(sp_cur, sp_prev) < MIN_SPEND:
                    continue
                if sp_prev == 0:
                    change = None
                else:
                    change = round((sp_cur - sp_prev) / sp_prev * 100, 1)
                if sp_cur == 0 and sp_prev >= MIN_SPEND:
                    alert_type = "STOPPED"
                elif change is not None and change <= -50:
                    alert_type = "DROP_CRITICAL"
                elif change is not None and change <= -THRESHOLD:
                    alert_type = "DROP"
                elif change is not None and change >= 100 and sp_cur >= MIN_SPEND:
                    alert_type = "BOOST"
                else:
                    continue
                meta = cur.get(cid) or prev.get(cid)
                alerts.append({
                    "channel": channel,
                    "campaign_name": meta["name"],
                    "country": meta["country"],
                    "spend_current_eur": round(sp_cur, 2),
                    "spend_previous_eur": round(sp_prev, 2),
                    "change_pct": change,
                    "type": alert_type,
                })
    return {
        "current_week": f"{cur_since} a {cur_until}",
        "previous_week": f"{prev_since} a {prev_until}",
        "country": country or "todos",
        "count": len(alerts),
        "alerts": alerts,
    }


def tool_get_overview_by_country(days="30"):
    since, until = _resolve_range(days)
    since_iso = since + "T00:00:00Z"
    until_iso = until + "T23:59:59Z"
    out = []
    with _get_conn() as conn:
        countries = sorted({r["c"] for r in conn.execute(
            "SELECT DISTINCT country c FROM campaigns WHERE country IS NOT NULL "
            "UNION SELECT DISTINCT country c FROM google_campaigns WHERE country IS NOT NULL"
        ).fetchall() if r["c"]})
        for pais in countries:
            meta_spend = conn.execute(
                "SELECT SUM(i.spend) s FROM insights_daily i JOIN campaigns c ON c.id=i.campaign_id "
                "WHERE i.date BETWEEN ? AND ? AND c.country = ?", (since, until, pais)).fetchone()["s"] or 0
            google_cost = conn.execute(
                "SELECT SUM(i.cost) s FROM google_insights_daily i JOIN google_campaigns c ON c.id=i.campaign_id "
                "WHERE i.date BETWEEN ? AND ? AND c.country = ?", (since, until, pais)).fetchone()["s"] or 0
            contactos = conn.execute(
                "SELECT COUNT(*) c FROM hubspot_contacts WHERE createdate BETWEEN ? AND ? AND pais = ?",
                (since_iso, until_iso, pais)).fetchone()["c"]
            deals = conn.execute(
                "SELECT COUNT(DISTINCT d.id) c, COALESCE(SUM(d.amount),0) rev "
                "FROM hubspot_deals d JOIN hubspot_deal_contacts dc ON dc.deal_id=d.id "
                "JOIN hubspot_contacts c ON c.id=dc.contact_id "
                "WHERE d.is_won=1 AND d.createdate BETWEEN ? AND ? AND c.pais=?",
                (since_iso, until_iso, pais)).fetchone()
            spend_total = meta_spend + google_cost
            revenue = deals["rev"] or 0
            out.append({
                "country": pais,
                "spend_total_eur": round(spend_total, 2),
                "spend_meta_eur": round(meta_spend, 2),
                "spend_google_eur": round(google_cost, 2),
                "contactos_creados": contactos,
                "deals_ganados": deals["c"],
                "revenue_eur": round(revenue, 2),
                "roas": round((revenue / spend_total) if spend_total else 0, 2),
            })
    out.sort(key=lambda r: r["spend_total_eur"], reverse=True)
    return {"period": f"{since} a {until}", "by_country": out}


TOOL_REGISTRY = {
    "get_kpis": tool_get_kpis,
    "get_top_campaigns": tool_get_top_campaigns,
    "get_alerts": tool_get_alerts,
    "get_overview_by_country": tool_get_overview_by_country,
}


# ====================================================================
# Loop principal de chat con function calling
# ====================================================================

def chat(messages, country=None):
    """Procesa una conversacion (lista de mensajes) y devuelve la respuesta.

    messages: lista [{role: 'user'|'assistant', content: '...'}, ...]
    country: pais activo del dashboard (se inyecta como contexto)

    Devuelve (reply_str, tools_used).
    """
    if not OPENAI_API_KEY:
        return ("No esta configurado OPENAI_API_KEY en .env. No puedo responder hasta que se configure.", [])

    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)

    system = SYSTEM_PROMPT
    if country:
        system += f"\n\nIMPORTANTE: el usuario tiene seleccionado el pais '{country}' en el dashboard. " \
                  "Aplica este filtro por defecto en tus consultas (param country) salvo que pida explicitamente otro."

    # Construir mensajes en formato OpenAI
    msg_list = [{"role": "system", "content": system}] + messages

    tools_used = []
    for _ in range(6):  # max 6 iteraciones (evita bucles infinitos)
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=msg_list,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.2,
        )
        msg = resp.choices[0].message

        # Si no hay tool_calls, hemos terminado
        if not msg.tool_calls:
            return (msg.content or "", tools_used)

        # Anadimos el mensaje del LLM con sus tool_calls al historial
        msg_list.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ],
        })

        # Ejecutar cada tool
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            tools_used.append({"name": name, "args": args})
            fn = TOOL_REGISTRY.get(name)
            if fn is None:
                result = {"error": f"Tool {name} no existe"}
            else:
                try:
                    result = fn(**args)
                except Exception as e:
                    result = {"error": f"Fallo ejecutando {name}: {e}"}
            msg_list.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, ensure_ascii=False, default=str),
            })

    return ("Llegue al limite de iteraciones del chatbot. Reformula la pregunta o pidemela mas simple.", tools_used)
