# -*- coding: utf-8 -*-
"""사내 서버 ④ Task 1 - 리눅스 갈래와 기록 파일 (계획 2026-11-25-lan-4-linux Task 1).
server_log.RotatingFile(10MB 다섯 개 - 시험은 200바이트 셋), server_log.configure 뒤 local_server.log → server.log·
local_server.audit → audit.log (설정 전에는 단독 그대로 자료 폴더의 로컬서버_기록.txt), 사내 서버 웹의 계정·보안·PC 기록은
audit.log 에만. 리눅스(WSL)에서만: 열쇠·계정 파일 0600·폴더 0700 (icacls 를 부르면 실패), 서버를 닫고 곧바로 같은 포트 다시 열기.
윈도우·WSL 둘 다에서 돈다 (WSL 의 임시 폴더는 /tmp 아래 - /mnt/d 는 권한 비트를 지키지 못한다).
    D:/AX/RPA/.venv/Scripts/python.exe tests/test_server_log.py
    wsl.exe -d Ubuntu -e python3 /mnt/d/AX/RPA_StandAlone/tests/test_server_log.py
"""
import http.client
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
POSIX = os.name == "posix"

# --- 윈도우 전용 길 엿보기 (리눅스에서 icacls·CREATE_NO_WINDOW 로 프로세스를 띄우면 남긴다 - wsl_lan_smoke 와 같은 방식) ---
SPAWNED = []          # (argv, creationflags)
_RealPopen = subprocess.Popen


class SpyPopen(_RealPopen):
    def __init__(self, args, *a, **kw):
        argv = [str(x) for x in (args if isinstance(args, (list, tuple)) else [args])]
        SPAWNED.append((argv, kw.get("creationflags", 0)))
        super().__init__(args, *a, **kw)


if POSIX:
    subprocess.Popen = SpyPopen

import local_server  # noqa: E402
import local_web  # noqa: E402
import pc_registry  # noqa: E402

fails = []
try:
    import server_log  # noqa: E402
except ImportError as e:
    print(f"  [실패] server_log 를 불러오지 못한다 - {e}")
    print("\n실패: 1")
    sys.exit(1)

TMP = tempfile.mkdtemp(prefix="rpa_server_log_", dir="/tmp" if POSIX else None)
LIC = {"edition": "standalone", "company": "시험상사", "cid": "c1", "pc_id": "srv", "issued": "2026-11-25",
       "modules": {}, "features": {}, "limits": {}}
NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))
BOSS_PW = "pw-12345678"
NEW_PW = "new-user-pw-777"


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def guard(name, fn):
    """시험 하나 - 예외는 그 시험의 실패로 (다음 시험은 돈다). 끝나면 기록 설정을 늘 되돌린다."""
    print(name)
    try:
        fn()
    except Exception as ex:
        check(f"{name} - 예외 없이 끝난다", False, f"{type(ex).__name__}: {ex}\n{traceback.format_exc()[-1200:]}")
    finally:
        try:
            server_log.configure(None, None)
        except Exception:
            pass


