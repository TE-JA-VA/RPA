"""돌지 않은 예약(꺼져 있던 동안 지남·띄우기 직전 거절·앞 실행을 기다리다 지남)을 실행 기록에 남기나, 다음 실행 3분 전에
절전에서 깨우고 실행이 끝날 때까지 깨어 있나 (사용자 2026-10-21).
실제로 띄우지 않는다 (DRY_RUN + 격리 폴더, exe 없이 돈다)."""
import datetime as dt
import io
import os
import socket
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
tmp = tempfile.mkdtemp(prefix="rpa_missed_")
os.environ["RPA_STATUS_DIR"] = tmp
os.environ["RPA_DASHBOARD_DRY_RUN"] = "1"
os.environ["RPA_OBSERVER_LOCK"] = f"AFTER_MARKET_RPA_OBSERVER_MISSED_TEST_{os.getpid()}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 저장소 (이 시험의 위 폴더)
import rpa_status as st  # noqa: E402
import rpa_dashboard as d  # noqa: E402

fails = []


def check(what, cond, detail=""):
    print(("통과 " if cond else "실패 ") + what + ("" if cond else f"  ({detail})"))
    if not cond:
        fails.append(what)


def rows(kind):
    return sorted((r for r in st.read_history() if r["run_id"].endswith(f"_{kind}_{socket.gethostname()}")), key=lambda r: r["started_at"])


MON = dt.datetime(2026, 9, 14)      # 월요일, 공휴일 아님
clock = [MON]
d.NOW = lambda: clock[0]
d.apply_schedule({"enabled": True, "days": [0, 1, 2, 3, 4],
                  "slots": [{"at": "06:00"}, {"at": "09:00", "run": ["Logistics"]}, {"at": "13:00", "until": "15:00", "rest_min": 10, "run": ["Sales"]}]})
sched = d.Scheduler()


def set_next(when):
    cfg = st.read_settings()
    cfg["schedule"]["next_run_at"] = when.isoformat(timespec="seconds")
    cfg["schedule"]["next_slot"] = when.strftime("%H:%M")      # advance 처럼 둘 다
    st.write_settings(cfg)


print("=== 1. 꺼져 있던 동안 지난 예약 (켤 때 resync) ===")
set_next(MON.replace(hour=6))
clock[0] = MON + dt.timedelta(days=1, hours=8, minutes=41)    # 화 08:41 에 켜짐
sched.resync()
got = rows("missed")
check("월 06:00·09:00·13:00~15:00 반복 시간대·화 06:00 넷이 기록된다 (화 09:00 은 아직)",
      [r["started_at"] for r in got] == ["2026-09-14T06:00:00", "2026-09-14T09:00:00", "2026-09-14T13:00:00", "2026-09-15T06:00:00"],
      [r["started_at"] for r in got])
check("상태는 '오류'(crashed - 웹이 아는 값, 도넛은 노랑), 소요 0, 토큰 0, 예약 표시",
      all(r["state"] == "crashed" and r["started_at"] == r["finished_at"] and not r.get("cost") and r.get("trigger") == "auto" for r in got),
      got[:1])
check("프로그램 칸: 전체 실행 줄은 ACTOR, 물류관리·매출처리 줄은 PROCESS",
      [r["program"] for r in got] == ["prepare", "routine", "routine", "prepare"], [r["program"] for r in got])
check("까닭 글: 예약 시각과 원인을 단정하지 않는 말, 반복 시간대는 그 시간대 - run_id 에 PC 이름 (여러 PC 가 같은 시각을 놓쳐도 안 겹침)",
      got[0]["reason"] == "06:00 예약이 실행되지 않았습니다. " + d.OFF_TEXT and got[0]["run_id"].endswith(socket.gethostname())
      and got[2]["reason"].startswith("13:00~15:00 반복 시간대가 실행되지 않았습니다."), [r["reason"] for r in got])
check("다음 예약은 지금 뒤로 (예전처럼 건너뛴다)", st.read_settings()["schedule"]["next_run_at"] == "2026-09-15T09:00:00",
      st.read_settings()["schedule"]["next_run_at"])
sched.resync()
check("다시 켜도 같은 예약을 또 남기지 않는다", len(rows("missed")) == 4, len(rows("missed")))

print("=== 2. 오래 꺼져 있던 PC - 줄 수 상한 ===")
set_next(MON.replace(hour=6) - dt.timedelta(days=21))
clock[0] = MON.replace(hour=5)
sched.resync()
new = [r for r in rows("missed") if r["started_at"] < "2026-09-14"]
more = rows("missed_more")
check(f"상한 {d.MISSED_RECORD_MAX}줄 + '그 밖 n회' 한 줄 (3주 × 평일 5일 × 3줄 = 45회)",
      len(new) == d.MISSED_RECORD_MAX and len(more) == 1 and "그 밖에 예약 25회가 실행되지 않았습니다" in more[0]["reason"],
      (len(new), [r["reason"] for r in more]))

