# -*- coding: utf-8 -*-
"""옵저버 화면 시험 - 진짜 창을 띄워 혼자 주소 치기 → 기록 → 단계 지우기·끄기 → 기록 끝 → 미리보기 → 저장을 하고 사진을 남긴다.
이어서 미리보기 손질(2026-10-02)을 본다: 브라우저를 못 띄움 → [■ 중단] → [Ⅱ 일시정지] 뒤 창 닫기.
3~4분 동안 마우스·키보드를 쓴다 (주소줄은 pywinauto 로 친다). 임시 설정으로만 돈다 (진짜 설정은 안 건드린다).
    .venv\\Scripts\\python.exe tests\\check_observer_ui.py [사진 폴더]
"""
import datetime
import glob
import json
import os
import sys
import tempfile
import time
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="rpa_observer_ui_")
os.environ["RPA_USER_CONFIG"] = os.path.join(TMP, "config", "RPA_UserConfig.json")
os.environ["RPA_PROGRAMDATA"] = os.path.join(TMP, "programdata")
os.environ["RPA_STATUS_DIR"] = os.path.join(TMP, "status")
os.makedirs(os.path.join(TMP, "config"))
os.makedirs(os.path.join(TMP, "programdata", "config"))
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.stdout.reconfigure(encoding="utf-8")

import rpa_status as st  # noqa: E402

st.write_user_config({"LogIn": {"AdminCode": "t", "ID": "erp", "PW": "erp-pw"}, "Sites": {}})
import tkinter as tk  # noqa: E402

import fake_mall  # noqa: E402
import rpa_observer as rr  # noqa: E402
import test_web_replay as twr  # noqa: E402
from PIL import ImageGrab  # noqa: E402
from pywinauto import Desktop  # noqa: E402

SHOTS = sys.argv[1] if len(sys.argv) > 1 else os.path.join(TMP, "사진")
os.makedirs(SHOTS, exist_ok=True)
PROFILES = os.path.join(tempfile.gettempdir(), rr.PROFILE_PREFIX + "*")
fails = []


