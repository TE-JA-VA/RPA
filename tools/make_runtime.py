r"""배포에 싣는 내장 파이썬 폴더(D:\AX\runtime\python)를 새 파이썬 버전으로 만든다 (2026-11-20, 3.14.7 → 3.14.10 때 손으로 한 일).

    .venv\Scripts\python.exe tools\make_runtime.py <기본 설치본 폴더> <새로 만들 폴더> [--like <지금 쓰는 내장 파이썬 폴더>]

    예) .venv\Scripts\python.exe tools\make_runtime.py %LOCALAPPDATA%\Python\pythoncore-3.14-64 D:\AX\runtime_new\python --like D:\AX\runtime\python

기본 설치본(python.org 설치본 - python.exe 가 든 폴더)에서 고객 PC 에 필요 없는 것을 빼고 복사한다:
문서(Doc)·Scripts·include·libs·share 와 Lib 의 ensurepip·idlelib·site-packages. __pycache__ 는 가져오지 않고, --like 를 주면
그 폴더에 pyc 가 있던 모듈만 새 원본으로 다시 컴파일한다 (설치 폴더는 일반 사용자가 못 써서, pyc 가 없으면 켤 때마다 다시 컴파일한다).
이미 있는 폴더는 덮어쓰지 않는다 - 새 폴더에 만든 뒤 사람이 D:\AX\runtime\python 과 바꾼다 (옛 폴더는 남겨 둔다).

내장 파이썬을 올리는 차례 (설계 docs/superpowers/specs/2026-11-20-runtime-update-design.md):
  1. 개발 PC 의 파이썬을 올린다 (py install --update 3.14 - 그 파이썬을 쓰는 프로그램을 먼저 끈다). .venv 는 venv --upgrade --without-pip
  2. 이 도구로 새 폴더를 만들고, 끝에 찍히는 '지금 폴더와 다른 파일' 을 본 뒤 D:\AX\runtime\python 과 바꾼다
  3. 빌드 (--modules - 조각이 모두 새로 만들어진다) → 샌드박스 --from <직전 버전 설치 파일> <새 설치 파일> → 내보내기
  빌드하는 파이썬(.venv)과 내장 파이썬은 같은 버전이어야 한다. 2026.11.20-1 보다 옛 버전인 PC 는 파이썬이 바뀐 버전을 못 받는다.
"""
import json
import os
import py_compile
import shutil
import subprocess
import sys

SKIP_TOP = ("Doc", "Scripts", "include", "libs", "share")
SKIP_LIB = ("ensurepip", "idlelib", "site-packages")


def _rels(root, pyc):
    out = set()
    for base, _, files in os.walk(root):
        for name in files:
            rel = os.path.relpath(os.path.join(base, name), root).replace(os.sep, "/")
            if ("__pycache__" in rel.split("/")) == pyc:
                out.add(rel)
    return out


def wanted(rel):
    parts = rel.split("/")
    return parts[0] not in SKIP_TOP and not (parts[0] == "Lib" and len(parts) > 1 and parts[1] in SKIP_LIB)


def make(base, out, like=None):
    """base(기본 설치본)에서 out 을 만든다. 돌려주는 것: 파일 수와 like(지금 폴더)와 견준 차이.
    pyc 는 이 함수를 돌리는 파이썬으로 컴파일한다 - 내장 파이썬과 같은 버전으로 돌려야 한다 (main 이 확인한다)."""
    if os.path.exists(out):
        raise FileExistsError(out)
    new = {r for r in _rels(base, pyc=False) if wanted(r)}
    for rel in sorted(new):
        dst = os.path.join(out, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(base, *rel.split("/")), dst)          # 수정 시각도 - pyc 가 원본 시각으로 맞는지 본다
    made, no_source = 0, []
    for rel in sorted(_rels(like, pyc=True)) if like else []:
        folder, name = os.path.split(rel)                                # Lib/__pycache__, os.cpython-314.pyc
        src = os.path.join(out, *os.path.dirname(folder).split("/"), name.split(".")[0] + ".py")
        if not os.path.isfile(src):
            no_source.append(rel)
            continue
        py_compile.compile(src, doraise=True)
        made += 1
    old = _rels(like, pyc=False) if like else new
    return {"files": len(new), "only_new": sorted(new - old), "only_old": sorted(old - new), "pyc_made": made, "pyc_no_source": no_source}


def _version(python_dir):
    r = subprocess.run([os.path.join(python_dir, "python.exe"), "-I", "-B", "-c", "import platform; print(platform.python_version())"],
                       capture_output=True, text=True, timeout=60)
    return r.stdout.strip()


def main(argv=None):
    args = sys.argv[1:] if argv is None else list(argv)
    like = None
    if "--like" in args:
        i = args.index("--like")
        like = args[i + 1] if i + 1 < len(args) else ""
        del args[i:i + 2]
    if len(args) != 2 or not os.path.isfile(os.path.join(args[0], "python.exe")) or (like is not None and not os.path.isdir(like)):
        print(__doc__)
        return 2
    base, out = args
    import platform
    if _version(base) != platform.python_version():
        print(f"이 도구를 돌리는 파이썬({platform.python_version()})과 기본 설치본({_version(base) or '?'})의 버전이 다릅니다 - "
              "같은 버전으로 돌려야 pyc 가 맞습니다 (.venv 를 먼저 올리세요).")
        return 2
    r = make(base, out, like=like)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    print(f"만든 폴더: {out}  (파이썬 {_version(out)})")
    if like:
        print("지금 폴더와 다른 파일(only_new·only_old)을 본 뒤, 지금 폴더를 다른 이름으로 남기고 이 폴더를 그 자리에 놓으세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
