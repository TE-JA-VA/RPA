# -*- coding: utf-8 -*-
"""스탠드얼론 ④ Task 1 - 짝지은 휴대폰 표·요청 서명·인증번호 자리 검사와 2분 만료 (계획 2026-11-23-standalone-4-phone).
포트(사내망)는 열지 않는다 - 계획 ① 의 로컬 서버(127.0.0.1)와 local_phone.Service 의 표·규칙만 본다. 시계는 가짜.
    D:/AX/RPA/.venv/Scripts/python.exe tests/test_phone_core.py
"""
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
import local_server  # noqa: E402
import local_store  # noqa: E402
import local_phone  # noqa: E402

fails = []
TMP = tempfile.mkdtemp(prefix="rpa_phone_core_")
LIC = {"edition": "standalone", "company": "시험상사", "cid": "c1", "pc_id": "p1", "issued": "2026-11-23",
       "modules": {}, "features": {}, "limits": {}}


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def raises(exc, fn, *a, **k):
    try:
        fn(*a, **k)
    except exc as e:
        return str(e) or True
    except Exception as e:
        return False and e
    return False


class Clock:
    def __init__(self, t=1795000000.0):
        self.t = t

    def __call__(self):
        return self.t


srv = runs = svc2 = None
try:
    # ------------------------------------------------------------------------------------------
    print("열쇠·서명")
    S1, S2 = bytes(range(32)), bytes(range(1, 33))
    R1, R2 = bytes(range(32, 64)), bytes(range(33, 65))
    pk = local_phone.pair_key(S1)
    check("pair_key = sha256('ap1 phone pair\\n' + 짝 열쇠) hex", pk == hashlib.sha256(b"ap1 phone pair\n" + S1).hexdigest()
          and pk == local_phone.pair_key(S1) and pk != local_phone.pair_key(S2) and re.fullmatch(r"[0-9a-f]{64}", pk))
    sk = local_phone.sign_key(S1, R1)
    check("sign_key = sha256('ap1 phone key\\n' + 짝 열쇠 + 휴대폰 무작위)", sk == hashlib.sha256(b"ap1 phone key\n" + S1 + R1).hexdigest()
          and sk == local_phone.sign_key(S1, R1) and sk != local_phone.sign_key(S1, R2) and sk != pk)
    base = ("ph_0a1b2c3d", "GET", "/phone/v1/request", 1795000000000, "0" * 16, b"")
    m0 = local_phone.request_mac(sk, *base)
    want = local_store._mac(sk, ["ap1", "phone-req", "ph_0a1b2c3d", "GET", "/phone/v1/request", "1795000000000", "0" * 16,
                                 hashlib.sha256(b"").hexdigest()])
    check("request_mac 의 조각과 차례 (local_store._mac)", m0 == want)
    changed = [("ph_0a1b2c3e",) + base[1:], base[:1] + ("POST",) + base[2:], base[:2] + ("/phone/v1/code",) + base[3:],
               base[:3] + (1795000000001,) + base[4:], base[:4] + ("1" * 16,) + base[5:], base[:5] + (b"{}",)]
    check("조각 하나만 달라도 서명이 달라진다 (번호·방법·경로·시각·nonce·본문)",
          all(local_phone.request_mac(sk, *c) != m0 for c in changed) and local_phone.request_mac(pk, *base) != m0)
    check("response_mac 의 조각", local_phone.response_mac(sk, "0" * 16, 200, b"{}")
          == local_store._mac(sk, ["ap1", "phone-res", "0" * 16, "200", hashlib.sha256(b"{}").hexdigest()]))

    # ------------------------------------------------------------------------------------------
    print("발신번호 (parse_senders)")
    check("'1588-1234, 0212345678' → 두 개", local_phone.parse_senders("1588-1234, 0212345678") == ["15881234", "0212345678"])
    check("쉼표·빈칸·; 와 괄호, 겹친 것 하나로", local_phone.parse_senders("(02)1234-5678;0212345678  1588 ") == ["0212345678", "1588"])
    check("목록도 받는다·빈 것은 []", local_phone.parse_senders(["010-1234-5678"]) == ["01012345678"] and local_phone.parse_senders("") == []
          and local_phone.parse_senders(None) == [])
    check("글자 섞인 것은 관리 화면과 같은 글", raises(ValueError, local_phone.parse_senders, "1588, 12a4") == "발신번호는 숫자 3~15자리여야 합니다: 12a4")
    check("21개는 '20개까지'", raises(ValueError, local_phone.parse_senders, ",".join(str(1000 + i) for i in range(21)))
          == "발신번호는 20개까지 입력할 수 있습니다.")

    # ------------------------------------------------------------------------------------------
    print("짝지은 휴대폰 표 (Phones)")
    ppath = os.path.join(TMP, "p1", local_phone.PHONES_NAME)
    phones = local_phone.Phones(ppath)
    phones.add("ph_00000001", "김OO 휴대폰", "김OO", ["15881234"], key="k" * 64, fp="a" * 64, os="android", app_version="1.0", device="Galaxy")
    phones.add("ph_00000002", "공용", "", [], key="j" * 64, fp="b" * 64, os="ios", app_version="1.0", device="iPhone")
    again = local_phone.Phones(ppath)
    check("넣고 다시 열어도 남는다", again.count() == 2 and again.get("ph_00000001")["key"] == "k" * 64)
    lst = again.list(fp_now="a" * 64)
    check("list() 에 열쇠·지문이 없다", lst and all("key" not in p and "fp" not in p for p in lst), repr(lst))
    check("list() 의 칸", set(lst[0]) == {"id", "label", "owner", "senders", "paired_at", "last_seen", "os", "app_version", "device", "stale"})
    check("stale = 짝지을 때의 지문과 지금 지문이 다르다", {p["id"]: p["stale"] for p in lst} == {"ph_00000001": False, "ph_00000002": True})
    pub = again.public()
    check("public() - 일반 버전 meta/companies/<cid>/phones 꼴 (senders {번호: true}, 비면 칸 없음)",
          pub == {"ph_00000001": {"label": "김OO 휴대폰", "owner": "김OO", "senders": {"15881234": True}},
                  "ph_00000002": {"label": "공용", "owner": ""}}, repr(pub))
    check("public()·list() 어디에도 열쇠 글이 없다", "k" * 64 not in json.dumps(pub) + json.dumps(lst))
    again.seen("ph_00000001")
    check("seen → last_seen (메모리에만)", isinstance({p["id"]: p for p in again.list()}["ph_00000001"]["last_seen"], int)
          and "last_seen" not in json.load(open(ppath, encoding="utf-8"))["phones"]["ph_00000001"])
    again.update("ph_00000002", label="공용 휴대폰", senders=["0212345678"])
    check("update", local_phone.Phones(ppath).get("ph_00000002")["label"] == "공용 휴대폰"
          and local_phone.Phones(ppath).get("ph_00000002")["senders"] == ["0212345678"])
    check("remove → True, 없는 것은 False", again.remove("ph_00000002") is True and again.remove("ph_00000002") is False and again.count() == 1)
    for i in range(19):
        again.add(f"ph_1{i:07d}", f"폰{i}", "", [], key="x" * 64, fp="a" * 64, os="android", app_version="1", device="d")
    check("21번째는 ValueError", raises(ValueError, again.add, "ph_ffffffff", "넘침", "", [], key="x" * 64, fp="a" * 64, os="android",
                                        app_version="1", device="d") == "휴대폰은 20대까지 등록할 수 있습니다." and again.count() == 20)
    check("파일 자리는 phones.json", local_phone.PHONES_NAME == "phones.json" and os.path.isfile(ppath)
          and not [n for n in os.listdir(os.path.dirname(ppath)) if n.endswith(".tmp")])
    bpath = os.path.join(TMP, "broken", "phones.json")
    os.makedirs(os.path.dirname(bpath))
    with open(bpath, "w", encoding="utf-8") as f:
        f.write('{"v": 1, "phones": {')
    broken = local_phone.Phones(bpath)
    check("깨진 파일 → 빈 표 + .broken", broken.count() == 0 and os.path.isfile(bpath + ".broken"))

    # ------------------------------------------------------------------------------------------
    print("짝짓기 (Pairing)")
    clk = Clock()
    pr = local_phone.Pairing(clock=clk)
    check("처음은 none", pr.state() == {"state": "none"}, repr(pr.state()))
    got = pr.start("김OO 휴대폰", "김OO", ["15881234"])
    check("start → 번호(ph_ + hex 8)·짝 열쇠 32바이트·300초", re.fullmatch(r"ph_[0-9a-f]{8}", got["phone_id"]) and len(got["secret"]) == 32
          and got["expires_at"] == clk.t + 300)
    st = pr.state()
    check("waiting · left_sec 300 (state 에 짝 열쇠 없음)", st == {"state": "waiting", "left_sec": 300}, repr(st))
    check("claim - 살아 있는 것만", (pr.claim(got["phone_id"]) or {}).get("secret") == got["secret"] and pr.claim("ph_00000000") is None)
    clk.t += 301
    check("301초 뒤 claim None · expired", pr.claim(got["phone_id"]) is None and pr.state()["state"] == "expired")
    clk.t += 61
    check("expired 는 60초 동안만 보이고 none", pr.state() == {"state": "none"})
    a = pr.start("하나", "", [])
    b = pr.start("둘", "", [])
    check("다시 시작하면 앞의 것은 못 쓴다", pr.claim(a["phone_id"]) is None and pr.claim(b["phone_id"]) is not None)
    for _ in range(4):
        pr.fail()
    check("틀림 4번까지는 그대로", pr.claim(b["phone_id"]) is not None)
    pr.fail()
    check("틀림 5번이면 취소", pr.claim(b["phone_id"]) is None and pr.state()["state"] == "none")
    c = pr.start("셋", "", [])
    pr.done({"id": c["phone_id"], "label": "셋", "os": "android", "device": "Fake"})
    st = pr.state()
    check("done → paired (기기 이름) 60초", st == {"state": "paired", "phone": {"id": c["phone_id"], "label": "셋", "os": "android", "device": "Fake"}}
          and pr.claim(c["phone_id"]) is None, repr(st))
    clk.t += 61
    check("60초 뒤 none", pr.state() == {"state": "none"})
    d = pr.start("넷", "", [])
    pr.cancel()
    check("cancel → none·claim None", pr.state() == {"state": "none"} and pr.claim(d["phone_id"]) is None)

    # ------------------------------------------------------------------------------------------
    print("요청 열기 검사 (otp_request_ok)")
    REQ = {"req_id": "req_0123456789abcdef", "site": "가나몰", "pcId": "p1", "senders": {"15881234": True}}
    ph = {"senders": ["15881234", "0212345678"]}
    check("짝지은 휴대폰 → True", local_server.otp_request_ok(REQ, LIC, ph) is True)
    check("phone=None → False (짝짓지 않은 휴대폰)", local_server.otp_request_ok(REQ, LIC, None) is False
          and local_server.otp_request_ok(REQ, LIC) is False)
    check("빈 senders → False", local_server.otp_request_ok(dict(REQ, senders={}), LIC, ph) is False
          and local_server.otp_request_ok({k: v for k, v in REQ.items() if k != "senders"}, LIC, ph) is False)
    check("허용 밖 발신번호 → False", local_server.otp_request_ok(dict(REQ, senders={"15990000": True}), LIC, ph) is False)
    check("허용 목록이 없는 휴대폰은 숫자면 된다", local_server.otp_request_ok(dict(REQ, senders={"15990000": True}), LIC, {"senders": []}) is True)
    check("req_id 7자 → False, 꼴 틀림 False", local_server.otp_request_ok(dict(REQ, req_id="req_abc"), LIC, ph) is False
          and local_server.otp_request_ok(dict(REQ, req_id="req 0123456789"), LIC, ph) is False)
    check("site 101자 → False", local_server.otp_request_ok(dict(REQ, site="가" * 101), LIC, ph) is False)

    # ------------------------------------------------------------------------------------------
    print("인증번호 자리 (Desk)")
    clk = Clock()
    store = local_server.Store(os.path.join(TMP, "desk", "store.json"), volatile=local_server.VOLATILE)
    dp = local_phone.Phones(os.path.join(TMP, "desk", "phones.json"))
    dp.add("ph_aaaaaaaa", "가", "", ["15881234"], key="k" * 64, fp="a" * 64, os="android", app_version="1", device="d")
    dp.add("ph_bbbbbbbb", "나", "", [], key="j" * 64, fp="a" * 64, os="android", app_version="1", device="d")
    desk = local_phone.Desk(store, dp, LIC, clock=clk)
    A, B = "ph_aaaaaaaa", "ph_bbbbbbbb"
    RQ, CD = f"apps/otp/requests/c1/{A}/current", f"apps/otp/codes/c1/{A}/current"
    GOOD = {"req_id": "req_0123456789abcdef", "code": "482913", "sender": "15881234", "sms_at": 1795000000000}
    check("요청 없음 → 409 no_request", desk.submit(A, GOOD) == (409, "no_request") and desk.open_request(A) is None)
    now_ms = int(clk.t * 1000)
    store.put(RQ, dict(REQ, created_at=now_ms))
    check("열린 요청", (desk.open_request(A) or {}).get("req_id") == REQ["req_id"])
    clk.t += 119.9
    check("119.9초 뒤 열려 있다", desk.open_request(A) is not None)
    clk.t += 0.1
    check("120초 뒤 닫힌다", desk.open_request(A) is None and desk.submit(A, GOOD) == (409, "no_request"))
    clk.t = now_ms / 1000 + 10
    check("req_id 다름 → 409 req_mismatch", desk.submit(A, dict(GOOD, req_id="req_ffffffffffffffff")) == (409, "req_mismatch"))
    check("요청에 없는 발신번호 → 403 sender_not_allowed", desk.submit(A, dict(GOOD, sender="15990000")) == (403, "sender_not_allowed"))
    bad = [dict(GOOD, code="12a456"), dict(GOOD, code="123"), dict(GOOD, code="123456789"), dict(GOOD, code=482913),
           dict(GOOD, body="문자 전체"), {k: v for k, v in GOOD.items() if k != "sms_at"}, dict(GOOD, sender="+821012"),
           dict(GOOD, sms_at="어제"), dict(GOOD, sms_at=True), "482913", None, dict(GOOD, req_id="x")]
    check("꼴 틀림·칸 더 있음(문자 전체)·모자람 → 400 bad_request", all(desk.submit(A, b) == (400, "bad_request") for b in bad),
          repr([desk.submit(A, b) for b in bad]))
    check("거절한 시도는 아무것도 쓰지 않았다", store.get(CD) is None)
    check("성공 → (200, None)", desk.submit(A, GOOD) == (200, None))
    saved = store.get(CD)
    check("쓴 값의 칸이 정확히 다섯 (본문 없음, written_at 은 서버 시각)", set(saved) == {"req_id", "code", "sender", "sms_at", "written_at"}
          and saved["written_at"] == int(clk.t * 1000) and saved["code"] == "482913", repr(saved))
    check("read_code - 요청이 열려 있고 req_id 가 같을 때만", desk.read_code(A) == saved)
    for _ in range(4):
        desk.submit(A, GOOD)
    check("같은 요청에 여섯 번째 → 429 too_many", desk.submit(A, GOOD) == (429, "too_many"))
    # 검토 2026-11-23 Minor 3: 요청이 열리기 전에 받은 (지난) 문자의 번호를 받았다 - 요청보다 30초 넘게 이른 문자는 거절
    opened = int(clk.t * 1000)
    store.put(RQ, dict(REQ, req_id="req_1111111111111111", created_at=opened))
    OLD = dict(GOOD, req_id="req_1111111111111111")
    check("요청보다 31초 이른 문자 → 409 old_sms (쓰지 않는다)", desk.submit(A, dict(OLD, sms_at=opened - 31000)) == (409, "old_sms")
          and (store.get(CD) or {}).get("req_id") != "req_1111111111111111")
    check("요청보다 29초 이른 문자 (시계 오차) → 200", desk.submit(A, dict(OLD, sms_at=opened - 29000)) == (200, None))
    clk.t += 5
    phone_ts = int(clk.t * 1000) - 100000          # 휴대폰 시계가 100초 늦다 - 문자는 요청 4초 뒤 (휴대폰 시계로)
    check("휴대폰 시계가 늦어도 보낸 시각(X-AP-Time)으로 견준다 → 200",
          desk.submit(A, dict(OLD, sms_at=phone_ts - 1000), sent_ms=phone_ts) == (200, None))
    check("… 휴대폰 시계로 요청보다 40초 이른 문자는 409 old_sms",
          desk.submit(A, dict(OLD, sms_at=phone_ts - 45000), sent_ms=phone_ts) == (409, "old_sms"))
    check("거절한 old_sms 는 같은 요청의 횟수를 쓰지 않는다 (성공 둘만 셈)", desk._puts.get((A, "req_1111111111111111")) == 2, repr(desk._puts))
    check("다른 휴대폰의 요청은 못 본다 (Review Focus 8)", desk.open_request(B) is None and desk.submit(B, GOOD) == (409, "no_request")
          and desk.read_code(B) is None)
    store.put(RQ, dict(REQ, req_id="req_9999999999999999", created_at=int(clk.t * 1000)))
    check("요청이 바뀌면 옛 번호는 아무도 못 읽는다", desk.read_code(A) is None)
    store.put(CD, dict(saved, req_id="req_9999999999999999"))
    clk.t += 121
    check("요청이 닫히면 번호도 못 읽는다", desk.read_code(A) is None)
    store.put(f"apps/otp/codes/c1/{B}/current", {"req_id": "req_0000000000000000", "code": "111111"})
    store.put("apps/otp/requests/c1/ph_cccccccc/current", dict(REQ, created_at=int(clk.t * 1000)))     # 짝짓지 않은(지운) 휴대폰
    n = desk.sweep()
    check("sweep - 지난 요청·그 번호·요청 없는 번호·지운 휴대폰 자리를 지운다", n >= 3 and store.get("apps/otp") is None, repr(store.get("apps/otp")))
    store.put(RQ, dict(REQ, created_at=int(clk.t * 1000)))
    check("sweep 은 열린 요청을 두고 간다", desk.sweep() == 0 and store.get(RQ) is not None)
    desk.forget(A)
    check("forget(휴대폰) - 그 휴대폰의 요청·번호 자리를 지운다", store.get(f"apps/otp/requests/c1/{A}") is None)

    # ------------------------------------------------------------------------------------------
    print("휴대폰 표를 쓴 뒤 권한 잠금 (검토 2026-11-23 Minor 4 - 짝짓기 응답이 icacls 여러 번을 기다렸다)")
    import rpa_status  # noqa: E402
    locked, real_lock, real_shipped = [], local_server.lock_key_files, rpa_status.shipped
    local_server.lock_key_files = lambda folder, *a, **k: (time.sleep(1.0), locked.append(folder))
    rpa_status.shipped = lambda: True
    try:
        lsvc = local_phone.Service(os.path.join(TMP, "lock"), local_server.Store(os.path.join(TMP, "lock", "store.json"), volatile=local_server.VOLATILE), LIC)
        began = time.time()
        lsvc.phones.add("ph_12121212", "가", "", [], key="k" * 64, fp="a" * 64, os="android", app_version="1", device="d")
        took = time.time() - began
        check("표를 쓰는 쪽(짝짓기 응답)은 잠금을 기다리지 않는다", took < 0.5, f"{took:.2f}초")
        lsvc.phones.add("ph_34343434", "나", "", [], key="j" * 64, fp="a" * 64, os="android", app_version="1", device="d")
        end = time.time() + 5
        while time.time() < end and len(locked) < 2:
            time.sleep(0.05)
        check("잠금은 따로 돌아 반드시 된다 (겹친 쓰기는 한 번 더)", len(locked) == 2 and locked[0] == os.path.join(TMP, "lock"), repr(locked))
        time.sleep(1.3)
        check("더 쓰지 않으면 더 돌지 않는다", len(locked) == 2, repr(locked))
        local_server.lock_key_files = lambda folder, *a, **k: locked.append("sync")
        locked.clear()
        lsvc.lock_files()
        check("lock_files() 는 그대로 바로 잠근다 (휴대폰 포트를 열 때·서버가 켤 때)", locked == ["sync"], repr(locked))
    finally:
        local_server.lock_key_files, rpa_status.shipped = real_lock, real_shipped

    # ------------------------------------------------------------------------------------------
    print("HTTP (계획 ① 서버 + Service)")
    folder = os.path.join(TMP, "http")
    os.makedirs(folder)
    store = local_server.Store(os.path.join(folder, "store.json"), volatile=local_server.VOLATILE)
    runs = local_server.Runs(os.path.join(folder, "runs.db"))
    AGENT, RELAY = local_server.ensure_keys(folder)
    svc = local_phone.Service(folder, store, LIC)
    PH = "ph_11111111"
    svc.phones.add(PH, "민기 휴대폰", "", ["01012345678"], key="s" * 64, fp="f" * 64, os="android", app_version="1", device="Fake")
    srv = local_server.make_server(store, runs, LIC, (AGENT, RELAY), port=0, folder=folder, phone=svc)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    URL = f"http://127.0.0.1:{srv.server_address[1]}"
    check("srv.phone = Service", srv.phone is svc)
    rc = local_store.Client({"standalone": True, "server_url": URL, "key": RELAY, "role": "relay"})
    got = rc.get("meta/companies/c1/phones")
    check("중계 열쇠의 휴대폰 목록에 열쇠·지문이 없다", got == {PH: {"label": "민기 휴대폰", "owner": "", "senders": {"01012345678": True}}}
          and "s" * 64 not in json.dumps(got) and "f" * 64 not in json.dumps(got), repr(got))
    import fb  # noqa: E402
    import otp_relay  # noqa: E402
    body = {"req_id": "req_0123456789abcdef", "site": "가나몰", "pcId": "p1", "senders": {"01012345678": True}, "created_at": {".sv": "timestamp"}}
    try:
        rc.put("apps/otp/requests/c1/ph_99999999/current", body)
        check("짝짓지 않은 휴대폰으로 요청 PUT 403", False)
    except fb.HttpError as e:
        check("짝짓지 않은 휴대폰으로 요청 PUT 403", e.status == 403)
    rc.put(f"apps/otp/requests/c1/{PH}/current", body)
    check("짝지은 휴대폰은 200 (서버 시각)", isinstance((store.get(f"apps/otp/requests/c1/{PH}/current") or {}).get("created_at"), int))
    store.delete(f"apps/otp/requests/c1/{PH}/current")
    began = time.time()
    try:
        otp_relay.PhoneRelay(rc, "c1", "p1", "ph_99999999", ["010-1234-5678"], "가나몰").open(tick=lambda s: time.sleep(0.05))
        check("PhoneRelay.open - 짝짓지 않은 휴대폰은 5초 안에 DENIED", False)
    except RuntimeError as e:
        check("PhoneRelay.open - 짝짓지 않은 휴대폰은 5초 안에 DENIED", str(e) == otp_relay.DENIED and time.time() - began < 5, str(e))
    relay = otp_relay.PhoneRelay(rc, "c1", "p1", PH, ["010-1234-5678"], "가나몰")
    req_id = relay.open(tick=lambda s: time.sleep(0.05))
    r = svc.desk.submit(PH, {"req_id": req_id, "code": "482913", "sender": "01012345678", "sms_at": int(time.time() * 1000)})
    check("열기 → desk.submit 200", r == (200, None), repr(r))
    check("relay.wait 가 그 번호", relay.wait(req_id, 3, tick=time.sleep) == "482913")
    relay.close(req_id)
    check("close 뒤 두 자리 없음", store.get(f"apps/otp/requests/c1/{PH}") is None and store.get(f"apps/otp/codes/c1/{PH}") is None)
    text = open(os.path.join(folder, "store.json"), encoding="utf-8").read()
    check("store.json 에 번호·열쇠가 없다", "482913" not in text and "s" * 64 not in text and "phones" not in text)
    check("휴대폰이 없는 서버(phone=None)는 요청 403·목록 null", True)
    srv2 = local_server.make_server(store, runs, LIC, (AGENT, RELAY), port=0, folder=folder)
    threading.Thread(target=srv2.serve_forever, daemon=True).start()
    rc2 = local_store.Client({"standalone": True, "server_url": f"http://127.0.0.1:{srv2.server_address[1]}", "key": RELAY, "role": "relay"})
    try:
        rc2.put(f"apps/otp/requests/c1/{PH}/current", body)
        ok403 = False
    except fb.HttpError as e:
        ok403 = e.status == 403
    check("phone 없는 서버: 요청 403, 목록·번호 null", ok403 and rc2.get("meta/companies/c1/phones") is None
          and rc2.get(f"apps/otp/codes/c1/{PH}/current") is None)
    srv2.shutdown()
    srv2.server_close()
    svc.start()
    store.put(f"apps/otp/requests/c1/{PH}/current", dict(REQ, created_at=int(time.time() * 1000) - 200000))
    end = time.time() + 12
    while time.time() < end and store.get(f"apps/otp/requests/c1/{PH}") is not None:
        time.sleep(0.2)
    check("Service 의 5초 고리가 지난 요청을 지운다", store.get(f"apps/otp/requests/c1/{PH}") is None)
    svc.stop()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    for s in (srv,):
        try:
            if s is not None:
                s.shutdown()
                s.server_close()
        except Exception:
            pass
    try:
        if runs is not None:
            runs.close()
    except Exception:
        pass
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n실패: {len(fails)}" + (f" ({', '.join(fails)})" if fails else ""))
sys.exit(1 if fails else 0)
