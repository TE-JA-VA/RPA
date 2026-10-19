"""쇼핑몰 프리셋 시험 - 프리셋 파일·사용자 설정 Sites 의 PRESETn 칸·대시보드 요약·켬끔 (rpa_status),
프리페어의 replay (web_runner), 옵저버의 저장 전 확인 (rpa_observer). 창은 뜨지 않는다.

실제 설정은 건드리지 않는다. RPA_USER_CONFIG·RPA_PROGRAMDATA·RPA_STATUS_DIR 를 임시 폴더로.
    .venv\\Scripts\\python.exe tests\\test_presets.py
"""
import datetime
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="rpa_presets_")
os.environ["RPA_USER_CONFIG"] = os.path.join(TMP, "config", "RPA_UserConfig.json")
os.environ["RPA_PROGRAMDATA"] = os.path.join(TMP, "programdata")
os.environ["RPA_STATUS_DIR"] = os.path.join(TMP, "status")
os.environ["RPA_OBSERVER_LOCK"] = rf"Local\AFTER_MARKET_RPA_OBSERVER_PRESETS_TEST_{os.getpid()}"   # 개발 PC 의 진짜 에이전트가 기다리지 않게
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(TMP, "no_browsers")   # 배포판처럼 같이 싣는 브라우저가 없다 - 깔린 Edge 로만 뜬다
os.makedirs(os.path.join(TMP, "config"))
os.makedirs(os.path.join(TMP, "programdata", "config"))    # 새 구조로 보이게 (기록 폴더가 programdata\data 가 된다)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.stdout.reconfigure(encoding="utf-8")

import rpa_status as st  # noqa: E402

fails = []
_no = [0]


