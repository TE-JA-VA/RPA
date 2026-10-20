"""병렬 수집 시험 (사용자 2026-10-15) - 사이트를 동시에 열되 인증 사이트는 휴대폰마다 한 번에 하나씩.

1. auth_end: 인증번호 단계 다음 [확인] 까지가 인증 구간
2. rpa_status.step(parallel=True): 여러 단계가 함께 진행 중, 끝은 key 로
3. web_runner.run_parallel: 대기열·동시 개수·실패해도 나머지 계속 (브라우저 없이 흉내)
4. 진짜 Edge: 가짜 쇼핑몰 3곳을 기록하고 동시에 재생 - 인증 사이트로 둔 둘은 인증 구간이 겹치지 않고,
   인증 없는 사이트는 그동안 기다리지 않는다. 셋 다 파일을 받는다.

    .venv\\Scripts\\python.exe tests\\test_parallel_collect.py
"""
import datetime
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="rpa_parallel_")
os.environ["RPA_STATUS_DIR"] = os.path.join(_tmp, "status")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")

import rpa_status as status  # noqa: E402
import web_replay as rec  # noqa: E402
import web_runner  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


print("=== 1. 인증 구간 (auth_end)")
S = lambda *kinds: [{"kind": k} for k in kinds]   # noqa: E731
check("인증번호 다음 누르기까지", rec.auth_end(S("fill", "secret", "click", "click", "otp", "click", "click")) == 6)
check("인증번호 다음이 엔터면 거기까지", rec.auth_end(S("fill", "secret", "click", "otp", "enter", "click")) == 5)
check("인증번호 뒤에 누르기가 없으면 인증번호 단계까지", rec.auth_end(S("fill", "secret", "otp")) == 3)
check("인증번호가 없으면 None (기다리지 않는다)", rec.auth_end(S("fill", "secret", "click", "click")) is None)
check("차례는 로그인 칸부터 - 앞의 검색·이동은 기다리지 않는다",
      rec.auth_start(S("goto", "click", "click", "fill", "secret", "enter", "click", "otp", "click")) == 4)
check("로그인 칸이 없으면 첫 단계부터", rec.auth_start(S("goto", "click", "otp", "click")) == 1)
check("[인증번호 받기] 가 첫 칸 넣기보다 앞이면 거기부터 (문자가 차례 밖에서 나가지 않게)",
      rec.auth_start([{"kind": "goto"}, {"kind": "click", "otpSend": True}, {"kind": "fill"}, {"kind": "otp"}, {"kind": "click"}]) == 2)

print("=== 2. 대시보드 단계 - 함께 진행 중")
status.start("prepare")
status.set_steps([("a", "A"), ("b", "B"), ("c", "C")])
status.step("a", parallel=True)
status.step("c", parallel=True)
st = {s["key"]: s["state"] for s in status._state["steps"]}
check("병렬이면 앞 단계가 완료·건너뜀으로 바뀌지 않는다", st == {"a": "running", "b": "pending", "c": "running"}, str(st))
status.done_step(key="a")
status.fail_step("x", key="c")
st = {s["key"]: s["state"] for s in status._state["steps"]}
check("끝은 그 단계만 (key)", st == {"a": "done", "b": "pending", "c": "failed"}, str(st))
status.step("b")
st = {s["key"]: s["state"] for s in status._state["steps"]}
check("병렬이 아니면 예전 그대로", st["b"] == "running", str(st))
status.finish("success")

status.start("prepare")
status.set_steps([("a", "A"), ("c", "C")])
go = threading.Event()


def worker_a():
    status.step("a", parallel=True)
    go.wait()
    status.metric("a:n", "받은 엑셀", 1)
    status.note("a 하는 중")


ta = threading.Thread(target=worker_a)
ta.start()
time.sleep(0.1)
tc = threading.Thread(target=lambda: status.step("c", parallel=True))
tc.start()
tc.join()
go.set()
ta.join()
m = next(x for x in status._state["metrics"] if x["key"] == "a:n")
notes = {s["key"]: s.get("note") for s in status._state["steps"]}
check("병렬: 숫자·메모는 그 실행기의 단계에 붙는다 (마지막에 시작한 다른 사이트 단계가 아니라)",
      m["step"] == "a" and notes == {"a": "a 하는 중", "c": None}, f"{m['step']} {notes}")
