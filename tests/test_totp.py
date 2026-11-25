# -*- coding: utf-8 -*-
"""사내 서버 ③ Task 1 - TOTP 계산 totp (계획 2026-11-25-lan-3-web-auth).
RFC 6238 예시 값·앞뒤 한 칸·쓴 칸 거절·비밀 값·otpauth 글·복구 번호. 포트는 열지 않는다.
    D:/AX/RPA/.venv/Scripts/python.exe tests/test_totp.py
"""
import base64
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
import totp  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


RFC_SECRET = base64.b32encode(b"12345678901234567890").decode("ascii")
RFC_VECTORS = ((59, "94287082"), (1111111109, "07081804"), (1111111111, "14050471"), (1234567890, "89005924"),
               (2000000000, "69279037"), (20000000000, "65353130"))


def test_rfc6238_vectors():
    print("test_rfc6238_vectors")
    for t, want in RFC_VECTORS:
        got8 = totp.code_at(RFC_SECRET, totp.step_of(t), 8)
        check(f"t={t} 8자리 {want}", got8 == want, got8)
        got6 = totp.code_at(RFC_SECRET, totp.step_of(t))
        check(f"t={t} 6자리 {want[-6:]}", got6 == want[-6:], got6)
    check("상수", (totp.STEP, totp.DIGITS, totp.WINDOW, totp.SECRET_BYTES, totp.RECOVERY_COUNT, totp.ISSUER)
          == (30, 6, 1, 20, 8, "오토파일럿"))
    check("step_of", totp.step_of(59.9) == 1 and totp.step_of(60) == 2 and totp.step_of(0) == 0)


def test_window_and_replay():
    print("test_window_and_replay")
    s = RFC_SECRET
    now = 1795000005.0
    step = totp.step_of(now)
    code = totp.code_at(s, step)
    check("같은 때", totp.match(s, code, now, None) == step)
    check("30초 뒤 (뒤 한 칸)", totp.match(s, code, now + 30, None) == step)
    check("61초 뒤 → None", totp.match(s, code, now + 61, None) is None)
    check("30초 앞 (앞 한 칸)", totp.match(s, code, now - 30, None) == step)
    check("61초 앞 → None", totp.match(s, code, now - 61, None) is None)
    check("쓴 칸 (last_step=그 칸) → None", totp.match(s, code, now, step) is None)
    check("더 뒤 칸을 썼으면 → None", totp.match(s, code, now, step + 1) is None)
    check("앞 칸을 썼으면 받음", totp.match(s, code, now, step - 1) == step)
    spaced = " " + code[:3] + " " + code[3:] + " "
    check("공백 받음", totp.match(s, spaced, now, None) == step)
    # RFC 예시 t=59 의 6자리 "287082"
    check("RFC 번호 공백", totp.match(s, " 287 082 ", 59, None) == 1)
    check("글자 섞임 None", totp.match(s, "28708a", 59, None) is None)
    check("7자리 None", totp.match(s, "2870821", 59, None) is None)
    check("None → None", totp.match(s, None, 59, None) is None)
    check("숫자형 → None", totp.match(s, 287082, 59, None) is None)
    check("틀린 번호 None", totp.match(s, "000000" if code != "000000" else "111111", now, None) is None)
    check("전각 숫자 None", totp.match(s, "２８７０８２", 59, None) is None)


def test_secret_and_uri():
    print("test_secret_and_uri")
    a, b = totp.new_secret(), totp.new_secret()
    check("32자", len(a) == 32, a)
    check("= 없음·대문자 base32", re.fullmatch(r"[A-Z2-7]{32}", a) is not None, a)
    check("풀면 20바이트", len(base64.b32decode(a)) == 20)
    check("두 번 다름", a != b)
    uri = totp.otpauth_uri(a, "admin kim")
    check("otpauth://totp/ 로 시작", uri.startswith("otpauth://totp/"), uri)
    check("secret 담음", f"secret={a}" in uri, uri)
    check("period=30", "period=30" in uri, uri)
    check("digits=6", "digits=6" in uri, uri)
    check("algorithm=SHA1", "algorithm=SHA1" in uri, uri)
    label = uri[len("otpauth://totp/"):].split("?", 1)[0]
    check("계정 이름 퍼센트 인코딩 (빈칸·한글 없음)", " " not in label and "오토" not in label and "admin%20kim" in label, label)
    check("issuer 파라미터 인코딩", "issuer=%EC%98%A4" in uri, uri)


def test_recovery():
    print("test_recovery")
    codes = totp.new_recovery_codes()
    check("8개", len(codes) == 8, codes)
    check("모양 xxxxx-xxxxx", all(re.fullmatch(r"[a-z2-7]{5}-[a-z2-7]{5}", c) for c in codes), codes)
    check("서로 다름", len(set(codes)) == 8)
    check("n 지정", len(totp.new_recovery_codes(3)) == 3)
    salt, salt2 = "00" * 16, "11" * 16
    h1 = totp.recovery_hash(salt, "ABCDE-fghij")
    check("대문자·- 같은 해시", h1 == totp.recovery_hash(salt, "abcdefghij") and h1 != "", h1)
    check("공백도 뺌", totp.recovery_hash(salt, " abcde fghij ") == h1)
    check("64자 hex", re.fullmatch(r"[0-9a-f]{64}", h1) is not None, h1)
    check("소금이 다르면 다름", totp.recovery_hash(salt2, "abcdefghij") != h1)
    check("짧은 글 → 빈 글", totp.recovery_hash(salt, "abc") == "")
    check("base32 밖 글자 → 빈 글", totp.recovery_hash(salt, "abcde-fgh1j") == "")
    check("None → 빈 글", totp.recovery_hash(salt, None) == "")


def main():
    for fn in (test_rfc6238_vectors, test_window_and_replay, test_secret_and_uri, test_recovery):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            check(f"{fn.__name__} 예외", False, repr(e))
    print(f"실패: {len(fails)}")
    if fails:
        for n in fails:
            print("  -", n)
        sys.exit(1)


if __name__ == "__main__":
    main()
