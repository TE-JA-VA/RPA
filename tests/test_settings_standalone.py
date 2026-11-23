# -*- coding: utf-8 -*-
"""스탠드얼론 설정 창의 창 없는 부분 (계획 ③ Task 4) - 라이선스 고르기·관리자 계정·비밀번호 다시 정하기·저장·설치 마무리·
멈추기·열쇠 파일 권한. 일반 버전 동작은 tests/test_settings.py 가 그대로 본다.

    D:/AX/RPA/.venv/Scripts/python.exe tests/test_settings_standalone.py

새 구조 자리는 RPA_PROGRAMDATA 임시 폴더, 로그인·작업 명령·icacls 는 가짜 (권한은 임시 폴더에서 한 번만 진짜로).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = tempfile.mkdtemp(prefix="rpa_settings_sa_")
PD = os.path.join(TMP, "programdata", "AFTER MARKET", "RPA")
os.makedirs(os.path.join(PD, "config"))
os.makedirs(os.path.join(PD, "standalone"))
for _k in ("RPA_USER_CONFIG", "RPA_CRED_FILE", "RPA_AGENT_CONFIG"):
    os.environ.pop(_k, None)
os.environ.update(RPA_PROGRAMDATA=PD, RPA_EDITION="standalone", RPA_MACHINE_GUID="pc-1",
                  RPA_AGENT_QUEUE=os.path.join(TMP, "queue.jsonl"), RPA_AGENT_MUTEX=rf"Local\AFTER_MARKET_RPA_AGENT_SA_SET_{os.getpid()}")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "firebase" / "agent"))
sys.stdout.reconfigure(encoding="utf-8")

import license_check  # noqa: E402
import local_server  # noqa: E402
import local_web  # noqa: E402
import rpa_settings as rs  # noqa: E402
import rpa_status as st  # noqa: E402
import update_sign  # noqa: E402

fails = []
_no = [0]


def check(name, cond, detail=""):
    _no[0] += 1
    print(f"  {_no[0]:2d}. [{'통과' if cond else '실패'}] {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(f"{_no[0]}. {name} {detail}")


lic_secret, lic_public = update_sign.keygen()
license_check.LICENSE_PUBLIC_KEY_HEX = lic_public.hex()
BODY = {"edition": "standalone", "company": "시험상사", "cid": "c1", "pc_id": "pc-1", "issued": "2026-11-24",
        "modules": {}, "features": {}, "limits": {}}


def license_file(path, **kw):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(license_check.sign_body(lic_secret, dict(BODY, **kw)), f, ensure_ascii=False)
    return path


def paths_in(name):
    d = os.path.join(TMP, name)
    cfg, prog, keys = os.path.join(d, "config"), os.path.join(d, "설치 폴더"), os.path.join(d, "standalone")
    for p in (cfg, os.path.join(d, "data"), os.path.join(prog, "firebase", "agent"), keys):
        os.makedirs(p)
    shutil.copyfile(ROOT / "release" / "RPA_UserConfig.template.json", os.path.join(prog, rs.TEMPLATE_NAME))
    return {"program_dir": prog, "config_dir": cfg, "user_config": os.path.join(cfg, st.USER_CONFIG_NAME),
            "agent_config": os.path.join(cfg, rs.AGENT_CONFIG_NAME), "template": os.path.join(prog, rs.TEMPLATE_NAME),
            "agent_py": os.path.join(prog, "firebase", "agent", "agent.py"), "stop_file": os.path.join(d, "data", "에이전트_멈춤.json"),
            "license": os.path.join(d, "license.json"), "accounts": os.path.join(keys, local_web.ACCOUNTS_NAME)}


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, args, timeout=60):
        self.calls.append(list(args))
        return 0, ""

    def verbs(self):
        return [a[1] for a in self.calls]


def form(**kw):
    f = {k: "" for k in rs.FORM_KEYS}
    f.update(admin_code="AM001", erp_id="rpa", erp_pw="Erp-Pw-1234!", print_mode=rs.PRINT_MANUAL)
    f.update(kw)
    return f


try:
    print("=== 0. 일반 버전은 그대로 ===")
    check("rows(False) is ROWS", rs.rows(False) is rs.ROWS)
    check("rows(True) 는 '대시보드 연결' 을 뺀 것", [t for t, _ in rs.rows(True)] == [t for t, _ in rs.ROWS if t != "대시보드 연결"])
    dp = rs.default_paths()
    check("default_paths 에 license·accounts", dp["license"] == license_check.license_path()
          and dp["accounts"] == os.path.join(PD, "standalone", "accounts.json"), str({k: dp.get(k) for k in ("license", "accounts")}))

    print("=== 1. 라이선스 ===")
    p = paths_in("lic")
    s = rs.license_state(p)
    check("없음: ok False·글·PC 번호", s["ok"] is False and s["text"].startswith("라이선스 파일이 없습니다") and s["pc_id"] == "pc-1"
          and s["company"] is None, str(s))
    license_file(p["license"], pc_id="pc-2")
    s = rs.license_state(p)
    check("다른 PC: 이 PC 의 라이선스가 아닙니다", s["ok"] is False and "이 PC 의 라이선스가 아닙니다" in s["text"], str(s))
    license_file(p["license"])
    s = rs.license_state(p)
    check("맞음: 업체·발급일·PC 번호", s == {"ok": True, "text": "", "pc_id": "pc-1", "company": "시험상사", "issued": "2026-11-24"}, str(s))
    os.remove(p["license"])
    src = license_file(os.path.join(TMP, "받은_license.json"))
    rs.install_license(src, p)
    check("install_license: 맞는 파일은 라이선스 자리로 옮겨진다 (원본과 같은 내용)",
          rs.license_state(p)["ok"] and Path(p["license"]).read_bytes() == Path(src).read_bytes())
    before = Path(p["license"]).read_bytes()
    other = license_file(os.path.join(TMP, "남의_license.json"), pc_id="pc-9", company="남의상사")
    try:
        rs.install_license(other, p)
        ok = False
    except license_check.LicenseError as e:
        ok = "이 PC 의 라이선스가 아닙니다" in str(e)
    check("다른 PC 의 파일은 LicenseError 이고 있던 라이선스는 그대로", ok and Path(p["license"]).read_bytes() == before)
    check("임시 파일이 남지 않는다", sorted(os.listdir(os.path.dirname(p["license"]))) == sorted(["config", "data", "설치 폴더", "standalone", "license.json"]),
          str(os.listdir(os.path.dirname(p["license"]))))

    print("=== 2. 관리자 계정 ===")
    check("처음엔 관리자 없음", rs.admin_exists(p) is False)
    for args, why in ((("admin", "Good-Pass-1", "Good-Pass-2"), "비밀번호 다름"), (("admin", "Short7!", "Short7!"), "7자"),
                      (("관 리", "Good-Pass-1", "Good-Pass-1"), "아이디 꼴")):
        try:
            rs.create_admin(p, *args)
            ok = False
        except ValueError as e:
            ok = (why != "비밀번호 다름") or str(e) == "비밀번호가 서로 다릅니다."
        check(f"create_admin: {why} → ValueError", ok)
    uid = rs.create_admin(p, "Admin", "Good-Pass-1", "Good-Pass-1")
    acc = local_web.Accounts(p["accounts"])
    got = acc.verify("admin", "Good-Pass-1")
    check("만든 계정이 맞고 관리자·첫 로그인에 바꾸기", uid == "admin" and got and got["role"] == "admin" and got["must_change"], str(got))
    check("이제 관리자 있음", rs.admin_exists(p) is True)
    try:
        rs.create_admin(p, "admin", "Other-Pass-1", "Other-Pass-1")
        ok = False
    except ValueError:
        ok = acc.verify("admin", "Good-Pass-1") is not None
    check("같은 아이디 두 번은 ValueError (있던 비밀번호는 그대로)", ok)
    acc.add("viewer1", "View-Pass-1", "viewer")
    real_admin = rs.is_admin
    try:
        rs.is_admin = lambda: False
        try:
            rs.reset_admin_password(p, "admin", "New-Pass-11", "New-Pass-11")
            ok = False
        except PermissionError as e:
            ok = str(e) == "윈도우 관리자 권한으로 실행하여 주십시오."
        check("reset_admin_password: 윈도우 관리자 권한이 아니면 PermissionError", ok)
        rs.is_admin = lambda: True
        try:
            rs.reset_admin_password(p, "viewer1", "New-Pass-11", "New-Pass-11")
            ok = False
        except ValueError:
            ok = True
        check("유저 계정은 ValueError", ok)
        try:
            rs.reset_admin_password(p, "admin", "New-Pass-11", "New-Pass-12")
            ok = False
        except ValueError as e:
            ok = str(e) == "비밀번호가 서로 다릅니다."
        check("새 비밀번호 둘이 다르면 ValueError", ok)
        acc.add("admin2", "Adm2-Pass-1", "admin")
        acc.disable("admin", True)
        rs.reset_admin_password(p, "admin", "New-Pass-11", "New-Pass-11")
        got = acc.verify("admin", "New-Pass-11")
        check("다시 정하면 옛 비밀번호 틀림·새 비밀번호 맞음·첫 로그인에 바꾸기·사용 중지였으면 푼다",
              acc.verify("admin", "Good-Pass-1") is None and got and got["must_change"] and not got["disabled"], str(got))
    finally:
        rs.is_admin = real_admin

    print("=== 3. 저장 ===")
    q = paths_in("save")
    rec = Recorder()
    calls = []
    real_warm = rs.warm_roots
    rs.warm_roots = lambda: calls.append("warm")

    def no_login(*a, **k):
        calls.append("login")
        raise AssertionError("스탠드얼론에서 에이전트 로그인을 불렀다")
    try:
        check("validate: 업체코드·PC코드·에이전트 비밀번호를 보지 않는다", rs.validate(form(), {"agent_pw": "none", "erp_pw": "none",
                                                                                     "saved": (None, None)}, standalone=True) == [])
        check("일반 validate 는 그대로 업체코드를 본다", "업체코드를 입력하여 주십시오." in rs.validate(form(), {"agent_pw": "none", "erp_pw": "none",
                                                                                                 "saved": (None, None)}))
        for setup, want in ((lambda: None, "라이선스 파일이 없습니다"),
                            (lambda: license_file(q["license"]), "업체 웹 관리자 계정을 만들어 주십시오.")):
            setup()
            try:
                rs.save(form(), q, login=no_login, run=rec, running=lambda: False, user="PC\\me", standalone=True)
                ok = False
            except ValueError as e:
                ok = want in str(e)
            check(f"저장 거절: {want[:20]}… (파일을 쓰지 않는다)", ok and not os.path.exists(q["user_config"]) and rec.calls == [])
        rs.create_admin(q, "admin", "Good-Pass-1", "Good-Pass-1")
        done = rs.save(form(), q, login=no_login, run=rec, running=lambda: False, user="PC\\me", standalone=True)
        check("라이선스·관리자가 있으면 설정 쓰기 → 작업 등록 → 에이전트 켜기", os.path.isfile(q["user_config"])
              and rec.verbs() == ["/Create", "/End", "/Run"] and "에이전트를 실행하였습니다." in done, f"{rec.verbs()} {done}")
        check("로그인·인증서 채우기를 부르지 않는다", calls == [], str(calls))
        check("agent_config.json 은 쓰지 않는다", not os.path.exists(q["agent_config"]))
    finally:
        rs.warm_roots = real_warm

    print("=== 4. 설치 마무리 (configured) ===")
    r = paths_in("conf")
    check("셋 다 없으면 False", rs.configured(r) is False)
    license_file(r["license"])
    rs.create_admin(r, "admin", "Good-Pass-1", "Good-Pass-1")
    check("설정 파일이 없으면 False", rs.configured(r) is False)
    st.write_user_config(st.read_user_config(r["template"]), r["user_config"])
    check("라이선스·계정·설정이 다 있으면 True (agent_config.json 이 없어도)", rs.configured(r) is True and not os.path.exists(r["agent_config"]))
    with open(r["stop_file"], "w", encoding="utf-8") as f:
        json.dump({"code": 3, "reason": "x"}, f)
    check("멈춤 코드 3 은 보지 않는다", rs.configured(r) is True)
    os.remove(r["license"])
    check("라이선스가 없으면 False", rs.configured(r) is False)
    license_file(r["license"])
    local_web.Accounts(r["accounts"]).add("admin2", "Adm2-Pass-1", "admin")
    local_web.Accounts(r["accounts"]).disable("admin", True)
    local_web.Accounts(r["accounts"]).disable("admin2", False)
    os.remove(r["accounts"])
    check("계정이 없으면 False", rs.configured(r) is False)

    print("=== 5. 멈추기 (--stop) - 남은 로컬 서버 ===")
    prog = r"C:\Program Files\AFTER MARKET\RPA"
    server = (77, "AFTER_MARKET_RPA_Agent.exe", prog + r"\python\AFTER_MARKET_RPA_Agent.exe",
              f'"{prog}\\python\\AFTER_MARKET_RPA_Agent.exe" -E -s -X utf8 "{prog}\\firebase\\agent\\local_server.py"')
    foreign = (88, "python.exe", r"C:\x\python.exe", r"python D:\dev\firebase\agent\local_server.py")
    check("남은 서버 찾기: 설치 폴더의 local_server.py 만", rs.leftover_servers([server, foreign], prog) == [77])
    rec = Recorder()
    lists = [[server, foreign], [foreign]]
    code = rs.stop_agent(procs=[], run=rec, running=lambda: False, sleep=lambda s: None, listing=lambda: lists.pop(0) if lists else [foreign],
                         program_dir=prog)
    check("작업을 끝낸 뒤에도 남은 서버는 끝내고 0", code == 0 and ["taskkill", "/PID", "77", "/F"] in rec.calls, f"{code} {rec.calls}")
    rec = Recorder()
    code = rs.stop_agent(procs=[], run=rec, running=lambda: False, wait=0.3, sleep=lambda s: None, listing=lambda: [server], program_dir=prog)
    check("끝내 남으면 6", code == rs.EXIT_STOP_FAILED, str(code))
    os.environ["RPA_EDITION"] = "cloud"
    rec, listed = Recorder(), []
    code = rs.stop_agent(procs=[], run=rec, running=lambda: False, sleep=lambda s: None, listing=lambda: listed.append(1) or [server],
                         program_dir=prog)
    check("일반 버전은 서버를 찾지 않는다 (지금과 같다)", code == 0 and not listed and rec.verbs() == ["/End"], f"{code} {rec.calls}")
    os.environ["RPA_EDITION"] = "standalone"

    print("=== 6. 열쇠 파일 권한 ===")
    kd = os.path.join(TMP, "keys")
    os.makedirs(kd)
    for n in ("agent.key", "relay.key", "accounts.json"):
        with open(os.path.join(kd, n), "w") as f:
            f.write("x")
    rec = Recorder()
    local_server.lock_key_files(kd, run=lambda args, timeout=60: rec(args) and (0, ""))
    files = [os.path.basename(a[1]) for a in rec.calls]
    check("세 파일 모두에 icacls (따로 붙은 권한 지우기 → 관리자·SYSTEM 만)",
          sorted(set(files)) == ["accounts.json", "agent.key", "relay.key"]
          and all("*S-1-5-32-544:F" in a and "*S-1-5-18:F" in a and "/inheritance:r" in a for a in rec.calls if "/grant:r" in a)
          and any("/reset" in a for a in rec.calls), str(rec.calls))
    check("readers 가 없으면 아무에게도 읽기를 더하지 않는다", not any(x.endswith(":R") for a in rec.calls for x in a))
    rec = Recorder()
    local_server.lock_key_files(kd, readers=("PC\\user1",), run=lambda args, timeout=60: rec(args) and (0, ""))
    with_r = [a for a in rec.calls if any(x.endswith(":R") for x in a)]
    check("readers 가 있으면 relay.key 에만 :R", len(with_r) == 1 and os.path.basename(with_r[0][1]) == "relay.key"
          and "PC\\user1:R" in with_r[0], str(with_r))
    codes = local_server.lock_key_files(kd)
    out = subprocess.run(["icacls", os.path.join(kd, "relay.key")], capture_output=True).stdout.decode("oem", "replace")
    out = out.replace(os.path.join(kd, "relay.key"), "")          # 경로의 C:\Users 는 권한이 아니다
    check("진짜 임시 폴더: icacls 출력에 Users·Everyone 이 없고 관리자·SYSTEM 이 있다",
          all(c == 0 for c in codes) and "Users" not in out and "Everyone" not in out and "BUILTIN\\Administrators" in out
          and "SYSTEM" in out, out)
    check("실패해도 예외를 내지 않는다 (없는 폴더)", isinstance(local_server.lock_key_files(os.path.join(TMP, "없음")), list))
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    subprocess.run(["icacls", os.path.join(TMP, "keys"), "/reset", "/T", "/C", "/Q"], capture_output=True)
    shutil.rmtree(TMP, ignore_errors=True)
print()
print(f"실패: {'없음' if not fails else fails}")
sys.exit(1 if fails else 0)
