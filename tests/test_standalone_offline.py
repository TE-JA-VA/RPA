# -*- coding: utf-8 -*-
"""스탠드얼론은 바깥에 연결하지 않는다 (계획 ③ Task 2, 설계 2026-11-23-standalone 6.6·8절).

① 스탠드얼론 설치본에 실리는 우리 코드·웹 파일(build_release.standalone_materials)에 바깥 주소 글자(BLOCKED)가 없다.
② 하위 프로세스(빈 server_info, ai_rescue 없음)에서 우리 모듈을 불러오고 로컬 서버+에이전트를 10초 돌리고 감독(background.run)을
   켜도 연결 대상은 이 PC 안(127.0.0.1·localhost)뿐이고 powershell 을 띄우지 않는다. AI 가 없으면 끈다.
③ 일반 버전의 주소는 글자 하나 바뀌지 않는다.
--release <배포 폴더> 면 만든 폴더의 바이트를 본다 (Task 6 - 우리 파일·조각, lib.zip 에 anthropic/ 없음).

    D:/AX/RPA/.venv/Scripts/python.exe tests/test_standalone_offline.py [--release D:\\AX\\배포_SA_TEST_<v>]
"""
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import types
import zipfile

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLOCKED = ("googleapis.com", "gstatic.com", "firebaseio.com", "firebasedatabase.app", "firebaseapp.com", ".web.app", "anthropic",
           "jsdelivr", "rpa-test-f02e0", "AIzaSy")
LOCAL = {"127.0.0.1", "localhost"}


def find_blocked(materials):
    """[(자리, 바이트)] 에서 BLOCKED 글자가 든 곳 [(자리, 글자, 앞뒤 글)] (대소문자 무시)."""
    hits = []
    for rel, data in materials:
        low = data.lower()
        for word in BLOCKED:
            at = low.find(word.lower().encode("utf-8"))
            if at >= 0:
                hits.append((rel, word, data[max(0, at - 40):at + 40].decode("utf-8", "replace").replace("\n", " ")))
    return hits


