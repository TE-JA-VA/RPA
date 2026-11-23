# -*- coding: utf-8 -*-
"""일반 버전과 스탠드얼론 버전의 폴더·이름 나누기 (사용자 2026-11-23 - "아예 일반버전과 스탠드얼론 버전이 있는 폴더를 분리").

    일반      Program Files\\AFTER MARKET\\RPA             ProgramData\\AFTER MARKET\\RPA             작업 AFTER MARKET\\RPA Agent
    스탠드얼론 Program Files\\AFTER MARKET\\RPA Standalone  ProgramData\\AFTER MARKET\\RPA Standalone  작업 AFTER MARKET\\RPA Standalone Agent

일반 버전의 글자는 한 자도 바뀌지 않아야 한다 (이미 깔린 PC 가 그 자리를 쓴다). 진짜 ProgramData 는 만들지도 쓰지도 않는다 -
자리 글자만 본다 (data_dir·local_server.data_dir 처럼 폴더를 만드는 함수는 임시 폴더에서만 부른다).

    D:/AX/RPA/.venv/Scripts/python.exe tests/test_folder_split.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "firebase", "agent")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
for _k in ("RPA_PROGRAMDATA", "RPA_EDITION", "RPA_USER_CONFIG", "RPA_CRED_FILE", "RPA_AGENT_CONFIG", "RPA_AGENT_QUEUE"):
    os.environ.pop(_k, None)
sys.stdout.reconfigure(encoding="utf-8")

import edition  # noqa: E402
import license_check  # noqa: E402
import local_store  # noqa: E402
import rpa_settings as rs  # noqa: E402
import rpa_status as st  # noqa: E402
import rpa_update  # noqa: E402

fails = []
_no = [0]


def check(name, cond, detail=""):
    _no[0] += 1
    print(f"  {_no[0]:2d}. [{'통과' if cond else '실패'}] {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(f"{_no[0]}. {name} {detail}")


PD = os.environ.get("ProgramData") or r"C:\ProgramData"
PF = os.path.normpath(os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles") or r"C:\Program Files")
CLOUD_ROOT = os.path.join(PD, "AFTER MARKET", "RPA")
SA_ROOT = os.path.join(PD, "AFTER MARKET", "RPA Standalone")

print("=== 1. 이름 (일반은 예전 글자 그대로) ===")
check("PRODUCT_DIRS 는 예전 그대로 ('AFTER MARKET', 'RPA')", st.PRODUCT_DIRS == ("AFTER MARKET", "RPA"))
check("스탠드얼론 폴더 이름 ('AFTER MARKET', 'RPA Standalone')", getattr(st, "STANDALONE_DIRS", None) == ("AFTER MARKET", "RPA Standalone"))
check("작업 이름: 일반은 예전 그대로", rs.TASK_NAME == r"AFTER MARKET\RPA Agent" and rs.HELPER_TASK_NAME == r"AFTER MARKET\RPA Update")
check("작업 이름: 스탠드얼론은 따로", getattr(rs, "STANDALONE_TASK_NAME", None) == r"AFTER MARKET\RPA Standalone Agent"
      and getattr(rs, "STANDALONE_HELPER_TASK_NAME", None) == r"AFTER MARKET\RPA Standalone Update")
check("설치 폴더: 일반은 예전 그대로 (INSTALL_DIR)", rs.INSTALL_DIR == os.path.join(PF, "AFTER MARKET", "RPA"), rs.INSTALL_DIR)

print("=== 2. 소스로 돌 때 (RPA_EDITION 으로 가른다) ===")
check("일반: install_root = ProgramData\\AFTER MARKET\\RPA", st.install_root() == CLOUD_ROOT, st.install_root())
check("일반: product_dirs = PRODUCT_DIRS", getattr(st, "product_dirs", lambda: None)() == st.PRODUCT_DIRS)
check("일반: 작업 이름·도우미 이름·설치 폴더", getattr(rs, "task_name", lambda: None)() == rs.TASK_NAME
      and getattr(rs, "helper_task_name", lambda: None)() == rs.HELPER_TASK_NAME
      and getattr(rs, "install_dir", lambda: None)() == rs.INSTALL_DIR)
check("일반: 라이선스·로컬 서버 자료·업데이트 자리도 예전 뿌리", license_check.license_path() == os.path.join(CLOUD_ROOT, "license.json")
      and local_store.keys_dir() == os.path.join(CLOUD_ROOT, "standalone") and rpa_update.path() == os.path.join(CLOUD_ROOT, "update"),
      f"{license_check.license_path()} {local_store.keys_dir()}")
os.environ["RPA_EDITION"] = "standalone"
check("스탠드얼론: install_root = ProgramData\\AFTER MARKET\\RPA Standalone", st.install_root() == SA_ROOT, st.install_root())
check("스탠드얼론: 라이선스·로컬 서버 자료(열쇠·계정·기록)·기록·설정 자리가 새 뿌리 아래",
      license_check.license_path() == os.path.join(SA_ROOT, "license.json") and local_store.keys_dir() == os.path.join(SA_ROOT, "standalone")
      and st.installed_sig_path().startswith(SA_ROOT + os.sep), f"{license_check.license_path()} {local_store.keys_dir()}")
check("스탠드얼론: 작업 이름·도우미 이름·설치 폴더", getattr(rs, "task_name", lambda: None)() == r"AFTER MARKET\RPA Standalone Agent"
      and getattr(rs, "helper_task_name", lambda: None)() == r"AFTER MARKET\RPA Standalone Update"
      and getattr(rs, "install_dir", lambda: None)() == os.path.join(PF, "AFTER MARKET", "RPA Standalone"))
problem = rs.start_problem(here=os.path.join(PF, "AFTER MARKET", "RPA")) if st.new_layout() else None
check("스탠드얼론: 일반 폴더의 설정 창은 '설치 폴더가 아님' (새 구조일 때) - 이 PC 에서는 건너뜀", problem is None or "RPA Standalone" in problem, problem)
tmp = tempfile.mkdtemp(prefix="rpa_split_")
os.environ["RPA_PROGRAMDATA"] = os.path.join(tmp, "pd")
check("RPA_PROGRAMDATA 가 버전 종류보다 앞선다 (시험 자리)", st.install_root() == os.path.join(tmp, "pd"))
os.makedirs(os.path.join(tmp, "pd", "config"))
sa_dir = os.path.join(tmp, "Program Files", "AFTER MARKET", "RPA Standalone")
old = rs.install_dir
rs.install_dir = lambda: sa_dir
try:
    p1 = rs.start_problem(session="", here=os.path.join(tmp, "Program Files", "AFTER MARKET", "RPA"))
    p2 = rs.start_problem(session="", here=sa_dir)
finally:
    rs.install_dir = old
check("설정 창 시작 점검은 install_dir() 로 본다 (스탠드얼론 폴더만 통과)", p1 is not None and sa_dir in p1 and p2 is None, f"{p1} / {p2}")
check("스탠드얼론 안내 글: 시작 메뉴 '오토파일럿 스탠드얼론'", p1 is not None and "오토파일럿 스탠드얼론" in p1, p1)
del os.environ["RPA_PROGRAMDATA"]
os.environ["RPA_EDITION"] = "cloud"
check("RPA_EDITION=cloud 면 예전 뿌리", st.install_root() == CLOUD_ROOT)
del os.environ["RPA_EDITION"]

print("=== 3. 설치본 흉내 (프로그램 폴더의 표시로 가른다 - 환경 변수는 안 따른다) ===")
real_program_dir = st.program_dir


def as_shipped(files, env_edition=None):
    """임시 프로그램 폴더를 설치본처럼 (manifest.json 이 있다) 꾸미고 install_root 를 돌려준다."""
    prog = tempfile.mkdtemp(prefix="rpa_split_prog_")
    with open(os.path.join(prog, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"version": "x", "files": files.get("manifest_files", {})}, f)
    for name, text in files.items():
        if name != "manifest_files":
            with open(os.path.join(prog, name), "w", encoding="utf-8") as f:
                f.write(text)
    st.program_dir = lambda: prog
    if env_edition:
        os.environ["RPA_EDITION"] = env_edition
    os.environ["RPA_PROGRAMDATA"] = os.path.join(prog, "evil")
    try:
        return st.install_root(), rs.task_name() if hasattr(rs, "task_name") else None
    finally:
        st.program_dir = real_program_dir
        os.environ.pop("RPA_EDITION", None)
        os.environ.pop("RPA_PROGRAMDATA", None)
        shutil.rmtree(prog, ignore_errors=True)


got = as_shipped({}, env_edition="standalone")
check("일반 설치본: 예전 뿌리·예전 작업 이름 (RPA_EDITION·RPA_PROGRAMDATA 를 줘도)", got == (CLOUD_ROOT, r"AFTER MARKET\RPA Agent"), got)
got = as_shipped({"edition.json": '{"edition": "standalone"}'}, env_edition="cloud")
check("스탠드얼론 설치본 (edition.json): 새 뿌리·새 작업 이름", got == (SA_ROOT, r"AFTER MARKET\RPA Standalone Agent"), got)
got = as_shipped({"manifest.sig": "00"})
check("edition.json 을 지운 스탠드얼론 설치본 (manifest.sig 만): 그래도 새 뿌리 (fail-closed 와 같은 판정)", got[0] == SA_ROOT, got)
got = as_shipped({"manifest_files": {"edition.json": "ab"}})
check("edition.json 을 지운 스탠드얼론 설치본 (버전 목록에만 있음): 새 뿌리", got[0] == SA_ROOT, got)

print("=== 4. 돌지 않는다 (edition 은 install_root 를 부르지 않는다) ===")


def boom(*a, **k):
    raise AssertionError("install_root 를 불렀다")


real_root = st.install_root
st.install_root = boom
try:
    os.environ["RPA_EDITION"] = "standalone"
    ok = (edition.edition() == "standalone" and edition.install_mismatch() is None and edition.test_build() is False)
    os.environ["RPA_EDITION"] = "cloud"
    ok = ok and edition.edition() == "cloud"
    err = ""
except AssertionError as e:
    ok, err = False, str(e)
finally:
    st.install_root = real_root
    os.environ.pop("RPA_EDITION", None)
check("edition.edition·install_mismatch·test_build 는 install_root 없이 판정한다", ok, err)

print("=== 5. 업데이트 도우미 runner (edition.py 가 없다 - 일반 버전에만 있다) ===")
runner = os.path.join(tmp, "runner")
os.makedirs(runner)
for name in rpa_update.RUNNER_FILES:
    shutil.copy2(os.path.join(ROOT, name), os.path.join(runner, name))
check("runner 에 edition.py 를 싣지 않는다", "edition.py" not in rpa_update.RUNNER_FILES)
env = {k: v for k, v in os.environ.items() if not k.startswith("RPA_")}
r = subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {runner!r}); import rpa_status as st; print(st.install_root())"],
                   cwd=runner, env=env,
                   capture_output=True, text=True, timeout=60)
check("runner 의 rpa_status 는 예전 뿌리 (edition 이 없으면 일반)", r.stdout.strip() == CLOUD_ROOT, (r.stdout + r.stderr)[-300:])
shutil.rmtree(tmp, ignore_errors=True)

print()
print(f"실패: {'없음' if not fails else fails}")
sys.exit(1 if fails else 0)
