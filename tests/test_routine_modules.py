"""루틴 RPA 모듈화 시험 - 설정 파싱 / 모듈 상태 기록 / 화면 진입 / 출력 팝업 정책 / 디스패처 / 모듈 함수.

ERPia 없이 돈다. 상태 기록은 임시 폴더로 격리한다 (RPA_STATUS_DIR).

    .venv\\Scripts\\python.exe tests\\test_routine_modules.py
"""
import contextlib
import os
import sys
import tempfile
import time as _time
import types
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="rpa_modules_")
os.environ["RPA_STATUS_DIR"] = _tmp          # rpa_status 가 status_dir() 를 부를 때 이 값을 쓴다
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


def finish():
    print()
    print(f"실패: {'없음' if not fails else fails}")
    sys.exit(1 if fails else 0)


# ---------------------------------------------------------------------------
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

# 운송장번호 전송 (모든 업체용, 2026-10-13): 되돌릴 수 없는 전송이라 칸이 없으면 끔 - 켠 PC 만
import rpa_status as _st  # noqa: E402
import run_routine as _rr  # noqa: E402
ALL = [m[1] for m in _rr.ROUTINE_MODULES]
with_settings({"Routine": {"Login": "Y"}})
sel, _ = pl.load_routine_modules(ALL, _st.ROUTINE_OFF_BY_DEFAULT)
check("운송장번호 전송은 칸이 없으면 끔, 나머지는 켬", "InvoiceSend" in ALL and sel["InvoiceSend"] is False
      and all(v for k, v in sel.items() if k != "InvoiceSend"), f"{sel}")
with_settings({"Routine": {"InvoiceSend": "Y"}})
check("운송장번호 전송은 Y 일 때만 돈다", pl.load_routine_modules(ALL, _st.ROUTINE_OFF_BY_DEFAULT)[0]["InvoiceSend"] is True)
called = []
orig_inv = _rr.wellife.module_invoice_send
_rr.wellife.module_invoice_send = lambda rr, ctx, live: called.append(live) or ("done", None)
# 2026-11-09 사용자: 보통 PROCESS 의 운송장번호 전송은 늘 실행 - 리허설·1건 모드를 없앴다 (업체 PC 가 기본값 리허설로 돌면 운송장이 안 나간다)
for mode in (None, "리허설", "실행", "1건", "yes"):
    called.clear()
    with_settings({"Routine": {"InvoiceSend": "Y", **({"InvoiceMode": mode} if mode else {})}})
    got = _rr.MODULE_FUNCS["invoicesend"](object())
    check(f"보통 PROCESS 의 운송장번호 전송: Routine.InvoiceMode {mode or '없음'} 이어도 늘 실행 (옛 값은 읽지 않는다, 2026-11-09)",
          called == [True] and got == ("done", None), f"{called} {got}")
for trigger in ("repeat", "auto"):
    called.clear()
    with_settings({"Routine": {"InvoiceSend": "Y"}})
    os.environ["RPA_RUN_TRIGGER"] = trigger
    try:
        _rr.MODULE_FUNCS["invoicesend"](object())
    finally:
        os.environ.pop("RPA_RUN_TRIGGER", None)
    check(f"{trigger} 회차도 실행으로 돈다 ('1건' 멈춤 없음)", called == [True], f"{called}")
_rr.wellife.module_invoice_send = orig_inv
check("Routine 에 남은 옛 InvoiceMode 는 모르는 키 경고에서 빠진다 (값은 안 쓴다)", "InvoiceMode" in _rr.ROUTINE_MODE_KEYS and _st.ROUTINE_MODES == ())
check("운송장번호 전송은 웰라이프와 같은 키·비트 512", ("invoicesend", "InvoiceSend", "운송장번호 전송", ("inv_send_screen", "inv_send"), 512)
      in _rr.ROUTINE_MODULES and any(m[0] == "invoicesend" and m[4] == 512 for m in _rr.wellife.MODULES))

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

with_settings({"LogIn": {"AdminCode": "x", "Routine": "Y"}})
try:
    pl.load_routine_modules(KEYS)
    check("섹션을 스칼라로 잘못 쓰면 RuntimeError", False, "예외 없음")
except RuntimeError as e:
    check("섹션을 스칼라로 잘못 쓰면 RuntimeError", "Routine" in str(e), str(e))

with_settings({"LogIn": {"AdminCode": "x"}, "Routine": "Y"})    # RPA_UserConfig.json 에서 섹션 자리에 값을 쓴 경우
try:
    pl.load_routine_modules(KEYS)
    check("새 파일에서 섹션 자리에 값을 써도 RuntimeError", False, "예외 없음")
except RuntimeError as e:
    check("새 파일에서 섹션 자리에 값을 써도 RuntimeError", "Routine" in str(e) and "섹션" in str(e), str(e))

# ---------------------------------------------------------------------------
import rpa_status as st  # noqa: E402

print()
print("=== 2. 모듈 상태 기록 (rpa_status) ===")
MODS = [("login", "로그인", ("login",), 1),
        ("sales", "매출", ("order_screen", "sales"), 2),
        ("hold", "물류대기", ("hold_screen", "hold_save"), 4)]
STEPS = [("login", "로그인"), ("order_screen", "화면"), ("sales", "정상매출"),
         ("hold_screen", "이동"), ("hold_save", "저장")]
st.start("routine", STEPS)
st.set_modules(MODS)
s = st._state
check("모듈 3개 등록, 비트는 넘긴 값 그대로", [m["bit"] for m in s["modules"]] == [1, 2, 4], str([m["bit"] for m in s["modules"]]))
check("처음엔 module_flags 0", s["module_flags"] == 0)
check("schema 2", s["schema"] == 2)

st.module_start("login")
st.step("login")
st.module_done("login", "done")
check("login done -> 비트 1", s["module_flags"] == 1, str(s["module_flags"]))
check("login 단계도 done 으로 닫힘", st._find_step("login")["state"] == "done")

st.module_start("sales")
st.step("order_screen")
st.progress(2, 5, "2/5")
check("progress pct 40", s["modules"][1]["progress"]["pct"] == 40, str(s["modules"][1]["progress"]))
st.progress(12, 10)
check("progress pct 는 100 을 넘지 않는다", s["modules"][1]["progress"]["pct"] == 100)
st.step("sales")
check("다음 step() 이면 progress 초기화", s["modules"][1]["progress"] is None)
st.progress(4, 5)
st.module_done("sales", "no_target", "대상 없음")
check("no_target 도 완료 비트 (1|2=3)", s["module_flags"] == 3, str(s["module_flags"]))
check("사유 저장", s["modules"][1]["reason"] == "대상 없음")

st.module_off("hold", "설정에서 끔")
st.skip("hold_screen", "설정에서 끔")
st.skip("hold_save", "설정에서 끔")
check("off 는 비트 안 세움", s["module_flags"] == 3 and s["modules"][2]["state"] == "off")

rec = st.history_record(s)
check("이력에 modules/module_flags/schema2", rec.get("module_flags") == 3 and len(rec.get("modules") or []) == 3 and rec["schema"] == 2)
check("이력의 modules 는 화이트리스트 (steps 목록 없음)", "steps" not in rec["modules"][0] and rec["modules"][1]["progress"] == {"value": 4, "total": 5, "pct": 80})

view = st.decorate(s)
m1, m2 = view["modules"][1], view["modules"][2]
check("decorate: 모듈별 steps_done/total", m1["steps_total"] == 2 and m1["steps_done"] == 2, str(m1))
check("decorate: 완료 모듈은 progress 가 남아 있어도 100", m1["pct"] == 100, str(m1["pct"]))
check("decorate: off 모듈은 pct None", m2["pct"] is None, str(m2["pct"]))

st.start("routine", [("login", "로그인"), ("hold_save", "저장")])
st.set_modules(MODS)
st.module_start("hold")
st.step("hold_save")
st.module_done("hold", "failed", "그리드 없음")
check("failed 는 비트 0", st._state["module_flags"] == 0)
check("failed 면 running 단계가 failed", st._find_step("hold_save")["state"] == "failed")
st.module_done("없는키", "done")
check("모르는 모듈 키는 무시", st._state["module_flags"] == 0)

st.start("routine", [("login", "로그인")])
st.set_modules(MODS)
st.module_start("login")
st.finish("crashed", "예외")
check("finish(crashed) 가 running 모듈을 failed 로", st._state["modules"][0]["state"] == "failed")

st.start("routine", [("login", "로그인")])
st.set_modules(MODS)
st.module_start("login")
st.step("login")
st.finish("success")
check("finish(success) 가 running 모듈을 done 으로 닫으면 비트도 세운다", st._state["modules"][0]["state"] == "done" and st._state["module_flags"] == 1, str(st._state["module_flags"]))
check("last_problem() 이 있다", callable(getattr(st, "last_problem", None)))
os.environ["RPA_RUN_TRIGGER"] = "repeat"
st.start("routine", [("login", "로그인")])
check("시작할 때 RPA_RUN_TRIGGER 를 trigger 로", st._state["trigger"] == "repeat" and st.history_record(st._state)["trigger"] == "repeat")
os.environ.pop("RPA_RUN_TRIGGER")
hist = os.path.join(_tmp, "history.jsonl")
lines = lambda: len(open(hist, encoding="utf-8").read().splitlines()) if os.path.exists(hist) else 0
n0 = lines()
st.set_modules(MODS); st.module_start("login"); st.module_done("login", "done")
check("done_modules: 완료 모듈 키", st.done_modules() == ["login"])
st.finish("success", record=False)
check("record=False 면 이력에 안 쓴다 (상태 파일은 끝남)", lines() == n0 and st.read_json(st.status_path("routine"))["state"] == "success")
st.start("routine", [("login", "로그인")]); st.finish("success")
check("평소엔 이력에 쓴다 (사람이 띄우면 trigger 없음)", lines() == n0 + 1 and __import__("json").loads(open(hist, encoding="utf-8").read().splitlines()[-1]).get("trigger") is None)

# ---------------------------------------------------------------------------
import run_routine as rr  # noqa: E402

_real_find_by_text = rr.find_by_text      # 죽은 핸들 시험에서 진짜를 쓴다
# 누르기 안전장치(press - 잠김·앞으로·덮개)는 맨 끝 절에서 따로 본다. 그 앞 흐름 시험의 가짜 요소는 예전처럼 바로 누른다
_real_press = rr.press
_real_wait_tab = rr.wait_for_active_main_tab     # 따로 뜬 팝업 시험에서 진짜를 쓴다 (앞 절이 바꿔 끼운다)
_real_ok_button, _real_popup_buttons = rr.find_popup_ok_button, rr.find_popup_buttons    # 창 안 단추만 고르는지 끝 절에서 본다
_real_print_preview = rr.run_print_preview       # 9절이 가짜로 바꾼다 - 미리보기 닫기 시험(끝 절)에서 진짜를 쓴다
rr.press = lambda hwnd, el, what, coords=None, double=False, popup=False, work=False, **kw: (el.double_click_input if double else el.click_input)(
    **({"coords": coords} if coords is not None else {}), **kw)
_real_handle_print_popups = rr.handle_print_popups   # 9절에서 진짜를 쓴다
_real_run_print_step = rr.run_print_step             # 6절이 가짜로 바꾸므로 9절에서 되살린다
_real_run_logistics_step = rr.run_logistics_step     # 7절이 가짜로 바꾸므로 8절에서 되살린다
_real_run_hold_logistics_step = rr.run_hold_logistics_step   # 8절이 가짜로 바꾸므로 조회 대기 시험(A13)에서 진짜를 쓴다

# R6 (2026-11-03): ERPia 는 이 윈도우 세션 것만 센다 - 다른 계정의 ERPia 는 창을 잡지도 끄지도 못한다. 세션을 못 읽으면 예전처럼
_real_ec = rr.ec
_queries = []
_orig_get = _real_ec.win32com.client.GetObject
_real_ec.win32com.client.GetObject = lambda name: types.SimpleNamespace(ExecQuery=lambda q: _queries.append(q) or [])
_real_ec.erpia_pids()
_orig_sid = _real_ec.session_id
_real_ec.session_id = lambda: None
_real_ec.erpia_pids()
_real_ec.session_id = _orig_sid
_real_ec.win32com.client.GetObject = _orig_get
check("ERPia 프로세스는 이 세션 것만 (세션을 못 읽으면 이름만)",
      len(_queries) == 2 and f"SessionId={_orig_sid()}" in _queries[0] and "SessionId" not in _queries[1], str(_queries))

print()
print("=== 3. 모듈 표 / 컨텍스트 / 화면 진입 ===")
rr.time = types.SimpleNamespace(sleep=lambda *_: None, time=_time.time, strftime=_time.strftime)
# 화면 이동 뒤 표 기다림(wellife.wait_tables)은 진짜 시계로 돈다 - 이 파일은 표를 가짜로 주므로 표 수가 안 맞으면 화면 이동마다 15초,
# 맞아도 1초씩 기다렸다 (11-25 실측: 246초 중 180초). 기다림 자체는 test_wellife 가 본다 - 여기서는 짧게만 (확인하는 것은 그대로)
rr.wellife.TABLE_WAIT_SECONDS, rr.wellife.TABLE_STABLE_SECONDS = 0.3, 0.05
rr.ec = types.SimpleNamespace(ensure_foreground=lambda *a, **k: True, find_erpia_pid=lambda: 4242,
                              process_elevated=lambda pid: False, pid_alive=lambda pid: True, erpia_pids=lambda: [],
                              erpia_pids_titled=lambda title: [4242])     # 설정 계정 제목의 ERPia (사용자 2026-11-16)
_real_log = rr.log     # 진짜 log - cloud=False 시험 (검토 11-25)
rr.log = lambda msg="", **_k: None
rr.win32gui = types.SimpleNamespace(IsWindow=lambda h: True, IsWindowVisible=lambda h: True,
                                    PostMessage=lambda h, m, w, l: None)


class FakeEl:
    def __init__(self):
        self.clicked = 0

    def rectangle(self):
        return "rect"

    def click_input(self):
        self.clicked += 1


class FakeWin:
    def rectangle(self):
        return "rect"

    def descendants(self, control_type=None):
        return []


_real_attach = rr.RoutineContext.attach   # 5절이 가짜로 바꾸므로 13절에서 되살린다
_real_run_modules = rr.run_modules        # 10절 뒤로 가짜로 바뀐다


def make_ctx():
    ctx = rr.RoutineContext()
    ctx.pid, ctx.hwnd = 4242, 777
    ctx.app = types.SimpleNamespace(window=lambda handle: FakeWin())
    return ctx


check("ROUTINE_MODULES 는 8개 (운송장번호 전송 2026-10-13, 주문매핑 셋 2026-10-30 모든 업체로)",
      [m[0] for m in rr.ROUTINE_MODULES] == ["login", "import", "excel", "sales", "hold", "logistics", "output", "invoicesend"])
check("비트는 1/2/4/8/16 고정 + 자동 수집 2048·엑셀 수집 1024·운송장번호 전송 512 (웰라이프와 같은 비트)",
      [m[4] for m in rr.ROUTINE_MODULES] == [1, 2048, 1024, 2, 4, 8, 16, 512], str([m[4] for m in rr.ROUTINE_MODULES]))
check("설정 키 순서가 rpa_status.ROUTINE_CONFIG_MODULES 와 같다 (웹·설정 창 순서)",
      [m[1] for m in rr.ROUTINE_MODULES] == [k for k, _ in st.ROUTINE_CONFIG_MODULES])
for mode, want in ((None, ["import", "excel"]), ("excel_import", ["import", "excel"]), ("excel", ["excel", "import"])):
    rr.TOGETHER_MODE = mode
    order = [m[0] for m in rr.routine_modules()]
    check(f"실행 순서 (함께 실행 {mode}): " + " -> ".join(want) + " -> 매출처리 (예전 sales_flow 차례 그대로)",
          [k for k in order if k in ("import", "excel")] == want and order.index("sales") == 3 and len(order) == 8, str(order))
rr.TOGETHER_MODE = None
steps_keys = [k for k, _ in rr.ROUTINE_STEPS]
check("logistics_screen 단계가 logistics 앞에", steps_keys.index("logistics_screen") + 1 == steps_keys.index("logistics"))
check("모듈 단계 키를 모두 합치면 ROUTINE_STEPS 와 같다", sorted(k for m in rr.ROUTINE_MODULES for k in m[3]) == sorted(steps_keys))

rr.find_by_text = lambda win, key, control_types=(): None
check("아이콘 없음 -> absent", rr.goto_screen_by_icon(make_ctx(), "lcg_X", "엑스", "엑스", wait_seconds=2) == "absent")
# R7 (2026-11-03): 번호 붙은 같은 화면 탭이 있으면 아이콘이 안 잡혀 'absent'(메뉴 없는 업체 = 건너뜀·성공)로 오판했다 - 찾지 않고 failed
_saved_nt = rr.wellife.numbered_tabs
rr.wellife.numbered_tabs = lambda ctx: ["물류대기 관리 (2)"]
looked = []
rr.find_by_text = lambda win, key, control_types=(): looked.append(key)
check("번호 붙은 탭이 있으면 아이콘을 찾지 않고 failed", rr.goto_screen_by_icon(make_ctx(), "lcg_X", "엑스", "엑스", wait_seconds=2) == "failed"
      and looked == [])
_saved_gh = rr.goto_hold_screen
rr.goto_hold_screen = lambda ctx: "failed"
res = rr.module_hold(make_ctx())
check("물류대기 실패 사유에 '여러 개 열려' 안내", res[0] == "failed" and "여러 개 열려" in res[1] and "(2)" in res[1], str(res))
rr.goto_hold_screen = _saved_gh
rr.wellife.numbered_tabs = _saved_nt
rr.find_by_text = lambda win, key, control_types=(): None

el = FakeEl()
rr.find_by_text = lambda win, key, control_types=(): el
rr.wait_for_active_main_tab = lambda app, hwnd, kw, timeout=20, interval=1.0, ctx=None: (True, "엑스 관리")
check("아이콘 클릭 + 탭 확인 -> ok", rr.goto_screen_by_icon(make_ctx(), "lcg_X", "엑스", "엑스") == "ok" and el.clicked == 1)

rr.wait_for_active_main_tab = lambda app, hwnd, kw, timeout=20, interval=1.0, ctx=None: (False, "다른탭")
check("클릭했지만 진입 확인 실패 -> failed", rr.goto_screen_by_icon(make_ctx(), "lcg_X", "엑스", "엑스") == "failed")


def raising(win, key, control_types=()):
    raise RuntimeError("COMError 흉내")


# ERPia 가 로그인 직후 스스로 업데이트해 다시 켜지면 PID 가 바뀐다 (triif 2026-11-13 09:01) - 새 PID 의 창을 잡아야 한다
_real_acquire = rr.acquire_main_window
_EC_NAMES = ("pid_alive", "find_erpia_pid", "wait_for_main_hwnd", "ensure_foreground", "erpia_pids_titled", "erpia_pids")
_saved_ec = {n: getattr(rr.ec, n, None) for n in _EC_NAMES}
_saved_cred3 = (rr.pl.load_credentials, rr.pl.load_account)
rr.pl.load_credentials = lambda: ("업체", "아이디", "비번")
rr.pl.load_account = lambda: ("업체", "아이디")
_saved_acq = (rr.is_main_app_window, rr.Application, rr.time.sleep)
seen_pids = []


def _wait_hwnd(pid, timeout=5):
    seen_pids.append(pid)
    if pid == 7828:
        raise RuntimeError("텍스트가 있는 최상위 창을 찾지 못했습니다.")
    return 555


rr.ec.pid_alive = lambda pid: pid != 7828
rr.ec.erpia_pids_titled = lambda title: [15260] if title == "업체 - 아이디" else []     # 다시 켜진 우리 ERPia (설정 계정 제목)
rr.ec.erpia_pids = lambda: [15260]
rr.ec.wait_for_main_hwnd = _wait_hwnd
rr.is_main_app_window = lambda h, errors=None: h == 555
rr.ec.ensure_foreground = lambda h: True
rr.Application = lambda backend=None: types.SimpleNamespace(connect=lambda handle: types.SimpleNamespace(window=lambda handle: FakeWin()))
rr.time.sleep = lambda s: None
r = _real_acquire(7828)
check("PID 가 끝났으면 새 ERPia PID 로 메인 창을 잡는다 (PID 7828 -> 15260)", r[0] == 555 and r[3] == 15260 and 7828 not in seen_pids, str((r, seen_pids)))
ctx = make_ctx()
ctx.pid = 7828
check("refresh 가 바뀐 PID 를 ctx 에 남긴다", ctx.refresh() and ctx.pid == 15260 and ctx.hwnd == 555, str((ctx.pid, ctx.hwnd)))
_next_pid = iter(range(20000, 30000))
_calls = []
rr.ec.pid_alive = lambda pid: False                       # 계속 꺼졌다 켜지는 ERPia - 볼 때마다 새 PID
rr.ec.erpia_pids_titled = lambda title: _calls.append(1) or [next(_next_pid)]
rr.ec.wait_for_main_hwnd = lambda pid, timeout=5: (_ for _ in ()).throw(RuntimeError("창 없음"))
r = _real_acquire(7828, tries=12)
rr.ec.wait_for_main_hwnd = _wait_hwnd
check("ERPia 가 끝없이 다시 켜져도 PID 바꿔 다시 세기는 3번까지라 끝난다 (12 x 4 = 48번 안)",
      r[0] is None and len(_calls) <= 12 * (rr.PID_SWITCH_MAX + 1), str(len(_calls)))
rr.ec.pid_alive = lambda pid: pid != 7828
rr.ec.erpia_pids_titled = lambda title: []                # 다른 계정 ERPia(9999)만 떠 있다 - 그리로 갈아타지 않는다 (검토 2026-11-16)
rr.ec.erpia_pids = lambda: [9999]
seen_pids.clear()
r = _real_acquire(7828, tries=3)
check("PID 가 끝나도 다른 계정 ERPia 로는 갈아타지 않는다 (사람이 쓰는 ERPia 를 조작하지 않게, 검토 2026-11-16)",
      r[0] is None and 9999 not in seen_pids, str((r, seen_pids)))
