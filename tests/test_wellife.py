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
check("적힌 Y 만 켬, 빠진 키(Sap·Wms·InvoiceSend)는 끔, 빠진 엑셀·자동 수집은 주문매핑(Sales)을 따른다 (10-15 나누기 전 PC)",
      sel == {"Login": True, "Excel": True, "Import": True, "Sales": True, "Hold": False, "Sap": False, "Wms": False,
              "InvoiceSend": False}, str(sel))
settings({"Wellife": {"Login": "Y", "Excel": "N", "Sales": "Y"}})
sel, _ = wellife.load_switches(rr)
check("엑셀 수집을 적어 두면 그 값 (끔), 빠진 자동 수집만 주문매핑을 따른다", sel["Excel"] is False and sel["Import"] is True, str(sel))
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
_saved_mods = {n: getattr(wellife, n) for n in ("module_sales", "module_sap")}
wellife.module_sales = lambda rr_, ctx_, sell: ("done", None)
wellife.module_sap = lambda rr_, ctx_, live: ("done", None)
for extra, want in (({}, set()), ({"NormalSalesMode": "1건"}, {"wellife_sales"})):
    got.clear()
    settings({"Wellife": {**ALL_Y["Wellife"], **extra}})
    wellife.run_main(rr)
    nctx = types.SimpleNamespace(no_rerun=set())
    for k in ("wellife_sales", "wellife_sap"):
        got["funcs"][k](nctx)
    check(f"'1건' 모드가 걸린 모듈만 ERPia 가 꺼져도 다시 돌지 않게 표시 {extra or '(모두 리허설)'} -> {want or '없음'}",
          nctx.no_rerun == want, str(nctx.no_rerun))
for n, f in _saved_mods.items():
    setattr(wellife, n, f)
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
      got.get("selected") == {"Login": True, "Excel": False, "Import": False, "Sales": False, "Hold": False, "Sap": False,
                              "Wms": True, "InvoiceSend": False},
      str(got.get("selected")))
picked_run("Login,Sap", section={"Wellife": {"Login": "Y"}})
check("섹션에서 끈 모듈도 예약 줄이 고르면 돈다 (④ 따로 실행)",
      got.get("selected") == {"Login": True, "Excel": False, "Import": False, "Sales": False, "Hold": False, "Sap": True,
                              "Wms": False, "InvoiceSend": False},
      str(got.get("selected")))
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
rr.ec.screen_locked = lambda: True
picked_run("Wms", trigger="repeat")
check("반복 회차가 잠긴 화면에서 시작도 못 했으면 이력에 남기지 않는다 (PC 가 그 회차만 건너뛴다 - 사용자 10-08)",
      fins and fins[-1][0][0] == "stopped" and "화면이 잠겨" in fins[-1][0][1] and fins[-1][1].get("record") is False, str(fins))
picked_run("Wms", trigger="auto")
check("반복이 아닌 실행은 잠겨 못 돈 것도 이력에 남긴다", fins and fins[-1][0][0] == "stopped" and fins[-1][1].get("record", True) is True, str(fins))
rr.ec.screen_locked = lambda: False
picked_run("Wms", trigger="auto")
check("반복이 아닌 예약 실행은 처리한 것이 없어도 이력에 남긴다",
      fins and fins[-1][1].get("record", True) is True, str(fins))
# '1건' 은 한 번 실행에 1건 - 반복 회차면 회차마다 1건씩 계속 넘어가므로 돌지 않는다 (PR #6 검토)
ONE_WMS = {"Wellife": {**ALL_Y["Wellife"], "WmsMode": "1건", "NormalSalesMode": "1건"}}
picked_run("Wms", section=ONE_WMS, trigger="repeat")
check("반복 회차에서 도는 모듈(⑤)이 '1건' 이면 run_modules 를 부르지 않고 '설정 확인' 으로 멈춘다 (이력에 남긴다)",
      not got and fins and fins[-1][0][0] == "stopped" and "설정 확인" in fins[-1][0][1] and "WmsMode" in fins[-1][0][1]
      and fins[-1][1].get("record", True) is True, str(fins))
picked_run("Sales", section=ONE_WMS, trigger="repeat")
check("② 를 반복하면 정상매출 '1건' 도 멈춘다", not got and fins and "NormalSalesMode" in fins[-1][0][1], str(fins))
picked_run("Hold", section=ONE_WMS, trigger="repeat")
check("이번 회차에 안 도는 모듈의 '1건' 은 보지 않는다 (③ 만 반복)", got.get("selected", {}).get("Hold") is True, str(fins))
picked_run("Wms", section=ONE_WMS, trigger="auto")
check("반복이 아닌 실행은 '1건' 이어도 돈다", got.get("selected", {}).get("Wms") is True, str(fins))

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
out = rr.run_modules({"Login": True, "Excel": True, "Import": False, "Sales": True, "Hold": False, "Sap": True, "Wms": False,
                      "InvoiceSend": False},
                     wellife.MODULES, funcs, "Wellife")
check("켠 모듈만 차례대로 (② 는 엑셀 수집 -> 자동 수집 -> 매출처리 순)", order == ["login", "wellife_excel", "wellife_sales", "wellife_sap"]
      and out == ("success", None), f"{order} {out}")
check("끈 모듈은 module_off", [a[0] for a in rec.of("module_off")] == ["wellife_import", "wellife_hold", "wellife_wms", "invoicesend"],
      str(rec.of("module_off")))

order.clear()
funcs["wellife_hold"] = fake("wellife_hold", "failed")
out = rr.run_modules({m[1]: True for m in wellife.MODULES}, wellife.MODULES, funcs, "Wellife")
check("물류대기가 실패하면 SAP·WMS 를 돌리지 않는다",
      order == ["login", "wellife_excel", "wellife_import", "wellife_sales", "wellife_hold"] and out[0] == "stopped", f"{order} {out}")
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
_saved = wellife.excel_collect, wellife.import_collect, wellife.normal_sales, wellife.hold_save
wellife.excel_collect = lambda rr_, ctx_, live: ("skipped", f"엑셀 live={live}")
wellife.import_collect = lambda rr_, ctx_, live: ("skipped", f"자동 live={live}")
wellife.normal_sales = lambda rr_, ctx_, sell: (f"sell={sell}", False)
wellife.hold_save = lambda rr_, ctx_, live: ("skipped", f"저장 live={live}")
fr.goto_order_screen = lambda ctx: (True, None)
check("② 엑셀 수집·자동 수집·매출처리는 각자 화면으로 가서 자기 모드로 (사용자 10-15 셋으로 나눔)",
      wellife.module_excel(fr, nctx, True) == ("skipped", "엑셀 live=True")
      and wellife.module_import(fr, nctx, False) == ("skipped", "자동 live=False")
      and wellife.module_sales(fr, nctx, wellife.ONE) == ("skipped", "[1건] 정상매출 sell=1건"))
check("② 화면을 떠나면 팝업 강제 넘기기를 끈다", nctx.pass_popups is False and fr.POPUP_PREFER_YES is False)
fr.goto_order_screen = lambda ctx: (False, "아이콘 없음")
check("② 이동 실패 -> failed", wellife.module_sales(fr, nctx) == ("failed", "아이콘 없음"))
for r, want in (("ok", "skipped"), ("absent", "failed"), ("failed", "failed")):
    fr.goto_hold_screen = lambda ctx, r=r: r
    check(f"③ 물류대기 '{r}' -> {want} (아이콘이 없어도 건너뛰지 않음)", wellife.module_hold(fr, nctx)[0] == want)
wellife.excel_collect, wellife.import_collect, wellife.normal_sales, wellife.hold_save = _saved
check("모듈은 자기 단계만 찍는다", [a[0] for a in fr.status.of("step")] ==
      ["wl_excel_screen", "wl_import_screen", "wl_order_screen", "wl_order_screen"] + ["wl_hold_screen"] * 3, str(fr.status.of("step")))

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


