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
    shoppingDisabledCountries: new Set(), // paises ocultos en los charts de Shopping
    shoppingPayload: null,    // cache del ultimo payload para re-render sin refetch
    shoppingSortBy: 'cost',   // columna por la que se ordena la tabla shopping
    shoppingSortDir: 'desc',  // asc | desc
    // === Search (paralelo a Shopping) ===
    searchGranularity: 'weekly',
    searchDisabledCountries: new Set(),
    searchPayload: null,
    searchSortBy: 'cost',
    searchSortDir: 'desc',
    // Drill-down de Search por ad group (cache por pais + paises expandidos)
    searchAdGroupsByCountry: {},
    searchExpandedCountries: new Set(),
    // === Meta (paralelo a Shopping) ===
    metaGranularity: 'weekly',
    metaDisabledCountries: new Set(),
    metaPayload: null,
    metaSortBy: 'cost',
    metaSortDir: 'desc',
    // Drill-down de Meta por ad set (cache por pais + paises expandidos)
    metaAdSetsByCountry: {},
    metaExpandedCountries: new Set(),
    // Granularidad de los 3 charts del top del Resumen (Inversion/Leads/CPL)
    resumenGranularity: 'weekly',
    // Set vacio (buildChannelChart espera DisabledCountries por kind; Resumen
    // no expone chips de paises pero reusamos la misma funcion).
    resumenDisabledCountries: new Set(),
    // Ocultar buckets parciales (semanas/meses incompletos por bordes del rango)
    resumenHidePartial: (() => {
        try { return localStorage.getItem('resumen-hide-partial') === '1'; }
        catch (e) { return false; }
    })(),
    // Filas expandidas en la tabla "Vista por periodos" (Resumen tab).
    // Cada id es 'w-{section_idx}-{row_idx}'. No persistimos en localStorage
    // (las expansiones se reinician al recargar la pagina).
    weeklyExpandedRows: new Set(),
    // Tratamiento de boosted posts (LINK_CLICKS): 'hidden' | 'budget_hidden' | 'all'.
    // Default 'hidden' = vista limpia de marketing real de captacion.
    metaBoostedMode: (() => {
        try {
            const v = localStorage.getItem('meta-boosted-mode');
            return ['hidden', 'budget_hidden', 'all'].includes(v) ? v : 'hidden';
        }
        catch (e) { return 'hidden'; }
    })(),
    alertsPayload: null,      // cache del ultimo payload de alertas para refiltrar por tab
    activeTab: 'resumen',     // pestana activa: resumen | shopping | search | hubspot
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
const fetchSearchComparison   = () => fetchJson(`/api/google/search-comparison?${buildQuery({granularity: state.searchGranularity})}`);
const fetchSearchAdGroups     = (country) => fetchJson(`/api/google/search-ad-groups?${buildQuery({country: country || ''})}`);
const fetchMetaComparison     = () => fetchJson(`/api/meta/country-comparison?${buildQuery({granularity: state.metaGranularity, boosted_mode: state.metaBoostedMode})}`);
const fetchMetaAdSets         = (country) => fetchJson(`/api/meta/ad-sets?${buildQuery({country: country || '', boosted_mode: state.metaBoostedMode})}`);
const fetchResumenComparison  = () => fetchJson(`/api/resumen-comparison?${buildQuery({granularity: state.resumenGranularity})}`);

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
    $('#kpi-cpc').textContent = fmtEur.format(k.cpc);
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
    // El canvas se elimino del Resumen; si no existe, salimos.
    const canvas = $('#chart-timeseries');
    if (!canvas) return;
    const granularity = payload.granularity || 'daily';
    const data = payload.data || [];
    const labels = data.map(d => formatPeriodLabel(d.period, granularity));
    const spend = data.map(d => d.spend);
    const leads = data.map(d => d.leads);

    const titleMap = { daily: 'Evolución diaria', weekly: 'Evolución semanal', monthly: 'Evolución mensual' };
    const titleEl = $('#chart-timeseries-title');
    if (titleEl) titleEl.textContent = titleMap[granularity] || 'Evolución';

    const ctx = canvas.getContext('2d');
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
    // El canvas se elimino del Resumen; si no existe, salimos.
    const canvas = $('#chart-top-campaigns');
    if (!canvas) return;
    const top = campaigns.filter(c => c.spend > 0).slice(0, 8);
    const labels = top.map(c => truncate(c.name, 28));
    const spend = top.map(c => c.spend);

    const ctx = canvas.getContext('2d');
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
            <td class="td-num">${c.clicks > 0 ? fmtEur.format(c.cpc) : '-'}</td>
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
            <td class="td-num">${tot.clicks > 0 ? fmtEur.format(totCpc) : '-'}</td>
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
    // Reset de caches dependientes de filtros (rango/pais)
    state.searchAdGroupsByCountry = {};
    state.searchExpandedCountries = new Set();
    state.metaAdSetsByCountry = {};
    state.metaExpandedCountries = new Set();
    try {
        const [k, ts, cs, hsK, hsF, hsSrc, hsSt, hsCo, wk, gK, gCs, al, sh, sr, mt, rs] = await Promise.all([
            fetchKpis(), fetchTimeseries(), fetchCampaigns(),
            fetchHsKpis(), fetchHsFunnel(), fetchHsBySource(),
            fetchHsByStatus(), fetchHsByCountry(),
            fetchWeekly(),
            fetchGoogleKpis(), fetchGoogleCampaigns(),
            fetchAlerts(),
            fetchShoppingComparison(),
            fetchSearchComparison(),
            fetchMetaComparison(),
            fetchResumenComparison(),
        ]);
        renderAlerts(al);
        renderChannelComparison('shopping', sh);
        renderChannelComparison('search', sr);
        renderChannelComparison('meta', mt);
        renderResumenComparison(rs);
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

// Mini-tag de delta para celdas de tabla. direction:
//   'up-good'   -> subida verde (clicks, impressions, ctr, conv, revenue, utilization, ...)
//   'down-good' -> bajada verde (cpc, cpl, cpm, cac)
//   'neutral'   -> azul/gris (cost, daily_budget, budget_period: subir/bajar no es bueno per se)
function deltaTag(pct, direction = 'up-good') {
    if (pct === null || pct === undefined) return '';
    const isFlat = Math.abs(pct) < 0.5;
    let cls = 'delta-flat';
    let arrow = '→';
    if (!isFlat) {
        const isUp = pct > 0;
        if (isUp) {
            arrow = '↑';
            cls = direction === 'up-good' ? 'delta-up' : direction === 'down-good' ? 'delta-down' : 'delta-flat';
        } else {
            arrow = '↓';
            cls = direction === 'down-good' ? 'delta-up' : direction === 'up-good' ? 'delta-down' : 'delta-flat';
        }
    }
    const sign = pct > 0 ? '+' : '';
    const pctStr = pct.toLocaleString('es-ES', { maximumFractionDigits: 1 });
    return `<span class="delta-mini ${cls}"><span class="delta-mini-arrow">${arrow}</span> ${sign}${pctStr}%</span>`;
}

// === Alerts render ===
// Filtra las alertas segun la pestana activa.
// Shopping tab -> solo campanas Shopping (basado en convencion de naming "| Shopping |").
// Resto -> todas.
function filterAlertsByTab(alerts, tab) {
    if (tab === 'shopping') {
        return alerts.filter(a => /\|\s*Shopping\s*\|/i.test(a.campaign_name || ''));
    }
    if (tab === 'search') {
        return alerts.filter(a => /\|\s*Search\s*\|/i.test(a.campaign_name || ''));
    }
    if (tab === 'meta') {
        // Alertas Meta: filtrar por canal META (mas fiable que por naming)
        return alerts.filter(a => (a.channel || '').toUpperCase() === 'META');
    }
    return alerts;
}

function renderAlerts(payload) {
    state.alertsPayload = payload;
    renderAlertsFiltered();
}

function renderAlertsFiltered() {
    const payload = state.alertsPayload;
    if (!payload) return;
    const bar = $('#alerts-bar');
    const list = $('#alerts-list');
    const allAlerts = payload.alerts || [];
    const alerts = filterAlertsByTab(allAlerts, state.activeTab);
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
    $('#g-kpi-cpc').textContent = fmtEur.format(k.cpc);
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
    setDelta('g-delta-cpc', d.cpc_pct, 'cpc', fmtForDelta(p.cpc || 0, 'eur'));
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
            <td class="td-num">${c.clicks > 0 ? fmtEur.format(c.cpc) : '-'}</td>
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
            <td class="td-num">${tot.clicks > 0 ? fmtEur.format(totCpc) : '-'}</td>
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
        renderChannelComparison('shopping', await fetchShoppingComparison());
    } catch (e) {
        toast('Error cargando comparativa Shopping: ' + e.message, 'error');
    }
}

