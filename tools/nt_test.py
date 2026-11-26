# -*- coding: utf-8 -*-
"""NT(시험 리눅스 VM)에 넣고 확인하기 - 사내 서버 ④ Task 9 (계획 2026-11-25-lan-4-linux Task 9).

    python tools/nt_test.py [--dry-run] [--config FILE] push FILE [DEST]
    python tools/nt_test.py [--dry-run] run "CMD"
    python tools/nt_test.py [--dry-run] fetch PATH [LOCAL]
    python tools/nt_test.py [--dry-run] check [--ca PEM] [--web-ca PEM] [--web-port 8443] [--agent-port 8444] [--closed PORT]
    python tools/nt_test.py [--dry-run] api --state FILE [--initial-pw-file FILE] [--user tester] [--company c_nt_test]
    python tools/nt_test.py [--dry-run] root-script NAME [--out-dir DIR] [--file F | CMD ...]   (CMD 가 없으면 표준 입력)

- 접속 정보는 %USERPROFILE%\\.autopilot_nt.json ({"host", "user", "key"}) - 없으면 아래 DEFAULT. 이 도구는 그 파일을 만들지 않는다.
- ssh·scp 는 늘 -o BatchMode=yes -o ConnectTimeout=8 (비밀번호를 묻지 않고, 안 닿으면 8초 안에 끝난다). 사람 계정(autopilot)만 -
  root 일은 하지 않는다. root 가 할 명령은 root-script 로 파일에 써서 VM 세션에 보낸다.
- check 는 개발 PC 에서 TLS 와 Host 머리글 규칙을 본다. Host 는 브라우저와 같게 '주소:포트' (443 이면 포트 없이) -
  사내 서버는 포트 없는 Host 를 403 '서버 주소로 접속하여 주십시오' 로 거절한다 (lan_config.web_hosts).
- api 는 관리자 로그인·2단계·PC 등록·현황까지 끝까지 본다. 비밀 값(비밀번호·2단계 비밀·복구 번호·에이전트 열쇠)은 인자로 받지 않고
  --state 파일에만 두며 화면에 찍지 않는다.
- --dry-run 은 접속하지 않고 만들 명령 줄·확인 계획만 보인다 (tests/test_nt_tool.py).
종료 코드: 0 정상, 1 확인 실패, 2 인자·설정 오류, 그 밖은 ssh·scp 의 종료 코드.
표준 라이브러리만 (api 만 firebase/agent 의 totp·local_store·pc_registry).
"""
import argparse
import hashlib
import http.client
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_NAME = ".autopilot_nt.json"
DEFAULT = {"host": "192.168.1.230", "user": "autopilot", "key": "%USERPROFILE%\\.ssh\\nt_autopilot"}
INCOMING = "/home/autopilot/incoming"
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=8"]
TIMEOUT = 8
NAME_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
REMOTE_RE = re.compile(r"[A-Za-z0-9._/+-]{1,512}")          # 원격 경로 글자 (빈칸·따옴표·셸 기호 없음)
USER_RE = re.compile(r"[a-z_][a-z0-9_-]{0,31}")
HOST_RE = re.compile(r"[A-Za-z0-9.:-]{1,253}")
SEC_HEADERS = ("Strict-Transport-Security", "Content-Security-Policy", "X-Frame-Options")


class UsageError(Exception):
    """인자·설정이 틀렸다 (종료 코드 2)."""


def _out(text=""):
    print(text, flush=True)


# ----------------------------------------------------------------------------------------------------
# 접속 정보
# ----------------------------------------------------------------------------------------------------

def _home():
    return os.environ.get("USERPROFILE") or os.path.expanduser("~")


def _expand(text):
    """%USERPROFILE% 와 ~ 를 푼다 (리눅스·WSL 에서 돌려도 같은 뜻)."""
    return os.path.expanduser(text.replace("%USERPROFILE%", _home()))


def config_path(given=None):
    return given or os.environ.get("AUTOPILOT_NT_CONFIG") or os.path.join(_home(), CONFIG_NAME)