print("=== 3. 띄우기 직전 거절 (토큰 0 등) ===")
set_next(MON.replace(hour=9))
clock[0] = MON.replace(hour=9, second=3)
sched._record_error("잔여 토큰이 없습니다 (남은 토큰 수 : 0개).\n토큰을 충전해주십시오.")
got = rows("rejected")
check("띄울 차례의 예약이 거절되면 그 예약을 기록 (줄바꿈은 빈칸으로)",
      len(got) == 1 and got[0]["started_at"] == "2026-09-14T09:00:00" and got[0]["program"] == "routine"
      and got[0]["reason"] == "09:00 예약이 실행되지 않았습니다. 잔여 토큰이 없습니다 (남은 토큰 수 : 0개). 토큰을 충전해주십시오.", got)
check("예약 칸 오류 글은 예전 그대로 남는다", st.read_settings()["schedule"]["last_error"].startswith("잔여 토큰이 없습니다"))
clock[0] = MON.replace(hour=10)
sched._record_error("ValueError: 다른 오류")
check("차례가 아닌 때의 오류(다음 예약이 아직)는 예약 기록을 남기지 않는다", len(rows("rejected")) == 1, len(rows("rejected")))
set_next(MON.replace(hour=9) + dt.timedelta(days=1))
clock[0] = MON.replace(hour=9, second=3) + dt.timedelta(days=1)
sched._record_error(d.UNUSED_ONLY)
check("'업체가 사용하지 않는 모듈만' 은 설정대로라 기록하지 않는다 (예약 칸 글은 그대로)", len(rows("rejected")) == 1
      and st.read_settings()["schedule"]["last_error"] == d.UNUSED_ONLY, len(rows("rejected")))

print("=== 4. 반복 회차 거절 ===")
clock[0] = MON.replace(hour=13, minute=5)
win = d.open_window(st.read_settings()["schedule"], clock[0])
_saved_launch_slot = d.launch_slot


def refuse(*a, **k):
    raise RuntimeError("잔여 토큰이 없습니다 (남은 토큰 수 : 0개).")


d.launch_slot = refuse
sched.tick_repeat(win, clock[0])
d.launch_slot = _saved_launch_slot
got = [r for r in rows("rejected") if r.get("trigger") == "repeat"]
check("반복 회차가 거절되면 기록 (반복 표시, 그 시각)", len(got) == 1 and got[0]["started_at"] == "2026-09-14T13:05:00"
      and got[0]["reason"].startswith("13:05 반복 회차가 실행되지 않았습니다. 잔여 토큰이 없습니다"), got)
check("반복은 예전처럼 멈춘다", bool((st.read_settings()["schedule"].get("repeat") or {}).get("stopped")))
# 업체가 안 쓰는 모듈만 든 줄은 설정대로라 남기지 않는다 - 반복 시간대면 매일 한 줄씩 쌓였다 (검토 10-22). 모든 기록이 record_missed 를 지난다
sch = st.read_settings()["schedule"]
d.record_missed(dict(sch, policy={"off": ["Sales"]}), [(clock[0], win)], lambda t, s: "x", "unused")
d.record_missed(dict(sch, policy={"off": ["Logistics"]}), [(clock[0], win)], lambda t, s: "x", "used")
check("안 쓰는 모듈(매출처리)만 든 반복 줄은 기록하지 않고, 다른 모듈을 끈 업체면 기록한다",
      not rows("unused") and len(rows("used")) == 1, (rows("unused"), rows("used")))

print("=== 5. 앞 실행을 기다리는 사이 지난 다른 예약 (launch 의 advance) ===")
fake_exe = os.path.join(tmp, "Run_All.bat")
open(fake_exe, "w").close()
_saved_target_path = d.target_path
d.target_path = lambda target: fake_exe
set_next(MON.replace(hour=6) + dt.timedelta(days=2))     # 수 06:00 예약을
clock[0] = MON + dt.timedelta(days=2, hours=9, minutes=30)  # 수 09:30 에야 띄운다 (앞 실행이 길었다)
d.launch_slot(d.slot_of(st.read_settings()["schedule"]))
d.target_path = _saved_target_path
got = rows("merged")
check("그 사이 지난 09:00 예약을 기록 - 원인은 단정하지 않고 (앞 실행·절전 등), 날짜와 함께",
      len(got) == 1 and got[0]["started_at"] == "2026-09-16T09:00:00" and "(앞 실행·절전 등)" in got[0]["reason"]
      and "09-16 09:30에 09-16 06:00 예약을 실행했습니다." in got[0]["reason"], got)
check("실행 자체는 예전대로 (DRY_RUN 기록)", d.LAUNCHED and d.LAUNCHED[-1] == "all:auto", d.LAUNCHED)

print("=== 6. 절전에서 깨우기·깨어 있기 (사용자 2026-10-21 - 절전과 꺼진 화면만) ===")
calls, logs = [], []
d.LOG = logs.append
pw = d.Power((lambda: "T", lambda h, ft: calls.append(("arm", h, ft)) or True, lambda h: calls.append(("cancel", h)),
              lambda v: calls.append(("state", v))))
