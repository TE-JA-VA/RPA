# -*- coding: utf-8 -*-
"""스탠드얼론 로컬 서버의 웹 창구 (설계 2026-11-23-standalone 6.2·6.3·6.5, 계획 ② Task 2).
계정·탭 단위 세션·잠금·/api·스트림·웹 파일 내주기. 브라우저 없이 urllib 로 본다 - 화면은 tests/check_web_local.py (Task 3).
임시 폴더만 쓴다. 미사용·잠금 시간은 가짜 시계로 넘긴다 (기다리지 않는다).
    .venv\\Scripts\\python.exe tests\\test_local_web_api.py
"""
import hashlib
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
import local_server  # noqa: E402
import local_store  # noqa: E402
import local_web  # noqa: E402

fails = []
TMP = tempfile.mkdtemp(prefix="rpa_lweb_")
DATA = os.path.join(TMP, "standalone")           # 서버 자료 폴더 (열쇠·계정·기록 파일)
WEB = os.path.join(TMP, "web")                   # 웹 파일 폴더 (진짜 firebase/web 의 사본)
LIC = {"edition": "standalone", "company": "시험상사", "cid": "c1", "pc_id": "p1", "issued": "2026-11-23",
       "modules": {"Hold": False}, "features": {"wellife": False}, "limits": {"schedule": 3, "presets": None, "parallel": None}}
NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))
BOSS_PW, STAFF_PW = "pw-12345678", "staff-pw-0001"
CSP = ("default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'; "
       "base-uri 'none'; form-action 'self'")
SKEW = [0.0]                                     # 가짜 시계 = 진짜 시각 + 이 값
PASSWORDS = {BOSS_PW, STAFF_PW}                  # 시험에 쓴 비밀번호 - 끝에 기록·응답에 없는지 본다
TOKENS, BODIES = [], []                          # 받은 세션 토큰, 모든 응답 본문


def clock():
    return time.time() + SKEW[0]


def later(sec):
    SKEW[0] += sec


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


class Got:
    def __init__(self, status, raw, headers):
        self.status, self.raw, self.headers = status, raw, headers

    def json(self):
        return json.loads(self.raw) if self.raw else None

    @property
    def code(self):
        try:
            v = self.json()
        except ValueError:
            return None
        return v.get("code") if isinstance(v, dict) else None

    def __repr__(self):
        return f"<{self.status} {self.raw[:200]}>"


