r"""ERPia 정해진 업무 루틴을 처음부터 끝까지 한 번에 실행한다.

모듈 (2026-09-18):
    아래 흐름을 다섯 화면 모듈로 나눠 사용자 설정(RPA_UserConfig.json)의 "Routine" 섹션으로 골라 돌린다.
      Login / Sales / Hold / Logistics / Output  = "Y"(켬) 또는 "N"(끔). 섹션·키가 없으면 켬.
      예: {"Routine": [{"Login": "Y"}, {"Sales": "Y"}, {"Hold": "N"}, {"Logistics": "Y"}, {"Output": "Y"}]}
      Y/N 이 아닌 값이면 아무것도 돌리지 않고 멈춘다 (설정은 정확히 지켜져야 한다).
    - 로그인을 끄면 이미 떠 있는 ERPia 에 붙는다. 물류관리/출력만 켜면 스스로 '물류 관리' 화면으로 간다.
    - 물류관리 모듈이 배송을 만들었으면 배송정보설정은 항상 돈다 (로그인 세션마다 초기화되므로).
      모듈 안 단계는 고를 수 없다. 하단 그리드가 0건이면 모듈 전체가 '대상 없음' 으로 끝난다.
    - 출력 모듈은 이번 실행에서 물류관리가 완료된 경우에만 예전처럼 돈다. 물류관리를 끈 채 출력만
      돌리면 '이미 출력한 배송장' 팝업에서 아니오를 누르고 끝낸다 (중복 인쇄 금지).
      물류관리가 돌았는데 완료가 아니면(대상 없음/실패) 출력은 아무것도 누르지 않는다.
      ** Logistics=N, Output=Y (출력 단독) 조합은 2026-09-18 기준 실측 전이다 - '이미 출력한 배송장'
         팝업의 버튼 구성을 실제로 확인하기 전에는 실운영에서 켜지 말 것. **
    - 물류대기 아이콘이 없는 업체는 물류대기 모듈을 건너뛴다. 아이콘을 눌렀는데 탭이 안 뜨면
      (예전처럼 물류처리로 넘어가지 않고) 실패로 멈춘다.
    - 상태 파일(RPA_STATUS\status_routine.json)에 modules[] / module_flags / progress 를 남긴다.
      module_flags 비트: login=1 sales=2 hold=4 logistics=8 output=16 (완료·대상없음·건너뜀이면 1).

흐름:
1. 자격증명(업체코드/아이디/비밀번호) 로드 - exe 옆 RPA_UserConfig.json 의 LogIn (비밀번호는 잠긴 값을 풀어 쓴다)
2. ERPia 위치 - RPA_UserConfig.json 의 ERPia.ExePath (틀렸으면 설치 기록에서 찾아 고친다. ERPia 가 이미 떠 있으면 안 본다)
3. ERPiaMain.exe가 안 떠있으면 실행하고, 로그인 창이 뜰 때까지 대기
4. 자동 로그인 (2차 인증 팝업/기타 팝업 처리 규칙은 perform_login.login_flow와 동일)
5. '주문매핑 매출처리' 화면으로 이동
6. 좌측 상단 그리드 전체선택 + 검증
7. '가져오기' 버튼에 5초간 마우스 유지 (클릭 없음)
7-1. 엑셀업로드: 바탕화면 ERPIA_AI\ERPIA_AI_EXCEL 폴더에 (nnn)~.xls(x) 파일이 있으면,
    좌측 상단 그리드에서 '사이트코드'가 nnn 인 행의 '엑셀업로드' 셀을 눌러 올린다.
    - 폴더가 없거나 파일이 없으면 통째로 건너뛴다
    - 올린 뒤 오류 팝업이 없으면 ERPIA_AI_EXCEL\완료\YYYYMMDD 로 이동
    - ERPIA_AI_EXCEL\오류 로 이동하는 경우:
      사이트코드 행이 없음 / 그 사이트가 엑셀업로드 미지원('엑셀업로드'!=1) /
      같은 사이트코드 파일이 여럿(최신 1개만 사용) / 업로드 후 오류 팝업이 뜸
    - 자세한 업로드 결과는 화면 우측 상단 로그로 사용자가 확인한다
8. 하단 그리드 전체선택 + 검증
9. '매출처리' 옆 ▼ 클릭 -> '정상매출' 클릭
   - 이 과정에서 '정상매출실패' 팝업이 뜨면 팝업만 닫고 루틴을 중단한다
     (매출이 안 잡힌 채로 물류 단계를 진행하면 안 되기 때문)
10. 확인 팝업이 뜨면 '예/확인' 클릭
11. 비동기 처리(그리드 위 로딩 스피너)가 끝날 때까지 2초 간격으로 확인
    (스피너가 15초 이상 계속 없으면 완료로 판정),
    끝난 뒤 완료 팝업이 뜨면 '예/확인' 클릭
12. 다음 단계인 '물류대기' 화면으로 이동
    - 물류대기 메뉴가 없으면 '물류처리'를 눌러 곧바로 '물류 관리'로 진입하고 13~14를 건너뛴다
      (물류대기는 없을 수 있어도 물류 관리는 항상 존재)
13. 물류대기 처리: 10초 대기
    13-1. '상품별 재고검토' 탭: 조회 -> 스피너가 사라질 때까지 대기
          -> 상단 그리드를 맨 위부터 맨 아래까지 스크롤하며 '부족수량'에 값이 있는 행을 전부 수집
             (STOCK_EXCLUDED_CODES 의 상품코드는 부족수량이 있어도 대상에서 제외)
          -> 각 건마다 그 셀을 클릭 -> 하단 그리드를 상품코드로 오름차순 정렬(헤더 상태로 확정)
             -> 찾기(Ctrl+F)로 그 상품코드 덩어리로 바로 점프(맨 위부터 페이지를 하나씩 내리지 않음)
             -> 덩어리의 첫 행 클릭 + 마지막 행 Shift+클릭 -> 우클릭 '선택영역 체크'
             (정렬이 어긋났거나 찾지 못하면 그 건은 배송보류하지 않고 건너뜀. 한 행씩 체크로 폴백하지 않음)
          -> 체크된 행 위에서 우클릭 '배송보류' (누르는 즉시 DB 저장됨)
          -> (검증 없이) 다음 부족수량 셀로 반복
          -> 전부 끝나면 '일반' 탭으로 복귀
    13-2. '일반' 탭: 조회 -> 상품상태 헤더를 눌러 '내림차순' 확정
          ('정상'이 이 컬럼의 최댓값이라 전부 위로 모이고, 보류 대상은 아래 한 덩어리가 된다)
          -> Ctrl+End 로 맨 아래 이동 -> 마지막 행 클릭(앵커)
          -> 위로 올라가며 '정상' 바로 다음 행을 찾아 Shift+클릭 (비정상 꼬리 구간만 선택)
          -> 우클릭 '선택영역 체크' -> 체크된 행 위에서 우클릭 '배송보류' 실행
          (전 행을 검사하지 않는다. 실운영은 수만 건이라 비용이 비정상 건수에만 비례하게 짰다)
14. 물류대기 마무리: 그리드 전체선택 -> '저장(S)' -> 비동기 대기
    (배송보류 자체는 우클릭 시점에 이미 저장된다. 저장(S)는 별개 역할)
    -> 좌측 '물류처리' 클릭 -> '물류 관리' 메뉴 열림 확인
15. 물류 관리 처리
    15-1. 화면에 들어오자마자 자동/수동(cboBS_Auto_YN)을 설정값대로 맞춘다.
          사용자 설정의 Logistic.cboBS_Auto_YN 이 "A" 또는 "Y" 면 자동, "N" 이면 수동.
          값이 없거나 자동 값이 아니거나 콤보 컨트롤 자체가 화면에 없으면 모두 '수동'으로 본다.
          이 값이 바뀌면 상단 버튼 배치와 상단 그리드 컬럼 구성이 통째로 바뀌므로
          그리드를 잡기 전에 먼저 맞춰야 한다. (업체에 따라 이 콤보가 없을 수 있다)
    15-2. 하단 그리드 조회 완료 대기 -> 하단 그리드 우클릭 '전체선택'
          -> 우클릭 '개별 배송(B)' -> 상단 그리드에 배송 데이터 생성 확인
16. 배송정보설정: 업체(cboTag) / 박스(cboTagAmt) / 구분(cboBeasong_Gu_Apply)을
    사용자 설정의 값으로 고르고 각각 '적용'. 이 값들은 로그인 세션마다 초기화되므로
    매번 명시적으로 설정해야 한다. 실패 시 잘못된 값으로 저장하지 않도록 중단한다.
17. 저장(S): '현재 저장중' 스피너가 사라질 때까지 대기 후 팝업 판정
    - 검증 오류 문구(배송일/연락처/우편번호 미입력 등)가 있으면 팝업을 그대로 두고 루틴 종료
    - 그 외 예/아니오 팝업이면 '예', 안내 팝업이면 '확인'을 누르고 계속
    - 성공하면 상단 그리드에 배송번호(BS...)가 생겼는지 확인
18. 출력
    - 자동: '운송장출력' -> 택배사 선택 창에서 cboTag 값 더블클릭
            -> '주소정제추출 실패' 팝업이면 확인 누르고 종료
            -> 출력 미리보기 -> 인쇄 -> 설정한 프린터(Printer) 선택 -> 인쇄(실제 출력)
    - 수동: '엑셀파일생성' -> 택배사 선택 창에서 cboTag 값 더블클릭
            -> 파일 저장 대화상자에서 프로그램이 채운 파일명 그대로, 폴더만
               바탕화면 ERPIA_AI_JOBS 로 바꿔 저장 (폴더가 없으면 생성)
            -> '생성한 엑셀파일을 여시겠습니까?' 팝업이 뜨면 누르지 않고 종료

주의: 물류 관리 화면에서 '조회(F)'는 상단 그리드 조회 버튼이며, 누르면 화면 모드가 바뀌어
      하단 그리드의 '개별 배송(B)'이 비활성화되므로 루틴에서는 누르지 않는다.
      (하단 그리드 조회는 '주문조회(J)')
"""
import os
import re
import shutil
import subprocess
import sys
import time

import ctypes.wintypes

import win32clipboard
import win32con
import win32gui
from pywinauto import Application, Desktop
from pywinauto.controls.uiawrapper import UIAWrapper
from pywinauto.controls.win32_controls import ButtonWrapper, EditWrapper
from pywinauto.uia_defines import IUIA
from pywinauto.keyboard import send_keys
from pywinauto.uia_element_info import UIAElementInfo
import win32process

import erpia_common as ec
import perform_login as pl
import rpa_status as status

# 결과 로그를 둘 폴더. 옛 구조는 exe 옆, 새 구조는 ProgramData\AFTER MARKET\RPA\data (rpa_status 가 정한다)
BASE_DIR = status.data_dir()
RESULT_PATH = os.path.join(BASE_DIR, "run_routine_result.txt")
PROCESS_WAIT_SECONDS = 30
LOGIN_WINDOW_WAIT_SECONDS = 30
# 로그인 후 메인 화면(좌측 메뉴 포함)이 완전히 뜰 때까지 기다리는 최대 시간
MAIN_WINDOW_READY_TIMEOUT = 90
GRID_MAX_SCROLLS = 80

# 팝업에서 눌러야 하는 버튼 텍스트 (예 / 확인 계열)
OK_BUTTON_TEXTS = ("예(Y)", "예", "확인(O)", "확인")
# '가져오기' 중에 뜨는 안내 팝업에서는 '아니오'를 먼저 찾는다.
# 사용자 규칙: 확인만 있는 팝업은 '확인', 예/아니오 팝업은 '아니오'.
# (예: Cafe24 필독 안내, 로그인 실패 안내 -> 재수집 여부를 묻는 경우가 있다)
# '취소'는 넣지 않는다. '확인/취소' 팝업에서는 사용자 규칙대로 '확인'을 눌러야 한다.
NO_BUTTON_TEXTS = ("아니오(N)", "아니오", "아니요(N)", "아니요")
# 매출처리가 실패하면 뜨는 팝업의 문구.
# 이 팝업이 뜨면 뒤 단계(물류대기/물류 관리)를 진행하면 안 되므로 루틴을 멈춘다.
SALES_FAIL_KEYWORDS = ("정상매출실패", "정상매출 실패", "매출처리실패", "매출처리 실패")
# 정상매출 도중 ERPia 가 내부 오류를 '별도 창'으로 띄울 때가 있다 (.NET NullReferenceException).
# 사용자 규칙: '확인'을 누르고 계속 기다린다. 뒤이어 '정상매출처리 실패' 팝업이 뜨면 그때 멈춘다.
ERROR_POPUP_KEYWORDS = ("개체 참조가 개체의 인스턴스로 설정되지 않았습니다",
                        "Object reference not set to an instance of an object")
# 비동기 처리 대기 폴링 간격/최대 대기
# 스피너 검사(grid_overlay_count/detect_spinner)는 win32 호출이라 사실상 공짜다.
# 촘촘히 봐도 비용이 들지 않고, 끝난 것을 늦게 알아차리는 손해만 줄어든다.
ASYNC_POLL_SECONDS = 2
ASYNC_MAX_WAIT_SECONDS = 600
# '스피너가 없다'를 완료로 인정하기 전에 이만큼은 계속 없어야 한다.
# (폴링 간격을 줄여도 완료 판정이 성급해지지 않도록 시간으로 못박는다)
ASYNC_IDLE_SECONDS = 15
# '가져오기'(주문 수집) 대기.
# 이 화면에는 그리드를 덮는 스피너가 없어서 버튼 상태로 판단한다 (2026-09-15 실측).
#   확인방법 1: '가져오기' 버튼이 비활성 + 아이콘이 '조회중'으로 바뀐다 (클릭 즉시).
#   확인방법 2: '매출처리' 버튼도 같이 비활성된다 (0.3초 뒤).
#   둘 다 다시 활성으로 돌아오면 끝난 것이다 (12개 몰 324초 걸렸다).
IMPORT_BUTTON_NAME = "가져오기"
IMPORT_BUSY_WAIT_SECONDS = 15      # 클릭 뒤 '조회중'으로 바뀌기를 기다리는 시간
IMPORT_POLL_SECONDS = 0.5
IMPORT_SETTLE_SECONDS = 3          # 둘 다 돌아온 뒤 이만큼 유지되어야 완료로 본다
# 많이 쓰는 업체도 1시간은 넘지 않는다고 해서 45분으로 잡았다 (실측 324초의 8배).
# 여기에 걸리면 '완료를 확인하지 못했다'고 남기고 다음 단계로 넘어간다.
IMPORT_MAX_WAIT_SECONDS = 2700
POPUP_RETRY_SECONDS = 3            # 안내 팝업 읽기에 실패했을 때 다시 볼 때까지
POPUP_MAX_ATTEMPTS = 3             # 이 횟수까지만 시도하고 더는 건드리지 않는다
# 커스텀 그리드라 체크박스 클릭이 한 번에 안 먹을 수 있어 재시도 횟수/대기시간을 둔다
CHECKBOX_CLICK_RETRIES = 3
CHECKBOX_CLICK_WAIT = 0.15
# 그리드 한 행의 높이(px) 기본값(폴백).
# 실제로는 measure_row_height()로 런타임에 측정해서 쓰므로
# DPI/글꼴 배율이 다른 PC에서도 어긋나지 않는다. 측정 실패 시에만 이 값을 쓴다.
GRID_ROW_HEIGHT = 23
# 물류 관리 화면에서 유휴 상태일 때 각 그리드를 덮고 있는 자식 창 개수(실측값).
# 이보다 많아지면 로딩 스피너가 떠 있는 것으로 본다.
LOGISTICS_BOTTOM_IDLE_OVERLAYS = 1

# 대시보드에 보여줄 단계 (rpa_status.step 에 넘기는 키, 화면에 쓰는 이름).
# 순서가 곧 진행 순서다. 건너뛴 단계는 대시보드에 '건너뜀'으로 표시된다.
ROUTINE_STEPS = (
    ("login", "ERPia 로그인"),
    ("order_screen", "주문매핑 화면 이동"),
    ("top_select", "상단 선택 · 주문 가져오기"),
    ("excel_upload", "엑셀 업로드"),
    ("bottom_select", "하단 주문 선택"),
    ("sales", "정상매출 처리"),
    ("hold_screen", "물류대기 화면 이동"),
    ("stock_review", "재고검토 배송보류"),
    ("abnormal_hold", "비정상 상품 배송보류"),
    ("hold_save", "물류대기 저장"),
    ("logistics_screen", "물류 관리 화면 이동"),
    ("logistics", "배송 생성"),
    ("shipping_setup", "배송정보 설정"),
    ("logistics_save", "물류 관리 저장"),
    ("output", "운송장 출력 / 엑셀 생성"),
)

# 화면 단위 모듈. 사용자 설정(RPA_UserConfig.json 의 "Routine" 섹션)으로 골라 돌린다.
# (모듈 키, 설정 키, 화면 이름, 이 모듈이 맡는 ROUTINE_STEPS 키들, module_flags 비트)
# 순서가 곧 실행 순서다. 비트는 명시 값이다 - 순서를 바꾸거나 모듈을 끼워 넣어도 기존 비트는 바꾸지 않는다
# (이력의 module_flags 정수 의미가 달라지면 안 된다). 새 모듈은 다음 빈 비트(32, 64, ...)를 쓴다.
# 모듈 안의 단계는 고를 수 없다 - 특히 물류관리의 배송정보설정(shipping_setup)은 로그인 세션마다
# 초기화되므로 저장 앞에서 항상 돌아야 한다.
ROUTINE_MODULES = (
    ("login",     "Login",     "로그인",              ("login",), 1),
    ("sales",     "Sales",     "주문매핑 매출처리",     ("order_screen", "top_select", "excel_upload", "bottom_select", "sales"), 2),
    ("hold",      "Hold",      "물류대기 관리",         ("hold_screen", "stock_review", "abnormal_hold", "hold_save"), 4),
    ("logistics", "Logistics", "물류관리",             ("logistics_screen", "logistics", "shipping_setup", "logistics_save"), 8),
    ("output",    "Output",    "운송장 출력 / 엑셀 생성", ("output",), 16),
)
RUN_MODULES_ENV = "RPA_RUN_MODULES"   # 예약 줄이 고른 이번 실행 모듈 (rpa_dashboard.launch_slot) - 있으면 설정 파일 대신


def run_modules_from_env(keys):
    """예약이 넘긴 이번 실행 모듈. ({설정 키: True/False}, 모르는 키) - 변수가 없으면 (None, []).
    로그인은 늘 켬, 물류관리가 없으면 출력은 뺀다 (설정 파일 규칙과 같다). 돌릴 게 없으면 전부 False."""
    raw = os.environ.get(RUN_MODULES_ENV)
    if raw is None:
        return None, []
    wanted = [k.strip() for k in raw.split(",") if k.strip()]
    unknown = [k for k in wanted if k not in keys]
    on = {k for k in wanted if k in keys}
    if "Logistics" not in on:
        on.discard("Output")
    if not on - {"Login"}:
        return {k: False for k in keys}, unknown
    on.add("Login")
    return {k: k in on for k in keys}, unknown

# 모듈 함수가 돌려주는 결과와 화면에 쓸 이름
MODULE_RESULT_LABEL = {"done": "완료", "no_target": "대상 없음", "skipped": "건너뜀",
                       "failed": "실패", "stopped": "중단"}

logs = []
_log_started = False


def log(msg):
    """화면에 찍고, 그때그때 파일에도 덧붙인다.

    예전에는 맨 끝에서 한 번에 썼다. 그러면 강제 종료했을 때 파일이 아예
    생기지 않아, 정작 원인을 알아야 하는 상황에서 볼 것이 없었다.
    """
    global _log_started
    line = f"[{time.strftime('%H:%M:%S')}] {msg}" if msg.strip() else msg
    logs.append(line)
    print(line)
    status.log_line(line)
    try:
        mode = "a" if _log_started else "w"
        with open(RESULT_PATH, mode, encoding="utf-8") as f:
            f.write(line + "\n")
        _log_started = True
    except Exception:
        pass


def load_exe_path():
    """ERPiaMain.exe 경로 (사용자 설정의 ERPia.ExePath). 틀렸으면 설치 기록·기본 폴더에서 찾아 고쳐 적는다.
    그래도 없으면 사람이 직접 띄운 실행일 때만 고르는 창을 띄운다. 대시보드·에이전트·예약이 띄운 무인 실행
    (RPA_UNATTENDED=1)은 창 앞에서 멈추면 안 되니 바로 멈추고 사유를 남긴다."""
    path = status.erpia_exe(ask=not os.environ.get("RPA_UNATTENDED"))
    if not path:
        raise RuntimeError("ERPia 프로그램(ERPiaMain.exe)을 찾지 못했습니다. ERPia 가 설치되어 있는지 보고, "
                           "에이전트를 다시 켜거나 루틴 RPA 를 직접 실행하면 위치를 고르는 창이 뜹니다")
    return path


def ensure_erpia_running():
    """ERPia 가 떠 있으면 그 PID. 없으면 띄운다 - 위치는 이때만 찾는다 (떠 있으면 위치가 틀려도 상관없다)."""
    try:
        pid = ec.find_erpia_pid()
        log(f"ERPiaMain.exe 이미 실행 중 (PID={pid})")
        return pid
    except RuntimeError:
        pass

    exe_path = load_exe_path()
    log(f"ERPiaMain.exe 미실행 -> 실행: {exe_path}")
    subprocess.Popen([exe_path], cwd=os.path.dirname(exe_path))

    waited = 0.0
    while waited < PROCESS_WAIT_SECONDS:
        try:
            pid = ec.find_erpia_pid()
            log(f"ERPiaMain.exe 실행 확인됨 (PID={pid})")
            return pid
        except RuntimeError:
            time.sleep(1)
            waited += 1
    raise RuntimeError("ERPiaMain.exe 프로세스가 뜨는 것을 확인하지 못했습니다.")


def is_main_app_window(hwnd):
    """해당 창이 '로그인 완료된 메인 화면'인지 확인한다.

    앱을 막 실행한 직후에는 로그인 창이 뜨기 전에 스플래시/초기 창이
    '텍스트 있는 최상위 창'으로 먼저 잡힐 수 있어, 이를 메인 창으로 오인하면 안 된다.
    좌측 메뉴(Accordion Menu / lcg_* 아이콘)가 있는지로 판별한다.
    """
    try:
        app = Application(backend="uia").connect(handle=hwnd)
        win = app.window(handle=hwnd)
        for c in win.descendants():
            t = c.window_text()
            if t == "Accordion Menu" or t.startswith("lcg_"):
                return True
    except Exception:
        pass
    return False


def acquire_main_window(pid, tries=12):
    """로그인 완료된 메인 창을 잡아 (hwnd, app, win) 을 돌려준다.

    로그인 직후(특히 2차 인증 안내 팝업을 거친 경우) ERPia 가 메인 창을 다시 만들어,
    방금 잡은 핸들로 UIA 를 호출하면 COMError(-2146233083, ElementFromHandle) 가 난다.
    그럴 때 창을 다시 찾아 재시도한다. 실제로 UIA 호출이 되는 창만 돌려준다.
    못 잡으면 (None, None, None).
    """
    for attempt in range(tries):
        try:
            candidate = ec.wait_for_main_hwnd(pid, timeout=5)
        except RuntimeError:
            candidate = None
        if candidate is None:
            time.sleep(1.0)
            continue
        try:
            # is_main_app_window 이 좌측 메뉴가 보일 때까지(=메인 화면 준비됨) 확인한다.
            if not is_main_app_window(candidate):
                time.sleep(1.0)
                continue
            ec.ensure_foreground(candidate)
            app = Application(backend="uia").connect(handle=candidate)
            win = app.window(handle=candidate)
            # 핸들이 곧 무효가 될 상태면 여기서 COMError 가 난다. 되면 이 창은 쓸 수 있다.
            win.rectangle()
            return candidate, app, win
        except Exception as e:
            log(f"  메인 창(hwnd={candidate}) 접근 실패 -> 다시 잡습니다 "
                f"({attempt + 1}/{tries}): {type(e).__name__}")
            time.sleep(1.5)
    return None, None, None


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
        self.options = None      # 물류 설정 (사용자 설정 Logistic). 처음 필요할 때 읽는다.
        self.results = {}        # 이번 실행의 모듈 결과 {모듈 키: "done" | "no_target" | ...}

    def refresh(self):
        """메인 창을 다시 잡는다. 못 잡으면 False."""
        self.hwnd, self.app, self.win = acquire_main_window(self.pid)
        return self.hwnd is not None

    def attach(self):
        """로그인 모듈 없이 시작할 때: 이미 떠 있는 ERPia 에 붙는다. (ok, 사유)"""
        try:
            self.pid = ec.find_erpia_pid()
        except Exception as e:
            return False, ("ERPia 가 실행되어 있지 않습니다. 로그인 모듈을 켜거나 ERPia 를 먼저 띄우세요."
                           f" ({type(e).__name__})")
        # 로그인 창이 떠 있으면 메인 창을 1분 넘게 기다렸다 실패하므로 먼저 가려낸다.
        # find_login_window 는 로그인 뒤 숨은 채 남는 잔재 창도 돌려주므로 '보이는' 창만 본다.
        login_win = pl.find_login_window()
        if login_win is not None and win32gui.IsWindowVisible(login_win.handle):
            return False, "ERPia 로그인 창이 떠 있습니다. Login 모듈을 켜거나 먼저 로그인하세요."
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


def wait_login_or_main(pid):
    """로그인 창을 기다리되, 이미 메인 화면이 떠 있으면(이미 로그인) 그 사실을 알려준다."""
    waited = 0.0
    while waited < LOGIN_WINDOW_WAIT_SECONDS:
        login_win = pl.find_login_window()
        if login_win is not None:
            return "login_window", login_win
        try:
            hwnd = ec.find_main_hwnd(pid)
            if is_main_app_window(hwnd):
                return "already_logged_in", hwnd
        except Exception:
            pass
        time.sleep(1)
        waited += 1
    return "timeout", None


def wait_for_active_main_tab(app, hwnd, keyword, timeout=20, interval=1.0, ctx=None):
    """활성 메인탭이 keyword를 포함할 때까지 기다린다.

    화면 전환 직후에는 탭바가 아직 만들어지지 않아 탭 목록이 비어 보일 수 있고,
    창 크기를 조절하는 중에도 일시적으로 조회가 실패할 수 있으므로 재시도한다.
    """
    waited = 0.0
    last = None
    while waited < timeout:
        last = get_active_main_tab(app, hwnd)   # 예외 대신 None 을 준다 -> 여기서 재시도
        if last and keyword in last:
            return True, last
        if last is None and not win32gui.IsWindow(hwnd):
            # 창 핸들 자체가 죽었다 = 창이 다시 만들어졌다. 새 메인 창을 잡아 이어서 기다린다.
            log("  메인 창 핸들이 무효가 됐습니다 -> 메인 창을 다시 잡습니다")
            try:
                new_hwnd, new_app, _win = acquire_main_window(ec.find_erpia_pid())
            except Exception as e:
                new_hwnd, new_app = None, None
                log(f"  메인 창 재확보 실패(계속 기다림): {type(e).__name__}")
            if new_hwnd is not None:
                hwnd, app = new_hwnd, new_app
                if ctx is not None:
                    ctx.hwnd, ctx.app = new_hwnd, new_app   # 호출자도 새 창을 쓰게 한다
                log(f"  메인 창 다시 확보: hwnd={hwnd}")
        time.sleep(interval)
        waited += interval
    return False, last


def goto_screen_by_icon(ctx, key, label, tab_keyword, wait_seconds=30):
    """좌측 아이콘(key)을 눌러 활성 메인탭에 tab_keyword 가 뜨는지 확인한다.

    반환: "ok" | "absent"(아이콘 자체가 없음 - 업체에 그 메뉴가 없다) | "failed"(눌렀지만 진입 확인 실패)
    'absent' 와 'failed' 를 구분하는 이유: 앞의 것은 모듈을 건너뛰어도 되지만 뒤의 것은 실패다.
    조회 중 UIA 오류가 한 번이라도 있었으면 'absent' 로 보지 않는다 (메뉴 없음으로 오판하지 않기 위해).
    """
    target = None
    waited = 0.0
    errors = 0          # 연속 UIA 오류 횟수
    had_error = False
    while waited < wait_seconds:
        try:
            win = ctx.window()
            # find_by_text 는 예외를 삼키고 None 을 돌려주므로, 핸들이 죽었는지는 여기서 직접 찔러 본다
            # (죽은 핸들이면 COMError - acquire_main_window 와 같은 probe). 안 찌르면 죽은 창에서
            # 30초 동안 None 만 받다가 '메뉴 없음' 으로 오판한다.
            win.rectangle()
            target = find_by_text(win, key, control_types=("Pane",))
            errors = 0
        except Exception as e:
            # 화면 전환 중 UIA 가 잠시 COMError 를 내면 '아직 없음'으로 보고 다시 시도한다.
            errors += 1
            had_error = True
            log(f"  '{label}' 아이콘 조회 실패(잠시 뒤 재시도): {type(e).__name__}")
            target = None
            if errors >= 3 or not win32gui.IsWindow(ctx.hwnd):
                # 창 자체가 다시 만들어졌거나(로그인 직후에 이런 일이 있다) 오류가 계속된다
                log("  메인 창 핸들이 무효가 됐거나 UIA 오류가 계속됩니다 -> 메인 창을 다시 잡습니다")
                if not ctx.refresh():
                    return "failed"
                errors = 0
                log(f"  메인 창 다시 확보: hwnd={ctx.hwnd}")
        if target is not None:
            break
        if not win32gui.IsWindow(ctx.hwnd):
            # 예외 없이도 창이 죽어 있을 수 있다
            had_error = True
            log("  메인 창 핸들이 무효가 됐습니다 -> 메인 창을 다시 잡습니다")
            if not ctx.refresh():
                return "failed"
            log(f"  메인 창 다시 확보: hwnd={ctx.hwnd}")
        time.sleep(1.0)
        waited += 1.0

    if target is None:
        if had_error:
            log(f"'{label}'({key}) 아이콘을 찾지 못했습니다 (조회 중 오류가 있어 '메뉴 없음' 으로 보지 않습니다).")
            return "failed"
        log(f"'{label}'({key}) 아이콘을 찾지 못했습니다.")
        return "absent"

    log(f"'{label}'({key}) 아이콘 클릭: rect={target.rectangle()}")
    ec.ensure_foreground(ctx.hwnd)
    try:
        target.click_input()
    except Exception as e:
        # 찾은 뒤 누르기 전에 창이 다시 만들어진 경우
        log(f"  '{label}' 아이콘 클릭 중 오류 -> 메인 창을 다시 잡고 재시도: {type(e).__name__}")
        if not ctx.refresh():
            return "failed"
        target = find_by_text(ctx.window(), key, control_types=("Pane",))
        if target is None:
            log(f"'{label}'({key}) 아이콘을 다시 찾지 못했습니다.")
            return "failed"
        ec.ensure_foreground(ctx.hwnd)
        target.click_input()

    # 탭이 미리 열려 있을 수 있으므로 '존재'가 아니라 '활성 탭'으로 확인한다.
    # 화면이 만들어지는 데 시간이 걸리므로 나타날 때까지 기다린다.
    ok, active = wait_for_active_main_tab(ctx.app, ctx.hwnd, tab_keyword, ctx=ctx)
    if ok:
        log(f"'{label}' 화면 이동 확인됨 (활성 메인탭='{active}')")
        return "ok"
    log(f"'{label}' 클릭했으나 진입 확인 실패 (활성 메인탭='{active}')")
    try:
        log(f"  (전체 탭 목록: {[t.window_text() for t in ctx.window().descendants(control_type='TabItem')]})")
    except Exception:
        pass
    return "failed"


def goto_hold_screen(ctx):
    """좌측 '물류대기'(lcg_HoldLogistics) 아이콘 -> '물류대기 관리' 탭."""
    return goto_screen_by_icon(ctx, "lcg_HoldLogistics", "물류대기", "물류대기")


def goto_logistics_screen(ctx):
    """좌측 '물류처리'(lcg_Logistics) 아이콘 -> '물류 관리' 탭. (아이콘 이름과 탭 이름이 다르다)"""
    return goto_screen_by_icon(ctx, "lcg_Logistics", "물류처리", "물류 관리")