def load_config(path):
    """접속 정보. 파일이 없으면 DEFAULT (만들지 않는다). 모르는 칸·틀린 꼴은 UsageError."""
    data = dict(DEFAULT)
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8-sig") as f:
                got = json.load(f)
        except (OSError, ValueError) as e:
            raise UsageError(f"접속 정보 파일을 읽지 못했습니다: {path} ({type(e).__name__})") from None
        if not isinstance(got, dict):
            raise UsageError(f"접속 정보 파일은 {{\"host\", \"user\", \"key\"}} 꼴이어야 합니다: {path}")
        extra = sorted(set(got) - set(DEFAULT))
        if extra:
            raise UsageError(f"접속 정보 파일에 모르는 칸이 있습니다: {', '.join(map(str, extra))}")
        data.update(got)
    if not isinstance(data["host"], str) or not HOST_RE.fullmatch(data["host"]):
        raise UsageError(f"host 가 올바르지 않습니다: {data['host']!r}")
    if not isinstance(data["user"], str) or not USER_RE.fullmatch(data["user"]):
        raise UsageError(f"user 가 올바르지 않습니다: {data['user']!r}")
    if not isinstance(data["key"], str) or not data["key"]:
        raise UsageError("key 에 SSH 열쇠 파일 경로를 적어 주십시오")
    data["key"] = _expand(data["key"])
    return data


def _exe(name):
    return shutil.which(name) or name


def ssh_argv(cfg, command):
    return [_exe("ssh"), *SSH_OPTS, "-o", "IdentitiesOnly=yes", "-i", cfg["key"], f"{cfg['user']}@{cfg['host']}", command]


def scp_argv(cfg, src, dst):
    return [_exe("scp"), *SSH_OPTS, "-o", "IdentitiesOnly=yes", "-i", cfg["key"], src, dst]


def _remote(cfg, path):
    return f"{cfg['user']}@{cfg['host']}:{path}"


def _remote_path(path):
    if not REMOTE_RE.fullmatch(path) or ".." in path.split("/"):
        raise UsageError(f"원격 경로에는 영문·숫자와 . _ / + - 만 쓸 수 있고 '..' 은 안 됩니다: {path!r}")
    return path


def _show(argv):
    """명령 줄을 사람이 읽을 꼴로 (보여 주기만 - 실행은 목록 그대로)."""
    return " ".join(a if a and re.fullmatch(r"[A-Za-z0-9._/:=@%+,~\\-]+", a) else '"' + a.replace('"', '\\"') + '"' for a in argv)


def _run(argv, dry, capture=False):
    _out(("(dry-run) " if dry else "$ ") + _show(argv))
    if dry:
        return 0, ""
    r = subprocess.run(argv, capture_output=capture, text=capture, encoding="utf-8" if capture else None,
                       errors="replace" if capture else None)
    return r.returncode, (r.stdout or "") if capture else ""


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ----------------------------------------------------------------------------------------------------
# push · run · fetch
# ----------------------------------------------------------------------------------------------------

def cmd_push(cfg, a):
    if not os.path.isfile(a.file):
        raise UsageError(f"보낼 파일이 없습니다: {a.file}")
    dest = a.dest or os.path.basename(a.file)
    if dest.startswith("/"):
        raise UsageError(f"DEST 는 {INCOMING}/ 아래 자리만 적습니다 (절대 경로 안 됨): {dest}")
    target = _remote_path(f"{INCOMING}/{dest}")
    folder = target.rsplit("/", 1)[0]
    digest = None if a.dry_run else sha256_file(a.file)
    rc, _ = _run(ssh_argv(cfg, f"mkdir -p -m 0700 {folder}"), a.dry_run)
    if rc:
        return rc
    rc, _ = _run(scp_argv(cfg, a.file, _remote(cfg, target)), a.dry_run)
    if rc:
        return rc
    rc, out = _run(ssh_argv(cfg, f"sha256sum {target}"), a.dry_run, capture=True)
    if a.dry_run:
        _out(f"(dry-run) 보낸 뒤 원격 sha256sum 을 이 PC 의 SHA-256 과 견줍니다: {target}")
        return 0
    remote = (out.split() or [""])[0]
    _out(f"이 PC  SHA-256 {digest}")
    _out(f"NT    SHA-256 {remote or '(읽지 못함)'}")
    if rc or remote != digest:
        _out("[실패] 보낸 파일의 SHA-256 이 다릅니다")
        return 1
    _out(f"[통과] {target} 에 보냄 (SHA-256 같음)")
    return 0


