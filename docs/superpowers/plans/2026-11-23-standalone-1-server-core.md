# 스탠드얼론 ① 서버 핵심 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 스탠드얼론 PC 에서 에이전트가 Firebase 없이 그 PC 의 로컬 서버로 현황을 올리고 명령을 받아 돈다 (라이선스로 업체·PC·정책을 정한다).

**Architecture:** 새 `local_server.py` 가 127.0.0.1:8781 에서 에이전트가 쓰던 RTDB 자리(현황·명령·업체 정책·휴대폰·인증번호)와 Firestore 실행 기록을 흉내 낸다. 에이전트·ACTOR·옵저버는 `fb.Client` 와 같은 메서드를 가진 `local_store.Client` 를 `client_for(cfg)` 로 받아 쓴다. 업체·PC·정책은 우리가 서명한 `license.json` 에서 온다.

**Tech Stack:** Python 3.14 표준 라이브러리(http.server·sqlite3·json·secrets·winreg), 기존 `update_sign.py`(순수 파이썬 Ed25519). 시험은 저장소 관례대로 `.venv\Scripts\python.exe tests\<파일>.py` (통과/실패를 찍고 실패가 있으면 종료 코드 1).

**Spec:** `docs/superpowers/specs/2026-11-23-standalone-local-server-design.md` (5절, 6.1·6.2·6.4, 11절)

## Global Constraints

- 일반(cloud) 버전 동작은 바뀌지 않는다. 각 작업 끝에 일반 버전 시험 `firebase\tests\test_agent.py`·`tests\test_fb_backoff.py`·`tests\test_cloud_scrub.py`·`tests\test_dev_env.py` 가 그대로 통과해야 한다.
- 스탠드얼론 경로는 Firebase·Google·Anthropic·업데이트 사이트에 연결을 **시도하지 않는다**.
- 로컬 서버는 `127.0.0.1` 에만 묶는다 (이 계획에서 사내망 포트 없음 - 계획 ④).
- 포트 `8781`. 데이터 폴더 `rpa_status.install_root()\standalone\` (store.json·runs.db·agent.key·relay.key). 라이선스 `rpa_status.install_root()\license.json`. 버전 종류 파일 `rpa_status.program_dir()\edition.json` = `{"edition": "standalone"}`.
- 시험용 덮어쓰기는 `rpa_status.dev_env` 로만 읽는다 (설치본은 프로그램 폴더에 `test_env.ok` 가 있을 때만 따른다): `RPA_EDITION`, `RPA_MACHINE_GUID`, `RPA_PROGRAMDATA`, `RPA_LOCAL_PORT`.
- 비밀 값(agent.key·relay.key·라이선스 서명 열쇠)은 로그·예외 글·실행 기록에 싣지 않는다. 라이선스 서명 **개인 열쇠 파일은 Claude 가 읽지 않는다** (만들기만 도구가).
- 글은 한국어, 화면·로그 문장은 지금 에이전트 말투 ("…하여 주십시오").
- 파이썬 패치는 Write 도구로 만든 파일로 (bash heredoc·`sed -i` 금지). 코드를 고친 뒤 `graphify update .`.
- 커밋은 작업마다, 메시지 끝에 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. push 는 사용자 지시가 있을 때만.

## Review Focus

1. 에이전트가 명령을 구독하는 중에 로컬 서버가 다시 켜짐 → 스트림이 끝나고(`watch_commands` 가 `"ended"`), 다시 붙으면 대기 중 명령을 다시 받는다 (Task 4 시험).
2. `store.json` 이 반쯤 쓰였거나 깨짐 → 서버가 빈 저장소로 켜지고 깨진 파일을 `store.json.broken` 으로 남긴다, 죽지 않는다 (Task 2 시험).
3. 포트 8781 을 이미 다른 프로그램이 씀 → 두 번째 서버가 조용히 뜨지 않고 사람 말로 로그를 남기고 끝난다 (Task 3 시험).
4. 라이선스가 없음·다른 PC·본문이 고쳐짐·서명 열쇠 없음 → 각각 다른 한국어 글, 에이전트는 종료 코드 2 로 끝나 감독이 다시 켜지 않는다 (Task 1·5 시험).
5. 에이전트가 명령의 `args`·`type` 을 바꾸거나 새 명령을 만듦, 다른 PC 자리를 씀 → 403 (Task 3 시험).

---

### Task 1: 버전 종류 · 라이선스 · 발급 도구

**Files:**
- Create: `edition.py`, `license_check.py`, `tools/make_license.py`
- Modify: `.gitignore` (`firebase/admin/license_signing_key.txt` 줄 추가)
- Test: `tests/test_license.py`

**Interfaces:**
- Produces:
  - `edition.edition() -> str` - `"cloud"` | `"standalone"`. `dev_env("RPA_EDITION")` 먼저, 다음 `program_dir()\edition.json`, 없으면 `"cloud"`. `edition.is_standalone() -> bool`.
  - `license_check.LICENSE_PUBLIC_KEY_HEX: str` (처음엔 `""` - 사용자가 `make_license.py --keygen` 뒤 넣는다)
  - `license_check.LicenseError(Exception)` (글은 사람 말)
  - `license_check.machine_guid() -> str` - `dev_env("RPA_MACHINE_GUID")` 먼저, 다음 `HKLM\SOFTWARE\Microsoft\Cryptography` 의 `MachineGuid`, 소문자.
  - `license_check.license_path() -> str` = `os.path.join(rpa_status.install_root(), "license.json")`
  - `license_check.canonical(body: dict) -> bytes` = `json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")`
  - `license_check.load(path=None, guid=None, public_key=None) -> dict` - 맞으면 본문 dict. 파일 꼴 `{"body": {...}, "sig": "<hex>"}`. 본문 칸: `edition`("standalone"), `company`, `cid`, `pc_id`(MachineGuid 소문자), `issued`("YYYY-MM-DD"), `modules`({키: false}), `features`({"wellife": bool}), `limits`({"schedule": int, "presets": int|null, "parallel": int|null}).
  - `license_check.sign_body(secret: bytes, body: dict) -> dict` - `{"body": body, "sig": update_sign.sign(secret, canonical(body)).hex()}` (발급 도구·시험이 쓴다).

