# Actual n8n Editor HTTPS Gateway

This is a **reverse proxy** to n8n Main, not a separate editor or DAG engine.
All native n8n nodes, connections, input/output inspectors, execution history,
Execute workflow buttons, and credential manager are served by n8n itself.

Security invariant:
- **Only this Caddy gateway** has a public Railway domain. Do not attach a
  generated domain to the private service named `n8n`.
- This gateway uses HTTP Basic auth with a bcrypt-hashed access password stored
  as Railway service variable `EDITOR_PASSWORD_HASH`. The plaintext password
  must not be committed or placed in an n8n workflow.
- Gateway over HTTPS (Railway edge terminates TLS), backend over private
  `http://n8n.railway.internal:5678` (Railway WireGuard networking).
- Gateway does not send the Basic Authorization header to n8n.
- `/healthz` reports only an HTTP 200 for Railway checks; all editor/UI/rest
  and setup routes require gateway authentication.
- Set `N8N_EDITOR_BASE_URL` and `N8N_WEBHOOK_URL` on n8n Main to the
  actual gateway URL and `N8N_PROXY_HOPS=2` (Railway + Caddy).
- After a trusted operator enters the gateway, they must sign up as the **n8n
  owner with their own real email and private password**. Never create an
  owner with an invented email. Once owner is created, run a controlled native
  n8n workflow import with a target owner/project ID if imported workflows
  are not accessible in the native workflows list.
- The 15 operating PF and 10 fictional S workflows must remain manually
  triggered/inactive. Do not start actual G2B collector jobs while testing
  the editor. All bid participation remains human/manual.
