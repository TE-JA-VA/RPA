# tests/test_update_sign.py
# -*- coding: utf-8 -*-
"""업데이트 서명 (설계 5절). RFC 8032 7.1 의 시험 값 + 서명·확인 왕복 + 바꿔치기."""
import io
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import update_sign as us  # noqa: E402

fails = []


def check(cond, what):
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        fails.append(what)


h = bytes.fromhex
# RFC 8032 7.1 TEST 1 (빈 글) · TEST 2 (0x72 한 바이트)
V = [("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
      "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
      "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
     ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
      "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
      "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00")]
for i, (sk, pk, msg, sig) in enumerate(V, 1):
    check(us.secret_to_public(h(sk)) == h(pk), f"RFC 8032 TEST {i}: 공개 열쇠")
    check(us.sign(h(sk), h(msg)) == h(sig), f"RFC 8032 TEST {i}: 서명")
    check(us.verify(h(pk), h(msg), h(sig)) is True, f"RFC 8032 TEST {i}: 확인")

sk, pk = us.keygen()
msg = '{"version": "2026.10.07-5", "files": {"rpa_status.py": "…"}}'.encode("utf-8")
t = time.time(); sig = us.sign(sk, msg); ok = us.verify(pk, msg, sig); took = time.time() - t
check(len(sk) == 32 and len(pk) == 32 and len(sig) == 64 and ok, "새 열쇠로 서명·확인 왕복")
check(took < 2.0, f"서명+확인이 2초 안 ({took:.2f}초)")
check(us.verify(pk, msg + b" ", sig) is False, "글이 1바이트 바뀌면 거짓")
check(us.verify(pk, msg, sig[:-1] + bytes([sig[-1] ^ 1])) is False, "서명이 1비트 바뀌면 거짓")
check(us.verify(us.keygen()[1], msg, sig) is False, "다른 열쇠면 거짓")
check(us.verify(pk, msg, b"short") is False and us.verify(b"x", msg, sig) is False, "길이가 틀려도 예외 없이 거짓")
check(us.PUBLIC_KEY_HEX == "" or len(us.PUBLIC_KEY_HEX) == 64, "박힌 공개 열쇠는 비었거나 64자")
check((us.public_key() is None) == (us.PUBLIC_KEY_HEX == ""), "공개 열쇠가 비면 public_key() 는 None")

print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
