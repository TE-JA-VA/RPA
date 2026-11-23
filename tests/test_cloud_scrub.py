# -*- coding: utf-8 -*-
"""클라우드로 올리기 직전 가림 (보안 진단 2026-11-23 E-3·C4, 11-13 고칠 목록 C4).
실행 기록(Firestore runs)과 PC 현황(RTDB live)에 ERPia 업체코드·아이디를 싣지 않고, 로그 줄·실패 사유의 전화·메일·긴 숫자·토큰을 가린다.
PC 안의 기록(바탕화면 실행 이력)은 그대로 둔다.
    .venv\\Scripts\\python.exe tests\\test_cloud_scrub.py
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
import rpa_status as st  # noqa: E402
import agent  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


SECRET_BITS = ("erp_admin7", "hong77", "010-1234-5678", "kim@shop.co.kr", "2026112012345", "eyJhbGciOiJSUzI1NiJ9.TOKEN")


def main():
    s = st.scrub
    print("가림 함수")
    check("S1 전화·메일·7자리 이상 숫자를 가린다", "5678" not in s("받는분 010-1234-5678") and "@" not in s("메일 kim@shop.co.kr")
          and "2026112012345" not in s("주문 2026112012345"))
    check("S2 주소의 토큰 값(auth=·token=·key=)을 가린다", "TOKEN" not in s("GET /x.json?print=silent&auth=eyJhbGciOiJSUzI1NiJ9.TOKEN 403"))
    check("S3 평범한 줄·짧은 수·시각은 그대로", s("[10:00:01] 3. 클릭 '엑셀받기' 12건") == "[10:00:01] 3. 클릭 '엑셀받기' 12건")

    rec = {"run_id": "r1", "program": "routine", "state": "fail", "started_at": "2026-11-23T10:00:00",
           "account": {"admin_code": "erp_admin7", "user_id": "hong77"},
           "reason": "받는분 010-1234-5678 kim@shop.co.kr 확인 실패",
           "log_tail": ["[10:00:01] 로그인 hong77", "주문 2026112012345 저장", "GET ?auth=eyJhbGciOiJSUzI1NiJ9.TOKEN"]}
    doc = agent.run_doc(rec, "ca", "pc1")
    whole = json.dumps(doc, ensure_ascii=False)
    print("실행 기록 (Firestore)")
    check("R1 ERPia 업체코드·아이디를 싣지 않는다 (로그 줄에 찍힌 아이디도)", "erp_admin7" not in whole and "hong77" not in whole
          and '"account"' not in doc["payload"], doc["payload"][:200])
    check("R2 로그 줄·실패 사유의 개인정보·토큰을 가린다", not any(b in whole for b in SECRET_BITS[2:]), whole[:300])
    check("R3 PC 의 기록 원본은 그대로 (가린 것은 사본)", rec["account"]["user_id"] == "hong77" and "010-1234-5678" in rec["reason"])

    snap = {"programs": {"routine": {"state": "running", "account": {"admin_code": "erp_admin7", "user_id": "hong77"},
                                     "reason": "kim@shop.co.kr", "log_tail": ["x"]}}}
    out = agent.trim_logs(snap)
    print("PC 현황 (RTDB live)")
    check("L1 현황에도 ERPia 업체코드·아이디·로그를 싣지 않는다", "account" not in out["programs"]["routine"] and "log_tail" not in out["programs"]["routine"])
    check("L2 현황의 사유도 가린다", "@" not in out["programs"]["routine"]["reason"])
    print("주소의 토큰이 예외 글로 새지 않게 (보안 진단 2026-11-23 E-4)")
    import fb
    import preset_transfer as pt
    c = fb.Client.__new__(fb.Client)
    c._cfg = {"database_url": "https://x.firebaseio.com"}
    c.token = lambda: "TOKENVALUE"
    u = c._url("apps/otp/requests/ca/ph one\x07")
    check("U1 경로 조각을 인코딩한다 - 빈칸·제어 글자가 주소에 그대로 들어가지 않는다",
          " " not in u.split("?")[0] and "\x07" not in u and u.endswith("auth=TOKENVALUE"), u)
    check("U2 평범한 경로는 그대로", c._url("apps/rpa/live/ca/pc_1").startswith("https://x.firebaseio.com/apps/rpa/live/ca/pc_1.json?"))
    check("U3 프리셋 옮기기의 휴대폰 키는 영문·숫자·_-·64자까지만", pt.phone_ok("ph_01-a") and not pt.phone_ok("ph one")
          and not pt.phone_ok("a/../b") and not pt.phone_ok("x" * 65) and not pt.phone_ok(""))
    print("\n실패:", fails if fails else "없음")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
