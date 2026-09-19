# 루틴 RPA 모듈화 구현 계획

> **상태 (2026-09-18):** Task 0~7 구현 완료. 오프라인 시험 `tests/test_routine_modules.py` 104건 + 기존 시험 5개 통과, `dist/ERPia_RPA.exe` 재빌드. 사후 검증(diff 대조 세 관점)에서 나온 blocker 2건(`find_by_text` 가 예외를 삼켜 죽은 핸들을 '메뉴 없음' 으로 오판 / 숨은 로그인 잔재 창 때문에 `attach` 거부)과 must-fix 들을 반영했다. **실제 ERPia 실행 확인은 아직** — 사용자 승인 뒤. `Logistics=N, Output=Y` 는 실측 전이라 실운영 금지.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `run_routine.py` 의 일직선 `main()` 을 다섯 화면 모듈(로그인 / 주문매핑 매출처리 / 물류대기 관리 / 물류관리 / 출력)로 나누고, `ERPIA_AI.txt` 의 `Routine` 섹션(Y/N)으로 모듈을 골라 돌리며, 모듈마다 완료 상태 + 비트마스크 + 진행률을 `status_routine.json` 에 남긴다.

**Architecture:** 한 파일(`run_routine.py`) 안에서 함수 경계만 세운다 — 물리적 파일 분리는 하지 않는다(사용자 결정 A3; `tests/test_stock_hold_sim.py` 가 `rr.ec/rr.time/rr.log` 를 통째로 갈아끼우므로 분리하면 시험이 진짜 `sleep` 을 돈다). 모듈 함수는 `RoutineContext` 하나를 받아 `(result, reason)` 을 돌려주고, `run_modules()` 디스패처가 설정대로 차례로 부른다. 상태 기록은 `rpa_status` 에 모듈 API 4개를 더해 얹는다. 대시보드 화면·설정 UI 는 **별도 계획(Plan B)** 이다.

**Tech Stack:** Python 3.14, pywinauto(uia), 표준 라이브러리. 시험은 브라우저·ERPia 없이 도는 오프라인 가짜 객체.

**Spec:** `C:\Users\20251216-003\.claude\projects\d--AX-RPA\memory\routine-modularization.md` (가능성 검토 결과 + 사용자 결정 3가지 + blocker 2개 + 의존 규칙). 아래 "사양 요약" 에 핵심을 옮겨 두었다.

## 사양 요약 (사용자 결정, 2026-09-18)

- **A1** flag 는 **비트마스크 정수(`module_flags`) 와 모듈별 상태(`modules[].state`) 둘 다**. progress 는 모듈별 `{value, total, pct}`.
- **A2** 모듈 선택 설정은 **`ERPIA_AI.txt` 의 `Routine` 섹션**. 값은 `"Y"`/`"N"` (`cboBS_Auto_YN` 관례). 섹션·키가 없으면 켠 것. 그 밖의 값이면 **돌리지 않고 멈춘다** (사용자: "이것만 잘 지켜지면 돼").
- **A3** 파일을 나누지 않는다. 설정대로 모듈이 실행/미실행되는 것이 핵심 요구.
- **Blocker 1** 출력 모듈을 이 실행에서 물류관리 모듈이 `done` 이 아닌 채로 돌리면, '이미 운송장…' 팝업에서 **'아니오' 를 누르고 `no_target` 으로 끝낸다** (중복 인쇄 금지).
- **Blocker 2** 물류관리 모듈 안에서 `shipping_setup` 은 **항상** 돈다. 모듈 안 단계는 고를 수 없다.

## 검토 반영 (2026-09-18, 세 관점 반박 검토 뒤)

아래는 계획 본문보다 우선한다. 본문의 코드 조각과 다르면 여기를 따른다.

- **비트는 순서가 아니라 명시 상수.** `ROUTINE_MODULES` 를 5열 `(key, cfg_key, label, steps, bit)` 로, `set_modules([(key, label, steps, bit)])`. 시험이 `[1,2,4,8,16]` 을 고정 검사. 새 모듈은 다음 빈 비트를 쓰고 기존 비트는 바꾸지 않는다.
- **`ctx.done` 대신 `ctx.results = {모듈키: 결과}`.** 출력 모듈 규칙: 물류관리가 **이번 실행에서 돌았는데 `done` 이 아니면** 출력하지 않고 `no_target` (화면 이동·버튼 클릭 없음). 물류관리가 설정에서 꺼져 있을 때만 단독 경로(화면 이동 + `prefetch_auto_ids` + `apply_auto_mode` + 정책 `stop`). 정책 `continue` 는 물류관리가 `done` 일 때만.
- **`run_hold_save` 는 원본 L1198-1226 을 글자 그대로** (전체선택 뒤 sleep 없음, 저장 뒤 팝업 3회 루프). 바뀌는 것은 이름·docstring·`no_target` 검사·문자열 반환뿐. DataItem 개수 세기는 `try/except` 로 감싸고 못 세면 예전처럼 진행.
- **`run_logistics_step` 의 `no_target`** 도 `try/except`. 하단이 0건인데 상단에 행이 있으면 경고 로그(자동 저장 안 함).
- **decorate:** `off` 모듈은 `pct=None`. 완료 상태(done/no_target/skipped)면 progress 와 무관하게 100. 그 다음이 progress.pct, 마지막이 단계 비율.
- **history_record 의 modules 는 화이트리스트** `key,label,bit,state,started_at,finished_at,reason` + `progress {value,total,pct}`. `schema 2` = modules/module_flags 키가 있음(빈 목록일 수 있음).
- **`module_done` 도 `m is None` 이면 return** (module_start/module_off 와 같은 계약).
- **`rpa_status.last_problem()`** 추가. `run_modules` 는 failed/stopped 인데 사유가 없으면 이것으로 채워 `module_done` 에 넘긴다.
- **전부 끔이면** `run_modules` 가 루프 앞에서 `("stopped", "켜진 모듈이 없습니다 (Routine 섹션 확인)")`.
- **`load_routine_modules`:** `"Routine": "Y"` 처럼 섹션을 스칼라로 쓰면 `load_settings` 가 LogIn 에 섞어 넣으므로 `LogIn.Routine` 이 있으면 RuntimeError 로 안내.
- **`RoutineContext.attach`:** `except Exception`; refresh 전에 `pl.find_login_window()` 가 있으면 즉시 "로그인 창이 떠 있습니다. Login 모듈을 켜거나 먼저 로그인하세요".
- **`goto_screen_by_icon`:** 기본 30초(예전 주문매핑 진입과 같게). 예외가 3번 연속이면 IsWindow 와 무관하게 `ctx.refresh()`. **예외가 한 번이라도 섞였으면 `absent` 가 아니라 `failed`** (메뉴 없음 오판 방지). `failed` 분기에서 전체 탭 목록 로그.
- **물류대기 탭 확인 실패는 더 이상 물류처리로 폴백하지 않고 중단한다 (의도).** 2026-09-17 성공 실행 경로(아이콘 클릭→탭 확인)는 그대로.
- **failed 인 모듈의 running 단계는 `failed` 로 닫는다** (예전엔 `stopped`). 의도된 개선.
- **`handle_print_popups(app, pid, hwnd, ...)`** 로 `pid` 를 받는다. '아니오' 를 누른 뒤 2초 기다려 `택배사 선택 / ERPia 출력 미리보기 / 인쇄` 최상위 창이 남아 있으면 `win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)` 로 닫고 로그. `stuck` 이면 `module_output` 이 사유를 명시: "출력 팝업을 처리하지 못해 메인 창에 남겨두었습니다. 팝업을 닫은 뒤 다시 실행하세요."
- **Blocker 2 문구 정정:** 물류관리 모듈이 배송을 생성한 경우 `shipping_setup` 은 항상 돈다(생략 불가). 하단 0건이면 저장할 배송장이 없어 모듈 전체가 `no_target`.
- **`main()` 의 설정 읽기는 `except Exception`** (파일 없음·JSON 깨짐도 '중단 + 사유').
- **시험 6절은 아래로 교체** (원안은 평가 순서 때문에 반드시 실패한다):

```python
seen = {}
def fake_goto(ctx):
    seen["goto"] = seen.get("goto", 0) + 1
    return "ok"
rr.goto_logistics_screen = fake_goto
rr.prefetch_auto_ids = lambda win, ids: None
rr.apply_auto_mode = lambda app, hwnd, opt: (seen.update(mode=True) or (False, True))
rr.run_print_step = lambda app, pid, hwnd, options=None, already_printed="continue": seen.update(policy=already_printed) or "done"
rr.status = StatusRec()
ctx = make_ctx(); ctx.options = {}
ctx.results = {"logistics": "done"}; seen.clear()
res = rr.module_output(ctx)
check("물류관리가 방금 done 이면 continue + 화면 이동 없음", res == ("done", None) and seen.get("policy") == "continue" and "goto" not in seen, str((res, seen)))
ctx.results = {}; seen.clear()
res = rr.module_output(ctx)
check("물류관리를 껐으면 화면 이동 + 모드 맞춤 + stop", res[0] == "done" and seen.get("goto") == 1 and seen.get("mode") is True and seen.get("policy") == "stop", str((res, seen)))
ctx.results = {"logistics": "no_target"}; seen.clear()
res = rr.module_output(ctx)
check("물류관리가 돌았는데 done 이 아니면 출력하지 않고 no_target", res[0] == "no_target" and not seen, str((res, seen)))
rr.run_print_step = lambda app, pid, hwnd, options=None, already_printed="continue": "already_printed"
ctx.results = {}; seen.clear()
check("이미 출력이면 no_target", rr.module_output(ctx)[0] == "no_target")
```
- **시험 5절의 가짜 attach** 는 `hwnd` 를 채우고 호출 횟수를 세어 "한 번만 붙는다" 를 검사. all-off 케이스 추가.
- **Task 3·4·5·6 은 한 세션에서 끝낸다.** 그 사이 `run_routine.py` 를 실행·빌드하지 않는다 (`main()` 이 잠시 지워진 이름을 부른다).
- **파일 구조 표 정정:** `fail_exception` 은 `finish("crashed")` 를 거치므로 손대지 않는다. `rpa_dashboard.run_summary` 화이트리스트(모듈을 이력 목록에 싣는 것)와 "설정에서 끔" 단계를 링에서 빼는 것은 Plan B.
- **Task 7 보고에 명시:** Output 단독 실행('이미 출력한 배송장' 팝업의 버튼 구성)은 실측 전이므로 실운영에서 `Logistics=N, Output=Y` 를 켜지 않는다.

## Global Constraints

