# -*- coding: utf-8 -*-
"""사내 서버 ④ Task 5 - 백업과 복구 (계획 2026-11-25-lan-4-linux Task 5, Review Focus 4).
같은 시점 백업(영속 쓰기 공통 잠금 server_backup.PERSIST_LOCK 을 쥔 채 JSON 은 파일 그대로, 두 DB 는 SQLite 백업 기능),
7개 유지, 0600, backup.json 지문. 서비스가 돌면 backup 은 SIGUSR1 로 서비스 안에서 뜨게 하고, 멈춰 있으면 잠금을 쥐고 직접 뜬다.
복구는 서비스 잠금을 쥔 채(그 사이 run 은 4), 압축 안 이름 검사, 지문, 형식 번호, 다른 서버 백업은 --force.
설정 백업(backup-config·restore-config)은 root 만. root 가 필요한 길은 server_main._euid·_service_ids·_drop_privileges 를
바꿔 끼워 흉내 낸다. 경쟁은 시간에 기대지 않는다 - 백업 중간 손잡이(server_backup._TEST_PAUSE)에서 쓰기를 끼워 넣는다.
윈도우·WSL 둘 다 (WSL 의 임시 폴더는 /tmp 아래, SIGUSR1 길은 리눅스만).
    D:/AX/RPA/.venv/Scripts/python.exe tests/test_server_backup.py
    wsl.exe -d Ubuntu -e python3 /mnt/d/AX/RPA_StandAlone/tests/test_server_backup.py
"""
import contextlib
import datetime
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import socket
import sqlite3
import stat
import sys
import tarfile
import tempfile
import threading
import time
import traceback
import uuid

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
POSIX = os.name == "posix"

import lan_ca  # noqa: E402
import license_check  # noqa: E402
import local_server  # noqa: E402
import local_web  # noqa: E402
import login_log  # noqa: E402
import pc_registry  # noqa: E402
import seat  # noqa: E402
import server_log  # noqa: E402
import update_sign  # noqa: E402

fails = []
try:
    import server_main  # noqa: E402
    import server_backup  # noqa: E402
except ImportError as e:
    print(f"  [실패] server_backup 을 불러오지 못한다 - {e}")
    print("\n실패: 1")
    sys.exit(1)

SERVICE = lambda: 1000                                     # noqa: E731  서비스 계정 흉내 (WSL 은 root 로 돈다)
ROOT_EUID = lambda: 0                                      # noqa: E731
server_main._euid = SERVICE
REAL_IDS, REAL_DROP = server_main._service_ids, server_main._drop_privileges
TMP = tempfile.mkdtemp(prefix="rpa_server_backup_", dir="/tmp" if POSIX else None)
LIC_SECRET, LIC_PUBLIC = update_sign.keygen()             # 시험 라이선스 열쇠
BOSS_PW = "pw-1234567890"
ENV_KEYS = ("AUTOPILOT_ETC", "AUTOPILOT_DATA", "AUTOPILOT_LOGS")
CA_DIR, CERT_DIR = os.path.join(TMP, "ca"), os.path.join(TMP, "cert")
lan_ca.make_ca(CA_DIR, [], ["127.0.0.1"])
CERT, KEY = lan_ca.issue_server(CA_DIR, CERT_DIR, [], ["127.0.0.1"])
NAME_RE = re.compile(r"autopilot-backup-\d{8}-\d{6}(-\d+)?\.tar\.gz")
CMD = "apps/rpa/commands/c1"


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


def register(reg, label="PC"):
    """등록부에 PC 하나를 등록한다 (대기 → 등록) → PC 번호."""
    info = reg.start(label)
    rand, guid, host = secrets.token_hex(32), str(uuid.uuid4()), "HOST-" + label
    proof = pc_registry.enroll_proof(info["token"], info["pc_id"], rand, guid, host)
    reg.enroll(info["pc_id"], rand, guid, host, proof)
    return info["pc_id"]


class Env:
    def __init__(self, name, seats=50):
        base = os.path.join(TMP, name)
        self.base = base
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
        for src, dst in ((CERT, self.paths.tls_cert), (KEY, self.paths.tls_key),
                         (os.path.join(CA_DIR, lan_ca.CA_CERT), self.paths.tls_ca)):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
        with open(os.path.join(self.data, "security.json"), "w", encoding="utf-8") as f:
            f.write('{"version":1,"totp_scope":"off","show_own_history":true}')
        with open(self.paths.format_file, "w", encoding="ascii") as f:          # run 이 처음 켤 때 쓰는 것
            f.write(f"{server_main.FORMAT}\n")
        self.accounts = os.path.join(self.data, local_web.ACCOUNTS_NAME)
        acc = local_web.Accounts(self.accounts)
        acc.admin_min = 10
        acc.set("boss", BOSS_PW, "admin")
        self.result, self.thread = [], None

    def fill(self):
        """서비스가 멈춘 상태의 자료 - PC 하나, 그 PC 의 명령, 실행 기록, 로그인 이력 한 줄."""
        reg = pc_registry.Registry(self.paths.pcs, seats=50)
        pc = register(reg, "MAIN")
        store = local_server.Store(self.paths.store, volatile=local_server.VOLATILE)
        store.put(f"{CMD}/{pc}/k1", {"type": "run", "state": "queued"})
        runs = local_server.Runs(self.paths.runs_db)
        runs.create("apps/rpa/companies/c1", "runs", "r1", {"pcId": pc, "started_at": "2026-11-25T10:00:00"}, pc_id=pc)
        runs.close()
        ll = login_log.LoginLog(os.path.join(self.data, login_log.LOGINS_NAME))
        ll.add("ok", "boss", "127.0.0.1", "Edge · Windows")
        ll.close()
        return pc

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

    def backups(self):
        try:
            return sorted(n for n in os.listdir(self.paths.backups) if NAME_RE.fullmatch(n))
        except OSError:
            return []


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
        server_main.LICENSE_PUBLIC_KEY = None
        server_backup._TEST_PAUSE = server_backup._TEST_RESTORE_PAUSE = None


def fake_root():
    events = []
    server_main._euid = ROOT_EUID
    server_main._service_ids = lambda user: (1000, 1000) if POSIX else None
    server_main._drop_privileges = lambda ids: events.append(("drop", ids))
    return events


