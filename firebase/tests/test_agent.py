"""에이전트 단위 시험. Firebase 없이 돈다.

실행: python tests/test_agent.py   (D:\\AX\\RPA\\firebase 에서)
"""
import base64
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent"))
os.environ.setdefault("RPA_AGENT_QUEUE", os.path.join(tempfile.mkdtemp(), "queue.jsonl"))   # log() 가 실제 기록을 어지럽히지 않게

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
    check("\\" in json.loads(raw).get("windows_user", "") and cfg["windows_user"] == json.loads(raw)["windows_user"],
          "만든 윈도우 계정(도메인\\이름)을 함께 적고 읽는다")
    with open(p, encoding="utf-8") as f:
        broken = json.load(f)
    broken["password_dpapi"] = base64.b64encode(b"not-dpapi").decode()   # 다른 계정에서 만든 것처럼
    json.dump(broken, open(p, "w", encoding="utf-8"))
    try:
        secret.load_config(p)
        check(False, "못 풀면 누가 만들었고 어떻게 하는지 알려준다")
    except OSError as e:
        check(broken["windows_user"] in str(e) and "agent_config.json 을 지우고" in str(e), "못 풀면 누가 만들었고 어떻게 하는지 알려준다")

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
        """payload 가 예외면 (URLError 같은 망 오류) 그대로 던진다"""
        self.replies.append((status, payload if isinstance(payload, Exception) else json.dumps(payload).encode("utf-8")))

    def __call__(self, req, timeout=None):
        body = req.data.decode("utf-8") if req.data else None
        self.calls.append((req.get_method(), req.full_url, body, dict(req.headers)))
        self.last_timeout = timeout
        status, data = self.replies.pop(0)
        if isinstance(data, Exception):
            raise data
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
c.put("apps/rpa/live/c_demo/pc_office", {"host": "PC1"})
method, url, body, _ = http.calls[-1]
check(method == "PUT" and url.startswith("https://db.example.com/apps/rpa/live/c_demo/pc_office.json"), "PUT 주소")
check("auth=T2" in url, "요청에 토큰을 싣는다")
check(json.loads(body) == {"host": "PC1"}, "보낸 몸통")

http.add({"ok": True})
c.patch("apps/rpa/commands/c_demo/pc_office/x", {"state": "running"})
check(http.calls[-1][0] == "PATCH", "PATCH 로 일부만 고친다")

http.add({"error": "Permission denied"}, status=401)
http.add({"id_token": "T3", "refresh_token": "R3", "expires_in": "3600"})
http.add({"ok": True})
c.put("apps/rpa/live/c_demo/pc_office", {"host": "PC1"})
check(c.token() == "T3", "401 이면 토큰을 새로 받고 한 번 더 시도한다")

http.add({"error": "Permission denied"}, status=403)
try:
    c.put("live/other/pc", {"x": 1})
    check(False, "거부는 HttpError 로 올린다")
except fb.HttpError as e:
    check(e.status == 403, "거부는 HttpError 로 올린다")

print("\n2-2절 인증이 죽었을 때 (비밀번호 변경·회수·정지)")
import urllib.error


def fresh_client():
    h = FakeHTTP()
    h.add({"idToken": "T1", "refreshToken": "R1", "expiresIn": "3600"})
    c = fb.Client(CFG, opener=h, clock=lambda: h.now)
    c.token()
    h.now += 3600            # 만료 - 다음 token() 은 갱신부터
    return h, c


h3, c3 = fresh_client()
h3.add({"error": {"code": 400, "message": "TOKEN_EXPIRED"}}, status=400)                  # 갱신 거부 (회수)
h3.add({"error": {"code": 400, "message": "INVALID_LOGIN_CREDENTIALS"}}, status=400)      # 비밀번호 로그인 거부
try:
    c3.token(); check(False, "갱신·로그인이 다 거부되면 AuthError(code)")
except fb.AuthError as e:
    check(e.status == 400 and e.code == "INVALID_LOGIN_CREDENTIALS", "갱신·로그인이 다 거부되면 AuthError(code)")
check("signInWithPassword" in h3.calls[-1][1] and "pw" in h3.calls[-1][2], "갱신이 거부되면 비밀번호로 다시 로그인해 본다")
n = len(h3.calls)
try:
    c3.token(); check(False, "죽은 뒤 token() 은 망에 안 나가고 같은 예외")
except fb.AuthError as e:
    check(e.code == "INVALID_LOGIN_CREDENTIALS" and len(h3.calls) == n, "죽은 뒤 token() 은 망에 안 나가고 같은 예외")
try:
    c3.put("apps/rpa/live/c_demo/pc_office", {"a": 1}); check(False, "_send 는 AuthError 를 그대로 올린다 (HttpError 로 안 감싼다)")
except fb.AuthError:
    check(len(h3.calls) == n, "_send 는 AuthError 를 그대로 올린다 (HttpError 로 안 감싼다)")
check(fb.Client(CFG, opener=h3, clock=lambda: h3.now)._dead is None, "새 Client 는 다시 시도한다")

h4, c4 = fresh_client()
h4.add(urllib.error.URLError("망 끊김"))
try:
    c4.token(); check(False, "갱신이 망 오류면 비밀번호를 보내지 않고 그대로 올린다")
except urllib.error.URLError:
    check(len(h4.calls) == 2 and "pw" not in h4.calls[-1][2], "갱신이 망 오류면 비밀번호를 보내지 않고 그대로 올린다")
h4.add({"error": {"code": 503, "message": "BACKEND_ERROR"}}, status=503)
try:
    c4.token(); check(False, "갱신이 5xx 면 그대로 올리고, 비밀번호는 안 나간다")
except urllib.error.HTTPError as e:
    check(e.code == 503 and len(h4.calls) == 3 and "pw" not in h4.calls[-1][2], "갱신이 5xx 면 그대로 올리고, 비밀번호는 안 나간다")
h4.add({"id_token": "T2", "refresh_token": "R2", "expires_in": "3600"})
check(c4.token() == "T2", "망이 돌아오면 갱신해서 이어간다")

h6, c6 = fresh_client()
h6.replies.append((403, b"<html>portal</html>"))          # 캡티브 포털·프록시 - Identity Toolkit 의 code 가 없다
try:
    c6.token(); check(False, "본문이 JSON 이 아닌 4xx 는 망 사정 - 그대로 올리고 _dead 가 안 된다")
except urllib.error.HTTPError as e:
    check(e.code == 403 and c6._dead is None and "pw" not in h6.calls[-1][2], "본문이 JSON 이 아닌 4xx 는 망 사정 - 그대로 올리고 _dead 가 안 된다")
h6.add({"error": {"code": 429, "message": "RESOURCE_EXHAUSTED"}}, status=429)
try:
    c6.token(); check(False, "429 도 망 사정 - _dead 가 안 된다")
except urllib.error.HTTPError as e:
    check(e.code == 429 and c6._dead is None, "429 도 망 사정 - _dead 가 안 된다")
h6.add({"id_token": "T2", "refresh_token": "R2", "expires_in": "3600"})
check(c6.token() == "T2" and len(h6.calls) == 4, "망이 돌아오면 다시 나가서 갱신한다")

h5, c5 = fresh_client()
h5.add({"error": {"code": 400, "message": "TOKEN_EXPIRED"}}, status=400)
h5.add({"error": {"code": 400, "message": "TOO_MANY_ATTEMPTS_TRY_LATER : Access to this account has been temporarily disabled"}}, status=400)
try:
    c5.token(); check(False, "'CODE : 설명' 꼴이면 CODE 만 남긴다")
except fb.AuthError as e:
    check(e.code == "TOO_MANY_ATTEMPTS_TRY_LATER" and "Access" not in str(e), "'CODE : 설명' 꼴이면 CODE 만 남긴다")

check(fb.parse_sse(["event: put", 'data: {"path":"/","data":{"a":1}}', ""]) ==
      [("put", {"path": "/", "data": {"a": 1}})], "SSE 한 덩이를 읽는다")
check(fb.parse_sse(["event: keep-alive", "data: null", ""]) == [("keep-alive", None)], "keep-alive 를 읽는다")

print("\n3절 상태 올리기와 오프라인 큐")
import agent as ag

