# -*- coding: utf-8 -*-
"""사내 서버 ④ Task 2 - 자리 증명서 (계획 2026-11-25-lan-4-linux Task 2, 설계 6.8).
seat.ensure_key(자리 서명 열쇠 seat.key - 없으면 만들고 0600), seat.issue·seat.verify (license_check.canonical 로 서명),
사내 서버 PC 등록(/enroll) 응답에 seat 와 server_license - 응답 서명(agent 열쇠) 안에 실리고, seat 는 라이선스의 seat_pub 으로
확인되며 guid 는 등록 요청의 guid. 서버에 자리 열쇠가 없으면(①~③ 처럼 직접 만든 서버) 응답은 지금 그대로.
    D:/AX/RPA/.venv/Scripts/python.exe tests/test_seat.py
    wsl.exe -d Ubuntu -e python3 /mnt/d/AX/RPA_StandAlone/tests/test_seat.py
"""
import copy
import hmac
import json
import os
import secrets
import shutil
import stat
import sys
import tempfile
import threading
import traceback
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
import license_check  # noqa: E402
import local_server  # noqa: E402
import local_store  # noqa: E402
import pc_registry  # noqa: E402
import update_sign  # noqa: E402

fails = []
try:
    import seat  # noqa: E402
except ImportError as e:
    print(f"  [실패] seat 를 불러오지 못한다 - {e}")
    print("\n실패: 1")
    sys.exit(1)

POSIX = os.name == "posix"
TMP = tempfile.mkdtemp(prefix="rpa_seat_", dir="/tmp" if POSIX else None)
GUID = "4c4c4544-0042-3510-8052-b4c04f4e3332"
GUID2 = "9f1b2c3d-1111-2222-3333-444455556666"
LIC = {"edition": "standalone", "kind": "server", "company": "시험상사", "cid": "c1", "server_id": "0f" * 16, "seats": 3,
       "issued": "2026-11-25", "modules": {}, "features": {}, "limits": {}}
NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


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


def bad(fn):
    """fn 이 ValueError 를 내면 참 (다른 예외는 거짓)."""
    try:
        fn()
    except ValueError:
        return True
    except Exception:
        return False
    return False


def test_issue_verify():
    folder = os.path.join(TMP, "k1")
    secret, pub = seat.ensure_key(folder)
    check("seat.SEAT_KEY 는 seat.key", seat.SEAT_KEY == "seat.key")
    check("ensure_key → (32바이트 비밀, 64자 공개 hex)", isinstance(secret, bytes) and len(secret) == 32 and isinstance(pub, str)
          and len(pub) == 64 and pub == update_sign.secret_to_public(secret).hex(), (type(secret), pub))
    check("다시 부르면 같은 열쇠 (덮지 않는다)", seat.ensure_key(folder) == (secret, pub))
    cert = seat.issue(secret, "c1", "pc_01", GUID, 1795000000123)
    check("issue → {body: {kind seat, cid, pc_id, guid, issued}, sig}", isinstance(cert, dict) and set(cert) == {"body", "sig"}
          and cert["body"] == {"kind": "seat", "cid": "c1", "pc_id": "pc_01", "guid": GUID, "issued": 1795000000123}, cert)
    check("서명은 license_check.canonical(body) 에 대한 Ed25519",
          update_sign.verify(bytes.fromhex(pub), license_check.canonical(cert["body"]), bytes.fromhex(cert["sig"])))
    body = seat.verify(pub, cert, GUID)
    check("verify → body", body == cert["body"], body)
    check("guid 대소문자는 가리지 않는다", seat.verify(pub, cert, GUID.upper()) == cert["body"])
    text = json.dumps(cert)
    check("증명서에 비밀 열쇠가 없다", secret.hex() not in text)


def test_wrong_guid():
    secret, pub = seat.ensure_key(os.path.join(TMP, "k2"))
    cert = seat.issue(secret, "c1", "pc_02", GUID, 1795000000000)
    check("다른 guid → ValueError", bad(lambda: seat.verify(pub, cert, GUID2)))
    check("빈 guid → ValueError", bad(lambda: seat.verify(pub, cert, "")))


def test_tampered():
    secret, pub = seat.ensure_key(os.path.join(TMP, "k3"))
    cert = seat.issue(secret, "c1", "pc_03", GUID, 1795000000000)
    c = copy.deepcopy(cert)
    c["body"]["pc_id"] = "pc_09"
    check("body 를 고치면 ValueError", bad(lambda: seat.verify(pub, c, GUID)))
    c = copy.deepcopy(cert)
    c["sig"] = ("0" if c["sig"][0] != "0" else "1") + c["sig"][1:]
    check("서명을 고치면 ValueError", bad(lambda: seat.verify(pub, c, GUID)))
    _, other_pub = seat.ensure_key(os.path.join(TMP, "k3b"))
    check("다른 서버의 공개 열쇠로는 ValueError", bad(lambda: seat.verify(other_pub, cert, GUID)))
    forged = {"body": dict(cert["body"], kind="license"), "sig": ""}
    forged["sig"] = update_sign.sign(secret, license_check.canonical(forged["body"])).hex()
    check("같은 열쇠로 서명했어도 kind 가 seat 가 아니면 ValueError", bad(lambda: seat.verify(pub, forged, GUID)))
    for name, value in (("None", None), ("빈 것", {}), ("sig 16진수 아님", {"body": cert["body"], "sig": "zz"}),
                        ("body 가 글", {"body": "x", "sig": cert["sig"]}), ("공개 열쇠 틀림", "pubbad")):
        if value == "pubbad":
            check(f"{name} → ValueError", bad(lambda: seat.verify("xyz", cert, GUID)))
        else:
            check(f"{name} → ValueError", bad(lambda v=value: seat.verify(pub, v, GUID)))


