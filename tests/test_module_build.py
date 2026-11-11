"""조각 컴파일 빌드 시험 - 시작 파일·조각 보관·라이브러리 묶음 (설계 docs/superpowers/specs/2026-11-11-module-build-design.md).

시작 파일은 진짜로 만들어 돌린다 (zig, 몇 초). 조각은 가짜 컴파일로 보관 규칙만 본다.

    .venv\\Scripts\\python.exe tests\\test_module_build.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.stdout.reconfigure(encoding="utf-8")

import win32api  # noqa: E402
import win32con  # noqa: E402

import build_release as br  # noqa: E402

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


def icon_count(path):
    h = win32api.LoadLibraryEx(path, 0, win32con.LOAD_LIBRARY_AS_DATAFILE)
    try:
        return len(win32api.EnumResourceNames(h, win32con.RT_ICON))
    finally:
        win32api.FreeLibrary(h)


def run(exe, *args, cwd):
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PYTHON")}
    return subprocess.run([exe, *args], capture_output=True, cwd=cwd, timeout=120, env=env)


tmp = tempfile.mkdtemp(prefix="rpa_modbuild_")

# ---------------------------------------------------------------------------
print("=== 1. 시작 파일 ===")
FAKE = ('import sys, os, json\n'
        'def run_main():\n'
        '    print(json.dumps({"argv": sys.argv, "exe": sys.executable, "home": os.environ.get("PYTHONHOME"), "path0": sys.path[0]}))\n'
        '    return 7\n')
top = os.path.join(tmp, "공백 한글 폴더", "RPA")
shutil.copytree(os.path.join(br.RUNTIME_ROOT, "python"), os.path.join(top, "python"))
os.makedirs(os.path.join(top, "app"))
os.makedirs(os.path.join(top, "lib"))
shutil.copy2(ROOT / "app_start.py", os.path.join(top, "app", "_start.py"))
for mod in ("web_runner", "rpa_observer", "run_routine"):
    with open(os.path.join(top, "app", mod + ".py"), "w", encoding="utf-8") as f:
        f.write(FAKE)
with open(os.path.join(top, "web_runner.py"), "w", encoding="utf-8") as f:      # 함정: 프로그램 폴더의 같은 이름
    f.write("raise SystemExit(99)\n")
lc = os.path.join(tmp, "lc")
br.build_launchers(top, cache=lc)
exe = os.path.join(top, "Prepare_RPA.exe")
r = run(exe, "--preset", "① 지마켓", 'a "b" c', cwd=top)
try:
    got = json.loads(r.stdout.decode("utf-8"))
except ValueError:
    got = {"argv": None, "exe": None, "home": "?", "path0": ""}
check("종료 코드가 그대로 나온다", r.returncode == 7, f"{r.returncode} {r.stderr[-300:]!r}")
check("인자가 그대로, argv[0] 은 exe", got["argv"] == [exe, "--preset", "① 지마켓", 'a "b" c'], str(got["argv"]))
check("sys.executable 은 exe, PYTHONHOME 은 물려주지 않는다", got["exe"] == exe and got["home"] is None, str(got))
check("프로그램 폴더의 함정 .py 가 아니라 app 의 것을 쓴다",
      os.path.normcase(got["path0"]) == os.path.normcase(os.path.join(top, "app")), got["path0"])
check("PROCESS 시작 파일", run(os.path.join(top, "ERPia_RPA.exe"), cwd=top).returncode == 7)
r = run(os.path.join(top, "Prepare_Observer.exe"), "--check", cwd=top)
check("옵저버 시작 파일 (창 프로그램, 출력은 부른 쪽이 받는다)", r.returncode == 7 and b'"argv"' in r.stdout, f"{r.returncode} {r.stdout[-200:]!r}")
check("다른 폴더에서 켜도 같다", run(exe, cwd=tmp).returncode == 7)
check("exe 마다 아이콘 9장", all(icon_count(os.path.join(top, e)) == 9 for e in br.EXES))
before = {e: open(os.path.join(top, e), "rb").read() for e in br.EXES}
br.build_launchers(top, cache=lc)
check("재료가 같으면 시작 파일이 한 바이트도 안 바뀐다", all(open(os.path.join(top, e), "rb").read() == before[e] for e in br.EXES))
check("프로그램마다 다른 파일 (아이콘·설명)", len(set(before.values())) == 3)
# lib 가 없다 / _start.py 가 없다 - 한 줄 안내와 코드 2 (Review Focus 3)
shutil.rmtree(os.path.join(top, "lib"))
r = run(exe, "--check", cwd=top)
check("lib 가 없으면 한 줄 안내와 코드 2",
      r.returncode == 2 and "다시 설치하여 주십시오".encode("utf-8") in r.stdout + r.stderr and b"Traceback" not in r.stderr,
      f"{r.returncode} {r.stderr[-300:]!r}")
os.remove(os.path.join(top, "app", "_start.py"))
r = run(exe, "--check", cwd=top)
check("_start.py 가 없으면 코드 2", r.returncode == 2, f"{r.returncode} {r.stderr[-300:]!r}")
r = run(os.path.join(top, "Prepare_Observer.exe"), "--check", cwd=top)
check("창 프로그램도 --check 면 창 없이 코드 2", r.returncode == 2, str(r.returncode))

shutil.rmtree(tmp, ignore_errors=True)
finish()
