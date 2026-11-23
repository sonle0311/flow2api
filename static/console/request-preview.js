// Renders the request that Studio sends, for copying into another project.
// The real API key is never an input here: the preview always uses a placeholder.

export const KEY_PLACEHOLDER = '$FLOW2API_API_KEY';
const DATA_URL = /^data:([^;,]+)[^,]*,(.*)$/s;

function abbreviate(value) {
    if (Array.isArray(value)) return value.map(abbreviate);
    if (value && typeof value === 'object') {
        return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, abbreviate(item)]));
    }
    if (typeof value === 'string') {
        const match = DATA_URL.exec(value);
        if (match) return `data:${match[1]};base64,<${Math.ceil(match[2].length * 3 / 4 / 1024)} KB>`;
    }
    return value;
}

export function toJson(body) {
    return JSON.stringify(abbreviate(body), null, 2);
}

export function toCurl(origin, body) {
    const payload = toJson(body).replace(/'/g, `'\\''`);
    return [
        `curl -N ${origin}/v1/chat/completions \\`,
        `  -H "Authorization: Bearer ${KEY_PLACEHOLDER}" \\`,
        `  -H "Content-Type: application/json" \\`,
        `  -d '${payload}'`,
    ].join('\n');
}
