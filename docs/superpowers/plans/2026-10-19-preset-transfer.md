# 프리셋 가져오기·넣어 주기·중간부터 고치기 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 총괄이 업체 PC 의 프리셋을 파일로 가져오고 고쳐 넣고, 옵저버가 미리보기 중 멈춘 자리부터 이어 기록하고, 업체 관리자가 자기 PC 끼리 프리셋을 복사한다.

**Architecture:** 프리셋 한 개 = 파일 한 개(`autopilot-preset` JSON). PC 쪽 읽기·검사·바꾸기·되돌리기는 새 모듈 `preset_transfer.py` 하나가 맡고 에이전트와 옵저버가 같이 쓴다. PC 사이·관리 화면과 PC 사이는 Realtime DB 의 새 자리 `apps/rpa/transfers/{cid}/{tid}` 에 잠깐 올렸다 지우고, 명령 `export_preset`·`import_preset`·`restore_preset` 으로 움직인다. 옵저버의 [수정]은 미리보기 브라우저에 기록기를 그대로 붙인다.

**Tech Stack:** Python 3.14 (tkinter, Playwright + 깔린 Edge), Firebase Realtime DB 규칙, Node 관리 도구(`firebase/admin`), 업체 웹(ES modules).

**Spec:** docs/superpowers/specs/2026-10-19-preset-transfer-design.md

## Global Constraints

- 아이디·비밀번호·로그인 세션은 어떤 경로(전송 자리·파일·명령 args·결과·로그·관리 기록)로도 PC 밖으로 나가지 않는다. 비밀번호 값이 든 파일은 받지 않는다.
- 같은 사이트코드를 넣으면 그 칸의 아이디·비밀번호·인증 휴대폰·켬/끔은 그대로. 다른 사이트코드(빈 칸 포함)면 아이디·비밀번호·인증 휴대폰을 지우고 꺼짐(Stts 9).
- 넣으면 바로 바뀐다 (업체 확인 없음). 바꾸기 전 것은 칸마다 하나 보관, `restore_preset` 으로 되돌린다.
- 받을 칸 번호를 지정한다 (기본: 같은 번호). 기록이 있는 칸이면 덮어쓴다.
- 옵저버가 열려 있거나 ACTOR·PROCESS 가 실행 중이면 끝날 때까지 기다리고, 명령 만료까지 못 하면 결과 "옵저버 또는 ACTOR가 실행 중이라 변경하지 못했습니다."
- 메일 고르기 기억(`메일기억/PRESETn.json`)은 옮기지도 손대지도 않는다.
- 인증 휴대폰(Phone·SmsSenders)은 업체 안 PC 끼리 복사에서만 따라간다. 총괄 파일에는 넣지 않는다.
- 전송 자리 만료 6시간 (`TRANSFER_TTL_SEC = 6 * 3600`). 명령 만료는 지금 그대로 600초.
- 화면·기록·결과 글은 docs/ui-wording.md 업무 서식. '판' 아님 '버전'.
- 무료 요금제: Cloud Functions 를 새로 쓰지 않는다. 관리 작업은 `firebase/admin/ops.js`·`routes.js` 에만 (functions/shared 는 `sync.mjs` 가 복사한다 - 손대지 않는다).
- 시험은 저장소 관례: `.venv\Scripts\python.exe tests\X.py` (단순 스크립트, `check(...)`), 에뮬레이터 시험은 `firebase emulators:exec`. 실서버·실업체에는 시험하지 않는다. 화면(Edge 창)을 띄우는 시험은 돌리기 전에 사용자에게 알린다.
- 새 파이썬 파일은 `tools/build_release.py` 의 배포 파일 목록에 넣는다 (에이전트는 .py 로 돈다).
- 코드를 바꾼 뒤 `graphify update .`

## Review Focus

1. 받는 PC 가 꺼져 있어 `import_preset` 이 만료됨 → 전송 자리가 6시간 뒤 다른 에이전트 주기 점검에서 지워져야 한다 (Task 2 `cleanup_transfers` 시험).
2. 칸이 2개뿐인 PC 의 5번 칸에 넣기 (업체 프리셋 수 10) → 3·4번은 빈 칸으로 채워지고 5번에 들어간다; 수를 넘으면 그 칸만 거절 (Task 1 시험).
3. 미리보기가 새 창(팝업)을 연 뒤 [수정] → 이어 기록한 단계의 탭 번호가 원래 기록의 번호와 맞아야 한다 (Task 5 시험).
4. 64 KB 가 넘는 프리셋 파일을 관리 화면에서 넣기 → 받아져야 한다 (Task 4 시험, 200 KB 기록).
5. 옛 버전 에이전트 PC (새 명령을 모름) 로 복사 → 업체 웹이 그 PC 를 고를 수 없게 막는다 (`live.preset_transfer` 표시, Task 2·7 시험).

