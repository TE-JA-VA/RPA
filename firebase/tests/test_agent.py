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
check(rs[-1] == {"date": "2026-09-14", "success": 1, "failed": 1}, "하루에 성공·실패를 센다")
check(rs[-2]["failed"] == 1 and sum(d["success"] for d in rs) == 1, "중단·비정상 종료는 실패, 20일 밖은 뺀다")

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


with tempfile.TemporaryDirectory() as d:
    q = os.path.join(d, "queue.jsonl")
    cl = FlakyClient()
    up = ag.Uploader(cl, "c_demo", "pc_office", q)

    up.push_live({"host": "PC1"})
    check(cl.puts[-1][0] == "apps/rpa/live/c_demo/pc_office", "현황은 live/회사/PC 로 간다")

    cl.ok = False
    up.push_live({"host": "PC2"})
    up.push_heartbeat({"at": 1})
    check(up.pending() == 2, "끊기면 큐에 쌓는다")
    check(os.path.exists(q), "큐는 파일로 남는다")

    cl.ok = True
    up.flush()
    check(up.pending() == 0, "연결되면 큐를 비운다")
    check([p for p, _ in cl.puts][-2:] == ["apps/rpa/live/c_demo/pc_office", "apps/rpa/live/c_demo/pc_office/heartbeat"],
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
            raise fb.HttpError(403, "Permission denied")
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
        sel = st.read_routine_modules(cred)[0]
        check(sel["Login"] is True and sel["Sales"] is False and sel["Hold"] is True, f"로그인은 꺼 달라고 해도 켜진 채 저장 ({sel})")
        check("Login" in msg, "결과 문장에 로그인 포함")
        raw = open(cred, encoding="utf-8").read()
        check("비밀-시험" in raw, "자격증명은 그대로 남는다")
        try:
            acts["set_modules"]({"Nope": True}); check(False, "모르는 모듈만 있으면 거부")
        except RuntimeError as e:
            check("아는 모듈" in str(e), "모르는 모듈만 있으면 거부")
    finally:
        os.environ.pop("RPA_CRED_FILE", None)

print("\n8절 첫 실행 설정 (새 PC)")
import base64


def jwt(payload):
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJSUzI1NiJ9.{body}.sig"


class TokenClient:
    def __init__(self, tok):
        self.tok = tok

    def token(self):
        return self.tok


check(fb.claims(jwt({"cid": "c_x", "pcId": "pc_y", "role": "agent"}))["pcId"] == "pc_y", "토큰에서 클레임을 읽는다")
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "agent_config.json")
    cfg = ag.first_run(p, " agent-pc-y@c-x.example.com ", "pw-1234",
                       TokenClient(jwt({"cid": "c_x", "pcId": "pc_y", "role": "agent"})))
    check(cfg["cid"] == "c_x" and cfg["pc_id"] == "pc_y" and cfg["email"] == "agent-pc-y@c-x.example.com"
          and cfg["password"] == "pw-1234", "회사·PC 는 토큰에서, 이메일은 다듬어서 저장한다")
    check(cfg["project_id"] == secret.PUBLIC["project_id"] and cfg["database_url"] == secret.PUBLIC["database_url"],
          "프로젝트 값은 공개 설정에서")
    with open(p, encoding="utf-8") as f:
        check("pw-1234" not in f.read(), "파일에 평문 비밀번호가 없다")
    bad = os.path.join(d, "x.json")
    try:
        ag.first_run(bad, "admin@c-x.example.com", "pw", TokenClient(jwt({"cid": "c_x", "role": "admin"})))
        check(False, "사람 계정은 거부한다")
    except ValueError:
        check(not os.path.exists(bad), "사람 계정은 거부한다")

print(f"\n{COUNT - len(FAIL)}/{COUNT} 통과")
if FAIL:
    print("실패:", ", ".join(FAIL))
    sys.exit(1)
