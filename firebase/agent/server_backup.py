# -*- coding: utf-8 -*-
"""사내 서버(리눅스)의 백업과 복구 (계획 2026-11-25-lan-4-linux Task 5, 설계 6.2 '백업', Codex 검토 8·9·10).

같은 시점 백업 (Codex 검토 9): 서비스가 돌 때 백업은 서비스 안에서 뜬다 (하루 한 번 정비 스레드, autopilot-server backup 의 SIGUSR1).
영속 쓰기 공통 잠금 PERSIST_LOCK 을 저장소(Store)·PC 등록부·계정·실행 기록 DB·로그인 이력 DB 의 쓰기가 같이 잡고 (attach),
snapshot 은 이 잠금을 쥔 채 JSON 파일은 그대로 읽어 메모리에 두고 두 DB 는 SQLite 백업 기능으로 뜬다 - 그래서 백업 안의 등록부·저장소·
계정·두 DB 가 같은 순간의 것이다 (복구 뒤 등록부에 없는 PC 의 명령이 없다). 잠금 차례: 각 저장소의 잠금 → PERSIST_LOCK (JSON 셋),
PERSIST_LOCK → 연결 잠금 (두 DB). snapshot 은 PERSIST_LOCK 을 쥔 채 저장소 잠금을 잡지 않는다 (DB 연결 잠금만).

백업 파일: <자료>/backups/autopilot-backup-YYYYMMDD-HHMMSS.tar.gz (0600, 폴더 0700) 안에 backup.json
{"version", "format", "server_id", "made", "files": {이름: sha256}}. 자료 폴더에서 backups/·uploads/·.service.lock·run.json,
복구 전 사본(before-restore-*), 점으로 시작하는 임시 이름·*.tmp·SQLite 곁 파일(-journal·-wal·-shm) 은 뺀다. 인증서 쌍은 current
링크를 따라가 current/ 이름으로 담는다 (pair-* 폴더는 담지 않는다 - 복구하면 current 가 진짜 폴더, lan_ca 가 다음 갈아 끼우기 때 옮긴다).
keep(7) 를 넘는 옛 백업을 지운다.

복구 (Codex 검토 10): 서비스 잠금(.service.lock)을 잡지 못하면 RuntimeError. 복구 내내 쥐고 있어 그 사이 서비스가 켜지면 잠금을 못 잡아
종료 코드 4 로 끝난다. 압축 안 이름은 정해진 꼴만 (절대 경로·'..'·역슬래시·점으로 시작하는 이름·링크·특수 파일 거절), 지문 확인,
형식 번호가 이 코드보다 크면 거절, 다른 서버의 백업은 force 없이 거절. 먼저 임시 폴더에 다 풀고 나서 지금 자료를
<자료>/before-restore-<시각>/ 으로 옮기고 푼 것을 넣는다 (.service.lock·backups/·uploads/ 는 그대로). 교체 구간은 자료 폴더의
'복구 중' 표시(.restore-in-progress, 0600, 시각과 옮겨 둔 폴더 이름)로 감싸고, 그 사이 SIGTERM·SIGHUP 은 예외로 바꿔 되돌린다.
SIGKILL·전원처럼 막을 수 없는 끊김이면 표시가 남아 서비스 run 이 종료 코드 4 로 멈춘다 (사내 서버 ④ Task 8.5).

설정 백업 (Codex 검토 8, root): /etc/autopilot 전체(설정·라이선스·ca/)를 /var/backups/autopilot/etc-YYYYMMDD.tar.gz (0600) 로, 7개.
표준 라이브러리만. 기록에 열쇠·비밀번호를 싣지 않는다 (백업 파일 안에는 열쇠·계정 해시·2단계 비밀 값이 있어 서비스 계정만 읽는다).
"""
import contextlib
import datetime
import hashlib
import io
import json
import os
import re
import shutil
import signal
import sqlite3
import tarfile
import tempfile
import threading
import time
import zlib

import lan_ca

