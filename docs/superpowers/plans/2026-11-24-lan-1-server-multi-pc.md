# 사내 서버 ① 서버 넓히기 (여러 PC) 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 지금 로컬 서버가 '사내 서버' 배치로도 돌게 한다 - PC 등록부, PC 마다 다른 열쇠(`ap2` 서명), 자기 자리만 쓰기, 시계 맞추기, 인증번호 요청 차례, 웹 API 의 PC 고르기. 단독(나)의 동작은 그대로.

**Architecture:** `make_server(..., registry=None)` 의 `registry` 가 있으면 사내 서버 배치(`LAN`), 없으면 지금 그대로(`SINGLE`). 서명 확인은 PC 번호 머리글로 등록부에서 열쇠를 찾고, 이후의 모든 자리 검사는 '서명으로 확인한 PC 번호' 로 한다. 이 단위는 TLS·사내 주소 듣기 없이 127.0.0.1 에서 가짜 PC 여럿으로 시험한다 (TLS·주소는 ②).

**Tech Stack:** 파이썬 3.14 표준 라이브러리만 (서버·클라이언트), 시험은 저장소 관례의 plain python 스크립트 (`check(...)` + 끝에 실패 수로 종료 코드).

**Spec:** `docs/superpowers/specs/2026-11-24-standalone-linux-server-design.md` (사용자 승인 2026-11-24). 이 계획은 14절 ① = 6.4·6.5 와 13절 1·2·3·6.

## Global Constraints

- 작업 폴더 `D:\AX\RPA_StandAlone`, 브랜치 `StandAlone`. 파이썬은 `D:\AX\RPA\.venv\Scripts\python.exe` (그 .venv 의 패키지는 고치지 않는다). `D:\AX\RPA` 폴더의 파일은 절대 고치지 않는다 (다른 세션이 쓴다) - 경로는 늘 `D:\AX\RPA_StandAlone\...` 절대 경로로.
- 단독(나)은 한 글자도 다르게 돌면 안 된다: `registry=None` 일 때의 상수·응답·검사는 지금과 같다. 지금 시험 전체가 그대로 통과해야 한다 (Task 7).
- 서버·클라이언트는 표준 라이브러리만. 바깥 연결을 여는 코드를 서버에 더하지 않는다.
- 기록(`local_server.log`)에 열쇠, 등록 토큰, 서명, 인증번호를 싣지 않는다. 등록 토큰은 디스크에 쓰지 않는다 (메모리에만 10분).
- 화면에 나가는 글은 한국어 업무 말투 ('~하여 주십시오'), '버전' (판 금지), '묶음' 금지.
- 사내 서버 PC 번호 꼴 `pc_01` (정규식 `pc_\d{2,4}`), 지운 번호는 다시 쓰지 않는다.
- 숫자: 등록 유효 600초, 등록 증명 틀림 5번이면 그 등록 취소, 사내 서버 서명 허용 차이 120000ms (단독은 지금 60000ms), 사내 서버 동시 연결 256, 웹 구독 32, 에이전트 구독 전체 64·PC 하나 4.
- 커밋은 작업마다 `git commit -F <파일>` (메시지 파일은 Write 로 만들고 BOM 없이), 끝줄 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. push 하지 않는다. `--no-verify` 금지.
- 끝나면 `graphify update .` (작업 폴더에서).

## Review Focus

1. 다른 PC 의 열쇠로 남의 PC 자리(현황·명령·실행 기록·인증번호 번호)를 읽거나 쓰려는 요청 - 모두 거절 (Task 4·5·7 시험).
2. 사용 중지·지운 PC 가 이미 열어 둔 구독 - 1~2초 안에 끊겨야 한다 (Task 4 시험 `test_disabled_pc_stream_closes`).
3. 등록 토큰을 주운 사람이 PC 보다 먼저 또는 나중에 등록하려는 경우 - 한 번만, 10분 안, 증명이 맞을 때만 (Task 2).
4. 서버 시계와 PC 시계가 5분 틀린 경우 - 한 번 다시 보내 성공, 서명이 틀린 요청에는 서버 시각을 알려 주지 않는다 (Task 3·4).
5. PC 둘이 같은 휴대폰으로 인증번호 요청을 거의 동시에 여는 경우 - 뒤 요청은 거절, 앞 요청의 번호는 앞 PC 만 읽는다 (Task 5).

---

## 파일