status.finish("success")

print("=== 3. 실행기 대기열 (브라우저 흉내)")


class FakePW:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    class chromium:
        launch = None


class FakeBrowser:
    def close(self):
        pass


_saved = web_runner.sync_playwright, web_runner.web_replay.edge, web_runner.run_site
running, peak, ran = [0], [0], []
lock = threading.Lock()


def fake_run_site(browser, name, site, use_session=True, keep_open=False, gates=None):
    with lock:
        running[0] += 1
        peak[0] = max(peak[0], running[0])
    time.sleep(0.2)
    with lock:
        running[0] -= 1
        ran.append(name)
    return name != "S3"      # 하나는 실패


web_runner.sync_playwright = FakePW
web_runner.web_replay.edge = lambda launch, headless=False: FakeBrowser()
web_runner.run_site = fake_run_site
chosen = [(f"S{i}", {}) for i in range(1, 8)]
t0 = time.time()
done = web_runner.run_parallel(chosen, 3, True, None)
took = time.time() - t0
check("7개를 3개씩: 동시에 셋까지만, 모두 돈다", peak[0] == 3 and sorted(ran) == sorted(n for n, _ in chosen), f"{peak} {ran}")
check("한 사이트가 실패해도 나머지는 끝까지 (성공 6)", done == 6, str(done))
check("하나씩보다 빠르다 (0.2초 x 7 = 1.4초 -> 3줄)", took < 1.0, f"{took:.2f}초")

print("=== 3-1. 인증 사이트는 한 창에서 차례로, 나머지 창은 인증 없는 사이트 (사용자 2026-10-19)")
AUTH = {"Action": ["login", "sms_2fa"], "Phone": "p"}
spans, launched = [], []


def lane_run_site(browser, name, site, use_session=True, keep_open=False, gates=None):
    t = time.time()
    time.sleep(0.1)
    with lock:
        spans.append((threading.current_thread().name, name, t, time.time()))
    return True


def lane_edge(launch, headless=False, **_):
    me = threading.current_thread().name
    launched.append(me)
    if me in FAIL_LAUNCH:
        raise RuntimeError("브라우저를 못 띄움")
    return FakeBrowser()


def lanes(chosen, n):
    spans.clear()
    launched.clear()
    done = web_runner.run_parallel(chosen, n, True, None)
    return done, {s[1]: s[0] for s in spans}


web_runner.web_replay.edge = lane_edge
web_runner.run_site = lane_run_site
FAIL_LAUNCH = ()
mix = [(f"A{i}", AUTH) for i in range(1, 4)] + [(f"N{i}", {}) for i in range(1, 7)]
for n in (6, 2):
    done, where = lanes(mix, n)
    auth_spans = sorted((t0, t1) for th, nm, t0, t1 in spans if nm.startswith("A"))
    check(f"{n}개 창: 인증 사이트는 모두 첫 창(수집1)에서 겹치지 않고 차례로, 인증 없는 사이트는 다른 창에서도",
          done == len(mix) and {where[f"A{i}"] for i in range(1, 4)} == {"수집1"}
          and all(b[0] >= a[1] for a, b in zip(auth_spans, auth_spans[1:]))
          and {where[f"N{i}"] for i in range(1, 7)} - {"수집1"}, f"{done} {where}")