---

### Task 1: PC 쪽 프리셋 파일·바꾸기·되돌리기 (`preset_transfer.py`)

**Files:**
- Create: `preset_transfer.py`
- Modify: `rpa_status.py` (`preset_summary` 에 `backup` 칸)
- Modify: `tools/build_release.py` (PROGRAM_FILES 에 `("preset_transfer.py", "preset_transfer.py")`)
- Test: `tests/test_preset_transfer.py` (env 설정은 `tests/test_presets.py` 와 같게: `RPA_USER_CONFIG`·`RPA_PROGRAMDATA`·`RPA_STATUS_DIR`·`RPA_OBSERVER_LOCK`)

**Interfaces:**
- Produces (모두 `preset_transfer` 모듈):
  - `FILE_KIND = "autopilot-preset"`, `FILE_VERSION = 1`
  - `export_item(no: int, with_phone: bool = False, source: dict | None = None) -> dict` — `{"kind","version","exported_at","from": source or {}, "no","name","code","record"}` + with_phone 이면 `"phone"`, `"senders"`. 빈 칸이면 `ValueError("프리셋 {no}에 기록이 없습니다.")`.
  - `check_file(obj) -> dict` — 형식 검사, 통과하면 obj. 틀리면 `ValueError(한국어 사유)`. 검사: kind·version, name·code 문자열, `record.steps` 목록, `record.version == web_replay.RECORD_VERSION`, 값이 든 비밀번호 단계(`kind == "secret"` 이고 `value` 가 비어 있지 않음, 또는 `credential == "PW"` 인데 `value` 있음) 없음, `phone`/`senders` 외 아이디·비밀번호 칸(`id`, `pw`, `ID`, `PW`) 없음.
  - `apply(items: list[tuple[dict, int]]) -> tuple[list[int], list[tuple[int, str]]]` — (넣은 칸들, [(칸, 사유)]). 칸마다 따로 성공/거절. 거절 사유: `"프리셋 수({limit}개)를 넘는 칸입니다."`, `"프리셋 {k}와(과) 같은 사이트코드 {code}를 사용합니다."`, `check_file` 사유.
  - `restore(slots: list[int]) -> tuple[list[int], list[tuple[int, str]]]` — 보관이 없으면 `"보관된 이전 기록이 없습니다."`.
  - `backup_path(no: int) -> str` — `os.path.join(st.data_dir(), "프리셋보관", f"PRESET{no}.json")`.
- `apply` 의 칸 처리 (이 순서):
  1. `st.read_presets()`; 칸 번호가 `st.preset_limit()` 를 넘으면 거절. 목록이 짧으면 `st.blank_preset` 으로 채운다.
  2. 그 칸에 기록이 있으면 보관: `{"preset": 그 칸 dict, "site": Sites["PRESETn"] 그대로(봉인된 PW 포함 - PC 밖으로 안 나감)}` 를 `backup_path(no)` 에 (덮어씀).
  3. 사이트코드가 다른 칸과 겹치면 거절 (보관은 그대로 두지 않고 지운다).
  4. 칸 내용 = 파일의 name·code·record, `saved_at` = 지금.
  5. Sites: 같은 code 이면 기존 칸 유지(`note` = name, `URL` = record.start_url). 다르면 `{"URL", "ID": "", "PW": "", "Action": [st.REPLAY_ACTION], "Stts": 9, "Preset": no, "note": name}` + 파일에 phone·senders 가 있으면 `Phone`·`SmsSenders`.
  6. `st.write_presets` 한 번, `st.write_user_config` 한 번 (모든 칸을 다 다룬 뒤). `st.save_preset_sites` 는 쓰지 않는다 (빈 비밀번호로 지울 수 없다).
- `rpa_status.preset_summary()` 의 각 항목에 `"backup": os.path.isfile(preset_transfer.backup_path(no))` — 순환 import 를 피하려면 경로 계산을 `rpa_status.preset_backup_path(no)` 로 두고 `preset_transfer.backup_path = st.preset_backup_path`.

- [ ] **Step 1: 실패하는 시험 쓰기** — `tests/test_preset_transfer.py`:
  - `export_item(1)` 의 키 = `{"kind","version","exported_at","from","no","name","code","record"}`, 아이디·비밀번호 칸 없음; `with_phone=True` 면 `phone`·`senders` 가 Sites 값.
  - `check_file` 거절: kind 다름, version 2, steps 가 dict, 비밀번호 값이 든 secret 단계, `"PW"` 키.
  - 같은 code 로 1번 칸에 apply → Sites PRESET1 의 ID·PW·Stts·Phone 그대로, 이름·기록만 바뀜, `backup_path(1)` 있음.
  - 다른 code 로 1번 칸 → ID "" · PW "" · Stts 9 · Phone 없음.
  - 칸 2개뿐인 PC 에서 칸 5 (preset_limit 10: `st.write_settings` 로 `schedule.policy.presets=10`) → 3·4 빈 칸, 5 에 들어감; 칸 11 → 거절 사유 `"프리셋 수(10개)를 넘는 칸입니다."`, 칸 5 는 그대로 성공.
  - 다른 칸과 code 겹침 → 그 칸만 거절, 다른 칸은 성공.
  - `restore([1])` → 칸 1 기록·Sites 가 바꾸기 전과 같음; 보관 없는 칸 → `"보관된 이전 기록이 없습니다."`.
  - `st.preset_summary()` 의 1번 `backup is True`.
  - 메일 기억 파일(`st.mail_memory_path(1)`)을 미리 만들어 두면 apply·restore 뒤에도 내용이 같다.
