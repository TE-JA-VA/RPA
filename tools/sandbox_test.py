r"""설치 파일을 윈도우 샌드박스에서 시험한다 (설계 9절). 이 PC 에는 설치하지 않는다.

    .venv\Scripts\python.exe tools\sandbox_test.py [--update] [--runtime <폴더>] [--from <옛 판 설치 파일>] D:\AX\AFTER_MARKET_RPA_Setup_<판>.exe

윈도우 샌드박스 기능이 켜져 있어야 한다 (관리자 PowerShell: Enable-WindowsOptionalFeature -Online
-FeatureName Containers-DisposableClientVM -All, 재부팅). 샌드박스 안에서 tools\sandbox_inner.ps1 이 조용한 설치 →
확인 → 가짜 설정으로 에이전트 → 다시 설치 → 설정 창 사진 → 조용한 제거를 하고 결과를 적은 뒤 샌드박스를 끈다.
결과는 임시 폴더의 out\results.txt·settings.png·setup*.log·agent_log1.txt. 샌드박스 안의 인터넷을 쓴다
(에이전트가 가짜 에이전트 계정으로 로그인을 한 번 시도해 거부당한다).

--update: 같은 판의 배포 폴더(D:\AX\배포_<판>)로 판 B(rpa_dashboard.py 한 줄 더)·판 C(켜지지 않는 에이전트)를 만들어
시험용 열쇠로 서명해 작업 폴더의 site\ 에 넣는다. 샌드박스 안에서 가짜 호스팅으로 업데이트·되돌리기·켜지지 않는 판·
도중 끊김을 시험한다 (설계 12절). 시험용 비밀 열쇠는 서명 뒤 지우고 공개 열쇠만 site\pub.txt 에 둔다.
--from <옛 판 설치 파일>: 그 옛 판을 깔고 판 B = 새 판 그대로로 업데이트한다 (구조가 바뀐 판으로 넘어가는 전환 시험).
--runtime <python.exe 가 든 폴더>: --update 에 더해, 내장 파이썬을 그 폴더 것으로 바꾼 판 R·RC(켜지지 않음)를 만들어
업데이트 → 되돌리기 → 켜지지 않는 판의 자동 되돌림에서 python 폴더까지 바뀌고 돌아오는지 본다 (설계 2026-11-20).
--offline: 샌드박스의 네트워크를 끈다 (<Networking>Disable</Networking>) - 실서버에 가짜 계정 로그인도 보내지 않는다.
    샌드박스 안 스크립트는 '인터넷 없음' 쪽을 본다 (에이전트가 죽지 않고 다시 붙으려 한다).

스탠드얼론 (계획 docs/superpowers/plans/2026-11-23-standalone-3-install-build.md Task 6):
    .venv\\Scripts\\python.exe tools\\sandbox_test.py --standalone [--cloud-setup <일반 설치 파일>] [--over-cloud <일반 설치 파일>]
        D:\\AX\\스탠드얼론\\AUTOPILOT_Standalone_TEST_Setup_<v>.exe
(스탠드얼론 빌드 결과는 D:\\AX\\스탠드얼론\\ 에 있다 - 폴더 나누기 2026-11-23. 샌드박스 안에서는 Program Files·ProgramData 의
AFTER MARKET\\RPA Standalone 에 깔리고, 일반 폴더 AFTER MARKET\\RPA 는 생기지 않아야 한다)
시험용 빌드(--test-build)의 설치 파일만 받는다 (이름에 TEST, 옆에 배포_SA_TEST_<v>.testkey.txt). 그 열쇠로 샌드박스 PC 번호
(SANDBOX_GUID)의 라이선스를 만들어 넣고 (열쇠 파일 자체는 넣지 않는다) tools\\sandbox_inner_standalone.ps1 이 설치·라이선스·
로그인·명령·기록·변조·덮어 설치·제거와 막은 주소로의 연결 시도(덫)를 본다.
정식 빌드(고객용, AUTOPILOT_Standalone_Setup_<v>.exe - 2026-11-24):
    ... --standalone --guid <이번만 쓰는 무작위 PC 번호> --license <그 번호의 license.json>
        --license-other <다른 무작위 번호의 license.json> [--test-key <시험용 빌드의 .testkey.txt>] <설치 파일>
    라이선스는 make_license.py 로 미리 발급해 넘긴다 (이 도구는 진짜 라이선스 열쇠를 읽지 않는다). 고정된 SANDBOX_GUID 는 받지 않는다.
사내 서버 등록 (사내 서버 ⑤ Task 8 - 시험용 빌드, NT 가 같은 시험 열쇠 서버 빌드):
    ... --standalone [--test-key <NT 시험 열쇠 파일>] --lan-enroll <업체 웹 [PC 추가] 의 등록 글을 담은 파일> <시험용 설치 파일>
    PC 시험 빌드는 build_release --test-build --license-key <NT 시험 열쇠 파일> 로 만든다 (서버 라이선스와 같은 열쇠 - 옆에 .testkey.txt
    가 없으므로 단독 회귀 시험에도 --test-key 로 같은 파일을 준다)
    tools\\sandbox_inner_lan.ps1 이 설치 → 등록·저장 → 에이전트가 붙는지까지 보고 out\\ready.txt 를 쓴 뒤 켜 둔다 (업체 웹에서 실행·사용 중지·
    지우기를 해 보는 동안 out\\status.json). 작업 폴더에 end.txt 를 만들면 끝낸다. 등록 글은 파일로만 넘기고 샌드박스 안에서 쓰고 지운다.
    '시험용' 표시(앱 이름·설정 창 제목·웹 띠)가 없는지, 시험 열쇠로 같은 번호에 서명한 라이선스가 거절되는지도 본다.
    끝나면 license*.json 이 든 작업 폴더를 지우는 것은 부르는 쪽 몫이다 (결과 폴더 위치를 찍는다).
--cloud-setup: 스탠드얼론이 깔린 PC 에서 일반 설치 파일이 멈추는지도 본다.
--over-cloud: 일반 버전을 먼저 깔고 스탠드얼론 설치 파일이 멈추는지만 본다.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
for _p in (REPO, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)
SANDBOX = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsSandbox.exe")
WSB = """<Configuration>
  <MappedFolders><MappedFolder><HostFolder>{work}</HostFolder><SandboxFolder>C:\\test</SandboxFolder><ReadOnly>false</ReadOnly></MappedFolder></MappedFolders>
  <LogonCommand><Command>powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\\test\\inner.ps1</Command></LogonCommand>
  <MemoryInMB>4096</MemoryInMB>
{extra}</Configuration>
"""
OFFLINE = "  <Networking>Disable</Networking>\n"

# 스탠드얼론 (계획 ③ Task 6)
SANDBOX_GUID = "5a17db0c-0000-4000-8000-000000000001"     # 샌드박스 안에서 MachineGuid 를 이 값으로 바꾼다
OTHER_GUID = "5a17db0c-0000-4000-8000-0000000000ff"       # 다른 PC 의 라이선스 (license_other.json)
SBX_COMPANY = {"company": "샌드박스상사", "cid": "c_sbx", "limits": {"schedule": 3}}
TRAP_IP = "127.0.0.2"
TEST_ONLY = "시험용 빌드(--test-build)로 만든 설치 파일만 시험합니다"
SA_SETUP_RE = re.compile(r"AUTOPILOT_Standalone_TEST_Setup_(.+)\.exe$")
OFFICIAL_SETUP_RE = re.compile(r"AUTOPILOT_Standalone_Setup_(.+)\.exe$")    # 정식 빌드 (고객용, 2026-11-24)
OFFICIAL_NEEDS = ("정식 빌드는 --guid <이번만 쓰는 무작위 PC 번호> --license <그 번호의 license.json> "
                  "--license-other <다른 PC 번호의 license.json> 이 필요합니다 (make_license.py 로 발급)")
OFFICIAL_GUID = "정식 빌드의 --guid 는 이번 실행만 쓰는 무작위 PC 번호여야 합니다 (고정된 샌드박스 번호는 안 됩니다)"
SA_FILES = {"inner.ps1": "sandbox_inner_standalone.ps1", "trap.ps1": "sandbox_trap.ps1",
            "check_standalone.py": "sandbox_check_standalone.py"}     # 작업 폴더 이름 → tools\ 의 원본


def BLOCK_HOSTS(info=None):                                  # noqa: N802 (계획서의 이름)
    """샌드박스에서 덫(127.0.0.2)으로 돌릴 주소 - server_info 값으로 만든다 (주소를 옮겨도 따라간다).
    gstatic 은 넣지 않는다 (윈도우·Edge 가 연결 확인에 쓰는 주소 - 우리 코드와 상관없는 시도가 덫에 걸린다)."""
    import urllib.parse
    if info is None:
        import server_info as info
    pid = info.PROJECT_ID
    out = [urllib.parse.urlsplit(info.DATABASE_URL).hostname, info.AUTH_HOST, info.TOKEN_HOST, info.FIRESTORE_HOST,
           f"{pid}.web.app", f"{pid}-releases.web.app", f"{pid}.firebaseapp.com",
           "api.anthropic.com", "fonts.googleapis.com", "cdn.jsdelivr.net"]
    for url in (info.DASHBOARD_URL, info.UPDATE_BASE_URL, *info.UPDATE_FALLBACK_URLS):
        out.append(urllib.parse.urlsplit(url).hostname)
    seen = []
    for h in out:
        if h and h not in seen:
            seen.append(h)
    return seen


OUT_ROOTS = {"배포_": r"D:\AX", "배포_SA_": r"D:\AX\스탠드얼론", "배포_SA_TEST_": r"D:\AX\스탠드얼론"}   # build_release 의 기본 결과 자리


def find_release(setup, prefix="배포_"):
    """설치 파일의 배포 폴더: 설치 파일이 있는 폴더의 <prefix><v> 를 먼저, 없으면 그 버전 종류의 기본 결과 자리 것
    (일반 D:\\AX, 스탠드얼론 D:\\AX\\스탠드얼론 - --out-root 로 만든 빌드도 시험한다).
    못 찾으면 그 이름의 기본 자리 (부르는 쪽이 manifest.json 으로 확인한다)."""
    m = re.search(r"Setup_(.+)\.exe$", os.path.basename(setup))
    if not m:
        return ""
    name = f"{prefix}{m.group(1)}"
    near = os.path.join(os.path.dirname(os.path.abspath(setup)), name)
    return near if os.path.isfile(os.path.join(near, "manifest.json")) else os.path.join(OUT_ROOTS.get(prefix, r"D:\AX"), name)


def test_key_path(setup):
    """시험용 빌드 설치 파일 옆의 시험용 라이선스 열쇠 자리 (없으면 "")."""
    m = SA_SETUP_RE.search(os.path.basename(setup))
    if not m:
        return ""
    return os.path.join(os.path.dirname(os.path.abspath(setup)), f"배포_SA_TEST_{m.group(1)}.testkey.txt")


def _fill_work(setup, work, guid, expect, cloud_setup=None, over_cloud=None):
    """두 빌드 종류가 함께 쓰는 작업 폴더 채우기: setup.exe·안쪽 스크립트 셋·hosts_block.txt·guid.txt·expect.json(무엇을 기대하나)."""
    os.makedirs(work, exist_ok=True)
    shutil.copy2(setup, os.path.join(work, "setup.exe"))
    for dst, src in SA_FILES.items():
        shutil.copy2(os.path.join(HERE, src), os.path.join(work, dst))
    with open(os.path.join(work, "hosts_block.txt"), "w", encoding="ascii", newline="\r\n") as f:
        f.write("".join(f"{TRAP_IP} {h}\n" for h in BLOCK_HOSTS()))
    with open(os.path.join(work, "guid.txt"), "w", encoding="ascii") as f:
        f.write(guid + "\n")
    with open(os.path.join(work, "expect.json"), "w", encoding="utf-8") as f:
        json.dump(expect, f, ensure_ascii=False)
    for src, name in ((cloud_setup, "cloud_setup.exe"), (over_cloud, "over_cloud.exe")):
        if src:
            shutil.copy2(src, os.path.join(work, name))
    return work


def prepare_standalone(setup, work, cloud_setup=None, over_cloud=None, key_file=None):
    """스탠드얼론 샌드박스 작업 폴더를 채운다: setup.exe·inner.ps1·trap.ps1·check_standalone.py·license.json(샌드박스 PC 번호)·
    license_other.json(다른 PC 번호)·hosts_block.txt·guid.txt·expect.json, 주면 cloud_setup.exe / over_cloud.exe.
    시험용 빌드가 아니면 (이름에 TEST 가 없거나 옆에 열쇠 파일이 없으면) ValueError(TEST_ONLY). 열쇠 파일은 작업 폴더에 넣지 않는다.
    key_file 을 주면 옆 열쇠 대신 그것 (build_release --license-key 로 만든 빌드 - 끝 검토 Codex 4)."""
    key_file = key_file or test_key_path(setup)
    if not key_file or not os.path.isfile(key_file):
        raise ValueError(TEST_ONLY)
    import license_check
    import make_license
    with open(key_file, encoding="ascii") as f:
        secret = bytes.fromhex(f.read().strip())
    _fill_work(setup, work, SANDBOX_GUID, {"official": False, "company": SBX_COMPANY["company"], "cid": SBX_COMPANY["cid"]},
               cloud_setup, over_cloud)
    for name, guid in (("license.json", SANDBOX_GUID), ("license_other.json", OTHER_GUID)):
        doc = license_check.sign_body(secret, make_license.build_body(guid, SBX_COMPANY))
        with open(os.path.join(work, name), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
    return work


def prepare_official(setup, work, guid, lic, lic_other, test_key=None, cloud_setup=None, over_cloud=None):
    """정식 빌드(고객용)의 작업 폴더. 라이선스는 make_license.py 로 미리 발급한 파일을 받는다 - 이 도구는 진짜 라이선스 열쇠를 읽지 않는다.
    guid 는 이번 실행만 쓰는 무작위 PC 번호여야 한다 (고정된 SANDBOX_GUID·OTHER_GUID 로 진짜 라이선스를 만들면 누구나 그 번호로
    바꿔 쓸 수 있다). lic 은 guid 로, lic_other 는 다른 PC 번호로 실린 공개 열쇠에 통과해야 한다 - 아니면 ValueError.
    license_testkey.json = 시험용 열쇠(test_key 파일, 없으면 그 자리에서 만든 열쇠)로 같은 guid 에 서명한 것 - 정식 빌드에서 거절돼야 한다."""
    import license_check
    import make_license
    import update_sign
    guid = str(guid or "").strip().lower()
    if not make_license.PC_ID.match(guid) or guid in (SANDBOX_GUID, OTHER_GUID):
        raise ValueError(OFFICIAL_GUID)
    try:
        body = license_check.load(path=lic, guid=guid)
        other = license_check.load(path=lic_other, guid=json.load(open(lic_other, encoding="utf-8-sig"))["body"]["pc_id"])
    except (license_check.LicenseError, OSError, ValueError, KeyError, TypeError) as e:
        raise ValueError(f"라이선스 파일이 이 빌드의 공개 열쇠·PC 번호에 맞지 않습니다: {e}") from None
    if str(other.get("pc_id")).lower() == guid:
        raise ValueError("--license-other 는 다른 PC 번호의 라이선스여야 합니다")
    if test_key:
        with open(test_key, encoding="ascii") as f:
            secret = bytes.fromhex(f.read().strip())
    else:
        secret = update_sign.keygen()[0]
    _fill_work(setup, work, guid, {"official": True, "company": body["company"], "cid": body["cid"]}, cloud_setup, over_cloud)
    shutil.copy2(lic, os.path.join(work, "license.json"))
    shutil.copy2(lic_other, os.path.join(work, "license_other.json"))
    with open(os.path.join(work, "license_testkey.json"), "w", encoding="utf-8") as f:
        json.dump(license_check.sign_body(secret, make_license.build_body(guid, {"company": body["company"], "cid": body["cid"]})),
                  f, ensure_ascii=False, indent=1)
    return work


def prepare_lan(setup, work, enroll_file, key_file=None):
    """사내 서버 등록 샌드박스 (사내 서버 ⑤ Task 8): setup.exe·inner.ps1(sandbox_inner_lan.ps1)·enroll.txt(받은 등록 글 그대로).
    라이선스·열쇠 파일은 넣지 않는다. 시험용 빌드가 아니면 ValueError(TEST_ONLY) - 사내 서버도 시험 열쇠 빌드(NT)다.
    key_file(--test-key) 를 주면 옆 열쇠 대신 그 파일이 있는지 본다 (build_release --license-key 빌드).
    등록 글은 파일로만 넘긴다 (.wsb·명령 줄에 싣지 않는다). 글은 10분·한 번짜리이고, 끝나면 부르는 쪽이 작업 폴더를 지운다."""
    if not SA_SETUP_RE.search(os.path.basename(setup)) or not os.path.isfile(key_file or test_key_path(setup)):
        raise ValueError(TEST_ONLY)
    os.makedirs(work, exist_ok=True)
    shutil.copy2(setup, os.path.join(work, "setup.exe"))
    shutil.copy2(os.path.join(HERE, "sandbox_inner_lan.ps1"), os.path.join(work, "inner.ps1"))
    shutil.copy2(enroll_file, os.path.join(work, "enroll.txt"))
    return work


def write_wsb(work, offline=False):
    with open(os.path.join(work, "test.wsb"), "w", encoding="utf-8") as f:
        f.write(WSB.format(work=work, extra=OFFLINE if offline else ""))


def wait_lan(work, minutes=20):
    """사내 서버 샌드박스: 첫 확인(설치·등록·저장·에이전트가 붙음)이 끝나 out\\ready.txt 가 생기기를 기다려 결과를 찍는다 → 종료 코드.
    샌드박스는 켜 둔다 - 업체 웹에서 실행·사용 중지·지우기를 해 보는 동안 out\\status.json 이 5초마다 바뀐다.
    끝내려면 작업 폴더에 end.txt 를 만든다 (안쪽이 마지막 결과를 쓰고 샌드박스를 끈다)."""
    print(f"샌드박스를 띄웁니다 (사내 서버 등록). 결과 폴더: {work}\\out")
    subprocess.Popen([SANDBOX, os.path.join(work, "test.wsb")])
    ready, results = os.path.join(work, "out", "ready.txt"), os.path.join(work, "out", "results.txt")
    until = time.time() + minutes * 60
    while time.time() < until and not os.path.exists(ready):
        time.sleep(5)
    text = open(results, encoding="utf-8-sig").read() if os.path.exists(results) else "(결과 없음)"
    print(text)
    print(f"샌드박스는 켜 둡니다. 상태: {work}\\out\\status.json  끝내기: {work}\\end.txt 를 만드십시오.")
    return 0 if os.path.exists(ready) and "실패  " not in text else 1


def _take(args, flag):
    """args 에서 '<flag> <값>' 을 빼 값을 돌려준다 (없으면 None, 값이 없으면 "")."""
    if flag not in args:
        return None
    i = args.index(flag)
    value = args[i + 1] if i + 1 < len(args) else ""
    del args[i:i + 2]
    return value


def wait_sandbox(work, minutes):
    """샌드박스를 띄우고 done.txt 를 기다린다 → 종료 코드 (끝 줄 '실패: 0' 이면 0)."""
    wsb = os.path.join(work, "test.wsb")
    print(f"샌드박스를 띄웁니다. 결과 폴더: {work}\\out (창을 건드리지 마세요, 끝나면 저절로 닫힙니다)")
    subprocess.Popen([SANDBOX, wsb])
    done = os.path.join(work, "done.txt")
    results = os.path.join(work, "out", "results.txt")
    until = time.time() + minutes * 60
    while time.time() < until and not os.path.exists(done):
        time.sleep(5)
    text = open(results, encoding="utf-8-sig").read() if os.path.exists(results) else "(결과 없음)"
    print(text)
    return 0 if os.path.exists(done) and text.rstrip().endswith("실패: 0") else 1


def main_standalone(args, offline=False):
    cloud = _take(args, "--cloud-setup")
    over = _take(args, "--over-cloud")
    for label, path in (("--cloud-setup", cloud), ("--over-cloud", over)):
        if path is not None and not os.path.isfile(path):
            print(f"{label} 의 일반 설치 파일이 없습니다: {path}")
            return 2
    guid, lic, lic_other, test_key = (_take(args, f) for f in ("--guid", "--license", "--license-other", "--test-key"))
    lan = _take(args, "--lan-enroll")         # 사내 서버 등록 (⑤ Task 8): 업체 웹에서 받은 등록 글 파일
    if len(args) != 1 or not os.path.isfile(args[0]):
        print(__doc__)
        return 2
    if lan is not None:
        if not lan or not os.path.isfile(lan):
            print(f"--lan-enroll 의 등록 글 파일이 없습니다: {lan}")
            return 2
        if not os.path.isfile(SANDBOX):
            print("윈도우 샌드박스가 꺼져 있습니다 (위 설명의 명령으로 켜고 재부팅)")
            return 2
        work = tempfile.mkdtemp(prefix="rpa_sbx_lan_")
        try:
            prepare_lan(args[0], work, lan, key_file=test_key)
        except ValueError as e:
            print(e)
            shutil.rmtree(work, ignore_errors=True)
            return 2
        write_wsb(work, offline)
        print(f"사내 서버 등록 시험: {os.path.basename(args[0])}")
        return wait_lan(work)
    official = bool(OFFICIAL_SETUP_RE.search(os.path.basename(args[0])))
    if official and not (guid and lic and lic_other and os.path.isfile(lic) and os.path.isfile(lic_other)
                         and (test_key is None or os.path.isfile(test_key))):
        print(OFFICIAL_NEEDS)
        return 2
    if not official and (not SA_SETUP_RE.search(os.path.basename(args[0])) or not os.path.isfile(test_key or test_key_path(args[0]))):
        print(TEST_ONLY)
        return 2
    if not os.path.isfile(SANDBOX):
        print("윈도우 샌드박스가 꺼져 있습니다 (위 설명의 명령으로 켜고 재부팅)")
        return 2
    work = tempfile.mkdtemp(prefix="rpa_sbx_sa_")
    try:
        if official:
            prepare_official(args[0], work, guid, lic, lic_other, test_key=test_key, cloud_setup=cloud, over_cloud=over)
        else:
            prepare_standalone(args[0], work, cloud_setup=cloud, over_cloud=over, key_file=test_key)
    except ValueError as e:
        print(e)
        shutil.rmtree(work, ignore_errors=True)
        return 2
    with open(os.path.join(work, "test.wsb"), "w", encoding="utf-8") as f:
        f.write(WSB.format(work=work, extra=OFFLINE if offline else ""))
    print(f"스탠드얼론 시험: {os.path.basename(args[0])}"
          + (f", 일반 설치 파일 멈춤 확인 {os.path.basename(cloud)}" if cloud else "")
          + (f", 일반 버전 위에 설치 {os.path.basename(over)}" if over else ""))
    return wait_sandbox(work, 30)


def python_info(python_dir):
    """그 폴더의 python.exe 가 말하는 버전 글 ("3.14.10 OpenSSL 3.5.9 29 Sep 2026") - 샌드박스 안에서 같은 명령으로 찍어 견준다."""
    r = subprocess.run([os.path.join(python_dir, "python.exe"), "-I", "-B", "-c", "import sys, ssl; print(sys.version.split()[0], ssl.OPENSSL_VERSION)"],
                       capture_output=True, text=True, timeout=60)
    return r.stdout.strip()


def swap_python(scratch, man, new_python):
    """scratch\\python 의 내장 파이썬 파일(목록의 runtime_files)을 new_python 폴더 것으로 바꾼다 - 이름 붙인 exe 둘(files)은 그대로.
    새 runtime_files 를 돌려준다."""
    import build_release
    for rel in man["runtime_files"]:
        os.remove(os.path.join(scratch, *rel.split("/")))
    for base, dirs, files in os.walk(new_python):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            dst = os.path.join(scratch, "python", os.path.relpath(os.path.join(base, name), new_python))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.join(base, name), dst)
    return build_release.runtime_file_list(scratch, list(man["files"]))


def build_site(version_a, release_dir, work, a_manifest=None, runtime=None):
    """release_dir 배포 폴더로 판 B·C 를 만들어 시험용 열쇠로 서명해 work\\site 에 넣는다. (B 판 번호, C 판 번호, 공개 열쇠).
    a_manifest 를 주면 (--from 전환 시험) 설치된 판 A 는 그 옛 판이고, 판 B 는 release_dir 그대로 (파일을 안 바꾼다).
    runtime (다른 버전의 내장 파이썬 폴더, 그 안에 python.exe) 을 주면 판 R(판 A 에 그 파이썬)·판 RC(R 인데 켜지지 않음)도 만든다
    (설계 2026-11-20 - 업데이트가 내장 파이썬을 바꾼다)."""
    import publish_release
    import rpa_status
    day = version_a.split("-")[0]
    vb, vc = f"{day}-9001", f"{day}-9002"               # VERSION_RE 가 -b/-c 를 받지 않는다
    site = os.path.join(work, "site")
    scratch = os.path.join(work, "rel")                 # 판 A 사본 (영문 경로) - 파일 하나를 바꿔 판 B·C 를 만든다
    shutil.copytree(release_dir, scratch)
    key = os.path.join(work, "test_key.txt")
    pub = publish_release.keygen(key)
    man = json.load(open(os.path.join(scratch, "manifest.json"), encoding="utf-8"))
    changed = set()

    def make(version, bodies, rt=None):
        m = json.loads(json.dumps(man))
        m["version"] = version
        if rt:                                          # (파이썬 버전 표기, 새 runtime_files) - scratch\python 은 이미 바꿔 두었다
            m["runtime"], m["runtime_files"] = {"python": rt[0]}, rt[1]
            changed.update(d["sha256"] for rel, d in rt[1].items() if (man["runtime_files"].get(rel) or {}).get("sha256") != d["sha256"])
        origs = {}
        for rel, body in bodies.items():
            full = os.path.join(scratch, *rel.split("/"))
            origs[full] = open(full, "rb").read()
            with open(full, "wb") as f:
                f.write(body(origs[full]))
            m["files"][rel] = rpa_status.file_digest(full)
            changed.add(m["files"][rel]["sha256"])
        with open(os.path.join(scratch, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)
        publish_release.publish(version, scratch, site, key, memo="샌드박스 시험", deploy=None, set_releases=None)
        for full, orig in origs.items():
            with open(full, "wb") as f:
                f.write(orig)                           # 다음 판도 판 A 에서 출발

    # 판 B 는 감독 exe 도 바꾼다 (끝에 몇 바이트 - 그대로 켜진다): 업데이트 도중 끊기면 새 판 감독이 그 exe 를 쥔 채로
    # 되돌리기가 돈다 (2026-10-16 전환 시험에서 PermissionError - 도우미가 남은 감독을 끝내고 잠긴 파일은 기다려 다시)
    make(vb, {"rpa_dashboard.py": lambda b: b} if a_manifest else
         {"rpa_dashboard.py": lambda b: b.rstrip(b"\r\n") + b"\n# update test B\n",
          "python/AFTER_MARKET_RPA_Supervisor.exe": lambda b: b + b"\0update-test-B"})
    make(vc, {"firebase/agent/agent.py": lambda b: b"import sys; sys.exit(1)\n"})
    versions = [vb, vc]
    if runtime:                                         # 판 R·RC: 내장 파이썬이 다른 버전 (판 B·C 를 다 만든 뒤 - scratch\python 을 바꾼다)
        info_a, info_new = python_info(os.path.join(release_dir, "python")), python_info(runtime)
        if not info_a or not info_new or info_a == info_new:
            raise SystemExit(f"--runtime 의 파이썬이 배포 폴더의 파이썬과 같거나 실행되지 않습니다 ({info_a!r} / {info_new!r})")
        rt = (info_new.split()[0], swap_python(scratch, man, runtime))
        vr, vrc = f"{day}-9003", f"{day}-9004"
        make(vr, {"rpa_dashboard.py": lambda b: b.rstrip(b"\r\n") + b"\n# update test R\n"}, rt=rt)
        make(vrc, {"firebase/agent/agent.py": lambda b: b"import sys; sys.exit(1)\n"}, rt=rt)
        versions += [vr, vrc]
        with open(os.path.join(site, "runtime.txt"), "w", encoding="ascii") as f:
            f.write(f"{info_a}\n{info_new}\n")
    keep = set(changed)                                 # 판 B·C·R·RC 를 만들며 바꾼 파일
    if a_manifest:
        # 전환 시험: 옛 판에서 올라올 때 받을 파일 = 옛 목록의 '같은 경로' 와 지문이 다른 것. 지문만 견주면 안 된다 - 옛 판의 다른 경로에
        # 같은 내용이 있던 파일(2026-11-19 부터 아이콘 넷이 같은 바이트)을 지워 404 가 난다 (검토 2026-11-20).
        # 내장 파이썬 파일은 파이썬 표기가 다를 때만 받는다 - 같을 때는 사이트에 두지 않아, 옛 코드가 받으려 들면 404 로 드러난다
        a_man = json.load(open(a_manifest, encoding="utf-8"))
        swap = (a_man.get("runtime") or {}) != (man.get("runtime") or {})
        a_all = {**(a_man.get("runtime_files") or {}), **a_man["files"]}
        b_all = {**((man.get("runtime_files") or {}) if swap else {}), **man["files"]}
        keep |= {d["sha256"] for rel, d in b_all.items() if (a_all.get(rel) or {}).get("sha256") != d["sha256"]}
        if swap:                                        # 내장 파이썬이 다른 옛 판에서 올라오는 실제 전환 - 샌드박스가 python 폴더까지 견준다
            with open(os.path.join(site, "runtime.txt"), "w", encoding="ascii") as f:
                f.write(f"{python_info(os.path.join(os.path.dirname(a_manifest), 'python'))}\n{python_info(os.path.join(release_dir, 'python'))}\n")
    for name in os.listdir(os.path.join(site, "blobs")):    # 판 A 와 같은 파일은 받을 일이 없다 - 작업 폴더를 작게
        if name not in keep:
            os.remove(os.path.join(site, "blobs", name))
    os.remove(key)                                      # 시험용 비밀 열쇠는 남기지 않는다
    shutil.rmtree(scratch)
    with open(os.path.join(site, "pub.txt"), "w", encoding="ascii") as f:
        f.write(pub + "\n")
    with open(os.path.join(site, "versions.txt"), "w", encoding="ascii") as f:
        f.write("".join(v + "\n" for v in versions))
    if a_manifest:
        open(os.path.join(site, "transition.txt"), "w").close()   # sandbox_inner.ps1 이 전환 확인을 더 한다
    return vb, vc, pub


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    offline = "--offline" in args
    args = [a for a in args if a != "--offline"]
    if "--standalone" in args:
        return main_standalone([a for a in args if a != "--standalone"], offline=offline)
    update = "--update" in args
    args = [a for a in args if a != "--update"]
    old = None
    if "--from" in args:                                # 전환 시험: 옛 판 설치 파일을 깔고 새 판으로 업데이트 (2026-10-16)
        i = args.index("--from")
        old = args[i + 1] if i + 1 < len(args) else ""
        del args[i:i + 2]
        update = True
        if not os.path.isfile(old):
            print(f"옛 판 설치 파일이 없습니다: {old}")
            return 2
    runtime = None
    if "--runtime" in args:                             # 내장 파이썬이 바뀐 버전으로 업데이트하는 시험 (설계 2026-11-20)
        i = args.index("--runtime")
        runtime = args[i + 1] if i + 1 < len(args) else ""
        del args[i:i + 2]
        if old or not update or not os.path.isfile(os.path.join(runtime, "python.exe")):
            print("--runtime 은 --update 와 같이 쓰고 (--from 과는 같이 못 쓴다), python.exe 가 든 폴더를 줍니다")
            return 2
    if len(args) != 1 or not os.path.isfile(args[0]):
        print(__doc__)
        return 2
    if not os.path.isfile(SANDBOX):
        print("윈도우 샌드박스가 꺼져 있습니다 (위 설명의 명령으로 켜고 재부팅)")
        return 2
    work = tempfile.mkdtemp(prefix="rpa_sbx_")          # 영문 경로 (샌드박스에 그대로 붙는다)
    shutil.copy2(old or args[0], os.path.join(work, "setup.exe"))
    shutil.copy2(os.path.join(HERE, "sandbox_inner.ps1"), os.path.join(work, "inner.ps1"))
    if update:
        m = re.search(r"Setup_(.+)\.exe$", os.path.basename(args[0]))
        release = find_release(args[0])                 # 설치 파일 옆의 배포 폴더 먼저 (--out-root 로 만든 확인 빌드), 없으면 D:\AX
        if not os.path.isfile(os.path.join(release, "manifest.json")):
            print(f"배포 폴더를 찾지 못했습니다: {release}")
            return 2
        a_man = None
        if old:
            a_rel = find_release(old)
            a_man = os.path.join(a_rel, "manifest.json") if a_rel else ""
            if not os.path.isfile(a_man):
                print(f"옛 판 배포 폴더를 찾지 못했습니다: {a_man}")
                return 2
        if runtime and not json.load(open(os.path.join(release, "manifest.json"), encoding="utf-8")).get("runtime_files"):
            print("이 배포 폴더의 목록에는 내장 파이썬 파일 칸(runtime_files)이 없습니다 - --runtime 시험은 2026-11-20 부터의 빌드로 합니다")
            return 2
        vb, vc, _ = build_site(m.group(1), release, work, a_manifest=a_man, runtime=runtime)
        print(f"업데이트 시험: {'옛 판 ' + os.path.basename(old) + ' 설치 → ' if old else ''}판 B {vb}, 판 C(켜지지 않음) {vc}"
              + (f", 내장 파이썬이 바뀐 판 R·RC ({runtime})" if runtime else ""))
    with open(os.path.join(work, "test.wsb"), "w", encoding="utf-8") as f:
        f.write(WSB.format(work=work, extra=OFFLINE if offline else ""))
    return wait_sandbox(work, 60 if runtime else 45)    # 업데이트 시험은 3분 점검이 세 번 더 든다 (--runtime 은 거기에 업데이트 셋 더)


if __name__ == "__main__":
    sys.exit(main())
