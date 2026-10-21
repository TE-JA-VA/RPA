# 서버 옮기기 전담 세션 안내 (2026-10-21)

오토파일럿을 Firebase에서 **회사 서버**로 옮기는 일을 맡은 세션이 처음 읽는 문서다.
- 회사가 서버 한 대를 줄 수도 있다. 망은 회사 내부망과 분리된 별도 망이고, DB도 직접 구축해야 한다고 한다.
- 아직 서버는 없고, 회사의 답을 기다린다.

## 1. 먼저 읽을 것

| 문서 | 무엇 |
|---|---|
| [firebase-architecture.md](firebase-architecture.md) | 지금 도는 구조 - 데이터 경로·권한(claim)·에이전트가 하는 일 |
| [server-move-stage1.md](server-move-stage1.md) | 1단계(정적 파일) - 미리 해 둔 것과 서버가 오면 할 순서 |
| [TODO.md](TODO.md) | 다른 미룬 일 (서버 옮기기 줄 포함) |
| [admin-web-transition.md](admin-web-transition.md) | 관리 화면을 웹으로 옮기는 순서 (Firebase Blaze 기준 - 회사 서버로 가면 다시 판단) |
| `server_info.py` | 서버 주소 한 곳. JS 쪽은 `firebase/web/firebase-config.js`, `firebase/admin/ops.js` 맨 위 |

## 2. 반드시 지킬 것

이 저장소의 규칙이다. 메모리(`MEMORY.md`)에도 있다.

- **답은 한국어 쉬운 말로만** 한다. 영어로 답하면 사용자가 지적한다. '판'이 아니라 **'버전'**이라고 한다.
- **비밀은 읽지도 옮기지도 않는다.** 아래 파일은 열거나 출력하지 않는다.
  - `RPA_UserConfig.json`, 실제 `RPA_Presets.json`, `ERPIA_AI.txt`
  - `WebManageConfig.json`, `agent_config.json`
  - `firebase/admin/serviceAccountKey.json`, `firebase/admin/update_signing_key.txt`
  - 비밀번호·키는 대화·기록·커밋·인자·결과에 싣지 않는다.
- **이 저장소는 공개 저장소다.** 회사 내부 정보, 서버 주소, 계정을 문서나 커밋에 넣지 않는다. 회사용 보고서는 저장소 밖에 둔다.
- **실서버 계정은 만들지 않는다.** 시험은 에뮬레이터나 이 PC의 로컬 환경에서 한다. 개발 PC에서 setup.exe를 돌리지 않는다.
- **배포·내보내기·규칙 배포는 사용자가 확인한 뒤에만** 한다.
- **커밋·푸시는 사용자가 말할 때만** 한다.
  - 작업은 develop에서 한다. main은 `ALLOW_MAIN_PUSH=1`로만 올린다. `--no-verify`는 쓰지 않는다.
- **버전 내보내기 순서:** 빌드(`tools/build_release.py`, 번호는 자동) → 샌드박스(`tools/sandbox_test.py --update <설치 파일>`) → 통과하면 내보내기(`echo 예 | python tools/publish_release.py <버전> "<메모>"`) → 보고.
- **코드를 고친 뒤:**
  - `graphify update .`를 돌린다.
  - .bat 파일은 CP949+CRLF로 저장한다.
  - 파이썬으로 패치할 때는 Write 도구로 파일을 만든 뒤 실행한다. heredoc은 글자가 깨진다.
- **실제 사이트를 직접 두드리지 않는다.** 네이버·쿠팡이 대상이다.

## 3. Firebase를 쓰는 곳 (2단계에서 바꿀 것 전부)

