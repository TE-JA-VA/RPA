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
for mode, want in ((None, False), ("리허설", False), ("실행", True), ("1건", _rr.wellife.ONE)):
    called.clear()
    with_settings({"Routine": {"InvoiceSend": "Y", **({"InvoiceMode": mode} if mode else {})}})
    _rr.MODULE_FUNCS["invoicesend"](object())
    check(f"보통 PROCESS 의 운송장번호 전송 모드: Routine.InvoiceMode {mode or '없음'} -> {want} (빠지면 리허설, 사용자 10-13)",
          called == [want], f"{called}")
called.clear()
with_settings({"Routine": {"InvoiceSend": "Y", "InvoiceMode": "yes"}})
got = _rr.MODULE_FUNCS["invoicesend"](object())
check("모드 값이 틀리면 화면을 열지 않고 설정 오류", called == [] and got[0] == "failed" and "InvoiceMode" in got[1], f"{got}")
for mode, trigger, runs in (("1건", "repeat", False), ("1건", "auto", True), ("실행", "repeat", True)):
    called.clear()
    with_settings({"Routine": {"InvoiceSend": "Y", "InvoiceMode": mode}})
    os.environ["RPA_RUN_TRIGGER"] = trigger
    try:
        got = _rr.MODULE_FUNCS["invoicesend"](object())
    finally:
        os.environ.pop("RPA_RUN_TRIGGER", None)
    check(f"InvoiceMode {mode} / {trigger}: " + ("돈다" if runs else "반복 회차의 '1건' 은 화면을 열지 않고 '설정 확인' 으로 멈춘다 (회차마다 1건씩 나가지 않게)"),
          bool(called) == runs and (runs or (got[0] == "stopped" and "설정 확인" in got[1])), f"{called} {got}")
_rr.wellife.module_invoice_send = orig_inv
check("Routine 의 InvoiceMode 는 모르는 키 경고에서 빠진다", "InvoiceMode" in _rr.ROUTINE_MODE_KEYS)
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
_real_handle_print_popups = rr.handle_print_popups   # 9절에서 진짜를 쓴다
_real_run_print_step = rr.run_print_step             # 6절이 가짜로 바꾸므로 9절에서 되살린다
_real_run_logistics_step = rr.run_logistics_step     # 7절이 가짜로 바꾸므로 8절에서 되살린다

print()
print("=== 3. 모듈 표 / 컨텍스트 / 화면 진입 ===")
rr.time = types.SimpleNamespace(sleep=lambda *_: None, time=_time.time, strftime=_time.strftime)
rr.ec = types.SimpleNamespace(ensure_foreground=lambda *a, **k: True, find_erpia_pid=lambda: 4242,
                              process_elevated=lambda pid: False, pid_alive=lambda pid: True, erpia_pids=lambda: [])
rr.log = lambda msg="": None
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


check("ROUTINE_MODULES 는 6개 (운송장번호 전송은 2026-10-13 모든 업체로)", [m[0] for m in rr.ROUTINE_MODULES] == ["login", "sales", "hold", "logistics", "output", "invoicesend"])
check("비트는 1/2/4/8/16 고정 + 운송장번호 전송 512 (웰라이프와 같은 비트)", [m[4] for m in rr.ROUTINE_MODULES] == [1, 2, 4, 8, 16, 512], str([m[4] for m in rr.ROUTINE_MODULES]))
steps_keys = [k for k, _ in rr.ROUTINE_STEPS]
check("logistics_screen 단계가 logistics 앞에", steps_keys.index("logistics_screen") + 1 == steps_keys.index("logistics"))
check("모듈 단계 키를 모두 합치면 ROUTINE_STEPS 와 같다", sorted(k for m in rr.ROUTINE_MODULES for k in m[3]) == sorted(steps_keys))

rr.find_by_text = lambda win, key, control_types=(): None
check("아이콘 없음 -> absent", rr.goto_screen_by_icon(make_ctx(), "lcg_X", "엑스", "엑스", wait_seconds=2) == "absent")

el = FakeEl()
rr.find_by_text = lambda win, key, control_types=(): el
rr.wait_for_active_main_tab = lambda app, hwnd, kw, timeout=20, interval=1.0, ctx=None: (True, "엑스 관리")
check("아이콘 클릭 + 탭 확인 -> ok", rr.goto_screen_by_icon(make_ctx(), "lcg_X", "엑스", "엑스") == "ok" and el.clicked == 1)

