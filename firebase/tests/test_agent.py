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

ff = fb.fs_fields({"a": "x", "b": 3, "c": True, "d": None, "e": 1.5, "f": {"k": [1]}})
check(ff["a"] == {"stringValue": "x"} and ff["b"] == {"integerValue": "3"} and ff["c"] == {"booleanValue": True}
      and ff["d"] == {"nullValue": None} and ff["e"] == {"doubleValue": 1.5}, "Firestore 형 붙이기")
check(json.loads(ff["f"]["stringValue"]) == {"k": [1]}, "복합 값은 JSON 문자열")

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
    try:
        acts = ag.real_actions()
        msg = acts["set_modules"]({"Login": False, "Sales": False, "Hold": True})
        import rpa_status as st
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
    finally:
        os.environ.pop("RPA_CRED_FILE", None)

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
check(ag.email_for("c_demo", "pc_office") == "agent-pc-office@c-demo.rpa-test-f02e0.firebaseapp.com", "기계 계정 이메일 (지금 실제 계정과 같다)")
check(ag.email_for("", "pc_x") == "agent-pc-x@rpa-test-f02e0.firebaseapp.com", "회사가 없으면 프로젝트 도메인")
check(ag.email_for("c_a_b", "pc_1_2") == "agent-pc-1-2@c-a-b.rpa-test-f02e0.firebaseapp.com", "밑줄은 전부 하이픈으로")

check(ag.auth_message("INVALID_LOGIN_CREDENTIALS") == ag.auth_message("EMAIL_NOT_FOUND") == ag.auth_message("INVALID_PASSWORD")
      and "비밀번호가 맞지" in ag.auth_message("INVALID_PASSWORD"), "자격증명 거부 셋은 한 문구")
check("막혀" in ag.auth_message("USER_DISABLED") and "10분" in ag.auth_message("TOO_MANY_ATTEMPTS_TRY_LATER"), "정지·과다 시도 문구")
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

print(f"\n{COUNT - len(FAIL)}/{COUNT} 통과")
if FAIL:
    print("실패:", ", ".join(FAIL))
    sys.exit(1)