rr.ec.erpia_pids = lambda: [9999, 16000]                  # 시작할 때 있던 남의 9999 는 빼고, 그 뒤 새로 뜬 16000 은 우리 것 (자체 업데이트)
seen_pids.clear()
r = _real_acquire(7828, tries=3, others={9999})
check("시작할 때 없던 새 ERPia 는 우리 것으로 따라간다 (로그인 전 자체 업데이트로 다시 켜짐)", 16000 in seen_pids and 9999 not in seen_pids, str(seen_pids))
_saved_li = rr.erpia_logged_in
rr.erpia_logged_in = lambda pid: pid == 16000             # 새로 떴지만 다른 계정으로 로그인돼 있다 - 실행 중에 사람이 띄운 것
seen_pids.clear()
r = _real_acquire(7828, tries=3, others={9999})
rr.erpia_logged_in = _saved_li
check("새로 떴어도 다른 계정으로 로그인된 ERPia 로는 갈아타지 않는다 (검토 2026-11-17)", r[0] is None and 16000 not in seen_pids, str(seen_pids))
rr.ec.erpia_pids = lambda: []
logs = []
_saved_log = rr.log
rr.log = logs.append
r = _real_acquire(7828, tries=3)
rr.log = _saved_log
check("ERPia 가 아예 없으면 시도 횟수 안에서 끝나고 진단 줄을 남긴다", r[:3] == (None, None, None) and any("메인 창 진단" in x for x in logs), str(logs[-1:]))
rr.ec.pid_alive = lambda pid: True
rr.is_main_app_window = lambda h, errors=None: (errors.append(RuntimeError("이벤트에서 가입자를 불러낼 수 없습니다")) if errors is not None else None) and False
logs = []
rr.log = logs.append
r = _real_acquire(4242, tries=2)
rr.log = _saved_log
check("메뉴 확인 중 난 오류를 진단 줄에 남긴다 (예전엔 삼켜서 72초 동안 흔적이 없었다)",
      r[0] is None and any("메뉴 확인 오류 2번" in x and "가입자" in x for x in logs), str(logs[-1:]))
rr.is_main_app_window, rr.Application, rr.time.sleep = _saved_acq
rr.pl.load_credentials, rr.pl.load_account = _saved_cred3
for _n, _v in _saved_ec.items():
    if _v is None:
        delattr(rr.ec, _n)
    else:
        setattr(rr.ec, _n, _v)

rr.find_by_text = raising
rr.acquire_main_window = lambda pid, tries=12, others=None: (778, types.SimpleNamespace(window=lambda handle: FakeWin()), FakeWin(), pid)
check("예외만 나다 끝나면 absent 가 아니라 failed", rr.goto_screen_by_icon(make_ctx(), "lcg_X", "엑스", "엑스", wait_seconds=4) == "failed")


# 죽은 핸들: find_by_text 는 예외를 삼키고 None 을 주므로 (진짜 함수로 시험) rectangle() probe 가 잡아야 한다
class DeadWin:
    def rectangle(self):
        raise RuntimeError("COMError 흉내")

    def descendants(self, control_type=None):
        raise RuntimeError("COMError 흉내")


class NamedEl(FakeEl):
    def window_text(self):
        return "lcg_X"


class LiveWin:
    def __init__(self, el):
        self.el = el

    def rectangle(self):
        return "rect"

    def descendants(self, control_type=None):
        return [self.el]


el = NamedEl()
rr.find_by_text = _real_find_by_text
rr.win32gui.IsWindow = lambda h: h != 777
rr.acquire_main_window = lambda pid, tries=12, others=None: (778, types.SimpleNamespace(window=lambda handle: LiveWin(el)), LiveWin(el), pid)
rr.wait_for_active_main_tab = lambda app, hwnd, kw, timeout=20, interval=1.0, ctx=None: (True, "엑스 관리")
ctx = make_ctx()
ctx.app = types.SimpleNamespace(window=lambda handle: DeadWin())
r = rr.goto_screen_by_icon(ctx, "lcg_X", "엑스", "엑스", wait_seconds=5)
check("죽은 핸들은 absent 가 아니라 창을 다시 잡고 진입 (진짜 find_by_text)", r == "ok" and ctx.hwnd == 778 and el.clicked == 1, str((r, ctx.hwnd, el.clicked)))
el = type("OrderEl", (FakeEl,), {"window_text": lambda self: "lcg_OrderCollect"})()
ctx = make_ctx()
ctx.app = types.SimpleNamespace(window=lambda handle: DeadWin())
_real_icon = rr.goto_screen_by_icon
rr.goto_screen_by_icon = lambda ctx_, key, label, tab, wait_seconds=30: _real_icon(ctx_, key, label, tab, wait_seconds=5)
r = rr.goto_order_screen(ctx)
rr.goto_screen_by_icon = _real_icon
check("K1: 주문매핑 이동도 죽은 핸들이면 창을 다시 잡고 진입 (예전엔 30초 None 만 받다 실패)", r == (True, None) and ctx.hwnd == 778 and el.clicked == 1,
      str((r, ctx.hwnd, el.clicked)))
rr.win32gui.IsWindow = lambda h: True

check("goto_hold_screen 은 lcg_HoldLogistics", "lcg_HoldLogistics" in rr.goto_hold_screen.__doc__)
check("goto_logistics_screen 은 lcg_Logistics", "lcg_Logistics" in rr.goto_logistics_screen.__doc__)
check("goto_logistics(폴백형) 는 없어졌다", not hasattr(rr, "goto_logistics"))
check("run_hold_save_and_goto_logistics 도 없어졌다", not hasattr(rr, "run_hold_save_and_goto_logistics"))

rr.pl = types.SimpleNamespace(find_login_window=lambda pid=None: None, load_logistic_options=lambda: {},
                              load_credentials=lambda: ("업체", "아이디", "비번"), load_account=lambda: ("업체", "아이디"),
                              ROUTINE_SECTION="Routine",
                              load_hold_save_only=lambda: pl.load_hold_save_only(), HOLD_SAVE_ONLY_KEY=pl.HOLD_SAVE_ONLY_KEY)
ctx = make_ctx()
rr.acquire_main_window = lambda pid, tries=12, others=None: (None, None, None, pid)
ok, reason = ctx.attach()
check("attach: 메인 창 못 잡으면 (False, 사유)", ok is False and "메인 화면" in reason, str(reason))
rr.acquire_main_window = lambda pid, tries=12, others=None: (999, "app", "win", pid)
ok, reason = ctx.attach()
check("attach: 성공하면 hwnd 갱신", ok is True and ctx.hwnd == 999 and ctx.pid == 4242)
rr.pl.find_login_window = lambda pid=None: types.SimpleNamespace(handle=1)     # 로그인 뒤 숨은 채 남는 잔재 창
rr.win32gui.IsWindowVisible = lambda h: False
ok, reason = ctx.attach()
check("attach: 숨은 로그인 잔재 창은 무시하고 붙는다", ok is True, str(reason))
rr.win32gui.IsWindowVisible = lambda h: True
ok, reason = ctx.attach()
check("attach: 보이는 로그인 창이면 즉시 안내", ok is False and "로그인 창" in reason, str(reason))
rr.pl.find_login_window = lambda pid=None: None
rr.ec.erpia_pids_titled = lambda title: []
ok, reason = ctx.attach()
check("attach: 설정 계정 ERPia 가 없으면 로그인 모듈 안내", ok is False and "로그인 모듈" in reason, str(reason))
rr.ec.erpia_pids = lambda: [9999]
ok, reason = ctx.attach()
check("attach: 다른 계정 ERPia 만 떠 있으면 거기에 붙지 않는다 (검토 2026-11-16)", ok is False and "건드리지 않습니다" in reason, str(reason))
rr.ec.erpia_pids, rr.ec.erpia_pids_titled = (lambda: []), (lambda title: [4242])

# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
print()
print("=== 5. 디스패처 (run_modules) ===")


class StatusRec:
    """rr.status 대역. 무엇이 어떤 순서로 불렸는지 기록한다. 모든 함수는 None 을 돌려준다."""

    OFF_NOTE = "설정에서 끔"     # 상수는 진짜 값으로 (run_modules 가 status.OFF_NOTE 를 읽는다)
    PICK_NOTE = "이번 실행에서 안 고름"

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def f(*a, **k):
            self.calls.append((name,) + a + ((k,) if k else ()))
            return None
        return f

    def of(self, name):
        return [c[1:] for c in self.calls if c[0] == name]


def run(selected, results, attach=(True, None), admin_off=()):
    """모듈 함수를 가짜로 바꿔 디스패처만 돌린다. results: {모듈키: (result, reason)}. admin_off: 관리자가 끈 모듈 (settings.json policy.off)"""
    rec = StatusRec()
    if admin_off:
        rec.read_settings = lambda: {"schedule": {"policy": {"off": list(admin_off)}}}
    rr.status = rec
    called = []
    attach_calls = []

    def fake(key):
        def f(ctx):
            called.append(key)
            res = results.get(key, ("done", None))
            if key == "login" and res[0] == "done":
                # 실제 module_login 은 refresh() 가 성공해야 done 을 돌려준다 (= hwnd 가 채워진다)
                ctx.pid, ctx.hwnd = 4242, 777
                ctx.app = types.SimpleNamespace(window=lambda handle: FakeWin())
            return res
        return f

    def fake_attach(self):
        attach_calls.append(1)
        ok, reason = attach
        if ok:
            self.pid, self.hwnd = 4242, 777
            self.app = types.SimpleNamespace(window=lambda handle: FakeWin())
        return ok, reason

    rr.MODULE_FUNCS = {k: fake(k) for k in ("login", "import", "excel", "sales", "hold", "logistics", "output")}
    rr.RoutineContext.attach = fake_attach
    out = rr.run_modules(selected)
    return out, called, rec, attach_calls


ALL_ON = {"Login": True, "Import": True, "Excel": True, "Sales": True, "Hold": True, "Logistics": True, "Output": True}
ALL7 = ["login", "import", "excel", "sales", "hold", "logistics", "output"]
out, called, rec, ac = run(ALL_ON, {})
check("전부 켜면 7개 순서대로", called == ALL7, str(called))
check("전부 done 이면 success", out == ("success", None), str(out))
check("module_done 7번 전부 done", [r[1] for r in rec.of("module_done")] == ["done"] * 7)
check("로그인이 켜져 있으면 attach 안 부름", ac == [])

out, called, rec, ac = run({**ALL_ON, "Sales": False, "Hold": False}, {})
check("끈 모듈은 부르지 않는다 (주문매핑만 끄면 수집은 돈다)", called == ["login", "import", "excel", "logistics", "output"], str(called))
check("끈 모듈은 module_off (칸이 없는 운송장번호 전송도 끔)", [r[0] for r in rec.of("module_off")] == ["sales", "hold", "invoicesend"])
skipped = rec.of("skip")
check("끈 모듈의 단계는 '설정에서 끔' 으로 skip", len(skipped) == 8 and all(s[1] == "설정에서 끔" for s in skipped), str(skipped))
out, called, rec, ac = run(ALL_ON, {}, admin_off=("Hold",))
check("관리자가 끈 모듈은 PC 설정에서 켜 있어도 [실행] 단추·'전체' 줄(모듈을 고르지 않은 실행)에서 돌지 않는다 (검토 2026-11-16)",
      "hold" not in called and "logistics" in called and "hold" in [r[0] for r in rec.of("module_off")], str(called))
logged = []
rr.log = lambda msg="", **_k: logged.append(msg)
os.environ["RPA_RUN_MODULES"] = "Logistics,Output"
try:
    out, called, rec, ac = run({**ALL_ON, "Sales": False, "Hold": False}, {})
finally:
    os.environ.pop("RPA_RUN_MODULES", None)
    rr.log = lambda msg="", **_k: None
skipped = rec.of("skip")
check("예약이 고른 실행이면 안 고른 모듈은 '이번 실행에서 안 고름' (설정과 상관없다)",
      len(skipped) == 8 and all(s[1] == "이번 실행에서 안 고름" for s in skipped)
      and [r[1] for r in rec.of("module_off")] == ["이번 실행에서 안 고름"] * 3, str(skipped))
check("로그도 '이번 실행에서 고르지 않아 건너뜁니다'",
      any("[주문매핑 매출처리] 이번 실행에서 고르지 않아 건너뜁니다" in m for m in logged) and not any("설정에서 꺼져" in m for m in logged), str(logged[:3]))

out, called, rec, ac = run({**ALL_ON, "Login": False}, {})
check("로그인을 끄면 ERPia 에 붙어서 계속", called == ALL7[1:] and out[0] == "success", str(called))
check("attach 는 한 번만", ac == [1], str(ac))
out, called, rec, ac = run({**ALL_ON, "Login": False}, {}, attach=(False, "ERPia 가 실행되어 있지 않습니다."))
check("붙기 실패면 아무 모듈도 안 돌고 stopped", called == [] and out[0] == "stopped" and "ERPia" in out[1], str(out))
check("붙기 실패는 그 모듈의 첫 단계에 실패로 보인다", rec.of("step") == [("order_screen",)] and rec.of("module_done")[-1][:2] == ("import", "failed"), str(rec.of("step")))
check("rpa_status.OFF_NOTE 가 있고 run_routine 에 리터럴이 없다",
      st.OFF_NOTE == "설정에서 끔" and '"설정에서 끔"' not in Path(rr.__file__).read_text(encoding="utf-8"))
check("rpa_status.PICK_NOTE 도 같은 자리에", st.PICK_NOTE == "이번 실행에서 안 고름" and set(st.OFF_NOTES) == {st.OFF_NOTE, st.PICK_NOTE})

out, called, rec, ac = run(ALL_ON, {"hold": ("failed", "그리드 없음")})
check("failed 면 뒤 모듈 안 돌고 stopped", called == ALL7[:5] and out == ("stopped", "그리드 없음"), str((called, out)))
out, called, rec, ac = run(ALL_ON, {"sales": ("stopped", "매출처리 실패: x")})
check("stopped 도 멈춘다", called == ALL7[:4] and out[0] == "stopped")
# 반복 회차: 처리를 시작하기 전에 멈추면 그 회차만 건너뛴다고 사유·로그에, 처리 도중이면 반복을 멈춘다고 로그에 (사용자 2026-11-24)
logged = []
rr.log = lambda msg="", **_k: logged.append(msg)
os.environ["RPA_RUN_TRIGGER"] = "repeat"
_saved_dw, rr.ERPIA_DYING_WAIT_SECONDS = rr.ERPIA_DYING_WAIT_SECONDS, 0.1   # 'UI 오류' 실패는 꺼지는 중을 기다린다 - 여기서는 짧게 (11-25 실측 5초)
try:
    StatusRec.failed_before_work = lambda self: True        # 판정은 rpa_status.failed_before_work (test_dashboard_modules 가 본다)
    out, called, rec, ac = run(ALL_ON, {"import": ("failed", "조회가 끝나지 않음")})
    check("반복 회차가 처리 전에 멈추면 사유에 '이번 회차만 건너뛰고 다시 합니다'",
          out[0] == "stopped" and out[1].startswith("조회가 끝나지 않음 (반복 회차: ERPia 자료를 바꾸기 전에 멈춰서 이번 회차만 건너뛰고")
          and any("처리를 시작하기 전 단계에서 멈춰 이번 회차만 건너뜁니다" in m for m in logged), str(out))
    logged.clear()
    StatusRec.failed_before_work = lambda self: False   # 잠김은 처리 전이어도 반복을 멈춘다 (REPEAT_STOP_TEXTS - test_dashboard_modules)
    out, called, rec, ac = run(ALL_ON, {"import": ("stopped", "5-1: 윈도우 화면이 잠겨 있어 누르지 않고 중단하였습니다.")})
    check("화면이 잠겨 멈춘 회차는 반복을 멈춘다고 로그에 (사용자 11-25 - 예전엔 그 회차만 건너뜀)",
          out == ("stopped", "5-1: 윈도우 화면이 잠겨 있어 누르지 않고 중단하였습니다.")
          and any("[자동 수집] 화면이 잠겨 반복을 멈춥니다" in m for m in logged), str(out))
    logged.clear()
    StatusRec.worked = lambda self: True
    out, called, rec, ac = run(ALL_ON, {"import": ("failed", "가져오기 끝을 못 봄")})
    check("처리 도중이면 사유는 그대로, 로그에 '처리 도중 실패해 반복을 멈춥니다'",
          out == ("stopped", "가져오기 끝을 못 봄") and any("[자동 수집] 처리 도중 실패해 반복을 멈춥니다" in m for m in logged), str(out))
    logged.clear()
    del StatusRec.worked
    out, called, rec, ac = run(ALL_ON, {"import": ("failed", "UI 오류: KeyError")})
    check("처리 전이어도 저절로 풀리지 않는 실패면 '저절로 풀리지 않는 실패라 반복을 멈춥니다'",
          out == ("stopped", "UI 오류: KeyError") and any("저절로 풀리지 않는 실패라 반복을 멈춥니다" in m for m in logged), str(out))
    logged.clear()
    out, called, rec, ac = run(ALL_ON, {"login": ("failed", "로그인 실패")})
    check("로그인 실패는 손대지 않는다", out == ("stopped", "로그인 실패") and not any("반복 회차" in m for m in logged), str(out))
finally:
    del StatusRec.failed_before_work
    rr.ERPIA_DYING_WAIT_SECONDS = _saved_dw
    if "worked" in StatusRec.__dict__:
        del StatusRec.worked
    os.environ.pop("RPA_RUN_TRIGGER", None)
    rr.log = lambda msg="", **_k: None
out, called, rec, ac = run(ALL_ON, {"import": ("failed", "조회가 끝나지 않음")})
check("반복이 아니면 사유를 바꾸지 않는다", out == ("stopped", "조회가 끝나지 않음"), str(out))
check("택배사 설정이 비면 실제 사유 글이 '저절로 풀리지 않는 실패' 로 잡혀 반복을 멈춘다 - 쉬는 시간마다 같은 실패를 되풀이하지 않게 (Codex 검토 11-25)",
      _st.failed_before_work({"modules": [{"key": "output", "state": "failed", "reason": f"{rr.SETUP_ERROR_CBOTAG} 중단합니다."}]}) is False
      and _st.failed_before_work({"modules": [{"key": "output", "state": "failed", "reason": "출력 전 조회 실패"}]}) is True)

# 데이터를 바꾸는 단추·엑셀 받기/올리기·출력 바로 앞에서 처리 시작을 적는다 (rpa_status.began_work) - 그 전의 실패만 반복 회차를 건너뛴다
_src_rr = Path(_rr.__file__).read_text(encoding="utf-8")
_src_wl = Path(_rr.wellife.__file__).read_text(encoding="utf-8")
_unmarked = []
for _name, _src, _needles in (       # 바로 앞 줄들에 began_work - 확인(덮개·잠김)을 지난 뒤 누르기 바로 앞 (Codex 검토 11-25)
        ("run_routine", _src_rr, ("upload_file_in_dialog(dlg, path, pid=pid)",
                                  "el.click_input(coords=pt, absolute=True, **kw)", "target.click_input(coords=pt, absolute=True)")),
        ("wellife", _src_wl, ("item.click_input(coords=pt, absolute=True)", "_click_in(rr, h, _child(rr, h, \"btn_ExportExcel\", \"[엑셀 다운로드]\"), \"[엑셀 다운로드]\")"))):
    _lines = _src.splitlines()
    for _nd in _needles:
        _at = [i for i, l in enumerate(_lines) if _nd in l]
        if not _at or not all(any("began_work()" in _lines[j] for j in range(max(0, i - 3), i)) for i in _at):
            _unmarked.append(f"{_name}: {_nd}")
# 데이터를 바꾸는 누르기는 work=True·DATA_MENU_ITEMS 로 - 화살표(완료처리·전송요청 포함)·저장·출력·배송보류·개별 배송·운송장 엑셀 받기
_unmarked += [nd for nd in ("click(rr, ctx, arrow, what, work=True)", "click(rr, ctx, save, \"물류대기 '저장(S)'\", work=True)",
                            "export_market(rr, ctx, t[\"market\"], pw, work=bool(live))") if nd not in _src_wl]
_unmarked += [nd for nd, n in (("click_toolbar_button(win, hwnd, \"저장(S)\", work=True)", 2), ("click_toolbar_button(win, hwnd, button, work=True)", 1), ("press(hwnd, imp, f\"'{IMPORT_BUTTON_NAME}' 단추\", work=True)", 1),
                               ("DATA_MENU_ITEMS = (\"배송보류\", \"개별 배송(B)\")", 1)) if _src_rr.count(nd) != n]
check("데이터를 바꾸는 자리마다 바로 앞에 처리 시작 표시", not _unmarked, str(_unmarked))
out, called, rec, ac = run(ALL_ON, {"hold": ("no_target", "행 없음")})
check("no_target 은 계속 간다", called == ALL7 and out[0] == "success")
out, called, rec, ac = run(ALL_ON, {"hold": ("skipped", "메뉴 없음")})
check("skipped 도 계속 간다", len(called) == 7 and out[0] == "success")

out, called, rec, ac = run({k: False for k in ALL_ON}, {})
check("전부 끄면 아무것도 안 돌고 stopped", called == [] and out[0] == "stopped" and "켜진 모듈" in out[1], str(out))
check("전부 끄면 여덟 모듈이 off 로 표시된다", len(rec.of("module_off")) == 8 and len(rec.of("skip")) == 17, str(len(rec.of("skip"))))

out, called, rec, ac = run(ALL_ON, {"hold": ("failed", None)})
check("사유 없는 failed 는 last_problem 으로 채우려 한다", ("last_problem",) in rec.calls, str(rec.calls[-3:]))

# ---------------------------------------------------------------------------
print()
print("=== 6. 출력 모듈의 중복 인쇄 방지 연결 ===")
seen = {}


def fake_goto(ctx):
    seen["goto"] = seen.get("goto", 0) + 1
    return "ok"


rr.goto_logistics_screen = fake_goto
rr.prefetch_auto_ids = lambda win, ids: None
rr.apply_auto_mode = lambda app, hwnd, opt: (seen.update(mode=True) or (False, True))
rr.run_print_step = lambda app, pid, hwnd, options=None, already_printed="continue": seen.update(policy=already_printed) or "done"
rr.status = StatusRec()
ctx = make_ctx()
ctx.options = {}

ctx.results = {"logistics": "done"}
seen.clear()
res = rr.module_output(ctx)
check("물류관리가 방금 done 이면 continue + 화면 이동 없음", res == ("done", None) and seen.get("policy") == "continue" and "goto" not in seen, str((res, seen)))

ctx.results = {}
seen.clear()
res = rr.module_output(ctx)
check("물류관리를 껐으면 화면 이동 + 모드 맞춤 + stop", res[0] == "done" and seen.get("goto") == 1 and seen.get("mode") is True and seen.get("policy") == "stop", str((res, seen)))

ctx.results = {"logistics": "no_target"}
seen.clear()
res = rr.module_output(ctx)
check("물류관리가 돌았는데 done 이 아니면 출력하지 않고 no_target", res[0] == "no_target" and not seen, str((res, seen)))

real_query = rr.query_print_targets      # ERPia 가 꺼져 물류관리를 다시 돌았으면 출력 전에 상단을 조회한다 (사용자 2026-11-16)
ctx.rerun = {"logistics"}
for n, want in ((0, "no_target"), (None, "failed"), (2, "done")):
    rr.query_print_targets = lambda c, n=n: seen.update(query=True) or n
    seen.clear()
    res = rr.module_output(ctx)
    printed = "policy" in seen
    check(f"물류관리를 다시 돌아 대상 없음이면 출력 전에 조회 - 조회 {n} → {want}"
          + (" ([아니오] 정책, 화면 이동 없음)" if n else " (출력 안 함)"),
          res[0] == want and seen.get("query") and printed == bool(n) and seen.get("policy", "stop") == "stop" and "goto" not in seen,
          str((res, seen)))
