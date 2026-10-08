"""웰라이프 실행 시험 - 설정 갈래 / 스위치 읽기 / run_main / run_modules 표 인자 / 화면 이동 모듈 / 메뉴 검색.

ERPia 없이 돈다. 설정·기록·상태는 임시 폴더로 격리한다 (RPA_PROGRAMDATA·RPA_STATUS_DIR).

    .venv\\Scripts\\python.exe tests\\test_wellife.py
"""
import os
import sys
import tempfile
import types
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="rpa_wellife_")
os.makedirs(os.path.join(_tmp, "config"))          # 새 구조로 보이게 - 설정·기록이 이 임시 폴더로 간다
os.environ["RPA_PROGRAMDATA"] = _tmp
os.environ["RPA_STATUS_DIR"] = os.path.join(_tmp, "status")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import run_routine as rr  # noqa: E402
import wellife  # noqa: E402

rr.ec.screen_locked = lambda: False   # 시험 결과가 이 PC 화면 잠김 상태에 따라 바뀌지 않게
rr.ec.erpia_pids = lambda: []          # 이 PC 에 ERPia 가 떠 있어도 결과가 같게
moves = []
wellife.mouse = types.SimpleNamespace(move=lambda coords: moves.append(coords))   # 진짜 마우스를 움직이지 않는다
TOP = [1]                                                                          # 누를 자리의 맨 위 창 (흉내)
wellife._top_window = lambda rr_, pt: TOP[0]

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


class Rec:
    """rpa_status 대신 불린 것을 적는다 (돌려주는 값은 모두 None)."""
    OFF_NOTE = "설정에서 끔"

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **k: self.calls.append((name, a))

    def of(self, name):
        return [a for n, a in self.calls if n == name]


def settings(data):
    rr.pl.load_settings = lambda: data


ALL_Y = {"Wellife": {"Login": "Y", "Sales": "Y", "Hold": "Y", "Sap": "Y"}}

# ---------------------------------------------------------------------------
print("=== 1. 갈래와 스위치 ===")
settings({"LogIn": {"AdminCode": "x"}, "Routine": {"Login": "Y", "Sales": "Y"}})
check("Wellife 섹션이 없으면 꺼짐 (지금 루틴 그대로)", wellife.enabled(rr) is False)
settings({"Wellife": {"Sales": "Y"}})
check("섹션이 있으면 켜짐", wellife.enabled(rr) is True)
settings({"LogIn": {"AdminCode": "x", "Wellife": "Y"}})
check("값으로 잘못 쓴 섹션(LogIn 에 섞임)도 웰라이프로 본다", wellife.enabled(rr) is True)


def _boom():
    raise RuntimeError("설정 파일이 없습니다")


rr.pl.load_settings = _boom
check("설정을 못 읽으면 False (오류는 기존 main 이 알린다)", wellife.enabled(rr) is False)

settings({"Wellife": {"Login": "Y", "Sales": " y ", "Hold": "N", "Extra": "Y"}})
sel, unknown = wellife.load_switches(rr)
check("적힌 Y 만 켬, 빠진 키(Sap·Wms)는 끔", sel == {"Login": True, "Sales": True, "Hold": False, "Sap": False, "Wms": False}, str(sel))
check("모르는 키는 돌려준다", unknown == ["Extra"], str(unknown))
settings({"Wellife": {}})
sel, _ = wellife.load_switches(rr)
check("빈 섹션이면 모두 끔", not any(sel.values()), str(sel))
for bad in ({"Wellife": {"Sales": "yes"}}, {"Wellife": {"Sap": None}}, {"LogIn": {"Wellife": "Y"}}):
    settings(bad)
    try:
        wellife.load_switches(rr)
        raised = False
    except RuntimeError:
        raised = True
    check(f"잘못된 설정은 RuntimeError {bad}", raised)

# ---------------------------------------------------------------------------
print("=== 2. run_main ===")
orig_run_modules = rr.run_modules
got = {}


def fake_run_modules(selected, modules=None, funcs=None, section=None):
    got.update(selected=selected, modules=modules, funcs=funcs, section=section)
    return "success", None


rec = Rec()
rr.status = rec
rr.run_modules = fake_run_modules
settings(ALL_Y)
wellife.run_main(rr)
check("기록은 program 'routine' 에 웰라이프 단계로 시작 (모드가 없으면 단계 이름 앞에 [리허설])",
      rec.of("start") and rec.of("start")[0][0] == "routine"
      and rec.of("start")[0][1] == tuple((k, "[리허설] " + v) for k, v in wellife.STEPS), str(rec.of("start")[:1]))
check("웰라이프 모듈 표를 등록", rec.of("set_modules") and [m[0] for m in rec.of("set_modules")[0][0]] == [m[0] for m in wellife.MODULES])
check("run_modules 에 웰라이프 표·섹션을 넘김", got.get("modules") is wellife.MODULES and got.get("section") == "Wellife")
check("함수 표의 키 = 모듈 키", set(got.get("funcs") or ()) == {m[0] for m in wellife.MODULES})
check("로그인은 기존 module_login 을 그대로 쓴다", (got.get("funcs") or {}).get("login") is rr.module_login)
check("끝은 finish(success)", rec.of("finish") and rec.of("finish")[-1][0] == "success")

rec = Rec()
rr.status = rec
got.clear()
settings({"Wellife": {"Sales": "yes"}})
wellife.run_main(rr)
fin = rec.of("finish")
check("설정 오류면 run_modules 를 부르지 않고 finish(stopped, 설정 파일 오류)",
      not got and fin and fin[-1][0] == "stopped" and "설정 파일 오류" in fin[-1][1], str(fin))

rec = Rec()
rr.status = rec
got.clear()
settings(ALL_Y)
rr.ec.erpia_pids = lambda: [13388, 30140]
wellife.run_main(rr)
fin = rec.of("finish")
check("ERPia 가 둘 이상이면 아무것도 누르지 않고 finish(stopped) - 다른 세션을 조작하지 않게",
      not got and fin and fin[-1][0] == "stopped" and "2개" in fin[-1][1], str(fin))
rr.ec.erpia_pids = lambda: []

# 모듈별 실행: 예약 줄이 고른 모듈(RPA_RUN_MODULES) - 섹션의 켬·끔 대신 그 모듈만 (지금 루틴과 같은 규칙)
fins = []


def picked_run(env, done=(), section=ALL_Y, trigger=None):
    global rec
    rec, got_ = Rec(), got
    got_.clear()
    fins.clear()
    rec.finish = lambda *a, **k: fins.append((a, k))
    rec.done_modules = lambda: list(done)
    rr.status = rec
    settings(section)
    os.environ["RPA_RUN_MODULES"] = env
    if trigger:
        os.environ["RPA_RUN_TRIGGER"] = trigger
    try:
        wellife.run_main(rr)
    finally:
        os.environ.pop("RPA_RUN_MODULES", None)
        os.environ.pop("RPA_RUN_TRIGGER", None)


picked_run("Wms")
check("예약 줄이 ⑤ 만 고르면 로그인 + ⑤ 만 (섹션에서 켠 ②③④ 는 안 돈다)",
      got.get("selected") == {"Login": True, "Sales": False, "Hold": False, "Sap": False, "Wms": True}, str(got.get("selected")))
