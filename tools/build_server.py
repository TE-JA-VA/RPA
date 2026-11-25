# -*- coding: utf-8 -*-
r"""사내 서버(리눅스) 설치 파일 만들기 (계획 2026-11-25-lan-4-linux Task 7, 설계 6.2·8절).

    .venv\Scripts\python.exe tools\build_server.py --version 2026.11.25-1 ^
        --runtime D:\AX\runtime\linux\cpython-3.14.10+20261110-x86_64-unknown-linux-gnu-install_only.tar.gz ^
        --sign-key <업데이트 서명 비밀 열쇠 파일> --out <폴더> [--test-key] [--server-dir <server 폴더>]

결과: <폴더>\AUTOPILOT_Server_<버전>_linux-x86_64.tar.gz 와 같은 이름 + .sig (tar.gz 전체 바이트의 Ed25519 서명, 16진수 한 줄 -
깔린 서버의 'autopilot-server verify·upgrade' 가 본다). 끝에 tar.gz 의 SHA-256 을 sha256sum 꼴로 보여 준다 - 처음 설치 때
업체에 다른 길(메일과 전화 등)로 알리는 값이다 (install.sh --expect-sha256).

안의 꼴 (맨 위 폴더 하나):
    autopilot-server-<버전>/python/         내장 파이썬 (python-build-standalone) - tools/linux_runtime.json 의 SHA-256 과 다르면 멈춘다
                           app/            서버 모듈만 (SERVER_FILES - server_main 에서 import 를 따라가 정한 목록, 하위 폴더 없이)
                           web/            업체 웹 파일 (firebase/web 에서 local_web.HIDDEN_FILES 를 뺀 것)
                           server/         install.sh, systemd 단위, autopilot-server 실행 글 (Task 8 - 폴더가 없으면 빈 자리)
                           manifest.json   파일마다 sha256·크기, 링크, 버전, edition standalone, kind server, 런타임 이름·지문
                           manifest.sig    manifest.json 바이트의 서명 (16진수 한 줄)

서명 열쇠는 경로로만 받는다 (이 도구가 열어 서명에 쓴다 - 내용을 화면·파일에 내지 않는다). --test-key 는 그 열쇠가 시험 열쇠라는
뜻이다: 묶음 안 update_sign·license_check 의 공개 열쇠를 그 열쇠의 공개 열쇠로 바꿔 끼우고 manifest 에 test_build 를 적는다
(고객 배포 금지). --test-key 가 없으면 열쇠가 실린 공개 열쇠(update_sign.PUBLIC_KEY_HEX)와 짝인지 보고, 아니면 멈춘다.
인터넷에서 아무것도 받지 않는다 - 내장 파이썬은 미리 받아 지문을 고정한 파일을 --runtime 으로 준다.
"""
import argparse
import ast
import datetime
import hashlib
import io
import json
import os
import posixpath
import re
import sys
import tarfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
import update_sign  # noqa: E402

PIN_FILE = os.path.join(REPO, "tools", "linux_runtime.json")
ENTRY = "server_main"
SEARCH = ("firebase/agent", ".")                    # 우리 모듈을 찾는 자리 (server_main 의 sys.path 와 같은 차례)
WEB_DIR = "firebase/web"
SERVER_DIR = "server"
EXEC_SCRIPTS = ("install.sh", "autopilot-server")  # server/ 에서 실행 권한(0755)을 주는 것
BUNDLE_PREFIX = "autopilot-server-"                 # server_main.BUNDLE_PREFIX
BUNDLE_VER_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z._-]{0,63}")   # server_main.BUNDLE_VER_RE
RUNTIME_TOP = "python"

