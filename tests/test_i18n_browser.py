"""Browser checks use local pages and mocked API responses, without real accounts."""

import base64
import json
import re
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def ui_server():
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(ROOT), **kwargs)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path in {"/", "/login", "/manage", "/test"}:
                name = "login" if path == "/" else path[1:]
                self.path = "/static/" + name + ".html"
            elif (
                not path.startswith("/static/")
                and path
                not in {
                    "/extension/options.html",
                    "/extension/options.js",
                    "/extension/locales.json",
                }
            ) or ".." in path.split("/"):
                self.send_error(404)
                return
            super().do_GET()

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def browser_page(ui_server):
    with playwright_api.sync_playwright() as playwright:
        if not Path(playwright.chromium.executable_path).is_file():
            pytest.skip("Playwright Chromium is not installed")
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(locale="en-US")
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route(
            "https://cdn.tailwindcss.com/**",
            lambda route: route.fulfill(
                content_type="application/javascript",
                body="window.tailwind={};document.head.insertAdjacentHTML('beforeend','<style>.hidden{display:none!important}</style>');",
            ),
        )

        def api_response(route):
            path = urlsplit(route.request.url).path
            data = {"success": True}
            status = 200
            if path == "/api/integration/reference":
                from src.core.integration_reference import build_integration_reference
                from src.main import app
                data = build_integration_reference(app)
            elif path == "/api/stats":
                if "/login" in route.request.headers.get("referer", ""):
                    status = 401
                data = {"total_tokens": 1, "active_tokens": 1}
            elif path == "/api/tokens":
                data = [
                    {
                        "id": 1,
                        "email": "account@example.com",
                        "remark": "保存",
                        "is_active": True,
                        "protocol_mode": "protocol",
                        "credits": 100,
                        "image_enabled": True,
                        "video_enabled": True,
                    }
                ]
            elif path == "/api/logs":
                data = [
                    {
                        "id": 1,
                        "operation": "generate_image",
                        "token_email": "account@example.com",
                        "status_code": 200,
                        "progress": 100,
                        "created_at": "2026-10-26T10:00:00Z",
                        "duration": 1.5,
                    }
                ]
            elif path == "/api/logs/1":
                data = {
                    "id": 1,
                    "operation": "generate_image",
                    "status_code": 200,
                    "progress": 100,
                    "created_at": "2026-10-26T10:00:00Z",
                    "duration": 1.5,
                    "request_body": '{"prompt":"保存"}',
                    "response_body": '{"message":"保存"}',
                }
            elif path == "/api/captcha/config":
                data = {"captcha_method": "yescaptcha"}
            elif path == "/api/token-refresh/config":
                data = {"success": True, "config": {
                    "at_auto_refresh_enabled": True,
                    "protocol_refresh_enabled": True,
                    "refresh_interval_minutes": 120,
                }}
            route.fulfill(
                status=status, content_type="application/json", body=json.dumps(data)
            )

        page.route("**/api/**", api_response)
        try:
            yield page, ui_server
            assert errors == []
        finally:
            context.close()
            browser.close()


def open_page(page, address):
    page.goto(address)
    page.wait_for_load_state("networkidle")
    page.wait_for_function(
        "window.I18n && document.querySelector('[data-language-select]').value === I18n.locale"
    )


def test_login_uses_json_post_while_translation_catalog_is_pending(browser_page):
    page, base = browser_page
    pending = []
    navigations = []
    page.route("**/static/locales/login.json", lambda route: pending.append(route))
    page.route(
        "**/api/login",
        lambda route: route.fulfill(
            status=401,
            content_type="application/json",
            body='{"detail":"Invalid credentials"}',
        ),
    )
    page.on(
        "request",
        lambda request: navigations.append(request.url)
        if request.is_navigation_request()
        else None,
    )
    try:
        page.goto(base + "/login", wait_until="domcontentloaded")
        page.locator("#username").fill("review-user")
        page.locator("#password").fill("review-password")
        assert pending
        with page.expect_request("**/api/login") as submitted:
            page.locator("#loginButton").click()
        assert submitted.value.method == "POST"
        assert submitted.value.post_data_json == {
            "username": "review-user",
            "password": "review-password",
        }
        assert page.url == base + "/login"
        assert all("password=" not in url for url in navigations)
    finally:
        for route in pending:
            route.fulfill(
                content_type="application/json",
                body=(ROOT / "static/locales/login.json").read_text(encoding="utf-8"),
            )
    page.wait_for_load_state("networkidle")
    playwright_api.expect(page.locator("#loginButton")).to_have_text("Sign in")


