import tempfile
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


class ManualLoginBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def test_launch_uses_a_normal_dedicated_browser_without_automation(self):
        from src.services.manual_login_browser import launch_manual_browser, read_profile_channel
        with tempfile.TemporaryDirectory() as root:
            profile = Path(root) / "account-profile"
            process = MagicMock()
            process.poll.return_value = None
            with patch("src.services.manual_login_browser.find_browser", return_value=("C:/Chrome/chrome.exe", "chrome")), patch("src.services.manual_login_browser.subprocess.Popen", return_value=process) as factory:
                handle = await launch_manual_browser(profile, proxy=None)
            args = factory.call_args.args[0]
            self.assertIn(f"--user-data-dir={profile}", args)
            self.assertIn("--restore-last-session", args)
            self.assertEqual("https://flow.google.com/projects", args[-1])
            self.assertFalse(any("automation" in arg or "headless" in arg for arg in args))
            # DevTools only on loopback, so the service can see a tab reach Flow.
            self.assertIn("--remote-debugging-address=127.0.0.1", args)
            self.assertIn(f"--remote-debugging-port={handle.debug_port}", args)
            self.assertNotIn("shell", factory.call_args.kwargs)
            self.assertTrue(handle.is_running)
            self.assertEqual("chrome", read_profile_channel(profile))

    async def test_autodetect_can_be_switched_off(self):
        from src.services.manual_login_browser import launch_manual_browser
        with tempfile.TemporaryDirectory() as root, patch.dict("os.environ", {"FLOW2API_MANUAL_LOGIN_AUTODETECT": "0"}):
            with patch("src.services.manual_login_browser.find_browser", return_value=("C:/Chrome/chrome.exe", "chrome")), patch("src.services.manual_login_browser.subprocess.Popen") as factory:
                handle = await launch_manual_browser(Path(root))
            self.assertFalse(any("debugging" in arg for arg in factory.call_args.args[0]))
            self.assertIsNone(handle.debug_port)
            self.assertFalse(await handle.has_flow_tab())

    def test_start_url_prefills_the_account_email_and_falls_back_to_flow(self):
        from urllib.parse import parse_qs, urlparse
        from src.services.manual_login_browser import FLOW_URL, start_url
        url = urlparse(start_url("first.last+x@gmail.com"))
        query = parse_qs(url.query)
        self.assertEqual(("accounts.google.com", "/ServiceLogin"), (url.hostname, url.path))
        self.assertEqual(["first.last+x@gmail.com"], query["Email"])
        self.assertEqual([FLOW_URL], query["continue"])
        for missing in (None, "", "not-an-email"):
            self.assertEqual(FLOW_URL, start_url(missing))

    async def test_flow_tab_detection_ignores_the_landing_page_and_other_sites(self):
        from src.services.manual_login_browser import ManualBrowser
        browser = ManualBrowser(MagicMock(), "chrome", debug_port=9222)
        tabs = [
            {"type": "page", "url": "https://accounts.google.com/v3/signin/identifier"},
            {"type": "page", "url": "https://flow.google.com/"},
            {"type": "page", "url": "https://flow.google.com/about?returnUrl=%2Fprojects"},
            {"type": "service_worker", "url": "https://flow.google.com/projects"},
        ]
        with patch("src.services.manual_login_browser._list_tabs", side_effect=lambda port: tabs):
            self.assertFalse(await browser.has_flow_tab())
            tabs.append({"type": "page", "url": "https://flow.google.com/projects?pli=1"})
            self.assertTrue(await browser.has_flow_tab())
        with patch("src.services.manual_login_browser._list_tabs", side_effect=OSError("closed")):
            self.assertFalse(await browser.has_flow_tab())

    def test_profile_check_sees_whether_chrome_flushed_the_sign_in_cookies(self):
        import sqlite3
        from src.services.manual_login_browser import profile_keeps_google_session
        with tempfile.TemporaryDirectory() as root:
            profile = Path(root)
            self.assertIsNone(profile_keeps_google_session(profile))  # no cookie store at all: nothing concluded
            store = profile / "Default/Network/Cookies"
            store.parent.mkdir(parents=True)
            conn = sqlite3.connect(store)
            conn.execute("CREATE TABLE cookies (host_key TEXT, name TEXT)")
            conn.executemany("INSERT INTO cookies VALUES (?, ?)", [(".google.com", "NID"), (".google.com", "AEC"), ("example.com", "SID")])
            conn.commit()
            conn.close()
            self.assertFalse(profile_keeps_google_session(profile))  # a profile killed too early
            conn = sqlite3.connect(store)
            conn.execute("INSERT INTO cookies VALUES ('.google.com', '__Secure-1PSID')")
            conn.commit()
            conn.close()
            self.assertTrue(profile_keeps_google_session(profile))
            store.write_bytes(b"not sqlite")
            self.assertIsNone(profile_keeps_google_session(profile))

    async def test_proxy_credentials_are_not_put_on_the_process_command_line(self):
        from src.services.manual_login_browser import launch_manual_browser
        with tempfile.TemporaryDirectory() as root:
            with patch("src.services.manual_login_browser.subprocess.Popen") as factory:
                with self.assertRaisesRegex(ValueError, "proxy_invalid"):
                    await launch_manual_browser(Path(root), proxy={"server": "http://localhost:9000", "username": "secret", "password": "private"})
            factory.assert_not_called()

    async def test_missing_browser_is_reported_before_creating_a_profile(self):
        from src.services.manual_login_browser import launch_manual_browser
        with tempfile.TemporaryDirectory() as root:
            profile = Path(root) / "not-created"
            with patch("src.services.manual_login_browser.find_browser", side_effect=FileNotFoundError("browser_unavailable")):
                with self.assertRaises(FileNotFoundError):
                    await launch_manual_browser(profile)
            self.assertFalse(profile.exists())

    async def test_existing_edge_profile_requests_edge_even_when_chrome_is_installed(self):
        from src.services.manual_login_browser import launch_manual_browser
        with tempfile.TemporaryDirectory() as root:
            profile = Path(root)
            (profile / ".flow2api-browser.json").write_text(json.dumps({"channel": "msedge"}))
            with patch("src.services.manual_login_browser.find_browser", return_value=("C:/Edge/msedge.exe", "msedge")) as find, patch("src.services.manual_login_browser.subprocess.Popen"):
                handle = await launch_manual_browser(profile)
            find.assert_called_once_with("msedge")
            self.assertEqual("msedge", handle.channel)

    async def test_profile_marker_failure_never_leaves_an_untracked_browser(self):
        from src.services.manual_login_browser import launch_manual_browser
        with tempfile.TemporaryDirectory() as root:
            with patch("src.services.manual_login_browser.find_browser", return_value=("C:/Chrome/chrome.exe", "chrome")), patch("pathlib.Path.write_text", side_effect=PermissionError()), patch("src.services.manual_login_browser.subprocess.Popen") as factory:
                with self.assertRaises(PermissionError):
                    await launch_manual_browser(Path(root))
            factory.assert_not_called()

    async def test_closed_process_does_not_receive_any_termination(self):
        from src.services.manual_login_browser import ManualBrowser
        process = MagicMock()
        process.poll.return_value = 0
        browser = ManualBrowser(process, "chrome")
        await browser.close()
        process.terminate.assert_not_called()
        process.kill.assert_not_called()

    async def test_close_signals_only_the_owned_process(self):
        from src.services.manual_login_browser import ManualBrowser
        process = MagicMock()
        process.poll.return_value = None
        process.wait.return_value = 0
        browser = ManualBrowser(process, "chrome")
        with patch("src.services.manual_login_browser._request_window_close", return_value=True) as close:
            await browser.close()
        close.assert_called_once_with(process.pid)
        process.wait.assert_called_once()
        process.terminate.assert_not_called()

    def test_closing_last_shown_window_ends_login_while_process_lives(self):
        from src.services.manual_login_browser import ManualBrowser
        process = MagicMock()
        process.poll.return_value = None
        helpers = [(1, False, 500.0, 500.0), (2, False, 1920.0, 30.0), (3, True, 1.0, 1.0)]
        windows = list(helpers)
        browser = ManualBrowser(process, "chrome", window_lister=lambda pid: windows)
        # Only hidden helper windows so far: keep waiting.
        self.assertTrue(browser.is_running)
        windows.append((10, True, 1200.0, 724.0))
        self.assertTrue(browser.is_running)
        # Minimized / on another Space: still listed, just not on screen.
        windows[-1] = (10, False, 1200.0, 724.0)
        self.assertTrue(browser.is_running)
        windows.pop()
        self.assertFalse(browser.is_running)
        self.assertTrue(browser.process_running)

    def test_second_window_keeps_login_open_until_all_are_closed(self):
        from src.services.manual_login_browser import ManualBrowser
        process = MagicMock()
        process.poll.return_value = None
        windows = [(10, True, 1200.0, 724.0)]
        browser = ManualBrowser(process, "chrome", window_lister=lambda pid: windows)
        self.assertTrue(browser.is_running)
        windows.append((11, True, 800.0, 600.0))
        self.assertTrue(browser.is_running)
        windows.pop(0)
        self.assertTrue(browser.is_running)
        windows.pop(0)
        self.assertFalse(browser.is_running)

    def test_window_listing_failure_falls_back_to_process_state(self):
        from src.services.manual_login_browser import ManualBrowser
        process = MagicMock()
        process.poll.return_value = None

        def broken(pid):
            raise OSError("unavailable")

        browser = ManualBrowser(process, "chrome", window_lister=broken)
        self.assertTrue(browser.is_running)
        process.poll.return_value = 0
        self.assertFalse(browser.is_running)

    async def test_close_terminates_window_less_browser_process(self):
        from src.services.manual_login_browser import ManualBrowser
        process = MagicMock()
        process.poll.return_value = None
        process.wait.return_value = 0
        browser = ManualBrowser(process, "chrome", window_lister=lambda pid: [])
        browser._seen_windows.add(10)
        self.assertFalse(browser.is_running)
        with patch("src.services.manual_login_browser._request_window_close", return_value=False):
            await browser.close()
        process.terminate.assert_called_once()
