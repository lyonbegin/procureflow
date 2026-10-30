# 조달청 자동화 공용 Studio 도입 — 개발·운영 인수인계서

> 작성 기준: **2026-10-30 KST** · 상태: **구현된 범위의 개발 문서** (최종 업무 완료 선언 아님)  
> 요구사항 정본: [2026-10-28 최종 기획](FINAL_PROJECT_MASTER_PLAN_2026-10-28.md)  
> 조달청 통합 PR: [#24](https://github.com/lyonbegin/procureflow/pull/24) (Draft)  
> **실제 확인된 편집기:** [PF05 — 10년 개찰·낙찰 분석](https://procureflow-n8n-native-canvas-production.up.railway.app/?workflow=operations%2FPF05.json)

## 2026-10-30 후속 개발: JSON 무손실 변환·Chrome 저장 검증·엔진 연결 사전 검사

**이 단락은 기존 인수인계서의 추가 변경 기록이다.** 공식 n8n의 인증 문제와 실업무 실행은 별도 미완료이며, 새 코드는 운영 Railway에 아직 재배포하지 않았다.

- **공용 소스 수정:** [shared-n8n-studio PR #5](https://github.com/lyonbegin/shared-n8n-studio/pull/5) · 검증 Git SHA `bff56f8544b2f2a521ca92b125c2d9641d8269e9`. 원본에 없던 `disabled:false` 필드 추가를 방지하고 연결의 원래 type, sourceIndex, targetIndex, 멀티포트·HOLD 출력/빈 포트 및 node metadata 보존. Studio 내보내기는 계속 `active=false` 강제.
- **26개 실제 n8n 원본 무손실 왕복 검사:** [CI #40971060236](https://github.com/lyonbegin/shared-n8n-studio/actions/runs/40971060236) **PASS**. PF00~PF15·S01~S10 전부 원본 → Vue Flow → n8n JSON 구조를 비교. PF05 Business Operation 이름·좌표 변경 후 성공/HOLD 분기 연결도 확인. 43개 비즈니스 게이트 검사.
- **소비자 이미지 소스 핀 갱신:** `n8n/Dockerfile.shared-studio-editor`가 해당 공용 SHA를 사용하도록 코드를 변경하고 CI도 맞춤. 실제 운영 Railway는 여전히 이전 `33bce353...` 커밋에 핀되어 있으므로 **새 코드가 운영에 배포됐다고 주장하지 않음**.
- **Chrome UI → 서버 저장 → 새로고침:** [CI #40971790335](https://github.com/lyonbegin/procureflow/actions/runs/40971790335) **PASS**. *격리 테스트 Studio/SQLite*에서 PF05 35개 노드·43개 연결 표시, 이름 수정, 실제 브라우저 `서버 저장` 클릭, `v1` 저장 확인, 새로고침 후 동일 이름 유지, 별도 브라우저는 원본 `v0` 유지. 저장본 `active=false`, 실제 업무 실행·관리자 생성 0건. **운영 서비스 SQLite에 직접 써서 검증한 것은 아님.**
- **기존 공식 n8n 조회 전용 브리지:** `n8n/studio-bridge/inspect-existing-n8n.mjs` 및 `tests/test_studio_existing_n8n_bridge.mjs`, [CI #40971790314](https://github.com/lyonbegin/procureflow/actions/runs/40971790314) **PASS**. `GET /rest/settings`의 owner 설정 여부 확인 → 준비 완료 및 서버 측 `N8N_API_KEY`가 있을 때에만 `GET /api/v1/workflows` 목록 조회·26개 원본 후보와 이름/중복 비교. POST/PUT/PATCH/DELETE, owner 생성, n8n 임포트·게시·실행은 없음. 인증이 없으면 `BLOCKED` 판정.
- **운영 공식 n8n 장애 확인:** 해당 게이트웨이 `/rest/settings`를 읽기 전용으로 재확인한 결과 `showSetupOnFirstLoad: true`. 관리자·DB 소유권/인증 복구 없이는 운영 엔진 실사용 미완료. 새 Studio의 로그인 없는 UI와 혼동하면 안 됨.

**다음 배포/연결을 위한 필수 조건:** 운영 초안 볼륨 보존·기존 운영 owner/워크플로 목록 조회 가능성·새 공용 SHA에서 Chrome 수용검사·보안 권한 설계 확인. 새 n8n 설치, owner 초기화, 비밀번호 우회, 자동 투찰 금지.

## 1. 개발 결론 및 범위

**주식 자동화가 사용하던 `lyonbegin/shared-n8n-studio` 소스의 Vue Flow 편집기와 초안 서버를 조달청 프로젝트가 재사용하도록 구현·배포했다.** 이미 있던 Railway `procureflow-n8n-native-canvas` 서비스 **한 개**의 구현을 교체했으며, 운영 중인 공식 n8n Main/Worker·PostgreSQL·Redis·기존 owner 기록은 변경하지 않았다.

기존 공식 n8n 서버를 재설치하지 **않았다**. 그러나 Studio 서비스의 배포에는 **다단계 Docker 이미지 빌드**를 사용한다. 'Docker를 전혀 사용하지 않았다'는 뜻이 아니다.

| 구분 | 실제 구현·검증된 범위 | 미완료/구분 필요 |
|---|---|---|
| 편집기 | 공용 Vue 3 / Vue Flow Studio, 조달청 모드, 노드 선택·설정 패널, 50종 팔레트 | **공식 n8n 인증 Vue 편집기 자체는 아님** |
| 워크플로 | PF00~PF15 **16개**, S01~S10 **10개** 원본 JSON 로드·편집 후보 | 운영 n8n PostgreSQL 등록/게시/실행은 별도 |
| 업무 노드 | 그래프에 Business Operation **43개**를 배치·HOLD 경로 검사 | 43개 업무 API가 모두 실행·성공한 것은 아님 |
| 업무 기능 | `n8n/operational_manifest.json`에 **104개 요구 기능 계약** | 실제 104개 기능 구현·증빙 완료 아님 |
| 저장 | 브라우저별 익명 쿠키 + 별도 Studio SQLite 초안/이력 | 운영 n8n DB 저장 또는 사용자 계정 동기화 아님 |
| 실행 | Studio 서버에서 G2B·Worker·투찰 실행 **차단** | S01~S10 실제 엔진 실행·진행상황 표시는 미연결 |
| 로그인 | 새 Studio URL은 `Set up owner account` 없이 화면 진입 | 기존 공식 n8n 게이트웨이의 owner 문제는 미해결 |
| Pan | **실제 Chrome 드래그로 Δ(+140,+75)px 확인** | 공식 n8n 편집기 Pan 검증과 별개 |

**요구사항 대비 한계:** [최종 기획](FINAL_PROJECT_MASTER_PLAN_2026-10-28.md) 6장에는 공식 네이티브 n8n에서 '편집 → 실제 서버 저장 → 실행 → 노드별 상태 확인'이 연속되는 UX를 요구한다. 이 문서의 공용 **Vue Flow Studio는 별도 초안 편집기**이므로 그 최종 수용 기준을 충족한 것으로 보고하지 않는다.

## 2. 참고한 실제 성공 사례: 주식 자동화

- 실제 투자 편집기: https://investment-n8n-native-editor-production.up.railway.app/?workflow=operations%2FWF01-pine-source-intake.json
- 투자 소스: [`autonomous-investor-backend/n8n/Dockerfile.native-editor-gateway`](https://github.com/lyonbegin/autonomous-investor-backend/blob/feature/editor-wf01-canvas-20261029/n8n/Dockerfile.native-editor-gateway)
- 투자 소스가 고정한 공용 커밋: `d43c30797569c83f07c42fd0439e62ec02b35601`.
- 주식은 `shared-n8n-studio/playground` UI와 `server/studio_server.py`를 재사용하고, 주식 워크플로 13개 JSON을 공개 정적 파일로 패키징한다. 서버는 브라우저별 SQLite 초안을 저장하고 주식 실행을 비활성화한다.
- 조달청도 **같은 공용 저장소/동일 편집기 구조**를 활용하되 조달청용 프로젝트 어댑터를 추가했다. 동일한 실제 n8n 실행 엔진을 공유한다는 뜻은 아니다.

## 3. 소스 소유권과 파일별 개발 내용

### 3.1 공용 편집기 소스 (공유 프로젝트가 소유)

- 원본: [lyonbegin/shared-n8n-studio](https://github.com/lyonbegin/shared-n8n-studio)
- 조달청 관련 개발 브랜치: `feature/procureflow-studio-adapter-20261029`
- 조달청 운영 이미지가 고정하여 사용한 Git SHA: **`18e2ce915265a5a2351383942c6f9312d802513f`**.

| 파일 | 구현 내용 |
|---|---|
| [`playground/src/procurement-adapter.js`](https://github.com/lyonbegin/shared-n8n-studio/blob/18e2ce915265a5a2351383942c6f9312d802513f/playground/src/procurement-adapter.js) | PF00~PF15 / S01~S10 경로·메뉴명, 총 26개 중복 검사 |
| [`playground/src/App.vue`](https://github.com/lyonbegin/shared-n8n-studio/blob/18e2ce915265a5a2351383942c6f9312d802513f/playground/src/App.vue) | `VITE_EDITOR_PROJECT=procurement`에 맞춰 조달청 목록·헤더·워터마크·선택/초안 저장키·기본 경로 제공. 주식 모드도 유지 |
| [`playground/src/investment-adapter.js`](https://github.com/lyonbegin/shared-n8n-studio/blob/18e2ce915265a5a2351383942c6f9312d802513f/playground/src/investment-adapter.js) | 재사용하는 `fromN8nWorkflow()` / `toN8nWorkflow()`, 원본 n8n 노드 유형/파라미터·연결 메타데이터 보존 시도 |
| `playground/src/node-catalog.js` | 공용 50종 노드 종류·필드·연결 포트 정의 |
| [`server/studio_server.py`](https://github.com/lyonbegin/shared-n8n-studio/blob/18e2ce915265a5a2351383942c6f9312d802513f/server/studio_server.py) | `STUDIO_WORKFLOW_DIR=procure-workflows` 추가; 익명 브라우저 쿠키별 스냅샷/버전 SQLite API. 외부 실행 없음 |

공통 UI 기능을 변경할 때마다 먼저 **이 공용 저장소를 수정**한다. 조달청 저장소에 공용 App.vue/컴포넌트 전체를 복사하여 제2의 편집기를 만들지 않는다. 공용 버전을 올릴 때는 검증된 commit SHA를 다시 핀한다.

### 3.2 조달청 프로젝트 소스 (소비 프로젝트가 소유)

- 저장소: [lyonbegin/procureflow](https://github.com/lyonbegin/procureflow)
- 작업 브랜치: `feature/procureflow-shared-studio-editor-20261030`
- 통합 PR: [#24](https://github.com/lyonbegin/procureflow/pull/24)

| 파일 | 역할 |
|---|---|
| [`n8n/Dockerfile.shared-studio-editor`](../n8n/Dockerfile.shared-studio-editor) | 기존 공용 Studio 고정 SHA checkout, 조달청 원본 26개 패키징, 공용 Python 초안 서버 실행 |
| [`n8n/operational_manifest.json`](../n8n/operational_manifest.json) | 업무 워크플로/43개 블록/104기능 **계약** |
| `n8n/operational/PF01.json`~`PF15.json` | 조달 운영 원본 후보 15개 |
| `n8n/source-build/compile-native-topology.mjs` | PF00 포함 운영 후보 16개로 컴파일 |
| `n8n/source-build/augment-business-operations.mjs` | 43개 Business Operation 게이트/연결 추가 |
| `n8n/source-build/test-native-topology.mjs`, `verify-packaged-graph.mjs` | PF 16개 + S 10개, 43개 게이트 정적 검사 |
| `n8n/workflows/S01.json`~`S10.json` | 가상/장애 시나리오 10개 원본 |
| [`.github/workflows/procureflow-shared-studio.yml`](../.github/workflows/procureflow-shared-studio.yml) | 공용 Studio 빌드·API·26개 JSON·43개 게이트·초안 저장 검증 |
| [`tests/shared_studio_live_pan.mjs`](../tests/shared_studio_live_pan.mjs) | 실제 배포 주소에서 Chromium 마우스 드래그/화면 이동 수치 검사 |
| [`.github/workflows/procureflow-shared-studio-live-pan.yml`](../.github/workflows/procureflow-shared-studio-live-pan.yml) | 실제 Chrome Pan 검사 CI |

### 3.3 배포 흐름

```text
shared-n8n-studio (고정 SHA 18e2ce9...)
  ├─ Vue3/Vue Flow App.vue + 50종 팔레트 + 조달청 어댑터
  └─ Python studio_server.py (별도 초안 API)
                    │
procureflow 업무 소스 ─┬─ PF01~PF15 + manifest + topology compiler
                     ├─ PF00 생성 + 43개 Business Operation 추가
                     └─ S01~S10 JSON (가상 테스트)
                    │
          n8n/Dockerfile.shared-studio-editor
                    │
        정적 JSON + Vite 빌드 + 공용 Python 서버
                    │
    [기존 Railway procureflow-n8n-native-canvas]
        ├─ Studio 편집기 화면 / port 3000
        └─ /data/studio.sqlite3 (신규 독립 초안 볼륨)

    [기존 운영 n8n Main/Worker/Postgres/Redis]
             ← 변경 없음 · 직접 연결 없음
```

**빌드는 Docker를 사용하지만 공식 `n8n start`/`n8n worker`를 새로 실행하거나 n8n owner를 등록하지 않는다.** 초안 SQLite는 n8n의 업무/인증 DB와 전혀 다르다.

## 4. Studio 화면과 저장 API

### 4.1 URL

| 목적 | URL |
|---|---|
| PF00 통합 흐름 | https://procureflow-n8n-native-canvas-production.up.railway.app/?workflow=operations%2FPF00.json |
| PF05 10년 개찰·낙찰 | https://procureflow-n8n-native-canvas-production.up.railway.app/?workflow=operations%2FPF05.json |
| S01 시나리오 | https://procureflow-n8n-native-canvas-production.up.railway.app/?workflow=scenarios%2FS01.json |

PF05 실제 브라우저 검증에서 **35 Nodes / 43 Connections**, 26개 PF/S 목록, 50종 팔레트, H01 클릭 시 노드 속성 패널 및 n8n 원본 Node Type/파라미터 표시를 확인했다. `Set up owner account` 없이 Studio UI가 열린다.

### 4.2 Studio API (공식 n8n REST API 아님)

| 메서드 | 경로 | 목적·조건 |
|---|---|---|
| GET | `/health` | 배포 프로세스 health |
| GET | `/api/studio/health` | `{"status":"ok","storage":"sqlite","executionEnabled":false,"mode":"isolated-demo"}` |
| GET | `/api/studio/workflows/operations/PF05.json` | 브라우저 쿠키별 원본 또는 초안·버전·source |
| PUT | `/api/studio/workflows/operations/PF05.json` | `{"expectedVersion":0,"workflow":{...}}` 형태의 초안 저장/낙관적 잠금·409 충돌 |
| GET | `/api/studio/workflows/operations/PF05.json/versions` | 브라우저별 버전 목록, 최근 최대 30개 |
| GET | `/api/studio/workflows/operations/PF05.json/versions/1` | 이전 버전 조회 |
| POST | `/rest/owner/setup` | Studio는 HTTP **405**, owner 생성 불가 |

- `/procure-workflows/operations/PF05.json` 같은 정적 원본 JSON도 이미지에 포함된다.
- 저장 대상은 **익명 `studio_sid` HttpOnly 쿠키로 식별되는 독립 SQLite**다. 서버는 저장 시 `active=false`를 강제한다.
- 화면의 'DB 연결됨'은 **Studio SQLite**가 연결됐다는 뜻이지 공식 n8n PostgreSQL, 워크플로 실행 엔진 연결을 의미하지 않는다.
- `/rest/settings`는 공식 n8n 설정 API가 아니다. 알 수 없는 GET 경로가 SPA의 `index.html`로 응답할 수 있다.
- 브라우저에서 JSON을 수정/저장해도 실제 G2B/Worker 실행이나 투찰은 일어나지 않는다.

## 5. Railway 배포 이력 (2026-10-30 KST 기준)

| 항목 | 확인한 값 |
|---|---|
| Railway 프로젝트/환경 | `thriving-education` / `production` |
| **기존** 서비스 | `procureflow-n8n-native-canvas` |
| 서비스 ID | `120dd399-6fc9-45a5-89f6-4818bdcd232d` |
| 소스 브랜치 | `feature/procureflow-shared-studio-editor-20261030` |
| **현재 운영에 핀된 ProcureFlow commit** | `33bce35353c8858bafb99128dd9206a6f62691df` |
| **공용 Studio commit** | `18e2ce915265a5a2351383942c6f9312d802513f` |
| 빌드 경로 | `n8n/Dockerfile.shared-studio-editor` |
| Runtime/health | Python `studio_server.py`, `PORT=3000`, `GET /health` |
| 배포 ID·확인 당시 상태 | `be0ad9c2-3457-4d58-828e-f08fb94d55f7` · **SUCCESS** |
| 초안 볼륨 | `procureflow-shared-studio-drafts`, `/data`, **512MB**, SQLite `/data/studio.sqlite3` |
| 공개 주소 | https://procureflow-n8n-native-canvas-production.up.railway.app |

**중요:** Railway Studio 소스는 당시 `33bce353...` 커밋에 **핀 고정**되었다. 이 브랜치에 문서나 테스트 커밋을 추가해도 운영 컨테이너에 자동 반영된다고 가정하지 않는다. 실제 코드 배포는 기존 서비스의 핀 업데이트·롤백 준비·실제 UI 검증을 거쳐야 한다.

### 이번 변경에서 유지한 기존 운영 서비스

- `n8n` Main: 서비스 ID `22eae389-025e-4ff1-bc56-1dff039ed6f9`, 기존 커밋 `b4dad318f2b2604d5032d1def5083aa8d3999e02`.
- `procureflow-n8n-worker`: ID `86849fe0-0f82-4d6e-98ef-4b401a5592c2`, 동일 커밋.
- 기존 `procureflow-n8n-editor-gateway`와 운영 PostgreSQL/Redis 및 계정·자격증명은 변경하지 않았다.
- 기존 n8n 게이트웨이 https://procureflow-n8n-editor-gateway-production.up.railway.app 에서는 이전 실제 검증 시 `Set up owner account`가 나타났다. **Studio 신규 화면의 로그인 부재는 이 장애를 해결한 것이 아니다.**

### 이전 캔버스로 롤백할 경우

- 기존 캔버스 소스 브랜치: `feat/n8n-native-editable-procurement-20261028`.
- 기존 Dockerfile: `n8n/native-editor/Dockerfile.gateway`.
- 기존 성공 배포: `ecf73e81-0f72-4994-960a-1469929938cf`.
- 해당 **캔버스 서비스 하나의 소스·Dockerfile 설정만** 복원한다. Main/Worker/Postgres/Redis나 투자 서비스는 건드리지 않는다.
- 신설 Studio 초안 볼륨 `/data`는 데이터를 보존할 수 있도록 **삭제하지 않는다**. 필요하면 백업 후 별도 처리한다.

## 6. 실제 검증 증거 (PASS와 미검증 분리)

| 항목 | 상태 | 증빙 |
|---|---|---|
| 같은 공용 Studio 소스 핀·빌드 성공 | **PASS** | [GitHub Actions #40899559884](https://github.com/lyonbegin/procureflow/actions/runs/40899559884) |
| 26개 원본 n8n JSON 제공 / 43개 Business Operation 그래프 | **PASS (격리 CI)** | 같은 CI |
| 테스트 서버 초안 PUT→재조회→버전 이력 / `active=false` 강제 | **PASS (격리 CI)** | 같은 CI; **운영 화면 실제 저장 검증과 다름** |
| 별도 Studio 실행 API 차단 및 owner setup 없음 | **PASS (CI)** | 같은 CI |
| 기존 캔버스 서비스 Studio 배포 | **SUCCESS** | Railway `be0ad9c2-3457-4d58-828e-f08fb94d55f7` |
| 실제 브라우저 PF05, 메뉴 26개, 35 노드/43 연결, H01 속성 패널 | **PASS** | [브라우저 검증 기록](https://agent.tinyfish.ai/runs/421d3d4f-4321-4c51-b6ed-955fad16fd71) |
| 새 Studio URL에서 로그인/owner setup 화면 없음 | **PASS** | 같은 브라우저 검증 |
| **실제 Chrome 빈 배경 왼쪽 드래그 Pan** | **PASS (좌표 측정)** | [GitHub Actions #40901817170](https://github.com/lyonbegin/procureflow/actions/runs/40901817170) |
| 운영 Studio 저장→새로고침→다시 읽기 | **미검증** | CI에서만 격리 DB에 쓰기 검증 |
| 운영 공식 n8n PostgreSQL에 26개 반영·실행 | **미완료/미검증** | 별도 과제 |
| 실제 입찰 데이터 10년 전수/104개 업무 기능 완료 | **미완료/미검증** | 최종 기획서 수용 기준 별도 |

**Pan 테스트의 수치 증빙:** 실제 Chrome에서 빈 캔버스에 왼쪽 버튼 누름 → 화면 기준 **(+140,+75)px** 이동 → 버튼 뗌. 계산 대상은 래퍼인 `.vue-flow__viewport`가 아니라 실질적으로 이동하는 **`.vue-flow__transformationpane`**다.

- BEFORE `matrix(0.2, 0, 0, 0.2, -368.3, 284.3)`
- AFTER `matrix(0.2, 0, 0, 0.2, -228.3, 359.3)`
- 관측 이동 **Δx=+140, Δy=+75px**, scale `0.2` 유지, H01 노드의 논리 위치 `translate(1760px, 330px)` 유지, 35개 노드 그대로, JavaScript 오류 0.
- 처음 테스트 [#40901571149](https://github.com/lyonbegin/procureflow/actions/runs/40901571149)는 **잘못된 DOM 래퍼 변환값**을 읽어 FAIL. 실제 이동 요소를 측정하도록 수정한 [#40901817170](https://github.com/lyonbegin/procureflow/actions/runs/40901817170)에서 PASS. 최초 실패 기록도 보존한다.

## 7. 개발 재현·수정·배포 절차

1. **요구사항 확인:** [마스터 기획서](FINAL_PROJECT_MASTER_PLAN_2026-10-28.md), 이 문서, PR #24 및 CI 기록을 확인한다. 104개 기능 완료 여부와 UI 완료 여부를 분리한다.
2. **공용 UI 수정:** `shared-n8n-studio`에서 `App.vue`, `procurement-adapter.js`, `node-catalog.js`, `studio_server.py`를 변경하고 기존 투자 13개 워크플로 기능의 회귀 테스트를 수행한다.
3. **업무 데이터 수정:** `procureflow`의 원본 PF/S JSON, manifest, graph compiler/augmenter를 수정한다. 별도 Vue/DAG 구현을 추가하지 않는다.
4. **공용 버전 고정:** 검증된 SHA를 `n8n/Dockerfile.shared-studio-editor`의 `SHARED_STUDIO_COMMIT`에 갱신한다. `main` 또는 움직이는 브랜치를 그대로 빌드하면 재현성이 무너진다.
5. **격리 검증:** [Studio CI](../.github/workflows/procureflow-shared-studio.yml)에서 26/43, 초안 버전·실행 차단을 확인하고 [Chrome CI](../.github/workflows/procureflow-shared-studio-live-pan.yml)에서 실제 좌측 드래그 Pan을 측정한다.
6. **운영 반영:** 새 Railway 프로젝트/신규 공식 n8n 서버를 만들지 말고 **기존 캔버스 서비스 하나**의 pinned commit만 갱신한다. 현재 초안 볼륨·롤백 대상을 먼저 확인한다.
7. **수용 검사:** PF00/PF05/S01 표시, 노드 선택/설정, 실제 빈 배경 Pan, 서버 저장/재진입, 로깅, 실행 비활성, 오염/보안 여부를 각기 증빙하고 PR에 기록한다.

### 선택적 로컬 재현 (운영 재배포 명령 아님)

```bash
# ProcureFlow 저장소 루트에서
docker build -f n8n/Dockerfile.shared-studio-editor -t pf-shared-studio-local .
docker run --rm -p 127.0.0.1:3031:3000 \
  -v pf-shared-studio-dev-drafts:/data pf-shared-studio-local

# 다른 터미널: 이 API는 공용 Studio용이지 n8n 엔진 API가 아니다.
curl -fsS http://127.0.0.1:3031/api/studio/health
curl -fsS http://127.0.0.1:3031/api/studio/workflows/operations/PF05.json
```

## 8. 보안·데이터 위험

- Studio의 '로그인 없음'은 **공개 익명 초안 편집기**라는 뜻이다. 기업용 사용자/RBAC 권한이 구현됐다는 증거가 아니다. 실행 엔진·입찰 권한은 연결하지 않는다.
- `studio_sid` HttpOnly 쿠키는 브라우저/기기마다 별도다. 쿠키 소실 시 저장된 초안에 접근하지 못할 수 있다. 백업·복구·접근통제는 추가 설계가 필요하다.
- 원본 PF/S JSON은 정적 공개 파일이므로 **비밀 키, 로그인 토큰, 개인정보, 미공개 입찰 원본** 등을 포함하면 안 된다.
- Studio SQLite `/data/studio.sqlite3`는 운영 n8n Postgres와 다르다. 초안 볼륨을 지우면 저장 내역이 유실될 수 있다.
- 저장 시 `active=false`를 강제하고, 브라우저/Studio에서 G2B 수집, 실제 Job 등록, 투찰·전자서명 API를 직접 실행하지 않는다.
- 공용 어댑터가 원본 n8n 노드 정보를 보존하려 하지만, **26개 전체 복잡한 멀티포트·IF·CUSTOM 노드의 무손실 편집→JSON 왕복**까지는 검증되지 않았다.
- 운영 n8n 기존 owner/DB/자격증명 초기화, 암호화키 변경, 인증 우회, 외부 설정 경로 개방은 **금지**. 이 기능은 Studio가 운영 n8n을 대체한다는 착각을 만들지 않아야 한다.

## 9. 미완료 사항 및 다음 개발 우선순위

| 우선순위 | 항목 | 완료를 인정할 증거 |
|---|---|---|
| P0 | **최종 기획서의 공식 n8n 네이티브 UI·저장·실제 실행·노드별 상태 연동** | 동일 사용자 플로우에서 저장한 워크플로가 공식 n8n 엔진 실행 결과에 반영, 로그/입출력/상태와 일치 |
| P0 | 기존 공식 n8n owner 화면 문제 복구 | 기존 관리자 레코드·DB 백업 원본 대조 후 정식 편집기 로그인/권한 검증 |
| P0 | 104개 실제 업무 기능 완성 및 정확한 10자리 세부종목 기준 10년 개찰·낙찰 증빙 | 기능별 실제 입력·공식 원본·실행·출력·검증 통과, 부분 수집은 HOLD |
| P1 | 운영 Studio 초안 저장→새로고침→재진입 사용자 시험 | 별도 익명 브라우저로 본인의 수정·버전 복구 실증 |
| P1 | PF/S 26개 JSON round-trip 비교 | 각 노드/포트/연결/파라미터·순서/비활성 상태 diff, 변경 허용 범위 문서화 |
| P1 | 50종 팔레트 전체 편집/Undo/연결 검증 | 실제 Chrome 수용 검사 |
| P1 | S01~S10 공식 엔진 실제 실행 및 진행상황/디버깅 | 실제 실행 로그·노드별 상태·원본 입력/출력·실패 재현 |
| P1 | 공개 Studio 보안 강화·인증/감사·백업 | RBAC, 초안 보관/복구, 공개 JSON 내용 및 쿠키 위험 감사 |

**구현 완료 보고의 경계:** GitHub 파일 존재, CI PASS, Railway SUCCESS, 'Set up owner account'가 없는 화면, 26개 목록, 43개 그래프, Pan PASS는 각각 **해당 층위의 사실**일 뿐이다. 실제 업무/엔진 동작과 별도로 검증·보고한다.

## 10. 증빙 바로가기

- [공용 UI 소스 고정 버전](https://github.com/lyonbegin/shared-n8n-studio/tree/18e2ce915265a5a2351383942c6f9312d802513f)
- [조달청 통합 소스 PR #24](https://github.com/lyonbegin/procureflow/pull/24)
- [빌드·26/43·격리 SQLite 시험 PASS](https://github.com/lyonbegin/procureflow/actions/runs/40899559884)
- [실제 사용자 화면/노드 H01 검사](https://agent.tinyfish.ai/runs/421d3d4f-4321-4c51-b6ed-955fad16fd71)
- [실제 Chromium 빈 배경 드래그 수치 PASS](https://github.com/lyonbegin/procureflow/actions/runs/40901817170)
- [이전 공식 n8n Pan 패치 작업 PR #22](https://github.com/lyonbegin/procureflow/pull/22) — 이번 Studio와 별도
- [이전 통합 후보 이미지 작업 PR #23](https://github.com/lyonbegin/procureflow/pull/23) — Studio와 별도

---

**최종 기록:** 주식 자동화에서 실제 작동하던 **공용 Vue Flow Studio 소스 재사용 방식**을 조달청 **기존 캔버스 서비스**에 적용했다. 사용자 화면에서 PF05·26개 목록·35개 노드·43개 연결·노드 설정·로그인 부재 및 빈 배경 Pan 이동을 확인했다. **운영 n8n 엔진 실행·104개 실제 조달 업무 완료는 선언하지 않는다.**
