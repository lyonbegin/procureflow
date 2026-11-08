# ProcureFlow 9단계 수집 우선 운영 규약 (2026-11-08)

## 결정 사항
- 기존 공용 `shared-n8n-studio` Vue Flow/9개 상위 노드 및 43개 기존 세부 업무 블록 유지.
- **N01~N08은 수집·원본 저장·출처 정리만 수행**. 업체 적격성, 경쟁업체 예측, 원가평가, 가격 추천, 입찰 여부 판단과 Word 제안서 작성 금지.
- **N09에서만** 공식 원본 HWP/PDF/HWPX를 GitHub Actions Runner에 읽어 SHA-256 검증 후 AI API로 종합 판단. 자동 투찰/전자서명/입찰 버튼 실행 없음.
- 각 노드는 GitHub Actions 별도 실행. Railway는 제어, 결과 상태, 원본 보관만 담당하며 Chromium 미설치.
- 원본 증거·API 호출이 누락되면 검증 완료로 위장하지 않고 `gaps`에 기록. 부분 수집 상태라도 다음 노드의 가능한 수집을 이어감.
- N02는 기존 공식 첨부 엔드포인트의 원본 바이트를 보존. N03~N08에서 원본문서 내용 자체를 읽지 않음.

## 노드별 실제 코드
| 단계 | 기능 | GitHub Actions 코드 |
|---|---|---|
| N01 | 나라장터 최신 미완료 공고 자동 선정 | `github_node_worker.py` → `live_nine_test._official_g2b_search` |
| N02 | 원본 파일 전체 수집 및 SHA·manifest | `github_node_worker.py` → `n02_collect.collect` |
| N03 | 공식 공고의 기관/분류/금액/계약방식 및 10자리 세부품명 필드 조회 | `collect_only_stages.n03_metadata` |
| N04 | 최근 3년 시작, 서로 다른 공식 과거공고 50건 미만일 때 1년씩 확대(최대 10년), 8자리 물품분류 우선·미확보 시 출처가 있는 후보검색 | `collect_only_stages.n04_history` |
| N05 | N04의 과거 후보 50건에 대한 공식 개찰 목록 조회 → 정확히 일치하는 목록 행의 개찰차수·진행차수·업무구분·상태로 업체별 상세 투찰 원본 수집 | `collect_only_stages.n05_openings` |
| N06 | 첨부 원본·기관·공급·인력 근거자료 출처 목록 정리 | `collect_only_stages.n06_supply_catalog` |
| N07 | 공식 예산·기초금액·과거 개찰 등 가격 근거 필드 수집 | `collect_only_stages.n07_price_sources` |
| N08 | 원본 순번/SHA 및 수집 JSON과 누락 출처를 AI 전달 구조로 통합 | `collect_only_stages.n08_handoff` |
| N09 | 원본문서 읽기·출처 매핑·AI Responses 호출 및 최종 종합보고 | `n09_final_ai.evaluate` |

## 실제로 검증된 항목
- GitHub Actions `collection-first-nine.yml`: 수집 전용 12개 테스트 및 공유 실행 컨트롤러 9개 테스트 PASS.
- 같은 GitHub Runner에서 G2B `R26BK01816186-000` 상세번호 직접 검색: 공고기관 등 공식 속성 확인. **해당 목록 응답에 10자리 세부품명 정보는 제공되지 않음**.
- N03는 이 경우 `partial`과 `official_10_digit_detail_class_not_verified`를 출력. N04는 10자리 번호를 필수로 요구하지 않으며, 최근 3년에서 시작하여 중복 제거 후 50건 미만이면 1년씩 확대(최대 10년). 분류번호가 없으면 공식 공고명 기반 후보로만 저장함.
- N05는 실제 개찰 목록과 업체별 투찰 상세 엔드포인트를 분리해서 조회함. 목록에 없는 공고에는 임의의 개찰완료 상태·분류·차수를 넣지 않으며, HTTP 422는 공식 원문 사유가 확인되지 않으면 미확인 오류로 남김. 상세 투찰 1행은 실제 개찰완료 공고 R26BK01813690-000에서 확인함. 이를 확정 낙찰자나 전체 50건 수집으로 주장하지 않음.
- N06·N07의 독립 견적/인력/낙찰하한율 자료 연결은 **미완료**. 확보하지 못한 출처를 `gaps`에 기록.
- N08은 AI를 호출하거나 문서 초안을 작성하지 않음.
- N09 API 키/모델/옵트인이 모두 없으면 `N09_AI_API_NOT_CONFIGURED`와 `ai_evaluation_performed:false` 출력. AI 종합 분석 수행 사실을 꾸미지 않음.

## 운영 시작 인증
Railway 환경 변수 `PROCUREFLOW_GITHUB_DISPATCH_TOKEN` 필요 (Github `lyonbegin/procureflow` Actions: Write, 개인 키 유출 금지). 이 토큰이 없으면 **실행 버튼 비활성화**, Railway Python 직접 수집으로 대체하지 않음.

N09는 GitHub Actions `OPENAI_API_KEY` secret와 `PROCUREFLOW_AI_MODEL` variable, `PROCUREFLOW_AI_ENABLED=1` variable이 필요. API 외부 전달 전에 개인정보·민감한 회사 자료 사용 동의를 별도로 확보해야 하며, 보고는 사람이 검토해야 함.

## 인프라 및 비용 제한
- 현재 Railway 첨부 파일은 볼륨 용량 상한이 있으며, 10년 전수 대량 데이터는 별도 오브젝트 스토리지·증분 수집·다중 파티션을 추가해야 함.
- N04는 최초 3년을 각각 연도별 검색하고 누적 고유 공고 후보가 50건 미만이면 한 번에 1년씩 과거로 확대함(최대 10년). 실제 조회 연도와 페이지, 50건 충족 여부 및 검색 누락은 `gaps`에 기록. 50건은 과거자료 수집 목표이지 관련성·낙찰확정 판정이 아님.
- N05는 최대 50건의 역사 후보에 대해 공식 목록과 상세를 조회. 정확한 목록 행이 있으면 응답의 bidClsfNo, bidPrgrsOrd, prcmBsneSeCd, bidPgstCd로 투찰 상세를 조회하고, 개찰 목록·투찰행·유찰/미조회·HTTP 오류를 각각 기록. 실제 개찰완료 공고 R26BK01813690-000에서 목록 1행·투찰상세 1행 N05 전체 경로 verified를 검증. 확정 낙찰 증빙은 별도.
- 중간 노드의 `verified`는 **수집 응답/무결성 검증 완료**이지 업체 적격·가격전략·입찰 승인 성공이 아님.
