# Issue #21 / Draft PR #22 — 격리 검증 증빙 원장

> 범위: `feature/shared-n8n-pan-integration`만 해당. **전체 필수 수용검사는 미완료**이며 이 문서는 배포 승인서가 아닙니다. 운영 `main`, Railway 운영 서비스·DB, 자격증명, 실제 투찰을 변경하지 않습니다.

## 실측 증빙 (2026-10-28 UTC)

| 검증 항목 | 실행 증빙 | 판정 |
|---|---|---|
| 공식 upstream n8n 2.44.6 소스 빌드 + 공유 Pan 고정 커밋 `999062f1676bdffafa852a36e6c986ef5ce7589f` | [공식 소스 빌드](https://github.com/lyonbegin/procureflow/actions/runs/40733790543), [후보 Docker 빌드](https://github.com/lyonbegin/procureflow/actions/runs/40733790644) | **PASS — 격리 빌드** |
| 원본 `Canvas.vue` 실제 Chrome Pan·Shift 선택·노드 추가/삭제·연결·이동·줌·설정·서버 저장/재열기 | [Chrome 16/16](https://github.com/lyonbegin/procureflow/actions/runs/40726387142), [스크린샷·trace·verdict](https://github.com/lyonbegin/procureflow/actions/runs/40726387142/artifacts/12833766215) | **PASS — 공식 UI 실측** |
| 실제 시험용 Code 노드 실행 ID·상태·출력 및 S01–S10 Chrome 가상 시나리오 | [Chrome 10/10 및 실행 로그](https://github.com/lyonbegin/procureflow/actions/runs/40726387142) | **PASS — 합성·격리 시나리오만** |
| 독립 SQLite 후보 n8n에 PF00–PF15 + S01–S10 **26개** 원본 워크플로 임포트 | [후보 CI 40733790644](https://github.com/lyonbegin/procureflow/actions/runs/40733790644), [실행 로그·워크플로 JSON](https://github.com/lyonbegin/procureflow/actions/runs/40733790644/artifacts/12836202751) | **PASS — 26개 실제 임포트** |
| 후보 n8n 커스텀 Business Operation 등록, **43개** `operationId` 선택지, success/HOLD 포트, 그래프 43개 게이트 | [후보 CI 40733790644](https://github.com/lyonbegin/procureflow/actions/runs/40733790644): `OFFICIAL_NATIVE_PF_IMPORT_PASS` 및 `OFFICIAL_N8N_BUSINESS_OPERATION_REGISTERED` | **PASS — 등록·연결 검증만** |
| **통합 후보 공식 Chrome**에서 Business Operation 검색 팔레트 추가 → 실제 `operationId=N02` 선택 → 서버 저장/재열기 → 삭제 | [Chrome 후보 CI 40737474081](https://github.com/lyonbegin/procureflow/actions/runs/40737474081), [스크린샷·trace·verdict 및 서버 로그](https://github.com/lyonbegin/procureflow/actions/runs/40737474081/artifacts/12837718281) | **PASS — 실제 Chrome 편집/설정/영속화, 업무 노드 미실행** |
| 50종 노드 UI 계약 (14 native / 7 composite / 29 extension), 43 업무 블록, 104 기능 | [계약 감사 CI 40733790606](https://github.com/lyonbegin/procureflow/actions/runs/40733790606) | **PASS — 정적 계약만** |
| 별도 디버깅 81–160 (총 80개) | [정적 감사 CI 40733790606](https://github.com/lyonbegin/procureflow/actions/runs/40733790606), [원본 기준표](workflow_81_160_implementation_20261025.md) | **미완료 — 구현 19 / 부분 47 / 미구현 14, 런타임 실증 0** |
| 기능 브랜치의 read-only 증빙 노드 보안 게이트 | [단일 편집기·단위 테스트 CI 40733790609](https://github.com/lyonbegin/procureflow/actions/runs/40733790609) | **PASS — 단위 테스트, 실제 43개 업무 핸들러 미실행** |

이전 후보 CI [40730751813](https://github.com/lyonbegin/procureflow/actions/runs/40730751813)는 커스텀 노드 조회 시 n8n 응답의 네임스페이스/응답 구조를 잘못 가정하여 실패했습니다. 후속 격리 CI [40733790644](https://github.com/lyonbegin/procureflow/actions/runs/40733790644)에서 공식 n8n 응답 `procureFlowBusinessOperation`을 확인하고 43개 옵션 및 26개 워크플로가 실제로 검증되어 **SUCCESS**였습니다.

## 기능 브랜치 안전성 강화 — 격리 CI PASS

`n8n/custom-nodes/ProcureFlowBusinessOperation.node.js`는 API 응답의 공식 출처·읽기 전용 플래그·실행 엔진·자동 투찰 금지·유일한 블록·입출력 계약을 검증하며, VERIFIED 판정 시 **기능 번호의 정확한 집합**과 누락 증빙 0건을 요구합니다. `tests/test_procureflow_business_operation.mjs`의 오탐 방지 회귀 테스트는 [현재 코드 SHA `66ac465`의 단일 편집기 CI 40737474057](https://github.com/lyonbegin/procureflow/actions/runs/40737474057)에서 통과했습니다. 동일 SHA의 [공식 후보 Docker + Chrome CI 40737474081](https://github.com/lyonbegin/procureflow/actions/runs/40737474081)도 성공했습니다. **가상 VERIFIED 응답의 단위 테스트 성공은 실제 공식 증빙 확보가 아닙니다.**

## 필수 미완료 — 전부 PASS 전에는 완료/병합/배포 금지

1. 50종 중 29 extension + 7 composite의 공식 n8n 실행 매핑 구현·실증 또는 미지원 종류를 실제 공식 편집기에서 비활성화하고 검증.
2. 43개 업무 블록의 **실제 수집·판정 핸들러**, 엄격한 입출력 JSON Schema, 발주·개찰·낙찰 원본 증빙 출처, 권한·Worker 안전 실행의 독립적인 실제 검증. 현재 커스텀 노드는 **읽기 전용 증빙 검사기**이며 `actual_business_handler_executed=false`입니다.
3. 정확한 세부종목·10년 개찰/낙찰 공식 데이터 완전성, 분리 Worker 재시도·동시성·fencing, 실제 G2B API 증빙.
4. 디버깅 80개 항목 각각의 실제 Chrome·n8n·Worker 재현 및 PASS 기록. 현재 정적 목록 감사만 통과.
5. 원본 n8n DB 백업·암호화 키/Worker 호환성·복구·보안·운영 전환 승인. 실제 Railway 및 운영 DB 변경은 허용되지 않습니다.

**Issue #21은 Open, PR #22는 Draft·미병합으로 유지합니다.** 위 PASS는 격리된 빌드·브라우저·워크플로 임포트·노드 등록 범위에서만 유효합니다.

## 2026-10-29 후속 구현 — 정확한 10년 이력 수집의 실제 Worker 연결

- `g2b_feature_api.execute_one`의 `collect_exact_ten_digit_outcomes` 경로가 기존의 후보 몇 건만 읽는 `run_batch` 직접 호출을 중단하고, **기존 공식 121개 월별 공고 검색 커서 → 원본 10자리 확인 → 실제 개찰·낙찰 조회**의 한정 실행으로 연결됨.
- Worker Job 1회당 **월별 구간 1개, 페이지 최대 2개**만 진행하며, 이미 저장된 다음 페이지를 재개함. 121개 전수 실행 완료를 주장하지 않음.
- API에서 `totalCount`가 있으나 응답 페이지가 비어 있거나 중간에서 잘린 경우, 다른 달 공고/잘못된 공고번호/분류 미확인 항목이 섞인 경우 **해당 월을 완료 처리하지 않고 차단**. HTTP 오류 예외 문자열로 공식 API 인증키가 DB/화면에 노출되지 않도록 변경함.
- `GET /api/n8n/operational/history/month-progress`와 n8n `/n8n/progress?flow=PF05` 읽기 전용 패널에서 121개 중 완료·잔여 월, 다음 월/페이지, 검색 상태를 확인할 수 있음.
- 121개 월별 공고 검색은 **8자리 `81111599`의 후보 탐색**에 불과함. 공식 10자리 `8111159901`의 원문 확인 및 실제 투찰자별 금액·순위·최종 낙찰 **전수 검증은 별도**이며, 월별 완료율이 100%여도 자동으로 VERIFIED를 반환하지 않음.
- 새 격리 단위 회귀: 잘린 페이지, 빈 페이지, 잘못된 월/번호, 정상 월, 인증키 비노출, Worker 월별 재개와 예외, 모든 121개월을 완료 처리한 상황에서의 10자리 낙찰/개찰 미완료 판정, 읽기 전용 진행 API. [GitHub Actions 40771630211](https://github.com/lyonbegin/procureflow/actions/runs/40771630211) **Python 63 PASS**. 원본 G2B 공공 API에 대한 실제 121개월 작업 실행은 이 CI에서 수행하지 않았음.

**배포는 여전히 금지:** 기능 브랜치에 한정해 코드를 구현하고 합성 테스트를 통과했을 뿐, 공식 API 키·운영 DB·실 Worker의 121개월 실제 결과와 최종 개찰/낙찰 원본은 미검증이다.

