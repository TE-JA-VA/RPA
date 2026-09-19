# -*- coding: utf-8 -*-
r"""휴대폰으로 오는 문자에서 인증번호를 뽑아 클립보드에 넣어주는 상주 프로그램.

ERPia 루틴(run_routine.py)과는 완전히 별개로 동작하며, 보통 루틴보다 먼저 실행해 둔다.
서로 import 하지 않으므로 exe 도 따로 만든다.

동작 방식
    'PC와 연결'(Phone Link) 앱이 아이폰에서 받아온 문자를 UIA 로 읽는다.
    대화 목록(CVSListView)의 각 항목에는 그 대화의 '마지막 문자 전문'이 들어 있다.
    실측 결과 이 미리보기는 잘리지 않아서(402자/627자 확인) 대화를 열어볼 필요가 없다.
    덕분에 클릭이 전혀 없고, 사용자가 앱을 쓰는 것을 방해하지 않는다.

    프로그램이 뜬 시점의 문자들을 '이미 본 것'으로 기록해 두고,
    그 뒤에 새로 도착한 문자만 검사한다.

왜 UIA 인가 (다른 길을 먼저 확인했다)
    Phone Link 는 %LOCALAPPDATA%\Packages\Microsoft.YourPhone_*\...\phone.db 에
    message 테이블을 두지만, 이건 안드로이드를 붙였을 때만 채워진다.
    아이폰은 문자를 로컬 DB 에 남기지 않는다(이 PC 의 phone.db 는 6개월 전에서 멈춰 있다).
    그래서 아이폰에서는 화면을 읽는 방법뿐이다.

아이폰 사용 시 알아둘 제약
    - 블루투스로 연결되어 있는 동안 도착한 문자만 들어온다.
      연결이 끊긴 사이에 온 문자는 나중에 소급해서 받아오지 못한다.
    - Phone Link 창이 열려 있어야 한다(다른 창에 가려져 있어도 된다).
    - 같은 사람이 완전히 똑같은 내용을 연달아 보내면 두 번째는 구분하지 못한다.
      (목록에 보이는 것이 '마지막 문자 한 건'뿐이라 변화가 생기지 않는다)

사용법
    python sms_watch.py             감시 시작 (Ctrl+C 로 종료)
    python sms_watch.py --once      지금 목록만 한 번 검사하고 종료
    python sms_watch.py --list      현재 대화 목록을 보여준다 (점검용, 내용은 가림)
    python sms_watch.py --check     실행 환경 자체 점검
    python sms_watch.py --seconds N N초 동안만 감시하고 종료
"""
import argparse
import ctypes
import datetime
import os
import re
import subprocess
import sys
import time

import win32clipboard
import win32con
import win32gui
from pywinauto import Application

# ---------------------------------------------------------------------------
# 설정값
# ---------------------------------------------------------------------------
# Phone Link 메인 창. 창 제목은 Windows 표시 언어에 따라 달라진다.
PHONE_LINK_CLASS = "WinUIDesktopWin32WindowClass"
PHONE_LINK_TITLES = ("휴대폰과 연결", "PC와 연결", "Phone Link", "Your Phone")
PHONE_LINK_APPID = r"Microsoft.YourPhone_8wekyb3d8bbwe!App"

# UIA automation id (창 제목과 달리 언어를 타지 않아 이쪽을 기준으로 삼는다)
AID_CHAT_TAB = "ChatNodeAutomationId"     # '메시지' 탭
AID_CONV_LIST = "CVSListView"             # 대화 목록

# 대화 목록 항목 텍스트에서 본문 앞에 붙는 안내 문구
PREVIEW_MARKERS = ("메시지 미리 보기", "Message preview")
NAME_SUFFIX_RE = re.compile(r"^(.*?)(?:와|과)의 대화(?=[\s.,])")

