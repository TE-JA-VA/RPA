# AFTER MARKET 구조 (지금 돌아가는 것)

**갱신:** 2026-09-22. 이 문서는 **실제로 도는 것**을 적는다. 왜 그렇게 정했는지와 확정 이력은 `docs/superpowers/specs/2026-09-19-firebase-design.md` 에 있다.

**한 줄:** Firebase 는 화면·저장소·로그인을 맡고, 각 PC 의 에이전트가 RPA 를 띄우고 설정 파일을 쓴다. 서버 코드는 없고 **보안은 DB 규칙이 전담한다**.

AFTER MARKET 은 플랫폼 이름이고 RPA 는 그 안의 앱 하나다. 데이터는 `apps/rpa/…`, 화면은 껍데기 + 앱 모듈로 나뉜다. 앱이 하나뿐이라 지금은 앱 고르기가 숨어 있다.

---

## 1. 전체 그림

```
   고객 PC (회사마다, PC 마다)                Firebase (rpa-test-f02e0)            사람 (어디서든)
 ┌────────────────────────────┐          ┌──────────────────────────┐        ┌──────────────────┐
 │ Prepare_RPA.exe            │          │ Realtime DB (싱가포르)    │        │ 브라우저          │
 │ ERPia_RPA.exe              │          │   meta/companies/{회사}   │        │  rpa-test-f02e0  │
 │        │ 상태 파일           │  상태·이력 │   apps/rpa/live/…        │ 구독    │      .web.app    │
 │        ▼                   │ ───────▶ │   apps/rpa/settings/…    │ ◀─────▶│                  │
 │ 에이전트 (python, 콘솔 창)   │          │   apps/rpa/commands/…    │        │  Auth            │
 │   · 5초 heartbeat          │  명령 SSE  │ Firestore (서울)          │  조회   │  (이메일+비밀번호) │
 │   · exe 실행 / ERPia 종료   │ ◀─────── │   runs/{회사}/items/…     │ ◀──────│                  │
 │   · 사용자 설정 쓰기         │          │   users/{uid}            │        └──────────────────┘
 │   · 자동 실행 예약           │          │ Hosting (정적 화면)        │
 └────────────────────────────┘          └──────────────────────────┘
```

에이전트가 꺼져 있으면 화면에서 아무것도 시킬 수 없다. 명령은 10분 뒤 만료된다. 이력은 Firestore 에 남아 PC 를 꺼도 보인다.

## 2. 파일 지도

```
firebase/
  web/       화면 (Hosting 에 그대로 올라간다)
    index.html         껍데기 HTML + 모든 CSS(색 토큰, 밝음/어두움)
    app.js             로그인, 사이드바, 회사·PC 고르기, 앱 mount/unmount
    rpa.js             RPA 앱 화면 (현황/기록 탭, 실행·모듈·자동 실행)
    account.js         계정 페이지 (비밀번호 바꾸기, 강조색)
    theme.js           밝음/어두움 + 강조색 (localStorage)
    firebase-config.js 공개 설정값 + HEARTBEAT_STALE_SEC, COMMAND_TTL_SEC
  agent/     고객 PC 에 들고 가는 것
    agent.py           본체 (상태 올리기, 명령 처리, 이력 업로드, 예약기 기동)
    fb.py              Auth·RTDB·Firestore REST 와 SSE (표준 라이브러리만)
    secret.py          설정 파일 + DPAPI 로 비밀번호 잠그기
    에이전트_시작.bat    관리자 권한 확인 후 agent.py 실행
  rules/     database.rules.json, firestore.rules, firestore.indexes.json
  admin/     우리 PC 전용. setup.js + serviceAccountKey.json (고객 PC 에 절대 금지)
  tests/     rules.test.js, test_agent.py, integration.js, check_web.py, check_setup.py
  design/    시안 (배포 안 함)
  firebase.json, .firebaserc, emu_env.ps1
```

