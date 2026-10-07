# -*- coding: utf-8 -*-
"""판 내보내기 (설계 4절). 임시 배포 폴더·임시 사이트 폴더 - 배포·DB 는 가짜 함수."""
import io
import json
import os
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [REPO, os.path.join(REPO, "tools")]
import publish_release as pr  # noqa: E402
import rpa_status as st  # noqa: E402
import update_sign as us  # noqa: E402

fails = []


def check(cond, what):
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        fails.append(what)


tmp = tempfile.mkdtemp(prefix="rpa_pub_")
KEY = os.path.join(tmp, "key.txt")
SITE = os.path.join(tmp, "site")
pub_hex = pr.keygen(KEY)
check(len(pub_hex) == 64 and len(open(KEY).read().strip()) == 64 and pub_hex not in open(KEY).read(), "열쇠 만들기: 비밀은 파일에만, 돌려주는 건 공개 열쇠")
try:
    pr.keygen(KEY); check(False, "열쇠를 덮어씀")
except FileExistsError:
    check(True, "있는 열쇠는 덮어쓰지 않는다 (잃으면 모든 PC 를 다시 설치해야)")


def make_release(n, changed):
    d = os.path.join(tmp, f"배포_2026.10.0{n}-1")
    files = {"a.py": f"A{n if changed else 0}", "python/AFTER_MARKET_RPA_Agent.exe": "EXE"}
    for rel, text in files.items():
        full = os.path.join(d, *rel.split("/")); os.makedirs(os.path.dirname(full), exist_ok=True)
        open(full, "w", encoding="utf-8").write(text)
    man = {"format": 1, "version": f"2026.10.0{n}-1", "runtime": {"python": "3.14.7"},
           "files": {r: st.file_digest(os.path.join(d, *r.split("/"))) for r in files}}
    open(os.path.join(d, "manifest.json"), "w", encoding="utf-8").write(json.dumps(man))
    return d, man


deployed, lists = [], []
d1, m1 = make_release(1, True)
r = pr.publish("2026.10.01-1", d1, SITE, KEY, memo="첫 판", deploy=lambda: deployed.append(1), set_releases=lambda l: lists.append(l))
mb = open(os.path.join(SITE, "releases", "2026.10.01-1", "manifest.json"), "rb").read()
sig = bytes.fromhex(open(os.path.join(SITE, "releases", "2026.10.01-1", "manifest.sig")).read().strip())
check(us.verify(bytes.fromhex(pub_hex), mb, sig), "올린 manifest 의 서명이 공개 열쇠로 맞는다")
check(all(os.path.isfile(os.path.join(SITE, "blobs", f["sha256"])) for f in m1["files"].values()), "파일은 지문 이름으로")
check(deployed == [1] and lists[-1][0]["version"] == "2026.10.01-1" and lists[-1][0]["memo"] == "첫 판", f"배포·DB 목록 ({lists[-1]})")
for n in range(2, 8):
    d, _ = make_release(n, True)
    pr.publish(f"2026.10.0{n}-1", d, SITE, KEY, deploy=lambda: None, set_releases=lambda l: lists.append(l),
               stable="2026.10.02-1" if n == 7 else None)
kept = sorted(os.listdir(os.path.join(SITE, "releases")))
check(kept == ["2026.10.02-1", "2026.10.03-1", "2026.10.04-1", "2026.10.05-1", "2026.10.06-1", "2026.10.07-1"],
      f"최근 5개 + 안정본(10.02-1)만 남는다 ({kept})")
blob_names = set(os.listdir(os.path.join(SITE, "blobs")))
used = set()
for v in kept:
    used |= {f["sha256"] for f in json.load(open(os.path.join(SITE, "releases", v, "manifest.json")))["files"].values()}
check(blob_names == used, "아무 판도 안 쓰는 파일은 지운다, 같은 파일(EXE)은 하나")
check([x["version"] for x in lists[-1]] == kept, "DB 목록도 남은 판만")
try:
    pr.publish("2026.10.09-1", d1, SITE, KEY, deploy=lambda: None, set_releases=lambda l: None)
    check(False, "판 번호와 폴더 manifest 가 다른데 올림")
