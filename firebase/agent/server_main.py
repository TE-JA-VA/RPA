# -*- coding: utf-8 -*-
"""사내 서버(리눅스)의 입구 `autopilot-server` (설계 6.2, 계획 2026-11-25-lan-4-linux Task 3·4).

    autopilot-server run      서비스(systemd, 서비스 계정 autopilotd)가 부른다 - 두 포트(웹 8443·에이전트 8444)를 열고 돈다
    autopilot-server request [-o FILE]                 라이선스 요청 파일 (서버 번호·자리 서명 공개 열쇠 - 비밀 값 없음)
    autopilot-server status [--json]                   상태 (도는 프로세스의 버전, 문제가 있으면 1)
    autopilot-server cert --show | --renew [--days N] [--owner U] [--if-expiring N] | --import-web CERT KEY [--chain C]
                                                       (renew·import 는 root, --if-expiring 은 새로 만들었을 때만 종료 코드 10)
    autopilot-server admin-reset ID [--password-stdin] [--clear-2fa] [--create]                         (root, 서비스를 멈춘 뒤)
    autopilot-server verify FILE [--sig SIG]           서버 설치 파일의 서명 확인
    autopilot-server upgrade FILE                      (root) 서명 확인 뒤 풀어 install.sh upgrade --verified-version <버전>
    autopilot-server backup                            자료 백업 (서비스가 돌면 SIGUSR1 로 서비스 안에서, 멈춰 있으면 잠금을 쥐고 직접)
    autopilot-server restore FILE [--force]            백업에서 복구 (서비스를 멈춘 뒤 - 복구 내내 서비스 잠금을 쥔다)
    autopilot-server backup-config                     (root) /etc/autopilot 을 /var/backups/autopilot/etc-YYYYMMDD.tar.gz 로
    autopilot-server restore-config FILE               (root, 서비스를 멈춘 뒤) /etc/autopilot 되살리기

경로 (설계 6.2): 설정 /etc/autopilot (server.json·license.json·ca/), 자료 /var/lib/autopilot (서비스 계정만 - 폴더 700·파일 600),
기록 /var/log/autopilot (server.log·audit.log). 환경 변수 AUTOPILOT_ETC·AUTOPILOT_DATA·AUTOPILOT_LOGS 가 있으면 그것 (시험·WSL 용).

run 의 차례: root 거절 → 기록 자리 → 서비스 잠금(.service.lock, 비차단) → 자료 형식 번호(FORMAT) → server.json → 서버 번호와
서버 라이선스 → PC 등록부(깨졌으면 켜지 않음, M-8) → 자리 서명 열쇠(라이선스의 seat_pub 과 대조) → TLS 파일 셋 → 저장소(깨졌으면
켜지 않음) → 실행 기록 DB → 웹 창구 → 두 포트 → run.json → SIGTERM·SIGINT(또는 시험 손잡이 stop()) 까지 돈다.
종료 코드: 0 정상, 2 라이선스 (systemd 가 다시 켜지 않음), 3 포트를 못 엶, 4 설정·자료가 깨짐·잠금을 못 잡음·root (다시 켜지 않음).
하루 한 번 정비: 1년(365일) 지난 실행 기록 지우기, 지운 지 3일 지난 PC 열쇠 지우기. 같은 스레드가 하루 한 번(server.json 의
backup_hour, 기본 3시) 서비스 안 백업을 뜨고, SIGUSR1 을 받으면 곧바로 뜬다 (server_backup.snapshot - 같은 시점 백업, Task 5).

기록·응답에 열쇠·비밀번호·세션 토큰·인증번호·2단계 비밀 값·자리 서명 열쇠를 싣지 않는다. 표준 라이브러리만, 바깥 연결을 열지 않는다.
"""
import argparse
import datetime
import errno
import getpass
import io
import json
import os
import re
import shutil
import signal
import ssl
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RPA_DIR = os.path.abspath(os.path.join(HERE, "..", ".."))
# 저장소에서는 license_check·update_sign 이 두 폴더 위에 있다. 설치본은 app/ 하나에 모두 있으므로 위 폴더(= /opt/autopilot/releases)를
# 검색 경로에 넣지 않는다 - 그 폴더의 이름(버전 폴더 등)이 모듈로 잡히지 않게 (사내 서버 ④ Task 8)
for _p in ((HERE,) if os.path.isfile(os.path.join(HERE, "license_check.py")) else (HERE, RPA_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lan_ca  # noqa: E402
import lan_config  # noqa: E402
import lan_server  # noqa: E402
import license_check  # noqa: E402
import local_server  # noqa: E402
import local_web  # noqa: E402
import pc_registry  # noqa: E402
import seat  # noqa: E402
import server_backup  # noqa: E402
import server_log  # noqa: E402
import update_sign  # noqa: E402

try:
    import fcntl
except ImportError:                        # 윈도우 (시험만 - 서버는 리눅스에서 돈다)
    fcntl = None
    import msvcrt

ETC, DATA, LOGS = "/etc/autopilot", "/var/lib/autopilot", "/var/log/autopilot"
ENV = ("AUTOPILOT_ETC", "AUTOPILOT_DATA", "AUTOPILOT_LOGS")
FORMAT = 1                                 # 자료 형식 번호 - 이 코드가 아는 가장 큰 것 (Global Constraints)
KEEP_RUNS_DAYS = 365                       # 실행 기록 보관 (1년)
MAINT_SEC = 86400                          # 정비 간격
EXIT_OK, EXIT_LICENSE, EXIT_PORT, EXIT_BROKEN = 0, 2, 3, 4
EXIT_RENEWED = 10                          # cert --renew --if-expiring 이 실제로 새로 만들었다 (인증서 타이머가 그때만 서비스를 다시 켠다)

SERVICE_USER = "autopilotd"                # 서비스 계정 (NT 의 사람 계정 autopilot 과 겹치지 않게 - Codex 검토 14)
REQUEST_NAME = "server_request.json"
BUNDLE_PREFIX = "autopilot-server-"        # 서버 설치 파일 안의 맨 위 폴더 autopilot-server-<버전>/
BUNDLE_VER_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z._-]{0,63}")
OWN_CERT_WARN_DAYS = 14                    # 우리 서버 인증서 - 타이머가 30일 앞에서 다시 만들므로 14일 안이면 타이머가 멈춘 것
WEB_CERT_WARN_DAYS = 30                    # 업체 웹 인증서 - 사람이 새로 넣어야 한다
DISK_WARN_MB = 1024
SH = "/bin/sh"
TICK = 1.0                                 # 정비 스레드가 백업 요청(SIGUSR1)·멈춤을 보는 간격
BACKUP_CHECK_SEC = 60                      # 하루 백업 때가 되었나 보는 간격
BACKUP_RETRY_SEC = 3600                    # 하루 백업이 실패하면 다시 해 보기까지
BACKUP_WAIT = 60                           # backup 명령이 서비스의 백업을 기다리는 시간
CONFIG_BACKUPS = "/var/backups/autopilot"  # root 설정 백업 자리 (시험 손잡이)
# install.sh --root 로 깐 시험 자리 (WSL 시험) - 시험 자리의 실행 글만 이 환경 변수를 싣는다. 진짜 실행 글(server/autopilot-server)은
# AUTOPILOT_* 를 지우고 시작하므로 설치본에서는 늘 비어 있다. 있으면 업그레이드 풀 자리·설정 백업 자리가 그 아래로, install.sh 에도 넘긴다.
ROOT_ENV, SERVICE_USER_ENV, NO_SYSTEMD_ENV = "AUTOPILOT_ROOT", "AUTOPILOT_SERVICE_USER", "AUTOPILOT_NO_SYSTEMD"


def _test_root():
    return os.environ.get(ROOT_ENV) or ""


def _default_user():
    """기본 서비스 계정 - autopilotd. 시험 자리(install.sh --root 의 실행 글)는 AUTOPILOT_SERVICE_USER (설치본 실행 글은 지운다)."""
    return (os.environ.get(SERVICE_USER_ENV) if _test_root() else None) or SERVICE_USER

# 시험 손잡이 - 서버 번호 파일, 라이선스 확인 공개 열쇠(None 이면 실린 것), 버전(None 이면 manifest.json),
# 업데이트 서명 공개 열쇠(None 이면 update_sign 에 실린 것, bytes), 업그레이드 때 풀 자리
MACHINE_ID = license_check.MACHINE_ID
LICENSE_PUBLIC_KEY = None
VERSION = None
UPDATE_PUBLIC_KEY = None
UPGRADE_TMP = "/opt/autopilot"

_stop = threading.Event()
_backup_now = threading.Event()            # SIGUSR1 - 정비 스레드가 곧바로 백업을 뜬다


class Paths:
    """사내 서버의 파일 자리 (설계 6.2). etc·data·logs 를 주지 않으면 환경 변수(AUTOPILOT_*), 그것도 없으면 기본 자리.
    from_env = 환경 변수로 정한 것들 [(이름, 값)] - run 이 기록에 한 줄 남긴다."""

    def __init__(self, etc=None, data=None, logs=None):
        self.from_env = []
        picked = []
        for given, env, default in ((etc, ENV[0], ETC), (data, ENV[1], DATA), (logs, ENV[2], LOGS)):
            if given is None and os.environ.get(env):
                given = os.environ[env]
                self.from_env.append((env, given))
            picked.append(given if given is not None else default)
        self.etc, self.data, self.logs = picked
        j = os.path.join
        self.server_json = j(self.etc, "server.json")
        self.license = j(self.etc, license_check.FILE_NAME)
        self.ca_dir = j(self.etc, "ca")                     # 인증 기관 열쇠 - root 만 (700)
        self.tls_dir = j(self.data, "tls")                  # 서버 인증서·열쇠·인증 기관 공개 인증서 사본 (서비스 계정)
        self.web_tls_dir = j(self.data, "tls-web")          # 업체 웹 인증서 넣을 자리 (8443 만)
        self.store = j(self.data, "store.json")
        self.runs_db = j(self.data, "runs.db")
        self.pcs = j(self.data, pc_registry.PCS_NAME)
        self.backups = j(self.data, "backups")
        self.server_log = j(self.logs, server_log.SERVER_LOG)
        self.audit_log = j(self.logs, server_log.AUDIT_LOG)
        self.lock = j(self.data, ".service.lock")
        self.format_file = j(self.data, "FORMAT")
        self.run_json = j(self.data, "run.json")
        self.seat_key = j(self.data, seat.SEAT_KEY)
        self.restore_mark = j(self.data, server_backup.RESTORE_MARK)    # 복구 중 표시 - 남아 있으면 run 은 4 (Task 8.5)

    # 인증서 쌍은 tls_dir/current/ (lan_ca.replace_pair 가 한 번에 갈아 끼운다 - 읽는 쪽은 current 를 실제 자리로 풀어 두 파일을 읽는다)
    @property
    def tls_cert(self):
        return os.path.join(self.tls_dir, lan_ca.CURRENT, lan_ca.SERVER_CERT)

    @property
    def tls_key(self):
        return os.path.join(self.tls_dir, lan_ca.CURRENT, lan_ca.SERVER_KEY)

    @property
    def tls_ca(self):
        return os.path.join(self.tls_dir, lan_ca.CA_CERT)            # 인증 기관 공개 인증서 사본 (열쇠는 etc/ca 에만)

    @property
    def web_cert(self):
        return os.path.join(self.web_tls_dir, lan_ca.CURRENT, lan_ca.SERVER_CERT)

    @property
    def web_key(self):
        return os.path.join(self.web_tls_dir, lan_ca.CURRENT, lan_ca.SERVER_KEY)


def _pair(cert_path):
    """쌍 폴더(current)를 실제 자리로 풀어 (인증서, 열쇠) - 읽는 사이 갈아 끼워져도 같은 쌍의 두 파일을 읽는다."""
    d = os.path.realpath(os.path.dirname(cert_path))
    return os.path.join(d, lan_ca.SERVER_CERT), os.path.join(d, lan_ca.SERVER_KEY)


class UnsafeLock(OSError):
    """서비스 잠금 파일이 보통 파일이 아니다 (링크·하드링크·폴더) - 그 대상을 열거나 소유자를 바꾸지 않는다."""

    def __init__(self, path):
        super().__init__(errno.EPERM, f"서비스 잠금 파일({path})이 보통 파일이 아닙니다 (링크·하드링크·폴더). 그 대상은 건드리지 "
                                      f"않았습니다 - 무엇인지 확인한 뒤 그 이름만 지우고 다시 하여 주십시오.")

    def __str__(self):
        return self.strerror


def _lock_err(e):
    """잠금 파일을 열지 못한 까닭 한 줄."""
    return str(e) if isinstance(e, UnsafeLock) else f"서비스 잠금 파일을 열지 못했습니다 ({type(e).__name__})."


class ServiceLock:
    """자료 폴더의 서비스 잠금 (.service.lock). 서비스는 켜져 있는 동안 쥐고, 복구·admin-reset 은 이것을 잡아 서비스가 멈췄는지
    본다 (포트 연결 여부로 판단하지 않는다 - Codex 검토 6·10). 리눅스 fcntl.flock(LOCK_EX|LOCK_NB), 윈도우(시험)는 msvcrt.locking.
    같은 프로세스 안에서도 다른 열기끼리는 서로 막는다. 프로세스가 끝나면 운영체제가 놓는다."""

    def __init__(self, path):
        self.path = path
        self.fd = None

    @staticmethod
    def _open(path, create):
        """잠금 파일을 링크를 따라가지 않고 연다 → fd. 자료 폴더는 서비스 계정이 쓸 수 있으므로 .service.lock 이 다른 파일로 가는
        링크·하드링크로 바뀌어 있을 수 있다 - 보통 파일이고 이름이 하나(nlink 1)일 때만 받는다, 아니면 UnsafeLock (Codex 중간 검토 2)."""
        flags = (os.O_RDWR | os.O_CREAT) if create else os.O_RDONLY
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NOCTTY", 0) | getattr(os, "O_BINARY", 0)
        try:
            fd = os.open(path, flags, 0o600)
        except OSError as e:
            if e.errno in (errno.ELOOP, errno.EISDIR, errno.ENOTDIR) or isinstance(e, (IsADirectoryError, NotADirectoryError)):
                raise UnsafeLock(path) from None
            raise
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
                raise UnsafeLock(path)
        except BaseException:
            os.close(fd)
            raise
        return fd

    def try_hold(self, owner=None):
        """비차단으로 잡는다 → 잡았으면 True (이미 쥐고 있어도 True), 다른 쪽이 쥐고 있으면 False. 잠금 파일이 링크·하드링크·폴더면
        UnsafeLock (OSError). owner = (uid, gid): root 가 잡을 때 잠금 파일을 서비스 계정 소유로 둔다 - root 가 새로 만든 0600 파일이면
        서비스가 다시 열지 못해 켜지지 않는다. 소유자는 확인을 지난 fd 로만 바꾼다 (이름을 다시 따라가지 않는다)."""
        if self.fd is not None:
            return True
        fd = self._open(self.path, create=True)
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            os.close(fd)
            return False
        if owner is not None and hasattr(os, "fchown"):
            try:
                if os.fstat(fd).st_uid != owner[0]:
                    os.fchown(fd, *owner)
            except OSError:
                pass
        self.fd = fd
        return True

    @staticmethod
    def held(path):
        """다른 쪽이 이 잠금을 쥐고 있나 → True·False, 열 권한이 없으면 None. 파일을 만들지 않는다 (status 가 root 로 불러도
        root 소유 잠금 파일이 생기지 않게). 링크·하드링크·폴더면 None (따라가지 않는다)."""
        try:
            fd = ServiceLock._open(path, create=False)
        except FileNotFoundError:
            return False
        except OSError:
            return None
        try:
            try:
                if fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(fd, fcntl.LOCK_UN)
                else:
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                return True
            return False
        finally:
            os.close(fd)

    def release(self):
        fd, self.fd = self.fd, None
        if fd is None:
            return
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
            else:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        finally:
            os.close(fd)


def _euid():
    """실행 계정 번호 (윈도우는 -1). 시험이 바꿔 끼운다."""
    return os.geteuid() if hasattr(os, "geteuid") else -1


def _service_ids(user):
    """서비스 계정의 (uid, gid). 리눅스가 아니면 None. 계정이 없으면 KeyError. 시험이 바꿔 끼운다."""
    if os.name != "posix":
        return None
    import pwd
    pw = pwd.getpwnam(user)
    return pw.pw_uid, pw.pw_gid


def _drop_privileges(ids):
    """root 에서 서비스 계정으로 권한을 내린다 (보조 그룹 → 그룹 → 사용자 차례, 되돌릴 수 없다). ids 가 None 이면 아무것도 하지 않는다.
    시험이 바꿔 끼운다 (실제로 내리면 시험 프로세스가 root 로 돌아오지 못한다)."""
    if ids is None:
        return
    uid, gid = ids
    os.setgroups([])
    os.setgid(gid)
    os.setuid(uid)
    if os.getuid() != uid or os.geteuid() != uid:
        raise OSError("서비스 계정으로 권한을 내리지 못했습니다.")


def version():
    """설치된 버전 - 프로그램 폴더의 manifest.json 의 version (설치본은 releases/<버전>/manifest.json), 없으면 'dev'."""
    if VERSION:
        return VERSION
    try:
        with open(os.path.join(os.path.dirname(HERE), "manifest.json"), encoding="utf-8") as f:
            v = json.load(f).get("version")
        return v if isinstance(v, str) and v else "dev"
    except (OSError, ValueError, AttributeError):
        return "dev"


def web_dir():
    """업체 웹 파일 폴더 - 설치본은 app/ 옆의 web/, 저장소에서는 firebase/web (둘 다 이 파일 폴더의 ../web)."""
    return os.path.join(os.path.dirname(HERE), "web")


def stop():
    """돌고 있는 run 을 끝낸다 (SIGTERM 과 같다 - 시험 손잡이)."""
    _stop.set()


def _write_private(path, text, owner=None):
    """글 파일을 0600 으로 원자적으로 쓴다 (임시 파일 → os.replace). owner = (uid, gid) 면 걸기 전에 임시 파일의 fd 로 소유자를
    바꾼다 - 건 뒤 경로로 chown 하지 않는다 (자료 폴더 안 이름은 서비스 계정이 그사이 링크로 바꿀 수 있다, Task 8.6)."""
    folder = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=os.path.basename(path) + ".", suffix=".tmp")   # mkstemp 는 0600, O_EXCL
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            if owner is not None:
                os.fchown(f.fileno(), *owner)
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _json_ok(path):
    """파일이 없거나 { } 로 묶인 JSON 이면 True. 읽을 수 없거나 깨졌으면 False (파일은 건드리지 않는다)."""
    try:
        with open(path, encoding="utf-8") as f:
            return isinstance(json.load(f), dict)
    except FileNotFoundError:
        return True
    except (OSError, ValueError):
        return False


