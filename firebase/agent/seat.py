# -*- coding: utf-8 -*-
"""사내 서버의 자리 증명서 (설계 6.8, 사내 서버 ④ Task 2).
서버는 자리 서명 열쇠(seat.key - Ed25519 비밀 값, 자료 폴더, 0600)를 한 번 만들고, 그 공개 열쇠(seat_pub)를 라이선스 요청에 싣는다.
공급사가 발급한 서버 라이선스에 seat_pub 이 들어가므로, PC 는 라이선스(우리 열쇠로 서명)로 seat_pub 을 믿고, seat_pub 으로
자리 증명서(이 PC 가 이 업체의 자리 하나를 받았다 - cid·pc_id·guid·발급 시각)를 확인한다. PC 쪽 확인은 ⑤.
seat.key 를 잃으면 라이선스와 짝이 끊긴다 - 깨진 파일을 새 열쇠로 덮지 않는다. 비밀 값은 기록·응답에 싣지 않는다.
표준 라이브러리 + 저장소의 update_sign(Ed25519)·license_check(canonical) 만 쓴다.
"""
import errno
import os
import re
import secrets
import stat
import sys
import tempfile

RPA_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
# update_sign·license_check (local_server 와 같은 규칙 - 사내 서버 설치본은 이 파일 옆 app/ 에 있어 위 폴더를 넣지 않는다)
if RPA_DIR not in sys.path and not os.path.isfile(os.path.join(os.path.dirname(os.path.abspath(__file__)), "license_check.py")):
    sys.path.insert(0, RPA_DIR)

import license_check  # noqa: E402
import update_sign  # noqa: E402

SEAT_KEY = "seat.key"
KIND = "seat"
_HEX64 = re.compile(r"[0-9a-f]{64}")
_HEX128 = re.compile(r"[0-9a-f]{128}")


_READ = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOCTTY", 0) \
    | getattr(os, "O_BINARY", 0)
_NEW = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NOCTTY", 0)


def _not_plain(shown):
    return ValueError(f"자리 서명 열쇠 파일({shown})이 보통 파일이 아닙니다 (링크·하드링크·폴더·특수 파일). 그 대상은 읽거나 "
                      f"바꾸지 않았습니다 - 무엇인지 확인한 뒤 그 이름을 치우고 백업에서 복구하여 주십시오.")


def _read_secret(path, dir_fd=None, strict=False, shown=None):
    """seat.key → 32바이트 비밀 값. 없으면 None, 꼴이 틀리면 ValueError (덮지 않는다).
    링크를 따라가지 않는다 (O_NOFOLLOW, 특수 파일을 열다 멈추지 않게 O_NONBLOCK) - 링크·폴더·FIFO 등 보통 파일이 아니면 ValueError.
    자료 폴더는 서비스 계정이 쓸 수 있어 seat.key 를 다른 파일로 가는 링크로 바꿔 둘 수 있다 (사내 서버 ④ Task 8.6).
    strict = root 가 부를 때 (request·install_helper license): 이름이 둘 이상인 파일(하드링크)도 거절."""
    shown = shown or path
    try:
        fd = os.open(path, _READ, dir_fd=dir_fd) if dir_fd is not None else os.open(path, _READ)
    except FileNotFoundError:
        return None
    except OSError as e:
        if e.errno in (errno.ELOOP, errno.EISDIR, errno.ENOTDIR, errno.ENXIO) or isinstance(e, IsADirectoryError):
            raise _not_plain(shown) from None
        raise
    with os.fdopen(fd, "rb") as f:
        st = os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode) or (strict and st.st_nlink != 1):
            raise _not_plain(shown)
        raw = f.read(4096)
    text = raw.decode("ascii", "replace").strip().lower()
    if not _HEX64.fullmatch(text):
        raise ValueError(f"자리 서명 열쇠 파일이 손상되었습니다. 백업에서 복구하여 주십시오. ({shown})")
    return bytes.fromhex(text)


def ensure_key(folder, owner=None):
    """자리 서명 열쇠 → (비밀 32바이트, 공개 열쇠 hex 64자). 없으면 만들어 0600 으로 저장한다 (임시 파일에 다 쓴 뒤 자리에 건다 -
    두 프로세스가 한꺼번에 만들어도 먼저 건 것 하나만 남고 둘 다 그것을 돌려준다). 있는데 꼴이 틀리거나 보통 파일이 아니면 ValueError.
    owner = (uid, gid): root 의 request 가 서비스 계정에 넘길 때 - 임시 파일의 fd 로 소유자를 바꾼 뒤 건다 (건 뒤 경로로 chown·chmod
    하지 않는다, Task 8.6). 리눅스는 폴더 fd 안에서만 읽고 만들고 건다 (이름을 다시 풀지 않는다, 링크는 따라가지 않는다)."""
    path = os.path.join(folder, SEAT_KEY)
    if os.name == "posix":
        return _ensure_key_fd(folder, path, owner)
    secret = _read_secret(path)
    if secret is None:
        os.makedirs(folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=SEAT_KEY + ".", suffix=".tmp")     # mkstemp 는 0600 으로 만든다
        try:
            with os.fdopen(fd, "w", encoding="ascii") as f:
                f.write(os.urandom(32).hex() + "\n")
                f.flush()
                os.fsync(f.fileno())
            try:
                os.link(tmp, path)               # 이미 있으면 FileExistsError - 다른 프로세스가 먼저 만든 열쇠를 쓴다
            except FileExistsError:
                pass
            except OSError:                      # 링크를 못 만드는 파일 시스템 - 없을 때만 옮긴다
                if not os.path.exists(path):
                    os.replace(tmp, path)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
        secret = _read_secret(path)
        if secret is None:
            raise OSError(f"자리 서명 열쇠 파일을 만들지 못했습니다. ({path})")
    return secret, update_sign.secret_to_public(secret).hex()


