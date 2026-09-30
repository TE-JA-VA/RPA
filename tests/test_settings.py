"""설정 창(rpa_settings.py)의 창 없는 부분 시험 - 칸 확인·설정 합치기·저장·작업 XML·옛 에이전트·멈추기·가져오기.

    .venv\\Scripts\\python.exe tests\\test_settings.py

새 구조 자리는 RPA_PROGRAMDATA 임시 폴더다 (이 PC 에 진짜 ProgramData\\AFTER MARKET\\RPA\\config 를 만들지 않는다).
로그인·작업 명령(schtasks)은 가짜로 바꿔 끼운다. 작업 XML 만은 관리자 권한 없이 되는 모양(LeastPrivilege)으로
진짜 작업 스케줄러에 한 번 등록해 보고 곧바로 지운다.
"""
import json
import os
import shutil
import ssl
import sys
import tempfile
import time
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = tempfile.mkdtemp(prefix="rpa_settings_")
PD = os.path.join(TMP, "programdata", "AFTER MARKET", "RPA")
os.makedirs(os.path.join(PD, "config"))
os.makedirs(os.path.join(TMP, "agentdata"))
for _k in ("RPA_USER_CONFIG", "RPA_CRED_FILE", "RPA_AGENT_CONFIG"):
    os.environ.pop(_k, None)
os.environ["RPA_PROGRAMDATA"] = PD
os.environ["RPA_AGENT_QUEUE"] = os.path.join(TMP, "agentdata", "queue.jsonl")
os.environ["RPA_AGENT_MUTEX"] = rf"Local\AFTER_MARKET_RPA_AGENT_SETTINGS_TEST_{os.getpid()}"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "firebase" / "agent"))
sys.stdout.reconfigure(encoding="utf-8")

import agent  # noqa: E402
import background as bg  # noqa: E402
import fb  # noqa: E402
import rpa_settings as rs  # noqa: E402
import rpa_status as st  # noqa: E402
import secret  # noqa: E402

fails = []
_no = [0]