def get_horizontal_scrollbar(grid):
    parent = grid.parent()
    sbars = parent.descendants(control_type="ScrollBar")
    horiz = [s for s in sbars if s.rectangle().width() > s.rectangle().height() and s.rectangle().height() > 0]
    return horiz[0] if horiz else None


def grid_column_names(grid):
    try:
        return [h.window_text() for h in grid.descendants(control_type="Header")]
    except Exception:
        return []


def _header_onscreen(grid, column_name):
    """컬럼 헤더가 그리드의 보이는 가로 범위 안에 실제로 있는지 (이름 존재가 아니라 위치).

    이름이 UIA 트리에 있어도 가로 스크롤로 화면 밖(음수/오른쪽 초과)에 있을 수 있다.
    셀을 x좌표로 읽으려면 헤더의 x중심이 그리드 가로 범위 안에 있어야 한다.
    """
    try:
        g = grid.rectangle()
        for h in grid.descendants(control_type="Header"):
            if column_name in (h.window_text() or ""):
                r = h.rectangle()
                cx = (r.left + r.right) // 2
                if r.width() > 0 and g.left <= cx <= g.right:
                    return True
    except Exception:
        pass
    return False


def scroll_grid_right_to_column(hwnd, grid, column_name, max_pages=20):
    """지정한 컬럼 헤더가 화면에 '보일' 때까지 가로 스크롤을 오른쪽으로 이동한다.
    (이름이 트리에 있는지가 아니라, 헤더 x중심이 그리드 가로 범위 안에 오는지로 판단.)"""
    for i in range(max_pages):
        if _header_onscreen(grid, column_name):
            if i:
                log(f"  가로 스크롤 {i}회 후 '{column_name}' 컬럼 보임")
            return True
        hsb = get_horizontal_scrollbar(grid)
        if hsb is None:
            return _header_onscreen(grid, column_name)
        pgright = next((c for c in hsb.descendants() if c.window_text() == "페이지 오른쪽"), None)
        if pgright is None:
            return _header_onscreen(grid, column_name)   # 더 오른쪽으로 갈 곳 없음
        ec.ensure_foreground(hwnd)
        pgright.click_input()
        time.sleep(0.6)
    return _header_onscreen(grid, column_name)


def scroll_grid_left_home(hwnd, grid, max_pages=20):
    """가로 스크롤을 맨 왼쪽으로 보낸다. ('페이지 왼쪽' 버튼이 사라지면 맨 왼쪽)
    Ctrl+End 로 가로가 오른쪽 끝까지 간 뒤, 컬럼을 다시 찾기 전에 기준점을 왼쪽으로 되돌린다."""
    for _ in range(max_pages):
        hsb = get_horizontal_scrollbar(grid)
        if hsb is None:
            return
        pgleft = next((c for c in hsb.descendants() if c.window_text() == "페이지 왼쪽"), None)
        if pgleft is None:
            return                               # 더 왼쪽으로 갈 곳 없음 = 맨 왼쪽
        ec.ensure_foreground(hwnd)
        pgleft.click_input()
        time.sleep(0.4)


_ROW_HEIGHT_CACHE = {}


def measure_row_height(grid, default=GRID_ROW_HEIGHT):
    """그리드의 실제 행 높이(px)를 런타임에 측정한다.

    DPI/글꼴 배율/테마에 따라 달라지므로 상수로 두면 다른 PC에서 어긋난다.
    같은 컬럼 셀들의 top 좌표 간격 중 최소값을 행 높이로 본다.
    """
    try:
        items = grid.descendants(control_type="DataItem")
    except Exception:
        return default

    by_col = {}
    for it in items:
        m = re.match(r"^(.*) 행 (\d+)$", it.window_text())
        if not m:
            continue
        try:
            r = it.rectangle()
        except Exception:
            continue
        if r.height() <= 0:
            continue
        by_col.setdefault(m.group(1), []).append(r.top)

    for tops in by_col.values():
        tops = sorted(set(tops))
        if len(tops) >= 2:
            diffs = [b - a for a, b in zip(tops, tops[1:]) if b > a]
            if diffs:
                return min(diffs)
    return default


def get_row_height(grid):
    """그리드별 행 높이 (한 번만 측정하고 캐시)."""
    try:
        r = grid.rectangle()
        key = (r.left, r.top, r.right, r.bottom)
    except Exception:
        return GRID_ROW_HEIGHT

    if key not in _ROW_HEIGHT_CACHE:
        h = measure_row_height(grid)
        _ROW_HEIGHT_CACHE[key] = h
        log(f"  행 높이 측정: {h}px (그리드 {key})")
    return _ROW_HEIGHT_CACHE[key]


def element_at_point(x, y):
    """화면 좌표의 UIA 요소를 바로 가져온다.
    (그리드 전체를 descendants로 훑으면 수 초가 걸리지만 이건 수십 ms)"""
    pt = ctypes.wintypes.POINT(int(x), int(y))
    el = IUIA().iuia.ElementFromPoint(pt)
    return UIAWrapper(UIAElementInfo(el))


def get_status_column_geometry(grid, status_col="상품상태"):
    """상품상태 컬럼의 x중심과 헤더 아래 y를 돌려준다."""
    header = next((h for h in grid.descendants(control_type="Header")
                   if h.window_text() == status_col), None)
    if header is None:
        return None, None
    hr = header.rectangle()
    return (hr.left + hr.right) // 2, hr.bottom


def scan_view_statuses(x, top_y, bottom_y, status_col="상품상태", step=None):
    """현재 화면의 상품상태 셀들을 좌표로 훑는다. [(y, 값, 요소)] (위->아래)

    step(행 높이)은 호출측에서 실측값을 넘겨준다.
    """
    if step is None:
        step = GRID_ROW_HEIGHT
    out = []
    y = top_y
    while y <= bottom_y:
        try:
            el = element_at_point(x, y)
            name = el.window_text()
            if name.startswith(status_col):
                out.append((y, legacy_value(el), el))
        except Exception:
            pass
        y += step
    return out


def page_status_desc_ok(vals, normal_value):
    """내림차순인가? = '정상'이 전부 앞에 몰려 있는가.

    (단종 < 일시품절 < 정상 이므로 내림차순이면 정상이 먼저 나온다)
    """
    seen_abnormal = False
    for v in vals:
        if v != normal_value:
            seen_abnormal = True
        elif seen_abnormal:
            return False
    return True


def sort_grid_by_status_desc(hwnd, grid, status_col="상품상태",
                             normal_value="정상", max_clicks=3):
    """상품상태를 내림차순으로 '확정'한다 ('정상'이 맨 위로 오게).

    ★ 화면을 보고 '이미 정렬돼 있다'고 판단하면 안 된다.
      이 그리드의 초기 정렬 기준은 항상 다른 컬럼(날짜 등)이다. 그리고 '정상'이
      대다수라서, 정렬되지 않은 상태에서도 맨 위가 '정상'인 경우가 흔하다.
      즉 '맨 위가 정상'은 정렬됐다는 증거가 되지 못한다. 그냥 눌러서 확정한다.

      DevExpress 헤더 클릭은 '정렬없음 -> 오름차순 -> 내림차순' 순환이다.
      그래서 보통 두 번 눌러야 내림차순이 된다.

    내림차순으로 맞추는 이유:
      '정상'은 이 컬럼의 최댓값이다. 내림차순이면 정상이 전부 위로 모이고
      보류 대상(단종/일시품절)은 아래 한 덩어리가 된다. 그 꼬리만 잡으면 되므로
      전 행을 검사할 필요가 없다. 수만 건이 들어와도 비용이 늘지 않는다.
    """
    x, header_bottom = get_status_column_geometry(grid, status_col)
    if x is None:
        log(f"  '{status_col}' 컬럼 좌표를 찾지 못했습니다.")
        return False

    rh = get_row_height(grid)
    top_y = header_bottom + rh // 2
    bottom_y = grid_usable_bottom(grid, rh)

    header = next((h for h in grid.descendants(control_type="Header")
                   if h.window_text() == status_col), None)
    if header is None:
        names = []
        try:
            names = [h.window_text() for h in grid.descendants(
                control_type="Header") if h.window_text()]
        except Exception:
            pass
        log(f"  '{status_col}' 헤더를 찾지 못해 정렬할 수 없습니다. "
            f"보이는 헤더: {names[:12]}")
        return False

    def snapshot():
        scroll_grid_to_top(hwnd, grid)
        rows = scan_view_statuses(x, top_y, bottom_y, status_col, step=rh)
        return [(v or "").strip() for _y, v, _el in rows if (v or "").strip()]

    # 1) 헤더가 정렬 상태를 직접 알려주면 그것으로 확정한다 (재고검토와 같은 방식).
    #    화면 값은 '맞게 정렬됐는지' 마지막 확인에만 쓴다.
    state = header_sort_state(header)
    if state is not None:
        clicks = 0
        while state != "desc" and clicks < max_clicks:
            clicks += 1
            log(f"  '{status_col}' 헤더 클릭 {clicks}회 (현재: {state})")
            ec.ensure_foreground(hwnd)
            header.click_input()
            time.sleep(3)
            state = header_sort_state(header)
        if state != "desc":
            log(f"  {clicks}번 눌렀는데도 내림차순이 되지 않았습니다 (헤더 상태: {state}).")
            return False
        vals = snapshot()
        if not vals:
            log(f"  '{status_col}' 값을 읽지 못했습니다.")
            return False
        if not page_status_desc_ok(vals, normal_value):
            log(f"  헤더는 내림차순인데 화면 값 순서가 맞지 않습니다: {vals[:12]}")
            return False
        log(f"  내림차순 확정 (헤더 {clicks}회 클릭, 맨 위 '{vals[0]}')")
        return True

    # 2) 헤더 상태를 못 읽는 그리드면 예전처럼 화면 값으로 확인한다.
    log("  헤더 정렬 상태를 읽지 못해 화면 값으로 확인합니다.")
    before = snapshot()
    if not before:
        log(f"  '{status_col}' 값을 읽지 못했습니다.")
        return False
    log(f"  누르기 전 화면: {len(before)}행 '{before[0]}' ~ '{before[-1]}'")

    for i in range(1, max_clicks + 1):
        log(f"  '{status_col}' 헤더 클릭 {i}회 (내림차순 확정)")
        ec.ensure_foreground(hwnd)
        header.click_input()
        time.sleep(3)

        vals = snapshot()
        if not vals:
            log(f"  '{status_col}' 값을 읽지 못했습니다.")
            return False
        log(f"    -> {len(vals)}행 '{vals[0]}' ~ '{vals[-1]}'")

        if vals[0] == normal_value and page_status_desc_ok(vals, normal_value):
            log(f"  내림차순 확정 (맨 위 '{vals[0]}')")
            return True

        if vals == before and i == 1:
            log("  헤더를 눌러도 화면이 그대로입니다 "
                "(이 그리드는 정렬이 막혀 있을 수 있습니다).")
            return False

    log(f"  {max_clicks}번 눌렀는데도 내림차순이 되지 않았습니다.")
    return False


def grid_at_bottom(grid):
    """더 내려갈 곳이 없으면 True. ('페이지 아래로'가 사라지는 것으로 본다)"""
    vsb = get_vertical_scrollbar(grid)
    if vsb is None:
        return True
    try:
        return not any(c.window_text() == "페이지 아래로" for c in vsb.descendants())
    except Exception:
        return False


def grid_jump_to_bottom(hwnd, grid, allow_keys=True, max_pages=400):
    """그리드를 맨 아래로 보낸다.

    '페이지 아래로'를 반복 클릭하는 방식은 쓸 수 없다. 한 번에 0.4초라
    수만 건(수백~수천 페이지)이면 몇 분이 날아간다. 한 번에 보내는 방법을 먼저 쓴다.

    allow_keys=False 면 키보드를 쓰지 않는다. 키보드(Ctrl+End)는 포커스 행을
    옮기므로, 선택 앵커를 잡아 둔 뒤에 쓰면 그 앵커가 깨진다.
    """
    # 1) UIA 스크롤 패턴 - 한 번에 끝난다
    try:
        grid.iface_scroll.SetScrollPercent(-1, 100.0)
        time.sleep(0.8)
        if grid_at_bottom(grid):
            log("    맨 아래로 이동 (스크롤 패턴)")
            return True
    except Exception:
        pass

    # 2) 키보드 Ctrl+End
    if allow_keys:
        try:
            cell = pick_grid_cell(grid)
            if cell is not None:
                ec.ensure_foreground(hwnd)
                cell.click_input()
                time.sleep(0.3)
                send_keys("^{END}")
                time.sleep(1.0)
                if grid_at_bottom(grid):
                    log("    맨 아래로 이동 (Ctrl+End)")
                    return True
        except Exception:
            pass

    # 3) 마지막 수단 - 버튼 반복 (느리다)
    log("    맨 아래로 이동 (페이지 버튼 반복 - 느립니다)")
    for _ in range(max_pages):
        if grid_at_bottom(grid):
            return True
        if not scroll_page_down(hwnd, grid):
            return True
    return grid_at_bottom(grid)


def scroll_page_down(hwnd, grid):
    vsb = get_vertical_scrollbar(grid)
    if vsb is None:
        return False
    pgdn = next((c for c in vsb.descendants() if c.window_text() == "페이지 아래로"), None)
    if pgdn is None:
        return False
    ec.ensure_foreground(hwnd)
    pgdn.click_input()
    time.sleep(0.5)
    return True


def scroll_page_up(hwnd, grid):
    vsb = get_vertical_scrollbar(grid)
    if vsb is None:
        return False
    pgup = next((c for c in vsb.descendants() if c.window_text() == "페이지 위로"), None)
    if pgup is None:
        return False
    ec.ensure_foreground(hwnd)
    pgup.click_input()
    time.sleep(0.5)
    return True


def grid_usable_bottom(grid, row_height=None):
    """클릭 가능한 마지막 y좌표. 가로 스크롤바에 걸치는 영역을 실측해서 제외한다."""
    g = grid.rectangle()
    hsb = get_horizontal_scrollbar(grid)
    if hsb is not None:
        try:
            return min(g.bottom, hsb.rectangle().top) - 2
        except Exception:
            pass
    return g.bottom - (row_height if row_height else GRID_ROW_HEIGHT)


def grid_click_bottom(grid):
    """행을 실제로 클릭할 수 있는 마지막 y좌표.

    grid_usable_bottom() 은 안전 여유로 '행 높이 하나'를 통째로 빼기 때문에
    맨 마지막 행이 늘 대상에서 빠진다. 여기서는 가로 스크롤바에 가려지는 부분만
    제외하므로 마지막 행도 포함된다.
    """
    g = grid.rectangle()
    hsb = get_horizontal_scrollbar(grid)
    if hsb is not None:
        try:
            return min(g.bottom, hsb.rectangle().top) - 1
        except Exception:
            pass
    return g.bottom - 1


# 컨텍스트 메뉴가 떴던 창 핸들. 모든 최상위 창을 매번 뒤지면 회당 2초쯤 걸린다.
_CONTEXT_MENU_HWND = None


def _menu_item_in_window(w, menu_text):
    """그 창 안에서 메뉴 항목 버튼을 찾는다."""
    try:
        return next((c for c in w.descendants(control_type="Button")
                     if c.window_text() == menu_text), None)
    except Exception:
        return None


def _menu_target_ready(target):
    """메뉴 항목이 실제로 화면에 떠 있는지 (닫힌 메뉴의 잔상이 아닌지) 확인."""
    try:
        r = target.rectangle()
        return r.width() > 0 and r.height() > 0
    except Exception:
        return False


def _find_menu_item(pid, main_hwnd, menu_text):
    """컨텍스트 메뉴 항목을 찾는다. 반환: (항목, 그 창 핸들)

    컨텍스트 메뉴는 항상 '별도의 최상위 창'으로 뜨므로 메인 창은 보지 않는다.
    메인 창은 요소가 수천 개라 훑으면 10초가 넘게 걸린다.
    """
    # 지난번에 메뉴가 떴던 창부터 (같은 창이 재사용되면 이 한 번으로 끝난다)
    if _CONTEXT_MENU_HWND and _CONTEXT_MENU_HWND != main_hwnd:
        try:
            if win32gui.IsWindow(_CONTEXT_MENU_HWND) and \
                    win32gui.IsWindowVisible(_CONTEXT_MENU_HWND):
                w = Desktop(backend="uia").window(
                    handle=_CONTEXT_MENU_HWND).wrapper_object()
                t = _menu_item_in_window(w, menu_text)
                if t is not None and _menu_target_ready(t):
                    return t, _CONTEXT_MENU_HWND
        except Exception:
            pass

    for w in Desktop(backend="uia").windows():
        try:
            h = w.handle
        except Exception:
            continue
        if h == main_hwnd or h == _CONTEXT_MENU_HWND:
            continue  # 메인 창은 제외 (훑으면 10초 이상), 캐시는 위에서 이미 봤다
        try:
            _, wpid = win32process.GetWindowThreadProcessId(h)
        except Exception:
            continue
        if wpid != pid:
            continue
        t = _menu_item_in_window(w, menu_text)
        if t is not None and _menu_target_ready(t):
            return t, h
    return None, None


def right_click_element_and_select(pid, hwnd, element, menu_text, wait=1.5):
    """지정한 요소 위에서 우클릭하고 컨텍스트 메뉴에서 항목을 클릭한다.

    (그리드 아무 데나 우클릭하면 그 행이 새로 선택되어 기존 범위 선택이 풀리므로,
     반드시 '선택 범위 안의 요소' 위에서 우클릭해야 한다)

    메뉴는 보통 0.2초 안에 뜨므로 고정 대기 대신 폴링해서 뜨는 즉시 진행한다.
    """
    global _CONTEXT_MENU_HWND

    ec.ensure_foreground(hwnd)
    try:
        element.click_input(button="right")
    except Exception as e:
        log(f"  우클릭 실패: {e}")
        return False

    target = None
    found_hwnd = None
    deadline = time.time() + wait
    while True:
        time.sleep(0.1)
        target, found_hwnd = _find_menu_item(pid, hwnd, menu_text)
        if target is not None or time.time() >= deadline:
            break

    if target is None:
        log(f"  컨텍스트 메뉴에서 '{menu_text}'를 찾지 못했습니다.")
        # 열린 메뉴를 닫아 둔다. 그대로 두면 다음 클릭이 메뉴 닫기에 먹혀 헛돈다.
        try:
            send_keys("{ESC}")
        except Exception:
            pass
        return False

    # 비활성(회색) 항목은 클릭해도 아무 일도 일어나지 않으므로 먼저 확인한다.
    try:
        enabled = target.is_enabled()
    except Exception:
        enabled = None
    if enabled is False:
        log(f"  컨텍스트 메뉴 '{menu_text}'가 비활성화 상태입니다. 클릭하지 않습니다.")
        try:
            send_keys("{ESC}")
        except Exception:
            pass
        return False

    log(f"  컨텍스트 메뉴 '{menu_text}' 클릭: {target.rectangle()} (enabled={enabled})")
    _CONTEXT_MENU_HWND = found_hwnd
    target.click_input()
    return True


def select_abnormal_range_and_check(pid, hwnd, grid, status_col="상품상태",
                                    normal_value="정상"):
    """내림차순 정렬 -> 맨 아래 '비정상 꼬리' 구간만 범위선택하고 체크한다.

    내림차순이면 [정상 ... 정상][일시품절 ... 단종] 이 된다.
    그래서 '마지막 행'을 앵커로 잡고 위로 올라가며 정상이 나오는 지점을 찾아
    그 바로 아래 행을 Shift+클릭하면 비정상 전부가 한 번에 선택된다.

    올라가는 거리는 비정상 건수에만 비례한다. 정상이 수만 건이어도 상관없다.

    반환:
      "held"  : 비정상 구간을 범위선택하고 '선택영역 체크'까지 끝냈다 (배송보류 대상 있음).
      "none"  : 전부 정상이라 보류할 비정상 상품이 없다 (실패 아님).
      "error" : 정렬/좌표/읽기/경계 판별에 실패했다.
    호출부는 "none"·"error" 이면 배송보류를 건너뛰고 전체 저장으로 진행한다 (중단하지 않는다).
    """
    if not sort_grid_by_status_desc(hwnd, grid, status_col, normal_value):
        log("  내림차순을 확정하지 못했습니다. 범위선택을 하지 않습니다.")
        return "error"

    x, header_bottom = get_status_column_geometry(grid, status_col)
    if x is None:
        log("  상품상태 컬럼 좌표를 찾지 못했습니다.")
        return "error"

    rh = get_row_height(grid)
    top_y = header_bottom + rh // 2

    # 1) 맨 아래로 가서 마지막 행을 앵커로 잡는다.
    log("  맨 아래로 이동합니다")
    grid_jump_to_bottom(hwnd, grid, allow_keys=True)

    # Ctrl+End 는 맨 아래-맨 오른쪽 셀로 가서 '가로 위치'까지 바꿀 수 있다. 상품상태가
    # 맨 오른쪽 컬럼이 아니면 화면 밖으로 밀려, 앞서 잡아둔 x 가 엉뚱한 컬럼을 가리킨다.
    # 그래서 왼쪽 끝으로 되돌린 뒤 상품상태 컬럼을 다시 화면에 들이고 좌표를 다시 잡는다.
    # (사용자 지시 4단계: Ctrl+End 뒤 상품상태 컬럼 위치 재확인)
    scroll_grid_left_home(hwnd, grid)
    if not scroll_grid_right_to_column(hwnd, grid, status_col):
        log("  맨 아래로 간 뒤 상품상태 컬럼을 다시 화면에 들이지 못했습니다.")
        return "error"
    x, header_bottom = get_status_column_geometry(grid, status_col)
    if x is None:
        log("  맨 아래 이동 후 상품상태 컬럼 좌표를 다시 잡지 못했습니다.")
        return "error"
    top_y = header_bottom + rh // 2

    rows = scan_view_statuses(x, top_y, grid_click_bottom(grid), status_col, step=rh)
    rows = [(y, (v or "").strip(), el) for y, v, el in rows if (v or "").strip()]
    if not rows:
        log("  마지막 화면에서 상품상태를 읽지 못했습니다.")
        return "error"

    last_y, last_val, last_el = rows[-1]
    if last_val == normal_value:
        log(f"  마지막 행이 '{last_val}' 입니다 -> 비정상 상품이 없습니다.")
        status.metric("abnormal_hold", "비정상 보류", 0, note="대상 없음")
        return "none"

    log(f"  마지막 행 클릭(앵커): '{last_val}' {last_el.rectangle()}")
    ec.ensure_foreground(hwnd)
    last_el.click_input()
    time.sleep(0.5)

    # 2) 위로 거슬러 올라가며 '정상'이 나오는 지점을 찾는다.
    boundary_el = None
    boundary_val = None
    for page in range(GRID_MAX_SCROLLS):
        rows = scan_view_statuses(x, top_y, grid_click_bottom(grid), status_col, step=rh)
        rows = [(y, (v or "").strip(), el) for y, v, el in rows if (v or "").strip()]
        vals = [v for _y, v, _el in rows]

        if normal_value in vals:
            # 이 화면에서 마지막 '정상' 바로 다음 행이 경계다.
            idx = len(vals) - 1 - vals[::-1].index(normal_value)
            if idx + 1 < len(rows):
                boundary_el = rows[idx + 1][2]
                boundary_val = rows[idx + 1][1]
                log(f"  경계 발견 (위로 {page}페이지): "
                    f"'{vals[idx]}' 다음 행 '{boundary_val}'")
                # 행을 하나씩 세지 않으므로 화면 한 쪽의 행 수로 추정한다.
                status.metric("abnormal_hold", "비정상 보류",
                              (len(rows) - (idx + 1)) + page * len(rows),
                              note=f"화면 {page + 1}쪽 기준 추정", approx=True)
                break
            # 정상이 이 화면의 맨 마지막 행이면 한 페이지 내려가서 첫 행을 잡는다.
            if not scroll_page_down(hwnd, grid):
                break
            rows = scan_view_statuses(x, top_y, grid_click_bottom(grid),
                                      status_col, step=rh)
            rows = [(y, (v or "").strip(), el) for y, v, el in rows if (v or "").strip()]
            cand = next(((y, v, el) for y, v, el in rows if v != normal_value), None)
            if cand:
                boundary_el, boundary_val = cand[2], cand[1]
                log(f"  경계 발견 (페이지 경계): '{boundary_val}'")
                status.metric("abnormal_hold", "비정상 보류", page * len(rows),
                              note=f"화면 {page}쪽 기준 추정", approx=True)
            break

        if not scroll_page_up(hwnd, grid):
            # 맨 위까지 정상이 하나도 없었다 = 전부 비정상이다.
            rows = scan_view_statuses(x, top_y, grid_click_bottom(grid),
                                      status_col, step=rh)
            rows = [(y, (v or "").strip(), el) for y, v, el in rows if (v or "").strip()]
            if rows:
                boundary_el, boundary_val = rows[0][2], rows[0][1]
                log(f"  맨 위까지 전부 비정상입니다 -> 첫 행 '{boundary_val}' 이 경계")
                status.metric("abnormal_hold", "비정상 보류", (page + 1) * len(rows),
                              note=f"화면 {page + 1}쪽 기준 추정", approx=True)
            break

    if boundary_el is None:
        log("  경계 행을 찾지 못했습니다.")
        return "error"

    # 3) 경계 행을 Shift+클릭해 앵커(마지막 행)까지 한 번에 선택한다.
    log(f"  경계 행 Shift+클릭: '{boundary_val}' {boundary_el.rectangle()}")
    ec.ensure_foreground(hwnd)
    boundary_el.click_input(pressed="shift")
    time.sleep(1.0)

    if right_click_element_and_select(pid, hwnd, boundary_el, "선택영역 체크"):
        return "held"
    return "error"


def right_click_grid_and_select(pid, hwnd, grid, menu_text, wait=1.5):
    """그리드 안에서 우클릭하고, 나타난 컨텍스트 메뉴에서 지정 항목을 클릭한다."""
    # 가능하면 실제 데이터 셀을 잡고, 못 잡으면 그리드 상단 1/4 지점을 쓴다.
    cell = pick_grid_cell(grid)
    if cell is not None:
        return right_click_element_and_select(pid, hwnd, cell, menu_text, wait=wait)

    r = grid.rectangle()
    cx = (r.left + r.right) // 2
    cy = r.top + (r.bottom - r.top) // 4

    ec.ensure_foreground(hwnd)
    log(f"  그리드 우클릭(대체 좌표): ({cx}, {cy})")
    grid.click_input(button="right", coords=(cx - r.left, cy - r.top))
    time.sleep(wait)

    # 컨텍스트 메뉴는 별도 최상위 창일 수도, 메인 창 내부일 수도 있다
    for w in Desktop(backend="uia").windows():
        try:
            _, wpid = win32process.GetWindowThreadProcessId(w.handle)
        except Exception:
            continue
        if wpid != pid:
            continue
        try:
            cands = [c for c in w.descendants() if c.window_text() == menu_text]
        except Exception:
            continue
        if cands:
            target = cands[0]
            log(f"  컨텍스트 메뉴에서 '{menu_text}' 클릭 (창 handle={w.handle}, rect={target.rectangle()})")
            target.click_input()
            return True

    log(f"  컨텍스트 메뉴에서 '{menu_text}'를 찾지 못했습니다.")
    return False


def select_all_by_header_checkbox(hwnd, grid, max_clicks=2):
    """헤더의 체크박스(row Check Box)로 그리드 전체선택.

    헤더는 토글이라 이미 전체선택된 상태에서 누르면 해제되므로,
    체크박스 컬럼(고정열)을 좌표로 읽어 상태를 확인한 뒤 필요할 때만 누른다.
    """
    header = next((c for c in grid.descendants(control_type="Header")
                   if c.window_text() == "row Check Box"), None)
    if header is None:
        log("  'row Check Box' 헤더를 찾지 못했습니다.")
        return False

    hr = header.rectangle()
    x = (hr.left + hr.right) // 2
    rh = get_row_height(grid)
    usable_bottom = grid_usable_bottom(grid, rh)

    def read_states(count=10):
        states = []
        y = hr.bottom + rh // 2
        for _ in range(count):
            if y > usable_bottom:
                break
            try:
                el = element_at_point(x, y)
                if el.window_text().startswith("row Check Box"):
                    states.append(legacy_value(el))
            except Exception:
                pass
            y += rh
        return states

    for attempt in range(1, max_clicks + 1):
        states = read_states()
        real = [s for s in states if s in ("선택", "선택안됨")]
        checked = [s for s in real if s == "선택"]
        if real and len(checked) == len(real):
            log(f"  전체선택 확인됨 (샘플 {len(real)}행 모두 체크)"
                f"{' - 이미 선택되어 있어 누르지 않음' if attempt == 1 else ''}")
            return True

        log(f"  헤더 체크박스 클릭(전체선택) 시도 {attempt} "
            f"(샘플 {len(real)}행 중 체크 {len(checked)}행)")
        ec.ensure_foreground(hwnd)
        header.click_input()
        time.sleep(1.0)

    states = read_states()
    real = [s for s in states if s in ("선택", "선택안됨")]
    ok = bool(real) and all(s == "선택" for s in real)
    log(f"  전체선택 결과: {'성공' if ok else '실패'} (샘플 {real})")
    return ok


def get_active_main_tab(app, hwnd):
    """현재 활성화된 '메인 탭'의 이름을 돌려준다. 못 읽으면 None (절대 예외를 내지 않는다).

    화면이 바뀌는 순간에는 ERPia 의 UIA 조회가 COMError(-2146233083) 를 낸다
    (2026-09-17 콜드스타트에서 주문매핑 이동 직후 이 함수에서 크래시). 그 순간은 지나가는
    것이므로 예외를 삼키고 None 을 돌려주면, 호출부(wait_for_active_main_tab)가 재시도한다.
    """
    try:
        return _get_active_main_tab_raw(app, hwnd)
    except Exception as e:
        log(f"  활성 탭 조회 실패(잠시 뒤 재시도): {type(e).__name__}")
        return None


def _get_active_main_tab_raw(app, hwnd):
    """현재 활성화된 '메인 탭'의 이름을 돌려준다.

    탭 목록에는 상단 메인 탭(메인페이지/주문매핑 매출처리/물류대기 관리/물류 관리 ...)과
    각 화면 안의 서브탭(주문수집/상품매핑/일반/직배송 ...)이 섞여 나온다.
    숨은 화면의 서브탭은 음수 좌표(화면 밖)에 있고 그 안에서도 selected=1 이다.

    픽셀 상수를 쓰지 않기 위해,
      1) 화면 안에 있는 Tab 컨테이너 중 가장 큰 것(= 메인 탭 컨트롤)을 찾고
      2) 그 컨테이너 '상단에 붙어 있는' 탭들만 메인 탭바로 본다.
         (허용 오차는 탭 자신의 높이를 쓰므로 DPI가 달라져도 비례한다)
    """
    win = app.window(handle=hwnd)
    wr = win.rectangle()

    containers = []
    for t in win.descendants(control_type="Tab"):
        try:
            r = t.rectangle()
        except Exception:
            continue
        if r.left >= wr.left and r.top >= wr.top and r.width() > 0 and r.height() > 0:
            containers.append(t)
    if not containers:
        return None

    main_tab = max(containers, key=lambda t: t.rectangle().width() * t.rectangle().height())
    main_top = main_tab.rectangle().top

    for item in main_tab.descendants(control_type="TabItem"):
        try:
            r = item.rectangle()
        except Exception:
            continue
        if r.left < wr.left or r.top < wr.top:
            continue  # 화면 밖(숨은 화면의 서브탭)
        if (r.top - main_top) > r.height():
            continue  # 탭바에 붙어있지 않음 -> 서브탭
        try:
            if item.is_selected():
                return item.window_text()
        except Exception:
            continue
    return None


