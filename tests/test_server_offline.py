# -*- coding: utf-8 -*-
"""사내 서버 ④ Task 7 - 서버 설치 파일은 바깥에 연결하지 않는다 (설계 8절 ①, 계획 2026-11-25-lan-4-linux Task 7).
tools/build_server.py 로 만든 묶음(가짜 내장 파이썬, 시험 열쇠)의 app/·web/ 에
  ① Firebase·Google·Anthropic·우리 사이트 주소 글(tests/test_standalone_offline.BLOCKED - 일반 버전 server_info 의 실제 값 포함)이 없고
  ② app/ 의 모듈이 바깥으로 연결하는 라이브러리(urllib.request·http.client·smtplib·ftplib)를 import 하지 않으며,
     이름 풀이·연결 함수(socket.create_connection·getaddrinfo·gethostbyname)를 부르지 않는다.
  ③ app/ 만 두고 server_main 을 불러온 프로세스에 urllib.request·smtplib·ftplib 와 PC 쪽 클라이언트 모듈이 없다.
(http.server 는 표준 라이브러리 안에서 http.client 를 불러온다 - 그래서 ③ 은 http.client 를 보지 않고 ② 가 우리 코드를 본다.)
    D:/AX/RPA/.venv/Scripts/python.exe tests/test_server_offline.py
"""
import ast
import contextlib
import importlib.util
import io
import os
import shutil
import sys
import tarfile
import tempfile
import traceback

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
POSIX = os.name == "posix"

import update_sign  # noqa: E402

fails = []
try:
    import build_server  # noqa: E402
    import test_build_server as tbs  # noqa: E402  가짜 런타임·가짜 server/·import 확인을 같이 쓴다
except ImportError as e:
    print(f"  [실패] tools/build_server.py 를 불러오지 못한다 - {e}")
    print("\n실패: 1")
    sys.exit(1)


