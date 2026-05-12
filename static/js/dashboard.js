// Dashboard Meta Ads Heroturfs

const state = {
    days: 30,
    granularity: 'daily',     // del grafico de evolucion
    weeklyGranularity: 'weekly', // de la tabla semanal/mensual
    shoppingGranularity: 'weekly', // de comparativa shopping por pais
    country: '',  // vacio = todos los paises
    customSince: null,        // YYYY-MM-DD si days === 'custom'
    customUntil: null,
    campaigns: [],
    sortBy: 'spend',
    sortDir: 'desc',
};

// Paleta de colores por pais para los graficos comparativos
const COUNTRY_COLORS = {
    "España":         "#dc2626", // rojo
    "Francia":        "#2563eb", // azul
    "Italia":         "#16a34a", // verde
    "Alemania":       "#f59e0b", // ambar
    "Reino Unido":    "#7c3aed", // morado
    "Bélgica":        "#ea580c", // naranja
    "Luxemburgo":     "#06b6d4", // cyan
    "Países Bajos":   "#0ea5e9", // azul cielo
    "Irlanda":        "#84cc16", // lima
    "Portugal":       "#d97706", // ambar oscuro
    "Estados Unidos": "#1e40af", // azul oscuro
    "Multi-país":     "#64748b", // gris
};
function colorForCountry(c) { return COUNTRY_COLORS[c] || "#94a3b8"; }

function buildQuery(extra = {}) {
    const params = new URLSearchParams();
    if (state.days === 'custom' && state.customSince && state.customUntil) {
        params.set('since', state.customSince);
        params.set('until', state.customUntil);
    } else {
        params.set('days', state.days);
    }
    if (state.country) params.set('country', state.country);
    Object.entries(extra).forEach(([k, v]) => params.set(k, v));
    return params.toString();
}

const MONTH_NAMES_ES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];

// Mapeo pais -> codigo ISO2 (alpha-2). Usado para servir SVG desde flagcdn.com.
// Windows no renderiza emojis de banderas, asi que usamos imagenes reales.
const COUNTRY_ISO = {
    "España": "es", "Francia": "fr", "Italia": "it", "Reino Unido": "gb",
    "Alemania": "de", "Bélgica": "be", "Luxemburgo": "lu", "Portugal": "pt",
    "Estados Unidos": "us", "Afganistán": "af", "Albania": "al", "Andorra": "ad",
    "Argentina": "ar", "Austria": "at", "Brasil": "br", "Bulgaria": "bg",
    "Canadá": "ca", "Catar": "qa", "Chequia": "cz", "Chile": "cl",
    "Chipre": "cy", "Costa Rica": "cr", "Croacia": "hr", "Dinamarca": "dk",
    "Emiratos Árabes Unidos": "ae", "Eslovaquia": "sk", "Eslovenia": "si",
    "Estonia": "ee", "Finlandia": "fi", "Grecia": "gr", "Hungría": "hu",
    "India": "in", "Irlanda": "ie", "Israel": "il", "Kuwait": "kw",
    "Lituania": "lt", "Malasia": "my", "Marruecos": "ma", "México": "mx",
    "Noruega": "no", "Nueva Caledonia": "nc", "Nueva Zelanda": "nz",
    "Países Bajos": "nl", "Perú": "pe", "Polonia": "pl", "Rumanía": "ro",
    "San Marino": "sm", "Suecia": "se", "Suiza": "ch", "Turquía": "tr",
    "Ucrania": "ua", "Venezuela": "ve",
    "Islas Ultramarinas Menores de Estados Unidos": "us",
};