rr.query_print_targets, ctx.rerun = real_query, set()

rr.run_print_step = lambda app, pid, hwnd, options=None, already_printed="continue": "already_printed"
ctx.results = {}
seen.clear()
check("이미 출력이면 no_target", rr.module_output(ctx)[0] == "no_target")
ctx.results, ctx.rerun = {"logistics": "no_target"}, {"logistics"}
rr.query_print_targets = lambda c: 2
res = rr.module_output(ctx)
check("출력 전 조회 뒤 '이미 출력' 이면 실패 + '화면에서 확인' - 이번에 저장한 배송장이 [아니오] 로 안 나갔을 수 있다 (검토 2026-11-17)",
      res[0] == "failed" and "이미 출력한 배송장이 섞여" in res[1] and res[1].endswith("화면에서 확인하여 주십시오."), str(res))
rr.query_print_targets, ctx.rerun, ctx.results = real_query, set(), {}

rr.run_print_step = lambda app, pid, hwnd, options=None, already_printed="continue": "stuck"
ctx.results = {}
res = rr.module_output(ctx)
check("팝업을 못 처리하면 failed + 사유에 '팝업'", res[0] == "failed" and res[1] and "팝업" in res[1], str(res))

rr.goto_logistics_screen = lambda ctx: "absent"
ctx.results = {}
res = rr.module_output(ctx)
check("출력 단독인데 물류처리 아이콘이 없으면 사유에 '아이콘'", res[0] == "failed" and "아이콘" in res[1], str(res))

# ---------------------------------------------------------------------------
print()
print("=== 7. 물류관리 모듈 - 배송정보설정은 항상 (Blocker 2) ===")
calls = []
rr.goto_logistics_screen = lambda ctx: "ok"
rr.run_logistics_step = lambda app, pid, hwnd, options=None: "done"
rr.run_shipping_setup_step = lambda app, pid, hwnd, options=None: calls.append("setup") or False
rr.run_logistics_save_step = lambda app, hwnd: calls.append("save") or (True, None)
rr.status = StatusRec()
ctx = make_ctx()
ctx.options = {}
res = rr.module_logistics(ctx)
check("배송정보설정 실패 -> stopped, 저장 안 함", res[0] == "stopped" and calls == ["setup"], str((res, calls)))
calls.clear()
rr.run_shipping_setup_step = lambda app, pid, hwnd, options=None: calls.append("setup") or True
check("done 경로는 설정 -> 저장 순서로 항상 돈다", rr.module_logistics(ctx) == ("done", None) and calls == ["setup", "save"], str(calls))
calls.clear()
rr.run_logistics_save_step = lambda app, hwnd: calls.append("save") or (False, "저장 검증 오류: 연락처")
res = rr.module_logistics(ctx)
check("저장이 막히면 stopped + 사유", res[0] == "stopped" and "연락처" in res[1], str(res))
calls.clear()
rr.run_logistics_step = lambda app, pid, hwnd, options=None: "no_target"
res = rr.module_logistics(ctx)
check("하단 0건이면 no_target + 설정/저장 안 감", res[0] == "no_target" and calls == [] and [s[0] for s in rr.status.of("skip")] == ["shipping_setup", "logistics_save"], str((res, calls)))
rr.run_logistics_step = lambda app, pid, hwnd, options=None: "failed"
check("물류 관리 처리 실패 -> failed", rr.module_logistics(ctx)[0] == "failed")

# ---------------------------------------------------------------------------
print()
print("=== 8. 물류대기 모듈 - absent / failed / no_target ===")
rec = StatusRec()
rr.status = rec
rr.goto_hold_screen = lambda ctx: "absent"
res = rr.module_hold(make_ctx())
check("아이콘 없음 -> skipped + stock_review/abnormal_hold/hold_save skip", res[0] == "skipped" and [s[0] for s in rec.of("skip")] == ["stock_review", "abnormal_hold", "hold_save"], str(res))
rr.goto_hold_screen = lambda ctx: "failed"
check("진입 실패 -> failed (물류처리 폴백 없음)", rr.module_hold(make_ctx())[0] == "failed")
rr.goto_hold_screen = lambda ctx: "ok"
rr.run_hold_logistics_step = lambda app, pid, hwnd: "no_target"
res = rr.module_hold(make_ctx())
check("저장할 행이 없으면 no_target", res[0] == "no_target" and "행이 없어" in res[1], str(res))
rr.run_hold_logistics_step = lambda app, pid, hwnd: "done"
check("정상이면 done", rr.module_hold(make_ctx()) == ("done", None))
# 업체 설정 '저장만' (Routine HoldSaveOnly, 사용자 2026-11-03) - 없으면 예전대로, Y 면 save_only, 이상한 값이면 화면에 가기 전에 멈춤
_saved_settings = pl.load_settings
seen = []
rr.run_hold_logistics_step = lambda app, pid, hwnd, save_only=False: seen.append(save_only) or "done"
with_settings({"Routine": {"Hold": "Y"}})
check("HoldSaveOnly 가 없으면 예전 흐름 (보류 뒤 저장)", rr.module_hold(make_ctx()) == ("done", None) and seen == [False], str(seen))
seen.clear()
with_settings({"Routine": {"HoldSaveOnly": " y "}})
check("HoldSaveOnly=Y 면 저장만", rr.module_hold(make_ctx()) == ("done", None) and seen == [True], str(seen))
seen.clear()
rec = StatusRec()
rr.status = rec
with_settings({"Routine": {"HoldSaveOnly": "yes"}})
res = rr.module_hold(make_ctx())
check("HoldSaveOnly 가 Y/N 이 아니면 화면에 가지 않고 failed", res[0] == "failed" and "HoldSaveOnly" in res[1] and seen == []
      and not rec.of("step"), str(res))
pl.load_settings = _saved_settings


# run_hold_save 자체: 0건 -> no_target, 세기 실패 -> 예전처럼 진행
class Grid:
    def __init__(self, cells):
        self.cells = cells

    def rectangle(self):
        return types.SimpleNamespace(width=lambda: 10, height=lambda: 10)

    def descendants(self, control_type=None):
        if self.cells is None:
            raise RuntimeError("COMError 흉내")
        return self.cells


rr.get_onscreen_tables = lambda win: [Grid([])]
check("run_hold_save: 그리드가 비어 있으면 no_target", rr.run_hold_save(make_ctx().app, 4242, 777) == "no_target")
rr.get_onscreen_tables = lambda win: [Grid(None)]
rr.select_all_by_header_checkbox = lambda hwnd, grid: False
check("run_hold_save: 셀 수를 못 세면 예전처럼 전체선택으로 진행 (실패하면 failed)", rr.run_hold_save(make_ctx().app, 4242, 777) == "failed")


# run_hold_save 저장 뒤 (사용자 2026-11-02, 검수 A4): 저장 끝을 확인 못 했거나 실패·오류 팝업이면 failed - 물류관리로 넘어가지 않는다
class PBtn:
    def __init__(self, text="확인"):
        self.text, self.clicked = text, 0

    def window_text(self):
        return self.text

    def click_input(self, **kw):
        self.clicked += 1


_saved_h = {n: getattr(rr, n) for n in ("get_onscreen_tables", "select_all_by_header_checkbox", "visible_child_windows", "click_toolbar_button",
                                         "probe_spinner", "wait_async_then_confirm", "find_popup_ok_button", "collect_popup_text",
                                         "PopupGate", "win32process", "find_popup_failure")}
rr.get_onscreen_tables = lambda win: [Grid([object()])]
rr.select_all_by_header_checkbox = lambda hwnd, grid: True
rr.visible_child_windows = lambda hwnd: {}
rr.click_toolbar_button = lambda win, hwnd, text, work=False: True
rr.probe_spinner = lambda hwnd, base: None
asked = []
for res_async, popups, want, why in (("timeout", [], "failed", "저장 끝을 확인 못 하면 failed"),
                                     ("popup_failed", [], "failed", "실패 팝업이면 failed"),
                                     ("clicked", ["저장 중 오류가 발생했습니다."], "failed", "뒤에 뜬 팝업에 오류 글이 있으면 닫고 failed"),
                                     ("clicked", ["저장되었습니다."], "done", "보통 팝업이면 예전처럼 done")):
    rr.wait_async_then_confirm = lambda app, hwnd, base, r=res_async, **k: asked.append(k) or r
    btns = [PBtn() for _ in popups]
    said = {id(b): t for b, t in zip(btns, popups)}
    rr.find_popup_ok_button = lambda win, b=list(btns): b.pop(0) if b else None
    rr.collect_popup_text = lambda btn, s=said: s.get(id(btn), "")
    got = rr.run_hold_save(make_ctx().app, 4242, 777)
    check(f"run_hold_save {res_async} {popups}: {why}", got == want and all(b.clicked for b in btns), (got, [b.clicked for b in btns]))
check("run_hold_save 는 저장 뒤 첫 팝업 글도 본다 (wait_async_then_confirm 에 fail_words)", asked and all(k.get("fail_words") for k in asked), asked)
rr.wait_async_then_confirm = _saved_h["wait_async_then_confirm"]
rr.PopupGate = lambda hwnd: types.SimpleNamespace(should_scan=lambda: True)
rr.win32process = types.SimpleNamespace(GetWindowThreadProcessId=lambda h: (_ for _ in ()).throw(RuntimeError("창 없음")))
pb = PBtn()
rr.find_popup_ok_button = lambda win: pb
rr.find_popup_failure = lambda win: None
rr.collect_popup_text = lambda btn: "저장 중 오류가 발생했습니다."
r1 = rr.wait_async_then_confirm(make_ctx().app, 777, {}, poll=0, max_wait=1, fail_words=rr.HOLD_FAIL_WORDS)
r2 = rr.wait_async_then_confirm(make_ctx().app, 777, {}, poll=0, max_wait=1)
check("wait_async_then_confirm: fail_words 를 주면 그 글이 든 팝업을 닫고 popup_failed, 안 주면 예전처럼 clicked (정상매출 쪽은 그대로)",
      r1 == "popup_failed" and r2 == "clicked" and pb.clicked == 2, (r1, r2, pb.clicked))
# 별도 창 팝업도 같은 낱말로 본다 (물류대기 저장 중 ERPia 가 오류를 별도 창으로 띄울 때)
_saved_hp = rr.handle_sales_popups, rr.popups_to_try, rr.dismiss_popup_window
rr.popups_to_try = lambda pid, hwnd, tried: [(1, 1)]
rr.dismiss_popup_window = lambda h: (True, "'확인' 클릭", "저장 중 오류가 발생했습니다.")
check("handle_sales_popups: 넘긴 낱말로 별도 창 실패를 가린다, 안 넘기면 예전처럼 매출처리 실패만",
      rr.handle_sales_popups(4242, 777, {}, rr.HOLD_FAIL_WORDS)[0] and rr.handle_sales_popups(4242, 777, {})[0] is None)
seen_kw = []
rr.win32process = types.SimpleNamespace(GetWindowThreadProcessId=lambda h: (1, 4242))
rr.handle_sales_popups = lambda pid, hwnd, tried, keywords=rr.SALES_FAIL_KEYWORDS: seen_kw.append(keywords) or ("저장 중 오류", 1)
r3 = rr.wait_async_then_confirm(make_ctx().app, 777, {}, poll=0, max_wait=1, fail_words=rr.HOLD_FAIL_WORDS)
check("wait_async_then_confirm: 별도 창 팝업도 fail_words 로 보고 popup_failed", r3 == "popup_failed" and seen_kw == [rr.HOLD_FAIL_WORDS], (r3, seen_kw))
rr.handle_sales_popups, rr.popups_to_try, rr.dismiss_popup_window = _saved_hp
for n, f in _saved_h.items():
    setattr(rr, n, f)

# run_logistics_step 자체: 하단 0건 -> no_target
rr.run_logistics_step = _real_run_logistics_step
rr.prefetch_auto_ids = lambda win, ids: None
rr.apply_auto_mode = lambda app, hwnd, opt: (False, True)


class LGrid(Grid):
    def __init__(self, cells, top):
        super().__init__(cells)
        self.top = top

    def rectangle(self):
        return types.SimpleNamespace(top=self.top, width=lambda: 10, height=lambda: 10)


rr.get_onscreen_tables = lambda win: [LGrid([object()], 10), LGrid([], 500)]
rr.wait_grid_spinner_gone = lambda *a, **k: True
check("run_logistics_step: 하단 0건이면 no_target", rr.run_logistics_step(make_ctx().app, 4242, 777, options={}) == "no_target")

# 조회가 끝나기 전에는 진행하지 않는다 (사용자 2026-11-02, 검수 A13): 10분이 아니라 끝까지 기다리고, 그래도 끝을 못 보면 failed
waits = []
rr.wait_grid_spinner_gone = lambda *a, **k: waits.append(k.get("max_wait")) or False
check("run_logistics_step: 하단 조회가 끝나지 않으면 덜 불러온 목록으로 진행하지 않고 failed",
      rr.run_logistics_step(make_ctx().app, 4242, 777, options={}) == "failed" and waits == [rr.QUERY_DONE_MAX_WAIT_SECONDS]
      and rr.QUERY_DONE_MAX_WAIT_SECONDS > rr.ASYNC_MAX_WAIT_SECONDS, waits)
_saved_q = {n: getattr(rr, n) for n in ("click_subtab", "grid_overlay_count", "click_toolbar_button", "run_stock_review_step",
                                         "scroll_grid_right_to_column", "run_hold_save", "collect_shortage_rows", "get_onscreen_tables")}
rr.click_subtab = lambda app, hwnd, name: True
rr.collect_shortage_rows = lambda hwnd, grid: ([], True)
rr.grid_overlay_count = lambda hwnd, grid: 0
rr.click_toolbar_button = lambda win, hwnd, text, work=False: True
check("run_stock_review_step: 재고검토 조회가 끝나지 않으면 None (부족수량을 덜 읽은 채 보류하지 않는다)",
      rr.run_stock_review_step(make_ctx().app, 4242, 777) is None)
qbtn = types.SimpleNamespace(window_text=lambda: "조회(F)", click_input=lambda **k: None,
                             rectangle=lambda: types.SimpleNamespace(left=10, top=10, right=20, bottom=20))
hold_app = types.SimpleNamespace(window=lambda handle: types.SimpleNamespace(
    rectangle=lambda: types.SimpleNamespace(left=0, top=0, right=100, bottom=100), descendants=lambda control_type=None: [qbtn]))
rr.get_onscreen_tables = lambda win: [Grid([object()])]
rr.scroll_grid_right_to_column = lambda *a: False
rr.run_hold_save = lambda app, pid, hwnd: "done"
rr.run_stock_review_step = lambda app, pid, hwnd: None
rr.wait_grid_spinner_gone = lambda *a, **k: True      # 일반 탭 조회는 끝난다 - 멈춤이 재고검토 때문인지만 본다
check("run_hold_logistics_step: 재고검토 조회가 끝나지 않으면 일반 탭·저장으로 가지 않고 failed",
      _real_run_hold_logistics_step(hold_app, 4242, 777) == "failed")
rr.wait_grid_spinner_gone = lambda *a, **k: False
rr.run_stock_review_step = lambda app, pid, hwnd: (0, 0)
check("run_hold_logistics_step: 일반 탭 조회가 끝나지 않으면 저장하지 않고 failed",
      _real_run_hold_logistics_step(hold_app, 4242, 777) == "failed")
# 저장만 (HoldSaveOnly, 사용자 2026-11-03): 재고검토·상품상태 정렬 없이 일반 탭 → 조회 → 전체선택·저장
rr.wait_grid_spinner_gone = lambda *a, **k: True
tabs, stock, scroll = [], [], []
rr.click_subtab = lambda app, hwnd, name: tabs.append(name) or True
rr.run_stock_review_step = lambda app, pid, hwnd: stock.append(1) or (0, 0)
rr.scroll_grid_right_to_column = lambda *a: scroll.append(1) or True
rec = StatusRec()
rr.status = rec
check("run_hold_logistics_step 저장만: 일반 탭 조회 뒤 저장, 재고검토·비정상 보류는 '건너뜀'",
      _real_run_hold_logistics_step(hold_app, 4242, 777, save_only=True) == "done" and tabs == ["일반"] and stock == [] and scroll == []
      and [s[0] for s in rec.of("skip")] == ["stock_review", "abnormal_hold"], str((tabs, stock, scroll, rec.of("skip"))))
rr.click_subtab = lambda app, hwnd, name: False
saves = []
rr.run_hold_save = lambda app, pid, hwnd: saves.append(1) or "done"
check("run_hold_logistics_step 저장만: 일반 탭으로 못 가면 다른 탭을 저장하지 않고 failed",
      _real_run_hold_logistics_step(hold_app, 4242, 777, save_only=True) == "failed" and saves == [])
for n, f in _saved_q.items():
    setattr(rr, n, f)
rr.wait_grid_spinner_gone = lambda *a, **k: True

# ---------------------------------------------------------------------------
print()
print("=== 9. run_print_step / handle_print_popups 사슬 ===")
rr.run_print_step = _real_run_print_step
rr.current_auto_mode = lambda app, hwnd: True


class TBtn:                                   # 툴바 단추 흉내 (BugBuster M17)
    def __init__(self, text, l, t, r, b):
        self.text, self.rect, self.clicked = text, types.SimpleNamespace(left=l, top=t, right=r, bottom=b), False

    def window_text(self):
        return self.text

    def rectangle(self):
        return self.rect

    def click_input(self, **kw):
        self.clicked = True


_ec, rr.ec = rr.ec, types.SimpleNamespace(ensure_foreground=lambda *a, **k: True)
_in = TBtn("출력", -1800, 150, -1740, 175)    # 창이 왼쪽(음수 좌표) 모니터 - 10-07 고객 PC 실측 환경
_out = TBtn("출력", -3800, 150, -3740, 175)   # 숨은 탭의 같은 이름 단추 (창 밖)
_twin = types.SimpleNamespace(rectangle=lambda: types.SimpleNamespace(left=-1920, top=0, right=0, bottom=1040),
                              descendants=lambda control_type=None: [_out, _in])
check("M17 툴바 단추: 창이 음수 좌표 모니터에 있어도 창 안 단추를 누른다 (창 밖 단추는 안 누름)",
      rr.click_toolbar_button(_twin, 1, "출력") and _in.clicked and not _out.clicked)
rr.ec = _ec
rr.click_toolbar_button = lambda win, hwnd, text, work=False: True
rr.pick_carrier = lambda pid, carrier, timeout=None: True
rr.run_print_preview = lambda app, pid, hwnd, printer, timeout=None: True
for nth, want in ((1, "already_printed"), (2, "already_printed"), (1, "stuck"), (2, "stuck")):
    n = [0]

    def fake_popups(app, pid, hwnd, rounds=3, wait=2.0, already_printed="continue", _nth=nth, _want=want):
        n[0] += 1
        return _want if n[0] == _nth else "none"

    rr.handle_print_popups = fake_popups
    r = rr.run_print_step(make_ctx().app, 4242, 777, options={"cboTag": "CJ"}, already_printed="stop")
    check(f"run_print_step: {nth}번째 팝업 처리가 {want} 면 그대로 올리고 멈춘다", r == want and n[0] == nth, str((r, n)))
rr.handle_print_popups = lambda *a, **k: "none"
check("run_print_step: 팝업 없이 끝까지 가면 done", rr.run_print_step(make_ctx().app, 4242, 777, options={"cboTag": "CJ"}) == "done")

# handle_print_popups 진짜 함수로 stop / continue / stuck 을 본다 (UIA 는 전부 가짜)
rr.handle_print_popups = _real_handle_print_popups


class Btn:
    def __init__(self, name):
        self.name, self.clicked = name, 0

    def window_text(self):
        return self.name

    def click_input(self):
        self.clicked += 1


closed = []
rr.find_top_hwnds_by_title = lambda pid, title, exact=True, visible_only=True: [11] if title == rr.CARRIER_PICKER_TITLE else []
rr.win32gui = types.SimpleNamespace(IsWindow=lambda h: True, IsWindowVisible=lambda h: True,
                                    PostMessage=lambda h, m, w, l: closed.append(h))
rr.collect_popup_text = lambda b: ALREADY
app = make_ctx().app
btns = [Btn("확인")]
rr.find_popup_buttons = lambda win: btns
r = rr.handle_print_popups(app, 4242, 777, rounds=1, wait=0, already_printed="stop")
check("handle_print_popups: stuck 이면 아무것도 안 누른다", r == "stuck" and btns[0].clicked == 0, str(r))
btns = [Btn("예(Y)"), Btn("아니오(N)")]
r = rr.handle_print_popups(app, 4242, 777, rounds=1, wait=0, already_printed="stop")
check("stop 정책: 아니오만 누르고 남은 출력 창을 닫는다", r == "already_printed" and btns[1].clicked == 1 and btns[0].clicked == 0 and closed == [11], str((r, closed)))
btns = [Btn("예(Y)"), Btn("아니오(N)")]
r = rr.handle_print_popups(app, 4242, 777, rounds=1, wait=0, already_printed="continue")
check("continue 정책: 예를 누른다 (예전 흐름)", r == "continued" and btns[0].clicked == 1 and btns[1].clicked == 0, str(r))
rr.collect_popup_text = lambda b: "주소정제추출 실패가 2건 존재합니다"
btns = [Btn("확인")]
r = rr.handle_print_popups(app, 4242, 777, rounds=1, wait=0, already_printed="stop")
check("주소정제 실패 팝업은 정책과 무관하게 확인 누르고 abort", r == "abort" and btns[0].clicked == 1, str(r))
rr.find_popup_buttons = lambda win: []
check("팝업이 없으면 none", rr.handle_print_popups(app, 4242, 777, rounds=1, wait=0) == "none")

# ---------------------------------------------------------------------------
print()
print("=== 10. main 의 설정 오류 처리 ===")
rec = StatusRec()
rr.status = rec
sys.argv = [sys.argv[0]]
rr.ec.screen_locked = lambda: False       # 시험하는 PC 화면이 잠겨 있어도 아래 main 시험은 잠기지 않은 것으로
rr.pl.load_routine_modules = lambda keys, *a: (_ for _ in ()).throw(RuntimeError("Hold='yes'"))
rr.run_modules = lambda selected: check("설정 오류면 run_modules 를 부르지 않는다", False) or ("success", None)
rr.main()
fin = rec.of("finish")
check("설정 오류면 finish(stopped, '설정 파일 오류: …')", bool(fin) and fin[-1][0] == "stopped" and "설정 파일 오류" in fin[-1][1] and "Hold" in fin[-1][1], str(fin))
rr.pl.load_routine_modules = lambda keys, *a: (_ for _ in ()).throw(FileNotFoundError("ERPIA_AI.txt"))
rec = StatusRec()
rr.status = rec
rr.main()
check("파일 없음도 stopped + 사유", bool(rec.of("finish")) and rec.of("finish")[-1][0] == "stopped")

