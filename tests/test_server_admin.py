# -*- coding: utf-8 -*-
"""사내 서버 ④ Task 4 - 관리 명령 (계획 2026-11-25-lan-4-linux Task 4).
request(요청 파일), status(도는 프로세스의 버전·문제면 1), cert(--show·--renew 하루 앞당긴 인증서·--import-web 업체 웹 인증서),
lan_ca.replace_pair(쌍으로 갈아 끼우기), admin-reset(서비스가 멈춰야, 잠금 → 권한 내리기 → 쓰기), verify·upgrade(서명 먼저).
root 가 필요한 길은 server_main._euid·_service_ids·_drop_privileges 를 바꿔 끼워 흉내 낸다 (WSL 은 root 로 돌지만 실제로 권한을
내리지 않는다). 서명은 시험 열쇠만 쓴다. 윈도우·WSL 둘 다 (WSL 의 임시 폴더는 /tmp 아래).
    D:/AX/RPA/.venv/Scripts/python.exe tests/test_server_admin.py
    wsl.exe -d Ubuntu -e python3 /mnt/d/AX/RPA_StandAlone/tests/test_server_admin.py
"""
import contextlib
import datetime
import io
import json
import os
import secrets
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import traceback

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
POSIX = os.name == "posix"

import lan_ca  # noqa: E402
import license_check  # noqa: E402
import local_web  # noqa: E402
import seat  # noqa: E402
import server_log  # noqa: E402
import totp  # noqa: E402
import update_sign  # noqa: E402

fails = []
try:
    import server_main  # noqa: E402
except ImportError as e:
    print(f"  [실패] server_main 을 불러오지 못한다 - {e}")
    print("\n실패: 1")
    sys.exit(1)

SERVICE = lambda: 1000                                     # noqa: E731  서비스 계정 흉내 (WSL 은 root 로 돈다)
ROOT_EUID = lambda: 0                                      # noqa: E731
server_main._euid = SERVICE
REAL_IDS, REAL_DROP = server_main._service_ids, server_main._drop_privileges
TMP = tempfile.mkdtemp(prefix="rpa_server_admin_", dir="/tmp" if POSIX else None)
LIC_SECRET, LIC_PUBLIC = update_sign.keygen()             # 시험 라이선스 열쇠
UPD_SECRET, UPD_PUBLIC = update_sign.keygen()             # 시험 업데이트 서명 열쇠
BOSS_PW = "pw-1234567890"
ENV_KEYS = ("AUTOPILOT_ETC", "AUTOPILOT_DATA", "AUTOPILOT_LOGS")
CA_DIR, CERT_DIR = os.path.join(TMP, "ca"), os.path.join(TMP, "cert")
lan_ca.make_ca(CA_DIR, [], ["127.0.0.1"])
CERT, KEY = lan_ca.issue_server(CA_DIR, CERT_DIR, [], ["127.0.0.1"])
CA_PEM = lan_ca.ca_pem(CA_DIR)


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


def until(fn, sec):
    end = time.time() + sec
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.05)
    return bool(fn())


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


def call(argv, stdin=None):
    """server_main.main(argv) → (종료 코드, 표준 출력, 표준 오류)."""
    out, err = io.StringIO(), io.StringIO()
    old_in = sys.stdin
    if stdin is not None:
        sys.stdin = io.StringIO(stdin)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = server_main.main(argv)
    finally:
        sys.stdin = old_in
    return code, out.getvalue(), err.getvalue()