에이전트는 저장소 루트의 **`rpa_status.py` 와 `rpa_dashboard.py` 를 import 해서 쓴다**(복사하지 않는다). `launch`, `stop_erpia`, `apply_schedule`, `SCHEDULER`, `write_routine_modules` 가 전부 거기 있던 것이다. 그래서 배포 폴더에도 이 두 파일이 같이 간다.

## 3. 데이터 경로

Realtime DB
```
meta/companies/{cid}                    { name, stts, pcs: { pcId: { label } } }   stts 0(없음도) 사용 · 9 삭제(비활성)
apps/rpa/live/{cid}/{pcId}              에이전트가 PATCH 로 올리는 현재 상태
                                        { programs, modules, schedule, recent[20], heartbeat, host, server_time }
apps/rpa/settings/{cid}/{pcId}          화면이 요청한 값 { modules, schedule }
apps/rpa/commands/{cid}/{pcId}/{cmdId}  { type, args, by, created_at, expires_at, state, result, … }
```
Firestore
```
runs/{cid}/items/{runId}   실행 이력 한 건 (조회용 필드 + payload JSON)
users/{uid}                { cid, role, name } - 표시용. 권한 근거는 custom claim 이다
```

기준값은 항상 `live` 다. `settings` 는 "이렇게 해 달라" 는 요청이고, PC 가 실제로 반영한 결과가 `live.modules` 와 `live.schedule` 로 돌아온다.

명령 종류는 `launch`, `stop_erpia`, `set_modules`, `set_schedule` 넷이다. 상태는 `queued → running → done|failed`, 늦게 받으면 `expired`.

| 값 | 지금 |
|---|---|
| heartbeat 주기 | 5초 |
| 연결 끊김 판정 | 신호 주기 × 3 + 5초 (새 에이전트 20초, `every` 를 안 올리는 옛 에이전트 95초) |
| 명령 만료 | 600초 |
| 최근 요약 | 20일 |
| 로그 꼬리 | 80줄 |
| 오프라인 큐 | 500건 |

## 4. 로그인과 권한

custom claim 세 가지가 전부다.

| claim | 누구 | 할 수 있는 것 |
|---|---|---|
| `{cid, role:"admin"}` | 회사 관리자 | 자기 회사 보기 + 실행·종료·설정 |
| `{cid, role:"viewer"}` | 열람자 | 자기 회사 보기만 |
| `{cid, pcId, role:"agent"}` | PC 에이전트 | 그 PC 의 live 쓰기, 명령 상태 갱신, 이력 올리기 |
| `{role:"super"}` | 우리 | 전 회사 |

계정은 `firebase/admin/setup.js` 로 우리 PC 에서만 만든다. 자가 가입은 없다.

```
node setup.js company c_demo 테스트업체
node setup.js pc      c_demo pc_a A 컴퓨터
node setup.js user    c_demo <아이디> admin <이름>     # 비밀번호는 무작위로 만들어 한 번만 찍는다
node setup.js agent   c_demo pc_a                    # 회사 코드·PC 이름·비밀번호 세 값이 나온다
node setup.js passwd  c_demo <아이디>                  # 새 비밀번호. disable / enable / show / list 도 있다
node setup.js remove  c_demo                         # 업체 삭제(비활성): stts=9 + 그 업체 계정 전부 막음. 자료는 남는다
node setup.js restore c_demo                         # 되살림: stts=0 + 계정 다시 엶
```

삭제된 업체(stts=9)에는 pc·user·agent 를 만들 수 없고, 남은 토큰으로 화면에 들어와도 "사용이 중지된 업체입니다" 로 내보낸다. 에이전트는 계정이 막혀 1시간 안에 멈춘다.

이메일은 `<아이디>@<회사 코드>.rpa-test-f02e0.firebaseapp.com` 으로 조립한다(밑줄은 하이픈, 기계 계정은 `agent-<pcId>`). 같은 규칙이 `agent.py`, `app.js`, `setup.js` 에 한 줄씩 있다.

