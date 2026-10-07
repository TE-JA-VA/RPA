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
check(st.ensure_wellife_section() is True and read_cfg()["Wellife"] == {"Login": "Y", "Sales": "Y", "Hold": "N", "Sap": "N", "Wms": "N"},
      "처음 열리면 로그인·주문매핑 매출처리만 켬")
check(read_cfg()["LogIn"] == {"AdminCode": "x"} and read_cfg()["Routine"] == {"Logistics": "Y"}, "다른 섹션은 그대로")
check(st.ensure_wellife_section() is False, "있으면 안 바꾼다")
got = st.write_wellife_modules({"Login": False, "Sales": True, "Hold": True, "Sap": True})
check(got == {"Login": True, "Sales": True, "Hold": True, "Sap": True, "Wms": False}, f"쓰기: 로그인은 늘 켬, 빠진 키는 끔 ({got})")
check(st.read_wellife_modules() == (got, []), "읽기는 쓴 값 그대로")
try:
    st.write_wellife_modules({"Logistics": True}); check(False, "모르는 키 거절")
except ValueError:
    check(True, "모르는 키(Logistics) 는 ValueError")
write_cfg({"LogIn": {}, "Wellife": {"Sales": "Y", "Hold": "maybe"}})
sel, problems = st.read_wellife_modules()
check(sel["Hold"] is None and problems and sel["Sap"] is False, f"Y/N 아닌 값은 None·문제, 빠진 키는 끔 ({sel}, {problems})")

print("=== 2. 정책 값 (settings.json) ===")
check(st.wellife_policy() is False, "정책을 한 번도 안 적었으면 False")
check(dash.set_policy(2, ["Logistics", "Output"], wellife=True) is True and st.wellife_policy() is True, "set_policy 가 wellife 도 적는다")
check(dash.set_policy(2, ["Logistics", "Output"], wellife=True) is False, "같으면 안 쓴다")
check(dash.set_policy(2, [], wellife=False) is True and st.wellife_policy() is False, "꺼지면 False")
check(dash.set_policy(2, []) is False, "wellife 를 안 넘기면 False 로 본다 (옛 부르는 쪽)")

print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
