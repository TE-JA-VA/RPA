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


_DEFAULT = object()


def seat_cert(guid="g-1", cid="c1", pc_id="pc_01", secret=None, ca=_DEFAULT):
    """자리 증명서 - ca 를 안 주면 연결 파일의 인증 기관(CA) 지문 (Codex 1), None 이면 ca 칸 없이."""
    ca = license_check.ca_fingerprint(CA) if ca is _DEFAULT else ca
    return seat.issue(secret or seat_secret, cid, pc_id, guid, 1764100000000, ca=ca)


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
          == ("https://192.168.1.230:8444", CA, AGENT_KEY, RELAY_KEY, "https://192.168.1.230:8443/"))
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

    print("Task 4b - Codex 계획 검토 1·3·4")
    make_link(seat_doc=seat_cert(ca=None))
    check("자리 증명서에 인증 기관 지문이 없으면 거절", raises(license_check.load_link, "인증 기관"))
    make_link(seat_doc=seat_cert(ca="0" * 64))
    check("자리 증명서의 인증 기관 지문 ≠ 연결 파일의 인증 기관 → 거절 (가짜 서버 중계)", raises(license_check.load_link, "인증 기관"))
    make_link(out=out_of(url="https://nt.example:8444"))
    check("서버 주소가 이름이면 거절 (사설 IP 글자만)", raises(license_check.load_link, "주소"))
    make_link(out=out_of(url="https://8.8.8.8:8444"))
    check("공인 IP 거절", raises(license_check.load_link, "주소"))
    make_link(web="https://evil.example/login")
    check("web 이 다른 호스트면 버린다 (None)", license_check.load_link()["web"] is None)
    make_link(web="http://192.168.1.230:8443")
    check("web 이 http 면 버린다", license_check.load_link()["web"] is None)
    make_link(web="https://192.168.1.230:8443")
    check("같은 IP 의 https web 은 쓴다", license_check.load_link()["web"] == "https://192.168.1.230:8443/")
    check("ca_fingerprint 는 DER 의 SHA-256 소문자 hex 64자", len(license_check.ca_fingerprint(CA)) == 64)
    import lan_config  # noqa: E402
    check("LAN_PRIVATE_NETS 는 lan_config.PRIVATE_NETS 와 같다",
          tuple(str(n) for n in lan_config.PRIVATE_NETS) == license_check.LAN_PRIVATE_NETS)
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

    print("Task 3 - 등록 결과에 자리 증명서·서버 라이선스 사본")
    import fb  # noqa: E402
    import lan_ca  # noqa: E402
    import local_store  # noqa: E402
    ca_dir = os.path.join(TMP, "ca")
    lan_ca.make_ca(ca_dir, ["nt"], ["192.168.1.230"])
    REAL_CA = lan_ca.ca_pem(ca_dir)
    TOKEN = "t" * 43
    RAND = "c" * 64
    NONCE = "d" * 32
    AK, _RK = pc_registry.derive_keys(TOKEN, RAND)
    SEAT, LIC = seat_cert(ca=license_check.ca_fingerprint(REAL_CA)), server_license()

    def enroll_text(**extra):
        return pc_registry.encode_enrollment(dict({"v": 1, "url": "https://192.168.1.230:8444", "pc": "pc_01", "token": TOKEN,
                                                   "exp": 1764100000000, "ca": REAL_CA}, **extra))

    class Resp:
        def __init__(self, raw, sign=True, status=200):
            self.status, self._raw = status, raw
            self.headers = {local_store.H_SIGN: local_store.response_mac(AK, NONCE, status, raw) if sign else "x"}

        def read(self):
            return self._raw

    def opener_for(reply, sign=True):
        raw = reply if isinstance(reply, bytes) else json.dumps(reply).encode("utf-8")
        return lambda req, timeout=30: Resp(raw, sign)

    def enroll_with(reply, sign=True, **extra):
        return local_store.enroll(enroll_text(**extra), "g-1", "PC-1", opener=opener_for(reply, sign), rand_hex=RAND, nonce=NONCE)

    def auth_code(fn):
        try:
            fn()
        except fb.AuthError as e:
            return e.code
        return None

    got = enroll_with({"pc": "pc_01", "seat": SEAT, "server_license": LIC})
    check("응답의 seat·server_license 를 그대로 돌려준다", got.get("seat") == SEAT and got.get("server_license") == LIC)
    check("열쇠·주소·인증 기관은 지금처럼", got["agent_key"] == AK and got["ca_pem"] == REAL_CA and got["pc_id"] == "pc_01")
    check("seat 가 빠진 https 응답은 NOT_VERIFIED (서명은 맞아도)",
          auth_code(lambda: enroll_with({"pc": "pc_01", "server_license": LIC})) == local_store.NOT_VERIFIED)
    check("server_license 가 빠져도 NOT_VERIFIED",
          auth_code(lambda: enroll_with({"pc": "pc_01", "seat": SEAT})) == local_store.NOT_VERIFIED)
    check("서명이 틀린 응답은 NOT_VERIFIED",
          auth_code(lambda: enroll_with({"pc": "pc_01", "seat": SEAT, "server_license": LIC}, sign=False)) == local_store.NOT_VERIFIED)
    check("JSON 이 아닌 본문 → NOT_VERIFIED", auth_code(lambda: enroll_with(b"not json")) == local_store.NOT_VERIFIED)
    got = enroll_with({"pc": "pc_01", "seat": SEAT, "server_license": LIC}, web="https://192.168.1.230:8443")
    check("등록 글의 web 칸은 https://IP:포트/ 로", got.get("web") == "https://192.168.1.230:8443/", got.get("web"))
    got = enroll_with({"pc": "pc_01", "seat": SEAT, "server_license": LIC})
    check("web 칸이 없으면 결과에도 없다", "web" not in got)
    got = enroll_with({"pc": "pc_01", "seat": SEAT, "server_license": LIC}, web="https://evil.example/login")
    check("등록 글의 web 이 다른 호스트면 버린다 (Codex 4)", "web" not in got, got.get("web"))
    called = []
    try:
        local_store.enroll(enroll_text(url="https://nt.example:8444"), "g-1", "PC-1",
                           opener=lambda req, timeout=30: called.append(1), rand_hex=RAND, nonce=NONCE)
        named = False
    except ValueError:
        named = True
    check("등록 글 주소가 이름이면 연결하기 전에 ValueError (Codex 3)", named and not called)
    doc = license_check.link_doc(got, got["seat"], got["server_license"], web=got.get("web"))
    write(doc)
    check("enroll 결과로 만든 연결 파일이 load_link 를 통과", license_check.load_link(guid="g-1")["pc_id"] == "pc_01")

    print("끝 검토 고침 - 인증서 둘 이은 PEM (Opus 1), web 의 줄바꿈 (Opus 2)")
    CA2 = "-----BEGIN CERTIFICATE-----\nMIIC\n-----END CERTIFICATE-----\n"
    for name, pem in (("인증서 둘", CA + CA2), ("뒤에 TRUSTED CERTIFICATE", CA + CA2.replace("CERTIFICATE", "TRUSTED CERTIFICATE"))):
        try:
            license_check.ca_fingerprint(pem)
            bad_fp = False
        except ValueError:
            bad_fp = True
        check(f"ca_fingerprint: {name} 이은 PEM 은 ValueError", bad_fp)
        make_link(out=out_of(ca=pem))                       # 자리 증명서의 ca = 첫 인증서 지문 (진짜 서버를 중계한 모양)
        check(f"load_link: {name} 이은 인증 기관은 거절 (첫 인증서 지문이 맞아도)", raises(license_check.load_link, "인증 기관"))
    ca_dir2 = os.path.join(TMP, "ca2")
    lan_ca.make_ca(ca_dir2, ["evil"], ["192.168.1.66"])
    called = []
    try:
        local_store.enroll(enroll_text(ca=REAL_CA + lan_ca.ca_pem(ca_dir2)), "g-1", "PC-1",
                           opener=lambda req, timeout=30: called.append(1), rand_hex=RAND, nonce=NONCE)
        two = False
    except ValueError:
        two = True
    check("등록 글의 인증 기관이 둘이면 연결하기 전에 ValueError", two and not called)
    inj = "https://192.168.1.230:8443/\r\nIconFile=\\\\192.168.1.66\\s\\a.ico"
    check("same_host_web: 줄바꿈이 든 주소는 버린다", license_check.same_host_web(inj, "https://192.168.1.230:8444") is None)
    bs = "https://evil.example\\@192.168.1.230:8443/"          # 파이썬은 사설 IP, 브라우저는 evil.example 로 읽는다 (Codex 끝 검토 2)
    check("lan_host: 역슬래시·@ 가 든 주소는 None", license_check.lan_host(bs) is None
          and license_check.lan_host("https://u@192.168.1.230:8444") is None)
    check("same_host_web: 역슬래시 주소는 버린다", license_check.same_host_web(bs, "https://192.168.1.230:8444") is None)
    check("lan_host: 빈칸·제어 문자가 든 주소는 None", license_check.lan_host("https://192.168.1.230:8444/\t") is None)
    got_web = license_check.same_host_web("https://192.168.1.230:8443/dash?x=1#y", "https://192.168.1.230:8444")
    check("same_host_web: 경로·물음은 버리고 https://IP:포트/ 로 새로 만든다", got_web == "https://192.168.1.230:8443/", repr(got_web))
    check("same_host_web: 포트 없으면 https://IP/",
          license_check.same_host_web("https://192.168.1.230/x?y", "https://192.168.1.230:8444") == "https://192.168.1.230/")
    check("same_host_web: IPv6 는 [] 로", license_check.same_host_web("https://[fd00::1]:8443", "https://[fd00::1]:8444")
          == "https://[fd00::1]:8443/")
    make_link(web=inj)
    check("load_link: 줄바꿈이 든 web 은 None", license_check.load_link()["web"] is None)
    make_link(web="https://192.168.1.230:8443/dash")
    check("load_link: web 은 새로 만든 주소", license_check.load_link()["web"] == "https://192.168.1.230:8443/")
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n실패 {len(fails)}건" + ("" if not fails else ":\n  " + "\n  ".join(fails)))
sys.exit(1 if fails else 0)
