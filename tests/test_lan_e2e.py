# -*- coding: utf-8 -*-
"""사내 서버 ① Task 7 - 가짜 PC 셋 전체 흐름 (계획 2026-11-24-lan-1-server-multi-pc, test_three_pcs_end_to_end).
모두 진짜 HTTP 로: 웹 관리자가 PC 셋 추가 → 등록 글로 local_store.enroll → lan 클라이언트 셋이 각자 현황 PATCH·명령 구독 →
관리자가 pc_02 에 launch → pc_02 구독에만 온다 → pc_02 가 queued→running→done·실행 기록 POST →
웹 /api/runs 는 고른 PC 것만 → pc_03 삭제 → pc_03 의 다음 요청은 AuthError(PC_REMOVED)·구독은 3초 안에 끝난다.
test_lan_server.py 와 따로 둔다 (그 파일은 순서에 기대는 시험이 많다). 임시 폴더만 쓴다.
    D:/AX/RPA/.venv/Scripts/python.exe tests/test_lan_e2e.py
"""
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
import local_web  # noqa: E402
import pc_registry  # noqa: E402

fails = []
TMP = tempfile.mkdtemp(prefix="rpa_lan_e2e_")
LIC = {"edition": "standalone", "company": "시험상사", "cid": "c1", "pc_id": "srv", "issued": "2026-11-24",
       "modules": {"Hold": False}, "features": {"wellife": False}, "limits": {"schedule": 3, "presets": None, "parallel": None}}
NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))
BOSS_PW = "pw-12345678"
GUIDS = ["aaaaaaaa-bbbb-cccc-dddd-0000000000%02d" % i for i in range(1, 4)]
HOSTS = ["OFFICE-1", "OFFICE-2", "OFFICE-3"]
PCS = ["pc_01", "pc_02", "pc_03"]


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
    def __init__(self, status, raw):
        self.status, self.raw = status, raw

    def json(self):
        try:
            return json.loads(self.raw) if self.raw else None
        except ValueError:
            return None

    def __repr__(self):
        return f"<{self.status} {self.raw[:300]}>"


