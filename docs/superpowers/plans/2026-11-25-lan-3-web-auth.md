# 사내 서버 ③ 웹 인증 보강 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사내 서버 웹에 2단계 인증(TOTP, 등록·로그인·복구 번호·관리자가 풀어 주기), '보안' 설정(범위·유저 이력 보이기), 로그인 이력(DB 저장과 조회 창구)을 서버 쪽에 만든다. 화면은 ⑥.

**Architecture:** 새 모듈 셋 - `totp`(RFC 6238 계산·복구 번호, 상태 없음), `web_security`(security.json 의 '보안' 설정), `login_log`(logins.db SQLite 이력). 계정 파일은 버전 2 로 올려 계정마다 `mfa` 칸을 두고, `local_web.Web` 이 로그인 두 단계(비밀번호 → 5분 표 → 번호), 등록 강제, 보안 설정·이력 창구를 붙인다. 모두 **사내 서버(`Web.registry` 있음)에서만** 켜진다 - 단독(나)은 응답·파일·동작이 지금과 같다.

**Tech Stack:** 파이썬 3.14 표준 라이브러리(`hmac`, `hashlib`, `base64`, `struct`, `secrets`, `sqlite3`), 시험은 저장소 관례 plain python (`[통과]`/`[실패]`, 끝에 `실패: N`).

**Spec:** `docs/superpowers/specs/2026-11-24-standalone-linux-server-design.md` 6.6 '2단계 인증'·'로그인 이력'·'사내망으로 넓어지며 더 막는 것'(관리자 비밀번호 10자), 6.5 끝(보관 기간), 10절 개발 PC 줄, 12절 7·8, 13절 12·13, 14절 ③. 목록 `docs/superpowers/plans/2026-11-24-lan-index.md`.

## Global Constraints

- 작업 폴더 `D:\AX\RPA_StandAlone`, 브랜치 `StandAlone`. 파이썬 `D:\AX\RPA\.venv\Scripts\python.exe`, cwd 는 작업 폴더, `$env:PYTHONUTF8="1"`. `D:\AX\RPA` 의 파일은 절대 고치지 않는다.
- 단독(나)은 그대로: `Web(registry=None)` 의 응답·상수·파일이 지금과 같다 (security.json·logins.db 를 만들지 않고, 새 창구는 404). `run_standalone_suite.py all` 이 '실패한 파일: 0'.
- 표준 라이브러리만, 바깥 연결 없음. QR 은 서버가 그리지 않는다 - `otpauth://` 글만 준다 (화면 ⑥ 이 `qr.js` 로 그린다).
- 숫자 (설계·Claude 판단): 번호 6자리, 30초, 앞뒤 한 칸, 한 번 쓴 칸은 다시 안 받음. 비밀 값 20바이트(base32 32자). 복구 번호 8개 `xxxxx-xxxxx` (base32 소문자 10자). 로그인 표 5분. 이력 보관 365일. 사내 서버 관리자 비밀번호 10자 이상(유저는 8자 그대로). 보안 기본값 `totp_scope="admin"`, `show_own_history=True`.
- 2단계 비밀 값·복구 번호·비밀번호·세션 토큰·로그인 표는 기록·이력·응답에 싣지 않는다. 예외 둘: 등록 시작 응답의 비밀 값(QR 용, 한 번), 등록 완료 응답의 복구 번호 8개(한 번).
- 틀린 2단계 번호·복구 번호는 틀린 비밀번호와 같이 센다 - 아이디 잠금(`_pair`), 아이디 전체(`id_lock`), 주소 잠금(`addr_lock`). 확인은 `_login_lock` 안에서, 잠금 확인 뒤에.
- 화면 글은 한국어 업무 말투, '버전' 사용·'묶음' 금지. 커밋은 작업마다 `git commit -F <새 파일 이름>` (메시지 파일 이름은 작업마다 새로), BOM 없이, 끝줄 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. push 는 사용자 말이 있을 때만.
- 끝나면 `graphify update .`.

## Review Focus