# 서버 묶음 app/ 에 싣는 모듈 - server_main 에서 import 를 따라간 결과와 같아야 한다 (server_files_problems, 시험이 본다).
# 새 모듈이 생기면 여기 더하기 전에 바깥 연결 0(설계 8절)을 지키는지 본다 (tests/test_server_offline.py).
SERVER_FILES = (
    "firebase/agent/server_main.py",
    "firebase/agent/ap_sign.py",
    "firebase/agent/lan_ca.py",
    "firebase/agent/lan_config.py",
    "firebase/agent/lan_server.py",
    "firebase/agent/local_server.py",
    "firebase/agent/local_web.py",
    "firebase/agent/login_log.py",
    "firebase/agent/pc_registry.py",
    "firebase/agent/seat.py",
    "firebase/agent/server_backup.py",
    "firebase/agent/server_log.py",
    "firebase/agent/totp.py",
    "firebase/agent/web_security.py",
    "license_check.py",
    "update_sign.py",
)
# 서버 모듈이 함수 안에서만 부르고, 사내 서버에서는 그 함수가 돌지 않는 PC 쪽 모듈 - 따라가지 않고 싣지 않는다 (까닭).
# 이 모듈을 서버 모듈이 맨 위(불러올 때)에서 부르면 문제로 본다.
LAZY_SKIP = {
    "rpa_status": "PC 의 설치 폴더·상태 파일 - 단독(나)의 local_server.data_dir·ensure_keys·main, local_web.web_dir, "
                  "license_check 의 PC 라이선스 자리만 부른다. 사내 서버는 server_main.Paths·web_dir 을 쓴다",
    "edition": "local_web.edition_js 가 try 안에서 부른다 - 없으면 시험용 빌드 띠를 끈다",
    "local_phone": "휴대폰 창구 - ⑧ 에서 연다 (사내 서버 run 은 phone=None)",
}
# 서버 묶음에 들어가면 안 되는 PC 쪽 모듈 (에이전트·ACTOR·옵저버·Firebase 클라이언트·감독·설정 창·업데이트)
CLIENT_MODULES = ("agent", "background", "fb", "local_store", "local_phone", "local_cert", "secret", "server_info", "rpa_status",
                  "edition", "rpa_update", "ap_guard", "update_helper", "ai_rescue", "web_runner", "web_record", "observer",
                  "rpa_settings", "app_start")


class BuildError(RuntimeError):
    """만들기를 멈춘 까닭 (사람 말)."""


# ----------------------------------------------------------------------------------------------------
# 서버 모듈 목록 (import 따라가기)
# ----------------------------------------------------------------------------------------------------
def _find(name, dirs):
    for d in dirs:
        p = os.path.join(d, name + ".py")
        if os.path.isfile(p):
            return p
    return None


def _imports(path):
    """모듈 글의 import [(모듈 첫 이름, 맨 위인가)]. 함수 안은 맨 위가 아니다 (try·if·클래스 본문은 불러올 때 돌므로 맨 위)."""
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), path)
    out = []

    def walk(node, top):
        for child in ast.iter_child_nodes(node):
            inner = top and not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
            if isinstance(child, ast.Import):
                out.extend((a.name.split(".")[0], top) for a in child.names)
            elif isinstance(child, ast.ImportFrom) and child.level == 0 and child.module:
                out.append((child.module.split(".")[0], top))
            walk(child, inner)
    walk(tree, True)
    return out


def module_closure(entry, dirs, skip=()):
    """entry 에서 import 를 따라간 우리 모듈 {이름: 경로} (dirs 에 .py 가 있는 것만 - 표준 라이브러리는 뺀다), 맨 위·함수 안·try 안 모두.
    skip 의 모듈은 따라가지 않는다. 돌려주는 것: (모듈, 처음 부른 쪽 {모듈: 부른 모듈}, skip 을 맨 위에서 부른 곳 [(부른 모듈, skip)])."""
    found, parent, top_skip = {}, {}, []
    todo = [entry]
    while todo:
        name = todo.pop(0)
        if name in found:
            continue
        path = _find(name, dirs)
        if path is None:
            continue
        found[name] = path
        for mod, top in _imports(path):
            if mod in skip:
                if top and (name, mod) not in top_skip:
                    top_skip.append((name, mod))
                continue
            if mod not in found and mod not in parent and mod != entry and _find(mod, dirs):
                parent[mod] = name
                todo.append(mod)
    return found, parent, top_skip


def chain_of(parent, name):
    """처음 부른 쪽을 거슬러 [entry, …, name]."""
    out = [name]
    while out[-1] in parent:
        out.append(parent[out[-1]])
    return out[::-1]