def check(name, cond, detail=""):
    _no[0] += 1
    print(f"  {_no[0]:2d}. [{'통과' if cond else '실패'}] {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(f"{_no[0]}. {name} {detail}")


def raw_config():
    with open(st.user_config_path(), encoding="utf-8") as f:
        return f.read()


def raises(exc, fn, *args):
    try:
        fn(*args)
        return None
    except exc as e:
        return e


PW = "프리셋-비밀번호-유출금지"
REC = {"version": 1, "start_url": "https://shop.example.com/login", "record_date": "2026-09-30",
       "steps": [{"kind": "goto", "page": 0, "url": "/login", "href": "https://shop.example.com/login", "gap": 0}]}
BASE = {"LogIn": {"AdminCode": "t", "ID": "erp", "PW": "erp-pw"}, "Routine": {"Login": "Y"},
        "Sites": {"SITE1": {"URL": "https://mail.example.com", "ID": "m", "PW": "mail-pw", "Action": "login", "Stts": 9}}}

print("=== 1. 프리셋 파일과 Sites 칸 (rpa_status) ===")
check("프리셋 파일 자리는 사용자 설정 옆", st.presets_path() == os.path.join(TMP, "config", "RPA_Presets.json"))
ps = st.read_presets()
check("파일이 없으면 빈 프리셋 둘", [p["no"] for p in ps] == [1, 2] and all(p["record"] is None for p in ps), str(ps))
st.write_presets([{"no": 7, "name": "지마켓", "code": "012", "saved_at": "2026-09-30T18:20:00", "record": REC},
                  st.blank_preset(2), {"no": 9, "name": "쿠팡", "code": "", "saved_at": None, "record": None}])
ps = st.read_presets()
check("쓰고 읽기 - 번호는 순서대로 다시 매긴다, 기록은 그대로", [p["no"] for p in ps] == [1, 2, 3]
      and ps[0]["name"] == "지마켓" and ps[0]["record"] == REC and ps[2]["name"] == "쿠팡", str(ps))
check("1개·41개는 거부 (2~40 - 웰라이프 업체 40, 2026-10-15)", all(raises(ValueError, st.write_presets, [st.blank_preset(i + 1) for i in range(n)])
                                  for n in (1, 41)))
check("사용자 설정이 없으면 Sites 를 새로 만들지 않는다", raises(FileNotFoundError, st.save_preset_sites, ps, {1: ("s", PW)}))
check("설정이 없으면 요약도 없음 (대시보드는 카드를 숨긴다)", st.preset_summary() is None)
st.write_user_config(BASE)
st.save_preset_sites(ps, {1: ("seller01", PW)})
cfg = st.read_user_config()
site = cfg["Sites"].get("PRESET1") or {}
check("기록 있는 프리셋만 칸이 생긴다, 처음엔 꺼짐 (Stts 9)", [k for k in cfg["Sites"] if k.startswith("PRESET")] == ["PRESET1"]
      and site.get("Stts") == 9 and site.get("Action") == ["replay"] and site.get("Preset") == 1 and site.get("note") == "지마켓"
      and site.get("URL") == REC["start_url"] and site.get("ID") == "seller01", str(site))
check("비밀번호는 잠겨서 들어가고 풀면 같다", PW not in raw_config() and st.unseal(site.get("PW")) == PW)
check("다른 섹션·다른 사이트는 그대로", cfg["LogIn"]["ID"] == "erp" and cfg["Routine"] == {"Login": "Y"}
      and st.unseal(cfg["Sites"]["SITE1"]["PW"]) == "mail-pw" and cfg["Sites"]["SITE1"]["Stts"] == 9)
cfg["Sites"]["PRESET1"]["Stts"] = 0
st.write_user_config(cfg)
ps[0]["name"] = "지마켓 판매자"
st.save_preset_sites(ps, {1: ("seller02", None)})
site = st.read_user_config()["Sites"]["PRESET1"]
check("다시 저장: 비밀번호를 안 주면 그대로, 켬/끔도 그대로, 이름·아이디는 새 값", st.unseal(site["PW"]) == PW
      and site["Stts"] == 0 and site["note"] == "지마켓 판매자" and site["ID"] == "seller02", str(site))
summary = st.preset_summary()
check("요약: 번호·이름·코드·단계 수·저장 시각·아이디 여부·켬·보관", summary[0] == {
      "no": 1, "name": "지마켓", "code": "012", "steps": 1, "saved_at": "2026-09-30T18:20:00", "has_login": True, "on": True, "backup": False}
      and summary[1]["steps"] == 0 and summary[1]["has_login"] is False, str(summary))
check("요약에는 기록 내용·아이디·비밀번호가 없다", all(set(s) == {"no", "name", "code", "steps", "saved_at", "has_login", "on", "backup"}
                                                  for s in summary) and "seller" not in json.dumps(summary, ensure_ascii=False))
check("켜기·끄기는 Stts 0/9 (키는 PRESET1·'1'·1 모두)",
      st.set_preset_switches({"PRESET1": False}) == {1: False} and st.read_user_config()["Sites"]["PRESET1"]["Stts"] == 9
      and st.set_preset_switches({"1": True}) == {1: True} and st.read_user_config()["Sites"]["PRESET1"]["Stts"] == 0
      and st.set_preset_switches({1: False}) == {1: False})
check("모르는 번호·번호가 아닌 키만 있으면 거부", raises(ValueError, st.set_preset_switches, {"PRESET7": True})
      and raises(ValueError, st.set_preset_switches, {"x": True}))
cfg = st.read_user_config()
cfg["Sites"]["PRESET1"]["PW"] = ""
st.write_user_config(cfg)
e = raises(ValueError, st.set_preset_switches, {"PRESET1": True})
check("비밀번호가 없는 프리셋은 켜지 않는다", e is not None and "아이디·비밀번호가 없습니다" in str(e), str(e))
check("끄기는 비밀번호가 없어도 된다", st.set_preset_switches({"PRESET1": False}) == {1: False})
st.save_preset_sites([dict(ps[0], record=None), ps[1], ps[2]], {})
check("기록을 지운 프리셋의 칸은 지운다", "PRESET1" not in st.read_user_config()["Sites"])
st.save_preset_sites(ps, {1: ("seller01", PW)})
st.save_preset_sites(ps, {1: ("seller01", None)}, phones={1: ("kim", ["15881234", "0212345678"])})
s1 = st.read_user_config()["Sites"]["PRESET1"]
check("인증 휴대폰·발신번호를 PRESETn 칸에 (휴대폰 중계 설계 13절)", s1.get("Phone") == "kim"
      and s1.get("SmsSenders") == ["15881234", "0212345678"] and s1.get("PW"), str({k: v for k, v in s1.items() if k != "PW"}))
st.save_preset_sites(ps, {1: ("seller01", None)})
check("휴대폰을 안 넘기면 있던 값 그대로", st.read_user_config()["Sites"]["PRESET1"].get("Phone") == "kim")
st.save_preset_sites(ps, {1: ("seller01", None)}, phones={1: ("", [])})
check("'(없음)' 으로 바꾸면 휴대폰 칸을 지운다", "Phone" not in st.read_user_config()["Sites"]["PRESET1"])
with open(st.presets_path(), "w", encoding="utf-8") as f:
    f.write("{깨진")
check("깨진 프리셋 파일은 ValueError (덮어쓰지 않게)", raises(ValueError, st.read_presets))
check("깨진 파일이면 요약은 없음 (빈 목록으로 속이지 않는다)", st.preset_summary() is None)
st.write_presets(ps)

print("=== 2. 옵저버 미리보기는 이력에만 ===")
st.start("observer", [("s1", "하나")], title="① 지마켓")
st.step("s1")
st.log_line("[10:00:00] 미리보기 성공")
st.finish("success")
rows = st.read_history(program="observer")
check("ACTOR 오토파일럿 미리보기는 이력에 '옵저버' 으로 남는다", bool(rows) and rows[0]["program_label"] == "옵저버", str(rows[:1]))
check("현황 카드(프로그램 목록)에는 안 나온다", "observer" not in st.dashboard_snapshot()["programs"])

print("=== 3. 관리자·계정 확인 (설정 창과 같이 쓴다) ===")
import rpa_settings as rs  # noqa: E402
check("계정 비교는 대소문자 무시", st.same_account("PC\\Me", "pc\\me") and not st.same_account("PC\\a", None))
check("설정 창은 같은 함수를 쓴다", rs.same_account is st.same_account and rs.session_user is st.session_user
      and rs.process_user is st.process_user and rs.is_admin is st.is_admin)

print("=== 4. 프리페어 replay (web_runner) ===")
import fake_mall  # noqa: E402
import web_replay  # noqa: E402
import web_runner as wr  # noqa: E402
from test_web_replay import hclick  # noqa: E402

TODAY = datetime.date.today()
# 프리페어는 PRESETn 만 본다 (사용자 2026-10-12: SITEn 방식을 쓰는 업체 없음). 설치 틀에 딸려 온 빈 예시 SITE1(켜짐)이
# 켜진 프리셋까지 막았다 - 옛 SITEn 칸은 지우지 않고 읽지만 않는다
cfg = st.read_user_config()
cfg["Sites"]["SITE1"] = {"URL": "https://ezsso.example.com", "ID": "", "PW": "", "Action": ["login"], "Stts": 0}
st.write_user_config(cfg)
check("프리페어 사이트 목록은 PRESETn 만 (빈 예시 SITE1 이 켜져 있어도 안 본다)", list(wr.load_config()) == ["PRESET1"], str(list(wr.load_config())))
check("옛 SITEn 칸은 설정에 그대로 남는다", "SITE1" in st.read_user_config()["Sites"])
# 새로 깐 PC 는 프리셋이 없다 - 점검(--check, 빌드가 끝 줄로 본다)은 오류가 아니라 끝까지 간다 (2026-10-12 빌드에서 걸림)
saved_cfg = st.read_user_config()
st.write_user_config(dict(saved_cfg, Sites={"_주석": ["안내"], "SITE1": saved_cfg["Sites"]["SITE1"]}))
lines = []
orig_log = wr.log
wr.log = lambda m="": lines.append(str(m))
try:
    rc = wr.cmd_check()
finally:
    wr.log = orig_log
st.write_user_config(saved_cfg)
check("프리셋이 없어도 점검은 0 으로 끝까지 (끝 줄 '쓸 수 있는 Action')",
      rc == 0 and any("쓸 수 있는 Action" in x for x in lines) and any("프리셋이 아직 없습니다" in x for x in lines), f"{rc} {lines}")
site = dict(st.read_user_config()["Sites"]["PRESET1"])
check("점검: 기록·코드가 있으면 문제 없음", wr.validate_site("PRESET1", site) == [], str(wr.validate_site("PRESET1", site)))
check("점검: 없는 프리셋 번호는 문제", any("기록이 없습니다" in x for x in wr.validate_site("PRESET1", dict(site, Preset=5))))
bad = st.read_presets()
bad[0]["code"] = "12"
st.write_presets(bad)
check("점검: 사이트코드가 세 자리가 아니면 문제", any("세 자리" in x for x in wr.validate_site("PRESET1", site)))
with open(st.presets_path(), "w", encoding="utf-8") as f:
    f.write("[깨진")
check("점검: 프리셋 파일이 깨졌으면 문제로 적는다", any("읽지 못했습니다" in x for x in wr.validate_site("PRESET1", site)))
check("대시보드 단계 이름은 '<프리셋 이름> 엑셀 받기'",
      wr.prepare_steps([("PRESET1", dict(site, note="지마켓"))]) == [("PRESET1:replay", "지마켓 엑셀 받기")])

srv, url, _ = fake_mall.start(TODAY, False)
srv.mall = mall = fake_mall.Mall(TODAY, False)


def human_e(page):
    hclick(page, page.get_by_placeholder("아이디"))
    page.keyboard.type(fake_mall.USER, delay=15)
    hclick(page, page.get_by_placeholder("비밀번호"))
    page.keyboard.type(fake_mall.PASSWORD, delay=15)
    hclick(page, page.get_by_role("button", name="로그인", exact=True))
    page.wait_for_url("**/main**")
    page.get_by_role("link", name="배송관리", exact=True).hover()
    hclick(page, page.get_by_role("link", name="송장전송", exact=True))
    fl = page.frame_locator("iframe[name=content]")
    with page.expect_download() as di:
        hclick(page, fl.get_by_role("button", name="송장 엑셀 받기", exact=True))
    di.value.path()


rec_e = web_replay.record(url + "/login", os.path.join(TMP, "rec_e.json"), headless=True, human=human_e, record_date=TODAY)
st.write_presets([{"no": 1, "name": "가짜몰", "code": "012", "saved_at": None, "record": rec_e}, st.blank_preset(2)])
st.save_preset_sites(st.read_presets(), {1: (fake_mall.USER, fake_mall.PASSWORD)})
st.set_preset_switches({"PRESET1": True})
DL = os.path.join(TMP, "ERPIA_AI_EXCEL")
wr.download_dir = lambda: DL           # 진짜 바탕화면 ERPIA_AI_EXCEL 대신
srv.mall = mall = fake_mall.Mall(TODAY, False)
code = wr.cmd_run(["PRESET1"], headless=True)
files = sorted(os.listdir(DL)) if os.path.isdir(DL) else []
check("프리페어가 켜진 프리셋을 재생해 (012)… 를 받는다", code == 0 and files == [f"(012)송장목록_{TODAY.isoformat()}.xlsx"]
      and mall.ship_downloads == [TODAY.isoformat()], str((code, files)))
row = st.read_history(program="prepare")[0]
check("이력: 단계 '가짜몰 엑셀 받기' 성공", [(s["label"], s["state"]) for s in row["steps"]] == [("가짜몰 엑셀 받기", "done")],
      str(row["steps"]))
logs = "\n".join(row["log_tail"])
check("이력 로그에 아이디·비밀번호가 없다", fake_mall.USER not in logs and fake_mall.PASSWORD not in logs, logs[-400:])
srv.mall = mall = fake_mall.Mall(TODAY, False)
cfg = st.read_user_config()
cfg["Sites"]["PRESET1"]["PW"] = "wrong-pw"
st.write_user_config(cfg)
code = wr.cmd_run(["PRESET1"], headless=True)
row = st.read_history(program="prepare")[0]
check("비밀번호가 틀리면 그 단계 실패로 끝나고 사유가 남는다", code == 1 and row["state"] != "success"
      and "단계에서 멈췄습니다" in (row["steps"][0].get("note") or ""), str(row["steps"]))
check("실패 사진은 받은 파일 폴더가 아니라 기록 폴더", not any(n.endswith(".png") for n in os.listdir(DL))
      and any(n.startswith("실패_") for n in os.listdir(wr.BASE_DIR)), str(os.listdir(DL)))
# 앞 사이트가 실패하고 마지막 사이트가 성공 - 실행은 '중단' 으로 끝나도 마지막 사이트의 단계는 '완료' (전엔 finish 가 '중단' 으로
# 덮어 기록 탭에 실패로 보였고 토큰 셈에서도 빠졌다, 2026-10-06)
st.write_presets([{"no": 1, "name": "가짜몰", "code": "012", "saved_at": None, "record": rec_e},
                  {"no": 2, "name": "가짜몰2", "code": "013", "saved_at": None, "record": rec_e}])
st.save_preset_sites(st.read_presets(), {2: (fake_mall.USER, fake_mall.PASSWORD)})     # ① 은 위의 틀린 비밀번호 그대로
st.set_preset_switches({"PRESET1": True, "PRESET2": True})
srv.mall = mall = fake_mall.Mall(TODAY, False)
code = wr.cmd_run(["PRESET1", "PRESET2"], headless=True)
row = st.read_history(program="prepare")[0]
check("앞 사이트 실패·마지막 사이트 성공: 실행은 중단, 마지막 사이트 단계는 완료로 남는다", code == 1 and row["state"] == "stopped"
      and [s["state"] for s in row["steps"]] == ["failed", "done"], str([(s["key"], s["state"]) for s in row["steps"]]))


def human_alert(page):
    hclick(page, page.get_by_role("link", name="로그인 정책", exact=True))     # 알림창 '로그인 정책: 비밀번호는 90일마다 바꿉니다'
    page.wait_for_timeout(300)


rec_alert = web_replay.record(url + "/login", os.path.join(TMP, "rec_alert.json"), headless=True, human=human_alert,
                              record_date=TODAY)
st.write_presets([{"no": 1, "name": "알림몰", "code": "014", "saved_at": None, "record": rec_alert}, st.blank_preset(2)])
site = dict(st.read_user_config()["Sites"]["PRESET1"], ID=fake_mall.USER, PW=fake_mall.PASSWORD, Code="014")   # 프리셋 파일만 바꿔치기 - Code 도 맞춘다
lines, real_log = [], wr.log
wr.log = lines.append
try:
    with web_replay.sync_playwright() as pw_:
        browser = web_replay.edge(pw_.chromium.launch)
        page = wr.prepare_page(browser.new_context().new_page())
        replayed = wr.action_replay(page, "PRESET1", site)
        page.evaluate("() => alert('재생 뒤 알림')")
        browser.close()
finally:
    wr.log = real_log
said = [x for x in lines if "로그인 정책" in x]
check("재생 중 알림창은 재생기 하나만 받는다 (프리페어 쪽 '브라우저 알림' 줄이 겹치지 않는다)", replayed
      and sum("-> 확인" in x for x in said) == 1 and not any("브라우저 알림" in x for x in said), "\n".join(said))
check("대시보드로 가는 알림 글은 20자로 줄인다", not any("바꿉니다" in x for x in lines), "\n".join(said))
check("재생이 끝나면 프리페어 쪽 알림 받기가 돌아온다", any("브라우저 알림" in x and "재생 뒤 알림" in x for x in lines),
      "\n".join(lines[-3:]))
srv.shutdown()


print("=== 5. 옵저버 저장 전 확인 (rpa_observer) ===")
import rpa_observer as rr  # noqa: E402

R = {"steps": [{"kind": "goto"}]}


def P(no, code="012", login="seller01", pw="", has_pw=True, record=R):
    return {"no": no, "name": f"몰{no}", "code": code, "id": login, "pw": pw, "has_pw": has_pw, "record": record}


check("문제 없으면 None", rr.validate_presets([P(1), P(2, code="013"), P(3, code="", record=None)]) is None)
check("사이트코드가 세 자리가 아니면 그 프리셋에서 막는다", (rr.validate_presets([P(1), P(2, code="13")]) or (0, ""))[0] == 2)
dup = rr.validate_presets([P(1), P(2, code="012")])
check("두 프리셋이 같은 사이트코드면 막는다 (루틴은 한 코드에 파일 하나 - Review Focus 2)", bool(dup) and dup[0] == 2
      and "012" in dup[1], str(dup))
check("아이디가 없으면 막는다", (rr.validate_presets([P(1, login=" ")]) or (0, ""))[0] == 1)
OTP_R = {"steps": [{"kind": "click", "otpSend": True}, {"kind": "otp"}]}
check("인증번호 단계가 있는데 인증 휴대폰이나 발신번호가 없으면 막는다 (설계 13절)",
      (rr.validate_presets([P(1, record=OTP_R)]) or (0, ""))[0] == 1
      and "인증 휴대폰" in (rr.validate_presets([dict(P(1, record=OTP_R), phone="kim", senders=" , ")]) or (0, ""))[1]
      and rr.validate_presets([dict(P(1, record=OTP_R), phone="kim", senders="1588-1234")]) is None)
check("발신번호는 숫자만, 쉼표로 여러 개, +82 는 0 으로 (휴대폰과 같은 꼴)",
      rr.senders_list("1588-1234, 02 123 4567; +82 90-258-0002") == ["15881234", "021234567", "0902580002"], rr.senders_list("+82 90-258-0002"))
check("휴대폰 앱·단축어와 같은 꼴 다섯 (맥 세션이 돌려 본 것, 2026-10-13)",
      rr.senders_list("+82 90-258-0002, +82902580002, +82 090-258-0002, 090-258-0002, 0902580002") == ["0902580002"] * 5,
      rr.senders_list("+82 90-258-0002, +82902580002, +82 090-258-0002, 090-258-0002, 0902580002"))
check("비밀번호가 저장돼 있지도 않고 치지도 않았으면 막는다", (rr.validate_presets([P(1, has_pw=False)]) or (0, ""))[0] == 1
      and rr.validate_presets([P(1, has_pw=False, pw="x")]) is None)
check("다른 계정의 관리자 권한이면 멈춘다 (비밀번호가 그 계정으로 잠긴다)",
      "다른 사용자의 관리자 권한" in (rr.start_problem(me="PC\\a", session="PC\\b") or "") and rr.start_problem(me="PC\\a", session="pc\\A") is None)


def no_cfg():
    raise FileNotFoundError("agent_config.json")


def bad_cfg():
    raise ValueError("설정에 빠진 항목: cid")


_steps = [{"kind": "click", "pick": {"prefix": ">>>"}, "row": {}}, {"kind": "click"}]
_pp = lambda steps, source="mail", prefix=">>>": rr.pick_problem([{"no": 3, "record": {"steps": steps}, "source": source, "prefix": prefix}])  # noqa: E731
check("메일 첨부파일: 저장 확인 - 문구 없음 / 그 문구 메일을 연 단계 없음 / 받기 단계 없음 (사용자 2026-10-14 문구)",
      _pp(_steps, prefix="  ") == (3, "메일 시작 문구를 넣어 주십시오.")
      and _pp([{"kind": "click"}]) == (3, "메일 시작 문구로 지정한 '>>>'(으)로 시작하는 메일을 찾지 못했습니다. "
                                         "'>>>'(으)로 시작하는 메일을 연 다음 첨부파일을 받는 것까지 기록해 주십시오.")
      and "파일 받기 단계가 없습니다" in (_pp(_steps) or (0, ""))[1]
      and _pp(_steps[:1] + [dict(_steps[1], download="a.xlsx")]) is None
      and _pp([{"kind": "click"}], source="shop") is None and rr.pick_problem([{"no": 1, "record": None, "source": "mail", "prefix": ""}]) is None)
check("오토파일럿 설정(에이전트 계정)이 없거나 깨졌으면 알리고 켜지지 않는다 (사용자 2026-10-14)",
      all("오토파일럿 설정을 먼저 해 주십시오" in (rr.setup_problem(f) or "") for f in (no_cfg, bad_cfg))
      and rr.setup_problem(lambda: {"cid": "c"}) is None)
st.start("prepare", ["a"])
st.flush()
busy = rr.busy_problem()
st.step("a")
st.done_step("skipped", "대상 없음")
_a = dict(st._find_step("a") or {})
st.finish("success")
check("받을 새 메일이 없으면 그 사이트 단계는 건너뜀·대상 없음 (토큰 안 씀, 메일 고르기 2026-10-14)",
      _a.get("state") == "skipped" and _a.get("note") == "대상 없음", _a)
check("RPA 가 돌고 있으면 ACTOR 오토파일럿을 안 연다 (RPA 가 화면·마우스를 쓴다)", "ACTOR 오토파일럿이 돌고 있습니다" in (busy or ""), str(busy))
check("켜면 옵저버 잠금을 쥔다 - 쥔 동안 대시보드는 RPA 를 안 띄우고 자동 실행은 기다린다",
      rr.busy_problem() is None and st.observer_open())
hold = st.hold_lock
st.hold_lock = lambda name: False
check("옵저버가 이미 떠 있으면 하나 더 안 연다", "이미 켜져" in (rr.busy_problem() or ""))
st.hold_lock = hold
exe, params = rr.self_command(["--x"])
check("소스로 돌 때 다시 띄우기는 파이썬 + 이 파일", exe == sys.executable and params[0].endswith("rpa_observer.py")
      and params[1:] == ["--x"])
r = subprocess.run([sys.executable, str(ROOT / "rpa_observer.py"), "--check"], capture_output=True, env=dict(os.environ),
                   timeout=120)
out = (r.stdout + r.stderr).decode("utf-8", "replace")
check("--check 는 창 없이 끝 줄을 찍고 관리자 권한을 묻지 않는다", r.returncode == 0 and rr.CHECK_DONE in out, out[-400:])
with open(st.presets_path(), "w", encoding="utf-8") as f:
    f.write("{깨진")
check("깨진 프리셋 파일이면 옵저버는 열지 않는다 (덮어쓰지 않게 - Review Focus 1)", raises(ValueError, rr.load_presets))


print("=== 6. 검토에서 나온 것 (2026-10-01 끝 검토) ===")
REC1 = {"version": 1, "start_url": "https://shop.example.com/login", "steps": [{"kind": "goto", "href": "https://shop.example.com/login"}]}


def put_presets(data):
    with open(st.presets_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


good = [{"no": 1, "name": "몰1", "code": "012", "saved_at": None, "record": REC1},
        {"no": 2, "name": "몰2", "code": "013", "saved_at": None, "record": None}]
put_presets([good[0], dict(good[1], no=3)])
check("손으로 가운데 프리셋을 지워 번호가 비면 ValueError (다른 쇼핑몰 계정과 엮이지 않게)", raises(ValueError, st.read_presets))
put_presets([good[0], dict(good[1], record="oops")])
check("기록 모양이 틀리면 ValueError (빈 프리셋으로 바꿔 읽지 않는다)", raises(ValueError, st.read_presets))
put_presets([dict(good[0], no=i, code=f"{i:03d}") for i in range(1, 42)])
check("41개면 ValueError (뒤를 잘라 읽지 않는다)", raises(ValueError, st.read_presets))
put_presets([good[0], dict(good[1], code="012", record=REC1)])
check("기록 있는 두 프리셋이 같은 사이트코드면 ValueError", raises(ValueError, st.read_presets))
put_presets([good[0], dict(good[1], saved_at=12)])
check("저장 시각이 글자가 아니면 ValueError (대시보드 그리기가 멈추지 않게)", raises(ValueError, st.read_presets))
put_presets(good)
check("제대로 된 파일은 그대로 읽힌다", [p["no"] for p in st.read_presets()] == [1, 2])

real_replace, tries = os.replace, []


def flaky_replace(a, b):
    tries.append(b)
    if len(tries) < 3:
        raise PermissionError(5, "다른 프로그램이 읽는 중")
    return real_replace(a, b)


os.replace = flaky_replace
try:
    ok = not raises(PermissionError, st.write_presets, good)
finally:
    os.replace = real_replace
check("프리셋 파일을 에이전트가 읽는 순간이면 몇 번 다시 쓴다 (사용자 설정과 같다)", ok and len(tries) == 3, str(tries))

real_wp = st.write_presets
st.write_presets = lambda presets: (_ for _ in ()).throw(PermissionError(5, "거부"))
try:
    msg = rr.store(good, {1: ("seller01", None)})
finally:
    st.write_presets = real_wp
check("저장이 안 되면 화면에 보일 문장을 돌려준다 (콘솔 없는 exe 에서 조용히 넘어가지 않게)",
      "저장하지 못했습니다" in (msg or ""), str(msg))
check("저장이 되면 None", rr.store(good, {}) is None)

two_page = {"version": 1, "start_url": "https://shop.example.com/login",
            "steps": [{"kind": "fill", "value": "seller01", "target": {"tag": "input"}},
                      {"kind": "click", "target": {"tag": "button", "text": "다음"}},
                      {"kind": "secret", "credential": "PW"},
                      {"kind": "fill", "value": "다른 글자", "target": {"tag": "input"}}]}
scrubbed = rr.scrub_login(json.loads(json.dumps(two_page)), "seller01")
check("두 쪽 로그인: 아이디를 친 칸도 '설정의 아이디' 로 바꾸고 값을 지운다 (아이디가 기록에 안 남게)",
      scrubbed["steps"][0].get("credential") == "ID" and "value" not in scrubbed["steps"][0]
      and scrubbed["steps"][3].get("value") == "다른 글자" and "seller01" not in json.dumps(scrubbed), str(scrubbed["steps"][0]))

css_rec = {"version": 1, "start_url": "https://admin.example.com/", "steps": [
    {"kind": "click", "target": {"tag": "a", "css": "#admin-menu", "text": "admin"}, "url": "/admin"}]}
quote_rec = {"version": 1, "start_url": "", "steps": [{"kind": "fill", "value": 'x ab"cd!9 y', "target": {"tag": "input"}}]}
check("비밀번호 확인은 친 값·친 주소만 본다 (짧은 비밀번호가 메뉴 이름과 같아도 저장된다)",
      not rr.password_in_record(css_rec, "admin"))
check("따옴표가 든 비밀번호를 칸에 친 것도 잡는다", rr.password_in_record(quote_rec, 'ab"cd!9'))

st.write_user_config({"LogIn": {"AdminCode": "t", "ID": "erp", "PW": "erp-pw"},
                      "Sites": {"PRESET1": {"URL": "https://shop.example.com/login", "ID": "old", "PW": "pw", "Action": ["replay"],
                                            "Stts": 0, "Preset": 1, "note": "몰1"}}})
st.save_preset_sites(good, {1: ("seller01", None)})
kept = st.read_user_config()["Sites"]["PRESET1"]["Stts"]
st.save_preset_sites(good, {1: ("seller01", None)}, fresh={1})
fresh = st.read_user_config()["Sites"]["PRESET1"]["Stts"]
check("다시 기록한 프리셋은 꺼진 채로 (확인 전에 자동 실행에 끼지 않게), 손대지 않은 것은 켬 그대로",
      kept == 0 and fresh == 9, f"kept={kept} fresh={fresh}")

with web_replay.sync_playwright() as pw_:
    browser = web_replay.edge(pw_.chromium.launch)
    lines = []
    r = web_replay.Replayer(browser.new_context(), {"version": 1, "start_url": "", "steps": [
        {"kind": "goto", "page": 0, "href": "http://127.0.0.1:9/login?sid=SECRET1", "gap": 0}]},
        {"ID": "", "PW": ""}, os.path.join(TMP, "q"), "012", hide_values=True, log=lines.append)
    ok = r.run()
    browser.close()
check("대시보드로 가는 실패 사유·로그에는 주소의 ? 뒤가 없다", not ok and "SECRET1" not in r.results[-1][2]
      and not any("SECRET1" in x for x in lines), str(r.results[-1:]))

print("=== 7. 미룬 것 손질 (2026-10-02) ===")
REC2 = {"version": 1, "start_url": "https://shop2.example.com/login", "steps": [{"kind": "goto", "href": "https://shop2.example.com/"}]}
old = {1: {"no": 1, "name": "몰1", "code": "012", "saved_at": "2026-09-30T10:00:00", "record": REC1},
       2: {"no": 2, "name": "몰2", "code": "013", "saved_at": "2026-09-30T11:00:00", "record": REC2}}
NOW = "2026-10-02T09:00:00"


def files_now():
    return json.loads(json.dumps([old[1], dict(old[2], name="몰2 새 이름"),
                                  {"no": 3, "name": "몰3", "code": "014", "saved_at": None, "record": REC1},
                                  {"no": 4, "name": "프리셋 4", "code": "", "saved_at": None, "record": None}]))


got = [f["saved_at"] for f in rr.keep_dates(files_now(), old, set(), NOW)]
check("저장 날짜: 바뀐 프리셋(이름·새 기록)만 오늘, 그대로인 것은 원래 날짜, 기록 없는 것은 없음",
      got == ["2026-09-30T10:00:00", NOW, NOW, None], str(got))
got = [f["saved_at"] for f in rr.keep_dates(files_now(), old, {1}, NOW)]
check("저장 날짜: 아이디·비밀번호만 바꿔도 그 프리셋은 오늘", got[0] == NOW, str(got))
got = [f["saved_at"] for f in rr.keep_dates(files_now(), {}, set(), NOW)]
check("저장 날짜: 예전 파일을 못 읽었으면 기록 있는 것은 모두 오늘", got == [NOW, NOW, NOW, None], str(got))

tmp_root = os.path.join(TMP, "temp_root")
stale = os.path.join(tmp_root, rr.PROFILE_PREFIX + "old", "Default")
os.makedirs(stale)
other = os.path.join(tmp_root, "남의_폴더")
os.makedirs(other)
rr.sweep_profiles(tmp_root)
check("지난번에 못 지운 브라우저 프로필(로그인 쿠키)은 옵저버를 켤 때 지운다, 다른 폴더는 그대로",
      not os.path.exists(os.path.dirname(stale)) and os.path.isdir(other), str(os.listdir(tmp_root)))


class NoBrowser:
    class chromium:
        @staticmethod
        def launch_persistent_context(*a, **k):
            raise RuntimeError("브라우저 없음")


import glob  # noqa: E402

pattern = os.path.join(tempfile.gettempdir(), rr.PROFILE_PREFIX + "*")
before = set(glob.glob(pattern))
e = raises(RuntimeError, rr.launch, NoBrowser)
check("브라우저를 못 띄우면 만든 프로필 폴더도 지운다", e is not None and set(glob.glob(pattern)) == before,
      str(set(glob.glob(pattern)) - before))

print("=== 8. 콘솔 없이 켜진 exe (2026-10-02 첫 실행) ===")
NO_CONSOLE = r"""
import ctypes, sys
for n in (-10, -11, -12):           # Nuitka attach exe 를 시작 메뉴·관리자 권한으로 켰을 때처럼
    ctypes.windll.kernel32.SetStdHandle(n, ctypes.c_void_p(-1))
sys.stderr = None
import rpa_observer as rr
if sys.argv[1] == "fix":
    rr.fix_std_handles()
from playwright.sync_api import sync_playwright
try:
    with sync_playwright():
        pass
    print("드라이버 뜸")
except OSError as e:
    print(f"WinError {e.winerror}")
"""
got = {m: subprocess.run([sys.executable, "-c", NO_CONSOLE, m], cwd=ROOT, capture_output=True, timeout=60,
                         env=dict(os.environ, PYTHONIOENCODING="utf-8")).stdout.decode("utf-8", "replace").strip()
       for m in ("as_is", "fix")}
check("표준 핸들이 못 쓰는 값이면 그대로는 WinError 6, fix_std_handles 뒤에는 Playwright 드라이버가 뜬다",
      got["as_is"].endswith("WinError 6") and got["fix"].endswith("드라이버 뜸"), str(got))

orig_read = wr.status.read_presets
wr.status.read_presets = lambda: [{"no": 2, "code": "012", "record": OTP_R}]
no_phone = wr._replay_problems("PRESET2", {"Preset": 2})
with_phone = wr._replay_problems("PRESET2", {"Preset": 2, "Phone": "kim", "SmsSenders": ["15881234"]})
wr.status.read_presets = orig_read
check("ACTOR 오토파일럿은 인증 휴대폰이 없는 인증번호 프리셋을 시작하지 않는다 (까닭을 남김)", no_phone and "인증 휴대폰" in no_phone[0] and with_phone == [],
      (no_phone, with_phone))

print("=== 업체별 프리셋 수 (에이전트가 적은 업체 정책, 사용자 2026-10-14) ===")
import rpa_dashboard as dash  # noqa: E402


def policy_presets(v):
    cfg = st.read_settings()
    cfg["schedule"]["policy"] = dict(cfg["schedule"].get("policy") or {}, presets=v)
    st.write_settings(cfg)


policy_presets(None)
check("업체 프리셋 수를 모르면 기본 2개", st.preset_limit() == 2, st.preset_limit())
dash.set_policy(2, [], False, 5)
check("에이전트가 적은 업체 프리셋 수를 쓴다 (set_policy 4번째)", st.preset_limit() == 5, st.preset_limit())
check("프리셋 수만 바뀌어도 다시 적는다", dash.set_policy(2, [], False, 6) is True and st.preset_limit() == 6)
bad = []
for v in (1, 41, "5", True, -3):
    policy_presets(v)
    bad.append(st.preset_limit())
check("이상한 값(2 미만·40 초과·글자·참거짓)이면 기본 2개", bad == [2] * 5, bad)
policy_presets(40)
check("웰라이프 업체 40 (에이전트가 적는다)", st.preset_limit() == 40, st.preset_limit())
policy_presets(2)
wr.status.read_presets = lambda: [{"no": n, "code": "012", "record": REC} for n in (1, 2, 3)]
over, under = wr._replay_problems("PRESET3", {"Preset": 3}), wr._replay_problems("PRESET2", {"Preset": 2})
wr.status.read_presets = orig_read
check("업체 프리셋 수를 넘는 프리셋은 ACTOR 오토파일럿이 돌리지 않는다 (까닭을 남김)", over and "프리셋 수" in over[0] and under == [], (over, under))
policy_presets(None)

print("=== 업체별 동시 실행 창 수 (관리 화면, 사용자 2026-10-16) ===")
check("정하지 않았으면 하나씩 (1)", st.parallel_limit() == 1, st.parallel_limit())
check("에이전트가 적은 값을 쓴다 (set_policy 5번째), 그 값만 바뀌어도 다시 적는다",
      dash.set_policy(2, [], False, None, 4) is True and st.parallel_limit() == 4 and dash.set_policy(2, [], False, None, 6) is True
      and st.parallel_limit() == 6)
bad = []
for v in (0, 17, "4", True, -1):
    cfg = st.read_settings()
    cfg["schedule"]["policy"]["parallel"] = v
    st.write_settings(cfg)
    bad.append(st.parallel_limit())
check("이상한 값(1 미만·16 초과·글자·참거짓)이면 1", bad == [1] * 5, bad)
dash.set_policy(2, [], False, None, None)

print("=== 옵저버 [파일에서 불러오기]·[파일로 내보내기] (설계 2026-10-19 4.2절) ===")
from types import SimpleNamespace  # noqa: E402

FREC = {"version": st.RECORD_VERSION, "start_url": "https://store.example.com/login", "record_date": "2026-10-19",
        "viewport": {"width": 900, "height": 640},
        "steps": [{"kind": "goto", "page": 0, "url": "/login", "href": "https://store.example.com/login", "gap": 0},
                  {"kind": "fill", "page": 0, "credential": "ID", "target": {"tag": "input"}, "gap": 10},
                  {"kind": "secret", "page": 0, "credential": "PW", "target": {"tag": "input"}, "gap": 10}]}
FILE = {"kind": "autopilot-preset", "version": 1, "exported_at": "2026-10-19T10:00:00", "from": {"cid": "c", "pcId": "pc_a", "no": 3},
        "no": 3, "name": "스마트스토어", "code": "013", "record": FREC}
check("새 프리셋 칸에는 head (수정으로 남긴 앞부분) 가 있고 비어 있다", rr.new_preset(1).get("head", 1) is None)
p = rr.new_preset(1, "지마켓", "012")
p.update(id="seller01", has_pw=True, phone="kim", senders="1588-1234", loaded={"steps": [{"id": 0, "kind": "goto"}]}, deleted={0},
         enabled={0: "x"}, otp={0: True}, head={"steps": []}, viewport={"width": 1, "height": 1})
rr.load_file_into(p, FILE)
check("다른 사이트코드의 파일을 불러오면 아이디·비밀번호·인증 휴대폰을 비운다 (Global Constraints)",
      p["id"] == "" and p["pw"] == "" and p["has_pw"] is False and p["phone"] == "" and p["senders"] == "", str({k: p[k] for k in ("id", "pw", "has_pw", "phone", "senders")}))
check("이름·사이트코드·기록(단계마다 id)·창 크기를 파일 것으로, 저장 전까지 새로 기록한 것과 같게 (fresh)",
      p["name"] == "스마트스토어" and p["code"] == "013" and [s["id"] for s in p["loaded"]["steps"]] == [0, 1, 2]
      and p["loaded"]["steps"][0]["kind"] == "goto" and p["viewport"] == FREC["viewport"] and p["fresh"] is True and p["raw"] == []
      and p["head"] is None and p["deleted"] == set() and p["enabled"] == {} and p["otp"] == {} and p["source"] == "shop",
      str({k: p[k] for k in ("name", "code", "fresh", "raw", "head", "deleted", "enabled", "otp", "source")}))
check("파일을 고쳐도 원본 dict 는 그대로 (파일 record 에 id 가 안 붙는다)", "id" not in FILE["record"]["steps"][0])
p2 = rr.new_preset(2, "스토어", "013")
p2.update(id="seller02", has_pw=True, phone="kim", senders="1588-1234")
rr.load_file_into(p2, FILE)
check("같은 사이트코드면 아이디·비밀번호·인증 휴대폰은 그대로", p2["id"] == "seller02" and p2["has_pw"] is True and p2["phone"] == "kim"
      and p2["senders"] == "1588-1234" and p2["name"] == "스마트스토어", str({k: p2[k] for k in ("id", "has_pw", "phone", "senders")}))
mail_rec = dict(FREC, steps=FREC["steps"][:1] + [{"kind": "click", "page": 0, "pick": {"prefix": ">>>"}, "row": {}, "gap": 0},
                                                 {"kind": "click", "page": 0, "download": "a.xlsx", "gap": 0}])
p3 = rr.new_preset(3)
rr.load_file_into(p3, dict(FILE, code="014", record=mail_rec))
check("메일 고르기 단계가 든 파일이면 메일 첨부파일·시작 문구로", p3["source"] == "mail" and p3["prefix"] == ">>>", str((p3["source"], p3["prefix"])))
told = []
fake = SimpleNamespace(presets=[dict(rr.new_preset(1), fresh=True, loaded=FREC)], cur=0, tell=lambda t, x: told.append(x))
rr.App.export_file(fake)
fake.presets[0].update(fresh=False, loaded=None, raw=[], head=None)
rr.App.export_file(fake)
check("내보내기: 저장 안 한 칸(fresh)·기록 없는 칸은 '저장한 뒤 내보내 주십시오.'", told == ["저장한 뒤 내보내 주십시오."] * 2, str(told))
asked, told[:] = [], []
_orig_export = rr.pt.export_item
rr.pt.export_item = lambda no, **kw: (asked.append(no), (_ for _ in ()).throw(ValueError("시험")))[1]
fake.status = SimpleNamespace(config=lambda **kw: None)
fake.presets[0].update(fresh=False, loaded=None, raw=[{"kind": "goto", "page": 0, "href": "https://x/"}])
rr.App.export_file(fake)
fake.presets[0].update(raw=[], head={"steps": []})
rr.App.export_file(fake)
rr.pt.export_item = _orig_export
check("내보내기: 기록해서 저장한 칸(raw 또는 head 있음·loaded None·fresh False) 은 export_item 까지 간다 (Task 6 검토 지적)",
      asked == [1, 1] and told == [], str((asked, told)))
check("내보내기 파일 이름은 프리셋_번호_이름.json (파일에 못 쓰는 글자는 _)",
      rr.export_name(3, 'a/b:c*d?e<f>g|h"') == "프리셋_3_a_b_c_d_e_f_g_h_.json", rr.export_name(3, 'a/b:c*d?e<f>g|h"'))

print("=== 옵저버 [수정] 화면 쪽 (최종 고침 A7·A8·A9·A11) ===")
LREC = dict(FREC, steps=[dict(s, id=k) for k, s in enumerate(FREC["steps"] + [
    {"kind": "click", "page": 0, "target": {"tag": "a", "text": "요청", "css": "#req", "textCount": 1}, "gap": 10},
    {"kind": "click", "page": 0, "target": {"tag": "a", "text": "다운로드", "css": "#dl", "textCount": 3}, "gap": 10, "appearsAfter": 3, "download": "a.xlsx"},
    {"kind": "click", "page": 0, "target": {"tag": "a", "text": "닫기", "css": "#x", "textCount": 1}, "gap": 10}])])
said = []
p = rr.new_preset(1, "지마켓", "012")
p.update(loaded=json.loads(json.dumps(LREC)), deleted={1, 5}, enabled={0: True, 2: False, 4: True, 5: True}, otp={1: False, 5: False})
fake = SimpleNamespace(presets=[p], previewing=True, paused=True, stopping=False, editing=True, failed_at=None, recording=None, shown=3,
                       status=SimpleNamespace(config=lambda **kw: said.append(kw.get("text"))), render=lambda: None)
fake._final = lambda q: rr.App._final(fake, q)
rr.App._start_edit(fake, 0, 4)
check("A11: cut(아직 안 한 단계 id 4) 앞까지만 남긴다 - 꺼 둔·지운 단계 포함, cut 뒤의 꺼 둔·지운·인증번호 표시는 버린다",
      [s["id"] for s in p["head"]["steps"]] == [0, 1, 2, 3] and p["deleted"] == {1} and p["enabled"] == {0: True, 2: False} and p["otp"] == {1: False}
      and p["raw"] == [] and p["fresh"] is True, str({k: p[k] for k in ("deleted", "enabled", "otp", "raw", "fresh")}))
check("A10: 남긴 앞부분(head)에 잘린 단계를 cut 으로 둔다 (이어 기록 첫 단계가 '몇 단계 뒤에 새로 생긴 것' 을 이어받게)",
      p["head"].get("cut") == LREC["steps"][4] and p["head"]["start_url"] == FREC["start_url"], str(p["head"].get("cut")))
check("A11: 미리보기 상태를 내리고 기록 중으로", fake.previewing is False and fake.paused is False and fake.editing is False and fake.failed_at is None
      and fake.recording == 0 and fake.shown == 0)
check("A7: 상태 글은 업무 서식", said and said[-1] == "● ① 지마켓 이어서 기록 중입니다. 마치면 [■ 기록 완료]를 눌러 주십시오.", str(said))
final = fake._final(p)
check("A10: 이어 붙인 기록에는 cut 이 남지 않는다", "cut" not in final and [s["id"] for s in final["steps"]] == [0, 1, 2, 3], str(final.keys()))


class FakeBtn:
    def __init__(self):
        self.calls, self.colors = [], ("c", "d")

    def config(self, **kw):
        self.calls.append(kw)

    def pack(self, **kw):
        pass

    def pack_forget(self):
        pass

    def state(self):
        return next((c["state"] for c in reversed(self.calls) if "state" in c), None)


def painted(**flags):
    f = SimpleNamespace(recording=None, previewing=True, paused=True, stopping=False, closing=False, editing=False, failed_at=None,
                        rec_btn=FakeBtn(), prev_btn=FakeBtn(), save_btn=FakeBtn(), edit_btn=FakeBtn(), import_btn=FakeBtn(), export_btn=FakeBtn(),
                        paint_presets=lambda: None, toggle_pause=None, stop_preview=None, preview=None, save=None, cur=0, presets=[p])
    f.__dict__.update(flags)
    rr.App.paint_buttons(f)
    return f


f = painted(editing=True)
check("A8: [수정] 직후 editing 중에도 [■ 중단] 은 열려 있다 (파일 받기를 기다리는 단계면 최대 5분 멈출 수 없었다)",
      f.save_btn.state() == "normal" and f.prev_btn.state() == "disabled" and f.edit_btn.state() == "disabled", str((f.save_btn.state(), f.prev_btn.state())))
f = painted(stopping=True)
check("A8: 중단하는 중이면 [■ 중단] 도 잠긴다", f.save_btn.state() == "disabled")
f = painted(closing=True)
check("A8: 창을 닫는 중이면 [■ 중단] 도 잠긴다", f.save_btn.state() == "disabled")
said = []
f = SimpleNamespace(previewing=True, paused=True, stopping=False, closing=False, editing=True, failed_at=None, paint_buttons=lambda: None,
                    status=SimpleNamespace(config=lambda **kw: said.append(kw.get("text"))), on_preview_done=lambda ok: None, _close_now=lambda: None)
closed = rr.App._preview_done(f, True, ["a.xlsx"], 12.3, None)
check("A8: 마지막 단계가 성공해 [수정] 이 무시되면 상태 글로 알린다", closed is False and f.editing is False and f.previewing is False
      and said[-1] == "마지막 단계까지 끝나 수정할 자리가 없습니다. 미리보기 성공 (12초) - 받은 파일: a.xlsx", str(said))
f.editing, f.previewing = False, True
rr.App._preview_done(f, True, [], 3.0, None)
check("A8: [수정] 을 안 눌렀으면 지금 글 그대로", said[-1] == "미리보기 성공 (3초) - 받은 파일: 없음", str(said))
f.closing = True
check("A8: 닫는 중이면 _close_now 로 True", rr.App._preview_done(f, False, [], 0, None) is True)
asked = []
hp = dict(rr.new_preset(2, "헤드만", "013"), head={"steps": []}, loaded=None, raw=[])
f = SimpleNamespace(recording=None, previewing=False, presets=[hp], cur=0, _store_fields=lambda: None, start_url=None, shown=0,
                    ask=lambda t, x: (asked.append(x), False)[1], status=SimpleNamespace(config=lambda **kw: None), render=lambda: None)
rr.App.toggle_record(f)
tmp_file = os.path.join(TMP, "preset_file.json")
with open(tmp_file, "w", encoding="utf-8") as fh:
    json.dump(FILE, fh, ensure_ascii=False)
_orig_open = rr.filedialog.askopenfilename
rr.filedialog.askopenfilename = lambda **kw: tmp_file
try:
    rr.App.import_file(f)
finally:
    rr.filedialog.askopenfilename = _orig_open
check("A9: head 만 남은 칸도 '기록이 있다' - 다시 기록·파일에서 불러오기 전에 묻는다 (묻지 않고 지우지 않는다)",
      len(asked) == 2 and hp["head"] == {"steps": []} and hp["name"] == "헤드만", str((asked, hp["head"], hp["name"])))

print("=== 고른 프리셋 지우기 - 번호에 묶인 값이 따라온다 (이슈 #13) ===")
import preset_transfer as pt  # noqa: E402


def _rec(no):
    return dict(FREC, start_url=f"https://shop{no}.example.com/login", steps=json.loads(json.dumps(FREC["steps"])))


def _site(no):
    return {"URL": f"https://shop{no}.example.com/login", "ID": f"seller0{no}", "PW": st.seal(f"pw-{no}"), "Action": ["replay"],
            "Stts": 0 if no % 2 == 0 else 9, "Preset": no, "Code": f"0{no}1", "note": f"몰{no}", "Phone": f"phone{no}", "SmsSenders": [f"1588000{no}"]}


def _side_path(kind, no):
    return {"mail": st.mail_memory_path, "session": lambda n: st.session_path(st.preset_site_key(n)), "backup": pt.backup_path}[kind](no)


def _seed(n=5):
    st.write_user_config({"LogIn": {"ID": "erp", "PW": "erp-pw"}, "Sites": {"SITE1": {"URL": "https://mail.example.com", "ID": "m", "PW": "x",
                          "Action": "login", "Stts": 9}, **{f"PRESET{i}": _site(i) for i in range(1, n + 1)}}})
    st.write_presets([{"no": i, "name": f"몰{i}", "code": f"0{i}1", "saved_at": f"2026-10-0{i}T10:00:00", "record": _rec(i)} for i in range(1, n + 1)])
    for kind in ("mail", "session", "backup"):
        for i in range(1, n + 1):
            os.makedirs(os.path.dirname(_side_path(kind, i)), exist_ok=True)
            with open(_side_path(kind, i), "w", encoding="utf-8") as fh:
                json.dump({"kind": kind, "of": i}, fh)


def _side(kind, no):
    p = _side_path(kind, no)
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)["of"]


def _app():
    asked, said, titles = [], [], []
    f = SimpleNamespace(presets=rr.load_presets(), cur=0, recording=None, previewing=False, shown=0, start_url=None, unsaved_drop=False,
                        _store_fields=lambda: None, _load_fields=lambda: None, render=lambda: None, select=lambda i: None,
                        ask=lambda t, x: (asked.append(x), titles.append(t), True)[2], status=SimpleNamespace(config=lambda **kw: said.append(kw.get("text"))))
    f._final = lambda q: rr.App._final(f, q)
    f._kept = lambda q, final: list(range(len(final["steps"])))
    f.asked, f.said, f.titles = asked, said, titles
    return f


def _sites_now():
    return st.read_user_config()[st.SITES_SECTION]


_seed()
app = _app()
check("불러온 칸은 원래 번호(orig)를 들고 있고 새 칸은 None", [p.get("orig") for p in app.presets] == [1, 2, 3, 4, 5] and rr.new_preset(6).get("orig", 0) is None)
app.cur = 2
rr.App.remove_preset(app)
check("[−] 는 고른 프리셋(③)을 지우고 번호를 당긴다 - 기록이 있어 묻는다", [p["name"] for p in app.presets] == ["몰1", "몰2", "몰4", "몰5"]
      and app.cur == 2 and len(app.asked) == 1 and "③ 몰3" in app.asked[0], str((app.asked, [p["name"] for p in app.presets], app.cur)))
r = rr.App.save(app)
sites = _sites_now()
check("저장: 새 ③ 의 Sites 는 옛 ④ 의 아이디·비밀번호·켬끔·휴대폰, 새 ④ 는 옛 ⑤, PRESET5 는 없다",
      r == st.presets_path() and sites["PRESET3"]["ID"] == "seller04" and st.unseal(sites["PRESET3"]["PW"]) == "pw-4"
      and sites["PRESET3"]["Stts"] == 0 and sites["PRESET3"]["Phone"] == "phone4" and sites["PRESET3"]["SmsSenders"] == ["15880004"]
      and sites["PRESET3"]["Preset"] == 3 and sites["PRESET3"]["note"] == "몰4" and sites["PRESET4"]["ID"] == "seller05"
      and st.unseal(sites["PRESET4"]["PW"]) == "pw-5" and sites["PRESET4"]["Stts"] == 9 and "PRESET5" not in sites
      and sites["PRESET1"]["ID"] == "seller01" and sites["SITE1"]["ID"] == "m", str((app.said, {k: (v.get("ID"), v.get("Stts")) for k, v in sites.items()})))
check("옛 ③ 의 계정은 어디에도 없다", "seller03" not in json.dumps(sites, ensure_ascii=False) and all(st.unseal(sites[f"PRESET{i}"]["PW"]) != "pw-3" for i in range(1, 5)))
ps = st.read_presets()
check("프리셋 파일도 당겨지고 그대로인 기록의 저장 날짜는 유지된다 (keep_dates 가 옛 번호로 맞춰 본다)",
      [(p["no"], p["name"], p["code"]) for p in ps] == [(1, "몰1", "011"), (2, "몰2", "021"), (3, "몰4", "041"), (4, "몰5", "051")]
      and ps[2]["saved_at"] == "2026-10-04T10:00:00" and ps[3]["saved_at"] == "2026-10-05T10:00:00", str([(p["no"], p["name"], p["saved_at"]) for p in ps]))
check("메일 기억·로그인 세션·보관 파일이 따라 옮겨지고 옛 ③ 것은 지워진다",
      all([_side(k, i) for i in range(1, 6)] == [1, 2, 4, 5, None] for k in ("mail", "session", "backup")),
      str({k: [_side(k, i) for i in range(1, 6)] for k in ("mail", "session", "backup")}))
check("저장한 뒤에는 화면 칸의 원래 번호가 새 번호가 된다 (다시 저장해도 또 당기지 않는다)", [p["orig"] for p in app.presets] == [1, 2, 3, 4])
summ = st.preset_summary()
check("대시보드 요약·켬끔은 Sites·프리셋 파일을 따른다", [(s["no"], s["name"], s["on"], s["backup"]) for s in summ] == [(1, "몰1", False, True), (2, "몰2", True, True), (3, "몰4", True, True), (4, "몰5", False, True)]
      and st.set_preset_switches({"PRESET3": False}) == {3: False}, str(summ))
before = (json.dumps(_sites_now(), sort_keys=True), json.dumps(st.read_presets(), sort_keys=True))
app = _app()
rr.App.save(app)
check("지우지 않은 평소 저장은 그대로 (번호·날짜·계정 안 바뀜)", before == (json.dumps(_sites_now(), sort_keys=True), json.dumps(st.read_presets(), sort_keys=True))
      and app.said[-1] == "저장했습니다.", str(app.said))

_seed()
app = _app()
rr.App.remove_preset(app)
rr.App.save(app)
sites = _sites_now()
check("① 도 지울 수 있다 - 새 ① 은 옛 ② 의 계정, 파일도 따라온다", [p["name"] for p in app.presets] == ["몰2", "몰3", "몰4", "몰5"] and app.cur == 0
      and sites["PRESET1"]["ID"] == "seller02" and st.unseal(sites["PRESET1"]["PW"]) == "pw-2" and "PRESET5" not in sites
      and [_side("mail", i) for i in range(1, 6)] == [2, 3, 4, 5, None] and "seller01" not in json.dumps(sites), str((app.said, [_side("mail", i) for i in range(1, 6)])))

_seed(2)
app = _app()
rr.App.remove_preset(app)
check("PRESET_MIN 개면 [−] 가 막힌다 (묻지도 않는다)", len(app.presets) == st.PRESET_MIN and app.asked == [], str((len(app.presets), app.asked)))
app.presets.append(rr.new_preset(3))
app.presets[2].update(name="새칸", code="031")
app.cur = 2
rr.App.remove_preset(app)
check("기록 없는 칸(새 칸)은 묻지 않고 지운다", len(app.presets) == 2 and app.asked == [])

_seed()
app = _app()
app.cur = 2
rr.App.remove_preset(app)
before = (json.dumps(_sites_now(), sort_keys=True), json.dumps(st.read_presets(), sort_keys=True), [_side("mail", i) for i in range(1, 6)])
st.start("prepare", ["a"])
st.flush()
r = rr.App.save(app)
st.finish("success")
check("오토파일럿이 실행 중이면 번호가 바뀌는 저장을 거절하고 아무것도 안 바뀐다",
      r is None and app.said[-1] == "오토파일럿이 실행 중이라 저장하지 못했습니다. 끝난 뒤 저장하여 주십시오."
      and before == (json.dumps(_sites_now(), sort_keys=True), json.dumps(st.read_presets(), sort_keys=True), [_side("mail", i) for i in range(1, 6)])
      and [p["orig"] for p in app.presets] == [1, 2, 4, 5], str((r, app.said, [p["orig"] for p in app.presets])))
r = rr.App.save(app)
check("끝난 뒤 다시 저장하면 당겨진다", r == st.presets_path() and _sites_now()["PRESET3"]["ID"] == "seller04" and [_side("backup", i) for i in range(1, 6)] == [1, 2, 4, 5, None])
_seed()
app = _app()
app.presets.pop()                        # 옛 [−] 처럼 마지막만 지워도 그 번호의 파일은 지운다
rr.App.save(app)
check("마지막 프리셋을 지우면 그 번호의 Sites·메일 기억·세션·보관을 지운다", "PRESET5" not in _sites_now() and len(st.read_presets()) == 4
      and all(_side(k, 5) is None and _side(k, 4) == 4 for k in ("mail", "session", "backup")))

print("=== 검토 고침 (이슈 #13): 계정과 기록의 짝(Code)·되돌리기 번호·새 칸·닫기 확인 ===")
policy_presets(10)
_seed()
pt._write_backup(4, st.read_presets()[3], _sites_now()["PRESET4"])      # ④ 에 넣어 주기 전 보관 (보관 당시 Preset 4)
app = _app()
app.cur = 2
rr.App.remove_preset(app)
check("확인 창 제목은 '프리셋 삭제' (docs/ui-wording.md)", app.titles == ["프리셋 삭제"], str(app.titles))
rr.App.save(app)
done, rejected = pt.restore([3])
s3, ps = _sites_now()["PRESET3"], st.read_presets()
check("넣어 주기 → 앞 번호 삭제 저장 → 되돌리기: 되돌린 칸의 Preset 은 돌린 칸 번호 (옛 ④ 계정이 지금의 ④ 사이트로 가지 않는다)",
      done == [3] and s3["Preset"] == 3 and s3["ID"] == "seller04" and ps[2]["code"] == "041" and ps[3]["code"] == "051", str((done, rejected, s3)))
check("저장·되돌리기가 Sites 칸마다 Code(그 칸 프리셋의 사이트코드)를 적는다",
      all(_sites_now()[f"PRESET{i}"].get("Code") == ps[i - 1]["code"] for i in range(1, 5)), str({k: v.get("Code") for k, v in _sites_now().items()}))

_seed()
app = _app()
app.cur = 2
rr.App.remove_preset(app)
_real_wuc = st.write_user_config


def _locked(*a, **k):
    raise PermissionError("locked")


st.write_user_config = _locked
try:
    r = rr.App.save(app)
finally:
    st.write_user_config = _real_wuc
sites = _sites_now()
check("설정 쓰기만 실패하면 프리셋은 당겨지고 Sites 는 옛 번호 그대로 - 저장 실패를 알린다",
      r is None and "저장하지 못했습니다" in app.said[-1] and st.read_presets()[2]["code"] == "041" and sites["PRESET3"]["ID"] == "seller03", str(app.said))
check("짝이 깨진 칸(Code ≠ 프리셋 사이트코드)은 ACTOR 가 실행하지 않는다 - 업무 서식 안내",
      wr._replay_problems("PRESET3", sites["PRESET3"]) == ["PRESET3: 프리셋 3의 아이디·비밀번호가 다른 사이트의 것입니다. 옵저버에서 다시 입력하여 주십시오."]
      and wr.validate_site("PRESET1", sites["PRESET1"]) == [], str(wr._replay_problems("PRESET3", sites["PRESET3"])))
check("Code 가 없는 옛 설정은 짝을 따지지 않는다 (다음 저장 때 채워진다)",
      wr._replay_problems("PRESET3", {k: v for k, v in sites["PRESET3"].items() if k != "Code"}) == [])
summ = st.preset_summary()
check("요약: 짝이 깨진 칸은 has_login False, 켜기도 막힌다",
      summ[2]["has_login"] is False and summ[0]["has_login"] is True and raises(ValueError, st.set_preset_switches, {"PRESET3": True}) is not None
      and st.set_preset_switches({"PRESET1": True}) == {1: True}, str(summ))
app2 = _app()
check("옵저버를 다시 열면 짝이 깨진 칸은 아이디·비밀번호가 비어 있다 (저장해도 잘못된 짝이 굳지 않는다)",
      app2.presets[2]["id"] == "" and app2.presets[2]["has_pw"] is False and app2.presets[0]["id"] == "seller01" and app2.presets[0]["has_pw"] is True,
      str([(p["id"], p["has_pw"]) for p in app2.presets]))
r = rr.App.save(app2)
check("그대로 저장하면 아이디를 묻는다", r is None and "아이디가 필요합니다" in app2.said[-1], str(app2.said))

_seed()
st.save_preset_sites(st.read_presets(), {5: ("newseller", "new-pw")}, origs={1: 1, 2: 2, 3: 4, 4: 5, 5: None})
s5 = _sites_now()["PRESET5"]
check("새 칸(orig None)은 옛 Sites 를 보지 않는다 - 옛 ⑤ 의 휴대폰·켬끔이 새 ⑤ 로 오지 않는다",
      s5["ID"] == "newseller" and "Phone" not in s5 and s5["Stts"] == 9 and s5["Code"] == "051", str(s5))

_seed()
app = _app()
app.closing = app.previewing = app.paused = app.stopping = app.editing = False
app.failed_at, closed = None, []
app._close_now = lambda: closed.append(1)
answers = [True, False]
app.ask = lambda t, x: (app.asked.append(x), answers.pop(0))[1]
app.cur = 2
rr.App.remove_preset(app)
rr.App.quit(app)
check("삭제만 하고 저장하지 않은 채 닫으면 묻는다 - 아니오면 안 닫는다", closed == [] and len(app.asked) == 2 and "저장하지 않은 변경이 있습니다" in app.asked[-1], str(app.asked))
rr.App.save(app)
rr.App.quit(app)
check("저장한 뒤에는 묻지 않고 닫는다", closed == [1] and len(app.asked) == 2 and app.said[-1] == "저장했습니다.", str((closed, app.asked, app.said)))

print()
print(f"실패: {'없음' if not fails else fails}")
sys.exit(1 if fails else 0)
