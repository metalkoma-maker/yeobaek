# 여백 아이폰 테스트 앱 — PC 없이 클라우드에서

Expo·React Native 첫 버전입니다. 로그인, 내 원고 목록과 최근 수정일, 새 원고/작성, 0.7초 자동저장, 전체 글자 수/오늘 증감을 구현했습니다. 웹과 같은 Flask 계정·원고 API, 세션 쿠키, CSRF, version/409 충돌 검사를 사용합니다. 테스트는 새 임시 DB와 가짜 계정으로만 합니다. 운영 계정·DB·원고를 복사하지 않습니다.

## 무엇이 완료됐고 무엇이 필요한가

| 항목 | 상태 |
| --- | --- |
| 기존 웹 수동 배포 | 기존 구성 유지. 모바일 실행과 별개 |
| 모바일 기능/저장 보호 | 구현 및 가짜 데이터 검증 완료 |
| 현재 Codex 내부 Metro | 실제 상태 응답/iOS manifest 생성 확인. 아이폰 외부 연결은 미검증 |
| 현재 Codex 상시 모바일 서버 | 공개 포트/항상 실행 보장 없음. 세션 종료 후 유지된다고 가정할 수 없음 |
| 현재 Codex ngrok 터널 | 소스의 제3자 공개 우려로 자동 승인 검토가 거부해 연결 시험 미실행 |
| PC 없이 iPhone 테스트 | 별도 GitHub Codespaces 실행 중 가능하도록 구성. Expo 무료 계정 및 실제 아이폰 연결 확인 필요 |

