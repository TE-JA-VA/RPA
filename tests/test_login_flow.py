# -*- coding: utf-8 -*-
"""perform_login.login_flow 의 두 갈래 (PR #2): 재시도 때 숨은 로그인 창은 로그인 창이 아니다, 메인 창이 먼저 뜨면 성공.
진짜 창·키 입력 없이 가짜로."""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import perform_login as pl  # noqa: E402

fails = []


def check(cond, what):
    print(("PASS  " if cond else "FAIL  ") + what)
    if not cond:
        fails.append(what)


class Win:
    def __init__(self, handle):
        self.handle = handle


def run(windows, visible, popup=None, popup_text="", pids=None):
    """windows: find_login_window 가 차례로 돌려줄 창 목록. visible: {handle: 보이나}. pids: {handle: pid}."""
    calls = {"click": 0}
    seq = list(windows)
    pids = pids or {}
    saved = {n: getattr(pl, n) for n in ("find_login_window", "fill_login_fields", "click_login_button", "wait_for_popup",
                                          "collect_text", "write_error_log")}
    saved_mods = (pl.win32gui, pl.win32process, pl.ec, pl.time)
    pl.find_login_window = lambda: seq.pop(0) if seq else None
    pl.fill_login_fields = lambda *a, **k: None
    pl.click_login_button = lambda *a, **k: calls.__setitem__("click", calls["click"] + 1)
    pl.wait_for_popup = lambda w, *a, **k: (popup, [])
    pl.collect_text = lambda w: popup_text
    pl.write_error_log = lambda text: "err.txt"
    pl.win32gui = types.SimpleNamespace(IsWindowVisible=lambda h: visible.get(h, False), IsWindow=lambda h: True)
    pl.win32process = types.SimpleNamespace(GetWindowThreadProcessId=lambda h: (0, pids.get(h, 1)))
    pl.ec = types.SimpleNamespace(ensure_foreground=lambda h: None)
    pl.time = types.SimpleNamespace(sleep=lambda s: None)
    try:
        return pl.login_flow("code", "id", "pw"), calls
    finally:
        for n, v in saved.items():
            setattr(pl, n, v)
        pl.win32gui, pl.win32process, pl.ec, pl.time = saved_mods


print("=== 재시도 때 숨은 로그인 창 ===")
r, calls = run([Win(1), Win(2)], {1: True, 2: False})
check(r["status"] == "success" and calls["click"] == 0, f"숨은 잔재 창은 로그인 창이 아니다 - 누르지 않고 성공 ({r}, {calls})")
r, calls = run([Win(1), Win(1)], {1: True}, popup=Win(9), popup_text="비밀번호가 일치하지 않습니다", pids={1: 7, 9: 7})
check(r["status"] == "popup_error" and calls["click"] == 1, f"보이는 로그인 창은 누르고, 모르는 팝업이면 멈춘다 ({r['status']})")

print("=== 메인 창이 먼저 뜨면 ===")
r, _ = run([Win(1), Win(1)], {1: True, 5: True}, popup=Win(5), popup_text="Accordion Menu | lcg_sales", pids={1: 7, 5: 7})
check(r["status"] == "success", f"같은 ERPia 의 보이는 메인 창 → 성공 ({r['status']})")
r, _ = run([Win(1), Win(1)], {1: True, 5: True}, popup=Win(5), popup_text="Accordion Menu | lcg_sales", pids={1: 7, 5: 8})
check(r["status"] != "success", f"다른 ERPia 의 메인 창은 성공이 아니다 ({r['status']})")
r, _ = run([Win(1), Win(1)], {1: True, 5: False}, popup=Win(5), popup_text="Accordion Menu | lcg_sales", pids={1: 7, 5: 7})
check(r["status"] != "success", f"숨은 메인 창은 성공이 아니다 ({r['status']})")

print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
