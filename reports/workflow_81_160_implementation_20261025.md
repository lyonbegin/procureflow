# ProcureFlow 워크플로 기능 81~160 구현·검증 현황

- 기준: 2026-10-25, `lyonbegin/procureflow`, PR #5(독립 작업실), PR #6(노드 테스트), PR #7(편집 DAG와 시뮬레이션 디버거)
- **중요:** 실제 운영 기능에 해당하는지는 GitHub 코드 테스트와 Railway 운영 DB 테스트를 반드시 구분한다.
- 판정: **구현** = 해당 범위의 코드 및 자동 단위 테스트 존재(항목 자체가 실서비스에서 전체 검증되었다는 의미 아님), **부분** = 일부만 구현, **미구현** = 해당 기능 제공하지 않음.
- 기존 조달청 업무 API 104개와 이번 81~160점검 80개는 서로 다른 기능 목록이다.
- 요약: 구현 19개 / 부분 47개 / 미구현 14개, 합계 80개.
- 실운영 Worker 병렬 DAG 실행 / 브레이크포인트 실제 외부 API 중단 / 일반 API 무제한 호출 / 악성코드 스캔은 현재 미구현이다.
- 테스트 결과 기준: `tests/test_g2b_node_lab.py`, `tests/test_g2b_dag_core.py`, `frontend/src/workflow.test.js`. CI 통과와 Railway 운영 검증 상태는 별도로 기록한다.

