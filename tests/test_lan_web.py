# -*- coding: utf-8 -*-
"""사내 서버 웹 API 의 여러 PC (계획 2026-11-24-lan-1-server-multi-pc Task 6, 설계 6.6 '여러 PC 고르기'·'새 카드').
PC 고르기(pcId), /api/company 의 PC 목록, /api/pcs 관리 창구(추가·이름·중지·재개·등록 취소·삭제·등록 글).
서버 둘을 띄운다: 사내 서버(등록부 있음 = LAN) 와 단독(없음 = SINGLE, 지금 그대로여야 한다). 임시 폴더만 쓴다.
    .venv\\Scripts\\python.exe tests\\test_lan_web.py
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
import local_server  # noqa: E402
import local_store  # noqa: E402
import local_web  # noqa: E402
import pc_registry  # noqa: E402

fails = []
TMP = tempfile.mkdtemp(prefix="rpa_lan_web_")
DATA = os.path.join(TMP, "lan")
DATA1 = os.path.join(TMP, "single")
LIC = {"edition": "standalone", "company": "시험상사", "cid": "c1", "pc_id": "srv", "issued": "2026-11-24",
       "modules": {"Hold": False}, "features": {"wellife": False}, "limits": {"schedule": 3, "presets": None, "parallel": None}}
LIC1 = dict(LIC, pc_id="p1")
NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))
BOSS_PW, STAFF_PW = "pw-12345678", "staff-pw-0001"
GUIDS = ["11111111-2222-3333-4444-5555555555%02d" % i for i in range(10)]
SECRETS = []                     # 등록 토큰·등록 글 - 끝에 서버 기록에 없는지 본다


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


class Got:
    def __init__(self, status, raw):
        self.status, self.raw = status, raw

    def json(self):
        try:
            return json.loads(self.raw) if self.raw else None
        except ValueError:
            return None

    @property
    def code(self):
        v = self.json()
        return v.get("code") if isinstance(v, dict) else None

    def __repr__(self):
        return f"<{self.status} {self.raw[:300]}>"


def api(method, path, body=None, token=None, base=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    hs = {"Content-Type": "application/json"} if data is not None else {}
    if token:
        hs["Authorization"] = "Bearer " + token
    req = urllib.request.Request((base or BASE) + path, data=data, method=method, headers=hs)
    try:
        with NO_PROXY.open(req, timeout=15) as r:
            got, status = r.read(), r.status
    except urllib.error.HTTPError as e:
        got, status = e.read(), e.code
    return Got(status, got.decode("utf-8", "replace"))


def token_of(uid, pw, base=None):
    r = api("POST", "/api/login", {"id": uid, "password": pw}, base=base)
    return r.json()["token"] if r.status == 200 else None


def wait_for(cond, sec=8.0):
    end = time.time() + sec
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return bool(cond())


class Stream:
    """/api/stream?… 을 다른 스레드에서 읽어 (event, data) 를 모은다."""

    def __init__(self, token, query="", base=None):
        self.events, self.status, self.ended, self.raw = [], None, False, ""
        self._req = urllib.request.Request((base or BASE) + "/api/stream" + query, headers={"Authorization": "Bearer " + token})
        self._r = None
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            with NO_PROXY.open(self._req, timeout=30) as r:
                self._r = r
                self.status = r.status
                event = data = None
                for line in r:
                    line = line.decode("utf-8", "replace").rstrip("\r\n")
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:"):
                        data = line[5:].strip()
                    elif line == "" and event is not None:
                        self.events.append((event, json.loads(data) if data else None))
                        event = data = None
        except urllib.error.HTTPError as e:
            self.status = e.code
            self.raw = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        self.ended = True

    def named(self, name):
        return [d for e, d in list(self.events) if e == name]

    def wait(self, cond, sec=8.0):
        return wait_for(lambda: cond(self), sec)

    def close(self):
        try:
            if self._r is not None:
                self._r.close()
        except Exception:
            pass


def log_text(folder):
    path = os.path.join(folder, local_server.LOG_NAME)
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def live_of(pc):
    return f"apps/rpa/live/c1/{pc}"


def cmds_of(pc):
    return f"apps/rpa/commands/c1/{pc}"


runs = runs1 = srv = srv1 = None
streams = []
try:
    os.makedirs(DATA)
    os.makedirs(DATA1)
    # --- 사내 서버 (등록부 있음) ---
    store = local_server.Store(os.path.join(DATA, "store.json"), volatile=local_server.VOLATILE)
    runs = local_server.Runs(os.path.join(DATA, "runs.db"))
    reg = pc_registry.Registry(os.path.join(DATA, "pcs.json"), seats=3)
    try:
        web = local_web.Web(store, runs, LIC, DATA, None, registry=reg)
    except TypeError as e:                       # Task 6 전 - Web 이 registry 를 받지 않는다
        print(f"  [실패] Web(..., registry=) 를 받지 않는다 - {e}")
        sys.exit(1)
    web.accounts.set("boss", BOSS_PW, "admin")
    web.accounts.set("staff", STAFF_PW, "viewer")
    srv = local_server.make_server(store, runs, LIC, None, port=0, folder=DATA, web=web, registry=reg)
    BASE = f"http://127.0.0.1:{srv.server_address[1]}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    # --- 단독 (등록부 없음) ---
    store1 = local_server.Store(os.path.join(DATA1, "store.json"), volatile=local_server.VOLATILE)
    runs1 = local_server.Runs(os.path.join(DATA1, "runs.db"))
    keys1 = local_server.ensure_keys(DATA1)
    web1 = local_web.Web(store1, runs1, LIC1, DATA1, None)
    web1.accounts.set("boss", BOSS_PW, "admin")
    srv1 = local_server.make_server(store1, runs1, LIC1, keys1, port=0, folder=DATA1, web=web1)
    BASE1 = f"http://127.0.0.1:{srv1.server_address[1]}"
    threading.Thread(target=srv1.serve_forever, daemon=True).start()

    BOSS, STAFF = token_of("boss", BOSS_PW), token_of("staff", STAFF_PW)
    BOSS1 = token_of("boss", BOSS_PW, base=BASE1)

    print("배치")
    check("make_server 의 등록부와 웹 창구의 등록부가 같다", srv.registry is reg and web.registry is reg and web1.registry is None)
    check("웹 스트림 상한 - 사내 서버 32, 단독은 지금 상수", web.max_streams == 32 and web1.max_streams == local_web.MAX_STREAMS == 16,
          repr((web.max_streams, web1.max_streams)))
    check("웹 창구에 서버 주소", web.public_url == BASE, repr(web.public_url))

    # ------------------------------------------------------------------------------------------
    print("test_pcs_api_admin_only")
    r = api("GET", "/api/pcs", token=STAFF)
    check("유저 계정 GET /api/pcs → 403", r.status == 403, repr(r))
    check("토큰 없이 → 401", api("GET", "/api/pcs").status == 401)
    r = api("GET", "/api/pcs", token=BOSS)
    check("관리자 → 200, seats·used·빈 목록", r.status == 200 and r.json() == {"pcs": [], "seats": 3, "used": 0}, repr(r))
    check("유저는 PC 추가도 못 한다", api("POST", "/api/pcs", {"label": "x"}, token=STAFF).status == 403 and reg.used() == 0)

    # ------------------------------------------------------------------------------------------
    print("test_add_pc_enrollment_text")
    r = api("POST", "/api/pcs", {"label": "2층"}, token=BOSS)
    out = r.json() or {}
    text = out.get("enrollment") or ""
    SECRETS.append(text)
    check("POST /api/pcs → pcId·등록 글·만료", r.status == 200 and out.get("pcId") == "pc_01" and text.startswith("APE1.")
          and isinstance(out.get("expiresAt"), int), repr(r))
    info = pc_registry.decode_enrollment(text) if text.startswith("APE1.") else {}
    SECRETS.append(info.get("token") or "never-matches")
    check("등록 글의 url 은 서버 주소, pc·exp 가 응답과 같다", info.get("url") == BASE and info.get("pc") == "pc_01"
          and info.get("exp") == out.get("expiresAt") and info.get("v") == 1, repr(info))
    r = api("GET", "/api/pcs", token=BOSS)
    rows = (r.json() or {}).get("pcs") or []
    check("목록에 대기 중으로 보인다", r.status == 200 and [(p["pcId"], p["label"], p["state"]) for p in rows] == [("pc_01", "2층", "pending")]
          and r.json().get("used") == 1, repr(r))
    check("토큰 원문은 GET 응답에 없다", info.get("token") and info["token"] not in r.raw and text not in r.raw)
    check("이름이 비면 400, 대기는 생기지 않는다", api("POST", "/api/pcs", {"label": "  "}, token=BOSS).status == 400
          and api("POST", "/api/pcs", {"label": 5}, token=BOSS).status == 400 and reg.used() == 1)
    check("본문이 dict 가 아니면 400", api("POST", "/api/pcs", ["2층"], token=BOSS).status == 400)
    got = local_store.enroll(text, GUIDS[1], "OFFICE-1")
    check("등록 글로 PC 가 등록된다 (같은 서버의 /enroll)", got.get("pc_id") == "pc_01" and reg.state("pc_01") == "active", repr(sorted(got)))
    r = api("POST", "/api/pcs", {"label": "3층"}, token=BOSS)
    text2 = (r.json() or {}).get("enrollment") or ""
    SECRETS.append(text2)
    if text2.startswith("APE1."):
        SECRETS.append(pc_registry.decode_enrollment(text2)["token"])
    got2 = local_store.enroll(text2, GUIDS[2], "OFFICE-2") if r.status == 200 else {}
    check("두 번째 PC pc_02 등록", r.status == 200 and got2.get("pc_id") == "pc_02" and reg.state("pc_02") == "active", repr(r))
    lg = log_text(DATA)
    check("기록에 'PC 추가  번호=pc_01 … 처리=boss'", "PC 추가  번호=pc_01" in lg and "처리=boss" in lg, lg[-400:])

    # ------------------------------------------------------------------------------------------
    print("test_seats_full_409")
    reg.seats = 2
    r = api("POST", "/api/pcs", {"label": "넘침"}, token=BOSS)
    check("자리를 다 쓰면 409 seats-full (자리 수를 알려 준다)", r.status == 409 and r.code == "seats-full" and "2대" in (r.json() or {}).get("message", ""),
          repr(r))
    check("자리가 없으면 대기도 생기지 않는다", reg.used() == 2)
    reg.seats = 3
    r = api("POST", "/api/pcs", {"label": "대기"}, token=BOSS)
    pend = (r.json() or {}).get("pcId")
    if r.status == 200:
        SECRETS.append(r.json()["enrollment"])
    check("자리가 나면 다시 추가된다 (pc_03 대기)", r.status == 200 and pend == "pc_03", repr(r))
    r = api("POST", "/api/pcs/pc_03", {"cancel": True}, token=BOSS)
    check("POST /api/pcs/<id> {cancel} → 대기 취소", r.status == 200 and "pc_03" not in [p["pcId"] for p in r.json()["pcs"]] and reg.used() == 2, repr(r))
    check("없는 대기 취소는 404", api("POST", "/api/pcs/pc_03", {"cancel": True}, token=BOSS).status == 404)
    r = api("POST", "/api/pcs", {"label": "또 대기"}, token=BOSS)
    if r.status == 200:
        SECRETS.append(r.json()["enrollment"])
    check("지운 번호는 다시 쓰지 않는다 (pc_04)", r.status == 200 and r.json().get("pcId") == "pc_04", repr(r))
    r = api("DELETE", "/api/pcs/pc_04", token=BOSS)
    check("대기 중인 PC 를 DELETE → 대기만 버린다", r.status == 200 and reg.used() == 2 and "pc_04" not in [p["pcId"] for p in r.json()["pcs"]], repr(r))
    check("기록에 '등록 취소'", "등록 취소  번호=pc_03" in log_text(DATA) and "등록 취소  번호=pc_04" in log_text(DATA), log_text(DATA)[-400:])

    print("PC 고치기 (POST /api/pcs/<id>)")
    r = api("POST", "/api/pcs/pc_01", {"label": "2층 사무실"}, token=BOSS)
    check("이름 바꾸기", r.status == 200 and [p["label"] for p in r.json()["pcs"] if p["pcId"] == "pc_01"] == ["2층 사무실"], repr(r))
    check("바꿀 것이 없거나 둘이면 400", api("POST", "/api/pcs/pc_01", {}, token=BOSS).status == 400
          and api("POST", "/api/pcs/pc_01", {"label": "a", "disabled": True}, token=BOSS).status == 400
          and api("POST", "/api/pcs/pc_01", {"disabled": "yes"}, token=BOSS).status == 400
          and api("POST", "/api/pcs/pc_01", {"cancel": False}, token=BOSS).status == 400
          and reg.state("pc_01") == "active")
    check("이상한 PC 번호 400, 없는 PC 404", api("POST", "/api/pcs/..", {"disabled": True}, token=BOSS).status == 400
          and api("POST", "/api/pcs/pc_1", {"disabled": True}, token=BOSS).status == 400
          and api("POST", "/api/pcs/pc_77", {"disabled": True}, token=BOSS).status == 404)
    check("유저는 고치지 못한다", api("POST", "/api/pcs/pc_01", {"disabled": True}, token=STAFF).status == 403 and reg.state("pc_01") == "active")
    lg = log_text(DATA)
    check("기록에 '이름 변경'", "이름 변경  번호=pc_01" in lg, lg[-300:])

    # ------------------------------------------------------------------------------------------
    print("test_command_needs_pc")
    r = api("POST", "/api/commands", {"type": "launch", "args": None}, token=BOSS)
    check("pcId 없는 명령 → 400 'PC 를 골라 주십시오.'", r.status == 400 and r.code == "invalid-argument"
          and "PC 를 골라" in (r.json() or {}).get("message", ""), repr(r))
    check("PC 번호 꼴이 아니면 400", api("POST", "/api/commands", {"type": "launch", "pcId": "pc_1"}, token=BOSS).status == 400
          and api("POST", "/api/commands", {"type": "launch", "pcId": 1}, token=BOSS).status == 400)
    r = api("POST", "/api/commands", {"type": "launch", "pcId": "pc_77"}, token=BOSS)
    check("없는 PC → 404 not-found", r.status == 404 and r.code == "not-found", repr(r))
    r = api("POST", "/api/pcs/pc_02", {"disabled": True}, token=BOSS)
    check("사용 중지", r.status == 200 and reg.state("pc_02") == "disabled", repr(r))
    r = api("POST", "/api/commands", {"type": "launch", "pcId": "pc_02"}, token=BOSS)
    check("사용 중지된 PC 에 명령 → 409 failed-precondition", r.status == 409 and r.code == "failed-precondition", repr(r))
    check("거절된 명령은 생기지 않는다", store.get(cmds_of("pc_02")) is None)
    r = api("POST", "/api/commands", {"type": "launch", "args": None, "pcId": "pc_01"}, token=BOSS)
    K1 = (r.json() or {}).get("key")
    check("active PC → 200, commands/c1/pc_01 아래에 생긴다", r.status == 200 and K1 and (store.get(f"{cmds_of('pc_01')}/{K1}") or {}).get("type") == "launch"
          and store.get(cmds_of("srv")) is None, repr(r))
    check("유저는 명령을 못 보낸다", api("POST", "/api/commands", {"type": "launch", "pcId": "pc_01"}, token=STAFF).status == 403)
    r = api("GET", f"/api/commands/{K1}?pcId=pc_01", token=STAFF)
    check("명령 하나 읽기 (pcId)", r.status == 200 and (r.json() or {}).get("type") == "launch", repr(r))
    check("명령 읽기에 pcId 가 없으면 400", api("GET", f"/api/commands/{K1}", token=STAFF).status == 400)
    r = api("GET", f"/api/commands/{K1}?pcId=pc_02", token=STAFF)
    check("다른 PC 자리에서는 null (사용 중지된 PC 도 읽기는 된다)", r.status == 200 and r.raw.strip() == "null", repr(r))
    lg = log_text(DATA)
    check("기록에 '사용 중지'", "사용 중지  번호=pc_02" in lg, lg[-300:])

    # ------------------------------------------------------------------------------------------
    print("test_company_lists_pcs")
    r = api("POST", "/api/pcs", {"label": "대기 PC"}, token=BOSS)
    if r.status == 200:
        SECRETS.append(r.json()["enrollment"])
    pend = (r.json() or {}).get("pcId")
    r = api("GET", "/api/company", token=STAFF)
    co = r.json() or {}
    pcs = co.get("pcs") or {}
    check("/api/company 의 pcs = active·disabled 만 (대기 없음)", r.status == 200 and sorted(pcs) == ["pc_01", "pc_02"] and pend not in pcs, repr(r))
    check("PC 마다 label·state·lastSeen", pcs.get("pc_01", {}).get("label") == "2층 사무실" and pcs.get("pc_01", {}).get("state") == "active"
          and pcs.get("pc_02", {}).get("state") == "disabled" and "lastSeen" in pcs.get("pc_01", {}), repr(pcs))
    check("사내 서버의 pcId 는 null, cid·apps 는 그대로", "pcId" in co and co["pcId"] is None and co.get("cid") == "c1" and "rpa" in co.get("apps", {}),
          repr(co))
    api("DELETE", f"/api/pcs/{pend}", token=BOSS)

    # ------------------------------------------------------------------------------------------
    print("test_stream_per_pc")
    s0 = Stream(STAFF)
    check("pcId 없는 스트림 → 400", s0.wait(lambda s: s.ended) and s0.status == 400, repr(s0.status))
    s0 = Stream(STAFF, "?pcId=pc_77")
    check("없는 PC 스트림 → 404", s0.wait(lambda s: s.ended) and s0.status == 404, repr(s0.status))
    s1 = Stream(STAFF, "?pcId=pc_01")
    streams.append(s1)
    check("붙으면 그 PC 의 live (없으면 null)", s1.wait(lambda s: len(s.named("live")) >= 1) and s1.named("live") == [None], repr(s1.events))
    store.put(live_of("pc_02"), {"state": "idle", "who": "pc_02"})
    store.put(f"{cmds_of('pc_02')}/k2", {"type": "launch", "state": "queued"})
    store.put(live_of("pc_01"), {"state": "running", "who": "pc_01"})
    check("pc_01 현황을 바꾸면 온다", s1.wait(lambda s: {"state": "running", "who": "pc_01"} in s.named("live")), repr(s1.events))
    check("pc_02 현황은 pc_01 스트림에 오지 않는다", s1.named("live") == [None, {"state": "running", "who": "pc_01"}], repr(s1.events))
    n = len(s1.named("command"))
    store.patch(f"{cmds_of('pc_01')}/{K1}", {"state": "running"})
    check("pc_01 명령은 온다", s1.wait(lambda s: len(s.named("command")) > n) and s1.named("command")[-1]["key"] == K1, repr(s1.events))
    check("pc_02 명령은 오지 않는다", all(c["key"] != "k2" for c in s1.named("command")), repr(s1.events))
    s2 = Stream(STAFF, "?pcId=pc_02")
    streams.append(s2)
    check("사용 중지된 PC 의 현황도 볼 수 있다", s2.wait(lambda s: len(s.named("live")) >= 1) and s2.named("live") == [{"state": "idle", "who": "pc_02"}],
          repr(s2.events))
    r = api("POST", "/api/pcs/pc_02", {"disabled": False}, token=BOSS)
    check("사용 재개", r.status == 200 and reg.state("pc_02") == "active" and "사용 재개  번호=pc_02" in log_text(DATA), repr(r))

    # ------------------------------------------------------------------------------------------
    print("test_remove_clears_spots")
    store.put(f"{cmds_of('pc_02')}/k3", {"type": "stop_rpa", "state": "queued"})
    runs.create("runs/c1", "items", "d1", {"pcId": "pc_02", "date": "2026-11-24", "started_at": "2026-11-24T09:00:00", "program": "pc02-run"})
    runs.create("runs/c1", "items", "d2", {"pcId": "pc_01", "date": "2026-11-24", "started_at": "2026-11-24T09:10:00", "program": "pc01-run"})
    r = api("GET", "/api/runs?pcId=pc_01", token=STAFF)
    check("실행 기록은 고른 PC 것만", r.status == 200 and [d["program"] for d in r.json()["runs"]] == ["pc01-run"], repr(r))
    check("실행 기록에 pcId 가 없으면 400·다른 업체 403", api("GET", "/api/runs", token=STAFF).status == 400
          and api("GET", "/api/runs?pcId=pc_01&cid=c9", token=STAFF).status == 403)
    check("유저는 지우지 못한다", api("DELETE", "/api/pcs/pc_02", token=STAFF).status == 403 and reg.state("pc_02") == "active")
    r = api("DELETE", "/api/pcs/pc_02", token=BOSS)
    check("DELETE → 200, 목록에서 빠지고 등록부는 removed", r.status == 200 and "pc_02" not in [p["pcId"] for p in r.json()["pcs"]]
          and reg.state("pc_02") == "removed", repr(r))
    check("그 PC 의 현황·명령 자리가 빈다", store.get(live_of("pc_02")) is None and store.get(cmds_of("pc_02")) is None)
    check("다른 PC 의 자리는 그대로", (store.get(live_of("pc_01")) or {}).get("who") == "pc_01" and store.get(f"{cmds_of('pc_01')}/{K1}") is not None)
    r = api("GET", "/api/runs?pcId=pc_02", token=STAFF)
    check("지운 PC 의 실행 기록 조회는 된다", r.status == 200 and [d["program"] for d in r.json()["runs"]] == ["pc02-run"], repr(r))
    check("지운 PC 에 명령·스트림·명령 읽기 → 404", api("POST", "/api/commands", {"type": "launch", "pcId": "pc_02"}, token=BOSS).status == 404
          and api("GET", "/api/commands/k3?pcId=pc_02", token=STAFF).status == 404
          and (lambda s: s.wait(lambda x: x.ended) and s.status == 404)(Stream(STAFF, "?pcId=pc_02")))
    check("/api/company 에서도 빠진다", sorted((api("GET", "/api/company", token=STAFF).json() or {}).get("pcs") or {}) == ["pc_01"])
    check("두 번 지우면 404", api("DELETE", "/api/pcs/pc_02", token=BOSS).status == 404)
    check("기록에 '삭제'", "삭제  번호=pc_02  처리=boss" in log_text(DATA), log_text(DATA)[-300:])

    # ------------------------------------------------------------------------------------------
    print("test_single_pcs_404")
    r = api("GET", "/api/pcs", token=BOSS1, base=BASE1)
    check("단독 서버의 /api/pcs → 404 '사내 서버에서만'", r.status == 404 and "사내 서버에서만" in (r.json() or {}).get("message", ""), repr(r))
    check("단독 서버의 POST·DELETE /api/pcs 도 404", api("POST", "/api/pcs", {"label": "x"}, token=BOSS1, base=BASE1).status == 404
          and api("DELETE", "/api/pcs/pc_01", token=BOSS1, base=BASE1).status == 404)
    r = api("POST", "/api/commands", {"type": "launch", "args": None}, token=BOSS1, base=BASE1)
    KS = (r.json() or {}).get("key")
    check("단독 명령은 pcId 없이 지금처럼 (commands/c1/p1)", r.status == 200 and store1.get(f"apps/rpa/commands/c1/p1/{KS}") is not None, repr(r))
    check("단독 명령에 자기 pcId 는 되고 다른 PC 는 403", api("POST", "/api/commands", {"type": "launch", "pcId": "p1"}, token=BOSS1, base=BASE1).status == 200
          and api("POST", "/api/commands", {"type": "launch", "pcId": "pc_01"}, token=BOSS1, base=BASE1).status == 403)
    check("단독 명령 읽기는 pcId 없이", api("GET", f"/api/commands/{KS}", token=BOSS1, base=BASE1).json().get("type") == "launch")
    co = api("GET", "/api/company", token=BOSS1, base=BASE1).json() or {}
    check("단독 /api/company 는 지금 그대로 (pcId=p1, PC 하나)", co.get("pcId") == "p1" and list(co.get("pcs") or {}) == ["p1"]
          and set(co["pcs"]["p1"]) == {"label"}, repr(co))
    check("단독 실행 기록 - 다른 PC 는 403, 없으면 이 PC", api("GET", "/api/runs?pcId=p9", token=BOSS1, base=BASE1).status == 403
          and api("GET", "/api/runs", token=BOSS1, base=BASE1).status == 200)
    s3 = Stream(BOSS1, base=BASE1)
    streams.append(s3)
    check("단독 스트림은 pcId 없이 붙는다", s3.wait(lambda s: len(s.named("live")) >= 1) and s3.status == 200, repr((s3.status, s3.events)))

    # ------------------------------------------------------------------------------------------
    print("기록")
    lg = log_text(DATA)
    check("서버 기록에 등록 토큰·등록 글이 없다", all(s and s not in lg for s in SECRETS), "토큰이 기록에 있음")
    check("서버 기록에 세션 토큰이 없다", BOSS not in lg and STAFF not in lg)
finally:
    for s in streams:
        s.close()
    for s in (srv, srv1):
        if s is not None:
            try:
                s.shutdown()
                s.server_close()
            except Exception:
                pass
    for r_ in (runs, runs1):
        if r_ is not None:
            try:
                r_.close()
            except Exception:
                pass
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n실패 {len(fails)}건" + ("" if not fails else ": " + ", ".join(fails)))
sys.exit(1 if fails else 0)
