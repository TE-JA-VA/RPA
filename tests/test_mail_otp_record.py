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


# --- 메일 본문이 표이고 번호 칸을 누르고 복사한 기록 (2026-11-06 실사용: 18단계 '인증 메일 열기 (제목: )' 로 못 찾음)
def table_row(text):
    return dict(row(text), sel="table > tr", key="")


def body_click_steps(code_cell=CODE):
    steps = [st("fill", 0, ph="아이디"), st("secret", 0, host="shop.example"), st("click", 0, "로그인"), st("click", 0, "인증 메일 보내기"),
             st("fill", 1, ph="메일 아이디", url="/mail/login"), st("secret", 1, host="mail.example", url="/mail/login"), st("click", 1, "로그인", url="/mail/login"),
             st("click", 1, "일회용 확인 코드", url="/mail/list", row=row("일회용 확인 코드")),
             st("click", 1, code_cell, url="/mail/read", row=table_row(code_cell)),
             st("copy", 1, url="/mail/read", copied=CODE),
             st("click", 1, code_cell, url="/mail/read", row=table_row(code_cell)),
             st("fill", 0, ph="인증번호", value=CODE, pasted=True), st("click", 0, "확인"), st("click", 0, "주문 엑셀", firstSeen=T[0] + 1)]
    return steps


r = rec.finalize(body_click_steps(), TODAY, "https://shop.example/login")
s = r["steps"]
opened = [x for x in s if x.get("mailOpen")]
check("본문 번호 칸을 눌러도 목록의 메일 줄이 인증 메일 열기", [x["mailOpen"]["fp"] for x in opened] == ["일회용 확인 코드"], [x.get("mailOpen") for x in s])
check("번호를 고르려고 누른 단계는 남기지 않는다 (번호는 매번 바뀐다)", CODE not in json.dumps(r, ensure_ascii=False) and len(s) == 12, [rec.describe(x) for x in s])
check("뒤 단계의 '몇 단계 뒤에 나타남' 번호를 함께 당긴다", s[-1].get("appearsAfter") == 10, s[-1].get("appearsAfter"))
check("메일 인증 문제 없음 (본문 표)", rec.mail_auth_problem(s) is None)
r = rec.finalize(body_click_steps(f"인증번호 {CODE}"), TODAY, "https://shop.example/login")
check("번호가 든 글 칸을 눌러도 같다", [x["mailOpen"]["fp"] for x in r["steps"] if x.get("mailOpen")] == ["일회용 확인 코드"], [rec.describe(x) for x in r["steps"]])
only_date = body_click_steps()
del only_date[8], only_date[9]
only_date[7:7] = [st("click", 1, "11-06 10:42", url="/mail/list", row=row("11-06 10:42"))]
r = rec.finalize(only_date, TODAY, "https://shop.example/login")
check("목록의 날짜 칸을 눌렀어도 제목이 빈 인증 메일 열기를 만들지 않는다", all(x["mailOpen"]["fp"] for x in r["steps"] if x.get("mailOpen")), [x.get("mailOpen") for x in r["steps"]])
check("제목이 빈 옛 기록은 저장을 막는다", "제목" in (rec.mail_auth_problem([{"kind": "click", "page": 1, "mailOpen": {"fp": ""}}]) or ""))

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

# --- 최종 검토 고침 (2026-11-02)
# C1: [수정]으로 메일함 로그인부터 이어 기록 - 쇼핑몰 비밀번호가 메일함 칸에 가면 안 된다. 복사는 앞부분, 붙여넣기는 새 부분이어도
head = rec.finalize(copy_paste_steps()[:4], TODAY, "https://shop.example/login")
full = rec.finalize(copy_paste_steps(), TODAY, "https://shop.example/login")
head_mail = dict(full, steps=full["steps"][:9])      # [수정] 의 앞부분 = 다듬은 기록을 자른 것 (짝이 맞은 복사가 남아 있다)
cont = rec.continue_record(head, copy_paste_steps()[4:], TODAY)
check("C1: 이어 기록해도 쇼핑몰 ID·PW, 메일함 MAIL_ID·MAIL_PW", [x.get("credential") for x in cont["steps"] if x.get("credential")]
      == ["ID", "PW", "MAIL_ID", "MAIL_PW"] and rec.mail_host(cont["steps"]) == "mail.example" and cont["version"] == 2,
      [x.get("credential") for x in cont["steps"] if x.get("credential")])