def test_login_never_puts_credentials_in_url_when_javascript_is_disabled(browser_page):
    owner, base = browser_page
    context = owner.context.browser.new_context(java_script_enabled=False)
    try:
        page = context.new_page()
        page.route(
            "**/api/login",
            lambda route: route.fulfill(status=400, content_type="text/html", body=""),
        )
        page.goto(base + "/login")
        page.locator("#username").fill("review-user")
        page.locator("#password").fill("review-password")
        with page.expect_request("**/api/login") as submitted:
            page.locator("#loginButton").click()
        assert submitted.value.method == "POST"
        assert urlsplit(submitted.value.url).query == ""
        assert "password=review-password" in submitted.value.post_data
    finally:
        context.close()


def test_login_language_persists_and_failure_restores_button(browser_page):
    page, base = browser_page
    page.route(
        "**/api/login",
        lambda route: route.fulfill(
            status=401,
            content_type="application/json",
            body='{"detail":"Invalid credentials"}',
        ),
    )
    open_page(page, base + "/login")
    assert page.title() == "Sign in - Flow2API"
    page.locator("#username").fill("保存")
    page.locator("#password").fill("test-password")
    page.locator("[data-language-select]").select_option("zh-CN")
    assert page.locator("#username").input_value() == "保存"
    assert page.locator("#password").input_value() == "test-password"
    assert page.locator("#loginButton").inner_text() == "登录"
    page.locator("[data-language-select]").select_option("en")
    page.locator("#loginButton").click()
    playwright_api.expect(page.locator("#loginButton")).to_have_text("Sign in")
    playwright_api.expect(
        page.get_by_text("Invalid username or password", exact=True)
    ).to_be_visible()
    page.locator("[data-language-select]").select_option("zh-CN")
    assert page.evaluate("localStorage.getItem('flow2api.language')") == "zh-CN"
    page.reload()
    page.wait_for_load_state("networkidle")
    assert page.locator("html").get_attribute("lang") == "zh-CN"
    open_page(page, base + "/test")
    assert page.locator("html").get_attribute("lang") == "zh-CN"


def test_management_switch_preserves_forms_and_log_payload(browser_page):
    page, base = browser_page
    open_page(page, base + "/manage")
    page.wait_for_function("typeof window.openAddModal === 'function'")
    playwright_api.expect(page.locator("#tabTokens")).to_have_text("Token Management")
    page.evaluate("openAddModal()")
    page.locator("#addTokenRemark").fill("保存")
    page.locator("#addTokenGoogleCookies").fill("SID=local-test")
    page.locator("[data-language-select]").select_option("zh-CN")
    assert page.locator("#addTokenRemark").input_value() == "保存"
    assert page.locator("#addTokenGoogleCookies").input_value() == "SID=local-test"
    assert "hidden" not in page.locator("#addModal").get_attribute("class").split()
    page.evaluate("closeAddModal(); switchTab('logs')")
    page.wait_for_selector("#logsTableBody tr")
    page.evaluate("showLogDetail(1)")
    playwright_api.expect(page.locator("#logDetailContent")).to_contain_text(
        '"prompt": "保存"'
    )
    before = page.locator("#logDetailContent pre").first.inner_text()
    page.locator("[data-language-select]").select_option("en")
    assert page.locator("#logDetailContent pre").first.inner_text() == before
    playwright_api.expect(page.locator("#logDetailContent")).to_contain_text(
        "Request data"
    )
    assert "hidden" not in page.locator("#panelLogs").get_attribute("class").split()


def test_log_status_colors_do_not_depend_on_language(browser_page):
    page, base = browser_page
    records = [
        {"id": 1, "status_text": "processing", "status_code": 102},
        {"id": 2, "status_text": "completed", "status_code": 200},
        {"id": 3, "status_text": "failed", "status_code": 500},
        {"id": 4, "status_text": "video_polling", "status_code": 102},
        {"id": 5, "status_text": "", "status_code": 200},
        {"id": 6, "status_text": "", "status_code": 503},
        {"id": 7, "status_text": "unknown", "status_code": None},
        {"id": 8, "status_text": "completed", "status_code": 102},
    ]
    expected = [
        "bg-amber-50 text-amber-700",
        "bg-green-50 text-green-700",
        "bg-red-50 text-red-700",
        "bg-amber-50 text-amber-700",
        "bg-green-50 text-green-700",
        "bg-red-50 text-red-700",
        "bg-gray-100 text-gray-700",
        "bg-green-50 text-green-700",
    ]
    requests = []

    def respond(route):
        requests.append(route.request.url)
        route.fulfill(content_type="application/json", body=json.dumps(records))

    page.route(re.compile(r"/api/logs(?:\?.*)?$"), respond)
    open_page(page, base + "/manage")
    page.evaluate("switchTab('logs')")
    rows = page.locator("#logsTableBody tr")
    playwright_api.expect(rows).to_have_count(len(records))
    for language in ["en", "zh-CN", "en"]:
        page.locator("[data-language-select]").select_option(language)
        for index, classes in enumerate(expected):
            badge = rows.nth(index).locator("td").nth(2).locator("span").first
            for css_class in classes.split():
                playwright_api.expect(badge).to_have_class(
                    re.compile(r"\b" + css_class + r"\b")
                )
    assert len(requests) == 1
    assert page.evaluate("window.allLogs") == records


