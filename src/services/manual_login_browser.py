"""Open an ordinary, user-operated browser without an automation connection."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


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


class ManualBrowser:
    def __init__(self, process, channel):
        self.process = process
        self.channel = channel

    @property
    def is_running(self):
        return self.process.poll() is None

    async def close(self):
        if not self.is_running:
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
            if self.is_running:
                self.process.terminate()
            try:
                await asyncio.to_thread(self.process.wait, timeout=3)
            except subprocess.TimeoutExpired:
                if self.is_running:
                    self.process.kill()
                await asyncio.to_thread(self.process.wait, timeout=3)


async def launch_manual_browser(profile_path, *, proxy=None):
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
    args = [
        executable, f"--user-data-dir={profile}", "--restore-last-session",
        "--no-first-run", "--disable-background-mode", "--new-window", FLOW_URL,
    ]
    if proxy:
        args.insert(-1, f"--proxy-server={proxy['server']}")
    (profile / _CHANNEL_FILE).write_text(json.dumps({"channel": channel}), encoding="utf-8")
    process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return ManualBrowser(process, channel)