def members(path):
    with tarfile.open(path, "r:gz") as tf:
        return {m.name: m for m in tf.getmembers()}


def blob(path, name):
    with tarfile.open(path, "r:gz") as tf:
        return tf.extractfile(name).read()


def manifest(path):
    return json.loads(blob(path, "backup.json").decode("utf-8"))


def db_from(path, name, where):
    """백업 안의 DB 를 임시 파일로 꺼내 연결한다."""
    out = os.path.join(where, secrets.token_hex(4) + "_" + name)
    with open(out, "wb") as f:
        f.write(blob(path, name))
    return sqlite3.connect(out)


def json_from(path, name):
    return json.loads(blob(path, name).decode("utf-8"))


def tree(folder, skip=()):
    """폴더 안 파일 {상대 이름: sha256} (skip 으로 시작하는 맨 위 이름은 뺀다)."""
    out = {}
    for d, dirs, files in os.walk(folder):
        rel_d = os.path.relpath(d, folder).replace("\\", "/")
        if rel_d != "." and rel_d.split("/")[0].startswith(skip):
            continue
        for n in files:
            rel = n if rel_d == "." else f"{rel_d}/{n}"
            if rel.split("/")[0].startswith(skip):
                continue
            with open(os.path.join(d, n), "rb") as f:
                out[rel] = hashlib.sha256(f.read()).hexdigest()
    return out


def db_rows(path, sql):
    db = sqlite3.connect(path)
    try:
        return sorted(db.execute(sql).fetchall())
    finally:
        db.close()


def logical(folder, skip):
    """tree 와 같되 DB 는 바이트 대신 줄 (SQLite 백업 사본은 바이트가 원본과 다르다)."""
    out = tree(folder, skip=skip)
    for name, sql in (("runs.db", "SELECT parent, collection, id, pc_id, doc FROM docs"),
                      ("logins.db", "SELECT at, uid, ip, agent, result FROM logins")):
        if name in out:
            out[name] = db_rows(os.path.join(folder, name), sql)
    return out


def repack(src, dst, change):
    """백업 파일을 풀어 change(이름→바이트 dict) 를 고친 뒤 다시 묶는다 (지문 목록도 고친다)."""
    with tarfile.open(src, "r:gz") as tf:
        files = {m.name: tf.extractfile(m).read() for m in tf.getmembers() if m.isfile()}
    change(files)
    man = json.loads(files["backup.json"])
    man["files"] = {n: hashlib.sha256(b).hexdigest() for n, b in files.items() if n != "backup.json"}
    files["backup.json"] = json.dumps(man).encode()
    write_tar(dst, [(n, b) for n, b in files.items()])


def write_tar(dst, entries):
    """entries = [(이름, 바이트)] 또는 [(TarInfo, 바이트|None)]."""
    with tarfile.open(dst, "w:gz") as tf:
        for name, data in entries:
            if isinstance(name, tarfile.TarInfo):
                tf.addfile(name, io.BytesIO(data) if data is not None else None)
                continue
            ti = tarfile.TarInfo(name)
            ti.size, ti.mode = len(data), 0o600
            tf.addfile(ti, io.BytesIO(data))


# ----------------------------------------------------------------------------------------------------

