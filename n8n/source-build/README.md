# Upstream n8n source build for ProcureFlow

This is a **real source build**, not `FROM n8nio/n8n`. It pulls the original `https://github.com/n8n-io/n8n` git tag `n8n@2.44.6` and verifies the exact commit SHA `b58d9e89d60e9a3485bb511c5091d8be0d9511e4`. It then runs upstream `pnpm build:deploy` and packages `compiled` in a Node 26 image.

The original `n8n/Dockerfile` using the published `n8nio/n8n:2.44.6` remains untouched. This source build is for *isolated validation before rollout*, because switching a production workflow engine without DB backups and import/credential compatibility tests can interrupt all 15 PF workflows and 10 demo scenarios.

Build locally from ProcureFlow repository root:

```sh
docker build -f n8n/source-build/Dockerfile -t procureflow-n8n-source:2.44.6 .
docker run --rm --entrypoint n8n procureflow-n8n-source:2.44.6 --version
```

Expected version: 2.44.6. The CI job builds this same Dockerfile and verifies the version and workflow JSON files. A successful build alone does not prove n8n startup, login, workflow importing or business acceptance.

Before swapping production:
- Make a restorable snapshot of the **dedicated n8n Postgres** and the encrypted credential environment; never export or print secret values.
- Reuse existing `N8N_ENCRYPTION_KEY`, DB and queue settings, and Worker version. Never generate a new encryption key for existing credentials.
- Run a separate test service with **no public editor domain** and no production DB connection.
- Verify startup, n8n editor behavior, workflow import, 15 PF + 10 demo execution results, rollback.
- The upstream source **also includes n8n's own initial owner registration**; compiling it does not remove that setup step.
- Do not add a second DAG engine, custom React Flow editor, or automatically submit bids.

n8n upstream is third-party source. Observe its Sustainable Use License and release compatibility.