done, where = lanes([(f"N{i}", {}) for i in range(1, 5)], 3)
check("인증 사이트가 없으면 모든 창이 인증 없는 사이트를 (예전처럼)", done == 4 and len(set(where.values())) == 3, str(where))
done, where = lanes([(f"A{i}", AUTH) for i in range(1, 4)], 4)
check("인증 사이트만 있으면 창 하나만 띄운다 (할 일 없는 창을 띄우지 않는다)", done == 3 and launched == ["수집1"], f"{launched} {where}")
done, where = lanes(mix[:2] + mix[3:5], 6)
check("인증 없는 사이트가 적으면 그만큼만 띄운다 (인증 1 + 2)", done == 4 and len(launched) == 3, str(launched))
preset_otp = [{"no": 7, "record": {"steps": [{"kind": "fill"}, {"kind": "otp"}, {"kind": "click"}]}},
              {"no": 8, "record": {"steps": [{"kind": "fill"}, {"kind": "click"}]}}, {"no": 9, "record": None}]
check("인증 사이트 가르기: 문자 인증 Action, 인증번호 단계가 있는 프리셋만",
      web_runner.needs_auth(AUTH) and web_runner.needs_auth({"Action": "replay", "Preset": 7}, preset_otp)
      and not web_runner.needs_auth({"Action": "replay", "Preset": 8}, preset_otp)
      and not web_runner.needs_auth({"Action": "replay", "Preset": 9}, preset_otp)
      and not web_runner.needs_auth({"Action": ["login", "mail"]}, preset_otp))
FAIL_LAUNCH = ("수집1",)
done, where = lanes(mix, 3)
check("첫 창이 브라우저를 못 띄우면 남은 인증 사이트는 다른 창이 가져간다 (빠뜨리지 않는다)",
      done == len(mix) and "수집1" not in where.values(), f"{done} {where}")
FAIL_LAUNCH = ()
web_runner.sync_playwright, web_runner.web_replay.edge, web_runner.run_site = _saved

print("=== 3-2. 예전 방식 문자 인증 사이트 (Action login·sms_2fa) 둘을 함께")
events = []


class FakePage:
    def set_default_timeout(self, ms):
        pass

    def on(self, ev, fn):
        pass


class FakeContext:
    def new_page(self):
        return FakePage()

    def close(self):
        pass


class FakeBrowser2:
    def new_context(self, **_):
        return FakeContext()


def fake_action(kind):
    def fn(page, name, site):
        events.append((name, kind))
        time.sleep(0.1)
    return fn


_actions = dict(web_runner.ACTIONS)
web_runner.ACTIONS.update(login=fake_action("login"), sms_2fa=fake_action("sms_2fa"), mail=fake_action("mail"))
names = ("시험A", "시험B")
status.start("prepare")
status.set_steps([(web_runner.step_key(n, a), a) for n in names for a in ("login", "sms_2fa", "mail")])
legacy, gates = {"Action": ["login", "sms_2fa", "mail"], "Phone": "p"}, web_runner.AuthGates()
workers = [threading.Thread(target=web_runner.run_site, args=(FakeBrowser2(), n, legacy, False, False, gates)) for n in names]
for w in workers:
    w.start()
    time.sleep(0.02)
for w in workers:
    w.join()
web_runner.ACTIONS.clear()
web_runner.ACTIONS.update(_actions)
auth = [e for e in events if e[1] != "mail"]
check("같은 휴대폰: 한 사이트의 로그인·인증 사이에 다른 사이트의 로그인이 끼지 않는다",
      auth[0][0] == auth[1][0] and auth[2][0] == auth[3][0], str(events))
st = {s["key"]: s["state"] for s in status._state["steps"]}
check("앞 Action 단계는 다음 Action 을 시작할 때 완료로 닫는다 ('진행 중' 으로 남지 않는다)", set(st.values()) == {"done"}, str(st))
status.finish("success")
check("동시 개수: 관리 화면 값이 없으면 1, 숫자 아님은 1, 상한", web_runner.parallel_count() == 1 and web_runner.parallel_count("x") == 1
      and web_runner.parallel_count(4) == 4 and web_runner.parallel_count(99) == status.PARALLEL_MAX)
