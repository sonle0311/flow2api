// Studio view: pick a base model and parameters, generate, inspect results.
import * as models from './models.js';
import {toCurl, toJson} from './request-preview.js';
import {streamGeneration} from './api.js';

const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
const SEGMENT_LIMIT = 5;
const KNOWN_ERRORS = new Set(['invalid_stream', 'stream_ended', 'no_result', 'missing_api_key']);
const ICONS = {
    copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a1 1 0 0 1 1-1h9"/>',
    close: '<path d="M6 6l12 12M18 6 6 18"/>',
    open: '<path d="M14 5h5v5M19 5l-8 8M10 7H6a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1v-4"/>',
    download: '<path d="M12 4v11m0 0-4-4m4 4 4-4M5 19h14"/>',
    reuse: '<path d="M4 12a8 8 0 0 1 14-5l2 2m0-5v5h-5M20 12a8 8 0 0 1-14 5l-2-2m0 5v-5h5"/>',
    retry: '<path d="M20 12a8 8 0 1 1-3-6.2L20 8m0-5v5h-5"/>',
};

// Tiny DOM builder: text is always set as text, never parsed as HTML.
export function h(tag, attributes = {}, ...children) {
    const node = document.createElement(tag);
    for (const [name, value] of Object.entries(attributes || {})) {
        if (value === false || value == null) continue;
        if (name.startsWith('on')) node.addEventListener(name.slice(2), value);
        else if (name === 'class') node.className = value;
        else node.setAttribute(name, value === true ? '' : value);
    }
    for (const child of children.flat()) {
        if (child != null && child !== false) node.append(child.nodeType ? child : String(child));
    }
    return node;
}

function icon(name) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    svg.innerHTML = ICONS[name]; // Static markup from the table above only.
    return svg;
}