check(ag.clean_for_rtdb({"a.b": 1, "ok": 2}) == {"ok": 2}, "점이 든 키를 버린다")
check(ag.clean_for_rtdb({"a": {"b$": 1, "c": 2}}) == {"a": {"c": 2}}, "깊은 곳의 키도 버린다")
check(ag.clean_for_rtdb({"a": []}) == {"a": None}, "빈 목록은 None (RTDB 는 빈 값을 못 담는다)")
check(ag.clean_for_rtdb({"a": [1, 2]}) == {"a": [1, 2]}, "값이 있는 목록은 그대로")

snap = {"programs": {"routine": {"log": [f"줄{i}" for i in range(200)], "state": "running"},
                     "prepare": None}}
out = ag.trim_logs(snap, lines=80)
check(len(out["programs"]["routine"]["log"]) == 80, "로그는 80줄만 남는다")
check(out["programs"]["routine"]["log"][0] == "줄120", "뒤에서 80줄")
check(out["programs"]["prepare"] is None, "없는 프로그램은 그대로 None")
check(len(snap["programs"]["routine"]["log"]) == 200, "원본은 건드리지 않는다")

import datetime as _dt
rows = [{"started_at": "2026-09-14T13:55:00", "state": "success"},
        {"started_at": "2026-09-14T13:39:00", "state": "stopped"},
        {"started_at": "2026-09-13T09:06:00", "state": "crashed"},
        {"started_at": "2026-08-20T09:06:00", "state": "success"},    # 20일 밖
        {"started_at": "", "state": "success"}]
rs = ag.recent_summary(rows, _dt.date(2026, 9, 14))
check(len(rs) == 20 and rs[0]["date"] == "2026-08-26" and rs[-1]["date"] == "2026-09-14", "최근 20일, 오래된 날부터")
check(rs[-1] == {"date": "2026-09-14", "success": 1, "failed": 1, "crashed": 0}, "하루에 성공·실패·비정상을 센다")
check(rs[-2]["crashed"] == 1 and rs[-2]["failed"] == 0 and sum(d["success"] for d in rs) == 1, "중단은 실패, 비정상 종료는 따로, 20일 밖은 뺀다")

ff = fb.fs_fields({"a": "x", "b": 3, "c": True, "d": None, "e": 1.5, "f": {"k": 2, "m": {"n": "o"}}, "g": [1]})
check(ff["a"] == {"stringValue": "x"} and ff["b"] == {"integerValue": "3"} and ff["c"] == {"booleanValue": True}
      and ff["d"] == {"nullValue": None} and ff["e"] == {"doubleValue": 1.5}, "Firestore 형 붙이기")
check(ff["f"] == {"mapValue": {"fields": {"k": {"integerValue": "2"}, "m": {"mapValue": {"fields": {"n": {"stringValue": "o"}}}}}}},
      "dict 는 Firestore map (서버가 칸마다 더할 수 있게 - 토큰)")
check(json.loads(ff["g"]["stringValue"]) == [1], "목록은 JSON 문자열")

rec = {"run_id": "r1", "program": "routine", "program_label": "루틴 RPA", "state": "stopped", "reason": "주소",
       "started_at": "2026-09-14T13:39:00", "finished_at": "2026-09-14T13:39:02", "duration_sec": 2,
       "steps": [{"key": "a"}], "log_tail": [f"줄{i}" for i in range(100)]}
doc = ag.run_doc(rec, "c_demo", "pc_office")
check(doc["cid"] == "c_demo" and doc["pcId"] == "pc_office" and doc["date"] == "2026-09-14" and doc["duration_sec"] == 2, "문서 조회 필드")
pl = json.loads(doc["payload"])
check(pl["steps"] == [{"key": "a"}] and len(pl["log"]) == 80 and "log_tail" not in pl, "payload 에 단계·로그 80줄")


class FsClient:
    def __init__(self):
        self.ok = True; self.puts = []; self.docs = []

    def put(self, path, value):
        self.puts.append((path, value))

    patch = put

    def fs_create(self, path, fields, doc_id):
        if not self.ok:
            raise fb.HttpError(503, "끊김")
        self.docs.append((path, doc_id, fields))
        return True


with tempfile.TemporaryDirectory() as d:
    fcl = FsClient()
    upl = ag.Uploader(fcl, "c_demo", "pc_office", os.path.join(d, "q.jsonl"))
    upl.push_run(doc)
    check(fcl.docs[-1][0] == "runs/c_demo/items" and fcl.docs[-1][1] == "r1", "runs/회사/items 에 run_id 로")
    check(fcl.docs[-1][2]["state"] == {"stringValue": "stopped"}, "형 붙여서 보낸다")
    fcl.ok = False
    upl.push_run(dict(doc, run_id="r2"))
    check(upl.pending() == 1, "끊기면 이력도 큐에")
    fcl.ok = True
    upl.flush()
    check(upl.pending() == 0 and fcl.docs[-1][1] == "r2", "다시 보낸다")

    hist = os.path.join(d, "history.jsonl")
    pos = os.path.join(d, "history_pos.txt")
    with open(hist, "w", encoding="utf-8") as f:
        f.write(json.dumps(dict(rec, run_id="h1")) + "\n" + json.dumps(dict(rec, run_id="h2")) + "\n" + '{"run_id": "h3", "st')
    n = ag.upload_new_history(hist, upl, {"cid": "c_demo", "pc_id": "pc_office"}, pos)
    check(n == 2 and [x[1] for x in fcl.docs[-2:]] == ["h1", "h2"], "새 줄만 올린다, 쓰다 만 줄은 남긴다")
    with open(hist, "a", encoding="utf-8") as f:
        f.write('ate": "success", "started_at": "2026-09-15T09:00:00"}\n')
    n = ag.upload_new_history(hist, upl, {"cid": "c_demo", "pc_id": "pc_office"}, pos)
    check(n == 1 and fcl.docs[-1][1] == "h3", "이어서 쓴 줄을 다음에 올린다")
    check(ag.upload_new_history(hist, upl, {"cid": "c_demo", "pc_id": "pc_office"}, pos) == 0, "바뀐 게 없으면 안 올린다")

print("토큰: 실행 기록 한 건이 쓴 것·쓴 토큰 (2026-10-07 바꿈 - '완료' 만 쓰고 대상 없음·실패·건너뜀·중단은 안 쓴다)")
mods = [{"key": "login", "state": "done"}, {"key": "sales", "state": "done"}, {"key": "hold", "state": "no_target"},
        {"key": "logistics", "state": "failed"}, {"key": "output", "state": "skipped"}]
check(ag.usage({"program": "routine", "modules": mods}) == {"login": 1, "sales": 1},
      "루틴: 완료인 모듈만 (대상 없음·실패·건너뜀은 안 씀 - 반복이 빈 회차로 토큰을 먹지 않게)")
check(ag.usage({"program": "routine", "modules": [{"key": "sales", "state": "stopped"}, {"key": "hold", "state": "pending"},
                                                  {"key": "logistics", "state": "off"}]}) == {}, "중단·안 돈 모듈·꺼진 모듈은 안 씀")
check(ag.usage({"program": "prepare", "steps": [
    {"key": "PRESET1:replay", "state": "done"}, {"key": "PRESET2:replay", "state": "failed"},
    {"key": "SITE1:login", "state": "done"}, {"key": "SITE1:download", "state": "done"},
    {"key": "SITE2:login", "state": "done"}, {"key": "SITE2:download", "state": "skipped"}]}) == {"sites": 2},
      "프리페어: 단계가 모두 완료인 사이트(프리셋) 하나가 1회")
check(ag.usage({"program": "observer", "steps": [{"key": "PRESET1:replay", "state": "done"}]}) == {}, "옵저버 미리보기는 안 센다")
check(ag.usage({"program": "routine", "state": "crashed"}) == {}, "시작하지 못한 실행은 0")
check(ag.run_cost({"login": 1, "sales": 1, "hold": 1}, ag.PRICES) == 2, "처음 값표: 모두 1, 로그인 0")
check(ag.run_cost({"sales": 2, "invoice_send": 1}, {"default": 1, "login": 0, "sales": 3}) == 7,
      "값표의 값 × 횟수, 값표에 없는 새 모듈은 default")
doc2 = ag.run_doc(dict(rec, modules=mods), "c_demo", "pc_office")
check(doc2["used"] == {"login": 1, "sales": 1} and doc2["cost"] == 1, "기록 문서에 쓴 것·쓴 토큰 (값표를 안 주면 처음 값표)")
check(ag.run_doc(dict(rec, modules=mods), "c_demo", "pc_office", {"default": 5, "login": 0})["cost"] == 5, "준 값표로 센다")


