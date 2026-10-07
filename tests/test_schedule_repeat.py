# -*- coding: utf-8 -*-
"""시간대 반복 시험 (설계 6절). 가짜 시계(rpa_dashboard.NOW) + DRY_RUN + 격리 폴더 - 실제 RPA 는 안 띄운다.
루틴이 도는 것은 상태 파일(status_routine.json)을 직접 써서 흉내 낸다."""
import datetime as dt
import io
import os
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
tmp = tempfile.mkdtemp(prefix="rpa_repeat_")
os.environ["RPA_STATUS_DIR"] = tmp
os.environ["RPA_DASHBOARD_DRY_RUN"] = "1"
os.environ["RPA_OBSERVER_LOCK"] = rf"Local\AFTER_MARKET_RPA_OBSERVER_REPEAT_TEST_{os.getpid()}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rpa_status as st  # noqa: E402
import rpa_dashboard as d  # noqa: E402

fails = []


def check(cond, what):
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        fails.append(what)


CLOCK = [dt.datetime(2026, 9, 14, 10, 58)]          # 2026-09-14 월요일
d.NOW = lambda: CLOCK[0]
PID, CREATED = os.getpid(), st.process_created(os.getpid())


def at(hhmm, day=0, sec=0):
    h, m = map(int, hhmm.split(":"))
    return dt.datetime(2026, 9, 14 + day, h, m, sec)


def iso(t):
    return t.isoformat(timespec="seconds")


def put_status(program, state, started, finished=None, modules=(), reason=None, trigger="repeat"):
    """상태 파일을 흉내 낸다 (running 이면 이 프로세스가 살아 있는 것으로 보인다). trigger 는 띄운 까닭 (사람이 누르면 None)."""
    st.write_json_atomic(st.status_path(program), {
        "schema": 2, "run_id": f"{program}_{started:%Y%m%d_%H%M%S}_{PID}", "program": program, "program_label": st.LABELS[program],
        "state": state, "reason": reason, "pid": PID, "pid_created": CREATED, "started_at": iso(started),
        "updated_at": iso(finished or started), "finished_at": iso(finished) if finished else None,
        "steps": [], "metrics": [], "modules": [dict(m) for m in modules], "module_flags": 0, "log_tail": [], "trigger": trigger})


def ended():
    """띄운 프로세스가 끝난 것으로 (DRY_RUN 은 손잡이가 없어 유예 시간을 쓴다)"""
    d._active["until"] = 0
    d._active["proc"] = None


def rep():
    return st.read_settings()["schedule"].get("repeat") or {}


LOGIN = {"key": "login", "label": "로그인", "state": "done"}
NO_TARGET = {"key": "logistics", "label": "물류관리", "state": "no_target"}
DONE = {"key": "logistics", "label": "물류관리", "state": "done"}
WIN = {"at": "11:00", "until": "12:00", "rest_min": 2, "run": ["Logistics"]}
ALL = list(range(7))

print("\n=== 1. 줄 검사 ===")
ok = d.normalize_slots([{"at": "10:00"}, dict(WIN)])
check(ok[1] == {"at": "11:00", "until": "12:00", "rest_min": 2, "on_fail": "stop", "run": ["Login", "Logistics"]},
      f"반복 줄: 쉬는 시간·실패하면 멈춤·로그인 붙음 ({ok[1]})")
check(d.normalize_slots([{"at": "11:00", "until": "12:00", "run": ["Hold"]}])[0]["rest_min"] == 2, "쉬는 시간을 안 주면 2분")
for bad, why in (
        ([{"at": "11:00", "until": "11:00", "run": ["Hold"]}], "늦어야"),
        ([{"at": "11:00", "until": "12:00", "run": ["Hold"], "rest_min": 0}], "1~60"),
        ([{"at": "11:00", "until": "12:00", "run": ["Hold"], "rest_min": 61}], "1~60"),
        ([{"at": "11:00", "until": "12:00", "run": ["Hold"], "on_fail": "retry"}], "멈춤"),
        ([{"at": "11:00", "until": "12:00"}], "전체"),
        ([{"at": "11:00", "until": "12:00", "run": ["Prepare", "Hold"]}], "쇼핑몰 받기"),
        ([dict(WIN), {"at": "11:30", "until": "12:30", "run": ["Hold"]}], "겹칩니다"),
        ([dict(WIN), {"at": "11:30"}], "반복 안에는"),
        ([dict(WIN), {"at": "11:00"}], "반복 안에는"),
        ([{"at": "23:00", "until": "24:00", "run": ["Hold"]}], "23:55")):
    try:
        d.normalize_slots(bad); check(False, f"거부: {why}")
    except ValueError as e:
        check(why in str(e), f"거부: {why} ({e})")
