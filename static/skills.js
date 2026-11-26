/* Agent skill tab: install and usage commands that follow the server URL the user types. */
(() => {
    'use strict';
    const byId = (id) => document.getElementById(id);
    const input = byId('skillsServerUrl');
    if (!input) return;

    const placeholder = '<SERVER_URL>';
    // Commands are built here, not stored in HTML, so quotes and $ signs stay exact.
    const commands = {
        skillsCmdClaude: () => 'mkdir -p ~/.claude/skills && unzip -o ~/Downloads/flow2api-skill.zip -d ~/.claude/skills',
        skillsCmdAgents: () => 'mkdir -p ~/.agents/skills && unzip -o ~/Downloads/flow2api-skill.zip -d ~/.agents/skills',
        skillsCmdKey: (root) => `mkdir -p ~/.config/flow2api && printf 'Flow2API key: ' && IFS= read -rs K && printf 'FLOW2API_BASE_URL=${root}\\nFLOW2API_API_KEY=%s\\n' "$K" > ~/.config/flow2api/env && chmod 600 ~/.config/flow2api/env && unset K && echo`,
        skillsCmdCheck: () => 'python3 ~/.claude/skills/flow2api/scripts/flow2api.py check',
        skillsCmdUse: () => [
            'S=~/.claude/skills/flow2api/scripts/flow2api.py',
            'python3 $S models                                   # models, options and image limits (free)',
            'python3 $S image "a red fox in snow" --aspect 9:16 --out ./out --name fox',
            'python3 $S video "a fox walks through snow" --draft --duration 3 --out ./out        # 360p draft, a third of the credits',
            'python3 $S video "day turns to night" --mode i2v --ref start.png --ref end.png --duration 5 --out ./out',
            'python3 $S video "keep walking" --mode extend --source <media_id> --duration 5 --out ./out',
            'python3 $S video "..." --dry-run                    # validate and print the request, sends nothing',
            'python3 $S jobs                                     # recent jobs; python3 $S job <job_id> fetches one',
        ].join('\n'),
    };

    // A root that is safe to place inside a shell command: http(s), no query, no /v1, plain characters.
    function cleanRoot(value) {
        try {
            const url = new URL(String(value || '').trim());
            if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
            if (url.username || url.password || url.search || url.hash) return null;
            const root = url.origin + url.pathname.replace(/\/+$/, '').replace(/\/v1$/, '');
            return /^[A-Za-z0-9._~:/%-]+$/.test(root) ? root : null;
        } catch (_) {
            return null;
        }
    }

    function render() {
        const root = cleanRoot(input.value);
        const error = byId('skillsUrlError');
        if (error) error.textContent = !input.value.trim() || root ? '' : I18n.t('skills.urlInvalid');
        for (const [id, build] of Object.entries(commands)) {
            const node = byId(id);
            if (node) node.textContent = build(root || placeholder);
        }
    }

    async function copy(id) {
        const status = byId('skillsCopyStatus');
        const node = byId(id);
        if (!node) return;
        if (id === 'skillsCmdKey' && !cleanRoot(input.value)) {
            if (status) status.textContent = I18n.t('skills.urlInvalid');
            return;
        }
        try {
            await navigator.clipboard.writeText(node.textContent);
            if (status) status.textContent = I18n.t('skills.copied');
        } catch (_) {
            // Clipboard needs a secure context; select the text so Ctrl+C works.
            const range = document.createRange();
            range.selectNodeContents(node);
            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            if (status) status.textContent = I18n.t('skills.copyFailed');
        }
    }

    input.value = location.origin;
    input.addEventListener('input', render);
    document.addEventListener('click', (event) => {
        const button = event.target.closest('[data-skills-copy]');
        if (button) copy(button.dataset.skillsCopy);
    });
    window.addEventListener('languagechange', render);
    I18n.ready.then(render);
})();