def test_rotate():
    d = os.path.join(TMP, "rotate")
    os.makedirs(d)
    path = os.path.join(d, "server.log")
    rf = server_log.RotatingFile(path, max_bytes=200, keep=3)
    for i in range(50):
        rf.write(f"줄 {i:03d}")
    names = sorted(os.listdir(d))
    check("server.log·.1·.2 만 남는다 (keep=3)", names == ["server.log", "server.log.1", "server.log.2"], names)
    sizes = {n: os.path.getsize(os.path.join(d, n)) for n in names}
    check("파일마다 200 바이트 안팎 (넘지 않고, 밀린 것은 절반 넘게 찼다)",
          all(s <= 200 for s in sizes.values()) and all(sizes[n] > 100 for n in names if n != "server.log"), sizes)
    lines = read(path).splitlines()
    check("가장 새 줄은 server.log 끝", lines and lines[-1].endswith("줄 049"), lines[-2:])
    check("줄 앞에 YYYY-MM-DD HH:MM:SS", bool(lines) and time.strptime(lines[-1][:19], "%Y-%m-%d %H:%M:%S") is not None, lines[-1:])
    older = read(path + ".1").splitlines()
    check("바로 앞 것은 .1 에 (차례가 이어진다)", older and int(older[-1][-3:]) + 1 == int(lines[0][-3:]), (older[-1:], lines[:1]))
    if POSIX:
        check("처음 만든 기록 파일은 0600", mode(path) == 0o600 and mode(path + ".1") == 0o600, oct(mode(path)))
    # 여러 스레드가 한꺼번에 써도 줄이 섞이거나 사라지지 않는다
    path2 = os.path.join(d, "many.log")
    rf2 = server_log.RotatingFile(path2, max_bytes=10 * 1024 * 1024, keep=5)

    def burst(t):
        for i in range(200):
            rf2.write(f"스레드{t} {i:03d}")
    ts = [threading.Thread(target=burst, args=(t,)) for t in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    got = read(path2).splitlines()
    check("스레드 넷 × 200 줄이 온전히", len(got) == 800 and all(len(ln) == 19 + 2 + len("스레드0 000") for ln in got), len(got))


def test_routes():
    folder = os.path.join(TMP, "routes")
    logs = os.path.join(TMP, "routes_logs")
    os.makedirs(folder)
    os.makedirs(logs)
    old = os.path.join(folder, local_server.LOG_NAME)
    srv_log, aud_log = os.path.join(logs, "server.log"), os.path.join(logs, "audit.log")
    check("처음에는 설정 안 됨 (active False)", server_log.active() is False)
    local_server.log(folder, "첫째 줄 A")
    check("설정 전 log 는 자료 폴더의 옛 기록 파일 (단독 그대로)", "첫째 줄 A" in read(old), read(old))
    local_server.audit(folder, "감사 줄 A0")
    check("설정 전 audit 은 log 와 같다", "감사 줄 A0" in read(old))
    server_log.configure(srv_log, aud_log)
    check("configure 뒤 active True", server_log.active() is True)
    local_server.log(folder, "둘째 줄 B")
    local_server.audit(folder, "감사 줄 C")
    check("설정 뒤 log 는 server.log 로", "둘째 줄 B" in read(srv_log) and "둘째 줄 B" not in read(old), read(srv_log))
    check("설정 뒤 audit 은 audit.log 에만", "감사 줄 C" in read(aud_log) and "감사 줄 C" not in read(srv_log)
          and "감사 줄 C" not in read(old), (read(aud_log), read(srv_log)))
    server_log.configure(None, None)
    local_server.audit(folder, "되돌린 뒤 D")
    check("configure(None, None) 이면 다시 단독 그대로", server_log.active() is False and "되돌린 뒤 D" in read(old))
    server_log.configure(srv_log, None)
    local_server.audit(folder, "감사 자리 없음 E")
    check("audit 자리만 없으면 audit 은 server.log 로 (log 와 같다)", "감사 자리 없음 E" in read(srv_log))


def api(base, method, path, body=None, token=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    hs = {"Content-Type": "application/json"} if data is not None else {}
    if token:
        hs["Authorization"] = "Bearer " + token
    req = urllib.request.Request(base + path, data=data, method=method, headers=hs)
    try:
        with NO_PROXY.open(req, timeout=15) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def test_web_audit():
    data = os.path.join(TMP, "web")
    logs = os.path.join(TMP, "web_logs")
    os.makedirs(data)
    os.makedirs(logs)
    with open(os.path.join(data, "security.json"), "w", encoding="utf-8") as f:     # 2단계 범위 끔 (2단계는 test_lan_mfa)
        f.write('{"version":1,"totp_scope":"off","show_own_history":true}')
    srv_log, aud_log = os.path.join(logs, "server.log"), os.path.join(logs, "audit.log")
    server_log.configure(srv_log, aud_log)
    store = local_server.Store(os.path.join(data, "store.json"), volatile=local_server.VOLATILE)
    runs = local_server.Runs(os.path.join(data, "runs.db"))
    reg = pc_registry.Registry(os.path.join(data, "pcs.json"), seats=3)
    web = local_web.Web(store, runs, LIC, data, None, registry=reg)
    web.accounts.set("boss", BOSS_PW, "admin")
    srv = local_server.make_server(store, runs, LIC, None, port=0, folder=data, web=web, registry=reg)
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        st, got = api(base, "POST", "/api/login", {"id": "boss", "password": BOSS_PW})
        token = got.get("token") if st == 200 and isinstance(got, dict) else None
        check("관리자 로그인 200", bool(token), (st, got))
        st, got = api(base, "POST", "/api/accounts", {"id": "kim", "password": NEW_PW, "role": "viewer"}, token)
        check("계정 추가 200", st == 200, (st, got))
        st, got = api(base, "POST", "/api/security", {"showOwnHistory": False}, token)
        check("보안 설정 변경 200", st == 200, (st, got))
        st, got = api(base, "POST", "/api/pcs", {"label": "기록 시험"}, token)
        check("PC 추가 200", st == 200, (st, got))
        import local_store
        enrolled = local_store.enroll(got["enrollment"], "11111111-2222-3333-4444-555555555501", "AUDIT-PC")
        check("PC 등록 (local_store.enroll)", enrolled.get("pc_id") == "pc_01", sorted(enrolled))
        st, got = api(base, "POST", "/api/commands", {"type": "launch", "pcId": "pc_01", "args": None}, token)
        check("명령 보내기 200", st == 200, (st, got))
        st, got = api(base, "POST", "/api/accounts/kim", {"disabled": True}, token)
        check("계정 변경 200", st == 200, (st, got))
    finally:
        srv.shutdown()
        srv.server_close()
        runs.close()
        if web.login_log is not None:
            web.login_log.close()
    a, s, old = read(aud_log), read(srv_log), read(os.path.join(data, local_server.LOG_NAME))
    for what in ("웹 계정 추가  아이디=kim", "웹 보안 설정 변경", "PC 추가  번호=pc_01", "웹 계정 변경 (사용 중지)  아이디=kim",
                 "명령 보냄  종류=launch  PC=pc_01"):
        check(f"'{what}' 은 audit.log 에만", what in a and what not in s and what not in old, (a, s))
    check("로그인 줄은 server.log 에 (감사 기록이 아니다)", "웹 로그인  아이디=boss" in s and "웹 로그인  아이디=boss" not in a, s)
    check("audit.log·server.log 에 비밀번호 없음", BOSS_PW not in a + s and NEW_PW not in a + s)
    check("설정이 되어 있으면 자료 폴더의 옛 기록 파일에 쓰지 않는다", old == "", old)
    if POSIX:
        check("audit.log 는 0600", mode(aud_log) == 0o600, oct(mode(aud_log)))


def test_posix_lock():
    if not POSIX:
        print("  [건너뜀] 리눅스(WSL)에서만 - 윈도우는 icacls (test_settings_standalone 등)")
        return
    folder = os.path.join(TMP, "keys")
    os.makedirs(folder, mode=0o755)
    os.chmod(folder, 0o755)
    for name in ("accounts.json", "pcs.json", "phones.json"):
        p = os.path.join(folder, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write("{}")
        os.chmod(p, 0o644)
    n0 = len(SPAWNED)
    codes = local_server.ensure_keys(folder, lock=True) and local_server.lock_key_files(folder)
    spawned = SPAWNED[n0:]
    check("icacls·CREATE_NO_WINDOW 로 프로세스를 띄우지 않는다", not spawned, spawned)
    for name in ("agent.key", "relay.key", "accounts.json", "pcs.json", "phones.json"):
        p = os.path.join(folder, name)
        check(f"{name} 0600", mode(p) == 0o600, oct(mode(p)))
    check("폴더 0700", mode(folder) == 0o700, oct(mode(folder)))
    check("결과 목록에 실패(-1·0 아닌 값)가 없다", isinstance(codes, list) and all(c == 0 for c in codes), codes)
    # lan_ca._run 은 리눅스에서 creationflags 0 (그대로 - 확인만)
    import lan_ca
    n1 = len(SPAWNED)
    try:
        lan_ca._run(None, ["version"])
    except lan_ca.CaError:
        pass
    check("lan_ca._run 은 creationflags 0", all(s[1] == 0 for s in SPAWNED[n1:]), SPAWNED[n1:])


def test_reuse_address():
    check("LocalServer.allow_reuse_address - posix 는 True, 윈도우는 False (남의 포트를 가로채지 않게)",
          local_server.LocalServer.allow_reuse_address is (os.name != "nt"), local_server.LocalServer.allow_reuse_address)
    if not POSIX:
        print("  [건너뜀] 같은 포트 다시 열기는 리눅스(WSL)에서만")
        return
    folder = os.path.join(TMP, "reuse")
    os.makedirs(folder)
    store = local_server.Store(os.path.join(folder, "store.json"), volatile=local_server.VOLATILE)
    runs = local_server.Runs(os.path.join(folder, "runs.db"))
    keys = local_server.ensure_keys(folder, lock=False)
    srv = local_server.make_server(store, runs, LIC, keys, port=0, folder=folder)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    for _ in range(3):           # 서버가 먼저 닫는 연결 (Connection: close) → 서버 쪽 포트에 TIME_WAIT 가 남는다
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("GET", "/db/x", headers={"Connection": "close"})
        r = c.getresponse()
        r.read()
        time.sleep(0.2)          # 서버의 FIN 을 먼저 받고 닫는다
        c.close()
    tw = subprocess.run(["ss", "-tan", "state", "time-wait", f"( sport = :{port} )"], capture_output=True, text=True)
    check("서버 쪽 포트에 TIME_WAIT 가 있다 (시험이 헛돌지 않게)", f":{port} " in tw.stdout, tw.stdout[-300:])
    srv.shutdown()
    srv.server_close()
    again = None
    try:
        again = local_server.make_server(store, runs, LIC, keys, port=port, folder=folder)
        check(f"닫고 곧바로 같은 포트({port}) 다시 열기", again.server_address[1] == port)
    except OSError as e:
        check(f"닫고 곧바로 같은 포트({port}) 다시 열기", False, f"{type(e).__name__}: {e}")
    finally:
        if again is not None:
            again.server_close()
        runs.close()


try:
    print("돌려 쓰는 기록 파일·리눅스 갈래 (test_server_log)")
    guard("test_rotate", test_rotate)
    guard("test_routes", test_routes)
    guard("test_web_audit", test_web_audit)
    guard("test_posix_lock", test_posix_lock)
    guard("test_reuse_address", test_reuse_address)
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n실패: {len(fails)}" + (f" ({', '.join(fails)})" if fails else ""))
sys.exit(1 if fails else 0)