import rpa_dashboard as dash  # noqa: E402
dash.set_policy(2, [], False, None, 6)
check("허용(6)했어도 업체가 고르기 전엔 하나씩", web_runner.parallel_count() == 1)
dash.set_parallel(4)
check("업체가 고른 수(4)로, --parallel 이 먼저", web_runner.parallel_count() == 4 and web_runner.parallel_count(2) == 2)
dash.set_parallel(8)
check("고른 수가 허용보다 크면 허용(6)까지", web_runner.parallel_count() == 6)
dash.set_policy(2, [], False, None, None)
check("허용을 거두면 고른 값과 상관없이 하나씩", web_runner.parallel_count() == 1)
dash.set_parallel(1)
VP = (1306, 920)      # 기록 때 페이지 크기 (프리셋 3~6)
bad = []
for size in ((1366, 728), (1920, 1032), (3840, 2112)):
    for n in (2, 4, 6, 9, 16):
        c, r, s = web_runner.best_grid(n, size, VP)
        if c * r < n or (VP[0] + 20) * s > size[0] / c + 0.01 or (VP[1] + 90) * s > size[1] / r + 0.01:
            bad.append((size, n, c, r, s))
check("개수는 줄이지 않고 화면에 맞춘다: 노트북·FHD·4K 에서 2~16개 모두 칸 안에 들어가는 배율", not bad, str(bad))
check("작은 화면(1366x768)에서 4개도 2x2 로 모두 띄운다 (창을 더 작게)", web_runner.best_grid(4, (1366, 728), VP)[:2] == (2, 2))
check("바둑판은 창이 가장 크게: FHD 2개는 좌우, 3개는 2x2 (3x1 보다 크다)",
      web_runner.best_grid(2, (1920, 1032), VP)[:2] == (2, 1) and web_runner.best_grid(3, (1920, 1032), VP)[:2] == (2, 2))
scale, spots = web_runner.tile_layout(4, (1306, 920))
xs, ys = sorted({x for x, _ in spots}), sorted({y for _, y in spots})
check("창 4개는 2x2 칸에 (배율 1 미만, 칸 사이가 창보다 넓다)", 0 < scale < 1 and len(xs) == 2 and len(ys) == 2
      and (xs[1] - xs[0]) >= 1306 + 19 and (ys[1] - ys[0]) >= 920 + 89, f"{scale} {spots}")

print("=== 3-3. 함께 실행 - ERPia 쪽을 같이 띄워 받은 엑셀을 받는 대로 (사용자 2026-10-19)")
since = time.time()
status.start("routine")
check("루틴이 놓아주기 전에는 Edge 창을 띄우지 않는다", status.prepare_go(since) == (False, None))
status.release_prepare((0, 0, 1920, 1032))
check("놓아주면 ERPia 창 자리와 함께", status.prepare_go(since) == (True, [0, 0, 1920, 1032]), str(status.prepare_go(since)))
check("띄우기 전에 시작한 루틴(앞 실행)의 표시는 보지 않는다", status.prepare_go(time.time() + 60) == (False, None))
status.finish("success")
check("루틴이 끝났으면 기다리지 않는다", status.prepare_go(since)[0] is True)

spawned = []


class FakeProc:
    def __init__(self, cmd, env=None):
        spawned.append((cmd, env))
        self.rc = None

    def poll(self):
        return self.rc

    def wait(self):
        return 3


_saved_tog = web_runner.subprocess.Popen, status.wellife_policy, web_runner.download_dir, status.prepare_go
web_runner.subprocess.Popen = FakeProc
os.environ.pop(status.ALL_RUN_ENV, None)
status.wellife_policy = lambda: True
check("전체 실행(Run_All.bat)이 아니면 함께 띄우지 않는다", web_runner.start_routine_together() is None and not spawned)
os.environ[status.ALL_RUN_ENV] = "1"
status.wellife_policy = lambda: False
check("웰라이프 업체가 아니면 함께 띄우지 않는다 (예전 차례)", web_runner.start_routine_together() is None and not spawned)
status.wellife_policy = lambda: True
together = web_runner.start_routine_together()
cmd, env = spawned[0] if spawned else (None, {})
check("웰라이프 전체 실행이면 루틴을 함께 띄운다 - 함께 표시는 주고 전체 실행 표시는 빼서",
      together is not None and env.get(status.TOGETHER_ENV) == "1" and status.ALL_RUN_ENV not in env
      and cmd[-1].endswith("run_routine.py"), str(cmd))