def test_proxy_validation_hint_follows_language_without_reloading_form(browser_page):
    page, base = browser_page
    requests = []
    page.route("**/api/proxy/test", lambda route: requests.append(route.request))
    open_page(page, base + "/manage")
    page.evaluate("switchTab('settings')")
    page.wait_for_load_state("networkidle")
    page.locator("#cfgAdminUsername").fill("review-name")
    page.locator("#btnTestProxy").click()
    result = page.locator("#proxyTestResult")
    playwright_api.expect(result).to_have_text(
        "Please enter at least one proxy URL first"
    )
    page.locator("[data-language-select]").select_option("zh-CN")
    playwright_api.expect(result).to_have_text("请先填写至少一个代理地址")
    assert page.locator("#cfgAdminUsername").input_value() == "review-name"
    assert requests == []


def test_proxy_results_retranslate_without_repeating_requests(browser_page):
    page, base = browser_page
    diagnostic = "upstream_diagnostic 保存 rpc=as29s"
    requests = []

    def respond(route):
        request = route.request.post_data_json
        requests.append(request)
        if request["proxy_url"].startswith("http:"):
            data = {
                "success": True,
                "message": "Proxy is working",
                "status_code": 200,
                "elapsed_ms": 12,
            }
        else:
            data = {
                "success": False,
                "message": diagnostic,
                "status_code": 502,
                "elapsed_ms": 34,
            }
        route.fulfill(content_type="application/json", body=json.dumps(data))

    page.route("**/api/proxy/test", respond)
    open_page(page, base + "/manage")
    page.evaluate("switchTab('settings')")
    page.wait_for_load_state("networkidle")
    page.locator("#cfgProxyUrl").fill("http://127.0.0.1:18080")
    page.locator("#cfgMediaProxyEnabled").check()
    page.locator("#cfgMediaProxyUrl").fill("socks5://127.0.0.1:18081")
    page.locator("#btnTestProxy").click()
    result = page.locator("#proxyTestResult")
    english = (
        "Request proxy: ✅ Proxy is working (HTTP 200) 12ms | Media proxy: ❌ "
        + diagnostic
        + " (HTTP 502) 34ms"
    )
    chinese = (
        "请求代理: ✅ 代理可用 (HTTP 200) 12ms | 媒体代理: ❌ "
        + diagnostic
        + " (HTTP 502) 34ms"
    )
    playwright_api.expect(result).to_have_text(english)
    page.locator("[data-language-select]").select_option("zh-CN")
    playwright_api.expect(result).to_have_text(chinese)
    page.locator("[data-language-select]").select_option("en")
    playwright_api.expect(result).to_have_text(english)
    assert len(requests) == 2
    assert page.locator("#cfgProxyUrl").input_value() == "http://127.0.0.1:18080"
    assert page.locator("#cfgMediaProxyUrl").input_value() == "socks5://127.0.0.1:18081"


@pytest.mark.parametrize(
    ("action", "network_error", "english", "chinese", "diagnostic"),
    [
        ("add", False, "Add failed", "添加失败", "Invalid proxy URL"),
        ("edit", False, "Update failed", "更新失败", "Invalid proxy URL"),
        ("add", True, "Add failed", "添加失败", "Failed to fetch"),
    ],
)
def test_account_failure_toasts_follow_language(
    browser_page, action, network_error, english, chinese, diagnostic
):
    page, base = browser_page

    def respond(route):
        if route.request.method not in {"POST", "PUT"}:
            route.fallback()
        elif network_error:
            route.abort("failed")
        else:
            route.fulfill(
                status=400,
                content_type="application/json",
                body=json.dumps({"detail": diagnostic}),
            )

    page.route(re.compile(r"/api/tokens(?:/\d+)?$"), respond)
    open_page(page, base + "/manage")
    if action == "add":
        page.evaluate("openAddModal()")
    else:
        page.wait_for_function("document.querySelector('#tokenTableBody tr') !== null")
        page.evaluate("openEditModal(1)")
    page.locator("#" + action + "TokenGoogleCookies").fill("SID=review-placeholder")
    page.locator("#" + action + "TokenLoginAccount").fill("review@example.com")
    page.locator("#" + action + "TokenBtn").click()
    toast = page.locator("body > div.fixed.bottom-4")
    playwright_api.expect(toast).to_have_text(english + ": " + diagnostic)
    page.locator("[data-language-select]").select_option("zh-CN")
    playwright_api.expect(toast).to_have_text(chinese + ": " + diagnostic)
    playwright_api.expect(page.locator("#" + action + "TokenBtn")).to_be_enabled()


