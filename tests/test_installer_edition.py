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


sys.path.insert(0, str(ROOT / "tests"))
from iss_view import preprocess  # noqa: E402
import rpa_status as st  # noqa: E402

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
# 폴더 나누기 (사용자 2026-11-23): ISCC 가 만드는 글처럼 {#…} 를 펼쳐 본다
cloud_x = preprocess(iss, {"Edition": "cloud"}, expand=True)
sa_x = preprocess(iss, {"Edition": "standalone"}, expand=True)
cloud_lines, sa_lines = cloud_x.splitlines(), sa_x.splitlines()
# 고치기 전(15a41ee) 일반 설치 파일의 자리 줄 - 한 글자도 바뀌면 안 된다 (이미 깔린 PC 가 그 자리를 쓴다)
OLD_CLOUD_LINES = [
    "DefaultDirName={commonpf64}\\AFTER MARKET\\RPA",
    "DefaultGroupName=오토파일럿",
    'Name: "{commonappdata}\\AFTER MARKET\\RPA\\config"; Flags: uninsneveruninstall',
    'Name: "{commonappdata}\\AFTER MARKET\\RPA\\data"; Flags: uninsneveruninstall',
    'Filename: "{sys}\\icacls.exe"; Parameters: """{commonappdata}\\AFTER MARKET\\RPA"" /setowner *S-1-5-32-544 /T /C /Q"; Flags: runhidden waituntilterminated; StatusMsg: "설정 폴더를 관리자만 열 수 있게 막는 중..."',
    'Filename: "{sys}\\icacls.exe"; Parameters: """{commonappdata}\\AFTER MARKET\\RPA"" /reset /C /Q"; Flags: runhidden waituntilterminated; StatusMsg: "설정 폴더를 관리자만 열 수 있게 막는 중..."',
    'Filename: "{sys}\\icacls.exe"; Parameters: """{commonappdata}\\AFTER MARKET\\RPA"" /inheritance:r /grant:r *S-1-5-32-544:(OI)(CI)F *S-1-5-18:(OI)(CI)F"; Flags: runhidden waituntilterminated; StatusMsg: "설정 폴더를 관리자만 열 수 있게 막는 중..."',
    'Filename: "{sys}\\icacls.exe"; Parameters: """{commonappdata}\\AFTER MARKET\\RPA\\*"" /reset /T /C /Q"; Flags: runhidden waituntilterminated; StatusMsg: "설정 폴더를 관리자만 열 수 있게 막는 중..."',
    "    Data := ExpandConstant('{commonappdata}\\AFTER MARKET\\RPA');",
    'Name: "{group}\\오토파일럿 설정"; Filename: "{app}\\python\\pythonw.exe"; Parameters: "-E -s ""{app}\\rpa_settings.py"""; WorkingDir: "{app}"; Comment: "오토파일럿 설정 창 (관리자 권한 요청이 뜹니다)"; IconFilename: "{app}\\AFTER_MARKET.ico"; AppUserModelID: "AFTERMARKET.RPA.Settings"',
    "Type: dirifempty; Name: \"{commonpf64}\\AFTER MARKET\"",
]
missing = [ln for ln in OLD_CLOUD_LINES if ln not in cloud_lines]
check("일반 설치 파일: 설치 폴더·시작 메뉴·설정 폴더·권한·제거 자리 줄이 예전 글자 그대로 (펼친 뒤)", not missing, str(missing))
check("일반 설치 파일: UsePreviousAppDir 줄이 없다 (예전처럼 깔린 자리를 물려받는다)", "UsePreviousAppDir" not in cloud_x)
check("일반 설치 파일: 'RPA Standalone' 은 상대 폴더를 보는 줄에만",
      all("OtherSub" in ln or "manifest.json" in ln for ln in cloud_lines if "RPA Standalone" in ln and not ln.strip().startswith(("//", ";"))),
      str([ln for ln in cloud_lines if "RPA Standalone" in ln]))
