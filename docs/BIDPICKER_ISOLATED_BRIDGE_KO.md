# 입찰공고 알리미 — 독립 수집 Bridge (개발 브랜치)

대상: 사용자가 제공한 입찰공고 알리미 1.0.1 XAPK에서 확인한 GET 검색 및 공고 데이터 필드.
제3자 서버가 실제 검색 데이터를 주는지는 **미검증**: 인증 없는 GET은 2026-11-06에 HTTP 401.
이 구현은 앱 보호코드를 우회하거나 APK에 포함된 제3자 자격증명을 추출·재사용하지 않습니다.

## 목표
1. 앱 형식 `keyword, category, region, taskType, sort, page, size`로 공고 검색 (GET)
2. `bidNo+bidSeq` 기준 중복제거, 원문 URL 도메인 형식 검사, 원문 JSON/해시 보존
3. **새 독립 PostgreSQL** `BIDPICKER_DATABASE_URL`의 `bidpicker_feed.notices`만 사용. 기존 `DATABASE_URL`/예전 DB/테스트 공고를 읽거나 이관하지 않음
4. 별도 n8n 보조 플로우가 Bridge의 검색 API를 호출해 PF01에 공고 후보로 전달할 수 있도록 구성
5. 반드시 공식 나라장터 원문·첨부·10년 결과를 따로 검증. 제3자 검색 결과만으로 PF04/PF05/최종 승인 통과 금지

## 실행 및 테스트
```bash
pip install -r integrations/bidpicker/requirements.txt
PYTHONPATH=. python -m unittest discover -s tests -p 'test_bidpicker_bridge.py' -v

# 별도 Bridge 서버; 레거시 main.py/worker.py를 실행하지 않음
uvicorn integrations.bidpicker.bridge:app --host 127.0.0.1 --port 8088
```

필요 환경변수 (값/비밀번호를 GitHub나 n8n JSON에 저장하지 않음):
```
BIDPICKER_USERNAME=<사용 권한이 있는 인증 계정>
BIDPICKER_PASSWORD=<사용 권한이 있는 인증 비밀번호>
BIDPICKER_BRIDGE_TOKEN=<별도 Bridge 관리자 비밀값>
BIDPICKER_DATABASE_URL=<새 별도 PostgreSQL URL>
BIDPICKER_SYNC_ENABLED=0
```
`BIDPICKER_SYNC_ENABLED=1`을 명시해야만 저장 API가 동작합니다.
`DATABASE_URL`과 `BIDPICKER_DATABASE_URL`을 동일 값으로 설정하면 DB 접근 거부.

읽기 전용 검색:
```bash
curl -H 'Authorization: Bearer YOUR_BRIDGE_TOKEN' \
 'http://127.0.0.1:8088/api/bidpicker/search?keyword=정보시스템&size=10'
```

저장(명시적 허가 시):
```bash
curl -X POST -H 'Authorization: Bearer YOUR_BRIDGE_TOKEN' \
 -H 'Content-Type: application/json' \
 -d '{"keyword":"정보시스템","page":1,"size":10}' \
 'http://127.0.0.1:8088/api/bidpicker/sync'
```

n8n:
- `n8n/integrations/PF01_BidPicker_Discovery.json`은 **별도 미활성 하위 워크플로**, 운영 PF01 JSON을 교체하지 않습니다.
- n8n 환경변수 `BIDPICKER_BRIDGE_URL`에 Bridge 주소, HTTP Header Auth Credential에 `Authorization: Bearer <BIDPICKER_BRIDGE_TOKEN>` 설정.
- 상위 PF01에서 Execute Workflow로 호출한 후 `DISCOVERY_ONLY` 결과를 공식 원문 검증 단계로 연결할 수 있음. **운영 실제 연결/배포는 미완료**.

안전 수칙: GET 검색만 공개 API가 아닌 제3자 서버에 수행합니다. 푸시/기기 등록/삭제 API 호출 없음. 401/403은 인증 우회 없이 오류로 처리. 저장된 검색 후보는 원본 공식 증빙이 아니며 경쟁업체·낙찰 분석 자료로 바로 사용하지 않음. 입력 JSON 형태가 달라지면 빈 결과로 위장하지 않고 오류로 처리합니다.