picked_run("Login,Sap", section={"Wellife": {"Login": "Y"}})
check("섹션에서 끈 모듈도 예약 줄이 고르면 돈다 (④ 따로 실행)",
      got.get("selected") == {"Login": True, "Sales": False, "Hold": False, "Sap": True, "Wms": False}, str(got.get("selected")))
picked_run("Logistics,Output")
check("웰라이프에 없는 모듈만 넘어오면 run_modules 를 부르지 않고 '비었습니다' 로 멈춤",
      not got and fins and fins[-1][0][0] == "stopped" and "비었습니다" in fins[-1][0][1], str(fins))
picked_run("Wms", section={"Wellife": {"Mode": "실험"}})
check("예약 줄이 골라도 섹션 값이 틀리면 설정 파일 오류 (모드는 섹션에서 읽는다)",
      not got and fins and "설정 파일 오류" in fins[-1][0][1], str(fins))
picked_run("Wms", trigger="repeat")
check("반복 회차가 처리한 것이 없으면 이력에 남기지 않는다 (record=False)",
      fins and fins[-1][0][0] == "success" and fins[-1][1].get("record") is False, str(fins))
picked_run("Wms", done=["login", "wellife_wms"], trigger="repeat")
check("반복 회차가 실제로 넘긴 것이 있으면 이력에 남긴다",
      fins and fins[-1][0][0] == "success" and fins[-1][1].get("record", True) is True, str(fins))
picked_run("Wms", trigger="auto")
check("반복이 아닌 예약 실행은 처리한 것이 없어도 이력에 남긴다",
      fins and fins[-1][1].get("record", True) is True, str(fins))

# ---------------------------------------------------------------------------
print("=== 3. main 갈래 ===")
orig_run_main = wellife.run_main
called = []
wellife.run_main = called.append
sys.argv = [sys.argv[0]]
rec = Rec()
rr.status = rec
rec.wellife_policy = lambda: True   # 관문: 업체 정책이 열려 있어야 웰라이프로 간다
settings(ALL_Y)
rr.main()
check("섹션이 있으면 main 이 웰라이프 실행으로 간다 (이 모듈을 넘김)", called == [rr] and not rec.of("start"), str(called))

called.clear()
rec = Rec()
rr.status = rec
routine_called = []
rr.run_modules = lambda selected: routine_called.append(selected) or ("success", None)
settings({"LogIn": {"AdminCode": "x"}, "Routine": {"Login": "Y", "Sales": "N"}})
rr.main()
check("섹션이 없으면 지금 루틴 그대로 (웰라이프 실행 안 함)",
      called == [] and routine_called and rec.of("start")[0][1] is rr.ROUTINE_STEPS)
wellife.run_main = orig_run_main
rr.run_modules = orig_run_modules

# ---------------------------------------------------------------------------
print("=== 4. run_modules 표 인자 ===")
order = []


def fake(key, result="skipped"):
    def f(ctx):
        ctx.hwnd = ctx.hwnd or 1          # 로그인한 것처럼 - 진짜 ERPia 에 붙지 않게
        order.append(key)
        return result, None
    return f


def no_attach(self):
    raise AssertionError("시험에서 진짜 ERPia 에 붙으면 안 된다")


rr.RoutineContext.attach = no_attach
rec = Rec()
rr.status = rec
funcs = {m[0]: fake(m[0]) for m in wellife.MODULES}
out = rr.run_modules({"Login": True, "Sales": True, "Hold": False, "Sap": True, "Wms": False}, wellife.MODULES, funcs, "Wellife")
check("켠 모듈만 차례대로", order == ["login", "wellife_sales", "wellife_sap"] and out == ("success", None), f"{order} {out}")
check("끈 모듈은 module_off", [a[0] for a in rec.of("module_off")] == ["wellife_hold", "wellife_wms"], str(rec.of("module_off")))

order.clear()
funcs["wellife_hold"] = fake("wellife_hold", "failed")
out = rr.run_modules({m[1]: True for m in wellife.MODULES}, wellife.MODULES, funcs, "Wellife")
check("물류대기가 실패하면 SAP·WMS 를 돌리지 않는다", order == ["login", "wellife_sales", "wellife_hold"] and out[0] == "stopped", f"{order} {out}")
out = rr.run_modules({m[1]: False for m in wellife.MODULES}, wellife.MODULES, funcs, "Wellife")
check("모두 끄면 'Wellife' 섹션을 가리킨다", out[0] == "stopped" and "'Wellife'" in out[1], str(out))

orig_funcs = rr.MODULE_FUNCS
order.clear()
rr.MODULE_FUNCS = {m[0]: fake(m[0]) for m in rr.ROUTINE_MODULES}
out = rr.run_modules({m[1]: True for m in rr.ROUTINE_MODULES})
check("표 인자 없이 부르면 MODULE_FUNCS 를 부를 때 찾는다 (기존 시험의 바꿔 끼우기)",
      order == [m[0] for m in rr.ROUTINE_MODULES], str(order))
rr.MODULE_FUNCS = orig_funcs

# ---------------------------------------------------------------------------
print("=== 5. 화면 이동 모듈 ===")
fr = types.SimpleNamespace(status=Rec(), log=lambda m: None,
                           ec=types.SimpleNamespace(screen_locked=lambda: False, ensure_foreground=lambda h: True))
nctx = types.SimpleNamespace(hwnd=1)
_saved = wellife.collect_orders, wellife.hold_save
wellife.collect_orders = lambda rr_, ctx_, live: ("skipped", f"수집 live={live}")
wellife.hold_save = lambda rr_, ctx_, live: ("skipped", f"저장 live={live}")
fr.goto_order_screen = lambda ctx: (True, None)
check("② 화면 이동 성공 -> 주문 수집으로 (모드를 넘긴다)", wellife.module_sales(fr, nctx, True) == ("skipped", "수집 live=True"))
fr.goto_order_screen = lambda ctx: (False, "아이콘 없음")
check("② 이동 실패 -> failed", wellife.module_sales(fr, nctx) == ("failed", "아이콘 없음"))
for r, want in (("ok", "skipped"), ("absent", "failed"), ("failed", "failed")):
    fr.goto_hold_screen = lambda ctx, r=r: r
    check(f"③ 물류대기 '{r}' -> {want} (아이콘이 없어도 건너뛰지 않음)", wellife.module_hold(fr, nctx)[0] == want)
wellife.collect_orders, wellife.hold_save = _saved
check("모듈은 자기 단계만 찍는다", [a[0] for a in fr.status.of("step")] == ["wl_order_screen"] * 2 + ["wl_hold_screen"] * 3)

# ---------------------------------------------------------------------------
print("=== 6. 메뉴 검색으로 화면 열기 ===")
acts = []


class Rect:
    def __init__(self, left, top, right, bottom):
        self.left, self.top, self.right, self.bottom = left, top, right, bottom

    def width(self):
        return self.right - self.left

    def height(self):
        return self.bottom - self.top


class El:
    def __init__(self, name, rect=None):
        self.name, self.rect = name, rect or Rect(10, 10, 150, 30)

    def window_text(self):
        return self.name

    def rectangle(self):
        return self.rect

    def click_input(self, **kw):
        acts.append(("click", self.name))

    def is_enabled(self):
        return getattr(self, "on", True)

    def type_keys(self, keys, **_):
        acts.append(("keys", keys))


