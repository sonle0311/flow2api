"""The console's Agent skill tab: commands follow the server URL, nothing unsafe reaches a shell."""
import re

import pytest

from test_i18n_browser import browser_page, ui_server, open_page, playwright_api


def command(page, element):
    return page.locator(element).inner_text()


def test_commands_follow_the_server_url(browser_page):
    page, base = browser_page
    open_page(page, base + "/manage#skills")
    playwright_api.expect(page.locator("#panelSkills")).to_be_visible()
    assert page.locator("#skillsServerUrl").input_value() == base
    assert f"FLOW2API_BASE_URL={base}\\n" in command(page, "#skillsCmdKey")
    assert command(page, "#skillsCmdClaude") == "mkdir -p ~/.claude/skills && unzip -o ~/Downloads/flow2api-skill.zip -d ~/.claude/skills"
    assert "~/.agents/skills" in command(page, "#skillsCmdAgents")
    assert page.locator("#skillsDownload").get_attribute("href") == "/api/admin/skills/flow2api/download"
    # A trailing /v1 or slash is not part of the server root the skill expects.
    page.locator("#skillsServerUrl").fill("https://api.example.com/flow/v1/")
    assert "FLOW2API_BASE_URL=https://api.example.com/flow\\n" in command(page, "#skillsCmdKey")


@pytest.mark.parametrize("invalid", [
    "javascript:alert(1)", "https://user:pass@example.com", "https://example.com?key=secret",
    "https://example.com/$(touch pwned)", "https://example.com/a'b", "https://example.com/a b;rm",
])
def test_an_address_that_could_alter_the_shell_command_is_refused(browser_page, invalid):
    page, base = browser_page
    open_page(page, base + "/manage#skills")
    page.locator("#skillsServerUrl").fill(invalid)
    assert page.locator("#skillsUrlError").inner_text()
    key_command = command(page, "#skillsCmdKey")
    assert "<SERVER_URL>" in key_command and "pwned" not in key_command and "alert" not in key_command


def test_copy_uses_the_clipboard_and_refuses_a_key_command_without_a_valid_address(browser_page):
    page, base = browser_page
    open_page(page, base + "/manage#skills")
    page.evaluate("""() => {
        window.copied = [];
        Object.defineProperty(navigator, 'clipboard', {configurable: true, value: {writeText: async text => { window.copied.push(text); }}});
    }""")
    page.locator('[data-skills-copy="skillsCmdCheck"]').click()
    assert page.evaluate("window.copied") == [command(page, "#skillsCmdCheck")]
    assert page.locator("#skillsCopyStatus").inner_text()
    page.locator("#skillsServerUrl").fill("not a url")
    page.locator('[data-skills-copy="skillsCmdKey"]').click()
    assert page.evaluate("window.copied.length") == 1


@pytest.mark.parametrize("locale", ["en", "vi", "zh-CN"])
def test_every_language_renders_the_panel_without_raw_keys(browser_page, locale):
    page, base = browser_page
    open_page(page, base + "/manage#skills")
    page.locator("[data-language-select]").select_option(locale)
    text = page.locator("#panelSkills").inner_text()
    assert not re.search(r"\bskills\.[A-Za-z0-9]+", text)
    assert page.locator("#skillsPromptExample").inner_text().strip()
    assert page.locator("#tabSkills").inner_text().strip()
    assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
