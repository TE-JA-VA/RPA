# -*- coding: utf-8 -*-
"""설치 폴더에서 소스(.py)로 도는 파일이 불러오는 우리 모듈이 모두 배포 파일 목록(build_release.PROGRAM_FILES)에 있는가.
빠지면 설치한 PC 에서 그 파일이 ModuleNotFoundError 로 켜지지 않는다 - 2026-11-23 검토 2번: agent.py 가 local_store·edition 을
불러오는데 목록에 없어, 이 브랜치로 일반 버전을 빌드하면 에이전트가 켜지지 않았다.
    .venv\\Scripts\\python.exe tests\\test_program_files_imports.py
"""
import ast
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import build_release as br  # noqa: E402

fails = []
# 배포 목록에 없어도 되는 것: exe 안에만 있는 모듈을 '있으면 쓰는' 자리 (ImportError 를 잡거나 exe 에서만 도는 길).
# 여기에 더할 때는 그 불러오기가 실패해도 설치본이 도는지 확인하고 까닭을 적는다.
ALLOW = {}


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def local_module(name):
    """그 이름의 우리 모듈 파일 (저장소 뿌리 또는 firebase/agent). 표준·바깥 패키지면 None."""
    for folder in ("", "firebase/agent"):
        rel = f"{folder}/{name}.py".lstrip("/")
        if os.path.isfile(os.path.join(ROOT, *rel.split("/"))):
            return rel
    return None


def guarded(tree):
    """try: … except ImportError 안의 불러오기 줄 번호 - 없어도 도는 자리."""
    lines = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and any(
                h.type is None or "ImportError" in ast.dump(h.type) or "Exception" in ast.dump(h.type) for h in node.handlers):
            for sub in node.body:
                for n in ast.walk(sub):
                    if isinstance(n, (ast.Import, ast.ImportFrom)):
                        lines.add(n.lineno)
    return lines


shipped = {rel for rel, _ in br.PROGRAM_FILES}
sources = {src: rel for rel, src in br.PROGRAM_FILES if rel.endswith(".py")}
missing = []
for src, rel in sorted(sources.items()):
    with open(os.path.join(ROOT, *src.split("/")), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    soft = guarded(tree)
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module.split(".")[0]]
        for name in names:
            need = local_module(name)
            if need and need not in shipped and node.lineno not in soft and (rel, name) not in ALLOW:
                missing.append(f"{rel}:{node.lineno} → {need}")

print("배포 파일 목록과 불러오기")
check("소스로 도는 파일이 불러오는 우리 모듈이 모두 배포 목록에 있다", not missing, "\n      " + "\n      ".join(missing))
check("스탠드얼론 파일 넷이 목록에 있다 (에이전트가 늘 불러오는 둘 포함)",
      {"edition.py", "license_check.py", "firebase/agent/local_store.py", "firebase/agent/local_server.py"} <= shipped)
check("exe 가 인증번호 중계에 쓰는 모듈에 local_store", "--include-module=local_store" in br.AGENT_MODULES)

print(f"\n실패: {len(fails)}" + (f" ({', '.join(fails)})" if fails else ""))
sys.exit(1 if fails else 0)
