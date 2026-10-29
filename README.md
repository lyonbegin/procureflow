# 조달청 자동화 프로젝트 — 최종 기획 정본

**모든 신규 작업·대화의 기준:** [최종 기획 기준서 (104개 업무 기능, 43개 블록, PF01~PF15, S01~S10, 노드 테스트·디버깅 80개)](docs/FINAL_PROJECT_MASTER_PLAN_2026-10-28.md)

**2026-10-30 공용 Studio 통합 개발 문서:** [주식과 동일한 shared-n8n-studio 재사용 — 소스 구성·26개 워크플로·Railway 배포·실제 Chrome Pan 검증·롤백·남은 작업](docs/SHARED_STUDIO_PROCUREFLOW_DEVELOPMENT_KO.md)

> 공용 Studio는 로그인 없이 노드 초안을 편집하는 **별도 Vue Flow UI**이며 공식 n8n 엔진·운영 PostgreSQL 저장·104개 실업무 완료를 의미하지 않는다. 실제 실행·투찰은 미연결.


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
