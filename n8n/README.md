# 실제 Worker 작업 연결 — 2026-10-25

운영 n8n의 PF01~PF15 워크플로는 공식 근거 조회(기본)와 명시적 수집 실행(관리자)을 구분합니다.

1. 기본 inspect 모드: n8n Manual Trigger를 누르면 실제 G2B PostgreSQL의 공식 증빙과 43개 업무 블록 입력·출력을 읽고, 이후 next-action GET으로 가능한 실제 작업 1개를 계획합니다. 이 경로는 Job을 등록하지 않습니다.
2. 운영자가 최초 코드 노드의 mode 값을 collect로 명시 변경하고, n8n에 암호화된 ProcureFlow 업무 API Credential(관리자 토큰)을 연결할 때에만 네이티브 IF의 실행 분기가 열립니다.
3. 승인된 분기는 POST /api/n8n/operational/flows/{PF}/dispatch로 실제 기존 G2B Worker Job 1건을 큐에 넣고 20초 대기 후 GET /api/n8n/operational/flows/{PF}/jobs/{id}로 Worker 결과와 독립 공식 증빙을 확인합니다.
4. 요청키 중복 실행은 동일 Job으로 반환합니다. 동시 G2B 기능 작업 3개, 동일 공유 수집기 중복, 최근 실행 후 30분 내 재시도는 차단합니다.
5. PF12 최종 승인, PF14 자원 관리, PF15 장애 복구는 무인 자동 Job 등록이 금지됩니다. 공식 10자리 세부종목 원본 검증 없이는 PF05의 10년 과거 개찰·낙찰 수집이 차단됩니다.

확인 API (읽기): /api/n8n/operational/flows/PF05/inspect , /api/n8n/operational/flows/PF05/next-action
관리자 인증 API (실제 동작): POST /api/n8n/operational/flows/PF05/dispatch , GET /api/n8n/operational/flows/PF05/jobs/{id}
운영 Job 이력: GET /api/n8n/operational/flows/PF05/dispatch-history

Credential은 n8n 내부에서만 관리해야 합니다. 토큰을 GitHub·채팅·워크플로 JSON에 넣지 마세요. 관리자 소유권 및 인증 구성 이전에는 n8n 외부 주소를 공개하면 안 됩니다.
작업이 완료되더라도 투찰/낙찰 분석의 완결성이 증명되는 것은 아닙니다. 자동 입찰 제출은 존재하지 않습니다.

---
# ProcureFlow — n8n single workflow engine

**The 10 exported workflows are not automatically active in Railway.**
The code does not have access to Railway's n8n Main service, its database,
or the n8n owner session. No claim of live n8n execution is made until the
import, startup and manual browser checks are completed.

## Local n8n main + queue Worker setup

1. From repository root: `cp n8n/.env.example .env`.
2. Put strong unique secrets in the untracked `.env`, generate encryption
   key with `openssl rand -hex 32`.
3. Start the n8n stack: `docker compose -f docker-compose.n8n.yml up -d`.
4. Open **http://localhost:5678** and create the initial n8n owner account.
5. Import TEN DEMO-ONLY workflows **once**:

   ```bash
   docker compose -f docker-compose.n8n.yml exec n8n-main \
     n8n import:workflow --separate --input=/demo-workflows
   ```

6. In the n8n workflows list search `[테스트 S01]` ... `[테스트 S10]`.
   Open each one and click **Execute workflow**. As the native n8n nodes turn
   green, click them to view their Input, Output, and trace. A failed HTTP QA
   node is red and contains the exact mismatch response.
7. Workflow S01 expected `READY_FOR_MANUAL_PARTICIPATION`,
   S02 and S06 `NO_BID`, S08 `REVIEW`, others `HOLD`.
8. If API is not reachable from the n8n host, edit the final HTTP QA node's URL
   to the accessible `https://procureflow-api-production.up.railway.app`
   endpoint or deploy the API first. Do NOT point this at a production write URL.

### Why not auto-import on every restart?

The n8n server import command may overwrite workflows that share IDs.
We intentionally do not import or republish on every container startup: an
operator must explicitly import the initial TEN DEMO workflows once.
Each export is `active: false` and begins with Manual Trigger only.

### Scenario verifiers (all fictional/read-only)

```bash
curl https://procureflow-api-production.up.railway.app/api/n8n/scenarios
curl https://procureflow-api-production.up.railway.app/api/n8n/qa
curl https://procureflow-api-production.up.railway.app/api/n8n/scenarios/S04/simulate
```

Native n8n workflows end with:
`POST /api/n8n/scenarios/{id}/verify`.
It recomputes the exact expected state/trace and returns HTTP 409 if a step was
skipped, forged or executed out of order. The read-only `/simulate` endpoint
is **not** proof that n8n ran; check the n8n execution itself.

### Railway production infrastructure

Deploy `n8n/Dockerfile` as a NEW service for n8n Main (port 5678).
Use a second service built from the same Dockerfile for `n8n worker --concurrency=3`.
Both share **dedicated n8n PostgreSQL**, **Redis**, and
`N8N_ENCRYPTION_KEY`; see official n8n queue-mode docs.
Set `N8N_EDITOR_BASE_URL`, `WEBHOOK_URL`, `N8N_HOST`, `N8N_PROTOCOL=https`,
`N8N_SECURE_COOKIE=true`, `EXECUTIONS_MODE=queue` for public HTTPS.

For the Python API set `N8N_EDITOR_URL=https://<actual-n8n-domain>`
**only after** n8n is reachable and the ten fixed-ID workflows have been imported.
The root `/` and retired `/flow` paths then present verified deep-link labels.
Before configuration, the landing page explicitly says n8n is not deployed and
only offers stateless test results.

**Important:** native n8n workflows are the only editable/executable flow
definitions. The Python QA module is a deterministic test oracle (no DAG,
no dispatch, no production writes). Existing Python jobs, source verification
and G2B business APIs are separate business processing components and remain.

### Acceptance gates before live operation

- All ten exported workflow JSONs import cleanly into n8n 2.44.6.
- Click/manual execution for S01~S10 produces green final QA nodes.
- Inspect node input/output and execution history in the native n8n canvas.
- Test a deliberately modified stage; final QA must reject with HTTP 409.
- Confirm S04 stale version, S05 114/121 partial, S08 fencing+reconciliation,
  S09 withdrawn approval and S10 2 deferred cases.
- Confirm there are no active G2B write/submit nodes in any demo workflow.
- Only after UI/execution verification proceed with PF01~PF15 **real**
  integration flows, validated primary-source data and authentication.

### Read native n8n execution status from API

After n8n is installed and its public API is enabled, configure on the Python
API service only:

- `N8N_ADMIN_API_URL` — n8n internal HTTPS URL (no credentials in URL)
- `N8N_ADMIN_API_KEY` — a read-only/least-privilege n8n API key

`GET /api/n8n/native/status` reports how many of the 10 workflows were
actually imported and how many produced a recorded native n8n successful
execution. It intentionally reports **0 and not verified** before connection;
`GET /api/n8n/qa` is only a stateless fictional model test.
No API key or internal host URL is exposed by the response.
