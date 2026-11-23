# -*- coding: utf-8 -*-
"""스탠드얼론 ④ Task 2 - 휴대폰 포트(HTTPS·자체 서명 인증서·지문), 방화벽 규칙, 쓸 때만 열기 (계획 2026-11-23-standalone-4-phone).
휴대폰 포트는 127.0.0.1 의 빈 포트에만 묶는다 (사내망에 열지 않는다). 방화벽 명령은 가짜 실행기가 받아 적기만 한다 -
이 PC 의 방화벽 규칙·파일 권한은 건드리지 않는다. 여러 보낸 쪽 주소는 PhoneServer.peer_ip 를 바꿔 끼워 흉내 낸다.
    D:/AX/RPA/.venv/Scripts/python.exe tests/test_phone_gate.py
"""
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import types
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import local_server  # noqa: E402
import local_web  # noqa: E402
import local_cert  # noqa: E402
import local_phone  # noqa: E402
from fake_phone_local import FakePhone, PinError, pair_key, request_mac  # noqa: E402

fails = []
TMP = tempfile.mkdtemp(prefix="rpa_phone_gate_")
LIC = {"edition": "standalone", "company": "시험상사", "cid": "c1", "pc_id": "p1", "issued": "2026-11-23",
       "modules": {}, "features": {}, "limits": {}}
RUNTIME_PY = r"D:\AX\runtime\python\python.exe"
SECRETS = []                         # 기록 파일에 없어야 할 값


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


class Clock:
    """진짜 시각 + skew (서버 쪽 시계만 앞으로 돌린다)."""

    def __init__(self):
        self.skew = 0.0

    def __call__(self):
        return time.time() + self.skew


class FakeRun:
    """방화벽 명령 흉내 - 받은 명령 글을 모은다. 규칙이 있는지 기억한다 (show 는 있으면 0, 없으면 1)."""

    def __init__(self, add_code=0, has=False):
        self.calls, self.add_code, self.has = [], add_code, has

    def __call__(self, cmd):
        self.calls.append(cmd)
        if " show rule " in cmd:
            return 0 if self.has else 1
        if " add rule " in cmd:
            if self.add_code == 0:
                self.has = True
            return self.add_code
        if " delete rule " in cmd:
            was, self.has = self.has, False
            return 0 if was else 1
        return 1

    def saw(self, word):
        return [c for c in self.calls if word in c]


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def tls_sock(port):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    raw = socket.create_connection(("127.0.0.1", port), timeout=10)
    return ctx.wrap_socket(raw)


def read_all(s, sec=3):
    s.settimeout(sec)
    buf = b""
    try:
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
    except (OSError, ssl.SSLError):
        pass
    return buf


def closed_within(s, sec):
    """s 가 sec 초 안에 닫히나 (읽기가 빈 값·끊김으로 끝난다) → (닫혔나, 걸린 초)."""
    began = time.time()
    s.settimeout(sec)
    try:
        got = s.recv(10)
        return got == b"", time.time() - began
    except socket.timeout:
        return False, time.time() - began
    except OSError:
        return True, time.time() - began


def qr_for(svc, label="김OO 휴대폰", owner="김OO", senders=("15881234",)):
    info = svc.pairing.start(label, owner, list(senders))
    svc.gate.open()
    st = svc.gate.status()
    SECRETS.append(info["secret"].hex())
    SECRETS.append(local_phone.b64url(info["secret"]))
    return local_phone.qr_text(st["hosts"], st["port"], info["phone_id"], info["secret"], st["fingerprint"]), info


