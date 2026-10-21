# 회사 서버로 옮기기 1단계 - 업체 웹·업데이트 파일 (2026-10-21 준비)

1단계는 **정적 파일만** 옮긴다. 업체 웹(`firebase/web`)과 업데이트 파일(`firebase/releases_site`)이다.
로그인·DB·실시간·버전 목록(stable)은 그대로 Firebase에 남는다 (2단계).

## 미리 해 둔 것

| 무엇 | 어디 |
|---|---|
| 서버 주소 한 곳 | `server_info.py` (JS 는 `firebase/web/firebase-config.js`, `firebase/admin/ops.js` 맨 위 - `tests/test_server_info.py` 가 셋이 같은지 본다) |
| 업데이트 주소 여럿 - 앞 주소에서 못 받으면 다음 주소 | `server_info.UPDATE_FALLBACK_URLS`, `rpa_update.UPDATE_BASE_URLS` |
| 업데이트 주소의 루트 인증서도 미리 받기 (갓 설치한 윈도우) | `firebase/agent/background.py` `ROOT_WARM_URLS` |
| 버전 내보낼 때 회사 서버에도 올리기 | 환경 변수 `RPA_RELEASES_MIRROR` (명령 한 줄, `firebase/releases_site` 에서 돈다) - `tools/publish_release.py` |
| nginx 설정 | `deploy/nginx/autopilot.conf` - 한 도메인에 업체 웹은 `/`, 업데이트는 `/releases/`·`/blobs/` |

이 PC에서 윈도우판 nginx로 그 설정을 띄워 시험했다 (2026-10-21).
- 업체 웹 파일 11개가 모두 열린다. 자바스크립트 형식과 no-cache도 맞다.
- published.json은 보이지 않는다.
- 2026.10.20-4 → 2026.10.21-1 업데이트를 받았다. 앞 주소가 죽어 있어도 다음 주소에서 서명 확인과 바뀐 파일 7개 받기까지 했다.

## 서버를 받은 첫날 (2026-10-21 계획)

서버는 새로 살 수도(리눅스), 기존 서버를 재활용할 수도(윈도우일 수 있음) 있다.

1. **회사에서 받을 것 (사용자 몫)**
   - 접속 방법(VPN 계정), 관리자 계정
   - 공개 주소, 도메인, 인증서 방식
   - 서버 비밀번호는 대화에 싣지 않는다. 사용자가 처음 한 번 넣고, 그 뒤로는 SSH 열쇠로 접속한다.
2. **설치 전에 길부터 확인** - 하나라도 막히면 설치해도 소용없다. 막힌 것을 정리해 회사에 다시 요청한다.
   - 이 PC에서 VPN으로 들어가 OS와 사양을 본다.
   - 서버에서 나가는 443이 되는지 본다 (패키지 저장소, GitHub, 인증서 발급처).
   - 밖에서 들어오는지 본다. 임시 페이지를 띄우고, 회사 와이파이 말고 **휴대폰 데이터로** 연다.
   - 연결을 10분 열어 두고 끊기는지 본다 (LVS·방화벽의 유휴 제한, 5분 이상이어야 한다).
3. **기본 손질**
   - 보안 업데이트를 하고, 방화벽은 들어오는 443·80만 연다.
   - 서버 시각을 자동으로 맞춘다 (NTP). 프리셋 전송 규칙이 서버 시각 ±10분만 받는다.
   - Docker를 설치한다. 윈도우 서버면 먼저 Hyper-V로 우분투 가상 머신을 만든다 (Docker Desktop은 윈도우 서버 미지원).
4. **1단계** - 아래 '서버가 오면 - 순서'. 이것만 해도 Firebase Hosting 저장 공간 문제가 사라진다.
5. **2단계** - 회사 답을 보고 다시 계획한다. Supabase 설치 → **DB 백업·복구 시험 먼저** (토큰 내역은 정산에 쓰인다) → 통신 코드 교체·시험 → 데이터 옮기기·전환 → Firebase와 1주 병행.