PERSIST_LOCK = threading.RLock()
PREFIX, SUFFIX = "autopilot-backup-", ".tar.gz"
MANIFEST = "backup.json"
KEEP = 7
SKIP_TOP = ("backups", "uploads", ".service.lock", "run.json", MANIFEST)
RESTORE_MARK = ".restore-in-progress"                           # 복구 교체 중 표시 - 남아 있으면 서비스 run 은 4 (Task 8.5)
KEEP_ON_RESTORE = (".service.lock", "backups", "uploads", RESTORE_MARK)   # 복구가 옮기지 않는 것 (잠금은 쥐고 있는 그 파일이어야 한다)
ASIDE_PREFIX = "before-restore-"
ASIDE_RE = re.compile(r"before-restore-\d{8}-\d{6}(?:-\d+)?")
DB_TAILS = ("-journal", "-wal", "-shm")
DB_OWNERS = {"runs.db": "runs", "logins.db": "login_log"}       # 서비스가 연결을 가진 DB - 그 연결로 뜬다
FIRST = ("pcs.json", "accounts.json", "store.json")             # 이 차례로 읽는다 (잠금 안이라 차례는 뜻이 없지만 시험이 끼어들 자리)
PART_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,127}")      # 이름 조각 - 점으로 시작하지 않는다
NAME_RE = re.compile(r"autopilot-backup-(\d{8}-\d{6})(?:-(\d+))?\.tar\.gz")
CONFIG_RE = re.compile(r"etc-(\d{8})\.tar\.gz")
MAX_DEPTH = 4
MAX_MEMBERS = 20000
MAX_BYTES = 4 * 1024 ** 3                                       # 풀어서 4GB 를 넘는 백업은 받지 않는다
STOP_FIRST = "서비스를 먼저 멈추어 주십시오: systemctl stop autopilot"

# 시험 손잡이 - snapshot 이 잠금 안에서 파일 하나를 읽을 때마다 _TEST_PAUSE(이름), restore 가 다 풀고 옮기기 직전에 _TEST_RESTORE_PAUSE()
_TEST_PAUSE = None
_TEST_RESTORE_PAUSE = None
_TEST_SWAP_PAUSE = None


def attach(*objs):
    """저장소들(Store·Registry·Accounts·Runs·LoginLog)의 쓰기가 PERSIST_LOCK 을 같이 잡게 한다. None 은 건너뛴다."""
    for o in objs:
        if o is not None:
            o.persist_lock = PERSIST_LOCK


def _ident():
    """(설치된 버전, 자료 형식 번호, 서버 번호 또는 None) - server_main 이 가진 값 (서로 부르는 모듈이라 늦게 부른다)."""
    import license_check
    import server_main
    try:
        sid = license_check.server_id(server_main.MACHINE_ID)
    except license_check.LicenseError:
        sid = None
    return server_main.version(), server_main.FORMAT, sid


def _get(state, key):
    if state is None or key is None:
        return None
    return state.get(key) if isinstance(state, dict) else getattr(state, key, None)


def _sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _private_dir(path):
    os.makedirs(path, mode=0o700, exist_ok=True)
    if os.name == "posix":
        os.chmod(path, 0o700)


# ----------------------------------------------------------------------------------------------------
# 백업
# ----------------------------------------------------------------------------------------------------

def _collect(root):
    """자료 폴더에서 담을 보통 파일 → [(상대 이름 'a/b', 실제 경로)]. 빼는 것은 머리글 참고. current 링크는 따라가 그 이름으로."""
    out = []

    def walk(folder, rel, depth):
        for n in sorted(os.listdir(folder)):
            p = os.path.join(folder, n)
            r = f"{rel}/{n}" if rel else n
            if not rel and (n in SKIP_TOP or n.startswith(ASIDE_PREFIX)):
                continue
            if not PART_RE.fullmatch(n) or n.endswith(".tmp") or n.endswith(DB_TAILS):
                continue                             # 점으로 시작하는 임시 이름·반쯤 쓴 파일·SQLite 곁 파일
            if os.path.islink(p):
                if n == lan_ca.CURRENT and os.path.isdir(p) and depth + 1 < MAX_DEPTH:
                    walk(os.path.realpath(p), r, depth + 1)       # 인증서 쌍 - 링크가 가리키는 pair-* 를 current/ 로
                continue                             # 그 밖의 링크는 담지 않는다
            if os.path.isdir(p):
                if n.startswith(lan_ca.PAIR_PREFIX) or depth + 1 >= MAX_DEPTH:
                    continue                         # pair-* 는 current 로만
                walk(p, r, depth + 1)
            elif os.path.isfile(p):
                out.append((r, p))
    walk(root, "", 0)
    return out


