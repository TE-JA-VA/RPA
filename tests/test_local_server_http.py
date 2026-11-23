# -*- coding: utf-8 -*-
"""스탠드얼론 로컬 서버의 창구·열쇠·검사 (설계 2026-11-23-standalone 6.2, 계획 ① Task 3).
지금 RTDB 규칙과 같은 뜻의 검사를 한다 - 에이전트는 자기 PC 자리만, 명령은 상태만 옮긴다.
    .venv\\Scripts\\python.exe tests\\test_local_server_http.py
"""
import json
import os
import shutil
import socket
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

fails = []
TMP = tempfile.mkdtemp(prefix="rpa_lsrv_")
LIC = {"edition": "standalone", "company": "시험상사", "cid": "c1", "pc_id": "p1", "issued": "2026-11-23",
       "modules": {"Hold": False}, "features": {"wellife": False}, "limits": {"schedule": 3, "presets": None, "parallel": None}}


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


class Got:
    def __init__(self, status, raw, headers):
        self.status, self.raw, self.headers = status, raw, headers

    def json(self):
        return json.loads(self.raw) if self.raw else None


def call(method, path, body=None, key=None, host=None, base=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request((base or BASE) + path, data=data, method=method, headers={"Content-Type": "application/json"})
    if key:
        req.add_header("Authorization", "Bearer " + key)
    if host:
        req.add_header("Host", host)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return Got(r.status, r.read().decode("utf-8"), r.headers)
    except urllib.error.HTTPError as e:
        return Got(e.code, e.read().decode("utf-8", "replace"), e.headers)


def sse(path, key, until=1.5):
    """until 초 동안 온 SSE 를 [(event, data)] 로."""
    req = urllib.request.Request(BASE + path, headers={"Accept": "text/event-stream", "Authorization": "Bearer " + key})
    lines = []
    resp = urllib.request.urlopen(req, timeout=until)
    try:
        for raw in resp:
            lines.append(raw.decode("utf-8", "replace").rstrip("\n"))
    except (socket.timeout, TimeoutError, OSError):
        pass
    finally:
        resp.close()
    return fb.parse_sse(lines)


CMD = "/db/apps/rpa/commands/c1/p1"
try:
    store = local_server.Store(os.path.join(TMP, "store.json"), volatile=local_server.VOLATILE)
    runs = local_server.Runs(os.path.join(TMP, "runs.db"))
    AGENT, RELAY = local_server.ensure_keys(TMP)
    srv = local_server.make_server(store, runs, LIC, (AGENT, RELAY), port=0)
    BASE = f"http://127.0.0.1:{srv.server_address[1]}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    print("열쇠")
    check("열쇠 둘은 다르고 길다", AGENT != RELAY and len(AGENT) >= 32 and len(RELAY) >= 32)
    check("다시 불러도 같은 열쇠", local_server.ensure_keys(TMP) == (AGENT, RELAY))
    check("열쇠 없음 401", call("GET", "/db/apps/rpa/live/c1/p1.json").status == 401)
    check("틀린 열쇠 401", call("GET", "/db/apps/rpa/live/c1/p1.json", key="x" * 43).status == 401)
    check("이 PC 주소로 온 요청만 (Host 검사)", call("GET", "/db/apps/rpa/live/c1/p1.json", key=AGENT, host="evil.example").status == 403)

    print("현황 · 정책")
    check("현황 쓰기", call("PUT", "/db/apps/rpa/live/c1/p1.json", {"state": "idle"}, key=AGENT).status in (200, 204))
    check("현황 읽기", call("GET", "/db/apps/rpa/live/c1/p1.json", key=AGENT).json() == {"state": "idle"})
    check("현황 아래 자리 고치기", call("PATCH", "/db/apps/rpa/live/c1/p1.json", {"heartbeat/at": 5}, key=AGENT).status in (200, 204)
          and store.get("apps/rpa/live/c1/p1/heartbeat/at") == 5)
    check("print=silent 는 빈 응답 204", call("PUT", "/db/apps/rpa/live/c1/p1/x.json?print=silent", 1, key=AGENT).status == 204)
    check("다른 PC 403", call("PUT", "/db/apps/rpa/live/c1/p2.json", {}, key=AGENT).status == 403)
    r = call("GET", "/db/apps/rpa/live/c2/p1.json", key=AGENT)
    check("다른 업체 403 (글은 Permission denied)", r.status == 403 and "Permission denied" in r.raw)
    check("자리 밖 403", call("GET", "/db/.json", key=AGENT).status == 403 and call("GET", "/db/apps.json", key=AGENT).status == 403)
    check("이상한 경로 400", call("GET", "/db/apps/rpa/live/c1/p1/../p2.json", key=AGENT).status in (400, 403))
    check("Date 머리글", bool(call("GET", "/db/apps/rpa/live/c1/p1.json", key=AGENT).headers.get("Date")))
    pol = call("GET", "/db/meta/companies/c1/apps/rpa.json", key=AGENT).json()
    check("정책은 라이선스에서", pol == {"modules": {"Hold": False}, "features": {"wellife": False},
                                 "limits": {"schedule": 3, "presets": None, "parallel": None}} or
          (pol and pol["limits"]["schedule"] == 3 and pol["modules"] == {"Hold": False}), repr(pol))
    check("정책 한 칸 읽기", call("GET", "/db/meta/companies/c1/apps/rpa/modules.json", key=AGENT).json() == {"Hold": False})
    check("AI 는 늘 꺼짐", call("GET", "/db/meta/companies/c1/apps/rpa/features/ai.json", key=AGENT).json() is None)
    check("정책 쓰기 403", call("PUT", "/db/meta/companies/c1/apps/rpa/limits.json", {"schedule": 99}, key=AGENT).status == 403)
    check("다른 업체 정책 403", call("GET", "/db/meta/companies/c2/apps/rpa.json", key=AGENT).status == 403)
    check("휴대폰 목록 (비어 있음)", call("GET", "/db/meta/companies/c1/phones.json", key=AGENT).json() is None)
    check("AI 키 자리 403", call("GET", "/db/apps/rpa/aikey/c1/key.json", key=AGENT).status == 403)
    check("프리셋 옮기기 자리 403", call("GET", "/db/apps/rpa/transfers/c1.json", key=AGENT).status == 403)

    print("명령 - 에이전트는 상태만 옮긴다")
    store.put("apps/rpa/commands/c1/p1/k1", {"state": "queued", "type": "launch", "args": {"target": "all"},
                                              "by": "web", "created_at": 1, "expires_at": 9e9})
    check("대기 중 명령 거르기", list((call("GET", CMD + '.json?orderBy=%22state%22&equalTo=%22queued%22', key=AGENT).json() or {})) == ["k1"])
    check("args 바꾸기 403", call("PATCH", CMD + "/k1.json", {"args": {"x": 1}}, key=AGENT).status == 403)
    check("type 바꾸기 403", call("PATCH", CMD + "/k1.json", {"type": "stop_rpa"}, key=AGENT).status == 403)
    check("만료 늘리기 403", call("PATCH", CMD + "/k1.json", {"expires_at": 9e10}, key=AGENT).status == 403)
    check("queued→done 403", call("PATCH", CMD + "/k1.json", {"state": "done"}, key=AGENT).status == 403)
    check("running 표시", call("PATCH", CMD + "/k1.json", {"state": "running", "started_at": 5}, key=AGENT).status in (200, 204))
    check("running→queued 403", call("PATCH", CMD + "/k1.json", {"state": "queued"}, key=AGENT).status == 403)
    check("명령함에 여러 자리 쓰기로 args 바꾸기 403", call("PATCH", CMD + ".json", {"k1/args": {"x": 1}}, key=AGENT).status == 403)
    check("명령 통째로 덮기 403", call("PUT", CMD + "/k1.json", {"state": "done"}, key=AGENT).status == 403)
    check("상태 칸만 PUT 으로 옮기기 403", call("PUT", CMD + "/k1/args.json", {"x": 1}, key=AGENT).status == 403)
    check("done 표시 (결과 글 함께)", call("PATCH", CMD + "/k1.json", {"state": "done", "result": "끝", "ended_at": 9}, key=AGENT).status in (200, 204)
          and store.get("apps/rpa/commands/c1/p1/k1")["args"] == {"target": "all"})
    check("done→failed 403", call("PATCH", CMD + "/k1.json", {"state": "failed"}, key=AGENT).status == 403)
    check("새 명령 만들기 403 (PUT)", call("PUT", CMD + "/k9.json", {"state": "queued", "type": "launch", "expires_at": 9e9}, key=AGENT).status == 403)
    check("새 명령 만들기 403 (PATCH)", call("PATCH", CMD + "/k9.json", {"state": "queued", "type": "launch"}, key=AGENT).status == 403)
    check("없는 명령은 안 생김", store.get("apps/rpa/commands/c1/p1/k9") is None)
    store.put("apps/rpa/commands/c1/p1/k2", {"state": "queued", "type": "launch", "expires_at": 1})
    check("queued→expired", call("PATCH", CMD + "/k2.json", {"state": "expired", "result": "만료"}, key=AGENT).status in (200, 204))
    check("끝난 명령 지우기", call("DELETE", CMD + "/k2.json", key=AGENT).status in (200, 204) and store.get("apps/rpa/commands/c1/p1/k2") is None)
    check("다른 PC 명령 403", call("GET", "/db/apps/rpa/commands/c1/p2.json", key=AGENT).status == 403)

    print("인증번호 열쇠 (ACTOR·옵저버)")
    check("현황 못 읽음", call("GET", "/db/apps/rpa/live/c1/p1.json", key=RELAY).status == 403)
    check("명령 못 읽음", call("GET", CMD + ".json", key=RELAY).status == 403)
    check("요청 열기", call("PUT", "/db/apps/otp/requests/c1/ph1/current.json", {"site": "x", "created_at": 1}, key=RELAY).status in (200, 204))
    store.put("apps/otp/codes/c1/ph1/current", {"code": "123456"})
    check("번호 읽기", call("GET", "/db/apps/otp/codes/c1/ph1/current.json", key=RELAY).json() == {"code": "123456"})
    saved = open(os.path.join(TMP, "store.json"), encoding="utf-8").read()
    check("인증번호·요청은 파일에 남지 않는다", "123456" not in saved and "otp" not in saved and "live" in saved)
    call("PUT", "/db/apps/otp/requests/c1/ph2/current.json", {"req_id": "r", "created_at": {".sv": "timestamp"}}, key=RELAY)
    at = (store.get("apps/otp/requests/c1/ph2/current") or {}).get("created_at")
    check("서버 시각 채우기 (.sv timestamp)", isinstance(at, int) and abs(at - time.time() * 1000) < 5000, repr(at))
    store.put("apps/rpa/commands/c1/p1/old1", {"state": "done", "type": "launch", "created_at": 10})
    store.put("apps/rpa/commands/c1/p1/old2", {"state": "done", "type": "launch", "created_at": 500})
    got_old = call("GET", CMD + '.json?orderBy=%22created_at%22&endAt=100&limitToFirst=50', key=AGENT).json() or {}
    check("지난 명령 고르기 (orderBy·endAt)", sorted(got_old) == ["k1", "old1"] or sorted(got_old) == ["old1"], repr(sorted(got_old)))
    call("DELETE", CMD + "/old1.json", key=AGENT), call("DELETE", CMD + "/old2.json", key=AGENT)
    check("번호 쓰기는 못 함 (휴대폰만)", call("PUT", "/db/apps/otp/codes/c1/ph1/current.json", {"code": "1"}, key=RELAY).status == 403)
    check("번호 지우기", call("DELETE", "/db/apps/otp/codes/c1/ph1/current.json", key=RELAY).status in (200, 204))
    check("다른 업체 요청 403", call("PUT", "/db/apps/otp/requests/c2/ph1/current.json", {}, key=RELAY).status == 403)
    check("휴대폰 목록 읽기", call("GET", "/db/meta/companies/c1/phones.json", key=RELAY).status == 200)
    check("에이전트 열쇠도 인증번호 자리 (같은 PC 의 실행)", call("GET", "/db/apps/otp/requests/c1/ph1/current.json", key=AGENT).status == 200)

    print("실행 기록")
    doc = {"pcId": "p1", "date": "2026-11-23", "started_at": "2026-11-23T09:00:00", "cost": 2}
    check("기록 만들기", call("POST", "/fs/runs/c1/items?id=d1", doc, key=AGENT).status == 200)
    check("기록 두 번 409", call("POST", "/fs/runs/c1/items?id=d1", doc, key=AGENT).status == 409)
    check("기록 읽기", call("GET", "/fs/runs/c1/items/d1", key=AGENT).json() == doc)
    check("없는 기록 404", call("GET", "/fs/runs/c1/items/none", key=AGENT).status == 404)
    check("합", call("GET", "/fs-sum?parent=runs/c1&collection=items&field=cost", key=AGENT).json() == {"sum": 2})
    check("since", call("GET", "/fs-sum?parent=runs/c1&collection=items&field=cost&since=2026-11-23T09:30:00", key=AGENT).json() == {"sum": 0})
    check("다른 업체 기록 403", call("POST", "/fs/runs/c2/items?id=d1", doc, key=AGENT).status == 403)
    check("통장 자리 403", call("GET", "/fs/wallet/c1", key=AGENT).status == 403)
    check("기록은 에이전트 열쇠만", call("POST", "/fs/runs/c1/items?id=d2", doc, key=RELAY).status == 403)

    print("구독")
    got = sse(CMD + '.json?orderBy=%22state%22&equalTo=%22queued%22', AGENT)
    check("처음 값 (대기 중 없음)", got[:1] == [("put", {"path": "/", "data": None})], repr(got))
    box = []
    t = threading.Thread(target=lambda: box.extend(sse(CMD + '.json?orderBy=%22state%22&equalTo=%22queued%22', AGENT, until=2.5)))
    t.start()
    time.sleep(0.7)
    new_cmd = {"state": "queued", "type": "launch", "created_at": 2, "expires_at": 9e9}
    store.put("apps/rpa/commands/c1/p1/k3", new_cmd)
    time.sleep(0.3)
    store.patch("apps/rpa/commands/c1/p1/k3", {"state": "running"})
    t.join(6)
    check("새 명령이 바로 온다", ("put", {"path": "/k3", "data": new_cmd}) in box, repr(box))
    check("running 이 되면 빠졌다고 온다", ("put", {"path": "/k3", "data": None}) in box, repr(box))
    check("열쇠 없는 구독 401", call("GET", CMD + ".json", key=None).status == 401)

    print("서버")
    try:
        local_server.make_server(store, runs, LIC, (AGENT, RELAY), port=srv.server_address[1])
        check("같은 포트에 두 번 뜨지 않는다", False, "예외 없음")
    except OSError:
        check("같은 포트에 두 번 뜨지 않는다", True)
    check("127.0.0.1 에만 묶는다", srv.server_address[0] == "127.0.0.1")
    try:
        local_server.make_server(store, runs, LIC, (AGENT, RELAY), host="0.0.0.0", port=0)
        check("사내망에 묶기는 거절", False, "예외 없음")
    except ValueError:
        check("사내망에 묶기는 거절", True)
    check("큰 본문 413", call("PUT", "/db/apps/rpa/live/c1/p1/big.json", "x" * (local_server.MAX_BODY + 10), key=AGENT).status == 413)
    bad = urllib.request.Request(BASE + "/db/apps/rpa/live/c1/p1/y.json", data=b'{"a": ', method="PUT",
                                 headers={"Authorization": "Bearer " + AGENT, "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(bad, timeout=5)
        check("깨진 본문 400", False, "예외 없음")
    except urllib.error.HTTPError as e:
        check("깨진 본문 400", e.code == 400)
    check("모르는 주소 404", call("GET", "/nothing", key=AGENT).status == 404)

    # 서버를 끄면 열린 구독이 끝난다 (에이전트가 다시 붙는다 - Review Focus 1)
    ended = []
    t = threading.Thread(target=lambda: ended.append(sse(CMD + ".json", AGENT, until=8)))
    t.start()
    time.sleep(0.7)
    began = time.time()
    srv.shutdown()
    srv.server_close()
    t.join(8)
    check("서버가 꺼지면 구독이 곧 끝난다", bool(ended) and time.time() - began < 5, f"{time.time() - began:.1f}초")

    print("main - 라이선스")
    pd = os.path.join(TMP, "pd")
    os.makedirs(pd)
    os.environ["RPA_PROGRAMDATA"] = pd
    os.environ["RPA_MACHINE_GUID"] = "p1"
    code = local_server.main()
    log_path = os.path.join(pd, "standalone", local_server.LOG_NAME)
    text = open(log_path, encoding="utf-8").read() if os.path.isfile(log_path) else ""
    check("라이선스 없으면 2, 까닭을 기록에", code == 2 and "라이선스 파일이 없습니다" in text, f"code={code} {text[-200:]}")
    check("열쇠는 기록에 없다", AGENT not in text and RELAY not in text)
finally:
    os.environ.pop("RPA_PROGRAMDATA", None)
    os.environ.pop("RPA_MACHINE_GUID", None)
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n실패: {len(fails)}" + (f" ({', '.join(fails)})" if fails else ""))
sys.exit(1 if fails else 0)