- [ ] **Step 2: 돌려 실패 확인** — `.venv\Scripts\python.exe tests\test_preset_transfer.py` → `ModuleNotFoundError: preset_transfer`
- [ ] **Step 3: `preset_transfer.py` 와 `rpa_status.preset_backup_path`·`preset_summary.backup` 구현**, build_release 목록에 한 줄.
- [ ] **Step 4: 통과 확인** — 위 시험 "실패: 없음", 그리고 `tests\test_presets.py`, `tests\test_build_release.py` 도 통과.
- [ ] **Step 5: 커밋** — `프리셋 파일·넣기·되돌리기 (preset_transfer) - 설계 2026-10-19 4.4·6절`

### Task 2: 에이전트 명령 셋 + 전송 자리 정리

**Files:**
- Modify: `firebase/agent/agent.py`
- Test: `firebase/tests/test_agent.py` (새 절)

**Interfaces:**
- Consumes: Task 1 의 `preset_transfer.export_item/check_file/apply/restore`.
- Produces:
  - `KNOWN_TYPES` 에 `"export_preset", "import_preset", "restore_preset"`.
  - `TRANSFER_TTL_SEC = 6 * 3600`, `TRANSFER_RE = re.compile(r"^[A-Za-z0-9_-]{16,40}$")`, `transfer_path(cid, tid) -> f"apps/rpa/transfers/{cid}/{tid}"`.
  - `Commands` 가 새 셋에는 handler 를 `action(args, meta)` 로 부른다 (`meta = {"by": cmd["by"], "expires_at": cmd["expires_at"]}`), 이름 목록 `META_TYPES`. 기존 handler 는 지금처럼 `action(args)`.
  - `SLOW_TYPES = ("import_preset",)` — running 으로 표시한 뒤 데몬 스레드에서 돌리고 그 스레드가 done/failed 를 쓴다. 스레드는 하나씩 (`threading.Lock`). 명령 흐름(SSE)을 막지 않는다.
  - handler (`real_actions` 안, `client`·`cid`·`pc_id` 를 받을 수 있게 인자 추가):
    - `export_preset(args{"tid", "nos": [int], "with_phone": bool}, meta)` → 전송 자리에 `{"by": meta.by, "from_pc": pc_id, "created_at": ms, "expires_at": ms + TRANSFER_TTL_SEC*1000, "presets": [export_item(n, with_phone, {"cid","pcId","no"})...]}` 를 PUT. tid 가 `TRANSFER_RE` 아니면 RuntimeError. 결과 `"프리셋 {n}개를 보냈습니다."`.
    - `import_preset(args{"tid", "slots": [int]}, meta)` → 마감(`meta.expires_at`)까지 2초마다: 전송이 아직 없거나 `busy()` 면 기다림. 마감이면 RuntimeError (전송 없음: `"보낼 PC에서 프리셋이 도착하지 않았습니다."`, 바쁨: `"옵저버 또는 ACTOR가 실행 중이라 변경하지 못했습니다."`). 도착하면 `apply(list(zip(presets, slots)))`, 전송 자리 DELETE, 결과 글 (아래), 실행 기록 한 건.
    - `restore_preset(args{"nos": [int]}, meta)` → busy 기다림 같음, `restore`, 결과·실행 기록.
  - `busy() -> bool` = `dash.any_rpa_running() or dash.launch_state() is not None or st.observer_open()` (업데이트 `idle()` 과 같은 조건).
  - `cleanup_transfers(client, cid, now_ms) -> int` — `apps/rpa/transfers/{cid}` 를 읽어 `expires_at < now_ms` 인 것 DELETE, 지운 수. `run()` 의 1초 루프에서 10분마다 (`policy.refresh()` 옆, AuthError 는 다시 올림).
  - live 에 `"preset_transfer": 1` 을 싣는다 (`push_live` 하는 스냅숏) — 업체 웹이 새 명령을 아는 PC 만 고르게.
