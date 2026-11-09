# -*- coding: utf-8 -*-
"""운송장 전송 마켓 (사용자 2026-11-09) - 옵저버가 프리셋마다 고르는 마켓, 운송장번호 전송이 켜진 PC 에만 칸이 보인다,
PROCESS 운송장번호 전송 모듈이 wellife.invoice_markets() 로 읽는다. 창은 숨긴 채로.
    .venv\\Scripts\\python.exe tests\\test_invoice_market.py
"""
import datetime
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "firebase" / "agent")]
TMP = tempfile.mkdtemp(prefix="rpa_market_")
os.environ.update(RPA_USER_CONFIG=os.path.join(TMP, "u.json"), RPA_PROGRAMDATA=TMP, RPA_STATUS_DIR=TMP)
sys.stdout.reconfigure(encoding="utf-8")

import preset_transfer as pt  # noqa: E402
import rpa_observer as obs  # noqa: E402
import rpa_status as st  # noqa: E402
import wellife  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  {detail!r}"))
    if not ok:
        fails.append(name)


M = st.INVOICE_MARKETS
check("마켓 40개, 겹치지 않고 준 순서 그대로", len(M) == 40 and len(set(M)) == 40 and M[0] == "삼성카드포인트몰"
      and M[8] == "옥션(A낙찰-B운송장)" and M[-1] == "LG라이프케어", M)

# --- 칸이 보이는 조건: 환경설정 켬 + 업체 정책이 안 막음 ---


def setup(routine=None, wellife_section=None, off=(), wl=False):
    cfg = {"LogIn": {"AdminCode": "t", "ID": "erp", "PW": "pw"}, "Sites": {}}
    if routine is not None:
        cfg["Routine"] = routine
    if wellife_section is not None:
        cfg["Wellife"] = wellife_section
    st.write_user_config(cfg)
    s = st.read_settings()
    s["schedule"]["policy"] = {"off": list(off), "wellife": wl}
    st.write_settings(s)


setup({"InvoiceSend": "Y"})
check("환경설정에서 켜면 보인다", st.invoice_send_on() is True)
setup({})
check("기본은 꺼짐 - 안 보인다", st.invoice_send_on() is False)
setup({"InvoiceSend": "N"})
check("끄면 안 보인다", st.invoice_send_on() is False)
setup({"InvoiceSend": "Y"}, off=["InvoiceSend"])
check("켰어도 업체가 막으면 안 보인다", st.invoice_send_on() is False)
setup({"InvoiceSend": "N"}, wellife_section={"InvoiceSend": "Y"}, wl=True)
check("웰라이프 업체는 Wellife 섹션을 본다", st.invoice_send_on() is True)

# --- 파일 ---
setup({"InvoiceSend": "Y"})
rec = {"version": 1, "start_url": "https://a", "steps": [{"kind": "goto", "href": "https://a", "url": "/", "page": 0, "frame": {"main": True}}]}
st.write_presets([{"name": "가", "code": "012", "record": rec, "market": "쿠팡"}, {"name": "나", "code": "", "record": None}])
ps = st.read_presets()
check("프리셋 파일에 market 이 남는다 (없으면 빈 글자)", [p["market"] for p in ps] == ["쿠팡", ""], ps)
Path(st.presets_path()).write_text('[{"no": 1, "name": "옛", "code": "", "saved_at": null, "record": null}, '
                                   '{"no": 2, "name": "옛2", "code": "", "saved_at": null, "record": null}]', encoding="utf-8")
check("market 이 없는 옛 파일도 읽는다", [p["market"] for p in st.read_presets()] == ["", ""])

