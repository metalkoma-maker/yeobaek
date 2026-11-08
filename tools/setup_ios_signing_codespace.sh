#!/usr/bin/env bash
set -euo pipefail

if [[ "${CODESPACES:-}" != true ]]; then
  echo '이 명령은 소설여백 모바일 GitHub Codespace에서만 실행하세요.' >&2
  exit 1
fi

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../mobile"
echo '소설여백 Expo 계정으로 로그인합니다. 인증 정보는 채팅에 보내지 마세요.'
npx --yes eas-cli@25.1.1 login
echo 'iOS production 서명 정보를 설정합니다. Apple 로그인은 Individual 계정의 Account Holder가 직접 진행해야 합니다.'
npx --yes eas-cli@25.1.1 credentials --platform ios
echo '서명 정보 설정이 끝났습니다. 결과만 코덱스 채팅에 알려주세요.'