| 파일 | 맡는 일 |
|---|---|
| 새 `firebase/agent/pc_registry.py` | PC 등록부 (`pcs.json`), 등록 토큰·증명·열쇠 만들기, 등록 글(한 줄) 꼴 |
| `firebase/agent/local_store.py` | `ap2` 서명(PC 번호 머리글), 시계 차이 한 번 다시 보내기, 중지·지워짐 오류, `enroll()` 클라이언트 |
| `firebase/agent/local_server.py` | `Deploy`(SINGLE·LAN), 현황만 바뀐 쓰기 저장 건너뛰기, `/enroll`, LAN 서명 확인, 자리 검사에 PC 번호, 에이전트 구독 상한 |
| `firebase/agent/local_phone.py` | `Desk` - 휴대폰마다 요청 하나, 연 PC 만 번호 읽기·지우기 |
| `firebase/agent/local_web.py` | PC 고르기(`pcId`), `/api/company` 의 PC 목록, `/api/pcs` 관리 창구 |
| 새 `tests/run_standalone_suite.py` | 스탠드얼론·일반 시험 일괄 실행 (지금 scratchpad 의 `run_sa_tests.py` 를 저장소로) |
| 새 `tests/test_pc_registry.py`, `tests/test_lan_server.py`, `tests/test_lan_web.py` | 이 계획의 시험 |

---

### Task 1: 현황·인증번호만 바뀐 쓰기는 파일을 다시 쓰지 않기 + 시험 일괄 실행 도구

**Files:**
- Modify: `firebase/agent/local_server.py` (`Store._write`, `Store.__init__`)
- Create: `tests/run_standalone_suite.py` (내용은 `C:\Users\202512~1\AppData\Local\Temp\claude\829f8928aef5982f\7867a5f6-6024-4100-8af7-b0f18f099fe7\scratchpad\run_sa_tests.py` 를 그대로 옮기되 `ROOT` 는 이 파일 기준 상대 경로로, 목록 끝에 이 계획의 새 시험 셋을 더한다 - 파일이 없으면 건너뛰는 지금 동작 그대로)
- Test: `tests/test_local_store_core.py` (끝에 더함)

**Interfaces:**
- Produces: `Store.saves` (int, 파일을 실제로 쓴 횟수 - 시험용 세기), 동작: 모든 쓰기 자리가 `volatile` 자리 아래(그 자리 자신 포함)이면 `_save` 를 부르지 않는다. 하나라도 밖이거나 volatile 의 윗자리(루트 포함)면 지금처럼 저장.

- [ ] **Step 1: 실패하는 시험** (`tests/test_local_store_core.py` 끝)

```python
def test_volatile_only_write_skips_file():
    path = os.path.join(TMP, "vol.json")
    s = local_server.Store(path, volatile=("apps/otp", "apps/rpa/live"))
    s.put("apps/rpa/commands/c1/p1/k1", {"state": "queued"})
    n = s.saves
    before = open(path, encoding="utf-8").read()
    s.patch("apps/rpa/live/c1/p1", {"heartbeat": 1})
    s.put("apps/otp/requests/c1/ph/current", {"req_id": "x" * 8})
    check("현황·인증번호만 바뀐 쓰기는 파일을 다시 쓰지 않는다", s.saves == n and open(path, encoding="utf-8").read() == before)
    check("메모리에는 들어 있다", s.get("apps/rpa/live/c1/p1/heartbeat") == 1)
    s.patch("apps/rpa", {"live/c1/p2/heartbeat": 2, "commands/c1/p2/k9": {"state": "queued"}})
    check("volatile 밖이 하나라도 섞이면 저장한다", s.saves == n + 1)
    s.put("apps/rpa", None)
    check("volatile 의 윗자리 쓰기는 저장한다", s.saves == n + 2)
```
(파일 끝의 실행 목록·`main` 관례에 맞춰 부른다.)

- [ ] **Step 2:** `D:\AX\RPA\.venv\Scripts\python.exe tests\test_local_store_core.py` → 새 시험이 `AttributeError: saves` 또는 실패.
- [ ] **Step 3:** `Store.__init__` 에 `self.saves = 0`, `_write` 에서 `writes` 의 모든 `parts` 가 어떤 volatile `v` 에 대해 `parts[:len(v)] == v` 이면 `_save` 를 건너뛰고, 아니면 `_save` 뒤 `self.saves += 1`. 구독 알림은 두 경우 모두 그대로.
- [ ] **Step 4:** 같은 명령 → 통과. `tests\test_local_server_http.py` 도 통과.
- [ ] **Step 5:** `tests/run_standalone_suite.py` 를 만들고 `D:\AX\RPA\.venv\Scripts\python.exe tests\run_standalone_suite.py sa` → '실패한 파일: 0'.
- [ ] **Step 6: 커밋** - `사내 서버 ① Task 1 - 현황·인증번호만 바뀐 쓰기는 저장 건너뜀, 스탠드얼론 시험 일괄 실행 도구`

---

### Task 2: PC 등록부 `pc_registry.py`

**Files:**
- Create: `firebase/agent/pc_registry.py`
- Modify: `firebase/agent/local_server.py` - `LOCKED_FILES` 에 `"pcs.json"` 더함
- Test: `tests/test_pc_registry.py`

