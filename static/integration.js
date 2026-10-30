/* Copyable API integration instructions for the admin console. */
(() => {
    'use strict';

    I18n.ready.then(() => {
        const server = document.getElementById('integrationServerUrl');
        const preview = document.getElementById('integrationGuide');
        const copyButton = document.getElementById('copyIntegrationGuide');
        const selectButton = document.getElementById('selectIntegrationGuide');
        const status = document.getElementById('integrationCopyStatus');
        const validation = document.getElementById('integrationUrlError');
        const referenceStatus = document.getElementById('integrationReferenceStatus');
        const reloadButton = document.getElementById('reloadIntegrationReference');
        const search = document.getElementById('integrationReferenceSearch');
        if (!server || !preview || !copyButton || !selectButton || !status || !validation) return;

        const t = key => I18n.t(`integration.${key}`);
        const code = (language, value) => `\`\`\`${language}\n${value}\n\`\`\``;
        let copyState = '';
        let reference = null;
        let loading = false;
        let loadFailed = false;
        const localized = value => value?.[I18n.locale] || value?.en || '';

        function referenceGuide(root) {
            const lines = [t('referenceSource'), `## ${t('auth')}`, t('authHelp'), `## ${t('endpoints')}`];
            for (const endpoint of reference.endpoints) {
                lines.push(`- ${endpoint.method} ${root}${endpoint.path} [${endpoint.auth}]`);
            }
            for (const [listed, heading] of [[true, 'publicModels'], [false, 'legacyModels']]) {
                lines.push(`## ${t(heading)}`, t('modelHelp'));
                lines.push('| ID | type | input | aspect_ratio | duration_seconds | configured_min_images | locally_validated_min_images | max_images | upsample |');
                lines.push('| --- | --- | --- | --- | --- | --- | --- | --- | --- |');
                for (const model of reference.models.filter(item => item.listed === listed)) {
                    lines.push(`| ${model.id} | ${model.type} | ${model.video_type || 'image'} | ${model.aspect_ratio} | ${model.duration_seconds} | ${model.min_images} | ${model.locally_validated_min_images} | ${model.max_images} | ${model.upsample} |`);
                }
            }
            lines.push(`## ${t('aliases')}`);
            for (const alias of reference.aliases) {
                lines.push(`- ${alias.id} | ${alias.type} | aspect: ${alias.aspects.join(', ')} | imageSize: ${alias.image_sizes.join(', ') || '—'}`);
            }
            lines.push(`## ${t('endpointDetails')}`);
            for (const endpoint of reference.endpoints) {
                const notes = endpoint.notes || {};
                lines.push(`### ${endpoint.method} ${endpoint.path}`, `${t('auth')}: ${endpoint.auth}`);
                lines.push(localized(notes.summary) || endpoint.summary);
                if (notes.details) lines.push(localized(notes.details));
                if (endpoint.parameters.length) lines.push(t('parameterLabel'), code('json', JSON.stringify(endpoint.parameters, null, 2)));
                if (endpoint.request_body) lines.push(t('bodyLabel'), code('json', JSON.stringify(endpoint.request_body, null, 2)));
                if (notes.body_fields) lines.push(t('fieldsLabel'), code('json', JSON.stringify(notes.body_fields, null, 2)));
                if (notes.body_example) lines.push(t('exampleLabel'), code('json', JSON.stringify(notes.body_example, null, 2)));
                if (notes.query_example) lines.push('query:', code('json', JSON.stringify(notes.query_example, null, 2)));
                if (notes.response_example) lines.push(t('responseLabel'), code('json', JSON.stringify(notes.response_example, null, 2)));
                if (Object.keys(endpoint.responses).length) lines.push(t('responseLabel'), code('json', JSON.stringify(endpoint.responses, null, 2)));
            }
            lines.push(`## ${t('schemas')}`, code('json', JSON.stringify({ components: { schemas: reference.schemas } }, null, 2)));
            return lines.join('\n\n');
        }

        function addRows(id, rows) {
            const fragment = document.createDocumentFragment();
            for (const values of rows) {
                const row = document.createElement('tr');
                row.className = 'border-t border-border';
                for (const value of values) {
                    const cell = document.createElement('td');
                    cell.className = 'p-3 align-top break-words';
                    cell.textContent = String(value);
                    row.appendChild(cell);
                }
                fragment.appendChild(row);
            }
            document.getElementById(id).replaceChildren(fragment);
        }

        function renderReference() {
            referenceStatus.textContent = t(loading ? 'loading' : loadFailed ? 'loadFailed' : 'ready');
            reloadButton.disabled = loading;
            if (!reference) return;
            const query = search.value.trim().toLowerCase();
            const matches = values => values.join(' ').toLowerCase().includes(query);
            const endpointRows = reference.endpoints.map(item => [item.method, item.path, item.auth]);
            const modelRows = reference.models.map(item => [item.id,
                `${item.type}/${item.video_type || 'image'} · ${item.aspect_ratio} · ${item.duration_seconds ?? '—'}s · images ${item.min_images}–${item.max_images ?? '?'} · ${item.upsample || '—'}`,
                t(item.listed ? 'publicModels' : 'legacyModels')]);
            const aliasRows = reference.aliases.map(item => [item.id, `${item.type} · ${item.aspects.join(', ')} · ${item.image_sizes.join(', ')}`]);
            addRows('integrationEndpointRows', endpointRows.filter(matches));
            addRows('integrationModelRows', modelRows.filter(matches));
            addRows('integrationAliasRows', aliasRows.filter(matches));
            document.getElementById('integrationEndpointCount').textContent = `(${reference.endpoints.length})`;
            document.getElementById('integrationModelCount').textContent = `(${reference.models.length})`;
            document.getElementById('integrationAliasCount').textContent = `(${reference.aliases.length})`;
        }

        function normalizeRoot(value) {
            const url = new URL(value.trim());
            if (!['http:', 'https:'].includes(url.protocol)
                || url.username || url.password || url.search || url.hash) {
                throw new Error('Invalid server root');
            }
            return url.href.replace(/\/+$/, '');
        }

        function buildGuide(root) {
            const request = {
                model: '<MODEL_ID_FROM_MODELS>',
                messages: [{ role: 'user', content: '<PROMPT>' }],
                stream: false,
            };
            const reference = [{ type: 'text', text: '<PROMPT>' }, {
                type: 'image_url', image_url: { url: '<HTTPS_IMAGE_URL_OR_DATA_IMAGE_URI>' },
            }];
            const geminiRequest = {
                contents: [{ role: 'user', parts: [{ text: '<PROMPT>' }] }],
            };
            const quotedRoot = `'${root.replace(/'/g, "'\\''")}'`;
            return [
                `# ${t('title')}`,
                t('agentTask'),
                `## ${t('connectionTitle')}`,
                code('sh', `export FLOW2API_BASE_URL=${quotedRoot}\nexport FLOW2API_API_KEY='<YOUR_FLOW2API_API_KEY>'`),
                `OpenAI base URL: ${root}/v1\nGemini base URL: ${root}/v1beta`,
                t('serverHelp'),
                t('connectionHelp'),
                `## ${t('discoveryTitle')}`,
                t('discoveryHelp'),
                code('sh', 'curl --fail-with-body "$FLOW2API_BASE_URL/health"\n\ncurl --fail-with-body "$FLOW2API_BASE_URL/v1/models" \\\n  -H "Authorization: Bearer $FLOW2API_API_KEY"'),
                `## ${t('openaiTitle')}`,
                t('openaiHelp'),
                `POST ${root}/v1/chat/completions\nAuthorization: Bearer <FLOW2API_API_KEY>\nContent-Type: application/json`,
                code('json', JSON.stringify(request, null, 2)),
                `## ${t('referenceTitle')}`,
                t('referenceHelp'),
                'messages[0].content:',
                code('json', JSON.stringify(reference, null, 2)),
                `## ${t('resultTitle')}`,
                t('resultHelp'),
                code('text', 'stream: false -> choices[0].message.content\nstream: true  -> data: {"choices":[{"delta":{"reasoning_content":"..."}}]}\n                data: {"choices":[{"delta":{"content":"..."}}]}\n                data: [DONE]\nimage: ![Generated Image](https://... or data:image/...)\nvideo: <video src="https://..." controls></video>'),
                `## ${t('geminiTitle')}`,
                t('geminiHelp'),
                `GET ${root}/v1beta/models\nPOST ${root}/v1beta/models/<MODEL_ID>:generateContent\nPOST ${root}/v1beta/models/<MODEL_ID>:streamGenerateContent?alt=sse\nx-goog-api-key: <FLOW2API_API_KEY>\nContent-Type: application/json`,
                code('json', JSON.stringify(geminiRequest, null, 2)),
                'candidates[0].content.parts -> inlineData { mimeType, data } / fileData { mimeType, fileUri } / text',
                `## ${t('reliabilityTitle')}`,
                t('reliabilityHelp'),
                `## ${t('checklistTitle')}`,
                t('checklist'),
                referenceGuide(root),
                window.Flow2APIIntegrationRecipes.build(root, I18n.locale),
            ].join('\n\n');
        }

        function renderStatus() {
            status.textContent = copyState ? t(copyState) : '';
            status.classList.toggle('text-destructive', copyState === 'copyFailed');
        }

        function renderGuide() {
            copyState = '';
            renderStatus();
            try {
                const root = normalizeRoot(server.value);
                preview.value = reference && !loading && !loadFailed ? buildGuide(root) : '';
                document.getElementById('integrationOpenAIBase').textContent = `${root}/v1`;
                validation.textContent = '';
                server.setAttribute('aria-invalid', 'false');
                copyButton.disabled = !preview.value;
                selectButton.disabled = !preview.value;
            } catch (_) {
                preview.value = '';
                document.getElementById('integrationOpenAIBase').textContent = '—';
                validation.textContent = t('invalidUrl');
                server.setAttribute('aria-invalid', 'true');
                copyButton.disabled = true;
                selectButton.disabled = true;
            }
        }

        async function loadReference() {
            if (loading) return;
            loading = true;
            loadFailed = false;
            renderReference();
            renderGuide();
            try {
                const response = await fetch('/api/integration/reference', {
                    credentials: 'include', headers: I18n.headers(), cache: 'no-store',
                });
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                const data = await response.json();
                if (!Array.isArray(data.endpoints) || !Array.isArray(data.models)
                    || !Array.isArray(data.aliases) || !data.schemas) throw new Error('Incomplete reference');
                reference = data;
            } catch (_) {
                loadFailed = true;
                reference = null;
            } finally {
                loading = false;
                renderReference();
                renderGuide();
            }
        }

        function selectGuide() {
            preview.focus();
            preview.select();
        }

        async function copyGuide() {
            if (!preview.value) return;
            const text = preview.value;
            let copied = false;
            copyButton.disabled = true;
            try {
                if (navigator.clipboard?.writeText) {
                    await navigator.clipboard.writeText(text);
                    copied = true;
                }
            } catch (_) { /* Continue with selectable-text fallback. */ }
            if (!copied) {
                try {
                    selectGuide();
                    copied = document.execCommand('copy');
                } catch (_) { /* The preview remains available for manual copying. */ }
            }
            copyButton.disabled = !preview.value;
            // A language or URL change while clipboard permission was pending resets feedback.
            if (preview.value === text) {
                copyState = copied ? 'copied' : 'copyFailed';
                renderStatus();
            }
        }

        server.value = window.location.origin;
        server.addEventListener('input', renderGuide);
        copyButton.addEventListener('click', copyGuide);
        selectButton.addEventListener('click', selectGuide);
        reloadButton.addEventListener('click', loadReference);
        search.addEventListener('input', renderReference);
        window.addEventListener('languagechange', () => { renderReference(); renderGuide(); });
        renderGuide();
        loadReference();
    });
})();
