# -*- coding: utf-8 -*-
"""설치 파일의 버전 종류 (스탠드얼론 계획 ③ Task 5) - release/installer.iss 하나를 /DEdition 으로 가른다.
글자 검사 + 작은 전처리 흉내로 버전 종류마다 남는 줄을 보고, ISCC 로 가짜 버전 폴더에 대고 셋(일반·스탠드얼론·시험용)을 컴파일해 본다
(만든 설치 파일은 돌리지 않는다).

    D:/AX/RPA/.venv/Scripts/python.exe tests/test_installer_edition.py
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.stdout.reconfigure(encoding="utf-8")

import build_release as br  # noqa: E402

fails = []
_no = [0]


def check(name, cond, detail=""):
    _no[0] += 1
    print(f"  {_no[0]:2d}. [{'통과' if cond else '실패'}] {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(f"{_no[0]}. {name} {detail}")


CLOUD_ID = "{{C3F7A2B4-5E81-4D2A-9B6C-7A1E0F3D8B52}"
SA_ID = "{{7D2E9A61-3B4F-4C8D-A5E2-91F0C6B3D7A4}"
raw = (ROOT / "release" / "installer.iss").read_bytes()
iss = raw.decode("utf-8-sig")


def preprocess(text, defines):
    """ISPP 흉내: #if Edition == "x" / #ifdef / #ifndef / #else / #endif 만. 남는 줄 (지시문 줄은 뺀다)."""
    out, stack = [], []
    for line in text.splitlines():
        s = line.strip()
        m = re.fullmatch(r'#if\s+(\w+)\s*==\s*"([^"]*)"', s)
        if m:
            stack.append(defines.get(m.group(1)) == m.group(2))
        elif s.startswith("#ifdef "):
            stack.append(s.split()[1] in defines)
        elif s.startswith("#ifndef "):
            stack.append(s.split()[1] not in defines)
        elif s == "#else":
            stack[-1] = not stack[-1]
        elif s == "#endif":
            stack.pop()
        elif s.startswith("#"):
            continue
        elif all(stack):
            out.append(line)
    assert not stack, "#if 와 #endif 의 짝이 맞지 않는다"
    return "\n".join(out)


print("=== 1. 글자 ===")
check("installer.iss 는 BOM 있는 UTF-8", raw.startswith(b"\xef\xbb\xbf"))
check("Edition 이 없으면 cloud", re.search(r'#ifndef Edition\s*\n\s*#define Edition "cloud"', iss) is not None)
cloud = preprocess(iss, {"Edition": "cloud"})
sa = preprocess(iss, {"Edition": "standalone"})
sat = preprocess(iss, {"Edition": "standalone", "TestBuild": "1"})
check("AppId: 일반은 지금 값, 스탠드얼론은 못박은 다른 값", f"AppId={CLOUD_ID}" in cloud and f"AppId={SA_ID}" not in cloud
      and f"AppId={SA_ID}" in sa and f"AppId={CLOUD_ID}" not in sa and CLOUD_ID != SA_ID)
check("앱 및 기능 이름: 일반 '오토파일럿', 스탠드얼론 '오토파일럿 스탠드얼론', 시험용은 ' (시험용)'",
      'MyAppName "오토파일럿"' in iss and 'MyAppName "오토파일럿 스탠드얼론"' in iss and 'MyAppName "오토파일럿 스탠드얼론 (시험용)"' in iss
      and "AppName={#MyAppName}" in cloud and "UninstallDisplayName={#MyAppName}" in cloud and "AppVerName={#MyAppName} {#AppVersion}" in cloud)
check("설치 폴더·시작 메뉴 이름은 두 버전 종류가 같다", all("DefaultDirName={commonpf64}\\AFTER MARKET\\RPA" in t and "DefaultGroupName=오토파일럿" in t
                                               for t in (cloud, sa)))
dir_line = '{commonappdata}\\AFTER MARKET\\RPA\\standalone"; Flags: uninsneveruninstall'
check("standalone 폴더는 스탠드얼론 가지에만 (지울 때 남김)", dir_line in sa and dir_line not in cloud)
check("스탠드얼론은 안내 파일 둘을 통째 복사에서 뺀다",
      'Excludes: "\\RPA_UserConfig.json,\\배포안내_스탠드얼론.txt,\\PC번호_확인.bat"' in sa
      and 'Excludes: "\\RPA_UserConfig.json,\\배포안내.txt,\\클라우드_안내.txt"' in cloud)
run_lines = [l for l in iss.splitlines() if "rpa_settings.py" in l and "--after-install" in l]
check("[Run] 의 설정 창 두 줄은 가지 밖에 한 벌 (두 버전 종류 모두 같은 줄)", len(run_lines) == 2
      and all(l in cloud and l in sa for l in run_lines), str(run_lines))