svc = svc_f = svc_p = web_srv = runs = None
real_req_per_min = local_phone.REQ_PER_MIN
try:
    local_phone.REQ_PER_MIN = 100000          # 이 시험은 한 주소(127.0.0.1)에서 많이 보낸다 - 분당 상한 시험은 따로
    # ------------------------------------------------------------------------------------------
    print("인증서 (local_cert)")
    cdir = os.path.join(TMP, "cert")
    cert, key, fp = local_cert.ensure(cdir)
    check("ensure 가 두 파일을 만들고 지문은 hex 64자", os.path.basename(cert) == local_cert.CERT_NAME == "phone_cert.pem"
          and os.path.basename(key) == local_cert.KEY_NAME == "phone_key.pem" and os.path.isfile(cert) and os.path.isfile(key)
          and len(fp) == 64 and all(c in "0123456789abcdef" for c in fp))
    der = ssl.PEM_cert_to_DER_cert(open(cert, encoding="ascii").read())
    import hashlib  # noqa: E402
    check("지문 = 인증서 DER 의 SHA-256", fp == hashlib.sha256(der).hexdigest() == local_cert.fingerprint(cert))
    stamp = os.path.getmtime(key)
    check("다시 부르면 같은 지문 (다시 만들지 않는다)", local_cert.ensure(cdir)[2] == fp and os.path.getmtime(key) == stamp)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    check("ssl 이 받는 인증서·열쇠 (P-256, CN, 10년)", "BEGIN PRIVATE KEY" in open(key, encoding="ascii").read())
    with open(key, "w", encoding="ascii") as f:
        f.write("-----BEGIN PRIVATE KEY-----\nbroken\n-----END PRIVATE KEY-----\n")
    fp2 = local_cert.ensure(cdir)[2]
    check("열쇠 파일을 깨뜨리면 새로 만들고 지문이 바뀐다", fp2 != fp and len(fp2) == 64)
    try:
        local_cert.ensure(os.path.join(TMP, "cert_fail"), run=lambda args, **k: types.SimpleNamespace(returncode=1))
        check("자식이 실패하면 CertError", False, "예외 없음")
    except local_cert.CertError as e:
        check("자식이 실패하면 CertError", str(e) == "휴대폰 포트의 인증서를 만들지 못했습니다.", str(e))
    seen_args = []
    local_cert.ensure(os.path.join(TMP, "cert_args"), run=lambda args, **k: (seen_args.append((args, k)), subprocess.run(args, **k))[1])
    check("자식 프로세스로 만든다 (python -E -s local_cert.py --make <폴더>, 30초, 창 없음)",
          seen_args and seen_args[0][0][1:3] == ["-E", "-s"] and seen_args[0][0][3].endswith("local_cert.py") and seen_args[0][0][4] == "--make"
          and seen_args[0][1].get("timeout") == 30 and seen_args[0][1].get("creationflags") == 0x08000000, repr(seen_args))
    if os.path.isfile(RUNTIME_PY):
        out = os.path.join(TMP, "cert_runtime")
        r = subprocess.run([RUNTIME_PY, "-E", "-s", local_cert.__file__, "--make", out], capture_output=True, timeout=60)
        ok = r.returncode == 0 and os.path.isfile(os.path.join(out, local_cert.CERT_NAME))
        if ok:
            c2 = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            c2.load_cert_chain(os.path.join(out, local_cert.CERT_NAME), os.path.join(out, local_cert.KEY_NAME))
        check("내장 파이썬(D:\\AX\\runtime\\python)으로도 --make (그 폴더에는 쓰지 않는다)", ok, (r.stdout + r.stderr).decode("utf-8", "replace")[-300:])
    else:
        print("  (내장 파이썬이 없어 건너뜀)")
    check("열쇠 파일 잠금 목록에 phone_key.pem·phones.json", {"phone_key.pem", "phones.json"} <= set(local_server.LOCKED_FILES))
    rec = []
    local_server.lock_key_files(cdir, run=lambda args, timeout=60: rec.append(args) or (0, ""))
    check("lock_key_files 가 phone_key.pem 에도 icacls (가짜 실행기)", any(a[1].endswith("phone_key.pem") for a in rec), repr(rec[:2]))

    # ------------------------------------------------------------------------------------------
    print("열고 닫기 (Review Focus 1)")
    store = local_server.Store(os.path.join(TMP, "store.json"), volatile=local_server.VOLATILE)
    runs = local_server.Runs(os.path.join(TMP, "runs.db"))
    keys = local_server.ensure_keys(TMP)
    clk = Clock()
    fw = FakeRun()
    svc = local_phone.Service(os.path.join(TMP, "main"), store, LIC, clock=clk, run=fw, host="127.0.0.1", port=0)
    st = svc.gate.sync()
    check("휴대폰 0대·짝짓기 없음 → 닫힘, 규칙을 만들지 않는다", st["open"] is False and not fw.saw(" add rule ") and svc.gate.server is None, repr(st))
    info = svc.pairing.start("김OO 휴대폰", "김OO", ["15881234"])
    st = svc.gate.sync()
    want = (f'advfirewall firewall add rule name="AUTOPILOT Phone OTP" dir=in action=allow protocol=TCP localport=8782 '
            f'profile=private,domain program="{sys.executable}" enable=yes')
    check("짝짓기 시작 → 열림, add rule 이 그 글자 그대로", st["open"] is True and st["firewall"] == "ok" and len(fw.saw(" add rule ")) == 1
          and fw.saw(" add rule ")[0].endswith(want), repr(fw.calls))
    check("status - 포트·주소·지문", st["port"] == svc.gate.server.server_address[1] and st["hosts"] == ["127.0.0.1"]
          and len(st["fingerprint"]) == 64, repr(st))
    check("휴대폰 포트의 인증서는 자료 폴더에", os.path.isfile(os.path.join(TMP, "main", "phone_cert.pem")))
    svc.pairing.cancel()
    st = svc.gate.sync()
    check("짝짓기 취소 → 닫힘·delete rule", st["open"] is False and len(fw.saw(" delete rule ")) == 1 and svc.gate.server is None, repr(fw.calls))
    fixed = free_port()
    fw_bad = FakeRun(add_code=1)
    svc_f = local_phone.Service(os.path.join(TMP, "fail"), store, LIC, run=fw_bad, host="127.0.0.1", port=fixed)
    svc_f.pairing.start("x", "", [])
    try:
        svc_f.gate.open()
        check("add rule 실패 → GateError(firewall)", False, "예외 없음")
    except local_phone.GateError as e:
        check("add rule 실패 → GateError(firewall), 글 끝에 관리자 명령 한 줄", e.code == "firewall" and e.message.rstrip().endswith(
            f'netsh advfirewall firewall add rule name="AUTOPILOT Phone OTP" dir=in action=allow protocol=TCP localport={fixed} '
            f'profile=private,domain program="{sys.executable}" enable=yes'), e.message)
    try:
        socket.create_connection(("127.0.0.1", fixed), timeout=1).close()
        check("규칙을 못 만들면 bind 하지 않는다 (그 포트에 연결이 안 된다)", False)
    except OSError:
        check("규칙을 못 만들면 bind 하지 않는다 (그 포트에 연결이 안 된다)", svc_f.gate.status()["open"] is False
              and svc_f.gate.status()["firewall"] == "failed")
    svc_f.gate.lan_info = lambda: [{"ip": "192.168.0.10", "category": "public"}, {"ip": "10.0.0.3", "category": "public"}]
    try:
        svc_f.gate.open()
        check("주소가 모두 공용 → GateError(public-network)", False, "예외 없음")
    except local_phone.GateError as e:
        check("주소가 모두 공용 → GateError(public-network)", e.code == "public-network" and "'공용'" in e.message and "'개인'" in e.message, e.message)
    svc_f.gate.lan_info = lambda: [{"ip": "192.168.0.10", "category": "public"}, {"ip": "10.1.2.3", "category": "private"},
                                   {"ip": "172.16.0.9", "category": "domain"}, {"ip": "10.9.9.9", "category": "unknown"}]
    check("QR 주소는 개인·도메인만", svc_f.gate.hosts() == ["10.1.2.3", "172.16.0.9"], repr(svc_f.gate.hosts()))
    parsed = local_phone.parse_lan(json.dumps([{"ip": "127.0.0.1", "category": "Private"}, {"ip": "169.254.3.4", "category": "Private"},
                                               {"ip": "192.168.1.7", "category": "Private"}, {"ip": "10.2.3.4", "category": "DomainAuthenticated"},
                                               {"ip": "172.20.1.1", "category": "Public"}, {"ip": "10.5.5.5", "category": ""},
                                               {"ip": "nonsense", "category": "Private"}]))
    check("lan_info 풀이: 127·169.254 빼고 종류를 private·domain·public·unknown 으로", parsed == [
        {"ip": "192.168.1.7", "category": "private"}, {"ip": "10.2.3.4", "category": "domain"}, {"ip": "172.20.1.1", "category": "public"},
        {"ip": "10.5.5.5", "category": "unknown"}], repr(parsed))
    check("lan_info 풀이: 하나뿐이면 dict 도 받는다·빈 글은 []", local_phone.parse_lan('{"ip": "10.0.0.1", "category": "Private"}')
          == [{"ip": "10.0.0.1", "category": "private"}] and local_phone.parse_lan("") == [])
    real = local_phone.lan_info()
    check("진짜 lan_info (읽기만 - PowerShell 한 번) 은 목록을 돌려준다", isinstance(real, list) and all(set(x) == {"ip", "category"} for x in real), repr(real))
    os.environ["RPA_PHONE_NO_FIREWALL"] = "1"
    try:
        fw_skip = FakeRun()
        svc_s = local_phone.Service(os.path.join(TMP, "skip"), store, LIC, run=fw_skip, host="127.0.0.1", port=0)
        svc_s.pairing.start("x", "", [])
        st = svc_s.gate.sync()
        check("RPA_PHONE_NO_FIREWALL=1 이면 방화벽 명령을 부르지 않는다 (firewall: skipped)", st["open"] and st["firewall"] == "skipped"
              and fw_skip.calls == [], repr(fw_skip.calls))
        svc_s.stop()
    finally:
        os.environ.pop("RPA_PHONE_NO_FIREWALL", None)

    # ------------------------------------------------------------------------------------------
    print("창구 (Review Focus 2)")
    qr, info = qr_for(svc)
    psrv = svc.gate.server
    PORT = psrv.server_address[1]
    phone = FakePhone(qr)
    got = phone.pair(os="android", app_version="1.0", device="Galaxy S23")
    SECRETS.append(phone.key)
    check("FakePhone 이 QR 로 짝짓는다 (응답은 새 서명 열쇠로 서명)", phone.pair_status == 200 and got.get("ok") is True and got.get("phone_id") == info["phone_id"]
          and got.get("label") == "김OO 휴대폰" and got.get("senders") == ["15881234"] and isinstance(got.get("now_ms"), int), repr(got))
    rec_ph = svc.phones.get(info["phone_id"])
    check("서버는 서명 열쇠 해시·지문·기기 정보를 표에 둔다", rec_ph and rec_ph["key"] == phone.key and rec_ph["fp"] == svc.gate.status()["fingerprint"]
          and rec_ph["device"] == "Galaxy S23" and rec_ph["os"] == "android")
    check("짝짓기 상태 paired (기기 이름)", svc.pairing.state() == {"state": "paired", "phone": {"id": info["phone_id"], "label": "김OO 휴대폰",
                                                                                         "os": "android", "device": "Galaxy S23"}}, repr(svc.pairing.state()))
    r = phone.request()
    check("짝지은 뒤 request() 200 {open: false}", r == {"open": False, "now_ms": r.get("now_ms")} and isinstance(r.get("now_ms"), int), repr(r))
    probes = [("GET", "/"), ("POST", "/api/login"), ("GET", "/api/session"), ("GET", f"/db/apps/otp/codes/c1/{info['phone_id']}/current.json"),
              ("GET", "/fs/runs/c1/items"), ("GET", "/index.html"), ("GET", "/phone/v1/request?x=1"), ("GET", "/phone/v1/%2e%2e/api/session"),
              ("GET", "/phone/v1/../api/session"), ("PUT", "/phone/v1/code"), ("OPTIONS", "/phone/v1/request"), ("GET", "/phone/v1/pair"),
              ("POST", "/phone/v1/request"), ("GET", "/phone/v1/code"), ("DELETE", "/phone/v1/request")]
    res = {f"{m} {p}": phone.call(m, p, body={} if m in ("POST", "PUT") else None) for m, p in probes}
    check("다른 창구·방법·질의는 모두 404 not_found·서명 없음", all(s == 404 and v == {"error": "not_found", "now_ms": v.get("now_ms")} and "x-ap-sign" not in h
                                                        for s, h, v in res.values()), repr({k: (s, v) for k, (s, h, v) in res.items() if s != 404}))
    raw = socket.create_connection(("127.0.0.1", PORT), timeout=10)
    raw.sendall(b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
    got = read_all(raw, 7)
    raw.close()
    check("TLS 없이 보낸 HTTP 는 응답 없이 닫힌다", b"HTTP/" not in got, repr(got[:80]))
    s = tls_sock(PORT)
    s.sendall(b"BREW /phone/v1/request HTTP/1.1\r\nHost: x\r\n\r\n")
    got = read_all(s)
    s.close()
    check("모르는 방법도 404 (머리 글자 그대로)", b" 404 " in got.split(b"\r\n")[0] and b"Connection: close" in got and b"no-store" in got, repr(got[:200]))
    web = local_web.Web(store, runs, LIC, TMP, os.path.join(ROOT, "firebase", "web"))
    web_srv = local_server.make_server(store, runs, LIC, keys, port=0, folder=TMP, web=web, phone=svc)
    threading.Thread(target=web_srv.serve_forever, daemon=True).start()
    WEB = f"http://127.0.0.1:{web_srv.server_address[1]}"
    check("8781 쪽 서버 소켓의 주소는 127.0.0.1, 휴대폰 포트는 따로", web_srv.server_address[0] == "127.0.0.1" and web_srv.server_address[1] != PORT)

    # ------------------------------------------------------------------------------------------
    print("인증 (Review Focus 3·4)")
    s1, h1, v1 = phone.call("GET", "/phone/v1/request", key="0" * 64)
    s2, h2, v2 = phone.call("GET", "/phone/v1/request", headers={"X-AP-Phone": "ph_deadbeef"})
    strip = lambda v: {k: x for k, x in (v or {}).items() if k != "now_ms"}  # noqa: E731
    check("틀린 서명·없는 휴대폰 번호가 같은 401 본문 (서명 없음)", s1 == s2 == 401 and strip(v1) == strip(v2) == {"error": "unauthorized"}
          and "x-ap-sign" not in h1 and "x-ap-sign" not in h2, repr((s1, v1, s2, v2)))
    n = "ab" * 16
    a = phone.call("GET", "/phone/v1/request", nonce=n)[0]
    b = phone.call("GET", "/phone/v1/request", nonce=n)[0]
    check("같은 nonce 두 번째 401", (a, b) == (200, 401), repr((a, b)))
    s3, h3, v3 = phone.call("GET", "/phone/v1/request", ts=phone.now_ms() - 300000)
    check("5분 전 시각 + 맞는 서명 → 401 clock, now_ms, 응답 서명 있음", s3 == 401 and v3.get("error") == "clock" and isinstance(v3.get("now_ms"), int)
          and "x-ap-sign" in h3, repr((s3, v3, h3)))
    bad_hdr = [{"X-AP-Time": "abc"}, {"X-AP-Nonce": "short"}, {"X-AP-Sign": "zz"}, {"X-AP-Phone": "ph1"}]
    check("머리글 꼴이 틀리면 401", all(phone.call("GET", "/phone/v1/request", headers=h)[0] == 401 for h in bad_hdr))
    who = ["10.0.0.50"]
    psrv.peer_ip = lambda addr: who[0]
    for _ in range(local_phone.BAD_LIMIT):
        phone.call("GET", "/phone/v1/request", key="1" * 64)
    s4, h4, v4 = phone.call("GET", "/phone/v1/request")
    check("틀린 서명 10번 뒤 맞는 요청도 429 too_many", s4 == 429 and strip(v4) == {"error": "too_many"} and "x-ap-sign" not in h4, repr((s4, v4)))
    who[0] = "10.0.0.51"
    check("다른 주소로 센 것은 영향 없음", phone.call("GET", "/phone/v1/request")[0] == 200)
    who[0] = "10.0.0.50"
    clk.skew += local_phone.BAD_SEC + 1
    r = phone.request()                   # 서버 시계가 601초 앞 - clock 을 받고 시계를 맞춘 뒤 다시
    check("가짜 시계 601초 뒤 200 (시계 차이는 clock 으로 맞춘다)", r.get("open") is False and abs(phone.offset_ms - (local_phone.BAD_SEC + 1) * 1000) < 5000,
          repr((r, phone.offset_ms)))
    psrv.peer_ip = lambda addr: "8.8.8.8"
    s = socket.create_connection(("127.0.0.1", PORT), timeout=10)
    closed, took = closed_within(s, 2)
    s.close()
    check("사설·이 PC 주소가 아니면 응답 없이 바로 닫는다", closed and took < 1.5, f"{closed} {took:.1f}초")
    psrv.peer_ip = lambda addr: addr[0]

    # ------------------------------------------------------------------------------------------
    print("짝짓기")
    psrv.peer_ip = lambda addr: "10.0.0.80"   # 이 칸은 일부러 틀린 서명을 많이 보낸다 - 다른 칸의 주소(127.0.0.1)가 막히지 않게
    qr2, info2 = qr_for(svc, "두 번째", "", [])
    p2 = FakePhone(qr2)
    p2.pair()
    again = FakePhone(qr2)
    again.pair()
    check("맞는 QR 로 한 번 200, 같은 QR 두 번째 401", p2.pair_status == 200 and again.pair_status == 401)
    SECRETS.append(p2.key)
    qr3, _ = qr_for(svc, "세 번째", "", [])
    clk.skew += local_phone.PAIR_SEC + 1
    p3 = FakePhone(qr3)
    p3.pair()
    check("301초 뒤 401", p3.pair_status == 401)
    qr4, info4 = qr_for(svc, "네 번째", "", [])
    p4 = FakePhone(qr4)
    for _ in range(local_phone.PAIR_FAIL_MAX):
        p4.call("POST", "/phone/v1/pair", {"rand": local_phone.b64url(os.urandom(32)), "os": "android", "app_version": "t", "device": "d"}, key="2" * 64)
    p4.pair()
    check("틀린 서명 5번 뒤 맞는 것도 401 (취소됨)", p4.pair_status == 401 and svc.pairing.state()["state"] == "none", repr(svc.pairing.state()))
    qr5, info5 = qr_for(svc, "다섯 번째", "", [])
    p5 = FakePhone(qr5)
    for body in ({"rand": "short", "os": "android", "app_version": "t", "device": "d"}, {"rand": local_phone.b64url(os.urandom(32)), "os": "windows",
                                                                                      "app_version": "t", "device": "d"},
                 {"rand": local_phone.b64url(os.urandom(32)), "os": "ios", "app_version": "t", "device": "d", "sms": "문자"}):
        st5 = p5.call("POST", "/phone/v1/pair", body, key=pair_key(p5.qr["secret"]))[0]
        check(f"짝짓기 본문 꼴이 틀리면 400 ({sorted(body)})", st5 == 400)
    p5.pair(os="ios", device="iPhone 15")
    check("본문이 틀린 시도는 짝짓기를 쓰지 않는다 - 그 뒤 맞는 것 200", p5.pair_status == 200)
    SECRETS.append(p5.key)
    st6 = p5.call("GET", "/phone/v1/request", key=pair_key(p5.qr["secret"]))[0]
    check("짝지은 뒤 pair_key 로 서명한 request 는 401 (QR 만으로는 그 뒤 요청을 못 만든다)", st6 == 401)
    svc.phones.remove(p2.phone_id)
    check("휴대폰을 지운 뒤 옛 열쇠 401", p2.call("GET", "/phone/v1/request")[0] == 401)
    psrv.peer_ip = lambda addr: addr[0]

    # ------------------------------------------------------------------------------------------
    print("묶기 (Review Focus 5)")
    s = tls_sock(PORT)
    began = time.time()
    s.sendall(b"POST /phone/v1/code HTTP/1.1\r\nHost: x\r\nContent-Length: 5000\r\n\r\n")
    got = read_all(s, 4)
    s.close()
    check("Content-Length: 5000 → 413 too_large, 본문을 기다리지 않는다", b" 413 " in got.split(b"\r\n")[0] and b"too_large" in got
          and time.time() - began < 2, repr(got[:120]))
    s = tls_sock(PORT)
    s.sendall(b"POST /phone/v1/code HTTP/1.1\r\nHost: x\r\n\r\n")
    got = read_all(s)
    s.close()
    check("길이 없는 POST 400 bad_request", b" 400 " in got.split(b"\r\n")[0] and b"bad_request" in got, repr(got[:120]))
    s = socket.create_connection(("127.0.0.1", PORT), timeout=10)
    closed, took = closed_within(s, 9)
    s.close()
    check("연결만 하고 아무것도 안 보냄 → 6초 안에 끊김", closed and took < 6.5, f"{closed} {took:.1f}초")
    s = tls_sock(PORT)
    began, closed, other = time.time(), False, None
    line = b"GET /phone/v1/request HTTP/1.1\r\nHost: x\r\nX-Pad: " + b"a" * 200
    for i, byte in enumerate(line):
        try:
            s.send(bytes([byte]))
        except OSError:
            closed = True
            break
        s.settimeout(0.4)                   # 서버가 보낸 것(TLS 1.3 세션 티켓 등)은 읽어 넘기고, 끊김만 본다
        try:
            closed = s.recv(10) == b""
        except socket.timeout:
            closed = False
        except (OSError, ssl.SSLError):
            closed = True
        if closed:
            break
        if i == 3:
            t0 = time.time()
            other = (phone.request().get("open") is False, time.time() - t0)
        if time.time() - began > 9:
            break
    took = time.time() - began
    s.close()
    check("악수 뒤 머리글을 한 바이트씩 → 6초 안에 끊김", closed and took < 6.5, f"{closed} {took:.1f}초")
    check("그 사이 다른 휴대폰의 request() 는 1초 안에 답", other is not None and other[0] and other[1] < 1.0, repr(other))
    psrv.peer_ip = lambda addr: "10.0.0.60"
    held = [socket.create_connection(("127.0.0.1", PORT), timeout=10) for _ in range(local_phone.MAX_PER_IP)]
    time.sleep(0.3)
    fifth = socket.create_connection(("127.0.0.1", PORT), timeout=10)
    closed, took = closed_within(fifth, 3)
    check("같은 주소 다섯 번째 동시 연결은 바로 닫힘", closed and took < 1.0, f"{closed} {took:.1f}초")
    for x in held + [fifth]:
        x.close()
    time.sleep(0.5)
    nxt = iter(range(1, 10000))
    psrv.peer_ip = lambda addr: f"10.1.{next(nxt) // 250}.{next(nxt) % 250 + 1}"
    held = [socket.create_connection(("127.0.0.1", PORT), timeout=10) for _ in range(local_phone.MAX_CONN)]
    time.sleep(0.5)
    extra = socket.create_connection(("127.0.0.1", PORT), timeout=10)
    closed, took = closed_within(extra, 3)
    check("주소를 바꿔 가며 열일곱 번째도 바로 닫힘", closed and took < 1.0, f"{closed} {took:.1f}초 (연결 {psrv.conns})")
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(WEB + "/api/session", timeout=5) as resp:
            web_status = resp.status
    except urllib.error.HTTPError as e:
        web_status = e.code
    except Exception as e:
        web_status = repr(e)
    check("휴대폰 포트에 빈 연결을 상한까지 걸어 두어도 127.0.0.1 의 GET /api/session 은 답한다", web_status == 401, repr(web_status))
    for x in held + [extra]:
        x.close()
    time.sleep(0.5)
    psrv.peer_ip = lambda addr: "10.0.0.70"
    local_phone.REQ_PER_MIN = 3
    try:
        conns = [socket.create_connection(("127.0.0.1", PORT), timeout=10) for _ in range(3)]
        time.sleep(0.3)
        fourth = socket.create_connection(("127.0.0.1", PORT), timeout=10)
        closed, took = closed_within(fourth, 3)
        check("한 주소에서 분당 요청 상한을 넘으면 바로 닫힘", closed and took < 1.0, f"{closed} {took:.1f}초")
        for x in conns + [fourth]:
            x.close()
    finally:
        local_phone.REQ_PER_MIN = 100000
    psrv.peer_ip = lambda addr: addr[0]
    time.sleep(0.3)
    check("그 뒤에도 휴대폰 요청을 받는다", phone.request().get("open") is False)

    # ------------------------------------------------------------------------------------------
    print("기록")
    log_text = open(os.path.join(TMP, "main", local_server.LOG_NAME), encoding="utf-8").read()
    check("서버 기록에 짝짓기·포트 열고 닫음이 남는다", "휴대폰" in log_text and info["phone_id"] in log_text, log_text[-300:])
    leaked = [x for x in SECRETS if x and x in log_text]
    check("서버 기록에 짝 열쇠·서명 열쇠가 없다", not leaked, repr(leaked))
    check("phones.json 은 자료 폴더, 열쇠 파일과 같은 잠금 목록", os.path.isfile(os.path.join(TMP, "main", "phones.json")))
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    local_phone.REQ_PER_MIN = real_req_per_min
    for s_ in (svc, svc_f):
        try:
            if s_ is not None:
                s_.stop()
        except Exception:
            pass
    try:
        if web_srv is not None:
            web_srv.shutdown()
            web_srv.server_close()
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
