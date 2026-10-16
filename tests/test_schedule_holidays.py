# -*- coding: utf-8 -*-
"""공휴일·업체 휴무일에는 자동 실행을 쉰다 (사용자 2026-10-15). 사람이 누르는 실행은 상관없다. 실제로 띄우지 않는다 (DRY_RUN + 격리 폴더).
    .venv\\Scripts\\python.exe tests\\test_schedule_holidays.py
"""
import datetime as dt
import io
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.environ["RPA_STATUS_DIR"] = tempfile.mkdtemp(prefix="rpa_holiday_")
os.environ["RPA_DASHBOARD_DRY_RUN"] = "1"
os.environ["RPA_OBSERVER_LOCK"] = rf"Local\AFTER_MARKET_RPA_OBSERVER_HOLIDAY_TEST_{os.getpid()}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import kr_holidays  # noqa: E402
import rpa_status as st  # noqa: E402
import rpa_dashboard as d  # noqa: E402

fails = []


def check(cond, what, detail=""):
    print(("PASS " if cond else "FAIL ") + what + ("" if cond else f"  {detail}"))
    if not cond:
        fails.append(what)


D = dt.date.fromisoformat
T = dt.datetime.fromisoformat
WEEKDAY_9 = {"enabled": True, "days": [0, 1, 2, 3, 4], "slots": [{"at": "09:00"}]}

print("=== 1. 공휴일 표 ===")
check(all(D(k).isoformat() == k and v.strip() for k, v in kr_holidays.HOLIDAYS.items()), "날짜는 모두 YYYY-MM-DD, 이름이 있다")
check(kr_holidays.LAST_YEAR >= 2027 and any(k.startswith(f"{kr_holidays.LAST_YEAR}-") for k in kr_holidays.HOLIDAYS),
      f"{kr_holidays.LAST_YEAR}년까지 들어 있다")
for day, name in (("2026-12-25", "성탄절"), ("2027-02-09", "대체공휴일"), ("2027-09-15", "추석"), ("2027-12-27", "대체공휴일"),
                  ("2026-07-17", "제헌절"), ("2027-07-17", "제헌절"), ("2027-07-19", "대체공휴일 (제헌절)")):
    check(name in kr_holidays.HOLIDAYS.get(day, ""), f"{day} {name}")
for day, name in (("2026-05-01", "노동절"), ("2027-05-01", "노동절"), ("2027-05-03", "대체공휴일 (노동절)")):
    check(name in kr_holidays.HOLIDAYS.get(day, ""), f"{day} {name}")
subs = [k for k, v in kr_holidays.HOLIDAYS.items() if v.startswith("대체공휴일")]
check(subs and all(D(k).weekday() < 5 for k in subs), "대체공휴일은 모두 평일", [(k, D(k).weekday()) for k in subs])

print("=== 2. 그날 쉬나 ===")
sch = st.read_settings()["schedule"]
check(sch.get("skip_holidays") is True and sch.get("off_dates") == [], "기본: 공휴일 쉬기 켬, 업체 휴무일 없음", sch)
check(d.day_off(sch, D("2026-12-25")) == "성탄절" and d.day_off(sch, D("2026-12-24")) is None, "성탄절은 쉬고 전날은 돈다")
check(d.day_off(dict(sch, skip_holidays=False), D("2026-12-25")) is None, "공휴일 쉬기를 끄면 공휴일에도 돈다")
check(d.day_off(dict(sch, skip_holidays=False, off_dates=["2026-11-20"]), D("2026-11-20")) == "업체 휴무일",
      "업체 휴무일은 공휴일 쉬기와 상관없이 쉰다")

