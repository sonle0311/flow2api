"""Managed browser UI uses mocked sessions; never launches a real login window."""
import json

import pytest
from test_i18n_browser import browser_page, ui_server, open_page


def session(status="not_configured", **updates):
    return {"token_id": 1, "enabled": status != "not_configured", "status": status,
            "browser_open": False, "last_sync_at": None, "error_code": None,
            "interval_minutes": 30, **updates}


def mock_sessions(page, initial=None):
    state = {"session": initial or session(), "requests": [], "fail": False}
    def respond(route):
        state["requests"].append((route.request.method, route.request.url.rsplit("/", 1)[-1]))
        if state["fail"]:
            route.fulfill(status=500, json={"detail": "SECRET_COOKIE_SHOULD_NEVER_RENDER"})
        else:
            if route.request.url.endswith("/login"):
                state["session"] = session("awaiting_login", browser_open=True)
            elif route.request.url.endswith("/stop"):
                state["session"] = session("stopped", enabled=False)
            route.fulfill(json={"success": True, "session": state["session"]})
    page.route("**/browser-session**", respond)
    return state


def mock_browser_account_creation(page):
    state = {"accounts": [], "posts": [], "fail": False, "pending": []}
    page.route("**/api/tokens", lambda route: route.fulfill(json=state["accounts"]))
    def create(route):
        state["posts"].append(route.request.post_data_json)
        if state["fail"]:
            route.fulfill(status=422, json={"detail": "SECRET_NOT_FOR_UI"})
            return
        state["accounts"] = [{"id": 7, "email": "first@example.com", "login_account": "first@example.com",
                              "st": "browser-pending-fixture", "is_active": False}]
        route.fulfill(json={"success": True, "created": True,
                            "session": session("awaiting_login", token_id=7, browser_open=True)})
    page.route("**/api/browser-sessions/accounts", create)
    page.route("**/api/tokens/7/browser-session", lambda route: route.fulfill(json={
        "success": True, "session": session("awaiting_login", token_id=7, browser_open=True)}))
    return state


@pytest.mark.parametrize("locale,label,pending", [
    ("en", "Add account using browser", "Awaiting sign-in"),
    ("vi", "Thêm tài khoản bằng trình duyệt", "Chờ đăng nhập"),
    ("zh-CN", "通过浏览器添加账号", "等待登录"),
])
def test_first_account_can_start_browser_login_without_cookies(browser_page, locale, label, pending):
    page, url = browser_page
    state = mock_browser_account_creation(page)
    open_page(page, url + "/manage")
    page.locator("[data-language-select]").select_option(locale)
    assert page.locator("#tokenTableBody [data-browser-add]").count() == 1
    assert page.locator("#addAccountWithBrowser").inner_text() == label
    page.locator("#tokenTableBody [data-browser-add]").click()
    assert page.locator("#managedBrowserAddDialog").is_visible()
    assert state["posts"] == []
    page.locator("#managedBrowserAddEmail").fill("first@example.com")
    page.locator("#managedBrowserAddSubmit").click()
    page.locator("#managedBrowserAccount").filter(has_text="first@example.com").wait_for()
    assert state["posts"] == [{"email": "first@example.com"}]
    assert not page.locator("#managedBrowserAddDialog").is_visible()
    assert page.locator("#managedBrowserDialog").is_visible()
    assert pending in page.locator("#tokenTableBody").inner_text()
    assert page.locator("#tokenTableBody [data-browser-add]").count() == 0