def _order(item):
    rel = item[0]
    return (FIRST.index(rel) if rel in FIRST else len(FIRST), rel.endswith(".db") and "/" not in rel, rel)


def _free_name(folder, now):
    stamp = datetime.datetime.fromtimestamp(now).strftime("%Y%m%d-%H%M%S")
    base = os.path.join(folder, PREFIX + stamp)
    if not os.path.exists(base + SUFFIX):
        return base + SUFFIX
    n = 2
    while os.path.exists(f"{base}-{n}{SUFFIX}"):
        n += 1
    return f"{base}-{n}{SUFFIX}"


def backup_names(folder):
    """folder 안의 백업 파일 이름 - 오래된 것부터 (이름의 시각·같은 초의 번호 차례). 없으면 []."""
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    found = []
    for n in names:
        m = NAME_RE.fullmatch(n)
        if m:
            found.append(((m.group(1), int(m.group(2) or 1)), n))
    return [n for _, n in sorted(found)]


def _prune(folder, keep, names_of):
    names = names_of(folder)
    for n in names[:max(0, len(names) - max(1, int(keep)))]:
        try:
            os.remove(os.path.join(folder, n))
        except OSError:
            pass


def _tar_add(tf, name, data, mtime):
    ti = tarfile.TarInfo(name)
    ti.size, ti.mode, ti.mtime = len(data), 0o600, int(mtime)
    ti.uid = ti.gid = 0
    ti.uname = ti.gname = ""
    tf.addfile(ti, io.BytesIO(data))


