# 운영 전 웹 미리보기

PR #4의 실제 Flask와 웹 화면을 새 가짜 DB로 실행합니다. 원고 3개와 테스트 계정이 준비되며 화면 위에 노란색 미리보기 안내가 표시됩니다. 운영 배포/운영 원고/기존 모바일 개발 서버를 사용하지 않습니다.

## GitHub 전달 주소가 열리지 않을 때: 임시 Cloudflare 주소

Codespaces 내부에서는 응답하지만 외부 브라우저에서 404 또는 다운로드 창이 반복되면, 같은 앱을 Cloudflare Quick Tunnel로 확인할 수 있습니다. 이 방법은 GitHub의 Public 포트/Continue 화면을 사용하지 않습니다. Cloudflare 계정이나 도메인은 필요하지 않습니다. URL을 아는 사람은 가짜 데이터 미리보기에 접근할 수 있습니다.

기존 Python 가상환경이 준비된 Codespaces에서 새 터미널에 다음 블록을 한 번에 붙여넣습니다. 별도 임시 복사본을 사용하므로 기존 모바일 브랜치나 미리보기 worktree를 변경하지 않습니다. 이 저장소의 Codespaces 기본 위치를 사용합니다.

```bash
preview_dir=$(mktemp -d /tmp/yeobaek-preview.XXXXXX) &&
git clone --depth 1 --branch codex/web-download-order-20261015 https://github.com/metalkoma-maker/yeobaek.git "$preview_dir" &&
/workspaces/yeobaek/.venv/bin/python -u "$preview_dir/tools/start_web_preview_tunnel.py"
```

실행기는 고정 버전 cloudflared를 임시 폴더에 내려받아 SHA256을 검증합니다. 시스템에 설치하거나 Cloudflare에 로그인하지 않습니다. 이미 사용 중인 포트를 공개하지 않도록 새 루프백 소켓을 먼저 확보하고, 그 소켓을 새 가짜 DB 서버에 직접 전달합니다. 기존 터널 설정과 TUNNEL_* 환경 설정은 사용하지 않습니다.

`미리보기 응답·로그인 확인 완료` 다음에 표시되는 `https://…trycloudflare.com/`을 엽니다. 주소 출력 전에 현재 실행의 진단 표식, HTML 형식, 테스트 로그인과 원고 목록을 검사합니다. 이 검사는 Codespaces에서 수행하므로 PC/아이폰에서 실제 화면이 열리는지도 확인해야 합니다. 실패하면 성공 링크를 출력하지 않고 시작한 프로세스를 종료합니다.

서버는 명시한 임시 HTTPS 주소에 맞춰 Secure 쿠키와 Origin/CSRF 검사를 유지합니다. 운영 주소나 임의의 외부 주소는 `--public-origin`으로 받을 수 없습니다. 테스트 글만 입력하세요. Ctrl+C 또는 터미널 종료로 연결과 새 가짜 DB를 정리합니다. 다음 실행은 새 URL과 초기 원고로 시작합니다. Quick Tunnel은 임시 개발용이며 가동 시간은 보장되지 않습니다. 기존 Codespaces 실행시간 한도는 적용됩니다.

검증 범위: 로컬의 실제 Flask 서버, 소켓 상속, 로그인·쿠키·Origin·CSRF·계정 순서 공유·DB 격리·종료 정리를 자동 테스트합니다. CI는 외부 터널을 게시하지 않습니다. Cloudflare 외부 연결은 사용자의 Codespaces에서 실행 시 검사합니다.

## 기존 Codespaces에서 처음 열기

기존 Codespace를 연 뒤 터미널에 아래 한 줄을 실행합니다. 원래 체크아웃한 모바일 브랜치는 그대로 두고 별도 Git worktree에서 미리보기를 실행합니다. fetch나 worktree 생성이 실패하면 뒤 명령을 실행하지 않습니다.

```bash
cd /workspaces/yeobaek && git fetch origin codex/web-download-order-20261015 && git worktree add --detach /tmp/yeobaek-web-preview-pr4 FETCH_HEAD && bash /tmp/yeobaek-web-preview-pr4/tools/start_web_preview.sh
```

초기 실행은 별도 가상환경에 기존 requirements.txt의 패키지를 설치합니다. 서버가 시작되면 PORTS에서 **8001을 Public**으로 설정합니다. Port protocol은 HTTP로 유지하며 GitHub가 외부 HTTPS를 제공합니다. 이 포트는 가짜 원고 테스트만 공유합니다.

터미널에 출력된 `https://<이 Codespace 이름>-8001.app.github.dev/`를 열고 로그인 버튼을 누릅니다. 계정 입력란은 아래 공개 테스트 계정으로 채워집니다.

```text
mobile-test@example.com
test-password-123
```

원고 목록에서 드래그하여 이동하고, 새로고침이나 같은 계정의 다른 브라우저에서 순서를 확인합니다. TXT 내려받기를 열어 첫 줄의 한국시간과 초 표시를 확인합니다. 실제 계정이나 실제 원고는 입력하지 않습니다.

## 다시 시작할 때

같은 worktree가 이미 있으면 생성 명령을 반복하지 말고 아래 명령만 실행합니다.

```bash
bash /tmp/yeobaek-web-preview-pr4/tools/start_web_preview.sh
```

미리보기 코드가 바뀌면 실행 터미널에서 Ctrl+C로 멈춘 뒤 별도 worktree만 아래처럼 갱신합니다. 로컬 변경이 충돌하면 강제로 초기화하지 않습니다.

```bash
git -C /tmp/yeobaek-web-preview-pr4 fetch origin codex/web-download-order-20261015 && git -C /tmp/yeobaek-web-preview-pr4 checkout --detach FETCH_HEAD && bash /tmp/yeobaek-web-preview-pr4/tools/start_web_preview.sh
```

Ctrl+C로 중지하면 새 가짜 DB는 삭제되며 다음 실행은 처음의 원고 3개로 시작합니다. Codespaces가 정지하면 링크도 멈춥니다. Public 포트 설정은 재시작 후 확인합니다. 테스트가 끝나면 8001을 Private으로 되돌리고 필요 없는 Codespace는 Stop합니다. 기존 Codespaces 실행시간/저장공간 한도가 적용됩니다.

로컬 개발 검증에서는 Python 가상환경을 준비한 뒤 `python tools/run_web_preview.py --port 8001`로 루프백에서만 실행할 수 있습니다. 이 주소는 클라우드 Codex 밖에서 직접 접속하는 공개 주소가 아닙니다.
