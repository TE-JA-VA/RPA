# -*- coding: utf-8 -*-
"""사내 서버 ④ Task 3 - 서버 입구 server_main run (계획 2026-11-25-lan-4-linux Task 3).
Paths 를 임시 폴더 셋(환경 변수 AUTOPILOT_ETC·DATA·LOGS)으로, 시험 열쇠로 서명한 서버 라이선스, lan_ca 로 만든 인증서,
server.json 은 127.0.0.1 과 미리 고른 빈 포트 (lan_config 가 1024 아래 포트를 받지 않아 포트 0 은 쓸 수 없다).
run 을 별도 스레드에서 돌리고 시험 손잡이 server_main.stop() 으로 끝낸다. 종료 코드 2(라이선스)·3(포트)·4(설정·자료·잠금),
깨진 등록부·저장소면 켜지 않음(M-8), 라이선스의 자리 수, 실행 기록 1년 정리, 기록은 server.log 로.
윈도우·WSL 둘 다에서 돈다 (WSL 의 임시 폴더는 /tmp 아래).
    D:/AX/RPA/.venv/Scripts/python.exe tests/test_server_main.py
    wsl.exe -d Ubuntu -e python3 /mnt/d/AX/RPA_StandAlone/tests/test_server_main.py
"""
import datetime
import hmac
import http.client
import json
import os
import secrets
import shutil
import socket
import ssl
import stat
import subprocess
import sys
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
import local_server  # noqa: E402
import local_store  # noqa: E402
import local_web  # noqa: E402
import pc_registry  # noqa: E402
import seat  # noqa: E402
import server_log  # noqa: E402
import update_sign  # noqa: E402

fails = []
try:
    import server_main  # noqa: E402
except ImportError as e:
    print(f"  [실패] server_main 을 불러오지 못한다 - {e}")
    print("\n실패: 1")
    sys.exit(1)

SERVICE_EUID = lambda: 1000                               # noqa: E731  서비스 계정 흉내 - WSL 은 root 로 돈다
server_main._euid = SERVICE_EUID
TMP = tempfile.mkdtemp(prefix="rpa_server_main_", dir="/tmp" if POSIX else None)
LIC_SECRET, LIC_PUBLIC = update_sign.keygen()             # 시험 라이선스 열쇠 (실제 열쇠는 쓰지 않는다)
BOSS_PW = "pw-1234567890"
GUID = "5c5c5544-0042-3510-8052-b4c04f4e3301"
ENV_KEYS = ("AUTOPILOT_ETC", "AUTOPILOT_DATA", "AUTOPILOT_LOGS")

# 인증 기관·서버 인증서는 한 번만 만든다 (openssl)
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