def test_historical_log_messages_localize_without_changing_raw_payloads(browser_page):
    page, base = browser_page
    diagnostic = "Flow frontend RPC rejected: rpc=as29s, code=[5]"
    nested_error = "生成失败: 视频生成成功但获取媒体地址失败: " + diagnostic
    model = "gemini-3.1-flash-image-landscape-4k"
    tier_error = "当前模型需要 Ult 账号，但没有可用的 Ult 账号: " + model
    records = [
        {"id": 11, "operation": "generate_video", "error_summary": nested_error},
        {"id": 12, "operation": "generate_image", "error_summary": tier_error},
        {"id": 13, "operation": "custom_operation", "error_summary": "保存"},
    ]
    for record in records:
        record.update(
            status_code=500,
            status_text="failed",
            progress=24,
            request_body=json.dumps(
                {"prompt": "生成失败: 保持原文"}, ensure_ascii=False
            ),
            response_body=json.dumps(
                {"error": {"message": record["error_summary"]}}, ensure_ascii=False
            ),
        )

    def respond(route):
        path = urlsplit(route.request.url).path
        data = (
            records
            if path == "/api/logs"
            else next(
                record for record in records if path == "/api/logs/" + str(record["id"])
            )
        )
        route.fulfill(content_type="application/json", body=json.dumps(data))

    page.route(re.compile(r"/api/logs(?:/\d+)?(?:\?.*)?$"), respond)
    open_page(page, base + "/manage")
    page.evaluate("switchTab('logs')")
    rows = page.locator("#logsTableBody tr")
    playwright_api.expect(rows).to_have_count(3)
    playwright_api.expect(page.locator("#panelLogs thead th").first).to_have_text(
        "Operation"
    )
    playwright_api.expect(rows.first.locator("td").first).to_have_text("Generate video")
    playwright_api.expect(rows.first.locator("button")).to_have_text("Details")
    expected = (
        "Generation failed: Video generation succeeded, but the media URL could not be retrieved: "
        + diagnostic
    )
    assert (
        rows.first.locator("td").nth(5).locator("div").get_attribute("title")
        == expected
    )
    assert rows.nth(1).locator("td").nth(5).locator("div").get_attribute("title") == (
        "This model requires the Ult tier, but no Ult account is available: " + model
    )
    playwright_api.expect(rows.nth(2).locator("td").first).to_have_text(
        "custom_operation"
    )
    playwright_api.expect(rows.nth(2).locator("td").nth(5)).to_have_text("保存")
    assert page.evaluate("window.allLogs[0].error_summary") == nested_error
    assert rows.first.locator("td").first.get_attribute("title") == "generate_video"
    rows.first.locator("button").click()
    error = page.locator("#logDetailContent [data-i18n-error]")
    playwright_api.expect(error).to_have_text(expected)
    raw_payloads = page.locator("#logDetailContent pre").all_text_contents()
    assert any(nested_error in payload for payload in raw_payloads)
    assert any("生成失败: 保持原文" in payload for payload in raw_payloads)
    page.locator("[data-language-select]").select_option("zh-CN")
    playwright_api.expect(error).to_have_text(nested_error)
    playwright_api.expect(rows.first.locator("button")).to_have_text("详情")
    playwright_api.expect(rows.first.locator("td").first).to_have_text("生成视频")
    assert page.locator("#logDetailContent pre").all_text_contents() == raw_payloads


