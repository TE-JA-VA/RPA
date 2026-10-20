"""웰라이프 전용 실행: 로그인 → ② 주문매핑 → ③ 물류대기 → ④ 웰라이프 SAP 연동관리 → ⑤ 웰라이프 WMS 이관관리
→ ⑥ 운송장번호 전송.

사용자 설정(RPA_UserConfig.json)에 "Wellife" 섹션이 있는 PC 에서만 run_routine.main 이 이리로 온다.
섹션이 없는 PC(다른 업체)는 지금 루틴 그대로 돈다 - ROUTINE_MODULES 와 Routine 섹션은 건드리지 않는다.
    예: {"Wellife": {"Login": "Y", "Sales": "Y", "Hold": "Y", "Sap": "Y", "Wms": "Y", "InvoiceSend": "Y",
                     "SalesMode": "리허설", "NormalSalesMode": "리허설", "Mode": "리허설", "SapMode": "리허설",
                     "WmsMode": "리허설", "InvoiceMode": "리허설"}}

모드 (사용자 10-08) - 데이터를 바꾸는 단추를 누를지 정한다. 빠지면 리허설.
모듈마다 키가 따로다: "SalesMode" ② 엑셀 업로드, "NormalSalesMode" ② 하단 정상매출, "Mode" ③ 물류대기 저장,
"SapMode" ④ 지정·화살표, "WmsMode" ⑤ 화살표, "InvoiceMode" ⑥ [전송요청(S)] (사용자 10-13 - 빠지면 리허설, Mode 를 따르지 않는다).
- "리허설": 데이터를 바꾸는 단추(엑셀 업로드·물류대기 저장·[지정]·화살표·[전송요청(S)])는 누르지 않고 마우스만 올린다.
- "실행": 실제로 누르고, 뜨는 팝업은 [예](없으면 [확인])를 누른다 - [아니오] 가 함께 있어도 [예] (사용자 10-08).
  팝업 문구는 모두 로그와 모듈 사유에 남긴다.
- "1건": 실행과 같되 전체 체크 대신 첫 줄 하나만 체크해서 넘긴다 (실데이터 시험용 - 전체를 넘기면 다음 시험까지
  데이터가 다시 쌓이기를 오래 기다려야 한다, 사용자 10-13). 체크 칸이 없는 4-4·5-4 는 실행처럼 누른다. ② 엑셀 업로드는
  줄이 없어 못 쓴다. 한 번 실행에 1건이라 반복 회차(RPA_RUN_TRIGGER=repeat)에서는 돌지 않고 멈춘다 (repeat_ones).
모드는 대시보드 단계 이름·실행 제목·모듈 사유 앞의 [리허설]/[실행] 과 시작 로그로 보인다.
- ② 주문매핑은 세 모듈 (사용자 2026-10-15 - 켬/끔·모드·토큰 각각, 이 순서로 돈다):
  엑셀 수집 (Excel, SalesMode) - 미리 둔 엑셀(ERPIA_AI_EXCEL 의 (사이트코드)~.xlsx)이 있을 때만 올린다.
  자동 수집 (Import, ImportMode - 빠지면 SalesMode) - 원래 PROCESS 와 같이 상단 전체선택 -> [가져오기] (리허설은 마우스만).
  매출처리 (Sales, NormalSalesMode) - 하단 전체선택 -> 매출처리 ▼ 정상매출 (원래 PROCESS 와 같이, 사용자 10-14).
  Excel·Import 가 빠진 10-15 전 섹션은 Sales 켬/끔을 따른다 (FOLLOW_SALES).
- ③ 물류대기: 일반 탭 조회 -> 전체선택 -> 저장 (보류는 하지 않는다).
- ④⑤ 는 단계 조회·대상 고르기·체크 -> [지정]('선택 항목만')·화살표. 체크는 다음 단계를 조회하면 풀려서 되돌리지 않는다.
- ⑥ 운송장번호 전송: 조회 -> 전체 체크 -> [전송요청(S)]. 모든 업체용 패키지 화면이라(좌측 아이콘) 웰라이프 고유 값을
  쓰지 않는다 - 보통 PROCESS 도 부른다 (run_routine.module_invoice_send, Routine 섹션 InvoiceMode. docs/wellife-rpa.md 9절).
모듈별 실행: 예약 줄이 모듈을 고르면(RPA_RUN_MODULES, Wellife 키) 그 모듈만 돈다 - ②~⑥ 을 따로 띄울 수 있다.
⑤ 는 SAP 에서 넘어온 건이 WMS 에 하나씩 들어오므로 반복 시간대(시작~끝, N분 쉬고 다시)로 돌린다 (docs/wellife-rpa.md 7절).

run_routine 을 import 하지 않는다. exe 에서 run_routine 은 __main__ 이라 다시 import 하면 사본이 하나 더 생기고,
그 사본이 결과 로그를 'w' 로 다시 열어 지운다. 그래서 run_routine 이 자기 모듈(rr)을 넘겨준다.
"""
import contextlib
import datetime
import os
import re
import time

from pywinauto import mouse

from rpa_status import TOGETHER_ENV, TOGETHER_MODES   # 사이트 수집이 함께 띄운 실행·업체가 고른 전체 실행 방식 (run_main)

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
KEYS_SETTLE_SECONDS = 1     # 함께 실행: 키보드를 잡고 이만큼 뒤에 친다 - 사이트 수집이 하던 단계(새 창을 띄울 수 있다)를 마칠 틈
HIDDEN_MAX = 10             # 함께 실행: 업로드 중 '+' 화면이 뒤로 간(자동 수집이 원래 탭을 앞으로 가져옴) 횟수가 이보다 많으면 멈춘다
IDLE_WAIT_SECONDS = 60      # 자동 수집: 화면이 조회·다시 그리기를 마치기(단추가 켜진 채 머물기)를 기다리는 최대 시간
FOCUS_WAIT_SECONDS = 2      # 칸을 누른 뒤 키보드 포커스가 오기를 기다리는 최대 시간 (자동 수집 중엔 늦게 온다 - 10-19 실측)
HOVER_SECONDS = 1.5         # 리허설: 누를 자리에 마우스를 올려 두는 시간 (사람이 화면으로 보게 - 조건 대기 아님)
DROPDOWN_WAIT_SECONDS = 5   # [지정▼] 를 누른 뒤 내림 메뉴가 뜨기(또는 ESC 뒤 닫히기)를 기다리는 최대 시간
SELECTED_ONLY = "선택 항목만"   # [지정▼] 내림 메뉴 항목
MAX_PAGES = 200             # 그리드를 넘기는 최대 페이지 (끝을 못 알아챌 때의 안전장치)
PAGE_WAIT_SECONDS = 5       # 페이지를 넘긴 뒤 그리드가 다 그려지기를 기다리는 최대 시간
QUERY_WAIT_SECONDS = 120    # 물류대기 조회가 끝나기를 기다리는 최대 시간
CONFIRM_WAIT_SECONDS = 600  # 실행: 누른 뒤 처리(스피너·팝업)가 끝나기를 기다리는 최대 시간
QUIET_SECONDS = 5           # 실행: 팝업도 스피너도 이만큼 없으면 처리가 끝난 것으로 본다
POPUP_SETTLE_SECONDS = 5    # 실행: [예]/[확인] 이 없는 팝업은 이만큼 다시 본 뒤 멈춘다 - 막 뜬 팝업은 단추·문구가 아직 안 그려졌다
                            # (10-15 실측: 5-4 API 전송 [예] 뒤 저장확인 팝업을 빈 문구·단추 없음으로 읽고 멈췄다)
MAX_POPUPS = 10             # 실행: 한 번 누른 뒤 이보다 많이 뜨면 멈춘다 (같은 팝업이 되풀이되는 경우)
TAB_WAIT_SECONDS = 20       # 탭·아이콘·메뉴를 누른 뒤 그 화면이 떠 있는 메인 탭이 되기를 기다리는 최대 시간
MAIN_TAB_DEPTH = 6          # 메인 탭바를 창에서 자식을 따라 찾을 때 내려가는 최대 깊이 (10-14 실측: 4)
FORM_DEPTH = 4              # 떠 있는 화면 안에서 폼(Frm_…)을 자식을 따라 찾을 때 내려가는 최대 깊이
MODE_KEY = "Mode"              # ③ 물류대기 저장 (④⑤ 는 10-13 부터 따로 - SapMode·WmsMode)
SALES_MODE_KEY = "SalesMode"   # ② 엑셀 수집 (엑셀 업로드) - 따로 정한다 (사용자 10-08)
IMPORT_MODE_KEY = "ImportMode" # ② 자동 수집 [가져오기] - 따로 정한다 (사용자 10-15). 빠지면 SalesMode 를 따른다 (그 전엔 SalesMode 였다)
NORMAL_SALES_MODE_KEY = "NormalSalesMode"   # ② 하단 정상매출 - 따로 정한다 (10-14, SalesMode '실행' 의 뜻이 바뀌지 않게)
SAP_MODE_KEY = "SapMode"       # ④ 지정·화살표 (사용자 10-13)
WMS_MODE_KEY = "WmsMode"       # ⑤ 화살표 (사용자 10-13)
INVOICE_MODE_KEY = "InvoiceMode"   # ⑥ 운송장번호 [전송요청(S)] - 따로 정한다 (사용자 10-13, 택배사로 나가 되돌릴 수 없다)
# 모드 키 -> (시작 로그·제목 이름, 누르는 것). 이 순서로 보인다 (rpa_status.WELLIFE_MODES 와 같은 순서)
MODE_NAMES = {SALES_MODE_KEY: ("② 엑셀 수집", "엑셀 업로드"), IMPORT_MODE_KEY: ("② 자동 수집", "[가져오기]"),
              NORMAL_SALES_MODE_KEY: ("② 정상매출", "매출처리 ▼ 정상매출"),
              MODE_KEY: ("③ 물류대기", "저장"),
              SAP_MODE_KEY: ("④ SAP 연동", "지정·화살표"), WMS_MODE_KEY: ("⑤ WMS 이관", "화살표"),
              INVOICE_MODE_KEY: ("⑥ 운송장 전송", "[전송요청(S)]")}
ONE = "1건"   # 실행하되 체크는 첫 줄 하나만 (실데이터 시험용, 사용자 10-13). 참으로 읽혀 실행 경로를 그대로 탄다
MODES = {"리허설": False, "실행": True, "1건": ONE}   # 설정 값 -> 실제로 누르는가
YES_TEXTS = ("예(Y)", "예")
OK_TEXTS = ("확인(O)", "확인")

# 대시보드 단계 (rpa_status.step 키, 화면 이름). 순서가 곧 진행 순서다. 실행할 때 이름 앞에 [모드] 를 붙인다
STEPS = (
    ("login", "ERPia 로그인"),
    ("wl_excel_screen", "주문매핑 화면 이동 (엑셀 수집)"),
    ("wl_order_excel", "엑셀 업로드"),
    ("wl_import_screen", "주문매핑 화면 이동 (자동 수집)"),
    ("wl_order_import", "상단 전체선택 → [가져오기]"),
    ("wl_order_screen", "주문매핑 화면 이동 (매출처리)"),
    ("wl_order_sales", "하단 전체선택 → 매출처리 ▼ 정상매출"),
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
    ("inv_send_screen", "운송장번호 전송 화면 이동"),
    ("inv_send", "운송장번호 전송 조회 → 전체 체크 → 전송요청(S)"),
)
# run_routine.ROUTINE_MODULES 와 같은 모양 (모듈 키, 설정 키, 이름, 단계, module_flags 비트). 비트 32 부터는 웰라이프
MODULES = (
    ("login", "Login", "로그인", ("login",), 1),
    # ② 주문매핑은 셋 - 엑셀 수집 / 자동 수집 / 매출처리 (사용자 2026-10-15, 모드·토큰도 각각). 이 순서로 돈다
    ("wellife_excel", "Excel", "웰라이프 엑셀 수집", ("wl_excel_screen", "wl_order_excel"), 1024),
    ("wellife_import", "Import", "웰라이프 자동 수집", ("wl_import_screen", "wl_order_import"), 2048),
    ("wellife_sales", "Sales", "웰라이프 주문매핑 매출처리", ("wl_order_screen", "wl_order_sales"), 32),
    ("wellife_hold", "Hold", "웰라이프 물류대기", ("wl_hold_screen", "wl_hold_save"), 64),
    ("wellife_sap", "Sap", "웰라이프 SAP 연동관리", ("wl_sap_screen", "wl_sap_slip", "wl_sap_shipping", "wl_sap_so"), 128),
    ("wellife_wms", "Wms", "웰라이프 WMS 이관관리",
     ("wl_wms_screen", "wl_wms_so", "wl_wms_prepack", "wl_wms_invoice", "wl_wms_api"), 256),
    # 모든 업체용 (rpa_status.SHARED_MODULES) - 모듈 키에 wellife_ 를 붙이지 않는다 (= 설정 키 소문자, agent.history_key)
    ("invoicesend", "InvoiceSend", "운송장번호 전송", ("inv_send_screen", "inv_send"), 512),
)
# 모듈마다 따로 정하는 모드 키. 여기 없는 모듈(로그인·③ 물류대기)은 MODE_KEY
MODULE_MODES = {"wellife_excel": SALES_MODE_KEY, "wellife_import": IMPORT_MODE_KEY, "wellife_sales": NORMAL_SALES_MODE_KEY,
                "wellife_sap": SAP_MODE_KEY, "wellife_wms": WMS_MODE_KEY, "invoicesend": INVOICE_MODE_KEY}
