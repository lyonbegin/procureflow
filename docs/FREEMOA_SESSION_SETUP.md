# 프리모아 Google 로그인: 최초 1회만 승인

GitHub Actions의 Headless Chrome에서 Google 신규 로그인을 반복하지 않습니다.
일반 Chrome에서 **처음 한 번** 프리모아 Google 로그인을 승인한 다음,
프리모아 도메인의 세션만 GitHub Actions가 재사용합니다.

## Windows 최초 승인

1. [ProcureFlow ZIP](https://github.com/lyonbegin/procureflow/archive/refs/heads/main.zip)을 받아 압축을 풉니다.
2. `tools/authorize_freemoa_once.cmd`를 실행합니다.
3. 새로 열린 **일반 Chrome**에서 프리모아의 Google 로그인을 완료합니다.
4. 해당 Chrome 창을 닫고 명령창에서 Enter를 누릅니다.
5. 프로그램이 실제 프리모아 프로젝트 상세 API에 접속하여 인증을 검사합니다.
6. 인증 성공 직후 프로젝트 최대 10건의 전체 상세를 수집하고 Windows `문서/ProcureFlow/Freemoa/result.json`과 `projects.csv`에 저장합니다.

GitHub CLI(`gh`)가 이미 로그인된 컴퓨터에서는 프로그램이
`FREEMOA_SESSION_B64` GitHub Secret을 등록하고 Actions 수집을 실행합니다.
그렇지 않으면 Secret을 클립보드에 복사하고
[GitHub Secrets 페이지](https://github.com/lyonbegin/procureflow/settings/secrets/actions)를 열어줍니다.
여기서 **Name**은 `FREEMOA_SESSION_B64`, **Secret**에는 클립보드 내용을 붙여넣습니다.

## 이후 자동 실행

[Freemoa Headless Google Login Actions](https://github.com/lyonbegin/procureflow/actions/workflows/freemoa-google.yml)
에서 `Run workflow` > `crawl`을 선택하면 GitHub 서버의 Headless Chrome이
비공개 Secret의 프리모아 세션으로 상세 프로젝트 10건을 차례로 엽니다.
Google 계정 이메일·비밀번호·Google 쿠키·별도의 암호화 키는 GitHub Actions에 제공하지 않습니다.

구글 인증/프리모아 세션이 만료될 때에만 다시 최초 승인 절차가 필요합니다.
프리모아가 다른 IP 또는 데이터센터의 로그인 세션을 제한하면 서버에서
`freemoa_session_expired_or_rejected`로 표시됩니다.

**보안:** `FREEMOA_SESSION_B64`는 인증된 프리모아 세션 자체이므로
비밀번호처럼 취급합니다. 채팅이나 공개 저장소에 붙여넣지 마세요.
Github Actions 공개 로그·아티팩트에는 인증된 원문 상세정보나 쿠키를 올리지 않습니다.

## 현재 상태

GitHub Actions의 실사이트 Google 링크 진입은 성공했습니다.
그러나 Google의 Headless 신규 로그인이 보안상 차단됐으므로,
세션 Secret이 들어오기 전에는 전체 업무내용·모집요건 수집은 성공하지 않습니다.