1. 비밀번호를 바꾸거나(본인), 관리자가 다시 정하거나, 사용 중지·다시 사용·권한 유지 저장을 해도 2단계 칸이 그대로 남는다 (13절 12) - Task 2 `test_mfa_survives_writes`.
2. 로그인 표를 다른 주소에서, 5분 뒤에, 두 번째로 쓰면 거절된다. 비밀번호가 바뀌었거나 중지된 계정의 표도 거절 - Task 3 `test_ticket_rules`.
3. 같은 30초 번호를 두 탭이 동시에 보내면 하나만 세션을 받는다 (쓴 칸 기록이 계정 잠금 안에서 한 번에) - Task 3 `test_same_code_race`.
4. 범위를 '모든 계정 필수' 로 올린 순간, 이미 로그인한 등록 안 된 유저 세션도 다음 요청부터 등록 창구만 쓴다 (범위는 요청마다 읽는다) - Task 4 `test_scope_raise_live_session`.
5. 응답·서버 기록·이력·security.json 어디에도 비밀 값(등록 시작 응답 제외)·복구 번호(등록 완료 응답 제외)·비밀번호·표가 없다 - Task 5 `test_no_secret_leaks`.

---

## 파일

| 파일 | 맡는 일 |
|---|---|
| `firebase/agent/totp.py` (새) | RFC 6238 번호 계산·맞추기, 비밀 값·복구 번호 만들기·해시, otpauth 글 |
| `firebase/agent/web_security.py` (새) | `security.json` 의 '보안' 설정 읽기·쓰기 |
| `firebase/agent/login_log.py` (새) | `logins.db` 로그인 이력 - 넣기·찾기·지우기, 브라우저 종류 |
| `firebase/agent/local_web.py` | 계정 파일 버전 2, 관리자 10자, 로그인 두 단계, 등록 강제, 새 창구 |
| `tools/build_release.py` | 배포 목록에 새 모듈 셋 |
| `tests/test_totp.py`, `tests/test_accounts_v2.py`, `tests/test_lan_mfa.py`, `tests/test_login_log.py` (새) | 시험 |
| `tests/run_standalone_suite.py` | SA 목록에 새 시험 넷 |

---

### Task 1: TOTP 계산 (`totp.py`)

**Files:** Create `firebase/agent/totp.py`, `tests/test_totp.py`

**Interfaces:**
- Produces:
  - 상수 `STEP=30`, `DIGITS=6`, `WINDOW=1`, `SECRET_BYTES=20`, `RECOVERY_COUNT=8`, `ISSUER="오토파일럿"`
  - `new_secret() -> str` (base32 대문자, `=` 없음, 32자)
  - `step_of(now: float) -> int` (`int(now // STEP)`)
  - `code_at(secret: str, step: int, digits: int = DIGITS) -> str` (HMAC-SHA1, RFC 4226 동적 자르기, 앞 0 채움)
  - `match(secret: str, code: str, now: float, last_step: int | None) -> int | None` - 공백을 뺀 6자리 숫자 글만, `step_of(now)-WINDOW .. +WINDOW` 칸 중 맞는 칸을 돌려준다. 그 칸이 `last_step` 이하면 None (한 번 쓴 칸). 비교는 `hmac.compare_digest`.
  - `otpauth_uri(secret: str, account: str, issuer: str = ISSUER) -> str` - `otpauth://totp/<quote(issuer:account)>?secret=..&issuer=<quote>&algorithm=SHA1&digits=6&period=30`
  - `new_recovery_codes(n: int = RECOVERY_COUNT) -> list[str]` - `"xxxxx-xxxxx"`, 글자는 `abcdefghijklmnopqrstuvwxyz234567`, 서로 다름
  - `recovery_hash(salt_hex: str, code: str) -> str` - 소문자로, 공백·`-` 를 뺀 뒤 `sha256(bytes.fromhex(salt_hex) + norm)` hex. 꼴이 틀린 글(10자 base32 아님)은 `""`.

