# update_sign.py
# -*- coding: utf-8 -*-
"""업데이트 판 서명 (자동 업데이트 설계 5절). ed25519 - RFC 8032 6절 참조 구현을 표준 라이브러리만으로 옮겼다.
업체 PC 의 내장 파이썬에는 cryptography 가 없어서 직접 넣는다. 느려도 판 하나에 한 번이라 괜찮다 (서명+확인 1초 안쪽).

비밀 열쇠는 우리 PC 의 firebase/admin/update_signing_key.txt 에만 있다 (tools/publish_release.py 가 쓴다).
여기 박힌 것은 공개 열쇠 - 이걸로 PC 가 판 목록(manifest.json)의 서명을 확인한다."""
import hashlib
import os

PUBLIC_KEY_HEX = ""     # tools/publish_release.py --keygen 이 알려 준 값 (비어 있으면 업데이트를 받지 않는다)

_p = 2 ** 255 - 19
_q = 2 ** 252 + 27742317777372353535851937790883648493


def _sha512(b):
    return hashlib.sha512(b).digest()


def _inv(x):
    return pow(x, _p - 2, _p)


_d = -121665 * _inv(121666) % _p
_sqrt_m1 = pow(2, (_p - 1) // 4, _p)


def _add(P, Q):
    A = (P[1] - P[0]) * (Q[1] - Q[0]) % _p
    B = (P[1] + P[0]) * (Q[1] + Q[0]) % _p
    C = 2 * P[3] * Q[3] * _d % _p
    D = 2 * P[2] * Q[2] % _p
    E, F, G, H = B - A, D - C, D + C, B + A
    return (E * F % _p, G * H % _p, F * G % _p, E * H % _p)


def _mul(s, P):
    Q = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            Q = _add(Q, P)
        P = _add(P, P)
        s >>= 1
    return Q


def _equal(P, Q):
    return (P[0] * Q[2] - Q[0] * P[2]) % _p == 0 and (P[1] * Q[2] - Q[1] * P[2]) % _p == 0


def _recover_x(y, sign):
    if y >= _p:
        return None
    x2 = (y * y - 1) * _inv(_d * y * y + 1)
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_p + 3) // 8, _p)
    if (x * x - x2) % _p != 0:
        x = x * _sqrt_m1 % _p
    if (x * x - x2) % _p != 0:
        return None
    if (x & 1) != sign:
        x = _p - x
    return x


_gy = 4 * _inv(5) % _p
_gx = _recover_x(_gy, 0)
_G = (_gx, _gy, 1, _gx * _gy % _p)


def _compress(P):
    zinv = _inv(P[2])
    x, y = P[0] * zinv % _p, P[1] * zinv % _p
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _decompress(s):
    if len(s) != 32:
        return None
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % _p)


def _expand(secret):
    if len(secret) != 32:
        raise ValueError("비밀 열쇠는 32바이트")
    h = _sha512(secret)
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def _hq(b):
    return int.from_bytes(_sha512(b), "little") % _q


def secret_to_public(secret):
    return _compress(_mul(_expand(secret)[0], _G))


def sign(secret, msg):
    a, prefix = _expand(secret)
    A = _compress(_mul(a, _G))
    r = _hq(prefix + msg)
    Rs = _compress(_mul(r, _G))
    s = (r + _hq(Rs + A + msg) * a) % _q
    return Rs + int.to_bytes(s, 32, "little")


def verify(public, msg, sig):
    """맞으면 True. 길이·모양이 틀려도 예외 없이 False."""
    try:
        if len(public) != 32 or len(sig) != 64:
            return False
        A, R = _decompress(public), _decompress(sig[:32])
        if not A or not R:
            return False
        s = int.from_bytes(sig[32:], "little")
        if s >= _q:
            return False
        return _equal(_mul(s, _G), _add(R, _mul(_hq(sig[:32] + public + msg), A)))
    except Exception:
        return False


def keygen():
    secret = os.urandom(32)
    return secret, secret_to_public(secret)


def public_key():
    return bytes.fromhex(PUBLIC_KEY_HEX) if PUBLIC_KEY_HEX else None