def click_toolbar_button(win, hwnd, text):
    """화면 안에 보이는 툴바 버튼을 클릭한다 (다른 탭의 동명 버튼은 화면 밖 좌표라 제외)."""
    wr = win.rectangle()
    for b in win.descendants(control_type="Button"):
        if b.window_text() != text:
            continue
        r = b.rectangle()
        if r.left >= 0 and r.top >= 0 and r.right <= wr.right and r.bottom <= wr.bottom:
            log(f"  '{text}' 클릭: {r}")
            ec.ensure_foreground(hwnd)
            b.click_input()
            return True
    log(f"  '{text}' 버튼을 화면에서 찾지 못했습니다.")
    return False


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
    # 개수를 못 세면 예전처럼 그냥 진행한다.
    try:
        rows = len(grid.descendants(control_type="DataItem"))
        if rows == 0:
            # 배송보류 직후 그리드가 다시 그려지는 중이면 잠깐 비어 보일 수 있다. 한 번 더 본다.
            time.sleep(2.0)
            rows = len(grid.descendants(control_type="DataItem"))
    except Exception as e:
        log(f"  그리드 셀 수를 세지 못했습니다(진행): {type(e).__name__}")
        rows = None
    if rows == 0:
        log("물류대기 그리드에 행이 없습니다 -> 저장할 것이 없습니다.")
        return "no_target"
    log(f"  그리드 DataItem 수(셀 기준, 보이는 것만): {rows}")

    log("그리드 전체선택 (헤더 체크박스)")
    if not select_all_by_header_checkbox(hwnd, grid):
        log("전체선택에 실패했습니다. 중단합니다.")
        return "failed"

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

    # 연속으로 뜨는 팝업이 더 있으면 처리
    for _ in range(3):
        time.sleep(1.5)
        win = app.window(handle=hwnd)
        btn = find_popup_ok_button(win)
        if btn is None:
            break
        log(f"  추가 팝업 -> '{btn.window_text()}' 클릭")
        ec.ensure_foreground(hwnd)
        btn.click_input()
    return "done"


def grid_overlay_count(hwnd, grid, tol=40):
    """그리드 영역과 거의 같은 크기의 '보이는 자식 창' 개수.
    유휴 상태에서도 1개(그리드 자신)가 잡히고, 로딩 스피너가 뜨면 그 위에 하나 더 생긴다."""
    g = grid.rectangle()
    n = 0
    for _h, (_cls, rect) in visible_child_windows(hwnd).items():
        if (abs(rect[0] - g.left) <= tol and abs(rect[1] - g.top) <= tol
                and abs(rect[2] - g.right) <= tol and abs(rect[3] - g.bottom) <= tol):
            n += 1
    return n


class PopupGate:
    """비싼 팝업 조회를 '자식 창 구성이 바뀌었을 때'만 하도록 거른다.

    이 앱의 팝업은 메인 창의 자식 창으로 뜬다. 자식 창 목록을 win32로 읽는 것은
    사실상 공짜(0.00초)인 반면, 팝업 버튼 조회는 창 전체를 훑어 수 초가 걸린다.
    첫 확인과 '자식 창이 바뀐 뒤'에만 실제 조회를 하므로, 팝업을 놓치지 않으면서
    폴링 비용을 없앨 수 있다.
    """

    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.last = None

    def should_scan(self):
        try:
            sig = frozenset(visible_child_windows(self.hwnd))
        except Exception:
            return True  # 못 읽으면 안전하게 조회한다
        if sig != self.last:
            self.last = sig
            return True
        return False


def find_by_text(win, text, control_types=("Button",)):
    """이름으로 컨트롤을 찾는다. 종류를 좁혀 먼저 찾고, 못 찾으면 전체를 훑는다.

    창 전체 순회는 요소가 수천 개라 10초가 넘게 걸린다. 종류를 지정하면 훨씬 싸다.
    (종류가 예상과 다를 수 있으므로 전체 순회로 반드시 되돌아간다)
    """
    for ct in control_types:
        try:
            for c in win.descendants(control_type=ct):
                if c.window_text() == text:
                    return c
        except Exception:
            pass
    try:
        return next((c for c in win.descendants() if c.window_text() == text), None)
    except Exception:
        return None


def wait_grid_spinner_gone(hwnd, grid, base_count, label="그리드",
                           poll=ASYNC_POLL_SECONDS, max_wait=ASYNC_MAX_WAIT_SECONDS):
    """그리드 위 로딩 스피너가 사라질 때까지 poll초 간격으로 확인한다.
    스피너가 아예 안 잡히면 이미 조회가 끝난 것으로 보고 바로 진행한다."""
    waited = 0
    reported = None
    while waited <= max_wait:
        n = grid_overlay_count(hwnd, grid)
        if n <= base_count:
            log(f"  [{label}] 스피너 없음(오버레이 {n}개) -> 조회 완료로 간주"
                f"{f' ({waited:.0f}초 대기)' if waited else ''}")
            return True
        if n != reported:   # 촘촘히 보므로 바뀔 때만 남긴다
            log(f"  [{label}] 비동기 실행중(오버레이 {n}개) - {poll}초 간격으로 확인")
            reported = n
        time.sleep(poll)
        waited += poll
    log(f"  [{label}] 최대 대기시간({max_wait}초) 초과")
    return False


def pick_grid_cell(grid):
    """그리드 첫 데이터 행에서 클릭 가능한 셀 하나를 찾아 반환한다.

    고정 픽셀 오프셋 대신 그리드 폭의 비율로 여러 지점을 시도하고,
    실제로 DataItem이 잡히는지 검증한다.
    """
    g = grid.rectangle()
    rh = get_row_height(grid)
    headers = grid.descendants(control_type="Header")
    hdr_bottom = max((h.rectangle().bottom for h in headers), default=g.top + rh)
    y = hdr_bottom + rh // 2

    for frac in (0.15, 0.30, 0.50, 0.08, 0.70):
        x = int(g.left + g.width() * frac)
        try:
            el = element_at_point(x, y)
        except Exception:
            continue
        try:
            if str(el.element_info.control_type) == "DataItem":
                return el
        except Exception:
            continue
    return None


def right_click_grid_cell_and_select(pid, hwnd, grid, menu_text, wait=1.5):
    """그리드의 데이터 셀 하나를 우클릭하고 컨텍스트 메뉴에서 항목을 클릭한다."""
    cell = pick_grid_cell(grid)
    if cell is None:
        log("  우클릭할 데이터 셀을 찾지 못했습니다.")
        return False

    log(f"  셀 우클릭: '{cell.window_text()}' {cell.rectangle()}")
    return right_click_element_and_select(pid, hwnd, cell, menu_text, wait=wait)


def run_logistics_step(app, pid, hwnd, options=None):
    """물류 관리 화면 처리:
    자동/수동 모드 설정 -> 하단 그리드 조회 완료 대기 -> 우클릭 '전체선택'
    -> 우클릭 '개별 배송(B)' -> 상단 그리드 비동기 확인
    반환: "done" | "no_target"(하단 그리드에 배송 대상이 없음) | "failed"

    모드(cboBS_Auto_YN)를 가장 먼저 맞추는 이유:
    이 값이 바뀌면 상단 버튼 배치뿐 아니라 상단 그리드 컬럼 구성까지 통째로 바뀐다.
    그리드를 잡아둔 뒤에 모드를 바꾸면 참조가 어긋나므로 화면에 들어오자마자 맞춘다.
    """
    if options is None:
        options = pl.load_logistic_options()

    # 이 화면에서 쓸 컨트롤들을 한 번의 순회로 미리 찾아 캐시한다
    win = app.window(handle=hwnd)
    prefetch_auto_ids(win, [AUTO_MODE_COMBO]
                      + [i for c in SHIPPING_CONTROLS for i in c[:2]])

    log("자동/수동 모드 설정")
    is_auto, mode_ok = apply_auto_mode(app, hwnd, options)
    if not mode_ok:
        log("자동/수동 모드를 설정하지 못했습니다. 중단합니다.")
        return "failed"
    log(f"  적용된 모드: {AUTO_MODE_LABEL[is_auto]} "
        f"-> 나중에 누를 버튼: '{AUTO_MODE_BUTTON[is_auto]}'")

    win = app.window(handle=hwnd)
    tables = get_onscreen_tables(win)
    if len(tables) < 2:
        log("물류 관리 화면의 그리드를 찾지 못했습니다 (2개 필요).")
        return "failed"

    top_grid = min(tables, key=lambda t: t.rectangle().top)
    bottom_grid = max(tables, key=lambda t: t.rectangle().top)
    log(f"상단 그리드={top_grid.rectangle()} / 하단 그리드={bottom_grid.rectangle()}")

    # 1) 하단 그리드 조회 완료 대기
    log("하단 그리드 조회 완료 대기")
    wait_grid_spinner_gone(hwnd, bottom_grid, LOGISTICS_BOTTOM_IDLE_OVERLAYS, label="하단")

    # 하단이 비어 있으면 개별 배송을 만들 것이 없다 (앞 모듈 없이 이 모듈만 돌릴 때 흔하다).
    # 개수를 못 세면 예전처럼 그냥 진행한다.
    try:
        bottom_rows = len(bottom_grid.descendants(control_type="DataItem"))
    except Exception as e:
        log(f"  하단 그리드 행 수를 세지 못했습니다(진행): {type(e).__name__}")
        bottom_rows = None
    if bottom_rows == 0:
        log("하단 그리드에 배송 대상이 없습니다 -> 할 것이 없습니다.")
        try:
            if top_grid.descendants(control_type="DataItem"):
                log("  경고: 상단 그리드에는 행이 남아 있습니다 (저장되지 않은 배송장일 수 있음). "
                    "자동으로 저장하지 않으니 화면에서 확인하세요.")
        except Exception:
            pass
        return "no_target"

    # 2) 우클릭 -> 전체선택
    log("하단 그리드 우클릭 -> '전체선택'")
    if not right_click_grid_cell_and_select(pid, hwnd, bottom_grid, "전체선택"):
        return "failed"
    time.sleep(1.5)

    # 3) 우클릭 -> 개별 배송(B)
    log("하단 그리드 우클릭 -> '개별 배송(B)'")
    top_overlays_before = grid_overlay_count(hwnd, top_grid)
    if not right_click_grid_cell_and_select(pid, hwnd, bottom_grid, "개별 배송(B)"):
        return "failed"
    time.sleep(1.5)

    # 4) 상단 그리드 비동기 확인
    log("상단 그리드 비동기 처리 확인")
    wait_grid_spinner_gone(hwnd, top_grid, top_overlays_before, label="상단")

    # 팝업이 떴으면 처리
    for _ in range(3):
        win = app.window(handle=hwnd)
        btn = find_popup_ok_button(win)
        if btn is None:
            break
        log(f"  팝업 -> '{btn.window_text()}' 클릭")
        ec.ensure_foreground(hwnd)
        btn.click_input()
        time.sleep(1.5)

    win = app.window(handle=hwnd)
    tables = get_onscreen_tables(win)
    top_grid = min(tables, key=lambda t: t.rectangle().top)
    rows = len(top_grid.descendants(control_type="DataItem"))
    if rows == 0:
        log("상단 그리드에 데이터가 생기지 않았습니다 (DataItem 0개). "
            "'개별 배송(B)'이 실제로 반영되지 않았을 수 있습니다.")
        return "failed"
    log(f"상단 그리드 DataItem {rows}개 -> 배송 생성 확인됨")
    return "done"


# ---------------------------------------------------------------------------
# 물류대기 관리 > '상품별 재고검토' 탭 처리
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 주문매핑 매출처리 > 엑셀업로드
# ---------------------------------------------------------------------------
EXCEL_UPLOAD_DIR_NAME = "ERPIA_AI_EXCEL"
EXCEL_UPLOAD_DONE_DIR = "완료"      # 업로드한 파일을 옮길 곳 (아래에 YYYYMMDD)
EXCEL_UPLOAD_ERROR_DIR = "오류"     # 올릴 수 없는 파일을 옮길 곳
EXCEL_UPLOAD_EXTS = (".xlsx", ".xls")
# 파일명은 '(nnn)로 시작한다. nnn 이 사이트코드다.
EXCEL_FILE_CODE_RE = re.compile(r"^\((\d{3})\)")
SITE_CODE_COL = "사이트코드"
EXCEL_UPLOAD_COL = "엑셀업로드"
# '엑셀업로드' 셀 값이 이 값이 아니면 그 사이트는 엑셀 업로드를 지원하지 않는다.
EXCEL_UPLOAD_ENABLED = "1"
# 셀을 누른 뒤 파일 열기 창이 뜨기를 기다리는 시간 (한 번 클릭 -> 안 뜨면 더블클릭)
OPEN_DIALOG_WAIT_SECONDS = 6
# 파일을 넘긴 뒤 결과 팝업을 기다리는 시간.
# 이걸 기다리지 않고 파일을 옮기면 ERPia 가 읽는 도중 파일이 사라져
# '헤더 개수: 0' 같은 오류가 난다 (실측으로 확인).
# 업로드가 정상이면 팝업이 아예 뜨지 않으므로, 이 시간은 '문제가 있었는지 지켜보는' 시간이다.
UPLOAD_RESULT_WAIT_SECONDS = 10
# 팝업을 닫은 뒤에도 파일이 잠겨 있을 수 있어, 풀릴 때까지 조금 더 기다린다.
UPLOAD_FILE_RELEASE_WAIT = 10

STOCK_TAB_NAME = "상품별 재고검토"
STOCK_GENERAL_TAB_NAME = "일반"
STOCK_SHORTAGE_COL = "부족수량"
# 상단 그리드에서 한 행을 식별하는 컬럼들
# (가상화된 '행 N'은 스크롤하면 다른 데이터에 재사용되므로 식별자로 쓸 수 없다)
STOCK_KEY_COLS = ("상품코드", "자체코드")
# 상단 그리드에서 '어떤 상품인지'를 나타내는 컬럼 (하단 그리드 선별 기준값)
STOCK_TOP_CODE_COL = "상품코드"
# 부족수량이 있어도 배송보류하지 않고 건너뛸 상품코드
# (배송비 등 재고 개념이 없는 항목이라 부족수량이 늘 잡히지만 보류 대상이 아니다)
STOCK_EXCLUDED_CODES = (
    "9813018000001",
    "9813018000002",
    "9813018000003",
    "9813018000004",
)
# 하단 그리드에서 같은 상품코드를 담고 있는 컬럼 후보 (업체/버전에 따라 이름이 다르다)
STOCK_BOTTOM_CODE_COLS = ("ERP상품코드", "ERP 상품코드", "상품코드")
# 그리드 체크박스 컬럼의 UIA 이름
GRID_CHECKBOX_COL = "row Check Box"
# 부족수량 셀을 클릭한 뒤 하단 그리드에 데이터가 채워질 때까지 기다리는 최대 시간
STOCK_BOTTOM_WAIT_SECONDS = 40


def _norm_tab_text(s):
    """탭 이름에는 '상품별\n재고검토'처럼 줄바꿈이 들어가므로 비교 전에 정규화한다."""
    return (s or "").replace("\n", "").replace("\r", "").replace(" ", "")


# 서브탭 조회는 창 전체를 훑어 회당 7초쯤 걸린다.
# 한 번 훑을 때 화면에 보이는 서브탭을 '전부' 담아 두면 그 뒤로는 순회가 없다.
_SUBTAB_CACHE = {}


def click_subtab(app, hwnd, name, wait=2.5):
    """화면 좌측의 서브탭을 이름으로 클릭한다.

    숨은 화면의 동명 서브탭은 음수 좌표(화면 밖)에 있으므로 제외한다.
    """
    key = _norm_tab_text(name)
    win = app.window(handle=hwnd)
    wr = win.rectangle()

    def onscreen(el):
        """화면 안에 실제로 보이는 탭인지 (숨은 화면의 동명 탭 제외)."""
        try:
            r = el.rectangle()
        except Exception:
            return None
        if r.width() <= 0 or r.height() <= 0:
            return None
        if r.left < wr.left or r.top < wr.top:
            return None
        return r

    def press(el, r):
        log(f"  서브탭 '{name}' 클릭: {r}")
        ec.ensure_foreground(hwnd)
        el.click_input()
        time.sleep(wait)
        return True

    cached = _SUBTAB_CACHE.get((hwnd, key))
    if cached is not None:
        r = onscreen(cached)
        if r is not None:
            return press(cached, r)
        _SUBTAB_CACHE.pop((hwnd, key), None)

    found = None
    found_rect = None
    seen = set()
    for t in win.descendants(control_type="TabItem"):
        r = onscreen(t)
        if r is None:
            continue
        k = _norm_tab_text(t.window_text())
        if k not in seen:          # 같은 이름이 여럿이면 처음 것을 쓴다 (기존 동작)
            seen.add(k)
            _SUBTAB_CACHE[(hwnd, k)] = t
        if k == key and found is None:
            found, found_rect = t, r

    if found is not None:
        return press(found, found_rect)

    log(f"  서브탭 '{name}'을 화면에서 찾지 못했습니다.")
    return False


# 스크롤바 조회는 그리드 하위를 전부 훑어 0.5초쯤 걸린다.
# 페이지를 넘길 때마다 부르므로 한 번 찾은 것을 기억해 둔다.
_GRID_SCROLLBAR_CACHE = {}


def _grid_cache_key(grid):
    """그리드를 캐시에서 식별하는 키. 화면 위치가 그대로면 같은 그리드로 본다."""
    try:
        r = grid.rectangle()
        return (r.left, r.top, r.right, r.bottom)
    except Exception:
        return None


def grid_vertical_scrollbar(grid):
    """그리드 자신의 세로 스크롤바만 고른다.

    한 화면에 그리드가 여러 개면 parent 기준으로 찾을 때 다른 그리드의 스크롤바를
    집을 수 있으므로, 그리드 사각형 안에 들어 있는 것만 인정한다.
    한 번 찾으면 캐시하고, 더 이상 쓸 수 없게 됐을 때만 다시 찾는다.
    """
    key = _grid_cache_key(grid)
    cached = _GRID_SCROLLBAR_CACHE.get(key) if key else None
    if cached is not None:
        try:
            cr = cached.rectangle()
            if cr.width() > 0 and cr.height() > 0:
                return cached
        except Exception:
            pass
        _GRID_SCROLLBAR_CACHE.pop(key, None)

    g = grid.rectangle()
    try:
        bars = list(grid.descendants(control_type="ScrollBar"))
        bars += list(grid.parent().descendants(control_type="ScrollBar"))
    except Exception:
        return None
    for sb in bars:
        try:
            r = sb.rectangle()
        except Exception:
            continue
        if r.width() <= 0 or r.height() <= r.width():
            continue  # 크기가 0이거나 가로 스크롤바
        if r.top >= g.top - 5 and r.bottom <= g.bottom + 5 and r.right <= g.right + 5:
            if key:
                _GRID_SCROLLBAR_CACHE[key] = sb
            return sb
    return None


def grid_rows(grid):
    """{행번호: {컬럼명: 셀요소}} - 현재 화면에 렌더링된 행들만 담긴다."""
    out = {}
    try:
        items = grid.descendants(control_type="DataItem")
    except Exception:
        return out
    for it in items:
        m = re.match(r"^(.*) 행 (\d+)$", it.window_text())
        if m:
            out.setdefault(int(m.group(2)), {})[m.group(1)] = it
    return out


def _row_key(cells):
    return tuple(legacy_value(cells[c]) if c in cells else None for c in STOCK_KEY_COLS)


def grid_scroll_to_top(hwnd, grid, max_pages=200):
    """그리드 자신의 세로 스크롤바로 맨 위까지 올린다.
    맨 위에 닿으면 '페이지 위로' 버튼이 사라지는 것을 종료 조건으로 쓴다."""
    for _ in range(max_pages):
        vsb = grid_vertical_scrollbar(grid)
        if vsb is None:
            return
        pgup = next((c for c in vsb.descendants() if c.window_text() == "페이지 위로"), None)
        if pgup is None:
            return
        ec.ensure_foreground(hwnd)
        pgup.click_input()
        time.sleep(0.4)


def collect_shortage_rows(hwnd, grid, max_scrolls=GRID_MAX_SCROLLS):
    """상단 그리드를 맨 위부터 맨 아래까지 훑어 부족수량이 있는 행의 키를 모은다.

    STOCK_EXCLUDED_CODES 에 있는 상품코드는 부족수량이 있어도 대상에서 뺀다.

    실제 환경에서는 상단 그리드에도 스크롤이 생기므로 반드시 끝까지 내려가며 봐야 한다.
    '이번 화면에서 새 대상이 없으면 중단'은 부족수량이 비어 있는 페이지에서 조기 종료하므로,
    '스크롤해도 화면에 보이는 행 자체가 그대로인지'를 종료 조건으로 쓴다.

    내릴 때는 '페이지 아래로' 한 번 (한 줄씩 여러 번 누르지 않는다).
    화면이 겹치지 않아도 되는 이유: 이미 본 행은 키(seen)로 걸러지고,
    '페이지 아래로'는 보이는 행 수보다 많이 내려가지 않는다.

    반환: (대상목록, 마지막 행까지 확인했는지 여부)
    """
    grid_scroll_to_top(hwnd, grid)
    ordered = []
    excluded = []
    seen = set()
    prev_view = None
    reached_bottom = False

    for _ in range(max_scrolls):
        rows = grid_rows(grid)
        view_keys = [_row_key(rows[n]) for n in sorted(rows)]

        for n in sorted(rows):
            cells = rows[n]
            cell = cells.get(STOCK_SHORTAGE_COL)
            if cell is None:
                continue
            qty = (legacy_value(cell) or "").strip()
            if not qty:
                continue
            key = _row_key(cells)
            if key in seen:
                continue
            seen.add(key)
            if (key[0] or "").strip() in STOCK_EXCLUDED_CODES:
                # 제외 대상이라도 '봤다'고 기록해 두어야 다음 화면에서 다시 걸리지 않는다
                excluded.append((key[0], qty))
                continue
            ordered.append((key, qty))

        if grid_vertical_scrollbar(grid) is None:
            reached_bottom = True  # 스크롤바가 없다 = 전체가 한 화면
            break
        if view_keys and view_keys == prev_view:
            reached_bottom = True  # 내려도 화면이 그대로 = 맨 아래
            break
        prev_view = view_keys

        if not grid_page_down(hwnd, grid):
            reached_bottom = True  # 방금 화면까지 읽고 나서 더 내려갈 곳이 없음
            break

    if excluded:
        log(f"  제외 상품코드라 건너뜁니다 ({len(excluded)}건): {excluded}")

    return ordered, reached_bottom


def find_row_cell_by_key(hwnd, grid, key, column, max_pages=GRID_MAX_SCROLLS):
    """키에 해당하는 행이 보일 때까지 스크롤하며 지정 컬럼의 셀 요소를 찾는다.

    '행 N'은 스크롤하면 다른 데이터에 재사용되므로 매번 키로 다시 찾아야 한다.

    대상은 위->아래 순서로 처리하므로 다음 대상은 대개 '지금 화면 아래'에 있다.
    그래서 맨 위로 되돌아가지 않고 지금 자리에서 페이지 단위로 내려가며 먼저 찾는다.
    맨 아래까지 없을 때만 맨 위로 올라가 한 번 더 내려간다.
    (예전에는 건마다 맨 위로 올라가 다시 훑어, 대상 수 x 화면 수만큼 스크롤했다.)
    """
    def look():
        for _n, cells in grid_rows(grid).items():
            if _row_key(cells) == key and column in cells:
                return cells[column]
        return None

    for from_top in (False, True):
        if from_top:
            grid_scroll_to_top(hwnd, grid)
        found = look()
        if found is not None:
            return found
        for _ in range(max_pages):
            if not grid_page_down(hwnd, grid):
                break
            found = look()
            if found is not None:
                return found
    return None


# 헤더 조회도 그리드 하위를 전부 훑는다. 컬럼 위치는 변하지 않으므로 캐시한다.
_GRID_HEADER_CACHE = {}


def grid_header(grid, col_name):
    """그리드의 컬럼 헤더 요소를 (캐시해서) 돌려준다."""
    gkey = _grid_cache_key(grid)
    key = (gkey, col_name)
    cached = _GRID_HEADER_CACHE.get(key) if gkey else None
    if cached is not None:
        try:
            r = cached.rectangle()
            if r.width() > 0 and r.height() > 0:
                return cached
        except Exception:
            pass
        _GRID_HEADER_CACHE.pop(key, None)

    try:
        header = next((h for h in grid.descendants(control_type="Header")
                       if h.window_text() == col_name), None)
    except Exception:
        return None
    if header is not None and gkey:
        _GRID_HEADER_CACHE[key] = header
    return header


def _column_scan_geometry(grid, col_name):
    """(컬럼 x중심, 첫 행 y, 마지막 행 y, 행 높이) - 좌표로 한 컬럼만 훑기 위한 값.

    헤더 조회는 그리드 하위를 전부 훑어 비싸므로, 화면에 머무는 동안은
    한 번 구해서 계속 재사용한다 (가로 스크롤을 하지 않으므로 위치가 변하지 않는다).
    """
    header = grid_header(grid, col_name)
    if header is None:
        return None
    hr = header.rectangle()
    rh = get_row_height(grid)
    x = (hr.left + hr.right) // 2
    return x, hr.bottom + rh // 2, grid_click_bottom(grid), rh


def checkbox_column_x(grid):
    """체크박스 컬럼의 x중심 (좌표로 체크 상태를 읽기 위해)."""
    header = grid_header(grid, GRID_CHECKBOX_COL)
    if header is None:
        return None
    hr = header.rectangle()
    return (hr.left + hr.right) // 2


def find_bottom_code_column_by_header(grid):
    """헤더 이름만으로 상품코드 컬럼을 고른다 (값 조회 없이 한 번만)."""
    try:
        names = [h.window_text() for h in grid.descendants(control_type="Header")]
    except Exception:
        return None
    for cand in STOCK_BOTTOM_CODE_COLS:
        if cand in names:
            return cand
    return None


def find_bottom_code_column(grid, code):
    """하단 그리드에서 '상단 상품코드와 같은 값'이 들어 있는 컬럼명을 찾는다.

    헤더가 2줄로 겹쳐 있는 그리드는 UIA 셀 이름이 실제 컬럼과 어긋나는 경우가 있어,
    이름만 믿지 않고 '값이 실제로 일치하는 컬럼'을 우선한다.
    (비싼 조회라 헤더 이름으로 못 정했을 때만 쓴다)
    """
    rows = grid_rows(grid)
    names = set()
    for cells in rows.values():
        names.update(cells)

    for cand in STOCK_BOTTOM_CODE_COLS:
        if cand not in names:
            continue
        for cells in rows.values():
            el = cells.get(cand)
            if el is not None and (legacy_value(el) or "").strip() == code:
                return cand

    for cells in rows.values():
        for col, el in cells.items():
            if col == GRID_CHECKBOX_COL:
                continue
            if (legacy_value(el) or "").strip() == code:
                log(f"    상품코드 컬럼을 값으로 찾았습니다: '{col}'")
                return col

    for cand in STOCK_BOTTOM_CODE_COLS:
        if cand in names:
            return cand
    return None


def scan_column(geo, col_name):
    """현재 화면에서 한 컬럼의 값을 좌표로 훑는다. [(y, 값, 요소)] (위->아래)"""
    x, top_y, bottom_y, rh = geo
    return scan_view_statuses(x, top_y, bottom_y, col_name, step=rh)


def probe_edge_row(geo, col_name, from_top=True):
    """화면의 첫(또는 마지막) 데이터 행의 (값, 요소).

    한 페이지를 통째로 읽지 않고 끝에서부터 유효한 셀이 나올 때까지만 읽는다.
    """
    x, top_y, bottom_y, rh = geo
    ys = (range(top_y, bottom_y + 1, rh) if from_top
          else range(bottom_y, top_y - 1, -rh))
    for y in ys:
        try:
            el = element_at_point(x, y)
            if not el.window_text().startswith(col_name):
                continue
            v = (legacy_value(el) or "").strip()
            if v:
                return v, el
        except Exception:
            continue
    return None, None


