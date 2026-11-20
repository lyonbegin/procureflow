# HITEL ChatGPT 원격 연결 — 실행 및 재사용

기준: 2026-11-20. 소스와 실행 입구는 기존 `lyonbegin/procureflow`의 `main`입니다.

## 실행

[Chrome 작업자 시작](https://github.com/lyonbegin/procureflow/actions/workflows/hitel-integration-bridge-live-qa.yml)에서 `Run workflow` → `worker_only` → `240`분을 선택합니다. 기존에 등록한 계정으로 연결하며 새 로그인 등록이나 비밀키 추가가 필요하지 않습니다. 이 실행 파일을 main에서 갱신할 때에도 4시간 세션을 한 번 시작합니다.

한 번의 실행은 최대 4시간입니다. 예약 실행·상시 자동 실행은 추가하지 않았습니다. 새 실행은 기존 실행을 취소하지 않고 대기합니다. 실제 ChatGPT 작업이 남아 있거나 상태를 검증할 수 없으면 새 작업자를 시작하지 않습니다.

실행 로그의 `PASS_TWO_EXISTING_CHATGPT_ROOMS_PREWARMED_IN_INDEPENDENT_TABS`는 기존 두 방의 독립 탭 준비 완료입니다. 실제 질문의 완료는 `reply.done`의 바이트 수와 SHA-256까지 확인해야 합니다.

[현재 상태 JSON](https://hitel-integration-api-production.up.railway.app/integrations/v1/public/status)에서 `worker_connected`, `worker_heartbeat_recent`, `worker_bootstrap_ready`를 확인하실 수 있습니다. `worker_autostart_configured=false`이면 종료 후 무인 재시작이 구성된 상태가 아닙니다.

## PC 또는 다른 프로그램에서 사용

```powershell
git clone https://github.com/lyonbegin/procureflow.git
cd procureflow
python -m pip install websockets==13.1
python tools/hitel_chat.py --room HITEL-WS-STABLE-AGENT-A --state agent-a.json --text "한국어로 짧게 인사해 주십시오."
```

두 번째 연결은 별도의 상태 파일과 방 이름을 사용합니다.

```powershell
python tools/hitel_chat.py --room HITEL-WS-STABLE-AGENT-B --state agent-b.json --text "두 번째 대화방입니다."
```

같은 방의 다음 질문은 동일한 상태 파일을 지정하시면 됩니다.

```powershell
python tools/hitel_chat.py --state agent-a.json --text "앞서 말씀하신 내용을 한 문장으로 정리해 주십시오."
```

연결이 끊겼거나 결과가 미확정이면 다음 명령으로 **기존 요청의 결과만** 이어받습니다.

```powershell
python tools/hitel_chat.py --state agent-a.json --resume
```

클라이언트는 전송 전에 request_id와 room_id를 원자적으로 저장합니다. 미확정 요청은 자동 재전송하지 않으며, `job.resume`으로 기존 job_id를 조회합니다. 다른 방의 답변, 순서가 다른 바이트 조각, 길이·SHA-256 불일치를 완료로 처리하지 않습니다. 요청이 서버에 도달했는지 확인할 수 없는 경우에도 새 질문을 자동 생성하지 않습니다.

이 연결은 기존 공개 시험방 전용입니다. 두 방의 명칭은 위 실제 검증에 사용한 공개 방이며, 개인 전용 대화방으로 취급하지 않습니다.

## 소스 위치

| 역할 | 파일 |
|---|---|
| 실행 입구 | `.github/workflows/hitel-integration-bridge-live-qa.yml` |
| 통합 Chrome 작업자 | `.github/scripts/hitel_web2api_worker.py` |
| 방별 독립 탭 및 원본 Web2API 프로세스 | `.github/scripts/hitel_room_tab_pool.py` |
| API·WebSocket 서버 | `chatgpt-android-relay/web/` |
| 외부 프로그램용 지속 소켓 클라이언트 | `tools/hitel_chat.py` |
| 통합 회귀시험 | `.github/workflows/hitel-runtime-regression.yml` |

기존 `w2a_relay_worker.py`는 이전 실행 경로의 호환성을 위해 유지합니다. 통합 실행은 `hitel_web2api_worker.py`를 사용합니다. 시험 브랜치 checkout 없이 main의 소스 한 벌로 실행합니다.

서버의 실행 진입점은 `chatgpt-android-relay/web`에서 `uvicorn app:app`입니다. 기존 배포 서버의 소스는 이번 소스 정리만으로 자동 변경하지 않습니다. 새 Railway 서비스는 만들지 않습니다.

## 확인된 실제 시험과 한계

[실제 송수신 시험 #44749309310](https://github.com/lyonbegin/procureflow/actions/runs/44749309310)은 2026-11-20 23:00~23:01 KST에 성공했습니다. A·B가 각각 하나의 지속 소켓으로 4회씩 총 8개 질문을 전송했으며, 응답 경로·대화 이력·바이트·SHA-256을 검증했습니다.

이 결과는 두 방의 텍스트 송수신에 대한 증거입니다. 파일 첨부·생성 파일 다운로드·24시간 상시 운영의 완료 증거는 아닙니다. 파일 시나리오의 이전 결과는 별도 문서에서 구분해 유지합니다. 통합 회귀시험에서는 실제 ChatGPT에 질문을 전송하지 않습니다.

실패 기록은 지우지 않습니다. 기존 120건·160건 등 다른 분류 작업의 진행률을 이 통신 시험으로 갱신하지 않습니다.
