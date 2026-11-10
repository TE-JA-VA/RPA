# -*- coding: utf-8 -*-
"""사이트 엑셀 업로드 시험 (설계 docs/superpowers/specs/2026-11-06-excel-upload-design.md).
스위치(st.EXCEL_UPLOAD_ON)가 꺼져 있으면 모두 다운로드 전용인지, 켜면 기록 → 재생 → 파일 정리 → 예약이 맞게 도는지 본다.
창은 뜨지 않는다 (Edge 는 숨김).    .venv\\Scripts\\python.exe tests\\test_excel_upload.py
"""
import datetime
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "firebase" / "agent")]
OUT = tempfile.mkdtemp(prefix="rpa_upload_")
os.environ.update(RPA_USER_CONFIG=os.path.join(OUT, "u.json"), RPA_PROGRAMDATA=OUT, RPA_STATUS_DIR=OUT)
sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright  # noqa: E402
import agent  # noqa: E402
import rpa_dashboard as dash  # noqa: E402
import rpa_observer as obs  # noqa: E402
import rpa_status as st  # noqa: E402
import web_replay as rec  # noqa: E402
import web_runner as run  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  {detail!r}"))
    if not ok:
        fails.append(name)


# --- 스위치가 꺼져 있으면 모두 다운로드 전용 ---
check("출고 기본값은 켜짐 (운송장번호 전송 메뉴를 고쳤다 - PR #32, 2026-11-09)", st.EXCEL_UPLOAD_ON is True)
check("파일 넣기 단계가 든 기록은 버전 3 - 옛 ACTOR 는 거절한다 (설계 9절)",
      rec.record_version([{"kind": "click"}, {"kind": "file"}]) == st.UPLOAD_RECORD_VERSION == 3 and 3 in st.RECORD_VERSIONS
      and rec.record_version([{"kind": "click"}]) == 1)
# 2026-11-09 pc_b: 같은 사이트코드의 다운로드·업로드 프리셋을 저장하면 read_presets 가 파일을 '깨짐' 으로 읽어 프리셋이 모두 사라져 보였다
_rec = lambda up: dict({"version": 3, "steps": [{"kind": "file"}] if up else [{"kind": "click"}]}, **({"upload": True} if up else {}))
st.write_presets([{"name": "가", "code": "012", "record": _rec(False)}, {"name": "가 업로드", "code": "012", "record": _rec(True)}])
check("같은 코드의 다운로드·업로드 프리셋 파일을 읽는다", [p["code"] for p in st.read_presets()] == ["012", "012"])
st.write_presets([{"name": "가", "code": "012", "record": _rec(True)}, {"name": "나", "code": "012", "record": _rec(True)}])
try:
    st.read_presets(); check("같은 코드의 업로드 프리셋 둘은 여전히 깨짐", False)
except ValueError:
    check("같은 코드의 업로드 프리셋 둘은 여전히 깨짐 (다운로드 둘과 같게)", True)
import preset_transfer as _pt  # noqa: E402
_ps = [{"no": 1, "code": "012", "record": _rec(False)}, {"no": 2, "code": "", "record": None}]
check("넣어 주기: 다운로드 프리셋과 같은 코드의 업로드 프리셋은 겹침이 아니다",
      _pt._code_clash(_ps, 2, "012", True) is None and _pt._code_clash(_ps, 2, "012", False) is not None)
st.write_presets([{"name": "프리셋 1", "code": "", "record": None}, {"name": "프리셋 2", "code": "", "record": None}])
st.EXCEL_UPLOAD_ON = False     # 이하 끈 경우 (스위치 하나로 모두 다운로드 전용으로 돌아가는지)
check("꺼져 있으면 upload 표시가 있어도 다운로드", st.is_upload({"upload": True}) is False)
check("꺼져 있으면 옵저버도 다운로드", obs.is_up(dict(obs.new_preset(1), upload=True)) is False)
sites = [("a", {"Preset": 1, "Action": ["replay"]})]
check("꺼져 있으면 보통 실행은 그대로", run.upload_choice(sites, False) == sites)
check("꺼져 있으면 --upload 는 아무것도 안 돈다", run.upload_choice(sites, True) == [])
sch = dash.Scheduler()
launched = []
REAL_LAUNCH, REAL_READ_JSON = dash.launch, st.read_json
dash.launch = lambda target, by, env=None: launched.append(target)
sch.tick_upload(datetime.datetime(2026, 11, 6, 12, 0, 0))
check("꺼져 있으면 예약이 업로드를 안 띄운다", launched == [], launched)

