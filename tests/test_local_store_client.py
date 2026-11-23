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
    srv = local_server.make_server(store, runs, LIC, (AGENT, RELAY), port=0)
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
    store.put("apps/otp/codes/c1/ph1/current", {"req_id": req_id, "code": "482913"})
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
    store.put("phones/c1", {"ph1": {"label": "민기 휴대폰"}, "ph2": {"owner": "이름 없는 것"}})
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
