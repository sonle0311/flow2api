/* Shared navigation only; existing page handlers retain their ownership. */
(() => {
    'use strict';
    const page = document.documentElement.dataset.i18nPage;
    if (!['manage', 'test'].includes(page)) return;
    const icons = {
        studio:'<rect x="3" y="5" width="18" height="15" rx="3"/><path d="m10 9 5 3.5-5 3.5zM7 2v3m10-3v3"/>',
        tokens:'<circle cx="9" cy="8" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3m2-17a3 3 0 0 1 0 6m2 4a6 6 0 0 1 3 5v2"/>',
        integration:'<path d="m8 6-6 6 6 6m8-12 6 6-6 6m-3-15-2 18"/>',
        logs:'<path d="M5 3h14v18H5zM8 7h8M8 12h8M8 17h5"/>',
        settings:'<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="8" cy="6" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="10" cy="18" r="2"/>',
    };
    const destinations = [
        ['studio','tabTestPage','/test'],['tokens','tabTokens','/manage#tokens'],
        ['integration','tabIntegration','/manage#integration'],['logs','tabLogs','/manage#logs'],
        ['settings','tabSettings','/manage#settings'],
    ];
    I18n.ready.then(() => {
        const rail = document.createElement('aside');
        rail.className = 'instrument-rail';
        rail.innerHTML = '<a class="instrument-brand" href="/manage" aria-label="Flow2API"><svg viewBox="0 0 40 40" fill="none" aria-hidden="true"><path d="M9 29V11h22M9 20h16M22 29l9-9-9-9" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg></a>';
        const navigation = document.createElement('nav');
        navigation.className = 'instrument-rail-nav';
        rail.append(navigation);
        const nodes = new Map();
        for (const [name, id, href] of destinations) {
            // Move the original tab node so inline handlers and references survive.
            const node = page === 'manage' ? document.getElementById(id) : document.createElement('a');
            if (!node) continue;
            if (node.tagName === 'A') node.href = href;
            const label = document.createElement('span');
            label.className = 'instrument-rail-label';
            label.dataset.instrumentLabel = name;
            node.replaceChildren();
            const svg = document.createElementNS('http://www.w3.org/2000/svg','svg');
            svg.setAttribute('viewBox','0 0 24 24');
            svg.setAttribute('aria-hidden','true');
            svg.innerHTML = icons[name];
            node.append(svg,label);
            node.dataset.instrumentDestination = name;
            navigation.append(node);
            nodes.set(name,node);
        }
        const note = document.createElement('span');
        note.className = 'instrument-rail-note';
        note.textContent = 'Instrument';
        rail.append(note);
        document.body.prepend(rail);
        function render() {
            navigation.setAttribute('aria-label',I18n.t('shell.navigation'));
            const active = page === 'test' ? 'studio' : ['tokens','settings','logs','integration'].find(name => {
                const panel = document.getElementById('panel' + name[0].toUpperCase() + name.slice(1));
                return panel && !panel.classList.contains('hidden');
            }) || 'tokens';
            for (const [name,node] of nodes) {
                node.setAttribute('aria-current',name === active ? 'page' : 'false');
                node.setAttribute('aria-label',I18n.t(`shell.${name}`));
                node.querySelector('.instrument-rail-label').textContent = I18n.t(`shell.${name}`);
            }
            const heading = document.getElementById('instrumentPageTitle');
            const description = document.getElementById('instrumentPageDescription');
            if (heading) heading.textContent=I18n.t(`shell.title.${active}`);
            if (description) description.textContent=I18n.t(`shell.description.${active}`);
            const breadcrumb = document.getElementById('instrumentBreadcrumb');
            if (breadcrumb) breadcrumb.textContent=I18n.t(`shell.${active}`);
        }
        if (page === 'manage') {
            const observer = new MutationObserver(render);
            document.querySelectorAll('#panelTokens,#panelSettings,#panelLogs,#panelIntegration').forEach(panel=>observer.observe(panel,{attributes:true,attributeFilter:['class']}));
        }
        window.addEventListener('languagechange',render);
        render();
    });
})();
