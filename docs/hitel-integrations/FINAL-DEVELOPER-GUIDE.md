# HITEL Integration API — 기술 검증 중 (상시 운영 인계 금지)

문서 버전: 1.2 · 2026-11-19 · GitHub Actions 1회성 실제 인증키 API 검증 통과

**검증 결과:** https://github.com/lyonbegin/procureflow/actions/runs/44369381864

등록된 ChatGPT 1번 계정을 실제 Chrome 세션과 대조하고, 본인 브라우저 연결코드를 서명된 GitHub Actions로 승인하여, 실제 htli_ Bearer 키를 발급하고, 해당 키로 방 생성·ChatGPT 질문·결과·대화방 URL 검증 및 시험키 폐기까지 성공했습니다.

**그러나 상시 운영 API가 아닙니다.** GitHub Chrome 작업자는 수동으로 실행하는 일회성 작업자이며, 연결되어 있지 않으면 새로운 질문은 HTTP 503으로 거부됩니다. 일반 CSV/PDF 첨부, 생성 파일 다운로드, 18,109개 문서 제목의 대량 자동분류는 아직 미완성입니다. 초기의 최종 완성본 표시는 철회한 상태입니다.

## 1. 공식 호출 주소와 현재 운영 상태

- Base URL: https://hitel-integration-api-production.up.railway.app
- **작업자 실행·재시작 및 연결 상태 화면:** https://hitel-integration-api-production.up.railway.app/integrations/worker
- **직접 GitHub Actions 실행:** https://github.com/lyonbegin/procureflow/actions/workflows/hitel-integration-bridge-live-qa.yml
- 브라우저용 개발자 안내: https://hitel-integration-api-production.up.railway.app/integrations/docs
- OpenAPI 3.0.3: https://hitel-integration-api-production.up.railway.app/integrations/openapi.yaml
- Python 표준라이브러리 호출 예제: https://hitel-integration-api-production.up.railway.app/integrations/example_client.py
- 실측 파일 QA 대시보드: https://hitel-integration-api-production.up.railway.app/integrations/v1/scenarios/files/view
- 실측 파일 QA JSON: https://hitel-integration-api-production.up.railway.app/integrations/v1/scenarios/files/latest

**2026-11-19 실측:** HTTP API 정상이며 인증키 기반 질문과 실제 ChatGPT 답변을 GitHub Actions #44369381864에서 검증했습니다. 기존 등록 Chrome 계정의 GitHub Actions 연결 절차는 위 3절을 보십시오. 작업자는 1회성으로 동작하므로 평상시 worker_connected=false일 수 있습니다.

**즉시 사용 가능한 공개 API:** GET /health, GET /integrations/v1/capabilities, GET /integrations/v1/scenarios/files/latest, GET /integrations/v1/scenarios/files/runs/{run_id}; 정적 문서 조회.

**1회 실증 완료:** 실제 htli_ 인증키 발급·방 생성·ChatGPT 송수신·결과 조회·키 폐기. **운영 미완료:** 상시 작업자, 파일, 대량분류.

**미지원:** 일반 외부 프로그램에서 임의 TXT/CSV/PDF/이미지/바이너리 첨부; ChatGPT가 생성한 파일의 일반 API 다운로드; SSE/스트리밍. 작업을 성공으로 가장하여서는 안 됩니다.

## 2. 호출 구조