- [ ] **Step 1: 실패하는 시험 쓰기** - `tests/test_license.py` (시험 열쇠는 `update_sign.keygen()` 으로 그 자리에서 만든다):

```python
secret, public = update_sign.keygen()
body = {"edition": "standalone", "company": "시험상사", "cid": "c_test", "pc_id": "aaaa-1111",
        "issued": "2026-11-23", "modules": {"Hold": False}, "features": {"wellife": False},
        "limits": {"schedule": 3, "presets": None, "parallel": None}}
write(tmp, license_check.sign_body(secret, body))
check("맞는 라이선스", license_check.load(tmp, guid="AAAA-1111", public_key=public) == body)   # PC 번호는 대소문자 무시
expect_error("다른 PC", lambda: license_check.load(tmp, guid="bbbb-2222", public_key=public), "이 PC 의 라이선스가 아닙니다")
tampered = json.loads(open(tmp, encoding="utf-8").read()); tampered["body"]["limits"]["schedule"] = 99
write(tmp2, tampered)
expect_error("본문 고침", lambda: license_check.load(tmp2, guid="aaaa-1111", public_key=public), "라이선스 서명이 맞지 않습니다")
expect_error("파일 없음", lambda: license_check.load(missing, guid="aaaa-1111", public_key=public), "라이선스 파일이 없습니다")
expect_error("열쇠 없음", lambda: license_check.load(tmp, guid="aaaa-1111", public_key=""), "라이선스 확인 열쇠가 없습니다")
expect_error("다른 버전 종류", ...body["edition"]="cloud" 로 서명..., "스탠드얼론 라이선스가 아닙니다")
os.environ["RPA_EDITION"] = "standalone"; check("버전 종류 덮어쓰기", edition.edition() == "standalone")
del os.environ["RPA_EDITION"]; check("기본은 cloud", edition.edition() == "cloud")
check("PC 번호 덮어쓰기", with_env("RPA_MACHINE_GUID", "ABC") == "abc")
```
`expect_error(name, fn, text)` = `LicenseError` 가 나고 글에 `text` 가 들어 있음. 다른 PC 글에는 이 PC 번호가 들어간다 (`(PC 번호 bbbb-2222)`).

- [ ] **Step 2: 실패 확인** - `.venv\Scripts\python.exe tests\test_license.py` → `ModuleNotFoundError: license_check`.
- [ ] **Step 3: `edition.py`·`license_check.py` 구현.** 확인 차례: 파일 있음 → JSON → 열쇠 있음 → 서명(`update_sign.verify(bytes.fromhex(key), canonical(body), bytes.fromhex(sig))`) → `edition == "standalone"` → `pc_id` 일치.
- [ ] **Step 4: `tools/make_license.py`** - `--keygen [열쇠 경로]` (기본 `firebase/admin/license_signing_key.txt`, 이미 있으면 거절, 공개 열쇠 hex 를 찍고 "license_check.LICENSE_PUBLIC_KEY_HEX 에 넣으십시오"), `<PC번호> <업체 정보 json> [--key 경로] [--out license.json]` (업체 정보 json = 본문 칸 중 edition·pc_id·issued 를 뺀 것, 도구가 채운다). 열쇠 내용은 찍지 않는다. 시험에 `make_license.main([...])` 을 임시 열쇠 경로로 불러 만든 파일이 `load` 를 통과하는 경우를 더한다.
- [ ] **Step 5: 통과 확인** - 같은 명령 → 실패 0. 일반 버전 시험 넷 통과.
- [ ] **Step 6: 커밋** - `edition.py license_check.py tools/make_license.py tests/test_license.py .gitignore`, 메시지 "스탠드얼론 ① Task 1 - 버전 종류·라이선스(PC 번호·우리 서명)·발급 도구".