goes = [(False, None), (False, None), (True, [1, 2, 3, 4])]
status.prepare_go = lambda since: goes.pop(0)
check("루틴이 놓아줄 때까지 기다렸다가 ERPia 창 자리를", web_runner.wait_routine_go() == [1, 2, 3, 4])
status.prepare_go = lambda since: (False, None)
web_runner._together[0].rc = 0
check("루틴이 먼저 끝나면 더 기다리지 않는다", web_runner.wait_routine_go() is None)
check("끝 코드는 100 + 루틴 코드 (Run_All.bat 이 루틴을 다시 띄우지 않게)", web_runner.finish_together(0) == 103)
check("Edge 인자: 함께 실행이면 맨 위 ERPia 에 가려져도 느려지지 않게",
      "--disable-backgrounding-occluded-windows" in web_runner.edge_args()["args"])

dl = tempfile.mkdtemp(prefix="rpa_dl_")
web_runner.download_dir = lambda: dl
mid = []


def fake_download(page, name, site):
    with open(os.path.join(web_runner.site_dest(), f"(107){name}.xlsx"), "w") as f:
        f.write("x")
    mid.append((web_runner.site_dest(), [f for f in os.listdir(dl) if f.endswith(".xlsx")]))


with open(os.path.join(dl, "(107)S1.xlsx"), "w") as f:
    f.write("old")
web_runner.ACTIONS["dl"] = fake_download
status.start("prepare")
web_runner.run_site(FakeBrowser2(), "S1", {"Action": ["dl"]}, False, False, None)
del web_runner.ACTIONS["dl"]
stage = os.path.join(dl, web_runner.STAGE_DIR_NAME)
check("받는 동안은 사이트마다 받는중 폴더에 - 업로드 폴더에는 아직 안 보인다",
      mid and mid[0][0].startswith(stage) and mid[0][1] == ["(107)S1.xlsx"], str(mid))
check("사이트를 다 돌면 업로드 폴더로 옮긴다 (같은 이름은 (1)), 받는중 폴더는 지운다",
      sorted(f for f in os.listdir(dl) if f.endswith(".xlsx")) == ["(107)S1 (1).xlsx", "(107)S1.xlsx"]
      and not os.listdir(stage), str(os.listdir(dl)))
os.makedirs(os.path.join(stage, "site_left"))
with open(os.path.join(stage, "site_left", "(108)남은것.xlsx"), "w") as f:
    f.write("x")
web_runner.recover_stage()
check("앞 실행이 사이트 도중에 꺼져 받는중에 남은 파일은 다음 실행 처음에 업로드 폴더로",
      "(108)남은것.xlsx" in os.listdir(dl) and not os.listdir(stage))
status.finish("success")

_saved_mon = web_runner.monitor_work_areas
web_runner.monitor_work_areas = lambda: [(-1920, 0, 0, 1040), (0, 0, 1920, 1040)]
check("모니터가 둘이면 Edge 창은 ERPia 가 없는 모니터에",
      web_runner.work_area((0, 0, 1920, 1032)) == (-1920, 0, 1920, 1040)
      and web_runner.work_area((-1920, 0, 0, 1032)) == (0, 0, 1920, 1040))
web_runner.monitor_work_areas = lambda: [(0, 0, 1920, 1040)]
check("모니터가 하나면 주 화면 그대로 (ERPia 를 맨 위로 둔다)", web_runner.work_area((0, 0, 1920, 1032)) == web_runner.work_area())
web_runner.monitor_work_areas = _saved_mon
web_runner.subprocess.Popen, status.wellife_policy, web_runner.download_dir, status.prepare_go = _saved_tog
web_runner._together = None
os.environ.pop(status.ALL_RUN_ENV, None)

print("=== 4. 진짜 Edge - 가짜 쇼핑몰 3곳을 동시에 (인증 사이트 둘은 차례로)")
import fake_mall  # noqa: E402
import test_web_replay as twr  # noqa: E402  (기록하는 사람 흉내)
from playwright.sync_api import sync_playwright  # noqa: E402

