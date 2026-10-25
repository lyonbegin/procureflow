# ProcureFlow · n8n 단일 실행 엔진 (운영 안내)

2026-10-25 검증 대상: Railway 서비스 `n8n`, `procureflow-n8n-worker`, 전용 Redis·PostgreSQL, 기존 `procureflow-api`·`procureflow-worker`. 기존 React Flow·자체 DAG 실행기는 사용하지 않습니다. 실제 15개 운영 PF 파일과 10개 S 시나리오 테스트 파일은 저장소에 있습니다. 15개 운영 PF는 기본적으로 수동·읽기 전용(`active:false`)입니다.

## 사용 화면

- **전체 목록:** `/`
- **실제 진행상황 모니터:** `/n8n/progress?flow=PF05` — 10초마다 검증된 증빙 블록, 미충족 근거, 실제 Worker Job ID·실행상태를 표시합니다. 작업을 새로 시작하거나 수정하지 않습니다.
- **각 흐름 실제 입력·출력:** `/api/n8n/operational/flows/PF05/inspect`
- **다음 실행 가능한 작업 (실행하지 않음):** `/api/n8n/operational/flows/PF05/next-action`
- **15개/43블록/104 기능:** `/api/n8n/operational/flows`
- **10개 가상 S 시나리오:** `/api/n8n/scenarios`, `/api/n8n/qa`

### 사용자 조작 순서 (n8n 관리자 계정 및 비공개 접근통제 설정 이후)

1. n8n 화면에서 **[운영 PF05] 10년 개찰·낙찰 전수** 등의 운영 플로우를 엽니다.
2. **Execute workflow**를 클릭하면 `01 · 발주번호·PF 흐름 선택` → 공식 DB 조회 → 업무 블록별 입력·출력 기록 → 다음 수집 작업 계획 → **읽기 전용 종료** 노드가 실제 n8n 캔버스에서 움직입니다. 기본값 `mode:"inspect"`이므로 Job을 만들지 않습니다.
3. 실제 수집이 필요한 경우에만 관리자가 n8n의 기본 **HTTP Header Auth Credential**을 생성해 **Authorization** 헤더에 `Bearer <서버 ADMIN_TOKEN>`을 연결합니다. 자격증명은 n8n 암호화 저장소에서만 관리해야 합니다. **채팅·GitHub·파일 JSON에 토큰을 기입하지 않습니다.**
4. 첫 번째 코드 노드의 `mode:"inspect"`를 명시적으로 `mode:"collect"`로 바꾸고, 수집·결과조회 두 **HTTP Request** 노드에 Credential을 연결합니다. 이때 원본 검증과 실제 수집 가능 여부가 통과해야 **IF 참 분기**가 작동하여 기존 Railway G2B Worker Job 1건을 등록합니다.
5. n8n 캔버스의 **Worker 처리 대기 20초 → 실제 Worker 상태 → Worker 응답·기한 검증**을 반복합니다. 완료·실패·취소 또는 생성 후 **15분 경과**하면 반복을 중지합니다. `POLL_TIMED_OUT`은 **작업 완료가 아니며 자동 재등록하지 않습니다**. 등록된 Job은 `/n8n/progress?flow=PF05`에서도 확인할 수 있습니다.
6. 최종 `EVIDENCE_VERIFIED`는 해당 **공식 원본 증빙 검증**까지 통과했을 때에만 표시됩니다. 단순 Worker 정상 종료는 `COLLECTED_BUT_EVIDENCE_PENDING`으로 구분합니다.

PF12 최종 승인, PF14 자원 관리, PF15 장애 복구는 수집 Job 자동 등록이 금지됩니다. PF05의 정확한 10자리 세부종목 **공식 원본** 확인 없이 10년 개찰·확정 낙찰 수집을 시작하지 않습니다. 후보 공고 목록은 투찰·낙찰 결과가 아닙니다.

## 안전장치와 복구

