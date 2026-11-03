# 공공입찰 한 건 중심 104기능 업무 통합 — 2026-11-03 인수인계

## 적용 범위
공공입찰(A형) **한 건만** 수정했다. 선택 사례 `R26BK01787028 / 000`, 10자리 코드 `8111159901`(구성/관측 코드이며 공식 원본 검증 완료는 아님). 민간 SW 개발(B형), 민간 인력용역(C형)은 원본 코드 그대로 보존하고 회귀 검사만 한다.

실제 G2B/고용24 크롤링, 외부인 접촉, 실제 투찰, 공식 n8n 관리자 신규 설정, 기존 n8n Main/Worker/PostgreSQL 초기화 및 설정 변경은 하지 않는다.

## 배포 위치
- 공공 입찰관리: https://procureflow-n8n-native-canvas-production.up.railway.app/admin/index.html?section=public
- 기능별 검증: https://procureflow-n8n-native-canvas-production.up.railway.app/admin/index.html?section=features
- 43개 원본 블록 노드 캔버스: https://procureflow-n8n-native-canvas-production.up.railway.app/?workflow=operations%2FA01-public-win-strategy.json
- 기존 업무 DB 읽기 전용 조회: https://procureflow-n8n-native-canvas-production.up.railway.app/api/procurement/public/verified-evidence
- Studio 검증 Actions: https://github.com/lyonbegin/procureflow/actions/runs/41627453611
- Source PR: https://github.com/lyonbegin/procureflow/pull/26
- Railway Studio 배포 ID: `e3416401-733b-46ba-a579-964c5f2f8d7a` (SUCCESS), 소스 SHA `90aadcb58742156d5ef837a89e4e8bb3c915ca1a`

## 기존 코드 재사용
- `g2b_feature_registry.py`: 기존 104개 기능 이름, 7개 업무영역, 기능별 `FEATURE_GATES`.
- `g2b_feature_contract_core.py`: 운영 `g2b_feature_api.py`의 `contract_params`, `collection_action`, `feature_contract`를 순수 모듈로 공통화. 기능별 입력 조건, 실제 운영 수집기/검증기 선택, 외부 Worker 상태·필수 증빙 조건, 공식 검증 미충족 결과를 동일한 코드로 평가한다. Studio는 **수집기를 실행하지 않고 계약만 계산**한다. API의 변경분은 feature branch에 있으며, 운영 API의 main 배포를 변경하지 않았다.
- `n8n/operational_manifest.json`: 기존 43블록 및 104기능 배치 그대로.
- `n8n/strategy-runtime/public_case_runtime.py`: 원본 43블록의 topological 순서로 허구의 입찰자료를 입력받고 기능별 original contract를 검증하는 고정된 *모의 노드 처리*. 원본 생산 수집·계산 함수가 모두 실행됐다는 뜻이 아님.
- `n8n/strategy-runtime/procurement_readonly_bridge.py`: 실제 운영 DB를 읽는 기존 원본 FastAPI PF01~PF15 `/api/n8n/operational/flows/PFxx/inspect`의 **GET만** 요청한다. 15개 실제 응답을 43블록/104기능으로 합치며 source/flow/case/official gate 검증을 한다. 사용자 제공 URL, HTTP POST, 실제 G2B 접근, Worker 실행, DB 쓰기 경로가 없음. 실패 시 503 / UNKNOWN으로 처리하며 공식 완료로 간주하지 않는다.
- `n8n/admin-console/public-case.js`: 선택 공고 중심 업무·노드·낙찰모의전략·가격·제안서·104 기능표·SQLite 이력과 운영 DB의 실제 공식 증빙 상태를 **별도 표/지표**로 표시한다. 운영 DB 조회는 사용자가 버튼을 누를 때만 수행.
- `shared-n8n-studio/server/studio_server.py`: `GET /api/procurement/public/verified-evidence` 단일 read-only API; 발주업무 운영자 계정/신규 n8n 서버 생성 없음.
- `n8n/Dockerfile.shared-studio-editor`: 기존 Studio의 원본 코드 사용, 위 공공 전용 모듈만 포함.

## 실제 검증
1. Python: 원본 104개 계약, 기존 43개 노드 계약, 121개월 **모의** 기간, 원본 API action/required verified gates 정확 일치, 공식 미확인 시 HOLD. B/C 모의 7/7+7/7 회귀.
2. HTTP/SQLite: 공공 43개 + B/C 회귀 14개 (총 57개 승인 테스트 노드), 이벤트/전달선/실행 이력.
3. Chrome: 공공 발주 하나 선택 → 전체 43블록 모의 처리 → 104 기능표 → 가격·제안서 초안 → Run ID/입출력/SQLite 이력. 기존 S01/S02 시나리오 및 PF05 노드 저장/재열기도 통과.
4. Chrome의 운영 DB 조회 버튼은 테스트 CI에서 **가짜 응답으로 가로채 검증**, 실제 DB 호출 금지.
5. 별도 실제 배포 화면에서 운영 API의 GET-only 증빙 조회 수행: PF01~PF15 **15개**, 업무 블록 **43개**, 총 기능 **104개**, **공식 승인 8개 / 미충족 96개**, `official_notice_verified:false`, 입찰참가 준비 HOLD. 확인된 원본 코드 `8111159901`은 아직 `verified_official_detail10:[]`; 임의 승격 금지.
6. Railway 서비스 새 배포 및 GET 응답 PASS. 주식 자동화 운영에는 변경 없음.

## 아직 미완료: 완료라고 보고 금지
- 104개 기능이 운영 Worker에서 모두 실제 처리되었다는 증거는 없음. 모의 실행의 `104/104`는 **입력·결과·게이트 계약 테스트**이다.
- 운영 DB `8/104`만 공식 증빙 승인. 나머지 `96/104` 및 공식 10년 전체 개찰·낙찰 원본과 제출양식·회사 적격성·가격증빙 부재.
- Studio가 **공식 n8n 전체 워크플로 실행 ID**를 받는 연결은 없음. Studio의 Run ID는 SQLite 모의 실행이며 엔진 Execution ID가 아님.
- 공식 n8n Main/Worker 관리자 설정/기존 DB는 건드리지 않음. 신규 인증·권한 생성 없이 검증.
- 실입찰 제안서·최종 참가서류 준비 완료 아님. `HOLD`에서 READY로 바꾸지 않음.

## 이후 개발 방향
별도 A01 모의 프로그램이 원래 PF00~PF15를 대신해선 안 된다. *하나의 선택된 입찰*에서 기존 `g2b_feature_api`, `g2b_case_engine`, `g2b_bid_package`, 원래 Worker와 n8n 업무 DAG가 서로 실제로 연결되어 104개의 개별 원본 증빙·실행 ID·입출력 기록을 전달하도록 확장해야 한다. 사용자 요청 전에는 G2B 실수집·투찰 금지.
