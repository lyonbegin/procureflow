# HITEL 파일 시나리오 — 실제 HTTPS API 왕복 검증

## 실제 프로토콜과 사용자 API의 구분
- 일반 외부 프로그램용 \`POST /integrations/v1/files\`는 현재 501 미지원입니다.
- 본 실험은 별도의 **고정 합성파일 QA API** \`/integrations/v1/scenarios/files/\`를 통하여 HTTP 파일 업로드/다운로드와 실제 ChatGPT Chrome UI 파일 작업을 연결합니다. QA API는 GitHub Actions **단일 검증 워크플로의 서명된 OIDC JWT**가 있어야 업로드·실행 결과 등록이 가능하며, 공개 결과 조회는 가능합니다.
- QA 프로토콜이 통과해도 이를 일반 클라이언트의 파일 전송 지원으로 오인하여서는 안 됩니다.

## 호출 순서
1. GitHub \`main\` 워크플로 \`.github/workflows/hitel-file-scenarios-via-api.yml\`만 서명된 OIDC를 발급받아 \`POST /integrations/v1/scenarios/files/runs\` 호출. 고유 \`run_id\`와 고정 합성파일 명세를 돌려받습니다.
2. \`POST /integrations/v1/scenarios/files/runs/{run_id}/files/txt\` 및 \`.../csv\`: multipart 원본 바이트 업로드, 서버 SHA-256 확인.
3. \`GET .../files/txt/content\`와 \`.../csv/content\`: 서버가 저장한 실제 바이트를 원래 GitHub runner로 다운로드. 두 파일 모두 원본 SHA-256이 일치해야 Chrome 단계로 진행합니다.
4. 이전에 등록한 실제 Chrome 1번 계정을 복원한 뒤, 암호화된 계정 레지스트리와 현재 로그인 세션을 비교합니다.
5. API에서 다시 내려받은 **바로 그 파일**을 ChatGPT 웹 UI에 첨부하며 다음 다섯 건을 각각 검증합니다.
   - **S08**: TXT 파일이 ChatGPT에 첨부된 상태로 화면에 표시되는지.
   - **S09**: 아직 전송하지 않은 TXT 첨부를 제거하는지.
   - **S10**: TXT의 고유 마커가 실제 ChatGPT 답변에 포함되는지.
   - **S15**: API CSV에 있는 3+5를 ChatGPT가 숫자 8로 답하는지.
   - **S11**: 생성 요청한 CSV를 실제 브라우저로 받아 **원본 CSV 바이트의 행과 값**을 확인하는지. 단순 가짜 링크 또는 빈 파일은 PASS 불가.
6. \`POST /integrations/v1/scenarios/files/runs/{run_id}/results\`로 검증된 5건 상태와 전송 무결성 증거를 API 서버에 저장합니다.
7. 외부 프로그램이나 웹사이트에서 \`GET /integrations/v1/scenarios/files/latest\` 또는 \`GET /integrations/v1/scenarios/files/runs/{run_id}\`로 결과를 읽을 수 있습니다.

### 공개 조회 URL

- [최신 파일 API 시험 결과](https://hitel-integration-api-production.up.railway.app/integrations/v1/scenarios/files/latest)
- [GitHub Actions 실 파일 API E2E 실행 로그](https://github.com/lyonbegin/procureflow/actions/workflows/hitel-file-scenarios-via-api.yml)
- [파일 API 원본 소스](https://github.com/lyonbegin/procureflow/blob/feature/hitel-integrations-api-20261118/chatgpt-android-relay/web/file_scenario_api.py)

## 증거 해석

- \`transport.uploaded_via_api=true\` 및 \`transport.downloaded_via_api=true\`: 합성 파일 원본이 진짜 HTTPS API를 왕복함.
- \`transport.sha256_match=true\`: 원본과 서버 재수신 파일의 SHA-256 일치.
- \`transport.saved_chatgpt_account_verified=true\`: Actions에서 등록된 1번 계정의 실제 Chrome 로그인 일치 검사 통과.
- \`cases[*].status=PASS\`: 해당 동작의 관측 근거가 있음. BLOCKED/FAIL은 미완료 또는 실패이며, 전체 CI도 실패로 처리함.
- \`S11=PASS\`는 실제 CSV 다운로드 이벤트가 발생하고 받아온 파일의 행/값이 일치할 때만 가능합니다.
- 시험에는 임의로 만든 합성 TXT/CSV만 사용합니다. 개인의 기존 파일, 기존 대화, ChatGPT 쿠키, 인증 토큰은 공개 API로 보내지 않습니다.
