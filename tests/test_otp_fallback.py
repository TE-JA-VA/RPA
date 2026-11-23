# -*- coding: utf-8 -*-
"""스탠드얼론 ④ Task 4 - 휴대폰이 없거나 답이 없으면 Edge 인증 칸에 사람이 5분 (그 사이트만 실패) (계획 2026-11-23-standalone-4-phone).

tests/test_otp_replay.py 의 가짜 사이트·흉내 중계 방식 그대로 (서버·실제 휴대폰 없이, 기다림 값은 짧게):
  [인증번호 받기] → 사이트가 6자리 번호를 만든다 → '인증번호 6자리' 칸 → [확인] → 맞으면 /done, 틀리면 알림창.
  '사람이 칸에 넣기' 는 가짜 사이트의 화면이 직접 칸을 채워 흉내 낸다 (FILL_MS 뒤 - Playwright 는 다른 스레드에서 못 만진다).
    D:/AX/RPA/.venv/Scripts/python.exe tests/test_otp_fallback.py
"""
import json
import os
import random
import sys
import tempfile
import threading
import time
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import web_replay as rec  # noqa: E402
import otp_relay  # noqa: E402

SENT = []                  # 사이트가 보낸 번호들 (문자)
FILL = [0]                 # >0 이면 [인증번호 받기] 뒤 이만큼(ms) 지나 화면이 칸을 채운다 (사람이 친 것 흉내)
VERIFY = """<!doctype html><meta charset="utf-8"><title>본인 인증</title>
<p>휴대폰으로 받은 인증번호를 넣어 주십시오.</p>
<button type="button" id="send" onclick="fetch('/api/send',{method:'POST'}).then(r=>r.json()).then(j=>{document.getElementById('msg').textContent='보냈습니다';
  if (j.fill > 0) setTimeout(()=>fetch('/api/last').then(r=>r.json()).then(k=>{document.getElementById('otp').value=k.code;}), j.fill);})">인증번호 받기</button>
<input id="otp" placeholder="인증번호 6자리" autocomplete="off">
<button type="button" onclick="fetch('/api/check?c='+document.getElementById('otp').value).then(r=>r.json()).then(j=>{
  if (j.ok) { alert('인증번호가 일치합니다. 다시 로그인 해주세요.'); location.href='/done'; } else { alert('인증번호가 일치하지 않습니다. 다시 받아 주십시오'); document.getElementById('otp').value=''; } })">확인</button>
<p id="msg"></p>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype="text/html; charset=utf-8"):
        b = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        path, _, q = self.path.partition("?")
        if path == "/verify":
            return self._send(VERIFY)
        if path == "/api/check":
            return self._send(json.dumps({"ok": bool(SENT) and q == f"c={SENT[-1]}"}), "application/json")
        if path == "/api/last":
            return self._send(json.dumps({"code": SENT[-1] if SENT else ""}), "application/json")
        self._send(f"<!doctype html><meta charset='utf-8'><title>{path}</title><h1>{path}</h1>")

    def do_POST(self):
        SENT.append(f"{random.randint(0, 999999):06d}")
        self._send(json.dumps({"fill": FILL[0]}), "application/json")


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
OUT = tempfile.mkdtemp(prefix="otp_fallback_")
fails = []


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


class FakePhoneRelay:
    """휴대폰 중계(PhoneRelay) 흉내. how: 'ok' 사이트가 보낸 번호 / 'quiet' 안 옴 / 'denied' open 이 거절 / 'wrong' 늘 틀린 번호."""

    def __init__(self, how):
        self.how, self.opened, self.closed, self.waits = how, 0, 0, 0

    def open(self, tick=None):
        if self.how == "denied":
            raise RuntimeError(otp_relay.DENIED)
        self.opened += 1
        return f"req_{self.opened:016d}"

    def wait(self, req, seconds, tick, field=None):
        self.waits += 1
        if self.how == "ok":
            tick(0.2)
            return SENT[-1]
        if self.how == "wrong":
            tick(0.2)
            return "000000" if SENT[-1] != "000000" else "111111"
        end = time.time() + seconds
        while time.time() < end:
            tick(min(0.2, max(0.01, end - time.time())))
        return None

    def close(self, req):
        self.closed += 1


def human(page):
    page.wait_for_timeout(500)
    page.click("#send")
    page.wait_for_function("document.getElementById('msg').textContent === '보냈습니다'")
    page.click("#otp")
    page.keyboard.type(SENT[-1], delay=20)
    page.get_by_role("button", name="확인").click()
    page.wait_for_url("**/done")


r = rec.record(BASE + "/verify", os.path.join(OUT, "rec.json"), headless=True, human=human)
check("기록: 인증번호 받기 → 인증번호 칸 → 확인", [s["kind"] for s in r["steps"]] == ["click", "otp", "click"] and r["steps"][0].get("otpSend") is True)


def replay(label, relay, wait=2):
    lines = []
    orig = rec.Replayer.__init__

    def init(self, *a, **kw):
        orig(self, *a, **kw)
        self.otp, self.otp_wait = relay, wait
    rec.Replayer.__init__ = init
    try:
        ok, rp = rec.replay(r, {"ID": "", "PW": ""}, os.path.join(OUT, label), "000", log=lines.append, step_timeout=5, step_tries=1)
    finally:
        rec.Replayer.__init__ = orig
    return ok, rp, lines


def fallback(phone, manual_sec=4):
    calls, logs = [], []
    fo = otp_relay.FallbackOtp(phone=phone, manual_sec=manual_sec, on_manual=lambda: calls.append(time.time()), log=logs.append)
    return fo, calls, logs


try:
    print("값")
    check("MANUAL_SEC 300·GIVE_UP '인증번호를 받지 못함'", otp_relay.MANUAL_SEC == 300 and otp_relay.GIVE_UP == "인증번호를 받지 못함")

    print("휴대폰이 번호를 준다")
    FILL[0] = 0
    ph = FakePhoneRelay("ok")
    fo, calls, logs = fallback(ph)
    n0 = len(SENT)
    ok, rp, lines = replay("phone_ok", fo)
    check("통과, on_manual 은 불리지 않는다", ok and not calls and len(SENT) - n0 == 1, rp.results[-1:])
    check("휴대폰 요청을 열고 닫는다", ph.opened == 1 and ph.closed >= 1)

    print("휴대폰이 조용하다 → seconds 뒤 사람 입력")
    FILL[0] = 2500
    ph = FakePhoneRelay("quiet")
    fo, calls, logs = fallback(ph, manual_sec=6)
    began = time.time()
    ok, rp, lines = replay("phone_quiet", fo, wait=1)
    check("휴대폰 1초 → on_manual 한 번 → 칸에 넣은 번호로 통과", ok and len(calls) == 1 and calls[0] - began >= 0.9, (rp.results[-1:], calls))

    print("휴대폰을 기다리는 중에 칸에 넣음")
    FILL[0] = 800
    ph = FakePhoneRelay("quiet")
    fo, calls, logs = fallback(ph, manual_sec=6)
    t0 = time.time()
    ok, rp, lines = replay("typed_early", fo, wait=20)
    check("휴대폰 기다림(20초)을 다 기다리지 않고 통과, on_manual 은 안 불림", ok and time.time() - t0 < 15 and not calls, f"{time.time() - t0:.1f}초 {rp.results[-1:]}")

    print("휴대폰 없음")
    FILL[0] = 1000
    fo = otp_relay.standalone_relay(None, [], "가나몰", on_manual=lambda: calls2.append(1), log=lambda m: None)
    calls2 = []
    check("standalone_relay(None, []) → 휴대폰 없는 FallbackOtp", isinstance(fo, otp_relay.FallbackOtp) and fo.phone is None)
    fo.manual_sec = 6
    ok, rp, lines = replay("no_phone", fo)
    check("바로 사람 입력 (on_manual 한 번)", ok and calls2 == [1], rp.results[-1:])

    print("phone.open 이 거절 (DENIED)")
    FILL[0] = 1000
    ph = FakePhoneRelay("denied")
    fo, calls, logs = fallback(ph, manual_sec=6)
    ok, rp, lines = replay("denied", fo)
    check("예외 없이 사람 입력, 로그 한 줄", ok and len(calls) == 1 and len(logs) == 1
          and logs[0].startswith("휴대폰으로 인증번호를 받을 수 없어 직접 입력을 기다립니다.") and otp_relay.DENIED in logs[0], repr(logs))

    print("아무도 안 넣음")
    FILL[0] = 0
    ph = FakePhoneRelay("quiet")
    fo, calls, logs = fallback(ph, manual_sec=1.5)
    n0 = len(SENT)
    ok, rp, lines = replay("nobody", fo, wait=1)
    last = rp.results[-1] if rp.results else None
    check("마지막 결과가 fail·'인증번호를 받지 못함'", not ok and last is not None and last[1] == "fail" and last[2] == "인증번호를 받지 못함", repr(rp.results))
    check("'인증번호 받기' 는 한 번만 눌림 (재발송 없음)", len(SENT) - n0 == 1 and ph.opened == 1, f"보낸 수 {len(SENT) - n0}, 열기 {ph.opened}")
    check("휴대폰 요청은 닫는다", ph.closed >= 1)
    sent_codes = set(SENT)
    check("로그·결과 글에 인증번호 숫자가 없다", not [c for c in sent_codes if any(c in x for x in lines + [str(rp.results)] + logs)])

    print("사이트가 거절 → 지금처럼 다시 (모두 3번)")
    FILL[0] = 0
    ph = FakePhoneRelay("wrong")
    fo, calls, logs = fallback(ph, manual_sec=1)
    n0 = len(SENT)
    ok, rp, lines = replay("rejected", fo)
    check("거절은 '인증번호 받기' 부터 모두 3번", not ok and len(SENT) - n0 == rec.OTP_TRIES and ph.opened == rec.OTP_TRIES
          and "3번 거절" in rp.results[-1][2], (len(SENT) - n0, ph.opened, rp.results[-1:]))

    print("FallbackOtp.wait (재생기 없이 - 칸 흉내)")

    class Field:
        def __init__(self):
            self.v = ""

        def input_value(self):
            return self.v
    fld = Field()
    fo, calls, logs = fallback(FakePhoneRelay("quiet"), manual_sec=5)
    req = fo.open()
    threading.Timer(1.5, lambda: setattr(fld, "v", "482913")).start()
    t0 = time.time()
    got = fo.wait(req, 0.5, time.sleep, field=fld)
    check("다른 스레드가 칸에 넣은 번호 (1초 그대로) → 그 번호", got == "482913" and len(calls) == 1 and time.time() - t0 < 4, (got, calls))
    fo.close(req)
    check("close 는 휴대폰 요청을 닫는다", fo.phone.closed == 1)

    print("web_runner (스탠드얼론일 때만)")
    import web_runner  # noqa: E402
    preset = {"no": 1, "name": "가나몰", "code": "123", "record": {"steps": r["steps"]}}
    st = web_runner.status
    saved = (st.read_presets, st.login_mismatch, st.record_mail_host, st.preset_limit, otp_relay._standalone)
    st.read_presets = lambda: [preset]
    st.login_mismatch = lambda *a: False
    st.record_mail_host = lambda rec_: None
    st.preset_limit = lambda: 50
    try:
        otp_relay._standalone = lambda: True
        p_sa = web_runner._replay_problems("가나몰", {"Preset": 1})
        otp_relay._standalone = lambda: False
        p_cloud = web_runner._replay_problems("가나몰", {"Preset": 1})
        check("_replay_problems: 스탠드얼론 + 인증번호 단계 + 휴대폰 없음 → []", p_sa == [], repr(p_sa))
        check("_replay_problems: 일반 버전은 지금 글", len(p_cloud) == 1 and "인증 휴대폰·발신번호가 설정되지 않았습니다" in p_cloud[0], repr(p_cloud))

        made = {}

        class FakeRp:
            def __init__(self, *a, **k):
                self.otp, self.saved, self.results, self.ai_calls, self.no_target = None, [], [], 0, False
                made["rp"] = self

            def run(self):
                return True
        real = (web_replay_mod := web_runner.web_replay).Replayer, web_runner.attach_ai, web_runner.site_dest, otp_relay.agent_relay, st.metric
        relays = []
        web_replay_mod.Replayer = FakeRp
        web_runner.attach_ai = lambda rp, name: None
        web_runner.site_dest = lambda: OUT
        otp_relay.agent_relay = lambda phone, senders, site: relays.append((phone, senders, site)) or FakePhoneRelay("ok")
        st.metric = lambda *a, **k: metrics.append((a, k))
        metrics, lines_ = [], []
        real_log = web_runner.log
        web_runner.log = lines_.append
        page = types.SimpleNamespace(context=None, remove_listener=lambda *a: None, on=lambda *a: None)
        try:
            otp_relay._standalone = lambda: False
            web_runner.action_replay(page, "가나몰", {"Preset": 1, "ID": "a", "PW": "b", "Phone": "ph_00000001", "SmsSenders": ["15881234"]})
            check("일반 버전: action_replay 는 agent_relay 를 부르고 FallbackOtp 를 만들지 않는다",
                  relays == [("ph_00000001", ["15881234"], "가나몰")] and isinstance(made["rp"].otp, FakePhoneRelay), repr((relays, made["rp"].otp)))
            relays.clear()
            otp_relay._standalone = lambda: True
            web_runner.action_replay(page, "가나몰", {"Preset": 1, "ID": "a", "PW": "b"})
            otp = made["rp"].otp
            check("스탠드얼론·휴대폰 없음: FallbackOtp(휴대폰 없음), agent_relay 를 부르지 않는다",
                  isinstance(otp, otp_relay.FallbackOtp) and otp.phone is None and relays == [] and otp.manual_sec == otp_relay.MANUAL_SEC, repr(otp))
            otp.on_manual()
            check("on_manual: 로그 '직접 입력하여 주십시오 (5분 안)' 와 현황 '인증번호 직접 입력 대기' 300초",
                  any("Edge 창의 인증번호 칸에 인증번호를 직접 입력하여 주십시오. (5분 안)" in x for x in lines_)
                  and any(a[0] == "가나몰:otp_manual" and a[1] == "인증번호 직접 입력 대기" and a[2] == 300 and k.get("unit") == "초" for a, k in metrics),
                  repr((lines_[-3:], metrics)))
            lines_.clear()
            web_runner.action_replay(page, "가나몰", {"Preset": 1, "ID": "a", "PW": "b", "Phone": "ph_00000001", "SmsSenders": ["15881234"]})
            otp = made["rp"].otp
            check("스탠드얼론·휴대폰 있음: FallbackOtp(휴대폰 중계) + '휴대폰 …(으)로 수신합니다' 로그",
                  isinstance(otp, otp_relay.FallbackOtp) and isinstance(otp.phone, FakePhoneRelay)
                  and any("인증번호는 휴대폰 ph_00000001(으)로 수신합니다." in x for x in lines_), repr(lines_))
            FakeRp.run = lambda self: (self.results.append((2, "fail", otp_relay.GIVE_UP)), False)[1]
            try:
                web_runner.action_replay(page, "가나몰", {"Preset": 1, "ID": "a", "PW": "b"})
                check("받지 못하면 그 사이트만 RuntimeError('2단계에서 멈췄습니다: 인증번호를 받지 못함')", False, "예외 없음")
            except RuntimeError as e:
                check("받지 못하면 그 사이트만 RuntimeError('2단계에서 멈췄습니다: 인증번호를 받지 못함')", str(e) == "2단계에서 멈췄습니다: 인증번호를 받지 못함", str(e))
        finally:
            web_replay_mod.Replayer, web_runner.attach_ai, web_runner.site_dest, otp_relay.agent_relay, st.metric = real
            web_runner.log = real_log
    finally:
        st.read_presets, st.login_mismatch, st.record_mail_host, st.preset_limit, otp_relay._standalone = saved

    print("옵저버 (스탠드얼론일 때만)")
    import rpa_observer  # noqa: E402
    check("저장 화면 안내 글 (스탠드얼론)", "정하지 않으면 실행할 때 Edge 창의 인증번호 칸에 직접 입력하여야 합니다" in rpa_observer.SMS_HINT_STANDALONE
          and rpa_observer.sms_hint(True) == rpa_observer.SMS_HINT_STANDALONE and rpa_observer.sms_hint(False) == rpa_observer.SMS_HINT)
finally:
    srv.shutdown()

print(f"\n실패: {len(fails)}" + (f" ({', '.join(fails)})" if fails else ""))
sys.exit(1 if fails else 0)
