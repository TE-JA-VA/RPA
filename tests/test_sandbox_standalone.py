# -*- coding: utf-8 -*-
"""스탠드얼론 샌드박스 준비 (tools/sandbox_test.py --standalone, 계획 ③ Task 6 Step 1) - 샌드박스는 띄우지 않는다.

    D:/AX/RPA/.venv/Scripts/python.exe tests/test_sandbox_standalone.py
"""
import io
import json
import os
import sys
import tempfile
import types
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)
import license_check  # noqa: E402
import sandbox_test as sb  # noqa: E402
import server_info  # noqa: E402
import update_sign  # noqa: E402

fails = 0


def check(what, cond):
    global fails
    print(f"  [{'통과' if cond else '실패'}] {what}")
    if not cond:
        fails += 1


def quiet(fn, *a):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = fn(*a)
    return code, buf.getvalue()


print("=== 1. 막을 주소 (server_info 로 만든다) ===")
hosts = sb.BLOCK_HOSTS()
check("RTDB·로그인·토큰·Firestore 주소", all(h in hosts for h in (
    "rpa-test-f02e0-default-rtdb.asia-southeast1.firebasedatabase.app", server_info.AUTH_HOST, server_info.TOKEN_HOST, server_info.FIRESTORE_HOST)))
check("업체 웹·업데이트 사이트·인증 도메인·Anthropic·글꼴·jsdelivr", all(h in hosts for h in (
    "rpa-test-f02e0.web.app", "rpa-test-f02e0-releases.web.app", "rpa-test-f02e0.firebaseapp.com", "api.anthropic.com",
    "fonts.googleapis.com", "cdn.jsdelivr.net")))
check("gstatic 은 넣지 않는다 · 겹치는 주소 없음", not any("gstatic" in h for h in hosts) and len(hosts) == len(set(hosts)))
fake = types.SimpleNamespace(PROJECT_ID="p-x", DATABASE_URL="https://db.example.test", AUTH_HOST="a.example.test", TOKEN_HOST="t.example.test",
                             FIRESTORE_HOST="f.example.test", DASHBOARD_URL="https://p-x.web.app", UPDATE_BASE_URL="https://up.example.test",
                             UPDATE_FALLBACK_URLS=("https://old.example.test/x",))
got = sb.BLOCK_HOSTS(fake)
check("주소를 옮기면 따라간다 (다른 server_info 값)", {"db.example.test", "a.example.test", "p-x-releases.web.app", "up.example.test",
                                                    "old.example.test"} <= set(got) and "rpa-test-f02e0.web.app" not in got)