**Interfaces:**
- Produces (모두 `pc_registry` 모듈):
  - `PC_RE = re.compile(r"pc_\d{2,4}")`, `ENROLL_SEC = 600`, `ENROLL_FAIL_MAX = 5`, `LABEL_MAX = 40`, `PREFIX = "APE1."`
  - `class SeatsFull(Exception)`, `class EnrollError(Exception)` - `.code` ∈ `"unknown" | "expired" | "bad_proof" | "duplicate" | "seats"`
  - `enroll_proof(token: str, pc_id: str, rand_hex: str, guid: str, host: str) -> str` = HMAC-SHA256(열쇠 token, 글 `"ap2 enroll\n{pc_id}\n{rand_hex}\n{guid}\n{host}"`) hex
  - `derive_keys(token: str, rand_hex: str) -> tuple[str, str]` = (HMAC-SHA256(token, `"ap2 pc agent\n" + rand_hex`) hex, HMAC-SHA256(token, `"ap2 pc relay\n" + rand_hex`) hex)
  - `encode_enrollment(info: dict) -> str` = `PREFIX + base64url(JSON, 패딩 없음)`; `decode_enrollment(text: str) -> dict` (앞뒤 빈칸 무시, 꼴이 틀리면 `ValueError`; 칸 `v`(=1)·`url`·`pc`·`token`·`exp` 가 모두 있어야 한다)
  - `class Registry(path, seats: int, clock=time.time)`:
    - `start(label: str) -> {"pc_id", "token", "expires_at"}` - 자리가 없으면 `SeatsFull`, 이름이 비었거나 `LABEL_MAX` 초과·제어 글자면 `ValueError`. 번호는 파일의 `next` 로 매기고 하나 올린다 (지운 번호를 다시 쓰지 않는다). 토큰 `secrets.token_urlsafe(32)` 는 메모리에만.
    - `enroll(pc_id, rand_hex, guid, host, proof) -> (agent_key, relay_key)` - 대기 중 아님 `unknown`, 10분 지남 `expired`(대기도 지움), 증명 틀림 `bad_proof`(5번째에 대기 취소), 같은 `guid` 가 active·disabled 로 이미 있음 `duplicate`, 자리 없음 `seats`. `rand_hex` 는 64자 소문자 hex, `guid` 는 `[0-9A-Fa-f-]{36}`, `host` 는 1~63자 출력 글자 - 아니면 `bad_proof` 와 같은 셈. 성공하면 기록 `{label, guid, host, agent_key, relay_key, state: "active", created_at, enrolled_at}` 을 저장하고 대기를 지운다.
    - `cancel(pc_id) -> bool`, `state(pc_id) -> "active"|"disabled"|"removed"|None`, `keys(pc_id) -> (agent_key, relay_key) | None` (removed 도 돌려준다 - 서버가 '지워짐' 답에 서명해야 해서), `label(pc_id) -> str | None`
    - `list() -> list[dict]` - removed 는 뺀다. 칸: `pcId, label, host, state("pending"|"active"|"disabled"), enrolledAt, expiresAt, lastSeen` (열쇠·토큰·guid 없음)
    - `rename(pc_id, label)`, `disable(pc_id, on: bool)`, `remove(pc_id)` (state=removed, removed_at - 자리를 돌려준다), `seen(pc_id)` (메모리의 마지막 연결 ms)
    - `used() -> int` = active + disabled + 살아 있는 대기
  - 파일 `pcs.json` = `{"v": 1, "next": N, "pcs": {pc_id: 기록}}`, 임시 파일 + `os.replace` 로 저장, 깨진 파일은 `.broken` 으로 옮기고 빈 등록부 (Store 와 같은 방식). 잠금 하나로 감싼다.

- [ ] **Step 1: 실패하는 시험** `tests/test_pc_registry.py` (관례: `check`, `fails`, `TMP`, 끝에 `sys.exit(1 if fails else 0)`). 시계는 `[t]` 리스트로 바꿔 끼운다.

