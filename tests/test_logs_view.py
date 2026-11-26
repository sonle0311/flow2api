"""The console's Logs tab: summary strip, server-side filters, paging, retention and the time breakdown."""
import json
import re
from urllib.parse import parse_qs, urlsplit

import pytest

from test_i18n_browser import browser_page, ui_server, open_page, playwright_api

TOTAL = 120

SUMMARY = {
    "hours": 24, "since": "2026-11-26 00:00:00", "total": 120, "truncated": False,
    "success": 90, "failed": 10, "running": 2, "success_rate": 0.9,
    "duration": {"count": 90, "median": 21.4, "p95": 88.0},
    "upload_cache": {"requests": 40, "hits": 30, "misses": 10, "hit_rate": 0.75},
    "by_account": [
        {"token_id": 5, "email": "ultra@example.test", "requests": 100, "success": 80, "failed": 5, "median": 20.0, "p95": 80.0, "success_rate": 0.94},
        {"token_id": 2, "email": "tier1@example.test", "requests": 20, "success": 10, "failed": 5, "median": 30.0, "p95": 90.0, "success_rate": 0.67},
    ],
    "by_model": [
        {"model": "gemini-3.1-flash-image-landscape-2k", "requests": 90, "success": 80, "failed": 5, "median": 70.0, "p95": 110.0, "success_rate": 0.94},
        {"model": "veo_3_1_t2v_lite", "requests": 30, "success": 10, "failed": 5, "median": 60.0, "p95": 100.0, "success_rate": 0.67},
    ],
    "by_client_key": [
        {"client_key_id": 4, "name": "agent-one", "requests": 80, "failed": 4},
        {"client_key_id": 0, "name": "", "requests": 40, "failed": 6},
    ],
    "buckets": [{"start": f"2026-11-26 {hour:02d}:00:00", "requests": hour + 1, "failed": hour % 3} for hour in range(24)],
}

DETAIL = {
    "id": 1, "token_id": 5, "token_email": "ultra@example.test", "operation": "generate_image",
    "model": "gemini-3.1-flash-image-landscape-2k", "prompt_excerpt": "a red fox", "client_key_id": 4,
    "client_key_name": "agent-one", "job_id": "job_0123456789abcdef", "status_code": 200, "duration": 70.0,
    "status_text": "completed", "progress": 100, "created_at": "2026-11-26 16:51:42", "updated_at": "2026-11-26 16:51:42",
    "error_summary": "", "request_body": "{}", "response_body": "{}",
    "timings": {
        "total_ms": 70000,
        "stages": [{"id": "upload_images", "ms": 16000}, {"id": "generate_api", "ms": 40000}, {"id": "upsample", "ms": 9000}],
        "other_ms": 5000, "input_images": 2, "upload_cache": {"hits": 1, "misses": 1},
    },
}


def log(number):
    return {
        "id": number, "token_id": 5, "token_email": "ultra@example.test", "token_username": "", "operation": "generate_image",
        "model": "gemini-3.1-flash-image-landscape-2k", "prompt_excerpt": f"fox number {number}",
        "client_key_id": 4, "client_key_name": "agent-one", "job_id": "job_0123456789abcdef",
        "status_code": 200, "duration": 10.5, "status_text": "completed", "progress": 100,
        "created_at": "2026-11-26 16:51:42", "updated_at": "2026-11-26 16:51:42", "error_summary": "",
    }


