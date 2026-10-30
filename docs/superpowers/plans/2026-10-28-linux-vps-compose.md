# Linux VPS with Docker Compose and browser desktop

**Goal:** Package the current application for a Linux amd64 VPS, with ordinary Chrome login accessible through an authenticated noVNC page.

**Architecture:** One non-root container runs Flow2API, Chrome, Xvfb, Fluxbox and a loopback-only VNC server. The existing admin session protects the noVNC page, static assets and binary WebSocket-to-RFB relay. Compose publishes only the app port, bound to loopback by default for SSH tunneling; named volumes retain database and browser profiles. A setup helper generates private initial credentials and a source bundle excludes local session material.

**Stack:** Docker Compose v2, Python/FastAPI, Debian/Chrome, Xvfb/Fluxbox/x11vnc, noVNC.

- [x] Add tests and implement non-root Dockerfile, Compose, bootstrap config and supervised startup, with Chrome sandbox support.
- [x] Add tests and implement admin-protected desktop page/assets/config/WebSocket relay, including same-origin and expired-session checks.
- [x] Add zh/en/vi desktop UI, connection states and optional VPS desktop link in the existing login dialog.
- [x] Add tested setup/package helpers, exclude secrets/profiles from Docker and deployment archives, and document first launch, SSH access, login, updates and backup.
- [x] Build/run Linux container locally, verify normal Chrome can run with its sandbox, authenticated noVNC/RFB, service cleanup and persistence with synthetic data only.
- [x] Run relevant application regressions, review the result and generate a deployment archive. Do not claim deployment on a real VPS without access to it.

The user requested Linux VPS Compose setup. Existing local changes and profiles must be preserved. No commit or push was requested.

## Verification evidence

- Full repository suite after correcting fake-browser closure/timing assumptions: 434 passed, 130 subtests passed.
- New VPS backend/UI/setup/reference focused suite: 51 passed; Docker/setup helper tests: 15 passed.
- Linux image built and ran as UID1000. Ordinary headed Chrome stayed running without automation/debugging/no-sandbox flags; sandboxed headless Chrome rendered a synthetic fixture.
- Real authenticated noVNC viewer rendered its canvas in Vietnamese with zero JavaScript errors; only loopback app port was published.
- A synthetic expiryless cookie survived container recreation in a named data volume. No Google login was performed.
- Extracted deployment archive ran setup_vps.py successfully in a second isolated Compose project and reached healthy status.
- Smoke containers and their synthetic-data volumes were removed by exact project name after verification. The existing Windows local server and account data were preserved.
- Shell/JS syntax, Python compilation and git diff checks passed.