function flagImg(country, size = 'small') {
    const iso = COUNTRY_ISO[country];
    if (!iso) return '<span class="flag-fallback">🌐</span>';
    // SVGs servidas localmente desde /static/flags/ (sin dependencia de internet).
    // Para anadir nuevos paises: ejecutar static/flags/_download_flags.py.
    const cls = size === 'big' ? 'flag-img flag-big' : 'flag-img';
    return `<img src="/static/flags/${iso}.svg" class="${cls}" alt="${escapeHtml(country)}" loading="lazy">`;
}

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// === Formatters ===
const fmtInt = new Intl.NumberFormat('es-ES');
const fmtEur = new Intl.NumberFormat('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtEur3 = new Intl.NumberFormat('es-ES', { minimumFractionDigits: 3, maximumFractionDigits: 3 });
// Formatter sin decimales (con separador de miles): para totales grandes tipo 1.128, 33.355
const fmtEurBig = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 0, useGrouping: true });
const fmtPct = (v) => v.toLocaleString('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + '%';

// === Toast ===
function toast(msg, type = '') {
    const t = $('#toast');
    t.textContent = msg;
    t.className = 'toast show ' + (type ? 'toast-' + type : '');
    setTimeout(() => t.classList.remove('show'), 3500);
}

// === API calls ===
async function fetchJson(path) {
    const r = await fetch(path);
    if (!r.ok) throw new Error(`API ${path} -> ${r.status}`);
    return r.json();
}

const fetchKpis = ()       => fetchJson(`/api/kpis?${buildQuery()}`);
const fetchTimeseries = () => fetchJson(`/api/timeseries?${buildQuery({granularity: state.granularity})}`);
const fetchCampaigns = ()  => fetchJson(`/api/campaigns?${buildQuery()}`);
const fetchHsKpis = ()     => fetchJson(`/api/hubspot/kpis?${buildQuery()}`);
const fetchHsFunnel = ()   => fetchJson(`/api/hubspot/funnel?${buildQuery()}`);
const fetchHsBySource = () => fetchJson(`/api/hubspot/by-source?${buildQuery()}`);
const fetchHsByStatus = () => fetchJson(`/api/hubspot/by-status?${buildQuery()}`);
const fetchHsByCountry = ()=> fetchJson(`/api/hubspot/by-country?${buildQuery()}`);
const fetchCountries = ()  => fetchJson('/api/countries');
const fetchWeekly = ()     => fetchJson(`/api/weekly?${buildQuery({granularity: state.weeklyGranularity})}`);
const fetchAlerts = ()     => fetchJson(`/api/alerts${state.country ? '?country=' + encodeURIComponent(state.country) : ''}`);
const fetchShoppingComparison = () => fetchJson(`/api/google/shopping-comparison?${buildQuery({granularity: state.shoppingGranularity})}`);

// Google Ads APIs
const fetchGoogleKpis = ()      => fetchJson(`/api/google/kpis?${buildQuery()}`);
const fetchGoogleCampaigns = () => fetchJson(`/api/google/campaigns?${buildQuery()}`);

// === Delta indicator helper ===
// "down-good": metricas donde bajada es buena (cpl, cpc, cpm, cpa, cac)
// "up-good": el resto (clicks, leads, ctr, conversions, revenue, roas, ...)
// "neutral": spend, cost, impressions, reach (subir/bajar no es bueno ni malo per se)
const DELTA_DIRECTION = {
    spend: 'neutral', cost: 'neutral', impressions: 'neutral', reach: 'neutral',
    cpl: 'down-good', cpc: 'down-good', cpm: 'down-good', cpa: 'down-good', cac: 'down-good',
    // resto se asume up-good
};

function setDelta(elId, pct, kpiKey, prevValue, prevFormat) {
    const el = document.getElementById(elId);
    if (!el) return;
    if (pct === null || pct === undefined) {
        el.innerHTML = '';
        el.className = 'kpi-delta';
        return;
    }
    const direction = DELTA_DIRECTION[kpiKey] || 'up-good';
    const isUp = pct > 0;
    const isFlat = Math.abs(pct) < 0.5;
    let cls = 'delta-flat';
    let arrow = '→';  // →
    if (!isFlat) {
        if (isUp) {
            arrow = '↗';  // ↗
            if (direction === 'up-good') cls = 'delta-up';
            else if (direction === 'down-good') cls = 'delta-down';
            else cls = 'delta-flat';
        } else {
            arrow = '↘';  // ↘
            if (direction === 'down-good') cls = 'delta-up';
            else if (direction === 'up-good') cls = 'delta-down';
            else cls = 'delta-flat';
        }
    }
    el.className = `kpi-delta ${cls}`;
    const sign = pct > 0 ? '+' : '';
    const pctStr = sign + pct.toLocaleString('es-ES', { maximumFractionDigits: 1 }) + '%';
    const prevStr = prevValue !== undefined ? `<span class="kpi-delta-prev">vs ${prevValue}</span>` : '';
    el.innerHTML = `<span class="kpi-delta-arrow">${arrow}</span> ${pctStr} ${prevStr}`;
}

function fmtForDelta(value, format) {
    if (format === 'eur') return fmtEur.format(value) + ' €';
    if (format === 'eur3') return fmtEur3.format(value) + ' €';
    if (format === 'pct') return value.toLocaleString('es-ES', { maximumFractionDigits: 2 }) + '%';
    if (format === 'x') return value.toLocaleString('es-ES', { maximumFractionDigits: 2 }) + 'x';
    return fmtInt.format(Math.round(value));
}

// === Render KPIs ===
function renderKpis(k) {
    $('#kpi-spend').textContent = fmtEurBig.format(Math.round(k.spend));
    $('#kpi-impressions').textContent = fmtInt.format(k.impressions);
    $('#kpi-reach').textContent = fmtInt.format(k.reach);
    $('#kpi-clicks').textContent = fmtInt.format(k.clicks);
    $('#kpi-ctr').textContent = k.ctr.toLocaleString('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    $('#kpi-cpc').textContent = fmtEur3.format(k.cpc);
    $('#kpi-leads').textContent = fmtInt.format(k.leads);
    $('#kpi-cpl').textContent = k.leads > 0 ? fmtEur.format(k.cpl) : '-';

    // Delta vs periodo anterior
    const d = k.deltas || {};
    const p = k.previous || {};
    setDelta('delta-spend', d.spend_pct, 'spend', fmtForDelta(p.spend || 0, 'eur'));
    setDelta('delta-impressions', d.impressions_pct, 'impressions', fmtForDelta(p.impressions || 0, 'int'));
    setDelta('delta-reach', d.reach_pct, 'reach', fmtForDelta(p.reach || 0, 'int'));
    setDelta('delta-clicks', d.clicks_pct, 'clicks', fmtForDelta(p.clicks || 0, 'int'));
    setDelta('delta-ctr', d.ctr_pct, 'ctr', fmtForDelta(p.ctr || 0, 'pct'));
    setDelta('delta-cpc', d.cpc_pct, 'cpc', fmtForDelta(p.cpc || 0, 'eur3'));
    setDelta('delta-leads', d.leads_pct, 'leads', fmtForDelta(p.leads || 0, 'int'));
    setDelta('delta-cpl', d.cpl_pct, 'cpl', fmtForDelta(p.cpl || 0, 'eur'));

    $('#date-range').textContent = `${formatDateES(k.since)} - ${formatDateES(k.until)} (${k.days} dias)`;
    $('#last-sync').textContent = k.last_sync
        ? `Meta: ${formatDateTimeES(k.last_sync)}`
        : 'Meta: nunca';
}

// === HubSpot rendering ===
function renderHsKpis(k) {
    $('#hs-kpi-contacts').textContent = fmtInt.format(k.contacts_total);
    $('#hs-kpi-deals-won').textContent = fmtInt.format(k.deals_won);
    $('#hs-kpi-revenue').textContent = fmtEurBig.format(Math.round(k.revenue_won));
    $('#hs-kpi-revenue-meta').textContent = fmtEurBig.format(Math.round(k.revenue_meta));
    $('#hs-kpi-revenue-google').textContent = fmtEurBig.format(Math.round(k.revenue_google));

    $('#last-sync-hs').textContent = k.last_sync
        ? `HubSpot: ${formatDateTimeES(k.last_sync)}`
        : 'HubSpot: nunca';

    // Delta vs periodo anterior
    const d = k.deltas || {};
    const p = k.previous || {};
    setDelta('hs-delta-contacts', d.contacts_total_pct, 'contacts', fmtForDelta(p.contacts_total || 0, 'int'));
    setDelta('hs-delta-deals-won', d.deals_won_pct, 'deals_won', fmtForDelta(p.deals_won || 0, 'int'));
    setDelta('hs-delta-revenue', d.revenue_won_pct, 'revenue', fmtForDelta(p.revenue_won || 0, 'eur'));
    setDelta('hs-delta-revenue-meta', d.revenue_meta_pct, 'revenue', fmtForDelta(p.revenue_meta || 0, 'eur'));
    setDelta('hs-delta-revenue-google', d.revenue_google_pct, 'revenue', fmtForDelta(p.revenue_google || 0, 'eur'));
}

function renderHsFunnel(f) {
    // Asignar metricas calculadas a sus KPI cards
    $('#hs-kpi-roas').textContent = f.roas > 0 ? `${f.roas.toLocaleString('es-ES', {minimumFractionDigits:2, maximumFractionDigits:2})}x` : '-';
    $('#hs-kpi-cpl').textContent = f.cpl_real > 0 ? fmtEur.format(f.cpl_real) : '-';
    $('#hs-kpi-cac').textContent = f.cac > 0 ? fmtEur.format(f.cac) : '-';

    // Delta vs periodo anterior (ROAS, CPL real, CAC)
    const d = f.deltas || {};
    const p = f.previous || {};
    setDelta('hs-delta-roas', d.roas_pct, 'roas', fmtForDelta(p.roas || 0, 'x'));
    setDelta('hs-delta-cpl', d.cpl_real_pct, 'cpl', fmtForDelta(p.cpl_real || 0, 'eur'));
    setDelta('hs-delta-cac', d.cac_pct, 'cac', fmtForDelta(p.cac || 0, 'eur'));

    // Renderizar stages del funnel
    const container = $('#funnel-stages');
    const stages = f.stages || [];
    const baseLeads = stages.find(s => s.label.includes('Leads Meta'))?.value || 0;
    container.innerHTML = stages.map((s, i) => {
        let pct = '';
        // Mostrar % de conversion respecto al stage de referencia (Leads Meta API)
        if (i >= 2 && baseLeads > 0 && !s.label.includes('Revenue')) {
            const p = (s.value / baseLeads * 100);
            pct = `<span class="funnel-stage-pct">${p.toFixed(1)}% de leads</span>`;
        }
        const valueFormatted = s.unit === 'EUR'
            ? fmtEur.format(s.value)
            : fmtInt.format(s.value);
        return `
            <div class="funnel-stage">
                ${pct}
                <div class="funnel-stage-label">${escapeHtml(s.label)}</div>
                <div class="funnel-stage-value">${valueFormatted}<span class="funnel-stage-unit">${s.unit || ''}</span></div>
            </div>
        `;
    }).join('');
}

function renderHsBySource(rows) {
    const tbody = $('#table-hs-source tbody');
    const tfoot = $('#table-hs-source tfoot');
    tbody.innerHTML = rows.map(r => `
        <tr>
            <td>${escapeHtml(r.fuente || '-')}</td>
            <td class="td-num">${fmtInt.format(r.contactos)}</td>
            <td class="td-num">${fmtInt.format(r.ganados)}</td>
            <td class="td-num">${r.contactos > 0 ? fmtPct(r.conv_rate) : '-'}</td>
            <td class="td-num">${fmtInt.format(r.deals_won)}</td>
            <td class="td-num">${r.revenue > 0 ? fmtEur.format(r.revenue) : '-'}</td>
        </tr>
    `).join('');

    const tot = rows.reduce((acc, r) => {
        acc.c += r.contactos; acc.g += r.ganados; acc.d += r.deals_won; acc.rev += r.revenue;
        return acc;
    }, { c: 0, g: 0, d: 0, rev: 0 });
    const totConv = tot.c > 0 ? (tot.g / tot.c * 100) : 0;
    tfoot.innerHTML = `
        <tr>
            <td>Total</td>
            <td class="td-num">${fmtInt.format(tot.c)}</td>
            <td class="td-num">${fmtInt.format(tot.g)}</td>
            <td class="td-num">${fmtPct(totConv)}</td>
            <td class="td-num">${fmtInt.format(tot.d)}</td>
            <td class="td-num">${fmtEur.format(tot.rev)}</td>
        </tr>
    `;
}

function renderHsByStatus(rows) {
    const tbody = $('#table-hs-status tbody');
    tbody.innerHTML = rows.map(r => `
        <tr>
            <td>${escapeHtml(r.estado)}</td>
            <td class="td-num">${fmtInt.format(r.contactos)}</td>
        </tr>
    `).join('');
}

function renderHsByCountry(rows) {
    const tbody = $('#table-hs-country tbody');
    tbody.innerHTML = rows.map(r => `
        <tr>
            <td>${flagImg(r.pais)}${escapeHtml(r.pais)}</td>
            <td class="td-num">${fmtInt.format(r.contactos)}</td>
        </tr>
    `).join('');
}

function formatDateES(iso) {
    if (!iso) return '-';
    const [y, m, d] = iso.substring(0, 10).split('-');
    return `${d}/${m}/${y}`;
}
function formatPeriodLabel(iso, granularity) {
    if (!iso) return '-';
    const [y, m, d] = iso.substring(0, 10).split('-');
    if (granularity === 'monthly') return `${MONTH_NAMES_ES[parseInt(m, 10) - 1]} ${y}`;
    if (granularity === 'weekly') return `Sem ${d}/${m}`;
    return `${d}/${m}/${y}`;
}
function formatDateTimeES(iso) {
    if (!iso) return '-';
    // ISO viene en UTC ("YYYY-MM-DD HH:MM:SS"), convertimos a local
    const dt = new Date(iso.replace(' ', 'T') + 'Z');
    return dt.toLocaleString('es-ES', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

// === Charts ===
let chartTimeseries = null;
let chartTopCampaigns = null;

function renderTimeseries(payload) {
    const granularity = payload.granularity || 'daily';
    const data = payload.data || [];
    const labels = data.map(d => formatPeriodLabel(d.period, granularity));
    const spend = data.map(d => d.spend);
    const leads = data.map(d => d.leads);

    const titleMap = { daily: 'Evolución diaria', weekly: 'Evolución semanal', monthly: 'Evolución mensual' };
    const titleEl = $('#chart-timeseries-title');
    if (titleEl) titleEl.textContent = titleMap[granularity] || 'Evolución';

    const ctx = $('#chart-timeseries').getContext('2d');
    if (chartTimeseries) chartTimeseries.destroy();
    chartTimeseries = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [
                {
                    label: 'Gasto (EUR)',
                    data: spend,
                    borderColor: '#2563eb',
                    backgroundColor: 'rgba(37, 99, 235, 0.08)',
                    fill: true,
                    tension: 0.3,
                    yAxisID: 'y',
                    borderWidth: 2,
                    pointRadius: 2,
                    pointHoverRadius: 5,
                },
                {
                    label: 'Leads',
                    data: leads,
                    borderColor: '#7c3aed',
                    backgroundColor: 'rgba(124, 58, 237, 0.08)',
                    fill: false,
                    tension: 0.3,
                    yAxisID: 'y1',
                    borderWidth: 2,
                    pointRadius: 2,
                    pointHoverRadius: 5,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { position: 'top', labels: { boxWidth: 12, font: { size: 12 } } },
                tooltip: {
                    callbacks: {
                        label: (ctx) => {
                            const v = ctx.parsed.y;
                            if (ctx.dataset.label.includes('Gasto')) return `${ctx.dataset.label}: ${fmtEur.format(v)} EUR`;
                            return `${ctx.dataset.label}: ${fmtInt.format(v)}`;
                        },
                    },
                },
            },
            scales: {
                x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 12 } },
                y: {
                    type: 'linear', position: 'left',
                    title: { display: true, text: 'Gasto (EUR)', color: '#2563eb' },
                    grid: { color: 'rgba(15,23,42,0.05)' },
                },
                y1: {
                    type: 'linear', position: 'right',
                    title: { display: true, text: 'Leads', color: '#7c3aed' },
                    grid: { drawOnChartArea: false },
                    beginAtZero: true,
                },
            },
        },
    });
}