```python
def test_enroll_once():
    reg = pc_registry.Registry(p("a.json"), seats=2, clock=lambda: T[0])
    s = reg.start("1층 PC")
    check("첫 번호는 pc_01", s["pc_id"] == "pc_01" and pc_registry.PC_RE.fullmatch(s["pc_id"]))
    rand = "ab" * 32
    proof = pc_registry.enroll_proof(s["token"], "pc_01", rand, GUID, "OFFICE-1")
    keys = reg.enroll("pc_01", rand, GUID, "OFFICE-1", proof)
    check("열쇠는 토큰과 PC 난수로 양쪽이 같게 만든다", keys == pc_registry.derive_keys(s["token"], rand))
    check("등록되면 active", reg.state("pc_01") == "active")
    check("두 번째 등록은 unknown", raises(lambda: reg.enroll("pc_01", rand, GUID, "OFFICE-1", proof), "unknown"))
    check("파일에 토큰이 없다", s["token"] not in open(p("a.json"), encoding="utf-8").read())

def test_expired_and_bad_proof():
    # 600초 지나면 expired, 틀린 증명 5번이면 대기가 취소되어 맞는 증명도 unknown
def test_seats():
    # seats=2: start 두 번(대기 포함) 뒤 세 번째 start 는 SeatsFull, 하나 remove 하면 다시 start 가능
def test_duplicate_guid():
    # 같은 GUID 로 두 번째 PC 등록 → duplicate
def test_numbers_not_reused():
    # pc_01 remove 뒤 새 start 는 pc_03 (pc_02 가 대기였다면) - 어떤 경우에도 pc_01 이 아니다
def test_list_has_no_secrets():
    # list() 의 어떤 칸에도 agent_key·relay_key·token·guid 글이 없다, removed 는 빠진다
def test_disable_remove_keys():
    # disable → state disabled, keys 그대로 / remove → state removed, keys 그대로, used() 가 하나 준다
def test_enrollment_text_roundtrip():
    info = {"v": 1, "url": "http://127.0.0.1:8781", "pc": "pc_01", "token": "t" * 43, "exp": 1}
    t = pc_registry.encode_enrollment(info)
    check("APE1. 로 시작하고 한 줄", t.startswith("APE1.") and "\n" not in t)
    check("다시 풀면 같다", pc_registry.decode_enrollment("  " + t + "\n") == info)
    check("꼴이 틀리면 ValueError", raises_value(lambda: pc_registry.decode_enrollment("APE1.@@@")))
def test_reload_keeps_pcs():
    # 새 Registry 로 같은 파일을 읽으면 active PC·next 가 남고 대기는 없다
```
(뼈대만 적은 시험은 위 주석의 단언을 그대로 `check` 로 쓴다.)

- [ ] **Step 2:** `D:\AX\RPA\.venv\Scripts\python.exe tests\test_pc_registry.py` → `ModuleNotFoundError: pc_registry`.
- [ ] **Step 3:** 위 Interfaces 대로 `firebase/agent/pc_registry.py` 를 쓴다. 증명 비교는 `hmac.compare_digest`.
- [ ] **Step 4:** 같은 명령 → 모두 통과.
- [ ] **Step 5: 커밋** - `사내 서버 ① Task 2 - PC 등록부 pc_registry (번호 pc_01·한 번만 쓰는 10분 등록 토큰·PC 난수로 열쇠 만들기·자리 수)`

---

### Task 3: 클라이언트 `ap2` 서명·시계 맞추기·등록

**Files:**
- Modify: `firebase/agent/local_store.py`
- Test: `tests/test_local_store_client.py` (끝에 더함 - 서버 없이 `opener` 를 바꿔 끼우는 지금 관례)

**Interfaces:**
- Consumes: Task 2 의 `pc_registry.enroll_proof`, `derive_keys`, `decode_enrollment`
- Produces:
  - `H_PC = "X-AP-PC"`, `PC_DISABLED = "PC_DISABLED"`, `PC_REMOVED = "PC_REMOVED"`
  - `request_mac2(key, pc_id, role, method, target, ts, nonce, body, digest=None) -> str` = `_mac(key, ["ap2", "req", pc_id, role, method, target, str(ts), nonce, digest or _digest(body)])`
  - `sign_headers(key, role, method, target, body=b"", now_ms=None, nonce=None, pc_id=None)` - `pc_id` 가 있으면 `H_PC` 를 싣고 `request_mac2`, 없으면 지금과 한 글자도 같다.
  - 응답·이벤트 서명(`response_mac`, `event_mac`)은 바꾸지 않는다 (열쇠가 PC 마다 다르다).
  - `Client(cfg)` - `cfg["lan"]` 이 참이면 `cfg["pc_id"]` 가 `pc_registry.PC_RE` 에 맞아야 하고 (아니면 `ValueError`), 모든 요청을 `pc_id` 로 서명한다. 주소는 ① 에서는 지금처럼 http·127.0.0.1 만 (② 가 넓힌다).
  - 시계: `Client._skew_ms` (처음 0). 서명된 401 응답의 본문이 `{"error": "clock", "server_ms": <정수>}` 이면 `_skew_ms = server_ms - 지금 ms` 로 두고 **그 요청을 한 번만** 다시 보낸다. 서명 시각은 `now*1000 + _skew_ms`. 단독(`lan` 없음)에서는 `_skew_ms` 를 바꾸지 않는다.
  - 서명된 403 응답 본문 `{"error": "pc_disabled"}` → `fb.AuthError(403, PC_DISABLED)`, `{"error": "pc_removed"}` → `fb.AuthError(403, PC_REMOVED)`. 그 밖은 지금처럼 `fb.HttpError`.
  - `enroll(text: str, guid: str, host: str, opener=None, rand_hex=None, nonce=None) -> dict` - 등록 글을 풀어 `POST {url}/enroll` 에 본문 `{"v": 1, "pc", "rand", "guid", "host", "nonce", "proof"}` 를 보낸다 (서명 머리글 없음). 200 이고 응답 서명이 `response_mac(새 agent 열쇠, nonce, 200, 본문)` 과 맞아야 `{"server_url", "pc_id", "agent_key", "relay_key"}` 를 돌려준다. 서명이 틀리면 `fb.AuthError(0, NOT_VERIFIED)`, 서버 거절은 `fb.HttpError` (본문의 `error` 코드 그대로). `rand_hex`·`nonce` 는 시험용 (없으면 `secrets.token_hex(32)`·`secrets.token_hex(16)`).