class Env:
    """시험 하나의 폴더 셋·라이선스·인증서·server.json. 환경 변수와 server_main 의 시험 손잡이를 맞춘다."""

    def __init__(self, name, seats=3, license=True, tls=True, seat_key=True, other_server=False, admin=True):
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
        self.write_config({"listen": "127.0.0.1", "names": [], "allow": ["127.0.0.0/8"],
                           "ports": {"web": self.web_port, "agent": self.agent_port, "phone": phone}})
        self.secret, self.pub = seat.ensure_key(self.data) if seat_key else (None, "ab" * 32)
        self.lic_doc = None
        if license:
            body = {"edition": "standalone", "kind": "server", "company": "시험상사", "cid": "c1",
                    "server_id": ("0" * 32 if other_server else self.server_id), "seat_pub": self.pub, "seats": seats,
                    "issued": "2026-11-25", "modules": {}, "features": {}, "limits": {}}
            self.lic_doc = license_check.sign_body(LIC_SECRET, body)
            with open(self.paths.license, "w", encoding="utf-8") as f:
                json.dump(self.lic_doc, f, ensure_ascii=False)
        if tls:
            place_tls(self.paths)
        fd = os.open(os.path.join(self.data, "security.json"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:     # 2단계 범위 끔 (서비스가 만든 것처럼 0600)
            f.write('{"version":1,"totp_scope":"off","show_own_history":true}')
        if admin:
            acc = local_web.Accounts(os.path.join(self.data, local_web.ACCOUNTS_NAME))
            acc.admin_min = 10
            acc.set("boss", BOSS_PW, "admin")
        self.result, self.thread = [], None

    def write_config(self, data):
        with open(self.paths.server_json, "w", encoding="utf-8") as f:
            json.dump(data, f)

    # --- run ---
    def start(self, wait=True):
        self.thread = threading.Thread(target=lambda: self.result.append(server_main.main(["run"])), daemon=True)
        self.thread.start()
        if wait:
            until(lambda: os.path.isfile(self.paths.run_json) or not self.thread.is_alive(), 30)
        return self

    def run_once(self):
        """끝까지 돌기를 기다린다 (켜지지 않아야 하는 경우) → 종료 코드 또는 None (20초 안에 안 끝남)."""
        self.start(wait=False)
        self.thread.join(20)
        if self.thread.is_alive():
            server_main.stop()
            self.thread.join(10)
            return None
        return self.result[0] if self.result else None

    def stop(self):
        server_main.stop()
        if self.thread is not None:
            self.thread.join(20)
        return self.result[0] if self.result else None

    # --- 요청 ---
    def ctx(self):
        return ssl.create_default_context(cadata=CA_PEM)

    def web(self, method, path, body=None, token=None):
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        hs = {"Host": f"127.0.0.1:{self.web_port}", "Origin": f"https://127.0.0.1:{self.web_port}"}
        if data is not None:
            hs["Content-Type"] = "application/json"
        if token:
            hs["Authorization"] = "Bearer " + token
        c = http.client.HTTPSConnection("127.0.0.1", self.web_port, context=self.ctx(), timeout=15)
        try:
            c.request(method, path, body=data, headers=hs)
            r = c.getresponse()
            raw = r.read()
            try:
                return r.status, json.loads(raw) if raw and raw[:1] in (b"{", b"[") else raw
            except ValueError:
                return r.status, raw
        finally:
            c.close()

    def login(self):
        st, got = self.web("POST", "/api/login", {"id": "boss", "password": BOSS_PW})
        return got.get("token") if st == 200 and isinstance(got, dict) else None

    def enroll_raw(self, text, guid, host):
        """등록 글로 /enroll 을 직접 보낸다 → (상태, 본문, 서명 맞음, 에이전트 열쇠)."""
        info = pc_registry.decode_enrollment(text)
        pc, token = info["pc"], info["token"]
        rand, nonce = secrets.token_hex(32), secrets.token_urlsafe(24)
        proof = pc_registry.enroll_proof(token, pc, rand, guid, host)
        data = json.dumps({"v": 1, "pc": pc, "rand": rand, "guid": guid, "host": host, "nonce": nonce,
                           "proof": proof}).encode("utf-8")
        c = http.client.HTTPSConnection("127.0.0.1", self.agent_port, context=self.ctx(), timeout=15)
        try:
            c.request("POST", "/enroll", body=data, headers={"Host": f"127.0.0.1:{self.agent_port}",
                                                             "Content-Type": "application/json"})
            r = c.getresponse()
            raw, sign = r.read(), r.getheader(local_store.H_SIGN) or ""
        finally:
            c.close()
        agent_key, _ = pc_registry.derive_keys(token, rand)
        signed = bool(sign) and hmac.compare_digest(sign, local_store.response_mac(agent_key, nonce, r.status, raw))
        try:
            body = json.loads(raw)
        except ValueError:
            body = None
        return r.status, body, signed, agent_key


def place_tls(paths):
    """서버 인증서·열쇠·인증 기관 공개 인증서를 Paths 가 읽는 자리에 둔다."""
    for src, dst in ((CERT, paths.tls_cert), (KEY, paths.tls_key), (os.path.join(CA_DIR, lan_ca.CA_CERT), paths.tls_ca)):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)


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
        server_main.MACHINE_ID = license_check.MACHINE_ID
        server_main.LICENSE_PUBLIC_KEY = None


# ----------------------------------------------------------------------------------------------------

def test_paths():
    for k in ENV_KEYS:
        os.environ.pop(k, None)
    p = server_main.Paths()
    check("기본 경로 /etc/autopilot·/var/lib/autopilot·/var/log/autopilot",
          (p.etc, p.data, p.logs) == ("/etc/autopilot", "/var/lib/autopilot", "/var/log/autopilot"), (p.etc, p.data, p.logs))
    j = os.path.join
    p = server_main.Paths(etc="E", data="D", logs="L")
    want = {"server_json": j("E", "server.json"), "license": j("E", "license.json"), "ca_dir": j("E", "ca"),
            "tls_dir": j("D", "tls"), "web_tls_dir": j("D", "tls-web"), "store": j("D", "store.json"),
            "runs_db": j("D", "runs.db"), "pcs": j("D", "pcs.json"), "backups": j("D", "backups"),
            "server_log": j("L", "server.log"), "audit_log": j("L", "audit.log"), "lock": j("D", ".service.lock"),
            "format_file": j("D", "FORMAT"), "run_json": j("D", "run.json")}
    got = {k: getattr(p, k) for k in want}
    check("Paths 속성 (설정·자료·기록 자리)", got == want, got)
    check("TLS 파일 셋은 tls_dir 아래", all(os.path.dirname(x).startswith(p.tls_dir) for x in (p.tls_cert, p.tls_key, p.tls_ca)))
    os.environ.update(dict(zip(ENV_KEYS, ("/x/etc", "/x/data", "/x/logs"))))
    p = server_main.Paths()
    check("환경 변수 AUTOPILOT_ETC·DATA·LOGS 가 있으면 그것", (p.etc, p.data, p.logs) == ("/x/etc", "/x/data", "/x/logs")
          and p.from_env, (p.etc, p.data, p.logs))
    check("인자 없으면 도움말과 1", server_main.main([]) == 1)


def test_run_serves():
    e = Env("serves")
    e.start()
    try:
        check("run 이 켜졌다 (run.json 생김, 스레드 살아 있음)", os.path.isfile(e.paths.run_json) and e.thread.is_alive(),
              (e.result, read(e.paths.server_log)[-500:]))
        info = json.loads(read(e.paths.run_json) or "{}")
        check("run.json = {version, pid, started, format}", set(info) == {"version", "pid", "started", "format"}
              and info["pid"] == os.getpid() and info["version"] == server_main.version() and info["format"] == 1, info)
        if POSIX:
            check("run.json 0600", mode(e.paths.run_json) == 0o600, oct(mode(e.paths.run_json)))
            check("FORMAT 이 1 로 생기고 0600", read(e.paths.format_file).strip() == "1" and mode(e.paths.format_file) == 0o600)
        else:
            check("FORMAT 이 1 로 생긴다", read(e.paths.format_file).strip() == "1")
        st, raw = e.web("GET", "/")
        check("웹 포트(https) 로그인 화면 200", st == 200 and b"<" in (raw if isinstance(raw, bytes) else b""), st)
        token = e.login()
        check("관리자 로그인", bool(token))
        st, got = e.web("POST", "/api/pcs", {"label": "입구 시험"}, token)
        text = got.get("enrollment") if st == 200 and isinstance(got, dict) else ""
        check("PC 추가 → 등록 글 (https 에이전트 포트)", bool(text) and
              pc_registry.decode_enrollment(text)["url"] == f"https://127.0.0.1:{e.agent_port}", (st, got))
        st, body, signed, akey = e.enroll_raw(text, GUID, "MAIN-PC")
        check("에이전트 포트(TLS) 등록 200, 새 열쇠로 서명", st == 200 and signed, (st, body))
        body = body or {}
        check("등록 응답에 자리 증명서·서버 라이선스 (입구가 단 seat_secret·license_doc)",
              body.get("server_license") == e.lic_doc and isinstance(body.get("seat"), dict), sorted(body))
        try:
            ok = seat.verify(e.pub, body.get("seat"), GUID)["pc_id"] == "pc_01"
        except Exception as ex:
            ok = ex
        check("자리 증명서가 라이선스의 seat_pub 으로 확인된다", ok is True, ok)
        e.akey, e.token = akey, token
    finally:
        code = e.stop()
    check("stop() 으로 끝나면 0", code == 0, code)
    check("끝나면 run.json 을 지운다", not os.path.exists(e.paths.run_json))
    lk = server_main.ServiceLock(e.paths.lock)
    check("끝나면 서비스 잠금을 놓는다 (다시 잡힌다)", lk.try_hold())
    lk.release()
    log = read(e.paths.server_log)
    check("server.log 에 시작·끝 줄", "사내 서버 시작" in log and "사내 서버 끝" in log, log[-600:])


def test_license_missing_2():
    e = Env("nolic", license=False)
    code = e.run_once()
    check("라이선스 파일이 없으면 2", code == 2, code)
    check("server.log 에 까닭 한 줄 (서버 번호 포함)", "라이선스" in read(e.paths.server_log) and e.server_id in read(e.paths.server_log),
          read(e.paths.server_log)[-300:])
    check("run.json 이 없다", not os.path.exists(e.paths.run_json))


def test_license_other_server_2():
    e = Env("otherlic", other_server=True)
    check("다른 서버의 라이선스면 2", e.run_once() == 2)
    check("기록에 '이 서버의 라이선스가 아닙니다'", "이 서버의 라이선스가 아닙니다" in read(e.paths.server_log))


def test_seat_key_mismatch_2():
    e = Env("seatmis")
    os.remove(os.path.join(e.data, seat.SEAT_KEY))
    seat.ensure_key(e.data)                      # 다른 열쇠
    check("자리 열쇠가 라이선스의 seat_pub 과 다르면 2", e.run_once() == 2)
    check("기록에 '자리 서명 열쇠가 라이선스와 맞지 않습니다'", "자리 서명 열쇠가 라이선스와 맞지 않습니다" in read(e.paths.server_log))


def test_seat_key_lost_with_pcs_4():
    e = Env("seatlost")
    reg = pc_registry.Registry(e.paths.pcs, seats=3)
    reg._save(2, {"pc_01": {"label": "a", "guid": GUID, "host": "H", "agent_key": "k" * 64, "relay_key": "r" * 64,
                            "state": "active", "created_at": 1, "enrolled_at": 1}})
    os.remove(os.path.join(e.data, seat.SEAT_KEY))
    check("등록된 PC 가 있는데 seat.key 가 없으면 4", e.run_once() == 4)
    check("새 seat.key 를 만들지 않는다", not os.path.exists(os.path.join(e.data, seat.SEAT_KEY)))
    check("기록에 백업 복구 안내", "백업" in read(e.paths.server_log), read(e.paths.server_log)[-300:])


def test_config_broken_4():
    e = Env("badcfg")
    with open(e.paths.server_json, "w", encoding="utf-8") as f:
        f.write("{ 깨진")
    check("server.json 이 깨졌으면 4", e.run_once() == 4)
    check("기록에 설정 파일 까닭", "설정 파일" in read(e.paths.server_log), read(e.paths.server_log)[-300:])


def test_tls_missing_4():
    e = Env("notls", tls=False)
    check("TLS 파일이 없으면 4", e.run_once() == 4)
    check("기록에 'autopilot-server cert --renew 를 root 로'", "autopilot-server cert --renew 를 root 로" in read(e.paths.server_log))


def test_port_busy_3():
    e = Env("busy")
    s = socket.socket()
    s.bind(("127.0.0.1", e.agent_port))
    s.listen(1)
    try:
        code = e.run_once()
    finally:
        s.close()
    check("포트를 다른 프로그램이 쓰면 3", code == 3, code)
    check("run.json 이 없다", not os.path.exists(e.paths.run_json))


def test_lock_held_4():
    e = Env("locked")
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import server_main; l = server_main.ServiceLock(sys.argv[2]);"
            "print('held' if l.try_hold() else 'no', flush=True); sys.stdin.read()")
    p = subprocess.Popen([sys.executable, "-c", code, os.path.join(ROOT, "firebase", "agent"), e.paths.lock],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, cwd=ROOT)
    try:
        line = p.stdout.readline().decode().strip()
        check("다른 프로세스가 .service.lock 을 쥐었다", line == "held", line)
        check("잠금을 못 잡으면 4", e.run_once() == 4)
        check("기록에 '다른 작업(복구 또는 계정 초기화)이 자료를 쓰고 있습니다'",
              "다른 작업(복구 또는 계정 초기화)이 자료를 쓰고 있습니다" in read(e.paths.server_log), read(e.paths.server_log)[-300:])
    finally:
        p.stdin.close()
        p.wait(10)


