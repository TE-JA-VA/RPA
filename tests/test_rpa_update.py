# tests/test_rpa_update.py
# -*- coding: utf-8 -*-
"""자동 업데이트 PC 핵심 (설계 6절). 가짜 Program Files·가짜 호스팅(사전) - 진짜 PC·인터넷은 안 쓴다."""
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
tmp = tempfile.mkdtemp(prefix="rpa_upd_")
os.environ["RPA_PROGRAMDATA"] = os.path.join(tmp, "pd")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rpa_status as st  # noqa: E402
import rpa_update as up  # noqa: E402
import update_sign as us  # noqa: E402

fails = []


def check(cond, what):
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        fails.append(what)


SK, PK = us.keygen()
PROG = os.path.join(tmp, "prog")


def put(root, rel, text):
    full = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(text)


def manifest_of(root, version, rels, runtime="3.14.7"):
    return {"format": 1, "version": version, "built_at": "x", "builder": "t", "runtime": {"python": runtime},
            "files": {r: st.file_digest(os.path.join(root, *r.split("/"))) for r in rels}}


def tree_digest(root):
    out = {}
    for base, _, files in os.walk(root):
        for n in files:
            p = os.path.join(base, n)
            out[os.path.relpath(p, root)] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    return out


# 지금 판 A: a.py, b.py, firebase/agent/agent.py
for rel, text in (("a.py", "A1"), ("b.py", "B1"), ("firebase/agent/agent.py", "G1")):
    put(PROG, rel, text)
MAN_A = manifest_of(PROG, "2026.10.07-1", ["a.py", "b.py", "firebase/agent/agent.py"])
with open(os.path.join(PROG, "manifest.json"), "w", encoding="utf-8") as f:
    json.dump(MAN_A, f)

# 새 판 B: a.py 바뀜, b.py 없어짐, c.py 새로, agent.py 그대로
SRC_B = os.path.join(tmp, "srcB")
for rel, text in (("a.py", "A2"), ("c.py", "C2"), ("pkg/__init__.py", ""), ("firebase/agent/agent.py", "G1")):
    put(SRC_B, rel, text)
MAN_B = manifest_of(SRC_B, "2026.10.07-2", ["a.py", "c.py", "pkg/__init__.py", "firebase/agent/agent.py"])
MB = json.dumps(MAN_B).encode("utf-8")
BASE = "https://example.test"
HOST = {f"{BASE}/releases/2026.10.07-2/manifest.json": MB,
        f"{BASE}/releases/2026.10.07-2/manifest.sig": us.sign(SK, MB).hex().encode()}
for rel in ("a.py", "c.py", "pkg/__init__.py", "firebase/agent/agent.py"):
    HOST[f"{BASE}/blobs/{MAN_B['files'][rel]['sha256']}"] = open(os.path.join(SRC_B, *rel.split("/")), "rb").read()
GOT = []


def get(url, host=HOST):
    GOT.append(url)
    if url not in host:
        raise up.UpdateError(f"받지 못했습니다: {url.rsplit('/', 1)[-1]} (404)")
    return host[url]


print("=== 1. 바뀐 파일만 고르기 ===")
fetch, remove, new = up.plan_files(MAN_A["files"], MAN_B["files"])
check(fetch == ["a.py", "c.py", "pkg/__init__.py"] and remove == ["b.py"] and new == ["c.py", "pkg/__init__.py"], f"받을 것·치울 것·새 파일 ({fetch} {remove} {new})")

print("\n=== 2. 받기·확인 ===")
STG = up.path("staging")
before = tree_digest(PROG)
man = up.fetch_release("2026.10.07-2", PROG, STG, base_url=BASE, get=get, pub=PK)
plan = json.load(open(os.path.join(STG, "plan.json"), encoding="utf-8"))
check(man["version"] == "2026.10.07-2" and plan == {"version": "2026.10.07-2", "from": "2026.10.07-1", "fetch": ["a.py", "c.py", "pkg/__init__.py"],
                                                  "remove": ["b.py"], "new": ["c.py", "pkg/__init__.py"]}, f"plan.json ({plan})")
check(open(os.path.join(STG, "files", "a.py"), encoding="utf-8").read() == "A2"
      and not os.path.exists(os.path.join(STG, "files", "firebase", "agent", "agent.py")), "바뀐 파일만 받았다 (그대로인 agent.py 는 안 받음)")
