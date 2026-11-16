# ProcureFlow 최근 2년 조달 원본·독립 테이블·JOIN 검증 기준 (2026-11-16)

> **현행 확정 범위: 최근 2년만. 12년 시장발견·백필·분석 계획은 폐기/보류하고 이 작업에 적용하지 않는다.** 이전 문서의 12년 언급은 사용자의 확정 지시에 따라 철회한다.
>
> 현재 존재하는 930,379개 공고 키(검증된 721일)와 187쌍 Stage 2 Release 보존 자산은 **재수집하지 않는다**. 미검증 10일도 임의 재검색 금지. 실제 ZIP/원본 내용을 재검사하는 작업은 별개. PC self-hosted Runner 재개 금지, GitHub-hosted ubuntu-latest/Xvfb 이용 유지.
>
> 여기서 '공식 보고서 확인'은 공공데이터포털의 보고서 메타데이터 확인에 불과하다. 실제 웹 원본 다운로드·2년치 완전성·행 수·SHA256 재검증과 혼동하지 않는다.

## 독립 데이터 엔터티

| 테이블 | 기본 grain/키(원본에 실제 있는 경우만 확정) | 주된 원본·주의 |
|---|---|---|
| notice_rounds | (공고번호, 공고차수, 분류번호, 집행회차) | 기존 notice queue; 정정과 재공고/재입찰을 별도 보존 |
| opening_results | 위 집행 키 + 개찰 결과/상태/일자 | 나라장터 개찰 웹 원본 |
| bid_participations | 집행 키 + 업체공식식별자 + 실제 투찰행 식별 | 기존 Stage 2 `bidders.csv` + `raw_*.json.gz`; 다중 투찰/무효/취소 보존 |
| award_results | 집행 키 + 최종 선정 결과 버전 | 나라장터 낙찰자선정 원본; **개찰 1순위 ≠ 최종 낙찰자** |
| contracts | 계약번호 + 계약차수/버전 | 체결일·금액·상대방·방법; 낙찰 Y ≠ 계약체결 |
| private_contract_details | 계약 키 FK + 수의계약 사유·견적 방식 | 수의계약은 `contracts`의 유형/하위 상세, 계약금액 별도 중복 합산 금지 |
| contract_partners | 계약 키 + 업체키 + 역할/업종 | 공동수급 대표·구성사·지분; 복수업종 지분/금액 중복 합산 금지 |
| contract_changes | 계약 키 + 변경 버전 | 정정·증감·취소, 원본 버전별 이력 |
| delivery_orders | 납품요구번호 + 변경차수 | MAS/단가계약 납품요구, 계약번호와 별도 FK; **납품요구 ≠ 실제 검수·납품 완료** |
| delivery_order_items | 납품요구 키 + 품목순번 | 품목/수량/단가/요구금액 |
| suppliers | 공개된 공식 업체식별값 | 업체명만으로 서로 다른 사업자를 병합 금지 |
| supplier_registration_history | 업체키+등록정보/유효시점 | 업체등록/면허업종/공급물품/제재; 현재 상태가 과거 상태라는 가정 금지 |
| procurement_links | from_type/from_id/to_type/to_id + 검증근거 | 낙찰→계약, 재공고→최초공고, 유찰→수의계약 등 명시적 관계. 근거 없으면 미연결 |
| source_evidence | 원본 URL+수집시각+해시+파서버전+페이지/상태 | raw 원본/정규화/누락/오류의 공통 감사 계층 |

정확한 JOIN은 **공고번호만이 아니라 공고차수·입찰분류번호·집행회차**를 고려한다. 계약은 계약번호/차수로 별도 식별하고 공고와의 연결 근거를 기록한다. 업체 연결은 공식 식별값과 기준시점을 사용한다. NULL 키로 억지 JOIN하거나 회사명/금액/일자 유사성만으로 계약 연결하지 않는다.

## 최근 2년 추가 확인/수집 대상 — 웹 보고서 우선, API키 전제 아님