| Firebase 기능 | 쓰는 곳 | 하는 일 |
|---|---|---|
| **Auth** (이메일+비밀번호, custom claim `cid`·`role`·`pcId`) | 에이전트 `firebase/agent/fb.py`, 업체 웹 `firebase/web/app.js`, 관리 `firebase/admin/ops.js` (Admin SDK) | 업체 관리자·열람자·PC 에이전트·휴대폰·총괄(super) 로그인. 이메일은 `<아이디>@<업체>.<AUTH_DOMAIN>`으로 조립 |
| **Realtime DB** | `meta/companies`, `apps/rpa/{live,settings,commands,transfers}`, `apps/otp/{requests,codes,phones}` | 현황(에이전트 → 화면), 설정 요청, 명령(화면 → 에이전트, SSE 구독), 프리셋 전송, 휴대폰 인증번호 중계 |
| **Firestore** | `runs/{cid}/items` (실행 기록), `wallet/{cid}` (토큰 통장), `meta/prices` (토큰 배율), `users/{uid}` | 기록 조회, 남은 토큰 = 넣은 양 - 기록 cost 합 (서버 합계 질의) |
| **보안 규칙** | `firebase/rules/database.rules.json`, `firestore.rules` | **서버 코드가 없어서 규칙이 유일한 방어선이다.** 옮기면 서버 API나 DB 권한(RLS)이 그대로 넘겨받아야 한다. 시험: `firebase/tests/rules.test.js` |
| **Hosting** | 업체 웹 `firebase/web`, 업데이트 `firebase/releases_site` | 1단계에서 옮긴다 (준비 끝) |
| **Functions** | `firebase/functions` (관리 화면 웹, Blaze가 있어야 해서 아직 안 씀) | 회사 서버로 가면 그 서버의 API로 대신할 수 있다 |

다음 것도 Firebase에 직접 붙는다. 2단계에서 같이 바꿔야 한다.
- `otp_relay.py`: ACTOR가 인증번호를 기다린다.
- 휴대폰 쪽 중계: 설계는 `docs/superpowers/specs/2026-10-12-phone-otp-relay-design.md`. 휴대폰 쪽(안드로이드 앱 `AUTOPILOT_AND`, 아이폰 단축어 `AUTOPILOT_IOS`, 약속 `CONTRACT.md`)은 **비공개 저장소 `TE-JA-VA/RPA-PhoneRelay`** 에 있다 (맥에서 만들고 빌드, 이 PC 에는 사본 없음). Firebase REST 로 직접 붙으므로 2단계에서 새 서버 주소·로그인으로 바꿔야 한다. 약속이 바뀌면 이 저장소의 규칙·`check_phone_relay.py` 를 먼저 바꾸고 그쪽 `CONTRACT.md`·앱을 맞춘다.
- 관리 화면 `firebase/admin` (Admin SDK + 서비스 계정 키).

## 4. 지금까지 한 것

- **0단계 (2026-10-21, 7cd3e26):** 코드 여러 곳에 박혀 있던 프로젝트 이름과 주소를 `server_info.py` 한 곳으로 모았다. `tests/test_server_info.py`가 세 곳(파이썬·업체 웹·관리 화면)이 같은지 본다.
- **1단계 준비 (bb469ec, 버전 2026.10.21-3에 실림):**
  - 업데이트 주소를 여러 개 둘 수 있다. 앞 주소가 안 되면 다음 주소로 받는다.
  - 업데이트 주소의 인증서도 미리 받는다.
  - 내보낼 때 회사 서버에도 올린다 (`RPA_RELEASES_MIRROR`).
  - nginx 설정 `deploy/nginx/autopilot.conf`
  - 이 PC에서 윈도우판 nginx로 시험해 통과했다.
- **주의 1:** 업데이트 도우미는 파일 몇 개만 runner 폴더로 복사해서 돈다 (`rpa_update.RUNNER_FILES`). 그 파일들이 부르는 모듈을 더하면 목록에도 넣는다. `tests/test_rpa_update.py`가 검사한다. server_info를 빠뜨려 샌드박스에서 업데이트가 실패한 적이 있다.
- **주의 2:** 설치된 PC는 첫 설정 때 `project_id`·`api_key`·`database_url`을 `agent_config.json`에 적어 둔다 (`firebase/agent/secret.py`의 `PUBLIC`). 2단계로 옮길 때는 그 값까지 바꾸는 **건너가기 버전**이 필요하다. 파일을 열어 보지 말고 코드로 처리한다.

## 5. 2단계 방향 (아직 결정 전 - 사용자와 정할 것)

