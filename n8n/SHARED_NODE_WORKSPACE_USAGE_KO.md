# ProcureFlow — 공통 n8n Studio 노드 입력·이력·재실행 모듈 사용 지침

## 노드 실행 버튼 UX (공통 v3)

- **노드 위 `▶ 실행`: 모달을 열지 않고 저장된 최신 INPUT으로 허용된 어댑터를 실행합니다. 캔버스가 보이는 상태로 노드가 실행 중/성공/실패 색상과 상태를 표시합니다.** 실행 기록은 서버 SQLite에 남습니다.
- **노드 위 `⚙ 설정·이력`: 사용자가 이 버튼을 명시적으로 눌렀을 때만 노드 작업 공간 모달을 엽니다.** 이때 저장된 실제 실행 OUTPUT과 수정 이력을 조회합니다.
- 모달의 `저장 후 ▶ 다시 실행`은 입력 편집 상황에서 명시적으로 실행 요청하는 별도 동작입니다. 새 모달을 열지 않습니다.
- 이 정책은 공통 UI 동작이며 ProcureFlow 등 실제 어댑터 미연결 노드의 ▶ 실행은 비활성화됩니다.
- 실제 Chromium 검증: https://github.com/lyonbegin/shared-n8n-studio/actions/runs/41229102100 (25/25 통과, Strategy/Library 모두 ▶ 클릭 후 모달 0개 확인).


> 갱신: 2026-11-01  
> 소비 프로젝트: `lyonbegin/procureflow` `main`  
> 공통 코드: https://github.com/lyonbegin/shared-n8n-studio  
> **기준 검증 커밋(독립 VueFlow Studio)**: `ae6653a8c4daae5d767c4d9c98b662ffc597a797`  
> 공통 모듈 브라우저 테스트: https://github.com/lyonbegin/shared-n8n-studio/actions/runs/41229102100 (25/25, 주식 N01 적용 검증)  
> 공통 원본 설명: https://github.com/lyonbegin/shared-n8n-studio/blob/feature/wf01-canvas-20261029/docs/SHARED_NODE_WORKSPACE_KO.md

## 1. 현재 적용 상태를 먼저 구분

ProcureFlow의 **현재 실제 업무용 편집기는 공식 n8n 2.44.6**이고 `n8n/editor-proxy`는 Caddy 프록시입니다. 기존 `n8n/native-preview`는 별도 VueFlow 조회/미리보기입니다.

이번에 추가된 **공통 노드 작업 공간 v2**는 `shared-n8n-studio`의 `playground/src/SharedNodeWorkspace.vue` 및 `server/node_workspace_store.py` 등에 구현된 **독립 VueFlow Studio 기능**입니다. **ProcureFlow 공식 n8n 편집기나 운영 PF01~PF15에 자동 적용된 것은 아닙니다.**

| 구분 | 상태 |
|---|---|
| 공통 저장소에 노드 위 `▶ 실행`, `⚙ 설정·이력` UI | 구현·주식 테스트 통과 |
| 공통 입력 JSON/실행 설정의 버전별 SQLite 저장 | 구현·주식 테스트 통과 |
| 이전 입력을 다시 불러오기 및 출력 JSON 변경점 비교 | 구현·주식 N01에서 테스트 통과 |
| URL/Python 코드 초안 작성/버전 저장 | 구현·공통 UI 테스트 통과 |
| ProcureFlow의 공식 n8n 2.44.6 에디터에 해당 기능 통합 | **미구현/미검증** |
| ProcureFlow 업무 노드 실행기/Worker에 연결 | **미구현/미검증** |
| 변경한 임의 Python/HTTP 초안 즉시 실행 | 지원하지 않음 |

즉 지금의 문서는 **ProcureFlow 개발자가 공통 v2를 재사용할 때 따라야 할 연동·시험 설명서**입니다. 기존 운영 n8n 및 실제 G2B 수집·낙찰/투찰 로직을 수정했다는 의미가 아닙니다.

## 2. 어디를 가져오고 어디를 직접 연결하나