except ValueError as e:
    check("판" in str(e), f"판 번호가 다르면 멈춘다 ({e})")

# --- 보완 1: 안정본은 DB 기준 (get_stable), --stable 은 DB 로 (set_stable)
SITE2 = os.path.join(tmp, "site2")
set_calls = []
for n in range(1, 8):
    d, _ = make_release(n, True)
    pr.publish(f"2026.10.0{n}-1", d, SITE2, KEY, deploy=lambda: None, set_releases=lambda l: None,
               get_stable=lambda: "2026.10.01-1", set_stable=lambda v: set_calls.append(v))
kept2 = sorted(os.listdir(os.path.join(SITE2, "releases")))
check("2026.10.01-1" in kept2 and len(kept2) == 6, f"DB 의 안정본은 오래돼도 안 지운다 ({kept2})")
b1 = {f["sha256"] for f in json.load(open(os.path.join(SITE2, "releases", "2026.10.01-1", "manifest.json")))["files"].values()}
check(b1 <= set(os.listdir(os.path.join(SITE2, "blobs"))), "안정본의 파일도 남는다")
check(set_calls == [], "--stable 이 없으면 DB 안정본을 안 건드린다")
pr.publish("2026.10.07-1", make_release(7, True)[0], SITE2, KEY, stable="2026.10.07-1", deploy=lambda: None,
           set_releases=lambda l: None, get_stable=lambda: None, set_stable=lambda v: set_calls.append(v))
check(set_calls == ["2026.10.07-1"], "--stable 은 set_stable 로 DB 에")
check(not os.path.exists(os.path.join(SITE2, "stable.txt")), "stable.txt 는 안 만든다")

# --- 보완 2: 배포가 먼저, 실패하면 DB 목록을 안 쓴다
def boom():
    raise RuntimeError("배포 실패")
wrote = []
try:
    d8, _ = make_release(1, True)
    mf = os.path.join(d8, "manifest.json")
    m = json.load(open(mf)); m["version"] = "2026.10.08-1"; open(mf, "w").write(json.dumps(m))
    pr.publish("2026.10.08-1", d8, SITE2, KEY, deploy=boom, set_releases=lambda l: wrote.append(l),
               get_stable=lambda: None, set_stable=lambda v: None)
    check(False, "배포 실패인데 통과")
except RuntimeError:
    check(wrote == [], "배포가 실패하면 DB 목록을 안 쓴다")

# --- 보완 3: 잘린 blob 은 다시 복사
SITE3 = os.path.join(tmp, "site3")
d, m = make_release(3, True)
os.makedirs(os.path.join(SITE3, "blobs"))
sha_a = m["files"]["a.py"]["sha256"]
open(os.path.join(SITE3, "blobs", sha_a), "wb").write(b"")
pr.publish("2026.10.03-1", d, SITE3, KEY, deploy=None, set_releases=None, get_stable=lambda: None)
check(open(os.path.join(SITE3, "blobs", sha_a), "rb").read() == b"A3", "잘린 blob 을 고쳐 놓는다")
check(not [x for x in os.listdir(os.path.join(SITE3, "blobs")) if x.endswith(".tmp")], ".tmp 가 안 남는다")

# --- 열쇠가 없는 PC (다른 작업자) - 내보내기는 저장소 관리자에게
orig_key, pr.KEY_PATH = pr.KEY_PATH, os.path.join(tmp, "없는_열쇠.txt")
out = io.StringIO()
old_stdout, sys.stdout = sys.stdout, out
try:
    code = pr.main(["2026.10.03-1", "메모"])
finally:
    sys.stdout, pr.KEY_PATH = old_stdout, orig_key
check(code != 0 and "저장소 관리자" in out.getvalue(), f"열쇠가 없으면 멈추고 저장소 관리자에게 가라고 알린다 ({out.getvalue().strip()})")

shutil.rmtree(tmp, ignore_errors=True)
print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
