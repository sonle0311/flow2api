// Pure selection logic over the server's model parameter contracts. No DOM, no network.
// A contract describes one base model: its parameters and the exact variants that exist.

// Earlier parameters constrain later ones; changing one repairs the ones after it.
const ORDER = ['mode', 'durationSeconds', 'aspectRatio', 'imageSize'];
const FALLBACK_MAX_IMAGES = 10;
const MODE_ORDER = ['auto', 't2v', 'i2v', 'r2v', 'extend', 'edit'];

export function parameterNames(contract) {
    return ORDER.filter(name => contract.parameters && contract.parameters[name]);
}

export function listModels(contracts, catalog = []) {
    const names = new Map(catalog.map(model => [model.id, model.display_name]));
    const groups = {image: [], video: []};
    for (const contract of contracts || []) {
        if (!contract.listed || !groups[contract.type]) continue;
        const preferred = findVariant(contract, initialSelection(contract));
        groups[contract.type].push({
            id: contract.id,
            label: titleFor(contract.id, preferred && names.get(preferred.id)),
        });
    }
    return groups;
}

// Variant display names carry the ratio/size/duration; keep only a readable base name.
function titleFor(id, variantName) {
    const fromId = id.split('-').map(part => /^\d/.test(part) ? part : part[0].toUpperCase() + part.slice(1)).join(' ');
    if (!variantName) return fromId;
    const trimmed = String(variantName).split(/\s+[·|(]/)[0].trim();
    return trimmed.length >= 3 && trimmed.length <= 40 ? trimmed : fromId;
}

export function initialSelection(contract, mode) {
    const defaults = (mode && contract.mode_defaults && contract.mode_defaults[mode]) || contract.defaults || {};
    const selection = {};
    for (const name of parameterNames(contract)) selection[name] = defaults[name];
    return repair(contract, selection, -1).selection;
}

function matches(variant, selection, names) {
    return names.every(name => variant[name] === selection[name]);
}

// Values a control may take given the controls that come before it.
export function validValues(contract, selection, name) {
    const names = parameterNames(contract);
    const earlier = names.slice(0, names.indexOf(name));
    const allowed = contract.parameters[name].values.filter(value =>
        contract.variants.some(variant => variant[name] === value && matches(variant, selection, earlier)));
    return name === 'mode' ? allowed.sort((a, b) => MODE_ORDER.indexOf(a) - MODE_ORDER.indexOf(b)) : allowed;
}

function nearest(values, wanted) {
    if (typeof wanted === 'number') {
        return values.reduce((best, value) => Math.abs(value - wanted) < Math.abs(best - wanted) ? value : best, values[0]);
    }
    return values[0];
}

function repair(contract, selection, afterIndex) {
    const names = parameterNames(contract);
    const next = {...selection};
    const changed = [];
    names.forEach((name, index) => {
        if (index <= afterIndex) return;
        const allowed = validValues(contract, next, name);
        if (!allowed.includes(next[name])) {
            next[name] = nearest(allowed, next[name]);
            changed.push(name);
        }
    });
    return {selection: next, changed};
}

// Apply one user change. Returns the new selection and which other controls had to move.
export function applyChange(contract, selection, name, value) {
    const names = parameterNames(contract);
    if (!names.includes(name) || !validValues(contract, selection, name).includes(value)) {
        return {selection: {...selection}, changed: []};
    }
    let next = {...selection, [name]: value};
    const changed = [];
    if (name === 'mode' && contract.mode_defaults && contract.mode_defaults[value]) {
        for (const other of names) {
            const preferred = contract.mode_defaults[value][other];
            if (other !== 'mode' && preferred !== undefined && preferred !== next[other]) {
                next[other] = preferred;
                changed.push(other);
            }
        }
    }
    const repaired = repair(contract, next, names.indexOf(name));
    return {selection: repaired.selection, changed: [...new Set([...changed, ...repaired.changed])]};
}

export function findVariant(contract, selection) {
    return contract.variants.find(variant => matches(variant, selection, parameterNames(contract))) || null;
}

// What the chosen combination accepts besides the prompt.
export function referenceRules(contract, selection) {
    const variant = findVariant(contract, selection);
    if (!variant) return {images: false, maxImages: 0, minImages: 0, needsMediaId: false};
    const limit = variant.max_images == null ? FALLBACK_MAX_IMAGES : variant.max_images;
    return {
        images: Boolean(variant.supports_images) && limit > 0,
        maxImages: limit,
        minImages: variant.locally_validated_min_images || 0,
        needsMediaId: variant.mode === 'extend' || variant.mode === 'edit',
    };
}

// Why the current form cannot be sent, as a locale key; null when it can.
export function blockingReason(contract, selection, input) {
    const rules = referenceRules(contract, selection);
    if (!findVariant(contract, selection)) return 'studio.block.combination';
    if (!String(input.prompt || '').trim()) return 'studio.block.prompt';
    if (rules.needsMediaId && !String(input.mediaId || '').trim()) return 'studio.block.mediaId';
    const count = (input.images || []).length;
    if (rules.images && count < rules.minImages) return 'studio.block.minImages';
    if (count > rules.maxImages) return 'studio.block.maxImages';
    return null;
}

// The request always names the base model; the server picks the variant from the parameters.
export function buildBody(contract, selection, input) {
    const rules = referenceRules(contract, selection);
    const prompt = String(input.prompt || '').trim();
    const content = [{type: 'text', text: prompt}];
    if (rules.images) {
        for (const url of (input.images || []).slice(0, rules.maxImages)) {
            content.push({type: 'image_url', image_url: {url}});
        }
    }
    if (rules.needsMediaId) {
        content.push({type: 'image_url', image_url: {url: 'extend://' + String(input.mediaId || '').trim()}});
    }
    const parameters = {};
    for (const name of parameterNames(contract)) parameters[name] = selection[name];
    const key = contract.type === 'image' ? 'imageConfig' : 'videoConfig';
    return {
        model: contract.id,
        stream: true,
        messages: [{role: 'user', content: content.length === 1 ? prompt : content}],
        generationConfig: {[key]: parameters},
    };
}

export function maxCount(capacity, type, ceiling = 4) {
    const limit = capacity && capacity[type] && capacity[type].recommended_max_parallel_requests;
    if (!Number.isFinite(limit) || limit <= 0) return 0;
    return Math.min(ceiling, Math.floor(limit));
}
