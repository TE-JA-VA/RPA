# -*- coding: utf-8 -*-
"""사내 서버 ④ Task 9 Step 1 - tools/nt_test.py (NT 에 넣고 확인하는 도구) 를 접속 없이 본다 (계획 2026-11-25-lan-4-linux Task 9).
--dry-run 이 만드는 ssh·scp 명령 줄(BatchMode·ConnectTimeout·열쇠·사람 계정·반입 폴더), 접속 정보 파일 읽기(없으면 기본값),
원격 경로 거절, root-script 파일(LF·BOM 없음·set -eux), dry-run 은 자식 프로세스를 하나도 띄우지 않음.
check 는 127.0.0.1 에 포트 0 으로 띄운 사내 서버(make_lan_servers)에 실제로 붙어 본다 (NT 에는 붙지 않는다).
    D:/AX/RPA/.venv/Scripts/python.exe tests/test_nt_tool.py
"""
import contextlib
import dataclasses
import io
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import traceback

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

fails = []
try:
    import nt_test  # noqa: E402
except ImportError as e:
    print(f"  [실패] tools/nt_test.py 를 불러오지 못한다 - {e}")
    print("\n실패: 1")
    sys.exit(1)

TMP = tempfile.mkdtemp(prefix="rpa_nt_tool_", dir="/tmp" if os.name == "posix" else None)
CONF = os.path.join(TMP, "nt.json")
KEY = os.path.join(TMP, "keys", "nt_key")
with open(CONF, "w", encoding="utf-8") as f:
    json.dump({"host": "192.168.1.230", "user": "autopilot", "key": KEY}, f)
PAYLOAD = os.path.join(TMP, "AUTOPILOT_Server_2026.11.26-1_linux-x86_64.tar.gz")
with open(PAYLOAD, "wb") as f:
    f.write(b"payload")


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


class NoChild(Exception):
    pass


def run(*argv, stdin=None):
    """nt_test.main 을 이 프로세스에서 → (종료 코드, 화면 글, 오류 글). 자식 프로세스를 띄우려 하면 NoChild."""
    out, err = io.StringIO(), io.StringIO()
    real, real_in = nt_test.subprocess.run, sys.stdin

    def no_child(*a, **k):
        raise NoChild(a[0] if a else k)

    nt_test.subprocess.run = no_child
    if stdin is not None:
        sys.stdin = io.StringIO(stdin)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = nt_test.main(list(argv))
    finally:
        nt_test.subprocess.run, sys.stdin = real, real_in
    return rc, out.getvalue(), err.getvalue()


def lines_with(text, word):
    return [ln for ln in text.splitlines() if word in ln]


# ----------------------------------------------------------------------------------------------------