## 서버가 오면 - 순서

1. **서버 준비 (회사 인프라)**
   - 도메인 하나와 **공인 인증서**를 준비한다. 자체 서명 인증서면 PC가 업데이트를 받지 못한다.
   - 업체 PC 망에서 443 포트로 닿아야 한다.
   - nginx에 `autopilot.conf`를 넣고 `<도메인>`과 인증서 경로를 바꾼다.
   - `firebase/web` 폴더를 `/srv/autopilot/web`으로 복사한다.
   - `firebase/releases_site` 폴더를 `/srv/autopilot/releases_site`로 복사한다.
2. **확인**
   - 업체 PC 브라우저에서 `https://<도메인>/`을 열어 로그인까지 해 본다. 로그인은 아직 Firebase로 간다.
   - `curl -s https://<도메인>/releases/<최신>/manifest.json | cmp - firebase/releases_site/releases/<최신>/manifest.json`
   - Google Cloud 콘솔에서 웹 API 키에 HTTP 리퍼러 제한이 있다면 새 도메인을 넣는다. 지금은 제한이 없을 것이다 - 확인만 한다.
3. **내보낼 때 같이 올리기**: `RPA_RELEASES_MIRROR`에 사이트 폴더를 서버와 똑같이 맞추는 명령을 넣는다. 지운 버전도 지우는 명령이어야 한다. 실패하면 내보내기가 멈추고, DB 버전 목록은 바뀌지 않는다.
   - 공유 폴더라면: `cmd /c "robocopy . \\서버\autopilot\releases_site /MIR /XF published.json /NJH /NJS & if errorlevel 8 (exit /b 1) else (exit /b 0)"` (robocopy는 1~7도 성공이다)
   - SSH만 된다면: 회사가 준 방법(rsync·WinSCP 동기화 등)에 맞춰 한 줄로 쓴다.
4. **건너가기 버전**
   - `server_info.py`에서 `DASHBOARD_URL = UPDATE_BASE_URL = "https://<도메인>"`로 바꾼다.
   - `UPDATE_FALLBACK_URLS = ("https://rpa-test-f02e0-releases.web.app",)` - 옛 주소를 둔다.
   - `ops.js`의 `DASHBOARD_URL`도 같게 바꾼다. `tests/test_server_info.py`가 맞는지 본다.
   - 빌드 → 샌드박스 → 내보내기. 내보내기는 Firebase와 회사 서버 양쪽에 올라간다. 옛 버전 PC는 옛 주소에서 이 버전을 받고, 그다음부터 새 주소에서 받는다.
   - 새 설치 파일의 업체 웹 바로가기도 새 주소가 된다.
5. **옛 업체 웹 주소 넘기기**
   - 이미 깔린 바로가기는 옛 `*.web.app`을 연다.
   - `firebase/firebase.json`의 `hosting`에 다음을 넣고 `firebase deploy --only hosting`을 한다.
     `"redirects": [{ "source": "/**", "destination": "https://<도메인>/", "type": 301 }]`
6. **정리 (몇 주 뒤)**
   - 관리 화면 PC 표에서 모든 PC가 건너가기 버전 이상인지 본다.
   - 그 뒤 옛 업데이트 호스팅에 올리기를 멈춘다. `_deploy`의 firebase deploy를 끄고 `RPA_RELEASES_MIRROR`만 남긴다.
   - 그다음 버전에서 `UPDATE_FALLBACK_URLS = ()`로 둔다.

## 되돌리기

- **새 서버가 죽으면:** PC는 옛 주소(`UPDATE_FALLBACK_URLS`)에서 받는다. 단, 옛 호스팅에도 계속 올리고 있어야 한다. 그래서 6번 정리는 서두르지 않는다.
- **업체 웹:** 5번의 redirects를 빼고 다시 배포한다.