rr.wait_for_active_main_tab = lambda app, hwnd, kw, timeout=20, interval=1.0, ctx=None: (False, "다른탭")
check("클릭했지만 진입 확인 실패 -> failed", rr.goto_screen_by_icon(make_ctx(), "lcg_X", "엑스", "엑스") == "failed")


def raising(win, key, control_types=()):
    raise RuntimeError("COMError 흉내")


rr.find_by_text = raising
rr.acquire_main_window = lambda pid, tries=12: (778, types.SimpleNamespace(window=lambda handle: FakeWin()), FakeWin())
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
rr.acquire_main_window = lambda pid, tries=12: (778, types.SimpleNamespace(window=lambda handle: LiveWin(el)), LiveWin(el))
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

rr.pl = types.SimpleNamespace(find_login_window=lambda: None, load_logistic_options=lambda: {},
                              load_credentials=pl.load_credentials, ROUTINE_SECTION="Routine")
ctx = make_ctx()
rr.acquire_main_window = lambda pid, tries=12: (None, None, None)
ok, reason = ctx.attach()
check("attach: 메인 창 못 잡으면 (False, 사유)", ok is False and "메인 화면" in reason, str(reason))
rr.acquire_main_window = lambda pid, tries=12: (999, "app", "win")
ok, reason = ctx.attach()
check("attach: 성공하면 hwnd 갱신", ok is True and ctx.hwnd == 999 and ctx.pid == 4242)
rr.pl.find_login_window = lambda: types.SimpleNamespace(handle=1)     # 로그인 뒤 숨은 채 남는 잔재 창
rr.win32gui.IsWindowVisible = lambda h: False
ok, reason = ctx.attach()
check("attach: 숨은 로그인 잔재 창은 무시하고 붙는다", ok is True, str(reason))
rr.win32gui.IsWindowVisible = lambda h: True
ok, reason = ctx.attach()
check("attach: 보이는 로그인 창이면 즉시 안내", ok is False and "로그인 창" in reason, str(reason))
rr.pl.find_login_window = lambda: None
rr.ec.find_erpia_pid = lambda: (_ for _ in ()).throw(RuntimeError("없음"))
ok, reason = ctx.attach()
check("attach: ERPia 미실행이면 로그인 모듈 안내", ok is False and "로그인 모듈" in reason, str(reason))
rr.ec.find_erpia_pid = lambda: 4242

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


def run(selected, results, attach=(True, None)):
    """모듈 함수를 가짜로 바꿔 디스패처만 돌린다. results: {모듈키: (result, reason)}"""
    rec = StatusRec()
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

    rr.MODULE_FUNCS = {k: fake(k) for k in ("login", "sales", "hold", "logistics", "output")}
    rr.RoutineContext.attach = fake_attach
    out = rr.run_modules(selected)
    return out, called, rec, attach_calls


ALL_ON = {"Login": True, "Sales": True, "Hold": True, "Logistics": True, "Output": True}
out, called, rec, ac = run(ALL_ON, {})
check("전부 켜면 5개 순서대로", called == ["login", "sales", "hold", "logistics", "output"], str(called))
check("전부 done 이면 success", out == ("success", None), str(out))
check("module_done 5번 전부 done", [r[1] for r in rec.of("module_done")] == ["done"] * 5)
check("로그인이 켜져 있으면 attach 안 부름", ac == [])

out, called, rec, ac = run({**ALL_ON, "Sales": False, "Hold": False}, {})
check("끈 모듈은 부르지 않는다", called == ["login", "logistics", "output"], str(called))
check("끈 모듈은 module_off (칸이 없는 운송장번호 전송도 끔)", [r[0] for r in rec.of("module_off")] == ["sales", "hold", "invoicesend"])
skipped = rec.of("skip")
check("끈 모듈의 단계는 '설정에서 끔' 으로 skip", len(skipped) == 11 and all(s[1] == "설정에서 끔" for s in skipped), str(skipped))
logged = []
rr.log = lambda msg="": logged.append(msg)
os.environ["RPA_RUN_MODULES"] = "Logistics,Output"
try:
    out, called, rec, ac = run({**ALL_ON, "Sales": False, "Hold": False}, {})
finally:
    os.environ.pop("RPA_RUN_MODULES", None)
    rr.log = lambda msg="": None
skipped = rec.of("skip")
check("예약이 고른 실행이면 안 고른 모듈은 '이번 실행에서 안 고름' (설정과 상관없다)",
      len(skipped) == 11 and all(s[1] == "이번 실행에서 안 고름" for s in skipped)
      and [r[1] for r in rec.of("module_off")] == ["이번 실행에서 안 고름"] * 3, str(skipped))
