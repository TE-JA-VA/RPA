# -*- coding: utf-8 -*-
"""웰라이프 실행 관문 (설계 docs/superpowers/specs/2026-10-07-wellife-gate-design.md). 설정은 임시 폴더."""
import json
import os
import sys
import tempfile

_tmp = tempfile.mkdtemp(prefix="wl_gate_")
os.environ["RPA_PROGRAMDATA"] = _tmp
os.environ["RPA_STATUS_DIR"] = os.path.join(_tmp, "status")
CFG = os.path.join(_tmp, "RPA_UserConfig.json")
os.environ["RPA_USER_CONFIG"] = CFG
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rpa_status as st  # noqa: E402
import rpa_dashboard as dash  # noqa: E402

fails = []


def check(cond, what):
    print(("PASS  " if cond else "FAIL  ") + what)
    if not cond:
        fails.append(what)


def write_cfg(data):
    with open(CFG, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def read_cfg():
    with open(CFG, encoding="utf-8") as f:
        return json.load(f)


print("=== 1. Wellife 섹션 ===")
write_cfg({"LogIn": {"AdminCode": "x"}, "Routine": {"Logistics": "Y"}})
check(st.has_wellife_section() is False, "섹션이 없으면 False")
check(st.ensure_wellife_section() is True and read_cfg()["Wellife"] == {"Login": "Y", "Excel": "Y", "Import": "Y", "Sales": "Y", "Hold": "N", "Sap": "N", "Wms": "N",
                                                                   "InvoiceSend": "N", "SalesMode": "리허설", "ImportMode": "리허설", "NormalSalesMode": "리허설",
                                                                   "Mode": "리허설", "SapMode": "리허설", "WmsMode": "리허설",
                                                                   "InvoiceMode": "리허설"},
      "처음 열리면 로그인·주문매핑(엑셀 수집·자동 수집·매출처리)만 켬, 모드는 모두 '리허설' 로 적음")
check(read_cfg()["LogIn"] == {"AdminCode": "x"} and read_cfg()["Routine"] == {"Logistics": "Y"}, "다른 섹션은 그대로")
check(st.ensure_wellife_section() is False, "있으면 안 바꾼다")
got = st.write_wellife_modules({"Login": False, "Sales": True, "Hold": True, "Sap": True})
check(got == {"Login": True, "Excel": False, "Import": False, "Sales": True, "Hold": True, "Sap": True, "Wms": False, "InvoiceSend": False},
      f"쓰기: 로그인은 늘 켬, 빠진 키는 끔 ({got})")
check(st.read_wellife_modules() == (got, []), "읽기는 쓴 값 그대로")
try:
    st.write_wellife_modules({"Logistics": True}); check(False, "모르는 키 거절")
except ValueError:
    check(True, "모르는 키(Logistics) 는 ValueError")
write_cfg({"LogIn": {}, "Wellife": {"Sales": "Y", "Hold": "maybe"}})
sel, problems = st.read_wellife_modules()
check(sel["Hold"] is None and problems and sel["Sap"] is False, f"Y/N 아닌 값은 None·문제, 빠진 키는 끔 ({sel}, {problems})")
check(sel["Excel"] is True and sel["Import"] is True, f"엑셀·자동 수집이 빠진 섹션(10-15 전)은 주문매핑(Sales) 켬을 따른다 ({sel})")
check(st.read_wellife_modes() == [["엑셀 수집", "리허설"], ["자동 수집", "리허설"], ["정상매출", "리허설"], ["물류대기", "리허설"], ["SAP 연동", "리허설"],
                                  ["WMS 이관", "리허설"], ["운송장번호 전송", "리허설"]],
      f"모드(웹 보기): 빠지면 리허설 ({st.read_wellife_modes()})")
write_cfg({"LogIn": {}, "Wellife": {"Mode": " 실행 ", "SapMode": "1건", "SalesMode": "1건", "NormalSalesMode": "1건",
                                    "InvoiceMode": "보냄"}})
check(st.read_wellife_modes() == [["엑셀 수집", "설정 오류 (1건)"], ["자동 수집", "설정 오류 (1건)"], ["정상매출", "1건"], ["물류대기", "실행"], ["SAP 연동", "1건"],
                                  ["WMS 이관", "리허설"], ["운송장번호 전송", "설정 오류 (보냄)"]],
      f"모드(웹 보기): 실행·1건·잘못된 값 (엑셀 수집·자동 수집은 1건을 못 쓴다 - ImportMode 가 없으면 SalesMode, 정상매출은 쓴다) ({st.read_wellife_modes()})")
write_cfg({"LogIn": {}})
check(st.read_wellife_modes() is None, "Wellife 섹션이 없으면 모드 None (웹에 안 보인다)")

write_cfg({"LogIn": {}})
check(st.remove_wellife_section() is False, "지울 섹션이 없으면 False")
write_cfg({"LogIn": {"AdminCode": "x"}, "Routine": {"Logistics": "Y"}, "Wellife": {"Sales": "Y"}})
check(st.remove_wellife_section() is True and "Wellife" not in read_cfg() and read_cfg()["Routine"] == {"Logistics": "Y"}
      and read_cfg()["LogIn"]["AdminCode"] == "x", "Wellife 섹션만 지운다 (다른 섹션·값은 그대로)")
check(st.remove_wellife_section() is False, "한 번 더 부르면 False")

print("=== 2. 정책 값 (settings.json) ===")
check(st.wellife_policy() is False, "정책을 한 번도 안 적었으면 False")
check(dash.set_policy(2, ["Logistics", "Output"], wellife=True) is True and st.wellife_policy() is True, "set_policy 가 wellife 도 적는다")
check(dash.set_policy(2, ["Logistics", "Output"], wellife=True) is False, "같으면 안 쓴다")
check(dash.set_policy(2, [], wellife=False) is True and st.wellife_policy() is False, "꺼지면 False")
check(dash.set_policy(2, []) is False, "wellife 를 안 넘기면 False 로 본다 (옛 부르는 쪽)")

print("=== 3. 루틴 갈래 ===")
import run_routine as rr  # noqa: E402
check(rr.wellife_route(True, True) == ("wellife", None), "열림 + 섹션 → 웰라이프 순서")
check(rr.wellife_route(True, False) == ("stop", "웰라이프 설정이 없습니다 (에이전트가 다시 씁니다)"), "열림 + 섹션 없음 → 멈춤 (보통 루틴으로 새지 않는다)")
check(rr.wellife_route(False, True) == ("stop", "이 업체는 웰라이프 실행이 열려 있지 않습니다 (관리 화면)"), "안 열림 + 섹션 → 멈춤")
check(rr.wellife_route(False, False) == ("routine", None), "안 열림 + 섹션 없음 → 지금 루틴 그대로")
# main 이 정말 이 갈래를 쓰는지 - 정책 켬·섹션 없음이면 보통 루틴을 시작하지 않고 멈춤으로 끝낸다
dash.set_policy(2, ["Logistics", "Output"], wellife=True)
write_cfg({"LogIn": {}})
called = []
orig_run, orig_start = rr.wellife.run_main, rr.status.start
rr.wellife.run_main = lambda r: called.append("wellife")
rr.status.start = lambda *a, **k: called.append(("start",) + a[:1])
finished = []
orig_finish = rr.status.finish
rr.status.finish = lambda result, reason=None, **k: finished.append((result, reason))
try:
    sys.argv = ["run_routine.py"]
    rr.main()
finally:
    rr.wellife.run_main, rr.status.start, rr.status.finish = orig_run, orig_start, orig_finish
check("wellife" not in called and finished and finished[-1][0] == "stopped" and "웰라이프 설정이 없습니다" in finished[-1][1],
      f"main: 정책 켬·섹션 없음 → 보통 루틴 안 돌고 멈춤 ({called}, {finished})")
dash.set_policy(2, [], wellife=False)

print("=== 4. 웰라이프 업체도 모듈별 줄·반복 시간대 (사용자 10-08: ②③④⑤ 따로, ⑤ 는 반복) ===")
import datetime as _dt  # noqa: E402
_rows = [{"at": "09:00", "run": ["Login", "Sales", "Hold", "Sap"]}, {"at": "13:00", "until": "17:00", "rest_min": 10, "run": ["Login", "Wms"]}]
_sch = {"enabled": True, "days": list(range(7)), "slots": _rows, "policy": {"limit": None, "off": ["Logistics", "Output"], "wellife": True}}
check(dash.active_slots(_sch) == _rows, f"wellife 켬: 줄 그대로 ({dash.active_slots(_sch)})")
_noon = _dt.datetime(2026, 10, 7, 14, 0)
check((dash.open_window(_sch, _noon) or {}).get("at") == "13:00", "wellife 켬: 반복 시간대가 열린다")
check(dash.slot_target(_rows[1], dash.slot_off(_sch)) == ("routine", {"RPA_RUN_MODULES": "Login,Wms"}), "⑤ 반복 회차는 루틴으로 Login,Wms 만")
check(dash.slot_target(_rows[0], dash.slot_off(_sch)) == ("routine", {"RPA_RUN_MODULES": "Login,Sales,Hold,Sap"}), "②③④ 줄")
check(dash.slot_target({"at": "10:00", "run": ["Login", "Logistics", "Wms"]}, dash.slot_off(_sch))[1] == {"RPA_RUN_MODULES": "Login,Wms"},
      "웰라이프 업체 줄의 물류관리는 뺀다 (업체 정책)")
check(dash.normalize_run(["Wms"]) == ["Login", "Wms"], "⑤ 만 골라도 로그인이 붙는다")
check(dash.slot_target({"at": "10:00", "until": "18:00", "rest_min": 5, "run": ["Login", "InvoiceSend"]}, dash.slot_off(_sch))
      == ("routine", {"RPA_RUN_MODULES": "Login,InvoiceSend"}), "⑥ 운송장 전송만 고른 반복 줄 (웰라이프 업체)")
check(dash.slot_text({"at": "10:00", "run": ["Login", "InvoiceSend"]}).endswith("운송장 전송"),
      f"줄 이름에 운송장 전송 ({dash.slot_text({'at': '10:00', 'run': ['Login', 'InvoiceSend']})})")
_sch["policy"] = {"limit": None, "off": [], "wellife": False}
check(dash.slot_off(_sch) == ["Sap", "Wms"], "보통 업체는 SAP 연동·WMS 이관만 뺀다 (운송장 전송 2026-10-13, 엑셀·자동 수집 2026-10-30 모든 업체로)")
check(dash.slot_target({"at": "10:00", "run": ["Login", "Import", "Excel"]}, dash.slot_off(_sch))
      == ("routine", {"RPA_RUN_MODULES": "Login,Import,Excel"}), "보통 업체도 자동·엑셀 수집만 고른 줄을 띄운다")
check(dash.slot_target(_rows[1], dash.slot_off(_sch)) == (None, {}), "보통 업체에 ⑤ 만 있는 줄은 띄우지 않는다")

# 주문매핑을 셋으로 나눈 뒤 (웰라이프 2026-10-15, 그 밖 업체 2026-10-30): 옛 예약 줄 'Sales' 에 엑셀·자동 수집을 한 번만 더한다
for wl in (False, True):
    _cfg = st.read_settings()
    _cfg["schedule"] = {"enabled": True, "days": [0], "policy": {"wellife": wl},
                        "slots": [{"at": "09:00", "run": ["Login", "Sales", "Hold"]}, {"at": "13:00", "run": ["Login", "Wms" if wl else "Logistics"]}]}
    st.write_settings(_cfg)
    check(dash.migrate_split_sales() is True, f"{'웰라이프' if wl else '보통'} 업체 PC 도 고친다")
    _slots = st.read_settings()["schedule"]["slots"]
    check(_slots[0]["run"] == ["Login", "Import", "Excel", "Sales", "Hold"] and _slots[1]["run"] == ["Login", "Wms" if wl else "Logistics"],
          f"'Sales' 가 든 줄만 엑셀·자동 수집을 더한다 ({_slots})")
_cfg = st.read_settings()
_cfg["schedule"]["slots"][0]["run"] = ["Login", "Sales"]          # 그 뒤 사람이 매출처리만 고른 줄
st.write_settings(_cfg)
check(dash.migrate_split_sales() is False and st.read_settings()["schedule"]["slots"][0]["run"] == ["Login", "Sales"],
      "한 번만 - 그 뒤 매출처리만 고른 줄은 그대로")

print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
