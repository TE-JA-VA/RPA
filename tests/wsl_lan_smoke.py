# -*- coding: utf-8 -*-
"""사내 서버 ② Task 8 - WSL(리눅스)에서 사내 서버를 한 번 끝까지 (계획 2026-11-24-lan-2-network Task 8).
리눅스 파이썬으로: /tmp 아래 임시 폴더 → lan_ca.find_openssl() 이 리눅스 openssl 을 찾는다 → 인증 기관·서버 인증서를 만들고
열쇠 파일이 0600 → make_lan_servers 를 127.0.0.1 에 포트 0 으로 → 웹 로그인(https, Host·Origin) → /api/pcs 로 PC 추가 →
local_store.enroll → 그 열쇠로 현황 PATCH → 웹 스트림(/api/stream)에 그 현황이 온다.
그동안 윈도우 전용 길(local_server.lock_key_files 의 icacls, creationflags=CREATE_NO_WINDOW)을 타면 실패로 본다 -
subprocess.Popen 과 local_server.lock_key_files 를 엿보기로 바꿔 끼워 부른 자리를 남긴다 (icacls 는 실제로 부르지 않는다).
/mnt/d 는 0600 을 지키지 못하므로 임시 폴더는 반드시 /tmp 아래. 리눅스가 아니면 건너뛴다 (종료 코드 0).
    wsl.exe -d Ubuntu -e python3 /mnt/d/AX/RPA_StandAlone/tests/wsl_lan_smoke.py
    D:/AX/RPA/.venv/Scripts/python.exe tests/run_standalone_suite.py wsl
"""
import dataclasses
import http.client
import json
import os
import secrets
import shutil
import ssl
import stat
import subprocess
import sys
import tempfile
import threading
import time
import traceback

sys.stdout.reconfigure(encoding="utf-8")
if os.name != "posix" or not sys.platform.startswith("linux"):
    print("  [건너뜀] 리눅스(WSL)에서만 도는 시험입니다.")
    print("\n실패 0건")
    sys.exit(0)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))

# --- 윈도우 전용 길 엿보기 (모듈을 불러오기 전에 끼운다) ---
SPAWNED = []          # (argv, creationflags, 부른 자리)
LOCKED = []           # lock_key_files 를 부른 자리


def _where():
    """우리 저장소 안의 가장 가까운 부른 자리 (파일:줄)."""
    for fr in reversed(traceback.extract_stack()[:-2]):
        if fr.filename.startswith(ROOT) and not fr.filename.endswith("wsl_lan_smoke.py"):
            return f"{os.path.relpath(fr.filename, ROOT)}:{fr.lineno}"
    return "?"


class SpyPopen(subprocess.Popen):
    def __init__(self, args, *a, **kw):
        argv = [str(x) for x in (args if isinstance(args, (list, tuple)) else [args])]
        SPAWNED.append((argv, kw.get("creationflags", 0), _where()))
        super().__init__(args, *a, **kw)


subprocess.Popen = SpyPopen

import lan_ca  # noqa: E402
import lan_config  # noqa: E402
import lan_server  # noqa: E402
import local_server  # noqa: E402
import local_store  # noqa: E402
import local_web  # noqa: E402
import pc_registry  # noqa: E402


def _spy_lock(folder, readers=(), run=None):
    LOCKED.append((folder, _where()))
    return []                                  # icacls 는 부르지 않는다


local_server.lock_key_files = _spy_lock

fails = []
TMP = tempfile.mkdtemp(prefix="rpa_wsl_lan_", dir="/tmp")
LIC = {"edition": "standalone", "company": "시험상사", "cid": "c1", "pc_id": "srv", "issued": "2026-11-24",
       "modules": {}, "features": {}, "limits": {}}
BOSS_PW = "pw-12345678"
GUID = "77777777-8888-9999-aaaa-bbbbbbbbbb01"


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def until(fn, sec):
    end = time.time() + sec
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.02)
    return bool(fn())


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


class Got:
    def __init__(self, status, raw):
        self.status, self.raw = status, raw

    def json(self):
        try:
            return json.loads(self.raw) if self.raw else None
        except ValueError:
            return None

    def __repr__(self):
        return f"<{self.status} {self.raw[:200]!r}>"


