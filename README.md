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

## HITEL ChatGPT 원격 연결

[실행·재사용 안내](docs/HITEL_WEB2API_CONTINUE.md) · [Chrome 작업자 시작](https://github.com/lyonbegin/procureflow/actions/workflows/hitel-integration-bridge-live-qa.yml) · [통합 회귀시험](https://github.com/lyonbegin/procureflow/actions/workflows/hitel-runtime-regression.yml)

소스는 이 저장소의 main에서 함께 관리합니다. 방마다 독립 Chrome 탭을 사용하고, 두 에이전트의 지속 WebSocket 연결을 지원합니다. 기본 실행 시간은 4시간이며 예약 실행은 추가하지 않습니다.

`tools/hitel_chat.py`는 요청을 저장한 뒤 전송하고, 연결이 끊기면 같은 요청의 결과를 이어받습니다. 기존 요청을 자동 재전송하지 않으며 응답의 방·요청·작업 ID와 SHA-256을 확인합니다.

[실제 두 방 8회 송수신 검증](https://github.com/lyonbegin/procureflow/actions/runs/44749309310). 파일 첨부와 24시간 상시 운영은 이 시험의 검증 범위에 포함되지 않습니다.