def test_backup_contents():
    e = Env("contents")
    pc = e.fill()
    if POSIX:                                       # 설치본처럼 tls/current 를 pair-* 를 가리키는 링크로
        lan_ca.replace_pair(e.paths.tls_dir, read(CERT), read(KEY))
    # 빠져야 하는 것들
    for rel, text in (("backups/old.txt", "x"), ("uploads/big.bin", "y"), ("run.json", "{}"), ("store.json.ab12.tmp", "half"),
                      ("before-restore-20261101-000000/store.json", "{}"), (".issue-xx/k.pem", "k")):
        p = os.path.join(e.data, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
    held = server_main.ServiceLock(e.paths.lock)
    held.try_hold()
    held.release()                                  # .service.lock 파일이 생긴다
    path = server_backup.snapshot(None, e.paths)
    check("백업 파일 이름 autopilot-backup-YYYYMMDD-HHMMSS.tar.gz, 자료 폴더의 backups/ 안",
          NAME_RE.fullmatch(os.path.basename(path)) is not None and os.path.dirname(path) == e.paths.backups, path)
    if POSIX:
        check("백업 파일 0600·backups 폴더 0700", mode(path) == 0o600 and mode(e.paths.backups) == 0o700,
              (oct(mode(path)), oct(mode(e.paths.backups))))
    m = members(path)
    names = set(m)
    want = {"backup.json", "store.json", "pcs.json", "accounts.json", "runs.db", "logins.db", "seat.key", "security.json",
            "FORMAT", "tls/ca_cert.pem", "tls/current/server_cert.pem", "tls/current/server_key.pem"}
    check("든 것: 저장소·등록부·계정·두 DB·자리 열쇠·보안 설정·형식 번호·인증서 쌍", want <= names, sorted(want - names))
    bad = [n for n in names if n.split("/")[0] in ("backups", "uploads", ".service.lock", "run.json")
           or n.endswith(".tmp") or n.startswith("before-restore-") or n.split("/")[0].startswith(".")
           or n.split("/")[-1].startswith("pair-") or "/pair-" in n]
    check("빠지는 것: backups/·uploads/·.service.lock·run.json·임시 파일·복구 전 사본·pair-* (current 만)", not bad, bad)
    check("압축 안은 보통 파일만 (링크 없음), 0600", all(x.isfile() and x.mode == 0o600 for x in m.values()),
          [(x.name, x.type, oct(x.mode)) for x in m.values() if not (x.isfile() and x.mode == 0o600)])
    man = manifest(path)
    check("backup.json = {version, format, server_id, made, files}", set(man) == {"version", "format", "server_id", "made", "files"},
          man.keys())
    check("backup.json 의 server_id·format·version", man.get("server_id") == e.server_id and man.get("format") == server_main.FORMAT
          and man.get("version") == server_main.version(), man)
    hashes = {n: hashlib.sha256(blob(path, n)).hexdigest() for n in names if n != "backup.json"}
    check("files 지문이 압축 안 파일마다 맞다 (빠짐·남음 없음)", man.get("files") == hashes,
          (set(man.get("files", {})) ^ set(hashes)))
    db = db_from(path, "runs.db", e.base)
    rows = db.execute("SELECT pc_id FROM docs").fetchall()
    ok = db.execute("PRAGMA integrity_check").fetchone()[0]
    db.close()
    check("백업의 실행 기록 DB 가 온전하고 기록이 들어 있다", rows == [(pc,)] and ok == "ok", (rows, ok))
    db = db_from(path, "logins.db", e.base)
    n = db.execute("SELECT COUNT(*) FROM logins").fetchone()[0]
    db.close()
    check("백업의 로그인 이력 DB 에 줄이 있다", n == 1, n)
    check("등록부·저장소 내용 그대로", pc in json_from(path, "pcs.json")["pcs"] and pc in json_from(path, "store.json")
          ["apps"]["rpa"]["commands"]["c1"])
    # 서비스가 멈춰 있으면 backup 명령이 잠금을 쥐고 직접 뜬다
    before = set(e.backups())
    code, so, se = call(["backup"])
    new = set(e.backups()) - before
    check("서비스가 멈춰 있으면 backup 명령이 직접 뜬다 (0, 경로 출력)", code == 0 and len(new) == 1 and next(iter(new)) in so,
          (code, so, se, new))
    check("끝나면 잠금을 놓는다", server_main.ServiceLock.held(e.paths.lock) is False)
    # root 로 부르면 잠금을 쥔 뒤 서비스 계정으로 권한을 내리고 뜬다
    events = fake_root()
    seen = {}
    server_main._drop_privileges = lambda ids: (events.append(("drop", ids)),
                                                seen.setdefault("locked", server_main.ServiceLock.held(e.paths.lock)))
    code, so, se = call(["backup"])
    check("root 로 부르면 잠금 → 권한 내리기 → 백업", code == 0 and [x[0] for x in events] == ["drop"] and seen.get("locked") is True,
          (code, se, events, seen))


def test_keep_7():
    e = Env("keep")
    e.fill()
    base = datetime.datetime(2026, 11, 1, 3, 0, 0)
    made = [server_backup.snapshot(None, e.paths, now=(base + datetime.timedelta(days=i)).timestamp()) for i in range(9)]
    left = e.backups()
    check("9번 뜨면 7개만 남는다", len(left) == 7, left)
    check("지워지는 것은 가장 오래된 둘", left == sorted(os.path.basename(p) for p in made[2:]), left)
    p = server_backup.snapshot(None, e.paths, keep=3, now=(base + datetime.timedelta(days=20)).timestamp())
    check("keep=3 이면 3개", len(e.backups()) == 3 and os.path.basename(p) in e.backups(), e.backups())
    q = server_backup.snapshot(None, e.paths, keep=7, now=(base + datetime.timedelta(days=20)).timestamp())
    check("같은 초에 두 번 떠도 앞 파일을 덮지 않는다", q != p and os.path.isfile(p) and os.path.isfile(q), (p, q))
    with open(os.path.join(e.paths.backups, "keep-me.txt"), "w") as f:
        f.write("x")
    for i in range(8):
        server_backup.snapshot(None, e.paths, now=(base + datetime.timedelta(days=30 + i)).timestamp())
    check("백업 이름이 아닌 파일은 지우지 않는다", os.path.isfile(os.path.join(e.paths.backups, "keep-me.txt")))


def test_backup_consistent_snapshot():
    e = Env("consistent")
    store = local_server.Store(e.paths.store, volatile=local_server.VOLATILE)
    reg = pc_registry.Registry(e.paths.pcs, seats=5000)
    acc = local_web.Accounts(e.accounts)
    runs = local_server.Runs(e.paths.runs_db)
    ll = login_log.LoginLog(os.path.join(e.data, login_log.LOGINS_NAME))
    server_backup.attach(store, reg, acc, runs, ll)
    check("attach 뒤 다섯 저장소가 같은 영속 잠금을 쓴다",
          all(o.persist_lock is server_backup.PERSIST_LOCK for o in (store, reg, acc, runs, ll)))

    def one(n):
        pc = register(reg, f"P{n}")
        store.put(f"{CMD}/{pc}/k{n}", {"type": "run", "state": "queued"})
        runs.create("apps/rpa/companies/c1", "runs", f"r{n}", {"pcId": pc, "started_at": "2026-11-25T10:00:00"}, pc_id=pc)
        ll.add("ok", "boss", "127.0.0.1", "Edge · Windows")
        return pc

    def verify(path, label):
        pcs = set(json_from(path, "pcs.json")["pcs"])
        cmds = set(((json_from(path, "store.json").get("apps") or {}).get("rpa") or {}).get("commands", {}).get("c1", {}))
        db = db_from(path, "runs.db", e.base)
        run_pcs = {r[0] for r in db.execute("SELECT pc_id FROM docs")}
        ok1 = db.execute("PRAGMA integrity_check").fetchone()[0]
        db.close()
        db = db_from(path, "logins.db", e.base)
        ok2 = db.execute("PRAGMA integrity_check").fetchone()[0]
        db.close()
        check(f"[{label}] 명령이 있는 PC 는 모두 등록부에 있다", cmds <= pcs, sorted(cmds - pcs))
        check(f"[{label}] 실행 기록이 있는 PC 는 모두 등록부에 있다", run_pcs <= pcs, sorted(run_pcs - pcs))
        check(f"[{label}] 두 DB integrity_check ok", ok1 == "ok" and ok2 == "ok", (ok1, ok2))
        return pcs, cmds

    # 1) 쉼 없이 쓰는 중에 여러 번
    stop, count = threading.Event(), [0]

    def writer():
        while not stop.is_set():
            count[0] += 1
            one(count[0])
    t = threading.Thread(target=writer, daemon=True)
    t.start()
    try:
        until(lambda: count[0] >= 3, 30)
        for i in range(5):
            verify(server_backup.snapshot({"store": store, "registry": reg, "accounts": acc, "runs": runs, "login_log": ll},
                                          e.paths, keep=10, now=time.time() + i), f"쓰는 중 {i + 1}")
    finally:
        stop.set()
        t.join(30)
    check("쓰기 스레드가 그동안 PC 를 여럿 등록했다", count[0] >= 5, count[0])

    # 2) 등록부를 읽은 바로 뒤에 PC 등록과 그 PC 의 명령을 끼워 넣는다 - 잠금이 막아 백업에 반쪽만 들어가지 않는다
    done, box = threading.Event(), {}

    def pause(rel):
        if rel == "pcs.json" and "t" not in box:
            def late():
                box["pc"] = one(9000)
                done.set()
            box["t"] = threading.Thread(target=late, daemon=True)
            box["t"].start()
            box["blocked"] = not done.wait(1.0)     # 잠금이 있으면 끝나지 못한다 (없으면 1초 안에 끝나 아래 검사가 실패한다)
    server_backup._TEST_PAUSE = pause
    try:
        path = server_backup.snapshot({"store": store, "registry": reg, "accounts": acc, "runs": runs, "login_log": ll},
                                      e.paths, keep=10, now=time.time() + 10)
    finally:
        server_backup._TEST_PAUSE = None
    check("백업 중 끼어든 쓰기는 영속 잠금 앞에서 기다린다", box.get("blocked") is True, box)
    pcs, cmds = verify(path, "끼워 넣기")
    check("끼어든 쓰기는 백업이 끝난 뒤 마무리된다", done.wait(30) and box.get("pc") not in pcs and box.get("pc") not in cmds, box)
    runs.close()
    ll.close()


def test_backup_signal_path():
    if not POSIX:
        print("  [건너뜀] SIGUSR1 길은 리눅스(WSL)에서만")
        return
    e = Env("signal")
    e.fill()
    box = {}

    def helper():
        try:
            until(lambda: os.path.isfile(e.paths.run_json), 30)
            box["first"] = until(lambda: len(e.backups()) >= 1, 30)        # 켜자마자 그날 백업 (아직 없으므로)
            before = set(e.backups())
            box["call"] = call(["backup"])
            box["new"] = set(e.backups()) - before
        finally:
            server_main.stop()
    safety = threading.Timer(120, server_main.stop)
    safety.start()
    t = threading.Thread(target=helper, daemon=True)
    t.start()
    try:
        code = server_main.main(["run"])           # 주 스레드 - SIGUSR1 처리기가 걸린다
    finally:
        safety.cancel()
        t.join(30)
    check("run 이 정상으로 끝났다", code == 0, (code, read(e.paths.server_log)[-500:]))
    check("켜지면 정비 스레드가 그날 백업을 뜬다 (backup_hour 지남·백업 없음)", box.get("first") is True, box)
    c = box.get("call") or (None, "", "")
    check("서비스가 돌면 backup 명령은 SIGUSR1 을 보내고 새 백업을 기다린다 (0)", c[0] == 0 and len(box.get("new") or ()) == 1,
          (c, box.get("new")))
    check("출력에 새 백업 경로", bool(box.get("new")) and next(iter(box["new"])) in c[1], c)
    check("server.log 에 백업 줄", "백업" in read(e.paths.server_log), read(e.paths.server_log)[-500:])


def test_backup_schedule():
    due = server_main.backup_due
    day = datetime.datetime(2026, 11, 25)
    at = lambda h, m=0, d=0: (day + datetime.timedelta(days=d, hours=h, minutes=m)).timestamp()   # noqa: E731
    check("백업이 하나도 없으면 바로", due(None, 3, at(10)) is True)
    check("오늘 3시 뒤에 뜬 백업이 있으면 아니다", due(at(3, 5), 3, at(10)) is False)
    check("어제 3시 뒤 백업, 지금 오늘 2시 → 아직", due(at(3, 5, -1), 3, at(2)) is False)
    check("어제 3시 뒤 백업, 지금 오늘 3시 1분 → 뜬다", due(at(3, 5, -1), 3, at(3, 1)) is True)
    check("이틀 전 백업, 지금 오늘 1시 → 어제 3시 몫을 뜬다", due(at(3, 5, -2), 3, at(1)) is True)
    check("backup_hour 0 도 된다", due(at(23, 0, -1), 0, at(0, 30)) is True and due(at(0, 10), 0, at(5)) is False)
    import lan_config
    check("server.json 의 backup_hour 기본 3", lan_config.parse({"listen": "127.0.0.1"}).backup_hour == 3)
    check("backup_hour 5 는 그대로", lan_config.parse({"listen": "127.0.0.1", "backup_hour": 5}).backup_hour == 5)
    for bad in (24, -1, "3", True, 3.0):
        try:
            lan_config.parse({"listen": "127.0.0.1", "backup_hour": bad})
            ok = False
        except lan_config.ConfigError:
            ok = True
        check(f"backup_hour {bad!r} 는 설정 오류", ok)


def test_restore_roundtrip():
    e = Env("roundtrip")
    pc = e.fill()
    path = server_backup.snapshot(None, e.paths)
    want = logical(e.data, skip=("backups", ".service.lock", "before-restore-"))
    # 백업 뒤에 자료가 바뀐다
    acc = local_web.Accounts(e.accounts)
    acc.admin_min = 10
    acc.set("boss", "changed-password-1", "admin")
    reg = pc_registry.Registry(e.paths.pcs, seats=50)
    pc2 = register(reg, "LATER")
    store = local_server.Store(e.paths.store)
    store.delete(f"{CMD}/{pc}")
    os.remove(os.path.join(e.data, "security.json"))
    before = tree(e.data, skip=("backups", ".service.lock", "before-restore-"))
    aside = server_backup.restore(e.paths, path)
    got = logical(e.data, skip=("backups", ".service.lock", "before-restore-"))
    check("복구하면 자료가 백업 때와 같다", got == want, (set(got) ^ set(want), [k for k in got if got.get(k) != want.get(k)]))
    check("전의 자료는 before-restore-<시각>/ 에 그대로", os.path.basename(aside).startswith("before-restore-")
          and os.path.dirname(aside) == e.paths.data and tree(aside) == before, aside)
    check("backups/ 는 그대로 (복구한 파일 포함)", os.path.isfile(path))
    check("복구한 계정은 옛 비밀번호", local_web.Accounts(e.accounts).verify("boss", BOSS_PW) is not None)
    check("복구한 등록부에는 백업 뒤에 등록한 PC 가 없다", pc2 not in json.loads(read(e.paths.pcs))["pcs"])
    if POSIX:
        bad = [p for p in tree(e.data, skip=("backups", "before-restore-")) if mode(os.path.join(e.data, p)) != 0o600]
        check("복구한 파일은 0600", not bad, bad)
    check("복구한 자료로 서버가 켜진다", e.start(), (e.result, read(e.paths.server_log)[-500:]))
    e.stop()
    # 명령 줄
    code, so, se = call(["restore", path])
    check("restore 명령 0, 안내에 systemctl start", code == 0 and "systemctl start autopilot" in so, (code, so, se))
    check("restore 의 audit.log 줄 (백업 파일 이름)", "복구" in read(e.paths.audit_log) and os.path.basename(path) in read(e.paths.audit_log),
          read(e.paths.audit_log)[-300:])


def test_restore_holds_lock():
    e = Env("holds")
    e.fill()
    path = server_backup.snapshot(None, e.paths)
    got = []
    server_backup._TEST_RESTORE_PAUSE = lambda: got.append(call(["run"]))
    server_backup.restore(e.paths, path)
    check("복구 중에 서비스 run 은 잠금을 못 잡아 4", [g[0] for g in got] == [4], got)
    check("그 까닭 '다른 작업(복구 또는 계정 초기화)'", bool(got) and "다른 작업" in got[0][2], got)
    check("복구가 끝나면 잠금을 놓는다", server_main.ServiceLock.held(e.paths.lock) is False)


def test_restore_refuses_running():
    e = Env("busy")
    e.fill()
    path = server_backup.snapshot(None, e.paths)
    before = tree(e.data, skip=("backups", ".service.lock"))
    held = server_main.ServiceLock(e.paths.lock)
    check("다른 쪽(서비스)이 잠금을 쥐었다", held.try_hold())
    try:
        try:
            server_backup.restore(e.paths, path)
            err = None
        except RuntimeError as ex:
            err = str(ex)
        code, so, se = call(["restore", path])
    finally:
        held.release()
    check("서비스가 돌면 RuntimeError('서비스를 먼저 멈추어 주십시오: systemctl stop autopilot')",
          err == "서비스를 먼저 멈추어 주십시오: systemctl stop autopilot", err)
    check("restore 명령은 1 과 같은 안내", code == 1 and "systemctl stop autopilot" in se, (code, se))
    check("자료는 그대로", tree(e.data, skip=("backups", ".service.lock")) == before)


def test_restore_rejects_bad_names():
    e = Env("names")
    e.fill()
    good = server_backup.snapshot(None, e.paths)
    with tarfile.open(good, "r:gz") as tf:
        files = {m.name: tf.extractfile(m).read() for m in tf.getmembers()}
    before = tree(e.data, skip=("backups", ".service.lock"))
    outside = os.path.join(e.base, "x")

    def man_for(extra):
        man = json.loads(files["backup.json"])
        man["files"] = dict(man["files"], **{n: hashlib.sha256(b).hexdigest() for n, b in extra.items()})
        return json.dumps(man).encode()

    cases = []
    for bad in ("../x", "/tmp/abs-x" if POSIX else "/abs-x", "tls/../../x", "a\\b", ".hidden"):
        extra = {bad: b"evil"}
        cases.append((bad, [(n, b) for n, b in files.items() if n != "backup.json"] + [("backup.json", man_for(extra)), (bad, b"evil")]))
    link = tarfile.TarInfo("link")
    link.type, link.linkname = tarfile.SYMTYPE, "../x"
    cases.append(("심볼릭 링크", [(n, b) for n, b in files.items()] + [(link, None)]))
    hard = tarfile.TarInfo("hard")
    hard.type, hard.linkname = tarfile.LNKTYPE, "store.json"
    cases.append(("하드 링크", [(n, b) for n, b in files.items()] + [(hard, None)]))
    dev = tarfile.TarInfo("fifo")
    dev.type = tarfile.FIFOTYPE
    cases.append(("특수 파일", [(n, b) for n, b in files.items()] + [(dev, None)]))
    for label, entries in cases:
        dst = os.path.join(e.base, f"bad_{secrets.token_hex(3)}.tar.gz")
        write_tar(dst, entries)
        try:
            server_backup.restore(e.paths, dst)
            err = None
        except ValueError as ex:
            err = str(ex)
        check(f"압축 안 이름 {label!r} → 거절 (ValueError)", err is not None, err)
        check(f"[{label}] 자료 그대로·밖에 아무것도 없다", tree(e.data, skip=("backups", ".service.lock")) == before
              and not os.path.exists(outside) and not os.path.exists("/tmp/abs-x"))
    # 지문이 틀린 것
    dst = os.path.join(e.base, "bad_hash.tar.gz")
    write_tar(dst, [(n, (b + b" " if n == "store.json" else b)) for n, b in files.items()])
    try:
        server_backup.restore(e.paths, dst)
        err = None
    except ValueError as ex:
        err = str(ex)
    check("지문이 틀린 파일이 있으면 거절", err is not None and tree(e.data, skip=("backups", ".service.lock")) == before, err)
    dst = os.path.join(e.base, "extra.tar.gz")
    write_tar(dst, list(files.items()) + [("extra.json", b"{}")])
    try:
        server_backup.restore(e.paths, dst)
        err = None
    except ValueError as ex:
        err = str(ex)
    check("backup.json 에 없는 파일이 끼어 있으면 거절", err is not None, err)
    dst = os.path.join(e.base, "nomani.tar.gz")
    write_tar(dst, [(n, b) for n, b in files.items() if n != "backup.json"])
    try:
        server_backup.restore(e.paths, dst)
        err = None
    except ValueError as ex:
        err = str(ex)
    check("backup.json 이 없으면 거절", err is not None, err)
    code, so, se = call(["restore", os.path.join(e.base, "bad_hash.tar.gz")])
    check("restore 명령은 1", code == 1, (code, se))


def test_restore_other_server():
    e = Env("other")
    e.fill()
    path = server_backup.snapshot(None, e.paths)
    other = os.path.join(e.base, "machine-id-2")
    with open(other, "w", encoding="ascii") as f:
        f.write(secrets.token_hex(16) + "\n")
    server_main.MACHINE_ID = other
    before = tree(e.data, skip=("backups", ".service.lock"))
    try:
        server_backup.restore(e.paths, path)
        err = None
    except ValueError as ex:
        err = str(ex)
    check("다른 서버의 백업은 force 없이 거절 ('다른 서버의 백업입니다. 라이선스를 다시 받아야 합니다')",
          err is not None and "다른 서버의 백업입니다. 라이선스를 다시 받아야 합니다" in err, err)
    check("자료 그대로", tree(e.data, skip=("backups", ".service.lock")) == before)
    code, so, se = call(["restore", path])
    check("restore 명령도 1 (--force 안내)", code == 1 and "--force" in se, (code, se))
    code, so, se = call(["restore", path, "--force"])
    check("--force 면 복구한다", code == 0, (code, se))


def test_restore_newer_format():
    e = Env("format")
    e.fill()
    path = server_backup.snapshot(None, e.paths)
    dst = os.path.join(e.base, "newer.tar.gz")

    def bump(files):
        man = json.loads(files["backup.json"])
        man["format"] = server_main.FORMAT + 1
        files["backup.json"] = json.dumps(man).encode()
        files["FORMAT"] = f"{server_main.FORMAT + 1}\n".encode()
    repack(path, dst, bump)
    before = tree(e.data, skip=("backups", ".service.lock"))
    try:
        server_backup.restore(e.paths, dst)
        err = None
    except ValueError as ex:
        err = str(ex)
    check("형식 번호가 이 코드보다 큰 백업은 거절", err is not None and "형식" in err, err)
    check("자료 그대로", tree(e.data, skip=("backups", ".service.lock")) == before)


def test_backup_config_root_only():
    e = Env("config")
    dest = os.path.join(e.base, "var-backups")
    server_main.CONFIG_BACKUPS = dest
    os.makedirs(e.paths.ca_dir)
    with open(os.path.join(e.paths.ca_dir, lan_ca.CA_KEY), "w") as f:
        f.write("CA-KEY")
    code, so, se = call(["backup-config"])
    check("root 가 아니면 backup-config 는 1", code == 1 and "root" in se and not os.path.exists(dest), (code, se))
    code, so, se = call(["restore-config", os.path.join(e.base, "none.tar.gz")])
    check("root 가 아니면 restore-config 도 1", code == 1 and "root" in se, (code, se))
    fake_root()
    code, so, se = call(["backup-config"])
    files = sorted(os.listdir(dest)) if os.path.isdir(dest) else []
    check("root 면 /var/backups/autopilot/etc-YYYYMMDD.tar.gz", code == 0 and len(files) == 1
          and re.fullmatch(r"etc-\d{8}\.tar\.gz", files[0]) is not None, (code, se, files))
    if not files:
        return
    path = os.path.join(dest, files[0])
    names = set(members(path))
    check("설정·라이선스·인증 기관(ca/) 이 든다", {"server.json", "license.json", f"ca/{lan_ca.CA_KEY}"} <= names, names)
    if POSIX:
        check("설정 백업 0600·폴더 0700", mode(path) == 0o600 and mode(dest) == 0o700)
    base = datetime.datetime(2026, 11, 1)
    for i in range(9):
        server_backup.config_backup(e.paths.etc, dest, now=(base + datetime.timedelta(days=i)).timestamp())
    check("설정 백업도 7개 유지", len(os.listdir(dest)) == 7, os.listdir(dest))
    # 되살리기
    want = read(e.paths.server_json)
    with open(e.paths.server_json, "w", encoding="utf-8") as f:
        f.write("{broken")
    held = server_main.ServiceLock(e.paths.lock)
    held.try_hold()
    try:
        code, so, se = call(["restore-config", path])
    finally:
        held.release()
    check("서비스가 돌면(잠금) restore-config 는 1, 그대로", code == 1 and read(e.paths.server_json) == "{broken", (code, se))
    code, so, se = call(["restore-config", path])
    check("restore-config 로 /etc/autopilot 이 되살아난다", code == 0 and read(e.paths.server_json) == want, (code, so, se))
    asides = [n for n in os.listdir(e.base) if n.startswith("etc.before-restore-")]
    check("전의 설정은 옆에 (etc.before-restore-<시각>)", len(asides) == 1
          and read(os.path.join(e.base, asides[0], "server.json")) == "{broken", asides)
    bad = os.path.join(e.base, "cfg_bad.tar.gz")
    write_tar(bad, [("../evil", b"x")])
    code, so, se = call(["restore-config", bad])
    check("설정 백업도 압축 안 이름이 틀리면 1", code == 1 and not os.path.exists(os.path.join(e.base, "evil")), (code, se))


def test_config_backup_odd_names_and_kind():
    """끝 검토 (Fable 4·5, Codex 9): 설정 폴더에 편집기 사본·숨김 임시·띄어쓰기 이름이 있어도 설정 백업은 복구 규칙에 맞는 이름만 담아
    restore-config 가 받는다. 자료 백업(backup.json)이나 server.json 이 없는 압축은 설정 복구가 거절한다 (설정 폴더 그대로)."""
    e = Env("config_odd")
    dest = os.path.join(e.base, "var-backups")
    server_main.CONFIG_BACKUPS = dest
    os.makedirs(e.paths.ca_dir)
    with open(os.path.join(e.paths.ca_dir, lan_ca.CA_KEY), "w") as f:
        f.write("CA-KEY")
    for n in ("server.json~", ".server.json.swp", "license (1).json", ".server.json.new"):
        with open(os.path.join(e.paths.etc, n), "w") as f:
            f.write("x")
    os.makedirs(os.path.join(e.paths.etc, ".cert-abc"))
    with open(os.path.join(e.paths.etc, ".cert-abc", "server_key.pem"), "w") as f:
        f.write("half")
    fake_root()
    code, so, se = call(["backup-config"])
    files = sorted(os.listdir(dest)) if os.path.isdir(dest) else []
    check("이상한 이름이 있어도 backup-config 0", code == 0 and len(files) == 1, (code, se, files))
    if not files:
        return
    path = os.path.join(dest, files[0])
    names = set(members(path))
    check("복구 규칙에 안 맞는 이름은 담지 않는다", not any(x in names for x in ("server.json~", ".server.json.swp", "license (1).json",
                                                                   ".server.json.new", ".cert-abc", ".cert-abc/server_key.pem")), names)
    check("빠진 이름을 알린다", "server.json~" in se and ".cert-abc" in se, se)
    check("설정·인증 기관은 그대로 담는다", {"server.json", f"ca/{lan_ca.CA_KEY}"} <= names, names)
    want = read(e.paths.server_json)
    with open(e.paths.server_json, "w", encoding="utf-8") as f:
        f.write("{broken")
    code, so, se = call(["restore-config", path])
    check("그 백업을 restore-config 가 받는다 (왕복)", code == 0 and read(e.paths.server_json) == want, (code, se))
    data_like = os.path.join(e.base, "data_like.tar.gz")
    write_tar(data_like, [("backup.json", b"{}"), ("accounts.json", b"{}"), ("server.json", b"{}")])
    before = read(e.paths.server_json)
    code, so, se = call(["restore-config", data_like])
    check("자료 백업(backup.json 이 든 것)은 설정 복구가 거절, 설정 그대로", code == 1 and read(e.paths.server_json) == before, (code, se))
    no_cfg = os.path.join(e.base, "no_cfg.tar.gz")
    write_tar(no_cfg, [("license.json", b"{}")])
    code, so, se = call(["restore-config", no_cfg])
    check("server.json 이 없는 압축은 설정 복구가 거절", code == 1 and read(e.paths.server_json) == before, (code, se))
    if not REAL_ROOT:
        print("  [건너뜀] 그룹 맞추기는 진짜 root(WSL)에서만")
        return
    # 끝 검토 Fable 5: 다른 장비의 설정 백업이면 서비스 계정 gid 가 다르다 - root 가 아닌 그룹은 지금 서비스 계정 그룹으로
    other = os.path.join(e.base, "other_gid.tar.gz")
    ti = tarfile.TarInfo("server.json")
    ti.size, ti.mode, ti.uid, ti.gid = len(want.encode()), 0o640, 0, 4242
    write_tar(other, [(ti, want.encode())])
    code, so, se = call(["restore-config", other])
    st = os.stat(e.paths.server_json)
    check("다른 장비 백업의 서비스 그룹(4242)은 지금 서비스 계정 그룹(1000)으로, root 소유·0640 그대로",
          code == 0 and (st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode)) == (0, 1000, 0o640), (code, se, st.st_uid, st.st_gid))


