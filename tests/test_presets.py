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
check("요약: 번호·이름·코드·단계 수·저장 시각·아이디 여부·켬", summary[0] == {
      "no": 1, "name": "지마켓", "code": "012", "steps": 1, "saved_at": "2026-09-30T18:20:00", "has_login": True, "on": True}
      and summary[1]["steps"] == 0 and summary[1]["has_login"] is False, str(summary))
check("요약에는 기록 내용·아이디·비밀번호가 없다", all(set(s) == {"no", "name", "code", "steps", "saved_at", "has_login", "on"}
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
site = dict(st.read_user_config()["Sites"]["PRESET1"], ID=fake_mall.USER, PW=fake_mall.PASSWORD)
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

print()
print(f"실패: {'없음' if not fails else fails}")
sys.exit(1 if fails else 0)