# 정상 설정이면 set_modules(5개, 비트 명시) 뒤 run_modules 로 간다
rec = StatusRec()
rr.status = rec
rr.pl.load_routine_modules = lambda keys, *a: ({k: True for k in keys}, ["Extra"])
ran = []
rr.run_modules = lambda selected: ran.append(selected) or ("success", None)
rr.main()
sm = rec.of("set_modules")
check("정상이면 set_modules 에 (키, 이름, 단계, 비트) 8개", bool(sm) and [m[3] for m in sm[0][0]] == [1, 2048, 1024, 2, 4, 8, 16, 512], str(sm))
check("정상이면 run_modules 로 간다 + finish(success)", ran and rec.of("finish")[-1] == ("success", None), str(rec.of("finish")))
for trigger, record in ((None, True), ("repeat", True)):     # 반복 회차도 실패로 남긴다 (사용자 11-25 - 예전엔 안 남김, 10-08)
    ran.clear()
    rec = StatusRec(); rr.status = rec
    rr.ec.screen_locked = lambda: True
    if trigger:
        os.environ["RPA_RUN_TRIGGER"] = trigger
    try:
        rr.main()
    finally:
        os.environ.pop("RPA_RUN_TRIGGER", None)
        rr.ec.screen_locked = lambda: False
    fin = rec.of("finish")
    check(f"화면이 잠겨 있으면 모듈을 돌리지 않고 '화면이 잠겨' 로 멈춘다, 반복 회차({trigger})면 기록 {record} - 웰라이프 run_main 과 같게 (사용자 11-19)",
          not ran and fin and fin[-1][0] == "stopped" and "화면이 잠겨" in fin[-1][1]
          and (fin[-1][2:] == ({"record": False},)) == (not record), str(fin))
# R9 (2026-11-03) 의 '시험 모드 포함' 사유는 2026-11-09 리허설을 없애며 함께 뺐다 - 옛 InvoiceMode 가 남아 있어도 성공 사유는 없다
for sec, want in (({"InvoiceSend": "Y"}, None), ({"InvoiceSend": "Y", "InvoiceMode": "리허설"}, None)):
    rr.pl.load_settings = lambda s=sec: {"Routine": s}
    rr.pl.config_name, rr.pl.LOGIN_SECTION = (lambda: "RPA_UserConfig.json"), "LogIn"
    rec = StatusRec(); rr.status = rec
    rr.main()
    check(f"운송장번호 전송 {sec.get('InvoiceMode', '모드 없음')} → 성공 사유 {want!r}", rec.of("finish")[-1] == ("success", want), str(rec.of("finish")))
del rr.pl.load_settings, rr.pl.config_name, rr.pl.LOGIN_SECTION

print()
print("=== 11. 예약이 넘긴 이번 실행 모듈 (RPA_RUN_MODULES, 2026-10-07) ===")
os.environ.pop("RPA_RUN_MODULES", None)
check("변수가 없으면 None (설정 파일을 쓴다)", rr.run_modules_from_env(KEYS) == (None, []))
os.environ["RPA_RUN_MODULES"] = "Logistics"
sel, unknown = rr.run_modules_from_env(KEYS)
check("물류관리만 → 로그인은 늘 켬, 나머지 끔", sel == {"Login": True, "Sales": False, "Hold": False, "Logistics": True, "Output": False} and unknown == [], f"{sel}")
os.environ["RPA_RUN_MODULES"] = "Login,Output"
sel, _ = rr.run_modules_from_env(KEYS)
check("물류관리 없이 출력만 → 출력도 빠져 돌릴 게 없다", not any(sel.values()), f"{sel}")
os.environ["RPA_RUN_MODULES"] = "Sales,Nope"
sel, unknown = rr.run_modules_from_env(KEYS)
check("모르는 키는 돌려주고 무시", unknown == ["Nope"] and sel["Sales"] and sel["Login"], f"{sel} {unknown}")
rec = StatusRec(); rr.status = rec
rr.pl.load_routine_modules = lambda keys, *a: check("변수가 있으면 설정 파일을 안 읽는다", False) or ({k: True for k in keys}, [])
ran = []
rr.run_modules = lambda selected: ran.append(selected) or ("success", None)
os.environ["RPA_RUN_MODULES"] = "Hold"
rr.main()
check("main 이 넘긴 모듈로 돈다", ran and ran[-1] == {"Login": True, "Import": False, "Excel": False, "Sales": False, "Hold": True, "Logistics": False, "Output": False,
                                                  "InvoiceSend": False}, f"{ran}")
os.environ["RPA_RUN_MODULES"] = "Login"
rec = StatusRec(); rr.status = rec; ran.clear()
rr.main()
check("돌릴 게 없으면 run_modules 없이 중단 + 사유", not ran and rec.of("finish")[-1] == ("stopped", "이번 실행 모듈이 비었습니다"), f"{rec.of('finish')}")
os.environ.pop("RPA_RUN_MODULES", None)

print()
print("=== 13. 도중에 꺼진 ERPia 다시 띄워 잇기 / 관리자 권한 ERPia (2026-10-14) ===")
ALIVE = [True]
rr.ec.pid_alive = lambda pid: ALIVE[0]
SALES_ON = {"Login": True, "Import": False, "Excel": False, "Sales": True, "Hold": False, "Logistics": False, "Output": False}
seen = []


def crash_once(ctx):
    seen.append(ctx.resume)
    if len(seen) == 1:
        ALIVE[0] = False             # 매출처리 중에 꺼졌다
        return "failed", "그리드가 충분히 발견되지 않았습니다."
    return "done", None


def run_crash(sales, selected=SALES_ON):
    seen.clear()
    ALIVE[0] = True
    rr.RoutineContext.attach = lambda self: (True, None)
    rec = StatusRec(); rr.status = rec
    called = []

    def login(ctx):
        called.append("login")
        ALIVE[0] = True               # 새로 띄운 ERPia
        ctx.pid, ctx.hwnd = 4243, 778
        return "done", None

    def track(f):
        return lambda ctx: (called.append("sales"), f(ctx))[1]
    rr.MODULE_FUNCS = {"login": login, "sales": track(sales), "hold": None, "logistics": None, "output": None}
    return _real_run_modules(selected), called, rec


out, called, rec = run_crash(crash_once)
check("매출처리 중 ERPia 가 꺼지면 다시 띄워 로그인하고 주문매핑을 다시 돈다",
      out == ("success", None) and called == ["login", "sales", "login", "sales"], f"{out} {called}")
check("다시 돌 때 ctx.resume='sales' (수집은 따로 끝난 모듈이라 다시 안 한다)", seen == [None, "sales"], str(seen))
check("꺼진 단계는 실패로 표시하고 모듈은 완료로 닫는다",
      len(rec.of("fail_step")) == 1 and [r[1] for r in rec.of("module_done")] == ["done", "done"], str(rec.calls[-6:]))


def always_crash(ctx):
    seen.append(ctx.resume)
    ALIVE[0] = False
    return "done", None


out, called, rec = run_crash(always_crash)
check(f"계속 꺼지면 {rr.ERPIA_RESTARTS}번 다시 띄운 뒤 멈춘다 ('done' 이라고 돌려줘도 꺼졌으면 다시 돈다)",
      out[0] == "stopped" and "3번 꺼져" in out[1] and called.count("sales") == rr.ERPIA_RESTARTS + 1, f"{out} {called}")


def raise_dead(ctx):
    seen.append(ctx.resume)
    if len(seen) == 1:
        ALIVE[0] = False
        raise RuntimeError("COMError 흉내")
    return "done", None


OTHERS = [[]]
rr.ec.erpia_pids = lambda: OTHERS[0]
OTHERS[0] = [9999]
out, called, rec = run_crash(crash_once)
check("꺼진 뒤 다른 계정 ERPia 가 떠 있어도 그것은 두고 우리 것을 다시 띄워 잇는다 (사용자 2026-11-16, 예전엔 멈춤)",
      out[0] == "success" and called == ["login", "sales", "login", "sales"], f"{out} {called}")
OTHERS[0] = []


def one_crash(ctx):
    ctx.no_rerun.add("sales")      # '1건' 모드 모듈 (wellife.run_main 의 once, module_invoice_send)
    seen.append(ctx.resume)
    ALIVE[0] = False
    return "done", None


out, called, rec = run_crash(one_crash)
check("'1건' 모드 모듈은 ERPia 가 꺼져도 다시 돌지 않고 멈춘다 (1건이 2건이 되지 않게, 리뷰 10-14)",
      out[0] == "stopped" and "1건" in out[1] and called == ["login", "sales"], f"{out} {called}")
WM = [0]


def worked_crash(ctx):     # 데이터를 바꾸는 단추를 누른 뒤(rpa_status.began_work) ERPia 가 꺼짐
    seen.append(ctx.resume)
    WM[0] += 1
    ALIVE[0] = False
    return "done", None


StatusRec.work_marks = lambda self: WM[0]
try:
    out, called, rec = run_crash(worked_crash)
finally:
    del StatusRec.work_marks
check("처리를 시작한 뒤 ERPia 가 꺼지면 다시 돌지 않고 '결과 미확인' 으로 멈춘다 - 같은 처리가 두 번 되지 않게 (사용자 11-25, Codex 검토)",
      out[0] == "stopped" and "결과 미확인" in out[1] and called == ["login", "sales"], f"{out} {called}")

out, called, rec = run_crash(raise_dead)
check("꺼지면서 난 UI 예외도 다시 띄워 잇는다", out == ("success", None) and seen == [None, "sales"], f"{out} {seen}")

DYING = [0]


def alive_dying(pid):
    """예외 순간에는 아직 떠 있다가 조금 뒤 끝나는 ERPia - 창이 먼저 사라지고 프로세스는 늦게 끝난다."""
    if DYING[0] > 0:
        DYING[0] -= 1
        ALIVE[0] = DYING[0] > 0
        return True
    return ALIVE[0]


def raise_dying(ctx):
    seen.append(ctx.resume)
    if len(seen) == 1:
        DYING[0] = 3
        raise KeyError(None)             # pywinauto - 사라지는 창의 요소 종류를 못 읽음 (2026-11-19 개발기 A3)
    return "done", None


rr.ec.pid_alive, rr.ERPIA_DYING_WAIT_SECONDS = alive_dying, 3
_saved_isw = rr.win32gui.IsWindow
rr.win32gui.IsWindow = lambda h: False      # 꺼지는 중 - 메인 창이 먼저 사라졌다 (run_routine.main_window_alive)
try:
    out, called, rec = run_crash(raise_dying)
except KeyError as e:
    out = f"KeyError 그대로: {e}"
check("예외 순간엔 아직 떠 있다가 곧 끝나는 ERPia(꺼지는 중)도 기다려 보고 다시 띄워 잇는다 (11-19 개발기: '프로그램 오류 - KeyError: None')",
      out == ("success", None) and seen == [None, "sales"], f"{out} {seen}")


def fail_dying(ctx):
    seen.append(ctx.resume)
    if len(seen) == 1:
        DYING[0] = 3
        return "failed", "UI 오류: KeyError"      # 웰라이프 ui_error 처럼 예외를 '실패' 결과로 돌려준다
    return "done", None


out, called, rec = run_crash(fail_dying)
check("예외를 '실패' 결과로 돌려주는 모듈(웰라이프 ui_error)도 꺼지는 중이면 기다려 보고 다시 띄워 잇는다 (웰라이프·일반 같은 동작, 사용자 11-19)",
      out == ("success", None) and seen == [None, "sales"], f"{out} {seen}")
rr.win32gui.IsWindow = lambda h: True       # ERPia 가 멀쩡하다 - 메인 창이 그대로
ALIVE[0] = True
_t0 = _time.time()
out, called, rec = run_crash(lambda ctx: ("failed", "조회가 끝나지 않음"))
check("모듈이 실패해도 메인 창이 그대로면 꺼지는 중을 기다리지 않는다 - 실패마다 5초씩 늘던 것 (검토 11-25)",
      out == ("stopped", "조회가 끝나지 않음") and _time.time() - _t0 < 1.5, f"{out} {_time.time() - _t0:.1f}초")
seen.clear()
out, called, rec = run_crash(raise_dying)
check("예외면 메인 창이 아직 있어도 꺼지는 중인지 지금처럼 기다린다 - 닫히는 도중 창보다 UIA 예외가 먼저 날 수 있다 (교차 검증 11-25)",
      out == ("success", None) and seen == [None, "sales"], f"{out} {seen}")
seen.clear()
out, called, rec = run_crash(fail_dying)
check("웰라이프처럼 예외를 'UI 오류' 실패로 돌려줘도 메인 창이 아직 있으면 기다려 다시 띄운다 (교차 검증 2차 11-25)",
      out == ("success", None) and seen == [None, "sales"], f"{out} {seen}")
rr.win32gui.IsWindow = _saved_isw
# 모듈 예외의 오류 추적은 PC 결과 파일에만 - 경로·창 글이 섞여 상태 최근 로그(log_tail)로 클라우드에 올라가지 않게 (검토 11-25)
_saved_rl = (rr.RESULT_PATH, rr.status)
rr.RESULT_PATH, rr.status = os.path.join(tempfile.mkdtemp(prefix="rpa_log_"), "result.txt"), StatusRec()
_real_log("Traceback 흉내: 파일 경로 줄 1", cloud=False)
_real_log("한 줄 사유")
with open(rr.RESULT_PATH, encoding="utf-8") as _f:
    _txt = _f.read()
_tails = [c[0] for c in rr.status.of("log_line")]
check("log(cloud=False): PC 결과 파일에는 남고 상태 최근 로그에는 안 간다 - 보통 로그는 둘 다",
      "Traceback 흉내" in _txt and "한 줄 사유" in _txt and len(_tails) == 1 and "한 줄 사유" in _tails[0], f"{_tails}")
check("모듈 예외의 오류 추적은 cloud=False 로 (한 줄 사유는 wellife.ui_error 가 남긴다)",
      "error.__traceback__)).rstrip(), cloud=False)" in Path(_rr.__file__).read_text(encoding="utf-8"))
rr.RESULT_PATH, rr.status = _saved_rl
rr.ec.pid_alive, rr.ERPIA_DYING_WAIT_SECONDS = (lambda pid: ALIVE[0]), 0.5


def raise_alive(ctx):
    raise ValueError("진짜 버그")


def raise_stop(ctx):
    raise rr.wellife.Stop("failed", "누를 자리를 다른 창이 덮고 있어 누르지 않고 중단하였습니다. (창 1 '시험 덮개')")


_saved_csp = rr.wellife.clear_separate_popups
cleared_p = []
rr.wellife.clear_separate_popups = lambda rr_, ctx, after, ignore=(): cleared_p.append(after) or 1
ran_p = []
out, called, rec = run_crash(lambda ctx: ran_p.append(1) or ("done", None))
rr.wellife.clear_separate_popups = _saved_csp
check("모듈을 시작하기 전에 따로 뜬 ERPia 팝업 창을 닫고 그 모듈을 돈다 (사용자 11-20: X 나 [확인] 으로 지우고 다음 단계로)",
      out == ("success", None) and ran_p and any("시작 전" in a for a in cleared_p), f"{out} {cleared_p}")
out, called, rec = run_crash(raise_stop)
check("웰라이프 안전장치의 Stop 은 그 결과·사유 그대로 모듈 결과로 ('UI 오류' 가 아니다, 사용자 11-19)",
      out == ("stopped", "누를 자리를 다른 창이 덮고 있어 누르지 않고 중단하였습니다. (창 1 '시험 덮개')")
      and rec.of("module_done")[-1][:2] == ("sales", "failed"), f"{out} {rec.of('module_done')}")
try:
    out, called, rec = run_crash(raise_alive)
except ValueError as e:
    out = f"예외 그대로: {e}"
check("ERPia 가 떠 있는데 난 예외는 그 모듈의 실패로 남기고 사유를 보이고 뒤 모듈은 멈춘다 (웰라이프 ui_error 와 같게, 사용자 11-19)",
      isinstance(out, tuple) and out[0] == "stopped" and out[1].startswith("UI 오류: ValueError") and "진짜 버그" in out[1]
      and rec.of("module_done")[-1][:2] == ("sales", "failed"), f"{out} {rec.of('module_done')}")


def login_fails_after(ctx):
    ALIVE[0] = False
    return "failed", "x"


rr.MODULE_FUNCS = {"login": lambda ctx: ("failed", "로그인 실패: 흉내"), "sales": None}
ctx = make_ctx()
rr.status = StatusRec()
ALIVE[0] = False
res = rr.run_module(ctx, "sales", "주문매핑", {"login": lambda c: ("failed", "로그인 실패: 흉내"), "sales": login_fails_after})
check("다시 띄우기(로그인)가 실패하면 그 사유로 실패", res[0] == "failed" and "로그인 실패: 흉내" in res[1] and ctx.resume is None, str(res))
ALIVE[0] = True

# 주문매핑 세 모듈 (모든 업체, 사용자 2026-10-30): 자동 수집 / 엑셀 수집 / 매출처리 - 저마다 화면으로 가서 제 일만 한다
_saved_s = {n: getattr(rr, n) for n in ("goto_order_screen", "get_onscreen_tables", "select_all_and_verify",
                                         "run_import_step", "run_excel_upload_step", "find_by_text")}
sales_acts = []


class Tbl:
    def __init__(self, top, rows=None):
        self.top, self.rows = top, rows      # rows None = 줄을 셀 수 없음 (예전처럼 진행)

    def rectangle(self):
        return types.SimpleNamespace(top=self.top, left=0)

    def descendants(self, control_type=None):
        if self.rows is None:
            raise RuntimeError("COMError 흉내")
        return self.rows


EXCEL_RET = [(2, 0)]


def fake_excel(*a):
    sales_acts.append(("excel",))
    if isinstance(EXCEL_RET[0], Exception):
        raise EXCEL_RET[0]
    return EXCEL_RET[0]


rr.status = StatusRec()
rr.goto_order_screen = lambda ctx: sales_acts.append(("goto",)) or (True, None)
rr.get_onscreen_tables = lambda win: [Tbl(10), Tbl(300)]
SELECTED = [3]
rr.select_all_and_verify = lambda name, *a: sales_acts.append(("select", name)) or SELECTED[0]
rr.run_import_step = lambda *a: sales_acts.append(("import",)) or True
rr.run_excel_upload_step = fake_excel


class Btn:
    def __init__(self, name, rect=(100, 10, 160, 30)):
        self.name, self.rect = name, rect

    def rectangle(self):
        return self.rect

    def window_text(self):
        return self.name


IMP, AGAIN = Btn("가져오기"), [None]
rr.find_by_text = lambda win, text, control_types=(): (AGAIN[0] or IMP) if text == rr.IMPORT_BUTTON_NAME else None   # 매출처리 단추 없음 -> 여기서 멈춘다
# 웰라이프 안전장치 (일반 PROCESS 도 같은 자리에서 부른다, 사용자 11-19) - 부른 차례만 적는다
_saved_wl = {n: getattr(rr.wellife, n) for n in ("visible_page", "onscreen_button", "no_popup", "front", "wait_idle", "sites_checked",
                                                 "clear_point", "check_header", "recheck", "press_menu_item")}
CHECKED, RECHECKED, PRESSED = [True], [True], [(" → '정상매출' 누름", True)]
rr.wellife.check_header = lambda grid, label="": Btn("row Check Box")
rr.wellife.recheck = lambda rr_, grid, label, live: sales_acts.append(("recheck", label)) or (
    RECHECKED[0].pop(0) if isinstance(RECHECKED[0], list) else RECHECKED[0])
sales_strict = []      # press_menu_item 에 넘긴 strict (▼·메뉴를 못 찾으면 실패)


def menu_fake(rr_, ctx, split, item, what, grid=None, confirm=True, strict=False):
    sales_acts.append(("menu", item, what, confirm))
    sales_strict.append(strict)
    if isinstance(PRESSED[0], Exception):
        raise PRESSED[0]
    return PRESSED[0]


rr.wellife.press_menu_item = menu_fake
READY, READY_CALLS = [False], []      # wait_sales_ready 가 돌려줄 값 (기다렸는가) / 부른 때 한 일 수·무엇·찾은 단추
_saved_wl["wait_sales_ready"] = getattr(rr.wellife, "wait_sales_ready", None)
rr.wellife.wait_sales_ready = lambda rr_, ctx, find, what: (READY_CALLS.append((sales_acts[-1:], what, getattr(find(), "name", find())))
                                                            or READY[0])
rr.wellife.visible_page = lambda ctx: "떠 있는 화면"
rr.wellife.onscreen_button = lambda page, text: IMP if text == rr.IMPORT_BUTTON_NAME else None
rr.wellife.no_popup = lambda rr_, ctx, after: sales_acts.append(("no_popup", after))
rr.wellife.front = lambda rr_, ctx, what: sales_acts.append(("front", what))
rr.wellife.wait_idle = lambda rr_, button, what: None
rr.wellife.sites_checked = lambda rr_, grid: CHECKED[0]
rr.wellife.clear_point = lambda rr_, ctx, el, what: sales_acts.append(("clear", el.name)) or (130, 20)
IMPORT_ACTS = [("goto",), ("no_popup", "상단 전체선택 전"), ("front", "상단 전체선택"), ("select", "좌측상단"), ("no_popup", "상단 전체선택"),
               ("front", "자동 수집 [가져오기]"), ("clear", "가져오기"), ("import",)]
SALES_ACTS = [("goto",), ("no_popup", "하단 전체선택 전"), ("front", "하단 전체선택"), ("clear", "row Check Box"), ("select", "하단"),
              ("no_popup", "하단 전체선택"), ("recheck", "주문매핑 하단")]     # 매출처리 단추가 없어 여기서 실패
for name, f, want, res_want in (("module_import", rr.module_import, IMPORT_ACTS, "done"),
                                ("module_excel", rr.module_excel, [("goto",), ("excel",)], "done"),
                                ("module_sales", rr.module_sales, SALES_ACTS, "failed")):
    sales_acts.clear()
    rr.status = StatusRec()
    res = f(make_ctx())
    check(f"{name}: " + " -> ".join(a[0] if len(a) == 1 else a[1] for a in want) + f" ({res_want})",
          sales_acts == want and res[0] == res_want, f"{sales_acts} {res}")