def test_config():
    old = {k: os.environ.get(k) for k in ("USERPROFILE", "AUTOPILOT_NT_CONFIG")}
    home = os.path.join(TMP, "home")
    os.makedirs(home, exist_ok=True)
    try:
        os.environ["USERPROFILE"] = home
        os.environ.pop("AUTOPILOT_NT_CONFIG", None)
        path = nt_test.config_path()
        check("접속 정보 기본 자리 = %USERPROFILE%\\.autopilot_nt.json", path == os.path.join(home, ".autopilot_nt.json"), path)
        cfg = nt_test.load_config(path)
        check("파일이 없으면 기본값 (192.168.1.230, autopilot)", (cfg["host"], cfg["user"]) == ("192.168.1.230", "autopilot"), cfg)
        check("기본 열쇠 = %USERPROFILE%\\.ssh\\nt_autopilot 를 푼 경로",
              os.path.normpath(cfg["key"]) == os.path.normpath(os.path.join(home, ".ssh", "nt_autopilot")), cfg["key"])
        check("없는 접속 정보 파일을 만들지 않는다", not os.path.exists(path))
        bad = os.path.join(TMP, "bad.json")
        with open(bad, "w", encoding="utf-8") as f:
            json.dump({"host": "192.168.1.230", "pasword": "x"}, f)
        rc, _, err = run("--config", bad, "--dry-run", "run", "id")
        check("모르는 칸이 있는 접속 정보는 2", rc == 2 and "pasword" in err, (rc, err))
        with open(bad, "w", encoding="utf-8") as f:
            json.dump({"user": "root; rm"}, f)
        rc, _, err = run("--config", bad, "--dry-run", "run", "id")
        check("틀린 user 는 2", rc == 2, (rc, err))
        other = os.path.join(TMP, "other.json")
        with open(other, "w", encoding="utf-8") as f:
            json.dump({"host": "10.0.0.5"}, f)
        os.environ["AUTOPILOT_NT_CONFIG"] = other
        rc, out, _ = run("--dry-run", "run", "id")
        check("AUTOPILOT_NT_CONFIG 의 파일을 읽고 빈 칸은 기본값", rc == 0 and "autopilot@10.0.0.5" in out, out)
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_push():
    rc, out, err = run("--config", CONF, "--dry-run", "push", PAYLOAD)
    ls = [ln for ln in out.splitlines() if ln.startswith("(dry-run) ") and ("ssh" in ln.lower() or "scp" in ln.lower())]
    check("push dry-run 0, 명령 셋 (mkdir → scp → sha256sum)", rc == 0 and len(ls) == 3, (rc, out, err))
    for ln in ls:
        ok = all(w in ln for w in ("-o BatchMode=yes", "-o ConnectTimeout=8", f"-i {KEY}"))
        check(f"BatchMode·ConnectTimeout·열쇠: {ln[10:40]}…", ok, ln)
    name = os.path.basename(PAYLOAD)
    check("mkdir 은 반입 폴더 /home/autopilot/incoming (사람 계정)",
          "autopilot@192.168.1.230" in ls[0] and "mkdir -p -m 0700 /home/autopilot/incoming" in ls[0], ls[:1])
    check("scp 대상 = autopilot@192.168.1.230:/home/autopilot/incoming/<파일 이름>",
          ls[1].endswith(f"autopilot@192.168.1.230:/home/autopilot/incoming/{name}") and "scp" in ls[1].lower(), ls[1:2])
    check("보낸 뒤 원격 sha256sum 으로 견줌", f"sha256sum /home/autopilot/incoming/{name}" in ls[2], ls[2:])
    check("root·sudo 를 쓰지 않는다", "sudo" not in out and "root@" not in out, out)
    rc, out, _ = run("--config", CONF, "--dry-run", "push", PAYLOAD, "u1/new.tar.gz")
    check("DEST 를 주면 반입 폴더 아래 그 자리", rc == 0 and ":/home/autopilot/incoming/u1/new.tar.gz" in out
          and "mkdir -p -m 0700 /home/autopilot/incoming/u1" in out, out)
    for dest in ("../x", "/etc/autopilot/x", "a b", "x;id"):
        rc, out, err = run("--config", CONF, "--dry-run", "push", PAYLOAD, dest)
        check(f"DEST {dest!r} 는 거절 (2)", rc == 2 and "dry-run" not in out, (rc, out, err))
    rc, _, err = run("--config", CONF, "--dry-run", "push", os.path.join(TMP, "none.tar.gz"))
    check("없는 파일은 2", rc == 2, (rc, err))