SERVERS, RUNS = [], []
stream_conn = None
try:
    print("리눅스에서 사내 서버 한 번 (wsl_lan_smoke)")
    check(f"리눅스 파이썬 {sys.version.split()[0]} ({sys.platform})", sys.platform.startswith("linux"))
    check("임시 폴더는 /tmp 아래 (/mnt 가 아니다)", os.path.realpath(TMP).startswith("/tmp/") and mode(TMP) == 0o700,
          (TMP, oct(mode(TMP))))

    # 1. openssl
    exe = lan_ca.find_openssl()
    check("find_openssl() 이 리눅스 openssl 을 찾는다", exe == shutil.which("openssl") and exe.startswith("/")
          and not exe.startswith("/mnt/") and os.path.basename(exe) == "openssl", exe)
    ver = lan_ca._run(None, ["version"]).strip()
    check(f"openssl 이 돈다 ({ver})", ver.startswith("OpenSSL"), ver)

    # 2. 인증 기관·서버 인증서, 열쇠 0600
    CA_DIR, OUT = os.path.join(TMP, "ca"), os.path.join(TMP, "srv")
    lan_ca.make_ca(CA_DIR, ["localhost"], ["127.0.0.1"])
    CERT, KEY = lan_ca.issue_server(CA_DIR, OUT, ["localhost"], ["127.0.0.1"])
    CA_PEM = lan_ca.ca_pem(CA_DIR)
    ca_key = os.path.join(CA_DIR, lan_ca.CA_KEY)
    check("인증 기관 열쇠 0600", mode(ca_key) == 0o600, oct(mode(ca_key)))
    check("서버 열쇠 0600", mode(KEY) == 0o600, oct(mode(KEY)))
    check("인증 기관 폴더 0700", mode(CA_DIR) == 0o700, oct(mode(CA_DIR)))
    check("만들 때 쓴 임시 폴더(.lan_ca_*)는 남지 않는다",
          not [n for d in (CA_DIR, OUT) for n in os.listdir(d) if n.startswith(".lan_ca_")])
    ossl = [s for s in SPAWNED if os.path.basename(s[0][0]) == "openssl"]
    check("openssl 은 creationflags 0 으로 부른다 (CREATE_NO_WINDOW 는 윈도우만)", ossl and all(s[1] == 0 for s in ossl),
          [(s[0][:2], s[1], s[2]) for s in ossl])

    # 3. 두 포트
    DATA = os.path.join(TMP, "lan")
    os.makedirs(DATA)
    WEB_DIR = os.path.join(TMP, "web")
    os.makedirs(WEB_DIR)
    with open(os.path.join(WEB_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write("<!doctype html><title>로그인</title>")
    store = local_server.Store(os.path.join(DATA, "store.json"), volatile=local_server.VOLATILE)
    runs = local_server.Runs(os.path.join(DATA, "runs.db"))
    RUNS.append(runs)
    reg = pc_registry.Registry(os.path.join(DATA, "pcs.json"), seats=5)
    web = local_web.Web(store, runs, LIC, DATA, WEB_DIR, registry=reg)
    web.accounts.set("boss", BOSS_PW, "admin")
    cfg = lan_config.parse({"listen": "127.0.0.1", "names": ["localhost"], "allow": ["127.0.0.0/8"]})
    cfg = dataclasses.replace(cfg, web_port=0, agent_port=0)
    w, a = lan_server.make_lan_servers(store, runs, LIC, reg, web, cfg, CERT, KEY, CA_PEM)
    for s in (w, a):
        SERVERS.append(s)
        threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    WP, AP = w.server_address[1], a.server_address[1]
    check("make_lan_servers 가 127.0.0.1 에 두 포트 (TLS)", w.server_address[0] == a.server_address[0] == "127.0.0.1"
          and WP != AP and isinstance(w.tls, ssl.SSLContext) and isinstance(a.tls, ssl.SSLContext))
    HOST, ORIGIN = f"127.0.0.1:{WP}", f"https://127.0.0.1:{WP}"

    def ctx():
        return ssl.create_default_context(cadata=CA_PEM)

    def call(method, path, body=None, token=None, origin=ORIGIN):
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        hs = {"Host": HOST}
        if origin:
            hs["Origin"] = origin
        if data is not None:
            hs["Content-Type"] = "application/json"
        if token:
            hs["Authorization"] = "Bearer " + token
        c = http.client.HTTPSConnection("127.0.0.1", WP, context=ctx(), timeout=10)
        try:
            c.request(method, path, body=data, headers=hs)
            r = c.getresponse()
            return Got(r.status, r.read().decode("utf-8", "replace"))
        finally:
            c.close()

    # 4. 웹 로그인 (https, Host·Origin)
    g = call("POST", "/api/login", {"id": "boss", "password": BOSS_PW}, origin=f"http://127.0.0.1:{WP}")
    check("http Origin 으로는 로그인 403", g.status == 403, g)
    g = call("POST", "/api/login", {"id": "boss", "password": BOSS_PW})
    BOSS = (g.json() or {}).get("token") if g.status == 200 else None
    check("https Origin·Host 로 관리자 로그인 200", bool(BOSS), g)

    # 5. PC 추가 → 등록
    g = call("POST", "/api/pcs", {"label": "리눅스 시험"}, token=BOSS)
    out = g.json() or {}
    PC, TEXT = out.get("pcId"), out.get("enrollment") or ""
    check("/api/pcs 로 PC 추가 → pc_01·등록 글", g.status == 200 and PC == "pc_01" and TEXT.startswith("APE1."), g)
    info = pc_registry.decode_enrollment(TEXT)
    check("등록 글의 주소는 https 에이전트 포트, 인증 기관 실림", info["url"] == f"https://127.0.0.1:{AP}" and info.get("ca") == CA_PEM,
          info.get("url"))
    got = local_store.enroll(TEXT, GUID, "WSL-PC")
    check("local_store.enroll 이 https 로 등록, 열쇠가 서버와 같다", got.get("pc_id") == PC and got.get("ca_pem") == CA_PEM
          and (got.get("agent_key"), got.get("relay_key")) == reg.keys(PC) and reg.state(PC) == "active", sorted(got))

    # 6. 웹 스트림을 열어 두고 현황 PATCH
    events = []

    def reader(resp):
        try:
            while True:
                line = resp.fp.readline()
                if not line:
                    break
                if line.startswith(b"event: "):
                    events.append([line[7:].strip().decode(), None])
                elif line.startswith(b"data: ") and events:
                    events[-1][1] = json.loads(line[6:].decode("utf-8"))
        except Exception:
            pass                               # 닫으면 읽기 오류 - 끝난 것으로 본다

    stream_conn = http.client.HTTPSConnection("127.0.0.1", WP, context=ctx(), timeout=15)
    stream_conn.request("GET", f"/api/stream?pcId={PC}", headers={"Host": HOST, "Authorization": "Bearer " + BOSS})
    resp = stream_conn.getresponse()
    check("웹 스트림 200 (text/event-stream)", resp.status == 200 and (resp.getheader("Content-Type") or "").startswith("text/event-stream"),
          resp.status)
    threading.Thread(target=reader, args=(resp,), daemon=True).start()
    check("붙자마자 live(아직 없음) 하나", until(lambda: any(e[0] == "live" for e in events), 5), events)

    MARK = "wsl-" + secrets.token_hex(4)
    cl = local_store.Client({"standalone": True, "server_url": got["server_url"], "key": got["agent_key"], "role": "agent",
                             "lan": True, "pc_id": PC, "ca_pem": got["ca_pem"]})
    cl.patch(f"apps/rpa/live/c1/{PC}", {"state": "idle", "who": MARK})
    check("현황 PATCH 가 저장소에", (store.get(f"apps/rpa/live/c1/{PC}") or {}).get("who") == MARK)
    check("3초 안에 웹 스트림에 그 현황이 온다",
          until(lambda: any(e[0] == "live" and isinstance(e[1], dict) and e[1].get("who") == MARK for e in events), 3), events)
    check("클라이언트로 읽기 (서명된 응답)", (cl.get(f"apps/rpa/live/c1/{PC}") or {}).get("who") == MARK)

    # 7. 윈도우 전용 길
    print("  윈도우 전용 길 (설계 13절 9 는 ④ 몫 - 여기서는 막히는 곳만 찾는다)")
    check("lock_key_files(icacls) 를 부르지 않았다", not LOCKED, LOCKED)
    win = [(s[0][:2], s[1], s[2]) for s in SPAWNED if s[1] or "icacls" in os.path.basename(s[0][0]).lower()]
    check("creationflags(CREATE_NO_WINDOW)·icacls 로 프로세스를 띄우지 않았다", not win, win)
    check("띄운 프로세스는 openssl 뿐", all(os.path.basename(s[0][0]) == "openssl" for s in SPAWNED),
          [(s[0][:2], s[2]) for s in SPAWNED])
    n_spawn, n_lock = len(SPAWNED), len(LOCKED)       # 엿보기가 헛돌지 않는가 - 일부러 한 번씩 타 본다
    try:
        subprocess.run(["true"], creationflags=lan_ca.CREATE_NO_WINDOW)
    except ValueError:                                 # 리눅스는 creationflags 를 받지 않는다 - 엿보기는 그 전에 남긴다
        pass
    local_server.ensure_keys(os.path.join(TMP, "keys"), lock=True)
    check("엿보기 확인: 일부러 탄 CREATE_NO_WINDOW·lock_key_files 를 자리와 함께 잡는다",
          len(SPAWNED) == n_spawn + 1 and SPAWNED[-1][1] == lan_ca.CREATE_NO_WINDOW and len(LOCKED) == n_lock + 1
          and LOCKED[-1][1].startswith("firebase/agent/local_server.py:"), (SPAWNED[n_spawn:], LOCKED[n_lock:]))
    for name in ("pcs.json", "accounts.json"):        # 참고만 - 리눅스 권한 잠그기는 ④ 몫
        p = os.path.join(DATA, name)
        if os.path.isfile(p):
            print(f"  [참고] {name} 권한 {oct(mode(p))} (윈도우는 lock_key_files, 리눅스는 ④ 에서)")
except Exception as ex:
    check("예외 없이 끝난다", False, f"{type(ex).__name__}: {ex}\n{traceback.format_exc()[-1500:]}")
finally:
    if stream_conn is not None:
        try:
            stream_conn.close()
        except Exception:
            pass
    for s in SERVERS:
        try:
            s.shutdown()
            s.server_close()
        except Exception:
            pass
    for r in RUNS:
        try:
            r.close()
        except Exception:
            pass
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n실패 {len(fails)}건" + (": " + ", ".join(fails) if fails else ""))
sys.exit(1 if fails else 0)
