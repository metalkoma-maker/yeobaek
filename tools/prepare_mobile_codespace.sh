#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if [[ "${CODESPACES:-}" != true ]]; then
  echo 'This setup is for a separate GitHub Codespace, not the production server.' >&2
  exit 1
fi
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm --prefix mobile ci --no-audit --no-fund
echo 'Ready: bash tools/start_mobile_codespace.sh'