def test_run_fetch():
    rc, out, _ = run("--config", CONF, "--dry-run", "run", "systemctl is-active autopilot")
    ls = lines_with(out, "(dry-run)")
    check("run 은 ssh 한 줄, 마지막 인자가 명령", rc == 0 and len(ls) == 1 and ls[0].endswith('autopilot@192.168.1.230 "systemctl is-active autopilot"')
          and "-o BatchMode=yes -o ConnectTimeout=8" in ls[0], out)
    argv = nt_test.ssh_argv(nt_test.load_config(CONF), "echo hi")
    check("ssh 인자 목록 = [... user@host, 명령] (명령은 한 덩어리)", argv[-2:] == ["autopilot@192.168.1.230", "echo hi"], argv)
    rc, out, _ = run("--config", CONF, "--dry-run", "fetch", "/var/lib/autopilot/server_request.json")
    want = os.path.join(tempfile.gettempdir(), "autopilot_nt", "server_request.json")
    check("fetch 기본 받을 자리 = %TEMP%\\autopilot_nt\\<이름>",
          rc == 0 and "autopilot@192.168.1.230:/var/lib/autopilot/server_request.json" in out and want in out, out)
    local = os.path.join(TMP, "got", "req.json")
    rc, out, _ = run("--config", CONF, "--dry-run", "fetch", "/home/autopilot/x.json", local)
    check("fetch LOCAL 을 주면 그 자리, dry-run 은 폴더를 만들지 않음", rc == 0 and local in out and not os.path.exists(os.path.dirname(local)), out)
    for bad in ("/home/autopilot/a b", "/tmp/$(id)", "../../etc/shadow", "/tmp/x;id"):
        rc, out, _ = run("--config", CONF, "--dry-run", "fetch", bad)
        check(f"원격 경로 {bad!r} 거절 (2)", rc == 2 and "dry-run" not in out, (rc, out))


def test_check_dry():
    rc, out, _ = run("--config", CONF, "--dry-run", "check")
    check("check dry-run 0", rc == 0, out)
    check("Host 는 '주소:포트' 로 200", "Host: 192.168.1.230:8443 → 200" in out, out)
    check("포트 없는 Host 는 403 을 기대", "Host: 192.168.1.230 → 403" in out, out)
    check("엉뚱한 Host 403", "Host: evil.example → 403" in out, out)
    check("8443·8444 TLS, --ca 없으면 지문만", "8443 TLS 연결 (지문만)" in out and "8444 TLS 연결 (지문만)" in out, out)
    ca = os.path.join(TMP, "ca_cert.pem")
    open(ca, "w").close()
    rc, out, _ = run("--config", CONF, "--dry-run", "check", "--ca", ca, "--web-port", "443", "--closed", "8443")
    check("nginx 앞(443): Host 는 포트 없이 200, 포트 없는 Host 403 줄은 없음",
          rc == 0 and "Host: 192.168.1.230 → 200" in out and "→ 403" in out and "Host: 192.168.1.230 → 403" not in out, out)
    check("--ca 를 주면 인증 기관 이름이 보임, --closed 줄", "인증 기관 ca_cert.pem" in out and "8443 은 이 PC 에서 닿지 않음" in out, out)
    rc, out, _ = run("--config", CONF, "--dry-run", "check", "--agent-port", "0")
    check("--agent-port 0 이면 8444 를 건너뜀", rc == 0 and "8444" not in out, out)
    check("host_header: 443 은 포트 없이, IPv6 는 대괄호",
          (nt_test.host_header("10.0.0.1", 443), nt_test.host_header("10.0.0.1", 8443), nt_test.host_header("fd00::1", 8443))
          == ("10.0.0.1", "10.0.0.1:8443", "[fd00::1]:8443"))
    rc, _, err = run("--config", CONF, "check", "--ca", os.path.join(TMP, "none.pem"))
    check("없는 --ca 파일은 접속 전에 2", rc == 2, (rc, err))


def test_api_dry():
    state = os.path.join(TMP, "secret", "state.json")
    rc, out, _ = run("--config", CONF, "--dry-run", "api", "--state", state)
    check("api dry-run 0, 단계 여섯 줄, Origin = https://주소:포트",
          rc == 0 and len(lines_with(out, "(dry-run) ")) == 8 and "Origin: https://192.168.1.230:8443" in out, out)
    check("api dry-run 은 상태 파일을 만들지 않는다", not os.path.exists(state))
    rc, _, err = run("--config", CONF, "--dry-run", "api")
    check("api 는 --state 가 꼭 있어야 한다 (2)", rc == 2 and "--state" in err, (rc, err))
    rc, _, err = run("--config", CONF, "--dry-run", "api", "--state", state, "--password", "x")
    check("비밀번호를 인자로 받는 선택지는 없다 (2)", rc == 2, (rc, err))