class Nav:
    def __init__(self, items):
        self.items = items

    def rectangle(self):
        return Rect(0, 0, 200, 400)

    def descendants(self, control_type=None):
        return self.items


MENU = wellife.SAP_MENU
FOCUS_IN = [("", "Edit", ""), ("sch_Menus", "Pane", "")]          # 검색 칸 안쪽 Edit 에 포커스
FOCUS_OUT = [("gridCtrl_List", "Table", "")]                       # 막 열린 화면의 그리드에 포커스
focus = [FOCUS_IN]
wellife._focus_chain = lambda rr_, depth=8: focus[0]


TAB_HIT = types.SimpleNamespace(element_info=types.SimpleNamespace(control_type="TabItem"),
                                window_text=lambda: MENU, parent=lambda: None)
HIT = [TAB_HIT]     # 탭 가운데를 히트테스트하면 맞는 요소 (흉내)


def menu_rr(nav, tab_ok=True, search=True, boom=False):
    box = El("sch")

    def find(win, aid):
        if boom:
            raise RuntimeError("COMError 흉내")
        return {"sch_Menus": box if search else None, "acd_Nav": nav}.get(aid)

    return types.SimpleNamespace(
        status=Rec(), log=lambda m: None,
        prefetch_auto_ids=lambda win, ids: 0,
        find_by_auto_id=find,
        legacy_value=lambda el: None,
        find_popup_buttons=lambda win: [], collect_popup_text=lambda b: "",
        element_at_point=lambda x, y: HIT[0],
        ec=types.SimpleNamespace(ensure_foreground=lambda h: True, literal_keys=rr.ec.literal_keys,
                                 screen_locked=lambda: False),
        wait_for_active_main_tab=lambda app, hwnd, kw, ctx=None: (tab_ok, kw if tab_ok else "메인페이지"))


ctx = types.SimpleNamespace(window=lambda: Nav([]), hwnd=1, app=None)
wellife.MENU_WAIT_SECONDS, wellife.MENU_POLL_SECONDS = 0.3, 0.01
TYPE = [("click", "sch"), ("keys", "^a{BACKSPACE}"), ("keys", MENU)]
CLEAR = [("click", "sch"), ("keys", "^a{BACKSPACE}")]

hidden, outside = El(MENU, Rect(0, 0, 0, 0)), El(MENU, Rect(300, 10, 450, 30))   # 크기 0 / 트리 밖
ok, reason = wellife.goto_screen_by_menu(menu_rr(Nav([El("다른 메뉴"), hidden, outside, El(MENU)])), ctx, MENU)
check("열림", ok and reason is None, str(reason))
check("검색 칸 클릭 -> 지우기 -> 메뉴명 -> 트리 안에 보이는 항목 클릭 -> 검색 칸 비우기",
      acts == TYPE + [("click", MENU)] + CLEAR, str(acts))

acts.clear()
ok, reason = wellife.goto_screen_by_menu(menu_rr(Nav([El("다른 메뉴"), outside])), ctx, MENU)
check("검색 결과에 (트리 안에 보이는) 항목이 없으면 실패하고 검색 칸만 비운다",
      not ok and "없습니다" in reason and acts == TYPE + CLEAR, str(acts))

acts.clear()
ok, reason = wellife.goto_screen_by_menu(menu_rr(Nav([El(MENU)]), tab_ok=False), ctx, MENU)
check("눌렀는데 탭이 안 열리면 실패", not ok and "열리지 않았습니다" in reason, str(reason))

acts.clear()
ok, reason = wellife.goto_screen_by_menu(menu_rr(Nav([El(MENU)]), search=False), ctx, MENU)
check("검색 칸이 없으면 아무것도 누르지 않고 실패", not ok and acts == [], str(acts))

acts.clear()
focus[0] = FOCUS_OUT
ok, reason = wellife.goto_screen_by_menu(menu_rr(Nav([El(MENU)])), ctx, MENU)
check("클릭 뒤 포커스가 검색 칸 밖이면 키를 하나도 보내지 않고 실패",
      not ok and "포커스" in reason and all(a[0] == "click" for a in acts), str(acts))
focus[0] = FOCUS_IN

acts.clear()
ok, reason = wellife.goto_screen_by_menu(menu_rr(Nav([El(MENU)]), boom=True), ctx, MENU)
check("UI 오류는 실행을 죽이지 않고 이 화면 이동의 실패로 돌려준다", not ok and "UI 오류" in reason and acts == [], str(reason))

# 이미 열린 화면: 메뉴를 눌러도 그 탭으로 가지 않는다 (10-07 실측) - 탭을 눌러 앞으로 가져온다
tab_ctx = types.SimpleNamespace(window=lambda: Nav([El("웰라이프 WMS 이관관리"), El(MENU)]), hwnd=1, app=None)
acts.clear()
ok, reason = wellife.goto_screen_by_menu(menu_rr(Nav([El(MENU)])), tab_ctx, MENU)
check("이미 열린 화면은 그 탭만 누르고 메뉴 검색은 하지 않는다", ok and acts == [("click", MENU)], f"{reason} {acts}")
acts.clear()
ok, reason = wellife.goto_screen_by_menu(menu_rr(Nav([El(MENU)]), tab_ok=False), tab_ctx, MENU)
check("탭을 눌렀는데 그 화면으로 안 바뀌면 실패", not ok and "탭을 눌렀으나" in reason and acts == [("click", MENU)],
      f"{reason} {acts}")
hidden_tab_ctx = types.SimpleNamespace(window=lambda: Nav([El(MENU, Rect(150, 10, 260, 30))]), hwnd=1, app=None)
acts.clear()
ok, reason = wellife.goto_screen_by_menu(menu_rr(Nav([El(MENU)])), hidden_tab_ctx, MENU)
check("이미 열린 화면인데 탭이 잘려 있으면(넘친 탭바) 누르지 않고 멈춘다 - 메뉴로는 못 간다",
      not ok and "다 보이지 않아" in reason and acts == [], f"{reason} {acts}")
HIT[0] = types.SimpleNamespace(element_info=types.SimpleNamespace(control_type="Button"),
                               window_text=lambda: "닫기", parent=lambda: None)
acts.clear()
ok, reason = wellife.goto_screen_by_menu(menu_rr(Nav([El(MENU)])), tab_ctx, MENU)
check("탭 가운데를 누르면 다른 것(탭바의 × 등)이 맞으면 누르지 않고 멈춘다", not ok and acts == [], f"{reason} {acts}")
HIT[0] = TAB_HIT
acts.clear()
ok, reason = wellife.goto_screen_by_menu(
    types.SimpleNamespace(**{**vars(menu_rr(Nav([El(MENU)]))), "find_popup_buttons": lambda win: [El("예")]}), ctx, MENU)
check("앞 화면의 팝업이 남아 있으면 화면 이동을 시작하지 않는다", not ok and "팝업" in reason and acts == [], f"{reason} {acts}")

# ---------------------------------------------------------------------------
print("=== 7. 글자 그대로 입력 (로그인·메뉴 검색 공용) ===")
from pywinauto.keyboard import parse_keys  # noqa: E402