- [ ] **Step 1: 실패하는 시험**

```python
def test_ap2_headers():
    h = local_store.sign_headers("k" * 43, "agent", "GET", "/db/x.json", b"", now_ms=1000, nonce="n" * 32, pc_id="pc_01")
    check("PC 번호 머리글", h[local_store.H_PC] == "pc_01")
    check("ap2 서명", h[local_store.H_SIGN] == local_store.request_mac2("k" * 43, "pc_01", "agent", "GET", "/db/x.json", "1000", "n" * 32, b""))
    h1 = local_store.sign_headers("k" * 43, "agent", "GET", "/db/x.json", b"", now_ms=1000, nonce="n" * 32)
    check("pc_id 없으면 지금 ap1 그대로·머리글 없음", local_store.H_PC not in h1 and h1[local_store.H_SIGN] == local_store.request_mac("k" * 43, "agent", "GET", "/db/x.json", "1000", "n" * 32, b""))

def test_clock_retry_once():
    # 가짜 opener: 첫 요청에 서명된 401 {"error":"clock","server_ms": 지금+300000}, 둘째 요청 X-AP-Time 이 300000 가까이 앞서면 200
    # → get() 이 값을 돌려주고 opener 가 정확히 2번 불렸다. 서명 없는 401 clock 은 다시 보내지 않고 AuthError(NOT_VERIFIED)
def test_clock_retry_not_in_single():
    # lan 없는 Client 는 서명된 401 clock 을 받아도 다시 보내지 않는다 (HttpError 401)
def test_disabled_removed_errors():
    # 서명된 403 {"error":"pc_disabled"} → AuthError 의 두 번째 인자 PC_DISABLED, pc_removed → PC_REMOVED
def test_enroll_client():
    # 가짜 opener 가 본문의 proof 를 enroll_proof 로 확인하고 derive_keys 의 agent 열쇠로 서명한 200 을 준다 → 돌려준 dict 의 열쇠가 derive_keys 와 같다
    # 같은 응답을 다른 열쇠로 서명하면 AuthError(NOT_VERIFIED)
def test_lan_client_needs_pc_id():
    # cfg lan=True 인데 pc_id 가 없거나 "p1" 이면 ValueError
```

- [ ] **Step 2:** `D:\AX\RPA\.venv\Scripts\python.exe tests\test_local_store_client.py` → 새 시험 실패.
- [ ] **Step 3:** 위 Interfaces 대로 고친다. `pc_registry` 는 `enroll`·`Client.__init__` 안에서 불러온다 (일반 버전 경로가 불러오지 않게).
- [ ] **Step 4:** 같은 명령 → 통과. `tests\test_local_server_http.py` 도 통과 (ap1 그대로).
- [ ] **Step 5: 커밋** - `사내 서버 ① Task 3 - 클라이언트 ap2 서명(PC 번호)·서명된 시계 차이로 한 번 다시 보내기·중지/지워짐 오류·등록`

---

### Task 4: 서버 LAN 배치 - 등록 창구·PC 별 서명 확인·자리 검사

**Files:**
- Modify: `firebase/agent/local_server.py`
- Test: 새 `tests/test_lan_server.py` (`test_local_server_http.py` 의 `call`·`sse`·`until` 꼴을 따라 서버를 스레드로 띄운다)

