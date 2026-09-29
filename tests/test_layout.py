"""배포판 구조 시험 - rpa_status 의 자리 찾기(프로그램·설정·기록)와 판 점검(manifest.json),
exe 쪽 모듈이 그 자리를 쓰는지. 설계: docs/superpowers/specs/2026-09-29-release-layout-design.md

실제 C:\\ProgramData 는 건드리지 않는다. 새 구조는 RPA_PROGRAMDATA 로 임시 폴더를 가리켜 흉내 낸다.

    .venv\\Scripts\\python.exe tests\\test_layout.py
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _k in ("RPA_PROGRAMDATA", "RPA_USER_CONFIG", "RPA_CRED_FILE", "RPA_AGENT_CONFIG", "RPA_AGENT_QUEUE"):
    os.environ.pop(_k, None)
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

import rpa_status as st  # noqa: E402

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


tmp = tempfile.mkdtemp(prefix="rpa_layout_")

# ---------------------------------------------------------------------------
print("=== 1. 옛 구조 (새 자리에 config 폴더가 없다) ===")
empty_root = os.path.join(tmp, "empty_root")
os.environ["RPA_PROGRAMDATA"] = empty_root
check("config 폴더가 없으면 옛 구조", st.new_layout() is False)
check("옛 구조의 설정 자리는 프로그램 폴더", st.config_dir() == st.program_dir())
check("옛 구조의 기록 자리도 프로그램 폴더", st.data_dir() == st.program_dir())
check("옛 구조의 사용자 설정은 지금 자리 그대로",
      st.user_config_path() == os.path.join(st.program_dir(), st.USER_CONFIG_NAME))
check("옛 구조에서는 새 자리 폴더를 만들지 않는다", not os.path.exists(empty_root))

# ---------------------------------------------------------------------------
print("=== 2. 새 구조 (RPA_PROGRAMDATA 에 config 폴더) ===")
new_root = os.path.join(tmp, "AFTER MARKET", "RPA")
os.makedirs(os.path.join(new_root, "config"))
os.environ["RPA_PROGRAMDATA"] = new_root
check("config 폴더가 있으면 새 구조", st.new_layout() is True)
check("새 구조의 설정 자리는 config", st.config_dir() == os.path.join(new_root, "config"))
data = st.data_dir()
check("새 구조의 기록 자리는 data, 없으면 만든다", data == os.path.join(new_root, "data") and os.path.isdir(data))
check("새 구조의 사용자 설정은 config 안",
      st.user_config_path() == os.path.join(new_root, "config", st.USER_CONFIG_NAME))
os.environ["RPA_USER_CONFIG"] = os.path.join(tmp, "x.json")
check("시험용 RPA_USER_CONFIG 가 새 구조보다 앞선다", st.user_config_path() == os.path.join(tmp, "x.json"))
del os.environ["RPA_USER_CONFIG"]

# ---------------------------------------------------------------------------
print("=== 3. 기본 뿌리 ===")
del os.environ["RPA_PROGRAMDATA"]
check("기본 뿌리는 %ProgramData%\\AFTER MARKET\\RPA",
      st.install_root() == os.path.join(os.environ.get("ProgramData") or r"C:\ProgramData", "AFTER MARKET", "RPA"))
check("이 개발 PC 에는 진짜 새 자리가 없다 (있으면 이 PC 가 새 구조로 넘어간다 - 만들지 말 것)", st.new_layout() is False)

# ---------------------------------------------------------------------------
print("=== 4. 프로그램 폴더: 소스·PyInstaller·Nuitka ===")
here = str(ROOT)
expected = os.path.join(here, "dist") if os.path.isfile(os.path.join(here, "dist", "Run_All.bat")) else here
check("소스는 저장소 폴더 (옆 dist 에 Run_All.bat 이 있으면 dist)", st.program_dir() == expected, st.program_dir())
check("소스는 묶인 exe 가 아니다", st.packaged() is False and st.run_kind() == "파이썬 스크립트")

real_exe, had_frozen = sys.executable, hasattr(sys, "frozen")
sys.frozen = True
sys.executable = os.path.join(tmp, "pyi", "ERPia_RPA.exe")
try:
    check("PyInstaller exe 는 exe 옆", st.program_dir() == os.path.join(tmp, "pyi"))
    check("실행 형태 이름 (PyInstaller)", st.packaged() is True and st.run_kind() == "exe(PyInstaller)")
finally:
    sys.executable = real_exe
    if not had_frozen:
        del sys.frozen

st.__compiled__ = types.SimpleNamespace(containing_dir=os.path.join(tmp, "nk"))
try:
    check("Nuitka exe 는 exe 가 놓인 폴더 (__compiled__.containing_dir, 풀린 임시 폴더가 아니다)",
          st.program_dir() == os.path.join(tmp, "nk"))
    check("실행 형태 이름 (Nuitka)", st.packaged() is True and st.run_kind() == "exe(Nuitka)")
finally:
    del st.__compiled__
st.__compiled__ = types.SimpleNamespace()
real_argv0 = sys.argv[0]
sys.argv[0] = os.path.join(tmp, "nk2", "ERPia_RPA.exe")
try:
    check("containing_dir 가 없으면 sys.argv[0] 의 폴더", st.program_dir() == os.path.join(tmp, "nk2"))
finally:
    sys.argv[0] = real_argv0
    del st.__compiled__

# ---------------------------------------------------------------------------
print("=== 5. 기록 폴더를 만들 수 없어도 예외를 내지 않는다 ===")
bad_root = os.path.join(tmp, "bad")
os.makedirs(os.path.join(bad_root, "config"))
open(os.path.join(bad_root, "data"), "w").close()      # data 자리에 파일이 있어 폴더를 못 만든다
os.environ["RPA_PROGRAMDATA"] = bad_root
try:
    got = st.data_dir()
    ok = got == os.path.join(bad_root, "data")
except Exception as e:  # noqa: BLE001
    ok, got = False, repr(e)
check("data 폴더를 못 만들어도 경로만 돌려준다 (기록 때문에 RPA 가 멈추면 안 된다)", ok, str(got))
del os.environ["RPA_PROGRAMDATA"]

# ---------------------------------------------------------------------------
print("=== 6. 판 점검 (manifest.json) ===")
prog = os.path.join(tmp, "prog")
os.makedirs(os.path.join(prog, "firebase", "agent"))
files = {
    "ERPia_RPA.exe": b"exe-1",
    "rpa_status.py": b"print(1)\n",
    "firebase/agent/에이전트_시작.bat": "@echo off\r\n".encode("cp949"),
}
for rel, body in files.items():
    with open(os.path.join(prog, *rel.split("/")), "wb") as f:
        f.write(body)


def write_manifest(entries, version="2026.09.29-1", fmt=1):
    with open(os.path.join(prog, st.MANIFEST_NAME), "w", encoding="utf-8") as f:
        json.dump({"format": fmt, "version": version, "files": entries}, f, ensure_ascii=False)


entries = {rel: st.file_digest(os.path.join(prog, *rel.split("/"))) for rel in files}
check("지문은 SHA-256 과 크기",
      entries["ERPia_RPA.exe"] == {"sha256": hashlib.sha256(b"exe-1").hexdigest(), "size": 5})
r = st.check_install(prog)
check("목록이 없으면 none", r["state"] == "none" and r["version"] is None and r["changed"] == [], str(r))
check("점검 시각을 남긴다", isinstance(r["checked_at"], str) and len(r["checked_at"]) == 19, str(r))
write_manifest(entries)
r = st.check_install(prog)
check("모두 같으면 ok", r["state"] == "ok" and r["version"] == "2026.09.29-1" and r["changed_count"] == 0, str(r))
os.makedirs(os.path.join(prog, "__pycache__"))
open(os.path.join(prog, "__pycache__", "rpa_status.cpython-314.pyc"), "wb").close()
check("목록에 없는 파일(__pycache__)은 무시한다", st.check_install(prog)["state"] == "ok")
with open(os.path.join(prog, "rpa_status.py"), "wb") as f:
    f.write(b"print(2)\n")
r = st.check_install(prog)
check("지문이 다르면 mixed, 그 파일 이름", r["state"] == "mixed" and r["changed"] == ["rpa_status.py"]
      and r["changed_count"] == 1, str(r))
os.remove(os.path.join(prog, "firebase", "agent", "에이전트_시작.bat"))
r = st.check_install(prog)
check("없는 파일도 mixed (한글 이름 그대로)", r["state"] == "mixed" and r["changed_count"] == 2
      and "firebase/agent/에이전트_시작.bat" in r["changed"], str(r))
write_manifest({f"f{i}.txt": {"sha256": "0" * 64, "size": 1} for i in range(15)})
r = st.check_install(prog)
check("다른 파일 이름은 10개까지, 개수는 따로", r["state"] == "mixed" and len(r["changed"]) == 10
      and r["changed_count"] == 15, str(r))
with open(os.path.join(prog, st.MANIFEST_NAME), "w", encoding="utf-8") as f:
    f.write("{깨짐")
r = st.check_install(prog)
check("목록이 깨지면 error (예외를 내보내지 않는다)", r["state"] == "error" and r.get("error"), str(r))
write_manifest(entries, fmt=2)
check("형식 번호가 다르면 error", st.check_install(prog)["state"] == "error")
write_manifest({"x.txt": "문자열"})
check("항목이 dict 가 아니면 error", st.check_install(prog)["state"] == "error")
outside = os.path.join(tmp, "outside.txt")
with open(outside, "w") as f:
    f.write("밖")
for bad in ("../outside.txt", "/abs.txt", "C:/Windows/win.ini", "a/../../outside.txt", "sub\\x.txt", "", "./x.txt"):
    write_manifest({bad: {"sha256": "0" * 64, "size": 1}})
    check(f"밖을 가리키거나 이상한 경로는 error ({bad!r})", st.check_install(prog)["state"] == "error")
check("manifest_path_ok: 안쪽 상대 경로만", st.manifest_path_ok("firebase/agent/agent.py")
      and not st.manifest_path_ok(None) and not st.manifest_path_ok("a//b"))

# ---------------------------------------------------------------------------
print("=== 7. exe 쪽 모듈은 rpa_status 의 기록 자리를 쓴다 ===")
NAMES = ["run_routine_result.txt", "prepare_result.txt", "sessions", "sms_watch_log.txt", "perform_login_result.txt"]
PROBE = (f"import sys; sys.path.insert(0, {str(ROOT)!r}); import json, run_routine as rr, web_runner as wr, "
         "sms_watch as sw, perform_login as pl; "
         "print(json.dumps([rr.RESULT_PATH, wr.RESULT_PATH, wr.SESSION_DIR, sw.LOG_PATH, pl.OUT_FILE]))")


def module_paths(programdata):
    """네 모듈을 새 프로세스에서 불러와 결과 파일 자리를 받는다 (모듈 상수라 import 할 때 정해진다)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("RPA_")}
    env.update(RPA_PROGRAMDATA=programdata, RPA_STATUS_DIR=os.path.join(tmp, "status"), PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, "-c", PROBE], cwd=str(ROOT), env=env, capture_output=True,
                       text=True, encoding="utf-8", timeout=180)
    if r.returncode != 0:
        return r.stderr[-500:]
    return json.loads(r.stdout.strip().splitlines()[-1])


got = module_paths(new_root)          # 2절에서 만든 새 구조 뿌리 (config 있음)
check("새 구조면 결과 로그·세션이 모두 data 에", got == [os.path.join(new_root, "data", n) for n in NAMES], str(got))
got = module_paths(os.path.join(tmp, "empty_root2"))
check("옛 구조면 지금처럼 프로그램 폴더 (exe 옆, 개발 PC 는 dist)",
      got == [os.path.join(st.program_dir(), n) for n in NAMES], str(got))
for name in ("run_routine.py", "web_runner.py", "sms_watch.py", "perform_login.py"):
    src = open(ROOT / name, encoding="utf-8").read()
    check(f"{name} 에 각자 exe 옆을 계산하던 app_base_dir 이 없다", "def app_base_dir" not in src)

finish()