def cmd_run(cfg, a):
    rc, _ = _run(ssh_argv(cfg, a.cmd), a.dry_run)
    return rc


def cmd_fetch(cfg, a):
    src = _remote_path(a.path)
    local = a.local or os.path.join(tempfile.gettempdir(), "autopilot_nt", os.path.basename(src.rstrip("/")))
    if not a.dry_run:
        os.makedirs(os.path.dirname(os.path.abspath(local)), exist_ok=True)
    rc, _ = _run(scp_argv(cfg, _remote(cfg, src), local), a.dry_run)
    if rc == 0 and not a.dry_run:
        _out(f"받음: {os.path.abspath(local)}  SHA-256 {sha256_file(local)}")
    return rc


# ----------------------------------------------------------------------------------------------------
# check - 개발 PC 에서 TLS·Host 규칙
# ----------------------------------------------------------------------------------------------------

def host_header(host, port):
    """브라우저가 보낼 Host 머리글 - 443 이면 포트 없이, 아니면 '주소:포트' (IPv6 는 대괄호)."""
    h = f"[{host}]" if ":" in host else host
    return h if port == 443 else f"{h}:{port}"


def _ctx(ca):
    if ca:
        return ssl.create_default_context(cafile=ca)          # 체인과 이름(IP SAN)까지
    c = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE                              # 인증 기관 파일이 없으면 지문만 본다
    return c


def _name(parts):
    return ", ".join(f"{k}={v}" for rdn in parts or () for k, v in rdn)


def tls_probe(host, port, ca):
    """→ (통과 여부, 설명 줄 목록)."""
    try:
        with socket.create_connection((host, port), timeout=TIMEOUT) as s:
            with _ctx(ca).wrap_socket(s, server_hostname=host) as t:
                der = t.getpeercert(binary_form=True)
                lines = [f"TLS {t.version()} {t.cipher()[0]}", f"인증서 SHA-256 {hashlib.sha256(der).hexdigest()}"]
                if ca:
                    c = t.getpeercert()
                    san = ", ".join(f"{k} {v}" for k, v in c.get("subjectAltName", ()))
                    lines += [f"주체 {_name(c.get('subject'))} / 발급 {_name(c.get('issuer'))}", f"SAN {san}",
                              f"기간 {c.get('notBefore')} ~ {c.get('notAfter')}", "체인·이름 확인됨 (--ca)"]
                else:
                    lines.append("체인·이름은 확인하지 않음 (--ca 없음)")
                return True, lines
    except (OSError, ssl.SSLError) as e:
        return False, [f"{type(e).__name__}: {e}"]


def http_get(host, port, ca, host_hdr, path="/"):
    c = http.client.HTTPSConnection(host, port, context=_ctx(ca), timeout=TIMEOUT)
    try:
        c.request("GET", path, headers={"Host": host_hdr})
        r = c.getresponse()
        body = r.read()
        return r.status, {k: r.getheader(k) for k in SEC_HEADERS + ("Content-Type",)}, body
    finally:
        c.close()


def check_plan(cfg, a):
    """확인 목록 (dry-run 이 보이는 것과 실제로 하는 것이 같다)."""
    host = cfg["host"]
    plan = [("tls", a.web_port, a.web_ca or a.ca), ("get", a.web_port, host_header(host, a.web_port), 200)]
    if a.web_port != 443:
        plan.append(("get", a.web_port, host, 403))                       # 포트 없는 Host
    plan.append(("get", a.web_port, "evil.example", 403))                 # 엉뚱한 Host
    if a.agent_port:
        plan.append(("tls", a.agent_port, a.ca))
    for p in a.closed or ():
        plan.append(("closed", p))
    return plan