function renderTopCampaigns(campaigns) {
    const top = campaigns.filter(c => c.spend > 0).slice(0, 8);
    const labels = top.map(c => truncate(c.name, 28));
    const spend = top.map(c => c.spend);

    const ctx = $('#chart-top-campaigns').getContext('2d');
    if (chartTopCampaigns) chartTopCampaigns.destroy();
    chartTopCampaigns = new Chart(ctx, {
        type: 'bar',
        data: {
            labels,
            datasets: [{
                label: 'Gasto (EUR)',
                data: spend,
                backgroundColor: '#2563eb',
                borderRadius: 4,
            }],
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (ctx) => `${fmtEur.format(ctx.parsed.x)} EUR`,
                    },
                },
            },
            scales: {
                x: { grid: { color: 'rgba(15,23,42,0.05)' }, ticks: { callback: (v) => fmtEur.format(v) } },
                y: { grid: { display: false }, ticks: { font: { size: 11 } } },
            },
        },
    });
}

function truncate(s, n) {
    if (!s) return '';
    return s.length > n ? s.substring(0, n - 1) + '…' : s;
}

// === Tabla ===
function renderTable() {
    const tbody = $('#table-campaigns tbody');
    const tfoot = $('#table-campaigns tfoot');
    const sorted = [...state.campaigns].sort((a, b) => {
        const av = a[state.sortBy] ?? 0;
        const bv = b[state.sortBy] ?? 0;
        if (typeof av === 'string') return state.sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
        return state.sortDir === 'asc' ? av - bv : bv - av;
    });

    tbody.innerHTML = sorted.map(c => `
        <tr>
            <td class="td-name" title="${escapeHtml(c.name || '')}">${escapeHtml(c.name || '(sin nombre)')}</td>
            <td class="td-country">${c.country ? flagImg(c.country) + escapeHtml(c.country) : '<span class="empty">-</span>'}</td>
            <td><span class="status-pill ${statusClass(c.status)}">${c.status || '-'}</span></td>
            <td class="td-num">${fmtEur.format(c.spend)}</td>
            <td class="td-num">${fmtInt.format(c.impressions)}</td>
            <td class="td-num">${fmtInt.format(c.clicks)}</td>
            <td class="td-num">${fmtPct(c.ctr)}</td>
            <td class="td-num">${c.clicks > 0 ? fmtEur3.format(c.cpc) : '-'}</td>
            <td class="td-num">${fmtInt.format(c.leads)}</td>
            <td class="td-num">${c.leads > 0 ? fmtEur.format(c.cpl) : '-'}</td>
        </tr>
    `).join('');

    // Totales
    const tot = state.campaigns.reduce((acc, c) => {
        acc.spend += c.spend; acc.impressions += c.impressions; acc.clicks += c.clicks; acc.leads += c.leads;
        return acc;
    }, { spend: 0, impressions: 0, clicks: 0, leads: 0 });
    const totCtr = tot.impressions > 0 ? (tot.clicks / tot.impressions * 100) : 0;
    const totCpc = tot.clicks > 0 ? (tot.spend / tot.clicks) : 0;
    const totCpl = tot.leads > 0 ? (tot.spend / tot.leads) : 0;
    tfoot.innerHTML = `
        <tr>
            <td>Total (${state.campaigns.length} campañas)</td>
            <td></td>
            <td></td>
            <td class="td-num">${fmtEur.format(tot.spend)}</td>
            <td class="td-num">${fmtInt.format(tot.impressions)}</td>
            <td class="td-num">${fmtInt.format(tot.clicks)}</td>
            <td class="td-num">${fmtPct(totCtr)}</td>
            <td class="td-num">${tot.clicks > 0 ? fmtEur3.format(totCpc) : '-'}</td>
            <td class="td-num">${fmtInt.format(tot.leads)}</td>
            <td class="td-num">${tot.leads > 0 ? fmtEur.format(totCpl) : '-'}</td>
        </tr>
    `;

    // Marcar columna ordenada
    $$('#table-campaigns thead th').forEach(th => th.classList.remove('sort-asc', 'sort-desc'));
    const idx = ['name', 'country', 'status', 'spend', 'impressions', 'clicks', 'ctr', 'cpc', 'leads', 'cpl'].indexOf(state.sortBy);
    if (idx >= 0) {
        const th = $$('#table-campaigns thead th')[idx];
        if (th) th.classList.add(state.sortDir === 'asc' ? 'sort-asc' : 'sort-desc');
    }
}

