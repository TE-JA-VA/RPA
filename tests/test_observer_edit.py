# -*- coding: utf-8 -*-
"""옵저버 미리보기 멈춘 자리부터 [수정] (설계 2026-10-19 4.2절) - Worker 를 직접 몰아 가짜 쇼핑몰에서 본다.
Edge 창이 뜬다 (미리보기는 창을 보이게 띄운다). 마우스·키보드는 쓰지 않는다 (Playwright 가 그 창 안에서만 누른다).

    .venv\\Scripts\\python.exe tests\\test_observer_edit.py
"""
import datetime
import glob
import json
import os
import queue
import sys
import tempfile
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="rpa_observer_edit_")
os.environ["RPA_USER_CONFIG"] = os.path.join(TMP, "config", "RPA_UserConfig.json")
os.environ["RPA_PROGRAMDATA"] = os.path.join(TMP, "programdata")
os.environ["RPA_STATUS_DIR"] = os.path.join(TMP, "status")
os.environ["RPA_OBSERVER_LOCK"] = rf"Local\AFTER_MARKET_RPA_OBSERVER_EDIT_TEST_{os.getpid()}"
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(TMP, "no_browsers")
os.makedirs(os.path.join(TMP, "config"))
os.makedirs(os.path.join(TMP, "programdata", "config"))
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.stdout.reconfigure(encoding="utf-8")

import fake_mall  # noqa: E402
import rpa_observer as rr  # noqa: E402
import rpa_status as st  # noqa: E402
import web_replay as rec  # noqa: E402
from test_web_replay import hclick  # noqa: E402

TODAY = datetime.date.today()
PROFILES = os.path.join(tempfile.gettempdir(), rr.PROFILE_PREFIX + "*")
CREDS = {"ID": fake_mall.USER, "PW": fake_mall.PASSWORD, "Phone": "", "SmsSenders": []}
fails = []