export function mountStudio(root, context) {
    let {t, reference} = context;
    const state = {
        type: 'image', modelId: '', selection: {}, prompt: '', images: [], mediaId: '',
        count: 1, format: 'curl', flash: [], inputError: '', jobs: [], nextJob: 1,
    };

    const contracts = () => reference.model_parameters || [];
    const groups = () => models.listModels(contracts(), reference.models || []);
    const contract = () => contracts().find(item => item.id === state.modelId);
    const input = () => ({prompt: state.prompt, images: state.images.map(item => item.url), mediaId: state.mediaId});
    const running = type => state.jobs.filter(job => job.type === type && (job.status === 'queued' || job.status === 'running')).length;

    function chooseModel(id) {
        state.modelId = id;
        state.selection = models.initialSelection(contract());
        trimInputs();
    }

    function chooseType(type) {
        state.type = type;
        const offered = groups()[type];
        if (offered.length) chooseModel(offered[0].id);
        else { state.modelId = ''; state.selection = {}; }
    }

    function trimInputs() {
        const rules = models.referenceRules(contract(), state.selection);
        if (!rules.images) state.images = [];
        else state.images = state.images.slice(0, rules.maxImages);
        state.count = Math.max(1, Math.min(state.count, models.maxCount(reference.capacity, state.type) || 1));
    }

    function valueLabel(name, value) {
        if (name === 'mode') return t('mode.' + value);
        if (name === 'durationSeconds') return t('unit.seconds', {n: value});
        return String(value);
    }

    // ----- Form -----
    const controls = h('div', {class: 'studio-controls'});
    const promptField = h('textarea', {
        id: 'studioPrompt', rows: '5', spellcheck: 'false',
        oninput: event => { state.prompt = event.target.value; paintFooter(); },
        onkeydown: event => { if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') submit(); },
    });
    const promptLabel = h('label', {class: 'label', for: 'studioPrompt'});
    const references = h('div', {class: 'studio-references'});
    const countRow = h('div', {class: 'studio-count'});
    const generate = h('button', {type: 'button', class: 'btn primary studio-generate', onclick: () => submit()});
    const reason = h('p', {class: 'studio-reason', id: 'studioReason', role: 'status'});
    const previewCode = h('pre', {class: 'studio-code mono', tabindex: '0'});
    const previewTools = h('div', {class: 'studio-preview-tools'});
    const previewSummary = h('summary');
    const preview = h('details', {class: 'studio-preview'}, previewSummary, previewTools, previewCode);
    const form = h('section', {class: 'studio-form'},
        controls, h('div', {class: 'studio-field'}, promptLabel, promptField), references, countRow,
        h('div', {class: 'studio-submit'}, generate, reason), preview);

    function segmented(label, values, current, onPick, describe = String, marked = false) {
        const group = h('div', {class: 'segmented' + (marked ? ' flash' : ''), role: 'group', 'aria-label': label},
            values.map(value => h('button', {
                type: 'button', 'aria-pressed': String(value === current), onclick: () => onPick(value),
            }, describe(value))));
        return h('div', {class: 'studio-field'}, h('span', {class: 'label'}, label), group);
    }

    function ratioLabel(value) {
        const [width, height] = String(value).split(':').map(Number);
        const box = h('span', {class: 'ratio', 'aria-hidden': 'true'});
        if (width > 0 && height > 0) box.style.aspectRatio = `${width} / ${height}`;
        return [box, String(value)];
    }

    function paintControls() {
        const offered = groups();
        const current = contract();
        const nodes = [
            segmented(t('studio.type'), ['image', 'video'], state.type, value => { chooseType(value); paint(); }, value => t('type.' + value)),
        ];
        const modelId = 'studioModel';
        nodes.push(h('div', {class: 'studio-field'},
            h('label', {class: 'label', for: modelId}, t('studio.model')),
            h('select', {id: modelId, onchange: event => { chooseModel(event.target.value); paint(); }},
                offered[state.type].map(item => h('option', {value: item.id, selected: item.id === state.modelId}, item.label)))));
        if (current) {
            for (const name of models.parameterNames(current)) {
                const values = models.validValues(current, state.selection, name);
                if (name === 'mode' && values.length < 2) continue;
                const pick = value => {
                    const result = models.applyChange(current, state.selection, name, value);
                    state.selection = result.selection;
                    state.flash = result.changed;
                    trimInputs();
                    paint();
                    state.flash = [];
                };
                const label = t('param.' + name);
                const marked = state.flash.includes(name);
                if (values.length <= SEGMENT_LIMIT) {
                    const describe = name === 'aspectRatio' ? ratioLabel : value => valueLabel(name, value);
                    nodes.push(segmented(label, values, state.selection[name], pick, describe, marked));
                } else {
                    const id = 'studioParam-' + name;
                    nodes.push(h('div', {class: 'studio-field'},
                        h('label', {class: 'label', for: id}, label),
                        h('select', {id, class: marked ? 'flash' : '', onchange: event => {
                            const raw = event.target.value;
                            pick(values.find(value => String(value) === raw));
                        }}, values.map(value => h('option', {value: String(value), selected: value === state.selection[name]}, valueLabel(name, value))))));
                }
            }
        }
        controls.replaceChildren(...nodes);
    }

    function addFiles(files) {
        const rules = models.referenceRules(contract(), state.selection);
        state.inputError = '';
        for (const file of files) {
            if (state.images.length >= rules.maxImages) { state.inputError = t('studio.error.tooMany', {n: rules.maxImages}); break; }
            if (!file.type.startsWith('image/')) { state.inputError = t('studio.error.notImage'); continue; }
            if (file.size > MAX_IMAGE_BYTES) { state.inputError = t('studio.error.tooLarge', {name: file.name}); continue; }
            const entry = {name: file.name, url: ''};
            state.images.push(entry);
            const reader = new FileReader();
            reader.onload = () => { entry.url = String(reader.result); paintReferences(); paintFooter(); };
            reader.onerror = () => { state.images = state.images.filter(item => item !== entry); state.inputError = t('studio.error.read'); paintReferences(); paintFooter(); };
            reader.readAsDataURL(file);
        }
        paintReferences();
        paintFooter();
    }

    function paintReferences() {
        const current = contract();
        const rules = current ? models.referenceRules(current, state.selection) : {images: false, needsMediaId: false};
        const nodes = [];
        if (rules.needsMediaId) {
            nodes.push(h('div', {class: 'studio-field'},
                h('label', {class: 'label', for: 'studioMediaId'}, t('studio.mediaId')),
                h('input', {
                    id: 'studioMediaId', type: 'text', class: 'mono', value: state.mediaId, spellcheck: 'false', autocomplete: 'off',
                    'aria-describedby': 'studioMediaHint', oninput: event => { state.mediaId = event.target.value; paintFooter(); },
                }),
                h('p', {class: 'studio-hint', id: 'studioMediaHint'}, t('studio.mediaIdHint'))));
        }
        if (rules.images) {
            const picker = h('input', {
                type: 'file', accept: 'image/*', multiple: rules.maxImages > 1, class: 'visually-hidden', id: 'studioFiles',
                onchange: event => { addFiles([...event.target.files]); event.target.value = ''; },
            });
            const full = state.images.length >= rules.maxImages;
            const zone = h('label', {
                class: 'studio-drop' + (full ? ' full' : ''), for: 'studioFiles',
                ondragover: event => { event.preventDefault(); zone.classList.add('over'); },
                ondragleave: () => zone.classList.remove('over'),
                ondrop: event => { event.preventDefault(); zone.classList.remove('over'); addFiles([...event.dataTransfer.files]); },
            }, full ? t('studio.dropFull', {n: rules.maxImages}) : t('studio.drop', {n: rules.maxImages}));
            const thumbs = state.images.map(item => h('li', {},
                item.url ? h('img', {src: item.url, alt: item.name}) : h('span', {class: 'studio-thumb-wait'}),
                h('button', {
                    type: 'button', class: 'studio-thumb-remove', 'aria-label': t('studio.removeImage', {name: item.name}),
                    onclick: () => { state.images = state.images.filter(other => other !== item); paintReferences(); paintFooter(); },
                }, icon('close'))));
            const hint = rules.minImages > 0 ? t('studio.refsRequired', {min: rules.minImages, max: rules.maxImages}) : t('studio.refsOptional', {max: rules.maxImages});
            nodes.push(h('div', {class: 'studio-field'},
                h('span', {class: 'label'}, t('studio.references')), picker, zone,
                thumbs.length ? h('ul', {class: 'studio-thumbs'}, thumbs) : null,
                h('p', {class: 'studio-hint'}, hint)));
        }
        if (state.inputError) nodes.push(h('p', {class: 'studio-input-error', role: 'alert'}, state.inputError));
        references.replaceChildren(...nodes);
    }

    function paintCount() {
        const limit = models.maxCount(reference.capacity, state.type);
        const values = Array.from({length: Math.max(limit, 1)}, (_, index) => index + 1);
        const field = segmented(t('studio.count'), values, state.count, value => { state.count = value; paintCount(); paintFooter(); });
        const capacity = reference.capacity && reference.capacity[state.type];
        const total = capacity ? capacity.recommended_max_parallel_requests : 0;
        const free = Math.max(0, total - running(state.type));
        countRow.replaceChildren(field, h('p', {class: 'studio-hint num'}, t('studio.capacity', {free, total})));
    }

    function blocking() {
        const current = contract();
        if (!current) return 'studio.block.noModels';
        const limit = models.maxCount(reference.capacity, state.type);
        if (!limit) return 'studio.block.capacity';
        if (state.images.some(item => !item.url)) return 'studio.block.reading';
        const key = models.blockingReason(current, state.selection, input());
        if (key) return key;
        const total = reference.capacity[state.type].recommended_max_parallel_requests;
        if (running(state.type) + state.count > total) return 'studio.block.busy';
        return null;
    }

    function paintFooter() {
        const current = contract();
        const key = blocking();
        const rules = current ? models.referenceRules(current, state.selection) : {minImages: 0, maxImages: 0};
        generate.disabled = Boolean(key);
        generate.textContent = t(state.type === 'image' ? 'studio.generateImages' : 'studio.generateVideos', {n: state.count});
        if (key) generate.setAttribute('aria-describedby', 'studioReason');
        else generate.removeAttribute('aria-describedby');
        reason.textContent = key ? t(key, {min: rules.minImages, max: rules.maxImages}) : t('studio.shortcut');
        reason.classList.toggle('blocked', Boolean(key) && key !== 'studio.block.prompt');
        previewSummary.textContent = t('studio.preview');
        previewTools.replaceChildren(
            h('div', {class: 'segmented', role: 'group', 'aria-label': t('studio.previewFormat')},
                ['curl', 'json'].map(format => h('button', {
                    type: 'button', 'aria-pressed': String(state.format === format),
                    onclick: () => { state.format = format; paintFooter(); },
                }, format === 'curl' ? 'cURL' : 'JSON'))),
            h('button', {type: 'button', class: 'btn small', onclick: event => copyPreview(event.currentTarget)}, icon('copy'), t('studio.copy')));
        previewCode.textContent = current ? previewText() : '';
    }

    function previewText() {
        const body = models.buildBody(contract(), state.selection, input());
        return state.format === 'json' ? toJson(body) : toCurl(window.location.origin, body);
    }

    async function copyPreview(button) {
        let copied = false;
        try { await navigator.clipboard.writeText(previewText()); copied = true; } catch (_) { /* Clipboard may be blocked. */ }
        const label = button.lastChild;
        label.textContent = t(copied ? 'studio.copied' : 'studio.copyFailed');
        setTimeout(() => { label.textContent = t('studio.copy'); }, 1600);
    }

    // ----- Results -----
    const resultTitle = h('h2');
    const resultMeta = h('span', {class: 'studio-result-meta num'});
    const clear = h('button', {type: 'button', class: 'btn small ghost', onclick: () => {
        for (const job of state.jobs.filter(item => item.status === 'done' || item.status === 'failed' || item.status === 'cancelled')) job.element.remove();
        state.jobs = state.jobs.filter(job => job.status === 'queued' || job.status === 'running');
        paintResultsHeader();
    }});
    const grid = h('ul', {class: 'studio-grid', 'aria-live': 'polite'});
    const empty = h('div', {class: 'studio-empty'});
    const results = h('section', {class: 'studio-results', 'aria-labelledby': 'studioResultsTitle'},
        h('header', {}, resultTitle, resultMeta, clear), empty, grid);
    resultTitle.id = 'studioResultsTitle';

    function paintResultsHeader() {
        resultTitle.textContent = t('studio.results');
        const active = state.jobs.filter(job => job.status === 'queued' || job.status === 'running').length;
        const finished = state.jobs.filter(job => job.status === 'done').length;
        resultMeta.textContent = state.jobs.length ? t('studio.resultMeta', {active, finished}) : '';
        clear.textContent = t('studio.clear');
        clear.hidden = state.jobs.length === active;
        empty.hidden = state.jobs.length > 0;
        empty.replaceChildren(h('p', {class: 'studio-empty-title'}, t('studio.emptyTitle')), h('p', {}, t('studio.emptyBody')));
    }

    function errorText(message) {
        return KNOWN_ERRORS.has(message) ? t('error.' + message) : message;
    }

    function paintJob(job) {
        const head = h('div', {class: 'studio-tile-head'},
            h('span', {class: 'studio-tile-model'}, job.label),
            h('span', {class: 'studio-tile-params mono'}, job.summary));
        let body;
        const actions = [];
        if (job.status === 'queued' || job.status === 'running') {
            job.progressNode = h('p', {class: 'studio-tile-progress'}, job.progress || t(job.status === 'queued' ? 'studio.queued' : 'studio.starting'));
            body = h('div', {class: 'studio-tile-body waiting'}, h('span', {class: 'studio-spinner', 'aria-hidden': 'true'}), job.progressNode);
            actions.push(h('button', {type: 'button', class: 'btn small', onclick: () => cancel(job)}, t('studio.cancel')));
        } else if (job.status === 'done') {
            body = h('div', {class: 'studio-tile-body media'}, job.media.map(item => item.kind === 'video'
                ? h('video', {src: item.url, controls: true, loop: true, muted: true, playsinline: true, preload: 'metadata'})
                : h('img', {src: item.url, alt: job.prompt, loading: 'lazy'})));
            const first = job.media[0];
            actions.push(
                h('a', {class: 'btn small', href: first.url, target: '_blank', rel: 'noopener'}, icon('open'), t('studio.open')),
                h('a', {class: 'btn small', href: first.url, download: ''}, icon('download'), t('studio.download')));
        } else {
            const cancelled = job.status === 'cancelled';
            body = h('div', {class: 'studio-tile-body ' + (cancelled ? 'cancelled' : 'failed')},
                h('p', {class: 'studio-tile-status'}, t(cancelled ? 'studio.cancelled' : 'studio.failed')),
                cancelled ? null : h('p', {class: 'studio-tile-error'}, errorText(job.error)));
            actions.push(h('button', {type: 'button', class: 'btn small', onclick: () => start(job)}, icon('retry'), t('studio.retry')));
        }
        if (job.status !== 'queued' && job.status !== 'running') {
            actions.push(h('button', {type: 'button', class: 'btn small ghost', onclick: () => reuse(job)}, icon('reuse'), t('studio.reuse')));
        }
        job.element.className = 'studio-tile ' + job.status;
        job.element.replaceChildren(head, body, h('div', {class: 'studio-tile-actions'}, actions));
    }

    function settle(job, status, extra = {}) {
        Object.assign(job, {status, controller: null}, extra);
        paintJob(job);
        paintResultsHeader();
        paintCount();
        paintFooter();
    }

    async function start(job) {
        job.controller = new AbortController();
        Object.assign(job, {status: 'running', progress: '', error: '', media: []});
        paintJob(job);
        paintResultsHeader();
        paintCount();
        paintFooter();
        const controller = job.controller;
        try {
            const media = await streamGeneration(job.body, {
                signal: controller.signal,
                onProgress: text => { job.progress = text; if (job.progressNode) job.progressNode.textContent = text; },
            });
            settle(job, 'done', {media});
        } catch (error) {
            if (controller.signal.aborted) settle(job, 'cancelled');
            else settle(job, 'failed', {error: (error && error.message) || 'no_result'});
        }
    }

    function cancel(job) {
        if (job.timer) { clearTimeout(job.timer); job.timer = null; settle(job, 'cancelled'); }
        else if (job.controller) job.controller.abort();
    }

    function reuse(job) {
        Object.assign(state, {
            type: job.type, modelId: job.snapshot.modelId, selection: {...job.snapshot.selection},
            prompt: job.prompt, images: job.snapshot.images.slice(), mediaId: job.snapshot.mediaId,
        });
        if (!contract()) chooseType(state.type);
        promptField.value = state.prompt;
        paint();
        promptField.focus();
    }

    function submit() {
        if (blocking()) return;
        const current = contract();
        const body = models.buildBody(current, state.selection, input());
        const label = groups()[state.type].find(item => item.id === current.id).label;
        const summary = models.parameterNames(current).filter(name => name !== 'mode' || current.parameters.mode.values.length > 1)
            .map(name => valueLabel(name, state.selection[name])).join(' · ');
        const stagger = Number(reference.capacity[state.type].launch_stagger_ms) || 0;
        for (let index = 0; index < state.count; index += 1) {
            const job = {
                id: state.nextJob++, type: state.type, label, summary, body, prompt: state.prompt.trim(), status: 'queued',
                snapshot: {modelId: current.id, selection: {...state.selection}, images: state.images.slice(), mediaId: state.mediaId},
                element: h('li'), media: [], progress: '', error: '',
            };
            state.jobs.unshift(job);
            grid.prepend(job.element);
            paintJob(job);
            if (index === 0) start(job);
            else job.timer = setTimeout(() => { job.timer = null; start(job); }, index * stagger);
        }
        paintResultsHeader();
        paintCount();
        paintFooter();
    }

    function paint() {
        promptLabel.textContent = t('studio.prompt');
        promptField.placeholder = t(state.type === 'image' ? 'studio.promptImage' : 'studio.promptVideo');
        paintControls();
        paintReferences();
        paintCount();
        paintFooter();
        paintResultsHeader();
        for (const job of state.jobs) paintJob(job);
    }

    form.addEventListener('paste', event => {
        const files = [...(event.clipboardData?.files || [])].filter(file => file.type.startsWith('image/'));
        if (files.length && contract() && models.referenceRules(contract(), state.selection).images) { event.preventDefault(); addFiles(files); }
    });

    chooseType(groups().image.length ? 'image' : 'video');
    root.replaceChildren(h('div', {class: 'studio'}, form, results));
    paint();

    return {
        update(next) {
            if (next.t) t = next.t;
            if (next.reference) {
                reference = next.reference;
                if (!contract()) chooseType(state.type);
                else trimInputs();
            }
            paint();
        },
    };
}
