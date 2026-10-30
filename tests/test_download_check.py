# -*- coding: utf-8 -*-
"""받은 파일 검사 (2026-10-15 메모 5: 다운로드가 다 됐나, 느려도 끝까지 받나, 진짜 엑셀인가).

  1. download_problem - 파일 모양만 본다 (브라우저 없음): 빈 파일·잘린 xlsx/xls·엑셀 대신 웹 화면·HTML 표 .xls·CSV
  2. 재생 (창은 뜨지 않는다): 한 번 기록한 '받기' 를 서버가 이렇게 줄 때
     느리게 시작 / 아주 느리게 내려받기 / 시작이 기다림보다 늦음 / 중간에 끊김 / 잘린 채 끝남 / 빈 파일 / 로그인 화면
    .venv\\Scripts\\python.exe tests\\test_download_check.py
"""
import io
import os
import sys
import tempfile
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import web_replay as rec  # noqa: E402
from fake_mall import xlsx_bytes  # noqa: E402

OUT = tempfile.mkdtemp(prefix="download_check_")
fails = []


def check(name, ok, detail=""):
    print(("통과 " if ok else "실패 ") + name + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def file(name, data):
    p = os.path.join(OUT, name)
    with open(p, "wb") as f:
        f.write(data)
    return p


print("=== 1. 파일 모양 ===")
GOOD = xlsx_bytes("주문 3건")
OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * (512 * 8 - 8)
LOGIN = "<!doctype html><html><head><meta charset='utf-8'><title>로그인</title></head><body><form>아이디 <input></form></body></html>"
TABLE = "<html><body><table><tr><td>주문번호</td><td>상품</td></tr><tr><td>1</td><td>사과</td></tr></table></body></html>"
for name, data, bad, why in (
        ("ok.xlsx", GOOD, None, "온전한 xlsx"),
        ("empty.xlsx", b"", "빈 파일", "빈 파일"),
        ("cut.xlsx", GOOD[: len(GOOD) // 2], "완료되지", "반만 받은 xlsx"),
        ("zip.xlsx", (lambda b: (zipfile.ZipFile(b, "w").close(), b.getvalue())[1])(io.BytesIO()), "엑셀", "엑셀이 아닌 빈 압축"),
        ("old.xls", OLE, None, "옛 엑셀 xls (512바이트 단위)"),
        ("oldcut.xls", OLE[:3000], None, "512바이트 단위가 아닌 xls 도 통과 (마지막 칸을 안 채우는 생성기가 있다 - 잘림은 브라우저가 알린다, 검토 2026-10-16)"),
        ("login.xlsx", LOGIN.encode(), "웹 화면", "엑셀 대신 로그인 화면"),
        ("login16.xls", ("﻿" + LOGIN).encode("utf-16-le"), "웹 화면", "UTF-16 웹 화면"),
        ("table.xls", TABLE.encode("cp949", "ignore"), None, "쇼핑몰이 주는 HTML 표 .xls"),
        ("table16.xls", ("﻿" + TABLE).encode("utf-16-le"), None, "UTF-16 HTML 표 .xls"),
        ("sml.xls", b"<?xml version='1.0'?><Workbook xmlns='urn:schemas-microsoft-com:office:spreadsheet'></Workbook>", None, "XML 스프레드시트"),
        ("orders.csv", "주문번호,상품\n1,사과\n".encode("cp949"), None, "CSV"),
        ("fake.xlsx", b"FAKE-XLSX", "형식", "글자만 든 .xlsx")):
    got = rec.download_problem(file(name, data))
    check(f"{why} -> {'통과' if bad is None else bad}", (got is None) if bad is None else (got is not None and bad in got), got)

print("=== 2. 재생: 서버가 이렇게 줄 때 ===")
MODE = {"m": "ok"}
HITS = []                                  # /file 요청 - 느린 받기를 두 번 누르지 않나
PAGE = """<!doctype html><meta charset="utf-8"><title>주문</title><p>주문 내역</p><a id="dl" href="/file">엑셀 받기</a>"""
CLICK = {   # 받기 단추가 파일 대신 알림창을 띄우는 몰 ('주문 없음' 헛된 기다림, 사용자 2026-10-21)
    "nodata": "alert('조회된 데이터가 없습니다.');return false",
    "nodata_late": "alert('조회된 데이터가 없습니다.');setTimeout(function(){location.href='/file'},1500);return false",
    "otheralert": "alert('엑셀 파일을 만드는 중입니다');return false",
    # 확인 질문은 [확인] 을 눌러 몰이 파일을 만든다 - 유예(시험 4초)보다 늦게 와도 받아야 한다 (검토 10-22)
    "nodata_confirm": "if(confirm('조회된 데이터가 없습니다.'))setTimeout(function(){location.href='/file'},6000);return false",
}
CHUNK = 4096
BIG = xlsx_bytes(os.urandom(120_000).hex())   # 무작위라 압축이 덜 돼 100KB 남짓 - 몇 초에 걸쳐 보낼 만큼


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def head(self, length=None, ctype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Disposition", "attachment; filename=orders.xlsx")
        if length is not None:
            self.send_header("Content-Length", str(length))
        else:
            self.send_header("Connection", "close")
        self.end_headers()

    def do_GET(self):
        if not self.path.startswith("/file"):
            click = CLICK.get(MODE.get("m"))
            b = (PAGE.replace('href="/file"', f'href="/file" onclick="{click}"') if click else PAGE).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
            return
        m = MODE["m"]
        HITS.append(m)
        if m in ("slowstart", "toolate"):
            time.sleep(MODE.get("wait", 9))      # 쇼핑몰이 엑셀을 만드는 동안 아무것도 안 보낸다
        if m == "trickle":                       # 아주 느리게 - 몇 초에 걸쳐 조금씩
            self.head(len(BIG))
            for i in range(0, len(BIG), CHUNK):
                self.wfile.write(BIG[i:i + CHUNK])
                self.wfile.flush()
                time.sleep(MODE.get("gap", 0.4))
            return
        if m == "drop":                          # 크기를 알려 놓고 중간에 끊긴다
            self.head(len(BIG))
            self.wfile.write(BIG[: len(BIG) // 3])
            self.wfile.flush()
            self.close_connection = True
            return
        if m == "cutclose":                      # 크기를 안 알려 주고 반만 보낸 채 닫는다 (브라우저는 다 받은 줄 안다)
            self.head(None)
            self.wfile.write(GOOD[: len(GOOD) // 2])
            self.close_connection = True
            return
        data = {"empty": b"", "login": LOGIN.encode("utf-8")}.get(m, GOOD)
        self.head(len(data), "text/html; charset=utf-8" if m == "login" else
                  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.wfile.write(data)


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"


def human(page):
    page.wait_for_timeout(400)
    with page.expect_download():
        page.click("#dl")
    page.wait_for_timeout(400)


r = rec.record(BASE + "/", os.path.join(OUT, "rec.json"), headless=True, human=human)
check("기록: 받기 단계에 받은 파일이 붙는다", any(s.get("download") == "orders.xlsx" for s in r["steps"]), [rec.describe(s) for s in r["steps"]])


def replay(mode, timeout_ms=None, **kw):
    MODE.clear()
    MODE.update(m=mode, **kw)
    HITS.clear()
    saved_timeout = rec.DOWNLOAD_TIMEOUT_MS
    if timeout_ms:
        rec.DOWNLOAD_TIMEOUT_MS = timeout_ms
    lines = []
    t = time.time()
    try:
        ok, rp = rec.replay(r, {"ID": "", "PW": ""}, os.path.join(OUT, mode), "012", log=lines.append, step_timeout=4, step_tries=1)
    finally:
        rec.DOWNLOAD_TIMEOUT_MS = saved_timeout
    files = [f for f in (os.listdir(os.path.join(OUT, mode)) if os.path.isdir(os.path.join(OUT, mode)) else [])
             if not f.startswith("실패_")]          # 실패 사진 (ACTOR 는 받은 파일 폴더가 아닌 곳에 둔다)
    return ok, rp, lines, files, time.time() - t


ok, rp, lines, files, sec = replay("ok")
check("보통: 받고 검사를 통과한다", ok and files == ["(012)orders.xlsx"], (lines[-3:], files))
check("기다림 기본값은 5분 (쇼핑몰이 엑셀을 만드는 데 오래 걸려도)", rec.DOWNLOAD_TIMEOUT_MS == 300000, rec.DOWNLOAD_TIMEOUT_MS)

ok, rp, lines, files, sec = replay("slowstart", wait=9)
check("느리게 시작 (9초 동안 아무것도 안 옴): 기다렸다가 받는다", ok and files == ["(012)orders.xlsx"], (lines[-3:], files))
check("기다리는 동안 '다운로드를 기다리는 중입니다' 를 남긴다 (사람이 멈춘 줄 알지 않게)", any("파일 다운로드를 기다리는 중입니다." in x for x in lines), lines[-6:])
check("느린 받기를 두 번 누르지 않는다 (요청 한 번 - 눌렀는데 늦게 오는 것을 '안 눌림' 으로 보고 스크립트로 또 눌렀다)",
      HITS == ["slowstart"] and not any("스크립트로 누름" in x for x in lines), (HITS, lines[-4:]))

ok, rp, lines, files, sec = replay("trickle", gap=0.15)
got = open(os.path.join(OUT, "trickle", files[0]), "rb").read() if files else b""
check(f"아주 느리게 내려받기 ({sec:.0f}초): 끝까지 받은 뒤에야 다음으로 - 파일이 온전하다", ok and got == BIG, (lines[-3:], len(got), len(BIG)))

ok, rp, lines, files, sec = replay("toolate", timeout_ms=4000, wait=8)
check("시작이 기다림보다 늦으면 실패 - '초 안에 파일이 오지 않았습니다'", not ok and any("파일 다운로드가 시작되지 않았습니다" in str(x) for x in rp.results[-1:]),
      rp.results[-1:])

saved_grace = rec.NO_DATA_GRACE
rec.NO_DATA_GRACE = 4
ok, rp, lines, files, sec = replay("nodata")
check(f"받기 단추 뒤 '자료 없음' 알림창 ({sec:.0f}초): 5분 기다리지 않고 '주문 없음' 으로 그 단계를 끝낸다 - 실패가 아니다 (사용자 2026-10-21)",
      ok and rp.no_target and not files and sec < 30 and "주문 없음 (알림창: 조회된 데이터가 없습니다.)" == rp.no_target_why
      and rp.results[-1][1] == "ok", (rp.results[-1:], rp.no_target_why, sec))
ok, rp, lines, files, sec = replay("nodata_late")
check("'자료 없음' 알림창 뒤라도 유예 안에 파일이 오면 받는다", ok and files == ["(012)orders.xlsx"] and not rp.no_target, (rp.results[-1:], files))
ok, rp, lines, files, sec = replay("otheralert", timeout_ms=6000)
check("다른 알림창('엑셀 파일을 만드는 중')이면 예전처럼 끝까지 기다린다", not ok and not rp.no_target and sec >= 5
      and "파일 다운로드가 시작되지 않았습니다" in str(rp.results[-1]), (rp.results[-1:], sec))
ok, rp, lines, files, sec = replay("nodata_confirm")
check("'자료 없음' 글이라도 확인 질문(confirm)이면 '주문 없음' 으로 보지 않고 늦게 오는 파일을 받는다 (검토 10-22)",
      ok and files == ["(012)orders.xlsx"] and not rp.no_target, (rp.results[-1:], files, sec))
rec.NO_DATA_GRACE = saved_grace
check("문구 판정: 자료 없음만 - 선택·권한·로그인·오류 낱말이 있으면 아니다",
      [rec.no_data(m) for m in ("검색 결과가 없습니다", "주문 내역이 존재하지 않습니다.", "선택된 주문이 없습니다.", "권한이 없습니다",
                                "로그인 세션이 없습니다", "오류가 발생했습니다. 데이터가 없습니다", "조회된 건이 없습니다", "조건에 맞는 값이 없습니다",
                                "동의 내역이 없습니다", " 검색 결과 없음 \n", "데이터가 존재하지 않습니다!")]
      == [True, True, False, False, False, False, True, False, False, True, True])
# 파일이 오는 글 - '주문 없음' 으로 보면 늦게 온 파일을 버려 주문이 빠진다 (검토 10-22)
FILE_COMING = ("주문 내역이 없는 상품은 제외하고 다운로드합니다", "결과가 없으면 빈 파일이 내려갑니다", "주문 상태 변경 없이 다운로드합니다",
               "신규 주문이 없습니다. 전체 주문을 다운로드합니다.", "미처리 주문이 없습니다. 전체 주문을 다운로드하시겠습니까?",
               "출고지시 주문이 없는 경우 빈 엑셀이 다운로드됩니다", "주문서 다운로드 내역이 없습니다. 새로 생성합니다",
               "엑셀 파일을 생성하였습니다\n미처리 주문이 없습니다")     # 줄바꿈도 문장 경계
check("문구 판정: 다른 말이 이어지는 글(없는·없으면·없이, 두 문장)은 자료 없음이 아니다", not any(rec.no_data(m) for m in FILE_COMING),
      [m for m in FILE_COMING if rec.no_data(m)])

for mode, why, word in (("drop", "중간에 끊김 (크기를 알려 놓고)", "끊겼"), ("cutclose", "반만 보내고 닫음 (크기 모름)", "완료되지"),
                        ("empty", "빈 파일", "빈 파일"), ("login", "엑셀 대신 로그인 화면", "웹 화면")):
    ok, rp, lines, files, sec = replay(mode)
    reason = str(rp.results[-1:])
    check(f"{why}: 실패로 끝나고 까닭이 남는다 ('{word}')", not ok and word in reason, (reason, lines[-3:]))
    check(f"{why}: 쓸 수 없는 파일은 남기지 않는다 (PROCESS 가 올리지 않게)", files == [] and not rp.saved, (files, rp.saved))

srv.shutdown()
print("실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
