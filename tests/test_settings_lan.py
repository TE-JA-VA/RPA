# -*- coding: utf-8 -*-
"""설정 창의 사내 서버 등록 (사내 서버 ⑤ Task 6, Codex 계획 검토 6·7·8·10) - 창 없는 함수만.
연결 방식(link_state), 등록(install_link: 거절 글·응답 잃음·인증 기관 신뢰·대시보드 바로 가기), 등록 해제(unlink),
덮어 설치 마무리(reapply_lan), 인증 기관 지우기(forget_ca), 단독 라이선스와 함께 두지 않기, 저장·configured.

    D:/AX/RPA/.venv/Scripts/python.exe tests/test_settings_lan.py

새 구조 자리는 RPA_PROGRAMDATA 임시 폴더, enroll·certutil·작업 명령은 가짜.
"""
import json
import os
import shutil
import sys
import tempfile
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = tempfile.mkdtemp(prefix="rpa_settings_lan_")
PD = os.path.join(TMP, "programdata")
for _d in ("config", "data", "standalone"):
    os.makedirs(os.path.join(PD, _d))
for _k in ("RPA_USER_CONFIG", "RPA_CRED_FILE", "RPA_AGENT_CONFIG"):
    os.environ.pop(_k, None)
os.environ.update(RPA_PROGRAMDATA=PD, RPA_EDITION="standalone", RPA_MACHINE_GUID="g-1",
                  RPA_AGENT_QUEUE=os.path.join(TMP, "queue.jsonl"), RPA_AGENT_MUTEX=rf"Local\AFTER_MARKET_RPA_AGENT_SA_LAN_{os.getpid()}")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "firebase" / "agent"))
sys.stdout.reconfigure(encoding="utf-8")

import fb  # noqa: E402
import license_check  # noqa: E402
import local_store  # noqa: E402
import rpa_settings as rs  # noqa: E402
import rpa_status as st  # noqa: E402
import seat  # noqa: E402
import update_sign  # noqa: E402

import local_server  # noqa: E402
LOCKED = []
local_server.lock_key_files = lambda folder, *a, **k: LOCKED.append(folder) or []    # 진짜 icacls 는 관리자 아닌 시험이 파일을 못 읽게 한다

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
CA = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"
AK, RK = "a" * 64, "b" * 64
SERVER_BODY = {"edition": "standalone", "kind": "server", "company": "시험상사", "cid": "c1", "server_id": "0" * 32,
               "seat_pub": seat_public.hex(), "seats": 5, "modules": {}, "features": {}, "limits": {}}
TEXT = "APE1.시험용등록글"                       # 가짜 enroll 이 받기만 한다 (풀지 않는다)
SHORTCUT_TEXT = "[InternetShortcut]\r\nURL=http://127.0.0.1:8781/\r\nIconFile=C:\\x\\AFTER_MARKET.ico\r\nIconIndex=0\r\n"


def enroll_out(guid="g-1", web="https://192.168.1.230:8443"):
    out = {"server_url": "https://192.168.1.230:8444", "pc_id": "pc_01", "agent_key": AK, "relay_key": RK, "ca_pem": CA,
           "seat": seat.issue(seat_secret, "c1", "pc_01", guid, 1, ca=license_check.ca_fingerprint(CA)),
           "server_license": license_check.sign_body(lic_secret, SERVER_BODY)}
    if web:
        out["web"] = web
    return out


class FakeEnroll:
    def __init__(self, result=None, exc=None):
        self.result, self.exc, self.calls = result, exc, []

    def __call__(self, text, guid, host):
        self.calls.append((text, guid, host))
        if self.exc:
            raise self.exc
        return self.result


class Cert:
    """가짜 certutil - -store 는 present 에 따라 0/1, -addstore·-delstore 는 code."""

    def __init__(self, present=False, code=0):
        self.present, self.code, self.calls = present, code, []

    def __call__(self, args, timeout=60):
        self.calls.append(list(args))
        if "-store" in args:
            return (0 if self.present else 1), ""
        return self.code, ""

    def verbs(self):
        return [a[1] for a in self.calls]


def paths_in(name):
    d = os.path.join(TMP, name)
    cfg, prog, keys, menu = (os.path.join(d, x) for x in ("config", "설치 폴더", "standalone", "menu"))
    for p in (cfg, os.path.join(d, "data"), os.path.join(prog, "firebase", "agent"), keys, menu):
        os.makedirs(p)
    shutil.copyfile(ROOT / "release" / "RPA_UserConfig.template.json", os.path.join(prog, rs.TEMPLATE_NAME))
    shortcut = os.path.join(menu, rs.SHORTCUT_NAME)
    with open(shortcut, "w", encoding="ascii", newline="") as f:
        f.write(SHORTCUT_TEXT)
    return {"program_dir": prog, "config_dir": cfg, "user_config": os.path.join(cfg, st.USER_CONFIG_NAME),
            "agent_config": os.path.join(cfg, rs.AGENT_CONFIG_NAME), "template": os.path.join(prog, rs.TEMPLATE_NAME),
            "agent_py": os.path.join(prog, "firebase", "agent", "agent.py"), "stop_file": os.path.join(d, "data", "에이전트_멈춤.json"),
            "license": os.path.join(d, "license.json"), "accounts": os.path.join(keys, "accounts.json"),
            "link": os.path.join(keys, license_check.LINK_NAME), "lan_ca": os.path.join(keys, rs.CA_RECORD_NAME),
            "shortcut": shortcut}