print("=== 2. 작업 폴더 준비 ===")
with tempfile.TemporaryDirectory() as tmp:
    rel = os.path.join(tmp, "rel")
    os.makedirs(rel)
    setup = os.path.join(rel, "AUTOPILOT_Standalone_TEST_Setup_2099.01.01-1.exe")
    open(setup, "wb").write(b"MZ fake")
    secret, public = update_sign.keygen()
    with open(os.path.join(rel, "배포_SA_TEST_2099.01.01-1.testkey.txt"), "w", encoding="ascii") as f:
        f.write(secret.hex() + "\n")
    cloud = os.path.join(rel, "AUTOPILOT_Setup_2099.01.01-1.exe")
    open(cloud, "wb").write(b"MZ cloud")
    work = sb.prepare_standalone(setup, os.path.join(tmp, "work"), cloud_setup=cloud)
    names = set(os.listdir(work))
    check("작업 폴더: setup·inner·trap·check·라이선스 둘·hosts·guid·일반 설치 파일",
          {"setup.exe", "inner.ps1", "trap.ps1", "check_standalone.py", "license.json", "license_other.json", "hosts_block.txt",
           "guid.txt", "cloud_setup.exe"} <= names and "over_cloud.exe" not in names)
    check("작업 폴더에 열쇠 파일이 없다", not any(n.endswith(".testkey.txt") or "key" in n.lower() for n in names))
    body = license_check.load(path=os.path.join(work, "license.json"), guid=sb.SANDBOX_GUID, public_key=public.hex())
    check("license.json 은 그 빌드의 시험용 공개 열쇠·SANDBOX_GUID 로 통과 (샌드박스상사 · c_sbx · 자동 실행 3줄)",
          body["company"] == "샌드박스상사" and body["cid"] == "c_sbx" and body["limits"]["schedule"] == 3 and body["pc_id"] == sb.SANDBOX_GUID)
    try:
        license_check.load(path=os.path.join(work, "license_other.json"), guid=sb.SANDBOX_GUID, public_key=public.hex())
        other = ""
    except license_check.LicenseError as e:
        other = str(e)
    check("license_other.json 은 '이 PC 의 라이선스가 아닙니다'", "이 PC 의 라이선스가 아닙니다" in other)
    try:
        license_check.load(path=os.path.join(work, "license.json"), guid=sb.SANDBOX_GUID, public_key=update_sign.keygen()[1].hex())
        wrong = ""
    except license_check.LicenseError as e:
        wrong = str(e)
    check("다른 열쇠(진짜 빌드)로는 통하지 않는다", "서명이 맞지 않습니다" in wrong)
    lines = open(os.path.join(work, "hosts_block.txt"), "rb").read().decode("ascii").split("\r\n")
    check("hosts_block.txt = '127.0.0.2 <주소>' 줄 (CRLF)", [ln for ln in lines if ln] == [f"127.0.0.2 {h}" for h in hosts])
    check("guid.txt = SANDBOX_GUID", open(os.path.join(work, "guid.txt")).read().strip() == sb.SANDBOX_GUID)
    work2 = sb.prepare_standalone(setup, os.path.join(tmp, "work2"), over_cloud=cloud)
    check("--over-cloud 는 over_cloud.exe 로", "over_cloud.exe" in os.listdir(work2) and "cloud_setup.exe" not in os.listdir(work2))

    print("=== 3. 시험용 빌드만 받는다 ===")
    plain = os.path.join(rel, "AUTOPILOT_Standalone_Setup_2099.01.01-1.exe")
    open(plain, "wb").write(b"MZ")
    code, out = quiet(sb.main, ["--standalone", plain])
    check("이름에 TEST 가 없으면 2 · 안내", code == 2 and sb.TEST_ONLY in out)
    nokey = os.path.join(tmp, "AUTOPILOT_Standalone_TEST_Setup_2099.01.02-1.exe")
    open(nokey, "wb").write(b"MZ")
    code, out = quiet(sb.main, ["--standalone", nokey])
    check("옆에 시험용 열쇠 파일이 없으면 2 · 안내", code == 2 and sb.TEST_ONLY in out)
    try:
        sb.prepare_standalone(nokey, os.path.join(tmp, "w3"))
        raised = False
    except ValueError as e:
        raised = str(e) == sb.TEST_ONLY
    check("prepare_standalone 도 열쇠가 없으면 ValueError", raised)
    code, out = quiet(sb.main, ["--standalone", "--cloud-setup", os.path.join(tmp, "없는.exe"), setup])
    check("--cloud-setup 파일이 없으면 2", code == 2)

    print("=== 4. 배포 폴더 찾기 (--update·--from) ===")
    near = os.path.join(rel, "배포_2099.01.01-1")
    os.makedirs(near)
    check("설치 파일 옆에 배포 폴더가 없으면 D:\\AX 의 것", sb.find_release(cloud) == os.path.join(r"D:\AX", "배포_2099.01.01-1"))
    open(os.path.join(near, "manifest.json"), "w").write("{}")
    check("설치 파일 옆의 배포 폴더를 먼저 (--out-root 빌드)", sb.find_release(cloud) == near)
    check("스탠드얼론 접두사 - 옆에 없으면 D:\\AX\\스탠드얼론 의 것 (폴더 나누기 2026-11-23)",
          sb.find_release(setup, "배포_SA_TEST_") == os.path.join(r"D:\AX\스탠드얼론", "배포_SA_TEST_2099.01.01-1"))

print("=== 5. 샌드박스 설정 파일 ===")
check("--offline 은 네트워크 끄기 줄을 넣는다", "<Networking>Disable</Networking>" in sb.WSB.format(work="W", extra=sb.OFFLINE)
      and "Networking" not in sb.WSB.format(work="W", extra=""))