def sample_column_values(geo, col_name, count=8):
    """화면의 여러 행을 듬성듬성 읽어 값 목록을 돌려준다 (정렬 상태 점검용)."""
    x, top_y, bottom_y, rh = geo
    total = max(1, (bottom_y - top_y) // rh + 1)
    step = max(1, total // max(1, count))
    out = []
    for i in range(0, total, step):
        y = top_y + i * rh
        if y > bottom_y:
            break
        try:
            el = element_at_point(x, y)
            if not el.window_text().startswith(col_name):
                continue
            v = (legacy_value(el) or "").strip()
            if v:
                out.append(v)
        except Exception:
            continue
    return out


def wait_bottom_grid_rows(hwnd, grid, geo, col_name,
                          timeout=STOCK_BOTTOM_WAIT_SECONDS, interval=0.5, settle_reads=2):
    """하단 그리드에 데이터가 채워지고 안정될 때까지 기다린다.

    창 전체를 훑는 조회(약 5초)를 폴링에 쓰면 건마다 수십 초가 날아가므로 한 컬럼만 좌표로 읽는다.
    예전에는 첫/마지막 행이 두 번 같으면 안정으로 봤는데, 그 뒤에 화면이 또 바뀐 일이 있었다
    (2026-09-16). 이제는 보이는 행 전체가 settle_reads 번 연달아 같을 때 안정으로 본다.
    반환: (첫 행 값, 마지막 행 값) - 값이 없으면 (None, None)
    """
    def edges(vals):
        filled = [v for v in vals if v]
        return (filled[0], filled[-1]) if filled else (None, None)

    prev = None
    same = 0
    waited = 0.0
    while waited < timeout:
        vals = tuple((v or "").strip() for _y, v, _el in scan_column(geo, col_name))
        if any(vals) and vals == prev:
            same += 1
            if same >= settle_reads:
                return edges(vals)
        else:
            same = 0
        prev = vals
        time.sleep(interval)
        waited += interval
    return edges(prev or ())


def grid_page_down(hwnd, grid, geo=None, col_name=None):
    """그리드 자신의 스크롤바로 한 페이지 내린다. 더 내려갈 곳이 없으면 False.

    (geo/col_name 은 호출부 호환을 위해 받기만 한다. '화면이 바뀌면 즉시 진행'하는
     방식도 재봤지만, 그리드 재렌더가 0.4초보다 오래 걸려 오히려 느렸다.)
    """
    vsb = grid_vertical_scrollbar(grid)
    if vsb is None:
        return False
    pgdn = next((c for c in vsb.descendants() if c.window_text() == "페이지 아래로"), None)
    if pgdn is None:
        return False
    ec.ensure_foreground(hwnd)
    pgdn.click_input()
    time.sleep(0.4)
    return True


def grid_page_up(hwnd, grid):
    """그리드 자신의 스크롤바로 한 페이지 올린다. 더 올라갈 곳이 없으면 False.
    (grid_page_down 의 반대. 한 줄씩이 아니라 '페이지 위로' 버튼 한 번.)"""
    vsb = grid_vertical_scrollbar(grid)
    if vsb is None:
        return False
    pgup = next((c for c in vsb.descendants() if c.window_text() == "페이지 위로"), None)
    if pgup is None:
        return False
    ec.ensure_foreground(hwnd)
    pgup.click_input()
    time.sleep(0.4)
    return True


# 정렬 상태는 헤더 요소가 직접 알려준다 (2026-09-17 실측).
#   DevExpress 그리드 헤더의 legacy_properties()['DefaultAction'] = '다음에 클릭하면 할 일':
#     '오름차순 정렬' -> 지금은 정렬 안 됨 (한 번 누르면 오름차순)
#     '내림차순 정렬' -> 지금 오름차순      (우리가 원하는 상태)
#     '정렬 제거'     -> 지금 내림차순      (한 번 누르면 오름차순)
#   그래서 첫/마지막 행 값을 추측할 필요 없이, 이 속성만 읽으면 정렬 상태를 안다.
#   2026-09-16 사고는 '행이 1개라 정렬된 걸로 보고' 헤더를 아예 누르지 않아서 났다.
#   이제는 값이 아니라 헤더 상태를 보고 오름차순이 될 때까지 누른다 (스크롤 없음, 최대 2클릭).
SORT_DA_ASCENDING = "내림차순 정렬"     # 이 값이면 '지금 오름차순'
SORT_DA_UNSORTED = "오름차순 정렬"
SORT_DA_DESCENDING = "정렬 제거"


def header_sort_state(header):
    """헤더의 DefaultAction 을 읽어 현재 정렬 상태를 돌려준다.
    'asc'(오름차순) / 'desc'(내림차순) / 'none'(정렬 안 됨) / None(못 읽음)."""
    try:
        da = (header.legacy_properties().get("DefaultAction") or "").strip()
    except Exception:
        return None
    if da == SORT_DA_ASCENDING:
        return "asc"
    if da == SORT_DA_DESCENDING:
        return "desc"
    if da == SORT_DA_UNSORTED:
        return "none"
    return None


def sort_grid_ascending_by(hwnd, grid, col_name, geo, max_clicks=3):
    """컬럼 헤더를 눌러 오름차순으로 '확정'한다.

    헤더의 DefaultAction 속성으로 현재 정렬 상태를 직접 읽는다 (값 추측 안 함).
    오름차순이 되면(DefaultAction=='내림차순 정렬') 멈춘다. 스크롤하지 않는다.

    정렬해 두면 같은 상품코드 행들이 '연속 구간'으로 모이므로,
    한 행씩 체크하지 않고 범위선택 한 번으로 처리할 수 있다.
    """
    header = grid_header(grid, col_name)
    if header is None:
        log(f"    '{col_name}' 헤더를 찾지 못해 정렬할 수 없습니다.")
        return False

    for attempt in range(max_clicks + 1):
        state = header_sort_state(header)
        if state == "asc":
            if attempt == 0:
                log(f"    '{col_name}' 이미 오름차순 (헤더 상태 확인)")
            else:
                log(f"    '{col_name}' 오름차순 확정 (헤더 클릭 {attempt}회)")
            return True
        if attempt == max_clicks:
            break
        desc = {"desc": "내림차순", "none": "정렬 안 됨", None: "알 수 없음"}.get(state, state)
        log(f"    '{col_name}' 헤더 클릭(정렬) {attempt + 1}회 (현재: {desc})")
        ec.ensure_foreground(hwnd)
        try:
            header.click_input()
        except Exception as e:
            log(f"    헤더 클릭 실패: {e}")
            return False
        time.sleep(1.5)

    log(f"    '{col_name}' 오름차순 정렬에 실패했습니다 (헤더 상태를 읽지 못했을 수 있음).")
    return False


FIND_DIALOG_TITLE = "찾기"
FIND_KEY_EDIT_ID = "txt_Key"


def _find_open_dialog_hwnd(pid, hwnd):
    """지금 열려 있는 '찾기' 창(pid 소유, 제목 '찾기')의 hwnd. 없으면 None.

    Desktop(uia).windows() 는 이 작은 대화상자를 놓치는 일이 있어(2026-09-17 실측),
    win32gui.EnumWindows + GetWindowText 로 찾는다(이건 확실히 잡았다).
    """
    found = []

    def _cb(h, _):
        if h == hwnd:
            return
        try:
            if not win32gui.IsWindowVisible(h):
                return
            _, wpid = win32process.GetWindowThreadProcessId(h)
        except Exception:
            return
        if wpid == pid and win32gui.GetWindowText(h) == FIND_DIALOG_TITLE:
            found.append(h)

    try:
        win32gui.EnumWindows(_cb, None)
    except Exception:
        pass
    return found[0] if found else None


def open_find_dialog(pid, hwnd, geo):
    """Ctrl+F 로 '찾기' 창을 연다. 창이 뜬 hwnd 를 돌려주고, 실패하면 None.

    전역 send_keys 는 '포그라운드 창'에 키를 보내므로, 그 순간 ERPia 가 포그라운드가
    아니면 Ctrl+F 가 엉뚱한 곳으로 간다(2026-09-17 실측: 클릭은 되는데 Ctrl+F 는 안 먹혔다).
    그래서 창을 확실히 포그라운드로 올리고, 그 창으로 직접 키를 보내고(type_keys),
    창이 뜰 때까지 폴링하며 몇 번 재시도한다.
    """
    x, top_y, bot_y, rh = geo
    for attempt in range(3):
        existing = _find_open_dialog_hwnd(pid, hwnd)
        if existing:
            return existing
        ec.ensure_foreground(hwnd)
        try:
            element_at_point(x, top_y).click_input()   # 그리드에 물리 클릭 -> ERPia 활성
        except Exception:
            pass
        time.sleep(0.2)
        fg_ok = ec.ensure_foreground(hwnd)
        sent = False
        try:
            # 전역 send_keys 대신 그 창으로 직접 보낸다(포그라운드도 같이 잡는다).
            Application(backend="uia").connect(handle=hwnd, timeout=3).window(
                handle=hwnd).type_keys("^f", set_foreground=True)
            sent = True
        except Exception:
            try:
                send_keys("^f")
                sent = True
            except Exception as e:
                log(f"    Ctrl+F 전송 실패: {e}")
        if not sent:
            continue
        deadline = time.time() + 2.5
        while time.time() < deadline:
            fh = _find_open_dialog_hwnd(pid, hwnd)
            if fh:
                return fh
            time.sleep(0.2)
        log(f"    찾기 창이 아직 안 뜸 (시도 {attempt + 1}/3, 포그라운드확보={fg_ok})")

    try:
        fg = win32gui.GetForegroundWindow()
        wins = []

        def _cb(h, _):
            try:
                _, wp = win32process.GetWindowThreadProcessId(h)
            except Exception:
                return
            if wp == pid and win32gui.IsWindowVisible(h):
                wins.append((h, win32gui.GetWindowText(h)[:20]))
        win32gui.EnumWindows(_cb, None)
        log(f"    [진단] 포그라운드={fg} (ERPia={hwnd}), pid 창들={wins[:8]}")
    except Exception:
        pass
    return None


def find_jump_to_code(pid, hwnd, grid, code_col, code, geo):
    """찾기(Ctrl+F)로 상품코드 덩어리 위치로 그리드를 점프시킨다.

    오름차순 정렬돼 있으면 찾기는 '가장 위의 일치 행'으로 바로 이동한다(사용자 확인).
    그래서 덩어리 앞의 수많은 페이지를 하나씩 내리지 않고 통째로 건너뛴다.
    점프해서 화면에 code 가 보이면 True. 찾기 창은 닫는다.
    """
    fhwnd = open_find_dialog(pid, hwnd, geo)
    if fhwnd is None:
        log("    찾기 창(Ctrl+F)을 열지 못했습니다.")
        return False

    ok = False
    try:
        fwin = Application(backend="uia").connect(handle=fhwnd, timeout=5).window(handle=fhwnd)
        key = next((e for e in fwin.descendants(control_type="Edit")
                    if e.element_info.automation_id == FIND_KEY_EDIT_ID), None)
        if key is None:
            log("    찾기 입력칸(txt_Key)을 찾지 못했습니다.")
        else:
            ec.ensure_foreground(fhwnd)
            key.click_input()
            time.sleep(0.2)
            # 입력칸에 직접 보낸다(전역 send_keys 는 포그라운드 의존이라 불안정).
            # ^a 로 기존 검색어를 지우고 코드 입력 후 Enter. 코드는 숫자라 특수문자 없음.
            try:
                key.type_keys("^a" + str(code) + "{ENTER}", set_foreground=True)
            except Exception:
                send_keys("^a"); send_keys(str(code)); send_keys("{ENTER}")
            time.sleep(1.0)
            ok = True
    finally:
        try:
            win32gui.PostMessage(fhwnd, win32con.WM_CLOSE, 0, 0)
        except Exception:
            pass
        time.sleep(0.4)
    if not ok:
        return False

    ec.ensure_foreground(hwnd)
    vals = [(v or "").strip() for _y, v, _el in scan_column(geo, code_col)]
    if code in vals:
        first = next((v for v in vals if v), "")
        log(f"    찾기로 상품코드 {code} 위치로 이동 (화면 첫 값 {first})")
        return True
    log(f"    찾기 후에도 화면에 상품코드 {code} 가 보이지 않습니다.")
    return False


def select_code_range_and_check(pid, hwnd, grid, code_col, code, geo):
    """정렬된 하단 그리드에서 상품코드가 일치하는 연속 구간을 범위선택하고 체크한다.

    ★ 찾기(Ctrl+F)로 덩어리 위치로 바로 점프한다. 맨 위부터 페이지를 하나씩 내리지 않는다.
      20만 행이어도 덩어리 앞은 찾기로 건너뛴다. 점프한 뒤에는 덩어리(첫~마지막 일치 행)
      그 자체만 아래로 훑어, 화면 한 장을 넘는 덩어리도 끝까지 잡는다.

    첫 일치 행 클릭(앵커) -> (스크롤) 마지막 일치 행 Shift+클릭 -> 우클릭 '선택영역 체크'.
    Shift+클릭은 앵커~클릭행 사이를 전부 선택하므로, 중간 행이 스크롤로 화면 밖에 나가도
    덩어리 전체가 선택된다 (2026-09-17 라이브에서 페이지에 걸친 건으로 확인).

    정렬이 오름차순임을 헤더가 보장하므로 구간은 한 덩어리다. 그래도 만약을 대비해
    구간을 훑는 동안 값이 오름차순이 아니면(page_order_problem) 범위선택을 하지 않고 False.
    이때 호출부는 이 건을 배송보류하지 않고 넘어간다 (개별 체크로 도망가지 않는다).

    반환: (성공여부, 우클릭 기준 요소)
    """
    if not find_jump_to_code(pid, hwnd, grid, code_col, code, geo):
        log(f"    찾기로 상품코드 {code} 위치로 이동하지 못했습니다. 범위선택을 하지 않습니다.")
        return False, None

    # 찾기가 '가장 위의 일치 행'으로 보내므로(오름차순, 사용자 확인), 화면의 첫 일치 행이
    # 덩어리 시작이다. 그 위로 다시 스크롤해 확인하지 않는다(불필요한 크롤링 제거).
    #
    # 끝은 '한 줄씩'이 아니라 '페이지 단위'로 내려가며 찾는다(grid_page_down: '페이지 아래로' 한 번).
    # 페이지 이동은 겹치지 않으므로, 덩어리 끝이 페이지 경계에 딱 걸리면 마지막 일치 행이
    # 다음 페이지에 안 보일 수 있다. 그때는 한 페이지만 올라가 마지막 일치 행을 다시 잡는다.
    first_clicked = False
    last_el = None
    pages = 0
    for _page in range(GRID_MAX_SCROLLS):
        pages += 1
        rows = [((v or "").strip(), el) for _y, v, el in scan_column(geo, code_col)]
        vals = [v for v, _el in rows]
        if not any(vals):
            break
        # 페이지 안이 오름차순인지 (정렬 안전망). 페이지끼리 겹치지 않으므로 페이지 내부만 본다.
        problem = page_order_problem(vals, None)
        if problem:
            log(f"    정렬이 어긋나 있습니다 (페이지 {pages}: {problem}). 범위선택을 하지 않습니다.")
            return False, None

        hits = [el for v, el in rows if v == code]
        filled = [v for v in vals if v]
        if hits:
            if not first_clicked:
                log(f"    첫 일치 행 클릭: {hits[0].rectangle()}")
                ec.ensure_foreground(hwnd)
                hits[0].click_input()
                time.sleep(0.4)
                first_clicked = True
            last_el = hits[-1]
            if filled and filled[-1] > code:
                break                   # 덩어리 끝이 이 페이지 안 (마지막 일치 행이 보인다)
        elif first_clicked:
            # 일치 행이 없는 페이지까지 왔다 = 덩어리 끝을 페이지 경계에서 지나쳤다.
            # 한 페이지 올라가 마지막 일치 행을 다시 잡는다.
            if grid_page_up(hwnd, grid):
                rows = [((v or "").strip(), el) for _y, v, el in scan_column(geo, code_col)]
                back_hits = [el for v, el in rows if v == code]
                if back_hits:
                    last_el = back_hits[-1]
            break
        if not grid_page_down(hwnd, grid):
            break

    if not first_clicked or last_el is None:
        log(f"    상품코드 {code} 일치 행을 찾지 못했습니다.")
        return False, None

    log(f"    마지막 일치 행 Shift+클릭: {last_el.rectangle()} (덩어리 {pages}화면)")
    ec.ensure_foreground(hwnd)
    try:
        last_el.click_input(pressed="shift")
    except Exception as e:
        log(f"    Shift+클릭 실패: {e}")
        return False, None
    time.sleep(0.6)

    if not right_click_element_and_select(pid, hwnd, last_el, "선택영역 체크"):
        log("    '선택영역 체크' 실행 실패")
        return False, None
    time.sleep(1.0)

    return True, last_el


def page_order_problem(vals, prev_last):
    """한 화면의 값 목록이 오름차순이고, 앞 화면과 겹쳐 이어지는지 본다.

    문제가 없으면 None, 있으면 사람이 읽을 설명. 빈 칸("")도 값으로 친다.
    화면을 겹치게 내리므로 이 화면의 첫 값은 앞 화면의 마지막 값보다 클 수 없다.
    크다면 사이의 행을 건너뛴 것이다.
    """
    for i in range(len(vals) - 1):
        if vals[i] > vals[i + 1]:
            return f"{vals[i] or '(빈 칸)'} 다음에 {vals[i + 1] or '(빈 칸)'}"
    if prev_last is not None and vals and vals[0] > prev_last:
        return f"앞 화면 끝 {prev_last or '(빈 칸)'} 과 이어지지 않음 (이 화면 첫 값 {vals[0]})"
    return None


def prepare_bottom_checks(pid, hwnd, grid, code, code_col, geo, cb_x):
    """배송보류 직전까지: 'ERP상품코드'를 오름차순으로 정렬하고 일치 구간만 범위선택한 뒤
    우클릭할 셀을 돌려준다. 사용자가 정한 방식 그대로다:
      1) 하단 그리드를 'ERP상품코드' 오름차순으로 정렬 (헤더 상태로 확정, 스크롤 없음)
      2) 상품코드가 일치하는 '연속 구간'을 범위선택 (첫 일치 행 ~ 마지막 일치 행)
      3) 우클릭 '선택영역 체크' 로 그 구간만 체크
    정렬이 오름차순임을 헤더가 보장하므로 구간은 반드시 한 덩어리다.
    구간을 훑는 동안 값이 오름차순이 아니면(정렬이 실제로 안 됐으면) 즉시 포기한다.

    ★ 20만 건에서도 쓰도록: 그리드 전체를 훑는 검증도, 한 행씩 클릭하는 폴백도 쓰지 않는다.
      정렬은 헤더 속성으로 O(1) 에 확정하고, 구간 선택은 클릭 2번 + 메뉴 1번으로 끝난다.
      실패하면 이 건은 배송보류하지 않고 넘어간다 (엉뚱한 행을 건드리는 것보다 안전하다).

    반환: (우클릭할 셀 또는 None, 정렬·범위선택 성공 여부)
    None 이면 배송보류를 누르면 안 된다.
    """
    if code_col is None or geo is None:
        found = find_bottom_code_column(grid, code)
        if found:
            code_col = found
            geo = _column_scan_geometry(grid, code_col)
    if geo is None:
        log("    하단 그리드의 상품코드 칸 위치를 잡지 못했습니다. 배송보류하지 않습니다.")
        return None, False

    top_v, bot_v = wait_bottom_grid_rows(hwnd, grid, geo, code_col)
    if top_v is None:
        log("    하단 그리드에 데이터가 표시되지 않아 건너뜁니다.")
        return None, False
    log(f"    하단 그리드 데이터 확인 (첫 행 {top_v} ~ 마지막 행 {bot_v})")

    if not sort_grid_ascending_by(hwnd, grid, code_col, geo):
        log("    'ERP상품코드'를 오름차순으로 정렬하지 못했습니다. "
            "이 건은 배송보류하지 않고 넘어갑니다.")
        return None, False

    ok, anchor = select_code_range_and_check(pid, hwnd, grid, code_col, code, geo)
    if not ok or anchor is None:
        # select_code_range_and_check 는 정렬이 어긋났거나 일치 행이 없으면 False 를 준다.
        # 여기서 한 행씩 다시 체크하지 않는다. 넘어간다.
        log("    범위선택에 실패했습니다. 이 건은 배송보류하지 않고 넘어갑니다.")
        return None, False

    return anchor, True



def excel_upload_dir():
    """ERPIA_AI 폴더 안의 ERPIA_AI_EXCEL 경로 (없어도 경로만 돌려준다)."""
    return os.path.join(pl.find_ai_dir(), EXCEL_UPLOAD_DIR_NAME)


def move_file_to(path, dest_dir, reason=""):
    """파일을 dest_dir 로 옮긴다. 폴더가 없으면 만들고, 이름이 겹치면 시각을 붙인다."""
    try:
        os.makedirs(dest_dir, exist_ok=True)
        dest = unique_path(os.path.join(dest_dir, os.path.basename(path)))
        shutil.move(path, dest)
        log(f"    파일 이동{f' ({reason})' if reason else ''}: {dest}")
        return True
    except Exception as e:
        log(f"    파일 이동 실패({path} -> {dest_dir}): {e}")
        return False


def collect_upload_files(folder):
    """폴더의 (nnn)~.xls(x) 파일을 사이트코드별로 모은다.

    (nnn) 은 고유해야 하므로, 같은 코드가 여럿이면 '가장 나중에 수정된 것'만 쓰고
    나머지는 오류 폴더로 보낼 목록에 담는다.
    반환: (코드->경로, 중복이라 치울 파일들, 이름 규칙에 안 맞아 건드리지 않은 파일들)
    """
    by_code = {}
    ignored = []
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        if os.path.splitext(name)[1].lower() not in EXCEL_UPLOAD_EXTS:
            ignored.append(path)
            continue
        m = EXCEL_FILE_CODE_RE.match(name)
        if not m:
            ignored.append(path)
            continue
        by_code.setdefault(m.group(1), []).append(path)

    targets = {}
    duplicates = []
    for code, paths in by_code.items():
        paths.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        targets[code] = paths[0]
        duplicates.extend(paths[1:])
    return targets, duplicates, ignored


def find_site_upload_cell(hwnd, grid, code, max_pages=GRID_MAX_SCROLLS):
    """사이트코드가 code 인 행의 '엑셀업로드' 셀과 그 값을 찾는다.

    이 그리드는 스크롤이 있고 중간에 Group Row 도 섞여 있으므로
    맨 위부터 훑으며 좌표로 두 컬럼만 읽는다.
    반환: (셀 요소, 엑셀업로드 값) - 못 찾으면 (None, None)
    """
    geo_code = _column_scan_geometry(grid, SITE_CODE_COL)
    geo_up = _column_scan_geometry(grid, EXCEL_UPLOAD_COL)
    if geo_code is None or geo_up is None:
        log(f"    '{SITE_CODE_COL}' 또는 '{EXCEL_UPLOAD_COL}' 컬럼을 찾지 못했습니다.")
        return None, None

    def look():
        x_up = geo_up[0]
        for y, value, _el in scan_column(geo_code, SITE_CODE_COL):
            if (value or "").strip() != code:
                continue
            try:
                cell = element_at_point(x_up, y)
                if cell.window_text().startswith(EXCEL_UPLOAD_COL):
                    return cell, (legacy_value(cell) or "").strip()
            except Exception:
                pass
        return None, None

    cell, val = look()
    if cell is not None:
        return cell, val

    grid_scroll_to_top(hwnd, grid)
    for _ in range(max_pages):
        cell, val = look()
        if cell is not None:
            return cell, val
        if not grid_page_down(hwnd, grid):
            break
    return look()


# 열기 대화상자의 '파일 이름' 콤보. 저장 대화상자(1001)와 ID 가 다르다.
OPEN_DIALOG_FILENAME_EDIT_ID = 1148


def find_open_dialog_filename_edit(dlg_hwnd):
    """파일 '열기' 대화상자의 '파일 이름' 입력란.

    반드시 컨트롤 ID 로 집는다. 위치나 부모 클래스로 고르면 안 된다.

    예전 구현은 'ComboBox 안의 Edit 중 가장 위에 있는 것' 을 골랐는데,
    창 맨 위의 **주소 표시줄**(Address Band, ID 41477)이 그 조건에 먼저 걸렸다.
    그러면 경로가 파일명 칸이 아니라 주소창에 들어간다. 읽어보면 경로가
    맞게 보이지만, Enter 를 눌러도 폴더만 이동하고 창은 닫히지 않는다.
    2026-09-10 에 이 증상으로 엑셀업로드가 통째로 실패했다.

    목록에 있는 파일 이름들도 Edit 으로 노출되므로 그 점도 ID 로 걸러진다.
    """
    for ctrl_id in (OPEN_DIALOG_FILENAME_EDIT_ID, SAVE_DIALOG_FILENAME_EDIT_ID):
        found = []

        def cb(h, _, _id=ctrl_id):
            try:
                if win32gui.GetClassName(h) != "Edit":
                    return True
                if win32gui.GetDlgCtrlID(h) != _id:
                    return True
                found.append((win32gui.GetWindowRect(h)[1], h))
            except Exception:
                pass
            return True

        try:
            win32gui.EnumChildWindows(dlg_hwnd, cb, None)
        except Exception:
            continue
        if found:
            # 같은 ID 가 여럿이면 위에 있는 것이 '파일 이름' 이다.
            return min(found)[1]
    return None


def dismiss_popups(app, hwnd, label="", rounds=4, wait=1.2):
    """메인 창에 떠 있는 안내 팝업을 닫고 내용을 로그로 남긴다.

    업로드 성공 여부는 사용자가 화면 우측 상단 로그로 판단하므로 여기서 판정하지 않는다.
    다만 팝업이 떠 있으면 다음 셀 클릭이 먹지 않으므로 반드시 닫아야 한다.
    반환: 닫은 팝업의 내용들
    """
    texts = []
    for _ in range(rounds):
        win = app.window(handle=hwnd)
        buttons = find_popup_buttons(win)
        if not buttons:
            break
        text = collect_popup_text(buttons[0])
        texts.append(text)
        log(f"    {label}팝업: {[b.window_text() for b in buttons]}")
        log(f"      내용: {text}")
        btn = next((b for b in buttons if b.window_text() in OK_BUTTON_TEXTS), None)
        if btn is None:
            log("      확인/예 버튼이 없어 그대로 둡니다.")
            break
        try:
            ec.ensure_foreground(hwnd)
            btn.click_input()
            time.sleep(wait)
        except Exception as e:
            log(f"      팝업 닫기 실패: {e}")
            break
    return texts


def wait_upload_result(app, hwnd, timeout=UPLOAD_RESULT_WAIT_SECONDS, interval=0.5):
    """파일을 넘긴 뒤 ERPia 가 읽기를 끝낼 때까지 기다린다.

    결과 팝업이 뜨면 그것이 '읽기가 끝났다'는 신호다. 팝업을 닫고 내용을 돌려준다.
    (자식 창 목록 확인은 win32 라 사실상 공짜라서 촘촘히 봐도 된다)
    """
    gate = PopupGate(hwnd)
    waited = 0.0
    while waited < timeout:
        if gate.should_scan():
            win = app.window(handle=hwnd)
            if find_popup_buttons(win):
                return dismiss_popups(app, hwnd, label="업로드 결과 ")
        time.sleep(interval)
        waited += interval
    log(f"    결과 팝업이 {timeout:.0f}초 안에 뜨지 않았습니다.")
    return []


def wait_file_unlocked(path, timeout=UPLOAD_FILE_RELEASE_WAIT, interval=0.5):
    """다른 프로세스가 파일을 놓을 때까지 기다린다.

    읽는 도중에 옮기면 ERPia 가 파일을 놓쳐 '헤더 개수: 0' 같은 오류가 난다.
    """
    waited = 0.0
    while waited < timeout:
        try:
            with open(path, "r+b"):
                return True
        except PermissionError:
            pass
        except Exception:
            return True  # 이미 없거나 다른 이유면 여기서 판단하지 않는다
        time.sleep(interval)
        waited += interval
    log(f"    파일이 {timeout:.0f}초 동안 잠겨 있습니다: {os.path.basename(path)}")
    return False


def _get_clipboard_text():
    try:
        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                return win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        pass
    return None


def _set_clipboard_text(text):
    for _ in range(3):
        try:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                # SetClipboardData(CF_UNICODETEXT, str) 는 pywin32 에서 힙을 망가뜨려
                # 프로세스가 0xc0000374 로 즉사한다. SetClipboardText 를 써야 한다.
                win32clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)
                return True
            finally:
                win32clipboard.CloseClipboard()
        except Exception:
            time.sleep(0.2)
    return False


def type_path_into_dialog(dlg_hwnd, edit_hwnd, path):
    """파일명 칸에 전체 경로를 넣는다 (클립보드 붙여넣기).

    이 대화상자에서는 EditWrapper.set_edit_text 가 먹지 않고,
    한글이 섞인 경로는 send_keys 타이핑도 불안정하다. 붙여넣기가 가장 확실하다.
    사용자 클립보드는 원래 내용으로 되돌려 놓는다.
    """
    saved = _get_clipboard_text()
    try:
        if not _set_clipboard_text(path):
            log("    클립보드에 경로를 넣지 못했습니다.")
            return False
        try:
            EditWrapper(edit_hwnd).click_input()
        except Exception as e:
            log(f"    파일명 칸 클릭 실패: {e}")
            return False
        time.sleep(0.2)

        # 기존 내용을 확실히 지운다.
        # 지우지 못한 채 붙여넣으면 경로가 덧붙어 '이 위치를 열 수 없습니다' 오류가 난다.
        send_keys("{END}+{HOME}{BACKSPACE}")
        time.sleep(0.2)
        leftover = (read_save_filename(edit_hwnd) or "").strip()
        if leftover:
            log(f"    파일명 칸을 비우지 못했습니다 (남은 값: {leftover!r})")
            return False

        send_keys("^v")
        time.sleep(0.3)
        typed = (read_save_filename(edit_hwnd) or "").strip().strip('"')
        if os.path.normcase(typed) == os.path.normcase(path):
            log(f"    파일명 입력 확인: {typed}")
            return True
        log(f"    파일명이 정확히 들어가지 않았습니다 (읽은 값: {typed!r})")
        return False
    finally:
        if saved is not None:
            _set_clipboard_text(saved)


DIALOG_ERROR_KEYWORDS = ("열 수 없습니다", "찾을 수 없습니다", "존재하지 않습니다")


def dismiss_dialog_error(pid, dlg_hwnd):
    """파일 대화상자 위에 뜬 오류 메시지 창을 닫는다.

    ('이 프로그램을 사용하여 이 위치를 열 수 없습니다' 등)
    이걸 닫지 않으면 대화상자를 취소할 수도 없어 다음 파일까지 막힌다.
    반환: 오류 창을 닫았으면 True
    """
    for h in find_top_hwnds_by_title(pid, "", exact=False):
        if h == dlg_hwnd:
            continue
        try:
            if win32gui.GetClassName(h) != SAVE_DIALOG_CLASS:
                continue
            dlg = connect_dialog(h)
            texts = [c.window_text() for c in dlg.descendants() if c.window_text()]
        except Exception:
            continue
        blob = " ".join(texts)
        if not any(k in blob for k in DIALOG_ERROR_KEYWORDS):
            continue
        log(f"    파일 대화상자 오류 창: {blob[:150]}")
        try:
            btn = next((c for c in dlg.descendants(control_type="Button")
                        if c.window_text() in ("확인", "확인(O)", "OK")), None)
            if btn is not None:
                btn.click_input()
                time.sleep(0.5)
                return True
        except Exception as e:
            log(f"    오류 창을 닫지 못했습니다: {e}")
    return False


def dialog_gone(dlg_hwnd, settle=2.0):
    """창이 닫힐 때까지 기다린다. 닫혔으면 True."""
    waited = 0.0
    while waited < settle:
        try:
            if not win32gui.IsWindow(dlg_hwnd) or not win32gui.IsWindowVisible(dlg_hwnd):
                return True
        except Exception:
            return True
        time.sleep(0.2)
        waited += 0.2
    return False


def submit_open_dialog(dlg_hwnd, pid=None, attempts=3, settle=2.0, edit_hwnd=None):
    """파일 열기 창을 확정한다(= '열기'를 누른 효과).

    한 가지 방법만으로는 빠져나오지 못하는 경우가 있어 세 가지를 차례로 쓴다.
    특히 경로를 붙여넣은 직후에는 파일명 칸의 자동완성 목록이 떠 있어서,
    이어지는 버튼 클릭이 그 목록을 닫는 데만 쓰이고 창은 그대로 남는다(실측).

      1) 파일명 칸에 포커스를 두고 Enter  - 사람이 하는 것과 같아 가장 잘 먹는다
      2) '열기'(IDOK) 버튼 클릭
      3) 창에 WM_COMMAND(IDOK) 전송      - 마우스/포커스와 무관하다

    각 방법마다 창이 실제로 닫혔는지 확인하고, 닫혔으면 바로 끝낸다.
    """
    for i in range(1, attempts + 1):
        # 1) 파일명 칸에서 Enter
        if edit_hwnd:
            try:
                ec.ensure_foreground(dlg_hwnd)
                EditWrapper(edit_hwnd).click_input()
                time.sleep(0.2)
                send_keys("{ENTER}")
                if dialog_gone(dlg_hwnd, settle):
                    return True
            except Exception as e:
                log(f"    파일명 칸 Enter 실패: {e}")

        # 2) '열기' 버튼 클릭
        try:
            ok = win32gui.GetDlgItem(dlg_hwnd, 1)   # IDOK = '열기(O)'
            if ok:
                ec.ensure_foreground(dlg_hwnd)
                ButtonWrapper(ok).click_input()
                if dialog_gone(dlg_hwnd, settle):
                    return True
        except Exception as e:
            log(f"    '열기' 버튼 클릭 실패: {e}")

        # 3) 창에 직접 명령 전송
        try:
            win32gui.SendMessage(dlg_hwnd, win32con.WM_COMMAND, 1, 0)
            if dialog_gone(dlg_hwnd, settle):
                return True
        except Exception as e:
            log(f"    WM_COMMAND 전송 실패: {e}")

        # 경로가 잘못되면 오류 메시지 창이 뜨고 대화상자는 그대로 남는다.
        if pid is not None and dismiss_dialog_error(pid, dlg_hwnd):
            return False
        log(f"    창이 아직 열려 있습니다 (시도 {i}/{attempts})")
    return False


def double_click_file_in_dialog(dlg_hwnd, path):
    """대화상자 목록에서 파일 이름을 찾아 더블클릭한다.

    대화상자는 보통 우리가 원하는 폴더에서 열리므로 이 방법이 가장 단순하고 확실하다.
    (확장자 표시가 꺼져 있으면 이름만 보이므로 둘 다 본다)
    """
    name = os.path.basename(path)
    stem = os.path.splitext(name)[0]
    try:
        dlg = connect_dialog(dlg_hwnd)
        for item in dlg.descendants(control_type="ListItem"):
            txt = item.window_text()
            if txt == name or txt == stem:
                log(f"    목록 항목 더블클릭: '{txt}'")
                item.double_click_input()
                return True
    except Exception as e:
        log(f"    목록 더블클릭 실패: {e}")
    log("    목록에서 파일을 찾지 못했습니다 (다른 폴더에서 열린 듯).")
    return False


def upload_file_in_dialog(dlg_hwnd, path, pid=None):
    """파일 열기 창에서 지정한 파일을 연다.

    1) 목록에서 더블클릭 - 대화상자가 그 폴더에서 열렸을 때 가장 확실하다.
    2) 없으면 파일명 칸에 전체 경로를 넣고 '열기' - 다른 폴더에서 열린 경우 대비.
    """
    if double_click_file_in_dialog(dlg_hwnd, path):
        return True

    log("    파일명 칸에 전체 경로를 넣어 다시 시도합니다.")
    edit = find_open_dialog_filename_edit(dlg_hwnd)
    if edit is None:
        log("    파일명 입력란을 찾지 못했습니다.")
        return False
    if not type_path_into_dialog(dlg_hwnd, edit, path):
        return False
    return submit_open_dialog(dlg_hwnd, pid=pid, edit_hwnd=edit)


def open_upload_dialog(pid, hwnd, cell):
    """'엑셀업로드' 셀을 눌러 파일 열기 창을 띄운다. 한 번 눌러 안 뜨면 더블클릭."""
    for attempt, how in ((1, "클릭"), (2, "더블클릭")):
        ec.ensure_foreground(hwnd)
        try:
            if how == "클릭":
                cell.click_input()
            else:
                cell.double_click_input()
        except Exception as e:
            log(f"    셀 {how} 실패: {e}")
            continue
        dlg = wait_save_dialog(pid, timeout=OPEN_DIALOG_WAIT_SECONDS)
        if dlg is not None:
            log(f"    파일 열기 창 확인 ({how}): hwnd={dlg}")
            return dlg
        log(f"    {how} 후 파일 열기 창이 뜨지 않았습니다.")
    return None


def run_excel_upload_step(app, pid, hwnd, grid, move_files=True):
    """바탕화면 ERPIA_AI_EXCEL 폴더의 엑셀을 사이트코드에 맞춰 업로드한다.

    - 폴더가 없거나 비어 있으면 아무것도 하지 않는다.
    - 업로드가 끝난 파일은 완료/YYYYMMDD 로, 올릴 수 없거나 실패한 파일은 오류 폴더로 옮긴다.
      오류로 가는 경우: 사이트코드 행이 없음 / 그 사이트가 엑셀업로드 미지원 /
      사이트코드 중복(최신 1개만 사용) / 업로드 후 오류 팝업이 뜸
    - 성공/실패는 팝업 유무로 가른다. 정상이면 팝업이 아예 뜨지 않고,
      실패하면 사유와 함께 확인 팝업이 뜬다(실측). 자세한 결과는 화면 우측 상단 로그에서 본다.
    반환: (업로드한 수, 오류로 보낸 수)
    """
    folder = excel_upload_dir()
    if not os.path.isdir(folder):
        log(f"  '{EXCEL_UPLOAD_DIR_NAME}' 폴더가 없습니다 -> 엑셀업로드를 건너뜁니다.")
        status.metric("excel_upload", "엑셀 업로드", 0, 0, unit="개", note="폴더 없음")
        return 0, 0

    targets, duplicates, ignored = collect_upload_files(folder)
    if not targets and not duplicates:
        log(f"  '{EXCEL_UPLOAD_DIR_NAME}' 폴더에 올릴 파일이 없습니다 -> 건너뜁니다.")
        status.metric("excel_upload", "엑셀 업로드", 0, 0, unit="개", note="올릴 파일 없음")
        return 0, 0

    log(f"  업로드 대상 {len(targets)}건: "
        f"{[(c, os.path.basename(p)) for c, p in sorted(targets.items())]}")
    if ignored:
        log(f"  이름 규칙에 맞지 않아 건드리지 않은 파일 {len(ignored)}건: "
            f"{[os.path.basename(p) for p in ignored]}")

    error_dir = os.path.join(folder, EXCEL_UPLOAD_ERROR_DIR)
    done_dir = os.path.join(folder, EXCEL_UPLOAD_DONE_DIR, time.strftime("%Y%m%d"))

    errors = 0
    failed = 0
    for path in duplicates:
        log(f"  사이트코드가 중복된 파일: {os.path.basename(path)}")
        if not move_files:
            log("    (검증 모드: 파일을 옮기지 않습니다)")
            continue
        if move_file_to(path, error_dir, "중복 - 최신 파일만 사용"):
            errors += 1

    uploaded = 0
    status.metric("excel_upload", "엑셀 업로드", 0, len(targets), unit="개")
    status.progress(0, len(targets))
    for idx, (code, path) in enumerate(sorted(targets.items()), 1):
        name = os.path.basename(path)
        log(f"  [{idx}/{len(targets)}] 사이트코드={code} 파일={name}")
        status.note(f"{idx}/{len(targets)} · {name}")
        status.progress(idx - 1, len(targets), name)

        cell, value = find_site_upload_cell(hwnd, grid, code)
        if cell is None:
            log(f"    사이트코드 {code} 인 행을 찾지 못했습니다.")
            if move_files and move_file_to(path, error_dir, "사이트코드 없음"):
                errors += 1
            continue

        if value != EXCEL_UPLOAD_ENABLED:
            log(f"    이 사이트는 엑셀업로드를 지원하지 않습니다 "
                f"('{EXCEL_UPLOAD_COL}'={value!r}).")
            if move_files and move_file_to(path, error_dir, "엑셀업로드 미지원 사이트"):
                errors += 1
            continue

        # 앞 파일의 결과 팝업이 남아 있으면 셀 클릭이 먹지 않는다.
        dismiss_popups(app, hwnd, label="클릭 전 남아있던 ")

        log(f"    '{EXCEL_UPLOAD_COL}' 셀 클릭: {cell.rectangle()}")
        dlg = open_upload_dialog(pid, hwnd, cell)
        if dlg is None:
            log("    파일 열기 창을 띄우지 못했습니다 -> 파일은 그대로 두고 넘어갑니다.")
            continue

        if not upload_file_in_dialog(dlg, path, pid=pid):
            log("    파일을 넘기지 못했습니다. 창을 닫고 파일은 그대로 둡니다.")
            dismiss_dialog_error(pid, dlg)   # 오류 창이 떠 있으면 취소도 안 먹는다
            cancel_save_dialog(dlg)
            continue

        # 창이 닫혔는지로 '넘겼다'를 확인한다 (업로드 결과 자체는 사용자가 로그로 본다)
        closed = False
        waited = 0.0
        while waited < OPEN_DIALOG_WAIT_SECONDS:
            if not win32gui.IsWindow(dlg) or not win32gui.IsWindowVisible(dlg):
                closed = True
                break
            time.sleep(0.5)
            waited += 0.5

        if not closed:
            log("    파일 열기 창이 닫히지 않았습니다. 취소하고 파일은 그대로 둡니다.")
            dismiss_dialog_error(pid, dlg)
            cancel_save_dialog(dlg)
            continue

        log("    파일을 넘겼습니다. ERPia 가 읽기를 끝낼 때까지 기다립니다.")
        popups = wait_upload_result(app, hwnd)
        # 읽는 도중에 옮기면 ERPia 가 파일을 놓친다. 잠금이 풀린 뒤에 옮긴다.
        wait_file_unlocked(path)

        # 정상 업로드면 팝업이 뜨지 않고, 실패하면 사유와 함께 확인 팝업이 뜬다(실측).
        if popups:
            log(f"    업로드 실패로 판단합니다 (팝업 {len(popups)}건).")
            failed += 1
            status.progress(uploaded, len(targets))
            status.metric("excel_upload", "엑셀 업로드", uploaded, len(targets),
                          unit="개", note=f"실패 {failed}개")
            if move_files:
                move_file_to(path, error_dir, "업로드 실패")
                errors += 1
            else:
                log("    (검증 모드: 파일을 옮기지 않습니다)")
        else:
            log("    업로드 완료 (오류 팝업 없음)")
            uploaded += 1
            status.progress(uploaded, len(targets))
            status.metric("excel_upload", "엑셀 업로드", uploaded, len(targets), unit="개",
                          note=(f"실패 {failed}개" if failed else None))
            if move_files:
                move_file_to(path, done_dir, "업로드 완료")
            else:
                log("    (검증 모드: 파일을 옮기지 않습니다)")
        time.sleep(1.0)

    log(f"  엑셀업로드 완료: 업로드 {uploaded}건 / 업로드 실패 {failed}건 "
        f"/ 오류 폴더로 옮긴 파일 {errors}건")
    return uploaded, errors


def find_top_qty_cell_by_code(geo_code, geo_qty, code):
    """상단 그리드에서 상품코드가 일치하는 행의 '부족수량' 셀을 좌표로 찾는다.

    행 전체(행x컬럼)를 열거하면 건마다 1.5초쯤 걸린다. 필요한 두 컬럼만 읽으면 된다.
    화면 밖으로 스크롤된 행은 못 찾으므로, 못 찾으면 호출측이 기존 방식으로 되돌아간다.
    """
    x_qty = geo_qty[0]
    for y, value, _el in scan_column(geo_code, STOCK_TOP_CODE_COL):
        if (value or "").strip() != code:
            continue
        try:
            el = element_at_point(x_qty, y)
            if el.window_text().startswith(STOCK_SHORTAGE_COL):
                return el
        except Exception:
            pass
    return None


def run_stock_review_step(app, pid, hwnd):
    """'상품별 재고검토' 탭에서 부족수량이 있는 모든 건을 배송보류 처리한다.

    상단 그리드의 부족수량 셀을 클릭하면 하단 그리드가 관련 주문들로 채워진다.
    하단에는 그 상품이 아닌 행(배송비 등)도 섞여 있으므로 전체선택하면 안 되고,
    상단 '상품코드'와 값이 완벽히 일치하는 행만 골라 체크한 뒤 우클릭 '배송보류'를 누른다.
    이것을 부족수량 건마다 반복한다.

    속도를 위해 그리드/컬럼 좌표는 화면에 들어올 때 한 번만 찾아 재사용한다.
    (창 전체를 훑는 조회는 한 번에 5초쯤 걸려, 건마다 부르면 그것만으로 수 분이 된다)

    우클릭 '배송보류'를 누르는 순간 그 건은 DB에 저장된다 (저장(S)를 기다리지 않는다).
    되돌리려면 화면에서 '배송보류해지'를 해야 하므로, 대상 선별이 틀리지 않았는지를
    누르기 전에 확인한다.

    반환: (처리건수, 전체대상건수)
    """
    if not click_subtab(app, hwnd, STOCK_TAB_NAME):
        return 0, 0

    win = app.window(handle=hwnd)
    tables = get_onscreen_tables(win)
    if len(tables) < 2:
        log("  상품별 재고검토 화면의 그리드를 찾지 못했습니다 (2개 필요).")
        return 0, 0
    top_grid = min(tables, key=lambda t: t.rectangle().top)
    bottom_grid = max(tables, key=lambda t: t.rectangle().top)
    log(f"  상단 그리드={top_grid.rectangle()} / 하단 그리드={bottom_grid.rectangle()}")

    # 조회 전 오버레이 개수를 기준선으로 잡아두고, 조회 후 스피너가 사라질 때까지 기다린다.
    base_overlays = grid_overlay_count(hwnd, top_grid)

    log("  '조회(F)' 클릭 (상품별 재고검토)")
    click_toolbar_button(win, hwnd, "조회(F)")
    time.sleep(2)
    wait_grid_spinner_gone(hwnd, top_grid, base_overlays, label="재고검토 상단")

    targets, reached_bottom = collect_shortage_rows(hwnd, top_grid)
    log(f"  부족수량이 있는 행 {len(targets)}건 "
        f"(상단 그리드 마지막 행까지 확인: {'완료' if reached_bottom else '미완료'}): "
        f"{[(k[0], q) for k, q in targets]}")
    if not reached_bottom:
        log("  경고: 상단 그리드를 끝까지 훑지 못했습니다. 누락된 부족수량 건이 있을 수 있습니다.")
    if not targets:
        log("  부족수량이 있는 행이 없습니다. 배송보류할 대상이 없습니다.")
        status.metric("stock_hold", "재고검토 보류", 0, 0, note="대상 없음")
        click_subtab(app, hwnd, STOCK_GENERAL_TAB_NAME)
        return 0, 0

    # 상단 그리드에서 대상 행을 다시 찾을 때 쓸 컬럼 좌표 (한 번만 구한다)
    top_code_geo = _column_scan_geometry(top_grid, STOCK_TOP_CODE_COL)
    top_qty_geo = _column_scan_geometry(top_grid, STOCK_SHORTAGE_COL)

    # 하단 그리드의 상품코드 컬럼 좌표는 이 화면에 머무는 동안 바뀌지 않으므로 한 번만 구한다.
    # (새 방식은 '선택영역 체크' 메뉴로 처리하므로 체크박스 컬럼 x좌표(cb_x)는 필요 없다.
    #  cb_x 는 옛 인자 호환을 위해 넘기기만 하고 실제로는 쓰지 않는다.)
    code_col = find_bottom_code_column_by_header(bottom_grid)
    geo = _column_scan_geometry(bottom_grid, code_col) if code_col else None
    cb_x = checkbox_column_x(bottom_grid)
    if geo is None:
        log("  하단 그리드의 상품코드 컬럼을 헤더로 찾지 못했습니다. 건마다 값으로 다시 찾습니다.")
    else:
        log(f"  하단 그리드 상품코드 컬럼: '{code_col}' (x={geo[0]})")

    done = 0
    status.metric("stock_hold", "재고검토 보류", 0, len(targets))
    status.progress(0, len(targets))
    for idx, (key, qty) in enumerate(targets, 1):
        code = (key[0] or "").strip()
        log(f"  [{idx}/{len(targets)}] 상품코드={code} 부족수량={qty}")
        status.note(f"{idx}/{len(targets)}건째 · 상품코드 {code}")
        status.progress(idx - 1, len(targets), f"상품코드 {code}")
        if not code:
            log("    상단 행의 상품코드를 읽지 못해 건너뜁니다.")
            continue
        if code in STOCK_EXCLUDED_CODES:
            log("    제외 상품코드입니다 -> 배송보류하지 않고 넘어갑니다.")
            continue

        cell = None
        if top_code_geo is not None and top_qty_geo is not None:
            cell = find_top_qty_cell_by_code(top_code_geo, top_qty_geo, code)
        if cell is None:
            # 스크롤로 화면 밖에 있거나 좌표를 못 잡은 경우 (스크롤하며 찾는다)
            cell = find_row_cell_by_key(hwnd, top_grid, key, STOCK_SHORTAGE_COL)
        if cell is None:
            log("    해당 행을 다시 찾지 못해 건너뜁니다.")
            continue

        # 스크롤로 행이 화면 안으로 올라오면 좌표만으로는 어느 행을 눌렀는지 알 수 없으므로,
        # 클릭 직전에 그 셀의 값을 다시 읽어 수집 당시 값과 같은지 로그로 남긴다.
        actual = (legacy_value(cell) or "").strip()
        log(f"    부족수량 셀 클릭: {cell.rectangle()} (셀 값={actual})")
        if actual != qty:
            log(f"    경고: 수집 당시 부족수량({qty})과 클릭 대상 값({actual})이 다릅니다.")
        ec.ensure_foreground(hwnd)
        cell.click_input()
        time.sleep(0.6)

        # 오름차순 정렬 -> 일치 구간 범위선택 -> '선택영역 체크' 까지 끝낸 뒤 우클릭할 셀을 받는다.
        # 정렬이 오름차순임을 헤더가 보장하므로 구간은 한 덩어리다 (그리드 전체를 훑지 않는다).
        # 우클릭은 반드시 그 선택 구간 안의 셀 위에서 한다 (prepare_bottom_checks 가 그 셀을 준다).
        anchor, _used_fast = prepare_bottom_checks(
            pid, hwnd, bottom_grid, code, code_col, geo, cb_x)
        if anchor is None:
            continue

        # 팝업 조회(find_popup_ok_button)는 창 전체를 훑어 회당 5초쯤 걸린다.
        # 이 앱의 팝업은 자식 창으로 뜨므로, 자식 창 수가 늘었을 때만 조회한다.
        # (자식 창 세기는 win32 호출이라 사실상 공짜다)
        children_before = len(visible_child_windows(hwnd))

        if not right_click_element_and_select(pid, hwnd, anchor, "배송보류"):
            log("    '배송보류' 실행 실패 -> 건너뜁니다.")
            continue
        time.sleep(1.2)

        # 확인 팝업이 뜨면 처리
        for _ in range(2):
            if len(visible_child_windows(hwnd)) <= children_before:
                break  # 새로 뜬 창이 없다 = 팝업 없음
            win = app.window(handle=hwnd)
            btn = find_popup_ok_button(win)
            if btn is None:
                break
            log(f"    배송보류 확인 팝업 -> '{btn.window_text()}' 클릭")
            ec.ensure_foreground(hwnd)
            btn.click_input()
            time.sleep(1.5)

        # 배송보류 클릭 후에는 따로 검증하지 않고 바로 다음 부족수량 셀로 넘어간다.
        # (이 화면은 처리 직후 '보류' 컬럼을 다시 읽으면 값이 제대로 보이지 않는 버그가 있다)
        log("    배송보류 실행 완료 -> 다음 건으로 진행")
        done += 1
        status.metric("stock_hold", "재고검토 보류", done, len(targets))
        status.progress(done, len(targets))

    log(f"  상품별 재고검토 처리 완료: {done}/{len(targets)}건")

    click_subtab(app, hwnd, STOCK_GENERAL_TAB_NAME)
    return done, len(targets)


# ---------------------------------------------------------------------------
# 물류 관리 > 배송정보설정 (업체/박스/구분 콤보 선택 + 적용)
# ---------------------------------------------------------------------------
# (콤보 automation_id, '적용' 버튼 automation_id, 화면상 라벨)
# 실제로 고를 값은 사용자 설정의 "Logistic" 섹션에서 콤보 automation_id 를 키로 읽는다.
# automation_id 는 창 크기/해상도와 무관하게 고정이라 좌표보다 안전하다.
SHIPPING_CONTROLS = (
    ("cboTag", "cmdTag", "업체"),
    ("cboTagAmt", "cmdTagAmt", "박스"),
    ("cboBeasong_Gu_Apply", "cmdBeasong_Gu_Apply", "구분"),
)
# 드롭다운 목록이 콤보에 붙어 있다고 볼 수 있는 최대 간격(px)
DROPDOWN_ATTACH_TOL = 24
# 드롭다운 목록에서 값을 찾기 위해 스크롤할 최대 페이지 수
DROPDOWN_MAX_SCROLL = 40
# 화면이 막 다시 그려진 직후에는 드롭다운을 열어도 항목이 비어 보일 수 있어 다시 열어본다
DROPDOWN_OPEN_RETRIES = 3

# 자동/수동 모드 콤보. 이 값에 따라 상단 버튼 배치가 통째로 바뀐다.
#   자동 -> '운송장출력' / 수동 -> '엑셀파일생성'
# 업체에 따라 이 콤보가 화면에 없을 수 있다(Visible=False).
AUTO_MODE_COMBO = "cboBS_Auto_YN"
AUTO_MODE_CONFIG_AUTO = ("A", "Y")  # 설정값이 이 중 하나면 자동, 그 외("N" 등)는 수동
AUTO_MODE_LABEL = {True: "자동", False: "수동"}
AUTO_MODE_BUTTON = {True: "운송장출력", False: "엑셀파일생성"}


# automation_id 로 찾은 요소와 그 부모 패널을 기억해 둔다.
# 메인 창 전체를 훑으면 그리드 행까지 포함해 5천 개가 넘어 한 번에 15초 이상 걸린다.
# 툴바/조회조건 컨트롤은 작은 패널 안에 모여 있으므로, 패널만 기억해 두면 이후는 거의 즉시다.
_AUTO_ID_ELEMENT_CACHE = {}
_AUTO_ID_PANEL_CACHE = {}


def _element_usable(el, auto_id=None):
    """캐시해 둔 요소가 아직 살아 있고 같은 컨트롤인지 확인한다."""
    if el is None:
        return False
    try:
        r = el.rectangle()
        if r.width() <= 0 or r.height() <= 0:
            return False
        if auto_id is not None and el.element_info.automation_id != auto_id:
            return False
    except Exception:
        return False
    return True


def _scan_for_auto_id(scope, auto_id, win_rect):
    """주어진 범위 안에서 automation_id 로 화면에 보이는 컨트롤을 찾는다."""
    try:
        items = scope.descendants()
    except Exception:
        return None
    for c in items:
        try:
            if c.element_info.automation_id != auto_id:
                continue
            r = c.rectangle()
        except Exception:
            continue
        if r.width() <= 0 or r.height() <= 0:
            continue
        if r.left < win_rect.left or r.top < win_rect.top:
            continue  # 숨은 화면(음수 좌표)
        return c
    return None


def find_by_auto_id(win, auto_id):
    """automation_id 로 화면 안에 보이는 컨트롤을 찾는다.

    1) 지난번에 찾은 요소가 그대로 쓸 수 있으면 그것을 쓴다.
    2) 아니면 지난번에 기억해 둔 부모 패널 안에서만 찾는다 (요소 수십 개).
    3) 그것도 안 되면 창 전체를 훑는다 (느리므로 마지막 수단).
    화면 모드가 바뀌어 컨트롤이 다시 그려지면 1)2)가 실패하고 자동으로 3)으로 간다.
    """
    key = (win.handle, auto_id)

    cached = _AUTO_ID_ELEMENT_CACHE.get(key)
    if _element_usable(cached, auto_id):
        return cached

    wr = win.rectangle()

    panel = _AUTO_ID_PANEL_CACHE.get(key)
    if _element_usable(panel):
        found = _scan_for_auto_id(panel, auto_id, wr)
        if found is not None:
            _AUTO_ID_ELEMENT_CACHE[key] = found
            return found

    found = _scan_for_auto_id(win, auto_id, wr)
    if found is None:
        return None

    _AUTO_ID_ELEMENT_CACHE[key] = found
    # 다음번을 위해 부모 패널을 기억해 둔다 (창 전체보다 훨씬 작다)
    try:
        parent = found.parent()
        if parent is not None and parent.handle != win.handle:
            _AUTO_ID_PANEL_CACHE[key] = parent
    except Exception:
        pass
    return found


def prefetch_auto_ids(win, auto_ids):
    """automation_id 여러 개를 '한 번의' 트리 순회로 찾아 캐시한다.

    하나씩 찾으면 그때마다 창 전체(그리드 행 포함 수천 개)를 훑어 개당 15초 이상 걸린다.
    한 번만 훑어서 필요한 것을 모두 담아 두면 전체가 그 한 번으로 끝난다.
    """
    wanted = {a for a in auto_ids
              if not _element_usable(_AUTO_ID_ELEMENT_CACHE.get((win.handle, a)), a)}
    if not wanted:
        return 0

    t0 = time.time()
    wr = win.rectangle()
    found = 0
    try:
        items = win.descendants()
    except Exception as e:
        log(f"  컨트롤 미리 찾기 실패(무시): {e}")
        return 0

    for c in items:
        try:
            aid = c.element_info.automation_id
            if aid not in wanted:
                continue
            r = c.rectangle()
            if r.width() <= 0 or r.height() <= 0:
                continue
            if r.left < wr.left or r.top < wr.top:
                continue  # 숨은 화면(음수 좌표)
        except Exception:
            continue
        key = (win.handle, aid)
        _AUTO_ID_ELEMENT_CACHE[key] = c
        try:
            parent = c.parent()
            if parent is not None and parent.handle != win.handle:
                _AUTO_ID_PANEL_CACHE[key] = parent
        except Exception:
            pass
        wanted.discard(aid)
        found += 1
        if not wanted:
            break

    log(f"  컨트롤 미리 찾기: {found}개 캐시 ({time.time() - t0:.1f}초, 요소 {len(items)}개)")
    return found


def combo_value(combo):
    """콤보의 현재 값. 껍데기 컨트롤은 값이 비어 있으므로 자식까지 본다."""
    v = (legacy_value(combo) or "").strip()
    if v:
        return v
    try:
        for c in combo.descendants():
            v = (legacy_value(c) or "").strip()
            if v:
                return v
    except Exception:
        pass
    return ""


def find_dropdown_list(win, combo_rect, tol=DROPDOWN_ATTACH_TOL):
    """콤보 바로 아래(또는 위)에 열린 드롭다운 목록을 찾는다.

    그리드 행들도 ListItem 으로 잡히므로, 반드시 '콤보에 붙어 있는 List 컨테이너'를
    먼저 찾고 그 안에서만 항목을 읽어야 한다.

    창 전체에서 List 를 훑으면 5초 이상 걸리므로, 먼저 콤보 바로 바깥 지점을
    ElementFromPoint 로 찍어 List 조상을 타고 올라간다 (수십 ms).
    """
    x = combo_rect.left + max(10, combo_rect.width() // 4)
    for y in (combo_rect.bottom + 8, combo_rect.bottom + 20,
              combo_rect.top - 8, combo_rect.top - 20):
        try:
            node = element_at_point(x, y)
        except Exception:
            continue
        for _ in range(4):
            try:
                if str(node.element_info.control_type) == "List":
                    r = node.rectangle()
                    if r.width() > 0 and r.height() > 0:
                        return node
                node = node.parent()
            except Exception:
                break

    for lst in win.descendants(control_type="List"):
        try:
            r = lst.rectangle()
        except Exception:
            continue
        if r.width() <= 0 or r.height() <= 0:
            continue
        if r.right < combo_rect.left or r.left > combo_rect.right:
            continue  # 가로로 안 겹침
        # 아래로 펼쳐졌거나(위쪽 기준) 위로 펼쳐졌거나(아래쪽 기준)
        if abs(r.top - combo_rect.bottom) <= tol or abs(r.bottom - combo_rect.top) <= tol:
            return lst
    return None


def dropdown_items(lst):
    """드롭다운 목록에 현재 렌더링된 항목: [(텍스트, 요소)]"""
    out = []
    try:
        items = lst.descendants(control_type="ListItem")
    except Exception:
        return out
    lr = lst.rectangle()
    for it in items:
        try:
            r = it.rectangle()
        except Exception:
            continue
        if r.height() <= 0:
            continue
        if r.top < lr.top - 2 or r.bottom > lr.bottom + 2:
            continue
        out.append((it.window_text(), it))
    return out


def open_combo(hwnd, combo):
    """콤보의 오른쪽 화살표를 눌러 드롭다운을 연다."""
    r = combo.rectangle()
    ec.ensure_foreground(hwnd)
    combo.click_input(coords=(max(4, r.width() - 8), r.height() // 2))
    time.sleep(1.0)


def _scan_dropdown(hwnd, lst, value):
    """열려 있는 드롭다운을 훑어 (완전일치 요소, 확인한 항목들)을 돌려준다.

    드롭다운은 '현재 선택값이 보이도록' 스크롤된 상태로 열리므로,
    곧바로 아래로만 훑으면 위쪽 항목을 통째로 놓친다. 먼저 맨 위로 올린 뒤 내려온다.
    """
    def scroll(name):
        # 스크롤바는 반드시 드롭다운 안에서만 찾는다
        # (부모까지 훑으면 화면 전체를 뒤져 느려진다)
        try:
            vsb = next((sb for sb in lst.descendants(control_type="ScrollBar")
                        if sb.rectangle().width() > 0
                        and sb.rectangle().height() > sb.rectangle().width()), None)
        except Exception:
            return False
        if vsb is None:
            return False  # 스크롤이 없다 = 전체가 한 화면
        btn = next((c for c in vsb.descendants() if c.window_text() == name), None)
        if btn is None:
            return False  # 그 방향 끝에 닿았다
        try:
            r = btn.rectangle()
            if r.width() <= 0 or r.height() <= 0:
                return False
            ec.ensure_foreground(hwnd)
            btn.click_input()
        except Exception:
            return False
        time.sleep(0.35)
        return True

    for _ in range(DROPDOWN_MAX_SCROLL):
        if not scroll("페이지 위로"):
            break

    seen = []
    for _ in range(DROPDOWN_MAX_SCROLL):
        for text, el in dropdown_items(lst):
            if text not in seen:
                seen.append(text)
            if text == value:  # 완전 일치만
                return el, seen
        if not scroll("페이지 아래로"):
            break  # 맨 아래까지 봤다
    return None, seen


def select_in_combo(win_provider, hwnd, combo_provider, value, label="",
                    retries=DROPDOWN_OPEN_RETRIES):
    """콤보를 열고 value 와 '완전히 일치하는' 항목을 골라 클릭한다.

    부분 일치를 쓰면 '중'을 고르려다 '김영중테스트'를 고르는 사고가 나므로
    반드시 완전 일치만 인정한다. 목록이 길면 스크롤하며 찾는다.

    화면이 막 다시 그려진 직후에는 드롭다운을 열어도 항목이 하나도 안 잡히는 경우가 있어
    (목록이 비어 보임) 몇 번 다시 열어본다.

    메인 창뿐 아니라 별도 대화상자(인쇄 대화상자 등)의 콤보에도 쓸 수 있도록
    '창을 얻는 함수'와 '콤보를 얻는 함수'를 받는다. 재시도할 때마다 새로 얻으므로
    화면이 다시 그려져 요소가 무효가 되어도 안전하다.
    """
    combo = combo_provider()
    if combo is None:
        log(f"  '{label}' 콤보를 찾지 못했습니다.")
        return False

    before = combo_value(combo)
    log(f"  '{label}' 콤보 열기: {combo.rectangle()} (현재값='{before}')")

    target = None
    seen = []
    for attempt in range(1, retries + 1):
        combo = combo_provider()
        if combo is None:
            break
        open_combo(hwnd, combo)

        win = win_provider()
        lst = find_dropdown_list(win, combo.rectangle())
        if lst is not None:
            target, seen = _scan_dropdown(hwnd, lst, value)
            if target is not None:
                break
            if seen:
                break  # 목록은 제대로 읽혔는데 그 값이 없는 것 -> 재시도해도 같다
            log(f"  '{label}' 드롭다운 항목이 비어 있습니다 (시도 {attempt}/{retries})")
        else:
            log(f"  '{label}' 드롭다운 목록을 찾지 못했습니다 (시도 {attempt}/{retries})")

        try:
            send_keys("{ESC}")
        except Exception:
            pass
        time.sleep(1.0)

    if target is None:
        log(f"  '{label}' 목록에서 '{value}'와 완전히 일치하는 항목을 찾지 못했습니다. "
            f"(확인한 항목: {seen[:30]}{' ...' if len(seen) > 30 else ''})")
        try:
            send_keys("{ESC}")
        except Exception:
            pass
        return False

    log(f"  '{label}' 항목 '{value}' 클릭: {target.rectangle()}")
    ec.ensure_foreground(hwnd)
    target.click_input()
    time.sleep(0.8)

    combo = combo_provider()
    after = combo_value(combo) if combo is not None else ""
    if after != value:
        log(f"  경고: '{label}' 선택 후 값이 '{after}' 입니다 (기대: '{value}').")
        return False
    log(f"  '{label}' 값 확인: '{after}'")
    return True


def select_combo_value(app, hwnd, combo_auto_id, value, label="",
                       retries=DROPDOWN_OPEN_RETRIES):
    """메인 창에서 automation_id 로 콤보를 찾아 값을 고른다."""
    return select_in_combo(
        lambda: app.window(handle=hwnd),
        hwnd,
        lambda: find_by_auto_id(app.window(handle=hwnd), combo_auto_id),
        value, label, retries)


def click_button_by_auto_id(app, hwnd, auto_id, label=""):
    win = app.window(handle=hwnd)
    btn = find_by_auto_id(win, auto_id)
    if btn is None:
        log(f"  '{label}' 버튼({auto_id})을 찾지 못했습니다.")
        return False
    log(f"  '{label}' 적용 클릭: {btn.rectangle()}")
    ec.ensure_foreground(hwnd)
    btn.click_input()
    time.sleep(1.0)
    return True


def resolve_auto_mode(options):
    """설정값으로 자동/수동을 결정한다. 'A' 또는 'Y' 면 자동, 그 외(키가 없는 경우 포함)는 수동."""
    raw = str(options.get(AUTO_MODE_COMBO) or "").strip().upper()
    return raw in AUTO_MODE_CONFIG_AUTO


def current_auto_mode(app, hwnd):
    """지금 화면의 실제 모드가 자동인지.

    콤보가 화면에 없으면(업체에 따라 Visible=False) 수동으로 간주한다.
    """
    win = app.window(handle=hwnd)
    combo = find_by_auto_id(win, AUTO_MODE_COMBO)
    if combo is None:
        return False
    return combo_value(combo) == AUTO_MODE_LABEL[True]


def apply_auto_mode(app, hwnd, options):
    """설정값에 따라 cboBS_Auto_YN 을 맞추고, '실제로 적용된 모드'를 돌려준다.

    수동으로 간주하는 경우 (= '엑셀파일생성'을 눌러야 하는 경우):
      - 설정에 cboBS_Auto_YN 키가 없을 때
      - 값이 "A"/"Y" 가 아닐 때 (예: "N")
      - 콤보 컨트롤 자체가 화면에 없을 때 (업체에 따라 Visible=False)

    이 값이 바뀌면 상단 버튼 배치와 상단 그리드 컬럼이 통째로 바뀌므로
    버튼을 누르기 전에 반드시 먼저 맞춰야 한다.

    반환: (실제 적용된 자동 여부, 성공 여부)
    """
    want_auto = resolve_auto_mode(options)
    raw = options.get(AUTO_MODE_COMBO)
    log(f"  설정값 '{AUTO_MODE_COMBO}'={raw!r} -> 원하는 모드 '{AUTO_MODE_LABEL[want_auto]}'")

    win = app.window(handle=hwnd)
    combo = find_by_auto_id(win, AUTO_MODE_COMBO)
    if combo is None:
        log(f"  '{AUTO_MODE_COMBO}' 콤보가 화면에 없습니다 (업체에 따라 없을 수 있음). "
            f"-> '수동'으로 간주합니다.")
        return False, True

    current = combo_value(combo)
    want = AUTO_MODE_LABEL[want_auto]
    if current == want:
        log(f"  자동/수동 = '{current}' (이미 설정값과 같아 바꾸지 않음)")
        return want_auto, True

    log(f"  자동/수동 '{current}' -> '{want}' 로 변경")
    if not select_combo_value(app, hwnd, AUTO_MODE_COMBO, want, "자동/수동"):
        return current_auto_mode(app, hwnd), False
    time.sleep(2.0)  # 상단 버튼이 다시 그려질 시간
    return want_auto, True


def run_shipping_setup_step(app, pid, hwnd, options=None):
    """물류 관리 화면 '배송정보설정': 업체/박스/구분을 각각 고르고 '적용'을 누른다.

    고를 값은 사용자 설정의 "Logistic" 섹션에서 읽는다.
    이 값들은 로그인 세션마다 기본값으로 돌아가므로 루틴이 매번 명시적으로 설정해야 한다.
    """
    if options is None:
        options = pl.load_logistic_options()
    log(f"  설정값: {options}")

    # 콤보/적용 버튼을 한 번의 순회로 모두 찾아 둔다 (하나씩 찾으면 개당 15초 이상)
    win = app.window(handle=hwnd)
    prefetch_auto_ids(win, [i for c in SHIPPING_CONTROLS for i in c[:2]])

    ok_all = True
    for combo_id, apply_id, label in SHIPPING_CONTROLS:
        value = str(options.get(combo_id) or "").strip()
        if not value:
            log(f"  '{label}'({combo_id}) 설정값이 없어 건너뜁니다.")
            ok_all = False
            continue
        if not select_combo_value(app, hwnd, combo_id, value, label):
            ok_all = False
            continue
        if not click_button_by_auto_id(app, hwnd, apply_id, label):
            ok_all = False

    return ok_all


# ---------------------------------------------------------------------------
# 물류 관리 > 저장(S) 과 저장 시 뜨는 팝업 판정
# ---------------------------------------------------------------------------
# 저장을 누르면 상단 그리드 데이터가 정상인지 검증한다.
# 아래 문구 중 하나라도 팝업에 들어 있으면 데이터가 잘못된 것이므로 루틴을 그대로 끝낸다.
# (문구가 매우 구체적이라 다른 화면 텍스트와 우연히 겹칠 일이 없다)
SAVE_VALIDATION_ERRORS = (
    "배송일을 지정하세요",
    "배송업체를 지정하세요",
    "박스수량을 입력하세요",
    "박스규격을 입력하세요",
    "배송구분을 지정하세요",
    "배송요금을 입력하세요",
    "수령자명을 입력하세요",
    "연락처를 입력하세요",
    "주소를 입력하세요",
    "우편번호를 입력하세요",
    "상품수량을 입력하세요",
    "상품수량을 올바로 입력하세요(양의정수)",
)
YES_BUTTON_TEXTS = ("예(Y)", "예")
NO_BUTTON_TEXTS = ("아니오(N)", "아니오", "아니요(N)", "아니요")
# 저장이 정상일 때는 완료 팝업이 뜨지 않는다. 대신 '현재 저장중' 스피너가 돌다가 사라진다.
# 가끔 아래 안내 팝업이 뜨는데, 오류가 아니므로 확인을 누르고 저장을 마무리하면 된다.
SAVE_NOTICE_MESSAGES = (
    "새로 생성한 배송장을 우선 조회하였습니다",
)
# 저장에 성공하면 상단 그리드의 배송번호 컬럼에 'BS' + 날짜 + 일련번호가 채워진다.
SHIPPING_NUMBER_PREFIX = "BS"
# 저장 스피너가 사라질 때까지 기다리는 파라미터
SAVE_SPINNER_PROBE_SECONDS = 5.0
SAVE_SPINNER_POLL = 2.0
SAVE_SPINNER_MAX_WAIT = 600
# 스피너가 사라진 뒤 팝업이 뜨는지 지켜보는 시간과, 연속 팝업을 처리할 최대 횟수
SAVE_POPUP_WAIT_SECONDS = 10
SAVE_POPUP_POLL = 1.0
SAVE_POPUP_MAX_ROUNDS = 6


def find_popup_buttons(win):
    """메인 창 안에 떠 있는 팝업의 버튼들(예/아니오/확인)을 찾는다.

    이 앱의 팝업은 별도 창이 아니라 메인 창 내부 오버레이로 그려진다.
    """
    wanted = set(OK_BUTTON_TEXTS) | set(YES_BUTTON_TEXTS) | set(NO_BUTTON_TEXTS)
    out = []
    try:
        wr = win.rectangle()
        for b in win.descendants(control_type="Button"):
            if b.window_text() not in wanted:
                continue
            r = b.rectangle()
            if r.width() <= 0 or r.height() <= 0:
                continue
            if r.left < wr.left or r.top < wr.top:
                continue  # 화면 밖(숨은 화면)
            out.append(b)
    except Exception:
        pass
    return out


def collect_popup_text(button, max_up=4, max_texts=60):
    """팝업 버튼에서 부모로 거슬러 올라가며 팝업 안의 텍스트를 모은다.

    창 전체를 훑으면 그리드 셀 수천 개까지 읽어 느리므로, 버튼 주변만 본다.
    """
    node = button
    best = ""
    for _ in range(max_up):
        try:
            node = node.parent()
            texts = [c.window_text() for c in node.descendants() if c.window_text()]
        except Exception:
            break
        if len(texts) > max_texts:
            break  # 팝업 범위를 넘어 화면 전체로 퍼진 것
        joined = " | ".join(texts)
        if len(joined) > len(best):
            best = joined
    return best


def find_validation_error(text):
    """팝업 텍스트에 검증 오류 문구가 있으면 그 문구를 돌려준다."""
    return next((m for m in SAVE_VALIDATION_ERRORS if m in text), None)


def wait_for_popup_buttons(app, hwnd, timeout=SAVE_POPUP_WAIT_SECONDS,
                           interval=SAVE_POPUP_POLL):
    """팝업 버튼이 나타날 때까지 기다린다. 안 뜨면 빈 목록."""
    waited = 0.0
    gate = PopupGate(hwnd)
    while waited < timeout:
        if gate.should_scan():
            win = app.window(handle=hwnd)
            buttons = find_popup_buttons(win)
            if buttons:
                return buttons
        time.sleep(interval)
        waited += interval
    return []


def wait_save_spinner_gone(app, hwnd, baseline_children,
                           poll=SAVE_SPINNER_POLL, max_wait=SAVE_SPINNER_MAX_WAIT):
    """'현재 저장중' 스피너가 사라질 때까지 기다린다.

    저장이 정상일 때는 완료 팝업이 없으므로, 스피너를 보지 않으면
    '아직 저장 중인데 팝업이 없다'와 '저장이 끝났다'를 구분할 수 없다.
    기다리는 동안 팝업이 먼저 뜨면(검증 오류 등) 바로 돌려준다.
    """
    waited = 0.0
    saw_spinner = False
    gate = PopupGate(hwnd)
    while waited <= max_wait:
        if gate.should_scan():
            win = app.window(handle=hwnd)
            if find_popup_buttons(win):
                log(f"  저장 대기 중 팝업이 떴습니다 ({waited:.0f}초 경과)")
                return saw_spinner

        spinners = detect_spinner(hwnd, baseline_children)
        if not spinners:
            if saw_spinner:
                log(f"  저장 스피너가 사라졌습니다 ({waited:.0f}초 경과)")
            return saw_spinner

        if not saw_spinner:
            saw_spinner = True
            log(f"  저장중 스피너 감지: {[(h, r) for h, _c, r in spinners]}")
        time.sleep(poll)
        waited += poll

    log(f"  경고: 저장 스피너가 {max_wait}초 안에 사라지지 않았습니다.")
    return saw_spinner


def count_shipping_numbers(app, hwnd, prefix=SHIPPING_NUMBER_PREFIX):
    """상단 그리드에 생성된 배송번호(BS...) 개수를 센다.

    이 그리드는 헤더가 '배송번호 / 매출구분' 처럼 2단이라 한 건이 두 줄로 그려지고,
    배송번호 셀이 UIA 에서는 '매출구분 행 N' 이라는 이름으로 잡힌다.
    그래서 컬럼 이름에 기대지 않고 '값이 BS 로 시작하는 셀'을 센다.
    화면에 렌더링된 행만 보이므로 전체 건수가 아니라 '저장이 되긴 했는지' 확인용이다.
    """
    try:
        win = app.window(handle=hwnd)
        tables = get_onscreen_tables(win)
        if not tables:
            return 0
        top_grid = min(tables, key=lambda t: t.rectangle().top)
        found = set()
        for cells in grid_rows(top_grid).values():
            for el in cells.values():
                v = (legacy_value(el) or "").strip()
                if v.upper().startswith(prefix):
                    found.add(v)
        return len(found)
    except Exception as e:
        log(f"  배송번호 확인 중 오류(무시): {e}")
        return 0


def _save_succeeded(app, hwnd, reason):
    """저장 성공 처리: 배송번호가 실제로 생겼는지 확인하고 결과를 돌려준다."""
    n = count_shipping_numbers(app, hwnd)
    if n:
        log(f"  배송번호 생성 확인: 화면에 보이는 범위에서 "
            f"'{SHIPPING_NUMBER_PREFIX}'로 시작하는 배송번호 {n}건")
    else:
        log(f"  경고: '{SHIPPING_NUMBER_PREFIX}'로 시작하는 배송번호를 화면에서 찾지 못했습니다. "
            f"저장이 실제로 반영되지 않았을 수 있습니다.")
    return True, reason


def run_logistics_save_step(app, hwnd):
    """물류 관리 '저장(S)' 클릭 후 팝업 규칙에 따라 처리한다.

    저장이 정상일 때는 완료 팝업이 뜨지 않고 '현재 저장중' 스피너만 돌다 사라진다.
    가끔 "새로 생성한 배송장을 우선 조회하였습니다..." 안내 팝업이 뜨는데 오류가 아니다.

    규칙:
      - 검증 오류 문구가 들어 있는 팝업 -> 루틴을 그대로 끝낸다.
        (팝업은 닫지 않고 그대로 둔다. 사용자가 무엇이 잘못됐는지 화면에서 볼 수 있어야 한다)
      - 그 외 팝업에 '예/아니오'가 있으면 -> '예'를 눌러 계속 진행한다.
      - '확인'만 있는 안내 팝업이면 -> 확인을 눌러 닫고 계속 진행한다.

    반환: (계속 진행해도 되는지, 사유)
    """
    baseline_children = visible_child_windows(hwnd)

    win = app.window(handle=hwnd)
    if not click_toolbar_button(win, hwnd, "저장(S)"):
        return False, "저장(S) 버튼을 찾지 못했습니다."

    # 저장이 정상이면 완료 팝업이 없다. 대신 '현재 저장중' 스피너가 돌므로
    # 그것이 사라질 때까지 기다려야 저장이 끝난 시점을 알 수 있다.
    probe_spinner(hwnd, baseline_children, seconds=SAVE_SPINNER_PROBE_SECONDS)
    saw_spinner = wait_save_spinner_gone(app, hwnd, baseline_children)
    if not saw_spinner:
        log("  스피너를 보지 못했습니다 (감지 전에 저장이 끝났을 수 있습니다).")

    for _round in range(1, SAVE_POPUP_MAX_ROUNDS + 1):
        buttons = wait_for_popup_buttons(app, hwnd)
        if not buttons:
            log("  팝업 없음 -> 저장이 정상 처리된 것으로 봅니다.")
            return _save_succeeded(app, hwnd, "팝업 없음")

        text = collect_popup_text(buttons[0])
        names = [b.window_text() for b in buttons]
        log(f"  [{_round}] 팝업 감지 (버튼: {names})")
        log(f"      내용: {text}")

        hit = find_validation_error(text)
        if hit:
            log(f"  검증 오류 팝업입니다: '{hit}'")
            log("  -> 규칙에 따라 루틴을 여기서 종료합니다. (팝업은 닫지 않고 그대로 둡니다)")
            return False, f"저장 검증 오류: {hit}"

        yes_btn = next((b for b in buttons if b.window_text() in YES_BUTTON_TEXTS), None)
        no_btn = next((b for b in buttons if b.window_text() in NO_BUTTON_TEXTS), None)
        if yes_btn is not None and no_btn is not None:
            log(f"  검증 오류가 아닌 예/아니오 팝업 -> '{yes_btn.window_text()}' 클릭하고 계속")
            # 실제 저장은 이 '예'를 누른 뒤에 일어난다. 그래서 여기서도 스피너를 다시 기다린다.
            # 기준선은 지금 다시 잡는다 (저장 클릭 시점 기준선을 쓰면 그 사이 생긴 창까지
            #  스피너로 오인해 최대 대기시간을 통째로 날릴 수 있다)
            spinner_baseline = visible_child_windows(hwnd)
            ec.ensure_foreground(hwnd)
            yes_btn.click_input()
            time.sleep(1.5)
            probe_spinner(hwnd, spinner_baseline, seconds=SAVE_SPINNER_PROBE_SECONDS)
            wait_save_spinner_gone(app, hwnd, spinner_baseline)
            continue

        ok_btn = next((b for b in buttons if b.window_text() in OK_BUTTON_TEXTS), None)
        if ok_btn is not None:
            notice = next((m for m in SAVE_NOTICE_MESSAGES if m in text), None)
            kind = f"알려진 안내 팝업('{notice}')" if notice else "안내 팝업"
            log(f"  {kind} -> '{ok_btn.window_text()}' 클릭하고 계속")
            ec.ensure_foreground(hwnd)
            ok_btn.click_input()
            time.sleep(2.0)
            continue

        log(f"  처리 방법을 모르는 팝업입니다 (버튼: {names}). 안전하게 중단합니다.")
        return False, f"알 수 없는 팝업: {names}"

    log(f"  팝업이 {SAVE_POPUP_MAX_ROUNDS}회를 넘겨 계속 뜹니다. 중단합니다.")
    return False, "팝업 반복 초과"


# ---------------------------------------------------------------------------
# 물류 관리 > 운송장출력(자동) / 엑셀파일생성(수동)
# ---------------------------------------------------------------------------
CARRIER_PICKER_TITLE = "택배사 선택"
PRINT_PREVIEW_TITLE = "ERPia 출력 미리보기"
PRINT_DIALOG_TITLE = "인쇄"
# 프린터 이름은 업체가 미리 설정한다. 값이 없으면 인쇄 대화상자의 기본값(시스템 기본 프린터)을 쓴다.
PRINTER_CONFIG_KEY = "Printer"
# 수동(엑셀파일생성)일 때 파일을 저장할 바탕화면 폴더 이름
JOBS_DIR_NAME = "ERPIA_AI_JOBS"
# '이미 운송장(으)로 생성(출력)한 배송장이...' 팝업 -> 예를 눌러 계속 진행
ALREADY_PRINTED_KEYWORD = "이미 운송장"
# 엑셀 저장 후 가끔 뜨는 '생성한 엑셀파일을 여시겠습니까?' 팝업.
# 버튼을 누르지 않고(엑셀을 열지 않고) 그대로 두고 루틴을 끝낸다.
EXCEL_OPEN_PROMPT_KEYWORDS = (
    "엑셀파일을 여",
    "엑셀 파일을 여",
)
# 엑셀 저장 후 '생성된 파일 경로는 다음과 같습니다...' 안내가 뜨는 업체가 있다(드묾).
# 닫지 않으면 화면에 그대로 남으므로 확인을 눌러 닫는다.
EXCEL_PATH_NOTICE_KEYWORDS = (
    "생성된 파일 경로",
)
# 출력 도중 이 문구가 든 팝업이 뜨면 확인을 누르고 루틴을 끝낸다.
# (건수 n이 문구에 섞여 들어오므로 변하지 않는 앞부분만 본다)
PRINT_ABORT_KEYWORDS = (
    "주소정제추출 실패",
)
DIALOG_WAIT_SECONDS = 60
SAVE_DIALOG_CLASS = "#32770"  # 표준 윈도우 파일 저장 대화상자
# 실물 프린터면 저장 창이 안 뜨므로, 인쇄 직후에는 짧게만 기다린다
FILE_PRINTER_SAVE_WAIT = 10
# 저장 대화상자의 '파일 이름' 입력란 컨트롤 ID (ComboBox 안에 들어있다)
SAVE_DIALOG_FILENAME_EDIT_ID = 1001
# 저장 후 덮어쓰기 확인이 뜰 때의 창 제목
SAVE_CONFIRM_TITLE = "다른 이름으로 저장 확인"


def find_top_hwnds_by_title(pid, title, exact=True, visible_only=True):
    """EnumWindows 로 해당 프로세스의 최상위 창을 제목으로 찾는다.

    이 앱의 대화상자(택배사 선택 / 출력 미리보기 / 인쇄)는 UIA 트리에서 최상위로 잡히지 않아
    Desktop.windows() 로는 못 찾는다. 반드시 핸들로 찾아야 한다.
    """
    out = []

    def cb(h, _):
        try:
            _, wp = win32process.GetWindowThreadProcessId(h)
            if wp != pid:
                return True
            if visible_only and not win32gui.IsWindowVisible(h):
                return True
            t = win32gui.GetWindowText(h)
            if (t == title) if exact else (title in t):
                out.append(h)
        except Exception:
            pass
        return True

    win32gui.EnumWindows(cb, None)
    return out


def wait_top_hwnd(pid, title, timeout=DIALOG_WAIT_SECONDS, interval=1.0, exact=True):
    """제목이 맞는 최상위 창이 나타날 때까지 기다린다. 없으면 None."""
    waited = 0.0
    while waited < timeout:
        hits = find_top_hwnds_by_title(pid, title, exact=exact)
        if hits:
            return hits[0]
        time.sleep(interval)
        waited += interval
    return None


def connect_dialog(dlg_hwnd):
    """대화상자에 UIA 로 붙는다.

    Desktop().window(handle=...) 로 래핑하면 자식이 0개로 나오는 경우가 있어
    Application.connect 를 쓴다.
    """
    return Application(backend="uia").connect(handle=dlg_hwnd).window(handle=dlg_hwnd)


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


def handle_print_popups(app, pid, hwnd, rounds=3, wait=2.0, already_printed="continue"):
    """출력 도중 뜨는 팝업을 처리한다.

    - PRINT_ABORT_KEYWORDS 팝업('주소정제추출 실패…'): 확인을 눌러 닫고 'abort'
    - '이미 운송장(으)로 생성(출력)한 배송장이…': already_printed 정책대로
        "continue" -> 예를 눌러 계속 ('continued')
        "stop"     -> 아니오를 눌러 멈춤 ('already_printed'). 아니오 뒤에 택배사 선택/미리보기/인쇄 창이
                      남아 있으면 닫는다. 아니오가 없으면 아무것도 누르지 않고 'stuck' (팝업이 남는다)
    - 그 외 팝업: 예(없으면 확인)를 눌러 계속
    - 팝업이 없으면 'none'

    반환: 'none' | 'continued' | 'abort' | 'already_printed' | 'stuck'
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
            hit = next((k for k in PRINT_ABORT_KEYWORDS if k in text), None)
            log(f"  출력 중단 팝업입니다: '{hit}'")
            log(f"      내용: {text}")
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
            return "stuck"
        if action == "already_printed":
            log(f"  '이미 출력한 배송장' 안내 -> '{want}' 클릭 (이번 실행에서 저장한 배송장이 아니라 다시 출력하지 않습니다)")
            log(f"      내용: {text}")
            ec.ensure_foreground(hwnd)
            btn.click_input()
            time.sleep(2.0)
            # 아니오 뒤에도 출력 관련 창이 남아 있으면 닫는다 (남으면 메인 창이 잠긴다)
            for title in (CARRIER_PICKER_TITLE, PRINT_PREVIEW_TITLE, PRINT_DIALOG_TITLE):
                for h in find_top_hwnds_by_title(pid, title):
                    log(f"  '{title}' 창이 남아 있어 닫습니다 (hwnd={h})")
                    try:
                        win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
                    except Exception as ex:
                        log(f"    닫지 못했습니다(무시): {type(ex).__name__}")
            return "already_printed"

        kind = "'이미 출력한 배송장' 안내" if ALREADY_PRINTED_KEYWORD in text else "출력 중 팝업"
        log(f"  {kind} -> '{want}' 클릭")
        log(f"      내용: {text}")
        ec.ensure_foreground(hwnd)
        btn.click_input()
        status_ = "continued"
    return status_


def pick_carrier(pid, carrier, timeout=DIALOG_WAIT_SECONDS):
    """'택배사 선택' 창에서 설정한 택배사 행을 더블클릭한다.

    이 목록은 '연동 택배사'만 담고 있어서 배송정보설정의 택배사 목록보다 짧다.
    (설정값이 이 목록에 없으면 진행할 수 없다)
    """
    dlg_hwnd = wait_top_hwnd(pid, CARRIER_PICKER_TITLE, timeout)
    if dlg_hwnd is None:
        log(f"  '{CARRIER_PICKER_TITLE}' 창이 뜨지 않았습니다.")
        return False
    log(f"  '{CARRIER_PICKER_TITLE}' 창: hwnd={dlg_hwnd}")

    dlg = connect_dialog(dlg_hwnd)
    rows = {}
    for it in dlg.descendants(control_type="DataItem"):
        m = re.match(r"^(.*) 행 (\d+)$", it.window_text())
        if m:
            rows.setdefault(int(m.group(2)), {})[m.group(1)] = it

    target = None
    listed = []
    for n in sorted(rows):
        name = (legacy_value(rows[n].get("택배사명")) or "").strip()
        code = (legacy_value(rows[n].get("코드")) or "").strip()
        listed.append(f"{code}:{name}")
        if name == carrier:  # 완전 일치만
            target = rows[n].get("택배사명")

    if target is None:
        log(f"  '{carrier}'와 일치하는 택배사가 목록에 없습니다. (목록: {listed})")
        close_btn = next((b for b in dlg.descendants(control_type="Button")
                          if b.element_info.automation_id == "btn_Close"), None)
        if close_btn is not None:
            ec.ensure_foreground(dlg_hwnd)
            close_btn.click_input()
        return False

    log(f"  택배사 '{carrier}' 더블클릭: {target.rectangle()}")
    ec.ensure_foreground(dlg_hwnd)
    target.double_click_input()
    time.sleep(2.0)

    if find_top_hwnds_by_title(pid, CARRIER_PICKER_TITLE):
        # 더블클릭이 안 먹은 경우: 행을 고른 뒤 '적용' 버튼을 눌러본다
        log("  더블클릭 후에도 창이 남아 있어 '적용' 버튼을 시도합니다.")
        dlg = connect_dialog(dlg_hwnd)
        apply_btn = next((b for b in dlg.descendants(control_type="Button")
                          if b.element_info.automation_id == "btn_Apply"), None)
        if apply_btn is None:
            log("  '적용' 버튼을 찾지 못했습니다.")
            return False
        ec.ensure_foreground(dlg_hwnd)
        apply_btn.click_input()
        time.sleep(2.0)
    return True


def find_printer_combo(dlg):
    """인쇄 대화상자에서 '프린터 이름:' 라벨과 같은 줄에 있는 콤보를 찾는다.

    이 대화상자에는 콤보가 셋(프린터 / 양면 / 용지 공급) 있어서 순서로 고르면 위험하다.
    """
    combos = []
    for c in dlg.descendants(control_type="ComboBox"):
        try:
            r = c.rectangle()
        except Exception:
            continue
        if r.width() > 0 and r.height() > 0:
            combos.append((r, c))
    if not combos:
        return None

    label = next((t for t in dlg.descendants(control_type="Text")
                  if t.window_text() == "프린터 이름:"), None)
    if label is not None:
        lr = label.rectangle()
        for r, c in combos:
            if abs(r.top - lr.top) <= 6:
                return c
    return min(combos, key=lambda x: x[0].top)[1]  # 폴백: 가장 위쪽 콤보


def run_print_dialog(pid, printer_name, timeout=DIALOG_WAIT_SECONDS):
    """인쇄 대화상자에서 프린터를 고르고 '인쇄'를 눌러 실제로 출력한다."""
    dlg_hwnd = wait_top_hwnd(pid, PRINT_DIALOG_TITLE, timeout)
    if dlg_hwnd is None:
        log(f"  '{PRINT_DIALOG_TITLE}' 대화상자가 뜨지 않았습니다.")
        return False
    log(f"  '{PRINT_DIALOG_TITLE}' 대화상자: hwnd={dlg_hwnd}")

    dlg = connect_dialog(dlg_hwnd)
    combo = find_printer_combo(dlg)
    if combo is None:
        log("  프린터 콤보를 찾지 못했습니다.")
        return False
    current = combo_value(combo)

    if printer_name:
        if current == printer_name:
            log(f"  프린터 = '{current}' (설정값과 같아 바꾸지 않음)")
        else:
            log(f"  프린터 '{current}' -> '{printer_name}' 로 변경")
            ok = select_in_combo(
                lambda: connect_dialog(dlg_hwnd),
                dlg_hwnd,
                lambda: find_printer_combo(connect_dialog(dlg_hwnd)),
                printer_name, "프린터")
            if not ok:
                log("  설정한 프린터를 고르지 못했습니다. 인쇄하지 않고 중단합니다.")
                dlg = connect_dialog(dlg_hwnd)
                cancel = next((b for b in dlg.descendants(control_type="Button")
                               if b.window_text() == "취소"), None)
                if cancel is not None:
                    ec.ensure_foreground(dlg_hwnd)
                    cancel.click_input()
                return False
    else:
        log(f"  설정에 '{PRINTER_CONFIG_KEY}' 값이 없어 기본 프린터로 인쇄합니다: '{current}'")

    dlg = connect_dialog(dlg_hwnd)
    print_btn = next((b for b in dlg.descendants(control_type="Button")
                      if b.window_text() == "인쇄"), None)
    if print_btn is None:
        log("  대화상자의 '인쇄' 버튼을 찾지 못했습니다.")
        return False
    log(f"  '인쇄' 클릭 (실제 출력): {print_btn.rectangle()}")
    ec.ensure_foreground(dlg_hwnd)
    print_btn.click_input()
    time.sleep(2.0)

    # 파일로 출력하는 프린터(Microsoft Print to PDF 등)는 저장 위치를 묻는 창을 띄운다.
    # 실물 프린터면 이 창이 안 뜨므로 짧게만 기다렸다 넘어간다.
    save_hwnd = wait_save_dialog(pid, timeout=FILE_PRINTER_SAVE_WAIT)
    if save_hwnd is not None:
        log("  파일로 출력하는 프린터입니다. 저장 위치를 지정합니다.")
        # 자동 출력에서 PDF 프린터를 쓰는 경우는 임시 저장이므로 우리가 이름을 정한다
        save_dialog_to_jobs(save_hwnd, ext=".pdf", prefix="WAYBILL", keep_name=False)
    time.sleep(1.5)
    return True


def run_print_preview(app, pid, hwnd, printer_name, timeout=DIALOG_WAIT_SECONDS):
    """'ERPia 출력 미리보기' 창에서 '인쇄'를 눌러 인쇄 대화상자를 띄우고 출력까지 진행한다."""
    prev_hwnd = wait_top_hwnd(pid, PRINT_PREVIEW_TITLE, timeout)
    if prev_hwnd is None:
        log(f"  '{PRINT_PREVIEW_TITLE}' 창이 뜨지 않았습니다.")
        return False

    prev = connect_dialog(prev_hwnd)
    pages = next((t for t in prev.descendants(control_type="Text")
                  if str(legacy_value(t) or "").startswith("페이지 ")), None)
    log(f"  '{PRINT_PREVIEW_TITLE}' 창: hwnd={prev_hwnd}"
        f"{' / ' + legacy_value(pages) if pages is not None else ''}")

    btn = next((b for b in prev.descendants(control_type="Button")
                if b.window_text() == "인쇄"), None)
    if btn is None:
        log("  미리보기의 '인쇄' 버튼을 찾지 못했습니다.")
        return False
    log(f"  미리보기 '인쇄' 클릭: {btn.rectangle()}")
    ec.ensure_foreground(prev_hwnd)
    btn.click_input()

    if not run_print_dialog(pid, printer_name):
        return False

    # 출력 후 미리보기 창은 닫아둔다 (다음 실행 때 걸리적거리지 않도록)
    if find_top_hwnds_by_title(pid, PRINT_PREVIEW_TITLE):
        try:
            prev = connect_dialog(prev_hwnd)
            close_btn = next((b for b in prev.descendants(control_type="Button")
                              if b.window_text() == "인쇄 미리 보기 닫기"), None)
            if close_btn is not None:
                log("  미리보기 창 닫기")
                ec.ensure_foreground(prev_hwnd)
                close_btn.click_input()
                time.sleep(1.5)
        except Exception as e:
            log(f"  미리보기 창을 닫지 못했습니다(무시): {e}")
    return True


def jobs_dir():
    """ERPIA_AI 폴더 안의 ERPIA_AI_JOBS 경로. 없으면 만든다."""
    path = os.path.join(pl.find_ai_dir(), JOBS_DIR_NAME)
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)
        log(f"  저장 폴더를 새로 만들었습니다: {path}")
    return path


def find_save_dialog(pid):
    """표준 윈도우 파일 저장 대화상자(class '#32770')를 찾는다."""
    for h in find_top_hwnds_by_title(pid, "", exact=False):
        try:
            if win32gui.GetClassName(h) == SAVE_DIALOG_CLASS:
                return h
        except Exception:
            continue
    return None


def wait_save_dialog(pid, timeout=DIALOG_WAIT_SECONDS, interval=1.0):
    waited = 0.0
    while waited < timeout:
        h = find_save_dialog(pid)
        if h is not None:
            return h
        time.sleep(interval)
        waited += interval
    return None


def find_save_dialog_filename_edit(dlg_hwnd):
    """저장 대화상자의 '파일 이름' 입력란(win32 핸들)을 찾는다.

    주의: 이 대화상자는 파일 '목록 항목'들도 Edit 컨트롤로 노출한다.
    그래서 UIA 로 '첫 번째 Edit'을 집으면 목록에 있는 남의 파일을 선택해버리고,
    저장을 누르면 그 파일을 덮어쓰게 된다. 실제 입력란은 ComboBox 안에 든
    컨트롤 ID 1001 짜리 Edit 이다. 아래쪽에 '파일 형식' 콤보가 하나 더 있으므로
    둘 중 위에 있는 것을 고른다.
    """
    found = []

    def cb(h, _):
        try:
            if win32gui.GetClassName(h) != "Edit":
                return True
            if win32gui.GetDlgCtrlID(h) != SAVE_DIALOG_FILENAME_EDIT_ID:
                return True
            if win32gui.GetClassName(win32gui.GetParent(h)) != "ComboBox":
                return True
            found.append((win32gui.GetWindowRect(h)[1], h))
        except Exception:
            pass
        return True

    try:
        win32gui.EnumChildWindows(dlg_hwnd, cb, None)
    except Exception:
        return None
    return min(found)[1] if found else None


def read_save_filename(edit_hwnd):
    """저장 대화상자 입력란의 현재 값을 읽는다 (프로세스가 달라 GetWindowText 로는 못 읽는다)."""
    try:
        from pywinauto.controls.win32_controls import EditWrapper
        return EditWrapper(edit_hwnd).window_text()
    except Exception as e:
        log(f"  파일 이름 읽기 실패: {e}")
        return ""


def set_save_filename(edit_hwnd, path):
    """저장 대화상자 입력란에 경로를 넣고, 실제로 들어간 값을 읽어 돌려준다.

    win32gui.SendMessage(WM_SETTEXT) 는 다른 프로세스의 컨트롤에는 반영되지 않고,
    GetWindowText 도 빈 문자열만 준다. pywinauto 의 Edit 래퍼는 프로세스 간
    버퍼 처리를 해주므로 그것을 쓴다.
    """
    try:
        from pywinauto.controls.win32_controls import EditWrapper
        w = EditWrapper(edit_hwnd)
        w.set_edit_text(path)
        time.sleep(0.4)
        return w.window_text()
    except Exception as e:
        log(f"  파일 이름 입력 실패: {e}")
        return None


def cancel_save_dialog(dlg_hwnd):
    """저장 대화상자를 취소로 닫는다."""
    try:
        dlg = connect_dialog(dlg_hwnd)
        cancel = next((b for b in dlg.descendants(control_type="Button")
                       if b.window_text() in ("취소", "Cancel")), None)
        if cancel is not None:
            ec.ensure_foreground(dlg_hwnd)
            cancel.click_input()
            time.sleep(1.0)
            return True
    except Exception as e:
        log(f"  저장 대화상자를 닫지 못했습니다(무시): {e}")
    return False


def unique_path(path):
    """같은 이름이 이미 있으면 뒤에 시각을 붙여 겹치지 않게 만든다.

    덮어쓰기 확인창이 뜨면 무조건 실패 처리하므로, 애초에 겹치지 않게 한다.
    """
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    return f"{base}_{time.strftime('%Y%m%d%H%M%S')}{ext}"


def save_dialog_to_jobs(dlg_hwnd, ext=".xlsx", prefix="WAYBILL", keep_name=True):
    """저장 대화상자에서 바탕화면 ERPIA_AI_JOBS 폴더로 저장한다.

    keep_name=True 면 프로그램이 미리 채워둔 파일명을 그대로 쓰고 폴더만 바꾼다.
    (수동 엑셀 생성은 프로그램이 이름을 정해주므로 우리가 새로 지으면 안 된다)
    이름이 비어 있을 때만 prefix+시각으로 만든다.
    """
    target_dir = jobs_dir()
    title = win32gui.GetWindowText(dlg_hwnd)
    log(f"  파일 저장 대화상자: hwnd={dlg_hwnd} title={title!r}")

    edit_hwnd = find_save_dialog_filename_edit(dlg_hwnd)
    if edit_hwnd is None:
        log("  '파일 이름' 입력란을 찾지 못했습니다. 저장하지 않고 중단합니다.")
        return False

    current = read_save_filename(edit_hwnd)
    log(f"  프로그램이 채워둔 파일명: {current!r}")

    name = ""
    if keep_name and current:
        name = os.path.basename(current.strip('"').strip())
    if not name:
        name = f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}{ext}"
        log(f"  파일명이 비어 있어 새로 만듭니다: {name}")

    full = unique_path(os.path.join(target_dir, name))
    log(f"  저장 경로: {full}")

    # 파일명이 정확히 들어간 것을 확인하기 전에는 저장을 누르지 않는다.
    # (입력이 안 된 채로 저장하면 목록에서 선택돼 있던 '남의 파일'을 덮어쓰게 된다)
    ec.ensure_foreground(dlg_hwnd)
    typed = set_save_filename(edit_hwnd, full)
    if typed != full:
        log(f"  파일 이름을 넣지 못했습니다 (입력란: {typed!r}). "
            f"덮어쓰기 사고를 막기 위해 저장하지 않고 취소합니다.")
        cancel_save_dialog(dlg_hwnd)
        return False

    dlg = connect_dialog(dlg_hwnd)
    save_btn = next((b for b in dlg.descendants(control_type="Button")
                     if b.window_text() in ("저장(S)", "저장", "Save")), None)
    if save_btn is None:
        log("  '저장' 버튼을 찾지 못했습니다.")
        return False
    log(f"  '{save_btn.window_text()}' 클릭")
    save_btn.click_input()
    time.sleep(2.0)

    # 파일명에 시각을 넣으므로 겹칠 일이 없다. 그래도 덮어쓰기 확인이 뜬다면
    # 우리가 의도한 파일이 아니라는 뜻이므로 '아니요'로 닫고 실패로 처리한다.
    # (자동화가 남의 파일을 덮어쓰는 일은 없어야 한다)
    _, dlg_pid = win32process.GetWindowThreadProcessId(dlg_hwnd)
    confirm = find_top_hwnds_by_title(dlg_pid, SAVE_CONFIRM_TITLE)
    if confirm:
        cdlg = connect_dialog(confirm[0])
        ctext = " ".join(t.window_text() for t in cdlg.descendants(control_type="Text")
                         if t.window_text())
        log(f"  덮어쓰기 확인창이 떴습니다: {ctext}")
        no = next((b for b in cdlg.descendants(control_type="Button")
                   if b.window_text() in NO_BUTTON_TEXTS), None)
        if no is not None:
            log(f"  -> '{no.window_text()}' 클릭 (기존 파일 보존). 저장 실패로 처리합니다.")
            ec.ensure_foreground(confirm[0])
            no.click_input()
            time.sleep(1.5)
        cancel_save_dialog(dlg_hwnd)
        return False

    for _ in range(10):
        if os.path.exists(full):
            log(f"  파일 생성 확인: {full} ({os.path.getsize(full):,} bytes)")
            return True
        time.sleep(1.0)
    log(f"  경고: 저장했는데 파일이 보이지 않습니다: {full}")
    return False


def run_save_dialog(pid, ext=".xlsx", prefix="WAYBILL", keep_name=True,
                    timeout=DIALOG_WAIT_SECONDS):
    """(수동) 파일 저장 대화상자를 기다렸다가 ERPIA_AI_JOBS 폴더에 저장한다.

    파일명은 프로그램이 채워둔 것을 그대로 쓴다(keep_name).
    """
    dlg_hwnd = wait_save_dialog(pid, timeout)
    if dlg_hwnd is None:
        log("  파일 저장 대화상자가 뜨지 않았습니다.")
        return False
    return save_dialog_to_jobs(dlg_hwnd, ext=ext, prefix=prefix, keep_name=keep_name)


def run_print_step(app, pid, hwnd, options=None, already_printed="continue"):
    """물류 관리: 자동이면 '운송장출력', 수동이면 '엑셀파일생성'을 눌러 끝까지 진행한다.

    자동: 운송장출력 -> 택배사 선택(더블클릭) -> ('이미 출력한 배송장' 팝업이면 예)
          -> 출력 미리보기 -> 인쇄 -> 설정한 프린터 선택 -> 인쇄(실제 출력)
    수동: 엑셀파일생성 -> 택배사 선택(더블클릭) -> 파일 저장 대화상자
          -> 바탕화면 ERPIA_AI_JOBS 폴더에 저장 (파일명은 프로그램이 채운 것을 그대로 씀)
          -> '생성한 엑셀파일을 여시겠습니까?' 팝업이 뜨면 누르지 않고 루틴 종료
    already_printed: '이미 출력한 배송장' 팝업 정책 (handle_print_popups 참고)
    반환: "done" | "already_printed"(아니오를 누르고 멈춤) | "stuck"(팝업을 처리하지 못해 남겨 둠) | "failed"
    """
    if options is None:
        options = pl.load_logistic_options()

    is_auto = current_auto_mode(app, hwnd)
    button = AUTO_MODE_BUTTON[is_auto]
    carrier = str(options.get("cboTag") or "").strip()
    printer = str(options.get(PRINTER_CONFIG_KEY) or "").strip()
    log(f"모드={AUTO_MODE_LABEL[is_auto]} / 누를 버튼='{button}' / "
        f"택배사='{carrier}' / 프린터='{printer or '(설정 없음 - 기본 프린터)'}'")

    if not carrier:
        log("설정에 'cboTag'(택배사) 값이 없습니다. 중단합니다.")
        return "failed"

    win = app.window(handle=hwnd)
    if not click_toolbar_button(win, hwnd, button):
        log(f"'{button}' 버튼을 찾지 못했습니다. 모드 설정이 잘못됐을 수 있습니다.")
        return "failed"

    # 버튼을 누른 직후 안내 팝업이 먼저 뜨는 경우가 있다
    r = handle_print_popups(app, pid, hwnd, rounds=1, wait=1.5, already_printed=already_printed)
    if r in ("abort", "stuck", "already_printed"):
        return "failed" if r == "abort" else r

    if not pick_carrier(pid, carrier):
        return "failed"

    # 택배사를 고른 뒤에 '주소정제추출 실패' 같은 오류가 뜰 수 있다.
    # 이 경우 확인만 누르고 여기서 루틴을 끝낸다.
    r = handle_print_popups(app, pid, hwnd, rounds=3, wait=1.5, already_printed=already_printed)
    if r == "abort":
        log("주소정제 등 출력 전 검증에 걸려 루틴을 종료합니다.")
        return "failed"
    if r in ("stuck", "already_printed"):
        return r

    if is_auto:
        return "done" if run_print_preview(app, pid, hwnd, printer) else "failed"

    saved = run_save_dialog(pid)

    # 저장 후 '생성한 엑셀파일을 여시겠습니까?' 가 뜰 수 있다.
    # 엑셀을 열 이유가 없으므로 버튼을 누르지 않고 그대로 둔 채 루틴을 끝낸다.
    check_excel_open_prompt(app, hwnd)
    return "done" if saved else "failed"


def click_popup_ok(app, hwnd, retries=3):
    """메인 창 안 팝업의 '확인' 버튼을 다시 찾아 누른다.

    팝업이 다시 그려지면서 앞서 잡아둔 버튼 요소의 이름이 비어 버리는 경우가 있어,
    누르기 직전에 새로 찾는다.
    """
    for _ in range(retries):
        win = app.window(handle=hwnd)
        btn = next((b for b in win.descendants(control_type="Button")
                    if b.window_text() in OK_BUTTON_TEXTS), None)
        if btn is not None:
            try:
                ec.ensure_foreground(hwnd)
                btn.click_input()
                time.sleep(1.5)
                return True
            except Exception as e:
                log(f"  확인 클릭 실패, 다시 시도합니다: {e}")
        time.sleep(1.0)
    return False


def check_excel_open_prompt(app, hwnd, rounds=3, wait=1.5):
    """엑셀 저장 후 뜨는 팝업을 처리한다.

    - '생성된 파일 경로는 다음과 같습니다...' : 확인을 눌러 닫는다.
    - '생성한 엑셀파일을 여시겠습니까?' : 엑셀을 열 이유가 없으므로
      누르지 않고 그대로 둔 채 루틴을 끝낸다.
    """
    for _ in range(rounds):
        time.sleep(wait)
        win = app.window(handle=hwnd)
        buttons = find_popup_buttons(win)
        if not buttons:
            return True
        text = collect_popup_text(buttons[0])

        if any(k in text for k in EXCEL_OPEN_PROMPT_KEYWORDS):
            log(f"  '엑셀 파일 열기' 안내 팝업이 떴습니다 "
                f"(버튼: {[b.window_text() for b in buttons]})")
            log(f"      내용: {text}")
            log("  -> 누르지 않고 그대로 둔 채 루틴을 끝냅니다.")
            return True

        if any(k in text for k in EXCEL_PATH_NOTICE_KEYWORDS):
            log("  '생성된 파일 경로' 안내 팝업 -> 확인을 눌러 닫습니다.")
            log(f"      내용: {text}")
            if not click_popup_ok(app, hwnd):
                log("  경고: 확인 버튼을 누르지 못해 팝업이 남아 있을 수 있습니다.")
                return False
            continue

        log(f"  저장 후 팝업 감지 (버튼: {[b.window_text() for b in buttons]})")
        log(f"      내용: {text}")
        return True
    return True


def run_hold_logistics_step(app, pid, hwnd):
    """물류대기 관리 화면에서의 처리:
    10초 대기
    -> '상품별 재고검토' 탭: 부족수량이 있는 건마다 하단에서 상품코드 일치 행만 체크 + 배송보류
       (STOCK_EXCLUDED_CODES 의 상품코드는 부족수량이 있어도 건너뛴다)
    -> '일반' 탭: 조회 -> 상품상태!=정상 행 체크 -> 우클릭 -> 배송보류
    반환: "done" | "no_target" | "failed"
    """
    log("10초 대기...")
    time.sleep(10)

    # 먼저 '상품별 재고검토' 탭에서 부족수량 건들을 배송보류 처리한다.
    # (탭이 없거나 대상이 없어도 이어지는 '일반' 탭 루틴은 계속 진행한다)
    status.step("stock_review")
    log("\n=== 물류대기: 상품별 재고검토 (부족수량 건 배송보류) ===")
    try:
        done, total = run_stock_review_step(app, pid, hwnd)
        if total and done < total:
            log(f"경고: 상품별 재고검토 {total}건 중 {total - done}건을 처리하지 못했습니다.")
    except Exception as e:
        log(f"경고: 상품별 재고검토 처리 중 오류가 발생해 건너뜁니다: {e}")
        click_subtab(app, hwnd, STOCK_GENERAL_TAB_NAME)

    status.step("abnormal_hold")
    log("\n=== 물류대기: 일반 탭 처리 ===")
    win = app.window(handle=hwnd)
    win_rect = win.rectangle()

    # 화면 안에 있는 '조회(F)' 버튼만 대상으로 (다른 탭의 동명 버튼이 화면 밖에 있음)
    query_btn = None
    for b in win.descendants(control_type="Button"):
        if b.window_text() != "조회(F)":
            continue
        r = b.rectangle()
        if r.left >= 0 and r.top >= 0 and r.right <= win_rect.right and r.bottom <= win_rect.bottom:
            query_btn = b
            break

    if query_btn is None:
        log("'조회(F)' 버튼을 찾지 못했습니다. 중단합니다.")
        return "failed"

    # 조회 전에 그리드를 잡아 두고 오버레이 개수를 기준선으로 삼는다.
    # (고정 대기로는 데이터가 많은 실제 환경에서 조회가 끝나기 전에 진행될 수 있다)
    tables = get_onscreen_tables(win)
    if not tables:
        log("그리드를 찾지 못했습니다. 중단합니다.")
        return "failed"
    grid = max(tables, key=lambda t: t.rectangle().width() * t.rectangle().height())
    log(f"대상 그리드: {grid.rectangle()}")
    base_overlays = grid_overlay_count(hwnd, grid)

    log(f"'조회(F)' 클릭: {query_btn.rectangle()}")
    ec.ensure_foreground(hwnd)
    query_btn.click_input()
    time.sleep(2)
    wait_grid_spinner_gone(hwnd, grid, base_overlays, label="일반 탭")

    # '상품상태' 컬럼이 보이도록 가로 스크롤.
    # 사용자 지시: 상품상태 컬럼이 안 보이면(=비정상을 판별할 수 없으면) 루틴을 종료하지 말고
    # 배송보류를 건너뛰고 전체 선택 후 저장으로 진행한다.
    do_hold = scroll_grid_right_to_column(hwnd, grid, "상품상태")
    if not do_hold:
        log("'상품상태' 컬럼을 찾지 못했습니다 -> 비정상 배송보류를 건너뛰고 전체 저장으로 진행합니다.")

    if do_hold:
        log("상품상태 내림차순 정렬 -> 아래 비정상 구간 범위선택 -> 선택영역 체크")
        result = select_abnormal_range_and_check(pid, hwnd, grid)
        if result == "none":
            log("비정상 상품이 없어 배송보류를 건너뛰고 전체 저장으로 진행합니다.")
        elif result == "error":
            log("비정상 상품을 판별하지 못했습니다(정렬/읽기 실패) -> 배송보류 없이 전체 저장으로 진행합니다.")
        else:  # "held": 비정상 구간 선택 + 선택영역 체크 완료
            time.sleep(1.5)
            # 체크된 상태에서 다시 우클릭 -> 배송보류. 앵커는 반드시 '정상이 아닌 행' 위에서 잡는다.
            # 내림차순이라 맨 위는 '정상'이고 체크되지 않은 행이다. 스크롤은 옮기지 않는다.
            log("우클릭 -> '배송보류' 실행")
            x, header_bottom = get_status_column_geometry(grid, "상품상태")
            anchor = None
            if x is not None:
                rh = get_row_height(grid)
                first_y = header_bottom + rh // 2
                rows = scan_view_statuses(x, first_y, grid_click_bottom(grid), step=rh)
                cand = next(((y, v, el) for y, v, el in rows
                             if (v or "").strip() and v.strip() != "정상"), None)
                if cand is not None:
                    log(f"  앵커: '{cand[1]}' {cand[2].rectangle()}")
                    anchor = cand[2]

            if anchor is None:
                ok = right_click_grid_and_select(pid, hwnd, grid, "배송보류")
            else:
                ok = right_click_element_and_select(pid, hwnd, anchor, "배송보류")

            if ok:
                time.sleep(2)
                win2 = app.window(handle=hwnd)
                btn = find_popup_ok_button(win2)
                if btn is not None:
                    log(f"  배송보류 확인 팝업 -> '{btn.window_text()}' 클릭")
                    ec.ensure_foreground(hwnd)
                    btn.click_input()
            else:
                log("  배송보류 실행에 실패했습니다 -> 전체 저장으로 진행합니다.")

    # 후반 처리: 전체선택 -> 저장 -> 비동기 대기 (배송보류 여부와 무관하게 항상 실행)
    status.step("hold_save")
    log("\n=== 물류대기: 전체선택 -> 저장 ===")
    return run_hold_save(app, pid, hwnd)


def native_enabled(el):
    """UIA 요소의 네이티브 창 손잡이로 활성 여부를 싸게 본다.

    is_enabled() 는 UIA 호출이라 촘촘히 부르면 느리고, 요소가 다시 만들어지면
    옛 값을 물고 있을 수 있다. 이 화면의 버튼은 WinForms 라 진짜 창 손잡이가
    있어서 IsWindowEnabled 로 보면 사실상 공짜다. 손잡이가 없을 때만 UIA 로 돌아간다.
    """
    h = getattr(el.element_info, "handle", None)
    if h:
        try:
            return bool(win32gui.IsWindowEnabled(h))
        except Exception:
            pass
    try:
        return bool(el.is_enabled())
    except Exception:
        return None


def find_popup_windows(pid, main_hwnd):
    """ERPia 가 띄운, 메인이 아닌 '보이는' 최상위 창들 (별도 창으로 뜨는 안내 팝업).

    EnumWindows 라 폴링 중에 매번 불러도 부담이 없다. 툴팁/드롭다운 같은
    작은 창은 크기로 걸러낸다.
    """
    found = []

    def handler(h, _):
        try:
            _, p = win32process.GetWindowThreadProcessId(h)
        except Exception:
            return
        if p != pid or h == main_hwnd:
            return
        try:
            if not win32gui.IsWindowVisible(h):
                return
            left, top, right, bottom = win32gui.GetWindowRect(h)
        except Exception:
            return
        if right - left < 120 or bottom - top < 60:
            return
        found.append(h)

    try:
        win32gui.EnumWindows(handler, None)
    except Exception:
        pass
    return found


POPUP_TEXT_SKIP_TYPES = ("Button", "TitleBar", "MenuBar", "MenuItem", "ScrollBar", "Thumb")


def popup_window_text(win):
    """팝업 창 안의 안내 문구를 한 줄로 합친다.

    Text 만 보면 메시지 상자 종류에 따라 문구를 놓칠 수 있어서, 버튼·제목줄을 뺀
    모든 요소의 이름을 모은다. 팝업은 작아서 전부 훑어도 싸다.
    잘라내지 않는다 - 실패 문구 판정에도 쓰기 때문이다 (로그에 남길 때 자른다).
    """
    parts = []
    try:
        for el in win.descendants():
            try:
                if str(el.element_info.control_type) in POPUP_TEXT_SKIP_TYPES:
                    continue
                s = " ".join((el.window_text() or "").split())
            except Exception:
                continue
            if s and s not in parts:
                parts.append(s)
    except Exception:
        pass
    return " / ".join(parts)


def pick_popup_button(buttons):
    """안내 팝업에서 누를 버튼을 고른다 (사용자 규칙).

    '예/아니오' 팝업이면 '아니오', 그 밖에는 '확인/예'. 둘 다 없으면 None
    (모르는 창은 건드리지 않는다).
    """
    def by(texts):
        return next((b for b in buttons if b.window_text() in texts), None)

    return by(NO_BUTTON_TEXTS) or by(OK_BUTTON_TEXTS)


def dismiss_popup_window(popup_hwnd):
    """안내 팝업 하나를 사용자 규칙대로 닫는다.

    '예/아니오' 팝업이면 '아니오', 그 외에는 '확인'. 아는 버튼이 없으면
    건드리지 않는다 (엉뚱한 창을 닫지 않기 위해).
    돌려주는 값: (닫았는지, 설명, 문구)
    """
    try:
        w = Desktop(backend="uia").window(handle=popup_hwnd)
        buttons = w.descendants(control_type="Button")
    except Exception as e:
        return False, f"팝업을 읽지 못했습니다: {e}", ""

    names = [b.window_text() for b in buttons]
    btn = pick_popup_button(buttons)
    if btn is None:
        return False, f"아는 버튼이 없습니다 (버튼: {names})", ""

    # 누를 버튼 이름과 문구는 반드시 클릭 '전에' 잡아둔다.
    # 클릭하면 창이 사라져서 그 뒤에 읽으면 빈 문자열이 나온다.
    label = btn.window_text()
    msg = popup_window_text(w)
    try:
        title = w.window_text()
    except Exception:
        title = ""
    try:
        ec.ensure_foreground(popup_hwnd)
    except Exception:
        pass
    try:
        btn.click_input()
    except Exception as e:
        return False, f"'{label}' 클릭 실패: {e}", msg
    return True, f"[{title}] {msg[:300]} -> '{label}' 클릭", msg


def popups_to_try(pid, hwnd, tried):
    """지금 손대야 할 별도 창 팝업을 (hwnd, 몇 번째 시도) 로 내준다.

    tried 는 {hwnd: (마지막 시도 시각, 시도 횟수)}. 창이 사라지는 중이면 읽기가
    실패할 수 있어서 곧장 포기하지 않고 POPUP_RETRY_SECONDS 뒤에 다시 본다.
    POPUP_MAX_ATTEMPTS 번까지 해보고 그래도 남아 있으면 더 건드리지 않는다
    (닫히지 않는 창에 매달려 같은 자리를 계속 클릭하지 않기 위해).
    """
    now = time.time()
    for h in find_popup_windows(pid, hwnd):
        last, attempts = tried.get(h, (0.0, 0))
        if attempts >= POPUP_MAX_ATTEMPTS or now - last < POPUP_RETRY_SECONDS:
            continue
        tried[h] = (now, attempts + 1)
        yield h, attempts + 1


def handle_import_popups(pid, hwnd, tried):
    """가져오기 대기 중에 뜬 안내 팝업을 닫는다. 닫은 개수를 돌려준다."""
    closed = 0
    for h, attempt in popups_to_try(pid, hwnd, tried):
        ok, why, _msg = dismiss_popup_window(h)
        if ok:
            closed += 1
            tried[h] = (time.time(), POPUP_MAX_ATTEMPTS)   # 닫았으면 더 보지 않는다
            log(f"  안내 팝업 처리: {why}")
            status.note(f"안내 팝업 처리: {why[:80]}")
        elif attempt >= POPUP_MAX_ATTEMPTS:
            log(f"  안내 팝업 그대로 둠: {why}")
    return closed


def handle_sales_popups(pid, hwnd, tried):
    """정상매출 대기 중 '별도 창'으로 뜬 팝업을 닫는다. (실패 문구, 닫은 개수) 를 돌려준다.

    이 팝업은 메인 창의 자식이 아니라서 PopupGate 로는 보이지 않는다.
    (2026-09-15 16:52: 개체 참조 오류 팝업을 못 보고 414초를 기다렸다)
    EnumWindows 라 폴링마다 불러도 비용이 없다.
      - 실패 문구가 있으면 닫고 그 문구를 돌려준다 -> 부른 쪽이 루틴을 멈춘다.
      - 그 밖(개체 참조 오류, 안내)은 규칙대로 닫고 계속 기다린다.
    """
    closed = 0
    for h, attempt in popups_to_try(pid, hwnd, tried):
        ok, why, msg = dismiss_popup_window(h)
        if not ok:
            if attempt >= POPUP_MAX_ATTEMPTS:
                log(f"  팝업 그대로 둠: {why}")
            continue
        closed += 1
        tried[h] = (time.time(), POPUP_MAX_ATTEMPTS)
        failure = match_sales_failure(msg)
        if failure:
            log(f"  매출처리 실패 팝업(별도 창): {why}")
            return failure, closed
        kind = "오류 팝업" if match_error_popup(msg) else "안내 팝업"
        log(f"  {kind} 처리, 계속 기다립니다: {why}")
        status.note(f"{kind} 처리: {msg[:60]}")
    return None, closed


def run_import_step(app, pid, hwnd, win):
    """'가져오기'를 실제로 눌러 주문을 받아오고, 끝날 때까지 기다린다.

    이 화면에는 그리드를 덮는 스피너가 없다. 대신 버튼 상태로 판단한다.
      확인방법 1: '가져오기'가 비활성 + 아이콘이 '조회중'으로 바뀐다 (클릭 즉시).
      확인방법 2: '매출처리'도 같이 비활성된다 (0.3초 뒤).
    둘 다 다시 활성이 되고 IMPORT_SETTLE_SECONDS 동안 유지되면 끝난 것으로 본다.
    (2026-09-15 실측: 12개 몰 324초, 중간에 버튼이 잠깐 돌아오는 일은 없었다)

    도중에 뜨는 안내 팝업은 규칙대로 닫는다. 팝업이 떠 있는 동안에는 메인 창이
    잠겨 버튼도 비활성으로 보이므로, 닫지 않으면 영영 기다리게 된다.
    """
    imp = find_by_text(win, IMPORT_BUTTON_NAME, control_types=("Button",))
    if imp is None:
        log(f"'{IMPORT_BUTTON_NAME}' 버튼을 찾지 못했습니다. 주문 가져오기를 건너뜁니다.")
        return False
    sal = find_by_text(win, "매출처리", control_types=("SplitButton", "Button"))
    if sal is None:
        log("'매출처리' 버튼을 찾지 못했습니다. '가져오기' 상태만으로 판단합니다.")

    def handles_alive():
        """들고 있는 버튼의 창 손잡이가 아직 살아 있는지."""
        for el in (imp, sal):
            if el is None:
                continue
            h = getattr(el.element_info, "handle", None)
            if h:
                try:
                    if not win32gui.IsWindow(h):
                        return False
                except Exception:
                    return False
        return True

    def refind_buttons():
        """화면이 다시 그려져 버튼이 새로 만들어졌을 때 다시 잡는다.

        죽은 손잡이로 IsWindowEnabled 를 부르면 계속 '비활성'으로 보여서
        영영 기다리게 된다. 비싸지만(창 순회) 이 경우에만 부른다.
        """
        nonlocal imp, sal
        try:
            w2 = app.window(handle=hwnd)
            imp2 = find_by_text(w2, IMPORT_BUTTON_NAME, control_types=("Button",))
            sal2 = find_by_text(w2, "매출처리", control_types=("SplitButton", "Button"))
        except Exception as e:
            log(f"  경고: 버튼을 다시 찾지 못했습니다: {e}")
            return False
        if imp2 is None:
            log("  경고: '가져오기' 버튼이 화면에서 사라졌습니다.")
            return False
        imp, sal = imp2, sal2
        log("  버튼을 다시 잡았습니다 (화면이 새로 그려짐).")
        return True

    def busy_now():
        """(가져오기 비활성, 매출처리 비활성) - 읽을 수 없으면 None"""
        a = native_enabled(imp)
        b = native_enabled(sal) if sal is not None else None
        return (None if a is None else not a), (None if b is None else not b)

    before = busy_now()
    if before[0]:
        log("  경고: 클릭 전인데 '가져오기'가 이미 비활성입니다. 앞 작업이 끝나기를 기다립니다.")
        waited = 0.0
        while waited < IMPORT_MAX_WAIT_SECONDS and busy_now()[0]:
            time.sleep(IMPORT_POLL_SECONDS)
            waited += IMPORT_POLL_SECONDS

    log(f"'{IMPORT_BUTTON_NAME}' 클릭")
    ec.ensure_foreground(hwnd)
    try:
        imp.click_input()
    except Exception as e:
        log(f"  '{IMPORT_BUTTON_NAME}' 클릭 실패: {e}")
        return False
    t0 = time.time()
    status.note("주문 가져오는 중")

    seen_popups = {}

    # 1) '조회중'으로 바뀌는지 확인한다 (클릭이 먹었는지 보는 것)
    became_busy = False
    while time.time() - t0 < IMPORT_BUSY_WAIT_SECONDS:
        a, b = busy_now()
        if a or b:
            became_busy = True
            log(f"  조회 시작 확인 (가져오기 비활성={a}, 매출처리 비활성={b},"
                f" {time.time() - t0:.1f}초)")
            break
        handle_import_popups(pid, hwnd, seen_popups)
        time.sleep(IMPORT_POLL_SECONDS)

    if not became_busy:
        # 팝업만 뜨고 조회가 시작되지 않았을 수 있다. 한 번 더 훑고 넘어간다.
        handle_import_popups(pid, hwnd, seen_popups)
        log(f"  경고: {IMPORT_BUSY_WAIT_SECONDS}초 안에 '조회중'으로 바뀌지 않았습니다."
            f" 가져올 주문이 없었거나 클릭이 먹지 않았을 수 있습니다.")
        return False

    # 2) 둘 다 활성으로 돌아오고, 잠깐 유지되면 완료
    idle_since = None
    last_report = 0.0
    while time.time() - t0 < IMPORT_MAX_WAIT_SECONDS:
        handle_import_popups(pid, hwnd, seen_popups)
        a, b = busy_now()
        elapsed = time.time() - t0
        if not a and not b:
            if idle_since is None:
                idle_since = time.time()
            elif time.time() - idle_since >= IMPORT_SETTLE_SECONDS:
                log(f"  주문 가져오기 완료 ({elapsed:.0f}초)")
                status.note(f"주문 가져오기 완료 ({elapsed:.0f}초)")
                handle_import_popups(pid, hwnd, seen_popups)
                return True
        else:
            idle_since = None
            if elapsed - last_report >= 30:
                last_report = elapsed
                log(f"  가져오는 중... {elapsed:.0f}초 경과")
                status.note(f"주문 가져오는 중 ({elapsed:.0f}초)")
                if not handles_alive() and not refind_buttons():
                    log("  버튼 상태를 더 볼 수 없어 대기를 끝냅니다.")
                    return False
        time.sleep(IMPORT_POLL_SECONDS)

    log(f"  경고: 최대 대기시간({IMPORT_MAX_WAIT_SECONDS // 60}분)을 넘겼습니다."
        " 가져오기가 끝났는지 확인하지 못했습니다.")
    return False


def find_popup_ok_button(win):
    """메인 창 내부에 떠 있는 팝업의 '예/확인' 버튼을 찾는다.
    (이 앱의 팝업은 별도 창이 아니라 메인 창 내부 오버레이로 렌더링된다)"""
    try:
        buttons = win.descendants(control_type="Button")
    except Exception:
        return None
    return next((b for b in buttons if b.window_text() in OK_BUTTON_TEXTS), None)


def match_sales_failure(text, keywords=SALES_FAIL_KEYWORDS):
    """문구가 매출처리 실패 안내면 한 줄로 편 문구를, 아니면 None."""
    flat = " ".join((text or "").split())
    if not flat:
        return None
    for k in keywords:
        if k in flat:
            return flat
    # 문구가 조금 달라도 '매출'과 '실패'가 같이 있으면 실패로 본다
    if "매출" in flat and "실패" in flat:
        return flat
    return None


def match_error_popup(text):
    """문구가 ERPia 내부 오류(개체 참조 등)면 한 줄로 편 문구를, 아니면 None."""
    flat = " ".join((text or "").split())
    return flat if flat and any(k in flat for k in ERROR_POPUP_KEYWORDS) else None


def _find_popup_text(win, matcher):
    try:
        texts = [t.window_text() for t in win.descendants(control_type="Text")]
    except Exception:
        return None
    for raw in texts:
        hit = matcher(raw)
        if hit:
            return hit
    return None


def find_popup_failure(win, keywords=SALES_FAIL_KEYWORDS):
    """화면에 실패 안내 문구가 떠 있으면 그 문구를, 없으면 None 을 돌려준다.

    메인 창 안의 오버레이 팝업용이라 창 전체의 Text 를 훑는다. 팝업이 떠 있는
    순간에만 부르므로 비용은 문제가 되지 않는다. (별도 창 팝업은 handle_sales_popups)
    """
    return _find_popup_text(win, lambda raw: match_sales_failure(raw, keywords))


def find_popup_error(win):
    """메인 창 안 오버레이에 ERPia 내부 오류 문구가 떠 있으면 그 문구를, 없으면 None."""
    return _find_popup_text(win, match_error_popup)


def visible_child_windows(hwnd):
    """메인 창의 보이는 자식 창 목록 {hwnd: (class, rect)}"""
    out = {}

    def cb(h, _):
        try:
            if win32gui.IsWindowVisible(h):
                out[h] = (win32gui.GetClassName(h), win32gui.GetWindowRect(h))
        except Exception:
            pass
        return True

    try:
        win32gui.EnumChildWindows(hwnd, cb, None)
    except Exception:
        pass
    return out


def detect_spinner(hwnd, baseline_children, min_size=100):
    """비동기 실행중 스피너(그리드 위를 덮는 로딩 오버레이)를 찾는다.

    실측 결과 이 오버레이는 그리드 영역을 통째로 덮는 자식 창으로 나타난다.
    (예: rect=(261, 718, 2549, 1381) = 하단 그리드 영역)
    따라서 기준선에 없던, 일정 크기 이상의 '보이는' 자식 창을 스피너로 판단한다.
    """
    cur = visible_child_windows(hwnd)
    candidates = []
    for h in set(cur) - set(baseline_children):
        cls, rect = cur[h]
        w, hgt = rect[2] - rect[0], rect[3] - rect[1]
        if w >= min_size and hgt >= min_size:
            candidates.append((h, cls, rect))
    return candidates


def probe_spinner(hwnd, baseline_children, seconds=5.0, interval=0.5):
    """'예' 클릭 직후 짧게 빠른 샘플링을 해서 스피너(자식 창)의 정체를 로그로 남긴다."""
    found = {}
    elapsed = 0.0
    while elapsed < seconds:
        cur = visible_child_windows(hwnd)
        for h in set(cur) - set(baseline_children):
            if h not in found:
                found[h] = cur[h]
                cls, rect = cur[h]
                log(f"  (프로브 {elapsed:.1f}s) 새 자식창 hwnd={h} class='{cls}' rect={rect}")
        time.sleep(interval)
        elapsed += interval
    if not found:
        log("  (프로브) 새로 나타난 자식 창 없음 - 스피너는 자식 창이 아닌 것으로 보임")
    return found


def wait_async_then_confirm(app, hwnd, baseline_children, poll=ASYNC_POLL_SECONDS,
                            max_wait=ASYNC_MAX_WAIT_SECONDS):
    """비동기 처리(스피너)가 끝나기를 기다리고, 팝업이 뜨면 '예/확인'을 누른다.

    - 팝업이 이미 떠 있으면 즉시 누른다.
    - 아니면 poll초 간격으로 스피너가 사라졌는지 확인한다.
    - 스피너가 사라진 뒤 팝업이 뜨면 누른다.
    반환: "clicked" | "no_popup" | "timeout" | "sales_failed"
    """
    idle_since = None
    waited = 0.0
    reported = None
    gate = PopupGate(hwnd)
    try:
        pid = win32process.GetWindowThreadProcessId(hwnd)[1]
    except Exception:
        pid = None
    tried = {}

    while waited <= max_wait:
        # 별도 창 팝업 (개체 참조 오류 등). 메인 창의 자식이 아니라 gate 로는 안 보인다.
        # 모달이라 닫지 않으면 뒤이은 실패 팝업도 뜨지 않는다.
        if pid:
            failure, closed = handle_sales_popups(pid, hwnd, tried)
            if failure:
                log(f"  [{waited:.0f}s] 매출처리 실패 팝업: {failure}")
                return "sales_failed"
            if closed:
                idle_since = None   # 닫은 뒤 뜰 팝업을 기다릴 시간을 다시 준다

        # 팝업 조회는 창 전체를 훑어 비싸므로, 자식 창이 바뀌었을 때만 한다.
        if gate.should_scan():
            win = app.window(handle=hwnd)
            btn = find_popup_ok_button(win)
            if btn is not None:
                failure = find_popup_failure(win)
                if failure:
                    # 팝업은 닫아 화면을 정리하고, 판단은 호출한 쪽에 맡긴다.
                    log(f"  [{waited:.0f}s] 매출처리 실패 팝업: {failure}")
                    ec.ensure_foreground(hwnd)
                    btn.click_input()
                    return "sales_failed"
                error = find_popup_error(win)
                if error:
                    # 내부 오류는 끝이 아니다. 닫고 계속 기다린다 (뒤에 실패 팝업이 올 수 있다).
                    label = btn.window_text()
                    log(f"  [{waited:.0f}s] 오류 팝업: {error} -> '{label}' 클릭, 계속 기다립니다")
                    status.note(f"오류 팝업 처리: {error[:60]}")
                    ec.ensure_foreground(hwnd)
                    btn.click_input()
                    idle_since = None
                    time.sleep(poll)
                    waited += poll
                    continue
                label = btn.window_text()
                log(f"  [{waited:.0f}s] 팝업 감지 -> '{label}' 클릭")
                ec.ensure_foreground(hwnd)
                btn.click_input()
                return "clicked"

        spinner = detect_spinner(hwnd, baseline_children)
        if spinner:
            idle_since = None
            if reported != "busy":
                log(f"  [{waited:.0f}s] 비동기 실행중(스피너 {len(spinner)}개: {spinner[:2]})"
                    f" - {poll}초 간격으로 확인")
                reported = "busy"
        else:
            if idle_since is None:
                idle_since = waited
                if reported != "idle":
                    log(f"  [{waited:.0f}s] 스피너/팝업 없음 "
                        f"- {ASYNC_IDLE_SECONDS}초 더 지켜봅니다")
                    reported = "idle"
            if waited - idle_since >= ASYNC_IDLE_SECONDS:
                return "no_popup"

        time.sleep(poll)
        waited += poll

    return "timeout"


def get_onscreen_tables(win):
    tables = win.descendants(control_type="Table")
    win_rect = win.rectangle()

    def is_onscreen(t):
        r = t.rectangle()
        return r.left >= win_rect.left - 5 and r.top >= win_rect.top - 5 and r.width() > 50 and r.height() > 50

    return [t for t in tables if is_onscreen(t)]


def legacy_value(ctrl):
    try:
        return ctrl.legacy_properties().get("Value", "")
    except Exception:
        return None


def scan_current_view(grid, id_columns):
    items = grid.descendants(control_type="DataItem")
    row_nums = sorted({int(m.group(1)) for it in items if (m := re.search(r"행 (\d+)$", it.window_text()))})
    by_name = {it.window_text(): it for it in items}

    view = {}
    for r in row_nums:
        key_parts = []
        ok = True
        for col in id_columns:
            c = by_name.get(f"{col} 행 {r}")
            if c is None:
                ok = False
                break
            key_parts.append(str(legacy_value(c)))
        if not ok or not any(key_parts):
            continue
        id_val = "|".join(key_parts)

        cb_ctrl = by_name.get(f"row Check Box 행 {r}")
        if cb_ctrl is None:
            status = "no_checkbox"
        else:
            v = legacy_value(cb_ctrl)
            status = "null" if v == "" else ("checked" if v == "선택" else "unchecked")
        view[id_val] = status
    return view


def get_vertical_scrollbar(grid):
    parent = grid.parent()
    sbars = parent.descendants(control_type="ScrollBar")
    vertical = [s for s in sbars if s.rectangle().height() > s.rectangle().width() and s.rectangle().width() > 0]
    return vertical[0] if vertical else None


def scroll_grid_to_top(hwnd, grid, max_pages=200):
    """스크롤바의 '페이지 위로' 버튼을 반복 클릭해 그리드를 맨 위로 올린다.
    맨 위에 도달하면 '페이지 위로' 버튼이 사라지므로 그것을 종료 조건으로 쓴다."""
    for _ in range(max_pages):
        vsb = get_vertical_scrollbar(grid)
        if vsb is None:
            return
        pgup = next((c for c in vsb.descendants() if c.window_text() == "페이지 위로"), None)
        if pgup is None:
            return
        ec.ensure_foreground(hwnd)
        pgup.click_input()
        time.sleep(0.4)


def summarize(all_ids):
    checked = [k for k, v in all_ids.items() if v == "checked"]
    unchecked = [k for k, v in all_ids.items() if v == "unchecked"]
    null_cb = [k for k, v in all_ids.items() if v == "null"]
    return checked, unchecked, null_cb


def select_all_and_verify(grid_name, hwnd, grid, id_columns, max_clicks=2):
    """전체선택 헤더를 눌러 전체선택 상태로 만든다.

    - 헤더는 '토글'이라 이미 전체선택된 상태에서 누르면 오히려 해제된다.
      따라서 누르기 전/후에 체크박스가 실제로 선택됐는지 반드시 확인한다.
    - 전체 행을 스크롤하며 검증하는 절차는 기획 변경으로 제외했다.
      (필요해지면 아래 주석 처리된 블록을 다시 켜면 된다)
    """
    header = next((c for c in grid.descendants() if c.window_text() == "row Check Box"), None)
    if header is None:
        log(f"[{grid_name}] 헤더 'row Check Box'를 찾지 못했습니다. 건너뜁니다.")
        return

    for attempt in range(1, max_clicks + 1):
        view = scan_current_view(grid, id_columns)
        v_checked, v_unchecked, v_null = summarize(view)

        if v_checked and not v_unchecked:
            reason = "이미 전체선택 상태 (토글이라 누르지 않음)" if attempt == 1 else "클릭 반영 확인됨"
            log(f"[{grid_name}] 체크 상태 확인: 체크됨 {len(v_checked)} / 미체크 0 / null(정상) {len(v_null)}"
                f" -> {reason}")
            return len(v_checked)

        log(f"[{grid_name}] 체크 상태 확인: 체크됨 {len(v_checked)} / 미체크 {len(v_unchecked)}"
            f" -> 헤더 클릭(전체선택) 시도 {attempt}")
        ec.ensure_foreground(hwnd)
        header.click_input()
        time.sleep(1.0)

    # 마지막 클릭 후 상태 확인
    view = scan_current_view(grid, id_columns)
    v_checked, v_unchecked, v_null = summarize(view)
    if v_unchecked or not v_checked:
        log(f"[{grid_name}] 경고: 전체선택 실패 (체크됨 {len(v_checked)} / 미체크 {len(v_unchecked)})")
    else:
        log(f"[{grid_name}] 전체선택 확인됨 (체크됨 {len(v_checked)} / null(정상) {len(v_null)})")
    return len(v_checked)

    # --- 아래는 '스크롤하며 전 행 검증' 절차 (기획 변경으로 현재 미사용) ---
    # scroll_grid_to_top(hwnd, grid)
    # all_ids = scan_all_rows(hwnd, grid, id_columns)
    # checked, unchecked, null_cb = summarize(all_ids)
    # log(f"[{grid_name}] 전체 검증: 고유 {len(all_ids)} / 체크됨 {len(checked)} / "
    #     f"미체크 {len(unchecked)} / null(정상) {len(null_cb)}")
    # if unchecked:
    #     log(f"[{grid_name}] 경고: 미체크 행 존재 - {unchecked[:5]}")


def run_self_check():
    """경로/설정이 제대로 잡히는지만 확인하고 끝낸다 (루틴은 실행하지 않는다).

    exe 로 배포한 뒤 "설정을 못 읽는다" 같은 문제를 현장에서 바로 확인하기 위한 모드.
    실행: ERPia_RPA.exe --check
    """
    log(f"=== 설정 점검 {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
    log(f"실행 형태   : {status.run_kind()}")
    log(f"프로그램 폴더: {status.program_dir()}")
    log(f"기록 폴더   : {BASE_DIR}{'  (새 구조)' if status.new_layout() else ''}")
    log(f"바탕화면    : {pl.DESKTOP_DIR}  {'있음' if os.path.isdir(pl.DESKTOP_DIR) else '없음!'}")
    log(f"작업 폴더   : {pl.AI_DIR}  {'있음' if os.path.isdir(pl.AI_DIR) else '없음!'}")
    user_cfg = status.user_config_path()
    log(f"사용자 설정 : {user_cfg}  {'있음' if os.path.exists(user_cfg) else '없음 (옛 ERPIA_AI.txt·WebManageConfig.json 을 읽는다)'}")
    log(f"엑셀 폴더   : {excel_upload_dir()}")
    log(f"저장 폴더   : {os.path.join(pl.AI_DIR, JOBS_DIR_NAME)}")

    try:
        admin_code, user_id, password = pl.load_credentials()
        log(f"로그인 정보 : 업체코드={admin_code} 아이디={user_id} 비밀번호=({len(password)}자)")
    except Exception as e:
        log(f"로그인 정보 : 읽기 실패 - {e}")

    try:
        options = pl.load_logistic_options()
        is_auto = resolve_auto_mode(options)
        log(f"물류 설정   : {options}")
        log(f"  -> 모드 {AUTO_MODE_LABEL[is_auto]} / 누를 버튼 '{AUTO_MODE_BUTTON[is_auto]}'")
        log(f"  -> 택배사 '{options.get('cboTag')}' / 박스 '{options.get('cboTagAmt')}' "
            f"/ 구분 '{options.get('cboBeasong_Gu_Apply')}'")
        log(f"  -> 프린터 '{options.get(PRINTER_CONFIG_KEY) or '(미설정: 기본 프린터)'}'")
    except Exception as e:
        log(f"물류 설정   : 읽기 실패 - {e}")

    try:
        selected, unknown = pl.load_routine_modules([m[1] for m in ROUTINE_MODULES])
        log("실행 모듈   : " + " / ".join(
            f"{label} {'켬' if selected[cfg] else '끔'}" for _, cfg, label, _, _ in ROUTINE_MODULES))
        for k in unknown:
            log(f"  -> 경고: '{pl.ROUTINE_SECTION}' 섹션의 '{k}' 는 모르는 키입니다 (무시됨)")
    except Exception as e:
        log(f"실행 모듈   : 읽기 실패 - {e}")

    try:
        found, configured = status.find_erpia_exe()   # 점검은 찾기만 한다 (고쳐 적거나 창을 띄우지 않는다)
        if found and os.path.normpath(configured or "") == found:
            log(f"프로그램    : {found}  있음")
        elif found:
            log(f"프로그램    : {found}  있음 (적힌 값 '{configured or '없음'}' 은 틀려서 찾아냄 - 실행하면 고쳐 적는다)")
        else:
            log(f"프로그램    : 못 찾음! (적힌 값 '{configured or '없음'}'. 루틴을 직접 실행하면 고르는 창이 뜬다)")
    except Exception as e:
        log(f"프로그램    : 찾기 실패 - {e}")

    try:
        log(f"실행 상태   : ERPiaMain.exe 실행 중 (PID={ec.find_erpia_pid()})")
    except Exception:
        log("실행 상태   : ERPiaMain.exe 실행되어 있지 않음")

    log("=== 점검 끝 (루틴은 실행하지 않았습니다) ===")


def run_uia_check():
    """화면 요소 조회(UIA)가 실제로 되는지 확인한다. 클릭 등 조작은 하지 않는다.

    pywinauto 는 내부에서 comtypes 로 COM 인터페이스 모듈을 실행 중에 만들어 쓴다.
    exe 로 묶으면 이 부분이 실패해 '창은 찾는데 안이 안 보이는' 상태가 되는 일이 있어,
    배포 전에 여기까지 되는지 확인해 둔다.
    실행: ERPia_RPA.exe --uiacheck
    """
    log(f"=== 화면 조회(UIA) 점검 {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
    log(f"실행 형태: {status.run_kind()}")

    try:
        pid = ec.find_erpia_pid()
    except Exception as e:
        log(f"ERPiaMain.exe 를 찾지 못했습니다: {e}")
        log("프로그램을 먼저 실행하고 로그인한 뒤 다시 시도하세요.")
        return False
    log(f"프로세스 확인: PID={pid}")

    try:
        hwnd = ec.wait_for_main_hwnd(pid, timeout=10)
        log(f"메인 창 확보: hwnd={hwnd}")
    except Exception as e:
        log(f"메인 창을 찾지 못했습니다: {e}")
        return False

    try:
        app = Application(backend="uia").connect(handle=hwnd)
        win = app.window(handle=hwnd)
        log(f"UIA 연결 성공: 창 이름='{win.window_text()}' 크기={win.rectangle()}")
    except Exception as e:
        log(f"UIA 연결 실패: {e}")
        return False

    try:
        buttons = [b.window_text() for b in win.descendants(control_type="Button")
                   if b.window_text()]
        log(f"버튼 조회 성공: {len(buttons)}개")
        log(f"  예시: {buttons[:8]}")
    except Exception as e:
        log(f"버튼 조회 실패: {e}")
        return False

    try:
        active = get_active_main_tab(app, hwnd)
        log(f"활성 메인탭: '{active}'")
    except Exception as e:
        log(f"탭 조회 실패: {e}")
        return False

    try:
        tables = get_onscreen_tables(win)
        log(f"그리드 조회 성공: {len(tables)}개")
        for t in sorted(tables, key=lambda x: x.rectangle().top):
            log(f"  {t.rectangle()} 컬럼 {len(grid_column_names(t))}개")
    except Exception as e:
        log(f"그리드 조회 실패: {e}")
        return False

    try:
        r = win.rectangle()
        el = element_at_point((r.left + r.right) // 2, (r.top + r.bottom) // 2)
        log(f"좌표 조회(ElementFromPoint) 성공: '{el.window_text()}' "
            f"[{el.element_info.control_type}]")
    except Exception as e:
        log(f"좌표 조회 실패: {e}")
        return False

    log("=== 모든 화면 조회 기능 정상 (클릭은 하지 않았습니다) ===")
    return True


# ---------------------------------------------------------------------------
# 화면 모듈. 각 모듈은 ctx 하나를 받아 (결과, 사유) 를 돌려준다.
#   결과: "done"      처리함
#         "no_target" 할 것이 없었음 (정상)
#         "skipped"   업체에 그 메뉴가 없어 건너뜀 (정상)
#         "stopped"   업무 규칙상 중단 (매출처리 실패, 저장 검증 오류 등) -> 뒤 모듈을 돌리지 않는다
#         "failed"    기술적 실패 (화면/버튼을 못 찾음 등) -> 뒤 모듈을 돌리지 않는다
# 모듈 안의 대시보드 단계(status.step)는 모듈 함수가 스스로 찍는다. finish 는 main 이 부른다.
# ---------------------------------------------------------------------------

def module_login(ctx):
    """ERPia 를 띄우고(이미 떠 있으면 그대로) 로그인한 뒤 메인 창을 잡는다."""
    status.step("login")
    admin_code, user_id, password = pl.load_credentials()
    ctx.pid = ensure_erpia_running()

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

    # 스플래시/초기 창을 메인 창으로 오인하지 않도록 좌측 메뉴가 보일 때까지 기다린다.
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
            # 창이 다시 만들어져 핸들이 무효가 됐다. 메인 창을 다시 잡는다.
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

    status.step("top_select")
    log("\n=== 좌측 상단 그리드 전체선택 ===")
    n_top = select_all_and_verify("좌측상단", hwnd, top_left, ["아이디"])
    if n_top is not None:
        status.metric("top_selected", "상단 선택", n_top, note="화면에 보이는 행 기준")

    log("\n=== 주문 가져오기 ===")
    if not run_import_step(app, pid, hwnd, win):
        log("경고: 주문 가져오기를 끝까지 확인하지 못했습니다. 이어서 진행합니다.")
    win = app.window(handle=hwnd)

    # 7-1. 엑셀업로드 (바탕화면 ERPIA_AI_EXCEL 폴더에 파일이 있을 때만)
    status.step("excel_upload")
    log("\n=== 엑셀업로드 ===")
    try:
        run_excel_upload_step(app, pid, hwnd, top_left)
    except Exception as e:
        log(f"경고: 엑셀업로드 처리 중 오류가 발생해 건너뜁니다: {e}")

    # 8. 하단 전체선택
    status.step("bottom_select")
    log("\n=== 하단 그리드 전체선택 ===")
    n_bottom = select_all_and_verify("하단", hwnd, bottom, ["주문번호", "마켓 상품명", "주문시간"])
    if n_bottom is not None:
        status.metric("bottom_selected", "하단 선택", n_bottom, note="화면에 보이는 행 기준")

    # 9. 매출처리 ▼ -> 정상매출
    status.step("sales")
    log("\n=== 매출처리 드롭다운 -> 정상매출 ===")
    # '매출처리'는 SplitButton 이다 (Button 으로 찾으면 못 찾고 전체 순회로 떨어져 더 느리다)
    split_btn = find_by_text(win, "매출처리", control_types=("SplitButton",))
    if split_btn is None:
        return "failed", "'매출처리' 버튼을 찾지 못했습니다."
    dropdown_btn = next((c for c in split_btn.descendants(control_type="Button")), None)
    if dropdown_btn is None:
        return "failed", "드롭다운(▼) 버튼을 찾지 못했습니다."
    ec.ensure_foreground(hwnd)
    dropdown_btn.click_input()
    time.sleep(1.0)

    menu_win = None
    for w in Desktop(backend="uia").windows():
        try:
            _, wpid = win32process.GetWindowThreadProcessId(w.handle)
        except Exception:
            continue
        if wpid != pid:
            continue
        try:
            buttons = [b.window_text() for b in w.descendants(control_type="Button")]
        except Exception:
            continue
        if "정상매출" in buttons:
            menu_win = w
            break

    if menu_win is None:
        return "failed", "드롭다운 메뉴(선택매출/정상매출)를 찾지 못했습니다."

    # 스피너 비교용 기준선(정상매출 클릭 전 상태) 확보
    baseline_children = visible_child_windows(hwnd)

    normal_btn = next(b for b in menu_win.descendants(control_type="Button") if b.window_text() == "정상매출")
    normal_btn.click_input()
    time.sleep(1.5)
    log("'정상매출' 클릭 완료")

    # 10. 확인 팝업 -> '예/확인' 클릭
    status.note("확인 팝업 처리")
    log("\n=== 확인 팝업 처리 ===")
    win = app.window(handle=hwnd)
    confirm_btn = find_popup_ok_button(win)
    if confirm_btn is None:
        log("확인 팝업이 뜨지 않았습니다. 비동기 대기 단계로 넘어갑니다.")
    else:
        failure = find_popup_failure(win)
        if failure:
            log(f"매출처리 실패 팝업이 떴습니다: {failure}")
            ec.ensure_foreground(hwnd)
            confirm_btn.click_input()
            log("이후 단계를 진행하지 않고 루틴을 중단합니다.")
            return "stopped", f"매출처리 실패: {failure}"
        label = confirm_btn.window_text()
        log(f"확인 팝업 감지 -> '{label}' 클릭")
        ec.ensure_foreground(hwnd)
        confirm_btn.click_input()
        time.sleep(1.5)

    # 11. 비동기 실행(스피너) 대기 -> 완료 팝업 '예/확인' 클릭
    status.note("매출 처리가 끝나기를 기다리는 중")
    log("\n=== 비동기 처리 대기 및 완료 팝업 처리 ===")
    probe_spinner(hwnd, baseline_children)
    result = wait_async_then_confirm(app, hwnd, baseline_children)
    if result == "sales_failed":
        log("정상매출이 실패했습니다.")
        log("이후 단계(물류대기/물류 관리)를 진행하지 않고 루틴을 중단합니다.")
        return "stopped", "정상매출이 실패했습니다"
    if result == "clicked":
        log("완료 팝업의 '예/확인'을 눌렀습니다.")
    elif result == "no_popup":
        log("스피너도 팝업도 없어 처리가 끝난 것으로 판단합니다.")
    else:
        log(f"경고: 최대 대기시간({ASYNC_MAX_WAIT_SECONDS}초)을 초과했습니다.")

    # 혹시 연속으로 뜨는 팝업이 더 있으면 한 번 더 확인 (별도 창 먼저)
    time.sleep(2)
    failure, _ = handle_sales_popups(pid, hwnd, {})
    if failure:
        log(f"매출처리 실패 팝업이 떴습니다: {failure}")
        log("이후 단계를 진행하지 않고 루틴을 중단합니다.")
        return "stopped", f"매출처리 실패: {failure}"
    win = app.window(handle=hwnd)
    extra_btn = find_popup_ok_button(win)
    if extra_btn is not None:
        failure = find_popup_failure(win)
        ec.ensure_foreground(hwnd)
        extra_btn.click_input()
        if failure:
            log(f"매출처리 실패 팝업이 떴습니다: {failure}")
            log("이후 단계를 진행하지 않고 루틴을 중단합니다.")
            return "stopped", f"매출처리 실패: {failure}"
        log(f"추가 팝업 감지 -> '{extra_btn.window_text()}' 클릭")
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
    if result == "no_target":
        return "no_target", "물류대기 그리드에 행이 없어 저장하지 않았습니다."
    if result != "done":
        return "failed", "물류대기 처리에 실패했습니다."
    return "done", None


def module_logistics(ctx):
    """물류관리: 화면 이동 -> 자동/수동 -> 개별 배송 -> 배송정보설정(항상) -> 저장.

    배송정보설정은 로그인 세션마다 초기화되므로, 배송을 만들었으면 이 모듈 안에서 반드시 돈다.
    실패하면 잘못된 택배사/구분으로 저장하지 않도록 중단한다.
    하단 그리드가 0건이면 만들 배송이 없으므로 모듈 전체를 '대상 없음' 으로 끝낸다.
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

    # 여기가 틀리면 잘못된 택배사/배송구분으로 저장되므로 실패 시 진행하지 않는다.
    status.step("shipping_setup")
    log("\n=== 배송정보설정 (업체/박스/구분) ===")
    if not run_shipping_setup_step(ctx.app, ctx.pid, ctx.hwnd, options=options):
        # 기술적으로는 '못 맞춤' 이지만, 잘못된 택배사/구분으로 저장되는 것을 막는 업무 규칙상의 중단이라
        # failed 가 아니라 stopped 로 둔다 (대시보드에 '중단' 으로 보인다).
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

    - 물류관리 모듈이 이번 실행에서 'done' 이면 예전 흐름 그대로 (팝업 정책 continue).
    - 물류관리가 이번 실행에서 돌았는데 done 이 아니면(대상 없음/실패) 출력할 배송장이 없으니
      아무것도 누르지 않고 '대상 없음'.
    - 물류관리를 설정에서 끈 채 출력만 돌리면: 화면을 스스로 '물류 관리' 로 옮기고 자동/수동을
      설정값대로 맞춘 뒤(출력은 화면 콤보의 현재값을 따른다), '이미 출력한 배송장' 팝업에서는
      아니오를 누르고 끝낸다 (중복 인쇄 금지).
    """
    status.step("output")
    logistics_result = ctx.results.get("logistics")
    if logistics_result is not None and logistics_result != "done":
        return "no_target", (f"물류관리 모듈이 '{MODULE_RESULT_LABEL.get(logistics_result, logistics_result)}' "
                             f"로 끝나 출력할 배송장이 없습니다.")

    if logistics_result is None:
        log("\n=== 물류 관리 화면 이동 (출력 단독 실행) ===")
        r = goto_logistics_screen(ctx)
        if r != "ok":
            return "failed", ("'물류처리' 아이콘을 찾지 못했습니다." if r == "absent"
                              else "물류 관리 화면으로 이동하지 못했습니다.")
        prefetch_auto_ids(ctx.window(), [AUTO_MODE_COMBO])
        log("자동/수동 모드 설정")
        _, mode_ok = apply_auto_mode(ctx.app, ctx.hwnd, ctx.logistic_options())
        if not mode_ok:
            return "failed", "자동/수동 모드를 설정하지 못해 출력하지 않습니다."

    log("\n=== 운송장 출력 / 엑셀파일 생성 ===")
    policy = "continue" if logistics_result == "done" else "stop"
    result = run_print_step(ctx.app, ctx.pid, ctx.hwnd, options=ctx.logistic_options(),
                            already_printed=policy)
    if result == "already_printed":
        return "no_target", "이미 출력한 배송장이라 다시 출력하지 않았습니다."
    if result == "stuck":
        return "failed", "출력 팝업을 처리하지 못해 메인 창에 남겨두었습니다. 팝업을 닫은 뒤 다시 실행하세요."
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
    if not any(selected.get(cfg, True) for _, cfg, _, _, _ in ROUTINE_MODULES):
        for key, _cfg, _label, steps, _bit in ROUTINE_MODULES:
            status.module_off(key, status.OFF_NOTE)
            for s in steps:
                status.skip(s, status.OFF_NOTE)
        return "stopped", f"켜진 모듈이 없습니다 ('{pl.ROUTINE_SECTION}' 섹션 확인)"

    ctx = RoutineContext()
    for key, cfg_key, label, steps, _bit in ROUTINE_MODULES:
        if not selected.get(cfg_key, True):
            log(f"\n=== [{label}] 설정에서 꺼져 있어 건너뜁니다 ({cfg_key}=N) ===")
            status.module_off(key, status.OFF_NOTE)
            for s in steps:
                status.skip(s, status.OFF_NOTE)
            continue

        if key != "login" and ctx.hwnd is None:
            ok, reason = ctx.attach()
            if not ok:
                log(f"[{label}] {reason}")
                status.module_start(key)
                status.step(steps[0])   # 단계 목록에도 어디서 멈췄는지 보이게 (첫 단계를 실패로 닫는다)
                status.module_done(key, "failed", reason)
                return "stopped", reason
            log(f"이미 떠 있는 ERPia 에 붙었습니다: pid={ctx.pid} hwnd={ctx.hwnd}")

        status.module_start(key)
        log(f"\n=== [{label}] 시작 ===")
        result, reason = MODULE_FUNCS[key](ctx)
        if reason is None and result in ("failed", "stopped"):
            reason = status.last_problem()
        status.module_done(key, result, reason)
        ctx.results[key] = result
        log(f"=== [{label}] {MODULE_RESULT_LABEL.get(result, result)}"
            f"{' - ' + reason if reason else ''} ===")
        if result in ("failed", "stopped"):
            return "stopped", reason
    return "success", None


def main():
    if "--check" in sys.argv[1:]:
        run_self_check()
        return
    if "--uiacheck" in sys.argv[1:]:
        run_uia_check()
        return

    status.start("routine", ROUTINE_STEPS)
    status.set_modules([(k, label, steps, bit) for k, _, label, steps, bit in ROUTINE_MODULES])
    log(f"=== 루틴 시작 {time.strftime('%Y-%m-%d %H:%M:%S')} ===")

    # 대시보드에 '업체코드 · 아이디' 로 보인다 (비밀번호는 읽지 않는다). 로그인 모듈을 꺼도 보이게 여기서.
    account = status.read_account()
    if account and (account.get("admin_code") or account.get("user_id")):
        status.account(account.get("admin_code"), account.get("user_id"))

    keys = [m[1] for m in ROUTINE_MODULES]
    selected, unknown = run_modules_from_env(keys)
    from_env = selected is not None
    if not from_env:
        try:
            selected, unknown = pl.load_routine_modules(keys)
        except Exception as e:
            log(f"설정 오류: {e}")
            status.finish("stopped", f"설정 파일 오류: {e}")
            log(f"=== 루틴 종료 {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
            return
    for k in unknown:
        log(f"경고: 예약에서 넘긴 '{k}' 는 모르는 모듈이라 무시합니다." if from_env
            else f"경고: '{pl.ROUTINE_SECTION}' 섹션의 '{k}' 는 모르는 키라 무시합니다.")
    if from_env and not any(selected.values()):
        log("이번 실행 모듈이 비었습니다 (예약에서 넘긴 값)")
        status.finish("stopped", "이번 실행 모듈이 비었습니다")
        log(f"=== 루틴 종료 {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
        return
    if from_env:
        log("이번 실행 모듈 (예약): " + " / ".join(label for _, cfg, label, _, _ in ROUTINE_MODULES if selected[cfg]))
    else:
        log("실행할 모듈: " + " / ".join(
            f"{label} {'켬' if selected[cfg] else '끔'}" for _, cfg, label, _, _ in ROUTINE_MODULES))

    result, reason = run_modules(selected)
    if os.environ.get("RPA_RUN_TRIGGER") == "repeat" and result == "success" \
            and not [k for k in (status.done_modules() or []) if k != "login"]:
        log("반복 회차 - 처리한 것이 없어 기록에 남기지 않습니다")
        status.finish(result, reason, record=False)
    else:
        status.finish(result, reason)
    log(f"=== 루틴 종료 {time.strftime('%Y-%m-%d %H:%M:%S')} ({'성공' if result == 'success' else '중단'}) ===")


if __name__ == "__main__":
    try:
        main()
    except BaseException as e:
        # 대시보드에 '비정상 종료'로 남긴다. 정상 흐름의 결과는 main() 이 이미 기록했다.
        status.fail_exception(e)
        raise
    finally:
        # log() 가 이미 한 줄씩 써 두었다. 여기서는 혹시 비어 있을 때만 채운다.
        try:
            if not _log_started:
                with open(RESULT_PATH, "w", encoding="utf-8") as f:
                    f.write("\n".join(logs))
        except Exception:
            pass
