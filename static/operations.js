/* Operations card: security checks, alerts, credit usage, Flow model table, captcha diagnostics. */
(() => {
    'use strict';
    const POLL_MS = 30000;
    let timer = null;
    let generation = 0;

    const element = id => document.getElementById(id);
    const t = (key, params) => window.I18n.t(key, params);
    const toast = (message, kind) => { if (typeof window.showToast === 'function') window.showToast(message, kind); };

    async function errorText(response) {
        try {
            const body = await response.json();
            if (typeof body.detail === 'string') return body.detail;
        } catch (error) { /* not JSON */ }
        return 'HTTP ' + response.status;
    }

    async function call(url, options) {
        const response = await window.apiRequest(url, options);
        if (!response) return null;
        if (!response.ok) throw new Error(await errorText(response));
        return response.json();
    }

    function showError(message) {
        const box = element('opsError');
        box.textContent = message || '';
        box.hidden = !message;
    }

    function item(text, state) {
        const li = document.createElement('li');
        li.textContent = text;
        if (state) li.dataset.state = state;
        return li;
    }

    function when(value) {
        const date = new Date(typeof value === 'number' ? value * 1000 : value);
        if (Number.isNaN(date.getTime())) return String(value || '');
        return date.toLocaleString(window.I18n.locale, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
    }

    function table(headers, rows) {
        const node = document.createElement('table');
        node.className = 'client-keys-table';
        const head = document.createElement('tr');
        headers.forEach(label => { const th = document.createElement('th'); th.textContent = label; head.appendChild(th); });
        node.appendChild(document.createElement('thead')).appendChild(head);
        const body = node.appendChild(document.createElement('tbody'));
        rows.forEach(values => {
            const tr = document.createElement('tr');
            values.forEach(value => { const td = document.createElement('td'); td.textContent = value === null || value === undefined ? '–' : String(value); tr.appendChild(td); });
            body.appendChild(tr);
        });
        return node;
    }

    function renderSecurity(status) {
        const list = element('opsSecurity');
        list.replaceChildren(
            status.default_admin_password
                ? item(t('管理员仍在使用默认密码'), 'bad') : item(t('管理员密码已修改'), 'ok'),
            status.default_api_key
                ? item(t('主 API Key 仍是默认值，请在设置中更换'), 'bad') : item(t('主 API Key 已自定义'), 'ok'),
            status.listening_on_all_interfaces
                ? item(t('监听所有网卡（端口 {0}）；如只需本机访问，请把 server.host 设为 127.0.0.1', { 0: status.port }), 'warn')
                : item(t('仅监听本机'), 'ok'),
        );
    }

    function renderAlerts(data) {
        const settings = data.settings;
        element('opsEnabled').checked = settings.enabled;
        if (document.activeElement !== element('opsLowCredits')) element('opsLowCredits').value = settings.low_credits;
        if (document.activeElement !== element('opsCooldown')) element('opsCooldown').value = settings.cooldown_minutes;
        element('opsWebhookNote').textContent = settings.webhook_configured
            ? t('已配置：{0}（地址不会再次显示；保存时留空即清除）', { 0: settings.webhook_host })
            : t('尚未配置 Webhook，问题只显示在这里');
        const conditions = element('opsConditions');
        conditions.replaceChildren(...(data.conditions.length
            ? data.conditions.map(row => item(`${row.message} (${when(row.since)})`, row.severity === 'critical' ? 'bad' : 'warn'))
            : [item(t('没有问题'), 'ok')]));
        element('opsEvents').replaceChildren(...data.history.slice(0, 10).map(row => {
            const state = row.delivered === true ? t('已发送') : row.delivered === false ? t('发送失败') : t('未发送');
            return item(`${when(row.time)} · ${row.kind} · ${row.message} · ${state}`, row.delivered === false ? 'warn' : '');
        }));
    }

    function renderUsage(data) {
        element('opsUsageSummary').textContent = t('近 {0} 天共消耗 {1} credit（按账号余额变化实测）', { 0: data.days, 1: data.total_credits });
        const box = element('opsUsage');
        box.replaceChildren();
        if (!data.by_key.length) return;
        box.append(
            table([t('客户'), 'credit', t('请求')], data.by_key.map(row => [row.name, row.credits, row.requests])),
            table([t('模型'), 'credit', t('请求')], data.by_model.slice(0, 12).map(row => [row.model, row.credits, row.requests])),
        );
    }

    function renderCatalog(state) {
        const parts = [];
        parts.push(state.last_checked ? t('上次检查：{0}', { 0: when(state.last_checked) }) : t('尚未检查'));
        if (state.last_error) parts.push(t('读取失败：{0}', { 0: state.last_error }));
        const report = state.report;
        if (report) {
            parts.push(t('Flow 共 {0} 个模型 key', { 0: state.entries }));
            if (report.obsolete_local_keys.length) parts.push(t('本地使用但 Flow 已下线的模型 key：{0}', { 0: report.obsolete_local_keys.join(', ') }));
            if (report.limit_mismatches.length) parts.push(t('{0} 个参考图上限与 Flow 不一致', { 0: report.limit_mismatches.length }));
        }
        const diff = state.last_diff;
        if (diff) {
            parts.push(diff.added.length || diff.removed.length || diff.repriced.length
                ? t('与上次相比：新增 {0}，移除 {1}，调价 {2}', { 0: diff.added.length, 1: diff.removed.length, 2: diff.repriced.length })
                : t('与上次相比没有变化'));
        }
        element('opsCatalog').textContent = parts.join(' · ');
    }

    function renderCaptcha(data) {
        element('opsCaptchaMethod').textContent = t('验证码方式：{0}', { 0: data.method });
        const box = element('opsCaptcha');
        box.replaceChildren();
        if (!data.accounts.length) { box.textContent = t('暂无记录'); return; }
        box.append(table(
            [t('账号'), t('近 1 小时成功'), t('失败'), t('被 Flow 拒绝'), t('平均耗时（秒）'), t('最近失败')],
            data.accounts.map(row => [
                row.token_id, row.last_hour.ok, row.last_hour.failed, row.last_hour.rejected, row.mint_seconds_avg,
                row.last_failure ? `${when(row.last_failure.at)} · ${row.last_failure.reason}` : null,
            ]),
        ));
    }

    async function load() {
        const current = ++generation;
        try {
            const [security, alerts, usage, catalog, captcha] = await Promise.all([
                call('/api/admin/security-status'), call('/api/admin/alerts'), call('/api/admin/usage?days=7'),
                call('/api/admin/catalog-status'), call('/api/admin/captcha-diagnostics'),
            ]);
            if (!security || current !== generation) return;
            showError('');
            renderSecurity(security);
            renderAlerts(alerts);
            renderUsage(usage);
            renderCatalog(catalog);
            renderCaptcha(captcha);
        } catch (error) {
            if (current === generation) showError(error.message);
        }
    }

    async function act(button, work) {
        button.disabled = true;
        try { await work(); } catch (error) { showError(error.message); } finally { button.disabled = false; }
    }

    async function saveAlerts(event) {
        event.preventDefault();
        await act(event.submitter || element('opsAlertForm').querySelector('[type=submit]'), async () => {
            const body = {
                enabled: element('opsEnabled').checked,
                low_credits: Number.parseInt(element('opsLowCredits').value || '0', 10),
                cooldown_minutes: Number.parseInt(element('opsCooldown').value || '360', 10),
            };
            const url = element('opsWebhook').value.trim();
            if (url) body.webhook_url = url;
            if (await call('/api/admin/alerts', { method: 'PUT', body: JSON.stringify(body) })) {
                element('opsWebhook').value = '';
                toast(t('告警设置已保存'), 'success');
                await load();
            }
        });
    }

    function panelVisible() {
        const panel = element('panelSettings');
        return Boolean(panel) && !panel.classList.contains('hidden') && !document.hidden;
    }

    function syncPolling() {
        if (panelVisible()) {
            if (timer === null) { load(); timer = setInterval(load, POLL_MS); }
        } else if (timer !== null) {
            clearInterval(timer);
            timer = null;
        }
    }

    function init() {
        const panel = element('panelSettings');
        if (!panel || !element('operationsCard')) return;
        element('opsAlertForm').addEventListener('submit', saveAlerts);
        element('opsAlertTest').addEventListener('click', event => act(event.currentTarget, async () => {
            if (await call('/api/admin/alerts/test', { method: 'POST' })) toast(t('测试消息已发送'), 'success');
        }));
        element('opsAlertCheck').addEventListener('click', event => act(event.currentTarget, async () => {
            if (await call('/api/admin/alerts/check', { method: 'POST' })) await load();
        }));
        element('opsCatalogCheck').addEventListener('click', event => act(event.currentTarget, async () => {
            if (await call('/api/admin/catalog-check', { method: 'POST' })) { toast(t('检查完成'), 'success'); await load(); }
        }));
        new MutationObserver(syncPolling).observe(panel, { attributes: true, attributeFilter: ['class'] });
        document.addEventListener('visibilitychange', syncPolling);
        window.addEventListener('languagechange', load);
        syncPolling();
    }

    window.I18n.ready.then(init);
})();
