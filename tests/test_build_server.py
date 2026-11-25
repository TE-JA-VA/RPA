# -*- coding: utf-8 -*-
"""사내 서버 ④ Task 7 - 서버 설치 파일 만들기 (계획 2026-11-25-lan-4-linux Task 7, 설계 6.2·8절).
tools/build_server.py 가 만든 AUTOPILOT_Server_<V>_linux-x86_64.tar.gz 의 꼴·지문·서명, 내장 파이썬 지문 고정,
SERVER_FILES(서버 모듈만 - server_main 에서 import 를 따라가 정한 목록)를 본다. 내장 파이썬은 가짜(작은 tar.gz), 서명은
그 자리에서 만든 시험 열쇠만 쓴다. 윈도우·WSL 둘 다 (WSL 의 임시 폴더는 /tmp 아래).
    D:/AX/RPA/.venv/Scripts/python.exe tests/test_build_server.py
    wsl.exe -d Ubuntu -e python3 /mnt/d/AX/RPA_StandAlone/tests/test_build_server.py
진짜 내장 파이썬으로 만든 묶음을 그 안의 파이썬으로 확인 (WSL, 한 번씩 손으로):
    wsl.exe -d Ubuntu -e python3 /mnt/d/AX/RPA_StandAlone/tests/test_build_server.py --real-bundle /tmp/.../AUTOPILOT_Server_<V>_linux-x86_64.tar.gz
"""
import ast
import contextlib
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import traceback

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
POSIX = os.name == "posix"

import update_sign  # noqa: E402

fails = []
try:
    import build_server  # noqa: E402
except ImportError as e:
    print(f"  [실패] tools/build_server.py 를 불러오지 못한다 - {e}")
    print("\n실패: 1")
    sys.exit(1)

TMP = tempfile.mkdtemp(prefix="rpa_build_server_", dir="/tmp" if POSIX else None)
SECRET, PUBLIC = update_sign.keygen()                      # 시험 업데이트 서명 열쇠 (진짜 열쇠 파일은 열지 않는다)
KEY_PATH = os.path.join(TMP, "test_sign_key.txt")
with open(KEY_PATH, "w", encoding="ascii") as f:
    f.write(SECRET.hex() + "\n")
VER = "2026.11.25-7"
TOP = f"autopilot-server-{VER}"
# 서버 묶음에 들어가면 안 되는 PC 쪽 코드 (에이전트·ACTOR·옵저버·Firebase 클라이언트·감독·설정 창)
CLIENT_FILES = ("agent.py", "background.py", "fb.py", "local_store.py", "local_phone.py", "local_cert.py", "secret.py",
                "server_info.py", "rpa_status.py", "edition.py", "rpa_update.py", "ap_guard.py", "update_helper.py")
CLIENT_PREFIXES = ("web_runner", "web_record", "observer", "actor", "ai_rescue", "rpa_settings", "agent")


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def sha(data):
    return hashlib.sha256(data).hexdigest()


RT_MTIME = 1700000000                                      # 가짜 런타임 파일의 시각 - 묶음에서도 그대로여야 한다