**SDK 57**을 사용합니다. 2026-10-13 사용자의 실제 iPhone Expo Go 화면이 지원 SDK를 57.0.0으로 표시했고, SDK54 프로젝트를 거부한 것을 확인해 의존성을 맞췄습니다. 앞서 읽은 공식 문서의 App Store 지원 버전 설명과 실기기가 달랐으므로 이 앱은 실기기 정보를 우선합니다. Expo Go의 지원 SDK와 프로젝트 SDK가 같아야 합니다. Expo Go로 테스트하는 현재 경로에 Mac, Xcode, 유료 Apple 개발자 계정은 필요하지 않습니다. [SDK 불일치 개념](https://docs.expo.dev/troubleshooting/expo-go-version-mismatch/)

## 권장: GitHub Codespaces 한 개에서 앱 + 가짜 웹 실행

Codespaces는 현재 Codex 작업 공간과 다른 클라우드 컴퓨터입니다. Codex에서 수정해 GitHub PR에 올린 코드를 Codespaces에서 실행합니다. PC가 꺼져 있어도 Codespaces가 실행 중이면 아이폰에서 테스트할 수 있습니다. 웹의 수동 배포 버튼이 앱 서버를 실행해 주는 것은 아닙니다. 운영 서버에는 설치하지 않습니다.

### 1. 아이폰과 무료 Expo 계정

1. iPhone App Store에서 **Expo Go**를 설치합니다. 현재 프로젝트 SDK57과 앱에 표시되는 지원 SDK가 같은지 확인합니다. 불일치 오류가 나오면 그 화면의 버전을 기준으로 프로젝트를 맞춥니다.
2. https://expo.dev/signup 에서 무료 Expo 계정을 만듭니다. 기존 계정이 있으면 그대로 사용합니다.
3. Expo Go의 계정 메뉴에서 로그인합니다. 같은 계정으로 아래 Codespaces의 Expo CLI도 로그인해야 합니다. 비밀번호/인증 토큰을 채팅이나 저장소에 넣지 않습니다. [실제 iPhone의 동일 계정 로그인 요구](https://docs.expo.dev/troubleshooting/expo-go-sign-in-required/)

### 2. 별도 Codespace 만들기 (iPhone Safari에서도 가능)

1. 모바일 변경 PR을 확인해 병합합니다. 앱을 시험하기만 한다면 PR 브랜치에서 Codespace를 만들어도 됩니다. 웹 배포 workflow는 실행하지 않습니다.
2. GitHub 여백 저장소 → **Code → Codespaces → ⋯ → New with options**로 이동합니다.
3. 모바일 코드가 있는 Branch를 선택합니다. Dev container configuration은 **Yeobaek iPhone test (synthetic data)**, Machine type은 **2-core**를 선택합니다. Create codespace를 누릅니다.
4. 초기 설치가 끝날 때까지 기다립니다. 이 설정은 Python 가상환경과 mobile 의존성만 준비합니다. Flask 앱을 가져오거나 DB를 만들거나 운영에 접속하지 않습니다.
5. 설치 오류가 있거나 기본 설정으로 만들었다면 터미널에서 다음 한 줄을 실행합니다. 아래 명령은 Windows/운영 SSH가 아닌 **Codespaces 웹 터미널**에 입력합니다.

```bash
bash tools/prepare_mobile_codespace.sh
```

### 3. 같은 Expo 계정으로 로그인하고 서버 시작

Codespaces 터미널에서 저장소 루트에 있는 상태로 한 줄씩 실행합니다. 비밀번호 입력값은 터미널의 로그인 질문에만 입력합니다.

```bash
cd mobile
```

```bash
npx expo login
```

```bash
npx expo whoami
```

Expo Go와 같은 계정인지 확인합니다.

```bash
cd ..
```

```bash
bash tools/start_mobile_codespace.sh
```

이 명령은 별도 Codespaces에서만 동작합니다. 가짜 계정/원고를 넣은 새 임시 DB로 Flask를 실행하고 Metro를 실행합니다. 8000은 테스트 API, 8081은 Expo 서버입니다. 앱의 API 주소는 해당 Codespace에 맞춰 자동 지정합니다. 시작 때마다 가짜 DB와 원고 ID가 새로 만들어집니다.

### 4. 아이폰에서 접근할 두 포트 공유

Codespaces 아래 **PORTS** 탭에서 `8000`, `8081` 두 행의 **Port Visibility → Public**을 각각 선택합니다. 없으면 Add port로 추가합니다. 기본은 Private이며 실행 스크립트는 공개 설정을 자동 변경하지 않습니다.

이는 해당 테스트 API와 Metro 코드가 URL을 아는 사람에게 공개되는 설정입니다. 저장소 소스와 가짜 데이터만 공유하고 실제 계정/원고/비밀 설정은 사용하지 않습니다. 테스트 종료 때 두 포트를 Private로 되돌리고 Codespace를 중지합니다. 기관 정책이 Public을 금지하면 이 방식은 사용할 수 없습니다. GitHub 토큰을 Expo 앱에 넣어 Private 포트를 우회하지 않습니다.

**Port protocol은 HTTP 그대로** 둡니다. 외부의 `https://...app.github.dev` 주소는 GitHub가 TLS를 제공합니다. 내부 Flask/Metro를 TLS 서버로 바꾸지 않습니다. [공식 포트 공유 안내](https://docs.github.com/en/codespaces/developing-in-a-codespace/forwarding-ports-in-your-codespace)

### 5. 같은 아이폰에서 앱 열기

1. 터미널에 출력된 `https://...-8000.app.github.dev/_mobile/open` 링크를 iPhone Safari에서 엽니다.
2. **Expo Go에서 여백 열기**를 누릅니다. 같은 폰으로 QR을 찍을 필요 없이 HTTPS용 `exps://` 링크로 앱을 엽니다. Expo 터미널의 QR 대신 이 버튼을 사용합니다.
3. 앱은 테스트 API 주소를 자동 입력합니다. 다음 가짜 계정으로 로그인합니다.

```text
이메일: mobile-test@example.com
비밀번호: test-password-123
```

4. 기본 가짜 원고를 열고 작성합니다. 입력을 멈춘 뒤 `저장됨`을 확인합니다.
5. Safari에서 같은 시작 페이지의 **테스트 웹 열기**를 눌러 같은 가짜 계정으로 로그인합니다. 앱과 웹에서 같은 원고를 보는지 확인합니다.

Expo 무료 계정은 앱을 여는 계정이고 위 가짜 Flask 계정은 원고에 로그인하는 계정입니다. GitHub 계정까지 총 세 역할이 있습니다. 실제 여백 운영 로그인 정보는 입력하지 않습니다. 원고 API 구조가 동일하다는 검증과 운영 DB를 직접 연결했다는 것은 다릅니다. 현재 앱은 지정된 Codespaces 테스트 API 또는 로컬 테스트 서버만 허용하고, 가짜 서버 표식도 로그인 전에 확인합니다. 운영 API 연결은 추후 별도로 검토합니다.

## PC를 끈 뒤 유지되는 범위와 비용

- PC가 꺼져도 별도 Codespace가 실행 중이면 앱의 코드/가짜 API를 제공합니다. Codespace가 정지되면 새 앱 로딩과 서버 저장이 중단됩니다. 이미 열어 쓴 내용은 기기에 보관하고 다시 저장할 수 있습니다.
- 기본 idle timeout은 30분이며 사용자 설정에서 최대 240분까지 가능합니다. GitHub Settings → Codespaces의 timeout을 필요한 테스트 길이만큼 설정합니다. 중지 후에는 Codespace를 다시 시작하고 위 시작 명령을 다시 실행합니다. 재시작 뒤 가짜 DB는 새 DB이므로 이전 테스트 원고가 서버에 이어지는 것은 아닙니다. [공식 timeout 안내](https://docs.github.com/en/codespaces/setting-your-user-preferences/setting-your-timeout-period-for-github-codespaces)
- GitHub Free 개인 계정의 월 무료분은 **120 core-hours**와 **15 GB-month**입니다. 2-core면 실행 시간 약 **60시간**에 해당합니다. 초과 시 2-core 계산 비용은 **시간당 USD 0.18**, 저장소는 **GB-month당 USD 0.07**입니다. 멈춘 Codespace도 저장공간을 사용합니다. 결제 수단/예산 설정에 따라 초과 시 중지되거나 청구될 수 있으므로 Billing에서 확인하고, 테스트 뒤 Stop합니다. [공식 비용](https://docs.github.com/en/billing/concepts/product-billing/github-codespaces)
- Expo 계정/호환되는 Expo Go로 테스트하는 데 Apple 개발자 가입이나 iOS 빌드 비용은 필요하지 않습니다. 무료 플랜의 현재 제한은 가입 화면에서 확인합니다.
- **24시간 항상 실행**이 필요하면 Codespaces 세션 방식으로 보장할 수 없습니다. 별도의 상시 개발/테스트 서버와 고정 HTTPS 연결이 필요하며 서버·스토리지 비용이 별도로 생깁니다. 기존 운영 서버나 기존 배포 VPN 정책을 이 목적으로 바꾸지 않았습니다.

EAS Update로 앱 JavaScript를 게시하면 Metro를 항상 실행할 필요를 줄일 수 있습니다. 다만 사용자 소유 Expo 프로젝트/게시 인증이 필요하고, 로그인·자동저장을 제공하는 별도 API 서버는 여전히 필요합니다. 앱 번들만 게시해서 원고 API까지 실행되는 것은 아닙니다. iPhone의 Expo Go에서는 본인/소속 조직의 프로젝트만 로딩할 수 있다는 현재 제한도 있습니다. 이번에는 이 추가 게시 구성을 만들지 않았습니다. [EAS Update 제한](https://expo.dev/changelog/expo-go-loading-changes-may-2026), [Expo 비용](https://expo.dev/pricing)

## 저장 보호와 실제 아이폰 검증

- 공백 제외/유니코드 코드 포인트 기준 글자 수. 오늘 증감은 한국시간, 저장 대기 중 입력 포함. 본문 10/12/14/16/18pt, 기본 12pt.
- 기기 임시본을 서버/계정/원고별로 순서대로 보관. 기기 저장 실패 시 서버 전송 중단. PUT 하나씩, version 필수. 저장 중 추가 입력/뒤늦은 GET이 현재 입력을 바꾸지 않음.
- 저장 실패 시 자동 재시도 중단. 사용자가 다시 저장. 409는 A/B 비교로 처리하고 원고를 자동 덮어쓰지 않음. B 불러오기는 명시적 저장 전까지 서버에 반영되지 않음. A 유지 뒤 A를 편집/저장해도 최근 B 별도 복구본을 보존.
- 미저장/충돌 상태에서 목록 이동·로그아웃은 차단. 인증 만료 시 입력을 유지하며 같은 계정 재로그인 후 명시적 저장.
- 기기 임시본은 종단간 암호화되지 않음. Expo Go 삭제/데이터 삭제/강제 종료 직전 아직 완료되지 않은 기기 저장은 보장하지 못함. 서버의 기존 수정이력 50개는 테스트 웹에서 확인.

실기기에서 다음을 확인합니다: 로그인/새 원고/최근 수정일, 한글 조합과 반복 삭제, 입력 후 자동저장, 비행기 모드에서 실패한 입력 유지, 인터넷 복구 후 재시도, Safari와 동시 편집 때 409, B 불러온 뒤 저장 전 서버 불변, 앱 종료 후 기기본 복구, iOS 키보드와 쿠키 유지. 실제 원고는 사용하지 않습니다. Codespace를 중지하는 대신 아이폰 인터넷만 끊어야 같은 가짜 DB로 연결 복구를 검증할 수 있습니다.

## 개발 검증

저장소 루트:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

mobile 폴더:

```bash
npm run typecheck
```

```bash
npm test
```

```bash
npm run export:ios
```

`export:ios`는 JS 번들 검증이며 서명된 iPhone 앱이나 TestFlight 배포가 아닙니다. 현재 Codex에서 테스트/번들/로컬 서버 응답을 검증했지만, 실제 Codespaces의 Public 포트와 iPhone Expo Go 연결·쿠키·키보드는 사용자 환경에서 아직 확인하지 않았습니다. 이 구성을 완전한 24시간 테스트 서비스라고 설명하지 않습니다.

## 이미 만든 Codespace에서 SDK 수정 반영

실행 중인 서버 터미널에서 Ctrl+C로 중지한 뒤 저장소 루트에서 한 줄씩 실행합니다. git pull이 충돌이나 로컬 변경 오류로 멈추면 강제 초기화하지 않습니다. git pull은 현재 체크아웃한 모바일 브랜치를 업데이트합니다.

```bash
git pull --ff-only
```

```bash
npm --prefix mobile ci
```

```bash
bash tools/start_mobile_codespace.sh
```

기존 Expo 로그인/공유 포트/서버 주소는 그대로 사용합니다. 테스트 서버 재시작은 새 가짜 DB를 만들므로 가짜 원고는 초기화됩니다. 설치된 Expo Go를 삭제하거나 오래된 버전으로 바꾸지 않습니다. 이 변경은 운영 웹/DB에 배포되지 않습니다.

## 테스트 웹에서 ‘허용되지 않는 요청’이 나오는 경우

Codespaces는 외부 HTTPS를 내부 HTTP로 전달합니다. 가짜 테스트 실행기는 이 Codespace에 설정된 8000번 HTTPS 주소를 고정해 Flask가 같은 주소를 보도록 합니다. 다른 Origin과 CSRF 토큰이 없는 요청은 기존 검사에서 계속 차단합니다. 요청의 X-Forwarded-* 헤더를 무조건 신뢰하거나 운영 Flask 검사를 해제하지 않습니다. 이 처리는 tools/mobile_test_proxy.py와 가짜 실행기에만 있으며 운영 웹/배포 설정에는 추가하지 않습니다.

이전 실행기가 동작 중이면 서버를 중지하고 git pull --ff-only 후 시작 명령을 다시 실행합니다. 테스트 DB가 새로 만들어지므로 웹과 앱 모두 가짜 계정으로 다시 로그인합니다. 앱이 이전 세션을 표시하면 Expo Go의 Reload 또는 앱을 다시 열어 로그인 상태를 새로 시작합니다.
