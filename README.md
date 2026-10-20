# ProcureFlow — Railway
FastAPI + isolated Headless Chromium worker + existing pgvector PostgreSQL.

- This repo adds tables only in PostgreSQL schema `procureflow`; other projects' tables and volumes are untouched.
- API: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Worker: `python worker.py`
- Both services need Railway variable `DATABASE_URL=${{pgvector.DATABASE_URL}}`.
- API needs `ADMIN_TOKEN`. Do not publish the token or DATABASE_URL.
- Deploy both services from this repository inside thriving-education / production.
- Browser collection has no external Chrome 9333 CDP connection.
- D2B deliberately disabled; S2B integration follows after its actual page structure is established.
- Existing SQLite datasets require a separate one-time import; migration is not automatically asserted.
- `/health` shows database reachability; `/api/jobs` queues collection for worker.