# 메인 탭바 읽기는 자식 따라가기(main_tab_bar)·떠 있는 탭(wait_tab) - 이 절과 운송장 절은 창 흉내(Nav)의 목록과
# rr.wait_for_active_main_tab 흉내로 대신한다. 진짜 함수는 '같은 화면 여러 개' 절에서 따로 본다
_real_tabs = wellife.main_tab_bar, wellife.wait_tab
wellife.main_tab_bar = lambda ctx_: (None, ctx_.window().descendants(control_type="TabItem"))
wellife.wait_tab = lambda rr_, ctx_, name, timeout=0: rr_.wait_for_active_main_tab(None, None, name)

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
check("SAP 화면의 UIA 오류는 ('failed', 'UI 오류: … - 문구')", res == ("failed", "UI 오류: RuntimeError - COMError 흉내"), str(res))
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
    vsb = types.SimpleNamespace(descendants=lambda: [El("페이지 위로")] + ([El("페이지 아래로")] if g.page + 1 < len(g.pages) else []))
    return types.SimpleNamespace(
        grid_rows=lambda grid: g.rows(), grid_page_down=lambda h, grid: g.down(),
        grid_vertical_scrollbar=lambda grid: getattr(g, "vsb", vsb),     # 끝 페이지면 '페이지 아래로' 가 없다
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
for why, vsb in (("None", None), ("예외", types.SimpleNamespace(descendants=lambda: 1 / 0))):
    g = FakeGrid((range(1, 25), range(1, 25)), stale=0)
    g.vsb = vsb
    try:
        run_marks(g, 24)
        res = None
    except wellife.Stop as e:
        res = e.result
    check(f"내렸는데 그대로고 스크롤바를 못 읽으면({why}) 끝으로 보지 않고 멈춘다 (사용자 10-13 - 뒤 줄을 모름)", res == "failed", str(res))
g = FakeGrid((range(1, 25),), stale=0, review=lambda n: None if n == 5 else "", stuck=(7,))
out, bad = run_marks(g, 24)
check("검토를 못 읽은 줄(None)은 체크하지 않는다", out.get(5) == "선택안됨", str(out.get(5)))
check("눌러도 안 바뀐 줄은 '못 맞춘 줄' 로 남는다 (4-2 를 누르지 않는 근거)", bad == [7], str(bad))
g = FakeGrid((range(1, 25),), stale=0)
g.cells[24][wellife.CHECK_COL].rect = Rect(0, 95, 10, 105)     # 마지막 줄 체크 칸이 아래로 잘림
out, bad = run_marks(g, 24)
check("끝 줄이 잘려 못 눌렀으면 '못 맞춘 줄' (전체 체크된 채 넘어가지 않게)", bad == [24], str(bad))
g = FakeGrid((range(1, 25), range(1, 25)), stale=0)
g.vsb = Nav([El("페이지 아래로")])
try:
    run_marks(g, 24)
    res = None
except wellife.Stop as e:
    res = e.result
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
settings({"Wellife": {"Login": "Y", "SalesMode": "실행"}})
check("SalesMode '실행' 이어도 정상매출(NormalSalesMode)은 빠지면 리허설 - 업데이트만으로 매출처리를 시작하지 않는다 (PR #6 검토)",
      wellife.load_mode(rr, wellife.SALES_MODE_KEY) is True and wellife.load_mode(rr, wellife.NORMAL_SALES_MODE_KEY) is False
      and wellife.load_switches(rr)[1] == [])
settings({"Wellife": {"Login": "Y", "NormalSalesMode": "1건"}})
check("정상매출은 '1건'(하단 첫 줄)을 쓸 수 있다", wellife.load_mode(rr, wellife.NORMAL_SALES_MODE_KEY) == wellife.ONE)

rec = Rec()
rr.status = rec
got.clear()
rr.run_modules = fake_run_modules
settings({"Wellife": {"Login": "Y", "Mode": "실행"}})
wellife.run_main(rr)
start = rec.of("start")[0]
own_keys = {k for m in wellife.MODULES if m[0] in wellife.MODULE_MODES for k in m[3]}
check("단계 이름 앞에 모드 - ②④⑤⑥ 은 제 키(빠져서 [리허설]), 로그인·③ 은 Mode([실행])",
      all(label.startswith("[리허설] " if k in own_keys else "[실행] ") for k, label in start[1]), str(start[1][:4]))
rec = Rec()
rr.status = rec
settings({"Wellife": {"Login": "Y", "SalesMode": "실행"}})
wellife.run_main(rr)
labels = dict(rec.of("start")[0][1])
check("② 엑셀 수집은 SalesMode([실행]), 자동 수집은 ImportMode 가 없으면 SalesMode 를 따르고([실행]), 매출처리는 NormalSalesMode([리허설])",
      labels["wl_order_excel"].startswith("[실행] ") and labels["wl_order_import"].startswith("[실행] ")
      and labels["wl_order_sales"].startswith("[리허설] "), str(labels))
seen = []
_saved_ms = {n: getattr(wellife, n) for n in ("module_excel", "module_import", "module_sales")}
wellife.module_excel = lambda rr_, ctx_, live: seen.append(("excel", live)) or ("skipped", None)
wellife.module_import = lambda rr_, ctx_, live: seen.append(("import", live)) or ("skipped", None)
wellife.module_sales = lambda rr_, ctx_, sell: seen.append(("sales", sell)) or ("skipped", None)
for k in ("wellife_excel", "wellife_import", "wellife_sales"):
    got["funcs"][k](None)
for n, f in _saved_ms.items():
    setattr(wellife, n, f)
check("② 세 모듈에 각자의 모드를 넘긴다", seen == [("excel", True), ("import", True), ("sales", False)], str(seen))
settings({"Wellife": {"Login": "Y", "SalesMode": "실행", "ImportMode": "리허설"}})
check("ImportMode 를 적어 두면 SalesMode 와 따로 (자동 수집만 리허설)", wellife.load_mode(rr, wellife.IMPORT_MODE_KEY) is False
      and wellife.load_mode(rr, wellife.SALES_MODE_KEY) is True)
settings({"Wellife": {"Login": "Y", "ImportMode": "1건"}})
try:
    wellife.load_mode(rr, wellife.IMPORT_MODE_KEY)
    raised = False
except RuntimeError:
    raised = True
check("ImportMode 도 줄이 없어 '1건' 을 못 쓴다 (설정 오류)", raised)
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
seen_pop = []


def drawing(win):     # 막 뜬 팝업: 처음 몇 번은 단추가 안 그려져 [닫기] 만 보인다 (10-15 실측: 5-4 저장확인)
    seen_pop.append(1)
    return [El("닫기")] if len(seen_pop) < 4 else list(POP)


POP[:] = [Click("확인", on_click=POP.clear)]
texts = wellife.confirm_popups(pop_rr(find_popup_buttons=drawing), actx, "시험")
check("막 뜬 팝업이라 [확인] 이 아직 안 보이면 다시 보고, 보이면 누른다 (10-15 5-4 저장확인에서 멈춤)",
      acts == [("click", "확인")] and len(texts) == 1, f"{acts} {texts}")
acts.clear()
_settle = wellife.POPUP_SETTLE_SECONDS
wellife.POPUP_SETTLE_SECONDS = 1
POP[:] = [El("아니오")]
try:
    wellife.confirm_popups(pop_rr(), actx, "시험")
    res = None
except wellife.Stop as e:
    res = e.result
check("[예]/[확인] 이 끝내 없는 팝업은 누르지 않고 멈춘다", res == "stopped" and acts == [], f"{res} {acts}")
wellife.POPUP_SETTLE_SECONDS = _settle

# ② 주문매핑 동안(ctx.pass_popups) 은 단계 사이 팝업도 멈추지 않고 [예]/[확인] 으로 넘긴다 (사용자 2026-10-15)
fail_rr = lambda text: pop_rr(collect_popup_text=lambda b: text, match_sales_failure=lambda t: "실패" if "실패" in t else None)
pctx = types.SimpleNamespace(pid=1, hwnd=2, window=lambda: Nav([]), pass_popups=True)
acts.clear()
POP[:] = [El("아니오"), Click("예", on_click=POP.clear)]
try:
    wellife.no_popup(fail_rr("저장하시겠습니까?"), pctx, "시험")
    res = "통과"
except wellife.Stop as e:
    res = e.result
check("② 동안: 예상 못 한 팝업도 [아니오] 가 있어도 [예] 를 누르고 이어간다", res == "통과" and acts == [("click", "예")], f"{res} {acts}")
acts.clear()
POP[:] = [Click("확인", on_click=POP.clear)]
try:
    wellife.no_popup(fail_rr("매출처리 실패: 재고 없음"), pctx, "시험")
    res = "통과"
except wellife.Stop as e:
    res = e.result
check("② 동안: 매출처리 실패 팝업은 [확인] 으로 닫고 멈춘다", res == "stopped" and acts == [("click", "확인")], f"{res} {acts}")
acts.clear()
POP[:] = [Click("예", on_click=POP.clear)]
try:
    wellife.no_popup(fail_rr("저장하시겠습니까?"), types.SimpleNamespace(pid=1, hwnd=2, window=lambda: Nav([])), "시험")
    res = "통과"
except wellife.Stop as e:
    res = e.result
check("② 밖에서는 예전처럼 누르지 않고 멈춘다", res == "stopped" and acts == [], f"{res} {acts}")
POP.clear()
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
AGAIN = ["선택"]      # 누르기 직전 다시 읽는 체크 값
srr = pop_rr(status=Rec(), grid_rows=lambda g: {1: {wellife.CHECK_COL: AGAIN[0]}}, legacy_value=lambda v: v)
for live, count, enabled, want_click in ((False, 3, True, False), (True, 3, True, True),
                                         (True, 0, True, False), (True, 3, False, False)):
    acts.clear(); moves.clear(); POP.clear()
    stage_with(count, enabled)
    note, pressed = wellife.simple_stage(srr, actx, wellife.SAP_FORM, *stage, live=live)
    clicked = ("click", "btn_ThirdSend") in acts
    check(f"화살표 live={live} {count}건 단추{'켜짐' if enabled else '꺼짐'} -> {'누름 + 팝업 [예]' if want_click else '안 누름'}",
          clicked == want_click and pressed == want_click and (not want_click or ("click", "예") in acts),
          f"{note} {acts}")
_saved_ca = wellife.check_all_rows
wellife.check_all_rows = lambda *a: True
check_stage = ("wl_sap_shipping", "dashBtn_ShippingInfo", "btn_ThirdSend", True, "4-3 선분할 배송정보 → S/O 생성요청")
for again, want_click in (("선택", True), ("선택안됨", False)):
    acts.clear(); POP.clear()
    stage_with(3)
    wellife.open_stage = lambda rr_, ctx_, form, dash: (3, {"btn_ThirdSend": arrow_btn, "gridCtrl_List": "g"})
    AGAIN[0] = again
    note, pressed = wellife.simple_stage(srr, actx, wellife.SAP_FORM, *check_stage, live=True)
    check(f"체크 칸이 있는 단계: 화살표 직전 다시 본 체크 '{again}' -> {'누름' if want_click else '안 누름 + 사유에 확인할 것 (재확인, 사용자 10-13)'}",
          (("click", "btn_ThirdSend") in acts) == want_click and pressed == want_click
          and (wellife.RECHECK_NOTE in note) == (not want_click), f"{note} {acts}")
AGAIN[0] = "선택"
wellife.check_all_rows = _saved_ca
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
def hold_rr(rows=1, tab=True, again="선택"):
    """tab: '일반' 탭을 찾았는가. again: 저장 직전 다시 읽은 체크 값 (조회가 늦게 끝나 풀렸으면 '선택안됨')."""
    grid = types.SimpleNamespace(rectangle=lambda: Rect(0, 50, 200, 300),     # 머리글 체크 칸 + 줄 rows 개
                                 descendants=lambda control_type=None: [El(wellife.CHECK_COL)] if control_type == "Header"
                                 else [1] * rows)
    return pop_rr(status=Rec(), click_subtab=lambda app, hwnd, name: acts.append(("tab", name)) or tab,
                  STOCK_GENERAL_TAB_NAME="일반", get_onscreen_tables=lambda win: [grid],
                  wait_grid_spinner_gone=lambda *a, **k: True,
                  grid_rows=lambda g: {n: {wellife.CHECK_COL: again} for n in range(1, rows + 1)},
                  legacy_value=lambda v: v,
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
for what, kw in (("'일반' 탭을 못 찾으면 조회·저장하지 않고 멈춘다 (다른 서브탭의 단추를 누르지 않게)", {"tab": False}),
                 ("저장 직전 다시 보니 체크가 풀려 있으면 저장하지 않는다 (사용자 10-13 - 재확인)", {"again": "선택안됨"})):
    acts.clear(); POP.clear()
    try:
        wellife.hold_save(hold_rr(**kw), hctx, True)
        res = None
    except wellife.Stop as e:
        res = e.result
    check(f"물류대기: {what}", res == "failed" and ("click", "저장(S)") not in acts, f"{res} {acts}")
acts.clear(); POP.clear()
res = wellife.hold_save(hold_rr(again="선택안됨"), hctx, False)
check("물류대기 리허설: 다시 보니 풀려 있으면 '확인할 것' 을 사유에 남긴다 (실행이었다면 누르지 않음)",
      res[0] == "skipped" and wellife.RECHECK_NOTE in res[1], str(res))

# 주문 수집: 엑셀이 있을 때만 올리고, 자동 수집은 상단 전체선택 -> [가져오기] (리허설은 전체선택 + 마우스만, 사용자 10-14)
xdir = tempfile.mkdtemp(prefix="rpa_wl_xl_")
uploads = []


def order_rr(files):
    return pop_rr(status=Rec(), excel_upload_dir=lambda: xdir,
                  collect_upload_files=lambda folder: (files, [], []),
                  get_onscreen_tables=lambda win: [El("사이트", Rect(0, 50, 200, 100))],
                  run_excel_upload_step=lambda app, pid, hwnd, grid: uploads.append(grid.name) or (len(files), 0),
                  find_site_upload_cell=lambda hwnd, grid, code: (El(f"업로드 {code}"), "1"),
                  select_all_and_verify=lambda name, hwnd, grid, cols: acts.append(("select", name, grid.name)) or 4,
                  run_import_step=lambda app, pid, hwnd, win: acts.append(("click", "가져오기", getattr(win, "name", "창"))) or IMPORTED[0],
                  find_by_text=lambda win, text, control_types=(): FOUND[0] or next(
                      (e for e in win.descendants() if e.window_text() == text), None),
                  IMPORT_BUTTON_NAME="가져오기")


IMPORTED, FOUND = [True], [None]
_saved_cp = wellife.clear_point
wellife.clear_point = lambda rr_, ctx_, el, what: acts.append(("clear", el.name)) or (0, 0)
class Page(Nav):
    name = "떠 있는 화면"


octx = types.SimpleNamespace(pid=1, hwnd=2, app=None, window=lambda: Page([El("가져오기")]))
_saved_ns = wellife.normal_sales
SOLD = [False]
wellife.normal_sales = lambda rr_, ctx_, live: (acts.append(("normal_sales", live)), ("매출처리 흉내", SOLD[0]))[1]
for live, files, want_res, want_up in ((True, {}, "skipped", []), (False, {"101": "x"}, "skipped", []),
                                       (True, {"101": "x"}, "done", ["사이트"])):
    acts.clear(); uploads.clear()
    res = wellife.excel_collect(order_rr(files), octx, live)
    check(f"엑셀 수집 live={live} 엑셀 {len(files)}건 -> {want_res}, 업로드 {len(want_up)}번, [가져오기]·정상매출은 하지 않음 (10-15 셋으로 나눔)",
          res[0] == want_res and uploads == want_up and not [a for a in acts if a[0] in ("click", "select", "normal_sales")],
          f"{res} {uploads} {acts}")


def upload_stop(app, pid, hwnd, grid):
    raise rr.UploadStop("처리할 수 있는 버튼이 없습니다.")


stop_rr = order_rr({"101": "x"})
stop_rr.run_excel_upload_step, stop_rr.UploadStop = upload_stop, rr.UploadStop
try:
    wellife.excel_collect(stop_rr, octx, True)
    res = None
except wellife.Stop as e:
    res = e.result, str(e)
check("엑셀 업로드 중 누를 단추를 모르는 창이 뜨면 멈춤 (누르지 않음)", res is not None and res[0] == "stopped" and "모르는 창" in res[1],
      str(res))
press = ("click", "가져오기", "떠 있는 화면")
for live in (True, False):
    acts.clear(); uploads.clear()
    res = wellife.import_collect(order_rr({"101": "x"}), octx, live)
    check(f"자동 수집 live={live}: 상단 전체선택 뒤 [가져오기] {'누를 자리 확인 뒤 떠 있는 화면만 넘겨 누름' if live else '안 누름 (마우스만)'}, "
          f"엑셀 업로드·정상매출은 안 함",
          res[0] == ("done" if live else "skipped") and (press in acts) == live and not uploads
          and (not live or acts.index(("clear", "가져오기")) < acts.index(press))
          and acts.index(("select", "좌측상단", "사이트")) < (acts.index(press) if live else len(acts))
          and not [a for a in acts if a[0] == "normal_sales"], f"{res} {acts}")


def collect_stop(rr_, ctx_=octx):
    acts.clear()
    try:
        wellife.import_collect(rr_, ctx_, True)
        return None
    except wellife.Stop as e:
        return e.result, str(e)


IMPORTED[0] = False
res = collect_stop(order_rr({}))
check("[가져오기] 끝을 확인 못 하면 다음 모듈로 넘어가지 않고 멈춘다 ('확인할 것', 리뷰 10-14)",
      res and res[0] == "stopped" and "확인할 것" in res[1], f"{res} {acts}")
IMPORTED[0] = True
zero_rr = order_rr({})
zero_rr.select_all_and_verify = lambda *a: None
res = collect_stop(zero_rr)
check("상단 전체선택을 확인 못 하면 [가져오기] 를 누르지 않고 멈춘다 (웰라이프는 모르면 멈춘다)",
      res and res[0] == "failed" and not [a for a in acts if a[0] == "click"], f"{res} {acts}")
FOUND[0] = El("가져오기", Rect(10, 900, 150, 930))     # 다시 찾은 단추가 다른 자리 (숨은 화면의 같은 이름 단추)
res = collect_stop(order_rr({}))
check("누를 단추가 확인한 단추와 다른 자리면 누르지 않고 멈춘다 (숨은 화면 단추, 리뷰 10-14)",
      res and res[0] == "failed" and not [a for a in acts if a[0] in ("click", "clear")], f"{res} {acts}")
FOUND[0] = None
acts.clear()
res = wellife.import_collect(order_rr({}), types.SimpleNamespace(pid=1, hwnd=2, app=None, window=lambda: Nav([])), True)
check("[가져오기] 단추가 없으면 전체선택도 누르기도 않고 사유에 남긴다",
      not [a for a in acts if a[0] in ("select", "click")] and "자동 수집 단추 없음" in res[1], f"{res} {acts}")
wellife.normal_sales = _saved_ns
wellife.clear_point = _saved_cp

# ② 하단 전체선택 -> 매출처리 ▼ 정상매출 (원래 PROCESS module_sales 8~11 단계, 사용자 10-14)
_saved_n = {n: getattr(wellife, n) for n in ("front", "no_popup", "clear_point", "check_header", "recheck",
                                               "hover_menu_item", "press_menu_item", "after_normal_sales", "check_one_row")}
NS = {"rows": {1: {}}, "again": True, "split": True, "one": True}
wellife.check_one_row = lambda rr_, ctx_, grid, label: acts.append(("one", grid.name)) or NS["one"]
wellife.front = wellife.no_popup = lambda *a: None
wellife.clear_point = lambda *a: (0, 0)
wellife.check_header = lambda grid, label="": El("row Check Box")
wellife.recheck = lambda rr_, grid, label, live: NS["again"]
wellife.hover_menu_item = lambda rr_, ctx_, split, item, what, would: acts.append(("hover", item, would)) or ""
wellife.press_menu_item = lambda rr_, ctx_, split, item, what, grid=None, confirm=True: (
    acts.append(("press", item, confirm)), (f" -> '{item}' 누름", True))[1]
wellife.after_normal_sales = lambda rr_, ctx_, base: acts.append(("after",)) or " (완료)"
ns_top, ns_bottom = El("사이트", Rect(0, 50, 200, 100)), El("주문", Rect(0, 300, 200, 500))
nrr = types.SimpleNamespace(status=Rec(), log=lambda m: None, visible_child_windows=lambda h: {},
                            get_onscreen_tables=lambda win: [ns_top, ns_bottom],
                            grid_rows=lambda g: NS["rows"] if g is ns_bottom else {},
                            select_all_and_verify=lambda name, h, g, cols: acts.append(("select_all", g.name, tuple(cols))) or 3,
                            find_by_text=lambda win, text, control_types=None: El(text) if NS["split"] else None)


def run_ns(live, **kw):
    NS.update({"rows": {1: {}}, "again": True, "split": True, "one": True}); NS.update(kw); acts.clear()
    try:
        return wellife.normal_sales(nrr, octx, live), None
    except wellife.Stop as e:
        return None, e.result


(note, sold), _ = run_ns(False)
check("리허설: 하단 전체선택(원래 select_all_and_verify) -> ▼ 를 열어 '정상매출' 에 마우스만 (누르지 않음)",
      acts == [("select_all", "주문", tuple(wellife.BOTTOM_ID_COLUMNS)), ("hover", "정상매출", True)] and sold is False
      and "정상매출은 누르지 않음" in note, f"{note} {acts}")
(note, sold), _ = run_ns(True)
check("실행: 하단 전체선택 -> ▼ '정상매출' 누름 (팝업은 원래 코드가 - confirm=False) -> 원래 팝업·대기 처리",
      acts == [("select_all", "주문", tuple(wellife.BOTTOM_ID_COLUMNS)), ("press", "정상매출", False), ("after",)] and sold,
      f"{note} {acts}")
(note, sold), _ = run_ns(True, rows={})
check("하단 0줄이면 전체선택도 매출처리도 하지 않는다 (원래는 0건이어도 누름 - 웰라이프는 안 누름)",
      acts == [] and sold is False and "0줄" in note, f"{note} {acts}")
(note, sold), _ = run_ns(True, again=False)
check("실행: 누르기 직전 다시 보니 체크가 풀려 있으면 정상매출을 누르지 않는다",
      ("press", "정상매출", False) not in acts and sold is False and "확인할 것" in note, f"{note} {acts}")
_, err = run_ns(True, split=False)
check("'매출처리' 단추가 없으면 멈춘다", err == "failed")
(note, sold), _ = run_ns(wellife.ONE)
check("1건: 하단 첫 줄만 체크(전체선택 안 함) -> 정상매출",
      acts == [("one", "주문"), ("press", "정상매출", False), ("after",)] and sold and "첫 줄 1건" in note, f"{note} {acts}")
(note, sold), _ = run_ns(wellife.ONE, one=False)
check("1건: 첫 줄 체크를 못 했으면 다시 보기가 '한 줄 체크' 로 맞아도(이미 체크돼 있던 줄) 누르지 않는다",
      ("press", "정상매출", False) not in acts and sold is False and "확인할 것" in note, f"{note} {acts}")
for n, f in _saved_n.items():
    setattr(wellife, n, f)

# 정상매출 뒤 - 원래 module_sales 10~11 단계 그대로: 확인 팝업 [예]/[확인], 실패 문구면 멈춤
AF = {"ok": None, "failure": None, "async": "clicked", "sep": (None, 0)}
arr = types.SimpleNamespace(log=lambda m: None, status=Rec(), ASYNC_MAX_WAIT_SECONDS=600,
                            find_popup_ok_button=lambda win: AF["ok"], find_popup_failure=lambda win: AF["failure"],
                            ec=types.SimpleNamespace(ensure_foreground=lambda h: True),
                            probe_spinner=lambda h, b: None, wait_async_then_confirm=lambda app, h, b: AF["async"],
                            handle_sales_popups=lambda pid, h, tried: AF["sep"])


def run_after(**kw):
    AF.update({"ok": None, "failure": None, "async": "clicked", "sep": (None, 0)}); AF.update(kw); acts.clear()
    try:
        return wellife.after_normal_sales(arr, octx, {}), None
    except wellife.Stop as e:
        return None, (e.result, str(e))


wellife.time.sleep = lambda s: None
aft, err = run_after(ok=Click("예"))
check("확인 팝업은 [예] 를 누르고, 완료까지 기다린다 (원래 규칙)", ("click", "예") in acts and err is None and "완료" in aft, f"{aft} {acts}")
aft, err = run_after(ok=Click("확인"), failure="정상매출 실패")
check("확인 팝업에 매출처리 실패 문구면 닫고 멈춘다 (뒤 모듈을 돌리지 않음)", err and err[0] == "stopped" and "실패" in err[1], str(err))
aft, err = run_after(**{"async": "sales_failed"})
check("기다리는 중 실패 팝업이면 멈춘다", err and err[0] == "stopped", str(err))
aft, err = run_after(sep=("매출처리 실패", 1))
check("따로 뜬 창의 실패 팝업이면 멈춘다", err and err[0] == "stopped", str(err))
aft, err = run_after(**{"async": "timeout"})
check("대기 시간 초과는 '확인할 것' 을 남기고 이어 간다 (원래와 같음)", err is None and "확인할 것" in aft, str(aft))
wellife.time.sleep = _sleep
TOP[0] = 1


# 4-1 → 4-2 순서 (사용자 10-08): 전체 체크 → [지정▼] 선택 항목만 → 검토 빈 줄만 체크 → 화살표
def run_slip(live, checked=True, pressed=True, marks=None, bad=(), again=True, held=True):
    """again: 지정 직전 다시 본 체크가 맞는가, held: 화살표 직전 다시 본 체크가 맞춘 값 그대로인가 (사용자 10-13 재확인)."""
    names = ("open_stage", "check_all_rows", "hover_menu_item", "press_menu_item", "controls", "mark_rows", "press_arrow",
             "recheck", "marks_held")
    saved = {n: getattr(wellife, n) for n in names}
    seq = []
    wellife.open_stage = lambda *a: (seq.append("조회"), (3, {"gridCtrl_List": "g"}))[1]
    wellife.check_all_rows = lambda *a: (seq.append("전체 체크"), checked)[1]
    wellife.recheck = lambda *a: again
    wellife.marks_held = lambda *a: held
    wellife.hover_menu_item = lambda *a: (seq.append("지정 마우스만"), "")[1]
    wellife.press_menu_item = lambda *a: (seq.append("지정 누름"), ("", pressed))[1]
    wellife.controls = lambda *a: (seq.append("다시 잡기"), {"gridCtrl_List": "g2"})[1]
    wellife.mark_rows = lambda rr_, ctx, grid, n, want, limit=None: (seq.append(f"줄 맞추기 {grid}" + (f" 최대 {limit}" if limit else "")),
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
res, seq = run_slip(True, again=False)
check("실행: 지정 직전 다시 보니 체크가 풀려 있으면 지정도 화살표도 누르지 않는다 (재확인)", seq == ["조회", "전체 체크"] and res[1] is False,
      f"{seq}")
res, seq = run_slip(True, held=False)
check("실행: 화살표 직전 다시 보니 맞춘 체크가 바뀌어 있으면 화살표를 누르지 않는다 (재확인)",
      seq[-1].endswith("want=False live=True") and wellife.RECHECK_NOTE in res[0], f"{seq} {res}")

# ---------------------------------------------------------------------------
print("=== 12. ⑥ 운송장번호 전송 (모든 업체용 화면, 지금은 웰라이프만) ===")
import rpa_status as st  # noqa: E402

check("모드 키가 rpa_status.WELLIFE_MODES(웹 보기)와 같은 키·순서", [k for k, _ in st.WELLIFE_MODES] == list(wellife.MODE_NAMES))
check("Wellife 설정 키가 rpa_status.WELLIFE_CONFIG_MODULES 와 같다",
      [m[1] for m in wellife.MODULES] == [k for k, _ in st.WELLIFE_CONFIG_MODULES])
check("모든 업체용 모듈 키 = 설정 키 소문자 (wellife_ 없음 - agent.history_key·토큰 배율이 같은 키)",
      [(m[0], m[1]) for m in wellife.MODULES if m[1] in st.SHARED_MODULES] == [("invoicesend", "InvoiceSend")])
check("모듈 비트가 겹치지 않는다", len({m[4] for m in wellife.MODULES} | {m[4] for m in rr.ROUTINE_MODULES})
      == len(wellife.MODULES) + len(rr.ROUTINE_MODULES) - 2)   # login(1)·운송장번호 전송(512, 모든 업체용 - 2026-10-13) 만 같다
settings({"Wellife": {"Login": "Y", "Mode": "실행", "InvoiceMode": "리허설"}})
check("InvoiceMode 는 Mode 와 따로 읽고 모르는 키가 아니다",
      wellife.load_mode(rr) is True and wellife.load_mode(rr, wellife.INVOICE_MODE_KEY) is False
      and wellife.load_switches(rr)[1] == [])
settings({"Wellife": {"Login": "Y", "Mode": "실행"}})
check("InvoiceMode 가 없으면 Mode 를 따르지 않고 리허설", wellife.load_mode(rr, wellife.INVOICE_MODE_KEY) is False)

rr.run_modules = fake_run_modules
rec, starts, seen = Rec(), [], []
rec.start = lambda *a, **k: starts.append((a, k))
rr.status = rec
got.clear()
_saved_inv = wellife.module_invoice_send
wellife.module_invoice_send = lambda rr_, ctx_, live: seen.append(live) or ("skipped", None)
settings({"Wellife": {"Login": "Y", "InvoiceSend": "Y", "InvoiceMode": "실행"}})
wellife.run_main(rr)
got["funcs"]["invoicesend"](None)
wellife.module_invoice_send = _saved_inv
check("⑥ 은 InvoiceMode 로 돈다 (Mode 가 빠져 리허설이어도 실행)", seen == [True], str(seen))
labels = dict(starts[0][0][1]) if starts else {}
check("⑥ 단계 이름 앞은 [실행], 그 밖은 [리허설] / 제목에 운송장 전송 모드",
      labels.get("inv_send", "").startswith("[실행] ") and labels.get("wl_wms_so", "").startswith("[리허설] ")
      and "운송장 전송 실행" in starts[0][1].get("title", ""), f"{labels.get('inv_send')} {starts[:1]}")
settings({"Wellife": {"Login": "Y", "InvoiceMode": "보냄"}})
rec = Rec()
rr.status = rec
got.clear()
wellife.run_main(rr)
fin = rec.of("finish")
check("InvoiceMode 가 잘못되면 아무것도 돌리지 않고 설정 파일 오류", not got and fin and "설정 파일 오류" in fin[-1][1], str(fin))
picked_run("InvoiceSend")
check("예약 줄이 운송장 전송만 고르면 로그인 + ⑥ 만 (반복 시간대도 같은 길)",
      got.get("selected") == {"Login": True, "Excel": False, "Import": False, "Sales": False, "Hold": False, "Sap": False, "Wms": False, "InvoiceSend": True},
      str(got.get("selected")))
picked_run("InvoiceSend", trigger="repeat")
check("반복 회차가 보낸 것이 없으면 이력에 남기지 않는다", fins and fins[-1][1].get("record") is False, str(fins))
rr.run_modules = orig_run_modules

# 조회 -> 전체 체크 -> [전송요청(S)]: 실행이면 누르고 팝업 [예], 리허설이면 마우스만
send_btn = Click("btn_SendRequest", on_click=lambda: POP.extend([Click("예", on_click=POP.clear)]))
INV = {"rows": 3, "checked": True, "forms": []}
_saved_inv = wellife.controls, wellife.count_rows, wellife.check_all_rows
_saved_eq = wellife.ensure_query
wellife.ensure_query = lambda *a: []          # 조회 조건 기본값은 아래 14절에서 따로
wellife.controls = lambda rr_, ctx_, form: INV["forms"].append(form) or {
    "btn_Search": El("조회(F)"), "gridCtrl_List": "grid", "btn_SendRequest": send_btn}
wellife.count_rows = lambda rr_, ctx_, grid: INV["rows"]
wellife.check_all_rows = lambda rr_, ctx_, grid, label: acts.append(("check_all",)) or INV["checked"]
_sleep = wellife.time.sleep
wellife.time.sleep = lambda s: _sleep(min(s, 0.01))
TOP[0] = actx.hwnd


def inv_run(live, rows=3, checked=True, on=True, popup=(), later="선택"):
    """later: 누르기 직전에 다시 읽는 체크 값 (조회가 늦게 끝나면 '선택안됨' 으로 풀린다)."""
    acts.clear(); moves.clear(); POP[:] = list(popup)
    INV.update(rows=rows, checked=checked, forms=[])
    send_btn.on = on
    return wellife.invoice_send(pop_rr(status=Rec(), wait_grid_spinner_gone=lambda *a, **k: True,
                                       grid_rows=lambda g: {1: {wellife.CHECK_COL: Cell(later)}, 2: {"마켓명": Cell("x")}},
                                       legacy_value=lambda el: el.v), actx, live)


res = inv_run(False)
check("리허설: 조회 -> 전체 체크 -> [전송요청(S)] 에 마우스만 (누르지 않음)",
      acts == [("click", "조회(F)"), ("check_all",)] and res[0] == "skipped" and res[1].startswith("[리허설] 운송장 3건")
      and moves and set(INV["forms"]) == {wellife.INVOICE_FORM}, f"{res} {acts}")
res = inv_run(True)
check("실행: 조회 -> 전체 체크 -> [전송요청(S)] 누름 -> 팝업 [예]",
      acts == [("click", "조회(F)"), ("check_all",), ("click", "btn_SendRequest"), ("click", "예")] and res[0] == "done",
      f"{res} {acts}")
res = inv_run(True, rows=0)
check("실행: 0건이면 체크도 전송요청도 하지 않는다 (no_target)",
      res[0] == "no_target" and acts == [("click", "조회(F)")], f"{res} {acts}")
res = inv_run(True, checked=False)
check("실행: 전체 체크가 안 되면 전송요청을 누르지 않는다 (확인할 것)",
      ("click", "btn_SendRequest") not in acts and res[0] == "skipped" and "확인할 것" in res[1], f"{res} {acts}")
res = inv_run(True, later="선택안됨")
check("실행: 누르기 직전에 다시 보니 체크가 풀려 있으면 누르지 않는다 (조회가 늦게 끝난 경우)",
      ("click", "btn_SendRequest") not in acts and res[0] == "skipped" and "확인할 것" in res[1], f"{res} {acts}")
res = inv_run(True, on=False)
check("실행: 단추가 꺼져 있으면 누르지 않는다", ("click", "btn_SendRequest") not in acts and res[0] == "skipped"
      and "꺼짐" in res[1], f"{res} {acts}")
try:
    inv_run(True, popup=[El("예")])
    res = None
except wellife.Stop as e:
    res = e.result
check("조회 전에 팝업이 떠 있으면 누르지 않고 멈춘다", res == "stopped" and acts == [], f"{res} {acts}")
wellife.controls = lambda rr_, ctx_, form: {"gridCtrl_List": "grid"}
try:
    inv_run(True)
    res = None
except wellife.Stop as e:
    res = e.result
check("조회(F) 단추가 없으면 멈춘다 (failed)", res == "failed" and acts == [], f"{res} {acts}")
wellife.controls, wellife.count_rows, wellife.check_all_rows = _saved_inv
wellife.ensure_query = _saved_eq
POP.clear()

# 화면 열기: 이미 열린 탭이면 그 탭, 아니면 좌측 아이콘 (없으면 건너뛰지 않고 실패)
_saved_inv = wellife.open_tab, wellife.invoice_send
wellife.invoice_send = lambda rr_, ctx_, live: ("skipped", f"전송 live={live}")
icons = []


def nav_rr(icon="ok", tab_ok=True):
    return pop_rr(status=Rec(), goto_screen_by_icon=lambda ctx_, key, label, tab: icons.append(key) or icon,
                  wait_for_active_main_tab=lambda app, hwnd, kw, ctx=None: (tab_ok, kw if tab_ok else "메인페이지"))


ictx = types.SimpleNamespace(pid=1, hwnd=2, app=None, window=lambda: Nav([]))
wellife.open_tab = lambda rr_, ctx_, name: El(name)
acts.clear(); icons.clear()
res = wellife.module_invoice_send(nav_rr(), ictx, True)
check("이미 열린 탭이면 그 탭을 누르고 아이콘은 안 누른다", acts == [("click", wellife.INVOICE_TAB)] and not icons
      and res == ("skipped", "전송 live=True"), f"{res} {acts} {icons}")
res = wellife.module_invoice_send(nav_rr(tab_ok=False), ictx, True)
check("탭을 눌렀는데 바뀌지 않으면 failed", res[0] == "failed", str(res))
wellife.open_tab = lambda rr_, ctx_, name: None
for icon, want in (("ok", "skipped"), ("absent", "failed"), ("failed", "failed")):
    icons.clear()
    res = wellife.module_invoice_send(nav_rr(icon), ictx, False)
    check(f"열린 탭이 없으면 아이콘 {wellife.INVOICE_ICON} -> '{icon}' 이면 {want}",
          icons == [wellife.INVOICE_ICON] and res[0] == want, f"{res} {icons}")
wellife.invoice_send = lambda rr_, ctx_, live: (_ for _ in ()).throw(RuntimeError("COMError 흉내"))
res = wellife.module_invoice_send(nav_rr(), ictx, True)
check("UI 오류는 ('failed', 'UI 오류: … - 문구')", res == ("failed", "UI 오류: RuntimeError - COMError 흉내"), str(res))
wellife.open_tab, wellife.invoice_send = _saved_inv
wellife.time.sleep = _sleep

# 줄 세기: 세로 스크롤바가 있으면 맨 위에서부터 넘기며 행 번호로 (앞 페이지가 그대로 읽히는 경우 포함)
g = FakeGrid((range(1, 25), range(24, 48), range(47, 60)))
crr = grid_rr(g)
crr.grid_vertical_scrollbar = lambda grid: "vsb"
check("세로 스크롤바가 있으면 끝까지 넘겨 센다 (59줄)", wellife.count_rows(crr, actx, g) == 59 and g.tops == 1, str(g.tops))
g = FakeGrid((range(1, 3),))
crr = grid_rr(g)
crr.grid_vertical_scrollbar = lambda grid: None
check("스크롤바가 없으면 보이는 줄 (2줄)", wellife.count_rows(crr, actx, g) == 2 and g.tops == 0)
crr.grid_rows = lambda grid: {}
check("줄이 없으면 0", wellife.count_rows(crr, actx, g) == 0)

# 스크롤바 캐시: 같은 자리에 그리드가 있던 다른 화면(숨으면 창 밖)의 스크롤바는 돌려주지 않고 새로 찾는다
own_bar, other_bar = El("bar", Rect(480, 100, 500, 600)), El("bar", Rect(-1440, 100, -1420, 600))
sgrid = types.SimpleNamespace(rectangle=lambda: Rect(0, 100, 500, 600),
                              descendants=lambda control_type=None: [own_bar],
                              parent=lambda: types.SimpleNamespace(descendants=lambda control_type=None: []))
rr._GRID_SCROLLBAR_CACHE[(0, 100, 500, 600)] = other_bar
check("스크롤바 캐시가 그리드 밖 스크롤바면 새로 찾는다", rr.grid_vertical_scrollbar(sgrid) is own_bar)
check("그리드 안 스크롤바는 캐시에서 그대로", rr.grid_vertical_scrollbar(sgrid) is own_bar
      and rr._GRID_SCROLLBAR_CACHE[(0, 100, 500, 600)] is own_bar)

# ---------------------------------------------------------------------------
print("=== 13. SAP·WMS 모드 따로, 실행 '1건' (사용자 10-13) ===")
ONE = wellife.ONE
settings({"Wellife": {"Login": "Y", "Mode": "실행"}})
check("SapMode·WmsMode 가 빠지면 Mode(실행)를 따르지 않고 리허설",
      wellife.load_mode(rr) is True and wellife.load_mode(rr, wellife.SAP_MODE_KEY) is False
      and wellife.load_mode(rr, wellife.WMS_MODE_KEY) is False)
settings({"Wellife": {"Login": "Y", "SapMode": "실행", "WmsMode": "1건", "InvoiceMode": "1건"}})
check("SapMode·WmsMode 는 따로 읽고, '1건' 은 ONE(참) - 모르는 키가 아니다",
      wellife.load_mode(rr, wellife.SAP_MODE_KEY) is True and wellife.load_mode(rr, wellife.WMS_MODE_KEY) == ONE
      and bool(ONE) and wellife.load_switches(rr)[1] == [] and wellife.mode_tag(ONE) == "1건")
settings({"Wellife": {"Login": "Y", "SalesMode": "1건"}})
try:
    wellife.load_mode(rr, wellife.SALES_MODE_KEY)
    raised = False
except RuntimeError:
    raised = True
check("② SalesMode 는 줄이 없어 '1건' 을 못 쓴다 (설정 오류)", raised)

rr.run_modules = fake_run_modules
rec, starts, seen = Rec(), [], {}
rec.start = lambda *a, **k: starts.append((a, k))
rr.status = rec
got.clear()
_saved_mods = wellife.module_hold, wellife.module_sap, wellife.module_wms
wellife.module_hold = lambda rr_, ctx_, live: seen.update(hold=live) or ("skipped", None)
wellife.module_sap = lambda rr_, ctx_, live: seen.update(sap=live) or ("skipped", None)
wellife.module_wms = lambda rr_, ctx_, live: seen.update(wms=live) or ("skipped", None)
settings({"Wellife": {"Login": "Y", "Hold": "Y", "Sap": "Y", "Wms": "Y", "Mode": "실행", "SapMode": "1건"}})
wellife.run_main(rr)
for k in ("wellife_hold", "wellife_sap", "wellife_wms"):
    got["funcs"][k](None)
wellife.module_hold, wellife.module_sap, wellife.module_wms = _saved_mods
rr.run_modules = orig_run_modules
labels = dict(starts[0][0][1]) if starts else {}
check("③ 은 Mode, ④ 는 SapMode, ⑤ 는 WmsMode 로 돈다", seen == {"hold": True, "sap": ONE, "wms": False}, str(seen))
check("단계 이름·제목에 모듈마다 모드 ([실행] 물류대기 / [1건] SAP / [리허설] WMS)",
      labels.get("wl_hold_save", "").startswith("[실행] ") and labels.get("wl_sap_slip", "").startswith("[1건] ")
      and labels.get("wl_wms_so", "").startswith("[리허설] ") and "SAP 연동 1건" in starts[0][1].get("title", ""),
      f"{labels.get('wl_sap_slip')} {starts[0][1] if starts else None}")

# 첫 줄 하나만 체크: 조회 직후(모두 풀림)에서 맨 위 첫 줄만 누르고, 그 줄만 '선택' 인지 다시 본다
_saved_cn = wellife.click, wellife.no_popup


def one_grid(checked=(), stuck=()):
    g = FakeGrid((range(1, 25), range(24, 48)), stuck=stuck)
    for n, c in g.cells.items():
        c[wellife.CHECK_COL].v = "선택" if n in checked else "선택안됨"
    g.clicks = []
    return g


def one_run(g):
    wellife.click = lambda rr_, ctx, el, what: (g.clicks.append(el), g.toggle(el))
    wellife.no_popup = lambda *a: None
    try:
        return wellife.check_one_row(grid_rr(g), actx, g, "시험")
    finally:
        wellife.click, wellife.no_popup = _saved_cn


g = one_grid()
ok = one_run(g)
check("'1건': 맨 위로 올리고 첫 줄만 체크 (다른 줄은 그대로)",
      ok and g.tops == 1 and g.clicks == [g.cells[1][wellife.CHECK_COL]]
      and [n for n, c in g.cells.items() if c[wellife.CHECK_COL].v == "선택"] == [1], str(g.clicks))
g = one_grid(checked=(3,))
check("'1건': 이미 체크된 줄이 보이면 누르지 않는다 (그 줄도 넘어가지 않게)", one_run(g) is False and g.clicks == [])
g = one_grid(stuck=(1,))
check("'1건': 눌러도 체크가 안 되면 실패", one_run(g) is False)
g = one_grid()
g.cells[2][wellife.CHECK_COL].v = None
check("'1건': 체크 값을 못 읽은 줄이 보이면 누르지 않는다 (이미 체크된 줄인지 몰라서 - 사용자 10-13)",
      one_run(g) is False and g.clicks == [])
check("다시 확인(1건): 보이는 줄 중 꼭 하나만 체크", wellife.rows_checked(
    types.SimpleNamespace(grid_rows=lambda g_: {1: {wellife.CHECK_COL: Cell("선택")}, 2: {wellife.CHECK_COL: Cell("선택안됨")}},
                          legacy_value=lambda el: el.v), None, one=True)
      and not wellife.rows_checked(
    types.SimpleNamespace(grid_rows=lambda g_: {1: {wellife.CHECK_COL: Cell("선택")}, 2: {wellife.CHECK_COL: Cell("선택")}},
                          legacy_value=lambda el: el.v), None, one=True))

# 4-2 '1건': 검토 빈 줄 중 위에서 처음 만난 한 줄만 넘긴다
g = FakeGrid((range(1, 25), range(24, 48), range(47, 60)), review=lambda n: "" if n % 5 == 0 else "택배X")
wellife.click = lambda rr_, ctx, el, what: (g.clicks.append(el), g.toggle(el))
wellife.no_popup = lambda *a: None
g.clicks = []
try:
    out, bad = wellife.mark_rows(grid_rr(g), actx, g, 59, wellife.slip_target, limit=1)
finally:
    wellife.click, wellife.no_popup = _saved_cn
check("4-2 '1건': 넘길 줄(검토 빈 칸) 중 첫 줄(5행)만 '선택', 나머지는 '선택안됨'",
      [n for n, v in out.items() if v == "선택"] == [5] and not bad and len(out) == 59, f"{[n for n, v in out.items() if v == '선택']} {bad}")

# 단계·물류대기·운송장: '1건' 이면 전체 체크 대신 첫 줄만, 체크 칸이 없는 단계는 그대로 누른다
_saved_chk = wellife.check_one_row, wellife.check_all_rows, wellife.open_stage
wellife.check_one_row = lambda *a: acts.append(("check_one",)) or True
wellife.check_all_rows = lambda *a: acts.append(("check_all",)) or True
TOP[0] = actx.hwnd
for stage, want in ((("wl_sap_shipping", "dashBtn_ShippingInfo", "btn_ThirdSend", True, "4-3 선분할 배송정보 → S/O 생성요청"),
                     [("check_one",), ("click", "btn_ThirdSend"), ("click", "예")]),
                    (("wl_sap_so", "dashBtn_Create_SO", "btn_ThirdSend", False, "4-4 SO생성 → SAP 전송"),
                     [("click", "btn_ThirdSend"), ("click", "예")])):
    acts.clear(); POP.clear()
    arrow_btn.on = True
    wellife.open_stage = lambda rr_, ctx_, form, dash: (3, {"btn_ThirdSend": arrow_btn, "gridCtrl_List": "g"})
    note, pressed = wellife.simple_stage(srr, actx, wellife.SAP_FORM, *stage, live=ONE)
    check(f"'1건' {stage[4].split(' →')[0]}: {'첫 줄만 체크 -> 화살표' if stage[3] else '체크 칸 없음 -> 건수와 상관없이 화살표 (사용자 10-13)'}",
          acts == want and pressed, f"{note} {acts}")
wellife.check_one_row, wellife.check_all_rows, wellife.open_stage = _saved_chk
_saved_chk = wellife.check_one_row
wellife.check_one_row = lambda *a: acts.append(("check_one",)) or True
acts.clear(); POP.clear()
res = wellife.hold_save(hold_rr(), hctx, ONE)
check("물류대기 '1건': 전체선택 대신 첫 줄만 -> 저장",
      ("check_one",) in acts and ("select_all",) not in acts and ("click", "저장(S)") in acts and res[0] == "done"
      and "첫 줄만" in res[1], f"{res} {acts}")
wellife.check_one_row = _saved_chk

_saved_inv1 = wellife.controls, wellife.count_rows, wellife.check_all_rows, wellife.check_one_row
wellife.ensure_query = lambda *a: []
wellife.controls = lambda rr_, ctx_, form: {"btn_Search": El("조회(F)"), "gridCtrl_List": "grid", "btn_SendRequest": send_btn}
wellife.count_rows = lambda rr_, ctx_, grid: INV["rows"]
wellife.check_all_rows = lambda *a: acts.append(("check_all",)) or True
wellife.check_one_row = lambda *a: acts.append(("check_one",)) or True
res = inv_run(ONE, rows=64)
check("⑥ '1건': 조회 -> 첫 줄만 체크 -> 다시 확인(한 줄) -> [전송요청(S)] 누름",
      acts == [("click", "조회(F)"), ("check_one",), ("click", "btn_SendRequest"), ("click", "예")] and res[0] == "done"
      and "64건 중 첫 줄 1건" in res[1], f"{res} {acts}")
wellife.controls, wellife.count_rows, wellife.check_all_rows, wellife.check_one_row = _saved_inv1
wellife.ensure_query = _saved_eq
POP.clear()

# ---------------------------------------------------------------------------
print("=== 14. 조회 조건 기본값 (사용자 10-13·10-14: 반복 화면은 조회 전에 기본값인지 보고 고친다) ===")
import datetime as _dt  # noqa: E402

D14 = _dt.date(2026, 10, 14)
check("날짜 칸 값 -> 오늘부터 일 수", wellife.date_days("2026년 10월 4일 일요일", D14) == -10
      and wellife.date_days("2026-10-15", D14) == 1 and wellife.date_days("", D14) is None
      and wellife.date_days("2026년 13월 1일", D14) is None)
check("체크 상자 안쪽 색 비율 -> 체크(0.551)·안 체크(0.000)·애매(0.15)·못 읽음",
      [wellife.check_state(v) for v in (0.551, 0.0, 0.15, None)] == ["Y", "N", None, None])


def _box(check_px, w=77, h=20, border=(150, 150, 165)):
    """흉내 그림 (BGRA): 흰 바탕, (1,3)~(13,15) 상자 테두리 2점, check_px 는 안쪽에 칠할 점들 (주황)."""
    raw = bytearray([255, 255, 255, 255] * (w * h))
    for y in range(h):
        for x in range(w):
            color = None
            if 1 <= x <= 13 and 3 <= y <= 15 and (x <= 2 or x >= 12 or y <= 4 or y >= 14):
                color = border
            if (x, y) in check_px:
                color = (240, 150, 30)
            if color:
                raw[(y * w + x) * 4:(y * w + x) * 4 + 3] = bytes((color[2], color[1], color[0]))
    return bytes(raw), w, h


_v = {(x, y) for x in range(4, 11) for y in range(6, 13) if abs((x - 4) - (y - 6)) <= 1 or abs((10 - x) - (y - 6)) <= 1}
check("상자 안쪽만 잰다: 테두리(회색·주황)는 세지 않고, 체크(주황 V)는 센다",
      wellife.box_ink(*_box(set())) == 0.0 and wellife.box_ink(*_box(set(), border=(240, 150, 30))) == 0.0
      and wellife.check_state(wellife.box_ink(*_box(_v))) == "Y", str(wellife.box_ink(*_box(_v))))
settings({"QueryDefaults": {"InvoiceSend": {"DateFrom": -30, "Sales": "매출구분 : 쿠팡", "SendStatus": "전체"}}})
qd = {k: w for k, _, _, w in wellife.query_defaults(rr, "InvoiceSend")}
check("설정 QueryDefaults 가 있으면 그 값 ('fixed' 는 늘 전체 - 고치지 않고 화면을 다시 열므로)",
      qd["DateFrom"] == -30 and qd["SendStatus"] == "전체" and qd["Sales"] == "매출구분 : 전체" and qd["DateTo"] == 0, str(qd))
settings({})
check("설정이 없으면 ERPia 를 새로 연 화면 값 (⑥ 10일 전~오늘·미전송, ⑤ 내일~내일·납품예정일)",
      {k: w for k, _, _, w in wellife.query_defaults(rr, "InvoiceSend")}["DateFrom"] == -10
      and {k: w for k, _, _, w in wellife.query_defaults(rr, "Wms")}["DateFrom"] == 1
      and {k: w for k, _, _, w in wellife.query_defaults(rr, "Wms")}["DateBasis"] == "납품예정일")
settings({"QueryDefaults": {"Wms": {"DateFrom": "내일"}}})
try:
    wellife.ensure_query(rr, actx, "Wms", wellife.WMS_FORM, lambda: None)
    res = None
except wellife.Stop as e:
    res = (e.result, str(e))
check("설정 값 모양이 틀리면 조회하지 않고 '설정 오류' 로 멈춘다", res and res[0] == "failed" and "설정 오류" in res[1], str(res))
settings({})


class CondEl:
    def __init__(self, value, kids=()):
        self.value, self.kids = value, list(kids)

    def descendants(self, control_type=None):
        return [k for k in self.kids if control_type is None or k.kind == control_type]


class Kid(CondEl):
    def __init__(self, kind, value, aid=""):
        super().__init__(value)
        self.kind = kind
        self.element_info = types.SimpleNamespace(automation_id=aid)


crr = types.SimpleNamespace(legacy_value=lambda el: el.value)
_empty = CondEl(None)
_empty.iface_value = types.SimpleNamespace(CurrentValue="")            # 빈 글 칸: ValuePattern 은 '', Legacy Value 는 없다
_typed = CondEl(None)
_typed.iface_value = types.SimpleNamespace(CurrentValue="zz")
ctl14 = {"ccc_SendorNot": CondEl("미전송"), "cbo_delivery": CondEl("택배사 : (전체)"), "txt_SearchValue": _empty,
         "txt_typed": _typed, "txt_unread": CondEl(None),                 # iface_value 가 없으면(못 읽음) None
         "ccc_Sales": CondEl(None, [Kid("Edit", "매출구분 : 전체", "popEdit")]),
         "dateFrom": CondEl(None, [Kid("ComboBox", f"{_dt.date.today():%Y}년 {_dt.date.today().month}월 {_dt.date.today().day}일")])}
check("지금 값 읽기: 콤보는 '택배사 : ' 를 떼고, 빈 검색어는 '', 못 읽은 검색어는 None (빈 칸으로 보지 않음), 매출구분은 안쪽 popEdit, 날짜는 오늘부터 일 수",
      [wellife.cond_value(crr, ctl14, a, k) for a, k in (("ccc_SendorNot", "combo"), ("cbo_delivery", "combo"),
                                                         ("txt_SearchValue", "text"), ("txt_typed", "text"),
                                                         ("txt_unread", "text"), ("ccc_Sales", "fixed"),
                                                         ("dateFrom", "date"), ("없음", "combo"))]
      == ["미전송", "(전체)", "", "zz", None, "매출구분 : 전체", 0, None])

# ensure_query 흐름: 값은 STATE, 고치기는 set_cond, 화면 다시 열기는 fixed·체크를 기본값으로 되돌린다
DEF = {aid: want for _, aid, _, want in wellife.query_defaults(rr, "InvoiceSend")}
STATE, LOG14 = {}, []
_saved14 = wellife.controls, wellife.cond_value, wellife.set_cond, wellife.close_screen
wellife.controls = lambda rr_, ctx_, form: {"btn_Close": 1}
wellife.cond_value = lambda rr_, ctl, aid, kind: STATE.get(aid)


def _set(rr_, ctx_, ctl, key, aid, kind, want):
    LOG14.append(("set", key))
    if aid not in STUCK:
        STATE[aid] = want


def _reopen():
    LOG14.append(("reopen",))
    for _, aid, kind, want in wellife.QUERY_CONDITIONS["InvoiceSend"]:
        if kind in ("fixed", "check") and aid not in STUCK:
            STATE[aid] = want


wellife.set_cond = _set
wellife.close_screen = lambda rr_, ctx_, ctl, form: LOG14.append(("close",))
STUCK = set()
qrr = types.SimpleNamespace(log=lambda m: None, pl=rr.pl)


def run14(**changes):
    STATE.clear(); STATE.update(DEF); STATE.update(changes); LOG14.clear()
    try:
        return wellife.ensure_query(qrr, actx, "InvoiceSend", wellife.INVOICE_FORM, _reopen), None
    except wellife.Stop as e:
        return None, (e.result, str(e))


got, err = run14()
check("모두 기본값이면 아무것도 하지 않는다", got == [] and LOG14 == [] and err is None, f"{got} {LOG14}")
got, err = run14(ccc_SendorNot="전체", dateFrom=-30, txt_SearchValue="홍길동")
check("콤보·날짜·검색어가 다르면 그 칸만 기본값으로 고친다 (화면은 다시 열지 않음)",
      LOG14 == [("set", "DateFrom"), ("set", "SendStatus"), ("set", "SearchValue")] and len(got) == 3
      and STATE["ccc_SendorNot"] == "미전송", f"{got} {LOG14}")
got, err = run14(ccc_Delivery="택배사 : 롯데연동 외 36개")
check("택배사 체크 목록이 '전체' 가 아니면 화면을 닫고 다시 연다 (사용자 10-14 - 복잡한 조건)",
      LOG14 == [("close",), ("reopen",)] and got and "화면 다시 열기(Delivery)" in got[0], f"{got} {LOG14}")
got, err = run14(chk_UnstoringStand=None)
check("'출고대기만' 을 못 읽으면(그림이 애매) 화면을 다시 연다", LOG14 == [("close",), ("reopen",)] and err is None, f"{LOG14}")
got, err = run14(chk_UnstoringStand="Y")
check("'출고대기만' 이 켜져 있으면 눌러 끈다 (화면을 다시 열지 않음)", LOG14 == [("set", "UnstoringOnly")], f"{LOG14}")
STUCK = {"ccc_Sales"}
got, err = run14(ccc_Sales="매출구분 : 옥션(zzata)")
check("다시 열어도 '전체' 가 아니면 조회하지 않고 멈춘다", err and err[0] == "failed" and LOG14 == [("close",), ("reopen",)], f"{err} {LOG14}")
STUCK = {"ccc_SendorNot"}
got, err = run14(ccc_SendorNot="전송완료")
check("고쳤는데 다시 읽은 값이 다르면 조회하지 않고 멈춘다", err and err[0] == "failed" and "SendStatus" in err[1], f"{err}")
STUCK = {"chk_UnstoringStand"}
got, err = run14(chk_UnstoringStand="Y")
check("체크 상자를 눌렀는데 그림이 그대로면 (그림을 잘못 읽는 PC) 켠 채 남기지 않게 화면을 다시 열고 멈춘다",
      err and err[0] == "failed" and LOG14 == [("set", "UnstoringOnly"), ("close",), ("reopen",)], f"{err} {LOG14}")
STUCK = set()
wellife.controls, wellife.cond_value, wellife.set_cond, wellife.close_screen = _saved14

# 입력 안전장치 그대로 (가짜로 바꿔 끼우지 않음): 날짜·글 칸은 포커스가 그 칸 안일 때만 키, 목록 항목은 목록 창이 맨 위일 때만
typed = []
_edit = types.SimpleNamespace(kind="Edit", type_keys=lambda keys, **kw: typed.append(keys))
_box14 = types.SimpleNamespace(kind="ComboBox", descendants=lambda control_type=None: [_edit])
_saved_in = wellife.click, wellife.no_popup, wellife._focus_in, wellife._focus_chain
wellife.click = lambda rr_, ctx_, el, what: None
wellife.no_popup = lambda *a: None
wellife._focus_chain = lambda rr_, depth=8: [("x", "Edit", "")]
for focus, want_typed in ((False, []), (True, ["^a2026-10-04{TAB}"])):
    typed.clear()
    wellife._focus_in = lambda rr_, aid, f=focus: f
    _dt_today = wellife.datetime.date
    try:
        wellife.set_cond(types.SimpleNamespace(), actx, {"dateFrom": types.SimpleNamespace(
            descendants=lambda control_type=None: [_box14])}, "DateFrom", "dateFrom", "date",
            (_dt.date(2026, 10, 4) - _dt.date.today()).days)
        res = None
    except wellife.Stop as e:
        res = e.result
    check(f"날짜 칸: 포커스가 {'칸 안이면 ^a → 날짜 → Tab' if focus else '칸 밖이면 키를 보내지 않고 멈춘다'}",
          typed == want_typed and (res is None if focus else res == "failed"), f"{typed} {res}")
wellife.click, wellife.no_popup, wellife._focus_in, wellife._focus_chain = _saved_in

pressed14 = []
_item = types.SimpleNamespace(window_text=lambda: "미전송", rectangle=lambda: Rect(10, 10, 50, 30),
                              click_input=lambda **kw: pressed14.append("미전송"))
_list = types.SimpleNamespace(wrapper_object=lambda: types.SimpleNamespace(descendants=lambda control_type=None: [_item]))
WIN14 = [set()]
_saved_pick = wellife.click, wellife._menu_windows, wellife._top_window, wellife._close_menu, wellife._shown
wellife.click = lambda rr_, ctx_, el, what: WIN14.__setitem__(0, {55})       # 콤보를 누르면 목록 창 55 가 뜬다
wellife._menu_windows = lambda rr_, ctx_: set(WIN14[0])
wellife._close_menu = lambda rr_, ctx_, wins, what: pressed14.append("ESC")
wellife._shown = lambda rr_, h: False
prr = types.SimpleNamespace(Desktop=lambda backend=None: types.SimpleNamespace(window=lambda handle=None: _list),
                            ec=types.SimpleNamespace(screen_locked=lambda: False))
for top, want in ((55, ["미전송", "ESC"]), (99, ["ESC"])):
    WIN14[0] = set(); pressed14.clear()
    wellife._top_window = lambda rr_, pt, t=top: t
    try:
        wellife.pick_item(prr, actx, object(), "미전송", "조회 조건 SendStatus")
        res = None
    except wellife.Stop as e:
        res = e.result
    check(f"목록 항목: 그 자리의 맨 위 창이 {'목록 창이면 누른다' if top == 55 else '다른 창이면 누르지 않고 목록을 닫고 멈춘다'}",
          pressed14 == want and (res is None if top == 55 else res == "failed"), f"{pressed14} {res}")
wellife.click, wellife._menu_windows, wellife._top_window, wellife._close_menu, wellife._shown = _saved_pick

# ⑥·⑤ 에 붙었는가: 조회 전에 ensure_query, 고친 것은 사유에
_saved14 = wellife.ensure_query, wellife.controls, wellife.count_rows, wellife.check_all_rows
calls14 = []
wellife.ensure_query = lambda rr_, ctx_, screen, form, reopen: calls14.append(screen) or ["화면 다시 열기(Sales)"]
wellife.controls = lambda rr_, ctx_, form: {"btn_Search": El("조회(F)"), "gridCtrl_List": "grid", "btn_SendRequest": send_btn}
wellife.count_rows = lambda rr_, ctx_, grid: 0
res = inv_run(False, rows=0)
check("⑥: 조회 전에 조회 조건을 보고, 고친 것을 사유에 남긴다", calls14 == ["InvoiceSend"] and "조회 조건 기본값으로 고침" in res[1], str(res))
calls14.clear()
_saved_wms = wellife.goto_screen_by_menu, wellife.simple_stage
wellife.goto_screen_by_menu = lambda rr_, ctx_, menu: (True, None)
wellife.simple_stage = lambda rr_, ctx_, form, *stage, live=False: (f"{stage[4].split(' →')[0]} 0건", False)
res = wellife.module_wms(types.SimpleNamespace(status=Rec(), log=lambda m: None), actx, False)
check("⑤: 회차마다 단계 단추 전에 조회 조건을 보고, 고친 것을 사유 앞에 (괄호가 잘리지 않게)", calls14 == ["Wms"] and "조회 조건 기본값으로 고침: 화면 다시 열기(Sales) / 5-1" in res[1]
      and res[1].index("조회 조건") < res[1].index("5-1"), str(res))
wellife.goto_screen_by_menu, wellife.simple_stage = _saved_wms
wellife.ensure_query, wellife.controls, wellife.count_rows, wellife.check_all_rows = _saved14
POP.clear()

# ---------------------------------------------------------------------------
print("=== 15. 같은 화면이 여러 개 열림 ('물류대기 관리 (2)', 10-14) ===")
# 실측: 번호 붙은 탭이 있으면 descendants() 가 메인 탭바·좌측 아이콘을 빠뜨린다 (자식을 따라가면 있다).
# 메인 탭바·아이콘은 자식을 따라 찾고, 이미 열린 화면은 번호 없는 탭을 누른다
wellife.main_tab_bar, wellife.wait_tab = _real_tabs


class UI:
    def __init__(self, kind, text="", aid="", rect=None, kids=(), selected=False):
        self.element_info = types.SimpleNamespace(control_type=kind, automation_id=aid)
        self.text, self.rect, self.kids, self.selected = text, rect or Rect(10, 10, 150, 30), list(kids), selected
        self.up = None
        for k in self.kids:
            k.up = self

    def parent(self):
        return self.up

    def children(self, control_type=None):
        return [k for k in self.kids if control_type is None or k.element_info.control_type == control_type]

    def descendants(self, control_type=None):     # 실측처럼 화면에 있는 것을 빠뜨린다 - 쓰이면 시험이 실패한다
        return []

    def rectangle(self):
        return self.rect

    def window_text(self):
        return self.text

    def is_selected(self):
        return self.selected


def erpia(tabs, active, icons=("lcg_OrderCollect", "lcg_HoldLogistics", "lcg_InvoiceSend")):
    """창 > pnlMain > (좌측 아이콘 줄, sdPnlMain > 화면들 + 메인 탭바(Tab) > 탭들, 숨은 화면의 서브탭 Tab)."""
    items = [UI("TabItem", t, rect=Rect(20 + 120 * i, 5, 130 + 120 * i, 25), selected=(t == active)) for i, t in enumerate(tabs)]
    hidden_sub = UI("Tab", rect=Rect(-900, -900, -100, -100), kids=[UI("TabItem", "일반", selected=True)])
    page = UI("Pane", active, kids=[UI("Pane", kids=[UI("Tab", aid="tab_Data", rect=Rect(10, 60, 800, 500),
                                                         kids=[UI("TabItem", "일반", selected=True)])])])
    bar = UI("Tab", active, rect=Rect(0, 0, 1000, 600), kids=items)
    work = UI("Pane", aid="sdPnlMain", kids=[UI("Pane", kids=[UI("Pane", "숨은 화면", rect=Rect(-900, -900, -100, -100), kids=[hidden_sub]),
                                                              page, bar])])
    side = UI("Pane", aid="tbPnl_ProcessBar", kids=[UI("Pane", kids=[UI("Pane", k, rect=Rect(2, 100, 40, 140)) for k in icons])])
    win = UI("Window", rect=Rect(0, 0, 1200, 900), kids=[UI("Pane", aid="pnlMain", kids=[side, work])])
    return types.SimpleNamespace(window=lambda: win, hwnd=1, app=None, bar=bar)


TABS = ["메인페이지", "웰라이프 SAP 연동관리", "물류대기 관리 ", "물류대기 관리 (2)"]
dctx = erpia(TABS, "물류대기 관리 (2)")
bar, items = wellife.main_tab_bar(dctx)
check("메인 탭바: 자식을 따라 얕은 곳부터 - 숨은 화면·떠 있는 화면 안의 서브탭(더 깊다)이 아니라 메인 탭바",
      bar is not None and [t.window_text() for t in items] == TABS, str(bar and bar.window_text()))
check("떠 있는 탭은 메인 탭바에서 (원래 함수가 서브탭 '일반' 을 돌려주던 상태)", wellife.active_tab(dctx) == "물류대기 관리 (2)")
check("번호 붙은 탭만 (이름 끝 공백인 원래 탭은 아님)", wellife.numbered_tabs(dctx) == ["물류대기 관리 (2)"])
check("못 찾은 탭은 실패 사유에 덧붙인다", "물류대기 관리 (2)" in wellife.dup_note(dctx) and wellife.dup_note(erpia(TABS[:3], "메인페이지")) == "")
check("아이콘은 자식을 따라 (화면 영역은 내려가지 않음)", wellife.find_icon(dctx, "lcg_HoldLogistics").window_text() == "lcg_HoldLogistics"
      and wellife.find_icon(dctx, "lcg_Logistics") is None)

clicked, orig_calls = [], []
_saved15 = wellife.click, wellife.TAB_WAIT_SECONDS
wellife.TAB_WAIT_SECONDS = 0.2


def press(rr_, ctx_, el, what):
    """탭을 누르면 그 탭이, 물류대기 아이콘을 누르면 새 '물류대기 관리 ' 탭이 떠 있게."""
    clicked.append(el.window_text())
    name = el.window_text()
    if name == "lcg_HoldLogistics":
        ctx_.bar.kids.append(UI("TabItem", "물류대기 관리 "))
        name = "물류대기 관리 "
    for t in ctx_.bar.kids:
        t.selected = t.window_text() == name


wellife.click = press
grr = types.SimpleNamespace(log=lambda m: None, element_at_point=lambda x, y: None)
wellife._hits_tab = lambda rr_, t, name: True


def go(ctx_, name, icon, r="ok"):
    clicked.clear(); orig_calls.clear()
    return wellife.goto_screen(grr, ctx_, name, icon, lambda: orig_calls.append(name) or r)


dctx = erpia(TABS, "물류대기 관리 (2)")
res = go(dctx, "물류대기 관리", "lcg_HoldLogistics")
check("이미 열린 화면: 번호 붙은 '(2)' 가 떠 있어도 번호 없는 원래 탭을 누른다 (아이콘·원래 함수 안 씀)",
      res == "ok" and clicked == ["물류대기 관리 "] and not orig_calls, f"{res} {clicked} {orig_calls}")
dctx = erpia(["메인페이지", "웰라이프 SAP 연동관리", "웰라이프 SAP 연동관리 (2)"], "웰라이프 SAP 연동관리 (2)")
res = go(dctx, "물류대기 관리", "lcg_HoldLogistics")
check("열려 있지 않은 화면 + 번호 붙은 탭이 있음: 원래 함수(못 찾고 몇 분 기다림) 대신 자식을 따라 찾은 아이콘",
      res == "ok" and clicked == ["lcg_HoldLogistics"] and not orig_calls, f"{res} {clicked} {orig_calls}")
res = go(erpia(["메인페이지"], "메인페이지", icons=()), "물류대기 관리", "lcg_HoldLogistics", r="absent")
check("번호 붙은 탭이 없으면 원래 아이콘 이동 그대로 (원래 결과 'absent' 를 그대로)",
      res == "absent" and orig_calls == ["물류대기 관리"] and not clicked, f"{res} {clicked} {orig_calls}")
res = go(erpia(["메인페이지"], "메인페이지"), "물류대기 관리", "lcg_HoldLogistics", r="failed")
check("원래 함수의 'failed' 는 사유 글로", res == "'물류대기 관리' 화면으로 이동하지 못했습니다.", res)
res = go(erpia(["메인페이지", "웰라이프 SAP 연동관리 (2)", "웰라이프 SAP 연동관리"], "메인페이지", icons=()), "물류대기 관리", "lcg_HoldLogistics")
check("번호 붙은 탭이 있는데 아이콘이 정말 없으면 'absent'", res == "absent" and not clicked and not orig_calls, f"{res} {clicked}")
stuck = erpia(TABS, "물류대기 관리 (2)")
wellife.click = lambda rr_, ctx_, el, what: clicked.append(el.window_text())     # 눌러도 안 바뀐다
res = go(stuck, "물류대기 관리", "lcg_HoldLogistics")
check("탭을 눌렀는데 그 화면이 안 되면 실패 사유 (떠 있는 화면 이름과)", "바뀌지 않았습니다" in res and "(2)" in res, res)
broken = types.SimpleNamespace(window=lambda: (_ for _ in ()).throw(RuntimeError("COMError 흉내")), hwnd=1, app=None)
res = go(broken, "주문매핑 매출처리", "lcg_OrderCollect")
check("탭을 읽다 UIA 오류(로그인 직후 등)면 원래 화면 이동으로", res == "ok" and orig_calls == ["주문매핑 매출처리"], f"{res} {orig_calls}")
wellife.click, wellife.TAB_WAIT_SECONDS = _saved15

# ---------------------------------------------------------------------------
print("=== 16. 창 전체를 훑지 않기 (10-14 리허설 9분 10초 - 화면 7~8개가 열려 요소 약 3,400개, 한 번에 10~14초) ===")
# 팝업 보기: 보이는 자식 창 목록이 마지막 '팝업 없음' 때와 같으면 다시 훑지 않는다 (ERPia 팝업은 자식 창으로 뜬다)
scans, kids15, tops15 = [], [{1: ("a", (0, 0, 9, 9)), 2: ("b", (0, 0, 9, 9))}], [[]]
prr = types.SimpleNamespace(visible_child_windows=lambda h: kids15[0], find_popup_windows=lambda pid, h: tops15[0],
                            find_popup_buttons=lambda win: scans.append(1) or POP15[0], collect_popup_text=lambda b: "팝업 글")
POP15 = [[]]
pctx = types.SimpleNamespace(hwnd=1, pid=5, window=lambda: None)
wellife.no_popup(prr, pctx, "가")
wellife.no_popup(prr, pctx, "나")
check("자식 창이 그대로면 두 번째는 훑지 않는다", len(scans) == 1, str(scans))
tops15[0] = [77]
wellife.no_popup(prr, pctx, "나2")
check("ERPia 가 따로 띄운 창(별도 창 팝업)이 생겨도 다시 훑는다", len(scans) == 2, str(scans))
kids15[0] = {1: ("a", (0, 0, 9, 9)), 2: ("b", (50, 50, 90, 90))}
wellife.no_popup(prr, pctx, "나3")
check("자식 창이 같아도 자리가 바뀌면 다시 훑는다", len(scans) == 3, str(scans))
kids15[0] = {}
wellife.no_popup(prr, pctx, "나4")
wellife.no_popup(prr, pctx, "나5")
check("자식 창 목록이 비면(창이 죽음 - 오류를 삼켜 빈 목록) 늘 훑는다", len(scans) == 5, str(scans))
del scans[1:]
kids15[0] = {1: 0, 2: 0, 3: 0}
POP15[0] = [El("예")]
try:
    wellife.no_popup(prr, pctx, "다")
    stopped = False
except wellife.Stop:
    stopped = True
check("자식 창이 바뀌면(팝업이 뜸) 다시 훑고, 팝업이 있으면 멈춘다", stopped and len(scans) == 2)
try:
    wellife.no_popup(prr, pctx, "라")
    stopped = False
except wellife.Stop:
    stopped = True
check("팝업을 본 뒤에는 자식 창이 같아도 다시 훑는다 (팝업이 남아 있으면 또 멈춤)", stopped and len(scans) == 3)
POP15[0] = []
prr.visible_child_windows = lambda h: (_ for _ in ()).throw(OSError("못 읽음"))
wellife.no_popup(prr, pctx, "마")
wellife.no_popup(prr, pctx, "바")
check("자식 창 목록을 못 읽으면 늘 훑는다", len(scans) == 5, str(scans))

# 화면 컨트롤: 떠 있는 화면 안에서 폼을 자식을 따라 찾고, 그리드(Table) 속 칸은 내려가지 않는다
cell = UI("DataItem", "칸", aid="inner_cell", rect=Rect(60, 200, 100, 220))
form = UI("Pane", aid="Frm_Test", rect=Rect(20, 60, 1100, 800), kids=[
    UI("Button", "조회(F)", aid="btn_Search", rect=Rect(30, 70, 90, 90)),
    UI("Pane", kids=[UI("Button", "", aid="btn_FirstSend", rect=Rect(100, 70, 120, 90)),
                     UI("Button", "", aid="btn_Hidden", rect=Rect(-900, -900, -880, -880))]),
    UI("Table", aid="gridCtrl_List", rect=Rect(30, 150, 1000, 700), kids=[cell])])
cctx = erpia(["메인페이지", "웰라이프 SAP 연동관리"], "웰라이프 SAP 연동관리")
page = wellife.visible_page(cctx)
page.kids.append(form)
check("떠 있는 화면 = 메인 탭바 옆의 창 안 Pane (숨은 화면 아님)", page.window_text() == "웰라이프 SAP 연동관리", page.window_text())
got15 = wellife.controls(rr, cctx, "Frm_Test")
check("폼 안의 보이는 컨트롤만 (창 밖 숨은 단추 빼고), 그리드 칸은 내려가지 않는다",
      set(got15) == {"btn_Search", "btn_FirstSend", "gridCtrl_List"}, str(sorted(got15)))
broken_page = types.SimpleNamespace(window=lambda: UI("Window", rect=Rect(0, 0, 1200, 900)), hwnd=1)
check("메인 탭바를 못 찾으면 떠 있는 화면 대신 창 (예전처럼 전체)", wellife.visible_page(broken_page).element_info.control_type == "Window")

finish()