def server_files_problems(repo=REPO):
    """SERVER_FILES 가 server_main 에서 import 를 따라간 모듈과 같은지 - 문제 글 목록 (빈 목록이면 통과)."""
    dirs = [os.path.join(repo, *d.split("/")) for d in SEARCH]
    found, parent, top_skip = module_closure(ENTRY, dirs, skip=set(LAZY_SKIP))
    probs = []
    for name in found:
        if name in CLIENT_MODULES:
            probs.append(f"서버 모듈이 PC 쪽 모듈 {name} 을 불러옵니다 ({' → '.join(chain_of(parent, name))}) - 서버 묶음에 싣지 않는 모듈입니다")
    for who, mod in top_skip:
        probs.append(f"{who} 가 {mod} 를 맨 위에서 불러옵니다 - 사내 서버에서 돌지 않는 함수 안에서만 불러야 합니다 (LAZY_SKIP)")
    rel = {name: os.path.relpath(path, repo).replace(os.sep, "/") for name, path in found.items() if name not in CLIENT_MODULES}
    listed = set(SERVER_FILES)
    for name, r in sorted(rel.items()):
        if r not in listed:
            probs.append(f"SERVER_FILES 에 없는 모듈 {r} ({' → '.join(chain_of(parent, name))})")
    for r in SERVER_FILES:
        if r not in rel.values():
            probs.append(f"SERVER_FILES 의 {r} 는 server_main 에서 불러오지 않습니다")
    names = [posixpath.basename(r) for r in SERVER_FILES]
    for n in sorted({n for n in names if names.count(n) > 1}):
        probs.append(f"app/ 에서 이름이 겹칩니다: {n}")
    return probs


# ----------------------------------------------------------------------------------------------------
# 재료
# ----------------------------------------------------------------------------------------------------
def load_pin(path=PIN_FILE):
    with open(path, encoding="utf-8") as f:
        pin = json.load(f)
    if not (isinstance(pin, dict) and isinstance(pin.get("file"), str) and re.fullmatch(r"[0-9a-f]{64}", str(pin.get("sha256")))):
        raise BuildError(f"{path} 의 꼴이 올바르지 않습니다 (file·sha256·url)")
    return pin


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_secret(path):
    """서명 비밀 열쇠 파일 (16진수 한 줄, tools/publish_release.py 와 같은 꼴). 내용은 어디에도 내지 않는다."""
    try:
        with open(path, encoding="ascii") as f:
            secret = bytes.fromhex(f.read().strip())
    except FileNotFoundError:
        raise BuildError(f"서명 열쇠 파일이 없습니다 ({path})") from None
    except (ValueError, UnicodeDecodeError):
        raise BuildError("서명 열쇠 파일의 꼴이 올바르지 않습니다") from None
    if len(secret) != 32:
        raise BuildError("서명 열쇠 파일의 꼴이 올바르지 않습니다")
    return secret


def swap_key(text, name, hex_value):
    """'<name> = "…"' 줄이 정확히 하나일 때만 그 값을 hex_value 로 바꾼 글 (tools/build_release.swap_key 와 같다)."""
    pat = re.compile(rf'^({re.escape(name)} = ")[0-9A-Fa-f]*(")', re.M)
    if len(pat.findall(text)) != 1:
        raise BuildError(f"{name} 줄이 정확히 하나가 아닙니다 - 시험 열쇠를 끼울 수 없습니다")
    return pat.sub(lambda m: m.group(1) + hex_value + m.group(2), text)


def key_value(text, name):
    m = re.search(rf'^{re.escape(name)} = "([0-9A-Fa-f]*)"', text, re.M)
    return m.group(1) if m else ""


def hidden_web_files(repo=REPO):
    """local_web.HIDDEN_FILES (글에서 읽는다 - 서버 모듈을 불러오지 않으려고)."""
    with open(os.path.join(repo, "firebase", "agent", "local_web.py"), encoding="utf-8") as f:
        for node in ast.parse(f.read()).body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "HIDDEN_FILES" for t in node.targets):
                return tuple(ast.literal_eval(node.value))
    raise BuildError("local_web.HIDDEN_FILES 를 찾지 못했습니다")