check("로그도 '이번 실행에서 고르지 않아 건너뜁니다'",
      any("[주문매핑 매출처리] 이번 실행에서 고르지 않아 건너뜁니다" in m for m in logged) and not any("설정에서 꺼져" in m for m in logged), str(logged[:3]))

out, called, rec, ac = run({**ALL_ON, "Login": False}, {})
check("로그인을 끄면 ERPia 에 붙어서 계속", called == ["sales", "hold", "logistics", "output"] and out[0] == "success", str(called))
check("attach 는 한 번만", ac == [1], str(ac))
out, called, rec, ac = run({**ALL_ON, "Login": False}, {}, attach=(False, "ERPia 가 실행되어 있지 않습니다."))
check("붙기 실패면 아무 모듈도 안 돌고 stopped", called == [] and out[0] == "stopped" and "ERPia" in out[1], str(out))
check("붙기 실패는 그 모듈의 첫 단계에 실패로 보인다", rec.of("step") == [("order_screen",)] and rec.of("module_done")[-1][:2] == ("sales", "failed"), str(rec.of("step")))
check("rpa_status.OFF_NOTE 가 있고 run_routine 에 리터럴이 없다",
      st.OFF_NOTE == "설정에서 끔" and '"설정에서 끔"' not in Path(rr.__file__).read_text(encoding="utf-8"))
check("rpa_status.PICK_NOTE 도 같은 자리에", st.PICK_NOTE == "이번 실행에서 안 고름" and set(st.OFF_NOTES) == {st.OFF_NOTE, st.PICK_NOTE})

out, called, rec, ac = run(ALL_ON, {"hold": ("failed", "그리드 없음")})
check("failed 면 뒤 모듈 안 돌고 stopped", called == ["login", "sales", "hold"] and out == ("stopped", "그리드 없음"), str((called, out)))
out, called, rec, ac = run(ALL_ON, {"sales": ("stopped", "매출처리 실패: x")})
check("stopped 도 멈춘다", called == ["login", "sales"] and out[0] == "stopped")
out, called, rec, ac = run(ALL_ON, {"hold": ("no_target", "행 없음")})
check("no_target 은 계속 간다", called == ["login", "sales", "hold", "logistics", "output"] and out[0] == "success")
out, called, rec, ac = run(ALL_ON, {"hold": ("skipped", "메뉴 없음")})
check("skipped 도 계속 간다", len(called) == 5 and out[0] == "success")

out, called, rec, ac = run({k: False for k in ALL_ON}, {})
check("전부 끄면 아무것도 안 돌고 stopped", called == [] and out[0] == "stopped" and "켜진 모듈" in out[1], str(out))
check("전부 끄면 여섯 모듈이 off 로 표시된다", len(rec.of("module_off")) == 6 and len(rec.of("skip")) == 17, str(len(rec.of("skip"))))

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

