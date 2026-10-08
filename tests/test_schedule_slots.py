# -*- coding: utf-8 -*-
"""요일 + 시간 예약 로직 단위 시험. 실제 Run_All.bat 은 띄우지 않는다 (DRY_RUN + 격리 폴더)."""
import datetime as dt
import io
import os
import shutil
import signal
import subprocess
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
tmp = tempfile.mkdtemp(prefix="rpa_sched_")
os.environ["RPA_STATUS_DIR"] = tmp
os.environ["RPA_DASHBOARD_DRY_RUN"] = "1"
os.environ["RPA_OBSERVER_LOCK"] = rf"Local\AFTER_MARKET_RPA_OBSERVER_SCHED_TEST_{os.getpid()}"
sys.path.insert(0, r"D:\AX\RPA")
import rpa_status as st  # noqa: E402
import rpa_dashboard as d  # noqa: E402

fails = []


def check(cond, what):
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        fails.append(what)


# 2026-09-14 = 월요일
MON = dt.datetime(2026, 9, 14)
check(MON.weekday() == 0, "기준일 2026-09-14 은 월요일")
at = lambda day_off, hh, mm, ss=0: MON + dt.timedelta(days=day_off, hours=hh, minutes=mm, seconds=ss)  # noqa: E731

print("\n=== 1. 다음 예약 시각 계산 ===")
WK = [0, 1, 2, 3, 4]
check(d.next_slot(WK, ["09:00"], at(0, 8, 0)) == at(0, 9, 0), "월 08:00 -> 월 09:00")
check(d.next_slot(WK, ["09:00"], at(0, 9, 0)) == at(1, 9, 0), "월 09:00 정각 -> 화 09:00 (같은 시각은 지난 것)")
check(d.next_slot(WK, ["09:00"], at(0, 9, 0, 30)) == at(1, 9, 0), "월 09:00:30 -> 화 09:00")
check(d.next_slot(WK, ["09:00", "14:30"], at(0, 10, 0)) == at(0, 14, 30), "하루 여러 번: 월 10:00 -> 월 14:30")
check(d.next_slot(WK, ["09:00"], at(4, 10, 0)) == at(7, 9, 0), "평일: 금 10:00 -> 다음 월 09:00 (주말 건너뜀)")
check(d.next_slot([5, 6], ["07:05"], at(0, 12, 0)) == at(5, 7, 5), "주말: 월 12:00 -> 토 07:05")
check(d.next_slot([2], ["09:00"], at(2, 9, 1)) == at(9, 9, 0), "수요일만: 수 09:01 -> 다음 주 수 09:00 (7일 뒤)")
check(d.next_slot(list(range(7)), ["00:00"], at(6, 23, 59)) == at(7, 0, 0), "매일 00:00: 일 23:59 -> 월 00:00 (자정 넘김)")
check(d.next_slot(list(range(7)), ["23:55", "00:05"], at(0, 23, 56)) == at(1, 0, 5), "정렬 안 된 입력도 가장 가까운 것")
check(d.next_slot([], ["09:00"], at(0, 8, 0)) is None and d.next_slot(WK, [], at(0, 8, 0)) is None, "요일/시간이 비면 None")

print("\n=== 2. 입력 검증 ===")
check(d.normalize_days([4, 0, 0, 2]) == [0, 2, 4], "요일 정렬·중복 제거")
check(d.normalize_times(["14:30", "09:00", "09:00"]) == ["09:00", "14:30"], "시간 정렬·중복 제거")
for bad_days in ([], [7], [-1], ["1"], [True], None, "0,1"):
    try:
        d.normalize_days(bad_days); check(False, f"요일 거부 {bad_days!r}")
    except ValueError:
        check(True, f"요일 거부 {bad_days!r}")
