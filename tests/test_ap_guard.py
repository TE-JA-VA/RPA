# -*- coding: utf-8 -*-
"""복사 막기 가드 시험 (스탠드얼론 계획 ③ Task 3, 설계 2026-11-23-standalone 6.4·6.5).

설치본 흉내는 임시 프로그램 폴더 + rpa_status.program_dir·license_check.machine_guid·열쇠 바꿔 끼우기.
ERPia·브라우저는 건드리지 않는다 (부르면 시험이 실패한다).

    D:/AX/RPA/.venv/Scripts/python.exe tests/test_ap_guard.py
"""
import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import types

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
TMP = tempfile.mkdtemp(prefix="rpa_guard_")
PD = os.path.join(TMP, "pd")
os.makedirs(os.path.join(PD, "config"))
os.makedirs(os.path.join(TMP, "status"))
os.environ.update(RPA_PROGRAMDATA=PD, RPA_STATUS_DIR=os.path.join(TMP, "status"), RPA_USER_CONFIG=os.path.join(TMP, "RPA_UserConfig.json"),
                  RPA_DASHBOARD_DRY_RUN="1", RPA_MACHINE_GUID="pc-1")
os.environ.pop("RPA_EDITION", None)
with open(os.environ["RPA_USER_CONFIG"], "w", encoding="utf-8") as f:
    json.dump({"Sites": {}}, f)

import ap_guard  # noqa: E402
import edition  # noqa: E402
import license_check  # noqa: E402
import rpa_status as st  # noqa: E402
import update_sign  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


