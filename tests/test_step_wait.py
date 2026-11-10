# -*- coding: utf-8 -*-
"""단계 뒤 'n초 대기' 시험 (사용자 2026-11-05) - 옵저버 값 → 기록 wait_sec → 재생이 기다린다. 창은 뜨지 않는다.
    .venv\\Scripts\\python.exe tests\\test_step_wait.py
"""
import http.server
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="rpa_wait_")
os.environ["RPA_USER_CONFIG"] = os.path.join(TMP, "config", "RPA_UserConfig.json")
os.environ["RPA_PROGRAMDATA"] = os.path.join(TMP, "programdata")
os.environ["RPA_STATUS_DIR"] = os.path.join(TMP, "status")
os.environ["RPA_OBSERVER_LOCK"] = rf"Local\AFTER_MARKET_RPA_OBSERVER_WAIT_TEST_{os.getpid()}"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import rpa_observer as ob  # noqa: E402
import web_replay as rec  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


print("=== 1. 체크하고 0 이상의 정수를 넣은 경우에만 ===")
steps = [{"id": k} for k in range(1, 8)]
steps[6]["wait_sec"] = 9                # 파일에서 불러온 값
ob.apply_waits(steps, {1: (True, "3"), 2: (True, "0"), 3: (False, "3"), 4: (True, ""), 5: (True, "abc"), 7: (False, "9")})
check("켜고 3 = 3초", steps[0].get("wait_sec") == 3, steps[0])
check("켜고 0 = 0초", steps[1].get("wait_sec") == 0, steps[1])
check("끄면 없음", "wait_sec" not in steps[2], steps[2])
check("비었으면 없음", "wait_sec" not in steps[3], steps[3])
check("정수가 아니면 없음", "wait_sec" not in steps[4], steps[4])
check("안 건드린 단계는 그대로 없음", "wait_sec" not in steps[5], steps[5])
check("불러온 값을 끄면 지운다", "wait_sec" not in steps[6], steps[6])
p = ob.new_preset(1)
p["raw"] = [{}]
before = ob.edit_view([p])
p["wait"][1] = (True, "5")
check("값을 바꾸면 '저장하지 않은 변경' 이다", ob.edit_view([p]) != before)
before = ob.edit_view([p])
p["market"] = "이지웰"
check("운송장 전송 마켓만 골라도 '저장하지 않은 변경' 이다", ob.edit_view([p]) != before)


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write("<title>대기</title><button id=a>하나</button><button id=b>둘</button>".encode())

    def log_message(self, *a):
        pass


srv = http.server.HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{srv.server_port}/"


def human(page):
    page.click("#a")
    page.wait_for_timeout(300)
    page.click("#b")
    page.wait_for_timeout(300)


print("=== 2. 재생 ===")
made = rec.record(url, os.path.join(TMP, "rec.json"), headless=True, human=human)
clicks = [s for s in made["steps"] if s["kind"] == "click"]
check("기록에 누르기 둘", len(clicks) == 2, made["steps"])


def play(sec):
    for s in made["steps"]:
        s.pop("wait_sec", None)
    if sec is not None:
        clicks[0]["wait_sec"] = sec
    lines = []
    t = time.time()
    ok, _ = rec.replay(made, {"ID": "", "PW": ""}, os.path.join(TMP, "dl"), "012", log=lines.append)
    return ok, time.time() - t, lines


ok0, t0, _ = play(None)
ok3, t3, lines = play(3)
check("대기 없이도 끝까지", ok0 is True, ok0)
check("3초 대기를 켠 재생은 끝까지", ok3 is True, ok3)
check("3초만큼 더 걸린다", 2.5 <= t3 - t0 <= 6, f"{t0:.1f} → {t3:.1f}")
check("기록에 남긴다", any("(3초 대기)" in x for x in lines), lines)

print("=== 3. 대기 중 [■ 중단] ===")
clicks[0]["wait_sec"] = 60
with rec.sync_playwright() as pw:
    b = rec.edge(pw.chromium.launch, headless=True)
    rp = rec.Replayer(b.new_context(), made, {"ID": "", "PW": ""}, os.path.join(TMP, "dl2"), "012", log=lambda x: None)
    rp.cancel = threading.Event()
    threading.Timer(3, rp.cancel.set).start()
    t = time.time()
    rp.run()
    b.close()
check("60초를 다 기다리지 않고 멈춘다", time.time() - t < 25 and any(x[2] == rec.STOPPED for x in rp.results), f"{time.time() - t:.1f}초 {rp.results}")

srv.shutdown()
shutil.rmtree(TMP, ignore_errors=True)
print()
print(f"실패: {'없음' if not fails else fails}")
sys.exit(1 if fails else 0)
