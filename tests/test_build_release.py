"""빌드 스크립트 시험 - exe 는 만들지 않고 가짜 입력으로 판 번호·모으기·판 목록·압축·검사를 돌린다.

    .venv\\Scripts\\python.exe tests\\test_build_release.py
"""
import datetime
import hashlib
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.stdout.reconfigure(encoding="utf-8")

import build_release as br  # noqa: E402
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


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode("utf-8"))


tmp = tempfile.mkdtemp(prefix="rpa_build_")
repo, runtime = os.path.join(tmp, "repo"), os.path.join(tmp, "runtime")
exe_dir, out_root = os.path.join(tmp, "exe"), os.path.join(tmp, "out")
BLANK = {"LogIn": {"AdminCode": "", "ID": "", "PW": ""}, "Sites": {"SITE1": {"URL": "https://x", "ID": "", "PW": ""}}}
for rel, src in br.PROGRAM_FILES + br.OTHER_FILES:
    body = json.dumps(BLANK) if src.endswith(".json") else f"{rel} 내용\r\n".encode("cp949")
    write(os.path.join(repo, *src.split("/")), body)
for exe in br.EXES:
    write(os.path.join(exe_dir, exe), b"MZ fake " + exe.encode())
write(os.path.join(runtime, "python", "Lib", "__pycache__", "os.cpython-314.pyc"), b"pyc")   # 내장 파이썬엔 원래 있다
write(os.path.join(runtime, "ms-playwright", "chromium-1234", "chrome.exe"), b"chrome")
write(os.path.join(runtime, "ms-playwright", ".links", "x"), b"")                              # playwright 가 남기는 표시 폴더
others = [rel for rel, _ in br.OTHER_FILES]

# ---------------------------------------------------------------------------
print("=== 1. 판 번호 ===")
day = datetime.date(2026, 9, 29)
check("첫 판은 -1", br.next_version(out_root, day) == "2026.09.29-1")
os.makedirs(os.path.join(out_root, "배포_2026.09.29-1"))
write(os.path.join(out_root, "배포_2026.09.29-2.zip"), b"")
check("그날 있는 폴더·압축의 다음 번호", br.next_version(out_root, day) == "2026.09.29-3")
check("날이 바뀌면 다시 1", br.next_version(out_root, datetime.date(2026, 9, 30)) == "2026.09.30-1")

# ---------------------------------------------------------------------------
print("=== 2. 모으기와 판 목록 ===")
out_dir = os.path.join(out_root, "배포_2026.09.29-3")
program = br.collect(out_dir, exe_dir, repo=repo, runtime_root=runtime)
check("판 목록 대상은 exe 둘과 프로그램 파일",
      set(program) == set(br.EXES) | {rel for rel, _ in br.PROGRAM_FILES}, str(program))
man = br.write_manifest(out_dir, "2026.09.29-3", "nuitka 4.2.2 · python 3.14.7", program)
check("형식·판 번호·빌더", man["format"] == st.MANIFEST_FORMAT and man["version"] == "2026.09.29-3"
      and man["builder"] == "nuitka 4.2.2 · python 3.14.7")
check("문서·배포 틀은 판 목록에 없다", not set(others) & set(man["files"]))
bat = "firebase/agent/에이전트_시작.bat"
check("한글 파일 이름도 지문", man["files"][bat]["sha256"]
      == hashlib.sha256(f"{bat} 내용\r\n".encode("cp949")).hexdigest())
check("런타임은 이름표만 (점으로 시작하는 표시 폴더는 뺀다)",
      man["runtime"]["ms-playwright"] == ["chromium-1234"] and "python" in man["runtime"], str(man["runtime"]))
check("만든 판은 에이전트의 판 점검에서 ok", st.check_install(out_dir)["state"] == "ok", str(st.check_install(out_dir)))
try:
    br.collect(out_dir, exe_dir, repo=repo, runtime_root=runtime)
    ok = False