| 모듈 소유 저장소 | 위치 | 용도 |
|---|---|---|
| `shared-n8n-studio` | `playground/src/SharedNodeWorkspace.vue` | 노드 입력 JSON, API URL·Python 코드 초안, 버전 복원, 결과 비교 공통 UI |
| `shared-n8n-studio` | `playground/src/App.vue`, `style.css` | 노드 위 버튼, VueFlow 상태 |
| `shared-n8n-studio` | `server/node_workspace_store.py` | 브라우저별 SQLite 입력·설정 수정 이력 |
| `shared-n8n-studio` | `server/studio_server.py` | 공통 `nodes/workspace` REST 경로; **현재 일부 투자 전용 코드 포함** |
| ProcureFlow | `n8n/operational/PF01.json`~`PF15.json`, `n8n/workflows/S01.json`~`S10.json` | 사업별 워크플로 데이터 |
| ProcureFlow | `main.py`, 기존 API/Worker, n8n Credential | 실제 G2B 요청, 권한, 업무 상태, 실행 엔진 — 공통 UI에 이관 금지 |

**주의:** 현 공통 `studio_server.py`는 `/app/dist/stock-workflows/(operations|scenarios)/...`를 참조하며, `App.vue`의 선택 목록은 `investment-adapter.js`에 고정되어 있습니다. 따라서 **ProcureFlow가 원본 Dockerfile을 복사하고 PF 파일만 추가한다고 곧바로 동작하지 않습니다.** 프로젝트별 목록 어댑터, fixture 경로 매핑, 서비스 인증, 실제 노드 runner를 별도 구성·검증해야 합니다. 범용 패키지화는 별도 후속 작업입니다.

## 3. 재사용 순서 — 운영 엔진과 분리된 테스트에서만

1. 테스트용 브랜치/별도 서비스를 구성하고, 공통 Git 커밋 `ae6653a8c4daae5d767c4d9c98b662ffc597a797`을 고정해 소스 전체를 참조합니다. 최신 `main`을 무조건 사용하지 않습니다.
2. 독립 VueFlow Studio 기반 테스트 서비스를 선택한다면 `SharedNodeWorkspace.vue`, `node_workspace_store.py`, `studio_server.py`, `App.vue`, `style.css` 버전을 **동일 커밋으로** 맞춥니다. 호환되는 `investment-adapter.js` 대신 ProcureFlow의 PF/S 목록 어댑터를 별도 개발합니다.
3. 실제 PF 운영 파일을 자동 활성화하지 않습니다. 테스트 전용 합성 `PF01_SANDBOX` 노드만 등록하고 공식 15개 운영 PF의 `active:false` 및 증빙·투찰 차단 규칙을 보존합니다.
4. 공통 서버가 현재 파일명/노드 ID를 찾도록 `operations|scenarios` 경로·워크플로 매핑을 검증합니다. 원본 n8n JSON node id/name/type/parameters/connection을 훼손하지 않습니다.
5. `GET /api/studio/nodes/workspace`로 빈 설정 확인, `PUT`으로 입력과 HTTP/Python 초안 저장, `GET /revisions`로 v1/v2 복원 검증. 같은 브라우저의 `studio_sid` 범위 내에서만 이력이 보입니다.
6. 프로젝트 별도 **허용 실행 어댑터**를 등록하기 전에는 `▶ 실행`을 비활성화합니다. `server/wf01_node_executor.py`는 투자 프로젝트 N01 전용이므로 ProcureFlow에 연결/복사하여 업무 코드를 실행하면 안 됩니다.
7. 승인된 테스트 어댑터와 *synthetic* 입력만 있을 때 `INPUT 변경 → v1 저장 → 실행 → v2 저장 → 재실행 → OUTPUT diff` 검증. 실제 API 호출·G2B Job 발행은 별도 명시 승인 후 검증합니다.
8. UI를 공식 n8n 2.44.6 에디터 내부로 넣으려면 추가 n8n Vue 컴포넌트 포팅과 upstream 호환성 검증이 필요합니다. 기존 `n8n/source-build/Dockerfile`에 공통 VueFlow `App.vue`를 복사하는 것으로는 공식 n8n 화면을 바꿀 수 없습니다.

## 4. 사용자가 시험 화면에서 수행해야 할 순서

해당 프로젝트의 **격리된 공통 VueFlow Studio 시험 배포가 완료된 이후에만** 아래를 실행할 수 있습니다. 현재 ProcureFlow 전용 실행 URL은 이 문서에서 제공하지 않습니다.