- [ ] **Step 1: 시험** `tests/test_totp.py`
  - `test_rfc6238_vectors`: 비밀 값 = `base64.b32encode(b"12345678901234567890")`. `code_at(s, step_of(t), 8)` 이 t=59 → `"94287082"`, 1111111109 → `"07081804"`, 1111111111 → `"14050471"`, 1234567890 → `"89005924"`, 2000000000 → `"69279037"`, 20000000000 → `"65353130"`. 6자리는 그 끝 6자 (`"287082"` 등).
  - `test_window_and_replay`: now 에서 만든 번호를 `match(..., now+30, None)` → 그 칸, `now+61` → None, `now-30` 쪽도 한 칸. `last_step=그 칸` 이면 None. `" 287 082 "` 공백은 받고 `"28708a"`·`"2870821"`·`None` 은 None.
  - `test_secret_and_uri`: `new_secret()` 32자·base32 로 풀면 20바이트, 두 번 부르면 다름. uri 가 `otpauth://totp/` 로 시작하고 `secret=<비밀>`·`period=30`·`digits=6` 을 담고 계정 이름이 퍼센트 인코딩.
  - `test_recovery`: 8개, 모두 `[a-z2-7]{5}-[a-z2-7]{5}`, 서로 다름. 같은 소금에서 `recovery_hash(s, "ABCDE-fghij")` == `recovery_hash(s, "abcdefghij")`, 소금이 다르면 다름, `"abc"` → `""`.
- [ ] **Step 2:** `D:\AX\RPA\.venv\Scripts\python.exe tests\test_totp.py` → 모듈 없음으로 실패.
- [ ] **Step 3:** `totp.py` 구현 (위 Interfaces 그대로, 표준 라이브러리만, 모듈 설명글 한국어).
- [ ] **Step 4:** 같은 명령 → `실패: 0`. WSL 에서도 `wsl.exe -d Ubuntu -e python3 /mnt/d/AX/RPA_StandAlone/tests/test_totp.py` → `실패: 0`.
- [ ] **Step 5: 커밋** `사내 서버 ③ Task 1 - TOTP 계산(RFC 6238 6자리 30초 앞뒤 한 칸·쓴 칸 거절)·복구 번호 8개·otpauth 글, 시험 test_totp`

---

### Task 2: 계정 파일 버전 2 (`local_web.Accounts`)

**Files:** Modify `firebase/agent/local_web.py` (`Accounts`, `_check_password`, `Web.__init__`), Create `tests/test_accounts_v2.py`

**Interfaces:**
- Consumes: `totp.new_recovery_codes`, `totp.recovery_hash`, `totp.match`
- Produces (모두 `Accounts` 메서드, 계정 잠금 안에서 읽고 쓰기를 한 번에):
  - 파일 `{"version": 2, "accounts": {...}}`. 계정 기록에 선택 칸 `mfa = {"secret": str, "last_step": int, "salt": hex, "recovery": [hash, ...], "enabled_at": ms}`. 버전 1 파일도 그대로 읽고, 다음 저장 때 2 로 쓴다.
  - `_public` 에 `"mfa": bool` (켜져 있나) 를 더한다 - 비밀 값·해시는 어디에도 안 나간다. `rev` 는 지금처럼 비밀번호 기록에서만 (2단계를 바꿔도 세션 rev 는 그대로 - 세션 닫기는 Web 이 한다).
  - `admin_min: int` 속성 (기본 `PASSWORD_MIN`=8). `_check_password(password, minimum=PASSWORD_MIN)`. `set`·`add`·`change_password` 는 그 계정 권한이 `admin` 이면 `admin_min` 으로 본다. 모자라면 `WeakPassword(f"관리자 비밀번호는 {admin_min}자 이상으로 입력하여 주십시오.")`.
  - `mfa_secret(id) -> str | None` (서버 안에서만)
  - `mfa_check(id, code: str, now: float) -> bool` - `totp.match` 로 맞추고 맞으면 `last_step` 을 그 칸으로 저장 (같은 칸 두 번째는 False)
  - `mfa_enable(id, secret: str, code: str, now: float) -> list[str] | None` - 번호가 맞으면 새 복구 번호 8개를 만들어 해시만 저장, `last_step`·`enabled_at` 적고 복구 번호 글을 돌려준다. 틀리면 None. 없는 계정 `NoAccount`.
  - `mfa_use_recovery(id, code: str) -> int | None` - 맞는 해시를 지우고 남은 개수, 아니면 None
  - `mfa_clear(id) -> bool` - `mfa` 칸을 지움 (없었으면 False)
  - `mfa_info(id) -> {"enabled": bool, "enabled_at": int | None, "recovery_left": int}`
  - `_put`(set·add)·`disable`·`change_password` 는 옛 기록의 `mfa` 칸을 새 기록으로 옮긴다.