@contextlib.contextmanager
def patched(obj, **values):
    old = {k: getattr(obj, k) for k in values}
    for k, v in values.items():
        setattr(obj, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(obj, k, v)


up_secret, up_public = update_sign.keygen()
lic_secret, lic_public = update_sign.keygen()
update_sign.PUBLIC_KEY_HEX = up_public.hex()
license_check.LICENSE_PUBLIC_KEY_HEX = lic_public.hex()
BODY = {"edition": "standalone", "company": "시험상사", "cid": "c1", "pc_id": "pc-1", "issued": "2026-11-24",
        "modules": {}, "features": {}, "limits": {}}
LIC = os.path.join(PD, "license.json")


def put_license(body=None, secret=None, tamper=False):
    doc = license_check.sign_body(secret or lic_secret, dict(body or BODY))
    if tamper:
        doc["body"]["company"] = "다른상사"
    with open(LIC, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)


try:
    # -----------------------------------------------------------------------------------------
    print("일반 버전")
    calls = []
    with patched(license_check, load=lambda *a, **k: calls.append(1)):
        check("startup_problem() 은 None 이고 라이선스를 읽지 않는다", ap_guard.startup_problem() is None and not calls)
        check("check_line() 은 빈 글 (찍지 않는다)", ap_guard.check_line() == "" and not calls)
    check("edition.test_build() 는 False", edition.test_build() is False)

    # -----------------------------------------------------------------------------------------
    print("스탠드얼론 (소스)")
    os.environ["RPA_EDITION"] = "standalone"
    p = ap_guard.startup_problem()
    check("라이선스 없음 → 라이선스 파일이 없습니다", (p or "").startswith("라이선스 파일이 없습니다"), p)
    check("--check 줄도 그 글", ap_guard.check_line().startswith("라이선스: 라이선스 파일이 없습니다"), ap_guard.check_line())
    put_license(dict(BODY, pc_id="pc-2"))
    p = ap_guard.startup_problem()
    check("다른 PC → 이 PC 의 라이선스가 아닙니다 (PC 번호 …)", "이 PC 의 라이선스가 아닙니다. (PC 번호 pc-1)" in (p or ""), p)
    put_license(tamper=True)
    check("본문을 고치면 라이선스 서명이 맞지 않습니다", (ap_guard.startup_problem() or "").startswith("라이선스 서명이 맞지 않습니다"))
    put_license()
    check("맞는 라이선스 → None", ap_guard.startup_problem() is None, ap_guard.startup_problem())
    check("--check 줄: 확인됨 (업체 이름, PC 번호)", ap_guard.check_line() == "라이선스: 확인됨 (시험상사, PC 번호 pc-1)", ap_guard.check_line())
    put_license(dict(BODY, hw={"board": "x"}))
    check("모르는 칸 hw 가 든 라이선스도 통과 (나중에 메인보드를 더 묶어도 이미 준 라이선스는 산다)", ap_guard.startup_problem() is None)
    other_secret, _ = update_sign.keygen()
    put_license(secret=other_secret)
    check("다른 열쇠(시험용 빌드 열쇠 ↔ 진짜)로 만든 라이선스는 통하지 않는다",
          (ap_guard.startup_problem() or "").startswith("라이선스 서명이 맞지 않습니다"))
    put_license()

    # -----------------------------------------------------------------------------------------
    print("스탠드얼론 (설치본 흉내)")
    P = os.path.join(TMP, "prog")
    os.makedirs(os.path.join(P, "app"))
    files = {"rpa_dashboard.py": b"print('dash')\n", "app/run_routine.cp314-win_amd64.pyd": b"pyd",
             "app/license_check.cp314-win_amd64.pyd": b"pyd2", "app/_start.py": b"start\n", "edition.json": b'{"edition": "standalone"}'}
    for rel, data in files.items():
        with open(os.path.join(P, *rel.split("/")), "wb") as f:
            f.write(data)
    man = {"format": st.MANIFEST_FORMAT, "version": "2026.11.24-1",
           "files": {rel: {"sha256": hashlib.sha256(d).hexdigest(), "size": len(d)} for rel, d in files.items()}}
    man_bytes = json.dumps(man).encode("utf-8")
    with open(os.path.join(P, "manifest.json"), "wb") as f:
        f.write(man_bytes)
    open(os.path.join(P, st.TEST_ENV_MARK), "w").close()      # 시험 표시 - RPA_PROGRAMDATA 를 따르게 (진짜 ProgramData 를 읽지 않게)

    def sign(data=man_bytes, secret=up_secret):
        with open(os.path.join(P, "manifest.sig"), "w", encoding="ascii") as f:
            f.write(update_sign.sign(secret, data).hex() + "\n")
    sign()
    real_loose = ap_guard.loose_sources
    import server_info  # noqa: E402
    # 스탠드얼론 설치본의 server_info 조각은 빈 값 사본이다 (tools/build_release.blank_server_info)
    with patched(st, program_dir=lambda: P), patched(license_check, machine_guid=lambda: "pc-1"), \
            patched(ap_guard, loose_sources=lambda root, modules=None: real_loose(root, modules={})), patched(server_info, AUTH_HOST=""):
        os.environ["RPA_EDITION"] = "cloud"           # 설치본은 환경 변수가 아니라 프로그램 폴더의 edition.json 을 본다
        check("설치본 흉내가 맞다 (shipped·스탠드얼론·RPA_PROGRAMDATA 따름)",
              st.shipped() and edition.is_standalone() and license_check.license_path() == LIC)
        check("서명 맞음 → None", ap_guard.startup_problem() is None, ap_guard.startup_problem())
        check("manifest_signed 참", ap_guard.manifest_signed(P) is True)
        os.remove(os.path.join(P, "manifest.sig"))
        p = ap_guard.startup_problem()
        check("manifest.sig 없음 → 서명 글", p == "프로그램 파일의 서명을 확인하지 못했습니다. 같은 버전 설치 파일로 다시 설치하여 주십시오.", p)
        sign(b"other")
        check("manifest.sig 틀림 → 서명 글", (ap_guard.startup_problem() or "").startswith("프로그램 파일의 서명을 확인하지 못했습니다"))
        sign(secret=update_sign.keygen()[0])
        check("다른 열쇠로 한 서명 → 서명 글", (ap_guard.startup_problem() or "").startswith("프로그램 파일의 서명을 확인하지 못했습니다"))
        sign()
        with open(os.path.join(P, "rpa_dashboard.py"), "ab") as f:
            f.write(b"#")
        p = ap_guard.startup_problem() or ""
        check("목록의 파일 한 바이트 고침 → 바뀐 파일 + 같은 버전 설치 파일로 다시 설치",
              "바뀐 파일: rpa_dashboard.py" in p and "같은 버전 설치 파일로 다시 설치" in p and "[업데이트]" not in p, p)
        with open(os.path.join(P, "rpa_dashboard.py"), "wb") as f:
            f.write(files["rpa_dashboard.py"])
        with open(os.path.join(P, "app", "license_check.py"), "w", encoding="utf-8") as f:
            f.write("def load(*a, **k): return {}\n")
        p = ap_guard.startup_problem() or ""
        check("app\\license_check.py 를 끼움 → 그 이름이 든 글",
              p.startswith("프로그램 파일이 설치된 버전과 달라 실행하지 않습니다.") and "app\\license_check.py" in p
              and p.endswith("같은 버전 설치 파일로 다시 설치하여 주십시오."), p)
        os.remove(os.path.join(P, "app", "license_check.py"))
        with open(os.path.join(P, "app", "edition.pyc"), "wb") as f:
            f.write(b"x")
        check(".pyc 도 잡는다", "app\\edition.pyc" in (ap_guard.startup_problem() or ""))
        os.remove(os.path.join(P, "app", "edition.pyc"))
        os.remove(os.path.join(P, "app", "run_routine.cp314-win_amd64.pyd"))
        check("빠진 파일만 있으면 (mixed) 막지 않는다", st.check_install(P)["state"] == "mixed" and ap_guard.startup_problem() is None)
        with open(os.path.join(P, "app", "run_routine.cp314-win_amd64.pyd"), "wb") as f:
            f.write(b"pyd")
        check("다시 맞으면 None", ap_guard.startup_problem() is None)
        # 검토 2026-11-23 I-1: edition.json 하나만 지우면 일반 버전으로 보여 라이선스·복사 막기를 모두 건너뛰었다 (fail-open)
        ed_path = os.path.join(P, "edition.json")
        os.remove(ed_path)
        p = ap_guard.startup_problem()
        check("설치본에서 edition.json 을 지워도 스탠드얼론으로 보고 막는다 (그 이름이 든 글)",
              edition.is_standalone() and (p or "").startswith("프로그램 파일이 설치된 버전과 달라 실행하지 않습니다.") and "edition.json" in (p or ""), p)
        put_license(dict(BODY, pc_id="pc-9"))
        p = ap_guard.startup_problem()
        check("… 라이선스도 본다 (다른 PC 라이선스면 그 글)", "이 PC 의 라이선스가 아닙니다" in (p or ""), p)
        put_license()
        with open(ed_path, "w", encoding="utf-8") as f:
            f.write('{"edition": "cloud"}')
        p = ap_guard.startup_problem()
        check("edition.json 을 cloud 로 바꿔도 스탠드얼론으로 보고 막는다", edition.is_standalone() and bool(p), p)
        with open(ed_path, "wb") as f:
            f.write(files["edition.json"])
        with patched(server_info, AUTH_HOST="identitytoolkit.googleapis.com"):
            p = ap_guard.startup_problem()
            check("server_info 조각을 일반 버전 것으로 바꿔 끼워도 (edition.json 은 스탠드얼론) 막는다",
                  edition.is_standalone() and "server_info" in (p or ""), p)
        check("다시 맞으면 None (edition.json·빈 server_info)", ap_guard.startup_problem() is None, ap_guard.startup_problem())
        os.environ["RPA_EDITION"] = "standalone"

    print("일반 버전 설치본 흉내 (edition.json 없음·목록에도 없음·서명 파일 없음·주소가 찬 server_info)")
    C = os.path.join(TMP, "cloud_prog")
    os.makedirs(os.path.join(C, "app"))
    c_files = {"rpa_dashboard.py": b"print('dash')\n", "app/run_routine.cp314-win_amd64.pyd": b"pyd"}
    for rel, data in c_files.items():
        with open(os.path.join(C, *rel.split("/")), "wb") as f:
            f.write(data)
    with open(os.path.join(C, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"format": st.MANIFEST_FORMAT, "version": "2026.11.24-1",
                   "files": {rel: {"sha256": hashlib.sha256(d).hexdigest(), "size": len(d)} for rel, d in c_files.items()}}, f)
    os.environ["RPA_EDITION"] = "standalone"          # 설치본은 환경 변수를 따르지 않는다
    calls = []
    with patched(st, program_dir=lambda: C), patched(license_check, load=lambda *a, **k: calls.append(1)):
        check("설치본 흉내 (shipped)", st.shipped())
        check("일반 버전 설치본은 그대로 cloud·startup_problem None·라이선스를 읽지 않는다",
              edition.edition() == "cloud" and ap_guard.startup_problem() is None and not calls, f"{edition.edition()} {calls}")
        with patched(server_info, AUTH_HOST=""):
            check("빈 server_info 조각이면 edition.json·목록이 없어도 스탠드얼론 (컴파일 조각이 정한다)", edition.is_standalone())
        open(os.path.join(C, "manifest.sig"), "w").close()
        check("목록 서명 파일(manifest.sig, 스탠드얼론만 싣는다)이 있으면 스탠드얼론", edition.is_standalone())
        os.remove(os.path.join(C, "manifest.sig"))
        check("지우면 다시 cloud", edition.edition() == "cloud")
        saved = server_info.AUTH_HOST
        del server_info.AUTH_HOST                     # 옛 일반 버전 조각 (AUTH_HOST 칸이 생기기 전) - 업데이트가 일부만 된 PC
        try:
            check("AUTH_HOST 칸이 없는 옛 일반 server_info 는 cloud (스탠드얼론으로 잘못 보고 막지 않는다)",
                  edition.edition() == "cloud" and ap_guard.startup_problem() is None, edition.edition())
        finally:
            server_info.AUTH_HOST = saved
        with patched(server_info, PROJECT_ID=""):
            check("PROJECT_ID 가 빈 조각도 스탠드얼론", edition.is_standalone())
    os.environ["RPA_EDITION"] = "standalone"

    print("업무 주 모듈을 불러올 때의 가드 (python.exe -c 로 안쪽 함수를 직접 부르는 길)")
    import ast  # noqa: E402
    for mod in ("run_routine", "web_runner", "rpa_observer"):
        with open(os.path.join(ROOT, mod + ".py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        first_def = next(i for i, n in enumerate(tree.body) if isinstance(n, (ast.FunctionDef, ast.ClassDef)))
        calls_at = [i for i, n in enumerate(tree.body) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                    and ast.unparse(n.value.func) == "ap_guard.import_guard"]
        check(f"{mod}.py 는 함수를 만들기 전 맨 위에서 ap_guard.import_guard() 를 부른다", bool(calls_at) and calls_at[0] < first_def, str(calls_at))
    os.remove(LIC)
    with patched(st, program_dir=lambda: P), patched(license_check, machine_guid=lambda: "pc-1"), \
            patched(ap_guard, loose_sources=lambda root, modules=None: real_loose(root, modules={})), patched(server_info, AUTH_HOST=""):
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                ap_guard.import_guard()
            code = None
        except SystemExit as e:
            code = e.code
        check("설치본·라이선스 없음·시작 파일이 아닌 곳(python.exe)에서 불러오면 SystemExit(2), 까닭은 stderr",
              code == ap_guard.EXIT_BLOCKED and "라이선스 파일이 없습니다" in err.getvalue(), f"{code} {err.getvalue()!r}")
        with patched(sys, executable=os.path.join(P, "ERPia_RPA.exe")):
            try:
                ap_guard.import_guard()
                code = None
            except SystemExit as e:
                code = e.code
        check("시작 파일(프로그램 폴더의 ERPia_RPA.exe)로 켤 때는 건너뛴다 (main 이 확인하고 현황·알림 창으로 알린다)", code is None, code)
    with patched(st, program_dir=lambda: C):
        try:
            ap_guard.import_guard()
            code = None
        except SystemExit as e:
            code = e.code
    check("일반 버전 설치본에서는 아무것도 하지 않는다", code is None, code)
    try:
        ap_guard.import_guard()
        code = None
    except SystemExit as e:
        code = e.code
    check("소스로 돌 때(시험·개발 PC)는 아무것도 하지 않는다 (라이선스가 없어도)", code is None, code)
    put_license()
    fake_py = types.SimpleNamespace(__file__=os.path.join(TMP, "x", "license_check.py"))
    fake_pyd = types.SimpleNamespace(__file__=os.path.join(P, "app", "license_check.cp314-win_amd64.pyd"))
    fake_nuitka = types.SimpleNamespace(__file__=os.path.join(P, "app", "update_sign.py"), __compiled__=object())
    got = real_loose(P, modules={"license_check": fake_py, "update_sign": fake_nuitka, "edition": fake_pyd, "os": os})
    check("가드 조각이 .pyd 가 아닌 파일에서 불렸으면 잡는다 (컴파일된 조각·가드가 아닌 모듈은 그대로)",
          len(got) == 1 and "license_check.py" in got[0], str(got))
    check("rpa_status.tamper_text: 일반 버전은 지금 문장 그대로",
          "관리자에게 [업데이트]를 요청하여 주십시오." in (st.tamper_text({"state": "tampered", "modified": ["a.py"], "changed_count": 1})
                                                         if os.environ.update(RPA_EDITION="cloud") is None else ""))
    os.environ["RPA_EDITION"] = "standalone"
    t = st.tamper_text({"state": "tampered", "modified": ["a.py"], "changed_count": 1})
    check("스탠드얼론은 끝 문장이 같은 버전 설치 파일로 다시 설치", t.endswith("같은 버전 설치 파일로 다시 설치하여 주십시오.") and "[업데이트]" not in t, t)
    with patched(st, program_dir=lambda: P):
        with open(os.path.join(P, "edition.json"), "w", encoding="utf-8") as f:
            json.dump({"edition": "standalone", "test_build": True}, f)
        check("edition.test_build(): edition.json 의 test_build 가 true 면 True", edition.test_build() is True)
        with open(os.path.join(P, "edition.json"), "w", encoding="utf-8") as f:
            json.dump({"edition": "cloud", "test_build": True}, f)
        check("… 스탠드얼론이 아니면 False", edition.test_build() is False)

    # -----------------------------------------------------------------------------------------
    print("부르는 자리 (exe 셋의 main)")

    class Touched(Exception):
        pass

    def boom(*a, **k):
        raise Touched("ERPia·브라우저 쪽을 불렀다")

    os.remove(LIC)                                       # 라이선스 없음 → 막힌다
    import run_routine as rr
    import web_runner as wr
    import rpa_observer as ob
    rec = []
    fake_status = dict(start=lambda *a, **k: rec.append(("start",) + a), finish=lambda *a, **k: rec.append(("finish",) + a))
    with patched(rr.status, **fake_status), patched(rr, wellife_route=boom, run_modules=boom), patched(sys, argv=["ERPia_RPA.exe"]):
        try:
            code = rr.main()
        except Touched:
            code = "건드림"
    fin = [r for r in rec if r[0] == "finish"]
    check("PROCESS main: 2 를 돌려주고 현황을 stopped (사유 = 그 글) 로 닫는다, ERPia 를 건드리지 않는다",
          code == ap_guard.EXIT_BLOCKED and fin and fin[-1][1] == "stopped" and fin[-1][2].startswith("라이선스 파일이 없습니다"), f"{code} {rec}")
    rec.clear()
    with patched(wr.status, **fake_status), patched(wr, cmd_run=boom, cmd_selftest=boom), patched(sys, argv=["Prepare_RPA.exe", "--all"]):
        try:
            code = wr.main()
        except Touched:
            code = "건드림"
    fin = [r for r in rec if r[0] == "finish"]
    check("ACTOR main: 2 와 stopped (사유 = 그 글), 브라우저를 띄우지 않는다",
          code == ap_guard.EXIT_BLOCKED and fin and fin[-1][1] == "stopped" and fin[-1][2].startswith("라이선스 파일이 없습니다"), f"{code} {rec}")
    shown = []
    with patched(ob, show_error=lambda t: shown.append(t), start_problem=boom, sweep_profiles=boom), patched(ob.st, is_admin=lambda: True):
        try:
            code = ob.main([])
        except Touched:
            code = "건드림"
    check("옵저버 main: 관리자 권한 뒤 알림 창에 그 글, 2", code == ap_guard.EXIT_BLOCKED and shown and shown[0].startswith("라이선스 파일이 없습니다"),
          f"{code} {shown}")
    raw = io.BytesIO()
    out = io.TextIOWrapper(raw, encoding="utf-8")       # 옵저버는 stdout.reconfigure 를 부른다
    with patched(ob, sync_playwright=boom), contextlib.redirect_stdout(out):
        code = ob.main(["--check"])
        out.flush()
    text = raw.getvalue().decode("utf-8")
    check("옵저버 --check 는 막지 않고 '라이선스:' 줄을 찍고 끝 줄까지", "라이선스: 라이선스 파일이 없습니다" in text
          and ob.CHECK_DONE in text, text[-400:])
    out = io.StringIO()
    with contextlib.redirect_stdout(out), patched(wr, log=lambda m: print(m)):
        wr.cmd_check()
    check("ACTOR --check 에 '라이선스:' 줄", "라이선스: 라이선스 파일이 없습니다" in out.getvalue(), out.getvalue()[-400:])

    print("일반 버전에서 세 main 의 흐름은 그대로")
    os.environ["RPA_EDITION"] = "cloud"
    with patched(rr.status, **fake_status), patched(rr, wellife_route=boom), patched(sys, argv=["ERPia_RPA.exe"]):
        try:
            rr.main()
            went = False
        except Touched:
            went = True
    check("PROCESS main 이 가드를 지나 원래 흐름으로 (웰라이프 관문까지 간다)", went)
    with patched(wr.status, **fake_status), patched(wr, cmd_run=boom), patched(sys, argv=["Prepare_RPA.exe", "--all"]):
        try:
            wr.main()
            went = False
        except Touched:
            went = True
    check("ACTOR main 도 원래 흐름으로 (사이트 실행까지 간다)", went)
    with patched(ob, show_error=lambda t: None, start_problem=boom), patched(ob.st, is_admin=lambda: True):
        try:
            ob.main([])
            went = False
        except Touched:
            went = True
    check("옵저버 main 도 원래 흐름으로 (시작 확인까지 간다)", went)

    # -----------------------------------------------------------------------------------------
    print("사내 서버 연결 (사내 서버 ⑤ Task 2)")
    os.environ["RPA_EDITION"] = "standalone"
    import seat  # noqa: E402
    LINK = license_check.link_path()
    for _p in (LIC, LINK):
        if os.path.exists(_p):
            os.remove(_p)
    os.makedirs(os.path.dirname(LINK), exist_ok=True)
    seat_secret, seat_public = update_sign.keygen()
    SERVER_BODY = {"edition": "standalone", "kind": "server", "company": "시험상사", "cid": "c1", "server_id": "0" * 32,
                   "seat_pub": seat_public.hex(), "seats": 5, "modules": {}, "features": {}, "limits": {}}

    def put_link(guid="pc-1"):
        out = {"server_url": "https://192.168.1.230:8444", "pc_id": "pc_01", "agent_key": "a" * 64, "relay_key": "b" * 64,
               "ca_pem": "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"}
        doc = license_check.link_doc(out, seat.issue(seat_secret, "c1", "pc_01", guid, 1764100000000),
                                     license_check.sign_body(lic_secret, SERVER_BODY))
        with open(LINK, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)

    put_link()
    check("연결 파일만 있으면 startup_problem None (서버에 묻지 않는다 - 서버 주소는 닿지 않는 곳)",
          ap_guard.startup_problem() is None, ap_guard.startup_problem())
    check("check_line 은 사내 서버 줄",
          ap_guard.check_line() == "라이선스: 확인됨 (시험상사, 사내 서버 192.168.1.230, PC pc_01)", ap_guard.check_line())
    put_link(guid="pc-2")
    check("다른 PC 의 연결 파일 → 그 까닭으로 막힘", "이 PC" in (ap_guard.startup_problem() or ""), ap_guard.startup_problem())
    put_link()
    put_license()
    check("라이선스 + 연결 파일 → BOTH_TEXT", ap_guard.startup_problem() == license_check.BOTH_TEXT, ap_guard.startup_problem())
    check("--check 줄도 BOTH_TEXT", ap_guard.check_line() == f"라이선스: {license_check.BOTH_TEXT}", ap_guard.check_line())
    os.remove(LINK)
    check("라이선스만 → 지금 단독 동작 그대로 (None, 지금 줄)",
          ap_guard.startup_problem() is None and ap_guard.check_line() == "라이선스: 확인됨 (시험상사, PC 번호 pc-1)",
          (ap_guard.startup_problem(), ap_guard.check_line()))
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(TMP, ignore_errors=True)
print(f"\n실패: {len(fails)}" + (f" ({', '.join(fails)})" if fails else ""))
sys.exit(1 if fails else 0)
