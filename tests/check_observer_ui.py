# -*- coding: utf-8 -*-
"""옵저버 화면 시험 - 진짜 창을 띄워 혼자 주소 치기 → 기록 → 단계 지우기·끄기 → 기록 끝 → 미리보기 → 저장을 하고 사진을 남긴다.
2~3분 동안 마우스·키보드를 쓴다 (주소줄은 pywinauto 로 친다). 임시 설정으로만 돈다 (진짜 설정은 안 건드린다).
    .venv\\Scripts\\python.exe tests\\check_observer_ui.py [사진 폴더]
"""
import datetime
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
fails = []


def check(name, cond, detail=""):
    print(f"  [{'통과' if cond else '실패'}] {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


def main():
    srv, base, mall = fake_mall.start(datetime.date.today(), True)
    host = base.replace("http://", "")
    scale = rr.dpi_scale()
    root = rr.new_root()
    app = rr.App(root, scale, rr.load_presets(), hint=f"시험용 가짜 쇼핑몰: <b>{host}/login</b>",
                 fake_creds=(fake_mall.USER, fake_mall.PASSWORD))
    result = {}

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
        app.toggle_record()                                                                     # 기록 끝

    def on_stopped():
        mall.notice = True
        app.root.after(600, app.preview)
        app.root.after(9000, lambda: shot("2_미리보기.png"))

    def on_preview_done(ok):
        result["preview_ok"] = ok
        app.root.after(500, finish)

    def finish():
        shot("3_끝.png")
        result["saved"] = app.save()
        for _ in range(12):
            if len(app.presets) < rr.MAX_PRESETS:
                app.add_preset()
        result["ten"] = (len(app.presets), "+" in [w.cget("text") for w in app.preset_bar.winfo_children()
                                                   if isinstance(w, tk.Button)])
        app.root.after(500, app.quit)

    app.on_recording, app.on_human_done = on_recording, on_human_done
    app.on_stopped, app.on_preview_done = on_stopped, on_preview_done
    root.mainloop()
    srv.shutdown()

    check("켜자마자 빈 ① 에서 기록을 시작하고, 주소줄에 친 주소가 첫 단계", result.get("first", "").startswith("주소줄에 http"),
          str(result))
    check("미리보기가 끝까지 갔다", result.get("preview_ok") is True, str(result))
    text = open(st.presets_path(), encoding="utf-8").read()
    saved = json.loads(text)
    check("프리셋 파일: 배열, ① 은 주소 치기로 시작·사이트코드 012·창 크기, ② 는 빈 것",
          isinstance(saved, list) and saved[0]["record"]["steps"][0]["kind"] == "goto" and saved[0]["code"] == "012"
          and saved[0]["record"].get("viewport") and saved[1]["record"] is None, text[:300])
    check("프리셋 파일에 아이디·비밀번호가 없다", fake_mall.USER not in text and fake_mall.PASSWORD not in text)
    site = st.read_user_config()["Sites"].get("PRESET1") or {}
    check("사용자 설정 PRESET1: 아이디, 잠긴 비밀번호, 꺼짐, replay", site.get("ID") == fake_mall.USER
          and st.unseal(site.get("PW")) == fake_mall.PASSWORD and site.get("Stts") == 9 and site.get("Action") == ["replay"],
          str(site))
    row = (st.read_history(program="observer") or [{}])[0]
    logs = "\n".join(row.get("log_tail") or [])
    check("대시보드 기록에 '옵저버' 미리보기 한 줄 (성공)", row.get("program_label") == "옵저버" and row.get("state") == "success",
          str(row)[:300])
    check("그 로그에는 칸에 친 값·아이디·비밀번호가 없다", "주문 처리" not in logs and fake_mall.USER not in logs
          and fake_mall.PASSWORD not in logs, logs[-500:])
    pv = os.path.join(st.data_dir(), "옵저버", "미리보기")
    check("미리보기로 받은 파일은 기록 폴더 (ERPIA_AI_EXCEL 아님)", os.path.isdir(pv) and any(n.startswith("(012)") for n in os.listdir(pv)))
    check("프리셋은 10개까지 - 10개면 [+] 가 없다", result.get("ten") == (10, False), str(result.get("ten")))
    print(f"사진: {SHOTS}")
    print("실패:", fails or "없음")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