# 자동 수집 누르기 전 안전장치 - 웰라이프 import_collect 와 같다 (사용자 11-19: 일반에도 넣는다)
for why, setup, word in (("상단 전체선택을 확인 못 하면", lambda: SELECTED.__setitem__(0, None), "전체선택을 확인하지 못해"),
                         ("전체선택 뒤 체크가 풀렸으면", lambda: CHECKED.__setitem__(0, False), "체크가 해제"),
                         ("다시 찾은 단추가 다른 자리(숨은 화면)면", lambda: AGAIN.__setitem__(0, Btn("가져오기", (5, 900, 60, 930))), "단추와 달라")):
    setup()
    sales_acts.clear()
    try:
        res = rr.module_import(make_ctx())
    except rr.wellife.Stop as e:       # run_module 이 이 결과·사유로 남긴다
        res = (e.result, str(e))
    check(f"자동 수집: {why} [가져오기] 를 누르지 않고 실패 (웰라이프와 같게, 사용자 11-19)",
          res[0] == "failed" and word in res[1] and ("import",) not in sales_acts and ("clear", "가져오기") not in sales_acts, f"{res} {sales_acts}")
    SELECTED[0], CHECKED[0], AGAIN[0] = 3, True, None


def covered(rr_, ctx, el, what, pt=None):
    raise rr.wellife.Stop("failed", f"{what}: 누를 자리를 다른 창이 덮고 있어 누르지 않고 중단하였습니다. (창 1 '시험 덮개')")


rr.wellife.clear_point = covered
sales_acts.clear()
try:
    res = rr.module_import(make_ctx())
except rr.wellife.Stop as e:
    res = ("Stop", e.result, str(e))
check("자동 수집: 누를 자리를 다른 창이 덮으면 누르지 않고 멈춘다 (run_module 이 그 사유로 실패를 남긴다)",
      res[0] == "Stop" and res[1] == "failed" and "시험 덮개" in res[2] and ("import",) not in sales_acts, f"{res} {sales_acts}")
rr.wellife.clear_point = lambda rr_, ctx, el, what: sales_acts.append(("clear", el.name)) or (130, 20)
check("매출처리 모듈은 하단 선택 단계부터 찍는다", rr.status.of("step")[0] == ("bottom_select",), str(rr.status.of("step")))
_saved_up = rr.wellife.upload_paths
rr.wellife.upload_paths = lambda r: set()      # 진짜 바탕화면 폴더를 읽지 않게 (R2 의 남은 파일 수)
for ret, want, why in (((0, 0), "skipped", "올릴 엑셀이 없으면 건너뜀 (토큰 0)"), ((0, 2), "skipped", "올린 게 없고 오류 폴더로만 가면 건너뜀 + 사유에 오류 수"),
                       ((3, 1), "done", "올린 게 있으면 완료 + 사유에 수"),
                       (RuntimeError("흉내"), "failed", "더 올릴 수 없게 막히면 실패로 멈추고 뒤 모듈은 돌리지 않는다 (사용자 11-25, 예전엔 건너뜀으로 이어 감)")):
    EXCEL_RET[0] = ret
    res = rr.module_excel(make_ctx())
    check(f"엑셀 수집 {ret!r}: {why}", res[0] == want and (not isinstance(ret, tuple) or not ret[1] or f"{ret[1]}개" in res[1]), str(res))
_us = rr.UploadStop("눌러도 닫히지 않는 팝업: 시험 창 글")
_us.uploaded, _us.errors = 2, 1
EXCEL_RET[0] = _us
rr.wellife.upload_paths = lambda r: {"(101)a.xlsx", "(102)b.xlsx"}
res = rr.module_excel(make_ctx())
check("엑셀 업로드가 막히면 실패 - 사유에 막은 창의 글·올린 수·오류 폴더 수·남은 파일 수·뒤 단계 안 함 (사용자 11-25: 사유를 자세히)",
      res[0] == "failed" and all(w in res[1] for w in ("시험 창 글", "2건 업로드", "오류 폴더로 1건", "남은 파일 2건", "뒤 단계는 진행하지 않았습니다")),
      str(res))
rr.wellife.upload_paths = lambda r: set()
# R2 (2026-11-03): 하나도 못 올렸는데 파일이 있었으면 '올릴 엑셀 없음' 과 가르고 반복 회차라도 기록에 남긴다 (토큰은 그대로 0)
for ret, left, keep, word in (((0, 0), set(), False, "올릴 엑셀 없음"), ((0, 2), set(), True, "하나도 올리지 못했습니다"),
                              ((0, 0), {"a.xlsx"}, True, "남은 파일 1개"), ((3, 0), {"a.xlsx"}, False, "3개 업로드"),
                              (RuntimeError("흉내"), set(), False, "엑셀 업로드를 멈추었습니다")):     # 실패는 원래 이력에 남는다
    EXCEL_RET[0] = ret
    rr.wellife.upload_paths = lambda r, s=left: set(s)
    rr.status = StatusRec()
    res = rr.module_excel(make_ctx())
    check(f"엑셀 수집 {ret!r} 남은 {len(left)}: 기록 남김 {keep}, 사유 '{word}'",
          word in res[1] and bool(rr.status.of("keep_record")) == keep, f"{res} {rr.status.of('keep_record')}")
rr.wellife.upload_paths = _saved_up
EXCEL_RET[0] = (2, 0)
# 자동 수집: [가져오기] 를 누르지 못했거나 눌러도 조회가 시작되지 않았으면(None) 건너뜀(토큰 0, 사용자 2026-11-02·11-19),
# 시작된 뒤 끝을 못 봤으면(False) 예전처럼 완료 (사용자 2026-11-02)
for ret, want, why in ((None, "skipped", "누르지 못했거나 조회가 시작되지 않았으면 건너뜀 (토큰 0)"),
                       (False, "failed", "시작된 뒤 끝을 못 보면 실패로 멈춘다 - 뒤 매출처리를 돌리지 않게 (사용자 11-23)")):
    rr.run_import_step = lambda *a, r=ret: r
    res = rr.module_import(make_ctx())
    check(f"자동 수집 {ret!r}: {why}", res[0] == want, str(res))
check("끝을 못 봤으면 누른 뒤 몇 초 기다렸는지 사유에 남긴다 (사용자 11-23)", bool(res[1]) and "0초 기다려도" in res[1], str(res))
rr.run_import_step = _saved_s["run_import_step"]
_saved_i = (rr.find_by_text, rr.native_enabled, rr.handle_import_popups, rr.IMPORT_BUSY_WAIT_SECONDS, rr.ec.ensure_foreground, rr.status)
_btn = types.SimpleNamespace(click_input=lambda: None, element_info=types.SimpleNamespace(handle=None))
rr.find_by_text, rr.native_enabled, rr.handle_import_popups = (lambda win, text, control_types=(): _btn), (lambda el: True), (lambda *a: None)
rr.IMPORT_BUSY_WAIT_SECONDS, rr.ec.ensure_foreground, rr.status = 0.3, (lambda h: None), StatusRec()
_clicks_i = []
_btn.click_input = lambda **k: _clicks_i.append(k)
check("[가져오기] 를 눌러도 '조회중' 이 안 되면(덮인 클릭 등) None - 누르지 못함과 같이 건너뜀 (웰라이프·일반 같게, 사용자 11-19)",
      rr.run_import_step(None, 1, 2, None) is None and rr.run_import_step(None, 1, 2, None, wait=False) is None and len(_clicks_i) == 2,
      str(_clicks_i))
check("  건너뜀 사유는 '눌렀으나 조회가 시작되지 않아' 로 나눠 적는다 (검토 11-25)", "눌렀으나" in rr.import_miss() and "조회가 시작되지 않아" in rr.import_miss(),
      rr.import_miss())
rr.find_by_text = lambda win, text, control_types=(): None
check("  단추가 없으면 '단추를 찾지 못해 누르지 않고'", rr.run_import_step(None, 1, 2, None) is None and "단추를 찾지 못해" in rr.import_miss(), rr.import_miss())
rr.find_by_text = lambda win, text, control_types=(): _btn
_saved_pr_i = rr.press


def _press_boom(*a, **k):
    raise RuntimeError("UIA 흉내")


rr.press = _press_boom
try:
    rr.run_import_step(None, 1, 2, None)
    res = "건너뜀"
except RuntimeError as e:
    res = str(e)
check("  누르기 직전 확인·누르기에서 난 뜻밖의 오류는 건너뜀이 아니라 위로 올린다 - 모듈 실패로 멈춘다 (검토 11-25, 교차 검증)", res == "UIA 흉내", res)
rr.press = _saved_pr_i
(rr.find_by_text, rr.native_enabled, rr.handle_import_popups, rr.IMPORT_BUSY_WAIT_SECONDS, rr.ec.ensure_foreground, rr.status) = _saved_i
rr.run_import_step = lambda *a: sales_acts.append(("import",)) or True
# 매출처리: 하단이 0줄이면 전체선택도 정상매출도 하지 않고 건너뜀 (토큰 0 - 사용자 2026-11-02). 줄을 못 세면 예전처럼 진행 (위 시험)
rr.get_onscreen_tables = lambda win: [Tbl(10), Tbl(300, rows=[])]
sales_acts.clear()
res = rr.module_sales(make_ctx())
check("매출처리: 하단 0줄이면 누르지 않고 건너뜀", res[0] == "skipped" and "0줄" in res[1] and sales_acts == [("goto",)], f"{sales_acts} {res}")
rr.get_onscreen_tables = lambda win: [Tbl(10), Tbl(300, rows=[object()])]
sales_acts.clear()
res = rr.module_sales(make_ctx())
check("매출처리: 하단에 줄이 있으면 전체선택으로 간다", sales_acts == SALES_ACTS, f"{sales_acts} {res}")
# 매출처리 누르기 전 안전장치 - 웰라이프 normal_sales 와 같다 (사용자 11-19)
SPLIT = Btn("매출처리")
rr.find_by_text = lambda win, text, control_types=(): SPLIT if text == "매출처리" else IMP
RECHECKED[0] = False
sales_acts.clear()
res = rr.module_sales(make_ctx())
check("매출처리: 누르기 직전 다시 보니 체크가 풀렸으면 정상매출을 누르지 않고 실패로 멈춘다 (사용자 11-23, 웰라이프와 같게)",
      res[0] == "failed" and "체크가 되지 않아" in res[1] and not [a for a in sales_acts if a[0] == "menu"], f"{res} {sales_acts}")
RECHECKED[0] = [False, True]      # 한 번 풀렸다가 다시 체크하니 맞다
sales_acts.clear()
try:
    res = rr.module_sales(make_ctx())
except rr.wellife.Stop as e:
    res = (e.result, str(e))
check("매출처리: 누르기 직전 체크가 풀렸으면 그리드를 다시 잡고 다시 체크한 뒤 이어간다 - 바로 실패하지 않는다 (사용자 11-23: 체크를 확실히)",
      [a[0] for a in sales_acts].count("select") == 2 and [a for a in sales_acts if a[0] == "menu"], f"{res} {sales_acts}")
RECHECKED[0], PRESSED[0] = True, rr.wellife.Stop("failed", "매출처리 ▼ (▼ 자리를 확인하지 못해 메뉴를 열지 않았습니다. 확인하여 주십시오)")
sales_acts.clear()
try:
    res = rr.module_sales(make_ctx())
except rr.wellife.Stop as e:      # run_module 이 그 모듈의 실패로 남긴다
    res = (e.result, str(e))
check("매출처리: ▼·정상매출은 웰라이프 press_menu_item 으로 (▼ 자리·새 메뉴 창·꺼진 항목·덮개 확인, 팝업은 원래 규칙 confirm=False), "
      "▼·메뉴를 못 찾으면 건너뜀이 아니라 실패 (strict - 사용자 11-20)",
      ("menu", "정상매출", "매출처리 ▼", False) in sales_acts and sales_strict[-1:] == [True] and res[0] == "failed"
      and "▼ 자리를 확인하지 못해" in res[1], f"{res} {sales_acts} {sales_strict}")
PRESSED[0] = rr.wellife.Stop("failed", "매출처리 ▼: '정상매출'이(가) 꺼져 있어 누르지 않고 중단하였습니다. 확인하여 주십시오.")
try:
    res = rr.module_sales(make_ctx())
except rr.wellife.Stop as e:
    res = (e.result, str(e))
check("매출처리: '정상매출' 이 꺼져 있으면 누르지 않고 실패로 멈춘다 (press_menu_item strict, 사용자 11-23)",
      res[0] == "failed" and "꺼져 있어" in res[1] and sales_strict[-1:] == [True], str(res))
check("매출처리: 하단 줄을 세기 전에 ▼ 를 누를 수 있을 때까지 기다린다 (주문 수집 중이면 꺼져 있다 - 사용자 11-23)",
      READY_CALLS[-1:] == [([("goto",)], "매출처리 ▼", "매출처리")], str(READY_CALLS))
PRESSED[0] = (" → '정상매출' 누름", True)
READY[0], tables_n = True, []
_got, _wt = rr.get_onscreen_tables, rr.wellife.wait_tables
rr.wellife.wait_tables = lambda *a: None      # 화면 이동 뒤 표 기다림(11-24)은 따로 본다 - 여기서는 매출처리의 다시 찾기만 센다
rr.get_onscreen_tables = lambda win: tables_n.append(1) or _got(win)
sales_acts.clear()
res = rr.module_sales(make_ctx())
rr.get_onscreen_tables, READY[0], rr.wellife.wait_tables = _got, False, _wt
check("매출처리: 기다렸으면 그새 다시 그려졌을 수 있어 그리드를 다시 찾는다", len(tables_n) == 2, f"{tables_n} {res}")
_saved_to = (rr.wait_async_then_confirm, rr.find_popup_ok_button, rr.handle_sales_popups, rr.probe_spinner)
rr.wait_async_then_confirm = lambda app, hwnd, base, **k: "timeout"
rr.find_popup_ok_button = lambda win: None
rr.handle_sales_popups = lambda *a, **k: (None, 0)
rr.probe_spinner = lambda hwnd, base: None
res = rr.module_sales(make_ctx())
(rr.wait_async_then_confirm, rr.find_popup_ok_button, rr.handle_sales_popups, rr.probe_spinner) = _saved_to
check("매출처리: 정상매출 뒤 대기 시간 초과는 실패로 멈춘다 - 기다린 초를 사유에 (사용자 11-23, 예전엔 사유 없이 완료로 이어 감)",
      res[0] == "failed" and f"{rr.ASYNC_MAX_WAIT_SECONDS}초" in (res[1] or ""), str(res))
PRESSED[0] = (" → '정상매출' 누름", True)
rr.find_by_text = lambda win, text, control_types=(): (AGAIN[0] or IMP) if text == rr.IMPORT_BUTTON_NAME else None
rr.get_onscreen_tables = lambda win: [Tbl(10), Tbl(300)]
rr.goto_order_screen = lambda ctx: (False, "아이콘 없음")
res = rr.module_sales(make_ctx())
check("화면으로 못 가면 그 모듈이 실패 (사유 그대로)", res == ("failed", "아이콘 없음"), str(res))
rr.goto_order_screen = lambda ctx: (True, None)
rr.get_onscreen_tables = lambda win: [Tbl(10)]
res = rr.module_import(make_ctx())
check("그리드가 모자라면 실패", res[0] == "failed" and "그리드" in res[1], str(res))
rr.get_onscreen_tables = lambda win: [Tbl(10), Tbl(300)]

# 함께 실행 (모든 업체, 사용자 2026-10-20): 엑셀은 받는 대로 (excel_upload_together). 차례는 routine_modules (위 4절)
_saved_t = {n: getattr(rr, n) for n in ("excel_upload_together", "sales_flow", "find_popup_windows", "upload_popups",
                                         "excel_upload_dir", "time")}
_saved_w = rr.wellife.on_top, rr.wellife.wait_prepare
rr.excel_upload_together = lambda ctx, grid: sales_acts.append(("together",)) or (1, 0, None)
tops, prep = [], [["prepare"], ["prepare"], []]
rr.wellife.on_top = lambda rr_, hwnd, on: tops.append(on)
rr.status = StatusRec()
rr.status.running_programs = lambda: prep.pop(0) if prep else []
rr.time = types.SimpleNamespace(sleep=lambda s: None, time=_time.time)
rr.TOGETHER_MODE = "excel"
sales_acts.clear()
res = rr.module_excel(make_ctx())
check("함께 실행 엑셀 수집: 받는 대로 올리고, 그동안 ERPia 를 맨 위로 두고 끝나면 풀며, 사이트 수집이 끝나기를 기다린 뒤 다음 모듈로",
      sales_acts == [("together",)] and tops == [True, False] and not prep and res[0] == "done", f"{sales_acts} {tops} {prep} {res}")
tops.clear()
rr.TOGETHER_MODE = "excel_import"
res = rr.module_import(make_ctx())
check("함께 실행 자동 수집도 ERPia 를 맨 위로 (사이트 수집의 Edge 창이 누를 자리를 덮지 않게)", tops == [True, False] and res[0] == "done", f"{tops} {res}")
rr.TOGETHER_MODE = None
tops.clear()
rr.module_sales(make_ctx())
check("함께 실행이 아니면 맨 위만 푼다 (앞 함께 실행이 [중지] 로 남긴 맨 위 - 맨 위가 아니면 아무 일 없음)", tops == [False], str(tops))
rr.excel_upload_together = _saved_t["excel_upload_together"]

tdir = tempfile.mkdtemp(prefix="rpa_tog_")
arrive, ups, labels, on = [["(108)b.xlsx"], []], [], [], [True]


def tog_sleep(_s):
    if arrive:
        for f in arrive.pop(0):
            open(os.path.join(tdir, f), "w").close()
    else:
        on[0] = False


def tog_up(app, pid, hwnd, grid, skip=()):
    todo = sorted(p for p in rr.wellife.upload_paths(rr) if p not in skip)
    ups.append(([os.path.basename(p) for p in todo], rr.UPLOAD_NO_KEYS))
    for p in todo:
        os.remove(p)
    return len(todo), 0


rr.excel_upload_dir = lambda: tdir
rr.find_popup_windows = lambda pid, hwnd: []
rr.upload_popups = lambda pid, hwnd, before=(), label="": labels.append(label) or (["늦은 팝업"] if len(labels) == 1 else [])
rr.run_excel_upload_step = tog_up
rr.status = StatusRec()
rr.status.running_programs = lambda: ["prepare"] if on[0] else []
rr.time = types.SimpleNamespace(sleep=tog_sleep, time=_time.time)
open(os.path.join(tdir, "(107)a.xlsx"), "w").close()
rr.excel_upload_together(make_ctx(), "그리드")
metric = rr.status.of("metric")
check("받는 엑셀은 들어오는 대로 (차례마다 새 파일만, 키보드·마우스 없이), 사이트 수집이 끝나고 새 파일이 없으면 멈춘다",
      [u[0] for u in ups] == [["(107)a.xlsx"], ["(108)b.xlsx"]] and all(u[1] for u in ups) and not rr.UPLOAD_NO_KEYS, str(ups))
check("업로드 차례 사이·끝에 새로 뜬 ERPia 창은 닫고 그 수를 결과에 알린다 (늦게 뜬 실패 팝업 - 그 파일은 이미 완료 폴더)",
      labels == ["업로드 사이 ", "업로드 사이 ", "업로드 끝 "] and metric and metric[-1][2:4] == (2, 2)
      and "업로드 사이 팝업 1개" in metric[-1][4]["note"], f"{labels} {metric[-1:]}")
ups.clear()


def last_hand_over():   # 수집이 마지막 사이트 파일을 넘기자마자 끝난다 (빈 차례와 '수집 끝' 확인 사이)
    open(os.path.join(tdir, "(109)c.xlsx"), "w").close()
    return []


rr.status.running_programs = last_hand_over
rr.excel_upload_together(make_ctx(), "그리드")
check("수집이 끝나기 직전에 넘긴 파일도 끝내기 전에 한 번 더 보고 올린다 (검토 10-20 - 웰라이프와 같은 규칙)",
      [u[0] for u in ups] == [["(109)c.xlsx"]], str(ups))
os.environ[rr.TOGETHER_ENV] = "1"
waits = []
rr.wellife.wait_prepare = lambda rr_, why: waits.append(why)
rr.status = StatusRec()
rr.status.TOGETHER_MODES = {"off": "순서대로", "excel": "함께 (엑셀 업로드)", "excel_import": "함께 (엑셀 업로드·자동 수집)"}
_saved_guard = getattr(rr.pl, "KEYS_GUARD", None)     # rr.pl 은 위에서 가짜로 바꿔 끼웠다
for mode, sales, want in (("excel", True, "excel"), ("excel_import", True, "excel_import"), ("excel", False, None), ("off", True, None)):
    rr.TOGETHER_MODE, rr.pl.KEYS_GUARD = None, contextlib.nullcontext
    waits.clear()
    rr.status.together_choice = lambda m=mode: m
    rr.together_setup(rr, {"Excel": sales})
    check(f"함께 띄운 루틴: 방식 '{mode}', 엑셀 수집 {'켬' if sales else '끔'} -> "
          + (f"받는 대로 올림 ('{want}'), 로그인 키 입력 동안 키보드 차례" if want else "사이트 수집이 끝나기를 기다린 뒤 예전처럼"),
          rr.TOGETHER_MODE == want and len(waits) == (0 if want else 1) and (rr.pl.KEYS_GUARD is not contextlib.nullcontext) == bool(want),
          f"{rr.TOGETHER_MODE} {waits}")
del os.environ[rr.TOGETHER_ENV]
rr.TOGETHER_MODE, rr.pl.KEYS_GUARD = None, contextlib.nullcontext
rr.together_setup(rr, {"Excel": True})
check("함께 띄운 루틴이 아니면 아무것도 바꾸지 않는다", rr.TOGETHER_MODE is None and rr.pl.KEYS_GUARD is contextlib.nullcontext)
rr.pl.KEYS_GUARD = _saved_guard
rr.wellife.on_top, rr.wellife.wait_prepare = _saved_w
for n, f in _saved_t.items():
    setattr(rr, n, f)
for n, f in _saved_s.items():
    setattr(rr, n, f)
for n, f in _saved_wl.items():
    setattr(rr.wellife, n, f)

# 출력 도중 꺼져 다시 돌면: 물류 관리 화면으로 가고, 이미 출력한 배송장은 다시 출력하지 않는다
_saved_o = {n: getattr(rr, n) for n in ("goto_logistics_screen", "prefetch_auto_ids", "apply_auto_mode", "run_print_step")}
out_acts = []
rr.goto_logistics_screen = lambda ctx: out_acts.append("goto") or "ok"
rr.prefetch_auto_ids = lambda *a: None
rr.apply_auto_mode = lambda *a: (None, True)
rr.run_print_step = lambda app, pid, hwnd, options=None, already_printed="continue": out_acts.append(already_printed) or "done"
for resume, want in ((None, ["continue"]), ("output", ["goto", "stop"])):
    out_acts.clear()
    ctx = make_ctx()
    ctx.options = {}
    ctx.results["logistics"] = "done"
    ctx.resume = resume
    rr.module_output(ctx)
    check(f"출력 resume={resume}: {want}", out_acts == want, str(out_acts))
for n, f in _saved_o.items():
    setattr(rr, n, f)