print("=== 3. 다음 예약 ===")
base = dict(sch, **WEEKDAY_9)
when, _ = d.next_due(base, T("2026-12-24T10:00"))
check(when == T("2026-12-28T09:00"), "목 12/24 10시 → 성탄절(금)·주말을 건너 월 12/28 09:00", when)
when, _ = d.next_due(dict(base, skip_holidays=False), T("2026-12-24T10:00"))
check(when == T("2026-12-25T09:00"), "공휴일 쉬기를 끄면 금 12/25 09:00", when)
long_off = [(D("2026-11-02") + dt.timedelta(days=i)).isoformat() for i in range(40)]      # 40일 휴가 (8일보다 길게)
when, _ = d.next_due(dict(base, off_dates=long_off), T("2026-11-01T10:00"))
check(when == T("2026-12-14T09:00"), "긴 휴무(40일) 뒤 첫 평일도 찾는다 (예전엔 8일까지만 봤다)", when)
win = dict(base, slots=[{"at": "10:00", "until": "11:00", "rest_min": 2, "run": ["Login", "Logistics"]}])
check(d.open_window(win, T("2026-12-25T10:30")) is None and d.open_window(win, T("2026-12-24T10:30")) is not None,
      "반복 시간대도 공휴일에는 열리지 않는다")

print("=== 4. [적용] ===")
d.NOW = lambda: T("2026-12-01T08:00")
check(d.apply_schedule(dict(WEEKDAY_9)) is True, "공휴일 값 없이 적용 (옛 화면)")
s = st.read_settings()["schedule"]
check(s["skip_holidays"] is True and s["off_dates"] == [], "옛 화면이 보내면 공휴일 값은 그대로 (기본 켬)", s)
check(d.apply_schedule(dict(WEEKDAY_9, skip_holidays=False, off_dates=["2026-12-31", "2026-12-31", "2026-11-30", "2027-01-04"])) is True,
      "공휴일 쉬기 끔 + 휴무일")
s = st.read_settings()["schedule"]
check(s["skip_holidays"] is False and s["off_dates"] == ["2026-12-31", "2027-01-04"], "지난 날은 빼고, 겹치면 하나로, 날짜 순", s["off_dates"])
check(d.apply_schedule(dict(WEEKDAY_9, skip_holidays=False, off_dates=["2027-01-04", "2026-12-31"])) is False, "같은 값이면 바뀐 것 없음")
d.apply_schedule(dict(WEEKDAY_9, skip_holidays=True, off_dates=["2026-12-01"]))
check(st.read_settings()["schedule"]["next_run_at"] == "2026-12-02T09:00:00", "오늘을 휴무일로 넣으면 다음 예약을 다시 잡는다 (화 12/1 → 수 12/2)",
      st.read_settings()["schedule"]["next_run_at"])
for bad, why in ((["2026-13-01"], "없는 날"), (["20261231"], "모양"), ([20261231], "글자 아님"), ("2026-12-31", "목록 아님"),
                 ([(D("2026-12-02") + dt.timedelta(days=i)).isoformat() for i in range(101)], "100개 넘음")):
    try:
        d.apply_schedule(dict(WEEKDAY_9, off_dates=bad))
        check(False, f"휴무일 거절: {why}")
    except ValueError as e:
        check("휴무일" in str(e), f"휴무일 거절: {why}", e)
d.apply_schedule(dict(WEEKDAY_9, skip_holidays=True, off_dates=["2026-12-31"]))
d.apply_schedule(dict(WEEKDAY_9, skip_holidays=True))           # 화면에서 마지막 칩을 뺐다 - Realtime DB 는 빈 목록 off_dates: [] 를 떨어뜨린다
check(st.read_settings()["schedule"]["off_dates"] == [], "마지막 휴무일을 빼고 적용하면 지워진다 (빈 목록이 DB 에서 사라져도 - 검토 2026-10-16)",
      st.read_settings()["schedule"]["off_dates"])
d.apply_schedule(dict(WEEKDAY_9, skip_holidays=True, off_dates=["2026-12-31"]))
d.apply_schedule(dict(WEEKDAY_9))
check(st.read_settings()["schedule"]["off_dates"] == ["2026-12-31"], "옛 화면 (공휴일 값을 아예 모름) 이 보내면 휴무일은 그대로")
try:
    d.apply_schedule(dict(WEEKDAY_9, skip_holidays="yes"))
    check(False, "공휴일 쉬기는 true/false")
except ValueError:
    check(True, "공휴일 쉬기는 true/false")