- 결과·실행 기록 글 (업무 서식, 실행 기록은 `st.append_history(st.history_record({...program "observer"...}))`, `run_id` 는 `f"preset_{명령 key}"`):
  - by == `"admin-tool"` 가져감: `"총괄 계정이 프리셋 {no} ({name})을(를) 가져갔습니다."`
  - by == `"admin-tool"` 넣음: `"총괄 계정이 프리셋 {no}을(를) 변경하였습니다. (이전 기록 보관)"`
  - 업체 안 복사 받음: `"PC {from_label}의 프리셋 {n}개를 복사하였습니다. 아이디·비밀번호가 없는 프리셋은 옵저버에서 입력하여 주십시오."` (from_label = 전송의 `from_pc`)
  - 거절된 칸이 있으면 결과 끝에 `" 변경하지 못한 프리셋: {칸} ({사유})"` 를 잇는다.
  - 되돌림: `"프리셋 {칸들}을(를) 이전 기록으로 되돌렸습니다."`

- [ ] **Step 1: 실패하는 시험 쓰기** (`firebase/tests/test_agent.py` 새 절, `RecClient`·`make_cmds` 와 temp `RPA_USER_CONFIG` 사용):
  - `ag.decide` 가 세 type 을 'run'.
  - `export_preset` → 가짜 client 의 PUT 경로 `apps/rpa/transfers/c_demo/<tid>`, 값에 `from_pc == "pc_office"`, `expires_at - created_at == 6*3600*1000`, presets[0] 에 ID·PW 없음. 나쁜 tid `"a/b"` → failed.
  - `import_preset`: 전송 GET 이 처음 두 번 None → 세 번째에 도착하면 apply 되고 DELETE, 명령 done. busy 가 계속 True 이고 마감이 지나면 failed + 결과 `"옵저버 또는 ACTOR가 실행 중이라 변경하지 못했습니다."` (시계·sleep 은 주입해 시험이 빨리 끝나게).
  - `Commands.handle` 이 import_preset 을 받으면 곧바로 돌아오고(스레드), 스레드가 끝난 뒤 done 패치가 있다.
  - `cleanup_transfers`: 만료 1건·안 만료 1건 → 1건만 DELETE, 반환 1.
  - 실행 기록: `st.read_history(program="observer")` 마지막 건 log_tail 에 `"총괄 계정이 프리셋 1을(를) 변경하였습니다. (이전 기록 보관)"`.
  - live 스냅숏에 `preset_transfer == 1`.
- [ ] **Step 2: 실패 확인** — `cd firebase; ..\.venv\Scripts\python.exe tests\test_agent.py` → 새 절 FAIL
- [ ] **Step 3: 구현**
- [ ] **Step 4: 통과 확인** — test_agent 전부 통과 (기존 256 + 새 것)
- [ ] **Step 5: 커밋** — `에이전트: 프리셋 보내기·받기·되돌리기 명령과 전송 자리 정리 (설계 2026-10-19 4.1·4.3·4.4·5절)`

### Task 3: Realtime DB 규칙

**Files:**
- Modify: `firebase/rules/database.rules.json`
- Test: `firebase/tests/rules.test.js`

**Interfaces:**
- 명령 `type` 목록에 `export_preset`·`import_preset`·`restore_preset` (그 업체 admin·super 가 만든다 - 지금 규칙 그대로).
- 새 `apps/rpa/transfers/$cid`:
  - `.read` (**`$cid` 에 둔다 - `$tid` 가 아니다**): 그 업체 agent 또는 super. 에이전트 `cleanup_transfers` 가 `apps/rpa/transfers/{cid}` 를 `?shallow=true` 로 읽어 tid 목록을 얻는데, RTDB 규칙은 위에서 아래로만 내려 주므로 `$tid` 에만 `.read` 가 있으면 그 읽기가 401 (규칙 거부) 이 되어 만료된 전송이 영영 안 지워진다 (Review Focus 1).
  - `$tid`:
    - `.write`: super, 또는 그 업체 agent 가 (새로 만들 때 `!data.exists()` 이고 `newData.child('from_pc').val() === auth.token.pcId`) 또는 지울 때(`!newData.exists()`).
    - `.validate` (지우기 아닐 때): `$tid` 가 `^[A-Za-z0-9_-]{16,40}$`, children `from_pc`·`by`·`created_at`·`expires_at`·`presets`, `by` 문자열 (에이전트 `do_export` 가 명령의 `by` 를, 관리 화면이 `"admin-tool"` 을 싣는다 - `$other: false` 를 두려면 `by` 를 빼먹지 말 것), `expires_at` 숫자이고 `created_at + 21600000` 이하.
