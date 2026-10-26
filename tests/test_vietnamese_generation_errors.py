"""Vietnamese presentation errors must preserve account and retry decisions."""
import unittest
from src.services.generation_handler import GenerationHandler
from src.services.flow_client import FlowClient
from src.services.browser_captcha_personal import BrowserCaptchaService


class VietnameseGenerationErrorsTests(unittest.TestCase):
    def test_no_available_token_is_not_an_account_fault(self):
        handler = GenerationHandler.__new__(GenerationHandler)
        for kind in ("image", "video"):
            with self.subTest(kind=kind):
                self.assertFalse(handler._should_count_token_error(
                    RuntimeError(handler._get_no_token_error_message(kind))))

    def test_captcha_resource_failure_is_not_an_account_fault(self):
        handler = GenerationHandler.__new__(GenerationHandler)
        for message in ("Dịch vụ giải CAPTCHA không đủ tài nguyên",
                        "Tài nguyên dịch vụ giải CAPTCHA bị chặn",
                        "Không lấy được token reCAPTCHA"):
            with self.subTest(message=message):
                self.assertFalse(handler._should_count_token_error(RuntimeError(message)))
        self.assertTrue(handler._should_count_token_error(RuntimeError("Token đã hết hạn")))

    def test_translated_timeouts_preserve_external_error_recovery(self):
        service = BrowserCaptchaService.__new__(BrowserCaptchaService)
        self.assertTrue(service._is_external_flow_error(
            "Lỗi mạng/TLS: Hết thời gian chờ API video Flow sau 30 giây"))
        self.assertTrue(service._is_external_flow_error(
            "Hết thời gian chờ API video Flow sau 30 giây"))

    def test_translated_http_500_preserves_server_error_recovery(self):
        service = BrowserCaptchaService.__new__(BrowserCaptchaService)
        self.assertTrue(service._is_server_side_flow_error(
            "Lỗi 500/nội bộ: Lỗi HTTP 500"))
        self.assertFalse(service._is_server_side_flow_error("Lỗi HTTP 400"))

    def test_browser_queue_timeout_does_not_retry(self):
        client = FlowClient.__new__(FlowClient)
        self.assertIsNone(client._get_retry_reason(
            "Hết thời gian chờ trong hàng đợi CAPTCHA trình duyệt"))


if __name__ == "__main__":
    unittest.main()
