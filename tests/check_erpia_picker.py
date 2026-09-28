"""ERPia 위치 고르는 창(rpa_status.pick_erpia_exe) 시험 - 진짜 창을 띄워 pywinauto 로 파일 이름을 넣는다.

화면에 파일 열기 창이 몇 번 잠깐 뜬다 (각각 몇 초). 가짜 ERPiaMain.exe(빈 파일)만 쓰고 설정 파일은 건드리지 않는다.

    .venv\\Scripts\\python.exe tests\\check_erpia_picker.py
"""
import os
import subprocess
import sys
import tempfile
import time

from pywinauto import Desktop

sys.stdout.reconfigure(encoding="utf-8")
fails = []


def check(name, cond, detail=""):
    print(f"  [{'통과' if cond else '실패'}] {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


tmp = tempfile.mkdtemp(prefix="rpa_picker_")
good = os.path.join(tmp, "OneZeroSoft", "ERPiaNet", "ERPiaMain.exe")
os.makedirs(os.path.dirname(good))
open(good, "wb").close()
wrong = os.path.join(tmp, "ERPia_Login.exe")
open(wrong, "wb").close()

CODE = ("import sys; sys.path.insert(0, r'D:\\AX\\RPA'); import rpa_status as st; "
        "r = st.pick_erpia_exe(); print('RESULT=' + repr(r), flush=True)")


def start_picker():
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.Popen([sys.executable, "-c", CODE], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)


def find_dialog(title_part, timeout=15):
    """#32770 파일 열기 창을 제목으로 찾는다 (사용자가 연 다른 창은 제목이 달라 안 걸린다)."""
    end = time.time() + timeout
    while time.time() < end:
        for w in Desktop(backend="win32").windows(class_name="#32770"):
            if title_part in w.window_text():
                return Desktop(backend="win32").window(handle=w.handle)
        time.sleep(0.2)
    return None


def cleanup():
    """시험이 도중에 죽어도 창이 화면에 남지 않게 - 이 시험이 띄운 창만 취소한다."""
    for w in Desktop(backend="win32").windows(class_name="#32770"):
        if "ERPia 프로그램" in w.window_text() or "가 아닙니다" in w.window_text():
            try:
                Desktop(backend="win32").window(handle=w.handle).child_window(control_id=2, class_name="Button").click()
            except Exception:
                pass


def submit(dlg, path):
    """파일 이름 칸(ID 1148) 에 전체 경로를 붙여넣고 Enter. 이 창은 set_edit_text 가 안 먹는다
    (run_routine.type_path_into_dialog 와 같은 방법). 사용자 클립보드는 되돌려 놓는다."""
    import win32clipboard
    import win32con
    from pywinauto.keyboard import send_keys

    def clip(text=None):
        win32clipboard.OpenClipboard()
        try:
            if text is None:
                return (win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT) else None)
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()

    saved = clip()
    try:
        clip(path)
        dlg.set_focus()
        edit = dlg.child_window(control_id=1148, class_name="ComboBoxEx32").child_window(class_name="Edit")
        edit.click_input()
        time.sleep(0.2)
        send_keys("{END}+{HOME}{BACKSPACE}^v")
        time.sleep(0.2)
        send_keys("{ENTER}")
    finally:
        time.sleep(0.3)
        if saved is not None:
            clip(saved)


def same(res, path):
    """창이 돌려준 경로(긴 이름)와 임시 폴더 경로(8.3 짧은 이름일 수 있다)가 같은 파일인가."""
    import ast
    try:
        got = ast.literal_eval(res)
        return isinstance(got, str) and os.path.samefile(got, path)
    except Exception:
        return False


def result_of(proc):
    out, _ = proc.communicate(timeout=20)
    text = out.decode("utf-8", "replace")
    line = next((l for l in text.splitlines() if l.startswith("RESULT=")), "")
    return line[len("RESULT="):], text


import atexit  # noqa: E402
atexit.register(cleanup)

print("=== 1. 맞는 파일을 고르면 그 경로 ===")
p = start_picker()
dlg = find_dialog("ERPia 프로그램")
check("고르는 창이 뜬다 (제목에 ERPia 프로그램)", dlg is not None)
if dlg:
    submit(dlg, good)
res, raw = result_of(p)
check("고른 ERPiaMain.exe 경로를 돌려준다", same(res, good), raw[-300:])

print("=== 2. 다른 이름을 고르면 다시 묻고, 그다음 맞는 파일 ===")
p = start_picker()
dlg = find_dialog("ERPia 프로그램")
if dlg:
    submit(dlg, wrong)
again = find_dialog("가 아닙니다")
check("ERPiaMain.exe 가 아니면 창을 다시 띄운다 (제목에 이유)", again is not None)
if again:
    submit(again, good)
res, raw = result_of(p)
check("다시 고른 맞는 파일을 돌려준다", same(res, good), raw[-300:])

print("=== 3. 취소하면 None ===")
p = start_picker()
dlg = find_dialog("ERPia 프로그램")
if dlg:
    dlg.child_window(control_id=2, class_name="Button").click()     # 취소
res, raw = result_of(p)
check("취소하면 None", res == "None", raw[-300:])

print()
print(f"실패: {'없음' if not fails else fails}")
sys.exit(1 if fails else 0)
