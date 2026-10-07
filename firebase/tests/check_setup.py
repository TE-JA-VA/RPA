"""setup.js 를 에뮬레이터에 대고 돌려 본다 (업체 등록 → 삭제(remove) → 되살림(restore)). 실제 프로젝트는 안 건드린다.

    cd D:\\AX\\RPA\\firebase; . .\\emu_env.ps1; cd tests
    firebase emulators:exec --config ../firebase.json --only auth,database,firestore --project rpa-test-f02e0 "python check_setup.py"

emulators:exec 가 FIREBASE_AUTH_EMULATOR_HOST 등을 넣어 주므로 setup.js 의 Admin SDK 가 에뮬레이터에 붙는다.
user·agent 가 찍는 비밀번호는 가짜 계정 것이지만 습관대로 가려서 찍는다.
"""
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
PROJECT = "rpa-test-f02e0"
DB = "http://127.0.0.1:9000"
NS = f"{PROJECT}-default-rtdb"
AUTH = "http://127.0.0.1:9099"
OWNER = {"Authorization": "Bearer owner"}
SETUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "admin", "setup.js")
FAIL = []
COUNT = 0
for k in ("FIREBASE_AUTH_EMULATOR_HOST", "FIREBASE_DATABASE_EMULATOR_HOST"):
    if not os.environ.get(k):
        sys.exit(f"{k} 가 없다. emulators:exec 안에서 돌릴 것")


