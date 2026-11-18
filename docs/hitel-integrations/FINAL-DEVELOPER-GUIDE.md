# HITEL 외부 프로그램 연동 API — 개발자 전달용 최종 설명서

문서 버전: 1.0 · 기준: 2026-11-19 (KST) · 범위: 현재 배포된 구현의 실제 지원 수준

> 이 문서는 외부 프로그램 개발자에게 그대로 전달하는 API 계약·호출 절차 문서입니다. **문서 자체는 완결본이지만, 아래에 명시한 미연결 기능까지 구현 완료되었다는 뜻은 아닙니다.** API가 실제 ChatGPT 답변을 제공하려면 계정 검증 및 GitHub Chrome 작업자 연결을 먼저 복구해야 합니다.

## 1. 공식 호출 주소와 현재 운영 상태

- Base URL: https://hitel-integration-api-production.up.railway.app
- 브라우저용 개발자 안내: https://hitel-integration-api-production.up.railway.app/integrations/docs
- OpenAPI 3.0.3: https://hitel-integration-api-production.up.railway.app/integrations/openapi.yaml
- Python 표준라이브러리 호출 예제: https://hitel-integration-api-production.up.railway.app/integrations/example_client.py
- 실측 파일 QA 대시보드: https://hitel-integration-api-production.up.railway.app/integrations/v1/scenarios/files/view
- 실측 파일 QA JSON: https://hitel-integration-api-production.up.railway.app/integrations/v1/scenarios/files/latest

**현시점 점검 결과 (2026-11-19):** GET /health는 200 정상; GET /integrations/v1/capabilities의 worker_connected=false, verified_account_enrollment_available=false. 이는 서버 HTTP가 정상이라는 뜻이지, 외부 ChatGPT 메시지 중계가 현재 작동한다는 뜻이 아닙니다. 상태는 수시로 바뀔 수 있으므로 배포 시점마다 capabilities를 재조회하십시오.

**즉시 사용 가능한 공개 API:** GET /health, GET /integrations/v1/capabilities, GET /integrations/v1/scenarios/files/latest, GET /integrations/v1/scenarios/files/runs/{run_id}; 정적 문서 조회.

**운영 연결이 복구되어야 실제 사용 가능한 API:** 인증키 발급·관리, 본문 대화방 생성, 채팅 제출, 작업 결과 조회. HTTP 라우터 및 자동 계약시험은 존재하지만 일반 사용자의 실서버 E2E 송수신은 아직 확인되지 않았습니다.

**미지원:** 일반 외부 프로그램에서 임의 TXT/CSV/PDF/이미지/바이너리 첨부; ChatGPT가 생성한 파일의 일반 API 다운로드; SSE/스트리밍. 작업을 성공으로 가장하여서는 안 됩니다.

## 2. 호출 구조