- [ ] **Step 1: 실패하는 시험 쓰기** (rules.test.js, 기존 persona): asAgentA1 이 from_pc pc1·by 가 든 전송 만들기 성공 / from_pc pc2 로 실패; asAgentA2 가 `apps/rpa/transfers/ca` 를 shallow 로 읽기 성공 (`get(query(ref(...)))` 대신 REST `?shallow=true` 와 같은 뜻으로 `get(ref(db, "apps/rpa/transfers/ca"))`), asAdminA·asAgentB 는 그 읽기 실패; asAgentA2 가 `$tid` 읽기·지우기 성공; asAdminA 읽기 실패·쓰기 실패; asAgentB(다른 업체)·asViewerA 읽기 실패; asSuper 읽기 성공; 만료 7시간 실패; asAdminA 가 `import_preset` 명령 만들기 성공.
- [ ] **Step 2: 실패 확인** — `cd firebase\tests; npm test` → 새 시험 실패
- [ ] **Step 3: 규칙 구현**
- [ ] **Step 4: 통과 확인** — `npm test` 모두 통과
- [ ] **Step 5: 커밋** — `규칙: 프리셋 전송 자리·명령 셋 (설계 2026-10-19 5절)`

### Task 4: 관리 화면 - 가져오기(파일 내려받기)·넣어 주기(파일 올리기)·되돌리기

**Files:**
- Modify: `firebase/admin/ops.js`, `firebase/admin/routes.js`, `firebase/admin/admin.js` (본문 크기), `firebase/admin/AFTERMARKET_SETUP.html`
- Test: `firebase/tests/check_admin.py`

**Interfaces:**
- Consumes: Task 2 명령·전송 모양, Task 3 규칙 (Admin SDK 는 규칙을 건너뛰지만 모양은 같게).
- Produces (ops.js, export):
  - `exportPreset(cid, pcId, no) -> {key, tid}` — tid 는 `crypto.randomBytes(10).toString("hex")` (영문 소문자·숫자 20자 - routes 의 `:param` 정규식 `[a-z0-9_]+` 와 `TRANSFER_RE` 를 둘 다 통과); `sendAdminCommand(cid, pcId, "export_preset", {tid, nos: [no], with_phone: false})`.
  - `takeTransfer(cid, tid) -> {file} | {pending: true}` — 전송을 읽어 있으면 지우고 `presets[0]` 을 돌려준다.
  - `importPreset(cid, pcId, file, slot) -> {key}` — 가벼운 검사(kind·version·`record.steps` 목록·`"PW"`/`"ID"`/`"pw"`/`"id"` 키 없음, JSON 길이 8 MB 이하, slot 1~40 정수) 틀리면 `Refused`; 전송 자리에 `{by: "admin-tool", from_pc: "admin", created_at, expires_at, presets: [file]}` set → `sendAdminCommand(..., "import_preset", {tid, slots: [slot]})`.
  - `restorePreset(cid, pcId, no) -> {key}`.
  - `commandStatus(cid, pcId, key) -> {type, state, result}`.
  - `companyDetail` 의 pcs 각 행에 `presets` (= `live.presets`) 를 더한다.
- routes.js:
  - `["POST", "/api/companies/:cid/pcs/:pcId/presets/:no/export", (b,p) => ops.exportPreset(p.cid, p.pcId, Number(p.no)), (b,r,p) => \`프리셋 가져오기 ${p.cid}/${p.pcId} ${p.no}\`]`
  - `["GET", "/api/companies/:cid/transfers/:tid", (b,p) => ops.takeTransfer(p.cid, p.tid), null]`
  - `["POST", "/api/companies/:cid/pcs/:pcId/presets/import", (b,p) => ops.importPreset(p.cid, p.pcId, b.file, b.slot), (b,r,p) => \`프리셋 넣어 주기 ${p.cid}/${p.pcId} ${b.slot}\`]` (기록 글에 파일 내용 금지)
  - `["POST", "/api/companies/:cid/pcs/:pcId/presets/:no/restore", ..., \`프리셋 되돌리기 ...\`]`, `["GET", "/api/companies/:cid/pcs/:pcId/commands/:key", ...]` (key 는 push key - 대문자·`-` 가 있어 같은 정규식 문제: 이 route 만 `[A-Za-z0-9_-]+` 를 받게 `compile` 에 패턴 덮어쓰기를 더하거나, 상태를 `GET /api/companies/:cid/pcs/:pcId/status` 의 `pcUpdateStatus` 에 마지막 프리셋 명령으로 싣는다 - 구현자가 고른다, 시험은 같다).