# ---------------------------------------------------------------------------------------------
# 하위 프로세스 (②) - 이 파일을 --child <임시 폴더> 로 다시 띄운다
# ---------------------------------------------------------------------------------------------
def child(tmp):
    sys.path.insert(0, ROOT)
    sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    pd = os.path.join(tmp, "pd")
    for d in ("config", "standalone", "status"):
        os.makedirs(os.path.join(pd, d), exist_ok=True)
    cfg_path = os.path.join(tmp, "RPA_UserConfig.json")
    with open(cfg_path, "w", encoding="utf-8") as f:              # 빈 사용자 설정 - 옛 설정 파일을 찾아가지 않게
        json.dump({"Sites": {}}, f)
    os.environ.update(RPA_PROGRAMDATA=pd, RPA_EDITION="standalone", RPA_MACHINE_GUID="p1",
                      RPA_STATUS_DIR=os.path.join(pd, "status"), RPA_AGENT_QUEUE=os.path.join(tmp, "queue.jsonl"),
                      RPA_USER_CONFIG=cfg_path, RPA_DASHBOARD_DRY_RUN="1", RPA_AGENT_MUTEX="RPA_AGENT_OFF_" + os.path.basename(tmp))
    for k in ("FIREBASE_AUTH_EMULATOR_HOST", "FIRESTORE_EMULATOR_HOST", "RPA_UPDATE_BASE_URL"):
        os.environ.pop(k, None)
    sys.stdin = io.StringIO("")

    import build_release as br                    # 빈 server_info 를 만든다 (빌드가 싣는 것과 같은 글)
    with open(os.path.join(ROOT, "server_info.py"), encoding="utf-8") as f:
        blank = br.blank_server_info(f.read())
    mod = types.ModuleType("server_info")
    exec(blank, mod.__dict__)
    sys.modules["server_info"] = mod
    sys.modules["ai_rescue"] = None               # 스탠드얼론에는 ai_rescue 조각이 없다
    for name in [n for n in sys.modules if n in ("background", "rpa_update", "secret", "fb", "agent")]:
        del sys.modules[name]                     # build_release 가 진짜 server_info 로 불러 둔 것은 버린다

    targets, procs = [], []
    real_connect, real_connect_ex, real_create, real_gai = (socket.socket.connect, socket.socket.connect_ex, socket.create_connection,
                                                            socket.getaddrinfo)

    def note(addr):
        try:
            targets.append(str(addr[0]))
        except Exception:
            targets.append(repr(addr))

    def wrap(fn):
        def inner(self, addr, *a, **k):
            note(addr)
            return fn(self, addr, *a, **k)
        return inner

    def create(addr, *a, **k):
        note(addr)
        return real_create(addr, *a, **k)

    def gai(host, *a, **k):
        targets.append(str(host))
        return real_gai(host, *a, **k)
    socket.socket.connect, socket.socket.connect_ex, socket.create_connection, socket.getaddrinfo = wrap(real_connect), wrap(real_connect_ex), create, gai

    real_popen, real_run = subprocess.Popen, subprocess.run

    class Popen(real_popen):
        def __init__(self, args, *a, **k):
            procs.append(args if isinstance(args, str) else " ".join(map(str, args)))
            super().__init__(args, *a, **k)

    def run(args, *a, **k):
        procs.append(args if isinstance(args, str) else " ".join(map(str, args)))
        return real_run(args, *a, **k)
    subprocess.Popen, subprocess.run = Popen, run

    out = {"imports": [], "errors": []}
    for name in ("agent", "background", "secret", "rpa_update", "rpa_settings", "local_server", "local_web", "otp_relay",
                 "web_replay", "web_runner"):
        try:
            __import__(name)
            out["imports"].append(name)
        except Exception as e:
            out["errors"].append(f"{name}: {type(e).__name__}: {e}")
    import agent
    import background
    import fb
    import license_check
    import local_server
    import rpa_update
    import secret
    import update_sign
    import web_replay
    import web_runner

    # 서버 + 에이전트 10초 (계획 ① e2e 와 같은 구성)
    lic_secret, lic_public = update_sign.keygen()
    license_check.LICENSE_PUBLIC_KEY_HEX = lic_public.hex()
    body = {"edition": "standalone", "company": "시험상사", "cid": "c1", "pc_id": "p1", "issued": "2026-11-23",
            "modules": {}, "features": {}, "limits": {}}
    with open(os.path.join(pd, "license.json"), "w", encoding="utf-8") as f:
        json.dump(license_check.sign_body(lic_secret, body), f, ensure_ascii=False)
    folder = local_server.data_dir()
    store = local_server.Store(os.path.join(folder, "store.json"), volatile=local_server.VOLATILE)
    runs = local_server.Runs(os.path.join(folder, "runs.db"))
    keys = local_server.ensure_keys(folder)
    srv = local_server.make_server(store, runs, license_check.load(), keys, port=0, folder=folder)
    os.environ["RPA_LOCAL_PORT"] = str(srv.server_address[1])
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    threading.Thread(target=lambda: agent.run(secret.load_config()), daemon=True, name="agent").start()
    end = time.time() + 10
    beat = False
    while time.time() < end:
        beat = beat or isinstance((store.get("apps/rpa/live/c1/p1/heartbeat") or {}).get("at"), int)
        time.sleep(0.2)
    out["heartbeat"] = beat

    # 감독: 가짜 main 으로 run() - 인증서 채우기(powershell)를 하지 않는다
    called = []
    background.main = lambda *a, **k: called.append(1) or 0
    out["bg_run"] = background.run()
    out["bg_main_called"] = bool(called)
    out["warm_urls"] = list(background.ROOT_WARM_URLS)
    ran = []
    background.warm_windows_roots(urls=(), run=lambda *a, **k: ran.append(a))
    out["warm_empty_ran"] = bool(ran)
    out["update_urls"] = list(rpa_update.update_urls())
    try:
        rpa_update.fetch_release("2026.01.01-1", tmp, os.path.join(tmp, "staging"), get=lambda url: (_ for _ in ()).throw(AssertionError(url)))
        out["fetch"] = "통과함"
    except rpa_update.UpdateError as e:
        out["fetch"] = str(e)
    try:
        fb.Client({"database_url": "https://x", "project_id": "p", "api_key": "k"})
        out["fb"] = "만들어짐"
    except RuntimeError as e:
        out["fb"] = str(e)

    # AI 가 없으면 끈다
    out["wr_ai"] = repr(web_replay.ai)
    out["runner_ai"] = repr(web_runner.ai_rescue)
    rp = web_replay.Replayer(None, {"steps": [{"kind": "click", "target": {"text": "a"}}]}, {}, tmp, "C", log=lambda m: None)
    cap = io.StringIO()
    real_stdout, sys.stdout = sys.stdout, cap
    try:
        rp.ai = "켜 둔 것처럼"
        web_runner.attach_ai(rp, "시험")
        out["attach"] = repr(rp.ai)
        out["ai_ok"] = rp._ai_ok(0, rp.rec["steps"][0])
        web_runner.cmd_check()
    finally:
        sys.stdout = real_stdout
    out["check"] = cap.getvalue()

    out["targets"] = sorted(set(targets))
    out["procs"] = procs
    srv.shutdown()
    with open(os.path.join(tmp, "child.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    sys.stdout.flush()
    os._exit(0)


# ---------------------------------------------------------------------------------------------
# 만든 배포 폴더 (Task 6)
# ---------------------------------------------------------------------------------------------
def release_materials(folder):
    """배포 폴더의 우리 파일 바이트 [(자리, 바이트)] - 내장 파이썬·node.exe·lib.zip 은 빼고, lib.zip 은 목록만 따로 본다."""
    out = []
    for base, dirs, files in os.walk(folder):
        rel_base = os.path.relpath(base, folder).replace(os.sep, "/")
        if rel_base.split("/")[0] in ("python", "lib", "playwright"):
            continue
        for name in files:
            rel = f"{rel_base}/{name}".lstrip("./")
            if rel in ("lib.zip",):
                continue
            with open(os.path.join(base, name), "rb") as f:
                out.append((rel, f.read()))
    return out


def main():
    sys.path.insert(0, ROOT)
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    fails = []

    def check(name, ok, detail=""):
        print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
        if not ok:
            fails.append(name)

    if "--release" in sys.argv:
        folder = sys.argv[sys.argv.index("--release") + 1]
        print(f"만든 배포 폴더 {folder}")
        hits = find_blocked(release_materials(folder))
        check("우리 파일·조각에 바깥 주소 글자가 없다", not hits, "\n      " + "\n      ".join(map(str, hits[:30])))
        with zipfile.ZipFile(os.path.join(folder, "lib.zip")) as z:
            bad = [n for n in z.namelist() if n.split("/")[0].lower().startswith("anthropic")]
        check("lib.zip 에 anthropic/ 이 없다", not bad, str(bad[:5]))
        print(f"\n실패: {len(fails)}" + (f" ({', '.join(fails)})" if fails else ""))
        return 1 if fails else 0

    import build_release as br
    import server_info

    print("① 실리는 우리 코드·웹 파일에 바깥 주소 글자가 없다")
    mats = br.standalone_materials()
    rels = {r for r, _ in mats}
    hits = find_blocked(mats)
    check(f"스탠드얼론 재료 {len(mats)}개에 BLOCKED 글자가 없다", not hits, "\n      " + "\n      ".join(map(str, hits[:30])))
    check("재료에 우리 코드·조각 원본·웹 파일이 든다 (빈 server_info, ai_rescue 없음)",
          {"server_info.py", "firebase/agent/fb.py", "firebase/agent/background.py", "web_replay.py", "firebase/web/index.html"} <= rels
          and "ai_rescue.py" not in rels and not any(r.startswith(".venv") or r.startswith("python/") for r in rels), str(sorted(rels)[:20]))
    real = [("server_info.py", open(os.path.join(ROOT, "server_info.py"), "rb").read()),
            ("ai_rescue.py", open(os.path.join(ROOT, "ai_rescue.py"), "rb").read())]
    got = {r for r, _, _ in find_blocked(real)}
    check("견줌: 진짜 server_info.py·ai_rescue.py 는 걸린다 (찾는 도구가 돈다)", got == {"server_info.py", "ai_rescue.py"}, str(got))

    print("② 하위 프로세스: 불러오기·서버+에이전트 10초·감독 - 이 PC 밖 연결 없음")
    tmp = tempfile.mkdtemp(prefix="rpa_offline_")
    try:
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "--child", tmp], capture_output=True, timeout=180,
                           env=dict(os.environ, PYTHONUTF8="1"))
        path = os.path.join(tmp, "child.json")
        res = json.load(open(path, encoding="utf-8")) if os.path.isfile(path) else {}
        if not res:
            print((r.stdout + r.stderr).decode("utf-8", "replace")[-3000:])
        check("모듈 열 개를 예외 없이 불러온다", len(res.get("imports") or []) == 10 and not res.get("errors"), str(res.get("errors")))
        check("에이전트가 로컬 서버로 살아 있다는 신호를 올렸다 (시험이 살아 있다)", res.get("heartbeat") is True)
        tg = set(res.get("targets") or [])
        check("연결·주소 찾기 대상은 이 PC 안뿐", tg and tg <= LOCAL, str(sorted(tg)))
        check("powershell 을 띄운 적 없다", not any("powershell" in p.lower() for p in res.get("procs") or []), str(res.get("procs")))
        check("감독 run() 은 인증서 채우기 없이 main 으로", res.get("bg_main_called") is True and res.get("bg_run") == 0)
        check("빈 server_info: ROOT_WARM_URLS 는 빈 튜플, urls=() 면 run 을 부르지 않는다",
              res.get("warm_urls") == [] and res.get("warm_empty_ran") is False, str(res.get("warm_urls")))
        check("빈 server_info: update_urls() == (), fetch_release 는 새 설치 파일 안내",
              res.get("update_urls") == [] and res.get("fetch") == "스탠드얼론 버전은 새 설치 파일로 업데이트합니다.", str(res.get("fetch")))
        check("빈 server_info: fb.Client 는 RuntimeError", res.get("fb") == "스탠드얼론 버전에서는 Firebase 에 연결하지 않습니다.", str(res.get("fb")))
        check("ai_rescue 가 없으면 web_replay.ai·web_runner.ai_rescue 가 None", res.get("wr_ai") == "None" and res.get("runner_ai") == "None")
        check("그때 ACTOR 는 재생기에 AI 를 붙이지 않고 (rp.ai = None), _ai_ok 는 False", res.get("attach") == "None" and res.get("ai_ok") is False,
              f"{res.get('attach')} {res.get('ai_ok')}")
        check("--check 에 'AI 어시스트: 이 버전에는 없습니다' 한 줄 (끝 줄까지 간다)",
              (res.get("check") or "").count("AI 어시스트: 이 버전에는 없습니다") == 1 and "쓸 수 있는 Action" in (res.get("check") or ""),
              (res.get("check") or "")[-600:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("③ 일반 버전의 주소는 그대로")
    for k in ("FIREBASE_AUTH_EMULATOR_HOST", "FIRESTORE_EMULATOR_HOST"):
        os.environ.pop(k, None)
    sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
    import background
    import fb
    import rpa_update
    want = ("https://identitytoolkit.googleapis.com/", "https://securetoken.googleapis.com/", "https://firestore.googleapis.com/",
            server_info.DATABASE_URL + "/.json", server_info.UPDATE_BASE_URL.rstrip("/") + "/")
    check("ROOT_WARM_URLS 가 고치기 전과 같은 다섯", background.ROOT_WARM_URLS == want, str(background.ROOT_WARM_URLS))
    check("server_info 의 새 주소 셋", (server_info.AUTH_HOST, server_info.TOKEN_HOST, server_info.FIRESTORE_HOST)
          == ("identitytoolkit.googleapis.com", "securetoken.googleapis.com", "firestore.googleapis.com"))
    c = fb.Client({"database_url": server_info.DATABASE_URL, "project_id": "p", "api_key": "k"})
    check("fb 의 주소 함수 셋이 지금과 같은 글",
          (fb._auth_host(), fb._token_host(), c._fs_base())
          == ("https://identitytoolkit.googleapis.com", "https://securetoken.googleapis.com",
              "https://firestore.googleapis.com/v1/projects/p/databases/(default)/documents"),
          str((fb._auth_host(), fb._token_host(), c._fs_base())))
    check("업데이트 주소는 그대로", rpa_update.update_urls()[0] == server_info.UPDATE_BASE_URL or os.environ.get("RPA_UPDATE_BASE_URL"))

    print(f"\n실패: {len(fails)}" + (f" ({', '.join(fails)})" if fails else ""))
    return 1 if fails else 0


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--child":
        child(sys.argv[2])
    sys.exit(main())