# 엑셀 수집·자동 수집이 빠진 섹션 (10-15 전 PC) 은 주문매핑(Sales) 켬/끔을 따른다 - 업데이트만으로 수집이 멈추지 않게
FOLLOW_SALES = ("Excel", "Import")
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
                           f'예: {{"{SECTION}": {{"Login": "Y", "Sales": "Y", "Hold": "Y", "Sap": "Y", "Wms": "Y", "InvoiceSend": "Y"}}}}')
    keys = [m[1] for m in MODULES]
    selected, bad = {}, []
    for key in keys:
        raw = section.get(key, "N")
        value = str(raw).strip().upper()
        if value not in ("Y", "N"):
            bad.append(f"{key}={raw!r}")
        selected[key] = value == "Y"
    for key in FOLLOW_SALES:
        if key not in section:
            selected[key] = selected["Sales"]
    if bad:
        raise RuntimeError(
            f"{rr.pl.config_name()} 의 '{SECTION}' 섹션 값은 Y 또는 N 이어야 합니다: {', '.join(bad)}")
    return selected, sorted(k for k in section if k not in keys and k not in MODE_NAMES)


def load_mode(rr, key=MODE_KEY, section=SECTION):
    """True 면 실행(데이터를 바꾸는 단추를 실제로 누름), False 면 리허설. 빠지면 리허설 - 잘 모르면 누르지 않는 쪽.
    key: MODE_NAMES 의 키 하나 (모듈마다 따로 - 빠지면 Mode 를 따르지 않고 리허설). "1건" 이면 ONE (참 - 실행하되 한 줄만).
    ② SalesMode(엑셀 업로드)는 줄이 없어 "1건" 을 못 쓴다 (NormalSalesMode 는 하단 첫 줄 1건).
    section: 보통 PROCESS 의 운송장번호 전송은 Routine 섹션의 InvoiceMode (run_routine.module_invoice_send, 사용자 10-13).
    "리허설"/"실행" 이 아닌 값은 RuntimeError (load_switches 뒤에 부른다 - 섹션 모양은 거기서 본다)."""
    found = rr.pl.load_settings().get(section) or {}
    raw = found.get(key, found.get(SALES_MODE_KEY, "리허설") if key == IMPORT_MODE_KEY else "리허설")   # ImportMode 가 없으면 SalesMode
    value = str(raw).strip()
    allowed = [m for m in MODES if not (key in (SALES_MODE_KEY, IMPORT_MODE_KEY) and MODES[m] == ONE)]   # 줄이 없어 '1건' 을 못 쓴다
    if value not in allowed:
        raise RuntimeError(f"{rr.pl.config_name()} 의 '{section}' 섹션 {key} 값은 "
                           f"{' 또는 '.join(repr(m) for m in allowed)} 이어야 합니다: {raw!r}")
    return MODES[value]


def mode_tag(live):
    return ONE if live == ONE else "실행" if live else "리허설"


def repeat_ones(modes):
    """반복 회차(RPA_RUN_TRIGGER=repeat)인데 '1건' 인 모드 키들. '1건' 은 한 번 실행에 1건이라 반복을 켜 두면 회차마다
    1건씩 계속 넘어간다 - 이 키가 있으면 돌지 않는다 (10-14 PR #6 검토). modes: {모드 키: load_mode 값}."""
    if os.environ.get("RPA_RUN_TRIGGER") != "repeat":
        return []
    return [k for k, v in modes.items() if v == ONE]


def repeat_one_reason(keys):
    return (f"설정 확인: 반복 회차에서는 '1건' 을 쓸 수 없습니다 ({', '.join(keys)}) - 회차마다 1건씩 계속 넘어갑니다. "
            f"'실행' 으로 바꾸거나 반복 시간대에서 빼십시오")