check(os.path.isfile(os.path.join(STG, "files", "pkg", "__init__.py")) and os.path.getsize(os.path.join(STG, "files", "pkg", "__init__.py")) == 0, "빈 파일(크기 0)도 받는다")
check(open(os.path.join(STG, "manifest.json"), "rb").read() == MB, "받은 manifest 를 바이트 그대로 둔다")
check(not any(u.endswith(MAN_B["files"]["firebase/agent/agent.py"]["sha256"]) for u in GOT), "그대로인 파일은 내려받지도 않는다")
check(tree_digest(PROG) == before, "받기만으로는 프로그램 폴더가 안 바뀐다")


def refused(what, host=None, pub=PK, version="2026.10.07-2", contains=""):
    shutil.rmtree(STG, ignore_errors=True)
    b = tree_digest(PROG)
    try:
        up.fetch_release(version, PROG, STG, base_url=BASE, get=lambda u: get(u, host or HOST), pub=pub)
        check(False, what + " (거절 안 됨)")
    except up.UpdateError as e:
        check(contains in str(e) and tree_digest(PROG) == b and not os.path.exists(os.path.join(STG, "files")),
              f"{what} - 프로그램 폴더 그대로, 받은 것 지움 ({e})")


refused("서명이 다르면 거절", pub=us.keygen()[1], contains="서명")
refused("공개 열쇠가 없으면 거절", pub=b"", contains="서명")
bad = dict(HOST); bad[f"{BASE}/blobs/{MAN_B['files']['c.py']['sha256']}"] = b"tampered"
refused("파일 지문이 다르면 거절 (Review Focus 3)", host=bad, contains="c.py")
gone = dict(HOST); del gone[f"{BASE}/blobs/{MAN_B['files']['a.py']['sha256']}"]
refused("파일이 없으면(404) 거절 (Review Focus 3)", host=gone, contains="404")
mv = dict(HOST)
for n in ("manifest.json", "manifest.sig"):
    mv[f"{BASE}/releases/2026.10.07-3/{n}"] = HOST[f"{BASE}/releases/2026.10.07-2/{n}"]   # -3 자리에 -2 의 서명된 manifest
refused("요청한 판과 manifest 판이 다르면 거절", host=mv, version="2026.10.07-3", contains="판")
MAN_R = dict(MAN_B, runtime={"python": "3.15.0"}); MR = json.dumps(MAN_R).encode()
rt = dict(HOST); rt[f"{BASE}/releases/2026.10.07-2/manifest.json"] = MR; rt[f"{BASE}/releases/2026.10.07-2/manifest.sig"] = us.sign(SK, MR).hex().encode()
refused("파이썬이 바뀐 판은 거절 (설치 파일로)", host=rt, contains="설치 파일")
MAN_X = json.loads(MB); MAN_X["files"]["../evil.py"] = MAN_X["files"]["a.py"]; MX = json.dumps(MAN_X).encode()
ev = dict(HOST); ev[f"{BASE}/releases/2026.10.07-2/manifest.json"] = MX; ev[f"{BASE}/releases/2026.10.07-2/manifest.sig"] = us.sign(SK, MX).hex().encode()
refused("밖을 가리키는 경로는 서명이 맞아도 거절", host=ev, contains="경로")
cut_n = []


def cut_get(u):
    if "/blobs/" in u:
        cut_n.append(u)
        if len(cut_n) == 2:
            raise ConnectionResetError("끊김")
    return get(u)


shutil.rmtree(STG, ignore_errors=True)
b4 = tree_digest(PROG)
try:
    up.fetch_release("2026.10.07-2", PROG, STG, base_url=BASE, get=cut_get, pub=PK)
    check(False, "받다가 끊기면 거절 (거절 안 됨)")
except up.UpdateError as e:
    check("받기 실패" in str(e) and "ConnectionResetError" in str(e) and tree_digest(PROG) == b4 and not os.path.exists(STG),
          f"받다가 끊기면 거절 - 프로그램 폴더 그대로, 받은 것 지움 ({e})")
real_usage = shutil.disk_usage
shutil.disk_usage = lambda p: real_usage(p)._replace(free=10)
try:
    refused("디스크 여유가 모자라면 시작 전 거절", contains="디스크")
finally:
    shutil.disk_usage = real_usage

