# HITEL Web2API: 실제 ChatGPT 계정 연결·전환

운영 화면: https://chatgpt-relay-web-production.up.railway.app/

## 정확히 구분할 세 계정/인증

1. **HITEL 임시 프로필**: 같은 브라우저에서 대화방·파일을 분리합니다. 실제 Google/OpenAI 로그인이 아닙니다.
2. **Sign in with ChatGPT**: OpenAI 공식 OAuth/OIDC 신원 인증입니다. 인증된 이름/이메일과 안정된 사용자 식별자만 연동합니다. Chrome 쿠키·ChatGPT 대화·파일에 접근하는 권한이 아닙니다.
3. **GitHub Actions Chrome**: 별도로 암호화된 Chrome 로그인 세션을 복원합니다. 다른 계정으로 로그인한 상태라면 HITEL에서 선택한 ChatGPT 계정의 대화를 임의로 실행해서는 안 됩니다.

## 구현되어 있는 것

- HITEL 화면의 'ChatGPT 로그인' 메뉴: 실명 등록 대신 OpenAI OIDC로 확인된 계정 목록만 표시합니다.
- 계정 최대 2개 저장·선택·연결 해제 API: `/web/api/chatgpt/accounts`.
- Authorization Code + PKCE, state/nonce, ID 토큰 서명 및 issuer/audience 검증, 동일 브라우저의 로그인 트랜잭션 검증을 위한 엔드포인트가 준비되어 있습니다.
- 선택한 공식 계정이 별도의 Github Chrome 세션과 연동되어 있지 않으면 **실제 질문 전송 HTTP 409로 차단**합니다. 다른 계정으로 대신 보내지 않습니다.
- 공개 HITEL에는 Google 비밀번호, OpenAI 비밀번호, ChatGPT 쿠키, Chrome 프로필을 입력하거나 업로드하지 않습니다.
- GitHub Actions 검증: 계정 없는 상태·교차 브라우저 접근 차단·CSRF·잘못된 계정 선택 차단.

## 현재 로그인 불가 사유 (2026-11-16 확인)

Railway 운영 서비스에는 `OPENAI_SIWC_CLIENT_ID`, `OPENAI_SIWC_REDIRECT_URI`, `OPENAI_SIWC_CLIENT_SECRET`이 설정되어 있지 않습니다.
이는 **OpenAI가 실제 발급한 OAuth 클라이언트가 없다는 의미**이며, 현재 사이트에서 ChatGPT 계정 1·2에 공식 로그인할 수 없음을 뜻합니다.
클라이언트 ID를 임의로 생성하거나 다른 서비스의 ID를 재사용해서는 안 됩니다.

웹사이트형 Sign in with ChatGPT는 승인된 클라이언트가 필요합니다.
공식 등록 안내: https://developers.openai.com/siwc/request-client-id
공식 웹사이트 통합 문서: https://developers.openai.com/siwc/website

신청/승인 후 Railway에 설정해야 할 값:

- `OPENAI_SIWC_CLIENT_ID`: OpenAI가 발급한 `oaiapp_...` 클라이언트 ID
- `OPENAI_SIWC_REDIRECT_URI`: 정확히 `https://chatgpt-relay-web-production.up.railway.app/web/api/chatgpt/callback`
- `OPENAI_SIWC_CLIENT_SECRET`: 승인된 클라이언트가 confidential인 경우에만 비밀변수로 설정

클라이언트 승인 및 사용자의 Google/OpenAI 로그인·동의는 대행할 수 없습니다.

## GitHub Actions에서 선택한 실제 ChatGPT 계정 실행

현재 작업자는 **기존에 인증된 단일 Chrome 프로필**만 사용합니다. 별도 계정 인증·프로필 생성 및 계정별 분리, 작업자 ID와 HITEL에서 선택한 신원 일치 검증은 아직 미구현입니다. **공식 OAuth에 로그인했다고 해서 Github Chrome에 로그인된 것은 아닙니다.**

운영 전 완료해야 할 검증 조건:

1. 계정 A와 B의 개별 GitHub Chrome 세션은 독립적으로 인증되어야 합니다.
2. 각 세션의 ChatGPT 사용자 식별을 실제 인증 화면에서 검증해야 합니다.
3. HITEL에서 선택한 계정과 GitHub 작업자 계정이 일치한다고 증명할 수 없는 작업은 거절해야 합니다.
4. 대화방은 생성 당시 선택한 계정으로 고정하고 다른 세션의 기존 대화 URL을 사용하지 않아야 합니다.
5. 브라우저 전용 로그인 정보는 사용자에게 표시하지 않고, 짧은 수명·비밀 저장·폐기·감사 기록을 유지해야 합니다.

## 공식 OpenAI 대안

OpenAI는 오픈소스/로컬 실행 도구에 한하여 사용자가 승인한 ChatGPT 플랜으로 Responses API를 이용하는 별도의 OAuth 접근을 제공합니다. 다만 이는 **일반적인 공개·원격 호스팅 웹사이트에 자동 적용되지 않습니다**. Railway 웹 서비스에는 웹사이트용 공식 승인 및 사용자별 명시적 동의가 우선입니다.

참조: https://developers.openai.com/siwc/token-sharing-open-source