def form(**kw):
    f = {k: "" for k in rs.FORM_KEYS}
    f.update(admin_code="AM001", erp_id="rpa", erp_pw="Erp-Pw-1234!", print_mode=rs.PRINT_MANUAL)
    f.update(kw)
    return f


def err_of(fn):
    try:
        fn()
    except (ValueError, license_check.LicenseError) as e:
        return str(e)
    return None


def shortcut_url(p):
    with open(p["shortcut"], encoding="ascii") as f:
        return [x for x in f.read().splitlines() if x.startswith("URL=")]


texts = []
try:
    print("연결 방식")
    p = paths_in("a")
    check("아무것도 없으면 mode none", rs.link_state(p)["mode"] == "none")

    print("등록 성공")
    cert = Cert()
    fake = FakeEnroll(enroll_out())
    got = rs.install_link("  " + TEXT + "\n", p, enroll=fake, run=cert)
    texts += got["done"]
    check("enroll 에 앞뒤 빈칸 없는 글·이 PC 번호", fake.calls and fake.calls[0][0] == TEXT and fake.calls[0][1] == "g-1", fake.calls)
    check("연결 파일이 생기고 mode lan·ok", os.path.isfile(p["link"]) and rs.link_state(p)["mode"] == "lan" and rs.link_state(p)["ok"],
          rs.link_state(p))
    check("link_state: 서버·PC·업체", (rs.link_state(p)["server"], rs.link_state(p)["pc_id"], rs.link_state(p)["company"])
          == ("192.168.1.230", "pc_01", "시험상사"))
    check("돌려준 값에 pc_id·server, 한 일에 등록 문장", got["pc_id"] == "pc_01" and got["server"] == "192.168.1.230"
          and any("pc_01" in x for x in got["done"]), got)
    check("certutil: 먼저 -store Root 로 있는지, 없으면 -addstore -f Root", cert.verbs() == ["-store", "-addstore"]
          and cert.calls[1][2:4] == ["-f", "Root"], cert.calls)
    rec = json.load(open(p["lan_ca"], encoding="utf-8"))
    check("우리가 넣은 인증 기관만 따로 적는다 (sha1 40자)", len(rec.get("sha1", "")) == 40 and cert.calls[0][3] == rec["sha1"], rec)
    check("대시보드 바로 가기 URL 이 업체 웹 주소로 (다른 줄 그대로)", shortcut_url(p) == ["URL=https://192.168.1.230:8443"]
          and "IconFile=C:\\x\\AFTER_MARKET.ico" in open(p["shortcut"], encoding="ascii").read())
    check("이미 등록된 PC 는 다시 등록하지 않는다 (해제 안내)",
          "등록 해제" in (err_of(lambda: rs.install_link(TEXT, p, enroll=FakeEnroll(enroll_out()), run=Cert())) or ""))
    check("연결 파일이 있으면 라이선스 넣기를 BOTH_TEXT 로 거절, license.json 안 생김",
          err_of(lambda: rs.install_license(os.path.join(TMP, "없는파일.json"), p)) == license_check.BOTH_TEXT
          and not os.path.exists(p["license"]))

    print("저장·configured (사내 서버는 관리자 계정을 PC 에 만들지 않는다)")
    run = Cert()
    done = rs.save(form(), p, run=run, running=lambda: True, user="PC\\u", standalone=True)
    texts += done
    check("관리자 계정이 없어도 저장된다", any("저장" in x for x in done) and not rs.admin_exists(p), done)
    check("configured 참", rs.configured(p))

    print("덮어 설치 마무리 (Codex 8)")
    with open(p["shortcut"], "w", encoding="ascii", newline="") as f:
        f.write(SHORTCUT_TEXT)
    cert = Cert(present=False)
    rs.reapply_lan(p, run=cert)
    check("바로 가기를 업체 웹 주소로 다시 쓰고 인증 기관을 다시 넣는다", shortcut_url(p) == ["URL=https://192.168.1.230:8443"]
          and "-addstore" in cert.verbs(), (shortcut_url(p), cert.calls))

    print("등록 해제 (Codex 6) · 인증 기관 지우기 (Codex 10)")
    cert = Cert()
    done = rs.unlink(p, run=cert)
    texts += done
    check("해제: 우리가 넣은 인증 기관을 -delstore Root <지문>, 연결 파일·기록 지움",
          cert.verbs() == ["-delstore"] and cert.calls[0][2:4] == ["Root", rec["sha1"]] and not os.path.exists(p["link"])
          and not os.path.exists(p["lan_ca"]), cert.calls)
    cert = Cert()
    check("기록이 없으면 forget_ca 는 0 이고 certutil 을 부르지 않는다", rs.forget_ca(p, run=cert) == 0 and not cert.calls)

    print("인증 기관이 이미 있으면 (IT 가 넣음) 넣지도 적지도 않는다")
    p2 = paths_in("b")
    cert = Cert(present=True)
    rs.install_link(TEXT, p2, enroll=FakeEnroll(enroll_out()), run=cert)
    check("-store 만 부르고 -addstore 없음, 기록 없음", cert.verbs() == ["-store"] and not os.path.exists(p2["lan_ca"]), cert.calls)

    print("certutil 이 실패해도 등록은 남는다")
    p3 = paths_in("c")
    got = rs.install_link(TEXT, p3, enroll=FakeEnroll(enroll_out(web=None)), run=Cert(code=5))
    texts += got["done"]
    check("등록은 남고 안내 문장", os.path.isfile(p3["link"]) and any("인증 기관" in x for x in got["done"]), got["done"])
    check("web 이 없으면 바로 가기를 건드리지 않고 업체 IT 안내", shortcut_url(p3) == ["URL=http://127.0.0.1:8781/"]
          and any("업체 IT" in x for x in got["done"]), got["done"])

    print("거절·실패 - 아무 파일도 쓰지 않는다")
    for code, word in (("expired", "10분"), ("unknown", "이미 쓴"), ("duplicate", "이미 사내 서버에 등록"), ("seats", "PC 수"),
                       ("bad_proof", "고치지 말고")):
        q = paths_in("r_" + code)
        e = err_of(lambda: rs.install_link(TEXT, q, enroll=FakeEnroll(exc=fb.HttpError(403, json.dumps({"error": code}))), run=Cert()))
        texts.append(e or "")
        check(f"서버 거절 {code} → 사람 말, 파일 없음", e == rs.ENROLL_TEXT[code] and word in e and not os.listdir(os.path.dirname(q["link"])), e)
    q = paths_in("cert")
    e = err_of(lambda: rs.install_link(TEXT, q, enroll=FakeEnroll(exc=fb.AuthError(0, local_store.CERT_FAILED)), run=Cert()))
    check("인증서 확인 실패 → 정해 둔 글", e and "인증 기관으로 서버를 확인하지 못했습니다" in e, e)
    q = paths_in("net")
    e = err_of(lambda: rs.install_link(TEXT, q, enroll=FakeEnroll(exc=urllib.error.URLError(TimeoutError("timed out"))), run=Cert()))
    texts.append(e or "")
    check("연결 오류 → 연결하지 못했다 + 응답을 잃었을 때 안내 (Codex 7)", e and "연결하지 못했습니다" in e and rs.LOST_TEXT in e, e)
    e = err_of(lambda: rs.install_link(TEXT, q, enroll=FakeEnroll(exc=fb.AuthError(0, local_store.NOT_VERIFIED)), run=Cert()))
    check("응답 확인 실패 → 응답을 잃었을 때 안내", e and rs.LOST_TEXT in e, e)
    check("실패 뒤 파일 없음", not os.listdir(os.path.dirname(q["link"])))
    q = paths_in("other")
    e = err_of(lambda: rs.install_link(TEXT, q, enroll=FakeEnroll(enroll_out(guid="g-2")), run=Cert()))
    check("다른 PC 의 자리 증명서 → LicenseError 글, 연결·임시 파일 없음", e and "이 PC" in e and not os.listdir(os.path.dirname(q["link"])), e)
    q = paths_in("alone")
    with open(q["license"], "w", encoding="utf-8") as f:
        f.write("{}")
    fake = FakeEnroll(enroll_out())
    e = err_of(lambda: rs.install_link(TEXT, q, enroll=fake, run=Cert()))
    check("단독 라이선스가 있는 PC 는 등록 거절, enroll 을 부르지 않음", e and "단독 라이선스" in e and not fake.calls, e)
    check("link_state: 라이선스만이면 alone", rs.link_state(q)["mode"] == "alone")

    rec_file = os.path.join(PD, "standalone", rs.CA_RECORD_NAME)
    with open(rec_file, "w", encoding="utf-8") as f:
        json.dump({"sha1": "c" * 40}, f)
    seen = []
    real_run = rs.run_quiet
    rs.run_quiet = lambda args, timeout=60: seen.append(list(args)) or (0, "")
    try:
        code = rs.main(["--uninstall-cleanup"])
    finally:
        rs.run_quiet = real_run
    check("--uninstall-cleanup (제거 - Task 7): 기록된 지문만 -delstore, 창 없이 0", code == 0 and len(seen) == 1
          and seen[0][1:4] == ["-delstore", "Root", "c" * 40] and not os.path.exists(rec_file), seen)
    check("연결 파일은 잠그는 열쇠 파일 목록에 (관리자·SYSTEM 만), 등록 뒤 그 폴더를 잠근다",
          license_check.LINK_NAME in local_server.LOCKED_FILES and os.path.dirname(p["link"]) in LOCKED, LOCKED)
    check("한 일·오류 글에 열쇠·등록 글이 없다", texts and all(AK not in t and RK not in t and TEXT not in t for t in texts), texts)
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(TMP, ignore_errors=True)
print()
print(f"실패: {'없음' if not fails else fails}")
sys.exit(1 if fails else 0)
