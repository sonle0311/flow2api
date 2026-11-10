"""Execute the shared script against a fully local synthetic browser API."""

import unittest

from playwright.async_api import async_playwright

from src.services.recaptcha_runtime import TRUSTED_RECAPTCHA_HOOK_SOURCE, build_recaptcha_execute_script


class RecaptchaFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)
        self.context = await self.browser.new_context()
        await self.context.route("**/*", lambda route: route.abort())
        self.page = await self.context.new_page()
        await self.page.set_content("<html><head><title>Local</title></head><body>Flow content</body></html>")
        await self.page.evaluate("""() => {
            const nativeTimeout = window.setTimeout;
            window.setTimeout = (fn, delay, ...args) => nativeTimeout(fn, delay === 250 ? 0 : delay, ...args);
        }""")

    async def asyncTearDown(self):
        await self.browser.close()
        await self.playwright.stop()

    async def run_script(self, setup, hook=True):
        if hook:
            await self.page.evaluate(TRUSTED_RECAPTCHA_HOOK_SOURCE)
        await self.page.evaluate(setup)
        return await self.page.evaluate(build_recaptcha_execute_script("site-key", "IMAGE_GENERATION", 40))

    async def test_no_bound_capture_uses_direct_execute_without_render(self):
        result = await self.run_script("""() => {
            window.grecaptcha = {enterprise: {
                execute(key, options) {
                    if (this !== grecaptcha.enterprise) throw Error('missing receiver');
                    return Promise.resolve(key + ':' + options.action);
                },
                render() { throw Error('render should not be needed'); }
            }};
        }""")
        self.assertEqual(result, {"ok": True, "token": "site-key:IMAGE_GENERATION"})

    async def test_widget_fallback_uses_empty_container_and_cleans_it(self):
        result = await self.run_script("""() => {
            window.calls = [];
            window.grecaptcha = {enterprise: {
                execute(key, options) {
                    calls.push({key, action: options.action});
                    if (key === 'site-key') throw Error('widget required');
                    return Promise.resolve('widget-token:' + options.action);
                },
                render(element, options) {
                    if (element.childNodes.length) throw Error('placeholder must be empty');
                    if (!element.isConnected) throw Error('placeholder must be attached');
                    element.appendChild(document.createElement('iframe'));
                    return 7;
                },
                reset(id) { window.resetId = id; }
            }};
        }""")
        self.assertEqual(result, {"ok": True, "token": "widget-token:IMAGE_GENERATION"})
        self.assertEqual(await self.page.evaluate("calls"), [
            {"key": "site-key", "action": "IMAGE_GENERATION"},
            {"key": 7, "action": "IMAGE_GENERATION"},
        ])
        self.assertEqual(await self.page.locator("iframe").count(), 0)
        self.assertEqual(await self.page.evaluate("window.resetId"), 7)

    async def test_widget_timeout_cleans_container_and_reports_failure(self):
        result = await self.run_script("""() => {
            window.grecaptcha = {enterprise: {
                execute(key) { if (key === 'site-key') throw Error('widget required'); return new Promise(() => {}); },
                render(element) { element.appendChild(document.createElement('iframe')); return 8; },
                reset(id) { window.resetId = id; }
            }};
        }""")
        self.assertFalse(result["ok"])
        self.assertIn("execute timeout", result["error"])
        self.assertEqual(await self.page.locator("iframe").count(), 0)
        self.assertEqual(await self.page.evaluate("window.resetId"), 8)

    async def test_v3_execute_without_render_remains_supported(self):
        result = await self.run_script("""() => {
            window.grecaptcha = {enterprise: {execute(key, options) { return Promise.resolve(options.action); }}};
        }""")
        self.assertEqual(result, {"ok": True, "token": "IMAGE_GENERATION"})

    async def test_no_capture_public_wrapper_keeps_requested_action_with_guard(self):
        result = await self.run_script("""() => {
            const original = (key, options) => Promise.resolve(options.action);
            window.grecaptcha = {enterprise: {execute(key, options) {
                return original(key, Object.assign({}, options, {action: 'extension_hijack_detected'}));
            }}};
        }""")
        self.assertEqual(result, {"ok": True, "token": "IMAGE_GENERATION"})

    async def test_unprotected_hijack_wrapper_still_fails_closed(self):
        result = await self.run_script("""() => {
            window.grecaptcha = {enterprise: {execute(key, options) {
                return Promise.resolve('extension_hijack_detected');
            }}};
        }""", hook=False)
        self.assertFalse(result["ok"])
        self.assertIn("action guard", result["error"])
