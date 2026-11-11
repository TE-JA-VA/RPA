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


def run(exe, *args, cwd, **more):
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PYTHON")}
    env.update(more)
    return subprocess.run([exe, *args], capture_output=True, cwd=cwd, timeout=120, env=env)


tmp = tempfile.mkdtemp(prefix="rpa_modbuild_")

# ---------------------------------------------------------------------------
print("=== 1. 시작 파일 ===")
FAKE = ('import sys, os, json, ctypes\n'
        'import probe_lib\n'
        'def run_main():\n'
        '    try:\n'
        '        ctypes.WinDLL("rpa_probe_dep.dll")\n'
        '        dep = True\n'
        '    except OSError:\n'
        '        dep = False\n'
        '    print(json.dumps({"argv": sys.argv, "exe": sys.executable, "home": os.environ.get("PYTHONHOME"), "path0": sys.path[0], "dep": dep,\n'
        '                      "lib": probe_lib.WHERE}))\n'
        '    return 7\n')
top = os.path.join(tmp, "공백 한글 폴더", "RPA")
shutil.copytree(os.path.join(br.RUNTIME_ROOT, "python"), os.path.join(top, "python"))
shutil.copy2(os.path.join(top, "python", "vcruntime140_1.dll"), os.path.join(top, "python", "rpa_probe_dep.dll"))   # 내장 Python 폴더에만 있는 DLL
os.makedirs(os.path.join(top, "app"))
os.makedirs(os.path.join(top, "lib"))
with open(os.path.join(top, "lib", ".unpacked"), "w", encoding="utf-8") as f:    # 설치 마무리가 다 풀었다는 표시
    f.write("x")
with open(os.path.join(top, "lib", "probe_lib.py"), "w", encoding="utf-8") as f:
    f.write('WHERE = "lib"\n')
trap = os.path.join(tmp, "trap")
os.makedirs(trap)
with open(os.path.join(trap, "probe_lib.py"), "w", encoding="utf-8") as f:       # PC 에 PYTHONPATH 가 잡혀 있을 때
    f.write('WHERE = "trap"\n')
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
    got = {"argv": None, "exe": None, "home": "?", "path0": "", "dep": None, "lib": None}
check("종료 코드가 그대로 나온다", r.returncode == 7, f"{r.returncode} {r.stderr[-300:]!r}")
check("인자가 그대로, argv[0] 은 exe", got["argv"] == [exe, "--preset", "① 지마켓", 'a "b" c'], str(got["argv"]))
check("sys.executable 은 exe, PYTHONHOME 은 물려주지 않는다", got["exe"] == exe and got["home"] is None, str(got))
check("프로그램 폴더의 함정 .py 가 아니라 app 의 것을 쓴다",
      os.path.normcase(got["path0"]) == os.path.normcase(os.path.join(top, "app")), got["path0"])
check("내장 Python 폴더의 DLL 을 찾는다 (깨끗한 윈도우에는 vcruntime140_1.dll 이 시스템에 없다 - 샌드박스 2026-11-11)", got["dep"] is True, str(got["dep"]))
r = run(exe, cwd=top, PYTHONPATH=trap, PYTHONSTARTUP=os.path.join(trap, "none.py"), PYTHONINSPECT="1")
try:
    where = json.loads(r.stdout.decode("utf-8"))["lib"]
except (ValueError, KeyError):
    where = r.stderr[-200:]
check("PC 의 PYTHONPATH 등이 우리 라이브러리를 가리지 않는다 (검토 2026-11-11)", r.returncode == 7 and where == "lib", f"{r.returncode} {where}")
check("PROCESS 시작 파일", run(os.path.join(top, "ERPia_RPA.exe"), cwd=top).returncode == 7)
r = run(os.path.join(top, "Prepare_Observer.exe"), "--check", cwd=top)
check("옵저버 시작 파일 (창 프로그램, 출력은 부른 쪽이 받는다)", r.returncode == 7 and b'"argv"' in r.stdout, f"{r.returncode} {r.stdout[-200:]!r}")
check("다른 폴더에서 켜도 같다", run(exe, cwd=tmp).returncode == 7)
check("exe 마다 아이콘 9장", all(icon_count(os.path.join(top, e)) == 9 for e in br.EXES))
before = {e: open(os.path.join(top, e), "rb").read() for e in br.EXES}
br.build_launchers(top, cache=lc)
check("재료가 같으면 시작 파일이 한 바이트도 안 바뀐다", all(open(os.path.join(top, e), "rb").read() == before[e] for e in br.EXES))
check("프로그램마다 다른 파일 (아이콘·설명)", len(set(before.values())) == 3)
# 조각·라이브러리가 빠졌다 / lib 를 덜 풀었다 / lib 가 없다 / _start.py 가 없다 - 한 줄 안내와 코드 2 (Review Focus 3)
os.rename(os.path.join(top, "app", "web_runner.py"), os.path.join(top, "app", "web_runner.gone"))
r = run(exe, "--check", cwd=top)
check("조각이 빠지면 (백신 격리) 오류 추적 대신 한 줄 안내와 코드 2",
      r.returncode == 2 and "다시 설치하여 주십시오".encode("utf-8") in r.stderr and b"Traceback" not in r.stderr and b"web_runner" in r.stderr,
      f"{r.returncode} {r.stderr[-300:]!r}")
