#!/usr/bin/env bash
set -euo pipefail

if [[ "${CODESPACES:-}" != true ]]; then
  echo '이 명령은 소설여백 모바일 GitHub Codespace에서만 실행하세요.' >&2
  exit 1
fi

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
mapfile -t keys < <(find "$repo/tools" "$repo/.ios-signing" -maxdepth 1 -type f -name 'AuthKey_*.p8' -print 2>/dev/null)
if (( ${#keys[@]} != 1 )); then
  echo '왼쪽 탐색기의 tools 폴더에 Apple에서 받은 AuthKey_*.p8 파일 하나만 넣어 주세요.' >&2
  exit 1
fi

read -r -p 'Apple API Key ID (10자리): ' key_id
read -r -p 'Apple Issuer ID (UUID): ' issuer_id
[[ "$key_id" =~ ^[A-Za-z0-9]{10}$ ]] || { echo 'Key ID 형식을 확인하세요.' >&2; exit 1; }
[[ "$issuer_id" =~ ^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$ ]] || { echo 'Issuer ID 형식을 확인하세요.' >&2; exit 1; }
openssl pkey -in "${keys[0]}" -noout >/dev/null 2>&1 || { echo 'Apple .p8 키 파일을 확인하세요.' >&2; exit 1; }

temp_dir=$(mktemp -d)
trap 'rm -rf -- "$temp_dir"' EXIT
mv -- "${keys[0]}" "$temp_dir/apple-api-key.p8"
chmod 600 "$temp_dir/apple-api-key.p8"
export EXPO_ASC_API_KEY_PATH="$temp_dir/apple-api-key.p8"
export EXPO_ASC_KEY_ID="$key_id"
export EXPO_ASC_ISSUER_ID="$issuer_id"
cd -- "$repo/mobile"
npx --yes eas-cli@27.5.0 submit --platform ios --profile production --id a35a32eb-b44b-477d-a2fc-eb6a58b23b33 --non-interactive --wait