@pytest.fixture
def logs_page(browser_page):
    page, base = browser_page
    seen = {"list": [], "summary": [], "retention": []}

    def list_route(route):
        query = parse_qs(urlsplit(route.request.url).query)
        seen["list"].append({key: values[0] for key, values in query.items()})
        limit, offset = int(query["limit"][0]), int(query["offset"][0])
        rows = [log(TOTAL - index) for index in range(offset, min(TOTAL, offset + limit))]
        route.fulfill(content_type="application/json", headers={"X-Total-Count": str(TOTAL)}, body=json.dumps(rows))

    def summary_route(route):
        seen["summary"].append(route.request.url)
        route.fulfill(content_type="application/json", body=json.dumps(SUMMARY))

    def retention_route(route):
        if route.request.method == "PUT":
            seen["retention"].append(json.loads(route.request.post_data))
            route.fulfill(content_type="application/json", body=json.dumps({"success": True, "purged": 3, "retention_days": 30}))
        else:
            route.fulfill(content_type="application/json", body=json.dumps({"success": True, "retention_days": 14}))

    page.route(re.compile(r"/api/logs(\?.*)?$"), list_route)
    page.route(re.compile(r"/api/logs/summary"), summary_route)
    page.route(re.compile(r"/api/logs/retention"), retention_route)
    page.route(re.compile(r"/api/logs/1$"), lambda route: route.fulfill(content_type="application/json", body=json.dumps(DETAIL)))
    open_page(page, base + "/manage#logs")
    playwright_api.expect(page.locator("#logsTableBody tr")).to_have_count(50)
    page.wait_for_function("document.querySelector('#logsSummary .logs-cards')")
    return page, seen


def test_the_summary_strip_shows_the_numbers_for_the_window(logs_page):
    page, seen = logs_page
    cards = page.locator("#logsSummary .logs-card")
    text = page.locator("#logsSummary").inner_text()
    for expected in ("120", "\n90%\n", "21 s", "p95 88 s", "\n75%\n", "30 hits, 10 misses", "2 running"):
        assert expected in text, expected
    assert cards.count() == 5
    assert page.locator("#logsSummary .logs-bar").count() == 24
    assert "hours=24" in seen["summary"][0]
    assert "logs." not in text


def test_filters_come_from_the_summary_and_are_sent_to_the_server(logs_page):
    page, seen = logs_page
    assert page.locator("#logsAccount option").all_inner_texts() == ["All accounts", "ultra@example.test", "tier1@example.test"]
    assert "veo_3_1_t2v_lite" in page.locator("#logsModel option").all_inner_texts()
    assert page.locator("#logsKey option").all_inner_texts() == ["All keys", "agent-one"]
    page.locator("#logsStatus").select_option("failed")
    page.locator("#logsAccount").select_option("2")
    page.locator("#logsModel").select_option("veo_3_1_t2v_lite")
    page.locator("#logsKey").select_option("4")
    page.locator("#logsRange").select_option("168")
    page.wait_for_function("window.__lastQuery = null, true")
    sent = [query for query in seen["list"] if query.get("hours") == "168"][-1]
    assert (sent["status"], sent["token_id"], sent["model"], sent["client_key_id"], sent["offset"]) == ("failed", "2", "veo_3_1_t2v_lite", "4", "0")
    page.locator("#logsReset").click()
    page.wait_for_function("document.querySelector('#logsStatus').value === ''")
    last = seen["list"][-1]
    assert not {"status", "token_id", "model", "client_key_id", "q"} & set(last)


def test_search_waits_for_a_pause_in_typing_then_asks_the_server(logs_page):
    page, seen = logs_page
    before = len(seen["list"])
    page.locator("#logsSearch").type("ogiZ0b", delay=20)
    page.wait_for_function("true")
    page.wait_for_timeout(700)
    queries = [query for query in seen["list"][before:] if "q" in query]
    assert [query["q"] for query in queries] == ["ogiZ0b"]


def test_paging_moves_by_the_page_size_and_says_where_you_are(logs_page):
    page, seen = logs_page
    assert page.locator("#logsShowing").inner_text() == "1–50 of 120"
    assert page.locator("#logsPrev").is_disabled()
    summaries = len(seen["summary"])
    page.locator("#logsNext").click()
    playwright_api.expect(page.locator("#logsShowing")).to_have_text("51–100 of 120")
    assert seen["list"][-1]["offset"] == "50"
    page.locator("#logsNext").click()
    playwright_api.expect(page.locator("#logsShowing")).to_have_text("101–120 of 120")
    assert page.locator("#logsNext").is_disabled()
    assert page.locator("#logsTableBody tr").count() == 20
    assert len(seen["summary"]) == summaries  # turning pages does not recompute the summary
    page.locator("#logsPageSize").select_option("100")
    playwright_api.expect(page.locator("#logsShowing")).to_have_text("1–100 of 120")


