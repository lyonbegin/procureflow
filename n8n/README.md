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
