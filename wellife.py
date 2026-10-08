"""웰라이프 전용 실행: 로그인 → ② 주문매핑 → ③ 물류대기 → ④ 웰라이프 SAP 연동관리 → ⑤ 웰라이프 WMS 이관관리.

사용자 설정(RPA_UserConfig.json)에 "Wellife" 섹션이 있는 PC 에서만 run_routine.main 이 이리로 온다.
섹션이 없는 PC(다른 업체)는 지금 루틴 그대로 돈다 - ROUTINE_MODULES 와 Routine 섹션은 건드리지 않는다.
    예: {"Wellife": {"Login": "Y", "Sales": "Y", "Hold": "Y", "Sap": "Y", "Wms": "Y",
                     "SalesMode": "리허설", "Mode": "리허설"}}

모드 (사용자 10-08) - 데이터를 바꾸는 단추를 누를지 정한다. 빠지면 리허설.
"SalesMode" 는 ② 주문매핑(엑셀 업로드)만, "Mode" 는 ③ 물류대기 저장·④⑤ 지정·화살표를 정한다.
- "리허설": 데이터를 바꾸는 단추(엑셀 업로드·물류대기 저장·[지정]·화살표)는 누르지 않고 마우스만 올린다.
- "실행": 실제로 누르고, 뜨는 팝업은 [예](없으면 [확인])를 누른다 - [아니오] 가 함께 있어도 [예] (사용자 10-08).
  팝업 문구는 모두 로그와 모듈 사유에 남긴다.
모드는 대시보드 단계 이름·실행 제목·모듈 사유 앞의 [리허설]/[실행] 과 시작 로그로 보인다.
- ② 주문매핑: 미리 둔 엑셀(ERPIA_AI_EXCEL 의 (사이트코드)~.xlsx)이 있을 때만 올린다. 자동 수집 [가져오기] 는
  모드와 상관없이 누르지 않는다 (마우스만). 선택주문 매출처리는 하지 않는다.
- ③ 물류대기: 일반 탭 조회 -> 전체선택 -> 저장 (보류는 하지 않는다).
- ④⑤ 는 단계 조회·대상 고르기·체크 -> [지정]('선택 항목만')·화살표. 체크는 다음 단계를 조회하면 풀려서 되돌리지 않는다.
모듈별 실행: 예약 줄이 모듈을 고르면(RPA_RUN_MODULES, Wellife 키) 그 모듈만 돈다 - ②③④⑤ 를 따로 띄울 수 있다.
⑤ 는 SAP 에서 넘어온 건이 WMS 에 하나씩 들어오므로 반복 시간대(시작~끝, N분 쉬고 다시)로 돌린다 (docs/wellife-rpa.md 7절).

run_routine 을 import 하지 않는다. exe 에서 run_routine 은 __main__ 이라 다시 import 하면 사본이 하나 더 생기고,
그 사본이 결과 로그를 'w' 로 다시 열어 지운다. 그래서 run_routine 이 자기 모듈(rr)을 넘겨준다.
"""
import os
import re
import time

from pywinauto import mouse

SECTION = "Wellife"
SAP_MENU = "웰라이프 SAP 연동관리"
WMS_MENU = "웰라이프 WMS 이관관리"
SAP_FORM = "Frm_Wellife_GetSend_SAP"     # 두 화면이 같은 auto_id(btn_FirstSend·cbo_stage·gridCtrl_List…)를 쓰므로
WMS_FORM = "Frm_Wellife_GetSend_WMS"     # 컨트롤은 늘 그 화면(폼) 안에서 찾는다
CHECK_COL = "row Check Box"              # 그리드 체크 칸·머리글 이름 (SAP·WMS 같음, 10-07 실측)
MENU_WAIT_SECONDS = 15      # 메뉴 검색 뒤 걸러진 트리에 항목이 나타나기를 기다리는 최대 시간
MENU_POLL_SECONDS = 0.5
STAGE_WAIT_SECONDS = 30     # 단계 단추를 누른 뒤 cbo_stage 가 그 단계가 되기를 기다리는 최대 시간
CHECK_WAIT_SECONDS = 3      # 체크 칸을 누른 뒤 값이 바뀌기를 기다리는 최대 시간
HOVER_SECONDS = 1.5         # 리허설: 누를 자리에 마우스를 올려 두는 시간 (사람이 화면으로 보게 - 조건 대기 아님)
DROPDOWN_WAIT_SECONDS = 5   # [지정▼] 를 누른 뒤 내림 메뉴가 뜨기(또는 ESC 뒤 닫히기)를 기다리는 최대 시간
SELECTED_ONLY = "선택 항목만"   # [지정▼] 내림 메뉴 항목
MAX_PAGES = 200             # 그리드를 넘기는 최대 페이지 (끝을 못 알아챌 때의 안전장치)
PAGE_WAIT_SECONDS = 5       # 페이지를 넘긴 뒤 그리드가 다 그려지기를 기다리는 최대 시간
QUERY_WAIT_SECONDS = 120    # 물류대기 조회가 끝나기를 기다리는 최대 시간
CONFIRM_WAIT_SECONDS = 600  # 실행: 누른 뒤 처리(스피너·팝업)가 끝나기를 기다리는 최대 시간
QUIET_SECONDS = 5           # 실행: 팝업도 스피너도 이만큼 없으면 처리가 끝난 것으로 본다
MAX_POPUPS = 10             # 실행: 한 번 누른 뒤 이보다 많이 뜨면 멈춘다 (같은 팝업이 되풀이되는 경우)
MODE_KEY = "Mode"              # ③ 물류대기 저장·④ 지정·화살표·⑤ 화살표
SALES_MODE_KEY = "SalesMode"   # ② 주문매핑 엑셀 업로드 - 따로 정한다 (사용자 10-08)
MODES = {"리허설": False, "실행": True}   # 설정 값 -> 실제로 누르는가
YES_TEXTS = ("예(Y)", "예")
OK_TEXTS = ("확인(O)", "확인")

# 대시보드 단계 (rpa_status.step 키, 화면 이름). 순서가 곧 진행 순서다. 실행할 때 이름 앞에 [모드] 를 붙인다
STEPS = (
    ("login", "ERPia 로그인"),
    ("wl_order_screen", "주문매핑 화면 이동"),
    ("wl_order_collect", "주문 수집 (엑셀 / 자동)"),
    ("wl_hold_screen", "물류대기 화면 이동"),
    ("wl_hold_save", "물류대기 조회 → 전체선택 → 저장"),
    ("wl_sap_screen", "웰라이프 SAP 연동관리 화면 열기"),
    ("wl_sap_slip", "4-1 매출전표 지정 → 4-2 넘기기"),
    ("wl_sap_shipping", "4-3 선분할 배송정보"),
    ("wl_sap_so", "4-4 SO생성"),
    ("wl_wms_screen", "웰라이프 WMS 이관관리 화면 열기"),
    ("wl_wms_so", "5-1 S/O매출"),
    ("wl_wms_prepack", "5-2 프리패키징"),
    ("wl_wms_invoice", "5-3 송장O"),
    ("wl_wms_api", "5-4 API대기"),
)
# run_routine.ROUTINE_MODULES 와 같은 모양 (모듈 키, 설정 키, 이름, 단계, module_flags 비트). 비트 32 부터는 웰라이프
MODULES = (
    ("login", "Login", "로그인", ("login",), 1),
    ("wellife_sales", "Sales", "웰라이프 주문매핑", ("wl_order_screen", "wl_order_collect"), 32),
    ("wellife_hold", "Hold", "웰라이프 물류대기", ("wl_hold_screen", "wl_hold_save"), 64),
    ("wellife_sap", "Sap", "웰라이프 SAP 연동관리", ("wl_sap_screen", "wl_sap_slip", "wl_sap_shipping", "wl_sap_so"), 128),
    ("wellife_wms", "Wms", "웰라이프 WMS 이관관리",
     ("wl_wms_screen", "wl_wms_so", "wl_wms_prepack", "wl_wms_invoice", "wl_wms_api"), 256),
)
# 단계 표 (단계 키, 대시보드 단추, 화살표, 머리글로 전체 체크하는가, 화살표가 하는 일). SAP전송전체 이후와
# 송장X·API실패·WMS작업중·할당·출고완료·결품관리는 사람이 보는 화면이라 넣지 않는다 (docs/wellife-rpa.md 2절)
SAP_SIMPLE_STAGES = (
    ("wl_sap_shipping", "dashBtn_ShippingInfo", "btn_SecondSend", True, "4-3 선분할 배송정보 → S/O 생성요청"),
    ("wl_sap_so", "dashBtn_Create_SO", "btn_ThirdSend", False, "4-4 SO생성 → SAP 전송"),
)
WMS_STAGES = (
    ("wl_wms_so", "dashBtn_SO_Sales", "btn_FirstSend", True, "5-1 S/O매출 → 프리패킹 이관"),
    ("wl_wms_prepack", "dashBtn_PrePackaging", "btn_SecondSend", True, "5-2 프리패키징 → 배송장 생성"),
    ("wl_wms_invoice", "dashBtn_Invoice_Success", "btn_ThirdSend", True, "5-3 송장O → API 대기"),
    ("wl_wms_api", "dashBtn_API_Wait", "btn_FourthSend", False, "5-4 API대기 → API 전송"),
)


class Stop(Exception):
    """이 화면 처리를 멈춘다. result: 'failed'(화면·컨트롤 문제) | 'stopped'(모르는 팝업 등 - 누르지 않고 멈춤)."""

    def __init__(self, result, reason):
        super().__init__(reason)
        self.result = result


