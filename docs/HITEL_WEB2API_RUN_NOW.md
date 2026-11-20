# HITEL ChatGPT 원격 연결 실행

[현재 실행·설치·재개 안내](HITEL_WEB2API_CONTINUE.md)를 기준으로 이용해 주십시오.

- 실행: [Chrome 작업자 시작](https://github.com/lyonbegin/procureflow/actions/workflows/hitel-integration-bridge-live-qa.yml)
- 기본 실행 시간: 240분
- 프로그램에서 사용: `python tools/hitel_chat.py --room HITEL-WS-STABLE-AGENT-A --state agent-a.json --text "질문"`
- 연결 종료 후 결과 이어받기: `python tools/hitel_chat.py --state agent-a.json --resume`

소스는 main에 통합되어 있으며 예약 실행은 추가하지 않았습니다.