cont2 = rec.continue_record(head_mail, copy_paste_steps()[9:], TODAY)
paste2 = next((x for x in cont2["steps"] if x["kind"] == "otp"), {})
check("C1: 복사는 앞부분·붙여넣기는 새 부분이어도 메일 번호 칸 (값 없음)", paste2.get("source") == "copy" and CODE not in json.dumps(cont2), paste2)
raw_link = copy_paste_steps()[4:8] + [st("click", 1, "인증하기", url="/mail/read", href="https://shop.example/a/confirm?t=secret-token-abc"),
                                       st("click", 0, "인증 완료")]
cont3 = rec.continue_record(head, raw_link, TODAY)
check("C1: 메일함 로그인이 새 부분이어도 링크 인증을 알아보고 표를 남기지 않는다",
      any(x.get("mailLink") for x in cont3["steps"]) and "secret-token-abc" not in json.dumps(cont3))
cont4 = rec.continue_record(head_mail, [st("click", 1, "인증하기", url="/mail/read", href="https://shop.example/a/confirm?t=tok-xyz"),
                                        st("click", 0, "인증 완료")], TODAY)
check("C1: 메일함 로그인이 앞부분이어도 링크 인증", any(x.get("mailLink") for x in cont4["steps"]) and "tok-xyz" not in json.dumps(cont4))

# I2: 로그인 사이트와 메일 사이트가 다른 메일함 (다음: accounts.kakao.com → mail.daum.net) - 메일함 자신의 링크는 인증 링크가 아니다
daum = [st("fill", 0, ph="아이디"), st("secret", 0, host="shop.example"), st("click", 0, "로그인"), st("click", 0, "인증 메일 보내기"),
        st("fill", 1, ph="카카오계정"), st("secret", 1, host="accounts.kakao.com"), st("click", 1, "로그인"),
        st("click", 1, "[가짜몰] 인증번호 안내", href="https://mail.daum.net/read/77", pageHost="mail.daum.net", row=row("[가짜몰] 인증번호 안내")),
        st("click", 1, "인증하기", href="https://shop.example/a/confirm?t=t1", pageHost="mail.daum.net"), st("click", 0, "인증 완료")]
ds = rec.finalize(daum, TODAY, "https://shop.example/")["steps"]
check("I2: 메일함 안 링크(같은 사이트)는 인증 링크가 아니고, 쇼핑몰로 가는 링크만",
      [bool(x.get("mailLink")) for x in ds[7:9]] == [False, True] and rec.mail_auth_problem(ds) is None, [x.get("mailLink") for x in ds])

# I3: 링크 글자가 주소 그대로 - 표가 글자로도 남지 않는다
url_text = copy_paste_steps()[:8] + [st("click", 1, "https://shop.example/verify?t=SECRETTOKEN123", url="/mail/read",
                                        href="https://shop.example/verify?t=SECRETTOKEN123"), st("click", 0, "인증 완료")]
ru = rec.finalize(url_text, TODAY, "https://shop.example/")
lk = next(x for x in ru["steps"] if x.get("mailLink"))
check("I3: 주소 모양 링크 글자는 남기지 않는다 (호스트로 찾는다)", "SECRETTOKEN123" not in json.dumps(ru) and lk["mailLink"] == {"text": "", "host": "shop.example"},
      lk.get("mailLink"))

# M4(→중요): 같은 창 안 복사·붙여넣기(주문번호를 검색칸에)는 메일 인증이 아니다
same = rec.finalize([st("click", 0, "주문 조회"), st("copy", 0, copied="20261102"), st("fill", 0, ph="검색어", value="20261102", pasted=True),
                     st("click", 0, "검색")], TODAY, "https://x/")
