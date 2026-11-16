# -*- coding: utf-8 -*-
"""누를 자리를 오토파일럿 자신의 실행 창(콘솔)이 덮은 날 (triif 2026-11-16 17:10 운송장번호 전송 '조회 조건 Sales ▼') -
덮개 검사(_top_window)가 우리 콘솔이면 최소화하고 다시 본다. 다른 프로그램 창은 지금처럼 건드리지 않는다. 창은 뜨지 않는다 (가짜 win32gui).
    .venv\\Scripts\\python.exe tests\\test_own_console_cover.py
"""
import os
import sys
from types import SimpleNamespace

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import wellife  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


CONSOLE, ERPIA, OTHER = 4327846, 1001, 2002


def fake(stack):
    """stack = 그 점의 맨 위부터 창 목록. 최소화된 창은 빠진다."""
    acts, logs, mini = [], [], set()
    top = lambda: next(h for h in stack if h not in mini)      # noqa: E731
    g = SimpleNamespace(WindowFromPoint=lambda pt: top(), GetAncestor=lambda h, flag: h,
                        ShowWindow=lambda h, cmd: (acts.append(("show", h, cmd)), mini.add(h) if cmd == 6 else None))
    return SimpleNamespace(win32gui=g, log=logs.append), acts, logs


keep = wellife._own_console
wellife._own_console = lambda: CONSOLE
try:
    rr, acts, logs = fake([CONSOLE, ERPIA])
    check("우리 콘솔이 덮었으면 최소화하고 그 밑의 ERPia 를 맨 위로 본다",
          wellife._top_window(rr, (10, 10)) == ERPIA and acts == [("show", CONSOLE, 6)], acts)
    check("최소화했다고 로그에 남긴다", logs and "오토파일럿 실행 창" in logs[0], logs)
    rr, acts, logs = fake([OTHER, ERPIA])
    check("다른 프로그램 창은 건드리지 않는다 (지금처럼 덮개로 멈춘다)", wellife._top_window(rr, (10, 10)) == OTHER and not acts, acts)
    rr, acts, logs = fake([ERPIA])
    check("덮은 것이 없으면 아무것도 안 한다", wellife._top_window(rr, (10, 10)) == ERPIA and not acts and not logs)
    wellife._own_console = lambda: None
    rr, acts, logs = fake([CONSOLE, ERPIA])
    check("콘솔이 없는 실행(창 없이 켠 것)이면 그대로", wellife._top_window(rr, (10, 10)) == CONSOLE and not acts)
finally:
    wellife._own_console = keep
check("실제 _own_console 은 예외 없이 창 번호나 None", keep() is None or isinstance(keep(), int))

print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
