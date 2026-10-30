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
            self.assertFalse(any("automation" in arg or "debugging" in arg or "headless" in arg for arg in args))
            self.assertNotIn("shell", factory.call_args.kwargs)
            self.assertTrue(handle.is_running)
            self.assertEqual("chrome", read_profile_channel(profile))

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