1. 시험 PF 노드의 위쪽 `⚙ 설정·이력` 클릭.
2. `① INPUT JSON`을 수동 편집하고 `설정 버전 저장` 클릭.
3. `② 수정 이력`에서 v1, v2 비교, 이전 입력 불러오기/새로운 v3으로 저장.
4. `③ 실행 설정 초안`의 HTTP Method·API URL 또는 Python module/function/code 수정. **이 변경은 직접 실행되지 않음**.
5. **검증된 시험 실행 어댑터가 등록되어 있는 노드에만** `저장 후 ▶ 다시 실행` 활성화.
6. `④ 실제 실행 결과`와 `⑤ 이전 실행과 OUTPUT 비교`에서 JSON 변경 필드 및 오류 확인.
7. 새로고침 후 같은 세션에서 입력·설정 이력 보존 및 노드 상태 복원 범위를 검사.
8. Chrome으로 노드 이동/연결선 조작과 도구모음 클릭이 충돌하지 않는지 시험.

`OUTPUT diff`는 성공한 실행 결과 두 건 이상이 존재할 때만 표시됩니다. 저장 초안과 실제 실행한 코드가 동일하다고 가정하면 안 됩니다.

## 5. 공통 서버 REST 계약

```http
GET /api/studio/nodes/workspace?workflow=operations/PF01_SANDBOX.json&node_id=pf-node-01
GET /api/studio/nodes/workspace/revisions?workflow=operations/PF01_SANDBOX.json&node_id=pf-node-01
PUT /api/studio/nodes/workspace
Content-Type: application/json
```

**위 워크플로 파일명과 node ID는 미래에 별도 배치할 테스트 fixture의 예시로, 현재 설치된 ProcureFlow API 경로라는 뜻이 아닙니다.**

PUT 예제:

```json
{
  "workflow": "operations/PF01_SANDBOX.json",
  "node_id": "pf-node-01",
  "expected_revision": 0,
  "input_json": {"mode": "inspect", "page": 1},
  "execution_draft": {
    "kind": "http",
    "http_method": "GET",
    "api_url": "https://example.invalid/test-only",
    "notes": "검증 목적의 URL 초안. 실행 금지"
  }
}
```

저장 결과의 `workspace.code_execution_approved`는 `false`입니다. 저장 시 새 SQLite 버전이 생성되며, 버전 충돌은 409를 반환해야 합니다. 이 REST 인터페이스는 **업무 실행 API도, n8n 워크플로 활성화 API도 아닙니다**.

## 6. 기존 ProcureFlow 운영 보안과 구분

- 공통 Studio 브라우저별 익명 세션 쿠키는 **운영 사용자 인증·RBAC를 제공하지 않습니다.** 운영 PF 편집에 그대로 노출하면 안 됩니다.
- API Token, G2B 서명, DB 연결 문자열, Credential은 INPUT JSON 및 Python/URL 초안에 저장하지 않습니다.
- ProcureFlow의 공식 n8n 계정·Credential·실제 Worker와 공통 Studio 별도 서비스의 테스트 데이터를 혼합하지 않습니다.
- 기존 `PF05`의 증빙 검증·수집 Job 중복 방지 및 PF12/PF15 관련 자동 행위 차단은 유지합니다.
- 프로젝트별 실행기에서 허용된 코드 버전·소스 해시·입출력 스키마·작업 권한·멱등 키 등을 검증할 때까지 노드 실행 금지.

## 7. 회귀/도입 판정

공통 모듈 자체의 참조 CI: https://github.com/lyonbegin/shared-n8n-studio/actions/runs/41229102100 (25/25 Chromium 통과). **주식 자동화 N01에 대한 증거**이며 ProcureFlow 실제 실행 증거는 아닙니다.

ProcureFlow 도입 완료를 주장하려면 최소한 다음을 통과해야 합니다:
- PF/S 워크플로 선택, 원본 노드 유형/연결선 보존
- 실제 브라우저 노드 위 버튼 클릭, 드래그·핸들 충돌 없음
- INPUT v1→v2→v3 복원, 쿠키별 DB 분리와 409 충돌 차단
- 실행 어댑터 없이 임의 Python/URL 실행이 차단됨
- 승인된 **합성** 노드 실행 결과/JSON diff, 신규 노드 버전 검증
- 운영 PF01~PF15/프로덕션 G2B DB/실제 투찰 상태 미변경

공통 모듈의 버전 업데이트가 필요하면 **공통 저장소에서 먼저 수정·테스트 → 커밋 고정 → ProcureFlow 테스트 프로젝트 연동 → 브라우저 수락 검사** 순서를 지킵니다. 소비 프로젝트에서 공통 UI 코드를 복제해 독립적으로 발전시키지 않습니다.
