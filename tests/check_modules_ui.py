# -*- coding: utf-8 -*-
"""환경설정 '실행 모듈' 화면 시험 + 현황/이력의 모듈 표시.

시험 서버(8766, DRY_RUN)를 직접 띄우고 끈다. 자격증명 파일은 임시 가짜(RPA_CRED_FILE)라
실제 바탕화면의 ERPIA_AI.txt 는 절대 건드리지 않는다. check_schedule_ui.py 와 같은 8766 포트를 쓰므로 동시에 돌리지 말 것.

    .venv\\Scripts\\python.exe tests\\check_modules_ui.py
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\AX\RPA")
from playwright.sync_api import sync_playwright  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "http://127.0.0.1:8766"
fails = []


def check(cond, what):
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        fails.append(what)


# 계정이 들어 있는 시뮬레이터 폴더를 복사해서 쓴다 (원본은 건드리지 않는다)
sim = tempfile.mkdtemp(prefix="rpa_ui_mod_")
shutil.copytree(os.path.join(HERE, "status_sim"), sim, dirs_exist_ok=True)

# 모듈이 든 루틴 기록을 하나 만들어 둔다 (현황 카드·이력 상세 표시 확인용)
os.environ["RPA_STATUS_DIR"] = sim
import rpa_status as st  # noqa: E402
st.start("routine", [("login", "ERPia 로그인"), ("order_screen", "주문매핑 화면 이동"), ("sales", "정상매출 처리"),
                     ("hold_screen", "물류대기 화면 이동"), ("hold_save", "물류대기 저장")])
st.set_modules([("login", "로그인", ("login",), 1), ("sales", "주문매핑 매출처리", ("order_screen", "sales"), 2),
                ("hold", "물류대기 관리", ("hold_screen", "hold_save"), 4)])
st.module_start("login"); st.step("login"); st.module_done("login", "done")
st.module_off("sales", st.OFF_NOTE); st.skip("order_screen", st.OFF_NOTE); st.skip("sales", st.OFF_NOTE)
st.module_start("hold"); st.step("hold_screen"); st.progress(3, 8, "상품코드 x"); st.step("hold_save")
st.module_done("hold", "no_target", "물류대기 그리드에 행이 없어 저장하지 않았습니다.")
st.finish("success")
# 프리페어 기록도 하나 (모듈 없음 - 상세에 '모듈 비트' 가 뜨면 안 된다)
st.start("prepare", [("login", "로그인"), ("mail", "메일")])
st.step("login"); st.step("mail")
st.finish("success")

# 가짜 자격증명 파일 (비밀번호가 화면·응답에 새지 않는지도 본다)
PW = "비밀번호-유출-금지-9876"
cred = os.path.join(sim, "ERPIA_AI.txt")
json.dump([{"LogIn": [{"AdminCode": "erpiatest2"}, {"ID": "admin"}, {"PW": PW}]},
           {"Logistic": [{"cboBS_Auto_YN": "Y"}]},
           {"Routine": [{"Login": "Y"}, {"Sales": "Y"}, {"Hold": "Y"}, {"Logistics": "Y"}, {"Output": "Y"}]}],
          open(cred, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def routine_in_file():
    # 대시보드가 처음 쓸 때 옛 파일을 합쳐 RPA_UserConfig.json(cred 옆)을 만들고 옛 파일은 .old 로 바꾼다
    new = os.path.join(sim, "RPA_UserConfig.json")
    if os.path.exists(new):
        return json.load(open(new, encoding="utf-8"))["Routine"]
    data = json.load(open(cred, encoding="utf-8"))
    sec = next(x for x in data if "Routine" in x)["Routine"]
    return {k: v for item in sec for k, v in item.items()}


srv = subprocess.Popen([r"D:\AX\RPA\.venv\Scripts\python.exe", "rpa_dashboard.py", "--port", "8766", "--host", "127.0.0.1", "--no-scheduler"],
                       cwd=r"D:\AX\RPA", env=dict(os.environ, RPA_DASHBOARD_DRY_RUN="1", RPA_STATUS_DIR=sim, RPA_CRED_FILE=cred),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(50):
    try:
        urllib.request.urlopen(BASE + "/healthz", timeout=1)
        break
    except Exception:
        time.sleep(0.2)


def login(pg, uid):
    pg.goto(BASE + "/#now"); pg.wait_for_selector("#login-view:not([hidden])")
    pg.fill("#login-code", "erpiatest2"); pg.fill("#login-id", uid); pg.fill("#login-pw", uid); pg.click("#login-btn")
    pg.wait_for_selector("#programs .card")


def goto_settings(pg):
    pg.click("#tab-settings"); pg.wait_for_selector("#set-mod-Login", state="attached")


try:
    with sync_playwright() as p:
        b = p.chromium.launch()
        # 대시보드는 CSP 로 eval 을 막는다(script-src 'unsafe-inline'). wait_for_function 이 eval 을 쓰므로 시험에서만 푼다.
        pg = b.new_page(viewport={"width": 1200, "height": 900}, bypass_csp=True)

        # --- 관리자: 스위치 5개, 적용, 파일 반영 ---
        login(pg, "admin")

        # 현황 카드의 모듈 표시
        pg.wait_for_selector(".card.hue-routine")
        rows = pg.query_selector_all(".card.hue-routine ol.steps")[0].query_selector_all("li.step")
        check(len(rows) == 3, f"현황 카드에 모듈 3줄 ({len(rows)})")
        states = [r.get_attribute("class") for r in rows]
        check(any("st-done" in c for c in states) and any("st-off" in c for c in states) and any("st-no_target" in c for c in states),
              f"모듈 상태 클래스 done/off/no_target ({states})")
        card_text = pg.inner_text(".card.hue-routine")
        check("설정에서 끔" in card_text and "대상 없음" in card_text, "모듈 줄 문구")
        ck = {c["name"]: c["value"] for c in pg.context.cookies()}
        snap = json.loads(urllib.request.urlopen(urllib.request.Request(
            BASE + "/api/status", headers={"Cookie": f"rpa_session={ck['rpa_session']}"}), timeout=5).read().decode("utf-8"))
        rt = snap["programs"]["routine"]
        check(rt["steps_total"] == 3 and rt["steps_done"] == 3, f"링 단계 수는 끈 단계(2)를 뺀 3/3 ({rt['steps_done']}/{rt['steps_total']})")
        check(rt.get("module_flags") == 5 and [m["state"] for m in rt["modules"]] == ["done", "off", "no_target"], f"API 의 모듈 상태/비트 ({rt.get('module_flags')}, {[m['state'] for m in rt.get('modules', [])]})")

        goto_settings(pg)
        ids = [e.get_attribute("id") for e in pg.query_selector_all("#set-modules input[type=checkbox]")]
        check(ids == ["set-mod-Login", "set-mod-Sales", "set-mod-Hold", "set-mod-Logistics", "set-mod-Output"], f"스위치 5개 순서 {ids}")
        check(pg.inner_text("#mod-meta") == "5/5 켬", f"머리 요약 '{pg.inner_text('#mod-meta')}'")
        check(pg.is_disabled("#set-apply"), "처음엔 적용 비활성")
        check(not pg.is_disabled("#set-mod-Sales"), "관리자는 스위치 활성")
        check("실행 모듈 선택" in pg.inner_text("#view-settings"), "권한 문구에 '실행 모듈 선택'")
        body = pg.content()
        check(PW not in body, "화면 어디에도 비밀번호가 없다")

        # 키보드로 토글해도 포커스가 유지된다 (다시 그리면 사라진다)
        pg.focus("#set-mod-Sales"); pg.keyboard.press("Space")
        pg.wait_for_selector("#set-dirty:not([hidden])")
        check(pg.evaluate("document.activeElement && document.activeElement.id") == "set-mod-Sales", "스페이스로 토글한 뒤 포커스 유지")
        check(not pg.is_checked("#set-mod-Sales"), "스페이스로 꺼짐")
        # 2초 폴링이 입력 중인 값을 덮어쓰지 않는다
        pg.wait_for_timeout(2600)
        check(not pg.is_checked("#set-mod-Sales") and not pg.is_hidden("#set-dirty"), "폴링 뒤에도 입력 중인 값 유지")
        check(not pg.is_disabled("#set-apply"), "스위치를 끄면 적용 활성")
        check(not pg.is_hidden("#tab-settings-dot"), "탭에 빨간 점")
        check(pg.inner_text("#mod-meta") == "4/5 켬", "머리 요약 4/5")
        pg.click("#set-apply")
        pg.wait_for_function("document.getElementById('set-msg').textContent.includes('적용했습니다')")
        check("다음 실행부터 반영" in pg.inner_text("#set-msg"), f"적용 메시지 '{pg.inner_text('#set-msg')}'")
        check(pg.is_disabled("#set-apply"), "적용 뒤 다시 비활성")
        check(pg.is_hidden("#set-dirty"), "적용 뒤 경고 사라짐")
        rf = routine_in_file()
        check(rf == {"Login": "Y", "Sales": "N", "Hold": "Y", "Logistics": "Y", "Output": "Y"}, f"파일의 Routine 이 바뀜 {rf}")
        new = os.path.join(sim, "RPA_UserConfig.json")
        data = json.load(open(new, encoding="utf-8"))
        check(st.unseal(data["LogIn"]["PW"]) == PW and data["Logistic"]["cboBS_Auto_YN"] == "Y", "비밀번호·다른 섹션은 그대로")
        check(PW not in open(new, encoding="utf-8").read() and os.path.exists(cred + ".old"),
              "옛 파일을 합쳐 RPA_UserConfig.json 으로 (비밀번호는 잠김, 옛 파일은 .old)")

        # 새로고침해도 유지
        # 새로 열어도 유지되는지 (환경설정 탭은 현황 카드가 숨겨져 있으므로 카드가 아니라 스위치를 기다린다)
        pg.goto(BASE + "/#settings"); pg.wait_for_selector("#set-mod-Login", state="attached")
        check(not pg.is_checked("#set-mod-Sales") and pg.is_checked("#set-mod-Login"), "새로고침 뒤에도 Sales 꺼짐 유지")

        # 원래대로 되돌리기 (스위치 켜고 적용)
        pg.click("#set-mod-Sales"); pg.wait_for_selector("#set-dirty:not([hidden])"); pg.click("#set-apply")
        pg.wait_for_function("document.getElementById('set-msg').textContent.includes('적용했습니다')")
        check(routine_in_file()["Sales"] == "Y", "되돌리기 반영")

        # 파일 값이 잘못됐을 때 경고 + 적용으로 고치기
        data = json.load(open(new, encoding="utf-8"))
        data["Routine"] = {"Login": "Y", "Hold": "maybe"}
        json.dump(data, open(new, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        pg.click("#set-refresh"); pg.wait_for_function("!document.getElementById('mod-problem').hidden")
        check("Hold" in pg.inner_text("#mod-problem"), "잘못된 값 경고")
        check(not pg.is_disabled("#set-apply"), "잘못된 값이 있으면 곧바로 적용 가능 (고치라는 뜻)")
        check(pg.is_hidden("#set-dirty") and pg.is_hidden("#tab-settings-dot"), "하지만 dirty 는 아니다 (경고 배너·탭 점 없음)")
        pg.click("#set-apply")
        pg.wait_for_function("document.getElementById('set-msg').textContent.includes('적용했습니다')")
        rf = routine_in_file()
        check(rf["Hold"] == "N" and len(rf) == 5, f"적용하면 5개 전부 Y/N 으로 정리 {rf}")
        pg.wait_for_function("document.getElementById('mod-problem').hidden")
        check(True, "경고 사라짐")

        # 이력 상세에 모듈 목록과 모듈 비트 (루틴), 프리페어 상세에는 모듈 비트 없음
        pg.click("#tab-history"); pg.wait_for_selector("#hist-body tr")
        rows = pg.query_selector_all("#hist-body tr")
        routine_row = next((r for r in rows if "루틴" in r.inner_text()), None)
        prepare_row = next((r for r in rows if "프리페어" in r.inner_text()), None)
        check(routine_row is not None and prepare_row is not None, "이력 목록에 루틴·프리페어 행")
        routine_row.click()
        pg.wait_for_function("document.body.innerText.includes('모듈 비트')")
        txt = pg.inner_text("body")
        check("모듈 비트" in txt and "대상 없음" in txt, "루틴 이력 상세: 모듈 목록 + 모듈 비트")
        pg.keyboard.press("Escape")
        prepare_row.click()
        pg.wait_for_timeout(600)
        check("모듈 비트" not in pg.inner_text("body"), "프리페어 이력 상세에는 모듈 비트 없음")
        pg.keyboard.press("Escape")

        # --- 일반 사용자: 잠김 ---
        pg.click("#tab-settings"); pg.wait_for_selector("#logout-btn")   # 로그아웃 버튼은 환경설정 탭에 있다
        pg.click("#logout-btn"); pg.wait_for_selector("#login-view:not([hidden])")
        login(pg, "user"); goto_settings(pg)
        check(pg.is_disabled("#set-mod-Sales"), "일반 사용자는 스위치 비활성")
        check(pg.is_hidden("#set-actions"), "일반 사용자는 적용 버튼 없음")

        # 서버 쪽 거부 (원시 POST)
        ck = {c["name"]: c["value"] for c in pg.context.cookies()}
        req = urllib.request.Request(BASE + "/api/settings", data=b'{"schedule":{"enabled":false,"days":[0],"times":["09:00"]},"modules":{"Sales":false}}', method="POST",
                                     headers={"Content-Type": "application/json", "X-RPA-Action": "1", "Cookie": f"rpa_session={ck['rpa_session']}"})
        try:
            urllib.request.urlopen(req, timeout=5); check(False, "일반 사용자 POST 거부")
        except urllib.error.HTTPError as e:
            check(e.code == 403, f"일반 사용자 POST 거부 ({e.code})")
        check(routine_in_file()["Sales"] == "Y", "거부된 요청은 파일을 안 바꿈")
        b.close()
finally:
    subprocess.run(["taskkill", "/PID", str(srv.pid), "/T", "/F"], capture_output=True)
    shutil.rmtree(sim, ignore_errors=True)

print()
print(f"실패: {'없음' if not fails else fails}")
sys.exit(1 if fails else 0)