check(len(d.normalize_slots([dict(WIN), {"at": "12:00"}])) == 2, "끝 시각과 같은 시각(12:00)은 된다")

print("\n=== 2. 시간대가 열리면 첫 회차 ===")
d.apply_schedule({"enabled": True, "days": ALL, "slots": [dict(WIN)]})
sched = d.Scheduler()
sched.tick()
check(d.LAUNCHED == [] and st.read_settings()["schedule"]["next_slot"] == "11:00", "10:58: 아직 (다음 실행은 시간대 시작)")
CLOCK[0] = at("11:00")
sched.tick()
check(d.LAUNCHED == ["routine:auto"] and d.LAUNCHED_ENV[-1] == {"RPA_RUN_MODULES": "Login,Logistics", "RPA_RUN_TRIGGER": "repeat"},
      f"11:00: 루틴만 + 그 모듈 + 반복 표시 ({d.LAUNCHED_ENV[-1:]})")
check(rep().get("pending") == iso(at("11:00")) and rep().get("runs") == 0 and rep().get("date") == "2026-09-14", "띄운 회차를 기다리는 중으로 적는다")
put_status("routine", "running", at("11:00", sec=5))
CLOCK[0] = at("11:00", sec=30)
sched.tick()
check(d.LAUNCHED == ["routine:auto"] and "끝나기를" in (sched.waiting_reason or ""), f"띄운 회차가 안 끝났으면 기다린다 ({sched.waiting_reason})")

print("\n=== 3. 성공하면 쉬었다가 다음 회차 ===")
put_status("routine", "success", at("11:00", sec=5), at("11:01"), [LOGIN, NO_TARGET]); ended()
CLOCK[0] = at("11:01", sec=30)
sched.tick()
r = rep()
check(r.get("runs") == 1 and r.get("done") == 0 and r.get("pending") is None and r.get("next_at") == iso(at("11:03")),
      f"대상 없음도 성공 - 회차 1·처리 0, 끝난 시각 + 2분에 다음 ({r})")
check(d.LAUNCHED == ["routine:auto"], "쉬는 동안은 안 띄운다")
CLOCK[0] = at("11:03")
sched.tick()
check(d.LAUNCHED == ["routine:auto"] * 2, "쉬는 시간이 지나면 다음 회차")
put_status("routine", "success", at("11:03", sec=5), at("11:04"), [LOGIN, DONE]); ended()
CLOCK[0] = at("11:05")
sched.tick()
check(rep().get("runs") == 2 and rep().get("done") == 1, f"처리한 회차는 처리 +1 ({rep()})")

print("\n=== 4. 실패하면 그 시간대 반복을 멈춘다 ===")
CLOCK[0] = at("11:06")
sched.tick()
check(len(d.LAUNCHED) == 3, "세 번째 회차")
put_status("routine", "stopped", at("11:06", sec=5), at("11:10"),
           [LOGIN, {"key": "logistics", "label": "물류관리", "state": "failed", "reason": "저장 실패"}], reason="저장 실패"); ended()
CLOCK[0] = at("11:15")
sched.tick()
check((rep().get("stopped") or {}).get("reason") == "11:10 물류관리 실패로 반복을 멈췄습니다: 저장 실패" and len(d.LAUNCHED) == 3,
      f"까닭을 남기고 멈춘다 ({rep().get('stopped')})")
check("멈췄습니다" in (sched.waiting_reason or ""), "예약기도 멈춤으로 안다")

print("\n=== 5. [반복 다시 시작] ===")
CLOCK[0] = at("11:16")
check(d.resume_repeat() == "반복을 다시 시작했습니다 (12:00까지)" and rep().get("stopped") is None, "멈춤을 푼다")
try:
    d.resume_repeat(); check(False, "멈추지 않았는데 다시 시작")
except RuntimeError as e:
    check(str(e) == "지금은 멈춘 반복이 없습니다", "두 번 눌러도 한 번만 (두 번째는 '멈춘 반복이 없습니다')")
sched.tick()
check(len(d.LAUNCHED) == 4, "바로 다음 회차 (11:10 + 2분이 지났다)")

print("\n=== 6. 토큰이 없으면 멈춘다 ===")
put_status("routine", "success", at("11:16", sec=5), at("11:17"), [LOGIN, NO_TARGET]); ended()
d.TOKEN_GATE = lambda target: (_ for _ in ()).throw(RuntimeError("토큰이 없습니다 (남은 0개). 충전한 뒤 실행하세요"))
try:
    CLOCK[0] = at("11:20")
    sched.tick()
    check(len(d.LAUNCHED) == 4 and "토큰이 없습니다" in (rep().get("stopped") or {}).get("reason", ""), f"까닭과 함께 멈춤 ({rep().get('stopped')})")