def _db_copy(src_path, dst_path):
    """서비스가 열지 않은 DB 파일 (서비스가 멈췄을 때) - 새 연결로 SQLite 백업 기능."""
    src = sqlite3.connect(src_path)
    try:
        dst = sqlite3.connect(dst_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def snapshot(state, paths, keep=KEEP, now=None):
    """자료 폴더의 같은 시점 백업 → 만든 파일 경로. state = 서비스가 가진 {store, registry, accounts, runs, login_log}
    (dict 나 속성 - 서비스가 멈췄으면 None: 파일·새 DB 연결로). now = 초 (이름·made, 시험이 넘긴다).
    실패하면 예외 (OSError·sqlite3.Error) - 반쯤 만든 파일은 남기지 않는다."""
    now = time.time() if now is None else now
    ver, fmt, sid = _ident()
    _private_dir(paths.backups)
    work = tempfile.mkdtemp(prefix=".snap-", dir=paths.backups)
    try:
        blobs, dbs = {}, {}
        with PERSIST_LOCK:
            for rel, real in sorted(_collect(paths.data), key=_order):
                if "/" not in rel and rel.endswith(".db"):
                    out = os.path.join(work, f"db{len(dbs)}")
                    owner = _get(state, DB_OWNERS.get(rel))
                    if owner is not None:
                        owner.backup_to(out)
                    else:
                        _db_copy(real, out)
                    dbs[rel] = out
                else:
                    with open(real, "rb") as f:
                        blobs[rel] = f.read()
                if _TEST_PAUSE is not None:
                    _TEST_PAUSE(rel)
        files = {rel: hashlib.sha256(b).hexdigest() for rel, b in blobs.items()}
        files.update({rel: _sha_file(p) for rel, p in dbs.items()})
        man = {"version": ver, "format": fmt, "server_id": sid,
               "made": datetime.datetime.fromtimestamp(now).isoformat(timespec="seconds"), "files": dict(sorted(files.items()))}
        tmp = os.path.join(work, "out" + SUFFIX)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(fd, "wb") as raw:
            with tarfile.open(fileobj=raw, mode="w:gz") as tf:
                _tar_add(tf, MANIFEST, json.dumps(man, ensure_ascii=False, indent=1).encode("utf-8"), now)
                for rel in sorted(files):
                    if rel in blobs:
                        _tar_add(tf, rel, blobs[rel], now)
                    else:
                        with open(dbs[rel], "rb") as f:
                            _tar_add(tf, rel, f.read(), now)
            raw.flush()
            os.fsync(raw.fileno())
        final = _free_name(paths.backups, now)
        os.replace(tmp, final)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    _prune(paths.backups, keep, backup_names)
    return final


# ----------------------------------------------------------------------------------------------------
# 복구
# ----------------------------------------------------------------------------------------------------

def _raw(file):
    if isinstance(file, (bytes, bytearray)):
        return bytes(file)
    with open(file, "rb") as f:
        return f.read()


def _open_tar(raw, allow_dirs=True):
    """tar.gz 바이트 → [(TarInfo, 바이트|None)]. 이름·종류를 먼저 모두 보고 하나라도 틀리면 ValueError (아무것도 풀지 않는다)."""
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
            members = tf.getmembers()
            if len(members) > MAX_MEMBERS:
                raise ValueError("백업 안 파일이 너무 많습니다.")
            seen, total = set(), 0
            for m in members:
                name = m.name
                parts = name.split("/")
                if not (m.isfile() or (allow_dirs and m.isdir())):
                    raise ValueError(f"백업 안에 링크나 특수 파일이 있습니다: {name!r}")
                if (name.startswith("/") or "\\" in name or len(parts) > MAX_DEPTH
                        or not all(PART_RE.fullmatch(p) for p in parts)):
                    raise ValueError(f"백업 안 이름이 정해진 꼴이 아닙니다: {name!r}")
                if name in seen:
                    raise ValueError(f"백업 안에 같은 이름이 두 번 있습니다: {name!r}")
                seen.add(name)
                total += max(0, m.size)
                if total > MAX_BYTES:
                    raise ValueError("백업이 너무 큽니다.")
            return [(m, tf.extractfile(m).read() if m.isfile() else None) for m in members]
    except (tarfile.TarError, EOFError, zlib.error, OSError) as e:
        raise ValueError(f"백업 파일의 꼴이 올바르지 않습니다 (tar.gz, {type(e).__name__}).") from None


def _check_backup(entries, force):
    """백업 내용 검사 → {이름: 바이트} (backup.json 뺀 것). 지문·형식 번호·서버 번호."""
    import server_main
    files = {m.name: data for m, data in entries if m.isfile()}
    if MANIFEST not in files:
        raise ValueError("백업 안에 backup.json 이 없습니다 - 오토파일럿 사내 서버의 백업이 아닙니다.")
    try:
        man = json.loads(files.pop(MANIFEST).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise ValueError("backup.json 을 읽지 못했습니다.") from None
    listed = man.get("files") if isinstance(man, dict) else None
    if not isinstance(listed, dict) or not all(isinstance(v, str) for v in listed.values()):
        raise ValueError("backup.json 의 꼴이 올바르지 않습니다.")
    if set(listed) != set(files):
        raise ValueError("백업의 파일 목록(backup.json)과 든 파일이 다릅니다: "
                         + ", ".join(sorted(set(listed) ^ set(files))[:5]))
    for name, data in files.items():
        if hashlib.sha256(data).hexdigest() != listed[name]:
            raise ValueError(f"백업 파일이 손상되었습니다 (지문이 맞지 않음: {name}).")
    fmt = man.get("format")
    if type(fmt) is not int or fmt < 1:
        raise ValueError("backup.json 의 자료 형식 번호가 올바르지 않습니다.")
    if fmt > server_main.FORMAT:
        raise ValueError(f"백업의 자료 형식 번호({fmt})가 이 버전이 아는 것({server_main.FORMAT})보다 큽니다 - 더 새 버전에서 뜬 "
                         "백업입니다. 그 버전을 설치한 뒤 복구하여 주십시오.")
    _, _, sid = _ident()
    if man.get("server_id") != sid and not force:
        raise ValueError(f"다른 서버의 백업입니다. 라이선스를 다시 받아야 합니다 (백업의 서버 번호 {man.get('server_id')}, "
                         f"이 서버 {sid}). 그래도 복구하려면 --force 를 붙여 주십시오.")
    return files


def _free_dir(base):
    path, n = base, 2
    while os.path.exists(path):
        path = f"{base}-{n}"
        n += 1
    return path


class RestoreInterrupted(RuntimeError):
    """복구 교체 중 SIGTERM·SIGHUP 을 받아 되돌렸다 (사람 말)."""


def _mark_path(data):
    return os.path.join(data, RESTORE_MARK)


def _mark_write(data, aside, now):
    """'복구 중' 표시를 새로 쓴다 (0600, 링크를 따라가지 않음, O_EXCL). 지난번에 끊긴 복구의 표시는 이름만 지운다 (링크면 링크만)."""
    p = _mark_path(data)
    try:
        os.unlink(p)
    except FileNotFoundError:
        pass
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps({"started": datetime.datetime.fromtimestamp(now).isoformat(timespec="seconds"),
                            "aside": os.path.basename(aside)}, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def _mark_clear(data):
    try:
        os.unlink(_mark_path(data))
    except FileNotFoundError:
        pass


def read_mark(data):
    """'복구 중' 표시가 있으면 {"started", "aside"} (읽지 못하면 빈 dict), 없으면 None. 링크를 따라가지 않는다 - 링크여도 '있음'."""
    p = _mark_path(data)
    if not os.path.lexists(p):
        return None
    try:
        fd = os.open(p, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
        with os.fdopen(fd, "rb") as f:
            info = json.loads(f.read(4096).decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    if not isinstance(info, dict):
        return {}
    aside = info.get("aside")
    return {"started": str(info.get("started") or ""), "aside": aside if isinstance(aside, str) and ASIDE_RE.fullmatch(aside) else ""}


@contextlib.contextmanager
def _signals_raise():
    """교체 구간: SIGTERM·SIGHUP(SSH 끊김)을 RestoreInterrupted 로 바꿔 되돌리기를 타게 한다 (한 번만 - 되돌리는 동안 오는 신호는
    무시). 주 스레드에서만 (신호 처리기는 주 스레드만 건다). box["quiet"] = True 면 그 뒤 신호는 무시 (다 넣은 뒤)."""
    box = {"got": None, "quiet": False}
    if threading.current_thread() is not threading.main_thread():
        yield box
        return

    def handler(signum, frame):
        if box["got"] is not None or box["quiet"]:
            return
        box["got"] = signum
        raise RestoreInterrupted(signum)
    old = {}
    try:
        for name in ("SIGTERM", "SIGHUP"):
            sig = getattr(signal, name, None)
            if sig is not None:
                old[sig] = signal.signal(sig, handler)
        yield box
    finally:
        for sig, h in old.items():
            signal.signal(sig, h)


def restore(paths, file, force=False, lock=None, now=None):
    """백업 파일(경로 또는 바이트)로 자료 폴더를 되살린다 → 전의 자료를 옮겨 둔 폴더. lock = 이미 쥔 server_main.ServiceLock
    (root 가 권한을 내리기 전에 잡은 것) - 없으면 여기서 비차단으로 잡고 못 잡으면 RuntimeError(STOP_FIRST). 백업이 틀리면 ValueError."""
    import server_main
    own = lock is None
    if own:
        lock = server_main.ServiceLock(paths.lock)
        try:
            held = lock.try_hold()
        except OSError as e:
            raise RuntimeError(server_main._lock_err(e)) from None
        if not held:
            raise RuntimeError(STOP_FIRST)
    try:
        return _restore(paths, _raw(file), force, now)
    finally:
        if own:
            lock.release()


def _restore(paths, raw, force, now):
    files = _check_backup(_open_tar(raw), force)
    now = time.time() if now is None else now
    data = paths.data
    stage = tempfile.mkdtemp(prefix=".restore-", dir=data)       # 0700
    try:
        for name, blob in files.items():
            dst = os.path.join(stage, *name.split("/"))
            os.makedirs(os.path.dirname(dst), mode=0o700, exist_ok=True)
            fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(blob)
                f.flush()
                os.fsync(f.fileno())
        if _TEST_RESTORE_PAUSE is not None:
            _TEST_RESTORE_PAUSE()
        aside = _free_dir(os.path.join(data, ASIDE_PREFIX + datetime.datetime.fromtimestamp(now).strftime("%Y%m%d-%H%M%S")))
        os.mkdir(aside, 0o700)
        moved, placed = [], []
        # 교체 구간 (Codex 중간 검토 8): '복구 중' 표시를 먼저 쓰고, SIGTERM·SIGHUP 은 예외로 바꿔 되돌린다. 막을 수 없는 끊김(SIGKILL·
        # 전원)이면 표시가 남아 서비스 run 이 4 로 멈춘다 - restore 를 다시 하거나 aside 에서 손으로 되돌린다
        with _signals_raise() as box:
            try:
                _mark_write(data, aside, now)
                for n in sorted(os.listdir(data)):
                    p = os.path.join(data, n)
                    if n in KEEP_ON_RESTORE or n.startswith(ASIDE_PREFIX) or p == stage or p == aside:
                        continue
                    os.replace(p, os.path.join(aside, n))
                    moved.append(n)
                    if _TEST_SWAP_PAUSE is not None:
                        _TEST_SWAP_PAUSE(n)
                for n in sorted(os.listdir(stage)):
                    os.replace(os.path.join(stage, n), os.path.join(data, n))
                    placed.append(n)
                box["quiet"] = True                      # 다 넣었다 - 이 뒤 신호로 되돌리지 않는다
                _mark_clear(data)
            except BaseException as e:
                box["quiet"] = True
                failed = []
                for n in placed:                         # 되돌리기 - 넣은 것을 임시 폴더로, 옮긴 것을 제자리로
                    try:
                        os.replace(os.path.join(data, n), os.path.join(stage, n))
                    except OSError:
                        failed.append(n)
                for n in moved:
                    try:
                        os.replace(os.path.join(aside, n), os.path.join(data, n))
                    except OSError:
                        failed.append(n)
                if not failed:                           # 다 되돌렸으면 표시와 빈 옮겨 둘 폴더를 지운다 (못 되돌렸으면 표시를 남긴다)
                    _mark_clear(data)
                    try:
                        os.rmdir(aside)
                    except OSError:
                        pass
                if isinstance(e, RestoreInterrupted):
                    name = {getattr(signal, "SIGTERM", -1): "SIGTERM", getattr(signal, "SIGHUP", -2): "SIGHUP"}.get(box["got"], "신호")
                    if failed:
                        raise RestoreInterrupted(f"복구 중 멈추라는 신호({name})를 받아 되돌렸지만 다 되돌리지 못했습니다 "
                                                 f"({', '.join(failed[:5])}). {aside} 에서 손으로 되돌리거나 restore 를 다시 하여 주십시오.") from None
                    raise RestoreInterrupted(f"복구 중 멈추라는 신호({name})를 받아 되돌렸습니다. 자료는 복구 전 그대로입니다.") from None
                raise
        return aside
    finally:
        shutil.rmtree(stage, ignore_errors=True)


# ----------------------------------------------------------------------------------------------------
# 설정 백업 (root)
# ----------------------------------------------------------------------------------------------------

def config_names(folder):
    try:
        return sorted(n for n in os.listdir(folder) if CONFIG_RE.fullmatch(n))
    except OSError:
        return []


def config_backup(etc, dest, keep=KEEP, now=None):
    """설정 폴더(/etc/autopilot) 전체를 dest/etc-YYYYMMDD.tar.gz (0600, 폴더 0700) 로 → 경로. 같은 날은 새로 덮는다. 링크는 담지 않는다.
    폴더·파일의 권한과 소유자를 담는다 (되살릴 때 그대로 - 서비스가 읽는 설정, root 만 읽는 ca/)."""
    now = time.time() if now is None else now
    if not os.path.isdir(etc):
        raise ValueError(f"설정 폴더가 없습니다 ({etc}).")
    _private_dir(dest)
    final = os.path.join(dest, "etc-" + datetime.datetime.fromtimestamp(now).strftime("%Y%m%d") + SUFFIX)
    fd, tmp = tempfile.mkstemp(prefix=".etc-", suffix=".tmp", dir=dest)           # 0600
    try:
        with os.fdopen(fd, "wb") as raw:
            with tarfile.open(fileobj=raw, mode="w:gz") as tf:
                for d, dirs, names in os.walk(etc):
                    dirs[:] = sorted(x for x in dirs if not os.path.islink(os.path.join(d, x)))
                    rel_d = os.path.relpath(d, etc).replace("\\", "/")
                    for n in sorted(dirs) + sorted(names):
                        p = os.path.join(d, n)
                        rel = n if rel_d == "." else f"{rel_d}/{n}"
                        if os.path.islink(p) or not (os.path.isdir(p) or os.path.isfile(p)):
                            continue
                        ti = tf.gettarinfo(p, arcname=rel)
                        ti.mode &= 0o777
                        if ti.isfile():
                            with open(p, "rb") as f:
                                tf.addfile(ti, f)
                        else:
                            tf.addfile(ti)
            raw.flush()
            os.fsync(raw.fileno())
        os.replace(tmp, final)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    _prune(dest, keep, config_names)
    return final


def restore_config(etc, file, now=None):
    """설정 백업으로 설정 폴더를 되살린다 → 전의 설정을 옮겨 둔 폴더 (<etc>.before-restore-<시각>). 서비스 잠금은 부르는 쪽이 쥔다.
    이름·종류 검사는 백업과 같다. 같은 부모 폴더의 임시 폴더에 다 푼 뒤 이름 바꾸기 두 번 (실패하면 전 설정을 제자리로)."""
    entries = _open_tar(_raw(file))
    now = time.time() if now is None else now
    parent = os.path.dirname(os.path.abspath(etc))
    stage = tempfile.mkdtemp(prefix=".autopilot-restore-", dir=parent)
    root = os.name == "posix" and os.geteuid() == 0
    try:
        for m, blob in sorted(entries, key=lambda x: x[0].name.count("/")):
            dst = os.path.join(stage, *m.name.split("/"))
            if m.isdir():
                os.makedirs(dst, mode=0o700, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(dst), mode=0o700, exist_ok=True)
                fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(blob)
                    f.flush()
                    os.fsync(f.fileno())
            if os.name == "posix":
                os.chmod(dst, (m.mode & 0o777) | (0o700 if m.isdir() else 0))
                if root:
                    os.chown(dst, m.uid, m.gid)
        try:
            st = os.stat(etc)
            if os.name == "posix":
                os.chmod(stage, st.st_mode & 0o777)
                if root:
                    os.chown(stage, st.st_uid, st.st_gid)
        except FileNotFoundError:
            if os.name == "posix":
                os.chmod(stage, 0o755)
        aside = _free_dir(os.path.abspath(etc) + ".before-restore-" + datetime.datetime.fromtimestamp(now).strftime("%Y%m%d-%H%M%S"))
        had = os.path.exists(etc)
        if had:
            os.replace(etc, aside)
        try:
            os.replace(stage, etc)
        except BaseException:
            if had:
                os.replace(aside, etc)
            raise
        return aside if had else None
    finally:
        shutil.rmtree(stage, ignore_errors=True)
