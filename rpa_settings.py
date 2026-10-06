r"""RPA 설정 창 (배포판 구조 2부 4절 - docs/superpowers/specs/2026-09-29-installer-design.md).

설치 마법사(AFTER_MARKET_RPA_Setup_<판>.exe)로 설치한 PC 에서만 돈다. 설치 마지막에 한 번 뜨고, 그 뒤로는 시작 메뉴
'RPA 설정' 으로 연다.

    {설치 폴더}\python\pythonw.exe {설치 폴더}\rpa_settings.py [--after-install [--no-window] | --stop | --remove-task | --check-rpa]

창: 에이전트 계정(업체코드·PC코드·비밀번호), ERPia 로그인·설치 위치, 물류 처리 옵션(출력 방식·택배사·박스·운임·프린터)을
받아 저장하고 (메일은 다른 프로그램이 맡는다 - 2026-09-30), 윈도우 로그인 때
에이전트를 창 없이 켜는 작업(AFTER MARKET\RPA Agent)을 등록하고 에이전트를 켠다. 옛 배포 폴더에서 설정을 가져온다.
창 없는 모드는 설치 파일(release/installer.iss)이 부른다. 종료 코드: 0 됨, 5 RPA 가 돌고 있음, 6 에이전트가 안 멈춤.

비밀번호는 잠근 뒤에만 파일에 쓰고(rpa_status.write_user_config, secret.write_config), 창의 다른 곳·기록·오류 글에
싣지 않는다. 시험: tests/test_settings.py (창 없이), tests/check_settings_ui.py (진짜 창).
"""
import base64
import ctypes
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import threading
import time
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.join(HERE, "firebase", "agent")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import rpa_status as st  # noqa: E402

TASK_NAME = r"AFTER MARKET\RPA Agent"
TEMPLATE_NAME = "RPA_UserConfig.template.json"   # 설치 파일이 빈 틀 RPA_UserConfig.json 을 이 이름으로 넣는다
AGENT_CONFIG_NAME = "agent_config.json"
LOGISTIC_SECTION = "Logistic"
KEY_RE = re.compile(r"[a-z0-9_]+")               # 업체코드·PC코드 (agent.ask_key 와 같은 규칙)
AGENT_PY_RE = re.compile(r"""(^|[\\/\s"'])agent\.py\b""", re.IGNORECASE)
RPA_EXES = ("ERPia_RPA.exe", "Prepare_RPA.exe")
EXIT_RPA_RUNNING = 5
EXIT_STOP_FAILED = 6
STOP_WAIT_SEC = 15
CREATE_NO_WINDOW = 0x08000000
FORM_KEYS = ("cid", "pc_id", "agent_pw", "admin_code", "erp_id", "erp_pw", "erpia_path",
             "print_mode", "carrier", "box", "fare", "printer")
# 물류 칸 → 사용자 설정 Logistic 키. RPA 가 물류관리 화면의 같은 이름 콤보에서 글자 그대로 고른다 (업체마다 다르다 - 2026-09-30)
LOGISTIC_KEYS = {"carrier": "cboTag", "box": "cboTagAmt", "fare": "cboBeasong_Gu_Apply", "printer": "Printer"}
AUTO_MODE_KEY = "cboBS_Auto_YN"
PRINT_MANUAL, PRINT_AUTO = "수동 - 엑셀 파일", "자동 - 운송장 인쇄"
PRINT_MODES = {PRINT_MANUAL: "N", PRINT_AUTO: "Y"}    # 수동이 먼저·기본 (수동을 쓰는 업체가 더 많다)
PASSWORD_KEYS = ("agent_pw", "erp_pw")
CRASH_LOG_NAME = "설정창_오류.txt"               # 뜻밖의 오류 추적 (기록 폴더)
ICON_NAME = "AFTER_MARKET.ico"                  # 프로그램 폴더 (tools/make_icon.py 가 만든다)
APP_ID = "AFTERMARKET.RPA.Settings"             # 작업 표시줄 묶음 이름. 시작 메뉴 바로 가기(installer.iss)와 같아야 한다
# 설치 파일이 넣는 자리 {commonpf64}\AFTER MARKET\RPA (ProgramW6432 는 32비트 프로세스에서도 64비트 Program Files)
INSTALL_DIR = os.path.normpath(os.path.join(os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles")
                                            or r"C:\Program Files", *st.PRODUCT_DIRS))


# ---------------------------------------------------------------------------
# 자리와 계정 (설계 4절 시작 점검)
# ---------------------------------------------------------------------------
def default_paths():
    """이 PC 의 자리: 설치 폴더(program_dir)와 새 구조 config·data. 시험은 같은 모양의 dict 를 직접 만든다."""
    import background
    import secret
    prog = st.program_dir()
    return {"program_dir": prog, "config_dir": st.config_dir(), "user_config": st.user_config_path(),
            "agent_config": secret.CONFIG_PATH, "template": os.path.join(prog, TEMPLATE_NAME),
            "agent_py": os.path.join(prog, "firebase", "agent", "agent.py"),
            "stop_file": os.path.join(st.data_dir(), background.STOP_NAME)}


# 관리자·계정 확인은 옵저버도 쓴다 - rpa_status 에 있다 (시험은 이 모듈의 이름을 바꿔 끼운다)
is_admin, process_user, session_user, same_account = st.is_admin, st.process_user, st.session_user, st.same_account


def relaunch_as_admin(args):
    """관리자 권한으로 자기를 다시 띄운다 (UAC 요청). 띄웠으면 True, 사용자가 거절하면 False."""
    return st.run_as_admin(sys.executable, [os.path.abspath(__file__), *args], HERE)


