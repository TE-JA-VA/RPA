# -*- coding: utf-8 -*-
"""부하 시험 (오래 걸린다, 따로 돌린다) - CPU 를 바쁘게 해 두고 A 기록을 다음 날·기다림 없이 번갈아 22번 재생한다.
옛 파일을 한 번이라도 받으면 실패. PC 가 바쁠 때 innerText 가 표 칸 사이 띄어쓰기를 빼먹어 옛 줄이 새것처럼 보였던 일
(2026-09-30, 그래서 글자는 textContent 로 읽는다)을 잡는다.
    .venv\\Scripts\\python.exe tests\\stress_web_replay.py
"""
import datetime
import multiprocessing
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake_mall  # noqa: E402
import web_replay as rec  # noqa: E402
from test_web_replay import DAY, human  # noqa: E402


def burn(stop):
    while not stop.is_set():
        sum(i * i for i in range(20000))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    out = tempfile.mkdtemp(prefix="rpa_stress_")
    srv, url, _ = fake_mall.start(DAY, True)
    srv.mall = mall = fake_mall.Mall(DAY, True)
    a = rec.record(url + "/login", os.path.join(out, "rec_a.json"), headless=True, human=human(mall, True, noise=True),
                   record_date=DAY)
    stop = multiprocessing.Event()
    burners = [multiprocessing.Process(target=burn, args=(stop,)) for _ in range(max(2, (os.cpu_count() or 4) - 2))]
    for b in burners:
        b.start()
    bad = 0
    try:
        for rnd in range(11):
            for off, settle in ((1, 3000), (3, 0)):
                day = DAY + datetime.timedelta(days=off)
                srv.mall = m = fake_mall.Mall(day, False)
                rec.SETTLE_MAX_MS = settle
                ok, r = rec.replay(a, {"ID": fake_mall.USER, "PW": fake_mall.PASSWORD}, os.path.join(out, "dl"), "012",
                                   today=day, log=lambda x: None)
                good = ok and m.downloads == [m.requests[-1]["id"]]
                print(rnd, off, settle, "OK" if good else "XXXX 옛 파일 또는 멈춤", m.downloads, r.results[-1][2][:40], flush=True)
                bad += not good
    finally:
        stop.set()
        for b in burners:
            b.join()
        srv.shutdown()
    print("실패:", bad or "없음")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