**Interfaces:**
- Consumes: Task 2 `Registry`, Task 3 `request_mac2`·`H_PC`·`Client(lan)`·`enroll`
- Produces:
  - `@dataclass(frozen=True) class Deploy: mode: str; max_conn: int; web_streams: int; agent_streams: int; per_pc_streams: int; sign_window_ms: int`
  - `SINGLE = Deploy("single", 64, 16, 0, 0, 60000)`, `LAN = Deploy("lan", 256, 32, 64, 4, 120000)` - `MAX_CONN`·`SIGN_WINDOW_MS` 상수는 그대로 두고 SINGLE 이 같은 값을 쓴다.
  - `make_server(store, runs, lic, keys, host="127.0.0.1", port=PORT, folder=None, web=None, phone=None, registry=None)` - `registry` 가 있으면 `srv.deploy = LAN`, `srv.registry = registry`, `keys` 는 쓰지 않는다 (None 이어도 된다). 없으면 `srv.deploy = SINGLE` 이고 지금 그대로. `process_request` 는 `srv.deploy.max_conn` 으로 센다. `web` 이 있으면 `web.public_url = f"http://127.0.0.1:{port}"` (② 에서 사내 주소로).
  - `Handler._role(method, digest) -> tuple[str, str]` = (역할, 서명으로 확인한 PC 번호). SINGLE: 지금 검사 그대로, PC 번호는 `lic["pc_id"]`, `X-AP-PC` 머리글이 있으면 401. LAN 순서: ① Host 검사(지금 그대로) ② `X-AP-PC` 가 `PC_RE` 이고 `registry.keys()` 가 있음 ③ 역할·시각 글자·nonce 길이 ④ `request_mac2` 맞음 - 여기까지 틀리면 서명 없는 401 ⑤ 시각 차이 > 120000ms 면 **서명된** 401 `{"error": "clock", "server_ms": 지금 ms}` ⑥ nonce 처음 ⑦ state `disabled` → 서명된 403 `{"error": "pc_disabled"}`, `removed` → 서명된 403 `{"error": "pc_removed"}` ⑧ `registry.seen(pc)`.
  - `allowed(role, method, parts, lic, pc_id=None)`, `otp_request_ok(body, lic, phone=None, pc_id=None)` - `pc_id` 가 None 이면 `lic["pc_id"]` (지금 시험 그대로 통과). `_db`·`_fs` 는 `_role` 이 준 PC 번호를 넘긴다.
  - `_fs` (LAN 만): POST 문서의 `pcId` 가 호출한 PC 와 다르면 403, GET 문서의 `pcId` 가 다르면 403.
  - `POST /enroll` (LAN 만, 서명 머리글 없음, `_role` 앞에서 갈라짐, SINGLE 은 404): 본문 Task 3 꼴 → `registry.enroll(...)` → 200 `{"pc": pc_id}` 을 새 agent 열쇠와 본문 `nonce` 로 서명. `EnrollError` 는 서명 없는 403 `{"error": e.code}`, 꼴이 틀리면 400. `nonce` 는 16~64자. 기록: `PC 등록  번호=…  컴퓨터=…` (토큰·열쇠·증명 없음).
  - 에이전트 구독 (LAN 만): 전체 `agent_streams`, PC 하나 `per_pc_streams` 를 넘으면 서명된 503 `{"error": "Too many streams"}`. 구독 고리는 1초마다 `registry.state(pc) == "active"` 를 보고 아니면 끝낸다.

- [ ] **Step 1: 실패하는 시험** `tests/test_lan_server.py` - 서버 하나에 `Registry(seats=5)` 를 달고, 시험 안에서 `reg.start` → `local_store.enroll(...)` 로 가짜 PC `pc_01`·`pc_02` 두 대를 등록해 `Client(lan=True)` 를 만든다. 시험 이름과 단언:
  - `test_enroll_over_http` - 등록 성공, 같은 글로 두 번째 등록 403 `unknown`, SINGLE 서버의 `/enroll` 은 404.
  - `test_own_spot_only` - pc_01 이 `apps/rpa/live/c1/pc_01` PATCH 200, `apps/rpa/live/c1/pc_02` PATCH 403, `apps/rpa/commands/c1/pc_02` GET 403.
  - `test_other_pc_key_rejected` - pc_02 열쇠로 `X-AP-PC: pc_01` 서명 → 서명 없는 401.
  - `test_runs_own_pc` - pc_01 이 `pcId: "pc_02"` 문서 POST → 403, 자기 문서 POST 200, pc_02 가 그 문서 GET → 403.
  - `test_clock_skew_signed_reply` - 시각을 300초 앞선 요청: 서명이 맞으면 서명된 401 clock, `server_ms` 가 지금과 2초 안. 서명이 틀리면 서명 없는 401 이고 본문에 `server_ms` 가 없다. `Client._now` 를 300초 늦춘 클라이언트로 `get` 이 성공한다.
  - `test_disabled_removed` - `reg.disable("pc_02", True)` 뒤 pc_02 요청 → 서명된 403 `pc_disabled` (클라이언트는 `AuthError(…, PC_DISABLED)`), `reg.remove` 뒤 → `PC_REMOVED`.
  - `test_disabled_pc_stream_closes` - pc_02 가 명령함 구독을 연 뒤 `reg.disable` → 3초 안에 구독이 끝난다.
  - `test_agent_stream_caps` - 한 PC 가 구독 4개 뒤 다섯 번째는 503.
  - `test_single_unchanged` - registry 없는 서버에 `X-AP-PC` 를 실은 ap2 요청 → 401, ap1 요청 → 200.
- [ ] **Step 2:** `D:\AX\RPA\.venv\Scripts\python.exe tests\test_lan_server.py` → 실패.
- [ ] **Step 3:** 위 Interfaces 대로 고친다.
- [ ] **Step 4:** 같은 명령 → 통과. `tests\test_local_server_http.py`, `tests\test_local_store_client.py` 통과.
- [ ] **Step 5: 커밋** - `사내 서버 ① Task 4 - 서버 LAN 배치: /enroll, PC 별 ap2 서명 확인, 자기 자리만, 서명된 시계 답, 중지·지워짐, 에이전트 구독 상한`

---

### Task 5: 인증번호 요청 차례 (휴대폰마다 하나, 연 PC 만)