REAL_ROOT = POSIX and os.geteuid() == 0                     # WSL 은 root - 진짜로 권한을 내려 보는 시험
AGENT_DIR = os.path.join(ROOT, "firebase", "agent")
SKIP = ("backups", ".service.lock", "before-restore-", ".restore-in-progress")


def test_backup_signal_drops_first():
    """서비스가 돌 때 root 의 backup 은 SIGUSR1 을 보내기 전에 서비스 계정으로 권한을 내린다 - run.json 의 pid 를 다른 사용자의
    프로세스로 바꿔 두어도 그 프로세스는 신호를 받지 않는다 (Codex 중간 검토 4). 진짜 root(WSL)에서 자식 프로세스로 확인한다."""
    if not REAL_ROOT:
        print("  [건너뜀] 진짜 권한 내리기는 리눅스 root(WSL)에서만")
        return
    import pwd
    import signal as sg
    import subprocess
    nob = pwd.getpwnam("nobody")
    base = tempfile.mkdtemp(prefix="sigpid_", dir="/tmp")
    os.chmod(base, 0o755)
    data, etc, logs = (os.path.join(base, n) for n in ("data", "etc", "logs"))
    for d in (data, etc, logs):
        os.makedirs(d, mode=0o700)
        os.chown(d, nob.pw_uid, nob.pw_gid)
    lock_path = os.path.join(data, ".service.lock")
    victim = subprocess.Popen(["sleep", "60"])                       # root 의 다른 프로세스 (SIGUSR1 을 받으면 죽는다)
    holder = open(lock_path, "w")                                    # 서비스가 잠금을 쥐고 있는 흉내 (이 프로세스가 flock)
    os.chown(lock_path, nob.pw_uid, nob.pw_gid)
    import fcntl
    fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    run_json = os.path.join(data, "run.json")
    with open(run_json, "w", encoding="utf-8") as f:
        json.dump({"version": "x", "pid": victim.pid, "started": "2026-11-25T00:00:00", "format": 1}, f)
    os.chown(run_json, nob.pw_uid, nob.pw_gid)
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import server_main; server_main.BACKUP_WAIT = 2; "
            "sys.exit(server_main.main(['backup', '--user', 'nobody']))")
    env = dict(os.environ, AUTOPILOT_DATA=data, AUTOPILOT_ETC=etc, AUTOPILOT_LOGS=logs)
    try:
        r = subprocess.run([sys.executable, "-c", code, AGENT_DIR], capture_output=True, timeout=60, env=env, cwd="/")
        time.sleep(0.5)
        alive = victim.poll() is None
        err = r.stderr.decode("utf-8", "replace")
        check("run.json 의 pid 가 root 의 다른 프로세스면 그 프로세스는 SIGUSR1 을 받지 않는다 (살아 있음)", alive,
              (victim.returncode, r.returncode, err[-400:]))
        check("backup 은 1 (서비스에 알리지 못함)", r.returncode == 1 and "알리지 못했습니다" in err, (r.returncode, err[-400:]))
    finally:
        holder.close()
        if victim.poll() is None:
            victim.send_signal(sg.SIGKILL)
        victim.wait(10)
        shutil.rmtree(base, ignore_errors=True)
    # 차례 (모든 posix): 권한 내리기가 신호보다 먼저
    e = Env("sigorder")
    held = server_main.ServiceLock(e.paths.lock)
    held.try_hold()
    try:
        with open(e.paths.run_json, "w", encoding="utf-8") as f:
            json.dump({"version": "x", "pid": os.getpid(), "started": "2026-11-25T00:00:00", "format": 1}, f)
        events = fake_root()
        real_kill = os.kill

        def kill(pid, sig):
            if sig:
                events.append(("kill", sig))
                return None
            return real_kill(pid, sig)
        server_main.BACKUP_WAIT = 0.3
        os.kill = kill
        try:
            call(["backup"])
        finally:
            os.kill = real_kill
            server_main.BACKUP_WAIT = 60
    finally:
        held.release()
    check("root 의 backup: 권한 내리기 → 신호 차례", [x[0] for x in events] == ["drop", "kill"], events)