def _offline_words():
    spec = importlib.util.spec_from_file_location("_sa_offline", os.path.join(ROOT, "tests", "test_standalone_offline.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.BLOCKED, mod.find_blocked


BLOCKED, find_blocked = _offline_words()
NET_MODULES = ("urllib.request", "http.client", "smtplib", "ftplib")
NET_CALLS = ("create_connection", "getaddrinfo", "gethostbyname", "gethostbyname_ex", "urlopen")
TMP = tempfile.mkdtemp(prefix="rpa_server_offline_", dir="/tmp" if POSIX else None)


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def bundle_files():
    secret, public = update_sign.keygen()
    key = os.path.join(TMP, "key.txt")
    with open(key, "w", encoding="ascii") as f:
        f.write(secret.hex() + "\n")
    rt, pin = tbs.fake_runtime(os.path.join(TMP, "rt"))
    with contextlib.redirect_stdout(io.StringIO()):
        path, _ = build_server.build("2026.11.25-7", rt, key, os.path.join(TMP, "out"), test_key=True, pin=pin,
                                     server_dir=tbs.fake_server_dir(os.path.join(TMP, "server")))
    out = []
    with tarfile.open(path, "r:gz") as tf:
        for m in tf.getmembers():
            if m.isfile():
                rel = m.name.split("/", 1)[1]
                if rel.startswith(("app/", "web/")):
                    out.append((rel, tf.extractfile(m).read()))
    return path, out


def net_imports(rel, text):
    """우리 모듈 글에서 바깥 연결 import·호출 [(자리, 줄, 무엇)]."""
    hits = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            for a in node.names:
                if any(a.name == m or a.name.startswith(m + ".") for m in NET_MODULES):
                    hits.append((rel, node.lineno, "import " + a.name))
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            full = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            for name in full:
                if any(name == m or name.startswith(m + ".") for m in NET_MODULES):
                    hits.append((rel, node.lineno, f"from {node.module} import ..."))
                    break
        elif isinstance(node, ast.Attribute) and node.attr in NET_CALLS:
            hits.append((rel, node.lineno, "." + node.attr))
        elif isinstance(node, ast.Name) and node.id in NET_CALLS:
            hits.append((rel, node.lineno, node.id))
    return hits


def source_imports(rel):
    """저장소 파일의 import 첫 이름 집합 (맨 위·함수 안 모두)."""
    with open(os.path.join(ROOT, *rel.split("/")), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.add(node.module.split(".")[0])
    return out


SIGN_NAMES = ("H_ROLE", "H_TIME", "H_NONCE", "H_SIGN", "H_PC", "ROLES", "request_mac", "request_mac2", "response_mac", "event_mac")


def _same_macs(ap_sign):
    """서명 값이 옛 계산식(hmac-sha256, 줄바꿈으로 이은 글)과 같은가 - 직접 계산해 견준다."""
    import hashlib
    import hmac
    body, n = b"body", "n" * 16

    def mac(parts):
        return hmac.new(b"k", "\n".join(parts).encode("utf-8"), hashlib.sha256).hexdigest()
    d = hashlib.sha256(body).hexdigest()
    return (ap_sign.request_mac("k", "agent", "GET", "/x", "1", n, body) == mac(["ap1", "req", "agent", "GET", "/x", "1", n, d])
            and ap_sign.request_mac("k", "agent", "GET", "/x", "1", n, b"", digest=d) == mac(["ap1", "req", "agent", "GET", "/x", "1", n, d])
            and ap_sign.request_mac2("k", "pc_01", "agent", "GET", "/x", "1", n, body)
            == mac(["ap2", "req", "pc_01", "agent", "GET", "/x", "1", n, d])
            and ap_sign.response_mac("k", n, 200, body) == mac(["ap1", "res", n, "200", d])
            and ap_sign.event_mac("k", n, 3, "put", "raw") == mac(["ap1", "sse", n, "3", "put", "raw"])
            and (ap_sign.H_ROLE, ap_sign.H_TIME, ap_sign.H_NONCE, ap_sign.H_SIGN, ap_sign.H_PC, ap_sign.ROLES)
            == ("X-AP-Role", "X-AP-Time", "X-AP-Nonce", "X-AP-Sign", "X-AP-PC", ("agent", "relay")))


def test_sign_split():
    """서명 함수는 ap_sign (표준 라이브러리만) - 서버(local_server)가 PC 클라이언트 local_store 를 불러오지 않는다."""
    print("⓪ 서명 모듈 나누기")
    got = source_imports("firebase/agent/local_server.py")
    check("local_server 가 local_store·fb·server_info 를 import 하지 않는다", not got & {"local_store", "fb", "server_info"},
          str(got & {"local_store", "fb", "server_info"}))
    check("local_server 가 ap_sign 을 import 한다", "ap_sign" in got)
    try:
        sign_imports = source_imports("firebase/agent/ap_sign.py")
    except OSError:
        sign_imports = None
    check("ap_sign 은 hashlib·hmac 만 import 한다", sign_imports is not None and sign_imports <= {"hashlib", "hmac"}, str(sign_imports))
    try:
        import ap_sign
        import local_store
    except ImportError as e:
        check("ap_sign·local_store 를 불러온다", False, str(e))
        return
    check("local_store 는 ap_sign 의 같은 이름을 그대로 내보낸다",
          all(getattr(local_store, n, None) is getattr(ap_sign, n) for n in SIGN_NAMES))
    check("서명 값·머리글 이름이 고치기 전 계산식과 같다", _same_macs(ap_sign))


def main():
    try:
        test_sign_split()
        print("묶음 만들기 (가짜 내장 파이썬·시험 열쇠)")
        path, files = bundle_files()
        app = [(r, d) for r, d in files if r.startswith("app/")]
        web = [(r, d) for r, d in files if r.startswith("web/")]
        check("app/·web/ 에 파일이 있다", len(app) >= 5 and len(web) >= 5, f"{len(app)} {len(web)}")

        print("① 바깥 주소 글")
        hits = find_blocked(files)
        check("app/·web/ 에 Firebase·Google·Anthropic·우리 사이트 주소 글이 없다", not hits,
              "; ".join(f"{r}: {w} …{ctx}…" for r, w, ctx in hits[:6]))
        check("막는 글 목록에 일반 버전 server_info 의 값이 들어 있다", "rpa-test-f02e0" in BLOCKED and "googleapis.com" in BLOCKED)

        print("② app/ 의 import 와 연결 함수")
        found = []
        for rel, data in app:
            found += net_imports(rel, data.decode("utf-8"))
        check("app/ 모듈이 urllib.request·http.client·smtplib·ftplib 를 import 하지 않고 연결·이름 풀이 함수를 부르지 않는다",
              not found, "; ".join(f"{r}:{n} {w}" for r, n, w in found[:8]))
        probe = net_imports("probe.py", "import urllib.request\nfrom http import client\nimport socket\nsocket.create_connection(('a', 1))\n")
        check("검사 자체가 잡는다 (import 둘·호출 하나)", len(probe) == 3, str(probe))

        print("③ 불러온 뒤 프로세스의 모듈")
        dest = os.path.join(TMP, "unpacked")
        with tarfile.open(path, "r:gz") as tf:
            tf.extractall(dest, filter="data")
        top = os.path.join(dest, os.listdir(dest)[0])
        ok, out = tbs.import_check(sys.executable, os.path.join(top, "app"))
        check("app/ 만 두고 import server_main - urllib.request·smtplib·ftplib·클라이언트 모듈 없음", ok, out[-600:])
    except Exception:
        traceback.print_exc()
        check("예외 없이 끝", False)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
        try:
            shutil.rmtree(tbs.TMP, ignore_errors=True)        # test_build_server 를 불러오며 만든 임시 폴더
        except Exception:
            pass
    print(f"\n실패: {len(fails)}" + (f" ({', '.join(fails)})" if fails else ""))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
