# -*- coding: utf-8 -*-
"""옵저버 단독 관제 서버 (observer_hub.py, 설계 2026-11-03 4.3) - 127.0.0.1 에만, Host·Origin 검사, 예약·실행·설정 API.
임시 폴더·DRY_RUN - 실제로 띄우지 않는다. 포트는 시험용 번호대(18775~)를 쓴다.
    .venv\\Scripts\\python.exe tests\\test_observer_hub.py
"""
import io
import json
import os
import socket
import sys
import tempfile
import urllib.error
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
TMP = tempfile.mkdtemp(prefix="rpa_hub_")
os.environ["RPA_STANDALONE"] = "1"
os.environ["RPA_STATUS_DIR"] = os.path.join(TMP, "status")
os.environ["RPA_PROGRAMDATA"] = os.path.join(TMP, "programdata")
os.environ["RPA_USER_CONFIG"] = os.path.join(TMP, "config", "RPA_UserConfig.json")
os.environ["RPA_DASHBOARD_DRY_RUN"] = "1"
os.environ["RPA_OBSERVER_LOCK"] = rf"Local\AFTER_MARKET_OBSERVER_SA_HUB_TEST_{os.getpid()}"
os.makedirs(os.path.join(TMP, "config"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rpa_status as st  # noqa: E402
import rpa_dashboard as d  # noqa: E402
import observer_hub as hub  # noqa: E402

fails = []


def check(cond, what, detail=""):
    print(("PASS " if cond else "FAIL ") + what + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(what)


REC = {"version": 1, "start_url": "https://shop.example.com/login", "record_date": "2026-11-03",
       "steps": [{"kind": "goto", "page": 0, "url": "/login", "href": "https://shop.example.com/login", "gap": 0}]}
st.write_user_config({"LogIn": {"AdminCode": "", "ID": "", "PW": ""}, "Sites": {}})
st.write_presets([dict(st.blank_preset(1), name="가몰", code="011", record=REC), dict(st.blank_preset(2), name="나몰", code="012", record=REC)])
st.save_preset_sites(st.read_presets(), {1: ("a", "pw"), 2: ("b", "pw")})
st.set_preset_switches({"1": True, "2": True})

PORTS = list(range(18775, 18785))
taken = socket.socket()
taken.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", socket.SO_REUSEADDR), 1)
taken.bind(("127.0.0.1", PORTS[0]))
taken.listen(1)
httpd = hub.start(PORTS)
port = httpd.server_address[1]
BASE = f"http://127.0.0.1:{port}"


def call(path, body=None, headers=None, host=None, origin=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None, method="POST" if body is not None else "GET")
    req.add_header("Content-Type", "application/json")
    if origin:
        req.add_header("Origin", origin)
    if host:
        req.add_header("Host", host)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read().decode("utf-8")
            return r.status, json.loads(raw) if r.headers.get("Content-Type", "").startswith("application/json") else raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw


print("=== 1. 서버 ===")
check(httpd.server_address[0] == "127.0.0.1", "binds_loopback: 127.0.0.1 에만", httpd.server_address)
check(port == PORTS[1] and open(hub.port_path(), encoding="utf-8").read().strip() == str(PORTS[1]), "port_fallback: 첫 포트를 쓰면 다음 포트 + hub_port.txt",
      (port, hub.port_path()))
code, body = call("/api/state")
check(code == 200 and body["presets"][0]["name"] == "가몰" and body["limits"] == {"presets": st.PRESET_MAX, "parallel_max": st.PARALLEL_MAX}
      and body["settings"]["download_dir"] == st.download_dir_choice() and body["running"] is False and body["observer_open"] is False
      and "schedule" in body and "snapshot" in body, "state: 프리셋·설정·한도·예약·현황", body if code != 200 else "")
code, body = call("/")
check(code == 200 and isinstance(body, str) and "옵저버 관제" in body, "GET / 는 관제 화면", body[:80] if isinstance(body, str) else body)

print("\n=== 2. Host·Origin (Review Focus 3) ===")
code, body = call("/api/run", {"presets": [1]}, origin="http://evil.example")
check(code == 403 and d.LAUNCHED == [], "foreign_origin_rejected: 다른 페이지의 POST 는 403", (code, body))
code, body = call("/api/run", {"presets": [1]}, host="192.168.0.5:8775")
check(code == 403 and d.LAUNCHED == [], "foreign_origin_rejected: 다른 Host 는 403", (code, body))
code, body = call("/api/state", host="192.168.0.5:8775")
check(code == 403, "api GET 도 Host 검사", (code, body))
code, body = call("/api/run", {"presets": [1]}, headers={"Content-Length": "100000"})
check(code in (400, 413) and d.LAUNCHED == [], "본문 64KB 넘으면 거절", (code, body))

print("\n=== 3. 실행·중지 ===")
code, body = call("/api/run", {"presets": [2]}, origin=BASE)
check(code == 200 and d.LAUNCHED == ["prepare:manual:hub"] and d.LAUNCHED_ENV[-1]["RPA_RUN_PRESETS"] == "2", "run_presets: 고른 프리셋으로 ACTOR",
      (code, body, d.LAUNCHED, d.LAUNCHED_ENV[-1:]))
d._active["until"] = 0; d._active["proc"] = None
code, body = call("/api/run", {"presets": None})
check(code == 200 and "RPA_RUN_PRESETS" not in d.LAUNCHED_ENV[-1], "run_presets: null 이면 켠 프리셋 모두", (code, body, d.LAUNCHED_ENV[-1:]))
d._active["until"] = 0; d._active["proc"] = None
code, body = call("/api/run", {"presets": [99]})
check(code == 400 and len(d.LAUNCHED) == 2, "run_presets: 틀린 번호는 400", (code, body))
st.hold_lock(st.observer_lock_name())
code, body = call("/api/run", {"presets": [2]})
check(code == 409 and body["error"] == "옵저버가 실행 중입니다. 옵저버를 종료한 뒤 실행하여 주십시오.", "run_presets: 옵저버가 떠 있으면 409", (code, body))
code, body = call("/api/observer", {})
check(code == 409 and body["error"] == "옵저버가 이미 실행 중입니다.", "observer: 이미 떠 있으면 409", (code, body))
code, body = call("/api/stop", {})
check(code == 200 and body["ok"], "stop: 도는 게 없어도 200", (code, body))

print("\n=== 4. 예약·설정 ===")
code, body = call("/api/schedule", {"enabled": True, "days": [0, 1, 2, 3, 4], "slots": [{"at": "09:00", "presets": [1]}], "skip_holidays": True, "off_dates": []})
state = call("/api/state")[1]
check(code == 200 and state["schedule"]["slots"] == [{"at": "09:00", "presets": [1]}] and state["schedule"]["enabled"], "schedule_roundtrip", (code, body))
code, body = call("/api/schedule", {"enabled": True, "days": [0], "slots": [{"at": "09:00", "run": ["Prepare"]}]})
check(code == 400 and "모듈" in body["error"], "schedule: run 은 400", (code, body))
before = st.read_settings()["prepare"].get("download_dir")
code, body = call("/api/settings", {"download_dir": "Q:\\없는드라이브\\x"})
check(code == 400 and body["error"] == "받은 파일 폴더를 만들 수 없습니다: Q:\\없는드라이브\\x" and st.read_settings()["prepare"].get("download_dir") == before,
      "download_dir_bad: 못 만드는 폴더는 400, 설정 그대로 (Review Focus 5)", (code, body))
good = os.path.join(TMP, "받은파일")
code, body = call("/api/settings", {"download_dir": good, "parallel": 3})
check(code == 200 and os.path.isdir(good) and st.download_dir_choice() == good and st.parallel_choice() == 3, "settings: 폴더 만들고 저장, 동시 실행 수", (code, body))
code, body = call("/api/settings", {"parallel": 99})
check(code == 400, "settings: 동시 실행 수 범위 밖은 400", (code, body))

print("\n=== 5. 기록 ===")
st.record_start_failure("prepare", "2026-11-03T09:00:00", "시험 기록")
code, body = call("/api/history?period=7")
check(code == 200 and body["summary"]["total"] == 1 and body["runs"][0]["reason"] == "시험 기록", "history: 요약·목록", (code, body))
rid = body["runs"][0]["run_id"]
code, one = call(f"/api/history/{rid}")
check(code == 200 and one["run_id"] == rid, "history/<run_id>", (code, one))
code, body = call("/api/open", {"run_id": "없는것"})
check(code == 404, "open: 모르는 기록은 404", (code, body))
code, body = call("/api/open", {"run_id": rid})
check(code == 200 and body["folder"] == st.data_dir(), "open: 기록의 사진 폴더 (요청 본문의 경로는 받지 않는다)", (code, body))

httpd.shutdown()
taken.close()
print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
