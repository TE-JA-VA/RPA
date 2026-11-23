# -*- coding: utf-8 -*-
"""스탠드얼론 로컬 서버의 저장소 핵심 시험 (HTTP 없이) - Store(RTDB 자리 흉내·구독)와 Runs(실행 기록 SQLite).
    .venv\\Scripts\\python.exe tests\\test_local_store_core.py
시험은 진짜 ProgramData 를 건드리지 않는다 - 임시 폴더만 쓴다.
"""
import json
import os
import queue
import shutil
import sys
import tempfile
import threading

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
import local_server  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def drain(q, wait=0.05):
    """큐에 쌓인 것을 모두 꺼낸다."""
    out = []
    while True:
        try:
            out.append(q.get(timeout=wait))
        except queue.Empty:
            return out


def test_store(tmpdir):
    print("[Store] 읽기·쓰기·여러 자리 쓰기·거르기")
    tmp = os.path.join(tmpdir, "store.json")
    s = local_server.Store(tmp)
    check("빈 나무의 루트는 None", s.get("") is None)
    check("없는 자리는 None", s.get("apps/rpa/nothing") is None)
    s.put("apps/rpa/live/c1/p1", {"state": "idle"})
    check("읽기", s.get("apps/rpa/live/c1/p1") == {"state": "idle"})
    check("중간 가지 읽기", s.get("apps/rpa/live/c1") == {"p1": {"state": "idle"}})
    check("잎 읽기", s.get("apps/rpa/live/c1/p1/state") == "idle")
    got = s.get("apps/rpa/live/c1/p1")
    got["state"] = "고침"
    check("읽은 값을 고쳐도 저장소는 그대로", s.get("apps/rpa/live/c1/p1") == {"state": "idle"})

    s.patch("apps/rpa/commands/c1/p1", {"k1/state": "queued", "k1/type": "launch", "k2/state": "done"})
    check("여러 자리 쓰기", s.get("apps/rpa/commands/c1/p1/k1") == {"state": "queued", "type": "launch"})
    check("거르기", s.get("apps/rpa/commands/c1/p1", order_by="state", equal_to="queued")
          == {"k1": {"state": "queued", "type": "launch"}})
    check("거르기 - 맞는 것 없으면 None", s.get("apps/rpa/commands/c1/p1", order_by="state", equal_to="x") is None)
    check("거르기 - 값이 숫자면 문자와 다름", s.get("apps/rpa/commands/c1/p1", order_by="state", equal_to=1) is None)

    s.patch("apps/rpa/commands/c1/p1/k1", {"state": "running"})
    check("patch 는 있던 다른 칸을 남김", s.get("apps/rpa/commands/c1/p1/k1") == {"state": "running", "type": "launch"})
    s.patch("apps/rpa/commands/c1/p1/k1", {"type": None})
    check("patch 값 None 은 그 칸을 지움", s.get("apps/rpa/commands/c1/p1/k1") == {"state": "running"})
    s.put("apps/rpa/commands/c1/p1/k1/state", None)
    check("put 값 None 은 지움(빈 가지 없앰)", s.get("apps/rpa/commands/c1/p1/k1") is None
          and s.get("apps/rpa/commands/c1/p1") == {"k2": {"state": "done"}})

    s.delete("apps/rpa/commands/c1/p1/k2")
    check("빈 가지 없앰", s.get("apps/rpa/commands/c1") is None)
    check("빈 가지가 위로 번지지 않음 - 다른 가지는 남음", s.get("apps/rpa/live/c1/p1") == {"state": "idle"})
    s.delete("apps/rpa/nothing/at/all")
    check("없는 자리 지우기는 조용히", s.get("apps/rpa/live/c1/p1") == {"state": "idle"})
    s.put("a/b", {})
    check("빈 dict 를 쓰면 없는 것과 같다", s.get("a") is None and s.get("a/b") is None)
    s.put("a/b", {"c": {}, "d": 1})
    check("값 안의 빈 가지도 없앰", s.get("a/b") == {"d": 1})
    s.put("a/b/d/e", 5)
    check("잎 아래로 쓰면 잎을 가지로 바꿈", s.get("a/b") == {"d": {"e": 5}})
    check("앞뒤 슬래시 무시", s.get("/a/b/d/e/") == 5)
    s.put("", {"x": {"y": 1}})
    check("루트 통째로 쓰기", s.get("") == {"x": {"y": 1}})
    s.delete("x/y")
    check("루트 비면 get('') None", s.get("") is None)

    s.put("apps/rpa/live/c1/p1", {"state": "idle", "n": 1.5, "t": True, "한글": "값"})
    check("다시 열어도 남음", local_server.Store(tmp).get("apps/rpa/live/c1/p1")
          == {"state": "idle", "n": 1.5, "t": True, "한글": "값"})
    left = [f for f in os.listdir(tmpdir) if f != "store.json"]
    check("임시 파일이 남지 않음", left == [], str(left))
    with open(tmp, encoding="utf-8") as f:
        check("저장 파일은 JSON", isinstance(json.load(f), dict))