### Task 2: 로컬 저장소 (HTTP 없이)

**Files:**
- Create: `firebase/agent/local_server.py` (이 작업은 `Store` 와 `Runs` 만)
- Test: `tests/test_local_store_core.py`

**Interfaces:**
- Produces (`local_server`):
  - `PORT = 8781`, `data_dir() -> str` = `install_root()\standalone` (없으면 만든다)
  - `class Store(path)` - JSON 나무. `get(path, order_by=None, equal_to=None)`, `put(path, value)`, `patch(path, value: dict)` (키에 `/` 가 있으면 여러 자리 쓰기 - RTDB PATCH 와 같다), `delete(path)`. 값이 `None` 이면 지움. 빈 dict 가 된 가지는 없앤다 (RTDB 처럼). 쓸 때마다 `path` 에 원자적으로 저장(임시 파일 → `os.replace`).
  - `Store.subscribe(path, order_by=None, equal_to=None) -> queue.Queue` 와 `unsubscribe(q)` - 바뀔 때마다 `("put"|"patch", {"path": "/<상대 경로>", "data": 값})` 를 넣는다. 처음엔 `("put", {"path": "/", "data": 지금 값(거른 것)})`. `equal_to` 로 거른 구독은 조건에서 빠진 자식에 `("put", {"path": "/<키>", "data": None})`.
  - `class Runs(db_path)` - SQLite. `create(parent, collection, doc_id, fields: dict) -> bool` (이미 있으면 False), `get(path) -> dict|None`, `sum(parent, collection, field, since=None) -> number` (`started_at >= since`, 칸 없는 문서는 뺌), `query(parent, collection, pc_id=None, date=None, limit=50) -> list` (started_at 내림차순 - 계획 ② 웹이 쓴다).
- 깨진 `store.json` 은 `store.json.broken` 으로 옮기고 빈 나무로 시작 (Review Focus 2).

- [ ] **Step 1: 실패하는 시험** - `tests/test_local_store_core.py`:

```python
s = local_server.Store(tmp)
s.put("apps/rpa/live/c1/p1", {"state": "idle"})
check("읽기", s.get("apps/rpa/live/c1/p1") == {"state": "idle"})
s.patch("apps/rpa/commands/c1/p1", {"k1/state": "queued", "k1/type": "launch", "k2/state": "done"})
check("여러 자리 쓰기", s.get("apps/rpa/commands/c1/p1/k1") == {"state": "queued", "type": "launch"})
check("거르기", s.get("apps/rpa/commands/c1/p1", order_by="state", equal_to="queued") == {"k1": {...}})
s.delete("apps/rpa/commands/c1/p1/k2"); s.delete("apps/rpa/commands/c1/p1/k1")
check("빈 가지 없앰", s.get("apps/rpa/commands/c1") is None)
check("다시 열어도 남음", local_server.Store(tmp).get("apps/rpa/live/c1/p1") == {"state": "idle"})
q = s.subscribe("apps/rpa/commands/c1/p1", order_by="state", equal_to="queued")
check("처음 값", q.get(timeout=1) == ("put", {"path": "/", "data": None}))
s.put("apps/rpa/commands/c1/p1/k3", {"state": "queued"})
check("새 명령", q.get(timeout=1) == ("put", {"path": "/k3", "data": {"state": "queued"}}))
s.patch("apps/rpa/commands/c1/p1/k3", {"state": "running"})
check("조건에서 빠짐", q.get(timeout=1) == ("put", {"path": "/k3", "data": None}))
open(tmp2, "w").write('{"apps": {"rp')            # 반쯤 쓴 파일
s2 = local_server.Store(tmp2)
check("깨진 파일 - 빈 나무", s2.get("") is None and os.path.exists(tmp2 + ".broken"))
r = local_server.Runs(db)
check("기록 만들기", r.create("runs/c1", "items", "d1", {"pcId": "p1", "date": "2026-11-23", "started_at": "2026-11-23T09:00:00", "cost": 3}))
check("같은 id 두 번", r.create("runs/c1", "items", "d1", {...}) is False)
r.create("runs/c1", "items", "d2", {"pcId": "p1", "date": "2026-11-23", "started_at": "2026-11-23T10:00:00"})   # cost 없음
check("합 (칸 없는 문서 뺌)", r.sum("runs/c1", "items", "cost") == 3)
check("since", r.sum("runs/c1", "items", "cost", since="2026-11-23T09:30:00") == 0)
check("최근 순", [d["started_at"] for d in r.query("runs/c1", "items", pc_id="p1")] == ["2026-11-23T10:00:00", "2026-11-23T09:00:00"])
```

