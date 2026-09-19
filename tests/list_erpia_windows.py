# -*- coding: utf-8 -*-
"""ERPia 프로세스가 가진 최상위 창을 모두 나열한다 (팝업 확인용). 아무것도 클릭하지 않는다."""
import io
import sys

sys.path.insert(0, r"D:\AX\RPA")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import win32gui  # noqa: E402
import win32process  # noqa: E402
import erpia_common as ec  # noqa: E402

pid = ec.find_erpia_pid()
print("pid =", pid)

rows = []


def handler(h, _):
    try:
        _, p = win32process.GetWindowThreadProcessId(h)
    except Exception:
        return
    if p != pid:
        return
    rows.append((h, win32gui.GetWindowText(h), win32gui.GetClassName(h),
                 bool(win32gui.IsWindowVisible(h)), bool(win32gui.IsWindowEnabled(h)),
                 win32gui.GetWindowRect(h)))


win32gui.EnumWindows(handler, None)
for h, title, cls, vis, en, rect in rows:
    print(f"  hwnd={h:<8} vis={str(vis):<5} enabled={str(en):<5} {rect}  cls={cls}")
    print(f"        제목: {title!r}")

print("\n=== 보이는 창 중 메인이 아닌 것의 내용 ===")
from pywinauto import Desktop  # noqa: E402

main = ec.find_main_hwnd(pid)
print("메인 hwnd =", main)
for h, title, cls, vis, en, rect in rows:
    if not vis or h == main:
        continue
    try:
        w = Desktop(backend="uia").window(handle=h)
        texts = []
        for c in w.descendants():
            t = (c.window_text() or "").strip()
            if t:
                texts.append(f"{c.element_info.control_type}:{t!r}")
        print(f"  [{title!r}] hwnd={h}")
        for t in texts[:30]:
            print("     ", t)
    except Exception as e:
        print(f"  [{title!r}] 읽기 실패: {e}")
