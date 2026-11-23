# -*- coding: utf-8 -*-
"""스탠드얼론 로컬 서버의 창구·서명·검사 (설계 2026-11-23-standalone 6.2, 계획 ① Task 3 + 검토 2026-11-23 고침).
지금 RTDB 규칙과 같은 뜻의 검사를 한다 - 에이전트는 자기 PC 자리만, 명령은 상태만 한 칸씩 옮긴다.
열쇠는 주고받지 않는다 - 요청·응답·구독 이벤트를 열쇠로 서명한다.
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
import local_server  # noqa: E402
import local_store  # noqa: E402

fails = []
TMP = tempfile.mkdtemp(prefix="rpa_lsrv_")
LIC = {"edition": "standalone", "company": "시험상사", "cid": "c1", "pc_id": "p1", "issued": "2026-11-23",
       "modules": {"Hold": False}, "features": {"wellife": False}, "limits": {"schedule": 3, "presets": None, "parallel": None}}
NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


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
        return json.loads(self.raw) if self.raw else None


def call(method, path, body=None, key=None, host=None, role=None, headers=None, raw=None, sign_path=None):
    """서명한 요청 한 번. key 가 없으면 서명 없이. headers 로 서명 머리글을 통째로 바꿔 끼울 수 있다 (거절 시험)."""
    data = raw if raw is not None else (b"" if body is None and method in ("GET", "DELETE") else json.dumps(body, ensure_ascii=False).encode("utf-8"))
    role = role or ("relay" if key == RELAY else "agent")
    hs = dict(headers) if headers is not None else (local_store.sign_headers(key, role, method, sign_path or path, data) if key else {})
    hs["Content-Type"] = "application/json"
    if host:
        hs["Host"] = host
    req = urllib.request.Request(BASE + path, data=data or None, method=method, headers=hs)
    nonce = hs.get(local_store.H_NONCE, "")
    try:
        with NO_PROXY.open(req, timeout=10) as r:
            got = r.read()
            status, rh = r.status, r.headers
    except urllib.error.HTTPError as e:
        got, status, rh = e.read(), e.code, e.headers
    signed = bool(key) and (rh.get(local_store.H_SIGN) or "") == local_store.response_mac(key, nonce, status, got)
    return Got(status, got.decode("utf-8", "replace"), rh, signed)


def sse(path, key, until=1.5):
    """until 초 동안 온 구독 이벤트를 [(event, data)] 로 - 진짜 클라이언트로 읽는다 (이벤트 서명 확인 포함)."""
    c = local_store.Client({"standalone": True, "server_url": BASE, "key": key, "role": "relay" if key == RELAY else "agent"})
    out = []
    try:
        for item in c.stream(path, PARAMS, timeout=until):
            out.append(item)
    except (socket.timeout, TimeoutError, OSError):
        pass
    return out


PARAMS = {"orderBy": '"state"', "equalTo": '"queued"'}
CMD = "/db/apps/rpa/commands/c1/p1"
QUEUED = CMD + '.json?orderBy=%22state%22&equalTo=%22queued%22'
OTP_REQ = {"req_id": "r1", "site": "시험몰", "pcId": "p1", "senders": {"01012345678": True}}
try:
    store = local_server.Store(os.path.join(TMP, "store.json"), volatile=local_server.VOLATILE)
    runs = local_server.Runs(os.path.join(TMP, "runs.db"))
    AGENT, RELAY = local_server.ensure_keys(TMP)
    srv = local_server.make_server(store, runs, LIC, (AGENT, RELAY), port=0)
    BASE = f"http://127.0.0.1:{srv.server_address[1]}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    LIVE = "/db/apps/rpa/live/c1/p1.json"

    print("열쇠와 서명")
    check("열쇠 둘은 다르고 길다", AGENT != RELAY and len(AGENT) >= 32 and len(RELAY) >= 32)
    check("다시 불러도 같은 열쇠", local_server.ensure_keys(TMP) == (AGENT, RELAY))
    check("서명 없음 401", call("GET", LIVE).status == 401)
    check("틀린 열쇠로 한 서명 401", call("GET", LIVE, key="x" * 43).status == 401)
    r = call("PUT", LIVE, {"state": "idle"}, key=AGENT)
    check("맞는 서명은 통과하고 응답에도 서명이 온다", r.status in (200, 204) and r.signed)
    check("열쇠를 그대로 보내는 옛 방식은 안 받는다", call("GET", LIVE, headers={"Authorization": "Bearer " + AGENT}).status == 401)
    hs = local_store.sign_headers(AGENT, "agent", "GET", LIVE, b"")
    check("같은 요청을 다시 보내면 401 (nonce)", call("GET", LIVE, headers=hs).status == 200 and call("GET", LIVE, headers=hs).status == 401)
    old = local_store.sign_headers(AGENT, "agent", "GET", LIVE, b"", now_ms=(time.time() - 120) * 1000)
    check("2분 전에 서명한 요청 401", call("GET", LIVE, headers=old).status == 401)
    check("다른 자리로 서명한 것 401", call("GET", LIVE, key=AGENT, sign_path="/db/apps/rpa/live/c1/p1/x.json").status == 401)
    hs = local_store.sign_headers(AGENT, "agent", "PUT", LIVE, b'{"state": "a"}')
    check("서명한 뒤 본문을 바꾸면 401", call("PUT", LIVE, headers=hs, raw=b'{"state": "b"}').status == 401)
    check("중계 열쇠로 에이전트 역할을 대면 401", call("GET", LIVE, key=RELAY, role="agent").status == 401)
    check("모르는 역할 401", call("GET", LIVE, key=AGENT, role="admin").status == 401)
    check("이 PC 주소로 온 요청만 (Host 검사)", call("GET", LIVE, key=AGENT, host="evil.example").status == 403)
    r = call("GET", "/db/apps/rpa/live/c2/p1.json", key=AGENT)
    check("거절 응답에도 서명 (진짜 서버의 거절임을 안다)", r.status == 403 and r.signed and "Permission denied" in r.raw)

    print("현황 · 정책")
    check("현황 읽기", call("GET", LIVE, key=AGENT).json() == {"state": "idle"})
    check("현황 아래 자리 고치기", call("PATCH", LIVE, {"heartbeat/at": 5}, key=AGENT).status in (200, 204)
          and store.get("apps/rpa/live/c1/p1/heartbeat/at") == 5)
    check("print=silent 는 빈 응답 204", call("PUT", "/db/apps/rpa/live/c1/p1/x.json?print=silent", 1, key=AGENT).status == 204)
    check("다른 PC 403", call("PUT", "/db/apps/rpa/live/c1/p2.json", {}, key=AGENT).status == 403)
    check("자리 밖은 거절", call("GET", "/db/.json", key=AGENT).status in (400, 403) and call("GET", "/db/apps.json", key=AGENT).status == 403)
    check("이상한 경로 400", call("GET", "/db/apps/rpa/live/c1/p1/../p2.json", key=AGENT).status == 400)
    check("Date 머리글", bool(call("GET", LIVE, key=AGENT).headers.get("Date")))
    pol = call("GET", "/db/meta/companies/c1/apps/rpa.json", key=AGENT).json()
    check("정책은 라이선스에서", pol == {"modules": {"Hold": False}, "features": {"wellife": False},
                                 "limits": {"schedule": 3, "presets": None, "parallel": None}}, repr(pol))
    check("정책 한 칸 읽기", call("GET", "/db/meta/companies/c1/apps/rpa/modules.json", key=AGENT).json() == {"Hold": False})
    check("AI 는 늘 꺼짐", call("GET", "/db/meta/companies/c1/apps/rpa/features/ai.json", key=AGENT).json() is None)
    check("정책 쓰기 403", call("PUT", "/db/meta/companies/c1/apps/rpa/limits.json", {"schedule": 99}, key=AGENT).status == 403)
    check("다른 업체 정책 403", call("GET", "/db/meta/companies/c2/apps/rpa.json", key=AGENT).status == 403)
    check("중계 열쇠는 정책을 못 읽는다", call("GET", "/db/meta/companies/c1/apps/rpa.json", key=RELAY).status == 403)
    check("휴대폰 목록 (비어 있음)", call("GET", "/db/meta/companies/c1/phones.json", key=AGENT).json() is None)
    check("AI 키 자리 403", call("GET", "/db/apps/rpa/aikey/c1/key.json", key=AGENT).status == 403)
    check("프리셋 옮기기 자리 403", call("GET", "/db/apps/rpa/transfers/c1.json", key=AGENT).status == 403)

    print("명령 - 에이전트는 상태만 한 칸씩 옮긴다")
    K1 = {"state": "queued", "type": "launch", "args": {"target": "all"}, "by": "web", "created_at": 1, "expires_at": 9e9}
    store.put("apps/rpa/commands/c1/p1/k1", K1)
    check("대기 중 명령 거르기", list((call("GET", QUEUED, key=AGENT).json() or {})) == ["k1"])
    check("args 바꾸기 403", call("PATCH", CMD + "/k1.json", {"args": {"x": 1}}, key=AGENT).status == 403)
    check("type 바꾸기 403", call("PATCH", CMD + "/k1.json", {"type": "stop_rpa"}, key=AGENT).status == 403)
    check("만료 늘리기 403", call("PATCH", CMD + "/k1.json", {"state": "running", "expires_at": 9e10}, key=AGENT).status == 403)
    check("queued→done 403", call("PATCH", CMD + "/k1.json", {"state": "done"}, key=AGENT).status == 403)
    check("모르는 칸 403", call("PATCH", CMD + "/k1.json", {"state": "running", "foo": 1}, key=AGENT).status == 403)
    check("상태 없이 결과만 쓰기 403", call("PATCH", CMD + "/k1.json", {"result": "x"}, key=AGENT).status == 403)
    check("상태 칸 안쪽 쓰기 403", call("PATCH", CMD + "/k1.json", {"state/x": 1}, key=AGENT).status == 403)
    check("결과가 글이 아니면 403", call("PATCH", CMD + "/k1.json", {"state": "running", "result": {"a": 1}}, key=AGENT).status == 403)
    # 주소 조각에 %2F 를 넣어 깊이 검사를 속이기 (검토 3번)
    check("%2F 로 args 고치기 400", call("PATCH", CMD + "/k1%2Fargs.json", {"target": "EVIL"}, key=AGENT).status == 400)
    check("%2F 로 만료 칸 지우기 400", call("DELETE", CMD + "/k1%2Fexpires_at.json", key=AGENT).status == 400)
    check("%5C 도 400", call("DELETE", CMD + "/k1%5Cstate.json", key=AGENT).status == 400)
    check("대기 중 명령은 못 지운다", call("DELETE", CMD + "/k1.json", key=AGENT).status == 403)
    check("명령의 칸 하나만 지우기 403", call("DELETE", CMD + "/k1/args.json", key=AGENT).status == 403)
    check("PATCH 로 명령 지우기 403", call("PATCH", CMD + ".json", {"k1": None}, key=AGENT).status == 403)
    check("거절된 시도 뒤 명령은 그대로", store.get("apps/rpa/commands/c1/p1/k1") == K1, repr(store.get("apps/rpa/commands/c1/p1/k1")))
    check("running 표시", call("PATCH", CMD + "/k1.json", {"state": "running", "started_at": 5}, key=AGENT).status in (200, 204))
    check("running 을 두 번 표시하지 못한다 (한 번만 실행)", call("PATCH", CMD + "/k1.json", {"state": "running", "started_at": 6}, key=AGENT).status == 403)
    check("running→queued 403", call("PATCH", CMD + "/k1.json", {"state": "queued"}, key=AGENT).status == 403)
    check("명령함에 여러 자리 쓰기로 args 바꾸기 403", call("PATCH", CMD + ".json", {"k1/args": {"x": 1}}, key=AGENT).status == 403)
    check("명령 통째로 덮기 403", call("PUT", CMD + "/k1.json", {"state": "done"}, key=AGENT).status == 403)
    check("칸만 PUT 으로 쓰기 403", call("PUT", CMD + "/k1/args.json", {"x": 1}, key=AGENT).status == 403)
    check("진행 중 명령도 못 지운다", call("DELETE", CMD + "/k1.json", key=AGENT).status == 403)
    check("명령함 자리에서 여러 자리 쓰기로 done 표시", call("PATCH", CMD + ".json", {"k1/state": "done", "k1/result": "끝", "k1/ended_at": 9}, key=AGENT).status in (200, 204)
          and store.get("apps/rpa/commands/c1/p1/k1") == dict(K1, state="done", result="끝", started_at=5, ended_at=9))
    check("done→failed 403", call("PATCH", CMD + "/k1.json", {"state": "failed"}, key=AGENT).status == 403)
    check("새 명령 만들기 403 (PUT)", call("PUT", CMD + "/k9.json", {"state": "queued", "type": "launch", "expires_at": 9e9}, key=AGENT).status == 403)
    check("새 명령 만들기 403 (PATCH)", call("PATCH", CMD + "/k9.json", {"state": "queued", "type": "launch"}, key=AGENT).status == 403)
    check("없는 명령은 안 생김", store.get("apps/rpa/commands/c1/p1/k9") is None)
    store.put("apps/rpa/commands/c1/p1/k2", {"state": "queued", "type": "launch", "expires_at": 1})
    check("queued→expired", call("PATCH", CMD + "/k2.json", {"state": "expired", "result": "만료", "ended_at": 3}, key=AGENT).status in (200, 204))
    check("끝난 명령 지우기", call("DELETE", CMD + "/k2.json", key=AGENT).status in (200, 204) and store.get("apps/rpa/commands/c1/p1/k2") is None)
    check("다른 PC 명령 403", call("GET", "/db/apps/rpa/commands/c1/p2.json", key=AGENT).status == 403)
    # 같은 대기 명령에 running 표시가 동시에 둘 오면 하나만 통과한다 (확인과 쓰기가 한 잠금 안)
    store.put("apps/rpa/commands/c1/p1/race", {"state": "queued", "type": "launch", "expires_at": 9e9})
    got = []
    ts = [threading.Thread(target=lambda: got.append(call("PATCH", CMD + "/race.json", {"state": "running", "started_at": 1}, key=AGENT).status))
          for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    check("동시에 온 running 표시는 하나만 통과", sorted(got).count(204) + sorted(got).count(200) == 1 and got.count(403) == 7, repr(got))
    store.put("apps/rpa/commands/c1/p1/old1", {"state": "done", "type": "launch", "created_at": 10})
    store.put("apps/rpa/commands/c1/p1/old2", {"state": "done", "type": "launch", "created_at": 500})
    got_old = call("GET", CMD + '.json?orderBy=%22created_at%22&endAt=100&limitToFirst=50', key=AGENT).json() or {}
    check("지난 명령 고르기 (orderBy·endAt)", sorted(got_old) == ["k1", "old1"], repr(sorted(got_old)))
    call("DELETE", CMD + "/old1.json", key=AGENT), call("DELETE", CMD + "/old2.json", key=AGENT)

    print("인증번호 (ACTOR·옵저버의 중계 열쇠)")
    REQ = "/db/apps/otp/requests/c1/ph1/current.json"
    check("현황 못 읽음", call("GET", LIVE, key=RELAY).status == 403)
    check("명령 못 읽음", call("GET", CMD + ".json", key=RELAY).status == 403)
    check("요청 열기", call("PUT", REQ, dict(OTP_REQ, created_at={".sv": "timestamp"}), key=RELAY).status in (200, 204))
    at = (store.get("apps/otp/requests/c1/ph1/current") or {}).get("created_at")
    check("요청 시각은 서버가 적는다", isinstance(at, int) and abs(at - time.time() * 1000) < 5000, repr(at))
    call("PUT", REQ, dict(OTP_REQ, created_at=5), key=RELAY)
    check("보낸 쪽이 적은 시각은 무시", abs(store.get("apps/otp/requests/c1/ph1/current")["created_at"] - time.time() * 1000) < 5000)
    check("다른 PC 이름의 요청 403", call("PUT", REQ, dict(OTP_REQ, pcId="p9"), key=RELAY).status == 403)
    check("모르는 칸 403", call("PUT", REQ, dict(OTP_REQ, extra=1), key=RELAY).status == 403)
    check("발신번호가 너무 많으면 403", call("PUT", REQ, dict(OTP_REQ, senders={str(1000 + i): True for i in range(21)}), key=RELAY).status == 403)
    check("발신번호가 숫자가 아니면 403", call("PUT", REQ, dict(OTP_REQ, senders={"abc": True}), key=RELAY).status == 403)
    check("요청 자리 통째로 쓰기 403", call("PUT", "/db/apps/otp/requests/c1.json", "x", key=RELAY).status == 403
          and call("PATCH", "/db/apps/otp/requests/c1.json", {"": {"a": 1}}, key=RELAY).status == 403)
    check("요청 아래 다른 자리 403", call("PUT", "/db/apps/otp/requests/c1/ph1/other.json", OTP_REQ, key=RELAY).status == 403
          and call("PATCH", REQ, {"site": "y"}, key=RELAY).status == 403)
    store.put("apps/otp/codes/c1/ph1/current", {"req_id": "r1", "code": "123456"})
    check("번호 읽기", call("GET", "/db/apps/otp/codes/c1/ph1/current.json", key=RELAY).json() == {"req_id": "r1", "code": "123456"})
    saved = open(os.path.join(TMP, "store.json"), encoding="utf-8").read()
    check("인증번호·요청·현황은 파일에 남지 않는다", "123456" not in saved and "otp" not in saved and "live" not in saved and "commands" in saved)
    check("번호 쓰기는 못 함 (휴대폰 창구만)", call("PUT", "/db/apps/otp/codes/c1/ph1/current.json", {"code": "1"}, key=RELAY).status == 403)
    check("번호 지우기", call("DELETE", "/db/apps/otp/codes/c1/ph1/current.json", key=RELAY).status in (200, 204))
    check("다른 업체 요청 403", call("PUT", "/db/apps/otp/requests/c2/ph1/current.json", OTP_REQ, key=RELAY).status == 403)
    check("휴대폰 목록 읽기", call("GET", "/db/meta/companies/c1/phones.json", key=RELAY).status == 200)
    check("에이전트 열쇠도 인증번호 자리 (같은 PC 의 실행)", call("GET", REQ, key=AGENT).status == 200)

    print("실행 기록")
    doc = {"pcId": "p1", "date": "2026-11-23", "started_at": "2026-11-23T09:00:00", "cost": 2}
    check("기록 만들기", call("POST", "/fs/runs/c1/items?id=d1", doc, key=AGENT).status == 200)
    check("기록 두 번 409 (서명된 답)", (lambda r: r.status == 409 and r.signed)(call("POST", "/fs/runs/c1/items?id=d1", doc, key=AGENT)))
    check("기록 읽기", call("GET", "/fs/runs/c1/items/d1", key=AGENT).json() == doc)
    check("없는 기록 404", call("GET", "/fs/runs/c1/items/none", key=AGENT).status == 404)
    check("합", call("GET", "/fs-sum?parent=runs/c1&collection=items&field=cost", key=AGENT).json() == {"sum": 2})
    check("since", call("GET", "/fs-sum?parent=runs/c1&collection=items&field=cost&since=2026-11-23T09:30:00", key=AGENT).json() == {"sum": 0})
    check("다른 업체 기록 403", call("POST", "/fs/runs/c2/items?id=d1", doc, key=AGENT).status == 403)
    check("통장 자리 403", call("GET", "/fs/wallet/c1", key=AGENT).status == 403)
    check("기록은 에이전트 열쇠만", call("POST", "/fs/runs/c1/items?id=d2", doc, key=RELAY).status == 403)

    print("구독")
    for k in ("race",):
        store.delete(f"apps/rpa/commands/c1/p1/{k}")
    got = sse("apps/rpa/commands/c1/p1", AGENT)
    check("처음 값 (대기 중 없음)", got[:1] == [("put", {"path": "/", "data": None})], repr(got))
    box = []
    t = threading.Thread(target=lambda: box.extend(sse("apps/rpa/commands/c1/p1", AGENT, until=3.0)))
    t.start()
    time.sleep(1.0)
    new_cmd = {"state": "queued", "type": "launch", "created_at": 2, "expires_at": 9e9}
    store.put("apps/rpa/commands/c1/p1/k3", new_cmd)
    time.sleep(0.2)
    store.patch("apps/rpa/commands/c1/p1/k3", {"note": "x"})
    time.sleep(0.2)
    store.patch("apps/rpa/commands/c1/p1/k3", {"state": "running"})
    t.join(8)
    check("새 명령이 바로 온다", ("put", {"path": "/k3", "data": new_cmd}) in box, repr(box))
    check("대기 중 명령의 안쪽 칸이 바뀌면 그 칸만 (명령을 또 보내지 않는다)", ("put", {"path": "/k3/note", "data": "x"}) in box
          and [e for e in box if e[1] and e[1].get("path") == "/k3" and e[1].get("data")] == [("put", {"path": "/k3", "data": new_cmd})], repr(box))
    check("running 이 되면 빠졌다고 온다", ("put", {"path": "/k3", "data": None}) in box, repr(box))
    check("서명 없는 구독 401", call("GET", CMD + ".json").status == 401)
    check("중계 열쇠는 명령을 구독하지 못한다", (lambda r: r.status == 403)(call("GET", CMD + ".json", key=RELAY, headers=dict(
        local_store.sign_headers(RELAY, "relay", "GET", CMD + ".json", b""), Accept="text/event-stream"))))
    real_max = local_server.SUB_QUEUE_MAX
    local_server.SUB_QUEUE_MAX = 5
    q = store.subscribe("apps/rpa/live/c1/p1")
    local_server.SUB_QUEUE_MAX = real_max
    for i in range(12):
        store.put("apps/rpa/live/c1/p1/n", i)
    check("읽지 않는 구독은 끊는다 (밀린 이벤트가 끝없이 쌓이지 않는다)", q.overflow is True and q.qsize() <= 5 and all(s["q"] is not q for s in store._subs))

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
    r = call("PUT", "/db/apps/rpa/live/c1/p1/big.json", "x" * (local_server.MAX_BODY + 10), key=AGENT)
    check("큰 본문 413 (서명된 답)", r.status == 413 and r.signed)
    hs = local_store.sign_headers(AGENT, "agent", "PUT", "/db/apps/rpa/live/c1/p1/y.json", b'{"a": ')
    check("깨진 본문 400", call("PUT", "/db/apps/rpa/live/c1/p1/y.json", headers=hs, raw=b'{"a": ').status == 400)
    check("모르는 주소 404", call("GET", "/nothing", key=AGENT).status == 404)
    # 아무것도 보내지 않는 연결이 스레드를 잡아 두지 못한다 (검토 4번)
    # 시각이 아니라 조건으로 본다. 윈도우는 listen 대기열(5)이 잠깐 차면 연결을 0.5초 뒤에 다시 시도한다 - 붙이는 데 0.5초 넘게
    # 걸리는 회차가 있어, 예전처럼 '시간 제한 1초 + 0.5초 뒤 한 번' 세면 먼저 붙은 연결이 이미 끊긴 뒤라 상한 밑으로 세어졌다 (1 → 1).
    # 그래서 상한은 시간 제한을 넉넉히 두고 보고, 시간이 지나 끊기는 것은 따로 몇 개로 본다
    real_timeout = local_server.Handler.timeout
    before = srv.conns            # 앞 시험의 구독 연결이 남아 있을 수 있다 (끊긴 구독은 다음 쓰기·30초 신호 때 정리된다)
    seen, watching = [srv.conns], threading.Event()
    watching.set()

    def watch():                  # 시험 내내 한 번이라도 상한을 넘는지
        while watching.is_set():
            seen.append(srv.conns)
            time.sleep(0.005)
    threading.Thread(target=watch, daemon=True).start()
    local_server.Handler.timeout = 30
    idle = [socket.create_connection(("127.0.0.1", srv.server_address[1])) for _ in range(local_server.MAX_CONN + 30)]
    full = until(lambda: srv.conns >= local_server.MAX_CONN, 20)
    check("동시에 붙은 연결은 상한까지만", full and before < local_server.MAX_CONN and max(seen) <= local_server.MAX_CONN,
          f"{before} → {srv.conns} (가장 많을 때 {max(seen)})")
    for s in idle:
        s.close()
    check("연결을 닫으면 자리가 돌아온다", until(lambda: srv.conns <= before, 10), f"{before} → {srv.conns}")
    local_server.Handler.timeout = 1
    idle = [socket.create_connection(("127.0.0.1", srv.server_address[1])) for _ in range(5)]
    held = until(lambda: srv.conns > before, 10)
    check("말 없는 연결은 시간이 지나면 끊긴다", held and until(lambda: srv.conns <= before, 10), f"{before} → {srv.conns}")
    watching.clear()
    check("상한을 한 번도 넘지 않았다", max(seen) <= local_server.MAX_CONN, f"가장 많을 때 {max(seen)}")
    for s in idle:
        s.close()
    local_server.Handler.timeout = real_timeout
    check("그 뒤에도 요청을 받는다", call("GET", LIVE, key=AGENT).status == 200)

    # 서버를 끄면 열린 구독이 끝난다 (에이전트가 다시 붙는다 - Review Focus 1)
    ended = []
    t = threading.Thread(target=lambda: ended.append(sse("apps/rpa/commands/c1/p1", AGENT, until=8)))
    t.start()
    time.sleep(1.0)
    began = time.time()
    srv.shutdown()
    srv.server_close()
    t.join(8)
    check("서버가 꺼지면 구독이 곧 끝난다", bool(ended) and time.time() - began < 5, f"{time.time() - began:.1f}초")

    print("파일을 잠깐 못 읽을 때 (검토 10번)")
    os.makedirs(os.path.join(TMP, "locked", "agent.key"))            # 열쇠 파일 자리에 폴더 - 읽기가 PermissionError
    try:
        local_server.ensure_keys(os.path.join(TMP, "locked"))
        check("못 읽은 열쇠를 새 열쇠로 덮지 않는다", False, "예외 없음")
    except OSError:
        check("못 읽은 열쇠를 새 열쇠로 덮지 않는다", os.path.isdir(os.path.join(TMP, "locked", "agent.key")))
    os.makedirs(os.path.join(TMP, "store_dir.json"))
    try:
        local_server.Store(os.path.join(TMP, "store_dir.json"))
        check("못 읽은 저장 파일을 깨진 파일로 치우지 않는다", False, "예외 없음")
    except OSError:
        check("못 읽은 저장 파일을 깨진 파일로 치우지 않는다", not os.path.exists(os.path.join(TMP, "store_dir.json.broken")))

    print("main - 라이선스 · 포트")
    pd = os.path.join(TMP, "pd")
    os.makedirs(pd)
    os.environ["RPA_PROGRAMDATA"] = pd
    os.environ["RPA_MACHINE_GUID"] = "p1"
    code = local_server.main()
    log_path = os.path.join(pd, "standalone", local_server.LOG_NAME)
    text = open(log_path, encoding="utf-8").read() if os.path.isfile(log_path) else ""
    check("라이선스 없으면 2, 까닭을 기록에", code == 2 and "라이선스 파일이 없습니다" in text, f"code={code} {text[-200:]}")
    check("열쇠는 기록에 없다", AGENT not in text and RELAY not in text)
    # 포트를 다른 프로그램이 쓰는 중 → 3, 까닭을 기록에 (Review Focus 3)
    import update_sign
    import license_check
    lic_secret, lic_public = update_sign.keygen()
    saved_pub = license_check.LICENSE_PUBLIC_KEY_HEX
    license_check.LICENSE_PUBLIC_KEY_HEX = lic_public.hex()
    with open(os.path.join(pd, "license.json"), "w", encoding="utf-8") as f:
        json.dump(license_check.sign_body(lic_secret, LIC), f, ensure_ascii=False)
    squat = socket.socket()
    squat.bind(("127.0.0.1", 0))
    squat.listen(1)
    os.environ["RPA_LOCAL_PORT"] = str(squat.getsockname()[1])
    try:
        code = local_server.main()
    finally:
        license_check.LICENSE_PUBLIC_KEY_HEX = saved_pub
        squat.close()
    text = open(log_path, encoding="utf-8").read()
    check("포트를 남이 쓰면 3, 까닭을 기록에", code == 3 and "다른 프로그램이 쓰고 있습니다" in text, f"code={code} {text[-200:]}")
finally:
    for k in ("RPA_PROGRAMDATA", "RPA_MACHINE_GUID", "RPA_LOCAL_PORT"):
        os.environ.pop(k, None)
    try:
        runs.close()
    except Exception:
        pass
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n실패: {len(fails)}" + (f" ({', '.join(fails)})" if fails else ""))
sys.exit(1 if fails else 0)
