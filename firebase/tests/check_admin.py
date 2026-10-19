"""관리 화면(AFTERMARKET_SETUP) 시험 - admin.js 를 에뮬레이터에 붙여 API 와 화면을 본다. 실제 프로젝트는 안 건드린다.

    cd D:\\AX\\RPA\\firebase; . .\\emu_env.ps1; cd tests
    firebase emulators:exec --config ../firebase.json --only auth,database,firestore --project rpa-test-f02e0 "D:\\AX\\RPA\\.venv\\Scripts\\python.exe check_admin.py"

만드는 계정은 에뮬레이터 것이라도 비밀번호를 찍지 않는다 (길이만 보고, 실패 글에서도 가린다).
"""
import atexit
import datetime
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
PROJECT = "rpa-test-f02e0"
DB = "http://127.0.0.1:9000"
NS = f"{PROJECT}-default-rtdb"
AUTH = "http://127.0.0.1:9099"
FS = f"http://127.0.0.1:8080/v1/projects/{PROJECT}/databases/(default)/documents"
OWNER = {"Authorization": "Bearer owner"}
ADMIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "admin")
LOG = os.path.join(ADMIN, "관리_기록.txt")
FAIL, SECRETS = [], []
COUNT = 0
for k in ("FIREBASE_AUTH_EMULATOR_HOST", "FIREBASE_DATABASE_EMULATOR_HOST", "FIRESTORE_EMULATOR_HOST"):
    if not os.environ.get(k):
        sys.exit(f"{k} 가 없다. emulators:exec 안에서 돌릴 것")


def mask(text):
    text = str(text)
    for s in SECRETS:
        if s:
            text = text.replace(s, "****")
    return re.sub(r"('password': ')[^']+", r"\1****", re.sub(r'("password": ")[^"]+', r"\1****", text))


def check(ok, label, detail=""):
    global COUNT
    COUNT += 1
    print(f"  {'통과' if ok else '실패'}  {label}" + (f"  {mask(detail)}" if detail and not ok else ""))
    if not ok:
        FAIL.append(label)


