# 공공입찰 실제 데이터 수집 및 104기능 현황 — 2026-11-03 추가 검증

## 실제 수집 요청의 결과 (모의 아님)
사용자는 가상 테스트가 아니라 실제 G2B 자료 수집을 요청했다. 기존 운영 Worker의 공공입찰 한 건만 실제 실행했다.
- 실제 대상: `R26BK01787028 / 000`, 10자리 관측 코드 `8111159901`.
- 운영 PostgreSQL 기존 실측: 8자리 후보공고 444건(개찰·낙찰 실적과 다름), **10자리 원본 확인 238건**, 실제 개찰업체 **246행**, 금액 있는 개찰 **156행**, 공식 확정 낙찰 **0건**.
- 국가종합전자조달시스템에서 원본 파일 4개(공고문 HWP/PDF, 과업지시서 HWP, 공내역서 XLSX) 다운로드·해시·파싱 이력 저장됨.
- 실제 기존 작업 `1681`: 2026-11-03 Worker 재가동 후 공식 공개 개찰 조회, `completed_partial`. R26BK01716629의 개찰업체 4행 조회·중복 0건 증가, 최종 낙찰 정보는 없음.
- 신규 실제 작업 `1685` 공고 원본 재조회: `completed_partial` 2026-11-03T12:04:33Z. `official.status=blocked_missing_official_api_key`, 공개 보조출처 처리, 새 건수 0.
- 신규 실제 작업 `1686` 정확한 10자리 과거 개찰·낙찰 조회: `completed_partial` 2026-11-03T12:05:54Z, checked 1/added 0. 10년 공식 전수 및 확정 낙찰 완료 아님.
- 최초 1685/1686 등록 때 `jsonb` 내 이중 직렬화 형식 오류로 즉시 실패했으며, **동일 작업 ID의 config만 올바른 object로 수정하여 정상 재실행**한 결과가 위 최종 상태.
- 기존 `procureflow-worker`를 1회 재가동해 정체된 1681번을 정상 종료, 기존 DB 초기화·n8n 재설치·계정 생성 없음. 작업 등록용 임시 Railway Function은 최종 조회 후 삭제해 상시 외부 공개 서비스로 남기지 않음.

## 실제 운영 화면
- https://procureflow-n8n-native-canvas-production.up.railway.app/admin/index.html?section=public
- https://procureflow-n8n-native-canvas-production.up.railway.app/api/procurement/public/actual-records
- 실제 G2B 현황 원본 API: https://procureflow-api-production.up.railway.app/api/g2b/full/exact-outcomes
- 소스 SHA `d3222282f6938ee1f06fd7538072b784e9dc7353`, Studio Railway 배포 `72fc72b9-28f8-4cd7-9697-9df521a47127` SUCCESS.
- 공용 Studio 서버는 실제 기존 FastAPI GET 데이터만 읽고, 허구의 업체·가격을 메인 화면에 사용하지 않음. 기존 43개 MOCK은 접힌 개발 진단 영역에만 남음.
- Chrome E2E: https://github.com/lyonbegin/procureflow/actions/runs/41631780378 SUCCESS. 별도 공개 브라우저에서 238/246/156/0, 실제 업체명과 원본 URL, 4건 원본 파일, HOLD 표시 확인.

## 중요한 미완료 및 진실성 기준
- `/api/g2b/full/schedule`상 공식 공공데이터 서비스 키가 아직 **미설정**. 121개월 중 공식 전수 검증 0개월, 기존 후보 공고 444건을 10년 완료로 주장하면 안 됨.
- 별도 공개 입찰 사이트에서 현재 사건의 9개사 개찰·낙찰업체/금액 표기를 발견했지만, 사이트 간 최종 낙찰 확정 표현이 달라 공식 확정 낙찰은 0으로 유지.
- 현재 운영 DB 원본 기능 승인 **8/104**, 미충족 96/104. 모의 계약 처리 104/104를 실제 수집·원본 증빙 완료라고 절대 보고 금지.
- 원가·견적·참가자격·가격 산식·과거 확정 낙찰·실제 제출 문서가 미충족, **HOLD**. 선택 공고 자체의 투찰 마감 2026-10-29 10:00은 이미 지남.
- 새 운영 n8n Execution ID를 받는 동작과 104개 Worker 실처리 전수는 아직 미완료. 실제 API 공개조회 및 bounded 실제 작업 실행은 수행됐지만 “자동화 완료” 아님.
- B/C의 소스 구현 변경은 없음. 기존 Worker 재시작의 평소 스케줄은 별도로 돌아갈 수 있으며 공공 전용 신규 기능과 구분한다.

---

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