def check(name, cond, detail=""):
    _no[0] += 1
    mark = "통과" if cond else "실패"
    print(f"  {_no[0]:2d}. [{mark}] {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(f"{_no[0]}. {name} {detail}")


TEMPLATE = ROOT / "release" / "RPA_UserConfig.template.json"
ERP_PW, MAIL_PW, AGENT_PW = "Erp-Pw-1234!", "Mail-Pw-9876!", "Agent-Pw-5555!"


def paths_in(name):
    """시험용 자리. 설치 폴더 이름에 한글과 빈칸을 넣는다 (Program Files 처럼)."""
    d = os.path.join(TMP, name)
    cfg, prog = os.path.join(d, "config"), os.path.join(d, "설치 폴더")
    os.makedirs(cfg)
    os.makedirs(os.path.join(d, "data"))
    os.makedirs(os.path.join(prog, "firebase", "agent"))
    shutil.copyfile(TEMPLATE, os.path.join(prog, rs.TEMPLATE_NAME))
    return {"program_dir": prog, "config_dir": cfg, "user_config": os.path.join(cfg, st.USER_CONFIG_NAME),
            "agent_config": os.path.join(cfg, rs.AGENT_CONFIG_NAME), "template": os.path.join(prog, rs.TEMPLATE_NAME),
            "agent_py": os.path.join(prog, "firebase", "agent", "agent.py"),
            "stop_file": os.path.join(d, "data", bg.STOP_NAME)}


def write_stop(paths, code):
    with open(paths["stop_file"], "w", encoding="utf-8") as f:
        json.dump({"code": code, "reason": bg.STOP_CODES[code], "at": "2026-09-29 15:00:00"}, f, ensure_ascii=False)


def good_form(**kw):
    f = dict(cid="net", pc_id="test", agent_pw=AGENT_PW, admin_code="AM001", erp_id="rpa", erp_pw=ERP_PW,
             erpia_path="", mail_id="mail@x.com", mail_pw=MAIL_PW, printer="사무실 프린터",
             print_mode=rs.PRINT_MANUAL, carrier="롯데택배", box="소", fare="착불")
    f.update(kw)
    return f


class Recorder:
    """가짜 명령 실행기: schtasks 인수를 모은다."""

    def __init__(self, code=0):
        self.calls, self.code = [], code

    def __call__(self, args, timeout=60):
        self.calls.append(list(args))
        return self.code, ""

    def verbs(self):
        return [a[1] for a in self.calls]


class Running:
    """가짜 잠금: 처음엔 on, 작업을 끝내면(/End) off. sticky 면 끝까지 안 풀린다."""

    def __init__(self, on, rec=None, sticky=False):
        self.on, self.rec, self.sticky = on, rec, sticky

    def __call__(self):
        if self.on and not self.sticky and self.rec is not None and "/End" in self.rec.verbs():
            self.on = False
        return self.on


logins = []


def fake_login(path, cid, pc_id, password):
    logins.append((cid, pc_id))
    secret.write_config(path, dict(secret.PUBLIC, email=agent.email_for(cid, pc_id), cid=cid, pc_id=pc_id), password)


NONE_STATE = {"agent_pw": "none", "erp_pw": "none", "mail_pw": "none", "mail_site": "SITE1", "saved": (None, None)}
OK_STATE = {"agent_pw": "ok", "erp_pw": "ok", "mail_pw": "ok", "mail_site": "SITE1", "saved": ("net", "test")}

print("=== 1. 칸 확인 ===")
p = rs.validate({k: "" for k in rs.FORM_KEYS}, NONE_STATE)
check("빈 칸은 모두 알린다", all(any(w in x for x in p) for w in (
    "업체코드를 넣으세요", "PC코드를 넣으세요", "처음 설정이라 기계 계정 비밀번호", "ERPia 관리자코드", "ERPia 아이디",
    "ERPia 비밀번호")), p)
check("업체코드 대문자는 안 된다", any("소문자" in x for x in rs.validate(good_form(cid="Net"), NONE_STATE)))
check("다 채우면 통과", rs.validate(good_form(), NONE_STATE) == [])
f = good_form(agent_pw="", erp_pw="", mail_pw="")
check("저장된 값이 있으면 비밀번호 칸을 비워도 된다 (로그인도 다시 안 한다)",
      rs.validate(f, OK_STATE) == [] and not rs.needs_agent_login(f, OK_STATE))
f = good_form(cid="net2", agent_pw="")
check("코드를 바꾸면 기계 계정 비밀번호가 필요하다",
      rs.needs_agent_login(f, OK_STATE) and any("바꿔서" in x for x in rs.validate(f, OK_STATE)))
p = rs.validate(good_form(agent_pw="", erp_pw=""), dict(OK_STATE, agent_pw="bad", erp_pw="bad"))
check("못 푸는 저장값이면 다시 넣게 한다", any("풀 수 없어" in x for x in p) and any("ERPia 비밀번호" in x for x in p), p)
fake_exe = os.path.join(TMP, "erp", st.ERPIA_EXE_NAME)
os.makedirs(os.path.dirname(fake_exe))
open(fake_exe, "wb").close()
check("ERPia 위치: 다른 파일이면 알린다",
      any("ERPia 위치" in x for x in rs.validate(good_form(erpia_path=sys.executable), NONE_STATE)))
check("ERPia 위치: ERPiaMain.exe 나 그 폴더면 통과", rs.validate(good_form(erpia_path=fake_exe), NONE_STATE) == []
      and rs.validate(good_form(erpia_path=os.path.dirname(fake_exe)), NONE_STATE) == [])
check("메일 아이디만 있고 비밀번호가 없으면 알린다",
      any("메일 비밀번호" in x for x in rs.validate(good_form(mail_pw=""), NONE_STATE)))
check("메일 사이트가 없으면 메일 칸은 안 본다", rs.validate(good_form(mail_pw=""), dict(NONE_STATE, mail_site=None)) == [])
check("물류 칸은 비워도 통과 (물류 모듈을 안 쓰는 업체)",
      rs.validate(good_form(carrier="", box="", fare="", printer=""), NONE_STATE) == [])

print("=== 2. 설정 합치기 ===")
base = st.read_user_config(str(TEMPLATE))
merged = rs.merge_user_config(base, good_form(erpia_path=os.path.dirname(fake_exe)))
check("ERPia 로그인 칸", merged["LogIn"] == {"AdminCode": "AM001", "ID": "rpa", "PW": ERP_PW}, merged["LogIn"])
check("실행 모듈은 빈 틀 그대로 (로그인만 Y)", merged["Routine"] == base["Routine"]
      and merged["Routine"]["Login"] == "Y" and merged["Routine"]["Sales"] == "N")
check("메일 사이트(SITE1) 아이디·비밀번호", merged["Sites"]["SITE1"]["ID"] == "mail@x.com"
      and merged["Sites"]["SITE1"]["PW"] == MAIL_PW)
check("다른 사이트·주석은 그대로", merged["Sites"]["SITE2"] == base["Sites"]["SITE2"]
      and merged["Sites"]["_주석"] == base["Sites"]["_주석"])
check("물류 칸 다섯을 RPA 가 읽는 이름으로 (출력 방식 수동 = N)", merged["Logistic"] == {
    "cboBS_Auto_YN": "N", "Printer": "사무실 프린터", "cboTag": "롯데택배", "cboTagAmt": "소", "cboBeasong_Gu_Apply": "착불"},
    merged["Logistic"])
auto = rs.merge_user_config(dict(base, Logistic=dict(base["Logistic"], _메모="그대로")), good_form(print_mode=rs.PRINT_AUTO))
check("출력 방식 자동 = Y, 물류 섹션의 다른 키는 그대로", auto["Logistic"]["cboBS_Auto_YN"] == "Y"
      and auto["Logistic"]["_메모"] == "그대로", auto["Logistic"])
check("ERPia 위치는 폴더를 줘도 exe 경로로, / 로", merged["ERPia"]["ExePath"] == fake_exe.replace("\\", "/"))
check("받은 dict 는 그대로 (사본에 쓴다)", base["LogIn"]["PW"] == "")
kept = rs.merge_user_config(dict(base, LogIn={"AdminCode": "a", "ID": "b", "PW": "dpapi:old"},
                                 ERPia={"ExePath": "C:/x/ERPiaMain.exe"}), good_form(erp_pw="", mail_pw="", erpia_path=""))
check("비밀번호 칸이 비면 저장된 값을 둔다", kept["LogIn"]["PW"] == "dpapi:old"
      and kept["Sites"]["SITE1"]["PW"] == base["Sites"]["SITE1"]["PW"])
check("ERPia 위치 칸이 비면 저장된 값을 둔다", kept["ERPia"]["ExePath"] == "C:/x/ERPiaMain.exe")

print("=== 2-1. 물류 칸 채우기 ===")
check("출력 방식 목록: 수동이 먼저 (기본값, 수동을 쓰는 업체가 더 많다)", list(rs.PRINT_MODES) == [rs.PRINT_MANUAL, rs.PRINT_AUTO]
      and rs.PRINT_MODES == {rs.PRINT_MANUAL: "N", rs.PRINT_AUTO: "Y"})
check("빈 틀: 출력 방식 수동(N), 택배사·박스·운임은 비어 있다 (우리 회사 값을 다른 업체가 물려받지 않게)",
      base["Logistic"] == {"cboBS_Auto_YN": "N", "Printer": "", "cboTag": "", "cboTagAmt": "", "cboBeasong_Gu_Apply": ""},
      base["Logistic"])
L = paths_in("logistic")
form, _ = rs.load_state(L)
check("새 설치(빈 틀)는 수동, 빈 칸", form["print_mode"] == rs.PRINT_MANUAL and form["carrier"] == form["box"] == form["fare"] == "",
      form)
data = st.read_user_config(str(TEMPLATE))
data["Logistic"].update(cboBS_Auto_YN="a", cboTag="한진연동", cboTagAmt="대", cboBeasong_Gu_Apply="신용")
st.write_user_config(data, L["user_config"])
form, _ = rs.load_state(L)
check("저장된 값으로 채운다 (A·Y 는 자동 - RPA 의 resolve_auto_mode 와 같은 규칙, 소문자도)",
      form["print_mode"] == rs.PRINT_AUTO and (form["carrier"], form["box"], form["fare"]) == ("한진연동", "대", "신용"), form)
del data["Logistic"]["cboBS_Auto_YN"]
st.write_user_config(data, L["user_config"])
check("출력 방식 값이 없으면 수동 (RPA 도 수동으로 돈다)", rs.load_state(L)[0]["print_mode"] == rs.PRINT_MANUAL)

print("=== 3. 메일 사이트 고르기 ===")
check("빈 틀은 SITE1", rs.mail_site(base) == "SITE1")
check("Action 이 글자 하나여도, '_' 주석은 건너뛴다", rs.mail_site({"Sites": {
    "_x": {"Action": "mail_download"}, "A": {"Action": "login"}, "B": {"Action": "mail_download"}}}) == "B")
check("없으면 None", rs.mail_site({"Sites": {"A": {"Action": ["login", "sms_2fa"]}}}) is None and rs.mail_site({}) is None)

print("=== 4. 비밀번호 칸 상태 ===")
check("없음", rs.pw_state("", st.unseal) == "none" and rs.pw_state(None, st.unseal) == "none")
check("이 PC 에서 잠근 값은 ok", rs.pw_state(st.seal("abc"), st.unseal) == "ok"
      and rs.pw_state(secret.protect("abc"), secret.unprotect) == "ok")
check("못 푸는 값은 bad", rs.pw_state("dpapi:AAAA", st.unseal) == "bad" and rs.pw_state("AAAA", secret.unprotect) == "bad")
check("평문(손으로 적은 값)은 ok - 저장할 때 잠근다", rs.pw_state("plain", st.unseal) == "ok")

print("=== 5. 저장 ===")
warms = []                          # 인증서 채우기를 부른 때의 로그인 횟수 (로그인보다 먼저여야 한다)
rs.warm_roots = lambda: warms.append(len(logins))
P = paths_in("save")
rec = Recorder()
done = rs.save(good_form(), P, login=fake_login, run=rec, running=Running(False), user="PC\\me")
check("기계 계정 로그인 전에 윈도우 인증서를 채운다 (갓 설치한 윈도우)", warms == [0], warms)
raw = Path(P["user_config"]).read_bytes()
check("처음 저장: 로그인·설정·에이전트 켜기", logins == [("net", "test")] and "에이전트를 켰습니다" in " ".join(done), done)
check("비밀번호 평문이 파일에 없다", all(pw.encode() not in raw for pw in (ERP_PW, MAIL_PW))
      and AGENT_PW.encode() not in Path(P["agent_config"]).read_bytes())
cfg = st.read_user_config(P["user_config"])
check("잠가서 저장 (dpapi:)", cfg["LogIn"]["PW"].startswith("dpapi:") and st.unseal(cfg["LogIn"]["PW"]) == ERP_PW
      and st.unseal(cfg["Sites"]["SITE1"]["PW"]) == MAIL_PW)
check("작업 등록 뒤 켜기 (꺼져 있어도 먼저 끝낸다)", rec.verbs() == ["/Create", "/End", "/Run"]
      and rec.calls[0][2:4] == ["/TN", rs.TASK_NAME], rec.calls)
check("작업 XML 은 잠깐 썼다 지운다", not os.path.exists(os.path.join(P["config_dir"], "agent_task.xml")))
first_pw = cfg["LogIn"]["PW"]
rec = Recorder()
done = rs.save(good_form(agent_pw="", erp_pw="", mail_pw="", printer="다른 프린터", carrier="CJ대한통운"), P,
               login=fake_login, run=rec, running=Running(True), user="PC\\me")
cfg = st.read_user_config(P["user_config"])
check("비밀번호를 비우고 프린터·택배사만 바꾸면 로그인·다시 켜기 없이 저장 (RPA 는 실행할 때마다 설정을 읽는다)",
      len(logins) == 1 and rec.verbs() == ["/Create"]
      and "에이전트를 켰습니다" not in " ".join(done) and "설정을 저장했습니다" in " ".join(done), (logins, rec.verbs(), done))
check("비운 비밀번호 칸은 저장된 값 그대로", cfg["LogIn"]["PW"] == first_pw and cfg["Logistic"]["Printer"] == "다른 프린터"
      and cfg["Logistic"]["cboTag"] == "CJ대한통운")
check("로그인을 안 하면 인증서도 안 채운다", warms == [0], warms)
rec = Recorder()
rs.save(good_form(agent_pw="new-agent-pw", erp_pw=""), P, login=fake_login, run=rec, running=Running(True, rec),
        user="PC\\me")
check("기계 계정을 다시 넣으면 멈췄다가 켠다", rec.verbs() == ["/Create", "/End", "/Run"] and len(logins) == 2, rec.verbs())
try:
    rs.save(good_form(cid="other", agent_pw="", erp_pw=""), P, login=fake_login, run=Recorder(), running=Running(False),
            user="PC\\me")
    check("코드만 바꾸고 비밀번호 없이 저장은 거절", False)
except ValueError as e:
    check("코드만 바꾸고 비밀번호 없이 저장은 거절", "바꿔서" in str(e), str(e))
P2 = paths_in("loginfail")


def refuse(*a):
    raise ValueError("기계 계정 로그인이 안 됩니다: 비밀번호가 맞지 않습니다")


try:
    rs.save(good_form(), P2, login=refuse, run=Recorder(), running=Running(False), user="PC\\me")
    check("로그인이 안 되면 아무것도 쓰지 않는다", False)
except ValueError:
    check("로그인이 안 되면 아무것도 쓰지 않는다", not os.path.exists(P2["user_config"])
          and not os.path.exists(P2["agent_config"]))
P3 = paths_in("notemplate")
os.remove(P3["template"])
try:
    rs.save(good_form(), P3, login=fake_login, run=Recorder(), running=Running(False), user="PC\\me")
    check("빈 틀이 없으면 멈춘다 (실행 모듈이 다 켜진 설정을 만들지 않게)", False)
except RuntimeError as e:
    check("빈 틀이 없으면 멈춘다 (실행 모듈이 다 켜진 설정을 만들지 않게)", "빈 틀" in str(e) and len(logins) == 2, str(e))
try:
    rs.save(good_form(agent_pw="", erp_pw=""), P, login=fake_login, run=Recorder(code=1), running=Running(False),
            user="PC\\me")
    check("작업 등록이 안 되면 알린다", False)
except RuntimeError as e:
    check("작업 등록이 안 되면 알린다", "자동 시작 작업을 등록하지 못했습니다" in str(e), str(e))

S = paths_in("stopped")
rs.save(good_form(), S, login=fake_login, run=Recorder(), running=Running(False), user="PC\\me")
write_stop(S, 3)
form, state = rs.load_state(S)
check("에이전트가 로그인 거부(3)로 멈췄으면 기계 계정 비밀번호 칸을 다시 받는다",
      state["agent_pw"] == "refused" and state["stopped"]["code"] == 3 and rs.needs_agent_login(form, state), state)
p = rs.validate(form, state)
check("비운 채 저장은 거절 (그대로 켜면 몇 초 뒤 또 멈춘다)", any("거부" in x for x in p), p)
rec = Recorder()
rs.save(dict(form, agent_pw="new-agent-pw"), S, login=fake_login, run=rec, running=Running(False), user="PC\\me")
check("새 비밀번호로 저장하면 멈춘 기록을 지우고 켠다", not os.path.exists(S["stop_file"]) and rec.verbs()[-1] == "/Run")
write_stop(S, 2)
_, state = rs.load_state(S)
check("설정 문제(2)로 멈춘 것도 까닭을 들고 온다 (비밀번호 칸은 그대로)", state["stopped"]["code"] == 2 and state["agent_pw"] == "ok")
E = paths_in("noerpia")
data = st.read_user_config(str(TEMPLATE))
data["ERPia"] = {"ExePath": "C:/없는 폴더/ERPiaMain.exe"}
st.write_user_config(data, E["user_config"])
saved_dirs = st._erpia_install_dirs
st._erpia_install_dirs = lambda: []
try:
    _, state = rs.load_state(E)
    check("ERPia 를 못 찾으면 알린다 (설계: 경고만)", state["erpia_missing"] is True)
    done = rs.save(good_form(), E, login=fake_login, run=Recorder(), running=Running(False), user="PC\\me")
    check("저장은 되고, ERPia 를 아직 못 찾았다고 덧붙인다", "ERPia 는 아직 못 찾았습니다" in " ".join(done), done)
finally:
    st._erpia_install_dirs = saved_dirs

print("=== 6. 기계 계정 로그인 오류 문장 ===")
orig_first_run = agent.first_run
try:
    for exc, want in ((fb.AuthError(400, "INVALID_LOGIN_CREDENTIALS"), "비밀번호가 맞지 않습니다"),
                      (ValueError("기계 계정(agent-…)이 아닙니다"), "기계 계정(agent-…)이 아닙니다"),
                      (urllib.error.URLError("down"), "인터넷에 연결하지 못해"),
                      (urllib.error.URLError(ssl.SSLCertVerificationError(
                          1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")), "보안 인증서")):
        def boom(*a, _e=exc, **k):
            raise _e
        agent.first_run = boom
        try:
            rs.agent_login("x.json", "net", "test", "pw")
            check(f"{type(exc).__name__} → 사람 문장", False)
        except ValueError as e:
            check(f"{type(exc).__name__} → 사람 문장", want in str(e), str(e))
    import urllib.request  # noqa: E402
    sentinel = object()
    urllib.request._opener = sentinel
    agent.first_run = lambda *a, **k: None
    rs.agent_login("x.json", "net", "test", "pw")
    check("로그인할 때마다 urllib 을 새로 만든다 (앞선 실패 때 읽은 인증서 목록을 버리게)", urllib.request._opener is not sentinel)
finally:
    agent.first_run = orig_first_run
    urllib.request._opener = None

print("=== 7. 작업 XML ===")
prog = r"C:\Program Files\AFTER MARKET\RPA"
ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
x = ET.fromstring(rs.task_xml("PC\\me & you", prog).encode("utf-16"))


def val(path):
    e = x.find(path, ns)
    return e.text if e is not None else None


check("로그온 트리거와 계정 (& 도 이스케이프)", val("t:Triggers/t:LogonTrigger/t:UserId") == "PC\\me & you"
      and val("t:Principals/t:Principal/t:UserId") == "PC\\me & you")
check("로그온했을 때만, 가장 높은 권한", val("t:Principals/t:Principal/t:LogonType") == "InteractiveToken"
      and val("t:Principals/t:Principal/t:RunLevel") == "HighestAvailable")
check("이미 돌면 새로 안 띄움", val("t:Settings/t:MultipleInstancesPolicy") == "IgnoreNew")
check("배터리여도 켜고 안 멈춤 (노트북)", val("t:Settings/t:DisallowStartIfOnBatteries") == "false"
      and val("t:Settings/t:StopIfGoingOnBatteries") == "false")
check("실행 시간 제한 없음 (기본 3일)", val("t:Settings/t:ExecutionTimeLimit") == "PT0S")
check("우선순위 5 (기본 7 은 낮음)", val("t:Settings/t:Priority") == "5")
check("동작: AFTER MARKET 사본이 없으면 내장 pythonw 로 background.py", val("t:Actions/t:Exec/t:Command") == prog + r"\python\pythonw.exe"
      and val("t:Actions/t:Exec/t:Arguments") == f'"{prog}\\firebase\\agent\\background.py"'
      and val("t:Actions/t:Exec/t:WorkingDirectory") == prog + r"\firebase\agent")
with tempfile.TemporaryDirectory() as d:
    os.makedirs(os.path.join(d, "python"))
    open(os.path.join(d, "python", bg.SUPERVISOR_EXE), "wb").close()
    cmd = ET.fromstring(rs.task_xml("PC\\me", d).encode("utf-16")).find("t:Actions/t:Exec/t:Command", ns).text
    check("동작: 설치 판은 작업 관리자에 AFTER MARKET 으로 보이는 감독 사본", cmd == os.path.join(d, "python", bg.SUPERVISOR_EXE)
          and bg.SUPERVISOR_EXE.startswith("AFTER_MARKET"), cmd)
name = f"RPA_settings_selftest_{os.getpid()}"
xf = os.path.join(TMP, "selftest.xml")
with open(xf, "w", encoding="utf-16") as f:
    f.write(rs.task_xml(rs.process_user(), prog).replace("HighestAvailable", "LeastPrivilege"))
try:
    code, out = rs.run_quiet(["schtasks", "/Create", "/TN", name, "/XML", xf, "/F"])
    qcode, q = rs.run_quiet(["schtasks", "/Query", "/TN", name, "/XML"])
    check("진짜 작업 스케줄러가 XML 을 받는다 (관리자 권한 없이 되는 LeastPrivilege 로 등록 → 조회)",
          code == 0 and qcode == 0 and "<Priority>5</Priority>" in q and "<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>" in q,
          out[-300:])
finally:
    rs.run_quiet(["schtasks", "/Delete", "/TN", name, "/F"])
check("시험 작업은 지웠다", rs.run_quiet(["schtasks", "/Query", "/TN", name])[0] != 0)

print("=== 8. 옛 에이전트·도는 RPA ===")
ours = r"C:\Program Files\AFTER MARKET\RPA\firebase\agent\agent.py"
procs = [
    (11, "python.exe", r"C:\Program Files\AFTER MARKET\RPA\python\python.exe",
     rf'"C:\Program Files\AFTER MARKET\RPA\python\python.exe" "{ours}"'),
    (12, "python.exe", r"D:\AX\배포_2026.09.29-4\python\python.exe",
     r'"D:\AX\배포_2026.09.29-4\firebase\agent\..\..\python\python.exe"  agent.py'),
    (13, "pythonw.exe", r"C:\Program Files\AFTER MARKET\RPA\python\pythonw.exe",
     r'"C:\Program Files\AFTER MARKET\RPA\python\pythonw.exe" "C:\Program Files\AFTER MARKET\RPA\firebase\agent\background.py"'),
    (14, "python.exe", r"C:\Python\python.exe", "python useragent.py"),
    (15, "ERPia_RPA.exe", r"C:\Program Files\AFTER MARKET\RPA\ERPia_RPA.exe", ""),
    (16, "pythonw.exe", r"D:\old\python\pythonw.exe", r"pythonw D:\old\firebase\agent\agent.py"),
]
check("옛 에이전트만 가린다 (상대 경로·다른 폴더)", [p[0] for p in rs.old_agents(procs, ours)] == [12, 16],
      rs.old_agents(procs, ours))
check("도는 RPA", rs.rpa_running(procs) == ["ERPia_RPA.exe"] and rs.rpa_running([]) == [])
mine = [p for p in rs.list_processes() if p[0] == os.getpid()]
check("진짜 프로세스 목록에 이 시험 프로세스 (명령줄 포함)", len(mine) == 1 and "test_settings.py" in mine[0][3], mine)

print("=== 9. 멈추기·켜기 ===")
rec = Recorder()
check("RPA 가 돌면 5 (작업은 건드리지 않는다)", rs.stop_agent(procs=[(15, "ERPia_RPA.exe", "", "")], run=rec,
                                                  running=Running(True)) == rs.EXIT_RPA_RUNNING and rec.calls == [])
rec = Recorder()
check("끝내고 잠금이 풀리면 0", rs.stop_agent(procs=[], run=rec, running=Running(True, rec)) == 0
      and rec.verbs() == ["/End"])
rec = Recorder()
check("잠금이 안 풀리면 6", rs.stop_agent(procs=[], run=rec, running=Running(True, rec, sticky=True), wait=0.3,
                                      sleep=lambda s: time.sleep(0.05)) == rs.EXIT_STOP_FAILED)
rec = Recorder()
rs.restart_agent(run=rec, running=Running(False))
check("꺼져 있어도 먼저 끝낸다 (감독이 다시 켜기를 기다리는 중이면 /Run 이 무시된다)", rec.verbs() == ["/End", "/Run"], rec.verbs())
check("--check-rpa: RPA 가 돌면 5, 아니면 0 (멈추지 않는다)",
      rs.check_rpa(procs=[(15, "ERPia_RPA.exe", "", "")]) == rs.EXIT_RPA_RUNNING and rs.check_rpa(procs=[]) == 0)
try:
    rs.restart_agent(run=Recorder(), running=Running(True, sticky=True), wait=0.3, sleep=lambda s: time.sleep(0.05))
    check("안 멈추면 알린다", False)
except RuntimeError as e:
    check("안 멈추면 알린다", "멈추지 않습니다" in str(e))
try:
    rs.start_task(run=Recorder(code=1))
    check("켜기가 안 되면 알린다", False)
except RuntimeError as e:
    check("켜기가 안 되면 알린다", "켜지 못했습니다" in str(e))

print("=== 10. 에이전트 잠금 ===")
check("잠금이 없으면 꺼져 있음", rs.agent_running() is False)
check("에이전트가 잠그면 돌고 있음", agent.single_instance() is True and rs.agent_running() is True)

print("=== 11. 옛 폴더에서 가져오기 ===")
old = os.path.join(TMP, "배포_2026.09.29-4")
os.makedirs(os.path.join(old, "firebase", "agent"))
open(os.path.join(old, "Run_All.bat"), "wb").close()                  # 옛 배포 폴더 표시
old_cfg = st.read_user_config(str(TEMPLATE))
old_cfg["LogIn"].update(AdminCode="OLD", ID="old", PW="dpapi:AAAA")     # 다른 PC 에서 잠근 값 흉내
old_cfg["Logistic"].update(cboBS_Auto_YN="Y", cboTag="한진연동", cboTagAmt="대", cboBeasong_Gu_Apply="신용")
st.write_user_config(old_cfg, os.path.join(old, st.USER_CONFIG_NAME))
secret.write_config(os.path.join(old, "firebase", "agent", rs.AGENT_CONFIG_NAME),
                    dict(secret.PUBLIC, email=agent.email_for("net", "test"), cid="net", pc_id="test"), AGENT_PW)
Q = paths_in("import")
check("두 파일을 가져온다", rs.import_old(old, Q["config_dir"]) == [st.USER_CONFIG_NAME, rs.AGENT_CONFIG_NAME])
form, state = rs.load_state(Q)
check("가져온 값으로 칸을 채운다 (비밀번호 칸은 비움)", form["cid"] == "net" and form["admin_code"] == "OLD"
      and form["agent_pw"] == "" and state["saved"] == ("net", "test"), (form, state))
check("이 PC 에서 잠근 기계 계정은 ok, 못 푸는 ERPia 비밀번호는 bad", state["agent_pw"] == "ok" and state["erp_pw"] == "bad")
check("옛 폴더의 물류 값도 딸려 온다", form["print_mode"] == rs.PRINT_AUTO
      and (form["carrier"], form["box"], form["fare"]) == ("한진연동", "대", "신용"), form)
try:
    rs.import_old(old, Q["config_dir"])
    check("이미 있으면 묻는다 (FileExistsError)", False)
except FileExistsError as e:
    check("이미 있으면 묻는다 (FileExistsError)", st.USER_CONFIG_NAME in str(e))
check("덮어쓰기", rs.import_old(old, Q["config_dir"], overwrite=True) == [st.USER_CONFIG_NAME, rs.AGENT_CONFIG_NAME])
only = os.path.join(TMP, "only_user")
os.makedirs(only)
shutil.copyfile(os.path.join(old, st.USER_CONFIG_NAME), os.path.join(only, st.USER_CONFIG_NAME))
try:
    rs.import_old(only, paths_in("import1")["config_dir"])
    check("Run_All.bat 이 없는 폴더(바탕화면 등)는 옛 배포 폴더가 아니다 - 가져오지도, 이름을 바꾸자고도 않는다", False)
except FileNotFoundError:
    check("Run_All.bat 이 없는 폴더(바탕화면 등)는 옛 배포 폴더가 아니다 - 가져오지도, 이름을 바꾸자고도 않는다", True)
open(os.path.join(only, "Run_All.bat"), "wb").close()
check("하나만 있으면 그것만", rs.import_old(only, paths_in("import2")["config_dir"]) == [st.USER_CONFIG_NAME])
try:
    rs.import_old(os.path.join(TMP, "erp"), paths_in("import3")["config_dir"])
    check("설정 파일이 없는 폴더는 FileNotFoundError", False)
except FileNotFoundError:
    check("설정 파일이 없는 폴더는 FileNotFoundError", True)
new = rs.retire_old_folder(old)
check("옛 폴더 이름 바꾸기 → _옮김", new == old + "_옮김" and os.path.isdir(new) and not os.path.exists(old))
os.makedirs(old)
check("또 바꾸면 _옮김2", rs.retire_old_folder(old) == old + "_옮김2")

print("=== 12. 계정·설치 확인 ===")
check("계정 비교는 대소문자 무시", rs.same_account("PC\\Me", "pc\\me") and not rs.same_account("PC\\a", None)
      and not rs.same_account("", ""))
INST = rs.INSTALL_DIR
check("설치 자리 = Program Files\\AFTER MARKET\\RPA", INST.lower().endswith("\\program files\\after market\\rpa"), INST)
p = rs.start_problem(session="PC\\staff", me="PC\\admin", here=INST)
check("다른 계정의 권한으로 뜨면 멈춘다", p is not None and "PC\\staff" in p and "PC\\admin" in p, p)
check("같은 계정이면 통과", rs.start_problem(session="PC\\me", me="pc\\ME", here=INST) is None)
check("세션 계정을 못 알아내면 막지 않는다", rs.start_problem(session="", me="PC\\me", here=INST) is None)
p = rs.start_problem(session="PC\\me", me="PC\\me", here=r"D:\AX\배포_2026.09.29-5")
check("설치 폴더가 아닌 사본(압축 폴더)에서 열면 멈춘다 - 자동 시작이 누구나 고칠 수 있는 폴더를 가리키게 되므로",
      p is not None and "Program Files" in p, p)
check("설치 폴더 비교는 대소문자를 가리지 않는다", rs.start_problem(session="", me="x", here=INST.upper()) is None)
os.environ["RPA_PROGRAMDATA"] = os.path.join(TMP, "no_install")
try:
    p = rs.start_problem(session="PC\\me", me="PC\\me", here=INST)
    check("설치 마법사로 설치한 PC 가 아니면 멈춘다", p is not None and "설치 마법사" in p, p)
finally:
    os.environ["RPA_PROGRAMDATA"] = PD
check("이 PC: 이 시험 프로세스의 계정 = 로그인한 계정", rs.same_account(rs.process_user(), rs.session_user()),
      (rs.process_user(), rs.session_user()))

print("=== 13. 판 올림 (--after-install) ===")
check("설정을 마친 PC 는 판 올림으로 본다", rs.configured(P))
check("처음 설치는 아니다", not rs.configured(paths_in("fresh")))
R = paths_in("badagent")
shutil.copyfile(P["user_config"], R["user_config"])
with open(R["agent_config"], "w", encoding="utf-8") as f:
    f.write('{"project_id": "p", "api_key": "k", "database_url": "u", "cid": "net", "pc_id": "test", '
            '"email": "e", "password_dpapi": "AAAA"}')
check("기계 계정 비밀번호가 안 풀리면 판 올림이 아니다 (창을 띄운다)", not rs.configured(R))
rec = Recorder()
rs.finish_upgrade(P, run=rec, running=Running(False), user="PC\\me")
check("판 올림: 작업 다시 등록 → 켜기", rec.verbs() == ["/Create", "/End", "/Run"], rec.verbs())

print("=== 14. 그 밖 ===")
check("프린터 목록은 글자 목록", isinstance(rs.list_printers(), list) and all(isinstance(n, str) for n in rs.list_printers()))
check("관리자가 아니면 --after-install --no-window 는 아무것도 안 하고 0",
      not rs.is_admin() and rs.main(["--after-install", "--no-window"]) == 0)
shown = []
saved_funcs = (rs.is_admin, rs.default_paths, rs.show_error_box)


def broken():
    raise RuntimeError("일부러 깨뜨림")


try:
    rs.is_admin, rs.default_paths, rs.show_error_box = (lambda: True), broken, shown.append
    code = rs.main([])
    crash = os.path.join(st.data_dir(), rs.CRASH_LOG_NAME)
    check("창 모드에서 뜻밖의 오류가 나면 알림 창으로 알리고 1 (pythonw 라 그냥 죽으면 아무것도 안 보인다)",
          code == 1 and len(shown) == 1 and "일부러 깨뜨림" in shown[0], (code, shown))
    check("오류 추적은 기록 폴더의 설정창_오류.txt 에", os.path.isfile(crash)
          and "일부러 깨뜨림" in open(crash, encoding="utf-8").read())
    shown.clear()
    check("--no-window 면 알림 창 없이 1", rs.main(["--after-install", "--no-window"]) == 1 and not shown, shown)
finally:
    rs.is_admin, rs.default_paths, rs.show_error_box = saved_funcs
deleted = []
saved_funcs = (rs.stop_agent, rs.delete_task)


def stop_fails(**kw):
    raise RuntimeError("멈추기 실패")


try:
    rs.stop_agent, rs.delete_task = stop_fails, (lambda run=None: deleted.append(1))
    code = rs.main(["--remove-task"])
    check("--remove-task: 멈추다 오류가 나도 작업은 지운다 (지워진 프로그램을 가리키는 작업이 남지 않게)",
          deleted == [1] and code == 1, (deleted, code))
finally:
    rs.stop_agent, rs.delete_task = saved_funcs

shutil.rmtree(TMP, ignore_errors=True)
print()
print(f"실패: {'없음' if not fails else fails}")
sys.exit(1 if fails else 0)
