"""ERPia 자동화 공통 유틸리티.
PID/창은 매번 바뀔 수 있으므로 항상 새로 찾고, 클릭/키 입력 전에는
반드시 ERPia 창을 foreground(활성)로 전환한 뒤 진행한다.
"""
import time
import win32api
import win32com.client
import win32con
import win32gui
import win32process


def find_erpia_pid(process_name="ERPiaMain.exe"):
    wmi = win32com.client.GetObject("winmgmts:")
    procs = wmi.ExecQuery(f"SELECT ProcessId FROM Win32_Process WHERE Name='{process_name}'")
    for p in procs:
        return int(p.ProcessId)
    raise RuntimeError(f"{process_name} 프로세스를 찾지 못했습니다.")


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