- [ ] **Step 2: 실패 확인** → `ModuleNotFoundError` (sys.path 에 `firebase/agent` 를 넣는다 - test_fb_backoff.py 와 같게).
- [ ] **Step 3: `Store`·`Runs` 구현.** 잠금 하나(`threading.Lock`)로 쓰기와 구독 알림을 묶는다. Runs 표: `docs(parent TEXT, collection TEXT, id TEXT, pc_id TEXT, date TEXT, started_at TEXT, doc TEXT, PRIMARY KEY(parent, collection, id))`, 합은 `doc` 의 JSON 에서 그 칸을 꺼내 파이썬에서 더한다 (`json_extract` 에 기대지 않는다).
- [ ] **Step 4: 통과 확인.**
- [ ] **Step 5: 커밋** - "스탠드얼론 ① Task 2 - 로컬 저장소(RTDB 자리 흉내·구독, 실행 기록 SQLite)".

### Task 3: 로컬 서버 HTTP · 인증 · 검사

**Files:**
- Modify: `firebase/agent/local_server.py`
- Test: `tests/test_local_server_http.py`

**Interfaces:**
- Consumes: Task 1 `license_check.load`, Task 2 `Store`·`Runs`.
- Produces:
  - `local_server.ensure_keys(folder) -> (agent_key, relay_key)` - 없으면 `secrets.token_urlsafe(32)` 로 `agent.key`·`relay.key` 를 만든다 (파일 권한은 계획 ③).
  - `local_server.make_server(store, runs, lic: dict, keys, host="127.0.0.1", port=PORT) -> ThreadingHTTPServer` - 옛 `rpa_dashboard.DashboardServer` 처럼 `allow_reuse_address=False` + `SO_EXCLUSIVEADDRUSE`, `getfqdn` 을 부르지 않는 bind. 포트가 쓰이면 `OSError` (Review Focus 3).
  - `local_server.main() -> int` - 라이선스 확인(틀리면 로그 남기고 2), 키·저장소 열고 `serve_forever`. 로그는 `data_dir()\로컬서버_기록.txt`.
  - 창구 (모두 `Authorization: Bearer <key>`, 없거나 틀리면 401 `{"error": "Permission denied"}`):
    - `GET|PUT|PATCH|DELETE /db/<path>.json` - RTDB REST 꼴. `GET` 의 `orderBy="state"&equalTo="queued"` (fb 가 보내는 따옴표 그대로), `Accept: text/event-stream` 이면 SSE (`event: put|patch`, `data: {"path","data"}`, 30초마다 `event: keep-alive` / `data: null`). 응답에 `Date` 머리글 (fb.Client.server_now 가 쓴다).
    - `POST /fs/<parent>/<collection>?id=<doc_id>` 본문 = 칸 dict (이미 있으면 409), `GET /fs/<path>`, `GET /fs-sum?parent=&collection=&field=&since=` → `{"sum": n}`.
  - 업체 정책 자리는 라이선스에서 **읽기 전용으로 만들어** 보여 준다: `meta/companies/<cid>/apps/rpa` = `{"modules", "limits", "features"}` (라이선스 본문 그대로), `meta/companies/<cid>/phones` = Store 의 `phones/<cid>` (계획 ④가 채운다, 지금은 비어 있음).
- **검사 (지금 RTDB 규칙과 같은 뜻)** - cid·pc 는 라이선스 값:
  - agent 열쇠: `apps/rpa/live/<cid>/<pc>/**` 읽기·쓰기. `apps/rpa/commands/<cid>/<pc>` 읽기·지우기, 있는 명령에 PATCH 만 - `type`·`args`·`by`·`created_at`·`expires_at` 을 바꾸면 403, 상태는 `queued→running|expired|failed`, `running→done|failed` 만. 새 명령 만들기(없는 키에 PUT/PATCH) 403. `meta/companies/<cid>/**` 읽기. `/fs` 는 `runs/<cid>/items` 만들기·읽기·합.
  - relay 열쇠: `apps/otp/requests/<cid>/**` 읽기·쓰기, `apps/otp/codes/<cid>/**` 읽기·지우기, `meta/companies/<cid>/phones` 읽기.
  - 그 밖 모두 403 `{"error": "Permission denied"}` (fb.HttpError 본문 검사와 같은 글).
  - 명령 만들기와 `args` 의 `excel_pw` 거부·만료(실행·중단 90초, 나머지 600초)는 웹이 명령을 넣는 계획 ② 창구에서 한다 - 이 계획의 시험은 명령을 `Store.put` 으로 직접 넣는다.