def check(name, cond, detail=""):
    print(f"  [{'통과' if cond else '실패'}] {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


def first_saved_at():
    with open(st.presets_path(), encoding="utf-8") as f:
        return json.load(f)[0]["saved_at"]


def main():
    srv, base, mall = fake_mall.start(datetime.date.today(), True)
    host = base.replace("http://", "")
    scale = rr.dpi_scale()
    root = rr.new_root()
    app = rr.App(root, scale, rr.load_presets(), hint=f"시험용 가짜 쇼핑몰: <b>{host}/login</b>",
                 fake_creds=(fake_mall.USER, fake_mall.PASSWORD))
    result, hooks, told, asked = {}, {}, [], []
    app.tell = lambda title, text: told.append(text)
    app.ask = lambda title, text: asked.append(text) and False       # 저장 안 한 기록 - '아니요' (닫지 않는다)
    state = lambda b: str(b.cget("state"))     # noqa: E731
    label = lambda b: b.cget("text")           # noqa: E731

    def shot(name):
        app.root.update()
        l, t, r, b = rr.frame_rect(int(app.root.wm_frame(), 16))
        ImageGrab.grab(bbox=(l - app.browser_w, t, r, b), all_screens=True).save(os.path.join(SHOTS, name))

    def type_url_then_human(page):
        w = Desktop(backend="win32").window(title_re="AFTER MARKET 기록.*")
        w.wait("exists visible", timeout=15)
        hw = w.wrapper_object()
        hw.set_focus()
        time.sleep(0.4)
        hw.type_keys("^l", set_foreground=True)
        time.sleep(0.3)
        hw.type_keys(host + "/login{ENTER}", with_spaces=True, set_foreground=True)
        page.wait_for_url("**/login", timeout=15000)
        page.wait_for_timeout(500)
        twr.human(mall, True, noise=True)(page)

    def on_recording():
        app.root.after(1200, lambda: shot("0_안내.png"))
        app.worker.human = type_url_then_human
        app.root.after(1500, lambda: app.worker.cmd.put(("human",)))

    def on_human_done():
        app.root.after(800, step2)

    def step2():
        shot("1_기록.png")
        p = app.presets[0]
        final = app._final(p)
        ids, texts = [s["id"] for s in final["steps"]], [rr.rec.describe(s) for s in final["steps"]]
        result["first"] = texts[0]
        app.delete(ids[[i for i, t in enumerate(texts) if "떠 있을 때만" in t][0]])             # 공지 닫기 삭제
        app._var(p, ids[[i for i, t in enumerate(texts) if "'새로고침'" in t][0]]).set(False)    # 새로고침 끄기
        app.render()
        result["save_while_rec"] = state(app.save_btn)
        app.toggle_record()                                                                     # 기록 끝

    def on_stopped():
        app.root.after(100, after_rec)       # '기록 끝' 알림 다음 차례 - 화면은 알림을 다 받은 뒤 다시 그린다

    def after_rec():
        result["save_after_stop"] = state(app.save_btn)
        app.select(1)
        result["save_empty"] = state(app.save_btn)
        app.select(0)
        app.quit()                           # 저장 안 한 기록이 있다 → 묻는다, '아니요' 면 안 닫힌다
        result["asked"] = bool(asked) and bool(app.root.winfo_exists())
        mall.notice = True
        hooks["done"] = after_full
        app.root.after(600, start_full)

    def start_full():
        app.preview()
        app.root.after(3000, while_full)
        app.root.after(9000, lambda: shot("2_미리보기.png"))

    def while_full():
        result["btns"] = (label(app.prev_btn), label(app.save_btn), state(app.save_btn))
        app.quit()                           # 미리보기가 도는 중 X → 안내만 하고 안 닫힌다
        result["refused"] = bool(told) and app.previewing

    def after_full(ok):
        result["preview_ok"] = ok
        result["btns_after"] = (label(app.prev_btn), label(app.save_btn))
        app.root.after(500, finish)

    def finish():
        shot("3_끝.png")
        result["saved"] = app.save()
        result["date1"] = first_saved_at()
        app.root.after(1500, finish2)        # 저장 시각은 초 단위 - 다시 저장해도 ① 의 날짜가 그대로인지

    def finish2():
        app.save()
        result["date2"] = first_saved_at()
        for _ in range(12):
            if len(app.presets) < rr.MAX_PRESETS:
                app.add_preset()
        result["ten"] = (len(app.presets), "+" in [w.cget("text") for w in app.preset_bar.winfo_children()
                                                   if isinstance(w, tk.Button)])
        app.select(0)
        real = rr.launch

        def broken(p, **kw):                 # 미리보기 브라우저만 못 띄운다 (기록 창은 이미 닫혔다)
            if "slow_mo" in kw:
                raise RuntimeError("브라우저 실행 파일이 없습니다")
            return real(p, **kw)
        rr.launch = broken
        hooks["done"] = lambda ok: after_fail(ok, real)
        app.root.after(300, app.preview)

    def after_fail(ok, real):
        rr.launch = real
        result["fail"] = (ok, app.msg.cget("text"), app.previewing, label(app.prev_btn))
        before, n = set(glob.glob(PROFILES)), [0]

        def on_progress(sid, s, how):
            n[0] += s == "ok"
            if s == "ok" and n[0] == 2:
                result["t_stop"] = time.time()
                app.stop_preview()
        hooks["progress"] = on_progress
        hooks["done"] = lambda ok: after_stop(ok, before)
        app.root.after(300, app.preview)

    def after_stop(ok, before):
        hooks.pop("progress", None)
        result["stop"] = (ok, app.msg.cget("text"), round(time.time() - result.get("t_stop", 0), 1),
                          sorted(set(glob.glob(PROFILES)) - before),
                          (st.read_history(program="observer") or [{}])[0].get("state"))
        result["before_pause"], n = set(glob.glob(PROFILES)), [0]

        def on_progress(sid, s, how):
            n[0] += s == "ok"
            if s == "ok" and n[0] == 2:
                app.toggle_pause()
        hooks["progress"] = on_progress
        hooks["done"] = lambda ok: None
        app.on_paused = on_paused
        app.root.after(300, app.preview)

    def on_paused():
        shot("4_일시정지.png")
        result["paused_btns"] = (label(app.prev_btn), label(app.save_btn))
        result["t_close"] = time.time()
        app.quit()                           # 일시정지 중 X → 미리보기를 멈추고 정리한 뒤 닫힌다

    progress = app._progress

    def spy(sid, s, how):
        progress(sid, s, how)
        hooks.get("progress", lambda *a: None)(sid, s, how)
    app._progress = spy
    app.on_recording, app.on_human_done = on_recording, on_human_done
    app.on_stopped = on_stopped
    app.on_preview_done = lambda ok: hooks.pop("done", lambda ok: None)(ok)
    root.mainloop()
    closed_in = time.time() - result.get("t_close", time.time())
    srv.shutdown()

    check("켜자마자 빈 ① 에서 기록을 시작하고, 주소줄에 친 주소가 첫 단계", result.get("first", "").startswith("주소줄에 http"),
          str(result))
    check("기록 중에는 저장 단추가 잠긴다", result.get("save_while_rec") == "disabled", str(result.get("save_while_rec")))
    check("기록을 끝내고 켜 둔 단계가 있으면 저장할 수 있다, 단계가 없는 프리셋에서는 잠긴다",
          result.get("save_after_stop") == "normal" and result.get("save_empty") == "disabled",
          f"{result.get('save_after_stop')} {result.get('save_empty')}")
    check("저장 안 한 기록이 있으면 닫을 때 묻고, '아니요' 면 안 닫힌다", result.get("asked") is True, str(asked))
    check("미리보기 중 단추는 [Ⅱ 일시정지]·[■ 중단]", result.get("btns") == ("Ⅱ  일시정지", "■  중단", "normal"),
          str(result.get("btns")))
    check("미리보기가 도는 중에는 창을 닫지 않고 안내한다", result.get("refused") is True and "일시정지" in " ".join(told), str(told))
    check("미리보기가 끝까지 갔다, 단추는 [▶ 미리보기]·[저장] 으로 돌아온다", result.get("preview_ok") is True
          and result.get("btns_after") == ("▶  미리보기", "저장"), str(result))
    text = open(st.presets_path(), encoding="utf-8").read()
    saved = json.loads(text)
    check("프리셋 파일: 배열, ① 은 주소 치기로 시작·사이트코드 012·창 크기, ② 는 빈 것",
          isinstance(saved, list) and saved[0]["record"]["steps"][0]["kind"] == "goto" and saved[0]["code"] == "012"
          and saved[0]["record"].get("viewport") and saved[1]["record"] is None, text[:300])
    check("손대지 않고 다시 저장하면 ① 의 저장 날짜는 그대로", result.get("date1") and result.get("date1") == result.get("date2"),
          f"{result.get('date1')} → {result.get('date2')}")
    check("프리셋 파일에 아이디·비밀번호가 없다", fake_mall.USER not in text and fake_mall.PASSWORD not in text)
    site = st.read_user_config()["Sites"].get("PRESET1") or {}
    check("사용자 설정 PRESET1: 아이디, 잠긴 비밀번호, 꺼짐, replay", site.get("ID") == fake_mall.USER
          and st.unseal(site.get("PW")) == fake_mall.PASSWORD and site.get("Stts") == 9 and site.get("Action") == ["replay"],
          str(site))
    rows = st.read_history(program="observer")
    row = next((r for r in rows if r.get("state") == "success"), {})
    logs = "\n".join(row.get("log_tail") or [])
    check("대시보드 기록에 '옵저버' 미리보기 한 줄 (성공)", row.get("program_label") == "옵저버", str(rows[:1])[:300])
    check("그 로그에는 칸에 친 값·아이디·비밀번호가 없다", "주문 처리" not in logs and fake_mall.USER not in logs
          and fake_mall.PASSWORD not in logs, logs[-500:])
    pv = os.path.join(st.data_dir(), "옵저버", "미리보기")
    check("미리보기로 받은 파일은 기록 폴더 (ERPIA_AI_EXCEL 아님)", os.path.isdir(pv) and any(n.startswith("(012)") for n in os.listdir(pv)))
    check("프리셋은 10개까지 - 10개면 [+] 가 없다", result.get("ten") == (10, False), str(result.get("ten")))
    fail = result.get("fail") or (None, "", None, "")
    check("미리보기 브라우저를 못 띄우면 까닭을 보이고 단추가 돌아온다 (미리보기 상태로 멈추지 않는다)",
          fail[0] is False and "띄우지 못했습니다" in fail[1] and fail[2] is False and fail[3] == "▶  미리보기", str(fail))
    stop = result.get("stop") or (None, "", 99, ["?"], None)
    check("[■ 중단] 은 곧 멈추고 브라우저 프로필을 지운다, 기록은 '멈춤'", stop[0] is False and "중단" in stop[1] and stop[2] < 6
          and stop[3] == [] and stop[4] == "stopped", str(stop))
    check("일시정지 중 단추는 [▶ 계속]·[■ 중단]", result.get("paused_btns") == ("▶  계속", "■  중단"), str(result.get("paused_btns")))
    left = sorted(set(glob.glob(PROFILES)) - result.get("before_pause", set()))
    check("일시정지 중에 창을 닫으면 정리하고 곧 닫힌다 (프로필 안 남음, 기록은 '멈춤')", "t_close" in result and closed_in < 10
          and left == [] and not app.worker.is_alive() and (st.read_history(program="observer") or [{}])[0].get("state") == "stopped",
          f"{closed_in:.1f}초 {left}")
    print(f"사진: {SHOTS}")
    print("실패:", fails or "없음")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