print("\n=== 3. 상태·실행 막기·화면 값 ===")
check(up.read_state() == {} and up.busy_reason() is None and up.live_view() is None, "상태가 없으면 막지 않고 화면 값도 없다")
for s in ("downloading", "done", "failed", "rolled_back"):
    up.write_state({"state": s})
    check(up.busy_reason() is None, f"{s} 는 실행을 막지 않는다")
for s in up.BUSY_STATES:
    up.write_state({"state": s})
    check(up.busy_reason() == "업데이트 중이라 잠시 실행할 수 없습니다", f"{s} 는 실행을 막는다")
up.write_state({"state": "done", "target": "2026.10.07-2", "from": "2026.10.07-1", "at": "2026-10-07T14:03:00", "reason": None})
os.makedirs(up.path("backup"), exist_ok=True)
with open(up.path("backup", "manifest.json"), "w", encoding="utf-8") as f:
    json.dump(MAN_A, f)
check(up.backup_version() == "2026.10.07-1" and up.live_view() == {"state": "done", "target": "2026.10.07-2", "from": "2026.10.07-1",
                                                                 "at": "2026-10-07T14:03:00", "reason": None, "backup": "2026.10.07-1"},
      f"live_view 에 보관본 판 ({up.live_view()})")
up.log("시험 한 줄")
check("시험 한 줄" in open(up.path("업데이트_기록.txt"), encoding="utf-8").read(), "업데이트 기록 파일")

print("\n=== 4. 되돌리기 준비 (보관본 → staging, 받기 없음) ===")
# 보관본 = A 의 바뀐 파일들 (Task 3 의 apply 가 남기는 모양)
for rel, text in (("a.py", "A1"), ("b.py", "B1")):
    put(up.path("backup", "files"), rel, text)
# 지금 판을 B 로 바꿔 둔다
for rel, text in (("a.py", "A2"), ("c.py", "C2"), ("pkg/__init__.py", "")):
    put(PROG, rel, text)
os.remove(os.path.join(PROG, "b.py"))
with open(os.path.join(PROG, "manifest.json"), "wb") as f:
    f.write(MB)
shutil.rmtree(STG, ignore_errors=True)
bman = up.stage_rollback(PROG, STG)
plan = json.load(open(os.path.join(STG, "plan.json"), encoding="utf-8"))
check(bman["version"] == "2026.10.07-1" and plan["fetch"] == ["a.py", "b.py"] and plan["remove"] == ["c.py", "pkg/__init__.py"] and plan["new"] == ["b.py"],
      f"보관본으로 가는 plan ({plan})")
check(open(os.path.join(STG, "files", "b.py"), encoding="utf-8").read() == "B1" and os.path.isfile(up.path("backup", "files", "a.py")),
      "보관본은 복사만 한다 (되돌리기가 실패해도 보관본은 남는다)")
os.remove(up.path("backup", "files", "b.py"))
shutil.rmtree(STG, ignore_errors=True)
try:
    up.stage_rollback(PROG, STG); check(False, "보관본이 모자라는데 되돌리기 준비됨")
except up.UpdateError as e:
    check("보관본" in str(e), f"보관본 파일이 모자라면 거절 ({e})")

print("\n=== 5. 살아 있음 표시 (도우미 3분 점검이 본다) ===")
up.write_state({"state": "done"})
check(up.mark_alive({"version": "2026.10.07-2", "state": "ok"}) is False and not os.path.exists(up.path("alive.json")), "업데이트 중이 아니면 안 적는다")
for s in ("applying", "rolling_back"):
    up.write_state({"state": s})
    check(up.mark_alive({"version": "2026.10.07-2", "state": "ok"}) is True
          and st.read_json(up.path("alive.json"))["version"] == "2026.10.07-2", f"{s} 면 alive.json 을 적는다")
check(up.health_local() is False, "표시 파일이 없으면 로그인까지 봐야 '살아 있음'")
open(up.path("health_local"), "w").close()
check(up.health_local() is True, "샌드박스용 표시 파일 update\\health_local (관리자만 쓰는 폴더)")
os.remove(up.path("health_local"))

print("\n=== 6. 받기 → 대기 → 넘기기 (run_update) ===")
for rel, text in (("a.py", "A1"), ("b.py", "B1")):
    put(PROG, rel, text)
for rel in ("c.py",):
    os.remove(os.path.join(PROG, rel)) if os.path.exists(os.path.join(PROG, rel)) else None
with open(os.path.join(PROG, "manifest.json"), "w", encoding="utf-8") as f:
    json.dump(MAN_A, f)
