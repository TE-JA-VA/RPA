"""ERPia 자동화 공통 유틸리티.
PID/창은 매번 바뀔 수 있으므로 항상 새로 찾고, 클릭/키 입력 전에는
반드시 ERPia 창을 foreground(활성)로 전환한 뒤 진행한다.
"""
import ctypes
import time
import win32api
import win32com.client
import win32con
import win32gui
import win32process


def literal_keys(text):
    """type_keys 에 글자 그대로 넘길 값. pywinauto 는 + ^ % ~ ( ) { } 를 조합키·묶음으로 읽으므로 {} 로 감싼다.
    (안 감싸면 'a(b)c' 가 'abc' 로 들어간다) 특수문자가 없는 값은 그대로다."""
    return "".join("{" + c + "}" if c in "+^%~(){}" else c for c in str(text))


def screen_locked():
    """윈도우 화면이 잠겼는가. 잠기면 click_input 이 예외 없이 헛돌아 엉뚱한 실패(화면 이동 실패 등)가 난다.
    입력 데스크톱이 안 열리거나, 맨 앞 창의 주인이 잠금 화면 앱(LockApp.exe)이면 잠김 - 창 제목은 언어마다 달라
    프로세스 이름으로 본다 (LockApp.exe 는 평소에도 떠 있으므로 '맨 앞인가' 를 본다). 판정할 수 없으면 False."""
    try:
        handle = ctypes.windll.user32.OpenInputDesktop(0, False, 0x0100)   # DESKTOP_SWITCHDESKTOP
        if not handle:
            return True
        ctypes.windll.user32.CloseDesktop(handle)
        fg = win32gui.GetForegroundWindow()
        if not fg:
            return False
        return (get_process_name(win32process.GetWindowThreadProcessId(fg)[1]) or "").lower() == "lockapp.exe"
    except Exception:
        return False


def find_erpia_pid(process_name="ERPiaMain.exe"):
    wmi = win32com.client.GetObject("winmgmts:")
    procs = wmi.ExecQuery(f"SELECT ProcessId FROM Win32_Process WHERE Name='{process_name}'")
    for p in procs:
        return int(p.ProcessId)
    raise RuntimeError(f"{process_name} 프로세스를 찾지 못했습니다.")


def erpia_pids(process_name="ERPiaMain.exe"):
    """떠 있는 ERPia 프로세스 번호 목록 (find_erpia_pid 는 그중 첫 번째만 본다)."""
    wmi = win32com.client.GetObject("winmgmts:")
    return [int(p.ProcessId) for p in wmi.ExecQuery(f"SELECT ProcessId FROM Win32_Process WHERE Name='{process_name}'")]


def get_process_name(pid):
    wmi = win32com.client.GetObject("winmgmts:")
    procs = wmi.ExecQuery(f"SELECT Name FROM Win32_Process WHERE ProcessId={pid}")
    for p in procs:
        return p.Name
    return None


def find_main_hwnd(pid):
    """텍스트가 있는 최상위 창 중 '보이는(visible)' 창만 대상으로 가장 넓은 것을 고른다.
    로그인 창처럼 닫힌 뒤에도 숨겨진 채로 남아있는(visible=False) 창이 폭이 더 넓어서
    잘못 선택되는 일이 없도록 visible 여부를 우선 필터링한다."""
    hwnds = []

    def handler(hwnd, results):
        _, p = win32process.GetWindowThreadProcessId(hwnd)
        if p == pid and win32gui.GetWindowText(hwnd):
            results.append(hwnd)

    win32gui.EnumWindows(handler, hwnds)
    if not hwnds:
        raise RuntimeError("텍스트가 있는 최상위 창을 찾지 못했습니다.")

    visible_hwnds = [h for h in hwnds if win32gui.IsWindowVisible(h)]
    candidates = visible_hwnds if visible_hwnds else hwnds

    best = max(candidates, key=lambda h: (win32gui.GetWindowRect(h)[2] - win32gui.GetWindowRect(h)[0]))
    if win32gui.IsIconic(best):
        win32gui.ShowWindow(best, win32con.SW_RESTORE)
    return best


def wait_for_main_hwnd(pid, timeout=60, interval=1.0):
    """메인 창이 나타날 때까지 기다렸다가 hwnd를 반환한다.

    로그인 창이 닫힌 직후에는 메인 창이 아직 만들어지지 않아
    find_main_hwnd가 곧바로 실패할 수 있으므로, 일정 시간 재시도한다.
    """
    waited = 0.0
    last_err = None
    while waited < timeout:
        try:
            return find_main_hwnd(pid)
        except RuntimeError as e:
            last_err = e
            time.sleep(interval)
            waited += interval
    raise RuntimeError(f"{timeout}초 안에 메인 창을 찾지 못했습니다. ({last_err})")


def is_foreground(hwnd):
    return win32gui.GetForegroundWindow() == hwnd


def ensure_foreground(hwnd, retries=5, delay=0.3):
    """대상 창을 foreground로 전환한다. 창 크기/위치는 절대 건드리지 않으며,
    최소화(minimized)된 경우에만 복원(restore)한다."""
    for _ in range(retries):
        if is_foreground(hwnd):
            return True

        fg_hwnd = win32gui.GetForegroundWindow()
        fg_thread = win32process.GetWindowThreadProcessId(fg_hwnd)[0] if fg_hwnd else 0
        cur_thread = win32api.GetCurrentThreadId()

        try:
            if fg_thread and fg_thread != cur_thread:
                win32process.AttachThreadInput(cur_thread, fg_thread, True)
            if win32gui.IsIconic(hwnd):
                # 최소화된 경우에만 복원 (크기/위치를 바꾸지 않기 위해 그 외에는 호출하지 않음)
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
        finally:
            if fg_thread and fg_thread != cur_thread:
                try:
                    win32process.AttachThreadInput(cur_thread, fg_thread, False)
                except Exception:
                    pass

        time.sleep(delay)

    return is_foreground(hwnd)


def find_erpia_windows_by_title(title_substr, process_name="ERPiaMain.exe"):
    """ERPiaMain.exe 프로세스가 소유한 최상위 창 중, 제목에 title_substr이
    포함된 모든 창을 pywinauto UIA 래퍼 리스트로 반환한다 (다른 프로세스의
    동명 창과 혼동되지 않도록 항상 프로세스 이름까지 확인한다)."""
    from pywinauto import Desktop

    results = []
    for w in Desktop(backend="uia").windows():
        try:
            title = w.window_text()
        except Exception:
            continue
        if title_substr not in title:
            continue
        try:
            _, pid = win32process.GetWindowThreadProcessId(w.handle)
        except Exception:
            continue
        if get_process_name(pid) == process_name:
            results.append(w)
    return results