def cmd_check(cfg, a):
    host, fails = cfg["host"], []
    for ca in (a.ca, a.web_ca):
        if ca and not os.path.isfile(ca):
            raise UsageError(f"인증 기관 파일이 없습니다: {ca}")

    def mark(name, ok, lines=()):
        _out(f"[{'통과' if ok else '실패'}] {name}")
        for ln in lines:
            _out("       " + ln)
        if not ok:
            fails.append(name)

    for step in check_plan(cfg, a):
        kind, port = step[0], step[1]
        if kind == "tls":
            label = f"{port} TLS 연결" + (f" (인증 기관 {os.path.basename(step[2])})" if step[2] else " (지문만)")
            if a.dry_run:
                _out(f"(dry-run) {label}  {host}:{port}")
                continue
            ok, lines = tls_probe(host, port, step[2])
            mark(label, ok, lines)
        elif kind == "get":
            hdr, want = step[2], step[3]
            label = f"{port} GET /  Host: {hdr} → {want}"
            if a.dry_run:
                _out(f"(dry-run) {label}")
                continue
            try:
                status, hs, body = http_get(host, port, a.web_ca or a.ca, hdr)
            except (OSError, ssl.SSLError, http.client.HTTPException) as e:
                mark(label, False, [f"{type(e).__name__}: {e}"])
                continue
            lines = [f"응답 {status}, {len(body)} 바이트, {hs.get('Content-Type') or '-'}"]
            ok = status == want
            if want == 200:
                text = body.decode("utf-8", "replace")
                lines.append("로그인 화면 글자 있음" if "로그인" in text else "로그인 글자 없음 (화면 파일을 확인)")
                for k in SEC_HEADERS:
                    lines.append(f"{k}: {(hs.get(k) or '-')[:90]}")
                ok = ok and all(hs.get(k) for k in SEC_HEADERS) and (hs.get("X-Frame-Options") or "").upper() == "DENY"
            mark(label, ok, lines)
        elif kind == "closed":
            label = f"{port} 은 이 PC 에서 닿지 않음"
            if a.dry_run:
                _out(f"(dry-run) {label}")
                continue
            try:
                socket.create_connection((host, port), timeout=TIMEOUT).close()
                mark(label, False, ["연결됨"])
            except OSError as e:
                mark(label, True, [type(e).__name__])
    if a.dry_run:
        return 0
    _out(f"실패: {len(fails) or '없음'}")
    return 1 if fails else 0


# ----------------------------------------------------------------------------------------------------
# api - 관리자 로그인·2단계·PC 등록·현황 (nt_api_check 의 흐름, 비밀 값은 --state 파일에만)
# ----------------------------------------------------------------------------------------------------

API_STEPS = ("첫 로그인 → 비밀번호 바꾸기 (state 에 바꾼 비밀번호가 있으면 건너뜀)",
             "2단계 등록 - 등록 전 다른 창구 403 auth/must-enroll-mfa, 틀린 번호 거절, 맞는 번호로 켬·복구 번호 8",
             "두 단계 로그인 - 비밀번호만으로는 ticket, 같은 30초 칸 번호 재사용 거절",
             "PC 추가 → 등록 글(APE1.) 주소·인증 기관, local_store.enroll 로 가짜 PC 등록 (state 에 PC 가 있으면 건너뜀)",
             "등록 글의 인증 기관으로 웹·에이전트 포트 체인·이름 확인",
             "웹 스트림을 열고 에이전트 현황 PATCH → 스트림에 옴, 서명된 응답 읽기, /api/company 에 PC, "
             "로그인 이력의 주소가 이 PC 주소 (프록시 뒤면 X-Forwarded-For 를 제대로 읽는지)")


