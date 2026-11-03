# 공공입찰 한 건 실데이터 검색 우선 실행 — 2026-11-03

## 최종 변경 원칙
사용자가 원하는 핵심은 신규 공고 한 건 → 원본·첨부 일괄 확인 → 기간·세부종목·기관으로 과거 개찰·낙찰 검색 → 실제 경쟁·가격·자격 분석 → 필요한 제출서류 준비 → 사람 결정이다.
기존 104개 F001~F104는 별도 독립 수집기를 104회 실행하는 대상이 아니라 원본 데이터에서 확인할 세부 계약이다. 이 브랜치는 **공공입찰(A)만 수정**한다. 민간 SW 개발(B)과 인력용역(C)은 기존 코드 그대로다.

## 실제 배포 링크
- **실데이터 9단계 공공 준비실:** https://procureflow-api-production.up.railway.app/public-search
- **기간·정확한 10자리·기관·결과 종류 검색 API:** https://procureflow-api-production.up.railway.app/api/g2b/public/selected/search?start=2016-10-24&end=2026-10-22&detail10=8111159901&kind=opening&limit=50
- **기존 실제 가격·원가:** https://procureflow-api-production.up.railway.app/api/g2b/full/price
- **기존 실제 공고·증빙·서류 초안:** https://procureflow-api-production.up.railway.app/api/g2b/full/proposal
- **기존 실제 원본 기반 검토 초안 DOCX:** https://procureflow-api-production.up.railway.app/api/g2b/full/proposal.docx
- **Studio 공공입찰 관리:** https://procureflow-n8n-native-canvas-production.up.railway.app/admin/index.html?section=public
- **개발 PR:** https://github.com/lyonbegin/procureflow/pull/27
- **CI PASS:** https://github.com/lyonbegin/procureflow/actions/runs/41640414333

## 실제 업무 코드 변경
- `g2b_search_first.py`: 기존 `procureflow.tenders`, `g2b_case_documents` 에서 각각 1회 DB 조회 후 캐시된 원본을 재사용. `g2b_case_outcome_verification`, `g2b_notice_categories`, `g2b_case_10yr_history`, `bid_results`를 **정확한 10자리 공식 원본 검증 코드 + 날짜 필터 + 기관(선택) + opening/award** 조건으로 SQL 조회한다. LIMIT/OFFSET 페이지 처리. 121개월 등록 또는 전체 기간 원본 일괄 다운로드 없음.
- 공고 `R26BK01787028/000` 의 실제 게시일 `2026-10-22` 이후 결과가 과거 데이터 분석에 유입되지 않도록 비교 시점 차단.
- `main.py`: `GET /api/g2b/public/selected/search`는 실제 DB만 읽음. `POST /api/g2b/public/selected/search/collect`는 기존 `ADMIN_TOKEN`을 요구하며 고정된 선택 공고·10자리·기간·기관·최대 3개만 `g2b_filtered` Worker 작업으로 등록.
- `worker.py`: 기존 Worker에 `g2b_filtered` 경로만 추가, 기존 `g2b_bid_collector.collect(bid_numbers=...)` 를 호출해 **번호가 일치하는 공개 개찰 상세만 수집**한다. 공식 문서상 10자리 원본 검증 없는 후보는 넘기지 않는다.
- `g2b_bid_collector.py`: `bid_numbers` 로 선택 조회 시 기존 전체 개찰 이력 정리·삭제 함수가 다른 건에 영향을 주지 않게 건너뛴다. 일반 공고목록 동기화에는 기존 로직 보존.
- `g2b_search_first.py` 의 `_save_filtered_attempts`: 성공·자료없음·오류를 기존 `g2b_case_outcome_attempts` 에 기록, 최근 12시간 중복 조회 제외. 공식 확정 낙찰은 명시적 G2B 최종 낙찰 원본 없는 경우 생성하지 않음.
- `g2b_bid_package.py`: 공급업체 견적이 필요한 외주형 사업은 검증된 견적 요구. **회사 자체 수행**이며 공식 근거로 승인된 `cost_breakdown.execution_model='self_performed'|'in_house'`와 `labor_krw>0` 가 있으면 외부 공급업체 견적을 강제하지 않는다. 실제 원가와 자격 증빙이 없으면 여전히 BLOCKED.
- `static/public-search.html`: 현재 선택 공고 실제 원본·첨부 4개, 조건별 개찰업체·투찰금액·순위, 기존 가격·자격·서류초안, HOLD 근거를 한 화면에서 조회하며, 관리자 토큰 입력 시에만 기존 Worker 한정 수집 요청.

