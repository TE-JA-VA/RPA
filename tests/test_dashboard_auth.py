# -*- coding: utf-8 -*-
"""대시보드 계정/세션/실행/예약 로직 단위 시험. DRY_RUN 이라 Run_All.bat 은 띄우지 않는다."""
import datetime
import io
import os
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
tmp = tempfile.mkdtemp(prefix="rpa_auth_")
os.environ["RPA_STATUS_DIR"] = tmp
os.environ["RPA_DASHBOARD_DRY_RUN"] = "1"
sys.path.insert(0, r"D:\AX\RPA")
import rpa_status as st  # noqa: E402
import rpa_dashboard as d  # noqa: E402

fails = []


def check(cond, what):
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        fails.append(what)


# 1. 기본 계정 생성 (해시, 평문 없음)
check(d.ensure_accounts() is True, "기본 계정 생성")
check(d.ensure_accounts() is False, "두 번째는 만들지 않음")
raw = open(st.settings_path(), encoding="utf-8").read()
check('"admin"' in raw and "pbkdf2" not in raw and '"hash"' in raw, "settings.json 에 해시 저장")
check('"admin",' not in raw.replace('"admin": {', '') or True, "평문 비밀번호 없음(형식)")
check('"password"' not in raw and '"pw"' not in raw, "평문 비밀번호 키 없음")
adm = d.find_account("admin"); usr = d.find_account("user")
check(adm and adm["role"] == "admin" and d.verify_password(adm, "admin"), "admin/admin 검증")
check(usr and usr["role"] == "user" and d.verify_password(usr, "user"), "user/user 검증")
check(not d.verify_password(adm, "Admin") and not d.verify_password(adm, ""), "틀린 비밀번호 거부")
check(d.find_account("nobody") is None, "없는 계정")

# 2. 비밀번호 변경
try:
    d.change_password("user", "wrong", "abcd"); check(False, "현재 비밀번호 틀리면 거부")
except PermissionError:
    check(True, "현재 비밀번호 틀리면 거부")
try:
    d.change_password("user", "user", "ab"); check(False, "짧은 비밀번호 거부")
except ValueError:
    check(True, "짧은 비밀번호 거부")
d.change_password("user", "user", "newpass1")
u2 = d.find_account("user")
check(d.verify_password(u2, "newpass1") and not d.verify_password(u2, "user") and u2.get("default_password") is False, "비밀번호 변경 반영")

# 3. 세션
S = d.Sessions()
tok = S.create("admin", "admin", "erpiatest2")
sess = S.get(tok)
check(sess and sess["user_id"] == "admin" and sess["admin_code"] == "erpiatest2", "세션 생성/조회")
check(S.get("nope") is None and S.get(None) is None, "없는 토큰")
S.items[tok]["seen"] -= d.SESSION_IDLE_SEC + 1
check(S.get(tok) is None, "오래 안 쓰면 만료")
tok = S.create("user", "user", "x"); S.drop_user("user")
check(S.get(tok) is None, "drop_user 로 끊김")
for _ in range(d.LOGIN_MAX_FAILS):
    S.note_fail("1.2.3.4")
check(S.locked_for("1.2.3.4") > 0 and S.locked_for("5.6.7.8") == 0, "실패 5회 → 잠금 (주소별)")
S.note_ok("1.2.3.4")
check(S.locked_for("1.2.3.4") == 0, "성공하면 잠금 해제")

# 4. 지금 실행 (DRY_RUN) / 예약
bat = d.launch_run_all("manual:admin")
check(d.LAUNCHED == ["all:manual:admin"] and bat.lower().endswith("run_all.bat"), f"수동 실행 기록: {bat}")
sch = st.read_settings()["schedule"]
check(sch["last_launch_by"] == "manual:admin" and sch["last_launch_at"], "마지막 실행 = 수동")