def cmd_api(cfg, a):
    host, wp = cfg["host"], a.web_port
    hdr = host_header(host, wp)
    if a.dry_run:
        _out(f"(dry-run) 웹 https://{hdr}  Host: {hdr}  Origin: https://{hdr}  계정 {a.user}  업체 {a.company}")
        _out(f"(dry-run) 비밀 값은 {a.state} 에만 둡니다 (화면에 찍지 않음)")
        for i, s in enumerate(API_STEPS, 1):
            _out(f"(dry-run) {i}. {s}")
        return 0
    return _api_flow(host, wp, a)


def _api_flow(host, wp, a):
    import secrets
    import threading
    import uuid
    for p in (ROOT, os.path.join(ROOT, "firebase", "agent")):
        if p not in sys.path:
            sys.path.insert(0, p)
    import local_store
    import pc_registry
    import totp

    hdr = host_header(host, wp)
    origin = "https://" + hdr
    st = {}
    if os.path.isfile(a.state):
        with open(a.state, encoding="utf-8") as f:
            st = json.load(f)
    fails = []

    def save():
        tmp = a.state + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(st, f)
        os.replace(tmp, a.state)

    def check(name, ok, detail=""):
        _out(("[통과] " if ok else "[실패] ") + name + ("" if ok else f"  ({str(detail)[:160]})"))
        if not ok:
            fails.append(name)
        return ok

    def ctx():
        if st.get("ca") and not a.web_ca:
            return ssl.create_default_context(cadata=st["ca"])
        return _ctx(a.web_ca)

    def call(method, path, body=None, tok=None):
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        hs = {"Host": hdr, "Origin": origin}
        if data is not None:
            hs["Content-Type"] = "application/json"
        if tok:
            hs["Authorization"] = "Bearer " + tok
        c = http.client.HTTPSConnection(host, wp, context=ctx(), timeout=15)
        try:
            c.request(method, path, body=data, headers=hs)
            r = c.getresponse()
            try:
                j = json.loads(r.read().decode("utf-8", "replace"))
            except ValueError:
                j = {}
            return r.status, j if isinstance(j, dict) else {}
        finally:
            c.close()

    def code(shift=0):
        return totp.code_at(st["totp"], totp.step_of(time.time()) + shift)

    def sess(j):
        return j.get("session") or {}

    # 1. 첫 로그인 → 비밀번호 바꾸기
    if "pw" not in st:
        if not a.initial_pw_file or not os.path.isfile(a.initial_pw_file):
            raise UsageError("state 에 비밀번호가 없습니다 - 처음 비밀번호 파일을 --initial-pw-file 로 주십시오")
        with open(a.initial_pw_file, encoding="ascii") as f:
            st["pw"] = f.read().strip()
        st["changed"] = False
        save()
    if not st.get("changed"):
        s, j = call("POST", "/api/login", {"id": a.user, "password": st["pw"]})
        check("첫 로그인 200 + 비밀번호 바꾸기 요구", s == 200 and sess(j).get("mustChange") is True, (s, sess(j).get("mustChange")))
        tok = j.get("token")
        s, j2 = call("GET", "/api/accounts", tok=tok)
        check("바꾸기 전에는 다른 창구 403 auth/must-change", s == 403 and j2.get("code") == "auth/must-change", (s, j2.get("code")))
        new = "nt-" + secrets.token_urlsafe(18)
        s, j2 = call("POST", "/api/password", {"current": st["pw"], "next": new}, tok)
        if check("비밀번호 바꾸기 200", s == 200, (s, j2.get("code"))):
            st["pw"], st["changed"] = new, True
            save()

    # 2. 2단계 등록
    if not st.get("totp"):
        s, j = call("POST", "/api/login", {"id": a.user, "password": st["pw"]})
        tok = j.get("token")
        check("새 비밀번호 로그인 200 + 2단계 등록 요구", s == 200 and sess(j).get("mustEnroll") is True, (s, sess(j).get("mustEnroll")))
        s, j2 = call("GET", "/api/accounts", tok=tok)
        check("2단계 등록 전에는 다른 창구 403 auth/must-enroll-mfa", s == 403 and j2.get("code") == "auth/must-enroll-mfa",
              (s, j2.get("code")))
        s, su = call("POST", "/api/mfa/setup", {}, tok)
        check("2단계 등록 시작 - otpauth", s == 200 and bool(su.get("secret"))
              and str(su.get("uri", su.get("otpauth", ""))).startswith("otpauth://"), (s, sorted(su)))
        st["totp"] = su.get("secret")
        save()
        s, _ = call("POST", "/api/mfa/enable", {"code": "000000" if code() != "000000" else "111111"}, tok)
        check("틀린 번호로는 켜지지 않음", s != 200, s)
        s, en = call("POST", "/api/mfa/enable", {"code": code()}, tok)
        check("맞는 번호로 2단계 켬 + 복구 번호 8개", s == 200 and len(en.get("recovery") or []) == 8, (s, en.get("code")))
        st["recovery"] = en.get("recovery")
        st["last_step"] = totp.step_of(time.time())
        save()

    # 3. 두 단계 로그인
    s, j = call("POST", "/api/login", {"id": a.user, "password": st["pw"]})
    check("비밀번호만으로는 토큰 없이 ticket", s == 200 and bool(j.get("ticket")) and not j.get("token"), (s, sorted(j)))
    while totp.step_of(time.time()) <= st.get("last_step", -1):
        time.sleep(1)
    s2, j2 = call("POST", "/api/login/mfa", {"ticket": j.get("ticket"), "code": code()})
    st["last_step"] = totp.step_of(time.time())
    save()
    tok = j2.get("token")
    check("두 단계 로그인 200 → 세션", s2 == 200 and bool(tok), (s2, j2.get("code")))
    _, j3 = call("POST", "/api/login", {"id": a.user, "password": st["pw"]})
    s4, j4 = call("POST", "/api/login/mfa", {"ticket": j3.get("ticket"), "code": code()})
    check("같은 30초 칸 번호는 다시 못 씀", s4 != 200, (s4, j4.get("code")))
    if not tok:
        _out(f"실패: {len(fails)}")
        return 1

    # 4. PC 추가 → 가짜 에이전트 등록
    if not st.get("pc"):
        s, out = call("POST", "/api/pcs", {"label": "NT 시험 가짜 PC"}, tok)
        text = out.get("enrollment") or ""
        check("PC 추가 → 등록 글(APE1.)", s == 200 and text.startswith("APE1."), (s, out.get("code")))
        if not text.startswith("APE1."):
            _out(f"실패: {len(fails)}")
            return 1
        info = pc_registry.decode_enrollment(text)
        want = f"https://{host_header(host, a.agent_port)}"
        check(f"등록 글 주소 = {want}, 인증 기관 실림", info.get("url") == want and "BEGIN CERTIFICATE" in (info.get("ca") or ""),
              info.get("url"))
        got = local_store.enroll(text, str(uuid.uuid4()), "DEV-FAKE-PC")
        check("가짜 에이전트 등록 (에이전트 포트, 우리 인증 기관으로 확인)", got.get("pc_id") == out.get("pcId") and bool(got.get("agent_key")),
              sorted(got))
        st.update(pc=got.get("pc_id"), ca=got.get("ca_pem"), server_url=got.get("server_url"), agent_key=got.get("agent_key"),
                  relay_key=got.get("relay_key"))
        save()
    pc = st["pc"]

    # 5. 등록 글의 인증 기관으로 체인 확인 (웹 포트가 nginx 의 다른 인증서면 --web-ca 로 따로)
    for port, ca_text in ((wp, None if a.web_ca else st["ca"]), (a.agent_port, st["ca"])):
        try:
            with socket.create_connection((host, port), timeout=TIMEOUT) as sk:
                c = ssl.create_default_context(cadata=ca_text) if ca_text else _ctx(a.web_ca)
                with c.wrap_socket(sk, server_hostname=host) as t:
                    check(f"{port} 인증서 체인·이름 확인 ({t.version()})", True)
        except (OSError, ssl.SSLError) as e:
            check(f"{port} 인증서 체인 확인", False, e)

    # 6. 웹 스트림 열고 현황 PATCH
    events = []

    def reader(resp):
        try:
            while True:
                line = resp.fp.readline()
                if not line:
                    break
                if line.startswith(b"event: "):
                    events.append([line[7:].strip().decode(), None])
                elif line.startswith(b"data: ") and events:
                    events[-1][1] = json.loads(line[6:].decode("utf-8"))
        except Exception:
            pass

    sc = http.client.HTTPSConnection(host, wp, context=ctx(), timeout=20)
    sc.request("GET", f"/api/stream?pcId={pc}", headers={"Host": hdr, "Authorization": "Bearer " + tok})
    resp = sc.getresponse()
    check("웹 스트림 200 (text/event-stream)", resp.status == 200 and (resp.getheader("Content-Type") or "").startswith(
        "text/event-stream"), resp.status)
    threading.Thread(target=reader, args=(resp,), daemon=True).start()
    time.sleep(1)
    mark = "nt-" + secrets.token_hex(4)
    cl = local_store.Client({"standalone": True, "server_url": st["server_url"], "key": st["agent_key"], "role": "agent",
                             "lan": True, "pc_id": pc, "ca_pem": st["ca"]})
    t0 = time.time()
    cl.patch(f"apps/rpa/live/{a.company}/{pc}", {"state": "idle", "who": mark})

    def seen():
        return any(e[0] == "live" and isinstance(e[1], dict) and e[1].get("who") == mark for e in events)

    end = time.time() + 5
    while time.time() < end and not seen():
        time.sleep(0.1)
    check(f"에이전트 현황이 웹 스트림에 옴 ({time.time() - t0:.1f}초)", seen(), [e[0] for e in events][-5:])
    check("에이전트로 다시 읽기 (서명된 응답)", (cl.get(f"apps/rpa/live/{a.company}/{pc}") or {}).get("who") == mark)
    s, co = call("GET", "/api/company", tok=tok)
    check("업체 정보에 등록된 PC 가 보임", s == 200 and pc in json.dumps(co, ensure_ascii=False), (s, co.get("code")))
    sc.close()
    with socket.create_connection((host, wp), timeout=TIMEOUT) as sk:
        me = sk.getsockname()[0]                     # 이 PC 가 NT 에 붙을 때 쓰는 주소
    s, lg = call("GET", "/api/logins/me?limit=5", tok=tok)
    oks = [i for i in (lg.get("items") or []) if isinstance(i, dict) and i.get("result") == "ok"]
    check(f"로그인 이력의 주소 = 이 PC 주소 {me}", s == 200 and bool(oks) and oks[0].get("ip") == me,
          (s, [(i.get("result"), i.get("ip")) for i in (lg.get("items") or [])[:3] if isinstance(i, dict)]))
    _out(f"실패: {len(fails) or '없음'}")
    return 1 if fails else 0


