# -*- coding: utf-8 -*-
"""옵저버 단계 목록 스크롤 (업체 미팅 2026-11-11 버그): 처음 켰을 때·프리셋을 바꿨을 때 맨 위부터, 기록 중 새 단계는 맨 아래로.
창은 숨긴 채로.  .venv\\Scripts\\python.exe tests\\test_observer_scroll.py
"""
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "firebase" / "agent")]
TMP = tempfile.mkdtemp(prefix="rpa_scroll_")
os.environ.update(RPA_USER_CONFIG=os.path.join(TMP, "u.json"), RPA_PROGRAMDATA=TMP, RPA_STATUS_DIR=TMP)
sys.stdout.reconfigure(encoding="utf-8")

import rpa_observer as obs  # noqa: E402
import rpa_status as st  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  {detail!r}"))
    if not ok:
        fails.append(name)


class NoWorker:
    def __init__(self, *a):
        self.cancel, self.pause, self.edit = threading.Event(), threading.Event(), threading.Event()

    def start(self):
        pass

    def bounds(self, *a):
        pass


obs.Worker = NoWorker
obs.otp_relay.phone_list = lambda: []
st.write_user_config({"LogIn": {"AdminCode": "t", "ID": "erp", "PW": "pw"}, "Sites": {}})
st.preset_limit = lambda: 3


def rec(n):
    steps = [{"kind": "goto", "href": "https://a", "url": "/", "page": 0, "frame": {"main": True}}]
    steps += [{"kind": "click", "page": 0, "frame": {"main": True}, "target": {"tag": "button", "text": f"단추 {i}", "textCount": 1}} for i in range(n)]
    return {"version": 1, "start_url": "https://a", "steps": [dict(s, id=k) for k, s in enumerate(steps)]}


st.write_presets([{"name": "가", "code": "012", "record": rec(60)}, {"name": "나", "code": "034", "record": rec(60)}])
root = obs.new_root()
root.geometry("900x500+0+0")
root.withdraw()
app = obs.App(root, 1.0, obs.load_presets())
root.update()


def top():
    root.update()
    return app.canvas.yview()[0]


check("처음 켰을 때 맨 위부터", top() == 0.0, top())
app.canvas.yview_moveto(0.5)
app.select(1)
check("다른 프리셋으로 바꾸면 맨 위부터", top() == 0.0, top())
check("목록이 화면보다 길다 (시험 전제)", app.canvas.yview()[1] < 1.0, app.canvas.yview())
app.canvas.yview_moveto(0.5)
app.select(0)
check("돌아와도 맨 위부터", top() == 0.0, top())
app.canvas.yview_moveto(0.5)
app.render()
check("같은 프리셋을 다시 그리면 (단계 지우기 등) 보던 자리 그대로", abs(top() - 0.5) < 0.05, top())
app.recording = app.cur
app.presets[0]["loaded"] = rec(70)        # 기록 중 단계가 늘어난 것 (그리기만 보면 된다)
app.render()
check("기록 중 새 단계가 생기면 맨 아래로", app.canvas.yview()[1] == 1.0, app.canvas.yview())
app.recording = None
root.destroy()

shutil.rmtree(TMP, ignore_errors=True)
print("=== 실패", len(fails), fails)
sys.exit(1 if fails else 0)
