#!/usr/bin/env bash
# Separate Codespaces preview only; no deployment or production DB access.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if [[ "${CODESPACES:-}" != true || ! "${CODESPACE_NAME:-}" =~ ^[a-z0-9-]+$ ]]; then
  echo 'Run this launcher in your GitHub Codespace.' >&2
  exit 1
fi
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
fi
echo 'In PORTS, set 8001 to Public. Keep port protocol HTTP.'
echo "Preview: https://${CODESPACE_NAME}-8001.app.github.dev/"
exec .venv/bin/python -u tools/run_web_preview.py --port 8001
