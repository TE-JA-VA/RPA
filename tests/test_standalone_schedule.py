# -*- coding: utf-8 -*-
"""옵저버 단독 - 예약 줄에 프리셋 (rpa_dashboard, 설계 2026-11-03). DRY_RUN + 격리 폴더, 실제로 띄우지 않는다.
    .venv\\Scripts\\python.exe tests\\test_standalone_schedule.py
"""
import io
import json
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
TMP = tempfile.mkdtemp(prefix="rpa_sa_sched_")
os.environ["RPA_STANDALONE"] = "1"
os.environ["RPA_STATUS_DIR"] = os.path.join(TMP, "status")
os.environ["RPA_PROGRAMDATA"] = os.path.join(TMP, "programdata")
os.environ["RPA_USER_CONFIG"] = os.path.join(TMP, "config", "RPA_UserConfig.json")
os.environ["RPA_DASHBOARD_DRY_RUN"] = "1"
os.environ["RPA_OBSERVER_LOCK"] = rf"Local\AFTER_MARKET_OBSERVER_SA_SCHED_TEST_{os.getpid()}"
os.makedirs(os.path.join(TMP, "config"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rpa_status as st  # noqa: E402
import rpa_dashboard as d  # noqa: E402

fails = []


def check(cond, what, detail=""):
    print(("PASS " if cond else "FAIL ") + what + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(what)


def raises(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
        return None
    except exc as e:
        return e


REC = {"version": 1, "start_url": "https://shop.example.com/login", "record_date": "2026-11-03",
       "steps": [{"kind": "goto", "page": 0, "url": "/login", "href": "https://shop.example.com/login", "gap": 0}]}
st.write_user_config({"LogIn": {"AdminCode": "", "ID": "", "PW": ""}, "Sites": {}})
st.write_presets([dict(st.blank_preset(1), name="가몰", code="011", record=REC), dict(st.blank_preset(2), name="나몰", code="012", record=REC),
                  dict(st.blank_preset(3), name="다몰", code="013", record=REC)])
st.save_preset_sites(st.read_presets(), {1: ("a", "pw"), 2: ("b", "pw"), 3: ("c", "pw")})
st.set_preset_switches({"1": True, "2": True, "3": True})
check([s["no"] for s in st.preset_summary() if s["on"]] == [1, 2, 3], "준비: 프리셋 1·2·3 켬")

print("\n=== 1. 줄 검사 ===")
slots = d.normalize_slots([{"at": "09:00", "presets": [3, 1, 3]}, {"at": "10:00"}])
check(slots == [{"at": "09:00", "presets": [1, 3]}, {"at": "10:00"}], "slot_presets_ok: 중복 없이 정렬, 없으면 모두", slots)
for bad in ([], [0], [41], ["1"], [True], "1", {}):
    check(isinstance(raises(ValueError, d.normalize_slots, [{"at": "09:00", "presets": bad}]), ValueError), f"slot_presets_ok: 거부 {bad!r}")
e = raises(ValueError, d.normalize_slots, [{"at": "09:00", "run": ["Prepare"]}])
check(str(e) == "옵저버 단독 버전에서는 모듈을 고를 수 없습니다.", "slot_run_rejected: run 은 거절", e)
e = raises(ValueError, d.normalize_slots, [{"at": "09:00", "inv_sites": True}])
check(str(e) == "옵저버 단독 버전에서는 모듈을 고를 수 없습니다.", "slot_run_rejected: inv_sites 도 거절", e)
slots = d.normalize_slots([{"at": "09:00", "until": "12:00", "rest_min": 5, "presets": [2]}])
check(slots == [{"at": "09:00", "until": "12:00", "rest_min": 5, "on_fail": "stop", "presets": [2]}], "repeat_without_run: 반복 줄은 run 없이 저장", slots)
check(d.apply_schedule({"enabled": True, "days": [0, 1, 2, 3, 4], "slots": [{"at": "09:00", "presets": [1, 3]}], "skip_holidays": True, "off_dates": []})
      and st.read_settings()["schedule"]["slots"] == [{"at": "09:00", "presets": [1, 3]}], "적용 → 저장", st.read_settings()["schedule"]["slots"])
check(d.slot_text({"at": "09:00", "presets": [1, 3]}) == "09:00 프리셋 1·3" and d.slot_text({"at": "09:00"}) == "09:00", "줄 글 '09:00 프리셋 1·3'",
      d.slot_text({"at": "09:00", "presets": [1, 3]}))

print("\n=== 2. 띄우기 ===")
check(isinstance(raises(ValueError, d.launch, "all", "manual"), ValueError) and isinstance(raises(ValueError, d.launch, "routine", "manual"), ValueError)
      and d.LAUNCHED == [], "launch: 단독은 prepare 만")
d.launch_slot({"at": "09:00", "presets": [1, 3]})
check(d.LAUNCHED == ["prepare:auto"] and d.LAUNCHED_ENV[-1] == {"RPA_RUN_PRESETS": "1,3", "RPA_RUN_TRIGGER": "auto"}, "launch_env: 고른 프리셋을 env 로",
      (d.LAUNCHED, d.LAUNCHED_ENV[-1:]))
d._active["until"] = 0; d._active["proc"] = None
d.launch_slot({"at": "10:00"})
check(d.LAUNCHED[-1] == "prepare:auto" and "RPA_RUN_PRESETS" not in d.LAUNCHED_ENV[-1], "launch_env: presets 없으면 env 에 그 키 없음", d.LAUNCHED_ENV[-1:])
d._active["until"] = 0; d._active["proc"] = None
st.set_preset_switches({"3": False})
check(d.slot_presets({"at": "09:00", "presets": [1, 3]}) == [1] and d.slot_presets({"at": "09:00"}) is None, "slot_presets: 꺼진 프리셋은 빠진다")
d.launch_slot({"at": "09:00", "presets": [1, 3]})
check(d.LAUNCHED_ENV[-1]["RPA_RUN_PRESETS"] == "1", "slot_presets_gone: 3 이 꺼지면 '1' (Review Focus 2)", d.LAUNCHED_ENV[-1:])
d._active["until"] = 0; d._active["proc"] = None
st.set_preset_switches({"1": False})
n = len(d.LAUNCHED)
e = raises(RuntimeError, d.launch_slot, {"at": "09:00", "presets": [1, 3]})
check(str(e) == "돌릴 프리셋이 없습니다. 예약 줄의 프리셋을 확인하여 주십시오." and len(d.LAUNCHED) == n, "slot_presets_gone: 모두 꺼지면 RuntimeError", e)

print("\n=== 3. 예약기 - 모두 꺼진 줄은 기록하고 다음 예약으로 ===")
import datetime as dt  # noqa: E402
now = dt.datetime.now().replace(second=0, microsecond=0)
at = (now + dt.timedelta(minutes=5)).strftime("%H:%M")
at = f"{at[:2]}:{int(at[3:]) // 5 * 5:02d}"
d.apply_schedule({"enabled": True, "days": list(range(7)), "slots": [{"at": at, "presets": [1, 3]}], "skip_holidays": False, "off_dates": []})
cfg = st.read_settings()
cfg["schedule"]["next_run_at"] = (now - dt.timedelta(minutes=1)).isoformat(timespec="seconds")
cfg["schedule"]["next_slot"] = at
st.write_settings(cfg)
sched = d.Scheduler()
sched.tick_safe()
sch = st.read_settings()["schedule"]
rows = st.read_history()
check(len(d.LAUNCHED) == n and sch["last_error"] == "돌릴 프리셋이 없습니다. 예약 줄의 프리셋을 확인하여 주십시오."
      and st.parse_iso(sch["next_run_at"]) > now, "예약기: 띄우지 않고 까닭을 남기고 다음 예약으로", (sch["last_error"], sch["next_run_at"]))
check(any("돌릴 프리셋이 없습니다" in (r.get("reason") or "") and r.get("program") == "prepare" for r in rows), "예약기: 실행 기록에 남는다",
      [r.get("reason") for r in rows])

print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
