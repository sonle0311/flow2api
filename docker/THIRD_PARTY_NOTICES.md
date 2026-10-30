# Third-party notice

`seccomp.chrome.json` is copied from the Microsoft Playwright project's
`utils/docker/seccomp_profile.json`:

https://github.com/microsoft/playwright/blob/main/utils/docker/seccomp_profile.json

The upstream project is licensed under Apache License 2.0. A copy is included
in `licenses/PLAYWRIGHT-APACHE-2.0.txt`. The profile is used to run Chromium's
sandbox in the non-root VPS container without privileged mode.

Chrome, noVNC and other operating system packages are installed from their
distribution repositories during the image build. Their licenses and notices
are supplied with those packages inside the image.