def api(method, path, body=None, token=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    hs = {"Content-Type": "application/json"} if data is not None else {}
    if token:
        hs["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=hs)
    try:
        with NO_PROXY.open(req, timeout=15) as r:
            got, status = r.read(), r.status
    except urllib.error.HTTPError as e:
        got, status = e.read(), e.code
    return Got(status, got.decode("utf-8", "replace"))


class Opener:
    """Client 의 opener - 구독 응답을 잡아 두어 끝에 닫을 수 있게 한다 (스레드가 읽는 제너레이터는 밖에서 close 못 한다)."""

    def __init__(self):
        self.held = []

    def __call__(self, req, timeout=None):
        resp = NO_PROXY.open(req, timeout=timeout)
        if (req.get_header("Accept") or "") == "text/event-stream":
            self.held.append(resp)
        return resp

    def close(self):
        for r in self.held:
            try:
                r.close()
            except Exception:
                pass


class CmdStream:
    """Client.stream(명령함, state==queued) 을 스레드에서 돌려 이벤트와 본 명령 키를 모은다."""

    def __init__(self, client, pc):
        self.client, self.pc = client, pc
        self.events, self.keys, self.error = [], set(), None
        self.ended = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            for event, data in self.client.stream(f"apps/rpa/commands/c1/{self.pc}",
                                                  {"orderBy": '"state"', "equalTo": '"queued"'}, timeout=60):
                self.events.append((event, data))
                if event in ("put", "patch") and isinstance(data, dict):
                    path, val = data.get("path") or "/", data.get("data")
                    if path == "/":
                        if isinstance(val, dict):
                            self.keys.update(k for k, v in val.items() if v is not None)
                    elif val is not None:
                        self.keys.add(path.strip("/").split("/")[0])
        except Exception as e:                 # 닫으면 읽기 오류가 날 수 있다 - 끝난 것으로 본다
            self.error = e
        self.ended.set()

    def started(self):
        return any(e == "put" for e, _ in list(self.events))


srv = runs = None
openers, streams = [], []
try:
    DATA = os.path.join(TMP, "lan")
    os.makedirs(DATA)
    store = local_server.Store(os.path.join(DATA, "store.json"), volatile=local_server.VOLATILE)
    runs = local_server.Runs(os.path.join(DATA, "runs.db"))
    reg = pc_registry.Registry(os.path.join(DATA, "pcs.json"), seats=5)
    web = local_web.Web(store, runs, LIC, DATA, None, registry=reg)
    web.accounts.set("boss", BOSS_PW, "admin")
    srv = local_server.make_server(store, runs, LIC, None, port=0, folder=DATA, web=web, registry=reg)
    BASE = f"http://127.0.0.1:{srv.server_address[1]}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    print("test_three_pcs_end_to_end")
    r = api("POST", "/api/login", {"id": "boss", "password": BOSS_PW})
    BOSS = (r.json() or {}).get("token") if r.status == 200 else None
    check("관리자 로그인", bool(BOSS), repr(r))

    # 1. 웹으로 PC 셋 추가 → 각 등록 글로 등록 → lan 클라이언트 셋
    clients = {}
    for i, pc in enumerate(PCS):
        r = api("POST", "/api/pcs", {"label": f"{i + 1}층"}, token=BOSS)
        out = r.json() or {}
        check(f"PC 추가 → {pc}", r.status == 200 and out.get("pcId") == pc and str(out.get("enrollment", "")).startswith("APE1."), repr(r))
        got = local_store.enroll(out.get("enrollment") or "", GUIDS[i], HOSTS[i])
        check(f"{pc} 등록 (다른 GUID), 서버와 열쇠가 같다", got.get("pc_id") == pc and got.get("server_url") == BASE
              and (got.get("agent_key"), got.get("relay_key")) == reg.keys(pc) and reg.state(pc) == "active", repr(sorted(got)))
        op = Opener()
        openers.append(op)
        clients[pc] = local_store.Client({"standalone": True, "server_url": got["server_url"], "key": got["agent_key"],
                                          "role": "agent", "lan": True, "pc_id": pc}, opener=op)
    r = api("GET", "/api/pcs", token=BOSS)
    check("목록에 셋 다 active, 자리 3/5", r.status == 200 and [(p["pcId"], p["state"]) for p in r.json()["pcs"]] == [(p, "active") for p in PCS]
          and r.json().get("used") == 3 and r.json().get("seats") == 5, repr(r))

    # 2. 각자 현황 PATCH, 명령 구독
    for pc in PCS:
        clients[pc].patch(f"apps/rpa/live/c1/{pc}", {"state": "idle", "who": pc})
    check("셋이 각자 자기 현황을 썼다", all((store.get(f"apps/rpa/live/c1/{pc}") or {}).get("who") == pc for pc in PCS))
    subs = {pc: CmdStream(clients[pc], pc) for pc in PCS}
    streams.extend(subs.values())
    check("셋의 구독이 열리고 첫 값(put)이 온다", until(lambda: all(s.started() for s in subs.values()), 5)
          and not any(s.ended.is_set() for s in subs.values()), repr({pc: (s.events, s.error) for pc, s in subs.items()}))

    # 3. 관리자가 pc_02 에 launch → pc_02 구독에만
    r = api("POST", "/api/commands", {"type": "launch", "pcId": "pc_02"}, token=BOSS)
    K = (r.json() or {}).get("key")
    check("관리자가 pc_02 에 launch 명령 → 200", r.status == 200 and bool(K), repr(r))
    check("3초 안에 pc_02 구독에 그 명령이 온다", until(lambda: K in subs["pc_02"].keys, 3), repr(subs["pc_02"].events))
    # 뒤에 pc_01·pc_03 에 보낸 표시 명령이 오면 그 구독은 K 뒤의 변화까지 읽은 것이다 (시간이 아니라 조건으로 '안 옴'을 본다)
    marks = {}
    for pc in ("pc_01", "pc_03"):
        r = api("POST", "/api/commands", {"type": "launch", "pcId": pc}, token=BOSS)
        marks[pc] = (r.json() or {}).get("key")
    check("pc_01·pc_03 구독에는 자기 표시 명령만 오고 pc_02 의 명령은 오지 않는다",
          until(lambda: all(marks[pc] in subs[pc].keys for pc in marks), 3) and all(K not in subs[pc].keys for pc in marks),
          repr({pc: subs[pc].keys for pc in marks}))
    check("pc_02 구독에는 남의 표시 명령이 오지 않는다", not (set(marks.values()) & subs["pc_02"].keys), repr(subs["pc_02"].keys))

    # 4. pc_02 가 queued→running→done (agent._mark 꼴), 실행 기록 POST
    c2 = clients["pc_02"]
    base2 = "apps/rpa/commands/c1/pc_02"
    now = int(c2.server_now())
    c2.patch(f"{base2}/{K}", {"state": "running", "started_at": now})
    check("pc_02 가 running 으로 옮긴다", (store.get(f"{base2}/{K}") or {}).get("state") == "running")
    c2.patch(f"{base2}/{K}", {"state": "done", "result": "시작했습니다", "ended_at": now + 1})
    r = api("GET", f"/api/commands/{K}?pcId=pc_02", token=BOSS)
    check("웹에서 그 명령은 done", r.status == 200 and (r.json() or {}).get("state") == "done" and (r.json() or {}).get("started_at") == now, repr(r))
    RID = "run_e2e_pc02_0001"
    doc = {"cid": "c1", "pcId": "pc_02", "run_id": RID, "program": "e2e", "program_label": "전체 흐름",
           "state": "success", "reason": None, "started_at": "2026-11-24T10:00:00", "finished_at": "2026-11-24T10:00:05",
           "duration_sec": 5, "date": "2026-11-24", "used": {"order": 1}, "cost": 1, "payload": json.dumps({"run_id": RID})}
    check("pc_02 가 실행 기록 POST (fs_create)", c2.fs_create("runs/c1/items", fb.fs_fields(doc), RID) is True)
    check("pc_02 는 자기 기록을 읽는다", (c2.fs_get(f"runs/c1/items/{RID}") or {}).get("run_id") == RID)

    # 5. 웹 실행 기록은 고른 PC 것만
    r = api("GET", "/api/runs?pcId=pc_02", token=BOSS)
    check("/api/runs?pcId=pc_02 에 그 기록", r.status == 200 and RID in [d.get("run_id") for d in r.json()["runs"]], repr(r))
    r = api("GET", "/api/runs?pcId=pc_01", token=BOSS)
    check("/api/runs?pcId=pc_01 에는 없다", r.status == 200 and RID not in [d.get("run_id") for d in r.json()["runs"]], repr(r))

    # 6. pc_03 삭제 → 다음 요청 PC_REMOVED, 구독은 3초 안에 끝
    r = api("DELETE", "/api/pcs/pc_03", token=BOSS)
    check("관리자가 pc_03 삭제", r.status == 200 and reg.state("pc_03") == "removed"
          and "pc_03" not in [p["pcId"] for p in r.json()["pcs"]], repr(r))
    try:
        clients["pc_03"].get("apps/rpa/live/c1/pc_03")
        check("pc_03 의 다음 요청은 AuthError PC_REMOVED", False, "예외 없음")
    except fb.AuthError as e:
        check("pc_03 의 다음 요청은 AuthError PC_REMOVED", e.status == 403 and e.code == local_store.PC_REMOVED, repr(e))
    except Exception as e:
        check("pc_03 의 다음 요청은 AuthError PC_REMOVED", False, repr(e))
    check("pc_03 의 구독은 3초 안에 끝난다", subs["pc_03"].ended.wait(3))
    check("다른 PC 는 그대로 쓴다", (clients["pc_01"].get("apps/rpa/live/c1/pc_01") or {}).get("who") == "pc_01"
          and not subs["pc_01"].ended.is_set() and not subs["pc_02"].ended.is_set())
finally:
    for op in openers:
        op.close()
    for s in streams:
        s.ended.wait(3)
    if srv is not None:
        try:
            srv.shutdown()
            srv.server_close()
        except Exception:
            pass
    if runs is not None:
        try:
            runs.close()
        except Exception:
            pass
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n실패 {len(fails)}건" + ("" if not fails else ": " + ", ".join(fails)))
sys.exit(1 if fails else 0)
