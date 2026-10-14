#!/usr/bin/env bash
# Starts only a synthetic Flask server and Metro. Ports remain private until user shares them.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if [[ "${CODESPACES:-}" != true || ! "${CODESPACE_NAME:-}" =~ ^[a-z0-9-]+$ ]]; then
  echo 'Run inside a separate GitHub Codespace. No production services are started.' >&2
  exit 1
fi
export EXPO_PUBLIC_TEST_API_URL="https://${CODESPACE_NAME}-8000.app.github.dev"
export EXPO_PACKAGER_PROXY_URL="https://${CODESPACE_NAME}-8081.app.github.dev"
export YEOBAEK_EXPO_LINK="exps://${CODESPACE_NAME}-8081.app.github.dev"
export YEOBAEK_TEST_RUN_ID="$(.venv/bin/python -c 'import secrets; print(secrets.token_hex(16))')"
echo 'In PORTS set 8000 and 8081 to Public (only fake data; Metro source is accessible).'
echo 'Keep port protocol HTTP: GitHub provides the external HTTPS URL.'
echo "On your iPhone open: ${EXPO_PUBLIC_TEST_API_URL}/_mobile/open"
.venv/bin/python -u tools/run_mobile_test.py &
test_api_pid=$!
cleanup() {
  kill "$test_api_pid" 2>/dev/null || true
  wait "$test_api_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
# Confirm this exact new runner is serving HTTP before starting Metro.
.venv/bin/python tools/check_mobile_test_server.py "$test_api_pid"
cd mobile
npm start -- --localhost --port 8081