async function loadSearchOnly() {
    try {
        // Al recargar Search invalidamos el cache de ad groups: el rango/pais
        // pudo cambiar y los totales cacheados ya no serian validos.
        state.searchAdGroupsByCountry = {};
        state.searchExpandedCountries = new Set();
        renderChannelComparison('search', await fetchSearchComparison());
    } catch (e) {
        toast('Error cargando comparativa Search: ' + e.message, 'error');
    }
}

async function loadMetaOnly() {
    try {
        state.metaAdSetsByCountry = {};
        state.metaExpandedCountries = new Set();
        renderChannelComparison('meta', await fetchMetaComparison());
    } catch (e) {
        toast('Error cargando comparativa Meta: ' + e.message, 'error');
    }
}

async function loadResumenComparisonOnly() {
    try {
        renderResumenComparison(await fetchResumenComparison());
    } catch (e) {
        toast('Error cargando charts del Resumen: ' + e.message, 'error');
    }
}

// Renderiza los 3 charts del top del Resumen (Inversion / Leads / CPL) con
// una sola serie agregada (no desglosado por pais). Marca con opacidad
// reducida los buckets parciales (semanas/meses incompletos por bordes del
// rango), o los oculta si state.resumenHidePartial = true.
function renderResumenComparison(payload) {
    if (!payload || !payload.series) return;
    const charts = channelCharts.resumen;
    if (charts.cost)  charts.cost.destroy();
    if (charts.leads) charts.leads.destroy();
    if (charts.cpl)   charts.cpl.destroy();

    // Filtra periods/series si el toggle "Ocultar parciales" esta activo.
    let periods = payload.periods || [];
    let costSeries = payload.series.cost || [];
    let leadsSeries = payload.series.leads || [];
    let cplSeries = payload.series.cpl || [];
    if (state.resumenHidePartial) {
        const idxKeep = periods.map((p, i) => p.is_partial ? -1 : i).filter(i => i >= 0);
        periods = idxKeep.map(i => periods[i]);
        costSeries = idxKeep.map(i => costSeries[i]);
        leadsSeries = idxKeep.map(i => leadsSeries[i]);
        cplSeries = idxKeep.map(i => cplSeries[i]);
    }

    const fmtEurFn = (v) => fmtEur.format(v || 0) + ' €';
    const fmtIntFn = (v) => fmtInt.format(v || 0);

    // Hero palette: Blue + Red + Navy
    charts.cost  = buildAggregateChart('chart-resumen-cost',  periods, costSeries,  'EUR',        fmtEurFn, 'bar',  '#005e94');
    charts.leads = buildAggregateChart('chart-resumen-leads', periods, leadsSeries, 'Leads',      fmtIntFn, 'bar',  '#e3332b');
    charts.cpl   = buildAggregateChart('chart-resumen-cpl',   periods, cplSeries,   'EUR / lead', fmtEurFn, 'line', '#323f49');

    const info = document.getElementById('resumen-info');
    if (info) {
        const granLabel = payload.granularity === 'monthly' ? 'meses' : payload.granularity === 'weekly' ? 'semanas' : 'días';
        const partialCount = (payload.periods || []).filter(p => p.is_partial).length;
        const partialHint = (partialCount && !state.resumenHidePartial)
            ? ` · ${partialCount} parcial${partialCount > 1 ? 'es' : ''} (atenuados)`
            : '';
        info.textContent = `${periods.length} ${granLabel} · ${payload.since} a ${payload.until}${partialHint}`;
    }
}

// Builder para charts agregados (una sola serie). Usado por el Resumen.
// `periods` es un array de {key, label, is_partial, days_covered, days_total}.
// Los buckets parciales se renderizan con opacidad reducida + asterisco en
// el datalabel y tooltip enriquecido.
function buildAggregateChart(canvasId, periods, data, yLabel, formatter, chartType, color) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;
    const ctx = canvas.getContext('2d');

    const labels = periods.map(p => (p.label + (p.is_partial ? ' *' : '')));
    // Color por punto: pleno para completo, semi-transparente para parcial.
    const colorFull = color;
    const colorPartial = color + '66';  // ~40% alpha
    const pointColors = periods.map(p => p.is_partial ? colorPartial : colorFull);

    const dataset = (chartType === 'bar')
        ? {
            label: 'Total',
            data,
            backgroundColor: pointColors,
            borderColor: pointColors,
            borderWidth: 0,
            borderRadius: 4,
            maxBarThickness: 36,
        }
        : {
            label: 'Total',
            data,
            borderColor: color,
            backgroundColor: color + '22',
            fill: false,
            tension: 0.3,
            borderWidth: 2,
            pointRadius: periods.map(p => p.is_partial ? 4 : 3),
            pointHoverRadius: 6,
            pointBackgroundColor: pointColors,
            pointBorderColor: pointColors,
            pointStyle: periods.map(p => p.is_partial ? 'crossRot' : 'circle'),
        };
    return new Chart(ctx, {
        type: chartType,
        data: { labels, datasets: [dataset] },
        plugins: window.ChartDataLabels ? [window.ChartDataLabels] : [],
        options: {
            responsive: true,
            maintainAspectRatio: false,
            layout: { padding: { top: 18 } },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (ctx) => {
                            const p = periods[ctx.dataIndex] || {};
                            const v = formatter(ctx.parsed.y);
                            if (p.is_partial) {
                                return `${v}  ·  Parcial: ${p.days_covered}/${p.days_total} días`;
                            }
                            return v;
                        },
                    },
                },
                datalabels: {
                    anchor: 'end',
                    align: 'top',
                    offset: 2,
                    clamp: true,
                    font: { size: 11, weight: '600' },
                    color: (ctx) => periods[ctx.dataIndex] && periods[ctx.dataIndex].is_partial
                        ? colorPartial : colorFull,
                    display: (ctx) => {
                        const v = ctx.dataset.data[ctx.dataIndex];
                        return v !== null && v !== undefined && v !== 0;
                    },
                    formatter: (value, ctx) => {
                        const p = periods[ctx.dataIndex] || {};
                        return formatter(value) + (p.is_partial ? ' *' : '');
                    },
                },
            },
            scales: {
                x: { grid: { display: false }, ticks: { font: { size: 10 } } },
                y: {
                    title: { display: true, text: yLabel },
                    grid: { color: 'rgba(15,23,42,0.05)' },
                    ticks: { callback: (v) => formatter(v), font: { size: 10 } },
                    beginAtZero: chartType === 'bar',
                },
            },
        },
    });
}