for bad_t in ([], ["9:00"], ["24:00"], ["09:03"], ["09:60"], ["0900"], [900], ["ab:cd"], None,
              [f"{h:02d}:00" for h in range(13)]):
    label = bad_t if not isinstance(bad_t, list) or len(bad_t) < 5 else f"{len(bad_t)}개"
    try:
        d.normalize_times(bad_t); check(False, f"시간 거부 {label!r}")
    except ValueError:
        check(True, f"시간 거부 {label!r}")
check(len(d.normalize_times([f"{h:02d}:00" for h in range(12)])) == 12, "12개까지는 받음 (PC 상한 - 업체 한도는 에이전트가)")

print("\n=== 3. 이름표 ===")
check(d.days_label(list(range(7))) == "매일", "매일")
check(d.days_label([4, 3, 2, 1, 0]) == "평일", "평일")
check(d.days_label([6, 5]) == "주말", "주말")
check(d.days_label([0, 2, 4]) == "월·수·금", "월·수·금")
check(d.schedule_label({"days": WK, "slots": [{"at": "09:00"}, {"at": "13:00"}]}) == "평일 09:00, 13:00", "평일 09:00, 13:00")
check(d.schedule_label({"days": WK, "slots": [{"at": t} for t in ("08:00", "10:00", "12:00", "14:00", "16:00")]}) == "평일 08:00, 10:00, 12:00 외 2개", "많으면 앞 3개 + 외 N개")
check(d.schedule_label({"days": WK, "slots": [{"at": "10:00"}, {"at": "11:00", "run": ["Login", "Logistics"]}]}) == "평일 10:00, 11:00 물류관리",
      "고르기 줄은 시각 뒤에 모듈 (로그인은 안 적는다)")

print("\n=== 4. 기본값과 예전 설정 ===")
cfg = st.read_settings()
check(cfg["schedule"]["enabled"] is False and cfg["schedule"]["days"] == WK and cfg["schedule"]["slots"] == [{"at": "09:00"}]
      and "times" not in cfg["schedule"] and cfg["schedule"]["version"] == 3, "기본: 꺼짐, 평일 09:00 '전체' 한 줄, 판 3")
old = st.read_settings(); old["schedule"]["interval_min"] = 15; st.write_settings(old)
check(d.schedule_view()["days"] == WK and "interval_min" not in d.schedule_view(), "예전 interval_min 이 있어도 새 모양으로 보임")
st.write_settings({"schedule": {"enabled": False, "days": WK, "times": ["13:30", "09:05"]}})
conv = st.read_settings()["schedule"]
check(conv["slots"] == [{"at": "13:30"}, {"at": "09:05"}] and "times" not in conv and conv["version"] == 3,
      "옛 모양 {days, times} 는 '전체' 줄로 읽힌다 (Review Focus 4)")
st.write_settings({"schedule": {"enabled": False, "interval_min": 15, "next_run_at": None}})
check(st.read_settings()["schedule"]["slots"] == [{"at": "09:00"}], "더 옛 모양 (interval_min, 시각 없음) 은 기본 줄 그대로")
st.write_settings({"schedule": {"enabled": False, "days": WK, "times": ["13:30", "09:05"]}})
sv = d.schedule_view()
check(sv["times"] == ["09:05", "13:30"] and sv["slots"][0] == {"at": "09:05"} and sv["version"] == 3,
      "화면 값: 줄은 시각 순, 옛 8765 화면용 times 도, 판 2 (줄이 0개여도 판으로 새 판을 안다 - Review Focus 5)")

print("\n=== 5. 적용 ===")
for bad in ({"enabled": "yes", "days": WK, "times": ["09:00"]}, {"enabled": True, "days": [], "times": ["09:00"]},
            {"enabled": True, "days": WK, "times": ["09:07"]}, {"enabled": True, "interval_min": 60}, "x", None):
    try:
        d.apply_schedule(bad); check(False, f"적용 거부 {bad!r}")
    except ValueError:
        check(True, f"적용 거부 {bad!r}")