def test_model_switch_preserves_uploads_and_inflight_generation(browser_page):
    page, base = browser_page
    page.route(
        "**/v1/models",
        lambda route: route.fulfill(
            content_type="application/json",
            body='{"data":[{"id":"gemini-3.1-flash-image","description":"Image generation"}]}',
        ),
    )
    pending = []
    page.route("**/v1/chat/completions", lambda route: pending.append(route))
    open_page(page, base + "/test")
    page.wait_for_selector('.model-item[data-model="gemini-3.1-flash-image"]')
    page.locator('.model-item[data-model="gemini-3.1-flash-image"]').click()
    page.locator("#promptInput").fill("保存")
    page.locator("#apiKey").fill("local-test-key")
    image = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jNekAAAAASUVORK5CYII="
    )
    page.locator("#imageFileInput").set_input_files(
        {"name": "image.png", "mimeType": "image/png", "buffer": image}
    )
    page.wait_for_selector(".image-preview-item")
    page.locator("[data-language-select]").select_option("zh-CN")
    assert page.locator("#promptInput").input_value() == "保存"
    assert page.locator(".image-preview-item").count() == 1

    assert page.locator(".model-item.active").count() == 1
    page.locator("#btnGenerate").click()
    page.wait_for_function("document.getElementById('btnGenerate').disabled")
    page.locator("[data-language-select]").select_option("en")
    playwright_api.expect(page.locator("#btnGenerate")).to_have_text("⏳ Generating...")
    assert page.locator("#btnGenerate").is_disabled()
    page.wait_for_timeout(50)
    assert len(pending) == 1
    assert pending[0].request.headers["accept-language"] == "zh-CN"
    assert (
        pending[0].request.post_data_json["messages"][0]["content"][0]["text"] == "保存"
    )
    events = [
        {"choices": [{"delta": {"reasoning_content": "初始化生成环境...\n"}}]},
        {"choices": [{"delta": {"content": "保存"}}]},
    ]
    pending[0].fulfill(
        content_type="text/event-stream",
        body="".join("data: " + json.dumps(event) + "\n\n" for event in events)
        + "data: [DONE]\n\n",
    )
    playwright_api.expect(page.locator("#btnGenerate")).to_be_enabled()
    playwright_api.expect(page.locator("#outputResult pre")).to_have_text("保存")
    playwright_api.expect(page.locator("#outputLog")).to_contain_text(
        "Preparing generation environment..."
    )
    assert page.locator(".image-preview-item").count() == 1


def test_language_switch_works_when_browser_storage_is_disabled(browser_page):
    page, base = browser_page
    page.add_init_script(
        "Object.defineProperty(window, 'localStorage', {get() {throw new DOMException('Disabled', 'SecurityError')}})"
    )
    open_page(page, base + "/login")
    assert page.locator("html").get_attribute("lang") == "en"
    page.locator("[data-language-select]").select_option("zh-CN")
    playwright_api.expect(page.locator("#loginButton")).to_have_text("登录")


def test_extension_language_preserves_settings_and_translates_status(browser_page):
    page, base = browser_page
    page.add_init_script("""
        const settings = {uiLanguage:'en', routeKey:'保存'};
        Object.defineProperty(window, 'chrome', {value: {
            runtime: {lastError: null},
            storage: {local: {
                get(defaults, callback) {queueMicrotask(() => callback({...defaults,...settings}));},
                set(values, callback) {Object.assign(settings,values); if(callback) queueMicrotask(callback);}
            }}
        }});
    """)
    page.goto(base + "/extension/options.html")
    page.wait_for_load_state("networkidle")
    playwright_api.expect(page.locator("#saveBtn")).to_have_text("Save")
    assert page.locator("#routeKey").input_value() == "保存"

    page.locator("#saveBtn").click()
    playwright_api.expect(page.locator("#status")).to_have_text(
        "Enter your Flow2API API key."
    )
    page.locator("#language").select_option("zh-CN")
    assert page.locator("#routeKey").input_value() == "保存"
    playwright_api.expect(page.locator("#status")).to_have_text(
        "请填写 Flow2API API Key。"
    )
    page.locator("#apiKey").fill("local-test-key")
    page.locator("#saveBtn").click()
    playwright_api.expect(page.locator("#status")).to_have_text(
        "已保存，后台连接会自动重连。"
    )
    page.locator("#language").select_option("en")
    playwright_api.expect(page.locator("#status")).to_have_text(
        "Settings saved. The background connection will reconnect automatically."
    )
    assert page.locator("#routeKey").input_value() == "保存"


@pytest.mark.parametrize("name", ["login", "manage", "test"])
def test_vietnamese_selection_persists_and_switches_back(browser_page, name):
    page, base = browser_page
    page.add_init_script("if (!localStorage.getItem('flow2api.language')) localStorage.setItem('flow2api.language', 'vi-VN')")
    open_page(page, base + "/" + name)
    assert page.locator("html").get_attribute("lang") == "vi"
    selector = page.locator("[data-language-select]")
    assert selector.input_value() == "vi"
    assert selector.locator('option[value="vi"]').inner_text() == "Tiếng Việt"
    catalog = json.loads((ROOT / f"static/locales/{name}.json").read_text(encoding="utf-8"))
    label = page.locator("[data-i18n]").filter(has_text=re.compile(".+")).first
    source = label.get_attribute("data-i18n")
    field = {"login": "#username", "manage": "#cfgAdminUsername", "test": "#promptInput"}[name]
    if name == "manage":
        page.evaluate("switchTab('settings')")
        page.wait_for_load_state("networkidle")
    page.locator(field).fill("Giữ nguyên 保存")
    for language in ["en", "zh-CN", "vi", "en", "vi"]:
        selector.select_option(language)
        assert page.locator(field).input_value() == "Giữ nguyên 保存"
        assert page.evaluate("I18n.locale") == language
        assert page.evaluate("localStorage.getItem('flow2api.language')") == language
        assert label.inner_text() == catalog[language][source]
    page.reload()
    page.wait_for_load_state("networkidle")
    assert page.locator("html").get_attribute("lang") == "vi"


