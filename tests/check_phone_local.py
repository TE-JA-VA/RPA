# -*- coding: utf-8 -*-
"""스탠드얼론 ④ Task 5 - 휴대폰 흉내로 끝에서 끝까지 + 바깥 연결 0 + 약속 문서의 예시 값 (계획 2026-11-23-standalone-4-phone).

로컬 서버를 local_server.main() 그대로 띄운다 (임시 RPA_PROGRAMDATA, RPA_EDITION=standalone, 시험 라이선스). 휴대폰 포트는
RPA_PHONE_HOST=127.0.0.1·빈 포트, RPA_PHONE_NO_FIREWALL=1 (방화벽 규칙을 만들지 않는다). 관리자 계정으로 짝짓고
tests/fake_phone_local.FakePhone(앱 흉내)이 문자를 받은 것처럼 번호를 보낸다 - 일반 버전 firebase/tests/check_phone_relay.py 와 같은 차례.
    D:/AX/RPA/.venv/Scripts/python.exe tests/check_phone_local.py
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

# --- 바깥 연결 0: 이 프로세스의 모든 연결 대상을 모은다 (불러오기 전에 감싼다) ---
TARGETS = []
_real_connect, _real_create = socket.socket.connect, socket.create_connection


def _connect(self, addr, *a, **k):
    TARGETS.append(str(addr[0]) if isinstance(addr, tuple) else repr(addr))
    return _real_connect(self, addr, *a, **k)


def _create(addr, *a, **k):
    TARGETS.append(str(addr[0]))
    return _real_create(addr, *a, **k)


socket.socket.connect, socket.create_connection = _connect, _create

import fake_phone_local as fpl  # noqa: E402
from fake_phone_local import FakePhone, PinError  # noqa: E402
import license_check  # noqa: E402
import local_phone  # noqa: E402
import local_server  # noqa: E402
import local_web  # noqa: E402
import otp_relay  # noqa: E402
import update_sign  # noqa: E402

fails = []
TMP = tempfile.mkdtemp(prefix="rpa_phone_e2e_")
PD = os.path.join(TMP, "pd")
LIC = {"edition": "standalone", "company": "시험상사", "cid": "c1", "pc_id": "p1", "issued": "2026-11-23",
       "modules": {}, "features": {}, "limits": {}}
BOSS_PW = "boss-pw-0001"
NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))
CONTRACT = os.path.join(ROOT, "docs", "phone-local-contract.md")


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def api(method, path, body=None, token=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    hs = {"Content-Type": "application/json"} if data is not None else {}
    if token:
        hs["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=hs)
    try:
        with NO_PROXY.open(req, timeout=15) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


made, codes, real_make = [], [], local_server.make_server
svc2 = None
try:
    os.makedirs(os.path.join(PD, "standalone"))
    os.environ.update(RPA_PROGRAMDATA=PD, RPA_EDITION="standalone", RPA_MACHINE_GUID="p1", RPA_PHONE_HOST="127.0.0.1",
                      RPA_PHONE_PORT="0", RPA_PHONE_NO_FIREWALL="1")
    lic_secret, lic_public = update_sign.keygen()
    license_check.LICENSE_PUBLIC_KEY_HEX = lic_public.hex()
    with open(os.path.join(PD, "license.json"), "w", encoding="utf-8") as f:
        json.dump(license_check.sign_body(lic_secret, LIC), f, ensure_ascii=False)
    folder = local_server.data_dir()
    local_web.Accounts(os.path.join(folder, local_web.ACCOUNTS_NAME)).set("boss", BOSS_PW, "admin")
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    os.environ["RPA_LOCAL_PORT"] = str(probe.getsockname()[1])
    probe.close()
    local_server.make_server = lambda *a, **k: made.append(real_make(*a, **k)) or made[-1]
    threading.Thread(target=lambda: codes.append(local_server.main()), daemon=True).start()
    end = time.time() + 20
    while not made and not codes and time.time() < end:
        time.sleep(0.05)
    srv = made[0]
    svc = srv.phone
    BASE = f"http://127.0.0.1:{srv.server_address[1]}"
    check("main 이 휴대폰 창구를 단다 (휴대폰 0대 → 포트 닫힘)", isinstance(svc, local_phone.Service) and srv.web.phone is svc
          and svc.gate.status()["open"] is False)

    print("짝짓기")
    st, got = api("POST", "/api/login", {"id": "boss", "password": BOSS_PW})
    TOKEN = got["token"]
    st, pair = api("POST", "/api/phone-pair", {"label": "김OO 휴대폰", "owner": "김OO", "senders": "1588-1234"}, TOKEN)
    check("POST /api/phone-pair → QR", st == 200 and pair["qr"].startswith("autopilot-phone://pair?v=1&h=127.0.0.1&"), repr(pair))
    phone = FakePhone(pair["qr"])
    phone.pair(os="android", app_version="1.0.0", device="SM-S918N")
    st, lst = api("GET", "/api/phones", token=TOKEN)
    PID = phone.phone_id
    check("FakePhone(qr).pair() → GET /api/phones 한 대", phone.pair_status == 200 and [p["id"] for p in lst["phones"]] == [PID], repr(lst))

    print("한 바퀴 (일반 버전 check_phone_relay.py 와 같은 차례)")
    check("요청 없음 → on_sms None", phone.on_sms("1588-1234", "[가나몰] 인증번호 [482913]") is None)
    relay = otp_relay.agent_relay(PID, ["1588-1234"], "가나몰")
    check("agent_relay 는 로컬 서버의 중계 열쇠로", type(relay.client).__name__ == "Client" and relay.client._role == "relay")
    req = relay.open(tick=lambda s: time.sleep(0.05))
    r = phone.request()
    check("열린 요청이 보인다 (req_id·site·senders·left_ms)", r.get("open") is True and r.get("req_id") == req and r.get("site") == "가나몰"
          and r.get("senders") == ["15881234"] and 0 < r.get("left_ms", 0) <= local_phone.OPEN_MS, repr(r))
    check("은행 발신번호 문자 → None", phone.on_sms("1599-0000", "[은행] 인증번호 [111111]") is None)
    check("인증번호 없는 문자 → None", phone.on_sms("1588-1234", "[가나몰] 주문이 접수되었습니다.") is None)
    check("맞는 문자 → '482913'", phone.on_sms("1588-1234", "[가나몰] 인증번호 [482913]를 입력해 주세요.") == "482913")
    saved = svc.store.get(f"apps/otp/codes/c1/{PID}/current")
    check("서버에 남은 값의 칸이 다섯 (본문 없음)", set(saved or {}) == {"req_id", "code", "sender", "sms_at", "written_at"}, repr(saved))
    check("relay.wait 가 그 번호", relay.wait(req, 5, tick=time.sleep) == "482913")
    relay.close(req)
    check("relay.close 뒤 요청·번호 없음", svc.store.get("apps/otp") is None)
    check("닫힌 뒤 on_sms None", phone.on_sms("1588-1234", "[가나몰] 인증번호 [482913]") is None)
    s_, v_ = phone.send_code(req, "482913", "15881234")
    check("억지 send_code → 409 no_request", s_ == 409 and (v_ or {}).get("error") == "no_request", repr((s_, v_)))

    print("2분")
    relay2 = otp_relay.agent_relay(PID, ["1588-1234"], "가나몰")
    req2 = relay2.open(tick=lambda s: time.sleep(0.05))
    real_clock = svc.clock
    skewed = lambda: real_clock() + 121  # noqa: E731
    svc.clock = svc.desk._clock = skewed
    try:
        r = phone.request()
        check("서버 시계를 121초 뒤로 → request() open: false (시계 차이는 clock 으로 맞춘다)", r.get("open") is False, repr(r))
        check("그때 send_code 409", phone.send_code(req2, "482913", "15881234")[0] == 409)
        svc.tick()
        check("5초 고리(tick) 뒤 자리가 비어 있다", svc.store.get("apps/otp") is None, repr(svc.store.get("apps/otp")))
    finally:
        svc.clock = svc.desk._clock = real_clock
        phone.offset_ms = 0

    print("허용 발신번호")
    try:
        otp_relay.agent_relay(PID, ["1599-0000"], "가나몰").open(tick=lambda s: time.sleep(0.05))
        check("휴대폰에 15881234 만 허용 → 15990000 요청은 RuntimeError", False, "예외 없음")
    except RuntimeError as e:
        check("휴대폰에 15881234 만 허용 → 15990000 요청은 RuntimeError", str(e) == otp_relay.DENIED, str(e))

    print("지문 (Review Focus 7)")
    svc2 = local_phone.Service(os.path.join(TMP, "other"), svc.store, LIC)       # 다른 폴더 = 다른 인증서
    svc2.pairing.start("x", "", [])
    svc2.gate.open()
    p2 = svc2.gate.status()["port"]
    seen = []
    real_head = local_phone.PhoneHandler._head

    def head(self):
        got_ = real_head(self)
        seen.append(self.server)
        return got_
    local_phone.PhoneHandler._head = head
    try:
        fake_qr = re.sub(r"&p=\d+&", f"&p={p2}&", pair["qr"])
        imp = FakePhone(fake_qr, key=phone.key)
        try:
            imp.request()
            check("다른 인증서의 서버에 같은 QR 로 붙으면 PinError", False, "예외 없음")
        except PinError:
            check("다른 인증서의 서버에 같은 QR 로 붙으면 PinError", imp.connects == 1)
        time.sleep(0.5)
        check("그 서버가 받은 요청이 0 (지문을 보고 아무것도 보내지 않았다)", not [s for s in seen if s is svc2.gate.server], repr(len(seen)))
    finally:
        local_phone.PhoneHandler._head = real_head

    print("거절 (Review Focus 4)")
    check("틀린 서명 401", phone.call("GET", fpl.REQUEST, key="0" * 64)[0] == 401)
    s_, h_, v_ = phone.call("GET", fpl.REQUEST, ts=phone.now_ms() - 300000)
    check("5분 전 시각 → 401 clock (응답 서명)", s_ == 401 and v_.get("error") == "clock" and "x-ap-sign" in h_)
    n = "cd" * 16
    check("같은 nonce 다시 401", [phone.call("GET", fpl.REQUEST, nonce=n)[0] for _ in range(2)] == [200, 401])
    st, _ = api("DELETE", f"/api/phones/{PID}", token=TOKEN)
    svc2.pairing.cancel()                         # 두 번째 서버를 닫는다 (첫 서버는 휴대폰 0대 → 닫힘)
    svc2.gate.sync()
    check("지운 휴대폰 - 포트가 닫혀 연결도 안 된다 (휴대폰 0대)", st == 200 and svc.gate.status()["open"] is False)

    print("사람 입력으로 넘어감")
    logs = []
    fo = otp_relay.standalone_relay(PID, ["1588-1234"], "가나몰", log=logs.append)
    t0 = time.time()
    got = fo.open()
    check("지운 휴대폰의 standalone_relay.open → 예외 없이 사람 입력 쪽 (로그 한 줄)", got == "manual" and len(logs) == 1
          and "직접 입력을 기다립니다" in logs[0] and time.time() - t0 < 10, repr((got, logs)))

    print("바깥 연결 0")
    check("이 시험의 연결 대상은 127.0.0.1 뿐", TARGETS and set(TARGETS) <= {"127.0.0.1"}, repr(sorted(set(TARGETS))))
    words = ("urllib", "http.client", "create_connection")
    found = {name: [w for w in words if w in open(os.path.join(ROOT, "firebase", "agent", name), encoding="utf-8").read()]
             for name in ("local_phone.py", "local_cert.py")}
    check("local_phone.py·local_cert.py 소스에 urllib·http.client·create_connection 낱말이 없다", not any(found.values()), repr(found))

    print("약속 문서 (docs/phone-local-contract.md)")
    doc = open(CONTRACT, encoding="utf-8").read() if os.path.isfile(CONTRACT) else ""
    vec = fpl.vectors()
    missing = [name for name, value in vec if f"`{value}`" not in doc]
    check("예시 값이 --vectors 의 지금 계산과 같다 (문서와 코드가 어긋나면 실패)", doc and not missing, repr(missing))
    out = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "fake_phone_local.py"), "--vectors"], capture_output=True, timeout=30)
    printed = out.stdout.decode("utf-8", "replace")
    check("python tests/fake_phone_local.py --vectors 가 같은 값을 찍는다", out.returncode == 0 and all(value in printed for _, value in vec))
    pk, sk = local_phone.pair_key(fpl.VECTOR_SECRET), local_phone.sign_key(fpl.VECTOR_SECRET, fpl.VECTOR_RAND)
    body = b'{"ok":true,"now_ms":1795000000000}'
    check("앱 흉내의 계산 = 서버 계산 (따로 쓴 두 코드)", pk == fpl.pair_key(fpl.VECTOR_SECRET) and sk == fpl.sign_key(fpl.VECTOR_SECRET, fpl.VECTOR_RAND)
          and local_phone.request_mac(sk, fpl.VECTOR_PHONE, "GET", fpl.REQUEST, fpl.VECTOR_TS, fpl.VECTOR_NONCE, b"")
          == fpl.request_mac(sk, fpl.VECTOR_PHONE, "GET", fpl.REQUEST, fpl.VECTOR_TS, fpl.VECTOR_NONCE, b"")
          and local_phone.response_mac(sk, fpl.VECTOR_NONCE, 200, body) == fpl.response_mac(sk, fpl.VECTOR_NONCE, 200, body))
    check("문서의 값 이름표: 포트·주소 셋·머리글 넷·오류 코드", all(w in doc for w in (
        "8782", "/phone/v1/pair", "/phone/v1/request", "/phone/v1/code", "X-AP-Phone", "X-AP-Time", "X-AP-Nonce", "X-AP-Sign",
        "bad_request", "unauthorized", "clock", "sender_not_allowed", "not_found", "no_request", "req_mismatch", "too_large", "too_many")))
    check("문서에 '판'·'묶음'·'권고' 낱말이 없다", not re.search(r"(?<![가-힣])판(?![가-힣])|묶음|권고", doc))
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    local_server.make_server = real_make
    for s in made:
        try:
            s.shutdown()
        except Exception:
            pass
    try:
        if svc2 is not None:
            svc2.stop()
    except Exception:
        pass
    for k in ("RPA_PROGRAMDATA", "RPA_EDITION", "RPA_MACHINE_GUID", "RPA_PHONE_HOST", "RPA_PHONE_PORT", "RPA_PHONE_NO_FIREWALL", "RPA_LOCAL_PORT"):
        os.environ.pop(k, None)
    time.sleep(0.5)
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n실패: {len(fails)}" + (f" ({', '.join(fails)})" if fails else ""))
sys.exit(1 if fails else 0)