# 이하는 켜고 본다
st.EXCEL_UPLOAD_ON = True
check("켜면 upload 표시를 본다", st.is_upload({"upload": True}) and not st.is_upload({"steps": []}))

# --- 저장 전 검사 ---
rec_up = {"steps": [{"kind": "file"}], "upload": True}
rec_down = {"steps": [{"kind": "click"}]}
base = {"id": "a", "pw": "b", "has_pw": True}
down = dict(base, no=1, name="가", code="012", record=rec_down)
up = dict(base, no=2, name="나", code="012", record=rec_up, upload=True)
check("같은 사이트의 다운로드·업로드는 코드가 같아도 된다", obs.validate_presets([down, up]) is None)
check("같은 방향 두 개는 막는다", "사용하고 있습니다" in (obs.validate_presets([up, dict(up, no=3)]) or (0, ""))[1])
no_file = dict(up, record={"steps": [{"kind": "click"}], "upload": True})
check("파일 넣기 단계가 없으면 막는다", "파일을 넣는 단계" in (obs.validate_presets([no_file]) or (0, ""))[1])

# --- 폴더에서 파일 고르기·옮기기 ---
folder = os.path.join(OUT, "up")
os.makedirs(folder)
st.upload_dir = lambda: folder


def put(name, age=0):
    p = os.path.join(folder, name)
    Path(p).write_bytes(b"x")
    os.utime(p, (time.time() - age, time.time() - age))
    return p


old, new = put("(012)옛것.xlsx", 100), put("(012)새것.xlsx")
put("(034)다른곳.xls")
put("메모.txt")
check("규칙에 맞는 파일만 사이트코드별로", sorted(st.upload_files()) == ["012", "034"], st.upload_files())
check("가장 새 파일을 고른다", run.upload_file_of("012") == new)
check("옛 파일은 오류 폴더로", os.path.isfile(os.path.join(folder, "오류", "(012)옛것.xlsx")) and not os.path.exists(old))
check("없는 사이트코드", run.upload_file_of("999") is None)
run.settle_upload(new, False, False)
check("파일을 넣기 전에 멈췄으면 그대로 둔다 (다음 회차에)", os.path.isfile(new))
run.settle_upload(new, True, True)
done = os.path.join(folder, "완료", time.strftime("%Y%m%d"), "(012)새것.xlsx")
check("시도하고 끝까지 갔으면 완료 폴더로", os.path.isfile(done) and not os.path.exists(new))
bad = put("(034)다른곳.xls")
run.settle_upload(bad, True, False)
check("넣은 뒤 멈췄으면 오류 폴더로 (다시 올리지 않는다)", os.path.isfile(os.path.join(folder, "오류", "(034)다른곳.xls")))

# --- 보통 실행과 --upload 나누기 ---
presets = [{"no": 1, "code": "012", "record": rec_down}, {"no": 2, "code": "012", "record": rec_up}, {"no": 3, "code": "034", "record": rec_up}]
st.read_presets = lambda: presets
chosen = [(f"P{p['no']}", {"Preset": p["no"]}) for p in presets]
check("보통 실행은 업로드 프리셋을 뺀다", [c[0] for c in run.upload_choice(chosen, False)] == ["P1"])
check("업로드 실행은 올릴 파일이 있는 것만", [c[0] for c in run.upload_choice(chosen, True)] == [], st.upload_files())
put("(034)올림.xlsx")
check("파일이 있으면 그 프리셋", [c[0] for c in run.upload_choice(chosen, True)] == ["P3"])

# --- 예약: PROCESS 끝 + 1분, 끝날 때마다 한 번 ---
end = datetime.datetime(2026, 11, 6, 10, 0, 0)
dash.st.read_json = lambda path, **kw: ({"state": "success", "finished_at": end.isoformat()} if path == st.status_path("routine")
                                         else REAL_READ_JSON(path, **kw))
sch.busy = lambda: None
sch.tick_upload(end + datetime.timedelta(seconds=5))
check("10초 전에는 안 띄운다", launched == [], launched)
sch.busy = lambda: "실행 중"
sch.tick_upload(end + datetime.timedelta(seconds=90))
check("다른 것이 돌면 기다린다", launched == [], launched)
sch.busy = lambda: None
sch.tick_upload(end + datetime.timedelta(seconds=90))
check("10초 뒤 띄운다", launched == ["upload"], launched)
sch.tick_upload(end + datetime.timedelta(seconds=120))
check("같은 PROCESS 몫은 다시 안 띄운다 (계정 잠금 방지)", launched == ["upload"], launched)
end += datetime.timedelta(hours=1)
sch.tick_upload(end + datetime.timedelta(seconds=90))
check("다음 PROCESS 가 끝나면 다시", launched == ["upload", "upload"], launched)
for f in list(st.upload_files().values()):
    os.remove(f[0])