- [ ] **Step 1: 실패하는 시험** - `tests/test_local_server_http.py`: 임시 폴더에 Store·Runs, 시험 라이선스 dict(`cid="c1"`, `pc_id="p1"`), `make_server(..., port=0)` 을 스레드로 띄우고 `urllib.request` 로 부른다.

```python
check("열쇠 없음 401", call("GET", "/db/apps/rpa/live/c1/p1.json", key=None).status == 401)
check("현황 쓰기", call("PUT", "/db/apps/rpa/live/c1/p1.json", {"state": "idle"}, key=AGENT).status == 200)
check("다른 PC 403", call("PUT", "/db/apps/rpa/live/c1/p2.json", {}, key=AGENT).status == 403)
check("다른 업체 403", call("GET", "/db/apps/rpa/live/c2/p1.json", key=AGENT).status == 403)
store.put("apps/rpa/commands/c1/p1/k1", {"state": "queued", "type": "launch", "args": {"target": "all"}, "expires_at": 9e9})
check("running 표시", call("PATCH", ".../k1.json", {"state": "running"}, key=AGENT).status == 200)
check("args 바꾸기 403", call("PATCH", ".../k1.json", {"args": {"x": 1}}, key=AGENT).status == 403)
check("running→queued 403", call("PATCH", ".../k1.json", {"state": "queued"}, key=AGENT).status == 403)
check("새 명령 403", call("PUT", ".../k9.json", {"state": "queued", "type": "launch"}, key=AGENT).status == 403)
check("정책은 라이선스", call("GET", "/db/meta/companies/c1/apps/rpa.json", key=AGENT).json()["limits"]["schedule"] == 3)
check("정책 쓰기 403", call("PUT", "/db/meta/companies/c1/apps/rpa/limits.json", {}, key=AGENT).status == 403)
check("relay 는 현황 못 읽음", call("GET", "/db/apps/rpa/live/c1/p1.json", key=RELAY).status == 403)
check("relay 인증번호 요청", call("PUT", "/db/apps/otp/requests/c1/ph1/current.json", {"site": "x"}, key=RELAY).status == 200)
check("Date 머리글", call("GET", "/db/apps/rpa/live/c1/p1.json", key=AGENT).headers.get("Date"))
check("기록 만들기", call("POST", "/fs/runs/c1/items?id=d1", {"pcId": "p1", "started_at": "2026-11-23T09:00:00", "cost": 2}, key=AGENT).status == 200)
check("기록 두 번 409", call("POST", "/fs/runs/c1/items?id=d1", {...}, key=AGENT).status == 409)
check("합", call("GET", "/fs-sum?parent=runs/c1&collection=items&field=cost", key=AGENT).json() == {"sum": 2})
check("다른 업체 기록 403", call("POST", "/fs/runs/c2/items?id=d1", {}, key=AGENT).status == 403)
# SSE: 대기 중 명령만, 처음 값 → 새 명령
lines = sse("/db/apps/rpa/commands/c1/p1.json?orderBy=%22state%22&equalTo=%22queued%22", key=AGENT, until=2)
check("SSE 처음 값", lines[0] == ("put", {"path": "/", "data": None}))   # k1 은 running 이라 빠짐
# 포트 겹침 (Review Focus 3)
expect_oserror("같은 포트 두 번", lambda: local_server.make_server(..., port=srv.server_address[1]))
# 라이선스 틀림 → main() 2 (RPA_PROGRAMDATA 임시, license.json 없음)
check("라이선스 없으면 2", run_main_with_env() == 2 and "라이선스 파일이 없습니다" in read_log())
```

- [ ] **Step 2: 실패 확인.**
- [ ] **Step 3: 구현.** 경로 검사는 `allowed(role, method, path, lic) -> bool` 한 함수 + 명령 PATCH 전용 `command_patch_ok(old: dict, patch: dict) -> bool`. SSE 는 요청 스레드에서 `Store.subscribe` 큐를 30초 기다림으로 읽고, 연결이 끊기면 `unsubscribe`. 서버를 끌 때(`shutdown`) 열린 SSE 는 끝을 보낸 뒤 닫는다 (Review Focus 1 - 에이전트 쪽 스트림이 끝나야 한다).
- [ ] **Step 4: 통과 확인.**
- [ ] **Step 5: 커밋** - "스탠드얼론 ① Task 3 - 로컬 서버 창구(RTDB·Firestore 꼴)·열쇠·규칙과 같은 검사".

### Task 4: `local_store.Client` · 설정 읽기 · 인증번호 연결

**Files:**
- Create: `firebase/agent/local_store.py`
- Modify: `firebase/agent/secret.py` (`load_config`), `otp_relay.py:195-210` (`phone_list`·`agent_relay`)
- Test: `tests/test_local_store_client.py`