sch = dict(st.read_settings()["schedule"], enabled=True, next_run_at="2026-09-21T06:00:00")     # 9-21 월요일
wake, awake = d.wake_plan(sch, dt.datetime(2026, 9, 21, 2, 0), False)
check("다음 실행 3분 전에 깨우고, 그 전에는 깨어 있지 않는다", wake == dt.datetime(2026, 9, 21, 5, 57) and not awake, (wake, awake))
pw.wake_at(wake)
pw.wake_at(wake)
arms = [c for c in calls if c[0] == "arm"]
check("타이머는 한 번만 맞춘다 (같은 시각이면 다시 안 부름) - 절대 시각 (1601년부터 100ns, UTC)",
      len(arms) == 1 and arms[0][2] == int((wake.timestamp() + 11644473600) * 10_000_000) and len(logs) == 1, (calls, logs))
wake, awake = d.wake_plan(sch, dt.datetime(2026, 9, 21, 5, 58), False)
pw.wake_at(wake)
pw.keep_awake(awake)
pw.keep_awake(awake)
check("3분 안이면 타이머는 끄고 잠들지 않게·화면 켬 (한 번만 부름)",
      wake is None and awake and ("cancel", "T") in calls and [c for c in calls if c[0] == "state"] == [("state", 0x80000003)], calls)
check("실행 중이면 깨어 있는다", d.wake_plan(sch, dt.datetime(2026, 9, 21, 6, 30), True)[1])
later = dict(sch, next_run_at="2026-09-22T06:00:00")
wake, awake = d.wake_plan(later, dt.datetime(2026, 9, 21, 7, 0), False)
pw.keep_awake(awake)
check("실행이 끝나고 다음 예약이 멀면 풀고(ES_CONTINUOUS 만) 다음 3분 전 타이머",
      not awake and wake == dt.datetime(2026, 9, 22, 5, 57) and calls[-1] == ("state", 0x80000000), (wake, awake, calls[-1:]))
check("반복 시간대가 열린 동안은 쉬는 시간에도 깨어 있는다", d.wake_plan(later, dt.datetime(2026, 9, 21, 13, 30), False)[1])
check("자동 실행을 껐으면 깨우지 않는다", d.wake_plan(dict(sch, enabled=False), dt.datetime(2026, 9, 21, 5, 58), False) == (None, False))
logs.clear()
pw2 = d.Power((lambda: "T", lambda h, ft: False, lambda h: None, lambda v: None))
pw2.wake_at(dt.datetime(2026, 9, 22, 5, 57))
pw2.wake_at(dt.datetime(2026, 9, 23, 5, 57))
check("깨우기 타이머를 못 쓰면(전원 설정) 한 번만 알리고, '맞췄습니다' 는 남기지 않는다",
      sum("깨우기 타이머 허용" in m for m in logs) == 1 and not any("맞췄습니다" in m for m in logs), logs)
d.LOG = print

print("=== 7. 자던 PC 가 쉬는 날에 깨어 밀린 평일 예약 ===")
before = len(rows("missed"))
set_next(dt.datetime(2026, 9, 23, 9, 0))               # 수 09:00 예약이 밀린 채
clock[0] = dt.datetime(2026, 9, 24, 8, 0)              # 추석(목)에 깨어남
sched.tick()
got = [r for r in rows("missed") if r["started_at"].startswith("2026-09-23")]
check("쉬는 날이라 늦게 돌리지 않고, 밀린 수 09:00·13:00~15:00 을 기록 - '쉬는 날이라'",
      len(rows("missed")) == before + 2 and [r["started_at"][11:16] for r in got] == ["09:00", "13:00"]
      and all("쉬는 날이라 늦게 실행하지 않았습니다" in r["reason"] for r in got) and d.LAUNCHED[-1] == "all:auto", (got, d.LAUNCHED[-1:]))

print("=== 8. 에이전트는 켠 채 자던 PC - 다음 실행이 반복 시간대였다 (깨우기가 안 먹음, 검토 10-22) ===")
before = len(rows("missed"))
set_next(dt.datetime(2026, 9, 28, 13, 0))              # 월 13:00~15:00 반복 시간대를 가리킨 채
clock[0] = dt.datetime(2026, 9, 29, 10, 0)             # 화 10:00 에 깨어남
sched.tick()
got = [r for r in rows("missed") if r["started_at"] >= "2026-09-28"]
check("밀린 월 13:00~15:00·화 06:00·09:00 을 기록 - '(절전 등)', 다음 예약은 화 13:00",
      [r["started_at"] for r in got] == ["2026-09-28T13:00:00", "2026-09-29T06:00:00", "2026-09-29T09:00:00"]
      and all("(절전 등)" in r["reason"] for r in got) and st.read_settings()["schedule"]["next_run_at"] == "2026-09-29T13:00:00",
      ([r["started_at"] for r in got], st.read_settings()["schedule"]["next_run_at"]))
before = len(rows("missed"))
clock[0] = dt.datetime(2026, 9, 29, 13, 0, 5)          # 평소: 반복 시간대가 막 열림
sched.tick()
check("평소 반복 시간대가 열릴 때는 기록하지 않는다 (열려 있는 시간대는 반복이 맡는다)", len(rows("missed")) == before, len(rows("missed")))

print("실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
