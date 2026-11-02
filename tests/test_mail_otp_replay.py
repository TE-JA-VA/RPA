# -*- coding: utf-8 -*-
"""메일 2차인증 - 기록기(copy·paste)와 재생 (설계 docs/superpowers/specs/2026-11-02-email-otp-design.md). 가짜 쇼핑몰·메일함 (mail_otp_sites).
창을 띄우지 않는다 (headless).
    .venv\\Scripts\\python.exe tests\\test_mail_otp_replay.py
"""
import datetime
import json
import os
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from playwright.sync_api import sync_playwright  # noqa: E402

import mail_otp_sites  # noqa: E402
import web_replay as rec  # noqa: E402

A, B, ST = mail_otp_sites.start()
OUT = tempfile.mkdtemp(prefix="mail_otp_")
MAIL_PW, SHOP_PW = "mail-secret-pw-9", "shop-secret-pw-7"
fails = []


def check(name, ok, detail=""):
    print(("  통과  " if ok else "  실패  ") + name + (f" ({detail})" if not ok and detail != "" else ""))
    if not ok:
        fails.append(name)


def record(mode, **opts):
    """사람이 하듯: 쇼핑몰 로그인 → 인증 메일 보내기 → 새 탭에서 메일함 로그인 → 메일 열기 → 번호 복사 → 쇼핑몰 칸에 붙여넣기 → 확인
    (링크 방식은 메일의 링크 → 쇼핑몰 [인증 완료]). 새 탭·주소 이동 단계는 옵저버(LiveRecorder)가 적는 꼴 그대로 넣는다."""
    ST.reset(mode)
    for k, v in opts.items():
        setattr(ST, k, v)
    with sync_playwright() as p:
        browser = rec.edge(p.chromium.launch, headless=True)
        ctx = browser.new_context(accept_downloads=True)
        for origin in (A, B):
            ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=origin)    # 시험 브라우저가 Ctrl+C·V 를 하게 (제품은 클립보드를 안 읽는다)
        r = rec.Recorder(ctx)
        a = ctx.new_page()
        a.goto(A + "/a/login")
        a.wait_for_timeout(300)
        a.fill("#uid", "shopper")
        a.click("#upw")
        a.keyboard.type(SHOP_PW, delay=5)
        a.click("text=로그인")
        a.wait_for_url("**/a/verify")
        a.click("#send")
        a.wait_for_function("document.getElementById('msg').textContent === '보냈습니다'")
        b = ctx.new_page()
        no = r._no(b)
        r.steps[-1].pop("opens", None)                     # 사람이 연 새 탭 (옵저버는 user_tab 으로 안다)
        r.steps.append({"kind": "newtab", "page": no, "url": "", "t": time.time() * 1000})
        b.goto(B + "/mail/login")
        r.steps.append({"kind": "goto", "page": no, "url": "/mail/login", "href": B + "/mail/login", "t": time.time() * 1000})
        b.wait_for_timeout(300)
        b.fill("#mid", "inbox-user")
        b.click("#mpw")
        b.keyboard.type(MAIL_PW, delay=5)
        b.click("text=로그인")
        if ST.sms_on_mailbox:                              # 메일함의 휴대폰 문자 인증 - 사람이 문자를 보고 친다
            b.wait_for_url("**/mail/sms")
            b.click("#smssend")
            b.wait_for_function("document.getElementById('m').textContent === '보냈습니다'")
            b.click("#smscode")
            b.keyboard.type(ST.sms[-1], delay=20)
            b.click("text=확인")
        b.wait_for_url("**/mail/list")
        b.wait_for_timeout(300)
        b.click("ul.mails li:first-child .subj")
        b.wait_for_url("**/mail/read*")
        b.wait_for_timeout(300)
        if mode == "link":
            with ctx.expect_page() as pi:
                b.click("a[target=_blank]")
            pi.value.wait_for_load_state()
            a.bring_to_front()
            a.click("text=인증 완료")
        else:
            b.evaluate("() => { const r = document.createRange(); r.selectNodeContents(document.getElementById('code'));"
                       " const s = getSelection(); s.removeAllRanges(); s.addRange(r); }")   # 번호만 골라 (더블클릭은 뒤 빈칸까지 고른다)
            b.keyboard.press("Control+C")
            a.bring_to_front()
            a.click("#otp")
            a.keyboard.press("Control+V")
            a.wait_for_timeout(200)
            a.click("text=확인")
        a.wait_for_url("**/a/done")
        a.wait_for_timeout(300)
        res = rec.finalize(r.steps, datetime.date.today(), A + "/a/login")
        browser.close()
    path = os.path.join(OUT, f"rec_{mode}{len(opts)}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    return res, open(path, encoding="utf-8").read()


print("--- 기록 (번호 복사·붙여넣기)")
r_code, text = record("code")
print("    " + " / ".join(rec.describe(s) for s in r_code["steps"]))
s = r_code["steps"]
kinds = [x["kind"] for x in s]
check("복사 단계 copyCode (숫자 6자리 모양)", any(x["kind"] == "copyCode" and x["shape"] == {"chars": "digit", "len": 6} for x in s), kinds)
paste = next((x for x in s if x["kind"] == "otp"), {})
check("붙여넣은 칸은 otp source=copy (Ctrl+V 의 paste 이벤트)", paste.get("source") == "copy", paste)
check("메일 보내기에 otpSend·mailSend", any(x.get("mailSend") and rec.name_of(x) == "인증 메일 보내기" for x in s))
check("메일 줄에 mailOpen", any(x.get("mailOpen", {}).get("fp") == "[가짜몰] 인증번호 안내" for x in s), [x.get("mailOpen") for x in s])
check("쇼핑몰·메일함 계정 칸", [x.get("credential") for x in s if x.get("credential")] == ["ID", "PW", "MAIL_ID", "MAIL_PW"],
      [x.get("credential") for x in s if x.get("credential")])
check("기록 파일에 번호·메일 비밀번호·쇼핑몰 비밀번호가 없다",
      ST.codes[-1] not in text and MAIL_PW not in text and SHOP_PW not in text and "inbox-user" not in text)
check("기록 버전 2", r_code["version"] == 2)
check("기록기 JS 는 붙여넣기를 paste 이벤트로 안다 (오른쪽 메뉴 붙여넣기도)", "addEventListener('paste'" in rec.JS and "addEventListener('copy'" in rec.JS)

print("--- 기록 (메일의 인증 링크)")
r_link, text = record("link")
print("    " + " / ".join(rec.describe(s) for s in r_link["steps"]))
s = r_link["steps"]
link = next((x for x in s if x.get("mailLink")), {})
check("인증 링크 누르기는 mailLink (글자·호스트)", link.get("mailLink") == {"text": "인증하기", "host": "127.0.0.1"}, link.get("mailLink"))
check("링크의 표는 기록에 없다", ST.tokens[-1] not in text)
check("링크 방식도 메일 보내기에 otpSend·mailSend, 버전 2",
      any(x.get("mailSend") and rec.name_of(x) == "인증 메일 보내기" for x in s) and r_link["version"] == 2)

# =====================================================================================================================
# 재생 (Task 3)
# =====================================================================================================================
CREDS = {"ID": "shopper", "PW": SHOP_PW, "MAIL_ID": "inbox-user", "MAIL_PW": MAIL_PW}


def replay(label, r, wait=20, preview=False, memory=True, relay=None, **opts):
    """r 을 재생한다. opts 는 가짜 사이트 상태 (reset 뒤에 켠다 - before 는 재생 전에 부를 함수)."""
    before = opts.pop("before", None)
    ST.reset("link" if any(x.get("mailLink") for x in r["steps"]) else "code")
    for k, v in opts.items():
        setattr(ST, k, v)
    if before:
        before()
    lines, ctx = [], {}
    orig = rec.Replayer.__init__
    mem_path = os.path.join(OUT, f"mem_{label}.json")

    def init(self, *a, **kw):
        orig(self, *a, **kw)
        self.otp_wait = wait
        self.pick_preview = preview
        self.mail_memory = rec.MailMemory(mem_path) if memory else None
        if relay is not None:
            self.otp = relay                       # 메일함의 휴대폰 문자 인증 흉내 (사슬)
        ctx["rp"] = self
    rec.Replayer.__init__ = init
    try:
        ok, rp = rec.replay(r, dict(CREDS), os.path.join(OUT, label), "000", log=lines.append, step_timeout=5, step_tries=1)
    finally:
        rec.Replayer.__init__ = orig
    log = "\n".join(lines)
    with open(os.path.join(OUT, f"{label}.log"), "w", encoding="utf-8") as f:     # 실패를 볼 때
        f.write(log)
    check(f"[{label}] 로그에 번호·비밀번호가 없다", MAIL_PW not in log and SHOP_PW not in log
          and not any(c in log for c in ST.codes), [x for x in lines if any(c in x for c in ST.codes)][:2])
    return ok, rp, lines


def last_why(rp):
    return rp.results[-1][2] if rp.results else ""


r_alnum, _ = record("code", alnum=True)
r_subj, _ = record("code", subject_with_code=True)

print("--- 재생")
ok, rp, lines = replay("ok", r_code)
check("번호 메일: 끝까지, 한 번에", ok and ST.sent == 1, (rp.results[-2:], ST.sent))
check("메일 기다리는 동안 진행 글", any("인증 메일" in x for x in lines))

ok, rp, lines = replay("old_mail_top", r_code, before=lambda: ST.add_old())
check("옛 인증 메일이 맨 위에 있어도 (받은 시각) 새 메일을 연다 - 한 번에", ok and ST.sent == 1, (last_why(rp), ST.sent))

ok, rp, lines = replay("old_mail_no_time", r_code, show_time=False, delay=4, before=lambda: ST.add_old())
check("받은 시각이 없는 메일함 + 옛 메일 맨 위: 거절된 뒤 다시 시도로 통과", ok and ST.sent >= 2, (last_why(rp), ST.sent))
check("다시 시도는 로그에 (n/3)", any("2/3" in x for x in lines))

ok, rp, lines = replay("late_mail", r_code, delay=6)
check("메일이 늦게 와도 기다렸다 통과", ok and ST.sent == 1, (last_why(rp), ST.sent))

ok, rp, lines = replay("subject_with_code", r_subj, subject_with_code=True)
check("제목에 번호가 든 메일함 (Review Focus 1)", ok and ST.sent == 1, (last_why(rp), ST.sent))

ok, rp, lines = replay("alnum", r_alnum, alnum=True)
check("영문+숫자 번호", ok and ST.sent == 1, (last_why(rp), ST.sent))

ok, rp, lines = replay("never", r_code, wait=2, never=True)
check("메일이 끝내 안 오면 3번 뒤 실패 - 글", not ok and ST.sent == 3 and last_why(rp) == "인증 메일을 3번 받지 못했습니다.", (last_why(rp), ST.sent))

ok, rp, lines = replay("mailbox_mfa", r_code, mfa_on_mailbox=True)
check("메일함이 기록에 없던 2차인증 - 다시 시도 없이 실패, 글", not ok and ST.sent == 1 and last_why(rp)
      == "인증 메일 계정에 로그인하지 못했습니다. 메일함이 기록에 없던 2차인증을 요구했을 수 있습니다. 옵저버에서 다시 기록하여 주십시오.",
      (last_why(rp), ST.sent))

bad = json.loads(json.dumps(r_code))
next(x for x in bad["steps"] if x.get("credential") == "MAIL_PW")["host"] = "evil.example"
ok, rp, lines = replay("wrong_host", bad)
check("메일 계정은 등록한 메일함 호스트에만 - 다른 사이트면 넣지 않고 실패", not ok
      and last_why(rp) == "인증 메일 계정을 등록한 메일함이 아닌 사이트에서 로그인을 요구하여 중단하였습니다.", last_why(rp))

ok, rp, lines = replay("link_ok", r_link)
check("링크 메일: 끝까지, 한 번에", ok and ST.sent == 1, (last_why(rp), ST.sent))
ok, rp, lines = replay("link_old", r_link, show_time=False, delay=4, before=lambda: ST.add_old())
check("옛 링크(만료)를 먼저 열어도 다시 시도로 통과", ok and ST.sent >= 2, (last_why(rp), ST.sent))
ok, rp, lines = replay("link_bad", r_link, bad_links=True)
check("링크로 3번 다 실패 - 글", not ok and ST.sent == 3 and last_why(rp) == "인증 링크로 3번 인증하지 못했습니다.", (last_why(rp), ST.sent))

nolink = json.loads(json.dumps(r_link))
next(x for x in nolink["steps"] if x.get("mailLink"))["target"]["text"] = "없는 링크"
next(x for x in nolink["steps"] if x.get("mailLink"))["mailLink"]["text"] = "없는 링크"
ok, rp, lines = replay("link_missing", nolink, wait=2)
check("메일에서 링크를 못 찾으면 - 글", not ok and last_why(rp) == "인증 메일에서 인증 링크를 찾지 못했습니다.", last_why(rp))

ok, rp, lines = replay("code_missing", r_alnum, wait=2)        # 숫자 6자리 메일에서 영문+숫자 8자리를 찾는다
check("메일에서 번호를 못 찾으면 - 글", not ok and last_why(rp) == "인증 메일에서 인증번호를 찾지 못했습니다.", last_why(rp))

ok1, rp1, _ = replay("two_a", r_code)
ok2, rp2, _ = replay("two_b", r_code)
check("재생기마다 번호를 따로 든다 (병렬 수집, Review Focus 5)", ok1 and ok2 and rp1 is not rp2 and "mail_code" in vars(rp1) and "mail_code" in vars(rp2))

ok, rp, lines = replay("preview", r_code, preview=True, before=lambda: ST.add_old())
check("미리보기: 기억 없이도 받은 시각으로 새 메일", ok and ST.sent == 1, (last_why(rp), ST.sent))

class SmsRelay:
    """휴대폰 중계 흉내 - 메일함이 마지막으로 보낸 문자 번호를 준다."""
    def open(self, tick=None):
        return {"req": len(ST.sms)}

    def wait(self, req, seconds, tick, field=None):
        return ST.sms[-1] if len(ST.sms) > req["req"] else None

    def close(self, req):
        pass


print("--- 최종 검토 고침: 메일함에 휴대폰 문자 인증이 붙은 사슬 (I5), 주소 모양 인증 링크 (I3)")
r_sms, _ = record("code", sms_on_mailbox=True)
ks = [(x["kind"], x.get("source")) for x in r_sms["steps"] if x["kind"] == "otp"]
check("사슬 기록: 메일함 문자 인증칸(휴대폰) + 쇼핑몰 번호칸(메일)", ks == [("otp", None), ("otp", "copy")], ks)
ok, rp, lines = replay("chain", r_sms, relay=SmsRelay(), sms_on_mailbox=True)
check("사슬: 한 번에 통과 (문자 1번, 메일 1번)", ok and ST.sent == 1 and len(ST.sms) == 1, (last_why(rp), ST.sent, len(ST.sms)))
ok, rp, lines = replay("chain_retry", r_sms, relay=SmsRelay(), sms_on_mailbox=True, show_time=False, delay=4, before=lambda: ST.add_old())
check("사슬: 쇼핑몰이 번호를 거절하면 '인증 메일 보내기' 부터 다시 (메일함 문자는 다시 안 함)",
      ok and ST.sent >= 2 and len(ST.sms) == 1, (last_why(rp), ST.sent, len(ST.sms)))
r_url, text = record("link", link_url_text=True)
check("주소 모양 링크: 기록에 표가 없다", ST.tokens[-1] not in text)
ok, rp, lines = replay("link_url_text", r_url, link_url_text=True)
check("주소 모양 링크: 호스트로 찾아 통과 (수신거부 링크는 안 누른다)", ok and ST.sent == 1, (last_why(rp), ST.sent))

print("실패: " + (", ".join(fails) if fails else "없음"))
sys.exit(1 if fails else 0)