- **추천:** 회사 서버에 **Supabase를 직접 설치**한다(Docker Compose) + nginx(HTTPS).
  - PostgreSQL이 Firestore를 대신한다.
  - Realtime이 RTDB 구독을 대신한다.
  - GoTrue가 Auth를 대신한다.
  - 행 단위 권한(RLS)이 보안 규칙을 대신한다.
- **에이전트:** `fb.py` 한 파일을 바꿔 끼우는 구조다. `agent.py`는 `client.get/put/patch/delete/stream/fs_*`만 부른다.
- **업체 웹·관리 화면:** Firebase SDK를 쓰는 데이터 부분을 다시 쓴다.
- **계정 옮기기:** Firebase Auth는 비밀번호 해시(scrypt 변형)를 내보낼 수 있다. 새 쪽이 그 방식을 확인할 수 없으면 재설정이 필요하다. **확인할 것.**
- **서버 없이 먼저 할 수 있는 것:** 이 PC에 Docker Desktop이 깔려 있다. 그 위에 Supabase를 띄워 코드 교체·시험·데이터 옮기기 스크립트를 미리 만들 수 있다.
  - 단, 회사 망 구성이 정해지기 전에 깊이 들어가면 다시 손볼 수 있다. 사용자는 **"2단계는 회사 답이 온 뒤"**로 정했다.
- 사람 기준으로 어림하면 3~6배 크게 나온다 (메모리 `plan-time-estimates`). 실제는 훨씬 빠르다.

## 6. 기다리는 것

- **회사 답** (사용자가 회사에 전달할 요청서는 저장소 밖에 있다: 사용자 다운로드 폴더 `오토파일럿_서버이전_요청서.docx`):
  - LCM이 무엇을 뜻하는지
  - 별도 망에서 인터넷으로 나가고 들어오는 방식 (업체 PC가 443으로 닿아야 한다)
  - 도메인과 공인 인증서
  - 부하 분산 장치(LVS)의 연결 유지 시간 (실시간 구독이 오래 열린 연결을 쓴다)
  - DB 백업과 장애 담당
  - 서버 사양 (GPU 여부 - 아래 LLM 건)
  - 서버 OS - 새 서버(리눅스) 또는 기존 서버 재활용(윈도우일 수 있음, 2026-10-21 사용자). 윈도우 서버면 Hyper-V 리눅스 가상 머신 안에 Supabase 를 둔다 (Docker Desktop 은 윈도우 서버 미지원). 그 서버가 이미 가상 머신이면 중첩 가상화가 필요하다. Hyper-V 를 못 쓰면 PostgreSQL 윈도우판 + Node 로 로그인·권한·실시간을 직접 만드는 길 (일이 크게 는다)
- **Issue #16:** 다른 작업자가 만든 '옵저버가 막히면 로컬 LLM이 넘기기'를 서버에서 돌릴 수 있는지 묻는 다섯 질문. 답이 오면 사용자가 전해 준다.
  - 서버에 올린다면 Ollama를 우리 API 뒤에 인증과 함께 둔다.
  - LLM이 할 수 있는 동작은 허용 목록으로 묶는다.
  - **캡차 풀기에는 쓰지 않는다.**

## 7. 시험 명령 (bash)

```bash
J=/c/Users/20251216-003/.devtools/jdk-21; export JAVA_HOME="C:\\Users\\20251216-003\\.devtools\\jdk-21" PATH="$J/bin:$PATH" PYTHONIOENCODING=utf-8
cd firebase/tests && npm test                                    # 규칙 (에뮬레이터)
firebase emulators:exec --config ../firebase.json --only auth,database,firestore --project rpa-test-f02e0 "D:/AX/RPA/.venv/Scripts/python.exe check_admin.py"
firebase emulators:exec --config ../firebase.json --only auth,database,firestore,hosting --project rpa-test-f02e0 "D:/AX/RPA/.venv/Scripts/python.exe check_web.py"   # 화면 시험은 Edge 창이 뜬다 - 사용자에게 먼저 알린다
cd firebase/tests && ../../.venv/Scripts/python.exe test_agent.py                    # 에이전트 (이 폴더에서)
cd /d/AX/RPA && .venv/Scripts/python.exe tests/test_server_info.py && .venv/Scripts/python.exe tests/test_rpa_update.py
```
