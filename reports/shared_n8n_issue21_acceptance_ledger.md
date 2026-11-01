# Issue #21 / Draft PR #22 — 격리 검증 증빙 원장

## 2026-11-01 KST — 10년 월별 G2B 페이지 재호출 중복 식별자 차단 (전체 완료 아님)

- **새로 확인한 결함:** 동일 월의 공식 API 조회를 `scan_month(..., pages_max=1)`로 두 번 나눠 실행하면 `seen_notice_keys`가 호출마다 초기화된다. 공식 `totalCount`가 501로 유지되어도 2페이지의 대상 세부 공고가 이전 1페이지와 동일하면 `ON CONFLICT`가 기존 기록을 갱신하고 `checked/matched`는 중복을 새 행으로 계산하여 월을 `completed`로 허위 인증할 수 있었다.
- **기능 브랜치 수정:** [재개 시 기존 공식 공고 식별자 조회/검증 `753abbac`](https://github.com/lyonbegin/procureflow/commit/753abbacc4bc9ed9af5771b29317979c00b81d14). 이미 저장된 `official_openapi_explicit_code`의 대상 8자리 월별 `(hist_notice_no,hist_notice_ord)`를 **읽기 전용**으로 조회하고 `matched` 커서와 고유 ID 개수를 대조한다. 불일치·DB 읽기 실패는 `blocked_unverified_persisted_history`로 차단하며 네트워크/월 상태 변경을 하지 않는다. 정상 재개 시 과거 식별자를 `seen_notice_keys`에 포함해 두 번째 호출의 중복을 차단한다. 완료된 월을 재조회하는 shortcut에도 기록 개수 검사를 적용한다.
- **격리 회귀:** [중복·손상 이력 시험 `e1dcebb`](https://github.com/lyonbegin/procureflow/commit/e1dcebbf02a21cb0df404de6f611bab1669a1acb), [기존 완료 상태 FakeDB 보정 `2fd02588`](https://github.com/lyonbegin/procureflow/commit/2fd02588043ead0ff77cb21bd8fde6b648647ae2). 대상 공고의 페이지 간 중복, 이전 기록 0건/중복 200건, 정상 501건 완료, 완료 상태의 기록 개수 불일치를 검증. **이전 페이지에서 대상 외 분류 공고의 ID는 DB에 보존하지 않으므로, 이 수정만으로 모든 분류의 교차 호출 중복 검출이 완료되었다고 주장하지 않는다.**
- **코드 SHA `2fd02588043ead0ff77cb21bd8fde6b648647ae2` G2B CI:** [#41294790541](https://github.com/lyonbegin/procureflow/actions/runs/41294790541) **SUCCESS**, [pytest job #124813247506](https://github.com/lyonbegin/procureflow/actions/runs/41294790541/job/124813247506) **503 passed / 3 warnings**. FakeHTTP/FakeDB만 사용하며 실제 G2B API·운영 DB·Worker·투찰 요청 0건.
- 같은 코드 SHA의 [오프라인 S01~S10 #41294790447](https://github.com/lyonbegin/procureflow/actions/runs/41294790447), [단일 공식 편집기 계약 #41294790432](https://github.com/lyonbegin/procureflow/actions/runs/41294790432), [50종/43블록 계약 #41294790590](https://github.com/lyonbegin/procureflow/actions/runs/41294790590) **SUCCESS**.
- [기존 운영 owner/readiness #41294790431](https://github.com/lyonbegin/procureflow/actions/runs/41294790431) **FAIL (기존 차단)**: `ownerSetupRequired=true`, `/setup=403`, `/rest/workflows=401`, `EDITOR_BLOCKED_UNCLAIMED_OWNER`. 계정/DB/키는 수정하지 않았다.
- [공식 후보 Docker + Chrome #41294790603](https://github.com/lyonbegin/procureflow/actions/runs/41294790603), [Pan 빌드 #41294790494](https://github.com/lyonbegin/procureflow/actions/runs/41294790494), [native S01~S10/PF #41294790455](https://github.com/lyonbegin/procureflow/actions/runs/41294790455), [PF15 #41294790610](https://github.com/lyonbegin/procureflow/actions/runs/41294790610), [Main/Worker 격리 #41294790439](https://github.com/lyonbegin/procureflow/actions/runs/41294790439)는 이 기록 작성 시 진행 중. **최종 상태 재확인 전 PASS 선판정 금지.**
- **필수 미완료:** 35종 실제 실행 어댑터, 43개 실업무 핸들러/엄격 payload, 정확 10자리 기준 공식 10년 개찰·낙찰 전수 및 Worker fencing, 디버깅 80개 전수, 운영 owner/DB/키 호환성 및 승인. Issue Open/PR Draft 유지. 운영 main/Railway 서비스·DB/자격증명/실제 투찰 불변.

## 2026-11-01 KST — 공식 G2B `items.item`와 오류 필드 혼합 응답 차단 (**전체 완료 아님**)

- **실제 결함:** 공식 API의 `body.items`가 `{"item":[],"error":"upstream unavailable"}` 또는 `{"item":[],"resultCode":"99"}`처럼 정상 `item` 키와 **알 수 없는 오류/메타데이터 키를 동시에 포함**하면, 기존 파서는 `item=[]`만 취하고 `totalCount=0` 월을 `completed`로 허위 인증할 수 있었다. 기존에는 `item` 자체가 없는 오류 래퍼만 차단했다.
- **기능 브랜치만 수정:** [fail-closed 파서 `f2eb786`](https://github.com/lyonbegin/procureflow/commit/f2eb7867974ccb0827472adfba7784e8a71934d9) — `body.items`의 알려진 `item` 이외 필드가 있으면 `g2b_api_items_wrapper_extra_fields`로 오류 처리. 기존 공식 빈 래퍼 `None`, `[]`, `{}`, `{"item":[]}`, `{"item":null}`는 유지.
- **신규 격리 회귀:** [테스트 `e478743`](https://github.com/lyonbegin/procureflow/commit/e4787439a12a3b9d288f713402a1c349db164400) — 오류/미확인 필드 5종 × `totalCount` 0/1 **10건 fail-closed**, 정상 래퍼 **3건 호환성**. FakeHTTP/FakeDB만 사용. 잘못된 응답은 `scan_month` 오류, 월별 history INSERT 0건, 자격증명/원문 오류 로그 유출 없음.
- **실제 동일 소스 SHA CI:** [G2B 104 API + Node Lab #41276392160](https://github.com/lyonbegin/procureflow/actions/runs/41276392160) **SUCCESS**, [job #124759321822](https://github.com/lyonbegin/procureflow/actions/runs/41276392160/job/124759321822) **361 passed / 3 warnings**. [S01~S10 오프라인 #41276392189](https://github.com/lyonbegin/procureflow/actions/runs/41276392189), [50종/43블록 #41276392158](https://github.com/lyonbegin/procureflow/actions/runs/41276392158), [단일 공식 편집기 계약 #41276392144](https://github.com/lyonbegin/procureflow/actions/runs/41276392144) **SUCCESS**.
- **기존 운영 owner/readiness #41276392143:** **FAIL**, 읽기 전용 실측 `ownerSetupRequired=true`, `/setup=403`, `/rest/workflows=401`, `EDITOR_BLOCKED_UNCLAIMED_OWNER`. 운영 계정·DB는 변경하지 않음.
- **장시간 격리 Docker/공식 Chrome/Pan/native 시나리오:** [공식 후보 #41276392201](https://github.com/lyonbegin/procureflow/actions/runs/41276392201), [Pan #41276392173](https://github.com/lyonbegin/procureflow/actions/runs/41276392173), [native #41276392142](https://github.com/lyonbegin/procureflow/actions/runs/41276392142), [PF15 #41276392186](https://github.com/lyonbegin/procureflow/actions/runs/41276392186), [Main/Worker 이미지 #41276392137](https://github.com/lyonbegin/procureflow/actions/runs/41276392137)는 **최종 확인 전 성공 판정 금지**.
- **남은 필수 수용검사:** 35종 미지원 실행 매핑, 43개 실업무 핸들러·엄격 JSON Schema, 정확한 10자리 세부품명 10년 실제 개찰/투찰/낙찰 원본 완전성, 별도 디버깅 80개 런타임 전수, 운영 owner/DB/키 호환성·명시적 배포 승인. 이번 테스트는 **격리 파서 회귀**이지 실제 공식 10년 전수 인증이 아니다.
- **불변:** 운영 `main`/Railway 서비스·DB/자격증명/실제 G2B API 호출·Worker dispatch·투찰 변경 없음. Issue #21 Open / PR #22 Draft·미병합.


## 2026-11-01 KST — 공식 월별 API의 비대상 분류 날짜 검증 강화 (전체 완료 아님)

- **발견한 결함:** 기존 `scan_month()`는 `totalCount`에 포함되는 비대상 8자리 분류 공고의 식별자는 검증했지만, `bidNtceDt` 날짜를 검사하기 전에 해당 행을 건너뛰었다. 따라서 다른 달 공고 또는 날짜가 없는 비대상 행이 `checked==totalCount`를 만족하면 월별 공고 발견을 허위 완료할 수 있었다.
- **기능 브랜치 수정:** [코드 `2ab22b5`](https://github.com/lyonbegin/procureflow/commit/2ab22b5b161919a29098737b2aa6e7a530a8d765) — **모든 공식 응답 행**의 공고번호·차수·발행일/시각·조회 월 범위를 확인한 뒤에만 분류 필터를 적용한다. 비대상 행은 검증된 `checked`에만 포함하고 실제 이력 테이블에 INSERT하지 않는다. 날짜 누락·잘못된 시각·다른 달은 해당 페이지 INSERT/완료 이전에 `blocked_unverified_response_scope`.
- **격리 회귀:** [신규 14건 `e1bf035`](https://github.com/lyonbegin/procureflow/commit/e1bf035518f7a292037d7aa21a53e79d4c3d7a05) — 비대상 공고의 누락·무효·월 외 날짜 11건 차단, 정상 날짜 3건은 `checked=1,matched=0` 확인. [기존 중복 테스트 fixture 보완 `52f1f12`](https://github.com/lyonbegin/procureflow/commit/52f1f129e51701b9290e104fb98841c49df2ced7).
- **실패 원인과 수정:** 첫 CI [#41265794015](https://github.com/lyonbegin/procureflow/actions/runs/41265794015)는 기존 비대상 중복 테스트에서 날짜가 빠져 `invalid_scope_rows=2`(무날짜 + 중복)인데 기존 기대값 1을 유지하여 **1 FAIL / 339 PASS**. 중복을 독립적으로 검사하도록 기존 fixture에 정상 날짜를 명시한 뒤 재검증.
- **수정 후 동일 코드 SHA `52f1f12` 실제 CI:** [G2B 104 API + Node Lab #41265847113](https://github.com/lyonbegin/procureflow/actions/runs/41265847113) **SUCCESS**, job [#124728368697](https://github.com/lyonbegin/procureflow/actions/runs/41265847113/job/124728368697) **340 passed / 3 warnings**. [오프라인 S01~S10 #41265847086](https://github.com/lyonbegin/procureflow/actions/runs/41265847086), [50종/43블록 #41265847103](https://github.com/lyonbegin/procureflow/actions/runs/41265847103), [단일 공식 편집기 계약 #41265847106](https://github.com/lyonbegin/procureflow/actions/runs/41265847106) **SUCCESS**.
- **기존 운영 owner/readiness [#41265847105](https://github.com/lyonbegin/procureflow/actions/runs/41265847105) FAIL:** 읽기 전용 응답 `ownerSetupRequired=true`, `/setup=403`, `/rest/workflows=401`, `EDITOR_BLOCKED_UNCLAIMED_OWNER`. 운영 DB/계정 변경 없이 차단 유지.
- 같은 SHA의 [공식 후보 Docker/Chrome #41265847118](https://github.com/lyonbegin/procureflow/actions/runs/41265847118), [Pan 빌드 #41265847095](https://github.com/lyonbegin/procureflow/actions/runs/41265847095), [native S01~S10 #41265847127](https://github.com/lyonbegin/procureflow/actions/runs/41265847127), [PF15 #41265847121](https://github.com/lyonbegin/procureflow/actions/runs/41265847121), [Main/Worker 이미지 #41265847084](https://github.com/lyonbegin/procureflow/actions/runs/41265847084)은 **개별 최종 확인 전 PASS 판정 금지**.
- **남은 필수 수용검사:** 35종 미지원 실행 어댑터, 43개 실업무 핸들러·엄격 payload, 정확한 10자리 세부종목 기준 10년 개찰·투찰·낙찰 공식 전수, 별도 디버깅 80개 런타임 전수, 운영 owner/DB/키 호환성·명시적 승인. 이번 340개는 **FakeHTTP/FakeDB 기반 회귀**, 실제 G2B/Worker/투찰 실행이 아니다.
- **불변:** 운영 `main`, Railway 운영 서비스·DB, 자격증명, 실제 G2B 호출·Worker dispatch·투찰 **변경 없음**. Issue #21 Open / PR #22 Draft·미병합. 전체 완료 통보 금지.


## 2026-11-01 KST — 8자리 공식 공고 발견의 비대상 분류 중복/무식별 응답 차단 (**전체 완료 아님**)

- **실제 결함:** 월별 `totalCount`는 대상 분류 외의 공식 API 행도 포함하지만 `scan_month()`는 기존에 대상 8자리 분류 행에 대해서만 `(bidNtceNo,bidNtceOrd)` 중복/식별자 유효성을 검사했다. 비대상 분류의 중복 행·식별자 누락이 포함된 페이지도 `checked==totalCount`가 되어 허위 `completed`로 인증될 수 있었다.
- **격리 기능 브랜치 코드:** [`382e048`](https://github.com/lyonbegin/procureflow/commit/382e048437a1c1ad9bafee5cbb93d761f3059fe6) — **모든 공식 API 행**에 대해 분류 대상 여부로 건너뛰기 전에 공고번호·차수의 유효성 및 호출 내 전체 페이지 간 중복을 검사한다. 비대상 행은 여전히 업무 history 테이블에 저장하지 않으며, 중복/무식별 행 발견 시 해당 페이지 INSERT 전에 `blocked_unverified_response_scope`로 차단한다.
- **격리 회귀:** [`dce1461`](https://github.com/lyonbegin/procureflow/commit/dce14610c4bba03d10c8b89bc5a634ab4baa7d1a), [`9dc309e`](https://github.com/lyonbegin/procureflow/commit/9dc309e61e804237eb2b1955603a7f8b824beb37). 비대상 분류 무식별자 6종, 대상/비대상 동일 공고 2종, 호출 내 서로 다른 페이지의 비대상 중복, 비대상끼리 중복, 서로 다른 정상 비대상 행의 `checked=2,matched=1` 보존 등 **11개 새 테스트**. FakeHTTP/FakeDB만 사용하며 실제 G2B API·운영 DB·Worker·투찰 접근 0건.
- **최종 코드 SHA `9dc309e` 실제 검증:** [G2B 104 API + Node Lab #41262558681](https://github.com/lyonbegin/procureflow/actions/runs/41262558681) **SUCCESS**, [job #124718617987](https://github.com/lyonbegin/procureflow/actions/runs/41262558681/job/124718617987) **326 passed / 3 warnings**. [S01~S10 오프라인 #41262558743](https://github.com/lyonbegin/procureflow/actions/runs/41262558743) **SUCCESS**. [50종/43블록 계약 #41262558685](https://github.com/lyonbegin/procureflow/actions/runs/41262558685) **SUCCESS**. 공식 Docker/Chrome/Pan/native 시나리오의 **같은 SHA 최종 결과는 별도 완료 확인 전까지 선판정하지 않음**.
- **기존 운영 owner/readiness:** [#41262558656](https://github.com/lyonbegin/procureflow/actions/runs/41262558656) **FAIL**, 기존 owner 미설정 문제를 운영 DB/계정 변경 없이 읽기 전용으로 확인.
- **한계:** 이 방어는 한 번의 `scan_month()` 호출 내 API 행/페이지 중복을 다룬다. **서로 다른 재개 호출 간** 비대상 분류 행 집합 동일성, 같은 `totalCount`에서 페이지 구성 변경, Worker 동시성은 여전히 별도 증빙이 필요하다. 공식 **10자리** 세부품명별 10년 개찰·낙찰 실제 원본 완전성을 인증하지 않는다.
- **전체 미완료:** 35종 실행 어댑터, 43개 실업무 핸들러·엄격 payload, 공식 10년 실데이터·Worker fencing, 별도 디버깅 80개 런타임 전수, 운영 owner/DB/키 호환성 및 승인. **Issue Open / PR Draft·미병합. 운영 main·Railway 운영 서비스/DB·자격증명·실제 투찰 변경 없음.**

## 2026-11-01 KST — 월별 G2B totalCount 재개 호출 간 스냅샷 보존 (전체 완료 아님)

- **원인:** 기존 `scan_month()`는 동일 함수 호출에서만 `totalCount` 변화 감지. 첫 500건을 `partial`로 저장하고 다음 호출에서 page 2를 읽으면, 공식 API 결과 총건수가 변경되어도 첫 호출의 원래 수치를 모르므로 일부 페이지가 빠진 상태를 `completed`로 잘못 판정할 수 있었다.
- **격리 기능 브랜치 코드:** [스키마 `f39212c`](https://github.com/lyonbegin/procureflow/commit/f39212c0259863294dabe60dd5eeffa9ac816b2c) — 월별 window에 nullable `expected_total bigint`를 추가하는 **향후 적용용 소스 DDL**. [수집기 `e45dca8`](https://github.com/lyonbegin/procureflow/commit/e45dca8a78cdb431e7e02fb02a80e53b43814aca), [보완 `dafb130`](https://github.com/lyonbegin/procureflow/commit/dafb13073fb9e0d1f55e8af3088b86860629d732) — 첫 검증 페이지의 공식 `totalCount`를 상태와 함께 저장, 재개 호출에서 일치하지 않으면 **해당 페이지 INSERT 전에** `blocked_unverified_response_scope`로 차단. 저장된 `partial/completed`에 유효한 snapshot이 없으면 네트워크·DB 쓰기 없이 fail-closed. 읽기 전용 월별 진단도 snapshot 없는 완료 상태를 인증하지 않음.
- **격리 회귀:** [`ed08711`](https://github.com/lyonbegin/procureflow/commit/ed08711eacce369c68002514a61b6f0efb2a68d0) 및 [후속 `0e2b9ca`](https://github.com/lyonbegin/procureflow/commit/0e2b9caa429ad1611f5a8617599c397804b2135f): 감소·증가 totalCount 3종, snapshot 누락·비정상 7종, 완료 row 불일치 5종, 월별 집계 음성/양성 1종. **FakeHTTP/FakeDB만 사용**. [CI 경로 갱신 `1312e05`](https://github.com/lyonbegin/procureflow/commit/1312e05a9e17ecd6bf63f8aeaab708af5b95d08b) — schema 파일 변경 시에도 회귀 CI 실행.
- **같은 최종 코드 HEAD 실제 [G2B 104 API + Node Lab #41253074272 SUCCESS](https://github.com/lyonbegin/procureflow/actions/runs/41253074272)**, job `124690445784`: **274 passed, 3 warnings**. [오프라인 S01~S10 #41253074255 SUCCESS](https://github.com/lyonbegin/procureflow/actions/runs/41253074255). Docker/공식 Chrome/Pan/50종/43블록/native 시나리오/PF15/Main·Worker/기존 owner 검사는 각각 결과 확인 전 최종 PASS 판정 보류.
- **운영 변경 없음:** DDL은 **기능 브랜치의 소스 변경일 뿐** 운영 DB에 실행하지 않았다. 기존 월별 snapshot이 없는 row는 사전 증빙·백업·승인 없이 임의 초기화하거나 완료로 승격하지 않는다. `totalCount` 일치만으로 **페이지 사이 실제 공고 집합 동일성까지 증명되는 것은 아니며**, 재개 호출 간 공고 ID 집합/스냅샷 일관성 및 동시 Worker fencing은 추가 검증 필요.
- **전체 필수 미완료:** 35종 실행 어댑터, 43개 실제 업무 핸들러, 공식 10자리 세부품명 10년 개찰·낙찰 전수, 디버깅 80개 런타임 전수, 기존 owner/운영 승인. **Issue Open / PR Draft·미병합. 운영 main/Railway 운영 서비스·DB/자격증명/실제 투찰 변경 없음.**


## 2026-11-01 KST — 공식 월별 API 페이지 간 totalCount 변동·중복 차단 (전체 완료 아님)

- **실제 기능 브랜치 패치:** [`84ddfcd`](https://github.com/lyonbegin/procureflow/commit/84ddfcd8dcc9a525670c42cc50a1797a2bf3ecfe) — `scan_month()`가 한 번의 월별 수집에서 1페이지의 `totalCount`와 다음 페이지의 값이 달라져도 결과를 합산하여 월 전체 완료로 오인할 수 있는 경로를 차단. 앞 페이지에서 이미 본 `(bidNtceNo,bidNtceOrd)`가 다음 페이지에 재등장할 경우에도 두 번째 페이지 INSERT 이전에 `blocked_unverified_response_scope`로 보류. 기존에 확인된 첫 페이지는 감사 가능한 `partial`로 보존. **이 검사는 동일 `scan_month` 호출의 연속 페이지에만 적용**되며 재개 호출 간 스냅샷 일치성은 별도 과제.
- **격리 회귀:** [`bab22d0`](https://github.com/lyonbegin/procureflow/commit/bab22d0b45999ec64e4158ecf847ea2f44147c83) — 공식 페이지 1은 500건, 페이지 2는 1건인 합성 데이터로 **7개** 양성/음성 시험: `totalCount` 감소·증가 3종, 두 번째 페이지의 중복 공고(동일/금액 상충/날짜 상충) 3종, 안정적 총건수와 고유 공고의 정상 완료 1종. `FakeHTTP/FakeDB`만 사용, 실 G2B API·운영 DB·Worker·투찰 접근 0건.
- **동일 HEAD [G2B 104 API + Node Lab #41237495880 SUCCESS](https://github.com/lyonbegin/procureflow/actions/runs/41237495880):** 실제 GitHub Actions job `124644232906` 로그 **242 passed, 3 warnings**. [오프라인 S01~S10 #41237495808 SUCCESS](https://github.com/lyonbegin/procureflow/actions/runs/41237495808), [단일 편집기 #41237495802 SUCCESS](https://github.com/lyonbegin/procureflow/actions/runs/41237495802), [50종/43블록 #41237495943 SUCCESS](https://github.com/lyonbegin/procureflow/actions/runs/41237495943).
- [기존 운영 owner/readiness #41237495838 FAIL](https://github.com/lyonbegin/procureflow/actions/runs/41237495838): 읽기 전용 검증만 수행, 운영 owner/DB/자격증명 변경 없음. 동일 SHA의 [Pan/Chrome #41237495804](https://github.com/lyonbegin/procureflow/actions/runs/41237495804), [후보 Docker/Chrome #41237495794](https://github.com/lyonbegin/procureflow/actions/runs/41237495794), [native S01~S10 #41237495806](https://github.com/lyonbegin/procureflow/actions/runs/41237495806), [PF15 #41237495833](https://github.com/lyonbegin/procureflow/actions/runs/41237495833), [Main/Worker 격리 #41237495837](https://github.com/lyonbegin/procureflow/actions/runs/41237495837)은 이 기록 시점 최종 PASS 선판정하지 않음.
- **미완료:** 35종 실행 매핑, 43개 실업무 핸들러, 정확한 10자리 세부품명 기준 공식 10년 개찰·낙찰 실데이터, 80개 디버깅 런타임 전수, 재개 호출 간 페이지 스냅샷 무결성, 기존 n8n owner/DB 복구·운영 승인. **Issue Open / PR Draft·미병합. 운영 main/Railway 운영 서비스·DB/자격증명/실제 Worker dispatch·투찰 변경 없음. 전체 완료 선언 금지.**

## 2026-11-01 KST — 공식 월별 발견 페이지의 중복 공고번호·차수 차단 (전체 완료 아님)

- **코드 수정:** [1fcb4d8](https://github.com/lyonbegin/procureflow/commit/1fcb4d844485498f9e28f8f73d1c3adc8da96074) — `scan_month()`가 한 공식 API 페이지에 같은 `(bidNtceNo,bidNtceOrd)`가 2회 등장해도 `ON CONFLICT`로 덮어쓰고 `totalCount`에 포함된 두 행을 정상 월별 발견 완료로 오인할 수 있던 경로 차단. 페이지 내부 공고 식별자 중복은 `blocked_unverified_response_scope`로 처리하고, 그 페이지의 **history INSERT를 시작하기 전에** 전체를 보류한다. 서로 다른 차수는 별도 공식 식별자로 계속 허용한다.
- **격리 회귀:** [d1c099e](https://github.com/lyonbegin/procureflow/commit/d1c099e3c5e95a109c6ce8cb1aa8f2185205fdf0) — 완전 동일 중복, 금액이 다른 중복, 날짜가 다른 중복 3종을 `FakeHTTP/FakeDB`로 검사하고, 서로 다른 차수의 정상 2건은 수용. 실 G2B API·운영 DB·투찰 호출 없음.
- **동일 코드 SHA G2B 104 API + Node Lab [#41230410719 SUCCESS](https://github.com/lyonbegin/procureflow/actions/runs/41230410719):** 실제 pytest job `124623263625` **235 passed, 3 warnings**. [공식 단일 편집기 #41230410675 SUCCESS](https://github.com/lyonbegin/procureflow/actions/runs/41230410675), [50종/43블록 #41230410680 SUCCESS](https://github.com/lyonbegin/procureflow/actions/runs/41230410680).
- **기존 운영 owner/readiness [#41230410811 FAIL](https://github.com/lyonbegin/procureflow/actions/runs/41230410811)** (읽기 전용 진단): `ownerSetupRequired=true`, `/setup=403`, `/rest/workflows=401`, `EDITOR_BLOCKED_UNCLAIMED_OWNER`. [마스킹된 verdict 아티팩트](https://github.com/lyonbegin/procureflow/actions/runs/41230410811/artifacts/13053895319). 기존 계정·DB 변경 없음.
- 같은 SHA의 [Pan 공식 Chrome #41230410709](https://github.com/lyonbegin/procureflow/actions/runs/41230410709), [후보 Docker/Chrome #41230410807](https://github.com/lyonbegin/procureflow/actions/runs/41230410807), [native S01~S10 #41230410691](https://github.com/lyonbegin/procureflow/actions/runs/41230410691), [오프라인 S01~S10 #41230410871](https://github.com/lyonbegin/procureflow/actions/runs/41230410871), [PF15 #41230410778](https://github.com/lyonbegin/procureflow/actions/runs/41230410778), [Main/Worker 격리 #41230410679](https://github.com/lyonbegin/procureflow/actions/runs/41230410679)는 기록 시점 **최종 완료 확인 전**으로 PASS 선판정 금지.
- **범위 한계:** 이 검사는 **단일 공식 API 페이지 내부의 중복**에 대한 방어다. 페이지 간·월 간 중복과 실제 공식 10자리 세부품명 개찰/낙찰 전수는 별도 검증 필요. 35종 실행 어댑터, 43개 실제 업무 핸들러, 디버깅 80개 전수, 운영 owner 복구·운영 승인 미완료. **Issue Open, PR Draft·미병합 유지. 운영 main/Railway 운영 서비스·DB/자격증명/Worker dispatch/실제 투찰 변경 없음.**

## 2026-11-01 KST — 손상된 부분 월 커서·페이지 수 요청의 무변경 차단 (전체 완료 아님)

- [코드 패치 `8c7bd96`](https://github.com/lyonbegin/procureflow/commit/8c7bd960c921c4928f4d774a7704aa035136647f): `scan_month()`의 **부분 월** 저장값이 `checked/matched/page_cursor` 수학에 맞지 않을 때 `_service_key()` 호출과 `_write_month()` 수행 **전에** `blocked_invalid_page_cursor`를 반환하도록 변경. 손상된 원본 DB 행을 덮어쓰지 않고 읽기 전용으로 보존. `pages_max=True/False/float/string/None/0/음수`를 `int()`로 묵시 변환하거나 1로 보정하여 공식 API 요청을 시작하던 경로도 `blocked_invalid_page_limit`로 차단.
- [격리 회귀 `ad9e633`](https://github.com/lyonbegin/procureflow/commit/ad9e6330edec8d135b9fdcc9d3d72b004254b3db): 손상된 부분 월 3종 × API 키 유무 2종, 잘못된 페이지 수 10종에 대해 **HTTP 0건 / API 키 조회 0건 / DB 쓰기 0건**을 FakeDB/FakeHTTP로 검사. 기존 구형 DB-write 기대값도 무변경 정책으로 보정.
- [**동일 HEAD G2B 104 API + Node Lab #41226204956 SUCCESS**](https://github.com/lyonbegin/procureflow/actions/runs/41226204956): job `124610758521`, 실제 pytest 로그 **231 passed, 3 warnings**. [50종/43블록 계약 #41226204979](https://github.com/lyonbegin/procureflow/actions/runs/41226204979) 및 [오프라인 S01~S10 #41226205050](https://github.com/lyonbegin/procureflow/actions/runs/41226205050)도 **SUCCESS**.
- [기존 운영 owner/readiness #41226205216 **FAIL**](https://github.com/lyonbegin/procureflow/actions/runs/41226205216): `ownerSetupRequired=true`, `/setup=403`, `/rest/workflows=401`, `EDITOR_BLOCKED_UNCLAIMED_OWNER`. 기존 운영 계정/DB는 변경하지 않음.
- 동일 SHA의 [공식 Pan/Chrome #41226205134](https://github.com/lyonbegin/procureflow/actions/runs/41226205134), [공식 후보 Docker/Chrome #41226205048](https://github.com/lyonbegin/procureflow/actions/runs/41226205048), [native S01~S10 #41226204898](https://github.com/lyonbegin/procureflow/actions/runs/41226204898), [PF15 #41226204927](https://github.com/lyonbegin/procureflow/actions/runs/41226204927), [Main/Worker 격리 #41226205039](https://github.com/lyonbegin/procureflow/actions/runs/41226205039), [단일 편집기 #41226205147](https://github.com/lyonbegin/procureflow/actions/runs/41226205147)은 이 기록 시점 **진행 중**, 최종 결과 확인 전 PASS 판정하지 않음.

**남은 필수 수용:** 35종 실행 어댑터, 43개 실업무 핸들러·엄격 업무 스키마/Worker, 정확한 10자리 세부품명 기준 공식 10년 실제 개찰·낙찰 전수, 디버깅 80개 런타임 전수, 기존 n8n owner 복구 및 운영 전환 승인. **Issue Open / PR Draft·미병합 유지**. 운영 `main`/Railway 운영 서비스·DB/자격증명/실제 Worker dispatch·투찰 **변경 없음**.

> 범위: `feature/shared-n8n-pan-integration`만 해당. **전체 필수 수용검사는 미완료**이며 이 문서는 배포 승인서가 아닙니다. 운영 `main`, Railway 운영 서비스·DB, 자격증명, 실제 투찰을 변경하지 않습니다.


## 2026-10-31 KST — 121개 월별 공식 공고 진행률 커서 무결성 강화 (**전체 완료 아님**)

- [읽기 전용 진행률 검증 패치 `16d2e8c`](https://github.com/lyonbegin/procureflow/commit/16d2e8c2a55c9cacb3637f205bbd7716615b2e5d): `summarize_month_cursor()`가 완료 상태의 음수·불리언·소수·잘못된 문자열 `checked/matched/page_cursor`를 `int()`로 묵시 변환하거나 0으로 덮어 **121/121 완료로 잘못 표시**할 수 있던 경로 차단. 완료 월은 페이지 수와 커서의 일치성(0건→page 1, 1~500건→page 2 등), `matched<=checked` 검증을 통과해야 완료 건수에 산입. 부분 월은 500건 단위의 저장된 전체 페이지·다음 커서 일치성을 검사. 응답에 `cursor_valid`, `invalid_cursor_rows` 진단 추가.
- [공식 페이지 판정 타입 패치 `342ec62`](https://github.com/lyonbegin/procureflow/commit/342ec6225c94cbbca9e02196f1dc0aaac7d277e4): `_page_verdict()`가 `True`/ `False`를 정수로 인정하거나 0·음수 페이지 크기를 허용하지 않도록 fail-closed 처리.
- [39개 격리 양성·음성 pytest 케이스 `340d6cf`](https://github.com/lyonbegin/procureflow/commit/340d6cf265d0a6b803afd113992631f7cae1b2bb): 공식 페이지 bool/크기 6, 완료 월 손상 18, 정상·손상 완료 커서 8, 부분 커서 7. **FakeDB·읽기 전용 순수 함수만 사용**; 운영 DB·공식 API·실제 투찰 호출 없음.
- [**G2B 104 API + Node Lab CI #41207212596 SUCCESS**](https://github.com/lyonbegin/procureflow/actions/runs/41207212596): job `124554638608` 실제 로그 **155 passed, 3 warnings**. [오프라인 S01~S10 #41207212589 SUCCESS](https://github.com/lyonbegin/procureflow/actions/runs/41207212589), [단일 공식 편집기 #41207212642 SUCCESS](https://github.com/lyonbegin/procureflow/actions/runs/41207212642).
- [기존 운영 owner/readiness #41207212607 FAIL](https://github.com/lyonbegin/procureflow/actions/runs/41207212607): **읽기 전용 실측** `gatewayHealthStatus=200`, `settingsStatus=200`, `ownerSetupRequired=true`, `/setup=403`, `/rest/workflows=401`, `ready=false`, `EDITOR_BLOCKED_UNCLAIMED_OWNER`. 운영 관리자 생성·DB 변경 없이 원래 장애를 보존.
- 같은 HEAD `340d6cf`의 [공식 Pan/Chrome #41207212658](https://github.com/lyonbegin/procureflow/actions/runs/41207212658), [공식 후보 Docker/Chrome #41207212616](https://github.com/lyonbegin/procureflow/actions/runs/41207212616), [native S01~S10 #41207212643](https://github.com/lyonbegin/procureflow/actions/runs/41207212643), [50종/43블록 #41207212665](https://github.com/lyonbegin/procureflow/actions/runs/41207212665), [Main/Worker 격리 이미지 #41207212622](https://github.com/lyonbegin/procureflow/actions/runs/41207212622), [PF15 #41207212599](https://github.com/lyonbegin/procureflow/actions/runs/41207212599)은 이 기록 시점 **일부 실행 중/대기**. 이전 SHA의 PASS를 최신 SHA의 PASS로 대체하지 않음.

**미완료:** 35종 실행 매핑, 43개 실제 업무 핸들러 및 엄격 payload, 정확한 10년 개찰·투찰·낙찰 공식 실데이터 전수, 별도 디버깅 80개 런타임, 기존 owner/DB/키 호환성·운영 승인. **Issue OPEN / PR Draft·미병합**. 운영 `main`, Railway 운영 서비스·DB, 자격증명, 실제 Worker dispatch/투찰 미변경.

## 2026-10-31 KST — 공식 월별 G2B 응답의 totalCount/items 엄격 검증 (전체 완료 아님)

- [응답 totalCount 타입 강제 `5e7d7c2`](https://github.com/lyonbegin/procureflow/commit/5e7d7c22024f9d8992d52ae3e5e0e56561268353): 공식 응답의 `totalCount`가 float/bool/list/object/소수·지수 문자열이면 `int(...)` 묵시적 변환을 금지하고 오류로 차단. `int(1.5)==1` 또는 `int(True)==1`로 **월 완료 오판** 가능했던 경로를 제거. 정상 정수/숫자 문자열만 허용.
- [totalCount 격리 음성·양성 테스트 `dbf1981`](https://github.com/lyonbegin/procureflow/commit/dbf1981e015b09ef9b3d98aa616b933d3bc4a204): 잘못된 값 13개, 정상 값 5개를 FakeHTTP/FakeDB로 검사.
- [명시적 scalar items 거부 `5d6cc04`](https://github.com/lyonbegin/procureflow/commit/5d6cc0497221f75a5e0fab4bbaf1f834e7307575): 공식 `items=0/False/""` 또는 `items.item=0/False/""`가 `or []` 때문에 빈 목록으로 바뀌어 **가짜 0건 완료**가 되던 경로 차단. 원본에 목록이 없거나 null인 정상 0건은 허용.
- [items 격리 음성·양성 테스트 `5932c90`](https://github.com/lyonbegin/procureflow/commit/5932c904e00d20b8c69a933ce23265d5ef671b12): 잘못된 envelope 8개, 정상 0건 envelope 5개. 공식 API·운영 DB·실제 Worker/투찰 접근 없이 테스트.
- [**새 HEAD G2B 104 API + Node Lab CI #41193445900**](https://github.com/lyonbegin/procureflow/actions/runs/41193445900): 실행 큐 진입 확인, **아직 최종 결과 미확정**. 같은 SHA의 [공식 Chrome Pan #41193445885](https://github.com/lyonbegin/procureflow/actions/runs/41193445885), [후보 Docker/Chrome #41193445910](https://github.com/lyonbegin/procureflow/actions/runs/41193445910), [50종/43블록 #41193445895](https://github.com/lyonbegin/procureflow/actions/runs/41193445895), [native S01~S10 #41193446030](https://github.com/lyonbegin/procureflow/actions/runs/41193446030)도 실행 대기/판정 전. 이전 SHA의 PASS를 최신 SHA의 PASS로 혼동하지 않음.

**미완료:** 35종 실행 매핑, 43개 실제 업무 핸들러, 정확한 10년 공식 개찰·낙찰 실데이터, 80개 디버깅 런타임 전수, 운영 owner/DB/키 호환성·승인. Issue OPEN, PR Draft·미병합, 운영 main/Railway DB/credentials/실제 투찰 미변경.

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



## 2026-10-29 — Railway 내부 read-only 포트 pin 회귀

- [기능 브랜치 보안 패치](https://github.com/lyonbegin/procureflow/commit/3b46c74f57e594d4b394af58550f209a363fa8c9): 기존 정확한 `PROCUREFLOW_APPROVED_INTERNAL_API_HOST` 검증에 **TCP 포트 검증**을 추가. 내부 서비스의 기본 포트만 별도 설정 없이 허용하며, 비표준 포트를 쓰려면 `PROCUREFLOW_APPROVED_INTERNAL_API_PORT`에 숫자 포트를 명시적으로 고정해야 합니다. 이 환경변수는 기능 브랜치 후보 코드의 읽기 전용 검사에만 해당하며 운영 환경은 수정하지 않았습니다.
- [회귀 테스트](https://github.com/lyonbegin/procureflow/commit/d80dfa0df8def19bce34289ff8ab7eab6ab42e6a): 호스트 일치·포트 불일치, 포트 미승인, 잘못된 포트 설정, 시험 모드 내부 접근 차단을 검증합니다. [동일 SHA CI](https://github.com/lyonbegin/procureflow/actions/runs/40828211477)는 별도 최종 확인이 필요하며 **이 기록 시점 PASS로 선판정하지 않습니다**.
- 35종 실행 매핑, 43개 실제 업무 핸들러, 공식 10년 원본 데이터, 80개 디버깅 전수 및 운영 호환성·승인은 계속 미완료입니다. Issue Open/PR Draft, 운영 main·Railway DB·자격증명·실제 투찰 불변.


## 2026-10-29 — 기존 공용 n8n에만 통합하도록 배포 방향 수정

**사용자 지시: 새 독립 n8n 설치·추가 계정·새 SQLite를 만들지 않는다.**
이미 존재하는 Railway `n8n` Main(서비스 `22eae389-025e-4ff1-bc56-1dff039ed6f9`), `procureflow-n8n-worker`(`86849fe0-0f82-4d6e-98ef-4b401a5592c2`) 및 공용 편집기 게이트웨이(`e3dcc972-2747-43a0-84c2-5280536f5671`)를 재사용한다. 이 Main·Worker는 모두 `main` + `n8n/Dockerfile`을 공유하고 운영 PostgreSQL·Redis·암호화 키를 사용한다.

- **잘못된 배포 경위**: 2026-10-29 `procureflow-shared-n8n-branch-preview`라는 별도 서비스를 새 SQLite와 함께 생성한 결과, n8n `Set up owner account` 최초 설치 화면이 표시되었다. 원인은 Pan 패치 부재가 아니라 **기존 공용 n8n 사용자 DB를 재사용하지 않은 것**이다.
- **즉시 처리**: 잘못 만든 게이트웨이의 공개 Railway 도메인을 제거하고, 독립 n8n 본체 서비스를 삭제했다. 해당 미리보기 SQLite 볼륨은 데이터 파괴를 피하려고 **분리·보존**했다. 별도 게이트웨이는 외부 도메인이 해제된 상태로 남아 있으며, 이를 공용 접속점으로 사용하면 안 된다.
- **공용 소스 통합**: 기능 브랜치의 `n8n/Dockerfile`을 기존 Main/Worker에서 함께 사용하는 **공식 upstream n8n 2.44.6 + 고정 공유 Pan 패치** 이미지로 수정했다. `N8N_CUSTOM_EXTENSIONS`로 43개 읽기 전용 게이트 노드를 포함하되, 업무 실행은 별도 승인 없이는 차단한다. 기존 `n8n start` CMD, Worker `n8n worker --concurrency=3` Railway override, 운영 워크플로 import 경로를 보존한다. **별도 owner/계정/bootstrap/SQLite/추가 로그인은 포함하지 않는다.**
- **기존 공용 n8n 미해결 문제**: 공개된 기존 게이트웨이의 읽기 전용 `/rest/settings`가 `userManagement.showSetupOnFirstLoad=true`를 반환하는 것을 관찰했다. 즉 **기존 공용 n8n도 관리자 초기화가 미완료인 상태**로 보인다. 보안을 위해 기존 게이트웨이의 공개 owner setup 경로 차단을 유지한다. UI를 정상적으로 쓰기 위한 신뢰된 최초 소유자 설정 또는 합법적인 기존 관리자 확인은 아직 미완료다.
- **검증 절차**: [기존 Main/Worker 통합 이미지 CI](https://github.com/lyonbegin/procureflow/actions/runs/40884401454)는 **새 서버를 띄우지 않고** 원본 이미지를 빌드·버전·확장 로드·CMD를 점검한다. 정적 구성 검사는 PASS, 실제 소스 이미지 빌드 최종 결과는 별도 CI 상태 확인 필요.
- **중요한 경계**: 변경은 `feature/shared-n8n-pan-integration`에만 존재한다. 기존 `main`, 운영 Main/Worker 이미지, 운영 PostgreSQL, 암호화 키, 워크플로, 실제 입찰은 바꾸지 않았다. 운영으로 적용하기 전 **복원 가능한 운영 DB 백업·현재 owner/credential 호환성·기존 Worker 일치·롤백**을 검증해야 한다. 새 독립 n8n 서비스를 이용한 우회 테스트/배포는 금지한다.


## 2026-10-29 14:08 UTC — 기존 공용 Railway n8n Main + Worker 실제 배포

사용자의 명시적인 배포 요청을 받아, **기존** Railway 서비스만 전환했다. 새 n8n 서비스·새 DB·사용자 계정·추가 비밀번호를 만들지 않았다.

| 대상 | Railway 배포 | 커밋 | 검증 |
|---|---|---|---|
| 기존 `procureflow-n8n-worker` | `9ff8d763-5baa-4a4c-a988-55bb26b8e856` | `b4dad318f2b2604d5032d1def5083aa8d3999e02` | `SUCCESS`, 실행 로그 `n8n worker is now ready`, Queue jobs |
| 기존 `n8n` Main | `6e52b659-525a-4580-85bf-a83ab6b72a73` | 동일 | `SUCCESS`, 실행 로그 `n8n ready` 및 Editor URL |
| 기존 `procureflow-n8n-editor-gateway` | 기존 배포 변경 없음 | `main` | `/healthz` 정상, 접속 주소 유지 |

- 두 서비스의 실제 Railway Docker 빌드 로그에서 `PAN_PATCH_PATCHED: .../Canvas.vue` 확인. 이는 패치 코드 적용 증거이며, **로그인 후 캔버스의 실제 사용자 동작 검증은 아님**.
- 운영 PostgreSQL/Redis/기존 `N8N_ENCRYPTION_KEY` 등의 **환경변수 이름 및 기존 설정을 유지**. 원래 Main에 지정되어 있던 무조건적 `n8n import:workflow --separate` pre-deploy 명령은 이번 배포 전 제거하여 기존 DB의 워크플로를 재덮어쓰지 않도록 했음.
- **중요 미완료**: 기존 게이트웨이 `/rest/settings`는 배포 이후에도 `userManagement.showSetupOnFirstLoad=true`; `/setup`은 403(공개 최초-owner 등록 차단). 사용자 인증 기반 실제 Chrome Pan/노드 검증 미완료. 실제 n8n 엔진 로그는 `Processed 0 draft workflows, 0 published workflows`였으며 DB 내 모든 워크플로 수를 검증하지 못했으므로 26개 기존 운영 흐름 활성화/작동 성공을 주장하지 않음.
- 첫 번째 Worker 배포 `43d75c48-8d25-440b-9daf-daa9a34f5426`는 Railway가 BuildKit `RUN --mount=type=secret`를 지원하지 않아 **빌드 FAILED**, 해당 문제를 `b4dad318`에서 수정 후 동일 운영 서비스에 성공 배포함.
- **백업 제약**: 사용 가능한 Railway 연결 도구로 PostgreSQL 백업본의 존재·복구 검증을 실행하지 못했다. 따라서 백업 검증 완료로 표시하지 않음. 신중한 후속 조치를 위해 기존 이전 deployment ID를 기록: Main `73422967-bfb7-4d26-8ed4-e496fd526abe` (교체로 REMOVED), Worker 이전 성공 `4a810cd1-8a04-4fa9-bdf3-37480f2df4c1`; 옛 이미지 복구 가능성을 별도 검증하기 전에는 롤백 완료를 주장하지 않음.
- Main 첫 시작 당시 `Detected 2 instances claiming leader role` 경고 1건을 관찰함. 배포 중 인스턴스 겹침 관련 가능성은 있으나 근본원인은 확인되지 않아 사후 관찰 필요.
- 기능 브랜치의 문서 변경은 라이브에 재배포되지 않으며, 두 운영 서비스는 상기 커밋 SHA로 고정되어 있음.


## 2026-10-29 — 기존 공식 편집기 진입 실패 원인 실측 (재설치·신규 계정 없음)

- 사용자가 제시한 `Set up owner account`는 **기존 공용 n8n의 현재 상태**와 일치한다. 실서비스 `https://procureflow-n8n-editor-gateway-production.up.railway.app/rest/settings`에서 `userManagement.showSetupOnFirstLoad=true` (HTTP 200) 재확인.
- 이 공용 게이트웨이의 `/setup`는 HTTP **403** (소스 `n8n/editor-proxy/Caddyfile`의 외부 최초 소유자 등록 차단), `/rest/workflows`는 HTTP **401** (인증 필요), `/healthz`는 HTTP **200**. 따라서 **게이트웨이 정상과 편집기 진입 가능은 다름**.
- 이전부터 존재하는 시험 서비스 `procureflow-n8n-github-source-test`의 `/rest/settings`도 `showSetupOnFirstLoad=true`. 이 서비스의 **별도 지속 볼륨에 26개 워크플로를 import 한 로그가 존재한다 해도 편집기 owner 인증이 완료되었다는 증거는 아님**.
- 운영 `n8n` Main은 `DB_POSTGRESDB_*` 및 `N8N_ENCRYPTION_KEY` 등 Postgres 설정이 있는 상태이고 시작 로그에 `n8n ready`, 과거 `Successfully imported 15 workflows`가 기록됨. 하지만 공식 소유자 `settings` 행/실제 워크플로 소유관계/DB 백업의 존재는 **도구로 SQL 조회 불가**. 지금 기록은 Postgres 연결 여부이지 기존 owner가 있었다는 증거가 아니다.
- Railway 공개 변수/민감정보는 연결된 접근 권한에서 **이름만 제공**됨. 실제 DB 호스트·DB명·키 일치, `user`/ `settings`/ `workflow_entity`/ `shared_workflow`/ `project_relation` 원본 행과 복구 백업 비교는 **추가 권한·원본 증빙이 있어야 가능**. 이를 확인하지 않고 DB 연결을 변경하면 원래 데이터 손실 위험이 있다.
- n8n 공식 사용자 관리 문서: n8n 1.0 이상에서 로그인 화면을 끄는 지원 설정은 없음. `n8n user-management:reset`는 기존 사용자 계정을 제거하는 명령이므로 **절대 실행 금지**.
- [실제 공개 상태 읽기 전용 CI](https://github.com/lyonbegin/procureflow/actions/workflows/existing-n8n-editor-readiness.yml): `GET /healthz`, `/rest/settings`, `/setup`, `/rest/workflows`만 확인하고 신규 n8n/owner/DB 변경 없이 **owner 미설정이면 명시적으로 FAIL**. 이 검사가 성공하기 전에는 공용 편집기를 사용 가능하다고 보고하지 않는다.
- **운영 수정 경계**: 임의 관리자 생성·새 계정/비밀번호·비밀번호 우회·공개 `/setup` 개방·추가 n8n 설치·DB 초기화/재연결·추측에 의한 운영 이전은 모두 금지. 우선 기존 데이터베이스 또는 복원 가능한 스냅샷에 기존 owner가 있었는지 권한 있는 읽기 전용 조사 → 발견 시 기존 owner와 워크플로 공유 관계 복원 검토. 기존 owner 부재가 실제로 확인되면 사용자의 명시적 동의하에 공식 1회 소유자 초기화 절차가 필요하다.


### 시험 10/10 PASS vs 운영 setup 실패의 차이 (확인된 직접 원인)

`.github/workflows/shared-n8n-candidate.yml`은 격리 n8n에 `DB_TYPE=sqlite`와 테스트 전용 `N8N_ENCRYPTION_KEY`를 넣고 `POST /rest/owner/setup`에 `candidate@example.invalid` 테스트 owner를 생성한 뒤 실제 Chrome/노드 API를 검사한다. 이 가상 계정 생성은 **오직 CI 임시 시험 DB에서** 수행되며 운영 Railway Main PostgreSQL에는 적용하지 않는다. 따라서 이전 10/10 Chrome PASS는 운영 사용자가 별도의 owner setup 없이 로그인할 수 있다는 뜻이 아니다.

[실제 운영 차단 CI run 40892467553](https://github.com/lyonbegin/procureflow/actions/runs/40892467553) 콘솔: `EXISTING_N8N_EDITOR_READINESS {"gatewayHealthStatus":200,"settingsStatus":200,"ownerSetupRequired":true,"publicOwnerSetupStatus":403,"unauthenticatedWorkflowApiStatus":401,...}` 다음 `EDITOR_BLOCKED_UNCLAIMED_OWNER` 로 정상 차단. **운영 소유자 문제 해결 전 화면 사용 가능 판정 불가**.

## 2026-10-30 00:54 KST — 기존 공식 편집기 owner 차단 CI 원인 분석 및 증빙 보존 개선 (전체 미완료)

- 대상: [Issue #21](https://github.com/lyonbegin/procureflow/issues/21) / [Draft PR #22](https://github.com/lyonbegin/procureflow/pull/22), 기능 브랜치 `feature/shared-n8n-pan-integration`만 수정.
- 기준 HEAD `10f8d208b551f42c94366b6d5ca81c7ab58cd66d`의 **9개 CI 중 8개 SUCCESS, 1개 FAILURE**. 성공: [단일 편집기](https://github.com/lyonbegin/procureflow/actions/runs/40899361302), [S01~S10](https://github.com/lyonbegin/procureflow/actions/runs/40899361296), [PF15](https://github.com/lyonbegin/procureflow/actions/runs/40899361287), [공식 후보 Docker/Chrome](https://github.com/lyonbegin/procureflow/actions/runs/40899361371), [기존 Main/Worker 이미지](https://github.com/lyonbegin/procureflow/actions/runs/40899361307), [Pan 소스 빌드](https://github.com/lyonbegin/procureflow/actions/runs/40899361267), [50종/43블록 계약](https://github.com/lyonbegin/procureflow/actions/runs/40899361285), [G2B 104 Node Lab](https://github.com/lyonbegin/procureflow/actions/runs/40899361315).
- **실패 CI [40899361274](https://github.com/lyonbegin/procureflow/actions/runs/40899361274)**: 공식 운영 게이트웨이 읽기 전용 응답 `/healthz=200`, `/rest/settings=200`, `showSetupOnFirstLoad=true`, `/setup=403`, `/rest/workflows=401`. 테스트가 의도대로 `EDITOR_BLOCKED_UNCLAIMED_OWNER`로 FAIL. **이것은 테스트 오탐이 아니며 기존 n8n 관리자 소유권/DB 준비 상태 미충족**. CI를 억지로 PASS 처리하거나 owner setup을 우회해서는 안 됨.
- 기능 브랜치에서 [`tests/test_existing_n8n_editor_readiness.mjs`](../tests/test_existing_n8n_editor_readiness.mjs)를 보강하여 **실패해도** 상태 코드/owner flag/보안 차단만 포함하는 **민감정보 제거 JSON 판정 파일**을 저장하도록 함. 응답 body, 쿠키, 자격증명, workflow data는 기록하지 않음.
- [`tests/test_existing_n8n_editor_readiness_unit.mjs`](../tests/test_existing_n8n_editor_readiness_unit.mjs)에 **격리 HTTP mock**으로 owner 미설정 시 FAIL + JSON 보존, 이미 설정 시 PASS, 민감정보 canary 비노출을 검증하는 2개 테스트 추가.
- [`existing-n8n-editor-readiness.yml`](../.github/workflows/existing-n8n-editor-readiness.yml)에서 격리 단위 테스트를 먼저 실행하고, 실제 읽기 전용 gate가 FAIL이어도 `actions/upload-artifact@v4`로 `existing-n8n-editor-owner-readiness-verdict` 업로드하도록 변경. **실제 owner 미설정이면 전체 job FAIL은 그대로 유지**.
- 변경 커밋: [`307a02e`](https://github.com/lyonbegin/procureflow/commit/307a02e01693810ee8e1069e67c799966a8a8121), [`3ab4ccb`](https://github.com/lyonbegin/procureflow/commit/3ab4ccb7b8c1f7f208c691f059fc7487d8397bb0), [`d8a24e1`](https://github.com/lyonbegin/procureflow/commit/d8a24e1fdecb2a2d0a19569435890e983e9334ad), [`6788c9d`](https://github.com/lyonbegin/procureflow/commit/6788c9dfe00ec07605673e9779321cf175f71d6d). 새 CI의 최종 상태는 **별도 확인 전 PASS로 표시하지 않음**.
- **전체 미완료:** 운영 owner/인증 복구, 35종 미지원 노드의 실행 어댑터, 43개 실제 업무 핸들러, 공식 10년 개찰·낙찰 증빙, 별도 디버깅 80개 전수, 운영 DB·키·백업/롤백·승인. 운영 `main`, Railway DB/자격증명, 실제 투찰 변경 없음. PR Draft·Issue Open 유지.

## 2026-10-30 KST — 공식 n8n 43개 격리 노드 HTTP 호출 실측 (전체 수용 **미완료**)

**기능 브랜치만 수정:** `feature/shared-n8n-pan-integration`. 운영 `main`, Railway 운영 서비스·DB·자격증명, 실제 투찰은 변경하지 않음. Issue #21 Open / PR #22 Draft·미병합 유지.

- [격리 fixture 요청 계측 커밋 `5b59d8f`](https://github.com/lyonbegin/procureflow/commit/5b59d8faedad18a21651316a1ffdea7a3461353d): 기존 loopback 전용 HTTP HOLD fixture에 읽기 요청 수·비허용 요청 수·PF별 요청 수를 누적하는 `GET /__fixture_stats` 추가. 원본 bid/자격증명/응답 payload는 계측하지 않음.
- [CI 실제 호출수 검증 `f86a89d`](https://github.com/lyonbegin/procureflow/commit/f86a89d3e04187131b2b26eec8c66c7bb54a82f2) 및 [PF15 소유 블록 0건 반영 `0526c28`](https://github.com/lyonbegin/procureflow/commit/0526c284fa8186aeddd2ad1071020349026d2d86), [JSONL 개행 수정 `a84b5f7`](https://github.com/lyonbegin/procureflow/commit/a84b5f71242d39c3410376d713e02a1575a2e18e): 실제 공식 n8n 2.44.6 격리 후보/Google Chrome E2E가 끝난 **후** 같은 컨테이너 안의 fixture 카운터를 독립 조회하고 manifest PF 소유 블록과 대조. PF15는 블록 소유 0건이므로 요청 0건이 정상.
- [**최종 공식 후보 Docker + 실제 Chrome CI #40948969757 — SUCCESS**](https://github.com/lyonbegin/procureflow/actions/runs/40948969757), [**실행 로그·스크린샷·trace·fixture traffic JSON**](https://github.com/lyonbegin/procureflow/actions/runs/40948969757/artifacts/12931431215): `OFFICIAL_NATIVE_PF_IMPORT_PASS` 26개 원본 워크플로/43개 노드; 실제 n8n 실행 ID 1(단일 HOLD), 2(43개 HOLD), 3(fail-closed error). `ISOLATED_NATIVE_43_BLOCK_HTTP_TRAFFIC_PASS {"validReads":46,"rejectedRequests":0,"checkedFlows":14}`. **46건 = 43개 블록 실제 격리 HTTP GET + 단일 HOLD 실행 1건 + fail-closed 실행 1건 + fixture 준비 확인 GET 1건**. PF01~PF14의 소유 블록별 예상 호출수와 정확히 일치.
- 같은 CI에서 `REAL_CHROME_DEBUG_80_SUBCHECKS_PASS {"observed":7,"fullyAccepted":0,"actualBusinessHandlers":0,"actualBidSubmissions":0}` 확인. **7개는 제한적인 합성 실행 하위검사**이고 80개 전체 수용은 **0/80**.
- 같은 HEAD `a84b5f7`의 [Pan 공식 Docker/Chrome #40948969795](https://github.com/lyonbegin/procureflow/actions/runs/40948969795), [S01~S10 #40948969807](https://github.com/lyonbegin/procureflow/actions/runs/40948969807), [50종/43블록 #40948969870](https://github.com/lyonbegin/procureflow/actions/runs/40948969870), [단일 공식 편집기 #40948969731](https://github.com/lyonbegin/procureflow/actions/runs/40948969731), [104 API/Node Lab #40948969713](https://github.com/lyonbegin/procureflow/actions/runs/40948969713), [PF15 읽기 전용 #40948969657](https://github.com/lyonbegin/procureflow/actions/runs/40948969657), [Main/Worker 격리 이미지 #40948969789](https://github.com/lyonbegin/procureflow/actions/runs/40948969789) **SUCCESS**.
- [기존 공식 n8n 운영 편집기 owner/readiness #40948969798](https://github.com/lyonbegin/procureflow/actions/runs/40948969798) **FAIL (실제 차단 지속)**. `showSetupOnFirstLoad=true`, `/setup=403`, `/rest/workflows=401`. 운영 DB/owner 초기화·인증 우회 없이 해결 불가 상태를 PASS로 처리하지 않음.

**남은 필수 수용:** 공식 운영 owner 복구(승인·DB 보존 필요), 35종 미지원 노드 실행 어댑터, 43개 **실제** 업무 핸들러, 10년 공식 개찰·낙찰 원본 완전성, 80개 디버깅 전체 실증, 운영 호환성/백업/승인. **46건은 loopback 합성 fixture HTTP 관측이며 실제 G2B 호출 46건이나 실제 업무 실행 43건이라는 뜻이 아님.**

## 2026-10-30 KST — isolated image smoke CI GitHub API 403 remediation (final acceptance pending)

- On [commit `34ccc5e9` CI #40950613021](https://github.com/lyonbegin/procureflow/actions/runs/40950613021), the `custom-node-image-smoke` job failed at the **source dependency install**, before any native workflow/runtime assertions. Log: `@vscode/ripgrep@1.17.1 postinstall` requested `https://api.github.com/repos/microsoft/ripgrep-prebuilt/releases/tags/v15.0.1` and repeatedly received **HTTP 403**, then `ERR_PNPM_EXECUTOR_LIFECYCLE_SCRIPT_FAILED`. Other scenario jobs in that run passed; **do not count the aggregate run as SUCCESS**.
- [Feature-branch CI fix `e46d389`](https://github.com/lyonbegin/procureflow/commit/e46d389088cdce08df85d5837559907c0f696a09): only `.github/workflows/n8n-single-engine-tests.yml` changed. CI copies the original `n8n/Dockerfile` to a temporary, uncommitted Dockerfile, injects a **BuildKit secret mount for the ephemeral read-only GitHub Actions token** at the single pnpm install step, and builds a disposable image with `docker build --secret`. It also increases the isolated full-source smoke timeout to 60 minutes. **The real `n8n/Dockerfile` bytes, production image configuration, operating main/Railway/DB/credentials, and bid submission remain untouched.** The secret is never an `ARG` or persistent `ENV`.
- [Revalidation on exact fix SHA — CI #40952522193](https://github.com/lyonbegin/procureflow/actions/runs/40952522193) **started; final result must be checked before PASS**. [Full official n8n Chrome candidate #40952522332](https://github.com/lyonbegin/procureflow/actions/runs/40952522332), [Pan Chrome #40952522136](https://github.com/lyonbegin/procureflow/actions/runs/40952522136), [50-kind/43-block #40952522179](https://github.com/lyonbegin/procureflow/actions/runs/40952522179), [S01-S10 native scenario job in #40952522193](https://github.com/lyonbegin/procureflow/actions/runs/40952522193), [owner readiness #40952522286](https://github.com/lyonbegin/procureflow/actions/runs/40952522286) are separately tracked. The owner gate remains a real blocker until it is actually verified fixed; do not bypass or auto-create an owner.
- **Overall status remains INCOMPLETE:** 35 unsupported shared kinds, 43 real business handlers, official 10-year award/bid evidence, 80 debugging requirements full runtime verification, operating owner/DB compatibility and authorized rollout. Issue Open / PR Draft, no merge or production deployment.


## 2026-10-30 KST — S01~S10 격리 시나리오 안전성 계약 27개 오프라인 회귀 (전체 수용 **미완료**)

- 기능 브랜치 전용 코드: [격리 변환기 `scenario-safety.mjs`](../.github/pan-e2e/scenario-safety.mjs), [S01~S10/악성 변조 검증 `test_isolated_scenario_safety.mjs`](../tests/test_isolated_scenario_safety.mjs), [격리 CI](../.github/workflows/shared-n8n-scenario-safety.yml). 운영 `main`, Railway 운영 서비스·DB·자격증명, 실제 투찰 변경 없음.
- [**독립 오프라인 시나리오 안전성 CI #40966375555 — SUCCESS**](https://github.com/lyonbegin/procureflow/actions/runs/40966375555): 원본 S01~S10 10개가 `active=false`이고, 외부 QA HTTP 노드 1개가 **실행 전에 로컬 Code assertion으로 치환**될 수 있음을 검사. 악성 원본의 활성화, 잘못된 QA URL/메서드, HTTP 노드 추가, 자격증명, 중복 노드 ID/이름, 미허용 노드, fetch/import/require/process/globalThis/HTTP helper/eval 등 **17개 실패-차단 회귀**를 추가. 이 신규 모듈은 **별도 오프라인 계약 검사**로, 기존 Chrome 시나리오 드라이버에 직접 연결되었다고 주장하지 않는다.
- 앞선 [`@vscode/ripgrep` GitHub API 403 이미지 smoke 실패 #40950613021](https://github.com/lyonbegin/procureflow/actions/runs/40950613021)의 [CI BuildKit secret 수정 `e46d389`](https://github.com/lyonbegin/procureflow/commit/e46d389088cdce08df85d5837559907c0f696a09)은 [**재검증 #40952522193 — 6/6 jobs SUCCESS**](https://github.com/lyonbegin/procureflow/actions/runs/40952522193)로 최종 확인. 같은 기능 브랜치의 [공식 Chrome 후보 #40952582850](https://github.com/lyonbegin/procureflow/actions/runs/40952582850), [Pan Chrome #40952582800](https://github.com/lyonbegin/procureflow/actions/runs/40952582800), [Main/Worker 격리 빌드 #40952582803](https://github.com/lyonbegin/procureflow/actions/runs/40952582803)도 SUCCESS. [Chrome 후보 스크린샷·trace·fixture HTTP 계측](https://github.com/lyonbegin/procureflow/actions/runs/40952582850/artifacts/12933215533) 보존.
- 공식 Chrome 후보 로그: 26개 PF/S 워크플로 임포트, 43개 custom node, PF05 노드 추가/설정/좌표 **[0,9]→[80,64]** 저장·재진입, 두 출력 핸들 연결·삭제, 실제 n8n 실행 ID **1·2·3**, 격리 HTTP GET **46회**, 7개 제한적 디버깅 하위검사. 실제 업무 핸들러 **0**, 실제 투찰 **0**, 전체 디버깅 요구 완전 수용 **0/80**.
- [**현재 운영 n8n owner/readiness #40966375345 — FAIL**](https://github.com/lyonbegin/procureflow/actions/runs/40966375345): `showSetupOnFirstLoad=true`, 공개 `/setup=403`, 비인증 `/rest/workflows=401` 차단 지속. 운영 DB/계정 초기화나 인증 우회 없이 실패로 유지.
- [이번 새 HEAD `d2013b5` 공식 후보 #40966375240](https://github.com/lyonbegin/procureflow/actions/runs/40966375240), [Pan #40966375370](https://github.com/lyonbegin/procureflow/actions/runs/40966375370), [S01~S10/native #40966375337](https://github.com/lyonbegin/procureflow/actions/runs/40966375337)는 **최종 결과 확인 전 PASS 판정 금지**.
- **남은 필수 수용:** 35종 실행 미지원 어댑터, 43개 실제 업무 핸들러/정식 payload 스키마, 공식 10년 개찰·낙찰 실데이터, 80개 디버깅 전체 런타임, 운영 owner·DB·키 호환성 및 승인. Issue Open / PR Draft·미병합 유지.


## 2026-10-30 KST — S01~S10 안전 변환기를 **실제 공식 Chrome 드라이버에 연결** (전체 미완료)

- [실제 Chrome 드라이버 연결 커밋 `49338f0`](https://github.com/lyonbegin/procureflow/commit/49338f09a4101059c66db8b054e4e5e771111fbb): `.github/pan-e2e/scenarios.mjs`의 별도·느슨한 `makeSafe()` 구현을 삭제하고, 기존 오프라인 검증된 `makeSafeScenario()`를 직접 import하여 **원본 n8n JSON을 공식 Chrome/격리 n8n에 import하기 직전** 동일 fail-closed 검사를 적용. 기존 브라우저의 원격 요청 차단도 유지.
- [드라이버 결속 테스트 `3cb2718`](https://github.com/lyonbegin/procureflow/commit/3cb2718c42adf7ab76f921a67d3a9b1eaf03a865): 실제 Chrome 드라이버가 공용 안전 변환기를 import·호출하고 중복 구현이 없는지 검사하는 테스트 추가.
- [CI 트리거 연결 `2558c63`](https://github.com/lyonbegin/procureflow/commit/2558c6346ad9d66ce5d3d0bc08360539bcc6ee77): Chrome 드라이버 변경 시 오프라인 S01~S10 안전성 회귀 CI가 자동 실행되도록 워크플로 경로 추가.
- [**최신 오프라인 안전성 CI #40968291400 — SUCCESS, 실제 job 로그 28/28 PASS**](https://github.com/lyonbegin/procureflow/actions/runs/40968291400): S01~S10 원본 비활성/원격 QA POST를 로컬 Code assertion으로 변환, 자격증명·외부 호출·동적 코드·잘못된 노드/ID/이름 차단, 실제 Chrome 드라이버와 같은 변환기 사용까지 검사.
- **공식 Google Chrome에서 S01~S10 실제 재실행:** [최신 Pan Docker/Chrome CI #40968291464](https://github.com/lyonbegin/procureflow/actions/runs/40968291464) **최종 결과 확인 전**, 오프라인 PASS를 실제 브라우저 PASS로 선판정하지 않음. 같은 SHA의 [공식 후보 #40968291774](https://github.com/lyonbegin/procureflow/actions/runs/40968291774)도 별도 검증 대상.
- [기존 공식 운영 owner/readiness #40968291455](https://github.com/lyonbegin/procureflow/actions/runs/40968291455)는 별도 읽기 전용 게이트. 기존 owner/DB 상태가 미해결이면 FAIL 유지; 우회·초기화 금지.

**최종 수용은 여전히 미완료:** 35종 실행 미지원 어댑터, 43개 실업무 핸들러·payload schema, 정확 세부품명 기준 10년 공식 개찰/낙찰 원본 전수, 디버깅 80개 런타임 전수, 운영 owner/DB 호환성·승인. 기능 브랜치만 수정. 운영 `main`, Railway 운영 서비스/DB/자격증명 및 실제 투찰 변경 없음. PR Draft·Issue Open 유지.


## 2026-10-30 KST — 공식 Chrome 재진입 전 실제 UI CRUD/드래그 순서 회귀 수정 (전체 미완료)

- [Pan UI 드라이버 수정 `e095f06`](https://github.com/lyonbegin/procureflow/commit/e095f0625968eb3e11a1d24b5d6fa8e8adabac27): 이전 [Chrome FAIL #41022772890](https://github.com/lyonbegin/procureflow/actions/runs/41022772890)에서 **재진입 직후 native node creator plus 버튼이 없던 현상**을 확인. 이제 원본 공식 n8n 화면 최초 진입 직후 **실제 Chrome 팔레트 노드 추가·삭제를 먼저 실행**하고, Pan/핸들/Code 좌표 저장·재진입·줌·CodeMirror·실제 n8n 실행을 계속 검사한다. 노드 삽입·삭제는 REST/DOM 직접 조작 금지, 실제 UI 동작으로만 판정. 재진입 후 팔레트 가시성은 별도 `OBSERVED`로 기록하며 그 회귀를 해결했다고 주장하지 않는다.
- [후보 custom 드래그 수정 `88796fc`](https://github.com/lyonbegin/procureflow/commit/88796fcb711399dbada0c0336a4e410a71011fa0) / [구문 정리 `69201d3`](https://github.com/lyonbegin/procureflow/commit/69201d3bfbe689e3fb5a88c64be34a22a33038fa): 이전 [Chrome FAIL #41022772802](https://github.com/lyonbegin/procureflow/actions/runs/41022772802)에서 **커스텀 노드 서버 좌표가 [0,9]에서 변하지 않음**. 새 드라이버는 **팔레트에서 추가한 동일한 Chrome 편집 세션에서 실제 마우스로 custom 노드를 드래그**, 서버 저장 좌표를 확인한 다음 **새로고침 후 좌표·N02/evidenceHandling=hold를 재검증**한다. 재진입 후 편집기 툴바 가시성은 별도 기록. **좌표를 API/DOM으로 강제 변경하지 않는다.**
- 두 드라이버 변경에 대한 V8 정적 구문 검사 **PASS**. 같은 코드 SHA `69201d3`의 [Pan 공식 Docker/Chrome CI #41027712029](https://github.com/lyonbegin/procureflow/actions/runs/41027712029), [후보 공식 Docker/Chrome CI #41027712300](https://github.com/lyonbegin/procureflow/actions/runs/41027712300) **실행 시작, 결과 대기**. 성공 전 PASS 선판정 금지.
- [50종/43블록 계약 #41027712078](https://github.com/lyonbegin/procureflow/actions/runs/41027712078), [G2B 104 Node Lab #41027712119](https://github.com/lyonbegin/procureflow/actions/runs/41027712119), [S01~S10 오프라인 안전성 #41027712043](https://github.com/lyonbegin/procureflow/actions/runs/41027712043), [단일 공식 편집기 #41027712100](https://github.com/lyonbegin/procureflow/actions/runs/41027712100) **SUCCESS**.
- [기존 운영 owner/readiness #41027711944](https://github.com/lyonbegin/procureflow/actions/runs/41027711944) **FAIL 지속**. 운영 DB/계정 초기화·우회 금지. 35종 실행 매핑, 43개 실제 핸들러, 공식 10년 실데이터, 디버깅 80개 런타임, 운영 호환성·승인 **미완료**.
- **Issue Open / PR Draft·미병합. 운영 main/Railway 운영 서비스·DB/자격증명/실제 투찰 변경 없음.**


## 2026-10-30 KST — 실제 43개 n8n read-only 노드 오류·HOLD·비밀정보 마스킹 격리 회귀 (**전체 미완료**)

- **기능 브랜치만 변경:** [테스트 커밋 `1359141`](https://github.com/lyonbegin/procureflow/commit/135914141046944b2ec73c0928f2cdd6243c2471)에서 `tests/test_inspection_envelope_runtime.mjs`에 **실제 `ProcureFlowBusinessOperation.execute()`를 43개 operationId마다 호출하는** 실패 주입 검사를 추가했다. 네트워크는 실제 호출하지 않고 `helpers.httpRequest`만 메모리 안에서 주입한다. 운영 DB·Railway·자격증명·실투찰 호출 없음.
- **[격리 50종/43블록 계약 CI #41070158439 — SUCCESS](https://github.com/lyonbegin/procureflow/actions/runs/41070158439)** · [계약/스키마 아티팩트 #12983454894](https://github.com/lyonbegin/procureflow/actions/runs/41070158439/artifacts/12983454894). **실제 job 로그** `PROCUREFLOW_43_READONLY_FAILURE_INJECTION_PASS`: 43개 실제 custom-node ID, **loopback mock GET 215회**, 네트워크 오류/원본 불일치/STOP 모드 **129건 fail-closed**, 불법 파라미터·선택 발주 불일치 **172건 HTTP 이전 차단**, 합성 승인 위조 **43건 HOLD 유지**, 상위 입력·HTTP provider 오류의 토큰/비밀정보 출력 차단 **43건**. 신규 2/2 node:test PASS.
- 같은 CI의 기존 JSON Schema 2020-12 검사는 **43개 실제 격리 노드 출력, mock GET 43건, 위조 파라미터·출력 817건 거부**, `PROCUREFLOW_43_ACTUAL_ISOLATED_INSPECTION_ENVELOPES_SCHEMA_PASS`. Chrome 증빙 위조 검증 33/33도 PASS. **실제 업무 핸들러 0 / 공식 G2B 원본 0 / 투찰 0**.
- 이 테스트는 디버깅 요구 138(HTTP 오류), 139(타임아웃 실패 경로), 158(비밀정보 마스킹)의 **일부 합성·격리 검증**이다. 80개 요구사항 전수 수용, 실제 시간 경과 타임아웃/실시간 스트리밍, 운영 오류 복구까지 완료했다는 뜻이 아니다.
- **기존 운영 편집기 owner/readiness #41070158453 — FAIL**: 실제 읽기 전용 검사 `gatewayHealthStatus=200`, `ownerSetupRequired=true`, `/setup=403`, 비인증 `/rest/workflows=401`, `ready=false`, `EDITOR_BLOCKED_UNCLAIMED_OWNER`. 계정/DB 초기화·우회·수정 없음.
- 동일 SHA의 [공식 n8n Docker/Chrome 후보 #41070158663](https://github.com/lyonbegin/procureflow/actions/runs/41070158663), [Pan 소스 #41070158426](https://github.com/lyonbegin/procureflow/actions/runs/41070158426), [S01~S10/native #41070158494](https://github.com/lyonbegin/procureflow/actions/runs/41070158494), [Main/Worker 격리 빌드 #41070158471](https://github.com/lyonbegin/procureflow/actions/runs/41070158471), [PF15 읽기 전용 #41070158475](https://github.com/lyonbegin/procureflow/actions/runs/41070158475)은 이 기록 시점 장시간 실행 중이므로 **최종 PASS 선판정 금지**.
- **잔여 필수 수용:** 35종 미지원 공용 노드 실행 매핑, 43개 실제 업무 핸들러·정식 payload 스키마, 정확 세부품명 기준 10년 공식 개찰·낙찰 전수, 디버깅 80개 전체 실증, 기존 운영 owner/DB·키 호환성·복원/명시적 승인. **Issue OPEN / PR Draft·미병합 유지. 운영 main/Railway 운영 서비스·DB/자격증명·실제 투찰 변경 없음.**


## 2026-10-31 KST — 선택 발주 식별자 falsey 값 차단 및 CI 실증 (전체 완료 아님)

- **기능 브랜치 코드 변경:** [`c9dc8f7`](https://github.com/lyonbegin/procureflow/commit/c9dc8f71eeffb7d72d794c809bcc73b3d6b32a26) — `ProcureFlowBusinessOperation.execute()`의 기존 `upstream.bid_no && upstream.bid_no !== bidNo` 조건은 앞 노드가 `bid_no: ""`, `null`, `0`, `false`를 명시해도 truthiness 때문에 검사에서 누락했다. `Object.hasOwn(upstream,'bid_no')`로 **명시된 모든 불일치**를 HTTP 요청 전 차단하고, 수동 시작으로 입력에 `bid_no` 자체가 없는 경우는 유지한다.
- **회귀 테스트:** [`3f1e1e1`](https://github.com/lyonbegin/procureflow/commit/3f1e1e1e0afb0d4e4210202e864c5b1d5da40c92) — 위 5개 잘못된 값 모두 HTTP **0회**, 누락/정상 ID 각각 HOLD 응답 및 GET **2회**를 검증한다.
- **[실제 CI #41079299576 — SUCCESS](https://github.com/lyonbegin/procureflow/actions/runs/41079299576)**: 공식 단일 편집기/Node 회귀 job 로그에 `explicit falsey or malformed upstream tender identifiers are blocked before HTTP` **ok**, Node **26/26 PASS**. [50종/43블록 계약 CI #41079299525](https://github.com/lyonbegin/procureflow/actions/runs/41079299525)도 SUCCESS.
- **[기존 운영 owner/readiness #41079299527 — FAIL](https://github.com/lyonbegin/procureflow/actions/runs/41079299527)**: 운영 계정/DB 수정 없이 읽기 전용 검사만 수행, 인증 준비 장애는 미해결. 같은 SHA의 장시간 후보 Docker/Chrome, Pan, S01~S10 등은 **최종 결과 확인 전** PASS로 기록하지 않는다.
- **전체 필수 미완료:** 35종 미지원 실행 어댑터, 43개 실업무 핸들러, 정확한 10자리 세부종목 10년 공식 원본 완전성, 디버깅 80개 전수, 운영 owner/DB/키 호환성·복구·승인. **Issue Open, PR Draft·미병합. 운영 main/Railway 운영 서비스·DB/자격증명/실제 투찰 변경 없음.**


## 2026-10-31 KST — malformed n8n item JSON preflight fail-closed (overall acceptance pending)

- [Feature-only runtime fix `6a2405d`](https://github.com/lyonbegin/procureflow/commit/6a2405d27d0b675623b7afe545f6f9c6ee17bd59): the actual `ProcureFlowBusinessOperation.execute()` previously used `entry?.json || {}`, silently interpreting `null`, arrays, primitives, or missing JSON as a legitimate empty manual-trigger object. Now it **rejects malformed input JSON objects for every batch item before issuing the first HTTP GET**, while retaining an actual `{}` manual-trigger input.
- [Isolated regression `57a1a2c`](https://github.com/lyonbegin/procureflow/commit/57a1a2cab2265c00fb25ab911a729cf2eea5dcd6): tests null, array, string, number, boolean, undefined, absent JSON and null item in **both first and second positions** of a two-item batch; each must produce **zero HTTP helper calls**, while a valid empty object still yields a synthetic HOLD. Tests use in-memory `httpRequest` stubs; no external network or production credential.
- **Same HEAD CI initiated (final result must be checked before PASS):** [single official editor + native node regression #41091263711](https://github.com/lyonbegin/procureflow/actions/runs/41091263711), [50 kinds/43 blocks #41091263828](https://github.com/lyonbegin/procureflow/actions/runs/41091263828), [isolated candidate official Chrome #41091263682](https://github.com/lyonbegin/procureflow/actions/runs/41091263682), [Pan source + Chrome #41091263661](https://github.com/lyonbegin/procureflow/actions/runs/41091263661), [S01–S10 offline #41091263651](https://github.com/lyonbegin/procureflow/actions/runs/41091263651).
- Prior [owner/readiness #41090161024](https://github.com/lyonbegin/procureflow/actions/runs/41090161024) **FAIL**: `ownerSetupRequired=true`, `/setup=403`, `/rest/workflows=401`; no owner/DB mutation.
- **Not final acceptance:** 35 unsupported shared executable kinds, 43 actual G2B business handlers, exact 10-year official evidence completeness, all 80 debugging requirements, operating owner/DB/key compatibility and authorized rollout remain outstanding. Issue OPEN, PR Draft/unmerged; operating `main`, Railway production services/DB, credentials and bids unchanged.


## 2026-10-31 KST — nested read-only evidence bid/Worker dispatch claims fail-closed (**전체 완료 아님**)

- **기능 브랜치만 변경:** [실제 n8n 커스텀 노드 보안 패치 `7297975`](https://github.com/lyonbegin/procureflow/commit/7297975f916d94ff8628ae80c5271c524314a3ab). 이전에는 inspection API의 최상위 bid/Worker 플래그를 검사했지만 **`blocks[]`와 `blocks[].output_value`의 내부 dispatch 주장을 검증하지 않고 출력에서만 제외**했다. 이제 읽기 전용 응답의 모든 블록(선택하지 않은 다른 블록 포함) 및 중첩 output에서 `bid_submitted`, `worker_job_enqueued`, `job_enqueued`, `automated_bid_submission`, `automatic_bid_submission`, `actual_job_executed`가 존재하면 정확히 `false`인지 검사하며, 위조된 값은 **HOLD로 무시하는 대신 계약 위반으로 실행을 차단**한다.
- [실제 커스텀 노드 `execute()` 회귀 테스트 `275e1a1`](https://github.com/lyonbegin/procureflow/commit/275e1a1a6127682fd963f69234057b8eee60ccc5): 6개 플래그 × 블록/출력 2개 계층 × 위조값 3종(`true`, `"true"`, `1`) = **36건**, 다른 블록의 가짜 Worker 등록 **1건**, 총 **37건** 거부. 누락 및 명시적 `false`는 기존 합성 HOLD를 유지한다.
- **로컬/격리 사전 실행:** 커넥터에서 읽은 실제 최신 노드 소스를 V8에서 안전한 `require`/URL 스텁으로 평가하고 **37/37 중첩 위조 차단**, 정상 합성 HOLD 및 `false` 호환을 확인. **실제 외부 HTTP 0건**, 스텁 응답 39건. 이것은 공식 Node 22 CI, 실제 Chrome 또는 운영 G2B 검증을 대체하지 않는다.
- **새 HEAD CI 실행:** [단일 편집기/노드 #41122464156](https://github.com/lyonbegin/procureflow/actions/runs/41122464156), [50종/43블록 #41122464513](https://github.com/lyonbegin/procureflow/actions/runs/41122464513), [격리 공식 Docker/Chrome #41122464014](https://github.com/lyonbegin/procureflow/actions/runs/41122464014), [Pan 소스/Chrome #41122464571](https://github.com/lyonbegin/procureflow/actions/runs/41122464571), [native S01~S10 #41122463868](https://github.com/lyonbegin/procureflow/actions/runs/41122463868), [운영 owner 읽기 전용 #41122464245](https://github.com/lyonbegin/procureflow/actions/runs/41122464245). **기록 시점 queued — 완료 로그를 확인하기 전에는 PASS 판정 금지**.
- **기존 HEAD `21212b5` 검증:** 공식 후보 Chrome #41109022117, Pan #41109021954, native 시나리오 #41109022019 등 **9개 CI SUCCESS**, 운영 owner/readiness #41109021973 **FAIL**. 이번 변경의 최신 SHA 결과와 구분한다.
- **여전히 미완료:** 35종 실행 어댑터, 43개 실제 업무 핸들러/정식 payload, 10년 실제 개찰·낙찰 전수, 80개 디버깅 런타임, 운영 owner/DB/키 호환성·승인. **Issue OPEN / PR Draft·미병합**, 운영 main/Railway 운영 서비스·DB/자격증명/실제 투찰 변경 없음.


## 2026-10-31 KST — entire-envelope nested dispatch claim validation (NOT FINAL ACCEPTANCE)

- **Feature branch only:** [actual native custom-node patch `e79c5ce`](https://github.com/lyonbegin/procureflow/commit/e79c5cee8ae1e8174476db416d0bc056f148448f). The read-only provenance validator previously scanned all `blocks[]` recursively, but **did not inspect top-level sibling metadata, audit history, provider records or arrays**. It now calls bounded `hasUnsafeNestedDispatchClaim(body)` on the **entire inspection envelope**, so hidden claims of `bid_submitted`, `worker_job_enqueued`, `job_enqueued`, `automated_bid_submission`, `automatic_bid_submission` or `actual_job_executed` anywhere in the provider response fail closed. The 10,000-object traversal limit applies to the whole envelope.
- [Actual native node regression `0076670`](https://github.com/lyonbegin/procureflow/commit/00766706da807c014c1777e6fe19005570d0bad5): six forged top-level nested metadata/array structures must be rejected by both `validateProvenance()` and `ProcureFlowBusinessOperation.execute()`; explicitly false claims preserve synthetic HOLD, and oversized top-level metadata fails closed. Test-only `helpers.httpRequest` stubs, **no external requests/Worker dispatch/actual bid**.
- **Verified on exact HEAD `0076670`:** [official single-editor + native Node 22 CI #41144660325](https://github.com/lyonbegin/procureflow/actions/runs/41144660325) **SUCCESS**, inspected job log **33/33 PASS** including `top-level nested provenance metadata cannot forge bid or Worker dispatch`, marker `PROCUREFLOW_TOP_LEVEL_NESTED_DISPATCH_BLOCKED` (6 rejected forgeries, 7 mocked responses, actual HTTP/Worker/bids 0). [50-kind/43-block audit #41144660273](https://github.com/lyonbegin/procureflow/actions/runs/41144660273) **SUCCESS**; 43 actual read-only node inspection envelopes/strict schemas and 43-operation failure injection continue to pass in-memory.
- [G2B 104 API Node Lab #41144660269](https://github.com/lyonbegin/procureflow/actions/runs/41144660269) and [S01–S10 offline safety #41144660334](https://github.com/lyonbegin/procureflow/actions/runs/41144660334) **SUCCESS**. Other exact-HEAD Docker/official Chrome Pan/full candidate, native S01–S10, PF15 and main/worker image jobs were **pending or in progress when checked**; do not pre-report PASS.
- [Existing operating editor readiness #41144660288](https://github.com/lyonbegin/procureflow/actions/runs/41144660288) **FAIL** (read-only): `ownerSetupRequired=true`, `/setup=403`, unauthenticated `/rest/workflows=401`, `EDITOR_BLOCKED_UNCLAIMED_OWNER`. Existing owner/DB unchanged.
- **Outstanding mandatory acceptance:** 35 unsupported shared executable kinds, 43 real G2B business handlers and strict business payloads, exact 10-year official bid/opening/award completeness, all 80 debugging requirements at runtime, operating owner/DB/key compatibility and explicit approval. **Issue OPEN / PR Draft and unmerged. No main merge, Railway production DB/service/credentials/owner change, actual bid or Worker dispatch.**

## 2026-10-31 KST — 원본 증빙 메타데이터 필드 수 제한 (전체 완료 아님)

- **기능 브랜치 코드만 수정:** [5cea768](https://github.com/lyonbegin/procureflow/commit/5cea7689f93cdc65a860b85ea1f5680315576904)에서 실제 공식 n8n 커스텀 노드 `ProcureFlowBusinessOperation.node.js`의 provenance 순회를 개선했다. 기존 10,000개 **객체 수** 제한은 primitive 값만 수만 개 포함한 하나의 배열/객체를 통과시켰다. `Object.values()` 전체 배열 생성 대신 자체 필드 순회로 **총 10,000개 필드 + 10,000개 객체**를 각각 제한하여 초대형 응답을 HOLD/실행 성공으로 받아들이지 않게 했다.
- **실제 Node 테스트 추가:** [46f96ed](https://github.com/lyonbegin/procureflow/commit/46f96ed3f8e7ba4f45109a6763546bed313c1abe)에서 10,050개 숫자 primitive 배열과 10,050개 primitive 속성 객체를 각각 거부, 소형 정상 증빙은 기존 HOLD 유지. **외부 HTTP/Worker/투찰 0건**, in-memory mock GET 3건.
- **검증된 동일 코드 SHA의 [공식 단일 편집기/Node CI #41167616351](https://github.com/lyonbegin/procureflow/actions/runs/41167616351) SUCCESS:** 실제 Node 22 로그 **34/34 PASS**, `PROCUREFLOW_PRIMITIVE_ONLY_EVIDENCE_FIELD_LIMIT_PASS`, 2개 초대형 증빙 거부·소형 HOLD 1건.
- [50종/43블록 계약 #41167616326](https://github.com/lyonbegin/procureflow/actions/runs/41167616326), [S01~S10 오프라인 #41167616356](https://github.com/lyonbegin/procureflow/actions/runs/41167616356), [G2B 104 Node Lab #41167616341](https://github.com/lyonbegin/procureflow/actions/runs/41167616341)은 **SUCCESS**. [공식 후보 Docker/Chrome #41167616331](https://github.com/lyonbegin/procureflow/actions/runs/41167616331), [Pan Chrome #41167616375](https://github.com/lyonbegin/procureflow/actions/runs/41167616375), [native S01~S10 #41167616350](https://github.com/lyonbegin/procureflow/actions/runs/41167616350), [Main/Worker 이미지 #41167616404](https://github.com/lyonbegin/procureflow/actions/runs/41167616404), [PF15 읽기 전용 #41167616336](https://github.com/lyonbegin/procureflow/actions/runs/41167616336)은 기록 시점 **진행 중 — PASS 선판정 금지**.
- **기존 운영 owner/readiness [#41167616327 FAIL](https://github.com/lyonbegin/procureflow/actions/runs/41167616327):** 읽기 전용 실제 응답 `ownerSetupRequired=true`, `/setup=403`, `/rest/workflows=401`, `EDITOR_BLOCKED_UNCLAIMED_OWNER`. 운영 계정·DB는 변경하지 않음.
- **필수 미완료:** 35종 미지원 공유 실행 매핑, 43개 실제 G2B 업무 핸들러·정식 payload, 정확한 10년 공식 개찰·낙찰 전수·Worker fencing, 별도 디버깅 80개 런타임 전수, 운영 n8n owner/DB/키 호환성·롤백·승인. **Issue Open / PR Draft·미병합 유지. 운영 main·Railway 서비스/DB·자격증명·실제 투찰 변경 없음.**


## 2026-10-31 KST — 기존 Main/Worker 이미지 CI GitHub 403 재현·격리 빌드 수정 (전체 완료 아님)

- **변경 범위:** 기능 브랜치 `feature/shared-n8n-pan-integration`의 `.github/workflows/shared-n8n-existing-service.yml` **CI 워크플로만 수정**. 운영 `main`, Railway Main/Worker/DB, owner, 자격증명, 실제 G2B API/Worker dispatch/투찰은 변경하지 않음. 운영 `n8n/Dockerfile`의 바이트는 수정하지 않음.
- **원인 실측:** 이전 HEAD `05fa84a`의 [PF15 읽기 전용 이미지 CI #41193475758](https://github.com/lyonbegin/procureflow/actions/runs/41193475758) FAIL. 실제 [job 124514825205](https://github.com/lyonbegin/procureflow/actions/runs/41193475758/job/124514825205) 로그에서 upstream n8n 2.44.6의 `@vscode/ripgrep@1.17.1` postinstall이 `api.github.com/repos/microsoft/ripgrep-prebuilt/releases/tags/v15.0.1` 조회를 **HTTP 403**으로 4회 실패해 `pnpm install` 단계에서 중단됨. **PF15 자체의 업무·실행 실패가 아니라 격리 이미지 빌드 실패**이므로 PF15 PASS로 보고하지 않음.
- **원인 구조:** 기존 워크플로는 `docker build --secret id=github_token,... -f n8n/Dockerfile`로 토큰을 전달했지만, 운영 Dockerfile은 Railway 호환성을 위해 BuildKit secret mount를 사용하지 않아 `GITHUB_TOKEN`이 postinstall에 전달되지 않았음. 별도 격리 Pan/후보 Dockerfile은 `RUN --mount=type=secret`으로 GitHub 토큰을 안전하게 전달하여 동일 소스 빌드에 성공한 이력이 있음.
- **수정:** [최종 CI 패치 `50ef072`](https://github.com/lyonbegin/procureflow/commit/50ef072ac856591cdc9c024ed186dacf874a261c). CI에서 **원본 운영 Dockerfile을 그대로 읽고, 유일한 `pnpm install` RUN에만** 임시 `--mount=type=secret,id=github_token`과 `GITHUB_TOKEN` 셸 환경 전달을 추가한 **/tmp 임시 Dockerfile**을 생성. 원본과 해당 한 구문 외 완전 동일한지 assertion으로 확인. GitHub Actions 토큰은 BuildKit secret으로만 공급하며 `ARG/ENV`에 넣지 않고 완성 이미지 `Config.Env`에도 없어야 함. 운영 소스/설정/배포/DB에 영향을 주지 않음.
- **동일 SHA 신규 CI:** [Main/Worker 이미지 #41197811866](https://github.com/lyonbegin/procureflow/actions/runs/41197811866), [PF15 #41197811834](https://github.com/lyonbegin/procureflow/actions/runs/41197811834), [공식 Chrome Pan #41197811867](https://github.com/lyonbegin/procureflow/actions/runs/41197811867), [공식 후보 Docker/Chrome #41197811842](https://github.com/lyonbegin/procureflow/actions/runs/41197811842), [native S01~S10 #41197811854](https://github.com/lyonbegin/procureflow/actions/runs/41197811854). **기록 시점 진행/대기 중 — 최종 PASS 선판정 금지.**
- [G2B 104/Node Lab #41197811832](https://github.com/lyonbegin/procureflow/actions/runs/41197811832), [오프라인 S01~S10 #41197811918](https://github.com/lyonbegin/procureflow/actions/runs/41197811918)은 같은 SHA에서 SUCCESS. [운영 owner/readiness #41197811840](https://github.com/lyonbegin/procureflow/actions/runs/41197811840)은 기존 미설정 owner로 FAIL; **운영 owner/DB는 그대로 보존**.
- **필수 미완료:** 35종 공유 노드 실제 실행 매핑, 43개 실제 G2B 핸들러/업무 스키마, 공식 10년 개찰·낙찰 실데이터 전수·Worker fencing, 디버깅 80개 전수, 운영 owner/DB/키 호환성·명시적 승인. **Issue Open, PR Draft·미병합, 최종 완료 통보 금지.**


## 2026-10-31 KST — 공식 월별 분류코드 다중 필드 모순 차단 (전체 완료 아님)

- **변경 범위:** 기능 브랜치만. [수집기 패치 `ce566cb`](https://github.com/lyonbegin/procureflow/commit/ce566cb742c2bea98919072105f40394a51cc694), [격리 회귀 테스트 `b0a9bca`](https://github.com/lyonbegin/procureflow/commit/b0a9bcaa1f1fdd776edcd47d48e4c261fda8bc6b). 운영 `main`, Railway Main/Worker/운영 DB/owner/자격증명/실제 투찰은 변경하지 않음.
- **실제 발견한 결함:** `g2b_case_10y_official._category_from()`가 `prdctClsfcNo` 등 여러 공식 분류 필드 중 **첫 번째 8자리 코드만** 확인했다. 첫 필드는 `81111599`인데 뒤의 `dtilPrdctClsfcNo`가 다른 부모 분류인 경우에도 해당 월을 정상 수집으로 판정할 수 있었다. 동일 부모 아래 서로 다른 10자리 세부코드 충돌과 잘못된 보조 필드도 무시했다.
- **수정:** 5종 공식 분류 필드 중 값이 존재하는 **모든 필드**를 검증하고, 부모 8자리 불일치·서로 다른 10자리 상세코드·잘못된 scalar/문자열은 `None`으로 판정하여 `blocked_unverified_response_scope`로 차단. 일관된 8자리+10자리 코드 조합과 다른 부모 8자리 정상 제외는 유지. **이는 8자리 공고 발견 무결성 강화이며 실제 10자리 개찰/낙찰 완전성 검증은 아님.**
- **격리 테스트:** 6개 모순/잘못된 필드 음성, 2개 일관된 부모+세부코드 양성, 1개 다른 부모 정상 제외를 추가. `FakeHTTP`/`FakeDB`만 사용, 실제 G2B API 호출·운영 DB 변경·Worker dispatch/투찰 **0건**.
- **동일 코드 HEAD `b0a9bcaa1f1fdd776edcd47d48e4c261fda8bc6b` [G2B 104 API + Node Lab #41203718680 SUCCESS](https://github.com/lyonbegin/procureflow/actions/runs/41203718680): 실제 job `124544461057` 로그 `116 passed, 3 warnings in 3.77s`.** [오프라인 S01~S10 #41203718615](https://github.com/lyonbegin/procureflow/actions/runs/41203718615), [50종/43블록 #41203718768](https://github.com/lyonbegin/procureflow/actions/runs/41203718768), [단일 공식 편집기 #41203718682](https://github.com/lyonbegin/procureflow/actions/runs/41203718682) **SUCCESS**.
- [공식 Pan/Chrome #41203718720](https://github.com/lyonbegin/procureflow/actions/runs/41203718720), [공식 후보 Docker/Chrome #41203718724](https://github.com/lyonbegin/procureflow/actions/runs/41203718724), [native S01~S10 #41203718651](https://github.com/lyonbegin/procureflow/actions/runs/41203718651), [Main/Worker 격리 이미지 #41203718716](https://github.com/lyonbegin/procureflow/actions/runs/41203718716), [PF15 #41203718708](https://github.com/lyonbegin/procureflow/actions/runs/41203718708)는 **기록 시점 진행 중 — 완료 PASS 선판정 금지**.
- [기존 운영 owner/readiness #41203718655](https://github.com/lyonbegin/procureflow/actions/runs/41203718655) **FAIL (읽기 전용 기존 장애)**. 운영 DB/owner 변경 없음.
- **필수 미완료:** 35종 실행 어댑터, 43개 실업무 핸들러/정식 payload, 공식 10년 개찰·낙찰 실데이터 전수, 별도 디버깅 80개 런타임 전수, 운영 owner/DB/키 호환성·승인. **Issue Open, PR Draft·미병합, 최종 완료 통보 금지.**



## 2026-11-01 KST — 공식 월별 수집 커서 위조/손상 차단 및 격리 회귀 (전체 완료 아님)

- **변경 범위:** `feature/shared-n8n-pan-integration`의 `g2b_case_10y_official.py` 및 `tests/test_g2b_official_month_cycle.py`만 수정. 운영 `main`, Railway 서비스·운영 DB·자격증명·실제 G2B 호출·Worker dispatch·투찰 **변경 없음**.
- **발견한 문제:** `scan_month()`가 DB에 저장된 `checked/matched/page_cursor`를 `int()`로 강제 변환하여 `True`, `1.5` 등 손상된 값을 정상 커서로 오인할 수 있었고, `status=completed`이면 커서 일관성을 검증하지 않고 `already_completed`를 반환했다. 이로 인해 121개월의 8자리 공고 발견 완료 상태를 잘못 신뢰할 수 있었다.
- **수정 커밋:** [`e284a68`](https://github.com/lyonbegin/procureflow/commit/e284a689d301099b468937d27b6955117ef79c8e), [`a31a1a5`](https://github.com/lyonbegin/procureflow/commit/a31a1a502ce2b81a264f316151c63e2eda9708a3), [최종 테스트 `d2e155e`](https://github.com/lyonbegin/procureflow/commit/d2e155e345d0ba6357827bea701ece79c4f61af6). `_audit_nonnegative_integer`를 사용해 DB 커서 원본 타입을 먼저 검증하고, 손상된 값은 **HTTP 호출 및 DB 기록 없이 read-only 차단**. 완료된 월은 `page==(checked+499)//500+1` 및 `matched<=checked`을 검증한 경우만 `already_completed` 반환. 정상 수치지만 일관성 없는 미완료 월의 기존 격리 상태 기록은 유지.
- **실제 실패 분석/재검증:** [중간 SHA CI #41219439368](https://github.com/lyonbegin/procureflow/actions/runs/41219439368)에서 기존 `checked=-1` 테스트가 예전 `_write_month` 호출을 기대해 **1 failed / 174 passed**. 새 정책은 손상된 DB 값을 다시 쓰지 않는 것이므로 기대값을 수정하고 19개 손상·완료 커서 음성/양성 사례를 추가. [최종 코드 SHA `d2e155e` G2B 104 API/Node Lab CI #41219473523](https://github.com/lyonbegin/procureflow/actions/runs/41219473523) **SUCCESS, 175 passed / 3 warnings**.
- [같은 SHA 오프라인 S01~S10 #41219473585](https://github.com/lyonbegin/procureflow/actions/runs/41219473585) **SUCCESS**. [50종/43블록 #41219473545](https://github.com/lyonbegin/procureflow/actions/runs/41219473545), [공식 Pan/Chrome #41219473538](https://github.com/lyonbegin/procureflow/actions/runs/41219473538), [공식 후보 Docker/Chrome #41219473554](https://github.com/lyonbegin/procureflow/actions/runs/41219473554), [native S01~S10 #41219473562](https://github.com/lyonbegin/procureflow/actions/runs/41219473562), [Main/Worker 격리 이미지 #41219473558](https://github.com/lyonbegin/procureflow/actions/runs/41219473558), [PF15 #41219473517](https://github.com/lyonbegin/procureflow/actions/runs/41219473517)은 이 기록 시점 일부 진행/대기 중이므로 **최종 PASS 선판정 금지**.
- **기존 owner 장애:** [직전 동일 기능 SHA의 운영 읽기 전용 CI #41212303293](https://github.com/lyonbegin/procureflow/actions/runs/41212303293) FAIL, `ownerSetupRequired=true`, `/setup=403`, `/rest/workflows=401`. 운영 owner/DB 변경 없이 남겨둠.
- **남은 필수 수용 기준:** 35종 미지원 공유 노드 실행 매핑, 43개 실제 G2B 업무 핸들러·payload, 정확한 10년 공식 개찰·낙찰 전수·Worker fencing, 80개 디버깅 런타임 전수, 운영 owner/DB/키 호환성·명시적 승인. **Issue Open, PR Draft·미병합, 전체 완료 통보 금지.**



## 2026-11-01 KST — 공식 n8n 읽기 전용 증빙 응답의 다중 식별자 모순 차단 (전체 완료 아님)

- **변경 범위:** `feature/shared-n8n-pan-integration`의 `n8n/custom-nodes/ProcureFlowBusinessOperation.node.js` 및 `tests/test_procureflow_business_operation.mjs`만 수정. 운영 `main`, Railway 서비스/DB, 관리자·자격증명, G2B 실제 조회, Worker dispatch, 투찰 **변경 없음**.
- **실제 발견한 결함:** 원본 `validateProvenance()`는 응답 최상위 `case_id`와 `flow_id` 및 선택된 `block.id`를 검사하지만, 응답에 추가로 실린 `bid_no`, `tenderNo`, 선택 블록의 `caseId`, `flowId`, `operationId` 등이 **서로 모순되어도** 통과할 수 있었다. 같은 응답이 다른 발주/업무 소유자를 주장하는 것을 엄격하게 차단해야 한다.
- **소스 패치:** [`02b5a0c`](https://github.com/lyonbegin/procureflow/commit/02b5a0c84a0b079cb0253b9c8e379dde393634e9) — 최상위 및 선택 블록의 6종 발주번호 별칭, 선택 블록의 2종 PF 플로우·2종 업무 ID 별칭이 존재할 경우 **모두 공식 선택값과 일치**해야 한다. 누락된 선택적 필드는 기존 API 호환성을 유지한다. 모순이면 성공/HOLD 판정 이전에 오류로 차단한다.
- **격리 회귀:** [`89b101b`](https://github.com/lyonbegin/procureflow/commit/89b101b76f0ff423d57836b8f93eb780a6c65d75) — 서로 모순되는 **15개 응답 별칭** 음성, 모든 별칭이 일치하는 양성 1개. 테스트는 **메모리 HTTP stub만 사용**, 실제 G2B 호출 0, Worker dispatch 0, 투찰 0.
- **실제 GitHub Actions:** [공식 단일 편집기·읽기 전용 노드 회귀 #41247707108](https://github.com/lyonbegin/procureflow/actions/runs/41247707108) **SUCCESS**, job 로그 `PROCUREFLOW_RESPONSE_IDENTITY_ALIAS_FAIL_CLOSED_PASS`, **Node 39/39 PASS**, 15개 모순 차단·일치 응답 HOLD 확인. [오프라인 S01~S10 #41247707105](https://github.com/lyonbegin/procureflow/actions/runs/41247707105) **SUCCESS**.
- **동일 SHA의 나머지 Docker/공식 Chrome/Pan/43블록/104 API/native S01~S10/PF15/Main-Worker 검증:** 해당 시점 일부 진행/대기 중. 결과를 확인하기 전 PASS라고 보고하지 않는다.
- **기존 owner/readiness:** [읽기 전용 CI #41247707093](https://github.com/lyonbegin/procureflow/actions/runs/41247707093) **FAIL**, 이전부터 존재한 `EDITOR_BLOCKED_UNCLAIMED_OWNER` 장애. 운영 owner/DB를 수정하지 않는다.
- **필수 미완료:** 35종 실행 어댑터, 43개 실제 업무 핸들러·payload, 정확한 10년 개찰·낙찰 공식 전수, 80개 디버깅 런타임 전수, 운영 owner/DB/키 호환성 및 명시적 승인. **Issue Open / PR Draft·미병합 / 전체 완료 통보 금지**.


## 2026-11-01 KST — 공식 8자리 월별 수집 완료 집계의 누락 totalCount 스냅샷 차단 (**전체 완료 아님**)

- **원인:** `scan_month()`의 완료/재개 경로는 이미 공식 API `expected_total` 스냅샷을 필수로 검증하지만, **읽기 전용** `summarize_month_cursor()`는 `expected_total` **필드 자체가 없으면** 검사 없이 `cursor_valid=true`를 허용했다. 이전 스키마의 완료 월 121개를 공식 API 총건수 확인 없이 `eight_digit_notice_discovery_complete=true`로 인증할 수 있는 불일치였다. `partial`의 `checked>0`도 스냅샷 필드가 없으면 같은 허점이 있었다.
- **브랜치 전용 패치:** [집계기 fail-closed `af9dac1`](https://github.com/lyonbegin/procureflow/commit/af9dac1b98f5005dcb47b045d883f2c13801ad16) · [7개 누락/null 스냅샷 격리 회귀 `eecfa73`](https://github.com/lyonbegin/procureflow/commit/eecfa7395c4dc806cddddec0ad01503f4d3745ee) · [불필요한 분기 제거 `ee7d961`](https://github.com/lyonbegin/procureflow/commit/ee7d961441c2ef8678cbe7da4e07de6960dbd585).
- **변경 효과:** 완료 월은 `expected_total == checked`가 **실제 저장돼 있어야만** 검증 통과. 500건 이상 수집한 부분 월은 `expected_total > checked`를 요구. 누락/NULL/불일치 시 `invalid_cursor_rows`에 집계하고 전체 8자리 공고 발견 완료를 차단. 기존 121개월 시험 fixture는 공식 0건 스냅샷을 명시해 올바른 양성 검증을 유지.
- **실제 격리 CI:** [G2B 104 API + Node Lab #41254301221](https://github.com/lyonbegin/procureflow/actions/runs/41254301221) **SUCCESS**, [실제 job 로그](https://github.com/lyonbegin/procureflow/actions/runs/41254301221/job/124694088078) **281 passed / 3 warnings**. [S01~S10 오프라인 #41254301236](https://github.com/lyonbegin/procureflow/actions/runs/41254301236) SUCCESS; [50종/43블록 #41254301262](https://github.com/lyonbegin/procureflow/actions/runs/41254301262) SUCCESS.
- [기존 공식 n8n owner/readiness #41254301232](https://github.com/lyonbegin/procureflow/actions/runs/41254301232) **FAIL**: 읽기 전용 실측 `ownerSetupRequired=true`, `/setup=403`, `/rest/workflows=401`, `EDITOR_BLOCKED_UNCLAIMED_OWNER`. 기존 owner/DB/인증키는 변경하지 않음.
- 동일 최신 SHA의 공식 Docker/Chrome/Pan/native 시나리오/Main-Worker/PF15 CI는 **별도 완료 확인 전까지 PASS로 보고하지 않음**.
- **남은 필수 수용검사:** 35종 미지원 실행 매핑, 43개 실제 업무 핸들러·정식 payload, 정확한 10년 공식 개찰·낙찰 전수 및 Worker fencing, 별도 디버깅 80개 런타임 전수, 운영 owner/DB/키 호환성·명시적 승인. 이번 수정은 **8자리 공고 발견 집계의 거짓 완료 방지**이며 10자리 실제 개찰·낙찰 완전성 증명이 아니다.
- **불변:** 운영 `main`, Railway 운영 서비스/DB, 자격증명, 실제 G2B 호출/Worker dispatch/투찰 변경 없음. Issue #21 Open, PR #22 Draft·미병합. 전체 완료 통보 금지.


## 2026-11-01 KST — n8n 증빙 객체 순환/공유 참조 fail-closed (전체 완료 아님)

- **발견한 결함:** `hasUnsafeNestedDispatchClaim()`는 `WeakSet`에 이미 있는 객체를 `continue`로 건너뛰었다. JSON에서 표현할 수 없는 **순환 참조** 또는 서로 다른 경로가 같은 객체를 공유하는 비정상 메모리 그래프가 들어오면 증빙/업스트림 입력이 정상 JSON인지 검증하지 않은 채 계속 진행할 수 있었다.
- **기능 브랜치 패치:** [`43ab12f`](https://github.com/lyonbegin/procureflow/commit/43ab12f9817f7a1a44fcae731253fd85d4b70da7) — 재방문 객체는 증빙 검사에서 **즉시 fail-closed**. 정상 JSON 트리 구조에는 영향이 없다. [`076a5f9`](https://github.com/lyonbegin/procureflow/commit/076a5f986342e785e46882d017f7402a89dd832e) — 순환 입력·공유 객체·후행 배치 아이템을 **HTTP 요청 전에** 차단하고, 순환 HTTP helper 응답이 증빙 인증으로 승격되지 않으며 정상 JSON HOLD는 유지됨을 검증.
- **같은 코드 HEAD의 실제 GitHub Actions:** [공식 단일 편집기/Node 회귀 #41284342540](https://github.com/lyonbegin/procureflow/actions/runs/41284342540) **SUCCESS**, [Node job #124782486672](https://github.com/lyonbegin/procureflow/actions/runs/41284342540/job/124782486672) **41/41 PASS**. 로그 `PROCUREFLOW_NON_JSON_REFERENCE_GRAPH_FAIL_CLOSED_PASS`: 비정상 upstream 3건·비정상 response 1건 차단, 정상 합성 HOLD에만 메모리 HTTP stub 1건, 외부 HTTP/Worker/투찰 **0**.
- [50종/43블록 계약 #41284342670](https://github.com/lyonbegin/procureflow/actions/runs/41284342670), [G2B 104 API Node Lab #41284342659](https://github.com/lyonbegin/procureflow/actions/runs/41284342659) (**361 passed/3 warnings**), [S01~S10 오프라인 #41284342677](https://github.com/lyonbegin/procureflow/actions/runs/41284342677) **SUCCESS**.
- **기존 운영 owner/readiness [#41284342683](https://github.com/lyonbegin/procureflow/actions/runs/41284342683) FAIL:** 기존 `EDITOR_BLOCKED_UNCLAIMED_OWNER` 유지. 계정/DB/자격증명 변경 없이 읽기 전용으로만 진단.
- 같은 코드 HEAD의 [격리 공식 Docker/Chrome #41284342634](https://github.com/lyonbegin/procureflow/actions/runs/41284342634), [Pan #41284342756](https://github.com/lyonbegin/procureflow/actions/runs/41284342756), [native S01~S10 #41284342607](https://github.com/lyonbegin/procureflow/actions/runs/41284342607), [PF15 #41284342621](https://github.com/lyonbegin/procureflow/actions/runs/41284342621), [Main/Worker 격리 #41284342650](https://github.com/lyonbegin/procureflow/actions/runs/41284342650)은 이 기록 시점 일부 진행 중으로 **PASS 선판정 금지**.
- **남은 필수 수용:** 35종 미지원 노드 실행 매핑, 43개 실제 업무 핸들러/엄격 payload, 정확한 10자리 세부품명 기준 공식 10년 개찰·낙찰 전수, 별도 디버깅 80개 런타임 전수, 운영 owner/DB/키 호환성·명시적 승인. **Issue #21 Open / PR #22 Draft·미병합 유지**. 운영 `main`, Railway 운영 서비스·DB, 자격증명, 실제 G2B API 호출/Worker dispatch/투찰 변경 없음.


## 2026-11-01 KST — 공식 G2B 응답 body 오류 마커와 성공 헤더가 공존할 때 월 완료 오인 차단 (**전체 완료 아님**)

- **결함:** `g2b_case_10y_official._parse()`는 `header.resultCode="00"`, `body.totalCount=0`, `body.items={"item":[]}`인 응답의 **body 자체**에 `error`/ `errorMessage`/ `fault` 등이 추가돼도 빈 결과 월을 `completed`로 처리할 수 있었다. 이전 수정은 `body.items` 내부의 오류 필드만 차단했기 때문에 서로 다른 레벨의 실패 신호가 누락됐다.
- **기능 브랜치 전용 코드:** [파서 수정 `3fa9341`](https://github.com/lyonbegin/procureflow/commit/3fa9341881ce592423b132f88f40533546496c06) — `body`에 알려진 오류/결함 마커 8종이 존재하면 `ValueError("g2b_api_body_error_marker")`로 차단. 명시적으로 비어 있거나 null이어도 차단하며, 비객체 body도 거부한다. 정상 `pageNo`/`numOfRows` 응답은 유지한다.
- **격리 회귀:** [테스트 `f1f66c7`](https://github.com/lyonbegin/procureflow/commit/f1f66c72c7d9a35b43d0458ac430e35b397ba186) — 8종 body 오류 마커 × 3개 값 × `totalCount=0/1` **48건**, 비객체 body **4건**, 정상 pagination **1건** = 신규 **53건**. FakeHTTP/FakeDB만 사용하고 오류 시 월 history INSERT **0건**을 검증. 운영 G2B API·Railway DB·Worker·실제 투찰 접근 없음.
- **실제 CI [G2B 104 API + Node Lab #41289328860](https://github.com/lyonbegin/procureflow/actions/runs/41289328860): SUCCESS**, [pytest job #124797099155](https://github.com/lyonbegin/procureflow/actions/runs/41289328860/job/124797099155) **414 passed / 3 warnings**. [S01~S10 오프라인 #41289328744](https://github.com/lyonbegin/procureflow/actions/runs/41289328744), [50종/43블록 계약 #41289328760](https://github.com/lyonbegin/procureflow/actions/runs/41289328760), [단일 공식 편집기 #41289329045](https://github.com/lyonbegin/procureflow/actions/runs/41289329045)도 **SUCCESS**.
- **운영 owner/readiness [#41289328801](https://github.com/lyonbegin/procureflow/actions/runs/41289328801) FAIL:** 읽기 전용 확인 `ownerSetupRequired=true`, `/setup=403`, `/rest/workflows=401`, `EDITOR_BLOCKED_UNCLAIMED_OWNER`. 관리자·DB·키는 변경하지 않았다.
- **같은 SHA의 공식 Docker/실제 Chrome 후보 [#41289328743](https://github.com/lyonbegin/procureflow/actions/runs/41289328743), Pan [#41289328843](https://github.com/lyonbegin/procureflow/actions/runs/41289328843), native S01~S10 [#41289328964](https://github.com/lyonbegin/procureflow/actions/runs/41289328964), Main/Worker 격리 [#41289328763](https://github.com/lyonbegin/procureflow/actions/runs/41289328763), PF15 [#41289328948](https://github.com/lyonbegin/procureflow/actions/runs/41289328948)**은 기록 시점 일부 진행 중이므로 최종 PASS를 선판정하지 않는다.
- **미완료:** 35종 미지원 실행 매핑, 43개 실제 업무 핸들러·엄격 payload, 공식 10자리 세부품명 기준 10년 개찰·낙찰 전수, 별도 디버깅 80개 런타임 전수, 운영 owner/DB/키 호환성·명시적 승인. **Issue #21 Open, PR #22 Draft·미병합 유지.**