class Env:
    def __init__(self, name, tls=True, admin=True, seats=3):
        base = os.path.join(TMP, name)
        self.etc, self.data, self.logs = (os.path.join(base, n) for n in ("etc", "data", "logs"))
        for d in (self.etc, self.data, self.logs):
            os.makedirs(d)
        for k, v in zip(ENV_KEYS, (self.etc, self.data, self.logs)):
            os.environ[k] = v
        self.paths = server_main.Paths()
        self.machine_id = os.path.join(base, "machine-id")
        with open(self.machine_id, "w", encoding="ascii") as f:
            f.write(secrets.token_hex(16) + "\n")
        server_main.MACHINE_ID = self.machine_id
        server_main.LICENSE_PUBLIC_KEY = LIC_PUBLIC.hex()
        self.server_id = license_check.server_id(self.machine_id)
        self.web_port, self.agent_port, phone = free_ports(3)
        with open(self.paths.server_json, "w", encoding="utf-8") as f:
            json.dump({"listen": "127.0.0.1", "names": [], "allow": ["127.0.0.0/8"],
                       "ports": {"web": self.web_port, "agent": self.agent_port, "phone": phone}}, f)
        self.secret, self.pub = seat.ensure_key(self.data)
        body = {"edition": "standalone", "kind": "server", "company": "시험상사", "cid": "c1", "server_id": self.server_id,
                "seat_pub": self.pub, "seats": seats, "issued": "2026-11-25", "modules": {}, "features": {}, "limits": {}}
        with open(self.paths.license, "w", encoding="utf-8") as f:
            json.dump(license_check.sign_body(LIC_SECRET, body), f, ensure_ascii=False)
        if tls:
            for src, dst in ((CERT, self.paths.tls_cert), (KEY, self.paths.tls_key),
                             (os.path.join(CA_DIR, lan_ca.CA_CERT), self.paths.tls_ca)):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copyfile(src, dst)
        fd = os.open(os.path.join(self.data, "security.json"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write('{"version":1,"totp_scope":"off","show_own_history":true}')
        self.accounts = os.path.join(self.data, local_web.ACCOUNTS_NAME)
        if admin:
            acc = local_web.Accounts(self.accounts)
            acc.admin_min = 10
            acc.set("boss", BOSS_PW, "admin")
        self.result, self.thread = [], None

    def start(self):
        self.thread = threading.Thread(target=lambda: self.result.append(server_main.main(["run"])), daemon=True)
        self.thread.start()
        until(lambda: os.path.isfile(self.paths.run_json) or not self.thread.is_alive(), 30)
        return os.path.isfile(self.paths.run_json)

    def stop(self):
        server_main.stop()
        if self.thread is not None:
            self.thread.join(20)
        return self.result[0] if self.result else None


def guard(name, fn):
    print(name)
    try:
        fn()
    except Exception as ex:
        check(f"{name} - 예외 없이 끝난다", False, f"{type(ex).__name__}: {ex}\n{traceback.format_exc()[-1500:]}")
    finally:
        try:
            server_main.stop()
        except Exception:
            pass
        server_log.configure(None, None)
        server_main._euid = SERVICE
        server_main._service_ids, server_main._drop_privileges = REAL_IDS, REAL_DROP
        server_main.MACHINE_ID = license_check.MACHINE_ID
        server_main.LICENSE_PUBLIC_KEY = server_main.UPDATE_PUBLIC_KEY = None
        lan_ca.FORCE_CA_STARTDATE = False


def fake_root():
    """root 흉내: euid 0, 서비스 계정 번호는 지금 계정(윈도우는 None), 권한 내리기는 기록만."""
    events = []
    server_main._euid = ROOT_EUID
    server_main._service_ids = lambda user: (1000, 1000) if POSIX else None
    server_main._drop_privileges = lambda ids: events.append(("drop", ids))
    return events


def cert_dates(path):
    out = lan_ca._run(None, ["x509", "-in", path, "-noout", "-startdate", "-enddate"])
    got = dict(line.split("=", 1) for line in out.strip().splitlines())
    return ssl.cert_time_to_seconds(got["notBefore"].strip()), ssl.cert_time_to_seconds(got["notAfter"].strip())


# ----------------------------------------------------------------------------------------------------

def test_request_file():
    e = Env("request")
    out = os.path.join(TMP, "request", "req.json")
    code, so, _ = call(["request", "-o", out])
    doc = json.loads(read(out) or "{}")
    check("request -o → 0, 경로를 출력", code == 0 and out in so, (code, so))
    check("요청 파일 = {server_id, seat_pub, version, made}", set(doc) == {"server_id", "seat_pub", "version", "made"}, doc)
    check("server_id·seat_pub 이 이 서버의 것", doc.get("server_id") == e.server_id and doc.get("seat_pub") == e.pub, doc)
    check("요청 파일에 자리 서명 비밀 값이 없다", e.secret.hex() not in read(out))
    os.remove(os.path.join(e.data, seat.SEAT_KEY))
    code, so, _ = call(["request"])
    dflt = os.path.join(e.data, "server_request.json")
    doc = json.loads(read(dflt) or "{}")
    check("-o 없으면 자료 폴더의 server_request.json, 자리 열쇠가 없으면 만든다",
          code == 0 and os.path.isfile(os.path.join(e.data, seat.SEAT_KEY)) and doc.get("seat_pub") not in (None, e.pub), (code, so))
    # 등록된 PC 가 있는데 자리 열쇠가 없으면 새로 만들지 않는다 (run 의 종료 코드 4 와 같은 규칙)
    os.remove(os.path.join(e.data, seat.SEAT_KEY))
    with open(e.paths.pcs, "w", encoding="utf-8") as f:
        json.dump({"v": 1, "next": 2, "pcs": {"pc_01": {"label": "a", "agent_key": "k", "relay_key": "r", "state": "active"}}}, f)
    code, so, se = call(["request"])
    check("등록된 PC 가 있고 seat.key 가 없으면 1, 새 열쇠를 만들지 않는다",
          code == 1 and not os.path.exists(os.path.join(e.data, seat.SEAT_KEY)) and "백업" in se, (code, se))


def test_status_ok_and_problems():
    e = Env("status")
    check("서버를 켰다", e.start(), e.result)
    try:
        code, so, _ = call(["status", "--json"])
        st = json.loads(so or "{}")
        check("돌고 있으면 status 0", code == 0, (code, st.get("problems")))
        check("도는 프로세스의 버전·pid (run.json + 잠금)", st.get("running") is True and st.get("running_version") == server_main.version()
              and st.get("pid") == os.getpid(), st)
        check("설치된 버전·서버 번호", st.get("installed_version") == server_main.version() and st.get("server_id") == e.server_id, st)
        lic = st.get("license") or {}
        check("라이선스(업체·자리 수·등록된 PC 수)", lic.get("company") == "시험상사" and lic.get("seats") == 3 and lic.get("pcs") == 0, lic)
        certs = st.get("certs") or {}
        check("인증서 만료까지 남은 날 (에이전트·웹)", certs.get("agent", {}).get("days_left", 0) > 300
              and certs.get("web", {}).get("days_left", 0) > 300 and certs.get("web", {}).get("source") == "ours", certs)
        check("디스크 남은 공간·마지막 백업 칸", isinstance(st.get("disk_free_mb"), int) and "last_backup" in st, st)
        code, so, _ = call(["status"])
        check("글 출력에 '실행 중'", code == 0 and "실행 중" in so, so)
    finally:
        e.stop()
    # 죽은 pid 의 run.json
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    with open(e.paths.run_json, "w", encoding="utf-8") as f:
        json.dump({"version": server_main.version(), "pid": p.pid, "started": "2026-11-25T00:00:00", "format": 1}, f)
    code, so, _ = call(["status"])
    check("run.json 의 pid 가 죽었으면 '실행 중 아님' 과 1", code == 1 and "실행 중 아님" in so, (code, so))
    code, so, _ = call(["status", "--json"])
    st = json.loads(so or "{}")
    check("--json 에도 running False 와 문제 목록", st.get("running") is False and st.get("problems"), st)
    # pid 는 살아 있어도 잠금이 없으면 실행 중이 아니다 (pid 를 다른 프로세스가 다시 받은 경우)
    with open(e.paths.run_json, "w", encoding="utf-8") as f:
        json.dump({"version": "x", "pid": os.getpid(), "started": "2026-11-25T00:00:00", "format": 1}, f)
    code, so, _ = call(["status", "--json"])
    check("pid 가 살아 있어도 잠금이 안 잡혀 있으면 실행 중 아님", json.loads(so or "{}").get("running") is False, so)


def test_admin_reset_needs_stopped():
    e = Env("reset_busy")
    fake_root()
    before = read(e.accounts)
    held = server_main.ServiceLock(e.paths.lock)
    check("다른 쪽(서비스)이 잠금을 쥐었다", held.try_hold())
    try:
        code, so, se = call(["admin-reset", "boss", "--password-stdin"], stdin="new-password-123\n")
    finally:
        held.release()
    check("서비스가 돌고 있으면(잠금) 1", code == 1, (code, se))
    check("안내 'systemctl stop autopilot 뒤 다시 실행하여 주십시오'", "systemctl stop autopilot 뒤 다시 실행하여 주십시오" in se, se)
    check("계정 파일은 그대로", read(e.accounts) == before)


def test_admin_reset_owner():
    e = Env("reset_owner")
    events = fake_root()
    before = read(e.accounts)
    seen = {}

    def drop(ids):
        events.append(("drop", ids))
        seen["locked"] = server_main.ServiceLock.held(e.paths.lock)
        seen["untouched"] = read(e.accounts) == before
    server_main._drop_privileges = drop
    code, so, se = call(["admin-reset", "boss", "--password-stdin"], stdin="new-password-123\n")
    check("admin-reset 0", code == 0, (code, se))
    check("권한 내리기를 서비스 계정 번호로 한 번 부른다", [x for x in events if x[0] == "drop"] == [("drop", (1000, 1000) if POSIX else None)],
          events)
    check("순서: 잠금을 쥔 뒤 권한을 내린다 (내릴 때 잠금이 잡혀 있다)", seen.get("locked") is True, seen)
    check("순서: 권한을 내린 뒤에 계정 파일을 쓴다 (내릴 때는 그대로)", seen.get("untouched") is True and read(e.accounts) != before, seen)
    check("끝나면 잠금을 놓는다", server_main.ServiceLock.held(e.paths.lock) is False)
    if POSIX:
        check("root 가 새로 만든 잠금 파일은 서비스 계정 소유로 (서비스가 다시 잡을 수 있게)", os.stat(e.paths.lock).st_uid == 1000,
              os.stat(e.paths.lock).st_uid)
    server_main._euid = SERVICE
    code, so, se = call(["admin-reset", "boss", "--password-stdin"], stdin="new-password-123\n")
    check("root 가 아니면 1", code == 1 and "root" in se, (code, se))


def test_admin_reset():
    e = Env("reset")
    fake_root()
    before = read(e.accounts)
    code, so, se = call(["admin-reset", "boss", "--password-stdin"], stdin="short-pw\n")
    check("관리자 비밀번호 10자 미만은 거절 (1, 파일 그대로)", code == 1 and read(e.accounts) == before and "10자" in se, (code, se))
    pw = "brand-new-pw-42"
    code, so, se = call(["admin-reset", "boss", "--password-stdin"], stdin=pw + "\n")
    acc = local_web.Accounts(e.accounts)
    got = acc.verify("boss", pw)
    check("바꾸면 새 비밀번호로 확인되고 must_change", code == 0 and got is not None and got["must_change"] is True
          and got["role"] == "admin", (code, se, got))
    # 2단계를 켠 뒤 --clear-2fa
    secret = totp.new_secret()
    now = time.time()
    acc.mfa_enable("boss", secret, totp.code_at(secret, totp.step_of(now)), now)
    check("2단계 켬 (준비)", acc.mfa_info("boss")["enabled"] is True)
    code, so, se = call(["admin-reset", "boss", "--clear-2fa"])
    check("--clear-2fa 뒤 2단계 꺼짐, 비밀번호는 그대로", code == 0 and local_web.Accounts(e.accounts).mfa_info("boss")["enabled"] is False
          and local_web.Accounts(e.accounts).verify("boss", pw) is not None, (code, se))
    code, so, se = call(["admin-reset", "nobody", "--password-stdin"], stdin="another-pw-123\n")
    check("없는 계정은 --create 없이 1", code == 1 and local_web.Accounts(e.accounts).get("nobody") is None, (code, se))
    code, so, se = call(["admin-reset", "admin", "--create", "--password-stdin"], stdin="first-admin-pw\n")
    a = local_web.Accounts(e.accounts).verify("admin", "first-admin-pw")
    check("--create 면 관리자로 만든다 (must_change)", code == 0 and a is not None and a["role"] == "admin" and a["must_change"], (code, se, a))
    audit = read(e.paths.audit_log)
    check("audit.log 에 admin-reset 줄 (아이디)", "admin-reset" in audit and "아이디=boss" in audit and "아이디=admin" in audit, audit[-400:])
    check("기록에 비밀번호가 없다", all(x not in audit + read(e.paths.server_log) for x in (pw, "first-admin-pw", "short-pw")))
    if POSIX:
        check("audit.log 0600", mode(e.paths.audit_log) == 0o600)


def make_bundle(folder, ver, install_sh="#!/bin/sh\necho ran \"$@\" > \"$MARK\"\n", kind="server", key=UPD_SECRET, extra=None):
    """가짜 서버 설치 파일 (tar.gz) 과 .sig (시험 열쇠)."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"AUTOPILOT_Server_{ver}_linux-x86_64.tar.gz")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        def add(name, data, mode=0o644):
            ti = tarfile.TarInfo(name)
            ti.size, ti.mode = len(data), mode
            tf.addfile(ti, io.BytesIO(data))
        top = f"autopilot-server-{ver}"
        add(f"{top}/manifest.json", json.dumps({"version": ver, "edition": "standalone", "kind": kind, "files": {}}).encode())
        add(f"{top}/server/install.sh", install_sh.encode(), 0o755)
        for name, data in (extra or {}).items():
            add(name, data)
    raw = buf.getvalue()
    with open(path, "wb") as f:
        f.write(raw)
    with open(path + ".sig", "w", encoding="ascii") as f:
        f.write(update_sign.sign(key, raw).hex() + "\n")
    return path


def test_verify():
    Env("verify")
    server_main.UPDATE_PUBLIC_KEY = UPD_PUBLIC
    path = make_bundle(os.path.join(TMP, "verify", "b"), "2026.11.25-1")
    code, so, se = call(["verify", path])
    check("시험 열쇠로 서명한 파일 → 0, '서명 확인됨  버전=…'", code == 0 and "서명 확인됨  버전=2026.11.25-1" in so, (code, so, se))
    code, so, se = call(["verify", path, "--sig", path + ".sig"])
    check("--sig 로 서명 파일을 따로 줘도 0", code == 0, (code, se))
    with open(path, "rb") as f:
        raw = bytearray(f.read())
    raw[len(raw) // 2] ^= 1
    bad = path.replace(".tar.gz", "_bad.tar.gz")
    with open(bad, "wb") as f:
        f.write(raw)
    shutil.copyfile(path + ".sig", bad + ".sig")
    code, so, se = call(["verify", bad])
    check("한 바이트 바꾸면 1", code == 1 and "서명 확인됨" not in so, (code, so, se))
    code, so, se = call(["verify", os.path.join(TMP, "verify", "none.tar.gz")])
    check("없는 파일은 1", code == 1)
    other = make_bundle(os.path.join(TMP, "verify", "o"), "2026.11.25-2", key=update_sign.keygen()[0])
    check("다른 열쇠로 서명한 파일은 1", call(["verify", other])[0] == 1)
    pc = make_bundle(os.path.join(TMP, "verify", "p"), "2026.11.25-3", kind="pc")
    check("서버 설치 파일이 아니면(kind pc) 1", call(["verify", pc])[0] == 1)


def test_upgrade_verifies_first():
    Env("upgrade")
    events = fake_root()
    server_main.UPDATE_PUBLIC_KEY = UPD_PUBLIC
    work = os.path.join(TMP, "upgrade", "work")
    os.makedirs(work)
    server_main.UPGRADE_TMP = work
    mark = os.path.join(TMP, "upgrade", "ran.txt")
    os.environ["MARK"] = mark
    path = make_bundle(os.path.join(TMP, "upgrade", "b"), "2026.11.25-5")
    with open(path + ".sig", "w", encoding="ascii") as f:
        f.write(update_sign.sign(update_sign.keygen()[0], b"x").hex())
    code, so, se = call(["upgrade", path])
    check("서명이 틀린 파일 → 1", code == 1, (code, se))
    check("서명이 틀리면 임시 자리에도 풀지 않는다", os.listdir(work) == [] and not os.path.exists(mark), os.listdir(work))
    evil = make_bundle(os.path.join(TMP, "upgrade", "e"), "2026.11.25-6", extra={"../evil.txt": b"x"})
    code, so, se = call(["upgrade", evil])
    check("서명은 맞아도 압축 안 이름이 정해진 꼴이 아니면 1, 아무것도 남기지 않는다",
          code == 1 and os.listdir(work) == [] and not os.path.exists(os.path.join(TMP, "upgrade", "evil.txt")), (code, se))
    server_main._euid = SERVICE
    good = make_bundle(os.path.join(TMP, "upgrade", "g"), "2026.11.25-7")
    check("root 가 아니면 1", call(["upgrade", good])[0] == 1)
    if not POSIX:
        print("  [건너뜀] install.sh 실행은 리눅스(WSL)에서만")
        return
    server_main._euid = ROOT_EUID
    code, so, se = call(["upgrade", good])
    check("서명이 맞으면 풀어 install.sh upgrade --verified-version <확인한 버전> 을 실행한다 (시험 자리 인자 없음)",
          code == 0 and read(mark).strip() == "ran upgrade --verified-version 2026.11.25-7", (code, se, read(mark)))
    # 시험 자리(install.sh --root 로 깐 서버의 실행 글이 AUTOPILOT_ROOT·AUTOPILOT_SERVICE_USER 를 싣는다) - 풀 자리도 그 아래
    troot = os.path.join(TMP, "upgrade", "troot")
    os.makedirs(os.path.join(troot, "opt", "autopilot"))
    os.environ.update(AUTOPILOT_ROOT=troot, AUTOPILOT_SERVICE_USER="nobody", AUTOPILOT_NO_SYSTEMD="1")
    server_main.UPGRADE_TMP = "/opt/autopilot"
    try:
        code, so, se = call(["upgrade", good])
    finally:
        for k in ("AUTOPILOT_ROOT", "AUTOPILOT_SERVICE_USER", "AUTOPILOT_NO_SYSTEMD"):
            os.environ.pop(k, None)
        server_main.UPGRADE_TMP = work
    check("시험 자리면 --root·--service-user·--no-systemd 를 넘긴다",
          code == 0 and read(mark).strip() == f"ran upgrade --verified-version 2026.11.25-7 --root {troot} --service-user nobody --no-systemd",
          (code, se, read(mark)))
    check("시험 자리면 <root>/opt/autopilot 아래에 풀고 지운다", os.listdir(os.path.join(troot, "opt", "autopilot")) == [],
          os.listdir(os.path.join(troot, "opt", "autopilot")))
    check("끝나면 임시 자리를 지운다", os.listdir(work) == [], os.listdir(work))
    check("권한 내리기는 부르지 않는다 (root 로 설치)", not events, events)


def test_cert_root_only():
    Env("cert_root")
    code, so, se = call(["cert", "--renew"])
    check("root 가 아니면 cert --renew 는 1", code == 1 and "root" in se, (code, se))
    code, so, se = call(["cert", "--import-web", CERT, KEY])
    check("root 가 아니면 cert --import-web 도 1", code == 1, (code, se))


def renew_and_check(label, force_ca_path):
    e = Env(label, tls=False)
    fake_root()
    lan_ca.FORCE_CA_STARTDATE = force_ca_path
    used, real_ca_sign = [], lan_ca._ca_sign
    lan_ca._ca_sign = lambda *a: (used.append("ca -startdate"), real_ca_sign(*a))
    t0 = time.time()
    try:
        code, so, se = call(["cert", "--renew", "--owner", "autopilotd"])
    finally:
        lan_ca._ca_sign = real_ca_sign
    check(f"[{label}] cert --renew 0", code == 0, (code, so, se))
    native = lan_ca._x509_not_before(None)
    want = ["ca -startdate"] if force_ca_path or not native else []
    check(f"[{label}] 서명 길: {'openssl ca -startdate' if want else 'x509 -not_before'} "
          f"({lan_ca._run(None, ['version']).split()[1]}{', 모르는 척' if force_ca_path else ''})", used == want, used)
    if code != 0:
        return e
    nb, na = cert_dates(e.paths.tls_cert)
    check(f"[{label}] notBefore 가 지금보다 23시간 넘게 앞 (하루 앞당김)", t0 - nb > 23 * 3600, (t0 - nb) / 3600)
    check(f"[{label}] notAfter 는 지금부터 397일 안팎 (전체 기간 398일 이하)", abs((na - t0) / 86400 - 397) < 1 and (na - nb) / 86400 <= 398.01,
          ((na - t0) / 86400, (na - nb) / 86400))
    check(f"[{label}] 인증 기관을 설정 폴더 ca/ 에 만들고, 공개 인증서만 tls/ 에 사본",
          os.path.isfile(os.path.join(e.paths.ca_dir, lan_ca.CA_KEY)) and os.path.isfile(e.paths.tls_ca)
          and not os.path.exists(os.path.join(e.paths.tls_dir, lan_ca.CA_KEY)))
    v = lan_ca._run(None, ["verify", "-CAfile", e.paths.tls_ca, e.paths.tls_cert])
    check(f"[{label}] 새 인증서가 인증 기관으로 확인된다", "OK" in v, v)
    if POSIX:
        check(f"[{label}] 서버 열쇠 0600·인증 기관 폴더 0700", mode(e.paths.tls_key) == 0o600 and mode(e.paths.ca_dir) == 0o700)
        check(f"[{label}] 서버 인증서 쌍은 서비스 계정 소유 (--owner)", os.stat(os.path.realpath(e.paths.tls_key)).st_uid == 1000
              and os.stat(e.paths.tls_ca).st_uid == 1000)
    return e


def test_cert_renew_backdated():
    renew_and_check("cert_native", False)
    renew_and_check("cert_ca_path", True)
    e = renew_and_check("cert_twice", False)
    first = read(e.paths.tls_cert)
    ca_first = read(os.path.join(e.paths.ca_dir, lan_ca.CA_CERT))
    code, so, se = call(["cert", "--renew", "--days", "30"])
    nb, na = cert_dates(e.paths.tls_cert)
    check("다시 renew 하면 새 인증서, 인증 기관은 그대로 (PC 를 다시 등록하지 않게)", code == 0 and read(e.paths.tls_cert) != first
          and read(os.path.join(e.paths.ca_dir, lan_ca.CA_CERT)) == ca_first and abs((na - time.time()) / 86400 - 30) < 1, (code, se))
    check("--days 398 은 1", call(["cert", "--renew", "--days", "398"])[0] == 1)
    code, so, se = call(["cert", "--show"])
    check("cert --show 에 에이전트 인증서 만료일", code == 0 and "에이전트" in so and "남은 날" in so, (code, so, se))
    server_main._euid = SERVICE
    check("서비스 계정으로 renew 한 인증서로 서버가 켜진다", e.start(), (e.result, read(e.paths.server_log)[-300:]))
    e.stop()


def test_cert_if_expiring():
    """인증서 타이머 (autopilot-cert.service): --if-expiring N 은 남은 날이 N 일 넘으면 그대로 0, 아니면 새로 만들고 10
    (10 일 때만 타이머가 systemctl try-restart autopilot)."""
    e = Env("cert_expiring", tls=False)
    fake_root()
    code, so, se = call(["cert", "--renew", "--if-expiring", "30", "--owner", "autopilotd"])
    check("인증서가 없으면 새로 만들고 10", code == server_main.EXIT_RENEWED == 10 and os.path.isfile(e.paths.tls_cert), (code, so, se))
    first = read(e.paths.tls_cert)
    code, so, se = call(["cert", "--renew", "--if-expiring", "30"])
    check("397일 남은 인증서는 그대로 두고 0", code == 0 and read(e.paths.tls_cert) == first and "새로 만들지 않았습니다" in so, (code, so, se))
    code, so, se = call(["cert", "--renew", "--days", "20"])
    check("--if-expiring 없는 renew 는 0 (지금 그대로)", code == 0, (code, se))
    second = read(e.paths.tls_cert)
    code, so, se = call(["cert", "--renew", "--if-expiring", "30"])
    check("20일 남은 인증서는 새로 만들고 10", code == 10 and read(e.paths.tls_cert) != second, (code, so, se))
    check("--if-expiring 은 --renew 와만 (--show 와 함께면 1)", call(["cert", "--show", "--if-expiring", "30"])[0] == 1)
    check("--if-expiring 음수는 1", call(["cert", "--renew", "--if-expiring", "-1"])[0] == 1)
    server_main._euid = SERVICE
    check("root 가 아니면 1 (10 이 아니다)", call(["cert", "--renew", "--if-expiring", "30"])[0] == 1)


def tls_peer(port, cafile_pem):
    ctx = ssl.create_default_context(cadata=cafile_pem)
    with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
        with ctx.wrap_socket(s, server_hostname="127.0.0.1") as t:
            return t.getpeercert(binary_form=True)


def test_import_web_cert():
    e = Env("import_web")
    co_ca, co_out = os.path.join(TMP, "co_ca"), os.path.join(TMP, "co_cert")       # 업체 사내 인증 기관 흉내
    lan_ca.make_ca(co_ca, [], ["127.0.0.1"])
    co_cert, co_key = lan_ca.issue_server(co_ca, co_out, [], ["127.0.0.1"])
    co_pem = lan_ca.ca_pem(co_ca)
    fake_root()
    code, so, se = call(["cert", "--import-web", co_cert, co_key, "--chain", os.path.join(co_ca, lan_ca.CA_CERT)])
    check("cert --import-web 0", code == 0, (code, so, se))
    check("업체 인증서는 web_tls_dir 에 (쌍)", os.path.isfile(e.paths.web_cert) and os.path.isfile(e.paths.web_key))
    code, so, se = call(["cert", "--import-web", co_cert, KEY])
    check("인증서와 열쇠가 짝이 아니면 1, 넣은 것은 그대로", code == 1 and read(e.paths.web_key) == read(co_key), (code, se))
    server_main._euid = SERVICE
    check("서버가 켜진다", e.start(), e.result)
    try:
        want_web = ssl.PEM_cert_to_DER_cert(read(co_cert).split("-----END CERTIFICATE-----")[0] + "-----END CERTIFICATE-----\n")
        want_agent = ssl.PEM_cert_to_DER_cert(read(CERT))
        check("8443(웹) 은 업체 인증서", tls_peer(e.web_port, co_pem) == want_web)
        check("8444(에이전트) 는 늘 우리 인증서", tls_peer(e.agent_port, CA_PEM) == want_agent)
        code, so, _ = call(["status", "--json"])
        check("status 의 웹 인증서는 업체 것", (json.loads(so or "{}").get("certs") or {}).get("web", {}).get("source") == "imported", so)
    finally:
        e.stop()


def test_replace_pair_atomic():
    d = os.path.join(TMP, "pair")
    cur = lan_ca.replace_pair(d, "CERT-1\n", "KEY-1\n")
    check("replace_pair → current 폴더에 두 파일", read(os.path.join(cur, lan_ca.SERVER_CERT)) == "CERT-1\n"
          and read(os.path.join(cur, lan_ca.SERVER_KEY)) == "KEY-1\n" and cur == os.path.join(d, lan_ca.CURRENT), cur)
    if POSIX:
        check("열쇠 0600", mode(os.path.join(cur, lan_ca.SERVER_KEY)) == 0o600)
    real = lan_ca._switch

    def die(folder, name, **kw):
        raise KeyboardInterrupt("갈아 끼우는 중 죽음 흉내")
    lan_ca._switch = die
    try:
        lan_ca.replace_pair(d, "CERT-2\n", "KEY-2\n")
        died = False
    except KeyboardInterrupt:
        died = True
    finally:
        lan_ca._switch = real
    check("죽은 흉내 뒤에도 이전 쌍이 그대로 읽힌다", died and read(os.path.join(d, lan_ca.CURRENT, lan_ca.SERVER_CERT)) == "CERT-1\n"
          and read(os.path.join(d, lan_ca.CURRENT, lan_ca.SERVER_KEY)) == "KEY-1\n")
    lan_ca.replace_pair(d, "CERT-3\n", "KEY-3\n")
    check("다음 갈아 끼우기는 새 쌍", read(os.path.join(d, lan_ca.CURRENT, lan_ca.SERVER_CERT)) == "CERT-3\n"
          and read(os.path.join(d, lan_ca.CURRENT, lan_ca.SERVER_KEY)) == "KEY-3\n")
    left = [n for n in os.listdir(d) if n != lan_ca.CURRENT and not (POSIX and os.path.realpath(os.path.join(d, n)) ==
                                                                   os.path.realpath(os.path.join(d, lan_ca.CURRENT)))]
    check("옛 쌍·반쯤 만든 쌍은 남지 않는다", not left, os.listdir(d))
    # 예전 꼴(current 가 진짜 폴더)에서도 갈아 끼운다
    d2 = os.path.join(TMP, "pair_legacy", lan_ca.CURRENT)
    os.makedirs(d2)
    with open(os.path.join(d2, lan_ca.SERVER_CERT), "w") as f:
        f.write("OLD")
    lan_ca.replace_pair(os.path.dirname(d2), "CERT-N\n", "KEY-N\n")
    check("current 가 진짜 폴더였어도 갈아 끼운다", read(os.path.join(d2, lan_ca.SERVER_CERT)) == "CERT-N\n")


REAL_ROOT = POSIX and os.geteuid() == 0                     # WSL 은 root - 진짜 소유자 바꾸기·링크로 확인한다


def victim_file(name):
    """root 소유 '남의 파일' 흉내 (/etc/shadow 대신) → 경로."""
    p = os.path.join(TMP, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write("secret\n")
    os.chmod(p, 0o600)
    return p


def same_file(p, st):
    now = os.stat(p)
    return (now.st_uid, now.st_gid, stat.S_IMODE(now.st_mode)) == (st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode)) and read(p) == "secret\n"


def test_lock_no_follow():
    """잠금 파일(.service.lock)이 링크·하드링크면 root 명령이 그 대상을 서비스 계정 소유로 바꾸지 않는다 (Codex 중간 검토 2)."""
    if not REAL_ROOT:
        print("  [건너뜀] 링크·소유자 확인은 리눅스 root(WSL)에서만")
        return
    e = Env("lock_link")
    victim = victim_file("lock_victim")
    st = os.stat(victim)
    os.symlink(victim, e.paths.lock)
    lock = server_main.ServiceLock(e.paths.lock)
    try:
        got = lock.try_hold(owner=(1000, 1000))
        lock.release()
        err = None
    except OSError as ex:
        got, err = None, str(ex)
    check("잠금 파일이 다른 파일로 가는 링크면 try_hold 가 OSError (알아듣는 글)", got is None and bool(err) and "잠금" in err, (got, err))
    check("링크 대상 파일의 소유자·모드·내용 그대로", same_file(victim, st), os.stat(victim))
    check("held() 도 링크를 따라가지 않는다 (None)", server_main.ServiceLock.held(e.paths.lock) is None)
    fake_root()
    code, so, se = call(["admin-reset", "boss", "--password-stdin"], stdin="new-password-123\n")
    check("admin-reset 도 1, 대상 그대로", code == 1 and same_file(victim, st), (code, se, os.stat(victim)))
    code, so, se = call(["backup"])
    check("backup 도 1, 대상 그대로", code == 1 and same_file(victim, st), (code, se, os.stat(victim)))
    os.remove(e.paths.lock)
    os.link(victim, e.paths.lock)                                     # 하드링크 (nlink 2)
    try:
        server_main.ServiceLock(e.paths.lock).try_hold(owner=(1000, 1000))
        err = None
    except OSError as ex:
        err = str(ex)
    check("하드링크(nlink 2) 잠금 파일도 거절", bool(err), err)
    check("하드링크 대상 그대로", same_file(victim, st), os.stat(victim))
    os.remove(e.paths.lock)
    os.mkdir(e.paths.lock)
    try:
        server_main.ServiceLock(e.paths.lock).try_hold()
        err = None
    except OSError as ex:
        err = str(ex)
    check("잠금 자리가 폴더면 거절", bool(err), err)
    os.rmdir(e.paths.lock)
    lock = server_main.ServiceLock(e.paths.lock)
    check("보통 잠금 파일은 그대로 잡힌다 (root 가 만들면 서비스 계정 소유로)", lock.try_hold(owner=(1000, 1000))
          and os.stat(e.paths.lock).st_uid == 1000)
    lock.release()


def test_cert_no_follow():
    """인증서 갱신·업체 인증서 넣기가 자료 폴더의 tls·tls-web 링크를 따라가지 않는다 (Codex 중간 검토 3)."""
    if not REAL_ROOT:
        print("  [건너뜀] 링크·소유자 확인은 리눅스 root(WSL)에서만")
        return
    e = Env("cert_link", tls=False)
    fake_root()
    victim = os.path.join(TMP, "cert_victim")                       # /etc/autopilot/ca 같은 root 전용 폴더 흉내
    os.makedirs(victim, mode=0o700)
    with open(os.path.join(victim, "ca_key.pem"), "w") as f:
        f.write("KEY")
    vst = os.stat(victim)
    os.symlink(victim, e.paths.tls_dir)
    code, so, se = call(["cert", "--renew", "--owner", "autopilotd"])
    check("data/tls 가 다른 폴더로 가는 링크면 cert --renew 는 1", code == 1, (code, so, se))
    check("링크 대상 폴더의 소유자·모드·내용 그대로", os.stat(victim).st_uid == vst.st_uid and stat.S_IMODE(os.stat(victim).st_mode) == 0o700
          and sorted(os.listdir(victim)) == ["ca_key.pem"], (os.stat(victim), os.listdir(victim)))
    code, so, se = call(["cert", "--renew"])
    check("--owner 없이도 1, 대상 그대로", code == 1 and sorted(os.listdir(victim)) == ["ca_key.pem"]
          and os.stat(victim).st_uid == vst.st_uid, (code, se))
    os.remove(e.paths.tls_dir)
    with open(e.paths.tls_dir, "w") as f:
        f.write("x")
    code, so, se = call(["cert", "--renew"])
    check("data/tls 가 보통 파일이면 1 (바꾸지 않음)", code == 1 and read(e.paths.tls_dir) == "x", (code, se))
    os.remove(e.paths.tls_dir)
    # 업체 웹 인증서 자리
    os.symlink(victim, e.paths.web_tls_dir)
    code, so, se = call(["cert", "--import-web", CERT, KEY])
    check("data/tls-web 이 링크면 --import-web 은 1, 대상 그대로", code == 1 and sorted(os.listdir(victim)) == ["ca_key.pem"]
          and os.stat(victim).st_uid == vst.st_uid, (code, se))
    os.remove(e.paths.web_tls_dir)
    # 발급은 자료 폴더 밖 root 전용 자리에서
    seen, real_issue = [], lan_ca.issue_server
    lan_ca.issue_server = lambda ca_dir, out_dir, *a, **k: (seen.append((out_dir, stat.S_IMODE(os.stat(out_dir).st_mode)
                                                                         if os.path.isdir(out_dir) else None,
                                                                         stat.S_IMODE(os.stat(os.path.dirname(out_dir)).st_mode))),
                                                            real_issue(ca_dir, out_dir, *a, **k))[1]
    try:
        code, so, se = call(["cert", "--renew"])
    finally:
        lan_ca.issue_server = real_issue
    data_real = os.path.realpath(e.data)
    check("링크가 없으면 renew 0", code == 0, (code, se))
    check("발급 작업 자리는 자료 폴더 밖, root 전용(0700) 임시 폴더 안", len(seen) == 1
          and not os.path.realpath(seen[0][0]).startswith(data_real + os.sep) and seen[0][1] == 0o700, seen)
    check("자료 폴더에 발급 임시 폴더가 남지 않는다", not [n for n in os.listdir(e.paths.tls_dir) if n.startswith(".")], os.listdir(e.paths.tls_dir))
    check("tls 폴더·쌍·인증 기관 사본은 서비스 계정 소유", os.stat(e.paths.tls_dir).st_uid == 1000
          and os.stat(os.path.realpath(e.paths.tls_key)).st_uid == 1000 and os.stat(e.paths.tls_ca).st_uid == 1000
          and mode(e.paths.tls_ca) == 0o600)
    # tls 폴더가 남(다른 계정) 소유면 거절
    os.chown(e.paths.tls_dir, 4242, 4242)
    code, so, se = call(["cert", "--renew"])
    check("tls 폴더가 서비스 계정·root 가 아닌 계정 소유면 1", code == 1, (code, se))


def test_cert_default_owner():
    """root 로 cert --renew·--import-web 을 --owner 없이 치면 서비스 계정 소유 (Codex 중간 검토 5 - 같은 UID 시험의 빈틈)."""
    e = Env("cert_owner", tls=False)
    fake_root()
    asked = []
    server_main._service_ids = lambda user: (asked.append(user), (1000, 1000) if POSIX else None)[1]
    code, so, se = call(["cert", "--renew"])
    check("--owner 없이 root 로 renew 0", code == 0, (code, se))
    check("기본 서비스 계정 autopilotd 를 찾는다", asked == ["autopilotd"], asked)
    if REAL_ROOT:
        check("--owner 없어도 서버 열쇠·인증서·인증 기관 사본이 서비스 계정 소유 (root 가 아님)",
              os.stat(os.path.realpath(e.paths.tls_key)).st_uid == 1000 and os.stat(os.path.realpath(e.paths.tls_cert)).st_uid == 1000
              and os.stat(e.paths.tls_ca).st_uid == 1000, os.stat(os.path.realpath(e.paths.tls_key)))
    co_ca, co_out = os.path.join(TMP, "owner_co_ca"), os.path.join(TMP, "owner_co_cert")
    lan_ca.make_ca(co_ca, [], ["127.0.0.1"])
    co_cert, co_key = lan_ca.issue_server(co_ca, co_out, [], ["127.0.0.1"])
    del asked[:]
    code, so, se = call(["cert", "--import-web", co_cert, co_key])
    check("--owner 없이 root 로 --import-web 0, 기본 서비스 계정", code == 0 and asked == ["autopilotd"], (code, se, asked))
    if REAL_ROOT:
        check("업체 웹 인증서 쌍도 서비스 계정 소유", os.stat(os.path.realpath(e.paths.web_key)).st_uid == 1000
              and os.stat(e.paths.web_tls_dir).st_uid == 1000)
    # 시험 자리(install.sh --root)의 실행 글은 AUTOPILOT_SERVICE_USER 를 싣는다
    os.environ.update(AUTOPILOT_ROOT=os.path.join(TMP, "owner_root"), AUTOPILOT_SERVICE_USER="nobody")
    del asked[:]
    try:
        code, so, se = call(["cert", "--renew"])
    finally:
        for k in ("AUTOPILOT_ROOT", "AUTOPILOT_SERVICE_USER"):
            os.environ.pop(k, None)
    check("시험 자리면 AUTOPILOT_SERVICE_USER 의 계정", code == 0 and asked == ["nobody"], (code, se, asked))

    def missing(user):
        raise KeyError(user)
    server_main._service_ids = missing
    code, so, se = call(["cert", "--renew"])
    check("서비스 계정이 없으면 1 (root 전용 인증서를 만들지 않는다)", code == 1 and "autopilotd" in se, (code, se))
    code, so, se = call(["cert", "--renew", "--help"])
    check("도움말에 --owner 의 기본값(autopilotd)", code == 0 and "autopilotd" in so, so[-400:])


try:
    print("관리 명령 (test_server_admin)")
    for t in (test_request_file, test_status_ok_and_problems, test_admin_reset_needs_stopped, test_admin_reset_owner,
              test_admin_reset, test_verify, test_upgrade_verifies_first, test_cert_root_only, test_cert_renew_backdated,
              test_cert_if_expiring, test_import_web_cert, test_replace_pair_atomic, test_lock_no_follow, test_cert_no_follow,
              test_cert_default_owner):
        guard(t.__name__, t)
finally:
    for k in ENV_KEYS + ("MARK",):
        os.environ.pop(k, None)
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n실패: {len(fails)}" + (f" ({', '.join(fails)})" if fails else ""))
sys.exit(1 if fails else 0)
