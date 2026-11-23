# -*- coding: utf-8 -*-
"""스탠드얼론 라이선스 (PC 번호에 묶인 우리 서명 파일)와 버전 종류 (설계 2026-11-23-standalone 6.1·6.4).
    .venv\\Scripts\\python.exe tests\\test_license.py
"""
import json
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import update_sign  # noqa: E402
import edition  # noqa: E402
import license_check  # noqa: E402
import make_license  # noqa: E402

fails = []
TMP = tempfile.mkdtemp(prefix="rpa_lic_")


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def expect_error(name, fn, text):
    try:
        got = fn()
    except license_check.LicenseError as e:
        check(name, text in str(e), f"글: {e}")
    else:
        check(name, False, f"예외 없이 {got!r}")


def write(name, doc):
    path = os.path.join(TMP, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    return path


def with_env(name, value, fn):
    old = os.environ.get(name)
    os.environ[name] = value
    try:
        return fn()
    finally:
        if old is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = old


try:
    secret, public = update_sign.keygen()
    pub = public.hex()
    body = {"edition": "standalone", "company": "시험상사", "cid": "c_test", "pc_id": "aaaa-1111",
            "issued": "2026-11-23", "modules": {"Hold": False}, "features": {"wellife": False},
            "limits": {"schedule": 3, "presets": None, "parallel": None}}

    print("라이선스 확인")
    good = write("good.json", license_check.sign_body(secret, body))
    check("맞는 라이선스 (PC 번호 대소문자 무시)", license_check.load(good, guid="AAAA-1111", public_key=pub) == body)
    try:
        license_check.load(good, guid="bbbb-2222", public_key=pub)
        check("다른 PC", False, "예외 없음")
    except license_check.LicenseError as e:
        check("다른 PC", "이 PC 의 라이선스가 아닙니다" in str(e) and "bbbb-2222" in str(e), str(e))
    doc = json.load(open(good, encoding="utf-8"))
    doc["body"]["limits"]["schedule"] = 99
    expect_error("본문 고침", lambda: license_check.load(write("tampered.json", doc), guid="aaaa-1111", public_key=pub),
                 "라이선스 서명이 맞지 않습니다")
    expect_error("파일 없음", lambda: license_check.load(os.path.join(TMP, "none.json"), guid="aaaa-1111", public_key=pub),
                 "라이선스 파일이 없습니다")
    expect_error("열쇠 없음", lambda: license_check.load(good, guid="aaaa-1111", public_key=""),
                 "라이선스 확인 열쇠가 없습니다")
    cloud = write("cloud.json", license_check.sign_body(secret, dict(body, edition="cloud")))
    expect_error("다른 버전 종류", lambda: license_check.load(cloud, guid="aaaa-1111", public_key=pub),
                 "스탠드얼론 라이선스가 아닙니다")
    broken = os.path.join(TMP, "broken.json")
    with open(broken, "w", encoding="utf-8") as f:
        f.write('{"body": {"edi')
    expect_error("깨진 파일", lambda: license_check.load(broken, guid="aaaa-1111", public_key=pub), "라이선스 파일을 읽지 못했습니다")
    expect_error("서명 칸 없음", lambda: license_check.load(write("nosig.json", {"body": body}), guid="aaaa-1111", public_key=pub),
                 "라이선스 파일을 읽지 못했습니다")
    expect_error("서명이 16진수가 아님", lambda: license_check.load(write("badsig.json", {"body": body, "sig": "zz"}),
                                                              guid="aaaa-1111", public_key=pub), "라이선스 서명이 맞지 않습니다")
    other_secret, _ = update_sign.keygen()
    forged = write("forged.json", license_check.sign_body(other_secret, body))
    expect_error("다른 열쇠로 서명", lambda: license_check.load(forged, guid="aaaa-1111", public_key=pub),
                 "라이선스 서명이 맞지 않습니다")
    check("본문 글 순서는 서명과 무관", license_check.canonical({"b": 1, "a": "가"}) == license_check.canonical({"a": "가", "b": 1})
          and license_check.canonical({"a": "가"}) == '{"a":"가"}'.encode("utf-8"))

    print("버전 종류 · PC 번호")
    check("기본은 cloud", with_env("RPA_EDITION", "", edition.edition) == "cloud" and not edition.is_standalone())
    check("버전 종류 덮어쓰기", with_env("RPA_EDITION", "standalone", edition.edition) == "standalone")
    check("이상한 값은 cloud", with_env("RPA_EDITION", "pro", edition.edition) == "cloud")
    check("is_standalone", with_env("RPA_EDITION", "standalone", edition.is_standalone) is True)
    check("PC 번호 덮어쓰기 (소문자로)", with_env("RPA_MACHINE_GUID", "ABC-Def", license_check.machine_guid) == "abc-def")
    real = with_env("RPA_MACHINE_GUID", "", license_check.machine_guid)
    check("이 PC 의 번호를 읽는다", isinstance(real, str) and len(real) >= 8 and real == real.lower(), repr(real))
    pd = os.path.join(TMP, "pd")
    check("라이선스 자리", with_env("RPA_PROGRAMDATA", pd, license_check.license_path) == os.path.join(pd, "license.json"))

    print("발급 도구")
    key_path = os.path.join(TMP, "lic_key.txt")
    made_pub = make_license.keygen(key_path)
    check("열쇠 만들기 - 공개 열쇠 64글자", len(made_pub) == 64 and os.path.isfile(key_path))
    try:
        make_license.keygen(key_path)
        check("이미 있는 열쇠는 덮지 않는다", False)
    except FileExistsError:
        check("이미 있는 열쇠는 덮지 않는다", True)
    info = write("info.json", {"company": "시험상사", "cid": "c_test", "modules": {}, "features": {"wellife": True},
                               "limits": {"schedule": 2}})
    out = os.path.join(TMP, "license.json")
    code = make_license.main(["AAAA-2222", info, "--key", key_path, "--out", out])
    got = license_check.load(out, guid="aaaa-2222", public_key=made_pub) if code == 0 else None
    check("발급한 파일이 확인을 통과", bool(got) and got["pc_id"] == "aaaa-2222" and got["edition"] == "standalone"
          and got["features"] == {"wellife": True} and len(got["issued"]) == 10, repr(got))
    check("없는 칸은 기본값", bool(got) and got["limits"] == {"schedule": 2, "presets": None, "parallel": None})
    bad = write("bad_info.json", {"company": "시험상사"})
    check("업체 코드 없는 정보는 거절", make_license.main(["AAAA-2222", bad, "--key", key_path, "--out", os.path.join(TMP, "x.json")]) != 0
          and not os.path.exists(os.path.join(TMP, "x.json")))
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n실패: {len(fails)}" + (f" ({', '.join(fails)})" if fails else ""))
sys.exit(1 if fails else 0)
