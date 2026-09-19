# -*- coding: utf-8 -*-
"""정상매출 대기 팝업 처리 시험. 가짜 프로그램(fake_popup_app.py)으로 ERPia 없이 돈다.

ERPia 는 건드리지 않는다 (프로세스 번호로 가짜 프로그램 창만 대상).
"""
import io
import os
import subprocess
import sys
import threading
import time

sys.path.insert(0, r"D:\AX\RPA")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from pywinauto import Application  # noqa: E402
import run_routine as rr  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PY = r"D:\AX\RPA\.venv\Scripts\python.exe"
fails = []


def check(cond, what):
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        fails.append(what)


class Fake:
    def __init__(self, scenario, linger):
        self.p = subprocess.Popen([PY, os.path.join(HERE, "fake_popup_app.py"), scenario, str(linger)],
                                  stdout=subprocess.PIPE, text=True, encoding="utf-8")
        self.hwnd = int(self.p.stdout.readline().strip())
        self.lines = []
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.p.stdout:
            self.lines.append(line.strip())

    def close(self):
        try:
            self.p.wait(timeout=40)
        except subprocess.TimeoutExpired:
            self.p.kill()
        time.sleep(0.3)
        return self.lines


def run_wait(scenario, linger, max_wait=60):
    f = Fake(scenario, linger)
    app = Application(backend="uia").connect(handle=f.hwnd)
    base = rr.visible_child_windows(f.hwnd)
    t0 = time.time()
    res = rr.wait_async_then_confirm(app, f.hwnd, base, poll=0.5, max_wait=max_wait)
    el = time.time() - t0
    return res, el, f.close()


print("=== 1. 개체 참조 오류 -> 확인 -> 정상매출처리 실패 -> 멈춤 (실제로 겪은 순서) ===")
res, el, out = run_wait("error,fail", 3)
print("   가짜 프로그램:", out)
check(res == "sales_failed", f"결과 = {res!r} ({el:.1f}초)")
check("error rc=1" in out, "오류 팝업은 '확인'으로 닫힘")
check("fail rc=1" in out, "실패 팝업도 닫힘")

print("\n=== 2. 개체 참조 오류만 -> 확인 누르고 계속 기다림 ('끝났다'고 착각하지 않음) ===")
res, el, out = run_wait("error", 25)
print("   가짜 프로그램:", out)
check("error rc=1" in out, "오류 팝업은 '확인'으로 닫힘")
check(res == "no_popup", f"결과 = {res!r} (clicked 이면 안 됨)")
check(el >= rr.ASYNC_IDLE_SECONDS, f"닫은 뒤에도 조용한 시간({rr.ASYNC_IDLE_SECONDS}초)만큼 더 지켜봄: {el:.1f}초")

print("\n=== 3. 정상매출처리 실패만 (별도 창) -> 멈춤 ===")
res, el, out = run_wait("fail", 3)
check(res == "sales_failed" and "fail rc=1" in out, f"결과 = {res!r}, {out}")

print("\n=== 4. 예/아니요 질문 (별도 창) -> 아니요 ===")
res, el, out = run_wait("yesno", 25)
check("yesno rc=7" in out, f"'아니요'가 눌림: {out}")
check(res == "no_popup", f"결과 = {res!r}")

print("\n=== 5. 메인 창 안 오류 문구(오버레이) -> 끝났다고 보지 않음 ===")
res, el, out = run_wait("overlay", 25)
check(res == "no_popup", f"결과 = {res!r} (clicked 이면 안 됨, {el:.1f}초)")

print("\n=== 6. 가져오기 단계 팝업 처리도 그대로 ===")
f = Fake("notice", 3)
time.sleep(2.5)
tried = {}
closed = 0
for _ in range(10):
    closed += rr.handle_import_popups(rr.win32process.GetWindowThreadProcessId(f.hwnd)[1], f.hwnd, tried)
    if closed:
        break
    time.sleep(0.5)
out = f.close()
check(closed == 1 and "notice rc=1" in out, f"필독 안내 닫음: closed={closed}, {out}")

print("\n=== 7. 문구 판정 ===")
check(rr.match_error_popup("개체 참조가 개체의 인스턴스로 설정되지 않았습니다.") is not None, "개체 참조 문구 = 오류")
check(rr.match_sales_failure("개체 참조가 개체의 인스턴스로 설정되지 않았습니다.") is None, "개체 참조 문구는 실패로 보지 않음")
check(rr.match_sales_failure("정상매출처리 실패") is not None, "정상매출처리 실패 = 실패")
check(rr.match_error_popup("정상매출처리 실패") is None, "실패 문구는 오류로 보지 않음")
check(rr.match_sales_failure("") is None and rr.match_error_popup(None) is None, "빈 문구는 둘 다 아님")

print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