// === Comparativa de canal (Shopping / Search) por pais ===
// Estructura paralela: un set de DOM IDs prefijado por kind + un slot de charts por kind.
const channelCharts = {
    resumen:  { cost: null, leads: null, cpl: null },
    meta:     { cost: null, cpc: null, ctr: null },
    shopping: { cost: null, cpc: null, ctr: null },
    search:   { cost: null, cpc: null, ctr: null },
};

// Devuelve los selectores/keys derivados del kind ('shopping' | 'search').
function channelCfg(kind) {
    return {
        kind,
        ids: {
            info:          `${kind}-info`,
            chips:         `${kind}-country-chips`,
            tableTotals:   `table-${kind}-totals`,
            chartCost:     `chart-${kind}-cost`,
            chartCpc:      `chart-${kind}-cpc`,
            chartCtr:      `chart-${kind}-ctr`,
            detailTable:   `${kind}-detail-table`,
            detailWrapper: `${kind}-detail-wrapper`,
            detailInfo:    `${kind}-detail-info`,
        },
        stateKeys: {
            payload:           `${kind}Payload`,
            disabledCountries: `${kind}DisabledCountries`,
            sortBy:            `${kind}SortBy`,
            sortDir:           `${kind}SortDir`,
            granularity:       `${kind}Granularity`,
        },
    };
}

function buildChannelChart(kind, canvasId, payload, metric, yLabel, formatter, chartType = 'line') {
    const disabledSet = state[channelCfg(kind).stateKeys.disabledCountries];
    const periods = payload.periods || [];
    const series = (payload.series && payload.series[metric]) || {};
    // Filtrar paises desactivados
    const countries = (payload.countries || []).filter(c => !disabledSet.has(c));
    const labels = periods.map(p => p.label);

    const datasets = countries.map(c => {
        const color = colorForCountry(c);
        if (chartType === 'bar') {
            return {
                label: c,
                data: series[c] || [],
                backgroundColor: color,
                borderColor: color,
                borderWidth: 0,
                borderRadius: 4,
                maxBarThickness: 28,
            };
        }
        return {
            label: c,
            data: series[c] || [],
            borderColor: color,
            backgroundColor: color + '22',
            fill: false,
            tension: 0.3,
            borderWidth: 2,
            pointRadius: 2,
            pointHoverRadius: 5,
        };
    });
    const ctx = document.getElementById(canvasId).getContext('2d');
    return new Chart(ctx, {
        type: chartType,
        data: { labels, datasets },
        // Plugin chartjs-plugin-datalabels (cargado via CDN) para mostrar el
        // valor sobre cada barra/punto. Registrado solo en estos charts para
        // no afectar a otros (timeseries, top campaigns, etc.).
        plugins: window.ChartDataLabels ? [window.ChartDataLabels] : [],
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            // Mas padding superior para que los labels no se corten arriba
            layout: { padding: { top: 18 } },
            plugins: {
                // Ocultamos legend porque ya tenemos los chips arriba
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (ctx) => `${ctx.dataset.label}: ${formatter(ctx.parsed.y)}`,
                    },
                },
                datalabels: {
                    anchor: 'end',
                    align: 'top',
                    offset: 2,
                    clamp: true,            // evita que labels se salgan del area
                    font: { size: 10, weight: '600' },
                    color: (ctx) => ctx.dataset.borderColor || ctx.dataset.backgroundColor || '#334155',
                    // Oculta el label si el valor es 0/null para no llenar de ceros
                    display: (ctx) => {
                        const v = ctx.dataset.data[ctx.dataIndex];
                        return v !== null && v !== undefined && v !== 0;
                    },
                    formatter: (value) => formatter(value),
                },
            },
            scales: {
                x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 10, font: { size: 10 } } },
                y: {
                    title: { display: true, text: yLabel },
                    grid: { color: 'rgba(15,23,42,0.05)' },
                    ticks: { callback: (v) => formatter(v), font: { size: 10 } },
                    beginAtZero: chartType === 'bar',
                },
            },
        },
    });
}

// Definicion de bloques de la tabla "tipo Excel" para cada kind.
// Shopping y Search comparten; Meta anade Leads/CPL (atribuidos via HubSpot).
const CHANNEL_DETAIL_METRICS = {
    shopping: [
        { key: 'cost',          title: 'Coste',                       format: 'eur',  totalKey: 'cost' },
        { key: 'daily_budget',  title: 'Presupuesto/día (medio)',     format: 'eur',  totalKey: 'daily_budget' },
        { key: 'budget_period', title: 'Presupuesto del periodo',     format: 'eur',  totalKey: 'budget_period' },
        { key: 'utilization',   title: 'Utilización',                 format: 'pct',  totalKey: 'utilization_pct' },
        { key: 'clicks',        title: 'Clicks',                      format: 'int',  totalKey: 'clicks' },
        { key: 'impressions',   title: 'Impresiones',                 format: 'int',  totalKey: 'impressions' },
        { key: 'ctr',           title: 'CTR',                         format: 'pct',  totalKey: 'ctr' },
        { key: 'cpc',           title: 'CPC',                         format: 'eur',  totalKey: 'cpc' },
    ],
};
CHANNEL_DETAIL_METRICS.search = CHANNEL_DETAIL_METRICS.shopping;  // alias
CHANNEL_DETAIL_METRICS.meta = [
    ...CHANNEL_DETAIL_METRICS.shopping,
    { key: 'leads', title: 'Leads (HubSpot)',  format: 'int',  totalKey: 'leads' },
    { key: 'cpl',   title: 'CPL (HubSpot)',     format: 'eur',  totalKey: 'cpl' },
];

// Numero total de columnas en la tabla de totales (drill-down usa este colspan).
// Meta anade 2 columnas (Leads + CPL) respecto a Shopping/Search.
const CHANNEL_TABLE_COLSPAN = {
    shopping: 9,
    search:   9,
    meta:     11,
};

