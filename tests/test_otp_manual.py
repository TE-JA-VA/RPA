"""재생기의 사람 인증 (옵저버 단독 설계 4.4) - 휴대폰 중계 없이 사람이 인증번호를 넣고 [확인]까지 누르기를 기다린다.
가짜 사이트는 tests/fake_otp_site (test_otp_replay 와 같다). headless Edge - 창은 뜨지 않는다.
    .venv\\Scripts\\python.exe tests\\test_otp_manual.py
"""
import os
import sys
import tempfile
import threading
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fake_otp_site as site  # noqa: E402
import web_replay as rec  # noqa: E402

srv, BASE = site.start()
SENT = site.SENT
OUT = tempfile.mkdtemp(prefix="otp_manual_")
fails = []


def check(name, ok, detail=""):
    print(("통과 " if ok else "실패 ") + name + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


r = rec.record(BASE + "/verify", os.path.join(OUT, "rec.json"), headless=True, human=site.human)
check("기록: 인증번호 받기 → otp → 확인", [s["kind"] for s in r["steps"]] == ["click", "otp", "click"], [s["kind"] for s in r["steps"]])
check("상수: 사람 대기 5분·실패 글", rec.OTP_MANUAL_WAIT == 300 and "5분" in rec.OTP_MANUAL_TIMEOUT)


def replay(label, on_wait, cancel=None, wait=None):
    """on_wait(page) 는 waiting=True 콜백에서 한다. calls 에 콜백의 waiting 값이 차례로 쌓인다."""
    lines, calls, ctx = [], [], {}
    orig = rec.Replayer.__init__

    def init(self, *a, **kw):
        orig(self, *a, **kw)
        self.cancel = cancel
        ctx["rp"] = self

        def manual(page, waiting):
            calls.append(waiting)
            if waiting:
                on_wait(page)
        self.otp_manual = manual
    rec.Replayer.__init__ = init
    saved = rec.OTP_MANUAL_WAIT
    if wait is not None:
        rec.OTP_MANUAL_WAIT = wait
    try:
        t = time.time()
        ok, rp = rec.replay(r, {"ID": "", "PW": ""}, os.path.join(OUT, label), "000", log=lines.append, step_timeout=5, step_tries=1)
        return ok, rp, lines, calls, time.time() - t
    finally:
        rec.Replayer.__init__ = orig
        rec.OTP_MANUAL_WAIT = saved


def person_types(page):
    page.fill("#otp", SENT[-1])
    page.get_by_role("button", name="확인").click()


n0 = len(SENT)
ok, rp, lines, calls, sec = replay("pass", person_types)
check("manual_otp_pass: 사람이 넣고 [확인] → 재생 성공", ok and len(rp.results) == 3, rp.results)
check("manual_otp_pass: 인증번호·[확인] 단계는 '사람이 입력'", [x[2] for x in rp.results[1:]] == ["사람이 입력", "사람이 입력"], rp.results)
check("manual_otp_pass: 콜백 순서 [True, False]", calls == [True, False], calls)
check("manual_otp_pass: 문자는 기록대로 한 번만 요청", len(SENT) - n0 == 1, len(SENT) - n0)

n0 = len(SENT)
ok, rp, lines, calls, sec = replay("timeout", lambda page: None, wait=2)
check("manual_otp_timeout: 기다려도 안 넘어가면 그 단계 실패 (다시 보내지 않음)", not ok and rp.results[-1][1:] == ("fail", rec.OTP_MANUAL_TIMEOUT)
      and len(SENT) - n0 == 1 and 1.5 < sec < 15, (rp.results[-1:], len(SENT) - n0, sec))
check("manual_otp_timeout: 콜백은 대기 끝에도 waiting=False", calls == [True, False], calls)

ev = threading.Event()
ok, rp, lines, calls, sec = replay("cancel", lambda page: threading.Timer(0.3, ev.set).start(), cancel=ev)
check("manual_otp_cancel: 대기 중 [중지] → 2초 안에 '사용자 중단' (Review Focus 4)", not ok and rp.results[-1][2] == rec.STOPPED and sec < 8,
      (rp.results[-1:], sec))

srv.shutdown()
print("실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
