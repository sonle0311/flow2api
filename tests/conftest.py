"""Make browser tests behave the same alone as in the full suite.

Importing ``src.services.browser_captcha`` (which the application does) sets
PLAYWRIGHT_BROWSERS_PATH=0, i.e. "use the browsers bundled inside the playwright package". In the full
suite that import happens before the first browser test, so they find Chromium; run on its own, a
browser test used Playwright's default cache, found no Chromium and was skipped or failed. Setting
the same value up front removes the difference.
"""

import os

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")