# ----------------------------------------------------------------------------------------------------
# root-script - root 가 할 명령을 파일로 (VM 세션에 보낼 글)
# ----------------------------------------------------------------------------------------------------

def root_script_text(name, cmds):
    lines = ["#!/bin/sh", f"# 오토파일럿 사내 서버 NT 시험 - root 가 할 일 '{name}' ({time.strftime('%Y-%m-%d %H:%M')} 개발 PC 에서 만듦)",
             "# VM 세션: 사용자 확인을 받은 뒤 root 로 실행합니다. 명령마다 화면에 찍고, 하나라도 실패하면 거기서 멈춥니다.",
             "set -eux", ""]
    lines += cmds
    return "\n".join(lines) + "\n"


def cmd_root_script(cfg, a):
    if not NAME_RE.fullmatch(a.name):
        raise UsageError(f"NAME 은 영문·숫자·_·- 만 씁니다: {a.name!r}")
    if a.file:
        with open(a.file, encoding="utf-8-sig") as f:
            raw = f.read().splitlines()
    elif a.cmds:
        raw = list(a.cmds)
    else:
        raw = sys.stdin.read().splitlines()
    cmds = [c.rstrip() for c in raw if c.strip()]
    if not cmds:
        raise UsageError("root 가 할 명령이 없습니다 (CMD 인자, --file, 표준 입력 가운데 하나로)")
    text = root_script_text(a.name, cmds)
    out_dir = a.out_dir or os.path.join(tempfile.gettempdir(), "autopilot_nt")
    path = os.path.join(out_dir, f"nt_root_{a.name}.sh")
    if a.dry_run:
        _out(f"(dry-run) {path} 에 쓸 내용:")
    else:
        os.makedirs(out_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        _out(f"씀: {os.path.abspath(path)}")
    _out(text.rstrip("\n"))
    return 0


# ----------------------------------------------------------------------------------------------------

class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message)