def test_subscribe(tmpdir):
    print("[Store] 구독")
    s = local_server.Store(os.path.join(tmpdir, "sub.json"))
    q = s.subscribe("apps/rpa/commands/c1/p1", order_by="state", equal_to="queued")
    check("처음 값", q.get(timeout=1) == ("put", {"path": "/", "data": None}))
    s.put("apps/rpa/commands/c1/p1/k3", {"state": "queued"})
    check("새 명령", q.get(timeout=1) == ("put", {"path": "/k3", "data": {"state": "queued"}}))
    s.patch("apps/rpa/commands/c1/p1/k3", {"state": "running"})
    check("조건에서 빠짐", q.get(timeout=1) == ("put", {"path": "/k3", "data": None}))
    s.put("apps/rpa/commands/c1/p1/k4", {"state": "done"})
    s.put("apps/rpa/live/c1/p1", {"state": "idle"})
    check("조건에 안 맞는 새 자식·다른 자리는 알리지 않음", drain(q) == [])
    s.patch("apps/rpa/commands/c1/p1", {"k4/state": "queued"})
    check("여러 자리 쓰기로 조건에 들어옴", q.get(timeout=1)
          == ("put", {"path": "/k4", "data": {"state": "queued"}}))
    s.delete("apps/rpa/commands/c1/p1/k4")
    check("지워서 빠짐", q.get(timeout=1) == ("put", {"path": "/k4", "data": None}))
    s.put("apps/rpa/commands/c1/p1/k5", {"state": "queued", "type": "launch"})
    s.put("apps/rpa/commands/c1/p1/k5/type", "stop")
    got = drain(q)
    check("자식 안쪽만 바뀌어도 그 자식을 통째로 다시 알림",
          got == [("put", {"path": "/k5", "data": {"state": "queued", "type": "launch"}}),
                  ("put", {"path": "/k5", "data": {"state": "queued", "type": "stop"}})], str(got))
    s.put("apps/rpa/commands/c1/p1", None)
    check("구독 자리 통째로 지움", drain(q)[-1] == ("put", {"path": "/", "data": None}))

    # 이미 조건에 맞는 자식이 있을 때의 처음 값
    s.put("apps/rpa/commands/c1/p1", {"k1": {"state": "queued"}, "k2": {"state": "running"}})
    q2 = s.subscribe("apps/rpa/commands/c1/p1", order_by="state", equal_to="queued")
    check("처음 값은 거른 것", q2.get(timeout=1) == ("put", {"path": "/", "data": {"k1": {"state": "queued"}}}))
    s.unsubscribe(q2)
    s.put("apps/rpa/commands/c1/p1/k7", {"state": "queued"})
    check("구독을 끊으면 더 안 옴", drain(q2) == [])

    # 거르지 않는 구독 - 상대 경로
    q3 = s.subscribe("apps/rpa/live/c1")
    check("거르지 않은 처음 값", q3.get(timeout=1) == ("put", {"path": "/", "data": {"p1": {"state": "idle"}}}))
    s.put("apps/rpa/live/c1/p1/state", "busy")
    check("깊은 쓰기는 상대 경로", q3.get(timeout=1) == ("put", {"path": "/p1/state", "data": "busy"}))
    s.patch("apps/rpa/live/c1/p1", {"state": "idle", "step": 2})
    check("patch 는 patch 로", q3.get(timeout=1) == ("patch", {"path": "/p1", "data": {"state": "idle", "step": 2}}))
    s.patch("apps/rpa/live/c1", {"p2/state": "idle"})
    check("구독 자리 patch 의 경로는 /", q3.get(timeout=1) == ("patch", {"path": "/", "data": {"p2/state": "idle"}}))
    s.delete("apps/rpa/live/c1/p2")
    check("지우면 put None", q3.get(timeout=1) == ("put", {"path": "/p2", "data": None}))
    s.put("apps/rpa/live/c1", {"p9": {"state": "x"}})
    check("구독 자리를 통째로 쓰면 / 에 새 값", q3.get(timeout=1) == ("put", {"path": "/", "data": {"p9": {"state": "x"}}}))
    s.put("apps/rpa", {"live": {"c1": {"p8": 1}}})
    check("윗자리를 쓰면 / 에 새 값", q3.get(timeout=1) == ("put", {"path": "/", "data": {"p8": 1}}))
    s.put("apps/rpa/commands/c1/p1/k1/state", "done")
    check("구독 밖 쓰기는 알리지 않음", drain(q3) == [])
    s.unsubscribe(q3)
    s.unsubscribe(q3)      # 두 번 끊어도 죽지 않는다
    check("두 번 끊어도 예외 없음", True)

    # 한 쓰기를 여러 구독자가 받는다
    qa, qb = s.subscribe("apps/rpa/live"), s.subscribe("apps/rpa/live/c1")
    drain(qa), drain(qb)
    s.put("apps/rpa/live/c1/pz", 1)
    check("구독자마다 자기 기준 경로", qa.get(timeout=1) == ("put", {"path": "/c1/pz", "data": 1})
          and qb.get(timeout=1) == ("put", {"path": "/pz", "data": 1}))


