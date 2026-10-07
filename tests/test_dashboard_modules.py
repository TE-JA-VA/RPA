"""대시보드 '실행 모듈' 설정 시험 - 사용자 설정(RPA_UserConfig.json)의 Routine 섹션 읽기/쓰기 헬퍼와 대시보드 API,
그리고 옛 두 파일(ERPIA_AI.txt, WebManageConfig.json)에서 한 파일로 옮기기·비밀번호 잠금.

실제 설정 파일은 건드리지 않는다. 임시 파일과 임시 상태 폴더로만 돈다 (RPA_USER_CONFIG 를 임시 폴더로).

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
os.environ["RPA_USER_CONFIG"] = os.path.join(_tmp, "RPA_UserConfig.json")   # 기본 자리를 부르는 시험이 실제 파일을 못 건드리게
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
text = open(p, encoding="utf-8").read()
data = json.loads(text)
check("옛 형식은 섹션 dict 로 풀려 쓰이고, 없던 Routine 은 끝에 붙는다", list(data) == ["LogIn", "Logistic", "Routine"], str(list(data)))
check("Routine 은 {키: Y/N}", data["Routine"] == {"Login": "Y", "Sales": "N", "Hold": "Y", "Logistics": "Y", "Output": "Y"}, str(data["Routine"]))
check("비밀번호는 잠겨서 들어간다 (파일에 평문이 없다)", PW not in text and data["LogIn"]["PW"].startswith(st.SEALED_PREFIX))
check("잠긴 비밀번호를 풀면 원래 값", st.unseal(data["LogIn"]["PW"]) == PW)
check("나머지는 그대로", data["LogIn"]["AdminCode"] == "erpiatest2" and data["LogIn"]["ID"] == "admin"
      and data["Logistic"] == {"cboBS_Auto_YN": "Y", "Printer": "Microsoft Print to PDF", "cboTag": "한진연동"})
check("평문이 남는 사본(.bak)은 만들지 않는다", not os.path.exists(p + ".bak"))
check("임시 파일이 남지 않는다", not [f for f in os.listdir(_tmp) if f.endswith(".tmp")])

out = st.write_routine_modules({k: False for k in KEYS}, p)
data = json.loads(open(p, encoding="utf-8").read())
check("있으면 제자리에서 바꾼다 (섹션 수 그대로)", len(data) == 3 and data["Routine"] == {k: "N" for k in KEYS}, str(data["Routine"]))
check("이미 잠긴 비밀번호는 다시 잠그지 않는다 (풀면 그대로)", st.unseal(data["LogIn"]["PW"]) == PW)

# 루틴 쪽 읽기 함수가 실제로 같은 결과로 읽는지 (perform_login.load_routine_modules)
pl.CONFIG_FILE = p
sel, unknown = pl.load_routine_modules(KEYS)
check("루틴의 load_routine_modules 가 쓴 그대로 읽는다", sel == {k: False for k in KEYS} and unknown == [], str(sel))
check("루틴의 load_credentials 는 잠긴 비밀번호를 풀어 준다", pl.load_credentials() == ("erpiatest2", "admin", PW))

p = write_file("e.txt", BASE + [{"Routine": [{"Login": "Y"}, {"Extra": "Y"}]}, {"Etc": [{"x": 1}]}])
st.write_routine_modules({"Login": False}, p)
data = json.loads(open(p, encoding="utf-8").read())
check("Routine 뒤의 다른 섹션도 순서 그대로", list(data) == ["LogIn", "Logistic", "Routine", "Etc"], str(list(data)))
check("아는 키는 제자리에서 바뀌고 모르는 키(Extra)는 보존된다 (루틴이 경고를 내 주도록)",
      list(data["Routine"].items())[:2] == [("Login", "N"), ("Extra", "Y")] and list(data["Routine"]) == ["Login", "Extra", "Sales", "Hold", "Logistics", "Output"], str(data["Routine"]))

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
pl.CONFIG_FILE = p
sel, _ = pl.load_routine_modules(KEYS)
check("다시 쓴 파일을 루틴이 읽는다 (Output 끔)", sel["Output"] is False and sel["Login"] is True)
pl.CONFIG_FILE = None

p = write_file("g.txt", {"LogIn": {"PW": PW}})
st.write_routine_modules({"Hold": False}, p)
data = json.loads(open(p, encoding="utf-8").read())
check("최상위 dict 형식은 키로 넣는다", data["Routine"] == {"Login": "Y", "Sales": "Y", "Hold": "N", "Logistics": "Y", "Output": "Y"}
      and st.unseal(data["LogIn"]["PW"]) == PW)

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
new = st.user_config_path()
check("처음 쓸 때 옛 파일을 합쳐 RPA_UserConfig.json 을 만들고 옛 파일은 .old 로",
      os.path.isfile(new) and not os.path.exists(p) and os.path.isfile(p + ".old"))
check("새 파일에도 평문 비밀번호가 없다", PW not in open(new, encoding="utf-8").read())
sel, _ = st.read_routine_modules()
check("apply 가 파일에 썼다 (Sales 끔)", sel["Sales"] is False and sel["Login"] is True)
check("계정은 새 파일에서 읽는다", st.read_account() == {"admin_code": "erpiatest2", "user_id": "admin"})
check("같은 값을 다시 적용하면 False", d.apply_routine_modules({"Sales": False}) is False)
check("빠진 키는 지금 값 유지", d.apply_routine_modules({"Output": False}) is True and st.read_routine_modules()[0]["Sales"] is False)
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
sel, _ = st.read_routine_modules()
check("거절된 요청은 파일을 안 건드린다", sel["Sales"] is False and sel["Output"] is False and sel["Login"] is True, str(sel))
try:
    d.validate_routine_modules({"Bogus": True})
    check("validate 는 파일 없이 검증만 (모르는 키 -> ValueError)", False, "예외 없음")
except ValueError:
    check("validate 는 파일 없이 검증만 (모르는 키 -> ValueError)", True)

open(new, "w", encoding="utf-8").write("깨진 json " + PW)
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

# ---------------------------------------------------------------------------
print()
print("=== 5. 옛 파일들 -> RPA_UserConfig.json (에이전트가 켤 때) ===")
mig = tempfile.mkdtemp(prefix="rpa_usercfg_")
os.environ["RPA_USER_CONFIG"] = os.path.join(mig, "RPA_UserConfig.json")
check("시험용 RPA_USER_CONFIG 면 옛 파일도 그 폴더만 본다 (실제 바탕화면·exe 옆은 안 본다)",
      all(os.path.dirname(x) == mig for x in st._old_config_paths()), str(st._old_config_paths()))
if os.path.isfile(r"D:\AX\RPA\dist\Run_All.bat"):
    check("개발 PC 에서 소스로 돌면 exe 가 있는 dist 를 본다 (대시보드가 띄우는 exe 와 같은 파일)",
          st.program_dir().lower().endswith("\\dist"), st.program_dir())
SITE_PW = "사이트-비번-유출-금지"
cred_old = os.path.join(mig, "ERPIA_AI.txt")
web_old = os.path.join(mig, "WebManageConfig.json")
json.dump(BASE + [{"Routine": [{"Login": "Y"}, {"Hold": "N"}]}], open(cred_old, "w", encoding="utf-8"), ensure_ascii=False)
json.dump({"_주석": ["Stts 0 실행, 9 보관"],
           "SITE1": {"URL": "https://a.example.com", "ID": "u1", "PW": SITE_PW, "Action": ["login"], "Stts": 0},
           "SITE2": {"URL": "https://b.example.com", "ID": "u2", "PW": "둘째-비번", "Action": "login", "Stts": 9}},
          open(web_old, "w", encoding="utf-8"), ensure_ascii=False)
fake_exe = os.path.join(mig, "OneZeroSoft", "ERPiaNet", "ERPiaMain.exe")      # 가짜 ERPia (빈 파일)
os.makedirs(os.path.dirname(fake_exe))
open(fake_exe, "wb").close()
lm_old = os.path.join(mig, "login_manager_config.json")
json.dump({"admin_code": "erpiatest2", "id": "admin", "exe_path": fake_exe.replace("\\", "/")}, open(lm_old, "w", encoding="utf-8"))

cfg = st.read_user_config()
check("새 파일이 없으면 옛 파일들을 합쳐 읽는다", cfg["LogIn"]["AdminCode"] == "erpiatest2" and cfg["Sites"]["SITE1"]["URL"] == "https://a.example.com"
      and cfg["Routine"] == {"Login": "Y", "Hold": "N"} and cfg["ERPia"] == {"ExePath": fake_exe.replace("\\", "/")})
check("옮기기 전에도 ERPia 위치를 읽는다 (옛 login_manager_config.json)", st.find_erpia_exe()[0] == os.path.normpath(fake_exe))
pl.CONFIG_FILE = None
check("옮기기 전에도 루틴은 옛 파일로 로그인 정보를 읽는다", pl.load_credentials() == ("erpiatest2", "admin", PW))
import web_runner as wr  # noqa: E402
sites = wr.load_config()
check("옮기기 전에도 프리페어는 옛 파일로 사이트를 읽는다 (주석 키는 빠진다)", list(sites) == ["SITE1", "SITE2"] and sites["SITE1"]["PW"] == SITE_PW)

msg = st.migrate_user_config()
check("옮기면 한 문장으로 알린다 (비밀번호 3개 잠금, 옛 파일 .old)", msg and "만들었습니다" in msg and "3개" in msg and ".old" in msg, str(msg))
new = st.user_config_path()
text = open(new, encoding="utf-8").read()
data = json.loads(text)
check("새 파일 한 개에 로그인·물류·모듈·사이트·ERPia 위치가 다 들어 있다", list(data) == ["LogIn", "Logistic", "Routine", "Sites", "ERPia"], str(list(data)))
check("ERPia 위치는 옛 exe_path 그대로 (업체코드·아이디는 LogIn 에 이미 있어 안 가져온다)", data["ERPia"] == {"ExePath": fake_exe.replace("\\", "/")})
check("평문 비밀번호가 하나도 없다", PW not in text and SITE_PW not in text and "둘째-비번" not in text)
check("비밀번호 자리는 모두 dpapi:", all(v.startswith(st.SEALED_PREFIX) for v in
                                      (data["LogIn"]["PW"], data["Sites"]["SITE1"]["PW"], data["Sites"]["SITE2"]["PW"])))
check("사이트 주석은 그대로 남는다", data["Sites"]["_주석"] == ["Stts 0 실행, 9 보관"])
check("옛 세 파일은 .old 로 바뀌었다", not any(os.path.exists(x) for x in (cred_old, web_old, lm_old))
      and all(os.path.isfile(x + ".old") for x in (cred_old, web_old, lm_old)))
check("옮긴 뒤 루틴은 잠긴 비밀번호를 풀어 로그인한다", pl.load_credentials() == ("erpiatest2", "admin", PW))
sites = wr.load_config()
check("옮긴 뒤 프리페어도 사이트 비밀번호를 풀어 쓴다", sites["SITE1"]["PW"] == SITE_PW and sites["SITE2"]["PW"] == "둘째-비번")
check("검사(validate_site)도 예전처럼 통과", wr.validate_site("SITE1", sites["SITE1"]) == [], str(wr.validate_site("SITE1", sites["SITE1"])))
check("다시 켜면 할 일이 없다", st.migrate_user_config() is None)

data["LogIn"]["PW"] = "새로-적은-평문"
json.dump(data, open(new, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
check("사람이 평문으로 고쳐 적어도 루틴은 그대로 읽는다", pl.load_credentials()[2] == "새로-적은-평문")
msg = st.migrate_user_config()
check("에이전트가 켤 때 평문을 잠근다", msg and "1개를 잠갔습니다" in msg and "새로-적은-평문" not in open(new, encoding="utf-8").read(), str(msg))
check("잠근 뒤에도 같은 값", pl.load_credentials()[2] == "새로-적은-평문")

st.write_routine_modules({"Hold": True})
check("모듈을 바꿔 써도 사이트·비밀번호는 그대로", wr.load_config()["SITE1"]["PW"] == SITE_PW and pl.load_credentials()[2] == "새로-적은-평문")
check("옛 .old 파일은 다시 건드리지 않는다", os.path.isfile(cred_old + ".old") and not os.path.exists(cred_old + ".old.old"))
check(".bak 도 임시 파일도 남지 않는다", not [f for f in os.listdir(mig) if f.endswith((".bak", ".tmp"))], str(os.listdir(mig)))

data = json.loads(open(new, encoding="utf-8").read())
data["LogIn"]["PW"] = st.SEALED_PREFIX + "AAAAAAAA"   # 다른 PC 에서 잠근 값을 흉내
json.dump(data, open(new, "w", encoding="utf-8"), ensure_ascii=False)
try:
    pl.load_credentials()
    check("못 푸는 비밀번호면 RuntimeError + 다시 넣으라는 안내", False, "예외 없음")
except RuntimeError as e:
    check("못 푸는 비밀번호면 RuntimeError + 다시 넣으라는 안내", "풀지 못했습니다" in str(e) and "다시 넣으세요" in str(e), str(e))

data["Routine"] = "Y"
json.dump(data, open(new, "w", encoding="utf-8"), ensure_ascii=False)
check("새 파일에서도 Routine 을 값으로 잘못 쓰면 '잘못됨' (전부 켬으로 읽지 않는다)",
      all(v is None for v in st.read_routine_modules()[0].values()) and "섹션" in st.read_routine_modules()[1][0])
try:
    pl.load_routine_modules(KEYS)
    check("루틴도 그 파일로는 돌지 않는다", False, "예외 없음")
except RuntimeError as e:
    check("루틴도 그 파일로는 돌지 않는다", "섹션" in str(e), str(e))

os.remove(new)
for x in (cred_old, web_old, lm_old):
    os.remove(x + ".old")
try:
    pl.load_routine_modules(KEYS)
    check("설정이 아무것도 없으면 루틴은 '설정 파일이 없습니다' 로 멈춘다 (전부 켬으로 돌지 않는다)", False, "예외 없음")
except RuntimeError as e:
    check("설정이 아무것도 없으면 루틴은 '설정 파일이 없습니다' 로 멈춘다 (전부 켬으로 돌지 않는다)", "없습니다" in str(e), str(e))
check("아무것도 없으면 옮길 것도 없다", st.migrate_user_config() is None and not os.path.exists(new))
try:
    st.write_routine_modules({"Hold": False})
    check("아무것도 없으면 모듈만 든 파일을 새로 만들지 않는다", False, "예외 없음")
except FileNotFoundError:
    check("아무것도 없으면 모듈만 든 파일을 새로 만들지 않는다", not os.path.exists(new))

# ---------------------------------------------------------------------------
print()
print("=== 6. ERPia 위치 (적힌 값 -> 설치 기록 -> 고르는 창) ===")
real_dirs, real_pick = st._erpia_install_dirs, st.pick_erpia_exe
picked = []
st.pick_erpia_exe = lambda: picked.append(1) or None          # 창은 띄우지 않고 불렸는지만 센다
other = os.path.join(mig, "D드라이브", "ERPiaNet")
os.makedirs(other)
other_exe = os.path.join(other, "ERPiaMain.exe")
open(other_exe, "wb").close()
login_exe = os.path.join(mig, "ERPia_Login.exe")               # 같은 회사의 다른 프로그램
open(login_exe, "wb").close()


def write_cfg(exe):
    st.write_user_config({"LogIn": {"AdminCode": "x", "ID": "a", "PW": PW}, "ERPia": {"ExePath": exe}} if exe is not None
                         else {"LogIn": {"AdminCode": "x", "ID": "a", "PW": PW}})


try:
    write_cfg(fake_exe.replace("\\", "/"))
    st._erpia_install_dirs = lambda: [other]
    check("적힌 값이 맞으면 그대로 (설치 기록은 안 본다)", st.erpia_exe() == os.path.normpath(fake_exe) and not picked)

    write_cfg(os.path.join(mig, "없는폴더", "ERPiaMain.exe"))
    got = st.erpia_exe()
    saved = json.load(open(new, encoding="utf-8"))["ERPia"]["ExePath"]
    check("적힌 값이 틀리면 설치 기록에서 찾아 고쳐 적는다 (/ 로)", got == os.path.normpath(other_exe) and saved == other_exe.replace("\\", "/") and not picked,
          str((got, saved)))
    check("고쳐 적어도 비밀번호는 그대로", st.unseal(json.load(open(new, encoding="utf-8"))["LogIn"]["PW"]) == PW)

    write_cfg(login_exe)
    st._erpia_install_dirs = lambda: []
    check("이름이 ERPiaMain.exe 가 아니면 받지 않는다", st.find_erpia_exe()[0] is None)
    check("폴더만 적어도 그 안의 ERPiaMain.exe 를 찾는다", st._erpia_file(other) == os.path.normpath(other_exe))

    write_cfg(None)
    check("못 찾으면 ask 없이는 창을 안 띄우고 None", st.erpia_exe() is None and not picked)
    st.pick_erpia_exe = lambda: picked.append(1) or os.path.normpath(other_exe)
    got = st.erpia_exe(ask=True)
    check("ask 면 고르는 창을 띄우고, 고른 곳을 적어 둔다", got == os.path.normpath(other_exe) and picked == [1]
          and json.load(open(new, encoding="utf-8"))["ERPia"]["ExePath"] == other_exe.replace("\\", "/"))
    check("다음부터는 적힌 값으로 (창을 다시 안 띄운다)", st.erpia_exe(ask=True) == os.path.normpath(other_exe) and picked == [1])

    open(new, "w", encoding="utf-8").write("깨진 json")
    st._erpia_install_dirs = lambda: [other]
    check("설정이 깨졌어도 ERPia 는 찾는다 (쓰기만 못 한다)", st.erpia_exe() == os.path.normpath(other_exe))

    # 그 파일보다 먼저 옮긴 PC: 새 파일에 ERPia 가 없고 login_manager_config.json 이 남아 있다
    st.write_user_config({"LogIn": {"AdminCode": "x", "ID": "a", "PW": PW}})
    json.dump({"exe_path": fake_exe.replace("\\", "/")}, open(lm_old, "w", encoding="utf-8"))
    msg = st.migrate_user_config()
    check("먼저 옮긴 PC 도 켤 때 ERPia 위치를 가져오고 옛 파일은 .old", msg and "ERPia 위치" in msg and os.path.isfile(lm_old + ".old")
          and not os.path.exists(lm_old) and json.load(open(new, encoding="utf-8"))["ERPia"]["ExePath"] == fake_exe.replace("\\", "/"), str(msg))
    check("한 번 가져오면 다시 할 일이 없다", st.migrate_user_config() is None)
finally:
    st._erpia_install_dirs, st.pick_erpia_exe = real_dirs, real_pick

# ---------------------------------------------------------------------------
print()
print("=== 7. 루틴이 ERPia 를 켤 때 (사람이 띄운 실행 / 무인 실행) ===")
calls = []
st.pick_erpia_exe = lambda: calls.append("창") or None
st._erpia_install_dirs = lambda: []
write_cfg(None)
try:
    os.environ["RPA_UNATTENDED"] = "1"
    try:
        rr.load_exe_path()
        check("무인 실행은 창을 안 띄우고 바로 멈춘다 (사유에 고르는 법)", False, "예외 없음")
    except RuntimeError as e:
        check("무인 실행은 창을 안 띄우고 바로 멈춘다 (사유에 고르는 법)", calls == [] and "찾지 못했습니다" in str(e) and "고르는 창" in str(e), str(e))
    del os.environ["RPA_UNATTENDED"]
    try:
        rr.load_exe_path()
    except RuntimeError:
        pass
    check("사람이 띄운 실행이면 고르는 창을 띄운다", calls == ["창"], str(calls))

    real_find_pid, real_load = rr.ec.find_erpia_pid, rr.load_exe_path
    rr.ec.find_erpia_pid = lambda: 4321
    rr.load_exe_path = lambda: calls.append("위치") or "없음"
    try:
        check("ERPia 가 이미 떠 있으면 위치를 찾지도 묻지도 않는다", rr.ensure_erpia_running() == 4321 and calls == ["창"], str(calls))
    finally:
        rr.ec.find_erpia_pid, rr.load_exe_path = real_find_pid, real_load
finally:
    os.environ.pop("RPA_UNATTENDED", None)
    st._erpia_install_dirs, st.pick_erpia_exe = real_dirs, real_pick

import rpa_dashboard as dash  # noqa: E402
src = open(dash.__file__, encoding="utf-8").read()
check("대시보드·에이전트가 띄우는 실행에는 무인 표시(RPA_UNATTENDED)를 붙인다", 'env={**os.environ, "RPA_UNATTENDED": "1", **(env or {})}' in src)   # 예약 줄의 모듈(RPA_RUN_MODULES)도 같이 (2026-10-07)

finish()