end += datetime.timedelta(hours=1)
sch.tick_upload(end + datetime.timedelta(seconds=90))
check("올릴 파일이 없으면 안 띄운다", len(launched) == 2, launched)
put("(077)프리셋없음.xlsx")
end += datetime.timedelta(hours=1)
sch.tick_upload(end + datetime.timedelta(seconds=90))
check("같은 코드의 업로드 프리셋이 없는 파일만 있으면 안 띄운다 (ACTOR 가 바로 끝나 '중단' 기록만 남았다, 11-09 실측)", len(launched) == 2, launched)
put("(034)올림.xlsx")
check("올릴 수 있는 파일은 업로드 프리셋이 있는 코드만", sorted(st.upload_pending()) == ["034"], st.upload_pending())
end += datetime.timedelta(hours=1)
sch.tick_upload(end + datetime.timedelta(seconds=90))
check("프리셋 있는 파일이 생기면 띄운다", len(launched) == 3, launched)

# #38: 시키지 않은 업로드 - 재시작·오래된 몫·옵저버를 닫자마자·예약 몫 삼키기
end += datetime.timedelta(hours=1)
check("#38: 에이전트를 켤 때 이미 끝난 PROCESS 는 처리한 것으로 본다", dash.Scheduler().upload_for == end)
fresh = dash.Scheduler()
fresh.busy = lambda: None
fresh.upload_for = None
fresh.tick_upload(end + datetime.timedelta(seconds=dash.UPLOAD_MAX_AGE_SEC + 5))
check("#38: 끝난 지 10분이 지난 PROCESS 몫은 띄우지 않는다", len(launched) == 3 and fresh.upload_for == end, launched)
# 옵저버가 떠 있으면 닫아 달라고 하고(30초 메시지 창), 닫히면 다음 틱에 바로 (사용자 2026-11-10)
end += datetime.timedelta(hours=1)
sch.busy = lambda: dash.OBSERVER_WAIT
sch.tick_upload(end + datetime.timedelta(seconds=15))
req = st.observer_close_request() or {}
check("옵저버가 떠 있으면 띄우지 않고 닫아 달라고 한다 (사유: ACTOR 실행 시 옵저버 사용 불가)", len(launched) == 3
      and req.get("key") == end.isoformat() and req.get("why") == st.OBSERVER_CLOSE_WHY and req.get("answer") is None, (launched, req))
sch.tick_upload(end + datetime.timedelta(seconds=20))
check("답을 기다리는 동안 다시 부탁하지 않는다 (같은 요청 그대로)", (st.observer_close_request() or {}).get("at") == req.get("at"))
sch.busy = lambda: None                # 옵저버가 닫혔다
sch.tick_upload(end + datetime.timedelta(seconds=45))
check("옵저버가 닫히면 바로 띄우고 요청을 지운다", len(launched) == 4 and st.observer_close_request() is None, launched)
end += datetime.timedelta(hours=1)
sch.busy = lambda: dash.OBSERVER_WAIT
sch.tick_upload(end + datetime.timedelta(seconds=15))
st.answer_observer_close(st.observer_close_request(), "cancel")
sch.tick_upload(end + datetime.timedelta(seconds=20))
sch.busy = lambda: None
sch.tick_upload(end + datetime.timedelta(seconds=25))
check("[취소] 면 이 몫은 띄우지 않는다 (옵저버를 닫아도)", len(launched) == 4 and sch.upload_for == end and st.observer_close_request() is None, launched)
end += datetime.timedelta(hours=1)
sch.busy = lambda: dash.OBSERVER_WAIT
sch.tick_upload(end + datetime.timedelta(seconds=15))
sch.tick_upload(end + datetime.timedelta(seconds=15 + dash.OBSERVER_CLOSE_GIVE_UP_SEC + 5))
check("답이 없으면 (옛 버전 옵저버) 90초 뒤 이 몫은 건너뛴다", len(launched) == 4 and sch.upload_for == end, launched)
for f in [p for ps in st.upload_files().values() for p in ps]:
    os.remove(f)
end += datetime.timedelta(hours=1)
sch.tick_upload(end + datetime.timedelta(seconds=15))
check("올릴 것이 없으면 옵저버를 닫아 달라고 하지 않는다", st.observer_close_request() is None and sch.upload_for == end)
sch.busy = lambda: None
put("(034)올림.xlsx")
end += datetime.timedelta(hours=1)
sch.tick_upload(end + datetime.timedelta(seconds=15))
check("#38: 다음 PROCESS 뒤에는 다시 띄운다 (10초 뒤)", len(launched) == 5, launched)
for f in [p for ps in st.upload_files().values() for p in ps]:
    os.remove(f)