- n8n 단일 엔진이 분기·대기·반복을 담당합니다. FastAPI는 실제 G2B 수집 및 Worker의 입력·출력 계약과 서버측 검증·조회만 담당합니다.
- **중복 요청:** `bid_no + flow_id + request_key` 조합이 같으면 하나의 Job만 등록하며, 응답이 유실되면 실제 Job 설정의 동일 식별자로 기존 Job을 회수합니다. 원래 Job이 확인되지 않는 예약은 HTTP 409로 차단합니다.
- **공유 수집기:** 동시에 같은 자원의 Job 2개를 실행하지 않습니다. 활성 G2B 기능 Job은 발주당 3개를 초과할 수 없으며(실제 INSERT 앞 DB 잠금), 최근 30분 수집은 재등록하지 않습니다.
- **Worker 완료와 공식 증빙:** 별개의 판정입니다. 빈 데이터·조회 실패·기관 누락·10년 미완료를 `VERIFIED`로 가공하지 않습니다.
- **원본 식별자:** 이 버전에서 선택된 발주는 `R26BK01787028`입니다. 다중 발주 지원을 구현하기 전까지 무관한 발주를 자동 분석하지 않습니다.
- **입찰 제출:** 자동 투찰, 입찰참가 버튼 클릭, 전자서명은 구현하지 않습니다.

## API 계약

| HTTP | 경로 | 의미 |
|---|---|---|
| GET | `/api/n8n/operational/flows/{PF}/inspect` | 실제 원본/증빙 블록별 검증 (읽기 전용) |
| GET | `/api/n8n/operational/flows/{PF}/progress` | 실시간 Worker ID·상태 및 공식 증빙 충족률 (비밀값 제외) |
| GET | `/api/n8n/operational/flows/{PF}/next-action` | 실행 가능한 실제 공유 수집기 1건 또는 차단사유 |
| POST | `/api/n8n/operational/flows/{PF}/dispatch` | 관리자 인증, Job 1건, 멱등 키 필수 |
| GET | `/api/n8n/operational/flows/{PF}/jobs/{job_id}` | 관리자 인증, 실제 Worker 시간/결과 및 독립 검증 |
| GET | `/api/n8n/operational/flows/{PF}/dispatch-history` | 관리자 인증, 수집 발행 이력 |
| GET | `/api/n8n/native/status` | n8n API 키 구성 시 운영 n8n의 실제 실행 기록 |

HTTP 200/워크플로 성공은 G2B 업무 전수 완료와 다릅니다. 모든 상태값은 실제 저장된 데이터로만 판단합니다.

## 배포·검증

- n8n 2.44.6의 내장 `manualTrigger`, `code`, `httpRequest`, `if`, `wait`만 사용합니다. 자체 커스텀 노드 패키지와 React Flow는 필요하지 않습니다.
- 운영 파일: `n8n/operational/PF01.json` ~ `PF15.json`. 가상 시나리오: `n8n/workflows/S01.json` ~ `S10.json`.
- 운영 DB 최초 가져오기 또는 파일 버전 갱신 시에는 통제된 n8n Main 배포 단계에서 `n8n import:workflow --separate --input=/home/node/procureflow-operational-workflows`를 사용합니다. **재시작 때마다 임의로 덮어쓰지 마세요.**
- `scripts/qa_n8n_operational_nodes.cjs`와 `tests/test_n8n_job_bridge.py`가 각각 실제 n8n Code JS(시간초과/신원확인)와 서버 Job 이중 등록·복구를 검사합니다.
- `.github/workflows/n8n-postdeploy-native-pf.yml`에서 실제 n8n 2.44.6 CLI로 PF01~PF15의 기본 안전 조회 분기를 운영 G2B API에 대해 검증합니다. 이는 **실제 collect 분기나 10년 전수 수집의 완료 증거가 아닙니다.**
- 최초 n8n 관리자 소유권과 인증을 구성하지 않은 상태에서는 운영 n8n 공개 도메인을 열지 않습니다. 위 읽기 전용 모니터만 API 서비스에서 볼 수 있습니다.