finally:
    d.TOKEN_GATE = None
d.resume_repeat()

print("\n=== 7. 단추로 누른 실행 - 끝나면 쉬고 이어 가고, 그 실패는 반복을 안 멈춘다 ===")
put_status("prepare", "stopped", at("11:19"), at("11:21"), reason="사이트 실패")
CLOCK[0] = at("11:22")
sched.tick()
check(len(d.LAUNCHED) == 4 and rep().get("stopped") is None, "사람이 띄운 실행이 11:21 에 끝났으면 11:23 까지 쉰다 (실패해도 반복은 그대로)")
CLOCK[0] = at("11:23")
sched.tick()
check(len(d.LAUNCHED) == 5, "11:23 에 다음 회차")

print("\n=== 8. 끝 시각 - 돌던 회차는 끝까지, 새 회차는 없다 ===")
put_status("routine", "running", at("11:23", sec=5))
CLOCK[0] = at("12:00", sec=30)
sched.tick()
check(len(d.LAUNCHED) == 5, "12:00 이 되면 새 회차는 없다")
put_status("routine", "success", at("11:23", sec=5), at("12:02"), [LOGIN, DONE]); ended()
runs = rep().get("runs")
CLOCK[0] = at("12:03")
sched.tick()
check(rep().get("runs") == runs + 1 and len(d.LAUNCHED) == 5, "끝 시각 뒤에 끝난 회차도 센다, 새 회차는 없다")

print("\n=== 9. 다음 날·시간대 중에 예약을 고치면 (Review Focus 2) ===")
CLOCK[0] = at("11:00", day=1)
sched.tick()
check(rep().get("date") == "2026-09-15" and rep().get("runs") == 0 and len(d.LAUNCHED) == 6, "다음 날 같은 시간대: 새 상태로 첫 회차")
put_status("routine", "success", at("11:00", 1, 5), at("11:01", 1), [LOGIN, NO_TARGET]); ended()
CLOCK[0] = at("11:01", 1, 30); sched.tick()
d.apply_schedule({"enabled": True, "days": ALL, "slots": [dict(WIN, rest_min=5)]})
CLOCK[0] = at("11:02", 1); sched.tick()
check(rep().get("runs") == 1 and len(d.LAUNCHED) == 6, "같은 시간대(시작·끝 같음)는 쉬는 시간만 바꾸면 횟수를 이어 가고 바꾼 쉬는 시간(5분)대로 기다린다")
d.apply_schedule({"enabled": True, "days": ALL, "slots": [dict(WIN, until="11:30")]})
CLOCK[0] = at("11:06", 1); sched.tick()
check(rep().get("until") == "11:30" and rep().get("runs") == 0 and len(d.LAUNCHED) == 7, "끝 시각을 바꾸면 새 상태")
put_status("routine", "running", at("11:06", 1, 5))
d.apply_schedule({"enabled": True, "days": ALL, "slots": [{"at": "15:00"}]})
put_status("routine", "success", at("11:06", 1, 5), at("11:08", 1), [LOGIN, NO_TARGET]); ended()
CLOCK[0] = at("11:20", 1); sched.tick()
check(len(d.LAUNCHED) == 7 and rep().get("runs") == 1, "시간대를 지우면 돌던 회차만 끝나고(센다) 새 회차는 없다")

print("\n=== 10. 정책 쓰기가 반복 상태를 지우지 않는다 (Review Focus 3) ===")
d.apply_schedule({"enabled": True, "days": ALL, "slots": [dict(WIN)]})
CLOCK[0] = at("11:00", day=2)
sched.tick()
d.set_policy(3, ["Hold"])
check(rep().get("pending") == iso(at("11:00", day=2)) and st.read_settings()["schedule"]["slots"][0]["until"] == "12:00", "정책을 적어도 줄·반복 상태는 그대로")
put_status("routine", "success", at("11:00", 2, 5), at("11:01", 2), [LOGIN, DONE]); ended()
CLOCK[0] = at("11:02", 2); sched.tick()
check(rep().get("runs") == 1, "그 회차를 그대로 센다")

print("\n=== 11. 자정을 넘겨 끝난 회차 (Review Focus 1) ===")
d.set_policy(5, [])
d.apply_schedule({"enabled": True, "days": ALL, "slots": [{"at": "23:00", "until": "23:55", "rest_min": 2, "run": ["Hold"]}]})
CLOCK[0] = at("23:50", day=3)
sched.tick()
n = len(d.LAUNCHED)
check(rep().get("date") == "2026-09-17" and rep().get("pending"), "23:50 에 띄운 회차")
put_status("routine", "success", at("23:50", 3, 5), at("00:03", 4), [LOGIN, {"key": "hold", "label": "물류대기 관리", "state": "done"}]); ended()
CLOCK[0] = at("00:05", day=4)
sched.tick()
check(rep().get("date") == "2026-09-17" and rep().get("runs") == 1 and rep().get("done") == 1 and len(d.LAUNCHED) == n,
      "어제 시간대에 세고, 오늘은 시간대 밖이라 안 띄운다")

