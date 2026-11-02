# -*- coding: utf-8 -*-
"""메일 2차인증 - 기록 다듬기 (설계 docs/superpowers/specs/2026-11-02-email-otp-design.md 3절). 브라우저 없이 기록기 원 단계로.
    .venv\\Scripts\\python.exe tests\\test_mail_otp_record.py
"""
import datetime
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import web_replay as rec  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(("  통과  " if ok else "  실패  ") + name + (f" ({detail})" if not ok and detail != "" else ""))
    if not ok:
        fails.append(name)


T = [0]


def st(kind, page, text="", url="/a", **kw):
    """기록기 원 단계 하나 (Recorder._event 가 만드는 꼴)."""
    T[0] += 1000
    target = {"css": f"#e{T[0]}", "text": text, "label": "", "placeholder": kw.pop("ph", ""), "aria": "", "title": "", "name": "",
              "id": "", "tag": "input" if kind in ("fill", "secret") else "button", "textCount": 1, "inOverlay": False}
    s = {"kind": kind, "page": page, "frame": {"main": True, "name": ""}, "url": url, "target": target, "t": T[0]}
    s.update(kw)
    return s


def row(text):
    return {"sel": "ul.mails > li", "inner": "", "key": "m1", "at": 0, "mine": [{"k": "m1", "t": text, "s": text}]}


TODAY = datetime.date(2026, 11, 2)
CODE = "482913"


def copy_paste_steps(mail_page=1, a_login_page=0):
    return [
        st("fill", a_login_page, ph="아이디"), st("secret", a_login_page, host="shop.example"), st("click", a_login_page, "로그인"),
        st("click", 0, "인증 메일 보내기"),
        st("fill", mail_page, ph="메일 아이디", url="/mail/login"), st("secret", mail_page, host="mail.example", url="/mail/login"),
        st("click", mail_page, "로그인", url="/mail/login"),
        st("click", mail_page, "[가짜몰] 인증번호 안내 10:42", url="/mail/list", row=row("[가짜몰] 인증번호 안내 10:42")),
        st("copy", mail_page, url="/mail/read", copied=CODE),
        st("fill", 0, ph="인증번호", value=CODE, pasted=True), st("click", 0, "확인"),
        st("click", 0, "주문 엑셀"),
    ]


# --- 번호 복사·붙여넣기
r = rec.finalize(copy_paste_steps(), TODAY, "https://shop.example/login")
s = r["steps"]
paste = next(x for x in s if x["kind"] == "otp")
check("붙여넣은 칸은 otp + source copy, 값 없음", paste.get("source") == "copy" and "value" not in paste, paste)
check("메일 보내기 누르기가 otpSend", s[3].get("otpSend") is True and not any(x.get("otpSend") for i, x in enumerate(s) if i != 3))
check("복사 단계는 copyCode, 모양만", s[8]["kind"] == "copyCode" and s[8]["shape"] == {"chars": "digit", "len": 6})
check("복사 전 목록 줄 누르기는 mailOpen (숫자·시각 뺀 줄 모양)", s[7].get("mailOpen") == {"fp": "[가짜몰] 인증번호 안내"}, s[7].get("mailOpen"))
check("쇼핑몰 계정 ID·PW, 메일함 계정 MAIL_ID·MAIL_PW",
      [x.get("credential") for x in s[:2]] == ["ID", "PW"] and [x.get("credential") for x in s[4:6]] == ["MAIL_ID", "MAIL_PW"],
      [x.get("credential") for x in s])
check("기록에 복사한 번호가 없다", CODE not in json.dumps(r, ensure_ascii=False))
check("메일 인증 기록은 버전 2 (옛 ACTOR 는 거절)", r["version"] == rec.MAIL_RECORD_VERSION == 2 and rec.MAIL_RECORD_VERSION in rec.RECORD_VERSIONS)
check("메일 계정을 넣을 호스트", rec.mail_host(s) == "mail.example")
check("다른 사이트 비밀번호 경고(I1)는 메일함을 빼고 센다", rec.password_sites(s) == ["shop.example"], rec.password_sites(s))
a, b = rec.auth_start(s), rec.auth_end(s)
check("인증 차례는 쇼핑몰 로그인부터 붙여넣기 다음 [확인]까지 (메일함 포함)", a == 1 and b == 11, (a, b))
check("메일 인증 문제 없음", rec.mail_auth_problem(s) is None, rec.mail_auth_problem(s))
want = {3: "'인증 메일 보내기' 누르기 (메일 요청)", 4: "인증 메일 아이디 입력", 5: "인증 메일 비밀번호 입력",
        7: "인증 메일 열기 (제목: [가짜몰] 인증번호 안내)", 8: "메일에서 인증번호 복사", 9: "'인증번호' 칸에 메일로 받은 번호 넣기"}
got = {i: rec.describe(s[i]) for i in want}
check("단계 글 (설계 6절)", got == want, got)

# --- 링크로 인증
raw = copy_paste_steps()[:8] + [
    st("click", 1, "인증하기", url="/mail/read", href="https://shop.example/a/confirm?t=secret-token-abc"),
    st("click", 0, "인증 완료"), st("click", 0, "주문 엑셀")]