def start_problem(session=None, me=None, here=None):
    """창을 띄우기 전 확인 (설계 4절 시작 점검 2·3). 사람에게 보일 문장, 문제가 없으면 None.
    session·me·here 는 시험용 (안 주면 이 PC 에서 알아낸다. session 이 빈 글자면 '못 알아냄' 으로 본다).
    설치 폴더 밖의 사본(손으로 넘긴 압축 폴더 등)에서 열면 멈춘다 - 그대로 저장하면 자동 시작 작업이 그 사본을 가리키는데,
    D:\\ 같은 곳의 폴더는 누구나 고칠 수 있어 그 파일이 관리자 권한으로 돌게 된다 (2026-09-29 검토)."""
    if not st.new_layout():
        return (f"설치 마법사로 설치한 PC 가 아닙니다 ({os.path.join(st.install_root(), 'config')} 이 없습니다).\n"
                "AFTER_MARKET_RPA_Setup 으로 설치한 뒤 시작 메뉴의 'RPA 설정' 을 여세요.")
    here = here or HERE
    if os.path.normcase(os.path.normpath(here)) != os.path.normcase(INSTALL_DIR):
        return (f"이 설정 창은 설치 폴더({INSTALL_DIR})의 것이 아닙니다 ({here}).\n"
                "시작 메뉴 → AFTER MARKET RPA → 'RPA 설정' 을 여세요.")
    me = me or process_user()
    session = session_user() if session is None else session
    if session and not same_account(me, session):
        return (f"이 PC 에 로그인한 윈도우 계정({session})이 아니라 다른 계정({me})의 관리자 권한으로 이 창이 떴습니다.\n"
                f"RPA 는 로그인한 계정으로 돕니다. {session} 계정을 관리자로 바꾼 뒤 그 계정으로 다시 설치하거나 "
                "'RPA 설정' 을 여세요.")
    return None


# ---------------------------------------------------------------------------
# 프로세스와 에이전트 잠금
# ---------------------------------------------------------------------------
def run_quiet(args, timeout=60):
    """창 없이 명령을 돌린다. (종료 코드, 출력 글자). 콘솔 명령은 OEM 코드 페이지로 찍는다."""
    r = subprocess.run(args, capture_output=True, timeout=timeout, creationflags=CREATE_NO_WINDOW)
    return r.returncode, (r.stdout + r.stderr).decode("oem", "replace")


def list_processes():
    """[(pid, 이름, 실행 파일, 명령줄)] - python 과 RPA exe 만. 관리자 권한이어야 관리자로 뜬 프로세스의 명령줄도 보인다.
    PowerShell 명령은 인코딩해서 넘긴다 (따옴표가 명령줄에서 깨지지 않게)."""
    names = " or ".join(f"Name='{n}'" for n in ("python.exe", "pythonw.exe") + RPA_EXES)
    script = ("[Console]::OutputEncoding = [Text.Encoding]::UTF8; ConvertTo-Json -Compress -InputObject @("
              f"Get-CimInstance Win32_Process -Filter \"{names}\" | Select-Object ProcessId,Name,ExecutablePath,CommandLine)")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand",
                        base64.b64encode(script.encode("utf-16-le")).decode("ascii")],
                       capture_output=True, timeout=60, creationflags=CREATE_NO_WINDOW)
    text = r.stdout.decode("utf-8-sig", "replace").strip()
    data = json.loads(text) if text else []
    if isinstance(data, dict):
        data = [data]
    return [(int(p.get("ProcessId") or 0), p.get("Name") or "", p.get("ExecutablePath") or "",
             p.get("CommandLine") or "") for p in data if isinstance(p, dict)]


def old_agents(procs, agent_py):
    """설치 폴더 밖의(또는 작업 밖에서 띄운) 에이전트 [(pid, 실행 파일, 명령줄)]: 명령줄에 agent.py 가 있는데 설치 폴더
    agent.py 의 절대 경로가 아닌 python. 옛 에이전트_시작.bat 은 'python agent.py' 로(상대 경로) 띄운다."""
    ours = os.path.normcase(os.path.abspath(agent_py))
    return [(pid, exe, cmd) for pid, name, exe, cmd in procs
            if name.lower() in ("python.exe", "pythonw.exe") and AGENT_PY_RE.search(cmd)
            and ours not in os.path.normcase(cmd)]


def rpa_running(procs):
    """도는 RPA exe 이름 (정렬)."""
    wanted = {n.lower(): n for n in RPA_EXES}
    return sorted({wanted[name.lower()] for _, name, _, _ in procs if name.lower() in wanted})


def agent_running(name=None):
    """에이전트 잠금이 있나 (agent.single_instance 가 잡는다). 권한 때문에 못 여는 것도 '있다'."""
    import agent
    return st.lock_held(name or agent.MUTEX_NAME)


# ---------------------------------------------------------------------------
# 자동 시작 작업 (설계 5절)
# ---------------------------------------------------------------------------
def task_xml(user, program_dir):
    """작업 스케줄러 XML. 기본값(3일 제한·배터리면 멈춤·낮은 우선순위)을 믿지 않고 모두 적는다."""
    import background
    py = os.path.join(program_dir, "python", background.SUPERVISOR_EXE)   # 작업 관리자에 AFTER MARKET 으로 보인다
    if not os.path.isfile(py):
        py = os.path.join(program_dir, "python", "pythonw.exe")
    agent_dir = os.path.join(program_dir, "firebase", "agent")
    script = os.path.join(agent_dir, "background.py")
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>AFTER MARKET RPA 에이전트 - 윈도우 로그인 때 창 없이 켠다 (설치 마법사가 등록)</Description></RegistrationInfo>
  <Triggers><LogonTrigger><Enabled>true</Enabled><UserId>{escape(user)}</UserId></LogonTrigger></Triggers>
  <Principals>
    <Principal id="Author"><UserId>{escape(user)}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>HighestAvailable</RunLevel></Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>false</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>5</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec><Command>{escape(py)}</Command><Arguments>"{escape(script)}"</Arguments><WorkingDirectory>{escape(agent_dir)}</WorkingDirectory></Exec>
  </Actions>