- **ERPia 를 실제로 조작하는 시험은 이 계획에 없다.** 모든 시험은 오프라인(가짜 객체)이며 `RPA_STATUS_DIR` 을 임시 폴더로 격리한다. 실제 8765 대시보드와 `바탕화면\ERPIA_AI\RPA_STATUS` 를 건드리지 않는다.
- 비밀번호를 로그·채팅에 절대 찍지 않는다 (`login_flow` 반환값은 `status/message/error_log_path` 뿐이라 안전).
- `rpa_status` 의 기록 함수는 **예외를 밖으로 내지 않는다** (`@_safe`). 새 함수도 같은 규칙.
- `time.sleep` 은 시험에서 `rr.time` 교체로 무력화되므로, 새 코드도 `time.sleep(...)` 모듈 별칭으로만 부른다 (`from time import sleep` 금지).
- 파이썬 패치는 Write 도구로 파일을 만들어 실행한다 (heredoc 금지 — 메모리 `bash-heredoc-mangling`).
- 코드 수정 후 `graphify update .` 를 돈다.
- 이 저장소는 git 이 아니다. 시작 전에 `backup\` 에 원본 3개를 복사해 둔다 (Task 0).
- 기존 시험 4개는 그대로 통과해야 한다: `tests\test_stock_hold_sim.py`(25건), `tests\test_popup_rule.py`, `tests\test_sales_popups.py`, `tests\test_mail_find.py`(15건).
- 실행: `D:\AX\RPA\.venv\Scripts\python.exe <시험 파일>` (pytest 없음, 각 파일이 스스로 통과/실패를 찍고 exit code 로 알린다).

---

## 파일 구조

| 파일 | 역할 | 변경 |
|---|---|---|
| `perform_login.py` | ERPIA_AI.txt 읽기 | `ROUTINE_SECTION`, `load_routine_modules()` 추가 |
| `rpa_status.py` | 실행 기록 | 모듈 API(`set_modules/module_start/module_done/module_off/progress`), `history_record`·`finish`·`fail_exception`·`_mark_vanished`·`decorate` 에 모듈 반영, `schema` 2 |
| `run_routine.py` | 루틴 본체 | `ROUTINE_MODULES`, `RoutineContext`, 화면 진입 함수 3개, 모듈 함수 5개, `run_modules()`, `main()` 재작성, `--check` 확장, 헤더 docstring 갱신, `goto_logistics` 삭제, `run_hold_save_and_goto_logistics` → `run_hold_save` |
| `tests/test_routine_modules.py` | 신규 오프라인 시험 | 설정 파싱 / 모듈 상태 API / 화면 진입 / 팝업 정책 / 디스패처 |

---

### Task 0: 백업

**Files:**
- Create: `backup\run_routine_before_modules_20260918.py`, `backup\rpa_status_before_modules_20260918.py`, `backup\perform_login_before_modules_20260918.py`

- [ ] **Step 1: 원본 복사**

Run:
```
Copy-Item D:\AX\RPA\run_routine.py D:\AX\RPA\backup\run_routine_before_modules_20260918.py
Copy-Item D:\AX\RPA\rpa_status.py D:\AX\RPA\backup\rpa_status_before_modules_20260918.py
Copy-Item D:\AX\RPA\perform_login.py D:\AX\RPA\backup\perform_login_before_modules_20260918.py
```
Expected: 세 파일이 `backup\` 에 생김.

- [ ] **Step 2: 기존 시험 기준선 확인**

Run: `.venv\Scripts\python.exe tests\test_stock_hold_sim.py` / `tests\test_popup_rule.py` / `tests\test_sales_popups.py` / `tests\test_mail_find.py`
Expected: 전부 "실패: 없음" 또는 exit 0. (`test_sales_popups.py` 는 `tests\fake_popup_app.py` 를 스스로 띄운다.)

---

### Task 1: 설정 읽기 — `load_routine_modules()`

**Files:**
- Modify: `perform_login.py` (`load_logistic_options()` 바로 아래, L158-160 뒤)
- Test: `tests/test_routine_modules.py` (신규)

**Interfaces:**
- Consumes: `perform_login.load_settings()` (섹션명 → {키: 값}), `perform_login.CRED_FILE`
- Produces: `perform_login.ROUTINE_SECTION = "Routine"`, `perform_login.load_routine_modules(module_keys) -> (selected: dict[str,bool], unknown: list[str])`. 값이 Y/N 이 아니면 `RuntimeError`.

- [ ] **Step 1: 실패하는 시험 작성**

`tests/test_routine_modules.py` 를 만든다. 뒤 Task 들이 같은 파일에 절을 덧붙이므로 `check()`/`fails` 를 공용으로 둔다.

```python
"""루틴 RPA 모듈화 시험 - 설정 파싱 / 모듈 상태 기록 / 화면 진입 / 출력 팝업 정책 / 디스패처.

ERPia 없이 돈다. 상태 기록은 임시 폴더로 격리한다 (RPA_STATUS_DIR).

    .venv\\Scripts\\python.exe tests\\test_routine_modules.py
"""
import os
import sys
import tempfile
import types
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="rpa_modules_")
os.environ["RPA_STATUS_DIR"] = _tmp          # rpa_status 가 import 될 때 이 값을 쓴다
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import perform_login as pl  # noqa: E402

fails = []
_no = [0]


