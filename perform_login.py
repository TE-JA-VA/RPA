"""ERPia 로그인 자동화 (최종본).

규칙:
- 로그인 창의 크기/위치는 절대 건드리지 않는다 (foreground 전환만 함).
- 로그인 시도 후 팝업이 뜰 수 있음:
  - '2차 인증' 관련 안내 팝업(전화번호 미등록)이면: 확인 클릭 후 20초 대기, 그 후 로그인 재시도
  - 그 외 팝업(비밀번호 변경 요청, 비밀번호 불일치 등)이면: 즉시 작업 중단하고
    바탕화면에 'AI 로그인 실패(YYYYMMDD_HHmmss).txt' 에러 로그를 남긴다.
    (파일명에 콜론(:)은 Windows에서 사용할 수 없어 HHmmss로 대체함)
"""
import json
import os
import sys
import time
from datetime import datetime

import win32gui
import win32process
from pywinauto import Desktop

import erpia_common as ec
import rpa_status


def find_desktop_dir():
    """현재 사용자의 실제 바탕화면 폴더.

    회사 PC는 OneDrive 등으로 바탕화면이 옮겨져 있는 경우가 흔해
    '~/Desktop' 으로 단정하면 안 된다. 윈도우에 등록된 경로를 먼저 읽는다.
    실제 구현은 rpa_status 에 있다. 대시보드도 같은 폴더를 찾아야 해서 한 곳에 둔다.
    """
    return rpa_status.find_desktop_dir()