def test_format_newer_4():
    e = Env("format")
    with open(e.paths.format_file, "w", encoding="ascii") as f:
        f.write("2\n")
    check("FORMAT 이 아는 것(1)보다 크면 4", e.run_once() == 4)
    check("FORMAT 파일은 그대로", read(e.paths.format_file).strip() == "2")


def test_refuses_root():
    e = Env("root")
    server_main._euid = lambda: 0
    try:
        code = e.run_once()
    finally:
        server_main._euid = SERVICE_EUID
    check("root(euid 0)로 부르면 4", code == 4, code)
    check("root 로는 기록·잠금·FORMAT 파일을 하나도 만들지 않는다 (root 소유 파일이 생기지 않게)",
          not os.listdir(e.logs) and not os.path.exists(e.paths.lock) and not os.path.exists(e.paths.format_file),
          (os.listdir(e.logs), os.listdir(e.data)))


def test_broken_registry_refuses():
    e = Env("badreg")
    garbage = "{ 쓰레기 pcs"
    with open(e.paths.pcs, "w", encoding="utf-8") as f:
        f.write(garbage)
    check("깨진 pcs.json → 4 (pc_01 부터 다시 매기지 않는다)", e.run_once() == 4)
    check("pcs.json 은 그대로, .broken 으로 옮기지 않는다", read(e.paths.pcs) == garbage and not os.path.exists(e.paths.pcs + ".broken"))
    check("기록에 'PC 등록부가 손상되었습니다. 백업에서 복구하여 주십시오.'",
          "PC 등록부가 손상되었습니다. 백업에서 복구하여 주십시오." in read(e.paths.server_log), read(e.paths.server_log)[-300:])
    with open(e.paths.pcs, "w", encoding="utf-8") as f:
        f.write('{"v": 1, "next": 3, "pcs": []}')
    check("꼴이 틀린 pcs.json (pcs 가 목록) 도 4", e.run_once() == 4)
    raised = None
    try:
        pc_registry.Registry(e.paths.pcs, seats=3)
    except pc_registry.RegistryBroken as ex:
        raised = ex
    check("pc_registry.Registry 는 RegistryBroken 을 낸다", raised is not None)