def enabled(rr):
    """이 PC 설정에 "Wellife" 섹션이 있는가. 설정을 못 읽으면 False - 그 오류는 기존 main 이 그대로 알린다.
    값으로 잘못 쓴 것({"Wellife": "Y"})은 LogIn 에 섞여 들어가므로(rpa_status._sections) 거기도 본다
    (그러면 load_switches 가 '섹션이어야 합니다' 로 멈춘다 - 일반 루틴으로 새지 않게).
    읽기는 세 번까지 해 본다 - 잠깐 못 읽은 웰라이프 PC 가 일반 루틴(빠진 키는 켬)으로 새지 않게."""
    for attempt in range(3):
        try:
            settings = rr.pl.load_settings()
            break
        except Exception:
            if attempt == 2:
                return False
            time.sleep(0.5)
    login = settings.get(rr.pl.LOGIN_SECTION)
    return SECTION in settings or (isinstance(login, dict) and SECTION in login)


def load_switches(rr):
    """({설정 키: True/False}, 모르는 키 목록). 적힌 "Y" 만 켬이고 빠진 키는 끔이다 - Routine 섹션과 반대.
    웰라이프 PC 에만 넣는 섹션이라, 잘못 들어간 빈 섹션이 매출처리·저장을 켜지 않게 한다.
    Y/N 이 아닌 값은 RuntimeError (고치기 전에는 아무것도 돌리지 않는다)."""
    section = rr.pl.load_settings().get(SECTION)
    if not isinstance(section, dict):
        raise RuntimeError(f"{rr.pl.config_name()} 의 '{SECTION}' 은 값이 아니라 섹션이어야 합니다. "
                           f'예: {{"{SECTION}": {{"Login": "Y", "Sales": "Y", "Hold": "Y", "Sap": "Y", "Wms": "Y"}}}}')
    keys = [m[1] for m in MODULES]
    selected, bad = {}, []
    for key in keys:
        raw = section.get(key, "N")
        value = str(raw).strip().upper()
        if value not in ("Y", "N"):
            bad.append(f"{key}={raw!r}")
        selected[key] = value == "Y"
    if bad:
        raise RuntimeError(
            f"{rr.pl.config_name()} 의 '{SECTION}' 섹션 값은 Y 또는 N 이어야 합니다: {', '.join(bad)}")
    return selected, sorted(k for k in section if k not in keys and k not in (MODE_KEY, SALES_MODE_KEY))


def load_mode(rr, key=MODE_KEY):
    """True 면 실행(데이터를 바꾸는 단추를 실제로 누름), False 면 리허설. 빠지면 리허설 - 잘 모르면 누르지 않는 쪽.
    key: MODE_KEY(③④⑤) 또는 SALES_MODE_KEY(② 주문매핑 - 따로 정한다, 사용자 10-08. 빠지면 Mode 를 따르지 않고 리허설).
    "리허설"/"실행" 이 아닌 값은 RuntimeError (load_switches 뒤에 부른다 - 섹션 모양은 거기서 본다)."""
    raw = rr.pl.load_settings()[SECTION].get(key, "리허설")
    value = str(raw).strip()
    if value not in MODES:
        raise RuntimeError(f"{rr.pl.config_name()} 의 '{SECTION}' 섹션 {key} 값은 "
                           f"{' 또는 '.join(repr(m) for m in MODES)} 이어야 합니다: {raw!r}")
    return MODES[value]


def mode_tag(live):
    return "실행" if live else "리허설"


