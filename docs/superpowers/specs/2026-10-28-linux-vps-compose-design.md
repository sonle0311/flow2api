# Linux VPS Compose with an authenticated browser desktop

The user requested a Docker Compose setup for a Linux VPS before the first deployment. The deployment contains the current local application changes, including browser-only account onboarding.

## Runtime

One Linux amd64 image installs ordinary Google Chrome, Xvfb, Fluxbox, x11vnc and noVNC. The application and browsers run as UID 1000. Chromium sandboxing is enabled in the VPS environment with the upstream Playwright seccomp allow list; privileged mode and extra capabilities are not required.

The entrypoint supervises the display, window manager, VNC service and app, stopping the app before the display to preserve profile shutdown. Only the app port is published, bound to host loopback by default. VNC stays on container loopback port 5900.

## Authentication and human login

The noVNC HTML page, library assets and binary WebSocket relay require the existing admin session. The WebSocket requires its HttpOnly cookie, exact same-origin Origin and a fixed RFB destination. Session revocation disconnects a live viewer. No passwords, keys or targets are passed in desktop URLs.

A human opens normal Chrome from account management, enters Google credentials through noVNC, and closes the dedicated profile windows. Only then does background profile validation begin. Closing the noVNC tab does not close Chrome or cancel the watcher. Google sign-in acceptance remains a manual verification step.

Local/default deployments do not enable the desktop. VPS Compose enables it, and the account dialog shows its desktop link only when the capability endpoint says it is available.

## Data and initial credentials

Named volumes retain `/app/data` and `/app/tmp`; database and per-account browser profiles persist across container recreation. `.env.vps` stores generated initial admin/API credentials with mode 600. Container-local TOML is generated from the canonical example at startup; an existing database remains authoritative for later settings.

Setup does not rotate existing credentials. Docker builds and deployment archives exclude local account databases, profiles, logs, environment keys, backups and private configuration. The deployment archive is source rather than an exported image so the VPS can build it without copying developer sessions.

## First access

The default access path is SSH forwarding from client port 18000 to VPS loopback port 8000, allowing login without a domain or exposed desktop ports. Later HTTPS reverse proxies must forward WebSockets and configure trusted proxy IPs so strict origin checks see the correct external scheme.

## Verification

The stack was built and run in Linux containers locally. Checks covered non-root sandboxed headed/headless Chrome, authenticated noVNC canvas rendering, synthetic cookie persistence through container recreation, and running the packaged setup helper from an extracted archive. No real VPS connection or Google login was performed during these deployment checks.