def test_first_account_creation_failure_is_safe_and_retryable(browser_page):
    page, url = browser_page
    state = mock_browser_account_creation(page)
    state["fail"] = True
    open_page(page, url + "/manage")
    page.locator("#addAccountWithBrowser").click()
    page.locator("#managedBrowserAddEmail").fill("first@example.com")
    page.locator("#managedBrowserAddSubmit").click()
    page.wait_for_function("!document.getElementById('managedBrowserAddSubmit').disabled")
    assert page.locator("#managedBrowserAddError").inner_text()
    assert "SECRET_NOT_FOR_UI" not in page.locator("#managedBrowserAddDialog").inner_text()
    assert page.locator("#managedBrowserAddEmail").input_value() == "first@example.com"
    state["fail"] = False
    page.locator("#managedBrowserAddSubmit").click()
    page.locator("#managedBrowserAccount").filter(has_text="first@example.com").wait_for()


def test_canceled_first_account_request_still_refreshes_without_reopening_dialog(browser_page):
    page, url = browser_page
    state = mock_browser_account_creation(page)
    waiting = []
    page.route("**/api/browser-sessions/accounts", lambda route: waiting.append(route))
    open_page(page, url + "/manage")
    page.locator("#addAccountWithBrowser").click()
    page.locator("#managedBrowserAddEmail").fill("first@example.com")
    page.locator("#managedBrowserAddSubmit").click()
    page.wait_for_function("document.getElementById('managedBrowserAddSubmit').disabled")
    assert len(waiting) == 1
    page.locator("#managedBrowserAddForm").evaluate("form => form.requestSubmit()")
    assert len(waiting) == 1
    page.locator("#managedBrowserAddCancel").click()
    state["accounts"] = [{"id": 7, "email": "first@example.com", "st": "browser-pending-fixture", "is_active": False}]
    waiting[0].fulfill(json={"success": True, "created": True,
                             "session": session("awaiting_login", token_id=7, browser_open=True)})
    page.locator("#tokenTableBody").filter(has_text="first@example.com").wait_for()
    assert not page.locator("#managedBrowserAddDialog").is_visible()
    assert not page.locator("#managedBrowserDialog").is_visible()


def test_pending_browser_accounts_cannot_be_enabled_from_row_actions(browser_page):
    page, url = browser_page
    page.route("**/api/tokens", lambda route: route.fulfill(json=[
        {"id": 7, "email": "pending@example.com", "st": "browser-pending-fixture", "is_active": False},
        {"id": 8, "email": "disabled@example.com", "st": "frontend-valid", "is_active": False},
    ]))
    open_page(page, url + "/manage")
    pending = page.locator("#tokenTableBody tr").filter(has_text="pending@example.com")
    ordinary = page.locator("#tokenTableBody tr").filter(has_text="disabled@example.com")
    assert pending.locator("[onclick^='toggleToken(']").count() == 0
    assert ordinary.locator("[onclick^='toggleToken(']").count() == 1
    assert pending.locator("[data-managed-browser-open='7']").count() == 1
    assert pending.locator("[onclick^='deleteToken(']").count() == 1


def test_first_account_email_dialog_fits_mobile(browser_page):
    page, url = browser_page
    mock_browser_account_creation(page)
    open_page(page, url + "/manage")
    page.locator("[data-language-select]").select_option("vi")
    page.locator("#addAccountWithBrowser").click()
    dialog = page.locator("#managedBrowserAddDialog")
    from pathlib import Path
    from tempfile import gettempdir
    for width in (1440, 390):
        page.set_viewport_size({"width": width, "height": 844})
        box = dialog.bounding_box()
        assert box and box["x"] >= 0 and box["x"] + box["width"] <= width
        assert dialog.evaluate("el => el.scrollWidth <= el.clientWidth")
        dialog.screenshot(path=str(Path(gettempdir()) / f"flow2api-first-account-{width}.png"))
    assert page.locator("#managedBrowserAddEmail").get_attribute("type") == "email"
    assert page.locator("#managedBrowserAddEmail").get_attribute("maxlength") == "254"