def app_base_dir():
    """로그를 둘 폴더. PyInstaller 로 묶인 상태에서는 exe 위치를 쓴다."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


# 이 프로그램이 쓰는 파일은 모두 여기 모은다.
# (설정, 받은 엑셀, 출력 결과, 실패 기록)
AI_DIR_NAME = "ERPIA_AI"
CRED_FILE_NAME = "ERPIA_AI.txt"


def find_ai_dir():
    r"""바탕화면\ERPIA_AI. 없으면 만든다.

    예전에는 이 파일들이 바탕화면에 그대로 흩어져 있었다.
    한 폴더로 모아 두면 다른 PC 로 옮길 때 헷갈릴 일이 없다.
    """
    path = os.path.join(find_desktop_dir(), AI_DIR_NAME)
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        return find_desktop_dir()
    return path


def find_cred_file():
    """ERPIA_AI.txt 위치. 새 자리에 없으면 예전 자리(바탕화면 루트)도 본다.

    이미 쓰고 있던 PC 에서 파일을 안 옮겨도 그대로 돌아가게 하기 위한 것이다.
    """
    # 대시보드(rpa_status.cred_file_path)와 같은 규칙을 쓴다 - 두 프로그램이 다른 파일을 보면 화면과 실제가 갈라진다.
    # (새 자리 -> 예전 자리 -> 새 자리 경로. 시험용 환경변수 RPA_CRED_FILE 도 같이 따른다)
    find_ai_dir()   # 새 자리 폴더는 만들어 둔다
    return rpa_status.cred_file_path()


BASE_DIR = app_base_dir()
DESKTOP_DIR = find_desktop_dir()
AI_DIR = find_ai_dir()
CRED_FILE = find_cred_file()
OUT_FILE = os.path.join(BASE_DIR, "perform_login_result.txt")

TWO_FA_KEYWORD = "2차 인증"
TWO_FA_WAIT_SECONDS = 20
MAX_TWO_FA_RETRIES = 3
POPUP_POLL_SECONDS = 5
POPUP_POLL_INTERVAL = 0.5


LOGIN_SECTION = "LogIn"
LOGISTIC_SECTION = "Logistic"


def _read_text(path):
    """설정 파일을 인코딩을 가리지 않고 읽는다.

    메모장에서 편집·저장하면 기본이 ANSI(CP949)라 한글 값이 UTF-8이 아니게 된다.
    사용자가 어떤 편집기로 저장하든 루틴이 깨지지 않도록 순서대로 시도한다.
    """
    last_error = None
    for encoding in ("utf-8-sig", "cp949", "utf-16"):
        try:
            with open(path, "r", encoding=encoding) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError) as e:
            last_error = e
    raise RuntimeError(f"{path} 의 인코딩을 알 수 없습니다: {last_error}")


def _flatten(value):
    """[{"K": v}, {"K2": v2}] 또는 {"K": v} 를 하나의 dict 로 합친다."""
    out = {}
    if isinstance(value, dict):
        out.update(value)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                out.update(item)
    return out


def load_settings():
    """ERPIA_AI.txt 를 {섹션명: {키: 값}} 형태로 읽는다.

    현재 형태 - 섹션 안에 단일키 객체들이 배열로 들어간다:
      [{"LogIn": [{"AdminCode": ...}, {"ID": ...}, {"PW": ...}]},
       {"Logistic": [{"cboTag": ...}, {"cboTagAmt": ...}, ...]}]

    섹션 없이 키가 바로 있던 옛 형태([{"AdminCode": ...}, ...])도 계속 읽을 수 있게
    LogIn 섹션에 있는 것으로 간주한다.
    """
    data = json.loads(_read_text(CRED_FILE))

    if not isinstance(data, (dict, list)):
        raise RuntimeError(
            f"{CRED_FILE} 의 JSON 최상위가 객체도 배열도 아닙니다: {type(data).__name__}")

    top = _flatten(data)
    sections = {}
    loose = {}
    for key, value in top.items():
        if isinstance(value, (dict, list)):
            sections[key] = _flatten(value)
        else:
            loose[key] = value  # 섹션으로 감싸지 않은 옛 형태
    if loose:
        sections.setdefault(LOGIN_SECTION, {}).update(loose)
    return sections


def load_credentials():
    creds = load_settings().get(LOGIN_SECTION, {})
    missing = [k for k in ("AdminCode", "ID", "PW") if not creds.get(k)]
    if missing:
        raise RuntimeError(
            f"{CRED_FILE} 의 '{LOGIN_SECTION}' 섹션에 다음 값이 없습니다: {', '.join(missing)}")
    return creds["AdminCode"], creds["ID"], creds["PW"]


def load_logistic_options():
    """물류 관리 '배송정보설정'에서 고를 값. {콤보 automation_id: 선택할 값}"""
    return load_settings().get(LOGISTIC_SECTION, {})


ROUTINE_SECTION = "Routine"


def load_routine_modules(module_keys):
    """어떤 모듈을 돌릴지. ({설정 키: True/False}, 모르는 키 목록) 을 돌려준다.

    ERPIA_AI.txt 의 "Routine" 섹션에 모듈 키마다 "Y"(켬) / "N"(끔) 을 적는다.
      예: {"Routine": [{"Login": "Y"}, {"Sales": "Y"}, {"Hold": "N"}, {"Logistics": "Y"}, {"Output": "Y"}]}
    섹션이나 키가 없으면 켠 것으로 본다 (예전 파일 그대로 돌아가게).
    그 밖의 값이면 RuntimeError - 사용자가 고치기 전에는 아무것도 돌리지 않는다.
    (어떤 모듈을 돌릴지는 사용자 설정이 정확히 지켜져야 하는 것이라, 어중간한 값을
     '켬'이나 '끔' 어느 쪽으로도 짐작하지 않는다.)
    """
    settings = load_settings()
    # {"Routine": "Y"} 처럼 섹션이 아니라 값으로 잘못 쓰면 load_settings 가 LogIn 에 섞어 넣는다.
    # 그대로 두면 '섹션 없음 = 전부 켬' 으로 읽혀 사용자 의도와 어긋나므로 여기서 잡는다.
    if settings.get(LOGIN_SECTION, {}).get(ROUTINE_SECTION) is not None:
        raise RuntimeError(
            f"{CRED_FILE} 의 '{ROUTINE_SECTION}' 은 값이 아니라 섹션이어야 합니다. "
            f'예: {{"{ROUTINE_SECTION}": [{{"Login": "Y"}}, {{"Sales": "Y"}}]}}')
    section = settings.get(ROUTINE_SECTION, {})

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


def find_login_window():
    """로그인 창을 찾는다. 닫힌 뒤에도 숨겨진 채 남아있는 잔재 창을 잘못 고르지 않도록
    visible한 것을 우선한다."""
    wins = ec.find_erpia_windows_by_title("로그인")
    if not wins:
        return None
    visible_wins = [w for w in wins if win32gui.IsWindowVisible(w.handle)]
    return visible_wins[0] if visible_wins else wins[0]


BASE_LOGIN_BUTTONS = {"닫기", "최소화", "최대화", "복원"}


def find_other_erpia_popups(exclude_handles):
    """ERPiaMain.exe 소유의, exclude_handles에 없는 별도의 최상위 팝업 창을 찾는다
    (일부 경고는 별도 창이 아니라 로그인 창 내부 오버레이로 뜨므로, 이건 보조 수단)."""
    results = []
    for w in Desktop(backend="uia").windows():
        if w.handle in exclude_handles:
            continue
        try:
            _, pid = win32process.GetWindowThreadProcessId(w.handle)
        except Exception:
            continue
        if ec.get_process_name(pid) != "ERPiaMain.exe":
            continue
        try:
            buttons = w.descendants(control_type="Button")
        except Exception:
            continue
        if buttons:
            results.append(w)
    return results


def find_embedded_popup_buttons(login_win):
    """로그인 창 내부에 기본 버튼(닫기/최소화/최대화/복원) 외의 버튼이 있으면
    경고/확인 팝업이 창 내부에 오버레이로 떠 있다는 뜻이다."""
    try:
        buttons = login_win.descendants(control_type="Button")
    except Exception:
        return []
    return [b for b in buttons if b.window_text() not in BASE_LOGIN_BUTTONS]


def collect_text(win):
    parts = [win.window_text()]
    try:
        for c in win.descendants():
            t = c.window_text()
            if t:
                parts.append(t)
    except Exception:
        pass
    return " | ".join(parts)


def fill_login_fields(login_win, admin_code, user_id, password, log):
    edits = login_win.descendants(control_type="Edit")
    edits_sorted = sorted(edits, key=lambda e: e.rectangle().top)
    if len(edits_sorted) < 6:
        raise RuntimeError(f"텍스트박스 개수가 예상과 다릅니다 ({len(edits_sorted)}개).")

    top_edit, mid_edit, bottom_edit = edits_sorted[0], edits_sorted[2], edits_sorted[4]

    def fill(edit, value, label):
        edit.click_input()
        time.sleep(0.2)
        edit.type_keys("^a{DEL}")
        edit.type_keys(value, with_spaces=True)
        log(f"  {label} 입력 완료")

    fill(top_edit, admin_code, "AdminCode(업체코드)")
    fill(mid_edit, user_id, "ID(아이디)")
    fill(bottom_edit, password, "PW(비밀번호)")


def click_login_button(login_win, log):
    pw_panel = next((c for c in login_win.descendants() if c.window_text() == "pnl_Password"), None)
    if pw_panel is None:
        raise RuntimeError("pnl_Password 패널을 찾지 못했습니다.")
    pw_bottom = pw_panel.rectangle().bottom

    candidates = [
        c for c in login_win.descendants(control_type="Text")
        if c.rectangle().top > pw_bottom and c.rectangle().height() > 30
    ]
    if not candidates:
        raise RuntimeError("로그인 버튼 후보를 찾지 못했습니다.")

    btn = min(candidates, key=lambda c: c.rectangle().top)
    log(f"  로그인 버튼 클릭: rect={btn.rectangle()}")
    ec.ensure_foreground(login_win.handle)
    btn.click_input()


def wait_for_popup(login_win, seconds=POPUP_POLL_SECONDS):
    """(팝업이 뜬 창, 그 팝업의 버튼 목록) 을 반환한다. 없으면 (None, None).
    로그인 창 내부 오버레이형 팝업과, 별도의 최상위 팝업 창 두 가지 모두 확인한다."""
    elapsed = 0.0
    while elapsed < seconds:
        embedded = find_embedded_popup_buttons(login_win)
        if embedded:
            return login_win, embedded

        others = find_other_erpia_popups({login_win.handle})
        if others:
            return others[0], others[0].descendants(control_type="Button")

        time.sleep(POPUP_POLL_INTERVAL)
        elapsed += POPUP_POLL_INTERVAL
    return None, None


def write_error_log(reason_text):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(AI_DIR, f"AI 로그인 실패({ts}).txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"발생 시각: {datetime.now().isoformat()}\n")
        f.write("사유: 예상치 못한 팝업으로 로그인 작업 중단\n\n")
        f.write(f"팝업 내용:\n{reason_text}\n")
    return path


def login_flow(admin_code, user_id, password, log=None):
    """실제 로그인 자동화 로직. 다른 스크립트(GUI 등)에서 재사용할 수 있도록 함수로 분리함.
    반환값: {"status": "success"|"already_logged_in"|"no_login_window"|"popup_error"|"max_retries"|"error",
             "message": str, "error_log_path": str|None}
    """
    if log is None:
        log = lambda msg: None

    login_win = find_login_window()
    if login_win is None:
        log("로그인 창을 찾지 못했습니다 (이미 로그인되어 있을 수 있습니다).")
        return {"status": "already_logged_in", "message": "로그인 창을 찾지 못함 (이미 로그인 상태일 수 있음)", "error_log_path": None}

    log(f"로그인 창 발견: handle={login_win.handle}")
    ec.ensure_foreground(login_win.handle)

    try:
        fill_login_fields(login_win, admin_code, user_id, password, log)
    except Exception as e:
        log(f"필드 입력 실패: {e}")
        return {"status": "error", "message": f"필드 입력 실패: {e}", "error_log_path": None}

    for attempt in range(1, MAX_TWO_FA_RETRIES + 1):
        login_win = find_login_window()
        if login_win is None:
            log(f"[시도 {attempt}] 로그인 창이 사라짐 -> 로그인 성공으로 판단")
            log("\n=== 로그인 최종 성공 ===")
            return {"status": "success", "message": "로그인 성공", "error_log_path": None}

        try:
            click_login_button(login_win, log)
        except Exception as e:
            log(f"로그인 버튼 클릭 실패: {e}")
            return {"status": "error", "message": f"로그인 버튼 클릭 실패: {e}", "error_log_path": None}

        popup_win, popup_buttons = wait_for_popup(login_win)

        if popup_win is None:
            still_open = win32gui.IsWindow(login_win.handle) and win32gui.IsWindowVisible(login_win.handle)
            if not still_open:
                log(f"[시도 {attempt}] 팝업 없이 로그인 완료됨")
                log("\n=== 로그인 최종 성공 ===")
                return {"status": "success", "message": "로그인 성공", "error_log_path": None}
            else:
                log(f"[시도 {attempt}] 팝업도 없고 로그인 창도 그대로 -> 상태 불명, 재시도")
                continue

        popup_text = collect_text(popup_win)
        log(f"[시도 {attempt}] 팝업 발견: handle={popup_win.handle} 내용='{popup_text}'")

        if TWO_FA_KEYWORD in popup_text:
            log(f"  -> 2차 인증 안내 팝업으로 판단. 확인 클릭 후 {TWO_FA_WAIT_SECONDS}초 대기합니다.")
            ok_btn = next((b for b in popup_buttons if "확인" in b.window_text()), None)
            if ok_btn is None:
                log("  '확인' 버튼을 찾지 못했습니다. 중단합니다.")
                path = write_error_log(f"[2차 인증 팝업이지만 확인 버튼 없음]\n{popup_text}")
                log(f"  에러 로그 저장: {path}")
                return {"status": "popup_error", "message": "2차 인증 팝업에 확인 버튼 없음", "error_log_path": path}

            ec.ensure_foreground(popup_win.handle)
            ok_btn.click_input()
            log(f"  확인 클릭 완료. {TWO_FA_WAIT_SECONDS}초 대기 시작...")
            time.sleep(TWO_FA_WAIT_SECONDS)
            log(f"  {TWO_FA_WAIT_SECONDS}초 대기 완료. 로그인 재시도합니다.")
            continue
        else:
            log("  -> 예상 밖 팝업(비밀번호 변경 요청/불일치 등)으로 판단. 작업을 중단합니다.")
            path = write_error_log(popup_text)
            log(f"  에러 로그 저장: {path}")
            return {"status": "popup_error", "message": f"예상 밖 팝업: {popup_text}", "error_log_path": path}

    log(f"최대 재시도({MAX_TWO_FA_RETRIES}회) 초과. 중단합니다.")
    path = write_error_log("2차 인증 팝업이 반복적으로 발생하여 최대 재시도 횟수를 초과함")
    log(f"에러 로그 저장: {path}")
    return {"status": "max_retries", "message": "2차 인증 팝업 반복으로 최대 재시도 초과", "error_log_path": path}


def main():
    logs = []

    def log(msg):
        logs.append(msg)
        print(msg)

    admin_code, user_id, password = load_credentials()
    result = login_flow(admin_code, user_id, password, log)
    log(f"\n결과: {result['status']} - {result['message']}")

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(logs))


if __name__ == "__main__":
    main()
