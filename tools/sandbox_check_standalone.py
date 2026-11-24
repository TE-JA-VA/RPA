# -*- coding: utf-8 -*-
"""스탠드얼론 샌드박스 - 로컬 서버(127.0.0.1:8781)의 웹 창구를 끝에서 끝까지 본다 (계획 ③ Task 6, sandbox_inner_standalone.ps1 5·7).

샌드박스 안에서 설치된 내장 파이썬으로 돈다: python.exe -I check_standalone.py <full|after> <아이디> <첫 비밀번호> <새 비밀번호> <결과 파일>
줄마다 '통과  <이름>' / '실패  <이름>  <까닭>' / '참고  <글>' 을 결과 파일(UTF-8)에 쓴다 (PowerShell 이 결과 표에 옮긴다 -
화면 출력은 콘솔 코드 페이지라 한글이 깨질 수 있어 파일로).
127.0.0.1 말고 다른 곳에는 붙지 않는다. 비밀번호·세션 토큰은 찍지 않는다.
  full  = / 와 CSP → 로그인(mustChange) → 비밀번호 바꾸기 → 다시 로그인 → 스트림의 첫 live(heartbeat) → set_schedule 명령 done →
          launch 명령 → /api/runs 에 그 실행 한 줄
  after = 덮어 설치 뒤: 바꾼 비밀번호로 로그인되고 첫 비밀번호는 안 되며 실행 기록이 남아 있다
"""
import http.client
import json
import sys
import time

import os

HOST, PORT = "127.0.0.1", 8781
SCHEDULE = {"enabled": True, "days": [0, 1, 2, 3, 4, 5, 6], "slots": [{"at": "03:17"}], "skip_holidays": False}
OUT = None


def expect():
    """옆의 expect.json (sandbox_test.py 가 쓴다) - 없으면 시험용 빌드·샌드박스상사."""
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "expect.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"official": False, "company": "샌드박스상사", "cid": "c_sbx"}


def _line(text):
    text = text.replace("\r", " ").replace("\n", " ")
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(text + "\n")


def say(ok, name, detail=""):
    _line(("통과  " if ok else "실패  ") + name + ("" if ok or not detail else f"  {detail}"))


def note(text):
    _line(f"참고  {text}")


def call(method, path, body=None, token=None, timeout=30):
    """(상태, 응답 머리글 dict(소문자 이름), 본문 bytes, JSON 또는 None). 연결이 안 되면 (0, {}, b"", None)."""
    headers = {}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    try:
        c = http.client.HTTPConnection(HOST, PORT, timeout=timeout)
        c.request(method, path, body=data, headers=headers)
        r = c.getresponse()
        raw = r.read()
        head = {k.lower(): v for k, v in r.getheaders()}
        c.close()
    except OSError as e:
        return 0, {}, str(e).encode("utf-8", "replace"), None
    try:
        js = json.loads(raw.decode("utf-8")) if raw else None
    except ValueError:
        js = None
    return r.status, head, raw, js


def login(uid, pw):
    status, _, _, js = call("POST", "/api/login", {"id": uid, "password": pw})
    return status, (js or {}).get("token"), (js or {}).get("session") or {}


def first_live(token, wait=120):
    """스트림을 열어 heartbeat 가 든 live 이벤트를 기다린다 → (상태, 그 값 또는 None)."""
    try:
        c = http.client.HTTPConnection(HOST, PORT, timeout=45)
        c.request("GET", "/api/stream", headers={"Authorization": "Bearer " + token})
        r = c.getresponse()
    except OSError as e:
        return 0, str(e)
    if r.status != 200:
        return r.status, None
    end, event = time.time() + wait, None
    try:
        while time.time() < end:
            line = r.fp.readline()
            if not line:
                break
            line = line.decode("utf-8", "replace").rstrip("\r\n")
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: ") and event == "live":
                value = json.loads(line[6:])
                if isinstance(value, dict) and value.get("heartbeat"):
                    return 200, value
    except OSError:
        pass
    finally:
        c.close()
    return 200, None


def wait_command(token, key, finals=("done", "failed", "expired"), wait=120):
    value = None
    end = time.time() + wait
    while time.time() < end:
        status, _, _, value = call("GET", f"/api/commands/{key}", token=token)
        if status == 200 and isinstance(value, dict) and value.get("state") in finals:
            return value
        time.sleep(1)
    return value


def runs(token):
    status, _, _, js = call("GET", "/api/runs?limit=20", token=token)
    return status, ((js or {}).get("runs") or []) if status == 200 else []