def test_rows_say_which_model_prompt_key_and_job_made_the_request(logs_page):
    page, _ = logs_page
    row = page.locator("#logsTableBody tr").first
    text = row.inner_text()
    assert "gemini-3.1-flash-image-landscape-2k" in text
    assert "fox number 120" in text
    assert "agent-one" in text
    assert "01234567" in text and "job_0123456789abcdef" == row.locator(".logs-job").get_attribute("title")


def test_times_are_shown_as_utc_instants_not_local_clock_times(logs_page):
    page, _ = logs_page
    assert page.evaluate("LogsView.date('2026-11-26 16:51:42').toISOString()") == "2026-11-26T16:51:42.000Z"
    assert page.evaluate("LogsView.date('2026-11-26T16:51:42+07:00').toISOString()") == "2026-11-26T09:51:42.000Z"
    assert page.evaluate("LogsView.date('garbage')") is None


def test_the_detail_shows_where_the_time_went(logs_page):
    page, _ = logs_page
    page.evaluate("showLogDetail(1)")
    detail = page.locator("#logDetailContent")
    playwright_api.expect(detail.locator(".logs-stages")).to_be_visible()
    rows = detail.locator(".logs-stages tr")
    assert rows.all_inner_texts() == [
        "Upload input images\t16.0 s\t23%", "Flow generates\t40.0 s\t57%", "Upscale\t9.0 s\t13%",
        "Other (waiting for Flow, downloads)\t5.0 s\t7%",
    ]
    text = detail.inner_text()
    assert "2 input images; upload cache: 1 hits, 1 misses." in text
    assert "agent-one" in text and "job_0123456789abcdef" in text
    widths = detail.locator(".logs-timeline > span").evaluate_all("els => els.map(e => parseFloat(e.style.width))")
    assert round(sum(widths)) == 100


def test_retention_is_loaded_confirmed_and_saved(logs_page):
    page, seen = logs_page
    assert page.locator("#logsRetentionDays").input_value() == "14"
    page.locator("#logsRetentionDays").fill("30")
    messages = []
    page.once("dialog", lambda dialog: (messages.append(dialog.message), dialog.dismiss()))
    page.locator("#logsRetentionSave").click()
    assert "30 days" in messages[0] and seen["retention"] == []  # declining the confirmation changes nothing
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#logsRetentionSave").click()
    playwright_api.expect(page.locator("#logsRetentionStatus")).to_have_text("Saved: keeping 30 days, deleted 3 logs now.")
    assert seen["retention"] == [{"retention_days": 30}]
    page.locator("#logsRetentionDays").fill("-2")
    page.locator("#logsRetentionSave").click()
    playwright_api.expect(page.locator("#logsRetentionStatus")).to_have_text("Enter a whole number from 0 to 3650.")
    assert seen["retention"] == [{"retention_days": 30}]


@pytest.mark.parametrize("language", ["vi", "zh-CN"])
def test_every_new_label_is_translated(logs_page, language):
    page, _ = logs_page
    page.locator("[data-language-select]").select_option(language)
    page.evaluate("showLogDetail(1)")
    playwright_api.expect(page.locator("#logDetailContent .logs-stages")).to_be_visible()
    visible = page.locator("#panelLogs").inner_text() + page.locator("#logDetailContent").inner_text()
    assert not re.search(r"\blogs\.[a-zA-Z]", visible)
    assert not re.search(r"\{\w+\}", visible)
    assert page.locator("#logsStatus option").all_inner_texts()[1] != "Success"
