# -*- coding: utf-8 -*-
"""고친 3단계(상단 전체선택 -> '가져오기' 클릭 -> 완료 대기)를 실제 ERPia 로 검증한다.

루틴 본문과 같은 순서로 부르되, 앞뒤 단계는 건드리지 않는다.
"""
import io
import sys
import time

sys.path.insert(0, r"D:\AX\RPA")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import erpia_common as ec  # noqa: E402
from pywinauto import Application  # noqa: E402
import run_routine as rr  # noqa: E402

fails = []


def check(cond, what):
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        fails.append(what)


pid = ec.find_erpia_pid()
hwnd = ec.find_main_hwnd(pid)
app = Application(backend="uia").connect(handle=hwnd)
win = app.window(handle=hwnd)
print(f"pid={pid} hwnd={hwnd}")

tables = rr.get_onscreen_tables(win)
check(len(tables) >= 2, f"주문매핑 화면 그리드 {len(tables)}개")
if len(tables) < 2:
    sys.exit(1)
top_left = min(tables, key=lambda t: (t.rectangle().top, t.rectangle().left))

print("\n=== 좌측 상단 전체선택 ===")
n_top = rr.select_all_and_verify("좌측상단", hwnd, top_left, ["아이디"])
check(n_top is not None and n_top > 0, f"상단 선택 {n_top}행")

print("\n=== run_import_step 실행 ===")
t0 = time.time()
ok = rr.run_import_step(app, pid, hwnd, win)
el = time.time() - t0
check(ok, f"가져오기 완료 반환 (걸린 시간 {el:.0f}초)")
check(el > 5, f"즉시 끝나지 않고 실제로 기다림 ({el:.0f}초)")

win = app.window(handle=hwnd)
imp = rr.find_by_text(win, "가져오기", control_types=("Button",))
sal = rr.find_by_text(win, "매출처리", control_types=("SplitButton",))
check(rr.native_enabled(imp) is True, "끝난 뒤 '가져오기' 다시 활성")
check(rr.native_enabled(sal) is True, "끝난 뒤 '매출처리' 다시 활성")
left = rr.find_popup_windows(pid, hwnd)
check(not left, f"남아 있는 팝업 없음: {left}")

print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