| 번호 | 판정 | 기능 | 구현한 범위 / 남은 작업 | 주요 소스 |
|---:|---|---|---|---|
| 81 | 부분 | 노드 자체 API 테스트 | 테스트 전용 4모드 구현; 수동 입력으로 실제 104개 업무 수집기 전체를 시험하지는 못함 | `g2b_node_lab.py` |
| 82 | 부분 | 텍스트 직접 입력 | JSON 객체 필드에 텍스트 입력 지원; 전용 텍스트 타입 매퍼 부족 | `NodeLabPanel.jsx` |
| 83 | 부분 | 숫자 날짜 선택형 입력 | 기존 숫자·문자 입력; 날짜·Boolean·Select 자동 생성 미완성 | `App.jsx` |
| 84 | 구현 | JSON 직접 입력 | 문법 확인·서버 Pydantic 검증·실행 결과 지원 | `NodeLabPanel.jsx` |
| 85 | 부분 | 입력 데이터 출처 선택 | 공식/수동/파일/Mock 및 시뮬레이션 선 매핑; 실제 104개 핸들러에 수동 데이터 전달 미완성 | `g2b_node_lab.py` |
| 86 | 부분 | 앞 노드 입력값 재정의 | 고정/수동 입력 시뮬레이션 지원; 운영 흐름 입력 덮어쓰기 금지 | `g2b_dag_core.py` |
| 87 | 구현 | 파일 직접 업로드 | PDF HWP HWPX DOCX XLSX CSV TXT JSON XML 개별 업로드·파싱 | `g2b_node_lab.py` |
| 88 | 구현 | 다중 파일 업로드 | 화면에서 최대 6개 선택·순차 업로드, 기능별 12개 저장 | `NodeLabPanel.jsx` |
| 89 | 구현 | 드래그 앤 드롭 | 노드 파일 탭에 파일 끌어놓기 지원 | `NodeLabPanel.jsx` |
| 90 | 부분 | 파일 형식 검증 | PDF/OLE/ZIP 서명·압축비·텍스트 NUL 검증; 전체 MIME 및 백신 미실시 | `g2b_node_lab.py` |
| 91 | 구현 | 파일 크기 개수 제한 | 8MiB/개, 12개/기능, 6개/테스트 | `g2b_node_lab.py` |
| 92 | 구현 | 파일 해시 식별자 | UUID 파일ID, SHA-256, 용량, 시각 및 테스트 출처 DB 저장 | `g2b_node_lab.py` |
| 93 | 부분 | 파일 미리보기 | 텍스트 추출·프리뷰 지원; PDF 페이지·Excel 그리드 뷰 미완성 | `NodeLabPanel.jsx` |
| 94 | 구현 | 테스트 파일 원본 분리 | 전용 테스트 테이블 저장; 공식 증빙 갱신 및 인증 금지 | `g2b_node_lab.py` |
| 95 | 미구현 | API URL Query Header 편집 | 임의 URL 실행 미지원·SSRF 방지; 정식 커넥터 모델 필요 | — |
| 96 | 미구현 | HTTP 메서드 선택 | 전용 외부 HTTP API 노드 타입 미구현 | — |
| 97 | 부분 | 요청 본문 형식 | 수동 JSON·Mock 및 multipart 업로드; 일반 API의 Form/Binary 호출 미지원 | `g2b_node_lab.py` |
| 98 | 부분 | API 인증 프로파일 | 기존 관리자 Bearer 토큰 사용; API키 OAuth 자격증명 저장소 미구현 | `frontend/src/api.js` |
| 99 | 미구현 | OpenAPI cURL 가져오기 | 외부 API 노드 자동 생성 없음 | — |
| 100 | 부분 | HTTP 응답 상세 | HTTP 상태·테스트 처리시간·오류·결과 표시; 응답 헤더 원문 미지원 | `g2b_node_lab.py` |
| 101 | 부분 | 응답 형태별 검사 | JSON 보기·문서 텍스트 미리보기; 표·이미지·바이너리 전문 뷰 미구현 | `NodeLabPanel.jsx` |
| 102 | 부분 | 입력 프리셋 | 테스트 실행 이력·입력 재현; 명명된 공유 프리셋 라이브러리 없음 | `g2b_node_lab.py` |
| 103 | 부분 | 파일 포함 API 호출 | 업로드 파일을 기존 파서로 실제 추출; 수동 파일로 공식 업무 /run 호출은 미지원 | `g2b_node_lab.py` |
| 104 | 구현 | 테스트 운영 분리 | 테스트 전용 DB·권한·출처 표시, official 검증 상태 불변 | `g2b_node_lab.py` |
| 105 | 부분 | 외부 호출 모의 실행 | 임의 Mock 응답과 실패 주입; 범용 Mock HTTP 서버 없음 | `g2b_node_lab.py` |
| 106 | 부분 | 현재 노드만 실행 | 기존 /run 실수집 단독 실행 + 테스트 모드; 임의 업로드를 업무 핸들러 입력으로 연결하지 않음 | `g2b_feature_api.py` |
| 107 | 부분 | 선택 노드부터 실행 | Step/Retry로 지정 준비 노드 테스트; 운영 작업 중간 진입 미완성 | `g2b_dag_core.py` |
| 108 | 부분 | 선택 노드까지 실행 | 지정 중단점으로 계속 진행 가능; 자동 실행 범위 선택 미완성 | `g2b_dag_core.py` |
| 109 | 구현 | Step Next | 테스트 시뮬레이터 단일 준비 노드 실행 | `g2b_dag_core.py` |
| 110 | 미구현 | Step Into | 서브워크플로 실행 컨텍스트 없음 | — |
| 111 | 미구현 | Step Out | 서브워크플로 복귀 모델 없음 | — |
| 112 | 구현 | 실행 전 중단점 | 시뮬레이션 전 브레이크포인트 | `g2b_dag_core.py` |
| 113 | 구현 | 실행 후 중단점 | 시뮬레이션 후 브레이크포인트 | `g2b_dag_core.py` |
| 114 | 미구현 | 조건부 중단점 | 응답 필드 평가 기반 브레이크포인트 미구현 | — |
| 115 | 부분 | Pause | DB 보존 시뮬레이터 Pause; 실제 Worker 일시정지 불가 | `g2b_dag_core.py` |
| 116 | 부분 | Resume | DB 보존 시뮬레이터 Resume; 실제 Worker 재개 불가 | `g2b_dag_core.py` |
| 117 | 부분 | Stop Cancel | 시뮬레이터 상태 취소; 실제 실행 중 외부 API 요청 취소 미구현 | `g2b_dag_core.py` |
| 118 | 구현 | Skip Node | 시뮬레이터 Skip, 결과 성공 위조 방지 | `g2b_dag_core.py` |
| 119 | 부분 | Retry Node | 시뮬레이터 Retry 및 기존 기능 개별 재요청; 운영 재시도 정책 없음 | `g2b_dag_core.py` |
| 120 | 부분 | Restart From Node | Retry 시 모든 하위 결과 무효화; 운영 실행 복원은 미구현 | `g2b_dag_core.py` |
| 121 | 부분 | Replay Execution | 노드 테스트 원입력 재현·고정 실행 그래프 보관; 전체 실제 Worker 재생 없음 | `g2b_node_lab.py` |
| 122 | 구현 | Pin Output | 테스트 출력 저장·시뮬레이터 수동 고정 | `g2b_node_lab.py` |
| 123 | 부분 | Edit Pinned Output | API로 출력 수정 가능; 편집기 내 변경 비교 이력 부족 | `g2b_node_lab.py` |
| 124 | 부분 | 강제 성공 실패 주입 | Mock 응답·실패 시뮬레이터; 실제 API 응답 변조는 금지 | `g2b_dag_core.py` |
| 125 | 미구현 | Watch Variables | 필드별 실시간 변수 감시 패널 없음 | — |
| 126 | 부분 | 입력 출력 비교 | 각 노드 resolved_inputs·outputs 조회; JSON Diff 전용 UI 없음 | `g2b_dag_core.py` |
| 127 | 부분 | 연결선 데이터 추적 | source/target JSON 경로 및 lineage 기록; 실제 Worker 전파 추적 없음 | `g2b_dag_core.py` |
| 128 | 부분 | 상세 예외 디버깅 | 오류 상태·결과 기록; 스택 트레이스·HTTP 전문 보호 및 별도 보기 미완성 | `g2b_node_lab.py` |
| 129 | 부분 | 노드 실시간 로그 | 기존 개별 작업 상태 3초 Polling; SSE·노드 로그 스트림 미구현 | `App.jsx` |
| 130 | 부분 | 실행 중 노드 강조 | 시뮬레이션 노드 상태별 UI 색상; 운영 Worker 다중 실행 상태 추적 미완성 | `DAGEditor.jsx` |
| 131 | 부분 | 병렬 노드 디버깅 | 병렬 준비 노드 계산·개별 Step; 실제 Worker 동시 실행 미구현 | `g2b_dag_core.py` |
| 132 | 구현 | 디버거 상태 영속화 | 디버그 세션·출력·버전 스냅샷 DB 저장/재조회 | `g2b_dag_api.py` |
| 133 | 구현 | 예상 출력값 설정 | assertions expected 지원 | `g2b_node_lab.py` |
| 134 | 구현 | Assert 검증 | eq/ne/exists/contains/gte/lte 비교 후 통과/실패 저장 | `g2b_node_lab.py` |
| 135 | 부분 | 출력 스키마 검증 | API Pydantic 입력 및 Assertion 검증; 범용 JSON Schema 출력 검증 없음 | `g2b_node_lab.py` |
| 136 | 부분 | 경계값 테스트 | 직접 최소 최대 입력·검증식 가능; 자동 테스트 케이스 생성 없음 | `NodeLabPanel.jsx` |
| 137 | 구현 | 필수 입력 누락 테스트 | 파일 누락·잘못된 파라미터 등 422 오류 및 회귀 테스트 | `tests/test_g2b_node_lab.py` |
| 138 | 부분 | HTTP 오류 시뮬레이션 | Mock 및 실패 경로 시험; 표준 HTTP 4xx·5xx 시퀀스 Mock 서버 미구현 | `g2b_dag_core.py` |
| 139 | 미구현 | 타임아웃 테스트 | 실행별 timeout·cancel 정책 없음 | — |
| 140 | 부분 | 중복 실행 안전성 | 기존 동일 발주 작업 큐 중복 차단; 테스트 호출 멱등성 키 없음 | `g2b_feature_api.py` |
| 141 | 부분 | 파일 테스트 데이터셋 | 업로드 파일 개별 저장·조회; 명명된 다중 파일 데이터셋 템플릿 없음 | `g2b_node_lab.py` |
| 142 | 부분 | 비정상 파일 테스트 | 손상 ZIP·과도한 압축·PDF 서명 차단, 암호화 문서 검출 일부 | `g2b_node_lab.py` |
| 143 | 미구현 | Golden Output 비교 | 핀 저장만 가능; 버전별 출력 Diff 및 회귀 판정 없음 | — |
| 144 | 부분 | 조건 분기 테스트 | success/failure/always/skipped 연결 조건 시뮬레이터; 실제 Worker 분기 없음 | `g2b_dag_core.py` |
| 145 | 구현 | 병렬 합류 테스트 | ALL/ANY/QUORUM 조건 Python 검증 테스트 | `tests/test_g2b_dag_core.py` |
| 146 | 구현 | Dry-run 통합 테스트 | 실제 수집·투찰 없는 그래프 테스트 실행 | `g2b_dag_api.py` |
| 147 | 부분 | Mock API 서버 연결 | Mock 출력 주입 가능; 독립 HTTP Mock 서버 없음 | `g2b_node_lab.py` |
| 148 | 미구현 | 실제 E2E 회귀 | 노드 전체 실제 API·파일·병렬 Worker 종단간 실행 테스트 없음 | — |
| 149 | 부분 | Checkpoint | 시뮬레이션 실행 상태·그래프 버전 저장; 실제 Worker 체크포인트 미구현 | `g2b_dag_api.py` |
| 150 | 부분 | 세분화 실행 상태 | 시뮬레이터 pending/paused/succeeded/failed/skipped/cancelled; 운영 상태와 통합 미완성 | `g2b_dag_core.py` |
| 151 | 미구현 | 다중 노드 디버깅 패널 | 다중 선택·동시 출력 비교 UI 없음 | — |
| 152 | 미구현 | 실시간 상태 이벤트 | WebSocket/SSE 미구현 (현재 polling) | — |
| 153 | 미구현 | 성능 병목 시각화 | 임계경로·대기시간 그래프 없음 | — |
| 154 | 미구현 | 디버그 결과 내보내기 | 민감정보 마스킹된 zip/json export 없음 | — |
| 155 | 부분 | 세분화 실행 권한 | Bearer 관리자 인증; 조회 테스트 편집 배포 RBAC 구분 없음 | `main.py` |
| 156 | 부분 | 실행 비용·시간 | 테스트 처리시간 ms 저장; API 호출 비용·CPU 등 미수집 | `g2b_node_lab.py` |
| 157 | 부분 | 업로드 보안 | 확장자·PDF/Office 서명·압축폭탄·파일수/크기 제한; 악성코드 AV 및 고급 콘텐츠 검역 없음 | `g2b_node_lab.py` |
| 158 | 부분 | 비밀정보 마스킹 | 토큰 password 필드 및 요청 미저장; 일반 출력의 비밀정보 자동 탐지·마스킹 없음 | `NodeLabPanel.jsx` |
| 159 | 부분 | 노드 워크플로 템플릿 | 기본 1개 편집 가능한 발주 DAG 제공; 템플릿 카탈로그 없음 | `g2b_dag_core.py` |
| 160 | 부분 | 노드 설명 주석 | 노드 이름 및 note 유형 지원; 설명·책임자·운영 지침 모델 미완성 | `DAGEditor.jsx` |

