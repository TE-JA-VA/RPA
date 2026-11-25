# -*- coding: utf-8 -*-
"""사내 서버 ④ Task 2 - 서버 번호와 서버 라이선스 (계획 2026-11-25-lan-4-linux Task 2, 설계 6.8).
license_check.server_id(machine-id 해시 앞 32자), license_check.load_server(서명·kind server·서버 번호·자리 수·자리 서명 공개 열쇠),
PC 라이선스를 읽는 load 는 서버 라이선스를 거절, tools/make_license.py --server 로 만든 파일이 load_server 를 통과.
서명 열쇠는 임시 폴더에 새로 만든 시험 열쇠만 쓴다 (실제 서명 열쇠 파일은 열지 않는다).
    D:/AX/RPA/.venv/Scripts/python.exe tests/test_server_license.py
    wsl.exe -d Ubuntu -e python3 /mnt/d/AX/RPA_StandAlone/tests/test_server_license.py
"""
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import license_check  # noqa: E402
import update_sign  # noqa: E402

fails = []
TMP = tempfile.mkdtemp(prefix="rpa_server_license_", dir="/tmp" if os.name == "posix" else None)
SECRET, PUBLIC = update_sign.keygen()
PUB = PUBLIC.hex()
SEAT_PUB = update_sign.secret_to_public(os.urandom(32)).hex()
GUID = "4c4c4544-0042-3510-8052-b4c04f4e3332"


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def guard(name, fn):
    print(name)
    try:
        fn()
    except Exception as ex:
        check(f"{name} - 예외 없이 끝난다", False, f"{type(ex).__name__}: {ex}\n{traceback.format_exc()[-1200:]}")


def p(name):
    return os.path.join(TMP, name)


def write(path, value, binary=False):
    with open(path, "wb" if binary else "w", **({} if binary else {"encoding": "utf-8"})) as f:
        f.write(value)
    return path


def lic_error(fn):
    """fn 이 LicenseError 를 내면 그 글, 아니면 None."""
    try:
        fn()
    except license_check.LicenseError as e:
        return str(e)
    except Exception as e:
        return f"!{type(e).__name__}: {e}"         # 다른 예외 - '!' 로 시작 (LicenseError 가 아니다)
    return None


def refused(fn):
    """fn 이 LicenseError 를 내면 참."""
    msg = lic_error(fn)
    return msg is not None and not msg.startswith("!")


def server_body(sid, **kw):
    body = {"edition": "standalone", "kind": "server", "company": "시험상사", "cid": "c_test", "server_id": sid,
            "seats": 10, "seat_pub": SEAT_PUB, "issued": "2026-11-25", "modules": {}, "features": {"wellife": False},
            "limits": {"schedule": 2, "presets": None, "parallel": None}}
    body.update(kw)
    return body


def write_lic(name, body, secret=SECRET):
    doc = license_check.sign_body(secret, body)
    write(p(name), json.dumps(doc, ensure_ascii=False))
    return p(name)


def test_server_id_stable():
    a = write(p("machine-id-a"), b"0123456789abcdef0123456789abcdef\n", binary=True)
    b = write(p("machine-id-b"), b"fedcba9876543210fedcba9876543210\n", binary=True)
    sid = license_check.server_id(a)
    check("같은 파일은 같은 값", sid == license_check.server_id(a))
    check("32자 16진수", isinstance(sid, str) and len(sid) == 32 and all(c in "0123456789abcdef" for c in sid), sid)
    check("sha256('autopilot-server:' + 내용) 앞 32자", sid == hashlib.sha256(b"autopilot-server:0123456789abcdef0123456789abcdef")
          .hexdigest()[:32], sid)
    check("다른 내용은 다른 값", license_check.server_id(b) != sid)
    a2 = write(p("machine-id-a2"), b"  0123456789abcdef0123456789abcdef  \r\n", binary=True)
    check("앞뒤 빈칸·줄바꿈은 셈하지 않는다", license_check.server_id(a2) == sid)
    empty = write(p("machine-id-empty"), b"\n", binary=True)
    check("빈 파일은 LicenseError", refused(lambda: license_check.server_id(empty)), lic_error(lambda: license_check.server_id(empty)))
    check("없는 파일은 LicenseError", refused(lambda: license_check.server_id(p("no-such"))))


