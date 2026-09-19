"""대시보드 '실행 모듈' 설정 시험 - ERPIA_AI.txt 의 Routine 섹션 읽기/쓰기 헬퍼와 대시보드 API.

실제 바탕화면 파일은 건드리지 않는다. 임시 파일과 임시 상태 폴더로만 돈다.

    .venv\\Scripts\\python.exe tests\\test_dashboard_modules.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="rpa_dashmod_")
os.environ["RPA_STATUS_DIR"] = _tmp
os.environ["RPA_DASHBOARD_DRY_RUN"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import rpa_status as st  # noqa: E402
import perform_login as pl  # noqa: E402

fails = []
_no = [0]


def check(name, cond, detail=""):
    _no[0] += 1
    mark = "통과" if cond else "실패"
    print(f"  {_no[0]:2d}. [{mark}] {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(f"{_no[0]}. {name} {detail}")


def finish():
    print()
    print(f"실패: {'없음' if not fails else fails}")
    sys.exit(1 if fails else 0)


def write_file(name, obj, encoding="utf-8", pretty=True):
    path = os.path.join(_tmp, name)
    text = json.dumps(obj, ensure_ascii=False, indent=2 if pretty else None)
    with open(path, "w", encoding=encoding) as f:
        f.write(text)
    return path


PW = "비밀번호-절대-유출-금지"
BASE = [
    {"LogIn": [{"AdminCode": "erpiatest2"}, {"ID": "admin"}, {"PW": PW}]},
    {"Logistic": [{"cboBS_Auto_YN": "Y"}, {"Printer": "Microsoft Print to PDF"}, {"cboTag": "한진연동"}]},
]
KEYS = [k for k, _ in st.ROUTINE_CONFIG_MODULES]

# ---------------------------------------------------------------------------
print("=== 1. 모듈 목록은 루틴과 같아야 한다 ===")
import run_routine as rr  # noqa: E402
check("ROUTINE_CONFIG_MODULES == run_routine.ROUTINE_MODULES 의 (설정 키, 이름)",
      list(st.ROUTINE_CONFIG_MODULES) == [(m[1], m[2]) for m in rr.ROUTINE_MODULES],
      str(list(st.ROUTINE_CONFIG_MODULES)))
check("ROUTINE_SECTION 도 같다", st.ROUTINE_SECTION == pl.ROUTINE_SECTION)

# ---------------------------------------------------------------------------
print()
print("=== 2. read_routine_modules ===")
p = write_file("a.txt", BASE)
sel, prob = st.read_routine_modules(p)
check("섹션 없음 -> 전부 켬, 문제 없음", sel == {k: True for k in KEYS} and prob == [], str((sel, prob)))

p = write_file("b.txt", BASE + [{"Routine": [{"Login": "Y"}, {"Sales": "n"}, {"Hold": "x"}]}])
sel, prob = st.read_routine_modules(p)
check("Y/N 읽기 + 없는 키는 켬", sel["Login"] is True and sel["Sales"] is False and sel["Logistics"] is True)
check("잘못된 값은 None + 문제 한 줄", sel["Hold"] is None and len(prob) == 1 and "Hold" in prob[0], str(prob))

sel, prob = st.read_routine_modules(os.path.join(_tmp, "없는파일.txt"))
check("파일 없음 -> 전부 None + 문제", all(v is None for v in sel.values()) and prob, str(prob))

p = write_file("c.txt", {"LogIn": {"PW": PW}, "Routine": {"Output": "N"}})
sel, prob = st.read_routine_modules(p)
check("최상위가 dict 인 형식도 읽는다", sel["Output"] is False and sel["Login"] is True)

# ---------------------------------------------------------------------------
print()
print("=== 3. write_routine_modules ===")
p = write_file("d.txt", BASE)
out = st.write_routine_modules({"Sales": False, "Hold": True}, p)
check("돌려주는 값은 5개 전부 (빠진 키는 켬)", out == {"Login": True, "Sales": False, "Hold": True, "Logistics": True, "Output": True}, str(out))
data = json.loads(open(p, encoding="utf-8").read())
check("섹션이 없으면 끝에 붙는다 (순서 유지)", [list(x.keys())[0] for x in data] == ["LogIn", "Logistic", "Routine"], str([list(x.keys())[0] for x in data]))
check("Routine 은 단일 키 dict 목록 + Y/N", data[2]["Routine"] == [{"Login": "Y"}, {"Sales": "N"}, {"Hold": "Y"}, {"Logistics": "Y"}, {"Output": "Y"}], str(data[2]))
check("비밀번호 등 나머지는 그대로", data[0] == BASE[0] and data[1] == BASE[1])
check(".bak 에 쓰기 전 원본이 남는다", json.loads(open(p + ".bak", encoding="utf-8").read()) == BASE)
check("임시 파일이 남지 않는다", not [f for f in os.listdir(_tmp) if f.endswith(".tmp")])

out = st.write_routine_modules({k: False for k in KEYS}, p)
data = json.loads(open(p, encoding="utf-8").read())
check("있으면 제자리에서 바꾼다 (항목 수 그대로)", len(data) == 3 and data[2]["Routine"] == [{k: "N"} for k in KEYS], str(data[2]))

# 루틴 쪽 읽기 함수가 실제로 같은 결과로 읽는지 (perform_login.load_routine_modules)
pl.CRED_FILE = p
sel, unknown = pl.load_routine_modules(KEYS)
check("루틴의 load_routine_modules 가 쓴 그대로 읽는다", sel == {k: False for k in KEYS} and unknown == [], str(sel))

p = write_file("e.txt", BASE + [{"Routine": [{"Login": "Y"}, {"Extra": "Y"}]}, {"Etc": [{"x": 1}]}])
st.write_routine_modules({"Login": False}, p)
data = json.loads(open(p, encoding="utf-8").read())
check("Routine 뒤의 다른 섹션도 순서 그대로", [list(x.keys())[0] for x in data] == ["LogIn", "Logistic", "Routine", "Etc"])
check("아는 키는 제자리에서 바뀌고 모르는 키(Extra)는 보존된다 (루틴이 경고를 내 주도록)",
      data[2]["Routine"][:2] == [{"Login": "N"}, {"Extra": "Y"}] and [list(x.keys())[0] for x in data[2]["Routine"]] == ["Login", "Extra", "Sales", "Hold", "Logistics", "Output"], str(data[2]["Routine"]))

p = write_file("e2.txt", BASE + [{"Routine": [{"Login": "N"}]}, {"Routine": [{"Login": "Y"}, {"Hold": "N"}]}])
sel, _ = st.read_routine_modules(p)
check("Routine 항목이 둘이면 마지막 것 (루틴과 같음)", sel["Login"] is True and sel["Hold"] is False, str(sel))

p = write_file("e3.txt", BASE + [{"Routine": "Y"}])
sel, prob = st.read_routine_modules(p)
check("Routine 이 섹션이 아니라 값이면 전부 None + 문제 (루틴은 이 파일로 안 돈다)", all(v is None for v in sel.values()) and prob and "섹션" in prob[0], str(prob))

p = write_file("f.txt", BASE, encoding="cp949")
st.write_routine_modules({"Output": False}, p)
raw = open(p, "rb").read()
check("cp949 파일도 읽어서 UTF-8(BOM 없음)로 쓴다", not raw.startswith(b"\xef\xbb\xbf") and raw.decode("utf-8") and "한진연동" in raw.decode("utf-8"))
pl.CRED_FILE = p
sel, _ = pl.load_routine_modules(KEYS)
check("다시 쓴 파일을 루틴이 읽는다 (Output 끔)", sel["Output"] is False and sel["Login"] is True)

p = write_file("g.txt", {"LogIn": {"PW": PW}})
st.write_routine_modules({"Hold": False}, p)
data = json.loads(open(p, encoding="utf-8").read())
check("최상위 dict 형식은 키로 넣는다", data["Routine"] == [{"Login": "Y"}, {"Sales": "Y"}, {"Hold": "N"}, {"Logistics": "Y"}, {"Output": "Y"}] and data["LogIn"]["PW"] == PW)

try:
    st.write_routine_modules({"Bogus": True}, p)
    check("모르는 키면 ValueError", False, "예외 없음")
except ValueError as e:
    check("모르는 키면 ValueError", "Bogus" in str(e))

try:
    st.write_routine_modules({"Login": True}, os.path.join(_tmp, "없는파일.txt"))
    check("파일이 없으면 예외 (새로 만들지 않는다)", False, "예외 없음")
except FileNotFoundError:
    check("파일이 없으면 예외 (새로 만들지 않는다)", True)

p = write_file("h.txt", BASE)
open(p, "w", encoding="utf-8").write("이건 JSON 이 아니다")
try:
    st.write_routine_modules({"Login": True}, p)
    check("깨진 JSON 이면 예외 + 원본 보존", False, "예외 없음")
except Exception:
    check("깨진 JSON 이면 예외 + 원본 보존", open(p, encoding="utf-8").read() == "이건 JSON 이 아니다" and not os.path.exists(p + ".bak"))

# ---------------------------------------------------------------------------
print()
print("=== 4. 대시보드 서버 함수 (rpa_dashboard) ===")
import rpa_dashboard as d  # noqa: E402

p = write_file("srv.txt", BASE)
os.environ["RPA_CRED_FILE"] = p
check("cred_file_path 는 RPA_CRED_FILE 을 따른다", st.cred_file_path() == p)
check("read_account 도 같은 파일을 본다 (비밀번호는 안 나옴)", st.read_account() == {"admin_code": "erpiatest2", "user_id": "admin"})
sess = {"user_id": "admin", "role": "admin", "admin_code": "e"}
v = d.settings_view(sess)
rm = v["routine_modules"]
check("settings_view 에 routine_modules 5개, 전부 켬", [it["key"] for it in rm["items"]] == KEYS and all(it["enabled"] is True for it in rm["items"]), str(rm))
check("응답 어디에도 비밀번호가 없다", PW not in json.dumps(v, ensure_ascii=False))

changed = d.apply_routine_modules({"Login": True, "Sales": False, "Hold": True, "Logistics": True, "Output": True})
check("apply: 바뀐 것이 있으면 True", changed is True)
sel, _ = st.read_routine_modules(p)
check("apply 가 파일에 썼다 (Sales 끔)", sel["Sales"] is False and sel["Login"] is True)
check("같은 값을 다시 적용하면 False", d.apply_routine_modules({"Sales": False}) is False)
check("빠진 키는 지금 값 유지", d.apply_routine_modules({"Output": False}) is True and st.read_routine_modules(p)[0]["Sales"] is False)
for bad, what in (("x", "dict 아님"), ({"Bogus": True}, "모르는 키"), ({"Login": "Y"}, "bool 아님")):
    try:
        d.apply_routine_modules(bad)
        check(f"apply 검증: {what} -> ValueError", False, "예외 없음")
    except ValueError:
        check(f"apply 검증: {what} -> ValueError", True)

try:
    d.apply_routine_modules({k: False for k in KEYS})
    check("전부 끄는 요청은 ValueError (최소 한 모듈)", False, "예외 없음")
except ValueError as e:
    check("전부 끄는 요청은 ValueError (최소 한 모듈)", "최소" in str(e), str(e))
sel, _ = st.read_routine_modules(p)
check("거절된 요청은 파일을 안 건드린다", sel["Sales"] is False and sel["Output"] is False and sel["Login"] is True, str(sel))
try:
    d.validate_routine_modules({"Bogus": True})
    check("validate 는 파일 없이 검증만 (모르는 키 -> ValueError)", False, "예외 없음")
except ValueError:
    check("validate 는 파일 없이 검증만 (모르는 키 -> ValueError)", True)

open(p, "w", encoding="utf-8").write("깨진 json " + PW)
try:
    d.apply_routine_modules({"Login": False})
    check("파일이 깨졌으면 RuntimeError (내용 노출 없음)", False, "예외 없음")
except RuntimeError as e:
    check("파일이 깨졌으면 RuntimeError (내용 노출 없음)", "깨진" not in str(e) and PW not in str(e), str(e))
v = d.settings_view(sess)
check("깨진 파일이면 problems 한 줄 + enabled 전부 None", v["routine_modules"]["problems"] and all(it["enabled"] is None for it in v["routine_modules"]["items"]), str(v["routine_modules"]))
check("깨진 파일의 problems 에도 비밀번호가 없다", PW not in json.dumps(v["routine_modules"], ensure_ascii=False))

# 링 분모: '설정에서 끔' 단계 제외 (현황 decorate 와 이력 run_summary 가 같은 계산)
st.start("routine", [("login", "로그인"), ("order_screen", "화면"), ("sales", "매출"), ("hold_screen", "이동")])
st.set_modules([("login", "로그인", ("login",), 1), ("sales", "매출", ("order_screen", "sales"), 2), ("hold", "물류대기", ("hold_screen",), 4)])
st.module_start("login")
st.step("login")
st.module_done("login", "done")
st.module_off("sales", st.OFF_NOTE)
st.skip("order_screen", st.OFF_NOTE)
st.skip("sales", st.OFF_NOTE)
st.module_start("hold")
st.step("hold_screen")
view = st.decorate(st._state)
check("decorate: 끈 단계는 분모/분자에서 빠진다 (2단계 중 1 완료)", view["steps_total"] == 2 and view["steps_done"] == 1, str((view["steps_total"], view["steps_done"])))
check("decorate: current_index 도 끈 단계를 뺀 순번", view["current_index"] == 2, str(view["current_index"]))
rec = st.history_record(st._state)
summ = d.run_summary(rec)
check("run_summary 도 같은 계산 + module_flags/modules", summ["steps_total"] == 2 and summ["steps_done"] == 1 and summ["module_flags"] == 1 and [m["state"] for m in summ["modules"]] == ["done", "off", "running"], str(summ))
st.finish("stopped", "시험 끝")

# 전부 끔 / 로그인만 / 옛 형식 레코드가 계산에서 예외 없이 처리되는지 + 평균은 전체 실행만
st.start("routine", [("login", "로그인"), ("sales", "매출")])
st.set_modules([("login", "로그인", ("login",), 1), ("sales", "매출", ("sales",), 2)])
for k, s in (("login", ("login",)), ("sales", ("sales",))):
    st.module_off(k, st.OFF_NOTE)
    for x in s:
        st.skip(x, st.OFF_NOTE)
view = st.decorate(st._state)
check("전부 끔: steps_total 0, current_index None (0 나누기 없음)", view["steps_total"] == 0 and view["steps_done"] == 0 and view["current_index"] is None, str((view["steps_total"], view["current_index"])))
st.finish("stopped", "켜진 모듈이 없습니다")
rec_alloff = st.history_record(st._state)

st.start("routine", [("login", "로그인"), ("sales", "매출")])
st.set_modules([("login", "로그인", ("login",), 1), ("sales", "매출", ("sales",), 2)])
st.module_start("login")
st.step("login")
st.module_done("login", "done")
st.module_off("sales", st.OFF_NOTE)
st.skip("sales", st.OFF_NOTE)
st.finish("success")
rec_partial = dict(st.history_record(st._state), duration_sec=30)
rec_full = {"program": "routine", "state": "success", "duration_sec": 600, "modules": [{"key": "login", "state": "done"}]}
rec_old = {"program": "routine", "state": "success", "duration_sec": 500}   # schema 1 (modules 없음) = 전체 실행
stats = d.history_stats([rec_alloff, rec_partial, rec_full, rec_old])
check("평균 소요는 모듈을 끈 실행을 뺀다 (600, 500 -> 550)", stats["avg_success_sec"].get("routine") == 550, str(stats))
check("run_summary: 로그인만 켠 실행은 1/1", d.run_summary(rec_partial)["steps_total"] == 1 and d.run_summary(rec_partial)["steps_done"] == 1)
check("run_summary: 전부 끔은 0/0", d.run_summary(rec_alloff)["steps_total"] == 0)
del os.environ["RPA_CRED_FILE"]

finish()