def test_browser_dialog_never_launches_until_explicit_click_and_closes_polling(browser_page):
    page, url = browser_page
    state = mock_sessions(page)
    open_page(page, url + "/manage")
    assert state["requests"] == []
    page.locator("[data-managed-browser-open='1']").click()
    dialog = page.locator("#managedBrowserDialog")
    page.wait_for_function("document.querySelector('#managedBrowserLogin').disabled === false")
    assert dialog.is_visible()
    assert state["requests"] == [("GET", "browser-session")]
    page.locator("#managedBrowserLogin").click()
    page.locator("#managedBrowserStatus").filter(has_text="Sign in to Google/Flow, then close the window to sync").wait_for()
    assert ("POST", "login") in state["requests"]
    page.keyboard.press("Escape")
    assert not dialog.is_visible()
    count = len(state["requests"])
    page.wait_for_timeout(3200)
    assert len(state["requests"]) == count


@pytest.mark.parametrize("locale,expected,description", [
    ("en", "Sign in to Google/Flow, then close the window to sync", "then close all windows of this account's dedicated browser profile"),
    ("vi", "Đăng nhập Google/Flow, sau đó đóng cửa sổ để đồng bộ", "sau đó đóng tất cả cửa sổ thuộc profile riêng của tài khoản này"),
    ("zh-CN", "请登录 Google/Flow，然后关闭窗口以同步", "然后关闭此账号专用配置的所有浏览器窗口"),
])
def test_normal_browser_login_instructions_explain_close_before_sync(browser_page, locale, expected, description):
    page, url = browser_page
    mock_sessions(page, session("awaiting_login", browser_open=True))
    open_page(page, url + "/manage")
    page.locator("[data-language-select]").select_option(locale)
    page.locator("[data-managed-browser-open='1']").click()
    page.wait_for_function("document.getElementById('managedBrowserDialog').getAttribute('aria-busy') === 'false'")
    assert page.locator("#managedBrowserStatus").inner_text() == expected
    text = page.locator("#managedBrowserDescription").inner_text()
    assert "Chrome" in text and "Edge" in text and description in text
    assert page.locator("#managedBrowserSync").is_disabled()
    help_link = page.locator("#managedBrowserHelp")
    assert help_link.get_attribute("href") == "https://support.google.com/accounts/answer/7675428?hl=en"
    assert "noreferrer" in help_link.get_attribute("rel")


@pytest.mark.parametrize("locale,expected", [
    ("en", "without a username and password"),
    ("vi", "không yêu cầu tên đăng nhập và mật khẩu"),
    ("zh-CN", "无需用户名和密码"),
])
def test_manual_browser_proxy_error_explains_unsupported_authentication(browser_page, locale, expected):
    page, url = browser_page
    mock_sessions(page, session("error", error_code="proxy_invalid"))
    open_page(page, url + "/manage")
    page.locator("[data-language-select]").select_option(locale)
    page.locator("[data-managed-browser-open='1']").click()
    page.wait_for_function("document.getElementById('managedBrowserDialog').getAttribute('aria-busy') === 'false'")
    assert expected in page.locator("#managedBrowserError").inner_text()


@pytest.mark.parametrize("email", ["correct-account@example.com", '<img src=x onerror="window.UI_INJECTED=true">@example.com'])
def test_browser_dialog_shows_expected_login_account_as_plain_text(browser_page, email):
    page, url = browser_page
    mock_sessions(page)
    page.route("**/api/tokens", lambda route: route.fulfill(json=[{
        "id": 1, "email": "listed@example.com", "login_account": email,
        "is_active": False,
    }]))
    open_page(page, url + "/manage")
    button = page.locator("[data-managed-browser-open='1']")
    button.click()
    assert email in page.locator("#managedBrowserAccount").inner_text()
    assert button.get_attribute("data-managed-browser-email") == email
    assert page.locator("#managedBrowserAccount img").count() == 0
    assert page.evaluate("window.UI_INJECTED === undefined")


