# 웰라이프 실행 관문 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 웰라이프 실행(PR #2, `wellife.py`)을 업체코드에 `wellife` 가 든 업체(대소문자 무관)와 관리 화면에서 연 업체에만 열고, 관리 화면 → 업체 웹 → 에이전트 → 루틴 갈래까지 같은 규칙으로 막는다.

**Architecture:** 규칙 하나 `wellife = "wellife" in cid.lower() or features.wellife is true` 를 관리 화면(ops.js)·업체 웹(rpa-common.js)·에이전트(agent.py)가 같이 쓴다. 에이전트가 규칙 결과를 PC 의 `settings.json` `schedule.policy.wellife` 에 적고, 루틴(`run_routine.main`)과 에이전트 명령은 그 값으로 막는다. `Wellife` 섹션은 에이전트가 쓴다 (메모장 편집 없음).

**Tech Stack:** Python 3.14 (표준 라이브러리), Node(firebase-admin) 관리 도구, 바닐라 JS 업체 웹, Firebase 에뮬레이터 시험, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-07-wellife-gate-design.md`

## Global Constraints

- 화면·기록·명령 결과 글은 한국어, 업무 서식 말투 (메모리 ui-wording): 체크 이름 **"웰라이프 실행"**, 잠금 글 **"업체코드에 wellife 포함 - 늘 열림"**, 막힌 모듈 글 **"웰라이프 업체는 쓰지 않음"**.
- 규칙: `"wellife" in cid.lower()` 이거나 `meta/companies/{cid}/apps/rpa/features/wellife === true`. 업체코드 규칙에 걸린 업체는 끌 수 없다.
- 웰라이프 업체 모듈 (설정 키·이름, 이 순서): `Login` 로그인 · `Sales` 주문매핑 매출처리 · `Hold` 물류대기 관리 · `Sap` 웰라이프 SAP 연동관리 · `Wms` 웰라이프 WMS 이관관리. 막는 모듈: `Logistics`·`Output`.
- 처음 열렸는데 `Wellife` 섹션이 없으면 `{"Login": "Y", "Sales": "Y", "Hold": "N", "Sap": "N", "Wms": "N"}` 으로 만든다.
- 웰라이프 업체의 자동 실행은 '전체' 줄만 - `run`·`until` 줄은 거절: **"웰라이프 업체는 '전체' 시각만 쓸 수 있습니다"**.
- 루틴 갈래 멈춤 글: 정책 켬·섹션 없음 **"웰라이프 설정이 없습니다 (에이전트가 다시 씁니다)"**, 정책 끔·섹션 있음 **"이 업체는 웰라이프 실행이 열려 있지 않습니다 (관리 화면)"**.
- `wellife.py` 의 화면 처리는 고치지 않는다 (작업자 몫, 설계 5절).
- 시험 방식: `check(cond, what)` → `PASS`/`FAIL`, 끝에 `실패: 없음`. 에뮬레이터만, 진짜 서버 금지. 한글 파일은 Write/Edit 또는 Write 로 만든 파이썬 패치 (heredoc 금지). 코드 바꾼 뒤 `graphify update .`.

## Review Focus

1. **보통 루틴으로 새는 길이 없어야 한다** - 웰라이프 업체 PC 에서 섹션이 지워지거나 설정을 못 읽어도 매출처리·물류관리·운송장이 돌지 않는다. Task 2 시험(표 네 칸 + 설정 못 읽음).
2. **열리지 않은 업체는 PC 파일을 고쳐도 웰라이프로 못 간다** - Task 2(갈래) + Task 3(명령 거절).
3. **대소문자·포함 판정** - `WELLIFE_x`, `my_wellife`, `wel_life`(안 열림) 를 세 곳이 똑같이 판정. Task 3·4·5 시험에 같은 예를 쓴다.
4. **보통 업체는 아무것도 안 바뀐다** - 정책 `wellife` 가 없거나 false 면 지금 그대로 (모듈 다섯 개, 시각별 고르기, 반복). Task 2·3·5 시험.
5. **정책을 못 읽었을 때** - 에이전트가 정책을 못 읽으면 PC 에 적힌 마지막 값(웰라이프면 웰라이프 그대로). Task 3 시험.

---

## 파일 지도

| 파일 | 할 일 |
|---|---|
| `rpa_status.py` | `WELLIFE_CONFIG_MODULES`, `WELLIFE_SECTION`, `WELLIFE_DEFAULT`, `read_wellife_modules`, `write_wellife_modules`, `ensure_wellife_section`, `wellife_policy` |
| `rpa_dashboard.py` | `set_policy(limit, off, wellife=False)` 가 `policy.wellife` 도 적는다 |
| `run_routine.py` | `wellife_route(policy_on, has_section)` 과 `main` 갈래 |
| `firebase/agent/agent.py` | `wellife_on(cid, features)`, `company_policy` 3개 값, `Policy.refresh`, `do_modules`, `do_schedule`, 하트비트 모듈 |
| `firebase/admin/ops.js`·`admin.js`·`AFTERMARKET_SETUP.html` | `wellifeOn`, `companyDetail` 의 `features`·`wellife`, `setFeature`, 경로, 체크 |
| `firebase/web/rpa-common.js`·`rpa-settings.js` | `WELLIFE_MODULES`, `wellifeOn`, 모듈 상자·자동 실행 |
| 시험 | `tests/test_wellife_gate.py`(새), `tests/test_login_flow.py`(새), `firebase/tests/test_agent.py`, `check_admin.py`, `check_web.py` |

시험 명령: PC 묶음 `bash .superpowers/sdd/2026-10-07-wellife-gate/pc_tests.sh <이름…>` (Task 1 에서 `.superpowers/sdd/2026-10-07-settings-schedule/` 의 `pc_tests.sh`·`emu.ps1` 을 복사), 에뮬레이터 `powershell -File .superpowers/sdd/2026-10-07-wellife-gate/emu.ps1 -Cmd '<명령>' -Only <에뮬레이터>`.

---

### Task 1: PC 설정 - Wellife 섹션 읽기·쓰기, 정책 값

**Files:**
- Modify: `rpa_status.py` (ROUTINE_CONFIG_MODULES 아래), `rpa_dashboard.py:656` (`set_policy`)
- Test: `tests/test_wellife_gate.py` (새)

**Interfaces:**
- Produces: `rpa_status.WELLIFE_SECTION = "Wellife"`, `WELLIFE_CONFIG_MODULES` (위 다섯 튜플), `WELLIFE_DEFAULT = {"Login": True, "Sales": True, "Hold": False, "Sap": False, "Wms": False}`, `read_wellife_modules(path=None) -> (dict, list)` (빠진 키는 **끔** - wellife.load_switches 와 같은 뜻, Login 은 늘 True), `write_wellife_modules(selected, path=None) -> dict` (Login 은 True 고정, 모르는 키 ValueError, 파일 없으면 FileNotFoundError), `ensure_wellife_section(path=None) -> bool` (없을 때만 WELLIFE_DEFAULT 로 쓰고 True), `has_wellife_section(path=None) -> bool`, `wellife_policy() -> bool` (settings.json schedule.policy.wellife is True, 못 읽으면 False), `rpa_dashboard.set_policy(limit, off, wellife=False) -> bool`.

- [ ] **Step 1: 작업 폴더 준비** - `mkdir -p .superpowers/sdd/2026-10-07-wellife-gate && cp .superpowers/sdd/2026-10-07-settings-schedule/{pc_tests.sh,emu.ps1} .superpowers/sdd/2026-10-07-wellife-gate/`

- [ ] **Step 2: 실패하는 시험** - `tests/test_wellife_gate.py`:

```python
# -*- coding: utf-8 -*-
"""웰라이프 실행 관문 (설계 docs/superpowers/specs/2026-10-07-wellife-gate-design.md). 설정은 임시 폴더."""
import json
import os
import sys
import tempfile