SA_MSG = "이 PC 에는 오토파일럿 일반 버전이 설치되어 있습니다. 스탠드얼론 버전은 일반 버전이 없는 PC 에만 설치할 수 있습니다."
CLOUD_MSG = "이 PC 에는 오토파일럿 스탠드얼론 버전이 설치되어 있습니다. 일반 버전은 스탠드얼론 버전이 없는 PC 에만 설치할 수 있습니다."
TEST_MSG = "시험용 빌드입니다. 고객 PC 에 설치하지 마십시오. 계속하시겠습니까?"
UNINSTALL_SA = "지우면 저장된 비밀번호·프리셋·실행 기록·라이선스·웹 계정이 모두 없어집니다. 다시 설치해서 계속 쓰려면 [아니요] 를 누르세요."
check("다른 버전 종류가 깔린 PC 알림: 스탠드얼론 설치 파일·일반 설치 파일 각자", SA_MSG in sa and CLOUD_MSG not in sa and CLOUD_MSG in cloud
      and SA_MSG not in cloud)
check("시험용이면 설치 시작 알림 (조용한 설치가 아닐 때)", TEST_MSG in sat and TEST_MSG not in sa and TEST_MSG not in cloud
      and "WizardSilent" in sat[sat.find("function InitializeSetup"):])
check("지울 때 묻는 글 (스탠드얼론은 라이선스·웹 계정까지)", UNINSTALL_SA in sa and UNINSTALL_SA not in cloud
      and "지우면 저장된 비밀번호·프리셋·실행 기록이 모두 없어집니다." in cloud)
init = sa[sa.find("function OtherEditionInstalled"):sa.find("function InitializeSetup")]
check("가리는 법: 상대 AppId 의 제거 등록 키(64비트 보기) 또는 프로그램 폴더의 manifest.json·edition.json",
      "HKLM64" in init and "_is1" in init and "manifest.json" in init and "not FileExists(Dir + '\\edition.json')" in init
      and "FileExists(Dir + '\\edition.json')" in cloud[cloud.find("function OtherEditionInstalled"):], init[:400])
check("일반 설치 파일이 보는 상대는 스탠드얼론 AppId, 그 반대도", "'{7D2E9A61-3B4F-4C8D-A5E2-91F0C6B3D7A4}'" in cloud.split("function")[0] + cloud
      and "OTHER_APPID = '{7D2E9A61-3B4F-4C8D-A5E2-91F0C6B3D7A4}'" in cloud and "OTHER_APPID = '{C3F7A2B4-5E81-4D2A-9B6C-7A1E0F3D8B52}'" in sa)
check("InitializeSetup 이 False 면 설치 파일은 시작 전에 멈춘다 (다른 버전 종류)",
      re.search(r"if OtherEditionInstalled\(\) then\s+begin\s+SuppressibleMsgBox\(OTHER_EDITION_TEXT", sa) is not None)
for rel, src in br.other_files("standalone"):
    check(f"안내 파일 원본이 저장소에 있다: {src}", (ROOT / src).is_file())

print("=== 2. 배포 안내 (우리 쪽 담당자용) ===")
guide_b = (ROOT / "release" / "배포안내_스탠드얼론.txt").read_bytes() if (ROOT / "release" / "배포안내_스탠드얼론.txt").exists() else b""
guide = guide_b.decode("utf-8-sig", "replace")
check("BOM 있는 UTF-8", guide_b.startswith(b"\xef\xbb\xbf"))
for word in ("PC번호_확인.bat", "make_license.py", "라이선스", "관리자 계정", "덮어 설치", "같은 버전 설치 파일로 다시 설치",
             "윈도우를 다시", "관리자 비밀번호 다시 정하기", "일반 버전", "TEST"):
    check(f"안내에 '{word}'", word in guide)
check("안내에 '판'·'묶음'·'권고' 낱말이 없다", not re.search(r"(?<![가-힣])판(?![가-힣])|묶음|권고", guide))

print("=== 3. ISCC 로 셋 다 컴파일된다 (가짜 버전 폴더) ===")
iscc = br.find_iscc()
check("이 PC 에 Inno Setup", iscc is not None)
if iscc:
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "배포_시험")
        for rel in ("RPA_UserConfig.json", "배포안내_스탠드얼론.txt", "PC번호_확인.bat", "rpa_settings.py", "manifest.json", "edition.json",
                    "python/python.exe", "python/pythonw.exe", "firebase/agent/background.py"):
            os.makedirs(os.path.dirname(os.path.join(src, *rel.split("/"))), exist_ok=True)
            with open(os.path.join(src, *rel.split("/")), "wb") as f:
                f.write(b"x")
        for edition, test in (("cloud", False), ("standalone", False), ("standalone", True)):
            cmd = br.iscc_command(iscc, src, "2026.11.24-99", out_root=d, edition=edition, test=test)
            r = subprocess.run(cmd, capture_output=True, timeout=300)
            out = os.path.join(d, br.setup_name("2026.11.24-99", edition, test))
            check(f"{edition}{' 시험용' if test else ''} 설치 파일이 컴파일된다", r.returncode == 0 and os.path.isfile(out),
                  (r.stdout + r.stderr)[-600:].decode("utf-8", "replace"))

print()
print(f"실패: {'없음' if not fails else fails}")
sys.exit(1 if fails else 0)