- admin.js: `readJson` 상한을 이 import route 만 8 MB (나머지는 65536 그대로).
- HTML: PC 표에 '프리셋' 열 [프리셋] 단추 → 그 PC 아래 펼침: 프리셋마다 `번호 · 이름 · 사이트코드 · 단계 수` + [가져오기] (+ `backup` 이면 [되돌리기]); 아래 `<input type="file" accept=".json">` + 칸 번호 칸(기본 = 파일의 no) + [넣어 주기] (confirm `"프리셋 {칸}을(를) 이 파일로 변경합니다. 기록이 있으면 덮어쓰며 이전 기록은 PC에 보관됩니다. 진행하시겠습니까?"`). 안내 한 줄: `"가져온 파일에는 아이디·비밀번호가 없습니다. 검색어 등 입력한 값은 포함될 수 있습니다."`
  - [가져오기]: export → 2초마다 transfer 를 받아 오면 `Blob` + `<a download>` 로 `프리셋_{cid}_{pcId}_{no}.json` 저장, 60초 넘으면 `"PC가 응답하지 않습니다."`.
  - [넣어 주기]·[되돌리기]: 명령 상태를 2초마다, done/failed 의 `result` 를 flash.
- [ ] **Step 1: 실패하는 시험 쓰기** (check_admin.py 새 절, 에뮬레이터): 업체·PC 와 `live/.../presets` 를 심고 → [프리셋] → [가져오기] 클릭 → 명령 `export_preset` args `{nos:[1], with_phone:false, tid}` 확인 → 시험이 에이전트 대신 전송을 써 넣음 → 내려받은 파일(page.expect_download) 내용 = 그 프리셋, 전송 자리 지워짐, 관리 기록에 `"프리셋 가져오기 t_new/pc1 1"` 있고 기록 내용 없음. 200 KB 기록 파일을 [넣어 주기] → 전송 자리 presets[0] 이 그 파일, 명령 `import_preset` args `slots:[3]`. `"PW"` 키가 든 파일 → 거절 글, 명령 안 생김. [되돌리기] → `restore_preset`.
- [ ] **Step 2: 실패 확인** — `cd firebase\tests; firebase emulators:exec --config ../firebase.json --only auth,database,firestore --project rpa-test-f02e0 "..\..\.venv\Scripts\python.exe check_admin.py"` (`PYTHONIOENCODING=utf-8`, JDK 21 은 `emu_env.ps1`)
- [ ] **Step 3: 구현**
- [ ] **Step 4: 통과 확인** — check_admin 전부, 그리고 `node functions/sync.mjs` 뒤 `check_admin_web.py` 도 통과 (웹 관리 화면이 같은 routes 를 쓴다)
- [ ] **Step 5: 커밋** — `관리 화면: 프리셋 가져오기·넣어 주기·되돌리기 (설계 2026-10-19 4.1절)`

### Task 5: 기록 이어 붙이기 (`web_replay`)

**Files:**
- Modify: `web_replay.py`
- Test: `tests/test_web_replay.py` (새 절, 가짜 쇼핑몰 `tests/fake_mall.py`, headless)

**Interfaces:**
- Produces:
  - `Recorder.adopt(pages: dict[int, Page]) -> None` — 이미 열린 탭들을 그 번호 그대로 받는다: `self.pages` 를 번호 0..max 의 목록으로 채우고(빈 번호는 `None`), 탭마다 `self._page(page)` 하고 지금 문서의 모든 frame 에 기록 JS 를 넣는다 (`frame.evaluate(JS)`, 이미 들어 있으면 두 번 붙지 않게 JS 첫 줄의 가드 사용). `_no(page)` 가 `None` 자리를 건너뛰고 새 탭은 max+1 부터 받는지 확인.
  - `continue_record(head: dict, raw_new: list[dict], record_date: datetime.date) -> dict` — head 는 이미 다듬은 기록(`finalize` 결과 모양)의 남길 앞부분, raw_new 는 기록기의 새 단계(`t` 있음). `finalize(raw_new, record_date, head["start_url"], head.get("viewport"))` 의 steps 를 head steps 뒤에 붙이고, 새 쪽의 `appearsAfter` 를 `len(head["steps"])` 만큼 민다. 새 쪽 첫 단계의 `gap` 은 `STEP_GAP_AFTER_EDIT = 1000` (ms). 반환 = head 의 나머지 칸 + 합친 steps.
- [ ] **Step 1: 실패하는 시험 쓰기**:
  - `continue_record`: head 2단계 + raw 3단계(그중 `firstSeen` 으로 appearsAfter 가 생기는 것 하나) → 5단계, 새 쪽 appearsAfter 가 head 길이만큼 밀림, 첫 새 단계 gap 1000, start_url·viewport 는 head 것.
  - `adopt`: 가짜 쇼핑몰을 Replayer 로 팝업(주문 내려받기 창)이 열린 단계까지 재생하고 멈춘 뒤 `Recorder(ctx).adopt(rp.pages)` → 팝업에서 단추 하나 누름 → 기록된 단계의 `page` 가 rp.pages 에서 그 팝업의 번호와 같다; 첫 탭에서 누르면 0.
  - 이어 붙인 기록을 `Replayer` 로 처음부터 재생 → 성공.