class PriceClient:
    def __init__(self, got):
        self.got, self.calls = got, 0

    def fs_get(self, path):
        self.calls += 1
        if isinstance(self.got, Exception):
            raise self.got
        return {"meta/prices": self.got}.get(path)


pc = PriceClient({"default": 2, "sales": 3, "hold": -1, "output": "9", "flag": True})
prices = ag.Prices(pc)
check(prices.get() == {"default": 2, "login": 0, "sales": 3}, "서버 값표(meta/prices)를 처음 값표 위에 - 0 이상 정수만, 이상한 값은 버림")
prices.get()
check(pc.calls == 1, "10분 안에는 다시 읽지 않는다")
check(ag.Prices(PriceClient(None)).get() == ag.PRICES, "서버에 값표가 없으면 처음 값표")
check(ag.Prices(PriceClient(fb.HttpError(503, "끊김"))).get() == ag.PRICES, "못 읽으면 처음 값표 (기록 올리기를 막지 않는다)")


class PathClient:
    """경로별 값 - 값이 예외면 그 경로만 실패 (업체 배율 prices/{cid} 와 기본 meta/prices 를 따로)."""
    def __init__(self, docs):
        self.docs, self.calls = docs, []

    def fs_get(self, path):
        self.calls.append(path)
        got = self.docs.get(path)
        if isinstance(got, Exception):
            raise got
        return got


cl = PathClient({"meta/prices": {"default": 2, "sales": 3}, "prices/c_demo": {"sales": 5, "wellife_sap": 4, "hold": -1}})
check(ag.Prices(cl, "c_demo").get() == {"default": 2, "login": 0, "sales": 5, "wellife_sap": 4},
      "업체 배율(prices/{cid})이 기본값 위에 - 업체 > 기본 > 처음 값표, 이상한 값은 버림 (사용자 2026-10-08)")
check(sorted(cl.calls) == ["meta/prices", "prices/c_demo"], f"기본값과 그 업체 배율만 읽는다 ({cl.calls})")
cl = PathClient({"meta/prices": {"default": 2, "sales": 3}, "prices/c_demo": fb.HttpError(403, "규칙")})
check(ag.Prices(cl, "c_demo").get() == {"default": 2, "login": 0, "sales": 3}, "업체 배율을 못 읽어도 기본값은 쓴다 (규칙 배포 전 등)")
cl = PathClient({"meta/prices": {"default": 2}, "prices/c_demo": {"sales": 5}})
pr = ag.Prices(cl, "c_demo", every=0)
pr.get()
cl.docs = {"meta/prices": fb.HttpError(503, "끊김"), "prices/c_demo": fb.HttpError(503, "끊김")}
check(pr.get() == {"default": 2, "login": 0, "sales": 5}, "둘 다 못 읽으면 지난 값 그대로")
cl.docs = {"meta/prices": {"default": 2}, "prices/c_demo": None}
check(pr.get() == {"default": 2, "login": 0}, "업체 배율을 지우면(문서 없음) 기본값으로 돌아간다")