- `Web.__init__`: `registry` 가 있으면 `self.accounts.admin_min = 10` (`LAN_ADMIN_PASSWORD_MIN = 10`).

- [ ] **Step 1: 시험** `tests/test_accounts_v2.py`
  - `test_v1_reads_v2_writes`: 버전 1 파일(계정 둘)을 손으로 쓰고 `list()` 가 둘, `disable` 한 번 뒤 파일 `version == 2`, 계정 칸 그대로.
  - `test_mfa_enable_and_check`: `new_secret` 로 `mfa_enable(uid, s, code_at(s, step_of(now)), now)` → 8개. 파일 안에 복구 번호 글이 없고 해시 8개. `mfa_check` 같은 번호 다시 → False, 다음 칸 번호 → True. `get(uid)["mfa"] is True`, `list()` 의 dict 에 `secret`·`recovery` 키 없음.
  - `test_recovery_once`: 복구 번호 하나 → 7, 같은 것 다시 → None, 대문자·`-` 없이 넣은 다른 것 → 6.
  - `test_mfa_survives_writes` (Review Focus 1): 켠 뒤 `change_password`, `set(uid, 새것, "admin", must_change=True)`, `disable(uid, True)`, `disable(uid, False)` 를 차례로 하고 매번 `mfa_info(uid)["enabled"]` 참이고 `mfa_secret` 같음.
  - `test_admin_min`: `admin_min=10` 인 Accounts 에서 관리자 `add(..., "9chars-pw", "admin")` → WeakPassword, 유저는 8자 됨. 기본(8) 은 관리자 8자 됨 (단독 그대로).
  - `test_clear`: `mfa_clear` → True, 다시 → False, `mfa_info` enabled False.
- [ ] **Step 2:** `tests\test_accounts_v2.py` → 실패 확인.
- [ ] **Step 3:** 구현. 저장 꼴만 바뀌고 단독 동작은 같다 (`test_local_web_api` 의 계정 시험이 그대로 통과해야 한다 - 파일 `version` 을 1 로 견주는 곳이 있으면 2 로 고치고 보고).
- [ ] **Step 4:** `tests\test_accounts_v2.py`, `tests\test_local_web_api.py`, `tests\test_settings_standalone.py` → 모두 `실패: 0`.
- [ ] **Step 5: 커밋** `사내 서버 ③ Task 2 - 계정 파일 버전 2(2단계 칸·복구 번호 해시, 비밀번호를 바꿔도 남음), 사내 서버 관리자 비밀번호 10자, 시험 test_accounts_v2`

---

### Task 3: 로그인 두 단계와 등록 (`web_security.py`, `local_web.Web`)

**Files:** Create `firebase/agent/web_security.py`, `tests/test_lan_mfa.py`. Modify `firebase/agent/local_web.py`. 기존 사내 서버 시험의 준비 자리(`tests/test_lan_web.py`, `test_lan_e2e.py`, `test_lan_web_tls.py`, `test_lan_tls.py`, `test_lan_review_fixes.py`, `test_lan_review2.py`, `test_lan_server.py`, `wsl_lan_smoke.py` 중 사내 서버 Web 을 띄우는 곳)에 `security.json` = `{"version":1,"totp_scope":"off","show_own_history":true}` 를 먼저 쓰는 한 줄.