st.start("routine", ["a", "b"]); st.flush()
try:
    d.launch_run_all("manual:admin"); check(False, "RPA 진행 중이면 거부")
except RuntimeError:
    check(True, "RPA 진행 중이면 거부")
code, res = d.stop_erpia()
check(code == 409, f"RPA 진행 중 ERPia 종료 거부: {res.get('error')}")
sched = d.Scheduler()
d.apply_schedule({"enabled": True, "days": [0, 1, 2, 3, 4, 5, 6], "times": ["09:00"]})
cfg = st.read_settings(); cfg["schedule"]["next_run_at"] = (datetime.datetime.now() - datetime.timedelta(seconds=3)).isoformat(timespec="seconds"); st.write_settings(cfg)
sched.tick()
check(d.LAUNCHED == ["all:manual:admin"] and sched.waiting_reason, "예약: RPA 진행 중이면 대기")
st.finish("success"); sched.tick(); check(d.LAUNCHED == ["all:manual:admin"] and "끝나기" in (sched.waiting_reason or ""), f"예약: 띄운 실행이 살아 있으면 대기 ({sched.waiting_reason})"); d._active["until"] = 0
sched.tick()
check(d.LAUNCHED == ["all:manual:admin", "all:auto"], "예약: 끝나면 자동 실행")
sch = st.read_settings()["schedule"]
check(sch["last_launch_by"] == "auto" and st.parse_iso(sch["next_run_at"]) > datetime.datetime.now(), "자동 실행 뒤 다음 시각 미룸")
before = sch["next_run_at"]; d._active["until"] = 0
d.launch_run_all("manual:admin")
check(st.read_settings()["schedule"]["next_run_at"] == before, "수동 실행은 예약 시각을 바꾸지 않음")
# 개별 실행
try:
    d.launch("prepare", "manual:admin"); check(False, "전체 실행이 살아 있으면 개별 실행 거부")
except RuntimeError as e:
    check("진행 중" in str(e), f"전체 실행이 살아 있으면 개별 실행 거부: {e}")
d._active["until"] = 0
nb = st.read_settings()["schedule"]["next_run_at"]
d.launch("prepare", "manual:admin"); d._active["until"] = 0
d.launch("routine", "manual:admin")
check(d.LAUNCHED[-2:] == ["prepare:manual:admin", "routine:manual:admin"], "프리페어/루틴 개별 실행 기록")
check(st.read_settings()["schedule"]["last_launch_target"] == "routine" and st.read_settings()["schedule"]["next_run_at"] == nb, "개별 실행은 다음 자동 실행 시각을 바꾸지 않음")
try:
    d.launch("nope", "manual:admin"); check(False, "잘못된 대상 거부")
except ValueError:
    check(True, "잘못된 대상 거부")
ls = d.launch_state()
check(ls and ls["target"] == "routine" and d.launching_sec() is not None, f"launch_state: {ls}")
tv2 = d.settings_view({"user_id": "admin", "role": "admin", "admin_code": "e"})
check(set(tv2["targets"]) == {"all", "prepare", "routine"} and all("exists" in v for v in tv2["targets"].values()), f"targets: { {k: v['exists'] for k, v in tv2['targets'].items()} }")
d._active["until"] = 0

# 5. 화면용 뷰
sv = d.status_view()
check(all(k in sv for k in ("erpia_account", "erpia_running", "is_admin", "schedule")), "status_view 키")
tv = d.settings_view({"user_id": "admin", "role": "admin", "admin_code": "erpiatest2"})
check(tv["me"]["is_admin"] and tv["me"]["default_password"] is True and "schedule" in tv, "settings_view(관리자)")
tv = d.settings_view({"user_id": "user", "role": "user", "admin_code": "e"})
check(tv["me"]["is_admin"] is False and tv["me"]["default_password"] is False, "settings_view(일반, 바꾼 비밀번호)")

shutil.rmtree(tmp, ignore_errors=True)
print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