def check_format(paths):
    """자료 형식 번호 → 맞으면 None, 아니면 까닭 글. FORMAT 이 없으면 지금 번호로 쓴다 (0600)."""
    try:
        with open(paths.format_file, encoding="ascii") as f:
            text = f.read().strip()
    except FileNotFoundError:
        _write_private(paths.format_file, f"{FORMAT}\n")
        return None
    except (OSError, UnicodeDecodeError):
        return f"자료 형식 번호 파일({paths.format_file})을 읽지 못했습니다."
    if not text.isdigit():
        return f"자료 형식 번호 파일({paths.format_file})이 손상되었습니다. 백업에서 복구하여 주십시오."
    if int(text) > FORMAT:
        return (f"자료 형식 번호({text})가 이 버전이 아는 것({FORMAT})보다 큽니다. 더 새 버전의 자료입니다 - "
                "새 버전을 다시 설치하여 주십시오.")
    return None


def maintain(runs, registry, now=None):
    """하루 한 번 정비 → 지운 실행 기록 수. 1년(KEEP_RUNS_DAYS) 지난 실행 기록, 지운 지 3일 지난 PC 열쇠 (등록부 purge).
    로그인 이력은 LoginLog.add 가 하루 한 번 스스로 지운다 (그대로). now 는 초 (시험이 손 시계를 넘긴다)."""
    now = time.time() if now is None else now
    gone = runs.purge(int((now - KEEP_RUNS_DAYS * 86400) * 1000))
    registry.purge()
    return gone