function renderChannelDetailTable(kind, payload) {
    const cfg = channelCfg(kind);
    const table = document.getElementById(cfg.ids.detailTable);
    if (!table) return;
    const periods = payload.periods || [];
    const allCountries = payload.countries || [];
    const disabledSet = state[cfg.stateKeys.disabledCountries];
    const visibleCountries = allCountries.filter(c => !disabledSet.has(c));
    const series = payload.series || {};
    const totals = payload.totals || {};
    const colspan = 2 + periods.length;

    // Info
    const info = document.getElementById(cfg.ids.detailInfo);
    if (info) {
        const granLabel = payload.granularity === 'monthly' ? 'meses' : payload.granularity === 'weekly' ? 'semanas' : 'días';
        info.textContent = `${visibleCountries.length} países visibles · ${periods.length} ${granLabel}`;
    }

    // Cabecera doble (ano arriba + periodo abajo)
    const yearGroups = buildYearGroups(periods);
    const thead = table.querySelector('thead');
    let h = '<tr class="th-year-row">';
    h += `<th class="col-label" rowspan="2">Métrica / País</th>`;
    h += `<th class="col-total" rowspan="2">Acumulado</th>`;
    yearGroups.forEach(g => {
        h += `<th class="col-year" colspan="${g.colspan}">${escapeHtml(g.year)}</th>`;
    });
    h += '</tr><tr>';
    periods.forEach(p => { h += `<th class="col-period">${escapeHtml(p.label)}</th>`; });
    h += '</tr>';
    thead.innerHTML = h;

    // Cuerpo
    const tbody = table.querySelector('tbody');
    let body = '';
    const metrics = CHANNEL_DETAIL_METRICS[kind] || CHANNEL_DETAIL_METRICS.shopping;
    metrics.forEach(m => {
        body += `<tr class="section-title"><td colspan="${colspan}">${escapeHtml(m.title)}</td></tr>`;
        visibleCountries.forEach(c => {
            const total = totals[c] ? totals[c][m.totalKey] : null;
            const values = (series[m.key] && series[m.key][c]) || [];
            body += '<tr>';
            body += `<td class="col-label">${flagImg(c)}<span style="color:${colorForCountry(c)};">●</span> ${escapeHtml(c)}</td>`;
            body += `<td class="col-total">${fmtCell(total, m.format)}</td>`;
            values.forEach(v => {
                body += `<td class="col-period">${fmtCell(v, m.format)}</td>`;
            });
            body += '</tr>';
        });
    });
    tbody.innerHTML = body;
    setTimeout(() => {
        const wrap = document.getElementById(cfg.ids.detailWrapper);
        if (wrap) wrap.dispatchEvent(new Event('scroll'));
    }, 30);
}

function setupStickyHeightTracking() {
    // Mide la altura del .sticky-header del dashboard y la expone como
    // variable CSS --sticky-header-h, para que las cabeceras de las tablas
    // se queden pegadas justo debajo al hacer scroll vertical.
    const header = document.querySelector('.sticky-header');
    if (!header) return;
    const update = () => {
        const h = header.offsetHeight;
        if (h > 0) document.documentElement.style.setProperty('--sticky-header-h', h + 'px');
    };
    update();
    window.addEventListener('resize', update);
    // ResizeObserver para detectar cambios en el header (ej. al ocultar/mostrar alertas)
    try {
        new ResizeObserver(update).observe(header);
    } catch (e) { /* navegador antiguo: ok con resize listener */ }
}

function setupScrollControls() {
    // Botones flecha (← →) sobre cada tabla con scroll horizontal.
    // Hacen scroll por la mitad del viewport visible.
    document.querySelectorAll('.scroll-btn[data-scroll-target]').forEach(btn => {
        btn.addEventListener('click', () => {
            const wrapper = document.getElementById(btn.dataset.scrollTarget);
            if (!wrapper) return;
            const dir = parseInt(btn.dataset.scrollDir, 10) || 1;
            const delta = wrapper.clientWidth * 0.7 * dir;
            wrapper.scrollLeft += delta;
        });
    });
    // Activar/desactivar botones según posición de scroll
    const updateScrollState = (wrapper) => {
        const wrapperId = wrapper.id;
        const maxScroll = wrapper.scrollWidth - wrapper.clientWidth;
        const leftBtn = document.querySelector(`.scroll-btn[data-scroll-target="${wrapperId}"][data-scroll-dir="-1"]`);
        const rightBtn = document.querySelector(`.scroll-btn[data-scroll-target="${wrapperId}"][data-scroll-dir="1"]`);
        if (leftBtn) leftBtn.disabled = wrapper.scrollLeft <= 2;
        if (rightBtn) rightBtn.disabled = wrapper.scrollLeft >= maxScroll - 2;
    };
    document.querySelectorAll('.weekly-table-wrapper[id]').forEach(wrapper => {
        wrapper.addEventListener('scroll', () => updateScrollState(wrapper), { passive: true });
        // Estado inicial (un poco tras render) y al resize
        setTimeout(() => updateScrollState(wrapper), 100);
        window.addEventListener('resize', () => updateScrollState(wrapper));
    });
}

function setupChannelTableSort(kind) {
    const cfg = channelCfg(kind);
    const ths = document.querySelectorAll(`#${cfg.ids.tableTotals} thead th[data-sort]`);
    ths.forEach(th => {
        th.addEventListener('click', () => {
            const col = th.dataset.sort;
            if (state[cfg.stateKeys.sortBy] === col) {
                state[cfg.stateKeys.sortDir] = state[cfg.stateKeys.sortDir] === 'asc' ? 'desc' : 'asc';
            } else {
                state[cfg.stateKeys.sortBy] = col;
                // Por defecto: texto asc, numericos desc
                state[cfg.stateKeys.sortDir] = col === 'country' ? 'asc' : 'desc';
            }
            const cached = state[cfg.stateKeys.payload];
            if (cached) renderChannelComparison(kind, cached, true);
        });
    });
}

function renderChannelCountryChips(kind, payload) {
    const cfg = channelCfg(kind);
    const cont = document.getElementById(cfg.ids.chips);
    if (!cont) return;
    const countries = payload.countries || [];
    if (!countries.length) {
        cont.innerHTML = '';
        return;
    }
    const disabledSet = state[cfg.stateKeys.disabledCountries];
    const items = ['<span class="shopping-country-chips-label">Países:</span>'];
    countries.forEach(c => {
        const disabled = disabledSet.has(c);
        const color = colorForCountry(c);
        items.push(`
            <span class="country-chip ${disabled ? 'disabled' : ''}" data-country="${escapeHtml(c)}" style="border-color:${color};color:${color};">
                <span class="country-chip-dot" style="background:${color};"></span>
                ${flagImg(c)}<span>${escapeHtml(c)}</span>
            </span>
        `);
    });
    cont.innerHTML = items.join('');

    // Hooks click - toggle visibilidad
    cont.querySelectorAll('.country-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            const c = chip.dataset.country;
            if (disabledSet.has(c)) {
                disabledSet.delete(c);
            } else {
                disabledSet.add(c);
            }
            // Re-render solo los charts con el payload cacheado (sin re-fetch)
            const cached = state[cfg.stateKeys.payload];
            if (cached) renderChannelComparison(kind, cached, true);
        });
    });
}

// === Drill-down generico: por ad group (Search) o por ad set (Meta) ===
// Colspan kind-aware para las sub-filas del drill-down. Debe coincidir con
// el numero de columnas del thead de cada tabla de totales:
// CHANNEL_TABLE_COLSPAN[kind] (definido arriba).
function drillColspan(kind) { return CHANNEL_TABLE_COLSPAN[kind] || 9; }