def typed(s):
    return "".join(chr(a.key) if isinstance(a.key, int) else str(a.key) for a in parse_keys(s, with_spaces=True))


for raw in ("a(b)c", "a+b^c%d~e{f}", "user01", MENU):
    check(f"literal_keys 로 감싸면 '{raw}' 가 그대로 들어간다", typed(rr.ec.literal_keys(raw)) == raw,
          repr(typed(rr.ec.literal_keys(raw))))
check("특수문자가 없으면 값이 바뀌지 않는다", rr.ec.literal_keys("company01") == "company01")
check("(감싸지 않으면 괄호가 빠진다 - 고친 버그)", typed("a(b)c") == "abc")

print("=== 9. 단계 건수·매출전표 대상 고르기 ===")
check("단추 이름에서 건수", wellife.stage_count("매출전표\r\n(199)") == 199 and wellife.stage_count("S/O매출\r\n(0)") == 0)
check("건수가 없으면 None", wellife.stage_count("") is None and wellife.stage_count("매출전표") is None)
check("콤보의 줄인 단계 이름도 같은 단계 (10-07 실측: 단추 '선분할 배송정보' -> 콤보 '선분할')",
      wellife.same_stage(wellife.stage_name("단계 : 선분할"), "선분할 배송정보")
      and wellife.same_stage(wellife.stage_name("단계 : 매출전표"), "매출전표")
      and wellife.same_stage(wellife.stage_name("단계 : S/O매출"), "S/O매출")
      and wellife.same_stage("SO생성", "S/O 생성"))
check("다른 단계·빈 값은 같은 단계가 아니다",
      not wellife.same_stage(wellife.stage_name("단계 : 전체(매출전표제외)"), "매출전표")
      and not wellife.same_stage(wellife.stage_name("단계 : 매출전표"), "선분할 배송정보")
      and not wellife.same_stage("", "매출전표") and not wellife.same_stage(wellife.stage_name(None), "x"))
check("검토 칸 나누기", wellife.review_tokens("예정일X/택배X") == ["예정일X", "택배X"] and wellife.review_tokens(" ") == [])
t42 = [v for v in ("예정일X/택배X", "/택배X", "예정일X", "", " ", None, "거래처X") if wellife.slip_target(v)]
check("4-2 넘길 줄 = 검토 칸이 빈 줄만 (사용자 10-08)", t42 == ["", " "], str(t42))
check("검토 값을 못 읽은 줄(None)은 넘기지 않는다", not wellife.slip_target(None))


class Split(El):
    def __init__(self, kids, rect=None):
        super().__init__("지정", rect or Rect(0, 0, 100, 30))
        self.kids = kids

    def children(self):
        return self.kids


arrow = El("오픈", Rect(80, 0, 100, 30))
check("[지정▼] 는 '오픈' 내림 단추를 고른다", wellife.split_open_button(Split([El("지정"), arrow])) is arrow)
check("10-07 실측 사각형(창이 왼쪽 모니터 - 음수 좌표)도 고른다", wellife.split_open_button(
    Split([El("오픈", Rect(-1196, 213, -1178, 236))], Rect(-1251, 213, -1178, 236))) is not None)
check("'오픈' 이 없거나·본체만큼 넓거나·왼쪽에 있거나·크기 0 이면 None - 본체(지정 실행)를 누르지 않게",
      all(wellife.split_open_button(x) is None for x in (
          Split([El("지정")]), Split([El("오픈", Rect(0, 0, 100, 30))]), Split([El("오픈", Rect(0, 0, 20, 30))]),
          Split([El("오픈", Rect(0, 0, 0, 0))]), None)))

# 내림 메뉴: ▼ 클릭 -> 항목에 마우스만 -> ESC -> 메뉴 창이 사라졌는지 확인. 항목은 누르지 않는다
wellife.HOVER_SECONDS, wellife.DROPDOWN_WAIT_SECONDS = 0, 0.5
WIN = {"open": set()}                                   # 보이는 ERPia 최상위 창 (메인 창 빼고)
wellife._menu_windows = lambda rr_, ctx_: set(WIN["open"])
wellife._shown = lambda rr_, h: h in WIN["open"]
wellife._window_texts = lambda rr_, hs: [[("Button", "미이관 전체")] for _ in hs]


class Arrow(El):
    def __init__(self, opens=True, on=True):
        super().__init__("오픈", Rect(80, 0, 100, 30))
        self.opens, self.on = opens, on

    def click_input(self, **kw):
        acts.append(("click", self.name))
        if self.opens:
            WIN["open"].add(7)


class Click(El):
    """누르면 on_click 도 부르는 요소."""
    def __init__(self, name, rect=None, on_click=lambda: None):
        super().__init__(name, rect)
        self.on_click = on_click

    def click_input(self, **kw):
        acts.append(("click", self.name))
        self.on_click()


def drop_rr(found=True, closes=True, popup=None, fg_pid=1):
    item = Click(wellife.SELECTED_ONLY, Rect(80, 30, 180, 50), lambda: WIN["open"].clear())   # 누르면 메뉴가 닫힌다

    def esc(k):
        acts.append(("keys", k))
        if closes:
            WIN["open"].clear()

    def popups(win):
        return [El("예")] if popup == "before" or (popup == "after" and WIN["open"]) else []

    return types.SimpleNamespace(
        log=lambda m: None, send_keys=esc, find_popup_buttons=popups, collect_popup_text=lambda b: "질문",
        _find_menu_item=lambda pid, hwnd, text: (item, 7) if found and 7 in WIN["open"] and text == item.name
        else (None, None),
        find_popup_windows=lambda pid, hwnd: [], grid_overlay_count=lambda h, g: 0,
        win32gui=types.SimpleNamespace(GetForegroundWindow=lambda: 5),
        win32process=types.SimpleNamespace(GetWindowThreadProcessId=lambda h: (0, fg_pid)),
        ec=types.SimpleNamespace(screen_locked=lambda: False, ensure_foreground=lambda h: True))


actx = types.SimpleNamespace(pid=1, hwnd=2, window=lambda: Nav([]))
wellife._has_buttons = lambda rr_, h: True


def run_drop(arrow_el, **kw):
    acts.clear(); moves.clear(); WIN["open"].clear()
    try:
        return wellife.hover_menu_item(drop_rr(**kw), actx, Split([El("지정"), arrow_el]),
                                       wellife.SELECTED_ONLY, "4-1 [지정▼]", True), None
    except wellife.Stop as e:
        return None, e


TOP[0] = actx.hwnd
note, err = run_drop(Arrow())
check("▼ 만 누르고 '선택 항목만' 에는 마우스만 -> ESC 로 닫힌 것까지 확인",
      err is None and note == "" and acts == [("click", "오픈"), ("keys", "{ESC}")] and moves[-1] == (130, 40),
      f"{note} {err} {acts} {moves}")
note, err = run_drop(Arrow(), found=False)
check("항목이 없으면 실측 로그를 남기고 메뉴를 닫은 뒤 '확인할 것' 으로 다음 단계로 간다",
      err is None and "확인할 것" in note and acts[-1] == ("keys", "{ESC}") and not WIN["open"], f"{note} {err} {acts}")