**Interfaces:**
- Consumes: Task 1·2 전부.
- Produces:
  - `web_security`: `SECURITY_NAME="security.json"`, `SCOPES=("off","admin","all")`, `DEFAULT={"totp_scope":"admin","show_own_history":True}`, `class Security(path)` - `get() -> dict`(파일이 없거나 깨졌으면 DEFAULT, 깨진 파일은 `.broken` 으로 치움), `set(totp_scope=None, show_own_history=None) -> dict`(임시 파일 → `os.replace`, 틀린 값 ValueError), `needs_mfa(scope: str, role: str) -> bool`(모듈 함수: all → 참, admin → role=="admin", off → 거짓).
  - `Web.security` (사내 서버만 `Security(<folder>/security.json)`, 단독 None). `Web.lan` 속성 = `self.registry is not None`.
  - `MFA_TICKET_SEC = 300`, 표는 메모리 `{표: {"id", "rev", "ip", "until"}}` 최대 `SESSIONS_MAX`, `secrets.token_urlsafe(32)`.
  - `POST /api/login`: 사내 서버에서 비밀번호가 맞고 그 계정이 `mfa` 켜짐이면 세션 대신 `{"mfa": True, "ticket": 표, "ttl": 300}`. 켜짐이 아니면 지금처럼 세션 (범위에 들면 아래 등록 강제).
  - `POST /api/login/mfa` (경로 `("login", True)`, 조각 `mfa`) `{ticket, code}` 또는 `{ticket, recovery}` → `{"token", "session"}` (+ 복구 번호로 들어오면 `"recoveryLeft": n`). 표가 없거나·끝났거나·다른 주소·계정 rev 가 다르거나·중지됐으면 401 `auth/ticket-expired` 와 표 지움. 번호가 틀리면 잠금 셋에 세고 401 `auth/invalid-code` (표는 남김 - 5분 안에 다시). 맞으면 표를 지우고 세션.
  - 등록 강제: `_auth(..., mfa_ok=False)` - 사내 서버에서 `needs_mfa(scope, role)` 이고 계정 `mfa` 꺼짐이면 `mfa_ok` 창구(세션·로그아웃·`/api/mfa/setup`·`/api/mfa/enable`)만, 나머지 403 `auth/must-enroll-mfa`. 차례는 `must_change` 먼저 (비밀번호를 바꿔야 하면 그 403 이 먼저). 범위는 요청마다 `security.get()` 으로 읽는다.
  - 세션 공개 칸 `_public` 에 사내 서버만 `"mfa": bool`, `"mustEnroll": bool`.
  - `POST /api/mfa/setup` `{password?}` → `{"secret", "uri"}` - 대기 비밀 값을 그 세션 토큰에 10분 둔다 (메모리). 이미 켜진 계정이면 `password` 가 맞아야 (틀리면 잠금 셋에 세고 403 `auth/wrong-password`).
  - `POST /api/mfa/enable` `{code}` → `{"recovery": [8개], "session"}` - 대기 비밀 값으로 `mfa_enable`. 대기 없음 409 `failed-precondition`, 틀린 번호 잠금 셋에 세고 400 `auth/invalid-code`. 성공하면 그 계정의 다른 세션을 닫는다.
  - `POST /api/mfa/disable` `{password, code}` → `{"ok": True}` - 범위가 그 계정을 필수로 묶으면 409, 비밀번호·번호 둘 다 맞아야.
  - `POST /api/accounts/<id>` 에 `{"mfaReset": true}` (관리자, 자기 계정 말고) → `mfa_clear`, 그 계정 세션 닫기, 기록 `웹 계정 변경 (2단계 해제)`.
  - `GET /api/server-time` (사내 서버, 로그인 없이) → `{"nowMs": int}`.
  - 단독(registry 없음): `/api/login/mfa`·`/api/mfa/*`·`/api/server-time` 404, 로그인 응답 지금과 같음.

