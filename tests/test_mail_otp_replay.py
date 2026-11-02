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


def record(mode):
    """사람이 하듯: 쇼핑몰 로그인 → 인증 메일 보내기 → 새 탭에서 메일함 로그인 → 메일 열기 → 번호 복사 → 쇼핑몰 칸에 붙여넣기 → 확인
    (링크 방식은 메일의 링크 → 쇼핑몰 [인증 완료]). 새 탭·주소 이동 단계는 옵저버(LiveRecorder)가 적는 꼴 그대로 넣는다."""
    ST.reset(mode)
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
        b.wait_for_url("**/mail/list")
        b.wait_for_timeout(300)
        b.click("ul.mails li:first-child .subj")
        b.wait_for_url("**/mail/read*")
        b.wait_for_timeout(300)
        if mode == "link":
            with ctx.expect_page() as pi:
                b.click("text=인증하기")
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
    path = os.path.join(OUT, f"rec_{mode}.json")
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

print("실패: " + (", ".join(fails) if fails else "없음"))
sys.exit(1 if fails else 0)
