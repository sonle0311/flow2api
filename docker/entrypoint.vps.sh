#!/usr/bin/env bash
set -euo pipefail

export DISPLAY="${DISPLAY:-:99}"
screen="${XVFB_SCREEN:-1440x900x24}"
children=()
app_pid=''

cleanup() {
    trap - EXIT INT TERM
    # Let the application flush/close its browser profiles before terminating
    # the virtual display. Chrome losing X11 first can interrupt that handoff.
    if [[ -n "$app_pid" ]] && kill -0 "$app_pid" 2>/dev/null; then
        kill -TERM "$app_pid" 2>/dev/null || true
        for _ in {1..350}; do
            kill -0 "$app_pid" 2>/dev/null || break
            sleep 0.1
        done
    fi
    if ((${#children[@]})); then
        kill -TERM "${children[@]}" 2>/dev/null || true
        for pid in "${children[@]}"; do
            wait "$pid" 2>/dev/null || true
        done
    fi
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

if [[ "$(id -u)" == "0" ]]; then
    echo '[vps] Refusing to run the login browser as root.' >&2
    exit 1
fi

python /app/docker/prepare_vps_config.py
mkdir -p /app/data /app/tmp

# No TCP X11 listener and no remotely published VNC listener. The application
# relays desktop traffic only after validating its administrator session.
Xvfb "$DISPLAY" -screen 0 "$screen" -nolisten tcp -ac +extension RANDR &
children+=("$!")
ready=false
for _ in {1..100}; do
    if xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; then
        ready=true
        break
    fi
    kill -0 "${children[0]}" 2>/dev/null || break
    sleep 0.1
done
if [[ "$ready" != "true" ]]; then
    echo '[vps] Virtual display did not start.' >&2
    exit 1
fi

fluxbox >/tmp/flow2api-fluxbox.log 2>&1 &
children+=("$!")
x11vnc -display "$DISPLAY" -localhost -rfbport 5900 -forever -shared -nopw -quiet -noxdamage &
children+=("$!")

python - <<'PY'
import socket
import time

for attempt in range(100):
    try:
        with socket.create_connection(("127.0.0.1", 5900), timeout=0.2):
            break
    except OSError:
        time.sleep(0.1)
else:
    raise SystemExit("[vps] Internal desktop listener did not start")
PY

python /app/main.py &
app_pid="$!"
children+=("$app_pid")

# Exit when any supervised component exits; Docker's restart policy can then
# recover the whole stack rather than leaving an API with a broken desktop.
set +e
wait -n "${children[@]}"
status=$?
set -e
if [[ "$status" == "0" ]]; then
    status=1
fi
echo '[vps] A supervised component exited; shutting down the stack.' >&2
exit "$status"
