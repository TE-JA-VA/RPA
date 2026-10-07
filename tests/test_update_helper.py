# tests/test_update_helper.py
# -*- coding: utf-8 -*-
"""도우미 (설계 7절). 가짜 Program Files·가짜 작업(ops) - 진짜 예약 작업·레지스트리는 안 건드린다."""
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
tmp = tempfile.mkdtemp(prefix="rpa_helper_")
os.environ["RPA_PROGRAMDATA"] = os.path.join(tmp, "pd")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rpa_status as st  # noqa: E402
import rpa_update as up  # noqa: E402
import update_helper as uh  # noqa: E402

fails = []


def check(cond, what):
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        fails.append(what)


PROG = os.path.join(tmp, "prog")


def put(root, rel, text):
    full = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(text)


def read(root, rel):
    full = os.path.join(root, *rel.split("/"))
    return open(full, encoding="utf-8").read() if os.path.isfile(full) else None


def man(version, files):
    """진짜 지문 (7절의 stage_rollback 이 보관본 지문을 확인한다)."""
    return {"format": 1, "version": version, "runtime": {"python": "3.14.7"},
            "files": {r: {"sha256": hashlib.sha256(t.encode("utf-8")).hexdigest(), "size": len(t.encode("utf-8"))} for r, t in files.items()}}


A = {"a.py": "A1", "b.py": "B1", "keep.py": "K"}
B = {"a.py": "A2", "c.py": "C2", "keep.py": "K"}