except FileExistsError:
    ok = True
check("이미 있는 판 폴더는 덮어쓰지 않는다", ok)

# ---------------------------------------------------------------------------
print("=== 3. 압축과 검사 ===")
zip_path = out_dir + ".zip"
br.make_zip(out_dir, zip_path)
with zipfile.ZipFile(zip_path) as z:
    names = z.namelist()
check("압축 맨 위 폴더는 판 폴더 이름", all(n.startswith("배포_2026.09.29-3/") for n in names))
check("한글 이름이 압축에서 깨지지 않는다", f"배포_2026.09.29-3/{bat}" in names)
check("깨끗한 판은 문제 없음 (런타임 안 __pycache__ 는 괜찮다)", br.verify_zip(zip_path, man, program, others) == [],
      str(br.verify_zip(zip_path, man, program, others)))


def variant(name, change):
    """out_dir 사본을 고쳐 압축하고 검사 결과를 돌려준다."""
    d = os.path.join(out_root, name)
    shutil.copytree(out_dir, d)
    change(d)
    br.make_zip(d, d + ".zip")
    return br.verify_zip(d + ".zip", man, program, others)


p = variant("배포_junk", lambda d: [write(os.path.join(d, "firebase", "agent", "queue.jsonl"), b""),
                                     write(os.path.join(d, "__pycache__", "rpa_status.cpython-314.pyc"), b""),
                                     write(os.path.join(d, "run_routine_result.txt"), b""),
                                     write(os.path.join(d, "sessions", "SITE1.json"), b"{}")])
check("찌꺼기(큐·__pycache__·결과 로그·세션)는 문제로 잡는다",
      all(any(k in x for x in p) for k in ("queue.jsonl", "__pycache__", "run_routine_result.txt", "sessions")), str(p))
p = variant("배포_leak", lambda d: write(os.path.join(d, "RPA_UserConfig.json"),
                                          json.dumps({"LogIn": {"AdminCode": "a", "ID": "b", "PW": "진짜비번"}})))
check("로그인이 든 배포 틀은 문제로 잡고, 값은 찍지 않는다",
      any("LogIn.PW" in x for x in p) and not any("진짜비번" in x for x in p), str(p))
p = variant("배포_tamper", lambda d: write(os.path.join(d, "rpa_status.py"), b"changed"))
check("지문이 다른 파일은 문제로 잡는다", any("지문 다름: rpa_status.py" in x for x in p), str(p))
p = variant("배포_extra", lambda d: write(os.path.join(d, "memo.txt"), b"x"))
check("모은 목록에 없는 파일은 문제로 잡는다", any("memo.txt" in x for x in p), str(p))

# ---------------------------------------------------------------------------
print("=== 4. exe 출력의 끝 줄 표지 ===")
check("UTF-8 출력에서 찾는다", br.found_marker("… === 점검 끝 (루틴은 …) ===\n".encode("utf-8"), "=== 점검 끝"))
check("CP949 출력에서 찾는다", br.found_marker("  쓸 수 있는 Action: login\r\n".encode("cp949"), "쓸 수 있는 Action"))
check("없으면 못 찾는다", not br.found_marker(b"Traceback ...", "=== 점검 끝"))

# ---------------------------------------------------------------------------
print("=== 5. exe 를 실행조차 못 해도 판정으로 끝난다 ===")
# 가짜 exe(윈도우 실행 파일이 아님)는 보안 프로그램이 격리해 실행을 못 하는 경우와 같다 - 오류 추적 대신 '문제' 로
try:
    p = br.smoke_check(zip_path, timeout=30)
    ok = len(p) == len(br.EXES) and all("실행하지 못했습니다" in x for x in p)
except OSError as e:
    p, ok = repr(e), False
check("실행 못 하는 exe 는 문제 한 줄씩 (예외로 빠져나가지 않는다)", ok, str(p))

finish()