def web_files(repo=REPO):
    """업체 웹 파일 [(web/ 안 자리, 원본 경로)] - firebase/web 아래 모든 파일, HIDDEN_FILES(어느 깊이든 파일 이름)·__pycache__ 는 뺀다."""
    base = os.path.join(repo, *WEB_DIR.split("/"))
    hidden = {n.lower() for n in hidden_web_files(repo)}
    out = []
    for folder, dirs, files in os.walk(base):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in files:
            if name.lower() not in hidden:
                path = os.path.join(folder, name)
                out.append((os.path.relpath(path, base).replace(os.sep, "/"), path))
    return sorted(out)


def server_dir_files(folder):
    """server/ 의 파일 [(자리, 경로)] (하위 폴더 없이). 폴더가 없으면 빈 목록."""
    if not folder or not os.path.isdir(folder):
        return []
    return sorted((n, os.path.join(folder, n)) for n in os.listdir(folder) if os.path.isfile(os.path.join(folder, n)))


def _safe_name(name):
    return bool(name) and not name.startswith("/") and "\\" not in name and ".." not in name.split("/") and "" not in name.split("/")


def scan_runtime(path):
    """내장 파이썬 tar.gz 를 훑어 [(자리, 종류 'file'|'link', 모드, 크기, sha256 또는 링크 대상)] - 맨 위 python/ 하나, 이상한 이름·
    하드 링크·장치 파일·밖을 가리키는 링크가 있으면 BuildError."""
    out = []
    try:
        with tarfile.open(path, "r:gz") as tf:
            for m in tf:
                name = m.name.rstrip("/")
                if not _safe_name(name) or name.split("/", 1)[0] != RUNTIME_TOP:
                    raise BuildError(f"내장 파이썬 안의 이름이 올바르지 않습니다: {m.name}")
                if m.isdir():
                    continue
                if m.issym():
                    target = posixpath.normpath(posixpath.join(posixpath.dirname(name), m.linkname))
                    if m.linkname.startswith("/") or not (target + "/").startswith(RUNTIME_TOP + "/"):
                        raise BuildError(f"내장 파이썬 안의 링크가 python/ 밖을 가리킵니다: {name} → {m.linkname}")
                    out.append((name, "link", 0o755, 0, m.linkname))
                elif m.isfile():
                    h = hashlib.sha256()
                    f = tf.extractfile(m)
                    for block in iter(lambda: f.read(1 << 20), b""):
                        h.update(block)
                    out.append((name, "file", 0o755 if m.mode & 0o111 else 0o644, m.size, h.hexdigest()))
                else:
                    raise BuildError(f"내장 파이썬 안에 파일·폴더·링크가 아닌 것이 있습니다: {name}")
    except (tarfile.TarError, OSError, EOFError) as e:
        raise BuildError(f"내장 파이썬 파일을 읽지 못했습니다 ({type(e).__name__})") from None
    if not any(n == f"{RUNTIME_TOP}/bin/python3" for n, *_ in out):
        raise BuildError("내장 파이썬 안에 python/bin/python3 이 없습니다")
    return out


def bundle_name(version):
    return f"AUTOPILOT_Server_{version}_linux-x86_64.tar.gz"