- [ ] **Step 2: 실패 확인** — `.venv\Scripts\python.exe tests\test_web_replay.py` → 새 절 FAIL
- [ ] **Step 3: 구현**
- [ ] **Step 4: 통과 확인** — test_web_replay 전부, `tests\test_typed_nav.py`, `tests\test_find_nested_text.py`
- [ ] **Step 5: 커밋** — `재생: 열린 탭에 기록기 붙이기·기록 이어 붙이기 (설계 2026-10-19 4.2절)`

### Task 6: 옵저버 - 파일 불러오기·내보내기, 멈춘 자리부터 [수정]

**Files:**
- Modify: `rpa_observer.py`
- Test: `tests/test_observer_edit.py` (새로, Worker 를 직접 몬다 - Edge 창이 뜬다: 돌리기 전에 사용자에게 알림), `tests/test_presets.py` (불러오기·내보내기 함수)

**Interfaces:**
- Consumes: Task 1 `preset_transfer.export_item/check_file`, Task 5 `Recorder.adopt`, `continue_record`.
- Produces:
  - 화면 단추 (btns 줄, 업무 서식): [파일에서 불러오기], [파일로 내보내기], 미리보기가 멈춰 있을 때만 [수정].
  - `App.import_file()` — `filedialog.askopenfilename(filetypes=[("프리셋 파일", "*.json")])` → `check_file` → 현재 칸(`self.cur`)에 기록이 있으면 `ask("프리셋 {n}의 기록을 이 파일로 바꿉니다. 저장하기 전까지는 파일에 반영되지 않습니다. 진행하시겠습니까?")` → `p.update(name, code, loaded=record(단계마다 id), raw=[], head=None, fresh=True)`; 파일 code 가 칸의 code 와 다르면 `id=""`, `pw=""`, `has_pw=False`, `phone=""`, `senders=""`. 저장은 지금 [저장] 그대로.
  - `App.export_file()` — 칸이 `fresh` 이거나 기록이 없으면 `tell("저장한 뒤 내보내 주십시오.")`; 아니면 `asksaveasfilename(initialfile=f"프리셋_{no}_{name}.json")` 에 `export_item(no)` (with_phone False) 를 UTF-8 로.
  - 미리보기 실패 시: `_do_preview` 가 1.5초 뒤 닫지 않고 `ui.put(("failed_at", i))` 뒤 `self.edit`/`self.cancel` 중 하나가 켜질 때까지 기다린다. 화면은 일시정지와 같은 모양 (`[수정]`, `[■ 중단]`, 상태 글 `"{i}단계에서 멈췄습니다. [수정]으로 이 단계부터 다시 기록하거나 [■ 중단]을 눌러 주십시오."`).
  - 일시정지 중 [수정]: `Worker.edit` (threading.Event) 를 켠다 → `Replayer._hold` 가 `EditHere(i)` 를 던진다 (web_replay 에 `class EditHere(Exception)`, `i` = 아직 안 한 단계, 1부터).
  - `Worker._do_preview` 가 EditHere 나 실패 뒤 edit 를 받으면: 미리보기 ctx·prof 를 `self.ctx`·`self.prof` 로 넘기고(닫지 않음), `LiveRecorder` 를 만들어 `adopt(rp.pages)`, `next_id = max(ids)+1`, `tabs = set(rp.pages)`, `rec_no` = 그 칸, `ui.put(("editing", no, cut_id))` (cut_id = `ids[i-1]`), 이후는 지금 기록과 같다 (`steps` 알림 → [■ 중단] → `_do_stop`). 미리보기 기록(`st.start("observer")`)은 `"stopped"` 로 끝낸다 (사유 `"{i}단계부터 수정합니다."`).
  - 화면의 `editing` 처리: 칸 p 에 `head` = `_final(p)` 에서 cut_id 단계 앞까지(꺼 둔 단계 포함 그대로), `raw = []`, `fresh = True`; `_final(p)` 은 `head` 가 있으면 `rec.continue_record(head, raw, today)`.
  - 새 preset 칸 `"head": None` 을 `new_preset` 에 더한다 (이름 `prefix` 는 메일 시작 문구가 쓰고 있다).
- [ ] **Step 1: 실패하는 시험 쓰기**:
  - `tests/test_observer_edit.py` (가짜 쇼핑몰): Worker 로 4단계 기록을 미리보기 → 2단계 뒤 pause → edit → 기록기로 새 단계 2개(가짜 쇼핑몰 단추) → stop → 화면 메시지 흐름 `paused`→`editing`→`steps`→`recording_stopped`; 칸의 `_final` = 앞 2단계 + 새 2단계; 프로필 폴더가 하나만 생기고 stop 뒤 지워짐. 두 번째 경우: 3단계 대상이 없는 기록 → `failed_at 3` → edit → 앞 2단계 + 새 단계.
  - `tests/test_presets.py`: 파일 불러오기 함수(대화상자 없이 부르는 `load_file_into(p, obj)` 로 나눠 시험) - 다른 code 면 id·pw·phone 비움, 같은 code 면 유지; `export_file` 은 fresh 칸 거절.
