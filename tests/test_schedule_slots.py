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
              [f"{h:02d}:00" for h in range(4)]):
    label = bad_t if not isinstance(bad_t, list) or len(bad_t) < 5 else f"{len(bad_t)}개"
    try:
        d.normalize_times(bad_t); check(False, f"시간 거부 {label!r}")
    except ValueError:
        check(True, f"시간 거부 {label!r}")
check(len(d.normalize_times([f"{h:02d}:00" for h in range(3)])) == 3, "3개까지는 받음")

print("\n=== 3. 이름표 ===")
check(d.days_label(list(range(7))) == "매일", "매일")
check(d.days_label([4, 3, 2, 1, 0]) == "평일", "평일")
check(d.days_label([6, 5]) == "주말", "주말")
check(d.days_label([0, 2, 4]) == "월·수·금", "월·수·금")
check(d.schedule_label({"days": WK, "times": ["09:00", "13:00"]}) == "평일 09:00, 13:00", "평일 09:00, 13:00")
check(d.schedule_label({"days": WK, "times": ["08:00", "10:00", "12:00", "14:00", "16:00"]}) == "평일 08:00, 10:00, 12:00 외 2개", "많으면 앞 3개 + 외 N개")

print("\n=== 4. 기본값과 예전 설정 ===")
cfg = st.read_settings()
check(cfg["schedule"]["enabled"] is False and cfg["schedule"]["days"] == WK and cfg["schedule"]["times"] == ["09:00"], "기본: 꺼짐, 평일 09:00")
old = st.read_settings(); old["schedule"]["interval_min"] = 15; st.write_settings(old)
check(d.schedule_view()["days"] == WK and "interval_min" not in d.schedule_view(), "예전 interval_min 이 있어도 새 모양으로 보임")

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
check(changed and sch["times"] == ["00:00", "12:00", "23:55"] and sch["days"] == list(range(7)), "켜기 적용 -> 정렬해 저장")
check("interval_min" not in sch, "적용하면 예전 interval_min 은 지움")
nxt = st.parse_iso(sch["next_run_at"])
check(nxt == d.next_slot(sch["days"], sch["times"], now) or nxt == d.next_slot(sch["days"], sch["times"], dt.datetime.now()),
      f"next_run_at = 다음 예약 ({sch['next_run_at']})")
check(d.apply_schedule({"enabled": True, "days": [6, 5, 4, 3, 2, 1, 0], "times": ["12:00", "00:00", "23:55"]}) is False,
      "같은 값(순서만 다름) 재적용 -> changed=False")
sv = d.schedule_view()
check(sv["label"] == "매일 00:00, 12:00, 23:55" and sv["times"] and sv["days"], f"schedule_view 이름표: {sv['label']}")

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
check(nxt.strftime("%H:%M") in sch["times"], "다음 시각이 예약 시간 중 하나")
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

print("\n=== 8. 화면에 주는 값 ===")
sess = {"user_id": "admin", "role": "admin", "admin_code": "erpiatest2"}
try:
    tv = d.settings_view(sess)
    check("schedule_limits" in tv and tv["schedule_limits"]["minute_step"] == 5 and "interval_min_limits" not in tv, "settings_view 제한값")
except Exception as e:
    check(False, f"settings_view 호출 실패: {type(e).__name__}: {e}")

shutil.rmtree(tmp, ignore_errors=True)
print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