def run_main(rr):
    """웰라이프 본 실행. run_routine.main 이 부른다. 기록은 지금 루틴과 같은 program "routine" 으로 남는다
    (실행 잠금·웹 현황·이력·토큰이 지금 규칙 그대로 동작한다)."""
    status, log = rr.status, rr.log
    try:
        selected, unknown = load_switches(rr)
        modes, error = {k: load_mode(rr, k) for k in MODE_NAMES}, None
    except Exception as e:
        modes, error = dict.fromkeys(MODE_NAMES, False), e
    # 예약 줄이 모듈을 골라 띄웠으면(반복 시간대 포함) 섹션의 켬·끔 대신 그 모듈만 - 지금 루틴과 같은 규칙. 모드는 섹션 그대로
    picked, picked_unknown = rr.run_modules_from_env([m[1] for m in MODULES])
    if not error and picked is not None:
        selected, unknown = picked, []
    # 모드는 단계 이름 앞에 붙여 대시보드·웹(진행 중 단계 이름 포함)에 늘 보이게 한다 - 단계마다 그 모듈의 모드
    step_mode = {k: MODULE_MODES.get(m[0], MODE_KEY) for m in MODULES for k in m[3]}
    steps = STEPS if error else tuple((k, f"[{mode_tag(modes[step_mode[k]])}] {label}") for k, label in STEPS)
    status.start("routine", steps, title="웰라이프 실행" if error else "웰라이프 실행 [" + " / ".join(
        f"{name[2:]} {mode_tag(modes[k])}" for k, (name, _) in MODE_NAMES.items()) + "]")
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
    for k, (name, what) in MODE_NAMES.items():
        v = modes[k]
        log(f"*  {name} 모드({k}): [{mode_tag(v)}] - " + (
            f"{what} 누르지 않고 마우스만" if not v else f"{what} 실제로 누르고, 팝업은 [예]/[확인]"
            + (" - 체크는 첫 줄 하나만" if v == ONE else "")))
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
    used = {step_mode[s] for m in MODULES if m[0] != "login" and selected[m[1]] for s in m[3]}   # 이번에 도는 모듈의 모드만
    ones = repeat_ones({k: modes[k] for k in MODE_NAMES if k in used})
    if ones:
        log(repeat_one_reason(ones))
        status.finish("stopped", repeat_one_reason(ones))
        log(f"=== 웰라이프 실행 종료 {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
        return
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

    def once(key, f):   # '1건' 모드가 걸린 모듈은 ERPia 가 꺼져도 다시 돌지 않는다 (run_routine.run_module - 1건이 2건이 된다)
        mod = next(m for m in MODULES if m[0] == key)
        one = any(modes[step_mode[s]] == ONE for s in mod[3])
        return lambda ctx: ((ctx.no_rerun.add(key) if one and hasattr(ctx, "no_rerun") else None), f(ctx))[1]

    # 함께 실행 (사용자 2026-10-19): 전체 실행에서 사이트 수집(프리페어)이 이 실행을 같이 띄웠다. 엑셀 수집을 실제로 하면 받는
    # 대로 올리고(excel_together), 아니면 수집이 끝나기를 기다린 뒤 예전처럼 돈다 (수집한 주문이 다 들어온 뒤에 매출처리).
    together = os.environ.get(TOGETHER_ENV) == "1"
    upload_together = together and bool(selected.get("Excel")) and bool(modes[SALES_MODE_KEY])
    import_live = bool(selected.get("Import")) and bool(modes[IMPORT_MODE_KEY])
    # 자동 수집도 사이트 수집과 함께 할지는 업체가 고른 전체 실행 방식대로 (사용자 2026-10-20) - '함께 (엑셀 업로드)' 면 엑셀만 받는 대로
    # 올리고 자동 수집은 ② 자동 수집 모듈이 사이트 수집이 끝난 뒤 (예전 차례)
    mode = rr.status.together_choice()
    import_together = import_live and mode == "excel_import"
    if together:
        log(f"전체 실행 방식: {TOGETHER_MODES.get(mode, mode)}")
    if together and not upload_together:
        wait_prepare(rr, "엑셀 수집을 실제로 하지 않아")
    if together:    # 로그인 창에 키를 치는 동안도 사이트 수집이 새 Edge 창을 띄우지 않게 (keys)
        rr.pl.KEYS_GUARD = lambda: keys(rr)
    funcs = {"login": rr.module_login,
             "wellife_excel": lambda ctx: module_excel(rr, ctx, modes[SALES_MODE_KEY], upload_together, import_together),
             "wellife_import": lambda ctx: module_import(rr, ctx, modes[IMPORT_MODE_KEY]),
             "wellife_sales": lambda ctx: module_sales(rr, ctx, modes[NORMAL_SALES_MODE_KEY]),
             "wellife_hold": lambda ctx: module_hold(rr, ctx, modes[MODE_KEY]),
             "wellife_sap": lambda ctx: module_sap(rr, ctx, modes[SAP_MODE_KEY]),
             "wellife_wms": lambda ctx: module_wms(rr, ctx, modes[WMS_MODE_KEY]),
             "invoicesend": lambda ctx: module_invoice_send(rr, ctx, modes[INVOICE_MODE_KEY])}
    funcs = {k: (f if k == "login" else once(k, f)) for k, f in funcs.items()}
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

def order_screen(rr, ctx, step, body):
    """② 주문매핑 화면으로 가서 body() - 엑셀 수집·자동 수집·매출처리 세 모듈이 함께 쓴다 (사용자 2026-10-15 셋으로 나눔).
    이 화면에서는 예상 못 한 팝업도 [예](없으면 [확인]) 로 넘긴다 - 단계 사이(no_popup)·[가져오기]·정상매출 뒤 별도 창 모두 (사용자 2026-10-15)."""
    rr.status.step(step)
    try:
        front(rr, ctx, "주문매핑 화면 이동")
        r = goto_screen(rr, ctx, ORDER_TAB, ORDER_ICON, lambda: _ok_or_reason(rr.goto_order_screen(ctx)))
    except Stop as e:
        return e.result, str(e)
    if r != "ok":
        return "failed", f"'{ORDER_ICON}' 아이콘을 찾지 못했습니다." if r == "absent" else r
    ctx.pass_popups = rr.POPUP_PREFER_YES = True
    try:
        return body()
    except Stop as e:
        return e.result, str(e)
    except Exception as e:
        return ui_error(rr, e)
    finally:
        ctx.pass_popups = rr.POPUP_PREFER_YES = False


def module_excel(rr, ctx, live=False, together=False, import_live=False):
    """② 엑셀 수집 (live: SalesMode). together - 사이트 수집과 함께 (excel_together)."""
    if together:    # 사이트 수집이 함께 돌며 Edge 창이 뜬다 - 화면 이동·[가져오기]·업로드 칸 자리를 덮지 않게 처음부터 맨 위로, 끝나면 푼다
        on_top(rr, ctx.hwnd, True)
        try:
            return order_screen(rr, ctx, "wl_excel_screen", lambda: excel_together(rr, ctx, import_live))
        finally:
            on_top(rr, ctx.hwnd, False)
    return order_screen(rr, ctx, "wl_excel_screen", lambda: excel_collect(rr, ctx, live))


def module_import(rr, ctx, live=False):
    """② 자동 수집 (live: ImportMode). 함께 실행이면 엑셀 업로드 전에 걸어 둔 자동 수집이 끝나기를 기다린다 (ctx.import_end)."""
    end = getattr(ctx, "import_end", None)
    if end is not None:
        ctx.import_end = None
        return order_screen(rr, ctx, "wl_import_screen", end)
    return order_screen(rr, ctx, "wl_import_screen", lambda: import_collect(rr, ctx, live))


def module_sales(rr, ctx, sell=False):
    """② 주문매핑 매출처리: 하단 전체선택 -> 매출처리 ▼ 정상매출 (normal_sales, sell: NormalSalesMode)."""
    def body():
        note, sold = normal_sales(rr, ctx, sell)
        return ("done" if sold else "skipped"), f"[{mode_tag(sell)}] 정상매출 " + note
    return order_screen(rr, ctx, "wl_order_screen", body)


def site_grid(rr, ctx):
    """주문매핑 상단 사이트 그리드 - 떠 있는 화면 안만 (창 전체는 숨은 화면까지 수천 개)."""
    tables = rr.get_onscreen_tables(visible_page(ctx))
    if not tables:
        raise Stop("failed", "주문매핑 사이트 그리드를 찾지 못했습니다.")
    return min(tables, key=lambda t: (t.rectangle().top, t.rectangle().left))


def excel_collect(rr, ctx, live):
    """엑셀 수집 (사용자 10-08): 미리 둔 파일(ERPIA_AI_EXCEL 의 (사이트코드)~.xlsx)이 있을 때만 기존 run_excel_upload_step 으로 올린다
    (끝난 파일은 완료/날짜, 못 올린 파일은 오류 폴더로 옮겨진다). 리허설이면 올리지 않고 첫 사이트의 업로드 칸에 마우스만."""
    rr.status.step("wl_order_excel")
    files = excel_files(rr)
    if not files:
        return "skipped", f"[{mode_tag(live)}] 엑셀: 올릴 파일 없음"
    sites, names = site_grid(rr, ctx), ", ".join(sorted(files))
    if not live:
        code = sorted(files)[0]
        cell, _ = rr.find_site_upload_cell(ctx.hwnd, sites, code)
        if cell is not None:
            hover(rr, ctx, cell, f"엑셀 업로드 칸 (사이트 {code})", True)
        return "skipped", f"[{mode_tag(live)}] 엑셀 {len(files)}건 있음 (사이트 {names}) - 올리지 않음"
    no_popup(rr, ctx, "엑셀 업로드 전")
    front(rr, ctx, "엑셀 업로드")
    rr.log(f"  [실행] 엑셀 업로드: 사이트 {names}")
    try:
        uploaded, errors = rr.run_excel_upload_step(ctx.app, ctx.pid, ctx.hwnd, sites)
    except rr.UploadStop as e:
        raise Stop("stopped", f"엑셀 업로드 중 누를 단추를 모르는 창이 떠 멈춤 (누르지 않음): {e}") from e
    return ("done" if uploaded else "skipped"), (f"[{mode_tag(live)}] 엑셀 {len(files)}건 중 {uploaded}건 업로드"
                                                 + (f", {errors}건은 오류 폴더로 (확인할 것)" if errors else ""))


def excel_together(rr, ctx, import_live):
    """함께 실행 (사용자 2026-10-19): 사이트 수집(프리페어)과 같이 돌며 사이트마다 받은 엑셀을 바로 올린다.
    1. 자동 수집도 실제로 하면 메뉴 검색의 '+' 로 같은 화면을 하나 더 열어 두고, 원래 화면으로 돌아가 [가져오기] 를 눌러 시작만
       확인한 뒤 (끝은 ② 자동 수집 모듈이 기다린다) '+' 화면으로 가서 올린다 - 자동 수집은 오래 걸린다 (사용자). 메뉴 검색에 키를
       치는 일은 자동 수집 전에 - 자동 수집 중 뜬 ERPia 팝업이 포커스를 가져가 '+' 를 못 열었다 (10-19 실측 2차).
    2. 사이트 수집은 기다리지 않고 인증 사이트부터 돈다 (사용자 10-19). 그동안 Edge 창이 뜰 때마다 포커스를 가져가므로 메뉴 검색에
       키를 치는 동안만 수집을 잡고(keys), ERPia 는 맨 위로 두고(module_excel - 업로드 칸을 다른 창이 덮으면 안 열린다) 파일 창·팝업은
       창 메시지·UIA 로만 (run_routine.UPLOAD_NO_KEYS).
    3. 프리페어가 끝나고 새 파일이 없을 때까지 올린다. 앞 차례에 못 올려 그 자리에 남은 파일은 다시 누르지 않는다 (다음 실행에)."""
    rr.status.step("wl_order_excel")
    copy = None
    if import_live:
        copy = open_order_copy(rr, ctx)
        switch_tab(rr, ctx, ORDER_TAB)
        end = import_collect(rr, ctx, True, wait=False)
        ctx.import_end = end if callable(end) else (lambda: end)    # 단추가 없어 건너뜀이면 그 결과를 그대로
        switch_tab(rr, ctx, copy)
    sites = site_grid(rr, ctx)
    no_popup(rr, ctx, "엑셀 업로드 전")
    uploaded = errors = hidden = 0
    tried = set()
    rr.UPLOAD_NO_KEYS = True
    try:
        rr.log("  [실행] 엑셀 업로드: 사이트 수집과 함께 - 사이트마다 받은 엑셀을 받는 대로 올립니다")
        while True:
            new = upload_paths(rr) - tried
            if new:
                if copy and keep_front(rr, ctx, copy):
                    sites = site_grid(rr, ctx)
                try:
                    u, e = rr.run_excel_upload_step(ctx.app, ctx.pid, ctx.hwnd, sites, skip=tried)
                    tried |= new
                except rr.UploadGridHidden as h:     # 남은 파일은 그 자리에 있다 - 다음 차례에 화면을 되돌려 이어서 올린다
                    u, e, hidden = h.uploaded, h.errors, hidden + 1
                    if not copy or hidden > HIDDEN_MAX:
                        raise Stop("stopped", f"엑셀 업로드 중 사이트 그리드가 계속 화면에서 사라져({hidden}번) 멈춤 - "
                                              "남은 파일은 업로드 폴더에 그대로 있습니다 (확인할 것)") from h
                uploaded, errors = uploaded + u, errors + e
            elif "prepare" in rr.status.running_programs():
                time.sleep(1)
            elif not upload_paths(rr) - tried:     # 수집이 끝났다 - 끝나기 직전에 넘긴 파일이 없으면 끝
                break
    except rr.UploadStop as e:
        raise Stop("stopped", f"엑셀 업로드 중 누를 단추를 모르는 창이 떠 멈춤 (누르지 않음): {e}") from e
    finally:
        rr.UPLOAD_NO_KEYS = False
    rr.status.metric("excel_upload", "엑셀 업로드", uploaded, len(tried), unit="개",
                     note=f"오류 폴더 {errors}개" if errors else None)
    if copy:
        close_order_copy(rr, ctx, copy)
    return ("done" if uploaded else "skipped"), (f"[{mode_tag(True)}] 엑셀 {len(tried)}건 중 {uploaded}건 업로드 (사이트 수집과 함께)"
                                                 + (f", {errors}건은 오류 폴더로 (확인할 것)" if errors else ""))


def upload_paths(rr):
    """업로드 폴더의 올릴 엑셀 경로 (사이트코드가 겹친 것도) - 폴더가 없으면 빈 집합."""
    folder = rr.excel_upload_dir()
    if not os.path.isdir(folder):
        return set()
    targets, duplicates, _ = rr.collect_upload_files(folder)
    return set(targets.values()) | set(duplicates)


def wait_prepare(rr, why):
    """함께 실행인데 엑셀을 함께 올리지 않는다 - 수집(프리페어)이 끝날 때까지 기다린다 (예전 차례 그대로)."""
    rr.log(f"사이트 수집과 함께 띄웠지만 {why} 수집이 끝나기를 기다린 뒤 시작합니다.")
    while "prepare" in rr.status.running_programs():
        time.sleep(2)


def on_top(rr, hwnd, on):
    """ERPia 메인 창을 맨 위로 두거나 푼다 (함께 실행 - Edge 창이 업로드 칸을 덮지 않게). 크기·자리·포커스는 그대로."""
    try:
        rr.win32gui.SetWindowPos(hwnd, rr.win32con.HWND_TOPMOST if on else rr.win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
                                 rr.win32con.SWP_NOMOVE | rr.win32con.SWP_NOSIZE | rr.win32con.SWP_NOACTIVATE)
    except Exception as e:
        rr.log(f"  ERPia 창을 {'맨 위로 두지' if on else '맨 위에서 풀지'} 못했습니다: {e}")


@contextlib.contextmanager
def keys(rr):
    """함께 실행 (사용자 10-19): 이 안에서 ERPia 에 키보드·포커스를 쓴다 - 사이트 수집(프리페어)이 도는 중이면 그동안 Edge 창을 새로
    띄우거나 다음 단계로 가지 않게 잡는다 (rpa_status.hold_keys). Edge 창은 뜰 때마다 포커스를 가져가 그사이 친 키(비밀번호
    포함)가 Edge 로 샌다 (개발기 실측). 함께 실행이 아니거나 수집이 끝났으면 아무것도 하지 않는다."""
    global _keys_depth
    if _keys_depth or os.environ.get(TOGETHER_ENV) != "1" or "prepare" not in rr.status.running_programs():
        _keys_depth += 1        # 이미 잡은 차례 안에서 다시 부르면(검색 칸 비우기 등) 바깥이 놓을 때까지 그대로
        try:
            yield
        finally:
            _keys_depth -= 1
        return
    rr.status.hold_keys(True)
    _keys_depth = 1
    try:
        # ponytail: 수집이 이미 시작한 단계가 늦게 띄우는 창(사이트 팝업)은 틈(KEYS_SETTLE_SECONDS)으로만 피한다 - 새는 일이 보이면
        # 수집 쪽이 '단계 사이에서 멈췄다' 를 알리고 루틴이 그것을 기다리게 바꿀 것
        time.sleep(KEYS_SETTLE_SECONDS)
        yield
    finally:
        _keys_depth = 0
        rr.status.hold_keys(False)


_keys_depth = 0     # keys 를 겹쳐 부른 깊이 (바깥 하나만 잡고 놓는다)


def open_order_copy(rr, ctx):
    """메뉴 검색에서 이미 열린 주문매핑 매출처리 옆 '+' 로 같은 화면을 하나 더 연다 (사용자 2026-10-19 - 자동 수집이 도는 동안
    엑셀은 다른 화면에서). 새 탭은 '주문매핑 매출처리 (2)' 처럼 번호가 붙어 바로 떠 있는 탭이 된다 (개발기 실측 2.4초).
    반환: 새 탭 이름. 못 열면 Stop."""
    win = ctx.window()
    rr.prefetch_auto_ids(win, ("sch_Menus", "acd_Nav"))
    search, nav = rr.find_by_auto_id(win, "sch_Menus"), rr.find_by_auto_id(win, "acd_Nav")
    if search is None or nav is None:
        raise Stop("failed", "메뉴 검색 칸(sch_Menus)이나 메뉴 트리(acd_Nav)를 찾지 못해 주문매핑 화면을 하나 더 열지 못했습니다.")
    try:
        # 입력부터 '+' 화면이 뜰 때까지 키보드 차례 안에서 - 입력만 잡았을 때 '+' 를 누른 순간 새 Edge 창이 포커스를 가져가
        # '(2)' 가 열리지 않았다 (10-20 실시험 2차)
        with keys(rr):
            click(rr, ctx, search, "메뉴 검색 칸")
            if not _focus_in(rr, "sch_Menus"):
                raise Stop("failed", "메뉴 검색 칸에 포커스가 오지 않아 주문매핑 화면을 하나 더 열지 못했습니다.")
            search.type_keys("^a{BACKSPACE}")
            search.type_keys(rr.ec.literal_keys(ORDER_TAB), with_spaces=True)
            item = _wait_tree_item(nav, ORDER_TAB, MENU_WAIT_SECONDS)
            plus = next((c for c in item.children() if c.element_info.control_type == "Button"), None) if item else None
            if plus is None:
                raise Stop("failed", f"메뉴 검색 결과에서 '{ORDER_TAB}' 옆 '+' 를 찾지 못했습니다.")
            click(rr, ctx, plus, f"'{ORDER_TAB}' 옆 + (같은 화면 하나 더)")
            end = time.time() + TAB_WAIT_SECONDS
            while time.time() < end:
                active = (rr.get_active_main_tab(ctx.app, ctx.hwnd) or "").strip()
                if active.startswith(ORDER_TAB) and active != ORDER_TAB and rr.get_onscreen_tables(visible_page(ctx)):
                    rr.log(f"  주문매핑 화면을 하나 더 열었습니다: '{active}' - 엑셀은 여기서 올립니다")
                    return active
                time.sleep(0.3)
            raise Stop("failed", f"'+' 를 눌렀으나 주문매핑 화면이 하나 더 열리지 않았습니다 ({TAB_WAIT_SECONDS}초).")
    finally:
        _clear_search(rr, ctx)


def keep_front(rr, ctx, name):
    """name 탭이 앞에 있게 - 자동 수집이 도는 동안 ERPia 가 원래 탭을 앞으로 가져와 '+' 로 연 화면이 뒤로 간다 (10-20 개발기 실측:
    숨은 탭의 그리드는 화면 밖으로 옮겨진다). 되돌렸으면 True (그리드를 다시 잡을 것)."""
    active = (active_tab(ctx) or "").strip()
    if active == name:
        return False
    rr.log(f"  '{name}' 화면이 뒤로 갔습니다 (떠 있는 탭='{active}') - 되돌립니다")
    switch_tab(rr, ctx, name)
    return True


def switch_tab(rr, ctx, name):
    """열려 있는 name 탭('주문매핑 매출처리 (2)' 처럼 번호까지)으로 간다. 못 가면 Stop."""
    went = goto_open_tab(rr, ctx, name)
    if not went or not went[0]:
        raise Stop("failed", went[1] if went else f"'{name}' 탭을 찾지 못했습니다.")


def close_order_copy(rr, ctx, name):
    """엑셀을 올린 '주문매핑 매출처리 (2)' 탭을 닫는다 (다음 실행에 번호가 늘지 않게). 못 닫아도 실행은 계속 - 로그만.
    숨은 탭의 닫기는 먹지 않았다 (10-20 실측: 자동 수집이 원래 탭을 앞으로 가져온 뒤 누른 닫기에 탭이 남았다) - 앞으로 가져와 닫는다."""
    try:
        keep_front(rr, ctx, name)
        tab = next((t for t in main_tab_bar(ctx)[1] if t.window_text().strip() == name), None)
        x = next((c for c in tab.children() if c.window_text() == "닫기"), None) if tab is not None else None
        if x is None:
            rr.log(f"  '{name}' 탭의 닫기 단추를 찾지 못해 열어 둡니다.")
            return
        click(rr, ctx, x, f"'{name}' 탭 닫기")
        no_popup(rr, ctx, f"'{name}' 탭 닫기")
        if any(t.window_text().strip() == name for t in main_tab_bar(ctx)[1]):
            rr.log(f"  '{name}' 탭의 닫기를 눌렀으나 닫히지 않아 열어 둡니다.")
    except Stop as e:
        rr.log(f"  '{name}' 탭을 닫지 못해 열어 둡니다: {e}")


def import_collect(rr, ctx, live, wait=True):
    """자동 수집: 원래 PROCESS 와 같이 상단(사이트) 전체선택 -> [가져오기] (run_import_step - 끝날 때까지 기다리고 안내 팝업은
    닫는다). 리허설은 전체선택만 하고(체크는 데이터를 바꾸지 않는다) [가져오기] 에 마우스만 (사용자 10-14)."""
    rr.status.step("wl_order_import")
    page, what = visible_page(ctx), f"자동 수집 [{rr.IMPORT_BUTTON_NAME}]"
    imp = onscreen_button(page, rr.IMPORT_BUTTON_NAME)
    if imp is None:
        return "skipped", f"[{mode_tag(live)}] 자동 수집 단추 없음"
    sites = site_grid(rr, ctx)
    no_popup(rr, ctx, "상단 전체선택 전")
    front(rr, ctx, "상단 전체선택")
    if live:    # 늦게 끝난 조회가 그리드를 다시 그리면 체크가 풀린다 - 풀린 채 누르면 '항목을 선택하세요' (10-19 실측 2차)
        wait_idle(rr, imp, what)
    n = rr.select_all_and_verify("좌측상단", ctx.hwnd, sites, ["아이디"])
    no_popup(rr, ctx, "상단 전체선택")
    if not live:
        hover(rr, ctx, imp, what, True)
        return "skipped", f"[{mode_tag(live)}] 자동 수집: 사이트 {n or 0}줄 전체선택, [{rr.IMPORT_BUTTON_NAME}] 는 누르지 않음"
    if not n:   # 원래 PROCESS 는 그래도 누르지만 웰라이프는 모르면 멈춘다
        raise Stop("failed", f"상단 전체선택을 확인하지 못해 {what} 를 누르지 않고 멈춤")
    wait_idle(rr, imp, what)
    # ponytail: 다시 본 뒤 run_import_step 이 단추를 다시 찾아 누르기까지(1~3초) 다시 그려지면 못 막는다 - 그때는 그 함수 안에서 다시 볼 것
    if not sites_checked(rr, sites):
        raise Stop("failed", f"상단 전체선택 뒤 화면이 다시 그려져 체크가 풀렸습니다 - {what} 를 누르지 않고 멈춤 (확인할 것)")
    # run_import_step 은 넘긴 범위에서 첫 같은 이름 단추를 다시 찾아 누른다 - 떠 있는 화면만 넘기고, 그 단추가
    # 확인한 단추와 같은 자리인지, 그 자리가 창 안에 보이고 덮이지 않았는지 본 뒤 누른다 (숨은 화면 단추를 누르지 않게)
    again = rr.find_by_text(page, rr.IMPORT_BUTTON_NAME, control_types=("Button",))
    if again is None or again.rectangle() != imp.rectangle():
        raise Stop("failed", f"{what}: 누를 단추가 떠 있는 화면의 단추와 달라 누르지 않고 멈춤")
    front(rr, ctx, what)
    clear_point(rr, ctx, imp, what)
    rr.log(f"  [실행] {what}: 사이트 {n}줄 전체선택 뒤")
    started = rr.run_import_step(ctx.app, ctx.pid, ctx.hwnd, page, wait=wait)

    def end(ok):
        if not ok:
            raise Stop("stopped", f"{what} 를 눌렀으나 끝난 것을 확인하지 못해 다음 모듈로 넘어가지 않고 멈춤 (확인할 것)")
        return "done", f"[{mode_tag(live)}] 자동 수집: 사이트 {n}줄 전체선택 -> [{rr.IMPORT_BUTTON_NAME}] 완료"
    if wait:
        return end(started)
    # 함께 실행: 끝은 ② 자동 수집 모듈에서 (module_import) - 시작을 못 봤으면 그때 멈춘다
    return lambda: end(bool(started) and started())


def wait_idle(rr, button, what):
    """button 이 rr.IMPORT_SETTLE_SECONDS 동안 계속 켜져 있을 때까지 - 화면이 조회·다시 그리기를 마쳤다 (run_import_step 이 끝을 보는
    방법과 같다). 켜짐을 못 읽으면 기다리지 않는다. IDLE_WAIT_SECONDS 안에 안 되면 멈춘다 (팝업이 메인 창을 막고 있어도 꺼져 보인다)."""
    end, since = time.time() + IDLE_WAIT_SECONDS, None
    while True:
        on = rr.native_enabled(button)
        if on is None:
            return
        since = (since or time.time()) if on else None
        if since is not None and time.time() - since >= rr.IMPORT_SETTLE_SECONDS:
            return
        if time.time() > end:
            raise Stop("failed", f"{what}: {IDLE_WAIT_SECONDS}초 동안 화면이 조회를 끝내지 않아(단추가 꺼져 있음) 누르지 않고 멈춤")
        time.sleep(0.3)


def sites_checked(rr, grid):
    """상단 사이트 그리드가 지금 전체선택 상태인가 - select_all_and_verify 와 같은 판단 (체크 칸 없는 줄 null 은 뺀다)."""
    checked, unchecked, _ = rr.summarize(rr.scan_current_view(grid, ["아이디"]))
    return bool(checked) and not unchecked


SALES_SPLIT, SALES_ITEM = "매출처리", "정상매출"
BOTTOM_ID_COLUMNS = ["주문번호", "마켓 상품명", "주문시간"]     # 원래 module_sales 의 하단 전체선택과 같다


def normal_sales(rr, ctx, live):
    """② 엑셀 업로드 뒤: 하단 그리드 전체선택 -> 매출처리 ▼ -> 정상매출 (원래 PROCESS module_sales 8~11 단계, 사용자 10-14).
    (사유 글, 눌렀는가). live: NormalSalesMode.
    - 하단 전체선택은 원래 select_all_and_verify 그대로 - 리허설도 한다 (체크는 데이터를 바꾸지 않는다). '1건' 은 첫 줄만.
    - 리허설은 ▼ 로 메뉴를 열어 '정상매출' 에 마우스만 올리고 ESC (hover_menu_item). 실행은 ▼ → '정상매출' 을 [지정▼] 와
      같은 자리 확인으로 누르고, 뒤 팝업·비동기 대기는 원래 코드 그대로 (after_normal_sales - 사용자 10-14 '원래 규칙').
    - 하단이 0줄이면 누르지 않는다 (원래는 0건이어도 누른다 - 웰라이프는 0건이면 누르지 않는다).
    - 누르기 직전에 보이는 줄이 모두 체크인지 다시 본다 (recheck)."""
    rr.status.step("wl_order_sales")
    page = visible_page(ctx)        # 떠 있는 화면 안만 훑는다
    tables = rr.get_onscreen_tables(page)
    if len(tables) < 2:
        raise Stop("failed", "주문매핑 하단 그리드를 찾지 못했습니다.")
    bottom = max(tables, key=lambda t: t.rectangle().top)
    if not rr.grid_rows(bottom):
        rr.log("  주문매핑 하단 0줄 - 매출처리 하지 않음")
        return "하단 0줄 - 매출처리 하지 않음", False
    no_popup(rr, ctx, "하단 전체선택 전")
    front(rr, ctx, "하단 전체선택")
    if live == ONE:     # 첫 줄 하나만 (다른 단계의 '1건' 과 같다). 못 했으면 이미 체크돼 있던 한 줄로 누르지 않게 n 으로도 막는다
        n = 1 if check_one_row(rr, ctx, bottom, "주문매핑 하단") else 0
        head = "하단 첫 줄 1건 체크" if n else "하단 첫 줄 체크 못 함"
    else:
        clear_point(rr, ctx, check_header(bottom, "주문매핑 하단"), "주문매핑 하단 머리글 체크 칸")
        n = rr.select_all_and_verify("하단", ctx.hwnd, bottom, BOTTOM_ID_COLUMNS)
        head = f"하단 {n or 0}줄 전체선택"
    no_popup(rr, ctx, "하단 전체선택")
    checked = (live != ONE or bool(n)) and recheck(rr, bottom, "주문매핑 하단", live)
    split = rr.find_by_text(page, SALES_SPLIT, control_types=("SplitButton",))
    if split is None:
        raise Stop("failed", f"'{SALES_SPLIT}' 단추를 찾지 못했습니다.")
    what = f"{SALES_SPLIT} ▼"
    if not live:
        return head + hover_menu_item(rr, ctx, split, SALES_ITEM, what, checked) + " - 정상매출은 누르지 않음", False
    if not checked:
        return head + " - 체크가 안 돼 매출처리하지 않음 (확인할 것)", False
    baseline = rr.visible_child_windows(ctx.hwnd)      # 스피너 비교 기준 (원래 코드와 같이 누르기 전)
    note, pressed = press_menu_item(rr, ctx, split, SALES_ITEM, what, confirm=False)
    if not pressed:
        return head + note, False
    return head + note + after_normal_sales(rr, ctx, baseline), True


def after_normal_sales(rr, ctx, baseline):
    """'정상매출' 을 누른 뒤 - 원래 PROCESS module_sales 10~11 단계 그대로 (사용자 10-14: 매출처리 팝업은 원래 규칙).
    메인 창 안 확인·완료 팝업은 [예]/[확인], 따로 뜬 창 팝업은 예/아니오면 [아니오]·그 밖은 [확인] (handle_sales_popups).
    매출처리 실패 문구면 닫고 멈춘다 (뒤 모듈을 돌리지 않는다). 사유에 덧붙일 글."""
    hwnd, notes = ctx.hwnd, []
    time.sleep(1.5)
    win = ctx.window()
    btn = rr.find_popup_ok_button(win)
    if btn is None:
        rr.log("  확인 팝업이 뜨지 않았습니다. 비동기 대기 단계로 넘어갑니다.")
    else:
        failure = rr.find_popup_failure(win)
        rr.ec.ensure_foreground(hwnd)
        btn.click_input()
        if failure:
            raise Stop("stopped", f"매출처리 실패: {failure}")
        rr.log(f"  확인 팝업 -> '{btn.window_text()}' 누름")
        time.sleep(1.5)
    rr.status.note("매출 처리가 끝나기를 기다리는 중")
    rr.probe_spinner(hwnd, baseline)
    result = rr.wait_async_then_confirm(ctx.app, hwnd, baseline)
    if result == "sales_failed":
        raise Stop("stopped", "정상매출이 실패했습니다")
    if result == "timeout":
        rr.log(f"  확인할 것: 정상매출 대기 시간({rr.ASYNC_MAX_WAIT_SECONDS}초)을 넘었습니다")
        notes.append("대기 시간 초과 (확인할 것)")
    time.sleep(2)
    failure, _ = rr.handle_sales_popups(ctx.pid, hwnd, {})
    if failure:
        raise Stop("stopped", f"매출처리 실패: {failure}")
    win = ctx.window()
    extra = rr.find_popup_ok_button(win)
    if extra is not None:
        failure = rr.find_popup_failure(win)
        rr.ec.ensure_foreground(hwnd)
        extra.click_input()
        if failure:
            raise Stop("stopped", f"매출처리 실패: {failure}")
        rr.log(f"  추가 팝업 -> '{extra.window_text()}' 누름")
    return f" (완료{'' if result != 'no_popup' else ' - 팝업 없음'}{', ' + ', '.join(notes) if notes else ''})"


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
    try:
        r = goto_screen(rr, ctx, HOLD_TAB, HOLD_ICON, lambda: rr.goto_hold_screen(ctx))
    except Stop as e:
        return e.result, str(e)
    if r == "absent":
        return "failed", "물류대기 아이콘(lcg_HoldLogistics)이 없습니다 - 이 ERPia 의 화면 구성을 확인하세요."
    if r != "ok":
        return "failed", r
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
    if not rr.click_subtab(ctx.app, ctx.hwnd, rr.STOCK_GENERAL_TAB_NAME):   # 못 가면 다른 서브탭('상품별 재고검토')의 조회·저장을 누르게 된다
        raise Stop("failed", f"물류대기 '{rr.STOCK_GENERAL_TAB_NAME}' 탭을 찾지 못해 조회·저장하지 않습니다.")
    page = visible_page(ctx)        # 떠 있는 화면 안만 훑는다
    query, tables = onscreen_button(page, "조회(F)"), rr.get_onscreen_tables(page)
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
    if not check_rows(rr, ctx, grid, "물류대기", live):    # 머리글 자리 확인·팝업 확인은 다른 단계와 같다
        raise Stop("failed", "물류대기 첫 줄만 체크하지 못했습니다 (1건) - 저장하지 않음." if live == ONE
                   else "물류대기 전체선택(머리글 체크)에 실패했습니다.")
    no_popup(rr, ctx, "물류대기 전체선택")
    save = onscreen_button(visible_page(ctx), "저장(S)")
    if save is None:
        raise Stop("failed", "물류대기 '저장(S)' 단추를 찾지 못했습니다.")
    again = recheck(rr, grid, "물류대기", live)
    if live and not again:
        raise Stop("failed", "물류대기 저장 직전 다시 보니 체크가 맞지 않아 저장하지 않음 (확인할 것).")
    if not live:
        hover(rr, ctx, save, "물류대기 '저장(S)'", True)
        return "skipped", f"[{tag}] 물류대기 조회 -> 전체선택 (저장은 누르지 않음)" + ("" if again else RECHECK_NOTE)
    before = popup_windows(rr, ctx)
    rr.log("  [실행] 물류대기 '저장(S)' 누름")
    click(rr, ctx, save, "물류대기 '저장(S)'")
    texts = confirm_popups(rr, ctx, "물류대기 저장", grid, idle, before)
    return "done", f"[{tag}] 물류대기 조회 -> {'첫 줄만 체크' if live == ONE else '전체선택'} -> 저장" + popup_note(texts)


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
        fixed = ensure_query(rr, ctx, "Wms", WMS_FORM, lambda: reopen_menu(rr, ctx, WMS_MENU))   # 회차마다 (사용자 10-13)
        done = [simple_stage(rr, ctx, WMS_FORM, *stage, live=live) for stage in WMS_STAGES]
        if fixed:
            done.insert(0, ("조회 조건 기본값으로 고침: " + ", ".join(fixed), False))
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
    detail = str(e).strip().splitlines()[0][:120] if str(e).strip() else ""
    return "failed", f"UI 오류: {type(e).__name__}" + (f" - {detail}" if detail else "")   # 웹에도 원인이 보이게


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
    checked = (check_rows(rr, ctx, ctl["gridCtrl_List"], "4-1 매출전표", live)
               and recheck(rr, ctl["gridCtrl_List"], "4-1 매출전표", live))
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
    marks, bad = mark_rows(rr, ctx, ctl["gridCtrl_List"], count, slip_target, limit=1 if live == ONE else None)
    targets = sum(1 for v in marks.values() if v == "선택")
    rr.log(f"  매출전표: 그리드 {len(marks)}줄 - 넘길 줄(검토 빈 칸) {targets}줄{f', 못 맞춘 줄 {len(bad)}' if bad else ''}")
    rr.status.note(f"매출전표 {count}건 / {len(marks)}줄 - 넘길 줄 {targets}")
    head += f" / 넘길 줄 {targets}" + (f" (못 맞춘 줄 {len(bad)} - 넘기지 않음)" if bad else "")
    held = bool(not targets or bad) or marks_held(rr, ctl["gridCtrl_List"], marks, SLIP_SEND)   # 화살표 직전 다시 보기
    head += "" if held else RECHECK_NOTE
    note, sent = press_arrow(rr, ctx, ctl, "btn_FirstSend", SLIP_SEND, bool(targets) and not bad and held, targets, live)
    return head + note, pressed or sent


def simple_stage(rr, ctx, form_id, step, dash_id, arrow_id, check_all, what, live=False):
    """단계 하나: 조회 -> (건수가 있으면) 머리글로 전체 체크 -> 화살표. (사유 한 줄, 눌렀는가).
    리허설은 화살표에 마우스만. 실행은 대상이 있고(체크 칸이 있는 단계는 전체 체크가 됐고) 단추가 켜져 있을 때만 누른다.
    체크는 다음 단계를 조회하면 풀리므로 되돌리지 않는다."""
    rr.status.step(step)
    count, ctl = open_stage(rr, ctx, form_id, dash_id)
    label = what.split(" →")[0]
    first = bool(count and check_all) and check_rows(rr, ctx, ctl["gridCtrl_List"], label, live)
    checked = first and recheck(rr, ctl["gridCtrl_List"], label, live)
    want = bool(count) and (checked or not check_all)
    # 실행 '1건' 은 체크 칸이 있는 단계만 한 줄 - 체크 칸이 없는 4-4·5-4 는 그 단계 건을 모두 넘긴다 (사용자 10-13)
    one = live == ONE and check_all
    note, pressed = press_arrow(rr, ctx, ctl, arrow_id, what, want, 1 if one else count, live)
    return (f"{label} {count}건" + (" 중 첫 줄 1건" if one and pressed else "")
            + (RECHECK_NOTE if first and not checked else "") + note), pressed


def check_rows(rr, ctx, grid, label, live):
    """실행 '1건' 이면 첫 줄 하나만, 아니면(리허설 포함) 머리글로 전체 체크. 됐는가."""
    return check_one_row(rr, ctx, grid, label) if live == ONE else check_all_rows(rr, ctx, grid, label)


def check_one_row(rr, ctx, grid, label):
    """실행 '1건' (실데이터 시험, 사용자 10-13): 맨 위로 올려 첫 줄 하나만 체크한다. 됐는가.
    조회 직후라 체크가 모두 풀려 있어야 한다 (조회하면 풀린다 - 10-13 실측). 보이는 줄에 이미 체크된 것이 있으면
    누르지 않는다 - 그 줄도 함께 넘어간다. 누른 뒤 그 줄만 '선택' 인지 다시 읽어 본다."""
    check_header(grid, label)       # 체크 칸이 있는 그리드인지 (없으면 멈춘다)
    front(rr, ctx, f"{label} 그리드 스크롤")     # 스크롤 단추는 rr 도우미가 누른다 (잠김·포커스는 여기서 한 번 본다)
    rr.grid_scroll_to_top(ctx.hwnd, grid)
    rows = settled_rows(rr, grid, first=1)
    states = {n: rr.legacy_value(c[CHECK_COL]) for n, c in rows.items() if CHECK_COL in c}
    # 보이는 줄 중 가장 위 (사용자 10-13). 못 읽은 체크 값이 있으면 이미 체크된 줄인지 몰라 누르지 않는다
    if not states or any(v != "선택안됨" for v in states.values()):
        rr.log(f"  확인할 것: {label} - 첫 줄만 체크하려는데 줄이 없거나, 이미 체크됐거나 못 읽은 줄이 있어 누르지 않음 ({states})")
        return False
    first = min(states)
    cell = rows[first][CHECK_COL]
    no_popup(rr, ctx, f"{label} {first}행 체크 전")
    click(rr, ctx, cell, f"{label} {first}행 체크 칸")
    deadline = time.time() + CHECK_WAIT_SECONDS
    while rr.legacy_value(cell) != "선택" and time.time() < deadline:
        time.sleep(0.2)
    no_popup(rr, ctx, f"{label} {first}행 체크")
    others = [n for n, c in rows.items() if n != first and CHECK_COL in c and rr.legacy_value(c[CHECK_COL]) == "선택"]
    ok = rr.legacy_value(cell) == "선택" and not others
    rr.log(f"  [1건] {label}: {first}행만 체크 - {'됨' if ok else '실패 (확인할 것)'}"
           + (f", 다른 줄도 체크됨 {others}" if others else ""))
    return ok


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
# ⑥ 운송장번호 전송 - 모든 업체용 패키지 화면 (좌측 아이콘, 폼 이름에 업체가 없다 - docs/wellife-rpa.md 9절).
# 웰라이프 고유 값을 쓰지 않는다. 지금은 웰라이프 실행만 부른다 (rpa_status.SHARED_MODULES)
# ---------------------------------------------------------------------------
INVOICE_TAB = "운송장번호 전송"
INVOICE_FORM = "Frm_Send_TrackingNumber"
INVOICE_ICON = "lcg_InvoiceSend"
INVOICE_SEND = "운송장번호 [전송요청(S)]"


def module_invoice_send(rr, ctx, live=False):
    """⑥ 운송장번호 전송: 화면 열기 -> 조회 -> 전체 체크 -> [전송요청(S)] (invoice_send). 리허설은 [전송요청(S)] 에 마우스만.
    [미전송 완료처리] 등 나머지 단추는 누르지 않는다. 아이콘이 없어도(absent) 건너뛰지 않고 실패다 (물류대기와 같다)."""
    rr.status.step("inv_send_screen")
    try:
        no_popup(rr, ctx, f"'{INVOICE_TAB}' 화면 이동 전")
        front(rr, ctx, f"'{INVOICE_TAB}' 화면 이동")
        r = goto_screen(rr, ctx, INVOICE_TAB, INVOICE_ICON,     # 이미 열린 화면은 그 탭 (SAP·WMS 와 같다)
                        lambda: rr.goto_screen_by_icon(ctx, INVOICE_ICON, INVOICE_TAB, INVOICE_TAB))
        if r == "absent":
            return "failed", f"'{INVOICE_TAB}' 아이콘({INVOICE_ICON})이 없습니다 - 이 ERPia 의 화면 구성을 확인하세요."
        if r != "ok":
            return "failed", r
        rr.status.step("inv_send")
        return invoice_send(rr, ctx, live)
    except Stop as e:
        return e.result, str(e)
    except Exception as e:
        return ui_error(rr, e)


def invoice_send(rr, ctx, live):
    """조회(F) -> (줄이 있으면) 머리글로 전체 체크 -> [전송요청(S)]. 조회 조건은 화면 기본값 그대로 (배송일 기간·미전송).
    실행은 전체 체크가 됐고 단추가 켜져 있을 때만 누르고 팝업을 [예]/[확인] 으로 넘긴다 (press_arrow).
    체크는 되돌리지 않는다 (다음 조회로 풀린다). (결과, 사유)."""
    tag = mode_tag(live)
    fixed = ensure_query(rr, ctx, "InvoiceSend", INVOICE_FORM, lambda: reopen_icon(rr, ctx))   # 조회 조건 기본값 (사용자 10-13)
    ctl = controls(rr, ctx, INVOICE_FORM)
    query, grid = ctl.get("btn_Search"), ctl.get("gridCtrl_List")
    if query is None or grid is None:
        raise Stop("failed", f"'{INVOICE_TAB}' 조회(F) 단추(btn_Search)나 그리드(gridCtrl_List)를 찾지 못했습니다.")
    idle = rr.grid_overlay_count(ctx.hwnd, grid)
    no_popup(rr, ctx, f"'{INVOICE_TAB}' 조회 전")
    click(rr, ctx, query, f"'{INVOICE_TAB}' 조회(F)")
    time.sleep(2)     # 스피너가 뜨기 전에 '끝' 으로 보지 않게 (물류대기 조회와 같다)
    if not rr.wait_grid_spinner_gone(ctx.hwnd, grid, idle, label=INVOICE_TAB, max_wait=QUERY_WAIT_SECONDS):
        raise Stop("failed", f"'{INVOICE_TAB}' 조회가 {QUERY_WAIT_SECONDS}초 안에 끝나지 않았습니다.")
    no_popup(rr, ctx, f"'{INVOICE_TAB}' 조회")
    count = count_rows(rr, ctx, grid)
    rr.log(f"  {INVOICE_TAB}: 그리드 {count}줄")
    rr.status.note(f"운송장 {count}건")
    if not count:
        return "no_target", f"[{tag}] 운송장 0건 - 전송할 것 없음" + query_note(fixed)
    checked = check_rows(rr, ctx, grid, INVOICE_TAB, live)
    ctl = controls(rr, ctx, INVOICE_FORM)
    # 누르기 직전에 체크를 다시 본다 - 새로 잡은 그리드로 (조회가 늦게 끝나 그리드가 새로 그려지면 체크가 풀린다)
    checked = checked and recheck(rr, ctl.get("gridCtrl_List") or grid, INVOICE_TAB, live)
    note, pressed = press_arrow(rr, ctx, ctl, "btn_SendRequest", INVOICE_SEND, checked, 1 if live == ONE else count, live)
    head = f"[{tag}] 운송장 {count}건" + (" 중 첫 줄 1건" if live == ONE and pressed else "") + (
        "" if checked else " - 체크가 안 돼 전송하지 않음 (확인할 것)")
    if not live:
        head += " - 전송요청은 누르지 않음"
    return ("done" if pressed else "skipped"), head + note + query_note(fixed)


def query_note(fixed):
    return f" (조회 조건 기본값으로 고침: {', '.join(fixed)})" if fixed else ""


def reopen_icon(rr, ctx):
    """⑥ 다시 열기 - 좌측 아이콘 (조회 조건을 화면 기본값으로 되돌릴 때)."""
    r = goto_screen(rr, ctx, INVOICE_TAB, INVOICE_ICON, lambda: rr.goto_screen_by_icon(ctx, INVOICE_ICON, INVOICE_TAB, INVOICE_TAB))
    if r != "ok":
        raise Stop("failed", f"'{INVOICE_TAB}' 화면을 다시 열지 못했습니다 ({r}).")


def reopen_menu(rr, ctx, menu):
    """메뉴 검색으로 다시 열기 (⑤ - 조회 조건을 화면 기본값으로 되돌릴 때)."""
    ok, reason = goto_screen_by_menu(rr, ctx, menu)
    if not ok:
        raise Stop("failed", f"'{menu}' 화면을 다시 열지 못했습니다: {reason}")


def rows_checked(rr, grid, one=False):
    """보이는 줄이 있고 모두 체크돼 있는가 (칸 값 '선택'). one 이면 보이는 줄 중 꼭 하나만 체크돼 있는가 (실행 '1건')."""
    states = [rr.legacy_value(c[CHECK_COL]) for c in rr.grid_rows(grid).values() if CHECK_COL in c]
    if one:
        return states.count("선택") == 1
    return bool(states) and all(s == "선택" for s in states)


RECHECK_NOTE = " (누르기 직전 다시 보니 체크가 맞지 않음 - 확인할 것)"


def recheck(rr, grid, label, live):
    """누르기 직전 다시 보기 (사용자 10-13: 누르는 곳 모두). 체크한 뒤 조회가 늦게 끝나 그리드가 새로 그려지면 체크가
    풀린다 - 풀린 채로 저장·화살표·전송을 누르지 않게. 리허설도 같은 것을 읽어 '실행이었다면 누르지 않음' 을 남긴다."""
    ok = rows_checked(rr, grid, one=live == ONE)
    if not ok:
        rr.log(f"  확인할 것: {label} - 누르기 직전 다시 보니 체크가 맞지 않음"
               f" ({'누르지 않음' if live else '리허설 - 실행이었다면 누르지 않음'})")
    return ok


def marks_held(rr, grid, marks, label):
    """4-2: 화살표 직전, 보이는 줄의 체크가 맞춘 값(marks: {행 번호: '선택'/'선택안됨'}) 그대로인가."""
    seen = {n: rr.legacy_value(c[CHECK_COL]) for n, c in rr.grid_rows(grid).items() if CHECK_COL in c and n in marks}
    off = sorted(n for n, v in seen.items() if v != marks[n])
    if not seen or off:
        rr.log(f"  확인할 것: {label} - 누르기 직전 다시 보니 체크가 맞춘 값과 다름 (행 {off or '못 읽음'})")
    return bool(seen) and not off


def count_rows(rr, ctx, grid):
    """그리드 줄 수. UIA Grid 패턴이 없어(10-13 실측) 행 번호(스크롤해도 이어지는 절대 번호)로 센다 - 세로 스크롤바가
    있으면 맨 위에서부터 페이지를 넘기며 (키보드는 쓰지 않는다)."""
    if not rr.grid_rows(grid):
        return 0
    if rr.grid_vertical_scrollbar(grid) is None:
        return max(settled_rows(rr, grid), default=0)
    front(rr, ctx, "그리드 스크롤")     # 스크롤 단추는 rr 도우미가 누른다 (잠김·포커스는 여기서 한 번 본다)
    rr.grid_scroll_to_top(ctx.hwnd, grid)
    rows, last = settled_rows(rr, grid, first=1), 0
    for _ in range(MAX_PAGES):
        last = max(last, max(rows, default=0))
        rows = next_page(rr, ctx, grid, rows)
        if rows is None:
            return last
    raise Stop("failed", f"그리드가 {MAX_PAGES}페이지를 넘어 끝까지 못 셈")


# ---------------------------------------------------------------------------
# 조회 조건 기본값 - 반복 화면(⑤ WMS·⑥ 운송장)은 회차마다 조회 전에 기본값인지 보고, 아니면 고쳐서 조회한다 (사용자 10-13).
# 기본값은 ERPia 를 새로 연 화면의 값 (10-14 개발기 실측, docs/wellife-rpa.md 9.4). 날짜는 오늘부터의 일 수 (-10 = 10일 전).
# 설정 QueryDefaults.<화면>.<키> 가 있으면 그 값 (웹에는 안 보인다). 'fixed' 는 목록 창이 복잡해(체크 목록·상품) 고치지
# 않고, 기본값이 아니면 화면을 닫고 다시 연다 (사용자 10-14). 체크 상자 '출고대기만' 은 UIA·MSAA 로 상태가 안 읽혀
# 컨트롤이 그린 그림(PrintWindow)으로 본다 - 애매하면 화면을 다시 연다.
# ---------------------------------------------------------------------------
QUERY_SECTION = "QueryDefaults"
QUERY_CONDITIONS = {      # 화면 -> (설정 키, auto_id, 종류, 기본값)
    "InvoiceSend": (
        ("Sales", "ccc_Sales", "fixed", "매출구분 : 전체"),
        ("Delivery", "ccc_Delivery", "fixed", "택배사 : 전체"),
        ("UnstoringOnly", "chk_UnstoringStand", "check", "N"),
        ("DateBasis", "cboCondition", "combo", "배송일"),
        ("DateFrom", "dateFrom", "date", -10),
        ("DateTo", "dateTo", "date", 0),
        ("SendStatus", "ccc_SendorNot", "combo", "미전송"),
        ("SearchField", "cbo_Condition", "combo", "수령자"),
        ("SearchValue", "txt_SearchValue", "text", ""),
    ),
    "Wms": (    # cbo_stage 는 단계 단추가 바꾼다. '건식상품 제외'(chk_Dryfood) 는 건드리지 않는다 (사용자 10-07)
        ("Sales", "cbo_CustSiteCode", "fixed", "매출구분 : 전체"),
        ("Goods", "cbo_customCtrlSelectorGoods", "fixed", "상품 : 전체"),
        ("DateBasis", "cboCondition", "combo", "납품예정일"),
        ("DateFrom", "dateFrom", "date", 1),        # 내일 ~ 내일 (사용자 10-14)
        ("DateTo", "dateTo", "date", 1),
        ("SearchField", "cbo_Condition", "combo", "PO번호(다중)"),
        ("SearchValue", "txt_SearchValue", "text", ""),
        ("Delivery", "cbo_delivery", "combo", "(전체)"),
    ),
}
CHECKED_AT, UNCHECKED_BELOW = 0.25, 0.05   # 체크 상자 안쪽의 색 있는 점 비율 (10-14 실측: 체크 0.551, 안 체크 0.000 - 포커스와 상관없이)


def query_defaults(rr, screen):
    """[(키, auto_id, 종류, 기본값)]. 설정에 같은 키가 있으면 그 값 ('fixed' 는 늘 전체 - 고치지 않고 화면을 다시 열므로).
    값 모양이 틀리면 RuntimeError (설정 오류)."""
    conf = (rr.pl.load_settings().get(QUERY_SECTION) or {}).get(screen) or {}
    out = []
    for key, aid, kind, default in QUERY_CONDITIONS[screen]:
        want = default if kind == "fixed" else conf.get(key, default)
        if (kind == "date" and not isinstance(want, int)) or (kind == "check" and want not in ("Y", "N")) \
                or (kind in ("combo", "text") and not isinstance(want, str)):
            raise RuntimeError(f"{rr.pl.config_name()} 의 '{QUERY_SECTION}.{screen}.{key}' 값이 틀립니다: {want!r}")
        out.append((key, aid, kind, want))
    return out


def date_days(value, today=None):
    """날짜 칸 값 '2026년 10월 4일 일요일' (또는 2026-10-04) -> 오늘부터의 일 수. 못 읽으면 None."""
    m = re.search(r"(\d{4})\s*[년.-]\s*(\d{1,2})\s*[월.-]\s*(\d{1,2})", value or "")
    if not m:
        return None
    try:
        day = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
    return (day - (today or datetime.date.today())).days


def check_state(ratio):
    """체크 상자 안쪽의 색 있는 점 비율 -> 'Y' / 'N' / None (애매함)."""
    if ratio is None:
        return None
    return "Y" if ratio >= CHECKED_AT else "N" if ratio < UNCHECKED_BELOW else None


def box_ink(raw, w, h):
    """BGRA 그림(한 줄 w 점)에서 체크 상자 안쪽의 색 있는 점 비율. 상자는 칸 높이의 65% 정사각형, 왼쪽·세로 가운데
    (10-14 실측: 높이 20 -> (1,3)~(13,15), 테두리 2점). 체크 안 됨은 안쪽이 흰색, 체크는 주황 체크(마우스가 올라가면 어둡게)."""
    s = round(h * 0.65)
    x0, y0 = max(1, round(h * 0.05)), (h - s) // 2
    m = max(3, round(s * 0.23))
    pts = [(x, y) for y in range(y0 + m, y0 + s - m) for x in range(x0 + m, x0 + s - m)]
    if not pts or x0 + s > w:
        return None

    def colored(x, y):
        b, g, r = raw[(y * w + x) * 4:(y * w + x) * 4 + 3]
        return max(r, g, b) - min(r, g, b) > 40 or (r + g + b) / 3 < 200
    return sum(1 for x, y in pts if colored(x, y)) / len(pts)


def glyph_ratio(rr, el):
    """체크 상자가 스스로 그린 그림(PrintWindow - 가려져도·왼쪽 모니터여도 같다)의 상자 안쪽 색 있는 점 비율. 못 읽으면 None.
    UIA·MSAA 로는 체크 상태가 안 나온다 (10-14 실측 - 포커스만 바뀐다). 마우스가 올라가 있으면 그림이 달라 먼저 치운다."""
    import ctypes
    import win32ui
    try:
        hwnd = el.element_info.handle
        if ctypes.windll.user32.IsHungAppWindow(rr.win32gui.GetAncestor(hwnd, 2)):
            return None     # 응답 없는 ERPia 에 PrintWindow 를 보내면 끝없이 기다린다 (제한 시간이 없다)
        l, t, r, b = rr.win32gui.GetWindowRect(hwnd)
        w, h = r - l, b - t
        mouse.move(coords=(r + 30, (t + b) // 2))     # 컨트롤 밖 (마우스만 - 누르지 않는다)
        time.sleep(0.2)
        hdc = rr.win32gui.GetWindowDC(hwnd)
        src = win32ui.CreateDCFromHandle(hdc)
        mem = src.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(src, w, h)
        mem.SelectObject(bmp)
        try:
            if not ctypes.windll.user32.PrintWindow(hwnd, mem.GetSafeHdc(), 0):
                return None
            return box_ink(bmp.GetBitmapBits(True), w, h)
        finally:
            mem.DeleteDC()
            src.DeleteDC()
            rr.win32gui.ReleaseDC(hwnd, hdc)
            rr.win32gui.DeleteObject(bmp.GetHandle())
    except Exception:
        return None


def cond_value(rr, ctl, aid, kind):
    """조회 조건의 지금 값 (기본값과 같은 모양). 컨트롤이 없거나 못 읽으면 None."""
    el = ctl.get(aid)
    if el is None:
        return None
    if kind == "date":
        box = next(iter(el.descendants(control_type="ComboBox")), None)
        return None if box is None else date_days(rr.legacy_value(box))
    if kind == "check":
        return check_state(glyph_ratio(rr, el))
    if kind == "text":      # 빈 칸은 Legacy Value 가 아예 없어 못 읽은 것과 구분되지 않는다 - ValuePattern 은 빈 칸이 ''
        try:
            return el.iface_value.CurrentValue or ""
        except Exception:
            return None     # 못 읽음 -> 기본값으로 다시 써 보고 다시 읽어 확인한다
    value = rr.legacy_value(el)
    if not value and kind == "fixed":     # 매출구분·상품은 안쪽 popEdit 에 글자가 있다
        edit = next((d for d in el.descendants(control_type="Edit") if d.element_info.automation_id == "popEdit"), None)
        value = rr.legacy_value(edit) if edit is not None else None
    if kind == "combo" and value and " : " in value:      # '택배사 : (전체)' -> '(전체)'
        value = value.split(" : ", 1)[1]
    return value


def ensure_query(rr, ctx, screen, form_id, reopen):
    """조회(단계 단추) 직전: 조회 조건이 기본값인가 보고, 아니면 고친다. 고친 것 목록 (로그에도). 맞추지 못하면 멈춘다
    (조회하지 않음). reopen(): 화면을 다시 여는 함수 - 'fixed' 가 다르거나 체크 상자가 애매할 때 한 번만."""
    try:
        conds = query_defaults(rr, screen)
    except RuntimeError as e:
        raise Stop("failed", f"설정 오류: {e}") from None
    changed = []
    for attempt in range(2):
        ctl = controls(rr, ctx, form_id)
        stale = [k for k, aid, kind, want in conds
                 if kind == "fixed" and cond_value(rr, ctl, aid, kind) != want
                 or kind == "check" and cond_value(rr, ctl, aid, kind) is None]
        if not stale:
            break
        if attempt:
            raise Stop("failed", f"조회 조건 {', '.join(stale)} 이(가) 화면을 다시 열어도 기본값이 아니어서 조회하지 않음.")
        rr.log(f"  조회 조건 {', '.join(stale)} 이(가) 기본값이 아니거나 못 읽어 화면을 닫고 다시 엽니다")
        close_screen(rr, ctx, ctl, form_id)
        reopen()
        changed.append(f"화면 다시 열기({', '.join(stale)})")
    for key, aid, kind, want in conds:
        if kind == "fixed":
            continue
        now = cond_value(rr, ctl, aid, kind)
        if now == want:
            continue
        set_cond(rr, ctx, ctl, key, aid, kind, want)
        ctl = controls(rr, ctx, form_id)
        got = cond_value(rr, ctl, aid, kind)
        if got != want:
            if kind == "check":     # 눌렀는데 그림이 기대와 다르다 - 그림을 잘못 읽는 PC 일 수 있다. 켠 채 남기지 않게 화면을 다시 열어 둔다
                close_screen(rr, ctx, ctl, form_id)
                reopen()
            raise Stop("failed", f"조회 조건 {key} 를 기본값({want!r})으로 맞추지 못해 조회하지 않음 (지금 {got!r}"
                       + (" - 화면을 다시 열어 두었다, 체크 상자 그림을 이 PC 에서 확인할 것" if kind == "check" else "") + ").")
        changed.append(f"{key} {now!r}→{want!r}")
    rr.log(f"  조회 조건({screen}): " + ("기본값 그대로" if not changed else "기본값으로 고침 - " + ", ".join(changed)))
    return changed


def set_cond(rr, ctx, ctl, key, aid, kind, want):
    """조회 조건 하나를 기본값으로. 키는 포커스가 그 칸 안일 때만 보낸다 (메뉴 검색과 같다)."""
    el = ctl[aid]
    what = f"조회 조건 {key}"
    no_popup(rr, ctx, f"{what} 바꾸기 전")
    if kind == "check":
        click(rr, ctx, el, what)            # 누를 때마다 켬/끔
        time.sleep(0.6)
        return
    if kind == "combo":
        pick_item(rr, ctx, el, want, what)
        return
    if kind == "date":      # 전체 선택 -> 2026-10-04 -> Tab (10-14 실측: 값이 '2026년 10월 4일 일요일' 이 된다)
        box = next(iter(el.descendants(control_type="ComboBox")))
        edit = next(iter(box.descendants(control_type="Edit")))
        keys = "^a" + (datetime.date.today() + datetime.timedelta(days=want)).strftime("%Y-%m-%d") + "{TAB}"
    else:
        edit = next(iter(el.descendants(control_type="Edit")), el)
        keys = "^a{BACKSPACE}" + rr.ec.literal_keys(want) + "{TAB}"
    click(rr, ctx, edit, what)
    if not _focus_in(rr, aid):
        raise Stop("failed", f"{what}: 칸에 포커스가 오지 않아 입력하지 않았습니다 (포커스: {_focus_chain(rr)[:2]}).")
    edit.type_keys(keys, with_spaces=True)
    time.sleep(0.6)


def pick_item(rr, ctx, combo, item, what):
    """콤보를 눌러 따로 뜬 목록 창에서 그 이름의 항목을 누른다. 항목이 없으면 목록을 ESC 로 닫고 멈춘다."""
    before = _menu_windows(rr, ctx)
    click(rr, ctx, combo, what)
    found, deadline = None, time.time() + DROPDOWN_WAIT_SECONDS
    while found is None and time.time() < deadline:
        time.sleep(0.2)
        for h in _menu_windows(rr, ctx) - before:
            try:
                items = rr.Desktop(backend="uia").window(handle=h).wrapper_object().descendants(control_type="ListItem")
            except Exception:
                continue    # 그새 닫힌 창 (그림자 창 등)
            hit = next((i for i in items if i.window_text() == item), None)
            if hit is not None:
                found = (h, hit)
                break
    opened = _menu_windows(rr, ctx) - before
    if found is None:
        _close_menu(rr, ctx, opened, what)
        raise Stop("failed", f"{what}: 목록에 '{item}' 이(가) 없어 바꾸지 않고 멈춤")
    h, hit = found
    r = hit.rectangle()
    pt = ((r.left + r.right) // 2, (r.top + r.bottom) // 2)
    if rr.ec.screen_locked():           # 목록을 연 사이에 잠겼으면 누르지 않는다 (front() 는 목록을 닫을 수 있어 잠김만 본다)
        raise Stop("stopped", f"{what}: 윈도우 화면이 잠겨 있어 누르지 않고 멈춤")
    if _top_window(rr, pt) != h:        # 목록 창이 맨 위일 때만 (다른 창이 덮었으면 그것이 눌린다)
        _close_menu(rr, ctx, opened, what)
        raise Stop("failed", f"{what}: 목록 항목 자리를 다른 창이 덮고 있어 누르지 않고 멈춤")
    hit.click_input(coords=pt, absolute=True)
    deadline = time.time() + DROPDOWN_WAIT_SECONDS
    while any(_shown(rr, w) for w in opened) and time.time() < deadline:
        time.sleep(0.2)
    _close_menu(rr, ctx, opened, what)     # 이미 닫혔으면 아무것도 안 한다


def close_screen(rr, ctx, ctl, form_id):
    """화면의 [닫기(X)](btn_Close) - 팝업 없이 탭이 닫힌다 (10-14 ⑥ 실측). 닫혔는지(폼이 안 보이는지) 본다."""
    btn = ctl.get("btn_Close")
    if btn is None:
        raise Stop("failed", f"화면({form_id})의 [닫기(X)] 단추를 찾지 못해 다시 열지 않음")
    no_popup(rr, ctx, f"화면({form_id}) 닫기 전")
    click(rr, ctx, btn, f"화면({form_id}) [닫기(X)]")
    deadline = time.time() + STAGE_WAIT_SECONDS
    while True:
        time.sleep(0.5)
        no_popup(rr, ctx, f"화면({form_id}) 닫기")
        try:
            controls(rr, ctx, form_id)
        except Stop:
            return      # 화면이 사라졌다
        if time.time() > deadline:
            raise Stop("failed", f"화면({form_id}) [닫기(X)] 를 눌렀으나 닫히지 않았습니다.")


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
    단계마다 보이는 단추가 달라서(지정·건식상품 제외) 단계를 연 뒤 다시 부른다.
    창 전체를 훑지 않는다 (10-14 실측: 화면 7~8개가 열려 있으면 요소 약 3,400개 - 한 번에 10~14초, 단계마다 여러 번):
    폼은 떠 있는 화면 안에서 자식을 따라 찾고, 폼 안도 자식을 따라 보되 그리드(Table) 속 칸은 내려가지 않는다."""
    win = ctx.window()
    wr = win.rectangle()

    def shown(c):
        r = c.rectangle()
        return r.width() > 0 and r.height() > 0 and wr.left <= r.left < wr.right and wr.top <= r.top < wr.bottom

    form = None
    try:
        form = _find_form(ctx, form_id, shown)
    except Exception:
        form = None
    if form is None:            # 못 찾으면 예전처럼 창 전체에서
        for c in win.descendants(control_type="Pane"):
            try:
                if c.element_info.automation_id == form_id and shown(c):
                    form = c
                    break
            except Exception:
                continue
    if form is None:
        raise Stop("failed", f"화면({form_id})을 찾지 못했습니다.")
    out, stack = {}, [form]
    while stack:
        try:
            kids = stack.pop().children()
        except Exception:
            continue
        for c in kids:
            try:
                aid = c.element_info.automation_id
                if aid and aid not in out and shown(c):
                    out[aid] = c
                if c.element_info.control_type != "Table":     # 그리드 칸(수백~수천)은 내려가지 않는다
                    stack.append(c)
            except Exception:
                continue
    return out


def _find_form(ctx, form_id, shown):
    """떠 있는 화면 안에서 자식을 따라 그 폼 (얕은 곳부터 FORM_DEPTH 까지). 없으면 None."""
    level = [visible_page(ctx)]
    if level[0].element_info.automation_id == form_id:
        return level[0]
    for _ in range(FORM_DEPTH):
        below = []
        for el in level:
            for c in el.children():
                if c.element_info.automation_id == form_id and shown(c):
                    return c
                below.append(c)
        level = below
    return None


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
    """팝업(예/아니오/확인 단추)이 떠 있으면 누르지 않고 멈춘다.
    단추 찾기는 창 전체를 훑어 수 초 걸린다 (10-14 실측: 단계마다 4~5번). ERPia 팝업은 메인 창의 자식 창으로 뜨므로
    (원래 PROCESS 의 PopupGate 와 같은 근거) 보이는 자식 창 목록(win32 - 거의 0초)이 마지막으로 '팝업 없음' 을
    확인했을 때와 같으면 다시 훑지 않는다. 목록을 못 읽으면 늘 훑는다."""
    if getattr(ctx, "pass_popups", False):
        return pass_popups(rr, ctx, after)
    sig = _calm_sig(rr, ctx)
    if sig is not None and getattr(ctx, "calm_children", None) == sig:
        return
    buttons = rr.find_popup_buttons(ctx.window())
    if buttons:
        ctx.calm_children = None
        text = rr.collect_popup_text(buttons[0])
        raise Stop("stopped", f"{after} 뒤 팝업이 떠서 멈춤 (누르지 않음): {text[:200]}")
    # 훑는 사이에 창 구성이 바뀌었으면(막 뜨는 팝업) 기억하지 않는다 - 다음에 다시 훑는다
    ctx.calm_children = sig if sig is not None and sig == _calm_sig(rr, ctx) else None


def pass_popups(rr, ctx, after):
    """② 주문매핑 (사용자 2026-10-15): 떠 있는 팝업은 예상 못 한 것도 [예](없으면 [확인]) 로 넘기고 이어간다.
    매출처리 실패 문구면 넘긴 뒤 멈춘다. [예]/[확인] 이 POPUP_SETTLE_SECONDS 동안 안 보이는 팝업, MAX_POPUPS 를 넘으면 멈춘다."""
    passed, unknown = 0, None
    while True:
        found = _next_popup(rr, ctx, frozenset())
        if found is None:
            return
        text, button = found
        if button is None:
            unknown = unknown or time.time()
            if time.time() - unknown < POPUP_SETTLE_SECONDS:   # 막 뜬 팝업은 단추가 아직 안 그려졌을 수 있다
                time.sleep(0.3)
                continue
            raise Stop("stopped", f"{after} 뒤 [예]/[확인] 이 없는 팝업이라 멈춤: {text[:200]}")
        unknown = None
        if passed >= MAX_POPUPS:
            raise Stop("stopped", f"{after} 뒤 팝업이 {MAX_POPUPS}개를 넘어 멈춤 (마지막: {text[:200]})")
        front(rr, ctx, f"{after} 팝업")
        rr.log(f"  {after} 뒤 팝업: {text[:300]} -> [{button.window_text()}] 누름")
        button.click_input()
        passed += 1
        if rr.match_sales_failure(text):
            raise Stop("stopped", f"{after} 뒤 매출처리 실패 팝업이라 닫고 멈춤: {text[:200]}")
        time.sleep(0.5)


def _calm_sig(rr, ctx):
    """팝업을 다시 훑을지 가르는 창 구성: 메인 창의 보이는 자식 창(자리 포함) + ERPia 가 따로 띄운 보이는 최상위 창
    (별도 창 팝업은 자식 창 목록에 안 보인다 - run_routine.find_popup_windows). 못 읽거나 자식 창이 하나도 없으면
    (창이 죽음 - visible_child_windows 는 오류를 삼키고 빈 목록을 준다) None - 늘 훑는다."""
    try:
        kids = rr.visible_child_windows(ctx.hwnd)
        if not kids:
            return None
        return ctx.hwnd, frozenset(kids.items()), frozenset(rr.find_popup_windows(ctx.pid, ctx.hwnd))
    except Exception:
        return None


def mark_rows(rr, ctx, grid, expected, want, limit=None):
    """그리드를 위에서부터 한 번만 내려가며, 줄마다 검토 칸을 읽는 대로 체크 칸을 맞춘다 - want(검토 값) 면 '선택',
    아니면 '선택안됨'. 다 읽고 다시 올라가 체크하지 않는다 (사용자 10-08). 행 번호는 스크롤해도 이어지는 절대 번호다
    (10-07 실측: 1~24 -> 페이지 아래로 -> 24~47). 칸 전체가 그리드 안에 보일 때만 누르고(잘린 칸을 누르면 스크롤바에
    떨어진다) 잘린 줄은 다음 페이지에서 맞춘다. 키보드는 쓰지 않는다 (행이 선택되면 아래 그리드가 다시 조회된다).
    limit: '선택' 으로 맞출 줄의 최대 수 (실행 '1건' 은 1 - 위에서부터 먼저 만난 줄). 나머지 대상 줄은 '선택안됨'.
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
            picked = sum(1 for v in out.values() if v == "선택")
            value = "선택" if want(review) and (limit is None or picked < limit) else "선택안됨"
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
    # 방금 내렸으니 스크롤바가 있었다 - 지금 못 읽으면(None·예외) 끝인지 모른다. 끝으로 보면 뒤 줄을 못 본 채
    # 4-2 화살표가 눌릴 수 있어 멈춘다 (사용자 10-13). 스크롤바를 읽었고 '페이지 아래로' 가 없을 때만 끝이다
    try:
        vsb = rr.grid_vertical_scrollbar(grid)
        more = None if vsb is None else any(c.window_text() == "페이지 아래로" for c in vsb.descendants())
    except Exception:
        more = None
    if more is None:
        raise Stop("failed", "페이지를 내렸는데 그리드가 움직이지 않았고 스크롤바도 읽지 못해 멈춤 (끝인지 모름 - 뒤 줄은 못 맞춤)")
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


def press_menu_item(rr, ctx, split, item_text, what, grid=None, confirm=True):
    """실행: [지정] 옆 ▼ 로 내림 메뉴를 열고 item_text 를 누른 뒤 팝업을 [예]/[확인] 으로 넘긴다. (사유 글, 눌렀는가).
    누를 점의 맨 위 창이 그 메뉴 창일 때만 누른다 (다른 창이 덮고 있으면 그것이 눌린다). 항목이 꺼져 있으면 닫고 넘어간다.
    confirm=False 면 누른 뒤 팝업은 부른 쪽이 본다 (② 정상매출 - 원래 PROCESS 의 팝업 규칙)."""
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
    if not confirm:
        return f" -> '{item_text}' 누름", True
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
    """누를 자리에 마우스만 올리고 잠깐 머문다 - 클릭하지 않는다 (리허설).
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
    [예]/[확인] 이 POPUP_SETTLE_SECONDS 동안 안 보이는 팝업, MAX_POPUPS 를 넘는 팝업, CONFIRM_WAIT_SECONDS 안에 안 끝나는
    처리는 멈춘다."""
    texts = []
    deadline = time.time() + CONFIRM_WAIT_SECONDS
    calm = unknown = None
    while time.time() < deadline:
        found = _next_popup(rr, ctx, before)
        if found is not None:
            text, button = found
            if button is None:
                unknown = unknown or time.time()
                if time.time() - unknown < POPUP_SETTLE_SECONDS:   # 아직 그려지는 중일 수 있다 - 다시 본다
                    time.sleep(0.3)
                    continue
                raise Stop("stopped", f"{what}: [예]/[확인] 이 없는 팝업이라 멈춤: {text[:200]}")
            unknown = None
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
        ok, reason = _open_by_menu(rr, ctx, menu)
    except Stop as e:           # 잠긴 화면 / ERPia 를 앞으로 못 가져옴 - 누르지 않고 멈춘 것
        return False, str(e)
    except Exception as e:
        rr.log(f"  메뉴 검색 중 UI 오류: {type(e).__name__}: {e}")
        _clear_search(rr, ctx)
        return False, f"메뉴 검색 중 UI 오류: {type(e).__name__}"
    return ok, (reason if ok else reason + dup_note(ctx))


def _open_by_menu(rr, ctx, menu):
    log = rr.log
    no_popup(rr, ctx, f"'{menu}' 화면 이동 전")   # 앞 화면(③ 물류대기 등)에서 뜬 팝업이 남아 있으면 그 위를 누르지 않게
    # 이미 열린 화면은 메뉴를 눌러도 그 탭으로 가지 않는다 (10-07 실측: 60초 기다리다 사람이 탭을 닫고 다시 열었다)
    went = goto_open_tab(rr, ctx, menu)
    if went is not None:
        return went

    win = ctx.window()
    rr.prefetch_auto_ids(win, ("sch_Menus", "acd_Nav"))
    search, nav = rr.find_by_auto_id(win, "sch_Menus"), rr.find_by_auto_id(win, "acd_Nav")
    if search is None or nav is None:
        return False, "메뉴 검색 칸(sch_Menus)이나 메뉴 트리(acd_Nav)를 찾지 못했습니다."

    log(f"메뉴 검색: '{menu}'")
    with keys(rr):      # 입력부터 메뉴 항목을 누를 때까지 (open_order_copy 와 같은 까닭)
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

    ok, active = wait_tab(rr, ctx, menu)
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
    탭바의 ◀ ▶ × 단추일 수 있다. 같은 이름의 탭이 있는데 그렇지 않으면 멈춘다 (메뉴로는 이미 열린 화면에 못 간다).
    번호 붙은 같은 화면('물류대기 관리 (2)')은 고르지 않는다 - 번호 없는 원래 화면 (사용자 10-14: 원래 화면이 늘 함께 있다).
    이름 끝 공백은 무시한다 (10-14 실측: '물류대기 관리 ')."""
    wr = ctx.window().rectangle()
    found = False
    for t in main_tab_bar(ctx)[1]:
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


# ---------------------------------------------------------------------------
# 화면 이동 - 메인 탭바·좌측 아이콘을 descendants() 로 찾지 않는다. 같은 화면이 번호를 달고 또 열려 있으면
# ('물류대기 관리 (2)') descendants 가 메인 탭바·좌측 아이콘 줄·메뉴 검색 칸을 빠뜨린다 (10-14 개발기 실측: 화면에는 있고
# 자식을 따라가면 다 있다. 원래 함수는 아이콘을 못 찾고 9분 30초 뒤 'absent' - 보통 PROCESS 는 ③ 을 '메뉴 없는 업체' 로 건너뛴다).
# 그래서 이미 열린 화면은 번호 없는 탭을 누르고, 번호 붙은 탭이 있을 때만 아이콘도 자식을 따라 찾는다.
# ---------------------------------------------------------------------------
NUMBERED_TAB = re.compile(r"\s\(\d+\)\s*$")      # 같은 화면을 또 열면 ERPia 가 붙이는 번호
ORDER_TAB, ORDER_ICON = "주문매핑 매출처리", "lcg_OrderCollect"
HOLD_TAB, HOLD_ICON = "물류대기 관리", "lcg_HoldLogistics"


def main_tab_bar(ctx):
    """(메인 탭바 Tab, 그 탭들). 창에서 자식을 따라 얕은 곳부터 보며 처음 만나는 창 안의 Tab (화면 안의 서브탭은
    더 깊다 - 10-14 실측: 메인 4, 물류대기 서브탭 6). 탭바의 이름은 떠 있는 화면 이름이다. 못 찾으면 (None, [])."""
    win = ctx.window()
    wr = win.rectangle()
    level = [win]
    for _ in range(MAIN_TAB_DEPTH):
        below = []
        for el in level:
            for c in el.children():
                if c.element_info.control_type == "Tab":
                    r = c.rectangle()
                    if r.width() > 0 and wr.left <= r.left < wr.right and wr.top <= r.top < wr.bottom:
                        return c, c.children(control_type="TabItem")
                below.append(c)
        level = below
    return None, []


def visible_page(ctx):
    """떠 있는 화면 (메인 탭바와 같은 부모 아래, 창 안에 있는 화면 Pane). 단추·그리드는 이 안에서만 찾는다 -
    창 전체에는 숨은 화면들까지 수천 개가 있다. 못 찾으면 창 (예전처럼 전체)."""
    win = ctx.window()
    try:
        bar, _ = main_tab_bar(ctx)
        wr = win.rectangle()
        for p in (bar.parent().children() if bar is not None else []):
            r = p.rectangle()
            if (p.element_info.control_type == "Pane" and r.width() > 0
                    and wr.left <= r.left < wr.right and wr.top <= r.top < wr.bottom):
                return p
    except Exception:
        pass
    return win


def active_tab(ctx):
    """떠 있는 메인 탭 이름 (못 읽으면 None). 원래 get_active_main_tab 은 descendants 로 가장 큰 Tab 을 고르는데,
    번호 붙은 '물류대기 관리 (2)' 가 떠 있으면 메인 탭바가 빠져 서브탭 '일반' 을 돌려줬다 (10-14 실측)."""
    for t in main_tab_bar(ctx)[1]:
        try:
            if t.is_selected():
                return t.window_text()
        except Exception:
            continue
    return None


def wait_tab(rr, ctx, name, timeout=TAB_WAIT_SECONDS):
    """떠 있는 메인 탭이 name 이 될 때까지 (이름 끝 공백 무시, 번호 붙은 같은 화면은 아님). (됐는가, 마지막 탭 이름)."""
    deadline = time.time() + timeout
    last = None
    while True:
        try:
            last = active_tab(ctx)
        except Exception:
            last = None         # 화면이 바뀌는 순간의 UIA 오류 - 다시 본다
        if last is not None and last.strip() == name:
            return True, last
        if time.time() > deadline:
            return False, last
        time.sleep(0.5)


def numbered_tabs(ctx):
    """번호 붙은 같은 화면 탭 이름들 ('물류대기 관리 (2)'). 못 읽으면 []."""
    try:
        return [t.window_text().strip() for t in main_tab_bar(ctx)[1] if NUMBERED_TAB.search(t.window_text())]
    except Exception:
        return []


def dup_note(ctx):
    """화면 이동 실패 사유에 덧붙일 글 - 번호 붙은 탭이 있으면 그것 때문일 수 있다."""
    dup = numbered_tabs(ctx)
    return f" (같은 화면이 여러 개 열려 있음: {', '.join(dup)} - 번호 붙은 화면을 닫고 다시 실행)" if dup else ""


def find_icon(ctx, key):
    """좌측 아이콘 (이름이 key 인 Pane). 자식을 따라 찾는다 - 화면 영역(sdPnlMain)은 내려가지 않는다. 없으면 None."""
    stack = [ctx.window()]
    while stack:
        for c in stack.pop().children():
            info = c.element_info
            if info.control_type == "Pane" and c.window_text() == key:
                return c
            if info.automation_id != "sdPnlMain":
                stack.append(c)
    return None


def goto_open_tab(rr, ctx, name):
    """이미 열린 name 화면이면 그 탭을 눌러 간다: (True, None) / (False, 사유). 열려 있지 않으면 None."""
    tab = open_tab(rr, ctx, name)
    if tab is None:
        return None
    rr.log(f"'{name}' 화면이 이미 열려 있어 그 탭을 누릅니다: {tab.rectangle()}")
    click(rr, ctx, tab, f"'{name}' 탭")
    ok, active = wait_tab(rr, ctx, name)
    if not ok:
        return False, f"'{name}' 탭을 눌렀으나 그 화면으로 바뀌지 않았습니다 (떠 있는 화면='{active}')."
    rr.log(f"'{name}' 화면으로 이동 확인")
    return True, None


def goto_screen(rr, ctx, name, icon, original):
    """②③⑥ 화면 이동 (좌측 아이콘 화면): 'ok' / 'absent'(아이콘 없음) / 실패 사유 글.
    1) 이미 열린 화면이면 번호 없는 그 탭을 누른다.  2) 번호 붙은 탭이 없으면 원래 아이콘 이동 original()
    ('ok'/'absent'/'failed' 또는 사유 글 - 로그인 직후 창이 다시 만들어지는 경우를 원래 함수가 다룬다).
    3) 번호 붙은 탭이 있으면 원래 함수는 아이콘을 못 찾으므로 자식을 따라 찾은 아이콘을 누른다.
    탭을 읽다가 난 UIA 오류(로그인 직후 등)는 '열려 있지 않음' 으로 보고 원래 함수로 간다."""
    try:
        went = goto_open_tab(rr, ctx, name)
        dup = [] if went is not None else numbered_tabs(ctx)
    except Stop:
        raise
    except Exception as e:
        rr.log(f"  '{name}' 탭을 읽지 못해 원래 화면 이동으로 갑니다: {type(e).__name__}")
        went, dup = None, []
    if went is not None:
        return "ok" if went[0] else went[1]
    if not dup:
        r = original()
        return r if r in ("ok", "absent") else (f"'{name}' 화면으로 이동하지 못했습니다." if r == "failed" else r)
    rr.log(f"  같은 화면이 여러 개 열려 있어({', '.join(dup)}) 좌측 아이콘을 자식을 따라 찾습니다")
    try:
        el = find_icon(ctx, icon)
        if el is None:
            return "absent"
        click(rr, ctx, el, f"'{name}' 아이콘")
        ok, active = wait_tab(rr, ctx, name)
    except Stop:
        raise
    except Exception as e:      # UIA 오류는 실행 전체를 죽이지 않고 이 화면 이동의 실패로 (원래 아이콘 이동과 같다)
        rr.log(f"  '{name}' 아이콘 이동 중 UI 오류: {type(e).__name__}: {e}")
        return f"'{name}' 화면으로 이동하지 못했습니다 (UI 오류: {type(e).__name__})" + dup_note(ctx)
    return "ok" if ok else f"'{name}' 아이콘을 눌렀으나 그 화면으로 바뀌지 않았습니다 (떠 있는 화면='{active}')."


def _ok_or_reason(result):
    """원래 goto_order_screen 의 (ok, 사유) -> 'ok' / 사유."""
    ok, reason = result
    return "ok" if ok else reason


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
    """키보드 포커스가 auto_id 컨트롤이나 그 안쪽(검색 칸의 Edit 등)에 있는가. 누른 직후 바로 안 올 수 있어
    FOCUS_WAIT_SECONDS 동안 다시 본다 (10-19 개발기: 자동 수집이 도는 중 메뉴 검색 칸을 누르고 바로 보면 아직 안 와 있었다)."""
    end = time.time() + FOCUS_WAIT_SECONDS
    while not any(aid == auto_id for aid, _, _ in _focus_chain(rr)):
        if time.time() >= end:
            return False
        time.sleep(0.1)
    return True


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
        with keys(rr):
            click(rr, ctx, search, "메뉴 검색 칸 비우기")   # 잠김·앞 창·덮인 자리를 보고 누른다 (Stop 도 아래에서 로그만)
            if not _focus_in(rr, "sch_Menus"):
                rr.log(f"  메뉴 검색 칸에 포커스가 오지 않아 비우지 않았습니다 (포커스: {_focus_chain(rr)[:2]}).")
                return
            search.type_keys("^a{BACKSPACE}")
    except Exception as e:
        rr.log(f"  메뉴 검색 칸을 비우지 못했습니다(무시): {type(e).__name__}")