# #38: 업로드를 띄워도 예약 시각을 넘기지 않는다 (예약 몫을 삼키지 않게)
due = "2026-11-06T18:38:00"
st.read_json = REAL_READ_JSON         # 위 예약 시험이 PROCESS 상태로 바꿔 둔 것 - 설정 파일은 진짜로 읽는다
cfg = st.read_settings()
cfg["schedule"].update(enabled=True, slots=[{"at": "18:38"}], next_run_at=due)
st.write_settings(cfg)
exe = os.path.join(OUT, "fake.exe")
Path(exe).write_bytes(b"")
saved = (dash.DRY_RUN, dash.target_path, dash.any_rpa_running, dash.launch_state, dash.TOKEN_GATE, dash.st.observer_open, dash.st.install_block_reason)
dash.DRY_RUN, dash.target_path, dash.any_rpa_running, dash.launch_state, dash.TOKEN_GATE = True, lambda t: exe, lambda: [], lambda: None, None
dash.st.observer_open, dash.st.install_block_reason = lambda: False, lambda: None
REAL_LAUNCH("upload", "auto")
s = st.read_settings()["schedule"]
check("#38: 업로드를 띄워도 다음 예약 시각은 그대로", s["next_run_at"] == due and s["last_launch_target"] == "upload", s.get("next_run_at"))
dash._active.clear()
put("(034)올림.xlsx")
before = len(launched)
due_sch = dash.Scheduler()
due_sch.busy, due_sch.upload_for = (lambda: None), None
end = datetime.datetime(2026, 11, 6, 18, 37, 50)
st.read_json = lambda path, **kw: ({"state": "success", "finished_at": end.isoformat()} if path == st.status_path("routine") else REAL_READ_JSON(path, **kw))
due_sch.tick_upload(datetime.datetime(2026, 11, 6, 18, 38, 5))
check("#41: 예약이 띄울 차례(next_run_at 지남)면 업로드를 띄우지 않는다 - 예약이 먼저", len(launched) == before and due_sch.upload_for is None, launched)
st.read_json = REAL_READ_JSON

# 옵저버: 닫기 요청은 1초마다 보고, 같은 요청은 메시지 창 한 번 - 켜기 전 요청·[취소] 로 답한 요청은 보지 않는다 (사용자 2026-11-10)
from types import SimpleNamespace  # noqa: E402
shown = []
ob = SimpleNamespace(closing=False, started_at="2026-11-06T09:00:00", close_seen=None, close_box=shown.append,
                     root=SimpleNamespace(after=lambda ms, fn: None), _watch_close=None)
st.ask_observer_close("2026-11-06T09:59:00", datetime.datetime(2026, 11, 6, 10, 0, 0))
obs.App._watch_close(ob)
obs.App._watch_close(ob)
check("옵저버: 새 닫기 요청이면 메시지 창 한 번 (같은 요청은 다시 안 띄운다)", len(shown) == 1 and shown[0]["why"] == st.OBSERVER_CLOSE_WHY, shown)
late = SimpleNamespace(ob.__dict__, started_at="2026-11-06T10:00:01", close_seen=None)
obs.App._watch_close(late)
check("옵저버: 켜기 전에 남은 요청은 보지 않는다", len(shown) == 1)
st.answer_observer_close(st.observer_close_request(), "cancel")
obs.App._watch_close(SimpleNamespace(ob.__dict__, close_seen=None))
check("옵저버: [취소] 로 답한 요청은 다시 띄우지 않는다", len(shown) == 1)
st.clear_observer_close()
(dash.DRY_RUN, dash.target_path, dash.any_rpa_running, dash.launch_state, dash.TOKEN_GATE, dash.st.observer_open, dash.st.install_block_reason) = saved

# --- 토큰: 운송장번호 전송에 포함 ---
steps = [{"key": "PRESET3:replay", "state": "done"}]
check("업로드 실행은 토큰을 세지 않는다", agent.usage({"program": "prepare", "title": st.UPLOAD_TITLE, "steps": steps}) == {})
check("보통 수집은 그대로 센다", agent.usage({"program": "prepare", "steps": steps}) == {"sites": 1})
check("이력에 제목이 남는다 (토큰 판단에 쓴다)", st.history_record({"title": st.UPLOAD_TITLE, "program": "prepare"}).get("title") == st.UPLOAD_TITLE)

