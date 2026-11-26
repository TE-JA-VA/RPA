# -*- coding: utf-8 -*-
"""사내 서버 ④ Task 8 - install.sh 와 systemd 단위 (WSL 전용, 계획 2026-11-25-lan-4-linux Task 8, Review Focus 1·2·5).

시험 모드로만 돈다: install.sh --root <임시 폴더> [--no-systemd] --service-user nobody. 이 PC(WSL)의 진짜 /etc·/opt·/var·systemd·
사용자 계정·방화벽은 건드리지 않는다 - install.sh 는 --root 이면 systemctl·useradd·userdel·ufw·firewall-cmd 를 AP_FAKE_BIN 의
가짜에서만 찾는다. 가짜 systemctl 은 서비스를 '실제로' 켠다: 설치된 실행 글(server/autopilot-server 를 시험 자리로 바꾼 사본)로
autopilot-server run 을 setpriv 로 nobody(65534) 계정에서 돌린다 (WSL 은 root 라 서비스 계정 흉내).
묶음은 tools/build_server.py 로 시험 열쇠와 가짜 런타임(python3 → 이 WSL 의 /usr/bin/python3)으로 만든다. 실행 글·install.sh·
단위 파일은 저장소의 server/ 그대로다 (Codex 검토 2 를 잡는다).
    wsl.exe -d Ubuntu -e python3 /mnt/d/AX/RPA_StandAlone/tests/wsl_install.py
진짜 내장 파이썬으로 핵심(설치·실행 글·활성화·업그레이드·되돌리기)만:
    wsl.exe -d Ubuntu -e python3 /mnt/d/AX/RPA_StandAlone/tests/wsl_install.py --real-runtime /mnt/d/AX/runtime/linux/<파일>.tar.gz
윈도우에서는 건너뛴다 (실패: 0).
"""
import contextlib
import hashlib
import io
import json
import os
import pwd
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import traceback

sys.stdout.reconfigure(encoding="utf-8")
if os.name != "posix":
    print("  [건너뜀] wsl_install 은 리눅스(WSL)에서만")
    print("\n실패: 0")
    sys.exit(0)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import build_server  # noqa: E402
import license_check  # noqa: E402
import make_license  # noqa: E402
import update_sign  # noqa: E402

fails = []
T = tempfile.mkdtemp(prefix="rpa_wsl_install_", dir="/tmp")
os.chmod(T, 0o755)                                   # 서비스 계정(nobody)이 시험 자리를 지나갈 수 있게
SECRET, PUBLIC = update_sign.keygen()                # 시험 열쇠 하나 - 업데이트 서명·라이선스 서명 모두 (--test-key 묶음)
KEY = os.path.join(T, "test_key.txt")
with open(KEY, "w", encoding="ascii") as f:
    f.write(SECRET.hex() + "\n")
os.chmod(KEY, 0o600)
NOBODY = pwd.getpwnam("nobody")
SVC_UID, SVC_GID = NOBODY.pw_uid, NOBODY.pw_gid
STD_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
REAL_RUNTIME = None                                  # --real-runtime
WAIT = "10"
BOSS_PW = "pw-1234567890"
UNITS = ("autopilot.service", "autopilot-cert.service", "autopilot-cert.timer", "autopilot-config-backup.service",
         "autopilot-config-backup.timer")


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {str(detail)[:1500]}"))
    if not ok:
        fails.append(name)


def mode(p):
    return stat.S_IMODE(os.lstat(p).st_mode)


def owner(p):
    st = os.stat(p)
    return st.st_uid, st.st_gid


def read(p, binary=False):
    try:
        with open(p, "rb" if binary else "r", **({} if binary else {"encoding": "utf-8"})) as f:
            return f.read()
    except OSError:
        return b"" if binary else ""


def tree(p):
    """폴더 안의 모든 자리 (상대 경로) - 아무것도 생기지 않았는지 볼 때."""
    out = []
    for d, ds, ns in os.walk(p):
        for n in ds + ns:
            out.append(os.path.relpath(os.path.join(d, n), p))
    return sorted(out)


def free_ports(n):
    socks, ports = [], []
    for _ in range(n):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        socks.append(s)
        ports.append(s.getsockname()[1])
    for s in socks:
        s.close()
    return ports