now = dt.datetime.now()
changed = d.apply_schedule({"enabled": True, "days": list(range(7)), "times": ["23:55", "00:00", "12:00"]})
sch = st.read_settings()["schedule"]
check(changed and [s["at"] for s in sch["slots"]] == ["00:00", "12:00", "23:55"] and sch["days"] == list(range(7)), "켜기 적용 -> 정렬해 저장")
check("interval_min" not in sch, "적용하면 예전 interval_min 은 지움")
nxt = st.parse_iso(sch["next_run_at"])
check(nxt == d.next_slot(sch["days"], [s["at"] for s in sch["slots"]], now) or nxt == d.next_slot(sch["days"], [s["at"] for s in sch["slots"]], dt.datetime.now()),
      f"next_run_at = 다음 예약 ({sch['next_run_at']})")
check(d.apply_schedule({"enabled": True, "days": [6, 5, 4, 3, 2, 1, 0], "times": ["12:00", "00:00", "23:55"]}) is False,
      "같은 값(순서만 다름) 재적용 -> changed=False")
sv = d.schedule_view()
check(sv["label"] == "매일 00:00, 12:00, 23:55" and sv["times"] and sv["days"], f"schedule_view 이름표: {sv['label']}")

print("\n=== 5-2. 줄마다 모듈 (2026-10-07 시각별 모듈) ===")
check(d.normalize_run(None) is None, "run 이 없으면 '전체'")
check(d.normalize_run(["Logistics"]) == ["Login", "Logistics"], "루틴 모듈을 고르면 로그인은 늘 붙는다")
check(d.normalize_run(["Output", "Logistics", "Prepare"]) == ["Prepare", "Login", "Logistics", "Output"], "정한 순서로 (사이트 수집 → 루틴)")
check(d.normalize_run(["Prepare", "Login"]) == ["Prepare"], "사이트 수집만이면 로그인은 뺀다")
for bad, why in ((["Output"], "물류관리와 같이"), (["Login"], "하나 이상"), ([], "하나 이상"), (["Nope"], "모르는 모듈"),
                 (["Sales", "Sales"], "두 번"), ("Sales", "잘못")):
    try:
        d.normalize_run(bad); check(False, f"run 거부 {bad!r}")
    except ValueError as e:
        check(why in str(e), f"run 거부 {bad!r} ({e})")
slots = d.normalize_slots([{"at": "11:00", "run": ["Logistics"]}, {"at": "10:00"}])
check(slots == [{"at": "10:00"}, {"at": "11:00", "run": ["Login", "Logistics"]}], f"줄은 시각 순, '전체' 줄엔 run 이 없다 ({slots})")
for bad, why in (([{"at": "10:00"}, {"at": "10:00", "run": ["Hold"]}], "같은 시각"), ([{"at": "10:03"}], "5분"),
                 ([{"at": f"{h:02d}:00"} for h in range(13)], "12개"), ([], "하나 이상"), (["10:00"], "줄이 잘못")):
    try:
        d.normalize_slots(bad); check(False, f"줄 거부 {why}")
    except ValueError as e:
        check(why in str(e), f"줄 거부 {why} ({e})")
check(d.slot_target({"at": "10:00"}) == ("all", {}), "'전체' 줄 → 전체 실행, 넘길 모듈 없음")
check(d.slot_target({"at": "11:00", "run": ["Login", "Logistics"]}) == ("routine", {"RPA_RUN_MODULES": "Login,Logistics"}), "사이트 수집 없음 → 루틴만")
check(d.slot_target({"at": "12:00", "run": ["Prepare"]}) == ("prepare", {}), "사이트 수집만 → 프리페어")
check(d.slot_target({"at": "13:00", "run": ["Prepare", "Login", "Sales"]}) == ("all", {"RPA_RUN_MODULES": "Login,Sales"}), "둘 다 → 전체 실행 + 루틴 모듈")
check(d.slot_target({"at": "14:00", "run": ["Login", "Hold"]}, off=["Hold"]) == (None, {}), "업체가 안 쓰는 모듈을 빼면 돌릴 게 없다 → 안 띄움")
check(d.slot_target({"at": "14:00", "run": ["Login", "Logistics", "Output"]}, off=["Logistics"]) == (None, {}), "물류관리를 빼면 출력도 빠진다")
d.apply_schedule({"enabled": True, "days": list(range(7)), "slots": [{"at": "10:00"}, {"at": "11:00", "run": ["Logistics"]}]})
sch = st.read_settings()["schedule"]
check(sch["slots"] == [{"at": "10:00"}, {"at": "11:00", "run": ["Login", "Logistics"]}] and sch["next_slot"] in ("10:00", "11:00"),
      f"줄 적용 → 저장·다음 줄 ({sch['next_slot']})")
