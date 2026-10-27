# Native n8n editor gateway

This Caddy reverse proxy points to the original n8n editor over Railway private networking.
No duplicate React Flow / DAG runner is used.

- Public: `https://procureflow-n8n-editor-gateway-production.up.railway.app`
- Internal upstream: `http://n8n.railway.internal:5678`
- The *extra browser HTTP Basic Auth popup* is removed; there is no gateway username/password.
- n8n's own session/account security remains enabled.
- Public first-owner registration (`/setup` and `/rest/owner/setup`) is blocked. Owner bootstrap must be performed on a trusted private connection before expecting normal editor login.
- Never expose a raw n8n main-service domain, encryption key, or database credentials.
- `/healthz` returns HTTP 200. A successful health check is not an assertion that all 15 flows execute correctly.
- Actual PF01-PF15 and S01-S10 workflow execution should be verified separately; do not submit real bids automatically.
