/* Request log view: summary strip, filters, paging, retention and the per-request time breakdown.
 * manage.html keeps the table and the detail modal; this file supplies what goes around and into them.
 * Nothing touches the DOM until LogsView.fetchPage() runs, so the script can load before the page is parsed. */
(() => {
    'use strict';
    const SUMMARY_MAX_AGE_MS = 30000;
    const AUTO_REFRESH_MS = 5000;
    const SEARCH_DEBOUNCE_MS = 350;
    const RANGES = [[1, 'logs.range1h'], [6, 'logs.range6h'], [24, 'logs.range24h'], [168, 'logs.range7d'], [720, 'logs.range30d'], [0, 'logs.rangeAll']];
    const PAGE_SIZES = [25, 50, 100, 200];
    const STAGE_COLORS = ['#7cb3ff', '#6ee7b7', '#fbbf24', '#b79cff', '#ff8585', '#5eead4', '#f9a8d4', '#a3e635', '#fdba74', '#93c5fd'];

    const state = {
        hours: 24, status: '', token: '', model: '', key: '', q: '', limit: 50, offset: 0, total: 0,
        summary: null, summaryAt: 0, summaryDirty: true, auto: false, timer: null, searchTimer: null, mounted: false,
    };

    const byId = (id) => document.getElementById(id);
    // Catalog keys that take values end with their parameter names, e.g. "logs.p95 {value}".
    const t = (key, params) => I18n.t(params ? key + ' ' + Object.keys(params).map((name) => `{${name}}`).join(' ') : key, params);
    const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[ch]));

    // Log timestamps are UTC without a zone ("2026-11-26 16:51:42"); say so, or the browser reads them as local time.
    function date(value) {
        if (!value) return null;
        const parsed = new Date(String(value).replace(' ', 'T') + (/[zZ]|[+-]\d\d:?\d\d$/.test(String(value)) ? '' : 'Z'));
        return Number.isNaN(parsed.getTime()) ? null : parsed;
    }
    const time = (value) => { const moment = date(value); return moment ? moment.toLocaleString(I18n.locale) : '-'; };
    const seconds = (value) => (value === null || value === undefined) ? '-' : (value < 10 ? value.toFixed(1) : Math.round(value)) + ' s';
    const percent = (value) => (value === null || value === undefined) ? '-' : (Math.round(value * 1000) / 10) + '%';
    const millis = (value) => value >= 1000 ? (value / 1000).toFixed(1) + ' s' : value + ' ms';

    const STYLE = `
.logs-summary{padding:16px 18px;border-bottom:1px solid var(--c-line)}
.logs-cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr)) minmax(0,1.6fr);gap:0}
.logs-card{padding:0 18px;border-right:1px solid var(--c-line);min-width:0}
.logs-card:first-child{padding-left:0}.logs-card:last-child{border-right:0;padding-right:0}
.logs-card-label{font-size:12px;color:var(--c-muted);margin:0 0 6px}
.logs-card-value{font-size:22px;line-height:1.2;letter-spacing:-.02em;margin:0;font-variant-numeric:tabular-nums}
.logs-card-note{font-size:12px;color:var(--c-muted);margin:4px 0 0}
.logs-bars{display:flex;align-items:flex-end;gap:2px;height:44px}
.logs-bar{flex:1;min-width:2px;display:flex;flex-direction:column;justify-content:flex-end;background:rgba(124,179,255,.1);border-radius:2px 2px 0 0;height:100%}
.logs-bar>i{display:block;background:var(--c-info);border-radius:2px 2px 0 0;min-height:1px}
.logs-bar>b{display:block;background:var(--c-danger)}
.logs-breakdown{margin-top:14px}
.logs-breakdown>summary{cursor:pointer;font-size:13px;color:var(--c-muted)}
.logs-breakdown-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px;margin-top:12px}
.logs-mini{width:100%;border-collapse:collapse;font-size:12px}
.logs-mini caption{text-align:left;font-weight:600;font-size:12px;color:var(--c-text);padding-bottom:6px}
.logs-mini th,.logs-mini td{padding:4px 6px 4px 0;text-align:left;border-bottom:1px solid var(--c-line);font-weight:400;white-space:nowrap}
.logs-mini td:first-child{max-width:14rem;overflow:hidden;text-overflow:ellipsis}
.logs-mini td+td,.logs-mini th+th{text-align:right;padding-right:0;padding-left:10px;font-variant-numeric:tabular-nums}
.logs-filters{display:flex;flex-wrap:wrap;align-items:flex-end;gap:10px 12px;padding:12px 18px;border-bottom:1px solid var(--c-line)}
.logs-field{display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--c-muted)}
.logs-field select,.logs-field input[type=search],.logs-field input[type=number]{height:34px;min-width:8rem;max-width:16rem;border-radius:8px;border:1px solid var(--c-line-strong);background:var(--c-raised);color:var(--c-text);padding:0 10px;font-size:13px}
.logs-field input[type=search]{min-width:13rem}
.logs-field input[type=number]{min-width:0;width:6rem}
.logs-field select:focus-visible,.logs-field input:focus-visible{outline:2px solid var(--c-accent);outline-offset:1px}
.logs-check{display:flex;align-items:center;gap:6px;font-size:13px;height:34px;color:var(--c-text)}
.logs-footer{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:10px 18px;padding:12px 18px;border-top:1px solid var(--c-line);font-size:13px;color:var(--c-muted)}
.logs-pager,.logs-retention{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.logs-retention-status{font-size:12px}
.logs-model{display:flex;flex-direction:column;gap:2px;width:12rem;max-width:12rem}
.instrument-log-sheet .w-\\[17rem\\]{width:12rem!important;max-width:12rem!important}
#panelLogs table th,#panelLogs table td{padding-left:8px;padding-right:8px}
#logsTableBody td:nth-child(4),#logsTableBody td:nth-child(9),#logsTableBody td:nth-child(10){white-space:nowrap}
#panelLogs table th:last-child,#panelLogs table td:last-child{position:sticky;right:0;background:var(--c-surface);box-shadow:-8px 0 8px -8px rgba(0,0,0,.6)}
.logs-model-id{font-size:12px;font-family:var(--c-mono);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.logs-prompt{font-size:12px;color:var(--c-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.logs-meta{font-size:11px;color:var(--c-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.logs-job{font-family:var(--c-mono);color:var(--c-muted)}
.logs-detail-grid{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;font-size:13px}
.logs-detail-grid dt{color:var(--c-muted)}.logs-detail-grid dd{margin:0;word-break:break-all}
.logs-timeline{display:flex;height:14px;border-radius:7px;overflow:hidden;background:var(--c-line)}
.logs-timeline>span{display:block;min-width:2px}
.logs-stages{width:100%;border-collapse:collapse;font-size:13px;margin-top:10px}
.logs-stages td{padding:4px 0;border-bottom:1px solid var(--c-line)}
.logs-stages td+td{text-align:right;font-variant-numeric:tabular-nums;padding-left:12px;white-space:nowrap}
.logs-swatch{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:8px}
@media (max-width:900px){.logs-cards{grid-template-columns:repeat(2,minmax(0,1fr));row-gap:16px}.logs-card{padding:0 12px 0 0;border-right:0}.logs-breakdown-grid{grid-template-columns:1fr}}
`;

    function option(value, label, selected) {
        return `<option value="${esc(value)}"${String(value) === String(selected) ? ' selected' : ''}>${label}</option>`;
    }

    function mount() {
        if (state.mounted) return;
        const summaryBox = byId('logsSummary');
        const filterBox = byId('logsFilters');
        const footerBox = byId('logsFooter');
        if (!summaryBox || !filterBox || !footerBox) return;
        state.mounted = true;
        const style = document.createElement('style');
        style.textContent = STYLE;
        document.head.appendChild(style);

        filterBox.innerHTML = `
            <label class="logs-field"><span data-i18n="logs.range">Time range</span>
                <select id="logsRange">${RANGES.map(([hours, key]) => `<option value="${hours}" data-i18n="${key}"${hours === state.hours ? ' selected' : ''}></option>`).join('')}</select></label>
            <label class="logs-field"><span data-i18n="logs.status">Status</span>
                <select id="logsStatus">${['', 'success', 'failed', 'running'].map((value) => `<option value="${value}" data-i18n="logs.status.${value || 'all'}"></option>`).join('')}</select></label>
            <label class="logs-field"><span data-i18n="logs.account">Account</span><select id="logsAccount"></select></label>
            <label class="logs-field"><span data-i18n="logs.model">Model</span><select id="logsModel"></select></label>
            <label class="logs-field"><span data-i18n="logs.key">Client key</span><select id="logsKey"></select></label>
            <label class="logs-field"><span data-i18n="logs.search">Search</span>
                <input id="logsSearch" type="search" autocomplete="off" spellcheck="false" data-i18n-placeholder="logs.searchPlaceholder" placeholder="Prompt, model, job id, error"></label>
            <button type="button" id="logsReset" data-i18n="logs.reset">Reset filters</button>
            <label class="logs-check"><input id="logsAuto" type="checkbox"><span data-i18n="logs.auto">Refresh every 5 s</span></label>`;
        footerBox.innerHTML = `
            <div class="logs-pager">
                <span id="logsShowing" aria-live="polite"></span>
                <button type="button" id="logsPrev" data-i18n="logs.prev">Previous</button>
                <button type="button" id="logsNext" data-i18n="logs.next">Next</button>
                <label class="logs-field" style="flex-direction:row;align-items:center"><span data-i18n="logs.pageSize">Rows per page</span>
                    <select id="logsPageSize">${PAGE_SIZES.map((size) => option(size, size, state.limit)).join('')}</select></label>
            </div>
            <div class="logs-retention">
                <label class="logs-field" style="flex-direction:row;align-items:center"><span data-i18n="logs.retention">Keep logs for (days, 0 = forever)</span>
                    <input id="logsRetentionDays" type="number" min="0" max="3650" step="1" value="0" inputmode="numeric"></label>
                <button type="button" id="logsRetentionSave" data-i18n="logs.retentionSave">Save</button>
                <span id="logsRetentionStatus" class="logs-retention-status" aria-live="polite"></span>
            </div>`;
        I18n.apply(filterBox);
        I18n.apply(footerBox);
        renderFacets();

        const change = (id, key, numeric) => byId(id).addEventListener('change', (event) => {
            state[key] = event.target.value;
            if (numeric) state[key] = Number(state[key]);
            state.offset = 0;
            if (key === 'hours') state.summaryDirty = true;
            reload();
        });
        change('logsRange', 'hours', true);
        change('logsStatus', 'status');
        change('logsAccount', 'token');
        change('logsModel', 'model');
        change('logsKey', 'key');
        byId('logsPageSize').addEventListener('change', (event) => { state.limit = Number(event.target.value); state.offset = 0; reload(); });
        byId('logsSearch').addEventListener('input', (event) => {
            clearTimeout(state.searchTimer);
            state.searchTimer = setTimeout(() => { state.q = event.target.value.trim(); state.offset = 0; reload(); }, SEARCH_DEBOUNCE_MS);
        });
        byId('logsReset').addEventListener('click', () => {
            Object.assign(state, {status: '', token: '', model: '', key: '', q: '', offset: 0});
            byId('logsStatus').value = '';
            byId('logsSearch').value = '';
            renderFacets();
            reload();
        });
        byId('logsPrev').addEventListener('click', () => { state.offset = Math.max(0, state.offset - state.limit); reload(); });
        byId('logsNext').addEventListener('click', () => { state.offset += state.limit; reload(); });
        byId('logsAuto').addEventListener('change', (event) => setAuto(event.target.checked));
        byId('logsRetentionSave').addEventListener('click', saveRetention);
        loadRetention();
        window.addEventListener('languagechange', () => { renderSummary(); renderFacets(); renderPager(); });
    }

    const reload = () => { if (typeof window.loadLogs === 'function') window.loadLogs(); };

    function setAuto(on) {
        state.auto = on;
        clearInterval(state.timer);
        state.timer = null;
        if (!on) return;
        state.timer = setInterval(() => {
            const panel = byId('panelLogs');
            if (document.hidden || !panel || panel.classList.contains('hidden')) return;
            window.loadLogs({silent: true});
        }, AUTO_REFRESH_MS);
    }

    // ---- list ----

    // manage.html hands over its authenticated request function; it is not a global yet when the tab opens from the URL hash.
    let request = null;

    async function fetchPage(api) {
        request = api;
        mount();
        const params = new URLSearchParams({limit: state.limit, offset: state.offset});
        if (state.hours) params.set('hours', state.hours);
        for (const [name, value] of [['status', state.status], ['token_id', state.token], ['model', state.model], ['client_key_id', state.key], ['q', state.q]]) {
            if (value) params.set(name, value);
        }
        const response = await request('/api/logs?' + params);
        if (!response) return null;
        const logs = await response.json();
        const header = Number(response.headers.get('X-Total-Count'));
        state.total = Number.isFinite(header) && response.headers.has('X-Total-Count') ? header : state.offset + logs.length;
        if (!logs.length && state.offset > 0 && state.total > 0) {
            // The page we were on is past the end (logs were deleted); go to the last page.
            state.offset = Math.floor((state.total - 1) / state.limit) * state.limit;
            return fetchPage();
        }
        renderPager();
        if (state.summaryDirty || Date.now() - state.summaryAt > SUMMARY_MAX_AGE_MS) refreshSummary();
        return logs;
    }

    function renderPager() {
        const label = byId('logsShowing');
        if (!label) return;
        const from = state.total ? state.offset + 1 : 0;
        const to = Math.min(state.total, state.offset + state.limit);
        label.textContent = t('logs.showing', {from, to, total: state.total});
        byId('logsPrev').disabled = state.offset <= 0;
        byId('logsNext').disabled = state.offset + state.limit >= state.total;
    }

    // ---- summary ----

    async function refreshSummary() {
        state.summaryDirty = false;
        state.summaryAt = Date.now();
        try {
            const response = await request('/api/logs/summary?hours=' + state.hours);
            if (!response || !response.ok) return;
            const data = await response.json();
            if (!Array.isArray(data.buckets) || !data.duration || !data.upload_cache) return;
            state.summary = data;
            renderSummary();
            renderFacets();
        } catch (error) {
            console.error('log summary failed:', error);
        }
    }

    function renderSummary() {
        const box = byId('logsSummary');
        const s = state.summary;
        if (!box || !s) return;
        const maxRequests = Math.max(1, ...s.buckets.map((slot) => slot.requests));
        const bars = s.buckets.map((slot) => {
            const when = date(slot.start);
            const title = `${when ? when.toLocaleString(I18n.locale) : slot.start} - ${t('logs.barTitle', {requests: slot.requests, failed: slot.failed})}`;
            const height = slot.requests / maxRequests * 100;
            const failed = slot.requests ? slot.failed / slot.requests * 100 : 0;
            return `<div class="logs-bar" title="${esc(title)}"><i style="height:${height}%"><b style="height:${failed}%"></b></i></div>`;
        }).join('');
        const cache = s.upload_cache;
        box.innerHTML = `
            <div class="logs-cards">
                <div class="logs-card"><p class="logs-card-label">${t('logs.requests')}</p><p class="logs-card-value">${s.total}</p>
                    <p class="logs-card-note">${t('logs.runningNow', {count: s.running})}${s.truncated ? ' · ' + t('logs.truncated') : ''}</p></div>
                <div class="logs-card"><p class="logs-card-label">${t('logs.successRate')}</p><p class="logs-card-value">${percent(s.success_rate)}</p>
                    <p class="logs-card-note">${t('logs.okFailed', {ok: s.success, failed: s.failed})}</p></div>
                <div class="logs-card"><p class="logs-card-label">${t('logs.duration')}</p><p class="logs-card-value">${seconds(s.duration.median)}</p>
                    <p class="logs-card-note">${t('logs.p95', {value: seconds(s.duration.p95)})}</p></div>
                <div class="logs-card"><p class="logs-card-label">${t('logs.uploadCache')}</p><p class="logs-card-value">${percent(cache.hit_rate)}</p>
                    <p class="logs-card-note">${t('logs.cacheNote', {hits: cache.hits, misses: cache.misses})}</p></div>
                <div class="logs-card"><p class="logs-card-label">${t('logs.overTime')}</p><div class="logs-bars" role="img" aria-label="${esc(t('logs.overTime'))}">${bars}</div></div>
            </div>
            <details class="logs-breakdown"><summary>${t('logs.breakdown')}</summary>
                <div class="logs-breakdown-grid">
                    ${miniTable(t('logs.account'), s.by_account.filter((a) => a.token_id !== null), (a) => a.email || ('#' + a.token_id), true)}
                    ${miniTable(t('logs.model'), s.by_model, (m) => m.model || t('logs.unknown'), true)}
                    ${miniTable(t('logs.key'), s.by_client_key, (k) => k.client_key_id ? (k.name || ('#' + k.client_key_id)) : t('logs.noKey'), false)}
                </div></details>`;
        const open = box.querySelector('.logs-breakdown');
        if (open && state.breakdownOpen) open.open = true;
        if (open) open.addEventListener('toggle', () => { state.breakdownOpen = open.open; });
    }

    function miniTable(title, rows, label, withMedian) {
        const columns = withMedian ? 4 : 3;
        const head = `<tr><th></th><th>${t('logs.requests')}</th><th>${t('logs.failedShort')}</th>${withMedian ? `<th>${t('logs.medianShort')}</th>` : ''}</tr>`;
        const body = rows.map((row) => `<tr><td title="${esc(label(row))}">${esc(label(row))}</td><td>${row.requests}</td><td>${row.failed}</td>${withMedian ? `<td>${seconds(row.median)}</td>` : ''}</tr>`).join('');
        return `<table class="logs-mini"><caption>${esc(title)}</caption><thead>${head}</thead><tbody>${body || `<tr><td colspan="${columns}">-</td></tr>`}</tbody></table>`;
    }

    // The account, model and key choices come from the logs of the chosen time range.
    function renderFacets() {
        const s = state.summary;
        const fill = (id, selected, first, items) => {
            const select = byId(id);
            if (!select) return;
            const known = new Set(items.map(([value]) => String(value)));
            const all = selected && !known.has(String(selected)) ? [[selected, String(selected)], ...items] : items;
            select.innerHTML = option('', first, '') + all.map(([value, label]) => option(value, esc(label), selected)).join('');
            select.value = selected || '';
        };
        fill('logsAccount', state.token, t('logs.allAccounts'), s ? s.by_account.filter((a) => a.token_id !== null).map((a) => [a.token_id, a.email || ('#' + a.token_id)]) : []);
        fill('logsModel', state.model, t('logs.allModels'), s ? s.by_model.filter((m) => m.model).map((m) => [m.model, m.model]) : []);
        fill('logsKey', state.key, t('logs.allKeys'), s ? s.by_client_key.filter((k) => k.client_key_id).map((k) => [k.client_key_id, k.name || ('#' + k.client_key_id)]) : []);
    }

    // ---- retention ----

    async function loadRetention() {
        try {
            const response = await request('/api/logs/retention');
            if (!response || !response.ok) return;
            const data = await response.json();
            byId('logsRetentionDays').value = data.retention_days;
        } catch (error) {
            console.error('log retention failed:', error);
        }
    }

    async function saveRetention() {
        const input = byId('logsRetentionDays');
        const status = byId('logsRetentionStatus');
        const days = Number(input.value);
        if (!Number.isInteger(days) || days < 0 || days > 3650) {
            status.textContent = t('logs.retentionInvalid');
            return;
        }
        if (days > 0 && !confirm(t('logs.retentionConfirm', {days}))) return;
        try {
            const response = await request('/api/logs/retention', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({retention_days: days})});
            if (!response) return;
            const data = await response.json();
            if (!response.ok) { status.textContent = t('logs.retentionInvalid'); return; }
            status.textContent = days === 0 ? t('logs.retentionOff') : t('logs.retentionSaved', {days, purged: data.purged});
            state.summaryDirty = true;
            reload();
        } catch (error) {
            status.textContent = String(error.message || error);
        }
    }

    // ---- cells and detail ----

    function modelCell(log) {
        const key = log.client_key_id ? (log.client_key_name || ('#' + log.client_key_id)) : '';
        const job = log.job_id ? log.job_id.replace(/^job_/, '').slice(0, 8) : '';
        if (!log.model && !log.prompt_excerpt && !key && !job) return '<span class="text-xs text-muted-foreground">-</span>';
        const meta = [key && esc(key), job && `<span class="logs-job" title="${esc(log.job_id)}">${esc(job)}</span>`].filter(Boolean).join(' · ');
        return `<div class="logs-model" title="${esc(log.prompt_excerpt)}"><span class="logs-model-id">${esc(log.model || '-')}</span><span class="logs-prompt">${esc(log.prompt_excerpt)}</span>${meta ? `<span class="logs-meta">${meta}</span>` : ''}</div>`;
    }

    function detailHtml(log) {
        const key = log.client_key_id ? (log.client_key_name || ('#' + log.client_key_id)) : t('logs.noKey');
        const rows = [
            [t('logs.model'), log.model || '-'],
            [t('logs.key'), key],
            [t('logs.job'), log.job_id || '-'],
        ];
        let html = `<div class="space-y-2 pt-4 border-t border-border"><h4 class="font-medium text-sm">${t('logs.source')}</h4><dl class="logs-detail-grid">${rows.map(([name, value]) => `<dt>${esc(name)}</dt><dd>${esc(value)}</dd>`).join('')}</dl></div>`;
        const timings = log.timings;
        if (timings) {
            const total = timings.total_ms || timings.stages.reduce((sum, stage) => sum + stage.ms, 0) || 1;
            const parts = timings.stages.map((stage, index) => ({label: t('logs.stage.' + stage.id), ms: stage.ms, color: STAGE_COLORS[index % STAGE_COLORS.length]}));
            if (timings.other_ms) parts.push({label: t('logs.stage.other'), ms: timings.other_ms, color: '#6b7488'});
            const segments = parts.filter((part) => part.ms > 0).map((part) => `<span title="${esc(part.label)}: ${millis(part.ms)}" style="width:${part.ms / total * 100}%;background:${part.color}"></span>`).join('');
            const lines = parts.map((part) => `<tr><td><span class="logs-swatch" style="background:${part.color}"></span>${esc(part.label)}</td><td>${millis(part.ms)}</td><td>${Math.round(part.ms / total * 100)}%</td></tr>`).join('');
            const cache = timings.upload_cache ? `<p class="text-xs text-muted-foreground">${t('logs.cacheDetail', {images: timings.input_images ?? 0, hits: timings.upload_cache.hits, misses: timings.upload_cache.misses})}</p>` : '';
            html += `<div class="space-y-2 pt-4 border-t border-border"><h4 class="font-medium text-sm">${t('logs.timeBreakdown')}${timings.total_ms ? ` <span class="text-muted-foreground">(${millis(timings.total_ms)})</span>` : ''}</h4><div class="logs-timeline" role="img" aria-label="${esc(t('logs.timeBreakdown'))}">${segments}</div><table class="logs-stages"><tbody>${lines}</tbody></table>${cache}</div>`;
        }
        return html;
    }

    window.LogsView = {fetchPage, modelCell, detailHtml, time, date, invalidate: () => { state.summaryDirty = true; }};
})();