with tempfile.TemporaryDirectory() as d:
    fcl = FsClient()
    upl = ag.Uploader(fcl, "c_demo", "pc_office", os.path.join(d, "q.jsonl"))
    hist, pos, asked = os.path.join(d, "history.jsonl"), os.path.join(d, "history_pos.txt"), []

    def table():
        asked.append(1)
        return {"default": 1, "login": 0}
    open(hist, "w", encoding="utf-8").close()
    ag.upload_new_history(hist, upl, {"cid": "c_demo", "pc_id": "pc_office"}, pos, prices=table)
    check(not asked, "올릴 기록이 없으면 값표를 안 읽는다")
    with open(hist, "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(rec, run_id="t1", modules=mods), ensure_ascii=False) + "\n")
    ag.upload_new_history(hist, upl, {"cid": "c_demo", "pc_id": "pc_office"}, pos, prices=table)
    sent = fcl.docs[-1][2]
    check(len(asked) == 1 and sent["cost"] == {"integerValue": "1"} and set(sent["used"]["mapValue"]["fields"]) == {"login", "sales"},
          "올릴 때 값표를 읽어 쓴 토큰(정수)·쓴 것(map)을 싣는다")


class WalletClient:
    def __init__(self, wallet, spent):
        self.wallet, self.spent, self.asked = wallet, spent, []

    def fs_get(self, path):
        return self.wallet if path == "wallet/c_demo" else None

    def fs_sum(self, parent, collection, field, since=None):
        self.asked.append((parent, collection, field, since))
        return self.spent


check(ag.balance(WalletClient(None, 3), "c_demo") is None, "통장이 없는 업체는 None - 토큰 제도 밖 (세기만 한다)")
wc = WalletClient({"granted": 10}, 3)
check(ag.balance(wc, "c_demo") == 7 and wc.asked == [("runs/c_demo", "items", "cost", None)],
      "남은 토큰 = 넣은 합계 - 실행 기록들의 쓴 토큰 합 (Firestore 가 서버에서 더한다)")
wc = WalletClient({"granted": 10, "since": "2026-10-06T12:00:00"}, 3)
check(ag.balance(wc, "c_demo") == 7 and wc.asked == [("runs/c_demo", "items", "cost", "2026-10-06T12:00:00")],
      "통장 시작 시각(since)이 있으면 그 뒤에 시작한 기록만 뺀다 (3부 - 통장 전에 쓴 것은 안 뺀다)")
check(ag.balance(WalletClient({"granted": 1}, 4), "c_demo") == -3, "마이너스도 그대로 (1 이상이면 시작해 끝까지 - 사용자 결정)")

print("토큰 2부: 막기 - 0 이하면 실행 거절, 통장 없으면 통과, 확인 못 하면 마지막으로 확인한 값 (2026-10-06 사용자 결정)")


class TokenClient(WalletClient):
    def __init__(self, granted, spent):
        super().__init__(None if granted is None else {"granted": granted}, spent)
        self.fail, self.reads = False, 0

    def fs_get(self, path):
        self.reads += 1
        if self.fail:
            raise fb.HttpError(503, "끊김")
        return {"default": 1, "login": 0} if path == "meta/prices" else super().fs_get(path)

    def fs_sum(self, parent, collection, field, since=None):
        if self.fail:
            raise fb.HttpError(503, "끊김")
        return super().fs_sum(parent, collection, field, since)


def plan():
    return ["login", "sales", "hold"], 2       # 켠 루틴 모듈 키, 켠 사이트·프리셋 수


def refused(tk, target="routine"):
    try:
        tk.gate(target)
        return None
    except RuntimeError as e:
        return str(e)


tc = TokenClient(None, 0)
tk = ag.Tokens(tc, "c_demo", ag.Prices(tc), plan)
check(refused(tk) is None and tk.view() is None, "통장이 없는 업체: 막지 않고 현황에도 안 올린다 (화면은 줄을 숨긴다)")
tc = TokenClient(5, 2)
tk = ag.Tokens(tc, "c_demo", ag.Prices(tc), plan)
check(refused(tk) is None and tk.view() == {"balance": 3, "cost": {"routine": 2, "prepare": 2, "all": 4}},
      "남은 3: 실행하고, 현황에 남은 토큰·실행 1번에 드는 토큰 (켠 모듈 × 값표, 로그인 0, 사이트 × 값표, 전체 = 둘의 합)")
tc.spent = 5
check(refused(tk) == "토큰이 없습니다 (남은 0개). 충전한 뒤 실행하세요", "남은 0: 실행 직전에 다시 확인해 거절 (사람에게 보일 글)")
tc.spent = 7
check(refused(tk, "all") == "토큰이 없습니다 (남은 -2개). 충전한 뒤 실행하세요", "마이너스도 거절")
tc.spent, tc.fail = 2, True
check(refused(tk) == "토큰이 없습니다 (남은 -2개). 충전한 뒤 실행하세요" and tk.view()["balance"] == -2,
      "확인을 못 하면 마지막으로 확인한 값으로 판단 (그 값이 0 이하면 막는다)")
tc.fail = False
reads = tc.reads
tk.refresh()
check(tc.reads == reads, "10분 안에는 다시 확인하지 않는다 (실행 직전·기록을 올린 뒤에는 force)")
tk.refresh(force=True)
check(tk.view()["balance"] == 3, "force 면 바로 다시 확인")
tc2 = TokenClient(5, 0)
tc2.fail = True
tk2 = ag.Tokens(tc2, "c_demo", ag.Prices(tc2), plan)
check(refused(tk2) is None and tk2.view() is None, "한 번도 확인하지 못했으면 막지 않는다 (인터넷 사정으로 업무가 멈추지 않게)")
check(ag.Tokens(TokenClient(9, 0), "c_demo", ag.Prices(TokenClient(9, 0)), lambda: (["login"], 0)).costs()
      == {"routine": 0, "prepare": 0, "all": 0}, "켠 것이 로그인뿐이면 0")


class FlakyClient:
    def __init__(self):
        self.ok = True
        self.puts = []

    def put(self, path, value):
        if not self.ok:
            raise fb.HttpError(503, "끊김")
        self.puts.append((path, value))

    patch = put   # 현황은 PATCH 로 간다 (heartbeat 를 지우지 않으려고). 기록만 하면 된다

    def fs_create(self, path, fields, doc_id):
        self.put(path, doc_id)


with tempfile.TemporaryDirectory() as d:
    q = os.path.join(d, "queue.jsonl")
    cl = FlakyClient()
    up = ag.Uploader(cl, "c_demo", "pc_office", q)

    up.push_live({"host": "PC1"})
    check(cl.puts[-1][0] == "apps/rpa/live/c_demo/pc_office", "현황은 live/회사/PC 로 간다")

    cl.ok = False
    up.push_live({"host": "PC2"})
    check(up.push_heartbeat({"at": 1}) is False and up.pending() == 1, "끊기면 현황은 큐에 쌓고 heartbeat 는 버린다")
    up.push_run(dict(doc, run_id="r9"))
    check(up.pending() == 2, "이력도 큐에")
    check(os.path.exists(q), "큐는 파일로 남는다")

    cl.ok = True
    up.flush()
    check(up.pending() == 0, "연결되면 큐를 비운다")
    check([p for p, _ in cl.puts][-2:] == ["apps/rpa/live/c_demo/pc_office", "runs/c_demo/items"],
          "쌓인 순서대로 보낸다")

    cl.ok = False
    up.push_live({"host": "PC3"})
    up2 = ag.Uploader(cl, "c_demo", "pc_office", q)
    check(up2.pending() == 1, "에이전트를 다시 켜도 큐가 남아 있다")

    cl2 = FlakyClient()
    cl2.ok = True
    up3 = ag.Uploader(cl2, "c_demo", "pc_office", q)
    up3.flush()
    check(up3.pending() == 0 and len(cl2.puts) == 1, "다시 켠 뒤 밀린 것을 보낸다")


class DenyClient:
    """옛 경로(live/…)는 규칙이 403 으로 거부한다. 2026-09-21 실기에서 49건이 큐 머리를 영원히 막았다."""
    def __init__(self):
        self.puts = []

    def put(self, path, value):
        if not path.startswith("apps/"):
            raise fb.HttpError(401, "Permission denied")   # RTDB 는 규칙 거부를 401 로 준다 (실기에서 확인)
        self.puts.append((path, value))

    patch = put


with tempfile.TemporaryDirectory() as d:
    q = os.path.join(d, "queue.jsonl")
    with open(q, "w", encoding="utf-8") as f:
        f.write(json.dumps({"path": "live/c_demo/pc_office/heartbeat", "value": {"at": 1}, "method": "put"}) + "\n")
        f.write(json.dumps({"path": "apps/rpa/live/c_demo/pc_office/heartbeat", "value": {"at": 2}, "method": "put"}) + "\n")
    dc = DenyClient()
    up4 = ag.Uploader(dc, "c_demo", "pc_office", q)
    check(up4.flush() and up4.pending() == 0, "거부된 항목은 버리고 뒤 항목을 보낸다")
    check(dc.puts == [("apps/rpa/live/c_demo/pc_office/heartbeat", {"at": 2})], "거부된 것은 다시 보내지 않는다")
    check(not os.path.exists(q), "큐 파일도 비운다")
    up4._send("live/x", {"a": 1})
    check(up4.pending() == 0, "거부된 것은 애초에 큐에 넣지 않는다")


class DeadClient:
    """인증이 죽은 클라이언트 - token() 이 매번 같은 AuthError 를 올린다"""
    def put(self, path, value):
        raise fb.AuthError(400, "USER_DISABLED")

    patch = put


with tempfile.TemporaryDirectory() as d:
    up5 = ag.Uploader(DeadClient(), "c_demo", "pc_office", os.path.join(d, "q.jsonl"))
    try:
        up5.push_live({"a": 1}); check(False, "인증이 죽으면 큐에 두지 않고 밖으로 올린다 (에이전트가 멈추고 다시 묻게)")
    except fb.AuthError:
        check(up5.pending() == 0, "인증이 죽으면 큐에 두지 않고 밖으로 올린다 (에이전트가 멈추고 다시 묻게)")

print("\n4절 명령 처리")

NOW = 2000.0
ok_cmd = {"type": "launch", "by": "u1", "created_at": 1900, "expires_at": 2500, "state": "queued"}

check(ag.decide(ok_cmd, NOW)[0] == "run", "아직 안 지난 명령은 실행한다")
check(ag.decide(dict(ok_cmd, expires_at=1999), NOW)[0] == "expired", "만료된 명령은 실행하지 않는다")
check(ag.decide(dict(ok_cmd, state="done"), NOW)[0] == "bad", "queued 가 아니면 건너뛴다")
check(ag.decide(dict(ok_cmd, type="rm_rf"), NOW)[0] == "bad", "모르는 종류는 건너뛴다")
check(ag.decide({}, NOW)[0] == "bad", "빈 명령은 건너뛴다")
check(ag.decide(dict(ok_cmd, type="resume_repeat"), NOW)[0] == "run", "resume_repeat (반복 다시 시작) 은 아는 종류")


class RecClient:
    def __init__(self):
        self.patches = []

    def patch(self, path, value):
        self.patches.append((path, value))


def make_cmds(actions):
    cl = RecClient()
    return cl, ag.Commands(cl, "c_demo", "pc_office", actions)


cl, cmds = make_cmds({"launch": lambda args: "띄웠습니다"})
cmds.handle("k1", dict(ok_cmd), NOW)
paths = [p for p, _ in cl.patches]
check(paths == ["apps/rpa/commands/c_demo/pc_office/k1"] * 2, "명령 자리에만 쓴다")
check(cl.patches[0][1]["state"] == "running", "먼저 running 으로 바꾼다")
check(cl.patches[1][1]["state"] == "done" and cl.patches[1][1]["result"] == "띄웠습니다", "끝나면 done")
check("started_at" in cl.patches[0][1] and "ended_at" in cl.patches[1][1], "시각을 남긴다")


def boom(args):
    raise RuntimeError("루틴 RPA 가 이미 돌고 있습니다")


cl, cmds = make_cmds({"launch": boom})
cmds.handle("k2", dict(ok_cmd), NOW)
check(cl.patches[-1][1]["state"] == "failed", "동작이 실패하면 failed")
check("이미 돌고" in cl.patches[-1][1]["result"], "실패 사유를 남긴다")

cl, cmds = make_cmds({})
cmds.handle("k3", dict(ok_cmd, expires_at=1999), NOW)
check(cl.patches[-1][1]["state"] == "expired", "만료는 expired 로 닫는다")
check(len(cl.patches) == 1, "만료는 running 을 거치지 않는다")

cl, cmds = make_cmds({})
cmds.handle("k4", dict(ok_cmd, state="running"), NOW)
check(cl.patches == [], "이미 running 인 명령은 건드리지 않는다")

cl, cmds = make_cmds({"set_modules": lambda args: f"모듈 {sorted(args)} 적용"})
cmds.handle("k5", dict(ok_cmd, type="set_modules", args={"Login": True, "Sales": False}), NOW)
check(cl.patches[-1][1]["state"] == "done" and "Login" in cl.patches[-1][1]["result"], "set_modules 에 args 를 넘긴다")

cl, cmds = make_cmds({"launch": lambda args: "ok"})
cmds.handle("k6", dict(ok_cmd, type="stop_erpia"), NOW)
check(cl.patches[-1][1]["state"] == "failed" and "할 수 없" in cl.patches[-1][1]["result"],
      "할 줄 모르는 종류는 failed 로 닫는다 (명령이 영원히 남지 않게)")


class DenyRunning(RecClient):
    """규칙이 queued→running 을 거부 (다른 PC 가 먼저 잡았거나 끊김)"""
    def patch(self, path, value):
        if value.get("state") == "running":
            raise fb.HttpError(401, "Permission denied")
        super().patch(path, value)


ran = []
cmds = ag.Commands(DenyRunning(), "c_demo", "pc_office", {"launch": lambda args: ran.append(1)})
check(cmds.handle("k7", dict(ok_cmd), NOW) == "deferred" and ran == [], "running 표시를 못 하면 실행하지 않고 deferred")

print("\n5절 실제 동작 - 실행 모듈 (가짜 자격증명 파일)")
with tempfile.TemporaryDirectory() as d:
    cred = os.path.join(d, "ERPIA_AI.txt")
    with open(cred, "w", encoding="utf-8") as f:
        json.dump([{"LogIn": [{"AdminCode": "x"}, {"ID": "a"}, {"PW": "비밀-시험"}]},
                   {"Routine": [{"Login": "Y"}, {"Sales": "Y"}]}], f, ensure_ascii=False)
    os.environ["RPA_CRED_FILE"] = cred
    os.environ["RPA_DASHBOARD_DRY_RUN"] = "1"
    os.environ["RPA_STATUS_DIR"] = os.path.join(d, "status")
    try:
        acts = ag.real_actions()
        msg = acts["set_modules"]({"Login": False, "Sales": False, "Hold": True})
        import rpa_status as st
        import rpa_dashboard as dash
        sel = st.read_routine_modules()[0]
        check(sel["Login"] is True and sel["Sales"] is False and sel["Hold"] is True, f"로그인은 꺼 달라고 해도 켜진 채 저장 ({sel})")
        check("Login" in msg, "결과 문장에 로그인 포함")
        # 처음 쓰면 옛 파일을 합쳐 RPA_UserConfig.json 을 만든다 (RPA_CRED_FILE 옆 = 임시 폴더)
        new = os.path.join(d, "RPA_UserConfig.json")
        raw = open(new, encoding="utf-8").read()
        check(os.path.isfile(cred + ".old") and not os.path.exists(cred), "옛 자격증명 파일은 .old 로")
        check("비밀-시험" not in raw and st.unseal(json.loads(raw)["LogIn"]["PW"]) == "비밀-시험", "자격증명은 잠긴 채 그대로 남는다")
        acts["set_modules"]({"Sales": True, "Hold": True, "Logistics": False, "Output": True})
        sel = st.read_routine_modules()[0]
        check(sel["Output"] is False, f"물류관리가 꺼지면 운송장 출력도 꺼진다 ({sel})")
        acts["set_modules"]({"Sales": True, "Hold": True, "Logistics": False})   # Output 을 안 보내면 Y 로 쓰이던 자리
        check(st.read_routine_modules()[0]["Output"] is False, "값을 안 보내도 물류관리가 꺼져 있으면 출력은 꺼짐")
        acts["set_modules"]({"Sales": True, "Hold": True, "Logistics": True, "Output": True})
        check(st.read_routine_modules()[0]["Output"] is True, "물류관리가 켜져 있으면 출력을 켤 수 있다")
        acts["set_modules"]({"Sales": True, "Hold": True, "Logistics": True, "Output": False})
        check(st.read_routine_modules()[0]["Output"] is False, "물류관리가 켜져 있어도 출력만 끌 수 있다")
        # 업체 정책 (총괄이 정한 '이 업체는 안 씀'). 화면을 우회한 명령도 여기서 막힌다
        strict = ag.real_actions(lambda: {"Hold": False})
        strict["set_modules"]({"Sales": True, "Hold": True, "Logistics": True, "Output": True})
        sel = st.read_routine_modules()[0]
        check(sel["Hold"] is False and sel["Sales"] is True, f"업체가 안 쓰는 모듈은 켜 달라고 해도 꺼진다 ({sel})")
        check(ag.real_actions(lambda: {"Nope": False})["set_modules"]({"Sales": True}) and st.read_routine_modules()[0]["Sales"] is True,
              "정책에 모르는 키가 있어도 넘어간다")
        try:
            acts["set_modules"]({"Nope": True}); check(False, "모르는 모듈만 있으면 거부")
        except RuntimeError as e:
            check("아는 모듈" in str(e), "모르는 모듈만 있으면 거부")
        dash.set_policy(2, ["Logistics", "Output"], wellife=True)
        msg = acts["set_modules"]({"Login": False, "Sales": True, "Hold": True, "Sap": True, "Wms": False})
        check(st.read_wellife_modules()[0] == {"Login": True, "Sales": True, "Hold": True, "Sap": True, "Wms": False} and "켬" in msg,
              f"웰라이프 업체: set_modules 는 Wellife 섹션에 쓴다 ({msg})")
        try:
            acts["set_modules"]({"Logistics": True}); check(False, "웰라이프 업체에 물류관리 거절")
        except RuntimeError as e:
            check("웰라이프 업체는 쓰지 않음" in str(e) and "물류관리" in str(e), f"웰라이프 업체: 물류관리·운송장은 거절 ({e})")
        try:
            acts["set_modules"]({"Output": True}); check(False, "웰라이프 업체에 운송장 거절")
        except RuntimeError as e:
            check(str(e) == "운송장 출력 / 엑셀 생성: 웰라이프 업체는 쓰지 않음", f"거절 글은 한국어 이름 ({e})")
        ag.real_actions(lambda: {"Hold": False})["set_modules"]({"Hold": True, "Sales": True})
        check(st.read_wellife_modules()[0]["Hold"] is False and st.read_wellife_modules()[0]["Sales"] is True, "웰라이프 업체도 업체 정책(안 쓰는 모듈)을 따른다")
        check(acts["set_schedule"]({"enabled": False, "days": [0], "slots": [{"at": "09:00", "run": ["Sales"]}]}) == "자동 실행을 껐습니다",
          "웰라이프 업체: 끄는 요청은 고르기 줄이 있어도 된다")
        for bad in ({"enabled": True, "days": [0], "slots": [{"at": "09:00", "run": ["Sales"]}]},
                    {"enabled": True, "days": [0], "slots": [{"at": "09:00", "until": "10:00", "rest_min": 5}]}):
            try:
                acts["set_schedule"](bad); check(False, f"웰라이프 업체 고르기·반복 줄 거절 {bad}")
            except RuntimeError as e:
                check("'전체' 시각만" in str(e), f"웰라이프 업체: 고르기·반복 줄 거절 ({e})")
        check("자동 실행" in acts["set_schedule"]({"enabled": True, "days": [0], "slots": [{"at": "09:00", "run": None}]}), "웰라이프 업체: '전체' 줄은 된다")
        dash.set_policy(2, [], wellife=False)
        check(acts["set_modules"]({"Sales": True, "Hold": True, "Logistics": True, "Output": True}) and st.read_routine_modules()[0]["Logistics"] is True,
              "보통 업체는 그대로 Routine 섹션")
    finally:
        os.environ.pop("RPA_CRED_FILE", None)
        os.environ.pop("RPA_STATUS_DIR", None)

print("\n5-2절 업체 모듈 정책 읽기")


class PolicyClient:
    def __init__(self, value):
        self.value, self.asked = value, []

    def get(self, path):
        self.asked.append(path)
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


pc = PolicyClient({"Hold": False, "Output": True})
check(ag.company_modules(pc, "c_x") == {"Hold": False}, "false 인 것만 정책으로 본다")
check(pc.asked == ["meta/companies/c_x/apps/rpa/modules"], f"회사 메타에서 읽는다 ({pc.asked})")
check(ag.company_modules(PolicyClient(None), "c_x") == {}, "정책이 없으면 빈 값")
check(ag.company_modules(PolicyClient(fb.HttpError(401, "denied")), "c_x") == {}, "못 읽어도 실행을 막지 않는다")

print("\n5-3절 업체 정책: 자동 실행 개수 (2026-10-07)")


class AppClient:
    def __init__(self, value):
        self.value, self.asked = value, []

    def get(self, path):
        self.asked.append(path)
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


ac = AppClient({"modules": {"Hold": False, "Sales": True}, "limits": {"schedule": 3}})
check(ag.company_policy(ac, "c_x") == (3, ["Hold"], False) and ac.asked == ["meta/companies/c_x/apps/rpa"], "한 번 읽어 한도·안 쓰는 모듈·웰라이프")
check(ag.company_policy(AppClient(None), "c_x") == (2, [], False), "정책이 없으면 기본 2개·안 쓰는 모듈 없음·웰라이프 아님")
check(ag.company_policy(AppClient({"limits": {"schedule": "9"}}), "c_x")[0] == 2 and ag.company_policy(AppClient({"limits": {"schedule": 0}}), "c_x")[0] == 0,
      "이상한 값은 기본 2, 0 은 0 (자동 실행을 못 쓴다)")
for cid, feats, want in (("WELLIFE_x", None, True), ("my_wellife", None, True), ("Wellife", {}, True), ("wel_life", None, False),
                         ("c_demo", {"wellife": True}, True), ("c_demo", {"wellife": False}, False), ("c_demo", None, False)):
    check(ag.wellife_on(cid, feats) is want, f"웰라이프 판정 {cid} {feats} → {want}")
check(ag.company_policy(AppClient({"modules": {"Hold": False}}), "wellife_a") == (2, ["Hold", "Logistics", "Output"], True),
      "웰라이프 업체: 물류관리·운송장 출력을 안 쓰는 모듈에 더한다")
check(ag.company_policy(AppClient({"features": {"wellife": True}}), "c_demo")[2] is True, "관리 화면에서 연 업체도 웰라이프")
with tempfile.TemporaryDirectory() as d:
    os.environ["RPA_STATUS_DIR"] = d              # 실제 settings.json 을 건드리지 않게
    os.environ["RPA_DASHBOARD_DRY_RUN"] = "1"
    try:
        import rpa_status as st
        import rpa_dashboard as dash
        three = {"enabled": True, "days": [0], "slots": [{"at": "09:00"}, {"at": "10:00"}, {"at": "11:00"}]}
        acts = ag.real_actions(limits=lambda: (2, ["Hold"]))
        try:
            acts["set_schedule"](three); check(False, "한도를 넘는 줄 수는 거절")
        except RuntimeError as e:
            check(str(e) == "자동 실행은 2개까지입니다" and st.read_settings()["schedule"]["slots"] == [{"at": "09:00"}], f"한도를 넘으면 저장 전에 거절 ({e})")
        msg = acts["set_schedule"]({**three, "enabled": False})
        check(msg == "자동 실행을 껐습니다" and len(st.read_settings()["schedule"]["slots"]) == 3, f"끄기는 한도를 넘어도 된다 - 줄은 그대로 ({msg})")
        msg = acts["set_schedule"]({"enabled": True, "days": [0], "slots": [{"at": "09:00"}, {"at": "11:00", "run": ["Logistics"]}]})
        check("월 09:00, 11:00 물류관리" in msg, f"한도 안이면 저장 ({msg})")
        dash.set_policy(1, [])
        try:
            ag.real_actions(limits=lambda: None)["set_schedule"](three); check(False, "못 읽어도 적힌 한도로 거절")
        except RuntimeError as e:
            check("1개까지" in str(e), "못 읽으면 PC 에 적힌 마지막 한도로")
        st.write_settings({"schedule": {}})       # policy 없음 = 한 번도 못 읽음
        ag.real_actions(limits=lambda: None)["set_schedule"](three)
        check(len(st.read_settings()["schedule"]["slots"]) == 3, "한 번도 못 읽었으면 자르지 않는다 (PC 상한 12 까지만)")
        pol = ag.Policy(AppClient({"limits": {"schedule": 3}, "modules": {"Hold": False}}), "c_x")
        check(pol.refresh() == (3, ["Hold"], False) and st.read_settings()["schedule"]["policy"]["limit"] == 3
              and st.read_settings()["schedule"]["policy"]["off"] == ["Hold"], "정책을 읽어 PC 설정에 적는다")
        check(pol.refresh() is None, "10분 안에는 다시 안 읽는다")
        check(ag.Policy(AppClient(fb.HttpError(503, "끊김")), "c_x").refresh(force=True) is None
              and st.read_settings()["schedule"]["policy"]["limit"] == 3, "못 읽으면 적힌 값 그대로")
        os.environ["RPA_USER_CONFIG"] = os.path.join(d, "RPA_UserConfig.json")
        with open(os.environ["RPA_USER_CONFIG"], "w", encoding="utf-8") as f:
            json.dump({"LogIn": {"AdminCode": "x"}}, f)
        wl = ag.Policy(AppClient({"features": {"wellife": True}}), "c_demo")
        check(wl.refresh(force=True) == (2, ["Logistics", "Output"], True) and st.wellife_policy() is True, "정책을 PC 에 적는다 (wellife)")
        check(st.read_wellife_modules()[0] == {"Login": True, "Sales": True, "Hold": False, "Sap": False, "Wms": False},
              "처음 열리면 섹션을 기본값(로그인·매출처리만)으로 만든다")
        check(ag.Policy(AppClient(fb.HttpError(503, "끊김")), "c_demo").refresh(force=True) is None and st.wellife_policy() is True,
              "정책을 못 읽으면 PC 에 적힌 마지막 값 (웰라이프 그대로)")
        check(st.has_wellife_section() is True, "정책을 못 읽어도 섹션은 안 지운다")
        check(ag.Policy(AppClient({"features": {"wellife": False}}), "c_demo").refresh(force=True) == (2, [], False)
              and st.wellife_policy() is False and st.has_wellife_section() is False
              and st.read_user_config()["LogIn"] == {"AdminCode": "x"}, "열렸다 닫히면 정책 False + Wellife 섹션 지움 (다른 섹션은 그대로)")
        st.ensure_wellife_section()                  # 메모장으로 직접 넣은 섹션 - 한 번도 안 열렸던 업체
        check(ag.Policy(AppClient({"features": {"wellife": False}}), "c_demo").refresh(force=True) is not None and st.has_wellife_section() is True,
              "한 번도 안 열린 업체의 섹션은 지우지 않는다 (그대로 멈춤)")
        os.environ.pop("RPA_USER_CONFIG", None)
        dash.set_policy(3, [])
        dash.apply_schedule({"enabled": True, "days": list(range(7)), "slots": [{"at": "11:00", "run": ["Prepare", "Logistics"]}]})
        tc = TokenClient(9, 0)
        tk = ag.Tokens(tc, "c_demo", ag.Prices(tc), plan, next_plan=ag.next_plan)
        tk.refresh(force=True)
        check(tk.view()["cost"]["next"] == 3, f"다음 예약 줄의 토큰 = 그 줄의 모듈 (물류관리 1·로그인 0) + 사이트 수집 (사이트 2) ({tk.view()['cost']})")
        dash.set_policy(3, ["Logistics"])
        dash.apply_schedule({"enabled": True, "days": list(range(7)), "slots": [{"at": "11:00", "run": ["Sales", "Logistics", "Output"]}]})
        check(tk.view()["cost"]["next"] == 1, f"업체가 물류관리를 안 쓰면 운송장도 안 돈다 - 주문매핑 1 만 ({tk.view()['cost']})")
        dash.apply_schedule({"enabled": True, "days": list(range(7)), "slots": [{"at": "11:00"}]})
        check("next" not in tk.costs(), "'전체' 줄이면 next 없음 (화면은 전체 실행 토큰을 쓴다)")
        try:
            ag.real_actions()["resume_repeat"](None); check(False, "멈춘 반복이 없는데 다시 시작")
        except RuntimeError as e:
            check(str(e) == "지금은 멈춘 반복이 없습니다", "resume_repeat: 멈춘 반복이 없으면 그 글로 실패")
    finally:
        os.environ.pop("RPA_STATUS_DIR", None)
        os.environ.pop("RPA_DASHBOARD_DRY_RUN", None)

print("\n7-2절 자동 업데이트 명령 (설계 6절)")
check(ag.decide({"state": "queued", "type": "update", "expires_at": NOW + 60, "by": "uid-of-admin"}, NOW)[0] == "bad",
      "관리 화면이 아닌 곳에서 온 update 는 버린다")
check(ag.decide({"state": "queued", "type": "rollback", "expires_at": NOW + 60, "by": "admin-tool"}, NOW)[0] == "run", "관리 화면의 rollback 은 돈다")
with tempfile.TemporaryDirectory() as d:
    os.environ["RPA_PROGRAMDATA"] = d
    try:
        import rpa_update as upd
        started = []
        acts = ag.real_actions(start_update=lambda v, m: started.append((v, m)))
        import rpa_status as st
        orig = st.check_install
        st.check_install = lambda root=None: {"version": "2026.10.07-4", "state": "ok"}
        try:
            for bad, why in (({"version": "../x"}, "판 번호"), ({"version": "2026.10.07-4"}, "이미 최신 업데이트를 사용하고 있습니다")):
                try:
                    acts["update"](bad); check(False, f"거절 안 됨 {bad}")
                except RuntimeError as e:
                    check(why in str(e), f"update 거절: {why} ({e})")
            msg = acts["update"]({"version": "2026.10.07-5"})
            check(started == [("2026.10.07-5", "update")] and "예약" in msg, f"update → 스레드 시작 ({msg})")
            upd.write_state({"state": "waiting"})
            try:
                acts["update"]({"version": "2026.10.07-6"}); check(False, "업데이트 중 두 번째")
            except RuntimeError as e:
                check("이미 업데이트" in str(e), f"업데이트 중이면 거절 ({e})")
            upd.write_state({"state": "done"})
            try:
                acts["rollback"](None); check(False, "보관본 없이 되돌리기")
            except RuntimeError as e:
                check("이전 판" in str(e), f"보관본이 없으면 거절 ({e})")
            st.check_install = lambda root=None: {"version": "2026.10.07-4", "state": "mixed"}
            try:
                acts["update"]({"version": "2026.10.07-5"}); check(False, "mixed 인데 업데이트")
            except RuntimeError as e:
                check("판 구조" in str(e), f"판 구조가 어긋난 PC 는 거절 ({e})")
        finally:
            st.check_install = orig
    finally:
        os.environ.pop("RPA_PROGRAMDATA", None)
check("update" in ag.KNOWN_TYPES and "rollback" in ag.KNOWN_TYPES, "명령 종류에 update·rollback")

print("\n7-3절 접속에 성공했을 때만 살아 있음")
with tempfile.TemporaryDirectory() as d:
    os.environ["RPA_PROGRAMDATA"] = d
    try:
        import rpa_update as upd
        upd.write_state({"state": "applying"})
        class FakeUp:
            def __init__(self, ok): self.ok = ok
            def push_heartbeat(self, info): return self.ok
        alive = [False]
        inst = {"version": "2026.10.07-5", "state": "ok"}
        ag.send_heartbeat(FakeUp(False), {"at": 1}, inst, alive)
        check(alive[0] is False and not os.path.exists(upd.path("alive.json")), "heartbeat 실패면 alive.json 안 적는다")
        ag.send_heartbeat(FakeUp(True), {"at": 1}, dict(inst, state="mixed"), alive)
        check(alive[0] is False and not os.path.exists(upd.path("alive.json")), "판 점검이 ok 가 아니면 안 적는다")
        ag.send_heartbeat(FakeUp(True), {"at": 1}, inst, alive)
        check(alive[0] is True and os.path.isfile(upd.path("alive.json")), "heartbeat 성공이면 alive.json")
    finally:
        os.environ.pop("RPA_PROGRAMDATA", None)

print("\n8절 첫 실행 설정 (새 PC)")


def jwt(payload):
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJSUzI1NiJ9.{body}.sig"


class TokenClient:
    def __init__(self, tok):
        self.tok = tok

    def token(self):
        return self.tok


check(fb.claims(jwt({"cid": "c_x", "pcId": "pc_y", "role": "agent"}))["pcId"] == "pc_y", "토큰에서 클레임을 읽는다")

# 이메일 조립 규칙 - setup.js·app.js 와 같은 예시
check(ag.email_for("c_demo", "pc_office") == "agent-pc-office@c-demo.rpa-test-f02e0.firebaseapp.com", "에이전트 계정 이메일 (지금 실제 계정과 같다)")
check(ag.email_for("", "pc_x") == "agent-pc-x@rpa-test-f02e0.firebaseapp.com", "회사가 없으면 프로젝트 도메인")
check(ag.email_for("c_a_b", "pc_1_2") == "agent-pc-1-2@c-a-b.rpa-test-f02e0.firebaseapp.com", "밑줄은 전부 하이픈으로")

check(ag.auth_message("INVALID_LOGIN_CREDENTIALS") == ag.auth_message("EMAIL_NOT_FOUND") == ag.auth_message("INVALID_PASSWORD")
      and "비밀번호가 맞지" in ag.auth_message("INVALID_PASSWORD"), "자격증명 거부 셋은 한 문구")
check(ag.auth_message("USER_DISABLED") == "이 에이전트 계정은 사용중지되어 있습니다. 관리자에게 물어보세요"
      and "10분" in ag.auth_message("TOO_MANY_ATTEMPTS_TRY_LATER"), "사용중지·과다 시도 문구 (2026-10-06 이름: 에이전트 계정·사용중지)")
check(ag.auth_message("OPERATION_NOT_ALLOWED") == "로그인 거부: OPERATION_NOT_ALLOWED", "모르는 code 는 그대로 보여 준다")

with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "agent_config.json")
    cfg = ag.first_run(p, "c_x", "pc_y", "pw-1234", TokenClient(jwt({"cid": "c_x", "pcId": "pc_y", "role": "agent"})))
    check(cfg["cid"] == "c_x" and cfg["pc_id"] == "pc_y" and cfg["email"] == "agent-pc-y@c-x.rpa-test-f02e0.firebaseapp.com"
          and cfg["password"] == "pw-1234", "회사 코드·PC 이름으로 이메일을 조립해 저장한다")
    check(cfg["project_id"] == secret.PUBLIC["project_id"] and cfg["database_url"] == secret.PUBLIC["database_url"],
          "프로젝트 값은 공개 설정에서")
    with open(p, encoding="utf-8") as f:
        check("pw-1234" not in f.read(), "파일에 평문 비밀번호가 없다")
    cfg = ag.first_run(p, "c_x", "pc_y", "pw-new", TokenClient(jwt({"cid": "c_x", "pcId": "pc_y", "role": "agent"})),
                       email="agent-pc-y@c-x.example.com")
    check(cfg["email"] == "agent-pc-y@c-x.example.com" and cfg["password"] == "pw-new", "비밀번호를 다시 물을 때는 옛 이메일을 그대로")
    cfg = ag.first_run(p, "c_x", "pc_y", "pw-new", TokenClient(jwt({"cid": "c_x", "pcId": "pc_z", "role": "agent"})),
                       email="agent-pc-y@c-x.example.com")
    check(cfg["pc_id"] == "pc_z" and cfg["cid"] == "c_x" and secret.load_config(p)["pc_id"] == "pc_z",
          "다시 물을 때 토큰의 회사·PC 가 다르면 토큰 값을 쓴다 (클레임을 옮기고 비밀번호도 바꾼 경우)")
    bad = os.path.join(d, "x.json")
    try:
        ag.first_run(bad, "c_x", "pc_y", "pw", TokenClient(jwt({"cid": "c_x", "role": "admin"})))
        check(False, "사람 계정은 거부한다")
    except ValueError:
        check(not os.path.exists(bad), "사람 계정은 거부한다")
    try:
        ag.first_run(bad, "c_x", "pc_z", "pw", TokenClient(jwt({"cid": "c_x", "pcId": "pc_y", "role": "agent"})))
        check(False, "토큰의 회사·PC 가 친 값과 다르면 거부한다")
    except ValueError as e:
        check("c_x/pc_y" in str(e) and not os.path.exists(bad), "토큰의 회사·PC 가 친 값과 다르면 거부한다")

