// Console boot: language, status strip, sign-out, and mounting the Studio view.
import {ApiError, loadApiKey, loadHealth, loadReference, setLanguage, signOut} from './api.js';
import {h, mountStudio} from './studio.js';

const LANGUAGES = ['vi', 'en', 'zh-CN'];
const STORAGE_KEY = 'flow2api.language'; // Shared with the classic pages.
const REFRESH_MS = 30000;
let catalog = {};
let language = 'en';
let studio = null;
let lastRefresh = 0;

function preferredLanguage() {
    let saved = '';
    try { saved = localStorage.getItem(STORAGE_KEY) || ''; } catch (_) { /* Storage is optional. */ }
    const wanted = [saved, ...(navigator.languages || [navigator.language || ''])];
    for (const value of wanted) {
        const lower = String(value).toLowerCase();
        if (lower.startsWith('vi')) return 'vi';
        if (lower.startsWith('zh')) return 'zh-CN';
        if (lower.startsWith('en')) return 'en';
    }
    return 'en';
}

function t(key, params = {}) {
    const text = (catalog[language] && catalog[language][key]) ?? (catalog.en && catalog.en[key]) ?? key;
    return text.replace(/\{(\w+)\}/g, (match, name) => name in params ? String(params[name]) : match);
}

function applyStaticText() {
    document.documentElement.lang = language;
    document.title = t('shell.title');
    for (const node of document.querySelectorAll('[data-t]')) node.textContent = t(node.dataset.t);
    for (const node of document.querySelectorAll('[data-t-title]')) node.title = t(node.dataset.tTitle);
    for (const node of document.querySelectorAll('[data-t-aria-label]')) node.setAttribute('aria-label', t(node.dataset.tAriaLabel));
}

function paintStatus(reference, healthy) {
    const capacity = reference && reference.capacity;
    const cell = (label, value, tone = '') => h('div', {}, h('dt', {}, label), h('dd', {class: tone}, value));
    const slots = kind => capacity && capacity[kind] ? String(capacity[kind].recommended_max_parallel_requests) : '–';
    document.getElementById('status').replaceChildren(
        cell(t('status.service'), t(healthy ? 'status.up' : 'status.down'), healthy ? 'ok' : 'bad'),
        cell(t('status.captcha'), capacity ? String(capacity.captcha_method) : '–'),
        cell(t('status.images'), slots('image')),
        cell(t('status.videos'), slots('video')));
}

function showError(view, error, retry) {
    const message = error instanceof ApiError && error.message.startsWith('HTTP') ? error.message : (error && error.message) || '';
    view.replaceChildren(h('div', {class: 'notice error', role: 'alert'},
        h('h2', {}, t('shell.loadFailed')),
        h('p', {}, t('shell.loadFailedBody')),
        message ? h('p', {class: 'mono'}, message) : null,
        h('button', {type: 'button', class: 'btn primary', onclick: retry}, t('shell.retry'))));
}

async function load() {
    const view = document.getElementById('view');
    view.replaceChildren(h('p', {class: 'boot', role: 'status'}, t('shell.loading')));
    studio = null;
    try {
        const [reference, healthy] = await Promise.all([loadReference(), loadHealth(), loadApiKey()]);
        lastRefresh = Date.now();
        paintStatus(reference, healthy);
        studio = mountStudio(view, {t, reference});
    } catch (error) {
        if (error instanceof ApiError && error.status === 401) return;
        paintStatus(null, false);
        showError(view, error, load);
    }
}

async function refresh() {
    if (!studio || document.hidden || Date.now() - lastRefresh < REFRESH_MS) return;
    lastRefresh = Date.now();
    try {
        const [reference, healthy] = await Promise.all([loadReference(), loadHealth()]);
        paintStatus(reference, healthy);
        studio.update({reference});
    } catch (_) { /* Keep the last known state; the next focus tries again. */ }
}

async function boot() {
    language = preferredLanguage();
    setLanguage(language);
    try {
        const response = await fetch('/static/console/locales.json', {cache: 'no-cache'});
        if (response.ok) catalog = await response.json();
    } catch (_) { /* Keys are shown if the catalogue cannot be read. */ }
    const select = document.getElementById('language');
    select.value = language;
    select.addEventListener('change', () => {
        if (!LANGUAGES.includes(select.value)) return;
        language = select.value;
        setLanguage(language);
        try { localStorage.setItem(STORAGE_KEY, language); } catch (_) { /* Storage is optional. */ }
        applyStaticText();
        lastRefresh = 0;
        if (studio) { studio.update({t}); refresh(); } else load();
    });
    document.getElementById('signOut').addEventListener('click', async () => {
        try { await signOut(); } catch (_) { /* The session may already be gone. */ }
        window.location.assign('/login');
    });
    const closeMenu = () => document.body.classList.remove('menu-open');
    document.getElementById('sideToggle').addEventListener('click', () => document.body.classList.toggle('menu-open'));
    document.getElementById('sideScrim').addEventListener('click', closeMenu);
    document.addEventListener('keydown', event => { if (event.key === 'Escape') closeMenu(); });
    applyStaticText();
    window.addEventListener('focus', refresh);
    document.addEventListener('visibilitychange', refresh);
    await load();
}

boot();