# 관리자 권한 ERPia: 일반 권한 RPA 는 다룰 수 없어 끄고 새로 띄운다
rr.status = StatusRec()
ADMIN, ELEV = [False], [True]
rr.status.is_admin = lambda: ADMIN[0]
rr.ec.process_elevated = lambda pid: ELEV[0]
check("관리자 ERPia + 일반 RPA -> 다룰 수 없음", rr.erpia_unreachable(4242) is True)
ADMIN[0] = True
check("RPA 가 관리자 권한이면 다룰 수 있다", rr.erpia_unreachable(4242) is False)
ADMIN[0], ELEV[0] = False, None
check("권한을 못 읽으면 끄지 않는다", rr.erpia_unreachable(4242) is False)
ELEV[0] = True

KILL, UAC = [], []
rr.ec.terminate_pid = lambda pid: KILL.append(pid) or None
ALIVE[0] = False
check("끌 수 있으면 끄고 꺼진 것을 확인", rr.close_elevated_erpia(4242) == (True, None) and KILL == [4242])
rr.ec.terminate_pid = lambda pid: "접근 거부"
rr.status.run_as_admin = lambda exe, args, cwd: UAC.append((exe, args)) or True
os.environ["RPA_UNATTENDED"] = "1"
res = rr.close_elevated_erpia(4242)
check("무인 실행: 접근 거부면 UAC 를 띄우지 않고 사유를 남겨 멈춘다", res[0] is False and "접근 거부" in res[1] and UAC == [], str(res))
os.environ.pop("RPA_UNATTENDED")
res = rr.close_elevated_erpia(4242)
check("사람이 띄운 실행: 관리자 권한 taskkill (UAC)", res == (True, None) and UAC == [("taskkill.exe", ["/F", "/PID", "4242"])], str(res))
ALIVE[0] = True
rr.time = types.SimpleNamespace(sleep=lambda *_: None, time=lambda: 10 ** 9 + len(KILL.append(0) or KILL) * 100,
                                strftime=_time.strftime)
rr.ec.terminate_pid = lambda pid: None
res = rr.close_elevated_erpia(4242)
check("끈다고 했는데 안 꺼지면 실패", res[0] is False and "종료되지 않았습니다" in res[1], str(res))
rr.time = types.SimpleNamespace(sleep=lambda *_: None, time=_time.time, strftime=_time.strftime)

POPEN = []
LOGGED = [True]
_saved_e = {n: getattr(rr, n) for n in ("load_exe_path", "subprocess", "erpia_logged_in")}
rr.erpia_logged_in = lambda pid: LOGGED[0]
rr.load_exe_path = lambda: r"C:\ERPia\ERPiaMain.exe"
PIDS, MINE = [4242], {4242}          # 떠 있는 ERPia / 그중 설정 계정 제목('업체 - 아이디')인 것 (사용자 2026-11-16)
_saved_ec13 = (rr.ec.erpia_pids, rr.ec.erpia_pids_titled, rr.pl.load_credentials, rr.pl.load_account)
rr.ec.erpia_pids = lambda: list(PIDS)
rr.ec.erpia_pids_titled = lambda title: [p for p in PIDS if p in MINE]
rr.pl.load_credentials = lambda: ("업체", "아이디", "비번")
rr.pl.load_account = lambda: ("업체", "아이디")
rr.ec.terminate_pid = lambda pid: (PIDS.remove(pid), ALIVE.__setitem__(0, False))[0]


def fake_popen(args, cwd=None):
    POPEN.append(args)
    PIDS.append(5555)


rr.subprocess = types.SimpleNamespace(Popen=fake_popen)
pid = rr.ensure_erpia_running()
check("ensure_erpia_running: 이미 로그인된 관리자 ERPia 는 끄고 새로 띄운 ERPia 의 PID", pid == 5555 and len(POPEN) == 1, f"{pid} {POPEN}")
ELEV[0] = False
POPEN.clear()
MINE.add(5555)                       # 새로 띄운 ERPia 에 로그인했다 - 제목이 설정 계정
check("같은 권한이면 떠 있는 ERPia 를 그대로", rr.ensure_erpia_running() == 5555 and POPEN == [])
PIDS[:] = [4343]                     # 다른 계정으로 로그인된 ERPia 만 떠 있다 (사람이 쓰는 것일 수 있다)
MINE.clear()
ALIVE[0] = True
ectx = rr.RoutineContext()
pid = rr.ensure_erpia_running(ectx)
check("다른 계정으로 로그인된 ERPia 는 두고 새로 띄운다 - 남의 것은 ctx.others 에 (사용자 2026-11-16)",
      pid == 5555 and len(POPEN) == 1 and ectx.others == {4343} and 4343 in PIDS, f"{pid} {POPEN} {ectx.others}")
POPEN.clear()
PIDS[:] = [4343, 4444]               # 로그인 창만 뜬 ERPia 가 둘 - 사람이 로그인하는 중일 수 있다
LOGGED[0] = False
pid = rr.ensure_erpia_running()
check("로그인 전 ERPia 라도 ERPia 가 여럿이면 거기에 로그인하지 않고 새로 띄운다 (검토 2026-11-17)",
      pid == 5555 and len(POPEN) == 1, f"{pid} {POPEN}")
PIDS[:] = [4343]
POPEN.clear()
check("로그인 전 ERPia 가 하나뿐이면 예전처럼 거기에 로그인한다", rr.ensure_erpia_running() == 4343 and POPEN == [], str(POPEN))
LOGGED[0] = True
POPEN.clear()
ELEV[0] = True
PIDS[:] = [4242]
MINE.add(4242)
ALIVE[0] = True
rr.ec.terminate_pid = lambda pid: "접근 거부"
os.environ["RPA_UNATTENDED"] = "1"
try:
    rr.ensure_erpia_running()
    res = None
except RuntimeError as e:
    res = str(e)
os.environ.pop("RPA_UNATTENDED")
check("못 끄면 새로 띄우지 않고 사유와 함께 멈춘다", res is not None and "종료하지 못했습니다" in res and POPEN == [], str(res))
PIDS[:] = [4242, 4343]               # 우리 관리자 ERPia(제목으로 앎) + 다른 계정 ERPia
KILLED = []
rr.ec.terminate_pid = lambda pid: (KILLED.append(pid), PIDS.remove(pid), ALIVE.__setitem__(0, False))[0]
pid = rr.ensure_erpia_running()
check("ERPia 가 여럿이어도 우리 관리자 ERPia 만 끄고 새로 띄운다 - 다른 계정 ERPia 는 그대로 (예전엔 멈춤, 사용자 2026-11-16)",
      pid == 5555 and KILLED == [4242] and 4343 in PIDS, f"{pid} {KILLED} {PIDS}")
POPEN.clear()
PIDS[:] = [4242]
MINE.clear()                         # 로그인 전 ERPia - 아직 어느 계정도 아니다
ALIVE[0] = True
LOGGED[0] = False
KILLED = []
rr.ec.terminate_pid = lambda pid: KILLED.append(pid)
try:
    rr.ensure_erpia_running()
    res = None
except RuntimeError as e:
    res = str(e)
check("관리자 ERPia 가 로그인 전(로그인 창)이면 끄지 않고 멈춘다 (사용자 10-14)",
      res is not None and "로그인 전" in res and KILLED == [] and POPEN == [], str(res))
_saved_cred = rr.pl.load_credentials
rr.pl.load_credentials = lambda: ("업체", "아이디", "비번")
lctx = rr.RoutineContext()
res = rr.module_login(lctx)
check("module_login: 로그인 전 관리자 ERPia 는 예외 없이 '실패' 와 사유 (프로그램 오류로 죽지 않음 - 10-14 실측)",
      res[0] == "failed" and "로그인 전" in res[1] and KILLED == [], str(res))
check("다른 계정 ERPia 가 있어 새로 실행했으면 ctx 에 표시 (로그인 실패 때 정리할 것)", getattr(ectx, "launched", False) is True)

# 검토 2026-11-17 (PR #47 댓글) - 비밀번호 없이 알아보기, 로그인 실패 때 새로 실행한 ERPia 정리, 로그인 창 기다리는 중 PID 바뀜
def _err(fn):
    try:
        fn()
    except Exception as e:      # noqa: BLE001 - 무엇이 났는지 본다
        return e


_saved_ls = pl.load_settings
pl.load_settings = lambda: {pl.LOGIN_SECTION: {"AdminCode": "업체", "ID": "아이디", "PW": ""}}
check("load_account: 비밀번호가 비어도 업체코드·아이디만 준다 (load_credentials 는 비밀번호가 없어 실패)",
      pl.load_account() == ("업체", "아이디") and isinstance(_err(pl.load_credentials), RuntimeError))
pl.load_settings = _saved_ls
_saved_lc = (rr.pl.load_credentials, rr.pl.load_account)
rr.pl.load_credentials = lambda: (_ for _ in ()).throw(RuntimeError("비밀번호를 풀 수 없음"))
PIDS[:], MINE = [4242], {4242}
check("my_erpia_pids: 비밀번호를 못 풀어도(사람이 로그인하는 PC) 제목으로 설정 계정 ERPia 를 찾는다", rr.my_erpia_pids() == [4242])
rr.pl.load_account = lambda: ("", "")
check("업체코드·아이디가 없으면 제목으로 찾지 않는다 (' - ' 제목을 찾지 않게)", rr.my_erpia_pids() == [])
rr.pl.load_credentials, rr.pl.load_account = _saved_lc
_saved_lg = rr._login
for case, launched, others, logged, result, want in (
        ("다른 계정 ERPia 가 있고 새로 실행한 ERPia 가 로그인 전", True, {4343}, False, "failed", [5555]),
        ("혼자 떠 있으면 다음 실행이 거기에 로그인 - 그대로", True, set(), False, "failed", []),
        ("떠 있던 ERPia 를 썼으면 그대로", False, {4343}, False, "failed", []),
        ("로그인은 됐으면(메인 창 못 잡음 등) 그대로", True, {4343}, True, "failed", []),
        ("로그인 성공이면 그대로", True, {4343}, False, "done", [])):
    KILLED = []
    rr.ec.terminate_pid = lambda pid: KILLED.append(pid)
    LOGGED[0] = logged
    rr._login = lambda c, result=result: (result, None)
    c = rr.RoutineContext()
    c.pid, c.others, c.launched = 5555, others, launched
    rr.module_login(c)
    check(f"로그인 실패 때 정리 - {case} (검토 2026-11-17)", KILLED == want, KILLED)
rr._login = _saved_lg
LOGGED[0] = False
_saved_wl = (rr.ec.pid_alive, rr.my_erpia_pids, rr.pl.find_login_window, rr.win32gui.IsWindowVisible)
rr.ec.pid_alive = lambda p: p != 7000                     # 기다리던 ERPia 가 끝났다 (로그인 전 자체 업데이트)
rr.my_erpia_pids = lambda others=None: [7001] if others == {4343} else []
rr.pl.find_login_window = lambda pid=None: types.SimpleNamespace(handle=40) if pid == 7001 else None
rr.win32gui.IsWindowVisible = lambda h: True
c = rr.RoutineContext()
c.pid, c.others = 7000, {4343}
state, obj = rr.wait_login_or_main(7000, c)
check("로그인 창을 기다리는 중 PID 가 바뀌면 우리 ERPia(남의 것 빼고)로 갈아타 이어간다 (검토 2026-11-17)",
      state == "login_window" and obj.handle == 40 and c.pid == 7001, str((state, c.pid)))
rr.ec.pid_alive, rr.my_erpia_pids, rr.pl.find_login_window, rr.win32gui.IsWindowVisible = _saved_wl
rr.pl.load_credentials = _saved_cred
LOGGED[0] = True
for n, f in _saved_e.items():
    setattr(rr, n, f)
rr.ec.erpia_pids, rr.ec.erpia_pids_titled, rr.pl.load_credentials, rr.pl.load_account = _saved_ec13

# ERPia 가 로그인 직후 스스로 업데이트해 다시 켜지며 로그인 창을 다시 띄우면 한 번 더 로그인한다 (triif 2026-11-13)
_saved_rl = {n: getattr(rr.pl, n, None) for n in ("load_credentials", "load_account", "login_flow", "find_login_window")}
_saved_rl2 = (rr.ensure_erpia_running, rr.wait_login_or_main, rr.RoutineContext.refresh, rr.win32gui.IsWindowVisible,
              getattr(rr.ec, "erpia_pids_titled", None))
FLOWS, REFRESH = [], [False, True]
rr.pl.load_credentials = lambda: ("업체", "아이디", "비번")
rr.pl.load_account = lambda: ("업체", "아이디")
rr.pl.login_flow = lambda a, u, p, log=None, pid=None: FLOWS.append(1) or {"status": "success"}
rr.pl.find_login_window = lambda pid=None: types.SimpleNamespace(handle=31)
rr.win32gui.IsWindowVisible = lambda h: True
rr.ensure_erpia_running = lambda ctx=None: 7828
rr.wait_login_or_main = lambda pid, ctx=None: ("login_window", types.SimpleNamespace(handle=30))
rr.ec.erpia_pids_titled = lambda title: [15260]      # 다시 켜진 ERPia - 아직 로그인 전이라도 시험에서는 제목으로 찾는다
rr.RoutineContext.refresh = lambda self: REFRESH.pop(0)
lctx = rr.RoutineContext()
res = rr.module_login(lctx)
check("ERPia 가 다시 켜져 로그인 창이 다시 뜨면 한 번 더 로그인하고 이어간다", res == ("done", None) and FLOWS == [1, 1] and lctx.pid == 15260,
      str((res, FLOWS, lctx.pid)))
FLOWS, REFRESH = [], [False]
rr.pl.find_login_window = lambda pid=None: None
res = rr.module_login(rr.RoutineContext())
check("로그인 창이 없으면 다시 로그인하지 않고 예전처럼 실패", res[0] == "failed" and "메인 화면" in res[1] and FLOWS == [1], str((res, FLOWS)))
for n, f in _saved_rl.items():
    if f is None:
        delattr(rr.pl, n)
    else:
        setattr(rr.pl, n, f)
(rr.ensure_erpia_running, rr.wait_login_or_main, rr.RoutineContext.refresh, rr.win32gui.IsWindowVisible, _fe) = _saved_rl2
if _fe is not None:
    rr.ec.erpia_pids_titled = _fe

LOGINS = []
_saved_ml = rr.module_login
rr.module_login = lambda ctx: LOGINS.append(1) or ("done", None)
rr.RoutineContext.attach = _real_attach
ctx = rr.RoutineContext()
rr.ec.erpia_pids_titled = lambda title: [4242]
ok, reason = ctx.attach()
check("로그인 모듈을 끈 채 관리자 ERPia 에 붙으려 하면 끄지 않고 사유를 남긴다 (끄는 것은 로그인할 때만)",
      ok is False and LOGINS == [] and "로그인 모듈" in reason, f"{ok} {reason}")
rr.module_login = _saved_ml
ELEV[0] = False
ALIVE[0] = True

print()
print("=== 12. 반복 회차 - 처리한 게 없으면 기록에 안 남긴다 (RPA_RUN_TRIGGER=repeat) ===")


class DoneRec(StatusRec):
    def __init__(self, done):
        super().__init__()
        self._done = done

    def done_modules(self):
        return self._done


rr.pl.load_routine_modules = lambda keys, *a: ({k: True for k in keys}, [])
rr.run_modules = lambda selected: ("success", None)
os.environ["RPA_RUN_TRIGGER"] = "repeat"
for done, keep, what in ((["login"], False, "로그인만 완료 (대상 없음) → 기록 안 남김"), (["login", "logistics"], True, "처리한 모듈이 있으면 남김")):
    rec = DoneRec(done); rr.status = rec
    rr.main()
    fin = rec.of("finish")[-1]
    check(what, fin == (("success", None) if keep else ("success", None, {"record": False})), str(fin))
rr.run_modules = lambda selected: ("stopped", "물류관리 실패")
rec = DoneRec(["login"]); rr.status = rec; rr.main()
check("실패한 반복 회차는 늘 남긴다", rec.of("finish")[-1] == ("stopped", "물류관리 실패"), str(rec.of("finish")))
os.environ["RPA_RUN_TRIGGER"] = "auto"
rr.run_modules = lambda selected: ("success", None)
rec = DoneRec(["login"]); rr.status = rec; rr.main()
check("정한 시각 실행은 대상 없음이어도 남긴다", rec.of("finish")[-1] == ("success", None), str(rec.of("finish")))
os.environ.pop("RPA_RUN_TRIGGER", None)

print("--- K2: 찾기 검색어는 글자 그대로")
typed_k2 = []
key_k2 = types.SimpleNamespace(element_info=types.SimpleNamespace(automation_id=rr.FIND_KEY_EDIT_ID), click_input=lambda: None,
                               type_keys=lambda keys, **kw: typed_k2.append((keys, kw)))
_saved_k2 = rr.open_find_dialog, rr.Application, rr.ec, rr.scan_column, rr.win32gui.PostMessage
rr.open_find_dialog = lambda pid, hwnd, geo: 5
rr.Application = lambda backend: types.SimpleNamespace(connect=lambda **k: types.SimpleNamespace(
    window=lambda handle: types.SimpleNamespace(descendants=lambda control_type: [key_k2])))
rr.ec = types.SimpleNamespace(ensure_foreground=lambda h: True, literal_keys=__import__("erpia_common").literal_keys)
rr.scan_column = lambda geo, col: []
rr.win32gui.PostMessage = lambda *a: None
rr.find_jump_to_code(1, 2, None, 0, "A (1)+B^2", None)
rr.open_find_dialog, rr.Application, rr.ec, rr.scan_column, rr.win32gui.PostMessage = _saved_k2
check("K2: 공백·괄호·+ ^ 가 있는 상품코드도 찾기 칸에 글자 그대로 (조합키로 읽히지 않게)",
      typed_k2 == [("^a" + "A {(}1{)}{+}B{^}2" + "{ENTER}", {"set_foreground": True, "with_spaces": True})], str(typed_k2))

print("=== 누르기 안전장치 press - 웰라이프 click 과 같다 (사용자 2026-11-19) ===")


_saved_p = (rr.wellife.front, rr.wellife.clear_point, rr.win32process, rr.Desktop)
rr.press = _real_press
pressed_p, seen_p = [], []
rr.win32process = types.SimpleNamespace(GetWindowThreadProcessId=lambda h: (1, 4242))
rr.Desktop = lambda backend=None: types.SimpleNamespace(window=lambda handle: f"창{handle}")
rr.wellife.front = lambda rr_, ctx, what: seen_p.append(("front", ctx.hwnd, ctx.pid, what))
rr.wellife.clear_point = lambda rr_, ctx, el, what, pt=None: seen_p.append(("clear", what, pt)) or (pt or (55, 66))
el_p = types.SimpleNamespace(rectangle=lambda: types.SimpleNamespace(left=10, top=20),
                             click_input=lambda **k: pressed_p.append(("click", k)),
                             double_click_input=lambda **k: pressed_p.append(("double", k)))
rr.press(777, el_p, "저장 단추")
rr.press(777, el_p, "그리드 우클릭", coords=(5, 6), button="right")
rr.press(777, el_p, "경계 행", pressed="shift")
rr.press(777, el_p, "목록 항목", double=True)
check("press: 앞으로·잠김 확인(front) → 누를 자리 확인(clear_point, 덮개) → 확인한 그 점을 누른다 (button·pressed·더블클릭·상대 좌표 그대로)",
      seen_p[:2] == [("front", 777, 4242, "저장 단추"), ("clear", "저장 단추", None)]
      and ("clear", "그리드 우클릭", (15, 26)) in seen_p
      and pressed_p == [("click", {"coords": (55, 66), "absolute": True}), ("click", {"coords": (15, 26), "absolute": True, "button": "right"}),
                        ("click", {"coords": (55, 66), "absolute": True, "pressed": "shift"}),
                        ("click", {"coords": (55, 66), "absolute": True, "double": True})],     # double_click_input 은 absolute 를 못 받는다 (검토 11-20)
      f"{seen_p} {pressed_p}")
pressed_p.clear()
rr.wellife.clear_point = covered
try:
    rr.press(777, el_p, "저장 단추")
    res = None
except rr.wellife.Stop as e:
    res = (e.result, str(e))
check("press: 누를 자리를 다른 창이 덮으면 누르지 않고 Stop", res and res[0] == "failed" and "시험 덮개" in res[1] and not pressed_p, f"{res} {pressed_p}")
# 처리 시작 표시(rpa_status.began_work)는 확인을 지난 뒤 누르기 바로 앞에만 - 덮여서 안 누른 반복 회차가 '처리 도중' 으로 반복을 멈추지 않게 (Codex 검토 11-25)
rr.status = StatusRec()
try:
    rr.press(777, el_p, "저장 단추", work=True)
except rr.wellife.Stop:
    pass
check("press(work=True): 덮여서 누르지 않으면 처리 시작을 적지 않는다", rr.status.of("began_work") == [] and not pressed_p, str(rr.status.calls))
rr.wellife.clear_point = lambda rr_, ctx, el, what, pt=None, allow=(): (55, 66)
rr.press(777, el_p, "저장 단추", work=True)
rr.press(777, el_p, "체크 칸")
check("press(work=True): 누르기 바로 앞에 적고, 보통 누르기(체크 칸 등)는 적지 않는다",
      rr.status.of("began_work") == [()] and len(pressed_p) == 2, f"{rr.status.calls} {pressed_p}")
pressed_p.clear()
# 우클릭 메뉴 항목도 웰라이프 press_menu_item 처럼 잠김·덮개를 보고 누른다 (Codex 검토 11-25 - 예전엔 찾자마자 눌렀다)
_saved_cm = (rr.ec.screen_locked, rr.wellife._top_window, rr.wellife.COVER_WAIT_SECONDS, rr.wellife._window_who, rr.win32gui, rr.send_keys)
cm_keys, cm_clicks, CM = [], [], {"top": 9, "locked": False}
rr.ec.screen_locked = lambda: CM["locked"]
rr.wellife._top_window = lambda rr_, pt: CM["top"]
rr.wellife.COVER_WAIT_SECONDS = 0.2
rr.wellife._window_who = lambda rr_, h: f"창{h}"
rr.win32gui = types.SimpleNamespace(GetForegroundWindow=lambda: 5)
rr.send_keys = cm_keys.append
cm_item = types.SimpleNamespace(rectangle=lambda: types.SimpleNamespace(left=100, top=200, right=140, bottom=220),
                                click_input=lambda **k: cm_clicks.append(k))
rr.status = StatusRec()
rr.press_context_menu_item(4242, cm_item, 9, "배송보류")
rr.press_context_menu_item(4242, cm_item, 9, "선택영역 체크")
check("우클릭 메뉴 항목: 맨 위 창이 그 메뉴면 확인한 점을 누르고, 데이터를 바꾸는 항목('배송보류')만 처리 시작을 적는다",
      cm_clicks == [{"coords": (120, 210), "absolute": True}] * 2 and rr.status.of("began_work") == [()], f"{cm_clicks} {rr.status.calls}")