- [ ] **Step 1: 시험** `tests/test_lan_mfa.py` (사내 서버 Web 을 `test_lan_web.py` 처럼 127.0.0.1 http 로 띄움, 손 시계 `clock` 을 Web 에 넘겨 `totp.code_at(secret, step_of(clock()))` 로 번호를 만든다)
  - `test_enroll_flow`: 기본 범위(파일 없음 = admin)에서 관리자 로그인 → 세션 `mustEnroll` 참, `/api/runs` 403 `auth/must-enroll-mfa`, `/api/session` 200. setup → secret·uri, enable 틀린 번호 400, 맞는 번호 → recovery 8개, 그 뒤 `/api/runs` 200. 유저(viewer)는 등록 없이 `/api/runs` 200.
  - `test_must_change_first`: must_change 관리자는 setup 도 403 `auth/must-change`, 비밀번호를 바꾼 뒤 setup 됨.
  - `test_two_step_login`: 켜진 계정 로그인 → `mfa` 표만 (token 없음). 번호 → 세션. 같은 번호로 새 표 → 401 `auth/invalid-code` (쓴 칸). 복구 번호 → 세션·`recoveryLeft` 7.
  - `test_ticket_rules` (Review Focus 2): 표를 다른 주소로(사내 서버 web_ip 를 바꾸는 시험 손잡이 - `test_lan_review2.py` 의 XFF 방식) → 401 ticket-expired. 시계 301초 → 401. 쓴 표 다시 → 401. 표를 받은 뒤 관리자가 그 계정 비밀번호를 다시 정함 → 401.
  - `test_code_lockout`: 틀린 번호 5번 → 다음은 맞는 번호도 429 (아이디 잠금 쌍), 주소 잠금에도 셈이 들어간다 (10번째 실패 뒤 다른 아이디의 비밀번호 로그인도 429).
  - `test_same_code_race` (Review Focus 3): 같은 계정 표 둘을 받아 같은 번호로 스레드 둘이 동시에 `/api/login/mfa` → 200 하나, 401 하나.
  - `test_admin_reset_and_disable`: 관리자 A 가 B 의 `mfaReset` → B 세션 닫힘, B 다시 로그인하면 mustEnroll. 자기 계정 mfaReset 400. 범위 off 에서 유저가 켠 2단계를 `disable`(비밀번호·번호) → ok, 범위 admin 에서 관리자 disable → 409.
  - `test_single_unchanged`: 단독 Web 의 `/api/login` 응답 키가 지금과 같고(`token`, `session`, 세션에 `mfa` 없음), `/api/mfa/setup`·`/api/server-time` 404, 자료 폴더에 `security.json` 없음.
- [ ] **Step 2:** `tests\test_lan_mfa.py` → 실패 확인.
- [ ] **Step 3:** `web_security.py`, `local_web.Web` 구현. 번호·복구·비밀번호 확인은 `_login_lock` 안에서 `_addr_check`·`_id_all_check`·`lockout.locked(pair)` 뒤에 하고, 틀리면 `_id_fail`·`_id_all_fail`·`_addr_fail` 을 그대로 쓴다. 기존 사내 서버 시험 준비 자리에 `security.json`(off) 한 줄.
- [ ] **Step 4:** `tests\test_lan_mfa.py`, `tests\test_lan_web.py`, `tests\test_lan_web_tls.py`, `tests\test_lan_e2e.py`, `tests\test_local_web_api.py` → 모두 `실패: 0`.
- [ ] **Step 5: 커밋** `사내 서버 ③ Task 3 - 2단계 인증: 비밀번호 뒤 5분 표·번호(앞뒤 한 칸, 쓴 칸 거절, 틀리면 잠금에 셈)·복구 번호, 범위에 든 계정은 등록 전 다른 창구 거절(비밀번호 변경 다음), 관리자가 풀어 주기, 서버 시각 창구. 단독 그대로`

---

### Task 4: '보안' 설정 창구

**Files:** Modify `firebase/agent/local_web.py`, `tests/test_lan_mfa.py` (끝에 붙임)

**Interfaces:**
- Consumes: Task 3 의 `Web.security`, 번호 확인 길.
- Produces:
  - `GET /api/security` (관리자) → `{"totpScope", "showOwnHistory", "nowMs"}`.
  - `POST /api/security` (관리자) `{totpScope?, showOwnHistory?, password?, code?}` → 바뀐 설정. **줄이는 변경**(범위가 `all→admin`·`all→off`·`admin→off`, 또는 `showOwnHistory` 를 끄는 것은 줄이는 것이 아님 - 범위만)은 `password` 가 맞고, 부른 관리자가 2단계를 켰으면 `code` 도 맞아야 한다 (틀리면 잠금 셋에 세고 403 `auth/wrong-password`·400 `auth/invalid-code`). 올리는 변경은 세션만. 틀린 값 400.
  - 바꾸면 서버 기록 `웹 보안 설정 변경  2단계 범위=<이전>→<이후>  유저 이력 보이기=<..>  처리=<아이디>  주소=<..>` (audit.log 를 따로 두는 것은 ④ - 지금은 서버 기록).
  - 단독은 404.

