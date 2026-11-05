# BidPicker Bridge Railway deployment attempt (2026-11-06, KST)

## Verified
- Repo: `lyonbegin/procureflow`
- Branch: `feature/bidpicker-isolated-discovery-20261106`
- Railway Dockerfile: `integrations/bidpicker/Dockerfile` (uses ${PORT:-8000})
- Railway build config on this branch: `railway.json` explicitly sets Bridge Dockerfile and /health
- CI: https://github.com/lyonbegin/procureflow/actions/runs/42062943827 — success
- Draft PR: https://github.com/lyonbegin/procureflow/pull/30

## Railway resources
- New isolated project created: `procureflow-bidpicker-bridge`
- Project ID: `e785153f-9492-4d0a-ae12-14f9dda9875c`
- Production environment ID: `d7b8a5dd-16fc-4ebb-9aa6-d7543ad6e384`
- `list_services` after attempts: **zero services**.
- `deploy_template(postgres)`: tool safety check blocked.
- `create_deployment(repo=lyonbegin/procureflow,branch=feature/bidpicker-isolated-discovery-20261106)`: tool safety check blocked.
- Therefore, there is **no deployed endpoint, running Bridge or actual DB**, and no live search data collected.

## Requirements for eventual live operation
- Brand-new database in this separate project, not legacy `DATABASE_URL`.
- `BIDPICKER_DATABASE_URL` mapped to new database URL.
- `BIDPICKER_BRIDGE_TOKEN` securely generated and configured at Railway (do not commit to repository).
- Authorized source credentials if supported; never reuse extracted third-party secrets.
- `BIDPICKER_SYNC_ENABLED=0` until real response contract is verified and user elects persistence.
- Generate new Railway public domain; check `GET /health` and authentication enforcement for search.
- A passing healthcheck does NOT imply third-party API returned real notices. The previously observed unauthenticated source response was HTTP 401.
- After deployment, separately verify `api/bids` response and source provenance; require primary G2B confirmation for official evidence.