def test_broken_pc_row_refuses():
    """번호 꼴(pc_NN)이 맞는 행이 깨졌으면 조용히 버리지 않고 RegistryBroken (Codex 중간 검토 9 - 버리면 번호를 다시 쓸 수 있다)."""
    e = Env("badrow")
    good = {"label": "a", "agent_key": "k" * 64, "relay_key": "r" * 64, "state": "active"}
    cases = (("행이 null", None), ("state 가 없음", {"label": "b", "agent_key": "k", "relay_key": "r"}),
             ("state 가 모르는 값", dict(good, state="weird")), ("지우지 않은 PC 인데 열쇠 없음", {"label": "c", "state": "active"}),
             ("relay_key 만 없음", {"label": "d", "agent_key": "k", "state": "disabled"}), ("행이 글", "pc"))
    for label, row in cases:
        text = json.dumps({"v": 1, "next": 4, "pcs": {"pc_01": good, "pc_03": row}})
        with open(e.paths.pcs, "w", encoding="utf-8") as f:
            f.write(text)
        raised = False
        try:
            pc_registry.Registry(e.paths.pcs, seats=5)
        except pc_registry.RegistryBroken:
            raised = True
        check(f"깨진 PC 행({label}) → RegistryBroken", raised)
    check("서비스 run 은 4 (깨진 PC 행)", e.run_once() == 4)
    check("등록부 파일은 그대로", read(e.paths.pcs) == text)
    # 번호 꼴이 아닌 키는 지금처럼 무시한다 (손으로 적은 메모 같은 것)
    with open(e.paths.pcs, "w", encoding="utf-8") as f:
        json.dump({"v": 1, "next": 2, "pcs": {"pc_01": good, "memo": None, "PC_02": {"x": 1}}}, f)
    reg = pc_registry.Registry(e.paths.pcs, seats=5)
    check("번호 꼴이 아닌 키는 무시하고 켜진다 (pc_01 하나)", len(reg.list()) == 1, reg.list())
    removed = {"label": "x", "state": "removed", "removed_at": 1}
    with open(e.paths.pcs, "w", encoding="utf-8") as f:
        json.dump({"v": 1, "next": 2, "pcs": {"pc_01": removed}}, f)
    ok = True
    try:
        pc_registry.Registry(e.paths.pcs, seats=5)
    except pc_registry.RegistryBroken:
        ok = False
    check("지운 PC(removed)는 열쇠가 없어도 된다", ok)