note, err = run_drop(Arrow(opens=False), found=False)
check("▼ 를 눌러도 메뉴가 안 뜨면 ESC 를 보내지 않는다", err is None and "뜨지 않음" in note
      and ("keys", "{ESC}") not in acts, f"{note} {err} {acts}")
note, err = run_drop(Arrow(), closes=False)
check("ESC 로 메뉴 창이 안 사라지면 멈춘다 (다음 클릭이 메뉴에 떨어지지 않게)",
      err is not None and err.result == "failed" and "닫히지 않" in str(err), f"{note} {err}")
note, err = run_drop(Arrow(), found=False, popup="after")
check("▼ 뒤 팝업이 떠 있으면 ESC 도 보내지 않고 멈춘다 (ESC 는 팝업을 닫는다)",
      err is not None and err.result == "stopped" and ("keys", "{ESC}") not in acts, f"{err} {acts}")
note, err = run_drop(Arrow(), popup="before")
check("팝업이 떠 있으면 ▼ 도 누르지 않는다", err is not None and acts == [], f"{err} {acts}")
note, err = run_drop(Arrow(), fg_pid=99)
check("맨 앞 창이 ERPia 가 아니면 ESC 를 보내지 않고 멈춘다",
      err is not None and "ESC 를 보내지 않고" in str(err) and ("keys", "{ESC}") not in acts, f"{err} {acts}")
note, err = run_drop(Arrow(on=False))
check("▼ 가 꺼져 있으면 누르지 않고 ▼ 위에 마우스만", err is None and acts == [] and moves == [(90, 15)], f"{acts} {moves}")
acts.clear(); moves.clear()
note = wellife.hover_menu_item(drop_rr(), actx, Split([El("지정")]), wellife.SELECTED_ONLY, "4-1 [지정▼]", True)
check("▼ 자리를 못 고르면 누르지 않고 본체 위에 마우스만 ('확인할 것')", acts == [] and "확인할 것" in note, f"{note} {acts}")
TOP[0] = 99
note, err = run_drop(Arrow())
check("누를 자리를 다른 창(열린 메뉴·다른 프로그램)이 덮고 있으면 누르지 않고 멈춘다",
      err is not None and err.result == "failed" and acts == [], f"{err} {acts}")
TOP[0] = 1
acts.clear()
for name, el in (("빈 사각형", El("빈", Rect(0, 0, 0, 0))), ("창 밖", El("밖", Rect(300, 500, 340, 520)))):
    try:
        wellife.click(drop_rr(), actx, el, name)
        check(f"누를 자리가 {name}이면 누르지 않고 멈춘다", False, "멈추지 않음")
    except wellife.Stop as e:
        check(f"누를 자리가 {name}이면 누르지 않고 멈춘다 ((0,0)·다른 곳을 누르지 않게)", acts == [], f"{e} {acts}")

# Stop 이 아닌 UI 오류는 실행 전체를 죽이지 않고 그 화면의 실패로
_saved = wellife.goto_screen_by_menu, wellife.sales_slip_stage
wellife.goto_screen_by_menu = lambda rr_, ctx_, menu: (True, None)


def _ui_boom(*_):
    raise RuntimeError("COMError 흉내")


wellife.sales_slip_stage = _ui_boom
res = wellife.module_sap(types.SimpleNamespace(status=Rec(), log=lambda m: None), actx)
check("SAP 화면의 UIA 오류는 ('failed', 'UI 오류: …')", res == ("failed", "UI 오류: RuntimeError"), str(res))
wellife.goto_screen_by_menu, wellife.sales_slip_stage = _saved


# 그리드 넘기기: 페이지를 넘긴 직후에는 앞 페이지가 그대로 읽힌다 (10-07 실측: 201건 중 140~161·끝 3줄을 못 읽음)
class Cell:
    def __init__(self, v, top=0):
        self.v, self.rect = v, Rect(0, top, 10, top + 10)

    def rectangle(self):
        return self.rect


class FakeGrid:
    """review(n) = 검토 값, stuck = 눌러도 체크가 안 바뀌는 줄. 체크 칸은 전체 체크된 채로 시작한다."""
    def __init__(self, ranges, stale=2, review=lambda n: "택배X", stuck=()):
        self.cells = {}
        for r in ranges:
            for n in r:
                self.cells[n] = {"검토": Cell(review(n)), wellife.CHECK_COL: Cell("선택")}
        self.pages = [{n: self.cells[n] for n in r} for r in ranges]
        self.page, self.stale, self.stale_left, self.tops, self.stuck = 0, stale, 0, 0, set(stuck)
        self.header = El(wellife.CHECK_COL)
        self.header.rect = Rect(0, -10, 10, -1)

    def descendants(self, control_type=None):
        return [self.header]

    def toggle(self, el):
        checks = [c[wellife.CHECK_COL] for c in self.cells.values()]
        if el is self.header:
            v = "선택안됨" if all(c.v == "선택" for c in checks) else "선택"
            for c in checks:
                c.v = v
            return
        n = next(n for n, c in self.cells.items() if c[wellife.CHECK_COL] is el)
        if n not in self.stuck:
            el.v = "선택안됨" if el.v == "선택" else "선택"

    def rows(self):
        if self.stale_left:
            self.stale_left -= 1
            return self.pages[self.page - 1]
        return self.pages[self.page]

    def down(self):
        if self.page + 1 >= len(self.pages):
            return False
        self.page += 1
        self.stale_left = self.stale
        return True

    def top(self):
        self.page, self.stale_left = 0, 0
        self.tops += 1


def grid_rr(g):
    return types.SimpleNamespace(
        grid_rows=lambda grid: g.rows(), grid_page_down=lambda h, grid: g.down(),
        grid_scroll_to_top=lambda h, grid: g.top(), legacy_value=lambda el: el.v, log=lambda m: None,
        grid_click_bottom=lambda grid: 100,
        ec=types.SimpleNamespace(screen_locked=lambda: False, ensure_foreground=lambda h: True))


def run_marks(g, expected):
    _saved = wellife.click, wellife.no_popup
    wellife.click = lambda rr_, ctx, el, what: (g.clicks.append(el), g.toggle(el))
    wellife.no_popup = lambda *a: None
    g.clicks = []
    try:
        return wellife.mark_rows(grid_rr(g), actx, g, expected, wellife.slip_target)
    finally:
        wellife.click, wellife.no_popup = _saved


wellife.PAGE_WAIT_SECONDS = 1
wellife.CHECK_WAIT_SECONDS = 0.3
g = FakeGrid((range(1, 25), range(24, 48), range(47, 60)), review=lambda n: "" if n % 5 == 0 else "택배X")
out, bad = run_marks(g, 59)
check("넘긴 직후 앞 페이지가 읽혀도 페이지를 건너뛰지 않고 끝 줄까지 맞춘다", sorted(out) == list(range(1, 60)) and not bad,
      f"{len(out)}줄 bad={bad}")
check("검토 빈 줄만 체크, 나머지는 풀림",
      all(v == ("선택" if n % 5 == 0 else "선택안됨") for n, v in out.items())
      and all(c[wellife.CHECK_COL].v == out[n] for n, c in g.cells.items()))
