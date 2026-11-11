"""Instrument Studio exercises real browser actions against local mock APIs only."""

from test_i18n_browser import browser_page, open_page, playwright_api, ui_server


CATALOG = [
    "omni-1.2-flash",
    "omni-1.2-flash-8s-landscape",
    "omni-1.2-flash-8s-portrait",
    "omni-1.2-flash-15s-portrait",
    "future-video-model",
    "veo_3_1_t2v_fast",
]


def open_studio(page, base):
    page.route("**/v1/models", lambda route: route.fulfill(json={
        "data": [{"id": model, "description": model} for model in CATALOG],
    }))
    open_page(page, base + "/test")
    page.locator("#apiKey").fill("synthetic-studio-key")
    page.locator("#apiKey").dispatch_event("change")
    page.wait_for_function("document.querySelectorAll('.model-item').length === 6")


def test_studio_parameters_only_select_published_combinations(browser_page):
    page, base = browser_page
    requests = []

    def complete(route):
        requests.append(route.request.post_data_json)
        route.fulfill(content_type="text/event-stream", body=(
            'data: {"choices":[{"delta":{"content":"![Result](/synthetic.png)"}}]}\n\n'
            'data: [DONE]\n\n'
        ))

    page.route("**/v1/chat/completions", complete)
    open_studio(page, base)
    page.locator("#studioModel").select_option("omni-1.2-flash")
    page.locator("#studioDuration").select_option("15")
    assert page.locator("#studioAspect").input_value() == "9:16"
    assert page.locator("#studioAspect option").all_text_contents() == ["9:16"]
    assert page.evaluate("STATE.selectedModel") == "omni-1.2-flash-15s-portrait"
    page.locator("#promptInput").fill("Synthetic scene")
    page.locator("#btnGenerate").click()
    playwright_api.expect(page.locator("#statusDot")).to_have_class("status-dot status-done")
    assert requests[0]["model"] == "omni-1.2-flash-15s-portrait"
    assert set(page.locator(".model-item").evaluate_all(
        "items => items.map(item => item.dataset.model)"
    )) == set(CATALOG)
    page.locator('.model-item[data-model="future-video-model"]').click()
    assert page.evaluate("STATE.selectedModel") == "future-video-model"
    playwright_api.expect(page.locator("#studioParameters")).to_be_hidden()


def test_studio_cancel_preserves_composer_and_allows_retry(browser_page):
    page, base = browser_page
    pending = []
    page.route("**/v1/chat/completions", lambda route: pending.append(route))
    open_studio(page, base)
    page.locator("#studioModel").select_option("omni-1.2-flash")
    page.locator("#promptInput").fill("Keep my prompt")
    page.locator("#btnGenerate").click()
    playwright_api.expect(page.locator("#btnCancel")).to_be_visible()
    page.locator("#btnCancel").click()
    playwright_api.expect(page.locator("#statusText")).to_have_text("Cancelled")
    playwright_api.expect(page.locator("#btnGenerate")).to_be_enabled()
    assert page.locator("#promptInput").input_value() == "Keep my prompt"
    assert page.evaluate("STATE.generating") is False
    pending[0].abort()


def test_studio_remembers_api_key_and_composer_accepts_image_paste(browser_page):
    page, base = browser_page
    open_studio(page, base)
    page.reload(wait_until="networkidle")
    assert page.locator("#apiKey").input_value() == "synthetic-studio-key"
    page.locator("#studioModel").select_option("omni-1.2-flash")
    page.locator("#promptInput").fill("Keep text when pasting")
    page.locator("#promptInput").evaluate("""element => {
        const data = new DataTransfer();
        data.items.add(new File(['reference'], 'reference.png', {type: 'image/png'}));
        element.dispatchEvent(new ClipboardEvent('paste', {clipboardData: data, bubbles: true, cancelable: true}));
    }""")
    playwright_api.expect(page.locator(".image-preview-item")).to_have_count(1)
    assert page.locator("#promptInput").input_value() == "Keep text when pasting"
    page.locator(".remove-btn").click()
    playwright_api.expect(page.locator(".image-preview-item")).to_have_count(0)


def test_studio_responsive_controls_and_catalog_keyboard_access(browser_page):
    page, base = browser_page
    open_studio(page, base)
    page.set_viewport_size({"width": 375, "height": 812})
    page.locator("#studioModel").select_option("omni-1.2-flash")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    title = page.locator(".section-title").first
    title.focus()
    title.press("Enter")
    assert "collapsed" in title.get_attribute("class")
    assert title.evaluate("element => element.nextElementSibling.classList.contains('hidden')")
    title.press("Enter")
    page.locator('.model-item[data-model="future-video-model"]').focus()
    page.locator('.model-item[data-model="future-video-model"]').press("Enter")
    assert page.evaluate("STATE.selectedModel") == "future-video-model"


