"""Instrument navigation must retain the existing console's state and destinations."""
import pytest

from test_i18n_browser import browser_page, ui_server, open_page, playwright_api


@pytest.mark.parametrize("destination, panel", [
    ("tokens", "Tokens"), ("settings", "Settings"),
    ("logs", "Logs"), ("integration", "Integration"),
])
def test_studio_rail_opens_the_requested_management_panel(browser_page, destination, panel):
    page, base = browser_page
    open_page(page, base + "/test")
    page.locator(f'[data-instrument-destination="{destination}"]').click()
    playwright_api.expect(page.locator("#panel" + panel)).to_be_visible()
    playwright_api.expect(page.locator("#tab" + panel)).to_have_attribute("aria-current", "page")


@pytest.mark.parametrize("width", [375, 1440])
def test_management_navigation_retains_inputs_and_modal_visibility(browser_page, width):
    page, base = browser_page
    page.set_viewport_size({"width": width, "height": 900})
    open_page(page, base + "/manage")
    page.locator("#tabSettings").click()
    page.locator("#cfgAdminUsername").fill("Keep local 保存")
    page.locator("[data-language-select]").select_option("vi")
    assert page.locator("#cfgAdminUsername").input_value() == "Keep local 保存"
    playwright_api.expect(page.locator("#tabSettings")).to_have_attribute("aria-current", "page")
    page.locator("#tabIntegration").click()
    page.locator("#integrationServerUrl").fill("https://example.invalid/flow")
    # Settings intentionally reload on entry; local integration inputs do not.
    page.locator("#tabLogs").click()
    page.locator("#tabIntegration").click()
    assert page.locator("#integrationServerUrl").input_value() == "https://example.invalid/flow"
    page.locator("#tabTokens").click()
    page.locator('button[onclick="openAddModal()"]').click()
    playwright_api.expect(page.locator("#addModal")).to_be_visible()
    page.locator('button[onclick="closeAddModal()"]').first.click()
    playwright_api.expect(page.locator("#addModal")).to_be_hidden()
    assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