// Config por kind: que fetcher usar, donde cachear, y como pintar cada sub-fila.
const DRILL_CFG = {
    search: {
        fetcher: fetchSearchAdGroups,
        cacheKey: 'searchAdGroupsByCountry',
        expandedKey: 'searchExpandedCountries',
        payloadKey: 'ad_groups',                  // campo de la respuesta JSON
        activeStatus: 'ENABLED',                  // status que NO se atenua
        loadingLabel: 'Cargando ad groups...',
        emptyLabel: 'No hay ad groups con datos en este periodo. (Ejecuta sync de Google Ads para poblar la tabla.)',
        headerCells: ['Ad group / Campaña', 'Coste', 'Clicks', 'Impr.', 'CTR', 'CPC', 'Conv.', 'ROAS'],
        renderRow: (g) => `
            <span class="drill-subrow-num">${fmtEur.format(g.cost)} €</span>
            <span class="drill-subrow-num">${fmtInt.format(g.clicks)}</span>
            <span class="drill-subrow-num">${fmtInt.format(g.impressions)}</span>
            <span class="drill-subrow-num">${(g.ctr || 0).toLocaleString('es-ES', { maximumFractionDigits: 2 })}%</span>
            <span class="drill-subrow-num">${g.clicks > 0 ? fmtEur.format(g.cpc) + ' €' : '-'}</span>
            <span class="drill-subrow-num">${g.conversions > 0 ? fmtInt.format(Math.round(g.conversions)) : '-'}</span>
            <span class="drill-subrow-num">${g.roas > 0 ? g.roas.toLocaleString('es-ES', {minimumFractionDigits:2, maximumFractionDigits:2})+'x' : '-'}</span>
        `,
        getName: (g) => g.ad_group_name,
        getStatus: (g) => g.ad_group_status,
    },
    meta: {
        fetcher: fetchMetaAdSets,
        cacheKey: 'metaAdSetsByCountry',
        expandedKey: 'metaExpandedCountries',
        payloadKey: 'ad_sets',
        activeStatus: 'ACTIVE',
        loadingLabel: 'Cargando ad sets...',
        emptyLabel: 'No hay ad sets con datos en este periodo. (Ejecuta sync de Meta para poblar la tabla.)',
        headerCells: ['Ad set / Campaña', 'Pres./día', 'Coste', 'Clicks', 'Impr.', 'CTR', 'CPC', 'Alcance'],
        renderRow: (g) => `
            <span class="drill-subrow-num">${g.daily_budget > 0 ? fmtEur.format(g.daily_budget) + ' €' : '-'}</span>
            <span class="drill-subrow-num">${fmtEur.format(g.cost)} €</span>
            <span class="drill-subrow-num">${fmtInt.format(g.clicks)}</span>
            <span class="drill-subrow-num">${fmtInt.format(g.impressions)}</span>
            <span class="drill-subrow-num">${(g.ctr || 0).toLocaleString('es-ES', { maximumFractionDigits: 2 })}%</span>
            <span class="drill-subrow-num">${g.clicks > 0 ? fmtEur.format(g.cpc) + ' €' : '-'}</span>
            <span class="drill-subrow-num">${fmtInt.format(g.reach || 0)}</span>
        `,
        getName: (g) => g.ad_set_name,
        getStatus: (g) => g.ad_set_status,
    },
};

function attachDrillDown(kind, tbody) {
    const cfg = DRILL_CFG[kind];
    if (!cfg) return;
    tbody.querySelectorAll('tr.drill-row[data-drill-country]').forEach(tr => {
        tr.addEventListener('click', () => toggleDrillDown(kind, tr));
        // Re-render expansiones previas si el pais sigue expandido
        const c = tr.dataset.drillCountry;
        if (state[cfg.expandedKey].has(c)) {
            const cached = state[cfg.cacheKey][c];
            if (cached) insertDrillSubRows(kind, tr, c, cached);
        }
    });
}

async function toggleDrillDown(kind, tr) {
    const cfg = DRILL_CFG[kind];
    const c = tr.dataset.drillCountry;
    const expandedSet = state[cfg.expandedKey];
    const cache = state[cfg.cacheKey];
    const expanded = expandedSet.has(c);
    const chev = tr.querySelector('.drill-chevron');
    if (expanded) {
        // Colapsar
        expandedSet.delete(c);
        if (chev) chev.classList.remove('open');
        removeDrillSubRows(tr);
        return;
    }
    // Expandir: marcar + fetch si no esta en cache + insertar sub-filas
    expandedSet.add(c);
    if (chev) chev.classList.add('open');
    let items = cache[c];
    if (!items) {
        insertDrillLoading(kind, tr, cfg.loadingLabel);
        try {
            const resp = await cfg.fetcher(c);
            items = resp[cfg.payloadKey] || [];
            cache[c] = items;
        } catch (e) {
            removeDrillSubRows(tr);
            toast('Error cargando drill-down: ' + e.message, 'error');
            expandedSet.delete(c);
            if (chev) chev.classList.remove('open');
            return;
        }
        removeDrillSubRows(tr);
    }
    insertDrillSubRows(kind, tr, c, items);
}

function insertDrillLoading(kind, tr, label) {
    const loadingTr = document.createElement('tr');
    loadingTr.className = 'drill-subrow drill-subrow-loading';
    loadingTr.dataset.drillParent = tr.dataset.drillCountry;
    loadingTr.innerHTML = `<td colspan="${drillColspan(kind)}" style="text-align:center;color:#64748b;padding:14px;">${escapeHtml(label)}</td>`;
    tr.after(loadingTr);
}

function removeDrillSubRows(tr) {
    const c = tr.dataset.drillCountry;
    let next = tr.nextElementSibling;
    while (next && next.classList && next.classList.contains('drill-subrow') && next.dataset.drillParent === c) {
        const toRemove = next;
        next = next.nextElementSibling;
        toRemove.remove();
    }
}

function insertDrillSubRows(kind, tr, country, items) {
    const cfg = DRILL_CFG[kind];
    if (!items || !items.length) {
        const emptyTr = document.createElement('tr');
        emptyTr.className = 'drill-subrow drill-subrow-empty';
        emptyTr.dataset.drillParent = country;
        emptyTr.innerHTML = `<td colspan="${drillColspan(kind)}" style="text-align:center;color:#64748b;padding:14px;">${escapeHtml(cfg.emptyLabel)}</td>`;
        tr.after(emptyTr);
        return;
    }
    // Header de sub-tabla
    const headerTr = document.createElement('tr');
    headerTr.className = 'drill-subrow drill-subhead';
    headerTr.dataset.drillParent = country;
    const headerCellsHtml = cfg.headerCells.map((h, i) =>
        `<span class="${i === 0 ? 'drill-subhead-label' : 'drill-subhead-num'}">${escapeHtml(h)}</span>`
    ).join('');
    headerTr.innerHTML = `
        <td colspan="${drillColspan(kind)}">
            <div class="drill-subhead-grid">${headerCellsHtml}</div>
        </td>
    `;
    tr.after(headerTr);

    // Sub-filas con datos (orden ya viene por coste desc del backend)
    let prev = headerTr;
    items.forEach(g => {
        const subTr = document.createElement('tr');
        subTr.className = 'drill-subrow';
        subTr.dataset.drillParent = country;
        const statusCls = cfg.getStatus(g) === cfg.activeStatus ? '' : 'drill-paused';
        const name = cfg.getName(g) || '(sin nombre)';
        subTr.innerHTML = `
            <td colspan="${drillColspan(kind)}">
                <div class="drill-subrow-grid ${statusCls}">
                    <div class="drill-subrow-label">
                        <span class="drill-ag-name" title="${escapeHtml(name)}">${escapeHtml(name)}</span>
                        <span class="drill-camp-name" title="${escapeHtml(g.campaign_name || '')}">${escapeHtml(g.campaign_name || '')}</span>
                    </div>
                    ${cfg.renderRow(g)}
                </div>
            </td>
        `;
        prev.after(subTr);
        prev = subTr;
    });
}