def setup_a_and_staged_b(mode="update"):
    """프로그램 폴더 = 판 A, staging = 판 B (Task 2 가 남기는 모양), state = ready."""
    shutil.rmtree(PROG, ignore_errors=True); shutil.rmtree(up.update_dir(), ignore_errors=True)
    for r, t in A.items():
        put(PROG, r, t)
    put(PROG, "user_note.txt", "목록 밖 파일")
    with open(os.path.join(PROG, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(man("2026.10.07-1", A), f)
    stg = up.path("staging")
    for r in ("a.py", "c.py"):
        put(os.path.join(stg, "files"), r, B[r])
    with open(os.path.join(stg, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(man("2026.10.07-2", B), f)
    with open(os.path.join(stg, "plan.json"), "w", encoding="utf-8") as f:
        json.dump({"version": "2026.10.07-2", "from": "2026.10.07-1", "fetch": ["a.py", "c.py"], "remove": ["b.py"], "new": ["c.py"]}, f)
    up.write_state({"state": "ready", "mode": mode, "target": "2026.10.07-2", "from": "2026.10.07-1",
                    "program_dir": PROG, "staging": stg, "at": up.now_text()})


class FakeOps:
    """after_install 은 에이전트가 켜진 것을 흉내 낸다: good 이면 프로그램 폴더 manifest 의 판으로 alive.json 을 적는다."""

    def __init__(self, good=("2026.10.07-2", "2026.10.07-1")):
        self.good, self.calls = set(good), []

    def end_agent(self):
        self.calls.append("end")

    def after_install(self, program_dir):
        v = json.load(open(os.path.join(program_dir, "manifest.json"), encoding="utf-8"))["version"]
        self.calls.append(f"after:{v}")
        if v in self.good:
            up.mark_alive({"version": v, "state": "ok"})
        return 0

    def set_display_version(self, v):
        self.calls.append(f"ver:{v}")

    def delete_helper_task(self):
        self.calls.append("deltask")

    def sleep(self, sec):
        pass


uh.HEALTH_POLL_SEC = 0
uh.HEALTH_WAIT_SEC = 0.05

print("=== 1. 성공 ===")
setup_a_and_staged_b()
ops = FakeOps()
check(uh.main(ops) == 0, "도우미 끝 (0)")
s = up.read_state()
check(read(PROG, "a.py") == "A2" and read(PROG, "c.py") == "C2" and read(PROG, "b.py") is None and read(PROG, "keep.py") == "K",
      "새 판 파일로 바뀌고 없어진 파일은 치웠다")
check(read(PROG, "user_note.txt") == "목록 밖 파일", "목록 밖 파일은 그대로")
check(json.load(open(os.path.join(PROG, "manifest.json"), encoding="utf-8"))["version"] == "2026.10.07-2", "manifest 도 새 판")
check(s["state"] == "done" and s["target"] == "2026.10.07-2" and s["from"] == "2026.10.07-1", f"상태 done ({s})")
check(read(up.path("backup", "files"), "a.py") == "A1" and read(up.path("backup", "files"), "b.py") == "B1"
      and up.backup_version() == "2026.10.07-1" and not os.path.exists(up.path("backup_new")), "직전 판(A)의 바뀐·치운 파일을 보관")
check(not os.path.exists(up.path("staging")) and not os.path.exists(up.path("alive.json")), "staging·alive 정리")
check(ops.calls == ["end", "ver:2026.10.07-2", "after:2026.10.07-2", "deltask"], f"순서 ({ops.calls})")

print("\n=== 2. 3분 점검 실패 → 되돌리기 ===")
setup_a_and_staged_b()
ops = FakeOps(good=("2026.10.07-1",))
uh.main(ops)
s = up.read_state()
check(read(PROG, "a.py") == "A1" and read(PROG, "b.py") == "B1" and read(PROG, "c.py") is None, "옛 판 파일 그대로 돌아왔다")
check(json.load(open(os.path.join(PROG, "manifest.json"), encoding="utf-8"))["version"] == "2026.10.07-1", "manifest 도 옛 판")
check(s["state"] == "rolled_back" and "3분" in (s.get("reason") or "") and "설치 파일" not in s["reason"], f"rolled_back + 까닭 ({s.get('reason')})")
check(ops.calls == ["end", "ver:2026.10.07-2", "after:2026.10.07-2", "end", "ver:2026.10.07-1", "after:2026.10.07-1", "deltask"], f"순서 ({ops.calls})")
check(not os.path.exists(up.path("backup_new")) and not os.path.exists(up.path("staging")), "바꾸던 보관·staging 정리")

print("\n=== 3. 새 판·옛 판 모두 점검 실패 (Review Focus 5) ===")
setup_a_and_staged_b()
ops = FakeOps(good=())
uh.main(ops)
s = up.read_state()
check(s["state"] == "rolled_back" and "설치 파일로 다시 설치" in s["reason"] and read(PROG, "a.py") == "A1", f"파일은 옛 판, 까닭에 다시 설치 안내 ({s['reason']})")
check(ops.calls.count("after:2026.10.07-1") == 1, "되돌리기를 되풀이하지 않는다")

print("\n=== 4. 옮기는 도중 어디서 끊겨도 되돌리면 옛 판 (Review Focus 2) ===")


class Crash(BaseException):
    pass


real_move = uh._move
for n in range(1, 5):            # 옮기기 = 보관 2번(a·b, c 는 원래 없음) + 넣기 2번(a·c) - 그 모든 자리에서
    setup_a_and_staged_b()
    count = [0]

    def boom(src, dst, n=n):
        count[0] += 1
        if count[0] == n:
            raise Crash()
        real_move(src, dst)

    uh._move = boom
    try:
        uh.main(FakeOps())
    except Crash:
        pass
    finally:
        uh._move = real_move
    mid = up.read_state()["state"]
    uh.main(FakeOps(good=("2026.10.07-1",)))          # 다음 로그온 (--recover)
    s = up.read_state()
    check(read(PROG, "a.py") == "A1" and read(PROG, "b.py") == "B1" and read(PROG, "c.py") is None
          and read(PROG, "keep.py") == "K" and s["state"] == "rolled_back",
          f"{n}번째 옮기기에서 끊김({mid}) → 다음 로그온에 옛 판 ({s['state']})")
for where in ("ver", "after"):
    setup_a_and_staged_b()
    ops = FakeOps()
    setattr(ops, "set_display_version" if where == "ver" else "after_install", lambda *a: (_ for _ in ()).throw(Crash()))
    try:
        uh.main(ops)
    except Crash:
        pass
    uh.main(FakeOps(good=("2026.10.07-1",)))
    check(read(PROG, "a.py") == "A1" and up.read_state()["state"] == "rolled_back", f"{where} 단계에서 끊김 → 되돌림")

print("\n=== 5. 되돌리는 도중 끊겨도 이어서 되돌린다 ===")
setup_a_and_staged_b()
ops = FakeOps(good=())
calls = [0]
orig_after = ops.after_install


def after_then_crash(p):
    calls[0] += 1
    if calls[0] == 2:          # 첫 번째 = 새 판 점검, 두 번째 = 되돌린 옛 판 - 여기서 끊김
        raise Crash()
    return orig_after(p)


ops.after_install = after_then_crash
try:
    uh.main(ops)
except Crash:
    pass
check(up.read_state()["state"] == "rolling_back", "되돌리는 중 표시가 남았다")
uh.main(FakeOps(good=("2026.10.07-1",)))
check(read(PROG, "a.py") == "A1" and up.read_state()["state"] == "rolled_back", "다음 로그온에 되돌리기를 마친다")

print("\n=== 6. 할 일이 없으면 작업만 지운다 ===")
up.write_state({"state": "done"})
ops = FakeOps()
check(uh.main(ops) == 0 and ops.calls == ["deltask"], "done 이면 작업만 지움")

print("\n=== 7. [이전 판으로 되돌리기] 도 같은 길 - 보관본은 방금 판이 된다 ===")
setup_a_and_staged_b()
uh.main(FakeOps())                                    # A → B (보관 A)
up.stage_rollback(PROG, up.path("staging"))           # 보관 A → staging
up.write_state({"state": "ready", "mode": "rollback", "target": "2026.10.07-1", "from": "2026.10.07-2",
                "program_dir": PROG, "staging": up.path("staging"), "at": up.now_text()})
uh.main(FakeOps())
check(read(PROG, "a.py") == "A1" and read(PROG, "b.py") == "B1" and read(PROG, "c.py") is None and up.backup_version() == "2026.10.07-2",
      "B → A, 보관본은 B (다시 앞으로 갈 수 있다)")

print("\n=== 8. 성공 정리 도중 끊겨도 다음 실행이 마저 정리 - 되돌리지 않는다 ===")
real_rmtree, real_replace, real_remove = shutil.rmtree, os.replace, os.remove
for n in range(1, 5):            # 보관 지우기·보관 바꾸기·staging 지우기·alive 지우기
    setup_a_and_staged_b()
    cnt = [0]

    def wrap(real, n=n):
        def f(*a, **k):
            if up.read_state().get("state") == "done":
                cnt[0] += 1
                if cnt[0] == n:
                    raise Crash()
            return real(*a, **k)
        return f

    shutil.rmtree, os.replace, os.remove = wrap(real_rmtree), wrap(real_replace), wrap(real_remove)
    ops1 = FakeOps()
    try:
        uh.main(ops1)
    except Crash:
        pass
    finally:
        shutil.rmtree, os.replace, os.remove = real_rmtree, real_replace, real_remove
    ops2 = FakeOps()
    uh.main(ops2)
    s = up.read_state()
    check(s["state"] == "done" and read(PROG, "a.py") == "A2" and read(PROG, "c.py") == "C2" and read(PROG, "b.py") is None
          and json.load(open(os.path.join(PROG, "manifest.json"), encoding="utf-8"))["version"] == "2026.10.07-2"
          and up.backup_version() == "2026.10.07-1" and read(up.path("backup", "files"), "a.py") == "A1"
          and not os.path.exists(up.path("backup_new")) and not os.path.exists(up.path("staging")) and not os.path.exists(up.path("alive.json")),
          f"정리 {n}번째에서 끊김 → 다시 실행하면 done·새 판·보관은 옛 판 ({s['state']})")
    check("deltask" not in ops1.calls and "end" not in ops2.calls, f"정리 {n}: 끊긴 쪽은 작업을 안 지움, 다시 실행은 되돌리기 안 함")

print("\n=== 9. 보통 오류(끊김 아님) → 바로 되돌린다 ===")
for n in range(1, 5):
    setup_a_and_staged_b()
    count = [0]

    def oserr(src, dst, n=n):
        count[0] += 1
        if count[0] == n:
            raise PermissionError("잠긴 파일")
        real_move(src, dst)

    uh._move = oserr
    ops = FakeOps(good=("2026.10.07-1",))
    try:
        uh.main(ops)
    finally:
        uh._move = real_move
    s = up.read_state()
    check(read(PROG, "a.py") == "A1" and read(PROG, "b.py") == "B1" and read(PROG, "c.py") is None and s["state"] == "rolled_back"
          and "바꾸는 중 오류 (PermissionError)" in s["reason"] and "설치 파일" not in s["reason"] and ops.calls[-1] == "deltask",
          f"{n}번째 옮기기 오류 → 바로 옛 판 ({s.get('reason')})")

print("\n=== 10. 되돌리는 중에도 오류 → 남기고 멈춘다 (되풀이 없음) ===")
setup_a_and_staged_b()
count = [0]


def always_fail(src, dst):
    count[0] += 1
    if count[0] >= 3:
        raise OSError("디스크 오류")
    real_move(src, dst)


uh._move = always_fail
ops = FakeOps(good=())
try:
    uh.main(ops)
finally:
    uh._move = real_move
s = up.read_state()
check(s["state"] == "rolled_back" and "설치 파일로" in s["reason"] and ops.calls[-1] == "deltask", f"rolled_back + 다시 설치 안내 ({s.get('reason')})")
ops = FakeOps()
uh.main(ops)
check(ops.calls == ["deltask"], "다음 로그온에는 할 일 없음")

print("\n=== 11. 옛 manifest 보관 복사 도중 끊겨도 프로그램 manifest 는 온전 ===")
setup_a_and_staged_b()
real_copy2 = shutil.copy2


def half(src, dst, *a, **k):
    data = open(src, "rb").read()
    open(dst, "wb").write(data[:10])
    raise Crash()


shutil.copy2 = half
try:
    uh.main(FakeOps())
except Crash:
    pass
finally:
    shutil.copy2 = real_copy2
uh.main(FakeOps(good=("2026.10.07-1",)))
try:
    mv = json.load(open(os.path.join(PROG, "manifest.json"), encoding="utf-8"))["version"]
except Exception:
    mv = None
check(mv == "2026.10.07-1" and read(PROG, "a.py") == "A1" and up.read_state()["state"] == "rolled_back", f"manifest 온전 ({mv})")

shutil.rmtree(tmp, ignore_errors=True)
print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
