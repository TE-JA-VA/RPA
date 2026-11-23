# -*- coding: utf-8 -*-
"""토큰 갱신·첫 로그인이 망 오류로 실패하면 물러선다 (보안 진단 2026-11-23 E-5) - 전엔 요청마다(1초) 비밀번호 로그인을 다시 보냈다.
    .venv\\Scripts\\python.exe tests\\test_fb_backoff.py
"""
import io
import json
import os
import sys
import urllib.error

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
import fb  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


def main():
    clock, calls, mode = Clock(), [], {"down": True}

    def opener(req, timeout=None):
        calls.append(req.full_url.split("?")[0].rsplit("/", 1)[-1])
        if mode["down"]:
            raise urllib.error.HTTPError(req.full_url, 503, "down", {}, io.BytesIO(b"<html>busy</html>"))
        body = {"idToken": "ID1", "refreshToken": "R1", "expiresIn": "3600"}
        return io.BytesIO(json.dumps(body).encode())

    cfg = {"database_url": "https://x.firebaseio.com", "api_key": "k", "email": "a@b", "password": "p"}
    c = fb.Client(cfg, opener=opener, clock=clock)
    errs = 0
    for _ in range(5):                      # 1초 간격으로 다섯 번 부름
        try:
            c.token()
        except Exception:
            errs += 1
        clock.t += 1
    check("B1 망 오류(503)면 곧바로 다시 로그인하지 않는다 - 5초 동안 로그인 요청은 3번 이하", errs == 5 and len(calls) <= 3, calls)
    check("B2 그래도 예외는 그대로 올린다 (에이전트가 '인증 거부' 로 멈추지 않는다)", not c._dead)
    clock.t += 120
    mode["down"] = False
    calls.clear()
    check("B3 물러선 시간이 지나면 다시 로그인하고 성공하면 원래대로", c.token() == "ID1" and calls == ["accounts:signInWithPassword"], calls)
    print("\n실패:", fails if fails else "없음")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
