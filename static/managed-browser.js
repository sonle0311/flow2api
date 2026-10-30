/* Account-scoped browser login. This UI never receives or renders cookie values. */
(() => {
    'use strict';
    const STATUS_KEYS = {
        not_configured: '尚未设置浏览器登录',
        opening: '正在打开登录浏览器…',
        awaiting_login: '请登录 Google/Flow，然后关闭窗口以同步',
        syncing: '正在验证并同步 Cookie…',
        ready: 'Cookie 已同步',
        needs_login: '需要重新登录',
        error: '浏览器同步失败',
        stopped: '自动同步已停止',
    };
    const ERROR_KEYS = {
        browser_unavailable: '无法启动浏览器。请在服务器安装 Chrome 或 Edge，并确认可以显示窗口。',
        browser_closed: '登录窗口已关闭。请重新打开浏览器完成登录。',
        login_timeout: '等待登录超时。请重新打开浏览器并完成 Google 验证。',
        login_required: 'Google 登录已失效。请打开浏览器重新登录。',
        identity_mismatch: '登录的 Google 账号与此账号不一致。请切换到此账号后重试。',
        validation_failed: 'Flow 登录验证失败。请在浏览器中确认账号可以正常访问 Flow，然后重试。',
        sync_failed: '浏览器同步失败。请确认网络连接后重试。',
        proxy_invalid: '此账号的代理无效或不受支持。手动浏览器登录仅支持无需用户名和密码的代理。',
    };
    const BUSY_STATUSES = new Set(['opening', 'awaiting_login', 'syncing']);
    let dialog, tokenId = null, expectedEmail = '', currentSession = null, loading = false;
    let timer = null, controller = null, generation = 0, uiError = '';
    let addDialog = null, addLoading = false, addGeneration = 0, addError = '';
    const element = id => document.getElementById(id);
    const t = (key, params) => window.I18n.t(key, params);

    function clearPoll() {
        if (timer !== null) clearTimeout(timer);
        timer = null;
    }

    function render() {
        if (!dialog || !dialog.open) return;
        const status = currentSession?.status || 'not_configured';
        element('managedBrowserAccount').textContent = expectedEmail
            ? `${expectedEmail} · Token #${tokenId}` : `Token #${tokenId}`;
        element('managedBrowserStatus').textContent = loading && !currentSession
            ? t('正在读取浏览器状态…') : t(STATUS_KEYS[status] || STATUS_KEYS.error);
        const date = currentSession?.last_sync_at ? new Date(currentSession.last_sync_at) : null;
        element('managedBrowserLastSync').textContent = date && Number.isFinite(date.getTime())
            ? date.toLocaleString(window.I18n.locale) : t('从未同步');
        const interval = Number(currentSession?.interval_minutes);
        element('managedBrowserInterval').textContent = Number.isFinite(interval) && interval > 0
            ? t('自动同步间隔：{0} 分钟', {'0': interval}) : '';
        const errorKey = uiError || ERROR_KEYS[currentSession?.error_code] ||
            (currentSession?.error_code ? ERROR_KEYS.sync_failed : '');
        const error = element('managedBrowserError');
        error.textContent = errorKey ? t(errorKey) : '';
        error.hidden = !errorKey;
        const pending = loading || BUSY_STATUSES.has(status);
        element('managedBrowserLogin').disabled = pending;
        element('managedBrowserSync').disabled = pending || !currentSession?.enabled;
        element('managedBrowserStop').disabled = loading || !currentSession?.enabled;
        dialog.setAttribute('aria-busy', loading ? 'true' : 'false');
    }

    function schedulePoll() {
        clearPoll();
        if (dialog?.open && tokenId !== null) timer = setTimeout(() => request(), 3000);
    }

    async function request(action = '') {
        if (tokenId === null || loading) return;
        clearPoll();
        const epoch = generation;
        const id = tokenId;
        const abort = new AbortController();
        controller = abort;
        loading = true;
        uiError = '';
        render();
        try {
            const response = await window.apiRequest(`/api/tokens/${id}/browser-session${action ? `/${action}` : ''}`, {
                method: action ? 'POST' : 'GET', signal: abort.signal,
            });
            if (!response) return;
            if (!response.ok) throw new Error('request_failed');
            const data = await response.json();
            if (epoch !== generation) return;
            if (!data.success || !data.session || data.session.token_id !== id) throw new Error('request_failed');
            const wasReady = currentSession?.status === 'ready';
            currentSession = data.session;
            if (!wasReady && currentSession.status === 'ready' && window.refreshTokens) {
                // Show the restored account immediately after explicit login succeeds.
                await window.refreshTokens();
            }
        } catch (error) {
            if (epoch === generation && error.name !== 'AbortError') {
                // Server diagnostics may contain credentials: expose only local translated copy.
                uiError = '无法读取或更新浏览器会话，请稍后重试。';
            }
        } finally {
            if (epoch === generation) {
                loading = false;
                controller = null;
                render();
                schedulePoll();
            }
        }
    }

    function close() {
        generation++;
        clearPoll();
        controller?.abort();
        controller = null;
        loading = false;
        tokenId = null;
        expectedEmail = '';
        currentSession = null;
        uiError = '';
    }

    function open(id, email = '') {
        if (!Number.isSafeInteger(id) || id <= 0 || !dialog) return;
        close();
        tokenId = id;
        expectedEmail = typeof email === 'string' ? email : '';
        if (!dialog.open) dialog.showModal();
        render();
        void request();
    }

    function renderAdd() {
        document.querySelectorAll('[data-browser-add]').forEach(button => {
            button.disabled = addLoading;
        });
        if (!addDialog) return;
        element('managedBrowserAddSubmit').disabled = addLoading;
        element('managedBrowserAddEmail').disabled = addLoading;
        addDialog.setAttribute('aria-busy', addLoading ? 'true' : 'false');
        const error = element('managedBrowserAddError');
        error.textContent = addError ? t(addError) : '';
        error.hidden = !addError;
    }

    function openAdd() {
        if (!addDialog || addLoading) return;
        addGeneration++;
        addError = '';
        element('managedBrowserAddForm').reset();
        addDialog.showModal();
        renderAdd();
        element('managedBrowserAddEmail').focus();
    }

    async function addAccount(event) {
        event.preventDefault();
        if (addLoading || !addDialog?.open) return;
        const form = element('managedBrowserAddForm');
        if (!form.reportValidity()) return;
        const email = element('managedBrowserAddEmail').value.trim().toLowerCase();
        const epoch = addGeneration;
        addLoading = true;
        addError = '';
        renderAdd();
        try {
            // Keep this request alive after dialog cancellation: the server may
            // already have created the pending account and opened its window.
            const response = await window.apiRequest('/api/browser-sessions/accounts', {
                method: 'POST', body: JSON.stringify({email}),
            });
            if (!response) return;
            if (!response.ok) throw new Error('request_failed');
            const data = await response.json();
            const id = data.session?.token_id;
            if (!data.success || !Number.isSafeInteger(id) || id <= 0) throw new Error('request_failed');
            if (window.refreshTokens) await window.refreshTokens();
            if (epoch === addGeneration && addDialog.open) {
                addDialog.close();
                open(id, email);
            }
        } catch (_) {
            if (epoch === addGeneration && addDialog.open) {
                addError = '无法通过浏览器添加账号，请检查邮箱后重试。';
            }
        } finally {
            addLoading = false;
            renderAdd();
        }
    }

    function initialize() {
        dialog = element('managedBrowserDialog');
        if (!dialog) return;
        window.openManagedBrowser = open;
        addDialog = element('managedBrowserAddDialog');
        window.openManagedBrowserAdd = openAdd;
        if (addDialog) {
            element('managedBrowserAddForm').addEventListener('submit', addAccount);
            element('managedBrowserAddCancel').addEventListener('click', () => addDialog.close());
            addDialog.addEventListener('close', () => {
                addGeneration++;
                addError = '';
                renderAdd();
            });
        }
        element('managedBrowserClose').addEventListener('click', () => dialog.close());
        dialog.addEventListener('close', close);
        element('managedBrowserLogin').addEventListener('click', () => request('login'));
        element('managedBrowserSync').addEventListener('click', () => request('sync'));
        element('managedBrowserStop').addEventListener('click', () => request('stop'));
        window.addEventListener('languagechange', render);
        window.addEventListener('languagechange', renderAdd);
        window.addEventListener('pagehide', close);
        // One same-origin capability read; this never opens a browser or tab.
        void fetch('/api/browser-desktop/config', {credentials: 'same-origin', cache: 'no-store'})
            .then(response => response.ok ? response.json() : null)
            .then(data => {
                if (data?.success && data.desktop?.enabled === true && data.desktop.url === '/browser-desktop/') {
                    element('managedBrowserDesktop').hidden = false;
                }
            }).catch(() => { /* Local deployments can omit the remote desktop. */ });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize, {once: true});
    else initialize();
})();