def run_main(rr):
    """웰라이프 본 실행. run_routine.main 이 부른다. 기록은 지금 루틴과 같은 program "routine" 으로 남는다
    (실행 잠금·웹 현황·이력·토큰이 지금 규칙 그대로 동작한다)."""
    status, log = rr.status, rr.log
    try:
        selected, unknown = load_switches(rr)
        live, sales_live, error = load_mode(rr), load_mode(rr, SALES_MODE_KEY), None
    except Exception as e:
        live, sales_live, error = False, False, e
    # 예약 줄이 모듈을 골라 띄웠으면(반복 시간대 포함) 섹션의 켬·끔 대신 그 모듈만 - 지금 루틴과 같은 규칙. 모드는 섹션 그대로
    picked, picked_unknown = rr.run_modules_from_env([m[1] for m in MODULES])
    if not error and picked is not None:
        selected, unknown = picked, []
    tag, sales_tag = mode_tag(live), mode_tag(sales_live)
    # 모드는 단계 이름 앞에 붙여 대시보드·웹(진행 중 단계 이름 포함)에 늘 보이게 한다. ② 단계는 SalesMode 를 붙인다
    sales_steps = next(m[3] for m in MODULES if m[0] == "wellife_sales")
    steps = STEPS if error else tuple(
        (k, f"[{sales_tag if k in sales_steps else tag}] {label}") for k, label in STEPS)
    status.start("routine", steps, title="웰라이프 실행" if error else f"웰라이프 실행 [주문매핑 {sales_tag} / 그 밖 {tag}]")
    status.set_modules([(k, label, steps_, bit) for k, _, label, steps_, bit in MODULES])
    log(f"=== 웰라이프 실행 시작 {time.strftime('%Y-%m-%d %H:%M:%S')} ===")

    account = status.read_account()
    if account and (account.get("admin_code") or account.get("user_id")):
        status.account(account.get("admin_code"), account.get("user_id"))

    if error:
        log(f"설정 오류: {error}")
        status.finish("stopped", f"설정 파일 오류: {error}")
        log(f"=== 웰라이프 실행 종료 {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
        return
    log("*" * 70)
    log(f"*  ② 주문매핑 모드({SALES_MODE_KEY}): [{sales_tag}] - " + (
        "미리 둔 엑셀을 실제로 업로드" if sales_live else "엑셀 업로드는 누르지 않고 마우스만"))
    log(f"*  ③④⑤ 모드({MODE_KEY}): [{tag}] - " + (
        "저장·지정·화살표를 실제로 누르고, 팝업은 [예]/[확인]" if live else "저장·지정·화살표는 누르지 않고 마우스만"))
    log("*" * 70)
    for k in unknown:
        log(f"경고: '{SECTION}' 섹션의 '{k}' 는 모르는 키라 무시합니다.")
    if picked is not None:
        for k in picked_unknown:
            log(f"경고: 예약에서 넘긴 '{k}' 는 모르는 모듈이라 무시합니다.")
        if not any(selected.values()):
            log("이번 실행 모듈이 비었습니다 (예약에서 넘긴 값)")
            status.finish("stopped", "이번 실행 모듈이 비었습니다")
            log(f"=== 웰라이프 실행 종료 {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
            return
        log("이번 실행 모듈 (예약): " + " / ".join(label for _, cfg, label, _, _ in MODULES if selected[cfg]))
    else:
        log("실행할 모듈: " + " / ".join(
            f"{label} {'켬' if selected[cfg] else '끔'}" for _, cfg, label, _, _ in MODULES))
    if rr.ec.screen_locked():   # 잠긴 화면에서는 클릭이 헛돌아 엉뚱한 실패가 난다 (10-07 실측)
        log("윈도우 화면이 잠겨 있어 실행하지 않았습니다.")
        # 반복 회차는 PC 가 이 회차만 건너뛰고 쉬는 시간 뒤 다시 띄운다 - 잠긴 동안 회차마다 이력이 쌓이지 않게 (사용자 10-08)
        status.finish("stopped", "윈도우 화면이 잠겨 있어 실행하지 않았습니다 (화면을 풀고 다시 실행)",
                      record=os.environ.get("RPA_RUN_TRIGGER") != "repeat")
        log(f"=== 웰라이프 실행 종료 {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
        return
    pids = rr.ec.erpia_pids()
    if len(pids) > 1:   # 어느 ERPia 에 붙을지 몰라 다른 세션을 조작할 수 있다 (10-07: 다른 계정 ERPia 가 함께 떠 있었다)
        log(f"ERPia 가 {len(pids)}개 떠 있어 실행하지 않았습니다: {pids}")
        status.finish("stopped", f"ERPia 가 {len(pids)}개 떠 있어 실행하지 않았습니다 (하나만 남기거나 모두 닫고 다시 실행)")
        log(f"=== 웰라이프 실행 종료 {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
        return

    funcs = {"login": rr.module_login,
             "wellife_sales": lambda ctx: module_sales(rr, ctx, sales_live),
             "wellife_hold": lambda ctx: module_hold(rr, ctx, live),
             "wellife_sap": lambda ctx: module_sap(rr, ctx, live),
             "wellife_wms": lambda ctx: module_wms(rr, ctx, live)}
    result, reason = rr.run_modules(selected, MODULES, funcs, SECTION)
    # 반복 회차(⑤ 를 시간대 동안 N분마다)는 처리한 것이 없으면 이력에 남기지 않는다 - 지금 루틴 main 과 같은 규칙
    if os.environ.get("RPA_RUN_TRIGGER") == "repeat" and result == "success" \
            and not [k for k in (status.done_modules() or []) if k != "login"]:
        log("반복 회차 - 처리한 것이 없어 기록에 남기지 않습니다")
        status.finish(result, reason, record=False)
    else:
        status.finish(result, reason)
    log(f"=== 웰라이프 실행 종료 {time.strftime('%Y-%m-%d %H:%M:%S')} "
        f"({'성공' if result == 'success' else '중단'}) ===")


# ---------------------------------------------------------------------------
# 모듈. run_routine 의 모듈 함수와 같이 (결과, 사유) 를 돌려준다. 사유 앞에는 [모드] 를 붙인다.
# 실제로 누른 것이 있으면 "done", 리허설·할 것 없음은 "skipped"(토큰 0).
# ---------------------------------------------------------------------------

def module_sales(rr, ctx, live=False):
    """② 주문매핑: 화면 이동 -> 주문 수집 (collect_orders). 선택주문 매출처리는 하지 않는다 (사용자 10-08 범위 밖)."""
    rr.status.step("wl_order_screen")
    try:
        front(rr, ctx, "주문매핑 화면 이동")
    except Stop as e:
        return e.result, str(e)
    ok, reason = rr.goto_order_screen(ctx)
    if not ok:
        return "failed", reason
    try:
        return collect_orders(rr, ctx, live)
    except Stop as e:
        return e.result, str(e)
    except Exception as e:
        return ui_error(rr, e)


def collect_orders(rr, ctx, live):
    """주문 수집 (사용자 10-08).
    - 엑셀: 미리 둔 파일(ERPIA_AI_EXCEL 의 (사이트코드)~.xlsx)이 있을 때만 기존 run_excel_upload_step 으로 올린다
      (끝난 파일은 완료/날짜, 못 올린 파일은 오류 폴더로 옮겨진다). 리허설이면 올리지 않고 첫 사이트의 업로드 칸에 마우스만.
    - 자동 수집 [가져오기] 는 모드와 상관없이 누르지 않는다 - 마우스만."""
    rr.status.step("wl_order_collect")
    win = ctx.window()
    files = excel_files(rr)
    notes, uploaded = [], 0
    if not files:
        notes.append("엑셀: 올릴 파일 없음")
    else:
        tables = rr.get_onscreen_tables(win)
        if not tables:
            raise Stop("failed", "주문매핑 사이트 그리드를 찾지 못했습니다.")
        sites = min(tables, key=lambda t: (t.rectangle().top, t.rectangle().left))
        names = ", ".join(sorted(files))
        if live:
            no_popup(rr, ctx, "엑셀 업로드 전")
            front(rr, ctx, "엑셀 업로드")
            rr.log(f"  [실행] 엑셀 업로드: 사이트 {names}")
            uploaded, errors = rr.run_excel_upload_step(ctx.app, ctx.pid, ctx.hwnd, sites)
            notes.append(f"엑셀 {len(files)}건 중 {uploaded}건 업로드"
                         + (f", {errors}건은 오류 폴더로 (확인할 것)" if errors else ""))
        else:
            code = sorted(files)[0]
            cell, _ = rr.find_site_upload_cell(ctx.hwnd, sites, code)
            if cell is not None:
                hover(rr, ctx, cell, f"엑셀 업로드 칸 (사이트 {code})", True)
            notes.append(f"엑셀 {len(files)}건 있음 (사이트 {names}) - 올리지 않음")
    imp = onscreen_button(win, rr.IMPORT_BUTTON_NAME)
    if imp is None:
        notes.append("자동 수집 단추 없음")
    else:
        hover(rr, ctx, imp, f"자동 수집 [{rr.IMPORT_BUTTON_NAME}] (모드와 상관없이 누르지 않음)", None)
        notes.append("자동 수집은 누르지 않음")
    return ("done" if uploaded else "skipped"), f"[{mode_tag(live)}] " + " / ".join(notes)


def excel_files(rr):
    """미리 둔 엑셀 {사이트코드: 경로} - 기존 업로드와 같은 폴더·이름 규칙. 폴더가 없으면 {}."""
    folder = rr.excel_upload_dir()
    if not os.path.isdir(folder):
        return {}
    return rr.collect_upload_files(folder)[0]


def module_hold(rr, ctx, live=False):
    """③ 물류대기: 화면 이동 -> 일반 탭 조회 -> 전체선택 -> 저장 (hold_save). 보류는 하지 않는다.
    웰라이프는 물류대기가 꼭 있어야 하므로 아이콘이 없어도(absent) 건너뛰지 않고 실패다 (기존 module_hold 와 다름)."""
    rr.status.step("wl_hold_screen")
    try:
        front(rr, ctx, "물류대기 화면 이동")
    except Stop as e:
        return e.result, str(e)
    r = rr.goto_hold_screen(ctx)
    if r == "absent":
        return "failed", "물류대기 아이콘(lcg_HoldLogistics)이 없습니다 - 이 ERPia 의 화면 구성을 확인하세요."
    if r != "ok":
        return "failed", "물류대기 화면으로 이동하지 못했습니다."
    try:
        return hold_save(rr, ctx, live)
    except Stop as e:
        return e.result, str(e)
    except Exception as e:
        return ui_error(rr, e)


def hold_save(rr, ctx, live):
    """일반 탭 '조회(F)' -> 머리글로 전체선택 -> '저장(S)'. 기존 run_hold_save 는 예/아니오 팝업에 [아니오] 를 누르는
    도우미를 거쳐서 쓰지 않는다 (웰라이프는 [예] - 사용자 10-08). 0건이면 저장하지 않는다."""
    rr.status.step("wl_hold_save")
    tag = mode_tag(live)
    front(rr, ctx, "물류대기 일반 탭")
    rr.click_subtab(ctx.app, ctx.hwnd, rr.STOCK_GENERAL_TAB_NAME)
    win = ctx.window()
    query, tables = onscreen_button(win, "조회(F)"), rr.get_onscreen_tables(win)
    if query is None or not tables:
        raise Stop("failed", "물류대기 '조회(F)' 단추나 그리드를 찾지 못했습니다.")
    grid = max(tables, key=lambda t: t.rectangle().width() * t.rectangle().height())
    idle = rr.grid_overlay_count(ctx.hwnd, grid)
    no_popup(rr, ctx, "물류대기 조회 전")
    click(rr, ctx, query, "물류대기 '조회(F)'")
    time.sleep(2)     # 스피너가 뜨기 전에 '끝' 으로 보지 않게 (기존 일반 탭 조회와 같다)
    if not rr.wait_grid_spinner_gone(ctx.hwnd, grid, idle, label="물류대기", max_wait=QUERY_WAIT_SECONDS):
        raise Stop("failed", f"물류대기 조회가 {QUERY_WAIT_SECONDS}초 안에 끝나지 않았습니다.")
    no_popup(rr, ctx, "물류대기 조회")
    if not grid.descendants(control_type="DataItem"):
        rr.log("  물류대기 0건 - 저장하지 않음")
        return "no_target", f"[{tag}] 물류대기 0건 - 저장할 것 없음"
    front(rr, ctx, "물류대기 전체선택")
    if not rr.select_all_by_header_checkbox(ctx.hwnd, grid):
        raise Stop("failed", "물류대기 전체선택(머리글 체크)에 실패했습니다.")
    no_popup(rr, ctx, "물류대기 전체선택")
    save = onscreen_button(ctx.window(), "저장(S)")
    if save is None:
        raise Stop("failed", "물류대기 '저장(S)' 단추를 찾지 못했습니다.")
    if not live:
        hover(rr, ctx, save, "물류대기 '저장(S)'", True)
        return "skipped", f"[{tag}] 물류대기 조회 -> 전체선택 (저장은 누르지 않음)"
    before = popup_windows(rr, ctx)
    rr.log("  [실행] 물류대기 '저장(S)' 누름")
    click(rr, ctx, save, "물류대기 '저장(S)'")
    texts = confirm_popups(rr, ctx, "물류대기 저장", grid, idle, before)
    return "done", f"[{tag}] 물류대기 조회 -> 전체선택 -> 저장" + popup_note(texts)


def module_sap(rr, ctx, live=False):
    """④ 웰라이프 SAP 연동관리 (docs/wellife-rpa.md 2절 4-1·4-2·4-3·4-4). 리허설이면 지정·화살표는 마우스만."""
    rr.status.step("wl_sap_screen")
    ok, reason = goto_screen_by_menu(rr, ctx, SAP_MENU)
    if not ok:
        return "failed", reason
    try:
        rr.status.step("wl_sap_slip")
        done = [sales_slip_stage(rr, ctx, live)]
        for stage in SAP_SIMPLE_STAGES:
            done.append(simple_stage(rr, ctx, SAP_FORM, *stage, live=live))
    except Stop as e:
        return e.result, str(e)
    except Exception as e:
        return ui_error(rr, e)
    return stage_result(live, done)


def module_wms(rr, ctx, live=False):
    """⑤ 웰라이프 WMS 이관관리 (docs/wellife-rpa.md 2절 5-1~5-4). 리허설이면 화살표는 마우스만."""
    rr.status.step("wl_wms_screen")
    ok, reason = goto_screen_by_menu(rr, ctx, WMS_MENU)
    if not ok:
        return "failed", reason
    try:
        done = [simple_stage(rr, ctx, WMS_FORM, *stage, live=live) for stage in WMS_STAGES]
    except Stop as e:
        return e.result, str(e)
    except Exception as e:
        return ui_error(rr, e)
    return stage_result(live, done)


def stage_result(live, done):
    """[(사유, 눌렀는가)] -> (결과, 사유). 하나라도 실제로 눌렀으면 done."""
    head = f"[{mode_tag(live)}] " + ("" if live else "누르지 않음: ")
    return ("done" if any(p for _, p in done) else "skipped"), head + " / ".join(n for n, _ in done)


def ui_error(rr, e):
    """Stop 이 아닌 예외(UIA COMError 등) - 실행 전체를 죽이지 않고 이 화면의 실패로 남긴다. 키·클릭은 더 하지 않는다
    (run_modules 가 failed 에서 뒤 모듈을 멈춘다)."""
    rr.log(f"  UI 오류: {type(e).__name__}: {e}")
    return "failed", f"UI 오류: {type(e).__name__}"


SLIP_SEND = "4-2 매출전표 → 넘기기"


def sales_slip_stage(rr, ctx, live=False):
    """4-1 매출전표 지정 -> 4-2 넘기기 (사용자 10-08). (사유 한 줄, 눌렀는가).
    머리글로 전체 체크 -> [지정] 옆 ▼ '선택 항목만' (납품예정일은 기본값 그대로) -> 검토 칸이 빈 줄만 체크 -> 화살표(btn_FirstSend).
    리허설은 '선택 항목만'·화살표에 마우스만 (전체 체크가 안 됐어도 자리를 보여 주려고 메뉴는 연다 - 여는 것은 데이터를 바꾸지 않는다).
    실행은 전체 체크가 됐을 때만 지정을 누르고, 지정을 눌렀고 모든 줄의 체크를 맞췄을 때만 화살표를 누른다
    (못 맞춘 줄이 있으면 검토에 문제가 있는 전표가 넘어갈 수 있다)."""
    count, ctl = open_stage(rr, ctx, SAP_FORM, "dashBtn_SalesSlip")
    if not count:
        return "4-1 매출전표 0건", False
    checked = check_all_rows(rr, ctx, ctl["gridCtrl_List"], "4-1 매출전표")
    head = f"매출전표 {count}건"
    if not live:
        head += hover_menu_item(rr, ctx, ctl.get("btn_CopyInsert"), SELECTED_ONLY, "4-1 [지정▼]", checked)
        pressed = False
    elif not checked:
        return head + " - 전체 체크가 안 돼 지정하지 않음 (확인할 것)", False
    else:
        note, pressed = press_menu_item(rr, ctx, ctl.get("btn_CopyInsert"), SELECTED_ONLY, "4-1 [지정▼]",
                                        ctl.get("gridCtrl_List"))
        head += note
        if not pressed:
            return head, False
        ctl = controls(rr, ctx, SAP_FORM)    # 지정 뒤 그리드가 다시 그려진다 - 컨트롤을 새로 잡는다
    marks, bad = mark_rows(rr, ctx, ctl["gridCtrl_List"], count, slip_target)
    targets = sum(1 for v in marks.values() if v == "선택")
    rr.log(f"  매출전표: 그리드 {len(marks)}줄 - 넘길 줄(검토 빈 칸) {targets}줄{f', 못 맞춘 줄 {len(bad)}' if bad else ''}")
    rr.status.note(f"매출전표 {count}건 / {len(marks)}줄 - 넘길 줄 {targets}")
    head += f" / 넘길 줄 {targets}" + (f" (못 맞춘 줄 {len(bad)} - 넘기지 않음)" if bad else "")
    note, sent = press_arrow(rr, ctx, ctl, "btn_FirstSend", SLIP_SEND, bool(targets) and not bad, targets, live)
    return head + note, pressed or sent


def simple_stage(rr, ctx, form_id, step, dash_id, arrow_id, check_all, what, live=False):
    """단계 하나: 조회 -> (건수가 있으면) 머리글로 전체 체크 -> 화살표. (사유 한 줄, 눌렀는가).
    리허설은 화살표에 마우스만. 실행은 대상이 있고(체크 칸이 있는 단계는 전체 체크가 됐고) 단추가 켜져 있을 때만 누른다.
    체크는 다음 단계를 조회하면 풀리므로 되돌리지 않는다."""
    rr.status.step(step)
    count, ctl = open_stage(rr, ctx, form_id, dash_id)
    label = what.split(" →")[0]
    checked = bool(count and check_all) and check_all_rows(rr, ctx, ctl["gridCtrl_List"], label)
    want = bool(count) and (checked or not check_all)
    note, pressed = press_arrow(rr, ctx, ctl, arrow_id, what, want, count, live)
    return f"{label} {count}건" + note, pressed


def check_all_rows(rr, ctx, grid, label):
    """머리글 체크 칸으로 그리드 전체 체크. 됐는가."""
    header = check_header(grid, label)
    no_popup(rr, ctx, f"{label} 전체 체크 전")
    front(rr, ctx, f"{label} 전체 체크")
    clear_point(rr, ctx, header, f"{label} 머리글 체크 칸")   # 머리글 클릭은 rr 도우미가 한다 - 자리만 여기서 본다
    checked = rr.select_all_by_header_checkbox(ctx.hwnd, grid)
    no_popup(rr, ctx, f"{label} 전체 체크")
    if not checked:
        rr.log(f"  확인할 것: {label} - 머리글로 전체 체크하지 못했습니다")
    return checked


def check_header(grid, label="그리드"):
    """그리드 체크 칸 머리글. 없으면 멈춘다."""
    header = next((h for h in grid.descendants(control_type="Header") if h.window_text() == CHECK_COL), None)
    if header is None:
        raise Stop("failed", f"{label}: 그리드 체크 칸 머리글('{CHECK_COL}')을 찾지 못했습니다.")
    return header


def press_arrow(rr, ctx, ctl, arrow_id, what, want, count, live):
    """화살표. 리허설은 마우스만. 실행은 want 이고 단추가 켜져 있을 때만 누르고 팝업을 [예]/[확인] 으로 넘긴다.
    (사유에 덧붙일 글, 눌렀는가)."""
    arrow = ctl.get(arrow_id)
    if not live:
        hover(rr, ctx, arrow, what, want)
        return "", False
    if not want:
        rr.log(f"  [실행] {what}: 누를 대상이 없어 누르지 않음 ({count}건)")
        return "", False
    if arrow is None:
        raise Stop("failed", f"{what} 단추({arrow_id})를 찾지 못했습니다.")
    if not arrow.is_enabled():
        rr.log(f"  확인할 것: {what} - 대상이 있는데 단추가 꺼져 있어 누르지 않음")
        return " (단추 꺼짐 - 확인할 것)", False
    grid = ctl.get("gridCtrl_List")
    idle = rr.grid_overlay_count(ctx.hwnd, grid) if grid is not None else 0
    no_popup(rr, ctx, f"{what} 누르기 전")
    before = popup_windows(rr, ctx)
    rr.log(f"  [실행] {what}: 누름 ({count}건)")
    click(rr, ctx, arrow, what)
    texts = confirm_popups(rr, ctx, what, grid, idle, before)
    return " -> 누름" + popup_note(texts), True


# ---------------------------------------------------------------------------
# 연동·이관 화면 도구 (SAP·WMS 공용)
# ---------------------------------------------------------------------------

def stage_name(value):
    """cbo_stage 값 '단계 : 선분할' -> '선분할'."""
    return (value or "").split(":", 1)[-1].strip()


def same_stage(name, label):
    """콤보의 단계 이름과 대시보드 단추 이름이 같은 단계인가. 콤보는 줄인 이름일 수 있다
    (10-07 실측: 단추 '선분할 배송정보' -> 콤보 '선분할'). 띄어쓰기·'/' 는 빼고 한쪽이 다른 쪽으로 시작하는지 본다."""
    a, b = (re.sub(r"[\s/]", "", x or "") for x in (name, label))
    return bool(a and b) and (a.startswith(b) or b.startswith(a))


def stage_count(text):
    """대시보드 단추 이름 '매출전표\\r\\n(199)' -> 199. 건수가 없으면 None."""
    m = re.search(r"\((\d+)\)\s*$", text or "")
    return int(m.group(1)) if m else None


def review_tokens(value):
    """검토 칸 '예정일X/택배X/거래처X' -> ['예정일X', '택배X', '거래처X']. 빈 칸이면 []."""
    return [t.strip() for t in (value or "").split("/") if t.strip()]


def slip_target(value):
    """검토 칸 값 -> 4-2 로 넘길 줄인가: 빈 칸만 (사용자 10-08). 못 읽은 값(None)은 아니다 - 문제 있는 전표가 넘어가지 않게."""
    return value is not None and not review_tokens(value)


def controls(rr, ctx, form_id):
    """그 화면(폼) 안의, 지금 창 안에 보이는 컨트롤 {auto_id: 요소}. 숨은 화면은 창 밖 좌표라 걸러진다
    (창이 왼쪽 모니터에 있으면 좌표가 음수다 - 그래서 늘 '지금의 창 사각형' 과 견준다).
    단계마다 보이는 단추가 달라서(지정·건식상품 제외) 단계를 연 뒤 다시 부른다."""
    win = ctx.window()
    wr = win.rectangle()

    def shown(c):
        r = c.rectangle()
        return r.width() > 0 and r.height() > 0 and wr.left <= r.left < wr.right and wr.top <= r.top < wr.bottom

    form = None
    for c in win.descendants(control_type="Pane"):
        try:
            if c.element_info.automation_id == form_id and shown(c):
                form = c
                break
        except Exception:
            continue
    if form is None:
        raise Stop("failed", f"화면({form_id})을 찾지 못했습니다.")
    out = {}
    for c in form.descendants():
        try:
            aid = c.element_info.automation_id
            if aid and aid not in out and shown(c):
                out[aid] = c
        except Exception:
            continue
    return out


def open_stage(rr, ctx, form_id, dash_id):
    """대시보드 단계 단추(조회)를 누르고 cbo_stage 가 '단계 : <이름>' 이 될 때까지 기다린다 (docs/wellife-rpa.md 4.4절 단계 조회).
    0건 단계는 그리드 변화로 끝을 알 수 없어서 이렇게 본다. 이미 그 단계면 값이 그대로라 스피너로도 본다.
    (건수, 컨트롤)."""
    ctl = controls(rr, ctx, form_id)
    btn, stage = ctl.get(dash_id), ctl.get("cbo_stage")
    if btn is None or stage is None:
        raise Stop("failed", f"단계 단추({dash_id})나 cbo_stage 를 찾지 못했습니다.")
    label = btn.window_text().split("\r\n")[0].strip()
    already = same_stage(stage_name(rr.legacy_value(stage)), label)
    grid = ctl.get("gridCtrl_List")
    # 쉬고 있을 때의 오버레이 수 - 화면마다 다르다 (SAP 연동관리는 2, 10-07 실측). 스피너가 뜨면 하나 늘어난다
    idle = rr.grid_overlay_count(ctx.hwnd, grid) if grid is not None else 0
    no_popup(rr, ctx, f"'{label}' 단계 단추를 누르기 전")
    click(rr, ctx, btn, f"'{label}' 단계 단추")
    deadline = time.time() + STAGE_WAIT_SECONDS
    while not same_stage(stage_name(rr.legacy_value(stage)), label):
        if time.time() > deadline:
            raise Stop("failed", f"'{label}' 조회가 끝나지 않았습니다 (cbo_stage={rr.legacy_value(stage)!r}).")
        time.sleep(0.3)
    if already and grid is not None:   # 이미 그 단계 - 콤보 값이 그대로라 스피너가 뜨는지 잠깐 본다 (빠른 조회는 안 뜬다)
        probe = time.time() + 2
        while rr.grid_overlay_count(ctx.hwnd, grid) <= idle and time.time() < probe:
            time.sleep(0.2)
    if grid is not None and not rr.wait_grid_spinner_gone(ctx.hwnd, grid, idle, label=label,
                                                          max_wait=STAGE_WAIT_SECONDS):
        raise Stop("failed", f"'{label}' 조회 스피너가 {STAGE_WAIT_SECONDS}초 안에 사라지지 않았습니다.")
    no_popup(rr, ctx, f"'{label}' 조회")
    ctl = controls(rr, ctx, form_id)
    count = stage_count(ctl[dash_id].window_text()) if dash_id in ctl else None
    if count is None:
        raise Stop("failed", f"'{label}' 단추 이름에서 건수를 읽지 못했습니다.")
    rr.log(f"  단계 '{label}' 조회: {count}건 (cbo_stage={rr.legacy_value(stage)!r})")
    return count, ctl


def front(rr, ctx, what):
    """누르기(또는 마우스 올리기) 직전: 화면이 잠겼거나 ERPia 를 앞으로 가져오지 못하면 누르지 않고 멈춘다
    - 좌표 클릭이 잠금 화면이나 다른 프로그램 창에 떨어지지 않게 (10-07 실측: 잠긴 화면에서 화면 이동이 헛돌았다)."""
    if rr.ec.screen_locked():
        raise Stop("stopped", f"{what}: 윈도우 화면이 잠겨 있어 누르지 않고 멈춤")
    if not rr.ec.ensure_foreground(ctx.hwnd):
        raise Stop("failed", f"{what}: ERPia 창을 앞으로 가져오지 못해 누르지 않고 멈춤")


def no_popup(rr, ctx, after):
    """팝업(예/아니오/확인 단추)이 떠 있으면 누르지 않고 멈춘다."""
    buttons = rr.find_popup_buttons(ctx.window())
    if buttons:
        text = rr.collect_popup_text(buttons[0])
        raise Stop("stopped", f"{after} 뒤 팝업이 떠서 멈춤 (누르지 않음): {text[:200]}")


def mark_rows(rr, ctx, grid, expected, want):
    """그리드를 위에서부터 한 번만 내려가며, 줄마다 검토 칸을 읽는 대로 체크 칸을 맞춘다 - want(검토 값) 면 '선택',
    아니면 '선택안됨'. 다 읽고 다시 올라가 체크하지 않는다 (사용자 10-08). 행 번호는 스크롤해도 이어지는 절대 번호다
    (10-07 실측: 1~24 -> 페이지 아래로 -> 24~47). 칸 전체가 그리드 안에 보일 때만 누르고(잘린 칸을 누르면 스크롤바에
    떨어진다) 잘린 줄은 다음 페이지에서 맞춘다. 키보드는 쓰지 않는다 (행이 선택되면 아래 그리드가 다시 조회된다).
    ({행: 맞춘 값}, 못 맞춘 행 목록) - 못 맞춘 행 = 눌러도 바뀌지 않았거나 중간에 못 읽고 지나간 행."""
    deadline = time.time() + STAGE_WAIT_SECONDS
    while expected and not rr.grid_rows(grid) and time.time() < deadline:
        time.sleep(0.3)     # 건수가 있는데 그리드가 아직 비었다 - 채워질 때까지
    header = check_header(grid)
    # 아래 끝은 가로 스크롤바에 가려지는 부분만 뺀다 (grid_usable_bottom 은 행 하나를 통째로 빼서 페이지마다 마지막 행을 못 누른다)
    top, bottom = header.rectangle().bottom, rr.grid_click_bottom(grid)
    front(rr, ctx, "그리드 스크롤")     # 스크롤 단추는 rr 도우미가 누른다 (잠김·포커스는 여기서 한 번 본다)
    rr.grid_scroll_to_top(ctx.hwnd, grid)
    rows = settled_rows(rr, grid, first=1)
    clear_all_checks(rr, ctx, grid, header, rows)
    out, failed, seen, reviews = {}, set(), set(), {}
    for _ in range(MAX_PAGES):
        seen.update(rows)
        for n, cells in sorted(rows.items()):
            if n in out or "검토" not in cells or CHECK_COL not in cells:
                continue
            cell = cells[CHECK_COL]
            r = cell.rectangle()
            if r.top < top or r.bottom > bottom:
                continue
            review = rr.legacy_value(cells["검토"])
            value = "선택" if want(review) else "선택안됨"
            if rr.legacy_value(cell) != value:
                no_popup(rr, ctx, f"{n}행 체크 전")   # 앞 클릭으로 뜬 팝업도 여기서 잡힌다
                click(rr, ctx, cell, f"{n}행 체크 칸")
                deadline = time.time() + CHECK_WAIT_SECONDS
                while rr.legacy_value(cell) != value and time.time() < deadline:
                    time.sleep(0.2)
            if rr.legacy_value(cell) == value:
                out[n] = value
                failed.discard(n)
                reviews[review] = reviews.get(review, 0) + 1
            else:
                failed.add(n)
                rr.log(f"  {n}행 체크 칸이 '{value}' 가 되지 않았습니다 (지금 {rr.legacy_value(cell)!r})")
        rows = next_page(rr, ctx, grid, rows)
        if rows is None:
            break
    else:
        raise Stop("failed", f"그리드가 {MAX_PAGES}페이지를 넘어 끝까지 못 맞춤")
    # 본 줄 중 못 맞춘 줄(잘린 칸·칸 없음·안 바뀜)과 중간에 빠진 번호. 끝까지 이어져 있으면 그리드가 거기서 끝난 것이다 -
    # 단추 건수와 달라도 그리드 기준으로 한다 (10-07 실측: 매출전표 단추 201건, 그리드 198행에서 끝. 차이는 무시 - 사용자 결정)
    bad = sorted(failed | (set(range(1, max(seen, default=0) + 1)) - set(out)))
    # 검토 값별 줄 수 - 고른 줄이 맞는지 로그로 확인하게 (빈 칸은 '' 로 보인다)
    rr.log(f"  검토 값: {', '.join(f'{v!r} {c}줄' for v, c in sorted(reviews.items(), key=lambda x: -x[1]))}")
    if bad:
        rr.log(f"  확인할 것: 체크를 맞추지 못한 줄 {bad[:20]}{' …' if len(bad) > 20 else ''}")
    elif expected and len(out) != expected:
        rr.log(f"  그리드 {len(out)}줄을 끝까지 맞춤 (단추 {expected}건과 다름 - 그리드 기준)")
    return out, bad


def clear_all_checks(rr, ctx, grid, header, rows):
    """보이는 줄이 모두 체크돼 있으면 머리글을 한 번 눌러 전체를 푼다 (머리글은 토글) - 넘기지 않을 줄을 하나씩
    풀지 않게 (10-07 실측: 개발기 매출전표 198줄이 모두 검토에 값이 있다). 못 풀어도 mark_rows 가 줄마다 맞춘다."""
    states = [rr.legacy_value(c[CHECK_COL]) for c in rows.values() if CHECK_COL in c]
    if not states or any(s != "선택" for s in states):
        return
    no_popup(rr, ctx, "머리글 체크 칸 (전체 풀기) 전")
    click(rr, ctx, header, "머리글 체크 칸 (전체 풀기)")
    deadline = time.time() + CHECK_WAIT_SECONDS
    while time.time() < deadline:
        if all(rr.legacy_value(c[CHECK_COL]) == "선택안됨" for c in rows.values() if CHECK_COL in c):
            rr.log("  머리글로 전체 체크를 풀었습니다")
            return
        time.sleep(0.2)
    rr.log("  머리글로 전체 체크를 다 풀지 못해 줄마다 맞춥니다")


def settled_rows(rr, grid, moved_from=None, first=None):
    """다 그려진 그리드 행들 {행 번호: {컬럼: 셀}}. 스크롤 직후에는 앞 페이지가 그대로 읽혀 한 페이지를 건너뛴다
    (10-07 실측: 201건 중 140~161 을 못 읽음) - 두 번 연속 같은 행 번호들이 읽히고, moved_from 이 있으면 첫 행 번호가
    그것과 달라질 때까지, first 가 있으면 첫 행이 그 번호일 때까지(맨 위로 올린 뒤) 기다린다.
    PAGE_WAIT_SECONDS 안에 안 되면 마지막으로 읽은 것."""
    deadline = time.time() + PAGE_WAIT_SECONDS
    last = None
    while True:
        rows = rr.grid_rows(grid)
        keys = sorted(rows)
        if (keys and keys == last and (moved_from is None or keys[0] != moved_from)
                and (first is None or keys[0] == first)):
            return rows
        if time.time() > deadline:
            return rows
        last = keys
        time.sleep(0.2)


def next_page(rr, ctx, grid, rows):
    """한 페이지 내리고 다 그려진 새 행들. 끝이면 None (내릴 단추가 없거나, 내렸는데 첫 행이 그대로).
    내렸는데 그대로인데 '페이지 아래로' 가 아직 있으면 끝이 아니다 - 뒤 줄의 체크를 모르므로 멈춘다
    (전체 체크된 채 남은 줄이 4-2 로 넘어가지 않게)."""
    first = min(rows, default=None)
    if not rr.grid_page_down(ctx.hwnd, grid):
        return None
    rows = settled_rows(rr, grid, moved_from=first)
    if min(rows, default=None) != first:
        return rows
    try:
        vsb = rr.grid_vertical_scrollbar(grid)
        more = vsb is not None and any(c.window_text() == "페이지 아래로" for c in vsb.descendants())
    except Exception:
        more = False
    if more:
        raise Stop("failed", "페이지를 내렸는데 그리드가 움직이지 않아 멈춤 (뒤 줄은 못 맞춤)")
    return None


def split_open_button(split):
    """[지정▼] SplitButton 의 내림 단추('오픈'). 본체([지정])를 누르면 지정이 실행되므로 '오픈' 이 없거나, 크기가 없거나,
    본체만큼 넓거나, 단추의 오른쪽 절반 안에 있지 않으면 None (10-07 실측: 본체 L-1251~R-1178, '오픈' L-1196~R-1178)."""
    try:
        s = split.rectangle()
        arrow = next((k for k in split.children() if k.window_text() == "오픈"), None)
        if arrow is not None:
            a = arrow.rectangle()
            if (0 < a.width() < s.width() / 2 and a.height() > 0 and a.left >= s.left + s.width() / 2
                    and a.right <= s.right + 2 and s.top - 2 <= a.top and a.bottom <= s.bottom + 2):
                return arrow
    except Exception:
        pass
    return None


def hover_menu_item(rr, ctx, split, item_text, what, would_press):
    """리허설: [지정] 옆 ▼ 를 눌러 내림 메뉴를 열고 item_text 에 마우스만 올린 뒤 ESC 로 닫는다 - 항목은 누르지 않는다.
    사유에 덧붙일 글을 돌려준다 (문제 없으면 "")."""
    item, menu = _open_menu(rr, ctx, split, item_text, what, would_press)
    if item is None:
        return menu     # 열지 못했다 - 사유 글
    if rr.ec.screen_locked():   # front() 는 쓰지 않는다 - 메인 창을 앞으로 가져오면 메뉴가 닫힌다
        raise Stop("stopped", f"{what}: 윈도우 화면이 잠겨 있어 멈춤 (메뉴가 열려 있을 수 있음)")
    r = item.rectangle()
    mouse.move(coords=((r.left + r.right) // 2, (r.top + r.bottom) // 2))
    try:
        active = item.is_enabled()
    except Exception:
        active = None
    rr.log(f"  [리허설] {what}: 내림 메뉴를 열고 '{item.window_text()}' 에 마우스만 올림 (누르지 않음, 활성={active}"
           f"{'' if would_press else ', 전체 체크가 안 돼 실제 실행에서는 지정하지 않는 자리'})")
    time.sleep(HOVER_SECONDS)
    _close_menu(rr, ctx, {menu}, what)
    return ""


def press_menu_item(rr, ctx, split, item_text, what, grid=None):
    """실행: [지정] 옆 ▼ 로 내림 메뉴를 열고 item_text 를 누른 뒤 팝업을 [예]/[확인] 으로 넘긴다. (사유 글, 눌렀는가).
    누를 점의 맨 위 창이 그 메뉴 창일 때만 누른다 (다른 창이 덮고 있으면 그것이 눌린다). 항목이 꺼져 있으면 닫고 넘어간다."""
    item, menu = _open_menu(rr, ctx, split, item_text, what, True)
    if item is None:
        return menu, False
    if rr.ec.screen_locked():
        raise Stop("stopped", f"{what}: 윈도우 화면이 잠겨 있어 멈춤 (메뉴가 열려 있을 수 있음)")
    try:
        active = item.is_enabled()
    except Exception:
        active = None
    if active is False:
        rr.log(f"  확인할 것: {what} - '{item.window_text()}' 가 꺼져 있어 누르지 않음")
        _close_menu(rr, ctx, {menu}, what)
        return f" (확인할 것: '{item_text}' 꺼짐 - 누르지 않음)", False
    r = item.rectangle()
    pt = ((r.left + r.right) // 2, (r.top + r.bottom) // 2)
    mouse.move(coords=pt)
    top = _top_window(rr, pt)
    if top != menu:
        _close_menu(rr, ctx, {menu}, what)
        raise Stop("failed", f"{what}: '{item_text}' 자리를 다른 창({top})이 덮고 있어 누르지 않고 멈춤")
    idle = rr.grid_overlay_count(ctx.hwnd, grid) if grid is not None else 0
    before = popup_windows(rr, ctx) - {menu}
    rr.log(f"  [실행] {what}: '{item.window_text()}' 누름")
    item.click_input(coords=pt, absolute=True)
    deadline = time.time() + DROPDOWN_WAIT_SECONDS
    while _shown(rr, menu):
        if time.time() > deadline:
            raise Stop("failed", f"{what}: '{item_text}' 를 눌렀는데 메뉴가 닫히지 않아 멈춤")
        time.sleep(0.2)
    texts = confirm_popups(rr, ctx, what, grid, idle, before)
    return f" -> '{item_text}' 누름" + popup_note(texts), True


def _open_menu(rr, ctx, split, item_text, what, would_press):
    """[지정] 옆 ▼ 를 눌러 내림 메뉴를 열고 (항목, 메뉴 창) 을 돌려준다. 열지 못했으면 (None, 사유 글) - 메뉴는 닫아 둔다.
    - ▼ 는 split_open_button 이 고른 자리만 누른다. 못 고르거나 ▼ 가 꺼져 있으면 누르지 않고 마우스만 올린다.
    - 메뉴는 ERPia 의 별도 최상위 창으로 뜬다. 닫혔는지는 그 창이 화면에서 사라졌는지로 보고, 못 읽으면 열린 것으로
      보고 멈춘다 - 열린 채면 다음 클릭이 메뉴 항목에 떨어질 수 있다.
    - 팝업이 떠 있으면 ESC 도 보내지 않고 멈춘다 (ESC 는 팝업을 닫는다).
    - 항목을 못 찾으면 새로 뜬 창의 글자를 로그에 남기고(실측), 메뉴를 닫은 뒤 '확인할 것' 으로 넘어간다."""
    if split is None:
        raise Stop("failed", f"{what}: [지정] 단추(btn_CopyInsert)를 찾지 못했습니다.")
    arrow = split_open_button(split)
    if arrow is None:
        try:
            rr.log(f"  {what}: ▼ 자리 확인 실패 - 본체 {split.rectangle()}, 자식 "
                   f"{[(k.window_text(), str(k.rectangle())) for k in split.children()]}")
        except Exception:
            pass
        hover(rr, ctx, split, f"{what} (▼ 자리를 확인하지 못해 열지 않음)", would_press)
        return None, " (확인할 것: ▼ 자리를 확인하지 못해 메뉴를 열지 않음)"
    try:
        arrow_on = arrow.is_enabled()
    except Exception:
        arrow_on = False
    if not arrow_on:
        hover(rr, ctx, arrow, f"{what} ▼ (꺼져 있어 열지 않음)", would_press)
        return None, " (▼ 꺼짐)"

    no_popup(rr, ctx, f"{what} ▼ 를 누르기 전")
    before = _menu_windows(rr, ctx)
    click(rr, ctx, arrow, f"{what} ▼")
    item, menu = None, None
    deadline = time.time() + DROPDOWN_WAIT_SECONDS
    while item is None and time.time() < deadline:
        time.sleep(0.2)
        for name in dict.fromkeys((item_text, item_text.replace(" ", ""))):   # 띄어쓰기는 실측 전이라 둘 다
            item, menu = rr._find_menu_item(ctx.pid, ctx.hwnd, name)
            if item is not None:
                break
    opened = _menu_windows(rr, ctx) - before
    if item is None:
        rr.log(f"  확인할 것: {what} - 내림 메뉴에서 '{item_text}' 를 찾지 못했습니다. "
               f"새로 뜬 창 {len(opened)}개: {_window_texts(rr, opened)}")
        no_popup(rr, ctx, f"{what} ▼ 를 누른 뒤")
        menus = {h for h in opened if _has_buttons(rr, h)}   # 툴팁 같은 창은 메뉴가 아니다 - ESC 를 보낼 까닭이 없다
        if not menus:
            return None, " (확인할 것: ▼ 를 눌렀으나 메뉴가 뜨지 않음)"
        _close_menu(rr, ctx, menus, what)
        return None, f" (확인할 것: 메뉴에 '{item_text}' 가 없음 - 로그의 실측 글자 참고)"
    if menu not in opened:   # 누르기 전부터 떠 있던 메뉴 창 - 무엇이 열렸는지 모르니 멈춘다
        raise Stop("failed", f"{what}: ▼ 를 누르기 전부터 떠 있던 메뉴에서 항목이 잡혀 멈춤 (창 {menu})")
    return item, menu


def _close_menu(rr, ctx, windows, what):
    """ESC 로 내림 메뉴를 닫고 그 창들이 화면에서 사라졌는지 본다. 안 사라지면(또는 못 읽으면) 멈춘다.
    ESC 는 맨 앞 창이 ERPia 것일 때만 보낸다 (다른 프로그램으로 키가 가지 않게). 이미 닫혔으면 보내지 않는다
    (그때 ESC 는 화면(폼)으로 간다)."""
    if not any(_shown(rr, h) for h in windows):
        return
    try:
        fg_pid = rr.win32process.GetWindowThreadProcessId(rr.win32gui.GetForegroundWindow())[1]
    except Exception:
        fg_pid = None
    if fg_pid != ctx.pid:
        raise Stop("failed", f"{what}: 맨 앞 창이 ERPia 가 아니라 ESC 를 보내지 않고 멈춤 (메뉴가 열려 있을 수 있음)")
    rr.send_keys("{ESC}")
    deadline = time.time() + DROPDOWN_WAIT_SECONDS
    while any(_shown(rr, h) for h in windows):
        if time.time() > deadline:
            raise Stop("failed", f"{what}: 내림 메뉴가 ESC 로 닫히지 않아 멈춤 (다음 클릭이 메뉴에 떨어질 수 있다)")
        time.sleep(0.2)


def _menu_windows(rr, ctx):
    """ERPia 의 보이는 최상위 창 (메인 창 빼고) - 내림 메뉴는 이렇게 따로 뜬다."""
    out = set()

    def add(h, _):
        try:
            if h != ctx.hwnd and rr.win32gui.IsWindowVisible(h) and \
                    rr.win32process.GetWindowThreadProcessId(h)[1] == ctx.pid:
                out.add(h)
        except Exception:
            pass
    rr.win32gui.EnumWindows(add, None)
    return out


def _shown(rr, h):
    """창이 아직 화면에 있는가 (보이고 크기가 있다). 못 읽으면 있다고 본다 - 닫혔다고 잘못 보고 다음을 누르지 않게."""
    try:
        if not rr.win32gui.IsWindow(h) or not rr.win32gui.IsWindowVisible(h):
            return False
        left, top, right, bottom = rr.win32gui.GetWindowRect(h)
        return right > left and bottom > top
    except Exception:
        return True


def _has_buttons(rr, h):
    """그 창 안에 단추가 있는가 (메뉴 항목은 Button 이다 - 10-07 실측). 못 읽으면 있다고 본다 (닫는 쪽으로)."""
    try:
        return bool(rr.Desktop(backend="uia").window(handle=h).wrapper_object().descendants(control_type="Button"))
    except Exception:
        return True


def _window_texts(rr, handles, limit=20):
    """실측용: 창마다 [(종류, 글자)] - 메뉴 항목 이름이 다르면 이 로그로 고친다."""
    out = []
    for h in handles:
        try:
            w = rr.Desktop(backend="uia").window(handle=h).wrapper_object()
            out.append([(d.element_info.control_type, d.window_text()) for d in w.descendants() if d.window_text()][:limit])
        except Exception as e:
            out.append(f"(못 읽음: {type(e).__name__})")
    return out


def click(rr, ctx, el, what):
    """누르기 (단계 단추·체크 칸·▼·메뉴 검색). front() 뒤, 누를 자리의 맨 위 창이 ERPia 메인 창일 때만 누른다 -
    좌표 클릭이라 열린 내림 메뉴나 다른 프로그램 창이 그 자리를 덮고 있으면 그것이 눌린다.
    (메인 창 안에 그려지는 ERPia 팝업은 여기서 못 가린다 - no_popup 으로 본다)"""
    front(rr, ctx, what)
    pt = clear_point(rr, ctx, el, what)
    el.click_input(coords=pt, absolute=True)   # 확인한 그 점을 누른다 (사각형을 다시 읽어 다른 점을 누르지 않게)


def clear_point(rr, ctx, el, what):
    """누를 점(가운데). 창 안에 보이고 그 점의 맨 위 창이 ERPia 메인 창일 때만 돌려주고, 아니면 멈춘다 - 빈 사각형이면
    (0,0) 이, 열린 내림 메뉴나 다른 프로그램 창이 덮고 있으면 그것이 눌린다. 마우스를 그 점으로 먼저 옮긴다 (툴팁 치우기)."""
    r = el.rectangle()
    pt = ((r.left + r.right) // 2, (r.top + r.bottom) // 2)
    wr = ctx.window().rectangle()
    if r.width() <= 0 or r.height() <= 0 or not (wr.left <= pt[0] < wr.right and wr.top <= pt[1] < wr.bottom):
        raise Stop("failed", f"{what}: 누를 자리가 창 안에 보이지 않아 누르지 않고 멈춤 ({r})")
    mouse.move(coords=pt)
    deadline = time.time() + 1.0
    top = _top_window(rr, pt)
    while top != ctx.hwnd:
        if time.time() > deadline:
            raise Stop("failed", f"{what}: 누를 자리를 다른 창({top})이 덮고 있어 누르지 않고 멈춤")
        time.sleep(0.1)
        top = _top_window(rr, pt)
    return pt


def _top_window(rr, pt):
    """그 화면 좌표의 맨 위 최상위 창. 못 읽으면 None."""
    try:
        return rr.win32gui.GetAncestor(rr.win32gui.WindowFromPoint(pt), 2)    # GA_ROOT
    except Exception:
        return None


def hover(rr, ctx, el, what, would_press):
    """누를 자리에 마우스만 올리고 잠깐 머문다 - 클릭하지 않는다 (리허설, 또는 늘 누르지 않는 자동 수집).
    would_press: True=실행이면 누를 자리, False=대상이 없어 실행에서도 안 누름, None=따지지 않음."""
    if el is None:
        raise Stop("failed", f"{what} 단추를 찾지 못했습니다.")
    r = el.rectangle()
    front(rr, ctx, what)
    mouse.move(coords=((r.left + r.right) // 2, (r.top + r.bottom) // 2))
    try:
        active = el.is_enabled()
    except Exception:
        active = None
    rr.log(f"  [마우스만] {what}: 누르지 않고 마우스만 올림 (활성={active}"
           f"{', 대상이 없어 실제 실행에서도 누르지 않는 자리' if would_press is False else ''})")
    if would_press and active is False:
        rr.log(f"  확인할 것: {what} - 대상이 있는데 단추가 비활성입니다")
    time.sleep(HOVER_SECONDS)


def onscreen_button(win, text):
    """지금 창 안에 보이는 그 이름의 단추 (숨은 화면의 같은 이름 단추는 창 밖 좌표라 뺀다). 없으면 None."""
    wr = win.rectangle()
    for b in win.descendants(control_type="Button"):
        try:
            if b.window_text() != text:
                continue
            r = b.rectangle()
            if r.width() > 0 and wr.left <= r.left and wr.top <= r.top and r.right <= wr.right and r.bottom <= wr.bottom:
                return b
        except Exception:
            continue
    return None


def popup_windows(rr, ctx):
    """ERPia 가 따로 띄운 보이는 창들 (팝업 후보). 누르기 전에 재 두고, 그 뒤 새로 뜬 것만 팝업으로 본다."""
    return set(rr.find_popup_windows(ctx.pid, ctx.hwnd))


def confirm_popups(rr, ctx, what, grid=None, idle=0, before=frozenset()):
    """실행: 누른 뒤 처리가 끝날 때까지 팝업을 [예](없으면 [확인]) 로 넘긴다 - [아니오] 가 함께 있어도 [예] (사용자 10-08).
    메인 창 안 팝업과, 누른 뒤 새로 뜬 별도 창 팝업을 본다. 팝업도 스피너(grid 의 오버레이가 idle 보다 많음)도
    QUIET_SECONDS 동안 없으면 끝이다. 넘긴 팝업 문구 목록을 돌려준다 (로그에도 하나씩 남긴다).
    [예]/[확인] 이 없는 팝업, MAX_POPUPS 를 넘는 팝업, CONFIRM_WAIT_SECONDS 안에 안 끝나는 처리는 멈춘다."""
    texts = []
    deadline = time.time() + CONFIRM_WAIT_SECONDS
    calm = None
    while time.time() < deadline:
        found = _next_popup(rr, ctx, before)
        if found is not None:
            text, button = found
            if button is None:
                raise Stop("stopped", f"{what}: [예]/[확인] 이 없는 팝업이라 멈춤: {text[:200]}")
            if len(texts) >= MAX_POPUPS:
                raise Stop("stopped", f"{what}: 팝업이 {MAX_POPUPS}개를 넘어 멈춤 (마지막: {text[:200]})")
            front(rr, ctx, f"{what} 팝업")    # 잠김·포커스 - 좌표 클릭이 다른 프로그램 창에 떨어지지 않게
            r = button.rectangle()
            pt = ((r.left + r.right) // 2, (r.top + r.bottom) // 2)
            top = _top_window(rr, pt)
            if top != ctx.hwnd and top not in popup_windows(rr, ctx):
                raise Stop("failed", f"{what}: 팝업 단추 자리를 다른 창({top})이 덮고 있어 누르지 않고 멈춤: {text[:200]}")
            name = button.window_text()
            rr.log(f"  [실행] {what} 팝업: {text[:300]} -> [{name}] 누름")
            button.click_input(coords=pt, absolute=True)
            texts.append(text)
            calm = None
            time.sleep(0.5)
            continue
        busy = grid is not None and rr.grid_overlay_count(ctx.hwnd, grid) > idle
        if busy:
            calm = None
        elif calm is None:
            calm = time.time()
        elif time.time() - calm >= QUIET_SECONDS:
            failed = [t for t in texts if any(k in t for k in ("실패", "오류", "에러"))]
            if failed:     # 넘기기는 했지만 처리가 잘못됐을 수 있다 - 뒤 단계(지정 뒤 4-2 화살표 등)로 가지 않는다
                raise Stop("stopped", f"{what}: 팝업에 실패/오류 문구가 있어 뒤 단계는 하지 않고 멈춤: {failed[0][:200]}")
            return texts
        time.sleep(0.3)
    raise Stop("failed", f"{what}: {CONFIRM_WAIT_SECONDS}초 안에 처리가 끝나지 않았습니다 (넘긴 팝업 {len(texts)}개)")


def _next_popup(rr, ctx, before):
    """떠 있는 팝업 하나 (문구, 누를 단추) - 누를 단추가 없으면 (문구, None). 팝업이 없으면 None."""
    buttons = rr.find_popup_buttons(ctx.window())
    if buttons:
        return rr.collect_popup_text(buttons[0]), _yes_button(buttons)
    for h in sorted(popup_windows(rr, ctx) - set(before)):
        try:
            w = rr.Desktop(backend="uia").window(handle=h)
            return rr.popup_window_text(w), _yes_button(w.descendants(control_type="Button"))
        except Exception:
            continue    # 그새 닫힌 창
    return None


def _yes_button(buttons):
    """[예] 가 있으면 [예], 없으면 [확인]. 둘 다 없으면 None."""
    for names in (YES_TEXTS, OK_TEXTS):
        b = next((b for b in buttons if b.window_text() in names), None)
        if b is not None:
            return b
    return None


def popup_note(texts):
    """모듈 사유에 덧붙일 팝업 문구 요약."""
    return f" (팝업 {len(texts)}개: {' / '.join(t[:60] for t in texts)})" if texts else ""


# ---------------------------------------------------------------------------
# 메뉴 검색으로 화면 열기 (업체전용 메뉴는 좌측 아이콘이 없다)
# ---------------------------------------------------------------------------

def goto_screen_by_menu(rr, ctx, menu):
    """메인 창의 메뉴 검색(sch_Menus)에 메뉴명을 넣고, 걸러진 메뉴 트리(acd_Nav)에서 그 항목을 눌러 화면을 연다. (ok, 사유)

    개발기 실측 (10-06): 결과는 따로 뜨는 목록이 아니라 acd_Nav 트리가 걸러져 '업체전용' 아래
    그 항목만 남는다. 항목은 auto_id 가 없는 TreeItem 이라 이름으로 찾는다. 검색 칸 안의 Edit·ListBox 는
    auto_id 가 실행마다 달라 쓰지 않는다. type_keys 는 글자를 유니코드로 보내 한/영 입력 상태와 상관없다.
    키는 포커스가 검색 칸 안에 있을 때만 보낸다 - 막 열린 화면의 그리드 등으로 ^a·글자가 새지 않게.
    연 뒤에는 검색 칸을 비워 트리를 되돌린다 (다음 화면 이동이 걸러진 트리에서 막히지 않게).
    UI 오류는 실행 전체를 죽이지 않고 이 화면 이동의 실패로 돌려준다.
    """
    try:
        return _open_by_menu(rr, ctx, menu)
    except Stop as e:           # 잠긴 화면 / ERPia 를 앞으로 못 가져옴 - 누르지 않고 멈춘 것
        return False, str(e)
    except Exception as e:
        rr.log(f"  메뉴 검색 중 UI 오류: {type(e).__name__}: {e}")
        _clear_search(rr, ctx)
        return False, f"메뉴 검색 중 UI 오류: {type(e).__name__}"


def _open_by_menu(rr, ctx, menu):
    log = rr.log
    no_popup(rr, ctx, f"'{menu}' 화면 이동 전")   # 앞 화면(③ 물류대기 등)에서 뜬 팝업이 남아 있으면 그 위를 누르지 않게
    tab = open_tab(rr, ctx, menu)
    if tab is not None:
        # 이미 열린 화면은 메뉴를 눌러도 그 탭으로 가지 않는다 (10-07 실측: 60초 기다리다 사람이 탭을 닫고 다시 열었다)
        log(f"'{menu}' 화면이 이미 열려 있어 그 탭을 누릅니다: {tab.rectangle()}")
        click(rr, ctx, tab, f"'{menu}' 탭")
        ok, active = rr.wait_for_active_main_tab(ctx.app, ctx.hwnd, menu, ctx=ctx)
        if not ok:
            return False, f"'{menu}' 탭을 눌렀으나 그 화면으로 바뀌지 않았습니다 (활성 메인탭='{active}')."
        log(f"'{menu}' 화면으로 이동 확인 (활성 메인탭='{active}')")
        return True, None

    win = ctx.window()
    rr.prefetch_auto_ids(win, ("sch_Menus", "acd_Nav"))
    search, nav = rr.find_by_auto_id(win, "sch_Menus"), rr.find_by_auto_id(win, "acd_Nav")
    if search is None or nav is None:
        return False, "메뉴 검색 칸(sch_Menus)이나 메뉴 트리(acd_Nav)를 찾지 못했습니다."

    log(f"메뉴 검색: '{menu}'")
    click(rr, ctx, search, "메뉴 검색 칸")
    if not _focus_in(rr, "sch_Menus"):
        return False, f"메뉴 검색 칸에 포커스가 오지 않아 입력하지 않았습니다 (포커스: {_focus_chain(rr)[:2]})."
    search.type_keys("^a{BACKSPACE}")
    search.type_keys(rr.ec.literal_keys(menu), with_spaces=True)

    item = _wait_tree_item(nav, menu, MENU_WAIT_SECONDS)
    if item is None:
        _log_menu_state(rr, ctx, search, nav)
        _clear_search(rr, ctx)
        return False, (f"메뉴 검색 결과에 '{menu}' 가 없습니다 ({MENU_WAIT_SECONDS}초 대기) - "
                       "이 업체에 메뉴가 없거나 이름이 다릅니다 (로그의 검색 칸 값으로 입력이 들어갔는지 확인).")
    log(f"  메뉴 항목 클릭: {item.rectangle()}")
    click(rr, ctx, item, "메뉴 항목")

    ok, active = rr.wait_for_active_main_tab(ctx.app, ctx.hwnd, menu, ctx=ctx)
    if not ok:
        _log_menu_state(rr, ctx, search, nav)
    _clear_search(rr, ctx)
    if not ok:
        return False, f"'{menu}' 메뉴를 눌렀으나 화면이 열리지 않았습니다 (활성 메인탭='{active}')."
    log(f"'{menu}' 화면 열림 확인 (활성 메인탭='{active}')")
    return True, None


def open_tab(rr, ctx, name):
    """이미 열려 있는 그 화면의 메인 탭 (화면 안의 서브탭은 이름이 다르다). 없으면 None - 그때는 메뉴 검색으로 연다.
    탭 머리 전체가 창 안에 있고, 그 가운데에서 맞는 요소가 그 탭일 때만 돌려준다 - 탭바가 넘쳐 잘린 탭의 가운데는
    탭바의 ◀ ▶ × 단추일 수 있다. 같은 이름의 탭이 있는데 그렇지 않으면 멈춘다 (메뉴로는 이미 열린 화면에 못 간다)."""
    win = ctx.window()
    wr = win.rectangle()
    found = False
    for t in win.descendants(control_type="TabItem"):
        try:
            if t.window_text().strip() != name:
                continue
            found = True
            r = t.rectangle()
            if (r.width() > 0 and r.height() > 0 and wr.left <= r.left and r.right <= wr.right
                    and wr.top <= r.top and r.bottom <= wr.bottom and _hits_tab(rr, t, name)):
                return t
        except Exception:
            continue
    if found:
        raise Stop("failed", f"'{name}' 화면이 이미 열려 있지만 탭이 다 보이지 않아 누르지 않았습니다 "
                             "(탭을 몇 개 닫고 다시 실행)")
    return None


def _hits_tab(rr, tab, name):
    """탭 가운데 점에서 맞는 요소가 그 탭(또는 그 안)인가 - UIA 히트테스트 (수십 ms)."""
    r = tab.rectangle()
    try:
        el = rr.element_at_point((r.left + r.right) // 2, (r.top + r.bottom) // 2)
        for _ in range(4):
            if el is None:
                return False
            if el.element_info.control_type == "TabItem":
                return el.window_text().strip() == name
            el = el.parent()
    except Exception:
        pass
    return False


def _wait_tree_item(nav, name, timeout):
    """걸러진 트리에서 이름이 name 인 TreeItem 이 트리 안에 보이고 자리가 멈추면 돌려준다 (두 번 연속 같은 자리).
    필터가 반영되며 트리가 다시 배치되는 중에 누르지 않게 한다. timeout 초 안에 안 되면 None."""
    deadline = time.time() + timeout
    last = None
    while True:
        try:
            box = nav.rectangle()
            for item in nav.descendants(control_type="TreeItem"):
                if item.window_text() != name:
                    continue
                r = item.rectangle()
                cx, cy = (r.left + r.right) // 2, (r.top + r.bottom) // 2
                if r.width() > 0 and r.height() > 0 and box.left <= cx <= box.right and box.top <= cy <= box.bottom:
                    here = (r.left, r.top, r.right, r.bottom)
                    if here == last:
                        return item
                    last = here
                    break
            else:
                last = None
        except Exception:
            last = None     # 트리를 다시 그리는 중이면 다음 차례에 다시 본다
        if time.time() >= deadline:
            return None
        time.sleep(MENU_POLL_SECONDS)


def _focus_chain(rr, depth=8):
    """키보드 포커스가 있는 요소부터 부모로 올라가며 (automation_id, 종류, 이름). 못 읽으면 []."""
    chain = []
    try:
        info = rr.UIAElementInfo(rr.IUIA().get_focused_element())
        while info is not None and len(chain) < depth:
            chain.append((info.automation_id, info.control_type, info.name))
            info = info.parent
    except Exception:
        pass
    return chain


def _focus_in(rr, auto_id):
    """키보드 포커스가 auto_id 컨트롤이나 그 안쪽(검색 칸의 Edit 등)에 있는가."""
    return any(aid == auto_id for aid, _, _ in _focus_chain(rr))


def _log_menu_state(rr, ctx, search, nav):
    """실패 원인을 가리는 기록: 검색 칸 값(입력이 들어갔나), 보이는 메뉴 항목, 탭 목록."""
    try:
        rr.log(f"  검색 칸 값: {rr.legacy_value(search)!r}")
        names = [i.window_text() for i in nav.descendants(control_type="TreeItem") if i.rectangle().width() > 0]
        rr.log(f"  보이는 메뉴 항목 {len(names)}개: {names[:10]}")
        rr.log(f"  탭 목록: {[t.window_text() for t in ctx.window().descendants(control_type='TabItem')][:15]}")
    except Exception as e:
        rr.log(f"  (메뉴 상태를 읽지 못함: {type(e).__name__})")


def _clear_search(rr, ctx):
    """검색 칸을 비워 메뉴 트리를 되돌린다. ERPia 가 앞에 있고 포커스가 검색 칸에 올 때만 키를 보낸다.
    실패해도 화면 이동 결과는 바꾸지 않는다 (로그만)."""
    try:
        search = rr.find_by_auto_id(ctx.window(), "sch_Menus")
        if search is None:
            rr.log("  메뉴 검색 칸을 비우지 않았습니다 (검색 칸이 없음).")
            return
        click(rr, ctx, search, "메뉴 검색 칸 비우기")   # 잠김·앞 창·덮인 자리를 보고 누른다 (Stop 도 아래에서 로그만)
        if not _focus_in(rr, "sch_Menus"):
            rr.log(f"  메뉴 검색 칸에 포커스가 오지 않아 비우지 않았습니다 (포커스: {_focus_chain(rr)[:2]}).")
            return
        search.type_keys("^a{BACKSPACE}")
    except Exception as e:
        rr.log(f"  메뉴 검색 칸을 비우지 못했습니다(무시): {type(e).__name__}")
