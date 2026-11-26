# -*- coding: utf-8 -*-
"""사내 서버 ⑤ (PC 쪽) - 연결 파일(server_link.json) 확인과 연결 방식 판정 (Task 1), 등록 결과에 자리 증명서·서버 라이선스 사본 (Task 3).

    D:/AX/RPA/.venv/Scripts/python.exe tests/test_lan_link.py

새 구조 자리는 RPA_PROGRAMDATA 임시 폴더. 라이선스 열쇠는 시험 열쇠로 바꿔 끼운다.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = tempfile.mkdtemp(prefix="rpa_lan_link_")
PD = os.path.join(TMP, "programdata")
os.makedirs(os.path.join(PD, "standalone"))
os.environ.update(RPA_PROGRAMDATA=PD, RPA_EDITION="standalone", RPA_MACHINE_GUID="g-1")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "firebase" / "agent"))
sys.stdout.reconfigure(encoding="utf-8")

import license_check  # noqa: E402
import pc_registry  # noqa: E402
import seat  # noqa: E402
import update_sign  # noqa: E402

fails = []
_no = [0]


def check(name, cond, detail=""):
    _no[0] += 1
    print(f"  {_no[0]:2d}. [{'통과' if cond else '실패'}] {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(f"{_no[0]}. {name} {detail}")


lic_secret, lic_public = update_sign.keygen()
license_check.LICENSE_PUBLIC_KEY_HEX = lic_public.hex()
seat_secret, seat_public = update_sign.keygen()
SEAT_PUB = seat_public.hex()
AGENT_KEY, RELAY_KEY = "a" * 64, "b" * 64
CA = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"
SERVER_BODY = {"edition": "standalone", "kind": "server", "company": "시험상사", "cid": "c1", "server_id": "0" * 32,
               "seat_pub": SEAT_PUB, "seats": 5, "issued": "2026-11-26", "modules": {}, "features": {}, "limits": {}}


def server_license(**kw):
    return license_check.sign_body(lic_secret, dict(SERVER_BODY, **kw))


def seat_cert(guid="g-1", cid="c1", pc_id="pc_01", secret=None):
    return seat.issue(secret or seat_secret, cid, pc_id, guid, 1764100000000)


def out_of(pc_id="pc_01", url="https://192.168.1.230:8444", ca=CA, agent_key=AGENT_KEY, relay_key=RELAY_KEY):
    return {"server_url": url, "pc_id": pc_id, "agent_key": agent_key, "relay_key": relay_key, "ca_pem": ca}


def write(doc, path=None):
    path = path or license_check.link_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    return path


def make_link(path=None, out=None, seat_doc=None, lic_doc=None, web=None, **extra):
    doc = license_check.link_doc(out or out_of(), seat_doc or seat_cert(), lic_doc or server_license(), web=web)
    doc.update(extra)
    return write(doc, path)


def raises(fn, needle=""):
    try:
        fn()
    except license_check.LicenseError as e:
        errors.append(e)
        return needle in str(e)
    return False


def clear():
    for p in (license_check.link_path(), license_check.license_path()):
        if os.path.exists(p):
            os.remove(p)


errors = []
try:
    print("Task 1 - 연결 파일과 연결 방식")
    check("link_path 는 설치 뿌리\\standalone\\server_link.json",
          license_check.link_path() == os.path.join(PD, "standalone", "server_link.json"), license_check.link_path())
    p = make_link(web="https://192.168.1.230:8443")
    got = license_check.load_link()
    check("맞는 연결 파일 → pc_id·cid·자리 증명서 guid",
          got["pc_id"] == "pc_01" and got["license"]["cid"] == "c1" and got["seat"]["guid"] == "g-1", got.get("pc_id"))
    check("주소·인증 기관·열쇠 둘·web 을 돌려준다",
          (got["server_url"], got["ca_pem"], got["agent_key"], got["relay_key"], got["web"])
          == ("https://192.168.1.230:8444", CA, AGENT_KEY, RELAY_KEY, "https://192.168.1.230:8443"))
    check("다른 PC(guid) 의 파일은 거절", raises(lambda: license_check.load_link(p, guid="g-2"), "이 PC"))

    bad = server_license()
    bad["body"] = dict(bad["body"], company="다른상사")
    make_link(lic_doc=bad)
    check("서버 라이선스 서명이 틀리면 거절", raises(license_check.load_link, "서명"))
    pc_lic = license_check.sign_body(lic_secret, {"edition": "standalone", "company": "시험상사", "cid": "c1", "pc_id": "g-1"})
    make_link(lic_doc=pc_lic)
    check("PC 라이선스(kind 없음)를 서버 라이선스 자리에 넣으면 거절", raises(license_check.load_link, "서버 라이선스"))
    other_secret, _ = update_sign.keygen()
    make_link(seat_doc=seat_cert(secret=other_secret))
    check("다른 자리 열쇠로 서명한 증명서는 거절", raises(license_check.load_link, "자리 증명서"))
    make_link(seat_doc=seat_cert(cid="c2"))
    check("seat cid ≠ 라이선스 cid 거절", raises(license_check.load_link, "업체"))
    make_link(seat_doc=seat_cert(pc_id="pc_02"))
    check("seat pc_id ≠ 파일 pc_id 거절", raises(license_check.load_link, "PC 번호"))
    make_link(out=out_of(pc_id="pc_x"), seat_doc=seat_cert(pc_id="pc_x"))
    check("pc_id 꼴이 틀리면 거절", raises(license_check.load_link, "PC 번호"))
    make_link(out=out_of(url="http://192.168.1.230:8444"))
    check("http 주소 거절", raises(license_check.load_link, "주소"))
    make_link(out=out_of(ca=""))
    check("빈 인증 기관 거절", raises(license_check.load_link, "인증 기관"))
    make_link(out=out_of(agent_key="abc"))
    check("짧은 열쇠 거절", raises(license_check.load_link, "열쇠"))
    make_link(v=2)
    check("v 2 는 거절", raises(license_check.load_link, "형식"))
    write(["not", "dict"])
    check("dict 가 아닌 파일 거절", raises(license_check.load_link, "읽지 못했습니다"))
    make_link(ca_sha1="ab" * 20)
    check("모르는 칸(ca_sha1)은 막지 않는다", license_check.load_link()["pc_id"] == "pc_01")
    check("오류 글에 열쇠 값이 없다", errors and all(AGENT_KEY not in str(e) and RELAY_KEY not in str(e) for e in errors),
          len(errors))

    clear()
    check("mode: 둘 다 없음 → alone (load 가 지금 글을 낸다)", license_check.mode() == license_check.MODE_ALONE)
    check("load_any: 둘 다 없으면 지금 '라이선스 파일이 없습니다'", raises(license_check.load_any, "라이선스 파일이 없습니다"))
    make_link()
    check("mode: 연결 파일만 → lan", license_check.mode() == license_check.MODE_LAN)
    m, body = license_check.load_any()
    check("load_any: lan 이면 load_link 결과", m == license_check.MODE_LAN and body["pc_id"] == "pc_01")
    write(license_check.sign_body(lic_secret, {"edition": "standalone", "company": "시험상사", "cid": "c1", "pc_id": "g-1"}),
          license_check.license_path())
    check("mode: 둘 다 → BOTH_TEXT", raises(license_check.mode) and str(errors[-1]) == license_check.BOTH_TEXT)
    os.remove(license_check.link_path())
    m, body = license_check.load_any()
    check("load_any: 라이선스만 → alone 과 PC 라이선스 body (지금 동작)", m == license_check.MODE_ALONE and body["pc_id"] == "g-1")
    clear()

    check("LAN_PC_RE 는 pc_registry.PC_RE 와 같은 꼴", license_check.LAN_PC_RE.pattern == pc_registry.PC_RE.pattern)
    cert = seat_cert()
    check("seat.verify 는 그대로 동작", seat.verify(SEAT_PUB, cert, "G-1")["pc_id"] == "pc_01")
    check("verify_seat 은 LicenseError (ValueError 의 하나)",
          raises(lambda: license_check.verify_seat(SEAT_PUB, cert, "g-2"), "이 PC") and isinstance(errors[-1], ValueError))
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n실패 {len(fails)}건" + ("" if not fails else ":\n  " + "\n  ".join(fails)))
sys.exit(1 if fails else 0)
