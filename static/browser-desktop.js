/* Human-operated VPS desktop; authentication stays in the same-origin session cookie. */
(() => {
    'use strict';
    const STATUS_KEYS = {
        connecting: '正在连接…', connected: '已连接', disconnected: '已断开连接',
        error: '连接失败', unavailable: '远程桌面不可用', auth: '请重新登录管理后台',
    };
    const MESSAGE_KEYS = {
        connecting: '正在打开服务器桌面。',
        disconnected: '桌面连接已断开。Chrome 和账号同步仍在服务器上运行。',
        error: '无法连接服务器桌面。请重新连接；如果仍失败，请检查服务器桌面服务。',
        unavailable: '此部署未启用远程桌面，或桌面服务尚未就绪。请返回账号管理。',
        auth: '管理会话已过期。请重新登录，再打开服务器桌面。',
    };
    let currentRfb = null, generation = 0, state = 'connecting';
    const element = id => document.getElementById(id);
    const t = key => window.I18n.t(key);

    function render() {
        element('desktopStatus').textContent = t(STATUS_KEYS[state] || STATUS_KEYS.error);
        element('desktopMessage').hidden = state === 'connected';
        element('desktopMessageText').textContent = MESSAGE_KEYS[state] ? t(MESSAGE_KEYS[state]) : '';
        element('desktopLoginLink').hidden = state !== 'auth';
        element('desktopReconnect').disabled = state === 'connecting';
        element('desktopDisconnect').disabled = state !== 'connected';
        element('desktopScreen').setAttribute('aria-busy', String(state === 'connecting'));
    }

    function setState(next) { state = next; render(); }

    function closeConnection() {
        const previous = currentRfb;
        currentRfb = null;
        if (previous) previous.disconnect();
        element('desktopScreen').replaceChildren();
    }

    async function desktopConfig() {
        const response = await fetch('/api/browser-desktop/config', {
            credentials: 'same-origin', cache: 'no-store', headers: window.I18n.headers(),
        });
        if (response.status === 401 || response.status === 403) return 'auth';
        if (!response.ok) return 'unavailable';
        const data = await response.json();
        return data.success && data.desktop?.enabled === true ? 'available' : 'unavailable';
    }

    async function disconnected(epoch) {
        if (epoch !== generation) return;
        currentRfb = null;
        setState('error');
        try {
            const availability = await desktopConfig();
            if (epoch === generation && availability !== 'available') setState(availability);
        } catch (_) { /* The translated connection error already offers recovery. */ }
    }

    async function connect() {
        const epoch = ++generation;
        closeConnection();
        setState('connecting');
        try {
            const availability = await desktopConfig();
            if (epoch !== generation) return;
            if (availability !== 'available') { setState(availability); return; }
            const {default: RFB} = await import('/browser-desktop/assets/core/rfb.js');
            if (epoch !== generation) return;
            const socket = new URL('/api/browser-desktop/ws', window.location.href);
            socket.protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const rfb = new RFB(element('desktopScreen'), socket.href);
            currentRfb = rfb;
            rfb.scaleViewport = true;
            rfb.resizeSession = false;
            rfb.viewOnly = false;
            rfb.addEventListener('connect', () => { if (epoch === generation) setState('connected'); });
            rfb.addEventListener('disconnect', () => void disconnected(epoch));
            rfb.addEventListener('securityfailure', () => { if (epoch === generation) setState('error'); });
            rfb.addEventListener('credentialsrequired', () => { if (epoch === generation) setState('error'); });
        } catch (_) {
            if (epoch === generation) setState('error');
        }
    }

    window.I18n.ready.then(() => {
        element('desktopReconnect').addEventListener('click', () => void connect());
        element('desktopDisconnect').addEventListener('click', () => {
            generation++;
            closeConnection();
            setState('disconnected');
        });
        window.addEventListener('languagechange', render);
        window.addEventListener('pagehide', () => { generation++; closeConnection(); });
        void connect();
    });
})();