def backup_due(newest, hour, now):
    """하루 백업을 뜰 때인가. newest = 가장 새 백업 파일의 시각(초, 없으면 None), hour = backup_hour, now = 지금(초).
    가장 최근에 지난 '그날 hour 시' 보다 앞선 백업밖에 없으면 뜬다 (서비스가 그 시각에 꺼져 있었으면 켜진 뒤 곧바로)."""
    t = datetime.datetime.fromtimestamp(now)
    sched = t.replace(hour=hour, minute=0, second=0, microsecond=0)
    if sched > t:
        sched -= datetime.timedelta(days=1)
    return newest is None or newest < sched.timestamp()


def _newest_backup(paths):
    names = server_backup.backup_names(paths.backups)
    try:
        return max(os.path.getmtime(os.path.join(paths.backups, n)) for n in names) if names else None
    except OSError:
        return None


def _maint_loop(runs, registry, folder, backup=None):
    """정비 스레드. backup = (state, paths, backup_hour) 면 하루 한 번(backup_due)과 SIGUSR1(_backup_now) 때 서비스 안 백업도."""
    last = next_check = retry_at = 0.0
    while not _stop.is_set():
        now = time.time()
        if not last or now - last >= MAINT_SEC:
            last = now
            try:
                n = maintain(runs, registry)
                if n:
                    local_server.log(folder, f"정비  1년 지난 실행 기록 {n}건을 지웠습니다.")
            except Exception as e:                   # 정비 때문에 서버가 멈추지 않는다
                local_server.log(folder, f"정비 오류: {type(e).__name__}")
        if backup is not None:
            state, paths, hour = backup
            asked = _backup_now.is_set()
            _backup_now.clear()
            if asked or (now >= next_check and now >= retry_at):
                next_check = now + BACKUP_CHECK_SEC
                if asked or backup_due(_newest_backup(paths), hour, now):
                    try:
                        made = server_backup.snapshot(state, paths)
                        local_server.log(folder, f"백업을 만들었습니다  {os.path.basename(made)}" + ("  (backup 명령)" if asked else ""))
                    except Exception as e:           # 디스크 부족 등 - 서버는 계속 돈다, 하루 백업은 한 시간 뒤 다시
                        local_server.log(folder, f"백업 오류: {type(e).__name__} {getattr(e, 'strerror', '') or ''}".rstrip())
                        if not asked:
                            retry_at = now + BACKUP_RETRY_SEC
        if _stop.wait(TICK):
            return


def _fail(folder, code, text):
    """켜지 않고 끝내는 까닭 한 줄 - server.log 와 표준 오류(systemd 기록)에 → 종료 코드."""
    local_server.log(folder, f"사내 서버를 켜지 않았습니다 - {text}")
    print(f"autopilot-server: {text}", file=sys.stderr)
    return code


# ----------------------------------------------------------------------------------------------------
# run
# ----------------------------------------------------------------------------------------------------

def cmd_run(args, paths):
    if _euid() == 0:                 # root 로 돌면 자료 폴더에 root 소유 파일이 생겨 서비스가 못 읽는다 - 기록 파일도 만들지 않는다
        print("autopilot-server: 서비스 계정으로 실행하여 주십시오 (root 로는 run 을 하지 않습니다: systemctl start autopilot).",
              file=sys.stderr)
        return EXIT_BROKEN
    if os.name == "posix":
        os.umask(0o077)              # 서비스가 새로 만드는 파일은 서비스 계정만 (DB·기록 포함)
    _stop.clear()
    try:
        os.makedirs(paths.logs, mode=0o700, exist_ok=True)
    except OSError:
        pass
    server_log.configure(paths.server_log, paths.audit_log)
    try:
        if paths.from_env:
            local_server.log(paths.data, "경로를 환경 변수로 정함  " + "  ".join(f"{k}={v}" for k, v in paths.from_env))
        try:
            os.makedirs(paths.data, mode=0o700, exist_ok=True)
        except OSError as e:
            return _fail(paths.data, EXIT_BROKEN, f"자료 폴더를 만들지 못했습니다 ({paths.data}, {type(e).__name__}).")
        lock = ServiceLock(paths.lock)
        try:
            held = lock.try_hold()
        except OSError as e:
            return _fail(paths.data, EXIT_BROKEN, _lock_err(e))
        if not held:
            return _fail(paths.data, EXIT_BROKEN, "다른 작업(복구 또는 계정 초기화)이 자료를 쓰고 있습니다. 끝난 뒤 다시 켜 주십시오.")
        try:
            return _serve(paths)
        finally:
            lock.release()
    finally:
        server_log.configure(None, None)


