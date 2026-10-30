"""Browser desktop controls use a fake RFB module, without remote credentials."""
import json
from pathlib import Path
from tempfile import gettempdir
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from test_i18n_browser import ROOT, browser_page, ui_server, open_page


RFB_STUB = """
export default class FakeRFB extends EventTarget {
  constructor(target, url) {
    super(); this.url=url; this.closed=false;
    window.__rfbInstances ||= []; window.__rfbInstances.push(this);
    const canvas=document.createElement('canvas'); canvas.width=1440; canvas.height=900;
    canvas.style.cssText='display:block;width:100%;height:100%;object-fit:contain';
    target.append(canvas);
    queueMicrotask(()=>this.dispatchEvent(new Event('connect')));
  }
  disconnect() {this.closed=true; this.dispatchEvent(new CustomEvent('disconnect',{detail:{clean:true}}));}
}
"""


def viewer_routes(page, *, enabled=True, unauthorized=False):
    page.route("**/browser-desktop/", lambda route: route.fulfill(
        content_type="text/html", body=(ROOT / "static/browser-desktop.html").read_text(encoding="utf-8")
    ))
    page.route("**/browser-desktop/assets/core/rfb.js", lambda route: route.fulfill(
        content_type="application/javascript", body=RFB_STUB
    ))
    state = {"unauthorized": unauthorized}
    def config(route):
        route.fulfill(status=401 if state["unauthorized"] else 200,
                      json={"success": True, "desktop": {"enabled": enabled, "url": "/browser-desktop/" if enabled else None}})
    page.route("**/api/browser-desktop/config", config)
    return state


def test_desktop_surface_has_a_real_translatable_page():
    assert (ROOT / "static/browser-desktop.html").is_file()
    assert (ROOT / "static/browser-desktop.js").is_file()
    assert (ROOT / "static/locales/desktop.json").is_file()


@pytest.mark.parametrize("locale,title,status", [
    ("vi", "Màn hình VPS", "Đã kết nối"),
    ("en", "VPS desktop", "Connected"),
    ("zh-CN", "VPS 桌面", "已连接"),
])
def test_viewer_uses_same_origin_binary_session_and_translated_instructions(browser_page, locale, title, status):
    page, url = browser_page
    viewer_routes(page)
    page.add_init_script(f"localStorage.setItem('flow2api.language', {json.dumps(locale)})")
    open_page(page, url + "/browser-desktop/")
    expect(page.locator("h1")).to_have_text(title)
    expect(page.locator("#desktopStatus")).to_have_text(status)
    assert page.evaluate("window.__rfbInstances[0].url") == url.replace("http:", "ws:") + "/api/browser-desktop/ws"
    assert page.evaluate("window.__rfbInstances[0].scaleViewport") is True
    assert page.evaluate("window.__rfbInstances[0].resizeSession") is False
    assert page.locator("#desktopInstructions").inner_text()
    assert not page.locator("input[type=password]").count()
    assert page.locator("#desktopManageLink").get_attribute("href") == "/manage"


def test_viewer_reconnect_closes_previous_connection_and_localizes_failures(browser_page):
    page, url = browser_page
    viewer_routes(page)
    open_page(page, url + "/browser-desktop/")
    expect(page.locator("#desktopStatus")).to_have_text("Connected")
    page.locator("#desktopReconnect").click()
    page.wait_for_function("window.__rfbInstances.length === 2")
    assert page.evaluate("window.__rfbInstances[0].closed") is True
    page.evaluate("window.__rfbInstances[1].dispatchEvent(new CustomEvent('securityfailure', {detail:{reason:'SECRET_COOKIE_SHOULD_NOT_RENDER'}}))")
    expect(page.locator("#desktopStatus")).to_have_text("Connection failed")
    assert "SECRET_COOKIE" not in page.locator("body").inner_text()
    page.locator("#desktopReconnect").click()
    expect(page.locator("#desktopStatus")).to_have_text("Connected")
    page.locator("#desktopDisconnect").click()
    expect(page.locator("#desktopStatus")).to_have_text("Disconnected")
    assert page.evaluate("window.__rfbInstances.at(-1).closed") is True