def test_restore_mark_refuses():
    """복구가 중간에 끊겨 '복구 중' 표시(.restore-in-progress)가 남았으면 run 은 4 (Codex 중간 검토 8)."""
    e = Env("restmark")
    mark = os.path.join(e.data, ".restore-in-progress")
    with open(mark, "w", encoding="utf-8") as f:
        f.write(json.dumps({"started": "2026-11-25T10:00:00", "aside": "before-restore-20261125-100000"}))
    check("복구 중 표시가 남아 있으면 4", e.run_once() == 4)
    log = read(e.paths.server_log)
    check("기록에 '복구가 중간에 끊겼습니다' 와 restore 다시·옮겨 둔 폴더 이름", "복구가 중간에 끊겼습니다" in log
          and "autopilot-server restore" in log and "before-restore-20261125-100000" in log, log[-400:])
    check("표시 파일은 그대로", os.path.isfile(mark))
    os.remove(mark)
    e.start()
    try:
        check("표시를 지우면 켜진다", os.path.isfile(e.paths.run_json), e.result)
    finally:
        e.stop()


def test_store_broken_4():
    e = Env("badstore")
    with open(e.paths.store, "w", encoding="utf-8") as f:
        f.write('{"apps": {"rp')
    check("깨진 store.json → 4", e.run_once() == 4)
    check("store.json 은 그대로", read(e.paths.store) == '{"apps": {"rp' and not os.path.exists(e.paths.store + ".broken"))