def _serve(paths):
    folder = paths.data
    mark = server_backup.read_mark(paths.data)       # 복구가 교체 중에 끊겼다 (SIGKILL·전원) - 자료가 섞였을 수 있다
    if mark is not None:
        aside = os.path.join(paths.data, mark["aside"]) if mark.get("aside") else os.path.join(paths.data, server_backup.ASIDE_PREFIX + "<시각>")
        return _fail(folder, EXIT_BROKEN, f"복구가 중간에 끊겼습니다. autopilot-server restore 를 다시 하거나 {aside} 에서 손으로 "
                                          f"되돌려 주십시오. (표시 파일 {paths.restore_mark} - 다 맞춘 뒤 지웁니다)")
    try:
        bad = check_format(paths)
    except OSError as e:
        bad = f"자료 형식 번호 파일을 쓰지 못했습니다 ({type(e).__name__})."
    if bad:
        return _fail(folder, EXIT_BROKEN, bad)
    try:
        cfg = lan_config.load(paths.server_json)
    except lan_config.ConfigError as e:
        return _fail(folder, EXIT_BROKEN, str(e))
    try:
        sid = license_check.server_id(MACHINE_ID)
        lic = license_check.load_server(paths.license, sid, public_key=LICENSE_PUBLIC_KEY)
        with open(paths.license, encoding="utf-8-sig") as f:
            doc = json.load(f)
        license_doc = {"body": doc["body"], "sig": doc["sig"]}       # PC 에 그대로 넘기는 원문 (공급사 서명)
    except license_check.LicenseError as e:
        return _fail(folder, EXIT_LICENSE, str(e))
    except (OSError, ValueError, KeyError, TypeError) as e:
        return _fail(folder, EXIT_LICENSE, f"라이선스 파일을 읽지 못했습니다 ({type(e).__name__}).")
    on_save = (lambda: os.chmod(paths.pcs, 0o600)) if os.name == "posix" else None   # 등록부 잠금 안 - chmod 만 (보류 1)
    try:
        registry = pc_registry.Registry(paths.pcs, seats=lic["seats"], on_save=on_save)
    except pc_registry.RegistryBroken:
        return _fail(folder, EXIT_BROKEN, f"PC 등록부가 손상되었습니다. 백업에서 복구하여 주십시오. ({paths.pcs})")
    except OSError as e:
        return _fail(folder, EXIT_BROKEN, f"PC 등록부를 읽지 못했습니다 ({type(e).__name__}).")
    if not os.path.exists(paths.seat_key) and registry.list():
        return _fail(folder, EXIT_BROKEN, "자리 서명 열쇠(seat.key)가 없습니다. 등록된 PC 가 있어 새로 만들지 않습니다 - "
                                          "백업에서 복구하여 주십시오.")
    try:
        seat_secret, seat_pub = seat.ensure_key(folder)
    except (ValueError, OSError) as e:
        return _fail(folder, EXIT_BROKEN, str(e) if isinstance(e, ValueError) else f"자리 서명 열쇠를 읽지 못했습니다 ({type(e).__name__}).")
    if seat_pub != str(lic.get("seat_pub") or "").lower():
        return _fail(folder, EXIT_LICENSE, f"자리 서명 열쇠가 라이선스와 맞지 않습니다. autopilot-server request 로 요청 파일을 만들어 "
                                           f"라이선스를 다시 받아 주십시오. (서버 번호 {sid})")
    cert, key = _pair(paths.tls_cert)
    for p in (cert, key, paths.tls_ca):
        if not os.path.isfile(p):
            return _fail(folder, EXIT_BROKEN, f"서버 인증서 파일이 없습니다 ({p}). autopilot-server cert --renew 를 root 로 실행하여 주십시오.")
    web_cert, web_key = _pair(paths.web_cert)
    if not (os.path.isfile(web_cert) and os.path.isfile(web_key)):
        web_cert = web_key = None                    # 업체 웹 인증서가 없으면 웹 포트도 우리 인증서
    try:
        ca_pem = lan_ca.ca_pem(os.path.dirname(paths.tls_ca))
    except lan_ca.CaError as e:
        return _fail(folder, EXIT_BROKEN, f"{e} ({paths.tls_ca})")
    if not _json_ok(paths.store):
        return _fail(folder, EXIT_BROKEN, f"저장소 파일이 손상되었습니다. 백업에서 복구하여 주십시오. ({paths.store})")
    if os.name == "posix":
        local_server.lock_key_files(folder)          # 열쇠·계정·등록부 0600, 자료 폴더 0700
    store = local_server.Store(paths.store, volatile=local_server.VOLATILE)
    try:
        runs = local_server.Runs(paths.runs_db)
    except Exception as e:                           # sqlite3.Error 등
        return _fail(folder, EXIT_BROKEN, f"실행 기록 DB 를 열지 못했습니다 ({type(e).__name__}).")
    web = None
    servers = []
    try:
        web = local_web.Web(store, runs, lic, folder, web_dir(), registry=registry)
        # 같은 시점 백업 - 다섯 저장소의 파일 쓰기가 영속 잠금을 같이 잡는다 (요청을 받기 전에)
        server_backup.attach(store, registry, web.accounts, runs, web.login_log)
        state = {"store": store, "registry": registry, "accounts": web.accounts, "runs": runs, "login_log": web.login_log}
        try:
            servers = list(lan_server.make_lan_servers(store, runs, lic, registry, web, cfg, cert, key, ca_pem,
                                                       web_cert=web_cert, web_key=web_key))
        except ssl.SSLError as e:                    # OSError 의 하나 - 포트 문제와 가른다
            return _fail(folder, EXIT_BROKEN, f"서버 인증서를 읽지 못했습니다 ({e.reason or type(e).__name__}). "
                                              "autopilot-server cert --renew 를 root 로 실행하여 주십시오.")
        except OSError as e:
            return _fail(folder, EXIT_PORT, f"포트를 열지 못했습니다 - 웹 {cfg.web_port}·에이전트 {cfg.agent_port} 을(를) 다른 프로그램이 "
                                            f"쓰고 있거나 주소 {cfg.listen} 이(가) 이 서버에 없습니다. ({type(e).__name__})")
        except ValueError as e:
            return _fail(folder, EXIT_BROKEN, str(e))
        for s in servers:
            s.seat_secret, s.license_doc = seat_secret, license_doc
        threads = [threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True) for s in servers]
        for t in threads:
            t.start()
        _write_private(paths.run_json, json.dumps({"version": version(), "pid": os.getpid(),
                                                   "started": datetime.datetime.now().isoformat(timespec="seconds"),
                                                   "format": FORMAT}, ensure_ascii=False) + "\n")
        w, a = servers
        local_server.log(folder, f"사내 서버 시작  버전={version()}  업체={lic.get('cid')}  서버 번호={sid}  자리={lic['seats']}  "
                                 f"웹={cfg.web_listen}:{w.server_address[1]}  에이전트={cfg.listen}:{a.server_address[1]}")
        old = {}
        _backup_now.clear()
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGTERM, signal.SIGINT):
                old[sig] = signal.signal(sig, lambda *_: _stop.set())
            if hasattr(signal, "SIGUSR1"):           # autopilot-server backup - 서비스 안에서 같은 시점 백업
                old[signal.SIGUSR1] = signal.signal(signal.SIGUSR1, lambda *_: _backup_now.set())
        maint = threading.Thread(target=_maint_loop, args=(runs, registry, folder, (state, paths, cfg.backup_hour)),
                                 daemon=True)
        maint.start()
        try:
            while not _stop.wait(1.0):
                pass
        finally:
            for sig, h in old.items():
                signal.signal(sig, h)
        _stop.set()
        maint.join(10)
        return EXIT_OK
    finally:
        for s in servers:
            try:
                s.shutdown()
                s.server_close()
            except Exception:
                pass
        if web is not None and web.login_log is not None:
            try:
                web.login_log.close()                # ③보-1
            except Exception:
                pass
        try:
            runs.close()
        except Exception:
            pass
        if servers:
            try:
                os.remove(paths.run_json)
            except OSError:
                pass
            local_server.log(folder, "사내 서버 끝")


# ----------------------------------------------------------------------------------------------------
# 관리 명령 (계획 Task 4)
# ----------------------------------------------------------------------------------------------------

def _err(text):
    print(f"autopilot-server: {text}", file=sys.stderr)
    return 1


def _need_root(what):
    if _euid() != 0:
        _err(f"{what} 는 root 로 실행하여 주십시오 (sudo autopilot-server ...).")
        return False
    return True