**Files:**
- Modify: `firebase/agent/local_phone.py` (`Desk`), `firebase/agent/local_server.py` (`_db` 의 otp 자리)
- Test: `tests/test_lan_server.py` (더함), `tests/test_phone_core.py` 는 그대로 통과

**Interfaces:**
- Consumes: Task 4 의 `_role` 이 준 PC 번호
- Produces:
  - `Desk.open(phone_id: str, body: dict, pc_id: str) -> bool` - `store.put(req_path, dict(body, created_at=지금 ms), guard=…)`. 다른 PC(`pcId` 가 다름)의 살아 있는 요청이 있으면 `False` (쓰지 않음). 같은 PC 는 덮어쓴다 (지금과 같다).
  - `Desk.read_code(phone_id, pc_id=None)` - `pc_id` 가 있으면 열린 요청의 `pcId` 가 같을 때만 번호.
  - `Desk.close_ok(get, phone_id, pc_id) -> bool` - 지우기 guard: 다른 PC 의 살아 있는 요청이면 False.
  - `local_server._db`: otp_requests PUT 은 `otp_request_ok(..., pc_id=pc)` 뒤 `phone.desk.open(...)` 이 False 면 403 `DENIED` (일반 버전 규칙 거절과 같은 꼴 - `otp_relay.PhoneRelay` 가 기다렸다 다시 연다). otp_codes GET 은 `read_code(rest[0], pc)`. otp_requests·otp_codes DELETE 는 `guard=lambda get: phone.desk.close_ok(get, rest[0], pc)`.
  - SINGLE 에서는 PC 가 하나라 결과가 지금과 같다.

- [ ] **Step 1: 실패하는 시험** (`tests/test_lan_server.py` 에, 짝지은 휴대폰 하나를 `local_phone.Service` 의 `phones.add(...)` 로 넣는다 - `tests/test_phone_core.py` 의 준비 꼴을 따른다)
  - `test_otp_one_request_per_phone` - pc_01 이 요청 PUT 200, 2분 안에 pc_02 가 같은 휴대폰에 PUT → 403, pc_01 이 다시 PUT → 200.
  - `test_otp_code_only_opener` - 휴대폰이 번호를 넣은 뒤 pc_01 GET codes → 번호, pc_02 GET → null, pc_02 DELETE requests → 403, pc_01 DELETE → 200.
  - `test_otp_after_expiry_other_pc` - 시계를 121초 넘긴 뒤 pc_02 PUT → 200.
- [ ] **Step 2:** 실행 → 실패.
- [ ] **Step 3:** 위대로 고친다.
- [ ] **Step 4:** `tests\test_lan_server.py`, `tests\test_phone_core.py`, `tests\test_phone_gate.py`, `tests\check_phone_local.py` 통과.
- [ ] **Step 5: 커밋** - `사내 서버 ① Task 5 - 인증번호 요청은 휴대폰마다 하나, 번호 읽기·지우기는 연 PC 만`

---

### Task 6: 웹 API 의 여러 PC

**Files:**
- Modify: `firebase/agent/local_web.py`
- Test: 새 `tests/test_lan_web.py` (`tests/test_local_web_api.py` 의 서버 띄우기·로그인 꼴을 따른다)

**Interfaces:**
- Consumes: Task 2 `Registry`·`encode_enrollment`, Task 4 `make_server(registry=)`·`web.public_url`
- Produces:
  - `Web(store, runs, lic, folder, web_dir, clock=time.time, registry=None)`. `self.max_streams = MAX_STREAMS if registry is None else 32` (`_stream` 이 이 값을 쓴다).
  - `Web._pc(raw, need_active=False, allow_removed=False) -> str` - SINGLE: 없으면 `lic["pc_id"]`, 다르면 403 `permission-denied`. LAN: 없으면 400 `invalid-argument` "PC 를 골라 주십시오.", `PC_RE` 아님 400, 등록부에 없음(또는 removed 인데 `allow_removed` 아님) 404 `not-found` "없는 PC 입니다.", `need_active` 인데 disabled 면 409 `failed-precondition` "사용이 중지된 PC 입니다."
  - `_company`: LAN 이면 `pcs = {pcId: {"label", "state", "lastSeen"}}` (active·disabled 만), `"pcId": None`. SINGLE 은 지금 그대로.
  - `_command_new`: 본문 `pcId` → `_pc(…, need_active=True)`. `_command_get`·`_stream`: 질의 `pcId` → `_pc(…)`. `_runs`: 질의 `pcId` → `_pc(…, allow_removed=True)`. 현황·명령 자리는 그 PC 번호로 만든다 (`self._live`·`self._cmds` 고정값 대신 `_spot(kind, pc)`).
  - `/api/pcs` (관리자, `touch=True`, LAN 만 - SINGLE 은 404 "사내 서버에서만 쓰는 주소입니다."):
    - `GET` → `{"pcs": registry.list(), "seats": n, "used": registry.used()}`
    - `POST {"label"}` → `registry.start` → `{"pcId", "enrollment": encode_enrollment({"v": 1, "url": self.public_url, "pc", "token", "exp"}), "expiresAt"}`. `SeatsFull` → 409 `seats-full` "등록할 수 있는 PC 수(n대)를 모두 썼습니다."
    - `POST /api/pcs/<id>` `{"label"}` 또는 `{"disabled": bool}` 또는 `{"cancel": true}`(대기 취소) → `{"pcs": …}`
    - `DELETE /api/pcs/<id>` → `registry.remove` 뒤 그 PC 의 `apps/rpa/live/<cid>/<pc>`·`apps/rpa/commands/<cid>/<pc>` 자리를 지운다 → `{"pcs": …}`
    - 기록: `PC 추가|사용 중지|사용 재개|이름 변경|삭제|등록 취소  번호=…  처리=<아이디>` (토큰·등록 글 없음)
  - `make_server` 가 `registry` 를 받으면 `web.registry` 가 같은 것이어야 한다 (`Web(..., registry=reg)` 로 만든 것을 넘긴다 - 시험이 둘이 같은지 본다).