</Task>
"""


def register_task(xml_text, folder, run=run_quiet):
    """작업을 등록한다 (같은 이름이면 덮는다). XML 은 folder 에 잠깐 썼다 지운다. 안 되면 RuntimeError."""
    path = os.path.join(folder, "agent_task.xml")
    with open(path, "w", encoding="utf-16") as f:
        f.write(xml_text)
    try:
        code, out = run(["schtasks", "/Create", "/TN", TASK_NAME, "/XML", path, "/F"])
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    if code != 0:
        raise RuntimeError(f"자동 시작 작업을 등록하지 못했습니다: {out.strip()[-300:]}")


def start_task(run=run_quiet):
    code, out = run(["schtasks", "/Run", "/TN", TASK_NAME])
    if code != 0:
        raise RuntimeError(f"에이전트를 켜지 못했습니다: {out.strip()[-300:]}")


def end_task(run=run_quiet):
    """작업을 끝낸다 - 감독이 죽으면 잡이 에이전트도 끝낸다. 작업이 없거나 안 돌고 있어도 괜찮다."""
    run(["schtasks", "/End", "/TN", TASK_NAME])


def delete_task(run=run_quiet):
    run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])


def wait_released(running, wait=STOP_WAIT_SEC, sleep=time.sleep):
    """에이전트 잠금이 풀릴 때까지 기다린다. 풀렸으면 True."""
    until = time.monotonic() + wait
    while running():
        if time.monotonic() >= until:
            return False
        sleep(0.5)
    return True


def stop_agent(procs=None, run=run_quiet, running=None, wait=STOP_WAIT_SEC, sleep=time.sleep):
    """--stop (설치 파일이 판을 올리거나 지우기 전에 부른다). RPA 가 돌면 5 - 도는 exe 는 덮어쓸 수 없다.
    작업을 끝내고 잠금이 풀리면 0, 안 풀리면 6 (작업 밖에서 띄운 에이전트 창)."""
    procs = list_processes() if procs is None else procs
    if rpa_running(procs):
        return EXIT_RPA_RUNNING
    end_task(run)
    return 0 if wait_released(running or agent_running, wait, sleep) else EXIT_STOP_FAILED


def restart_agent(run=run_quiet, running=None, wait=STOP_WAIT_SEC, sleep=time.sleep):
    """에이전트를 켠다. 먼저 작업을 끝낸다 - 에이전트가 꺼져 있어도 감독이 다시 켜기를 기다리는 중(최대 300초)이면
    작업이 돌고 있는 것이라 /Run 이 무시되기 때문이다 (IgnoreNew). 돌던 에이전트는 잠금이 풀린 뒤 켠다
    (도는 RPA 는 잡에서 빠져 있어 끝까지 간다)."""
    running = running or agent_running
    end_task(run)
    if not wait_released(running, wait, sleep):
        raise RuntimeError("에이전트가 멈추지 않습니다. 에이전트 창(에이전트_시작.bat)이 열려 있으면 닫고 다시 저장하세요")
    start_task(run)


def check_rpa(procs=None):
    """--check-rpa (지우기 시작 때): RPA 가 돌면 5, 아니면 0. 아무것도 멈추지 않는다 - 사람이 제거를 그만두면
    에이전트가 꺼진 채 남지 않게, 멈추기는 파일을 지우기 직전(--remove-task)에 한다."""
    return EXIT_RPA_RUNNING if rpa_running(list_processes() if procs is None else procs) else 0


# ---------------------------------------------------------------------------
# 설정 읽기·확인·합치기·저장 (설계 4절 '칸'·'저장')
# ---------------------------------------------------------------------------
def read_agent_raw(path):
    """agent_config.json 을 비밀번호를 풀지 않고 읽는다. 없거나 깨졌으면 {}."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def pw_state(value, unseal):
    """저장된 비밀번호 칸: 'none' 없음 / 'ok' 풀림 / 'bad' 못 풂 (다른 PC·계정에서 잠근 값)."""
    if not value:
        return "none"
    try:
        unseal(value)
        return "ok"
    except Exception:
        return "bad"


def _section(data, name):
    value = data.get(name)
    return value if isinstance(value, dict) else {}


def load_state(paths):
    """창에 채울 값과 비밀번호 칸 상태 (form, state). form 의 비밀번호 칸은 늘 비어 있다.
    state: agent_pw·erp_pw 는 'none'|'ok'|'bad'(에이전트 계정은 'refused' 도), saved 는 저장된 (cid, pc_id)."""
    import secret
    raw = read_agent_raw(paths["agent_config"])
    path = paths["user_config"] if os.path.isfile(paths["user_config"]) else paths["template"]
    data = st.read_user_config(path) if os.path.isfile(path) else {}
    login, erpia, logistic = _section(data, st.LOGIN_SECTION), _section(data, st.ERPIA_SECTION), _section(data, LOGISTIC_SECTION)
    exe = st._erpia_file(erpia.get("ExePath")) or next(
        (found for found in (st._erpia_file(d) for d in st._erpia_install_dirs()) if found), "")
    auto = str(logistic.get(AUTO_MODE_KEY) or "").strip().upper() in ("A", "Y")   # run_routine.resolve_auto_mode 와 같은 규칙
    form = {k: "" for k in FORM_KEYS}
    form.update(cid=str(raw.get("cid") or ""), pc_id=str(raw.get("pc_id") or ""),
                admin_code=str(login.get("AdminCode") or ""), erp_id=str(login.get("ID") or ""),
                erpia_path=exe.replace("\\", "/"), print_mode=PRINT_AUTO if auto else PRINT_MANUAL,
                **{k: str(logistic.get(v) or "") for k, v in LOGISTIC_KEYS.items()})
    stopped = read_stop(paths.get("stop_file"))
    agent_state = pw_state(raw.get("password_dpapi"), secret.unprotect)
    if stopped and stopped.get("code") == 3 and agent_state == "ok":
        agent_state = "refused"          # 저장된 값은 풀리지만 Firebase 가 거부했다 - 새 비밀번호가 있어야 다시 켤 수 있다
    state = {"agent_pw": agent_state,
             "erp_pw": pw_state(login.get("PW"), st.unseal),
             "saved": (raw.get("cid"), raw.get("pc_id")),
             "stopped": stopped, "erpia_missing": not exe}
    return form, state


