# -*- coding: utf-8 -*-
"""perform_login.login_flow 의 두 갈래 (PR #2): 재시도 때 숨은 로그인 창은 로그인 창이 아니다, 메인 창이 먼저 뜨면 성공.
진짜 창·키 입력 없이 가짜로."""
import contextlib
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

print("=== 함께 실행: 칸에 치기 전 포커스가 ERPia 에 있는지 (검토 10-20) ===")


class Edit:
    def __init__(self, top, typed):
        self.top, self.typed = top, typed

    def rectangle(self):
        return types.SimpleNamespace(top=self.top)

    def click_input(self):
        pass

    def type_keys(self, keys, **k):
        self.typed.append(keys)


def fill(fg_pid, guard):
    """로그인 칸 여섯 개(ERPia pid 7)에 친다. fg_pid: 맨 앞 창의 프로세스. guard: KEYS_GUARD (함께 실행이면 바뀐다)."""
    typed = []
    login = types.SimpleNamespace(handle=1, descendants=lambda control_type=None: [Edit(i, typed) for i in range(6)])
    saved_mods = (pl.win32gui, pl.win32process, pl.ec, pl.time, pl.KEYS_GUARD)
    pl.win32gui = types.SimpleNamespace(GetForegroundWindow=lambda: 9)
    pl.win32process = types.SimpleNamespace(GetWindowThreadProcessId=lambda h: (0, fg_pid if h == 9 else 7))
    pl.ec = types.SimpleNamespace(ensure_foreground=lambda h: None, literal_keys=lambda v: v)
    pl.time = types.SimpleNamespace(sleep=lambda s: None)
    pl.KEYS_GUARD = guard
    try:
        pl.fill_login_fields(login, "code", "id", "pw", lambda m: None)
        return typed, None
    except RuntimeError as e:
        return typed, str(e)
    finally:
        pl.win32gui, pl.win32process, pl.ec, pl.time, pl.KEYS_GUARD = saved_mods


typed, err = fill(8, lambda: contextlib.nullcontext())
check(err is not None and typed == [], f"함께 실행에서 포커스가 다른 프로그램(Edge 등)이면 한 글자도 치지 않고 멈춘다 ({err})")
typed, err = fill(7, lambda: contextlib.nullcontext())
check(err is None and "pw" in typed, "함께 실행에서 포커스가 ERPia 면 그대로 친다")
typed, err = fill(8, contextlib.nullcontext)
check(err is None and "pw" in typed, "평소(함께 실행이 아님)에는 포커스를 따로 보지 않는다 (지금과 같다)")

print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