def _parser():
    p = _Parser(prog="nt_test", description="NT(시험 리눅스 VM)에 넣고 확인하기 - 사람 계정만, root 일은 root-script 로")
    p.add_argument("--dry-run", action="store_true", help="접속하지 않고 만들 명령 줄만 보인다")
    p.add_argument("--config", help=f"접속 정보 파일 (기본 %%USERPROFILE%%\\{CONFIG_NAME})")
    sub = p.add_subparsers(dest="cmd")
    r = sub.add_parser("push", help=f"파일을 {INCOMING}/ 에 보내고 SHA-256 을 견준다")
    r.add_argument("file")
    r.add_argument("dest", nargs="?", help=f"{INCOMING}/ 아래 자리 (기본 파일 이름)")
    r.set_defaults(func=cmd_push)
    r = sub.add_parser("run", help="사람 계정으로 한 줄 실행")
    r.add_argument("cmd")
    r.set_defaults(func=cmd_run)
    r = sub.add_parser("fetch", help="NT 의 파일을 가져온다")
    r.add_argument("path")
    r.add_argument("local", nargs="?", help="받을 자리 (기본 %%TEMP%%\\autopilot_nt\\<파일 이름>)")
    r.set_defaults(func=cmd_fetch)
    for name, fn, hlp in (("check", cmd_check, "개발 PC 에서 TLS 와 Host 규칙 확인"),
                          ("api", cmd_api, "관리자 로그인·2단계·PC 등록·현황 끝까지 (비밀 값은 --state 파일에만)")):
        r = sub.add_parser(name, help=hlp)
        r.add_argument("--web-port", type=int, default=8443, help="웹 포트 (nginx 앞이면 443)")
        r.add_argument("--agent-port", type=int, default=8444, help="에이전트 포트 (check 에서 0 이면 건너뜀)")
        r.add_argument("--ca", help="우리 인증 기관 공개 인증서 PEM - 주면 체인·이름 확인")
        r.add_argument("--web-ca", help="웹 포트만 다른 인증서일 때 (nginx 의 인증서) 그 PEM")
        r.set_defaults(func=fn)
        if name == "check":
            r.add_argument("--closed", type=int, action="append", help="이 PC 에서 닿지 않아야 할 포트 (여러 번)")
        else:
            r.add_argument("--state", required=True, help="비밀 값을 두는 상태 파일 (화면에 찍지 않음)")
            r.add_argument("--initial-pw-file", help="처음 비밀번호 파일 (state 에 비밀번호가 없을 때만 읽음)")
            r.add_argument("--user", default="tester", help="시험 관리자 계정")
            r.add_argument("--company", default="c_nt_test", help="업체 번호 (현황 경로)")
    r = sub.add_parser("root-script", help="root 가 할 명령을 nt_root_<NAME>.sh 로 써서 보인다")
    r.add_argument("name")
    r.add_argument("cmds", nargs="*")
    r.add_argument("--file", help="명령 목록 파일 (한 줄에 하나)")
    r.add_argument("--out-dir", help="쓸 폴더 (기본 %%TEMP%%\\autopilot_nt - 메인 세션은 scratchpad 를 준다)")
    r.set_defaults(func=cmd_root_script)
    return p


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    argv = sys.argv[1:] if argv is None else list(argv)
    try:
        a = _parser().parse_args(argv)
        if not getattr(a, "func", None):
            _parser().print_help()
            return 2
        cfg = load_config(config_path(a.config))
        return a.func(cfg, a)
    except UsageError as e:
        print(f"nt_test: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