# --- 저장 전 검사 ---
base = {"id": "a", "pw": "b", "has_pw": True, "record": None}
a = dict(base, no=1, name="가", code="012", market="쿠팡")
b = dict(base, no=2, name="나", code="034", market="쿠팡")
c = dict(base, no=3, name="다", code="056", market="이마트")
check("여러 프리셋이 같은 마켓을 골라도 된다 (프리셋 하나에 마켓 하나 - 사용자 2026-11-09)", obs.validate_presets([a, b, c]) is None)
check("안 고른 칸은 여럿이어도 된다", obs.validate_presets([dict(a, market=""), dict(b, market="")]) is None)
old = {1: {"name": "가", "code": "012", "record": rec, "saved_at": "2026-11-01T00:00:00", "market": "쿠팡"}}
f = obs.keep_dates([{"no": 1, "name": "가", "code": "012", "record": rec, "market": "이마트"}], old, set(), "now")
check("마켓을 바꾸면 저장 날짜가 바뀐다", f[0]["saved_at"] == "now", f)
f = obs.keep_dates([{"no": 1, "name": "가", "code": "012", "record": rec, "market": "쿠팡"}], old, set(), "now")
check("그대로면 날짜도 그대로", f[0]["saved_at"] == "2026-11-01T00:00:00", f)

# --- PROCESS 가 읽는 값 ---
st.write_presets([{"name": "가", "code": "012", "record": rec, "market": "쿠팡"}, {"name": "나", "code": "034", "record": None, "market": ""},
                  {"name": "다", "code": "056", "record": None, "market": "이마트"}])
st.preset_limit = lambda: 3
check("운송장번호 전송 모듈이 읽는 목록: 고른 것만, 번호·사이트코드와 함께", wellife.invoice_markets() ==
      [{"no": 1, "code": "012", "market": "쿠팡"}, {"no": 3, "code": "056", "market": "이마트"}], wellife.invoice_markets())
st.preset_limit = lambda: 2
check("업체 프리셋 수를 넘는 칸은 뺀다", [m["no"] for m in wellife.invoice_markets()] == [1])
check("프리셋 내보내기 파일에 마켓", pt.export_item(1).get("market") == "쿠팡")

# --- 옵저버 화면 ---


class NoWorker:
    def __init__(self, *a):
        self.cancel, self.pause, self.edit = threading.Event(), threading.Event(), threading.Event()

    def start(self):
        pass

    def bounds(self, *a):
        pass


obs.Worker = NoWorker
obs.otp_relay.phone_list = lambda: []
st.preset_limit = lambda: 3


def app_with(on):
    setup({"InvoiceSend": "Y" if on else "N"})
    root = obs.new_root()
    root.withdraw()
    app = obs.App(root, 1.0, obs.load_presets())
    root.update()
    return root, app


root, app = app_with(True)
check("켜진 PC 는 칸이 보인다", bool(app.market_box.grid_info()))
check("불러온 프리셋의 마켓이 골라져 있다", app.market_box.get() == "쿠팡", app.market_box.get())
app.select(1)
check("안 고른 프리셋은 '(선택 안 함)'", app.market_box.get() == obs.MARKET_NONE, app.market_box.get())
app.market_box.current(M.index("AK몰") + 1)
app._market_changed()
check("고르면 그 프리셋 값이 된다", app.presets[1]["market"] == "AK몰")
app.market_box._open()
lb = app.market_box._list
check("마켓 목록은 10줄 스크롤 목록으로 열린다", int(lb["height"]) == 10 and len(lb.get_children()) == 41, (lb["height"], len(lb.get_children())))
app.market_box._close(30)
check("목록에서 고르면 그 프리셋 값이 되고 목록이 닫힌다", app.presets[1]["market"] == M[29] != "AK몰" and not lb.winfo_exists(),
      app.presets[1]["market"])
app.select(0)
check("다른 프리셋으로 가면 그 프리셋 값", app.market_box.get() == "쿠팡")
app.market_box.current(0)
app._market_changed()
check("'(선택 안 함)' 은 빈 값", app.presets[0]["market"] == "")
root.destroy()
root, app = app_with(False)
check("꺼진 PC 는 칸이 안 보인다", not app.market_box.grid_info())
check("꺼져 있어도 고른 값은 그대로 들고 있다", app.presets[0]["market"] == "쿠팡")
root.destroy()

shutil.rmtree(TMP, ignore_errors=True)
print("=== 실패", len(fails), fails)
sys.exit(1 if fails else 0)