function renderChannelComparison(kind, payload, skipChipsRebuild = false) {
    if (!payload || !payload.countries) return;
    const cfg = channelCfg(kind);
    // Cachear payload para re-render rapido al togglear paises
    state[cfg.stateKeys.payload] = payload;
    const disabledSet = state[cfg.stateKeys.disabledCountries];

    const info = document.getElementById(cfg.ids.info);
    if (info) {
        const granLabel = payload.granularity === 'monthly' ? 'meses' : payload.granularity === 'weekly' ? 'semanas' : 'días';
        const visibles = payload.countries.filter(c => !disabledSet.has(c)).length;
        info.textContent = `${payload.periods.length} ${granLabel} · ${payload.since} a ${payload.until} · ${visibles}/${payload.countries.length} países`;
    }

    if (!skipChipsRebuild) renderChannelCountryChips(kind, payload);
    else {
        // Solo actualizar clases (sin re-construir DOM)
        document.querySelectorAll(`#${cfg.ids.chips} .country-chip`).forEach(chip => {
            chip.classList.toggle('disabled', disabledSet.has(chip.dataset.country));
        });
    }

    const charts = channelCharts[kind];
    if (charts.cost) charts.cost.destroy();
    if (charts.cpc)  charts.cpc.destroy();
    if (charts.ctr)  charts.ctr.destroy();

    const fmtEurFn  = (v) => fmtEur.format(v || 0) + ' €';
    const fmtCpcFn  = (v) => fmtEur.format(v || 0) + ' €';
    const fmtCtrFn  = (v) => (v || 0).toLocaleString('es-ES', { maximumFractionDigits: 2 }) + '%';
    const fmtIntFn  = (v) => fmtInt.format(v || 0);

    charts.cost = buildChannelChart(kind, cfg.ids.chartCost, payload, 'cost', 'EUR', fmtEurFn, 'bar');
    if (kind === 'meta') {
        // En Meta los charts 2 y 3 son Leads (HubSpot) y CPL en lugar de CPC/CTR.
        // Reutilizamos los mismos canvas IDs (chart-meta-cpc / chart-meta-ctr).
        charts.cpc = buildChannelChart(kind, cfg.ids.chartCpc, payload, 'leads', 'Leads',      fmtIntFn, 'bar');
        charts.ctr = buildChannelChart(kind, cfg.ids.chartCtr, payload, 'cpl',   'EUR / lead', fmtCpcFn, 'line');
    } else {
        charts.cpc = buildChannelChart(kind, cfg.ids.chartCpc, payload, 'cpc', 'EUR / click', fmtCpcFn, 'line');
        charts.ctr = buildChannelChart(kind, cfg.ids.chartCtr, payload, 'ctr', '%',           fmtCtrFn, 'line');
    }

    // Tabla "tipo Excel" por periodos (debajo de los charts)
    renderChannelDetailTable(kind, payload);

    // Tabla de totales con ordenacion segun state[kindSortBy/SortDir]
    const tbody = document.querySelector(`#${cfg.ids.tableTotals} tbody`);
    const sortKey = state[cfg.stateKeys.sortBy];
    const dir = state[cfg.stateKeys.sortDir] === 'asc' ? 1 : -1;
    const sorted = [...payload.countries].sort((a, b) => {
        let va, vb;
        if (sortKey === 'country') {
            va = a; vb = b;
        } else {
            va = payload.totals[a] ? payload.totals[a][sortKey] : null;
            vb = payload.totals[b] ? payload.totals[b][sortKey] : null;
        }
        // null/undefined siempre al final (independiente de direccion)
        if (va == null && vb == null) return 0;
        if (va == null) return 1;
        if (vb == null) return -1;
        if (typeof va === 'string') return dir * va.localeCompare(vb);
        return dir * (va - vb);
    });

    // Marcar columna ordenada en el thead
    document.querySelectorAll(`#${cfg.ids.tableTotals} thead th[data-sort]`).forEach(th => {
        th.classList.remove('sort-asc', 'sort-desc');
        if (th.dataset.sort === sortKey) {
            th.classList.add(state[cfg.stateKeys.sortDir] === 'asc' ? 'sort-asc' : 'sort-desc');
        }
    });
    tbody.innerHTML = sorted.map(c => {
        const t = payload.totals[c];
        // Render utilizacion como barra visual con color segun nivel
        const util = t.utilization_pct;
        let utilCell;
        if (util === null || util === undefined) {
            utilCell = '<span class="empty" title="No hay campañas ENABLED con presupuesto">-</span>';
        } else {
            const cls = util >= 95 ? 'util-full'
                      : util >= 70 ? 'util-good'
                      : util >= 40 ? 'util-low'
                      : 'util-critical';
            const widthPct = Math.min(util, 100);
            utilCell = `
                <div class="util-cell">
                    <div class="util-bar"><div class="util-fill ${cls}" style="width:${widthPct}%;"></div></div>
                    <span class="util-pct">${util.toLocaleString('es-ES', {maximumFractionDigits: 1})}%</span>
                </div>
            `;
        }
        const budgetDay = t.daily_budget > 0 ? fmtEur.format(t.daily_budget) + ' €' : '<span class="empty">-</span>';
        const budgetPer = t.budget_period ? fmtEur.format(t.budget_period) + ' €' : '<span class="empty">-</span>';
        const d = t.deltas || {};
        // En Search/Meta: la fila es clickable y muestra un chevron para drill-down
        // (Search -> ad groups, Meta -> ad sets). Shopping no tiene drill-down.
        const drillable = kind === 'search' || kind === 'meta';
        const expandedKey = kind === 'meta' ? 'metaExpandedCountries' : 'searchExpandedCountries';
        const expanded = drillable && state[expandedKey] && state[expandedKey].has(c);
        const chevron = drillable ? `<span class="drill-chevron ${expanded ? 'open' : ''}">&#9656;</span>` : '';
        const rowCls = drillable ? 'drill-row' : '';
        const rowAttrs = drillable ? ` data-drill-country="${escapeHtml(c)}"` : '';
        // Celdas extra solo para Meta: Leads (HubSpot) + CPL.
        const metaCells = kind === 'meta' ? `
                <td class="td-num">${fmtInt.format(t.leads || 0)}${deltaTag(d.leads_pct, 'up-good')}</td>
                <td class="td-num">${t.cpl != null ? fmtEur.format(t.cpl) + ' €' : '<span class="empty">-</span>'}${deltaTag(d.cpl_pct, 'down-good')}</td>
        ` : '';
        return `
            <tr class="${rowCls}"${rowAttrs}>
                <td>${chevron}${flagImg(c)}<span style="color:${colorForCountry(c)};font-weight:600;">●</span> ${escapeHtml(c)}</td>
                <td class="td-num">${budgetDay}${deltaTag(d.daily_budget_pct, 'neutral')}</td>
                <td class="td-num">${fmtEur.format(t.cost)} €${deltaTag(d.cost_pct, 'neutral')}</td>
                <td class="td-num">${budgetPer}${deltaTag(d.budget_period_pct, 'neutral')}</td>
                <td class="td-num">${utilCell}${deltaTag(d.utilization_pct_pct, 'up-good')}</td>
                <td class="td-num">${fmtInt.format(t.clicks)}${deltaTag(d.clicks_pct, 'up-good')}</td>
                <td class="td-num">${fmtInt.format(t.impressions)}${deltaTag(d.impressions_pct, 'up-good')}</td>
                <td class="td-num">${(t.ctr || 0).toLocaleString('es-ES', { maximumFractionDigits: 2 })}%${deltaTag(d.ctr_pct, 'up-good')}</td>
                <td class="td-num">${fmtEur.format(t.cpc)} €${deltaTag(d.cpc_pct, 'down-good')}</td>${metaCells}
            </tr>
        `;
    }).join('');

    // En Search/Meta: enganchar click handlers para drill-down + re-render expansiones cacheadas
    if (kind === 'search' || kind === 'meta') {
        attachDrillDown(kind, tbody);
    }

    // Fila de totales (sumas de columnas absolutas, ratios recalculados desde sumas)
    const tfoot = document.querySelector(`#${cfg.ids.tableTotals} tfoot`);
    const sums = sorted.reduce((acc, c) => {
        const t = payload.totals[c] || {};
        acc.cost += t.cost || 0;
        acc.daily_budget += t.daily_budget || 0;
        acc.budget_period += t.budget_period || 0;
        acc.clicks += t.clicks || 0;
        acc.impressions += t.impressions || 0;
        acc.leads += t.leads || 0;
        return acc;
    }, { cost: 0, daily_budget: 0, budget_period: 0, clicks: 0, impressions: 0, leads: 0 });
    const totCtr = sums.impressions > 0 ? (sums.clicks / sums.impressions * 100) : 0;
    const totCpc = sums.clicks > 0 ? (sums.cost / sums.clicks) : 0;
    const totUtil = sums.budget_period > 0 ? (sums.cost / sums.budget_period * 100) : null;

    // Sumas del periodo anterior (mismo calculo pero con totals[c].previous)
    const prevSums = sorted.reduce((acc, c) => {
        const p = (payload.totals[c] || {}).previous || {};
        acc.cost += p.cost || 0;
        acc.daily_budget += p.daily_budget || 0;
        acc.budget_period += p.budget_period || 0;
        acc.clicks += p.clicks || 0;
        acc.impressions += p.impressions || 0;
        acc.leads += p.leads || 0;
        return acc;
    }, { cost: 0, daily_budget: 0, budget_period: 0, clicks: 0, impressions: 0, leads: 0 });
    const prevCtr = prevSums.impressions > 0 ? (prevSums.clicks / prevSums.impressions * 100) : 0;
    const prevCpc = prevSums.clicks > 0 ? (prevSums.cost / prevSums.clicks) : 0;
    const prevUtil = prevSums.budget_period > 0 ? (prevSums.cost / prevSums.budget_period * 100) : null;

    const _dpct = (cur, prev) => (prev === null || prev === undefined || prev === 0) ? null : Math.round((cur - prev) / prev * 1000) / 10;
    // CPL = cost / leads (re-calculado desde sumas).
    const totCpl = sums.leads > 0 ? (sums.cost / sums.leads) : null;
    const prevCpl = prevSums.leads > 0 ? (prevSums.cost / prevSums.leads) : null;
    const dT = {
        cost: _dpct(sums.cost, prevSums.cost),
        daily_budget: _dpct(sums.daily_budget, prevSums.daily_budget),
        budget_period: _dpct(sums.budget_period, prevSums.budget_period),
        clicks: _dpct(sums.clicks, prevSums.clicks),
        impressions: _dpct(sums.impressions, prevSums.impressions),
        ctr: _dpct(totCtr, prevCtr),
        cpc: _dpct(totCpc, prevCpc),
        util: prevUtil !== null && totUtil !== null ? _dpct(totUtil, prevUtil) : null,
        leads: _dpct(sums.leads, prevSums.leads),
        cpl: (totCpl !== null && prevCpl !== null) ? _dpct(totCpl, prevCpl) : null,
    };

    let utilTot;
    if (totUtil === null) {
        utilTot = '<span class="empty">-</span>';
    } else {
        const cls = totUtil >= 95 ? 'util-full'
                  : totUtil >= 70 ? 'util-good'
                  : totUtil >= 40 ? 'util-low'
                  : 'util-critical';
        const widthPct = Math.min(totUtil, 100);
        utilTot = `
            <div class="util-cell">
                <div class="util-bar"><div class="util-fill ${cls}" style="width:${widthPct}%;"></div></div>
                <span class="util-pct">${totUtil.toLocaleString('es-ES', {maximumFractionDigits: 1})}%</span>
            </div>
        `;
    }
    const budgetDayTot = sums.daily_budget > 0 ? fmtEur.format(sums.daily_budget) + ' €' : '<span class="empty">-</span>';
    const budgetPerTot = sums.budget_period > 0 ? fmtEur.format(sums.budget_period) + ' €' : '<span class="empty">-</span>';
    // Celdas extra para tfoot Meta
    const metaCellsTot = kind === 'meta' ? `
            <td class="td-num">${fmtInt.format(sums.leads)}${deltaTag(dT.leads, 'up-good')}</td>
            <td class="td-num">${totCpl != null ? fmtEur.format(totCpl) + ' €' : '<span class="empty">-</span>'}${deltaTag(dT.cpl, 'down-good')}</td>
    ` : '';
    tfoot.innerHTML = `
        <tr>
            <td>Total (${sorted.length} países)</td>
            <td class="td-num">${budgetDayTot}${deltaTag(dT.daily_budget, 'neutral')}</td>
            <td class="td-num">${fmtEur.format(sums.cost)} €${deltaTag(dT.cost, 'neutral')}</td>
            <td class="td-num">${budgetPerTot}${deltaTag(dT.budget_period, 'neutral')}</td>
            <td class="td-num">${utilTot}${deltaTag(dT.util, 'up-good')}</td>
            <td class="td-num">${fmtInt.format(sums.clicks)}${deltaTag(dT.clicks, 'up-good')}</td>
            <td class="td-num">${fmtInt.format(sums.impressions)}${deltaTag(dT.impressions, 'up-good')}</td>
            <td class="td-num">${totCtr.toLocaleString('es-ES', { maximumFractionDigits: 2 })}%${deltaTag(dT.ctr, 'up-good')}</td>
            <td class="td-num">${sums.clicks > 0 ? fmtEur.format(totCpc) + ' €' : '<span class="empty">-</span>'}${deltaTag(dT.cpc, 'down-good')}</td>${metaCellsTot}
        </tr>
    `;
}

