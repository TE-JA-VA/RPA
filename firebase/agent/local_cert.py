# -*- coding: utf-8 -*-
"""스탠드얼론 휴대폰 포트의 자체 서명 인증서 (계획 2026-11-23-standalone-4-phone Task 2).

그 PC 에서 처음 한 번 만든다: P-256(ECDSA) 열쇠, SHA-256 서명, 유효 3650일, CN "AUTOPILOT Phone Gate".
휴대폰 앱은 이름·기관·날짜를 보지 않고 **인증서 DER 의 SHA-256(지문)** 이 QR 의 fp 와 같을 때만 요청을 보낸다.
다시 만들면 지문이 바뀌어 모든 휴대폰을 다시 짝지어야 한다 - 그래서 파일이 멀쩡하면 그대로 쓴다.

내장 파이썬에는 cryptography 가 없다 - 이미 실린 OpenSSL(_ssl 옆 libcrypto-3.dll)을 ctypes 로 부른다. ctypes 를 잘못 부르면
예외가 아니라 프로세스가 죽으므로 만들기는 **자식 프로세스**(이 파일 --make <폴더>)에서 한다 - 로컬 서버가 같이 죽지 않게.
파일 자리: 로컬 서버 자료 폴더(local_server.data_dir) - 관리자·SYSTEM 전용 폴더 권한을 물려받고, 개인 열쇠 phone_key.pem 은
local_server.lock_key_files 가 한 번 더 잠근다. 표준 라이브러리만 쓰고 밖으로 연결하지 않는다.
"""
import ctypes
import hashlib
import os
import secrets
import ssl
import subprocess
import sys

CERT_NAME = "phone_cert.pem"
KEY_NAME = "phone_key.pem"
VALID_DAYS = 3650
CN = "AUTOPILOT Phone Gate"
MAKE_TIMEOUT = 30
CREATE_NO_WINDOW = 0x08000000
EVP_PKEY_EC = 408                    # NID_X9_62_id_ecPublicKey
NID_P256 = 415                       # NID_X9_62_prime256v1
MBSTRING_ASC = 0x1001
BIO_CTRL_INFO = 3


class CertError(Exception):
    """휴대폰 포트의 인증서를 만들지 못했다."""


def _crypto():
    """내장 OpenSSL(libcrypto-3.dll) - 함수마다 restype·argtypes 를 적는다 (포인터는 c_void_p)."""
    import _ssl
    lib = ctypes.CDLL(os.path.join(os.path.dirname(_ssl.__file__), "libcrypto-3.dll"))
    P, I, L = ctypes.c_void_p, ctypes.c_int, ctypes.c_long
    table = {
        "EVP_PKEY_CTX_new_id": (P, [I, P]), "EVP_PKEY_keygen_init": (I, [P]),
        "EVP_PKEY_CTX_set_ec_paramgen_curve_nid": (I, [P, I]), "EVP_PKEY_keygen": (I, [P, ctypes.POINTER(P)]),
        "EVP_PKEY_CTX_free": (None, [P]), "EVP_PKEY_free": (None, [P]),
        "X509_new": (P, []), "X509_free": (None, [P]), "X509_set_version": (I, [P, L]),
        "X509_get_serialNumber": (P, [P]), "ASN1_INTEGER_set_uint64": (I, [P, ctypes.c_uint64]),
        "X509_getm_notBefore": (P, [P]), "X509_getm_notAfter": (P, [P]), "X509_gmtime_adj": (P, [P, L]),
        "X509_set_pubkey": (I, [P, P]), "X509_get_subject_name": (P, [P]),
        "X509_NAME_add_entry_by_txt": (I, [P, ctypes.c_char_p, I, ctypes.c_char_p, I, I, I]),
        "X509_set_issuer_name": (I, [P, P]), "EVP_sha256": (P, []), "X509_sign": (I, [P, P, P]),
        "BIO_s_mem": (P, []), "BIO_new": (P, [P]), "BIO_free": (I, [P]),
        "PEM_write_bio_PrivateKey": (I, [P, P, P, P, I, P, P]), "PEM_write_bio_X509": (I, [P, P]),
        "BIO_ctrl": (L, [P, I, L, P]),
    }
    for name, (res, args) in table.items():
        fn = getattr(lib, name)
        fn.restype, fn.argtypes = res, args
    return lib


def _pem(lib, write, *args):
    """BIO 메모리에 PEM 을 써서 bytes 로."""
    bio = lib.BIO_new(lib.BIO_s_mem())
    if not bio:
        raise CertError("BIO_new")
    try:
        if write(bio, *args) != 1:
            raise CertError("PEM 쓰기")
        ptr = ctypes.c_void_p()
        n = lib.BIO_ctrl(bio, BIO_CTRL_INFO, 0, ctypes.byref(ptr))
        return ctypes.string_at(ptr, n)
    finally:
        lib.BIO_free(bio)