def _pc_count(paths):
    """등록부의 등록된 PC 수 (사용 중·중지) - 파일만 읽는다 (Registry 를 만들지 않는다). 없으면 0, 깨졌으면 ValueError."""
    try:
        with open(paths.pcs, encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return 0
    except (OSError, ValueError):
        raise ValueError("PC 등록부를 읽지 못했습니다.") from None
    rows = raw.get("pcs") if isinstance(raw, dict) else None
    if not isinstance(rows, dict):
        raise ValueError("PC 등록부가 손상되었습니다.")
    return sum(1 for v in rows.values() if isinstance(v, dict) and v.get("state") in ("active", "disabled"))


def _pid_alive(pid):
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if os.name == "posix":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True
    import ctypes                                    # 윈도우 (시험만)
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        return bool(k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259     # STILL_ACTIVE
    finally:
        k32.CloseHandle(h)


def cmd_request(args, paths):
    """서버 번호·자리 서명 공개 열쇠가 든 라이선스 요청 파일 (비밀 값 없음). 자리 열쇠가 없으면 만든다 - 단 등록된 PC 가 있으면
    새로 만들지 않는다 (run 의 종료 코드 4 와 같은 규칙 - 있던 자리 증명서가 모두 쓸모없어진다). root 로 부르면 만든 열쇠와
    자료 폴더 안의 요청 파일을 서비스 계정 소유로 둔다 - 걸기 전에 fd 로 (경로로 chown 하지 않는다), seat.key 가 링크·하드링크면
    따라가지 않고 1 (자료 폴더 안 이름은 서비스 계정이 바꿔 둘 수 있다 - Task 8.6)."""
    owner = None
    if _euid() == 0:
        try:
            owner = _service_ids(args.user)
        except KeyError:
            return _err(f"서비스 계정 {args.user} 이(가) 없습니다.")
    try:
        sid = license_check.server_id(MACHINE_ID)
    except license_check.LicenseError as e:
        return _err(str(e))
    if not os.path.lexists(paths.seat_key):          # 끊어진 링크는 '없음' 이 아니다 (ensure_key 가 거절)
        try:
            n = _pc_count(paths)
        except ValueError as e:
            return _err(f"{e} 백업에서 복구하여 주십시오.")
        if n:
            return _err("자리 서명 열쇠(seat.key)가 없습니다. 등록된 PC 가 있어 새로 만들지 않습니다 - 백업에서 복구하여 주십시오.")
    try:
        os.makedirs(paths.data, mode=0o700, exist_ok=True)
        _, pub = seat.ensure_key(paths.data, owner=owner)
    except ValueError as e:
        return _err(str(e))
    except OSError as e:
        return _err(f"자리 서명 열쇠를 만들지 못했습니다 ({type(e).__name__}).")
    out = os.path.abspath(args.output or os.path.join(paths.data, REQUEST_NAME))
    doc = {"server_id": sid, "seat_pub": pub, "version": version(), "made": datetime.datetime.now().isoformat(timespec="seconds")}
    in_data = owner is not None and os.path.dirname(out) == os.path.abspath(paths.data)
    try:
        # 자료 폴더 안의 파일은 서비스 계정 소유 (백업이 읽는다)
        _write_private(out, json.dumps(doc, ensure_ascii=False, indent=1) + "\n", owner=owner if in_data else None)
    except OSError as e:
        return _err(f"요청 파일을 쓰지 못했습니다 ({out}, {type(e).__name__}).")
    print(out)
    return 0


def collect_status(paths):
    """상태 dict - 설치된 버전, 도는 프로세스(run.json 의 pid 가 살아 있고 서비스 잠금이 잡혀 있을 때만 실행 중), 서버 번호,
    라이선스(업체·자리 수·등록된 PC 수), 인증서 남은 날(에이전트·웹), 마지막 백업, 디스크 남은 공간, problems(사람 말 목록)."""
    problems = []
    st = {"installed_version": version(), "running": False, "running_version": None, "pid": None, "started": None,
          "server_id": None, "license": None, "certs": {}, "last_backup": None, "disk_free_mb": None, "problems": problems}
    try:
        with open(paths.run_json, encoding="utf-8") as f:
            info = json.load(f)
        info = info if isinstance(info, dict) else {}
    except (OSError, ValueError):
        info = {}
    pid = info.get("pid")
    held = ServiceLock.held(paths.lock)
    if _pid_alive(pid) and held is not False:        # 잠금이 없으면 pid 를 다른 프로세스가 다시 받은 것
        st.update(running=True, pid=pid, running_version=info.get("version"), started=info.get("started"))
        if st["running_version"] != st["installed_version"]:
            problems.append(f"도는 버전({st['running_version']})이 설치된 버전({st['installed_version']})과 다릅니다 - "
                            "systemctl restart autopilot")
    else:
        problems.append("서버가 실행 중이 아닙니다 (systemctl status autopilot 으로 까닭을 보십시오).")
    try:
        sid = st["server_id"] = license_check.server_id(MACHINE_ID)
        body = license_check.load_server(paths.license, sid, public_key=LICENSE_PUBLIC_KEY)
        st["license"] = {"company": body.get("company"), "cid": body.get("cid"), "seats": body.get("seats"), "pcs": None}
        st["license"]["pcs"] = _pc_count(paths)
    except (license_check.LicenseError, ValueError) as e:
        problems.append(str(e))
    certs = st["certs"]
    cert = _pair(paths.tls_cert)[0]
    try:
        if not os.path.isfile(cert):
            problems.append("서버 인증서가 없습니다 - autopilot-server cert --renew 를 root 로 실행하여 주십시오.")
        else:
            days = lan_ca.days_left(cert)
            certs["agent"] = {"days_left": days, "source": "ours"}
            if days < OWN_CERT_WARN_DAYS:
                problems.append(f"서버 인증서가 {days}일 뒤 끝납니다 - autopilot-server cert --renew 를 root 로 실행하여 주십시오.")
        wcert = _pair(paths.web_cert)[0]
        if os.path.isfile(wcert):
            days = lan_ca.days_left(wcert)
            certs["web"] = {"days_left": days, "source": "imported"}
            if days < WEB_CERT_WARN_DAYS:
                problems.append(f"업체 웹 인증서가 {days}일 뒤 끝납니다 - 새 인증서를 cert --import-web 으로 넣어 주십시오.")
        elif "agent" in certs:
            certs["web"] = dict(certs["agent"])
    except lan_ca.CaError as e:
        problems.append(f"인증서를 읽지 못했습니다: {e}")
    try:
        found = sorted((os.path.getmtime(os.path.join(paths.backups, n)), n) for n in os.listdir(paths.backups)
                       if n.startswith("autopilot-backup-") and n.endswith(".tar.gz"))
        if found:
            st["last_backup"] = {"file": found[-1][1],
                                 "made": datetime.datetime.fromtimestamp(found[-1][0]).isoformat(timespec="seconds")}
    except OSError:
        pass
    try:
        free = shutil.disk_usage(paths.data if os.path.isdir(paths.data) else os.path.dirname(paths.data) or ".").free
        st["disk_free_mb"] = int(free // (1024 * 1024))
        if st["disk_free_mb"] < DISK_WARN_MB:
            problems.append(f"자료 폴더의 디스크 남은 공간이 {st['disk_free_mb']}MB 입니다.")
    except OSError:
        pass
    return st


def cmd_status(args, paths):
    st = collect_status(paths)
    if args.json:
        print(json.dumps(st, ensure_ascii=False, indent=1))
        return 1 if st["problems"] else 0
    lic, certs, b = st["license"] or {}, st["certs"], st["last_backup"]
    run = (f"실행 중 (pid {st['pid']}, 도는 버전 {st['running_version']}, 시작 {st['started']})" if st["running"] else "실행 중 아님")
    lines = [f"설치된 버전      {st['installed_version']}", f"서버            {run}", f"서버 번호        {st['server_id'] or '-'}",
             (f"라이선스        업체 {lic.get('company')} ({lic.get('cid')}), 자리 {lic.get('seats')}, 등록된 PC {lic.get('pcs')}"
              if lic else "라이선스        확인 안 됨")]
    for key, label in (("agent", "에이전트 인증서"), ("web", "웹 인증서")):
        c = certs.get(key)
        src = {"ours": "우리 인증 기관", "imported": "업체 인증서"}.get((c or {}).get("source"), "")
        lines.append(f"{label}  " + (f"{c['days_left']}일 남음 ({src})" if c else "없음"))
    lines.append("마지막 백업      " + (f"{b['file']} ({b['made']})" if b else "없음"))
    lines.append(f"디스크 남은 공간  {st['disk_free_mb']}MB" if st["disk_free_mb"] is not None else "디스크 남은 공간  -")
    if st["problems"]:
        lines.append("확인할 것")
        lines += [f"  - {p}" for p in st["problems"]]
    print("\n".join(lines))
    return 1 if st["problems"] else 0


def _cert_show(paths):
    rows = [("에이전트(8444)", _pair(paths.tls_cert)[0], "우리 인증 기관")]
    wcert = _pair(paths.web_cert)[0]
    rows.append(("웹(8443)", wcert, "업체 인증서") if os.path.isfile(wcert) else ("웹(8443)", rows[0][1], "우리 인증 기관"))
    code = 0
    for label, path, src in rows:
        if not os.path.isfile(path):
            print(f"{label}  없음 - autopilot-server cert --renew 를 root 로 실행하여 주십시오.")
            code = 1
            continue
        try:
            out = lan_ca._run(None, ["x509", "-in", path, "-noout", "-subject", "-enddate", "-fingerprint", "-sha256"])
            days = lan_ca.days_left(path)
        except lan_ca.CaError as e:
            print(f"{label}  읽지 못함 - {e}")
            code = 1
            continue
        info = dict(ln.split("=", 1) for ln in out.strip().splitlines() if "=" in ln)
        end = info.get("notAfter", "").strip()
        fp = next((v.strip() for k, v in info.items() if "Fingerprint" in k), "")
        print(f"{label}  {src}  남은 날 {days}일  끝 {end}  SHA-256 {fp}")
    return code


def _root_work(paths):
    """root 전용 임시 폴더 (0700) - 설정 폴더(/etc/autopilot, root 소유) 안, 없으면 기본 임시 자리. 서비스 계정이 쓸 수 있는 자료
    폴더 밖에서 발급·검사한다 (Codex 중간 검토 3). 지우는 것은 부르는 쪽."""
    return tempfile.mkdtemp(prefix=".cert-", dir=paths.etc if os.path.isdir(paths.etc) else None)


def _cert_renew(args, paths, owner):
    try:
        cfg = lan_config.load(paths.server_json)
    except lan_config.ConfigError as e:
        return _err(str(e))
    days = args.days
    if not 1 <= days <= lan_ca.SERVER_DAYS:
        return _err(f"--days 는 1~{lan_ca.SERVER_DAYS} 이어야 합니다.")
    names = list(cfg.names)                          # listen 주소 + 이름들 (IP 글자는 lan_ca 가 주소로 옮긴다)
    try:
        lan_ca.make_ca(paths.ca_dir, names, [])      # 있으면 그대로 (다시 만들면 PC 를 모두 다시 등록해야 한다)
        if os.name == "posix":
            os.chmod(paths.ca_dir, 0o700)
        work = _root_work(paths)
        try:
            c, k = lan_ca.issue_server(paths.ca_dir, work, names, [], days=days, backdate_days=1)
            with open(c, encoding="ascii") as f:
                cert_text = f.read()
            with open(k, encoding="ascii") as f:
                key_text = f.read()
            left = lan_ca.days_left(c)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        with open(os.path.join(paths.ca_dir, lan_ca.CA_CERT), encoding="ascii") as f:
            ca_text = f.read()
        # 서비스 쪽(자료 폴더 tls/)에는 링크를 따라가지 않고 넣는다 - 공개 인증서 사본과 서버 쌍
        lan_ca.put_file(paths.tls_dir, lan_ca.CA_CERT, ca_text, owner=owner)
        lan_ca.replace_pair(paths.tls_dir, cert_text, key_text, owner=owner)
    except lan_ca.CaError as e:
        return _err(str(e))
    except OSError as e:
        return _err(f"서버 인증서를 만들지 못했습니다 ({type(e).__name__}: {e.filename or ''}).")
    print(f"서버 인증서를 새로 만들었습니다 (만료까지 {left}일). 서비스를 다시 켜면 새 인증서를 씁니다: systemctl restart autopilot")
    return 0


def _cert_import(args, paths, owner):
    cert_p, key_p = args.import_web
    try:
        with open(cert_p, encoding="ascii") as f:
            cert_text = f.read()
        with open(key_p, encoding="ascii") as f:
            key_text = f.read()
        chain_text = ""
        if args.chain:
            with open(args.chain, encoding="ascii") as f:
                chain_text = f.read()
    except (OSError, UnicodeDecodeError) as e:
        return _err(f"인증서 파일을 읽지 못했습니다 ({type(e).__name__}).")
    full = cert_text.rstrip("\n") + "\n" + (chain_text.rstrip("\n") + "\n" if chain_text.strip() else "")
    try:
        work = _root_work(paths)                     # 열쇠 검사는 자료 폴더 밖 root 전용 자리에서 (Codex 중간 검토 3)
    except OSError as e:
        return _err(f"임시 자리를 만들지 못했습니다 ({type(e).__name__}).")
    try:
        c, k = os.path.join(work, lan_ca.SERVER_CERT), os.path.join(work, lan_ca.SERVER_KEY)
        for p, text in ((c, full), (k, key_text)):
            _write_private(p, text)
        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(c, k)
        except (ssl.SSLError, ValueError, OSError):
            return _err("인증서와 열쇠가 짝이 아니거나 읽을 수 없는 꼴입니다 (PEM 인증서·암호 없는 열쇠).")
        try:
            days = lan_ca.days_left(c)
        except lan_ca.CaError as e:
            return _err(str(e))
        if days < 0:
            return _err("이미 끝난 인증서입니다.")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    try:
        lan_ca.replace_pair(paths.web_tls_dir, full, key_text, owner=owner)     # 폴더 소유자도 연 fd 로 맞춘다
    except lan_ca.CaError as e:
        return _err(str(e))
    except OSError as e:
        return _err(f"업체 웹 인증서를 넣지 못했습니다 ({type(e).__name__}).")
    warn = f" 30일 안에 끝나므로 새 인증서를 곧 넣어 주십시오." if days < WEB_CERT_WARN_DAYS else ""
    print(f"업체 웹 인증서를 넣었습니다 (만료까지 {days}일, 웹 포트만 - 에이전트 포트는 우리 인증서 그대로). "
          f"systemctl restart autopilot 으로 다시 켜 주십시오.{warn}")
    return 0


def cmd_cert(args, paths):
    if args.if_expiring is not None and not args.renew:
        return _err("--if-expiring 은 --renew 와 함께만 씁니다.")
    if args.show:
        return _cert_show(paths)
    if not _need_root("cert --renew·--import-web"):
        return 1
    if args.if_expiring is not None and args.if_expiring < 0:
        return _err("--if-expiring 은 0 이상의 날 수입니다.")
    # root 가 만든 인증서·열쇠는 늘 서비스 계정 소유로 - --owner 가 없어도 기본 서비스 계정 (root 전용 0600 이면 서비스가 못 읽는다,
    # Codex 중간 검토 5). 계정이 없으면 만들지 않는다.
    user = args.owner or _default_user()
    try:
        owner = _service_ids(user)
    except KeyError:
        return _err(f"서비스 계정 {user} 이(가) 없습니다 - 인증서를 서비스가 읽을 수 있게 넘길 계정이 필요합니다 (--owner <계정>).")
    if args.renew:
        if args.if_expiring is None:
            return _cert_renew(args, paths, owner)
        # 인증서 타이머 (autopilot-cert.service): 남은 날이 넉넉하면 그대로 0, 아니면(없거나 못 읽어도) 새로 만들고 EXIT_RENEWED
        cert = _pair(paths.tls_cert)[0]
        try:
            left = lan_ca.days_left(cert) if os.path.isfile(cert) else None
        except lan_ca.CaError:
            left = None
        if left is not None and left > args.if_expiring:
            print(f"서버 인증서가 아직 {left}일 남아 새로 만들지 않았습니다 (기준 {args.if_expiring}일).")
            return 0
        code = _cert_renew(args, paths, owner)
        return EXIT_RENEWED if code == 0 else code
    return _cert_import(args, paths, owner)


def cmd_admin_reset(args, paths):
    """관리자 계정 비밀번호 다시 정하기·2단계 풀기 (root, 서비스가 멈춘 뒤). 차례: 비밀번호 읽기 → 서비스 잠금 잡기(못 잡으면 1) →
    서비스 계정으로 권한 내리기 → 계정 파일 고치기 → audit.log (비밀번호 없이). root 소유 파일이 생기지 않는다 (Codex 검토 6·7)."""
    if not _need_root("admin-reset"):
        return 1
    try:
        owner = _service_ids(args.user)
    except KeyError:
        return _err(f"서비스 계정 {args.user} 이(가) 없습니다.")
    password = None
    if args.password_stdin or args.create or not args.clear_2fa:
        if args.password_stdin:
            password = sys.stdin.readline().rstrip("\r\n")
        else:
            password = getpass.getpass("새 비밀번호: ")
            if getpass.getpass("한 번 더: ") != password:
                return _err("두 비밀번호가 다릅니다.")
    if not os.path.isdir(paths.data):
        return _err(f"자료 폴더가 없습니다 ({paths.data}).")
    lock = ServiceLock(paths.lock)
    try:
        held = lock.try_hold(owner=owner)
    except OSError as e:
        return _err(_lock_err(e))
    if not held:
        return _err("서비스가 돌고 있습니다. systemctl stop autopilot 뒤 다시 실행하여 주십시오.")
    try:
        try:
            _drop_privileges(owner)
        except OSError as e:
            return _err(str(e))
        return _admin_reset_apply(args, paths, password)
    finally:
        lock.release()


def _admin_reset_apply(args, paths, password):
    server_log.configure(paths.server_log, paths.audit_log)
    try:
        acc = local_web.Accounts(os.path.join(paths.data, local_web.ACCOUNTS_NAME))
        acc.admin_min = local_web.LAN_ADMIN_PASSWORD_MIN
        uid = local_web.norm_id(args.id)
        done = []
        try:
            cur = acc.get(uid)
            if password is not None:
                if cur is None and not args.create:
                    return _err(f"없는 계정입니다 ({uid}). 새 관리자 계정은 --create 로 만듭니다.")
                acc.set(uid, password, cur["role"] if cur else "admin", must_change=True)
                done.append("관리자 계정 만듦" if cur is None else "비밀번호 다시 정함")
            if args.clear_2fa:
                done.append("2단계 인증 풀기" if acc.mfa_clear(uid) else "2단계 인증 없음")
        except local_web.NoAccount:
            return _err(f"없는 계정입니다 ({uid}).")
        except ValueError as e:                      # 비밀번호 규칙·아이디 꼴 (WeakPassword 포함)
            return _err(str(e))
        local_server.audit(paths.data, f"관리자 초기화(admin-reset)  아이디={uid}  {', '.join(done)}  (서버 root)")
        print(f"{uid}: {', '.join(done)}." + (" 다음 로그인 때 비밀번호를 바꾸게 됩니다." if password is not None else ""))
        return 0
    finally:
        server_log.configure(None, None)


def verify_bundle(path, sig_path=None):
    """서버 설치 파일(tar.gz)의 서명을 업데이트 공개 열쇠로 확인 → (버전, 파일 바이트). 서명이 맞은 뒤에만 안을 본다:
    맨 위 폴더 하나 autopilot-server-<버전>/, 모든 이름이 그 아래 (절대 경로·'..' 없음), manifest.json 의 version·edition
    standalone·kind server. 아니면 ValueError (사람 말). 확인한 바이트를 그대로 돌려준다 - 다시 읽는 사이 바뀐 파일을 풀지 않게."""
    with open(path, "rb") as f:
        raw = f.read()
    try:
        with open(sig_path or path + ".sig", encoding="ascii") as f:
            sig = bytes.fromhex(f.read().strip())
    except FileNotFoundError:
        raise ValueError(f"서명 파일이 없습니다 ({sig_path or path + '.sig'}).") from None
    except (ValueError, UnicodeDecodeError):
        raise ValueError("서명 파일의 꼴이 올바르지 않습니다.") from None
    pub = UPDATE_PUBLIC_KEY if UPDATE_PUBLIC_KEY is not None else update_sign.public_key()
    if not pub:
        raise ValueError("서명 확인 열쇠가 없습니다.")
    if not update_sign.verify(pub, raw, sig):
        raise ValueError("서명이 맞지 않습니다. 공급사에서 받은 파일을 고치지 말고 그대로 써 주십시오.")
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
            names = tf.getnames()
            tops = {n.split("/", 1)[0] for n in names}
            top = tops.pop() if len(tops) == 1 else ""
            ver = top[len(BUNDLE_PREFIX):] if top.startswith(BUNDLE_PREFIX) else ""
            if not BUNDLE_VER_RE.fullmatch(ver) or any(n.startswith("/") or "\\" in n or ".." in n.split("/") for n in names):
                raise ValueError("이름")
            man = json.load(tf.extractfile(f"{top}/manifest.json"))
    except (tarfile.TarError, KeyError, ValueError, OSError, AttributeError, TypeError):
        raise ValueError("서버 설치 파일의 꼴이 올바르지 않습니다.") from None
    if not isinstance(man, dict) or man.get("version") != ver or man.get("edition") != "standalone" or man.get("kind") != "server":
        raise ValueError("서버 설치 파일이 아닙니다 (PC 업데이트 파일은 업체 웹의 업데이트에서 올립니다).")
    return ver, raw


def cmd_verify(args, paths):
    try:
        ver, _ = verify_bundle(args.file, args.sig)
    except OSError as e:
        return _err(f"파일을 읽지 못했습니다 ({type(e).__name__}).")
    except ValueError as e:
        return _err(str(e))
    print(f"서명 확인됨  버전={ver}")
    return 0


def upgrade_argv(script, ver):
    """install.sh upgrade 를 부를 인자 - 확인한 버전을 넘긴다 (install.sh 가 풀린 폴더의 버전과 견준다). 시험 자리(AUTOPILOT_ROOT)면
    --root·--service-user·--no-systemd 도."""
    argv = [SH, script, "upgrade", "--verified-version", ver]
    root = _test_root()
    if root:
        argv += ["--root", root]
        if os.environ.get(SERVICE_USER_ENV):
            argv += ["--service-user", os.environ[SERVICE_USER_ENV]]
        if os.environ.get(NO_SYSTEMD_ENV):
            argv.append("--no-systemd")
    return argv


def cmd_upgrade(args, paths):
    """서버 업그레이드 (root): 지금 깔린 코드로 FILE 과 FILE.sig 를 먼저 확인하고(틀리면 아무것도 풀지 않음), 확인한 바이트를 임시
    자리(/opt/autopilot/.upgrade-*, releases 와 같은 파일 시스템)에 풀어 그 안의 install.sh upgrade 를 실행한다 (Codex 검토 1).
    끝나면 임시 자리를 지운다. 종료 코드는 install.sh 의 것."""
    if not _need_root("upgrade"):
        return 1
    try:
        ver, raw = verify_bundle(args.file)
    except OSError as e:
        return _err(f"파일을 읽지 못했습니다 ({type(e).__name__}).")
    except ValueError as e:
        return _err(str(e))
    base = _test_root() + UPGRADE_TMP if _test_root() else UPGRADE_TMP
    try:
        os.makedirs(base, exist_ok=True)
        work = tempfile.mkdtemp(prefix=".upgrade-", dir=base)                  # 0700
    except OSError as e:
        return _err(f"풀 자리를 만들지 못했습니다 ({type(e).__name__}).")
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
            tf.extractall(work, filter="data")       # 밖을 가리키는 링크·특수 파일·setuid 비트 거절
        bundle = os.path.join(work, BUNDLE_PREFIX + ver)
        script = os.path.join(bundle, "server", "install.sh")
        if not os.path.isfile(script):
            return _err("설치 파일 안에 server/install.sh 가 없습니다.")
        print(f"서명 확인됨  버전={ver} - 업그레이드를 시작합니다.")
        sys.stdout.flush()
        return subprocess.run(upgrade_argv(script, ver), cwd=bundle).returncode
    except (tarfile.TarError, OSError) as e:
        return _err(f"설치 파일을 풀지 못했습니다 ({type(e).__name__}).")
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ----------------------------------------------------------------------------------------------------
# 백업과 복구 (계획 Task 5)
# ----------------------------------------------------------------------------------------------------

def _run_info(paths):
    try:
        with open(paths.run_json, encoding="utf-8") as f:
            info = json.load(f)
        return info if isinstance(info, dict) else {}
    except (OSError, ValueError):
        return {}


def _owner_or_err(user):
    """root 면 서비스 계정 (uid, gid) (리눅스가 아니면 None), root 가 아니면 None. 계정이 없으면 KeyError."""
    return _service_ids(user) if _euid() == 0 else None


def cmd_backup(args, paths):
    """자료 백업. 서비스가 돌면(잠금이 잡혀 있고 run.json 의 pid 가 살아 있음) 그 pid 에 SIGUSR1 을 보내 서비스가 같은 시점 백업을
    뜨게 하고 새 파일을 BACKUP_WAIT 초 기다린다. 멈춰 있으면 잠금을 쥔 채 직접 뜬다 (root 면 서비스 계정으로 권한을 내린 뒤 -
    백업 파일이 서비스 계정 소유). 서비스가 돌 때도 root 면 run.json 을 읽고 신호를 보내기 전에 서비스 계정으로 권한을 내린다 -
    run.json 은 서비스가 쓸 수 있으므로 그 pid 가 다른 사용자의 프로세스일 수 있다 (Codex 중간 검토 4, 업그레이드 전 백업도 이 길)."""
    held = ServiceLock.held(paths.lock)
    if held is None:
        return _err("서비스 잠금 파일을 열 수 없습니다 - root 나 서비스 계정으로 실행하여 주십시오 (잠금 파일이 링크·하드링크면 "
                    "그 이름만 지우고 다시 하여 주십시오).")
    if held:
        if _euid() == 0:
            try:
                _drop_privileges(_service_ids(args.user))
            except KeyError:
                return _err(f"서비스 계정 {args.user} 이(가) 없습니다.")
            except OSError as e:
                return _err(str(e))
        pid = _run_info(paths).get("pid")
        if not _pid_alive(pid):
            return _err("다른 작업(복구 또는 계정 초기화)이 자료를 쓰고 있거나 서비스가 켜지는 중입니다. 잠시 뒤 다시 실행하여 주십시오.")
        if not hasattr(signal, "SIGUSR1"):
            return _err("이 운영체제에서는 도는 서비스에 백업을 시킬 수 없습니다.")
        before = set(server_backup.backup_names(paths.backups))
        try:
            os.kill(pid, signal.SIGUSR1)
        except PermissionError:
            return _err(f"서비스에 백업을 알리지 못했습니다 - {paths.run_json} 의 pid({pid})가 서비스 계정의 프로세스가 아닙니다. "
                        "systemctl status autopilot 으로 확인하여 주십시오.")
        except OSError as e:
            return _err(f"서비스에 백업을 알리지 못했습니다 ({type(e).__name__}) - root 나 서비스 계정으로 실행하여 주십시오.")
        end = time.time() + BACKUP_WAIT
        while True:
            new = sorted(set(server_backup.backup_names(paths.backups)) - before)
            if new:
                print(os.path.join(paths.backups, new[-1]))
                return 0
            if time.time() >= end:
                return _err(f"서비스가 {BACKUP_WAIT}초 안에 백업을 만들지 못했습니다. {paths.server_log} 를 보아 주십시오.")
            time.sleep(0.2)
    try:
        owner = _owner_or_err(args.user)
    except KeyError:
        return _err(f"서비스 계정 {args.user} 이(가) 없습니다.")
    if not os.path.isdir(paths.data):
        return _err(f"자료 폴더가 없습니다 ({paths.data}).")
    lock = ServiceLock(paths.lock)
    try:
        if not lock.try_hold(owner=owner):
            return _err("다른 작업(복구 또는 계정 초기화)이 자료를 쓰고 있거나 서비스가 켜지는 중입니다. 잠시 뒤 다시 실행하여 주십시오.")
    except OSError as e:
        return _err(_lock_err(e))
    try:
        if _euid() == 0:
            _drop_privileges(owner)
        made = server_backup.snapshot(None, paths)
    except Exception as e:                           # OSError·sqlite3.Error
        return _err(f"백업을 만들지 못했습니다 ({type(e).__name__} {getattr(e, 'strerror', '') or ''}".rstrip() + ").")
    finally:
        lock.release()
    print(made)
    return 0


def cmd_restore(args, paths):
    """백업에서 복구 (서비스를 멈춘 뒤). 차례: 백업 파일 읽기(root 만 읽는 자리여도 되게 권한을 내리기 전에) → 서비스 잠금(못 잡으면 1)
    → root 면 서비스 계정으로 권한 내리기 → server_backup.restore(잠금을 쥔 채) → audit.log. 복구한 파일은 서비스 계정 소유."""
    try:
        owner = _owner_or_err(args.user)
    except KeyError:
        return _err(f"서비스 계정 {args.user} 이(가) 없습니다.")
    try:
        with open(args.file, "rb") as f:
            raw = f.read()
    except OSError as e:
        return _err(f"백업 파일을 읽지 못했습니다 ({type(e).__name__}).")
    if not os.path.isdir(paths.data):
        return _err(f"자료 폴더가 없습니다 ({paths.data}).")
    lock = ServiceLock(paths.lock)
    try:
        if not lock.try_hold(owner=owner):
            return _err(server_backup.STOP_FIRST)
    except OSError as e:
        return _err(_lock_err(e))
    try:
        if _euid() == 0:
            try:
                _drop_privileges(owner)
            except OSError as e:
                return _err(str(e))
        try:
            aside = server_backup.restore(paths, raw, force=args.force, lock=lock)
        except (ValueError, RuntimeError) as e:
            return _err(str(e))
        except OSError as e:
            return _err(f"복구하지 못했습니다 ({type(e).__name__}). 자료는 복구 전 그대로입니다.")
        server_log.configure(paths.server_log, paths.audit_log)
        try:
            local_server.audit(paths.data, f"백업에서 복구  파일={os.path.basename(args.file)}"
                                           + ("  (다른 서버의 백업, --force)" if args.force else ""))
        finally:
            server_log.configure(None, None)
    finally:
        lock.release()
    print(f"복구했습니다. 전의 자료는 {aside} 에 옮겨 두었습니다. systemctl start autopilot 으로 서비스를 켜 주십시오.")
    return 0


def cmd_backup_config(args, paths):
    """(root) 설정 폴더 백업 - CONFIG_BACKUPS/etc-YYYYMMDD.tar.gz, 7개. 기록 파일에는 쓰지 않는다 (root 소유 기록 파일이 생기지 않게)."""
    if not _need_root("backup-config"):
        return 1
    try:
        made = server_backup.config_backup(paths.etc, _test_root() + CONFIG_BACKUPS if _test_root() else CONFIG_BACKUPS)
    except (OSError, ValueError) as e:
        return _err(str(e) if isinstance(e, ValueError) else f"설정 백업을 만들지 못했습니다 ({type(e).__name__}).")
    print(made)
    return 0


def cmd_restore_config(args, paths):
    """(root, 서비스를 멈춘 뒤) 설정 백업으로 /etc/autopilot 되살리기. 서비스 잠금을 쥔 채."""
    if not _need_root("restore-config"):
        return 1
    try:
        owner = _service_ids(args.user)
    except KeyError:
        return _err(f"서비스 계정 {args.user} 이(가) 없습니다.")
    if not os.path.isdir(paths.data):
        return _err(f"자료 폴더가 없습니다 ({paths.data}).")
    lock = ServiceLock(paths.lock)
    try:
        if not lock.try_hold(owner=owner):
            return _err(server_backup.STOP_FIRST)
    except OSError as e:
        return _err(_lock_err(e))
    try:
        aside = server_backup.restore_config(paths.etc, args.file)
    except ValueError as e:
        return _err(str(e))
    except OSError as e:
        return _err(f"설정을 되살리지 못했습니다 ({type(e).__name__}).")
    finally:
        lock.release()
    print("설정을 되살렸습니다." + (f" 전의 설정은 {aside} 에 옮겨 두었습니다." if aside else "")
          + " systemctl start autopilot 으로 서비스를 켜 주십시오.")
    return 0


# ----------------------------------------------------------------------------------------------------
# 명령 줄
# ----------------------------------------------------------------------------------------------------

class _Usage(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):        # argparse 의 종료 코드 2 는 '라이선스' 와 겹친다 - 잘못 쓴 명령은 1
        raise _Usage(message)


def _parser():
    p = _Parser(prog="autopilot-server", description="오토파일럿 사내 서버 관리 명령")
    sub = p.add_subparsers(dest="cmd")
    r = sub.add_parser("run", help="서버를 돈다 (서비스가 부른다 - 서비스 계정으로)")
    r.set_defaults(func=cmd_run)
    r = sub.add_parser("request", help="라이선스 요청 파일 만들기 (서버 번호·자리 서명 공개 열쇠)")
    r.add_argument("-o", "--output", help="요청 파일 자리 (기본 자료 폴더의 server_request.json)")
    r.add_argument("--user", default=SERVICE_USER, help="root 로 부를 때 열쇠를 넘길 서비스 계정")
    r.set_defaults(func=cmd_request)
    r = sub.add_parser("status", help="상태 보기 (문제가 있으면 종료 코드 1)")
    r.add_argument("--json", action="store_true")
    r.set_defaults(func=cmd_status)
    r = sub.add_parser("cert", help="인증서 보기·다시 만들기(root)·업체 웹 인증서 넣기(root)")
    g = r.add_mutually_exclusive_group(required=True)
    g.add_argument("--show", action="store_true")
    g.add_argument("--renew", action="store_true")
    g.add_argument("--import-web", nargs=2, metavar=("CERT", "KEY"))
    r.add_argument("--chain", help="업체 인증서의 중간 인증서 묶음 (--import-web)")
    r.add_argument("--days", type=int, default=lan_ca.SERVER_DAYS)
    r.add_argument("--owner", help="만든 인증서를 넘길 서비스 계정 (주지 않으면 기본 서비스 계정 autopilotd - root 가 만든 인증서도 "
                                    "늘 서비스가 읽는다)")
    r.add_argument("--if-expiring", type=int, metavar="DAYS",
                   help="(--renew 와) 남은 날이 DAYS 를 넘으면 그대로 0, 아니면 새로 만들고 종료 코드 10 (인증서 타이머)")
    r.set_defaults(func=cmd_cert)
    r = sub.add_parser("admin-reset", help="관리자 비밀번호·2단계 인증 다시 정하기 (root, 서비스를 멈춘 뒤)")
    r.add_argument("id")
    r.add_argument("--password-stdin", action="store_true", help="새 비밀번호를 표준 입력 한 줄로")
    r.add_argument("--clear-2fa", action="store_true", help="2단계 인증 풀기")
    r.add_argument("--create", action="store_true", help="없으면 관리자 계정으로 만들기")
    r.add_argument("--user", default=SERVICE_USER, help="권한을 내릴 서비스 계정")
    r.set_defaults(func=cmd_admin_reset)
    r = sub.add_parser("verify", help="서버 설치 파일의 서명 확인")
    r.add_argument("file")
    r.add_argument("--sig", help="서명 파일 (기본 FILE.sig)")
    r.set_defaults(func=cmd_verify)
    r = sub.add_parser("upgrade", help="서버 업그레이드 (root - 서명을 먼저 확인한 뒤 풀어 install.sh upgrade)")
    r.add_argument("file")
    r.set_defaults(func=cmd_upgrade)
    r = sub.add_parser("backup", help="자료 백업 (서비스가 돌면 서비스 안에서)")
    r.add_argument("--user", default=SERVICE_USER, help="root 로 부를 때 권한을 내릴 서비스 계정")
    r.set_defaults(func=cmd_backup)
    r = sub.add_parser("restore", help="백업에서 복구 (서비스를 멈춘 뒤)")
    r.add_argument("file")
    r.add_argument("--force", action="store_true", help="다른 서버의 백업이어도 복구 (라이선스를 다시 받아야 한다)")
    r.add_argument("--user", default=SERVICE_USER, help="root 로 부를 때 권한을 내릴 서비스 계정")
    r.set_defaults(func=cmd_restore)
    r = sub.add_parser("backup-config", help="(root) 설정 폴더 백업")
    r.set_defaults(func=cmd_backup_config)
    r = sub.add_parser("restore-config", help="(root, 서비스를 멈춘 뒤) 설정 폴더 되살리기")
    r.add_argument("file")
    r.add_argument("--user", default=SERVICE_USER, help="서비스 계정 (잠금 파일 소유자)")
    r.set_defaults(func=cmd_restore_config)
    return p


def main(argv=None):
    """명령 줄 입구 → 종료 코드. 인자가 없으면 도움말과 1."""
    argv = sys.argv[1:] if argv is None else list(argv)
    parser = _parser()
    if not argv:
        parser.print_help()
        return 1
    try:
        args = parser.parse_args(argv)
    except _Usage as e:
        print(f"autopilot-server: {e}", file=sys.stderr)
        return 1
    except SystemExit as e:                          # --help
        return e.code if isinstance(e.code, int) else 0
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    return args.func(args, Paths())


if __name__ == "__main__":
    sys.exit(main())
