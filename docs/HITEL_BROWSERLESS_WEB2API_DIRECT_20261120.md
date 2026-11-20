# HITEL HTTP 두 에이전트 격리 시험 — 시험 전용

2026-11-20 사용자 요청에 따른 수정: 인증 구조를 새로 설계하거나 추가하지 않습니다.

## 허용 범위

- 브라우저 및 화면 자동화 없이 로컬 HTTP 시험 서버에서 두 에이전트 동시 요청 검사
- 에이전트별 독립 `room_id`, `conversation_id`, `parent_message_id` 상태 유지
- A 35회 + B 35회 = 70회 교차 전송 및 응답 내용·중복·순서 검사
- 한쪽 HTTP 429 또는 응답 대화방 ID 불일치 시 해당 방 격리, 다른 방 정상 진행 검사
- 시험 데이터와 인메모리 대화 상태만 사용
- 연구용 실제 A그룹·Scribd 대화방 및 Railway 운영 환경은 수정하지 않음

## 사용자 요청에 따라 제거한 부분

- 실계정에 접속하려고 임의로 추가했던 인증파일 처리 코드
- 신규 GitHub 환경 변수/비밀값 등록을 요구하는 워크플로와 라이브 시험 코드
- 별도 실사용 워커를 생성해 인증·운영까지 전환하려던 코드

**현재 브랜치는 실제 ChatGPT 웹 서버가 아닌 로컬 시험 서버용입니다.**
테스트 통과를 실제 두 사용자 계정의 ChatGPT 동시 전송 성공으로 표시하지 않습니다.

## 시험 실행

```sh
python3 -m unittest discover -s tests -p 'test_hitel_direct_web2api.py' -v
python3 -m unittest discover -s tests -p 'test_hitel_direct_two_agents_burst.py' -v
```

- `.github/workflows/hitel-browserless-web2api-20261120.yml`
- `.github/workflows/hitel-two-agent-burst-offline-20261120.yml`

실제 운영 인증은 **기존 시스템에 사용자가 이미 승인한 방식**만 사용할 수 있습니다.
현재 그 경로에서 브라우저 없는 실전 메시지 송수신이 검증되었다는 증거는 없습니다.
인증정보를 새로 요청하거나 저장하는 조치는 수행하지 않습니다.