def test_key_file_mode():
    folder = os.path.join(TMP, "k4")
    seat.ensure_key(folder)
    path = os.path.join(folder, seat.SEAT_KEY)
    check("seat.key 가 생긴다", os.path.isfile(path))
    check("만들 때 쓴 임시 파일이 남지 않는다", os.listdir(folder) == [seat.SEAT_KEY], os.listdir(folder))
    if POSIX:
        check("seat.key 0600", stat.S_IMODE(os.stat(path).st_mode) == 0o600, oct(stat.S_IMODE(os.stat(path).st_mode)))
    else:
        print("  [건너뜀] 0600 은 리눅스(WSL)에서만")
    with open(path, "w", encoding="utf-8") as f:
        f.write("깨진 값")
    check("깨진 seat.key 는 덮지 않고 ValueError (라이선스와 짝이 끊기지 않게)", bad(lambda: seat.ensure_key(folder))
          and open(path, encoding="utf-8").read() == "깨진 값")


def post_enroll(base, body):
    req = urllib.request.Request(base + "/enroll", data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with NO_PROXY.open(req, timeout=15) as r:
            return r.status, r.read(), r.headers.get(local_store.H_SIGN) or ""
    except urllib.error.HTTPError as e:
        return e.code, e.read(), ""


def enroll_once(srv, reg, guid, host):
    """대기를 만들고 /enroll 을 직접 보낸다 → (상태, 본문 dict, 응답 서명이 그 PC 열쇠로 맞는가, pc_id)."""
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    got = reg.start(host)
    pc, token = got["pc_id"], got["token"]
    rand, nonce = secrets.token_hex(32), secrets.token_urlsafe(24)
    proof = pc_registry.enroll_proof(token, pc, rand, guid, host)
    status, raw, sign = post_enroll(base, {"v": 1, "pc": pc, "rand": rand, "guid": guid, "host": host, "nonce": nonce,
                                           "proof": proof})
    agent_key, _ = pc_registry.derive_keys(token, rand)
    signed = bool(sign) and hmac.compare_digest(sign, local_store.response_mac(agent_key, nonce, status, raw))
    try:
        body = json.loads(raw)
    except ValueError:
        body = None
    return status, body, signed, pc


def test_enroll_returns_seat():
    data = os.path.join(TMP, "server")
    os.makedirs(data)
    secret, pub = seat.ensure_key(data)
    lic_secret, lic_public = update_sign.keygen()                  # 시험 라이선스 열쇠
    lic_body = dict(LIC, seat_pub=pub)
    lic_doc = license_check.sign_body(lic_secret, lic_body)
    store = local_server.Store(os.path.join(data, "store.json"), volatile=local_server.VOLATILE)
    runs = local_server.Runs(os.path.join(data, "runs.db"))
    reg = pc_registry.Registry(os.path.join(data, "pcs.json"), seats=3)
    srv = local_server.make_server(store, runs, lic_body, None, port=0, folder=data, registry=reg)
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    try:
        check("서버의 seat_secret·license_doc 기본값은 None", srv.seat_secret is None and srv.license_doc is None)
        status, body, signed, pc = enroll_once(srv, reg, GUID2, "OLD-PC")
        check("자리 열쇠가 없는 서버(①~③ 그대로)의 등록 응답은 {pc} 만", status == 200 and body == {"pc": pc} and signed, (status, body))
        srv.seat_secret, srv.license_doc = secret, lic_doc
        status, body, signed, pc = enroll_once(srv, reg, GUID, "NEW-PC")
        check("등록 200, 응답 서명이 새 PC 열쇠로 맞다 (seat·server_license 가 서명 안에)", status == 200 and signed, (status, body))
        body = body or {}
        check("응답에 pc·seat·server_license", set(body) == {"pc", "seat", "server_license"} and body.get("pc") == pc, sorted(body))
        check("server_license 는 license.json 의 body+sig 원문", body.get("server_license") == lic_doc)
        got = None
        try:
            got = seat.verify(body["server_license"]["body"]["seat_pub"], body.get("seat"), GUID)
        except Exception as e:
            check("seat 가 라이선스의 seat_pub 으로 확인된다", False, f"{type(e).__name__}: {e}")
        if got is not None:
            check("seat 가 라이선스의 seat_pub 으로 확인되고 guid 는 등록 요청의 guid",
                  got["guid"] == GUID and got["pc_id"] == pc and got["cid"] == "c1" and got["kind"] == "seat"
                  and isinstance(got["issued"], int), got)
        check("라이선스 서명도 시험 열쇠로 맞다",
              update_sign.verify(lic_public, license_check.canonical(body["server_license"]["body"]),
                                 bytes.fromhex(body["server_license"]["sig"])))
        check("seat 의 guid 를 바꿔 쓰면 다른 PC 에서는 통과하지 못한다", bad(lambda: seat.verify(pub, body["seat"], GUID2)))
        log = ""
        try:
            with open(os.path.join(data, local_server.LOG_NAME), encoding="utf-8") as f:
                log = f.read()
        except OSError:
            pass
        check("서버 기록에 자리 서명 열쇠가 없다", secret.hex() not in log and "PC 등록  번호=" + pc in log, log[-300:])
    finally:
        srv.shutdown()
        srv.server_close()
        runs.close()


try:
    print("자리 증명서 (test_seat)")
    guard("test_issue_verify", test_issue_verify)
    guard("test_wrong_guid", test_wrong_guid)
    guard("test_tampered", test_tampered)
    guard("test_key_file_mode", test_key_file_mode)
    guard("test_enroll_returns_seat", test_enroll_returns_seat)
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n실패: {len(fails)}" + (f" ({', '.join(fails)})" if fails else ""))
sys.exit(1 if fails else 0)