def fake_runtime(folder, broken=False):
    """가짜 내장 파이썬 tar.gz (python/ 아래 실행 글·링크·글 파일) 와 그 고정 값 {file, sha256, url}."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "cpython-3.14.0+00000000-x86_64-unknown-linux-gnu-install_only.tar.gz")
    with tarfile.open(path, "w:gz") as tf:
        def put(name, data, mode=0o644):
            ti = tarfile.TarInfo(name)
            ti.size, ti.mode, ti.mtime = len(data), mode, RT_MTIME
            tf.addfile(ti, io.BytesIO(data))
        put("python/bin/python3.14", b"#!/bin/sh\necho fake-python\n", 0o755)
        ln = tarfile.TarInfo("python/bin/python3")
        ln.type, ln.linkname = tarfile.SYMTYPE, "python3.14"
        tf.addfile(ln)
        put("python/lib/python3.14/os.py", b"# fake\n")
        if broken:                                         # 묶음 밖을 가리키는 링크
            bad = tarfile.TarInfo("python/lib/escape")
            bad.type, bad.linkname = tarfile.SYMTYPE, "../../../etc/passwd"
            tf.addfile(bad)
    with open(path, "rb") as f:
        digest = sha(f.read())
    return path, {"file": os.path.basename(path), "sha256": digest, "url": "https://example.invalid/fake.tar.gz"}


def fake_server_dir(folder):
    """Task 8 이 만들 server/ 의 가짜 (install.sh·autopilot-server 는 실행 글, 단위 파일 하나)."""
    os.makedirs(folder, exist_ok=True)
    for name, text in (("install.sh", "#!/bin/sh\necho fake install\n"), ("autopilot-server", "#!/bin/sh\necho fake\n"),
                       ("autopilot.service", "[Unit]\nDescription=fake\n")):
        with open(os.path.join(folder, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    return folder


RT_PATH, RT_PIN = fake_runtime(os.path.join(TMP, "rt"))
SERVER_DIR = fake_server_dir(os.path.join(TMP, "server_src"))


def make(tag, **kw):
    out = os.path.join(TMP, "out_" + tag)
    args = dict(version=VER, runtime=RT_PATH, sign_key=KEY_PATH, out_dir=out, test_key=True, pin=RT_PIN, server_dir=SERVER_DIR)
    args.update(kw)
    with contextlib.redirect_stdout(io.StringIO()):
        return build_server.build(**args)


def members(path):
    with tarfile.open(path, "r:gz") as tf:
        out = {}
        for m in tf.getmembers():
            data = tf.extractfile(m).read() if m.isfile() else None
            out[m.name] = (m, data)
        return out


_BUNDLE = {}


def bundle():
    """시험 열쇠·가짜 런타임·가짜 server/ 로 만든 묶음 하나 (여러 시험이 같이 본다)."""
    if not _BUNDLE:
        _BUNDLE["paths"] = make("main")
    return _BUNDLE["paths"]


# ---------------------------------------------------------------------------------------------
def test_runtime_pin():
    with open(os.path.join(ROOT, "tools", "linux_runtime.json"), encoding="utf-8") as f:
        pin = json.load(f)
    check("linux_runtime.json 은 file·sha256·url 셋", set(pin) >= {"file", "sha256", "url"}, str(pin))
    check("내장 파이썬은 3.14 계열 x86_64 install_only", pin["file"].startswith("cpython-3.14.")
          and pin["file"].endswith("-x86_64-unknown-linux-gnu-install_only.tar.gz"), pin["file"])
    check("지문은 64자 16진수", len(pin["sha256"]) == 64 and all(c in "0123456789abcdef" for c in pin["sha256"]), pin["sha256"])
    check("주소는 python-build-standalone 릴리스",
          pin["url"].startswith("https://github.com/astral-sh/python-build-standalone/releases/download/"), pin["url"])
    check("build_server.load_pin 이 같은 값", build_server.load_pin() == pin)


def test_layout():
    path, sig = bundle()
    check("이름 AUTOPILOT_Server_<V>_linux-x86_64.tar.gz",
          os.path.basename(path) == f"AUTOPILOT_Server_{VER}_linux-x86_64.tar.gz" and sig == path + ".sig", path)
    got = members(path)
    names = list(got)
    check("맨 위 폴더 하나 autopilot-server-<V>/", {n.split("/", 1)[0] for n in names} == {TOP}, str(sorted(names)[:5]))
    check("절대 경로·'..'·역슬래시 없음", not any(n.startswith("/") or ".." in n.split("/") or "\\" in n for n in names))
    for sub in ("python", "app", "web", "server"):
        check(f"{sub}/ 가 있다", any(n.startswith(f"{TOP}/{sub}/") or n == f"{TOP}/{sub}" for n in names))
    check("소유자는 root(0)", all(m.uid == 0 and m.gid == 0 for m, _ in got.values()))
    check("특수 비트(setuid·setgid·sticky) 없음, 그룹·남 쓰기 없음",
          all(not (m.mode & 0o7022) for m, _ in got.values()), str([(n, oct(m.mode)) for n, (m, _) in got.items() if m.mode & 0o7022][:3]))
    check("링크·폴더·파일 말고 없음", all(m.isfile() or m.isdir() or m.issym() for m, _ in got.values()))
    man_m, man_raw = got.get(f"{TOP}/manifest.json", (None, None))
    check("manifest.json 이 있다", man_raw is not None)
    man = json.loads(man_raw.decode("utf-8"))
    check("manifest 의 version·edition·kind", (man.get("version"), man.get("edition"), man.get("kind")) == (VER, "standalone", "server"),
          str({k: man.get(k) for k in ("version", "edition", "kind")}))
    check("시험 열쇠 묶음은 test_build 참", man.get("test_build") is True)
    check("manifest 에 런타임 파일 이름·지문", man.get("runtime") == {"file": RT_PIN["file"], "sha256": RT_PIN["sha256"]}, str(man.get("runtime")))
    files = {n[len(TOP) + 1:]: d for n, (m, d) in got.items() if m.isfile()}
    listed = man.get("files") or {}
    want = {rel for rel in files if rel not in ("manifest.json", "manifest.sig")}
    check("manifest 의 files 가 묶음 안 파일과 정확히 같다", set(listed) == want,
          f"빠짐 {sorted(want - set(listed))[:5]} 더 있음 {sorted(set(listed) - want)[:5]}")
    bad = [rel for rel in want & set(listed) if listed[rel] != {"sha256": sha(files[rel]), "size": len(files[rel])}]
    check("파일마다 sha256·크기가 맞다", not bad, str(bad[:5]))
    links = {n[len(TOP) + 1:]: m.linkname for n, (m, _) in got.items() if m.issym()}
    check("링크는 manifest 의 links 에", man.get("links") == links and links.get("python/bin/python3") == "python3.14", str(man.get("links")))
    check("python/ 은 가짜 런타임 그대로", files.get("python/bin/python3.14") == b"#!/bin/sh\necho fake-python\n")
    app = sorted(rel[4:] for rel in files if rel.startswith("app/"))
    want_app = sorted(os.path.basename(p) for p in build_server.SERVER_FILES)
    check("app/ 는 SERVER_FILES 의 모듈 그대로 (하위 폴더 없음)", app == want_app, f"{app} != {want_app}")
    changed = []
    for p in build_server.SERVER_FILES:
        name = os.path.basename(p)
        if name in ("update_sign.py", "license_check.py"):   # 시험 열쇠를 끼운 사본 (test_signature)
            continue
        with open(os.path.join(ROOT, *p.split("/")), "rb") as f:
            if files.get("app/" + name) != f.read():
                changed.append(name)
    check("app/ 의 나머지 모듈은 원본 바이트 그대로", not changed, str(changed))
    web = sorted(rel[4:] for rel in files if rel.startswith("web/"))
    import local_web
    check("web/ 에 HIDDEN_FILES 없음", not set(web) & set(local_web.HIDDEN_FILES), str(set(web) & set(local_web.HIDDEN_FILES)))
    src = sorted(os.path.relpath(os.path.join(d, n), os.path.join(ROOT, "firebase", "web")).replace(os.sep, "/")
                 for d, ds, ns in os.walk(os.path.join(ROOT, "firebase", "web")) if "__pycache__" not in d for n in ns)
    check("web/ 는 firebase/web 에서 HIDDEN_FILES 를 뺀 것", web == [n for n in src if n not in local_web.HIDDEN_FILES],
          f"{len(web)} / {len(src)}")
    check("server/ 는 받은 폴더의 파일", sorted(rel[7:] for rel in files if rel.startswith("server/"))
          == ["autopilot-server", "autopilot.service", "install.sh"])
    modes = {n[len(TOP) + 1:]: stat.S_IMODE(m.mode) for n, (m, _) in got.items()}
    check("install.sh·autopilot-server 는 0755, 단위 파일·app 은 0644",
          (modes.get("server/install.sh"), modes.get("server/autopilot-server"), modes.get("server/autopilot.service"),
           modes.get("app/server_main.py")) == (0o755, 0o755, 0o644, 0o644),
          str([oct(modes.get(k) or 0) for k in ("server/install.sh", "server/autopilot-server", "server/autopilot.service", "app/server_main.py")]))
    check("런타임 실행 파일 모드 0755 유지", modes.get("python/bin/python3.14") == 0o755, oct(modes.get("python/bin/python3.14") or 0))
    times = {n[len(TOP) + 1:]: m.mtime for n, (m, _) in got.items()}
    check("런타임 파일은 원래 시각 그대로 (실린 .pyc 가 낡은 것으로 보이지 않게)",
          times.get("python/bin/python3.14") == RT_MTIME and times.get("python/lib/python3.14/os.py") == RT_MTIME
          and times.get("app/server_main.py") != RT_MTIME,
          (times.get("python/bin/python3.14"), times.get("python/lib/python3.14/os.py"), times.get("app/server_main.py")))
    check("폴더 항목은 0755", all(stat.S_IMODE(m.mode) == 0o755 for m, _ in got.values() if m.isdir()))
    check("manifest.sig 가 있고 files 에는 없다", f"{TOP}/manifest.sig" in got and "manifest.sig" not in listed)


def test_bad_inputs():
    for ver in ("../x", "", "a b", "x" * 70):
        try:
            make("badver", version=ver)
            check(f"버전 '{ver[:10]}' 거절", False, "만들어짐")
        except ValueError:
            check(f"버전 '{ver[:10]}' 거절", True)
    bad_rt, bad_pin = fake_runtime(os.path.join(TMP, "rt_bad"), broken=True)
    out = os.path.join(TMP, "out_badrt")
    try:
        make("badrt", runtime=bad_rt, pin=bad_pin)
        check("런타임 안 밖을 가리키는 링크면 멈춤", False, "만들어짐")
    except RuntimeError as e:
        check("런타임 안 밖을 가리키는 링크면 멈춤", "escape" in str(e), str(e))
    check("멈추면 결과 파일이 없다", not os.path.isdir(out) or not [n for n in os.listdir(out) if n.endswith((".tar.gz", ".sig"))],
          str(os.listdir(out) if os.path.isdir(out) else ""))


def test_runtime_hash_mismatch_stops():
    out = os.path.join(TMP, "out_mismatch")
    try:
        make("mismatch", pin=dict(RT_PIN, sha256="0" * 64))
        check("지문이 다르면 RuntimeError", False, "만들어짐")
    except RuntimeError as e:
        check("지문이 다르면 RuntimeError (사람 말)", "지문" in str(e), str(e))
    check("멈추면 결과 파일이 없다", not os.path.isdir(out) or not os.listdir(out), str(os.listdir(out) if os.path.isdir(out) else ""))
    out2 = os.path.join(TMP, "out_cli_mismatch")             # 명령 줄 - tools/linux_runtime.json 의 진짜 지문과 가짜 런타임
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = build_server.main(["--version", VER, "--runtime", RT_PATH, "--sign-key", KEY_PATH, "--out", out2, "--test-key",
                                "--server-dir", SERVER_DIR])
    check("명령 줄: 고정한 지문과 다른 런타임이면 1", rc == 1, f"{rc} {buf.getvalue()[-300:]}")
    check("명령 줄: 결과 파일 없음", not os.path.isdir(out2) or not os.listdir(out2))


def test_real_key_mismatch_stops():
    """--test-key 없이 실린 공개 열쇠(update_sign.PUBLIC_KEY_HEX)와 짝이 아닌 열쇠면 멈춘다 - 깔린 서버가 확인하지 못하는 묶음이 나온다."""
    out = os.path.join(TMP, "out_realkey")
    try:
        make("realkey", test_key=False)
        check("짝이 아닌 서명 열쇠면 멈춤", False, "만들어짐")
    except RuntimeError as e:
        check("짝이 아닌 서명 열쇠면 멈춤 (사람 말)", "짝" in str(e), str(e))
    check("멈추면 결과 파일이 없다", not os.path.isdir(out) or not os.listdir(out))


def test_signature():
    path, sig_path = bundle()
    with open(path, "rb") as f:
        raw = f.read()
    with open(sig_path, encoding="ascii") as f:
        sig_text = f.read()
    check(".sig 는 16진수 한 줄", sig_text.endswith("\n") and len(sig_text.strip()) == 128 and sig_text.count("\n") == 1, repr(sig_text[:20]))
    check(".sig 가 tar.gz 전체 바이트의 서명", update_sign.verify(PUBLIC, raw, bytes.fromhex(sig_text.strip())))
    flipped = bytearray(raw)
    flipped[len(raw) // 2] ^= 1
    check("한 바이트 바꾸면 .sig 가 맞지 않다", not update_sign.verify(PUBLIC, bytes(flipped), bytes.fromhex(sig_text.strip())))
    got = members(path)
    man_raw, msig = got[f"{TOP}/manifest.json"][1], got[f"{TOP}/manifest.sig"][1].decode("ascii")
    check("manifest.sig 가 manifest.json 바이트의 서명 (16진수 한 줄)",
          msig.count("\n") == 1 and update_sign.verify(PUBLIC, man_raw, bytes.fromhex(msig.strip())))
    us = got[f"{TOP}/app/update_sign.py"][1].decode("utf-8")
    lc = got[f"{TOP}/app/license_check.py"][1].decode("utf-8")
    check("시험 묶음의 update_sign 공개 열쇠는 시험 열쇠", f'PUBLIC_KEY_HEX = "{PUBLIC.hex()}"' in us)
    check("시험 묶음의 license_check 공개 열쇠도 시험 열쇠", f'LICENSE_PUBLIC_KEY_HEX = "{PUBLIC.hex()}"' in lc)
    try:                                                   # 같은 버전을 다시 만들면 내보낸 파일·지문을 덮지 않는다
        make("main")
        check("같은 자리에 같은 버전이 있으면 멈춤", False, "덮어씀")
    except RuntimeError as e:
        check("같은 자리에 같은 버전이 있으면 멈춤", "이미" in str(e), str(e))
    with open(path, "rb") as f:
        check("멈춰도 있던 파일은 그대로", f.read() == raw)


def test_server_main_verify():
    """Task 4 의 server_main.verify_bundle·'autopilot-server verify' 가 이 묶음을 받는다 (꼴이 정확히 맞는다)."""
    import server_main
    check("버전 꼴·맨 위 폴더 이름이 server_main 과 같다", (build_server.BUNDLE_VER_RE.pattern, build_server.BUNDLE_PREFIX)
          == (server_main.BUNDLE_VER_RE.pattern, server_main.BUNDLE_PREFIX))
    path, sig_path = bundle()
    old = server_main.UPDATE_PUBLIC_KEY
    server_main.UPDATE_PUBLIC_KEY = PUBLIC
    try:
        ver, raw = server_main.verify_bundle(path)
        check("verify_bundle → 버전", ver == VER, ver)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = server_main.main(["verify", path])
        check("autopilot-server verify 0 과 '서명 확인됨  버전=<V>'", rc == 0 and f"서명 확인됨  버전={VER}" in buf.getvalue(),
              f"{rc} {buf.getvalue()[-200:]}")
        other, _ = update_sign.keygen()
        server_main.UPDATE_PUBLIC_KEY = update_sign.secret_to_public(other)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc = server_main.main(["verify", path])
        check("다른 열쇠면 verify 1", rc == 1, str(rc))
    finally:
        server_main.UPDATE_PUBLIC_KEY = old


def test_server_files_closure():
    """SERVER_FILES 는 server_main 에서 import 를 따라간 것과 같다 - 새 import 가 생기면 여기서 잡힌다."""
    probs = build_server.server_files_problems()
    check("SERVER_FILES 와 import 를 따라간 모듈이 같고 클라이언트 모듈을 부르지 않는다", not probs, " / ".join(probs))
    check("SERVER_FILES 는 모두 있는 파일", all(os.path.isfile(os.path.join(ROOT, *p.split("/"))) for p in build_server.SERVER_FILES))
    check("server_main 이 첫째", build_server.SERVER_FILES[0] == "firebase/agent/server_main.py", build_server.SERVER_FILES[0])
    # 작은 가짜 모듈 셋으로 따라가기를 본다: a → b(맨 위), b → c(함수 안), b → skipme(함수 안, 건너뛰는 목록), c → client(맨 위)
    d = os.path.join(TMP, "mods")
    os.makedirs(d, exist_ok=True)
    for name, text in (("a", "import os\nimport b\n"), ("b", "def f():\n    import c\n    import skipme\n"),
                       ("c", "try:\n    import client\nexcept ImportError:\n    client = None\n"), ("skipme", ""), ("client", "")):
        with open(os.path.join(d, name + ".py"), "w", encoding="utf-8") as f:
            f.write(text)
    found, chain, top_skip = build_server.module_closure("a", [d], skip={"skipme"})
    check("따라가기: 맨 위·함수 안·try 안 import 모두", set(found) == {"a", "b", "c", "client"}, str(sorted(found)))
    check("따라가기: 표준 라이브러리(os)는 넣지 않는다", "os" not in found)
    check("따라가기: 사슬 a → b → c → client", build_server.chain_of(chain, "client") == ["a", "b", "c", "client"],
          str(build_server.chain_of(chain, "client")))
    with open(os.path.join(d, "a.py"), "w", encoding="utf-8") as f:
        f.write("import b\nimport skipme\n")
    found, chain, top_skip = build_server.module_closure("a", [d], skip={"skipme"})
    check("건너뛰는 모듈을 맨 위에서 부르면 알려 준다", top_skip == [("a", "skipme")], str(top_skip))
    with open(os.path.join(d, "a.py"), "w", encoding="utf-8") as f:     # 클래스 본문은 불러올 때 돈다 - 맨 위로 본다
        f.write("import b\nclass K:\n    import skipme\n    def m(self):\n        import os\n")
    found, chain, top_skip = build_server.module_closure("a", [d], skip={"skipme"})
    check("클래스 본문의 import 도 맨 위로 본다", top_skip == [("a", "skipme")], str(top_skip))


def test_no_client_code():
    path, _ = bundle()
    names = [n[len(TOP) + 1:] for n in members(path)]
    app = [n[4:] for n in names if n.startswith("app/") and n != "app/"]
    bad = [n for n in app if n in CLIENT_FILES or n.startswith(CLIENT_PREFIXES) or "/" in n.strip("/")]
    check("app/ 에 에이전트·ACTOR·옵저버·Firebase 클라이언트 파일 없음", not bad, str(bad))
    check("app/ 는 .py 만", all(n.endswith(".py") for n in app if n), str([n for n in app if not n.endswith(".py")]))
    top = {n.split("/", 1)[0] for n in names}
    check("맨 위에는 python·app·web·server·manifest 만", top <= {"", "python", "app", "web", "server", "manifest.json", "manifest.sig"},
          str(top))
    check("CLIENT_MODULES 와 SERVER_FILES 가 겹치지 않는다",
          not {os.path.basename(p)[:-3] for p in build_server.SERVER_FILES} & set(build_server.CLIENT_MODULES))


def test_server_dir_missing():
    """Task 8 전: server/ 폴더가 없으면 빈 server/ 자리만 두고 알린다."""
    out = os.path.join(TMP, "out_noserver")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        path, _ = build_server.build(VER, RT_PATH, KEY_PATH, out, test_key=True, pin=RT_PIN, server_dir=os.path.join(TMP, "none"))
    names = members(path)
    check("server/ 폴더 항목만 있다", f"{TOP}/server" in names and not [n for n in names if n.startswith(f"{TOP}/server/")],
          str([n for n in names if "server" in n.split("/")[1:2]]))
    check("install.sh 가 없다고 알린다", "install.sh" in buf.getvalue(), buf.getvalue()[-300:])


def test_server_dir_crlf_stops():
    """Task 8: server/ 의 글(install.sh·실행 글·단위 파일)에 CR 이 있으면 리눅스 sh·systemd 가 깨진다 - 만들기를 멈춘다.
    저장소 server/ 의 파일은 모두 LF (.gitattributes 로 고정)."""
    d = fake_server_dir(os.path.join(TMP, "server_crlf"))
    with open(os.path.join(d, "install.sh"), "wb") as f:
        f.write(b"#!/bin/sh\r\necho crlf\r\n")
    out = os.path.join(TMP, "out_crlf")
    try:
        make("crlf", server_dir=d, out_dir=out)
        check("server/ 글에 CR 이 있으면 멈춤", False, "만들어짐")
    except RuntimeError as e:
        check("server/ 글에 CR 이 있으면 멈춤 (파일 이름과 함께)", "install.sh" in str(e) and "CR" in str(e), str(e))
    check("멈추면 결과 파일이 없다", not os.path.isdir(out) or not os.listdir(out))
    repo_server = os.path.join(ROOT, "server")
    names = sorted(os.listdir(repo_server)) if os.path.isdir(repo_server) else []
    check("저장소 server/ 에 Task 8 파일이 모두 있다",
          set(names) >= {"install.sh", "autopilot-server", "autopilot.service", "autopilot-cert.service", "autopilot-cert.timer",
                         "autopilot-config-backup.service", "autopilot-config-backup.timer", "nginx-example.conf"}, names)
    crlf = []
    for n in names:
        with open(os.path.join(repo_server, n), "rb") as f:
            if b"\r" in f.read():
                crlf.append(n)
    check("저장소 server/ 의 파일은 모두 LF", not crlf, crlf)
    try:
        with open(os.path.join(ROOT, ".gitattributes"), encoding="utf-8") as f:
            attrs = f.read()
    except OSError:
        attrs = ""
    check(".gitattributes 가 server/ 를 eol=lf 로 고정", any(ln.split()[:1] == ["server/**"] and "eol=lf" in ln for ln in attrs.splitlines()),
          attrs)


def _extract(path, dest):
    with tarfile.open(path, "r:gz") as tf:
        tf.extractall(dest, filter="data")
    tops = os.listdir(dest)
    return os.path.join(dest, tops[0]) if len(tops) == 1 else dest


def test_server_imports_closed():
    """묶음을 풀고 app/ 만 sys.path 로 'import server_main' - 빠진 모듈이 있으면 ImportError. 클라이언트 모듈은 불려 오지 않는다.
    이 PC 의 파이썬으로 (WSL 에서는 리눅스 파이썬). 진짜 내장 파이썬은 --real-bundle 로."""
    path, _ = bundle()
    dest = os.path.join(TMP, "unpacked")
    top = _extract(path, dest)
    ok, out = import_check(sys.executable, os.path.join(top, "app"))
    check(f"{'리눅스' if POSIX else '윈도우'} 파이썬 -I 로 app/ 만 두고 import server_main", ok, out[-600:])


IMPORT_CODE = ("import sys; sys.path.insert(0, sys.argv[1]); import server_main, json; "
               "bad = sorted(m for m in sys.modules if m.split('.')[0] in {CLIENT} or m in ('urllib.request', 'smtplib', 'ftplib')); "
               "print(json.dumps({'ok': True, 'bad': bad, 'file': server_main.__file__, 'py': sys.version.split()[0]}))")


def import_check(python, app_dir):
    code = IMPORT_CODE.replace("{CLIENT}", repr(set(build_server.CLIENT_MODULES)))
    try:
        r = subprocess.run([python, "-I", "-c", code, app_dir], capture_output=True, timeout=120, cwd=os.path.dirname(app_dir))
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"{type(e).__name__}: {e}"
    out = r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")
    if r.returncode != 0:
        return False, out
    try:
        got = json.loads(r.stdout.decode("utf-8").strip().splitlines()[-1])
    except (ValueError, IndexError):
        return False, out
    inside = os.path.normcase(os.path.abspath(got["file"])).startswith(os.path.normcase(os.path.abspath(app_dir)))
    return got["ok"] and not got["bad"] and inside, out


def real_bundle(path):
    """진짜 내장 파이썬 묶음: 풀고 그 안의 python/bin/python3 -I 로 import server_main, 그리고 그 안의 server_main verify."""
    dest = tempfile.mkdtemp(prefix="rpa_real_bundle_", dir="/tmp" if POSIX else None)
    try:
        top = _extract(path, dest)
        py = os.path.join(top, "python", "bin", "python3")
        r = subprocess.run([py, "-I", "-c", "import sys, ssl, sqlite3; print(sys.version.split()[0], ssl.OPENSSL_VERSION, sqlite3.sqlite_version)"],
                           capture_output=True, timeout=60)
        print("  내장 파이썬:", (r.stdout or r.stderr).decode("utf-8", "replace").strip())
        ok, out = import_check(py, os.path.join(top, "app"))
        check("내장 파이썬 -I 로 app/ 만 두고 import server_main", ok, out[-600:])
        print("   ", out.strip()[-400:])
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import server_main; "
                "sys.exit(server_main.main(['verify', sys.argv[2]]))")
        r = subprocess.run([py, "-I", "-c", code, os.path.join(top, "app"), path], capture_output=True, timeout=120)
        out = (r.stdout + r.stderr).decode("utf-8", "replace").strip()
        check("묶음 안 server_main verify 가 이 묶음을 0 으로", r.returncode == 0 and "서명 확인됨" in out, out[-300:])
        print("   ", out[-300:])
        app = sorted(os.listdir(os.path.join(top, "app")))
        print("  app/:", " ".join(app))
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--real-bundle":
        print("진짜 내장 파이썬 묶음")
        try:
            real_bundle(sys.argv[2])
        except Exception:
            traceback.print_exc()
            check("real_bundle", False, "예외")
        print(f"\n실패: {len(fails)}" + (f" ({', '.join(fails)})" if fails else ""))
        return 1 if fails else 0
    tests = [test_runtime_pin, test_layout, test_bad_inputs, test_runtime_hash_mismatch_stops, test_real_key_mismatch_stops,
             test_signature, test_server_main_verify, test_server_files_closure, test_no_client_code, test_server_dir_missing,
             test_server_dir_crlf_stops, test_server_imports_closed]
    try:
        for t in tests:
            print(t.__name__)
            try:
                t()
            except Exception:
                traceback.print_exc()
                check(t.__name__, False, "예외")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n실패: {len(fails)}" + (f" ({', '.join(fails)})" if fails else ""))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