- [ ] **Step 2: 실패 확인** — 두 시험 FAIL (사용자에게 Edge 창이 뜬다고 먼저 알림)
- [ ] **Step 3: 구현** (web_replay 의 `EditHere` 포함)
- [ ] **Step 4: 통과 확인** — 두 시험 + `tests\test_presets.py` 전부 + `.venv\Scripts\python.exe rpa_observer.py --check`
- [ ] **Step 5: 커밋** — `옵저버: 파일 불러오기·내보내기, 미리보기 멈춘 자리부터 [수정] (설계 2026-10-19 4.2절)`

### Task 7: 업체 웹 - 자기 PC 끼리 복사·되돌리기

**Files:**
- Modify: `firebase/web/app.js` (`ctx()` 에 `pcs: company?.pcs || {}`), `firebase/web/rpa-settings.js`, `firebase/web/rpa-common.js` (명령 둘을 한꺼번에), `firebase/web/index.html` (필요하면 CSS)
- Test: `firebase/tests/check_web.py`

**Interfaces:**
- Consumes: Task 2 명령 모양·`live.preset_transfer`, Task 3 규칙.
- Produces:
  - 쇼핑몰 프리셋 카드 아래 '프리셋 복사' 카드 (`#copy-card`): 관리자(`c.isAdmin`)이고 업체 PC 가 2대 이상일 때만. 받을 PC 선택(지금 PC 제외, `live.preset_transfer !== 1` 인 PC 는 `(업데이트 필요)` 를 붙이고 고를 수 없음), 기록이 있는 프리셋마다 체크 + 받을 칸 번호(기본 같은 번호), [전부 선택], [복사].
  - 같은 받을 칸이 둘이면 [복사] 를 막고 `"받을 프리셋 번호가 중복되어 있습니다."`.
  - [복사]: tid = 영문 소문자·숫자 20자 (Task 4 와 같은 규칙), `sendPair(c, [ [지금 PC, "export_preset", {tid, nos, with_phone: true}], [받을 PC, "import_preset", {tid, slots}] ], "프리셋 복사")` — rpa-common 에 두 명령을 push 하고 받을 PC 명령만 지켜본다 (결과 toast).
  - 확인 창: `"{받을 PC}의 프리셋 {칸들}을(를) 이 PC의 프리셋으로 변경합니다. 기록이 있으면 덮어쓰며 아이디·비밀번호는 복사되지 않습니다. 진행하시겠습니까?"`
  - 쇼핑몰 프리셋 목록: `has_login` false 인 줄에 이름표 `"아이디·비밀번호 입력 필요"`; `backup` 이면 [되돌리기] (`send("restore_preset", {nos:[no]}, "프리셋 되돌리기")`, 확인 창 `"프리셋 {no}을(를) 이전 기록으로 되돌리시겠습니까?"`).
- [ ] **Step 1: 실패하는 시험 쓰기** (check_web.py 새 절): PC 둘(pc_a 는 `preset_transfer: 1`, pc_b 도 1, pc_c 는 없음)과 live.presets 를 심고 → 카드 보임, pc_c 는 고를 수 없음 → 프리셋 1·2 체크, 2 를 칸 5 로 → [복사] → 명령 둘: pc_a 에 `export_preset {tid, nos:[1,2], with_phone:true}`, pc_b 에 `import_preset {tid, slots:[1,5]}` (같은 tid). 같은 칸 둘 → 막힘 글. 뷰어 계정은 카드 없음. PC 하나뿐인 업체는 카드 없음. `has_login:false` 줄에 `"아이디·비밀번호 입력 필요"`. `backup:true` 줄 [되돌리기] → `restore_preset {nos:[n]}`.
- [ ] **Step 2: 실패 확인** — `firebase emulators:exec --config ../firebase.json --only auth,database,firestore,hosting --project rpa-test-f02e0 "..\..\.venv\Scripts\python.exe check_web.py"` (firebase\tests 에서)
- [ ] **Step 3: 구현**
- [ ] **Step 4: 통과 확인** — check_web 전부
- [ ] **Step 5: 커밋** — `업체 웹: 자기 PC 끼리 프리셋 복사·되돌리기 (설계 2026-10-19 4.3절)`

### 끝나면

- `docs/firebase-architecture.md` 에 전송 자리·명령 셋 한 절 (Task 2·3 커밋에 같이 넣어도 된다).
- `docs/TODO.md` 에서 '총괄이 프리셋 가져오기·다른 PC에 넣어 주기' 줄을 지운다.
- 배포 순서 (사용자가 정할 때): 규칙(database) → 웹(hosting) → PC 버전 빌드·샌드박스·내보내기. 옛 PC 는 `preset_transfer` 를 올리지 않아 업체 웹이 고르지 못한다.
