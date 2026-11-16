# HITEL ChatGPT-Web2API — GitHub 실행 화면

이 문서는 **GitHub에서 직접 실행 버튼을 누르고 결과를 확인하는 운영 페이지**입니다. 개인 비밀번호나 토큰을 채팅·공개 소스에 입력하지 않습니다.

## 1. 바로 실행할 수 있는 GitHub Actions

**[Web2API GitHub 실행 및 결과 확인](https://github.com/lyonbegin/procureflow/actions/workflows/hitel-web2api-github-console.yml)**

1. 위 GitHub Actions 페이지를 엽니다.
2. 오른쪽의 **Run workflow**를 클릭하고 브랜치는 **main**을 선택합니다.
3. 실행 모드를 고른 다음 **Run workflow**를 클릭합니다.
   - `server_status`: Railway에 실제 HTTP 요청을 보내 서버 응답·시험 상태·기존 개인정보 보호를 확인합니다. ChatGPT에 새 질문을 전송하지 않습니다.
   - `real_chat`: GitHub 호스팅 Chrome에 저장된 암호화 로그인 세션을 복원하고 원본 Web2API를 실행해 **실제 한 번의 질문/답변**을 검증합니다. 결과는 해당 Actions 로그에서 확인합니다.
4. 시작된 실행을 열어 **Job summary**와 각 단계 로그에서 `PASS_` / `FAIL_` 결과를 확인합니다.

### 작업자 수동 실행

**[GitHub Chrome 작업자 시작](https://github.com/lyonbegin/procureflow/actions/workflows/chatgpt-web2api-relay-worker.yml)**

- GitHub에서 **Run workflow**로 시작합니다. 웹페이지의 클릭이 이 수동 실행을 대신한다고 주장하지 않습니다.
- Chrome 작업자가 성공적으로 연결되면 아래 시험 페이지에서 고정된 질문/답변을 실행할 수 있습니다.
- GitHub Actions는 임시 작업자입니다. 작업 완료 후 Chrome 프로세스와 로컬 API 서버는 종료됩니다.

## 2. 서버와 API 주소

- **Railway Web2API 시험 페이지:** https://chatgpt-relay-web-production.up.railway.app/
- **배포 서비스:** `chatgpt-relay-web`
- **서버 상태 확인:** https://chatgpt-relay-web-production.up.railway.app/health
- **시험 상태 확인:** https://chatgpt-relay-web-production.up.railway.app/demo/status
- **고정 질문 시험 접수:** `POST https://chatgpt-relay-web-production.up.railway.app/demo/start`
- **작업자 WebSocket:** `wss://chatgpt-relay-web-production.up.railway.app/ws`

**중요:** Railway 주소는 현재 *공개 범위를 제한한 시험용 릴레이*입니다. 전체 사용자가 임의의 질문을 보낼 수 있는 OpenAI 호환 API가 아닙니다. `/v1/chat/completions`은 GitHub Chrome 실행기 안의 `http://127.0.0.1:18080`에서 임시로 실행됩니다. 외부 공개 API 서버를 별도로 배포한 것으로 오해하시면 안 됩니다.

개인 대화·파일용 기존 `/api/v1/` 주소는 공개 시험 모드에서 차단됩니다. 공개 저장소와 HTML에 API 토큰·세션 쿠키를 넣지 않습니다.

## 3. 실제 코드와 설치 위치

| 항목 | GitHub 저장소 경로 |
| --- | --- |
| GitHub 실행 화면 (이 문서) | `docs/HITEL_WEB2API_GITHUB_OPERATOR.md` |
| 실행 선택 워크플로 | `.github/workflows/hitel-web2api-github-console.yml` |
| ChatGPT 실제 질문·답변 시험 | `.github/workflows/chatgpt-web2api-verify-session.yml` |
| GitHub Chrome 릴레이 실행 | `.github/workflows/chatgpt-web2api-relay-worker.yml` |
| Web2API 브라우저 검증 스크립트 | `.github/scripts/w2a_verify_chat_completion.py` |
| GitHub Chrome 릴레이 연결 코드 | `.github/scripts/w2a_relay_worker.py` |
| Railway 서버 및 API | `feature/chatgpt-web2api-relay-bridge-20261113:chatgpt-android-relay/web/app.py` |
| Railway 시험 웹페이지 | `feature/chatgpt-web2api-relay-bridge-20261113:chatgpt-android-relay/web/static/index.html` |

원본 Web2API는 `MartinezS8/chatgpt-web2api`의 특정 커밋 `497527dceabfa3f95961e23c291e618c5570f1ac`을 GitHub Actions가 내려받아 시험에 사용합니다. 별도 자체 재구현이 아닙니다. 원본 코드가 수정된 웹 UI 구조를 인식하도록 범위를 제한한 패치가 적용됩니다.

작업자는 Python 패키지·Chrome·Xvfb를 GitHub Actions에서 설치하고, **기존 GitHub Actions 암호화 세션 아티팩트**를 실행기 내부에서 복원합니다. 이 자료가 만료되거나 로그인 자체가 무효화되면 `real_chat`은 실패합니다. 실패를 성공으로 표시하지 않습니다.

## 4. Google Drive 백업

- [Google Drive 프로젝트 폴더](https://drive.google.com/drive/folders/1yEsZUSM4_ZC57ZSAlsY_cWjKQITgBPYk)
- [Google Drive 검증 소스 ZIP](https://drive.google.com/file/d/1mf_E_nFTsxf_CDifxGwUIzbzYz3Tt-M0/view)

Drive의 파일은 백업이며, **GitHub Actions의 자동 설치 입력이 아닙니다.** GitHub의 실행기는 GitHub 저장소 코드를 체크아웃하여 실행합니다. Drive에 보관한 파일이 자동으로 서버에 배포된 것으로 판단하지 않습니다.

## 5. 2026-11-16 실제 실행 기록

| 실제 시험 | GitHub Actions 결과 | 확인한 사실 |
| --- | --- | --- |
| [GitHub 운영 콘솔 통합 실측](https://github.com/lyonbegin/procureflow/actions/runs/43793536967) | **두 작업 모두 성공** | GitHub 콘솔에서 서버 검사 및 재사용 워크플로의 실제 ChatGPT 질문·답변이 모두 통과 |
| [Railway 서버 API 실측](https://github.com/lyonbegin/procureflow/actions/runs/43792983527) | **성공** | Railway /health 200, /demo/status 200, 기존 /api/v1/rooms 404 |
| [ChatGPT 실제 질문·답변 실측](https://github.com/lyonbegin/procureflow/actions/runs/43793249813) | **성공** | Chrome 로그인 복원, 모델 21개 조회, 실제 질문 HTTP 200, 답변 표식 일치 |
| [수정 전 입력창 장애 원본 로그](https://github.com/lyonbegin/procureflow/actions/runs/43792504439) | 당시 실패 | HTTP 500 입력창 인식 오류. `?model=auto` 이동 주소 수정 후 위 시험에서 통과 |
| [기존 과거 질문·답변 통과 기록](https://github.com/lyonbegin/procureflow/actions/runs/43357968431) | 당시 성공 | 2026-11-13 단발 시험 통과 |

서버 API와 ChatGPT 실제 문답은 **서로 다른 시험**으로 검증했으며, 2026-11-16에는 GitHub 운영 콘솔의 두 작업을 한 실행에서 각각 성공적으로 완료했습니다. 실제 Chrome 질문 HTTP 200·답변 표식 일치도 확인했습니다. GitHub 사용자 인터페이스에서 사람이 직접 `Run workflow`를 누르는 GUI 동작은 별도 검증하지 않았습니다.
임시 Chrome 작업자가 연결되지 않은 시점에는 `workerConnected=false`로 표시됩니다.

## 6. 결과 판단 기준

- `PASS_RAILWAY_API_HTTP`: 실제 Railway 상태 HTTP 요청 성공
- `PASS_TEST_CONSOLE_STATUS`: 시험 상태 API 정상
- `PASS_PRIVATE_ROOMS_NOT_PUBLIC`: 기존 사용자 방 정보 접근 차단
- `PASS_WEB2API_CHAT_SEND_AND_RECEIVE`: ChatGPT에 실제 시험 질문을 보낸 뒤 답변 표식 검증 완료
- `FAIL_...`: 해당 단계 미통과 — 작업 전체를 성공이라고 판단하지 않습니다

**안전:** GitHub Actions 사용자 권한으로 실행하실 수 있지만, 공개 웹페이지에는 GitHub 실행 권한이 없으므로 브라우저 클릭이 곧바로 Actions 실행을 보장하지 않습니다. 모든 비밀값은 허가된 실행 환경에만 둡니다.