- [ ] **Step 1: 실패하는 시험** `tests/test_lan_web.py`
  - `test_pcs_api_admin_only` - 유저 계정 `GET /api/pcs` → 403, 관리자 → 200 이고 `seats`·`used`.
  - `test_add_pc_enrollment_text` - `POST /api/pcs {"label":"2층"}` → `enrollment` 가 `APE1.` 로 시작하고 `decode_enrollment` 의 `url` 이 서버 주소다. 토큰 원문은 POST 응답의 등록 글 안에만 있고, `GET /api/pcs` 응답과 서버 기록 파일에는 없다.
  - `test_seats_full_409` - seats=1 에서 두 번째 추가 → 409 `seats-full`.
  - `test_command_needs_pc` - LAN 에서 `pcId` 없는 명령 → 400, 사용 중지된 PC → 409, active PC → 200 이고 `apps/rpa/commands/c1/<pc>` 아래에 생긴다.
  - `test_stream_per_pc` - pc_01 스트림을 연 뒤 pc_02 현황을 바꾸면 pc_01 스트림에 `live` 가 오지 않고, pc_01 현황을 바꾸면 온다.
  - `test_company_lists_pcs` - `/api/company` 의 `pcs` 에 active·disabled 가 있고 removed·대기는 없다.
  - `test_remove_clears_spots` - DELETE 뒤 그 PC 의 현황·명령 자리가 비고 실행 기록 조회(`pcId` 그 PC)는 된다.
  - `test_single_pcs_404` - registry 없는 서버의 `/api/pcs` → 404, 명령은 `pcId` 없이 지금처럼 된다.
- [ ] **Step 2:** 실행 → 실패.
- [ ] **Step 3:** 위대로 고친다.
- [ ] **Step 4:** `tests\test_lan_web.py`, `tests\test_local_web_api.py`, `tests\check_web_local.py` 통과.
- [ ] **Step 5: 커밋** - `사내 서버 ① Task 6 - 웹 API 의 여러 PC (pcId 고르기·PC 목록·/api/pcs 추가·중지·삭제·등록 글)`

---

### Task 7: 가짜 PC 셋 전체 흐름 + 회귀

**Files:**
- Test: `tests/test_lan_server.py` 에 `test_three_pcs_end_to_end` 더함
- Modify: `docs/superpowers/plans/2026-11-24-lan-index.md` 의 ① 상태 칸

**Interfaces:**
- Consumes: Task 1~6 전부.

- [ ] **Step 1: 시험** `test_three_pcs_end_to_end` - 웹으로 PC 셋 추가 → 각 등록 글로 `local_store.enroll` → 셋이 각자 현황 PATCH·명령 구독. 관리자가 `pc_02` 에 `launch` 명령 → pc_02 구독에만 오고 pc_01·pc_03 에는 오지 않는다. pc_02 가 queued→running→done 으로 옮기고 실행 기록 POST. 웹 `/api/runs?pcId=pc_02` 에 그 기록, `pcId=pc_01` 에는 없음. 마지막에 `pc_03` 삭제 → pc_03 클라이언트 다음 요청이 `PC_REMOVED`.
- [ ] **Step 2:** `D:\AX\RPA\.venv\Scripts\python.exe tests\test_lan_server.py` → 통과.
- [ ] **Step 3: 회귀** - `D:\AX\RPA\.venv\Scripts\python.exe tests\run_standalone_suite.py all` → '실패한 파일: 0'. 화면 시험(에뮬레이터)은 이 계획이 일반 버전 웹을 건드리지 않으므로 돌리지 않는다.
- [ ] **Step 4:** `graphify update .` (작업 폴더), 목록 문서 ① 상태를 '구현 끝 (커밋 범위)' 로.
- [ ] **Step 5: 커밋** - `사내 서버 ① Task 7 - 가짜 PC 셋 전체 흐름 시험, 계획 목록 상태`