def call(method, url, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read().decode("utf-8")
        return json.loads(raw) if raw else None


def db_patch(path, value):
    return call("PATCH", f"{DB}/{path}.json?ns={NS}", value, OWNER)


def db_get(path):
    return call("GET", f"{DB}/{path}.json?ns={NS}", None, OWNER)


def db_put(path, value):
    return call("PUT", f"{DB}/{path}.json?ns={NS}", value, OWNER)


def account(email_):
    r = call("POST", f"{AUTH}/identitytoolkit.googleapis.com/v1/projects/{PROJECT}/accounts:lookup", {"email": [email_]}, OWNER)
    return (r or {}).get("users", [None])[0] or {}


def claims(email_):
    return json.loads(account(email_).get("customAttributes") or "{}")


def fs_doc(path):
    try:
        d = call("GET", f"{FS}/{path}", None, OWNER)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    return {k: int(v["integerValue"]) if "integerValue" in v else v.get("stringValue") for k, v in (d.get("fields") or {}).items()}


def email(cid, local):
    return f"{local.replace('_', '-')}@{cid.replace('_', '-')}.{PROJECT}.firebaseapp.com"


# --- 서버 켜기 (브라우저 없이) ---
log_start = os.path.getsize(LOG) if os.path.exists(LOG) else 0
srv = subprocess.Popen(["node", "admin.js", "--no-open"], cwd=ADMIN, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, encoding="utf-8", errors="replace")
atexit.register(lambda: srv.poll() is None and srv.kill())   # 시험이 중간에 죽어도 서버를 남기지 않는다
url = port = key = None
for line in srv.stdout:
    m = re.search(r"http://127\.0\.0\.1:(\d+)/\?k=([\w-]+)", line)
    if m:
        url, port, key = m.group(0), m.group(1), m.group(2)
        break
out_lines = []
threading.Thread(target=lambda: out_lines.extend(srv.stdout), daemon=True).start()   # 서버 출력을 계속 비운다 (막히지 않게)
BASE = f"http://127.0.0.1:{port}"


def api(method, path, body=None, k=None, host=None):
    headers = {"X-Admin-Key": key if k is None else k}
    if host:
        headers["Host"] = host
    try:
        return 200, call(method, BASE + path, body, headers)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


print("=== 1. 켜기와 보안 ===")
check(url is not None, "브라우저 없이 켜면 주소(비밀 값 포함)를 찍는다")
code, r = api("GET", "/api/info", k="")
check(code == 403 and "비밀 값" in r.get("error", ""), "비밀 값 없이 /api 를 부르면 거절", (code, r))
code, r = api("GET", "/api/info", k="x" * len(key or ""))
check(code == 403, "비밀 값이 틀려도 거절", code)
code, r = api("GET", "/api/info", host=f"localhost:{port}")
check(code == 403 and "127.0.0.1" in r.get("error", ""), "Host 가 127.0.0.1:<포트> 가 아니면 거절 (주소 이름 위조)", (code, r))
try:   # new URL 이 못 읽는 요청 줄 - 브라우저 fetch 로도 보낼 수 있다. 서버가 죽으면 하던 신규 업체 흐름이 반쪽으로 남는다 (검토 2026-10-06)
    with socket.create_connection(("127.0.0.1", int(port)), timeout=10) as raw:
        raw.sendall(f"GET //[ HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n".encode())
        raw.recv(200)
except OSError:
    pass
try:
    code, r = api("GET", "/api/info")
except urllib.error.URLError as e:
    code, r = None, e
check(code == 200, "이상한 요청 줄(GET //[)을 받아도 서버가 죽지 않는다", (code, r))
page_html = urllib.request.urlopen(BASE + "/", timeout=30).read().decode("utf-8")
check("오토파일럿 관리" in page_html and (key or "?") not in page_html, "화면 파일은 비밀 값 없이 내려주고, 그 안에 비밀 값이 없다")
code, r = api("GET", "/api/info")
check(code == 200 and r == {"emulator": True, "project": PROJECT, "dashboard": f"https://{PROJECT}.web.app"}, "에뮬레이터에 붙었다고 알린다", r)

print("=== 2. 신규 업체 (한 흐름) ===")
PLAN = {"cid": "t_new", "name": "<img src=x onerror=alert(1)> 새 업체", "hold": False,
        "pcs": [{"pcId": "pc_a", "label": "사무실 PC"}, {"pcId": "pc_b", "label": "창고 PC"}],
        "users": [{"id": "boss", "name": "대표", "role": "admin"}, {"id": "staff", "name": "직원", "role": "viewer"}],
        "tokens": {"amount": "+500", "memo": "첫 결제"}}
for bad, why in ((dict(PLAN, cid="Net-1"), "업체코드"), ({k: v for k, v in PLAN.items() if k != "hold"}, "물류대기"),
                 (dict(PLAN, pcs=[]), "PC"), (dict(PLAN, users=[{"id": "v", "role": "viewer"}]), "관리자"),
                 (dict(PLAN, tokens={"amount": "1,000"}), "최초 토큰량")):
    code, r = api("POST", "/api/setup", bad)
    check(code == 400 and why in r.get("error", ""), f"잘못된 내용은 만들기 전에 거절: {why}", (code, r))
check(db_get("meta/companies/t_new") is None, "거절된 내용으로는 아무것도 안 만든다")
code, r = api("POST", "/api/setup", PLAN)
made = r.get("made", {}) if code == 200 else {}
SECRETS += [u.get("password", "") for u in made.get("users", [])] + [a.get("password", "") for a in made.get("agents", [])]
check(code == 200 and r["ok"] and len(r["steps"]) == 9 and all(s["ok"] for s in r["steps"]),
      "다 만들었다 (업체·PC 2·계정 2·에이전트 계정 2·물류대기·첫 토큰 = 9 줄)", (code, r.get("steps")))
labels = [x["label"] for x in r.get("steps", [])] if code == 200 else []
check("유저 계정 staff" in labels and "에이전트 계정 pc_a" in labels and "물류대기 관리 메뉴 사용 안 함" in labels and "최초 토큰 500개" in labels
      and not any(w in " ".join(labels) for w in ("열람자", "기계", "첫 토큰", "씀")),
      "단계 이름: 유저 계정·에이전트 계정 (사용자가 고른 이름 2026-10-06)", labels)
check({u["id"] for u in made.get("users", [])} == {"boss", "staff"} and {a["pcId"] for a in made.get("agents", [])} == {"pc_a", "pc_b"}
      and len(SECRETS) == 4 and all(len(s) == 24 for s in SECRETS), "만든 계정의 비밀번호를 한 번 돌려준다 (24자)")
check(claims(email("t_new", "boss")) == {"cid": "t_new", "role": "admin"} and claims(email("t_new", "staff")) == {"cid": "t_new", "role": "viewer"}
      and claims(email("t_new", "agent-pc_a")) == {"cid": "t_new", "pcId": "pc_a", "role": "agent"}, "계정·권한(claim)이 실제로 생겼다")
meta = db_get("meta/companies/t_new") or {}
check(meta.get("name") == PLAN["name"] and set(meta.get("pcs", {})) == {"pc_a", "pc_b"}
      and meta.get("apps", {}).get("rpa", {}).get("modules") == {"Hold": False}, "업체·PC·물류대기 끔 (모듈 정책)", meta)
w = fs_doc("wallet/t_new") or {}
check(w.get("granted") == 500 and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", w.get("since") or ""), "첫 토큰 500 - 통장과 시작 시각", w)
code, r = api("POST", "/api/setup", dict(PLAN, name="다른 업체", users=[{"id": "newboss", "role": "admin"}], tokens=None))
check(code == 400 and "이미 등록된 업체" in r.get("error", "") and (db_get("meta/companies/t_new") or {}).get("name") == PLAN["name"]
      and not account(email("t_new", "newboss")), "이미 있는 업체코드를 다른 이름으로 치면 거절 (그 업체 이름을 안 바꾸고 계정도 안 만든다)", (code, r))

TWICE = dict(PLAN, cid="t_twice", name="두번", pcs=[{"pcId": "pc_1", "label": "PC"}], users=[{"id": "boss", "role": "admin"}],
             tokens={"amount": "100"})
results = [None, None]
threads = [threading.Thread(target=lambda i=i: results.__setitem__(i, api("POST", "/api/setup", TWICE))) for i in (0, 1)]
for t in threads:
    t.start()
for t in threads:
    t.join()
for _, res in results:
    SECRETS += [u["password"] for u in res.get("made", {}).get("users", [])] + [a["password"] for a in res.get("made", {}).get("agents", [])]
w = fs_doc("wallet/t_twice") or {}
check(all(c == 200 for c, _ in results) and w.get("granted") == 100, f"동시에 두 번 눌러도 토큰은 한 번만 ({w.get('granted')})")
late = [res for _, res in results if not res.get("made", {}).get("users")]
check(len(late) == 1 and any("이미 등록되어 있어 건너뛰었습니다" in s["note"] for s in late[0]["steps"])
      and any("이미 토큰 정보가 있어" in s["note"] for s in late[0]["steps"]), "늦은 쪽은 이미 있는 계정·통장을 건너뛴다", late)

subprocess.run(["node", "setup.js", "company", "t_retry", "다시"], cwd=ADMIN, capture_output=True, timeout=60)
code, r = api("POST", "/api/companies/t_retry/users", {"id": "boss", "role": "admin", "name": "먼저"})
SECRETS.append(r.get("password", ""))
code, r = api("POST", "/api/setup", dict(TWICE, cid="t_retry", name="다시", tokens=None))
SECRETS += [a["password"] for a in r.get("made", {}).get("agents", [])]
check(code == 200 and r["ok"] and not r["made"]["users"] and [a["pcId"] for a in r["made"]["agents"]] == ["pc_1"]
      and any("boss" in s["label"] and "재발급" in s["note"] for s in r["steps"]), "다시 누르면 남은 것만 (이미 있는 계정은 건너뛰고 재발급 안내)", r.get("steps"))
check(fs_doc("wallet/t_retry") is None, "첫 토큰을 '나중에' 로 하면 통장 없이 (세기만)")

print("=== 3. 업체 표·상세 ===")
code, rows = api("GET", "/api/companies")
row = next((x for x in rows if x["cid"] == "t_new"), {}) if code == 200 else {}
check(row.get("pcs") == 2 and row.get("users") == 4 and row.get("left") == 500 and row.get("month") == 0 and row.get("stts") == 0,
      "업체 표: PC 2 · 계정 4 · 남은 500 · 이번 달 0", row)
code, d = api("GET", "/api/companies/t_new")
check(code == 200 and {u["role"] for u in d["users"]} == {"admin", "viewer", "agent"} and d["modules"] == {"Hold": False}
      and d["tokens"]["granted"] == 500 and d["tokens"]["grants"][0]["memo"] == "첫 결제", "상세: 계정·역할·모듈·통장·넣은 내역", str(d)[:300])
code, r = api("POST", "/api/companies/t_new/tokens", {"amount": "+100", "memo": "추가"})
check(code == 200 and r["wallet"]["left"] == 600 and not r["created"], "토큰 더 넣기 → 남은 600", str(r)[:200])
code, r = api("POST", "/api/companies/t_new/tokens", {"amount": "1,000"})
check(code == 400 and "0이 아닌 정수" in r.get("error", ""), "토큰 수 '1,000' 은 거절 (쉼표)", r)
boss = email("t_new", "boss")
code, r = api("POST", "/api/companies/t_new/passwd", {"id": boss})
SECRETS.append(r.get("password", ""))
check(code == 200 and len(r.get("password", "")) == 24 and r.get("email") == boss, "비밀번호 재발급 (새 값을 한 번 돌려준다)")
code, r = api("POST", "/api/companies/t_new/disabled", {"id": boss, "disabled": True})
check(code == 200 and account(boss).get("disabled") is True, "계정 막기")
code, r = api("POST", "/api/companies/t_new/disabled", {"id": boss, "disabled": False})
check(code == 200 and account(boss).get("disabled") is not True, "계정 다시 열기")
code, r = api("POST", "/api/companies/t_new/modules", {"Hold": "on"})
check(code == 200 and (db_get("meta/companies/t_new/apps/rpa/modules") or {}) == {}, "모듈 정책 켜기 (정책을 지운다 = 그 업체가 쓴다)")
code, r = api("POST", "/api/companies/t_new/modules", {"InvoiceSend": "off"})
check(code == 200 and db_get("meta/companies/t_new/apps/rpa/modules") == {"InvoiceSend": False}, "모듈 정책: 운송장번호 전송도 끌 수 있다 (사용자 2026-10-14)", r)
api("POST", "/api/companies/t_new/modules", {"InvoiceSend": "on"})
code, d = api("GET", "/api/companies/t_new")
check(code == 200 and d.get("scheduleLimit") is None, "자동 실행 개수: 값이 없으면 null (화면은 기본 2)", str(d.get("scheduleLimit")))
code, r = api("POST", "/api/companies/t_new/limits", {"schedule": "3"})
check(code == 200 and r == {"cid": "t_new", "schedule": 3} and db_get("meta/companies/t_new/apps/rpa/limits/schedule") == 3, "자동 실행 개수 3", r)
for bad in ("13", "-1", "2.5", "", "셋"):
    code, r = api("POST", "/api/companies/t_new/limits", {"schedule": bad})
    check(code == 400 and "0~12" in r.get("error", "") and db_get("meta/companies/t_new/apps/rpa/limits/schedule") == 3, f"자동 실행 개수 거절 {bad!r}", r)
code, d = api("GET", "/api/companies/t_new")
check(code == 200 and d.get("presetLimit") is None, "옵저버 프리셋 수: 값이 없으면 null (화면은 기본 2)", str(d.get("presetLimit")))
code, r = api("POST", "/api/companies/t_new/presets", {"presets": "5"})
check(code == 200 and r == {"cid": "t_new", "presets": 5} and db_get("meta/companies/t_new/apps/rpa/limits/presets") == 5, "옵저버 프리셋 수 5", r)
for bad in ("1", "11", "2.5", "", "셋"):
    code, r = api("POST", "/api/companies/t_new/presets", {"presets": bad})
    check(code == 400 and "2~10" in r.get("error", "") and db_get("meta/companies/t_new/apps/rpa/limits/presets") == 5, f"옵저버 프리셋 수 거절 {bad!r}", r)
check(db_get("meta/companies/t_new/apps/rpa/limits/schedule") == 3, "프리셋 수를 바꿔도 자동 실행 개수는 그대로")
code, d = api("GET", "/api/companies/t_new")
check(code == 200 and d.get("parallelLimit") is None, "병렬 실행 최대 창 수: 값이 없으면 null (화면은 기본 1 = 허용 안 함)", str(d.get("parallelLimit")))
code, r = api("POST", "/api/companies/t_new/parallel", {"parallel": "4"})
check(code == 200 and r == {"cid": "t_new", "parallel": 4} and db_get("meta/companies/t_new/apps/rpa/limits/parallel") == 4, "병렬 실행 4개까지 허용", r)
for bad in ("0", "17", "2.5", "", "넷"):
    code, r = api("POST", "/api/companies/t_new/parallel", {"parallel": bad})
    check(code == 400 and "1~16" in r.get("error", "") and db_get("meta/companies/t_new/apps/rpa/limits/parallel") == 4, f"병렬 실행 최대 창 수 거절 {bad!r}", r)
check(db_get("meta/companies/t_new/apps/rpa/limits/presets") == 5, "병렬 실행 허용을 바꿔도 프리셋 수는 그대로")
code, d = api("GET", "/api/companies/t_new")
check(code == 200 and d.get("wellife") is False and d.get("wellifeAuto") is False, "웰라이프: 보통 업체는 꺼짐", str(d.get("wellife")))
code, r = api("POST", "/api/companies/t_new/features", {"wellife": True})
check(code == 200 and db_get("meta/companies/t_new/apps/rpa/features/wellife") is True, "웰라이프 실행 켜기", r)
code, d = api("GET", "/api/companies/t_new")
check(d.get("wellife") is True and d.get("wellifeAuto") is False, "켠 업체는 웰라이프")
code, r = api("POST", "/api/companies/t_new/features", {"wellife": False})
check(code == 200 and db_get("meta/companies/t_new/apps/rpa/features/wellife") is None, "끄면 자리를 지운다")
db_put("meta/companies/my_wellife", {"name": "웰라이프 시험", "stts": 0})
code, d = api("GET", "/api/companies/my_wellife")
check(code == 200 and d.get("wellife") is True and d.get("wellifeAuto") is True, "업체코드에 wellife → 늘 켜짐", str(d)[:200])
code, r = api("POST", "/api/companies/my_wellife/features", {"wellife": False})
check(code == 400 and "항상 켜져" in r.get("error", ""), "업체코드 규칙 업체는 끌 수 없다", r)
code, r = api("POST", "/api/companies/t_new/remove", {"confirm": "t_ne"})
check(code == 400 and db_get("meta/companies/t_new/stts") == 0, "업체코드를 똑같이 안 치면 삭제하지 않는다", (code, r))
code, r = api("POST", "/api/companies/t_new/remove", {"confirm": "t_new"})
check(code == 200 and db_get("meta/companies/t_new/stts") == 9 and account(boss).get("disabled") is True, "업체 삭제: stts 9, 계정 막힘")
code, r = api("POST", "/api/companies/t_new/restore", {})
check(code == 200 and db_get("meta/companies/t_new/stts") == 0 and account(boss).get("disabled") is not True, "되살림")
# 일괄 저장 (사용자 2026-10-12): 바꾼 줄을 values 로 한 번에, 하나라도 틀리면 아무것도 안 쓴다
code, r = api("POST", "/api/prices", {"values": {"logistics": "3", "hold": "2"}})
check(code == 200 and r.get("logistics") == 3 and r.get("hold") == 2 and r.get("login") == 0, "토큰 배율 여러 줄을 한 번에", r)
code, r = api("POST", "/api/prices", {"values": {"logistics": "5", "hold": "-1"}})
check(code == 400 and "토큰 배율" in r.get("error", "") and (fs_doc("meta/prices") or {}).get("logistics") == 3,
      "하나라도 틀리면(음수) 거절하고 다른 줄도 안 쓴다", r)
code, r = api("POST", "/api/prices", {"values": {}})
check(code == 400, "바꾼 줄이 없으면 거절", r)
code, r = api("POST", "/api/prices", {"values": {"logistics": ""}})
check(code == 400 and (fs_doc("meta/prices") or {}).get("logistics") == 3, "기본값은 비울 수 없다", r)
api("POST", "/api/prices", {"values": {"hold": "1"}})
# 업체 배율 (사용자 2026-10-08): prices/{cid} 에, 비우면 그 키를 지워 기본값을 따른다
code, r = api("POST", "/api/companies/t_new/prices", {"values": {"sales": "7", "hold": "4"}})
check(code == 200 and (fs_doc("prices/t_new") or {}).get("sales") == 7 and r.get("prices") == {"sales": 7, "hold": 4}
      and (fs_doc("meta/prices") or {}).get("sales") is None, "업체 배율: 그 업체 문서에만 (기본값은 그대로), 여러 줄 한 번에", r)
code, r = api("GET", "/api/companies/my_wellife/prices")
check(code == 200 and r.get("prices") == {} and r.get("wellife") is True, "업체 배율 읽기: 없으면 {}, 웰라이프 업체인지도", r)
code, r = api("POST", "/api/companies/t_new/prices", {"values": {"sales": "", "hold": ""}})
check(code == 200 and "sales" not in (fs_doc("prices/t_new") or {}) and r.get("prices") == {}, "업체 배율 비우기 = 기본값을 따름", r)
code, r = api("POST", "/api/companies/t_new/prices", {"values": {"sales": "2", "hold": "-1"}})
check(code == 400 and "토큰 배율" in r.get("error", "") and "sales" not in (fs_doc("prices/t_new") or {}),
      "업체 배율도 하나라도 틀리면 아무것도 안 쓴다", r)
code, r = api("POST", "/api/companies/nobody/prices", {"values": {"sales": "1"}})
check(code == 400 and fs_doc("prices/nobody") is None, "없는 업체에는 쓰지 않는다", r)
code, rows = api("GET", "/api/usage")
check(code == 200 and any(x["cid"] == "t_new" and x["left"] == 600 for x in rows), "통계: 업체마다 남은 토큰", str(rows)[:200])
code, r = api("GET", "/api/companies/Bad")
check(code == 404, "업체코드 꼴이 아닌 주소는 없는 요청", code)

print("=== 3-2. 휴대폰 (인증번호 중계 5단계) ===")
db_patch("meta/companies/t_phone", {"name": "휴대폰 시험", "stts": 0})
code, r = api("POST", "/api/companies/t_phone/phones", {"phoneId": "kim", "label": "김OO 휴대폰", "owner": "김OO"})
SECRETS.append(r.get("password", ""))
kim = email("t_phone", "phone-kim")
check(code == 200 and r.get("email") == kim and len(r.get("password", "")) == 24 and r.get("phoneId") == "kim",
      "휴대폰 추가: 계정(phone-<휴대폰코드>)과 비밀번호를 한 번 돌려준다", r)
check(claims(kim) == {"cid": "t_phone", "phoneId": "kim", "role": "phone"}, "휴대폰 계정 claim = cid·phoneId·role phone", claims(kim))
check(db_get("meta/companies/t_phone/phones/kim") == {"label": "김OO 휴대폰", "owner": "김OO"}, "업체의 휴대폰 목록에 이름·주인",
      db_get("meta/companies/t_phone/phones/kim"))
code, r = api("POST", "/api/companies/t_phone/phones", {"phoneId": "kim", "label": "또"})
check(code == 400 and "이미" in r.get("error", "") and db_get("meta/companies/t_phone/phones/kim/label") == "김OO 휴대폰",
      "같은 휴대폰코드를 또 추가하면 거절 (목록 이름도 그대로)", r)
for bad in ({"phoneId": "Kim!", "label": "x"}, {"phoneId": "", "label": "x"}, {"phoneId": "lee", "label": ""}):
    code, r = api("POST", "/api/companies/t_phone/phones", bad)
    check(code == 400 and not db_get(f"meta/companies/t_phone/phones/{bad['phoneId'] or 'x'}"), f"잘못된 값은 거절 ({bad})", r)
code, r = api("POST", "/api/companies/nobody/phones", {"phoneId": "kim", "label": "x"})
check(code == 400 and not account(email("nobody", "phone-kim")), "없는 업체에는 휴대폰을 못 넣는다", r)
code, d = api("GET", "/api/companies/t_phone")
ph = d.get("phones") if code == 200 else None
check(ph and [{k: v for k, v in x.items() if k != "lastSignIn"} for x in ph] == [{"phoneId": "kim", "label": "김OO 휴대폰", "owner": "김OO", "email": kim, "disabled": False}] and "lastSignIn" in ph[0],
      "상세에 휴대폰 목록 (계정 상태 함께)", ph)
check(all(u["role"] != "phone" for u in d.get("users", [])), "휴대폰 계정은 '계정' 표에 섞이지 않는다 (휴대폰 칸에)", d.get("users"))
pw_kim = SECRETS[-1]
tok = call("POST", f"{AUTH}/identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=fake",
           {"email": kim, "password": pw_kim, "returnSecureToken": True}).get("idToken")
check(bool(tok), "만든 휴대폰 계정으로 로그인된다 (앱이 하는 대로)")
code, r = api("POST", "/api/companies/t_phone/passwd", {"id": kim})
SECRETS.append(r.get("password", ""))
check(code == 200 and len(r.get("password", "")) == 24 and r.get("phone") is True, "휴대폰 계정 비밀번호 재발급", r)
code, r = api("POST", "/api/companies/t_phone/disabled", {"id": kim, "disabled": True})
check(code == 200 and account(kim).get("disabled") is True, "휴대폰 계정 사용중지")
api("POST", "/api/companies/t_phone/disabled", {"id": kim, "disabled": False})

print("=== 4. 화면 (Playwright headless) ===")
from playwright.sync_api import sync_playwright  # noqa: E402

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page()
    dialogs = []
    answer = {"yes": True}   # 확인 창에 예 / 아니오 - 시험이 잠깐 바꿀 수 있다
    page.on("dialog", lambda d: (dialogs.append(d.message), d.accept() if answer["yes"] else d.dismiss()))
    page.goto(url)
    page.wait_for_function("document.getElementById('badge')?.textContent.includes('에뮬레이터')", timeout=15000)
    check(page.text_content("#badge") == "에뮬레이터 (시험)" and "k=" not in page.url, "띠에 '에뮬레이터 (시험)', 주소창에서 비밀 값을 지운다", page.url)
    page.wait_for_selector("#companies tr[data-cid='t_new']", timeout=15000)
    cell = page.text_content("#companies tr[data-cid='t_new'] td:nth-child(2)")
    check(cell == PLAN["name"] and "1" not in dialogs and page.locator("#companies img").count() == 0,
          "업체 이름에 넣은 HTML 은 글자 그대로 (스크립트로 안 돈다)", cell)
    page.click("#companies tr[data-cid='t_new']")
    page.wait_for_function("document.querySelector('#detail table.wallet td.left')?.textContent === '600'", timeout=15000)
    check(True, "줄을 누르면 상세: 현재 토큰 600")
    # 이 시험엔 업체 웹(Hosting)이 없어 새 탭 대신 가짜 창에 넣는 주소만 본다
    page.evaluate("""() => { window.__win = { location: {}, closed: false, close() { this.closed = true; } };
      window.open = (u, t) => { window.__win.first = String(u) + '|' + String(t); return window.__win; }; }""")
    page.click("#open-dash")
    page.wait_for_function("!!window.__win.location.href", timeout=15000)
    w = page.evaluate("({ first: window.__win.first, href: window.__win.location.href, opener: window.__win.opener })")
    dash, _, tok = w["href"].partition("#t=")
    check(page.text_content("#open-dash") == "대시보드 보기" and w["first"] == "about:blank|_blank" and w["opener"] is None
          and dash.endswith("cid=t_new") and "127.0.0.1:5000" in dash and tok.count(".") == 2,
          "[대시보드 보기] 는 누른 순간 새 탭을 열고, 받은 총괄 로그인 열쇠를 # 뒤에 붙여 그 업체(?cid=) 대시보드로", str(w)[:200])
    import base64
    tok_body = json.loads(base64.urlsafe_b64decode(tok.split(".")[1] + "=="))
    check(tok_body.get("uid") == "admin-console" and tok_body.get("claims") == {"role": "super"},
          "열쇠는 관리 화면 전용 계정(admin-console)·총괄 권한", str(tok_body)[:200])
    LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "admin", "관리_기록.txt")
    logtxt = open(LOG_PATH, encoding="utf-8").read() if os.path.exists(LOG_PATH) else ""
    check("대시보드 보기 t_new" in logtxt and tok not in logtxt, "관리 기록엔 '대시보드 보기' 만, 열쇠는 안 남긴다")
    heads = [h.strip() for h in page.locator("#detail table.wallet th").all_text_contents()]
    check(heads == ["발급한 토큰", "사용한 토큰", "현재 토큰", "토큰 정보 생성"], f"토큰 정보는 표로 ({heads})")
    OLD = ("기계", "열람자", "통장", "막기", "막힘", "막을", "막았", "열기", "열림", "열었", "더하기", "더했", "삭제", "되살",
           "한 대 더", "쓰나요", "예, 씁니다", "첫 토큰", "세기만", "관리자 계정 (대시보드에 로그인할 사람)", "유저 추가")
    NEW = ("에이전트 계정도 만들기", "PC 추가", '"추가"', "사용중지", "사용중", "유저", "토큰 정보", "업체 비활성화", "다시 활성화",
           '<button id="s-add-pc">+ 추가</button>', "4. 물류대기 관리 메뉴 사용 여부", 'value="yes">예</label>', 'value="no">아니오</label>',
           "5. 최초 토큰량 설정", 'value="later" checked>나중에 설정</label>', "3. 대시보드 계정", '<button id="s-add-user">+ 추가</button>',
           "업체가 보유한 토큰 정보가 없습니다. 최초 토큰 생성시 토큰 정보가 함께 생성됩니다. 토큰이 0이하라면 모듈 실행을 막습니다.",
           "업체가 사용할 모듈을 결정합니다. 체크 해제시 업체 대시보드에서 보이지 않고, 에이전트도 실행하지 않습니다.",
           "이 업체를 비활성화 합니다. 데이터(기록, 토큰 정보 등)도 남고, 언제든지 다시 활성화 할 수 있습니다.")
    shown = page_html + page.text_content("body")
    check(not [w for w in OLD if w in shown] and all(w in shown for w in NEW),
          "화면 이름은 사용자가 고른 것 (에이전트·유저·사용중지/사용·추가·토큰 정보·업체 비활성화 - 2026-10-06)",
          ([w for w in OLD if w in shown], [w for w in NEW if w not in shown]))
    page.fill("#detail input[placeholder^='+1000']", "+50")
    page.fill("#detail input[placeholder^='비고']", "화면에서")
    page.click("#detail button:has-text('넣기')")
    page.wait_for_function("document.querySelector('#detail table.wallet td.left')?.textContent === '650'", timeout=15000)
    check(True, "화면에서 토큰 넣기 → 현재 토큰 650")
    page.fill("#detail input[aria-label='자동 실행 슬롯 수']", "4")
    page.click("#detail .row:has(input[aria-label='자동 실행 슬롯 수']) button")
    page.wait_for_function("document.querySelector(\"#detail input[aria-label='자동 실행 슬롯 수']\")?.value === '4'", timeout=10000)
    check(db_get("meta/companies/t_new/apps/rpa/limits/schedule") == 4, "화면: 업체 상세에서 자동 실행 개수 저장")
    check("옵저버에서 만들 수 있는 프리셋 수를 결정합니다. (2~10, 기본 2)" in page.text_content("#detail"), "옵저버 프리셋 수 설명")
    preset = "document.querySelector(\"#detail input[aria-label='옵저버 프리셋 수']\")"
    page.evaluate(f"{preset}.dataset.old = '1'")     # 저장하면 업체 상세를 다시 그린다 - 다시 그려졌는지 보려고
    page.fill("#detail input[aria-label='옵저버 프리셋 수']", "7")
    page.click("#detail .row:has(input[aria-label='옵저버 프리셋 수']) button")
    page.wait_for_function("document.querySelector(\"#detail input[aria-label='옵저버 프리셋 수']\")?.value === '7'", timeout=10000)
    # 다시 그려질 때까지 (새 칸에 7) - 그 전에 다음 칸을 채우면 다시 그리며 지워진다
    page.wait_for_function(f"{preset} && !{preset}.dataset.old && {preset}.value === '7'", timeout=10000)
    check(db_get("meta/companies/t_new/apps/rpa/limits/presets") == 7, "화면: 업체 상세에서 옵저버 프리셋 수 저장")
    check("1이면 허용하지 않으며 업체 화면에도 보이지 않습니다. (1~16, 기본 1)" in page.text_content("#detail"), "병렬 실행 허용 설명")
    page.fill("#detail input[aria-label='병렬 실행 최대 창 수']", "6")
    page.click("#detail .row:has(input[aria-label='병렬 실행 최대 창 수']) button")
    # 칸 값은 채우자마자 6 이라 저장을 못 기다린다 - 저장 뒤 다시 그린 제목의 허용 상태를 기다린다
    page.wait_for_function("[...document.querySelectorAll('#detail h3')].some((h) => h.textContent.includes('6개까지 허용'))", timeout=10000)
    check(db_get("meta/companies/t_new/apps/rpa/limits/parallel") == 6 and "6개까지 허용" in page.text_content("#detail"),
          "화면: 업체 상세에서 병렬 실행 허용 저장 (제목 옆에 허용 상태)")

    print("자동 업데이트 (설계 8절)")
    CID, PC = "t_new", "pc_a"
    db_put("meta/releases", {"list": {"2026_10_07-4": {"version": "2026.10.07-4", "published_at": "2026-10-07T12:00:00", "bytes": 1, "memo": "안정"},
                                      "2026_10_07-5": {"version": "2026.10.07-5", "published_at": "2026-10-07T13:00:00", "bytes": 1, "memo": "새"}},
                             "stable": "2026.10.07-4", "newest": "2026.10.07-5"})
    db_put(f"apps/rpa/live/{CID}/{PC}", {"version": {"version": "2026.10.07-4", "state": "ok"},
                                          "update": {"state": "done", "target": "2026.10.07-4", "from": "2026.10.07-3", "at": "2026-10-07T14:03:00", "backup": "2026.10.07-3"}})

    def open_company(pg, cid):
        pg.click("nav button[data-view='companies']")
        pg.wait_for_timeout(1000)   # 앞서 늦게 도착하는 상세 응답이 새 그림을 덮지 않게
        pg.evaluate("document.getElementById('detail').replaceChildren()")   # 옛 상세를 비워야 새로 그린 줄을 기다린다
        pg.click(f"#companies tr[data-cid='{cid}']")
        pg.wait_for_selector(f"#detail #pc-{PC}", timeout=15000)

    open_company(page, CID)
    heads = [h.strip() for h in page.locator("#detail table.pcs th").all_text_contents()]
    check(heads == ["PC 이름", "PC코드", "버전", "업데이트 상태", "프리셋", "업데이트"], f"PC 는 표로 - 칸이 맞춰진다 ({heads})")
    cells = [c.strip() for c in page.locator(f"#pc-{PC} td").all_text_contents()]
    check(cells[1] == PC and cells[2] == "2026.10.07-4 (안정본)" and cells[3] == "업데이트됨 10/7 14:03", f"PC 줄 칸: 코드·버전·상태 ({cells})")
    check(page.input_value(f"#pc-{PC} select.upd-ver") == "2026.10.07-4"
          and "(최신본)" in page.text_content(f"#pc-{PC} select.upd-ver option[value='2026.10.07-5']"), "판 고르기: 처음은 안정본, 최신본 표시")
    # 줄이 자연스럽게 (사용자 2026-10-08): 고르기 칸엔 버전만, 비고는 칸 아래 작은 글로. 머리·칸·단추는 한 줄
    opt = page.text_content(f"#pc-{PC} select.upd-ver option[value='2026.10.07-5']")
    check(opt == "2026.10.07-5 (최신본)" and page.text_content(f"#pc-{PC} .upd-memo") == "안정",
          f"고르기 칸은 버전만, 고른 버전의 비고는 아래에 ({opt!r}, {page.text_content(f'#pc-{PC} .upd-memo')!r})")
    lines = lambda sel: page.evaluate(f"""[...document.querySelectorAll("{sel}")].map((el) => {{ const r = document.createRange();
      r.selectNodeContents(el); return r.getClientRects().length; }})""")
    cells_sel = f"#pc-{PC} td:not(:last-child):not(:has(button))"   # 단추만 든 칸(프리셋)은 단추 쪽에서 잰다 (Range 가 단추를 두 상자로 센다)
    check(set(lines("#detail table.pcs th") + lines(cells_sel) + lines(f"#pc-{PC} button")) == {1},
          f"PC 표 머리·칸·단추가 한 줄 ({lines('#detail table.pcs th')}, {lines(cells_sel)}, {lines(f'#pc-{PC} button')})")
    if os.environ.get("SHOT_DIR"): page.locator("#detail .sec").first.screenshot(path=os.path.join(os.environ["SHOT_DIR"], "pc_row.png"))
    page.select_option(f"#pc-{PC} select.upd-ver", "2026.10.07-5")
    check(page.text_content(f"#pc-{PC} .upd-memo") == "새", "다른 버전을 고르면 그 버전의 비고")
    dialogs.clear()   # 위쪽 page.on("dialog") 가 이미 모두 받아들인다
    page.click(f"#pc-{PC} button.upd-go")
    page.wait_for_timeout(800)
    cmd = [v for v in (db_get(f"apps/rpa/commands/{CID}/{PC}") or {}).values() if v.get("type") == "update"]
    check(dialogs == [f"{CID} / {PC}을(를) 2026.10.07-5 버전으로 업데이트하시겠습니까? 오토파일럿 실행이 끝나면 바로 적용됩니다."], f"확인 창 ({dialogs})")
    check(len(cmd) == 1 and cmd[0]["args"] == {"version": "2026.10.07-5"} and cmd[0]["by"] == "admin-tool" and cmd[0]["state"] == "queued"
          and cmd[0]["expires_at"] - cmd[0]["created_at"] == 600, f"update 명령 ({cmd})")
    # 누른 뒤 그 줄만 따라간다 (사용자 2026-10-08): 명령 보냄 → PC 상태 → 끝나면 단추가 풀린다
    status_cell = f"#pc-{PC} td:nth-child(4)"
    check("명령 보냄 - PC 응답 기다리는 중" in page.text_content(status_cell) and page.is_disabled(f"#pc-{PC} button.upd-go")
          and page.is_disabled(f"#pc-{PC} button.upd-back"), f"누르면 바로 '명령 보냄'·단추 잠금 ({page.text_content(status_cell)})")
    ckey = [k for k, v in (db_get(f"apps/rpa/commands/{CID}/{PC}") or {}).items() if v.get("type") == "update"][0]
    t0 = int(time.time())
    db_patch(f"apps/rpa/commands/{CID}/{PC}/{ckey}", {"state": "done", "started_at": t0, "ended_at": t0, "result": "업데이트를 예약했습니다"})
    db_put(f"apps/rpa/live/{CID}/{PC}/update", {"state": "downloading", "target": "2026.10.07-5", "from": "2026.10.07-4",
                                                "at": datetime.datetime.now().isoformat(timespec="seconds"), "backup": "2026.10.07-3"})
    page.wait_for_function(f"document.querySelector('{status_cell}')?.textContent.includes('업데이트 받는 중')", timeout=10000)
    check(page.is_disabled(f"#pc-{PC} button.upd-go"), "새로 고치지 않아도 그 줄이 'PC 상태' 를 따라간다 (받는 중엔 잠금)")
    db_put(f"apps/rpa/live/{CID}/{PC}/update", {"state": "done", "target": "2026.10.07-5", "from": "2026.10.07-4",
                                                "at": datetime.datetime.now().isoformat(timespec="seconds"), "backup": "2026.10.07-3"})
    page.wait_for_function(f"document.querySelector('{status_cell}')?.textContent.includes('업데이트됨')", timeout=10000)
    check(not page.is_disabled(f"#pc-{PC} button.upd-go"), "끝나면 단추가 다시 풀린다")
    old = int(time.time()) - 700
    db_put(f"apps/rpa/commands/{CID}/{PC}/zz_old", {"type": "update", "args": {"version": "2026.10.07-5"}, "by": "admin-tool",
                                                   "created_at": old, "expires_at": old + 600, "state": "queued"})
    open_company(page, CID)
    check("PC가 응답하지 않습니다" in page.text_content(status_cell) and not page.is_disabled(f"#pc-{PC} button.upd-go"),
          f"10분 안에 PC 가 안 받으면 '응답하지 않습니다' ({page.text_content(status_cell)})")
    db_patch(f"apps/rpa/commands/{CID}/{PC}/zz_old", {"state": "failed", "started_at": int(time.time()), "result": "이미 최신 업데이트를 사용하고 있습니다"})
    open_company(page, CID)
    check("명령 실패: 이미 최신 업데이트를 사용하고 있습니다" in page.text_content(status_cell), f"PC 가 거절하면 그 까닭 ({page.text_content(status_cell)})")
    call("DELETE", f"{DB}/apps/rpa/commands/{CID}/{PC}/zz_old.json?ns={NS}", None, OWNER)
    open_company(page, CID)
    check(page.is_visible(f"#pc-{PC} button.upd-back") and "2026.10.07-3" in page.text_content(f"#pc-{PC} button.upd-back"), "보관본이 있으면 되돌리기 단추")
    page.click(f"#pc-{PC} button.upd-back")
    page.wait_for_timeout(800)
    check(any(v.get("type") == "rollback" and v["by"] == "admin-tool" and v["state"] == "queued"
              for v in (db_get(f"apps/rpa/commands/{CID}/{PC}") or {}).values()), "되돌리기 명령")
    code, r = api("POST", f"/api/companies/{CID}/pcs/{PC}/update", {"version": "2026.10.07-9"})
    check(code == 400, "올라가 있지 않은 판은 거절", r)
    db_put(f"apps/rpa/live/{CID}/{PC}/update", {"state": "waiting", "target": "2026.10.07-5", "from": "2026.10.07-4", "at": "2026-10-07T15:00:00", "backup": "2026.10.07-3"})
    open_company(page, CID)
    check(page.is_disabled(f"#pc-{PC} button.upd-go") and page.is_disabled(f"#pc-{PC} button.upd-back")
          and "업데이트 대기 중" in page.text_content(f"#pc-{PC}"), "진행 중이면 두 단추 잠금")
    check(page.text_content(f"#pc-{PC} button.upd-back") == "이전 버전으로 되돌리기",
          f"진행 중엔 되돌리기 단추에 버전을 안 붙인다 (보관본은 끝나야 바뀐다) ({page.text_content(f'#pc-{PC} button.upd-back')})")
    db_put(f"apps/rpa/live/{CID}/{PC}/version", {"version": "2026.10.07-5", "state": "ok"})
    open_company(page, CID)
    check(page.input_value(f"#pc-{PC} select.upd-ver") == "2026.10.07-5", "버전 고르기: 지금 버전이 있으면 지금 버전")
    call("DELETE", f"{DB}/apps/rpa/live/{CID}/{PC}/version.json?ns={NS}", None, OWNER)
    open_company(page, CID)
    cells = [c.strip() for c in page.locator(f"#pc-{PC} td").all_text_contents()]
    check(cells[2] == "버전 정보 없음" and page.input_value(f"#pc-{PC} select.upd-ver") == "2026.10.07-4",
          f"버전을 모르면 '버전 정보 없음'·안정본 ({cells[2]})")
    db_put(f"apps/rpa/live/{CID}/{PC}/version", {"version": "2026.10.07-4", "state": "ok"})
    page.click("#releases-open")
    page.click("#releases button[data-stable='2026.10.07-5']")
    page.wait_for_timeout(800)
    check(db_get("meta/releases/stable") == "2026.10.07-5", "판 목록에서 안정본으로 지정")
    check("안정본 지정 2026.10.07-5" in open(LOG, encoding="utf-8").read(), "관리 기록에 남는다")

    print("프리셋 가져오기·넣어 주기·되돌리기 (설계 2026-10-19 4.1절)")
    import tempfile
    CMDS = f"apps/rpa/commands/{CID}/{PC}"
    REC = {"version": 1, "start_url": "https://mall.example/login", "viewport": {"width": 1280, "height": 800},
           "steps": [{"id": 1, "kind": "click", "sel": "#go"}, {"id": 2, "kind": "type", "sel": "#q", "value": "검색어"}]}
    FILE = {"kind": "autopilot-preset", "version": 1, "exported_at": "2026-10-19T10:00:00", "from": {"cid": CID, "pcId": PC, "no": 1},
            "no": 1, "name": "네이버 스마트스토어", "code": "001", "record": REC}
    db_put(f"apps/rpa/live/{CID}/{PC}/presets", [
        {"no": 1, "name": "네이버 스마트스토어", "code": "001", "steps": 2, "saved_at": "2026-10-19T09:00:00", "has_login": True, "on": True, "backup": False},
        {"no": 2, "name": "쿠팡", "code": "002", "steps": 5, "saved_at": "2026-10-19T09:00:00", "has_login": False, "on": False, "backup": True}])
    db_put(f"apps/rpa/live/{CID}/{PC}/preset_transfer", 1)
    open_company(page, CID)
    box = f"#pc-{PC}-presets"
    page.click(f"#pc-{PC} button.preset-open")
    page.wait_for_selector(box, timeout=10000)
    rows = [r.strip() for r in page.locator(f"{box} tr.preset").all_text_contents()]
    check(len(rows) == 2 and all(w in rows[0] for w in ("1", "네이버 스마트스토어", "001", "2")) and all(w in rows[1] for w in ("2", "쿠팡", "002", "5")),
          f"[프리셋] 을 누르면 그 PC 아래 프리셋마다 번호·이름·사이트코드·단계 수 ({rows})")
    check(page.locator(f"{box} button.preset-export").count() == 2 and page.locator(f"{box} button.preset-restore").count() == 1
          and page.get_attribute(f"{box} button.preset-restore", "data-no") == "2", "프리셋마다 [가져오기], 보관이 있는 칸에만 [되돌리기]")
    check("가져온 파일에는 아이디·비밀번호가 없습니다. 검색어 등 입력한 값은 포함될 수 있습니다." in page.text_content(box), "안내 한 줄")
    dialogs.clear()
    with page.expect_download(timeout=30000) as dl:
        page.click(f"{box} button.preset-export[data-no='1']")
        page.wait_for_timeout(800)
        exp = [(k, v) for k, v in (db_get(CMDS) or {}).items() if v.get("type") == "export_preset"]
        tid = exp[0][1]["args"].get("tid", "") if exp else ""
        check(len(exp) == 1 and exp[0][1]["args"] == {"tid": tid, "nos": [1], "with_phone": False} and exp[0][1]["by"] == "admin-tool"
              and re.fullmatch(r"[a-z0-9]{20}", tid) and exp[0][1]["state"] == "queued", f"[가져오기] → export_preset 명령 (tid 20자, nos [1], 휴대폰 없이) ({exp})")
        now_ms = int(time.time() * 1000)   # 에이전트 대신 전송 자리에 올리고 명령을 끝낸다
        db_put(f"apps/rpa/transfers/{CID}/{tid}", {"by": "admin-tool", "from_pc": PC, "created_at": now_ms, "expires_at": now_ms + 6 * 3600 * 1000, "presets": [FILE]})
        db_patch(f"{CMDS}/{exp[0][0]}", {"state": "done", "started_at": int(time.time()), "ended_at": int(time.time()), "result": "프리셋 1개를 보냈습니다."})
    got = dl.value
    with open(got.path(), encoding="utf-8") as f:
        content = json.load(f)
    check(got.suggested_filename == f"프리셋_{CID}_{PC}_1.json" and content == FILE, f"파일로 내려받는다 (이름·내용) ({got.suggested_filename})")
    check(db_get(f"apps/rpa/transfers/{CID}/{tid}") is None, "내려받은 뒤 전송 자리는 지운다")
    text = open(LOG, encoding="utf-8").read()
    check(f"프리셋 가져오기 {CID}/{PC} 1" in text and "mall.example" not in text and "검색어" not in text, "관리 기록에 가져오기 한 줄, 기록 내용은 없다")
    code, r = api("GET", f"/api/companies/{CID}/transfers/{tid}")
    check(code == 200 and r == {"pending": True}, "없는 전송은 '아직' (pending)", (code, r))
    # 넣어 주기 - 200 KB 기록 (Review Focus 4: 요청 상한 64 KB 를 넘는다)
    BIG = dict(FILE, no=2, name="큰 기록", code="003", record=dict(REC, steps=[{"id": i, "kind": "click", "sel": f"#b{i}", "text": "x" * 100} for i in range(1, 1801)]))
    tmp = tempfile.mkdtemp()
    big_path = os.path.join(tmp, "big.json")
    with open(big_path, "w", encoding="utf-8") as f:
        json.dump(BIG, f, ensure_ascii=False)
    check(os.path.getsize(big_path) > 200 * 1024, f"시험 파일은 200 KB 넘김 ({os.path.getsize(big_path)})")
    page.set_input_files(f"{box} input[type=file]", big_path)
    page.wait_for_function(f"document.querySelector('{box} input.preset-slot')?.value === '2'", timeout=10000)
    check(True, "파일을 고르면 칸 번호 기본값 = 파일의 번호")
    page.fill(f"{box} input.preset-slot", "3")
    dialogs.clear()
    page.click(f"{box} button.preset-import")
    page.wait_for_timeout(1500)
    check(dialogs == ["프리셋 3을(를) 이 파일로 변경합니다. 기록이 있으면 덮어쓰며 이전 기록은 PC에 보관됩니다. 진행하시겠습니까?"], f"넣어 주기 확인 창 ({dialogs})")
    imp = [(k, v) for k, v in (db_get(CMDS) or {}).items() if v.get("type") == "import_preset"]
    tid2 = imp[0][1]["args"].get("tid", "") if imp else ""
    check(len(imp) == 1 and imp[0][1]["args"] == {"tid": tid2, "slots": [3]} and re.fullmatch(r"[a-z0-9]{20}", tid2), f"import_preset 명령 (slots [3]) ({imp and imp[0][1]['args'].get('slots')})")
    tr = db_get(f"apps/rpa/transfers/{CID}/{tid2}") or {}
    check(tr.get("presets", [None])[0] == BIG and tr.get("by") == "admin-tool" and tr.get("from_pc") == "admin"
          and tr.get("expires_at", 0) - tr.get("created_at", 0) == 6 * 3600 * 1000, "전송 자리에 그 파일 (by admin-tool, 6시간)", {k: v for k, v in tr.items() if k != "presets"})
    db_patch(f"{CMDS}/{imp[0][0]}", {"state": "done", "started_at": int(time.time()), "ended_at": int(time.time()), "result": "총괄 계정이 프리셋 3을(를) 변경하였습니다. (이전 기록 보관)"})
    page.wait_for_function("document.getElementById('flash').textContent.includes('변경하였습니다')", timeout=15000)
    check("bad" not in (page.get_attribute("#flash", "class") or ""), "PC 가 끝내면 그 결과를 알린다")
    text = open(LOG, encoding="utf-8").read()
    check(f"프리셋 넣어 주기 {CID}/{PC} 3" in text and "#b1799" not in text, "관리 기록에 넣어 주기 한 줄, 파일 내용은 없다")
    # 비밀번호가 든 파일은 올리기 전에 거절 (서버에도 남지 않는다)
    for label, bad in (("PW 키", dict(FILE, PW="secret-pw-value")),
                       ("값이 든 비밀번호 단계", dict(FILE, record=dict(REC, steps=[{"id": 1, "kind": "secret", "value": "hunter2-pw"}])))):
        bad_path = os.path.join(tmp, f"bad_{label}.json")   # 같은 이름을 다시 고르면 change 가 안 난다
        with open(bad_path, "w", encoding="utf-8") as f:
            json.dump(bad, f, ensure_ascii=False)
        page.fill(f"{box} input.preset-slot", "")
        page.set_input_files(f"{box} input[type=file]", bad_path)
        page.wait_for_function(f"document.querySelector('{box} input.preset-slot')?.value === '1'", timeout=10000)   # 파일을 다 읽은 뒤
        page.click(f"{box} button.preset-import")
        page.wait_for_function("!document.getElementById('flash').classList.contains('hide') && document.getElementById('flash').classList.contains('bad')", timeout=10000)
        tr_all = json.dumps(db_get(f"apps/rpa/transfers/{CID}") or {}, ensure_ascii=False)
        check("비밀번호" in page.text_content("#flash") and len([v for v in (db_get(CMDS) or {}).values() if v.get("type") == "import_preset"]) == 1
              and "secret-pw-value" not in tr_all and "hunter2-pw" not in tr_all, f"{label}가 든 파일은 거절 (명령·전송 없음) ({page.text_content('#flash')})")
        page.evaluate("document.getElementById('flash').classList.add('hide')")
    for label, body in (("칸 번호 41", {"file": FILE, "slot": 41}), ("칸 번호 글자", {"file": FILE, "slot": "셋"}), ("파일 아님", {"file": "x", "slot": 1})):
        code, r = api("POST", f"/api/companies/{CID}/pcs/{PC}/presets/import", body)
        check(code == 400, f"넣어 주기 거절: {label}", (code, r))
    check(len([v for v in (db_get(CMDS) or {}).values() if v.get("type") == "import_preset"]) == 1, "거절된 것은 명령을 만들지 않는다")
    dialogs.clear()
    page.click(f"{box} button.preset-restore[data-no='2']")
    page.wait_for_timeout(1000)
    rst = [v for v in (db_get(CMDS) or {}).values() if v.get("type") == "restore_preset"]
    check(dialogs == ["프리셋 2을(를) 이전 기록으로 되돌리시겠습니까?"] and len(rst) == 1 and rst[0]["args"] == {"nos": [2]},
          f"[되돌리기] → restore_preset 명령 ({dialogs}, {rst and rst[0]['args']})")
    check(f"프리셋 되돌리기 {CID}/{PC} 2" in open(LOG, encoding="utf-8").read(), "관리 기록에 되돌리기 한 줄")
    code, d = api("GET", f"/api/companies/{CID}")
    pcrow = next((x for x in d.get("pcs", []) if x["pcId"] == PC), {}) if code == 200 else {}
    check([x["no"] for x in pcrow.get("presets") or []] == [1, 2], "업체 상세의 PC 줄에 프리셋 요약 (live.presets)", str(pcrow)[:200])
    call("DELETE", f"{DB}/apps/rpa/transfers/{CID}.json?ns={NS}", None, OWNER)

    print("화면 다듬기 (사용자 2026-10-07)")
    check("지금은 기본값" not in page.text_content("#detail"), "자동 실행 개수: '지금은 기본값' 글 없음")
    hold0 = page.is_checked("#detail input[data-mod='Hold']")
    page.evaluate("document.getElementById('flash').classList.add('hide')")
    before = db_get(f"meta/companies/{CID}/apps/rpa/modules") or {}
    page.click("#detail input[data-mod='Hold']")
    page.wait_for_timeout(800)
    check((db_get(f"meta/companies/{CID}/apps/rpa/modules") or {}) == before, "모듈 정책: 체크만으로는 안 바뀐다 ([적용] 을 눌러야)")
    page.click("#detail button.mod-apply")
    page.wait_for_selector("#detail .mod-ok:not(.hide)", timeout=5000)
    mods = db_get(f"meta/companies/{CID}/apps/rpa/modules") or {}
    check(page.text_content("#detail .mod-ok").strip() == "반영되었습니다." and (mods.get("Hold") is False) == hold0
          and "hide" in (page.get_attribute("#flash", "class") or ""), f"[적용] → 제목 옆 초록 '반영되었습니다.' (아래 알림 없음) ({mods})")
    page.wait_for_selector("#detail .mod-ok.hide", state="attached", timeout=5000)
    check(True, "초록 글은 잠깐 뒤 사라진다")
    check("자동 실행 슬롯 수" in page.text_content("#detail") and "자동 실행 개수" not in page.text_content("#detail"), "자동 실행 슬롯 수 (이름)")
    check("예약 실행, 반복 실행 슬롯을 몇 개까지 열어줄 지 결정합니다. (0~12, 기본 2)" in page.text_content("#detail"), "자동 실행 슬롯 수 설명")
    page.click("#detail input[data-mod='Hold']")   # 되돌려 둔다
    page.click("#detail button.mod-apply")
    page.wait_for_timeout(800)
    wl = page.locator("#detail input[data-feature='wellife']")
    check(wl.count() == 1 and not wl.is_checked() and not wl.is_disabled(), "모듈 정책에 '웰라이프 실행' 체크 (보통 업체는 꺼짐)")
    page.wait_for_selector("#detail .mod-ok.hide", state="attached", timeout=5000)   # 앞 [적용] 의 초록 글이 사라진 뒤여야 새 것을 기다린다
    wl.check(); page.click("#detail button.mod-apply"); page.wait_for_selector("#detail .mod-ok:not(.hide)", timeout=5000)
    check(db_get(f"meta/companies/{CID}/apps/rpa/features/wellife") is True, "[적용] 으로 웰라이프 실행을 켠다")
    open_company(page, CID)
    check(page.is_disabled("#detail input[data-mod='Logistics']") and "웰라이프 업체는 쓰지 않음" in page.text_content("#detail .sec:has(.mod-apply)"),
          "웰라이프 업체: 물류관리·운송장 체크 잠김")
    check(not page.is_disabled("#detail input[data-mod='InvoiceSend']") and "운송장번호 전송" in page.text_content("#detail .sec:has(.mod-apply)"),
          "모듈 정책에 '운송장번호 전송' 체크 (웰라이프 업체도 쓴다 - 잠기지 않음)")
    page.locator("#detail input[data-feature='wellife']").uncheck(); page.click("#detail button.mod-apply"); page.wait_for_timeout(800)
    check(db_get(f"meta/companies/{CID}/apps/rpa/features/wellife") is None, "다시 끈다")
    api("POST", f"/api/companies/{CID}/tokens", {"amount": 1500, "memo": "보기 시험"})
    api("POST", f"/api/companies/{CID}/tokens", {"amount": -50, "memo": "보기 시험 빼기"})
    open_company(page, CID)
    heads = [h.strip() for h in page.locator("#detail table.grants th").all_text_contents()]
    check(heads == ["날짜", "토큰량", "비고"], f"토큰 내역 머리 ({heads})")
    amt = page.evaluate("""[...document.querySelectorAll('#detail table.grants td.num')].map((td) => [td.textContent.trim(), getComputedStyle(td).color])""")
    good, bad = page.evaluate("[getComputedStyle(document.body).getPropertyValue('--good').trim(), getComputedStyle(document.body).getPropertyValue('--bad').trim()]")
    plus = [c for t, c in amt if t == "+1,500"]
    minus = [c for t, c in amt if t == "-50"]
    check(plus and minus and plus[0] != minus[0] and plus[0] != page.evaluate("getComputedStyle(document.body).color"),
          f"토큰량: 1000 단위 콤마, + 초록·- 빨강 ({amt}, good {good}, bad {bad})")
    sec = page.evaluate("""[...document.querySelectorAll('#detail .sec')].map((s) => {
        const c = getComputedStyle(s); return [parseFloat(c.borderLeftWidth), c.backgroundColor, c.borderTopColor, parseFloat(c.borderTopLeftRadius)]; })""")
    card = page.evaluate("getComputedStyle(document.getElementById('detail')).backgroundColor")
    row_line = page.evaluate("getComputedStyle(document.querySelector('#detail table td')).borderBottomColor")
    check(len(sec) >= 6 and all(w >= 1 and bg != card and r > 0 for w, bg, _, r in sec) and sec[1][2] != row_line and sec[-1][2] != sec[1][2],
          f"상세 항목마다 상자 (바탕이 카드와 다르고, 테두리는 표 줄보다 진하게, 비활성화는 빨간 테두리) ({sec}, card {card}, row {row_line})")
    crow = page.text_content(f"#companies tr[data-cid='{CID}']")
    check("현재 토큰" in page.text_content("table:has(#companies) thead") and re.search(r"\d,\d{3}", crow), f"업체 표: 현재 토큰, 1000 단위 콤마 ({crow})")
    ph = page.get_attribute("#detail .sec.danger input", "placeholder")
    check(ph == CID, f"업체 비활성화 칸 안내 글은 업체코드만 (길면 잘림) ({ph})")
    nav = page.text_content("nav")
    check("신규 업체 등록" in nav and "토큰 배율·통계" in nav, f"위 메뉴 글 ({nav})")
    check(page.text_content("#releases-open").strip() == "버전 목록", "버전 목록 단추")
    heads = [h.strip() for h in page.locator("#releases th").all_text_contents()]
    check(heads[:5] == ["버전", "업데이트 날짜", "크기(MB)", "비고", "버전 특이사항"], f"버전 목록 머리 ({heads})")
    gap = page.evaluate(f"""(() => {{ const s = document.querySelector('#pc-{PC} select.upd-ver').getBoundingClientRect(),
        b = document.querySelector('#pc-{PC} button.upd-go').getBoundingClientRect(); return b.left - s.right; }})()""")
    check(6 <= gap <= 12, f"PC 줄 고르기·단추 사이가 아래 줄처럼 8px 남짓 ({gap}px)")
    prefs = os.path.join(ADMIN, "admin_prefs.json")
    prefs_before = open(prefs, encoding="utf-8").read() if os.path.exists(prefs) else None
    try:
        theme = lambda: page.evaluate("document.documentElement.dataset.theme || ''")
        bg = lambda: page.evaluate("getComputedStyle(document.body).backgroundColor")
        t0, bg0 = theme(), bg()
        page.click("#theme")
        page.wait_for_timeout(500)
        t1 = theme()
        check(t1 in ("light", "dark") and t1 != t0 and bg() != bg0, f"[테마] 단추로 밝게/어둡게 ({t0!r} → {t1!r})")
        check(page.text_content("#theme").strip() == ("☀ 밝게" if t1 == "dark" else "☾ 어둡게"), "단추 글은 바꿀 쪽")
        page.reload()
        page.wait_for_function(f"document.documentElement.dataset.theme === '{t1}'", timeout=10000)
        check(True, "다시 열어도 고른 테마 (포트가 바뀌어도 - 관리 도구 옆 파일에 남긴다)")
    finally:
        if prefs_before is None:
            if os.path.exists(prefs):
                os.remove(prefs)
        else:
            open(prefs, "w", encoding="utf-8").write(prefs_before)

    page.click("nav button[data-view='setup']")
    page.fill("#s-tok-amount", "100000")
    page.focus("#s-tok-memo")
    shown = page.input_value("#s-tok-amount")
    page.focus("#s-tok-amount")
    check(shown == "100,000" and page.input_value("#s-tok-amount") == "100000", f"최초 토큰량: 칸을 벗어나면 콤마, 다시 들어오면 콤마 없이 ({shown})")
    check(page.get_attribute("#s-tok-memo", "placeholder").startswith("비고"), "최초 토큰량 옆 칸은 비고")
    page.fill("#s-tok-amount", "")
    page.fill("#s-cid", "t_ui")
    page.fill("#s-name", "화면 업체")
    page.fill("#s-pcs .pc-id", "pc_ui")
    page.fill("#s-pcs .pc-label", "화면 PC")
    page.fill("#s-users .acct:nth-child(1) .u-id", "ui_admin")
    page.fill("#s-users .acct:nth-child(1) .u-name", "담당")
    page.click("#s-add-user"); page.click("#s-add-user")
    roles = [page.input_value(f"#s-users .acct:nth-child({i}) .u-role") for i in (1, 2, 3)]
    check(roles == ["admin", "viewer", "viewer"], f"계정 줄마다 역할 - 첫 줄은 관리자, + 추가 한 줄은 유저로 시작 ({roles})")
    page.fill("#s-users .acct:nth-child(2) .u-id", "ui_boss2")
    page.select_option("#s-users .acct:nth-child(2) .u-role", "admin")
    page.fill("#s-users .acct:nth-child(3) .u-id", "ui_view")
    page.check("input[name=tok][value=later]")
    page.click("#s-make")
    page.wait_for_function("document.getElementById('flash')?.textContent.includes('물류대기')", timeout=15000)
    check(db_get("meta/companies/t_ui") is None, "물류대기 사용 여부를 안 고르면 빨간 알림, 아무것도 안 만든다")
    page.check("input[name=hold][value=yes]")
    page.click("#s-make")
    page.wait_for_selector("#setup-result:not(.hide) .secret pre", timeout=30000)
    sent = page.text_content("#setup-result .secret pre")
    seen = re.findall(r"비밀번호: (\S{24})", sent)
    SECRETS.extend(seen)
    check(page.text_content("#setup-result h2") == "모두 등록하였습니다." and "관리자  업체코드: t_ui   아이디: ui_admin" in sent
          and "관리자  업체코드: t_ui   아이디: ui_boss2" in sent and "유저  업체코드: t_ui   아이디: ui_view" in sent
          and "업체코드: t_ui   PC코드: pc_ui" in sent and len(seen) == 4 and f"https://{PROJECT}.web.app" in sent,
          "다 만들면 고객에게 보낼 정보 (대시보드 주소·관리자 둘·유저·에이전트 계정)", sent)
    check(claims(email("t_ui", "ui_admin")) == {"cid": "t_ui", "role": "admin"} and claims(email("t_ui", "ui_boss2")) == {"cid": "t_ui", "role": "admin"}
          and claims(email("t_ui", "ui_view")) == {"cid": "t_ui", "role": "viewer"} and (db_get("meta/companies/t_ui/apps/rpa/modules") or {}) == {},
          "화면으로 만든 업체: 고른 역할대로 관리자 둘·유저 하나, 물류대기 씀 (정책 없음)")

    page.click("nav button[data-view='rates']")
    page.wait_for_selector("#rates tr", timeout=15000)
    groups = [g.strip() for g in page.locator("#rates tr.grp").all_text_contents()]
    check(groups == ["ACTOR 오토파일럿", "PROCESS 오토파일럿", "PROCESS 오토파일럿 · 웰라이프 업체", "그 밖"],
          f"토큰 배율: ACTOR 오토파일럿·PROCESS·웰라이프·그 밖으로 나눔 (사용자 2026-10-08) ({groups})")
    names = [t.strip() for t in page.locator("#rates tr[data-key] td:first-child").all_text_contents()]
    check("사이트 수집" in names and not any("쇼핑몰" in n for n in names) and "웰라이프 SAP 연동관리" in names
          and "웰라이프 WMS 이관관리" in names, f"사이트 수집 이름·웰라이프 모듈 줄 ({names})")
    if os.environ.get("SHOT_DIR"): page.locator("#view-rates .card").first.screenshot(path=os.path.join(os.environ["SHOT_DIR"], "rates_base.png"))
    # 줄마다 [저장] 대신 표 아래 [저장] 하나 (사용자 2026-10-12) - 바꾼 줄만 한 번에, 바꾼 줄은 표시
    check(page.locator("#rates button").count() == 0 and page.is_disabled("#rates-save"), "줄마다 단추 없음, 바뀐 게 없으면 [저장] 잠김")
    rate = page.locator("#rates tr[data-key='sales']")
    rate.locator("input").fill("2")
    page.locator("#rates tr[data-key='hold'] input").fill("3")
    check(not page.is_disabled("#rates-save") and "2개" in page.text_content("#rates-save")
          and page.locator("#rates tr.changed").count() == 2, f"바꾼 줄 표시 + 단추에 개수 ({page.text_content('#rates-save')})")
    page.click("#rates-save")
    page.wait_for_function("document.getElementById('flash')?.textContent.includes('배율')", timeout=15000)
    check((fs_doc("meta/prices") or {}).get("sales") == 2 and (fs_doc("meta/prices") or {}).get("hold") == 3, "두 줄을 한 번에 저장 (sales 2, hold 3)")
    page.wait_for_function("document.getElementById('rates-save')?.textContent === '저장' && !document.querySelector('#rates tr.changed')", timeout=15000)
    page.locator("#rates tr[data-key='hold'] input").fill("-1")
    page.click("#rates-save")
    page.wait_for_function("document.getElementById('flash')?.textContent.includes('0 이상의 정수')", timeout=15000)
    check((fs_doc("meta/prices") or {}).get("hold") == 3, "틀린 값이면 알리고 저장하지 않는다")
    page.locator("#rates tr[data-key='hold'] input").fill("1")
    page.click("#rates-save")
    page.wait_for_function("document.getElementById('flash')?.textContent.includes('물류대기 관리 1')", timeout=15000)
    page.wait_for_function("document.getElementById('rates-save')?.textContent === '저장' && !document.querySelector('#rates tr.changed')", timeout=15000)
    check((fs_doc("meta/prices") or {}).get("hold") == 1, "고쳐서 다시 저장하면 들어간다 (hold 1)")
    # 업체를 고르면 기본값 옆에 그 업체 칸 - 넣으면 그 업체만, 비우면 기본값을 따름
    page.select_option("#rate-cid", "t_new")
    page.wait_for_selector("#rates tr[data-key='sales'] input[placeholder='2']", timeout=15000)
    groups = [g.strip() for g in page.locator("#rates tr.grp").all_text_contents()]
    check(groups == ["ACTOR 오토파일럿", "PROCESS 오토파일럿", "그 밖"], f"보통 업체는 웰라이프 묶음 없음 ({groups})")
    rate = page.locator("#rates tr[data-key='sales']")
    check(rate.locator("td").nth(1).text_content().strip() == "2" and rate.locator("input").input_value() == "",
          "업체 칸: 기본값 2 가 보이고 업체 칸은 비어 있다 (따로 정한 값 없음)")
    rate.locator("input").fill("9")
    page.click("#rates-save")
    page.wait_for_function("document.querySelector(\"#rates tr[data-key='sales']\")?.classList.contains('own')", timeout=15000)
    if os.environ.get("SHOT_DIR"): page.locator("#view-rates .card").first.screenshot(path=os.path.join(os.environ["SHOT_DIR"], "rates_company.png"))
    check((fs_doc("prices/t_new") or {}).get("sales") == 9 and (fs_doc("meta/prices") or {}).get("sales") == 2
          and page.locator("#rates tr[data-key='sales'] td").nth(3).text_content() == "이 업체에만 적용", "업체 배율 저장: 그 업체만 9, 비고 칸에 '이 업체에만 적용'")
    heads = [h.strip() for h in page.locator("#rates-head th").all_text_contents()]
    check(heads == ["모듈", "기본값", "이 업체", "비고"], f"업체 배율 표 머리에 비고 칸 (사용자 2026-10-12) ({heads})")
    rate.locator("input").fill("")
    page.click("#rates-save")
    page.wait_for_function("!document.querySelector(\"#rates tr[data-key='sales']\")?.classList.contains('own')", timeout=15000)
    check("sales" not in (fs_doc("prices/t_new") or {}), "비우고 저장하면 기본값을 따른다")
    page.locator("#rates tr[data-key='hold'] input").fill("5")
    answer["yes"], dialogs[:] = False, []
    page.select_option("#rate-cid", "")
    answer["yes"] = True
    check(page.input_value("#rate-cid") == "t_new" and page.locator("#rates tr.changed").count() == 1
          and any("저장하지 않은" in m for m in dialogs), f"저장 안 한 값이 있으면 업체를 바꾸기 전에 묻는다 (취소하면 그대로) ({dialogs})")
    page.locator("#rates tr[data-key='hold'] input").fill("")
    page.select_option("#rate-cid", "my_wellife")
    page.wait_for_function("[...document.querySelectorAll('#rates tr.grp')].some((g) => g.textContent.includes('웰라이프'))", timeout=15000)
    keys = page.evaluate("[...document.querySelectorAll('#rates tr[data-key]')].map((r) => r.dataset.key)")
    if os.environ.get("SHOT_DIR"): page.locator("#view-rates .card").first.screenshot(path=os.path.join(os.environ["SHOT_DIR"], "rates_wellife.png"))
    check("wellife_sap" in keys and "logistics" not in keys and "login" in keys,
          f"웰라이프 업체: PROCESS 는 로그인 + 웰라이프 모듈 (업체 웹과 같은 다섯) ({keys})")
    page.select_option("#rate-cid", "")
    page.wait_for_function("document.querySelectorAll('#rates tr.grp').length === 4", timeout=15000)
    check(page.locator("#usage tr", has_text="t_new").count() == 1, "통계 표에 업체가 나온다")
    rh = [h.strip() for h in page.locator("#view-rates table").first.locator("th").all_text_contents()]
    uh = [h.strip() for h in page.locator("#view-rates table").nth(1).locator("th").all_text_contents()]
    check("키" not in rh and rh[:2] == ["모듈", "배율"], f"토큰 배율 표: 키 칸 없음 ({rh})")
    check("현재 토큰" in uh and "이번 달 사용한 토큰" in uh, f"통계 표 머리 ({uh})")

    print("휴대폰 (5단계)")
    page.click("nav button[data-view='companies']")
    page.wait_for_timeout(1000)
    page.evaluate("document.getElementById('detail').replaceChildren()")
    page.click("#companies tr[data-cid='t_phone']")
    page.wait_for_selector("#detail #phone-kim", timeout=15000)
    cells = [c.strip() for c in page.locator("#phone-kim td").all_text_contents()]
    check(cells[:4] == ["김OO 휴대폰", "kim", "김OO", "사용중"], f"휴대폰 표: 이름·휴대폰코드·사용자 이름·상태 ({cells})")
    page.fill("#detail input[placeholder^='휴대폰코드']", "park")
    page.fill("#detail input[placeholder^='휴대폰 이름']", "박OO 휴대폰")
    page.fill("#detail input[placeholder^='사용자 이름']", "박OO")
    page.click("#detail button:has-text('휴대폰 추가')")
    page.wait_for_selector("#detail #phone-park", timeout=15000)
    box = page.text_content("#detail .secret") or ""
    m = re.search(r"비밀번호: (\S+)", box)
    SECRETS.append(m.group(1) if m else "")
    check(email("t_phone", "phone-park") in box and m and "오토파일럿 컨트롤타워" in box and claims(email("t_phone", "phone-park")).get("role") == "phone",
          "화면에서 휴대폰 추가 → 앱에 넣을 이메일·비밀번호를 한 번 보여 준다", mask(box))

    old = browser.new_page()
    old.goto(f"{BASE}/?k={'x' * len(key)}")
    old.wait_for_function("document.getElementById('badge')?.textContent === '연결 안 됨'", timeout=15000)
    check("다시 실행하여 주십시오" in old.text_content("#flash"), "비밀 값이 틀린 화면(옛 주소)은 '다시 켜세요' 를 알린다")

    LATE = dict(PLAN, cid="t_late", name="끄기 직전", pcs=[{"pcId": f"pc_{i}", "label": f"PC {i}"} for i in range(1, 31)],
                users=[{"id": "boss", "role": "admin"}], tokens={"amount": "7"})
    late = []
    worker = threading.Thread(target=lambda: late.append(api("POST", "/api/setup", LATE)))
    worker.start()
    for _ in range(1000):   # 첫 단계(업체)가 끝나 흐름이 한창 돌 때 [끄기] - PC 30대·에이전트 계정 30개가 남아 있다
        if db_get("meta/companies/t_late"):
            break
        time.sleep(0.01)
    page.click("#quit")
    worker.join(timeout=60)
    srv.wait(timeout=15)
    page.wait_for_function("document.body.textContent.includes('관리 화면을 종료하였습니다')", timeout=15000)
    check("3초 뒤 이 창을 닫습니다" in page.text_content("body"), "끄면 '3초 뒤 이 창을 닫습니다' (사용자 2026-10-08)")
    page.wait_for_timeout(3800)
    check(page.is_closed() or "직접 닫아 주십시오" in page.text_content("body"),
          "3초 뒤 창을 닫는다 - 브라우저가 막으면 직접 닫으라고 알린다")
    browser.close()
    done = late[0][1] if late and late[0][0] == 200 else {}
    SECRETS += [u["password"] for u in done.get("made", {}).get("users", [])] + [a["password"] for a in done.get("made", {}).get("agents", [])]
    check(done.get("ok") and len(done.get("made", {}).get("agents", [])) == 30 and (fs_doc("wallet/t_late") or {}).get("granted") == 7,
          "[만들기] 바로 뒤 [끄기] 를 눌러도 하던 일을 끝내고 끈다", late[0][0] if late else "응답 없음 (중간에 꺼짐)")

print("=== 5. 기록 ===")
if srv.poll() is None:
    code, r = api("POST", "/api/quit")
    srv.wait(timeout=15)
text = open(LOG, "rb").read()[log_start:].decode("utf-8") if os.path.exists(LOG) else ""
check("휴대폰 추가 t_phone/kim (김OO 휴대폰)" in text, "기록: 휴대폰 추가 한 줄", text[-400:])
check("신규 업체 t_new" in text and "토큰 +100 t_new 추가" in text and "비밀번호 재발급 t_new" in text and "업체 비활성화 t_new" in text,
      "관리_기록.txt 에 한 일이 한 줄씩", text[-400:])
check(SECRETS and all(SECRETS) and not any(s in text for s in SECRETS) and not any(s in "".join(out_lines) for s in SECRETS),
      "기록 파일·서버 출력 어디에도 비밀번호가 없다")
check(0 <= text.find("신규 업체 t_late") < text.rfind("관리 화면 끔"), "끄기는 하던 일(신규 업체 t_late)이 끝난 뒤에 (기록 차례)", text[-300:])
check(srv.returncode == 0, "[끄기](/api/quit) 로 서버가 끝난다", srv.returncode)
# 관리 기록은 DB(admin_log)에도 - 웹 관리와 한 곳에 모인다 (2026-10-15 웹 전환 밑작업). 로컬은 기다리지 않고 쓰므로 조금 기다려 본다
db_lines = []
for _ in range(20):
    docs = (call("GET", f"{FS}/admin_log?pageSize=500", headers=OWNER) or {}).get("documents", [])
    db_lines = [{k: list(v.values())[0] for k, v in d["fields"].items()} for d in docs]
    if any("신규 업체 t_new" in r.get("line", "") for r in db_lines):
        break
    time.sleep(0.5)
check(any("신규 업체 t_new" in r.get("line", "") and r.get("via") == "로컬" and r.get("by") is None and r.get("at") for r in db_lines)
      and any("비밀번호 재발급 t_new" in r.get("line", "") for r in db_lines),
      "관리 기록이 DB admin_log 에도 {at, line, by=없음, via=로컬}", db_lines[-3:])
check(not any(s in json.dumps(db_lines, ensure_ascii=False) for s in SECRETS if s), "DB 관리 기록에도 비밀번호가 없다")
if srv.poll() is None:
    srv.kill()
print(f"\n{COUNT - len(FAIL)}/{COUNT} 통과")
if FAIL:
    print("실패:", ", ".join(FAIL))
    sys.exit(1)
