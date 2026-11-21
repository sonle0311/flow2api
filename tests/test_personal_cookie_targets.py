"""Personal captcha contexts must keep every captured Google cookie at its scope."""

import json

from src.services.browser_captcha_personal import BrowserCaptchaService


CAPTURED = json.dumps([
    {"name": "SID", "value": "sid", "domain": ".google.com", "path": "/", "secure": True, "httpOnly": True,
     "hostOnly": False, "sameSite": "Lax", "expires": 4102444800},
    {"name": "OSID", "value": "osid", "domain": "flow.google.com", "path": "/", "secure": True, "httpOnly": True,
     "hostOnly": True, "sameSite": "Lax", "expires": 4102444800},
    {"name": "__Host-1PLSID", "value": "lsid", "domain": "accounts.google.com", "path": "/", "secure": True,
     "httpOnly": True, "hostOnly": True, "sameSite": "Lax", "expires": 4102444800},
])


def scopes(targets, name):
    return {target.get("domain") or target.get("url") for target in targets if target["name"] == name}


def test_host_only_flow_and_accounts_cookies_keep_their_own_scope():
    targets = BrowserCaptchaService._build_personal_cookie_targets(CAPTURED)
    assert "https://flow.google.com/" in scopes(targets, "OSID")
    assert "https://accounts.google.com/" in scopes(targets, "__Host-1PLSID")
    assert ".google.com" in scopes(targets, "SID")
    # reCAPTCHA mirrors are still added on top of the originals.
    assert "https://www.recaptcha.net/" in scopes(targets, "SID")
    assert "https://www.recaptcha.net/" in scopes(targets, "OSID")


def test_configured_startup_cookies_keep_host_only_scope_too():
    targets = BrowserCaptchaService._build_configured_browser_cookie_targets(CAPTURED)
    assert "https://flow.google.com/" in scopes(targets, "OSID")