**서버 코드가 없으므로 규칙이 유일한 방어선이다.** 규칙을 고치면 `tests/rules.test.js` 를 반드시 돌린다. 화면 코드에서 버튼을 숨기는 것은 편의일 뿐 보안이 아니다.

## 5. 에이전트가 하는 일

- 1초마다 `rpa_status` 상태 파일을 보고 바뀌었을 때만 `live` 를 PATCH 한다.
- 5초마다 heartbeat. 신호에 주기(`every`)를 같이 올리고, 화면은 그 값으로 끊김 기준을 잡는다. 그래서 아직 안 고친 PC 가 30초마다 보내도 깜빡이지 않는다.
- `history.jsonl` 에 새 줄이 생기면 Firestore 에 올린다. 어디까지 올렸는지는 `history_pos.txt` 에 바이트 위치로 남겨 다시 켜도 이어서 간다.
- 명령은 SSE 로 받는다. 끊기면 1초부터 60초까지 늘려 가며 다시 붙는다. 로그인 토큰이 1시간마다 만료되면 Firebase 가 `auth_revoked` 를 보내고, 그러면 토큰을 새로 받아 바로 다시 붙는다. 90초 넘게 아무것도(keep-alive 포함) 안 오면 죽은 연결로 보고 다시 붙는다.
- 못 올린 것은 `queue.jsonl` 에 쌓고 연결되면 순서대로 보낸다. 규칙이 거부한 것은 버린다. 기록 실패가 RPA 를 막는 일은 없다.
- **자동 실행 예약기를 에이전트가 띄운다.** 그래서 옛 8765 대시보드(`RPA_Dashboard.exe`, `대시보드_시작.bat`)와 같이 띄우면 예약이 두 번 돈다. 배포 폴더에서 옛 대시보드를 빼 둔 이유가 이것이다.
- 로그인 모듈은 항상 켬으로 고정한다. 화면에서도 잠겨 있고 에이전트도 `Login=Y` 로 덮어쓴다.
- 켤 때 사용자 설정을 한 파일로 옮긴다. 아래 '사용자 설정' 참고.

### 사용자 설정: `RPA_UserConfig.json`

업체마다 사람이 정하는 값은 배포 폴더 루트(exe 옆)의 이 파일 하나에 있다. 개발 PC 는 `dist\` 에 있다.

```json
{"LogIn":    {"AdminCode": "…", "ID": "…", "PW": "dpapi:…"},
 "Routine":  {"Login": "Y", "Sales": "Y", "Hold": "N", "Logistics": "Y", "Output": "Y"},
 "Logistic": {"cboBS_Auto_YN": "…", "Printer": "…", "cboTag": "…", "cboTagAmt": "…", "cboBeasong_Gu_Apply": "…"},
 "Sites":    {"SITE1": {"URL": "…", "ID": "…", "PW": "dpapi:…", "Action": ["…"], "Stts": 0, "…": "…"}},
 "ERPia":    {"ExePath": "C:/Program Files (x86)/OneZeroSoft/ERPiaNet/ERPiaMain.exe"}}