def check(name, cond, detail=""):
    print(f"  [{'통과' if cond else '실패'}] {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


class SpyQueue(queue.Queue):
    """화면 큐 - 일꾼 스레드가 넣는 순간 hook 을 부른다 (다음 단계로 가기 전에 일시정지를 켤 수 있게)."""

    def __init__(self):
        super().__init__()
        self.hook = None

    def put(self, m, *a, **k):
        super().put(m, *a, **k)
        if self.hook:
            self.hook(m)


def human_login_menu(page):
    """기록: 아이디·비밀번호·[로그인] → 주문관리 올리고 발송처리 → 검색 (6단계)."""
    hclick(page, page.get_by_placeholder("아이디"))
    page.keyboard.type(fake_mall.USER, delay=15)
    hclick(page, page.get_by_placeholder("비밀번호"))
    page.keyboard.type(fake_mall.PASSWORD, delay=15)
    hclick(page, page.get_by_role("button", name="로그인", exact=True))
    page.wait_for_url("**/main**")
    page.get_by_role("link", name="주문관리", exact=True).hover()
    hclick(page, page.get_by_role("link", name="발송처리", exact=True))
    fl = page.frame_locator("iframe[name=content]")
    fl.locator("#btnSearch").wait_for()
    hclick(page, fl.locator("#btnSearch"))
    fl.get_by_text("검색 결과").wait_for()


def human_ship(page):
    """이어서: 배송관리 올리고 송장전송 (hover + click = 새 단계 2개)."""
    page.get_by_role("link", name="배송관리", exact=True).hover()
    hclick(page, page.get_by_role("link", name="송장전송", exact=True))
    page.frame_locator("iframe[name=content]").get_by_text("송장전송").wait_for()
    page.wait_for_timeout(300)


def human_login_only(page):
    hclick(page, page.get_by_role("button", name="로그인", exact=True))
    page.wait_for_url("**/main**")
    page.wait_for_timeout(300)


def with_ids(record):
    r = json.loads(json.dumps(record))
    for k, s in enumerate(r["steps"]):
        s["id"] = k
    return r


def drain(ui, until, timeout=180):
    """until(m) 이 참인 메시지까지 받는다 → 받은 것 전부."""
    got, end = [], datetime.datetime.now() + datetime.timedelta(seconds=timeout)
    while datetime.datetime.now() < end:
        try:
            m = ui.get(timeout=1)
        except queue.Empty:
            continue
        got.append(m)
        if until(m):
            return got
    raise RuntimeError(f"기다리던 메시지가 안 옴: {[m[0] for m in got]}")


def kinds(msgs):
    return [m[0] for m in msgs if m[0] not in ("status", "viewport", "progress")]


def run_edit(label, record, human_new, stop_after_ok, want_cut):
    """미리보기 → (stop_after_ok 번째 성공 뒤 일시정지 | 실패) → [수정] → 새 단계 기록 → 기록 끝. 결과 묶음을 돌려준다."""
    print(f"--- {label}")
    r = with_ids(record)
    ids = [s["id"] for s in r["steps"]]
    ui = SpyQueue()
    w = rr.Worker({"left": 0, "top": 0, "width": 1000, "height": 720}, ui, "")
    w.step_wait = (2.0, 1)                   # 못 찾으면 2초 한 번만 (기본 20초 × 6)
    before = set(glob.glob(PROFILES))
    w.start()
    drain(ui, lambda m: m[0] == "ready")
    n_ok = [0]

    def hook(m):
        if m[0] == "progress" and m[2] == "ok":
            n_ok[0] += 1
            if stop_after_ok and n_ok[0] == stop_after_ok:
                w.pause.set()
    ui.hook = hook
    w.cmd.put(("preview", 0, r, ids, CREDS, "012", "① 가짜몰"))
    got = drain(ui, lambda m: m[0] in ("paused", "failed_at", "preview_done"))
    out = {"first": got[-1], "flow": kinds(got)}
    if got[-1][0] == "preview_done":
        w.cmd.put(("quit",))
        w.join(20)
        return out
    w.edit.set()
    got = drain(ui, lambda m: m[0] in ("editing", "preview_done"))
    out["flow"] += kinds(got)
    out["editing"] = got[-1]
    if got[-1][0] != "editing":
        w.cmd.put(("quit",))
        w.join(20)
        return out
    out["profiles_editing"] = sorted(set(glob.glob(PROFILES)) - before)
    out["history_preview"] = (st.read_history(program="observer") or [{}])[0]
    w.human = human_new
    w.cmd.put(("human",))
    got = drain(ui, lambda m: m[0] == "human_done")
    out["flow"] += kinds(got)
    raw = [m[2] for m in got if m[0] == "steps"]
    out["raw"] = raw[-1] if raw else []
    w.cmd.put(("stop",))
    got = drain(ui, lambda m: m[0] == "recording_stopped")
    out["flow"] += kinds(got)
    out["profiles_after"] = sorted(set(glob.glob(PROFILES)) - before)
    w.cmd.put(("quit",))
    w.join(20)
    # 화면이 하는 것과 같게: 남긴 앞부분(head) + 새 단계 (continue_record)
    cut = out["editing"][2]
    k = next(i for i, s in enumerate(r["steps"]) if s["id"] == cut)
    head = dict(r, steps=r["steps"][:k])
    out["final"] = rec.continue_record(head, json.loads(json.dumps(out["raw"])), TODAY)
    for s in out["final"]["steps"]:
        s.pop("id", None)
    for i, s in enumerate(out["final"]["steps"], 1):
        print(f"    {i:2d}. {rec.describe(s)}")
    out["cut_ok"] = cut == want_cut
    return out


def main():
    srv, url, _ = fake_mall.start(TODAY, False)
    try:
        a = rec.record(url + "/login", os.path.join(TMP, "rec_a.json"), headless=True, human=human_login_menu, record_date=TODAY)
        print("기록 A:")
        for i, s in enumerate(a["steps"], 1):
            print(f"    {i:2d}. {rec.describe(s)}")
        check("A: 6단계 (아이디·비밀번호·로그인·메뉴 올리기·발송처리·검색)", len(a["steps"]) == 6
              and [s["kind"] for s in a["steps"]] == ["fill", "secret", "click", "hover", "click", "click"], str([s["kind"] for s in a["steps"]]))

        # 1. 3단계(로그인)까지 하고 일시정지 → [수정] → 배송관리·송장전송 → 기록 끝
        srv.mall = fake_mall.Mall(TODAY, False)
        o = run_edit("1. 일시정지 뒤 [수정]", a, human_ship, 3, 3)
        check("1: 3단계 성공 뒤 일시정지 - 화면 흐름 paused → editing → steps → recording_stopped",
              o["first"][0] == "paused" and [x for x in o["flow"] if x != "steps"] == ["paused", "editing", "human_done", "recording_stopped"]
              and "steps" in o["flow"] and o["flow"].index("editing") < o["flow"].index("steps"), str(o["flow"]))
        check("1: editing 알림은 (칸 번호, 아직 안 한 4단계의 id = 3)", o.get("editing", ())[:2] == ("editing", 0) and o.get("cut_ok"), str(o.get("editing")))
        check("1: 미리보기 기록은 '중단' 으로 끝나고 사유는 '4단계부터 수정합니다.'", o.get("history_preview", {}).get("state") == "stopped"
              and "4단계부터 수정합니다." in json.dumps(o.get("history_preview", {}), ensure_ascii=False), str(o.get("history_preview"))[:300])
        check("1: 프로필 폴더는 미리보기 것 하나만 (새로 띄우지 않았다), 기록을 끝내면 지워진다",
              len(o.get("profiles_editing", [])) == 1 and o.get("profiles_after") == [], str((o.get("profiles_editing"), o.get("profiles_after"))))
        fs = o.get("final", {}).get("steps", [])
        check("1: 최종 기록 = 남긴 3단계 + 새 2단계 (배송관리 올리기·송장전송), 탭 번호 0",
              len(fs) == 5 and fs[:3] == a["steps"][:3] and [s["kind"] for s in fs[3:]] == ["hover", "click"]
              and fs[4]["target"]["text"] == "송장전송" and all(s["page"] == 0 for s in fs), str([rec.describe(s) for s in fs[3:]]))
        check("1: 새 쪽 첫 단계 gap 은 STEP_GAP_AFTER_EDIT", bool(fs) and fs[3].get("gap") == rec.STEP_GAP_AFTER_EDIT, str(fs[3:4]))
        dump = json.dumps(o.get("final", {}), ensure_ascii=False)
        check("1: 최종 기록에 아이디·비밀번호 값이 없다", fs and fake_mall.PASSWORD not in dump and fake_mall.USER not in dump, dump[:200])
        srv.mall = m = fake_mall.Mall(TODAY, False)
        ok, rp = rec.replay(o["final"], CREDS, os.path.join(TMP, "replay1"), "012", today=TODAY, log=print, step_timeout=10, step_tries=1)
        check("1: 이어 붙인 기록을 처음부터 재생하면 끝까지 간다 (송장전송 화면)", ok and m.logins and len(rp.results) == 5, str(rp.results[-1:]))

        # 2. 3단계 대상이 없는 기록 → failed_at 3 → [수정] → 로그인 누르기 → 기록 끝
        b = json.loads(json.dumps(a))
        b["steps"][2]["target"].update(text="없는 단추", css="#nope", id="nope")
        srv.mall = fake_mall.Mall(TODAY, False)
        o = run_edit("2. 실패한 자리에서 [수정]", b, human_login_only, 0, 2)
        check("2: 3단계를 못 찾으면 브라우저를 닫지 않고 failed_at 3", o["first"] == ("failed_at", 3), str(o["first"]))
        check("2: 화면 흐름 failed_at → editing → steps → recording_stopped, cut 은 3단계의 id = 2",
              [x for x in o["flow"] if x != "steps"] == ["failed_at", "editing", "human_done", "recording_stopped"] and o.get("cut_ok"),
              str((o["flow"], o.get("editing"))))
        check("2: 미리보기 기록 사유 '3단계부터 수정합니다.'", "3단계부터 수정합니다." in json.dumps(o.get("history_preview", {}), ensure_ascii=False),
              str(o.get("history_preview"))[:300])
        fs = o.get("final", {}).get("steps", [])
        check("2: 최종 기록 = 남긴 2단계 + 새 1단계 (로그인)", len(fs) == 3 and fs[:2] == a["steps"][:2] and fs[2]["kind"] == "click"
              and fs[2]["target"]["text"] == "로그인", str([rec.describe(s) for s in fs]))
        check("2: 프로필은 하나, 끝나면 지워진다", len(o.get("profiles_editing", [])) == 1 and o.get("profiles_after") == [],
              str((o.get("profiles_editing"), o.get("profiles_after"))))
        srv.mall = m = fake_mall.Mall(TODAY, False)
        ok, rp = rec.replay(o["final"], CREDS, os.path.join(TMP, "replay2"), "012", today=TODAY, log=print, step_timeout=10, step_tries=1)
        check("2: 고친 기록을 처음부터 재생하면 로그인된다", ok and m.logins == [(fake_mall.USER, True)], str((rp.results[-1:], m.logins)))

        # 3. 실패한 자리에서 [■ 중단] - 닫고 preview_done
        ui = SpyQueue()
        w = rr.Worker({"left": 0, "top": 0, "width": 1000, "height": 720}, ui, "")
        w.step_wait = (2.0, 1)
        before = set(glob.glob(PROFILES))
        w.start()
        drain(ui, lambda m: m[0] == "ready")
        r = with_ids(b)
        srv.mall = fake_mall.Mall(TODAY, False)
        w.cmd.put(("preview", 0, r, [s["id"] for s in r["steps"]], CREDS, "012", "① 가짜몰"))
        got = drain(ui, lambda m: m[0] in ("failed_at", "preview_done"))
        w.cancel.set()
        got += drain(ui, lambda m: m[0] == "preview_done")
        w.cmd.put(("quit",))
        w.join(20)
        done = got[-1]
        check("3: 실패한 자리에서 [■ 중단] 이면 닫고 preview_done (중단 사유), 프로필 지워짐", got[0][0] != "preview_done"
              and done[0] == "preview_done" and done[1] is False and done[4] == "미리보기를 중단하였습니다."
              and set(glob.glob(PROFILES)) - before == set(), str((done, kinds(got))))
    finally:
        srv.shutdown()
    print()
    print(f"실패: {'없음' if not fails else fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