def check(name, cond, detail=""):
    _no[0] += 1
    mark = "통과" if cond else "실패"
    print(f"  {_no[0]:2d}. [{mark}] {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(f"{_no[0]}. {name} {detail}")


KEYS = ["Login", "Sales", "Hold", "Logistics", "Output"]


def with_settings(sections):
    """pl.load_settings 를 가짜로 바꾼다."""
    pl.load_settings = lambda: sections


print("=== 1. Routine 섹션 읽기 ===")
with_settings({"LogIn": {"AdminCode": "x"}})
sel, unknown = pl.load_routine_modules(KEYS)
check("섹션이 없으면 전부 켬", sel == {k: True for k in KEYS} and unknown == [], f"{sel} {unknown}")

with_settings({"Routine": {"Login": "Y", "Sales": "n", "Hold": " N ", "Logistics": "y"}})
sel, unknown = pl.load_routine_modules(KEYS)
check("Y/N 대소문자·공백 무시", sel == {"Login": True, "Sales": False, "Hold": False, "Logistics": True, "Output": True}, f"{sel}")
check("키가 없으면 켬 (Output)", sel["Output"] is True)

with_settings({"Routine": {"Login": "Y", "Extra": "N"}})
sel, unknown = pl.load_routine_modules(KEYS)
check("모르는 키는 unknown 으로 돌려준다", unknown == ["Extra"], f"{unknown}")

for bad in ("yes", "1", "", "예"):
    with_settings({"Routine": {"Hold": bad}})
    try:
        pl.load_routine_modules(KEYS)
        check(f"잘못된 값 {bad!r} 이면 RuntimeError", False, "예외 없음")
    except RuntimeError as e:
        check(f"잘못된 값 {bad!r} 이면 RuntimeError", "Hold" in str(e) and "Y 또는 N" in str(e), str(e))

print()
print(f"실패: {'없음' if not fails else fails}")
sys.exit(1 if fails else 0)
```

- [ ] **Step 2: 실패 확인**

Run: `.venv\Scripts\python.exe tests\test_routine_modules.py`
Expected: `AttributeError: module 'perform_login' has no attribute 'load_routine_modules'`

- [ ] **Step 3: 구현**

`perform_login.py` 의 `load_logistic_options()` 아래에 추가:

```python
ROUTINE_SECTION = "Routine"


def load_routine_modules(module_keys):
    """어떤 모듈을 돌릴지. {설정 키: True/False} 와 모르는 키 목록을 돌려준다.

    ERPIA_AI.txt 의 "Routine" 섹션에 모듈 키마다 "Y"(켬) / "N"(끔) 을 적는다.
    섹션이나 키가 없으면 켠 것으로 본다 (예전 파일 그대로 돌아가게).
    그 밖의 값이면 RuntimeError - 사용자가 고치기 전에는 아무것도 돌리지 않는다.
    (어떤 모듈을 돌릴지는 사용자 설정이 정확히 지켜져야 하는 것이라, 어중간한 값을
     '켬'이나 '끔' 어느 쪽으로도 짐작하지 않는다.)
    """
    section = load_settings().get(ROUTINE_SECTION, {})
    selected = {}
    bad = []
    for key in module_keys:
        raw = section.get(key)
        if raw is None:
            selected[key] = True
            continue
        value = str(raw).strip().upper()
        if value == "Y":
            selected[key] = True
        elif value == "N":
            selected[key] = False
        else:
            bad.append(f"{key}={raw!r}")
    if bad:
        raise RuntimeError(
            f"{CRED_FILE} 의 '{ROUTINE_SECTION}' 섹션 값은 Y 또는 N 이어야 합니다: {', '.join(bad)}")
    unknown = sorted(k for k in section if k not in module_keys)
    return selected, unknown
```

- [ ] **Step 4: 통과 확인**

Run: `.venv\Scripts\python.exe tests\test_routine_modules.py`
Expected: 8건 통과, "실패: 없음".

---

### Task 2: 모듈 상태 기록 API — `rpa_status`

**Files:**
- Modify: `rpa_status.py`
  - `_new_step` 옆에 `_new_module`, `_find_module` (L405 부근)
  - `start()` 의 `_state` 초기값에 `"modules": [], "module_flags": 0, "current_module": None`, `"schema": 2` (L460-481)
  - `step()` 에 현재 모듈 progress 초기화 (L510-533)
  - `set_steps` 아래에 `set_modules / module_start / module_done / module_off / progress` (L507 뒤)
  - `finish()` 에서 running 모듈 닫기 (L616-634)
  - `history_record()` 에 `modules`, `module_flags`, `schema: 2` (L307-327)
  - `_mark_vanished()` 에서 running 모듈 failed (L672-689)
  - `decorate()` 에 모듈별 `steps_done/steps_total/pct/duration_sec` (L692-725)
- Test: `tests/test_routine_modules.py` 에 절 추가

**Interfaces:**
- Produces:
  - `set_modules(modules)` — `[(key, label, step_keys), ...]`. 순서대로 비트 배정 (첫 모듈=1, 둘째=2, 셋째=4 …).
  - `module_start(key)`, `module_done(key, result, reason=None)` — `result ∈ {"done","no_target","skipped","failed","stopped"}`. `done/no_target/skipped` 만 `module_flags` 비트를 세운다. 지금 running 인 단계도 같이 닫는다.
  - `module_off(key, reason=None)` — 설정에서 끔. 상태 `"off"`, 비트 0.
  - `progress(value, total, note=None)` — 현재 모듈의 `progress = {value,total,pct,note,updated_at}`.
  - `_state["modules"][i] = {"key","label","bit","steps","state","started_at","finished_at","reason","progress"}`
  - `decorate(view)["modules"][i]` 에 `steps_done, steps_total, pct, duration_sec` 추가.

- [ ] **Step 1: 실패하는 시험 추가**

`tests/test_routine_modules.py` 의 `print()` / `실패:` 줄 **앞**에 추가:

```python
import rpa_status as st  # noqa: E402

print()
print("=== 2. 모듈 상태 기록 (rpa_status) ===")
MODS = [("login", "로그인", ("login",)),
        ("sales", "매출", ("order_screen", "sales")),
        ("hold", "물류대기", ("hold_screen", "hold_save"))]
st.start("routine", [("login", "로그인"), ("order_screen", "화면"), ("sales", "정상매출"),
                     ("hold_screen", "이동"), ("hold_save", "저장")])
st.set_modules(MODS)
s = st._state
check("모듈 3개 등록, 비트 1/2/4", [m["bit"] for m in s["modules"]] == [1, 2, 4], str([m["bit"] for m in s["modules"]]))
check("처음엔 module_flags 0", s["module_flags"] == 0)
check("schema 2", s["schema"] == 2)

st.module_start("login"); st.step("login"); st.module_done("login", "done")
check("login done -> 비트 1", s["module_flags"] == 1, str(s["module_flags"]))
check("login 단계도 done 으로 닫힘", st._find_step("login")["state"] == "done")

st.module_start("sales"); st.step("order_screen"); st.progress(2, 5, "2/5")
check("progress pct 40", s["modules"][1]["progress"]["pct"] == 40, str(s["modules"][1]["progress"]))
st.step("sales")
check("다음 step() 이면 progress 초기화", s["modules"][1]["progress"] is None)
st.module_done("sales", "no_target", "대상 없음")
check("no_target 도 완료 비트 (1|2=3)", s["module_flags"] == 3, str(s["module_flags"]))
check("사유 저장", s["modules"][1]["reason"] == "대상 없음")

st.module_off("hold", "설정에서 끔")
check("off 는 비트 안 세움", s["module_flags"] == 3 and s["modules"][2]["state"] == "off")

rec = st.history_record(s)
check("이력에 modules/module_flags/schema2", rec.get("module_flags") == 3 and len(rec.get("modules") or []) == 3 and rec["schema"] == 2)

view = st.decorate(s)
m1 = view["modules"][1]
check("decorate: 모듈별 steps_done/total", m1["steps_total"] == 2 and m1["steps_done"] == 2, str(m1))

# failed 는 비트를 안 세우고 running 단계를 failed 로 닫는다
st.start("routine", [("login", "로그인"), ("hold_save", "저장")])
st.set_modules(MODS)
st.module_start("hold"); st.step("hold_save"); st.module_done("hold", "failed", "그리드 없음")
check("failed 는 비트 0", st._state["module_flags"] == 0)
check("failed 면 running 단계가 failed", st._find_step("hold_save")["state"] == "failed")

# finish 가 running 모듈을 닫는다
st.start("routine", [("login", "로그인")])
st.set_modules(MODS)
st.module_start("login")
st.finish("crashed", "예외")
check("finish(crashed) 가 running 모듈을 failed 로", st._state["modules"][0]["state"] == "failed")
```

- [ ] **Step 2: 실패 확인**

Run: `.venv\Scripts\python.exe tests\test_routine_modules.py`
Expected: `AttributeError: module 'rpa_status' has no attribute 'set_modules'`

- [ ] **Step 3: 구현 — 헬퍼와 상태 초기값**

`rpa_status.py` L405 `_new_step` 아래에:

```python
def _new_module(key, label, bit, steps):
    return {"key": str(key), "label": str(label), "bit": int(bit), "steps": [str(s) for s in steps],
            "state": "pending", "started_at": None, "finished_at": None, "reason": None, "progress": None}


def _find_module(key):
    if _state is None or key is None:
        return None
    return next((m for m in _state.get("modules") or [] if m["key"] == key), None)
```

`start()` 의 `_state = {` 에서 `"schema": 1,` → `"schema": 2,` 로, 그리고 `"metrics": [],` 다음에:

```python
            "modules": [],
            "module_flags": 0,
            "current_module": None,
```

- [ ] **Step 4: 구현 — 모듈 API**

`set_steps` 아래에 추가:

```python
# ---------------------------------------------------------------------------
# 모듈 (화면 단위 묶음). 단계(step)보다 큰 단위로 '어디까지 끝났는지'를 남긴다.
#   modules[].state : pending / running / done / no_target / skipped / failed / stopped / off
#   module_flags    : 끝난 모듈의 비트를 OR 한 정수. 첫 모듈=1, 둘째=2, 셋째=4 ...
#                     done·no_target·skipped 만 센다 (그 모듈은 더 할 일이 없다는 뜻).
#                     failed·stopped·off 는 세지 않는다.
#   progress        : 지금 도는 모듈 안의 진행 {value, total, pct} (건수가 있는 작업만)
# ---------------------------------------------------------------------------
MODULE_RESULTS = ("done", "no_target", "skipped", "failed", "stopped")
_MODULE_COMPLETE = ("done", "no_target", "skipped")
_MODULE_STEP_END = {"done": "done", "no_target": "done", "skipped": "skipped",
                    "failed": "failed", "stopped": "stopped"}


@_safe
def set_modules(modules):
    """모듈 목록 [(key, label, step_keys), ...]. 순서대로 비트를 배정한다."""
    with _lock:
        if not _active():
            return
        _state["modules"] = [_new_module(k, l, 1 << i, steps) for i, (k, l, steps) in enumerate(modules or ())]
        _state["module_flags"] = 0
        _state["current_module"] = None
        _touch_locked(immediate=True)


@_safe
def module_start(key):
    with _lock:
        if not _active():
            return
        m = _find_module(key)
        if m is None:
            return
        m.update(state="running", started_at=now_iso(), finished_at=None, reason=None, progress=None)
        _state["current_module"] = key
        _touch_locked(immediate=True)


@_safe
def module_done(key, result, reason=None):
    """모듈을 닫는다. 지금 running 인 단계도 같은 결과로 닫는다.

    모듈의 마지막 단계는 다음 step() 이 불릴 때까지 running 으로 남기 때문에,
    여기서 닫지 않으면 '모듈은 끝났는데 단계는 진행 중' 인 상태가 된다.
    """
    with _lock:
        if not _active():
            return
        if result not in MODULE_RESULTS:
            result = "failed"
        now = now_iso()
        m = _find_module(key)
        if m is not None:
            m.update(state=result, finished_at=now, reason=reason)
            if result in _MODULE_COMPLETE:
                _state["module_flags"] = int(_state.get("module_flags") or 0) | int(m["bit"])
        end = _MODULE_STEP_END[result]
        for s in _state["steps"]:
            if s["state"] == "running":
                s["state"] = end
                s["finished_at"] = now
                if reason and end != "done":
                    s["note"] = reason
        if _state.get("current_module") == key:
            _state["current_module"] = None
        _touch_locked(immediate=True)


@_safe
def module_off(key, reason=None):
    """설정에서 꺼서 돌리지 않는 모듈. 비트는 세우지 않는다."""
    with _lock:
        if not _active():
            return
        m = _find_module(key)
        if m is None:
            return
        m.update(state="off", reason=reason, progress=None)
        _touch_locked(immediate=True)


@_safe
def progress(value, total, note=None):
    """지금 도는 모듈 안에서 얼마나 진행됐는지 (예: 재고검토 3/10)."""
    with _lock:
        if not _active():
            return
        m = _find_module(_state.get("current_module"))
        if m is None:
            return
        try:
            pct = int(round(100.0 * float(value) / float(total))) if total else None
        except (TypeError, ValueError, ZeroDivisionError):
            pct = None
        m["progress"] = {"value": value, "total": total, "pct": pct, "note": note, "updated_at": now_iso()}
        _touch_locked()
```

`step()` 안, `target.update(state="running", ...)` 바로 뒤에 (L530 부근):

```python
        cur = _find_module(_state.get("current_module"))
        if cur is not None:
            cur["progress"] = None   # 단계가 바뀌면 이전 단계의 진행률은 뜻이 없다
```

- [ ] **Step 5: 구현 — finish / history / vanished / decorate**

`finish()` 의 `for s in _state["steps"]:` 루프 **앞**에:

```python
        mod_end = {"success": "done", "stopped": "stopped", "crashed": "failed"}[result]
        for m in _state.get("modules") or []:
            if m["state"] == "running":
                m["state"] = mod_end
                m["finished_at"] = now
                if reason and mod_end != "done":
                    m["reason"] = reason
        _state["current_module"] = None
```

`history_record()`: `"schema": 1,` → `"schema": 2,`, 그리고 `"metrics": ...` 줄 다음에:

```python
        "modules": state.get("modules") or [],
        "module_flags": int(state.get("module_flags") or 0),
```

`_mark_vanished()` 의 `for s in cur.get("steps") or []:` 루프 뒤에:

```python
        for m in cur.get("modules") or []:
            if m.get("state") == "running":
                m["state"] = "failed"
                m["finished_at"] = end
                m["reason"] = m.get("reason") or "여기서 멈췄습니다"
```

`decorate()` 의 `view["metrics"] = metrics` 뒤에:

```python
    # 모듈별로 '몇 단계 중 몇 단계가 끝났는지' 와 퍼센트를 붙인다.
    # 건수 진행(progress.pct)이 있으면 그것을, 없으면 단계 수로 계산한다.
    stepstate = {s.get("key"): s.get("state") for s in steps}
    modules = []
    for m in state.get("modules") or []:
        mm = dict(m)
        keys = m.get("steps") or []
        done = sum(1 for k in keys if stepstate.get(k) in ("done", "skipped"))
        mm["steps_total"] = len(keys)
        mm["steps_done"] = done
        p = m.get("progress") or {}
        if p.get("pct") is not None:
            mm["pct"] = p["pct"]
        elif m.get("state") in ("done", "no_target", "skipped"):
            mm["pct"] = 100
        else:
            mm["pct"] = int(round(100.0 * done / len(keys))) if keys else 0
        a = parse_iso(m.get("started_at"))
        b = parse_iso(m.get("finished_at"))
        mm["duration_sec"] = _seconds(a, b or (now if m.get("state") == "running" else None))
        modules.append(mm)
    view["modules"] = modules
```

- [ ] **Step 6: 통과 확인**

Run: `.venv\Scripts\python.exe tests\test_routine_modules.py`
Expected: 1·2절 모두 통과, "실패: 없음".

- [ ] **Step 7: 대시보드 회귀 확인**

Run: `.venv\Scripts\python.exe tests\test_dashboard_auth.py`
Expected: 기존과 같이 통과 (새 키는 화면이 무시한다).

---

### Task 3: 화면 진입 함수와 `RoutineContext`

**Files:**
- Modify: `run_routine.py`
  - `ROUTINE_STEPS` (L173-188) 에 `("logistics_screen", "물류 관리 화면 이동")` 을 `("logistics", "배송 생성")` 앞에 삽입, 그 아래에 `ROUTINE_MODULES` 추가
  - `wait_for_active_main_tab` (L319-345) 에 `ctx=None` 인자
  - `goto_logistics` (L347-394) 삭제 → `goto_screen_by_icon / goto_hold_screen / goto_logistics_screen` 으로 대체
  - `RoutineContext` 클래스는 `acquire_main_window` 뒤(L299 부근)에
- Test: `tests/test_routine_modules.py` 에 절 추가

**Interfaces:**
- Produces:
  - `ROUTINE_MODULES = ((key, cfg_key, label, step_keys), ...)` 5개.
  - `class RoutineContext` — 속성 `pid, hwnd, app, win, options, done(set)`; 메서드 `refresh() -> bool`, `attach() -> (ok, reason)`, `window() -> win`, `logistic_options() -> dict`.
  - `goto_screen_by_icon(ctx, key, label, tab_keyword, wait_seconds=15) -> "ok" | "absent" | "failed"`
  - `goto_hold_screen(ctx)`, `goto_logistics_screen(ctx)` — 같은 반환.
  - `wait_for_active_main_tab(app, hwnd, keyword, timeout=20, interval=1.0, ctx=None)` — 창을 다시 잡으면 `ctx.hwnd/app` 도 갱신.

- [ ] **Step 1: 실패하는 시험 추가**

`tests/test_routine_modules.py` 의 `실패:` 줄 앞에:

```python
import run_routine as rr  # noqa: E402

print()
print("=== 3. 화면 진입 (goto_screen_by_icon) ===")
rr.time = types.SimpleNamespace(sleep=lambda *_: None, time=__import__("time").time, strftime=__import__("time").strftime)
rr.ec = types.SimpleNamespace(ensure_foreground=lambda *a, **k: True, find_erpia_pid=lambda: 4242)
rr.log = lambda msg="": None


class FakeEl:
    def __init__(self):
        self.clicked = 0

    def rectangle(self):
        return "rect"

    def click_input(self):
        self.clicked += 1


def make_ctx():
    ctx = rr.RoutineContext()
    ctx.pid, ctx.hwnd = 4242, 777
    ctx.app = types.SimpleNamespace(window=lambda handle: "win")
    return ctx


check("ROUTINE_MODULES 는 5개", [m[0] for m in rr.ROUTINE_MODULES] == ["login", "sales", "hold", "logistics", "output"])
check("logistics_screen 단계가 logistics 앞에", [k for k, _ in rr.ROUTINE_STEPS].index("logistics_screen") + 1 == [k for k, _ in rr.ROUTINE_STEPS].index("logistics"))
check("모듈 단계 키가 전부 ROUTINE_STEPS 에 있다", all(k in dict(rr.ROUTINE_STEPS) for m in rr.ROUTINE_MODULES for k in m[3]))

rr.find_by_text = lambda win, key, control_types=(): None
check("아이콘 없음 -> absent", rr.goto_screen_by_icon(make_ctx(), "lcg_X", "엑스", "엑스", wait_seconds=2) == "absent")

el = FakeEl()
rr.find_by_text = lambda win, key, control_types=(): el
rr.wait_for_active_main_tab = lambda app, hwnd, kw, timeout=20, interval=1.0, ctx=None: (True, "엑스 관리")
check("아이콘 클릭 + 탭 확인 -> ok", rr.goto_screen_by_icon(make_ctx(), "lcg_X", "엑스", "엑스") == "ok" and el.clicked == 1)

rr.wait_for_active_main_tab = lambda app, hwnd, kw, timeout=20, interval=1.0, ctx=None: (False, "다른탭")
check("클릭했지만 진입 확인 실패 -> failed", rr.goto_screen_by_icon(make_ctx(), "lcg_X", "엑스", "엑스") == "failed")

check("goto_hold_screen 은 lcg_HoldLogistics", "lcg_HoldLogistics" in rr.goto_hold_screen.__doc__)
check("goto_logistics_screen 은 lcg_Logistics", "lcg_Logistics" in rr.goto_logistics_screen.__doc__)
check("goto_logistics(폴백형) 는 없어졌다", not hasattr(rr, "goto_logistics"))

ctx = make_ctx()
rr.acquire_main_window = lambda pid, tries=12: (None, None, None)
ok, reason = ctx.attach()
check("attach: 메인 창 못 잡으면 (False, 사유)", ok is False and "메인 화면" in reason, str(reason))
rr.acquire_main_window = lambda pid, tries=12: (999, "app", "win")
ok, reason = ctx.attach()
check("attach: 성공하면 hwnd 갱신", ok is True and ctx.hwnd == 999 and ctx.pid == 4242)
rr.ec.find_erpia_pid = lambda: (_ for _ in ()).throw(RuntimeError("없음"))
ok, reason = ctx.attach()
check("attach: ERPia 미실행이면 로그인 모듈 안내", ok is False and "로그인 모듈" in reason, str(reason))
```

- [ ] **Step 2: 실패 확인**

Run: `.venv\Scripts\python.exe tests\test_routine_modules.py`
Expected: `AttributeError: module 'run_routine' has no attribute 'RoutineContext'` (또는 ROUTINE_MODULES).

- [ ] **Step 3: 구현 — 단계·모듈 표**

`ROUTINE_STEPS` 에서 `("logistics", "배송 생성"),` 앞에 `("logistics_screen", "물류 관리 화면 이동"),` 를 넣고, 튜플 닫힌 뒤에:

```python
# 화면 단위 모듈. 설정(ERPIA_AI.txt 의 "Routine" 섹션)으로 골라 돌린다.
# (모듈 키, 설정 키, 화면 이름, 이 모듈이 맡는 ROUTINE_STEPS 키들)
# 순서가 곧 실행 순서이자 module_flags 의 비트 순서다 (login=1, sales=2, hold=4, logistics=8, output=16).
# 모듈 안의 단계는 고를 수 없다 - 특히 물류관리의 배송정보설정(shipping_setup)은 로그인 세션마다
# 초기화되므로 저장 앞에서 항상 돌아야 한다.
ROUTINE_MODULES = (
    ("login",     "Login",     "로그인",              ("login",)),
    ("sales",     "Sales",     "주문매핑 매출처리",     ("order_screen", "top_select", "excel_upload", "bottom_select", "sales")),
    ("hold",      "Hold",      "물류대기 관리",         ("hold_screen", "stock_review", "abnormal_hold", "hold_save")),
    ("logistics", "Logistics", "물류관리",             ("logistics_screen", "logistics", "shipping_setup", "logistics_save")),
    ("output",    "Output",    "운송장 출력 / 엑셀 생성", ("output",)),
)
# 모듈 함수가 돌려주는 결과와 화면에 쓸 이름
MODULE_RESULT_LABEL = {"done": "완료", "no_target": "대상 없음", "skipped": "건너뜀",
                       "failed": "실패", "stopped": "중단"}
```

- [ ] **Step 4: 구현 — `RoutineContext`**

`acquire_main_window()` 정의 바로 뒤(`def wait_login_or_main` 앞)에:

```python
class RoutineContext:
    """모듈 사이를 오가는 것들.

    hwnd/app/win 은 ERPia 가 메인 창을 다시 만들면(2차 인증 경로) 무효가 되므로
    한 곳에서 들고 refresh() 로 다시 잡는다. 모듈 함수는 이 객체 하나만 받는다.
    """

    def __init__(self):
        self.pid = None
        self.hwnd = None
        self.app = None
        self.win = None
        self.options = None      # 물류 설정 (ERPIA_AI.txt Logistic). 처음 필요할 때 읽는다.
        self.done = set()        # 이번 실행에서 'done' 으로 끝난 모듈 키

    def refresh(self):
        """메인 창을 다시 잡는다. 못 잡으면 False."""
        self.hwnd, self.app, self.win = acquire_main_window(self.pid)
        return self.hwnd is not None

    def attach(self):
        """로그인 모듈 없이 시작할 때: 이미 떠 있는 ERPia 에 붙는다. (ok, 사유)"""
        try:
            self.pid = ec.find_erpia_pid()
        except RuntimeError:
            return False, "ERPia 가 실행되어 있지 않습니다. 로그인 모듈을 켜거나 ERPia 를 먼저 띄우세요."
        if not self.refresh():
            return False, "메인 화면을 잡지 못했습니다 (로그인 전이거나 팝업이 떠 있을 수 있습니다)."
        return True, None

    def window(self):
        """값싼 wrapper 를 매번 새로 만든다 (오래 들고 있으면 stale 이 된다)."""
        self.win = self.app.window(handle=self.hwnd)
        return self.win

    def logistic_options(self):
        if self.options is None:
            self.options = pl.load_logistic_options()
        return self.options
```

- [ ] **Step 5: 구현 — `wait_for_active_main_tab` 에 ctx**

시그니처를 `def wait_for_active_main_tab(app, hwnd, keyword, timeout=20, interval=1.0, ctx=None):` 로 바꾸고, `hwnd, app = new_hwnd, new_app` 바로 뒤에:

```python
                if ctx is not None:
                    ctx.hwnd, ctx.app = new_hwnd, new_app   # 호출자도 새 창을 쓰게 한다
```

- [ ] **Step 6: 구현 — `goto_logistics` 를 세 함수로**

`goto_logistics` 함수(L347-394) 전체를 지우고 그 자리에:

```python
def goto_screen_by_icon(ctx, key, label, tab_keyword, wait_seconds=15):
    """좌측 아이콘(key)을 눌러 활성 메인탭에 tab_keyword 가 뜨는지 확인한다.

    반환: "ok" | "absent"(아이콘 자체가 없음 - 업체에 그 메뉴가 없다) | "failed"(눌렀지만 진입 확인 실패)
    'absent' 와 'failed' 를 구분하는 이유: 앞의 것은 모듈을 건너뛰어도 되지만 뒤의 것은 실패다.
    """
    target = None
    waited = 0.0
    while waited < wait_seconds:
        try:
            target = find_by_text(ctx.window(), key, control_types=("Pane",))
        except Exception as e:
            # 화면 전환 중 UIA 가 잠시 COMError 를 내면 '아직 없음'으로 보고 다시 시도한다.
            log(f"  '{label}' 아이콘 조회 실패(잠시 뒤 재시도): {type(e).__name__}")
            target = None
            if not win32gui.IsWindow(ctx.hwnd):
                # 창 자체가 다시 만들어졌다 (로그인 직후에 이런 일이 있다)
                log("  메인 창 핸들이 무효가 됐습니다 -> 메인 창을 다시 잡습니다")
                if not ctx.refresh():
                    return "failed"
                log(f"  메인 창 다시 확보: hwnd={ctx.hwnd}")
        if target is not None:
            break
        time.sleep(1.0)
        waited += 1.0

    if target is None:
        log(f"'{label}'({key}) 아이콘을 찾지 못했습니다.")
        return "absent"

    log(f"'{label}'({key}) 아이콘 클릭: rect={target.rectangle()}")
    ec.ensure_foreground(ctx.hwnd)
    target.click_input()

    # 탭이 미리 열려 있을 수 있으므로 '존재'가 아니라 '활성 탭'으로 확인한다.
    ok, active = wait_for_active_main_tab(ctx.app, ctx.hwnd, tab_keyword, ctx=ctx)
    if ok:
        log(f"'{label}' 화면 이동 확인됨 (활성 메인탭='{active}')")
        return "ok"
    log(f"'{label}' 클릭했으나 진입 확인 실패 (활성 메인탭='{active}')")
    return "failed"


def goto_hold_screen(ctx):
    """좌측 '물류대기'(lcg_HoldLogistics) 아이콘 -> '물류대기 관리' 탭."""
    return goto_screen_by_icon(ctx, "lcg_HoldLogistics", "물류대기", "물류대기")


def goto_logistics_screen(ctx):
    """좌측 '물류처리'(lcg_Logistics) 아이콘 -> '물류 관리' 탭. (아이콘 이름과 탭 이름이 다르다)"""
    return goto_screen_by_icon(ctx, "lcg_Logistics", "물류처리", "물류 관리")
```

- [ ] **Step 7: 통과 확인**

Run: `.venv\Scripts\python.exe tests\test_routine_modules.py`
Expected: 3절까지 통과. (`main()` 은 아직 `goto_logistics` 를 부르지만 import 시점엔 문제 없다 — Task 6 에서 지운다.)

---

### Task 4: 물류대기 저장과 화면 이동 분리, '대상 없음' 판정

**Files:**
- Modify: `run_routine.py`
  - `run_hold_save_and_goto_logistics` (L1189-1260) → `run_hold_save(app, pid, hwnd) -> "done" | "no_target" | "failed"`
  - `run_hold_logistics_step` (L4394-4501) → 반환 `"done" | "no_target" | "failed"`
  - `run_logistics_step` (L1376-1452) → 반환 `"done" | "no_target" | "failed"`

**Interfaces:**
- Consumes: `select_all_by_header_checkbox`, `click_toolbar_button`, `wait_async_then_confirm`, `find_popup_ok_button`, `get_onscreen_tables`
- Produces: 위 세 함수의 문자열 반환 계약. 호출자는 Task 6 의 모듈 함수뿐.

- [ ] **Step 1: `run_hold_save`**

`def run_hold_save_and_goto_logistics(app, pid, hwnd):` 부터 그 함수 끝(`return ok`)까지를 아래로 교체:

```python
def run_hold_save(app, pid, hwnd):
    """물류대기 관리 마무리: 그리드 전체선택 -> 저장(S) -> 비동기 대기 -> 팝업 처리.

    예전에는 여기서 곧바로 '물류처리' 아이콘까지 눌러 '물류 관리' 로 넘어갔다.
    모듈로 나누면서 화면 이동은 물류관리 모듈의 진입(goto_logistics_screen)으로 옮겼다.
    반환: "done" | "no_target"(그리드에 행이 없어 저장할 것이 없음) | "failed"
    """
    win = app.window(handle=hwnd)
    tables = get_onscreen_tables(win)
    if not tables:
        log("그리드를 찾지 못했습니다. 중단합니다.")
        return "failed"
    grid = max(tables, key=lambda t: t.rectangle().width() * t.rectangle().height())

    # 행이 하나도 없으면 전체선택 자체가 실패로 읽히므로 먼저 가려낸다.
    # (앞 모듈 없이 이 모듈만 돌릴 때 흔한 상황 - 실패가 아니라 '할 게 없음'이다)
    if not grid.descendants(control_type="DataItem"):
        log("물류대기 그리드에 행이 없습니다 -> 저장할 것이 없습니다.")
        return "no_target"

    log("그리드 전체선택 (헤더 체크박스)")
    if not select_all_by_header_checkbox(hwnd, grid):
        log("전체선택에 실패했습니다. 중단합니다.")
        return "failed"
    time.sleep(1.0)

    baseline_children = visible_child_windows(hwnd)
    log("'저장(S)' 클릭")
    win = app.window(handle=hwnd)
    if not click_toolbar_button(win, hwnd, "저장(S)"):
        return "failed"
    time.sleep(1.5)

    log("비동기 처리 대기 및 팝업 처리")
    probe_spinner(hwnd, baseline_children)
    result = wait_async_then_confirm(app, hwnd, baseline_children)
    log(f"  비동기 대기 결과: {result}")

    # 연속 팝업이 더 있으면 한 번 더
    time.sleep(1.5)
    win = app.window(handle=hwnd)
    btn = find_popup_ok_button(win)
    if btn is not None:
        log(f"  추가 팝업 -> '{btn.window_text()}' 클릭")
        ec.ensure_foreground(hwnd)
        btn.click_input()
    return "done"
```

> 주의: 위 본문 중 전체선택~저장~팝업 부분은 **기존 L1198-1226 의 코드를 그대로** 옮긴다. 이 계획의 코드는 그 구간의 실제 줄(`log("그리드 전체선택 (헤더 체크박스)")` … `btn.click_input()`)을 읽어 맞춘다. 바뀌는 것은 (1) 함수 이름·docstring, (2) `no_target` 검사 추가, (3) L1228 이후(물류처리 클릭~`return ok`) 삭제, (4) `return True/False` → 문자열.

- [ ] **Step 2: `run_hold_logistics_step` 반환 계약**

함수 안의 `return False` 두 곳(`'조회(F)' 버튼을 찾지 못했습니다`, `그리드를 찾지 못했습니다`)을 `return "failed"` 로, 마지막 줄을:

```python
    # 후반 처리: 전체선택 -> 저장 -> 비동기 대기 (배송보류 여부와 무관하게 항상 실행)
    status.step("hold_save")
    log("\n=== 물류대기: 전체선택 -> 저장 ===")
    return run_hold_save(app, pid, hwnd)
```

docstring 첫 줄 아래에 `반환: "done" | "no_target" | "failed"` 를 덧붙인다.

- [ ] **Step 3: `run_logistics_step` 반환 계약과 '대상 없음'**

- `return False` 다섯 곳(`모드 설정 실패`, `그리드 2개 필요`, `'전체선택'` 실패, `'개별 배송(B)'` 실패, `DataItem 0개`) → `return "failed"`
- `return True` → `return "done"`
- `wait_grid_spinner_gone(hwnd, bottom_grid, LOGISTICS_BOTTOM_IDLE_OVERLAYS, label="하단")` 바로 뒤에:

```python
    if not bottom_grid.descendants(control_type="DataItem"):
        log("하단 그리드에 배송 대상이 없습니다 -> 할 것이 없습니다.")
        return "no_target"
```

- docstring 에 `반환: "done" | "no_target" | "failed"` 추가.

- [ ] **Step 4: 구문 검사**

Run: `.venv\Scripts\python.exe -c "import ast;ast.parse(open(r'D:\AX\RPA\run_routine.py',encoding='utf-8').read());print('ok')"`
Expected: `ok`

- [ ] **Step 5: 기존 시험 회귀**

Run: `.venv\Scripts\python.exe tests\test_stock_hold_sim.py`
Expected: 25건 통과 (이 시험은 저장 함수를 부르지 않는다).

---

### Task 5: 출력 팝업 정책 — 중복 인쇄 방지 (Blocker 1)

**Files:**
- Modify: `run_routine.py`
  - `handle_print_popups` (L3840-3892) → `print_popup_decision()` 분리 + `already_printed` 인자
  - `run_print_step` (L4284-4335) → `already_printed="continue"` 인자, 반환 `"done" | "already_printed" | "failed"`
- Test: `tests/test_routine_modules.py` 절 추가

**Interfaces:**
- Produces:
  - `print_popup_decision(text, button_texts, already_printed="continue") -> (action, button_text)`; `action ∈ {"abort","continue","already_printed","stuck"}`
  - `handle_print_popups(app, hwnd, rounds=3, wait=2.0, already_printed="continue") -> "none" | "continued" | "abort" | "already_printed"`
  - `run_print_step(app, pid, hwnd, options=None, already_printed="continue") -> "done" | "already_printed" | "failed"`

- [ ] **Step 1: 실패하는 시험 추가**

```python
print()
print("=== 4. 출력 팝업 정책 (중복 인쇄 방지) ===")
ALREADY = "이미 운송장(으)로 생성(출력)한 배송장이 3건 있습니다. 계속하시겠습니까?"
YN = ["예(Y)", "아니오(N)"]
check("주소정제 실패 -> abort + 확인", rr.print_popup_decision("주소정제추출 실패가 1건 존재합니다", ["확인"]) == ("abort", "확인"))
check("일반 팝업 -> continue + 예", rr.print_popup_decision("계속하시겠습니까?", YN) == ("continue", "예(Y)"))
check("이미 출력 + continue 정책 -> 예", rr.print_popup_decision(ALREADY, YN, "continue") == ("continue", "예(Y)"))
check("이미 출력 + stop 정책 -> 아니오", rr.print_popup_decision(ALREADY, YN, "stop") == ("already_printed", "아니오(N)"))
check("이미 출력 + stop 인데 아니오 없음 -> stuck (아무것도 안 누름)", rr.print_popup_decision(ALREADY, ["확인"], "stop") == ("stuck", None))
check("버튼을 모르면 stuck", rr.print_popup_decision("???", ["닫기"]) == ("stuck", None))
```

- [ ] **Step 2: 실패 확인**

Run: `.venv\Scripts\python.exe tests\test_routine_modules.py`
Expected: `AttributeError: ... 'print_popup_decision'`

- [ ] **Step 3: 구현 — 결정 함수와 `handle_print_popups`**

`handle_print_popups` 정의 **앞**에:

```python
def print_popup_decision(text, button_texts, already_printed="continue"):
    """출력 중 팝업에서 무엇을 누를지 정한다 (UIA 없이 판단만 - 시험하기 위해 떼어냈다).

    already_printed: '이미 운송장(으)로 생성(출력)한 배송장이…' 팝업 정책
      "continue" - 예를 눌러 계속 (방금 저장한 배송장 중 일부가 이미 출력된 정상 흐름)
      "stop"     - 아니오를 누르고 멈춤 (물류관리 모듈 없이 출력 모듈만 돌 때: 전부 이미 출력된
                   상태라 예를 누르면 프린터로 같은 운송장이 다시 나간다)
    반환: (동작, 누를 버튼 글자)  동작 = "abort" | "continue" | "already_printed" | "stuck"
    """
    def pick(candidates):
        return next((b for b in button_texts if b in candidates), None)

    if any(k in text for k in PRINT_ABORT_KEYWORDS):
        return "abort", pick(OK_BUTTON_TEXTS)
    if ALREADY_PRINTED_KEYWORD in text and already_printed == "stop":
        no_btn = pick(NO_BUTTON_TEXTS)
        return ("already_printed", no_btn) if no_btn else ("stuck", None)
    btn = pick(YES_BUTTON_TEXTS) or pick(OK_BUTTON_TEXTS)
    return ("continue", btn) if btn else ("stuck", None)
```

`handle_print_popups` 를 아래로 교체:

```python
def handle_print_popups(app, hwnd, rounds=3, wait=2.0, already_printed="continue"):
    """출력 도중 뜨는 팝업을 처리한다.

    - PRINT_ABORT_KEYWORDS 팝업('주소정제추출 실패…'): 확인을 눌러 닫고 'abort'
    - '이미 운송장(으)로 생성(출력)한 배송장이…': already_printed 정책대로
        "continue" -> 예를 눌러 계속 ('continued')
        "stop"     -> 아니오를 눌러 멈춤 ('already_printed'). 아니오가 없으면 아무것도 누르지 않고 'abort'
    - 그 외 팝업: 예(없으면 확인)를 눌러 계속
    - 팝업이 없으면 'none'

    반환: 'none' | 'continued' | 'abort' | 'already_printed'
    """
    status_ = "none"
    for _ in range(rounds):
        time.sleep(wait)
        win = app.window(handle=hwnd)
        buttons = find_popup_buttons(win)
        if not buttons:
            return status_
        text = collect_popup_text(buttons[0])
        names = [b.window_text() for b in buttons]
        action, want = print_popup_decision(text, names, already_printed)
        btn = next((b for b in buttons if b.window_text() == want), None) if want else None

        if action == "abort":
            log(f"  출력 중단 팝업입니다: {text}")
            if btn is not None:
                log(f"  -> '{want}' 클릭 후 루틴을 종료합니다.")
                ec.ensure_foreground(hwnd)
                btn.click_input()
                time.sleep(1.5)
            else:
                log(f"  -> 확인 버튼이 없습니다 (버튼: {names}). 팝업을 그대로 두고 종료합니다.")
            return "abort"
        if action == "stuck":
            log(f"  출력 중 팝업의 버튼을 처리할 수 없습니다: {names}")
            log(f"      내용: {text}")
            return "abort"
        if action == "already_printed":
            log(f"  '이미 출력한 배송장' 안내 -> '{want}' 클릭 (이번 실행에서 저장한 배송장이 아니라 다시 출력하지 않습니다)")
            log(f"      내용: {text}")
            ec.ensure_foreground(hwnd)
            btn.click_input()
            time.sleep(1.0)
            return "already_printed"

        kind = "'이미 출력한 배송장' 안내" if ALREADY_PRINTED_KEYWORD in text else "출력 중 팝업"
        log(f"  {kind} -> '{want}' 클릭")
        log(f"      내용: {text}")
        ec.ensure_foreground(hwnd)
        btn.click_input()
        status_ = "continued"
    return status_
```

- [ ] **Step 4: 구현 — `run_print_step`**

시그니처 `def run_print_step(app, pid, hwnd, options=None, already_printed="continue"):`. 본문에서:
- `if handle_print_popups(app, hwnd, rounds=1, wait=1.5) == "abort": return False` →

```python
    r = handle_print_popups(app, hwnd, rounds=1, wait=1.5, already_printed=already_printed)
    if r == "abort":
        return "failed"
    if r == "already_printed":
        return "already_printed"
```
- `if not pick_carrier(pid, carrier): return False` → `return "failed"`
- 두 번째 `handle_print_popups(app, hwnd, rounds=3, wait=1.5)` 블록 →

```python
    r = handle_print_popups(app, hwnd, rounds=3, wait=1.5, already_printed=already_printed)
    if r == "abort":
        log("주소정제 등 출력 전 검증에 걸려 루틴을 종료합니다.")
        return "failed"
    if r == "already_printed":
        return "already_printed"
```
- 그 위의 `return False` (cboTag 없음 L4305, 버튼 없음 L4310) → `return "failed"`
- `return run_print_preview(...)` → `return "done" if run_print_preview(app, pid, hwnd, printer) else "failed"`
- 수동 경로 끝의 `return saved`/`return True` 계열 → `return "done" if saved else "failed"` (해당 줄을 읽어 맞춘다)
- docstring 에 `반환: "done" | "already_printed" | "failed"` 와 `already_printed` 설명 추가.

- [ ] **Step 5: 통과 확인**

Run: `.venv\Scripts\python.exe tests\test_routine_modules.py`
Expected: 4절 6건 통과.

---

### Task 6: 모듈 함수 5개, 디스패처, `main()` 재작성

**Files:**
- Modify: `run_routine.py`
  - 헤더 docstring (L1-70) "흐름" 절을 모듈 기준으로 갱신
  - `run_self_check` (L5138-5185) 에 실행 모듈 출력
  - `main()` (L5257-5556) 전체 교체 + 그 앞에 `goto_order_screen`, `module_*` 5개, `MODULE_FUNCS`, `run_modules`
  - `status.metric(..., value, total)` 옆에 `status.progress(value, total)` — `run_excel_upload_step` L2793·L2853·L2863, `run_stock_review_step` L2960·L3027
- Test: `tests/test_routine_modules.py` 절 추가

**Interfaces:**
- Consumes: Task 1~5 전부.
- Produces: `goto_order_screen(ctx) -> (ok, reason)`, `module_login/sales/hold/logistics/output(ctx) -> (result, reason)`, `MODULE_FUNCS = {key: func}`, `run_modules(selected) -> ("success"|"stopped", reason)`.

- [ ] **Step 1: 실패하는 시험 추가**

```python
print()
print("=== 5. 디스패처 (run_modules) ===")


class StatusRec:
    """rr.status 대역. 무엇이 어떤 순서로 불렸는지 기록한다."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def f(*a, **k):
            self.calls.append((name,) + a)
        return f

    def of(self, name):
        return [c[1:] for c in self.calls if c[0] == name]


def run(selected, results, attach=(True, None)):
    """모듈 함수를 가짜로 바꿔 디스패처만 돌린다. results: {모듈키: (result, reason)}"""
    rec = StatusRec()
    rr.status = rec
    called = []

    def fake(key):
        def f(ctx):
            called.append(key)
            return results.get(key, ("done", None))
        return f

    rr.MODULE_FUNCS = {k: fake(k) for k in ("login", "sales", "hold", "logistics", "output")}
    rr.RoutineContext.attach = lambda self: attach
    out = rr.run_modules(selected)
    return out, called, rec


ALL_ON = {"Login": True, "Sales": True, "Hold": True, "Logistics": True, "Output": True}
out, called, rec = run(ALL_ON, {})
check("전부 켜면 5개 순서대로", called == ["login", "sales", "hold", "logistics", "output"], str(called))
check("전부 done 이면 success", out == ("success", None), str(out))
check("module_done 5번 전부 done", [r[1] for r in rec.of("module_done")] == ["done"] * 5)

out, called, rec = run({**ALL_ON, "Sales": False, "Hold": False}, {})
check("끈 모듈은 부르지 않는다", called == ["login", "logistics", "output"], str(called))
check("끈 모듈은 module_off", [r[0] for r in rec.of("module_off")] == ["sales", "hold"])
skipped = rec.of("skip")
check("끈 모듈의 단계는 '설정에서 끔' 으로 skip", len(skipped) == 9 and all(s[1] == "설정에서 끔" for s in skipped), str(skipped))

out, called, rec = run({**ALL_ON, "Login": False}, {})
check("로그인을 끄면 ERPia 에 붙어서 계속", called == ["sales", "hold", "logistics", "output"] and out[0] == "success", str(called))
out, called, rec = run({**ALL_ON, "Login": False}, {}, attach=(False, "ERPia 가 실행되어 있지 않습니다."))
check("붙기 실패면 아무 모듈도 안 돌고 stopped", called == [] and out[0] == "stopped" and "ERPia" in out[1], str(out))

out, called, rec = run(ALL_ON, {"hold": ("failed", "그리드 없음")})
check("failed 면 뒤 모듈 안 돌고 stopped", called == ["login", "sales", "hold"] and out == ("stopped", "그리드 없음"), str((called, out)))
out, called, rec = run(ALL_ON, {"sales": ("stopped", "매출처리 실패: x")})
check("stopped 도 멈춘다", called == ["login", "sales"] and out[0] == "stopped")
out, called, rec = run(ALL_ON, {"hold": ("no_target", "행 없음")})
check("no_target 은 계속 간다", called == ["login", "sales", "hold", "logistics", "output"] and out[0] == "success")
out, called, rec = run(ALL_ON, {"hold": ("skipped", "메뉴 없음")})
check("skipped 도 계속 간다", len(called) == 5 and out[0] == "success")

print()
print("=== 6. 출력 모듈의 중복 인쇄 방지 연결 ===")
seen = {}
rr.goto_logistics_screen = lambda ctx: seen.setdefault("goto", 0) or seen.update(goto=seen.get("goto", 0) + 1) or "ok"
rr.apply_auto_mode = lambda app, hwnd, opt: (seen.update(mode=True) or (False, True))
rr.run_print_step = lambda app, pid, hwnd, options=None, already_printed="continue": seen.update(policy=already_printed) or "done"
rr.status = StatusRec()
ctx = make_ctx()
ctx.options = {}
ctx.done = {"logistics"}
seen.clear()
check("물류관리가 방금 done 이면 continue + 화면 이동 없음", rr.module_output(ctx) == ("done", None) and seen.get("policy") == "continue" and "goto" not in seen, str(seen))
ctx.done = set()
seen.clear()
check("물류관리 없이 출력만이면 화면 이동 + 모드 맞춤 + stop", seen.get("goto") == 1 and seen.get("mode") is True and seen.get("policy") == "stop" and rr.module_output(ctx)[0] == "done", str(seen))
rr.run_print_step = lambda app, pid, hwnd, options=None, already_printed="continue": "already_printed"
check("이미 출력이면 no_target", rr.module_output(ctx)[0] == "no_target")
```

> 6절 두 번째 check 는 `module_output` 을 먼저 한 번 돌린 뒤 `seen` 을 보는 구조가 아니라 한 식 안에서 부른다. 순서가 헷갈리면 `res = rr.module_output(ctx)` 를 먼저 두고 check 하도록 풀어 써도 된다.

- [ ] **Step 2: 실패 확인**

Run: `.venv\Scripts\python.exe tests\test_routine_modules.py`
Expected: `AttributeError: ... 'run_modules'`

- [ ] **Step 3: 구현 — progress 호출 추가**

`run_excel_upload_step`:
- `status.metric("excel_upload", "엑셀 업로드", 0, len(targets), unit="개")` 뒤에 `status.progress(0, len(targets))`
- 루프 안 `status.note(f"{idx}/{len(targets)} · {name}")` 뒤에 `status.progress(idx - 1, len(targets), name)`
- 끝의 두 `status.metric("excel_upload", ..., uploaded, len(targets), ...)` 뒤에 각각 `status.progress(uploaded, len(targets))`

`run_stock_review_step`:
- `status.metric("stock_hold", "재고검토 보류", 0, len(targets))` 뒤에 `status.progress(0, len(targets))`
- `status.note(f"{idx}/{len(targets)}건째 · 상품코드 {code}")` 뒤에 `status.progress(idx - 1, len(targets), f"상품코드 {code}")`
- `status.metric("stock_hold", "재고검토 보류", done, len(targets))` 뒤에 `status.progress(done, len(targets))`

- [ ] **Step 4: 구현 — `goto_order_screen` 과 모듈 함수 5개**

`main()` 정의 바로 앞에 추가 (기존 main 의 코드를 옮기는 것이므로, 각 함수의 처리 본문은 **현재 main() L5348-5489 의 줄을 그대로** 가져오고 `return` 만 바꾼다):

```python
# ---------------------------------------------------------------------------
# 화면 모듈. 각 모듈은 ctx 하나를 받아 (결과, 사유) 를 돌려준다.
#   결과: "done"      처리함
#         "no_target" 할 것이 없었음 (정상)
#         "skipped"   업체에 그 메뉴가 없어 건너뜀 (정상)
#         "stopped"   업무 규칙상 중단 (매출처리 실패, 저장 검증 오류 등) -> 뒤 모듈을 돌리지 않는다
#         "failed"    기술적 실패 (화면/버튼을 못 찾음 등) -> 뒤 모듈을 돌리지 않는다
# 모듈 안의 대시보드 단계(status.step)는 모듈 함수가 스스로 찍는다.
# ---------------------------------------------------------------------------

def module_login(ctx):
    """ERPia 를 띄우고(이미 떠 있으면 그대로) 로그인한 뒤 메인 창을 잡는다."""
    status.step("login")
    admin_code, user_id, password = pl.load_credentials()
    exe_path = load_exe_path()
    ctx.pid = ensure_erpia_running(exe_path)

    state, obj = wait_login_or_main(ctx.pid)
    if state == "timeout":
        return "failed", "로그인 창도 메인 화면도 나타나지 않았습니다."
    if state == "login_window":
        log(f"로그인 창 발견: handle={obj.handle}")
        result = pl.login_flow(admin_code, user_id, password, log=log)
        if result["status"] not in ("success", "already_logged_in"):
            return "failed", f"로그인 실패: {result.get('status')} - {result.get('message')}"
    else:
        log("이미 로그인된 상태로 확인됨.")

    # 로그인 직후 ERPia 가 메인 창을 다시 만들어 핸들이 무효가 되는 일이 있어(2차 인증 팝업 경로),
    # UIA 호출이 실제로 되는 창을 잡을 때까지 재시도한다.
    log("메인 화면 대기 중...")
    if not ctx.refresh():
        return "failed", "메인 화면을 안정적으로 잡지 못했습니다."
    log(f"메인 창 확보: hwnd={ctx.hwnd}")
    return "done", None


def goto_order_screen(ctx):
    """좌측 'lcg_OrderCollect' 아이콘으로 '주문매핑 매출처리' 화면에 들어간다. (ok, 사유)

    로그인 직후에는 창이 다시 만들어져 UIA 오류가 날 수 있어, 그때는 ctx.refresh() 로 창을 다시 잡는다.
    """
    target = None
    waited = 0.0
    while waited < 30.0:
        try:
            target = find_by_text(ctx.window(), "lcg_OrderCollect", control_types=("Pane",))
        except Exception as e:
            log(f"  화면 이동 준비 중 UIA 오류 -> 메인 창을 다시 잡습니다: {type(e).__name__}")
            if not ctx.refresh():
                return False, "메인 창을 다시 잡지 못했습니다."
            log(f"  메인 창 다시 확보: hwnd={ctx.hwnd}")
            target = None
        if target is not None:
            break
        time.sleep(1.0)
        waited += 1.0
    if target is None:
        return False, "'lcg_OrderCollect' 아이콘을 찾지 못했습니다 (30초 대기 후)."

    ec.ensure_foreground(ctx.hwnd)
    try:
        target.click_input()
    except Exception as e:
        log(f"  주문매핑 아이콘 클릭 중 오류 -> 메인 창을 다시 잡고 재시도: {type(e).__name__}")
        if not ctx.refresh():
            return False, "메인 창을 다시 잡지 못했습니다."
        target = find_by_text(ctx.window(), "lcg_OrderCollect", control_types=("Pane",))
        if target is None:
            return False, "'lcg_OrderCollect' 아이콘을 다시 찾지 못했습니다."
        ec.ensure_foreground(ctx.hwnd)
        target.click_input()

    ok, active = wait_for_active_main_tab(ctx.app, ctx.hwnd, "주문매핑", ctx=ctx)
    if not ok:
        tabs = [t.window_text() for t in ctx.window().descendants(control_type="TabItem")]
        return False, f"화면 이동 실패 (활성 메인탭='{active}'). 탭 목록: {tabs}"
    log(f"화면 이동 확인됨 (활성 메인탭='{active}')")
    return True, None


def module_sales(ctx):
    """주문매핑 매출처리: 화면 이동 -> 상단 전체선택 -> 가져오기 -> 엑셀업로드 -> 하단 전체선택 -> 정상매출.

    대상이 0건이어도 '정상매출'을 누른다 (예전 흐름 그대로. ERPia 가 어떤 팝업을 내는지 실측이 없어
    '대상 없음' 판정은 넣지 않았다).
    """
    status.step("order_screen")
    log("\n=== 주문매핑 매출처리 화면 이동 ===")
    ok, reason = goto_order_screen(ctx)
    if not ok:
        return "failed", reason
    app, pid, hwnd = ctx.app, ctx.pid, ctx.hwnd
    win = ctx.window()

    onscreen_tables = get_onscreen_tables(win)
    if len(onscreen_tables) < 2:
        return "failed", "그리드가 충분히 발견되지 않았습니다."
    top_left = min(onscreen_tables, key=lambda t: (t.rectangle().top, t.rectangle().left))
    bottom = max(onscreen_tables, key=lambda t: t.rectangle().top)

    # --- 여기부터 '정상매출' 클릭 완료까지: 기존 main() L5355-5424 의 코드를 그대로 옮긴다 ---
    #     (status.step("top_select") ... select_all_and_verify ... run_import_step ...
    #      status.step("excel_upload") ... status.step("bottom_select") ... status.step("sales")
    #      split_btn / dropdown_btn / menu_win 탐색 / baseline_children / normal_btn.click_input())
    #     바뀌는 것: 'log(...); return' 세 곳(매출처리 버튼 없음, ▼ 없음, 메뉴 없음)을
    #     'return "failed", "<같은 문구>"' 로.
    # --- 여기부터 끝까지: 기존 main() L5426-5489 를 옮기되 status.finish(...) + return 네 곳을
    #     'return "stopped", "<같은 사유>"' 로 바꾼다. (finish 는 run_modules/main 이 부른다) ---
    return "done", None


def module_hold(ctx):
    """물류대기 관리: 화면 이동 -> 재고검토 배송보류 -> 일반 탭 비정상 배송보류 -> 저장."""
    status.step("hold_screen")
    log("\n=== 물류대기 화면 이동 ===")
    r = goto_hold_screen(ctx)
    if r == "absent":
        # 물류대기 메뉴가 없는 업체. 물류 관리는 항상 있으므로 다음 모듈로 넘어가면 된다.
        for key in ("stock_review", "abnormal_hold", "hold_save"):
            status.skip(key, "물류대기 메뉴가 없는 업체")
        return "skipped", "물류대기 메뉴가 없는 업체"
    if r != "ok":
        return "failed", "물류대기 화면으로 이동하지 못했습니다."

    log("\n=== 물류대기 처리 ===")
    result = run_hold_logistics_step(ctx.app, ctx.pid, ctx.hwnd)
    if result == "failed":
        return "failed", "물류대기 처리에 실패했습니다."
    if result == "no_target":
        return "no_target", "물류대기 그리드에 행이 없어 저장하지 않았습니다."
    return "done", None


def module_logistics(ctx):
    """물류관리: 화면 이동 -> 자동/수동 -> 개별 배송 -> 배송정보설정(항상) -> 저장.

    배송정보설정은 로그인 세션마다 초기화되므로 이 모듈 안에서 반드시 돈다.
    실패하면 잘못된 택배사/구분으로 저장하지 않도록 중단한다.
    """
    status.step("logistics_screen")
    log("\n=== 물류 관리 화면 이동 ===")
    r = goto_logistics_screen(ctx)
    if r == "absent":
        return "failed", "'물류처리' 아이콘을 찾지 못했습니다."
    if r != "ok":
        return "failed", "물류 관리 화면으로 이동하지 못했습니다."

    options = ctx.logistic_options()
    log(f"\n물류 관리 설정값: {options}")

    status.step("logistics")
    log("\n=== 물류 관리 처리 ===")
    result = run_logistics_step(ctx.app, ctx.pid, ctx.hwnd, options=options)
    log(f"물류 관리 처리 결과: {MODULE_RESULT_LABEL.get(result, result)}")
    if result == "no_target":
        status.skip("shipping_setup", "배송 대상 없음")
        status.skip("logistics_save", "배송 대상 없음")
        return "no_target", "물류 관리 하단 그리드에 배송 대상이 없습니다."
    if result != "done":
        return "failed", "물류 관리 처리에 실패했습니다."

    status.step("shipping_setup")
    log("\n=== 배송정보설정 (업체/박스/구분) ===")
    if not run_shipping_setup_step(ctx.app, ctx.pid, ctx.hwnd, options=options):
        return "stopped", "배송정보설정에 실패했습니다. 잘못된 값으로 저장하지 않도록 중단합니다."

    status.step("logistics_save")
    log("\n=== 물류 관리 저장 ===")
    ok, reason = run_logistics_save_step(ctx.app, ctx.hwnd)
    log(f"저장 결과: {'성공' if ok else '중단'} / 사유: {reason}")
    if not ok:
        return "stopped", f"물류 관리 저장이 막혔습니다 - {reason}"
    return "done", None


def module_output(ctx):
    """운송장 출력(자동) 또는 엑셀파일 생성(수동).

    이번 실행에서 물류관리 모듈이 done 이 아니면(출력만 따로 돌릴 때):
      - 화면을 스스로 '물류 관리' 로 옮기고 자동/수동을 설정값대로 맞춘다
        (출력은 화면 콤보의 현재값을 따르므로, 안 맞추면 직전 세션 잔값대로 눌린다)
      - '이미 운송장(으)로 생성(출력)한 배송장' 팝업에서는 '아니오' 를 누르고 끝낸다 (중복 인쇄 금지)
    """
    status.step("output")
    if "logistics" not in ctx.done:
        log("\n=== 물류 관리 화면 이동 (출력 단독 실행) ===")
        if goto_logistics_screen(ctx) != "ok":
            return "failed", "물류 관리 화면으로 이동하지 못했습니다."
        log("자동/수동 모드 설정")
        _, mode_ok = apply_auto_mode(ctx.app, ctx.hwnd, ctx.logistic_options())
        if not mode_ok:
            return "failed", "자동/수동 모드를 설정하지 못해 출력하지 않습니다."

    log("\n=== 운송장 출력 / 엑셀파일 생성 ===")
    policy = "continue" if "logistics" in ctx.done else "stop"
    result = run_print_step(ctx.app, ctx.pid, ctx.hwnd, options=ctx.logistic_options(),
                            already_printed=policy)
    if result == "already_printed":
        return "no_target", "이미 출력한 배송장이라 다시 출력하지 않았습니다."
    if result != "done":
        return "failed", None   # 사유는 run_print_step 이 남긴 마지막 문제 로그에서 가져간다
    return "done", None


MODULE_FUNCS = {
    "login": module_login,
    "sales": module_sales,
    "hold": module_hold,
    "logistics": module_logistics,
    "output": module_output,
}


def run_modules(selected):
    """설정대로 모듈을 차례로 돌린다. (전체 결과 "success"|"stopped", 사유)

    - 끈 모듈은 부르지 않고 그 단계들을 '설정에서 끔' 으로 표시한다.
    - 로그인 모듈 없이 시작하면 이미 떠 있는 ERPia 에 붙는다.
    - failed / stopped 가 나오면 뒤 모듈을 돌리지 않는다. done / no_target / skipped 는 계속 간다.
    """
    ctx = RoutineContext()
    for key, cfg_key, label, steps in ROUTINE_MODULES:
        if not selected.get(cfg_key, True):
            log(f"\n=== [{label}] 설정에서 꺼져 있어 건너뜁니다 ({cfg_key}=N) ===")
            status.module_off(key, "설정에서 끔")
            for s in steps:
                status.skip(s, "설정에서 끔")
            continue

        if key != "login" and ctx.hwnd is None:
            ok, reason = ctx.attach()
            if not ok:
                log(f"[{label}] {reason}")
                status.module_start(key)
                status.module_done(key, "failed", reason)
                return "stopped", reason
            log(f"이미 떠 있는 ERPia 에 붙었습니다: pid={ctx.pid} hwnd={ctx.hwnd}")

        status.module_start(key)
        log(f"\n=== [{label}] 시작 ===")
        result, reason = MODULE_FUNCS[key](ctx)
        status.module_done(key, result, reason)
        log(f"=== [{label}] {MODULE_RESULT_LABEL.get(result, result)}"
            f"{' - ' + reason if reason else ''} ===")
        if result == "done":
            ctx.done.add(key)
        if result in ("failed", "stopped"):
            return "stopped", reason
    return "success", None
```

- [ ] **Step 5: 구현 — `main()` 교체**

기존 `def main():` 부터 `log(f"=== 루틴 종료 ...")` 까지 전체를:

```python
def main():
    if "--check" in sys.argv[1:]:
        run_self_check()
        return
    if "--uiacheck" in sys.argv[1:]:
        run_uia_check()
        return

    status.start("routine", ROUTINE_STEPS)
    status.set_modules([(k, label, steps) for k, _, label, steps in ROUTINE_MODULES])
    log(f"=== 루틴 시작 {time.strftime('%Y-%m-%d %H:%M:%S')} ===")

    # 대시보드에 '업체코드 · 아이디' 로 보인다 (비밀번호는 읽지 않는다). 로그인 모듈을 꺼도 보이게 여기서.
    account = status.read_account()
    if account:
        status.account(account.get("admin_code"), account.get("user_id"))

    try:
        selected, unknown = pl.load_routine_modules([m[1] for m in ROUTINE_MODULES])
    except RuntimeError as e:
        log(f"설정 오류: {e}")
        status.finish("stopped", str(e))
        log(f"=== 루틴 종료 {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
        return
    for k in unknown:
        log(f"경고: '{pl.ROUTINE_SECTION}' 섹션의 '{k}' 는 모르는 키라 무시합니다.")
    log("실행할 모듈: " + " / ".join(
        f"{label} {'켬' if selected[cfg] else '끔'}" for _, cfg, label, _ in ROUTINE_MODULES))

    result, reason = run_modules(selected)
    status.finish(result, reason)
    log(f"=== 루틴 종료 {time.strftime('%Y-%m-%d %H:%M:%S')} ({'성공' if result == 'success' else '중단'}) ===")
```

- [ ] **Step 6: 구현 — `--check` 와 헤더 docstring**

`run_self_check()` 의 `물류 설정` 블록 뒤에:

```python
    try:
        selected, unknown = pl.load_routine_modules([m[1] for m in ROUTINE_MODULES])
        log("실행 모듈   : " + " / ".join(
            f"{label} {'켬' if selected[cfg] else '끔'}" for _, cfg, label, _ in ROUTINE_MODULES))
        for k in unknown:
            log(f"  -> 경고: '{pl.ROUTINE_SECTION}' 섹션의 '{k}' 는 모르는 키입니다 (무시됨)")
    except Exception as e:
        log(f"실행 모듈   : 읽기 실패 - {e}")
```

헤더 docstring 의 "흐름:" 앞에 다음 절을 넣는다 (기존 1~18 번호 목록은 그대로 둔다 — 각 모듈이 무엇을 하는지의 설명으로 여전히 맞다):

```
모듈 (2026-09-18):
    흐름을 다섯 화면 모듈로 나눠 ERPIA_AI.txt 의 "Routine" 섹션으로 골라 돌린다.
      Login / Sales / Hold / Logistics / Output  = "Y"(켬) 또는 "N"(끔). 없으면 켬.
      예: {"Routine": [{"Login": "Y"}, {"Sales": "Y"}, {"Hold": "N"}, {"Logistics": "Y"}, {"Output": "Y"}]}
    - 로그인을 끄면 이미 떠 있는 ERPia 에 붙는다. 물류관리/출력만 켜면 스스로 '물류 관리' 화면으로 간다.
    - 물류관리 안의 배송정보설정은 로그인 세션마다 초기화되므로 항상 돈다 (모듈 안 단계는 고를 수 없다).
    - 출력만 따로 돌릴 때 '이미 출력한 배송장' 팝업이 뜨면 아니오를 누르고 끝낸다 (중복 인쇄 금지).
    - 상태 파일(RPA_STATUS\status_routine.json)에 modules[]/module_flags(비트: login=1 sales=2 hold=4
      logistics=8 output=16)/progress 를 남긴다.
```

- [ ] **Step 7: 통과 확인 + 회귀**

Run: `.venv\Scripts\python.exe tests\test_routine_modules.py`
Expected: 1~6절 전부 통과.

Run: `tests\test_stock_hold_sim.py`, `tests\test_popup_rule.py`, `tests\test_sales_popups.py`, `tests\test_mail_find.py`, `tests\test_dashboard_auth.py`
Expected: 전부 통과.

- [ ] **Step 8: 죽은 코드 확인**

Run: `.venv\Scripts\python.exe -c "import run_routine as rr; print(hasattr(rr,'goto_logistics'), hasattr(rr,'run_hold_save_and_goto_logistics'))"`
Expected: `False False`

---

### Task 7: 마무리 — 그래프, 빌드, 설정 파일 점검

**Files:**
- Run only. 수정 없음 (ERPIA_AI.txt 는 사용자 파일이라 여기서 손대지 않는다).

- [ ] **Step 1: 그래프 갱신**

Run: `graphify update .`
Expected: "Code graph updated".

- [ ] **Step 2: `--check` (소스)**

Run: `.venv\Scripts\python.exe run_routine.py --check`
Expected: `실행 모듈   : 로그인 켬 / 주문매핑 매출처리 켬 / ...` 한 줄이 나오고 (Routine 섹션이 아직 없으니 전부 켬), 나머지 기존 항목 그대로.

- [ ] **Step 3: exe 재빌드와 점검**

Run: `.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean ERPia_RPA.spec`
Run: `dist\ERPia_RPA.exe --check`
Expected: exit 0, 헤더 `4D 5A`(MZ), 실행 모듈 줄 출력. 크기 21~22MB (전과 비슷).

- [ ] **Step 4: 사용자에게 보고**

실제 ERPia 로 도는 확인(전체 켬 / 출력만 켬 / 로그인 끔 조합)은 사용자 승인 뒤 별도로 한다. 이 계획의 시험은 전부 오프라인이다.

---

## Self-Review

**사양 커버리지**
- 모듈 5개로 나눔 → Task 3(표), 6(함수). ✓
- 설정으로 골라 실행 (A2, A3) → Task 1(읽기), 6(디스패처 `selected`). ✓
- 완료 flag: 상태 + 비트 (A1) → Task 2 `modules[].state`, `module_flags`. ✓
- 모듈 안 progress (A1) → Task 2 `progress()`, Task 6 Step 3 호출, `decorate` pct. ✓
- Blocker 1 중복 인쇄 → Task 5 정책, Task 6 `module_output` 의 `policy`. ✓
- Blocker 2 shipping_setup 고정 → Task 6 `module_logistics` (선택 불가, 실패 시 stopped). ✓
- 의존 규칙: 물류관리 진입 함수(Task 3), hold/process 폴백 분리(Task 3), 출력 단독 시 모드 맞춤(Task 6), 대상 0건 정상 종료(Task 4), 로그인 생략 시 attach(Task 3·6), hwnd 무효 재확보(Task 3 `goto_screen_by_icon`, Task 6 `goto_order_screen`, `wait_for_active_main_tab ctx`). ✓
- 잔존 팝업 규칙: 출력이 마지막 모듈이고 저장 실패는 `stopped` 라 자연히 지켜진다. 별도 코드 없음 (의도적).
- 강제 종료·예외 시 모듈 상태 닫기 → Task 2 `finish`, `_mark_vanished`. ✓

**자리표시자 점검** — Task 4 Step 1 과 Task 6 Step 4 의 `module_sales` 에 "기존 줄을 그대로 옮긴다" 지시가 있다. 이는 140줄짜리 기존 코드를 계획에 다시 복사하지 않기 위한 것으로, 옮길 줄 범위(L5355-5424, L5426-5489)와 바꿀 곳(return 문구)을 정확히 적었다. 실행자는 그 줄을 읽어 옮긴다.

**타입 일관성** — `goto_screen_by_icon` 반환 `"ok"/"absent"/"failed"` 를 `module_hold`/`module_logistics`/`module_output` 이 같은 문자열로 본다 ✓. `run_hold_logistics_step`/`run_logistics_step`/`run_print_step` 의 문자열 반환을 모듈 함수가 같은 값으로 본다 ✓. `wait_for_active_main_tab(..., ctx=)` 시그니처가 시험의 가짜 함수와 같다 ✓. `set_modules([(key,label,steps)])` 를 `main()` 이 그 모양으로 부른다 ✓.
