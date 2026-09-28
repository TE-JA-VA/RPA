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
check(rc == 0 and account(AG) and not account(AG).get("disabled"), "agent 등록", out[-200:])
rc, out = setup("user", "t_none", "u9", "admin", "없는 업체")
check(rc != 0 and "먼저 company" in out and account(f"u9@t-none.{PROJECT}.firebaseapp.com") is None, "없는 업체엔 user 를 못 만든다", out[-200:])

print("=== 2. 삭제 (remove) ===")
rc, out = setup("remove", CID)
check(rc == 0 and db_get(f"meta/companies/{CID}/stts") == 9, "stts=9", out[-300:])
check(account(U1).get("disabled") is True and account(AG).get("disabled") is True, "그 업체 계정(사람·기계)이 모두 막힌다")
check("계정 2개 막음" in out and U1 in out and AG in out, "막은 계정을 찍는다", out[-300:])
check(db_get(f"meta/companies/{CID}/name") == "시험 업체" and db_get(f"meta/companies/{CID}/pcs/pc_1/label") == "첫 PC", "이름·PC 는 남는다")
for args in (("pc", CID, "pc_2", "둘"), ("user", CID, "u2", "admin", "둘"), ("agent", CID, "pc_1"), ("company", CID, "다시")):
    rc, out = setup(*args)
    check(rc != 0 and "삭제된 업체" in out and "restore" in out, f"삭제된 업체엔 {args[0]} 을 막는다", out[-200:])
check(db_get(f"meta/companies/{CID}/pcs/pc_2") is None and db_get(f"meta/companies/{CID}/name") == "시험 업체", "막힌 명령은 아무것도 안 쓴다")
rc, out = setup("remove", CID)
check(rc == 0 and db_get(f"meta/companies/{CID}/stts") == 9, "remove 를 다시 돌려도 된다 (중간에 실패했을 때)", out[-200:])
check(out.startswith("이미 삭제된 업체입니다.") and "계정 2개 막음" in out, "다시 remove 하면 이미 삭제됐다고 알리고 그래도 막는다", out[-200:])
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
check(rc == 0 and out.strip() == "이미 서비스중인 업체입니다.", "살아 있는 업체를 restore 하면 알리기만 한다", out[-200:])
check(account(U1).get("disabled") is True and account(AG).get("disabled") is not True, "따로 막아 둔 계정은 그대로 막혀 있다")
rc, out = setup("pc", CID, "pc_2", "둘째")
check(rc == 0 and db_get(f"meta/companies/{CID}/pcs/pc_2/label") == "둘째", "되살린 업체엔 다시 pc 를 만들 수 있다", out[-200:])

print(f"\n{COUNT - len(FAIL)}/{COUNT} 통과")
if FAIL:
    print("실패:", ", ".join(FAIL))
    sys.exit(1)