function statusClass(s) {
    if (!s) return 'status-default';
    if (['ACTIVE', 'PAUSED', 'DELETED', 'ARCHIVED'].includes(s)) return 'status-' + s;
    return 'status-default';
}

function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}

// === Sort tabla ===
function setupTableSort() {
    const cols = ['name', 'country', 'status', 'spend', 'impressions', 'clicks', 'ctr', 'cpc', 'leads', 'cpl'];
    $$('#table-campaigns thead th').forEach((th, i) => {
        th.addEventListener('click', () => {
            const col = cols[i];
            if (state.sortBy === col) {
                state.sortDir = state.sortDir === 'asc' ? 'desc' : 'asc';
            } else {
                state.sortBy = col;
                state.sortDir = (col === 'name' || col === 'status') ? 'asc' : 'desc';
            }
            renderTable();
        });
    });
}

// === Export CSV ===
function exportCsv() {
    const headers = ['Campaña', 'Estado', 'Objetivo', 'Gasto EUR', 'Impresiones', 'Alcance', 'Clicks', 'CTR %', 'CPC EUR', 'Leads', 'CPL EUR'];
    const rows = state.campaigns.map(c => [
        c.name, c.status, c.objective,
        c.spend, c.impressions, c.reach, c.clicks, c.ctr, c.cpc, c.leads, c.cpl,
    ]);
    const csv = [headers, ...rows].map(r => r.map(csvCell).join(';')).join('\r\n');
    const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `meta-ads-heroturfs-${new Date().toISOString().substring(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
}

function csvCell(v) {
    if (v == null) return '';
    const s = String(v);
    if (s.includes(';') || s.includes('"') || s.includes('\n')) return '"' + s.replace(/"/g, '""') + '"';
    return s;
}

// === Carga principal ===
async function loadAll() {
    try {
        const [k, ts, cs, hsK, hsF, hsSrc, hsSt, hsCo, wk, gK, gCs, al, sh] = await Promise.all([
            fetchKpis(), fetchTimeseries(), fetchCampaigns(),
            fetchHsKpis(), fetchHsFunnel(), fetchHsBySource(),
            fetchHsByStatus(), fetchHsByCountry(),
            fetchWeekly(),
            fetchGoogleKpis(), fetchGoogleCampaigns(),
            fetchAlerts(),
            fetchShoppingComparison(),
        ]);
        renderAlerts(al);
        renderShoppingComparison(sh);
        renderKpis(k);
        renderTimeseries(ts);
        state.campaigns = cs;
        renderTopCampaigns(cs);
        renderTable();
        renderHsKpis(hsK);
        renderHsFunnel(hsF);
        renderHsBySource(hsSrc);
        renderHsByStatus(hsSt);
        renderHsByCountry(hsCo);
        renderWeekly(wk);
        renderGoogleKpis(gK);
        renderGoogleCampaigns(gCs);
    } catch (e) {
        toast('Error cargando datos: ' + e.message, 'error');
    }
}

// === Alerts render ===
function renderAlerts(payload) {
    const bar = $('#alerts-bar');
    const list = $('#alerts-list');
    const alerts = payload.alerts || [];
    if (!alerts.length) {
        bar.style.display = 'none';
        return;
    }
    bar.style.display = 'block';
    $('#alerts-count').textContent = alerts.length;
    $('#alerts-period').textContent = `${payload.current_period} vs ${payload.previous_period}`;

    list.innerHTML = alerts.map(a => {
        const change = a.change_pct;
        const changeStr = change === null ? 'nuevo' : (change > 0 ? '+' : '') + change.toLocaleString('es-ES', { maximumFractionDigits: 0 }) + '%';
        const changeCls = change !== null && change < 0 ? 'change-negative' : (change !== null && change > 0 ? 'change-positive' : '');
        const arrow = change === null ? '·' : (change < 0 ? '↓' : '↑');
        return `
            <div class="alert-chip severity-${a.severity}">
                <div class="alert-chip-top">
                    <div class="alert-chip-tags">
                        <span class="alert-chip-tag tag-${a.channel}">${a.channel}</span>
                        <span class="alert-chip-tag tag-${a.type}">${a.type}</span>
                        ${a.country ? `${flagImg(a.country)}` : ''}
                    </div>
                    <span class="alert-chip-change ${changeCls}">${arrow} ${changeStr}</span>
                </div>
                <div class="alert-chip-name" title="${escapeHtml(a.campaign_name)}">${escapeHtml(a.campaign_name)}</div>
                <div class="alert-chip-vals">${fmtEur.format(a.spend_previous)} € → ${fmtEur.format(a.spend_current)} €</div>
            </div>
        `;
    }).join('');
}

// === Google Ads render ===
function renderGoogleKpis(k) {
    $('#g-kpi-cost').textContent = fmtEurBig.format(Math.round(k.cost));
    $('#g-kpi-impressions').textContent = fmtInt.format(k.impressions);
    $('#g-kpi-clicks').textContent = fmtInt.format(k.clicks);
    $('#g-kpi-ctr').textContent = k.ctr.toLocaleString('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    $('#g-kpi-cpc').textContent = fmtEur3.format(k.cpc);
    $('#g-kpi-conv').textContent = fmtInt.format(Math.round(k.conversions));
    $('#g-kpi-revenue').textContent = fmtEurBig.format(Math.round(k.revenue));
    $('#g-kpi-roas').textContent = k.roas > 0 ? `${k.roas.toLocaleString('es-ES', {minimumFractionDigits:2, maximumFractionDigits:2})}x` : '-';

    // Delta vs periodo anterior
    const d = k.deltas || {};
    const p = k.previous || {};
    setDelta('g-delta-cost', d.cost_pct, 'cost', fmtForDelta(p.cost || 0, 'eur'));
    setDelta('g-delta-impressions', d.impressions_pct, 'impressions', fmtForDelta(p.impressions || 0, 'int'));
    setDelta('g-delta-clicks', d.clicks_pct, 'clicks', fmtForDelta(p.clicks || 0, 'int'));
    setDelta('g-delta-ctr', d.ctr_pct, 'ctr', fmtForDelta(p.ctr || 0, 'pct'));
    setDelta('g-delta-cpc', d.cpc_pct, 'cpc', fmtForDelta(p.cpc || 0, 'eur3'));
    setDelta('g-delta-conv', d.conversions_pct, 'conversions', fmtForDelta(p.conversions || 0, 'int'));
    setDelta('g-delta-revenue', d.revenue_pct, 'revenue', fmtForDelta(p.revenue || 0, 'eur'));
    setDelta('g-delta-roas', d.roas_pct, 'roas', fmtForDelta(p.roas || 0, 'x'));

    $('#last-sync-google').textContent = k.last_sync
        ? `Google: ${formatDateTimeES(k.last_sync)}`
        : 'Google: nunca';

    // Mensaje si no hay datos
    const msg = $('#google-status-msg');
    if (k.cost === 0 && k.impressions === 0) {
        msg.textContent = '⏳ Sin datos. Pendiente de aprobación del Developer Token o de primera sincronización.';
    } else {
        msg.textContent = '';
    }
}

function renderGoogleCampaigns(rows) {
    const tbody = $('#table-google-campaigns tbody');
    const tfoot = $('#table-google-campaigns tfoot');

    if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="12" style="text-align:center;color:#64748b;padding:24px;">No hay campañas Google. Pulsa "Sincronizar Google" o lanza desde terminal: <code>python google_sync.py</code></td></tr>';
        tfoot.innerHTML = '';
        return;
    }

    tbody.innerHTML = rows.map(c => `
        <tr>
            <td class="td-name" title="${escapeHtml(c.name || '')}">${escapeHtml(c.name || '(sin nombre)')}</td>
            <td class="td-country">${c.country ? flagImg(c.country) + escapeHtml(c.country) : '<span class="empty">-</span>'}</td>
            <td>${escapeHtml(c.channel_type || '-')}</td>
            <td><span class="status-pill ${statusClass(c.status)}">${c.status || '-'}</span></td>
            <td class="td-num">${fmtEur.format(c.cost)}</td>
            <td class="td-num">${fmtInt.format(c.impressions)}</td>
            <td class="td-num">${fmtInt.format(c.clicks)}</td>
            <td class="td-num">${fmtPct(c.ctr)}</td>
            <td class="td-num">${c.clicks > 0 ? fmtEur3.format(c.cpc) : '-'}</td>
            <td class="td-num">${c.conversions > 0 ? fmtInt.format(Math.round(c.conversions)) : '-'}</td>
            <td class="td-num">${c.revenue > 0 ? fmtEur.format(c.revenue) : '-'}</td>
            <td class="td-num">${c.roas > 0 ? c.roas.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+'x' : '-'}</td>
        </tr>
    `).join('');

    const tot = rows.reduce((acc, c) => {
        acc.cost += c.cost; acc.impr += c.impressions; acc.clicks += c.clicks;
        acc.conv += c.conversions; acc.rev += c.revenue;
        return acc;
    }, { cost: 0, impr: 0, clicks: 0, conv: 0, rev: 0 });
    const totCtr = tot.impr > 0 ? (tot.clicks / tot.impr * 100) : 0;
    const totCpc = tot.clicks > 0 ? (tot.cost / tot.clicks) : 0;
    const totRoas = tot.cost > 0 ? (tot.rev / tot.cost) : 0;
    tfoot.innerHTML = `
        <tr>
            <td>Total (${rows.length} campañas)</td>
            <td></td><td></td><td></td>
            <td class="td-num">${fmtEur.format(tot.cost)}</td>
            <td class="td-num">${fmtInt.format(tot.impr)}</td>
            <td class="td-num">${fmtInt.format(tot.clicks)}</td>
            <td class="td-num">${fmtPct(totCtr)}</td>
            <td class="td-num">${tot.clicks > 0 ? fmtEur3.format(totCpc) : '-'}</td>
            <td class="td-num">${fmtInt.format(Math.round(tot.conv))}</td>
            <td class="td-num">${fmtEur.format(tot.rev)}</td>
            <td class="td-num">${totRoas > 0 ? totRoas.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+'x' : '-'}</td>
        </tr>
    `;
}

async function loadWeeklyOnly() {
    try {
        renderWeekly(await fetchWeekly());
    } catch (e) {
        toast('Error cargando tabla semanal: ' + e.message, 'error');
    }
}

async function loadShoppingOnly() {
    try {
        renderShoppingComparison(await fetchShoppingComparison());
    } catch (e) {
        toast('Error cargando comparativa Shopping: ' + e.message, 'error');
    }
}

// === Comparativa Shopping por pais ===
let chartShoppingCost = null;
let chartShoppingCpc = null;
let chartShoppingCtr = null;

function buildShoppingChart(canvasId, payload, metric, yLabel, formatter) {
    const periods = payload.periods || [];
    const countries = payload.countries || [];
    const series = (payload.series && payload.series[metric]) || {};
    const labels = periods.map(p => p.label);
    const datasets = countries.map(c => ({
        label: c,
        data: series[c] || [],
        borderColor: colorForCountry(c),
        backgroundColor: colorForCountry(c) + '22',
        fill: false,
        tension: 0.3,
        borderWidth: 2,
        pointRadius: 2,
        pointHoverRadius: 5,
    }));
    const ctx = document.getElementById(canvasId).getContext('2d');
    return new Chart(ctx, {
        type: 'line',
        data: { labels, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: {
                    position: 'top',
                    labels: { boxWidth: 10, font: { size: 11 }, padding: 8 },
                },
                tooltip: {
                    callbacks: {
                        label: (ctx) => `${ctx.dataset.label}: ${formatter(ctx.parsed.y)}`,
                    },
                },
            },
            scales: {
                x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 10, font: { size: 10 } } },
                y: {
                    title: { display: true, text: yLabel },
                    grid: { color: 'rgba(15,23,42,0.05)' },
                    ticks: { callback: (v) => formatter(v), font: { size: 10 } },
                },
            },
        },
    });
}

function renderShoppingComparison(payload) {
    if (!payload || !payload.countries) return;

    const info = $('#shopping-info');
    if (info) {
        const granLabel = payload.granularity === 'monthly' ? 'meses' : payload.granularity === 'weekly' ? 'semanas' : 'días';
        info.textContent = `${payload.periods.length} ${granLabel} · ${payload.since} a ${payload.until} · ${payload.countries.length} países`;
    }

    if (chartShoppingCost) chartShoppingCost.destroy();
    if (chartShoppingCpc) chartShoppingCpc.destroy();
    if (chartShoppingCtr) chartShoppingCtr.destroy();

    const fmtEurFn = (v) => fmtEur.format(v || 0) + ' €';
    const fmtCpcFn = (v) => fmtEur3.format(v || 0) + ' €';
    const fmtCtrFn = (v) => (v || 0).toLocaleString('es-ES', { maximumFractionDigits: 2 }) + '%';

    chartShoppingCost = buildShoppingChart('chart-shopping-cost', payload, 'cost', 'EUR', fmtEurFn);
    chartShoppingCpc = buildShoppingChart('chart-shopping-cpc', payload, 'cpc', 'EUR / click', fmtCpcFn);
    chartShoppingCtr = buildShoppingChart('chart-shopping-ctr', payload, 'ctr', '%', fmtCtrFn);

    // Tabla de totales (ordenada por gasto descendente)
    const tbody = $('#table-shopping-totals tbody');
    const sorted = [...payload.countries].sort((a, b) => (payload.totals[b].cost || 0) - (payload.totals[a].cost || 0));
    tbody.innerHTML = sorted.map(c => {
        const t = payload.totals[c];
        return `
            <tr>
                <td>${flagImg(c)}<span style="color:${colorForCountry(c)};font-weight:600;">●</span> ${escapeHtml(c)}</td>
                <td class="td-num">${fmtEur.format(t.cost)} €</td>
                <td class="td-num">${fmtInt.format(t.clicks)}</td>
                <td class="td-num">${fmtInt.format(t.impressions)}</td>
                <td class="td-num">${(t.ctr || 0).toLocaleString('es-ES', { maximumFractionDigits: 2 })}%</td>
                <td class="td-num">${fmtEur3.format(t.cpc)} €</td>
            </tr>
        `;
    }).join('');
}

// === Weekly table render ===
function fmtCell(value, format) {
    if (value === 0 || value === null || value === undefined) return '<span class="empty">-</span>';
    if (format === 'eur') return fmtEur.format(value) + ' €';
    if (format === 'pct') return value.toLocaleString('es-ES', {minimumFractionDigits:1, maximumFractionDigits:1}) + '%';
    if (format === 'x') return value.toLocaleString('es-ES', {minimumFractionDigits:2, maximumFractionDigits:2}) + 'x';
    return fmtInt.format(value);
}

function renderWeekly(payload) {
    const periods = payload.periods || [];
    const sections = payload.sections || [];

    // Cabecera
    const thead = $('#weekly-table thead');
    let html = '<tr>';
    html += `<th class="col-label">Métrica</th>`;
    html += `<th class="col-total">${escapeHtml(payload.totals_label || 'Acumulado')}</th>`;
    periods.forEach(p => {
        html += `<th class="col-period">${escapeHtml(p.label)}</th>`;
    });
    html += '</tr>';
    thead.innerHTML = html;

    // Cuerpo
    const tbody = $('#weekly-table tbody');
    const colspan = 2 + periods.length;
    let bodyHtml = '';

    sections.forEach(sec => {
        bodyHtml += `<tr class="section-title"><td class="col-label" colspan="${colspan}">${escapeHtml(sec.title)}</td></tr>`;
        sec.rows.forEach(row => {
            const cls = [];
            if (row.indent) cls.push('row-indent');
            if (row.header) cls.push('row-header');
            bodyHtml += `<tr class="${cls.join(' ')}">`;
            const labelTooltip = row.note ? ` title="${escapeHtml(row.note)}"` : '';
            const labelExtra = row.note ? ' <span class="note-disabled">(pendiente)</span>' : '';
            bodyHtml += `<td class="col-label"${labelTooltip}>${escapeHtml(row.label)}${labelExtra}</td>`;
            bodyHtml += `<td class="col-total">${fmtCell(row.total, row.format)}</td>`;
            row.values.forEach(v => {
                bodyHtml += `<td class="col-period">${fmtCell(v, row.format)}</td>`;
            });
            bodyHtml += '</tr>';
        });
    });
    tbody.innerHTML = bodyHtml;

    // Info
    $('#weekly-info').textContent = `${periods.length} ${payload.granularity === 'monthly' ? 'meses' : payload.granularity === 'weekly' ? 'semanas' : 'días'} - ${payload.since} a ${payload.until}${payload.country ? ' - ' + payload.country : ''}`;
}

async function loadTimeseriesOnly() {
    try {
        const ts = await fetchTimeseries();
        renderTimeseries(ts);
    } catch (e) {
        toast('Error cargando grafico: ' + e.message, 'error');
    }
}

async function loadCountrySelector() {
    try {
        const countries = await fetchCountries();
        const ul = $('#country-options');
        // Opcion "todos" + resto con bandera SVG
        const items = [
            `<li data-value="" class="selected"><span class="flag-fallback">🌐</span> Todos los países</li>`
        ];
        countries.forEach(c => {
            items.push(`<li data-value="${escapeHtml(c)}">${flagImg(c)} ${escapeHtml(c)}</li>`);
        });
        ul.innerHTML = items.join('');
    } catch (e) {
        console.error('No se pudo cargar lista de paises:', e);
    }
}

function setupCountryDropdown() {
    const dropdown = $('#country-dropdown');
    const trigger = $('#country-trigger');
    const ul = $('#country-options');
    const triggerFlag = $('#country-trigger-flag');
    const triggerLabel = $('#country-trigger-label');

    trigger.addEventListener('click', (e) => {
        e.stopPropagation();
        dropdown.classList.toggle('open');
    });

    document.addEventListener('click', (e) => {
        if (!dropdown.contains(e.target)) dropdown.classList.remove('open');
    });

    ul.addEventListener('click', (e) => {
        const li = e.target.closest('li');
        if (!li) return;
        const value = li.dataset.value;
        // Marcar seleccionada
        ul.querySelectorAll('li').forEach(x => x.classList.remove('selected'));
        li.classList.add('selected');
        // Actualizar trigger
        triggerLabel.textContent = value || 'Todos los países';
        triggerFlag.innerHTML = value ? flagImg(value) : '<span class="flag-fallback">🌐</span>';
        dropdown.classList.toggle('has-value', !!value);
        dropdown.classList.remove('open');
        // Aplicar filtro
        if (value !== state.country) {
            state.country = value;
            loadAll();
        }
    });
}

// === Sync ===
async function doSyncSource(btnId, endpoint, labelOriginal, labelDuring) {
    const btn = document.getElementById(btnId);
    btn.classList.add('syncing');
    btn.disabled = true;
    const labelEl = $('.sync-label', btn);
    labelEl.textContent = labelDuring;
    try {
        const r = await fetch(endpoint, { method: 'POST' });
        const data = await r.json();
        if (data.status === 'ok') {
            toast(`Sincronizacion ${labelOriginal} completada`, 'success');
            await loadAll();
        } else {
            toast('Error: ' + (data.error || 'desconocido'), 'error');
        }
    } catch (e) {
        toast('Error de red: ' + e.message, 'error');
    } finally {
        btn.classList.remove('syncing');
        btn.disabled = false;
        labelEl.textContent = labelOriginal;
    }
}

const doSync = () => doSyncSource('btn-sync', '/api/sync', 'Meta', 'Meta...');
const doSyncGoogle = () => doSyncSource('btn-sync-google', '/api/google/sync', 'Google', 'Google...');
const doSyncHs = () => doSyncSource('btn-sync-hs', '/api/hubspot/sync', 'HubSpot', 'HubSpot...');

// === Chatbot ===
const chatState = { history: [] };

function chatAppendMessage(role, text, tools) {
    const container = $('#chat-messages');
    const div = document.createElement('div');
    div.className = `chat-msg chat-msg-${role}`;
    // Render markdown muy basico (negrita, codigo inline, listas y saltos)
    div.innerHTML = role === 'bot' ? formatBotText(text) : escapeHtml(text);
    if (tools && tools.length) {
        const tt = document.createElement('div');
        tt.className = 'chat-msg-tools';
        tt.textContent = '🔧 ' + tools.map(t => t.name).join(', ');
        div.appendChild(tt);
    }
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    return div;
}

function chatAppendLoading() {
    const container = $('#chat-messages');
    const div = document.createElement('div');
    div.className = 'chat-msg chat-msg-bot chat-msg-loading';
    div.textContent = 'Pensando';
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    return div;
}

function chatAppendError(text) {
    const container = $('#chat-messages');
    const div = document.createElement('div');
    div.className = 'chat-msg chat-msg-bot chat-msg-error';
    div.textContent = text;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

function formatBotText(s) {
    if (!s) return '';
    // Basico: escapar HTML primero, despues sustituciones de markdown
    let html = escapeHtml(s);
    // **bold** -> <strong>
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // `code` -> <code>
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    // Tablas markdown (linea con | ... |)
    const lines = html.split('\n');
    const out = [];
    let inTable = false;
    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        const isRow = /^\s*\|.*\|\s*$/.test(line);
        const isSep = /^\s*\|[\s|:-]+\|\s*$/.test(line);
        if (isRow && !isSep) {
            if (!inTable) { out.push('<table>'); inTable = true; }
            const cells = line.trim().slice(1, -1).split('|').map(c => c.trim());
            // Comprobar si la linea siguiente es separador (=> header)
            const isHeader = lines[i + 1] && /^\s*\|[\s|:-]+\|\s*$/.test(lines[i + 1]);
            const tag = isHeader ? 'th' : 'td';
            out.push('<tr>' + cells.map(c => `<${tag}>${c}</${tag}>`).join('') + '</tr>');
        } else if (isSep) {
            // separador de header, no renderizamos
        } else {
            if (inTable) { out.push('</table>'); inTable = false; }
            out.push(line);
        }
    }
    if (inTable) out.push('</table>');
    return out.join('<br>').replace(/<br><table>/g, '<table>').replace(/<\/table><br>/g, '</table>');
}

async function chatSend(text) {
    if (!text || !text.trim()) return;
    const userMsg = text.trim();
    chatAppendMessage('user', userMsg);
    chatState.history.push({ role: 'user', content: userMsg });

    const loading = chatAppendLoading();
    const sendBtn = $('.chat-send');
    const input = $('#chat-input');
    sendBtn.disabled = true;
    input.disabled = true;

    try {
        const r = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                messages: chatState.history,
                country: state.country || null,
            }),
        });
        loading.remove();
        if (!r.ok) {
            const err = await r.json().catch(() => ({}));
            chatAppendError('Error: ' + (err.error || `HTTP ${r.status}`));
            return;
        }
        const data = await r.json();
        chatAppendMessage('bot', data.reply, data.tools_used);
        chatState.history.push({ role: 'assistant', content: data.reply });
    } catch (e) {
        loading.remove();
        chatAppendError('Error de red: ' + e.message);
    } finally {
        sendBtn.disabled = false;
        input.disabled = false;
        input.value = '';
        input.focus();
    }
}

function setupCustomRangePicker() {
    const wrapper = $('#custom-range');
    const btn = $('#btn-custom-range');
    const sinceInput = $('#custom-since');
    const untilInput = $('#custom-until');
    const apply = $('#custom-apply');
    const cancel = $('#custom-cancel');
    const label = $('#custom-range-label');

    // Valores por defecto: ultimos 30 dias
    const today = new Date();
    const monthAgo = new Date(today);
    monthAgo.setDate(today.getDate() - 29);
    sinceInput.value = monthAgo.toISOString().substring(0, 10);
    untilInput.value = today.toISOString().substring(0, 10);
    untilInput.max = today.toISOString().substring(0, 10);

    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        wrapper.classList.toggle('open');
    });
    document.addEventListener('click', (e) => {
        if (!wrapper.contains(e.target)) wrapper.classList.remove('open');
    });
    cancel.addEventListener('click', () => wrapper.classList.remove('open'));

    apply.addEventListener('click', () => {
        const since = sinceInput.value;
        const until = untilInput.value;
        if (!since || !until) {
            toast('Debes elegir ambas fechas', 'error');
            return;
        }
        if (since > until) {
            toast('La fecha "Desde" debe ser anterior a "Hasta"', 'error');
            return;
        }
        state.days = 'custom';
        state.customSince = since;
        state.customUntil = until;

        // Marcar este boton como activo, desmarcar los presets
        $$('.range-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');

        // Etiqueta corta
        const sDate = since.split('-').reverse().slice(0, 2).join('/'); // dd/mm
        const uDate = until.split('-').reverse().slice(0, 2).join('/');
        label.textContent = `${sDate} - ${uDate}`;

        // Si el rango es largo, forzar granularidad mensual
        const days = (new Date(until) - new Date(since)) / 86400000 + 1;
        if (days >= 180) {
            state.granularity = 'monthly';
            $$('.gran-btn').forEach(b => b.classList.toggle('active', b.dataset.gran === 'monthly'));
        }

        wrapper.classList.remove('open');
        loadAll();
    });
}

function setupChatbot() {
    const widget = $('#chat-widget');
    $('#chat-toggle').addEventListener('click', () => {
        widget.classList.add('open');
        $('#chat-input').focus();
    });
    $('#chat-close').addEventListener('click', () => widget.classList.remove('open'));

    $('#chat-form').addEventListener('submit', (e) => {
        e.preventDefault();
        const v = $('#chat-input').value;
        chatSend(v);
    });

    $$('.chat-suggestion').forEach(btn => {
        btn.addEventListener('click', () => chatSend(btn.dataset.q));
    });
}

// === Init ===
function init() {
    // Selector de rango (preset)
    $$('.range-btn[data-days]').forEach(btn => {
        btn.addEventListener('click', () => {
            $$('.range-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            // "all" se pasa tal cual; los numericos se mantienen como string
            state.days = btn.dataset.days;
            state.customSince = null;
            state.customUntil = null;
            // Reset etiqueta del boton personalizado
            $('#custom-range-label').textContent = 'Personalizado';
            // Si pasamos a "Todo" o "12 meses", forzar granularidad mensual por defecto
            if (state.days === 'all' || parseInt(state.days, 10) >= 180) {
                state.granularity = 'monthly';
                $$('.gran-btn').forEach(b => b.classList.toggle('active', b.dataset.gran === 'monthly'));
            }
            loadAll();
        });
    });

    // Selector de rango personalizado
    setupCustomRangePicker();

    // Selector de granularidad (solo afecta al grafico de evolucion)
    $$('.gran-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            $$('.gran-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            state.granularity = btn.dataset.gran;
            loadTimeseriesOnly();
        });
    });

    $('#btn-sync').addEventListener('click', doSync);
    $('#btn-sync-google').addEventListener('click', doSyncGoogle);
    $('#btn-sync-hs').addEventListener('click', doSyncHs);
    $('#btn-export').addEventListener('click', exportCsv);

    // Selector de pais (dropdown custom para soportar imagenes de banderas)
    setupCountryDropdown();

    // Selector de granularidad de la tabla semanal (independiente del grafico)
    $$('.wgran-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            $$('.wgran-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            state.weeklyGranularity = btn.dataset.wgran;
            loadWeeklyOnly();
        });
    });

    // Selector de granularidad de la comparativa Shopping por pais
    $$('.sgran-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            $$('.sgran-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            state.shoppingGranularity = btn.dataset.sgran;
            loadShoppingOnly();
        });
    });

    setupTableSort();
    setupChatbot();
    loadCountrySelector();
    loadAll();
}

document.addEventListener('DOMContentLoaded', init);
