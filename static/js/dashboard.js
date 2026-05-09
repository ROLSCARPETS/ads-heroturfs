// Dashboard Meta Ads Heroturfs

const state = {
    days: 30,
    campaigns: [],
    sortBy: 'spend',
    sortDir: 'desc',
};

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
async function fetchKpis(days) {
    const r = await fetch(`/api/kpis?days=${days}`);
    if (!r.ok) throw new Error('KPIs API error');
    return r.json();
}
async function fetchTimeseries(days) {
    const r = await fetch(`/api/timeseries?days=${days}`);
    if (!r.ok) throw new Error('Timeseries API error');
    return r.json();
}
async function fetchCampaigns(days) {
    const r = await fetch(`/api/campaigns?days=${days}`);
    if (!r.ok) throw new Error('Campaigns API error');
    return r.json();
}

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
        ? `Ultima sincronizacion: ${formatDateTimeES(k.last_sync)}`
        : 'Nunca sincronizado';
}

function formatDateES(iso) {
    if (!iso) return '-';
    const [y, m, d] = iso.substring(0, 10).split('-');
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

function renderTimeseries(data) {
    const labels = data.map(d => formatDateES(d.date));
    const spend = data.map(d => d.spend);
    const leads = data.map(d => d.leads);

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
        const [k, ts, cs] = await Promise.all([
            fetchKpis(state.days),
            fetchTimeseries(state.days),
            fetchCampaigns(state.days),
        ]);
        renderKpis(k);
        renderTimeseries(ts);
        state.campaigns = cs;
        renderTopCampaigns(cs);
        renderTable();
    } catch (e) {
        toast('Error cargando datos: ' + e.message, 'error');
    }
}

// === Sync ===
async function doSync() {
    const btn = $('#btn-sync');
    btn.classList.add('syncing');
    btn.disabled = true;
    $('.sync-label', btn).textContent = 'Sincronizando...';
    try {
        const r = await fetch('/api/sync', { method: 'POST' });
        const data = await r.json();
        if (data.status === 'ok') {
            toast('Sincronizacion completada', 'success');
            await loadAll();
        } else {
            toast('Error: ' + (data.error || 'desconocido'), 'error');
        }
    } catch (e) {
        toast('Error de red: ' + e.message, 'error');
    } finally {
        btn.classList.remove('syncing');
        btn.disabled = false;
        $('.sync-label', btn).textContent = 'Sincronizar';
    }
}

// === Init ===
function init() {
    // Selector de rango
    $$('.range-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            $$('.range-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            state.days = parseInt(btn.dataset.days, 10);
            loadAll();
        });
    });

    $('#btn-sync').addEventListener('click', doSync);
    $('#btn-export').addEventListener('click', exportCsv);

    setupTableSort();
    loadAll();
}

document.addEventListener('DOMContentLoaded', init);