def make(folder):
    """P-256 열쇠와 v3 자체 서명 인증서를 만들어 folder 에 둔다 (열쇠를 먼저 임시 이름으로 쓰고 둘을 os.replace).
    ctypes 를 부르므로 로컬 서버 안에서 직접 부르지 말고 ensure() 를 쓴다 (자식 프로세스)."""
    lib = _crypto()
    os.makedirs(folder, exist_ok=True)
    ctx = pkey = x = None
    try:
        ctx = lib.EVP_PKEY_CTX_new_id(EVP_PKEY_EC, None)
        pkey = ctypes.c_void_p()
        if not ctx or lib.EVP_PKEY_keygen_init(ctx) != 1 or lib.EVP_PKEY_CTX_set_ec_paramgen_curve_nid(ctx, NID_P256) != 1 \
                or lib.EVP_PKEY_keygen(ctx, ctypes.byref(pkey)) != 1 or not pkey:
            raise CertError("열쇠 만들기")
        x = lib.X509_new()
        if not x or lib.X509_set_version(x, 2) != 1:
            raise CertError("X509_new")
        if lib.ASN1_INTEGER_set_uint64(lib.X509_get_serialNumber(x), secrets.randbits(63) or 1) != 1:
            raise CertError("일련번호")
        if not lib.X509_gmtime_adj(lib.X509_getm_notBefore(x), -86400) or not lib.X509_gmtime_adj(lib.X509_getm_notAfter(x), VALID_DAYS * 86400):
            raise CertError("유효 기간")
        name = lib.X509_get_subject_name(x)
        cn = CN.encode("ascii")
        if lib.X509_set_pubkey(x, pkey) != 1 or lib.X509_NAME_add_entry_by_txt(name, b"CN", MBSTRING_ASC, cn, len(cn), -1, 0) != 1 \
                or lib.X509_set_issuer_name(x, name) != 1:
            raise CertError("이름")
        if lib.X509_sign(x, pkey, lib.EVP_sha256()) <= 0:
            raise CertError("서명")
        key_pem = _pem(lib, lib.PEM_write_bio_PrivateKey, pkey, None, None, 0, None, None)
        cert_pem = _pem(lib, lib.PEM_write_bio_X509, x)
    finally:
        if x:
            lib.X509_free(x)
        if pkey:
            lib.EVP_PKEY_free(pkey)
        if ctx:
            lib.EVP_PKEY_CTX_free(ctx)
    cert_path, key_path = os.path.join(folder, CERT_NAME), os.path.join(folder, KEY_NAME)
    tmp_key, tmp_cert = f"{key_path}.{os.getpid()}.tmp", f"{cert_path}.{os.getpid()}.tmp"
    try:
        with open(tmp_key, "wb") as f:
            f.write(key_pem)
        with open(tmp_cert, "wb") as f:
            f.write(cert_pem)
        os.replace(tmp_key, key_path)
        os.replace(tmp_cert, cert_path)
    finally:
        for p in (tmp_key, tmp_cert):
            try:
                os.remove(p)
            except OSError:
                pass
    return cert_path, key_path


def fingerprint(cert_path):
    """인증서 DER 의 SHA-256 소문자 hex 64자 (QR 의 fp)."""
    with open(cert_path, encoding="ascii") as f:
        der = ssl.PEM_cert_to_DER_cert(f.read())
    return hashlib.sha256(der).hexdigest()


def _usable(cert_path, key_path):
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert_path, key_path)
        return True
    except (OSError, ssl.SSLError, ValueError):
        return False


def ensure(folder, run=subprocess.run):
    """(인증서 자리, 열쇠 자리, 지문). 두 파일이 있고 ssl 이 받으면 그대로, 아니면 자식 프로세스로 새로 만든다
    ([sys.executable, -E, -s, 이 파일, --make, folder], 30초, 창 없음). 그래도 안 되면 CertError."""
    cert_path, key_path = os.path.join(folder, CERT_NAME), os.path.join(folder, KEY_NAME)
    if not _usable(cert_path, key_path):
        try:
            run([sys.executable, "-E", "-s", os.path.abspath(__file__), "--make", os.path.abspath(folder)],
                capture_output=True, timeout=MAKE_TIMEOUT, creationflags=CREATE_NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            pass
        if not _usable(cert_path, key_path):
            raise CertError("휴대폰 포트의 인증서를 만들지 못했습니다.")
    try:
        return cert_path, key_path, fingerprint(cert_path)
    except (OSError, ValueError) as e:
        raise CertError("휴대폰 포트의 인증서를 만들지 못했습니다.") from e


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--make":
        try:
            make(sys.argv[2])
        except CertError:
            sys.exit(1)
        sys.exit(0)
    sys.exit(2)
