// Dashboard Meta Ads Heroturfs

const state = {
    days: 30,
    granularity: 'daily',     // del grafico de evolucion
    weeklyGranularity: 'weekly', // de la tabla semanal/mensual
    country: '',  // vacio = todos los paises
    campaigns: [],
    sortBy: 'spend',
    sortDir: 'desc',
};

function buildQuery(extra = {}) {
    const params = new URLSearchParams();
    params.set('days', state.days);
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
    // Usamos SVG de flagcdn.com (CDN publico). w40 = 40px width PNG, .svg = vectorial
    const cls = size === 'big' ? 'flag-img flag-big' : 'flag-img';
    return `<img src="https://flagcdn.com/${iso}.svg" class="${cls}" alt="${escapeHtml(country)}" loading="lazy">`;
}

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// === Formatters ===
const fmtInt = new Intl.NumberFormat('es-ES');
const fmtEur = new Intl.NumberFormat('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtEur3 = new Intl.NumberFormat('es-ES', { minimumFractionDigits: 3, maximumFractionDigits: 3 });
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

// === Render KPIs ===
function renderKpis(k) {
    $('#kpi-spend').textContent = fmtEur.format(k.spend);
    $('#kpi-impressions').textContent = fmtInt.format(k.impressions);
    $('#kpi-reach').textContent = fmtInt.format(k.reach);
    $('#kpi-clicks').textContent = fmtInt.format(k.clicks);
    $('#kpi-ctr').textContent = k.ctr.toLocaleString('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    $('#kpi-cpc').textContent = fmtEur3.format(k.cpc);
    $('#kpi-leads').textContent = fmtInt.format(k.leads);
    $('#kpi-cpl').textContent = k.leads > 0 ? fmtEur.format(k.cpl) : '-';

    $('#date-range').textContent = `${formatDateES(k.since)} - ${formatDateES(k.until)} (${k.days} dias)`;
    $('#last-sync').textContent = k.last_sync
        ? `Meta: ${formatDateTimeES(k.last_sync)}`
        : 'Meta: nunca';
}

// === HubSpot rendering ===
function renderHsKpis(k) {
    $('#hs-kpi-contacts').textContent = fmtInt.format(k.contacts_total);
    $('#hs-kpi-deals-won').textContent = fmtInt.format(k.deals_won);
    $('#hs-kpi-revenue').textContent = fmtEur.format(k.revenue_won);
    $('#hs-kpi-revenue-meta').textContent = fmtEur.format(k.revenue_meta);
    $('#hs-kpi-revenue-google').textContent = fmtEur.format(k.revenue_google);

    $('#last-sync-hs').textContent = k.last_sync
        ? `HubSpot: ${formatDateTimeES(k.last_sync)}`
        : 'HubSpot: nunca';
}

function renderHsFunnel(f) {
    // Asignar metricas calculadas a sus KPI cards
    $('#hs-kpi-roas').textContent = f.roas > 0 ? `${f.roas.toLocaleString('es-ES', {minimumFractionDigits:2, maximumFractionDigits:2})}x` : '-';
    $('#hs-kpi-cpl').textContent = f.cpl_real > 0 ? fmtEur.format(f.cpl_real) : '-';
    $('#hs-kpi-cac').textContent = f.cac > 0 ? fmtEur.format(f.cac) : '-';

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
    const idx = ['name', 'status', 'spend', 'impressions', 'clicks', 'ctr', 'cpc', 'leads', 'cpl'].indexOf(state.sortBy);
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
    const cols = ['name', 'status', 'spend', 'impressions', 'clicks', 'ctr', 'cpc', 'leads', 'cpl'];
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
        const [k, ts, cs, hsK, hsF, hsSrc, hsSt, hsCo, wk] = await Promise.all([
            fetchKpis(), fetchTimeseries(), fetchCampaigns(),
            fetchHsKpis(), fetchHsFunnel(), fetchHsBySource(),
            fetchHsByStatus(), fetchHsByCountry(),
            fetchWeekly(),
        ]);
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
    } catch (e) {
        toast('Error cargando datos: ' + e.message, 'error');
    }
}

async function loadWeeklyOnly() {
    try {
        renderWeekly(await fetchWeekly());
    } catch (e) {
        toast('Error cargando tabla semanal: ' + e.message, 'error');
    }
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
const doSyncHs = () => doSyncSource('btn-sync-hs', '/api/hubspot/sync', 'HubSpot', 'HubSpot...');

// === Init ===
function init() {
    // Selector de rango
    $$('.range-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            $$('.range-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            // "all" se pasa tal cual; los numericos se mantienen como string
            state.days = btn.dataset.days;
            // Si pasamos a "Todo" o "12 meses", forzar granularidad mensual por defecto
            if (state.days === 'all' || parseInt(state.days, 10) >= 180) {
                state.granularity = 'monthly';
                $$('.gran-btn').forEach(b => b.classList.toggle('active', b.dataset.gran === 'monthly'));
            }
            loadAll();
        });
    });

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

    setupTableSort();
    loadCountrySelector();
    loadAll();
}

document.addEventListener('DOMContentLoaded', init);
