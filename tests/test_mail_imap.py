# -*- coding: utf-8 -*-
"""메일에서 엑셀 받기 (IMAP) - 설계 11절. 가짜 IMAP 서버(tests/fake_imap.py)로만, 실제 메일함에 접속하지 않는다.
  규칙(보낸 사람·제목 시작·들어 있는 말·빼는 말·기간 경계·안 읽음), 한글 머리글(UTF-8·EUC-KR·RFC 2231·이름 없는 첨부),
  기억(두 번 돌려도 한 번·하나 실패하면 기억 안 함·90일 지난 것 지움), 읽음 표시, 실패 까닭, 로그, 규칙 검사, 금지 명령
    .venv\\Scripts\\python.exe tests\\test_mail_imap.py
"""
import base64
import datetime as dt
import email.policy
import email.utils
import json
import os
import re
import socket
import sys
import tempfile
import time
from email.message import EmailMessage

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import mail_imap as mi  # noqa: E402
from fake_imap import PASSWORD, FakeIMAP  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(("통과 " if ok else "실패 ") + name + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def raises(fn, *a, **kw):
    """fn 이 낸 예외 (없으면 None)."""
    try:
        fn(*a, **kw)
    except Exception as e:
        return e
    return None


NOW = dt.datetime(2026, 10, 22, 10, 0)
TODAY = NOW.replace(hour=0)
BODY = "본문비밀내용"
XLSX = ("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def mail(sender, subject, atts, raw_subject=None, enc_names=None):
    """메일 bytes (CRLF). raw_subject/enc_names 로 머리글을 bytes 그대로 바꿔 넣는다 (EUC-KR encoded-word)."""
    m = EmailMessage()
    m["From"], m["To"] = sender, "tester@example.com"
    m["Subject"] = "SUBJ-PLACEHOLDER" if raw_subject else subject
    m["Message-ID"] = email.utils.make_msgid()
    m.set_content(BODY)
    for name, data in atts:
        m.add_attachment(data, *(XLSX if not name or name.endswith(".xlsx") else ("application", "octet-stream")),
                         **({"filename": name} if name else {}))
    raw = m.as_bytes(policy=email.policy.SMTP)
    if raw_subject:
        raw = raw.replace(b"SUBJ-PLACEHOLDER", raw_subject)
    for k, v in (enc_names or {}).items():
        raw = raw.replace(k.encode(), v)
    return raw


def euckr_word(s):
    return b"=?euc-kr?B?" + base64.b64encode(s.encode("euc-kr")) + b"?="


# ---- 1. 규칙 (순수) ----
R = mi.check_rules({"subject_prefix": ">>>"})
check("기본값: 모두·오늘·xlsx/xls·20통·읽음 표시 끔 (csv 뺌 - BugBuster I6)",
      (R["unseen_only"], R["days"], R["exts"], R["max"], R["mark_seen"], R["mailbox"], R["warn"]) == (False, 0, ["xlsx", "xls"], 20, False, "INBOX", ""), R)
check("업로드 못 하는 종류(csv)를 넣으면 알린다 (거절은 안 함)", "csv" in mi.check_rules({"subject_prefix": ">", "exts": "xlsx, csv"})["warn"])
check("제목 시작 - 전각 '＞＞＞' 도 맞음", mi.matches(R, "a@b.c", "＞＞＞ 주문", NOW, NOW))
check("제목 시작 - 'RE: >>>' 는 안 맞음", not mi.matches(R, "a@b.c", "RE: >>> 주문", NOW, NOW))
check("기간 경계 - 어제 23:59 는 빠짐", not mi.matches(R, "a", ">>>", TODAY - dt.timedelta(minutes=1), NOW))
check("기간 경계 - 오늘 00:00 은 맞음", mi.matches(R, "a", ">>>", TODAY, NOW))
check("최근 1일이면 어제 23:59 도 맞음", mi.matches(mi.check_rules({"subject_prefix": ">>>", "days": 1}), "a", ">>>", TODAY - dt.timedelta(minutes=1), NOW))
Rs = mi.check_rules({"senders": "Order@Shop.co.kr, 없는사람"})
check("보낸 사람 - 대소문자 무시, 하나라도 맞으면", mi.matches(Rs, "주문팀 <order@shop.co.kr>", "아무 제목", NOW, NOW)
      and not mi.matches(Rs, "x <x@y.z>", "아무 제목", NOW, NOW))
check("보낸 사람 - 이름으로도", mi.matches(mi.check_rules({"senders": ["주문 팀"]}), "주문팀 <o@s.kr>", "t", NOW, NOW))
check("보낸 사람 - @ 든 조건은 주소로만, 이름에 흉내 낸 주소는 안 맞음 (BugBuster I10)",
      not mi.matches(Rs, '"order@shop.co.kr" <evil@x.com>', "t", NOW, NOW) and not mi.matches(Rs, "order@shop.co.kr 담당 <evil@x.com>", "t", NOW, NOW)
      and mi.matches(mi.check_rules({"senders": "@shop.co.kr"}), "주문팀 <order@shop.co.kr>", "t", NOW, NOW))
check("기간: 첫 실행은 규칙대로, 그 뒤는 마지막 실행 날부터, 최대 30일 (BugBuster I8)",
      (mi._days(R, {}, NOW), mi._days(R, {mi.LAST_RUN: "2026-10-20"}, NOW), mi._days(R, {mi.LAST_RUN: "2026-08-01"}, NOW),
       mi._days(dict(R, days=5), {mi.LAST_RUN: "2026-10-22"}, NOW), mi._days(R, {mi.LAST_RUN: "이상한 값"}, NOW)) == (0, 2, 30, 5, 0))
Rh = mi.check_rules({"subject_has": "주문, 엑셀", "subject_not": "RE:,회신"})
check("들어 있는 말은 모두, 빼는 말은 하나라도",
      mi.matches(Rh, "a", "[주문] 엑셀 보냄", NOW, NOW) and not mi.matches(Rh, "a", "[주문] 보냄", NOW, NOW)
      and not mi.matches(Rh, "a", "re: [주문] 엑셀", NOW, NOW) and not mi.matches(Rh, "a", "[주문] 엑셀 회신", NOW, NOW))

# ---- 7. 규칙 검사 ----
check("규칙이 비면 거절", isinstance(raises(mi.check_rules, {}), ValueError))
check("위험 확장자(xlsm) 거절", isinstance(raises(mi.check_rules, {"subject_prefix": ">", "exts": "xlsx, .XLSM"}), ValueError))
check("exe 거절", isinstance(raises(mi.check_rules, {"subject_prefix": ">", "exts": ["exe"]}), ValueError))
check("기간 31·최대 0·최대 51 거절", all(isinstance(raises(mi.check_rules, {"subject_prefix": ">", **kw}), ValueError)
                                   for kw in ({"days": 31}, {"max": 0}, {"max": 51})))
check("쉼표 글 → 목록, 확장자 다듬기", mi.check_rules({"senders": "a, b", "exts": ".XLSX, csv"})["exts"] == ["xlsx", "csv"]
      and mi.check_rules({"senders": "a, b"})["senders"] == ["a", "b"])
check("보낸 사람 가리기", mi.mask_sender("주문팀 <order@shop.co.kr>") == "or***@shop.co.kr", mi.mask_sender("주문팀 <order@shop.co.kr>"))
odd = [mi.mask_sender(a) for a in ("order@shop.co.kr>", "주문팀 order@shop.co.kr", '"order@shop.co.kr" <order@shop.co.kr>', "<order@shop.co.kr")]
check("보낸 사람 가리기 - 어떤 꼴이어도 전체 주소를 싣지 않는다 (BugBuster M14)", not any("order@" in x for x in odd), odd)
ks = lambda s: b"=?ks_c_5601-1987?B?" + base64.b64encode(s.encode("cp949")) + b"?="     # noqa: E731  아웃룩 꼴
rawks = mail("a <a@b.kr>", None, [("KSNAME.xlsx", b"k")], raw_subject=ks(">>> 뷁 주문"), enc_names={"KSNAME.xlsx": ks("똠방.xlsx")})
mks = email.message_from_bytes(rawks, policy=email.policy.default)
got_ks = ([n for n, _ in mi._attachments(mks, R, 1)], mi._hdr(mks, "Subject"))
check("ks_c_5601-1987 의 cp949 확장 글자(똠·뷁) 이름·제목 (BugBuster M16)", got_ks == (["똠방.xlsx"], ">>> 뷁 주문"), got_ks)
check("알려진 서버", mi.guess_server("Someone@NAVER.com") == ("imap.naver.com", 993, "ssl") and mi.guess_server("a@x.kr") is None)
check("한글 메일함 이름 (RFC 3501 예)", mi._mutf7("~peter/mail/台北/日本語") == "~peter/mail/&U,BTFw-/&ZeVnLIqe-", mi._mutf7("~peter/mail/台北/日本語"))
raw8 = (b"From: a@b\r\nSubject: x\r\nMIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary=BB\r\n\r\n--BB\r\n"
        b"Content-Type: application/octet-stream\r\nContent-Disposition: attachment; filename=\"" + "주문서.xlsx".encode("cp949")
        + b"\"\r\nContent-Transfer-Encoding: base64\r\n\r\neDE=\r\n--BB--\r\n")
got8 = [n for n, _ in mi._attachments(email.message_from_bytes(raw8, policy=email.policy.default), R, 9)]
check("8비트 그대로 온 CP949 파일 이름", got8 == ["주문서.xlsx"], got8)
check("위험한 글자·경로 뺌", mi._safe_name('..\\x/a<b>:c?.xlsx') == "a_b__c_.xlsx", mi._safe_name('..\\x/a<b>:c?.xlsx'))
src = open(os.path.join(ROOT, "mail_imap.py"), encoding="utf-8").read()
check("코드에 지우기·옮기기 명령이 없다", not re.search(r"\.(expunge|delete|move|copy)\(|\b(EXPUNGE|DELETE|MOVE|COPY|CLOSE)\b", src))

# ---- 가짜 서버 ----
mi.CMD_TIMEOUT = 5
fake = FakeIMAP()
try:
    u1 = fake.add(mail("주문팀 <order@shop.co.kr>", ">>> 주문 엑셀 1", [("주문.xlsx", b"x1"), ("readme.txt", b"t")]), TODAY + dt.timedelta(hours=9))
    raw2 = mail("발주 <po@vendor.kr>", None, [(None, b"x2"), ("ENCNAME.xls", b"c2")], raw_subject=euckr_word(">>> 주문 2"),
                enc_names={"ENCNAME.xls": euckr_word("발주.xls")})
    u2 = fake.add(raw2, TODAY + dt.timedelta(hours=8))
    u3 = fake.add(mail("a <a@b.kr>", ">>> 주문 3", [("c.xlsx", b"x3")]), TODAY - dt.timedelta(minutes=1))
    u4 = fake.add(mail("a <a@b.kr>", "공지", [("d.xlsx", b"x4")]), TODAY + dt.timedelta(hours=5))
    u5 = fake.add(mail("a <a@b.kr>", ">>> 주문 5", [("a.xlsx", b"x5")]), TODAY + dt.timedelta(hours=7), seen=True)
    u6 = fake.add(mail("a <a@b.kr>", ">>> 주문 6", [("ok.xlsx", b"x6"), ("bad.xlsx", b"x7")]), TODAY + dt.timedelta(hours=6))
    check("시험 메일이 RFC 2231 이름·EUC-KR encoded-word 를 실제로 담음",
          b"filename*=" in fake.boxes["INBOX"][0]["raw"] and b"=?euc-kr?B?" in raw2)
    S = fake.server()
    work = tempfile.mkdtemp(prefix="mail_imap_test_")
    flags0 = fake.flags()

    # ---- 찾아보기 ----
    n_cmd = len(fake.commands)
    items = mi.find(S, {"subject_prefix": ">>>"}, now=NOW)
    check("찾아보기: 오늘·'>>>' 만, 최근 것부터", [i["uid"] for i in items] == [u1, u2, u5, u6], [i["uid"] for i in items])
    att = {i["uid"]: i["attachments"] for i in items}
    check("RFC 2231 한글 파일 이름, 맞지 않는 확장자 뺌", att.get(u1) == ["주문.xlsx"], att.get(u1))
    check("EUC-KR 제목·파일 이름, 이름 없는 첨부", att.get(u2) == ["첨부_2_1.xlsx", "발주.xls"]
          and items[1]["subject"] == ">>> 주문 2", (att.get(u2), items[1]["subject"]))
    check("찾아보기는 표시를 바꾸지 않고 파일도 안 만든다", fake.flags() == flags0 and not os.listdir(work))
    cmds = fake.commands[n_cmd:]
    check("찾아보기는 EXAMINE", any(" EXAMINE " in c for c in cmds) and not any(" SELECT " in c for c in cmds), cmds)
    check("안 읽은 것만", [i["uid"] for i in mi.find(S, {"subject_prefix": ">>>", "unseen_only": True}, now=NOW)] == [u1, u2, u6])
    check("한 번에 최대", [i["uid"] for i in mi.find(S, {"subject_prefix": ">>>", "max": 2}, now=NOW)] == [u1, u2])
    check("최근 1일", [i["uid"] for i in mi.find(S, {"subject_prefix": ">>>", "days": 1}, now=NOW)] == [u1, u2, u5, u6, u3])
    check("보낸 사람 규칙 (서버에서)", [i["uid"] for i in mi.find(S, {"senders": "PO@vendor.kr"}, now=NOW)] == [u2])
    check("빼는 말 규칙 (서버에서)", [i["uid"] for i in mi.find(S, {"subject_prefix": ">>>", "subject_not": "엑셀"}, now=NOW)] == [u2, u5, u6])

    # ---- 받기 + 기억 ----
    dest, mem = os.path.join(work, "excel"), os.path.join(work, "data", "메일", "PRESET1.json")
    os.makedirs(os.path.dirname(mem))
    with open(mem, "w", encoding="utf-8") as f:
        json.dump({"old@x": "2026-07-01", "recent@x": "2026-10-01"}, f)
    real_save = mi._save

    def flaky_save(path, data):
        if "bad" in os.path.basename(path):
            raise OSError(28, "디스크 공간 부족")
        real_save(path, data)

    lines = []
    mi._save = flaky_save
    n_cmd = len(fake.commands)
    r1 = mi.fetch(S, {"subject_prefix": ">>>"}, dest, "P1", mem, log=lines.append, now=NOW)
    mi._save = real_save
    got = sorted(os.path.basename(p) for p in r1["saved"])
    check("받기: 맞는 첨부만 (사이트코드)이름 으로", got == sorted(["(P1)주문.xlsx", "(P1)첨부_2_1.xlsx", "(P1)발주.xls", "(P1)a.xlsx", "(P1)ok.xlsx"]), got)
    check("받은 내용 그대로", open(os.path.join(dest, "(P1)주문.xlsx"), "rb").read() == b"x1")
    check("실패한 첨부는 까닭과 함께", r1["mails"] == 4 and any(n == "bad.xlsx" for n, _ in r1["skipped"]), r1)
    m1 = json.load(open(mem, encoding="utf-8"))
    keys6 = re.search(rb"Message-ID: (<[^>]+>)", fake.boxes["INBOX"][u6 - 1]["raw"])[1].decode()
    check("첨부 하나라도 실패한 메일은 기억 안 함", len(m1) == 4 and keys6 not in m1, m1)
    check("90일 지난 기억은 지움", "old@x" not in m1 and "recent@x" in m1, m1)
    check("읽음 표시 끔: 서버 플래그 그대로", fake.flags() == flags0, fake.flags())
    cmds = fake.commands[n_cmd:]
    check("받기는 EXAMINE, 금지 명령 없음, 모두 PEEK",
          any(" EXAMINE " in c for c in cmds) and not any(re.search(r"\b(STORE|EXPUNGE|DELETE|MOVE|COPY|SELECT)\b", c) for c in cmds)
          and not any("BODY[" in c for c in cmds), cmds)
    log = "\n".join(lines)
    check("로그에 비밀번호·본문·전체 주소가 없다", PASSWORD not in log and BODY not in log and "order@shop.co.kr" not in log, log)
    check("로그에 가린 주소·첨부 이름", "or***@shop.co.kr" in log and "(P1)주문.xlsx" in log, log)

    r2 = mi.fetch(S, {"subject_prefix": ">>>"}, dest, "P1", mem, log=lines.append, now=NOW)
    got = sorted(os.path.basename(p) for p in r2["saved"])
    check("다시 돌리면 못 받은 메일만, 같은 이름은 (1)", r2["mails"] == 1 and got == ["(P1)bad.xlsx", "(P1)ok (1).xlsx"], (r2, got))
    check("이제 기억함", keys6 in json.load(open(mem, encoding="utf-8")))
    r3 = mi.fetch(S, {"subject_prefix": ">>>"}, dest, "P1", mem, log=lines.append, now=NOW)
    check("세 번째는 대상 없음", r3["mails"] == 0 and not r3["saved"], r3)
    check("찾아보기에 처리함 표시", all(i["done"] for i in mi.find(S, {"subject_prefix": ">>>"}, mem, now=NOW)))
    mi.forget(mem)
    check("기억 지우기", not os.path.exists(mem))

    # ---- 4. 읽음 표시 켬 ----
    mi._save = flaky_save
    n_cmd = len(fake.commands)
    mi.fetch(S, {"subject_prefix": ">>>", "mark_seen": True}, os.path.join(work, "seen"), "P2", os.path.join(work, "m2.json"),
             log=lines.append, now=NOW)
    mi._save = real_save
    fl = fake.flags()
    check("읽음 표시 켬: 다 받은 메일만 \\Seen", fl[u1] == fl[u2] == fl[u5] == ["\\Seen"] and fl[u6] == [] and fl[u3] == fl[u4] == [], fl)
    cmds = fake.commands[n_cmd:]
    check("켬이면 SELECT, STORE 는 받은 메일만", any(" SELECT " in c for c in cmds)
          and sorted(c.split()[3] for c in cmds if " STORE " in c) == sorted(map(str, (u1, u2, u5))), cmds)

    # ---- 5. 실패 까닭 ----
    def why(server, rules=None):
        e = raises(mi.find, server, rules or {"subject_prefix": ">>>"}, now=NOW)
        return str(e) if isinstance(e, mi.MailError) else repr(e)

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        dead = s.getsockname()[1]
    check("연결 거부", why({**S, "port": dead}) == mi.CONNECT_FAIL)
    cert = why({k: v for k, v in S.items() if k != "context"})
    check("믿지 못할 인증서는 연결하지 않고 인증서 탓이라고 알린다 (BugBuster K14)", cert.startswith(mi.CERT_FAIL) and "certificate" in cert, cert)
    check("암호화 없는 연결은 거절", "암호화" in why({**S, "security": "plain"}))
    bad = why({**S, "password": "wrong-pw"})
    check("로그인 거부", bad == mi.LOGIN_FAIL and "wrong-pw" not in bad, bad)
    check("없는 메일함", why(S, {"subject_prefix": ">>>", "mailbox": "없는함"}) == "메일함 '없는함'이(가) 없습니다.")
    check("STARTTLS 로도", [i["uid"] for i in mi.find(fake.server("starttls"), {"subject_prefix": ">>>", "max": 1}, now=NOW)] == [u1])
    fake.boxes["RO"] = []
    fake.readonly.add("RO")
    ro = str(raises(mi.fetch, S, {"subject_prefix": ">>>", "mailbox": "RO", "mark_seen": True}, os.path.join(work, "ro"), "P", os.path.join(work, "ro.json"),
                    log=lines.append, now=NOW))
    check("읽음 표시를 켠 채 읽기 전용 메일함이면 그 까닭으로 (BugBuster L11)", "읽기 전용" in ro, ro)

    # ---- 6. BugBuster I7·I8·I9·M15·K16 (메일함을 따로 써 위 시험과 섞이지 않게) ----
    Y22 = TODAY - dt.timedelta(hours=2)        # 어제 22:00
    for subj, when in ((">>> 나", TODAY + dt.timedelta(hours=9)), (">>> 가", Y22), (">>> 다", TODAY + dt.timedelta(hours=8))):
        fake.add(mail("a <a@b.kr>", subj, [(subj[-1] + ".xlsx", b"z")]), when, box="B2")
    rb = {"subject_prefix": ">>>", "mailbox": "B2"}
    f1 = mi.fetch(S, rb, os.path.join(work, "b2a"), "P9", os.path.join(work, "b2a.json"), log=lines.append, now=NOW)
    check("첫 실행은 오늘 것만 (어제 22:00 메일 빠짐)", [os.path.basename(p) for p in f1["saved"]] == ["(P9)다.xlsx", "(P9)나.xlsx"], f1)
    check("다 처리하면 마지막 실행 날을 기억", json.load(open(os.path.join(work, "b2a.json"), encoding="utf-8")).get(mi.LAST_RUN) == "2026-10-22")
    mb = os.path.join(work, "b2b.json")
    with open(mb, "w", encoding="utf-8") as f:
        json.dump({mi.LAST_RUN: "2026-10-21"}, f)
    f2 = mi.fetch(S, dict(rb, max=1), os.path.join(work, "b2b"), "P9", mb, log=lines.append, now=NOW)
    check("한 번에 최대를 넘겨 남은 메일이 있으면 마지막 실행 날을 옮기지 않는다",
          len(f2["saved"]) == 1 and json.load(open(mb, encoding="utf-8")).get(mi.LAST_RUN) == "2026-10-21", f2)
    f3 = mi.fetch(S, rb, os.path.join(work, "b2b"), "P9", mb, log=lines.append, now=NOW)
    names3 = [os.path.basename(p) for p in f3["saved"]]
    check("다음 실행은 마지막 실행 날(어제)부터 - 어제 저녁 메일도, 오래된 것부터 저장 (I8·I7)", names3 == ["(P9)가.xlsx", "(P9)다.xlsx"], names3)
    check("파일 시각 = 메일 시각 (I7)", abs(os.path.getmtime(f3["saved"][0]) - Y22.timestamp()) < 2
          and os.path.getmtime(f3["saved"][0]) < os.path.getmtime(f3["saved"][1]))

    fake.add(mail("a <a@b.kr>", ">>> 큰 메일", [("큰.xlsx", b"z" * 2000)]), TODAY + dt.timedelta(hours=1), box="B3")
    fake.add(mail("a <a@b.kr>", ">>> 첨부 없음", []), TODAY + dt.timedelta(hours=2), box="B3")
    real_max, mi.MAX_SIZE = mi.MAX_SIZE, 1000
    mb3 = os.path.join(work, "b3.json")
    f4 = mi.fetch(S, dict(rb, mailbox="B3"), os.path.join(work, "b3"), "P9", mb3, log=lines.append, now=NOW)
    f5 = mi.fetch(S, dict(rb, mailbox="B3"), os.path.join(work, "b3"), "P9", mb3, log=lines.append, now=NOW)
    mi.MAX_SIZE = real_max
    check("50MB 넘는 메일은 까닭과 함께 건너뛰고 기억한다 - 다음엔 대상이 아님 (M15)",
          f4["skipped"] == [(">>> 큰 메일", mi.TOO_BIG)] and not f4["saved"] and f5["mails"] == 0, (f4, f5))
    check("받을 첨부 없는 메일 수를 따로 센다 (I9)", f4["no_attach"] == 1, f4)

    fake.add(b"Date: " + email.utils.format_datetime(NOW.astimezone().replace(hour=8)).encode() + b"\r\n"
             + mail("a <a@b.kr>", ">>> 시각 머리글", [("t.xlsx", b"t")]), NOW, box="B4", idate='"bad-date"')
    fake.add(mail("a <a@b.kr>", ">>> 시각 없음", [("u.xlsx", b"u")]), NOW, box="B4", idate='"bad-date"')
    n_log = len(lines)
    f6 = mi.fetch(S, dict(rb, mailbox="B4"), os.path.join(work, "b4"), "P9", os.path.join(work, "b4.json"), log=lines.append, now=NOW)
    check("INTERNALDATE 를 못 읽으면 Date 머리글로, 그것도 없으면 건너뛰고 로그 (K16)",
          [os.path.basename(p) for p in f6["saved"]] == ["(P9)t.xlsx"] and any("메일 시각을 읽지 못해" in x for x in lines[n_log:]), (f6, lines[n_log:]))
    fake.stall, mi.CMD_TIMEOUT = True, 1
    t0 = time.time()
    check("시간 넘김", why(S) == mi.NO_RESPONSE and time.time() - t0 < 5, time.time() - t0)
    fake.stall = False
    check("가짜 서버에 금지 명령이 한 번도 오지 않음",
          not any(re.search(r"\b(EXPUNGE|DELETE|MOVE|COPY)\b", c, re.I) for c in fake.commands))
finally:
    fake.close()

print("실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