check("M4: 같은 창 복사·붙여넣기는 평범한 칸 (버전 1)", same["steps"][1]["kind"] == "fill" and same["steps"][1].get("value") == "20261102"
      and same["version"] == 1, [x["kind"] for x in same["steps"]])

# I7: 받은 시각 꼴 (영어 AM/PM 앞뒤, 오전·오후, 24시)
sent = datetime.datetime.now().replace(hour=14, minute=4, second=0, microsecond=0).timestamp()
got = {t: rec.mail_time_ok(t, sent) for t in ("2:05 PM", "PM 2:05", "오후 2:05", "14:05", "02:05 AM", "오전 9:30", "13:50")}
check("I7: 받은 시각 - 오후 2:05 는 새 메일, 오전·이른 시각은 옛 메일",
      got == {"2:05 PM": True, "PM 2:05": True, "오후 2:05": True, "14:05": True, "02:05 AM": False, "오전 9:30": False, "13:50": False}, got)

# --- 줄 모양
check("줄 모양: 숫자·날짜·시각을 뺀다", rec.mail_fp("[몰] 인증번호 [482913] 안내 2026.11.02 10:42") == "[몰] 인증번호 [] 안내",
      rec.mail_fp("[몰] 인증번호 [482913] 안내 2026.11.02 10:42"))
check("줄 모양: 오후 2:05·11월 2일 꼴도", rec.mail_fp("인증 메일 오후 2:05") == rec.mail_fp("인증 메일 11월 2일") == "인증 메일",
      (rec.mail_fp("인증 메일 오후 2:05"), rec.mail_fp("인증 메일 11월 2일")))

# O7 (2026-11-03): 아이디·비밀번호를 두 쪽(/login → /login/pw)에서 받는 사이트 - 본 프레임은 주소가 바뀌어도 같은 화면
def at(s, path):
    return dict(s, frame={"main": True, "name": "", "path": path})


two = rec.finalize([at(st("fill", 0, ph="아이디", value="다른계정"), "/login"), st("click", 0, "다음"),
                    at(st("secret", 0, host="shop.example"), "/login/pw"), st("click", 0, "로그인")], TODAY, "https://shop.example/login")["steps"]
check("두 쪽 로그인의 아이디도 ID - 기록한 글자를 남기지 않는다 (O7)", two[0].get("credential") == "ID" and "value" not in two[0], two[0])
mail2 = copy_paste_steps()
mail2[4], mail2[5] = at(mail2[4], "/mail/id"), at(mail2[5], "/mail/pw")
s5 = rec.finalize(mail2, TODAY, "https://shop.example/login")["steps"]
check("메일함 두 쪽 로그인도 MAIL_ID·MAIL_PW (쇼핑몰 아이디를 메일함에 치지 않게)",
      [x.get("credential") for x in s5[4:6]] == ["MAIL_ID", "MAIL_PW"], [x.get("credential") for x in s5])
srch = rec.finalize([at(st("fill", 0, ph="검색어", value="여름 신상"), "/main"), st("click", 0, "로그인"),
                     at(st("secret", 0, host="shop.example"), "/login"), st("click", 0, "확인")], TODAY, "https://shop.example/")["steps"]
check("다른 쪽의 검색 칸은 아이디로 바꾸지 않는다 - 아이디가 미리 채워진 사이트 (검토 2026-11-03)",
      srch[0].get("credential") is None and srch[0].get("value") == "여름 신상", srch[0])
check("안쪽 프레임이 다르면 예전처럼 같은 화면이 아니다",
      not rec.same_screen({"page": 0, "frame": {"main": False, "name": "a", "path": "/x"}}, {"page": 0, "frame": {"main": False, "name": "b", "path": "/x"}}))

print("실패: " + (", ".join(fails) if fails else "없음"))
sys.exit(1 if fails else 0)
