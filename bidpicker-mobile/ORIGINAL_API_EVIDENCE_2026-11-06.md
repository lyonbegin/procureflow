# 원본 XAPK 검색 요청 재검증 — 2026-11-06

## 원본 앱에서 직접 확인된 네트워크 계약

사용자 제공 `입찰공고 알리미_1.0.1.xapk`의 `base.apk/classes.dex` 정적 분석을 기준으로 한다.

- 앱 Retrofit 기본 주소: `https://www.pickersoft.com/bidpicker-api/` (`LM2/l.get`, 문자열 상수)
- 목록: `GET api/bids` (`LO2/d.f`, DEX 메서드 ID 4889)
- 상세: `GET api/bids/{id}` (`LO2/d.a`, 메서드 ID 4884)
- 인기 검색어: `GET api/trending-keywords` (`LO2/d.e`, 메서드 ID 4888)
- 원본 GET의 검색 파라미터: `keyword,category,region,taskType,status,deadlineSoon,includeClosed,sort,page,size`
- 클래스 `LM2/l.get`는 `LO2/c` 인스턴스를 생성하고 HTTP client interceptor 목록에 추가한다 (`classes.dex` 오프셋 0x122e80, 0x122e8e)
- `LO2/c.a`에서 `Authorization: Basic ...`과 `Accept: application/json`을 헤더에 추가하는 코드가 존재 (`classes.dex` 오프셋 0x127d48~0x127e40). 요청용 인증정보는 DEX의 배열 초기화/문자열 조합 형태이므로 **이 문서와 앱 저장소에는 그 값을 저장하거나 재배포하지 않았다.**

## 검증된 운영 서버 응답

읽기 전용으로 같은 URL을 외부에서 두 종류의 User-Agent로 요청했다.

| HTTP GET 경로 | 일반 Android/OkHttp UA | 모바일 브라우저 UA | 인증 요구 |
|---|---|---|---|
| `/bidpicker-api/api/bids` | 401 | 401 | `WWW-Authenticate: Basic realm="bidpicker"` |
| `/bidpicker-api/api/trending-keywords` | 401 | 401 | 동일 |

증빙: https://github.com/lyonbegin/procureflow/actions/runs/42186744880

## 이전 모바일 웹앱 오류와 실제 수정

**잘못된 구조:** 모바일 웹앱 → 별도로 만든 `/api/bidpicker/discover` Bridge → Bridge에서 `BIDPICKER_USERNAME/PASSWORD` 없으면 **요청 자체를 보내지 않고 임의의 HTTP 503** 반환.

**수정 구조:** 모바일 웹앱 → 자체 읽기 전용 프록시 → XAPK에 적힌 원본 도메인의 `api/bids` 직접 GET. 원본 서버가 401을 반환하면 사용자에게 **HTTP 401 그대로 보고**하며 인공적인 503으로 바꾸지 않음.

- 검색 파라미터는 원본 Retrofit 쿼리명에 대응 (예: `task_type` → `taskType`).
- 상세, 인기 검색어도 원본 GET URL로 직접 연결됨.
- 인증정보가 없는 상태에서도 원본 GET을 실제 전송하며, 서버가 반환한 상태를 그대로 전달함.
- 원본 서버 사용 권한이 있는 경우, 서버 **비밀 환경변수** `BIDPICKER_UPSTREAM_USERNAME`과 `BIDPICKER_UPSTREAM_PASSWORD`로 Basic 인증 헤더를 설정할 수 있음. 현재 해당 값은 배포 환경에 설정되지 않음. 원본 APK의 제3자 내장 인증값은 추출하거나 운영에 재사용하지 않음.
- 임의 데이터, 기존 자동화 DB 또는 다른 공고 수집기를 검색 결과인 것처럼 주입하지 않음.

## 아직 검증되지 않은 점

- 원본 웹 API에서 `200 OK`와 실제 `BidPageDto`를 수신한 사례: **없음**
- 원본 앱이 정상 실행되는 Android 런타임의 실제 네트워크 응답: 캡처하지 않음
- 목록/상세/인기 검색어 API의 인증된 실서비스 JSON 검증: 완료되지 않음
- 원본 앱 화면의 100% 픽셀 수준 동일성: 별개 검증 필요

## 별도 배포

- 브랜치: `feature/bidpicker-mobile-original-ui-20261106`
- 모바일 화면: https://bidpicker-original-mobile-ui-production.up.railway.app/
- 원본 API 연결: `https://www.pickersoft.com/bidpicker-api/` (XAPK 실주소)
- 2026-11-06 현재 원본 서버 HTTP 401 인증 요청이 남아 있어 실제 공고 표시까지 완료된 것은 아님.