check(d.apply_schedule({"enabled": False, "days": [], "slots": []}) is True and st.read_settings()["schedule"]["slots"] == [],
      "끌 때는 요일·줄이 비어도 된다")
d.apply_schedule({"enabled": True, "days": list(range(7)), "times": ["23:55", "00:00", "12:00"]})   # 6절이 기대하는 상태로 되돌린다

print("\n=== 6. 스케줄러 ===")
d.LAUNCHED.clear()
sched = d.Scheduler()


def set_next(delta_sec):
    c = st.read_settings()
    c["schedule"]["next_run_at"] = (dt.datetime.now() + dt.timedelta(seconds=delta_sec)).isoformat(timespec="seconds")
    st.write_settings(c)


set_next(600)
sched.tick()
check(d.LAUNCHED == [], "예약 시각 전에는 띄우지 않음")

set_next(-3)
st.start("routine", ["a", "b"]); st.flush()
sched.tick()
check(d.LAUNCHED == [] and "돌고 있어" in (sched.waiting_reason or ""), f"RPA 진행 중이면 대기: {sched.waiting_reason}")
st.finish("success")
sched.tick()
check(d.LAUNCHED == ["all:auto"], "끝나면 자동 실행")
sch = st.read_settings()["schedule"]
nxt = st.parse_iso(sch["next_run_at"])
check(sch["last_launch_by"] == "auto" and nxt and nxt > dt.datetime.now(), f"띄운 뒤 다음 예약으로 넘어감 ({sch['next_run_at']})")
check(nxt.strftime("%H:%M") in [s["at"] for s in sch["slots"]], "다음 시각이 예약 시간 중 하나")
d._active["until"] = 0; d._active["proc"] = None

before = sch["next_run_at"]
d.launch_run_all("manual:admin")
check(st.read_settings()["schedule"]["next_run_at"] == before, "수동 실행은 예약 시각을 바꾸지 않음")
d._active["until"] = 0