print("\n=== 12. 꺼져 있거나 한도 밖이면 안 돈다 ===")
d.apply_schedule({"enabled": False, "days": ALL, "slots": [dict(WIN)]})
CLOCK[0] = at("11:10", day=5); n = len(d.LAUNCHED); sched.tick()
check(len(d.LAUNCHED) == n, "자동 실행을 끄면 시간대여도 안 돈다")
d.set_policy(1, [])
d.apply_schedule({"enabled": True, "days": ALL, "slots": [{"at": "10:00"}, dict(WIN)]})
sched.tick()
check(len(d.LAUNCHED) == n, "한도 1 이면 시각 순 앞 줄(10:00)만 - 11:00 시간대는 쉰다")

print("\n=== 13. 화면 값·이름표 ===")
d.set_policy(5, [])
sv = d.schedule_view()
check(sv["times"] == ["10:00"] and sv["repeat"] is not None and sv["slots"][1]["until"] == "12:00", "옛 8765 화면엔 시각 줄만, 반복 상태도 싣는다")
label = d.schedule_label(st.read_settings()["schedule"])
check(label == "매일 10:00, 11:00~12:00 반복 물류관리", label)

print("\n=== 14. 반복 회차를 다른 실행과 헷갈리지 않는다 (끝 검토) ===")
d.apply_schedule({"enabled": True, "days": ALL, "slots": [dict(WIN)]})
CLOCK[0] = at("11:00", day=6); n = len(d.LAUNCHED); sched.tick()
check(len(d.LAUNCHED) == n + 1 and rep().get("pending") == iso(at("11:00", day=6)), "회차를 띄움")
ended()
CLOCK[0] = at("11:00", day=6, sec=30); sched.tick()
check(rep().get("stopped") is None and rep().get("pending"), "상태 파일이 아직 옛 실행이어도 바로 '시작하지 못함' 으로 멈추지 않는다 (에이전트를 다시 켠 직후 등)")
CLOCK[0] = at("11:02", day=6); sched.tick()
check("시작하지 못했습니다" in (rep().get("stopped") or {}).get("reason", ""), "유예가 지나도 기록이 없으면 그때 멈춘다")
d.resume_repeat(); sched.tick()
check(len(d.LAUNCHED) == n + 2 and rep().get("pending") == iso(at("11:02", day=6)), "다시 시작 → 회차")
ended()
put_status("routine", "stopped", at("11:02", 6, 10), at("11:03", 6), [LOGIN], reason="사람이 누른 실행 실패", trigger=None)
CLOCK[0] = at("11:04", day=6); sched.tick()
check(rep().get("stopped") is None and rep().get("pending") is None and rep().get("runs") == 0 and len(d.LAUNCHED) == n + 2,
      f"사람이 누른 실행이 상태를 덮었으면 세지도 멈추지도 않는다 ({rep().get('stopped')})")
CLOCK[0] = at("11:05", day=6); sched.tick()
check(len(d.LAUNCHED) == n + 3, "쉬는 시간 뒤 다음 회차")
put_status("routine", "running", at("11:05", 6, 5))
d.apply_schedule({"enabled": False, "days": ALL, "slots": [dict(WIN)]})
put_status("routine", "success", at("11:05", 6, 5), at("11:07", 6), [LOGIN, DONE]); ended()
CLOCK[0] = at("11:08", day=6); sched.tick()
check(rep().get("runs") == 1 and rep().get("done") == 1 and rep().get("pending") is None and len(d.LAUNCHED) == n + 3,
      f"자동 실행을 꺼도 돌던 회차는 센다, 새 회차는 없다 ({rep()})")
d.apply_schedule({"enabled": True, "days": ALL, "slots": [dict(WIN)]})
d.TOKEN_GATE = lambda target: (_ for _ in ()).throw(FileNotFoundError("ERPia_RPA.exe 이(가) 없습니다"))
try:
    CLOCK[0] = at("11:10", day=6); sched.tick_safe()
    check("없습니다" in (rep().get("stopped") or {}).get("reason", ""), f"exe 가 없어도 그 시간대를 멈춘다 - 5초마다 다시 안 띄운다 ({rep().get('stopped')})")
finally:
    d.TOKEN_GATE = None

shutil.rmtree(tmp, ignore_errors=True)
print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