def test_vietnamese_messages_translate_back_from_all_aliases(browser_page):
    page, base = browser_page
    open_page(page, base + "/login")
    catalog = json.loads((ROOT / "static/locales/backend.json").read_text(encoding="utf-8"))
    for source, params in [("Token已启用", {}), ("生成失败: {error}", {"error": "raw 保存 rpc=as29s"})]:
        for original in ("zh-CN", "en", "vi"):
            text = catalog[original][source]
            for key, value in params.items():
                text = text.replace("{" + key + "}", value)
            for target in ("vi", "en", "zh-CN"):
                page.evaluate("language => I18n.setLanguage(language)", target)
                expected = catalog[target][source]
                for key, value in params.items():
                    expected = expected.replace("{" + key + "}", value)
                assert page.evaluate("text => I18n.translateError(text)", text) == expected


def test_extension_normalizes_vietnamese_and_persists_selection(browser_page):
    page, base = browser_page
    page.add_init_script("""
        window.testSettings = {uiLanguage:'vi-VN', routeKey:'Giữ nguyên 保存'};
        Object.defineProperty(window, 'chrome', {value: {
            runtime: {lastError: null},
            storage: {local: {
                get(defaults, callback) {queueMicrotask(() => callback({...defaults,...window.testSettings}));},
                set(values, callback) {Object.assign(window.testSettings,values); if(callback) queueMicrotask(callback);}
            }}
        }});
    """)
    page.goto(base + "/extension/options.html")
    page.wait_for_load_state("networkidle")
    catalog = json.loads((ROOT / "extension/locales.json").read_text(encoding="utf-8"))
    assert page.locator("html").get_attribute("lang") == "vi"
    page.locator("#saveBtn").click()
    for language in ["vi", "en", "zh-CN", "vi"]:
        page.locator("#language").select_option(language)
        playwright_api.expect(page.locator("#status")).to_have_text(catalog[language]["请填写 Flow2API API Key。"])
        assert page.locator("#routeKey").input_value() == "Giữ nguyên 保存"
        assert page.evaluate("window.testSettings.uiLanguage") == language