def test_load_server_ok_and_refusals():
    sid = "0f" * 16
    ok = write_lic("srv_ok.json", server_body(sid))
    body = license_check.load_server(ok, sid, public_key=PUB)
    check("맞는 서버 라이선스는 body 를 돌려준다", body.get("seats") == 10 and body.get("seat_pub") == SEAT_PUB and body["server_id"] == sid,
          body)
    check("서버 번호는 대문자로 받아도 같다", license_check.load_server(ok, sid.upper(), public_key=PUB)["cid"] == "c_test")
    other = "ab" * 16
    msg = lic_error(lambda: license_check.load_server(ok, other, public_key=PUB))
    check("서버 번호가 다르면 LicenseError (글에 이 서버 번호)", msg and not msg.startswith("!") and other in msg, msg)
    cases = {
        "kind 빠짐": server_body(sid, kind=None),
        "kind 가 pc": server_body(sid, kind="pc"),
        "seats 0": server_body(sid, seats=0),
        "seats 10000": server_body(sid, seats=10000),
        "seats 참거짓": server_body(sid, seats=True),
        "seats 글": server_body(sid, seats="10"),
        "seat_pub 짧음": server_body(sid, seat_pub="ab" * 31),
        "seat_pub 16진수 아님": server_body(sid, seat_pub="zz" * 32),
        "edition 다름": server_body(sid, edition="cloud"),
    }
    for i, (name, b) in enumerate(cases.items()):
        if b.get("kind") is None:
            b = {k: v for k, v in b.items() if k != "kind"}
        path = write_lic(f"srv_case{i}.json", b)
        msg = lic_error(lambda: license_check.load_server(path, sid, public_key=PUB))
        check(f"{name} → LicenseError", msg is not None and not msg.startswith("!"), msg)
    # 서명 틀림: 서명한 뒤 자리 수를 고친 파일
    doc = license_check.sign_body(SECRET, server_body(sid))
    doc2 = copy.deepcopy(doc)
    doc2["body"]["seats"] = 9999
    write(p("srv_tampered.json"), json.dumps(doc2))
    msg = lic_error(lambda: license_check.load_server(p("srv_tampered.json"), sid, public_key=PUB))
    check("서명한 뒤 고친 파일 → LicenseError (서명)", msg is not None and "서명" in msg, msg)
    other_secret, _ = update_sign.keygen()
    path = write_lic("srv_other_key.json", server_body(sid), secret=other_secret)
    msg = lic_error(lambda: license_check.load_server(path, sid, public_key=PUB))
    check("다른 열쇠로 서명 → LicenseError", msg is not None and "서명" in msg, msg)
    msg = lic_error(lambda: license_check.load_server(p("srv_missing.json"), sid, public_key=PUB))
    check("파일이 없으면 LicenseError (글에 서버 번호)", msg is not None and sid in msg, msg)
    write(p("srv_garbage.json"), "{쓰레기")
    msg = lic_error(lambda: license_check.load_server(p("srv_garbage.json"), sid, public_key=PUB))
    check("읽을 수 없는 파일 → LicenseError", msg is not None and not msg.startswith("!"), msg)


def test_pc_load_refuses_server():
    sid = "0f" * 16
    path = write_lic("srv_as_pc.json", server_body(sid, pc_id=GUID))      # PC 번호 칸까지 맞춰도 kind 가 server 면 거절
    msg = lic_error(lambda: license_check.load(path, guid=GUID, public_key=PUB))
    check("PC 라이선스를 읽는 load 는 서버 라이선스를 거절 ('PC 라이선스가 아닙니다')", msg is not None and "PC 라이선스가 아닙니다" in msg,
          msg)
    pc_body = {"edition": "standalone", "company": "시험상사", "cid": "c_test", "pc_id": GUID, "issued": "2026-11-25",
               "modules": {}, "features": {"wellife": False}, "limits": {"schedule": 2, "presets": None, "parallel": None}}
    pc_path = write_lic("pc_ok.json", pc_body)
    check("PC 라이선스는 지금처럼 통과", license_check.load(pc_path, guid=GUID, public_key=PUB)["pc_id"] == GUID)
    msg = lic_error(lambda: license_check.load_server(pc_path, sid, public_key=PUB))
    check("load_server 는 PC 라이선스를 거절", msg is not None and not msg.startswith("!"), msg)