check("한 번만 내려간다 - 맨 위로 올리기는 처음 한 번 (아래로 → 위로 → 아래로 하지 않음)", g.tops == 1 and g.page == 2,
      f"맨 위로 {g.tops}번")
check("전체 체크된 채면 머리글 한 번으로 풀고, 넘길 줄만 하나씩 누른다",
      g.clicks[0] is g.header and len(g.clicks) == 1 + 11, f"{len(g.clicks)}번 누름")
out, _ = run_marks(FakeGrid((range(1, 25), range(1, 25)), stale=0), 24)
check("내렸는데 첫 행이 그대로면 끝으로 본다 (같은 페이지를 끝없이 돌지 않음)", sorted(out) == list(range(1, 25)), f"{len(out)}줄")
g = FakeGrid((range(1, 25),), stale=0, review=lambda n: None if n == 5 else "", stuck=(7,))
out, bad = run_marks(g, 24)
check("검토를 못 읽은 줄(None)은 체크하지 않는다", out.get(5) == "선택안됨", str(out.get(5)))
check("눌러도 안 바뀐 줄은 '못 맞춘 줄' 로 남는다 (4-2 를 누르지 않는 근거)", bad == [7], str(bad))
g = FakeGrid((range(1, 25),), stale=0)
g.cells[24][wellife.CHECK_COL].rect = Rect(0, 95, 10, 105)     # 마지막 줄 체크 칸이 아래로 잘림
out, bad = run_marks(g, 24)
check("끝 줄이 잘려 못 눌렀으면 '못 맞춘 줄' (전체 체크된 채 넘어가지 않게)", bad == [24], str(bad))
g = FakeGrid((range(1, 25), range(1, 25)), stale=0)
_grr = grid_rr
grid_rr = lambda g_: types.SimpleNamespace(**vars(_grr(g_)), grid_vertical_scrollbar=lambda grid: Nav([El("페이지 아래로")]))
try:
    run_marks(g, 24)
    res = None
except wellife.Stop as e:
    res = e.result
grid_rr = _grr
check("페이지를 내렸는데 그리드가 그대로인데 '페이지 아래로' 가 있으면 멈춘다 (뒤 줄을 모름)", res == "failed", str(res))
check("SAP전송전체 이후·송장X·API실패 등 사람이 보는 단추는 단계 표에 없다",
      not {s[1] for s in wellife.SAP_SIMPLE_STAGES + wellife.WMS_STAGES}
      & {"dashBtn_SendSAP_All", "dashBtn_SendSAP_Success", "dashBtn_SendSAP_Fail", "dashBtn_SAP_Complate",
         "dashBtn_SAP_Error", "dashBtn_Invocie_Fail", "dashBtn_API_Fail", "dashBtn_WMS_Working",
         "dashBtn_Send_Allot", "dashBtn_WMS_Export", "dashBtn_Missing"})

print("=== 10. 잠긴 화면·앞으로 못 가져옴 ===")
locked = types.SimpleNamespace(log=lambda m: None, status=Rec(),
                               ec=types.SimpleNamespace(screen_locked=lambda: True, ensure_foreground=lambda h: True))
try:
    wellife.front(locked, nctx, "시험 단추")
    res = None
except wellife.Stop as e:
    res = (e.result, str(e))
check("잠긴 화면이면 누르지 않고 stopped", res and res[0] == "stopped" and "잠겨" in res[1], str(res))
behind = types.SimpleNamespace(log=lambda m: None, status=Rec(),
                               ec=types.SimpleNamespace(screen_locked=lambda: False, ensure_foreground=lambda h: False))
try:
    wellife.front(behind, nctx, "시험 단추")
    res = None
except wellife.Stop as e:
    res = (e.result, str(e))
check("ERPia 를 앞으로 못 가져오면 누르지 않고 failed", res and res[0] == "failed", str(res))
locked.goto_order_screen = lambda ctx: (_ for _ in ()).throw(AssertionError("눌렀다"))
check("② 도 잠긴 화면이면 화면 이동을 시작하지 않는다", wellife.module_sales(locked, nctx)[0] == "stopped")

rec = Rec()
rr.status = rec
got.clear()
rr.run_modules = fake_run_modules
rr.ec.screen_locked = lambda: True
settings(ALL_Y)
wellife.run_main(rr)
fin = rec.of("finish")
check("실행 첫머리에 화면이 잠겨 있으면 모듈을 돌리지 않고 stopped",
      not got and fin and fin[-1][0] == "stopped" and "잠겨" in fin[-1][1], str(fin))
rr.ec.screen_locked = lambda: False
rr.run_modules = orig_run_modules

print("=== 8. 로그인 뒤 메인 창을 팝업으로 오판하지 않기 ===")
main_texts = "company01 - user01 | pnlMain | Accordion Menu | 업체전용 | 물류대기 | lcg_HoldLogistics".split(" | ")
popup_texts = "로그인     v852 | 로그인 실패 | 잘못된 아이디 혹은 비밀번호입니다. | 확인(O) | 닫기".split(" | ")
check("좌측 메뉴가 있는 창은 메인 화면", rr.pl.is_main_screen_texts(main_texts))
check("로그인 실패 팝업은 메인 화면이 아니다", not rr.pl.is_main_screen_texts(popup_texts))

# 이미 로그인된 ERPia: 숨은 로그인 잔재 창을 로그인 창으로 보면 그 창 Edit 좌표(= 메인 화면 위)를 누른다
_saved = rr.pl.find_login_window, rr.ec.find_main_hwnd, rr.is_main_app_window, rr.win32gui
rr.pl.find_login_window = lambda: types.SimpleNamespace(handle=77)
rr.ec.find_main_hwnd = lambda pid: 55
rr.is_main_app_window = lambda h: True
rr.win32gui = types.SimpleNamespace(IsWindowVisible=lambda h: False)
check("숨은 로그인 잔재 창은 로그인 창으로 보지 않는다 (이미 로그인된 ERPia)",
      rr.wait_login_or_main(1) == ("already_logged_in", 55))
rr.win32gui = types.SimpleNamespace(IsWindowVisible=lambda h: True)
check("보이는 로그인 창이면 로그인 창", rr.wait_login_or_main(1)[0] == "login_window")
rr.pl.find_login_window, rr.ec.find_main_hwnd, rr.is_main_app_window, rr.win32gui = _saved

print("=== 11. 모드 (리허설 / 실행) 와 실제로 누르기 ===")
settings({"Wellife": {"Login": "Y", "Mode": "실행"}})
_, unknown = wellife.load_switches(rr)
check("Mode 는 모르는 키가 아니다", unknown == [], str(unknown))
check("Mode '실행' -> 실제로 누름", wellife.load_mode(rr) is True)
settings({"Wellife": {"Login": "Y"}})
check("Mode 가 없으면 리허설 (누르지 않는 쪽)", wellife.load_mode(rr) is False)
settings({"Wellife": {"Login": "Y", "Mode": "run"}})
try:
    wellife.load_mode(rr)
    raised = False
except RuntimeError:
    raised = True
check("Mode 가 '리허설'/'실행' 이 아니면 설정 오류", raised)
settings({"Wellife": {"Login": "Y", "Mode": "실행", "SalesMode": "리허설"}})
check("SalesMode 는 Mode 와 따로 읽는다",
      wellife.load_mode(rr) is True and wellife.load_mode(rr, wellife.SALES_MODE_KEY) is False
      and wellife.load_switches(rr)[1] == [])
