"""배포판 글 파일 인코딩 시험 (2026-09-29).

- 안내 문서(.txt)는 UTF-8 (BOM 포함 - 윈도우 메모장·Mac 모두 바로 읽는다). 사용자 요청으로 CP949 에서 바꿨다
- .bat 는 CP949 그대로, 줄 끝 CRLF. UTF-8 + chcp 65001 로 바꿔 보니 cmd 가 한글 줄 뒤의 줄 위치를 잘못 세어
  다음 줄 앞부분을 건너뛰고 나머지 조각을 명령으로 실행했다 ('바탕화면\\ERPIA_AI\\…' 를 명령으로 실행 → 경로 오류).
  그래서 .bat 는 UTF-8 로 바꾸지 않는다
- Run_All.bat 은 실제로 돌려 본다: 두 exe 자리에 곧바로 끝나는 가짜(where.exe)를 두고 새 콘솔에서 실행해
  한글 안내 줄이 그대로 찍히고 명령 창 오류가 한 줄도 없는지 본다. 실제 RPA 는 돌지 않는다.

    .venv\\Scripts\\python.exe tests\\test_encoding.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding="utf-8")
BATS = [ROOT / "Run_All.bat", ROOT / "firebase" / "agent" / "에이전트_시작.bat"]
GUIDES = [ROOT / "release" / "배포안내.txt", ROOT / "release" / "클라우드_안내.txt"]

fails = []
_no = [0]


def check(name, cond, detail=""):
    _no[0] += 1
    mark = "통과" if cond else "실패"
    print(f"  {_no[0]:2d}. [{mark}] {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(f"{_no[0]}. {name} {detail}")


def decodes(b, enc):
    try:
        b.decode(enc)
        return True
    except UnicodeDecodeError:
        return False


print("=== 1. .bat 는 CP949, CRLF (UTF-8 로 바꾸지 않는다) ===")
for bat in BATS:
    b = bat.read_bytes()
    check(f"{bat.name} 는 CP949 (UTF-8 이 아님)", decodes(b, "cp949") and not decodes(b, "utf-8"))
    check(f"{bat.name} 줄 끝은 모두 CRLF (LF 만 있으면 cmd 가 줄을 잘못 읽는다)", b.count(b"\n") == b.count(b"\r\n"))
    commands = [l.strip().lower() for l in b.split(b"\r\n") if not l.strip().lower().startswith(b"rem")]
    check(f"{bat.name} 에 chcp 65001 명령이 없다 (설명 줄 rem 은 뺀다)", not any(l.startswith(b"chcp 65001") for l in commands))

print("=== 1-2. 관리 화면 bat 은 영문만 (한글이 없으면 CP949·UTF-8 어느 쪽으로 읽어도 같다 - 2026-10-06) ===")
admin_bat = ROOT / "firebase" / "admin" / "AFTERMARKET_SETUP.bat"
b = admin_bat.read_bytes() if admin_bat.exists() else b"\xff"
check("AFTERMARKET_SETUP.bat 는 영문만 (ASCII)", all(c < 128 for c in b))
check("AFTERMARKET_SETUP.bat 줄 끝은 모두 CRLF", b.count(b"\n") == b.count(b"\r\n") and b.count(b"\n") > 0)

print("=== 2. 안내 문서는 UTF-8 (BOM 포함) ===")
for g in GUIDES:
    b = g.read_bytes()
    check(f"{g.name} 는 BOM 있는 UTF-8", b.startswith(b"\xef\xbb\xbf") and decodes(b[3:], "utf-8"))

print("=== 3. Run_All.bat 를 가짜 exe 로 실제 실행 ===")
tmp = tempfile.mkdtemp(prefix="rpa_bat_")
shutil.copy2(ROOT / "Run_All.bat", os.path.join(tmp, "Run_All.bat"))
where = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "where.exe")   # 인수가 틀리면 곧바로 끝난다
for name in ("Prepare_RPA.exe", "ERPia_RPA.exe"):
    shutil.copy2(where, os.path.join(tmp, name))
r = subprocess.run(["cmd.exe", "/c", os.path.join(tmp, "Run_All.bat")], cwd=tmp, stdin=subprocess.DEVNULL,
                   capture_output=True, creationflags=subprocess.CREATE_NEW_CONSOLE, timeout=60)
shutil.rmtree(tmp, ignore_errors=True)
text, errs = r.stdout.decode("cp949", "replace"), r.stderr.decode("cp949", "replace")   # CP949 명령 창은 CP949 로 찍는다
for want in ("1/2  프리페어 RPA - 메일 첨부파일 내려받기", "[경고] 프리페어 RPA 가 정상 종료하지 않았습니다. 코드=",
             "2/2  루틴 RPA - ERPia 처리", "끝났습니다.  프리페어="):     # 가짜 exe 의 종료 코드(1·2)는 보지 않는다
    check(f"한글 줄이 그대로 찍힌다: {want[:24]}…", want in text, text[-300:])
check("명령 창 오류가 한 줄도 없다 (줄 조각이 명령으로 실행되면 여기 찍힌다)", errs.strip() == "", errs[-300:])

print("=== 4. 설치 파일 스크립트는 BOM 있는 UTF-8 ===")
for s in (ROOT / "release" / "installer.iss", ROOT / "tools" / "sandbox_inner.ps1"):
    if s.exists():
        b = s.read_bytes()
        check(f"{s.name} 는 BOM 있는 UTF-8 (Inno Setup·PowerShell 5.1 이 한글을 그렇게 읽는다)",
              b.startswith(b"\xef\xbb\xbf") and decodes(b[3:], "utf-8"))

print()
print(f"실패: {'없음' if not fails else fails}")
sys.exit(1 if fails else 0)
