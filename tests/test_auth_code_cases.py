# -*- coding: utf-8 -*-
"""인증번호 뽑기 - RPA·안드로이드 앱·아이폰 단축어가 같은 답을 내는지 (휴대폰 중계 설계 9절 '세 군데가 같은 답').

시험 자료 testdata/auth_code_cases.json 은 TE-JA-VA/RPA-PhoneRelay 의 testdata/auth_code_cases.json 사본 (2026-10-13, 6499c14).
그쪽에서 자료가 바뀌면 이 사본도 같이 바꾼다. sms_watch.extract_auth_code 를 고치면 이 시험이 먼저 알려 준다.
    .venv\\Scripts\\python.exe tests\\test_auth_code_cases.py
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from sms_watch import extract_auth_code  # noqa: E402

with open(os.path.join(HERE, "testdata", "auth_code_cases.json"), encoding="utf-8") as f:
    cases = json.load(f)["cases"]

fails = []
for c in cases:
    got = extract_auth_code(c["body"])
    if got != c["code"]:
        fails.append(f"{c['note']}: {c['body']!r} → {got!r} (기대 {c['code']!r})")
print(f"{len(cases) - len(fails)}/{len(cases)} 통과")
for f in fails:
    print("  실패", f)
print("실패:", fails if fails else "없음")
sys.exit(1 if fails or not cases else 0)