settings({"Wellife": {"Login": "Y", "Mode": "실행"}})
check("SalesMode 가 없으면 Mode 를 따르지 않고 리허설", wellife.load_mode(rr, wellife.SALES_MODE_KEY) is False)

rec = Rec()
rr.status = rec
got.clear()
rr.run_modules = fake_run_modules
settings({"Wellife": {"Login": "Y", "Mode": "실행"}})
wellife.run_main(rr)
start = rec.of("start")[0]
sales_keys = {"wl_order_screen", "wl_order_collect"}
check("단계 이름 앞에 모드 - ② 는 SalesMode(빠져서 [리허설]), 나머지는 Mode([실행])",
      all(label.startswith("[리허설] " if k in sales_keys else "[실행] ") for k, label in start[1]), str(start[1][:4]))
settings({"Wellife": {"Login": "Y", "Mode": "run"}})
rec = Rec()
rr.status = rec
got.clear()
wellife.run_main(rr)
fin = rec.of("finish")
check("Mode 가 잘못되면 아무것도 돌리지 않고 설정 파일 오류", not got and fin and "설정 파일 오류" in fin[-1][1], str(fin))
rr.run_modules = orig_run_modules

# 팝업 넘기기: [아니오] 가 함께 있어도 [예]
wellife.QUIET_SECONDS = 0.05
POP = []


def pop_rr(**kw):
    base = dict(log=lambda m: None, find_popup_buttons=lambda win: list(POP), collect_popup_text=lambda b: "저장하시겠습니까?",
                find_popup_windows=lambda pid, hwnd: [], grid_overlay_count=lambda h, g: 0,
                ec=types.SimpleNamespace(screen_locked=lambda: False, ensure_foreground=lambda h: True))
    base.update(kw)
    return types.SimpleNamespace(**base)


TOP[0] = actx.hwnd               # 팝업 단추 자리의 맨 위 창 = ERPia 메인 창
acts.clear()
POP[:] = [El("아니오"), Click("예", on_click=POP.clear)]
texts = wellife.confirm_popups(pop_rr(), actx, "시험")
check("팝업은 [아니오] 가 함께 있어도 [예] 를 누르고 문구를 남긴다",
      acts == [("click", "예")] and texts == ["저장하시겠습니까?"], f"{acts} {texts}")
acts.clear()
POP[:] = [Click("확인", on_click=POP.clear)]
check("[예] 가 없으면 [확인]", wellife.confirm_popups(pop_rr(), actx, "시험") and acts == [("click", "확인")], str(acts))
acts.clear()
POP[:] = [El("아니오")]
try:
    wellife.confirm_popups(pop_rr(), actx, "시험")
    res = None
except wellife.Stop as e:
    res = e.result
check("[예]/[확인] 이 없는 팝업은 누르지 않고 멈춘다", res == "stopped" and acts == [], f"{res} {acts}")
POP[:] = [El("예")]            # 눌러도 안 닫히는 팝업
_sleep = wellife.time.sleep
wellife.time.sleep = lambda s: None
try:
    wellife.confirm_popups(pop_rr(), actx, "시험")
    res = None
except wellife.Stop as e:
    res = str(e)
check(f"팝업이 {wellife.MAX_POPUPS}개를 넘으면 멈춘다 (끝없이 누르지 않게)", res and "넘어" in res, str(res))
wellife.time.sleep = _sleep
acts.clear()
POP[:] = [Click("확인", on_click=POP.clear)]
try:
    wellife.confirm_popups(pop_rr(collect_popup_text=lambda b: "지정 실패: 납품예정일"), actx, "시험")
    res = None
except wellife.Stop as e:
    res = e.result
check("실패/오류 문구 팝업은 넘긴 뒤 멈춘다 (지정 실패 뒤 4-2 를 누르지 않게)", res == "stopped" and acts == [("click", "확인")],
      f"{res} {acts}")
acts.clear()
POP[:] = [Click("예", on_click=POP.clear)]
TOP[0] = 99                      # 다른 프로그램 창이 덮고 있다
try:
    wellife.confirm_popups(pop_rr(), actx, "시험")
    res = None
except wellife.Stop as e:
    res = e.result
check("팝업 단추 자리를 다른 창이 덮고 있으면 누르지 않고 멈춘다", res == "failed" and acts == [], f"{res} {acts}")
TOP[0] = 1
POP.clear()

# 화살표 단계: 실행이면 누르고, 리허설이면 마우스만
_saved_open = wellife.open_stage
arrow_btn = Click("btn_ThirdSend", on_click=lambda: POP.extend([Click("예", on_click=POP.clear)]))


def stage_with(count, enabled=True):
    arrow_btn.on = enabled
    wellife.open_stage = lambda rr_, ctx_, form, dash: (count, {"btn_ThirdSend": arrow_btn})


TOP[0] = actx.hwnd
stage = ("wl_sap_so", "dashBtn_Create_SO", "btn_ThirdSend", False, "4-4 SO생성 → SAP 전송")
srr = pop_rr(status=Rec())
for live, count, enabled, want_click in ((False, 3, True, False), (True, 3, True, True),
                                         (True, 0, True, False), (True, 3, False, False)):
    acts.clear(); moves.clear(); POP.clear()
    stage_with(count, enabled)
    note, pressed = wellife.simple_stage(srr, actx, wellife.SAP_FORM, *stage, live=live)
    clicked = ("click", "btn_ThirdSend") in acts
    check(f"화살표 live={live} {count}건 단추{'켜짐' if enabled else '꺼짐'} -> {'누름 + 팝업 [예]' if want_click else '안 누름'}",
          clicked == want_click and pressed == want_click and (not want_click or ("click", "예") in acts),
          f"{note} {acts}")
wellife.open_stage = _saved_open
r = wellife.stage_result(True, [("a", False), ("b", True)])
check("실제로 누른 단계가 있으면 모듈 결과 done, 사유 앞에 [실행]", r[0] == "done" and r[1].startswith("[실행] "), str(r))
r = wellife.stage_result(False, [("a", False)])
check("리허설은 skipped, 사유 앞에 [리허설]", r[0] == "skipped" and r[1].startswith("[리허설] "), str(r))

# [지정▼] 실행: ▼ 로 열고 '선택 항목만' 을 누른다 (그 자리의 맨 위 창이 메뉴일 때만)
_saved_top = wellife._top_window
wellife._top_window = lambda rr_, pt: 7 if pt == (130, 40) else actx.hwnd
acts.clear(); moves.clear(); WIN["open"].clear()
note, pressed = wellife.press_menu_item(drop_rr(), actx, Split([El("지정"), Arrow()]), wellife.SELECTED_ONLY, "4-1 [지정▼]")
check("실행: ▼ 를 누르고 '선택 항목만' 을 누른다 (ESC 는 보내지 않는다)",
      pressed and acts == [("click", "오픈"), ("click", wellife.SELECTED_ONLY)], f"{note} {acts}")
wellife._top_window = lambda rr_, pt: 99 if pt == (130, 40) else actx.hwnd
acts.clear(); WIN["open"].clear()
try:
    wellife.press_menu_item(drop_rr(), actx, Split([El("지정"), Arrow()]), wellife.SELECTED_ONLY, "4-1 [지정▼]")
    res = None