- [ ] **Step 1: 시험** (test_lan_mfa.py 끝)
  - `test_security_get_set`: 기본 → `totpScope "admin"`, `showOwnHistory true`. 유저 세션 403. `all` 로 올리기 → 비밀번호 없이 200. `off` 로 줄이기 비밀번호 없이 → 403, 비밀번호만(관리자 2단계 켜짐) → 400 invalid-code, 둘 다 맞음 → 200, 기록 줄 하나. 틀린 값 `"some"` → 400.
  - `test_scope_raise_live_session` (Review Focus 4): 범위 admin 에서 유저 로그인(등록 없이 `/api/runs` 200) → 관리자가 `all` 로 올림 → 같은 유저 세션의 `/api/runs` 403 must-enroll-mfa, `/api/session` 의 `mustEnroll` 참.
- [ ] **Step 2:** 실패 확인. **Step 3:** 구현. **Step 4:** `tests\test_lan_mfa.py` → `실패: 0`.
- [ ] **Step 5: 커밋** `사내 서버 ③ Task 4 - '보안' 설정 창구(2단계 범위 끔·관리자만·모든 계정, 유저에게 이력 보이기), 범위를 줄일 때는 비밀번호와 지금 번호, 바꾼 일 기록`

---

### Task 5: 로그인 이력 (`login_log.py`)

**Files:** Create `firebase/agent/login_log.py`, `tests/test_login_log.py`. Modify `firebase/agent/local_web.py` (`Sessions`, `Web`), `tests/test_lan_mfa.py` (끝에 붙임)

**Interfaces:**
- Produces:
  - `login_log`: `LOGINS_NAME="logins.db"`, `KEEP_DAYS=365`, `RESULTS=("ok","bad_password","bad_code","locked","disabled","logout","timeout","mfa_on","mfa_off","mfa_reset","recovery")`, `browser_kind(ua: str | None) -> str` (`"Edge"`·`"Chrome"`·`"Firefox"`·`"Safari"`·`"기타"` + `" · Windows"`·`" · macOS"`·`" · Android"`·`" · iOS"`·`" · Linux"` 중 하나, 40자 안, User-Agent 원문은 저장하지 않는다).
  - `class LoginLog(path, clock=time.time)` - 표 `logins(id INTEGER PRIMARY KEY, at INTEGER, uid TEXT, ip TEXT, agent TEXT, result TEXT)` + `at`·`uid` 색인. `add(result, uid, ip, agent) -> None` (result 는 RESULTS 안만, uid 는 등록된 아이디 또는 None), `query(uid=None, since_ms=None, until_ms=None, result=None, limit=50, before_id=None) -> list[dict]` (최신 먼저, limit 1~200, 칸 `id, at, uid, ip, agent, result`), `last_ok(uid, before_id=None) -> dict | None`, `purge() -> int` (KEEP_DAYS 넘은 줄), `add` 가 하루 한 번 `purge` 를 부른다. `close()`.
  - `Sessions(..., on_end=None)` - 미사용·12시간으로 끝난 세션을 `get`·`open` 이 지울 때 `on_end(세션 사본, "timeout")`.
  - `Web.login_log` (사내 서버만, `<folder>/logins.db`). 남기는 곳: 로그인 성공 `ok`(2단계면 번호까지 맞은 뒤), 틀린 비밀번호 `bad_password`, 틀린 번호·복구 `bad_code`, 이번 실패로 잠금이 **시작될 때** `locked` (잠긴 동안의 거절은 줄마다 남기지 않는다), 중지 계정 `disabled`, 로그아웃 `logout`, 자동 로그아웃 `timeout`, 2단계 켬 `mfa_on`·끔 `mfa_off`·관리자가 풂 `mfa_reset`(대상 계정 아이디로)·복구 번호로 로그인 `recovery`. 없는 아이디는 uid None.
  - 로그인 성공 응답(두 단계 모두)에 사내 서버만 `"lastLogin": {"at": ms, "ip": str} | None` (이번 것 바로 앞의 `ok`).
  - `GET /api/logins/me?limit=&before=` (로그인한 누구나, must_ok) → `{"items": [...]}` 자기 것만. 유저인데 `showOwnHistory` 꺼짐 → 403. 관리자는 늘 됨.
  - `GET /api/logins?id=&from=YYYY-MM-DD&to=YYYY-MM-DD&result=&limit=&before=` (관리자) → `{"items": [...]}`. 날짜는 서버 지역 시각 하루 단위, 틀린 값 400.
  - 웹에서 지우는 창구는 없다. 단독은 404, logins.db 를 만들지 않는다.

