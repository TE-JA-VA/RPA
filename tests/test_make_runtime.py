# tests/test_make_runtime.py
# -*- coding: utf-8 -*-
"""배포에 싣는 내장 파이썬 폴더 만들기 (tools/make_runtime.py, 2026-11-20). 가짜 설치본·가짜 지금 폴더 - 진짜 파이썬은 안 쓴다."""
import io
import os
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [REPO, os.path.join(REPO, "tools")]
import make_runtime as mr  # noqa: E402

fails = []


def check(cond, what):
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        fails.append(what)


def put(root, rel, text="x = 1\n"):
    full = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(text)


def rels(root):
    out = set()
    for base, _, files in os.walk(root):
        for n in files:
            out.add(os.path.relpath(os.path.join(base, n), root).replace(os.sep, "/"))
    return out


tmp = tempfile.mkdtemp(prefix="rpa_mkrt_")
TAG = sys.implementation.cache_tag                       # cpython-314
BASE, LIKE, OUT = os.path.join(tmp, "base"), os.path.join(tmp, "like"), os.path.join(tmp, "out", "python")
for rel in ("python.exe", "python314.dll", "DLLs/_ssl.pyd", "Lib/os.py", "Lib/new_mod.py", "Lib/json/__init__.py", f"Lib/__pycache__/os.{TAG}.pyc",
            "Lib/idlelib/idle.py", "Lib/ensurepip/__init__.py", "Lib/site-packages/pip/__init__.py", "Doc/html/index.html", "Scripts/pip.exe",
            "include/Python.h", "libs/python314.lib", "share/man/man1/python.1"):
    put(BASE, rel)
for rel in ("python.exe", "python314.dll", "DLLs/_ssl.pyd", "Lib/os.py", "Lib/old_mod.py", "Lib/json/__init__.py",
            f"Lib/__pycache__/os.{TAG}.pyc", f"Lib/__pycache__/old_mod.{TAG}.pyc", f"Lib/json/__pycache__/__init__.{TAG}.pyc"):
    put(LIKE, rel, "old\n")

r = mr.make(BASE, OUT, like=LIKE)
got = rels(OUT)
check({"python.exe", "python314.dll", "DLLs/_ssl.pyd", "Lib/os.py", "Lib/new_mod.py", "Lib/json/__init__.py"} <= got,
      f"기본 설치본의 실행 파일·DLL·표준 라이브러리를 가져온다 ({sorted(got)})")
check(not [x for x in got if x.split("/")[0] in ("Doc", "Scripts", "include", "libs", "share")
           or x.startswith(("Lib/idlelib/", "Lib/ensurepip/", "Lib/site-packages/"))],
      "문서·Scripts·include·libs·share 와 Lib 의 idlelib·ensurepip·site-packages 는 뺀다")
pyc = sorted(x for x in got if "__pycache__" in x)
check(pyc == [f"Lib/__pycache__/os.{TAG}.pyc", f"Lib/json/__pycache__/__init__.{TAG}.pyc"],
      f"__pycache__ 는 지금 폴더에 있던 모듈만 새 원본으로 다시 컴파일한다 (설치본의 pyc 는 안 가져온다) ({pyc})")
check(open(os.path.join(OUT, "Lib", "__pycache__", f"os.{TAG}.pyc"), "rb").read() != open(os.path.join(BASE, "Lib", "__pycache__", f"os.{TAG}.pyc"), "rb").read(),
      "pyc 는 복사가 아니라 컴파일한 것")
check(open(os.path.join(OUT, "Lib", "os.py"), encoding="utf-8").read() == "x = 1\n"
      and int(os.path.getmtime(os.path.join(OUT, "Lib", "os.py"))) == int(os.path.getmtime(os.path.join(BASE, "Lib", "os.py"))),
      "원본 파일의 내용과 수정 시각을 그대로 (pyc 가 원본 시각으로 맞는지 본다)")
check(r["only_new"] == ["Lib/new_mod.py"] and r["only_old"] == ["Lib/old_mod.py"] and r["pyc_no_source"] == [f"Lib/__pycache__/old_mod.{TAG}.pyc"]
      and r["pyc_made"] == 2 and r["files"] == 6, f"지금 폴더와 견준 차이를 알려 준다 ({r})")
try:
    mr.make(BASE, OUT, like=LIKE)
    check(False, "이미 있는 폴더를 덮어씀")
except FileExistsError:
    check(True, "이미 있는 폴더는 덮어쓰지 않는다")
OUT2 = os.path.join(tmp, "out2", "python")
r2 = mr.make(BASE, OUT2)
check(not [x for x in rels(OUT2) if "__pycache__" in x] and r2["pyc_made"] == 0 and r2["only_new"] == [] and r2["only_old"] == [],
      "견줄 폴더(like)를 안 주면 __pycache__ 없이 만든다")

shutil.rmtree(tmp, ignore_errors=True)
print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
