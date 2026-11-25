/* Per-client API keys. The secret is shown once, never stored, and cleared when its dialog closes. */
(() => {
    'use strict';
    const POLL_MS = 10000;
    let rows = [];
    let timer = null;
    let generation = 0;
    let editingId = null;
    let secretDialog = null;
    let editDialog = null;
    let editPicker = null;
    let createPicker = null;
    let modelOptionsLoaded = false;

    const element = id => document.getElementById(id);
    const t = (key, params) => window.I18n.t(key, params);
    const toast = (message, kind) => { if (typeof window.showToast === 'function') window.showToast(message, kind); };

    async function errorText(response) {
        try {
            const body = await response.json();
            const detail = body && body.detail;
            if (Array.isArray(detail) && detail.length) return String(detail[0].msg || detail[0].type || response.status);
            if (typeof detail === 'string') return detail;
        } catch (error) { /* not JSON */ }
        return 'HTTP ' + response.status;
    }

    // Resolves to the parsed JSON, or null when the page redirected to login.
    async function call(url, options) {
        const response = await window.apiRequest(url, options);
        if (!response) return null;
        if (!response.ok) throw new Error(await errorText(response));
        return response.json();
    }

    function showError(message) {
        const box = element('clientKeysError');
        if (!box) return;
        box.textContent = message || '';
        box.hidden = !message;
    }

    function cell(content, className) {
        const td = document.createElement('td');
        if (className) td.className = className;
        if (content instanceof Node) td.appendChild(content); else td.textContent = content;
        return td;
    }

    function limitText(value) {
        return value > 0 ? String(value) : t('不限');
    }

    function modelsText(models) {
        if (!models.length) return t('全部模型');
        return models.length <= 2 ? models.join(', ') : `${models.slice(0, 2).join(', ')} +${models.length - 2}`;
    }

    function creditsText(row) {
        if (row.credit_budget > 0) return ' · ' + t('本月 {0} / {1} credit', { 0: row.credits_used, 1: row.credit_budget });
        return row.credits_used > 0 ? ' · ' + t('本月 {0} credit', { 0: row.credits_used }) : '';
    }

    function lastUsedText(value) {
        if (!value) return t('从未');
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return value;
        return date.toLocaleString(window.I18n.locale, { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
    }

    function actionButton(label, onClick, danger) {
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = label;
        if (danger) button.dataset.danger = '';
        button.addEventListener('click', onClick);
        return button;
    }

    function render() {
        const body = element('clientKeysBody');
        if (!body) return;
        body.replaceChildren();
        if (!rows.length) {
            const tr = document.createElement('tr');
            const td = cell(t('还没有客户密钥。在上方填写名称即可创建。'), 'client-keys-empty');
            td.colSpan = 7;
            tr.appendChild(td);
            body.appendChild(tr);
            return;
        }
        for (const row of rows) {
            const tr = document.createElement('tr');
            const identity = document.createElement('div');
            const prefix = document.createElement('code');
            prefix.textContent = row.key_prefix + '…';
            identity.append(document.createTextNode(row.name), document.createElement('br'), prefix);
            const badge = document.createElement('span');
            badge.className = 'client-keys-badge';
            badge.dataset.active = String(row.is_active);
            badge.textContent = row.is_active ? t('已启用') : t('已禁用');
            const actions = document.createElement('div');
            actions.className = 'client-keys-actions';
            actions.append(
                actionButton(row.is_active ? t('禁用') : t('启用'), () => update(row, { is_active: !row.is_active })),
                actionButton(t('编辑'), () => openEdit(row)),
                actionButton(t('轮换密钥'), () => rotate(row)),
                actionButton(t('删除'), () => remove(row), true),
            );
            const models = cell(modelsText(row.allowed_models || []), 'client-keys-models');
            if (row.allowed_models && row.allowed_models.length) models.title = row.allowed_models.join('\n');
            tr.append(
                cell(identity), cell(badge),
                cell(t('{0} / 分钟 · {1} 并发', { 0: limitText(row.rate_limit_per_minute), 1: limitText(row.max_concurrent) })),
                models,
                cell(t('{0} 进行中 · {1} 近 1 分钟 · {2} 累计', { 0: row.in_flight, 1: row.requests_last_minute, 2: row.total_requests }) + creditsText(row)),
                cell(lastUsedText(row.last_used_at)), cell(actions),
            );
            body.appendChild(tr);
        }
    }

    async function load() {
        const current = ++generation;
        try {
            const data = await call('/api/client-keys');
            if (!data || current !== generation) return;
            rows = Array.isArray(data.client_keys) ? data.client_keys : [];
            showError('');
            render();
        } catch (error) {
            if (current === generation) showError(t('加载客户密钥失败: {0}', { 0: error.message }));
        }
    }

    function showSecret(secret, titleKey) {
        element('clientKeySecretTitle').textContent = t(titleKey);
        element('clientKeySecretValue').textContent = secret;
        element('clientKeyCopy').textContent = t('复制');
        if (!secretDialog.open) secretDialog.showModal();
    }

    function closeSecret() {
        element('clientKeySecretValue').textContent = '';
        if (secretDialog.open) secretDialog.close();
    }

    async function copySecret() {
        const text = element('clientKeySecretValue').textContent;
        const button = element('clientKeyCopy');
        try {
            if (navigator.clipboard && navigator.clipboard.writeText) {
                await navigator.clipboard.writeText(text);
            } else {
                const range = document.createRange();
                range.selectNodeContents(element('clientKeySecretValue'));
                const selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);
                if (!document.execCommand('copy')) throw new Error('copy');
            }
            button.textContent = t('已复制');
        } catch (error) {
            toast(t('复制失败，请手动选择并复制'), 'error');
        }
    }

    async function guarded(action) {
        try {
            await action();
        } catch (error) {
            toast(t('客户密钥操作失败: {0}', { 0: error.message }), 'error');
        }
    }

    async function create(event) {
        event.preventDefault();
        const submit = element('clientKeySubmit');
        submit.disabled = true;
        await guarded(async () => {
            const data = await call('/api/client-keys', {
                method: 'POST',
                body: JSON.stringify({
                    name: element('clientKeyName').value.trim(),
                    rate_limit_per_minute: Number.parseInt(element('clientKeyRate').value, 10),
                    max_concurrent: Number.parseInt(element('clientKeyConcurrent').value, 10),
                    credit_budget: Number.parseInt(element('clientKeyBudget').value || '0', 10),
                    allowed_models: createPicker.collect(),
                }),
            });
            if (!data) return;
            element('clientKeyName').value = '';
            createPicker.set([]);
            showSecret(data.api_key, '客户密钥已创建');
            await load();
        });
        submit.disabled = false;
    }

    async function update(row, changes) {
        await guarded(async () => {
            if (await call('/api/client-keys/' + row.id, { method: 'PUT', body: JSON.stringify(changes) })) {
                toast(t('客户密钥已更新'), 'success');
                await load();
            }
        });
    }

    // A list of model names/patterns edited as chips; `root` carries the data-picker-* parts.
    function makePicker(root) {
        const input = root.querySelector('[data-picker-input]');
        const chips = root.querySelector('[data-picker-chips]');
        let models = [];

        function render() {
            chips.replaceChildren();
            if (!models.length) {
                const empty = document.createElement('li');
                empty.className = 'client-keys-hint';
                empty.textContent = t('全部模型');
                chips.appendChild(empty);
                return;
            }
            for (const pattern of models) {
                const chip = document.createElement('li');
                chip.className = 'client-keys-chip';
                const name = document.createElement('code');
                name.textContent = pattern;
                const remove = document.createElement('button');
                remove.type = 'button';
                remove.textContent = '×';
                remove.setAttribute('aria-label', t('移除 {0}', { 0: pattern }));
                remove.addEventListener('click', () => {
                    models = models.filter(item => item !== pattern);
                    render();
                });
                chip.append(name, remove);
                chips.appendChild(chip);
            }
        }

        function add(value) {
            const pattern = String(value).trim();
            if (pattern && !models.includes(pattern)) models.push(pattern);
            input.value = '';
            render();
        }

        root.querySelector('[data-picker-add]').addEventListener('click', () => add(input.value));
        input.addEventListener('keydown', event => {
            if (event.key !== 'Enter') return;
            event.preventDefault();
            add(input.value);
        });
        for (const preset of root.querySelectorAll('[data-client-key-preset]')) {
            preset.addEventListener('click', () => add(preset.dataset.clientKeyPreset));
        }
        render();
        return {
            render,
            set(list) {
                models = [...list];
                input.value = '';
                render();
            },
            // Text still typed in the box counts as an entry, so Save/Create never drops it.
            collect() {
                add(input.value);
                return [...models];
            },
        };
    }

    // Suggestions only: any model name or pattern can still be typed, and the server validates it.
    async function loadModelOptions() {
        if (modelOptionsLoaded) return;
        try {
            const data = await call('/api/client-keys/models');
            if (!data) return;
            element('clientKeyModelOptions').replaceChildren(...data.models.map(model => {
                const option = document.createElement('option');
                option.value = model.id;
                option.label = model.type;
                return option;
            }));
            modelOptionsLoaded = true;
        } catch (error) { /* typing a name still works */ }
    }

    function openEdit(row) {
        editingId = row.id;
        element('clientKeyEditName').value = row.name;
        element('clientKeyEditRate').value = row.rate_limit_per_minute;
        element('clientKeyEditConcurrent').value = row.max_concurrent;
        element('clientKeyEditBudget').value = row.credit_budget || 0;
        element('clientKeyEditReset').checked = false;
        editPicker.set(row.allowed_models || []);
        element('clientKeyEditError').hidden = true;
        editDialog.showModal();
        loadModelOptions();
    }

    async function saveEdit(event) {
        event.preventDefault();
        const error = element('clientKeyEditError');
        try {
            const data = await call('/api/client-keys/' + editingId, {
                method: 'PUT',
                body: JSON.stringify({
                    name: element('clientKeyEditName').value.trim(),
                    rate_limit_per_minute: Number.parseInt(element('clientKeyEditRate').value, 10),
                    max_concurrent: Number.parseInt(element('clientKeyEditConcurrent').value, 10),
                    credit_budget: Number.parseInt(element('clientKeyEditBudget').value || '0', 10),
                    reset_credits_used: element('clientKeyEditReset').checked,
                    allowed_models: editPicker.collect(),
                }),
            });
            if (!data) return;
            editDialog.close();
            toast(t('客户密钥已更新'), 'success');
            await load();
        } catch (failure) {
            error.textContent = failure.message;
            error.hidden = false;
        }
    }

    async function rotate(row) {
        if (!window.confirm(t('确定要轮换密钥“{0}”吗？旧密钥会立即失效。', { 0: row.name }))) return;
        await guarded(async () => {
            const data = await call('/api/client-keys/' + row.id + '/rotate', { method: 'POST' });
            if (!data) return;
            showSecret(data.api_key, '客户密钥已轮换');
            await load();
        });
    }

    async function remove(row) {
        if (!window.confirm(t('确定要删除密钥“{0}”吗？此操作无法撤销，使用它的客户会立即收到 401。', { 0: row.name }))) return;
        await guarded(async () => {
            if (await call('/api/client-keys/' + row.id, { method: 'DELETE' })) {
                toast(t('客户密钥已删除'), 'success');
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
            if (timer === null) {
                load();
                timer = setInterval(load, POLL_MS);
            }
        } else if (timer !== null) {
            clearInterval(timer);
            timer = null;
        }
    }

    function init() {
        const panel = element('panelSettings');
        if (!panel || !element('clientKeyForm')) return;
        secretDialog = element('clientKeySecretDialog');
        editDialog = element('clientKeyEditDialog');
        element('clientKeyForm').addEventListener('submit', create);
        element('clientKeyEditForm').addEventListener('submit', saveEdit);
        element('clientKeyCopy').addEventListener('click', copySecret);
        element('clientKeySecretClose').addEventListener('click', closeSecret);
        element('clientKeyEditCancel').addEventListener('click', () => editDialog.close());
        editPicker = makePicker(element('clientKeyEditModels'));
        createPicker = makePicker(element('clientKeyCreateModels'));
        document.querySelector('.client-keys-form-models').addEventListener('toggle', loadModelOptions);
        // Closing by Escape must clear the secret as well.
        secretDialog.addEventListener('close', () => { element('clientKeySecretValue').textContent = ''; });
        new MutationObserver(syncPolling).observe(panel, { attributes: true, attributeFilter: ['class'] });
        document.addEventListener('visibilitychange', syncPolling);
        window.addEventListener('languagechange', () => { render(); editPicker.render(); createPicker.render(); });
        syncPolling();
    }

    window.I18n.ready.then(init);
})();