print("\n9절 명령 구독 (토큰 만료·끊김)")


class StreamClient:
    """stream() 이 미리 정한 이벤트를 내놓는 가짜 클라이언트"""
    def __init__(self, events):
        self.events, self.renewed, self.closed = events, 0, False

    def stream(self, path):
        try:
            for ev in self.events:
                yield ev
        finally:
            self.closed = True

    def renew(self):
        self.renewed += 1


got = []
sc = StreamClient([("keep-alive", None),
                   ("put", {"path": "/", "data": {"c1": {"type": "launch"}, "c2": {"type": "stop_erpia"}}}),
                   ("patch", {"path": "/c3", "data": {"type": "launch"}}),
                   ("put", {"path": "/c1/state", "data": "done"}),
                   ("auth_revoked", None),
                   ("put", {"path": "/c9", "data": {"type": "launch"}})])
why = ag.watch_commands(sc, "apps/rpa/commands/c_demo/pc_office", lambda i, c: got.append(i))
check(got == ["c1", "c2", "c3"], "처음 덩어리와 낱개 명령을 건네주고, 하위 값 변경은 건너뛴다")
check(why == "auth_revoked" and sc.renewed == 1 and sc.closed, "토큰 만료 알림이 오면 토큰을 버리고 돌아온다 (다시 붙게)")
check(ag.watch_commands(StreamClient([("keep-alive", None)]), "p", lambda i, c: None) == "ended", "서버가 닫으면 ended")