# ----------------------------------------------------------------------------------------------------
# 만들기
# ----------------------------------------------------------------------------------------------------
def build(version, runtime, sign_key, out_dir, test_key=False, pin=None, server_dir=None, repo=REPO, now=None):
    """설치 파일과 서명을 만든다 → (tar.gz 경로, .sig 경로). 멈출 까닭이면 BuildError(RuntimeError)·ValueError(버전) - 결과 파일을
    남기지 않는다."""
    if not isinstance(version, str) or not BUNDLE_VER_RE.fullmatch(version):
        raise ValueError(f"버전 꼴이 올바르지 않습니다: {version!r}")
    pin = pin if pin is not None else load_pin()
    probs = server_files_problems(repo)
    if probs:
        raise BuildError("서버 모듈 목록에 문제가 있습니다:\n    " + "\n    ".join(probs))
    secret = read_secret(sign_key)
    public = update_sign.secret_to_public(secret).hex()
    texts = {}                                                   # 원본 대신 싣는 글 {SERVER_FILES 자리: 글}
    for rel in ("update_sign.py", "license_check.py"):
        with open(os.path.join(repo, rel), encoding="utf-8") as f:
            texts[rel] = f.read()
    if test_key:
        texts["update_sign.py"] = swap_key(texts["update_sign.py"], "PUBLIC_KEY_HEX", public)
        texts["license_check.py"] = swap_key(texts["license_check.py"], "LICENSE_PUBLIC_KEY_HEX", public)
    else:
        if key_value(texts["update_sign.py"], "PUBLIC_KEY_HEX").lower() != public:
            raise BuildError("서명 열쇠가 실린 공개 열쇠(update_sign.PUBLIC_KEY_HEX)와 짝이 아닙니다 - 깔린 서버가 이 파일을 확인하지 못합니다")
        if not key_value(texts["license_check.py"], "LICENSE_PUBLIC_KEY_HEX"):
            raise BuildError("라이선스 공개 열쇠(license_check.LICENSE_PUBLIC_KEY_HEX)가 비어 있습니다 - 어떤 라이선스도 통하지 않습니다")
        texts = {}
    if file_sha256(runtime) != pin["sha256"]:
        raise BuildError(f"내장 파이썬의 지문(SHA-256)이 고정한 값과 다릅니다 ({os.path.basename(runtime)}) - "
                         "tools/linux_runtime.json 의 파일을 써 주십시오")
    rt = scan_runtime(runtime)

    # 묶음에 넣을 것 [(자리, 종류, 모드, 바이트·경로·링크)] - 런타임 파일은 쓸 때 다시 읽는다
    items = []
    for rel in SERVER_FILES:
        base = posixpath.basename(rel)
        if rel in texts:
            data = texts[rel].encode("utf-8")
        else:
            with open(os.path.join(repo, *rel.split("/")), "rb") as f:
                data = f.read()
        items.append(("app/" + base, "file", 0o644, data))
    for rel, path in web_files(repo):
        with open(path, "rb") as f:
            items.append(("web/" + rel, "file", 0o644, f.read()))
    sfiles = server_dir_files(server_dir if server_dir is not None else os.path.join(repo, SERVER_DIR))
    if not any(n == "install.sh" for n, _ in sfiles):
        print("  알림: server/ 에 install.sh 가 없습니다 - 설치할 수 없는 묶음입니다 (Task 8 전 시험용)")
    for name, path in sfiles:
        with open(path, "rb") as f:
            items.append(("server/" + name, "file", 0o755 if name in EXEC_SCRIPTS else 0o644, f.read()))

    files, links = {}, {}
    for rel, kind, mode, data in items:
        files[rel] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    for rel, kind, mode, size, val in rt:
        if kind == "link":
            links[rel] = val
        else:
            files[rel] = {"sha256": val, "size": size}
    made = now or datetime.datetime.now().astimezone()
    man = {"version": version, "edition": "standalone", "kind": "server", "made": made.isoformat(timespec="seconds"),
           "test_build": bool(test_key), "runtime": {"file": pin["file"], "sha256": pin["sha256"]},
           "files": dict(sorted(files.items())), "links": dict(sorted(links.items()))}
    man_raw = json.dumps(man, ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8") + b"\n"
    man_sig = (update_sign.sign(secret, man_raw).hex() + "\n").encode("ascii")

    dirs = {"", "app", "web", "server", RUNTIME_TOP}
    for rel in list(files) + list(links):
        parts = rel.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            dirs.add("/".join(parts[:i]))
    top = BUNDLE_PREFIX + version
    mtime = int(made.timestamp())

    def info(rel, kind, mode, size=0, link=""):
        ti = tarfile.TarInfo(f"{top}/{rel}" if rel else top)
        ti.mode, ti.mtime, ti.uid, ti.gid, ti.uname, ti.gname = mode, mtime, 0, 0, "root", "root"
        if kind == "dir":
            ti.type = tarfile.DIRTYPE
        elif kind == "link":
            ti.type, ti.linkname = tarfile.SYMTYPE, link
        else:
            ti.size = size
        return ti

    path = os.path.join(out_dir, bundle_name(version))
    sig_path = path + ".sig"
    if os.path.exists(path) or os.path.exists(sig_path):          # 내보낸 버전의 파일·지문을 덮지 않는다
        raise BuildError(f"이미 있습니다 ({path}) - 다른 버전 번호를 쓰거나 옛 파일을 치운 뒤 다시 만드십시오")
    os.makedirs(out_dir, exist_ok=True)
    part, sig_part = path + ".part", sig_path + ".part"
    try:
        with tarfile.open(part, "w:gz", format=tarfile.PAX_FORMAT) as out:
            for d in sorted(dirs):
                out.addfile(info(d, "dir", 0o755))
            for rel, data in (("manifest.json", man_raw), ("manifest.sig", man_sig)):
                out.addfile(info(rel, "file", 0o644, len(data)), io.BytesIO(data))
            for rel, kind, mode, data in items:
                out.addfile(info(rel, "file", mode, len(data)), io.BytesIO(data))
            want = {n: (k, mode, size, val) for n, k, mode, size, val in rt}
            with tarfile.open(runtime, "r:gz") as src:           # 두 번째로 읽으며 그대로 옮긴다 - 지문을 다시 맞춰 본다
                for m in src:
                    name = m.name.rstrip("/")
                    if m.isdir():
                        continue
                    got = want.pop(name, None)
                    if got is None:
                        raise BuildError(f"내장 파이썬 파일이 읽는 사이 바뀌었습니다: {name}")
                    kind, mode, size, val = got
                    if kind == "link":
                        out.addfile(info(name, "link", 0o755, link=val))
                        continue
                    data = src.extractfile(m).read()
                    if hashlib.sha256(data).hexdigest() != val:
                        raise BuildError(f"내장 파이썬 파일이 읽는 사이 바뀌었습니다: {name}")
                    out.addfile(info(name, "file", mode, len(data)), io.BytesIO(data))
            if want:
                raise BuildError("내장 파이썬 파일이 읽는 사이 바뀌었습니다")
        with open(part, "rb") as f:
            raw = f.read()
        sig = update_sign.sign(secret, raw)
        if not update_sign.verify(bytes.fromhex(public), raw, sig):
            raise BuildError("만든 서명이 맞지 않습니다")
        with open(sig_part, "w", encoding="ascii", newline="\n") as f:
            f.write(sig.hex() + "\n")
        os.replace(part, path)
        os.replace(sig_part, sig_path)
    except BaseException:
        for p in (part, sig_part, path, sig_path):            # 이 호출이 만든 것만 (있던 파일이면 위에서 멈췄다)
            try:
                os.remove(p)
            except OSError:
                pass
        raise
    return path, sig_path


def main(argv=None):
    ap = argparse.ArgumentParser(description="사내 서버(리눅스) 설치 파일을 만든다")
    ap.add_argument("--version", required=True, help="버전 (예: 2026.11.25-1)")
    ap.add_argument("--runtime", required=True, help="내장 파이썬 tar.gz (tools/linux_runtime.json 에 지문을 고정한 파일)")
    ap.add_argument("--sign-key", required=True, metavar="파일", help="업데이트 서명 비밀 열쇠 파일 (경로만 - 내용은 내지 않는다)")
    ap.add_argument("--out", required=True, metavar="폴더", help="결과를 둘 폴더")
    ap.add_argument("--test-key", action="store_true", help="시험 열쇠: 묶음 안 공개 열쇠를 그 열쇠로 바꿔 끼운다 (고객 배포 금지)")
    ap.add_argument("--server-dir", default=None, metavar="폴더", help=f"server/ 에 넣을 폴더 (기본 저장소의 {SERVER_DIR}/)")
    args = ap.parse_args(argv)
    try:
        path, sig = build(args.version, args.runtime, args.sign_key, args.out, test_key=args.test_key, server_dir=args.server_dir)
    except (BuildError, ValueError, OSError) as e:
        print("  문제:", e)
        return 1
    print(f"서버 설치 파일 {path}  ({os.path.getsize(path) // 2 ** 20}MB)" + ("  - 시험용, 고객 배포 금지" if args.test_key else ""))
    print(f"  서명 {sig}")
    print(f"  SHA-256 (sha256sum -c 꼴):\n{file_sha256(path)}  {os.path.basename(path)}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
