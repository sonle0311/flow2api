const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

function openOptions() {
  const root = path.join(__dirname, '..', 'extension');
  const html = fs.readFileSync(path.join(root, 'options.html'), 'utf8');
  const elements = [];
  const byId = {};
  for (const match of html.matchAll(/<(\w+)\b([^>]*)>/g)) {
    const attrs = Object.fromEntries([...match[2].matchAll(/([\w-]+)="([^"]*)"/g)].map(m => [m[1], m[2]]));
    const el = { dataset: {}, style: {}, value: '', textContent: '', placeholder: attrs.placeholder, listeners: {}, addEventListener(name, fn) { this.listeners[name] = fn; } };
    for (const [key, value] of Object.entries(attrs)) {
      if (key.startsWith('data-')) el.dataset[key.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = value;
    }
    elements.push(el);
    if (attrs.id) byId[attrs.id] = el;
  }
  const ready = [];
  const writes = [];
  const context = vm.createContext({ URL, window: {}, document: {
    documentElement: {}, getElementById: id => byId[id],
    querySelectorAll: selector => elements.filter(el => selector === '[data-i18n]' ? el.dataset.i18n : el.dataset.i18nPlaceholder),
    addEventListener: (name, fn) => { if (name === 'DOMContentLoaded') ready.push(fn); }
  }, chrome: { runtime: {}, storage: { local: {
    get: (defaults, callback) => callback({ ...defaults, routeKey: ' 9223 ', apiKey: ' saved-key ', clientLabel: ' browser ' }),
    set: (settings, callback) => { writes.push(settings); callback(); }
  } } } });
  for (const match of html.matchAll(/<script\s+src="([^"]+)"/g)) {
    vm.runInContext(fs.readFileSync(path.join(root, match[1]), 'utf8'), context, { filename: match[1] });
  }
  ready.forEach(fn => fn());
  return { byId, elements, writes, context };
}

test('options loads its Vietnamese catalog and resolves every declared translation', () => {
  const page = openOptions();
  assert.ok(page.context.window.extensionI18n, 'options.html must load its catalog before options.js');
  for (const el of page.elements) {
    if (el.dataset.i18n) assert.notEqual(el.textContent, el.dataset.i18n);
    if (el.dataset.i18nPlaceholder) assert.notEqual(el.placeholder, el.dataset.i18nPlaceholder);
  }
  assert.equal(page.byId.saveBtn.textContent, 'Lưu');
  assert.equal(page.byId.apiKey.placeholder, 'Khóa API trong bảng quản trị');
});

test('settings load, save and report success in Vietnamese', () => {
  const page = openOptions();
  assert.equal(page.byId.routeKey.value, '9223');
  assert.equal(page.byId.apiKey.value, 'saved-key');
  page.byId.saveBtn.listeners.click();
  assert.equal(page.writes.length, 1);
  assert.match(page.byId.status.textContent, /Đã lưu/);
  page.context.chrome.runtime.lastError = { message: 'storage unavailable' };
  page.byId.saveBtn.listeners.click();
  assert.equal(page.byId.status.textContent, 'Lưu thất bại: storage unavailable');
});

test('invalid WebSocket URL and missing API key show Vietnamese errors without saving', () => {
  const page = openOptions();
  page.byId.serverUrl.value = 'https://example.com';
  page.byId.saveBtn.listeners.click();
  assert.match(page.byId.status.textContent, /WebSocket.*ws:\/\//);
  page.byId.serverUrl.value = 'wss://example.com/captcha_ws';
  page.byId.apiKey.value = ' ';
  page.byId.saveBtn.listeners.click();
  assert.equal(page.byId.status.textContent, 'Vui lòng nhập khóa API Flow2API.');
  assert.equal(page.byId.status.style.color, '#b91c1c');
  assert.equal(page.writes.length, 0);
});