def run_tool(*args):
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "make_license.py"), *args], capture_output=True,
                       cwd=TMP, env=dict(os.environ, PYTHONUTF8="1"), timeout=120)
    return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")


def test_make_license_server():
    key = p("test_license_key.txt")
    code, out = run_tool("--keygen", key)
    check("--keygen 을 임시 경로로", code == 0 and os.path.isfile(key), out)
    with open(key, encoding="ascii") as f:            # 이 시험이 방금 만든 시험 열쇠
        pub = update_sign.secret_to_public(bytes.fromhex(f.read().strip())).hex()
    check("--keygen 이 알려 준 공개 열쇠가 열쇠 파일과 맞다", pub in out, out)
    sid = license_check.server_id(write(p("mid"), b"11112222333344445555666677778888\n", binary=True))
    req = write(p("server_request.json"), json.dumps({"server_id": sid, "seat_pub": SEAT_PUB, "version": "2026.11.25-1"}))
    info = write(p("info.json"), json.dumps({"company": "시험상사", "cid": "c_srv", "seats": 5, "modules": {"Hold": False}},
                                            ensure_ascii=False))
    out_path = p("license_server.json")
    code, out = run_tool("--server", req, info, "--key", key, "-o", out_path)
    check("--server 발급 0", code == 0 and os.path.isfile(out_path), out)
    if os.path.isfile(out_path):
        body = license_check.load_server(out_path, sid, public_key=pub)
        check("만든 파일이 load_server 를 통과 (자리 5·자리 공개 열쇠·업체)",
              body["seats"] == 5 and body["seat_pub"] == SEAT_PUB and body["cid"] == "c_srv" and body["kind"] == "server"
              and body["modules"] == {"Hold": False}, body)
        msg = lic_error(lambda: license_check.load(out_path, guid=GUID, public_key=pub))
        check("만든 파일은 PC 라이선스로는 거절", msg is not None and "PC 라이선스가 아닙니다" in msg, msg)
    for name, value in (("seats 없음", {"company": "시험상사", "cid": "c_srv"}),
                        ("seats 0", {"company": "시험상사", "cid": "c_srv", "seats": 0})):
        bad = write(p("info_bad.json"), json.dumps(value, ensure_ascii=False))
        code, out = run_tool("--server", req, bad, "--key", key, "-o", p("bad.json"))
        check(f"업체 정보 {name} → 발급하지 않음", code != 0 and not os.path.exists(p("bad.json")), out)
    for name, value in (("서버 번호 틀림", {"server_id": "xyz", "seat_pub": SEAT_PUB}),
                        ("자리 공개 열쇠 틀림", {"server_id": sid, "seat_pub": "ab"})):
        bad = write(p("req_bad.json"), json.dumps(value))
        code, out = run_tool("--server", bad, info, "--key", key, "-o", p("bad.json"))
        check(f"요청 파일 {name} → 발급하지 않음", code != 0 and not os.path.exists(p("bad.json")), out)
    code, out = run_tool(GUID, info, "--key", key, "--out", p("pc_from_tool.json"))
    check("PC 발급은 그대로", code == 0 and license_check.load(p("pc_from_tool.json"), guid=GUID, public_key=pub)["pc_id"] == GUID, out)


try:
    print("서버 번호·서버 라이선스 (test_server_license)")
    missing = [n for n in ("server_id", "load_server") if not hasattr(license_check, n)]
    if missing:
        check("license_check 에 " + "·".join(missing), False, "없음")
    guard("test_server_id_stable", test_server_id_stable)
    guard("test_load_server_ok_and_refusals", test_load_server_ok_and_refusals)
    guard("test_pc_load_refuses_server", test_pc_load_refuses_server)
    guard("test_make_license_server", test_make_license_server)
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n실패: {len(fails)}" + (f" ({', '.join(fails)})" if fails else ""))
sys.exit(1 if fails else 0)