SA_DIR_LINES = [
    "DefaultDirName={commonpf64}\\AFTER MARKET\\RPA Standalone",
    "DefaultGroupName=오토파일럿 스탠드얼론",
    "UsePreviousAppDir=no",
    'Name: "{commonappdata}\\AFTER MARKET\\RPA Standalone\\config"; Flags: uninsneveruninstall',
    'Name: "{commonappdata}\\AFTER MARKET\\RPA Standalone\\data"; Flags: uninsneveruninstall',
    "    Data := ExpandConstant('{commonappdata}\\AFTER MARKET\\RPA Standalone');",
]
missing = [ln for ln in SA_DIR_LINES if ln not in sa_lines]
check("스탠드얼론 설치 파일: 프로그램 폴더 ...\\RPA Standalone · 시작 메뉴 '오토파일럿 스탠드얼론' · 설정 폴더 · 지울 때 묻는 자리", not missing, str(missing))
icacls_sa = [ln for ln in sa_lines if "icacls.exe" in ln]
check("스탠드얼론 설치 파일: 권한 잠그기 네 줄 모두 새 설정 폴더 (일반 설정 폴더를 건드리지 않는다)",
      len(icacls_sa) == 4 and all('{commonappdata}\\AFTER MARKET\\RPA Standalone' in ln for ln in icacls_sa), str(icacls_sa))
old_place = re.compile(r"AFTER MARKET\\RPA(?! Standalone)(?=[\\'\"])")
stray = [ln for ln in sa_lines if old_place.search(ln) and not ln.strip().startswith(("//", ";"))
         and not any(k in ln for k in ("manifest.json", "edition.json", "OLD_PLACE_TEXT"))]
check("스탠드얼론 설치 파일: 일반 폴더(...\\RPA)는 다른 버전 종류를 알아보는 줄에서만 본다", not stray, str(stray))
pd_names = re.findall(r'#define ProductSub "([^"]+)"', iss)
check("ProductSub = rpa_status 의 폴더 이름 (일반 PRODUCT_DIRS, 스탠드얼론 STANDALONE_DIRS)",
      pd_names == [st.STANDALONE_DIRS[1], st.PRODUCT_DIRS[1]] and st.PRODUCT_DIRS[0] == st.STANDALONE_DIRS[0] == "AFTER MARKET", str(pd_names))
dir_line = '{commonappdata}\\AFTER MARKET\\RPA Standalone\\standalone"; Flags: uninsneveruninstall'
check("standalone 폴더는 스탠드얼론 가지에만 (지울 때 남김)", dir_line in sa_x and "\\standalone\"" not in cloud_x)
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
init = sa_x[sa_x.find("function OtherEditionInstalled"):sa_x.find("function InitializeSetup")]
init_c = cloud_x[cloud_x.find("function OtherEditionInstalled"):cloud_x.find("function InitializeSetup")]
check("가리는 법 (스탠드얼론 설치 파일): 일반 AppId 의 제거 등록 키(64비트 보기) 또는 일반 폴더의 manifest.json",
      "HKLM64" in init and "_is1" in init and "FileExists(ExpandConstant('{commonpf64}\\AFTER MARKET\\RPA\\manifest.json'))" in init, init[:500])
check("가리는 법 (일반 설치 파일): 스탠드얼론 AppId 의 등록 키 또는 스탠드얼론 새 폴더의 manifest.json, 그리고 나누기 전 자리(...\\RPA)의 edition.json",
      "HKLM64" in init_c and "FileExists(ExpandConstant('{commonpf64}\\AFTER MARKET\\RPA Standalone\\manifest.json'))" in init_c
      and "Dir := ExpandConstant('{commonpf64}\\AFTER MARKET\\RPA');" in init_c and "Result := FileExists(Dir + '\\edition.json');" in init_c, init_c[:700])