# ---------------------------------------------------------------------------------------------
# 묶음 만들기 (가짜 런타임 또는 진짜)
# ---------------------------------------------------------------------------------------------
def fake_runtime():
    path = os.path.join(T, "rt", "cpython-3.14.0+00000000-x86_64-unknown-linux-gnu-install_only.tar.gz")
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path))
        with tarfile.open(path, "w:gz") as tf:
            data = b'#!/bin/sh\nexec /usr/bin/python3 "$@"\n'     # 가짜 내장 파이썬 = 이 WSL 의 파이썬
            ti = tarfile.TarInfo("python/bin/python3.14")
            ti.size, ti.mode = len(data), 0o755
            tf.addfile(ti, io.BytesIO(data))
            ln = tarfile.TarInfo("python/bin/python3")
            ln.type, ln.linkname = tarfile.SYMTYPE, "python3.14"
            tf.addfile(ln)
    with open(path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    return path, {"file": os.path.basename(path), "sha256": digest, "url": "https://example.invalid/fake.tar.gz"}


def broken_repo():
    """'켜지지 않는 새 버전' 을 만들 저장소 사본 - server_main.cmd_run 이 곧바로 4 (run.json 을 쓰지 않는다)."""
    d = os.path.join(T, "repo_norun")
    if os.path.isdir(d):
        return d
    for rel in build_server.SERVER_FILES:
        dst = os.path.join(d, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(os.path.join(ROOT, *rel.split("/")), dst)
    shutil.copytree(os.path.join(ROOT, "firebase", "web"), os.path.join(d, "firebase", "web"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(os.path.join(ROOT, "server"), os.path.join(d, "server"))
    p = os.path.join(d, "firebase", "agent", "server_main.py")
    text = read(p)
    new = text.replace("def cmd_run(args, paths):\n", "def cmd_run(args, paths):\n    return 4                         # 시험: 켜지지 않는 새 버전\n", 1)
    assert new != text, "cmd_run 을 찾지 못함"
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(new)
    return d


BUNDLES = {}


def bundle(ver, norun=False, bad_manifest=False):
    """시험 열쇠 묶음 → (tar.gz 경로, sha256, 푼 폴더). 푼 폴더는 tar.gz 옆 (사람이 푸는 자리 - install.sh 가 ../ 에서 tar.gz 를 찾는다)."""
    if ver in BUNDLES:
        return BUNDLES[ver]
    out = os.path.join(T, "b_" + ver)
    if REAL_RUNTIME:
        rt, pin = REAL_RUNTIME, build_server.load_pin()
    else:
        rt, pin = fake_runtime()
    repo = broken_repo() if norun else build_server.REPO
    with contextlib.redirect_stdout(io.StringIO()):
        path, sig = build_server.build(ver, rt, KEY, out, test_key=True, pin=pin, repo=repo,
                                       server_dir=os.path.join(repo, "server"))
    if bad_manifest:                                 # manifest 의 지문 하나를 바꾸고 manifest.sig·.sig 를 다시 서명 (서명은 맞고 지문만 틀림)
        top = f"autopilot-server-{ver}"
        with tarfile.open(path, "r:gz") as src:
            items = [(m, src.extractfile(m).read() if m.isfile() else None) for m in src.getmembers()]
        man_raw = next(d for m, d in items if m.name == f"{top}/manifest.json")
        man = json.loads(man_raw)
        man["files"]["app/server_main.py"]["sha256"] = "0" * 64
        new_raw = json.dumps(man, ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8") + b"\n"
        new_sig = (update_sign.sign(SECRET, new_raw).hex() + "\n").encode("ascii")
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.PAX_FORMAT) as dst:
            for m, d in items:
                if m.name == f"{top}/manifest.json":
                    d = new_raw
                elif m.name == f"{top}/manifest.sig":
                    d = new_sig
                if d is not None:
                    m.size = len(d)
                    dst.addfile(m, io.BytesIO(d))
                else:
                    dst.addfile(m)
        raw = buf.getvalue()
        with open(path, "wb") as f:
            f.write(raw)
        with open(sig, "w", encoding="ascii") as f:
            f.write(update_sign.sign(SECRET, raw).hex() + "\n")
    with open(path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    with tarfile.open(path, "r:gz") as tf:
        tf.extractall(out, filter="data")
    BUNDLES[ver] = (path, digest, os.path.join(out, f"autopilot-server-{ver}"))
    return BUNDLES[ver]


# ---------------------------------------------------------------------------------------------
# 가짜 시스템 명령
# ---------------------------------------------------------------------------------------------
FAKE_SYSTEMCTL = r'''#!/usr/bin/python3
# 가짜 systemctl (wsl_install.py) - 부른 인자를 FAKE_LOG 에 적고, autopilot 서비스는 설치된 실행 글로 nobody 계정에서 실제로 켠다
import os, signal, subprocess, sys, time
log, prefix, state = os.environ["FAKE_LOG"], os.environ["FAKE_PREFIX"], os.environ["FAKE_STATE"]
args = sys.argv[1:]
with open(log, "a", encoding="utf-8") as f:
    f.write("systemctl " + " ".join(args) + "\n")
if args[:1] == ["--version"]:
    print("systemd %s (fake)" % os.environ.get("FAKE_SYSTEMD_VERSION", "255"))
    sys.exit(0)
os.makedirs(state, exist_ok=True)
pidf = os.path.join(state, "service.pid")

def pid():
    try:
        with open(pidf) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None

def alive(p):
    if not p:
        return False
    try:
        with open("/proc/%d/stat" % p) as f:
            st = f.read().rsplit(")", 1)[1].split()[0]
    except (OSError, IndexError):
        return False
    return st not in ("Z", "X")

def stop():
    p = pid()
    if alive(p):
        os.kill(p, signal.SIGTERM)
        end = time.time() + 20
        while alive(p) and time.time() < end:
            time.sleep(0.1)
        if alive(p):
            os.kill(p, signal.SIGKILL)
            time.sleep(0.5)
    try:
        os.remove(pidf)
    except OSError:
        pass

def start():
    if alive(pid()):
        return
    out = open(os.path.join(state, "service.out"), "ab")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("AUTOPILOT_", "AP_", "FAKE_"))}
    env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    p = subprocess.Popen(["setpriv", "--reuid=65534", "--regid=65534", "--clear-groups", "--",
                          os.path.join(prefix, "usr/local/sbin/autopilot-server"), "run"],
                         stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, env=env, start_new_session=True, cwd="/")
    with open(pidf, "w") as f:
        f.write(str(p.pid))

cmd = args[0] if args else ""
units = [a for a in args[1:] if not a.startswith("-")]
svc = any(u in ("autopilot", "autopilot.service") for u in units)
if cmd == "enable" and "--now" in args and svc:
    start()
elif cmd == "start" and svc:
    start()
elif cmd == "stop" and svc:
    stop()
elif cmd == "restart" and svc:
    stop()
    start()
elif cmd == "try-restart" and svc:
    if alive(pid()):
        stop()
        start()
elif cmd == "is-active":
    sys.exit(0 if alive(pid()) else 3)
sys.exit(0)
'''


def fakebin(name, systemctl=True, ufw=False, getent=None, useradd=False, openssl_broken=False):
    d = os.path.join(T, "fb_" + name)
    os.makedirs(d, exist_ok=True)

    def put(n, text):
        p = os.path.join(d, n)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.chmod(p, 0o755)
    if systemctl:
        put("systemctl", FAKE_SYSTEMCTL)
    if ufw:
        put("ufw", '#!/bin/sh\necho "ufw $*" >> "$FAKE_LOG"\n[ "$1" = status ] && echo "Status: active"\nexit 0\n')
    if getent == "human":
        put("getent", '#!/bin/sh\necho "getent $*" >> "$FAKE_LOG"\n'
                      '[ "$2" = autopilotd ] && echo "autopilotd:x:1001:1001:Autopilot:/home/autopilotd:/bin/bash" && exit 0\nexit 2\n')
    elif getent == "missing":
        put("getent", '#!/bin/sh\necho "getent $*" >> "$FAKE_LOG"\nexit 2\n')
    if useradd:
        put("useradd", '#!/bin/sh\necho "useradd $*" >> "$FAKE_LOG"\necho "useradd: 시험이라 만들지 않음" >&2\nexit 1\n')
    if openssl_broken:
        put("openssl", '#!/bin/sh\necho "openssl $*" >> "$FAKE_LOG"\nexit 127\n')
    return d


class Box:
    """시험 자리 하나 (--root PREFIX) 와 그 가짜 명령."""

    def __init__(self, name, **fake):
        self.name = name
        self.p = os.path.join(T, "p_" + name)
        os.makedirs(self.p)
        os.chmod(self.p, 0o755)
        self.fb = fakebin(name, **fake)
        self.log = os.path.join(T, f"fake_{name}.log")
        self.state = os.path.join(T, f"state_{name}")
        self.opt = os.path.join(self.p, "opt", "autopilot")
        self.cur = os.path.join(self.opt, "current")
        self.rel = os.path.join(self.opt, "releases")
        self.etc = os.path.join(self.p, "etc", "autopilot")
        self.data = os.path.join(self.p, "var", "lib", "autopilot")
        self.logs = os.path.join(self.p, "var", "log", "autopilot")
        self.bkp = os.path.join(self.p, "var", "backups", "autopilot")
        self.units = os.path.join(self.p, "etc", "systemd", "system")
        self.ap = os.path.join(self.p, "usr", "local", "sbin", "autopilot-server")

    def env(self, **extra):
        e = {"PATH": STD_PATH, "HOME": "/root", "LANG": "C.UTF-8", "AP_FAKE_BIN": self.fb, "FAKE_LOG": self.log,
             "FAKE_PREFIX": self.p, "FAKE_STATE": self.state, "AP_START_WAIT": WAIT}
        e.update({k: str(v) for k, v in extra.items()})
        return e

    def sh(self, bdir, args, env=None, timeout=300):
        assert "--root" in args, "시험은 --root 로만"
        r = subprocess.run(["sh", os.path.join(bdir, "server", "install.sh")] + args, capture_output=True, timeout=timeout,
                           env=env or self.env(), cwd=T)
        return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")

    def install(self, ver, extra=(), env=None, sha=None, systemd=False):
        path, digest, bdir = bundle(ver)
        args = ["install", "--expect-sha256", sha or digest, "--listen", "127.0.0.1", "--allow", "127.0.0.0/8",
                "--root", self.p, "--service-user", "nobody"] + ([] if systemd else ["--no-systemd"]) + list(extra)
        return self.sh(bdir, args, env)

    def ap_run(self, args, env=None, stdin=None, timeout=300):
        r = subprocess.run([self.ap] + args, capture_output=True, timeout=timeout, env=env or self.env(), cwd=T,
                           input=stdin.encode("utf-8") if stdin is not None else None)
        return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")

    def systemctl(self, *args):
        return subprocess.run([os.path.join(self.fb, "systemctl")] + list(args), env=self.env(), capture_output=True, timeout=60).returncode

    def fake_log(self):
        return read(self.log)

    def current(self):
        try:
            return os.readlink(self.cur)
        except OSError:
            return None

    def running(self):
        """도는 서비스의 (버전, pid) - autopilot-server status --json (root)."""
        code, so, se = self.ap_run(["status", "--json"])
        try:
            d = json.loads(so)
        except ValueError:
            return None, None
        return (d.get("running_version"), d.get("pid")) if d.get("running") else (None, None)

    def wait_running(self, ver, sec=20):
        end = time.time() + sec
        while time.time() < end:
            if self.running()[0] == ver:
                return True
            time.sleep(0.3)
        return self.running()[0] == ver

    def backups(self):
        try:
            return sorted(n for n in os.listdir(os.path.join(self.data, "backups")) if n.endswith(".tar.gz"))
        except OSError:
            return []

    def releases(self):
        return sorted(os.listdir(self.rel)) if os.path.isdir(self.rel) else []

    def set_ports(self):
        """server.json 의 포트를 비어 있는 것으로 (모드·소유자 그대로 - 같은 파일에 덮어쓴다)."""
        p = os.path.join(self.etc, "server.json")
        cfg = json.loads(read(p))
        w, a = free_ports(2)
        cfg["ports"] = {"web": w, "agent": a}
        with open(p, "w", encoding="utf-8") as f:
            f.write(json.dumps(cfg, ensure_ascii=False, indent=1) + "\n")

    def as_nobody(self, argv):
        r = subprocess.run(["setpriv", "--reuid=65534", "--regid=65534", "--clear-groups", "--"] + argv, capture_output=True,
                           timeout=60, cwd="/", env={"PATH": STD_PATH})
        return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace")

    def cleanup(self):
        try:
            self.systemctl("stop", "autopilot.service")
        except Exception:
            pass


BOXES = []


def box(name, **fake):
    b = Box(name, **fake)
    BOXES.append(b)
    return b


def license_for(b, server_id=None, seat_pub=None, seats=5):
    req = json.loads(read(os.path.join(b.data, "server_request.json")))
    body = make_license.build_server_body({"server_id": server_id or req["server_id"], "seat_pub": seat_pub or req["seat_pub"]},
                                          {"company": "시험상사", "cid": "c_test", "seats": seats})
    doc = license_check.sign_body(SECRET, body)
    p = os.path.join(T, f"license_{b.name}_{len(os.listdir(T))}.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    return p


# ---------------------------------------------------------------------------------------------
# 시험
# ---------------------------------------------------------------------------------------------
V1, V2, V3, V4, V5, V6, V7 = ("2026.11.25-81", "2026.11.25-82", "2026.11.25-83", "2026.11.25-84", "2026.11.25-85",
                              "2026.11.25-86", "2026.11.25-87")
V8 = "2026.11.25-88"
MAIN = {}


def test_expect_sha256():
    b = box("sha")
    code, so, se = b.install(V1, sha="0" * 64)
    check("SHA-256 이 다르면 1", code != 0 and "SHA-256" in se and "아무것도" in se, (code, so, se))
    check("SHA-256 이 다르면 아무것도 생기지 않는다", tree(b.p) == [], tree(b.p))
    code, so, se = b.install(V1, sha="xyz")
    check("SHA-256 꼴이 틀려도 1, 아무것도 없음", code != 0 and tree(b.p) == [], (code, se))
    path, digest, bdir = bundle(V1)
    code, so, se = b.sh(bdir, ["install", "--expect-sha256", digest, "--listen", "127.0.0.1", "--allow", "127.0.0.0/8",
                               "--root", b.p, "--service-user", "nobody", "--no-systemd", "--bundle", os.path.join(T, "none.tar.gz")])
    check("설치 파일을 못 찾으면 1 (--bundle 안내)", code != 0 and "--bundle" in se and tree(b.p) == [], (code, se))


def test_preflight():
    b = box("pre_openssl", openssl_broken=True)
    code, so, se = b.install(V1)
    check("openssl 이 돌지 않으면 멈춤 (까닭에 openssl)", code != 0 and "openssl" in se and "설치 전 점검" in se, (code, se))
    check("openssl 점검에서 멈추면 아무것도 없다", tree(b.p) == [], tree(b.p))
    b = box("pre_disk")
    code, so, se = b.install(V1, env=b.env(AP_MIN_FREE_MB=10 ** 9))
    check("남은 공간이 모자라면 멈춤 (까닭에 공간)", code != 0 and "공간" in se, (code, se))
    check("공간 점검에서 멈추면 아무것도 없다", tree(b.p) == [], tree(b.p))
    b = box("pre_systemd")
    code, so, se = b.install(V1, env=b.env(FAKE_SYSTEMD_VERSION=219), systemd=True)
    check("systemd 가 235 보다 낮으면 멈춤", code != 0 and "systemd" in se and "235" in se, (code, se))
    check("systemd 점검에서 멈추면 아무것도 없다", tree(b.p) == [], tree(b.p))
    b = box("pre_nosystemctl", systemctl=False)
    code, so, se = b.install(V1, systemd=True)
    check("systemctl 이 없으면 멈춤", code != 0 and "systemctl" in se and tree(b.p) == [], (code, se))
    # root 가 아님 - --root 없이 nobody 로 (root 확인에서 곧바로 멈춘다: 진짜 자리에는 아무것도 하지 않는다)
    path, digest, bdir = bundle(V1)
    code, out = b.as_nobody(["sh", os.path.join(bdir, "server", "install.sh"), "install", "--expect-sha256", digest,
                             "--listen", "127.0.0.1", "--allow", "127.0.0.0/8"])
    check("root 가 아니면 멈춤 ('root 로 실행')", code != 0 and "root" in out, (code, out))
    code, so, se = b.sh(bdir, ["install", "--expect-sha256", digest, "--listen", "127.0.0.1", "--allow", "127.0.0.0/8",
                               "--service-user", "nobody", "--root", b.p, "--bogus"])
    check("모르는 인자는 1", code != 0 and "--bogus" in se, (code, se))
    # --root 없는 진짜 설치 모양은 nobody 로만 돌린다 (설령 멈추지 않아도 진짜 자리에 쓰지 못한다)
    code, out = b.as_nobody(["sh", os.path.join(bdir, "server", "install.sh"), "install", "--expect-sha256", digest, "--listen", "127.0.0.1",
                             "--allow", "127.0.0.0/8", "--service-user", "nobody"])
    check("--service-user 는 --root 와 함께만 (진짜 설치에서 거절)", code != 0 and "--root" in out, out)
    b = box("pre_cfg")
    code, so, se = b.install(V1, extra=["--names", "kr"])
    check("설정 값이 틀리면(점 없는 이름) 멈춤, 아무것도 없음", code != 0 and "names" in se and tree(b.p) == [], (code, se))


def test_account_rules():
    b = box("acct_human", getent="human")
    path, digest, bdir = bundle(V1)
    code, so, se = b.sh(bdir, ["install", "--expect-sha256", digest, "--listen", "127.0.0.1", "--allow", "127.0.0.0/8",
                               "--root", b.p, "--no-systemd"])
    check("같은 이름의 로그인 계정(autopilotd, /bin/bash)이 있으면 멈춤", code != 0 and "로그인할 수 있는 계정" in se, (code, se))
    check("계정 점검에서 멈추면 아무것도 없다", tree(b.p) == [], tree(b.p))
    b = box("acct_missing", getent="missing", useradd=True)
    code, so, se = b.sh(bdir, ["install", "--expect-sha256", digest, "--listen", "127.0.0.1", "--allow", "127.0.0.0/8",
                               "--root", b.p, "--no-systemd"])
    log = b.fake_log()
    ua = [ln for ln in log.splitlines() if ln.startswith("useradd ")]
    check("계정이 없으면 시스템 계정으로 만든다 (useradd --system --no-create-home --shell …nologin --user-group autopilotd)",
          len(ua) == 1 and all(w in ua[0].split() for w in ("--system", "--no-create-home", "--user-group", "autopilotd"))
          and "nologin" in ua[0], log)
    check("계정을 못 만들면 멈추고 아무것도 없다", code != 0 and tree(b.p) == [], (code, se, tree(b.p)))


def unpacked_copy(name, ver):
    """사람이 받은 tar.gz 를 새 폴더에 복사해 그 옆에 푼 것 → (tar.gz 사본, 푼 폴더, 지문)."""
    path, digest, _ = bundle(ver)
    d = os.path.join(T, name)
    os.makedirs(d)
    tar = os.path.join(d, os.path.basename(path))
    shutil.copyfile(path, tar)
    with tarfile.open(tar, "r:gz") as tf:
        tf.extractall(d, filter="data")
    return tar, os.path.join(d, f"autopilot-server-{ver}"), digest


def test_install_uses_verified_copy():
    """처음 설치는 지문을 맞춘 tar.gz 의 root 전용 사본만 쓴다 - 사람이 풀어 둔 폴더의 python3·install_helper.py 는 root 로 돌리지
    않고, 지문을 본 뒤 원래 tar.gz 를 바꿔치기해도 사본으로 푼다 (Codex 중간 검토 1)."""
    tar, bdir, digest = unpacked_copy("trust1", V1)
    other = bundle(V2)[0]
    mark_py, mark_helper = os.path.join(T, "trust1_python_ran"), os.path.join(T, "trust1_helper_ran")
    py = os.path.join(bdir, "python", "bin", "python3")
    os.remove(py)
    with open(py, "w", encoding="utf-8", newline="\n") as f:      # 돌면 표시를 남기고 원래 tar.gz 를 다른 버전으로 바꾼다
        f.write(f'#!/bin/sh\n: > "{mark_py}"\ncp "{other}" "{tar}"\nexec "$(dirname "$0")/python3.14" "$@"\n')
    os.chmod(py, 0o755)
    helper = os.path.join(bdir, "server", "install_helper.py")
    text = read(helper)
    with open(helper, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"open({mark_helper!r}, 'w').close()\n" + text)
    b = box("trust1")
    args = ["install", "--expect-sha256", digest, "--listen", "127.0.0.1", "--allow", "127.0.0.0/8", "--root", b.p,
            "--service-user", "nobody", "--no-systemd"]
    code, so, se = b.sh(bdir, args)
    check("풀어 둔 폴더의 python3 를 바꿔 두어도 설치 0", code == 0, (code, so[-800:], se[-1200:]))
    check("풀어 둔 폴더의 python3 은 한 번도 돌지 않았다", not os.path.exists(mark_py))
    check("풀어 둔 폴더의 install_helper.py 도 돌지 않았다", not os.path.exists(mark_helper))
    man = os.path.join(b.rel, V1, "manifest.json")
    check("설치된 것은 지문을 맞춘 버전", b.current() == f"releases/{V1}" and json.loads(read(man) or "{}").get("version") == V1,
          (b.current(), read(man)[:200]))
    check("root 전용 임시 자리는 남기지 않는다", not [n for n in os.listdir(b.p) if n.startswith(".")], os.listdir(b.p))
    # 지문을 본 직후 원래 tar.gz 를 바꿔치기 (시험 손잡이) - 확인한 사본으로 풀어야 한다
    tar2, bdir2, digest2 = unpacked_copy("trust2", V1)
    b2 = box("trust2")
    args2 = ["install", "--expect-sha256", digest2, "--listen", "127.0.0.1", "--allow", "127.0.0.0/8", "--root", b2.p,
             "--service-user", "nobody", "--no-systemd"]
    code, so, se = b2.sh(bdir2, args2, env=b2.env(AP_TEST_SWAP_TAR=other))
    check("지문을 본 뒤 원래 tar.gz 를 바꿔치기해도 설치 0 (확인한 사본으로 푼다)", code == 0
          and json.loads(read(os.path.join(b2.rel, V1, "manifest.json")) or "{}").get("version") == V1, (code, se[-1200:]))
    check("바꿔치기는 실제로 일어났다 (시험 확인)", read(tar2, True) == read(other, True))
    # 업체 안내 순서 (머리 주석·끝 안내)
    head = read(os.path.join(ROOT, "server", "install.sh"))[:3000]
    check("머리 주석: 풀기 전에 sha256sum → root 전용 폴더(install -d -m 0700)에 풀기 → install.sh",
          "sha256sum" in head and "install -d -m 0700" in head and head.index("sha256sum") < head.index("install -d -m 0700"), head[:1500])
    code, so, se = b2.sh(bdir2, ["--help", "--root", b2.p])
    check("도움말에도 같은 순서", "install -d -m 0700" in so and "sha256sum" in so, so[:1500])


def test_fresh_install_layout():
    b = box("main")
    MAIN["b"] = b
    t0 = time.time()
    code, so, se = b.install(V1, sha=bundle(V1)[1].upper(), env=b.env(TZ="UTC"))
    print(f"    (설치 {time.time() - t0:.1f}초)")
    check("설치 0 (지문은 대문자로 줘도 된다)", code == 0, (code, so[-1500:], se[-1500:]))
    if code != 0:
        return
    check("current 링크 → releases/<버전> (상대 링크)", os.path.islink(b.cur) and b.current() == f"releases/{V1}", b.current())
    check("releases 에는 그 버전 하나 (임시 폴더 없음)", b.releases() == [V1], b.releases())
    check("/opt/autopilot 은 root 0755", owner(b.opt) == (0, 0) and mode(b.opt) == 0o755, (owner(b.opt), oct(mode(b.opt))))
    rel = os.path.join(b.rel, V1)
    check("프로그램 파일은 root 소유, 남·그룹 쓰기 없음",
          all(owner(os.path.join(d, n))[0] == 0 and not (mode(os.path.join(d, n)) & 0o022)
              for d, ds, ns in os.walk(rel) for n in ns if not os.path.islink(os.path.join(d, n))))
    check("설정 폴더 /etc/autopilot 은 root:<서비스 그룹> 0750", owner(b.etc) == (0, SVC_GID) and mode(b.etc) == 0o750,
          (owner(b.etc), oct(mode(b.etc))))
    sj = os.path.join(b.etc, "server.json")
    check("server.json 은 root:<서비스 그룹> 0640", owner(sj) == (0, SVC_GID) and mode(sj) == 0o640, (owner(sj), oct(mode(sj))))
    cfg = json.loads(read(sj))
    check("server.json 은 인자로 (listen·allow)", cfg.get("listen") == "127.0.0.1" and cfg.get("allow") == ["127.0.0.0/8"], cfg)
    ca = os.path.join(b.etc, "ca")
    check("인증 기관 폴더 ca/ 는 root 0700, 열쇠가 있다", owner(ca)[0] == 0 and mode(ca) == 0o700
          and os.path.isfile(os.path.join(ca, "ca_key.pem")), (owner(ca), oct(mode(ca))))
    check("자료 폴더는 서비스 계정 0700", owner(b.data) == (SVC_UID, SVC_GID) and mode(b.data) == 0o700, (owner(b.data), oct(mode(b.data))))
    check("기록 폴더는 서비스 계정 0700", owner(b.logs)[0] == SVC_UID and mode(b.logs) == 0o700)
    check("설정 백업 폴더는 root 0700", owner(b.bkp)[0] == 0 and mode(b.bkp) == 0o700)
    key = os.path.realpath(os.path.join(b.data, "tls", "current", "server_key.pem"))
    cacert = os.path.join(b.data, "tls", "ca_cert.pem")
    check("서버 인증서 열쇠는 서비스 계정 0600, 인증 기관 공개 인증서 사본도 서비스 계정",
          os.path.isfile(key) and owner(key)[0] == SVC_UID and mode(key) == 0o600 and owner(cacert)[0] == SVC_UID, key)
    check("자료 폴더에 인증 기관 열쇠는 없다", not [n for d, ds, ns in os.walk(b.data) for n in ns if n == "ca_key.pem"])
    req = os.path.join(b.data, "server_request.json")
    sk = os.path.join(b.data, "seat.key")
    check("라이선스 요청 파일·자리 서명 열쇠는 서비스 계정 0600", os.path.isfile(req) and owner(req)[0] == SVC_UID and mode(req) == 0o600
          and owner(sk)[0] == SVC_UID and mode(sk) == 0o600)
    doc = json.loads(read(req))
    check("요청 파일에 서버 번호·자리 공개 열쇠·버전 (비밀 값 없음)", set(doc) == {"server_id", "seat_pub", "version", "made"}
          and doc["version"] == V1 and doc["server_id"] == license_check.server_id(), doc)
    check("끝 안내: 요청 파일 자리와 'install.sh activate'", req.replace(b.p, "") in so or req in so, so[-800:])
    check("끝 안내: 공급사에 보내 라이선스를 받은 뒤", "공급사" in so and "install.sh activate" in so, so[-800:])
    check("시간대가 UTC 면 추천 글 (바꾸지는 않는다)", "timedatectl set-timezone Asia/Seoul" in so, so[-800:])
    check("서비스는 켜지 않았다 (run.json 없음, --no-systemd 라 systemctl 도 부르지 않음)",
          not os.path.exists(os.path.join(b.data, "run.json")) and "systemctl" not in b.fake_log(), b.fake_log())
    for u in UNITS:
        p = os.path.join(b.units, u)
        check(f"단위 파일 {u} 0644", os.path.isfile(p) and mode(p) == 0o644)
    check("실행 글 /usr/local/sbin/autopilot-server (시험 자리 사본, 0755)", os.path.isfile(b.ap) and mode(b.ap) == 0o755)
    pyc = os.path.join(rel, "app", "__pycache__")
    check("app/__pycache__ 는 설치가 미리 만들고 root 소유", os.path.isdir(pyc) and owner(pyc)[0] == 0
          and all(owner(os.path.join(pyc, n))[0] == 0 for n in os.listdir(pyc)) and len(os.listdir(pyc)) >= 10,
          os.listdir(pyc) if os.path.isdir(pyc) else "없음")
    # Review Focus 5 - 서비스 계정은 프로그램 폴더를 쓸 수 없고 인증 기관 열쇠를 읽지 못한다 (진짜 nobody 로)
    c1, o1 = b.as_nobody(["sh", "-c", f"echo x > '{os.path.join(rel, 'app', 'evil.py')}'"])
    c2, o2 = b.as_nobody(["cat", os.path.join(ca, "ca_key.pem")])
    c3, o3 = b.as_nobody(["cat", sj])
    c4, o4 = b.as_nobody(["sh", "-c", f"ln -sfn /tmp '{b.cur}'"])
    check("서비스 계정은 프로그램 폴더에 쓰지 못한다", c1 != 0 and not os.path.exists(os.path.join(rel, "app", "evil.py")), o1)
    check("서비스 계정은 current 링크를 바꾸지 못한다", c4 != 0 and b.current() == f"releases/{V1}", o4)
    check("서비스 계정은 인증 기관 열쇠를 읽지 못한다", c2 != 0 and "PRIVATE KEY" not in o2, o2[:200])
    check("서비스 계정은 server.json 을 읽는다 (그룹)", c3 == 0 and "127.0.0.1" in o3, o3[:200])
    code, so, se = b.install(V1)
    check("이미 깔린 자리에 다시 install 하면 1 (업그레이드 안내), 그대로", code != 0 and "autopilot-server upgrade" in se
          and b.current() == f"releases/{V1}", (code, se))


def test_unit_files():
    b = MAIN.get("b")
    src = os.path.join(ROOT, "server", "autopilot.service")
    t = read(src)
    need = ["User=autopilotd", "ExecStart=/usr/local/sbin/autopilot-server run", "Restart=on-failure", "RestartSec=5",
            "RestartPreventExitStatus=2 4", "ProtectSystem=strict", "ReadWritePaths=/var/lib/autopilot /var/log/autopilot",
            "ProtectHome=yes", "PrivateTmp=yes", "NoNewPrivileges=yes", "RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX",
            "IPAddressDeny=any", "IPAddressAllow=@ALLOW@ 127.0.0.1/32 ::1/128", "UMask=0077"]
    lines = [ln.strip() for ln in t.splitlines()]
    check("autopilot.service 원본에 보호 설정 줄이 모두", all(n in lines for n in need), [n for n in need if n not in lines])
    settings = [ln for ln in lines if ln and not ln.startswith("#")]
    check("autopilot.service 에 ExecReload(SIGUSR1) 없음 - SIGUSR1 은 백업", not any(ln.startswith("ExecReload") for ln in settings))
    check("autopilot.service 는 Group 을 적지 않는다 (서비스 계정의 기본 그룹)", not any(ln.startswith("Group=") for ln in settings))
    cert = read(os.path.join(ROOT, "server", "autopilot-cert.service"))
    check("인증서 단위: cert --renew --if-expiring 30 --owner autopilotd, 10 일 때만 try-restart (systemd 의 $$ 이스케이프)",
          "cert --renew --if-expiring 30 --owner autopilotd" in cert and "try-restart autopilot" in cert and "$$rc" in cert
          and "-eq 10" in cert, cert)
    for tm in ("autopilot-cert.timer", "autopilot-config-backup.timer"):
        x = read(os.path.join(ROOT, "server", tm))
        check(f"{tm}: 주 1회·Persistent·timers.target", "OnCalendar=weekly" in x and "Persistent=true" in x and "WantedBy=timers.target" in x, x)
    cb = read(os.path.join(ROOT, "server", "autopilot-config-backup.service"))
    check("설정 백업 단위: root 로 autopilot-server backup-config", "ExecStart=/usr/local/sbin/autopilot-server backup-config" in cb
          and "User=" not in cb, cb)
    ng = read(os.path.join(ROOT, "server", "nginx-example.conf"))
    check("nginx 예시: proxy_set_header X-Autopilot-Proxy <proxy_secret> (평문 모양) 과 TLS 다시 잇기 모양",
          "proxy_set_header X-Autopilot-Proxy" in ng and "proxy_pass https://" in ng and "proxy_pass http://127.0.0.1" in ng, ng[:300])
    if not b:
        check("설치된 단위 파일 (설치 실패로 건너뜀)", False)
        return
    got = read(os.path.join(b.units, "autopilot.service"))
    check("설치된 autopilot.service: 허용 대역을 채웠다 (@ALLOW@ 없음)", "IPAddressAllow=127.0.0.0/8 127.0.0.1/32 ::1/128" in got
          and "@ALLOW@" not in got, [ln for ln in got.splitlines() if "IPAddress" in ln])
    check("설치된 단위의 서비스 계정 (시험은 nobody)", "User=nobody" in got and "--owner nobody" in read(os.path.join(b.units, "autopilot-cert.service")))
    sa = shutil.which("systemd-analyze")
    if not sa:
        print("  [건너뜀] systemd-analyze 가 없다")
        return
    d = os.path.join(T, "units_verify")
    os.makedirs(d, exist_ok=True)
    for u in UNITS:
        shutil.copyfile(os.path.join(b.units, u), os.path.join(d, u))
    r = subprocess.run([sa, "verify", "--man=no"] + [os.path.join(d, u) for u in UNITS], capture_output=True, timeout=120)
    out = (r.stdout + r.stderr).decode("utf-8", "replace")
    # 실행 파일이 이 WSL 에 없다는 말(/usr/local/sbin/autopilot-server)은 넘긴다 - 단위 글의 꼴 오류만 본다
    bad = [ln for ln in out.splitlines() if any(w in ln for w in ("Unknown key", "Unknown lvalue", "Failed to parse", "Invalid",
                                                                    "Unknown section", "bad-setting", "Missing '='"))]
    check("systemd-analyze verify: 모르는 설정·꼴 오류 없음", not bad, out[-1500:])


def test_launcher_imports():
    b = MAIN.get("b")
    if not b:
        check("실행 글 (설치 실패로 건너뜀)", False)
        return
    rel = os.path.join(b.rel, V1)
    pyc = os.path.join(rel, "app", "__pycache__")
    before = sorted(os.listdir(pyc))
    code, so, se = b.ap_run(["--help"])
    check("설치된 autopilot-server --help 가 실제로 돈다 (0, 하위 명령 목록)", code == 0 and "upgrade" in so and "admin-reset" in so,
          (code, so[-500:], se[-800:]))
    code, so, se = b.ap_run([])
    check("인자 없으면 도움말과 1", code == 1 and "autopilot-server" in so, (code, se))
    check("root 로 돈 명령이 프로그램 폴더에 .pyc 를 쓰지 않는다 (-B)", sorted(os.listdir(pyc)) == before)
    r = subprocess.run([os.path.join(rel, "python", "bin", "python3"), "-I", "-B", os.path.join(rel, "server", "install_helper.py"),
                        "verify-tree", rel, V1], capture_output=True, timeout=300)
    check("설치·관리 명령을 돈 뒤에도 버전 폴더가 버전 목록과 같다 (런타임 .pyc 포함)", r.returncode == 0,
          r.stderr.decode("utf-8", "replace")[-600:])
    # 실행 글의 python 줄 그대로, 마지막만 sys.path 를 찍게 바꾼 사본 - releases 폴더가 검색 경로에 없다 (Task 8 넘김)
    text = read(b.ap)
    probe = text.replace("import server_main; sys.exit(server_main.main(sys.argv[1:]))", "import server_main; print(repr(sys.path))")
    check("실행 글의 python 줄 모양 (-I -B, app/ 를 직접 넣음)", probe != text and " -I -B -c " in text, text[-400:])
    pp = os.path.join(T, "launcher_probe")
    with open(pp, "w", encoding="utf-8", newline="\n") as f:
        f.write(probe)
    os.chmod(pp, 0o755)
    r = subprocess.run([pp], capture_output=True, timeout=60, env=b.env(), cwd=T)
    out = r.stdout.decode("utf-8", "replace").strip()
    try:
        paths = eval(out.splitlines()[-1], {"__builtins__": {}})        # noqa: S307 - 우리가 만든 repr 한 줄
    except Exception:
        paths = None
    relreal = os.path.realpath(b.rel)
    check("sys.path 에 releases 폴더(app/../..)가 없다", isinstance(paths, list)
          and not any(os.path.realpath(p) == relreal for p in paths if p), (out, r.stderr.decode("utf-8", "replace")[-500:]))
    check("sys.path 의 app/ 는 실제 자리 (current 링크를 풀었다 - 업그레이드 중 섞이지 않게)",
          isinstance(paths, list) and os.path.join(rel, "app") in paths and not any("/current/" in (p or "") + "/" for p in paths), paths)
    check("sys.path 에 현재 폴더('')가 없다 (-I)", isinstance(paths, list) and "" not in paths, paths)
    # 시험용 빌드 띠 - 서버에는 edition 모듈이 없다, manifest 의 test_build 로 (Task 8 넘김)
    py = os.path.join(b.cur, "python", "bin", "python3")
    r = subprocess.run([py, "-I", "-B", "-c", "import sys; sys.path.insert(0, sys.argv[1]); import local_web; "
                        "sys.stdout.write(local_web.edition_js().decode())", os.path.join(b.cur, "app")], capture_output=True, timeout=60)
    js = r.stdout.decode("utf-8", "replace")
    check("--test-key 묶음의 서버 웹 edition.js 는 TEST_BUILD = true (시험용 빌드 띠)", "TEST_BUILD = true;" in js,
          (js, r.stderr.decode("utf-8", "replace")[-500:]))
    # 휴대폰 페어링 - 묶음에 local_phone 이 없다, 500 이 아니라 404 (Task 8 넘김)
    script = os.path.join(T, "phone404.py")
    with open(script, "w", encoding="utf-8") as f:
        f.write(PHONE404)
    r = subprocess.run([py, "-I", "-B", script, os.path.join(b.cur, "app")], capture_output=True, timeout=120, cwd=T)
    out = r.stdout.decode("utf-8", "replace").strip()
    try:
        got = json.loads(out.splitlines()[-1])
    except (ValueError, IndexError):
        got = {}
    check("서버 묶음에서 휴대폰 페어링 요청은 404 ('이 서버에서는 휴대폰 페어링을 쓰지 않습니다')",
          got.get("status") == 404 and "휴대폰 페어링을 쓰지 않습니다" in str(got.get("body")) and got.get("local_phone") is False,
          (out[-600:], r.stderr.decode("utf-8", "replace")[-800:]))


PHONE404 = r'''
import json, os, sys, tempfile, threading, urllib.error, urllib.request
sys.path.insert(0, sys.argv[1])
import local_server, local_web, pc_registry
folder = tempfile.mkdtemp()
with open(os.path.join(folder, "security.json"), "w", encoding="utf-8") as f:
    f.write('{"version":1,"totp_scope":"off","show_own_history":true}')
LIC = {"edition": "standalone", "company": "시험상사", "cid": "c1", "pc_id": "srv", "issued": "2026-11-25", "modules": {},
       "features": {}, "limits": {}}
store = local_server.Store(os.path.join(folder, "store.json"), volatile=local_server.VOLATILE)
runs = local_server.Runs(":memory:")
reg = pc_registry.Registry(os.path.join(folder, "pcs.json"), seats=5)
web = local_web.Web(store, runs, LIC, folder, None, registry=reg)
web.accounts.set("boss", "pw-1234567890", "admin")
srv = local_server.make_server(store, runs, LIC, None, port=0, folder=folder, web=web, registry=reg)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d" % srv.server_address[1]
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
def call(method, path, body=None, token=None):
    hs = {"Content-Type": "application/json"}
    if token:
        hs["Authorization"] = "Bearer " + token
    req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(), method=method, headers=hs)
    try:
        with op.open(req, timeout=15) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")
st, body = call("POST", "/api/login", {"id": "boss", "password": "pw-1234567890"})
tok = json.loads(body).get("token") if st == 200 else None
st, body = call("POST", "/api/phone-pair", {"label": "김 휴대폰"}, tok)
srv.shutdown()
print(json.dumps({"status": st, "body": body, "login": bool(tok), "local_phone": "local_phone" in sys.modules}, ensure_ascii=False))
'''


def test_activate():
    b = MAIN.get("b")
    if not b:
        check("활성화 (설치 실패로 건너뜀)", False)
        return
    b.set_ports()
    path, digest, bdir = bundle(V1)
    lic = os.path.join(b.etc, "license.json")
    other = license_for(b, server_id="0" * 32)
    code, so, se = b.sh(bdir, ["activate", other, "--root", b.p, "--service-user", "nobody"])
    check("다른 서버의 라이선스는 넣지 않는다 (1, 서버 번호 안내)", code != 0 and "서버 번호" in se and not os.path.exists(lic), (code, se))
    wrong_seat = license_for(b, seat_pub="ab" * 32)
    code, so, se = b.sh(bdir, ["activate", wrong_seat, "--root", b.p, "--service-user", "nobody"])
    check("자리 서명 열쇠가 다른 라이선스도 넣지 않는다", code != 0 and "자리" in se and not os.path.exists(lic), (code, se))
    check("틀린 라이선스에서는 서비스를 켜지 않았다", "systemctl" not in b.fake_log(), b.fake_log())
    good = license_for(b)
    t0 = time.time()
    code, so, se = b.sh(bdir, ["activate", good, "--root", b.p, "--service-user", "nobody"])
    print(f"    (활성화 {time.time() - t0:.1f}초)")
    check("시험 라이선스로 활성화 0", code == 0, (code, so[-1500:], se[-1500:], read(os.path.join(b.state, "service.out"))[-800:]))
    check("license.json 은 root:<서비스 그룹> 0640", os.path.isfile(lic) and owner(lic) == (0, SVC_GID) and mode(lic) == 0o640,
          (owner(lic), oct(mode(lic))) if os.path.exists(lic) else "없음")
    log = b.fake_log()
    check("daemon-reload 뒤 enable 과 restart (타이머 둘도 enable --now)", "systemctl daemon-reload" in log
          and "systemctl enable autopilot.service" in log and "systemctl restart autopilot.service" in log
          and "autopilot-cert.timer" in log and "autopilot-config-backup.timer" in log, log)
    ver, pid = b.running()
    check("도는 서비스가 알리는 버전이 설치된 버전", ver == V1, (ver, read(os.path.join(b.state, "service.out"))[-800:]))
    check("관리자 계정이 없으면 멈춘 뒤 admin-reset --create 안내", "admin-reset admin --create" in so and "systemctl stop autopilot" in so, so[-800:])
    run_json = os.path.join(b.data, "run.json")
    check("run.json 은 서비스 계정 0600", os.path.isfile(run_json) and owner(run_json)[0] == SVC_UID and mode(run_json) == 0o600)
    # 관리자 계정 - 서비스를 멈춘 뒤 root 로 admin-reset (권한을 내려 쓰므로 계정 파일은 서비스 계정 소유)
    code, so, se = b.ap_run(["admin-reset", "admin", "--create", "--password-stdin", "--user", "nobody"], stdin=BOSS_PW + "\n")
    check("서비스가 돌면 admin-reset 은 1 (멈춘 뒤)", code == 1 and "systemctl stop autopilot" in se, (code, se))
    b.systemctl("stop", "autopilot.service")
    code, so, se = b.ap_run(["admin-reset", "admin", "--create", "--password-stdin", "--user", "nobody"], stdin=BOSS_PW + "\n")
    acc = os.path.join(b.data, "accounts.json")
    check("멈춘 뒤 admin-reset --create 0, accounts.json 은 서비스 계정 0600",
          code == 0 and owner(acc)[0] == SVC_UID and mode(acc) == 0o600, (code, so, se))
    b.systemctl("start", "autopilot.service")
    check("다시 켜면 같은 버전", b.wait_running(V1), b.running())
    MAIN["active"] = True


def test_cert_default_owner():
    """root 로 cert --renew·--import-web 을 --owner 없이 쳐도 서비스 계정(nobody) 소유 - 서비스(진짜 nobody)가 다시 켜진다
    (Codex 중간 검토 5, 서로 다른 UID)."""
    b = MAIN.get("b")
    if not MAIN.get("active"):
        check("인증서 기본 소유자 (활성화 실패로 건너뜀)", False)
        return
    code, so, se = b.ap_run(["cert", "--renew"])
    check("root 로 cert --renew (--owner 없음) 0", code == 0, (code, se))
    key = os.path.realpath(os.path.join(b.data, "tls", "current", "server_key.pem"))
    check("새 서버 열쇠·인증 기관 사본은 서비스 계정 소유", owner(key)[0] == SVC_UID
          and owner(os.path.join(b.data, "tls", "ca_cert.pem"))[0] == SVC_UID, (owner(key), key))
    b.systemctl("restart", "autopilot.service")
    check("새 인증서로 서비스가 다시 켜진다 (서비스 계정이 읽는다)", b.wait_running(V1), read(os.path.join(b.state, "service.out"))[-600:])
    sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
    import lan_ca
    co_ca, co_out = os.path.join(T, "co_ca"), os.path.join(T, "co_out")
    lan_ca.make_ca(co_ca, [], ["127.0.0.1"])
    cert, ckey = lan_ca.issue_server(co_ca, co_out, [], ["127.0.0.1"])
    code, so, se = b.ap_run(["cert", "--import-web", cert, ckey])
    wkey = os.path.realpath(os.path.join(b.data, "tls-web", "current", "server_key.pem"))
    check("root 로 cert --import-web (--owner 없음) 0, 서비스 계정 소유", code == 0 and os.path.isfile(wkey) and owner(wkey)[0] == SVC_UID,
          (code, se))
    b.systemctl("restart", "autopilot.service")
    check("업체 인증서를 넣은 뒤에도 서비스가 켜진다", b.wait_running(V1), read(os.path.join(b.state, "service.out"))[-600:])
    code, so, se = b.ap_run(["status", "--json"])
    check("웹 인증서는 업체 것", (json.loads(so or "{}").get("certs") or {}).get("web", {}).get("source") == "imported", so[-400:])


def test_request_no_follow():
    """설치된 실행 글로 root 가 request 를 칠 때 자료 폴더의 seat.key 가 root 전용 열쇠 파일로 가는 링크·하드링크면 그 열쇠를 읽지
    않고 대상의 소유자·모드를 바꾸지 않는다 (Task 8.6 - 서비스 계정은 자료 폴더 안 이름을 바꿔 둘 수 있다)."""
    b = MAIN.get("b")
    if not b:
        check("request 링크 (설치 실패로 건너뜀)", False)
        return
    sk = os.path.join(b.data, "seat.key")
    req = os.path.join(b.data, "server_request.json")
    aside = sk + ".keep"
    victim = os.path.join(T, "request_victim.key")
    other = os.urandom(32).hex()
    with open(victim, "w", encoding="ascii") as f:
        f.write(other + "\n")
    os.chmod(victim, 0o600)
    before, vst = read(req), os.stat(victim)
    os.rename(sk, aside)
    try:
        for kind in ("symlink", "hardlink"):
            (os.symlink if kind == "symlink" else os.link)(victim, sk)
            try:
                code, so, se = b.ap_run(["request", "--user", "nobody"])
            finally:
                os.remove(sk)
            now = os.stat(victim)
            check(f"seat.key 가 root 열쇠 파일로 가는 {kind} 면 request 1, 요청 파일 그대로", code == 1 and read(req) == before
                  and "seat.key" in se, (code, so, se))
            check(f"{kind}: 대상은 root 0600 그대로", (now.st_uid, stat.S_IMODE(now.st_mode)) == (vst.st_uid, 0o600), now)
    finally:
        os.rename(aside, sk)
    code, so, se = b.ap_run(["request", "--user", "nobody"])
    check("제자리 seat.key 면 request 0, seat.key·요청 파일은 서비스 계정 0600", code == 0 and owner(sk)[0] == SVC_UID
          and owner(req)[0] == SVC_UID and mode(req) == 0o600 and mode(sk) == 0o600, (code, se, owner(sk), owner(req)))


def upgrade(b, ver, env=None):
    path = bundle(ver)[0] if ver in BUNDLES else None
    t0 = time.time()
    code, so, se = b.ap_run(["upgrade", path], env=env)
    print(f"    (업그레이드 {ver} {time.time() - t0:.1f}초, 종료 {code})")
    return code, so, se


def snapshot(b):
    return {"server.json": read(os.path.join(b.etc, "server.json"), True), "license.json": read(os.path.join(b.etc, "license.json"), True),
            "units": {u: read(os.path.join(b.units, u), True) for u in UNITS}, "backups": b.backups(), "current": b.current(),
            "running": b.running(), "releases": b.releases()}


def test_upgrade_keeps_config_and_restarts():
    b = MAIN.get("b")
    if not MAIN.get("active"):
        check("업그레이드 (활성화 실패로 건너뜀)", False)
        return
    bundle(V2)
    before = snapshot(b)
    open(b.log, "w").close()
    code, so, se = upgrade(b, V2)
    check("업그레이드 0", code == 0, (code, so[-1500:], se[-1500:]))
    check("current → releases/<새 버전>", b.current() == f"releases/{V2}", b.current())
    ver, pid = b.running()
    check("도는 프로세스가 알리는 버전이 새 버전 (restart 로 바꿨다)", ver == V2 and pid != before["running"][1], (ver, pid, before["running"]))
    log = b.fake_log()
    check("systemctl restart autopilot (enable --now 가 아니다)", "systemctl restart autopilot.service" in log
          and "enable --now autopilot.service" not in log, log)
    check("server.json·license.json 그대로", snapshot(b)["server.json"] == before["server.json"]
          and snapshot(b)["license.json"] == before["license.json"])
    check("업그레이드 앞에 백업 하나", len(b.backups()) == len(before["backups"]) + 1, (before["backups"], b.backups()))
    check("옛 버전은 releases 에 남는다 (되돌리기 자리)", b.releases() == sorted([V1, V2]), b.releases())
    check("풀었던 임시 자리·단위 사본이 남지 않는다", not [n for n in os.listdir(b.opt) if n.startswith(".")], os.listdir(b.opt))
    check("서명 확인 → 업그레이드 시작 글", f"서명 확인됨  버전={V2}" in so, so[:400])


def test_install_fails_clean():
    b = MAIN.get("b")
    if not MAIN.get("active"):
        check("반쯤 깔림 (활성화 실패로 건너뜀)", False)
        return
    bundle(V3, bad_manifest=True)
    before = snapshot(b)
    code, so, se = upgrade(b, V3)
    check("manifest 지문 하나가 틀린 묶음 → 실패 (지문)", code != 0 and "지문" in se, (code, se[-1200:]))
    check("releases 에 새 폴더 없음 (임시 폴더도)", b.releases() == before["releases"], b.releases())
    check("current 그대로", b.current() == before["current"], b.current())
    check("서비스는 건드리지 않았다 (같은 pid)", b.running() == before["running"], (b.running(), before["running"]))
    check("단위 파일 그대로", snapshot(b)["units"] == before["units"])
    # 서명이 틀린 묶음은 풀리지도 않는다 (Task 4 - 깔린 도구가 먼저 본다)
    path = bundle(V3)[0]
    raw = bytearray(read(path, True))
    raw[len(raw) // 3] ^= 1
    bad = os.path.join(T, "tampered", os.path.basename(path))
    os.makedirs(os.path.dirname(bad), exist_ok=True)
    with open(bad, "wb") as f:
        f.write(raw)
    shutil.copyfile(path + ".sig", bad + ".sig")
    code, so, se = b.ap_run(["upgrade", bad])
    check("서명이 틀린 파일은 1, 아무것도 풀지 않는다", code == 1 and "서명" in se and not [n for n in os.listdir(b.opt) if n.startswith(".")]
          and b.releases() == before["releases"], (code, se))


def test_interrupt_after_link():
    b = MAIN.get("b")
    if not MAIN.get("active"):
        check("링크 뒤 끊김 (활성화 실패로 건너뜀)", False)
        return
    bundle(V5)
    before = snapshot(b)
    open(b.log, "w").close()
    code, so, se = upgrade(b, V5, env=b.env(AP_TEST_DIE_AFTER_LINK=1))
    check("링크를 바꾼 다음 줄에서 끊기면 실패로 끝난다", code != 0, (code, se[-800:]))
    check("current 는 옛 버전으로 되돌아간다", b.current() == before["current"], b.current())
    check("되돌린 뒤 옛 버전을 다시 켰다 (restart)", "systemctl restart autopilot.service" in b.fake_log() and b.wait_running(V2),
          (b.fake_log(), b.running()))
    check("새 버전 폴더는 지운다", V5 not in b.releases() and b.releases() == before["releases"], b.releases())
    check("단위 파일은 옛 것으로 되돌린다", snapshot(b)["units"] == before["units"])
    check("실행 글도 옛 버전을 가리킨다", f"releases/{V5}" not in read(b.ap) and b.ap_run(["--help"])[0] == 0)


def test_interrupt_in_units_backup():
    """단위 파일 사본을 만드는 도중에 끊기면 원래 단위 파일을 하나도 지우지 않는다 (Codex 중간 검토 6)."""
    b = MAIN.get("b")
    if not MAIN.get("active"):
        check("단위 사본 중 끊김 (활성화 실패로 건너뜀)", False)
        return
    bundle(V8)
    before = snapshot(b)
    code, so, se = upgrade(b, V8, env=b.env(AP_TEST_DIE_IN_UNITS_BACKUP=1))
    check("단위 파일 사본을 만드는 도중 끊기면 실패로 끝난다", code != 0, (code, se[-600:]))
    now = snapshot(b)
    check("원래 단위 파일이 모두 그대로 (지운 것 없음)", now["units"] == before["units"],
          [u for u in UNITS if now["units"][u] != before["units"][u]])
    check("current·releases·서비스 그대로", now["current"] == before["current"] and now["releases"] == before["releases"]
          and now["running"] == before["running"], (now["current"], now["releases"], now["running"]))
    check("반쯤 만든 사본 자리가 남지 않는다", not [n for n in os.listdir(b.opt) if n.startswith(".")], os.listdir(b.opt))


def test_restore_link_fails():
    """링크를 되돌리지 못하면 current 가 가리키는 새 버전 폴더와 단위 사본을 지우지 않고 손으로 할 일을 적는다 (Codex 중간 검토 7)."""
    b = MAIN.get("b")
    if not MAIN.get("active"):
        check("링크 되돌리기 실패 (활성화 실패로 건너뜀)", False)
        return
    bundle(V8)
    before = snapshot(b)
    code, so, se = upgrade(b, V8, env=b.env(AP_TEST_DIE_AFTER_LINK=1, AP_TEST_FAIL_RESTORE_LINK=1))
    saved = os.path.join(b.opt, f".units-before-{V8}")
    check("링크 뒤 끊김 + 되돌리기 실패 → 실패로 끝난다", code != 0, (code, se[-600:]))
    check("current 는 새 버전을 가리킨 채 끊어지지 않았다 (가리키는 폴더를 지우지 않음)", b.current() == f"releases/{V8}"
          and os.path.isdir(b.cur), (b.current(), b.releases()))
    check("단위 파일 사본(복구 자료)을 지우지 않는다", os.path.isdir(saved) and all(
        read(os.path.join(saved, u), True) == before["units"][u] for u in UNITS), os.listdir(b.opt))
    check("손으로 할 일을 적는다 (current 를 옛 버전으로·단위 사본 자리)", "손으로" in se and before["current"] in se and saved in se,
          se[-1200:])
    # 시험 자리를 손으로 되돌린다 (안내대로)
    tmp = os.path.join(b.opt, ".fix")
    os.symlink(before["current"], tmp)
    os.replace(tmp, b.cur)
    for u in UNITS:
        shutil.copyfile(os.path.join(saved, u), os.path.join(b.units, u))
    shutil.rmtree(saved)
    shutil.rmtree(os.path.join(b.rel, V8), ignore_errors=True)
    check("손으로 되돌린 뒤 옛 버전이 돈다", b.wait_running(V2) and snapshot(b)["units"] == before["units"], b.running())


def test_upgrade_rollback():
    b = MAIN.get("b")
    if not MAIN.get("active"):
        check("되돌리기 (활성화 실패로 건너뜀)", False)
        return
    bundle(V4, norun=True)
    before = snapshot(b)
    code, so, se = upgrade(b, V4, env=b.env(AP_START_WAIT=5))
    check(f"새 버전이 run.json 을 쓰지 않으면 실패 (되돌림 안내)", code != 0 and "되돌" in se, (code, so[-600:], se[-1200:]))
    check("current 는 옛 버전", b.current() == before["current"], b.current())
    check("옛 버전이 다시 돈다", b.wait_running(V2), b.running())
    check("켜지지 않은 새 버전 폴더는 지운다", V4 not in b.releases(), b.releases())


def test_refuse_format_downgrade():
    b = MAIN.get("b")
    if not MAIN.get("active"):
        check("형식 번호 (활성화 실패로 건너뜀)", False)
        return
    bundle(V6)
    fmt = os.path.join(b.data, "FORMAT")
    old = read(fmt)
    with open(fmt, "w", encoding="ascii") as f:                # 같은 파일에 덮어써 소유자·모드 그대로
        f.write("2\n")
    before = snapshot(b)
    try:
        code, so, se = upgrade(b, V6)
    finally:
        with open(fmt, "w", encoding="ascii") as f:
            f.write(old)
    check("자료 형식 번호가 새 버전이 아는 것보다 크면 거절", code != 0 and "형식" in se, (code, se[-800:]))
    check("거절하면 아무것도 바꾸지 않는다 (current·releases·백업 수·서비스)",
          b.current() == before["current"] and b.releases() == before["releases"] and b.backups() == before["backups"]
          and b.running() == before["running"], (b.current(), b.releases(), b.backups()))


def test_prune_releases():
    b = MAIN.get("b")
    if not MAIN.get("active"):
        check("옛 버전 정리 (활성화 실패로 건너뜀)", False)
        return
    code, so, se = upgrade(b, V6)
    check("다시 업그레이드 0", code == 0 and b.wait_running(V6), (code, se[-800:]))
    bundle(V7)
    code, so, se = upgrade(b, V7)
    check("세 번째 업그레이드 0", code == 0 and b.wait_running(V7), (code, se[-800:]))
    check("releases 에는 최근 셋만 (가장 옛 것을 지움)", b.releases() == sorted([V2, V6, V7]), b.releases())


def test_firewall():
    b = box("fw", ufw=True)
    path, digest, bdir = bundle(V1)
    base = ["install", "--expect-sha256", digest, "--listen", "192.168.77.5", "--allow", "192.168.77.0/24,10.20.0.0/16",
            "--root", b.p, "--service-user", "nobody", "--no-systemd"]
    code, so, se = b.sh(bdir, base)
    log = b.fake_log()
    check("방화벽 규칙을 보여 준다 (포트 8443·8444, 대역)", code == 0 and "8443" in so and "8444" in so and "192.168.77.0/24" in so, (code, so[-800:], se[-800:]))
    check("--apply-firewall 없이는 넣지 않는다", "ufw allow" not in log, log)
    b2 = box("fw2", ufw=True)
    code, so, se = b2.sh(bdir, base[:base.index("--root") + 1] + [b2.p] + base[base.index("--root") + 2:] + ["--apply-firewall"])
    log = b2.fake_log()
    rules = [ln for ln in log.splitlines() if ln.startswith("ufw allow")]
    check("--apply-firewall 이면 ufw 에 대역마다 한 줄 (tcp 8443,8444)",
          code == 0 and len(rules) == 2 and all("proto tcp" in r and "port 8443,8444" in r for r in rules)
          and any("192.168.77.0/24" in r for r in rules) and any("10.20.0.0/16" in r for r in rules), (log, se[-500:]))
    got = read(os.path.join(b2.units, "autopilot.service"))
    check("autopilot.service 의 IPAddressAllow 에 두 대역", "IPAddressAllow=192.168.77.0/24 10.20.0.0/16 127.0.0.1/32 ::1/128" in got,
          [ln for ln in got.splitlines() if "IPAddressAllow" in ln])


def main():
    global REAL_RUNTIME
    if len(sys.argv) > 2 and sys.argv[1] == "--real-runtime":
        REAL_RUNTIME = sys.argv[2]
        print(f"진짜 내장 파이썬 묶음: {os.path.basename(REAL_RUNTIME)}")
        tests = [test_install_uses_verified_copy, test_fresh_install_layout, test_launcher_imports, test_activate,
                 test_cert_default_owner, test_request_no_follow, test_upgrade_keeps_config_and_restarts, test_upgrade_rollback,
                 test_interrupt_after_link]
    else:
        print("install.sh 와 systemd 단위 (wsl_install, 가짜 런타임)")
        tests = [test_expect_sha256, test_preflight, test_account_rules, test_install_uses_verified_copy, test_fresh_install_layout,
                 test_unit_files, test_launcher_imports, test_activate, test_cert_default_owner, test_request_no_follow,
                 test_upgrade_keeps_config_and_restarts, test_install_fails_clean, test_interrupt_after_link,
                 test_interrupt_in_units_backup, test_restore_link_fails, test_upgrade_rollback, test_refuse_format_downgrade,
                 test_prune_releases, test_firewall]
    only = [n for n in os.environ.get("WSL_INSTALL_ONLY", "").split(",") if n]      # 고르기 (고치기 전 확인 등)
    if only:
        tests = [t for t in tests if t.__name__ in only]
    try:
        for t in tests:
            print(t.__name__)
            try:
                t()
            except Exception:
                traceback.print_exc()
                check(t.__name__, False, "예외")
    finally:
        for b in BOXES:
            b.cleanup()
        shutil.rmtree(T, ignore_errors=True)
    print(f"\n실패: {len(fails)}" + (f" ({', '.join(fails)})" if fails else ""))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