def test_integration_guide_tab_copies_complete_instructions_without_secrets(browser_page):
    page, base = browser_page
    open_page(page, base + "/manage")
    page.locator("[data-language-select]").select_option("vi")
    page.evaluate("""() => {
        document.getElementById('cfgCurrentAPIKey').value = 'private-api-key-do-not-copy';
        Object.defineProperty(navigator, 'clipboard', {configurable: true, value: {
            writeText: async text => { window.copiedIntegrationGuide = text; }
        }});
    }""")
    requests = []
    page.on("request", lambda request: requests.append(urlsplit(request.url).path))
    page.locator("#tabIntegration").click(timeout=3000)
    playwright_api.expect(page.locator("#panelIntegration")).to_be_visible()
    playwright_api.expect(page.locator("#panelTokens")).to_be_hidden()
    guide = page.locator("#integrationGuide").input_value()
    assert base in guide
    for contract in ("/v1/models", "/v1/chat/completions", "FLOW2API_API_KEY",
                     "Authorization: Bearer", "image_url", "reasoning_content",
                     "[DONE]", "generateContent", "inlineData"):
        assert contract in guide
    examples = [json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", guide, re.S)]
    assert examples[0]["stream"] is False
    assert examples[0]["messages"][0]["role"] == "user"
    assert examples[1][1]["type"] == "image_url"
    assert examples[2]["contents"][0]["parts"][0]["text"] == "<PROMPT>"
    assert "private-api-key-do-not-copy" not in guide
    page.locator("#copyIntegrationGuide").click()
    assert page.evaluate("window.copiedIntegrationGuide") == guide
    assert not any(path.startswith("/api/admin/") or path.endswith("/chat/completions") for path in requests)
    page.locator("#tabTokens").click()
    playwright_api.expect(page.locator("#panelIntegration")).to_be_hidden()


def test_integration_guide_preserves_server_and_handles_invalid_urls(browser_page):
    page, base = browser_page
    open_page(page, base + "/manage")
    page.locator("#tabIntegration").click(timeout=3000)
    server = page.locator("#integrationServerUrl")
    server.fill("https://api.example.com/flow/")
    for locale in ("vi", "zh-CN", "en"):
        page.locator("[data-language-select]").select_option(locale)
        assert server.input_value() == "https://api.example.com/flow/"
        guide = page.locator("#integrationGuide").input_value()
        assert "https://api.example.com/flow/v1" in guide
        assert "https://api.example.com/flow//v1" not in guide
        assert not re.search(r"\bintegration\.(title|agentTask|connectionHelp|resultHelp)\b", guide)
    for invalid in ("javascript:alert(1)", "https://user:pass@example.com", "https://example.com?key=secret"):
        server.fill(invalid)
        playwright_api.expect(page.locator("#copyIntegrationGuide")).to_be_disabled()
        assert page.locator("#integrationGuide").input_value() == ""
        assert server.get_attribute("aria-invalid") == "true"
    server.fill(base)
    playwright_api.expect(page.locator("#copyIntegrationGuide")).to_be_enabled()
    assert server.get_attribute("aria-invalid") == "false"


def test_integration_clipboard_fallback_and_manual_recovery(browser_page):
    page, base = browser_page
    open_page(page, base + "/manage")
    page.locator("#tabIntegration").click(timeout=3000)
    page.evaluate("""() => {
        Object.defineProperty(navigator, 'clipboard', {configurable: true, value: undefined});
        document.execCommand = command => {
            window.fallbackGuide = document.activeElement.value;
            return command === 'copy';
        };
    }""")
    page.locator("#copyIntegrationGuide").click()
    assert page.evaluate("window.fallbackGuide") == page.locator("#integrationGuide").input_value()
    page.evaluate("document.execCommand = () => false")
    page.locator("#copyIntegrationGuide").click()
    assert page.locator("#integrationCopyStatus").inner_text()
    page.locator("#selectIntegrationGuide").click()
    selection = page.locator("#integrationGuide").evaluate("el => el.selectionEnd - el.selectionStart")
    assert selection == len(page.locator("#integrationGuide").input_value())


def test_integration_reference_lists_every_endpoint_model_and_filters(browser_page):
    from src.services.generation_handler import MODEL_CONFIG
    page, base = browser_page
    open_page(page, base + "/manage#integration")
    playwright_api.expect(page.locator("#copyIntegrationGuide")).to_be_enabled()
    guide = page.locator("#integrationGuide").input_value()
    for model_id in MODEL_CONFIG:
        assert model_id in guide
    for path in ("/api/tokens/import", "/api/cache/config", "/api/plugin/check-tokens", "/captcha_ws", "/v1/models/aliases"):
        assert path in guide
    assert "ChatCompletionRequest" in guide
    assert "ADMIN" in guide or "admin_session" in guide
    assert page.locator("#integrationModelRows tr").count() == len(MODEL_CONFIG)
    page.locator("#integrationReferenceSearch").fill("/api/cache")
    assert page.locator("#integrationEndpointRows tr").count() > 0
    assert all("/api/cache" in line for line in page.locator("#integrationEndpointRows tr").all_text_contents())
    page.locator("#integrationReferenceSearch").fill("gemini-3.1-flash-image-landscape-2k")
    assert page.locator("#integrationModelRows tr").count() == 1
    assert page.locator("#integrationGuide").input_value() == guide


def test_integration_reference_failure_disables_partial_copy_and_can_retry(browser_page):
    page, base = browser_page
    page.route("**/api/integration/reference", lambda route: route.fulfill(status=503, json={"detail": "unavailable"}))
    open_page(page, base + "/manage#integration")
    playwright_api.expect(page.locator("#copyIntegrationGuide")).to_be_disabled()
    assert page.locator("#integrationGuide").input_value() == ""
    assert page.locator("#integrationReferenceStatus").inner_text()
    page.unroute("**/api/integration/reference")
    page.locator("#reloadIntegrationReference").click()
    playwright_api.expect(page.locator("#copyIntegrationGuide")).to_be_enabled()
    assert "/api/tokens/import" in page.locator("#integrationGuide").input_value()


@pytest.mark.parametrize("enabled", [False, True])
def test_background_refresh_toggle_uses_its_own_setting(browser_page, enabled):
    page, base = browser_page
    page.route("**/api/token-refresh/config", lambda route: route.fulfill(json={
        "success": True, "config": {"at_auto_refresh_enabled": True,
        "protocol_refresh_enabled": enabled, "refresh_interval_minutes": 47}}))
    open_page(page, base + "/manage")
    assert page.locator("#atAutoRefreshToggle").is_checked() is enabled
    assert page.locator("#globalRefreshIntervalMinutes").input_value() == "47"


def test_background_refresh_toggle_persists_after_reload(browser_page):
    page, base = browser_page
    state = {"enabled": False}
    writes = []
    page.route("**/api/token-refresh/config", lambda route: route.fulfill(json={
        "success": True, "config": {"at_auto_refresh_enabled": True,
        "protocol_refresh_enabled": state["enabled"], "refresh_interval_minutes": 30}}))
    def save(route):
        body = route.request.post_data_json
        writes.append(body)
        state["enabled"] = body["enabled"]
        route.fulfill(json={"success": True})
    page.route("**/api/token-refresh/enabled", save)
    open_page(page, base + "/manage")
    toggle = page.locator("#atAutoRefreshToggle")
    for enabled in (True, False):
        toggle.set_checked(enabled)
        page.wait_for_load_state("networkidle")
        assert writes[-1] == {"enabled": enabled}
        page.reload()
        page.wait_for_load_state("networkidle")
        assert toggle.is_checked() is enabled


@pytest.mark.parametrize("failure", ["network", "rejected", "http"])
def test_background_refresh_toggle_rolls_back_failed_save(browser_page, failure):
    page, base = browser_page
    page.route("**/api/token-refresh/config", lambda route: route.fulfill(json={
        "success": True, "config": {"at_auto_refresh_enabled": True,
        "protocol_refresh_enabled": True, "refresh_interval_minutes": 30}}))
    def save(route):
        if failure == "network":
            route.abort("failed")
        else:
            route.fulfill(status=500 if failure == "http" else 200,
                          json={"success": False, "detail": "Unable to save"})
    page.route("**/api/token-refresh/enabled", save)
    open_page(page, base + "/manage")
    toggle = page.locator("#atAutoRefreshToggle")
    toggle.uncheck()
    playwright_api.expect(toggle).to_be_checked()
    playwright_api.expect(toggle).to_be_enabled()


def test_authenticated_model_catalog_shows_all_current_image_and_video_models(browser_page):
    from src.api.routes import _get_openai_model_catalog
    page, base = browser_page
    catalog = _get_openai_model_catalog()
    page.route("**/v1/models", lambda route: route.fulfill(json={"object": "list", "data": catalog}))
    open_page(page, base + "/test")
    page.locator("#apiKey").fill("test-api-key")
    page.locator("#apiKey").dispatch_event("change")
    page.wait_for_load_state("networkidle")
    expected = {model["id"] for model in catalog}
    playwright_api.expect(page.locator(".model-item[data-model]")).to_have_count(len(expected))
    for language in ("en", "vi", "zh-CN"):
        page.locator("[data-language-select]").select_option(language)
        rendered = page.locator(".model-item[data-model]").evaluate_all("items => items.map(item => item.dataset.model)")
        assert set(rendered) == expected
        assert len(rendered) == len(expected)
    page.locator('.model-item[data-model="veo-3.1-fast-4s-landscape"]').click()
    assert page.evaluate("STATE.selectedModel") == "veo-3.1-fast-4s-landscape"
    assert page.evaluate("STATE.modelConfig.type") == "video"


def test_model_sidebar_keeps_legacy_and_unknown_ids_and_omni_image_inputs(browser_page):
    page, base = browser_page
    ids = ["veo_3_1_t2v_fast", "veo_3_1_interpolation_lite_8s", "omni-1.1-flash-4s-landscape",
           "veo-3.1-fast-extend-8s-landscape", "future-image-model", "future-video-model"]
    page.route("**/v1/models", lambda route: route.fulfill(json={"data": [{"id": model, "description": model} for model in ids]}))
    open_page(page, base + "/test")
    page.locator("#apiKey").fill("test-api-key")
    page.evaluate("loadModels()")
    assert page.locator(".model-item[data-model]").count() == len(ids)
    assert set(page.locator(".model-item[data-model]").evaluate_all("items => items.map(item => item.dataset.model)")) == set(ids)
    page.locator('.model-item[data-model="omni-1.1-flash-4s-landscape"]').click()
    playwright_api.expect(page.locator("#imageUploadGroup")).to_be_visible()
    assert page.evaluate("STATE.modelConfig.maxImages") == 3
    assert page.evaluate("getModelMeta('veo_3_1_interpolation_lite_8s').minImages") == 2
    assert page.evaluate("getModelMeta('veo-3.1-fast-r2v-8s-landscape').minImages") == 1