// === Weekly table render ===
function fmtCell(value, format) {
    if (value === 0 || value === null || value === undefined) return '<span class="empty">-</span>';
    if (format === 'eur') return fmtEur.format(value) + ' €';
    if (format === 'eur3') return fmtEur3.format(value) + ' €';
    if (format === 'pct') return value.toLocaleString('es-ES', {minimumFractionDigits:1, maximumFractionDigits:1}) + '%';
    if (format === 'x') return value.toLocaleString('es-ES', {minimumFractionDigits:2, maximumFractionDigits:2}) + 'x';
    return fmtInt.format(value);
}

function buildYearGroups(periods) {
    // Devuelve [{year, colspan}, ...] agrupando consecutivos del mismo ano.
    const groups = [];
    let cur = null;
    periods.forEach(p => {
        const year = (p.key || '').substring(0, 4);
        if (cur && cur.year === year) cur.colspan += 1;
        else { if (cur) groups.push(cur); cur = { year, colspan: 1 }; }
    });
    if (cur) groups.push(cur);
    return groups;
}

function renderWeekly(payload) {
    const periods = payload.periods || [];
    const sections = payload.sections || [];
    const yearGroups = buildYearGroups(periods);

    // Cabecera doble (ano arriba + periodo abajo)
    const thead = $('#weekly-table thead');
    let html = '<tr class="th-year-row">';
    html += `<th class="col-label" rowspan="2">Métrica</th>`;
    html += `<th class="col-total" rowspan="2">${escapeHtml(payload.totals_label || 'Acumulado')}</th>`;
    yearGroups.forEach(g => {
        html += `<th class="col-year" colspan="${g.colspan}">${escapeHtml(g.year)}</th>`;
    });
    html += '</tr><tr>';
    periods.forEach(p => {
        html += `<th class="col-period">${escapeHtml(p.label)}</th>`;
    });
    html += '</tr>';
    thead.innerHTML = html;

    // Cuerpo
    const tbody = $('#weekly-table tbody');
    const colspan = 2 + periods.length;
    let bodyHtml = '';

    // Cada fila con by_country tiene un ID estable para que el chevron pueda
    // togglear sub-filas via data-attribute. Usamos seccion+indice de fila.
    sections.forEach((sec, si) => {
        bodyHtml += `<tr class="section-title"><td class="col-label" colspan="${colspan}">${escapeHtml(sec.title)}</td></tr>`;
        sec.rows.forEach((row, ri) => {
            const cls = [];
            if (row.indent) cls.push('row-indent');
            if (row.header) cls.push('row-header');
            const hasDrill = Array.isArray(row.by_country) && row.by_country.length > 0;
            const rowId = `w-${si}-${ri}`;
            if (hasDrill) {
                cls.push('weekly-drill-row');
            }
            const expanded = state.weeklyExpandedRows && state.weeklyExpandedRows.has(rowId);
            if (expanded) cls.push('expanded');
            const labelTooltip = row.note ? ` title="${escapeHtml(row.note)}"` : '';
            const labelExtra = row.note ? ' <span class="note-disabled">(pendiente)</span>' : '';
            const chevron = hasDrill
                ? `<span class="drill-chevron ${expanded ? 'open' : ''}">&#9656;</span>`
                : '';
            const attrs = hasDrill ? ` data-weekly-row="${rowId}"` : '';
            bodyHtml += `<tr class="${cls.join(' ')}"${attrs}>`;
            bodyHtml += `<td class="col-label"${labelTooltip}>${chevron}${escapeHtml(row.label)}${labelExtra}</td>`;
            bodyHtml += `<td class="col-total">${fmtCell(row.total, row.format)}</td>`;
            row.values.forEach(v => {
                bodyHtml += `<td class="col-period">${fmtCell(v, row.format)}</td>`;
            });
            bodyHtml += '</tr>';
            // Sub-filas por pais (si la fila esta expandida en state)
            if (hasDrill && expanded) {
                row.by_country.forEach(bc => {
                    bodyHtml += `<tr class="weekly-subrow" data-weekly-parent="${rowId}">`;
                    bodyHtml += `<td class="col-label weekly-subrow-label">${flagImg(bc.label)}${escapeHtml(bc.label)}</td>`;
                    bodyHtml += `<td class="col-total">${fmtCell(bc.total, row.format)}</td>`;
                    bc.values.forEach(v => {
                        bodyHtml += `<td class="col-period">${fmtCell(v, row.format)}</td>`;
                    });
                    bodyHtml += '</tr>';
                });
            }
        });
    });
    tbody.innerHTML = bodyHtml;

    // Click handler de las filas con drill-down: toggle expansion + re-render
    tbody.querySelectorAll('tr.weekly-drill-row').forEach(tr => {
        tr.addEventListener('click', () => {
            const id = tr.dataset.weeklyRow;
            if (!state.weeklyExpandedRows) state.weeklyExpandedRows = new Set();
            if (state.weeklyExpandedRows.has(id)) state.weeklyExpandedRows.delete(id);
            else state.weeklyExpandedRows.add(id);
            renderWeekly(payload);
        });
    });

    // Refresca estado de botones de scroll tras inyectar contenido
    setTimeout(() => {
        const wrap = document.getElementById('weekly-wrapper');
        if (wrap) wrap.dispatchEvent(new Event('scroll'));
    }, 30);

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

function setupTabs() {
    const tabs = $$('.tab-btn');
    const panes = $$('.tab-pane');

    const activate = (target) => {
        state.activeTab = target;
        tabs.forEach(b => b.classList.toggle('active', b.dataset.tab === target));
        panes.forEach(p => p.classList.toggle('active', p.dataset.tab === target));
        try { localStorage.setItem('dashboard-tab', target); } catch (e) {}
        // Re-filtrar alertas para que solo se vean las del tab actual (Shopping -> solo Shopping)
        renderAlertsFiltered();
        // Re-resize charts del tab activo (Chart.js no calcula bien si el canvas estaba display:none)
        setTimeout(() => {
            [chartTimeseries, chartTopCampaigns,
             channelCharts.resumen.cost,  channelCharts.resumen.leads, channelCharts.resumen.cpl,
             channelCharts.shopping.cost, channelCharts.shopping.cpc,  channelCharts.shopping.ctr,
             channelCharts.search.cost,   channelCharts.search.cpc,    channelCharts.search.ctr,
             channelCharts.meta.cost,     channelCharts.meta.cpc,      channelCharts.meta.ctr]
                .forEach(c => { if (c) try { c.resize(); } catch (e) {} });
        }, 50);
        // Scroll arriba al cambiar
        window.scrollTo({ top: 0, behavior: 'smooth' });
    };

    tabs.forEach(btn => btn.addEventListener('click', () => activate(btn.dataset.tab)));

    // Restaurar ultima pestana usada
    try {
        const saved = localStorage.getItem('dashboard-tab');
        if (saved && $(`.tab-btn[data-tab="${saved}"]`)) activate(saved);
    } catch (e) {}
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

    // Selector de granularidad de la comparativa Search por pais
    $$('.srgran-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            $$('.srgran-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            state.searchGranularity = btn.dataset.srgran;
            loadSearchOnly();
        });
    });

    // Selector de granularidad de los 3 charts del top del Resumen
    $$('.rgran-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            $$('.rgran-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            state.resumenGranularity = btn.dataset.rgran;
            loadResumenComparisonOnly();
        });
    });

    // Toggle "Ocultar parciales" del Resumen
    const hidePartialCb = document.getElementById('resumen-hide-partial');
    if (hidePartialCb) {
        hidePartialCb.checked = state.resumenHidePartial;
        hidePartialCb.addEventListener('change', () => {
            state.resumenHidePartial = hidePartialCb.checked;
            try { localStorage.setItem('resumen-hide-partial', hidePartialCb.checked ? '1' : '0'); } catch (e) {}
            // Re-render sin refetch (los datos no cambian)
            loadResumenComparisonOnly();
        });
    }

    // Selector de granularidad de la comparativa Meta por pais
    $$('.mgran-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            $$('.mgran-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            state.metaGranularity = btn.dataset.mgran;
            loadMetaOnly();
        });
    });

    // Selector de tratamiento de boosted posts en la pestaña Meta
    const boostedSel = document.getElementById('meta-boosted-mode');
    if (boostedSel) {
        boostedSel.value = state.metaBoostedMode;
        boostedSel.addEventListener('change', () => {
            state.metaBoostedMode = boostedSel.value;
            try { localStorage.setItem('meta-boosted-mode', boostedSel.value); } catch (e) {}
            loadMetaOnly();
        });
    }

    setupTableSort();
    setupChannelTableSort('shopping');
    setupChannelTableSort('search');
    setupChannelTableSort('meta');
    setupScrollControls();
    setupStickyHeightTracking();
    setupTabs();
    setupChatbot();
    loadCountrySelector();
    loadAll();
}

document.addEventListener('DOMContentLoaded', init);