DAY = twr.DAY
servers, records = [], []
try:
    for k in range(3):
        srv, url, _ = fake_mall.start(DAY, False)
        srv.mall = mall = fake_mall.Mall(DAY, False)
        r = rec.record(url + "/login", os.path.join(_tmp, f"rec{k}.json"), headless=True, human=twr.human(mall, False),
                       record_date=DAY)
        servers.append(srv)
        records.append(r)
        print(f"    기록 {k + 1}: {len(r['steps'])}단계")
    login_end = 3            # 아이디·비밀번호·로그인 - 인증번호 단계가 있다고 치고 여기까지를 인증 구간으로
    gate = threading.Lock()
    events = []              # (시각, 사이트, 일)
    results = {}
    elock = threading.Lock()

    def note(site, what):
        with elock:
            events.append((time.time(), site, what))

    def run(k, gated):
        day = DAY + datetime.timedelta(days=1)
        servers[k].mall = fake_mall.Mall(day, False)
        name = f"사이트{k + 1}"

        def log(m):
            if "차례를 넘깁니다" in m:
                note(name, "release")
            if "차례를 기다립니다" in m:
                note(name, "wait")
        with sync_playwright() as p:
            browser = rec.edge(p.chromium.launch, headless=True)
            ctx = browser.new_context(accept_downloads=True)
            rp = rec.Replayer(ctx, records[k], {"ID": fake_mall.USER, "PW": fake_mall.PASSWORD},
                              os.path.join(_tmp, f"out{k}"), f"0{k}{k}", today=day, log=log)
            if gated:
                rp.gate = (gate, 1, login_end)
            orig = rp._hold

            def hold(i):
                if i == 1:
                    note(name, "ask")
                orig(i)
                if i == 1:
                    note(name, "step1")
            rp._hold = hold
            ok = rp.run()
            note(name, "end")
            results[name] = (ok, [os.path.basename(x) for x in rp.saved], rp.elapsed)
            browser.close()

    t0 = time.time()
    threads = [threading.Thread(target=run, args=(k, k != 1)) for k in range(3)]   # 1·3 인증, 2 인증 없음
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    total = time.time() - t0
    for n, (ok, saved, el) in sorted(results.items()):
        print(f"    {n}: {'성공' if ok else '실패'} {el:.1f}초 {saved}")
    check("셋 다 끝까지 재생하고 파일을 받았다", len(results) == 3 and all(ok and saved for ok, saved, _ in results.values()),
          str(results))
    ev = {(s, w): t for t, s, w in events}
    a = (ev.get(("사이트1", "step1")), ev.get(("사이트1", "release")))
    c = (ev.get(("사이트3", "step1")), ev.get(("사이트3", "release")))
    first, second = sorted([a, c])
    check("인증 사이트 둘의 인증 구간이 겹치지 않는다 (뒤 사이트는 앞 사이트가 넘긴 뒤 로그인)",
          None not in a + c and second[0] >= first[1], f"{a} {c}")
    check("뒤 인증 사이트는 '차례를 기다립니다' 를 남겼다",
          ("사이트1", "wait") in ev or ("사이트3", "wait") in ev, str(sorted(ev)))
    b1 = ev.get(("사이트2", "step1"))
    check("인증 없는 사이트는 기다리지 않고 바로 로그인한다 (앞 인증 사이트가 차례를 잡고 있는 동안)",
          b1 is not None and b1 < first[1], f"{b1} {first}")
    longest = max(el for _, _, el in results.values())
    check(f"동시에 돌아 전체({total:.1f}초)가 셋을 더한 것({sum(el for _, _, el in results.values()):.1f}초)보다 짧다",
          total < sum(el for _, _, el in results.values()), f"가장 긴 사이트 {longest:.1f}초")
finally:
    for srv in servers:
        srv.shutdown()

print()
print("실패:", fails or "없음")
sys.exit(1 if fails else 0)
