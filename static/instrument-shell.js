/* Shared shell for the management pages: sidebar, page actions, filters and
   section navigation. Existing page handlers keep ownership of their nodes;
   this file only moves them and adds view-only controls around them. */
(() => {
    'use strict';
    const page = document.documentElement.dataset.i18nPage;
    if (!['manage', 'test'].includes(page)) return;
    const icons = {
        studio:'<rect x="3" y="5" width="18" height="15" rx="3"/><path d="m10 9 5 3.5-5 3.5zM7 2v3m10-3v3"/>',
        tokens:'<circle cx="9" cy="8" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3m2-17a3 3 0 0 1 0 6m2 4a6 6 0 0 1 3 5v2"/>',
        integration:'<path d="m8 6-6 6 6 6m8-12 6 6-6 6m-3-15-2 18"/>',
        skills:'<path d="M12 3l2.2 5.8L20 11l-5.8 2.2L12 19l-2.2-5.8L4 11l5.8-2.2z"/><path d="M19 3v4m-2-2h4"/>',
        logs:'<path d="M5 3h14v18H5zM8 7h8M8 12h8M8 17h5"/>',
        settings:'<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="8" cy="6" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="10" cy="18" r="2"/>',
        menu:'<path d="M4 6h16M4 12h16M4 18h16"/>',
        search:'<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
        brand:'<path d="M6 17V7h12M6 12h8M13 17l5-5-5-5"/>',
    };
    const groups = [
        ['workspace', [['studio','tabTestPage','/console']]],
        ['manage', [['tokens','tabTokens','/manage#tokens'], ['logs','tabLogs','/manage#logs']]],
        ['configure', [['settings','tabSettings','/manage#settings'], ['integration','tabIntegration','/manage#integration'], ['skills','tabSkills','/manage#skills']]],
    ];
    const el = (tag, className, text) => {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    };
    const svg = (name) => {
        const node = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        node.setAttribute('viewBox', '0 0 24 24');
        node.setAttribute('aria-hidden', 'true');
        node.innerHTML = icons[name];
        return node;
    };
    // Text owned by the shell, re-rendered when the language changes.
    const texts = [];
    const bind = (node, key, attribute) => { texts.push([node, key, attribute]); return node; };
    const paintTexts = () => {
        for (const [node, key, attribute] of texts) {
            const value = I18n.t(key);
            if (attribute) node.setAttribute(attribute, value); else node.textContent = value;
        }
    };

    function buildFilter(host, body, searchKey, options, classify) {
        const bar = el('div', 'sheet-filter');
        const field = el('label', 'sheet-search');
        field.append(svg('search'));
        const input = el('input');
        input.type = 'search';
        input.autocomplete = 'off';
        bind(input, searchKey, 'placeholder');
        bind(input, searchKey, 'aria-label');
        field.append(input);
        const chips = el('div', 'sheet-chips');
        chips.setAttribute('role', 'group');
        const count = el('span', 'sheet-count');
        count.setAttribute('aria-live', 'polite');
        let active = options[0];
        const buttons = options.map((name) => {
            const button = el('button');
            button.type = 'button';
            button.dataset.filter = name;
            const label = bind(el('span'), 'shell.filter.' + name);
            const badge = el('b');
            button.append(label, badge);
            button.addEventListener('click', () => { active = name; run(); });
            chips.append(button);
            return [name, button, badge];
        });
        function run() {
            const query = input.value.trim().toLowerCase();
            const rows = [...body.querySelectorAll(':scope > tr')].filter((row) => row.children.length > 1);
            const totals = Object.fromEntries(options.map((name) => [name, 0]));
            let shown = 0;
            for (const row of rows) {
                const kind = classify(row);
                const matchesText = !query || row.textContent.toLowerCase().includes(query);
                if (matchesText) { totals[options[0]] += 1; if (kind in totals && kind !== options[0]) totals[kind] += 1; }
                const visible = matchesText && (active === options[0] || kind === active);
                row.hidden = !visible;
                if (visible) shown += 1;
            }
            for (const [name, button, badge] of buttons) {
                button.setAttribute('aria-pressed', String(name === active));
                badge.textContent = String(totals[name]);
            }
            count.textContent = rows.length ? `${shown} / ${rows.length}` : '';
        }
        input.addEventListener('input', run);
        new MutationObserver(run).observe(body, {childList: true});
        bar.append(field, chips, count);
        host.after(bar);
        run();
    }

    function buildManageLayout(render) {
        // Primary account actions sit beside the page title.
        const heading = document.querySelector('.instrument-page-heading');
        const toolbar = document.querySelector('.instrument-account-toolbar');
        let actions = null;
        if (heading) {
            const copy = el('div', 'page-heading-copy');
            copy.append(...heading.children);
            actions = el('div', 'page-actions');
            heading.append(copy, actions);
            if (toolbar) {
                for (const selector of ['button[onclick="exportTokens()"]', 'button[onclick="openImportModal()"]', 'button[onclick="openAddModal()"]', '#addAccountWithBrowser']) {
                    const button = toolbar.querySelector(selector);
                    if (button) actions.append(button);
                }
            }
        }
        const tokenBody = document.getElementById('tokenTableBody');
        if (toolbar && tokenBody) {
            buildFilter(toolbar.querySelector('h3'), tokenBody, 'shell.search.accounts', ['all', 'enabled', 'disabled'],
                (row) => row.children[1] && row.children[1].querySelector('.bg-green-50') ? 'enabled' : 'disabled');
        }
        // Settings: one column of sections with a sticky table of contents.
        const settings = document.getElementById('panelSettings');
        const cards = settings ? [...settings.querySelectorAll(':scope > .grid > div')] : [];
        if (cards.length) {
            const nav = el('nav', 'settings-nav');
            bind(nav, 'shell.sections', 'aria-label');
            const links = cards.map((card, index) => {
                card.id = card.id || 'settings-section-' + (index + 1);
                const link = el('a');
                link.href = '#' + card.id;
                const title = card.querySelector(':scope > h3 > span');
                link.append(title ? title.cloneNode(true) : document.createTextNode(String(index + 1)));
                link.addEventListener('click', (event) => {
                    event.preventDefault();
                    card.scrollIntoView({behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start'});
                    mark(link);
                });
                nav.append(link);
                return link;
            });
            const mark = (current) => links.forEach((link) => link.setAttribute('aria-current', link === current ? 'true' : 'false'));
            mark(links[0]);
            if ('IntersectionObserver' in window) {
                const spy = new IntersectionObserver((entries) => {
                    const top = entries.filter((entry) => entry.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
                    if (top) mark(links[cards.indexOf(top.target)]);
                }, {rootMargin: '-80px 0px -60% 0px'});
                cards.forEach((card) => spy.observe(card));
            }
            settings.prepend(nav);
        }
        return (active) => { if (actions) actions.hidden = active !== 'tokens'; };
    }

    I18n.ready.then(() => {
        const rail = el('aside', 'instrument-rail');
        const brand = el('a', 'instrument-brand');
        brand.href = '/console';
        brand.setAttribute('aria-label', 'Flow2API');
        const mark = el('span', 'instrument-brand-mark');
        mark.append(svg('brand'));
        brand.append(mark, el('span', '', 'flow2api'));
        const navigation = el('nav', 'instrument-rail-nav');
        rail.append(brand, navigation);
        const nodes = new Map();
        for (const [group, destinations] of groups) {
            navigation.append(bind(el('p', 'instrument-rail-group'), 'shell.group.' + group));
            for (const [name, id, href] of destinations) {
                // Move the original tab node so inline handlers and references survive.
                const node = page === 'manage' ? document.getElementById(id) : el('a');
                if (!node) continue;
                if (node.tagName === 'A') node.href = href;
                const label = el('span', 'instrument-rail-label');
                label.dataset.instrumentLabel = name;
                node.replaceChildren(svg(name), label);
                node.dataset.instrumentDestination = name;
                node.addEventListener('click', () => document.body.classList.remove('instrument-menu-open'));
                navigation.append(node);
                nodes.set(name, node);
            }
        }
        // Live system card.
        const status = el('dl', 'instrument-rail-status');
        const row = (key) => {
            const wrap = el('div');
            const value = el('dd', '', '–');
            wrap.append(bind(el('dt'), key), value);
            status.append(wrap);
            return value;
        };
        const service = row('shell.status.service');
        const accounts = row('shell.status.accounts');
        let healthy = null;
        const paintService = () => {
            if (healthy === null) return;
            service.textContent = I18n.t(healthy ? 'shell.status.online' : 'shell.status.offline');
            service.className = healthy ? 'ok' : 'bad';
        };
        async function refreshStatus() {
            if (document.hidden) return;
            try { healthy = (await fetch('/health', {cache: 'no-store'})).ok; } catch (_) { healthy = false; }
            paintService();
            try {
                const response = await fetch('/api/stats', {credentials: 'include', headers: I18n.headers()});
                if (response.ok) {
                    const stats = await response.json();
                    if (stats && stats.total_tokens !== undefined) accounts.textContent = `${stats.active_tokens ?? 0} / ${stats.total_tokens}`;
                }
            } catch (_) { /* The card keeps its last value. */ }
        }
        rail.append(status);
        // Language, repository link and sign-out move to the foot of the sidebar.
        const foot = el('div', 'instrument-rail-foot');
        for (const selector of ['[data-language-select]', '.instrument-topbar a[href^="https://github.com"]', 'button[onclick="logout()"]']) {
            const node = document.querySelector(selector);
            if (node) foot.append(node);
        }
        rail.append(foot);
        const scrim = el('div', 'instrument-rail-scrim');
        scrim.addEventListener('click', () => document.body.classList.remove('instrument-menu-open'));
        const toggle = el('button', 'instrument-menu-toggle');
        toggle.type = 'button';
        toggle.append(svg('menu'));
        bind(toggle, 'shell.menu', 'aria-label');
        toggle.addEventListener('click', () => document.body.classList.toggle('instrument-menu-open'));
        document.addEventListener('keydown', (event) => { if (event.key === 'Escape') document.body.classList.remove('instrument-menu-open'); });
        const topbar = document.querySelector('.instrument-topbar');
        if (topbar) topbar.prepend(toggle);
        document.body.prepend(rail, scrim);
        const onPanel = page === 'manage' ? buildManageLayout() : null;

        function render() {
            navigation.setAttribute('aria-label', I18n.t('shell.navigation'));
            const active = page === 'test' ? 'studio' : ['tokens','settings','logs','integration','skills'].find(name => {
                const panel = document.getElementById('panel' + name[0].toUpperCase() + name.slice(1));
                return panel && !panel.classList.contains('hidden');
            }) || 'tokens';
            for (const [name, node] of nodes) {
                node.setAttribute('aria-current', name === active ? 'page' : 'false');
                node.setAttribute('aria-label', I18n.t(`shell.${name}`));
                node.querySelector('.instrument-rail-label').textContent = I18n.t(`shell.${name}`);
            }
            const heading = document.getElementById('instrumentPageTitle');
            const description = document.getElementById('instrumentPageDescription');
            if (heading) heading.textContent = I18n.t(`shell.title.${active}`);
            if (description) description.textContent = I18n.t(`shell.description.${active}`);
            const breadcrumb = document.getElementById('instrumentBreadcrumb');
            if (breadcrumb) breadcrumb.textContent = I18n.t(`shell.${active}`);
            document.body.dataset.instrumentPanel = active;
            if (onPanel) onPanel(active);
            paintTexts();
            paintService();
        }
        if (page === 'manage') {
            const observer = new MutationObserver(render);
            document.querySelectorAll('#panelTokens,#panelSettings,#panelLogs,#panelIntegration,#panelSkills').forEach(panel => observer.observe(panel, {attributes: true, attributeFilter: ['class']}));
        }
        window.addEventListener('languagechange', render);
        window.addEventListener('focus', refreshStatus);
        render();
        refreshStatus();
    });
})();