CHILD_RESTORE = r'''
import os, sys, time
sys.path.insert(0, sys.argv[1])
import server_backup, server_main
flag, path = sys.argv[2], sys.argv[3]
def pause(name):
    if not os.path.exists(flag):
        with open(flag, "w") as f:
            f.write(name)
        time.sleep(40)
server_backup._TEST_SWAP_PAUSE = pause
try:
    server_backup.restore(server_main.Paths(), path, force=True)
    print("done", flush=True)
except BaseException as e:
    print("raised", type(e).__name__, e, flush=True)
    sys.exit(3)
'''


def test_restore_interrupted():
    """복구 교체 중 SIGTERM·SIGHUP 을 받으면 되돌리고, 막을 수 없는 끊김(SIGKILL)이면 '복구 중' 표시가 남아 run 이 4 (Codex 중간 검토 8)."""
    if not POSIX:
        print("  [건너뜀] 신호 시험은 리눅스(WSL)에서만 (표시가 남은 채 run → 4 는 test_server_main)")
        return
    import signal as sg
    import subprocess
    e = Env("interrupt")
    e.fill()
    path = server_backup.snapshot(None, e.paths)
    acc = local_web.Accounts(e.accounts)                             # 백업 뒤에 자료가 바뀐다
    acc.admin_min = 10
    acc.set("boss", "changed-password-1", "admin")
    before = logical(e.data, skip=SKIP)
    mark = os.path.join(e.data, ".restore-in-progress")
    for sig, label in ((sg.SIGTERM, "SIGTERM"), (sg.SIGHUP, "SIGHUP (SSH 끊김)")):
        flag = os.path.join(e.base, f"flag_{label[:7]}")
        p = subprocess.Popen([sys.executable, "-c", CHILD_RESTORE, AGENT_DIR, flag, path], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, cwd="/")
        reached = until(lambda: os.path.exists(flag), 30)
        check(f"[{label}] 교체 구간에 들어갔다 (옮기기 하나 뒤)", reached)
        p.send_signal(sig)
        out = p.communicate(timeout=60)[0].decode("utf-8", "replace")
        check(f"[{label}] 자료는 복구 전 그대로 (되돌림)", logical(e.data, skip=SKIP) == before,
              (out[-300:], set(logical(e.data, skip=SKIP)) ^ set(before)))
        check(f"[{label}] 되돌린 뒤 '복구 중' 표시는 지운다", not os.path.lexists(mark), out[-300:])
        check(f"[{label}] 되돌렸다는 예외로 끝난다", "raised" in out and "되돌" in out, out[-300:])
        check(f"[{label}] 빈 옮겨 둘 폴더는 남기지 않는다", not [n for n in os.listdir(e.data) if n.startswith("before-restore-")
                                                   and not os.listdir(os.path.join(e.data, n))], os.listdir(e.data))
    # 막을 수 없는 끊김 - 표시가 남고 서비스가 켜지지 않는다, 다시 복구하면 된다
    flag = os.path.join(e.base, "flag_kill")
    p = subprocess.Popen([sys.executable, "-c", CHILD_RESTORE, AGENT_DIR, flag, path], stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, cwd="/")
    until(lambda: os.path.exists(flag), 30)
    p.send_signal(sg.SIGKILL)
    p.communicate(timeout=60)
    check("SIGKILL 이면 '복구 중' 표시(.restore-in-progress, 0600)가 남는다", os.path.isfile(mark) and mode(mark) == 0o600,
          os.listdir(e.data))
    info = json.loads(read(mark) or "{}")
    check("표시 안에 시각과 옮겨 둔 폴더 이름", str(info.get("aside", "")).startswith("before-restore-") and info.get("started"), info)
    box = []
    t = threading.Thread(target=lambda: box.append(call(["run"])), daemon=True)
    t.start()
    t.join(20)
    if t.is_alive():                                                 # 켜져 버렸다 - 끄고 실패로
        server_main.stop()
        t.join(20)
    code, so, se = box[0] if box else (None, "", "")
    check("표시가 남은 채 run → 4, '복구가 중간에 끊겼습니다'", code == 4 and "복구가 중간에 끊겼습니다" in se and info.get("aside", "?") in se,
          (code, se[-300:]))
    code, so, se = call(["restore", path, "--force"])
    check("restore 를 다시 하면 0, 표시가 지워진다", code == 0 and not os.path.lexists(mark), (code, se))
    check("다시 복구한 자료는 백업 때 것 (옛 비밀번호)", local_web.Accounts(e.accounts).verify("boss", BOSS_PW) is not None)
    # 표시 자리가 링크여도 따라가지 않는다
    victim = os.path.join(e.base, "mark_victim")
    with open(victim, "w") as f:
        f.write("keep")
    os.symlink(victim, mark)
    code, so, se = call(["restore", path, "--force"])
    check("표시 자리에 링크가 있어도 대상 파일은 그대로", read(victim) == "keep", (code, se))
    check("링크가 있던 자리도 끝나면 비어 있다", not os.path.lexists(mark), (code, se))


try:
    print("백업과 복구 (test_server_backup)")
    for t in (test_backup_contents, test_keep_7, test_backup_consistent_snapshot, test_backup_signal_path, test_backup_schedule,
              test_restore_roundtrip, test_restore_holds_lock, test_restore_refuses_running, test_restore_rejects_bad_names,
              test_restore_other_server, test_restore_newer_format, test_backup_config_root_only,
              test_config_backup_odd_names_and_kind, test_backup_signal_drops_first,
              test_restore_interrupted):
        guard(t.__name__, t)
finally:
    for k in ENV_KEYS:
        os.environ.pop(k, None)
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n실패: {len(fails)}" + (f" ({', '.join(fails)})" if fails else ""))
sys.exit(1 if fails else 0)