for rel in up.RUNNER_FILES:
    put(PROG, rel, f"# {rel}")
put(PROG, "python/pythonw.exe", "fake")
up.write_state({}); shutil.rmtree(up.path("backup"), ignore_errors=True)
seen, idle_calls, reg = [], [0], []


def idle():
    idle_calls[0] += 1
    seen.append(up.read_state()["state"])
    return idle_calls[0] >= 3          # 두 번은 RPA 가 돌고 있다


up.run_update("2026.10.07-2", "update", PROG, idle, register=lambda r: reg.append(("reg", r)), run_task=lambda: reg.append(("run",)),
              fetch=lambda v, p, s: up.fetch_release(v, p, s, base_url=BASE, get=get, pub=PK), sleep=lambda s: None)
s = up.read_state()
check(seen == ["waiting"] * 3, f"받은 뒤 RPA 가 쉴 때까지 waiting ({seen})")
check(s["state"] == "ready" and s["mode"] == "update" and s["target"] == "2026.10.07-2" and s["from"] == "2026.10.07-1"
      and s["program_dir"] == PROG and s["staging"] == up.path("staging"), f"넘길 때 ready + 도우미가 쓸 칸 ({s})")
check(all(os.path.isfile(up.path("runner", r)) for r in up.RUNNER_FILES) and os.path.isfile(up.path("runner", "python", "pythonw.exe")),
      "도우미와 파이썬을 runner 로 복사")
check(reg == [("reg", up.path("runner")), ("run",)], f"작업 등록 → 실행 ({reg})")
up.write_state({})
up.run_update("2026.10.07-2", "update", PROG, idle, register=lambda r: None, run_task=lambda: None,
              fetch=lambda v, p, s: (_ for _ in ()).throw(up.UpdateError("판 서명이 맞지 않습니다 - 받지 않습니다")), sleep=lambda s: None)
check(up.read_state()["state"] == "failed" and "서명" in up.read_state()["reason"], "받기 실패면 failed + 까닭 (대기도 안 한다)")
up.write_state({})
up.run_update("2026.10.07-2", "update", PROG, lambda: True, register=lambda r: (_ for _ in ()).throw(RuntimeError("등록 실패")),
              run_task=lambda: None, fetch=lambda v, p, s: up.fetch_release(v, p, s, base_url=BASE, get=get, pub=PK), sleep=lambda s: None)
check(up.read_state()["state"] == "failed" and "도우미" in up.read_state()["reason"], "도우미를 못 띄우면 failed (실행 막기가 풀린다)")

print("\n=== 7. 다시 켜진 에이전트가 멈춘 대기를 정리 / 실패 글은 한국어 ===")
for s0 in ("downloading", "waiting"):
    up.write_state({"state": s0, "mode": "update", "target": "2026.10.07-2", "from": "2026.10.07-1"})
    os.makedirs(up.path("staging", "files"), exist_ok=True)
    up.clear_stale()
    s = up.read_state()
    check(s["state"] == "failed" and "다시 켜져" in s["reason"] and s["target"] == "2026.10.07-2" and s["from"] == "2026.10.07-1"
          and not os.path.exists(up.path("staging")), f"{s0} 였다면 failed + staging 지움 ({s.get('reason')})")
    check(up.busy_reason() is None, f"{s0} 정리 뒤엔 실행 막기가 풀린다")
for s0 in ("ready", "applying", "rolling_back", "done"):
    up.write_state({"state": s0, "target": "x"})
    os.makedirs(up.path("staging"), exist_ok=True)
    up.clear_stale()
    check(up.read_state()["state"] == s0 and os.path.isdir(up.path("staging")), f"{s0} 는 건드리지 않는다")
shutil.rmtree(up.path("staging"), ignore_errors=True)
up.write_state({})
shutil.rmtree(os.path.join(PROG, "python"), ignore_errors=True)
up.run_update("2026.10.07-2", "update", PROG, lambda: True, register=lambda r: None, run_task=lambda: None,
              fetch=lambda v, p, s: up.fetch_release(v, p, s, base_url=BASE, get=get, pub=PK), sleep=lambda s: None)
r = up.read_state().get("reason") or ""
check(up.read_state()["state"] == "failed" and "Error" not in r and "도우미" in r, f"보통 오류도 쉬운 한국어 ({r})")

shutil.rmtree(tmp, ignore_errors=True)
print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
