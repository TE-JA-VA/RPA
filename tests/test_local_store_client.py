# -*- coding: utf-8 -*-
"""스탠드얼론: 로컬 서버에 붙는 클라이언트(local_store)가 fb.Client 와 같은 꼴로 도는가, 설정 읽기·인증번호 연결 (계획 ① Task 4).
    .venv\\Scripts\\python.exe tests\\test_local_store_client.py
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
import update_sign  # noqa: E402
import license_check  # noqa: E402
import fb  # noqa: E402
import local_server  # noqa: E402
import local_store  # noqa: E402
import secret  # noqa: E402
import agent  # noqa: E402
import otp_relay  # noqa: E402

fails = []
TMP = tempfile.mkdtemp(prefix="rpa_lcli_")
PD = os.path.join(TMP, "pd")
LIC = {"edition": "standalone", "company": "시험상사", "cid": "c1", "pc_id": "p1", "issued": "2026-11-23",
       "modules": {}, "features": {"wellife": False}, "limits": {"schedule": 3, "presets": None, "parallel": None}}
ENV = ("RPA_PROGRAMDATA", "RPA_EDITION", "RPA_MACHINE_GUID", "RPA_LOCAL_PORT")
saved_env = {k: os.environ.get(k) for k in ENV}
saved_pub = license_check.LICENSE_PUBLIC_KEY_HEX


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def expect(name, exc, status, fn):
    try:
        got = fn()
    except exc as e:
        check(name, status is None or getattr(e, "status", None) == status, f"status={getattr(e, 'status', None)}")
    except Exception as e:
        check(name, False, f"{type(e).__name__}: {e}")
    else:
        check(name, False, f"예외 없이 {got!r}")


def wait_until(fn, seconds=5):
    end = time.time() + seconds
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.05)
    return False


try:
    folder = os.path.join(PD, "standalone")
    os.makedirs(folder)
    store = local_server.Store(os.path.join(folder, "store.json"), volatile=local_server.VOLATILE)
    runs = local_server.Runs(os.path.join(folder, "runs.db"))
    AGENT, RELAY = local_server.ensure_keys(folder)
    import local_phone  # noqa: E402
    phone = local_phone.Service(folder, store, LIC)       # 인증번호 요청은 짝지은 휴대폰에만 (계획 ④ Task 1)
    phone.phones.add("ph1", "민기 휴대폰", "", [], key="k" * 64, fp="f" * 64, os="android", app_version="t", device="t")
    srv = local_server.make_server(store, runs, LIC, (AGENT, RELAY), port=0, phone=phone)
    port = srv.server_address[1]
    url = f"http://127.0.0.1:{port}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    CFG = {"standalone": True, "server_url": url, "key": AGENT, "cid": "c1", "pc_id": "p1"}

    print("자리 읽고 쓰기")
    c = local_store.Client(CFG)
    c.put("apps/rpa/live/c1/p1", {"state": "idle"})
    check("put/get", c.get("apps/rpa/live/c1/p1") == {"state": "idle"})
    c.patch("apps/rpa/live/c1/p1", {"state": "running", "heartbeat/at": 3})
    check("patch (여러 자리)", c.get("apps/rpa/live/c1/p1") == {"state": "running", "heartbeat": {"at": 3}})
    c.delete("apps/rpa/live/c1/p1/heartbeat")
    check("delete", c.get("apps/rpa/live/c1/p1") == {"state": "running"})
    check("없는 자리는 None", c.get("apps/rpa/live/c1/p1/none") is None)
    expect("다른 PC 는 HttpError 403", fb.HttpError, 403, lambda: c.put("apps/rpa/live/c1/p2", {}))
    try:
        c.get("apps/rpa/aikey/c1/key")
        check("거절 본문은 Permission denied", False)
    except fb.HttpError as e:
        check("거절 본문은 Permission denied", "Permission denied" in (e.body or ""))
    bad = local_store.Client(dict(CFG, key="x" * 43))
    try:
        bad.get("apps/rpa/live/c1/p1")
        check("틀린 열쇠는 AuthError", False)
    except fb.AuthError as e:
        check("틀린 열쇠는 AuthError (서버의 답을 확인하지 못함)", e.status == 0 and e.code == local_store.NOT_VERIFIED and "x" * 43 not in str(e))
    check("server_now", abs(c.server_now() - time.time()) < 5)
    check("token·renew 는 있기만 하다 (열쇠를 내주지 않는다)", c.token() == "" and c.renew() is None)
    check("질의 (대기 중만)", c.get("apps/rpa/commands/c1/p1", {"orderBy": '"state"', "equalTo": '"queued"'}) is None)

    print("실행 기록")
    doc = {"run_id": "d1", "pcId": "p1", "date": "2026-11-23", "started_at": "2026-11-23T09:00:00", "cost": 4,
           "used": {"login": 1}, "steps": [{"name": "로그인", "ok": True}], "note": None}
    check("fs_create (Firestore 꼴 칸을 풀어 보낸다)", c.fs_create("runs/c1/items", fb.fs_fields(doc), "d1") is True)
    check("같은 id 는 False", c.fs_create("runs/c1/items", fb.fs_fields(doc), "d1") is False)
    back = c.fs_get("runs/c1/items/d1")
    # 일반 버전에서 Firestore 에 들어가는 값과 같다 (fs_fields 는 목록을 JSON 글로 싣는다 - 화면이 지금처럼 읽는다)
    check("fs_get - Firestore 에 들어가던 값 그대로", back is not None and back["cost"] == 4 and back["used"] == {"login": 1}
          and back == {k: fb.fs_value(v) for k, v in fb.fs_fields(doc).items()}, repr(back))
    check("없는 문서는 None", c.fs_get("runs/c1/items/none") is None)
    check("fs_sum", c.fs_sum("runs/c1", "items", "cost") == 4 and c.fs_sum("runs/c1", "items", "cost", "2026-11-24T00:00:00") == 0)
    expect("통장 자리는 403", fb.HttpError, 403, lambda: c.fs_get("wallet/c1"))

    print("에이전트 코드가 그대로 돈다")
    up = agent.Uploader(c, "c1", "p1", queue_path=os.path.join(TMP, "queue.jsonl"))
    check("Uploader.push_live", up.push_live({"state": "idle", "programs": {}}) is True and c.get("apps/rpa/live/c1/p1")["state"] == "idle")
    check("Uploader.push_run", up.push_run(dict(doc, run_id="d2")) is True and c.fs_get("runs/c1/items/d2")["run_id"] == "d2")
    store.put("apps/rpa/commands/c1/p1/k1", {"state": "queued", "type": "set_parallel", "args": {"n": 1}, "by": "web",
                                              "created_at": int(time.time()), "expires_at": int(time.time()) + 600})
    done = []
    cmds = agent.Commands(c, "c1", "p1", {"set_parallel": lambda args: done.append(args) or "끝"}, up=up)
    seen = []

    def on_command(cmd_id, cmd):
        seen.append(cmd_id)
        cmds.handle(cmd_id, cmd)

    ended = []
    t = threading.Thread(target=lambda: ended.append(agent.watch_commands(c, "apps/rpa/commands/c1/p1", on_command)), daemon=True)
    t.start()
    check("대기 중 명령을 받는다", wait_until(lambda: "k1" in seen))
    check("명령이 돌고 done 으로", wait_until(lambda: (store.get("apps/rpa/commands/c1/p1/k1") or {}).get("state") == "done")
          and done == [{"n": 1}], repr(store.get("apps/rpa/commands/c1/p1/k1")))
    store.put("apps/rpa/commands/c1/p1/k2", {"state": "queued", "type": "set_parallel", "args": {"n": 2}, "by": "web",
                                              "created_at": int(time.time()), "expires_at": int(time.time()) + 600})
    check("구독 중에 온 새 명령도 받는다", wait_until(lambda: "k2" in seen and len(done) == 2))
    store.put("apps/rpa/commands/c1/p1/old", {"state": "done", "type": "set_parallel", "created_at": 5, "expires_at": 6})
    check("지난 명령 정리", agent.cleanup_commands(c, "c1", "p1", time.time()) == 1 and store.get("apps/rpa/commands/c1/p1/old") is None
          and store.get("apps/rpa/commands/c1/p1/k1") is not None)
    store.put("apps/rpa/commands/c1/p1/stuck", {"state": "running", "type": "set_parallel", "created_at": int(time.time()), "expires_at": 9e9})
    check("끝나지 못한 명령 닫기", agent.fail_stale_slow(c, "c1", "p1", time.time()) == 1
          and store.get("apps/rpa/commands/c1/p1/stuck")["state"] == "failed")
    check("업체 정책 읽기", agent.company_policy(c, "c1")[0] == 3 and agent.company_modules(c, "c1") == {})

    print("인증번호 중계 (같은 PhoneRelay)")
    rc = local_store.Client(dict(CFG, key=RELAY, role="relay"))
    relay = otp_relay.PhoneRelay(rc, "c1", "p1", "ph1", ["010-1234-5678"], "시험몰")
    req_id = relay.open(tick=lambda s: None)
    req = store.get("apps/otp/requests/c1/ph1/current")
    check("요청이 열린다 (서버 시각)", isinstance(req, dict) and req["req_id"] == req_id and isinstance(req["created_at"], int)
          and req["senders"] == {"01012345678": True}, repr(req))
    store.put("apps/otp/codes/c1/ph1/current", {"req_id": req_id, "code": "482913", "written_at": int(time.time() * 1000)})     # 휴대폰 창구처럼 쓴 시각 (검토 I-1)
    check("번호를 받는다", relay.wait(req_id, 2, tick=time.sleep) == "482913")
    relay.close(req_id)
    check("끝나면 번호·요청을 지운다", store.get("apps/otp/codes/c1/ph1") is None and store.get("apps/otp/requests/c1/ph1") is None)

    print("고르기 · 주소")
    check("client_for - 스탠드얼론", isinstance(local_store.client_for(CFG), local_store.Client))
    check("client_for - 일반", isinstance(local_store.client_for({"database_url": "https://x.example", "api_key": "k",
                                                              "email": "a@b.c", "password": "p", "project_id": "p"}), fb.Client))
    expect("이 PC 가 아닌 주소는 거절", ValueError, None, lambda: local_store.Client(dict(CFG, server_url="http://10.0.0.5:8781")))
    expect("https 가 아닌 꼴·빈 주소 거절", ValueError, None, lambda: local_store.Client(dict(CFG, server_url="")))
    expect("열쇠 없는 설정 거절", ValueError, None, lambda: local_store.Client(dict(CFG, key="")))

    print("설정 읽기 (secret.load_config)")
    lic_secret, lic_public = update_sign.keygen()
    license_check.LICENSE_PUBLIC_KEY_HEX = lic_public.hex()
    os.environ.update(RPA_PROGRAMDATA=PD, RPA_EDITION="standalone", RPA_MACHINE_GUID="p1", RPA_LOCAL_PORT=str(port))
    try:
        secret.load_config()
        check("라이선스가 없으면 LicenseError", False)
    except license_check.LicenseError as e:
        check("라이선스가 없으면 LicenseError", "라이선스 파일이 없습니다" in str(e) and isinstance(e, ValueError))
    with open(os.path.join(PD, "license.json"), "w", encoding="utf-8") as f:
        json.dump(license_check.sign_body(lic_secret, LIC), f, ensure_ascii=False)
    cfg = secret.load_config()
    check("에이전트 설정", cfg["standalone"] is True and cfg["key"] == AGENT and (cfg["cid"], cfg["pc_id"]) == ("c1", "p1")
          and cfg["server_url"] == url and cfg["license"]["limits"]["schedule"] == 3)
    check("중계 설정은 다른 열쇠·다른 역할", secret.load_config(role="relay")["key"] == RELAY
          and secret.load_config(role="relay")["role"] == "relay" and cfg["role"] == "agent")
    check("그 설정으로 붙는다", local_store.client_for(cfg).get("apps/rpa/live/c1/p1")["state"] == "idle")
    check("열쇠 자리 = 서버 자료 폴더", local_store.keys_dir() == local_server.data_dir())
    check("옵저버·ACTOR 의 중계 설정", otp_relay.relay_config()["key"] == RELAY)
    phone.phones.add("ph2", "", "이름 없는 것", [], key="j" * 64, fp="f" * 64, os="android", app_version="t", device="t")
    check("휴대폰 목록 (이름순, 이름이 없으면 코드)", otp_relay.phone_list() == sorted([("ph1", "민기 휴대폰"), ("ph2", "ph2")], key=lambda x: x[1]),
          repr(otp_relay.phone_list()))
    r2 = otp_relay.agent_relay("ph1", ["0212345678"], "시험몰")
    check("agent_relay 는 로컬 서버로", isinstance(r2.client, local_store.Client) and r2.cid == "c1" and r2.pc_id == "p1")
    os.rename(os.path.join(folder, "relay.key"), os.path.join(folder, "relay.key.x"))
    try:
        otp_relay.agent_relay("ph1", [], "시험몰")
        check("열쇠가 없으면 사람 말", False)
    except RuntimeError as e:
        check("열쇠가 없으면 사람 말", "인증번호를 수신할 수 없습니다" in str(e))
    try:
        secret.load_config(role="relay")
        check("열쇠 파일 없음은 FileNotFoundError", False)
    except FileNotFoundError:
        check("열쇠 파일 없음은 FileNotFoundError", True)
    os.rename(os.path.join(folder, "relay.key.x"), os.path.join(folder, "relay.key"))
    os.environ["RPA_EDITION"] = "cloud"
    try:
        secret.load_config(os.path.join(TMP, "none.json"))
        check("일반 버전은 옛 길 그대로", False)
    except FileNotFoundError:
        check("일반 버전은 옛 길 그대로", True)

    print("포트를 다른 프로그램이 먼저 잡았을 때 (검토 2026-11-23 1번)")
    import http.server
    seen_headers, hits = [], []

    class Fake(http.server.BaseHTTPRequestHandler):
        """우리 서버인 척하는 프로그램 - 무엇이든 받아 주고, 구독에는 가짜 명령을 내려 준다."""

        def log_message(self, *a):
            pass

        def _any(self):
            seen_headers.append({k: v for k, v in self.headers.items()})
            hits.append((self.command, self.path))
            n = int(self.headers.get("Content-Length") or 0)
            if n:
                self.rfile.read(n)
            if "text/event-stream" in (self.headers.get("Accept") or ""):
                evil = {"path": "/", "data": {"evil1": {"state": "queued", "type": "set_parallel", "args": {"parallel": 1},
                                                      "by": "web", "created_at": int(time.time()), "expires_at": int(time.time()) + 600}}}
                body = ("event: put\ndata: " + json.dumps(evil) + "\n\n").encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(body)
                return
            status = 403 if "refuse" in self.path else 200
            body = b'{"error": "Permission denied"}' if status == 403 else b"{}"
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        do_GET = do_PUT = do_PATCH = do_DELETE = do_POST = _any

    fake = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=fake.serve_forever, daemon=True).start()
    fcfg = dict(CFG, server_url=f"http://127.0.0.1:{fake.server_address[1]}")
    fc = local_store.Client(fcfg)

    def not_verified(fn):
        try:
            fn()
        except fb.AuthError as e:
            return e.status == 0 and e.code == local_store.NOT_VERIFIED
        except Exception as e:
            return f"{type(e).__name__}: {e}"
        return "예외 없음"

    check("가짜가 준 값은 쓰지 않는다 (읽기)", not_verified(lambda: fc.get("apps/rpa/live/c1/p1")) is True)
    check("가짜가 '받았다' 해도 믿지 않는다 (쓰기)", not_verified(lambda: fc.put("apps/rpa/live/c1/p1", {"state": "idle"})) is True)
    check("가짜의 거절(4xx)을 '내용 거부' 로 보지 않는다", not_verified(lambda: fc.put("apps/rpa/live/c1/p1/refuse", 1)) is True)
    got_cmds = []
    check("가짜가 내려 준 명령은 실행되지 않는다", not_verified(lambda: agent.watch_commands(fc, "apps/rpa/commands/c1/p1",
                                                                              lambda i, cmd: got_cmds.append(i))) is True and got_cmds == [])
    fup = agent.Uploader(fc, "c1", "p1", queue_path=os.path.join(TMP, "queue_fake.jsonl"))
    check("실행 기록을 버리지 않는다 (에이전트가 멈춘다)", not_verified(lambda: fup.push_run(dict(doc, run_id="d9"))) is True)
    began = time.time()
    frelay = otp_relay.PhoneRelay(local_store.Client(dict(fcfg, key=RELAY, role="relay")), "c1", "p1", "ph1", ["01012345678"], "시험몰")
    check("인증번호 요청도 곧바로 멈춘다 (2분을 기다리지 않는다)", not_verified(lambda: frelay.open(tick=lambda s: None)) is True and time.time() - began < 5)
    blob = json.dumps(seen_headers) + json.dumps(hits)
    check("가짜에게 열쇠가 넘어가지 않는다", len(seen_headers) >= 5 and AGENT not in blob and RELAY not in blob)
    check("보낸 것은 역할·시각·nonce·서명뿐", all(local_store.H_SIGN.lower() in {k.lower() for k in h} and "authorization" not in {k.lower() for k in h}
                                         for h in seen_headers))
    fake.shutdown()
    fake.server_close()

    print("서버가 꺼지면")
    began = time.time()
    srv.shutdown()
    srv.server_close()
    t.join(8)
    check("구독이 끝난다 (다시 붙게)", ended == ["ended"] and time.time() - began < 6, f"{ended} {time.time() - began:.1f}초")
    try:
        c.get("apps/rpa/live/c1/p1")
        check("꺼진 서버는 망 오류 (큐에 쌓는 쪽)", False)
    except fb.AuthError:
        check("꺼진 서버는 망 오류 (큐에 쌓는 쪽)", False, "AuthError")
    except OSError:
        check("꺼진 서버는 망 오류 (큐에 쌓는 쪽)", True)

    # --- 사내 서버 ① Task 3: ap2 서명·시계 맞추기·중지/지워짐·등록 (서버 없이 opener 를 바꿔 끼운다) ---------
    import email.message  # noqa: E402
    import io  # noqa: E402
    import urllib.error  # noqa: E402
    import pc_registry  # noqa: E402

    KEY2 = "k" * 64
    LAN_CFG = {"standalone": True, "lan": True, "server_url": "http://127.0.0.1:8781", "key": KEY2, "cid": "c1", "pc_id": "pc_01"}

    def hdr(req, name):
        return req.get_header(name.capitalize())      # urllib.request.Request 는 머리글 이름을 capitalize 해 둔다

    def msg(sign=None):
        m = email.message.Message()
        m["Content-Type"] = "application/json"
        if sign:
            m[local_store.H_SIGN] = sign
        return m

    class Resp:
        def __init__(self, status, body, headers):
            self.status, self._body, self.headers = status, body, headers

        def read(self):
            return self._body

        def close(self):
            pass

    def reply(req, status, obj, key=KEY2, signed=True):
        """가짜 서버의 답 - 2xx 는 응답, 그 밖은 HTTPError. signed 면 그 요청의 nonce 로 서명한다."""
        raw = json.dumps(obj).encode("utf-8")
        sign = local_store.response_mac(key, hdr(req, local_store.H_NONCE), status, raw) if signed else None
        if 200 <= status < 300:
            return Resp(status, raw, msg(sign))
        raise urllib.error.HTTPError(req.full_url, status, "x", msg(sign), io.BytesIO(raw))

    print("ap2 서명 머리글")
    h = local_store.sign_headers("k" * 43, "agent", "GET", "/db/x.json", b"", now_ms=1000, nonce="n" * 32, pc_id="pc_01")
    check("PC 번호 머리글", h[local_store.H_PC] == "pc_01")
    check("ap2 서명", h[local_store.H_SIGN] == local_store.request_mac2("k" * 43, "pc_01", "agent", "GET", "/db/x.json", "1000", "n" * 32, b""))
    check("ap2 서명은 ap1 과 다르다", h[local_store.H_SIGN] != local_store.request_mac("k" * 43, "agent", "GET", "/db/x.json", "1000", "n" * 32, b""))
    h1 = local_store.sign_headers("k" * 43, "agent", "GET", "/db/x.json", b"", now_ms=1000, nonce="n" * 32)
    check("pc_id 없으면 지금 ap1 그대로·머리글 없음", local_store.H_PC not in h1
          and h1 == {local_store.H_ROLE: "agent", local_store.H_TIME: "1000", local_store.H_NONCE: "n" * 32,
                     local_store.H_SIGN: local_store.request_mac("k" * 43, "agent", "GET", "/db/x.json", "1000", "n" * 32, b"")})

    print("시계 차이 - 서명된 401 clock 이면 한 번만 다시 보낸다")
    AHEAD = 300000
    calls = []

    def clock_opener(req, timeout=30):
        calls.append(req)
        ts = int(hdr(req, local_store.H_TIME))
        mac = local_store.request_mac2(KEY2, "pc_01", "agent", req.get_method(), req.selector, hdr(req, local_store.H_TIME),
                                       hdr(req, local_store.H_NONCE), req.data or b"")
        if hdr(req, local_store.H_PC) != "pc_01" or hdr(req, local_store.H_SIGN) != mac:
            return reply(req, 401, {"error": "Unauthorized"}, signed=False)
        server_ms = int(time.time() * 1000) + AHEAD
        if abs(server_ms - ts) > 120000:
            return reply(req, 401, {"error": "clock", "server_ms": server_ms})
        return reply(req, 200, {"state": "idle"})

    lc = local_store.Client(LAN_CFG, opener=clock_opener)
    check("처음 차이는 0", lc._skew_ms == 0)
    try:
        got = lc.get("apps/rpa/live/c1/pc_01")
    except Exception as e:
        got = f"{type(e).__name__}: {e}"
    check("다시 보낸 요청이 성공한다", got == {"state": "idle"}, repr(got))
    check("opener 는 정확히 2번", len(calls) == 2, len(calls))
    check("다시 보낸 요청의 시각이 서버에 맞다", len(calls) == 2 and abs(int(hdr(calls[1], local_store.H_TIME)) - int(time.time() * 1000) - AHEAD) < 5000)
    check("다시 보낸 요청은 새 nonce", len(calls) == 2 and hdr(calls[0], local_store.H_NONCE) != hdr(calls[1], local_store.H_NONCE))
    check("차이를 기억한다 (다음 요청은 한 번에)", abs(lc._skew_ms - AHEAD) < 5000 and (calls.clear() or lc.get("apps/rpa/live/c1/pc_01")) == {"state": "idle"}
          and len(calls) == 1)

    calls.clear()

    def always_clock(req, timeout=30):
        calls.append(req)
        return reply(req, 401, {"error": "clock", "server_ms": int(time.time() * 1000) + 10 ** 9})

    expect("두 번째도 clock 이면 더 보내지 않고 HttpError 401", fb.HttpError, 401,
           lambda: local_store.Client(LAN_CFG, opener=always_clock).get("apps/x"))
    check("한 번만 다시 보냈다", len(calls) == 2, len(calls))

    calls.clear()

    def unsigned_clock(req, timeout=30):
        calls.append(req)
        return reply(req, 401, {"error": "clock", "server_ms": int(time.time() * 1000) + AHEAD}, signed=False)

    try:
        local_store.Client(LAN_CFG, opener=unsigned_clock).get("apps/x")
        check("서명 없는 clock 은 AuthError(NOT_VERIFIED)", False)
    except fb.AuthError as e:
        check("서명 없는 clock 은 AuthError(NOT_VERIFIED)", e.status == 0 and e.code == local_store.NOT_VERIFIED)
    check("서명 없는 clock 은 다시 보내지 않는다", len(calls) == 1, len(calls))

    calls.clear()

    def other_key_clock(req, timeout=30):
        calls.append(req)
        return reply(req, 401, {"error": "clock", "server_ms": int(time.time() * 1000) + AHEAD}, key="z" * 64)

    expect("다른 열쇠로 서명한 clock 도 AuthError", fb.AuthError, 0, lambda: local_store.Client(LAN_CFG, opener=other_key_clock).get("apps/x"))
    check("다른 열쇠 clock 도 다시 보내지 않는다", len(calls) == 1, len(calls))

    calls.clear()
    for bad_body in ({"error": "clock"}, {"error": "clock", "server_ms": "1"}, {"error": "clock", "server_ms": True}, {"error": "Unauthorized"}):
        def odd_clock(req, timeout=30, body=bad_body):
            calls.append(req)
            return reply(req, 401, body)
        expect(f"꼴이 틀린 서명된 401 은 HttpError 401 ({bad_body})", fb.HttpError, 401,
               lambda: local_store.Client(LAN_CFG, opener=odd_clock).get("apps/x"))
    check("꼴이 틀린 401 은 다시 보내지 않는다", len(calls) == 4, len(calls))

    print("시계 차이 - 단독(나)은 다시 보내지 않는다")
    calls.clear()
    single = local_store.Client(dict(LAN_CFG, lan=False, pc_id="p1"), opener=always_clock)
    expect("lan 없는 Client 는 서명된 401 clock 도 HttpError 401", fb.HttpError, 401, lambda: single.get("apps/x"))
    check("단독은 한 번만 보냈고 차이를 바꾸지 않는다", len(calls) == 1 and single._skew_ms == 0, f"{len(calls)} {single._skew_ms}")
    check("단독 요청에는 PC 번호 머리글이 없다 (ap1)", calls and hdr(calls[0], local_store.H_PC) is None
          and hdr(calls[0], local_store.H_SIGN) == local_store.request_mac(KEY2, "agent", "GET", calls[0].selector, hdr(calls[0], local_store.H_TIME),
                                                                           hdr(calls[0], local_store.H_NONCE), b""))

    print("시계 차이 - 구독도 차이를 더해 서명하고, 열 때 clock 이면 한 번 다시 연다")
    calls.clear()

    class StreamResp(Resp):
        def __iter__(self):
            return iter([])

    def stream_opener(req, timeout=30):
        calls.append(req)
        ts = int(hdr(req, local_store.H_TIME))
        server_ms = int(time.time() * 1000) + AHEAD
        if abs(server_ms - ts) > 120000:
            return reply(req, 401, {"error": "clock", "server_ms": server_ms})
        sign = local_store.response_mac(KEY2, hdr(req, local_store.H_NONCE), 200, b"")
        return StreamResp(200, b"", msg(sign))

    sc = local_store.Client(LAN_CFG, opener=stream_opener)
    try:
        got = list(sc.stream("apps/rpa/commands/c1/pc_01"))
    except Exception as e:
        got = f"{type(e).__name__}: {e}"
    check("구독이 열린다 (두 번째에)", got == [] and len(calls) == 2, f"{got!r} {len(calls)}")
    calls.clear()
    list(sc.stream("apps/rpa/commands/c1/pc_01"))
    check("다음 구독은 차이를 더해 한 번에", len(calls) == 1)

    print("사용 중지·지워짐")
    for body, code in (({"error": "pc_disabled"}, local_store.PC_DISABLED), ({"error": "pc_removed"}, local_store.PC_REMOVED)):
        def st_opener(req, timeout=30, body=body):
            return reply(req, 403, body)
        try:
            local_store.Client(LAN_CFG, opener=st_opener).put("apps/rpa/live/c1/pc_01", {"state": "idle"})
            check(f"서명된 403 {body['error']} → AuthError", False)
        except fb.AuthError as e:
            check(f"서명된 403 {body['error']} → AuthError", e.status == 403 and e.code == code, f"{e.status} {e.code}")
        except Exception as e:
            check(f"서명된 403 {body['error']} → AuthError", False, f"{type(e).__name__}: {e}")
    expect("그 밖의 서명된 403 은 지금처럼 HttpError", fb.HttpError, 403,
           lambda: local_store.Client(LAN_CFG, opener=lambda req, timeout=30: reply(req, 403, {"error": "Permission denied"})).get("apps/x"))
    expect("서명 없는 403 pc_disabled 는 AuthError(NOT_VERIFIED)", fb.AuthError, 0,
           lambda: local_store.Client(LAN_CFG, opener=lambda req, timeout=30: reply(req, 403, {"error": "pc_disabled"}, signed=False)).get("apps/x"))

    print("사내 서버 설정은 PC 번호가 있어야 한다")
    expect("lan 인데 pc_id 없음 → ValueError", ValueError, None, lambda: local_store.Client({k: v for k, v in LAN_CFG.items() if k != "pc_id"}))
    expect("lan 인데 pc_id 가 p1 → ValueError", ValueError, None, lambda: local_store.Client(dict(LAN_CFG, pc_id="p1")))
    expect("lan 인데 pc_id 가 pc_1 → ValueError", ValueError, None, lambda: local_store.Client(dict(LAN_CFG, pc_id="pc_1")))
    check("lan 없으면 pc_id 꼴을 보지 않는다", isinstance(local_store.Client(dict(LAN_CFG, lan=False, pc_id="p1")), local_store.Client))

    print("등록 (enroll)")
    TOKEN, RAND, GUID, HOST = "t" * 43, "cd" * 32, "12345678-1234-1234-1234-1234567890ab", "OFFICE-1"
    NONCE = "e" * 32
    ETEXT = pc_registry.encode_enrollment({"v": 1, "url": "http://127.0.0.1:8781", "pc": "pc_01", "token": TOKEN, "exp": 1})
    WANT_AGENT, WANT_RELAY = pc_registry.derive_keys(TOKEN, RAND)
    sent = []

    def enroll_opener(sign_key):
        def op(req, timeout=30):
            sent.append(req)
            b = json.loads(req.data.decode("utf-8"))
            ok = (req.get_method() == "POST" and req.full_url == "http://127.0.0.1:8781/enroll"
                  and b == {"v": 1, "pc": "pc_01", "rand": RAND, "guid": GUID, "host": HOST, "nonce": NONCE,
                            "proof": pc_registry.enroll_proof(TOKEN, "pc_01", RAND, GUID, HOST)})
            if not ok:
                return reply(req, 403, {"error": "bad_proof"}, signed=False)
            raw = json.dumps({"pc": "pc_01"}).encode("utf-8")
            return Resp(200, raw, msg(local_store.response_mac(sign_key, b["nonce"], 200, raw)))
        return op

    try:
        got = local_store.enroll("  " + ETEXT + "\n", GUID, HOST, opener=enroll_opener(WANT_AGENT), rand_hex=RAND, nonce=NONCE)
    except Exception as e:
        got = f"{type(e).__name__}: {e}"
    check("등록 - 돌려준 열쇠가 derive_keys 와 같다", got == {"server_url": "http://127.0.0.1:8781", "pc_id": "pc_01",
                                                         "agent_key": WANT_AGENT, "relay_key": WANT_RELAY}, repr(got))
    check("등록 요청에 서명 머리글·토큰이 없다", sent and hdr(sent[0], local_store.H_SIGN) is None and TOKEN not in sent[0].data.decode("utf-8"))
    try:
        local_store.enroll(ETEXT, GUID, HOST, opener=enroll_opener("z" * 64), rand_hex=RAND, nonce=NONCE)
        check("다른 열쇠로 서명한 등록 답은 AuthError(NOT_VERIFIED)", False)
    except fb.AuthError as e:
        check("다른 열쇠로 서명한 등록 답은 AuthError(NOT_VERIFIED)", e.status == 0 and e.code == local_store.NOT_VERIFIED)
    try:
        local_store.enroll(ETEXT, GUID, "OTHER", opener=enroll_opener(WANT_AGENT), rand_hex=RAND, nonce=NONCE)
        check("서버 거절은 HttpError (본문의 error 코드 그대로)", False)
    except fb.HttpError as e:
        check("서버 거절은 HttpError (본문의 error 코드 그대로)", e.status == 403 and json.loads(e.body)["error"] == "bad_proof", e.body)
    expect("등록 글 꼴이 틀리면 ValueError", ValueError, None, lambda: local_store.enroll("APE1.@@@", GUID, HOST, opener=enroll_opener(WANT_AGENT)))
    r = []

    def capture(req, timeout=30):
        r.append(json.loads(req.data.decode("utf-8")))
        return reply(req, 403, {"error": "unknown"}, signed=False)

    expect("난수·nonce 를 안 주면 새로 만든다", fb.HttpError, 403, lambda: local_store.enroll(ETEXT, GUID, HOST, opener=capture))
    check("만든 난수 64자·nonce 32자 hex", r and len(r[0]["rand"]) == 64 and len(r[0]["nonce"]) == 32
          and all(ch in "0123456789abcdef" for ch in r[0]["rand"] + r[0]["nonce"]))

    # --- 사내 서버 ② Task 5: https 는 우리 인증 기관만 믿기, 사설 주소 규칙, 등록 글의 인증 기관 ---------
    import ssl  # noqa: E402
    import lan_ca  # noqa: E402
    CA_DIR = os.path.join(TMP, "lan_ca")
    lan_ca.make_ca(CA_DIR, ["nt"], ["10.1.2.3"])
    CA = lan_ca.ca_pem(CA_DIR)
    HTTPS_CFG = dict(LAN_CFG, server_url="https://10.1.2.3:8444", ca_pem=CA)

    print("test_lan_https_needs_ca")
    expect("lan https 인데 ca_pem 없음 → ValueError", ValueError, None,
           lambda: local_store.Client({k: v for k, v in HTTPS_CFG.items() if k != "ca_pem"}))
    expect("lan https 인데 ca_pem 이 빈 글 → ValueError", ValueError, None, lambda: local_store.Client(dict(HTTPS_CFG, ca_pem="")))
    expect("lan https 인데 ca_pem 이 인증서가 아님 → ValueError", ValueError, None,
           lambda: local_store.Client(dict(HTTPS_CFG, ca_pem="-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n")))
    expect("lan 없는 https 는 지금처럼 ValueError", ValueError, None, lambda: local_store.Client(dict(HTTPS_CFG, lan=False)))
    expect("lan http 는 지금처럼 127.0.0.1 만 (사내 주소 → ValueError)", ValueError, None,
           lambda: local_store.Client(dict(LAN_CFG, server_url="http://10.1.2.3:8444")))
    hc = local_store.Client(HTTPS_CFG)
    ctx = getattr(hc, "_ctx", None)
    check("만든 컨텍스트는 이름 확인·인증서 확인을 켠다", isinstance(ctx, ssl.SSLContext) and ctx.check_hostname
          and ctx.verify_mode == ssl.CERT_REQUIRED)
    check("믿는 인증 기관은 우리 것 하나뿐 (윈도우 신뢰 저장소를 읽지 않는다)", ctx is not None and len(ctx.get_ca_certs()) == 1)
    check("http 단독 Client 는 TLS 컨텍스트가 없다", getattr(local_store.Client(CFG), "_ctx", "없음") is None)

    print("test_lan_public_ip_refused")
    for u in ("https://8.8.8.8:8444", "https://0.0.0.0:8444", "https://169.254.1.1:8444", "https://[2001:4860::8888]:8444",
              "https://[::ffff:8.8.8.8]:8444", "https://:8444", "ftp://10.1.2.3:8444"):
        expect(f"{u} → ValueError", ValueError, None, lambda u=u: local_store.Client(dict(HTTPS_CFG, server_url=u)))
    for u in ("https://10.1.2.3:8444", "https://192.168.1.230:8444", "https://172.16.0.9:8444", "https://127.0.0.1:8444",
              "https://nt:8444", "https://ap.corp.local:8444", "https://[fd00::5]:8444", "https://[::1]:8444"):
        try:
            ok = isinstance(local_store.Client(dict(HTTPS_CFG, server_url=u)), local_store.Client)
        except Exception as e:
            ok = f"{type(e).__name__}: {e}"
        check(f"{u} → 만들어짐", ok is True, ok)

    print("인증서 확인 실패는 AuthError(0, CERT_FAILED), 다른 연결 오류는 그대로")
    check("CERT_FAILED 상수", getattr(local_store, "CERT_FAILED", None) == "SERVER_CERT_FAILED")
    bad_cert = ssl.SSLCertVerificationError(1, "certificate verify failed")
    for name, exc in (("URLError 로 싼 인증서 오류", urllib.error.URLError(bad_cert)), ("인증서 오류 그대로", bad_cert)):
        def cert_opener(req, timeout=30, exc=exc):
            raise exc
        try:
            local_store.Client(HTTPS_CFG, opener=cert_opener).get("apps/x")
            check(f"{name} → AuthError(0, CERT_FAILED)", False, "예외 없음")
        except fb.AuthError as e:
            check(f"{name} → AuthError(0, CERT_FAILED)", e.status == 0 and e.code == getattr(local_store, "CERT_FAILED", "?"), repr(e))
        except Exception as e:
            check(f"{name} → AuthError(0, CERT_FAILED)", False, f"{type(e).__name__}: {e}")
        try:
            list(local_store.Client(HTTPS_CFG, opener=cert_opener).stream("apps/rpa/commands/c1/pc_01"))
            check(f"구독도 {name} → AuthError(0, CERT_FAILED)", False, "예외 없음")
        except fb.AuthError as e:
            check(f"구독도 {name} → AuthError(0, CERT_FAILED)", e.code == getattr(local_store, "CERT_FAILED", "?"), repr(e))
        except Exception as e:
            check(f"구독도 {name} → AuthError(0, CERT_FAILED)", False, f"{type(e).__name__}: {e}")

    def refused_opener(req, timeout=30):
        raise urllib.error.URLError(ConnectionRefusedError(10061, "refused"))
    expect("연결 거절은 지금처럼 URLError (큐에 쌓는 쪽)", urllib.error.URLError, None,
           lambda: local_store.Client(HTTPS_CFG, opener=refused_opener).get("apps/x"))
    expect("다른 TLS 오류(인증서 확인이 아님)는 그대로", urllib.error.URLError, None,
           lambda: local_store.Client(HTTPS_CFG, opener=lambda req, timeout=30: (_ for _ in ()).throw(
               urllib.error.URLError(ssl.SSLError(1, "handshake failure")))).get("apps/x"))

    print("https 등록 (enroll) - 등록 글의 인증 기관")
    HTEXT = pc_registry.encode_enrollment({"v": 1, "url": "https://10.1.2.3:8444", "pc": "pc_01", "token": TOKEN, "exp": 1, "ca": CA})
    hsent = []

    def https_enroll(req, timeout=30):
        hsent.append(req)
        b = json.loads(req.data.decode("utf-8"))
        raw = json.dumps({"pc": "pc_01"}).encode("utf-8")
        return Resp(200, raw, msg(local_store.response_mac(WANT_AGENT, b["nonce"], 200, raw)))
    try:
        got = local_store.enroll(HTEXT, GUID, HOST, opener=https_enroll, rand_hex=RAND, nonce=NONCE)
    except Exception as e:
        got = f"{type(e).__name__}: {e}"
    check("https 등록 - 돌려주는 dict 에 ca_pem", got == {"server_url": "https://10.1.2.3:8444", "pc_id": "pc_01", "agent_key": WANT_AGENT,
                                                    "relay_key": WANT_RELAY, "ca_pem": CA}, repr(got))
    check("https 등록 요청은 https 주소로", hsent and hsent[0].full_url == "https://10.1.2.3:8444/enroll")
    check("받은 값으로 lan https Client 를 만들 수 있다", isinstance(got, dict) and isinstance(local_store.Client(
        {"standalone": True, "lan": True, "server_url": got["server_url"], "key": got["agent_key"], "pc_id": got["pc_id"],
         "ca_pem": got["ca_pem"]}), local_store.Client))
    expect("https 등록 글에 ca 가 없으면 ValueError", ValueError, None, lambda: local_store.enroll(
        "APE1." + __import__("base64").urlsafe_b64encode(json.dumps({"v": 1, "url": "https://10.1.2.3:8444", "pc": "pc_01",
                                                                       "token": TOKEN, "exp": 1}).encode()).decode().rstrip("="),
        GUID, HOST, opener=https_enroll))
    PTEXT = pc_registry.encode_enrollment({"v": 1, "url": "https://8.8.8.8:8444", "pc": "pc_01", "token": TOKEN, "exp": 1, "ca": CA})
    hsent.clear()
    expect("https 등록 글의 주소가 공인 IP 면 ValueError (보내지 않는다)", ValueError, None,
           lambda: local_store.enroll(PTEXT, GUID, HOST, opener=https_enroll))
    check("공인 IP 등록 글은 아무것도 보내지 않았다", not hsent)
    try:
        local_store.enroll(HTEXT, GUID, HOST, opener=lambda req, timeout=30: (_ for _ in ()).throw(urllib.error.URLError(bad_cert)))
        check("등록의 인증서 확인 실패 → AuthError(0, CERT_FAILED)", False, "예외 없음")
    except fb.AuthError as e:
        check("등록의 인증서 확인 실패 → AuthError(0, CERT_FAILED)", e.code == getattr(local_store, "CERT_FAILED", "?"), repr(e))
    except Exception as e:
        check("등록의 인증서 확인 실패 → AuthError(0, CERT_FAILED)", False, f"{type(e).__name__}: {e}")
    check("http 등록 답에는 ca_pem 칸이 없다 (① 그대로)",
          "ca_pem" not in local_store.enroll(ETEXT, GUID, HOST, opener=enroll_opener(WANT_AGENT), rand_hex=RAND, nonce=NONCE))
finally:
    license_check.LICENSE_PUBLIC_KEY_HEX = saved_pub
    for k, v in saved_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        runs.close()
    except Exception:
        pass
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n실패: {len(fails)}" + (f" ({', '.join(fails)})" if fails else ""))
sys.exit(1 if fails else 0)