OLD_MSG = "이 PC 에는 예전 자리(C:\\Program Files\\AFTER MARKET\\RPA)에 오토파일럿 스탠드얼론이 설치되어 있습니다. 앱 및 기능에서 먼저 제거한 뒤 다시 설치하세요."
setup_sa = sa_x[sa_x.find("function InitializeSetup"):sa_x.find("function RunSettings")]
check("스탠드얼론 설치 파일: 나누기 전 자리(...\\RPA\\edition.json)에 깔린 시험용 빌드가 있으면 먼저 지우라고 멈춘다 (일반 버전 알림보다 먼저)",
      OLD_MSG in sa_x and OLD_MSG not in cloud_x and "function OldPlaceInstalled" in sa_x and "OldPlaceInstalled" not in cloud_x
      and "FileExists(ExpandConstant('{commonpf64}\\AFTER MARKET\\RPA\\edition.json'))" in sa_x
      and 0 < setup_sa.find("if OldPlaceInstalled() then") < setup_sa.find("if OtherEditionInstalled() then"), setup_sa[:600])
check("일반 설치 파일이 보는 상대는 스탠드얼론 AppId, 그 반대도", "'{7D2E9A61-3B4F-4C8D-A5E2-91F0C6B3D7A4}'" in cloud.split("function")[0] + cloud
      and "OTHER_APPID = '{7D2E9A61-3B4F-4C8D-A5E2-91F0C6B3D7A4}'" in cloud and "OTHER_APPID = '{C3F7A2B4-5E81-4D2A-9B6C-7A1E0F3D8B52}'" in sa)
check("InitializeSetup 이 False 면 설치 파일은 시작 전에 멈춘다 (다른 버전 종류)",
      re.search(r"if OtherEditionInstalled\(\) then\s+begin\s+SuppressibleMsgBox\(OTHER_EDITION_TEXT", sa) is not None)
for rel, src in br.other_files("standalone"):
    check(f"안내 파일 원본이 저장소에 있다: {src}", (ROOT / src).is_file())
# 휴대폰 창구 (계획 ④): 제거 때 방화벽 규칙을 지우고, 덮어 설치는 standalone 폴더(인증서·짝지은 휴대폰)를 건드리지 않는다
fw_line = 'Filename: "{sys}\\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""AUTOPILOT Phone OTP"""'
check("스탠드얼론 제거 때 휴대폰 방화벽 규칙을 지운다 ([UninstallRun] netsh, 일반 버전엔 없음)",
      "[UninstallRun]" in sa and fw_line in sa and fw_line not in cloud and "[UninstallRun]" not in cloud)
# 사내 서버 ⑤ Task 7: 제거 때 설정 창이 우리가 신뢰 저장소에 넣은 사내 서버 인증 기관만 지운다 (rpa_settings --uninstall-cleanup)
ca_line = re.search(r'^Filename: "\{app\}\\python\\python\.exe"; Parameters: "-E -s ""\{app\}\\rpa_settings\.py"" --uninstall-cleanup";.*$',
                    sa, re.M)
check("스탠드얼론 제거 때 --uninstall-cleanup (창 없이·기다림·한 번만), 일반 버전엔 없음",
      ca_line is not None and "runhidden" in ca_line.group(0) and "waituntilterminated" in ca_line.group(0)
      and "RunOnceId:" in ca_line.group(0) and "--uninstall-cleanup" not in cloud, ca_line.group(0) if ca_line else None)
inst_del = sa[sa.find("[InstallDelete]"):sa.find("[Files]")]
check("덮어 설치가 standalone 폴더를 지우지 않는다 (InstallDelete·UninstallDelete 에 없음, 폴더는 uninsneveruninstall)",
      "standalone" not in inst_del and "standalone" not in sa[sa.find("[UninstallDelete]"):sa.find("[Code]")] and dir_line in sa_x)
check("배포 파일 목록에 휴대폰 창구 파일 (local_phone·local_cert·qr.js·vendor/qrcode.js·라이선스 글)",
      {"firebase/agent/local_phone.py", "firebase/agent/local_cert.py", "firebase/web/qr.js", "firebase/web/phone-card.js",
       "firebase/web/vendor/qrcode.js", "firebase/web/vendor/LICENSE-qrcode-generator.txt"} <= {r for r, _ in br.program_files("standalone")})

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