## 적용한 안전 원칙

1. 모든 G2B 업무는 선택 발주정보 `R26BK01787028` 기준이며 사용자가 공식 출처를 덮어써도 원본 증빙으로 인정하지 않는다.
2. Node Lab의 수동 JSON·업로드 파일·Mock 응답은 `test_only` 출처로 저장되며 기존 `g2b_case_evidence` 공식 인증에 반영되지 않는다.
3. 편집 그래프 실행은 **시뮬레이션**에 한정한다. 테스트 결과는 실제 나라장터 입찰 수집·낙찰 분석 완료가 아니다.
4. 그래프는 저장된 버전의 스냅샷으로 테스트하므로 편집 후에도 기존 테스트 내역이 유지된다.
5. 실제 입찰 참가, 전자서명, 투찰 제출은 자동 실행하지 않는다.

## 다음 개발에서 반드시 해결할 핵심 잔여 P0

- 실제 Worker의 병렬 DAG 실행/합류/충돌 제한/재시작 복구
- 수동 값·테스트 파일을 안전한 입력 인터페이스로 받는 실제 업무 기능 핸들러 확장
- 범용 외부 HTTP 연결의 인증 자격증명·SSRF 방지·허용 도메인 제어
- 실제 Worker의 Pause/Resume/Cancel/Replay, 단계별 로그 스트리밍
- JSON Schema 입출력 검증, Golden Output 비교, 실운영 E2E 테스트
- 노드별 권한·테스트 데이터 접근 범위·비밀정보 마스킹·바이러스 검역

현재 일부 핵심 기능이 미완성이므로 **80개 전체 구현완료라고 보고하지 않는다**.