**Interfaces:**
- Consumes: Task 3 창구, `fb.HttpError`·`fb.AuthError`·`fb.parse_sse`.
- Produces:
  - `local_store.Client(cfg, opener=None, clock=time.time)` - cfg = `{"standalone": True, "server_url": "http://127.0.0.1:8781", "key": str, "cid": str, "pc_id": str}`. 메서드: `put/patch/get/delete(path[, value|params])`, `stream(path, params=None, timeout=90)` (fb 와 같은 `(event, data)` 제너레이터), `server_now()` (응답 `Date` 로), `renew()` (아무것도 안 함), `token() -> str` (열쇠), `fs_create(path, fields, doc_id)` (path = `"runs/<cid>/items"`), `fs_get(path)`, `fs_sum(parent, collection, field, since=None)`. 4xx/5xx 는 `fb.HttpError(status, body)`, 401 은 `fb.AuthError(401, "INVALID_KEY")`. 127.0.0.1 이 아닌 `server_url` 은 `ValueError` (이 계획 범위).
  - `local_store.client_for(cfg)` - `cfg.get("standalone")` 면 `local_store.Client`, 아니면 `fb.Client`.
  - `secret.load_config(role="agent")` - `edition.is_standalone()` 이면 라이선스(`license_check.load()`)와 `local_server.data_dir()` 의 `agent.key`(role="relay" 면 `relay.key`)로 위 cfg 를 만든다 (`server_url` 포트는 `dev_env("RPA_LOCAL_PORT")` 또는 8781). 키 파일이 없으면 `FileNotFoundError` (서버가 아직 안 켜짐). cloud 면 지금 동작 그대로 (`role` 무시).
  - `otp_relay.phone_list()`·`agent_relay()` - `secret.load_config(role="relay")` + `local_store.client_for(cfg)` (cloud 는 지금과 같음).

- [ ] **Step 1: 실패하는 시험** - `tests/test_local_store_client.py`: Task 3 서버를 port=0 으로 띄우고 `local_store.Client` 로:

```python
c = local_store.Client({"standalone": True, "server_url": url, "key": AGENT, "cid": "c1", "pc_id": "p1"})
c.put("apps/rpa/live/c1/p1", {"state": "idle"}); check("put/get", c.get("apps/rpa/live/c1/p1") == {"state": "idle"})
c.patch("apps/rpa/live/c1/p1", {"state": "running"}); check("patch", c.get("apps/rpa/live/c1/p1")["state"] == "running")
expect(fb.HttpError, 403, lambda: c.put("apps/rpa/live/c1/p2", {}))
expect(fb.AuthError, 401, lambda: local_store.Client({... "key": "틀림" ...}).get("apps/rpa/live/c1/p1"))
check("server_now", abs(c.server_now() - time.time()) < 5)
check("fs_create", c.fs_create("runs/c1/items", {"pcId": "p1", "started_at": "2026-11-23T09:00:00", "cost": 4}, "d1") is not False)
check("fs_sum", c.fs_sum("runs/c1", "items", "cost") == 4)
# watch_commands 가 그대로 돈다 (agent.watch_commands)
store.put("apps/rpa/commands/c1/p1/k1", {"state": "queued", "type": "launch", "created_at": 1, "expires_at": 9e9})
got = []; t = threading.Thread(target=lambda: got.append(agent.watch_commands(c, "apps/rpa/commands/c1/p1", lambda i, cmd: got.append(i))))
t.start(); wait_until(lambda: "k1" in got)
srv.shutdown()                                   # Review Focus 1: 서버가 꺼지면 구독이 끝난다
t.join(5); check("서버 꺼짐 → ended", got[-1] == "ended")
check("client_for 고르기", isinstance(local_store.client_for({"standalone": True, ...}), local_store.Client)
      and isinstance(local_store.client_for({"database_url": "https://x", ...}), fb.Client))
expect(ValueError, None, lambda: local_store.Client({... "server_url": "http://10.0.0.5:8781" ...}))
# secret.load_config 스탠드얼론 (RPA_EDITION=standalone, RPA_PROGRAMDATA=임시, RPA_MACHINE_GUID=p1, 임시 라이선스·키)
cfg = secret.load_config(); check("설정 - 에이전트", cfg["key"] == AGENT and cfg["cid"] == "c1" and cfg["standalone"])
check("설정 - relay", secret.load_config(role="relay")["key"] == RELAY)
```
라이선스 공개 열쇠는 시험에서 `license_check.LICENSE_PUBLIC_KEY_HEX` 를 시험 열쇠로 바꿔 끼운다.

