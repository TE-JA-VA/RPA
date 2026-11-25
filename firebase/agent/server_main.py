# -*- coding: utf-8 -*-
"""사내 서버(리눅스)의 입구 `autopilot-server` (설계 6.2, 계획 2026-11-25-lan-4-linux Task 3).

    autopilot-server run      서비스(systemd, 서비스 계정 autopilotd)가 부른다 - 두 포트(웹 8443·에이전트 8444)를 열고 돈다

경로 (설계 6.2): 설정 /etc/autopilot (server.json·license.json·ca/), 자료 /var/lib/autopilot (서비스 계정만 - 폴더 700·파일 600),
기록 /var/log/autopilot (server.log·audit.log). 환경 변수 AUTOPILOT_ETC·AUTOPILOT_DATA·AUTOPILOT_LOGS 가 있으면 그것 (시험·WSL 용).

run 의 차례: root 거절 → 기록 자리 → 서비스 잠금(.service.lock, 비차단) → 자료 형식 번호(FORMAT) → server.json → 서버 번호와
서버 라이선스 → PC 등록부(깨졌으면 켜지 않음, M-8) → 자리 서명 열쇠(라이선스의 seat_pub 과 대조) → TLS 파일 셋 → 저장소(깨졌으면
켜지 않음) → 실행 기록 DB → 웹 창구 → 두 포트 → run.json → SIGTERM·SIGINT(또는 시험 손잡이 stop()) 까지 돈다.
종료 코드: 0 정상, 2 라이선스 (systemd 가 다시 켜지 않음), 3 포트를 못 엶, 4 설정·자료가 깨짐·잠금을 못 잡음·root (다시 켜지 않음).
하루 한 번 정비: 1년(365일) 지난 실행 기록 지우기, 지운 지 3일 지난 PC 열쇠 지우기 (백업은 ④ Task 5 에서 여기에 붙는다).

기록·응답에 열쇠·비밀번호·세션 토큰·인증번호·2단계 비밀 값·자리 서명 열쇠를 싣지 않는다. 표준 라이브러리만, 바깥 연결을 열지 않는다.
"""
import argparse
import datetime
import json
import os
import signal
import ssl
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RPA_DIR = os.path.abspath(os.path.join(HERE, "..", ".."))
for _p in (HERE, RPA_DIR):                 # 설치본은 app/ 하나에 모두 있다 - 저장소에서는 license_check·update_sign 이 위 폴더에
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
import server_log  # noqa: E402

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

# 시험 손잡이 - 서버 번호 파일, 라이선스 확인 공개 열쇠(None 이면 실린 것), 버전(None 이면 manifest.json)
MACHINE_ID = license_check.MACHINE_ID
LICENSE_PUBLIC_KEY = None
VERSION = None

_stop = threading.Event()


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

    @property
    def tls_cert(self):
        return os.path.join(self.tls_dir, lan_ca.SERVER_CERT)

    @property
    def tls_key(self):
        return os.path.join(self.tls_dir, lan_ca.SERVER_KEY)

    @property
    def tls_ca(self):
        return os.path.join(self.tls_dir, lan_ca.CA_CERT)


class ServiceLock:
    """자료 폴더의 서비스 잠금 (.service.lock). 서비스는 켜져 있는 동안 쥐고, 복구·admin-reset 은 이것을 잡아 서비스가 멈췄는지
    본다 (포트 연결 여부로 판단하지 않는다 - Codex 검토 6·10). 리눅스 fcntl.flock(LOCK_EX|LOCK_NB), 윈도우(시험)는 msvcrt.locking.
    같은 프로세스 안에서도 다른 열기끼리는 서로 막는다. 프로세스가 끝나면 운영체제가 놓는다."""

    def __init__(self, path):
        self.path = path
        self.fd = None

    def try_hold(self):
        """비차단으로 잡는다 → 잡았으면 True (이미 쥐고 있어도 True), 다른 쪽이 쥐고 있으면 False."""
        if self.fd is not None:
            return True
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o600)
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            os.close(fd)
            return False
        self.fd = fd
        return True

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


def _write_private(path, text):
    """글 파일을 0600 으로 원자적으로 쓴다 (임시 파일 → os.replace)."""
    folder = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=os.path.basename(path) + ".", suffix=".tmp")   # mkstemp 는 0600
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
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


def _maint_loop(runs, registry, folder):
    while True:
        try:
            n = maintain(runs, registry)
            if n:
                local_server.log(folder, f"정비  1년 지난 실행 기록 {n}건을 지웠습니다.")
        except Exception as e:                       # 정비 때문에 서버가 멈추지 않는다
            local_server.log(folder, f"정비 오류: {type(e).__name__}")
        if _stop.wait(MAINT_SEC):
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
            return _fail(paths.data, EXIT_BROKEN, f"서비스 잠금 파일을 열지 못했습니다 ({paths.lock}, {type(e).__name__}).")
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
    for p in (paths.tls_cert, paths.tls_key, paths.tls_ca):
        if not os.path.isfile(p):
            return _fail(folder, EXIT_BROKEN, f"서버 인증서 파일이 없습니다 ({p}). autopilot-server cert --renew 를 root 로 실행하여 주십시오.")
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
        try:
            servers = list(lan_server.make_lan_servers(store, runs, lic, registry, web, cfg, paths.tls_cert, paths.tls_key, ca_pem))
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
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGTERM, signal.SIGINT):
                old[sig] = signal.signal(sig, lambda *_: _stop.set())
        maint = threading.Thread(target=_maint_loop, args=(runs, registry, folder), daemon=True)
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
