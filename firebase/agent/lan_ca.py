# -*- coding: utf-8 -*-
"""사내 서버의 '오토파일럿 사내 인증 기관' 과 서버 인증서 (계획 2026-11-24-lan-2-network Task 2, 설계 6.3).

설치할 때 서버가 인증 기관(P-256, 3650일)을 한 번 만들고, 그 열쇠로 서버 인증서(P-256, 397일 - 브라우저 상한 398일 안)를 발급한다.
인증 기관에는 **이름 제한(nameConstraints, critical)** 을 걸어 이 서버의 이름·주소 인증서만 서명할 수 있게 한다 - 열쇠가 새어도
다른 사이트 인증서를 만들어 가로채지 못하게. 이름이 없으면 'autopilot.invalid', 주소가 없으면 '0.0.0.0/32' 만 허용해
그 종류를 통째로 막는다 (제한이 없는 종류는 무엇이든 허용되기 때문).
발급한 인증서는 바꿔 넣기 전에 `openssl verify -x509_strict` 로 인증 기관의 이름 제한 안인지 확인한다 - 서버 이름을 바꿨는데
인증 기관을 그대로 두면 에이전트가 모두 거절하게 되므로, 그런 인증서는 아예 남기지 않고 CaError 로 알린다.

openssl 은 자식 프로세스로만 부른다: 인자는 목록(셸 없음), 30초 제한, 이름·확장은 임시 폴더의 설정 파일(-config·-extfile)로 넘긴다
(Git 의 msys openssl 이 '/CN=…' 같은 인자를 경로로 바꾸지 않게 - MSYS_NO_PATHCONV·MSYS2_ARG_CONV_EXCL 도 끈다).
임시 폴더는 결과 폴더 안에 만들고(같은 디스크라 os.replace 가 되고, 리눅스에서 0700) 끝나면 지운다.
열쇠 내용은 읽지도 찍지도 않는다. 리눅스에서는 열쇠 파일을 0600 으로, 윈도우 권한(ACL)은 건드리지 않는다.
인증 기관 열쇠 폴더(ca_dir)와 서버 인증서 폴더(out_dir)는 달라야 한다 (④ 가 ca_dir 를 root 전용 폴더로 옮긴다).
표준 라이브러리만 쓰고 밖으로 연결하지 않는다.
"""
import ipaddress
import os
import re
import secrets
import shutil
import ssl
import subprocess
import tempfile
import time

CA_CERT = "ca_cert.pem"
CA_KEY = "ca_key.pem"
SERVER_CERT = "server_cert.pem"
SERVER_KEY = "server_key.pem"
CA_DAYS = 3650
SERVER_DAYS = 397
CA_CN = "AUTOPILOT LAN CA"
SERVER_CN = "AUTOPILOT LAN Server"
TIMEOUT = 30
NO_DNS = "autopilot.invalid"           # 이름이 없을 때 허용하는 하나뿐인 이름 (.invalid 는 쓰이지 않는 최상위 이름)
NO_IP = "0.0.0.0/255.255.255.255"      # 주소가 없을 때 허용하는 하나뿐인 주소
WINDOWS_OPENSSL = (r"C:\Program Files\Git\usr\bin\openssl.exe", r"C:\Program Files\Git\mingw64\bin\openssl.exe")
CREATE_NO_WINDOW = 0x08000000
CURRENT = "current"                    # replace_pair 가 갈아 끼우는 쌍 폴더 (리눅스는 pair-* 를 가리키는 링크)
PAIR_PREFIX = "pair-"
FORCE_CA_STARTDATE = False             # 시험 손잡이 - openssl 이 x509 -not_before 를 모르는 척 (3.0 의 `ca -startdate` 길로)
_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_NOT_BEFORE = {}                       # openssl 자리 → x509 -not_before 를 아는가 (한 번만 묻는다)


class CaError(Exception):
    """인증 기관·서버 인증서를 만들거나 읽지 못했다 (한국어 까닭)."""


def find_openssl():
    """openssl 실행 파일 자리. PATH 먼저, 윈도우면 Git 에 딸린 것. 환경 변수로 자리를 바꾸지 않는다."""
    exe = shutil.which("openssl")
    if exe:
        return exe
    if os.name == "nt":
        for cand in WINDOWS_OPENSSL:
            if os.path.isfile(cand):
                return cand
    raise CaError("openssl 을 찾지 못했습니다.")


