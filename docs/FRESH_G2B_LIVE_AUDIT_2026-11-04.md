# Fresh G2B 실운영 검증 및 다음 수정 기준 (2026-11-04 KST)

## 판정
- 대상: `feature/fresh-g2b-official-crawl-isolated-20261104`, 배포 SHA `456f97c5d7923fdad8f97c1fc1018d6b98b93731`.
- Railway 별도 프로젝트: `procureflow-fresh-g2b-official`; 서비스 `fresh-g2b-site-center`, 독립 `Postgres`.
- 운영 `/health`: `status=ok`, `isolated_new_db=true`, `old_db_access=false`, `new_db_notices=0`, `official_site_search_live_proven=false`.
- 운영 `/api/fresh/notices`: `items=[]`.
- 운영 `/api/fresh/recent-jobs`: 6건 모두 `status=blocked`, 각각 `rows_seen=0`, `rows_saved=0`.
- 최신 실패: `OFFICIAL_BID_SEARCH_UNVERIFIED_G2B_OFFICIAL_SITE_RENDERED_EMPTY`.
- Railway 실제 런타임 로그: G2B 홈 title '나라장터'까지 관찰했지만 `body=""` 및 `controls=[]`; 마지막 검색에서 `FRESH_SITE_JOB_FAILED ... SourceBlocked`.
- `fresh_g2b_api.py`에서 search/opening/files는 별도 POST이며 원클릭 전체 파이프라인은 아님.
- `files` 작업은 `found["files"][:10]`까지만 다운로드를 시도하고, 하나 이상 성공해도 완료 처리할 수 있음. 최종 기획의 '첨부 전량' 조건 미달.
- 기존 데이터가 연결되지 않도록 `fresh_g2b_store.initialize`에서 `procureflow.tenders` 존재를 차단함. 이는 해당 스키마 접근 방어 증거이며 모든 시스템의 기존 DB 데이터 물리 삭제 증명은 아님.
- DB/화면 배포 성공과 10자리 검색, 10년 개찰·투찰·낙찰 전수 및 104개 기능의 운영 증빙은 분리 판정.

## 수정 우선순위 / 합격 조건
1. 실제 나라장터에서 입찰공고 검색 화면과 정확한 10자리 검색 필드 및 XHR 전송 경로를 직접 확인한다. 브라우저 렌더링 장애는 화면/프레임/요청 로그로 원인을 구분한다. 기존 DB/8자리/타이틀 추정으로 대체하지 않는다.
2. 10자리 필드·기간이 포함된 검증된 검색 요청과 실제 원본 결과 최소 1건을 신규 DB에 넣고, source endpoint/원본 응답 SHA/검색 페이지/수집시각을 함께 확인한다.
3. 선택 공고 원본·첨부 목록 전체 확보: 발견 건수 = 성공 + 실패 + 미처리, 부분 실패가 있으면 전체 상태는 PARTIAL/HOLD. 모든 파일의 SHA-256과 출처를 기록한다.
4. 공식 공고에서 검증한 정확한 10자리로 과거 10년 월별·페이지별 순회, 구형·신형 공고번호와 재입찰 집행차수를 구분한다. 전 기간 coverage가 입증되기 전 '전수 완료'를 표기하지 않는다.
5. 실제 개찰/투찰/확정 낙찰을 새 DB에 저장하고 미발표/무응답/유찰을 서로 구분한다. 확정 증빙 없는 1순위를 낙찰자로 판정하지 않는다.
6. 신규 DB의 실제 원본으로만 발주기관·반복 참가·투찰률·유찰 변화를 분석한다. 경쟁업체 예측은 관측과 추정을 분리한다.
7. PF00~PF15/n8n 연동과 104 기능 실행 증빙은 별도 합격 판정; 현재 Fresh UI의 검색/개찰/파일 단일 기능을 전체 실행으로 표시하지 않는다.

## 검증 URL
- https://fresh-g2b-site-center-production.up.railway.app/health
- https://fresh-g2b-site-center-production.up.railway.app/api/fresh/recent-jobs
- https://fresh-g2b-site-center-production.up.railway.app/api/fresh/notices
- https://github.com/lyonbegin/procureflow/tree/feature/fresh-g2b-official-crawl-isolated-20261104

이 문서는 현재까지 확인된 실운영 점검 결과만 기록한다. 나라장터 실데이터 성공이나 10년 전수 완료를 주장하지 않는다.