rr.run_print_step = lambda app, pid, hwnd, options=None, already_printed="continue": "already_printed"
ctx.results = {}
seen.clear()
check("이미 출력이면 no_target", rr.module_output(ctx)[0] == "no_target")

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
rr.wait_grid_spinner_gone = lambda *a, **k: None
check("run_logistics_step: 하단 0건이면 no_target", rr.run_logistics_step(make_ctx().app, 4242, 777, options={}) == "no_target")

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
rr.click_toolbar_button = lambda win, hwnd, text: True
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
check("정상이면 set_modules 에 (키, 이름, 단계, 비트) 6개", bool(sm) and [m[3] for m in sm[0][0]] == [1, 2, 4, 8, 16, 512], str(sm))
check("정상이면 run_modules 로 간다 + finish(success)", ran and rec.of("finish")[-1] == ("success", None), str(rec.of("finish")))

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
check("main 이 넘긴 모듈로 돈다", ran and ran[-1] == {"Login": True, "Sales": False, "Hold": True, "Logistics": False, "Output": False,
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
SALES_ON = {"Login": True, "Sales": True, "Hold": False, "Logistics": False, "Output": False}
seen = []


def crash_once(ctx):
    seen.append((ctx.resume, ctx.collected))
    if len(seen) == 1:
        ctx.collected = True         # 수집은 끝냈고 매출처리 중에 꺼졌다
        ALIVE[0] = False
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
check("다시 돌 때 ctx.resume='sales', 수집 끝남(collected) 이 남아 매출처리부터", seen == [(None, False), ("sales", True)], str(seen))
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
check("꺼진 뒤 다른 ERPia 가 떠 있으면 다시 띄우지 않고 멈춘다 (사람이 띄운 것일 수 있다, 리뷰 10-14)",
      out[0] == "stopped" and "9999" in out[1] and called == ["login", "sales"], f"{out} {called}")
OTHERS[0] = []


def one_crash(ctx):
    ctx.no_rerun.add("sales")      # '1건' 모드 모듈 (wellife.run_main 의 once, module_invoice_send)
    seen.append(ctx.resume)
    ALIVE[0] = False
    return "done", None


out, called, rec = run_crash(one_crash)
check("'1건' 모드 모듈은 ERPia 가 꺼져도 다시 돌지 않고 멈춘다 (1건이 2건이 되지 않게, 리뷰 10-14)",
      out[0] == "stopped" and "1건" in out[1] and called == ["login", "sales"], f"{out} {called}")

out, called, rec = run_crash(raise_dead)
check("꺼지면서 난 UI 예외도 다시 띄워 잇는다", out == ("success", None) and seen == [None, "sales"], f"{out} {seen}")


def raise_alive(ctx):
    raise ValueError("진짜 버그")


try:
    run_crash(raise_alive)
    res = None
except ValueError as e:
    res = str(e)
check("ERPia 가 떠 있는데 난 예외는 예전처럼 그대로 올린다", res == "진짜 버그", str(res))


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

# 주문매핑 module_sales: 수집이 끝났으면 상단 전체선택·가져오기·엑셀을 건너뛴다
_saved_s = {n: getattr(rr, n) for n in ("goto_order_screen", "get_onscreen_tables", "select_all_and_verify",
                                         "run_import_step", "run_excel_upload_step", "find_by_text")}
sales_acts = []


class Tbl:
    def __init__(self, top):
        self.top = top

    def rectangle(self):
        return types.SimpleNamespace(top=self.top, left=0)


rr.status = StatusRec()
rr.goto_order_screen = lambda ctx: (True, None)
rr.get_onscreen_tables = lambda win: [Tbl(10), Tbl(300)]
rr.select_all_and_verify = lambda name, *a: sales_acts.append(("select", name)) or 3
rr.run_import_step = lambda *a: sales_acts.append(("import",)) or True
rr.run_excel_upload_step = lambda *a: sales_acts.append(("excel",))
rr.find_by_text = lambda *a, **k: None          # 매출처리 단추 없음 -> 여기서 멈춘다 (시험은 그 앞까지만 본다)
for collected, want in ((False, [("select", "좌측상단"), ("import",), ("excel",), ("select", "하단")]),
                        (True, [("select", "하단")])):
    sales_acts.clear()
    ctx = make_ctx()
    ctx.collected = collected
    res = rr.module_sales(ctx)
    check(f"module_sales collected={collected}: " + ("상단 전체선택 -> 가져오기 -> 엑셀 -> 하단" if not collected
                                                     else "수집을 건너뛰고 하단 전체선택(매출처리)부터"),
          sales_acts == want and res[0] == "failed", f"{sales_acts} {res}")
ctx = make_ctx()
ALIVE[0] = False
rr.module_sales(ctx)
check("수집 도중 ERPia 가 꺼졌으면 collected 를 세우지 않는다 (다시 돌 때 수집부터)", ctx.collected is False)
ALIVE[0] = True

# 함께 실행 (모든 업체, 사용자 2026-10-20): 엑셀은 받는 대로 - 'excel' 은 상단 전체선택 앞, 'excel_import' 는 가져오기를 끝까지 본 뒤
_saved_t = {n: getattr(rr, n) for n in ("excel_upload_together", "sales_flow", "find_popup_windows", "upload_popups",
                                         "excel_upload_dir", "time")}
_saved_w = rr.wellife.on_top, rr.wellife.wait_prepare
rr.excel_upload_together = lambda ctx, grid: sales_acts.append(("together",))
for mode, want in (("excel", [("together",), ("select", "좌측상단"), ("import",), ("select", "하단")]),
                   ("excel_import", [("select", "좌측상단"), ("import",), ("together",), ("select", "하단")])):
    sales_acts.clear()
    rr.TOGETHER_MODE = mode
    rr.sales_flow(make_ctx())
    check(f"함께 실행 '{mode}': " + ("받는 엑셀을 먼저 (수집이 끝날 때까지) -> 상단 전체선택 -> 가져오기 -> 하단" if mode == "excel"
                                   else "상단 전체선택 -> 가져오기(끝까지) -> 받는 엑셀 -> 하단 (예전 엑셀업로드 자리, '+' 화면 없이)"),
          sales_acts == want, str(sales_acts))
tops, prep = [], [["prepare"], ["prepare"], []]
rr.wellife.on_top = lambda rr_, hwnd, on: tops.append(on)
rr.status = StatusRec()
rr.status.running_programs = lambda: prep.pop(0) if prep else []
rr.time = types.SimpleNamespace(sleep=lambda s: None, time=_time.time)
rr.TOGETHER_MODE = "excel"
rr.sales_flow = lambda ctx: ("done", None)
res = rr.module_sales(make_ctx())
check("함께 실행이면 주문매핑 동안 ERPia 를 맨 위로 두고 끝나면 풀며, 사이트 수집이 끝나기를 기다린 뒤 다음 모듈로 (키를 치는 뒤 모듈이 Edge 와 겹치지 않게)",
      tops == [True, False] and not prep and res == ("done", None), f"{tops} {prep} {res}")
rr.TOGETHER_MODE = None
tops.clear()
rr.module_sales(make_ctx())
check("함께 실행이 아니면 맨 위만 푼다 (앞 함께 실행이 [중지] 로 남긴 맨 위 - 맨 위가 아니면 아무 일 없음)", tops == [False], str(tops))
rr.sales_flow = _saved_t["sales_flow"]
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
    rr.together_setup(rr, {"Sales": sales})
    check(f"함께 띄운 루틴: 방식 '{mode}', 주문매핑 {'켬' if sales else '끔'} -> "
          + (f"받는 대로 올림 ('{want}'), 로그인 키 입력 동안 키보드 차례" if want else "사이트 수집이 끝나기를 기다린 뒤 예전처럼"),
          rr.TOGETHER_MODE == want and len(waits) == (0 if want else 1) and (rr.pl.KEYS_GUARD is not contextlib.nullcontext) == bool(want),
          f"{rr.TOGETHER_MODE} {waits}")
del os.environ[rr.TOGETHER_ENV]
rr.TOGETHER_MODE, rr.pl.KEYS_GUARD = None, contextlib.nullcontext
rr.together_setup(rr, {"Sales": True})
check("함께 띄운 루틴이 아니면 아무것도 바꾸지 않는다", rr.TOGETHER_MODE is None and rr.pl.KEYS_GUARD is contextlib.nullcontext)
rr.pl.KEYS_GUARD = _saved_guard
rr.wellife.on_top, rr.wellife.wait_prepare = _saved_w
for n, f in _saved_t.items():
    setattr(rr, n, f)
for n, f in _saved_s.items():
    setattr(rr, n, f)

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
PIDS = [4242]
rr.ec.find_erpia_pid = lambda: PIDS[0] if PIDS else (_ for _ in ()).throw(RuntimeError("없음"))
rr.ec.terminate_pid = lambda pid: (PIDS.clear(), ALIVE.__setitem__(0, False))[0]


def fake_popen(args, cwd=None):
    POPEN.append(args)
    PIDS.append(5555)


rr.subprocess = types.SimpleNamespace(Popen=fake_popen)
pid = rr.ensure_erpia_running()
check("ensure_erpia_running: 이미 로그인된 관리자 ERPia 는 끄고 새로 띄운 ERPia 의 PID", pid == 5555 and len(POPEN) == 1, f"{pid} {POPEN}")
ELEV[0] = False
POPEN.clear()
check("같은 권한이면 떠 있는 ERPia 를 그대로", rr.ensure_erpia_running() == 5555 and POPEN == [])
ELEV[0] = True
PIDS[:] = [4242]
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
OTHERS[0] = [4242, 4343]
KILLED = []
rr.ec.terminate_pid = lambda pid: KILLED.append(pid)
try:
    rr.ensure_erpia_running()
    res = None
except RuntimeError as e:
    res = str(e)
check("ERPia 가 여러 개면 로그인된 관리자 ERPia 라도 끄지 않는다 (리뷰 10-14)",
      res is not None and "여러 개" in res and KILLED == [] and POPEN == [], str(res))
OTHERS[0] = []
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
rr.pl.load_credentials = _saved_cred
LOGGED[0] = True
for n, f in _saved_e.items():
    setattr(rr, n, f)

LOGINS = []
_saved_ml = rr.module_login
rr.module_login = lambda ctx: LOGINS.append(1) or ("done", None)
rr.RoutineContext.attach = _real_attach
ctx = rr.RoutineContext()
rr.ec.find_erpia_pid = lambda: 4242
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

finish()