os.rename(os.path.join(top, "app", "web_runner.gone"), os.path.join(top, "app", "web_runner.py"))
os.remove(os.path.join(top, "lib", "probe_lib.py"))
r = run(exe, "--check", cwd=top)
check("라이브러리가 빠져도 한 줄 안내와 코드 2", r.returncode == 2 and b"Traceback" not in r.stderr and b"probe_lib" in r.stderr, f"{r.returncode} {r.stderr[-300:]!r}")
os.remove(os.path.join(top, "lib", ".unpacked"))
r = run(exe, "--check", cwd=top)
check("lib 를 덜 풀었으면 (표시 없음) 한 줄 안내와 코드 2", r.returncode == 2 and b"Traceback" not in r.stderr and b".unpacked" in r.stderr, f"{r.returncode} {r.stderr[-300:]!r}")
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

# ---------------------------------------------------------------------------
print("=== 2. 조각 컴파일과 보관 (가짜 컴파일) ===")
import importlib.machinery  # noqa: E402

SUFFIX = importlib.machinery.EXTENSION_SUFFIXES[0]
calls = []


def fake(src, out_dir):
    """compile_module 흉내: 부른 소스를 적고 내용이 소스 이름인 조각을 쓴다."""
    calls.append(os.path.basename(src))
    path = os.path.join(out_dir, os.path.splitext(os.path.basename(src))[0] + SUFFIX)
    with open(path, "wb") as f:
        f.write(os.path.basename(src).encode("utf-8"))
    return path


work, cache = os.path.join(tmp, "work"), os.path.join(tmp, "pc")
sources = br.module_sources()
names = {os.path.splitext(os.path.basename(s))[0] for s in sources}
check("exe 셋의 우리 파일을 모두 모은다",
      names >= {"run_routine", "web_runner", "rpa_observer", "rpa_status", "web_replay", "fb", "secret", "wellife"}, str(sorted(names)))
check("같은 파일은 한 번만", len(names) == len(sources))
out1 = br.build_modules(work, cache=cache, compile=fake)
check("처음에는 모두 컴파일한다", sorted(calls) == sorted(os.path.basename(s) for s in sources), str(calls))
check("조각은 work\\app 에", sorted(os.listdir(os.path.join(work, "app"))) == sorted(n + SUFFIX for n in names))
check("builder 글자에 도구와 새로 만든 수", "nuitka" in out1 and f"조각 새로 {len(sources)}" in out1, out1)
calls.clear()
out2 = br.build_modules(work, cache=cache, compile=fake)
check("재료가 같으면 하나도 다시 만들지 않는다", calls == [] and f"그대로 {len(sources)}" in out2, f"{calls} {out2}")
calls.clear()
br.build_modules(work, cache=cache, compile=fake, force=True)
check("force 면 모두 새로", len(calls) == len(sources))
with open(os.path.join(cache, "rpa_status" + SUFFIX), "wb") as f:
    f.write(b"broken")
calls.clear()
out3 = br.build_modules(work, cache=cache, compile=fake)
check("보관한 조각이 깨졌으면 그것만 다시 만든다", calls == ["rpa_status.py"] and "조각 새로 1: rpa_status" in out3, f"{calls} {out3}")
a, b = os.path.join(tmp, "a.py"), os.path.join(tmp, "b.py")
for path, text in ((a, "x = 1\n"), (b, "x = 2\n")):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
check("지문은 그 파일 내용과 도구 버전만 본다",
      br.module_fingerprint(a, "t") != br.module_fingerprint(b, "t") and br.module_fingerprint(a, "t") == br.module_fingerprint(a, "t")
      and br.module_fingerprint(a, "t") != br.module_fingerprint(a, "t2"))
with open(os.path.join(work, "app", "gone" + SUFFIX), "wb") as f:
    f.write(b"x")
br.build_modules(work, cache=cache, compile=fake)
check("소스에 없는 옛 조각은 남기지 않는다", not os.path.exists(os.path.join(work, "app", "gone" + SUFFIX)))

# ---------------------------------------------------------------------------
print("=== 3. 라이브러리 묶음 ===")
import zipfile  # noqa: E402

z1, z2 = os.path.join(tmp, "lib1.zip"), os.path.join(tmp, "lib2.zip")
br.build_lib_zip(z1)
br.build_lib_zip(z2)
with zipfile.ZipFile(z1) as z:
    lib_names = z.namelist()
    checker = z.read("comtypes/_tlib_version_checker.py")
check("같은 재료면 묶음이 한 바이트도 안 다르다", open(z1, "rb").read() == open(z2, "rb").read())
check("실을 것이 들어 있다", {"playwright/__init__.py", "pywinauto/__init__.py", "pythonwin/mfc140u.dll", "pywin32.pth",
                              "pythoncom.py", "greenlet/__init__.py", "PIL/__init__.py"} <= set(lib_names))
check("뺄 것은 빠졌다", not any("__pycache__" in n or n.endswith("driver/node.exe") or n.startswith("comtypes/test/")
                                or ".dist-info/" in n for n in lib_names))
check("comtypes 시각 검사를 껐다", b'if not hasattr(sys, "frozen"):' not in checker and b"if False:" in checker)
check("빌드 PC 의 comtypes gen 을 같이 싣는다", any(n.startswith("comtypes/gen/") and n.endswith(".py") for n in lib_names))
check("우리 코드·개발 도구는 싣지 않는다", not any(n.split("/")[0] in ("nuitka", "pip", "numpy", "setuptools") for n in lib_names))
check("묶음 크기 60MB 안쪽", os.path.getsize(z1) < 60 * 2 ** 20, f"{os.path.getsize(z1) // 2 ** 20}MB")

shutil.rmtree(tmp, ignore_errors=True)
finish()