@pytest.mark.parametrize("locale,expected", [("en", "Sign in again"), ("vi", "Cần đăng nhập lại"), ("zh-CN", "需要重新登录")])
def test_browser_session_status_and_identity_error_translate_without_raw_errors(browser_page, locale, expected):
    page, url = browser_page
    state = mock_sessions(page, session("needs_login", error_code="identity_mismatch"))
    open_page(page, url + "/manage")
    page.locator("[data-language-select]").select_option(locale)
    page.locator("[data-managed-browser-open='1']").click()
    page.locator("#managedBrowserStatus").filter(has_text=expected).wait_for()
    text = page.locator("#managedBrowserError").inner_text()
    assert text and "identity_mismatch" not in text
    state["fail"] = True
    page.locator("#managedBrowserLogin").click()
    page.wait_for_function("document.querySelector('#managedBrowserLogin').disabled === false")
    assert "SECRET_COOKIE" not in page.locator("#managedBrowserDialog").inner_text()
    assert page.locator("#managedBrowserError").inner_text() != text


def test_browser_ready_poll_refreshes_account_and_stop_preserves_profile_message(browser_page):
    page, url = browser_page
    state = mock_sessions(page, session("awaiting_login", browser_open=True))
    open_page(page, url + "/manage")
    page.locator("[data-managed-browser-open='1']").click()
    page.locator("#managedBrowserStatus").filter(has_text="Sign in to Google/Flow, then close the window to sync").wait_for()
    state["session"] = session("ready", browser_open=True, last_sync_at="2026-10-27T10:00:00Z")
    with page.expect_response("**/api/tokens"):
        page.locator("#managedBrowserStatus").filter(has_text="Cookies synchronized").wait_for(timeout=6000)
    assert page.locator("#managedBrowserLastSync").inner_text() not in {"", "Never"}
    page.locator("#managedBrowserStop").click()
    page.locator("#managedBrowserStatus").filter(has_text="Automatic sync stopped").wait_for()
    assert ("POST", "stop") in state["requests"]
    assert "saved profile" in page.locator("#managedBrowserDialog").inner_text()


def test_browser_pending_action_disables_controls_and_closed_dialog_ignores_response(browser_page):
    page, url = browser_page
    mock_sessions(page, session("ready"))
    pending = []
    page.route("**/browser-session/login", lambda route: pending.append(route))
    open_page(page, url + "/manage")
    page.locator("[data-managed-browser-open='1']").click()
    page.wait_for_function("document.querySelector('#managedBrowserLogin').disabled === false")
    page.locator("#managedBrowserLogin").click()
    for button in ("Login", "Sync", "Stop"):
        assert page.locator("#managedBrowser" + button).is_disabled()
    assert len(pending) == 1
    page.locator("#managedBrowserClose").click()
    pending[0].fulfill(json={"success": True, "session": session("awaiting_login")})
    assert not page.locator("#managedBrowserDialog").is_visible()


def test_browser_dialog_fits_desktop_and_mobile_with_translated_copy(browser_page):
    page, url = browser_page
    mock_sessions(page, session("needs_login", error_code="login_required"))
    open_page(page, url + "/manage")
    page.locator("[data-language-select]").select_option("vi")
    page.locator("[data-managed-browser-open='1']").click()
    page.locator("#managedBrowserStatus").filter(has_text="Cần đăng nhập lại").wait_for()
    assert page.locator("#managedBrowserClose").inner_text() == "Đóng"
    from tempfile import gettempdir
    from pathlib import Path
    for name, width in (("desktop", 1440), ("mobile", 390)):
        page.set_viewport_size({"width": width, "height": 900})
        box = page.locator("#managedBrowserDialog").bounding_box()
        assert box and box["x"] >= 0 and box["x"] + box["width"] <= width
        assert page.locator("#managedBrowserDialog").evaluate("el => el.scrollWidth <= el.clientWidth")
        assert page.locator("#managedBrowserClose").is_visible()
        page.locator("#managedBrowserDialog").screenshot(path=str(Path(gettempdir()) / f"flow2api-managed-browser-{name}.png"))