# --- 기록 → 재생 (Edge 숨김) ---
page_file = os.path.join(OUT, "shop.html")
Path(page_file).write_text("""<!doctype html><meta charset=utf-8><title>시작</title>
<button id=pick onclick="document.getElementById('f').click()">파일 선택</button>
<input type=file id=f style="display:none" onchange="document.title = this.files[0].name">
<button id=send onclick="document.getElementById('r').textContent = '올림'">업로드</button><p id=r></p>""", encoding="utf-8")
url = Path(page_file).as_uri()
sample = put("(012)운송장.xlsx")
with sync_playwright() as p:
    browser = rec.edge(p.chromium.launch, headless=True)
    ctx = browser.new_context()
    recorder = rec.Recorder(ctx)
    page = ctx.new_page()
    page.goto(url)
    page.wait_for_timeout(300)
    page.locator("#f").set_input_files(sample)
    page.wait_for_timeout(300)
    raw = [s for s in recorder.steps if s["kind"] == "file"]
    check("파일 칸에 넣은 것을 기록한다 (이름만)", len(raw) == 1 and raw[0].get("value") == "(012)운송장.xlsx", recorder.steps)
    check("#39: 파일 칸을 '글자 넣기' 로 함께 적지 않는다", not [s for s in recorder.steps if s["kind"] == "fill"], recorder.steps)
    ctx.close()

    record = rec.finalize(list(raw), datetime.date(2026, 11, 6), url)
    check("다듬어도 파일 단계가 남는다", any(s["kind"] == "file" for s in record["steps"]), record["steps"])
    check("단계 설명", "엑셀 파일 넣기" in rec.describe(record["steps"][-1]) and "운송장" not in rec.describe(record["steps"][-1], hide_values=True))
    send = {"kind": "click", "page": 0, "frame": raw[0]["frame"], "url": raw[0]["url"], "gap": 0,
            "target": dict(raw[0]["target"], tag="button", id="send", name="", type="", text="업로드", label="업로드", css="#send")}
    pick = dict(send, target=dict(send["target"], id="pick", text="파일 선택", label="파일 선택", css="#pick"))
    record["steps"] = [pick] + record["steps"] + [send]
    record["start_url"] = url

    def replay(file):
        ctx = browser.new_context()
        rp = rec.Replayer(ctx, record, {"ID": "", "PW": ""}, OUT, "012", log=lambda m: None, step_timeout=2, step_tries=1, shot_dir=OUT)
        rp.upload_file = file
        rp.first_page = ctx.new_page()
        rp.first_page.goto(url)
        ok = rp.run()
        result = (ok, rp.upload_tried, rp.first_page.title(), rp.first_page.locator("#r").inner_text(), rp.results[-1])
        ctx.close()
        return result

    ok, tried, title, sent, _ = replay(sample)
    check("숨긴 파일 칸에 넣고 끝까지 간다", ok and tried and title == "(012)운송장.xlsx" and sent == "올림", (ok, tried, title, sent))
    ok, tried, title, sent, last = replay(None)
    check("미리보기는 파일을 안 올리고 그 단계에서 멈춘다", not ok and not tried and title == "시작" and sent == "" and "미리보기" in last[2], last)
    # #39: 고치기 전 기록기로 저장한 프리셋 - 파일 칸 'fill'(C:\fakepath\…) 이 'file' 앞에 있다. 다시 기록하지 않아도 끝까지 간다
    fi = next(i for i, s in enumerate(record["steps"]) if s["kind"] == "file")
    old = dict(record["steps"][fi], kind="fill", value="C:\\fakepath\\(012)운송장.xlsx")
    record["steps"].insert(fi, old)
    ok, tried, title, sent, _ = replay(sample)
    check("#39: 옛 기록의 파일 칸 '글자 넣기' 는 건너뛰고 끝까지 간다", ok and tried and sent == "올림", (ok, tried, title, sent))
    browser.close()

_wr = run
_site = {"Preset": 1, "note": "가짜몰"}
_wr.site_actions = lambda site: [st.REPLAY_ACTION]
check("#39: 업로드 실행의 대시보드 단계 이름은 '엑셀 올리기'", _wr.prepare_steps([("PRESET1", _site)], True)[0][1] == "가짜몰 엑셀 올리기"
      and _wr.prepare_steps([("PRESET1", _site)])[0][1] == "가짜몰 엑셀 받기")

shutil.rmtree(OUT, ignore_errors=True)
print("=== 실패", len(fails), fails)
sys.exit(1 if fails else 0)