def test_seats_from_license():
    e = Env("seats", seats=2)
    e.start()
    try:
        token = e.login()
        codes = [e.web("POST", "/api/pcs", {"label": f"자리 {i}"}, token)[0] for i in range(3)]
        check("라이선스 자리 2 → 두 대는 추가, 세 번째는 거절 (409)", codes == [200, 200, 409], codes)
    finally:
        e.stop()


def test_runs_purge():
    db = os.path.join(TMP, "purge", "runs.db")
    runs = local_server.Runs(db)
    now = datetime.datetime(2026, 11, 25, 12, 0, 0)
    for days, rid in ((366, "old"), (364, "keep"), (0, "today")):
        t = (now - datetime.timedelta(days=days)).isoformat(timespec="seconds")
        runs.create("runs/c1", "items", rid, {"pcId": "pc_01", "started_at": t, "date": t[:10]}, pc_id="pc_01")
    runs.create("runs/c1", "items", "nostart", {"pcId": "pc_01"}, pc_id="pc_01")
    before_ms = int((now - datetime.timedelta(days=365)).timestamp() * 1000)
    gone = runs.purge(before_ms)
    left = sorted(d.get("started_at", "-")[:10] for d in runs.query("runs/c1", "items", limit=10))
    check("Runs.purge(before_ms) 는 그보다 앞의 기록만 지운다 → 지운 수 1", gone == 1, gone)
    check("366일 전 기록은 지워지고 364일 전·오늘·시작 시각 없는 기록은 남는다",
          runs.get("runs/c1/items/old", pc_id="pc_01") is None and runs.get("runs/c1/items/keep", pc_id="pc_01") is not None
          and runs.get("runs/c1/items/nostart", pc_id="pc_01") is not None and len(left) == 3, left)
    # 서버 정비 (하루 한 번) - 손 시계
    runs.create("runs/c1", "items", "old2", {"pcId": "pc_01", "started_at": (now - datetime.timedelta(days=366)).isoformat(
        timespec="seconds")}, pc_id="pc_01")
    reg = pc_registry.Registry(os.path.join(TMP, "purge", "pcs.json"), seats=3)
    server_main.maintain(runs, reg, now=now.timestamp())
    check("server_main.maintain(손 시계) 가 1년 지난 실행 기록을 지운다",
          runs.get("runs/c1/items/old2", pc_id="pc_01") is None and runs.get("runs/c1/items/keep", pc_id="pc_01") is not None)
    runs.close()


