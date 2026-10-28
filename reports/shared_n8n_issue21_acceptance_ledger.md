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