| 우선 | 공식 보고서 URL | 원본 분류 | 실제 다운로드 |
|---|---|---|---|
| 1 | [입찰공고 기업별 투찰 및 계약내역](https://www.data.go.kr/data/15050832/fileData.do) | 투찰/개찰순위/낙찰선정/계약 일부 대조; 투찰 없는 계약 제외 명시 | 미검증 |
| 2 | [업무별 구성원별 계약 내역](https://www.data.go.kr/data/15159123/fileData.do) | 전체 계약 및 공동도급 구성원; 3개월 이상 무조건 단일 조회 시 지연 경고 | 미검증 |
| 3 | [조달업체 등록 내역](https://www.data.go.kr/data/15053474/fileData.do) | 업체 식별/지역/등록; 여러 업무등록 시 업체 중복, 폐업·취소 업체 제외 | 미검증 |
| 4 | [조달업체 면허 업종 등록 내역](https://www.data.go.kr/data/15053476/fileData.do) | 면허·업종·시공능력평가액; 과거 스냅샷 여부 별도 검증 | 미검증 |
| 5 | [나라장터쇼핑몰 납품요구 물품 내역](https://www.data.go.kr/data/15053481/fileData.do) | 납품요구번호·변경차수·품목·계약번호·업체·금액; 실제 검수와 분리 | 미검증 |
| 6 | [조달업체별 계약방법별 계약납품요구 실적통계](https://www.data.go.kr/data/15050792/fileData.do) | 일반/제한/지명/수의 계약 건수·금액 교차검증 | 미검증 |
| 7 | [조달업체별 업무구분별 계약납품요구 실적통계](https://www.data.go.kr/data/15050793/fileData.do) | 물품/공사/용역별 업체 실적 대조 | 미검증 |
| 8 | [계약방법별 월별 계약납품요구 실적통계](https://www.data.go.kr/data/15050806/fileData.do) | 월별 계약/납품 금액 독립 통계 대조 | 미검증 |

확인된 공식 웹 경로: `https://www.g2b.go.kr/` (개찰·낙찰), `https://data.g2b.go.kr/` (웹 보고서), `https://shop.g2b.go.kr/` (MAS/단가/납품요구). 공개 웹 화면/파일 출력 기능을 우선 검증하고, 개별 화면 SSO·로그인·접근제한은 명시한다. **공공데이터포털 OpenAPI와 ServiceKey를 필수 경로로 사용하지 않는다.** 웹 화면의 허용 기간/페이지는 개별 실제 응답으로만 판정한다.

## 현존 코드와 검증에서 발견한 불일치

- `lyonbegin/hitel-scribd-runner/tools/procureflow/g2b_bidder_detail_stage2_recovery.py`: 원본 페이지 `raw_%05d.json.gz`, 업체행 `bidders.csv`, `status.json`을 생성. 행에는 `bid_no,bid_ord,bid_clsfc_no,bid_prgrs_ord,bidder_name,business_no,rank,bid_amount,bid_rate,qualified,remarks,bid_time,evidence_page`가 있다. JSON/페이지 SHA 검증 로직이 있으나 Release 전체 재검증 결과와는 별개.
- `lyonbegin/hitel-scribd-runner/tools/procureflow/g2b_stage2_tenworker_supervisor.py`: ZIP 보존·status manifest 업로드. `award_linkage_verified: false`, `excel_integration_verified: false`로 기록.
- `lyonbegin/procureflow/g2b_final_award_collector.py`: 상태코드 `입160010` 및 실제 `sfbrSlctnRsltCd == '낙찰'`을 확인하며 개찰 1순위만으로 최종 낙찰 간주 금지.
- **주의**: `lyonbegin/procureflow/db.py`의 `procureflow.bid_results`는 현재 `result_kind`로 개찰/낙찰 데이터를 같은 테이블에 저장하도록 정의됨. 요청된 물리적 독립 테이블 구조에 맞지 않음. 향후 새 스키마/마이그레이션 및 기존 데이터를 보존한 단계적 전환이 필요. 실제 운영 DB의 적용 상태는 확인되지 않음.

## 반드시 통과할 실데이터 검증

1. 원본 2개 GitHub Releases, 187개 ZIP·187개 상태파일의 실제 다운로드 → ZIP CRC, 파일 바이트수, SHA256 독립 계산; GitHub digest 메타데이터만으로 실검증 성공 표시 금지.
2. 저장된 930,379 공고키 중 721 검증일의 데이터만 기존 자료에서 비교; 상세 상태는 `verified_complete`/`no_opening_data`/`error`/`partial_page_limit` 등으로 각각 집계. **파일이 187개라는 것과 공고 상세가 전부 유효하다는 것은 다름**.
3. 원본 각 페이지의 총건수·끝페이지·연속 페이지·반복 행 검사; 모든 업체 투찰행의 복합키 중복/결측 처리; 0건과 수집실패를 분리.
4. 개찰→낙찰→계약→납품요구의 행수/금액을 각 다른 grain으로 계산하여 중복합산 금지; 미연결은 미연결로 남겨두기.
5. 수의계약·유찰·무응찰·공동수급·변경계약·MAS에 대한 단독 샘플 검증; 투찰 기반 자료만으로 완전성 선언 금지.
6. 공식 보고서와 최근 2년 월·기관·업무구분별 집계 교차대조; 원본의 날짜 기준(공고일/개찰일/계약일/납품요구일) 다름 명시.
7. 최종 뷰/Excel은 각 원본 테이블의 JOIN 결과에서 생성. 원본을 한 테이블에 덮어쓰기 금지.

**현 상태:** 기존 Stage2 Release 보존과 코드 구조 확인; 공식 보고서의 존재 및 기술된 데이터 의미 확인. 신규 2년 보고서 웹 원본 **실제 다운로드**, 187개 ZIP 전체 **바이트·행·원본페이지 재검증**, DB 마이그레이션·실운영 JOIN은 아직 완료 증거 없음. 완료로 보고하지 않는다.