def test_logs_go_to_files():
    e = Env("logs")
    e.start()
    secrets_seen = []
    try:
        token = e.login()
        st, got = e.web("POST", "/api/pcs", {"label": "기록 시험"}, token)
        text = got.get("enrollment") if isinstance(got, dict) else ""
        st, body, signed, akey = e.enroll_raw(text, GUID, "LOG-PC")
        secrets_seen = [BOSS_PW, token or "-", akey, e.secret.hex(), pc_registry.decode_enrollment(text)["token"]]
    finally:
        e.stop()
    log, audit = read(e.paths.server_log), read(e.paths.audit_log)
    check("server.log 에 시작 줄 (버전·업체·포트)", "사내 서버 시작" in log and f"{e.agent_port}" in log, log[-500:])
    check("PC 추가는 audit.log 에", "PC 추가  번호=pc_01" in audit, audit[-300:])
    check("환경 변수로 정한 경로를 기록에 한 줄", "AUTOPILOT_DATA" in log, log[-500:])
    check("기록에 비밀번호·세션 토큰·PC 열쇠·자리 서명 열쇠·등록 토큰이 없다",
          all(s and s not in log + audit for s in secrets_seen), [s[:6] for s in secrets_seen if s in log + audit])
    check("자료 폴더의 옛 기록 파일(로컬서버_기록.txt)은 쓰지 않는다", not os.path.exists(os.path.join(e.data, local_server.LOG_NAME)))
    if POSIX:
        check("server.log·audit.log 0600", mode(e.paths.server_log) == 0o600 and mode(e.paths.audit_log) == 0o600)
        bad = [n for n in os.listdir(e.data) if os.path.isfile(os.path.join(e.data, n)) and mode(os.path.join(e.data, n)) & 0o077]
        check("자료 폴더의 파일은 모두 남이 못 읽는다 (0600)", not bad, [(n, oct(mode(os.path.join(e.data, n)))) for n in bad])


try:
    print("서버 입구 server_main run (test_server_main)")
    for t in (test_paths, test_run_serves, test_license_missing_2, test_license_other_server_2, test_seat_key_mismatch_2,
              test_seat_key_lost_with_pcs_4, test_config_broken_4, test_tls_missing_4, test_port_busy_3, test_lock_held_4,
              test_format_newer_4, test_refuses_root, test_broken_registry_refuses, test_broken_pc_row_refuses,
              test_restore_mark_refuses, test_store_broken_4,
              test_seats_from_license, test_runs_purge, test_logs_go_to_files):
        guard(t.__name__, t)
finally:
    for k in ENV_KEYS:
        os.environ.pop(k, None)
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n실패: {len(fails)}" + (f" ({', '.join(fails)})" if fails else ""))
sys.exit(1 if fails else 0)