# 휴대폰 연결이 끊겼을 때 화면에 뜨는 안내 문구.
# 머리말은 '연결됨'이라고 표시하면서 아래에 이 문구가 떠 있는 경우가 있다.
# 이걸 못 보면 '문자가 안 온다'는 증상만 남아 원인을 찾지 못한다(실제로 겪었다).
CONNECTION_ERROR_MARKERS = (
    "연결하는 데 문제",
    "Bluetooth를 활성화",
    "다시 연결",
    "연결되어 있지 않",
    "Trouble connecting",
    "Reconnect",
)

KEYWORD = "인증번호"
POLL_SECONDS = 2.0            # 목록 읽기가 0.1초 미만이라 촘촘히 봐도 부담이 없다
LAUNCH_WAIT_SECONDS = 40      # 앱을 새로 띄웠을 때 창이 뜨기를 기다리는 시간
RECONNECT_WAIT_SECONDS = 5


def app_base_dir():
    """PyInstaller 로 묶이면 __file__ 이 임시폴더를 가리키므로 exe 위치를 쓴다."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = app_base_dir()
LOG_PATH = os.path.join(BASE_DIR, "sms_watch_log.txt")


def log(msg, secret=False):
    """화면에 찍고 파일에도 남긴다.

    secret=True 인 줄은 파일에는 남기지 않는다.
    인증번호가 로그 파일에 평문으로 쌓이면 곤란하기 때문이다.
    """
    line = f"[{datetime.datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    if secret:
        return
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 인증번호 추출
# ---------------------------------------------------------------------------
# 괄호로 감싼 코드가 있으면 그게 가장 확실하다: 인증번호 [123456]
BRACKET_CODE_RE = re.compile(r"[\[(<【]\s*([0-9A-Za-z]{4,8})\s*[\])>】]")
# 맨숫자 코드. 앞뒤에 숫자나 '-' 가 붙어 있으면 전화번호/날짜일 가능성이 커서 제외한다.
# 한글 바로 옆에 붙어 있어도 잡아야 하므로 \b 대신 전후방탐색을 쓴다.
PLAIN_CODE_RE = re.compile(r"(?<![0-9\-])([0-9]{4,8})(?![0-9\-])")

FORWARD_WINDOW = 60   # '인증번호' 뒤로 이만큼 안에서 코드를 찾는다
BACKWARD_WINDOW = 30  # 못 찾으면 앞쪽도 이만큼 본다


def extract_auth_code(body, keyword=KEYWORD):
    """본문에서 인증번호로 보이는 값을 뽑는다. 없으면 None.

    '인증번호' 라는 낱말 주변만 본다. 문자 전체에서 4~8자리 숫자를 찾으면
    전화번호나 금액을 잘못 집기 때문이다.
    """
    if not body or keyword not in body:
        return None

    for m in re.finditer(re.escape(keyword), body):
        after = body[m.end():m.end() + FORWARD_WINDOW]

        # 1) 인증번호 [123456] / (123456)
        b = BRACKET_CODE_RE.search(after)
        if b:
            return b.group(1)

        # 2) 인증번호는 123456 입니다 / 인증번호 : 123456
        p = PLAIN_CODE_RE.search(after)
        if p:
            return p.group(1)

        # 3) 코드가 낱말 앞에 오는 경우: 123456 이 인증번호입니다
        before = body[max(0, m.start() - BACKWARD_WINDOW):m.start()]
        cands = BRACKET_CODE_RE.findall(before) or PLAIN_CODE_RE.findall(before)
        if cands:
            return cands[-1]

    return None


# ---------------------------------------------------------------------------
# 대화 목록 항목 해석
# ---------------------------------------------------------------------------
def parse_conversation_item(text):
    """대화 목록 항목 하나를 (상대, 본문) 으로 나눈다.

    실제로 들어오는 형태는 두 가지다.
        읽음   : '114와의 대화 메시지 미리 보기 [SKT]...'
        안읽음 : '080-258-0002와의 대화. 읽지 않은 메시지. 메시지 미리 보기. [Web발신]...'
    앞부분 문구가 조금씩 다르므로 '메시지 미리 보기' 를 기준으로 자른다.
    """
    if not text:
        return None, ""

    idx = -1
    marker = ""
    for mk in PREVIEW_MARKERS:
        i = text.find(mk)
        if i >= 0:
            idx, marker = i, mk
            break
    if idx < 0:
        return None, ""

    m = NAME_SUFFIX_RE.match(text)
    name = m.group(1).strip() if m else text[:idx].strip()

    rest = text[idx + len(marker):]
    body = re.sub(r"^\s*\.?\s*", "", rest)   # 본문 앞의 '. ' 또는 ' ' 를 걷어낸다
    return name, body.strip()


def mask(text, keep=12):
    """점검용 출력에서 남의 문자 내용이 통째로 찍히지 않게 가린다."""
    text = (text or "").replace("\r", " ").replace("\n", " ")
    if len(text) <= keep:
        return text
    return f"{text[:keep]}... ({len(text)}자)"


# ---------------------------------------------------------------------------
# 클립보드
# ---------------------------------------------------------------------------
def set_clipboard_text(text):
    """다른 프로그램이 클립보드를 쥐고 있을 수 있어 몇 번 재시도한다."""
    for _ in range(5):
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


# ---------------------------------------------------------------------------
# Phone Link 창 붙잡기
# ---------------------------------------------------------------------------
def find_phone_link_hwnd():
    found = []

    def cb(h, _):
        try:
            if not win32gui.IsWindow(h):
                return True
            if win32gui.GetClassName(h) != PHONE_LINK_CLASS:
                return True
            if win32gui.GetWindowText(h) in PHONE_LINK_TITLES:
                found.append(h)
        except Exception:
            pass
        return True

    win32gui.EnumWindows(cb, None)
    return found[0] if found else None


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def launch_phone_link():
    """Phone Link 를 띄운다.

    관리자 권한 프로세스에서 shell:AppsFolder 를 직접 실행하면 스토어 앱은
    조용히 실패한다. explorer.exe 를 거치면 로그온 사용자 권한으로 실행되어 열린다.
    """
    log("Phone Link 창이 없습니다. 실행합니다.")
    try:
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{PHONE_LINK_APPID}"],
                         shell=False)
    except Exception as e:
        log(f"실행 실패: {e}")
        return None

    waited = 0.0
    while waited < LAUNCH_WAIT_SECONDS:
        h = find_phone_link_hwnd()
        if h:
            log(f"Phone Link 창 확인 (hwnd={h})")
            time.sleep(3)   # 첫 그리기와 동기화가 끝나기를 잠깐 기다린다
            return h
        time.sleep(1)
        waited += 1
    log(f"{LAUNCH_WAIT_SECONDS}초 안에 Phone Link 창이 뜨지 않았습니다.")
    return None


class PhoneLinkReader:
    """Phone Link 창에서 대화 목록을 읽는다. 창이 닫히면 다시 붙는다."""

    def __init__(self):
        self.hwnd = None
        self.win = None
        self._list = None

    def attach(self, launch=True):
        h = find_phone_link_hwnd()
        if h is None and launch:
            h = launch_phone_link()
        if h is None:
            return False
        if h != self.hwnd or self.win is None:
            self.hwnd = h
            self.win = Application(backend="uia").connect(handle=h).window(handle=h)
            self._list = None
            self.ensure_messages_tab()
        return True

    def ensure_messages_tab(self):
        """'메시지' 탭이 선택되어 있지 않으면 선택한다.

        마우스를 움직이지 않도록 선택 패턴을 먼저 쓰고, 안 되면 클릭한다.
        """
        try:
            tab = self.win.child_window(auto_id=AID_CHAT_TAB,
                                        control_type="TabItem").wrapper_object()
        except Exception:
            return False
        try:
            if tab.is_selected():
                return True
        except Exception:
            pass
        for attempt in ("pattern", "click"):
            try:
                if attempt == "pattern":
                    tab.iface_selection_item.Select()
                else:
                    tab.click_input()
                time.sleep(1.5)
                return True
            except Exception:
                continue
        return False

    def connection_problem(self):
        """휴대폰 연결에 문제가 있으면 그 안내 문구를, 없으면 None 을 돌려준다.

        상단 표시가 '연결됨' 이어도 아래에 오류 안내가 떠 있을 수 있으므로
        그 문구를 직접 찾는다. 연결이 끊긴 동안 온 문자는 영영 들어오지 않는다.
        """
        try:
            texts = [t.window_text() for t in self.win.descendants(control_type="Text")]
        except Exception:
            return None
        for s in texts:
            if any(m in s for m in CONNECTION_ERROR_MARKERS):
                return s.strip()
        return None

    def _conv_list(self):
        """대화 목록 요소를 돌려준다. 읽을 때마다 다시 찾는다.

        캐시하면 안 된다. Phone Link 가 새 문자를 받으며 목록 컨트롤을 다시
        만들면, 캐시된 낡은 요소는 예외도 없이 '옛날 항목'만 돌려준다.
        그러면 화면에 문자가 떠 있는데도 폴링 루프는 끝까지 못 알아챈다.
        한 번 찾는 데 0.05초라 매번 찾아도 부담이 없다.
        """
        try:
            self._list = self.win.child_window(
                auto_id=AID_CONV_LIST, control_type="List").wrapper_object()
        except Exception:
            if self._list is None:
                raise
        return self._list

    def read_conversations(self):
        """[(상대, 본문)] 을 돌려준다. 창을 못 읽으면 None (빈 목록과 구분하기 위해)."""
        try:
            items = self._conv_list().descendants(control_type="ListItem")
        except Exception:
            # 창이 닫혔거나 탭이 바뀌었다. 다시 붙어서 한 번 더 시도한다.
            self.win = None
            self._list = None
            if not self.attach(launch=False):
                return None
            try:
                items = self._conv_list().descendants(control_type="ListItem")
            except Exception:
                return None

        out = []
        for it in items:
            try:
                text = it.window_text()
            except Exception:
                continue
            name, body = parse_conversation_item(text)
            if body:
                out.append((name, body))
        return out


# ---------------------------------------------------------------------------
# 인증번호를 찾았을 때 할 일
# ---------------------------------------------------------------------------
def on_code_found(code, sender, body):
    """인증번호를 찾았을 때 실행된다.

    지금은 클립보드에 넣는 것까지만 한다.
    이후 동작(예: 특정 화면에 자동 입력)을 붙일 자리다.
    """
    if set_clipboard_text(code):
        log(f"  >> 인증번호 {code} - 클립보드에 복사했습니다. (발신: {sender})", secret=True)
        log(f"  >> 인증번호를 클립보드에 복사했습니다. (발신: {sender})")
    else:
        log(f"  >> 클립보드 복사에 실패했습니다. 인증번호: {code}", secret=True)
        log("  >> 클립보드 복사에 실패했습니다.")


def handle_new_messages(new_items):
    """새로 도착한 문자들 중 인증번호가 든 것을 처리한다."""
    hits = 0
    for name, body in new_items:
        if KEYWORD not in body:
            continue
        code = extract_auth_code(body)
        if code is None:
            log(f"  '{KEYWORD}' 문자를 받았지만 번호를 못 찾았습니다. "
                f"(발신: {name}, 본문 {len(body)}자)")
            continue
        on_code_found(code, name, body)
        hits += 1
    return hits


# ---------------------------------------------------------------------------
# 실행 모드
# ---------------------------------------------------------------------------
def cmd_check():
    log("=== 실행 환경 점검 ===")
    log(f"  실행 형태: {'exe(패키징됨)' if getattr(sys, 'frozen', False) else '파이썬 스크립트'}")
    log(f"  기준 폴더: {BASE_DIR}")
    log(f"  관리자 권한: {'예' if is_admin() else '아니오'}")

    h = find_phone_link_hwnd()
    if h:
        log(f"  Phone Link 창: 열려 있음 (hwnd={h}, 제목='{win32gui.GetWindowText(h)}')")
    else:
        log("  Phone Link 창: 닫혀 있음 (감시 시작 시 자동으로 띄웁니다)")

    reader = PhoneLinkReader()
    if not reader.attach():
        log("  결과: Phone Link 창을 확보하지 못했습니다.")
        return 1

    try:
        dev = reader.win.child_window(auto_id="DeviceSelectorComboBox").window_text()
        log(f"  연결된 기기: {dev}")
    except Exception:
        log("  연결된 기기: 확인 못 함")

    t0 = time.time()
    convs = reader.read_conversations()
    if convs is None:
        log("  대화 목록: 읽기 실패")
        return 1
    log(f"  대화 목록: {len(convs)}건 읽음 ({time.time() - t0:.2f}초)")
    log(f"  '{KEYWORD}' 포함: {sum(1 for _, b in convs if KEYWORD in b)}건")

    problem = reader.connection_problem()
    if problem:
        log(f"  휴대폰 연결: 문제 있음 -> {problem}")
        log("  결과: 연결을 고쳐야 새 문자가 들어옵니다.")
        return 1
    log("  휴대폰 연결: 이상 없음")
    log("  결과: 정상")
    return 0


def cmd_list():
    reader = PhoneLinkReader()
    if not reader.attach():
        log("Phone Link 창을 확보하지 못했습니다.")
        return 1
    convs = reader.read_conversations()
    if convs is None:
        log("대화 목록을 읽지 못했습니다.")
        return 1
    log(f"대화 {len(convs)}건 (내용은 가려서 표시합니다)")
    for name, body in convs:
        tag = f" <-- '{KEYWORD}' 있음" if KEYWORD in body else ""
        log(f"  {name}: {mask(body)}{tag}")
    return 0


def cmd_once():
    reader = PhoneLinkReader()
    if not reader.attach():
        log("Phone Link 창을 확보하지 못했습니다.")
        return 1
    convs = reader.read_conversations()
    if convs is None:
        log("대화 목록을 읽지 못했습니다.")
        return 1
    log(f"대화 {len(convs)}건을 검사합니다.")
    hits = handle_new_messages(convs)
    log(f"인증번호 {hits}건을 찾았습니다.")
    return 0


def cmd_watch(seconds=None):
    reader = PhoneLinkReader()
    if not reader.attach():
        log("Phone Link 창을 확보하지 못했습니다. 종료합니다.")
        return 1

    seen = reader.read_conversations()
    if seen is None:
        log("대화 목록을 읽지 못했습니다. 종료합니다.")
        return 1
    seen = set(seen)
    log(f"감시를 시작합니다. 현재 대화 {len(seen)}건은 '이미 본 것'으로 둡니다.")
    log(f"지금부터 새로 도착하는 문자에서 '{KEYWORD}' 를 찾습니다. (Ctrl+C 로 종료)")

    started = time.time()
    misses = 0
    try:
        while True:
            if seconds is not None and time.time() - started >= seconds:
                log(f"{seconds}초가 지나 종료합니다.")
                break

            time.sleep(POLL_SECONDS)
            convs = reader.read_conversations()

            if convs is None:
                misses += 1
                if misses == 1:
                    log("Phone Link 창을 놓쳤습니다. 다시 붙습니다.")
                time.sleep(RECONNECT_WAIT_SECONDS)
                reader.attach()
                continue
            if misses:
                log("Phone Link 창에 다시 붙었습니다.")
                misses = 0

            new_items = [c for c in convs if c not in seen]
            if new_items:
                for name, body in new_items:
                    log(f"새 문자: {name} - {mask(body)}")
                handle_new_messages(new_items)
                seen.update(new_items)
    except KeyboardInterrupt:
        log("사용자가 종료했습니다.")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="휴대폰 문자에서 인증번호를 뽑아 클립보드에 복사합니다.")
    ap.add_argument("--check", action="store_true", help="실행 환경 자체 점검")
    ap.add_argument("--list", action="store_true", help="현재 대화 목록 표시 (점검용)")
    ap.add_argument("--once", action="store_true", help="지금 목록을 한 번만 검사")
    ap.add_argument("--seconds", type=int, default=None, help="이 시간(초) 동안만 감시")
    args = ap.parse_args()

    if args.check:
        return cmd_check()
    if args.list:
        return cmd_list()
    if args.once:
        return cmd_once()
    return cmd_watch(seconds=args.seconds)


if __name__ == "__main__":
    sys.exit(main())