print("=== 5. 예약기: 예전에 잡아 둔 시각이 공휴일이면 ===")
d.apply_schedule(dict(WEEKDAY_9, skip_holidays=True, off_dates=[]))
c = st.read_settings()
c["schedule"]["next_run_at"], c["schedule"]["next_slot"] = "2026-12-25T09:00:00", "09:00"     # 공휴일을 모르던 버전이 잡아 둔 값
st.write_settings(c)
d.NOW = lambda: T("2026-12-25T09:00:05")
d.LAUNCHED.clear()
sched = d.Scheduler()
sched.tick()
s = st.read_settings()["schedule"]
check(d.LAUNCHED == [] and s["next_run_at"] == "2026-12-28T09:00:00", "띄우지 않고 다음 평일로 넘긴다", (d.LAUNCHED, s["next_run_at"]))
d.NOW = lambda: T("2026-12-28T09:00:05")
sched.tick()
check(d.LAUNCHED == ["all:auto"], "다음 평일에는 돈다", d.LAUNCHED)

d.apply_schedule(dict(WEEKDAY_9, skip_holidays=True, off_dates=[]))
c = st.read_settings()
c["schedule"]["next_run_at"], c["schedule"]["next_slot"] = "2026-12-24T09:00:00", "09:00"     # 목 09:00 - PC 가 자고 있었다
st.write_settings(c)
d.NOW = lambda: T("2026-12-25T10:00:00")                                                       # 성탄절에 깼다
d.LAUNCHED.clear()
sched.tick()
s = st.read_settings()["schedule"]
check(d.LAUNCHED == [] and s["next_run_at"] == "2026-12-28T09:00:00", "밀린 실행도 오늘이 공휴일이면 띄우지 않는다 (검토 2026-10-16)",
      (d.LAUNCHED, s["next_run_at"]))

print("=== 6. 화면에 보내는 값 ===")
d.NOW = lambda: T("2026-12-20T08:00")
d.apply_schedule(dict(WEEKDAY_9, skip_holidays=True, off_dates=["2026-12-31"]))
v = d.schedule_view()
check(v["version"] >= 4 and v["skip_holidays"] is True and v["off_dates"] == ["2026-12-31"], "판 4 + 공휴일 값", v)
check(v["next_off"] == {"date": "2026-12-25", "name": "성탄절"}, "가까운 쉬는 날 (화면에 '12/25 성탄절 쉼')", v.get("next_off"))
check(v["holidays_until"] == f"{kr_holidays.LAST_YEAR}-12-31", "공휴일 표가 언제까지인지", v.get("holidays_until"))
d.apply_schedule(dict(WEEKDAY_9, skip_holidays=False, off_dates=["2026-12-31"]))
check(d.schedule_view()["next_off"] == {"date": "2026-12-31", "name": "업체 휴무일"}, "공휴일 쉬기를 끄면 업체 휴무일만")

print("=== 7. 에이전트가 웹에 올리는 값 (schedule_live) ===")
d.NOW = lambda: T("2026-12-20T08:00")
d.apply_schedule(dict(WEEKDAY_9, skip_holidays=True, off_dates=["2026-12-21", "2026-12-31"]))
raw = st.read_settings()["schedule"]
raw["off_dates"] = ["2026-12-01"] + raw["off_dates"]                       # 저장한 뒤 지난 날
live = d.schedule_live(raw, dt.date(2026, 12, 22))
check(live["next_off"] == {"date": "2026-12-25", "name": "성탄절"} and live["holidays_until"] == f"{kr_holidays.LAST_YEAR}-12-31",
      "가까운 휴무일·공휴일 표 끝이 들어간다 (예전엔 settings.json 그대로 올려 화면 안내가 안 떴다 - 검토 2026-10-16)", live)
check(live["off_dates"] == ["2026-12-31"] and live["version"] == st.SCHEDULE_VERSION and live["slots"] == raw["slots"],
      "지난 휴무일은 빼고, 나머지 값은 그대로", live)
check(raw["off_dates"][0] == "2026-12-01", "settings.json 값은 건드리지 않는다 (복사본)")
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "firebase", "agent", "agent.py"), encoding="utf-8").read()
check("dash.schedule_live(" in src and 'snap["schedule"] = st.read_settings().get("schedule")' not in src, "에이전트는 schedule_live 를 올린다")

print("\n" + ("모두 통과" if not fails else f"실패 {len(fails)}건: {fails}"))
sys.exit(1 if fails else 0)