r2 = rec.finalize(raw, TODAY, "https://shop.example/login")
s2 = r2["steps"]
check("메일 링크 누르기는 mailLink (글자·호스트만)", s2[8].get("mailLink") == {"text": "인증하기", "host": "shop.example"}, s2[8].get("mailLink"))
check("링크의 나머지 주소(표)는 기록에 없다", "secret-token-abc" not in json.dumps(r2, ensure_ascii=False))
check("링크 방식: 메일함으로 넘어가기 직전 쇼핑몰 누르기가 otpSend", s2[3].get("otpSend") is True)
check("링크 방식도 mailOpen", s2[7].get("mailOpen") == {"fp": "[가짜몰] 인증번호 안내"})
check("링크 단계 글", rec.describe(s2[8]) == "메일의 '인증하기' 링크 누르기", rec.describe(s2[8]))
check("링크 방식도 버전 2·문제 없음", r2["version"] == 2 and rec.mail_auth_problem(s2) is None)

# --- 손으로 친 인증번호는 지금처럼 휴대폰
r3 = rec.finalize([st("click", 0, "인증번호 받기"), st("fill", 0, ph="인증번호", value="123456"), st("click", 0, "확인")], TODAY, "https://x/")
check("손으로 친 인증번호 칸은 휴대폰 otp (source 없음)", r3["steps"][1]["kind"] == "otp" and "source" not in r3["steps"][1]
      and r3["version"] == 1, r3["steps"][1])

# --- 메일 인증이 없는 보통 기록: 다른 사이트 비밀번호는 지금처럼 PW (I1 경고가 그대로 뜨게)
plain = rec.finalize([st("fill", 0, ph="아이디"), st("secret", 0, host="shop.example"), st("click", 0, "로그인"),
                      st("fill", 1, ph="아이디"), st("secret", 1, host="other.example"), st("click", 1, "로그인")], TODAY, "https://shop.example/")
check("메일 인증이 없으면 메일 계정 칸으로 바꾸지 않는다 (I1 경고 유지)",
      [x.get("credential") for x in plain["steps"] if x.get("credential")] == ["ID", "PW", "ID", "PW"]
      and rec.password_sites(plain["steps"]) == ["other.example", "shop.example"] and plain["version"] == 1,
      [x.get("credential") for x in plain["steps"]])

# --- 쇼핑몰 로그인이 팝업 창
r4 = rec.finalize(copy_paste_steps(mail_page=2, a_login_page=1), TODAY, "https://shop.example/login")
check("쇼핑몰 로그인이 팝업(page 1)이어도 그것이 ID·PW, 메일함(page 2)이 MAIL_*",
      [x.get("credential") for x in r4["steps"][:2]] == ["ID", "PW"] and r4["steps"][5].get("credential") == "MAIL_PW")

# --- 저장 막기 (설계 6절 글 그대로)
twice = copy_paste_steps() + copy_paste_steps()[3:11]
check("메일 인증 둘", rec.mail_auth_problem(rec.finalize(twice, TODAY, "https://shop.example/")["steps"])
      == "프리셋 하나에는 메일 인증을 하나만 기록할 수 있습니다. 다시 기록하여 주십시오.")
third = copy_paste_steps()[:11] + [st("fill", 2, ph="아이디"), st("secret", 2, host="other.example"), st("click", 2, "로그인")]
check("세 번째 사이트 로그인", rec.mail_auth_problem(rec.finalize(third, TODAY, "https://shop.example/")["steps"])
      == "쇼핑몰과 인증 메일함이 아닌 다른 사이트에 로그인한 기록은 저장할 수 없습니다. 다시 기록하여 주십시오.")
nested = copy_paste_steps()[:7] + [st("click", 1, "인증 메일 보내기"),
                                   st("click", 2, "[메일] 로그인 확인", url="/c/list", row=row("[메일] 로그인 확인")),
                                   st("copy", 2, copied="777777"), st("fill", 1, ph="확인 번호", value="777777", pasted=True),
                                   st("click", 1, "확인")] + copy_paste_steps()[7:]
check("메일함 안의 메일 인증", rec.mail_auth_problem(rec.finalize(nested, TODAY, "https://shop.example/")["steps"])
      == "인증 메일함의 로그인에 다시 메일 인증이 필요한 경우는 지원하지 않습니다.")

# --- 줄 모양
check("줄 모양: 숫자·날짜·시각을 뺀다", rec.mail_fp("[몰] 인증번호 [482913] 안내 2026.11.02 10:42") == "[몰] 인증번호 [] 안내",
      rec.mail_fp("[몰] 인증번호 [482913] 안내 2026.11.02 10:42"))
check("줄 모양: 오후 2:05·11월 2일 꼴도", rec.mail_fp("인증 메일 오후 2:05") == rec.mail_fp("인증 메일 11월 2일") == "인증 메일",
      (rec.mail_fp("인증 메일 오후 2:05"), rec.mail_fp("인증 메일 11월 2일")))

print("실패: " + (", ".join(fails) if fails else "없음"))
sys.exit(1 if fails else 0)