import threading
ev, got2 = threading.Event(), []
ev.set()
sc2 = StreamClient([("keep-alive", None), ("put", {"path": "/c1", "data": {"type": "launch"}})])
check(ag.watch_commands(sc2, "p", lambda i, c: got2.append(i), stop=ev) == "stopped" and got2 == [] and sc2.closed,
      "stop 이 켜지면 keep-alive 에서 빠져나온다 (pump 가 인증이 죽은 걸 먼저 봤을 때)")

h2 = FakeHTTP()
h2.add({"idToken": "T", "refreshToken": "R", "expiresIn": "3600"})
h2.replies.append((200, b"event: keep-alive\ndata: null\n\n"))
c2 = fb.Client(CFG, opener=h2, clock=lambda: h2.now)
check(list(c2.stream("apps/rpa/commands/c_demo/pc_office")) == [("keep-alive", None)] and h2.last_timeout == 90,
      "구독 연결에 90초 읽기 시한 (30초 keep-alive 가 세 번 안 오면 끊긴 것)")

print("\n10절 에이전트 파일 자리 (배포판 구조 1부)")
import subprocess  # noqa: E402

AGENT_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent"))
WHERE = "import json, agent, secret; print(json.dumps([agent.QUEUE_PATH, agent.HISTORY_POS_PATH, secret.CONFIG_PATH]))"