def check(ok, label, detail=""):
    """detail(명령 출력 끝부분)은 실패했을 때만 붙인다"""
    global COUNT
    COUNT += 1
    print(f"  {'통과' if ok else '실패'}  {label}" + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        FAIL.append(label)


def call(method, url, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read().decode("utf-8")
        return json.loads(raw) if raw else None


def db_get(path):
    return call("GET", f"{DB}/{path}.json?ns={NS}", None, OWNER)


def account(email):
    """에뮬레이터 계정 하나 (없으면 None). disabled 도 들어 있다."""
    r = call("POST", f"{AUTH}/identitytoolkit.googleapis.com/v1/projects/{PROJECT}/accounts:lookup", {"email": [email]}, OWNER)
    return (r or {}).get("users", [None])[0]


def setup(*args):
    """(종료 코드, 출력). 비밀번호 줄은 가린다."""
    p = subprocess.run(["node", SETUP, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       cwd=os.path.dirname(SETUP), timeout=60)
    out = re.sub(r"비밀번호: \S+", "비밀번호: ****", p.stdout + p.stderr)
    return p.returncode, out


CID = "t_x"
U1 = f"u1@t-x.{PROJECT}.firebaseapp.com"
AG = f"agent-pc-1@t-x.{PROJECT}.firebaseapp.com"

print("=== 1. 등록 ===")
rc, out = setup("company", CID, "시험", "업체")
check(rc == 0 and db_get(f"meta/companies/{CID}") == {"name": "시험 업체", "stts": 0}, "company 는 이름과 stts=0 을 쓴다", out[-200:])
rc, out = setup("pc", CID, "pc_1", "첫", "PC")
check(rc == 0 and db_get(f"meta/companies/{CID}/pcs/pc_1/label") == "첫 PC", "pc 등록", out[-200:])
rc, out = setup("user", CID, "u1", "admin", "담당자")
check(rc == 0 and "비밀번호: ****" in out and account(U1) and not account(U1).get("disabled"), "user 등록", out[-200:])
rc, out = setup("agent", CID, "pc_1")
check(rc == 0 and account(AG) and not account(AG).get("disabled") and "업체코드: t_x   PC코드: pc_1   비밀번호: ****" in out,
      "agent 등록 - PC 설정 창의 칸 이름 그대로 (업체코드·PC코드)", out[-200:])
rc, out = setup("user", "t_none", "u9", "admin", "없는 업체")
check(rc != 0 and "먼저 company" in out and account(f"u9@t-none.{PROJECT}.firebaseapp.com") is None, "없는 업체엔 user 를 못 만든다", out[-200:])
check(out.strip().startswith("오류: 먼저 company") and "    at " not in out, "거절은 '오류: …' 한 줄 (오류 꼬리 없이)", out[-200:])
rc, out = setup("modules", "t_none", "Hold=off")
check(rc != 0 and "먼저 company" in out and db_get("meta/companies/t_none") is None, "없는 업체엔 모듈 정책을 못 넣는다", out[-200:])

print("=== 2. 삭제 (remove) ===")
rc, out = setup("remove", CID)
check(rc == 0 and db_get(f"meta/companies/{CID}/stts") == 9, "stts=9", out[-300:])
check(account(U1).get("disabled") is True and account(AG).get("disabled") is True, "그 업체 계정(사람·기계)이 모두 막힌다")
check("업체 비활성화: t_x" in out and "계정 2개 사용중지" in out and U1 in out and AG in out, "사용중지한 계정을 찍는다", out[-300:])
check(db_get(f"meta/companies/{CID}/name") == "시험 업체" and db_get(f"meta/companies/{CID}/pcs/pc_1/label") == "첫 PC", "이름·PC 는 남는다")
for args in (("pc", CID, "pc_2", "둘"), ("user", CID, "u2", "admin", "둘"), ("agent", CID, "pc_1"), ("company", CID, "다시")):
    rc, out = setup(*args)
    check(rc != 0 and "비활성화된 업체" in out and "restore" in out, f"비활성화된 업체엔 {args[0]} 을 막는다", out[-200:])
check(db_get(f"meta/companies/{CID}/pcs/pc_2") is None and db_get(f"meta/companies/{CID}/name") == "시험 업체", "막힌 명령은 아무것도 안 쓴다")
rc, out = setup("remove", CID)
check(rc == 0 and db_get(f"meta/companies/{CID}/stts") == 9, "remove 를 다시 돌려도 된다 (중간에 실패했을 때)", out[-200:])
check(out.startswith("이미 비활성화된 업체입니다.") and "계정 2개 사용중지" in out, "다시 remove 하면 이미 비활성화됐다고 알리고 그래도 사용중지한다", out[-200:])
rc, out = setup("remove", "t_none")
check(rc != 0 and "먼저 company" in out, "없는 업체는 remove 못 한다", out[-200:])
rc, out = setup("list")
check(rc == 0 and CID in out and "9" in out, "list 에 업체 상태가 나온다", out[-300:])

print("=== 3. 되살림 (restore) ===")
rc, out = setup("restore", CID)
check(rc == 0 and db_get(f"meta/companies/{CID}/stts") == 0, "stts=0", out[-300:])
check(account(U1).get("disabled") is not True and account(AG).get("disabled") is not True, "계정이 다시 열린다")
call("POST", f"{AUTH}/identitytoolkit.googleapis.com/v1/projects/{PROJECT}/accounts:update",
     {"localId": account(U1)["localId"], "disableUser": True}, OWNER)   # 서비스 중에 사람 하나만 따로 막아 둔다
rc, out = setup("restore", CID)
check(rc == 0 and out.strip() == "이미 사용중인 업체입니다.", "사용중인 업체를 restore 하면 알리기만 한다", out[-200:])
check(account(U1).get("disabled") is True and account(AG).get("disabled") is not True, "따로 막아 둔 계정은 그대로 막혀 있다")
rc, out = setup("pc", CID, "pc_2", "둘째")
check(rc == 0 and db_get(f"meta/companies/{CID}/pcs/pc_2/label") == "둘째", "되살린 업체엔 다시 pc 를 만들 수 있다", out[-200:])

print("=== 4. 토큰 (tokens · price · usage, 2026-10-06 3부) ===")
import datetime  # noqa: E402

FS = f"http://127.0.0.1:8080/v1/projects/{PROJECT}/databases/(default)/documents"


def fs_doc(path):
    """문서 fields 를 파이썬 값으로 (없으면 None) - 정수·글자만"""
    try:
        d = call("GET", f"{FS}/{path}", None, OWNER)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    return {k: int(v["integerValue"]) if "integerValue" in v else v.get("stringValue") for k, v in (d.get("fields") or {}).items()}


def fs_list(path):
    return [{k: int(v["integerValue"]) if "integerValue" in v else v.get("stringValue") for k, v in (x.get("fields") or {}).items()}
            for x in (call("GET", f"{FS}/{path}", None, OWNER) or {}).get("documents", [])]


def fs_run(run_id, started_at, cost):
    call("POST", f"{FS}/runs/{CID}/items?documentId={run_id}", {"fields": {
        "cid": {"stringValue": CID}, "pcId": {"stringValue": "pc_1"}, "started_at": {"stringValue": started_at},
        "cost": {"integerValue": str(cost)}, "used": {"mapValue": {"fields": {"logistics": {"integerValue": str(cost)}}}}}}, OWNER)


fs_run("before", "2020-01-01T09:00:00", 5)                 # 통장을 만들기 전 기록 - 빼지 않는다
rc, out = setup("tokens", CID)
check(rc == 0 and "토큰 정보가 없다" in out and fs_doc(f"wallet/{CID}") is None, "토큰 정보가 없으면 그렇다고만 (만들지 않는다)", out[-200:])
rc, out = setup("tokens", CID, "+1000", "10월", "결제")
w = fs_doc(f"wallet/{CID}") or {}
check(rc == 0 and w.get("granted") == 1000 and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", w.get("since") or ""),
      "처음 넣으면 통장을 만든다 (넣은 합계·시작 시각 - 기록의 started_at 과 같은 꼴)", out[-300:])
check("토큰 정보를 만들었습니다" in out and "모듈 실행을 막습니다" in out and "남은 1000" in out, "만들었다고 알리고, 토큰 정보 전 기록은 안 뺀다", out[-300:])
g = fs_list(f"wallet/{CID}/grants")
check(len(g) == 1 and g[0].get("amount") == 1000 and g[0].get("memo") == "10월 결제" and g[0].get("at"), "넣은 내역 한 줄 (언제·얼마·메모)", str(g))
fs_run("after", (datetime.datetime.now() + datetime.timedelta(minutes=1)).isoformat(timespec="seconds"), 30)
rc, out = setup("tokens", CID, "-50", "정정")
check(rc == 0 and (fs_doc(f"wallet/{CID}") or {}).get("granted") == 950 and "쓴 30" in out and "남은 920" in out
      and len(fs_list(f"wallet/{CID}/grants")) == 2, "빼기(정정)도 내역에 남고, 통장 시작 뒤 기록만 뺀다", out[-300:])
rc, out = setup("tokens", CID)
check(rc == 0 and "남은 920" in out and "10월 결제" in out and "정정" in out, "금액 없이 부르면 합계·남은 토큰·넣은 내역", out[-400:])
for bad in ("abc", "0", "1.5"):
    rc, out = setup("tokens", CID, bad)
    check(rc != 0 and "0 이 아닌 정수" in out and (fs_doc(f"wallet/{CID}") or {}).get("granted") == 950, f"토큰 수 '{bad}' 은 거절", out[-200:])
rc, out = setup("tokens", "t_none", "+5")
check(rc != 0 and "먼저 company" in out and fs_doc("wallet/t_none") is None, "없는 업체엔 못 넣는다", out[-200:])
rc, out = setup("price")
check(rc == 0 and "토큰 배율" in out and "default" in out and "login" in out, "토큰 배율 보기 (서버에 없으면 처음 배율)", out[-200:])
rc, out = setup("price", "logistics", "2")
check(rc == 0 and (fs_doc("meta/prices") or {}).get("logistics") == 2, "값 바꾸기", out[-200:])
for args in (("logistics", "-1"), ("logistics", "x"), ("Bad-Key", "1"), ("logistics",)):
    rc, out = setup("price", *args)
    check(rc != 0 and (fs_doc("meta/prices") or {}).get("logistics") == 2, f"값표 {args} 은 거절", out[-200:])
rc, out = setup("usage")
check(rc == 0 and "토큰 정보" in out and "통장" not in out, "usage 칸 이름도 '토큰 정보'", out[-300:])
check(rc == 0 and CID in out and "920" in out and "30" in out, "usage: 업체마다 남은 토큰·이번 달 쓴 토큰", out[-500:])

rc, out = setup()
old = [w for w in ("막기", "막음", "다시 엶", "통장", "삭제(비활성)", "되살림", "서비스중") if w in out]
check(rc != 0 and "사용중지" in out and "업체 비활성화" in out and "다시 활성화" in out and not old, "도움말도 새 이름 (사용중지·업체 비활성화·다시 활성화·토큰 정보)", old)
print("=== 5. 자동 실행 개수 (slots, 2026-10-07) ===")
rc, out = setup("slots", CID)
check(rc == 0 and "2 (기본)" in out, "값이 없으면 기본 2", out[-200:])
rc, out = setup("slots", CID, "3")
check(rc == 0 and db_get(f"meta/companies/{CID}/apps/rpa/limits/schedule") == 3 and "= 3" in out, "slots 3", out[-200:])
rc, out = setup("slots", CID, "13")
check(rc != 0 and out.strip().startswith("오류:") and db_get(f"meta/companies/{CID}/apps/rpa/limits/schedule") == 3, "13 은 거절 (0~12)", out[-200:])
rc, out = setup("slots", "t_none", "3")
check(rc != 0 and "먼저 company" in out, "없는 업체는 거절", out[-200:])
print(f"\n{COUNT - len(FAIL)}/{COUNT} 통과")
if FAIL:
    print("실패:", ", ".join(FAIL))
    sys.exit(1)