def read_stop(path):
    """감독이 남긴 '다시 켜지 않고 멈춘 까닭' {code, reason, at} (background.STOP_NAME). 없거나 깨졌으면 None."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) and "code" in data else None
    except (OSError, TypeError, ValueError):
        return None


def needs_agent_login(form, state):
    """에이전트 계정 로그인을 다시 해야 하나: 비밀번호를 넣었거나, 코드가 바뀌었거나, 저장된 비밀번호가 없거나 안 풀린다."""
    return (bool(form["agent_pw"]) or state["agent_pw"] != "ok"
            or (form["cid"], form["pc_id"]) != tuple(state["saved"]))


def validate(form, state):
    """칸 확인 (설계 4절 표). 사람에게 보일 문장 목록 - 비면 통과."""
    out = []
    for key, label in (("cid", "업체코드"), ("pc_id", "PC코드")):
        if not form[key]:
            out.append(f"{label}를 넣으세요")
        elif not KEY_RE.fullmatch(form[key]):
            out.append(f"{label}는 영어 소문자·숫자·밑줄(_)만 쓸 수 있습니다")
    if needs_agent_login(form, state) and not form["agent_pw"]:
        why = {"none": "처음 설정이라", "bad": "저장된 비밀번호를 이 PC 에서 풀 수 없어",
               "refused": "에이전트가 로그인을 거부당해 멈춰서"}.get(state["agent_pw"], "업체코드나 PC코드를 바꿔서")
        out.append(f"{why} 에이전트 계정 비밀번호를 넣어야 합니다")
    if not form["admin_code"]:
        out.append("ERPia 업체코드를 넣으세요")
    if not form["erp_id"]:
        out.append("ERPia 아이디를 넣으세요")
    if not form["erp_pw"] and state["erp_pw"] != "ok":
        out.append("ERPia 비밀번호를 넣으세요" + (" (저장된 값을 이 PC 에서 풀 수 없습니다)" if state["erp_pw"] == "bad" else ""))
    if form["erpia_path"] and not st._erpia_file(form["erpia_path"]):
        out.append(f"ERPia 설치 위치에 {st.ERPIA_EXE_NAME} 가 없습니다. [찾기] 로 고르거나 비워 두세요")
    return out


def merge_user_config(base, form):
    """칸 값을 사용자 설정({섹션: {키: 값}})에 넣은 사본. 비밀번호·ERPia 위치 칸이 비었으면 저장된 값을 그대로 둔다.
    다른 섹션·키·주석은 건드리지 않는다 - Sites(메일 등)는 다른 프로그램이 맡는다 (2026-09-30). 비밀번호 잠그기는
    write_user_config 가 한다."""
    data = json.loads(json.dumps(base, ensure_ascii=False))
    login = data[st.LOGIN_SECTION] = _section(data, st.LOGIN_SECTION)
    login["AdminCode"], login["ID"] = form["admin_code"], form["erp_id"]
    if form["erp_pw"]:
        login["PW"] = form["erp_pw"]
    exe = st._erpia_file(form["erpia_path"]) if form["erpia_path"] else None
    if exe:
        data[st.ERPIA_SECTION] = dict(_section(data, st.ERPIA_SECTION), ExePath=exe.replace("\\", "/"))
    logistic = dict(_section(data, LOGISTIC_SECTION), **{v: form[k] for k, v in LOGISTIC_KEYS.items()})
    logistic[AUTO_MODE_KEY] = PRINT_MODES.get(form["print_mode"], "N")
    data[LOGISTIC_SECTION] = logistic
    return data


def agent_login(path, cid, pc_id, password):
    """에이전트 계정으로 실제 로그인해 보고 agent_config.json 을 쓴다 (agent.first_run). 안 되면 ValueError(사람 문장)."""
    import urllib.request
    import agent
    import fb
    # urllib 은 처음 만든 연결 도구에 그때의 인증서 목록을 담아 두고 다시 안 읽는다 (3.12+). 인터넷이 없어 한 번 실패한 뒤
    # warm_roots 가 인증서를 받아 와도 옛 목록으로 계속 실패하지 않게 로그인할 때마다 새로 만든다 (2026-09-29 검토)
    urllib.request.install_opener(urllib.request.build_opener())
    try:
        agent.first_run(path, cid, pc_id, password)
    except fb.AuthError as e:
        raise ValueError(f"에이전트 계정 로그인이 안 됩니다: {agent.auth_message(e.code)}") from None
    except ValueError as e:
        raise ValueError(f"에이전트 계정 로그인이 안 됩니다: {e}") from None
    except OSError as e:
        if isinstance(getattr(e, "reason", e), ssl.SSLCertVerificationError):
            raise ValueError("Firebase 의 보안 인증서를 확인하지 못했습니다. 인터넷 연결과 이 PC 의 날짜·시간이 맞는지 보고 "
                             "다시 저장하세요 (CERTIFICATE_VERIFY_FAILED)") from None
        raise ValueError(f"인터넷에 연결하지 못해 에이전트 계정을 확인하지 못했습니다 ({type(e).__name__}). "
                         "연결을 확인하고 다시 저장하세요") from None


def warm_roots():
    """파이썬이 Firebase 에 처음 붙기 전에 윈도우가 루트 인증서를 받아 두게 한다 (background.warm_windows_roots 설명).
    갓 설치한 윈도우에서 이게 없으면 로그인 확인이 CERTIFICATE_VERIFY_FAILED 로 실패한다 (2026-09-29 샌드박스)."""
    import background
    background.warm_windows_roots()


def save(form, paths, login=agent_login, run=run_quiet, running=None, user=None):
    """저장 (설계 4절 '저장' 1~5). 한 일 문장 목록. 칸이 틀리거나 로그인이 안 되면 ValueError, 빈 틀이 없거나
    작업 등록·켜기가 안 되면 RuntimeError (둘 다 사람에게 보일 문장). 로그인이 안 되면 아무 파일도 쓰지 않는다."""
    _, state = load_state(paths)
    problems = validate(form, state)
    if problems:
        raise ValueError("\n".join(problems))
    base_path = paths["user_config"] if os.path.isfile(paths["user_config"]) else paths["template"]
    if not os.path.isfile(base_path):
        raise RuntimeError(f"빈 틀({TEMPLATE_NAME})이 없습니다. 설치 파일로 다시 설치하세요")
    done = []
    relogin = needs_agent_login(form, state)
    if relogin:
        warm_roots()
        login(paths["agent_config"], form["cid"], form["pc_id"], form["agent_pw"])
        done.append("에이전트 계정 로그인을 확인했습니다.")
    merged = merge_user_config(st.read_user_config(base_path), form)
    st.write_user_config(merged, paths["user_config"])
    done.append("설정을 저장했습니다.")
    if not st._erpia_file(_section(merged, st.ERPIA_SECTION).get("ExePath")):
        done.append("ERPia 는 아직 못 찾았습니다 - ERPia 를 설치한 뒤 'RPA 설정' 에서 위치를 고르세요.")
    register_task(task_xml(user or process_user(), paths["program_dir"]), paths["config_dir"], run)
    running = running or agent_running
    if relogin or not running():
        try:
            os.remove(paths.get("stop_file") or "")      # 새로 켜니 앞선 멈춤의 까닭은 옛말 (감독도 켤 때 지운다)
        except OSError:
            pass
        restart_agent(run, running)
        done.append("에이전트를 켰습니다.")
    return done


def configured(paths):
    """두 설정 파일이 다 있고 읽히나 - 에이전트 계정 비밀번호까지 풀려야 한다 (판을 올린 설치면 참)."""
    import secret
    if not os.path.isfile(paths["user_config"]):
        return False
    try:
        secret.load_config(paths["agent_config"])
        st.read_user_config(paths["user_config"])
        return True
    except Exception:
        return False


def finish_upgrade(paths, run=run_quiet, running=None, user=None):
    """판 올림 (--after-install 인데 설정이 이미 있다): 창 없이 작업을 다시 등록하고 에이전트를 켠다."""
    register_task(task_xml(user or process_user(), paths["program_dir"]), paths["config_dir"], run)
    restart_agent(run, running)


# ---------------------------------------------------------------------------
# 옛 배포 폴더에서 가져오기 (설계 4절)
# ---------------------------------------------------------------------------
def find_old_files(folder):
    """옛 배포 폴더의 설정 파일 [RPA_UserConfig.json, firebase\\agent\\agent_config.json] 중 있는 것."""
    return [p for p in (os.path.join(folder, st.USER_CONFIG_NAME),
                        os.path.join(folder, "firebase", "agent", AGENT_CONFIG_NAME)) if os.path.isfile(p)]


def import_old(folder, config_dir, overwrite=False):
    """옛 폴더의 설정 파일을 config_dir 로 복사한다. 복사한 이름 목록. 둘 다 없으면 FileNotFoundError,
    config_dir 에 이미 있는데 overwrite 가 아니면 FileExistsError(겹치는 이름)."""
    found = find_old_files(folder)
    if not found or not os.path.isfile(os.path.join(folder, "Run_All.bat")):
        # Run_All.bat 이 없으면 옛 배포 폴더가 아니다 (바탕화면·문서 폴더에 설정 사본만 있는 곳) - 가져오지도, 이름을
        # 바꾸자고도 하지 않는다 (2026-09-29 검토)
        raise FileNotFoundError(folder)
    pairs = [(src, os.path.join(config_dir, os.path.basename(src))) for src in found]
    clash = [os.path.basename(dst) for _, dst in pairs if os.path.exists(dst)]
    if clash and not overwrite:
        raise FileExistsError(", ".join(clash))
    for src, dst in pairs:
        shutil.copyfile(src, dst)          # 내용만 - 권한은 config 폴더 것을 물려받는다
    return [os.path.basename(dst) for _, dst in pairs]


def retire_old_folder(folder):
    """옛 폴더 이름을 <이름>_옮김 (있으면 _옮김2 …) 으로 바꾼다. 새 이름. 안 되면 OSError."""
    base = os.path.normpath(folder) + "_옮김"
    target, n = base, 2
    while os.path.exists(target):
        target, n = f"{base}{n}", n + 1
    os.rename(folder, target)
    return target


def list_printers():
    """이 PC 의 프린터 이름 (로컬과 연결된 네트워크 프린터, 정렬). 못 읽으면 []."""
    class Info4(ctypes.Structure):                      # PRINTER_INFO_4W
        _fields_ = [("pPrinterName", ctypes.c_wchar_p), ("pServerName", ctypes.c_wchar_p),
                    ("Attributes", ctypes.c_uint32)]
    try:
        w = ctypes.WinDLL("winspool.drv")
        w.EnumPrintersW.argtypes = (ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p,
                                    ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32))
        flags = 0x2 | 0x4                                 # PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS
        need, count = ctypes.c_uint32(), ctypes.c_uint32()
        w.EnumPrintersW(flags, None, 4, None, 0, ctypes.byref(need), ctypes.byref(count))
        if not need.value:
            return []
        buf = ctypes.create_string_buffer(need.value)
        if not w.EnumPrintersW(flags, None, 4, buf, need.value, ctypes.byref(need), ctypes.byref(count)):
            return []
        items = ctypes.cast(buf, ctypes.POINTER(Info4))
        return sorted({items[i].pPrinterName for i in range(count.value) if items[i].pPrinterName})
    except Exception:
        return []


# ---------------------------------------------------------------------------
# 창 (tkinter). 칸은 한 줄에 '이름 | 입력 | 안내' - 세로가 짧아야 768 높이 노트북에 들어간다
# ---------------------------------------------------------------------------
ROWS = (
    ("대시보드 연결", (
        ("cid", "업체코드", "", "text"),
        ("pc_id", "PC코드", "", "text"),
        ("agent_pw", "에이전트 계정 비밀번호", "", "password"),
    )),
    ("ERPia 로그인", (
        ("admin_code", "업체코드", "", "text"),      # 대시보드 업체코드와 같은 개념이라 같은 이름 (2026-09-30 사용자)
        ("erp_id", "아이디", "", "text"),
        ("erp_pw", "비밀번호", "", "password"),
        ("erpia_path", "ERPia 설치 위치", "비우면 설치된 곳을 찾아 씁니다", "path"),
    )),
    ("물류 처리 옵션", (
        ("print_mode", "출력 방식", "", "choice"),
        ("carrier", "택배사", "ERPia 에 등록한 이름 그대로", "text"),
        ("box", "박스", "배송정보설정의 박스 그대로", "text"),
        ("fare", "운임", "배송정보설정의 구분 그대로", "text"),
        ("printer", "프린터", "", "printer"),      # 안 골랐으면 DEFAULT_PRINTER, 자동일 때만 켜진다 (sync_printer)
    )),
)
# 셋째 칸(설명)은 칸 안 흐린 안내 - 빈 칸일 때만 보인다. 오른쪽 설명 열을 없애 창 폭을 줄였다 (2026-09-30 사용자)
# 묶음 맨 위 한 줄과 묶음 아래 늘 보이는 주황 한 줄 (2026-09-30 사용자 문구)
LEADS = {"대시보드 연결": "담당자로부터 받은 정보를 입력해주세요."}
NOTES = {"물류 처리 옵션": "※ 실제 ERPia 에 등록한 택배사·박스·운임과 다를 경우\n   물류관리에서 저장할 수 없습니다."}
PW_HINTS = {"none": "", "ok": "저장됨 - 바꿀 때만 입력", "bad": "다시 입력 - 저장값이 안 풀림",
            "refused": "새 비밀번호 입력 - 로그인 거부됨"}   # 빈 칸 안 흐린 안내. 처음('none')은 없음 - 빠지면 저장 때 알린다
ERPIA_MISSING = "ERPia 를 못 찾음 - [찾기]"
DEFAULT_PRINTER = "(기본 프린터)"                 # 프린터 목록 맨 위. 저장은 빈 값 = 윈도우 기본 프린터
MISSING_PRINTER = "이 PC 에 없는 프린터입니다 - 다시 고르세요"
WRAP_STATUS, WRAP_MSG = "230p", "330p"            # 긴 글이 창을 넓히지 않게 줄바꿈 (포인트라 화면 배율을 따른다)
GRAY, RED, GREEN, AMBER, PLACEHOLDER = "#6b7280", "#dc2626", "#15803d", "#b45309", "#9ca3af"


def dpi_aware():
    """고해상도 화면에서 창이 흐릿하지 않게 한다 (Tk 를 만들기 전에)."""
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(1)
    except Exception:
        pass


def new_root():
    """Tk 뿌리 창을 AFTER MARKET 아이콘으로 만든다. 앱 ID 는 창보다 먼저 정해야 한다 - 없으면 작업 표시줄이
    pythonw.exe 의 파이썬 아이콘으로 묶는다. 아이콘 파일이 없어도 창은 뜬다."""
    import tkinter as tk
    dpi_aware()
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass
    root = tk.Tk()
    icon = os.path.join(HERE, ICON_NAME)
    if os.path.isfile(icon):
        root.iconbitmap(icon)                       # 이 창 (default 만 주면 이 창은 깃털 그대로 - 2026-09-30 실측)
        root.iconbitmap(default=icon)               # 뒤에 뜨는 알림 창
    return root


class Dialogs:
    """알림·고르기 창. 시험은 같은 이름의 가짜로 바꾼다."""

    def __init__(self, parent):
        from tkinter import filedialog, messagebox
        self._m, self._f, self._p = messagebox, filedialog, parent

    def info(self, text):
        self._m.showinfo("RPA 설정", text, parent=self._p)

    def error(self, text):
        self._m.showerror("RPA 설정", text, parent=self._p)

    def yesno(self, text):
        return self._m.askyesno("RPA 설정", text, parent=self._p)

    def retry(self, text):
        return self._m.askretrycancel("RPA 설정", text, parent=self._p)

    def folder(self, title):
        return self._f.askdirectory(title=title, mustexist=True, parent=self._p)

    def exe(self, start):
        return self._f.askopenfilename(title=f"ERPia 프로그램({st.ERPIA_EXE_NAME})을 고르세요", initialdir=start,
                                       filetypes=[("ERPia 프로그램", st.ERPIA_EXE_NAME)], parent=self._p)


class SettingsWindow:
    """설정 창 (설계 4절). 시험은 login·run·running·procs·printers·dialogs 를 가짜로 넣는다."""

    def __init__(self, root, paths, after_install=False, login=agent_login, run=run_quiet, running=None,
                 procs=list_processes, printers=None, dialogs=None):
        import tkinter as tk
        from tkinter import font, ttk
        self.root, self.paths, self.after_install = root, paths, after_install
        self.login, self.run, self.running, self.procs = login, run, running or agent_running, procs
        self.dialogs = dialogs or Dialogs(root)
        self.saved, self.imported_from, self.busy_now, self._result = False, None, False, None
        self.printers = list_printers() if printers is None else list(printers)
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont"):
            font.nametofont(name).configure(family="Malgun Gothic", size=10)
        root.title("AFTER MARKET RPA 설정")
        root.resizable(False, False)
        self.vars = {k: tk.StringVar(master=root) for k in FORM_KEYS}
        self.status, self.msg = tk.StringVar(master=root), tk.StringVar(master=root)
        self.entries, self.hints, self.printer_missing = {}, {}, False
        frame = ttk.Frame(root, padding=14)
        frame.grid(sticky="nsew")
        top = ttk.Frame(frame)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.status_label = ttk.Label(top, textvariable=self.status, wraplength=WRAP_STATUS)
        self.status_label.pack(side="left")
        self.import_btn = ttk.Button(top, text="기존 설정값 가져오기", command=self.on_import)
        self.import_btn.pack(side="right")
        for n, (title, fields) in enumerate(ROWS):
            box = ttk.LabelFrame(frame, text=title, padding=(10, 2, 10, 4))
            box.grid(row=1 + n, column=0, sticky="ew", pady=3)
            first = 0
            if title in LEADS:
                ttk.Label(box, text=LEADS[title], foreground=GRAY).grid(row=0, column=0, columnspan=3, sticky="w",
                                                                        pady=(0, 2))
                first = 1
            for i, (key, label, hint, kind) in enumerate(fields, start=first):
                ttk.Label(box, text=label, width=21).grid(row=i, column=0, sticky="w", pady=2)   # '에이전트 계정 비밀번호' 가 들어가게 (18 이면 잘린다)
                if kind in ("printer", "choice"):
                    w = ttk.Combobox(box, textvariable=self.vars[key], width=31, state="readonly",
                                     values=list(PRINT_MODES) if kind == "choice" else ())
                else:
                    w = ttk.Entry(box, textvariable=self.vars[key], width=33, show="•" if kind == "password" else "")
                    # 흐린 안내: 칸 위에 얹은 글씨라 칸 값은 빈 채로 있다 (저장되지 않는다). 칸에 들어가면 숨는다 - 커서를 가리지 않게
                    ph = tk.Label(box, text=hint, fg=PLACEHOLDER, bg="SystemWindow", bd=0, padx=0, pady=0, cursor="xterm")
                    ph.bind("<Button-1>", lambda _e, entry=w: entry.focus_set())
                    for event in ("<FocusIn>", "<FocusOut>"):
                        w.bind(event, lambda _e, k=key: self.sync_hint(k), add="+")
                    self.vars[key].trace_add("write", lambda *_, k=key: self.sync_hint(k))
                    self.hints[key] = (ph, hint)
                w.grid(row=i, column=1, sticky="w", pady=2)
                self.entries[key] = w
                if kind == "path":
                    ttk.Button(box, text="찾기", width=5, command=self.on_browse).grid(row=i, column=2, padx=(4, 0))
            row = first + len(fields)
            if "printer" in (f[0] for f in fields):     # 없는 프린터는 프린터 줄 바로 아래 주황 한 줄 (자동일 때만)
                self.printer_warn = ttk.Label(box, text=MISSING_PRINTER, foreground=AMBER)
                self.printer_warn.grid(row=row, column=0, columnspan=3, sticky="w")
                self.printer_warn.grid_remove()
                row += 1
            if title in NOTES:
                ttk.Label(box, text=NOTES[title], foreground=AMBER, justify="left").grid(row=row, column=0, columnspan=3,
                                                                                         sticky="w", pady=(2, 0))
        self.vars["print_mode"].trace_add("write", self.sync_printer)
        self.msg_label = tk.Label(frame, textvariable=self.msg, fg=RED, wraplength=WRAP_MSG, justify="left", anchor="w")
        self.msg_label.grid(row=1 + len(ROWS), column=0, sticky="ew", pady=(6, 0))
        bottom = ttk.Frame(frame)
        bottom.grid(row=2 + len(ROWS), column=0, sticky="e", pady=(4, 0))
        self.close_btn = ttk.Button(bottom, text="닫기", command=self.on_close)
        self.close_btn.pack(side="right")
        self.save_btn = ttk.Button(bottom, text="저장", command=self.on_save)
        self.save_btn.pack(side="right", padx=(0, 6))
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.report_callback_exception = self._callback_error
        self.reload()

    def _callback_error(self, exc_type, exc, tb):
        """단추 처리 중 뜻밖의 오류: 창은 두고 빨간 글씨로 알리고 기록한다 (Tk 기본은 보이지 않는 stderr 로 찍는다)."""
        path = crash_log(exc)
        if self.busy_now:
            self.busy(False)
        self.say(f"뜻밖의 문제가 생겼습니다 ({exc_type.__name__}: {exc}). 자세한 내용: {path or '(기록하지 못함)'}")

    # --- 채우기 -----------------------------------------------------------
    def reload(self):
        """파일에서 칸을 다시 채운다 (처음, 가져오기·저장 뒤). 비밀번호 칸은 비운다."""
        form, self.state = load_state(self.paths)
        for k in FORM_KEYS:
            self.vars[k].set(form[k])
        for key, (_, hint) in self.hints.items():
            self.set_hint(key, hint)
        for key in PASSWORD_KEYS:
            self.set_hint(key, PW_HINTS[self.state[key]], AMBER if self.state[key] in ("bad", "refused") else PLACEHOLDER)
        if self.state["erpia_missing"]:
            self.set_hint("erpia_path", ERPIA_MISSING, AMBER)
        self.printer_missing = bool(form["printer"]) and form["printer"] not in self.printers
        self.entries["printer"].configure(
            values=[DEFAULT_PRINTER] + self.printers + ([form["printer"]] if self.printer_missing else []))
        self.vars["printer"].set(form["printer"] or DEFAULT_PRINTER)
        self.sync_printer()
        self.set_status()

    def set_hint(self, key, text, color=PLACEHOLDER):
        self.hints[key][0].configure(text=text, fg=color)
        self.sync_hint(key)

    def sync_hint(self, key):
        """흐린 안내는 칸이 비었고 그 칸에 들어가 있지 않을 때만 보인다."""
        label, entry = self.hints[key][0], self.entries[key]
        try:
            inside = self.root.focus_get() is entry
        except KeyError:                    # 콤보 목록이 열려 있는 순간 등 - 칸 안이 아니다
            inside = False
        if label.cget("text") and not self.vars[key].get() and not inside:
            label.place(in_=entry, x=5, rely=0.5, anchor="w")
        else:
            label.place_forget()

    def sync_printer(self, *_):
        """프린터는 출력 방식이 자동일 때만 고른다 - 수동은 엑셀 파일이라 안 쓴다 (2026-09-30). 없는 프린터 주황 줄도
        자동일 때만. 값은 지우지 않는다 (자동으로 돌아오면 그대로)."""
        auto = self.vars["print_mode"].get() == PRINT_AUTO
        self.entries["printer"].configure(state="readonly" if auto else "disabled")
        if auto and self.printer_missing:
            self.printer_warn.grid()
        else:
            self.printer_warn.grid_remove()

    def set_status(self, starting=False):
        """맨 위 줄: 버전과 에이전트 상태. 감독이 까닭을 남기고 멈췄으면 그 까닭을 노란 글씨로 (2026-09-29 검토)."""
        version = st.check_install(self.paths["program_dir"]).get("version") or "없음"
        stopped = self.state.get("stopped")
        if starting:
            text, color = "켜는 중 (1분쯤 걸립니다)", GRAY
        elif self.running():
            text, color = "돌고 있음", ""
        elif stopped:
            text, color = f"멈춤 - {stopped.get('reason') or stopped.get('code')}", AMBER
        else:
            text, color = "꺼져 있음", ""
        self.status.set(f"버전 {version}   ·   에이전트: {text}")
        self.status_label.configure(foreground=color)

    def say(self, text, color=RED):
        self.msg_label.configure(fg=color)
        self.msg.set(text)

    def busy(self, on):
        self.busy_now = on
        for b in (self.save_btn, self.close_btn, self.import_btn):
            b.state(["disabled"] if on else ["!disabled"])
        if on:
            self.say("확인하는 중입니다… (에이전트 계정 로그인·자동 시작 등록)", GRAY)

    def form(self):
        out = {k: self.vars[k].get() for k in FORM_KEYS}
        if out["printer"] == DEFAULT_PRINTER:
            out["printer"] = ""                 # 보이는 글자일 뿐 - 빈 값이 윈도우 기본 프린터다
        return {k: (v if k in PASSWORD_KEYS else v.strip()) for k, v in out.items()}

    # --- 옛 에이전트 ------------------------------------------------------
    def startup(self):
        """창이 뜬 직후: 옛 에이전트가 돌면 닫게 하고, 그만두면 창을 닫는다."""
        if not self.check_old_agents():
            self.root.destroy()

    def check_old_agents(self):
        """옛 에이전트가 돌면 닫으라고 한다. 다 닫혔으면 True, 사용자가 그만두면 False."""
        while True:
            try:
                olds = old_agents(self.procs(), self.paths["agent_py"])
            except Exception:
                return True                        # 프로세스를 못 읽으면 막지 않는다
            if not olds:
                return True
            lines = "\n".join(f"    {exe or '?'}" for _, exe, _ in olds[:5])
            if not self.dialogs.retry("옛 에이전트가 켜져 있습니다. 그 창(ERPia RPA 클라우드 에이전트)을 닫은 뒤 "
                                      f"[다시 시도] 를 누르세요.\n\n{lines}\n\n"
                                      "같이 켜 두면 에이전트 둘이 같은 PC 로 돌아 자동 실행이 두 번 될 수 있습니다."):
                return False

    # --- 단추 -------------------------------------------------------------
    def on_browse(self):
        cur = self.vars["erpia_path"].get()
        start = os.path.dirname(cur) if cur else (os.environ.get("ProgramFiles(x86)") or "C:\\")
        path = self.dialogs.exe(start)
        if not path:
            return
        found = st._erpia_file(path)
        if found:
            self.vars["erpia_path"].set(found.replace("\\", "/"))
            self.say("")
        else:
            self.say(f"{st.ERPIA_EXE_NAME} 가 아닙니다. ERPia 설치 폴더의 {st.ERPIA_EXE_NAME} 를 고르세요")

    def on_save(self):
        if self.busy_now or not self.check_old_agents():
            return
        form = self.form()
        self.busy(True)
        self._result = None
        threading.Thread(target=self._save_worker, args=(form,), daemon=True).start()
        self.root.after(100, self._poll)

    def _save_worker(self, form):
        """저장은 로그인(인터넷)·작업 등록이 있어 따로 돌린다 - 창이 굳지 않게. 창은 _poll 이 만진다."""
        try:
            self._result = ("ok", save(form, self.paths, login=self.login, run=self.run, running=self.running))
        except (ValueError, RuntimeError) as e:
            self._result = ("error", str(e))
        except Exception as e:
            self._result = ("error", f"저장하지 못했습니다 ({type(e).__name__}: {e})")

    def _poll(self):
        if self._result is None:
            self.root.after(100, self._poll)
            return
        kind, value = self._result
        self.busy(False)
        if kind == "error":
            self.say(value)
            return
        self.saved = True
        self.reload()
        if "에이전트를 켰습니다." in value:
            self.set_status(starting=True)       # 감독이 인증서를 채우고 잠금을 잡기까지 '꺼져 있음' 으로 보이지 않게
        self.say(" ".join(value), GREEN)
        self.after_saved()

    def after_saved(self):
        if self.imported_from:
            folder, self.imported_from = self.imported_from, None
            if self.dialogs.yesno(f"옛 에이전트가 다시 켜지지 않게 옛 폴더 이름을 바꿀까요?\n\n{folder}\n→ {folder}_옮김\n\n"
                                  "파일은 그대로 남습니다. 옛 바로 가기로 옛 에이전트를 켜면 에이전트 둘이 같이 돌아 "
                                  "자동 실행이 두 번 될 수 있습니다."):
                try:
                    self.dialogs.info(f"이름을 바꿨습니다: {retire_old_folder(folder)}")
                except OSError as e:
                    self.dialogs.error(f"이름을 바꾸지 못했습니다 ({e.strerror or e}). 옛 에이전트 창이 열려 있지 않은지 "
                                       "보고 직접 바꾸거나 지우세요")
        if self.after_install:
            self.dialogs.info("설정을 마쳤습니다. 에이전트는 윈도우에 로그인할 때마다 창 없이 켜집니다.\n"
                              "설정을 바꿀 때는 시작 메뉴의 'RPA 설정' 을 여세요.")
            self.root.destroy()

    def on_import(self):
        folder = self.dialogs.folder("옛 배포 폴더(Run_All.bat 이 있는 폴더)를 고르세요")
        if not folder:
            return
        folder = os.path.normpath(folder)
        try:
            try:
                names = import_old(folder, self.paths["config_dir"])
            except FileExistsError as e:
                if not self.dialogs.yesno(f"지금 설정({e})을 옛 폴더의 것으로 바꿀까요?"):
                    return
                names = import_old(folder, self.paths["config_dir"], overwrite=True)
        except FileNotFoundError:
            self.say("그 폴더에서 설정 파일(RPA_UserConfig.json, firebase\\agent\\agent_config.json)을 찾지 못했습니다. "
                     "옛 배포 폴더(Run_All.bat 이 있는 폴더)를 고르세요")
            return
        except OSError as e:
            self.say(f"가져오지 못했습니다 ({e.strerror or e})")
            return
        self.imported_from = folder
        self.reload()
        bad = [label for key, label in (("agent_pw", "에이전트 계정"), ("erp_pw", "ERPia")) if self.state[key] == "bad"]
        self.say(f"가져왔습니다 ({', '.join(names)}). "
                 + (f"다른 PC·계정에서 잠근 비밀번호라 다시 넣어야 합니다: {', '.join(bad)}. " if bad else "")
                 + "확인한 뒤 [저장] 을 누르세요.", GREEN)

    def on_close(self):
        if self.busy_now:
            return                                  # 저장하는 중
        if not self.saved and not configured(self.paths):
            if not self.dialogs.yesno("설정을 마치지 않으면 에이전트가 켜지지 않습니다.\n"
                                      "시작 메뉴의 'RPA 설정' 에서 이어서 할 수 있습니다. 닫을까요?"):
                return
        self.root.destroy()


def run_window(paths, after_install=False):
    """창을 띄우고 닫힐 때까지 돈다. 창이 뜨면 옛 에이전트부터 본다."""
    root = new_root()
    win = SettingsWindow(root, paths, after_install=after_install)
    root.after(200, win.startup)
    root.mainloop()
    return 0


def show_error_box(text):
    from tkinter import messagebox
    root = new_root()
    root.withdraw()
    messagebox.showerror("RPA 설정", text, parent=root)
    root.destroy()


def crash_log(exc):
    """뜻밖의 오류 추적을 기록 폴더에 덧붙인다 (pythonw 라 화면에 찍을 곳이 없다). 쓴 경로, 못 쓰면 None."""
    import traceback
    try:
        path = os.path.join(st.data_dir(), CRASH_LOG_NAME)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\n{''.join(traceback.format_exception(exc))}\n")
        return path
    except Exception:
        return None


def main(argv=None):
    """모드: (없음) 창 / --after-install 설치 마지막 (판 올림이면 창 없이) / --no-window 창을 절대 안 띄움 /
    --stop·--remove-task 설치 파일이 부르는 멈추기 (0·5·6) / --check-rpa 지우기 전 확인만 (0·5). 뜻밖의 오류는 기록하고 (창 모드면) 알림 창으로 알린 뒤 1 -
    pythonw 라 그냥 죽으면 'RPA 설정 을 눌렀는데 아무것도 안 뜬다' 가 된다."""
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        return _main(args)
    except Exception as e:
        path = crash_log(e)
        if not ({"--no-window", "--stop", "--remove-task", "--check-rpa"} & set(args)):
            show_error_box(f"설정 창에 뜻밖의 문제가 생겼습니다 ({type(e).__name__}: {e}).\n"
                           f"자세한 내용: {path or '(기록하지 못함)'}")
        return 1


def _main(args):
    if "--check-rpa" in args:
        return check_rpa()
    if "--stop" in args:
        return stop_agent()
    if "--remove-task" in args:
        try:
            return stop_agent()
        finally:
            delete_task()          # 멈추다 오류가 나도 지운다 - 지워진 프로그램을 가리키는 작업이 남지 않게
    after, quiet = "--after-install" in args, "--no-window" in args
    if not is_admin():
        if not quiet:
            relaunch_as_admin(args)
        return 0
    paths = default_paths()
    problem = start_problem()
    if problem:
        if not quiet:
            show_error_box(problem)
        return 1
    if after and configured(paths):
        try:
            finish_upgrade(paths)
        except RuntimeError as e:
            if not quiet:
                show_error_box(str(e))
            return 1
        return 0
    if quiet:
        return 0
    return run_window(paths, after_install=after)


if __name__ == "__main__":
    sys.exit(main())
