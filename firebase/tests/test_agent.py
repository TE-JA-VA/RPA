"""에이전트 단위 시험. Firebase 없이 돈다.

실행: python tests/test_agent.py   (D:\\AX\\RPA\\firebase 에서)
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent"))

FAIL = []
COUNT = 0


def check(ok, label):
    global COUNT
    COUNT += 1
    if ok:
        print(f"  통과  {label}")
    else:
        FAIL.append(label)
        print(f"  실패  {label}")


print("1절 설정과 비밀번호 보관")
import secret

blob = secret.protect("비밀번호-시험-1234")
check(isinstance(blob, str) and "비밀번호" not in blob, "감싼 값에 평문이 보이지 않는다")
check(secret.unprotect(blob) == "비밀번호-시험-1234", "감쌌다가 풀면 원래 값")
check(secret.protect("같은값") != secret.protect("같은값"), "같은 값이라도 결과가 다르다")

with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "agent_config.json")
    secret.write_config(p, {
        "project_id": "proj", "api_key": "key", "database_url": "https://db",
        "cid": "c_demo", "pc_id": "pc_office", "email": "a@b.c",
    }, "비밀번호-시험-1234")
    raw = open(p, encoding="utf-8").read()
    check("비밀번호-시험-1234" not in raw, "설정 파일에 평문 비밀번호가 없다")
    check("password_dpapi" in json.loads(raw), "password_dpapi 로 저장한다")
    cfg = secret.load_config(p)
    check(cfg["password"] == "비밀번호-시험-1234", "읽으면 비밀번호가 풀린다")
    check(cfg["cid"] == "c_demo" and cfg["pc_id"] == "pc_office", "나머지 값도 읽는다")

    json.dump({"cid": "c_demo"}, open(p, "w", encoding="utf-8"))
    try:
        secret.load_config(p)
        check(False, "빠진 항목이 있으면 막는다")
    except ValueError as e:
        check("api_key" in str(e), "빠진 항목이 있으면 막는다")

print("\n2절 Firebase REST 클라이언트")
import io
import fb

CFG = {"project_id": "proj", "api_key": "KEY", "database_url": "https://db.example.com",
       "cid": "c_demo", "pc_id": "pc_office", "email": "a@b.c", "password": "pw"}


class FakeHTTP:
    """urlopen 을 대신한다. 부른 내역을 남기고 미리 정한 응답을 돌려준다."""

    def __init__(self):
        self.calls = []
        self.replies = []
        self.now = 1000.0

    def add(self, payload, status=200):
        self.replies.append((status, json.dumps(payload).encode("utf-8")))

    def __call__(self, req, timeout=None):
        body = req.data.decode("utf-8") if req.data else None
        self.calls.append((req.get_method(), req.full_url, body, dict(req.headers)))
        status, data = self.replies.pop(0)
        if status >= 400:
            import urllib.error
            raise urllib.error.HTTPError(req.full_url, status, "err", {}, io.BytesIO(data))
        return io.BytesIO(data)


http = FakeHTTP()
http.add({"idToken": "T1", "refreshToken": "R1", "expiresIn": "3600"})
c = fb.Client(CFG, opener=http, clock=lambda: http.now)
check(c.token() == "T1", "비밀번호로 첫 토큰을 받는다")
check("signInWithPassword?key=KEY" in http.calls[0][1], "로그인 주소에 api_key 를 쓴다")
check("pw" in http.calls[0][2], "로그인 요청에만 비밀번호가 들어간다")

check(c.token() == "T1" and len(http.calls) == 1, "만료 전에는 다시 받지 않는다")

http.now = 1000.0 + 3600 - 30      # 만료 30초 전
http.add({"id_token": "T2", "refresh_token": "R2", "expires_in": "3600"})
check(c.token() == "T2", "만료가 가까우면 갱신한다")
check("securetoken" in http.calls[1][1] and "R1" in http.calls[1][2], "갱신은 refresh token 으로")
check("pw" not in http.calls[1][2], "갱신 요청에는 비밀번호가 없다")

http.add({"ok": True})
c.put("live/c_demo/pc_office", {"host": "PC1"})
method, url, body, _ = http.calls[-1]
check(method == "PUT" and url.startswith("https://db.example.com/live/c_demo/pc_office.json"), "PUT 주소")
check("auth=T2" in url, "요청에 토큰을 싣는다")
check(json.loads(body) == {"host": "PC1"}, "보낸 몸통")

http.add({"ok": True})
c.patch("commands/c_demo/pc_office/x", {"state": "running"})
check(http.calls[-1][0] == "PATCH", "PATCH 로 일부만 고친다")

http.add({"error": "Permission denied"}, status=401)
http.add({"id_token": "T3", "refresh_token": "R3", "expires_in": "3600"})
http.add({"ok": True})
c.put("live/c_demo/pc_office", {"host": "PC1"})
check(c.token() == "T3", "401 이면 토큰을 새로 받고 한 번 더 시도한다")

http.add({"error": "Permission denied"}, status=403)
try:
    c.put("live/other/pc", {"x": 1})
    check(False, "거부는 HttpError 로 올린다")
except fb.HttpError as e:
    check(e.status == 403, "거부는 HttpError 로 올린다")

check(fb.parse_sse(["event: put", 'data: {"path":"/","data":{"a":1}}', ""]) ==
      [("put", {"path": "/", "data": {"a": 1}})], "SSE 한 덩이를 읽는다")
check(fb.parse_sse(["event: keep-alive", "data: null", ""]) == [("keep-alive", None)], "keep-alive 를 읽는다")

print(f"\n{COUNT - len(FAIL)}/{COUNT} 통과")
if FAIL:
    print("실패:", ", ".join(FAIL))
    sys.exit(1)