```

- 예전의 `ERPIA_AI.txt`(바탕화면, 로그인·물류·모듈), `WebManageConfig.json`(exe 옆, 사이트), `login_manager_config.json`(exe 옆, ERPia 위치 `exe_path`)을 합친 것이다. 에이전트가 켤 때 이 파일이 없으면 옛 파일들을 합쳐 만들고 옛 파일은 `.old` 로 바꾼다. `.old` 에는 평문 비밀번호가 있으니 RPA 가 잘 도는 것을 본 뒤 지운다.
- 비밀번호(`PW`)는 DPAPI 로 잠가 `dpapi:…` 로 넣는다. 그 PC·그 윈도우 계정에서만 풀린다. 평문으로 적어도 읽히고, 에이전트가 켤 때 잠근다. 다른 PC 에서 잠근 값은 못 푸니 파일째 옮기지 말고 평문으로 다시 적는다.
- 읽는 곳은 `rpa_status` 한 곳이다(`read_user_config`). 이 파일이 없으면 옛 파일들을 읽으므로 exe 만 먼저 바꿔도 돈다. 비밀번호는 로그인하는 곳(`perform_login.load_credentials`, `web_runner.load_config`)에서만 푼다.
- **ERPia 위치(`ERPia.ExePath`)** 는 적힌 값이 틀리면 설치 기록(제어판 '프로그램 제거' 목록의 설치 폴더)과 기본 설치 폴더에서 `ERPiaMain.exe` 를 찾아 고쳐 적는다. 그래도 없으면 **사람이 있을 때만** 파일 고르는 창을 띄운다: 에이전트 창을 켤 때, 또는 루틴을 직접 실행할 때. 대시보드·에이전트·예약이 띄운 실행은 `RPA_UNATTENDED=1` 이 붙어 창을 띄우지 않고 바로 멈춘다(아무도 없는 PC 에서 창 앞에 멈추면 안 된다). ERPia 가 이미 떠 있으면 위치는 보지 않는다.

첫 실행에는 설정 파일이 없으므로 회사 코드·PC 이름·비밀번호를 묻고(`setup.js agent` 가 찍어 준 세 값) 이메일은 프로그램이 조립한다. 로그인해 보고 토큰의 회사·PC 가 친 값과 같아야 `agent_config.json` 을 만든다. 돌다가 인증이 죽으면(비밀번호 교체·계정 막힘) 멈추고 이유를 찍은 뒤 창에서 새 비밀번호를 다시 묻는다. 비밀번호는 DPAPI 로 그 PC, 그 윈도우 계정에서만 풀리게 잠긴다. 사람 계정으로는 거부한다.

## 6. 화면

- `app.js` 가 껍데기다. 로그인, 사이드바, 회사 이름, PC 고르기, 앱 mount 를 맡는다.
- 앱 모듈은 `key/label/icon/perPc/mount(root, ctx)/unmount()` 를 내보낸다. 새 앱을 붙이려면 파일 하나를 만들고 `APPS` 에 넣으면 된다.
- 관리자가 아니면 오른쪽 열이 통째로 빠지고 본문이 그 폭을 쓴다.
- 색은 `index.html` 의 토큰 한 곳에서 정한다. 상태색은 성공 초록, 진행 파랑, 실패 빨강, 오류 노랑이다. 강조색은 사용자가 계정 페이지에서 고른다.
- 상태 이름은 세 가지뿐이다. **성공**(success), **실패**(stopped·failed: 단계 검사에서 스스로 멈춤, 사용자 중지 포함), **오류**(crashed: 프로그램이 죽음). 상태 카드, 도넛 범례, 기록 표가 모두 같은 말을 쓴다. 실패는 데이터를 보고, 오류는 PC 를 본다.
- 배포 뒤 옛 화면이 남지 않게 js·html 에 `Cache-Control: no-cache` 를 걸어 두었다.

## 7. 새 PC 붙이기

1. 우리 PC 에서 `setup.js pc` 와 `setup.js agent` 로 PC 와 기계 계정을 만든다.
2. 배포 폴더(지금 본은 `D:\AX\배포_20260928_3`, 같은 이름의 zip 도 있다)를 통째로 복사한다. 옛 대시보드는 넣지 않는다.
3. `RPA_UserConfig.json` 을 그 업체 값으로 맞춘다. 비밀번호는 평문으로 적으면 에이전트가 처음 켤 때 잠근다. ERPia 위치는 에이전트가 켤 때 찾고, 못 찾으면 고르는 창을 띄운다.
4. `firebase\agent\에이전트_시작.bat` 을 실행하고 1번에서 받은 회사 코드·PC 이름·비밀번호를 넣는다.
5. 대시보드에서 그 PC 를 고른다. PC 가 둘 이상이면 제목 옆에 고르는 칸이 생긴다.

자세한 절차는 배포 폴더의 `클라우드_안내.txt` 에 있다.

## 8. 고치고 시험하기

에뮬레이터는 Java 21 이 필요하다. 창마다 `. .\emu_env.ps1` 로 그 창에서만 앞세운다. 시스템 Java 8 은 건드리지 않는다.

```powershell
cd D:\AX\RPA\firebase; . .\emu_env.ps1
python tests\test_agent.py                      # 에이전트 단위 (Firebase 없이)
cd tests; npm test                              # 규칙
firebase emulators:exec --config ../firebase.json --only auth,database,firestore          --project rpa-test-f02e0 "node integration.js"
firebase emulators:exec --config ../firebase.json --only auth,database,firestore,hosting  --project rpa-test-f02e0 "python check_web.py"
firebase emulators:exec --config ../firebase.json --only auth,database,firestore          --project rpa-test-f02e0 "python check_setup.py"
cd ..; firebase deploy --only hosting --config firebase.json
```

| 시험 | 건수 | 보는 것 |
|---|---|---|
| 규칙 | 24 | 다른 회사·열람자·위조 거부, 명령 상태 전이 |
| 에이전트 단위 | 123 | 큐, 토큰, 인증 거부·망 오류 구분, 명령 선점, 세 칸 첫 실행 |
| 통합 | 30 | 에뮬레이터에 에이전트를 붙여 명령 왕복, 사용자 설정 옮기기·잠금·모듈 쓰기·ERPia 위치 |
| 화면 | 221 | Playwright. 대비 4.5:1, 띠, 기록 탭, 권한별 화면, 세 칸 로그인, 이스케이프, 삭제된 업체·막힌 계정 안내 |
| 관리 스크립트 | 23 | setup.js 를 에뮬레이터에 대고 등록 → remove(stts=9, 계정 막힘, 새 등록 거부) → restore |

에뮬레이터 명령에는 항상 `--config ../firebase.json` 이 붙는다. 화면을 에뮬레이터로 볼 때는 주소 뒤에 `?emu=1` 을 붙인다.

## 9. 비밀 취급

- `RPA_UserConfig.json` 의 비밀번호는 DPAPI 로 잠겨 있지만 **PC 밖으로 내보내지 않는다.** 클라우드에는 모듈 켬/끔 값만 오간다. 옮기고 남은 `ERPIA_AI.txt.old`, `WebManageConfig.json.old` 에는 평문이 있으니 확인 뒤 지운다 (`login_manager_config.json.old` 는 ERPia 위치뿐).
- `serviceAccountKey.json` 은 규칙을 우회하는 만능 열쇠다. `firebase/admin/` 에만 두고 고객 PC 에 복사하지 않는다.
- `agent_config.json`, `queue.jsonl`, `history_pos.txt`, 에이전트 기록은 모두 gitignore 다.
- 비밀번호는 `setup.js` 가 무작위로 만들어 한 번만 찍는다. 명령줄에 없으니 이력에 남지 않는다. 예전 이력에 남은 것은 `Remove-Item (Get-PSReadLineOption).HistorySavePath` 로 저장 파일을 지운다 (`Clear-History` 는 세션 버퍼만 비운다).
- PC 를 빼거나 담당자가 바뀌면 `setup.js disable` 또는 `passwd`. 업체와 계약이 끝나면 `setup.js remove <cid>` (계정 전부 막힘, 자료는 남음). 이미 받은 토큰은 최대 1시간 산다.

## 10. 아직 안 한 것

- 첫 로그인 때 비밀번호 변경 강제 (`must_change_password` 는 자리만 있다)
- 총괄(super)의 회사 목록 화면. 지금은 회사가 하나라 안 쓴다
- 실패했을 때 알림
- 배송장 생성·주문 수집 건수 정확히 세기 (루틴 RPA 수정 + exe 재빌드 필요)
- 옛 `rpa_dashboard.py` 8765 대시보드를 언제 접을지
