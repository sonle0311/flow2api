"""Open an ordinary, user-operated browser; no automation touches the sign-in pages.

The browser listens for DevTools on a random loopback port only so that the service can see,
without attaching, when a tab has reached Flow. It attaches once, after sign-in, to read the
cookies, then closes the browser. FLOW2API_MANUAL_LOGIN_AUTODETECT=0 turns the port off, and
the hand-off then waits for the user to close the window.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path
from urllib.parse import quote, urlparse


FLOW_URL = "https://flow.google.com/projects"
_CHANNEL_FILE = ".flow2api-browser.json"


def find_browser(preferred_channel=None):
    """Prefer installed Chrome, then Edge; do not use an embedded test browser."""
    candidates = []
    if os.name == "nt":
        for channel, relative in (
            ("chrome", "Google/Chrome/Application/chrome.exe"),
            ("msedge", "Microsoft/Edge/Application/msedge.exe"),
        ):
            for root in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")):
                if root:
                    candidates.append((Path(root) / relative, channel))
    elif sys.platform == "darwin":
        candidates.extend([
            (Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"), "chrome"),
            (Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"), "msedge"),
        ])
    for name, channel in (("google-chrome", "chrome"), ("google-chrome-stable", "chrome"), ("chrome", "chrome"), ("microsoft-edge", "msedge"), ("msedge", "msedge")):
        path = shutil.which(name)
        if path:
            candidates.append((Path(path), channel))
    for path, channel in candidates:
        if (not preferred_channel or channel == preferred_channel) and path.is_file():
            return str(path), channel
    raise FileNotFoundError("browser_unavailable")


def read_profile_channel(profile_path):
    try:
        value = json.loads((Path(profile_path) / _CHANNEL_FILE).read_text(encoding="utf-8"))
        channel = value.get("channel")
        return channel if channel in {"chrome", "msedge"} else None
    except (OSError, ValueError, AttributeError):
        return None


def _request_window_close(pid):
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    found = False

    @callback_type
    def close_window(hwnd, _):
        nonlocal found
        window_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
        if window_pid.value == pid:
            found = True
            user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE, only this owned process.
        return True

    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows(close_window, 0)
    return found


_MAC_MIN_WIDTH = 300
_MAC_MIN_HEIGHT = 200
_mac_window_api = None


def _load_mac_window_api():
    """Bind the CoreGraphics window list via ctypes (window metadata needs no permission)."""
    global _mac_window_api
    if _mac_window_api is None:
        import ctypes
        import ctypes.util

        vp = ctypes.c_void_p
        cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
        cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
        cg.CGWindowListCopyWindowInfo.restype = vp
        cg.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
        cf.CFArrayGetCount.restype = ctypes.c_long
        cf.CFArrayGetCount.argtypes = [vp]
        cf.CFArrayGetValueAtIndex.restype = vp
        cf.CFArrayGetValueAtIndex.argtypes = [vp, ctypes.c_long]
        cf.CFDictionaryGetValue.restype = vp
        cf.CFDictionaryGetValue.argtypes = [vp, vp]
        cf.CFNumberGetValue.restype = ctypes.c_bool
        cf.CFNumberGetValue.argtypes = [vp, ctypes.c_int, vp]
        cf.CFBooleanGetValue.restype = ctypes.c_bool
        cf.CFBooleanGetValue.argtypes = [vp]
        cf.CFRelease.argtypes = [vp]

        class Rect(ctypes.Structure):
            _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double), ("w", ctypes.c_double), ("h", ctypes.c_double)]

        cg.CGRectMakeWithDictionaryRepresentation.restype = ctypes.c_bool
        cg.CGRectMakeWithDictionaryRepresentation.argtypes = [vp, ctypes.POINTER(Rect)]
        keys = {
            name: vp.in_dll(cg, name)
            for name in ("kCGWindowOwnerPID", "kCGWindowLayer", "kCGWindowNumber", "kCGWindowIsOnscreen", "kCGWindowBounds")
        }
        _mac_window_api = (ctypes, cg, cf, Rect, keys)
    return _mac_window_api


def _mac_windows(pid):
    """Return [(window_number, onscreen, width, height)] for normal-layer windows owned by pid."""
    ctypes, cg, cf, Rect, keys = _load_mac_window_api()

    def number(entry, key):
        value = cf.CFDictionaryGetValue(entry, keys[key])
        if not value:
            return None
        out = ctypes.c_int64()
        cf.CFNumberGetValue(value, 4, ctypes.byref(out))  # kCFNumberSInt64Type
        return out.value

    windows = []
    listing = cg.CGWindowListCopyWindowInfo(0, 0)  # kCGWindowListOptionAll, including minimized/other Spaces
    if not listing:
        raise OSError("window_list_unavailable")
    try:
        for index in range(cf.CFArrayGetCount(listing)):
            entry = cf.CFArrayGetValueAtIndex(listing, index)
            if number(entry, "kCGWindowOwnerPID") != pid or number(entry, "kCGWindowLayer") != 0:
                continue
            onscreen = cf.CFDictionaryGetValue(entry, keys["kCGWindowIsOnscreen"])
            rect = Rect()
            bounds = cf.CFDictionaryGetValue(entry, keys["kCGWindowBounds"])
            if bounds:
                cg.CGRectMakeWithDictionaryRepresentation(bounds, ctypes.byref(rect))
            windows.append((number(entry, "kCGWindowNumber"), bool(onscreen and cf.CFBooleanGetValue(onscreen)), rect.w, rect.h))
    finally:
        cf.CFRelease(listing)
    return windows


class ManualBrowser:
    def __init__(self, process, channel, window_lister=None, debug_port=None):
        self.process = process
        self.channel = channel
        self.debug_port = debug_port
        # macOS keeps Chrome alive after its last window closes, so process exit
        # alone never signals the hand-off there; watch the browser windows too.
        if window_lister is None and sys.platform == "darwin":
            window_lister = _mac_windows
        self._window_lister = window_lister
        self._seen_windows = set()

    def _windows_closed(self):
        """True once every real browser window that has been shown is gone.

        Chrome also owns hidden helper windows that never appear on screen, so a
        window counts only after it has been visible at browser-window size.
        Minimized windows or windows on another Space remain in the list and
        therefore do not count as closed.
        """
        if self._window_lister is None:
            return False
        try:
            windows = self._window_lister(self.process.pid)
        except Exception:
            return False
        for number, onscreen, width, height in windows:
            if onscreen and width >= _MAC_MIN_WIDTH and height >= _MAC_MIN_HEIGHT:
                self._seen_windows.add(number)
        if not self._seen_windows:
            return False
        existing = {number for number, *_ in windows}
        return not (self._seen_windows & existing)

    @property
    def is_running(self):
        return self.process.poll() is None and not self._windows_closed()

    @property
    def process_running(self):
        return self.process.poll() is None

    async def has_flow_tab(self):
        """True when a tab sits on a Flow page past the landing page (plain HTTP, no attach)."""
        if not self.debug_port:
            return False
        try:
            tabs = await asyncio.to_thread(_list_tabs, self.debug_port)
        except Exception:
            return False
        for tab in tabs:
            url = urlparse(str(tab.get("url") or ""))
            if tab.get("type") == "page" and url.hostname == "flow.google.com" and url.path.startswith("/project"):
                return True
        return False

    async def close(self):
        # A window-less Chrome on macOS still holds the profile lock and unsaved
        # cookies; terminating it (SIGTERM) shuts it down cleanly and flushes them.
        if not self.process_running:
            return
        try:
            closed = await asyncio.to_thread(_request_window_close, self.process.pid)
        except OSError:
            closed = False
        if not closed:
            self.process.terminate()
        try:
            await asyncio.to_thread(self.process.wait, timeout=8)
        except subprocess.TimeoutExpired:
            if self.process_running:
                self.process.terminate()
            try:
                await asyncio.to_thread(self.process.wait, timeout=3)
            except subprocess.TimeoutExpired:
                if self.process_running:
                    self.process.kill()
                await asyncio.to_thread(self.process.wait, timeout=3)


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _list_tabs(port):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


def start_url(login_hint=None):
    """Flow itself, or Google's sign-in with the account's email filled in.

    A profile that is still signed in goes straight on to Flow; otherwise the user only
    has to type the password and complete verification.
    """
    hint = str(login_hint or "").strip()
    if "@" not in hint:
        return FLOW_URL
    return (
        "https://accounts.google.com/ServiceLogin?continue="
        f"{quote(FLOW_URL, safe='')}&Email={quote(hint, safe='@')}"
    )


async def launch_manual_browser(profile_path, *, proxy=None, login_hint=None):
    if proxy:
        server = urlparse(str(proxy.get("server") or ""))
        if proxy.get("username") or proxy.get("password") or server.username is not None or server.password is not None:
            raise ValueError("proxy_invalid")
    saved_channel = read_profile_channel(profile_path)
    executable, channel = find_browser(saved_channel)
    if saved_channel and saved_channel != channel:
        # Reusing a profile in a different browser can lose its encrypted cookies.
        raise RuntimeError("browser_unavailable")
    profile = Path(profile_path)
    profile.mkdir(parents=True, exist_ok=True)
    # Open Flow as a tab of the restored window rather than in an extra
    # window, so repeated logins do not stack up windows in the profile.
    args = [
        executable, f"--user-data-dir={profile}", "--restore-last-session",
        "--no-first-run", "--disable-background-mode", start_url(login_hint),
    ]
    debug_port = None
    if os.environ.get("FLOW2API_MANUAL_LOGIN_AUTODETECT", "1").strip().lower() not in {"0", "false", "no", "off"}:
        debug_port = _free_port()
        args[-1:-1] = [f"--remote-debugging-port={debug_port}", "--remote-debugging-address=127.0.0.1"]
    if proxy:
        args.insert(-1, f"--proxy-server={proxy['server']}")
    (profile / _CHANNEL_FILE).write_text(json.dumps({"channel": channel}), encoding="utf-8")
    process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return ManualBrowser(process, channel, debug_port=debug_port)