for name in ("sandbox_inner_standalone.ps1", "sandbox_trap.ps1"):
    b = open(os.path.join(ROOT, "tools", name), "rb").read()
    check(f"{name} 는 BOM 있는 UTF-8", b.startswith(b"\xef\xbb\xbf") and bool(b[3:].decode("utf-8")))
inner = open(os.path.join(ROOT, "tools", "sandbox_inner_standalone.ps1"), encoding="utf-8-sig").read()
check("안쪽 스크립트가 결과 끝 줄 '실패: N' 을 쓰고 done.txt 를 남긴다", '"실패: $script:fails"' in inner and "done.txt" in inner)
cloud_inner = open(os.path.join(ROOT, "tools", "sandbox_inner.ps1"), encoding="utf-8-sig").read()
check("일반 버전의 sandbox_inner.ps1 은 스탠드얼론 기능을 시험하지 않는다 (소문자 standalone 글자 없음)", "standalone" not in cloud_inner)

print("=== 6. 폴더 나누기 (사용자 2026-11-23) ===")
for line in ('$App = "C:\\Program Files\\AFTER MARKET\\RPA Standalone"', '$PD = "C:\\ProgramData\\AFTER MARKET\\RPA Standalone"',
             '$SM = "C:\\ProgramData\\Microsoft\\Windows\\Start Menu\\Programs\\오토파일럿 스탠드얼론"', '$Task = "AFTER MARKET\\RPA Standalone Agent"',
             '$CloudApp = "C:\\Program Files\\AFTER MARKET\\RPA"', '$CloudPD = "C:\\ProgramData\\AFTER MARKET\\RPA"'):
    check(f"스탠드얼론 샌드박스 자리: {line}", line in inner)
check("스탠드얼론 샌드박스: 설치 뒤·일반 설치 파일이 멈춘 뒤·제거 뒤에 일반 폴더(프로그램·설정)를 만들지 않았는지 본다",
      inner.count("@(NoCloudDirs)") >= 4)
check("스탠드얼론 샌드박스: 설치본의 install_root 가 새 설정 폴더, 작업 이름은 일반 이름이 아니다",
      "st.install_root()" in inner and "AFTER MARKET\\RPA Agent" in inner)
check("스탠드얼론 샌드박스 --over-cloud: 일반 설치는 일반 폴더에, 스탠드얼론 폴더는 생기지 않는다",
      "$CloudApp\\manifest.json" in inner and "-not (Test-Path $App)" in inner)
for line in ('$App = "C:\\Program Files\\AFTER MARKET\\RPA"', '$PD = "C:\\ProgramData\\AFTER MARKET\\RPA"',
             '$SM = "C:\\ProgramData\\Microsoft\\Windows\\Start Menu\\Programs\\오토파일럿"', '$Task = "AFTER MARKET\\RPA Agent"'):
    check(f"일반 샌드박스 자리는 예전 그대로: {line}", line in cloud_inner)
check("일반 샌드박스: 스탠드얼론 폴더(프로그램·설정)를 만들지 않았는지 본다",
      'C:\\Program Files\\AFTER MARKET\\RPA Standalone' in cloud_inner and 'C:\\ProgramData\\AFTER MARKET\\RPA Standalone' in cloud_inner)
src = open(os.path.join(ROOT, "tools", "sandbox_test.py"), encoding="utf-8").read()
check("sandbox_test 안내의 스탠드얼론 설치 파일 예시는 D:\\AX\\스탠드얼론", "D:\\\\AX\\\\스탠드얼론\\\\AUTOPILOT_Standalone_TEST_Setup_" in src)
import build_release as br  # noqa: E402
check("sandbox_test 의 기본 결과 자리 = build_release 의 버전 종류별 기본값",
      sb.OUT_ROOTS == {"배포_": br.default_out_root("cloud"), "배포_SA_": br.default_out_root("standalone"),
                       "배포_SA_TEST_": br.default_out_root("standalone")})

print(f"\n실패: {fails}")
sys.exit(1 if fails else 0)
