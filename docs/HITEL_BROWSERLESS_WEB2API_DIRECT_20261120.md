# HITEL: Chrome 없는 Web2API HTTP 재구성 (2026-11-20)

## 구현과 검증 범위

**신규 브랜치**: `feature/hitel-browserless-web2api-20261120`

이 브랜치는 기존 Railway의 A그룹 연구 및 Scribd 분류 데이터를 수정하지 않습니다.
기존 Chrome/CDP/ProseMirror/클릭 워커를 재사용하지 않고 새 Python HTTP worker와
MIT 라이선스 Go `5yu4n/gptweb2api`를 결합합니다.

- Go 원본: https://github.com/5yu4n/gptweb2api
- 고정 SHA: `985f4f45a49fbfdb2f8524686ab25759fd5195bb`
- Go 전송 모드: `GPTWEB_TRANSPORT_MODE=direct` (브라우저 fallback 비활성화)
- Go 게이트웨이: `127.0.0.1:8787` 만 바인딩
- 작업 수신: 기존 Railway `/ws` + GitHub OIDC 인증 (v4 프로토콜 유지)
- 질문 전송: POST `http://127.0.0.1:8787/v1/chat/completions`
- Go 원본의 실제 업스트림 전송: ChatGPT Web의 비공개 HTTP/SSE 인터페이스
- 인증: **실제 Codex OAuth 인증 파일**(`auth.json`)이 필요
- 사용하지 않음: Chrome, Playwright, CDP, DOM, Selenium, `api.openai.com`, 유료 OpenAI API

### 구성요소

| 파일 | 역할 |
|---|---|
| `.github/scripts/hitel_direct_http_transport.py` | HTTP 전송, 대화 ID/상위 메시지 ID 검증, 응답 검증, 재전송 차단 |
| `.github/scripts/hitel_direct_web2api_worker.py` | 기존 Railway OIDC/WebSocket v4 작업 큐와 연결 |
| `tests/test_hitel_direct_web2api.py` | 브라우저 없는 전송·방 독립성·실패/중복/보안 회귀검증 |
| `.github/workflows/hitel-browserless-web2api-20261120.yml` | 원본 핀·Go 빌드/테스트·실제 로컬 게이트웨이 시동 검증 |

### 대화방별 문맥

1. 서버가 보내는 기존 `room_id`, `chatgpt_url`, `target_conversation_id`를 유지합니다.
2. 기존 방은 인증된 읽기 전용 GET
   `https://chatgpt.com/backend-api/conversation/{conversation_id}` 에서
   실제 `current_node`의 assistant 메시지 ID를 확인합니다.
3. 정확한 `X-GPTWeb-Conversation-ID`,
   `X-GPTWeb-Parent-Message-ID`를 HTTP POST에 포함합니다.
4. 답변 본문, 대화 ID, assistant message ID를 모두 검증한 경우에만
   `job.result`를 Railway로 반환합니다.
5. 방 ID→대화 ID 연결을 임의 변경하지 않습니다. 두 방은 Python dict와 별도
   처리 태스크/동시실행 가드로 격리합니다. **Chrome 탭 자체가 존재하지 않습니다.**
6. POST 이후 HTTP 429, 5xx, 전송 끊김, 결과 ID 불일치 발생 시 해당 방을
   `uncertain`으로 격리합니다. 동일 질문의 자동 재전송은 금지합니다.

### 서브시스템별 현실적인 제약

- 원본 `MartinezS8/chatgpt-web2api`는 Chrome CDP가 필수이므로
  이 브랜치의 전송 코드에서는 더 이상 사용하지 않습니다.
- `5yu4n/gptweb2api`는 **비공식 ChatGPT Web API** 기반입니다.
  실제 서비스의 스키마·요청 제한·인증 요구가 바뀌면 작동하지 않을 수 있습니다.
- ChatGPT Plus/Pro 웹 구독은 공식 OpenAI API 크레딧이 아닙니다.
  여기서는 **유료 API를 대체하거나 몰래 호출하지 않습니다.**
- GitHub Actions의 기존 Google 로그인 Chrome 프로필은 Codex OAuth `auth.json`과
  동일하지 않습니다. 브라우저 쿠키를 OAuth 토큰인 것처럼 재사용하지 않습니다.
- 현재 기존 GitHub secret에 새 인증값이 있는지는 확인되지 않았습니다.
  인증이 없으면 읽기 전용 검사 단계에서 중지됩니다.
- 기존 연구방의 대화 기록을 확인하지 못하면 원본 방에 새 질문을 보내지 않습니다.
- 별도 계정 지정 `account_id` 작업 및 바이너리 첨부는 계정/파일 무결성
  검증이 확장되기 전에는 **실패로 처리합니다**.
- 현재 Railway 운용 워커는 수정하지 않았으며 실제 연구를 자동 재개하지 않았습니다.
  운영 전환 전에 기존 Chrome 워커를 종료하고 단일 WebSocket 소유자를 보장해야 합니다.
- **빌드·모의 응답·로컬 HTTP 검증 성공과 실계정 ChatGPT 답변 성공을 구분합니다.**

### 실행 정책

1. 브랜치 Push CI는 **네트워크 ChatGPT 요청 없는** 오프라인 Python 회귀검사,
   실제 고정 Go 소스 빌드, Go 회귀검사, 익명 로컬 HTTP 프로세스 시험만 수행합니다.
2. 수동 `workflow_dispatch mode=readonly`는 인증된 모델 목록과 직접 전송
   준비상태만 조회합니다. 메시지는 전송하지 않습니다.
3. 수동 `mode=serve`는 별도로 `RELEASE_DIRECT_HTTP` 승인 입력을 요구하며,
   유효한 Codex OAuth GitHub secret
   `HITEL_DIRECT_CREDENTIALS_JSON_B64` 없이는 시작하지 않습니다.
   base64 값은 인가된 `auth.json` 바이트의 표현일 뿐 암호화가 아닙니다.
   GitHub Actions secret으로만 저장해야 합니다.
4. **현재 실사용 전환 조건 미달**: 기존 두 방의 실제 읽기 전용 조회,
   동일 방 3회 연속 POST, 서로 다른 방 병렬 응답 확인,
   20건 실제 교재 분류, HTTP 429 후 안전 복구를 최종 재검증해야 합니다.

## 판정 문구

`PASS_BROWSERLESS_GO_GATEWAY_BUILD_AND_UPSTREAM_TESTS` =
Go 게이트웨이가 컴파일되고 upstream 단위 테스트가 통과했습니다.
**유료 API 호출 없음. 실계정 질문 전송 검증 아님.**

`PASS_ACTUAL_BROWSERLESS_GO_HTTP_NO_CREDENTIAL_FAIL_CLOSED` =
실제 Go 서버가 Chrome 없이 로컬 HTTP 요청을 받고 인증 없을 때 503을 반환했습니다.
**실계정 질문 전송 검증 아님.**

`PASS_AUTHENTICATED_DIRECT_READONLY_READY` =
실제 사용자 계정으로 읽기 전용 모델 목록을 취득했습니다.
**질문 전송 검증 아님.**

`DIRECT_HTTP_VERIFIED_REPLY` = 해당 요청에 답변 본문과 대화/assistant
메시지 ID를 검증했습니다. 하지만 A그룹·Scribd 전용 27개 시나리오 합격과는
별도의 기준입니다.