def full(uid, pw1, pw2):
    status, head, raw, _ = call("GET", "/")
    say(status == 200 and b"<html" in raw.lower() and "default-src 'self'" in head.get("content-security-policy", ""),
        "업체 웹 첫 화면 200 · CSP 머리글", f"{status} {head.get('content-security-policy')}")
    exp = expect()
    status, _, raw, _ = call("GET", "/edition.js")
    if exp.get("official"):
        say(status == 200 and b"standalone" in raw and b"TEST_BUILD = false" in raw and b"TEST_BUILD = true" not in raw,
            "edition.js = 스탠드얼론 · 정식 빌드 (웹 맨 위 '시험용 빌드' 띠 없음)", raw[:200].decode("utf-8", "replace"))
    else:
        say(status == 200 and b"standalone" in raw and b"TEST_BUILD = true" in raw, "edition.js = 스탠드얼론 · 시험용 빌드 표시",
            raw[:200].decode("utf-8", "replace"))
    status, _, _, _ = call("GET", "/firebase-config.js")
    say(status == 404, "firebase-config.js 는 내주지 않는다 (404)", str(status))
    status, token, sess = login(uid, pw1)
    say(status == 200 and token and sess.get("mustChange") is True and sess.get("role") == "admin",
        "첫 로그인 - 관리자, 비밀번호를 바꿔야 한다 (mustChange)", f"{status} {sess}")
    if not token:
        return
    status, _, _, _ = call("POST", "/api/commands", {"type": "launch", "args": {"target": "routine"}}, token=token)
    say(status == 403, "비밀번호를 바꾸기 전에는 명령을 못 보낸다 (403)", str(status))
    status, _, _, js = call("POST", "/api/password", {"current": pw1, "next": pw2}, token=token)
    say(status == 200 and (js or {}).get("ok") is True, "비밀번호 바꾸기", f"{status} {js}")
    status, token, sess = login(uid, pw2)
    say(status == 200 and token and sess.get("mustChange") is False, "새 비밀번호로 다시 로그인 (mustChange 없음)", f"{status} {sess}")
    old, _, _ = login(uid, pw1)
    say(old == 401, "첫 비밀번호로는 로그인되지 않는다 (401)", str(old))
    if not token:
        return
    status, _, _, js = call("GET", "/api/company", token=token)
    say(status == 200 and (js or {}).get("name") == exp.get("company") and (js or {}).get("cid") == exp.get("cid"),
        f"업체 정보 = 라이선스의 업체 ({exp.get('company')} · {exp.get('cid')})", f"{status} {js}")
    status, live = first_live(token)
    say(status == 200 and isinstance(live, dict), "스트림의 첫 live 에 heartbeat (에이전트가 로컬 서버에 현황을 올린다)", f"{status} {live}")
    status, _, _, js = call("POST", "/api/commands", {"type": "set_schedule", "args": SCHEDULE}, token=token)
    key = (js or {}).get("key")
    value = wait_command(token, key) if key else None
    say(isinstance(value, dict) and value.get("state") == "done", "set_schedule 명령 → done (자동 실행 03:17 저장)",
        f"{status} {json.dumps(value, ensure_ascii=False)[:300]}")
    if isinstance(value, dict):
        note(f"set_schedule 결과: {value.get('result')}")
    before = len(runs(token)[1])
    status, _, _, js = call("POST", "/api/commands", {"type": "launch", "args": {"target": "routine"}}, token=token)
    key = (js or {}).get("key")
    value = wait_command(token, key) if key else None
    say(isinstance(value, dict) and value.get("state") in ("done", "failed"), "launch 명령을 에이전트가 처리했다",
        f"{status} {json.dumps(value, ensure_ascii=False)[:300]}")
    if isinstance(value, dict):
        note(f"launch 결과: {value.get('state')} {value.get('result')}")
    rows, end = [], time.time() + 300           # 샌드박스에는 ERPia 가 없다 - PROCESS 는 곧 '중단' 으로 끝나고 기록이 올라온다
    while time.time() < end:
        status, rows = runs(token)
        if len(rows) > before:
            break
        time.sleep(3)
    say(len(rows) > before, "launch 한 실행이 /api/runs 에 한 줄 (ERPia 없이 끝난 실행)", f"기록 {len(rows)}줄 (전 {before})")
    if rows:
        note("실행 기록 첫 줄: " + json.dumps(rows[0], ensure_ascii=False)[:400])


def after(uid, pw1, pw2):
    status, token, sess = login(uid, pw2)
    say(status == 200 and token and sess.get("mustChange") is False, "덮어 설치 뒤: 바꾼 비밀번호로 로그인된다 (계정이 남았다)", f"{status} {sess}")
    old, _, _ = login(uid, pw1)
    say(old == 401, "덮어 설치 뒤: 첫 비밀번호로는 안 된다", str(old))
    if token:
        _, rows = runs(token)
        say(len(rows) >= 1, "덮어 설치 뒤: 실행 기록이 남아 있다", f"{len(rows)}줄")
        status, live = first_live(token)
        say(status == 200 and isinstance(live, dict), "덮어 설치 뒤: 에이전트가 다시 현황을 올린다 (heartbeat)", f"{status} {live}")


def main(argv):
    global OUT
    if len(argv) != 5 or argv[0] not in ("full", "after"):
        print(__doc__)
        return 2
    OUT = argv[4]
    try:
        (full if argv[0] == "full" else after)(*argv[1:4])
    except Exception as e:                       # 예상 못 한 오류도 결과 표에 (까닭의 종류와 글)
        say(False, f"check_standalone {argv[0]} 가 끝까지 돌았다", f"{type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
