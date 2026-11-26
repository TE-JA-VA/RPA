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
    check("정식 빌드 이름인데 --guid·--license·--license-other 가 없으면 2 · 안내", code == 2 and sb.OFFICIAL_NEEDS in out)
    odd = os.path.join(rel, "다른이름_Setup_2099.01.01-1.exe")
    open(odd, "wb").write(b"MZ")
    code, out = quiet(sb.main, ["--standalone", odd])
    check("스탠드얼론 설치 파일 이름이 아니면 2 · 안내", code == 2 and sb.TEST_ONLY in out)
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
    kf = os.path.join(tmp, "nt_test_key.txt")                # build_release --license-key 로 만든 빌드 - 옆에 .testkey.txt 가 없다
    ks, kp = update_sign.keygen()
    with open(kf, "w", encoding="ascii") as f:
        f.write(ks.hex() + "\n")
    w4 = sb.prepare_standalone(nokey, os.path.join(tmp, "w4"), key_file=kf)
    check("prepare_standalone(key_file=): 옆에 열쇠가 없어도 그 열쇠로 license.json (끝 검토 Codex 4)",
          license_check.load(path=os.path.join(w4, "license.json"), guid=sb.SANDBOX_GUID, public_key=kp.hex())["cid"] == "c_sbx")
    real_sbx, sb.SANDBOX = sb.SANDBOX, os.path.join(tmp, "없는_샌드박스.exe")     # 진짜 샌드박스를 띄우지 않게
    try:
        code, out = quiet(sb.main, ["--standalone", "--test-key", kf, nokey])
    finally:
        sb.SANDBOX = real_sbx
    check("main: 시험용 빌드에 --test-key 를 주면 옆 열쇠를 찾지 않는다 (샌드박스 확인까지 간다)",
          code == 2 and sb.TEST_ONLY not in out and "샌드박스가 꺼져" in out)
    code, out = quiet(sb.main, ["--standalone", "--cloud-setup", os.path.join(tmp, "없는.exe"), setup])
    check("--cloud-setup 파일이 없으면 2", code == 2)

    print("=== 3-1. 정식 빌드 (미리 발급한 라이선스, 무작위 PC 번호 - 2026-11-24) ===")
    import uuid
    import make_license
    real_secret, real_public = update_sign.keygen()            # '진짜' 열쇠 대신 - 실린 공개 열쇠를 잠깐 바꿔 끼운다
    saved_pub = license_check.LICENSE_PUBLIC_KEY_HEX
    license_check.LICENSE_PUBLIC_KEY_HEX = real_public.hex()
    try:
        g1, g2 = str(uuid.uuid4()), str(uuid.uuid4())
        info = {"company": "시험상사", "cid": "c_test"}
        lic1, lic2 = os.path.join(tmp, "l1.json"), os.path.join(tmp, "l2.json")
        for path, g in ((lic1, g1), (lic2, g2)):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(license_check.sign_body(real_secret, make_license.build_body(g, info)), f, ensure_ascii=False)
        tkey = os.path.join(tmp, "t.testkey.txt")
        t_secret, t_public = update_sign.keygen()
        open(tkey, "w", encoding="ascii").write(t_secret.hex() + "\n")
        w = sb.prepare_official(plain, os.path.join(tmp, "wo"), g1, lic1, lic2, test_key=tkey, cloud_setup=cloud)
        names = set(os.listdir(w))
        check("정식: 작업 폴더에 라이선스 셋·expect.json·guid.txt, 열쇠 파일 없음",
              {"setup.exe", "inner.ps1", "license.json", "license_other.json", "license_testkey.json", "expect.json", "guid.txt",
               "cloud_setup.exe"} <= names and not any(n.endswith(".testkey.txt") or "key.txt" in n for n in names))
        check("정식: guid.txt = 받은 무작위 번호", open(os.path.join(w, "guid.txt")).read().strip() == g1)
        exp = json.load(open(os.path.join(w, "expect.json"), encoding="utf-8"))
        check("정식: expect.json = official · 라이선스의 업체", exp == {"official": True, "company": "시험상사", "cid": "c_test"})
        try:
            license_check.load(path=os.path.join(w, "license_testkey.json"), guid=g1)
            tl = ""
        except license_check.LicenseError as e:
            tl = str(e)
        check("정식: 시험 열쇠로 같은 번호에 서명한 라이선스는 실린 열쇠로 '서명이 맞지 않습니다'", "서명이 맞지 않습니다" in tl)
        body = license_check.load(path=os.path.join(w, "license_testkey.json"), guid=g1, public_key=t_public.hex())
        check("정식: 그 라이선스는 시험 열쇠로는 맞다 (서명 말고는 같은 모양)", body["pc_id"] == g1)
        for bad_g, why in ((sb.SANDBOX_GUID, "고정된 SANDBOX_GUID"), (g2, "license 와 다른 번호"), ("xyz", "모양이 틀린 번호")):
            try:
                sb.prepare_official(plain, os.path.join(tmp, "wbad"), bad_g, lic1, lic2)
                ok = False
            except ValueError:
                ok = True
            check(f"정식: {why} 는 ValueError", ok)
        try:
            sb.prepare_official(plain, os.path.join(tmp, "wsame"), g1, lic1, lic1)
            ok = False
        except ValueError:
            ok = True
        check("정식: --license-other 가 같은 번호면 ValueError", ok)
        w2 = sb.prepare_official(plain, os.path.join(tmp, "wo2"), g1, lic1, lic2)
        check("정식: --test-key 가 없으면 그 자리에서 만든 열쇠로 시험 라이선스", os.path.isfile(os.path.join(w2, "license_testkey.json")))
    finally:
        license_check.LICENSE_PUBLIC_KEY_HEX = saved_pub
    w3 = sb.prepare_standalone(setup, os.path.join(tmp, "w_test_exp"))
    check("시험용: expect.json = official 아님 · 샌드박스상사", json.load(open(os.path.join(w3, "expect.json"), encoding="utf-8"))
          == {"official": False, "company": "샌드박스상사", "cid": "c_sbx"})
    inner_src = open(os.path.join(ROOT, "tools", "sandbox_inner_standalone.ps1"), encoding="utf-8-sig").read()
    check("안쪽 스크립트: 정식이면 앱 이름 '시험용' 없음·시험 라이선스 거절·test_build 표시 꺼짐을 본다",
          '"오토파일럿 스탠드얼론" } else' in inner_src and "license_testkey.json" in inner_src and '"False False"' in inner_src)
    chk_src = open(os.path.join(ROOT, "tools", "sandbox_check_standalone.py"), encoding="utf-8").read()
    check("웹 확인: 정식이면 edition.js 에 TEST_BUILD = false", 'b"TEST_BUILD = false"' in chk_src)

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

