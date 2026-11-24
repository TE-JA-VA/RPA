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
_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


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


def issue_server(ca_dir, out_dir, names, ips, days=SERVER_DAYS, openssl=None):
    """인증 기관 열쇠로 서버 인증서를 발급해 out_dir 에 server_cert.pem·server_key.pem 으로 둔다 → (인증서 자리, 열쇠 자리).
    새 P-256 열쇠, SAN = DNS 이름들 + IP 들, serverAuth, CA:FALSE. 이름 제한 밖이면 CaError (파일을 바꾸지 않는다)."""
    if os.path.normcase(os.path.realpath(ca_dir)) == os.path.normcase(os.path.realpath(out_dir)):
        raise CaError("서버 인증서는 인증 기관 열쇠와 다른 폴더에 두어야 합니다.")
    ca_cert, ca_key = os.path.join(ca_dir, CA_CERT), os.path.join(ca_dir, CA_KEY)
    if not _usable(ca_cert, ca_key):
        raise CaError("인증 기관 파일이 없거나 쓸 수 없습니다.")
    dns, addrs = _split(names, ips)
    if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= SERVER_DAYS:
        raise CaError(f"서버 인증서 날 수는 1~{SERVER_DAYS} 이어야 합니다.")
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
        _run(openssl, ["x509", "-req", "-in", csr, "-CA", ca_cert, "-CAkey", ca_key, "-sha256", "-days", str(days),
                       "-set_serial", str(secrets.randbits(63) or 1), "-extfile", ext, "-extensions", "v3_srv", "-out", tmp_cert])
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
