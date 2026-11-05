# 스마트나라장터 WebView 실화면 확보 검증 (2026-11-05)

## 전제
- 사용자가 업로드한 APK: 스마트 나라장터_1.1.65.apk, 패키지 `kr.go.g2bkoneps`.
- APK 정적 분석: 896 XML 중 218 layout XML; WebView 입찰 업무 HTML은 APK에 내장되어 있지 않음.
- 추출된 확인 경로: `/tm/index.do`, `/co/coa/coaa/MainMenu/selectMainMenuByUsrAuthrtList.do`.
- **이 문서는 화면 수집 검증 보고서이지 UI 복제 완료 또는 104개 기능 완성을 뜻하지 않음.**

## 실제 브라우저 검증
- GitHub Actions Playwright Chrome PASS: https://github.com/lyonbegin/procureflow/actions/runs/42038146751
- 결과 아티팩트: https://github.com/lyonbegin/procureflow/actions/runs/42038146751/artifacts/13420235824
- GitHub Actions 시스템 Chrome PASS: https://github.com/lyonbegin/procureflow/actions/runs/42039596612
- 빠른 브라우저 증빙 아티팩트: https://github.com/lyonbegin/procureflow/actions/runs/42039596612/artifacts/13420212573
- 화면 및 JSON 증빙: `g2b_quick_capture/` (동일 조사 브랜치)

| 대상 | 응답/브라우저 검증 | 관찰한 내용 | 원본 업무 UI 확보 |
| --- | --- | --- | --- |
| `https://www.g2b.go.kr/` | Playwright HTTP 200, title 나라장터; 시스템 Chrome 렌더링 타임아웃/빈 DOM | 브라우저 본문 텍스트 0; 실제 공고 화면 검증 불가 | 아니오 |
| `https://www.g2b.go.kr/tm/index.do` | Chrome HTTP 200 | `{"result":true,"ErrorCode":0}` 형태의 JSON, 입찰 페이지 아님 | 아니오 |
| `https://m.g2b.go.kr/` | Chrome HTTP 200 | 스마트 나라장터 앱 설치 안내 | 설치 안내만 |
| `https://m.g2b.go.kr/tm/index.do` | Chrome HTTP 200 | 동일 앱 설치 안내 | 설치 안내만 |
| `https://www.g2b.go.kr/ehelpdesk` | Playwright HTTP 200, title 나라장터 | 브라우저 본문 텍스트 0 | 아니오 |
| `https://www.g2b.go.kr/co/coa/coaa/MainMenu/selectMainMenuByUsrAuthrtList.do` | 비인증 GET HTTP 403 (외부 페이지 조회) | 공개 메뉴 응답 확인 불가 | 아니오 |

참고: 모바일 설치 안내 HTML에 “스마트나라장터 서비스 준비중으로 이용이 불가능합니다”라는 문구가 주석으로 보존되어 있을 수 있음. **화면에 현재 표시되는 공지로 간주하지 말 것.** 한글 폰트가 없는 시스템 Chrome 스크린샷에서는 글자가 네모로 표시되므로 문구 검증은 DOM 텍스트로 대조.

## 현재 확인된 것
1. APK WebView 진입 주소의 일부는 공식 사이트에 응답하지만, 그 자체가 입찰 검색 HTML이 아니다.
2. 업무 메뉴는 비인증 요청에서 확인되지 않았고, 등록 사용자 세션/화면 조건이 필요한 것으로 보인다. 실제 앱 세션으로의 원본 검증은 하지 않았다.
3. 본 보고서의 증빙으로 로그인 후 업무 화면을 본 것처럼 설명하거나 UI를 임의로 채우면 안 된다.
4. 운영 n8n, PostgreSQL, Railway, 기존 투자 서비스는 변경하지 않았다. 검증 브랜치 `investigate/g2b-webview-capture-20261105`에만 조사 스크립트와 결과를 보관한다.

## 다음 수집의 합격 기준
- 공식 조달청 매뉴얼·앱 스크린샷 등 화면 출처 확보 → 버전·촬영 시점 분류
- 검색/목록/상세 UI가 실제 출력된 원본 화면과 DOM 또는 스크린샷 저장
- 화면 구성요소와 메뉴 링크를 원본별로 매핑
- 원본 화면 대비 일대일 검증 전 임의 클론/배포 금지

