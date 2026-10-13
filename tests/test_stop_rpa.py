# -*- coding: utf-8 -*-
"""[RPA 중단] (2026-10-12 사용자: 하던 단계를 기다리지 않고 바로 끔, ERPia 는 그대로) - 진짜 프로세스로 본다.
가짜 루틴(파이썬)이 상태 파일을 쓰고 손자 하나와 가짜 ERPiaMain.exe(ping 사본)를 띄운다. 기록 폴더는 임시.

    .venv\\Scripts\\python.exe tests\\test_stop_rpa.py
"""
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(prefix="rpa_stop_")
os.environ["RPA_STATUS_DIR"] = tmp
sys.path.insert(0, ROOT)
import rpa_status as st  # noqa: E402
import rpa_dashboard as d  # noqa: E402

fails = []


def check(cond, what, detail=""):
    print(("PASS " if cond else "FAIL ") + what + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(what)


fake_erpia = os.path.join(tmp, d.ERPIA_EXE)
shutil.copy(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "PING.EXE"), fake_erpia)
pidfile = os.path.join(tmp, "pids.txt")
child_py = os.path.join(tmp, "fake_routine.py")
with open(child_py, "w", encoding="utf-8") as f:
    f.write(f"""import subprocess, sys, time
sys.path.insert(0, {ROOT!r})
import rpa_status as st
st.start("routine")
st.set_modules([("login", "로그인", [], 1), ("logistics", "물류관리", [], 8)])
st.module_start("login"); st.module_done("login", "done"); st.module_start("logistics")
gc = subprocess.Popen([{fake_erpia!r}, "-n", "120", "127.0.0.1"], stdout=subprocess.DEVNULL)     # ERPia - 남아야 한다
kid = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])                   # 딸린 프로그램 - 꺼져야 한다
open({pidfile!r}, "w").write(f"{{gc.pid}} {{kid.pid}}")
time.sleep(120)
""")


def wait(cond, sec=20):
    end = time.time() + sec
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.2)
    return False


def alive(pid):
    return st.process_alive(pid) is True


print("=== 1. 도는 RPA 가 없으면 ===")
code, body = d.stop_rpa()
check(code == 200 and body.get("message") == "이미 완료되어 중단할 수 없었습니다.", "할 일 없음 - 성공으로 알림", str(body))

print("=== 2. 대시보드가 띄운 루틴을 중단 ===")
proc = subprocess.Popen([sys.executable, child_py], env=dict(os.environ))
d._active.update(target="routine", by="cloud", at=time.time(), proc=proc, checked=False, until=0.0)
check(wait(lambda: os.path.exists(pidfile) and os.path.getsize(pidfile) > 0), "가짜 루틴이 떴다")
erpia_pid, kid_pid = map(int, open(pidfile).read().split())
check(st.running_programs() == ["routine"], "중단 전: 루틴이 돈다", str(st.running_programs()))

code, body = d.stop_rpa()
check(code == 200 and body.get("message") == "PROCESS 오토파일럿을 중단했습니다.", "결과 글", f"{code} {body}")
check(proc.poll() is not None, "루틴 프로그램이 꺼졌다")
check(wait(lambda: not alive(kid_pid), 5), "딸린 프로그램도 꺼졌다")
check(alive(erpia_pid), "ERPia 는 그대로 (사용자 2026-10-12)")
check(d.launch_state() is None, "띄운 실행 잠금이 풀렸다 - 단추가 다시 [ERPia 종료]")

v = st.read_json(st.status_path("routine"))
check(v["state"] == "stopped" and v["reason"] == d.STOPPED_TEXT, "기록: '중단' + 대시보드에서 중단했습니다", f"{v['state']} {v['reason']}")
mods = {m["key"]: m["state"] for m in v["modules"]}
check(mods == {"login": "done", "logistics": "stopped"}, "끝난 모듈은 완료 그대로, 하던 모듈은 중단 (토큰은 완료만)", str(mods))
hist = st.read_history(program="routine")
check(len(hist) == 1 and hist[0]["state"] == "stopped" and hist[0]["reason"] == d.STOPPED_TEXT, "이력에 한 번 남는다",
      str([(h["state"], h["reason"]) for h in hist]))
time.sleep(0.5)
st.dashboard_snapshot()                                     # 대시보드가 다시 읽어도 '비정상 종료' 로 덮이지 않는다
check(len(st.read_history(program="routine")) == 1 and st.read_json(st.status_path("routine"))["state"] == "stopped",
      "다시 읽어도 '비정상 종료' 로 바뀌지 않는다")
check(not any(h.get("reason", "").startswith("시작하지 못했습니다") for h in st.read_history()), "'시작하지 못함' 이력이 안 생긴다")

print("=== 3. 반복 회차를 중단하면 반복을 멈추는 까닭 ===")
why = d.stop_reason(v)
check("대시보드에서 중단" in why and "실패" not in why, "까닭에 '실패' 대신 중단", why)

print("=== 4. 다시 누르면 ===")
code, body = d.stop_rpa()
check(code == 200 and body.get("message") == "이미 완료되어 중단할 수 없었습니다.", "이미 멈췄으면 할 일 없음", str(body))

d.terminate_pid(erpia_pid)
shutil.rmtree(tmp, ignore_errors=True)
print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