def test_broken(tmpdir):
    print("[Store] 깨진 파일")
    tmp2 = os.path.join(tmpdir, "broken.json")
    with open(tmp2, "w", encoding="utf-8") as f:
        f.write('{"apps": {"rp')           # 반쯤 쓴 파일
    s2 = local_server.Store(tmp2)
    check("깨진 파일 - 빈 나무", s2.get("") is None and os.path.exists(tmp2 + ".broken"))
    with open(tmp2 + ".broken", encoding="utf-8") as f:
        check("깨진 내용을 .broken 에 보존", f.read() == '{"apps": {"rp')
    s2.put("a/b", 1)
    check("깨진 뒤에도 쓰기 됨", local_server.Store(tmp2).get("a/b") == 1)

    tmp3 = os.path.join(tmpdir, "empty.json")
    open(tmp3, "w").close()
    check("0바이트 파일 - 죽지 않음", local_server.Store(tmp3).get("") is None)
    tmp4 = os.path.join(tmpdir, "list.json")
    with open(tmp4, "w", encoding="utf-8") as f:
        f.write("[1, 2]")
    check("나무가 dict 가 아니면 깨진 것으로", local_server.Store(tmp4).get("") is None
          and os.path.exists(tmp4 + ".broken"))
    tmp5 = os.path.join(tmpdir, "bin.json")
    with open(tmp5, "wb") as f:
        f.write(b"\xff\xfe\x00\x80garbage")
    check("바이트가 깨져도 죽지 않음", local_server.Store(tmp5).get("") is None)
    tmp6 = os.path.join(tmpdir, "newdir", "deep", "store.json")
    s6 = local_server.Store(tmp6)
    s6.put("k", 1)
    check("없는 폴더도 만들어 저장", local_server.Store(tmp6).get("k") == 1)


