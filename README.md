# 조달청 자동화 프로젝트 — 최종 기획 정본

**모든 신규 작업·대화의 기준:** [최종 기획 기준서 (104개 업무 기능, 43개 블록, PF01~PF15, S01~S10, 노드 테스트·디버깅 80개)](docs/FINAL_PROJECT_MASTER_PLAN_2026-10-28.md)

> 프로젝트 채팅 간 요구사항이 달라지거나 이전 구현 내용이 불일치하면 위 문서를 먼저 확인한다. n8n 설치·JSON 등록·가상 시나리오 통과를 실제 공식 개찰·낙찰 전수 완료로 보고하지 않는다. 변경은 본 문서의 버전·근거를 함께 수정한다.

---

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


---

## HITEL ChatGPT-Web2API · GitHub 실행

**[GitHub 실행 화면 — 서버 API 확인 / 실제 ChatGPT 메시지 시험](https://github.com/lyonbegin/procureflow/actions/workflows/hitel-web2api-github-console.yml)**

[한국어 실행·설치 안내](docs/HITEL_WEB2API_GITHUB_OPERATOR.md) · [GitHub Chrome 작업자](https://github.com/lyonbegin/procureflow/actions/workflows/chatgpt-web2api-relay-worker.yml) · [Railway 시험 화면](https://chatgpt-relay-web-production.up.railway.app/)

> Web2API의 원본 OpenAI 호환 API는 GitHub Actions 실행기의 localhost에서 임시 실행됩니다. Railway의 현재 공개 URL은 고정 질문용 시험 API이며, 일반 사용자용 OpenAI 호환 API 서버로 공개된 것은 아닙니다. API 비밀키나 Google 로그인 세션을 GitHub 공개 코드에 저장하지 않습니다.