_tmp = tempfile.mkdtemp(prefix="wl_gate_")
os.environ["RPA_PROGRAMDATA"] = _tmp
os.environ["RPA_STATUS_DIR"] = os.path.join(_tmp, "status")
CFG = os.path.join(_tmp, "RPA_UserConfig.json")
os.environ["RPA_USER_CONFIG"] = CFG
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rpa_status as st  # noqa: E402
import rpa_dashboard as dash  # noqa: E402

fails = []


def check(cond, what):
    print(("PASS  " if cond else "FAIL  ") + what)
    if not cond:
        fails.append(what)


def write_cfg(data):
    with open(CFG, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def read_cfg():
    with open(CFG, encoding="utf-8") as f:
        return json.load(f)


print("=== 1. Wellife 섹션 ===")
write_cfg({"LogIn": {"AdminCode": "x"}, "Routine": {"Logistics": "Y"}})
check(st.has_wellife_section() is False, "섹션이 없으면 False")
check(st.ensure_wellife_section() is True and read_cfg()["Wellife"] == {"Login": "Y", "Sales": "Y", "Hold": "N", "Sap": "N", "Wms": "N"},
      "처음 열리면 로그인·주문매핑 매출처리만 켬")
check(read_cfg()["LogIn"] == {"AdminCode": "x"} and read_cfg()["Routine"] == {"Logistics": "Y"}, "다른 섹션은 그대로")
check(st.ensure_wellife_section() is False, "있으면 안 바꾼다")
got = st.write_wellife_modules({"Login": False, "Sales": True, "Hold": True, "Sap": True})
check(got == {"Login": True, "Sales": True, "Hold": True, "Sap": True, "Wms": False}, f"쓰기: 로그인은 늘 켬, 빠진 키는 끔 ({got})")
check(st.read_wellife_modules() == (got, []), "읽기는 쓴 값 그대로")
try:
    st.write_wellife_modules({"Logistics": True}); check(False, "모르는 키 거절")
except ValueError:
    check(True, "모르는 키(Logistics) 는 ValueError")
write_cfg({"LogIn": {}, "Wellife": {"Sales": "Y", "Hold": "maybe"}})
sel, problems = st.read_wellife_modules()
check(sel["Hold"] is None and problems and sel["Sap"] is False, f"Y/N 아닌 값은 None·문제, 빠진 키는 끔 ({sel}, {problems})")

print("=== 2. 정책 값 (settings.json) ===")
check(st.wellife_policy() is False, "정책을 한 번도 안 적었으면 False")
check(dash.set_policy(2, ["Logistics", "Output"], wellife=True) is True and st.wellife_policy() is True, "set_policy 가 wellife 도 적는다")
check(dash.set_policy(2, ["Logistics", "Output"], wellife=True) is False, "같으면 안 쓴다")
check(dash.set_policy(2, [], wellife=False) is True and st.wellife_policy() is False, "꺼지면 False")
check(dash.set_policy(2, []) is False, "wellife 를 안 넘기면 False 로 본다 (옛 부르는 쪽)")

print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
```

- [ ] **Step 3: 실패 확인** - `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe tests/test_wellife_gate.py` → `AttributeError: ... has_wellife_section`

- [ ] **Step 4: 구현** - `rpa_status.py`, `ROUTINE_CONFIG_MODULES` 바로 아래:

```python
WELLIFE_SECTION = "Wellife"    # 웰라이프 업체 PC 만 (설계 2026-10-07-wellife-gate). 키 이름은 wellife.MODULES 와 같다 - 바꾸면 둘 다
WELLIFE_CONFIG_MODULES = (
    ("Login", "로그인"),
    ("Sales", "주문매핑 매출처리"),
    ("Hold", "물류대기 관리"),
    ("Sap", "웰라이프 SAP 연동관리"),
    ("Wms", "웰라이프 WMS 이관관리"),
)
WELLIFE_DEFAULT = {"Login": True, "Sales": True, "Hold": False, "Sap": False, "Wms": False}   # 처음 열릴 때 (사용자 2026-10-07)
```

`write_routine_modules` 아래:

```python
def read_wellife_modules(path=None):
    """Wellife 섹션을 {키: True/False/None} 으로. 빠진 키는 끔 (Routine 과 반대 - wellife.load_switches 와 같다). 로그인은 늘 켬."""
    keys = [k for k, _ in WELLIFE_CONFIG_MODULES]
    try:
        data = read_user_config(path) or {}
    except Exception as e:
        return {k: None for k in keys}, [f"설정을 읽지 못했습니다: {type(e).__name__}"]
    section = data.get(WELLIFE_SECTION)
    if not isinstance(section, dict):
        return {k: (k == "Login") for k in keys}, ([] if section is None else [f"'{WELLIFE_SECTION}' 은 섹션이어야 합니다"])
    selected, problems = {}, []
    for k in keys:
        raw = section.get(k)
        v = str(raw).strip().upper() if raw is not None else "N"
        if v in ("Y", "N"):
            selected[k] = v == "Y" or k == "Login"
        else:
            selected[k] = None
            problems.append(f"{k} 값이 Y/N 이 아닙니다 ({raw!r})")
    return selected, problems


def write_wellife_modules(selected, path=None):
    """Wellife 섹션만 바꿔 쓴다 (나머지·비밀번호는 그대로). 로그인은 늘 Y, 빠진 키는 N. 모르는 키 ValueError."""
    keys = [k for k, _ in WELLIFE_CONFIG_MODULES]
    unknown = sorted(set(selected) - set(keys))
    if unknown:
        raise ValueError(f"모르는 모듈 키: {', '.join(unknown)}")
    final = {k: (k == "Login") or bool(selected.get(k, False)) for k in keys}
    data = read_user_config(path)
    if not data:
        raise FileNotFoundError(path or user_config_path())
    data[WELLIFE_SECTION] = _merge_routine_section(data.get(WELLIFE_SECTION), final)
    write_user_config(data, path)
    return final


def has_wellife_section(path=None):
    try:
        return isinstance((read_user_config(path) or {}).get(WELLIFE_SECTION), dict)
    except Exception:
        return False


def ensure_wellife_section(path=None):
    """웰라이프 업체가 처음 열렸는데 섹션이 없으면 기본값(로그인·주문매핑 매출처리만)으로 만든다. 만들었으면 True."""
    if has_wellife_section(path):
        return False
    write_wellife_modules({k: v for k, v in WELLIFE_DEFAULT.items()}, path)
    return True


def wellife_policy():
    """에이전트가 적은 업체 정책 - 이 PC 의 업체가 웰라이프로 열려 있나. 못 읽거나 없으면 False."""
    try:
        return (read_settings()["schedule"].get("policy") or {}).get("wellife") is True
    except Exception:
        return False
```

`rpa_dashboard.py` `set_policy`:

```python
def set_policy(limit, off, wellife=False):
    """...(기존 설명)... wellife: 이 업체가 웰라이프로 열려 있나 (루틴 갈래·명령이 본다)."""
    new = {"limit": limit, "off": sorted(off), "wellife": bool(wellife)}
    with _settings_lock:
        cfg = st.read_settings()
        sch = cfg["schedule"]
        old = sch.get("policy") or {}
        if (old.get("limit"), old.get("off"), bool(old.get("wellife"))) == (new["limit"], new["off"], new["wellife"]):
            return False
        ...(나머지 그대로)
```

- [ ] **Step 5: 통과 확인** - `bash .superpowers/sdd/2026-10-07-wellife-gate/pc_tests.sh test_wellife_gate test_routine_modules test_schedule_slots test_schedule_repeat test_settings agent` → 모두 통과

- [ ] **Step 6: 커밋**

```bash
git add rpa_status.py rpa_dashboard.py tests/test_wellife_gate.py
git commit -m "웰라이프 관문 1: PC 설정 - Wellife 섹션 읽기·쓰기(처음은 로그인·매출처리만), 정책 값 wellife"
```

---

### Task 2: 루틴 갈래 (`run_routine.main`)

**Files:**
- Modify: `run_routine.py:5864-5874` (`main`)
- Test: `tests/test_wellife_gate.py` (3절 추가)

**Interfaces:**
- Consumes: `st.wellife_policy()`, `st.has_wellife_section()` (Task 1)
- Produces: `run_routine.wellife_route(policy_on: bool, has_section: bool) -> tuple[str, str | None]` - `("wellife", None)` / `("routine", None)` / `("stop", 까닭)`.

- [ ] **Step 1: 실패하는 시험** - `tests/test_wellife_gate.py` 의 끝 출력 줄 앞에:

```python
print("=== 3. 루틴 갈래 ===")
import run_routine as rr  # noqa: E402
check(rr.wellife_route(True, True) == ("wellife", None), "열림 + 섹션 → 웰라이프 순서")
check(rr.wellife_route(True, False) == ("stop", "웰라이프 설정이 없습니다 (에이전트가 다시 씁니다)"), "열림 + 섹션 없음 → 멈춤 (보통 루틴으로 새지 않는다)")
check(rr.wellife_route(False, True) == ("stop", "이 업체는 웰라이프 실행이 열려 있지 않습니다 (관리 화면)"), "안 열림 + 섹션 → 멈춤")
check(rr.wellife_route(False, False) == ("routine", None), "안 열림 + 섹션 없음 → 지금 루틴 그대로")
# main 이 정말 이 갈래를 쓰는지 - 정책 켬·섹션 없음이면 보통 루틴을 시작하지 않고 멈춤으로 끝낸다
dash.set_policy(2, ["Logistics", "Output"], wellife=True)
write_cfg({"LogIn": {}})
called = []
orig_run, orig_start = rr.wellife.run_main, rr.status.start
rr.wellife.run_main = lambda r: called.append("wellife")
rr.status.start = lambda *a, **k: called.append(("start",) + a[:1])
finished = []
orig_finish = rr.status.finish
rr.status.finish = lambda result, reason=None, **k: finished.append((result, reason))
try:
    sys.argv = ["run_routine.py"]
    rr.main()
finally:
    rr.wellife.run_main, rr.status.start, rr.status.finish = orig_run, orig_start, orig_finish
check("wellife" not in called and finished and finished[-1][0] == "stopped" and "웰라이프 설정이 없습니다" in finished[-1][1],
      f"main: 정책 켬·섹션 없음 → 보통 루틴 안 돌고 멈춤 ({called}, {finished})")
dash.set_policy(2, [], wellife=False)
```

- [ ] **Step 2: 실패 확인** - `... tests/test_wellife_gate.py` → `AttributeError: module 'run_routine' has no attribute 'wellife_route'`

- [ ] **Step 3: 구현** - `run_routine.py`, `def main():` 바로 위:

```python
def wellife_route(policy_on, has_section):
    """웰라이프 관문 (설계 2026-10-07-wellife-gate 4.3). policy_on: 에이전트가 적은 업체 정책, has_section: PC 의 Wellife 섹션.
    ('wellife'|'routine'|'stop', 까닭). 열린 업체는 보통 루틴으로 새지 않고, 안 열린 업체는 파일을 고쳐도 웰라이프로 못 간다."""
    if policy_on:
        return ("wellife", None) if has_section else ("stop", "웰라이프 설정이 없습니다 (에이전트가 다시 씁니다)")
    return ("stop", "이 업체는 웰라이프 실행이 열려 있지 않습니다 (관리 화면)") if has_section else ("routine", None)
```

`main` 의 갈래를 바꾼다:

```python
    rr = sys.modules[__name__]   # exe 에서는 __main__ - wellife 가 다시 import 하지 않게 넘긴다
    route, why = wellife_route(status.wellife_policy(), wellife.enabled(rr))
    if route == "wellife":
        wellife.run_main(rr)
        return
    if route == "stop":
        status.start("routine", ROUTINE_STEPS)
        log(f"웰라이프 관문: {why}")
        status.finish("stopped", why)
        return
```

(`wellife.enabled(rr)` 은 섹션이 있는지 - 세 번 읽어 보고 못 읽으면 False. 정책이 켜져 있으면 못 읽어도 '멈춤' 이라 새지 않는다.)

- [ ] **Step 4: 통과 확인** - `bash .superpowers/sdd/2026-10-07-wellife-gate/pc_tests.sh test_wellife_gate test_wellife test_routine_modules` → 모두 통과

- [ ] **Step 5: 커밋**

```bash
git add run_routine.py tests/test_wellife_gate.py
git commit -m "웰라이프 관문 2: 루틴 갈래 - 열린 업체는 보통 루틴으로 새지 않고, 안 열린 업체는 섹션이 있어도 멈춤"
```

---

### Task 3: 에이전트 - 정책·섹션·명령

**Files:**
- Modify: `firebase/agent/agent.py` (`company_policy` :501, `Policy.refresh` :516, `do_modules` :554, `do_schedule` :584, 하트비트 모듈 :872)
- Test: `firebase/tests/test_agent.py` (company_policy 시험 :680 근처, set_modules 시험 :612 근처)

**Interfaces:**
- Consumes: Task 1 (`st.write_wellife_modules`, `st.ensure_wellife_section`, `st.wellife_policy`, `st.read_wellife_modules`, `st.WELLIFE_CONFIG_MODULES`, `dash.set_policy(limit, off, wellife)`)
- Produces: `agent.wellife_on(cid: str, features: dict | None) -> bool`, `agent.company_policy(client, cid) -> (limit, off, wellife)` (웰라이프면 off 에 Logistics·Output), `agent.WELLIFE_BLOCKED = ("Logistics", "Output")`.

- [ ] **Step 1: 실패하는 시험** - `test_agent.py` 의 company_policy 시험 세 줄(:680-682)을 3개 값으로 고치고 아래를 더한다:

```python
check(ag.company_policy(ac, "c_x") == (3, ["Hold"], False) and ac.asked == ["meta/companies/c_x/apps/rpa"], "한 번 읽어 한도·안 쓰는 모듈·웰라이프")
check(ag.company_policy(AppClient(None), "c_x") == (2, [], False), "정책이 없으면 기본 2개·안 쓰는 모듈 없음·웰라이프 아님")
check(ag.company_policy(AppClient({"limits": {"schedule": "9"}}), "c_x")[0] == 2 and ag.company_policy(AppClient({"limits": {"schedule": 0}}), "c_x")[0] == 0,
      "...(기존 글 그대로)")
for cid, feats, want in (("WELLIFE_x", None, True), ("my_wellife", None, True), ("Wellife", {}, True), ("wel_life", None, False),
                         ("c_demo", {"wellife": True}, True), ("c_demo", {"wellife": False}, False), ("c_demo", None, False)):
    check(ag.wellife_on(cid, feats) is want, f"웰라이프 판정 {cid} {feats} → {want}")
check(ag.company_policy(AppClient({"modules": {"Hold": False}}), "wellife_a") == (2, ["Hold", "Logistics", "Output"], True),
      "웰라이프 업체: 물류관리·운송장 출력을 안 쓰는 모듈에 더한다")
check(ag.company_policy(AppClient({"features": {"wellife": True}}), "c_demo")[2] is True, "관리 화면에서 연 업체도 웰라이프")
```

`Policy` 시험(:708 근처)에 더한다 (그 블록의 임시 RPA_PROGRAMDATA·RPA_USER_CONFIG 를 그대로 쓴다 - 사용자 설정 파일이 있어야 섹션을 쓸 수 있으니 블록이 만드는 파일을 쓴다):

```python
        wl = ag.Policy(AppClient({"features": {"wellife": True}}), "c_demo")
        check(wl.refresh(force=True) == (2, ["Logistics", "Output"], True) and st.wellife_policy() is True, "정책을 PC 에 적는다 (wellife)")
        check(st.read_wellife_modules()[0] == {"Login": True, "Sales": True, "Hold": False, "Sap": False, "Wms": False},
              "처음 열리면 섹션을 기본값(로그인·매출처리만)으로 만든다")
        check(ag.Policy(AppClient(fb.HttpError(503, "끊김")), "c_demo").refresh(force=True) is None and st.wellife_policy() is True,
              "정책을 못 읽으면 PC 에 적힌 마지막 값 (웰라이프 그대로)")
```

set_modules 시험(:612 근처, 같은 블록)에 더한다:

```python
        dash.set_policy(2, ["Logistics", "Output"], wellife=True)
        msg = acts["set_modules"]({"Login": False, "Sales": True, "Hold": True, "Sap": True, "Wms": False})
        check(st.read_wellife_modules()[0] == {"Login": True, "Sales": True, "Hold": True, "Sap": True, "Wms": False} and "켬" in msg,
              f"웰라이프 업체: set_modules 는 Wellife 섹션에 쓴다 ({msg})")
        try:
            acts["set_modules"]({"Logistics": True}); check(False, "웰라이프 업체에 물류관리 거절")
        except RuntimeError as e:
            check("웰라이프 업체는 쓰지 않음" in str(e), f"웰라이프 업체: 물류관리·운송장은 거절 ({e})")
        for bad in ({"enabled": True, "days": [0], "slots": [{"at": "09:00", "run": ["Sales"]}]},
                    {"enabled": True, "days": [0], "slots": [{"at": "09:00", "until": "10:00", "rest_min": 5}]}):
            try:
                acts["set_schedule"](bad); check(False, f"웰라이프 업체 고르기·반복 줄 거절 {bad}")
            except RuntimeError as e:
                check("'전체' 시각만" in str(e), f"웰라이프 업체: 고르기·반복 줄 거절 ({e})")
        check("자동 실행" in acts["set_schedule"]({"enabled": True, "days": [0], "slots": [{"at": "09:00", "run": None}]}), "웰라이프 업체: '전체' 줄은 된다")
        dash.set_policy(2, [], wellife=False)
        check(acts["set_modules"]({"Sales": True, "Hold": True, "Logistics": True, "Output": True}) and st.read_routine_modules()[0]["Logistics"] is True,
              "보통 업체는 그대로 Routine 섹션")
```

(`acts` 의 명령 이름이 `set_modules`/`set_schedule` 인지 그 파일의 기존 시험에서 확인하고 그대로 쓴다.)

- [ ] **Step 2: 실패 확인** - `bash .superpowers/sdd/2026-10-07-wellife-gate/pc_tests.sh agent` → company_policy 3개 값·wellife_on 실패

- [ ] **Step 3: 구현** - `agent.py`:

```python
WELLIFE_BLOCKED = ("Logistics", "Output")    # 웰라이프 업체가 안 쓰는 보통 루틴 모듈 (설계 2026-10-07-wellife-gate)


def wellife_on(cid, features):
    """웰라이프 업체인가 - 업체코드에 wellife (대소문자 무관) 또는 관리 화면에서 연 업체 (features.wellife true).
    관리 화면(ops.wellifeOn)·업체 웹(rpa-common.wellifeOn)과 같은 규칙."""
    return "wellife" in str(cid or "").lower() or (isinstance(features, dict) and features.get("wellife") is True)


def company_policy(client, cid, app=APP):
    """업체 정책 한 번에 - (자동 실행 개수, 안 쓰는 모듈 키 목록, 웰라이프). ...(기존 설명)
    웰라이프 업체는 물류관리·운송장 출력도 안 쓰는 모듈에 더한다."""
    got = client.get(f"meta/companies/{cid}/apps/{app}") or {}
    raw = (got.get("limits") or {}).get("schedule")
    ok = isinstance(raw, int) and not isinstance(raw, bool) and 0 <= raw <= SCHEDULE_LIMIT_MAX
    off = {k for k, v in (got.get("modules") or {}).items() if v is False}
    wl = wellife_on(cid, got.get("features"))
    if wl:
        off |= set(WELLIFE_BLOCKED)
    return (raw if ok else SCHEDULE_LIMIT_DEFAULT), sorted(off), wl
```

`Policy.refresh` 의 `dash.set_policy(*got)` 다음 줄:

```python
        if got[2]:
            import rpa_status as st
            try:
                st.ensure_wellife_section()          # 처음 열리면 로그인·매출처리만 켠 섹션 (메모장 편집 없음)
            except Exception:
                pass                                 # 사용자 설정이 아직 없으면 다음 번에
```

`do_modules` 맨 앞(`if not isinstance(args, dict)…` 다음):

```python
        if st.wellife_policy():                       # 웰라이프 업체 - Wellife 섹션 (설계 4.2)
            blocked = [k for k, v in args.items() if v and k in WELLIFE_BLOCKED]
            if blocked:
                raise RuntimeError(f"{', '.join(blocked)}: 웰라이프 업체는 쓰지 않음")
            wanted = {k: bool(v) for k, v in args.items() if k in dict(st.WELLIFE_CONFIG_MODULES)}
            if not wanted:
                raise RuntimeError("아는 모듈이 없습니다")
            final = st.write_wellife_modules(wanted)
            return f"실행 모듈을 바꿨습니다 (켬: {', '.join(k for k, v in final.items() if v)})"
```

`do_schedule` 맨 앞:

```python
        if st.wellife_policy() and isinstance(args, dict) and any(
                isinstance(s, dict) and (s.get("run") or s.get("until")) for s in (args.get("slots") or [])):
            raise RuntimeError("웰라이프 업체는 '전체' 시각만 쓸 수 있습니다")
```

하트비트(:872):

```python
                    snap["modules"] = (st.read_wellife_modules() if st.wellife_policy() else st.read_routine_modules())[0]
```

`company_policy` 를 부르는 다른 곳(`limits` 함수 등 - `grep -n company_policy firebase/agent/agent.py`)이 2개 값을 풀고 있으면 3개로 고친다.

- [ ] **Step 4: 통과 확인** - `bash .superpowers/sdd/2026-10-07-wellife-gate/pc_tests.sh agent test_wellife_gate test_schedule_slots test_schedule_repeat` → 모두 통과

- [ ] **Step 5: 커밋**

```bash
git add firebase/agent/agent.py firebase/tests/test_agent.py
git commit -m "웰라이프 관문 3: 에이전트 - 규칙(업체코드·관리 화면), 정책에 웰라이프·물류관리/운송장 막기, Wellife 섹션 쓰기, '전체' 시각만"
```

---

### Task 4: 관리 화면 - "웰라이프 실행" 체크

**Files:**
- Modify: `firebase/admin/ops.js` (`companyDetail` :307, `setModules` :161 옆), `firebase/admin/admin.js` (ROUTES), `firebase/admin/AFTERMARKET_SETUP.html` (`moduleSection`)
- Test: `firebase/tests/check_admin.py`

**Interfaces:**
- Produces: `ops.wellifeOn(cid, features) -> boolean`, `companyDetail(cid).features: {}`, `.wellife: boolean`, `.wellifeAuto: boolean`, `ops.setFeature(cid, key, on) -> {features}` (key 는 `"wellife"` 만, on 이면 true, 아니면 그 자리 지움), `POST /api/companies/:cid/features {wellife: bool}` (기록 `웰라이프 실행 {cid} = 켬/끔`).

- [ ] **Step 1: 실패하는 시험** - `check_admin.py` 의 API 시험(모듈 정책 :219 근처) 뒤에:

```python
code, d = api("GET", "/api/companies/t_new")
check(code == 200 and d.get("wellife") is False and d.get("wellifeAuto") is False, "웰라이프: 보통 업체는 꺼짐", str(d.get("wellife")))
code, r = api("POST", "/api/companies/t_new/features", {"wellife": True})
check(code == 200 and db_get("meta/companies/t_new/apps/rpa/features/wellife") is True, "웰라이프 실행 켜기", r)
code, d = api("GET", "/api/companies/t_new")
check(d.get("wellife") is True and d.get("wellifeAuto") is False, "켠 업체는 웰라이프")
code, r = api("POST", "/api/companies/t_new/features", {"wellife": False})
check(code == 200 and db_get("meta/companies/t_new/apps/rpa/features/wellife") is None, "끄면 자리를 지운다")
db_put("meta/companies/WELLIFE_x", {"name": "웰라이프 시험", "stts": 0})
code, d = api("GET", "/api/companies/WELLIFE_x")
check(code == 200 and d.get("wellife") is True and d.get("wellifeAuto") is True, "업체코드에 wellife (대소문자 무관) → 늘 열림", str(d)[:200])
code, r = api("POST", "/api/companies/WELLIFE_x/features", {"wellife": False})
check(code == 400 and "늘 열림" in r.get("error", ""), "업체코드 규칙 업체는 끌 수 없다", r)
```

(`WELLIFE_x` 같은 대문자 업체코드를 `checkKey` 가 거절하면 `my_wellife` 로 바꾼다 - 업체코드 형식은 ops.js 의 `checkKey` 를 따른다. 업체 상세가 계정 목록 등 다른 자리를 요구하면 `db_put` 에 그 자리를 함께 넣는다.)

화면 시험("화면 다듬기" 블록 안, `open_company(page, CID)` 로 연 상세):

```python
    wl = page.locator("#detail input[data-feature='wellife']")
    check(wl.count() == 1 and not wl.is_checked() and not wl.is_disabled(), "모듈 정책에 '웰라이프 실행' 체크 (보통 업체는 꺼짐)")
    wl.check(); page.click("#detail button.mod-apply"); page.wait_for_selector("#detail .mod-ok:not(.hide)", timeout=5000)
    check(db_get(f"meta/companies/{CID}/apps/rpa/features/wellife") is True, "[적용] 으로 웰라이프 실행을 켠다")
    open_company(page, CID)
    check(page.is_disabled("#detail input[data-mod='Logistics']") and "웰라이프 업체는 쓰지 않음" in page.text_content("#detail .sec:has(.mod-apply)"),
          "웰라이프 업체: 물류관리·운송장 체크 잠김")
    page.locator("#detail input[data-feature='wellife']").uncheck(); page.click("#detail button.mod-apply"); page.wait_for_timeout(800)
    check(db_get(f"meta/companies/{CID}/apps/rpa/features/wellife") is None, "다시 끈다")
```

- [ ] **Step 2: 실패 확인** - `powershell -File .superpowers/sdd/2026-10-07-wellife-gate/emu.ps1 -Cmd 'python check_admin.py' -Only auth,database,firestore` → 웰라이프 줄 실패

- [ ] **Step 3: 구현** - `ops.js`:

```js
/** 웰라이프 업체인가 - 업체코드에 wellife (대소문자 무관) 또는 관리 화면에서 연 업체. 에이전트(agent.wellife_on)·업체 웹(rpa-common.wellifeOn)과 같은 규칙 */
export const wellifeAuto = (cid) => String(cid ?? "").toLowerCase().includes("wellife");
export const wellifeOn = (cid, features) => wellifeAuto(cid) || features?.wellife === true;
export async function setFeature(cid, key, on) {
  checkKey("cid", cid);
  if (key !== "wellife") throw new Refused(`모르는 기능입니다: ${key}`);
  await companyOf(cid, { removed: true });
  if (!on && wellifeAuto(cid)) throw new Refused("업체코드에 wellife 포함 - 늘 열림 (끌 수 없습니다)");
  const at = rtdb.ref(`meta/companies/${cid}/apps/rpa/features/${key}`);
  await at.set(on ? true : null);
  return { features: (await rtdb.ref(`meta/companies/${cid}/apps/rpa/features`).get()).val() ?? {} };
}
```

`companyDetail` 의 반환 객체에 `features: v.apps?.rpa?.features ?? {}, wellife: wellifeOn(cid, v.apps?.rpa?.features), wellifeAuto: wellifeAuto(cid),` 를 더한다.

`admin.js` ROUTES (`/modules` 줄 다음):

```js
  ["POST", "/api/companies/:cid/features", (b, p) => ops.setFeature(p.cid, "wellife", b.wellife === true),
    (b, r, p) => `웰라이프 실행 ${p.cid} = ${b.wellife === true ? "켬" : "끔"}`],
```

`AFTERMARKET_SETUP.html` `moduleSection` - 체크 줄에 웰라이프 체크를 더하고, [적용] 이 모듈과 함께 보낸다:

```js
  const wl = el("input", { type: "checkbox", "data-feature": "wellife", checked: d.wellife, disabled: d.wellifeAuto });
  const wlBox = el("label", { class: "inline" }, wl, "웰라이프 실행", d.wellifeAuto ? el("span", { class: "muted" }, " (업체코드에 wellife 포함 - 늘 열림)") : "");
  // 웰라이프 업체: 물류관리·운송장 출력 체크는 잠근다 (에이전트가 막는다)
  for (const [k, , cb] of cbs) if (d.wellife && (k === "Logistics" || k === "Output")) cb.disabled = true;
```

[적용] 의 onclick 안, 모듈 POST 다음 줄:

```js
    if (!d.wellifeAuto && wl.checked !== d.wellife) await api("POST", `/api/companies/${d.cid}/features`, { wellife: wl.checked });
```

성공 뒤 `openDetail(d.cid)` 를 부른다 (웰라이프가 바뀌면 잠금이 바뀐다 - 다시 그린 상자에 '반영되었습니다.' 를 보이게 `keep` 대신 그린 뒤 `.mod-ok` 를 2초 보인다). 상자 설명 아래(웰라이프면) `el("p", { class: "muted" }, "웰라이프 업체는 쓰지 않음: 물류관리 · 운송장 출력 / 엑셀 생성")`. 상자 줄은 `el("div", { class: "row" }, boxes, wlBox, apply)`.

- [ ] **Step 4: 통과 확인** - 위 에뮬레이터 명령 → 모두 통과

- [ ] **Step 5: 커밋**

```bash
git add firebase/admin/ops.js firebase/admin/admin.js firebase/admin/AFTERMARKET_SETUP.html firebase/tests/check_admin.py
git commit -m "웰라이프 관문 4: 관리 화면 - 모듈 정책에 '웰라이프 실행' (업체코드에 wellife 면 늘 열림), 웰라이프 업체는 물류관리·운송장 잠금"
```

---

### Task 5: 업체 웹 - 모듈 다섯·'전체' 시각만

**Files:**
- Modify: `firebase/web/rpa-common.js` (`MODULES` 옆), `firebase/web/rpa-settings.js` (`offByCompany`·`shownModules`·`MODULES` 쓰는 곳, `paintTimes`, `sch-add-win`)
- Test: `firebase/tests/check_web.py` (모듈 정책 시험 :528 근처)

**Interfaces:**
- Produces: `rpa-common.WELLIFE_MODULES` (다섯 `[키, 이름]`), `rpa-common.wellifeOn(cid, policy) -> boolean` (`policy` 는 `c.policy` - `policy?.rpa?.features?.wellife === true`).

- [ ] **Step 1: 실패하는 시험** - `check_web.py` 의 `db_patch("meta/companies/c_demo/apps/rpa", {"modules": None})` 줄 다음에:

```python
    db_patch("meta/companies/c_demo/apps/rpa", {"features": {"wellife": True}})
    reload_to(page, "settings"); page.wait_for_selector("#mod-list label")
    names = [x.strip() for x in page.locator("#mod-list label").all_text_contents()]
    check(len(names) == 5 and any("웰라이프 SAP 연동관리" in n for n in names) and any("웰라이프 WMS 이관관리" in n for n in names)
          and not any("물류관리" == n or "운송장" in n for n in names), f"웰라이프 업체: 모듈 다섯 (물류관리·운송장 없음) ({names})")
    check(not page.is_visible("#sch-add-win") and page.locator("#sch-times select.mode").count() == 0,
          "웰라이프 업체: '전체' 시각만 (고르기·반복 시간대 숨김)")
    db_patch("meta/companies/c_demo/apps/rpa", {"features": None})
    reload_to(page, "settings"); page.wait_for_selector("#mod-list label")
    check(page.locator("#mod-list label").count() == 5 and page.locator("#mod-list input[aria-label='물류관리']").count() == 1,
          "보통 업체로 돌아오면 지금 그대로")
```

(`#sch-times select.mode` 는 v2 PC 에서만 보이는 줄 고르기 - 이 시험 블록의 live.schedule 이 v2 가 아니면 `page.locator(...).count() == 0` 은 늘 참이다. 같은 파일의 시각별 모듈 시험이 쓰는 v2 live 를 만드는 방식(`schedule.version: 2`)을 찾아 이 시험 앞에 같은 값을 넣는다.)

판정 함수는 `node` 로 직접 본다 (check_web 이 이미 node 를 부르면 그 방식, 아니면 `subprocess.run(["node", "--input-type=module", "-e", ...])`):

```python
    out = subprocess.run(["node", "--input-type=module", "-e",
        "import { wellifeOn } from './web/rpa-common.js'; console.log(JSON.stringify(["
        "wellifeOn('WELLIFE_x', null), wellifeOn('my_wellife', {}), wellifeOn('wel_life', null),"
        "wellifeOn('c_demo', {rpa: {features: {wellife: true}}}), wellifeOn('c_demo', {rpa: {features: {wellife: false}}})]))"],
        cwd=os.path.join(HERE, ".."), capture_output=True, text=True, encoding="utf-8")
    check(out.stdout.strip() == "[true,true,false,true,false]", f"웹 판정 규칙이 에이전트·관리 화면과 같다 ({out.stdout.strip()} {out.stderr[-200:]})")
```

(`rpa-common.js` 가 브라우저 전용 import(gstatic URL)를 맨 위에서 하면 node 가 못 읽는다 - 그러면 이 판정 시험은 페이지에서 `page.evaluate("import('./rpa-common.js').then(m => ...)")` 로 한다.)

- [ ] **Step 2: 실패 확인** - `powershell -File .superpowers/sdd/2026-10-07-wellife-gate/emu.ps1 -Cmd 'python check_web.py' -Only auth,database,firestore,hosting` → 웰라이프 줄 실패

- [ ] **Step 3: 구현** - `rpa-common.js`, `MODULES` 아래:

```js
// 웰라이프 업체 모듈 (설계 2026-10-07-wellife-gate) - PC 의 Wellife 섹션 키, wellife.MODULES 와 같다
export const WELLIFE_MODULES = [
  ["Login", "로그인"], ["Sales", "주문매핑 매출처리"], ["Hold", "물류대기 관리"],
  ["Sap", "웰라이프 SAP 연동관리"], ["Wms", "웰라이프 WMS 이관관리"],
];
/** 웰라이프 업체인가 - 업체코드에 wellife (대소문자 무관) 또는 관리 화면에서 연 업체. 에이전트·관리 화면과 같은 규칙 */
export const wellifeOn = (cid, policy) => String(cid ?? "").toLowerCase().includes("wellife") || policy?.rpa?.features?.wellife === true;
```

`rpa-settings.js`: import 에 `WELLIFE_MODULES, wellifeOn` 을 더하고

```js
const isWellife = () => wellifeOn(c?.me?.cid, c?.policy);
const modList = () => (isWellife() ? WELLIFE_MODULES : MODULES);
const offByCompany = (k) => !isWellife() && c?.policy?.rpa?.modules?.[k] === false;
const shownModules = () => modList().filter(([k]) => !offByCompany(k));
```

파일 안의 `MODULES.map`·`MODULES.some`·`dict(MODULES)` 를 `modList()` 로 바꾼다 (`NEEDS` 는 웰라이프에 없는 키라 그대로 둬도 된다). `paintTimes` 의 `} else if (isV2()) {` → `} else if (isV2() && !isWellife()) {`, `paintScheduleMeta` 의 `show($("sch-add-win"), isV2());` → `show($("sch-add-win"), isV2() && !isWellife());`.

정책이 로그인 뒤 바뀌어도 따라가게 - 지금 `c.policy` 는 로그인 때 읽은 값이다. 한도 구독(:73, `stopLimit`)과 같은 방식으로 `meta/companies/${cid}/apps/rpa/features` 를 구독해 `c.policy.rpa.features` 를 갈고 `paintModules(); paintTimes(); paintScheduleMeta();` 를 부른다 (떠날 때 `stopFeatures()`).

- [ ] **Step 4: 통과 확인** - 위 에뮬레이터 명령 → 모두 통과

- [ ] **Step 5: 커밋**

```bash
git add firebase/web/rpa-common.js firebase/web/rpa-settings.js firebase/tests/check_web.py
git commit -m "웰라이프 관문 5: 업체 웹 - 웰라이프 업체는 모듈 다섯(물류관리·운송장 없음)·'전체' 시각만"
```

---

### Task 6: 로그인 수정 두 갈래 시험 (PR #2 검토에서 빠진 것)

**Files:**
- Create: `tests/test_login_flow.py`

**Interfaces:**
- Consumes: `perform_login.login_flow(admin_code, user_id, password, log=None)` 와 그 안이 부르는 `find_login_window`·`fill_login_fields`·`click_login_button`·`wait_for_popup`·`collect_text`·`write_error_log`·`win32gui`·`win32process`·`ec.ensure_foreground`·`time.sleep` (시험이 바꿔 끼운다)

- [ ] **Step 1: 시험 쓰기** (코드는 이미 있다 - 이 시험은 PR #2 의 수정을 고정한다. 쓴 뒤 수정 한 줄을 잠시 되돌려 실패하는 것을 확인하고 원래대로):

```python
# -*- coding: utf-8 -*-
"""perform_login.login_flow 의 두 갈래 (PR #2): 재시도 때 숨은 로그인 창은 로그인 창이 아니다, 메인 창이 먼저 뜨면 성공.
진짜 창·키 입력 없이 가짜로."""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import perform_login as pl  # noqa: E402

fails = []


def check(cond, what):
    print(("PASS  " if cond else "FAIL  ") + what)
    if not cond:
        fails.append(what)


class Win:
    def __init__(self, handle):
        self.handle = handle


def run(windows, visible, popup=None, popup_text="", pids=None):
    """windows: find_login_window 가 차례로 돌려줄 창 목록. visible: {handle: 보이나}. pids: {handle: pid}."""
    calls = {"click": 0}
    seq = list(windows)
    pids = pids or {}
    saved = {n: getattr(pl, n) for n in ("find_login_window", "fill_login_fields", "click_login_button", "wait_for_popup",
                                          "collect_text", "write_error_log")}
    saved_mods = (pl.win32gui, pl.win32process, pl.ec, pl.time)
    pl.find_login_window = lambda: seq.pop(0) if seq else None
    pl.fill_login_fields = lambda *a, **k: None
    pl.click_login_button = lambda *a, **k: calls.__setitem__("click", calls["click"] + 1)
    pl.wait_for_popup = lambda w, *a, **k: (popup, [])
    pl.collect_text = lambda w: popup_text
    pl.write_error_log = lambda text: "err.txt"
    pl.win32gui = types.SimpleNamespace(IsWindowVisible=lambda h: visible.get(h, False), IsWindow=lambda h: True)
    pl.win32process = types.SimpleNamespace(GetWindowThreadProcessId=lambda h: (0, pids.get(h, 1)))
    pl.ec = types.SimpleNamespace(ensure_foreground=lambda h: None)
    pl.time = types.SimpleNamespace(sleep=lambda s: None)
    try:
        return pl.login_flow("code", "id", "pw"), calls
    finally:
        for n, v in saved.items():
            setattr(pl, n, v)
        pl.win32gui, pl.win32process, pl.ec, pl.time = saved_mods


print("=== 재시도 때 숨은 로그인 창 ===")
r, calls = run([Win(1), Win(2)], {1: True, 2: False})
check(r["status"] == "success" and calls["click"] == 0, f"숨은 잔재 창은 로그인 창이 아니다 - 누르지 않고 성공 ({r}, {calls})")
r, calls = run([Win(1), Win(1)], {1: True}, popup=Win(9), popup_text="비밀번호가 일치하지 않습니다", pids={1: 7, 9: 7})
check(r["status"] == "popup_error" and calls["click"] == 1, f"보이는 로그인 창은 누르고, 모르는 팝업이면 멈춘다 ({r['status']})")

print("=== 메인 창이 먼저 뜨면 ===")
r, _ = run([Win(1), Win(1)], {1: True, 5: True}, popup=Win(5), popup_text="Accordion Menu | lcg_sales", pids={1: 7, 5: 7})
check(r["status"] == "success", f"같은 ERPia 의 보이는 메인 창 → 성공 ({r['status']})")
r, _ = run([Win(1), Win(1)], {1: True, 5: True}, popup=Win(5), popup_text="Accordion Menu | lcg_sales", pids={1: 7, 5: 8})
check(r["status"] != "success", f"다른 ERPia 의 메인 창은 성공이 아니다 ({r['status']})")
r, _ = run([Win(1), Win(1)], {1: True, 5: False}, popup=Win(5), popup_text="Accordion Menu | lcg_sales", pids={1: 7, 5: 7})
check(r["status"] != "success", f"숨은 메인 창은 성공이 아니다 ({r['status']})")

print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
```

- [ ] **Step 2: 돌려 보기** - `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe tests/test_login_flow.py` → `실패: 없음`. 그 다음 `perform_login.py` 의 `or not win32gui.IsWindowVisible(login_win.handle)` 를 잠시 지우고 다시 돌려 첫 시험이 FAIL 하는지 본 뒤 되돌린다 (git diff 가 비었는지 확인).

- [ ] **Step 3: 커밋**

```bash
git add tests/test_login_flow.py
git commit -m "로그인 두 갈래 시험 (PR #2): 숨은 로그인 창은 안 누름, 같은 ERPia 의 보이는 메인 창만 성공"
```

---

### Task 7: 문서 · 빌드 · 샌드박스

**Files:**
- Modify: `docs/firebase-architecture.md` (웰라이프 관문 한 줄, 시험 표 두 줄), `docs/wellife-rpa.md` (맨 위에 "관문: docs/superpowers/specs/2026-10-07-wellife-gate-design.md - 섹션은 에이전트가 쓴다, 업체코드에 wellife 또는 관리 화면" 한 줄)

- [ ] **Step 1: 문서** - 위 두 곳.
- [ ] **Step 2: 전체 시험** - PC 묶음 전부(`test_wellife_gate test_login_flow test_wellife test_routine_modules test_dashboard_modules test_schedule_slots test_schedule_repeat test_settings test_background test_dashboard_auth test_start_failure test_encoding test_rpa_update test_update_helper test_update_sign test_publish_release check_schedule_ui check_modules_ui agent`), 에뮬레이터 check_admin·check_web·check_setup, `cd firebase/tests && npm test` (규칙).
- [ ] **Step 3: 커밋** - `git commit -m "웰라이프 관문: 문서"`
- [ ] **Step 4: 빌드·샌드박스** (컨트롤러) - `tools/build_release.py` → `tools/sandbox_test.py --update <설치 파일>` → 46/46.