def where(extra):
    """새 프로세스에서 agent·secret 을 불러와 기본 자리를 받는다 (모듈 상수라 import 할 때 정해진다)."""
    env = {k: v for k, v in os.environ.items() if k not in ("RPA_AGENT_QUEUE", "RPA_AGENT_CONFIG", "RPA_PROGRAMDATA")}
    env.update(extra, PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, "-c", WHERE], cwd=AGENT_DIR, env=env, capture_output=True,
                       text=True, encoding="utf-8", timeout=60)
    if r.returncode != 0:
        return r.stderr[-300:]
    return [os.path.normpath(p) for p in json.loads(r.stdout.strip().splitlines()[-1])]


with tempfile.TemporaryDirectory() as d:
    got = where({"RPA_PROGRAMDATA": os.path.join(d, "none")})
    check(got == [os.path.join(AGENT_DIR, n) for n in ("queue.jsonl", "history_pos.txt", "agent_config.json")],
          f"옛 구조는 지금 자리 (에이전트 폴더, 개발 PC 도 dist 가 아니다) {got}")
    root = os.path.join(d, "AFTER MARKET", "RPA")
    os.makedirs(os.path.join(root, "config"))
    got = where({"RPA_PROGRAMDATA": root})
    check(got == [os.path.join(root, "data", "queue.jsonl"), os.path.join(root, "data", "history_pos.txt"),
                  os.path.join(root, "config", "agent_config.json")], f"새 구조는 data·config {got}")
    got = where({"RPA_PROGRAMDATA": root, "RPA_AGENT_QUEUE": os.path.join(d, "q", "queue.jsonl"),
                 "RPA_AGENT_CONFIG": os.path.join(d, "c.json")})
    check(got == [os.path.join(d, "q", "queue.jsonl"), os.path.join(d, "q", "history_pos.txt"),
                  os.path.join(d, "c.json")], f"시험용 환경변수가 새 구조보다 앞선다 {got}")