외부 프로그램 → HTTPS /integrations/v1/* → Bearer 키 및 계정·방 검증 → 대기열 접수(HTTP 202) → GitHub Chrome 작업자 → 사용자 ChatGPT 계정 → 작업 결과 API.

반드시 구분하십시오.

1. HTTP 200/201: 조회/리소스 생성 성공을 뜻합니다.
2. HTTP 202: 메시지가 **대기열에 접수**되었다는 뜻이며, ChatGPT 전송·답변이 완료된 것이 아닙니다. 응답의 sent_to_chatgpt=false가 정상 설계입니다.
3. GET /integrations/v1/jobs/{job_id}에서 status=completed이고 result_text가 있어야 최종 답변으로 취급할 수 있습니다.
4. status=failed이면 error를 읽으십시오. queued/running이면 동일 작업 ID로 재조회하며 메시지 재전송은 하지 마십시오.
5. worker_connected=false일 때는 운영용 질문을 제출하지 말고 의존성 복구를 기다리거나 장애를 노출하십시오.

## 2-1. 매번 작업자를 켜는 방법

이전에 연결된 1번 계정은 다시 등록하거나 로그인할 필요가 없습니다.

1. **https://hitel-integration-api-production.up.railway.app/integrations/worker** 를 여십시오.
2. "GitHub Chrome 작업자 실행 화면 열기" 링크를 누르십시오. 저장소 실행 권한이 있는 GitHub 계정이어야 합니다.
3. GitHub에서 **Run workflow**를 누르십시오. 기본값은 operation=worker_only, run_minutes=240(4시간)입니다. pairing_code는 **비워 둡니다**.
4. GitHub에서 Run workflow를 최종 확인하여 실제 워크플로를 실행하십시오. 로그인 프로필 검증 후 서버 WebSocket에 붙습니다.
5. 원래 페이지에서 **worker_connected=true**가 표시되면 다른 프로그램이 API 메시지를 전송할 수 있습니다. 상태가 자동 갱신됩니다.
6. 연결이 종료되면 같은 페이지에서 다시 실행하십시오. GitHub-hosted runner 한 회의 실행은 상시 서버가 아닙니다.

**제약을 숨기지 마십시오:** GitHub 인증 및 CSRF 보호 때문에 단순 GET 링크 클릭만으로 GitHub Action을 실행할 수는 없습니다. 실행 화면에서 별도로 Run workflow를 승인해야 합니다. 승인 없이 자동 실행되는 공개 URL은 만들지 않았습니다. 예약 실행도 추가하지 않았습니다.

## 3. 기존 ChatGPT 1번 계정 연결과 API 키 발급

외부 프로그램은 ChatGPT 비밀번호·쿠키·GitHub 토큰이 아니라 별도 발급되는 htli_ Bearer 키와 해당 oai_ 계정 ID만 사용합니다.

**브라우저 소유자 연결 절차**

1. 같은 브라우저에서 https://hitel-integration-api-production.up.railway.app/integrations/connect 를 여십시오.
2. "일회성 연결코드 발급"을 누르면 브라우저 소유자와 연결된 15분 유효 코드가 발급됩니다.
3. 저장소 소유자 권한으로 https://github.com/lyonbegin/procureflow/actions/workflows/hitel-integration-bridge-live-qa.yml 에서 Run workflow를 열고 pairing_code 입력란에 위 코드를 넣고 실행하십시오.
4. GitHub Actions는 이전에 저장된 Chrome 계정과 실제 ChatGPT 로그인 세션의 이메일을 확인하고, GitHub OIDC 서명으로 일회성 코드를 승인합니다. 이는 공식 OpenAI OAuth가 아닌 **등록된 Chrome 세션에 대한 서명된 검증**입니다.
5. 위 브라우저에서 "상태 다시 확인" 후 "API 키 발급"을 누르십시오. 반환된 htli_ 비밀키는 한 번만 공개됩니다. 함께 반환되는 oai_ 계정 ID를 보관하십시오.
6. 일반 프로그램의 모든 JSON 요청은 Authorization: Bearer (발급받은 키)를 사용합니다. 대화 POST에서는 account_id를 별도 JSON 필드로 보내십시오.
7. 키 목록은 GET /web/api/integrations/keys, 폐기는 DELETE /web/api/integrations/keys/{key_id} (브라우저 세션·CSRF 필요)입니다.

**실증:** Actions #44369381864에서 모의 브라우저 소유자 세션을 생성해 위 계정 연결부터 실제 Bearer 채팅 응답까지 모두 통과했습니다. 일반 사용자의 직접 수동 입력과 장기 세션 유지까지 검증된 것은 아닙니다.

## 4. 공개 API 전체 목록

| HTTP | 경로 | 인증 | 반환/의미 |
|---|---|---|---|
| GET | /health | 없음 | HTTP 서비스 상태. Chrome 연결과는 별개 |
| GET | /integrations/v1/capabilities | 없음 | 워커 및 기능 지원 여부 |
| POST | /web/api/integrations/keys | 브라우저 쿠키·CSRF·검증계정 | 연결코드 승인 후 키 1회 발급, 실제 시험 PASS |
| GET | /web/api/integrations/keys | 브라우저 쿠키 | 발급 키 메타데이터 |
| DELETE | /web/api/integrations/keys/{key_id} | 브라우저 쿠키·CSRF | 키 폐기 |
| GET | /integrations/v1/rooms | Bearer | 현재 키와 계정의 활성 방 목록 (최대 100) |
| POST | /integrations/v1/rooms | Bearer | 계정에 고정된 방 생성, HTTP 201 |
| POST | /integrations/v1/chat | Bearer + Idempotency-Key | 작업자 연결 시 HTTP 202, 미연결 시 HTTP 503 |
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

worker_connected=false인 경우 Chat POST는 HTTP 503이며 작업을 새로 접수하지 않습니다. 등록 계정 연결은 3절의 GitHub Actions 경로를 사용하십시오.

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
| 503 | Chrome 작업자 미연결 | 신규 질문 미접수; 작업자 가동 확인 |

**시간당 5건 및 전체 하루 30건의 HITEL 자체 채팅 횟수 제한은 제거했습니다.** 다른 서비스의 정책·실제 작업자 처리 속도와는 별개이며, 동일 방의 미완료 작업 중복 제출 차단과 Idempotency-Key 검사는 유지합니다. 활성 인증키 최대 5개/프로필은 채팅 횟수 제한이 아니라 키 관리 한도입니다.

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

## 8. 남은 운영 의존성 및 인계 보류 기준

이미 검증한 것: 일회성 계정 페어링, 실제 API 키 발급, 계정 고정 대화방, 질문 접수, 실제 ChatGPT 답변, 대화 URL, 테스트 키 폐기 (Actions #44369381864).

**아직 미완료:**

1. GitHub Chrome 작업자를 수동 실행하는 링크와 30~240분 선택은 제공했습니다. 24시간 상시 실행은 구현되지 않았으므로 작업자가 꺼져 있는 동안 worker_connected=false이며 새 질문은 HTTP 503입니다.
2. 일반 외부 프로그램이 임의 파일을 첨부하는 API. POST /integrations/v1/files는 501입니다.
3. ChatGPT 생성 파일을 외부 앱으로 전달하는 다운로드 API. S11은 BLOCKED입니다.
4. 18,109개 제목의 CSV 대량 입력, 분할·재개·출력 무결성, 호출 제한 조정 및 실제 전체 분류 검증.
5. 실제 외부 개발자의 브라우저 연결 및 반복 운영 시나리오 검증.

**이 항목들이 완료되기 전에는 다른 개발자에게 "상시 사용 가능한 최종 운영 API"라고 전달하지 마십시오.**

## 9. 실제 개발자에게 전달할 파일/주소

- 이 문서의 웹 버전: https://hitel-integration-api-production.up.railway.app/integrations/docs
- OpenAPI 계약: https://hitel-integration-api-production.up.railway.app/integrations/openapi.yaml
- Python 호출 예제: https://hitel-integration-api-production.up.railway.app/integrations/example_client.py
- 최신 파일 검증: https://hitel-integration-api-production.up.railway.app/integrations/v1/scenarios/files/view
- GitHub 코드 브랜치: https://github.com/lyonbegin/procureflow/tree/feature/hitel-integrations-api-20261118

보안 주의: 인증키·브라우저 쿠키·OpenAI 로그인 토큰·GitHub Actions OIDC를 문서나 공개 저장소에 기록하지 마십시오. 각 프로그램이 소유한 htli_ 키를 사용하는 것이 기본 원칙입니다.

---
HITEL Integration API v1 · 2026-11-19 · 구현 코드/실측 검증 기준
