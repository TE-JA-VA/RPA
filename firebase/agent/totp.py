# -*- coding: utf-8 -*-
"""사내 서버 웹의 2단계 인증 번호 계산 - 시간 기반 일회용 번호(TOTP, RFC 6238) (설계 2026-11-24 6.6, 계획 ③ Task 1).

휴대폰 인증 앱(Google Authenticator, Microsoft Authenticator 같은 것)과 같은 계산을 한다: HMAC-SHA1, 30초 한 칸, 6자리.
번호는 앞뒤 한 칸(30초)까지 받고, 한 번 쓴 칸(last_step 이하)은 다시 받지 않는다. 복구 번호는 8개를 만들어 글은 한 번만
보여 주고 서버에는 소금 붙인 sha256 해시만 둔다. 이 모듈은 상태를 갖지 않는다 (마지막으로 쓴 칸·해시는 계정 파일에 - local_web.Accounts).
QR 은 여기서 그리지 않는다 - otpauth:// 글만 만들고 화면이 qr.js 로 그린다. 비밀 값·번호·복구 번호는 기록에 싣지 않는다.
표준 라이브러리만 쓴다.
"""
import base64
import hashlib
import hmac
import re
import secrets
import struct
import urllib.parse

STEP = 30                   # 한 칸 (초)
DIGITS = 6                  # 번호 자리 수
WINDOW = 1                  # 앞뒤로 받는 칸 수
SECRET_BYTES = 20           # 비밀 값 (base32 32자)
RECOVERY_COUNT = 8          # 복구 번호 개수
ISSUER = "오토파일럿"

B32_LOWER = "abcdefghijklmnopqrstuvwxyz234567"
_CODE_RE = re.compile(r"[0-9]{%d}" % DIGITS, re.ASCII)
_RECOVERY_RE = re.compile(r"[a-z2-7]{10}", re.ASCII)


def new_secret():
    """새 비밀 값 - base32 대문자, '=' 없이 32자 (20바이트)."""
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode("ascii").rstrip("=")


def _key(secret):
    """base32 글 → 바이트. 소문자·빈칸·빠진 '=' 도 받는다."""
    s = re.sub(r"\s+", "", secret).upper().rstrip("=")
    return base64.b32decode(s + "=" * (-len(s) % 8))


def step_of(now):
    """시각(초) → 칸 번호."""
    return int(now // STEP)


def code_at(secret, step, digits=DIGITS):
    """그 칸의 번호 (RFC 4226 동적 자르기, 앞을 0 으로 채운 글)."""
    mac = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    value = struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF
    return str(value % (10 ** digits)).zfill(digits)


def match_detail(secret, code, now, last_step):
    """→ (맞은 칸 번호 또는 None, used). used 는 번호가 맞는 칸이지만 모두 last_step 이하(한 번 쓴 칸)라 받지 않았을 때만 True
    (전체 검토 6 - 쓴 번호를 '틀린 번호' 로 세지 않게). 공백을 뺀 6자리 숫자 글만 본다.
    step_of(now)-WINDOW .. +WINDOW 칸 가운데 아직 쓰지 않은 맞는 칸이 있으면 그 가운데 앞 칸."""
    if not isinstance(code, str):
        return None, False
    code = re.sub(r"\s+", "", code)
    if not _CODE_RE.fullmatch(code):
        return None, False
    try:
        _key(secret)
    except (ValueError, TypeError, AttributeError):
        return None, False
    now_step = step_of(now)
    fresh, used = None, False
    for step in range(now_step - WINDOW, now_step + WINDOW + 1):       # 칸마다 다 견준다 (맞은 칸에서 멈추지 않는다)
        if hmac.compare_digest(code_at(secret, step).encode("ascii"), code.encode("ascii")):
            if last_step is not None and step <= last_step:
                used = True
            elif fresh is None:
                fresh = step
    if fresh is not None:
        return fresh, False
    return None, used


def match(secret, code, now, last_step):
    """번호가 맞으면 맞은 칸 번호, 아니면 None (틀렸거나 한 번 쓴 칸 - 둘을 가르려면 match_detail)."""
    return match_detail(secret, code, now, last_step)[0]


def otpauth_uri(secret, account, issuer=ISSUER):
    """인증 앱에 넣을 글: otpauth://totp/<issuer:account>?secret=..&issuer=..&algorithm=SHA1&digits=6&period=30"""
    label = urllib.parse.quote(f"{issuer}:{account}", safe="")
    query = (f"secret={secret}&issuer={urllib.parse.quote(issuer, safe='')}"
             f"&algorithm=SHA1&digits={DIGITS}&period={STEP}")
    return f"otpauth://totp/{label}?{query}"


def new_recovery_codes(n=RECOVERY_COUNT):
    """복구 번호 n 개 - "xxxxx-xxxxx" (base32 소문자 10자), 서로 다르다."""
    out = []
    while len(out) < n:
        raw = "".join(secrets.choice(B32_LOWER) for _ in range(10))
        code = f"{raw[:5]}-{raw[5:]}"
        if code not in out:
            out.append(code)
    return out


def recovery_hash(salt_hex, code):
    """복구 번호의 해시 - 소문자로, 공백·'-' 를 뺀 뒤 sha256(소금 + 글) hex. 꼴이 틀린 글(base32 10자 아님)은 ""."""
    if not isinstance(code, str):
        return ""
    norm = re.sub(r"[\s-]+", "", code).lower()
    if not _RECOVERY_RE.fullmatch(norm):
        return ""
    return hashlib.sha256(bytes.fromhex(salt_hex) + norm.encode("ascii")).hexdigest()
