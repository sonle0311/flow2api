// Network access for the console. Admin calls use the session cookie; generation uses the
// API key, which is held in this module's memory only and never stored or logged.

let apiKey = '';
let language = 'en';

export function setLanguage(value) { language = value; }

export class ApiError extends Error {
    constructor(message, status) { super(message); this.status = status; }
}

export async function adminRequest(path, options = {}) {
    const response = await fetch(path, {
        credentials: 'same-origin', cache: 'no-store', ...options,
        headers: {'Accept-Language': language, ...(options.body ? {'Content-Type': 'application/json'} : {}), ...options.headers},
    });
    if (response.status === 401) {
        window.location.assign('/login');
        throw new ApiError('unauthorized', 401);
    }
    if (!response.ok) throw new ApiError(await readError(response), response.status);
    return response.json();
}

async function readError(response) {
    const text = await response.text().catch(() => '');
    try {
        const data = JSON.parse(text);
        const detail = data.error?.message || data.detail || data.message;
        if (typeof detail === 'string' && detail) return detail;
    } catch (_) { /* Not JSON: fall through to the status line. */ }
    return `HTTP ${response.status}`;
}

export function loadReference() { return adminRequest('/api/integration/reference'); }

export async function loadApiKey() {
    const config = await adminRequest('/api/admin/config');
    apiKey = typeof config.api_key === 'string' ? config.api_key : '';
    return Boolean(apiKey);
}

export async function loadHealth() {
    try { return (await fetch('/health', {cache: 'no-store'})).ok; } catch (_) { return false; }
}

export function signOut() { return adminRequest('/api/admin/logout', {method: 'POST'}); }

// Incremental parser for the chat-completions event stream. Pure: feed text, read state.
export function createStreamParser() {
    const state = {content: '', progress: '', done: false};
    let buffer = '';
    function consume(frame) {
        const data = frame.split(/\r?\n/).filter(line => line.startsWith('data:'))
            .map(line => line.slice(5).replace(/^ /, '')).join('\n').trim();
        if (!data) return;
        if (data === '[DONE]') { state.done = true; return; }
        let parsed;
        try { parsed = JSON.parse(data); } catch (_) { throw new ApiError('invalid_stream'); }
        if (parsed.error) throw new ApiError(parsed.error.message || JSON.stringify(parsed.error));
        for (const choice of parsed.choices || []) {
            const delta = choice.delta || {};
            if (typeof delta.reasoning_content === 'string' && delta.reasoning_content.trim()) {
                state.progress = delta.reasoning_content.trim().split(/\r?\n/).pop();
            }
            if (typeof delta.content === 'string') state.content += delta.content;
        }
    }
    return {
        state,
        push(text) {
            buffer += text;
            let separator;
            while (!state.done && (separator = /\r?\n\r?\n/.exec(buffer))) {
                const frame = buffer.slice(0, separator.index);
                buffer = buffer.slice(separator.index + separator[0].length);
                consume(frame);
            }
        },
    };
}

// Results arrive as markdown images or <video> tags inside the message content.
export function extractMedia(content) {
    const media = [];
    for (const match of String(content).matchAll(/!\[[^\]]*\]\(([^)\s]+)\)/g)) media.push({kind: 'image', url: match[1]});
    for (const match of String(content).matchAll(/<video[^>]+src=['"]([^'"]+)['"]/gi)) media.push({kind: 'video', url: match[1]});
    return media.filter(item => /^(https?:\/\/|\/|data:(image|video)\/)/i.test(item.url));
}

export async function streamGeneration(body, {signal, onProgress} = {}) {
    if (!apiKey) throw new ApiError('missing_api_key');
    const response = await fetch('/v1/chat/completions', {
        method: 'POST', signal, body: JSON.stringify(body),
        headers: {'Authorization': `Bearer ${apiKey}`, 'Content-Type': 'application/json', 'Accept-Language': language},
    });
    if (!response.ok) throw new ApiError(await readError(response), response.status);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    const parser = createStreamParser();
    try {
        while (!parser.state.done) {
            const {done, value} = await reader.read();
            if (done) break;
            parser.push(decoder.decode(value, {stream: true}));
            if (onProgress && parser.state.progress) onProgress(parser.state.progress);
        }
        parser.push(decoder.decode() + '\n\n');
    } finally {
        await reader.cancel().catch(() => {});
    }
    if (!parser.state.done) throw new ApiError('stream_ended');
    const media = extractMedia(parser.state.content);
    if (!media.length) throw new ApiError('no_result');
    return media;
}
