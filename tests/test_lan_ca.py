# -*- coding: utf-8 -*-
"""사내 서버 ② Task 2 - 우리 인증 기관 lan_ca (계획 2026-11-24-lan-2-network).
openssl 명령으로 인증 기관(이름 제한)과 서버 인증서를 만들고, 127.0.0.1 에 TLS 서버를 잠깐 띄워 ssl 로 실제로 붙어 본다.
윈도우·리눅스(WSL) 둘 다 같은 파일로 돈다. 신뢰 저장소에는 아무것도 넣지 않는다.
    D:/AX/RPA/.venv/Scripts/python.exe tests/test_lan_ca.py
    wsl.exe -d Ubuntu -e python3 /mnt/d/AX/RPA_StandAlone/tests/test_lan_ca.py
"""
import os
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import threading
import time

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
import lan_ca  # noqa: E402

fails = []
TMP = tempfile.mkdtemp(prefix="rpa_lan_ca_")
POSIX = os.name == "posix"
X509_V_ERR_PERMITTED_VIOLATION = 47


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def p(*names):
    return os.path.join(TMP, *names)


def raises_ca(fn):
    try:
        fn()
    except lan_ca.CaError:
        return True
    except Exception:
        return False
    return False


def openssl(*args):
    """시험이 직접 부르는 openssl (모듈을 거치지 않는다). 셸 없이, msys 경로 바꾸기 끔."""
    env = dict(os.environ, MSYS_NO_PATHCONV="1", MSYS2_ARG_CONV_EXCL="*")
    r = subprocess.run([lan_ca.find_openssl(), *args], capture_output=True, timeout=30, env=env,
                       stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise RuntimeError(f"openssl {args[0]}: {r.stderr.decode('utf-8', 'replace')[-300:]}")
    return r.stdout.decode("utf-8", "replace")


def sign_outside(ca_dir, folder, san, cn):
    """같은 인증 기관 열쇠로 이름 제한 밖 SAN 의 서버 인증서를 openssl 로 직접 서명한다 (모듈 검사를 거치지 않는다)."""
    os.makedirs(folder, exist_ok=True)
    key, csr, cert = (os.path.join(folder, n) for n in ("key.pem", "req.csr", "cert.pem"))
    cfg, ext = os.path.join(folder, "req.cnf"), os.path.join(folder, "ext.cnf")
    with open(cfg, "w", encoding="ascii") as f:
        f.write(f"[req]\ndistinguished_name = dn\nprompt = no\n[dn]\nCN = {cn}\n")
    with open(ext, "w", encoding="ascii") as f:
        f.write("[v3]\nbasicConstraints = critical,CA:FALSE\nkeyUsage = critical,digitalSignature\n"
                f"extendedKeyUsage = serverAuth\nsubjectAltName = {san}\n"
                "subjectKeyIdentifier = hash\nauthorityKeyIdentifier = keyid:always\n")
    openssl("genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256", "-out", key)
    openssl("req", "-new", "-key", key, "-config", cfg, "-out", csr)
    openssl("x509", "-req", "-in", csr, "-CA", os.path.join(ca_dir, lan_ca.CA_CERT),
            "-CAkey", os.path.join(ca_dir, lan_ca.CA_KEY), "-days", "30", "-sha256", "-set_serial", "12345",
            "-extfile", ext, "-extensions", "v3", "-out", cert)
    return cert, key


def handshake(cert, key, client_ctx, server_hostname):
    """127.0.0.1 에 TLS 서버를 하나 띄워 한 번 붙는다. 성공하면 None, 실패하면 클라이언트 쪽 예외."""
    sctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    sctx.minimum_version = ssl.TLSVersion.TLSv1_2
    sctx.load_cert_chain(cert, key)
    lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    lsock.bind(("127.0.0.1", 0))
    lsock.listen(1)
    lsock.settimeout(5)
    port = lsock.getsockname()[1]

    def serve():
        try:
            conn, _ = lsock.accept()
        except OSError:
            return
        conn.settimeout(5)
        try:
            with sctx.wrap_socket(conn, server_side=True) as s:
                s.sendall(b"ok")
        except (OSError, ssl.SSLError):
            pass
        finally:
            conn.close()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    err = None
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
            with client_ctx.wrap_socket(raw, server_hostname=server_hostname) as s:
                if s.recv(2) != b"ok":
                    err = RuntimeError("답이 다르다")
    except Exception as e:
        err = e
    t.join(5)
    lsock.close()
    return err


def ours(ca_dir):
    return ssl.create_default_context(cadata=lan_ca.ca_pem(ca_dir))


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def test_find_openssl():
    print("openssl 찾기")
    exe = lan_ca.find_openssl()
    check("있는 파일 자리를 돌려준다", os.path.isfile(exe), exe)
    check("상수", (lan_ca.CA_CERT, lan_ca.CA_KEY, lan_ca.SERVER_CERT, lan_ca.SERVER_KEY, lan_ca.CA_DAYS, lan_ca.SERVER_DAYS)
          == ("ca_cert.pem", "ca_key.pem", "server_cert.pem", "server_key.pem", 3650, 397))


def test_make_ca_and_server():
    print("인증 기관과 서버 인증서로 실제 TLS 악수")
    ca_dir, out = p("a", "ca"), p("a", "srv")
    got = lan_ca.make_ca(ca_dir, ["nt"], ["127.0.0.1"])
    check("make_ca 는 인증 기관 폴더를 돌려준다", os.path.abspath(got) == os.path.abspath(ca_dir), got)
    check("인증 기관 파일 둘", {lan_ca.CA_CERT, lan_ca.CA_KEY} <= set(os.listdir(ca_dir)), os.listdir(ca_dir))
    cert, key = lan_ca.issue_server(ca_dir, out, ["nt"], ["127.0.0.1"])
    check("issue_server 는 (인증서, 열쇠) 자리", (cert, key) == (os.path.join(out, lan_ca.SERVER_CERT), os.path.join(out, lan_ca.SERVER_KEY))
          and os.path.isfile(cert) and os.path.isfile(key), (cert, key))

    text = openssl("x509", "-in", os.path.join(ca_dir, lan_ca.CA_CERT), "-noout", "-text", "-nameopt", "RFC2253")
    check("인증 기관 이름", "CN=AUTOPILOT LAN CA" in text, text[:400])
    check("CA:TRUE, pathlen:0 (critical)", "Basic Constraints: critical" in text and "CA:TRUE, pathlen:0" in text)
    check("keyUsage 는 인증서 서명·CRL 서명 (critical)", "Key Usage: critical" in text and "Certificate Sign, CRL Sign" in text)
    check("이름 제한 (critical) 에 nt 와 127.0.0.1/32", "Name Constraints: critical" in text and "DNS:nt" in text
          and "IP:127.0.0.1/255.255.255.255" in text, text)
    check("P-256", "prime256v1" in text or "P-256" in text)
    stext = openssl("x509", "-in", cert, "-noout", "-text")
    check("서버 인증서 SAN = DNS:nt, IP 127.0.0.1", "DNS:nt" in stext and "IP Address:127.0.0.1" in stext, stext)
    check("serverAuth·CA:FALSE (critical)", "TLS Web Server Authentication" in stext and "CA:FALSE" in stext
          and "Basic Constraints: critical" in stext)

    check("우리 인증 기관만 믿는 클라이언트 + 127.0.0.1 → 악수 성공",
          handshake(cert, key, ours(ca_dir), "127.0.0.1") is None)
    check("이름 nt 로도 악수 성공", handshake(cert, key, ours(ca_dir), "nt") is None)
    err = handshake(cert, key, ours(ca_dir), "other")
    check("인증서에 없는 이름이면 SSLCertVerificationError", isinstance(err, ssl.SSLCertVerificationError), repr(err))
    err = handshake(cert, key, ssl.create_default_context(), "127.0.0.1")
    check("기본 컨텍스트(시스템 신뢰 저장소)는 실패", isinstance(err, ssl.SSLCertVerificationError), repr(err))
    ctx = ours(ca_dir)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    check("TLS 1.2 이상으로도 성공", handshake(cert, key, ctx, "127.0.0.1") is None)
    if POSIX:
        check("리눅스에서 열쇠 파일은 0600", mode(os.path.join(ca_dir, lan_ca.CA_KEY)) == 0o600 and mode(key) == 0o600,
              (oct(mode(os.path.join(ca_dir, lan_ca.CA_KEY))), oct(mode(key))))
    pem = lan_ca.ca_pem(ca_dir)
    check("ca_pem 은 PEM 인증서 글 (열쇠 없음)", pem.startswith("-----BEGIN CERTIFICATE-----") and "PRIVATE KEY" not in pem)
    leftovers = [n for d in (ca_dir, out) for n in os.listdir(d) if n not in
                 (lan_ca.CA_CERT, lan_ca.CA_KEY, lan_ca.SERVER_CERT, lan_ca.SERVER_KEY)]
    check("임시 파일·폴더가 남지 않는다", not leftovers, leftovers)


def test_name_constraints_enforced():
    print("이름 제한 밖 인증서는 클라이언트가 거절")
    ca_dir = p("b", "ca")
    lan_ca.make_ca(ca_dir, ["nt"], ["127.0.0.1"])
    cert, key = sign_outside(ca_dir, p("b", "evil_dns"), "DNS:evil.example", "evil.example")
    err = handshake(cert, key, ours(ca_dir), "evil.example")
    check("DNS:evil.example → SSLCertVerificationError", isinstance(err, ssl.SSLCertVerificationError), repr(err))
    check("까닭은 이름 제한 (permitted subtree violation)", getattr(err, "verify_code", None) == X509_V_ERR_PERMITTED_VIOLATION,
          getattr(err, "verify_message", repr(err)))
    cert, key = sign_outside(ca_dir, p("b", "evil_ip"), "IP:10.9.9.9", "10.9.9.9")
    err = handshake(cert, key, ours(ca_dir), "10.9.9.9")
    check("IP:10.9.9.9 → 이름 제한으로 거절", isinstance(err, ssl.SSLCertVerificationError)
          and getattr(err, "verify_code", None) == X509_V_ERR_PERMITTED_VIOLATION, repr(err))
    cert, key = sign_outside(ca_dir, p("b", "evil_v6"), "IP:::1", "localhost6")
    err = handshake(cert, key, ours(ca_dir), "::1")
    check("IPv6 IP:::1 (허용은 IPv4 하나) → 이름 제한으로 거절", isinstance(err, ssl.SSLCertVerificationError)
          and getattr(err, "verify_code", None) == X509_V_ERR_PERMITTED_VIOLATION, repr(err))

    # DNS 이름 없이 주소만 준 인증 기관도 아무 DNS 이름이나 서명하게 되지 않는다
    ip_ca = p("b", "ipca")
    lan_ca.make_ca(ip_ca, [], ["127.0.0.1"])
    cert, key = sign_outside(ip_ca, p("b", "evil_dns2"), "DNS:evil.example", "evil.example")
    err = handshake(cert, key, ours(ip_ca), "evil.example")
    check("주소만 있는 인증 기관도 DNS:evil.example 거절", isinstance(err, ssl.SSLCertVerificationError)
          and getattr(err, "verify_code", None) == X509_V_ERR_PERMITTED_VIOLATION, repr(err))
    c2, k2 = lan_ca.issue_server(ip_ca, p("b", "ipsrv"), [], ["127.0.0.1"])
    check("주소만 있는 인증 기관의 정상 인증서는 성공", handshake(c2, k2, ours(ip_ca), "127.0.0.1") is None)
    # 이름만 준 인증 기관도 아무 주소나 서명하게 되지 않는다
    dns_ca = p("b", "dnsca")
    lan_ca.make_ca(dns_ca, ["nt"], [])
    cert, key = sign_outside(dns_ca, p("b", "evil_ip2"), "DNS:nt,IP:127.0.0.1", "nt")
    err = handshake(cert, key, ours(dns_ca), "127.0.0.1")
    check("이름만 있는 인증 기관도 IP:127.0.0.1 거절", isinstance(err, ssl.SSLCertVerificationError)
          and getattr(err, "verify_code", None) == X509_V_ERR_PERMITTED_VIOLATION, repr(err))

    # 모듈은 이름 제한 밖 인증서를 아예 만들지 않는다 (다른 이름으로 다시 발급 → CaError, 파일 없음)
    out = p("b", "srv_out")
    check("이름 제한 밖 이름으로 issue_server → CaError", raises_ca(lambda: lan_ca.issue_server(ca_dir, out, ["other"], ["127.0.0.1"])))
    check("그때 서버 인증서 파일을 남기지 않는다", not os.path.exists(os.path.join(out, lan_ca.SERVER_CERT))
          and not os.path.exists(os.path.join(out, lan_ca.SERVER_KEY)))
    check("허용 밖 주소로 issue_server → CaError", raises_ca(lambda: lan_ca.issue_server(ca_dir, out, ["nt"], ["10.0.0.1"])))


def test_make_ca_keeps_existing():
    print("인증 기관은 있으면 그대로")
    ca_dir = p("c", "ca")
    lan_ca.make_ca(ca_dir, ["nt"], ["127.0.0.1"])
    first = open(os.path.join(ca_dir, lan_ca.CA_CERT), encoding="ascii").read()
    key_before = open(os.path.join(ca_dir, lan_ca.CA_KEY), "rb").read()
    lan_ca.make_ca(ca_dir, ["nt"], ["127.0.0.1"])
    check("두 번 부르면 같은 ca_cert.pem", open(os.path.join(ca_dir, lan_ca.CA_CERT), encoding="ascii").read() == first)
    check("열쇠도 그대로", open(os.path.join(ca_dir, lan_ca.CA_KEY), "rb").read() == key_before)
    check("ca_pem 이 파일 내용과 같다", lan_ca.ca_pem(ca_dir) == first)
    with open(os.path.join(ca_dir, lan_ca.CA_CERT), "w", encoding="ascii") as f:
        f.write("깨진 인증서".encode("utf-8").hex())
    lan_ca.make_ca(ca_dir, ["nt"], ["127.0.0.1"])
    again = open(os.path.join(ca_dir, lan_ca.CA_CERT), encoding="ascii").read()
    check("쓸 수 없는 파일이면 새로 만든다", again != first and again.startswith("-----BEGIN CERTIFICATE-----"))
    check("없는 폴더의 ca_pem → CaError", raises_ca(lambda: lan_ca.ca_pem(p("c", "none"))))


def test_days_left():
    print("남은 날")
    ca_dir = p("d", "ca")
    lan_ca.make_ca(ca_dir, ["nt"], ["127.0.0.1"])
    cert, _ = lan_ca.issue_server(ca_dir, p("d", "srv"), ["nt"], ["127.0.0.1"])
    d = lan_ca.days_left(cert)
    check("새 서버 인증서는 396~397", 396 <= d <= 397, d)
    d_ca = lan_ca.days_left(os.path.join(ca_dir, lan_ca.CA_CERT))
    check("인증 기관은 3649~3650", 3649 <= d_ca <= 3650, d_ca)
    check("400일 뒤에는 음수", lan_ca.days_left(cert, now=time.time() + 400 * 86400) < 0)
    c30, _ = lan_ca.issue_server(ca_dir, p("d", "srv30"), ["nt"], ["127.0.0.1"], days=30)
    check("days=30 이면 29~30", 29 <= lan_ca.days_left(c30) <= 30, lan_ca.days_left(c30))
    check("없는 파일 → CaError", raises_ca(lambda: lan_ca.days_left(p("d", "none.pem"))))


def test_key_never_in_cert_dir():
    print("인증 기관 열쇠는 서버 인증서 폴더에 없다")
    ca_dir, out = p("e", "ca"), p("e", "srv")
    lan_ca.make_ca(ca_dir, ["nt"], ["127.0.0.1"])
    lan_ca.issue_server(ca_dir, out, ["nt"], ["127.0.0.1"])
    check("out_dir 에 ca_key.pem 이 없다", lan_ca.CA_KEY not in os.listdir(out), os.listdir(out))
    check("out_dir 에는 서버 인증서·열쇠 둘뿐", sorted(os.listdir(out)) == [lan_ca.SERVER_CERT, lan_ca.SERVER_KEY], os.listdir(out))
    check("out_dir 가 ca_dir 와 같으면 CaError", raises_ca(lambda: lan_ca.issue_server(ca_dir, ca_dir, ["nt"], ["127.0.0.1"])))
    check("그때 ca_dir 에 서버 파일이 생기지 않는다", lan_ca.SERVER_KEY not in os.listdir(ca_dir))
    old = open(os.path.join(out, lan_ca.SERVER_CERT), encoding="ascii").read()
    lan_ca.issue_server(ca_dir, out, ["nt"], ["127.0.0.1"])
    check("다시 발급하면 새 인증서로 바뀐다", open(os.path.join(out, lan_ca.SERVER_CERT), encoding="ascii").read() != old)
    check("다시 발급해도 out_dir 에는 둘뿐", sorted(os.listdir(out)) == [lan_ca.SERVER_CERT, lan_ca.SERVER_KEY], os.listdir(out))


def test_bad_names_rejected():
    print("설정 파일에 끼어들 수 있는 이름은 거절")
    for names, ips in ((["a b"], []), (["nt\nDNS:evil.example"], []), (["nt,DNS:evil.example"], []), ([".nt"], []),
                       (["nt"], ["not-an-ip"]), (["nt"], ["fe80::1%eth0"]), ([], []), (["x" * 254], [])):
        check(f"make_ca 거절 {repr(names)[:40]} {ips!r}",raises_ca(lambda: lan_ca.make_ca(p("f", "ca"), names, ips)))
    check("거절하면 인증 기관 파일을 만들지 않는다", not os.path.exists(os.path.join(p("f", "ca"), lan_ca.CA_KEY)))
    ca_dir = p("f", "ok")
    lan_ca.make_ca(ca_dir, ["NT", "127.0.0.1"], ["::1"])
    text = openssl("x509", "-in", os.path.join(ca_dir, lan_ca.CA_CERT), "-noout", "-text")
    check("names 안의 IP 글자는 주소로, 이름은 소문자로, IPv6 는 /128", "DNS:nt" in text and "IP:127.0.0.1/255.255.255.255" in text
          and "IP:0:0:0:0:0:0:0:1/FFFF:FFFF:FFFF:FFFF:FFFF:FFFF:FFFF:FFFF" in text.replace("ffff", "FFFF"), text)
    check("issue_server 도 이상한 이름 거절", raises_ca(lambda: lan_ca.issue_server(ca_dir, p("f", "srv"), ["nt\n"], [])))


try:
    test_find_openssl()
    test_make_ca_and_server()
    test_name_constraints_enforced()
    test_make_ca_keeps_existing()
    test_days_left()
    test_key_never_in_cert_dir()
    test_bad_names_rejected()
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n실패 {len(fails)}건" + (": " + ", ".join(fails) if fails else ""))
sys.exit(1 if fails else 0)