print("\n11절 에이전트 하나만 (설치 마법사 2부)")
import ctypes  # noqa: E402
import agent  # noqa: E402

lock = rf"Local\AFTER_MARKET_RPA_AGENT_TEST_{os.getpid()}"
check(agent.single_instance(lock) is True, "처음 잡으면 True")
check(agent.single_instance(lock) is True, "같은 프로세스가 다시 부르면 그대로 True (이미 잡았다)")
child = f"import sys; sys.path.insert(0, {AGENT_DIR!r}); import agent; print(agent.single_instance({lock!r}))"
r = subprocess.run([sys.executable, "-c", child], cwd=AGENT_DIR, capture_output=True, text=True, encoding="utf-8",
                   timeout=60, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
check(r.stdout.strip().splitlines()[-1:] == ["False"], f"다른 프로세스는 못 잡는다 {r.stdout[-200:]} {r.stderr[-200:]}")
held = rf"Local\AFTER_MARKET_RPA_AGENT_HELD_{os.getpid()}"
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateMutexW.restype = ctypes.c_void_p
k32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
held_handle = k32.CreateMutexW(None, False, held)       # '다른 에이전트' 가 잡은 잠금 흉내
old_name = agent.MUTEX_NAME
agent.MUTEX_NAME = held
try:
    check(agent.main() == 4, "이미 돌고 있으면 main() 은 설정을 읽기 전에 4 로 끝난다")
finally:
    agent.MUTEX_NAME = old_name
check(agent.MUTEX_NAME == (os.environ.get("RPA_AGENT_MUTEX") or r"Local\AFTER_MARKET_RPA_AGENT"),
      "기본 이름 Local\\AFTER_MARKET_RPA_AGENT (시험은 RPA_AGENT_MUTEX)")

print("\n5-2절 실제 동작 - 쇼핑몰 프리셋 (가짜 사용자 설정)")
with tempfile.TemporaryDirectory() as d:
    os.environ["RPA_USER_CONFIG"] = os.path.join(d, "RPA_UserConfig.json")
    try:
        import rpa_status as st
        st.write_user_config({"LogIn": {"AdminCode": "x", "ID": "a", "PW": "비밀-시험"}, "Sites": {
            "PRESET1": {"URL": "https://x/login", "ID": "seller", "PW": "몰-비밀", "Action": ["replay"], "Stts": 9, "Preset": 1,
                        "note": "지마켓"},
            "PRESET2": {"URL": "https://y/login", "ID": "seller", "PW": "", "Action": ["replay"], "Stts": 9, "Preset": 2,
                        "note": "쿠팡"}}})
        rec1 = {"version": 1, "start_url": "https://x/login", "steps": [{"kind": "goto", "page": 0, "href": "https://x/login"}]}
        st.write_presets([{"no": 1, "name": "지마켓", "code": "012", "saved_at": None, "record": rec1},
                          {"no": 2, "name": "쿠팡", "code": "013", "saved_at": None, "record": rec1}])
        acts = ag.real_actions()
        msg = acts["set_presets"]({"PRESET1": True})
        check(st.read_user_config()["Sites"]["PRESET1"]["Stts"] == 0 and "① 지마켓" in msg, f"켜면 Stts 0, 결과에 이름 ({msg})")
        acts["set_presets"]({"PRESET1": False})
        check(st.read_user_config()["Sites"]["PRESET1"]["Stts"] == 9, "끄면 Stts 9")
        for args, why in (({"PRESET7": True}, "아는 프리셋"), ({"PRESET2": True}, "켤 수 없")):
            try:
                acts["set_presets"](args)
                check(False, f"거부: {why}")
            except RuntimeError as e:
                check(why in str(e), f"거부: {why} ({e})")
        check(ag.decide({"type": "set_presets", "state": "queued", "expires_at": NOW + 60}, NOW)[0] == "run", "set_presets 는 아는 명령")
        rows2 = [{"started_at": "2026-09-14T13:55:00", "state": "success", "program": "observer"},
                 {"started_at": "2026-09-14T13:56:00", "state": "stopped", "program": "prepare"}]
        check(ag.recent_summary(rows2, _dt.date(2026, 9, 14))[-1] == {"date": "2026-09-14", "success": 0, "failed": 1, "crashed": 0},
              "옵저버 미리보기는 날짜별 도넛에 안 센다")
    finally:
        os.environ.pop("RPA_USER_CONFIG", None)

print(f"\n{COUNT - len(FAIL)}/{COUNT} 통과")
if FAIL:
    print("실패:", ", ".join(FAIL))
    sys.exit(1)