## 운영 관측(실데이터, 모의 아닌 실제 DB)
- 선택 공고: `R26BK01787028/000`; 실제 공고명 `철강·금속 인공지능전환(AX)실증센터 스마트 실증장비 모니터링 시스템용 소프트웨어 개발 용역`, 발주 `재단법인전남테크노파크`, 게시 `2026-10-22`, 마감 `2026-10-29 10:00`.
- 실제 브라우저에서 필터 `8111159901`, `2016-10-24..2026-10-22`, `opening` 적용해 **정확한 원본 10자리 일치 공고차수 67건, 실제 개찰 기록 262행, 확정 낙찰 0건** 확인. 이는 조건부 결과이며 10년 전수 완료 수치가 아님.
- 기존 실제 공고 첨부 4개: HWP 공고문·과업지시서·XLSX 공내역서·PDF 공고문. SHA256 및 추출 텍스트 원본 재사용.
- 실제 수집 시험: 기존 Worker에 `g2b_filtered` 작업 ID **1709** 1건 등록, 공식 원본 10자리 검증을 통과한 `R26BK01777010/000` 을 실제 G2B 웹에서 직접 조회. G2B 개찰 상세가 비공개/미제공이라 `completed_partial`, 신규 0건, 확정 낙찰 0건; 모의 결과 없음. 임시 작업 등록용 Railway Function은 삭제. 이 시험에서 발견된 반복 미공개 조회의 문제를 후속 커밋에서 기존 감사 테이블 `g2b_case_outcome_attempts` 기록으로 개선했으며 그 후속 코드의 개별 실G2B 호출 재시험은 미수행.
- 기존 공식 공공데이터 API 키 미설정 시 별도의 미수집 기간은 차단되며, 기존 확보 자료만 사용한다.

## 검증·운영 경계
- GitHub Python/Node 소스 검사 PASS. 실제 API + 원본 DB 검색과 브라우저 날짜/종목/종류 필터 확인.
- 원가·참가자격 원본 미흡이면 `blocked`/`unknown` 표시, 승인 투찰가격 없음. 개찰 1순위는 확정 낙찰로 승격하지 않음.
- 이 구현은 **운영 원본 API·기존 Worker 기반**이다. 새로운 모의 데이터, 별도 DAG 실행기, n8n 신규 계정·설치, 실제 입찰참가·제출은 하지 않았다.
- 기존 공식 n8n의 PF00~PF15 워크플로 노드를 9개로 병합·실행한 것은 아니다. 기존 앱은 계속 실행 가능하고 새 API·Worker·실무 화면이 추가된 상태. 기존 공식 n8n Execution ID 연결과 실제 서류 최종 완성은 별도 검증 필요.

## 관리 설정
- API Railway service `procureflow-api`, Worker `procureflow-worker`에 `feature/public-search-first-real-20261103` 소스 연결. 운영 DB 초기화 없음. 기존 Studio는 `feature/public-single-tender-104-integration-20261103`에 새 실데이터 페이지로 가는 링크만 추가.
- 실제 운영 데이터 검색은 GET으로 즉시 수행, 부족한 결과의 추가 수집은 관리자 POST 요청(건별 최대 3건)으로만 수행.
