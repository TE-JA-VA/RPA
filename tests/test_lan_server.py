# -*- coding: utf-8 -*-
"""사내 서버 ① Task 4 - 서버 LAN 배치: /enroll, PC 별 ap2 서명 확인, 자기 자리만, 서명된 시계 답, 중지·지워짐, 에이전트 구독 상한
(계획 2026-11-24-lan-1-server-multi-pc, 설계 6.4·6.5).
TLS·사내 주소 없이 127.0.0.1 서버 하나에 PC 등록부를 달고 가짜 PC 여럿으로 본다.
ap2 머리글은 이 파일이 직접 만든다 (서명 글은 계획이 정한 꼴 - 클라이언트 Task 3 없이도 돈다).
클라이언트(local_store.Client lan·enroll)가 있어야 하는 시험은 Task 3 가 들어온 뒤에만 돈다 ([보류] 줄).
    D:/AX/RPA/.venv/Scripts/python.exe tests/test_lan_server.py
"""
import dataclasses
import http.client
import json
import os
import shutil
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
import fb  # noqa: E402
import local_server  # noqa: E402
import local_store  # noqa: E402
import pc_registry  # noqa: E402

fails = []
TMP = tempfile.mkdtemp(prefix="rpa_lan_srv_")
LIC = {"edition": "standalone", "company": "시험상사", "cid": "c1", "pc_id": "srv", "issued": "2026-11-24",
       "modules": {"Hold": False}, "features": {"wellife": False}, "limits": {"schedule": 3, "presets": None, "parallel": None}}
NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))
H_PC = local_store.H_PC
TASK3 = hasattr(local_store, "request_mac2") and hasattr(local_store, "enroll")


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def pending(name):
    print(f"  [보류] {name}  - Task 3 기다림 (local_store 의 request_mac2·enroll 이 아직 없다)")


def until(fn, sec):
    """fn() 이 참이 될 때까지 (시간이 아니라 조건으로 기다린다) → 참이 됐으면 True."""
    end = time.time() + sec
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.02)
    return bool(fn())


class Got:
    def __init__(self, status, raw, headers, signed):
        self.status, self.raw, self.headers, self.signed = status, raw, headers, signed

    def json(self):
        try:
            return json.loads(self.raw) if self.raw else None
        except ValueError:
            return None


def mac2(key, pc, role, method, target, ts, nonce, body):
    """계획이 정한 ap2 요청 서명 = _mac(열쇠, ["ap2","req",PC,역할,방법,주소,시각,nonce,본문 sha256])."""
    out = local_store._mac(key, ["ap2", "req", pc, role, method, target, str(ts), nonce, local_store._digest(body)])
    if TASK3:                      # 클라이언트(Task 3)의 함수와 같은 값인지도 본다
        assert out == local_store.request_mac2(key, pc, role, method, target, str(ts), nonce, body)
    return out


def ap2_headers(key, pc, role, method, target, body=b"", now_ms=None, nonce=None, sign_pc=None):
    ts = str(int(time.time() * 1000) if now_ms is None else int(now_ms))
    nonce = nonce or os.urandom(16).hex()
    return {local_store.H_ROLE: role, local_store.H_TIME: ts, local_store.H_NONCE: nonce, H_PC: pc,
            local_store.H_SIGN: mac2(key, sign_pc or pc, role, method, target, ts, nonce, body)}


def send(base, method, path, data, hs, verify_key):
    hs = dict(hs)
    hs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(base + path, data=data or None, method=method, headers=hs)
    nonce = hs.get(local_store.H_NONCE, "")
    try:
        with NO_PROXY.open(req, timeout=10) as r:
            got, status, rh = r.read(), r.status, r.headers
    except urllib.error.HTTPError as e:
        got, status, rh = e.read(), e.code, e.headers
    signed = bool(verify_key) and (rh.get(local_store.H_SIGN) or "") == local_store.response_mac(verify_key, nonce, status, got)
    return Got(status, got.decode("utf-8", "replace"), rh, signed)