cm_clicks.clear()
rr.status = StatusRec()
CM["top"] = 77
try:
    rr.press_context_menu_item(4242, cm_item, 9, "배송보류")
    res = None
except rr.wellife.Stop as e:
    res = (e.result, str(e))
check("우클릭 메뉴 항목: 다른 창이 덮으면 누르지 않고 멈추고, 맨 앞이 ERPia 면 ESC 로 메뉴를 닫는다 (처리 시작도 안 적는다)",
      res and res[0] == "failed" and "창77" in res[1] and not cm_clicks and cm_keys == ["{ESC}"] and not rr.status.of("began_work"),
      f"{res} {cm_clicks} {cm_keys}")
cm_keys.clear()
CM.update(top=9, locked=True)
try:
    rr.press_context_menu_item(4242, cm_item, 9, "개별 배송(B)")
    res = None
except rr.wellife.Stop as e:
    res = (e.result, str(e))
check("우클릭 메뉴 항목: 화면이 잠겼으면 누르지 않고 멈춘다", res and res[0] == "stopped" and "화면이 잠겨" in res[1] and not cm_clicks, f"{res}")
(rr.ec.screen_locked, rr.wellife._top_window, rr.wellife.COVER_WAIT_SECONDS, rr.wellife._window_who, rr.win32gui, rr.send_keys) = _saved_cm
seen_p.clear()
rr.wellife.clear_point = lambda rr_, ctx, el, what, pt=None, allow=(), esc=True: seen_p.append(("clear", what, ctx.hwnd, set(allow), esc)) or (55, 66)
_saved_ow = (rr.owner_window, rr.ec.ensure_foreground, rr.ec.screen_locked)
OWN = {"h": 888}
rr.owner_window = lambda el: OWN["h"]
rr.ec.ensure_foreground = lambda h: seen_p.append(("앞으로", h)) or True
rr.ec.screen_locked = lambda: False
rr.press(777, el_p, "팝업 단추", popup=True)
OWN["h"] = 777          # 메인 창 안에 그려진 팝업의 단추 - 지금처럼 메인 창만
rr.press(777, el_p, "메인 창 팝업 단추", popup=True)
rr.press(777, el_p, "저장 단추")
check("press(popup=True): 따로 뜬 팝업 창의 단추는 그 창을 앞으로 하고 그 창을 기준으로(맨 위·창 안) 덮개를 보며 ESC 는 보내지 않는다 - "
      "메인 창을 앞으로 하지 않는다(모달이 앞을 쥔다) (검토 11-25, 리뷰 2차). 메인 창 안의 단추·다른 단추는 메인 창 기준 그대로",
      [x for x in seen_p if x[0] in ("clear", "앞으로", "front")] ==
      [("앞으로", 888), ("clear", "팝업 단추", 888, set(), False), ("front", 777, 4242, "메인 창 팝업 단추"),
       ("clear", "메인 창 팝업 단추", 777, set(), True), ("front", 777, 4242, "저장 단추"), ("clear", "저장 단추", 777, set(), True)]
      and pressed_p == [("click", {"coords": (55, 66), "absolute": True})] * 3, f"{seen_p} {pressed_p}")
pressed_p.clear()
OWN["h"] = 888
rr.ec.ensure_foreground = lambda h: False
try:
    rr.press(777, el_p, "팝업 단추", popup=True)
    res = None
except rr.wellife.Stop as e:
    res = (e.result, str(e))
check("press(popup=True): 따로 뜬 팝업 창을 앞으로 못 가져오면 누르지 않고 멈춘다 - wellife.front 와 같은 안전장치 (교차 검증 11-25)",
      res and res[0] == "failed" and "앞으로 가져오지 못해" in res[1] and not pressed_p, f"{res} {pressed_p}")
# 팝업 갈래를 진짜 clear_point 로: 맨 위가 그 팝업일 때만 누르고, 메인 창이 맨 위이거나 작은 창이 덮으면 누르지 않으며 ESC 도 보내지 않고,
# 누를 자리가 그 팝업 사각형 밖이면 누르지 않는다 (리뷰 2차 11-25 - 예전엔 메인 창 기준이라 메인 창이 맨 위여도 눌렀다)


class _R:
    def __init__(self, left, top, right, bottom):
        self.left, self.top, self.right, self.bottom = left, top, right, bottom

    def width(self):
        return self.right - self.left

    def height(self):
        return self.bottom - self.top


_w = rr.wellife
_saved_cp = (_w.clear_point, _w._top_window, _w.mouse, _w.COVER_WAIT_SECONDS, _w._window_pid, _w._title, _w._foreground, _w._window_who,
             rr.send_keys, rr.Desktop)
_w.clear_point = _saved_p[1]       # 진짜
TOPQ, keys_q = {"h": 888}, []
_w._top_window = lambda rr_, pt: TOPQ["h"]
_w.mouse = types.SimpleNamespace(move=lambda coords: None)
_w.COVER_WAIT_SECONDS = 0.2
_w._window_pid, _w._title, _w._foreground = (lambda rr_, h: 4242), (lambda rr_, h: ""), (lambda rr_: 5)   # 제목 없는 ERPia 작은 창, ERPia 가 맨 앞
_w._window_who = lambda rr_, h: f"창{h}"
rr.send_keys = keys_q.append
rr.Desktop = lambda backend=None: types.SimpleNamespace(window=lambda handle: types.SimpleNamespace(
    rectangle=lambda: _R(100, 100, 400, 300) if handle == 888 else _R(0, 0, 1000, 800)))
rr.ec.ensure_foreground, rr.ec.screen_locked = (lambda h: True), (lambda: False)
el_q = types.SimpleNamespace(rectangle=lambda: _R(200, 150, 260, 170), click_input=lambda **k: pressed_p.append(("click", k)))
pressed_p.clear()
rr.press(777, el_q, "팝업 단추", popup=True)
ok_top = pressed_p == [("click", {"coords": (230, 160), "absolute": True})]
res_q = []
for _top in (777, 999):          # 메인 창이 맨 위 / 제목 없는 ERPia 작은 창이 덮음
    TOPQ["h"] = _top
    pressed_p.clear()
    try:
        rr.press(777, el_q, "팝업 단추", popup=True)
        res_q.append("누름")
    except rr.wellife.Stop as e:
        res_q.append(e.result)
check("press(popup=True) 진짜 덮개 확인: 맨 위가 그 팝업이면 누르고, 메인 창이 맨 위이거나 작은 창이 덮으면 누르지 않으며 ESC 도 보내지 않는다 (리뷰 2차 11-25)",
      ok_top and res_q == ["failed", "failed"] and not pressed_p and keys_q == [], f"{ok_top} {res_q} {keys_q}")
TOPQ["h"] = 888
el_far = types.SimpleNamespace(rectangle=lambda: _R(500, 500, 560, 520), click_input=lambda **k: pressed_p.append(("click", k)))
try:
    rr.press(777, el_far, "팝업 단추", popup=True)
    res = "누름"
except rr.wellife.Stop as e:
    res = str(e)
check("  누를 자리가 그 팝업 사각형 밖이면(메인 창 안이어도) 누르지 않는다", "창 안에 보이지 않아" in res and not pressed_p, res)
(_w.clear_point, _w._top_window, _w.mouse, _w.COVER_WAIT_SECONDS, _w._window_pid, _w._title, _w._foreground, _w._window_who,
 rr.send_keys, rr.Desktop) = _saved_cp
(rr.owner_window, rr.ec.ensure_foreground, rr.ec.screen_locked) = _saved_ow
_saved_ga = rr.win32gui
rr.win32gui = types.SimpleNamespace(GetAncestor=lambda h, f: {55: 888, 66: 777}.get(h, 0))
_own_el = lambda h, top=None: types.SimpleNamespace(element_info=types.SimpleNamespace(handle=h),
                                                    top_level_parent=lambda: types.SimpleNamespace(handle=top))
check("owner_window: 단추 창의 최상위 창 (GA_ROOT), 창 핸들이 없는 단추는 그 최상위 부모로, 못 읽으면 None",
      rr.owner_window(_own_el(55)) == 888 and rr.owner_window(_own_el(None, 66)) == 777 and rr.owner_window(object()) is None)
rr.win32gui = _saved_ga
_src_rr = Path(_rr.__file__).read_text(encoding="utf-8")
check("팝업 단추 누르기는 popup=True 로 (이어 뜨는 팝업·배송보류 확인 팝업 둘)",
      'press(hwnd, btn, "팝업 단추", popup=True)' in _src_rr and _src_rr.count('"배송보류 확인 팝업 단추", popup=True)') == 2)
rr.wellife.front, rr.wellife.clear_point, rr.win32process, rr.Desktop = _saved_p
# 메인 창 안을 누르는 자리는 press 로 (덮개·잠김·앞으로) - 대화상자·팝업 창 단추·스크롤 단추는 그대로
GUARDED = {"_press_icon": "target.click_input(", "sort_grid_by_status_desc": "header.click_input(",
           "grid_jump_to_bottom": "cell.click_input(", "right_click_element_and_select": "element.click_input(",
           "select_abnormal_range_and_check": "_el.click_input(", "right_click_grid_and_select": "grid.click_input(",
           "header_check_all": "header.click_input(", "click_toolbar_button": "b.click_input(",
           "close_follow_up_popups": "btn.click_input(", "click_subtab": "el.click_input(",
           "sort_grid_ascending_by": "header.click_input(", "open_find_dialog": "top_y).click_input(",
           "select_code_range_and_check": ".click_input(", "run_stock_review_step": ".click_input(",
           "click_button_by_auto_id": "btn.click_input(", "run_hold_logistics_step": ".click_input(",
           }    # 머리글 전체선택(select_all_and_verify·select_all_by_header_checkbox)은 header_check_all 이 누른다
_src_p = open(rr.__file__, encoding="utf-8").read()     # 앞 절들이 바꿔 끼운 가짜가 아니라 파일의 함수 본문을 본다


def _body(name):
    s = _src_p.find(f"\ndef {name}(")
    if s < 0:
        return ""
    e = _src_p.find("\ndef ", s + 5)
    return _src_p[s:e if e > 0 else None]


left_p = [n for n, s in GUARDED.items() if s in _body(n) or "press(" not in _body(n)]
check("메인 창 안을 누르는 자리(화면 이동 아이콘·머리글·체크 칸·도구 단추·행 선택·우클릭·물류 단추)는 모두 press 로 누른다", not left_p, left_p)

print("=== 따로 뜬 ERPia 팝업 창 - 화면 이동 (사용자 2026-11-20: 닫고 다음 단계로) ===")
_body_g = _body("goto_screen_by_icon")
check("화면 이동 아이콘을 누르기 전에 따로 뜬 팝업 창을 닫는다",
      "clear_separate_popups" in _body_g and "_press_icon(" in _body_g
      and _body_g.index("clear_separate_popups") < _body_g.index("_press_icon("), "")
_saved_g = (rr.get_active_main_tab, rr.wellife.clear_separate_popups, getattr(rr.wellife, "TAB_AFTER_POPUP_SECONDS", 5))
rr.wellife.TAB_AFTER_POPUP_SECONDS = 0.3       # 닫은 뒤 더 보는 시간 (실제 5초) - 시험에서는 짧게
rr.get_active_main_tab = lambda app, hwnd: "물류 관리"        # 눌렀는데 화면이 안 바뀐다 (팝업이 막고 있다)
seen_g = []
rr.wellife.clear_separate_popups = lambda rr_, ctx, after, ignore=(): seen_g.append(after) or (1 if len(seen_g) >= 2 else 0)
t0 = _time.time()
res = _real_wait_tab(None, 777, "주문매핑", timeout=150, interval=0.01, ctx=make_ctx())
check("화면 이동을 기다리는 동안 따로 뜬 팝업 창을 닫았으면 잠깐(실제 5초)만 더 보고 2.5분을 기다리지 않고 돌아온다 "
      "(그 클릭은 먹지 않았다 - 11-19 B10: 15:45:56→15:48:28 헛기다림, 더 닫아도 늘리지 않는다)",
      res[0] is False and _time.time() - t0 < 2 and len(seen_g) >= 2, f"{res} {seen_g}")
reads_g = []
rr.get_active_main_tab = lambda app, hwnd: reads_g.append(1) or ("물류 관리" if len(reads_g) < 4 else "주문매핑 매출처리")
seen_g.clear()
rr.wellife.clear_separate_popups = lambda rr_, ctx, after, ignore=(): seen_g.append(after) or (1 if len(seen_g) == 2 else 0)
res = _real_wait_tab(None, 777, "주문매핑", timeout=150, interval=0.01, ctx=make_ctx())
check("닫은 뒤 다시 본 탭이 그 화면이면 도착 - 화면이 열리면서 뜬 안내였다 (다시 누르지 않는다, 검토 11-20)", res == (True, "주문매핑 매출처리"), str(res))
_saved_dead = (rr.win32gui.IsWindow, rr.acquire_main_window)
hwnds_g, reads_g = [], []
rr.get_active_main_tab = lambda app, hwnd: reads_g.append(hwnd) or (None if hwnd == 777 else "주문매핑 매출처리")
rr.win32gui.IsWindow = lambda h: h != 777
rr.acquire_main_window = lambda pid, tries=12, others=None: (778, "새 앱", "새 창", pid)
rr.wellife.clear_separate_popups = lambda rr_, ctx, after, ignore=(): hwnds_g.append(ctx.hwnd) or 0
ctx_g = make_ctx()
res = _real_wait_tab(None, 777, "주문매핑", timeout=5, interval=0.01, ctx=ctx_g)
rr.win32gui.IsWindow, rr.acquire_main_window = _saved_dead
check("메인 창 핸들이 죽었으면 따로 뜬 팝업 보기보다 먼저 새 메인 창을 잡는다 - 죽은 핸들로 보면 새 메인 창을 팝업으로 본다 (검토 11-20)",
      hwnds_g[:1] == [778] and res[0] is True and ctx_g.hwnd == 778, f"{hwnds_g} {res}")
rr.get_active_main_tab, rr.wellife.clear_separate_popups, rr.wellife.TAB_AFTER_POPUP_SECONDS = _saved_g
_saved_r = (rr.wellife.numbered_tabs, rr.wellife.clear_separate_popups, rr.find_by_text, rr.press, rr.wait_for_active_main_tab)
icon_r, pressed_r, waits_r = types.SimpleNamespace(rectangle=lambda: "아이콘 자리"), [], []
ctx_r = make_ctx()
ctx_r.window = lambda: types.SimpleNamespace(rectangle=lambda: None)
rr.wellife.numbered_tabs = lambda ctx: []
rr.wellife.clear_separate_popups = lambda rr_, ctx, after, ignore=(): 0
found_r = []
rr.find_by_text = lambda win, text, control_types=(): found_r.append(types.SimpleNamespace(rectangle=lambda: "아이콘 자리")) or found_r[-1]
rr.press = lambda hwnd, el, what, **k: pressed_r.append(el)


def wait_r(app, hwnd, keyword, timeout=20, interval=1.0, ctx=None):
    waits_r.append(keyword)
    if len(waits_r) == 1:          # 기다리는 동안 팝업을 닫았다
        ctx.popups_closed = getattr(ctx, "popups_closed", 0) + 1
        return False, "물류 관리"
    return True, "주문매핑 매출처리"


rr.wait_for_active_main_tab = wait_r
res = rr.goto_screen_by_icon(ctx_r, "lcg_OrderCollect", "주문매핑", "주문매핑")
(rr.wellife.numbered_tabs, rr.wellife.clear_separate_popups, rr.find_by_text, rr.press, rr.wait_for_active_main_tab) = _saved_r
check("이동을 기다리는 동안 팝업을 닫았으면 아이콘을 다시 찾아 한 번 더 누른다 (옛 아이콘이 아니라 - 그새 창이 다시 만들어졌을 수 있다, 검토 11-20)",
      res == "ok" and len(pressed_r) == 2 and len(waits_r) == 2 and pressed_r[1] is found_r[-1] and pressed_r[0] is not pressed_r[1],
      f"{res} {pressed_r} {found_r}")

print("=== 화면 이동 아이콘: 찾은 뒤 누르기 전에 메인 창이 다시 만들어지면 (검토 2026-11-20) ===")
_saved_d = (rr.wellife.numbered_tabs, rr.wellife.clear_separate_popups, rr.find_by_text, rr.press, rr.wait_for_active_main_tab,
            rr.win32gui.IsWindow, rr.acquire_main_window)
rr.wellife.numbered_tabs = lambda ctx: []
rr.wellife.clear_separate_popups = lambda rr_, ctx, after, ignore=(): 0
rr.wait_for_active_main_tab = lambda app, hwnd, kw, timeout=20, interval=1.0, ctx=None: (True, "주문매핑 매출처리")
rr.acquire_main_window = lambda pid, tries=12, others=None: (778, types.SimpleNamespace(window=lambda handle: f"창{handle}"), f"창778", pid)
dead_d, found_d, pressed_d = set(), [], []
rr.win32gui.IsWindow = lambda h: h not in dead_d
rr.find_by_text = lambda win, text, control_types=(): found_d.append(win) or types.SimpleNamespace(rectangle=lambda: "자리", win=win.name)


def press_d(hwnd, el, what, **k):
    if hwnd in dead_d:      # 죽은 창 - 진짜 press 는 앞으로 못 가져와 멈춘다
        raise rr.wellife.Stop("failed", f"{what}: ERPia 창을 앞으로 가져오지 못해 누르지 않고 중단하였습니다.")
    pressed_d.append((hwnd, el.win))


def run_d(die_at_press):
    dead_d.clear(); found_d.clear(); pressed_d.clear()
    ctx_d = make_ctx()
    ctx_d.window = lambda: types.SimpleNamespace(rectangle=lambda: None, name=f"창{ctx_d.hwnd}")
    if die_at_press:            # 누르는 순간 죽었다 (IsWindow 는 살아 보였다)
        def press_dying(hwnd, el, what, **k):
            if hwnd == 777 and 777 not in dead_d:
                dead_d.add(777)
            return press_d(hwnd, el, what, **k)
        rr.press = press_dying
    else:                       # 찾은 뒤 누르기 전에 죽었다
        rr.press = press_d
        _ft = rr.find_by_text
        rr.find_by_text = lambda win, text, control_types=(): (dead_d.add(777), _ft(win, text, control_types))[1]
    try:
        return rr.goto_screen_by_icon(ctx_d, "lcg_OrderCollect", "주문매핑", "주문매핑", wait_seconds=3), pressed_d[:]
    except rr.wellife.Stop as e:
        return ("Stop", str(e)), pressed_d[:]
    finally:
        rr.find_by_text = lambda win, text, control_types=(): found_d.append(win) or types.SimpleNamespace(rectangle=lambda: "자리", win=win.name)


for die, name in ((False, "찾은 뒤 누르기 전에 창이 죽었으면"), (True, "누르는 순간 창이 죽어 press 가 '앞으로 못 가져옴' 으로 멈추면")):
    res, pressed = run_d(die)
    check(f"{name} 기존 복구 갈래로 - 메인 창을 다시 잡고 아이콘을 다시 찾아 새 창에서 누른다", res == "ok" and pressed == [(778, "창778")],
          f"{res} {pressed}")
dead_d.clear()


def press_covered(hwnd, el, what, **k):
    raise rr.wellife.Stop("failed", f"{what}: 시험 덮개")


rr.press = press_covered
rr.find_by_text = lambda win, text, control_types=(): types.SimpleNamespace(rectangle=lambda: "자리")
try:
    res = rr.goto_screen_by_icon(make_ctx(), "lcg_OrderCollect", "주문매핑", "주문매핑", wait_seconds=3)
except rr.wellife.Stop as e:
    res = ("Stop", str(e))
check("살아 있는 창에서 멈춘 것(덮개·잠김)은 복구하지 않고 그대로 멈춘다", res[0] == "Stop" and "시험 덮개" in res[1], str(res))
(rr.wellife.numbered_tabs, rr.wellife.clear_separate_popups, rr.find_by_text, rr.press, rr.wait_for_active_main_tab,
 rr.win32gui.IsWindow, rr.acquire_main_window) = _saved_d

print("=== 메인 창 안 팝업 [예]/[확인] - 창 안에 보이는 단추만 (검토 2026-11-20) ===")
_saved_ok = (rr.find_popup_ok_button, rr.find_popup_buttons)
rr.find_popup_ok_button, rr.find_popup_buttons = _real_ok_button, _real_popup_buttons


def _rect(left, top, w=60, h=20):
    return types.SimpleNamespace(left=left, top=top, right=left + w, bottom=top + h, width=lambda: w, height=lambda: h)


hidden_ok = types.SimpleNamespace(window_text=lambda: "확인", rectangle=lambda: _rect(-1900, 300))     # 숨은 화면 (창 밖)
empty_ok = types.SimpleNamespace(window_text=lambda: "확인(O)", rectangle=lambda: _rect(0, 0, 0, 0))
shown_ok = types.SimpleNamespace(window_text=lambda: "예(Y)", rectangle=lambda: _rect(500, 400))
win_ok = types.SimpleNamespace(rectangle=lambda: _rect(0, 0, 1920, 1040),
                               descendants=lambda control_type=None: [hidden_ok, empty_ok, shown_ok])
check("find_popup_ok_button 은 창 안에 보이는 [예]/[확인] 만 고른다 - 숨은 화면의 [확인] 을 고르면 press 가 '창 안에 보이지 않아' 로 멈춘다 "
      "(물류대기 저장·물류관리·재고검토 추가 팝업, 검토 11-20)", rr.find_popup_ok_button(win_ok) is shown_ok)
win_ok.descendants = lambda control_type=None: [hidden_ok]
check("창 안에 [예]/[확인] 이 없으면 None", rr.find_popup_ok_button(win_ok) is None)
rr.find_popup_ok_button, rr.find_popup_buttons = _saved_ok

print("=== 실패면 그 단계에서 멈춤 (사용자 2026-11-23) - 물류대기 재고검토·출력·물류관리 ===")
_SV = ("click_subtab", "get_onscreen_tables", "grid_overlay_count", "click_toolbar_button", "wait_grid_spinner_gone",
       "collect_shortage_rows", "_column_scan_geometry", "find_bottom_code_column_by_header", "checkbox_column_x",
       "find_top_qty_cell_by_code", "find_row_cell_by_key", "legacy_value", "press", "prepare_bottom_checks", "visible_child_windows",
       "right_click_element_and_select", "status", "time", "run_stock_review_step", "scroll_grid_right_to_column", "run_hold_save",
       "sort_grid_by_status_desc", "get_status_column_geometry", "get_row_height", "grid_jump_to_bottom", "wait_top_hwnd",
       "connect_dialog", "find_printer_combo", "combo_value", "wait_save_dialog", "save_dialog_to_jobs", "find_popup_buttons",
       "collect_popup_text", "click_popup_ok", "find_popup_ok_button", "popup_says")