def test_root_script():
    out_dir = os.path.join(TMP, "scratch")
    cmds = ["systemctl stop autopilot", "/opt/autopilot/current/bin/autopilot-server status"]
    rc, out, _ = run("--config", CONF, "--dry-run", "root-script", "perm", *cmds, "--out-dir", out_dir)
    path = os.path.join(out_dir, "nt_root_perm.sh")
    check("root-script dry-run 은 내용만 보이고 쓰지 않음", rc == 0 and not os.path.exists(path) and cmds[0] in out, out)
    rc, out, _ = run("--config", CONF, "root-script", "perm", *cmds, "--out-dir", out_dir)
    check("root-script 가 nt_root_<NAME>.sh 를 씀", rc == 0 and os.path.isfile(path), out)
    raw = open(path, "rb").read() if os.path.isfile(path) else b""
    check("LF·BOM 없음·#!/bin/sh·set -eux", b"\r" not in raw and not raw.startswith(b"\xef\xbb\xbf") and raw.startswith(b"#!/bin/sh\n")
          and b"\nset -eux\n" in raw, raw[:120])
    check("명령이 순서대로 실림", raw.decode("utf-8").rstrip("\n").splitlines()[-2:] == cmds, raw[-200:])
    rc, _, _ = run("--config", CONF, "root-script", "from_in", "--out-dir", out_dir, stdin="ufw status verbose\n\n  \nid -u autopilotd\n")
    got = open(os.path.join(out_dir, "nt_root_from_in.sh"), encoding="utf-8").read().splitlines() if rc == 0 else []
    check("명령이 없으면 표준 입력에서 (빈 줄은 뺌)", got[-2:] == ["ufw status verbose", "id -u autopilotd"], got)
    lst = os.path.join(TMP, "cmds.txt")
    with open(lst, "w", encoding="utf-8-sig") as f:
        f.write("nginx -t\r\nsystemctl reload nginx\r\n")
    rc, _, _ = run("--config", CONF, "root-script", "nginx", "--file", lst, "--out-dir", out_dir)
    raw = open(os.path.join(out_dir, "nt_root_nginx.sh"), "rb").read() if rc == 0 else b""
    check("--file (BOM·CRLF 이어도) → LF 줄", raw.endswith(b"nginx -t\nsystemctl reload nginx\n") and b"\r" not in raw, raw[-80:])
    for bad in ("../x", "a b", "x/y", ""):
        rc, _, _ = run("--config", CONF, "root-script", bad, "id", "--out-dir", out_dir)
        check(f"NAME {bad!r} 거절 (2)", rc == 2, rc)
    rc, _, err = run("--config", CONF, "root-script", "empty", "--out-dir", out_dir, stdin="\n")
    check("명령이 없으면 2", rc == 2 and not os.path.exists(os.path.join(out_dir, "nt_root_empty.sh")), (rc, err))


def test_no_args():
    rc, _, _ = run("--config", CONF)
    check("하위 명령이 없으면 2", rc == 2, rc)
    rc, _, err = run("--config", CONF, "--dry-run", "scp-all")
    check("모르는 하위 명령은 2", rc == 2, (rc, err))


# ----------------------------------------------------------------------------------------------------
# check 를 실제로 - 127.0.0.1 에 띄운 사내 서버 (NT 대신)
# ----------------------------------------------------------------------------------------------------

