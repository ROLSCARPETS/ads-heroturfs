"""Genera el PDF de diseno tecnico para la solicitud de Developer Token de Google Ads."""
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem,
    Table, TableStyle, KeepTogether
)

OUTPUT = r"C:\Users\fferr\ClaudeProyectos\Heroturfs analisis ads\docs\google-ads-api-design.pdf"

ACCENT = HexColor("#1d4ed8")
TEXT = HexColor("#1a1a2e")
MUTED = HexColor("#64748b")
BG_LIGHT = HexColor("#f5f7fa")

styles = getSampleStyleSheet()

style_title = ParagraphStyle(
    "Title", parent=styles["Title"],
    fontName="Helvetica-Bold", fontSize=20, leading=24,
    textColor=ACCENT, spaceAfter=4,
)
style_subtitle = ParagraphStyle(
    "Subtitle", parent=styles["Normal"],
    fontName="Helvetica", fontSize=11, leading=14,
    textColor=MUTED, spaceAfter=4,
)
style_meta = ParagraphStyle(
    "Meta", parent=styles["Normal"],
    fontName="Helvetica", fontSize=9, leading=12,
    textColor=MUTED, spaceAfter=12,
)
style_h2 = ParagraphStyle(
    "H2", parent=styles["Heading2"],
    fontName="Helvetica-Bold", fontSize=12, leading=16,
    textColor=ACCENT, spaceBefore=10, spaceAfter=4,
    borderPadding=(0, 0, 4, 0),
)
style_body = ParagraphStyle(
    "Body", parent=styles["Normal"],
    fontName="Helvetica", fontSize=10, leading=14,
    textColor=TEXT, alignment=TA_JUSTIFY, spaceAfter=4,
)
style_bullet = ParagraphStyle(
    "Bullet", parent=style_body, leftIndent=12, bulletIndent=0, spaceAfter=2,
)


style_cell = ParagraphStyle(
    "Cell", parent=styles["Normal"],
    fontName="Helvetica", fontSize=9, leading=12,
    textColor=TEXT, alignment=TA_LEFT,
)
style_cell_label = ParagraphStyle(
    "CellLabel", parent=style_cell,
    fontName="Helvetica-Bold", textColor=ACCENT,
)


def bullets(items):
    return ListFlowable(
        [Paragraph(t, style_body) for t in items],
        bulletType="bullet", bulletFontName="Helvetica", bulletFontSize=10,
        bulletColor=ACCENT, leftIndent=14,
    )


def kv_table(rows):
    """Render key-value table; wrap each cell in Paragraph for word-wrap."""
    wrapped = [[Paragraph(k, style_cell_label), Paragraph(v, style_cell)] for k, v in rows]
    t = Table(wrapped, colWidths=[5.5 * cm, 11 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), BG_LIGHT),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, MUTED),
    ]))
    return t


doc = SimpleDocTemplate(
    OUTPUT, pagesize=A4,
    leftMargin=2 * cm, rightMargin=2 * cm,
    topMargin=2 * cm, bottomMargin=2 * cm,
    title="Heroturfs Ads Dashboard - Technical Design",
    author="ROLS Carpets / Heroturfs",
)

story = []

# Header
story.append(Paragraph("Heroturfs Ads Dashboard", style_title))
story.append(Paragraph("Technical Design Document &#8211; Google Ads API Integration Request", style_subtitle))
story.append(Paragraph(
    "Date: 2026-05-10 &nbsp;&middot;&nbsp; Owner: ROLS Carpets / Heroturfs &nbsp;&middot;&nbsp; "
    "Contact: Fernando Ferr&aacute;ndez (fernando@rolscarpets.com)",
    style_meta,
))

# 1. Executive Summary
story.append(Paragraph("1. Executive Summary", style_h2))
story.append(Paragraph(
    "Internal analytics dashboard built for ROLS Carpets / Heroturfs to read Google Ads "
    "campaign performance data and combine it with Meta Ads and HubSpot CRM data into a "
    "unified marketing view. The tool is read-only, used internally by approximately 5 "
    "employees (marketing team and management), and hosted locally on internal machines. "
    "It is not publicly accessible.",
    style_body,
))

# 2. System Architecture
story.append(Paragraph("2. System Architecture", style_h2))
story.append(bullets([
    "<b>Backend</b>: Python 3 + Flask web framework",
    "<b>Database</b>: SQLite (local file, used as cache only)",
    "<b>Frontend</b>: HTML + Vanilla JavaScript + Chart.js for visualizations",
    "<b>Data sources integrated</b>: Meta Marketing API (already), HubSpot CRM API (already), "
    "Google Ads API (subject of this request)",
    "<b>Source code</b>: private GitHub repository (github.com/ROLSCARPETS/ads-heroturfs)",
]))

# 3. Data Flow
story.append(Paragraph("3. Data Flow", style_h2))
story.append(Paragraph(
    "The system follows a standard ETL pattern: extract data from each API, transform "
    "and aggregate, and load into the local SQLite cache. The dashboard reads from SQLite, "
    "never directly from APIs at request time. A manual refresh button in the UI triggers "
    "a sync, and daily automated syncs are planned via Windows Task Scheduler. <b>All API "
    "interactions are READ ONLY</b> &#8212; no data is written back to Google Ads, Meta or HubSpot.",
    style_body,
))

# 4. Google Ads API Usage
story.append(Paragraph("4. Google Ads API Usage", style_h2))
story.append(KeepTogether(kv_table([
    ["Endpoint", "GoogleAdsService.SearchStream (read-only GAQL queries)"],
    ["Data extracted", "Campaigns metadata, ad groups, daily insights "
                       "(impressions, clicks, cost_micros, conversions, conversion_value, ctr, cpc, cpm)"],
    ["Login customer (MCC)", "561-179-0021"],
    ["Operating customer (Heroturfs)", "308-486-6445"],
    ["Authentication", "OAuth 2.0 with refresh token + Developer Token (Basic Access)"],
    ["Estimated daily ops", "100-500 (1 daily sync &times; ~22 campaigns &times; ~30 days incremental). "
                            "Well below the 15,000 ops/day Basic Access limit."],
])))

# 5. Security and Privacy
story.append(Paragraph("5. Security and Privacy", style_h2))
story.append(bullets([
    "All credentials (Developer Token, OAuth Client Secret, Refresh Token) stored in a "
    "local .env file, excluded from version control via .gitignore.",
    "No customer PII is exported from Google Ads beyond what is already in our control.",
    "The dashboard is hosted on localhost (127.0.0.1:5001), accessible only on the internal LAN.",
    "Source code is in a private GitHub repository (no public exposure).",
    "All API calls are read-only. We do not modify campaigns, budgets, or any Google Ads object.",
    "No data is shared with third parties or external services.",
]))

# 6. User Interface
story.append(Paragraph("6. User Interface", style_h2))
story.append(Paragraph(
    "The dashboard has the following main sections:",
    style_body,
))
story.append(bullets([
    "KPI cards: spend, leads, CPL, CTR, CPC, ROAS, CAC by selected country and date range",
    "Evolution chart: daily / weekly / monthly time series of spend vs leads",
    "Campaign performance table with filters by country and status",
    "HubSpot CRM section: conversion funnel, revenue attribution, deals by stage",
    "Weekly summary table (Excel-style) combining all 3 sources for at-a-glance review",
]))

doc.build(story)
print(f"PDF generated: {OUTPUT}")