- [ ] **Step 1: 시험**
  - `tests/test_login_log.py`: `test_add_query`(넣은 차례 반대로 나옴, uid·result·기간 거르기, before_id 로 다음 쪽, limit 0→1·999→200), `test_bad_result`(RESULTS 밖 ValueError), `test_purge`(손 시계로 366일 전 줄은 지워지고 364일 전은 남음, add 가 하루 한 번만 purge), `test_browser_kind`(Edge·Chrome·Firefox·Safari·빈 값 → 기대 글, 500자 이상한 글도 40자 안).
  - test_lan_mfa.py 끝: `test_history_events`(성공·틀림·잠김 시작·중지·로그아웃·자동 로그아웃(손 시계 1801초)·2단계 켬·풂·복구 로그인이 각각 한 줄, 잠긴 동안 거절 3번은 줄이 늘지 않음, 없는 아이디는 uid None, ip 칸이 보낸 쪽 주소), `test_history_access`(유저는 `/api/logins` 403, `/api/logins/me` 는 자기 것만, 관리자가 showOwnHistory 끄면 유저 me 403·관리자 me 200, 두 번째 로그인 응답의 lastLogin 이 첫 로그인 시각·주소), `test_no_secret_leaks` (Review Focus 5: 시험 동안 받은 모든 응답 글(등록 시작·완료 응답 둘 빼고)·서버 기록 파일·logins.db 의 모든 칸·security.json 에 비밀 값·복구 번호·비밀번호·표가 없음).
- [ ] **Step 2:** 실패 확인. **Step 3:** 구현. **Step 4:** `tests\test_login_log.py`, `tests\test_lan_mfa.py` → `실패: 0`, WSL 에서 둘 다 `실패: 0`.
- [ ] **Step 5: 커밋** `사내 서버 ③ Task 5 - 로그인 이력 DB(logins.db, 성공·실패·잠김 시작·중지·로그아웃·자동 로그아웃·2단계 바꾼 일, 브라우저 종류, 1년 지나면 지움), 내 이력·관리자 이력 창구, 마지막 로그인`

---

### Task 6: 묶어 확인

**Files:** Modify `tools/build_release.py` (배포 목록에 `totp.py`·`web_security.py`·`login_log.py`), `tests/run_standalone_suite.py` (SA 목록에 새 시험 넷), `docs/superpowers/plans/2026-11-24-lan-index.md` (③ 상태, 미룬 것 표에 'audit.log 따로 두기 → ④')

- [ ] **Step 1:** `tests\test_program_files_imports.py`·`tests\test_build_release.py` → `실패: 0` (새 모듈이 배포 목록에 있어야 통과).
- [ ] **Step 2:** `D:\AX\RPA\.venv\Scripts\python.exe tests\run_standalone_suite.py all` → '실패한 파일: 0', `run_standalone_suite.py wsl` → '실패한 파일: 0'.
- [ ] **Step 3:** `graphify update .`
- [ ] **Step 4: 커밋** `사내 서버 ③ Task 6 - 배포 목록에 totp·web_security·login_log, 시험 일괄 실행에 새 시험 넷, 계획 목록 상태`