def test_studio_image_and_video_mode_parameters_follow_catalog(browser_page):
    page, base = browser_page
    ids = [
        "gemini-3.1-flash-image", "gemini-3.1-flash-image-landscape",
        "gemini-3.1-flash-image-portrait-2k", "gemini-3.1-flash-image-landscape-4k",
        "veo-3.1-fast", "veo-3.1-fast-8s-landscape",
        "veo-3.1-fast-i2v-4s-portrait", "veo-3.1-fast-extend-8s-landscape",
    ]
    page.route("**/v1/models", lambda route: route.fulfill(json={
        "data": [{"id": model, "description": model} for model in ids],
    }))
    open_page(page, base + "/test")
    page.locator("#apiKey").fill("synthetic-key")
    page.locator("#apiKey").dispatch_event("change")
    page.wait_for_function("document.querySelectorAll('.model-item').length === 8")
    page.locator("#studioModel").select_option("gemini-3.1-flash-image")
    page.locator("#studioAspect").select_option("9:16")
    assert page.locator("#studioSize").input_value() == "2K"
    assert page.locator("#studioSize option").all_text_contents() == ["2K"]
    assert page.evaluate("STATE.selectedModel") == "gemini-3.1-flash-image-portrait-2k"
    page.locator("#studioModel").select_option("veo-3.1-fast")
    page.locator("#studioMode").select_option("i2v")
    assert page.locator("#studioDuration").input_value() == "4"
    assert page.locator("#studioAspect").input_value() == "9:16"
    playwright_api.expect(page.locator("#imageUploadGroup")).to_be_visible()
    page.locator("#studioMode").select_option("extend")
    assert page.evaluate("STATE.selectedModel") == "veo-3.1-fast-extend-8s-landscape"
    playwright_api.expect(page.locator("#videoSourceGroup")).to_be_visible()
    playwright_api.expect(page.locator("#imageUploadGroup")).to_be_hidden()


def test_studio_raw_alias_does_not_claim_concrete_parameters(browser_page):
    page, base = browser_page
    ids = [
        "gemini-3.1-flash-image", "gemini-3.1-flash-image-landscape",
        "gemini-3.1-flash-image-portrait", "gemini-3.1-flash-image-landscape-2k",
    ]
    requests = []
    page.route("**/v1/models", lambda route: route.fulfill(json={
        "data": [{"id": model, "description": model} for model in ids],
    }))

    def complete(route):
        requests.append(route.request.post_data_json)
        route.fulfill(content_type="text/event-stream", body=(
            'data: {"choices":[{"delta":{"content":"![Result](/synthetic.png)"}}]}\n\n'
            'data: [DONE]\n\n'
        ))

    page.route("**/v1/chat/completions", complete)
    open_page(page, base + "/test")
    page.locator("#apiKey").fill("synthetic-key")
    page.locator("#apiKey").dispatch_event("change")
    page.wait_for_function("document.querySelectorAll('.model-item').length === 4")
    page.locator('.model-item[data-model="gemini-3.1-flash-image"]').click()
    playwright_api.expect(page.locator("#studioParameters")).to_be_hidden()
    playwright_api.expect(page.locator("#studioParameterNote")).to_be_visible()
    assert page.evaluate("STATE.selectedModel") == "gemini-3.1-flash-image"
    page.locator("#promptInput").evaluate("""element => {
        const data = new DataTransfer();
        data.items.add(new File(['reference'], 'reference.png', {type: 'image/png'}));
        element.dispatchEvent(new ClipboardEvent('paste', {clipboardData: data, bubbles: true, cancelable: true}));
    }""")
    playwright_api.expect(page.locator(".image-preview-item")).to_have_count(1)
    page.locator("[data-language-select]").select_option("vi")
    playwright_api.expect(page.locator("#studioParameters")).to_be_hidden()
    playwright_api.expect(page.locator(".image-preview-item")).to_have_count(1)
    page.locator("#btnGenerate").click()
    playwright_api.expect(page.locator("#btnGenerate")).to_be_enabled()
    assert requests[0]["model"] == "gemini-3.1-flash-image"
    assert "generationConfig" not in requests[0]
    page.locator("#studioUseParameters").click()
    playwright_api.expect(page.locator("#studioParameters")).to_be_visible()
    assert page.evaluate("STATE.selectedModel") == "gemini-3.1-flash-image-landscape"
    playwright_api.expect(page.locator(".image-preview-item")).to_have_count(1)
    page.evaluate("selectModel('gemini-3.1-flash-image-portrait-4k')")
    playwright_api.expect(page.locator("#studioUseParameters")).to_be_hidden()


def test_studio_placeholder_cannot_mask_an_active_model(browser_page):
    page, base = browser_page
    open_studio(page, base)
    placeholder = page.locator('#studioModel option[value=""]')
    playwright_api.expect(placeholder).to_be_enabled()
    page.locator("#studioModel").select_option("omni-1.2-flash")
    playwright_api.expect(placeholder).to_be_disabled()
    page.locator("[data-language-select]").select_option("vi")
    playwright_api.expect(placeholder).to_be_disabled()
    assert page.locator("#studioModel").input_value() == "omni-1.2-flash"
    assert page.evaluate("STATE.selectedModel") == "omni-1.2-flash-8s-landscape"
    playwright_api.expect(page.locator("#btnGenerate")).to_be_enabled()