def body_of(method, body):
    return b"" if body is None and method in ("GET", "DELETE") else json.dumps(body, ensure_ascii=False).encode("utf-8")


def call2(method, path, body=None, pc="pc_01", keys=None, role="agent", now_ms=None, nonce=None, sign_pc=None, sign_key=None, base=None):
    """PC 하나의 ap2 요청. keys = (agent, relay). 응답 서명은 그 역할의 열쇠로 본다."""
    keys = keys or PCS[pc]
    key = keys[local_store.ROLES.index(role)]
    data = body_of(method, body)
    hs = ap2_headers(sign_key or key, pc, role, method, path, data, now_ms=now_ms, nonce=nonce, sign_pc=sign_pc)
    return send(base or BASE, method, path, data, hs, key)


def call1(base, method, path, key, body=None, extra=None):
    """지금(ap1) 서명 요청."""
    data = body_of(method, body)
    hs = local_store.sign_headers(key, "agent", method, path, data)
    hs.update(extra or {})
    return send(base, method, path, data, hs, key)


def enroll_raw(start, rand, guid, host, nonce=None, base=None, proof=None, body=None):
    """등록 요청 한 번 (서명 머리글 없음) → (Got, 새 열쇠 둘). 응답 서명은 새 agent 열쇠와 본문 nonce 로 본다."""
    nonce = nonce or os.urandom(16).hex()
    pc = start["pc_id"]
    keys = pc_registry.derive_keys(start["token"], rand)
    body = body if body is not None else {"v": 1, "pc": pc, "rand": rand, "guid": guid, "host": host, "nonce": nonce,
                                          "proof": proof or pc_registry.enroll_proof(start["token"], pc, rand, guid, host)}
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request((base or BASE) + "/enroll", data=data, method="POST", headers={"Content-Type": "application/json"})
    try:
        with NO_PROXY.open(req, timeout=10) as r:
            got, status, rh = r.read(), r.status, r.headers
    except urllib.error.HTTPError as e:
        got, status, rh = e.read(), e.code, e.headers
    signed = (rh.get(local_store.H_SIGN) or "") == local_store.response_mac(keys[0], nonce, status, got)
    return Got(status, got.decode("utf-8", "replace"), rh, signed), keys


class Stream:
    """ap2 구독 하나 (http.client 로 직접) - 첫 응답줄을 받고 뒤에서 줄을 읽어 끝(EOF)을 본다."""

    def __init__(self, pc, path, keys=None, role="agent"):
        keys = keys or PCS[pc]
        target = f"/db/{path}.json"
        hs = ap2_headers(keys[local_store.ROLES.index(role)], pc, role, "GET", target)
        hs["Accept"] = "text/event-stream"
        self.conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=15)
        self.conn.request("GET", target, headers=hs)
        self.resp = self.conn.getresponse()
        self.status = self.resp.status
        self.lines, self.ended = [], threading.Event()
        if self.status == 200:
            threading.Thread(target=self._pump, daemon=True).start()
        else:
            self.raw = self.resp.read()
            self.signed = (self.resp.headers.get(local_store.H_SIGN) or "") == local_store.response_mac(
                keys[local_store.ROLES.index(role)], hs[local_store.H_NONCE], self.status, self.raw)
            self.ended.set()

    def _pump(self):
        try:
            while True:
                line = self.resp.readline()
                if not line:
                    break
                self.lines.append(line)
        except Exception:
            pass
        self.ended.set()

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass


GUIDS = ["11111111-2222-3333-4444-5555555555%02d" % i for i in range(10)]
RANDS = [("%02x" % i) * 32 for i in range(1, 10)]
PCS = {}
srv = srv1 = runs = None
try:
    # --- 서버 둘: 사내 서버(등록부 있음)와 단독(없음) ---
    store = local_server.Store(os.path.join(TMP, "store.json"), volatile=local_server.VOLATILE)
    runs = local_server.Runs(os.path.join(TMP, "runs.db"))
    reg = pc_registry.Registry(os.path.join(TMP, "pcs.json"), seats=5)

    class FakeWeb:                 # make_server 가 public_url 을 적는지만 본다 (웹 창구 일은 Task 6)
        def handle(self, h, method, path, query, raw):
            return False
    web = FakeWeb()
    srv = local_server.make_server(store, runs, LIC, None, port=0, folder=TMP, registry=reg, web=web)
    PORT = srv.server_address[1]
    BASE = f"http://127.0.0.1:{PORT}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    TMP1 = os.path.join(TMP, "single")
    os.makedirs(TMP1)
    store1 = local_server.Store(os.path.join(TMP1, "store.json"), volatile=local_server.VOLATILE)
    AGENT1, RELAY1 = local_server.ensure_keys(TMP1)
    LIC1 = dict(LIC, pc_id="p1")
    srv1 = local_server.make_server(store1, runs, LIC1, (AGENT1, RELAY1), port=0, folder=TMP1)
    BASE1 = f"http://127.0.0.1:{srv1.server_address[1]}"
    threading.Thread(target=srv1.serve_forever, daemon=True).start()

    print("배치 (Deploy)")
    check("SINGLE 은 지금 상수 그대로", local_server.SINGLE == local_server.Deploy("single", local_server.MAX_CONN, 16, 0, 0, local_server.SIGN_WINDOW_MS)
          and local_server.MAX_CONN == 64 and local_server.SIGN_WINDOW_MS == 60000)
    check("LAN 의 숫자", local_server.LAN == local_server.Deploy("lan", 256, 32, 64, 4, 120000))
    check("등록부가 있으면 LAN, 없으면 SINGLE", srv.deploy is local_server.LAN and srv.registry is reg
          and srv1.deploy is local_server.SINGLE and srv1.registry is None)
    check("웹 창구에 서버 주소를 적는다", getattr(web, "public_url", None) == BASE, repr(getattr(web, "public_url", None)))
    try:
        frozen = False
        local_server.LAN.max_conn = 1
    except dataclasses.FrozenInstanceError:
        frozen = True
    check("Deploy 는 바꿀 수 없다 (frozen)", frozen)

    print("test_enroll_over_http - 등록 창구")
    s1 = reg.start("1층 PC")
    r, k1 = enroll_raw(s1, RANDS[0], GUIDS[1], "OFFICE-1")
    check("등록 200, 새 agent 열쇠와 본문 nonce 로 서명", r.status == 200 and r.signed and r.json() == {"pc": "pc_01"}, f"{r.status} {r.raw}")
    check("서버의 열쇠와 PC 가 만든 열쇠가 같다", reg.keys("pc_01") == k1 and reg.state("pc_01") == "active")
    PCS["pc_01"] = k1
    r2, _ = enroll_raw(s1, RANDS[0], GUIDS[1], "OFFICE-1")
    check("같은 글로 두 번째 등록 403 unknown (서명 없음)", r2.status == 403 and r2.json() == {"error": "unknown"} and not r2.signed, f"{r2.status} {r2.raw}")
    s2 = reg.start("2층 PC")
    r, _ = enroll_raw(s2, RANDS[1], GUIDS[2], "OFFICE-2", proof="0" * 64)
    check("증명이 틀리면 403 bad_proof", r.status == 403 and r.json() == {"error": "bad_proof"}, f"{r.status} {r.raw}")
    r, _ = enroll_raw(s2, RANDS[1], GUIDS[1], "OFFICE-2")
    check("같은 윈도우 PC 는 403 duplicate", r.status == 403 and r.json() == {"error": "duplicate"}, f"{r.status} {r.raw}")
    bad_bodies = [
        ("본문이 dict 가 아님", ["x"]),
        ("v 가 1 이 아님", {"v": 2, "pc": "pc_02", "rand": RANDS[1], "guid": GUIDS[2], "host": "H", "nonce": "n" * 32, "proof": "p"}),
        ("nonce 가 짧음", {"v": 1, "pc": "pc_02", "rand": RANDS[1], "guid": GUIDS[2], "host": "H", "nonce": "n" * 8, "proof": "p"}),
        ("칸이 빠짐", {"v": 1, "pc": "pc_02", "rand": RANDS[1], "guid": GUIDS[2], "nonce": "n" * 32, "proof": "p"}),
        ("칸이 글이 아님", {"v": 1, "pc": "pc_02", "rand": 5, "guid": GUIDS[2], "host": "H", "nonce": "n" * 32, "proof": "p"}),
    ]
    for name, b in bad_bodies:
        r, _ = enroll_raw(s2, RANDS[1], GUIDS[2], "OFFICE-2", body=b)
        check(f"꼴이 틀리면 400 ({name})", r.status == 400, f"{r.status} {r.raw}")
    r, k2 = enroll_raw(s2, RANDS[1], GUIDS[2], "OFFICE-2")
    check("틀린 시도 뒤에도 맞는 등록은 된다 (5번 안)", r.status == 200 and r.signed, f"{r.status} {r.raw}")
    PCS["pc_02"] = k2
    req = urllib.request.Request(BASE1 + "/enroll", data=b"{}", method="POST", headers={"Content-Type": "application/json"})
    try:
        with NO_PROXY.open(req, timeout=10) as resp:
            st1 = resp.status
    except urllib.error.HTTPError as e:
        st1 = e.code
    check("단독 서버의 /enroll 은 404", st1 == 404, st1)
    text = open(os.path.join(TMP, local_server.LOG_NAME), encoding="utf-8").read()
    check("등록은 기록에 번호·컴퓨터 이름만", "PC 등록  번호=pc_01  컴퓨터=OFFICE-1" in text, text[-300:])
    check("기록에 토큰·열쇠·증명이 없다", all(x not in text for x in (s1["token"], s2["token"], *k1, *k2,
                                                                 pc_registry.enroll_proof(s1["token"], "pc_01", RANDS[0], GUIDS[1], "OFFICE-1"))))
    if TASK3:
        s3 = reg.start("3층 PC")
        info = {"v": 1, "url": BASE, "pc": s3["pc_id"], "token": s3["token"], "exp": s3["expires_at"]}
        got = local_store.enroll(pc_registry.encode_enrollment(info), GUIDS[3], "OFFICE-3")
        check("클라이언트 enroll 로 등록 (Task 3)", got.get("pc_id") == "pc_03" and (got.get("agent_key"), got.get("relay_key")) == reg.keys("pc_03"), repr(sorted(got)))
        PCS["pc_03"] = (got["agent_key"], got["relay_key"])
        try:
            local_store.enroll(pc_registry.encode_enrollment(info), GUIDS[3], "OFFICE-3")
            check("같은 글로 클라이언트 두 번째 등록은 거절 (Task 3)", False, "예외 없음")
        except fb.HttpError as e:
            check("같은 글로 클라이언트 두 번째 등록은 거절 (Task 3)", e.status == 403 and "unknown" in e.body, repr(e.body))
    else:
        pending("클라이언트 enroll 로 등록")
        s3 = reg.start("3층 PC")
        r, k3 = enroll_raw(s3, RANDS[2], GUIDS[3], "OFFICE-3")
        check("세 번째 PC 등록 (직접 요청)", r.status == 200 and r.signed, f"{r.status} {r.raw}")
        PCS["pc_03"] = k3

    print("test_own_spot_only - 자기 자리만")
    r = call2("PATCH", "/db/apps/rpa/live/c1/pc_01.json", {"state": "idle"})
    check("pc_01 이 자기 현황 PATCH 200 (서명된 답)", r.status == 200 and r.signed and store.get("apps/rpa/live/c1/pc_01/state") == "idle", f"{r.status} {r.raw}")
    r = call2("PATCH", "/db/apps/rpa/live/c1/pc_02.json", {"state": "idle"})
    check("pc_01 이 pc_02 현황 PATCH 403 (서명된 거절)", r.status == 403 and r.signed and store.get("apps/rpa/live/c1/pc_02") is None, f"{r.status} {r.raw}")
    store.put("apps/rpa/commands/c1/pc_02/k1", {"state": "queued", "type": "launch", "expires_at": 9e9})
    check("pc_01 이 pc_02 명령 GET 403", call2("GET", "/db/apps/rpa/commands/c1/pc_02.json").status == 403)
    check("pc_02 는 자기 명령을 읽는다", (call2("GET", "/db/apps/rpa/commands/c1/pc_02.json", pc="pc_02").json() or {}).get("k1", {}).get("state") == "queued")
    check("pc_01 이 pc_02 명령 상태 옮기기 403", call2("PATCH", "/db/apps/rpa/commands/c1/pc_02/k1.json", {"state": "running"}).status == 403
          and store.get("apps/rpa/commands/c1/pc_02/k1/state") == "queued")
    check("서버 라이선스의 PC 번호 자리도 403", call2("GET", "/db/apps/rpa/live/c1/srv.json").status == 403)
    check("다른 업체 자리 403", call2("GET", "/db/apps/rpa/live/c2/pc_01.json").status == 403)
    check("정책 읽기는 된다", call2("GET", "/db/meta/companies/c1/apps/rpa/modules.json").json() == {"Hold": False})
    check("중계 열쇠는 현황을 못 쓴다", call2("PATCH", "/db/apps/rpa/live/c1/pc_01.json", {"x": 1}, role="relay").status == 403)
    check("중계 열쇠로 휴대폰 목록 읽기 (서명된 답)", (lambda g: g.status == 200 and g.signed)(call2("GET", "/db/meta/companies/c1/phones.json", role="relay")))
    if TASK3:
        c1 = local_store.Client({"standalone": True, "server_url": BASE, "key": PCS["pc_01"][0], "role": "agent", "lan": True, "pc_id": "pc_01"})
        c1.patch("apps/rpa/live/c1/pc_01", {"heartbeat": 7})
        check("클라이언트(lan)로 자기 현황 쓰기·읽기 (Task 3)", c1.get("apps/rpa/live/c1/pc_01/heartbeat") == 7)
        try:
            c1.get("apps/rpa/live/c1/pc_02")
            check("클라이언트(lan)로 남의 현황 읽기는 HttpError 403 (Task 3)", False, "예외 없음")
        except fb.HttpError as e:
            check("클라이언트(lan)로 남의 현황 읽기는 HttpError 403 (Task 3)", e.status == 403)
        ev = []
        try:
            for item in c1.stream("apps/rpa/commands/c1/pc_01", timeout=1.5):
                ev.append(item)
                break
        except Exception as e:
            ev.append(repr(e))
        check("클라이언트(lan) 구독의 첫 이벤트 (서명 확인 포함, Task 3)", ev[:1] == [("put", {"path": "/", "data": None})], repr(ev))
    else:
        pending("클라이언트(lan) 요청·구독")
    check("allowed 에 PC 번호를 넘긴다", local_server.allowed("agent", "GET", ["apps", "rpa", "live", "c1", "pc_01"], LIC, "pc_01")
          and not local_server.allowed("agent", "GET", ["apps", "rpa", "live", "c1", "pc_01"], LIC, "pc_02")
          and local_server.allowed("agent", "GET", ["apps", "rpa", "live", "c1", "srv"], LIC))
    OTPB = {"req_id": "req_lan_0001", "site": "시험몰", "pcId": "pc_01", "senders": {"0101": True}}
    check("otp_request_ok 에 PC 번호를 넘긴다", local_server.otp_request_ok(OTPB, LIC, {"senders": []}, "pc_01") is True
          and local_server.otp_request_ok(OTPB, LIC, {"senders": []}, "pc_02") is False
          and local_server.otp_request_ok(OTPB, LIC, {"senders": []}) is False
          and local_server.otp_request_ok(dict(OTPB, pcId="srv"), LIC, {"senders": []}) is True)

    print("test_other_pc_key_rejected - 다른 PC 의 열쇠")
    r = call2("GET", "/db/apps/rpa/live/c1/pc_01.json", pc="pc_01", sign_key=PCS["pc_02"][0])
    check("pc_02 열쇠로 X-AP-PC: pc_01 서명 → 서명 없는 401", r.status == 401 and not r.signed and r.headers.get(local_store.H_SIGN) is None, f"{r.status} {r.raw}")
    r = call2("GET", "/db/apps/rpa/live/c1/pc_01.json", pc="pc_01", sign_pc="pc_02", sign_key=PCS["pc_02"][0])
    check("서명 글의 PC 번호와 머리글이 다르면 401", r.status == 401 and r.headers.get(local_store.H_SIGN) is None)
    check("모르는 PC 번호 401", call2("GET", "/db/apps/rpa/live/c1/pc_09.json", pc="pc_09", keys=PCS["pc_01"]).status == 401)
    check("꼴이 틀린 PC 번호 401", call2("GET", "/db/apps/rpa/live/c1/p1.json", pc="p1", keys=PCS["pc_01"]).status == 401)
    check("중계 열쇠로 agent 역할을 대면 401", call2("GET", "/db/apps/rpa/live/c1/pc_01.json", sign_key=PCS["pc_01"][1]).status == 401)
    path = "/db/apps/rpa/live/c1/pc_01.json"
    hs = ap2_headers(PCS["pc_01"][0], "pc_01", "agent", "GET", path)
    first, again = send(BASE, "GET", path, b"", hs, PCS["pc_01"][0]), send(BASE, "GET", path, b"", hs, PCS["pc_01"][0])
    check("같은 요청을 다시 보내면 서명 없는 401 (nonce)", first.status == 200 and again.status == 401 and not again.signed)
    check("ap1(PC 번호 없는) 서명은 사내 서버에서 401", call1(BASE, "GET", path, PCS["pc_01"][0]).status == 401)
    r = call2("GET", path)
    check("Host 가 다르면 403", send(BASE, "GET", path, b"", dict(ap2_headers(PCS["pc_01"][0], "pc_01", "agent", "GET", path), Host="evil.example"),
                                    PCS["pc_01"][0]).status == 403 and r.status == 200)

    print("test_runs_own_pc - 실행 기록")
    doc2 = {"pcId": "pc_02", "date": "2026-11-24", "started_at": "2026-11-24T09:00:00", "cost": 1}
    doc1 = dict(doc2, pcId="pc_01")
    check("pc_01 이 pcId pc_02 문서 POST → 403", call2("POST", "/fs/runs/c1/items?id=x2", doc2).status == 403 and runs.get("runs/c1/items/x2") is None)
    check("pcId 없는 문서 POST → 403", call2("POST", "/fs/runs/c1/items?id=x0", {"cost": 1}).status == 403)
    check("자기 문서 POST 200", call2("POST", "/fs/runs/c1/items?id=x1", doc1).status == 200)
    check("pc_02 가 그 문서 GET → 403", call2("GET", "/fs/runs/c1/items/x1", pc="pc_02").status == 403)
    check("pc_01 은 자기 문서를 읽는다", call2("GET", "/fs/runs/c1/items/x1").json() == doc1)
    check("없는 문서 404", call2("GET", "/fs/runs/c1/items/none").status == 404)
    check("합 읽기", call2("GET", "/fs-sum?parent=runs/c1&collection=items&field=cost").json() == {"sum": 1})

    print("test_clock_skew_signed_reply - 시계")
    ahead = (time.time() + 300) * 1000
    r = call2("GET", path, now_ms=ahead)
    body = r.json() or {}
    check("300초 앞선 요청: 서명이 맞으면 서명된 401 clock", r.status == 401 and r.signed and body.get("error") == "clock", f"{r.status} {r.raw}")
    check("server_ms 는 지금과 2초 안", isinstance(body.get("server_ms"), int) and abs(body["server_ms"] - time.time() * 1000) < 2000, repr(body))
    r = call2("GET", path, now_ms=ahead, sign_key=PCS["pc_02"][0])
    check("서명이 틀리면 서명 없는 401 이고 server_ms 가 없다", r.status == 401 and r.headers.get(local_store.H_SIGN) is None and "server_ms" not in r.raw, r.raw)
    r = call2("GET", path, now_ms=(time.time() - 110) * 1000)
    check("110초 차이는 받는다 (사내 서버 허용 120초)", r.status == 200, f"{r.status} {r.raw}")
    if TASK3:
        c = local_store.Client({"standalone": True, "server_url": BASE, "key": PCS["pc_01"][0], "role": "agent",
                                "lan": True, "pc_id": "pc_01"}, clock=lambda: time.time() - 300)
        try:
            v = c.get("apps/rpa/live/c1/pc_01")
            check("300초 늦은 클라이언트도 한 번 다시 보내 성공 (Task 3)", (v or {}).get("state") == "idle"
                  and abs(getattr(c, "_skew_ms", 0) - 300000) < 5000, f"{v!r} skew={getattr(c, '_skew_ms', None)}")
        except Exception as e:
            check("300초 늦은 클라이언트도 한 번 다시 보내 성공 (Task 3)", False, repr(e))
    else:
        pending("300초 늦은 클라이언트의 한 번 다시 보내기")

    print("test_agent_stream_caps - 에이전트 구독 상한")
    held = [Stream("pc_03", "apps/rpa/commands/c1/pc_03") for _ in range(4)]
    check("한 PC 의 구독 4개는 열린다", [s.status for s in held] == [200] * 4, repr([s.status for s in held]))
    fifth = Stream("pc_03", "apps/rpa/commands/c1/pc_03")
    check("다섯 번째는 서명된 503", fifth.status == 503 and fifth.signed and json.loads(fifth.raw) == {"error": "Too many streams"},
          f"{fifth.status} {getattr(fifth, 'raw', b'')}")
    other = Stream("pc_01", "apps/rpa/commands/c1/pc_01")
    check("다른 PC 의 구독은 따로 센다", other.status == 200)
    real = srv.deploy
    srv.deploy = dataclasses.replace(local_server.LAN, agent_streams=5)
    over = Stream("pc_02", "apps/rpa/commands/c1/pc_02")
    srv.deploy = real
    check("전체 상한(agent_streams)을 넘으면 503", over.status == 503 and over.signed, over.status)
    check("남의 자리 구독은 403", Stream("pc_01", "apps/rpa/commands/c1/pc_02").status == 403)
    reg.remove("pc_03")
    check("지운 PC 의 구독은 3초 안에 끝난다", until(lambda: all(s.ended.is_set() for s in held), 3))
    for s in held:
        s.close()
    other.close()
    check("끝난 구독은 수에서 빠진다", until(lambda: "pc_03" not in srv.streams, 3), repr(getattr(srv, "streams", None)))

    print("test_disabled_pc_stream_closes - 사용 중지한 PC 의 구독")
    st = Stream("pc_02", "apps/rpa/commands/c1/pc_02")
    check("pc_02 구독 열림, 처음 값이 온다", st.status == 200 and until(lambda: any(b"event: put" in x for x in st.lines), 3))
    began = time.time()
    reg.disable("pc_02", True)
    check("사용 중지하면 3초 안에 구독이 끝난다", st.ended.wait(3), f"{time.time() - began:.1f}초")
    st.close()

    print("test_disabled_removed - 중지·지워짐")
    r = call2("GET", "/db/apps/rpa/commands/c1/pc_02.json", pc="pc_02")
    check("중지된 PC → 서명된 403 pc_disabled", r.status == 403 and r.signed and r.json() == {"error": "pc_disabled"}, f"{r.status} {r.raw}")
    if TASK3:
        c2 = local_store.Client({"standalone": True, "server_url": BASE, "key": PCS["pc_02"][0], "role": "agent", "lan": True, "pc_id": "pc_02"})
        try:
            c2.get("apps/rpa/commands/c1/pc_02")
            check("클라이언트는 AuthError PC_DISABLED (Task 3)", False, "예외 없음")
        except fb.AuthError as e:
            check("클라이언트는 AuthError PC_DISABLED (Task 3)", e.status == 403 and e.code == local_store.PC_DISABLED, repr(e))
    else:
        pending("클라이언트의 AuthError PC_DISABLED")
    reg.disable("pc_02", False)
    check("다시 사용하면 통과", call2("GET", "/db/apps/rpa/commands/c1/pc_02.json", pc="pc_02").status == 200)
    reg.remove("pc_02")
    r = call2("GET", "/db/apps/rpa/commands/c1/pc_02.json", pc="pc_02")
    check("지운 PC → 서명된 403 pc_removed", r.status == 403 and r.signed and r.json() == {"error": "pc_removed"}, f"{r.status} {r.raw}")
    if TASK3:
        try:
            c2.get("apps/rpa/commands/c1/pc_02")
            check("클라이언트는 AuthError PC_REMOVED (Task 3)", False, "예외 없음")
        except fb.AuthError as e:
            check("클라이언트는 AuthError PC_REMOVED (Task 3)", e.status == 403 and e.code == local_store.PC_REMOVED, repr(e))
    else:
        pending("클라이언트의 AuthError PC_REMOVED")
    r = call2("GET", "/db/apps/rpa/commands/c1/pc_02.json", pc="pc_02", now_ms=ahead)
    check("지운 PC 라도 시계가 틀리면 clock 이 먼저 (서명된 401)", r.status == 401 and r.signed and (r.json() or {}).get("error") == "clock")

    print("test_single_unchanged - 단독 서버")
    LIVE1 = "/db/apps/rpa/live/c1/p1.json"
    check("ap1 요청 200", call1(BASE1, "PUT", LIVE1, AGENT1, {"state": "idle"}).status == 200)
    hs = ap2_headers(AGENT1, "pc_01", "agent", "GET", LIVE1)
    check("X-AP-PC 를 실은 ap2 요청 401", send(BASE1, "GET", LIVE1, b"", hs, AGENT1).status == 401)
    r = call1(BASE1, "GET", LIVE1, AGENT1, extra={H_PC: "pc_01"})
    check("ap1 서명이 맞아도 X-AP-PC 가 있으면 401", r.status == 401 and r.headers.get(local_store.H_SIGN) is None)
    old = local_store.sign_headers(AGENT1, "agent", "GET", LIVE1, b"", now_ms=(time.time() - 90) * 1000)
    r = send(BASE1, "GET", LIVE1, b"", old, AGENT1)
    check("단독은 90초 차이도 서명 없는 401 (60초, clock 답 없음)", r.status == 401 and r.headers.get(local_store.H_SIGN) is None and "server_ms" not in r.raw)
    check("단독의 구독은 상한을 세지 않는다", srv1.deploy.agent_streams == 0)
finally:
    for s in (srv, srv1):
        if s is not None:
            try:
                s.shutdown()
                s.server_close()
            except Exception:
                pass
    try:
        runs.close()
    except Exception:
        pass
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n실패: {len(fails)}" + (f" ({', '.join(fails)})" if fails else "") + ("" if TASK3 else "  (Task 3 기다리는 시험은 [보류])"))
sys.exit(1 if fails else 0)