def _run(openssl, args):
    """openssl 을 목록 인자로 부른다 (셸 없음, 30초). 실패하면 CaError - stderr 끝만 싣는다 (열쇠는 늘 파일로만 오간다)."""
    env = dict(os.environ, MSYS_NO_PATHCONV="1", MSYS2_ARG_CONV_EXCL="*")
    try:
        r = subprocess.run([openssl or find_openssl(), *args], capture_output=True, timeout=TIMEOUT, env=env,
                           stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
    except (OSError, subprocess.SubprocessError) as e:
        raise CaError(f"openssl {args[0]} 을 부르지 못했습니다 ({type(e).__name__}).") from None
    if r.returncode != 0:
        tail = r.stderr.decode("utf-8", "replace").strip()[-300:]
        raise CaError(f"openssl {args[0]} 이 실패했습니다: {tail}")
    return r.stdout.decode("utf-8", "replace")


def _x509_not_before(openssl):
    """openssl x509 가 -not_before 를 아는가 (OpenSSL 3.4 부터 - NT 의 3.0·Git 의 3.2 는 모른다). `x509 -help` 의 글로 본다
    (종료 코드는 판마다 달라 보지 않는다). 시험 손잡이 FORCE_CA_STARTDATE 면 모르는 것으로."""
    if FORCE_CA_STARTDATE:
        return False
    exe = openssl or find_openssl()
    if exe not in _NOT_BEFORE:
        env = dict(os.environ, MSYS_NO_PATHCONV="1", MSYS2_ARG_CONV_EXCL="*")
        try:
            r = subprocess.run([exe, "x509", "-help"], capture_output=True, timeout=TIMEOUT, env=env, stdin=subprocess.DEVNULL,
                               creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
            _NOT_BEFORE[exe] = b"-not_before" in r.stdout + r.stderr
        except (OSError, subprocess.SubprocessError):
            _NOT_BEFORE[exe] = False
    return _NOT_BEFORE[exe]


def _asn1(t):
    """초 → openssl 시각 글 YYYYMMDDHHMMSSZ (UTC)."""
    return time.strftime("%Y%m%d%H%M%SZ", time.gmtime(t))


def _ip(value):
    try:
        ip = ipaddress.ip_address(value if isinstance(value, str) else str(value))
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.scope_id:
        return None
    return ip


def _dns(value):
    name = value.lower() if isinstance(value, str) else ""    # 앞뒤 빈칸·줄바꿈도 다듬지 않고 거절한다
    if not 1 <= len(name) <= 253 or not all(_LABEL.fullmatch(part) for part in name.split(".")):
        return None
    return name


def _split(names, ips):
    """(DNS 이름 목록, IP 목록). names 안의 IP 글자는 주소로 옮긴다. 설정 파일에 끼어들 수 있는 글자는 CaError."""
    dns, addrs = [], []
    for n in names or ():
        ip = _ip(n)
        if ip is not None:
            if ip not in addrs:
                addrs.append(ip)
            continue
        d = _dns(n)
        if d is None:
            raise CaError(f"인증서에 넣을 수 없는 이름입니다: {n!r}")
        if d not in dns:
            dns.append(d)
    for a in ips or ():
        ip = _ip(a)
        if ip is None:
            raise CaError(f"인증서에 넣을 수 없는 주소입니다: {a!r}")
        if ip not in addrs:
            addrs.append(ip)
    if not dns and not addrs:
        raise CaError("인증서에 넣을 이름이나 주소가 없습니다.")
    return dns, addrs


def _mask(ip):
    full = ipaddress.IPv4Address(2 ** 32 - 1) if ip.version == 4 else ipaddress.IPv6Address(2 ** 128 - 1)
    return f"{ip}/{full}"


def _write(folder, name, text):
    path = os.path.join(folder, name)
    with open(path, "w", encoding="ascii", newline="\n") as f:
        f.write(text)
    return path


def _lock(path):
    if os.name == "posix":
        os.chmod(path, 0o600)


def _usable(cert_path, key_path):
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert_path, key_path)
        return True
    except (OSError, ssl.SSLError, ValueError):
        return False


def _genkey(openssl, path):
    _run(openssl, ["genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256", "-out", path])
    _lock(path)


def make_ca(ca_dir, names, ips, openssl=None):
    """인증 기관을 ca_dir 에 만들고 ca_dir 를 돌려준다. ca_cert.pem·ca_key.pem 이 있고 ssl 이 받으면 그대로 둔다
    (다시 만들면 등록한 PC 를 모두 다시 등록해야 한다). 이름 제한은 names 의 DNS 이름과 ips(+ names 안의 IP 글자)."""
    cert_path, key_path = os.path.join(ca_dir, CA_CERT), os.path.join(ca_dir, CA_KEY)
    if _usable(cert_path, key_path):
        return ca_dir
    dns, addrs = _split(names, ips)
    permitted = [f"permitted;DNS:{d}" for d in dns or [NO_DNS]] + [f"permitted;IP:{_mask(a)}" for a in addrs] \
        + ([] if addrs else [f"permitted;IP:{NO_IP}"])
    os.makedirs(ca_dir, mode=0o700, exist_ok=True)
    work = tempfile.mkdtemp(prefix=".lan_ca_", dir=ca_dir)
    try:
        cfg = _write(work, "ca.cnf", "\n".join([
            "[req]", "distinguished_name = dn", "prompt = no", "utf8 = yes", "x509_extensions = v3_ca",
            "[dn]", f"CN = {CA_CN}",
            "[v3_ca]", "basicConstraints = critical,CA:TRUE,pathlen:0", "keyUsage = critical,keyCertSign,cRLSign",
            "subjectKeyIdentifier = hash", "authorityKeyIdentifier = keyid:always",
            f"nameConstraints = critical,{','.join(permitted)}", ""]))
        tmp_key, tmp_cert = os.path.join(work, CA_KEY), os.path.join(work, CA_CERT)
        _genkey(openssl, tmp_key)
        _run(openssl, ["req", "-new", "-x509", "-config", cfg, "-key", tmp_key, "-sha256", "-days", str(CA_DAYS),
                       "-set_serial", str(secrets.randbits(63) or 1), "-out", tmp_cert])
        if not _usable(tmp_cert, tmp_key):
            raise CaError("만든 인증 기관을 ssl 이 읽지 못했습니다.")
        os.replace(tmp_key, key_path)
        os.replace(tmp_cert, cert_path)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return ca_dir


def issue_server(ca_dir, out_dir, names, ips, days=SERVER_DAYS, openssl=None, backdate_days=0):
    """인증 기관 열쇠로 서버 인증서를 발급해 out_dir 에 server_cert.pem·server_key.pem 으로 둔다 → (인증서 자리, 열쇠 자리).
    새 P-256 열쇠, SAN = DNS 이름들 + IP 들, serverAuth, CA:FALSE. 이름 제한 밖이면 CaError (파일을 바꾸지 않는다).
    backdate_days: 시작 시각(notBefore)을 그 날 수만큼 앞당긴다 - 시계가 조금 늦은 PC 가 막 만든 인증서를 '아직 유효하지 않음' 으로
    거절하지 않게 (사내 서버 ④ Task 4, ②-T2). 끝(notAfter)은 지금부터 days. openssl 이 x509 -not_before 를 알면(3.4 부터) 그것으로,
    모르면(3.0) `openssl ca -startdate` 길 (임시 ca 설정·index·serial 은 결과 폴더 안 임시 폴더에)."""
    if os.path.normcase(os.path.realpath(ca_dir)) == os.path.normcase(os.path.realpath(out_dir)):
        raise CaError("서버 인증서는 인증 기관 열쇠와 다른 폴더에 두어야 합니다.")
    ca_cert, ca_key = os.path.join(ca_dir, CA_CERT), os.path.join(ca_dir, CA_KEY)
    if not _usable(ca_cert, ca_key):
        raise CaError("인증 기관 파일이 없거나 쓸 수 없습니다.")
    dns, addrs = _split(names, ips)
    if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= SERVER_DAYS:
        raise CaError(f"서버 인증서 날 수는 1~{SERVER_DAYS} 이어야 합니다.")
    if not isinstance(backdate_days, int) or isinstance(backdate_days, bool) or not 0 <= backdate_days <= 1:
        raise CaError("서버 인증서를 앞당기는 날 수는 0 이나 1 이어야 합니다.")     # 전체 기간이 브라우저 상한 398일을 넘지 않게
    san = ",".join([f"DNS:{d}" for d in dns] + [f"IP:{a}" for a in addrs])
    # DNS 이름이 없으면 CN 을 이름 꼴이 아닌 글로 - openssl 은 DNS SAN 이 없을 때 이름 꼴 CN('127.0.0.1')을 DNS 제한에 견준다
    cn = dns[0] if dns else SERVER_CN
    os.makedirs(out_dir, exist_ok=True)
    cert_path, key_path = os.path.join(out_dir, SERVER_CERT), os.path.join(out_dir, SERVER_KEY)
    work = tempfile.mkdtemp(prefix=".lan_ca_", dir=out_dir)
    try:
        cfg = _write(work, "req.cnf", "\n".join(["[req]", "distinguished_name = dn", "prompt = no", "[dn]", f"CN = {cn}", ""]))
        ext = _write(work, "ext.cnf", "\n".join([
            "[v3_srv]", "basicConstraints = critical,CA:FALSE", "keyUsage = critical,digitalSignature",
            "extendedKeyUsage = serverAuth", f"subjectAltName = {san}",
            "subjectKeyIdentifier = hash", "authorityKeyIdentifier = keyid:always", ""]))
        tmp_key, csr, tmp_cert = os.path.join(work, SERVER_KEY), os.path.join(work, "server.csr"), os.path.join(work, SERVER_CERT)
        _genkey(openssl, tmp_key)
        _run(openssl, ["req", "-new", "-config", cfg, "-key", tmp_key, "-sha256", "-out", csr])
        now = time.time()
        start, end = _asn1(now - backdate_days * 86400), _asn1(now + days * 86400)
        if not backdate_days:
            _run(openssl, ["x509", "-req", "-in", csr, "-CA", ca_cert, "-CAkey", ca_key, "-sha256", "-days", str(days),
                           "-set_serial", str(secrets.randbits(63) or 1), "-extfile", ext, "-extensions", "v3_srv", "-out", tmp_cert])
        elif _x509_not_before(openssl):
            _run(openssl, ["x509", "-req", "-in", csr, "-CA", ca_cert, "-CAkey", ca_key, "-sha256", "-not_before", start,
                           "-not_after", end, "-set_serial", str(secrets.randbits(63) or 1), "-extfile", ext, "-extensions", "v3_srv",
                           "-out", tmp_cert])
        else:
            _ca_sign(openssl, work, csr, ca_cert, ca_key, ext, start, end, tmp_cert)
        try:
            _run(openssl, ["verify", "-x509_strict", "-purpose", "sslserver", "-no-CApath", "-no-CAstore",
                           "-CAfile", ca_cert, tmp_cert])
        except CaError:
            raise CaError("인증 기관의 이름 제한 밖 이름·주소입니다 - 서버 이름을 바꿨다면 인증 기관부터 새로 만들어야 합니다.") from None
        if not _usable(tmp_cert, tmp_key):
            raise CaError("발급한 서버 인증서를 ssl 이 읽지 못했습니다.")
        os.replace(tmp_key, key_path)
        os.replace(tmp_cert, cert_path)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return cert_path, key_path


def _cnf_path(path):
    """openssl 설정 파일 안에 적는 경로 - 역슬래시는 설정 글에서 이스케이프라 / 로 (윈도우 시험)."""
    return path.replace("\\", "/")


def _ca_sign(openssl, work, csr, ca_cert, ca_key, ext, start, end, out):
    """`openssl ca -startdate -enddate` 로 서명 (x509 -not_before 를 모르는 openssl 3.0 길). 임시 ca 설정·index·serial 은 work 안에."""
    db = os.path.join(work, "index.txt")
    _write(work, "index.txt", "")
    _write(work, "serial", f"{secrets.randbits(63) or 1:016x}\n")
    cnf = _write(work, "ca_sign.cnf", "\n".join([
        "[ca]", "default_ca = srvca",
        "[srvca]", f"database = {_cnf_path(db)}", f"new_certs_dir = {_cnf_path(work)}",
        f"serial = {_cnf_path(os.path.join(work, 'serial'))}", "default_md = sha256", "policy = pol", "unique_subject = no",
        "copy_extensions = none", "email_in_dn = no",
        "[pol]", "commonName = supplied", ""]))
    _run(openssl, ["ca", "-batch", "-notext", "-config", cnf, "-in", csr, "-out", out, "-cert", ca_cert, "-keyfile", ca_key,
                   "-startdate", start, "-enddate", end, "-extfile", ext, "-extensions", "v3_srv", "-md", "sha256"])


def _switch(folder, name):
    """folder/current 가 folder/name 을 가리키게 한 번에 바꾼다. 리눅스: 임시 링크를 만들어 os.replace (원자적 - 읽는 쪽은 옛 쌍이나
    새 쌍 하나만 본다). 윈도우(시험): 옛 폴더를 옆으로 옮기고 새 폴더 이름을 current 로."""
    cur = os.path.join(folder, CURRENT)
    if os.name == "posix":
        if os.path.isdir(cur) and not os.path.islink(cur):         # 예전 꼴 (current 가 진짜 폴더) - 한 번만 옆으로
            os.replace(cur, os.path.join(folder, PAIR_PREFIX + "legacy-" + secrets.token_hex(4)))
        tmp = os.path.join(folder, f".{CURRENT}-{secrets.token_hex(4)}")
        os.symlink(name, tmp)
        try:
            os.replace(tmp, cur)
        except BaseException:
            os.remove(tmp)
            raise
        return
    old = None
    if os.path.isdir(cur):
        old = os.path.join(folder, PAIR_PREFIX + "old-" + secrets.token_hex(4))
        os.replace(cur, old)
    os.replace(os.path.join(folder, name), cur)
    if old:
        shutil.rmtree(old, ignore_errors=True)


def replace_pair(folder, cert_text, key_text, owner=None):
    """인증서·열쇠 쌍을 folder/current 에 갈아 끼운다 → folder/current (사내 서버 ④ Task 4, ②검-7).
    두 파일을 같은 폴더의 새 하위 폴더(pair-*)에 다 쓰고(fsync, 열쇠 0600) 폴더 바꾸기 한 번으로 건다 - 어느 줄에서 끊겨도 읽는 쪽은
    옛 쌍이나 새 쌍 하나를 온전히 본다 (인증서와 열쇠가 서로 다른 쌍이 되지 않는다). 읽는 쪽은 current 를 실제 자리로 풀어
    (os.path.realpath) 그 안의 두 파일을 읽는다. owner = (uid, gid) 면 걸기 전에 새 폴더·파일의 소유자를 바꾼다 (root 의 renew 가
    서비스 계정에 넘김). 끝나면 걸리지 않은 옛 쌍·반쯤 만든 쌍을 지운다. 열쇠 내용은 찍지 않는다."""
    os.makedirs(folder, mode=0o700, exist_ok=True)
    new = tempfile.mkdtemp(prefix=PAIR_PREFIX, dir=folder)          # 0700
    try:
        for name, text in ((SERVER_CERT, cert_text), (SERVER_KEY, key_text)):
            fd = os.open(os.path.join(new, name), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
            with os.fdopen(fd, "w", encoding="ascii", newline="\n") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
        if owner is not None:
            for p in (new, os.path.join(new, SERVER_CERT), os.path.join(new, SERVER_KEY)):
                os.chown(p, *owner)
        _switch(folder, os.path.basename(new))
    except BaseException:
        shutil.rmtree(new, ignore_errors=True)
        raise
    live = os.path.realpath(os.path.join(folder, CURRENT))
    for n in os.listdir(folder):
        p = os.path.join(folder, n)
        if n.startswith(PAIR_PREFIX) and os.path.realpath(p) != live:
            shutil.rmtree(p, ignore_errors=True)
        elif n.startswith(f".{CURRENT}-") and os.path.islink(p):     # 걸지 못한 임시 링크
            try:
                os.remove(p)
            except OSError:
                pass
    return os.path.join(folder, CURRENT)


def ca_pem(ca_dir):
    """인증 기관 인증서 PEM 글 (등록 글·에이전트가 믿을 것). 열쇠는 싣지 않는다."""
    try:
        with open(os.path.join(ca_dir, CA_CERT), encoding="ascii") as f:
            text = f.read()
        ssl.PEM_cert_to_DER_cert(text)
    except (OSError, ValueError) as e:
        raise CaError("인증 기관 인증서를 읽지 못했습니다.") from e
    return text


def days_left(cert_path, now=None, openssl=None):
    """인증서가 끝나기까지 남은 날 (내림, 지났으면 음수). `openssl x509 -enddate -noout` 을 읽는다."""
    if not os.path.isfile(cert_path):
        raise CaError("인증서 파일이 없습니다.")
    out = _run(openssl, ["x509", "-in", cert_path, "-noout", "-enddate"]).strip()
    if not out.startswith("notAfter="):
        raise CaError("인증서 만료일을 읽지 못했습니다.")
    try:
        end = ssl.cert_time_to_seconds(out[len("notAfter="):].strip())
    except ValueError as e:
        raise CaError("인증서 만료일을 읽지 못했습니다.") from e
    return int((end - (time.time() if now is None else now)) // 86400)