def test_check_live():
    import lan_ca
    import lan_config
    import lan_server
    import local_server
    import local_web
    import pc_registry
    ca_dir, out = os.path.join(TMP, "ca"), os.path.join(TMP, "srv")
    lan_ca.make_ca(ca_dir, ["localhost"], ["127.0.0.1"])
    cert, key = lan_ca.issue_server(ca_dir, out, ["localhost"], ["127.0.0.1"])
    ca_pem = lan_ca.ca_pem(ca_dir)
    ca_file = os.path.join(TMP, "live_ca.pem")
    with open(ca_file, "w", encoding="ascii") as f:
        f.write(ca_pem)
    web_dir = os.path.join(TMP, "webfiles")
    os.makedirs(web_dir)
    with open(os.path.join(web_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write("<!doctype html><title>로그인</title>")
    folder = os.path.join(TMP, "data")
    os.makedirs(folder)
    lic = {"edition": "standalone", "company": "시험상사", "cid": "c1", "pc_id": "srv", "issued": "2026-11-26",
           "modules": {}, "features": {}, "limits": {}}
    store = local_server.Store(os.path.join(folder, "store.json"), volatile=local_server.VOLATILE)
    runs = local_server.Runs(":memory:")
    reg = pc_registry.Registry(os.path.join(folder, "pcs.json"), seats=5)
    web = local_web.Web(store, runs, lic, folder, web_dir, registry=reg)
    cfg = lan_config.parse({"listen": "127.0.0.1", "allow": ["127.0.0.0/8"]})
    cfg = dataclasses.replace(cfg, web_port=0, agent_port=0)
    w, a = lan_server.make_lan_servers(store, runs, lic, reg, web, cfg, cert, key, ca_pem)
    import update_sign
    seat_secret = update_sign.keygen()[0]
    for s in (w, a):
        # 실제 서버 입구처럼 자리 열쇠·라이선스 원문 (PC 등록은 자리 증명서가 있어야 믿는다 - 사내 서버 ⑤ Task 3)
        s.seat_secret, s.license_doc = seat_secret, {"body": dict(lic, kind="server"), "sig": "0" * 128}
        threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    wp, ap = w.server_address[1], a.server_address[1]
    sk = socket.socket()
    sk.bind(("127.0.0.1", 0))
    free = sk.getsockname()[1]
    sk.close()
    live = os.path.join(TMP, "live.json")
    with open(live, "w", encoding="utf-8") as f:
        json.dump({"host": "127.0.0.1"}, f)
    try:
        rc, out, err = run("--config", live, "check", "--web-port", str(wp), "--agent-port", str(ap), "--ca", ca_file,
                           "--closed", str(free))
        check("실제 check (인증 기관 확인) - 통과, 실패 없음", rc == 0 and "실패: 없음" in out and "[실패]" not in out, out + err)
        check("포트 없는 Host 와 엉뚱한 Host 는 403 을 받음",
              f"Host: 127.0.0.1 → 403" in out and "Host: evil.example → 403" in out and out.count("응답 403") == 2, out)
        check("TLS 버전·지문·SAN·체인 확인 줄", "TLS TLSv1." in out and "인증서 SHA-256 " in out and "IP Address 127.0.0.1" in out
              and "체인·이름 확인됨" in out, out)
        check("보안 머리글 셋이 보임 (X-Frame-Options DENY)", "X-Frame-Options: DENY" in out and "Strict-Transport-Security: max-age" in out, out)
        rc, out, _ = run("--config", live, "check", "--web-port", str(wp), "--agent-port", str(ap))
        check("--ca 없이도 통과 (지문만)", rc == 0 and "체인·이름은 확인하지 않음" in out, out)
        rc, out, _ = run("--config", live, "check", "--web-port", str(wp), "--agent-port", "0", "--closed", str(wp))
        check("열린 포트를 --closed 로 주면 실패 1", rc == 1 and f"[실패] {wp} 은 이 PC 에서 닿지 않음" in out, out)
        other_ca = os.path.join(TMP, "other_ca")
        lan_ca.make_ca(other_ca, ["localhost"], ["127.0.0.1"])
        other = os.path.join(TMP, "other_ca.pem")
        with open(other, "w", encoding="ascii") as f:
            f.write(lan_ca.ca_pem(other_ca))
        rc, out, _ = run("--config", live, "check", "--web-port", str(wp), "--agent-port", str(ap), "--ca", other)
        check("다른 인증 기관을 주면 TLS 확인 실패 1", rc == 1 and "[실패] " + str(ap) + " TLS 연결" in out, out)

        # api 끝까지 - 비밀번호를 바꿔야 하는 시험 관리자 (NT 의 tester 와 같은 처음 상태)
        init_pw = "init-" + "q" * 20
        web.accounts.set("tester", init_pw, "admin", must_change=True)
        pw_file, state = os.path.join(TMP, "secret", "tester_initial.pw"), os.path.join(TMP, "secret", "state.json")
        os.makedirs(os.path.dirname(pw_file))
        with open(pw_file, "w", encoding="ascii") as f:
            f.write(init_pw + "\n")
        args = ("--config", live, "api", "--state", state, "--web-port", str(wp), "--agent-port", str(ap), "--company", "c1")
        rc, out, err = run(*args, "--initial-pw-file", pw_file)
        check("실제 api 첫 실행 - 실패 없음 (비밀번호 바꾸기 → 2단계 → 두 단계 로그인 → PC 등록 → 현황 → 이력)",
              rc == 0 and "실패: 없음" in out and "[실패]" not in out, out + err)
        check("로그인 이력의 주소 = 127.0.0.1", "로그인 이력의 주소 = 이 PC 주소 127.0.0.1" in out, out)
        st = json.load(open(state, encoding="utf-8")) if os.path.isfile(state) else {}
        check("상태 파일에 바꾼 비밀번호·2단계·PC 가 남음", st.get("changed") is True and st.get("totp") and st.get("pc"), sorted(st))
        secrets_shown = [v for v in (st.get("pw"), st.get("totp"), st.get("agent_key"), init_pw) if v and v in out + err]
        check("비밀 값(비밀번호·2단계 비밀·에이전트 열쇠)은 화면에 찍지 않는다", not secrets_shown, len(secrets_shown))
        rc, out, err = run(*args)
        check("두 번째 실행은 상태 파일로 이어 감 (비밀번호·2단계·PC 등록 건너뜀)", rc == 0 and "실패: 없음" in out
              and "첫 로그인" not in out and "PC 추가" not in out, out + err)
    finally:
        for s in (w, a):
            s.shutdown()
            s.server_close()
        runs.close() if hasattr(runs, "close") else None


def test_nginx_host_rule():
    """nginx 443 뒤의 브라우저 Host(포트 없음)는 public_web 에 그 값이 있을 때만 웹 Host 목록에 든다 (nginx 계획의 근거)."""
    import lan_config
    base = {"listen": "192.168.1.230", "allow": ["192.168.1.0/24"]}
    c = lan_config.parse(base)
    check("public_web 없이는 '192.168.1.230' 이 웹 Host 목록에 없다 (→ 403)", "192.168.1.230" not in c.web_hosts()
          and "192.168.1.230:8443" in c.web_hosts(), sorted(c.web_hosts()))
    c = lan_config.parse(dict(base, public_web=["192.168.1.230"], trusted_proxies=["192.168.1.230"]))
    check("public_web 에 '192.168.1.230' 을 넣으면 Host·Origin 이 통과할 목록에 든다", "192.168.1.230" in c.web_hosts(), sorted(c.web_hosts()))
    c = lan_config.parse(dict(base, web_plain=True, trusted_proxies=["127.0.0.1"], public_web=["192.168.1.230"],
                              proxy_secret="s" * 40))
    check("web_plain: 웹은 127.0.0.1 에서만 듣고 에이전트는 listen 그대로", c.web_listen == "127.0.0.1" and c.listen == "192.168.1.230")


TESTS = [test_config, test_push, test_run_fetch, test_check_dry, test_api_dry, test_root_script, test_no_args, test_check_live,
         test_nginx_host_rule]

if __name__ == "__main__":
    try:
        for t in TESTS:
            print(f"- {t.__name__}")
            try:
                t()
            except Exception:
                traceback.print_exc()
                fails.append(t.__name__)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n실패: {len(fails)}")
    sys.exit(1 if fails else 0)