except wellife.Stop as e:
    res = e.result
check("항목 자리를 다른 창이 덮고 있으면 누르지 않고 메뉴를 닫은 뒤 멈춘다",
      res == "failed" and ("click", wellife.SELECTED_ONLY) not in acts and ("keys", "{ESC}") in acts, f"{res} {acts}")
wellife._top_window = _saved_top


# 물류대기: 조회 -> 전체선택 -> 저장
def hold_rr(rows=1):
    grid = types.SimpleNamespace(rectangle=lambda: Rect(0, 50, 200, 300),
                                 descendants=lambda control_type=None: [1] * rows)
    return pop_rr(status=Rec(), click_subtab=lambda app, hwnd, name: acts.append(("tab", name)),
                  STOCK_GENERAL_TAB_NAME="일반", get_onscreen_tables=lambda win: [grid],
                  wait_grid_spinner_gone=lambda *a, **k: True,
                  select_all_by_header_checkbox=lambda hwnd, g: acts.append(("select_all",)) or True)


save_btn = Click("저장(S)", on_click=lambda: POP.extend([El("아니오"), Click("예(Y)", on_click=POP.clear)]))
hctx = types.SimpleNamespace(pid=1, hwnd=2, app=None, window=lambda: Nav([El("조회(F)"), save_btn]))
TOP[0] = hctx.hwnd
_sleep = wellife.time.sleep
wellife.time.sleep = lambda s: _sleep(min(s, 0.01))
for live in (False, True):
    acts.clear(); POP.clear()
    res = wellife.hold_save(hold_rr(), hctx, live)
    want = [("tab", "일반"), ("click", "조회(F)"), ("select_all",)] + (
        [("click", "저장(S)"), ("click", "예(Y)")] if live else [])
    check(f"물류대기 live={live}: 일반 탭 조회 -> 전체선택 -> {'저장 + 팝업 [예]' if live else '저장은 마우스만'}",
          acts == want and res[0] == ("done" if live else "skipped") and res[1].startswith(f"[{wellife.mode_tag(live)}]"),
          f"{res} {acts}")
acts.clear()
res = wellife.hold_save(hold_rr(rows=0), hctx, True)
check("물류대기 0건이면 저장하지 않는다", res[0] == "no_target" and ("click", "저장(S)") not in acts, f"{res} {acts}")

# 주문 수집: 엑셀이 있을 때만 올리고, 자동 수집 [가져오기] 는 누르지 않는다
xdir = tempfile.mkdtemp(prefix="rpa_wl_xl_")
uploads = []


def order_rr(files):
    return pop_rr(status=Rec(), excel_upload_dir=lambda: xdir,
                  collect_upload_files=lambda folder: (files, [], []),
                  get_onscreen_tables=lambda win: [El("사이트", Rect(0, 50, 200, 100))],
                  run_excel_upload_step=lambda app, pid, hwnd, grid: uploads.append(grid.name) or (len(files), 0),
                  find_site_upload_cell=lambda hwnd, grid, code: (El(f"업로드 {code}"), "1"),
                  IMPORT_BUTTON_NAME="가져오기")


octx = types.SimpleNamespace(pid=1, hwnd=2, app=None, window=lambda: Nav([El("가져오기")]))
for live, files, want_res, want_up in ((True, {}, "skipped", []), (False, {"101": "x"}, "skipped", []),
                                       (True, {"101": "x"}, "done", ["사이트"])):
    acts.clear(); uploads.clear()
    res = wellife.collect_orders(order_rr(files), octx, live)
    check(f"주문 수집 live={live} 엑셀 {len(files)}건 -> {want_res}, 업로드 {len(want_up)}번, [가져오기] 는 안 누름",
          res[0] == want_res and uploads == want_up and ("click", "가져오기") not in acts, f"{res} {uploads} {acts}")
wellife.time.sleep = _sleep
TOP[0] = 1


# 4-1 → 4-2 순서 (사용자 10-08): 전체 체크 → [지정▼] 선택 항목만 → 검토 빈 줄만 체크 → 화살표
def run_slip(live, checked=True, pressed=True, marks=None, bad=()):
    names = ("open_stage", "check_all_rows", "hover_menu_item", "press_menu_item", "controls", "mark_rows", "press_arrow")
    saved = {n: getattr(wellife, n) for n in names}
    seq = []
    wellife.open_stage = lambda *a: (seq.append("조회"), (3, {"gridCtrl_List": "g"}))[1]
    wellife.check_all_rows = lambda *a: (seq.append("전체 체크"), checked)[1]
    wellife.hover_menu_item = lambda *a: (seq.append("지정 마우스만"), "")[1]
    wellife.press_menu_item = lambda *a: (seq.append("지정 누름"), ("", pressed))[1]
    wellife.controls = lambda *a: (seq.append("다시 잡기"), {"gridCtrl_List": "g2"})[1]
    wellife.mark_rows = lambda rr_, ctx, grid, n, want: (seq.append(f"줄 맞추기 {grid}"),
                                                         (marks if marks is not None else {1: "선택", 2: "선택안됨"}, list(bad)))[1]
    wellife.press_arrow = lambda rr_, ctx, ctl, aid, what, want, n, lv: (seq.append(f"화살표 {aid} want={want} live={lv}"),
                                                                        ("", lv and want))[1]
    try:
        return wellife.sales_slip_stage(types.SimpleNamespace(log=lambda m: None, status=Rec()), actx, live), seq
    finally:
        for n, f in saved.items():
            setattr(wellife, n, f)


res, seq = run_slip(True)
check("실행: 조회 → 전체 체크 → 지정 누름 → 다시 잡고 줄 맞추기 → 화살표(btn_FirstSend)",
      seq == ["조회", "전체 체크", "지정 누름", "다시 잡기", "줄 맞추기 g2", "화살표 btn_FirstSend want=True live=True"]
      and res[1] is True, f"{seq} {res}")
res, seq = run_slip(False)
check("리허설: 지정·화살표는 마우스만", seq == ["조회", "전체 체크", "지정 마우스만", "줄 맞추기 g",
                                     "화살표 btn_FirstSend want=True live=False"] and res[1] is False, f"{seq}")
res, seq = run_slip(True, bad=(2,))
check("실행: 못 맞춘 줄이 있으면 화살표를 누르지 않는다", seq[-1].endswith("want=False live=True") and "넘기지 않음" in res[0],
      f"{seq} {res}")
res, seq = run_slip(True, marks={1: "선택안됨"})
check("실행: 넘길 줄(검토 빈 칸)이 없으면 화살표를 누르지 않는다", seq[-1].endswith("want=False live=True"), f"{seq}")
res, seq = run_slip(True, checked=False)
check("실행: 전체 체크가 안 되면 지정도 화살표도 누르지 않는다", seq == ["조회", "전체 체크"] and res[1] is False, f"{seq}")
res, seq = run_slip(True, pressed=False)
check("실행: 지정을 못 눌렀으면 줄 맞추기·화살표로 가지 않는다", seq == ["조회", "전체 체크", "지정 누름"] and res[1] is False,
      f"{seq}")

finish()