_saved_sv = {n: getattr(rr, n) for n in _SV}
rr.time = types.SimpleNamespace(sleep=lambda s: None, time=_time.time)
rr.status = StatusRec()
SR = {}
_g = lambda top: types.SimpleNamespace(rectangle=lambda: types.SimpleNamespace(top=top, left=0, right=10, bottom=top + 5))  # noqa: E731


def run_sr(**kw):
    SR.clear()
    SR.update(tab=True, tables=2, query=True, targets=[(("A",), "1"), (("B",), "2")], bottom=True, cell=True, anchor_fail=None,
              menu_fail=None, pressed=[], held=[])
    SR.update(kw)
    rr.click_subtab = lambda app, hwnd, name: SR["tab"]
    def _tables(win):   # late: 탭을 연 직후 몇 번은 표가 1개만 보인다 (늦게 그려짐)
        if SR.get("late"):
            SR["late"] -= 1
            return [_g(10)]
        return [_g(10), _g(300)][:SR["tables"]]
    rr.get_onscreen_tables = _tables
    rr.grid_overlay_count = lambda hwnd, grid: 0
    rr.click_toolbar_button = lambda win, hwnd, text, work=False: SR["query"]
    rr.wait_grid_spinner_gone = lambda *a, **k: True
    rr.collect_shortage_rows = lambda hwnd, grid: (SR["targets"], SR["bottom"])
    rr._column_scan_geometry = lambda grid, col: (1, 2)
    rr.find_bottom_code_column_by_header = lambda grid: "상품코드"
    rr.checkbox_column_x = lambda grid: 5
    rr.find_top_qty_cell_by_code = lambda a, b, code: types.SimpleNamespace(v="1", rectangle=lambda: "칸") if SR["cell"] else None
    rr.find_row_cell_by_key = lambda hwnd, grid, key, col: None
    rr.legacy_value = lambda el: el.v
    rr.press = lambda hwnd, el, what, **k: SR["pressed"].append(what)
    rr.prepare_bottom_checks = lambda pid, hwnd, grid, code, col, geo, cbx: (
        (None, False) if code == SR["anchor_fail"] else (types.SimpleNamespace(code=code), False))
    rr.visible_child_windows = lambda hwnd: {}
    rr.right_click_element_and_select = lambda pid, hwnd, el, text: el.code != SR["menu_fail"] and (SR["held"].append(el.code) or True)
    try:
        return rr.run_stock_review_step(make_ctx().app, 4242, 777)
    except rr.wellife.Stop as e:
        return ("Stop", e.result, str(e))


res = run_sr()
check("재고검토: 모두 처리하면 (처리, 전체)", res == (2, 2) and SR["held"] == ["A", "B"], f"{res} {SR}")
res = run_sr(anchor_fail="B")
check("재고검토: 하단에서 그 상품 줄을 못 골랐으면 넘어가지 않고 그 자리에서 실패로 멈춘다 - 사유에 상품코드·앞서 보류해 이미 저장된 수 (사용자 11-23)",
      res[:2] == ("Stop", "failed") and "상품코드 B" in res[2] and "1건" in res[2] and SR["held"] == ["A"], f"{res} {SR['held']}")
res = run_sr(menu_fail="A")
check("재고검토: 우클릭 '배송보류' 를 못 하면 넘어가지 않고 실패로 멈춘다", res[:2] == ("Stop", "failed") and "배송보류" in res[2]
      and SR["held"] == [], str(res))
res = run_sr(cell=False)
check("재고검토: 상단에서 그 행을 다시 못 찾으면 실패로 멈춘다", res[:2] == ("Stop", "failed") and "다시 찾지 못" in res[2], str(res))
res = run_sr(targets=[(("",), "1")])
check("재고검토: 상단 행의 상품코드를 못 읽으면 실패로 멈춘다", res[:2] == ("Stop", "failed") and "상품코드를 읽지 못" in res[2], str(res))
res = run_sr(query=False)
check("재고검토: 조회(F) 를 못 누르면 옛 화면으로 보류하지 않고 실패로 멈춘다", res[:2] == ("Stop", "failed") and "조회" in res[2]
      and not SR["pressed"], str(res))
_saved_tw = rr.wellife.TABLE_WAIT_SECONDS
rr.wellife.TABLE_WAIT_SECONDS = 0.3
res = run_sr(tables=1)
check("재고검토: 탭은 있는데 기다려도 그리드를 못 찾으면 실패로 멈춘다 (일반 탭 조회·저장을 재고검토 탭에서 누르지 않게)",
      res[:2] == ("Stop", "failed") and "그리드" in res[2] and "기다림" in res[2], str(res))
rr.wellife.TABLE_WAIT_SECONDS = 5
res = run_sr(late=3)
check("재고검토: 탭을 연 직후 표가 늦게 그려져도 기다렸다가 이어 간다 - 거짓 실패로 물류대기가 멈추지 않게 (검토 11-25)",
      res == (2, 2) and SR["held"] == ["A", "B"], f"{res}")
rr.wellife.TABLE_WAIT_SECONDS = _saved_tw
res = run_sr(bottom=False)
check("재고검토: 상단을 끝까지 못 훑었으면 보류를 하나도 하지 않고 실패로 멈춘다 (빠진 부족수량 건이 보류 없이 저장되지 않게)",
      res[:2] == ("Stop", "failed") and "끝까지" in res[2] and not SR["pressed"] and not SR["held"], str(res))
if rr.STOCK_EXCLUDED_CODES:
    res = run_sr(targets=[((next(iter(rr.STOCK_EXCLUDED_CODES)),), "1"), (("A",), "1")])
    check("재고검토: 제외 상품코드는 실패가 아니다 - 넘어간다", res == (1, 2) and SR["held"] == ["A"], f"{res} {SR['held']}")
res = run_sr(tab=False)
check("재고검토: 탭 자체가 없으면 지금처럼 (0,0) (탭이 원래 없는 업체 - 확인 중)", res == (0, 0), str(res))
rr.click_subtab = lambda app, hwnd, name: True
rr.get_onscreen_tables = lambda win: [Grid([object()])]
rr.scroll_grid_right_to_column = lambda *a: False
rr.run_hold_save = lambda app, pid, hwnd: "done"


def stock_boom(app, pid, hwnd):
    raise RuntimeError("재고검토 흉내 오류")


rr.run_stock_review_step = stock_boom
try:
    res = _real_run_hold_logistics_step(hold_app, 4242, 777)
except RuntimeError as e:
    res = ("RuntimeError", str(e))
check("물류대기: 재고검토 중 뜻밖의 오류는 삼키지 않는다 - 일반 탭 저장으로 가지 않고 그 모듈 실패 (run_module 이 UI 오류로 남긴다)",
      res[0] == "RuntimeError", str(res))
rr.run_stock_review_step = lambda app, pid, hwnd: (1, 2)
try:
    res = _real_run_hold_logistics_step(hold_app, 4242, 777)
except rr.wellife.Stop as e:
    res = (e.result, str(e))
check("물류대기: 재고검토를 다 처리하지 못했으면 경고 뒤 저장하지 않고 실패로 멈춘다", res[0] == "failed" and "2건 중 1건" in res[1], str(res))
rr.sort_grid_by_status_desc = lambda *a, **k: True
rr.get_status_column_geometry = lambda grid, col: (50, 20)
rr.get_row_height = lambda grid: 18
rr.grid_jump_to_bottom = lambda hwnd, grid, allow_keys=True: False
check("비정상 범위선택: 맨 아래로 못 가면 화면의 마지막 행으로 판정하지 않고 'error' (판별 실패 - 원래 지시대로 보류 없이 전체 저장)",
      rr.select_abnormal_range_and_check(4242, 777, Grid([object()])) == "error")
# 출력: 파일 프린터 저장 실패·엑셀 저장 뒤 팝업
pbtn = types.SimpleNamespace(window_text=lambda: "인쇄", rectangle=lambda: "자리", click_input=lambda **k: None)
rr.wait_top_hwnd = lambda pid, title, timeout: 5
rr.connect_dialog = lambda h: types.SimpleNamespace(descendants=lambda control_type=None: [pbtn])
rr.find_printer_combo = lambda dlg: "콤보"
rr.combo_value = lambda combo: "PDF"
rr.wait_save_dialog = lambda pid, timeout=0: 9
rr.save_dialog_to_jobs = lambda *a, **k: False
_ef = rr.ec.ensure_foreground
rr.ec.ensure_foreground = lambda h: True
check("출력: 파일 프린터(PDF)에 저장하지 못했으면 인쇄를 '완료' 로 보지 않는다 (예전엔 결과를 버렸다)",
      rr.run_print_dialog(4242, "PDF") is False)
rr.save_dialog_to_jobs = lambda *a, **k: r"C:\저장\WAYBILL.pdf"
check("출력: 파일 프린터에 저장했으면 완료", rr.run_print_dialog(4242, "PDF") is True)
rr.ec.ensure_foreground = _ef
POPTXT = ["무슨 안내인지 모름"]
rr.find_popup_buttons = lambda win: [types.SimpleNamespace(window_text=lambda: "확인")] if POPTXT else []
rr.collect_popup_text = lambda b: POPTXT[0]
check("엑셀 저장 뒤 모르는 팝업이 남으면 '완료' 로 넘기지 않는다 (운송장번호 전송이 그 위에서 시작되지 않게)",
      rr.check_excel_open_prompt(make_ctx().app, 777) is False)
POPTXT[:] = ["생성된 파일 경로는 다음과 같습니다"]
rr.click_popup_ok = lambda app, hwnd: False
if any(k in POPTXT[0] for k in rr.EXCEL_PATH_NOTICE_KEYWORDS):
    check("엑셀 저장 뒤 '파일 경로' 안내의 [확인] 을 못 누르면 실패", rr.check_excel_open_prompt(make_ctx().app, 777) is False)
POPTXT[:] = [rr.EXCEL_OPEN_PROMPT_KEYWORDS[0]]
check("'엑셀파일을 여시겠습니까' 는 일부러 남긴다 - 완료 (사용자 11-03)", rr.check_excel_open_prompt(make_ctx().app, 777) is True)
# 물류관리·물류대기 저장 뒤 이어 뜨는 팝업
FOLLOW = []
rr.find_popup_ok_button = lambda win: FOLLOW[0] if FOLLOW else None
rr.popup_says = lambda btn, words: "실패" if "실패" in btn.text else None
rr.press = lambda hwnd, el, what, **k: FOLLOW.pop(0) if el.sticky is False else None
FOLLOW[:] = [types.SimpleNamespace(text="배송정보 생성 실패", sticky=False, window_text=lambda: "확인")]
check("이어 뜨는 팝업 글에 실패가 있으면 닫고 멈춘다", (rr.close_follow_up_popups(make_ctx().app, 777, "개별 배송") or "").find("실패") >= 0)
FOLLOW[:] = [types.SimpleNamespace(text="안내", sticky=True, window_text=lambda: "확인")]
check("닫아도 계속 뜨면 정해진 번 넘게 이어진 것 - 멈춘다 (예전엔 3번 누르고 그냥 넘어갔다)",
      "넘게" in (rr.close_follow_up_popups(make_ctx().app, 777, "개별 배송") or ""))
FOLLOW[:] = [types.SimpleNamespace(text="안내", sticky=False, window_text=lambda: "확인")]
check("실패 글이 없는 팝업은 닫고 이어간다 (모르는 팝업은 누르고 계속 - 사용자 11-23 그대로)",
      rr.close_follow_up_popups(make_ctx().app, 777, "개별 배송") is None and not FOLLOW)
# 인쇄 뒤 미리보기 창을 못 닫으면 실패 (사용자 2026-11-23: '인쇄는 끝남' 을 남기고 멈춤 - 예전엔 무시하고 완료)
_saved_pv = (rr.run_print_dialog, rr.find_top_hwnds_by_title, rr.legacy_value, rr.ec.ensure_foreground)
pv_btn = types.SimpleNamespace(window_text=lambda: "인쇄", rectangle=lambda: "자리", click_input=lambda **k: None)
PV = {}
pv_close = types.SimpleNamespace(window_text=lambda: "인쇄 미리 보기 닫기", click_input=lambda **k: PV.update(open=PV["stay"]))
rr.wait_top_hwnd = lambda pid, title, timeout: 6
rr.connect_dialog = lambda h: types.SimpleNamespace(descendants=lambda control_type=None: (
    [] if control_type == "Text" else [pv_btn] + ([pv_close] if PV["close"] else [])))
rr.run_print_dialog = lambda pid, printer: True
rr.find_top_hwnds_by_title = lambda pid, title, exact=True: [6] if PV["open"] else []
rr.ec.ensure_foreground = lambda h: True
for close, stay, want, why in ((True, False, True, "닫혔으면 완료"), (False, False, False, "닫기 단추가 없으면 실패 (인쇄는 끝남을 남김)"),
                               (True, True, False, "눌러도 창이 남으면 실패")):
    PV.update(close=close, stay=stay, open=True)
    check(f"인쇄 뒤 미리보기 창: {why}", _real_print_preview(make_ctx().app, 4242, 777, "PDF") is want)
(rr.run_print_dialog, rr.find_top_hwnds_by_title, rr.legacy_value, rr.ec.ensure_foreground) = _saved_pv
print("=== 우클릭할 그리드 칸 - 대상이 1줄이어도 (11-23 회차8 B6: 물류관리 '전체선택' 우클릭 칸을 못 찾음) ===")
_saved_pc = (rr.element_at_point, rr.get_row_height)
PC_R = lambda l, t, r, b: types.SimpleNamespace(left=l, top=t, right=r, bottom=b, width=lambda: r - l, height=lambda: b - t)  # noqa: E731


class PcEl:
    def __init__(self, name, rect, ctype="DataItem"):
        self.name, self.rect, self.ctype = name, rect, ctype
        self.element_info = types.SimpleNamespace(control_type=ctype)

    def window_text(self):
        return self.name

    def rectangle(self):
        return self.rect


# 실측 모양: 머리글이 두 겹(737~758·758~779)으로 잡히고 데이터 첫 줄도 758~778 - 줄은 1줄
pc_cells = [PcEl("row Check Box 행 1", PC_R(-1651, 758, -1631, 778)), PcEl("매출구분 행 1", PC_R(-1631, 758, -1562, 778)),
            PcEl("매출처 행 1", PC_R(-1561, 758, -1491, 778))]
pc_heads = [PcEl("매출구분", PC_R(-1631, 737, -1561, 758), "Header"), PcEl("매출구분", PC_R(-1631, 758, -1561, 779), "Header")]
pc_grid = types.SimpleNamespace(rectangle=lambda: PC_R(-1656, 715, -14, 1018),
                                descendants=lambda control_type=None: pc_cells if control_type == "DataItem" else pc_heads)


def pc_at(x, y):        # 줄(758~778) 안이면 그 칸, 아니면 데이터 패널(빈 곳)
    hit = next((c for c in pc_cells if c.rect.left <= x < c.rect.right and c.rect.top <= y < c.rect.bottom), None)
    return hit or PcEl("데이터 패널", PC_R(-1655, 758, -15, 1000), "Custom")


rr.element_at_point, rr.get_row_height = pc_at, lambda grid: 23
got_pc = rr.pick_grid_cell(pc_grid)
check("대상이 1줄이어도 우클릭할 데이터 칸을 찾는다 - 머리글 두 겹 아래(빈 곳)를 짚지 않고 grid_rows 의 첫 줄 칸 (체크 칸 아님)",
      got_pc is not None and got_pc.name == "매출구분 행 1", str(got_pc and got_pc.name))
_pc_keep = list(pc_cells)
pc_cells[:] = [PcEl("row Check Box 행 1", PC_R(-1651, 758, -1600, 778)), PcEl("매출구분 행 1", PC_R(-1640, 758, -1610, 778)),
               PcEl("매출처 행 1", PC_R(-1561, 758, -1491, 778))]
got_pc = rr.pick_grid_cell(pc_grid)
check("가로 스크롤로 칸이 고정된 체크 칸 아래 깔려 가운데 점이 체크 칸이면 그 칸은 고르지 않는다 - 누르면 첫 줄 체크가 켜진다 (검토 11-23)",
      got_pc is not None and got_pc.name == "매출처 행 1", str(got_pc and got_pc.name))
pc_cells[:] = [_pc_keep[0]]
check("체크 칸밖에 없으면 체크 칸은 고르지 않는다 (누르면 체크가 바뀐다)", rr.pick_grid_cell(pc_grid) is None)
rr.element_at_point, rr.get_row_height = _saved_pc
print("=== 화면 이동은 웰라이프와 같은 길로 - 화면이 많이 열려 있어도 (11-23 회차5 B6·B7, 사용자: '명백한 버그') ===")
_saved_os = (rr.wellife.goto_screen, rr.wellife.numbered_tabs)
seen_os = []
rr.wellife.goto_screen = lambda rr_, ctx, name, icon, original: seen_os.append((name, icon)) or OS_R[0]
OS_R = ["ok"]
rr.wellife.numbered_tabs = lambda ctx: []
res_os = getattr(rr, "open_screen", lambda *a: "없음")(make_ctx(), "물류 관리", "lcg_Logistics", lambda: "ok")
check("open_screen 은 wellife.goto_screen 으로 간다 (이미 열린 탭·자식을 따라 아이콘·탭을 찾는다)", res_os == "ok" and seen_os == [("물류 관리", "lcg_Logistics")],
      f"{res_os} {seen_os}")
OS_R[0] = "absent"
check("아이콘이 정말 없으면 absent 그대로 (물류대기 '메뉴 없는 업체')", getattr(rr, "open_screen", lambda *a: "없음")(make_ctx(), "물류대기 관리", "x", None) == "absent")
rr.wellife.numbered_tabs = lambda ctx: ["물류대기 관리 (2)"]
res_os = getattr(rr, "open_screen", lambda *a: "없음")(make_ctx(), "물류대기 관리", "lcg_HoldLogistics", None)
check("번호 붙은 같은 화면이 있으면 absent 가 아니라 실패 사유 - '메뉴 없는 업체' 로 건너뛰지 않는다 (R7)",
      res_os not in ("absent", "ok", "없음") and "(2)" in res_os, str(res_os))
rr.wellife.goto_screen, rr.wellife.numbered_tabs = _saved_os
_src_os = open(rr.__file__, encoding="utf-8").read()
_left_os = [n for n in ("order_module", "module_hold", "module_logistics", "module_output")
            if "open_screen(" not in _src_os[_src_os.index(f"\ndef {n}("):_src_os.find("\ndef ", _src_os.index(f"\ndef {n}(") + 5)]]
check("주문매핑·물류대기·물류관리·출력 화면 이동은 모두 open_screen 으로", not _left_os, _left_os)
print("=== 체크를 확실히 - 머리글을 누른 뒤 반영될 때까지 지켜보고, 못 읽으면 누르지 않는다 (사용자 2026-11-23) ===")
_saved_hc = tuple(getattr(rr, n, None) for n in ("CHECK_READ_WAIT_SECONDS", "CHECK_SETTLE_SECONDS", "CHECK_STABLE_SECONDS", "CHECK_POLL_SECONDS"))
rr.CHECK_READ_WAIT_SECONDS, rr.CHECK_SETTLE_SECONDS, rr.CHECK_STABLE_SECONDS, rr.CHECK_POLL_SECONDS = 0.2, 0.8, 0.15, 0.01   # 안 바뀌는 것 확인은 짧게 (11-25)
rr.time = __import__("time")
HC = {"clicks": 0, "seq": []}


def hc_read():      # 누를 때마다 다음 상태 줄로 (줄의 마지막 값에 머문다)
    s = HC["seq"][min(HC["clicks"], len(HC["seq"]) - 1)]
    return s.pop(0) if len(s) > 1 else s[0]


def hc_run(*seq):
    HC.update(clicks=0, seq=[list(s) for s in seq])
    rr.press = lambda hwnd, el, what, **k: HC.__setitem__("clicks", HC["clicks"] + 1)
    try:
        return rr.header_check_all("[시험]", 777, "머리글", hc_read), HC["clicks"]
    except AttributeError as e:
        return ("없음", str(e)), 0


res, clicks = hc_run([(5, 0)])
check("이미 모두 체크면 누르지 않는다 (토글)", res == (5, 0) and clicks == 0, f"{res} {clicks}")
res, clicks = hc_run([(0, 0)])
check("체크 상태를 못 읽으면 기다렸다 다시 읽고, 끝내 못 읽으면 누르지 않는다 (모르고 누르면 풀 수 있다)", res == (0, 0) and clicks == 0, f"{res} {clicks}")
res, clicks = hc_run([(0, 0), (0, 0), (0, 5)], [(0, 5), (2, 3), (4, 1), (5, 0)])
check("처음엔 못 읽다가 읽히면 그때 누른다", res == (5, 0) and clicks == 1, f"{res} {clicks}")
res, clicks = hc_run([(0, 5)], [(0, 5), (0, 5), (2, 3), (2, 3), (4, 1), (5, 0)])
check("누른 뒤 반영이 늦어도(바뀌는 중) 다시 누르지 않고 끝까지 지켜본다 - 예전엔 1초 뒤 다시 눌러 체크를 도로 풀었다",
      res == (5, 0) and clicks == 1, f"{res} {clicks}")
res, clicks = hc_run([(0, 5)], [(0, 5)], [(5, 0)])
check("눌러도 상태가 전혀 안 바뀌고 멈춰 있으면(클릭이 안 먹음) 다시 누른다", res == (5, 0) and clicks == 2, f"{res} {clicks}")
res, clicks = hc_run([(0, 5)], [(0, 5)] * 25 + [(5, 0)])     # 25번 읽는 동안(0.25초+) 그대로 - CHECK_STABLE 보다 길고 SETTLE 보다 짧다
check("누른 뒤 한동안 그대로였다가 한꺼번에 반영되면 다시 누르지 않는다 - 첫 변화 전에는 '그대로' 로 끝내지 않는다 (Codex 검토 11-25, 실측 17줄 2.5초)",
      res == (5, 0) and clicks == 1, f"{res} {clicks}")
res, clicks = hc_run([(2, 3)], [(0, 5)], [(5, 0)])
check("일부만 체크돼 있다가 눌러 모두 풀렸으면 한 번 더 눌러 모두 체크한다", res == (5, 0) and clicks == 2, f"{res} {clicks}")
res, clicks = hc_run([(0, 5)], [(0, 5)], [(0, 5)])
check("정해진 번(2번) 눌러도 안 되면 더 누르지 않고 그 상태를 돌려준다 (부른 쪽이 실패로 멈춘다)", res == (0, 5) and clicks == 2, f"{res} {clicks}")
rr.CHECK_READ_WAIT_SECONDS, rr.CHECK_SETTLE_SECONDS, rr.CHECK_STABLE_SECONDS, rr.CHECK_POLL_SECONDS = _saved_hc
for n, f in _saved_sv.items():
    setattr(rr, n, f)

finish()
