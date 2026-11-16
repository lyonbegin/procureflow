# HITEL Web2API 자동 실행 요청

- 실행 식별: 2026-11-16T12:41+09:00
- 요청자 지시: GitHub Actions Run workflow 버튼을 사용자에게 요구하지 말고 ChatGPT가 직접 실행할 것
- 실행: Railway /health 및 /demo/status 확인, GitHub-hosted Chrome 설치, 저장된 ChatGPT 로그인 세션 복원, 원본 Web2API 실제 질문/답변 왕복 검증
- 처리 방식: 이 파일의 자동화 요청 커밋이 워크플로를 호출함
- 공개 비밀번호, 쿠키 및 사용자의 개인 대화 내용은 저장하지 않음
- 검증 기준: 각 job 결과와 PASS_WEB2API_CHAT_SEND_AND_RECEIVE를 실제 GitHub Actions에서 확인

이 파일은 비밀정보 없는 GitHub Actions 실행 트리거입니다. 저장소에서 사용자에게 Run workflow 버튼 조작을 요구하지 않습니다.