def test_concurrent(tmpdir):
    print("[Store] 동시에 쓰기")
    tmp = os.path.join(tmpdir, "conc.json")
    s = local_server.Store(tmp)
    q = s.subscribe("n")
    errors = []

    def work(t):
        try:
            for i in range(25):
                s.put(f"n/t{t}/i{i}", i)
        except Exception as e:  # noqa: BLE001
            errors.append(repr(e))

    threads = [threading.Thread(target=work, args=(t,)) for t in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    check("스레드 예외 없음", errors == [], str(errors))
    data = s.get("n")
    check("모든 쓰기가 남음", data is not None and len(data) == 8 and all(len(v) == 25 for v in data.values()))
    again = local_server.Store(tmp)
    check("파일이 깨지지 않고 같은 내용", again.get("n") == data and not os.path.exists(tmp + ".broken"))
    got = drain(q, wait=0.2)
    check("알림 개수 = 처음 1 + 쓰기 200", len(got) == 201, str(len(got)))


def test_runs(tmpdir):
    print("[Runs] 실행 기록")
    db = os.path.join(tmpdir, "runs.db")
    r = local_server.Runs(db)
    check("기록 만들기", r.create("runs/c1", "items", "d1",
                              {"pcId": "p1", "date": "2026-11-23", "started_at": "2026-11-23T09:00:00", "cost": 3}))
    check("같은 id 두 번", r.create("runs/c1", "items", "d1",
                               {"pcId": "p1", "date": "2026-11-23", "started_at": "2026-11-23T09:05:00", "cost": 99}) is False)
    check("두 번째 시도가 첫 기록을 덮지 않음", r.get("runs/c1/items/d1")["cost"] == 3)
    r.create("runs/c1", "items", "d2", {"pcId": "p1", "date": "2026-11-23", "started_at": "2026-11-23T10:00:00"})   # cost 없음
    check("합 (칸 없는 문서 뺌)", r.sum("runs/c1", "items", "cost") == 3)
    check("since", r.sum("runs/c1", "items", "cost", since="2026-11-23T09:30:00") == 0)
    check("since 가 같으면 포함", r.sum("runs/c1", "items", "cost", since="2026-11-23T09:00:00") == 3)
    check("없는 칸의 합은 0", r.sum("runs/c1", "items", "nothing") == 0)
    check("최근 순", [d["started_at"] for d in r.query("runs/c1", "items", pc_id="p1")]
          == ["2026-11-23T10:00:00", "2026-11-23T09:00:00"])
    check("get 은 칸 그대로", r.get("runs/c1/items/d1")
          == {"pcId": "p1", "date": "2026-11-23", "started_at": "2026-11-23T09:00:00", "cost": 3})
    check("없는 기록 get 은 None", r.get("runs/c1/items/zz") is None and r.get("runs/c1") is None)

    r.create("runs/c1", "items", "d3", {"pcId": "p2", "date": "2026-11-24", "started_at": "2026-11-24T08:00:00", "cost": 1.5})
    r.create("runs/c2", "items", "d1", {"pcId": "p1", "date": "2026-11-23", "started_at": "2026-11-23T09:00:00", "cost": 100})
    r.create("runs/c1", "other", "d1", {"pcId": "p1", "started_at": "2026-11-23T09:00:00", "cost": 100})
    check("합은 업체·모음별로 나뉨", r.sum("runs/c1", "items", "cost") == 4.5)
    check("날짜로 거르기", [d["started_at"] for d in r.query("runs/c1", "items", date="2026-11-24")] == ["2026-11-24T08:00:00"])
    check("PC 로 거르기", len(r.query("runs/c1", "items", pc_id="p2")) == 1)
    check("PC·날짜 같이", r.query("runs/c1", "items", pc_id="p1", date="2026-11-24") == [])
    check("거르지 않으면 모두 최근 순", [d["started_at"] for d in r.query("runs/c1", "items")]
          == ["2026-11-24T08:00:00", "2026-11-23T10:00:00", "2026-11-23T09:00:00"])
    check("limit", len(r.query("runs/c1", "items", limit=2)) == 2)
    r.create("runs/c3", "items", "한글", {"pcId": "p1", "started_at": "2026-11-23T09:00:00", "메모": "가나다"})
    check("한글 칸·id", r.get("runs/c3/items/한글")["메모"] == "가나다")
    r.create("runs/c1", "items", "dx", {"pcId": "p1", "started_at": "2026-11-25T00:00:00", "cost": "abc"})
    check("숫자 아닌 칸은 합에서 뺌", r.sum("runs/c1", "items", "cost") == 4.5)
    r.close()
    r2 = local_server.Runs(db)
    check("다시 열어도 남음", r2.get("runs/c1/items/d1")["cost"] == 3)

    # 여러 스레드에서 (HTTP 서버가 스레드마다 부른다)
    errors, created = [], []

    def work(t):
        try:
            for i in range(20):
                created.append(r2.create("runs/c9", "items", f"t{t}-{i}", {"pcId": "p1", "started_at": f"2026-11-23T{t:02d}:{i:02d}:00", "cost": 1}))
                r2.sum("runs/c9", "items", "cost")
                r2.query("runs/c9", "items", limit=5)
        except Exception as e:  # noqa: BLE001
            errors.append(repr(e))

    threads = [threading.Thread(target=work, args=(t,)) for t in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    check("스레드 예외 없음", errors == [], str(errors))
    check("스레드에서 만든 120건 모두 남음", all(created) and r2.sum("runs/c9", "items", "cost") == 120)
    r2.close()


def test_data_dir(tmpdir):
    print("[data_dir]")
    old = os.environ.get("RPA_PROGRAMDATA")
    root = os.path.join(tmpdir, "pd")
    os.environ["RPA_PROGRAMDATA"] = root
    try:
        d = local_server.data_dir()
        check("install_root\\standalone", d == os.path.join(root, "standalone"), d)
        check("없으면 만든다", os.path.isdir(d))
        check("두 번째 불러도 같음", local_server.data_dir() == d)
    finally:
        if old is None:
            os.environ.pop("RPA_PROGRAMDATA", None)
        else:
            os.environ["RPA_PROGRAMDATA"] = old
    check("포트", local_server.PORT == 8781)


def main():
    tmpdir = tempfile.mkdtemp(prefix="local_store_core_")
    try:
        test_store(tmpdir)
        test_subscribe(tmpdir)
        test_broken(tmpdir)
        test_concurrent(tmpdir)
        test_runs(tmpdir)
        test_data_dir(tmpdir)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    print()
    if fails:
        print(f"실패 {len(fails)}건: " + ", ".join(fails))
        sys.exit(1)
    print("전부 통과")


if __name__ == "__main__":
    main()