외부 프로그램 → HTTPS /integrations/v1/* → Bearer 키 및 계정·방 검증 → 대기열 접수(HTTP 202) → GitHub Chrome 작업자 → 사용자 ChatGPT 계정 → 작업 결과 API.

반드시 구분하십시오.

1. HTTP 200/201: 조회/리소스 생성 성공을 뜻합니다.
2. HTTP 202: 메시지가 **대기열에 접수**되었다는 뜻이며, ChatGPT 전송·답변이 완료된 것이 아닙니다. 응답의 sent_to_chatgpt=false가 정상 설계입니다.
3. GET /integrations/v1/jobs/{job_id}에서 status=completed이고 result_text가 있어야 최종 답변으로 취급할 수 있습니다.
4. status=failed이면 error를 읽으십시오. queued/running이면 동일 작업 ID로 재조회하며 메시지 재전송은 하지 마십시오.
5. worker_connected=false일 때는 운영용 질문을 제출하지 말고 의존성 복구를 기다리거나 장애를 노출하십시오.

## 3. 인증·계정 발급 및 관리

외부 프로그램은 ChatGPT/Google 비밀번호, 로그인 쿠키, GitHub 토큰을 요구하거나 저장하지 않습니다. HITEL 별도 Bearer 키인 htli_... 문자열만 사용합니다. 키는 **하나의 브라우저 프로필 및 검증된 ChatGPT account_id에 고정**됩니다. API가 받는 account_id는 매 채팅 요청 JSON 본문의 별도 필드로 보냅니다.

API 키 최초 발급은 사용자 소유 브라우저에서만 가능합니다. 해당 브라우저가 서버에 발급받은 서명 쿠키를 보유해야 하고, 서버에 활성 프로필 및 OpenAI 인증으로 검증된 ChatGPT 계정이 이미 등록되어 있어야 합니다.

발급 절차:

1. 사용자의 동일 도메인 브라우저에서 GET /web/api/bootstrap을 호출해 세션 쿠키와 csrf를 받습니다.
2. 그 브라우저에서 검증된 ChatGPT 계정을 선택·등록합니다. 계정 등록 기능 자체가 활성화되어 있어야 합니다.
3. 동일 브라우저 세션, Origin 및 X-Web-Csrf 헤더로 POST /web/api/integrations/keys에 아래 본문을 보냅니다.
4. 반환값 api_key는 **한 번만 공개**되므로 비밀 저장소에 즉시 저장하고, 반환값 account_id를 함께 보관합니다.
5. 브라우저에서는 GET /web/api/integrations/keys로 메타데이터 목록을 조회하고 DELETE /web/api/integrations/keys/{key_id}로 폐기할 수 있습니다.

~~~http
POST /web/api/integrations/keys
Content-Type: application/json
X-Web-Csrf: (bootstrap에서 받은 값)
Cookie: (동일 브라우저의 서버 서명 세션 쿠키)

{"name":"partner-app"}
~~~

성공 응답 형식 예시 (실서버 발급 성공 사례가 아니라 코드 기반 예시):

~~~json
{
  "id":"ikey_<발급 ID>",
  "name":"partner-app",
  "account_id":"oai_<검증된 계정 ID>",
  "api_key":"htli_<발급된 비밀키>",
  "warning":"Secret is shown once. Store outside source control."
}
~~~

현재 verified_account_enrollment_available=false이므로, 이 신규 서버에서 최초 키 발급을 완료할 수 있다고 안내하면 안 됩니다. 운영자가 실제 계정 검증 연동을 완료하고 발급 시험을 통과한 다음 사용하도록 하십시오. 기존 다른 HITEL 서비스에 로그인했다는 사실만으로 본 신규 서버에 같은 계정이 등록된 것은 아닙니다.

## 4. 공개 API 전체 목록

| HTTP | 경로 | 인증 | 반환/의미 |
|---|---|---|---|
| GET | /health | 없음 | HTTP 서비스 상태. Chrome 연결과는 별개 |
| GET | /integrations/v1/capabilities | 없음 | 워커 및 기능 지원 여부 |
| POST | /web/api/integrations/keys | 브라우저 쿠키·CSRF·검증계정 | 키 1회 발급. 현재 계정 등록 경로 미가동 |
| GET | /web/api/integrations/keys | 브라우저 쿠키 | 발급 키 메타데이터 |
| DELETE | /web/api/integrations/keys/{key_id} | 브라우저 쿠키·CSRF | 키 폐기 |
| GET | /integrations/v1/rooms | Bearer | 현재 키와 계정의 활성 방 목록 (최대 100) |
| POST | /integrations/v1/rooms | Bearer | 계정에 고정된 방 생성, HTTP 201 |
| POST | /integrations/v1/chat | Bearer + Idempotency-Key | 질문 작업 생성, HTTP 202 |
| GET | /integrations/v1/jobs/{job_id} | Bearer | 해당 키/계정 작업의 진행 상태와 결과 |
| POST | /integrations/v1/files | Bearer | 인증 후 HTTP 501. 일반 파일 전송 미지원 |
| GET | /integrations/v1/scenarios/files/latest | 없음 | 마지막 합성파일 QA 실측 결과 |
| GET | /integrations/v1/scenarios/files/runs/{run_id} | 없음 | 지정된 합성파일 QA 결과 |

주의: /integrations/v1/scenarios/files/runs, /files/{role}, /results와 같은 **QA 쓰기 엔드포인트는 일반 외부 개발자가 호출하는 기능이 아닙니다.** 지정된 GitHub Actions 워크플로의 OIDC 서명이 있어야 합니다. 다른 프로그램에 OIDC 토큰 또는 테스트용 로그인 쿠키를 제공하지 마십시오.

## 5. 외부 프로그램의 실제 호출 예시

아래 예시는 API 키와 실제 ChatGPT account_id가 **이미 정상 발급되어 있고 worker_connected=true인 운영 환경**을 전제로 합니다. 현재 서버에서는 준비가 끝나기 전까지 실행하지 마십시오.

### A. 환경변수 및 사용 가능 여부

~~~bash
export BASE_URL="https://hitel-integration-api-production.up.railway.app"
export HITEL_API_KEY="htli_실제로_발급된_키"
export HITEL_ACCOUNT_ID="oai_실제로_발급된_계정_ID"

curl -sS "$BASE_URL/integrations/v1/capabilities"
~~~

worker_connected가 false이거나 verified_account_enrollment_available가 false이고 아직 키가 없다면 그대로 진행하지 마십시오.

### B. 대화방 생성

~~~bash
curl -sS -X POST "$BASE_URL/integrations/v1/rooms" \
  -H "Authorization: Bearer $HITEL_API_KEY" \
  -H "Content-Type: application/json" \
  --data '{"title":"외부 프로그램 새 대화방"}'
~~~

성공은 HTTP 201이며, 반환값 room_id와 account_id를 저장합니다. 방 제목은 1~160자입니다. 방은 해당 계정에 고정됩니다. 최대 방 수에는 서버의 웹 프로필별 한도가 적용됩니다.

### C. 질문 접수

~~~bash
curl -i -X POST "$BASE_URL/integrations/v1/chat" \
  -H "Authorization: Bearer $HITEL_API_KEY" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: client-20261119-req-000001" \
  --data '{
    "room_id":"room_<실제 생성된 32자리 hex ID>",
    "account_id":"oai_<키와 같은 검증 계정 ID>",
    "text":"안녕하세요. 한 문장으로 답변해 주십시오.",
    "attachment_ids":[]
  }'
~~~

HTTP 202 응답 형식:

~~~json
{
  "job_id":"job_<32자리 hex ID>",
  "status":"queued",
  "replayed":false,
  "accepted":true,
  "sent_to_chatgpt":false,
  "worker_connected":true,
  "poll":"/integrations/v1/jobs/job_<32자리 hex ID>"
}
~~~

이 예시의 worker_connected=true는 **정상 연결되었을 때의 형식 예시**이며 현시점 실서버 값은 false입니다.

- text: 공백 제외 유효한 1~2,000자.
- account_id: 키에 고정된 oai_ 식별자와 완전히 동일해야 합니다. 다르면 HTTP 409.
- room_id: 발급된 room_ 뒤 32자리 소문자 hex.
- Idempotency-Key: 16~128자의 영숫자, 밑줄, 점, 콜론 또는 하이픈. 같은 키·같은 요청을 다시 보내면 기존 job_id를 반환합니다. 같은 키로 다른 내용을 제출하면 HTTP 409입니다.
- attachment_ids: 현재 반드시 빈 배열로 보내십시오. 파일 ID를 넣으면 HTTP 501입니다.

### D. 질문 결과 조회

~~~bash
curl -sS "$BASE_URL/integrations/v1/jobs/job_<실제 받은 작업 ID>" \
  -H "Authorization: Bearer $HITEL_API_KEY"
~~~

~~~json
{
  "job_id":"job_<작업 ID>",
  "room_id":"room_<대화방 ID>",
  "status":"completed",
  "stage":"<서버가 기록한 단계>",
  "result_text":"<실제 검증 후 얻은 답변>",
  "error":null,
  "created_at":0,
  "updated_at":0
}
~~~

위 JSON은 응답 **스키마 예시**이며 실제 사용자 답변 결과가 아닙니다. created_at/updated_at은 실제 응답에서 Unix 밀리초 단위로 들어옵니다. completed 이전에는 result_text가 null입니다. failed라면 error를 점검하십시오.

같은 방 후속 질문은 **직전 job이 completed이고 기존 ChatGPT 대화방 연결이 검증된 경우**에만 제출하십시오. 진행 중인 작업이 있으면 다른 키로 중복 질문을 생성하지 마십시오.

## 6. 오류 코드, 제한 및 재시도

| HTTP | 의미 | 프로그램의 동작 |
|---|---|---|
| 200 | 조회 성공 또는 브라우저 키 발급 | 해당 엔드포인트 반환값 확인 |
| 201 | 새 대화방 생성 | room_id 저장 |
| 202 | 작업 대기열 접수 | job_id 저장 후 GET으로 조회 |
| 400 | Idempotency-Key 누락·형식 불량 | 키 포맷 수정 |
| 401 | Authorization 없음 | Bearer 키 헤더 추가 |
| 403 | 키 무효·폐기 또는 CSRF 거부 | 키/브라우저 인증 재검증 |
| 404 | 자신의 작업·키가 아니거나 존재하지 않음 | ID 및 소유권 검증 |
| 409 | 계정 불일치, 이미 처리 중, 중복키 충돌, 계정 해제 등 | 계정·방·작업 상태 확인 후 복구 |
| 422 | 본문·ID 형식 검증 실패 | 스키마에 맞게 수정 |
| 429 | 과도한 호출 또는 키/방 한도 | 전송 중지, 한도 확인 |
| 501 | 일반 파일 전송/비어 있지 않은 attachment_ids | 미지원으로 처리 |

현재 서버 코드에는 프로필당 시간당 최대 5개 채팅 작업, 브라우저 시험 계열 전체 하루 최대 30개 작업, 활성 인증키 최대 5개/프로필의 제한이 있습니다. 방·텍스트 한도를 무시한 무한 재시도를 금지합니다.

네트워크 타임아웃이 발생했을 때는 동일한 Idempotency-Key와 동일한 본문으로만 재확인하며, 성공적으로 접수된 작업은 GET jobs/{job_id}로 조회하십시오. HTTP 202를 실제 답변으로 보여주지 마십시오. 작업자가 끊긴 상태에서는 제출하지 않는 것을 원칙으로 합니다.

## 7. 파일 첨부 / 생성 파일 다운로드 — 정확한 현재 범위

일반 앱의 POST /integrations/v1/files는 **HTTP 501**입니다. 파일 첨부와 결과 파일 다운로드용 범용 API 계약이 만들어졌다고 보고하지 마십시오.

다만 2026-11-18 GitHub Actions #44312253301에서는 별도의 **서명된 QA 전용 API**를 통해 고정 합성 TXT/CSV를 HTTPS로 업로드하고, 서버에서 다시 내려받고, SHA-256을 대조한 후, 등록된 1번 ChatGPT Chrome 계정에서 사용했습니다. 실제 결과:

| 시나리오 | 관측 동작 | 상태 |
|---|---|---|
| S08 | TXT 첨부가 ChatGPT 입력창에 표시 | PASS |
| S09 | 전송 전 TXT 첨부 제거 | PASS |
| S10 | TXT 안의 고유 시험값을 ChatGPT 답변에서 확인 | PASS |
| S15 | CSV의 3+5를 답변 8로 확인 | PASS |
| S11 | ChatGPT 생성 CSV를 브라우저에 다운로드 | BLOCKED — BROWSER_DOWNLOAD_NOT_STARTED |

증거:
- 실측 보고서: https://hitel-integration-api-production.up.railway.app/integrations/v1/scenarios/files/view
- 기계 판독 JSON: https://hitel-integration-api-production.up.railway.app/integrations/v1/scenarios/files/latest
- GitHub Actions 로그: https://github.com/lyonbegin/procureflow/actions/runs/44312253301

이 실험의 **QA 파일 API**는 소유자 통제 합성 데이터만 받습니다. 다른 앱이 임의 파일을 넣거나 파일을 받을 수 있다는 뜻이 아닙니다. S11 실패는 ChatGPT 답변의 다운로드 버튼 선택 후 브라우저 다운로드 이벤트가 실제로 발생하지 않았다는 것이며, ChatGPT 생성 파일의 전달 방식을 재구현·재검증해야 합니다.

## 8. 운영자가 아직 완료해야 하는 작업 (외부 개발자에게 의존성으로 통보)

1. 신규 Railway API 서비스에서 실제 OpenAI 계정 검증·등록을 복구하고, 선택된 account_id와 활성 브라우저 프로필이 동일 서비스의 데이터베이스에 저장되는지 확인.
2. 기존 GitHub Chrome 작업자가 **신규 서비스의** 인증된 WebSocket에 실제 연결되도록 수정하고, 현재 등록된 1번 계정의 세션 및 계정 ID 일치 여부를 검증.
3. 브라우저에서 실제 htli_ 키 1개를 발급하고, 해당 키로 API 대화방 생성 → 질문 202 → worker 처리 → job completed/result_text까지 **실제 E2E 통과 증거** 확보.
4. 범용 원본파일 첨부 API와 ChatGPT로의 바이트 전달, 다운로드된 결과 파일 저장·회수 API를 별도 구현. 현재 QA 전용 합성파일 엔드포인트를 범용 파일 API로 재사용하거나 권한 우회하지 말 것.
5. S11에서 실제 생성 파일을 수신할 수 있는 경로를 확인하고 다운로드 콘텐츠를 검증한 후 자동 시험을 PASS로 바꿀 것. 실패한 로그를 성공으로 기재하지 말 것.

**이 다섯 가지가 완성되기 전에는 외부 개발자에게 '일반 파일 송수신까지 완성된 운영 API'라고 안내하지 마십시오.**

## 9. 실제 개발자에게 전달할 파일/주소

- 이 문서의 웹 버전: https://hitel-integration-api-production.up.railway.app/integrations/docs
- OpenAPI 계약: https://hitel-integration-api-production.up.railway.app/integrations/openapi.yaml
- Python 호출 예제: https://hitel-integration-api-production.up.railway.app/integrations/example_client.py
- 최신 파일 검증: https://hitel-integration-api-production.up.railway.app/integrations/v1/scenarios/files/view
- GitHub 코드 브랜치: https://github.com/lyonbegin/procureflow/tree/feature/hitel-integrations-api-20261118

보안 주의: 인증키·브라우저 쿠키·OpenAI 로그인 토큰·GitHub Actions OIDC를 문서나 공개 저장소에 기록하지 마십시오. 각 프로그램이 소유한 htli_ 키를 사용하는 것이 기본 원칙입니다.

---
HITEL Integration API v1 · 2026-11-19 · 구현 코드/실측 검증 기준