print("=== 사내 서버 등록 샌드박스 (사내 서버 ⑤ Task 8) ===")
with tempfile.TemporaryDirectory() as tmp:
    rel = os.path.join(tmp, "rel")
    os.makedirs(rel)
    setup = os.path.join(rel, "AUTOPILOT_Standalone_TEST_Setup_2099.01.01-1.exe")
    open(setup, "wb").write(b"MZ fake")
    with open(os.path.join(rel, "배포_SA_TEST_2099.01.01-1.testkey.txt"), "w", encoding="ascii") as f:
        f.write(update_sign.keygen()[0].hex() + "\n")
    enroll = os.path.join(tmp, "등록글.txt")
    TEXT = "APE1.시험용등록글_샌드박스"
    with open(enroll, "w", encoding="utf-8") as f:
        f.write(TEXT + "\n")
    work = sb.prepare_lan(setup, os.path.join(tmp, "lan"), enroll)
    names = set(os.listdir(work))
    check("사내 서버 작업 폴더: setup·inner(사내 서버용)·enroll.txt, 라이선스·열쇠 파일 없음",
          {"setup.exe", "inner.ps1", "enroll.txt"} <= names and not any("license" in n or "key" in n.lower() for n in names))
    check("inner.ps1 은 sandbox_inner_lan.ps1", open(os.path.join(work, "inner.ps1"), "rb").read()
          == open(os.path.join(ROOT, "tools", "sandbox_inner_lan.ps1"), "rb").read())
    check("enroll.txt 는 받은 글 그대로 (파일로만 넘긴다)", open(os.path.join(work, "enroll.txt"), encoding="utf-8").read().strip() == TEXT)
    sb.write_wsb(work)
    wsb = open(os.path.join(work, "test.wsb"), encoding="utf-8").read()
    check("샌드박스 설정(.wsb)에 등록 글이 실리지 않는다", TEXT not in wsb and "inner.ps1" in wsb)
    code, out = quiet(sb.main, ["--standalone", setup, "--lan-enroll", os.path.join(tmp, "없음.txt")])
    check("--lan-enroll 파일이 없으면 2", code == 2)
    try:
        sb.prepare_lan(os.path.join(rel, "AUTOPILOT_Setup_2099.01.01-1.exe"), os.path.join(tmp, "lan2"), enroll)
        raised = False
    except ValueError as e:
        raised = str(e) == sb.TEST_ONLY
    check("사내 서버 샌드박스도 시험용 빌드만 (TEST_ONLY)", raised)
    os.remove(os.path.join(rel, "배포_SA_TEST_2099.01.01-1.testkey.txt"))
    kf = os.path.join(tmp, "nt_test_key.txt")
    with open(kf, "w", encoding="ascii") as f:
        f.write(update_sign.keygen()[0].hex() + "\n")
    w5 = sb.prepare_lan(setup, os.path.join(tmp, "lan3"), enroll, key_file=kf)
    check("prepare_lan(key_file=): --license-key 빌드(옆 열쇠 없음)도 받고, 열쇠는 작업 폴더에 넣지 않는다",
          "enroll.txt" in os.listdir(w5) and not any("key" in n.lower() for n in os.listdir(w5)))
lan_inner = open(os.path.join(ROOT, "tools", "sandbox_inner_lan.ps1"), encoding="utf-8-sig").read()
check("사내 서버 inner: 라이선스를 넣지 않고 install_link·save, 로컬 서버(8781)가 듣지 않는지, end.txt 를 기다린다",
      "license.json" not in lan_inner and "install_link" in lan_inner and "rs.save" in lan_inner and "8781" in lan_inner
      and "end.txt" in lan_inner and "ready.txt" in lan_inner)
check("사내 서버 inner 는 BOM 있는 UTF-8 (PowerShell 5.1)", open(os.path.join(ROOT, "tools", "sandbox_inner_lan.ps1"), "rb").read(3)
      == b"\xef\xbb\xbf")

print(f"\n실패: {fails}")
sys.exit(1 if fails else 0)