def _ensure_key_fd(folder, path, owner):
    """리눅스 ensure_key - 자료 폴더를 한 번 열고 그 fd 안에서만. 자료 폴더 자체는 root 소유 부모(/var/lib) 안이라 서비스 계정이
    바꿀 수 없고, 그 안의 이름(seat.key·임시 이름)은 바꿀 수 있다 - 그래서 이름은 모두 O_NOFOLLOW·O_EXCL·링크 안 따라가는 linkat."""
    os.makedirs(folder, exist_ok=True)
    dfd = os.open(folder, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    strict = owner is not None
    try:
        secret = _read_secret(SEAT_KEY, dir_fd=dfd, strict=strict, shown=path)
        if secret is not None:
            return secret, update_sign.secret_to_public(secret).hex()
        tmp = f"{SEAT_KEY}.{secrets.token_hex(6)}.tmp"
        fd = os.open(tmp, _NEW, 0o600, dir_fd=dfd)
        try:
            with os.fdopen(fd, "w", encoding="ascii") as f:
                f.write(os.urandom(32).hex() + "\n")
                f.flush()
                if owner is not None:
                    os.fchown(f.fileno(), *owner)        # 걸기 전에 fd 로 - 건 뒤 경로로 바꾸지 않는다
                os.fchmod(f.fileno(), 0o600)
                os.fsync(f.fileno())
            try:
                # 이미 있으면 FileExistsError - 다른 프로세스가 먼저 만든 열쇠를 쓴다. 임시 이름이 그사이 링크로 바뀌었어도 따라가지
                # 않는다 (링크 그 자체가 걸리고 아래 읽기가 거절한다)
                os.link(tmp, SEAT_KEY, src_dir_fd=dfd, dst_dir_fd=dfd, follow_symlinks=False)
            except FileExistsError:
                pass
            except OSError:                          # 링크를 못 만드는 파일 시스템 - 없을 때만 옮긴다
                try:
                    os.stat(SEAT_KEY, dir_fd=dfd, follow_symlinks=False)
                except FileNotFoundError:
                    os.replace(tmp, SEAT_KEY, src_dir_fd=dfd, dst_dir_fd=dfd)
        finally:
            try:
                os.unlink(tmp, dir_fd=dfd)
            except OSError:
                pass
        secret = _read_secret(SEAT_KEY, dir_fd=dfd, strict=strict, shown=path)
        if secret is None:
            raise OSError(f"자리 서명 열쇠 파일을 만들지 못했습니다. ({path})")
        return secret, update_sign.secret_to_public(secret).hex()
    finally:
        os.close(dfd)


def issue(secret, cid, pc_id, guid, issued_ms):
    """자리 증명서 {"body": {"kind": "seat", cid, pc_id, guid, issued}, "sig": hex} (license_check.canonical(body) 에 Ed25519)."""
    body = {"kind": KIND, "cid": cid, "pc_id": pc_id, "guid": guid, "issued": int(issued_ms)}
    return {"body": body, "sig": update_sign.sign(secret, license_check.canonical(body)).hex()}


def verify(pub_hex, cert, guid):
    """자리 증명서를 확인해 body 를 돌려준다 - 서명이 pub_hex 로 맞고, kind 가 seat 이고, guid 가 이 PC 의 것(대소문자 무시).
    아니면 ValueError."""
    if not isinstance(pub_hex, str) or not _HEX64.fullmatch(pub_hex.lower()):
        raise ValueError("자리 서명 공개 열쇠가 올바르지 않습니다.")
    if not isinstance(cert, dict) or not isinstance(cert.get("body"), dict) or not isinstance(cert.get("sig"), str) \
            or not _HEX128.fullmatch(cert["sig"].lower()):
        raise ValueError("자리 증명서의 꼴이 올바르지 않습니다.")
    body = cert["body"]
    if not update_sign.verify(bytes.fromhex(pub_hex), license_check.canonical(body), bytes.fromhex(cert["sig"])):
        raise ValueError("자리 증명서의 서명이 맞지 않습니다.")
    if body.get("kind") != KIND:
        raise ValueError("자리 증명서가 아닙니다.")
    mine = str(guid or "").strip().lower()
    if not mine or str(body.get("guid") or "").strip().lower() != mine:
        raise ValueError("이 PC 의 자리 증명서가 아닙니다.")
    return body