def api(method, path, body=None, token=None, headers=None, raw=None, base=None):
    """요청 한 번. token 이 있으면 Authorization: Bearer 로. headers 로 Host·Origin 등을 바꿔 끼운다."""
    data = raw if raw is not None else (None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8"))
    hs = {}
    if data is not None:
        hs["Content-Type"] = "application/json"
    if token:
        hs["Authorization"] = "Bearer " + token
    hs.update(headers or {})
    req = urllib.request.Request((base or BASE) + path, data=data, method=method, headers=hs)
    try:
        with NO_PROXY.open(req, timeout=15) as r:
            got, status, rh = r.read(), r.status, r.headers
    except urllib.error.HTTPError as e:
        got, status, rh = e.read(), e.code, e.headers
    BODIES.append(got)
    return Got(status, got.decode("utf-8", "replace"), rh)


def raw_get(target):
    """주소를 손대지 않고 그대로 보낸다 (urllib·http.client 가 고치거나 거절하는 글자까지). → (상태, 본문 글)"""
    s = socket.create_connection(("127.0.0.1", PORT), timeout=10)
    try:
        s.sendall(b"GET " + target + b" HTTP/1.0\r\nHost: 127.0.0.1:" + str(PORT).encode() + b"\r\n\r\n")
        buf = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
    finally:
        s.close()
    BODIES.append(buf)
    m = re.match(rb"HTTP/\d\.\d (\d{3})", buf)
    return (int(m.group(1)) if m else 0), buf.decode("utf-8", "replace")


def login(uid, pw, **kw):
    PASSWORDS.add(pw)
    r = api("POST", "/api/login", {"id": uid, "password": pw}, **kw)
    if r.status == 200:
        TOKENS.append(r.json()["token"])
    return r


def token_of(uid, pw):
    r = login(uid, pw)
    return r.json()["token"] if r.status == 200 else None


def wait_for(cond, sec=8.0):
    end = time.time() + sec
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return bool(cond())


class Stream:
    """/api/stream 을 다른 스레드에서 읽어 (event, data) 를 모은다."""

    def __init__(self, token=None, headers=None):
        self.events, self.status, self.ctype, self.ended, self.raw = [], None, "", False, ""
        hs = dict(headers or {})
        if token:
            hs["Authorization"] = "Bearer " + token
        self._req = urllib.request.Request(BASE + "/api/stream", headers=hs)
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def _run(self):
        try:
            with NO_PROXY.open(self._req, timeout=30) as r:
                self.status, self.ctype = r.status, r.headers.get("Content-Type") or ""
                event = data = None
                for line in r:
                    line = line.decode("utf-8", "replace").rstrip("\r\n")
                    self.raw += line + "\n"
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:"):
                        data = line[5:].strip()
                    elif line == "" and event is not None:
                        self.events.append((event, json.loads(data) if data else None))
                        event = data = None
        except urllib.error.HTTPError as e:
            self.status = e.code
            self.raw = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        self.ended = True

    def named(self, name):
        return [d for e, d in list(self.events) if e == name]

    def wait(self, cond, sec=8.0):
        return wait_for(lambda: cond(self), sec)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def raises(exc, fn, *args):
    try:
        fn(*args)
    except exc:
        return True
    except Exception:
        return False
    return False


CMDS = "apps/rpa/commands/c1/p1"
LIVE = "apps/rpa/live/c1/p1"
runs = srv = srv2 = None
try:
    os.makedirs(DATA)
    shutil.copytree(os.path.join(ROOT, "firebase", "web"), WEB)
    write(os.path.join(WEB, "notes.txt"), "허용 목록에 없는 확장자")
    write(os.path.join(WEB, ".secret.js"), "export const HIDDEN = 1;")
    write(os.path.join(DATA, "license.json"), '{"body": {}, "sig": "LICENSE-SIG-SECRET"}')
    store = local_server.Store(os.path.join(DATA, "store.json"), volatile=local_server.VOLATILE)
    runs = local_server.Runs(os.path.join(DATA, "runs.db"))
    AGENT, RELAY = local_server.ensure_keys(DATA)
    web = local_web.Web(store, runs, LIC, DATA, WEB, clock=clock)
    srv = local_server.make_server(store, runs, LIC, (AGENT, RELAY), port=0, folder=DATA, web=web)
    PORT = srv.server_address[1]
    BASE = f"http://127.0.0.1:{PORT}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    ACC = os.path.join(DATA, "accounts.json")

    def signed(method, path, body=None, key=None):
        """에이전트 열쇠로 서명한 요청 (/db·/fs 창구가 받는 꼴)."""
        key = key or AGENT
        data = b"" if body is None else json.dumps(body).encode("utf-8")
        return api(method, path, raw=data or None, headers=local_store.sign_headers(key, "agent", method, path, data))

    # ------------------------------------------------------------------------------------------
    print("계정 파일 (Accounts)")
    check("계정 파일이 없으면 계정도 없다 (기본 계정을 만들지 않는다)", web.accounts.list() == [] and not os.path.exists(ACC))
    check("계정 파일이 없으면 로그인은 늘 틀림", login("boss", BOSS_PW).code == "auth/invalid-credential" and not os.path.exists(ACC))
    web.accounts.set("boss", BOSS_PW, "admin")
    web.accounts.set("staff", STAFF_PW, "viewer")
    check("계정 목록 - 아이디·권한·중지·바꿔야 함 뿐", web.accounts.list() == [
        {"id": "boss", "role": "admin", "disabled": False, "must_change": False},
        {"id": "staff", "role": "viewer", "disabled": False, "must_change": False}], repr(web.accounts.list()))
    saved = json.load(open(ACC, encoding="utf-8"))
    rec = saved["accounts"]["boss"]
    check("비밀번호는 파일에 그대로 없다", BOSS_PW not in json.dumps(saved) and STAFF_PW not in json.dumps(saved))
    check("소금은 계정마다 16바이트", len(bytes.fromhex(rec["salt"])) == 16 and rec["salt"] != saved["accounts"]["staff"]["salt"])
    check("해시 = pbkdf2_hmac(sha256, 비밀번호, 소금, 310000)",
          rec["hash"] == hashlib.pbkdf2_hmac("sha256", BOSS_PW.encode("utf-8"), bytes.fromhex(rec["salt"]), 310000).hex()
          and local_web.PBKDF2_ITER == 310000)
    check("임시 파일이 남지 않는다 (원자적 저장)", sorted(n for n in os.listdir(DATA) if n.startswith("accounts")) == ["accounts.json"],
          repr(os.listdir(DATA)))
    check("verify - 맞으면 계정, 틀리면 None", (web.accounts.verify("boss", BOSS_PW) or {}).get("role") == "admin"
          and web.accounts.verify("boss", "wrong-pw-0000") is None and web.accounts.verify("nobody", BOSS_PW) is None)
    check("아이디 꼴이 아니면 ValueError", all(raises(ValueError, web.accounts.set, bad, "pw-12345678", "viewer")
                                       for bad in ("a", "한글아이디", "a b", "x" * 33, "a/b", "ab\nc", "")))
    check("짧은 비밀번호는 ValueError", raises(ValueError, web.accounts.set, "short1", "1234567", "viewer"))
    check("모르는 권한은 ValueError", raises(ValueError, web.accounts.set, "role1", "pw-12345678", "owner"))
    check("거절된 계정은 생기지 않는다", [a["id"] for a in web.accounts.list()] == ["boss", "staff"])
    check("마지막 관리자는 중지할 수 없다", raises(ValueError, web.accounts.disable, "boss", True))
    check("마지막 관리자는 지울 수 없다", raises(ValueError, web.accounts.remove, "boss"))
    check("마지막 관리자를 유저로 바꿀 수 없다", raises(ValueError, web.accounts.set, "boss", BOSS_PW, "viewer"))
    check("그 뒤에도 관리자는 그대로", web.accounts.list()[0] == {"id": "boss", "role": "admin", "disabled": False, "must_change": False})
    other = local_web.Accounts(ACC)                  # 설정 창처럼 다른 곳에서 같은 파일을 고친다
    other.set("outside", "outside-pw-01", "viewer", must_change=True)
    PASSWORDS.add("outside-pw-01")
    check("다른 곳에서 고친 파일을 다시 읽는다", [a["id"] for a in web.accounts.list()] == ["boss", "outside", "staff"]
          and web.accounts.list()[1]["must_change"] is True)
    other.remove("outside")
    write(os.path.join(TMP, "broken", "accounts.json"), "{ 깨진 파일")
    check("깨진 계정 파일 - 죽지 않고 계정 없음", local_web.Accounts(os.path.join(TMP, "broken", "accounts.json")).list() == [])

    # ------------------------------------------------------------------------------------------
    print("로그인")
    r = login("boss", BOSS_PW)
    BOSS = r.json().get("token") if r.status == 200 else None
    check("맞는 비밀번호 → 토큰과 세션", r.status == 200 and isinstance(BOSS, str) and len(BOSS) >= 40
          and r.json()["session"] == {"uid": "boss", "id": "boss", "email": "boss", "cid": "c1", "role": "admin", "mustChange": False}, repr(r))
    check("응답은 토큰·세션 둘뿐 (해시·소금 없음)", r.status == 200 and sorted(r.json()) == ["session", "token"])
    check("쿠키를 쓰지 않는다", r.headers.get("Set-Cookie") is None)
    r = login("boss", "wrong-pw-0000")
    wrong_msg = (r.json() or {}).get("message")
    check("틀린 비밀번호 401 auth/invalid-credential", r.status == 401 and r.code == "auth/invalid-credential" and bool(wrong_msg), repr(r))
    r = login("nobody", BOSS_PW)
    check("없는 아이디도 401 같은 code·같은 글", r.status == 401 and r.code == "auth/invalid-credential" and r.json().get("message") == wrong_msg, repr(r))
    r = login("BOSS", BOSS_PW)
    check("대문자 아이디 BOSS 도 로그인", r.status == 200 and r.json()["session"]["id"] == "boss", repr(r))
    r = login("staff", STAFF_PW)
    STAFF = r.json().get("token") if r.status == 200 else None
    check("유저 로그인 - role viewer", r.status == 200 and r.json()["session"]["role"] == "viewer", repr(r))
    web.accounts.set("gone1", "gone1-pw-0001", "viewer")
    web.accounts.disable("gone1", True)
    r = login("gone1", "gone1-pw-0001")
    check("중지 계정 403 auth/user-disabled", r.status == 403 and r.code == "auth/user-disabled", repr(r))
    r = login("gone1", "wrong-pw-0000")
    check("중지 계정이라도 비밀번호가 틀리면 그냥 틀림 (중지 여부를 알려 주지 않는다)", r.status == 401 and r.code == "auth/invalid-credential", repr(r))
    check("아이디·비밀번호가 글이 아니면 400", api("POST", "/api/login", {"id": ["boss"], "password": BOSS_PW}).status == 400
          and api("POST", "/api/login", {"id": "boss"}).status == 400 and api("POST", "/api/login", ["boss", BOSS_PW]).status == 400)
    check("깨진 본문 400", api("POST", "/api/login", raw=b'{"id": ').status == 400)
    check("GET /api/login 은 405", api("GET", "/api/login").status == 405)
    # 없는 아이디도 진짜 계정과 같은 계산을 한 번 한다 (걸리는 시간으로 아이디가 있는지 알 수 없게)
    counted, real_pbkdf2 = [], hashlib.pbkdf2_hmac

    def counting(name, password, salt, iterations, *a, **k):
        counted.append((name, len(salt), iterations))
        return real_pbkdf2(name, password, salt, iterations, *a, **k)

    hashlib.pbkdf2_hmac = counting
    try:
        login("nobody2", BOSS_PW)
        n_unknown = list(counted)
        del counted[:]
        login("staff", "wrong-pw-0000")
        n_known = list(counted)
        del counted[:]
        login("이상한 아이디!!", BOSS_PW)
        n_bad = list(counted)
    finally:
        hashlib.pbkdf2_hmac = real_pbkdf2
    check("없는 아이디도 가짜 해시를 한 번 계산한다", n_unknown == [("sha256", 16, 310000)] and n_known == n_unknown and n_bad == n_unknown,
          f"{n_unknown} {n_known} {n_bad}")

    # ------------------------------------------------------------------------------------------
    print("잠금 (Review Focus 2)")
    web.accounts.set("lock1", "lock1-pw-0001", "viewer")
    got = [login("lock1", "wrong-pw-0000").status for _ in range(5)]
    check("다섯 번 틀릴 때까지는 401", got == [401] * 5, repr(got))
    r = login("lock1", "lock1-pw-0001")
    check("5번 틀린 뒤에는 맞는 비밀번호도 429 auth/too-many-requests", r.status == 429 and r.code == "auth/too-many-requests", repr(r))
    check("대문자로 적어도 같은 잠금", login("LOCK1", "lock1-pw-0001").status == 429)
    later(30)
    check("30초 뒤에도 잠김", login("lock1", "lock1-pw-0001").status == 429)
    later(31)
    r = login("lock1", "lock1-pw-0001")
    check("61초 뒤 로그인", r.status == 200, repr(r))
    got = [login("lock1", "wrong-pw-0000").status for _ in range(4)] + [login("lock1", "lock1-pw-0001").status]
    got += [login("lock1", "wrong-pw-0000").status for _ in range(4)] + [login("lock1", "lock1-pw-0001").status]
    check("성공하면 실패 수가 0 (4번 틀림 → 성공 → 4번 틀림 → 성공)", got == [401] * 4 + [200] + [401] * 4 + [200], repr(got))
    got = [login("ghost9", "wrong-pw-0000").status for _ in range(6)]
    check("없는 아이디도 똑같이 잠긴다 (아이디가 있는지 드러나지 않는다)", got == [401] * 5 + [429], repr(got))
    check("다른 계정은 잠기지 않는다", login("staff", STAFF_PW).status == 200)
    web.accounts.set("race1", "race1-pw-0001", "viewer")
    got = []
    ts = [threading.Thread(target=lambda: got.append(login("race1", "wrong-pw-0000").status)) for _ in range(12)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    check("한꺼번에 틀려도 비밀번호는 다섯 번까지만 견준다 (나머지는 429)", sorted(got) == [401] * 5 + [429] * 7, repr(got))
    lo = local_web.Lockout(limit=5, lock_sec=60, clock=clock)
    for _ in range(4):
        lo.fail("x")
    four = lo.locked("x")
    lo.fail("x")
    five = lo.locked("x")
    later(61)
    after = lo.locked("x")
    lo.fail("x")
    check("Lockout - 4번은 아님, 5번째에 잠금, 60초 뒤 풀리고 다시 0 부터", (four, five, after, lo.locked("x")) == (False, True, False, False))
    lo.ok("x")
    later(120)                                      # 위에서 잠근 것들이 모두 풀리게

    # ------------------------------------------------------------------------------------------
    print("세션 (Review Focus 1)")
    check("토큰 없이 401", api("GET", "/api/session").status == 401)
    check("엉터리 토큰 401", api("GET", "/api/session", token="x" * 43).status == 401)
    t1 = token_of("boss", BOSS_PW)
    r = api("GET", "/api/session", token=t1)
    check("세션 읽기 - 세션과 서버 시각", r.status == 200 and r.json()["session"]["role"] == "admin"
          and abs(r.json()["now_ms"] - clock() * 1000) < 5000 and sorted(r.json()) == ["now_ms", "session"], repr(r))
    check("세션 토큰을 Bearer 가 아닌 꼴로 보내면 401", api("GET", "/api/session", headers={"Authorization": t1}).status == 401
          and api("GET", f"/api/session?token={t1}").status == 401)
    later(1700)
    check("28분 뒤에는 아직 로그인", api("GET", "/api/session", token=t1).status == 200)
    later(101)
    check("그냥 읽기는 시계를 되돌리지 않는다 - 1801초 뒤 401", api("GET", "/api/session", token=t1).status == 401)
    check("한 번 끝난 세션은 돌아오지 않는다", api("GET", "/api/session?touch=1", token=t1).status == 401)
    t2 = token_of("boss", BOSS_PW)
    later(1000)
    a = api("GET", "/api/session?touch=1", token=t2).status
    later(1000)
    b = api("GET", "/api/session", token=t2).status          # 처음부터 2000초 - touch 가 없었다면 끝났다
    later(801)
    c = api("GET", "/api/session", token=t2).status          # touch 뒤 1801초
    check("?touch=1 이 미사용 시계를 되돌린다", (a, b, c) == (200, 200, 401), repr((a, b, c)))
    t3 = token_of("boss", BOSS_PW)
    got = []
    for _ in range(26):                                      # 1700초마다 쓰면 미사용으로는 안 끝난다 - 25번째 42500초, 26번째 44200초
        later(1700)
        got.append(api("GET", "/api/session?touch=1", token=t3).status)
    check("12시간이 넘으면 계속 써도 401", got == [200] * 25 + [401], repr(got))
    t4 = token_of("boss", BOSS_PW)
    r = api("POST", "/api/logout", token=t4)
    check("로그아웃 뒤 401", r.status == 200 and api("GET", "/api/session", token=t4).status == 401, repr(r))
    check("토큰 없는 로그아웃 401", api("POST", "/api/logout").status == 401)
    BOSS, STAFF = token_of("boss", BOSS_PW), token_of("staff", STAFF_PW)
    # 에이전트 열쇠와 세션 토큰은 서로의 창구에서 통하지 않는다
    check("에이전트 서명으로 /api/session 401", signed("GET", "/api/session").status == 401)
    check("에이전트 열쇠를 Bearer 로 보내도 401", api("GET", "/api/session", token=AGENT).status == 401)
    check("에이전트 서명으로 명령을 만들지 못한다", signed("POST", "/api/commands", {"type": "launch", "args": None}).status == 401)
    check("세션 토큰으로 /db 401", api("GET", f"/db/{LIVE}.json", token=BOSS).status == 401
          and api("PUT", f"/db/{LIVE}.json", {"state": "x"}, token=BOSS).status == 401)
    check("세션 토큰으로 /fs·/fs-sum 401", api("GET", "/fs/runs/c1/items/d1", token=BOSS).status == 401
          and api("GET", "/fs-sum?parent=runs/c1&collection=items&field=cost", token=BOSS).status == 401)
    r = signed("PUT", f"/db/{LIVE}.json?print=silent", {"state": "idle"})
    check("에이전트 창구는 그대로 (서명한 요청 통과, 응답에 서명)", r.status == 204 and bool(r.headers.get(local_store.H_SIGN)), repr(r))
    r = api("GET", "/api/session", token=BOSS)
    check("/api 응답에는 서명 머리글이 없다", r.status == 200 and r.headers.get(local_store.H_SIGN) is None)
    check("/api 응답 보안 머리글", r.headers.get("Content-Security-Policy") == CSP and r.headers.get("X-Content-Type-Options") == "nosniff"
          and r.headers.get("X-Frame-Options") == "DENY" and r.headers.get("Cache-Control") == "no-store"
          and r.headers.get("Referrer-Policy") == "no-referrer" and "application/json" in (r.headers.get("Content-Type") or ""), repr(dict(r.headers)))
    r = api("GET", "/api/session")
    check("거절 응답에도 보안 머리글·code·사람 말", r.headers.get("Content-Security-Policy") == CSP and r.headers.get("Cache-Control") == "no-store"
          and isinstance(r.code, str) and bool(r.json().get("message")), repr(r))
    check("모르는 /api 주소 404", api("GET", "/api/nothing", token=BOSS).status == 404 and api("GET", "/api/", token=BOSS).status == 404)

    # ------------------------------------------------------------------------------------------
    print("업체 정보")
    r = api("GET", "/api/company", token=STAFF)
    check("업체 정보는 라이선스에서", r.json() == {
        "name": "시험상사", "stts": 0, "pcs": {"p1": {"label": socket.gethostname()}}, "cid": "c1", "pcId": "p1",
        "apps": {"rpa": {"modules": {"Hold": False}, "limits": {"schedule": 3, "presets": None, "parallel": None}, "features": {"wellife": False}}}}, repr(r))
    check("토큰 없이 업체 정보 401", api("GET", "/api/company").status == 401)

    # ------------------------------------------------------------------------------------------
    print("명령 (Review Focus 3)")
    check("명령 만료 값·보낼 수 있는 종류", local_web.QUICK_TTL == 90 and local_web.COMMAND_TTL == 600 and tuple(local_web.WEB_TYPES) == (
        "launch", "stop_erpia", "stop_rpa", "set_modules", "set_schedule", "set_presets", "set_parallel", "set_together", "resume_repeat"))
    r = api("POST", "/api/commands", {"type": "launch", "args": {"target": "all"}}, token=BOSS)
    K1 = (r.json() or {}).get("key") or "none"
    v = store.get(f"{CMDS}/{K1}") or {}
    check("관리자 launch → 저장소에 대기 명령", r.status == 200 and re.fullmatch(r"\d{13}[0-9a-f]{8}", K1) is not None
          and v == r.json()["value"] and v.get("state") == "queued" and v.get("type") == "launch" and v.get("args") == {"target": "all"}
          and v.get("by") == "boss" and sorted(v) == ["args", "by", "created_at", "expires_at", "state", "type"], repr(r))
    check("launch 는 90초 뒤 만료, 시각은 서버가 적는다(초)", v.get("expires_at", 0) - v.get("created_at", 0) == 90
          and abs(v.get("created_at", 0) - clock()) < 5 and isinstance(v.get("created_at"), int), repr(v))
    check("명령 키 앞 13자리는 만든 시각(ms)", abs(int(K1[:13] or 0) - clock() * 1000) < 5000, K1)
    r = api("POST", "/api/commands", {"type": "set_schedule", "args": {"enabled": False}}, token=BOSS)
    K2 = (r.json() or {}).get("key") or "none"
    v2 = store.get(f"{CMDS}/{K2}") or {}
    check("set_schedule 은 600초", r.status == 200 and v2.get("expires_at", 0) - v2.get("created_at", 0) == 600, repr(r))
    check("만든 순서로 줄 선다", K2[:13] >= K1[:13] and K1 != K2)
    r = api("POST", "/api/commands", {"type": "stop_rpa"}, token=BOSS)
    K3 = (r.json() or {}).get("key") or "none"
    check("args 없이 (null) 도 된다", r.status == 200 and "args" not in (store.get(f"{CMDS}/{K3}") or {"args": 1})
          and r.json()["value"]["expires_at"] - r.json()["value"]["created_at"] == 90, repr(r))
    r = api("POST", "/api/commands", {"type": "stop_erpia", "args": None, "by": "evil", "state": "done", "created_at": 1,
                                      "expires_at": 9e12, "result": "x"}, token=BOSS)
    v = (r.json() or {}).get("value") or {}
    check("보낸 쪽이 적은 by·상태·시각은 쓰지 않는다", r.status == 200 and v.get("by") == "boss" and v.get("state") == "queued"
          and v.get("expires_at", 0) - v.get("created_at", 0) == 90 and "result" not in v and abs(v.get("created_at", 0) - clock()) < 5, repr(r))
    before = store.get(CMDS)
    r = api("POST", "/api/commands", {"type": "launch", "args": {"target": "all"}}, token=STAFF)
    check("유저(viewer)는 403 PERMISSION_DENIED", r.status == 403 and r.code == "PERMISSION_DENIED", repr(r))
    check("토큰 없이 명령 401", api("POST", "/api/commands", {"type": "launch", "args": None}).status == 401)
    got = {t: api("POST", "/api/commands", {"type": t, "args": None}, token=BOSS).status
           for t in ("update", "rollback", "export_preset", "import_preset", "undo_import", "", "LAUNCH")}
    check("update·프리셋 옮기기 등 목록 밖 종류 400", set(got.values()) == {400}, repr(got))
    check("종류가 글이 아니면 400", api("POST", "/api/commands", {"type": ["launch"], "args": None}, token=BOSS).status == 400
          and api("POST", "/api/commands", {"args": None}, token=BOSS).status == 400)
    check("args 에 excel_pw 칸 400", api("POST", "/api/commands", {"type": "set_presets", "args": {"a": True, "excel_pw": "1234"}}, token=BOSS).status == 400)
    check("args 안쪽 깊은 곳의 excel_pw 도 400", api("POST", "/api/commands", {"type": "set_presets", "args": {"a": [{"excel_pw": "1"}]}}, token=BOSS).status == 400)
    check("args 가 글·목록·숫자면 400", [api("POST", "/api/commands", {"type": "launch", "args": a}, token=BOSS).status
                                 for a in ("all", ["all"], 3, True)] == [400] * 4)
    deep = {}
    node = deep
    for _ in range(60):
        node["a"] = {}
        node = node["a"]
    check("args 가 너무 깊으면 400", api("POST", "/api/commands", {"type": "launch", "args": deep}, token=BOSS).status == 400)
    check("본문이 dict 가 아니면 400", api("POST", "/api/commands", ["launch"], token=BOSS).status == 400
          and api("POST", "/api/commands", raw=b"", token=BOSS).status == 400)
    check("거절된 요청은 명령을 만들지 않는다", store.get(CMDS) == before)
    r = signed("PATCH", f"/db/{CMDS}/{K1}.json?print=silent", {"state": "running", "started_at": 5})
    check("웹이 만든 명령을 에이전트 열쇠가 running 으로 옮긴다", r.status == 204 and store.get(f"{CMDS}/{K1}/state") == "running", repr(r))
    r = api("GET", f"/api/commands/{K1}", token=STAFF)
    check("명령 하나 읽기 (유저도)", r.status == 200 and r.json() == store.get(f"{CMDS}/{K1}") and r.json()["state"] == "running", repr(r))
    r = api("GET", "/api/commands/0000000000000deadbeef", token=BOSS)
    check("없는 명령은 null", r.status == 200 and r.raw.strip() == "null", repr(r))
    check("이상한 명령 키 400·토큰 없이 401", api("GET", "/api/commands/a%2Fb", token=BOSS).status == 400
          and api("GET", "/api/commands/..", token=BOSS).status == 400 and api("GET", f"/api/commands/{K1}").status == 401)
    check("명령 목록 통째 읽기·지우기·고치기 창구는 없다", api("GET", "/api/commands", token=BOSS).status == 405
          and api("DELETE", f"/api/commands/{K1}", token=BOSS).status == 405 and api("PUT", f"/api/commands/{K1}", {"state": "done"}, token=BOSS).status == 405
          and store.get(f"{CMDS}/{K1}/state") == "running")

    # ------------------------------------------------------------------------------------------
    print("스트림")
    s0 = Stream()
    check("토큰 없이 스트림 401", s0.wait(lambda s: s.ended) and s0.status == 401, repr(s0.status))
    store.delete(LIVE)
    ts = token_of("staff", STAFF_PW)
    s1 = Stream(ts)
    check("붙으면 live 한 번 (현황이 없으면 null)", s1.wait(lambda s: len(s.named("live")) >= 1) and s1.named("live") == [None]
          and s1.status == 200 and s1.ctype.startswith("text/event-stream"), repr((s1.status, s1.events)))
    store.put(LIVE, {"state": "idle", "heartbeat": {"at": 1}})
    check("현황을 쓰면 live 가 다시 온다 (전체 값)", s1.wait(lambda s: {"state": "idle", "heartbeat": {"at": 1}} in s.named("live")), repr(s1.events))
    store.patch(LIVE, {"heartbeat/at": 2})
    check("안쪽 칸만 바뀌어도 live 는 전체 값", s1.wait(lambda s: {"state": "idle", "heartbeat": {"at": 2}} in s.named("live")), repr(s1.events))
    n = len(s1.named("command"))
    store.patch(f"{CMDS}/{K2}", {"state": "running", "started_at": 7})
    check("명령 상태가 바뀌면 command {key, value}", s1.wait(lambda s: len(s.named("command")) > n)
          and s1.named("command")[-1] == {"key": K2, "value": store.get(f"{CMDS}/{K2}")} and s1.named("command")[-1]["value"]["state"] == "running",
          repr(s1.events))
    r = signed("PATCH", f"/db/{CMDS}.json?print=silent", {f"{K2}/state": "done", f"{K2}/result": "끝", f"{K2}/ended_at": 9})
    check("에이전트가 명령함 자리에서 여러 칸을 써도 그 명령이 온다", r.status == 204 and s1.wait(lambda s: any(
        c["key"] == K2 and (c["value"] or {}).get("state") == "done" and c["value"].get("result") == "끝" for c in s.named("command"))), repr(s1.events))
    r = api("POST", "/api/commands", {"type": "resume_repeat", "args": None}, token=BOSS)
    K4 = (r.json() or {}).get("key")
    check("새 명령도 스트림에 온다", s1.wait(lambda s: any(c["key"] == K4 and (c["value"] or {}).get("state") == "queued" for c in s.named("command"))),
          repr(s1.events))
    store.patch(f"{CMDS}/{K4}", {"state": "expired"})
    signed("DELETE", f"/db/{CMDS}/{K4}.json")
    check("지워진 명령은 value null", s1.wait(lambda s: {"key": K4, "value": None} in s.named("command")), repr(s1.events))
    check("스트림 이벤트에 서명 줄이 없다 (브라우저용)", "mac:" not in s1.raw and "event: live" in s1.raw)
    real_keep = local_server.KEEPALIVE_SEC
    local_server.KEEPALIVE_SEC = 1
    check("조용하면 keep-alive", s1.wait(lambda s: len(s.named("keep-alive")) >= 1, 6), repr(s1.events[-3:]))
    local_server.KEEPALIVE_SEC = real_keep
    check("스트림을 열어 둬도 구독은 하나", len(store._subs) == 1, repr(len(store._subs)))
    api("POST", "/api/logout", token=ts)
    check("세션을 닫으면 gone 을 보내고 끝난다", s1.wait(lambda s: s.ended, 6) and s1.events[-1:] == [("gone", None)], repr(s1.events[-2:]))
    check("끝난 스트림의 구독은 풀린다", wait_for(lambda: len(store._subs) == 0, 4), repr(len(store._subs)))
    ts = token_of("staff", STAFF_PW)
    s2 = Stream(ts)
    s2.wait(lambda s: len(s.named("live")) >= 1)
    later(1801)
    check("스트림은 미사용 시계를 되돌리지 않는다 (1801초 뒤 gone)", s2.wait(lambda s: s.ended, 6) and s2.events[-1:] == [("gone", None)], repr(s2.events[-2:]))
    BOSS, STAFF = token_of("boss", BOSS_PW), token_of("staff", STAFF_PW)
    real_max = local_web.MAX_STREAMS
    local_web.MAX_STREAMS = 1
    s3 = Stream(STAFF)
    s3.wait(lambda s: len(s.named("live")) >= 1)
    s4 = Stream(STAFF)
    check("스트림 수 상한을 넘으면 503 (에이전트가 붙을 자리를 남긴다)", s4.wait(lambda s: s.ended) and s4.status == 503, repr(s4.status))
    local_web.MAX_STREAMS = real_max

    # ------------------------------------------------------------------------------------------
    print("실행 기록")
    runs.create("runs/c1", "items", "d1", {"pcId": "p1", "date": "2026-11-22", "started_at": "2026-11-22T09:00:00", "program": "process"})
    runs.create("runs/c1", "items", "d2", {"pcId": "p1", "date": "2026-11-23", "started_at": "2026-11-23T09:00:00", "program": "actor"})
    runs.create("runs/c1", "items", "d3", {"pcId": "p9", "date": "2026-11-23", "started_at": "2026-11-23T10:00:00", "program": "other-pc"})
    runs.create("runs/c9", "items", "d4", {"pcId": "p1", "date": "2026-11-23", "started_at": "2026-11-23T11:00:00", "program": "other-company"})
    r = api("GET", "/api/runs", token=STAFF)
    got = [d.get("program") for d in (r.json() or {}).get("runs", [])]
    check("기록 - 이 PC 것만 최근 순", r.status == 200 and got == ["actor", "process"], repr(r))
    r = api("GET", "/api/runs?date=2026-11-22", token=STAFF)
    check("date 로 거르기", [d.get("program") for d in r.json()["runs"]] == ["process"], repr(r))
    check("limit", [d.get("program") for d in api("GET", "/api/runs?limit=1", token=STAFF).json()["runs"]] == ["actor"])
    check("limit 은 1~200 으로 맞춘다", len(api("GET", "/api/runs?limit=0", token=STAFF).json()["runs"]) == 1
          and api("GET", "/api/runs?limit=99999", token=STAFF).status == 200)
    check("limit·date 꼴이 아니면 400", api("GET", "/api/runs?limit=abc", token=STAFF).status == 400
          and api("GET", "/api/runs?date=2026-11-2", token=STAFF).status == 400 and api("GET", "/api/runs?date=x%27%20OR%201", token=STAFF).status == 400)
    r = api("GET", "/api/runs?pcId=p9", token=BOSS)
    check("다른 PC·업체 값은 받지 않는다 (403 permission-denied)", r.status == 403 and r.code == "permission-denied"
          and api("GET", "/api/runs?cid=c9", token=BOSS).status == 403 and api("GET", "/api/runs?pcId=p1&cid=c1", token=BOSS).status == 200, repr(r))
    check("토큰 없이 기록 401", api("GET", "/api/runs").status == 401)

    # ------------------------------------------------------------------------------------------
    print("계정 관리 (관리자)")
    r = api("GET", "/api/accounts", token=BOSS)
    rows = (r.json() or {}).get("accounts") or []
    check("계정 목록", r.status == 200 and [a["id"] for a in rows] == ["boss", "gone1", "lock1", "race1", "staff"]
          and all(sorted(a) == ["disabled", "id", "mustChange", "role"] for a in rows), repr(r))
    got = [api("GET", "/api/accounts", token=STAFF), api("POST", "/api/accounts", {"id": "sneak", "password": "sneak-pw-0001", "role": "admin"}, token=STAFF),
           api("POST", "/api/accounts/boss", {"password": "hijack-pw-001"}, token=STAFF), api("POST", "/api/accounts/boss", {"disabled": True}, token=STAFF),
           api("DELETE", "/api/accounts/boss", token=STAFF)]
    check("유저(viewer)는 계정 창구 모두 403 PERMISSION_DENIED", all(g.status == 403 and g.code == "PERMISSION_DENIED" for g in got), repr(got))
    check("유저의 시도 뒤 관리자는 그대로 로그인", login("boss", BOSS_PW).status == 200 and "sneak" not in [a["id"] for a in web.accounts.list()])
    check("토큰 없이 계정 창구 401", api("GET", "/api/accounts").status == 401 and api("POST", "/api/accounts", {"id": "x1", "password": "x1-pw-00001", "role": "viewer"}).status == 401)
    PASSWORDS.update({"temp1-pw-0001", "reset-pw-0001", "boss2-pw-0001"})
    r = api("POST", "/api/accounts", {"id": "Temp1", "password": "temp1-pw-0001", "role": "viewer"}, token=BOSS)
    check("유저 추가 (아이디는 소문자로) - 관리자가 만든 계정은 mustChange (관리자가 비밀번호를 안다 → 첫 로그인에 바꾸게)",
          r.status == 200 and {"id": "temp1", "role": "viewer", "disabled": False, "mustChange": True} in r.json()["accounts"], repr(r))
    r = login("temp1", "temp1-pw-0001")
    TEMP = (r.json() or {}).get("token")
    check("추가한 유저로 로그인 (mustChange 세션)", r.status == 200 and r.json()["session"]["role"] == "viewer"
          and r.json()["session"]["mustChange"] is True, repr(r))
    got = {p: api("GET", p, token=TEMP) for p in ("/api/runs", f"/api/commands/{K1}", "/api/accounts")}
    got["POST /api/commands"] = api("POST", "/api/commands", {"type": "launch", "args": None}, token=TEMP)
    got["POST /api/accounts"] = api("POST", "/api/accounts", {"id": "sneak2", "password": "sneak-pw-0002", "role": "viewer"}, token=TEMP)
    check("mustChange 세션은 서버도 막는다 - 기록·명령·계정 403 auth/must-change", all(
        g.status == 403 and g.code == "auth/must-change" and (g.json() or {}).get("message") == "비밀번호를 먼저 바꿔 주십시오."
        for g in got.values()), repr(got))
    check("mustChange 세션도 세션·업체 정보는 읽는다 (비밀번호 바꾸기 화면)", api("GET", "/api/session", token=TEMP).status == 200
          and api("GET", "/api/session?touch=1", token=TEMP).status == 200 and api("GET", "/api/company", token=TEMP).status == 200)
    check("이미 있는 아이디 400", api("POST", "/api/accounts", {"id": "temp1", "password": "other-pw-0001", "role": "viewer"}, token=BOSS).status == 400
          and login("temp1", "temp1-pw-0001").status == 200)
    got = [api("POST", "/api/accounts", {"id": i, "password": "valid-pw-0001", "role": "viewer"}, token=BOSS).status for i in ("a", "a b", "한글", "x" * 33, 7)]
    check("아이디 꼴이 아니면 400", got == [400] * 5, repr(got))
    r = api("POST", "/api/accounts", {"id": "short1", "password": "1234567", "role": "viewer"}, token=BOSS)
    check("짧은 비밀번호 400 auth/weak-password", r.status == 400 and r.code == "auth/weak-password", repr(r))
    check("모르는 권한 400", api("POST", "/api/accounts", {"id": "role1", "password": "valid-pw-0001", "role": "owner"}, token=BOSS).status == 400)
    st_temp = Stream(TEMP)
    check("mustChange 세션도 스트림은 붙는다", st_temp.wait(lambda s: len(s.named("live")) >= 1) and st_temp.status == 200, repr(st_temp.status))
    r = api("POST", "/api/accounts/temp1", {"disabled": True}, token=BOSS)
    check("사용 중지", r.status == 200 and {"id": "temp1", "role": "viewer", "disabled": True, "mustChange": True} in r.json()["accounts"], repr(r))
    r = login("temp1", "temp1-pw-0001")
    check("중지한 계정은 로그인 403", r.status == 403 and r.code == "auth/user-disabled", repr(r))
    check("중지한 계정의 열린 세션 401", api("GET", "/api/session", token=TEMP).status == 401)
    check("중지한 계정의 열린 스트림은 gone", st_temp.wait(lambda s: s.ended, 6) and st_temp.events[-1:] == [("gone", None)], repr(st_temp.events[-2:]))
    r = api("POST", "/api/accounts/temp1", {"disabled": False}, token=BOSS)
    TEMP = token_of("temp1", "temp1-pw-0001")
    check("다시 사용하면 로그인", r.status == 200 and TEMP is not None)
    r = api("POST", "/api/accounts/temp1", {"password": "reset-pw-0001"}, token=BOSS)
    check("비밀번호 다시 정하기 - 그 계정의 열린 세션 401·옛 비밀번호 틀림", r.status == 200 and api("GET", "/api/session", token=TEMP).status == 401
          and login("temp1", "temp1-pw-0001").status == 401, repr(r))
    r = login("temp1", "reset-pw-0001")
    TEMP = (r.json() or {}).get("token")
    check("다시 정한 비밀번호로 로그인하면 mustChange", r.status == 200 and r.json()["session"]["mustChange"] is True
          and {"id": "temp1", "role": "viewer", "disabled": False, "mustChange": True} in api("GET", "/api/accounts", token=BOSS).json()["accounts"], repr(r))
    check("다시 정하는 비밀번호가 짧으면 400", api("POST", "/api/accounts/temp1", {"password": "1234567"}, token=BOSS).code == "auth/weak-password"
          and api("POST", "/api/accounts/temp1", {"disabled": "yes"}, token=BOSS).status == 400 and api("POST", "/api/accounts/temp1", {}, token=BOSS).status == 400)
    r = api("DELETE", "/api/accounts/temp1", token=BOSS)
    check("지우기 - 목록에서 빠지고 로그인·세션이 끝난다", r.status == 200 and "temp1" not in [a["id"] for a in r.json()["accounts"]]
          and login("temp1", "reset-pw-0001").status == 401 and api("GET", "/api/session", token=TEMP).status == 401, repr(r))
    check("없는 계정은 404", api("DELETE", "/api/accounts/temp1", token=BOSS).status == 404 and api("POST", "/api/accounts/nobody", {"disabled": True}, token=BOSS).status == 404)
    check("자기 자신 지우기 400", api("DELETE", "/api/accounts/boss", token=BOSS).status == 400)
    check("자기 자신 중지 400", api("POST", "/api/accounts/boss", {"disabled": True}, token=BOSS).status == 400)
    check("자기 비밀번호는 계정 창구로 다시 정하지 못한다 (현재 비밀번호를 거치게)", api("POST", "/api/accounts/boss", {"password": "hijack-pw-001"}, token=BOSS).status == 400
          and api("GET", "/api/session", token=BOSS).status == 200 and login("boss", BOSS_PW).status == 200)
    r = api("POST", "/api/accounts", {"id": "boss2", "password": "boss2-pw-0001", "role": "admin"}, token=BOSS)
    B2 = token_of("boss2", "boss2-pw-0001")
    PASSWORDS.add("boss2-pw-0002")
    first = api("GET", "/api/accounts", token=B2)
    changed = api("POST", "/api/password", {"current": "boss2-pw-0001", "next": "boss2-pw-0002"}, token=B2)
    check("관리자 추가 - 새 관리자도 비밀번호를 바꾸기 전에는 계정 창구 403 auth/must-change, 바꾸면 200",
          r.status == 200 and first.status == 403 and first.code == "auth/must-change" and changed.status == 200
          and api("GET", "/api/accounts", token=B2).status == 200, repr((first, changed)))
    r = api("POST", "/api/accounts/boss2", {"disabled": True}, token=BOSS)
    check("다른 관리자 중지 - 그 세션은 끝", r.status == 200 and api("GET", "/api/accounts", token=B2).status == 401)
    check("남은 관리자 하나는 중지·삭제할 수 없다 (중지된 관리자는 세지 않는다)", raises(ValueError, web.accounts.disable, "boss", True)
          and raises(ValueError, web.accounts.remove, "boss"))
    check("계정 주소에 이상한 조각 400", api("DELETE", "/api/accounts/a%2Fb", token=BOSS).status == 400
          and api("DELETE", "/api/accounts/..%5Cx", token=BOSS).status == 400 and api("DELETE", "/api/accounts/boss2/x", token=BOSS).status == 404)
    api("DELETE", "/api/accounts/boss2", token=BOSS)

    # ------------------------------------------------------------------------------------------
    print("비밀번호 바꾸기")
    PASSWORDS.update({"first-pw-0001", "second-pw-001", "third-pw-0001"})
    web.accounts.set("pwuser", "first-pw-0001", "viewer", must_change=True)
    r = login("pwuser", "first-pw-0001")
    PA = (r.json() or {}).get("token")
    PB = token_of("pwuser", "first-pw-0001")
    check("바꿔야 하는 계정은 mustChange", r.status == 200 and r.json()["session"]["mustChange"] is True)
    PC_ = token_of("pwuser", "first-pw-0001")
    check("mustChange 세션도 로그아웃은 된다", api("POST", "/api/logout", token=PC_).status == 200 and api("GET", "/api/session", token=PC_).status == 401)
    r = api("POST", "/api/password", {"current": "wrong-pw-0000", "next": "second-pw-001"}, token=PA)
    check("틀린 현재 비밀번호 auth/wrong-password (세션은 그대로)", r.status == 403 and r.code == "auth/wrong-password"
          and api("GET", "/api/session", token=PA).status == 200, repr(r))
    r = api("POST", "/api/password", {"current": "first-pw-0001", "next": "1234567"}, token=PA)
    check("7자 auth/weak-password", r.status == 400 and r.code == "auth/weak-password", repr(r))
    r = api("POST", "/api/password", {"current": "first-pw-0001", "next": "first-pw-0001"}, token=PA)
    check("같은 비밀번호로는 바꾸지 못한다", r.status == 400 and r.code == "auth/weak-password", repr(r))
    check("글이 아니면 400·토큰 없이 401", api("POST", "/api/password", {"current": "first-pw-0001", "next": 12345678}, token=PA).status == 400
          and api("POST", "/api/password", {"current": "first-pw-0001", "next": "second-pw-001"}).status == 401)
    check("실패한 시도 뒤 비밀번호는 그대로", web.accounts.verify("pwuser", "first-pw-0001") is not None)
    r = api("POST", "/api/password", {"current": "first-pw-0001", "next": "second-pw-001"}, token=PA)
    check("바꾸기 성공 - 응답의 세션은 mustChange 꺼짐", r.status == 200 and r.json()["session"]["mustChange"] is False, repr(r))
    check("바꾼 탭은 로그인 유지, 그 계정의 다른 세션은 끝", api("GET", "/api/session", token=PA).status == 200 and api("GET", "/api/session", token=PB).status == 401)
    check("옛 비밀번호 로그인 실패", login("pwuser", "first-pw-0001").status == 401)
    r = login("pwuser", "second-pw-001")
    check("새 비밀번호 로그인·mustChange 꺼짐", r.status == 200 and r.json()["session"]["mustChange"] is False
          and api("GET", "/api/session", token=PA).json()["session"]["mustChange"] is False, repr(r))
    got = [api("POST", "/api/password", {"current": "wrong-pw-0000", "next": "third-pw-0001"}, token=PA).status for _ in range(5)]
    r = api("POST", "/api/password", {"current": "second-pw-001", "next": "third-pw-0001"}, token=PA)
    check("현재 비밀번호를 5번 틀리면 잠금 (열린 탭으로 비밀번호를 찍어 맞히지 못한다)", got == [403] * 5 and r.status == 429
          and r.code == "auth/too-many-requests" and web.accounts.verify("pwuser", "second-pw-001") is not None, repr((got, r)))
    later(61)
    # 설정 창(다른 프로세스)이 비밀번호를 다시 정하면 서버의 열린 세션도 끝난다
    PA = token_of("pwuser", "second-pw-001")
    local_web.Accounts(ACC).set("pwuser", "third-pw-0001", "viewer", must_change=True)
    check("밖에서 비밀번호를 다시 정해도 열린 세션은 끝난다", PA is not None and api("GET", "/api/session", token=PA).status == 401)

    # ------------------------------------------------------------------------------------------
    print("웹 파일 (Review Focus 5)")
    disk = open(os.path.join(WEB, "index.html"), encoding="utf-8").read()
    r = api("GET", "/")
    check("/ 는 index.html", r.status == 200 and "text/html" in (r.headers.get("Content-Type") or "") and "<html" in r.raw.lower(), repr(r)[:300])
    check("웹 파일 보안 머리글 (CSP·nosniff·DENY·no-cache·no-referrer)", r.headers.get("Content-Security-Policy") == CSP
          and r.headers.get("X-Content-Type-Options") == "nosniff" and r.headers.get("X-Frame-Options") == "DENY"
          and r.headers.get("Cache-Control") == "no-cache" and r.headers.get("Referrer-Policy") == "no-referrer", repr(dict(r.headers)))
    check("index.html 에 google-site-verification 줄이 없다 (원본에는 있다)", "google-site-verification" in disk
          and "google-site-verification" not in r.raw and "google-site-verification" not in api("GET", "/index.html").raw)
    check("그 줄만 빠진다", r.raw.count("\n") == disk.count("\n") - 1 and "<title>" in r.raw)
    r = api("GET", "/edition.js")
    check("/edition.js 는 늘 standalone (파일에는 cloud)", r.status == 200 and r.raw.strip() == 'export const EDITION = "standalone";'
          and "cloud" in open(os.path.join(WEB, "edition.js"), encoding="utf-8").read() and "javascript" in (r.headers.get("Content-Type") or ""), repr(r))
    check("대소문자를 바꿔도 cloud 판 edition.js 는 나가지 않는다", all("cloud" not in api("GET", p).raw for p in ("/Edition.js", "/EDITION.JS", "/edition.JS")))
    check("firebase-config.js·data-firebase.js 는 404 (파일은 있다)", os.path.isfile(os.path.join(WEB, "firebase-config.js"))
          and os.path.isfile(os.path.join(WEB, "data-firebase.js"))
          and [api("GET", p).status for p in ("/firebase-config.js", "/data-firebase.js", "/Firebase-Config.js", "/DATA-FIREBASE.JS",
                                              "/firebase-config.js?x=1", "/img/../firebase-config.js", "/./data-firebase.js")] == [404] * 7)
    r = api("GET", "/app.js")
    check("js 파일", r.status == 200 and "javascript" in r.headers.get("Content-Type") and r.raw == open(os.path.join(WEB, "app.js"), encoding="utf-8", newline="").read())
    check("주소 뒤 질의는 무시", api("GET", "/app.js?v=3").status == 200)
    check("대소문자가 다른 이름은 404", api("GET", "/APP.JS").status == 404 and api("GET", "/IMG/login.webp").status == 404)
    req = urllib.request.Request(BASE + "/img/login.webp")
    with NO_PROXY.open(req, timeout=10) as resp:
        img, img_type = resp.read(), resp.headers.get("Content-Type")
    check(".webp 는 image/webp", img_type == "image/webp" and img == open(os.path.join(WEB, "img", "login.webp"), "rb").read())
    check("png·css·html 종류", api("GET", "/img/icon.png").headers.get("Content-Type") == "image/png")
    check("허용 목록 밖 확장자·점으로 시작하는 파일·폴더 404", [api("GET", p).status for p in ("/notes.txt", "/.secret.js", "/img", "/img/", "/nothing.js", "/app")] == [404] * 6)
    escapes = ["/..%2fstandalone%2fagent.key", "/%2e%2e/license.json", "/app.js%00.png", "/C:%5CWindows%5Cwin.ini",
               "/%2e%2e/standalone/accounts.json", "/%2e%2e%2fstandalone%2flicense.json", "/..%5cstandalone%5caccounts.json",
               "/img/..%2f..%2fstandalone/accounts.json", "/img/%2e%2e/%2e%2e/standalone/agent.key", "/%252e%252e/standalone/agent.key",
               "/..%252fstandalone%252fagent.key", "/%2Fstandalone%2Fagent.key", "/C:/Windows/win.ini", "/C%3A/Windows/win.ini",
               "/app.js::$DATA", "/app.js:stream", "/app.js.", "/app.js%20", "/app.js%0a", "/app.js/", "/nul.js", "/con.html", "/NUL",
               "/%5C%5C127.0.0.1%5Cc$%5Cwindows%5Cwin.ini", "/standalone/agent.key", "/accounts.json", "/license.json",
               "/../standalone/accounts.json", "/img/../../standalone/license.json", "/....//standalone/agent.key"]
    got = {p: api("GET", p) for p in escapes}
    check("웹 폴더 밖·이상한 이름은 모두 404", all(g.status == 404 for g in got.values()), repr({p: g.status for p, g in got.items() if g.status != 404}))
    raws = [b"/../standalone/agent.key", b"/..\\standalone\\agent.key", b"/..\\..\\standalone\\accounts.json", b"/app.js\x00.png",
            b"/%2e%2e/standalone/agent.key", b"//standalone/agent.key", b"/\\standalone\\license.json", b"/app.js::$DATA", b"/img/..\\app.js",
            b"http://127.0.0.1/../standalone/agent.key"]
    got_raw = {p: raw_get(p) for p in raws}
    check("손대지 않은 주소(..·\\·NUL)로도 밖으로 못 나간다", all(st in (400, 404) for st, _ in got_raw.values()), repr({p: st for p, (st, _) in got_raw.items()}))
    # 두 겹이 따로 서는지: 주소 조각의 글자 검사를 없앤 채로 절대 경로를 달라고 해도 진짜 자리 검사가 막는다
    real_seg, real_dev = local_web.SEG_RE, local_web.DEVICES
    local_web.SEG_RE, local_web.DEVICES = re.compile(r"[^/]*", re.S), set()
    try:
        got2 = [api("GET", "/" + urllib.parse.quote(os.path.realpath(p), safe="")) for p in (ACC, os.path.join(DATA, "license.json"))]
        got2 += [api("GET", "/" + urllib.parse.quote("\\\\?\\" + os.path.realpath(ACC), safe="")), api("GET", "/APP.JS")]
    finally:
        local_web.SEG_RE, local_web.DEVICES = real_seg, real_dev
    check("주소 글자 검사가 없어도 웹 폴더 밖 파일은 나가지 않는다 (진짜 자리 검사)", [g.status for g in got2] == [404] * 4, repr(got2))
    leaked = [n for n, b in [("agent.key", AGENT), ("relay.key", RELAY), ("license", "LICENSE-SIG-SECRET"), ("해시", rec["hash"]), ("소금", rec["salt"])]
              if any(b.encode() in body for body in BODIES)]
    check("어느 응답에도 열쇠·라이선스 서명·해시·소금이 없다", not leaked, repr(leaked))
    r = api("GET", "/nothing.js")
    check("404 에도 보안 머리글", r.status == 404 and r.headers.get("Content-Security-Policy") == CSP and r.headers.get("X-Content-Type-Options") == "nosniff")
    check("웹 파일 자리에 POST·PUT·DELETE 는 받지 않는다", [api(m, "/index.html", {"a": 1}).status for m in ("POST", "PUT", "DELETE")] == [401] * 3)
    check("웹 파일 폴더 (소스에서는 firebase/web)", os.path.isfile(os.path.join(local_web.web_dir(), "index.html"))
          and os.path.normcase(local_web.web_dir()) == os.path.normcase(os.path.join(ROOT, "firebase", "web")), local_web.web_dir())

    # ------------------------------------------------------------------------------------------
    print("Host · Origin · 본문 크기")
    check("다른 이름으로 이 PC 를 가리킨 요청 403 (웹 파일·/api)", api("GET", "/", headers={"Host": "evil.example"}).status == 403
          and api("GET", "/api/session", token=BOSS, headers={"Host": f"evil.example:{PORT}"}).status == 403
          and api("POST", "/api/login", {"id": "boss", "password": BOSS_PW}, headers={"Host": "127.0.0.1:1"}).status == 403)
    check("localhost 이름은 통과", api("GET", "/", headers={"Host": f"localhost:{PORT}"}).status == 200)
    r = login("boss", BOSS_PW, headers={"Origin": "http://evil.example"})
    check("다른 사이트(Origin)에서 온 POST /api/login 403", r.status == 403 and "token" not in r.raw, repr(r))
    got = [login("boss", BOSS_PW, headers={"Origin": o}).status for o in (
        f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT + 1}", f"https://127.0.0.1:{PORT}", "null",
        f"http://127.0.0.1:{PORT}.evil.example", "http://127.0.0.1")]
    check("Origin 은 이 서버 주소 둘만", got == [200, 200, 403, 403, 403, 403, 403], repr(got))
    check("Origin 없는 요청(주소창)은 통과", login("boss", BOSS_PW).status == 200 and api("GET", "/api/session", token=BOSS).status == 200)
    check("다른 사이트의 GET 도 403 (Origin·Sec-Fetch-Site)", api("GET", "/api/session", token=BOSS, headers={"Origin": "http://evil.example"}).status == 403
          and api("GET", "/api/session", token=BOSS, headers={"Sec-Fetch-Site": "cross-site"}).status == 403
          and api("GET", "/api/session", token=BOSS, headers={"Sec-Fetch-Site": "same-site"}).status == 403
          and api("GET", "/api/session", token=BOSS, headers={"Sec-Fetch-Site": "same-origin"}).status == 200
          and api("GET", "/api/session", token=BOSS, headers={"Sec-Fetch-Site": "none"}).status == 200)
    big = json.dumps({"id": "boss", "password": BOSS_PW, "pad": "x" * (64 * 1024)}).encode("utf-8")
    check("/api 본문은 64KB 까지 (413)", api("POST", "/api/login", raw=big).status == 413
          and api("POST", "/api/commands", raw=json.dumps({"type": "launch", "args": {"pad": "x" * (64 * 1024)}}).encode(), token=BOSS).status == 413)
    ok_size = json.dumps({"type": "set_presets", "args": {"pad": "x" * (60 * 1024)}}).encode("utf-8")
    check("64KB 안쪽은 받는다", api("POST", "/api/commands", raw=ok_size, token=BOSS).status == 200)

    # ------------------------------------------------------------------------------------------
    print("기록 파일")
    log_path = os.path.join(DATA, local_server.LOG_NAME)
    text = open(log_path, encoding="utf-8").read() if os.path.isfile(log_path) else ""
    check("로그인 성공·실패·잠금이 아이디와 함께 남는다", "boss" in text and "lock1" in text and "로그인" in text and "잠" in text, text[-300:])
    check("계정 바꿈이 남는다", "temp1" in text and "boss2" in text and "계정" in text, text[-300:])
    check("기록에 비밀번호가 없다", not [p for p in PASSWORDS | {"wrong-pw-0000", "hijack-pw-001"} if p in text])
    check("기록에 세션 토큰·열쇠가 없다", len(TOKENS) > 20 and not [t for t in TOKENS if t in text] and AGENT not in text and RELAY not in text)
    check("없는 아이디로 넣은 글은 기록에 싣지 않는다 (아이디 칸에 비밀번호를 친 경우)", "nobody" not in text and "ghost9" not in text and "이상한" not in text)
    saved = open(os.path.join(DATA, "store.json"), encoding="utf-8").read()
    check("세션 토큰은 저장 파일에도 없다 (메모리에만)", not [t for t in TOKENS if t in saved]
          and not [t for t in TOKENS if t in open(ACC, encoding="utf-8").read()])

    # ------------------------------------------------------------------------------------------
    print("web 없이 만든 서버는 예전 그대로")
    srv2 = local_server.make_server(store, runs, LIC, (AGENT, RELAY), port=0, folder=DATA)
    B2 = f"http://127.0.0.1:{srv2.server_address[1]}"
    threading.Thread(target=srv2.serve_forever, daemon=True).start()
    check("web 이 없으면 / 와 /api 는 서명 없는 요청으로 401", srv2.web is None and api("GET", "/", base=B2).status == 401
          and api("GET", "/api/session", token=BOSS, base=B2).status == 401 and api("POST", "/api/login", {"id": "boss", "password": BOSS_PW}, base=B2).status == 401)
    hs = local_store.sign_headers(AGENT, "agent", "GET", "/nothing", b"")
    check("서명한 모르는 주소는 404", api("GET", "/nothing", headers=hs, base=B2).status == 404)

    # ------------------------------------------------------------------------------------------
    print("서버를 끄면 스트림이 끝난다 · main 이 웹 창구를 단다")
    s5 = Stream(BOSS)
    s5.wait(lambda s: len(s.named("live")) >= 1)
    began = time.time()
    srv.shutdown()
    srv.server_close()
    check("서버가 꺼지면 스트림이 곧 끝난다 (gone 없이 - 화면이 다시 붙는다)", s5.wait(lambda s: s.ended, 6) and time.time() - began < 5
          and "gone" not in [e for e, _ in s5.events], repr(s5.events[-2:]))
    srv = None
    import license_check  # noqa: E402
    import update_sign  # noqa: E402
    pd = os.path.join(TMP, "pd")
    os.makedirs(pd)
    os.environ["RPA_PROGRAMDATA"] = pd
    os.environ["RPA_MACHINE_GUID"] = "p1"
    lic_secret, lic_public = update_sign.keygen()
    saved_pub = license_check.LICENSE_PUBLIC_KEY_HEX
    license_check.LICENSE_PUBLIC_KEY_HEX = lic_public.hex()
    with open(os.path.join(pd, "license.json"), "w", encoding="utf-8") as f:
        json.dump(license_check.sign_body(lic_secret, LIC), f, ensure_ascii=False)
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    main_port = probe.getsockname()[1]
    probe.close()
    os.environ["RPA_LOCAL_PORT"] = str(main_port)
    made, real_make = [], local_server.make_server

    def capture(*a, **k):
        made.append(real_make(*a, **k))
        return made[-1]

    local_server.make_server = capture
    codes = []
    t = threading.Thread(target=lambda: codes.append(local_server.main()), daemon=True)
    try:
        t.start()
        wait_for(lambda: made or codes, 15)
        MB = f"http://127.0.0.1:{main_port}"
        check("main 이 만든 서버에 웹 창구가 달린다", bool(made) and isinstance(made[0].web, local_web.Web), repr(codes))
        r = api("GET", "/", base=MB) if made else Got(0, "", {})
        check("main 서버가 웹 파일을 내준다 (계정 파일은 자료 폴더)", r.status == 200 and "<html" in r.raw.lower()
              and api("GET", "/edition.js", base=MB).raw.strip() == 'export const EDITION = "standalone";'
              and api("POST", "/api/login", {"id": "boss", "password": BOSS_PW}, base=MB).status == 401
              and made[0].web.accounts.path == os.path.join(pd, "standalone", "accounts.json"), repr(r)[:200])
    finally:
        local_server.make_server = real_make
        license_check.LICENSE_PUBLIC_KEY_HEX = saved_pub
        for s in made:
            s.shutdown()
        t.join(8)
    check("main 은 꺼지면 0 으로 끝난다", codes == [0], repr(codes))
finally:
    for k in ("RPA_PROGRAMDATA", "RPA_MACHINE_GUID", "RPA_LOCAL_PORT"):
        os.environ.pop(k, None)
    for s in (srv, srv2):
        try:
            if s is not None:
                s.shutdown()
                s.server_close()
        except Exception:
            pass
    try:
        if runs is not None:
            runs.close()
    except Exception:
        pass
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n실패: {len(fails)}" + (f" ({', '.join(fails)})" if fails else ""))
sys.exit(1 if fails else 0)