print("\n=== 6-2. 옵저버가 떠 있으면 (기록하는 사람과 RPA 가 화면을 두고 부딪히지 않게) ===")
saved = list(d.LAUNCHED)
RPA = os.path.dirname(os.path.abspath(st.__file__))
holder = subprocess.Popen(
    [sys.executable, "-c", f"import os, sys; sys.path.insert(0, {RPA!r}); import rpa_status as st; "
                           "print(st.hold_lock(st.OBSERVER_LOCK), os.getpid(), flush=True); sys.stdin.read()"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
held, pid = (holder.stdout.readline().split() + ["", "0"])[:2]
check(held == "True", "옵저버(다른 프로세스)가 잠금을 잡음")
check(st.observer_open() is True, "잠금이 있으면 옵저버가 떠 있다")
check(st.hold_lock(st.OBSERVER_LOCK) is False, "옵저버는 둘이 못 뜬다")
set_next(-3)
sched.tick()
check(d.LAUNCHED == saved and "옵저버" in (sched.waiting_reason or ""), f"예약 시각이 와도 기다림: {sched.waiting_reason}")
try:
    d.launch_run_all("cloud")
    check(False, "옵저버가 떠 있는데 실행 단추가 띄움")
except RuntimeError as e:
    check("옵저버" in str(e) and d.LAUNCHED == saved, f"실행 단추는 까닭과 함께 거절: {e}")
if pid != "0":
    os.kill(int(pid), signal.SIGTERM)   # 잠금을 쥔 파이썬을 바로 죽인다 (venv 의 python.exe 는 진짜 파이썬을 자식으로 띄운다)
holder.stdin.close()
holder.wait()
check(st.observer_open() is False, "옵저버가 끝나면 (죽어도) 잠금이 풀린다")
sched.tick()
check(d.LAUNCHED == saved + ["all:auto"], "옵저버가 닫히면 미룬 예약이 돈다")
d.LAUNCHED[:] = saved
d._active["until"] = 0
d._active["proc"] = None

print("\n=== 6-3. 토큰이 없으면 (2026-10-06 - 에이전트가 TOKEN_GATE 를 단다) ===")
saved, asked = list(d.LAUNCHED), []
NO_TOKENS = "토큰이 없습니다 (남은 0개). 충전한 뒤 실행하세요"


def no_tokens(target):
    asked.append(target)
    raise RuntimeError(NO_TOKENS)


d.TOKEN_GATE = no_tokens
try:
    try:
        d.launch("routine", "cloud")
        check(False, "토큰이 없는데 실행 단추가 띄움")
    except RuntimeError as e:
        check(str(e) == NO_TOKENS and d.LAUNCHED == saved and asked == ["routine"], f"실행 단추는 까닭과 함께 거절: {e}")
    set_next(-3)
    sched.tick_safe()
    sch = st.read_settings()["schedule"]
    check(d.LAUNCHED == saved and asked[-1] == "all" and sch["last_error"] == NO_TOKENS
          and st.parse_iso(sch["next_run_at"]) > dt.datetime.now(),
          f"예약은 건너뛰고 까닭을 그대로 남긴 뒤 다음 예약으로 ({sch['last_error']})")
    d.TOKEN_GATE = lambda target: None
    set_next(-3)
    sched.tick_safe()
    check(d.LAUNCHED == saved + ["all:auto"] and st.read_settings()["schedule"]["last_error"] is None,
          "토큰이 있으면 예약이 돌고 남은 까닭은 지워진다")
finally:
    d.TOKEN_GATE = None
d.LAUNCHED[:] = saved
d._active["until"] = 0
d._active["proc"] = None

print("\n=== 6-4. 고르기 줄은 그 모듈만 넘긴다 ===")
saved = list(d.LAUNCHED)
d.apply_schedule({"enabled": True, "days": list(range(7)), "slots": [{"at": "11:00", "run": ["Logistics"]}]})
c = st.read_settings(); c["schedule"]["next_run_at"] = (dt.datetime.now() - dt.timedelta(seconds=3)).isoformat(timespec="seconds"); st.write_settings(c)
sched.tick()
check(d.LAUNCHED == saved + ["routine:auto"] and d.LAUNCHED_ENV[-1] == {"RPA_RUN_MODULES": "Login,Logistics", "RPA_RUN_TRIGGER": "auto"},
      f"next_slot 의 줄대로 루틴만 + 이번 실행 모듈 ({d.LAUNCHED_ENV[-1:]})")
d.LAUNCHED[:] = saved; d._active["until"] = 0; d._active["proc"] = None

print("\n=== 7. 대시보드를 다시 켰을 때 (resync) ===")
set_next(-3600)
s2 = d.Scheduler(); s2.resync()
sch = st.read_settings()["schedule"]
check(s2.skipped_at is not None and st.parse_iso(sch["next_run_at"]) > dt.datetime.now(), "1시간 전에 지난 예약 -> 건너뛰고 다음 예약으로")
set_next(-60)
before = st.read_settings()["schedule"]["next_run_at"]
s3 = d.Scheduler(); s3.resync()
check(st.read_settings()["schedule"]["next_run_at"] == before and s3.skipped_at is None, "1분 전에 지난 예약 -> 그대로 둬서 곧 돈다")
c = st.read_settings(); c["schedule"]["next_run_at"] = None; st.write_settings(c)
s4 = d.Scheduler(); s4.resync()
check(st.read_settings()["schedule"]["next_run_at"] is not None and s4.skipped_at is None, "다음 시각이 없으면 새로 계산")
d.apply_schedule({"enabled": False, "days": WK, "times": ["09:00"]})
s5 = d.Scheduler(); s5.resync()
check(st.read_settings()["schedule"]["next_run_at"] is None, "꺼져 있으면 resync 가 아무것도 안 함")
sched.tick()
check(d.LAUNCHED == ["all:auto", "all:manual:admin"], "꺼진 뒤 tick -> 띄우지 않음")

print("\n=== 9. 업체 한도·안 쓰는 모듈 (에이전트가 policy 를 적는다) ===")
d.apply_schedule({"enabled": True, "days": list(range(7)), "slots": [{"at": "10:00"}, {"at": "11:00", "run": ["Hold"]}, {"at": "12:00"}]})
check([s["at"] for s in d.active_slots(st.read_settings()["schedule"])] == ["10:00", "11:00", "12:00"], "한도를 모르면 자르지 않는다")
check(d.set_policy(2, ["Hold"]) is True and d.set_policy(2, ["Hold"]) is False, "정책을 적고, 같으면 다시 안 쓴다")
sch = st.read_settings()["schedule"]
check([s["at"] for s in d.active_slots(sch)] == ["10:00", "11:00"] and len(d.schedule_view()["slots"]) == 3
      and sch["slots"][2] == {"at": "12:00"} and sch["next_slot"] in ("10:00", "11:00"),
      "한도 2 → 시각 순 앞 2줄만 돈다 (줄은 지우지 않는다 - Review Focus 3)")
saved = list(d.LAUNCHED)
c = st.read_settings(); c["schedule"]["next_slot"] = "12:00"; c["schedule"]["next_run_at"] = (dt.datetime.now() - dt.timedelta(seconds=3)).isoformat(timespec="seconds"); st.write_settings(c)
sched.tick()
check(d.LAUNCHED == saved and st.read_settings()["schedule"]["next_slot"] in ("10:00", "11:00"), "가리키던 줄이 한도로 빠졌으면 띄우지 않고 다음 줄로")
c = st.read_settings(); c["schedule"]["next_slot"] = "11:00"; c["schedule"]["next_run_at"] = (dt.datetime.now() - dt.timedelta(seconds=3)).isoformat(timespec="seconds"); st.write_settings(c)
sched.tick_safe()
check(d.LAUNCHED == saved and st.read_settings()["schedule"]["last_error"] == "업체가 쓰지 않는 모듈만 남아 건너뜁니다",
      f"줄의 모듈이 모두 업체가 안 쓰는 것 → 건너뛰고 까닭 ({st.read_settings()['schedule']['last_error']})")
d.set_policy(0, [])
check(d.active_slots(st.read_settings()["schedule"]) == [] and d.schedule_view()["next_run_at"] is None, "한도 0 → 아무것도 안 돈다")
d._active["until"] = 0; d._active["proc"] = None

print("\n=== 8. 화면에 주는 값 ===")
sess = {"user_id": "admin", "role": "admin", "admin_code": "erpiatest2"}
try:
    tv = d.settings_view(sess)
    check("schedule_limits" in tv and tv["schedule_limits"]["minute_step"] == 5 and "interval_min_limits" not in tv, "settings_view 제한값")
except Exception as e:
    check(False, f"settings_view 호출 실패: {type(e).__name__}: {e}")

print("\n=== 10. 업데이트 대기 중이면 새 실행을 안 띄운다 (Review Focus 4) ===")
import rpa_update as up  # noqa: E402
d._active["until"] = 0; d._active["proc"] = None
os.environ["RPA_PROGRAMDATA"] = os.path.join(tmp, "pd")
for state in up.BUSY_STATES:
    up.write_state({"state": state})
    try:
        d.launch("routine", "manual:admin"); check(False, f"{state}: 띄움")
    except RuntimeError as e:
        check(str(e) == "업데이트 중이라 잠시 실행할 수 없습니다", f"{state}: 단추 실행 거절 ({e})")
    check(sched.busy() == "업데이트 중이라 잠시 실행할 수 없습니다", f"{state}: 예약·반복도 기다린다")
up.write_state({"state": "done"})
check(sched.busy() is None, "done 이면 다시 띄울 수 있다")
os.environ.pop("RPA_PROGRAMDATA")

print("\n=== 줄마다 요일 (사용자 2026-10-08) ===")
one = d.normalize_slots([{"at": "09:00", "days": [4, 0, 0]}, {"at": "09:00", "days": [5], "run": ["Logistics"]}])
check(one == [{"at": "09:00", "days": [0, 4]}, {"at": "09:00", "days": [5], "run": ["Login", "Logistics"]}],
      f"줄마다 요일을 저장 - 요일이 다르면 같은 시각도 된다 ({one})")
for bad, why in (([{"at": "09:00", "days": []}], "요일을 하나 이상"),
                 ([{"at": "09:00", "days": [0, 1]}, {"at": "09:00", "days": [1]}], "같은 시각"),
                 ([{"at": "10:00", "until": "11:00", "run": ["Hold"], "days": [0]}, {"at": "10:30", "days": [0, 6]}], "겹칩니다")):
    try:
        d.normalize_slots(bad); check(False, f"거부: {why}")
    except ValueError as e:
        check(why in str(e), f"거부: {why} ({e})")
check(len(d.normalize_slots([{"at": "10:00", "until": "11:00", "run": ["Hold"], "days": [0]}, {"at": "10:30", "days": [6]}])) == 2,
      "요일이 다르면 반복 시간대 안의 시각도 된다")
SCH = {"enabled": True, "days": [0, 1, 2, 3, 4, 5, 6],
       "slots": [{"at": "09:00", "days": [0, 1, 2, 3, 4]}, {"at": "09:00", "days": [5], "run": ["Logistics"]}, {"at": "10:00"}]}
when, slot = d.next_due(SCH, at(4, 9, 30))                    # 금 09:30 -> 금 10:00 (요일 없는 줄은 공통 요일)
check(when == at(4, 10, 0) and slot == {"at": "10:00"}, f"요일 없는 줄은 공통 요일 ({when}, {slot})")
when, slot = d.next_due(SCH, at(4, 10, 0))                    # 금 10:00 -> 토 09:00 은 토요일 줄
check(when == at(5, 9, 0) and slot.get("run") == ["Logistics"], f"토요일 09:00 은 토요일 줄 ({when}, {slot})")
sch2 = dict(SCH, next_run_at=at(5, 9, 0).isoformat(timespec="seconds"), next_slot="09:00")
check(d.slot_of(sch2).get("run") == ["Logistics"], "같은 시각 줄이 둘이면 그날 요일의 줄을 띄운다")
check(d.next_due(dict(SCH, slots=[{"at": "09:00", "days": [2]}]), at(0, 8, 0))[0] == at(2, 9, 0), "수요일만 고른 줄은 수요일에")
WSCH = {"enabled": True, "days": [0, 1, 2, 3, 4], "slots": [{"at": "10:00", "until": "11:00", "run": ["Hold"], "days": [5]}]}
check(d.open_window(WSCH, at(5, 10, 30)) is not None and d.open_window(WSCH, at(0, 10, 30)) is None,
      "반복 시간대도 그 줄의 요일에만 열린다")
check(d.schedule_label(SCH) == "평일 09:00, 토 09:00 물류관리, 매일 10:00", f"요약 글은 줄마다 요일 ({d.schedule_label(SCH)})")
check(d.schedule_label({"days": [0, 1, 2, 3, 4], "slots": [{"at": "09:00"}]}) == "평일 09:00", "줄마다 요일이 없으면 지금처럼")

shutil.rmtree(tmp, ignore_errors=True)
print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