- [ ] **Step 2: 실패 확인.**
- [ ] **Step 3: 구현.** `stream` 은 `fb.Client.stream` 과 같은 줄 읽기(`fb.parse_sse`)를 쓴다. cloud 경로의 `secret.load_config` 본문은 건드리지 않고 맨 앞에 스탠드얼론 분기만.
- [ ] **Step 4: 통과 확인** + 일반 버전 시험 넷 + `tests\test_otp_replay.py`.
- [ ] **Step 5: 커밋** - "스탠드얼론 ① Task 4 - local_store 클라이언트(fb 와 같은 꼴)·설정 읽기·인증번호 연결".

### Task 5: 에이전트 · 감독의 스탠드얼론 분기

**Files:**
- Modify: `firebase/agent/agent.py` (`company_policy` 를 나눔, `Policy`, `real_actions`, `run`, `main`), `firebase/agent/background.py` (`run`, `main`), `rpa_update.py` (`ensure_installed_sig`)
- Test: `tests/test_agent_standalone.py`

**Interfaces:**
- Consumes: Task 1 `edition.is_standalone`·`license_check.load`, Task 4 `client_for`·`secret.load_config`.
- Produces:
  - `agent.policy_from(cid, got: dict) -> (limit, off, wellife, presets, parallel)` - 지금 `company_policy` 의 본문 (`got` = `{"limits","modules","features"}`). `company_policy(client, cid)` 는 `policy_from(cid, client.get(...) or {})` 로 줄어든다 (일반 버전 동작 같음).
  - `agent.LicensePolicy(lic)` - `Policy` 와 같은 `refresh(force=False)`. 값은 `policy_from(lic["cid"], lic)`, 적는 길(`dash.set_policy`·웰라이프 섹션·`migrate_split_sales`)은 `Policy` 와 같은 함수 `apply_policy(got)` 로 나눠 같이 쓴다. AI 는 늘 `st.set_ai(False, None)`.
  - `agent.real_actions(..., standalone=False)` - True 면 `update`·`rollback`·`export_preset`·`import_preset`·`restore_preset` 을 넣지 않는다. 그 종류의 명령이 오면 `Commands.handle` 이 `failed`, result `"스탠드얼론 버전에서는 쓰지 않는 기능입니다."` 로 표시한다 (`decide` 가 아니라 actions 에 없음으로 판정).
  - `agent.run(cfg)` 스탠드얼론 분기: `client = local_store.client_for(cfg)`; 토큰 claims 검사 대신 `cfg["cid"]·cfg["pc_id"]` 가 라이선스와 같은지; `Prices`·`Tokens` 를 만들지 않고 `dash.TOKEN_GATE = None` (막지 않음); `Policy` 대신 `LicensePolicy`; `cleanup_transfers` 부르지 않음; `refresh_icons`·업데이트 점검 등 업데이트 사이트에 닿는 호출 없음.
  - `agent.main()` 스탠드얼론: `secret.load_config()` 가 `LicenseError` 면 그 글을 로그에 남기고 **2** (처음 묻기 `ask_setup` 없음), `FileNotFoundError`(키 없음 = 서버 아직 안 켜짐)면 로그 후 **1** (감독이 잠시 뒤 다시 켠다).
  - `rpa_update.ensure_installed_sig(program_root, get=None, pub=None)` - 스탠드얼론이면 받지 않고, 설치본에 실린 `manifest.sig`(프로그램 폴더)가 맞으면 그것을 `st.installed_sig_path()` 에 둔다. 없거나 틀리면 None (계획 ③ 빌드가 싣는다).
  - `background.server_command(exe_dir=None) -> list` (`agent_command` 와 같은 꼴, `local_server.py`), `background.main(...)` 스탠드얼론: 서버를 먼저 띄우고 에이전트를 띄운다. 둘 다 같은 일(job)에 넣고, 서버가 죽으면 다시 켠다 (에이전트 다시 켜기 규칙은 지금 그대로). `warm_windows_roots()` 는 부르지 않는다.

- [ ] **Step 1: 실패하는 시험** - `tests/test_agent_standalone.py`:

```python
check("정책 나눔 - 같은 값", agent.policy_from("c1", {"limits": {"schedule": 3}, "modules": {"Hold": False}, "features": {}}) == (3, ["Hold"], False, None, None))
check("웰라이프 업체코드", agent.policy_from("wellife_x", {})[2] is True)
acts = agent.real_actions(standalone=True)
check("업데이트·옮기기 빠짐", not ({"update", "rollback", "export_preset", "import_preset", "restore_preset"} & set(acts)))
check("일반은 그대로", "update" in agent.real_actions())
fake = FakeClient()                              # patch 를 기록하는 가짜
cmds = agent.Commands(fake, "c1", "p1", acts)
cmds.handle("k1", {"state": "queued", "type": "export_preset", "expires_at": 9e9, "args": {}}, now=1)
check("빠진 종류 → failed", fake.last_patch["state"] == "failed" and "스탠드얼론 버전에서는" in fake.last_patch["result"])
applied = []; agent.apply_policy = lambda got: applied.append(got)   # 적는 길 가짜
agent.LicensePolicy({"cid": "c1", "limits": {"schedule": 2}, "modules": {}, "features": {}}).refresh(force=True)
check("라이선스 정책 적힘", applied and applied[0][0] == 2)
# main: 라이선스 없음 → 2, 글 남김 (RPA_EDITION=standalone, RPA_PROGRAMDATA=빈 임시)
check("라이선스 없음 → 2", agent.main() == 2 and "라이선스 파일이 없습니다" in read_agent_log())
# ensure_installed_sig: 스탠드얼론은 망에 안 나감 (get 이 불리면 실패)
check("서명 - 망 안 씀", rpa_update.ensure_installed_sig(prog_dir, get=lambda *a: fail("불림")) in (None, sig_hex))
# background: 서버 → 에이전트 차례, 서버가 끝나면 다시 켬, warm_windows_roots 안 부름
started = run_background_with_fakes(server_exits_once=True)
check("차례·다시 켬", started[:3] == ["server", "agent", "server"])
check("인증서 데우기 안 함", not warm_called)
```

- [ ] **Step 2: 실패 확인.**
- [ ] **Step 3: 구현.** 분기는 모두 `edition.is_standalone()` 한 곳에서 정해 `run` 첫머리에 `standalone` 변수로 둔다. `Commands.handle` 이 actions 에 없는 종류를 만나면 지금 어떻게 되는지 먼저 읽고, `failed` + 위 글로 맞춘다 (일반 버전에선 생기지 않는 경우).
- [ ] **Step 4: 통과 확인** + 일반 버전 시험 넷 + `tests\test_background.py`·`tests\test_rpa_update.py`.
- [ ] **Step 5: 커밋** - "스탠드얼론 ① Task 5 - 에이전트·감독 분기(라이선스 정책, 토큰·업데이트·옮기기 없음, 서버 함께 띄우기)".

### Task 6: 끝에서 끝까지

**Files:**
- Test: `tests/test_standalone_e2e.py`

**Interfaces:**
- Consumes: 위 모두. 새 실행 코드 없음 (시험만 - 고칠 것이 나오면 해당 작업 파일을 고친다).

- [ ] **Step 1: 시험 쓰기** - 임시 `RPA_PROGRAMDATA`·`RPA_STATUS_DIR`, `RPA_EDITION=standalone`, `RPA_MACHINE_GUID=p1`, `RPA_LOCAL_PORT=<빈 포트>`, 시험 라이선스(공개 열쇠 바꿔 끼움), 시험 표시 `test_env.ok`. `local_server.main` 을 하위 프로세스로, 에이전트는 `agent.run(secret.load_config())` 을 스레드로 (실제 ERPia·RPA 를 띄우지 않게 `RPA_DASHBOARD_DRY_RUN=1`).

```python
wait_until(lambda: srv_get("apps/rpa/live/c1/p1") is not None, 20)
check("현황이 올라옴", srv_get("apps/rpa/live/c1/p1").get("heartbeat") is not None)
store_put_via_admin("apps/rpa/commands/c1/p1/k1", {"state": "queued", "type": "set_schedule",
                    "args": {"enabled": False, "days": [0], "slots": []}, "created_at": now, "expires_at": now + 600, "by": "web"})
wait_until(lambda: srv_get("apps/rpa/commands/c1/p1/k1")["state"] in ("done", "failed"), 20)
check("명령 처리됨", srv_get("apps/rpa/commands/c1/p1/k1")["state"] == "done")
check("정책이 PC 설정에", rpa_status.read_settings()["schedule"]["policy"]["limit"] == 3)   # 라이선스 limits.schedule
check("바깥 연결 없음", outbound_hosts() <= {"127.0.0.1"})
```
`store_put_via_admin` = 서버 프로세스의 `store.json` 이 아니라 시험용 관리 열쇠 창구가 없으므로, 이 시험만 서버를 같은 프로세스 스레드(`make_server`)로 띄워 `Store.put` 을 직접 부른다 (그럼 `local_server.main` 대신 같은 구성). `outbound_hosts()` = 시험 동안 `socket.create_connection`·`socket.socket.connect` 를 감싸 대상 호스트를 모은 집합.

- [ ] **Step 2: 실행** → 처음엔 빠진 연결이 드러날 수 있다. 원인을 찾아 해당 작업 파일을 고친다 (시험을 고치지 않는다).
- [ ] **Step 3: 통과 확인** + 이 계획의 시험 다섯 + 일반 버전 시험 넷 + `graphify update .`.
- [ ] **Step 4: 커밋** - "스탠드얼론 ① Task 6 - 끝에서 끝까지 (에이전트 ↔ 로컬 서버, 바깥 연결 없음)".