@pytest.mark.parametrize("unauthorized,expected", [(True, "Sign in to the admin console again"), (False, "Remote desktop is unavailable")])
def test_viewer_unavailable_or_expired_session_never_loads_rfb(browser_page, unauthorized, expected):
    page, url = browser_page
    viewer_routes(page, enabled=False, unauthorized=unauthorized)
    open_page(page, url + "/browser-desktop/")
    expect(page.locator("#desktopStatus")).to_have_text(expected)
    assert page.evaluate("window.__rfbInstances?.length || 0") == 0


def test_viewer_reports_session_expiration_after_socket_disconnect(browser_page):
    page, url = browser_page
    state = viewer_routes(page)
    open_page(page, url + "/browser-desktop/")
    expect(page.locator("#desktopStatus")).to_have_text("Connected")
    state["unauthorized"] = True
    page.evaluate("window.__rfbInstances[0].dispatchEvent(new CustomEvent('disconnect', {detail:{clean:false}}))")
    expect(page.locator("#desktopStatus")).to_have_text("Sign in to the admin console again")
    expect(page.locator("#desktopLoginLink")).to_be_visible()


def test_https_viewer_uses_wss_without_tokens_in_the_url(browser_page):
    page, _ = browser_page
    def secure_surface(route):
        path = urlsplit(route.request.url).path
        if path == "/browser-desktop/":
            route.fulfill(content_type="text/html", body=(ROOT / "static/browser-desktop.html").read_text(encoding="utf-8"))
        elif path == "/api/browser-desktop/config":
            route.fulfill(json={"success": True, "desktop": {"enabled": True, "url": "/browser-desktop/"}})
        elif path == "/browser-desktop/assets/core/rfb.js":
            route.fulfill(content_type="application/javascript", body=RFB_STUB)
        else:
            target = ROOT / path.lstrip("/")
            route.fulfill(content_type="application/json" if path.endswith(".json") else "application/javascript", body=target.read_text(encoding="utf-8"))
    page.route("https://desktop.test/**", secure_surface)
    open_page(page, "https://desktop.test/browser-desktop/")
    expect(page.locator("#desktopStatus")).to_have_text("Connected")
    assert page.evaluate("window.__rfbInstances[0].url") == "wss://desktop.test/api/browser-desktop/ws"
    page.evaluate("window.dispatchEvent(new PageTransitionEvent('pagehide'))")
    assert page.evaluate("window.__rfbInstances[0].closed") is True


@pytest.mark.parametrize("enabled", [True, False])
def test_managed_dialog_shows_desktop_link_only_when_enabled(browser_page, enabled):
    page, url = browser_page
    viewer_routes(page, enabled=enabled)
    page.route("**/browser-session", lambda route: route.fulfill(json={"success": True, "session": {
        "token_id": 1, "enabled": True, "status": "awaiting_login", "browser_open": True,
        "last_sync_at": None, "error_code": "", "interval_minutes": 30,
    }}))
    open_page(page, url + "/manage")
    page.locator("[data-managed-browser-open='1']").click()
    expect(page.locator("#managedBrowserDesktopLink")).to_be_visible() if enabled else expect(page.locator("#managedBrowserDesktopLink")).to_be_hidden()
    if enabled:
        assert page.locator("#managedBrowserDesktopLink").get_attribute("href") == "/browser-desktop/"
        assert page.locator("#managedBrowserDesktopLink").get_attribute("target") == "_blank"


def test_viewer_fits_desktop_and_phone_without_page_overflow(browser_page):
    page, url = browser_page
    viewer_routes(page)
    page.add_init_script("localStorage.setItem('flow2api.language','vi')")
    open_page(page, url + "/browser-desktop/")
    expect(page.locator("#desktopStatus")).to_have_text("Đã kết nối")
    for width in (1440, 390):
        page.set_viewport_size({"width": width, "height": 900})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert page.evaluate("document.documentElement.scrollHeight <= innerHeight")
        assert page.locator("#desktopScreen").bounding_box()["height"] > 200
        page.screenshot(path=str(Path(gettempdir()) / f"flow2api-vps-desktop-{width}.png"))
