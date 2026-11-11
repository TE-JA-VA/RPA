# -*- coding: utf-8 -*-
r"""옵저버 - 왼쪽 브라우저(주소줄 있음), 오른쪽 프리셋 ①~⑩ 과 사람이 한 조작 목록, 아래 미리보기·저장.

    시작 메뉴 'RPA 옵저버' (Prepare_Observer.exe). 켤 때 관리자 권한을 묻는다 (설정 폴더는 관리자만 고칠 수 있다).
    Prepare_Observer.exe --check      창 없이 확인하고 끝 줄 '옵저버 점검 끝' (빌드·샌드박스)
    .venv\Scripts\python.exe rpa_observer.py   개발 PC 에서는 RPA_USER_CONFIG·RPA_PROGRAMDATA 로 시험 폴더를 가리킨 채로만

프리셋마다 '로그인 ~ 엑셀 받기' 기록 하나 → 사용자 설정 옆 RPA_Presets.json (rpa_status.read_presets/write_presets).
아이디·비밀번호는 사용자 설정 Sites 의 PRESETn 칸에 (비밀번호는 쓰는 순간 잠긴다, rpa_status.save_preset_sites).
설계: docs/superpowers/specs/2026-09-30-shop-record-replay-design.md 4절. 화면 시험: tests/check_observer_ui.py
브라우저를 이 창 속에 끼우지 않는다 (SetParent 로 끼우면 한글 입력·포커스가 흔들린다). 기록 창 왼쪽에 붙여 두고 같이 옮긴다.
Playwright 는 한 스레드에서만 부를 수 있어 일꾼 스레드가 브라우저를 모두 맡고, 화면(tkinter)과는 큐로만 주고받는다.
"""
import argparse
import ctypes
import datetime
import glob
import json
import msvcrt
import os
import queue
import re
import shutil
import sys
import tempfile
import threading
import time
import tkinter as tk
import unicodedata
from ctypes import wintypes
from tkinter import filedialog, messagebox

from playwright.sync_api import sync_playwright

import mail_imap
import observer_widgets as w
import otp_relay
import preset_transfer as pt
import rpa_status as st
import web_replay as rec


REC_DIR = os.path.join(st.data_dir(), "옵저버")          # 기록·미리보기로 받은 파일 (루틴이 읽는 ERPIA_AI_EXCEL 이 아니다)
RECORD_DL = os.path.join(REC_DIR, "기록")
PREVIEW_DL = os.path.join(REC_DIR, "미리보기")
# 메일 2차인증 메일함 계정 칸 안내 (설계 2026-11-02 6절 - 사용자 검수)
MAIL_ACCOUNT_HINT = "인증 메일을 받는 메일 계정입니다. 이 PC에만 암호화하여 저장되며, 오토파일럿이 인증번호를 확인하는 데만 사용합니다."
MAIL_HINT = ("엑셀파일을 받으려는 메일이 '메일 시작 문구'로 시작하는 경우, 그 글자로 시작하는 메일이 처리대상이 됩니다."   # 메일 첨부파일일 때 안내 (사용자 2026-10-14 검수)
             " 메일이 많으면 제목으로 검색한 뒤 고르십시오.")      # (BugBuster I5)
IMAP_HINT = ("메일 서버(IMAP)에서 조건에 맞는 메일의 엑셀 첨부파일을 받습니다. 아이디·비밀번호는 메일 계정의 것입니다 "
             "(네이버·다음·Gmail 은 메일 설정에서 IMAP 사용을 켜고, Gmail 은 앱 비밀번호를 넣어 주십시오).")
PICK_NOTE = "# 알림 : 미리보기 중에는 가장 적절한 메일 1통으로 테스트합니다. (이미 받은 메일도 포함)"   # 메일 고르기 미리보기 알림 (사용자 2026-10-14 검수)
MIN_PRESETS = st.PRESET_MIN             # 최대는 업체마다 (st.preset_limit - App.max_presets)
MARKET_NONE = "(선택 안 함)"
HEAD_DOWN = "각 프리셋마다 로그인부터 엑셀 파일 다운로드까지 보여주시면 다음 번부터 자동으로 엑셀파일을 수집합니다."
HEAD_UP = "각 프리셋마다 로그인부터 엑셀 파일 업로드까지 보여주시면 다음 번부터 자동으로 사이트에 엑셀파일을 올립니다."
APP_ID = "AFTERMARKET.RPA.Observer"                     # 작업 표시줄 묶음 이름. 시작 메뉴 바로 가기(installer.iss)와 같아야 한다
ICON_NAME = "AFTER_MARKET_PREPARE.ico"                  # 옵저버 주황 날개 (tools/make_icon.py)
CHECK_DONE = "옵저버 점검 끝"                              # --check 끝 줄 (build_release.MARKERS·sandbox_inner.ps1)
PROFILE_PREFIX = "rec_prof_"                            # 기록·미리보기 브라우저의 새 프로필 (로그인 쿠키가 든다 - 끝나면 지운다)
UI, F, F_SMALL, F_BOLD = w.UI, w.F, w.F_SMALL, w.F_BOLD
BG, CARD, LINE = w.PAGE, w.CARD, w.SPLIT                # Ant Design (설계 2026-11-06, observer_widgets)
INK, MUTED = w.TEXT, w.TEXT2
BLUE = w.PRIMARY
GREEN_D = "#389e0d"
RED, RED_D = "#cf1322", "#a8071a"                       # 글자용 - 단추 빨강(w.DANGER)은 작은 글자로 쓰기에 흐리다
GUIDE = """<!doctype html><meta charset="utf-8"><title>오토파일럿 기록</title>
<body style="margin:0;font-family:'Malgun Gothic',sans-serif;background:#f3f4f6;color:#111827">
<div style="padding:28px 40px"><div style="font-size:40px;line-height:1">⬆</div>
<h2 style="margin:10px 0 6px">주소 표시줄에 쇼핑몰 주소를 입력해주십시오.</h2>
<p style="margin:0 0 18px;font-size:15px">먼저 프리셋에 쇼핑몰 아이디와 비밀번호를 설정해 주십시오.<br>로그인부터 엑셀 파일을 받을 때까지의 행위를 기록하게 됩니다.</p>
<p style="margin:0;color:#6b7280;font-size:14px">{hint}</p></div>"""


circled = st.circled     # ① ~ ㊿ (웰라이프 40개) - 에이전트와 같은 함수


def dpi_scale():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    try:
        return ctypes.windll.user32.GetDpiForSystem() / 96
    except Exception:
        return 1.0


def work_area():
    r = wintypes.RECT()
    ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0)       # SPI_GETWORKAREA, 물리 픽셀
    return r.left, r.top, r.right, r.bottom


def frame_rect(hwnd):
    """창의 보이는 테두리 (윈도우 11 의 안 보이는 크기 조절 테두리는 뺀다), 물리 픽셀."""
    r = wintypes.RECT()
    if ctypes.windll.dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:
        ctypes.windll.user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


class LiveRecorder(rec.Recorder):
    """rec.Recorder + 주소줄에 친 주소·뒤로 가기·새 탭도 단계로, 바뀔 때마다 화면에 알림. 단계마다 고유 번호."""

    def __init__(self, context, sample_dir, notify):
        self.notify, self.next_id, self.context, self.tabs = notify, 0, context, set()
        super().__init__(context, sample_dir)

    def _ids(self):
        for s in self.steps:                # 한 번에 둘이 들어올 수 있다 (마우스 올리기 + 누르기)
            if "id" not in s:
                s["id"] = self.next_id
                self.next_id += 1
        self.notify(self.steps)

    def _add(self, step):
        step["t"] = time.time() * 1000      # JS 의 Date.now() 와 같은 시계
        self.steps.append(step)
        self._ids()

    def _event(self, source, ev):
        super()._event(source, ev)
        self._ids()

    def _page(self, page):
        super()._page(page)
        no = self._no(page)
        if no and rec.user_tab(page):
            self._new_tab(no)
        self._track_nav(page, no)
        self._ids()

    def _browser_page(self, page, no, step):
        super()._browser_page(page, no, step)
        if "newtab" in page.url or "new-tab" in page.url or page.url.startswith(rec.EDGE_NEW_TAB):  # 주소 없이 생겼다가 새 탭 주소가 붙은 탭
            self._new_tab(no)

    def _new_tab(self, no):
        if no not in self.tabs:
            self.tabs.add(no)
            self._add({"kind": "newtab", "page": no, "url": ""})

    def _track_nav(self, page, no):
        """주소줄에 친 주소 = 페이지가 먼저 요청하지 않고 시작된 새 문서 이동 (링크·폼·스크립트·새로고침 태그는
        frameRequestedNavigation 이 먼저 온다). 이력의 이동 종류(typed)로 보면 열리자마자 스크립트로 넘어가는 주소는
        그 줄이 'link' 로 덮여 빠졌다 (2026-10-16 사용자: 긴 링크를 붙여넣으면 기록이 안 됨). 뒤로 가기는 이력 번호가 줄면."""
        try:
            cdp = self.context.new_cdp_session(page)
            cdp.send("Page.enable")
            main = cdp.send("Page.getFrameTree")["frameTree"]["frame"]["id"]
        except Exception:
            return
        last = {"i": None, "asked": 0.0}

        def asked(e):
            if e.get("frameId") == main:
                last["asked"] = time.time()

        def started(e):
            if e.get("frameId") != main:
                return                      # iframe 안 이동은 누른 것의 결과
            by_page, last["asked"] = time.time() - last["asked"] < 10, 0.0
            href = e.get("url") or ""
            if (e.get("navigationType") == "differentDocument" and not by_page
                    and href.startswith(("http://", "https://")) and not href.startswith(rec.BROWSER_PAGES)):
                self._add({"kind": "goto", "page": no, "url": rec.url_path(href), "href": href})

        def on_nav(frame):
            if frame is not page.main_frame:
                return
            try:
                h = cdp.send("Page.getNavigationHistory")
            except Exception:
                return
            i = h["currentIndex"]
            prev, last["i"] = last["i"], i
            if prev is not None and i < prev:
                self._add({"kind": "back", "page": no, "url": rec.url_path(h["entries"][i]["url"])})
        cdp.on("Page.frameRequestedNavigation", asked)
        cdp.on("Page.frameStartedNavigating", started)
        page.on("framenavigated", on_nav)

    def _dialog(self, d):
        super()._dialog(d)
        self._ids()

    def _download(self, d):
        super()._download(d)
        self._ids()


def launch(p, **kw):
    """새 프로필 Edge (주소줄·탭 보임). 기록 중 화면을 가리는 것은 끈다: 자동화 안내 띠, 비밀번호 저장 제안, 파일을 받을 때
    뜨는 다운로드 창, '--no-sandbox' 경고 띠 (자동화 안내 띠를 끄면 대신 뜬다 - 보호 기능을 켜 그 플래그를 안 붙인다).
    못 띄우면 만든 프로필 폴더를 지우고 오류를 그대로 올린다."""
    prof = tempfile.mkdtemp(prefix=PROFILE_PREFIX)
    try:
        os.makedirs(os.path.join(prof, "Default"))
        with open(os.path.join(prof, "Default", "Preferences"), "w", encoding="utf-8") as f:
            json.dump({"credentials_enable_service": False, "profile": {"password_manager_enabled": False},
                       "browser": {"show_hub_popup_on_download_start": False}}, f)
        ctx = rec.edge(p.chromium.launch_persistent_context, prof, headless=False, no_viewport=True, accept_downloads=True,
                       ignore_default_args=["--enable-automation"], chromium_sandbox=True, **kw)
    except BaseException:
        shutil.rmtree(prof, ignore_errors=True)
        raise
    return ctx, prof


def sweep_profiles(root=None):
    """지난번에 못 지운 기록·미리보기 프로필을 지운다 (작업 관리자로 끔·정전 - 로그인 쿠키가 남는다).
    옵저버 잠금을 쥔 뒤에만 부른다 - 그때는 다른 옵저버가 쓰는 프로필일 수 없다."""
    for path in glob.glob(os.path.join(root or tempfile.gettempdir(), PROFILE_PREFIX + "*")):
        shutil.rmtree(path, ignore_errors=True)


class Worker(threading.Thread):
    """브라우저 일꾼 - 기록 창과 미리보기 창. 화면과는 cmd(받기)·ui(보내기) 큐로만."""

    def __init__(self, bounds, ui, hint):
        super().__init__(daemon=True)
        self.bounds, self.ui, self.hint, self.cmd = bounds, ui, hint, queue.Queue()
        self.ctx = self.prof = self.page = self.recorder = None
        self.rec_no = None
        self.cancel = threading.Event()   # [■ 중단]·창 닫기 - 미리보기가 찾기·기다리기 중에도 곧 멈춘다
        self.pause = threading.Event()    # [Ⅱ 일시정지] - 미리보기가 다음 단계 앞에서 기다린다. 둘 다 화면이 켜고 끈다
        self.edit = threading.Event()     # [수정] - 일시정지·실패한 자리에서 브라우저를 그대로 두고 이어 기록한다
        self.human = None                 # 시험: 사람 대신 조작할 함수
        self.step_wait = (rec.STEP_WAIT, rec.STEP_TRIES)   # 미리보기가 못 찾을 때 (초, 번) - 시험이 줄인다

    def run(self):
        try:
            with sync_playwright() as p:
                self.p = p
                self.ui.put(("ready",))
                self._loop()
        except Exception as e:
            self.ui.put(("status", f"오류: {type(e).__name__}: {str(e).splitlines()[0]}", RED))
        finally:
            self._close()

    def _loop(self):
        while True:
            try:
                c = self.cmd.get_nowait()
            except queue.Empty:
                c = None
            if c and c[0] == "quit":
                self._close()
                return
            if c:
                try:
                    getattr(self, "_do_" + c[0])(*c[1:])
                except Exception as e:
                    self.ui.put(("status", f"오류 ({c[0]}): {type(e).__name__}: {str(e).splitlines()[0]}", RED))
            live = [pg for pg in self.ctx.pages if not pg.is_closed()] if self.ctx else []
            if live:
                try:
                    live[0].wait_for_timeout(40)       # 들어온 알림(기록)을 Playwright 가 처리할 틈
                except Exception:
                    pass
            else:
                if self.ctx:                            # 사람이 브라우저를 닫았다
                    self._close()
                    self.ui.put(("status", "브라우저가 닫혔습니다. 마지막 작업까지 기록되었습니다.", MUTED))
                    self.ui.put(("recording_stopped",))
                time.sleep(0.05)

    def _close(self):
        if self.ctx:
            try:
                self.ctx.close()
            except Exception:
                pass
        if self.prof:
            shutil.rmtree(self.prof, ignore_errors=True)
        self.ctx = self.prof = self.page = self.recorder = None

    # --- 창 자리 (CDP 의 창 크기는 DIP) ---
    def _window(self, page):
        cdp = page.context.new_cdp_session(page)
        return cdp, cdp.send("Browser.getWindowForTarget")["windowId"]

    def _set_bounds(self, page, b):
        try:
            cdp, wid = self._window(page)
            cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "normal"}})
            cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": b})
            cdp.detach()
        except Exception as e:
            self.ui.put(("status", f"브라우저 창 자리를 못 맞춤: {e}", RED))

    def _rec_bounds(self):
        if not self.page or self.page.is_closed():
            return self.bounds
        try:
            cdp, wid = self._window(self.page)
            b = cdp.send("Browser.getWindowBounds", {"windowId": wid})["bounds"]
            cdp.detach()
            return {k: b[k] for k in ("left", "top", "width", "height")}
        except Exception:
            return self.bounds

    # --- 화면이 시키는 것 ---
    def _do_record(self, no, name, start_url=None):
        self._close()
        self.ctx, self.prof = launch(self.p)
        self.recorder = LiveRecorder(self.ctx, RECORD_DL,
                                     lambda steps: self.ui.put(("steps", no, json.loads(json.dumps(steps)))))
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.recorder._page(self.page)
        self._set_bounds(self.page, self.bounds)
        self.rec_no = no
        if start_url:
            self.page.goto(start_url)
        else:
            self.page.set_content(GUIDE.format(hint=self.hint))
        self._send_viewport()
        self.ui.put(("recording", no))
        self.ui.put(("status", f"● {circled(no + 1)} {name} 기록 중", RED))

    def _send_viewport(self):
        """기록 창 브라우저의 안쪽 크기 - 기록에 넣어 프리페어가 같은 크기로 연다."""
        try:
            self.page.wait_for_timeout(200)          # 창 크기를 바꾼 뒤 그려질 틈
            w, h = self.page.evaluate("() => innerWidth + 'x' + innerHeight").split("x")   # 글자로 (사이트가 Map 을 바꿔치기해도 - rec.SNAP_JS)
            vp = {"width": int(w), "height": int(h)}
            self.ui.put(("viewport", self.rec_no, vp))
        except Exception:
            pass

    def _do_stop(self):
        self._close()
        self.ui.put(("status", "기록했습니다. 목록에서 건너뛰거나 제외할 단계를 선택하실 수 있습니다.", MUTED))
        self.ui.put(("recording_stopped",))

    def _do_dock(self, b):
        self.bounds = b
        if self.page and not self.page.is_closed():
            self._set_bounds(self.page, b)
            self._send_viewport()

    def _do_human(self):
        self.human(self.page)
        self.ui.put(("human_done",))

    def _otp_relay(self, creds, label, stamp):
        """미리보기의 인증번호: 인증 휴대폰을 정했으면 휴대폰 중계, 아니면 (또는 서버에 못 붙으면) 사람이 미리보기 창 칸에 칠 때까지."""
        if creds.get("Phone") and creds.get("SmsSenders"):
            try:
                return otp_relay.agent_relay(creds["Phone"], creds["SmsSenders"], label)
            except RuntimeError as e:
                st.log_line(f"{stamp()} {e} 미리보기 창에서 직접 입력하기를 기다립니다.")
        return otp_relay.ManualOtp(on_wait=lambda: self.ui.put(
            ("status", "미리보기 창의 인증번호 칸에 휴대폰으로 받은 번호를 넣어 주십시오 (2분 안).", BLUE)))

    def _do_preview(self, no, record, ids, creds, code, label):
        """새 프로필 브라우저로 켜 둔 단계를 따라 한다. 한 번 할 때마다 상태 기록 'observer' 한 건 (대시보드 '기록').
        로그에는 칸에 친 값·주소 ? 뒤를 싣지 않는다. 끝나면 (못 띄웠어도·중단해도) 늘 preview_done 과 프로필 지우기.
        단, 일시정지·실패한 자리에서 [수정](edit) 이면 브라우저를 닫지 않고 기록기를 붙여 이어 기록한다 (설계 2026-10-19 4.2절) -
        그때는 editing 알림 뒤 지금 기록과 같다 (steps → [■ 기록 완료] → _do_stop). 못 찾아 멈춘 단계에서도 바로 닫지 않고
        [수정]·[■ 중단] 을 기다린다 (failed_at 알림)."""
        where = self._rec_bounds()
        stamp = lambda: datetime.datetime.now().strftime("[%H:%M:%S]")   # noqa: E731
        steps = record["steps"]
        st.start("observer", [(f"s{i}", rec.describe(s, hide_values=True)) for i, s in enumerate(steps, 1)], title=label)
        st.log_line(f"{stamp()} === 미리보기: {label} ({len(steps)}단계) ===")
        ok, why, note, saved, sec = False, "미리보기를 끝까지 진행하지 못했습니다.", None, [], 0.0
        ctx = prof = None
        editing = False
        try:
            try:
                ctx, prof = launch(self.p, slow_mo=120)     # 새 프로필 = RPA 가 혼자 돌 때처럼 로그아웃 상태
            except Exception as e:
                why = note = f"미리보기 브라우저를 띄우지 못했습니다: {type(e).__name__}: {str(e).splitlines()[0]}"
                st.log_line(f"{stamp()} {why}")
                return
            rp = rec.Replayer(ctx, record, creds, PREVIEW_DL, code, review=True, hide_values=True,
                              log=lambda m: st.log_line(f"{stamp()} {m}"),     # 못 찾으면 20초씩 6번 (rec.STEP_WAIT·STEP_TRIES)
                              step_timeout=self.step_wait[0], step_tries=self.step_wait[1])
            rp.first_page = ctx.pages[0] if ctx.pages else None
            rp.page_hook = lambda pg: self._set_bounds(pg, where)               # 기록 창 자리에 겹쳐 띄운다
            rp.cancel, rp.pause, rp.edit = self.cancel, self.pause, self.edit
            if any(s["kind"] == "otp" and s.get("source") != "copy" for s in steps):   # 휴대폰 문자 인증만 (메일 인증은 메일함에서)
                rp.otp = self._otp_relay(creds, label, stamp)
            if any(s.get("mailOpen") for s in steps):   # 메일 2차인증 - 미리보기는 기억 없이 받은 시각으로 새 메일 (설계 2026-11-02 4절)
                rp.pick_preview = True
            if any(s.get("pick") for s in steps):     # 메일 고르기 - 기억과 상관없이 맞는 메일 1통 (사용자 2026-10-14)
                rp.pick_preview = True
                st.log_line(f"{stamp()} {PICK_NOTE}")

            def progress(i, state, how):
                if state == "paused":
                    self.ui.put(("paused",))
                    return
                if state == "run":
                    st.step(f"s{i}")
                elif state == "skip":
                    st.note("건너뜀 - 화면에 없음")
                elif state == "fail":
                    st.fail_step(how)
                self.ui.put(("progress", ids[i - 1], state, how))
            rp.progress = progress
            try:
                ok = rp.run()
                saved, sec = [os.path.basename(x) for x in rp.saved], rp.elapsed
                failed = rp.results[-1][0] if not ok and rp.results and rp.results[-1][1] == "fail" else None
                if failed and not self.cancel.is_set() and any(not pg.is_closed() for pg in ctx.pages):
                    self.ui.put(("failed_at", failed))          # 닫지 않고 그 단계 앞에서 [수정]·[■ 중단] 을 기다린다
                    while not (self.edit.is_set() or self.cancel.is_set()):
                        rp._idle(200)
                    if self.edit.is_set() and not self.cancel.is_set():   # [수정] 뒤에 [■ 중단] 을 눌렀으면 중단이 이긴다
                        raise rec.EditHere(failed)
            except rec.EditHere as e:
                why = str(e)
                st.log_line(f"{stamp()} {why} 미리보기 브라우저에서 이어서 기록합니다.")
                recorder = LiveRecorder(ctx, RECORD_DL, lambda steps: self.ui.put(("steps", no, json.loads(json.dumps(steps)))))
                recorder.next_id, recorder.tabs = max(ids) + 1, set(rp.pages)   # 새 단계 번호는 이어서, 받은 탭은 '새 탭' 단계로 안 적는다
                editing = True
                self.ui.put(("editing", no, ids[e.i - 1]))      # 기록기가 steps 를 보내기 전에 - 화면이 남길 앞부분을 먼저 자른다
                self.ctx, self.prof, self.page, self.recorder, self.rec_no = ctx, prof, rp.pages[0], recorder, no
                ctx = prof = None                               # finally 가 닫지 않게
                recorder.adopt(rp.pages)                        # 미리보기가 쓰던 탭 번호 그대로 (설계 4.2절 - 새 창을 여는 사이트)
                return
            if not ok and self.cancel.is_set():
                why = note = "미리보기를 중단하였습니다."
            elif not ok and rp.results:
                i, _, how = rp.results[-1]
                why = f"{i}단계에서 멈췄습니다: {how}"
            st.log_line(f"{stamp()} {'미리보기 성공' if ok else '미리보기 멈춤'} ({sec:.0f}초) - 받은 파일: "
                        f"{', '.join(saved) or '없음'}")
            if ctx.pages and not self.cancel.is_set():
                ctx.pages[0].wait_for_timeout(1500)
        except Exception as e:
            why = f"{type(e).__name__}: {str(e).splitlines()[0]}"
            note = f"미리보기 오류: {why}"
            st.log_line(f"{stamp()} {note}")
        finally:
            st.finish("success" if ok else "stopped", None if ok else why)
            if ctx is not None:
                try:
                    ctx.close()
                except Exception:
                    pass
            if prof:
                shutil.rmtree(prof, ignore_errors=True)
            if not editing:
                self.ui.put(("preview_done", ok, saved, sec, note))


def new_preset(no, name=None, code=""):
    """화면이 들고 있는 프리셋 하나. raw = 이번에 기록한 단계, loaded = 저장돼 있던 기록 (둘 중 하나).
    head = [수정]으로 남긴 앞부분 (다듬어진 기록) - 있으면 그 뒤에 raw 를 이어 붙인다."""
    return {"name": name or f"프리셋 {no}", "code": code, "raw": [], "loaded": None, "head": None, "start_url": None,
            "enabled": {}, "deleted": set(), "id": "", "pw": "", "has_pw": False, "saved_at": None, "viewport": None,
            "phone": "", "senders": "", "otp": {},       # 인증 휴대폰(phoneId)·발신번호(쉼표), otp = 단계 목록에서 바꾼 인증번호 칸 {sid: 켬/끔}
            "wait": {},         # 단계 목록에서 바꾼 'n초 대기' {sid: (켬, 글자)} (apply_waits)
            "mail_id": "", "mail_pw": "", "has_mail_pw": False,   # 메일 2차인증 메일함 계정 (설계 2026-11-02, 비밀번호는 저장하면 비우고 has_mail_pw)
            "source": "shop", "prefix": "",              # 주문 수집용 엑셀파일 경로 (shop 쇼핑몰 / mail 메일 첨부파일 / imap 메일 서버), 메일 시작 문구
            "market": "",       # 운송장 전송 마켓 (st.INVOICE_MARKETS 하나 - 프리셋 하나에 마켓 하나, 여러 프리셋이 같은 마켓은 된다. 사용자 2026-11-09)
            "upload": False,    # 사이트에 엑셀을 올리는 프리셋 (st.EXCEL_UPLOAD_ON 이 꺼져 있으면 무시 - is_up)
            "imap": None,       # 메일 서버(IMAP) 칸 {host, port, security, rules} - source 가 imap 일 때 (2026-10-22)
            "orig": None,       # 불러올 때의 번호 (새 칸은 None) - 프리셋을 지워 번호가 당겨지면 저장할 때 이 번호의 옛 값을 쓴다 (이슈 #13)
            "fresh": False}     # fresh = 이번에 기록하고 아직 저장 안 함 (닫을 때 묻고 내보내기를 막는다. 켬/끔은 저장해도 그대로 - 2026-11-03)


def is_up(p):
    return st.EXCEL_UPLOAD_ON and p["upload"]


def edit_view(presets):
    """닫을 때 '저장하지 않은 변경' 을 가르는 칸 값 - 사람이 고치는 것만 (2026-11-03: 비밀번호만 바꾸고 닫으면 묻지 않고 버렸다).
    기록이 없는 칸은 저장하지 않으니 뺀다. 비밀번호는 새로 친 글자가 있으면 바뀐 것. 단계 체크는 끈 것만 (켬은 그릴 때 채워진다).
    이름·사이트코드·메일 시작 문구는 _store_fields 와 같이 다듬어 견준다 - 고르기만 한 칸(옛 전각 코드 등)을 고친 것으로 보지 않게."""
    return [(p["name"].strip(), unicodedata.normalize("NFKC", p["code"]).strip(), p["id"], bool(p["pw"]), p["phone"], p["senders"],
             p["mail_id"], bool(p["mail_pw"]), p["source"], p["prefix"].strip(), repr(p["imap"]), sorted(p["deleted"]), sorted(p["otp"].items()),
             sorted(k for k, v in p["enabled"].items() if not v.get()), sorted(p["wait"].items()),
             p["market"])     # 운송장 전송 마켓만 고르고 닫으면 묻지 않고 버렸다 (2026-11-10)
            for p in presets if p["loaded"] or p["raw"] or p["head"]]


def apply_waits(steps, waits):
    """단계 목록에서 바꾼 'n초 대기' {sid: (켬, 글자)} 를 기록 단계의 wait_sec 으로. 켰고 0 이상의 정수일 때만 - 아니면 대기 없음 (사용자 2026-11-05)."""
    for s in steps:
        if s.get("id") in waits:
            on, text = waits[s["id"]]
            s.pop("wait_sec", None)
            if on and text.isdecimal():
                s["wait_sec"] = int(text)


def load_file_into(p, obj):
    """프리셋 파일(pt.check_file 을 지난 dict)을 화면 칸 p 에 넣는다 - 저장 전까지 새로 기록한 것과 같게 (fresh).
    사이트코드가 칸의 것과 다르면 아이디·비밀번호·인증 휴대폰을 비운다 (같으면 그대로). 같은 dict 를 돌려준다."""
    r = json.loads(json.dumps(obj["record"]))
    for k, s in enumerate(r["steps"]):
        s["id"] = k
    if obj["code"] != p["code"]:
        p.update(id="", pw="", has_pw=False, phone="", senders="", mail_id="", mail_pw="", has_mail_pw=False)
    pick = next((s["pick"] for s in r["steps"] if s.get("pick")), None)
    p.update(name=obj["name"], code=obj["code"], loaded=r, raw=[], head=None, start_url=None, viewport=r.get("viewport"),
             enabled={}, deleted=set(), otp={}, wait={}, fresh=True,
             source="mail" if pick else "shop", prefix=pick["prefix"] if pick else "", upload=bool(r.get("upload")))
    load_imap(p, r)
    return p


def load_imap(p, r):
    """기록이 메일 받기(imap 단계 하나)면 화면 칸 p 를 메일 서버 방식으로."""
    step = st.imap_step(r)
    if step:
        p.update(source="imap", imap={"host": step.get("host") or "", "port": step.get("port") or 993,
                                      "security": step.get("security") or "ssl", "rules": dict(step.get("rules") or {})})


def export_name(no, name):
    """내보내기 파일 이름 - 파일에 못 쓰는 글자는 _ 로."""
    return f"프리셋_{no}_{re.sub(r'[\\/:*?\"<>|]', '_', name)}.json"


def load_presets():
    """저장된 프리셋과 그 아이디 (비밀번호는 있는지만). 설정이나 프리셋 파일이 깨졌으면 ValueError - 덮어쓰지 않게 열지 않는다."""
    sites = st.read_user_config().get(st.SITES_SECTION) or {}
    out = []
    for p in st.read_presets():
        q = new_preset(p["no"], p["name"], p["code"])
        q["saved_at"], q["orig"], q["market"] = p["saved_at"], p["no"], p.get("market") or ""
        r = p["record"]
        if r and r.get("steps"):
            for k, s in enumerate(r["steps"]):
                s["id"] = k
            q["loaded"], q["viewport"], q["upload"] = r, r.get("viewport"), bool(r.get("upload"))
            pick = next((s["pick"] for s in r["steps"] if s.get("pick")), None)
            if pick:
                q["source"], q["prefix"] = "mail", pick["prefix"]
            load_imap(q, r)
        site = sites.get(st.preset_site_key(p["no"])) if isinstance(sites, dict) else None
        if isinstance(site, dict):
            if not st.login_mismatch(site, p["code"]):     # 다른 사이트의 계정이면 비워 둔다 - 다시 저장해도 잘못된 짝이 굳지 않게 (이슈 #13 검토)
                q["id"], q["has_pw"] = site.get("ID") or "", bool(site.get("PW"))
                q["mail_id"], q["has_mail_pw"] = site.get("MailID") or "", bool(site.get("MailPW"))
            q["phone"], q["senders"] = site.get("Phone") or "", ", ".join(site.get("SmsSenders") or [])
        out.append(q)
    return out


def senders_list(text):
    """'1588-1234, 02 123 4567, +82 90-258-0002' → ['15881234', '021234567', '0902580002'] (숫자만, +82 는 0 으로 - 휴대폰과 같은 꼴)."""
    return [d for d in (otp_relay.sender_number(x) for x in re.split(r"[,;/]+", text or "")) if d]


def has_otp(record):
    """휴대폰 문자 인증 단계가 있나 (메일에서 복사한 번호를 넣는 칸 source=copy 는 휴대폰이 필요 없다)."""
    return any(s.get("kind") == "otp" and s.get("source") != "copy" for s in (record or {}).get("steps") or [])


def has_mail_login(record):
    """메일 2차인증 메일함 로그인이 있나 - 저장 화면에 '인증 메일 아이디·비밀번호' 칸을 보인다. 다듬은 기록(finalize)이 메일 인증이 있을
    때만 메일함 칸을 MAIL_PW 로 둔다 - 사이트 둘에 로그인한 보통 기록은 아니다 (I1 경고로 알린다)."""
    return any(s.get("credential") == "MAIL_PW" for s in (record or {}).get("steps") or [])


def blank_imap(login_id=""):
    """메일 서버 칸의 처음 값 - 아이디가 잘 알려진 메일 주소면 서버를 채운다."""
    host, port, sec = mail_imap.guess_server(login_id) or ("", 993, "ssl")
    return {"host": host, "port": port, "security": sec, "rules": dict(mail_imap.DEFAULT_RULES)}


def imap_record(cfg):
    """메일 서버 칸 → 기록 (imap 단계 하나 - st.imap_step)."""
    step = {"id": 0, "kind": st.IMAP_KIND, "host": str(cfg["host"]).strip(), "port": cfg["port"], "security": cfg["security"],
            "rules": dict(cfg["rules"])}
    return {"version": st.RECORD_VERSION, "start_url": f"imap://{step['host']}", "steps": [step]}


def imap_problem(step):
    """메일 받기 단계의 문제 (사람에게 보일 글) 또는 None."""
    if not str(step.get("host") or "").strip():
        return "메일 서버 주소를 넣어 주십시오."
    port = step.get("port")
    if not (isinstance(port, int) and not isinstance(port, bool) and 0 < port < 65536):
        return "메일 서버 포트가 올바르지 않습니다."
    if step.get("security") not in ("ssl", "starttls"):
        return "보안 방식이 올바르지 않습니다."
    try:
        mail_imap.check_rules(step.get("rules") or {})
    except ValueError as e:
        return str(e)
    return None


def imap_warn(step):
    """메일 받기 조건의 경고 (막지 않고 보이기만 - 예: csv 첨부는 받기만 하고 업로드되지 않음). 없으면 빈 글자."""
    if not step:
        return ""
    try:
        return mail_imap.check_rules((step or {}).get("rules") or {}).get("warn") or ""
    except ValueError:
        return ""


def stored_password(no, key="PW"):
    """저장된 비밀번호 (미리보기·저장 전 확인용, 화면에는 안 보인다). 없으면 빈 글자. key="MailPW" 면 메일 2차인증 메일함 비밀번호."""
    site = (st.read_user_config().get(st.SITES_SECTION) or {}).get(st.preset_site_key(no)) or {}
    return st.unseal(site.get(key) or "") or ""


def saved_no(p, cur):
    """화면 cur 칸의 파일·저장된 비밀번호를 찾을 번호 = 불러올 때 번호(orig). 새 칸이거나, 프리셋을 지워 화면 번호가 당겨진 채
    아직 저장 전이면 None - 화면 번호로 찾으면 다른 프리셋의 것을 쓴다 (BugBuster H2)."""
    return p["orig"] if p["orig"] == cur + 1 else None


def scrub_login(record, login_id, mail_id=""):
    """아이디를 친 칸을 '설정의 아이디' 로 바꾸고 값을 지운다. 기록 때는 비밀번호 바로 앞 칸만 알아보므로 두 쪽 로그인
    (아이디 → 다음 → 비밀번호)·비밀번호 먼저 치기 등은 아이디가 글자로 남았다 (2026-10-01 검토). 같은 dict 를 돌려준다.
    mail_id: 메일 2차인증 메일함 창(MAIL_PW 가 있는 창)에서 친 메일 아이디는 '설정의 인증 메일 아이디' 로 (최종 검토 I4)."""
    login_id, mail_id = (login_id or "").strip(), (mail_id or "").strip()
    steps = (record or {}).get("steps", [])
    mail_pages = {s.get("page") for s in steps if s.get("credential") == "MAIL_PW"}
    for s in steps:
        if s.get("kind") != "fill" or s.get("credential"):
            continue
        v = (s.get("value") or "").strip()
        if mail_id and v == mail_id and s.get("page") in mail_pages:
            s["credential"] = "MAIL_ID"
            s.pop("value", None)
        elif login_id and v == login_id:
            s["credential"] = "ID"
            s.pop("value", None)
    return record


def password_in_record(record, pw):
    """비밀번호 칸이 아닌 곳에 비밀번호를 쳤나 - 사람이 친 값과 친 주소만 본다
    (파일 전체 글자로 보면 따옴표 든 비밀번호는 못 잡고, 짧은 비밀번호는 메뉴 이름·css 와 우연히 같아 저장이 막혔다)."""
    return bool(pw) and any(pw in str(s.get(k) or "") for s in (record or {}).get("steps", []) for k in ("value", "href"))


def keep_dates(files, old, logins_changed, now):
    """저장 날짜는 이번에 바뀐 프리셋만 now (이름·사이트코드·기록, 아이디·비밀번호), 그대로인 것은 원래 날짜.
    예전엔 저장할 때마다 모든 프리셋이 그날로 바뀌었다 (2026-10-01 검토). old: {번호: 예전 파일의 프리셋}. files 를 고쳐 돌려준다."""
    for f in files:
        o = old.get(f["no"]) or {}
        same = (f["record"] and f["no"] not in logins_changed and o.get("saved_at")
                and all(o.get(k) == f[k] for k in ("name", "code", "record")) and (o.get("market") or "") == (f.get("market") or ""))
        f["saved_at"] = o["saved_at"] if same else (now if f["record"] else None)
    return files


def store(files, logins, phones=None, origs=None, dropped=(), mail_logins=None):
    """프리셋 파일과 Sites 의 PRESETn 을 쓴다. 못 쓰면 화면에 보일 문장 (콘솔 없는 exe 라 조용히 넘어가면 안 된다), 되면 None.
    origs: {번호: 불러올 때 번호}·dropped: 지운 옛 번호 - 프리셋을 지워 번호가 당겨졌을 때 (이슈 #13) Sites 의 옛 값은 옛 번호에서 찾고,
    메일 기억·로그인 세션·보관 파일도 따라 옮긴다. 순서는 프리셋 → 설정 → 파일: 설정 쓰기가 실패해도 Sites 는 옛 번호 그대로라
    다시 저장하면 같은 옛 번호로 다시 찾는다 (반대 순서면 두 번 당겨진다)."""
    try:
        old_codes = {p["no"]: p["code"] for p in st.read_presets()}
    except (OSError, ValueError):
        old_codes = None                     # 옛 파일을 못 읽으면 메일 기억은 그대로 둔다
    try:
        st.write_presets(files)
        st.save_preset_sites(files, logins, phones=phones, origs=origs, mail_logins=mail_logins)
    except (OSError, ValueError, RuntimeError) as e:
        return f"저장하지 못했습니다. ({e}) 잠시 후 다시 저장하여 주십시오."
    pt.move_preset_files(origs or {}, dropped)
    for f in files if old_codes is not None else ():
        # 같은 칸에 다른 사이트(또는 새 칸)를 저장하면 옛 사이트의 메일 기억을 지운다 - 키가 겹쳐 새 메일을 건너뛰지 않게 (BugBuster K13)
        if f["record"] and old_codes.get(origs.get(f["no"]) if origs else f["no"]) != f["code"]:
            for path in (st.mail_memory_path(f["no"]), st.imap_memory_path(f["no"])):
                try:
                    os.remove(path)
                except OSError:
                    pass
    return None


def imap_overlap(out):
    """같은 메일함·같은 계정의 메일 서버 프리셋 둘의 조건이 겹치면 [(앞 번호, 뒤 번호)] - 한 메일을 두 사이트코드로 올릴 수 있다.
    받는 규칙은 바꾸지 않는다 (어느 프리셋 몫인지 가를 근거가 없다) - 저장 때 알리기만 (O12, 2026-11-03).
    제목 포함·제외 조건은 보지 않아 실제보다 넓게 알릴 수 있다."""
    seen, hits, n = [], [], mail_imap._norm
    for o in out:
        s = st.imap_step(o["record"])
        if not s:
            continue
        try:
            r = mail_imap.check_rules(s.get("rules"))
        except ValueError:
            continue                        # 조건이 틀린 것은 imap_warn·validate 가 따로 알린다
        key = ((s.get("host") or "").strip().lower(), o["id"].strip().lower(), r["mailbox"])
        mine = {n(x) for x in r["senders"]}
        for no, k, q, theirs in seen:
            pa, pb = n(r["subject_prefix"]), n(q["subject_prefix"])
            if k == key and (not mine or not theirs or mine & theirs) and (pa.startswith(pb) or pb.startswith(pa)):
                hits.append((no, o["no"]))
        seen.append((o["no"], key, r, mine))
    return hits


def pick_problem(presets):
    """메일 첨부파일 프리셋의 문제 (번호, 글) - 문구 없음 / 그 문구로 시작하는 메일을 연 단계 없음 / 그 아래 받기 단계 없음. 없으면 None."""
    for o in presets:
        steps = (o["record"] or {}).get("steps") or []
        if o.get("source") != "mail" or not steps:
            continue
        prefix = (o.get("prefix") or "").strip()
        if not prefix:
            return o["no"], "메일 시작 문구를 넣어 주십시오."
        i = next((k for k, x in enumerate(steps) if x.get("pick")), None)
        if i is None:
            return o["no"], (f"메일 시작 문구로 지정한 '{prefix}'(으)로 시작하는 메일을 찾지 못했습니다. "
                             f"'{prefix}'(으)로 시작하는 메일을 연 다음 첨부파일을 받는 것까지 기록해 주십시오.")
        if rec.pick_body(steps, i) is None:
            return o["no"], "메일 고르기 아래에 파일 받기 단계가 없습니다. 첨부를 받는 단계까지 기록해 주십시오."
    return None


def validate_presets(presets, need_market=False):
    """저장 전에 막을 것: (프리셋 번호, 사람에게 보일 문장) 또는 None.
    presets: [{no, name, code, id, pw, has_pw, record}] - 기록이 있는 것만 본다.
    need_market: '운송장 전송 마켓' 칸이 보이는 PC - 업로드 프리셋은 마켓을 골라야 저장된다 (사용자 2026-11-10)."""
    codes = {}
    for p in presets:
        if not p.get("record"):
            continue
        tag = f"{circled(p['no'])} {p['name']}"
        if not re.fullmatch(r"[0-9]{3}", p.get("code") or ""):       # \d 는 전각·다른 글자의 숫자도 받는다
            return p["no"], f"{tag}: 사이트코드는 숫자 세 자리여야 합니다 (받은 엑셀파일 이름 앞에 붙어, 엑셀 수집 모듈에서 자동으로 처리하게 됩니다.)"
        key = (p["code"], bool(p.get("upload")))      # 같은 사이트의 다운로드·업로드 프리셋은 코드가 같다 (사용자 2026-11-06)
        if key in codes:
            return p["no"], (f"{tag}: 사이트코드 {p['code']}을(를) {codes[key]}에서도 사용하고 있습니다. "
                             "다른 사이트코드를 입력하여 주십시오.")
        codes[key] = tag
        if p.get("upload") and not any(s["kind"] == "file" for s in p["record"].get("steps") or []):
            return p["no"], f"{tag}: 파일을 넣는 단계가 기록되지 않았습니다. 사이트의 파일 칸에 엑셀 파일을 넣는 것까지 기록하여 주십시오."
        if need_market and p.get("upload") and not p.get("market"):
            return p["no"], f"{tag}: 엑셀 업로드 프리셋은 운송장 전송 마켓을 선택하여 주십시오."
        step = st.imap_step(p["record"])
        if step and imap_problem(step):
            return p["no"], f"{tag}: {imap_problem(step)}"
        why = rec.mail_auth_problem(p["record"].get("steps") or [])     # 메일 2차인증 기록 규칙 (설계 2026-11-02 6절)
        if why:
            return p["no"], f"{tag}: {why}"
        if has_mail_login(p["record"]) and not ((p.get("mail_id") or "").strip() and (p.get("mail_pw") or p.get("has_mail_pw"))):
            return p["no"], f"{tag}: 인증 메일 계정이 입력되지 않았습니다. 인증 메일 아이디와 비밀번호를 입력하여 주십시오."
        if has_otp(p["record"]) and not (p.get("phone") and senders_list(p.get("senders"))):
            return p["no"], f"{tag}: 인증번호 단계가 있습니다. 인증 휴대폰과 발신번호를 정해 주십시오."
        if not (p.get("id") or "").strip():
            return p["no"], f"{tag}: 아이디가 필요합니다."
        if not (p.get("pw") or p.get("has_pw")):
            return p["no"], f"{tag}: 비밀번호가 필요합니다."
    return None


def button(parent, text, kind, command, **kw):
    return w.Btn(parent, text, kind, command, **kw)


def enable(b, on):
    b.config(state="normal" if on else "disabled")


def skin(b, text, kind, command):
    """같은 단추를 다른 일에 (미리보기 중에는 [▶ 미리보기]·[저장] 자리가 [Ⅱ 일시정지]·[■ 중단])."""
    b.config(text=text, command=command, kind=kind)


def tab_text(i, p):
    """프리셋 탭 글자 - 50개면 번호만으로는 못 찾는다. 긴 이름은 줄인다."""
    name = p["name"]
    return f"{circled(i + 1)} {name[:10] + '…' if len(name) > 11 else name}"


class App:
    def __init__(self, root, scale, presets, hint="", fake_creds=None):
        self.root, self.scale = root, scale
        w.init(scale)
        self.presets = presets
        self.max_presets = st.preset_limit()     # 업체 프리셋 수 (에이전트가 적은 업체 정책) - 켤 때 한 번
        if fake_creds and not any(p["loaded"] for p in self.presets):      # 시험: 가짜 쇼핑몰 계정
            self.presets[0].update(name="가짜 쇼핑몰", code="012", id=fake_creds[0], pw=fake_creds[1])
        self.cur, self.recording, self.previewing = 0, None, False
        self.unsaved_drop = False       # [−] 로 지우고 아직 저장 안 함 (닫을 때 묻는다)
        self.paused = self.stopping = self.closing = False      # 미리보기 [Ⅱ 일시정지]·[■ 중단]·일시정지 중 창 닫기
        self.failed_at, self.editing = None, False               # 미리보기가 못 찾아 멈춘 단계 (브라우저는 열린 채), [수정] 누름
        self.tell, self.ask = messagebox.showinfo, messagebox.askyesno     # 시험이 갈아 끼운다
        self.labels, self.base, self.shown, self._dock_job = {}, {}, 0, None
        self.start_url = None           # 시험: 주소를 치지 않고 바로 연다
        self.ui = queue.Queue()
        L, T, R, B = work_area()
        m = int(10 * scale)
        L, T, R, B = L + m, T + m, R - m, B - m
        self.panel_w = max(int((R - L) * 0.30), int(460 * scale))
        self.browser_w = (R - L) - self.panel_w
        root.title("옵저버")
        root.configure(bg=BG)
        root.geometry(f"{self.panel_w}x{B - T - int(32 * scale)}+{L + self.browser_w}+{T}")
        self.name_var, self.code_var = tk.StringVar(root), tk.StringVar(root)
        self.id_var, self.pw_var = tk.StringVar(root), tk.StringVar(root)
        self.mail_id_var, self.mail_pw_var = tk.StringVar(root), tk.StringVar(root)   # 메일 2차인증 메일함 계정
        self.senders_var, self.phones, self.phone_ids = tk.StringVar(root), None, [""]
        self.source_var, self.prefix_var = tk.StringVar(root, value="shop"), tk.StringVar(root)
        self._build()
        threading.Thread(target=self._load_phones, daemon=True).start()
        self._load_fields()
        self._store_fields()                    # 닫을 때와 같은 다듬기를 거친 값으로 견준다
        self.saved_view = edit_view(self.presets)
        root.update()
        self.worker = Worker(self.browser_bounds(), self.ui, hint)
        self.worker.start()
        root.bind("<Configure>", self._on_configure)
        root.protocol("WM_DELETE_WINDOW", self.quit)
        root.after(80, self._poll)
        self.started_at = st.now_iso()          # 켜기 전에 남은 닫기 요청은 보지 않는다
        self.close_seen, self.close_box = None, self._close_box     # 에이전트의 닫기 요청 (사용자 2026-11-10) - 시험이 메시지 창을 갈아 끼운다
        root.after(1000, self._watch_close)

    # --- 화면 ---
    def _entry(self, parent, var, width, show=""):
        return w.Field(parent, width=width, textvariable=var, show=show)

    def _build(self):
        root, s = self.root, self.scale
        narrow = self.panel_w < int(560 * s)             # 좁은 화면은 여백부터 줄인다 (설계 5절)
        pad, card_pad = int((14 if narrow else 20) * s), int((12 if narrow else 20) * s)
        head = tk.Frame(root, bg=BG)
        head.pack(fill="x", padx=pad, pady=(int(14 * s), int(8 * s)))
        tk.Label(head, text="사용자 행위 기록", font=(UI, 15, "bold"), bg=BG, fg=INK).pack(anchor="w")
        self.head_note = tk.Label(head, text=HEAD_DOWN, font=F_SMALL, bg=BG, fg=MUTED, anchor="w", justify="left", wraplength=self.panel_w - 2 * pad)
        self.head_note.pack(fill="x")

        # 프리셋: 탭 줄 + 프리셋마다 따로인 칸
        card = w.Card(root, card_pad)
        card.pack(fill="x", padx=pad)
        inner = card.inner
        head = tk.Frame(inner, bg=CARD)
        head.pack(fill="x")
        self.preset_tools = tk.Frame(head, bg=CARD)      # 탭이 스크롤돼도 오른쪽에 그대로
        self.preset_tools.pack(side="right", anchor="n")
        self.add_btn = w.Icon(self.preset_tools, "plus", self.add_preset, color=w.TEXT3)
        self.sub_btn = w.Icon(self.preset_tools, "minus", self.remove_preset, color=w.TEXT3)
        self.count_label = tk.Label(self.preset_tools, font=F_SMALL, bg=CARD, fg=w.TEXT3)
        self.count_label.pack(side="right", padx=(int(8 * s), int(6 * s)))
        self.tabs = w.Tabs(head, self.select)
        self.tabs.pack(side="left", fill="x", expand=True)
        tk.Frame(inner, bg=LINE, height=1).pack(fill="x", pady=(0, int(10 * s)))
        top = tk.Frame(inner, bg=CARD)           # 어느 폭에서나 남는 줄 - 경로 줄에 두면 FHD 에서 [프리셋 삭제] 가 '메일 서버' 를 가린다 (사용자 2026-11-06)
        top.pack(fill="x", pady=(0, int(10 * s)))
        top.columnconfigure(3, weight=1)
        self.del_btn = button(top, "프리셋 삭제", "danger_ghost", self.remove_preset, h=26, pad=9, font=F_SMALL)
        self.del_btn.grid(row=0, column=3, sticky="e")
        if st.EXCEL_UPLOAD_ON:
            self.down_label = tk.Label(top, text="엑셀 다운로드", font=F, bg=CARD)
            self.down_label.grid(row=0, column=0, sticky="w")
            top.columnconfigure(0, minsize=w._font_of(top, F_BOLD).measure("엑셀 다운로드") + 2)    # 글자가 굵어져도 스위치가 밀리지 않게
            self.switch = w.Switch(top, self._switch)
            self.switch.grid(row=0, column=1, padx=8)
            self.up_label = tk.Label(top, text="엑셀 업로드", font=F, bg=CARD)
            self.up_label.grid(row=0, column=2, sticky="w")
        form = tk.Frame(inner, bg=CARD)          # 프리셋마다 따로인 칸은 모두 여기 (아이디·비밀번호도 - 2026-10-02)
        form.pack(fill="x")
        for r, (left, lvar, right, rvar, show) in enumerate((("이름", self.name_var, "사이트코드", self.code_var, ""),
                                                             ("아이디", self.id_var, "비밀번호", self.pw_var, "•"))):
            y = (3 if r else 0, 0)
            tk.Label(form, text=left, font=F, bg=CARD, fg=MUTED).grid(row=r, column=0, sticky="w", pady=y)
            self._entry(form, lvar, 12).grid(row=r, column=1, sticky="we", padx=(6, 0), pady=y)
            tk.Label(form, text=right, font=F, bg=CARD, fg=MUTED).grid(row=r, column=2, sticky="w", padx=(12, 0), pady=y)
            self._entry(form, rvar, 12, show=show).grid(row=r, column=3, sticky="we", padx=(6, 0), pady=y)
        tk.Label(form, text="인증 휴대폰", font=F, bg=CARD, fg=MUTED).grid(row=2, column=0, sticky="w", pady=(3, 0))
        self.phone_box = w.Select(form, values=["(없음)"])
        self.phone_box.grid(row=2, column=1, sticky="we", padx=(6, 0), pady=(3, 0))
        self.phone_box.bind("<<ComboboxSelected>>", lambda e: self._field_changed())
        tk.Label(form, text="발신번호", font=F, bg=CARD, fg=MUTED).grid(row=2, column=2, sticky="w", padx=(12, 0), pady=(3, 0))
        self._entry(form, self.senders_var, 12).grid(row=2, column=3, sticky="we", padx=(6, 0), pady=(3, 0))
        self.senders_var.trace_add("write", lambda *a: self._field_changed())
        src = tk.Frame(form, bg=CARD)               # 주문 수집용 엑셀파일 경로 (사용자 2026-10-14)
        src.grid(row=3, column=0, columnspan=4, sticky="we", pady=(8, 0))
        self.src_row = src
        if st.EXCEL_UPLOAD_ON:                      # 같은 칸에 겹쳐 두고 앞뒤만 바꾼다 - 높이가 안 변한다
            self.up_note = tk.Label(form, font=F_SMALL, bg=CARD, fg=MUTED, anchor="w", justify="left",
                                    wraplength=self.panel_w - 2 * (pad + card_pad))
            self.up_note.grid(row=3, column=0, columnspan=4, sticky="nsew", pady=(8, 0))
            self.code_var.trace_add("write", lambda *a: self._paint_direction())
        tk.Label(src, text="주문 수집용 엑셀파일 경로", font=F, bg=CARD, fg=MUTED).pack(side="top" if narrow else "left", anchor="w")
        picks = tk.Frame(src, bg=CARD)              # 좁은 창에서는 다음 줄로
        picks.pack(side="top" if narrow else "left", anchor="w", pady=(4, 0) if narrow else 0)
        for k, (value, label) in enumerate((("shop", "쇼핑몰"), ("mail", "메일 첨부파일"), ("imap", "메일 서버"))):
            w.Radio(picks, label, value, self.source_var, self._source_changed).pack(side="left", padx=(12 if k or not narrow else 0, 0))
        # 메일 2차인증 (설계 2026-11-02): 기록에 메일함 로그인이 있을 때만 보인다 (_show_mail)
        self.mail_widgets = [tk.Label(form, text="인증 메일 아이디", font=F, bg=CARD, fg=MUTED), self._entry(form, self.mail_id_var, 12),
                             tk.Label(form, text="인증 메일 비밀번호", font=F, bg=CARD, fg=MUTED), self._entry(form, self.mail_pw_var, 12, show="•"),
                             tk.Label(form, text=MAIL_ACCOUNT_HINT, font=F_SMALL, bg=CARD, fg=MUTED, anchor="w", justify="left",
                                      wraplength=self.panel_w - 2 * (pad + card_pad))]
        self.prefix_label = tk.Label(form, text="메일 시작 문구", font=F, bg=CARD, fg=MUTED)
        self.prefix_entry = self._entry(form, self.prefix_var, 12)
        self.prefix_var.trace_add("write", lambda *a: self._field_changed())
        # 운송장 전송 마켓 (사용자 2026-11-09): 운송장번호 전송이 켜진 PC 에만 보인다 (켤 때 한 번 본다). 꺼져 있어도 고른 값은 그대로 둔다
        self.market_box = w.Select(form, values=[MARKET_NONE, *st.INVOICE_MARKETS])
        self.market_box.bind("<<ComboboxSelected>>", lambda e: self._market_changed())
        if st.invoice_send_on():
            tk.Label(form, text="운송장 전송 마켓", font=F, bg=CARD, fg=MUTED).grid(row=7, column=0, sticky="w", pady=(3, 0))
            self.market_box.grid(row=7, column=1, sticky="we", padx=(6, 0), pady=(3, 0))
        form.columnconfigure(0, minsize=self.prefix_label.winfo_reqwidth())    # '메일 시작 문구' 가 나타나도 칸이 옆으로 밀리지 않게 (사용자 2026-10-20)
        for col in (1, 3):              # 왼쪽(이름·아이디·인증 휴대폰)·오른쪽(사이트코드·비밀번호·발신번호) 칸을 같은 너비로 (사용자 2026-10-13)
            form.columnconfigure(col, weight=1, uniform="field")
        self.pw_hint = tk.Label(inner, text="", font=F_SMALL, bg=CARD, fg=w.TEXT3, anchor="w", justify="left",
                                wraplength=self.panel_w - 2 * (pad + card_pad))
        self.pw_hint.pack(fill="x", pady=(6, 0))
        self.name_var.trace_add("write", lambda *a: self._field_changed())
        self.code_var.trace_add("write", lambda *a: self._field_changed())

        # 안내 한 줄 (기록·미리보기·저장 모두 여기 - 두 곳이면 지난 일이 남는다, 2026-10-02) + 기록 단추
        bar = tk.Frame(root, bg=BG)
        bar.pack(fill="x", padx=pad, pady=int(8 * s))
        self.rec_btn = button(bar, "●  기록 시작", "primary", self.toggle_record)
        self.rec_btn.pack(side="right")
        self.status = w.Status(bar, text="브라우저 준비 중…", font=F, bg=BG, fg=MUTED, anchor="w", justify="left",
                               wraplength=self.panel_w - int(190 * s))
        self.status.pack(side="left", fill="x", expand=True)

        # 단추 (목록보다 먼저 붙여 목록이 남는 자리를 쓴다)
        btns = tk.Frame(root, bg=BG)
        btns.pack(side="bottom", fill="x", padx=pad, pady=(int(8 * s), int(14 * s)))
        self.save_btn = button(btns, "저장", "primary", self.save, width=8)
        self.save_btn.pack(side="right")
        self.prev_btn = button(btns, "▶  미리보기", "default", self.preview, width=12)
        self.prev_btn.pack(side="right", padx=8)
        self.edit_btn = button(btns, "수정", "default", self.edit_preview, width=8)      # 미리보기가 멈춰 있을 때만 보인다
        self.import_btn, self.export_btn = (w.Link(btns, t, c) for t, c in (("파일에서 불러오기", self.import_file), ("파일로 내보내기", self.export_file)))
        self.import_btn.pack(side="left")
        self.export_btn.pack(side="left", padx=(int(12 * s), 0))

        # 기록 목록
        mid = w.Card(root, int(14 * s), fill=True)
        mid.pack(fill="both", expand=True, padx=pad)
        self.list_title = tk.Label(mid.inner, text="", font=F_BOLD, bg=CARD, fg=INK, anchor="w")
        self.list_title.pack(fill="x", pady=(0, int(2 * s)))
        self.col_head = tk.Frame(mid.inner, bg=CARD, height=w.px(20))     # 칸 이름 - 스크롤해도 그대로, 자리는 첫 줄에 맞춘다 (_align_columns)
        self.col_head.pack_propagate(False)
        self.col_head.pack(fill="x", pady=int(4 * s))
        self.col_names = {t: tk.Label(self.col_head, text=t, font=F_SMALL, bg=CARD, fg=w.TEXT3) for t in ("실행", "단계", "설명", "대기", "삭제")}
        self.col_head.bind("<Configure>", lambda e: self._align_columns())
        self.col_refs = None
        tk.Frame(mid.inner, bg=LINE, height=1).pack(fill="x")
        body = tk.Frame(mid.inner, bg=CARD)
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(body, highlightthickness=0, bg=CARD)
        sb = w.Bar(body, "vertical", self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=CARD)
        self.win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.win, width=e.width))
        self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))

    def paint_presets(self):
        busy = self.recording is not None or self.previewing
        self.tabs.show([(tab_text(i, p), bool(p["raw"] or p["loaded"]), is_up(p)) for i, p in enumerate(self.presets)], self.cur, self.recording, busy)
        enable(self.del_btn, len(self.presets) > MIN_PRESETS and not busy)
        self.sub_btn.set_state("normal" if len(self.presets) > MIN_PRESETS and not busy else "disabled")
        self.count_label.config(text=f"{len(self.presets)}/{self.max_presets}")
        if len(self.presets) < self.max_presets:
            self.add_btn.pack(side="right", before=self.count_label)
            self.add_btn.set_state("disabled" if busy else "normal")
        else:
            self.add_btn.pack_forget()
        self.sub_btn.pack(side="right", padx=(0, int(6 * self.scale)), before=self.count_label)

    def paint_buttons(self):
        rec_on = self.recording is not None
        self.rec_btn.config(text="■  기록 완료" if rec_on else "●  기록 시작", kind="danger" if rec_on else "primary")
        imap = self.presets[self.cur]["source"] == "imap"     # 메일 서버 - 기록·미리보기 대신 [찾아보기]
        enable(self.rec_btn, not self.previewing and (not rec_on or self.recording == self.cur) and not (imap and not rec_on))
        if self.previewing:         # 창을 닫는 대신 멈추는 단추 (2026-10-02 - 미리보기 중에는 창이 안 닫힌다)
            idle = not (self.stopping or self.closing or self.editing)
            skin(self.prev_btn, "▶  계속" if self.paused else "Ⅱ  일시정지", "default", self.toggle_pause)
            skin(self.save_btn, "■  중단", "danger", self.stop_preview)
            enable(self.prev_btn, idle and self.failed_at is None)      # 못 찾아 멈춘 자리에서는 이어 갈 수 없다
            enable(self.save_btn, not (self.stopping or self.closing))  # [수정] 뒤 기다리는 동안(파일 받기 최대 5분)에도 멈출 수 있게
            if self.paused or self.failed_at is not None:               # 멈춰 있을 때만 [수정] (설계 2026-10-19 4.2절)
                self.edit_btn.pack(side="right", padx=(0, 8))
                enable(self.edit_btn, idle)
            else:
                self.edit_btn.pack_forget()
        else:
            self.edit_btn.pack_forget()
            kept = not rec_on and self._has_kept(self.presets[self.cur])
            skin(self.prev_btn, "▶  미리보기", "default", self.preview)
            skin(self.save_btn, "저장", "primary", self.save)
            enable(self.prev_btn, kept and not imap)
            enable(self.save_btn, kept)     # 기록이 끝나 있고 켜 둔 단계가 한 줄은 있어야 (2026-10-02)
        for b in (self.import_btn, self.export_btn):
            b.config(state="disabled" if rec_on or self.previewing else "normal", cursor="arrow" if rec_on or self.previewing else "hand2")
        self.paint_presets()

    def _switch(self, on):
        """[엑셀 다운로드 / 업로드] 스위치. 글자·탭·안내를 한 번에 바꾼 뒤 손잡이가 움직인다."""
        p = self.presets[self.cur]
        if self.recording is not None or self.previewing:
            return
        if on and p["source"] != "shop":
            return self.status.config(text="쇼핑몰 기록만 업로드 프리셋으로 사용할 수 있습니다.", fg=RED)
        p["upload"] = on
        w.at_once(self.root, lambda: (self._paint_direction(), self.paint_presets()))
        self.switch.set(on, animate=True)

    def _paint_direction(self):
        if not st.EXCEL_UPLOAD_ON:
            return
        on = self.presets[self.cur]["upload"]
        self.down_label.config(fg=MUTED if on else INK, font=F if on else F_BOLD)
        self.up_label.config(fg=INK if on else MUTED, font=F_BOLD if on else F)
        self.head_note.config(text=HEAD_UP if on else HEAD_DOWN)
        self.up_note.config(text=f"올릴 파일: 바탕화면\\ERPIA_AI\\{st.UPLOAD_DIR_NAME} 폴더의 ({self.code_var.get() or '사이트코드'})로 시작하는 파일")
        (self.up_note if on else self.src_row).tkraise()

    def _market_changed(self):
        v = self.market_box.get()
        self.presets[self.cur]["market"] = "" if v == MARKET_NONE else v

    def _load_fields(self):
        p = self.presets[self.cur]
        self.market_box.current(st.INVOICE_MARKETS.index(p["market"]) + 1 if p["market"] in st.INVOICE_MARKETS else 0)
        if st.EXCEL_UPLOAD_ON:
            self.switch.set(p["upload"])
        self._loading = True
        self.name_var.set(p["name"])
        self.code_var.set(p["code"])
        self.id_var.set(p["id"])
        self.pw_var.set(p["pw"])
        self.mail_id_var.set(p["mail_id"])
        self.mail_pw_var.set(p["mail_pw"])
        self.senders_var.set(p["senders"])
        self.source_var.set(p["source"])
        self.prefix_var.set(p["prefix"])
        self._fill_phone_box()
        self._loading = False
        self._show_prefix()
        self.pw_hint.config(text=("저장된 비밀번호가 있습니다. " if p["has_pw"] else "")
                            + "아이디·비밀번호는 암호화하여 이 PC 설정에 저장합니다. 사이트 로그인 외 다른 용도로 사용하지 않습니다.\n"
                            + (IMAP_HINT if p["source"] == "imap" else
                               "문자 인증번호를 받는 사이트면 인증 휴대폰과 발신번호(여러 개면 쉼표로)를 정해 주십시오.")
                            + ("\n" + MAIL_HINT if p["source"] == "mail" else "")
                            + (" (휴대폰 목록을 불러오지 못했습니다)" if self.phones == [] and getattr(self, "phones_failed", False) else ""))

    def _load_phones(self):
        """업체 휴대폰 목록 (관리 화면 '휴대폰 추가') - 에이전트 계정으로. 못 읽으면 빈 목록 (저장된 값은 그대로 보인다)."""
        try:
            self.ui.put(("phones", otp_relay.phone_list()))
        except Exception:
            self.ui.put(("phones", None))

    def _fill_phone_box(self):
        p = self.presets[self.cur]
        pairs = list(self.phones or [])
        if p["phone"] and p["phone"] not in [k for k, _ in pairs]:
            pairs.append((p["phone"], p["phone"]))         # 목록에 없는 (못 불러온·지운) 휴대폰도 저장된 값은 보인다
        self.phone_ids = [""] + [k for k, _ in pairs]
        self.phone_box.config(values=["(없음)"] + [label for _, label in pairs])
        self.phone_box.current(self.phone_ids.index(p["phone"]) if p["phone"] in self.phone_ids else 0)

    def _store_fields(self):
        p = self.presets[self.cur]
        i = self.phone_box.current()
        source, prefix = self.source_var.get(), self.prefix_var.get().strip()
        p.update(name=self.name_var.get().strip() or p["name"],
                 code=unicodedata.normalize("NFKC", self.code_var.get()).strip(),     # 전각 '１０１' → '101' (ERPia 사이트코드와 맞게, 2026-10-22)
                 id=self.id_var.get(), pw=self.pw_var.get(), senders=self.senders_var.get(),
                 mail_id=self.mail_id_var.get(), mail_pw=self.mail_pw_var.get(),
                 phone=self.phone_ids[i] if 0 <= i < len(self.phone_ids) else p["phone"], source=source, prefix=prefix)

    def _field_changed(self):
        if not getattr(self, "_loading", False) and hasattr(self, "list_title"):
            p = self.presets[self.cur]
            before = (p["source"], p["prefix"])
            self._store_fields()
            self._title()
            self.paint_presets()                    # 탭에 이름이 보인다
            guess = p["source"] == "imap" and p["imap"] and not p["imap"]["host"] and mail_imap.guess_server(p["id"].strip())
            if guess:                               # 메일 주소를 아이디로 넣으면 서버 칸을 채운다
                p["imap"].update(host=guess[0], port=guess[1], security=guess[2])
            if (p["source"], p["prefix"]) != before or guess:
                self.render()                       # '메일마다' 단계가 바뀐다

    def _show_mail(self, record):
        """기록에 메일함 로그인이 있으면 '인증 메일 아이디·비밀번호' 칸과 안내를 보인다 (5·6번째 줄)."""
        if has_mail_login(record):
            for k, x in enumerate(self.mail_widgets[:4]):
                x.grid(row=5, column=k, sticky="w" if k % 2 == 0 else "we", padx=(12 if k == 2 else 6 if k else 0, 0), pady=(3, 0))
            self.mail_widgets[4].grid(row=6, column=0, columnspan=4, sticky="we", pady=(2, 0))
        else:
            for x in self.mail_widgets:
                x.grid_remove()

    def _show_prefix(self):
        """메일 첨부파일일 때만 '메일 시작 문구' 칸 (쇼핑몰이면 감춘다)."""
        if self.source_var.get() == "mail":
            self.prefix_label.grid(row=4, column=0, sticky="w", pady=(3, 0))
            self.prefix_entry.grid(row=4, column=1, sticky="we", padx=(6, 0), pady=(3, 0))
        else:
            self.prefix_label.grid_remove()
            self.prefix_entry.grid_remove()

    def _source_changed(self):
        """라디오: 메일 첨부파일로 처음 바꾸면 시작 문구는 '>>>' 부터. 메일 서버로 바꾸면 기록한 단계 대신 서버·조건 칸 -
        기록이 있으면 묻는다 (저장하면 기록이 메일 받기로 바뀐다)."""
        p = self.presets[self.cur]
        if self.source_var.get() == "imap" and p["source"] != "imap":
            if (p["raw"] or p["head"] or (p["loaded"] and not st.imap_step(p["loaded"]))) and not self.ask(
                    "메일 서버", f"{circled(self.cur + 1)} {p['name']}을(를) 기록한 단계 대신 메일 서버에서 받도록 바꿉니다. "
                    "저장하면 기록한 단계는 삭제됩니다. 진행하시겠습니까?"):
                self.source_var.set(p["source"])
                return
            p["imap"] = p["imap"] or blank_imap(self.id_var.get().strip())
        w.at_once(self.root, self._show_source)     # 묻는 창은 위에서 - 그동안 화면이 멈춰 있지 않게 (사용자 2026-11-09)

    def _show_source(self):
        """수집 경로에 맞춰 칸·단계 목록을 바꾼다 - 한 번에 그린다 (_source_changed)."""
        if self.source_var.get() == "mail" and not self.prefix_var.get().strip():
            self._loading = True
            self.prefix_var.set(rec.MAIL_PICK_DEFAULT)
            self._loading = False
        self._field_changed()
        self._load_fields()                 # 칸 보이기·안내 줄

    def _title(self):
        p = self.presets[self.cur]
        self.list_title.config(text=f"{circled(self.cur + 1)} {p['name']} - " + ("메일 받기 조건" if p["source"] == "imap" else "기록한 단계"))

    def select(self, i):
        if i == self.cur:
            return
        self._store_fields()
        self.cur, self.shown = i, 0
        w.at_once(self.root, self._show_preset)     # 칸·탭·목록이 하나씩 바뀌어 보이지 않게 한 번에 (사용자 2026-11-09)

    def _show_preset(self):
        self._load_fields()
        self.status.config(text="")         # 다른 프리셋의 일을 말하는 글은 지운다
        self.render()

    def add_preset(self):
        self._store_fields()
        self.presets.append(new_preset(len(self.presets) + 1))
        self.select(len(self.presets) - 1)

    def remove_preset(self):
        """고른 프리셋 하나를 지우고 뒤 번호를 당긴다 (이슈 #13). 파일·설정은 [저장] 때 바뀐다 (save - orig 로 옛 값을 찾는다)."""
        if len(self.presets) <= MIN_PRESETS:
            return
        p = self.presets[self.cur]
        if (p["raw"] or p["loaded"] or p["head"]) and not self.ask(
                "프리셋 삭제", f"{circled(self.cur + 1)} {p['name']}에 기록이 있습니다. 프리셋을 삭제하시겠습니까?"):
            return
        self.presets.pop(self.cur)
        self.unsaved_drop = True
        self.cur, self.shown = min(self.cur, len(self.presets) - 1), 0
        w.at_once(self.root, self._show_preset)

    # --- 기록 목록 ---
    def _final(self, p):
        if p["source"] == "imap":                 # 메일 서버 - 기록 대신 imap 단계 하나 (2026-10-22)
            return imap_record(p["imap"] or blank_imap(p["id"]))
        if p["head"]:                            # [수정] - 남긴 앞부분 뒤에 이어 기록한 단계 (설계 2026-10-19 4.2절)
            final = rec.continue_record(p["head"], json.loads(json.dumps(p["raw"])), datetime.date.today())
        elif p["raw"]:
            start = p["start_url"] or next((s["href"] for s in p["raw"] if s["kind"] == "goto"), "")
            final = rec.finalize(json.loads(json.dumps(p["raw"])), datetime.date.today(), start, viewport=p["viewport"])
        else:
            final = None if st.imap_step(p["loaded"]) else p["loaded"]     # 메일 서버에서 쇼핑몰로 바꾼 칸 - 기록이 없다
        for sid, on in p["otp"].items():          # 단계 목록에서 바꾼 인증번호 칸 (기록이 못 알아본 것·잘못 알아본 것)
            i = next((k for k, s in enumerate(final["steps"]) if s["id"] == sid), None) if final else None
            if i is not None and (final["steps"][i]["kind"] == "otp") != on:
                rec.set_otp(final["steps"], i, on)
        if final:
            apply_waits(final["steps"], p["wait"])
        if final:                                 # 메일 첨부파일 - 메일 시작 문구로 '메일마다' 단계를 스스로 찾는다 (사용자 2026-10-14)
            for k in range(len(final["steps"])):
                rec.set_pick(final["steps"], k, None)
            i = rec.auto_pick(final["steps"], p["prefix"]) if p["source"] == "mail" else None
            if i is not None:
                rec.set_pick(final["steps"], i, p["prefix"])
        return final

    def toggle_otp(self, sid, on):
        self.presets[self.cur]["otp"][sid] = on
        self.render()

    SAVE_FIRST = "저장한 뒤에 해 주십시오."

    def clear_mail_memory(self):
        """[받은 메일 기억 지우기]: 다음 실행 때 메일함의 맞는 메일을 다시 받는다."""
        no = saved_no(self.presets[self.cur], self.cur)
        if no is None:
            return self.status.config(text=self.SAVE_FIRST, fg=RED)
        mem = rec.MailMemory(st.mail_memory_path(no))
        if not self.ask("받은 메일 기억 지우기", f"이 프리셋의 메일 처리 기록({len(mem.keys)}통)을 삭제합니다. "
                        "다음 실행 때 메일함에서 조건에 맞는 메일을 다시 다운로드합니다. 삭제하시겠습니까?"):
            return
        mem.clear()
        self.status.config(text="받은 메일 기억을 지웠습니다.", fg=GREEN_D)

    def _var(self, p, sid):
        return p["enabled"].setdefault(sid, tk.BooleanVar(self.root, value=True))

    def _kept(self, p, final):
        return [i for i, s in enumerate(final["steps"]) if s["id"] not in p["deleted"] and self._var(p, s["id"]).get()]

    def _has_kept(self, p):
        final = self._final(p)
        return bool(final) and bool(self._kept(p, final))

    def render(self):
        for c in self.inner.winfo_children():
            c.destroy()
        self.labels, self.base, self.wait_vars = {}, {}, []
        p = self.presets[self.cur]
        self.rows, self.col_refs = {}, None
        if p["source"] == "imap":
            self.col_head.pack_forget()
            self._show_mail(None)
            self._render_imap(p)
            self._title()
            self.paint_buttons()
            return
        self.col_head.pack(fill="x", pady=int(4 * self.scale), after=self.list_title)
        final = self._final(p)
        self._show_mail(final)
        n, body = 0, set()
        for k, s in enumerate(final["steps"] if final else []):
            end = rec.pick_body(final["steps"], k) if s.get("pick") else None
            body |= set(range(k + 1, end + 1)) if end is not None else set()
        last = max((k for k, s in enumerate(final["steps"] if final else []) if s["id"] not in p["deleted"]), default=None)
        for k, s in enumerate(final["steps"] if final else []):
            sid = s["id"]
            if sid in p["deleted"]:
                continue
            n += 1
            var = self._var(p, sid)
            on = var.get()
            row = tk.Frame(self.inner, bg=CARD)
            row.pack(fill="x", pady=(int(4 * self.scale) if n == 1 else 0, 0))
            chk = w.Check(row, variable=var, command=lambda sid=sid: self._check_changed(sid))
            chk.pack(side="left", anchor="n", padx=(4, 10), pady=10)
            del_x = w.Icon(row, "x", lambda sid=sid: self.delete(sid), hover=w.DANGER)
            del_x.pack(side="right", anchor="n", padx=(8, 4), pady=11)
            wait_on, wait_unit = self._wait_box(row, p, s)
            if s["kind"] in ("fill", "otp"):        # 글자 칸 - 문자로 받는 인증번호 칸인지 사람이 바꿀 수 있다
                is_otp = s["kind"] == "otp"
                w.Link(row, "인증번호 칸 해제" if is_otp else "인증번호 칸", lambda sid=sid, on=not is_otp: self.toggle_otp(sid, on),
                       fg=BLUE if is_otp else MUTED).pack(side="right", anchor="n", padx=2, pady=9)
            dot = w.StepDot(row, n, "idle" if on else "off", n == 1, k == last)
            dot.pack(side="left", fill="y")
            cell = tk.Frame(row, bg=CARD)
            cell.pack(side="left", fill="x", expand=True, padx=(10, 8), pady=8)
            text = ("↳ " if k in body else "") + re.sub(r" \(\d+단계 뒤에 새로 생긴 것\)", " (새로 생긴 것)", rec.describe(s))
            warn = s["kind"] == "goto" and "로그인 세션 값을 감지" in text
            lab = tk.Label(cell, text=text, font=F_BOLD, bg=CARD, anchor="w", justify="left",
                           fg=(RED_D if warn else w.STEP_INK) if on else w.STEP_MUTE,
                           wraplength=self.panel_w - int(330 * self.scale))
            lab.pack(fill="x")
            why = tk.Label(cell, font=F_SMALL, bg=CARD, fg=RED, anchor="w", justify="left")     # 실패 사유 (_progress)

            def fit(e, lab=lab, why=why):        # 오른쪽 칸을 뺀 폭 - [인증번호 칸] 이 있는 줄·좁은 창에서 글이 잘리지 않게
                lab.config(wraplength=e.width)
                why.config(wraplength=e.width)
            lab.bind("<Configure>", fit)
            w.hover_row(row, lab, why)
            self.labels[sid], self.base[sid] = lab, text
            self.rows[sid] = {"dot": dot, "lab": lab, "why": why, "row": row, "warn": warn}
            self.col_refs = self.col_refs or (chk, dot, cell, wait_on, wait_unit, del_x)
        if final and any(s.get("pick") for s in final["steps"]):
            w.Link(self.inner, "받은 메일 기억 지우기", self.clear_mail_memory, fg=MUTED).pack(anchor="e", padx=8, pady=6)
        if not n:
            tip = ("[● 기록 시작] 을 누르고 쇼핑몰 사이트 주소를 입력하는 것부터 시작해주세요.\n"
                   "모두 완료하였다면 [■ 기록 완료] 버튼을 누른 다음 저장해주세요.") if self.recording is None else \
                "주소 표시줄에 쇼핑몰 주소를 입력해주십시오."
            tk.Label(self.inner, text=tip, font=F, bg=CARD, fg=MUTED, justify="left", anchor="w",
                     wraplength=self.panel_w - int(90 * self.scale)).pack(fill="x", padx=14, pady=14)
        self._title()
        self.canvas.update_idletasks()
        self._align_columns()
        if self.recording is not None and n > self.shown:
            self.canvas.yview_moveto(1.0)       # 기록 중 새 단계가 생기면 맨 아래로
        elif not self.shown:                    # 처음 켤 때·프리셋을 바꿀 때·파일을 불러올 때는 맨 위부터 (업체 미팅 2026-11-11 -
            self.canvas.yview_moveto(0.0)       # 전에는 shown 이 0 이라 '새 단계' 로 보고 맨 아래로 내려갔다)
        self.shown = n
        self.paint_buttons()

    def _align_columns(self):
        """칸 이름을 첫 줄의 칸 자리에 맞춘다. 줄이 없으면 숨긴다."""
        names, refs = self.col_names, self.col_refs
        if not refs or not refs[0].winfo_exists():
            for x in names.values():
                x.place_forget()
            return
        chk, dot, cell, wait_on, wait_unit, del_x = refs
        base = self.col_head.winfo_rootx()
        left = lambda x: x.winfo_rootx() - base                      # noqa: E731
        mid = lambda x: left(x) + x.winfo_width() // 2                # noqa: E731
        names["실행"].place(x=max(mid(chk), w.px(14)), y=0, anchor="n")
        names["단계"].place(x=mid(dot), y=0, anchor="n")
        names["설명"].place(x=left(cell), y=0, anchor="nw")
        names["대기"].place(x=(left(wait_on) + left(wait_unit) + wait_unit.winfo_width()) // 2, y=0, anchor="n")
        names["삭제"].place(x=mid(del_x), y=0, anchor="n")

    def _check_changed(self, sid):
        """단계 체크: 그 줄만 고친다 - 목록을 다시 만들면 반짝인다. 미리보기 중에는 지금 도는 내용이 그대로라 표시도 그대로."""
        r = self.rows[sid]
        on = self._var(self.presets[self.cur], sid).get()
        if not self.previewing:
            r["dot"].set_state("idle" if on else "off")
            r["lab"].config(fg=(RED_D if r["warn"] else w.STEP_INK) if on else w.STEP_MUTE)
        self.paint_buttons()

    def _wait_box(self, row, p, s):
        """단계 줄 오른쪽의 [ ] [  ] 초 대기 (사용자 2026-11-05). 고쳐도 다시 그리지 않는다 - 치는 중인 칸을 잃지 않게.
        (체크, '초' 글자) 를 돌려준다 - 칸 이름 자리를 맞춘다."""
        sid = s["id"]
        on, text = p["wait"].get(sid, ("wait_sec" in s, str(s.get("wait_sec", ""))))
        on_var, text_var = tk.BooleanVar(self.root, value=on), tk.StringVar(self.root, value=text)
        self.wait_vars.append((on_var, text_var))
        unit = tk.Label(row, text="초", font=F_SMALL, bg=CARD, fg=w.TEXT3)      # 칸 이름에 '대기' 가 있다
        unit.pack(side="right", anchor="n", pady=9)
        w.Field(row, width=3, h=24, font=F_SMALL, textvariable=text_var, justify="right", validate="key",
                validatecommand=(row.register(lambda t: not t or t.isdecimal()), "%P")).pack(side="right", anchor="n", padx=(0, 2), pady=6)
        box = w.Check(row, variable=on_var)
        box.pack(side="right", anchor="n", padx=(0, 2), pady=10)

        def changed(*_):
            p["wait"][sid] = (on_var.get(), text_var.get())
        on_var.trace_add("write", changed)
        text_var.trace_add("write", changed)
        return box, unit

    def delete(self, sid):
        self.presets[self.cur]["deleted"].add(sid)
        self.render()

    # --- 메일 서버(IMAP) ---
    IMAP_TEXT = (("서버 주소", "host"), ("포트", "port"), ("메일함", "mailbox"), ("보낸 사람", "senders"), ("제목 시작 글자", "subject_prefix"),
                 ("제목에 들어갈 말", "subject_has"), ("제목에서 뺄 말", "subject_not"), ("처음 받을 때 최근 며칠 (0 = 오늘)", "days"),
                 ("첨부 종류", "exts"), ("한 번에 최대 메일 수", "max"))
    SECURITY = (("ssl", "SSL (포트 993)"), ("starttls", "STARTTLS (포트 143)"))
    SENDER_NOTE = "보낸 사람을 이름만 넣으면 다른 사람이 흉내 낼 수 있습니다. 메일 주소(@ 포함)로 넣는 것을 권합니다."   # (BugBuster I10)
    DAYS_NOTE = "기간은 처음 받을 때만 쓰고, 그 뒤는 지난번 받은 날부터 받습니다 (최대 30일)."      # mail_imap._days (BugBuster I8)

    def _render_imap(self, p):
        """기록한 단계 목록 자리에 메일 서버·조건 칸과 [찾아보기]. 칸을 고쳐도 다시 그리지 않는다 (치는 중에 칸이 사라지지 않게)."""
        cfg = p["imap"] = p["imap"] or blank_imap(p["id"])
        r = {**mail_imap.DEFAULT_RULES, **cfg["rules"]}
        show = lambda v: ", ".join(v) if isinstance(v, list) else str(v)     # noqa: E731
        box = tk.Frame(self.inner, bg=CARD)
        box.pack(fill="x", padx=12, pady=(10, 4))
        v = {}
        for i, (label, key) in enumerate(self.IMAP_TEXT):
            v[key] = tk.StringVar(self.root, value=show(cfg[key] if key in ("host", "port") else r[key]))
            tk.Label(box, text=label, font=F, bg=CARD, fg=MUTED).grid(row=i, column=0, sticky="w", pady=2)
            self._entry(box, v[key], 20).grid(row=i, column=1, sticky="we", padx=(8, 0), pady=1)
        n = len(self.IMAP_TEXT)
        tk.Label(box, text="보안 방식", font=F, bg=CARD, fg=MUTED).grid(row=n, column=0, sticky="w", pady=2)
        sec = w.Select(box, values=[t for _, t in self.SECURITY])
        sec.current(next((k for k, (x, _) in enumerate(self.SECURITY) if x == cfg["security"]), 0))
        sec.grid(row=n, column=1, sticky="we", padx=(8, 0), pady=2)
        v["unseen_only"], v["mark_seen"] = tk.BooleanVar(self.root, value=bool(r["unseen_only"])), tk.BooleanVar(self.root, value=bool(r["mark_seen"]))
        for k, (key, text) in enumerate((("unseen_only", "안 읽은 메일만"), ("mark_seen", "받은 뒤 읽음으로 표시"))):
            w.Check(box, text=text, variable=v[key], command=lambda: self._imap_store(p, v, sec)).grid(row=n + 1 + k, column=0, columnspan=2, sticky="w", pady=2)
        box.columnconfigure(1, weight=1)
        for x in v.values():
            if isinstance(x, tk.StringVar):
                x.trace_add("write", lambda *a: self._imap_store(p, v, sec))
        sec.bind("<<ComboboxSelected>>", lambda e: self._imap_store(p, v, sec))
        tk.Label(self.inner, text="보낸 사람·제목 조건은 쉼표로 여러 개를 넣을 수 있습니다. 보낸 사람이나 제목 조건 가운데 하나는 꼭 넣어 주십시오. "
                 "이미 받은 메일은 다시 받지 않습니다. " + self.DAYS_NOTE + " " + self.SENDER_NOTE, font=F_SMALL, bg=CARD, fg=MUTED, justify="left", anchor="w",
                 wraplength=self.panel_w - int(90 * self.scale)).pack(fill="x", padx=12, pady=(4, 6))
        row = tk.Frame(self.inner, bg=CARD)
        row.pack(fill="x", padx=12, pady=(0, 6))
        button(row, "찾아보기", "primary", self.imap_find).pack(side="left")
        w.Link(row, "받은 메일 기억 지우기", self.clear_imap_memory, fg=MUTED).pack(side="right")
        found = getattr(self, "imap_found", None)
        if found and found[0] == self.cur and isinstance(found[1], list):
            for it in found[1]:
                text = (f"{it['date']:%m-%d %H:%M}  {it['sender']}\n    {it['subject'][:60]}"
                        + (f"\n    첨부: {', '.join(it['attachments'])}" if it["attachments"] else "\n    받을 첨부 없음")
                        + ("  (이미 받음)" if it["done"] else ""))
                tk.Label(self.inner, text=text, font=F_SMALL, bg=CARD, fg=w.TEXT4 if it["done"] else INK, justify="left", anchor="w",
                         wraplength=self.panel_w - int(90 * self.scale)).pack(fill="x", padx=14, pady=2)

    def _imap_store(self, p, v, sec):
        """메일 서버 칸 → p['imap']. 숫자 칸에 숫자가 아닌 글을 넣으면 그대로 두어 저장·찾아보기 때 까닭을 보인다."""
        num = lambda s: int(s) if s.strip().isdigit() else s.strip()     # noqa: E731
        split = lambda s: [x.strip() for x in s.split(",") if x.strip()]     # noqa: E731
        cfg = p["imap"]
        cfg.update(host=v["host"].get().strip(), port=num(v["port"].get()),
                   security=self.SECURITY[max(sec.current(), 0)][0])
        cfg["rules"].update(mailbox=v["mailbox"].get().strip() or "INBOX", senders=split(v["senders"].get()),
                            subject_prefix=v["subject_prefix"].get().strip(), subject_has=split(v["subject_has"].get()),
                            subject_not=split(v["subject_not"].get()), days=num(v["days"].get()), exts=split(v["exts"].get()),
                            max=num(v["max"].get()), unseen_only=v["unseen_only"].get(), mark_seen=v["mark_seen"].get())

    def imap_find(self):
        """[찾아보기]: 지금 조건에 맞는 메일 목록. 받지도, 읽음 표시를 바꾸지도 않는다 (mail_imap.find)."""
        self._store_fields()
        i, p = self.cur, self.presets[self.cur]
        step = imap_record(p["imap"])["steps"][0]
        no = saved_no(p, i)                      # (BugBuster H2)
        if not p["pw"] and p["has_pw"] and no is None:
            return self.status.config(text=self.SAVE_FIRST, fg=RED)
        pw = p["pw"] or (stored_password(no) if p["has_pw"] else "")
        memory = st.imap_memory_path(no) if no else None
        why = imap_problem(step) or (None if p["id"].strip() and pw else "메일 계정의 아이디·비밀번호를 넣어 주십시오.")
        if why:
            return self.status.config(text=why, fg=RED)
        server = {"host": step["host"], "port": step["port"], "security": step["security"], "user": p["id"].strip(), "password": pw}
        self.status.config(text="메일 서버에서 찾는 중…", fg=MUTED)

        def work():
            try:
                res = mail_imap.find(server, step["rules"], memory)
            except mail_imap.MailError as e:
                res = str(e)
            except Exception as e:
                res = f"메일을 찾지 못했습니다. ({type(e).__name__})"
            self.ui.put(("imap_found", i, res))
        threading.Thread(target=work, daemon=True).start()
        return None

    def _imap_found(self, i, res):
        self.imap_found = (i, res)
        if isinstance(res, str):
            self.status.config(text=res, fg=RED)
        else:
            done = sum(1 for x in res if x["done"])
            warn = imap_warn(imap_record(self.presets[i]["imap"])["steps"][0]) if i < len(self.presets) and self.presets[i]["imap"] else ""
            self.status.config(text=f"조건에 맞는 메일 {len(res)}통" + (f" (이미 받은 메일 {done}통)" if done else "")
                               + " - 찾아보기는 받거나 읽음 표시를 하지 않습니다." + (f" {warn}" if warn else ""), fg=GREEN_D)   # (BugBuster I6)
        if i == self.cur:
            self.render()

    def clear_imap_memory(self):
        """[받은 메일 기억 지우기] (메일 서버): 다음 실행 때 조건에 맞는 메일을 다시 받는다."""
        no = saved_no(self.presets[self.cur], self.cur)     # (BugBuster H2)
        if no is None:
            return self.status.config(text=self.SAVE_FIRST, fg=RED)
        path = st.imap_memory_path(no)
        if not os.path.isfile(path):
            return self.status.config(text="받은 메일 기억이 없습니다.", fg=MUTED)
        if not self.ask("받은 메일 기억 지우기", "이 프리셋의 메일 처리 기록을 삭제합니다. 다음 실행 때 메일함에서 조건에 맞는 메일을 다시 "
                        "다운로드합니다. 삭제하시겠습니까?"):
            return None
        mail_imap.forget(path)
        return self.status.config(text="받은 메일 기억을 지웠습니다.", fg=GREEN_D)

    def _progress(self, sid, st, how):
        r = self.rows.get(sid)
        if r is None:
            return
        state, tail = {"run": ("run", ""), "ok": ("done", f"  [{how}]"), "skip": ("auto", "  (건너뜀 - 화면에 없음)"), "fail": ("fail", "")}[st]
        if st == "fail" and self.worker.cancel.is_set():
            state, tail = "stop", "  (중단)"                 # 사람이 멈춘 것 - 고칠 단계가 아니다
        r["dot"].set_state(state)
        r["lab"].config(text=self.base[sid] + tail, fg=RED if state == "fail" else w.STEP_MUTE if state in ("auto", "stop") else w.STEP_INK)
        if state == "fail":
            r["why"].config(text=how)
            r["why"].pack(fill="x")
        else:
            r["why"].pack_forget()
        y = r["row"].winfo_y()
        h = max(self.inner.winfo_height(), 1)
        self.canvas.yview_moveto(max(0, (y - 60) / h))

    # --- 단추 ---
    def toggle_record(self):
        if self.recording is not None:
            self.worker.cmd.put(("stop",))
            return
        self._store_fields()
        p = self.presets[self.cur]
        if (p["raw"] or p["loaded"] or p["head"]) and not self.ask(
                "다시 기록", f"{circled(self.cur + 1)} {p['name']}의 기록을 삭제하고 처음부터 다시 기록하시겠습니까?"):
            return
        p.update(raw=[], loaded=None, head=None, start_url=self.start_url, enabled={}, deleted=set(), otp={}, wait={})
        self.recording, self.shown = self.cur, 0
        self.status.config(text="브라우저를 여는 중…", fg=MUTED)
        self.render()
        self.worker.cmd.put(("record", self.cur, p["name"], self.start_url))

    def preview(self):
        self._store_fields()
        p = self.presets[self.cur]
        final = self._final(p)
        if not final:
            return self.status.config(text="기록된 단계가 없습니다.", fg=RED)
        kept = self._kept(p, final)
        if not kept:
            return self.status.config(text="실행할 단계가 없습니다.", fg=RED)
        no = saved_no(p, self.cur)               # (BugBuster H2)
        if not p["pw"] and p["has_pw"] and no is None:
            return self.status.config(text=self.SAVE_FIRST, fg=RED)
        pw = p["pw"] or (stored_password(no) if p["has_pw"] else "")
        if not p["id"].strip() or not pw:
            return self.status.config(text="프리셋에 아이디·비밀번호를 설정하신 후 미리보기를 진행해 주십시오.", fg=RED)
        r = rec.keep_steps(final, kept)
        ids = [s["id"] for s in r["steps"]]
        self.render()
        for sid in ids:
            self.rows[sid]["dot"].set_state("wait")
            self.rows[sid]["lab"].config(fg=w.STEP_MUTE)
        self.worker.cancel.clear()          # 명령보다 먼저 - 일꾼이 받기 전에 누른 [■ 중단] 을 지우지 않게
        self.worker.pause.clear()
        self.worker.edit.clear()
        self.previewing, self.paused, self.stopping = True, False, False
        self.failed_at, self.editing = None, False
        self.paint_buttons()
        self.status.config(text=PICK_NOTE if any(s.get("pick") for s in r["steps"]) else "미리보기 중", fg=BLUE)
        mail_pw = p["mail_pw"] or (stored_password(no, "MailPW") if p["has_mail_pw"] and no is not None else "")
        if has_mail_login(r) and not (p["mail_id"].strip() and mail_pw):
            return self.status.config(text="인증 메일 계정이 입력되지 않았습니다. 인증 메일 아이디와 비밀번호를 입력하여 주십시오.", fg=RED)
        self.worker.cmd.put(("preview", self.cur, r, ids, {"ID": p["id"].strip(), "PW": pw, "Phone": p["phone"],
                                                            "SmsSenders": senders_list(p["senders"]),
                                                            "MAIL_ID": p["mail_id"].strip(), "MAIL_PW": mail_pw}, p["code"] or "000",
                             f"{circled(self.cur + 1)} {p['name']}"))

    def toggle_pause(self):
        """[Ⅱ 일시정지]: 지금 단계를 마치고 다음 단계 앞에서 기다린다. [▶ 계속] 이면 이어 간다."""
        self.paused = not self.paused
        (self.worker.pause.set if self.paused else self.worker.pause.clear)()
        self.status.config(text="일시정지하였습니다. [▶ 계속]으로 이어서 진행하거나 [■ 중단]을 눌러 주십시오." if self.paused else
                        "미리보기 중", fg=BLUE)
        self.paint_buttons()

    def stop_preview(self):
        """[■ 중단]: 찾거나 기다리던 것을 그만두고 브라우저를 닫는다 (대개 1초 안). 끝나면 preview_done."""
        self.stopping = True
        self.worker.cancel.set()
        self.status.config(text="중단하는 중…", fg=MUTED)
        self.paint_buttons()

    def edit_preview(self):
        """[수정]: 일시정지·실패한 자리에서 - 아직 안 한 단계를 지우고 미리보기 브라우저에 기록기를 붙여 이어 기록한다. 일꾼이 editing."""
        self.editing = True
        self.worker.edit.set()
        self.status.config(text="이어서 기록할 준비 중…", fg=MUTED)
        self.paint_buttons()

    def _start_edit(self, no, cut):
        """일꾼의 editing: 칸 no 의 기록을 cut(아직 안 한 단계의 id) 앞까지만 남기고 (꺼 둔 단계 포함 그대로) 그 뒤에 새 단계를 받는다.
        id 는 단계 순서대로 커지므로 cut 보다 작은 것이 남긴 단계다. 잘린 단계는 head["cut"] 에 둔다 - 이어 기록한 같은 대상이
        '몇 단계 뒤에 새로 생긴 것' 을 이어받는다 (rec.continue_record)."""
        p = self.presets[no]
        final = self._final(p)
        k = next((i for i, s in enumerate(final["steps"]) if s["id"] == cut), len(final["steps"]))
        p.update(head=dict(final, steps=final["steps"][:k], cut=final["steps"][k] if k < len(final["steps"]) else None), raw=[], fresh=True,
                 deleted={d for d in p["deleted"] if d < cut}, enabled={d: v for d, v in p["enabled"].items() if d < cut},
                 otp={d: v for d, v in p["otp"].items() if d < cut}, wait={d: v for d, v in p["wait"].items() if d < cut})
        self.previewing = self.paused = self.stopping = self.editing = False
        self.failed_at = None
        self.recording, self.shown = no, 0
        self.status.config(text=f"● {circled(no + 1)} {p['name']} 이어서 기록 중입니다. 마치면 [■ 기록 완료]를 눌러 주십시오.", fg=RED)
        self.render()

    def import_file(self):
        """[파일에서 불러오기]: 프리셋 파일(6절)을 지금 칸에 넣는다. 저장은 [저장] 그대로 (아이디·비밀번호는 사용자가 넣는다)."""
        if self.recording is not None or self.previewing:
            return None
        path = filedialog.askopenfilename(title="파일에서 불러오기", filetypes=[("프리셋 파일", "*.json")])
        if not path:
            return None
        try:
            with open(path, encoding="utf-8") as f:
                obj = pt.check_file(json.load(f))
        except (OSError, ValueError) as e:
            return self.status.config(text=f"파일을 불러오지 못했습니다. ({e})", fg=RED)
        self._store_fields()
        p = self.presets[self.cur]
        if (p["raw"] or p["loaded"] or p["head"]) and not self.ask(
                "파일에서 불러오기", f"프리셋 {self.cur + 1}의 기록을 이 파일로 바꿉니다. 저장하기 전까지는 파일에 반영되지 않습니다. 진행하시겠습니까?"):
            return None
        load_file_into(p, obj)
        self.shown = 0
        self._load_fields()
        self.render()
        return self.status.config(text="파일에서 불러왔습니다. 아이디·비밀번호를 확인하고 저장하여 주십시오.", fg=GREEN_D)

    def export_file(self):
        """[파일로 내보내기]: 저장된 지금 칸을 프리셋 파일(6절)로. 아이디·비밀번호·인증 휴대폰은 넣지 않는다 (pt.export_item)."""
        p = self.presets[self.cur]
        no = self.cur + 1                        # 지워 당겨진 번호(orig 가 다름)면 파일의 다른 프리셋을 내보낸다 (BugBuster H2) - 새 칸은 fresh 로 막힌다
        if p.get("fresh") or not (p["loaded"] or p["raw"] or p["head"]) or p["orig"] not in (None, no):      # 기록한 칸은 저장 뒤에도 loaded 가 없다 (raw·head)
            return self.tell("파일로 내보내기", "저장한 뒤 내보내 주십시오.")
        try:
            item = pt.export_item(no)
        except ValueError as e:
            return self.status.config(text=str(e), fg=RED)
        path = filedialog.asksaveasfilename(title="파일로 내보내기", initialfile=export_name(no, item["name"]), defaultextension=".json",
                                            filetypes=[("프리셋 파일", "*.json")])
        if not path:
            return None
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(item, f, ensure_ascii=False, indent=1)
        except OSError as e:
            return self.status.config(text=f"파일로 내보내지 못했습니다. ({e})", fg=RED)
        return self.status.config(text=f"파일로 내보냈습니다. ({os.path.basename(path)})", fg=GREEN_D)

    def save(self):
        if self.recording is not None or self.previewing:
            return None                     # 단추가 잠겨 있다 - 기록·미리보기가 끝난 뒤에만 (2026-10-02)
        self._store_fields()
        try:
            cfg = st.read_user_config()
        except ValueError as e:
            return self.status.config(text=f"사용자 설정을 읽지 못했습니다: {e}", fg=RED)
        if not cfg:
            return self.status.config(text="이 PC의 사용자 설정이 없습니다. 시작 메뉴의 '오토파일럿 설정'에서 먼저 저장하여 주십시오.", fg=RED)
        now = datetime.datetime.now().isoformat(timespec="seconds")
        out, warns = [], []
        for no, p in enumerate(self.presets, 1):
            final, r = self._final(p), None
            if final and final["steps"]:
                kept = self._kept(p, final)
                r = rec.keep_steps(final, kept)
                if is_up(p):
                    r["upload"] = True
                for s in r["steps"]:
                    s.pop("id", None)
                # 막지 않고 알리기만: 날짜로 못 바꾼 날짜 모양 값 (BugBuster I3) - 번호는 단계 목록에 보이는 번호 (지운 단계 뺌)
                for k, v in rec.date_like_fills(final["steps"]):
                    if k in kept:
                        n = sum(1 for s in final["steps"][:k + 1] if s["id"] not in p["deleted"])
                        warns.append(f"{circled(no)} {n}단계 값 '{v}'은(는) 날짜로 바꾸지 못해 매일 같은 날짜를 넣습니다.")
                for k, v in rec.otp_suspects(final["steps"]):     # 단서 없는 인증번호 칸 (O8)
                    if k in kept:
                        n = sum(1 for s in final["steps"][:k + 1] if s["id"] not in p["deleted"])
                        warns.append(f"{circled(no)} {n}단계 값 '{v}'은(는) 매일 같은 값을 넣습니다. 문자로 받는 인증번호면 "
                                     "그 단계의 [인증번호 칸]을 눌러 주십시오.")
                dl = sum(1 for k, s in enumerate(final["steps"]) if k in kept and s.get("download"))
                if dl > 1:                             # 같은 사이트코드 파일은 하나만 올린다 (run_routine.collect_upload_files)
                    warns.append(f"{circled(no)} 파일 받기 단계가 {dl}개입니다. 같은 사이트코드의 파일은 가장 나중에 받은 1개만 "
                                 "업로드하고 나머지는 오류 폴더로 옮깁니다.")
                if imap_warn(st.imap_step(final)):     # (BugBuster I6)
                    warns.append(f"{circled(no)} {imap_warn(st.imap_step(final))}")
                pw_sites = rec.password_sites([s for k, s in enumerate(final["steps"]) if k in kept])
                if len(pw_sites) > 1:                  # (BugBuster I1)
                    warns.append(f"{circled(no)} 비밀번호 단계가 서로 다른 사이트({', '.join(pw_sites)})에 있습니다. "
                                 "실행할 때마다 모든 사이트에 이 프리셋의 비밀번호를 입력합니다.")
            out.append({"no": no, "name": p["name"], "code": p["code"], "record": r, "source": p["source"], "prefix": p["prefix"], "upload": is_up(p), "market": p["market"],
                        "id": p["id"], "pw": p["pw"], "has_pw": p["has_pw"], "phone": p["phone"], "senders": p["senders"],
                        "mail_id": p["mail_id"], "mail_pw": p["mail_pw"], "has_mail_pw": p["has_mail_pw"]})
        problem = validate_presets(out, need_market=bool(self.market_box.grid_info())) or pick_problem(out)
        if problem:
            self.select(problem[0] - 1)
            return self.status.config(text=problem[1], fg=RED)
        for a, b in imap_overlap(out):                 # (O12)
            warns.append(f"{circled(a)}·{circled(b)} 같은 메일함의 조건이 겹쳐 한 메일을 두 사이트코드로 올릴 수 있습니다. "
                         "보낸 사람이나 제목 조건을 나눠 주십시오.")
        for o in out:
            if o["record"]:
                scrub_login(o["record"], o["id"], o["mail_id"])      # 아이디(메일함 아이디도)는 기록에 글자로 안 남긴다 (설정 값으로 친다)
        try:
            old = {p["no"]: p for p in st.read_presets()}
        except ValueError:
            old = {}                                   # 예전 파일을 못 읽으면 기록 있는 것은 모두 오늘 날짜
        # 프리셋을 지워 번호가 당겨졌으면 (이슈 #13) 옛 값(비밀번호·켬끔·날짜·파일)은 불러올 때 번호(orig)로 찾는다 - 새 칸은 None (옛 값 없음)
        origs = {no: p["orig"] for no, p in enumerate(self.presets, 1)}
        dropped = sorted(set(old) - set(origs.values()))
        # rpa_dashboard.launch_state()(띄우는 중)는 에이전트 프로세스 안의 Popen 손잡이(_active)라 다른 프로세스인 옵저버에서는 늘 None - 못 쓴다.
        # 옵저버가 열린 동안은 대시보드가 RPA 를 안 띄우므로 (busy_problem 의 잠금) 기록에 남은 '도는 중' 만 본다.
        if (dropped or any(o is not None and o != no for no, o in origs.items())) and st.running_programs():
            return self.status.config(text="오토파일럿이 실행 중이라 저장하지 못했습니다. 끝난 뒤 저장하여 주십시오.", fg=RED)
        old = {no: old[o] for no, o in origs.items() if o in old}
        for o in out:          # 같은 칸을 다른 사이트로 다시 녹화하고 비밀번호를 비웠다 - 옛 사이트 비밀번호를 쓴다, 짝 검사도 못 잡는다 (BugBuster I1)
            if o["record"] and not o["pw"] and o["has_pw"] and o["no"] in old and old[o["no"]]["code"] != o["code"]:
                warns.append(f"{circled(o['no'])} 사이트코드가 바뀌었지만 비밀번호를 새로 입력하지 않아 이전 사이트의 비밀번호를 사용합니다.")
            if o["record"] and o["source"] in ("mail", "imap") and o["no"] in old and old[o["no"]]["code"] != o["code"]:   # (O6 - 지우는 것은 store, K13)
                warns.append(f"{circled(o['no'])} 사이트코드가 바뀌어 받은 메일 기억을 지웠습니다. 다음 실행에 기간 안의 메일을 다시 받습니다.")
        sites = cfg.get(st.SITES_SECTION)
        sites = sites if isinstance(sites, dict) else {}
        logins_changed = {o["no"] for o in out if o["pw"] or o["id"].strip() != (
            (sites.get(st.preset_site_key(origs.get(o["no"]))) or {}).get("ID") or "")}
        files = keep_dates([{k: o[k] for k in ("no", "name", "code", "record", "market")} for o in out], old, logins_changed, now)
        for o in out:
            try:
                pw = o["pw"] or (stored_password(origs.get(o["no"])) if o["has_pw"] and origs.get(o["no"]) else "")
            except RuntimeError as e:
                return self.status.config(text=f"{circled(o['no'])} 저장된 비밀번호가 일치하지 않습니다. ({e}) - 비밀번호를 다시 "
                                            "설정해 주십시오.", fg=RED)
            hit = next((f for f in files if password_in_record(f["record"], pw)), None)    # 비밀번호 칸이 아닌 곳에 비밀번호를 친 경우
            if hit:
                self.select(hit["no"] - 1)               # 걸린 기록의 프리셋으로 (BugBuster L6)
                return self.status.config(text=f"{circled(hit['no'])} 기록에 비밀번호로 보이는 글자가 있어 저장하지 않았습니다. "
                                            "해당 단계를 수정해주십시오.", fg=RED)
        problem = store(files, {o["no"]: (o["id"].strip(), o["pw"] or None) for o in out if o["record"]},
                        phones={o["no"]: (o["phone"], senders_list(o["senders"])) for o in out if o["record"]}, origs=origs, dropped=dropped,
                        mail_logins={o["no"]: (o["mail_id"].strip(), o["mail_pw"] or None) for o in out if o["record"]})
        if problem:
            return self.status.config(text=problem, fg=RED)
        self.unsaved_drop = False
        for p, f in zip(self.presets, files):
            p["orig"] = f["no"]                  # 이제부터는 이 번호가 옛 번호
            if f["record"]:
                p.update(pw="", has_pw=True, saved_at=f["saved_at"], fresh=False,
                         mail_pw="", has_mail_pw=has_mail_login(f["record"]) and bool(p["mail_pw"] or p["has_mail_pw"]))
        self._load_fields()
        self.saved_view = edit_view(self.presets)
        self.status.config(text=" ".join(["저장했습니다."] + warns), fg=BLUE if warns else GREEN_D)     # 기록 때 보이던 메일도 실행 때 받는다 - '이미 처리' 로 미리 채우지 않는다 (사용자 2026-10-20, 중복은 주문번호로 막힌다)
        return st.presets_path()

    def browser_bounds(self):
        l, t, r, b = frame_rect(int(self.root.wm_frame(), 16))
        s = self.scale
        return {"left": round((l - self.browser_w) / s), "top": round(t / s),
                "width": round(self.browser_w / s), "height": round((b - t) / s)}

    def _on_configure(self, e):
        if e.widget is not self.root:
            return
        if self._dock_job:
            self.root.after_cancel(self._dock_job)
        self._dock_job = self.root.after(150, lambda: self.worker.cmd.put(("dock", self.browser_bounds())))

    def _poll(self):
        dirty = False
        try:
            while True:
                m = self.ui.get_nowait()
                if m[0] == "steps":
                    self.presets[m[1]]["raw"] = m[2]
                    self.presets[m[1]]["fresh"] = True
                    dirty = dirty or m[1] == self.cur
                elif m[0] == "viewport":
                    self.presets[m[1]]["viewport"] = m[2]
                elif m[0] == "phones":
                    if hasattr(self, "phone_box"):
                        self._store_fields()     # 치던 아이디·비밀번호를 먼저 담는다 - 목록이 늦게 와도 안 지워지게 (BugBuster M12)
                    self.phones, self.phones_failed = m[1] or [], m[1] is None
                    self._load_fields()
                elif m[0] == "status":
                    self.status.config(text=m[1], fg=m[2])
                elif m[0] == "ready":
                    self.status.config(text="프리셋을 고르고 [● 기록 시작] 을 누르십시오.", fg=MUTED)
                    self.render()
                    self.on_ready()
                elif m[0] == "recording":
                    self.on_recording()
                elif m[0] == "recording_stopped":
                    self.recording = None
                    dirty = True
                    if not self._has_kept(self.presets[self.cur]):     # 일꾼의 '[미리보기] 로 확인하세요' 대신
                        self.status.config(text="기록된 단계가 없습니다.", fg=MUTED)
                    self.on_stopped()
                elif m[0] == "progress":
                    self._progress(*m[1:])
                elif m[0] == "paused":
                    self.status.config(text="일시정지하였습니다. [▶ 계속]으로 이어서 진행하거나 [■ 중단]을 눌러 주십시오.",
                                    fg=BLUE)
                    self.on_paused()
                elif m[0] == "failed_at":
                    self.failed_at = m[1]
                    self.status.config(text=f"{m[1]}단계에서 멈췄습니다. [수정]으로 이 단계부터 다시 기록하거나 [■ 중단]을 눌러 주십시오.", fg=RED)
                    self.paint_buttons()
                    self.on_paused()
                elif m[0] == "editing":
                    self._start_edit(*m[1:])
                elif m[0] == "preview_done":
                    if self._preview_done(*m[1:]):
                        return
                elif m[0] == "human_done":
                    self.on_human_done()
                elif m[0] == "imap_found":
                    self._imap_found(m[1], m[2])
        except queue.Empty:
            pass
        if dirty and not self.previewing:
            self.render()
        self.root.after(80, self._poll)

    def _preview_done(self, ok, saved, sec, note):
        """미리보기가 끝났다 → 창을 닫는 중이면 True (부른 쪽이 _poll 을 끝낸다). [수정] 을 눌렀는데 마지막 단계까지 성공해 수정할
        자리가 없었으면 그 말도 상태 글에."""
        stopped, was_editing = self.stopping, self.editing
        self.previewing = self.paused = self.stopping = self.editing = False
        self.failed_at = None
        if self.closing:            # 일시정지 중에 창을 닫았다 - 브라우저·프로필 정리가 끝났다
            self._close_now()
            return True
        self.paint_buttons()
        if ok:
            warn = next(filter(None, map(rec.upload_warning, saved)), None)   # csv·zip 등 - 예전엔 로그에만 ((iii), 2026-11-03)
            self.status.config(text=("마지막 단계까지 끝나 수정할 자리가 없습니다. " if was_editing else "")
                               + f"미리보기 성공 ({sec:.0f}초) - 받은 파일: {', '.join(saved) or '없음'}"
                               + (f" [주의] {warn}" if warn else ""), fg=BLUE if warn else GREEN_D)
        elif stopped:
            self.status.config(text="미리보기를 중단하였습니다.", fg=MUTED)
        else:
            self.status.config(text=note or "미리보기 중 오류가 발생했습니다. - 문제의 단계를 확인하여 주십시오.", fg=RED)
        self.on_preview_done(ok)
        return False

    # 시험 모드가 갈아 끼운다
    def on_ready(self):
        p = self.presets[self.cur]
        if not (p["raw"] or p["loaded"]) and p["source"] != "imap":
            self.toggle_record()        # 빈 프리셋이면 켜자마자 브라우저를 띄우고 기록을 시작한다

    def on_recording(self):
        pass

    def on_stopped(self):
        pass

    def on_human_done(self):
        pass

    def on_paused(self):
        pass

    def on_preview_done(self, ok):
        pass

    def quit(self):
        """창 닫기 (X). 미리보기가 도는 중에는 닫지 않는다 - 예전엔 30초 기다리다 그냥 닫혀 로그인 쿠키가 든 프로필이 남았다
        (2026-10-02). 일시정지·중단 중이면 미리보기를 멈추고 정리가 끝난 뒤 (preview_done) 닫는다."""
        if self.closing:
            return
        if self.previewing and not (self.paused or self.stopping or self.failed_at is not None) or self.editing:
            return self.tell("미리보기 중", "미리보기 중에는 창을 닫을 수 없습니다.\n[Ⅱ 일시정지] 나 [■ 중단] 을 누른 후 다시 시도해 주십시오.")
        self._store_fields()                    # 보고 있는 칸에 친 값까지
        edited = getattr(self, "saved_view", None) not in (None, edit_view(self.presets))
        if (any(p.get("fresh") for p in self.presets) or self.unsaved_drop or edited) and not self.ask(
                "저장하지 않은 변경", "저장하지 않은 변경이 있습니다. 저장하지 않고 닫으시겠습니까?"):
            return
        if self.previewing:
            self.closing = True
            self.worker.cancel.set()
            self.status.config(text="미리보기를 멈추고 닫는 중…", fg=MUTED)
            self.paint_buttons()
            return
        self._close_now()

    # --- 에이전트가 닫아 달라고 할 때 (사이트 엑셀 업로드를 띄울 차례, 사용자 2026-11-10) ---
    CLOSE_SEC = 30

    def _watch_close(self):
        """1초마다 닫기 요청(st.observer_close_request)을 본다. 새 요청이면 메시지 창 하나 (같은 요청은 한 번만)."""
        if self.closing:
            return
        try:
            req = st.observer_close_request()
            if (req and not req.get("answer") and req.get("key") != self.close_seen
                    and str(req.get("at") or "") >= self.started_at):
                self.close_seen = req.get("key")
                self.close_box(req)
        except Exception:
            pass                        # 요청을 못 읽어도 옵저버는 그대로 쓴다
        self.root.after(1000, self._watch_close)

    def _close_box(self, req):
        """'30초 후 옵저버를 닫습니다' + 사유, [옵저버 닫기]·[취소]. 30초가 지나거나 [옵저버 닫기] 면 force_close, [취소]·X 면 답만 적는다."""
        top = tk.Toplevel(self.root, bg=CARD)
        top.title("옵저버")
        top.transient(self.root)
        top.resizable(False, False)
        top.attributes("-topmost", True)
        pad = w.px(24)
        body = tk.Frame(top, bg=CARD, padx=pad, pady=pad)
        body.pack(fill="both", expand=True)
        head = tk.Label(body, bg=CARD, fg=w.TEXT, font=(w.UI, 11, "bold"), anchor="w", justify="left")
        head.pack(anchor="w")
        tk.Label(body, text=f"사유 : {req.get('why') or st.OBSERVER_CLOSE_WHY}", bg=CARD, fg=w.TEXT2, font=w.F,
                 anchor="w", justify="left").pack(anchor="w", pady=(w.px(8), 0))
        row = tk.Frame(body, bg=CARD)
        row.pack(anchor="e", pady=(w.px(20), 0))
        left = [self.CLOSE_SEC]

        def done(close):
            if not top.winfo_exists():
                return
            top.destroy()
            if close:
                return self.force_close()
            st.answer_observer_close(req, "cancel")
            self.status.config(text="옵저버 닫기를 취소하였습니다. 이번 사이트 엑셀 업로드는 실행하지 않습니다.", fg=MUTED)

        w.Btn(row, "옵저버 닫기", kind="primary", command=lambda: done(True)).pack(side="right")
        w.Btn(row, "취소", command=lambda: done(False)).pack(side="right", padx=(0, w.px(8)))
        top.protocol("WM_DELETE_WINDOW", lambda: done(False))

        def tick():
            if not top.winfo_exists():
                return
            head.config(text=f"{left[0]}초 후 옵저버를 닫습니다")
            if left[0] <= 0:
                return done(True)
            left[0] -= 1
            top.after(1000, tick)
        tick()
        top.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - top.winfo_reqwidth()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - top.winfo_reqheight()) // 3
        top.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        top.lift()
        top.focus_force()

    def force_close(self):
        """묻지 않고 닫는다 (에이전트 요청 - 저장하지 않은 변경은 버린다). 미리보기 중이면 멈추고 정리가 끝나면 닫는다 (quit 과 같은 길)."""
        if self.closing:
            return
        if self.previewing:
            self.closing = True
            self.worker.cancel.set()
            self.status.config(text="미리보기를 멈추고 닫는 중…", fg=MUTED)
            self.paint_buttons()
            return
        self.closing = True
        self._close_now()

    def _close_now(self):
        self.worker.cancel.set()
        self.worker.cmd.put(("quit",))
        self.worker.join(timeout=10)       # 기록 브라우저를 닫고 프로필을 지운다
        self.root.destroy()


def icon_path():
    """주황 A 아이콘 파일 (설치 폴더, 없으면 저장소 release). 없으면 None."""
    for path in (os.path.join(st.program_dir(), ICON_NAME),
                 os.path.join(os.path.dirname(os.path.abspath(__file__)), "release", ICON_NAME)):
        if os.path.isfile(path):
            return path
    return None


def new_root():
    """주황 A 아이콘의 Tk 뿌리 창. 앱 ID 는 창보다 먼저 정해야 작업 표시줄이 파이썬 아이콘으로 묶지 않는다 (설정 창과 같다)."""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass
    root = tk.Tk()
    icon = icon_path()
    if icon:
        root.iconbitmap(icon)                   # 이 창
        root.iconbitmap(default=icon)           # 뒤에 뜨는 알림 창
    return root


def self_command(args):
    """관리자 권한으로 다시 띄울 (exe, 인자). exe 로 묶였으면 그 exe, 소스면 파이썬 + 이 파일."""
    if st.packaged():
        return os.path.abspath(sys.argv[0]), list(args)
    return sys.executable, [os.path.abspath(__file__), *args]


def start_problem(me=None, session=None):
    """창을 띄우기 전 확인 - 사람에게 보일 문장, 문제가 없으면 None. me·session 은 시험용."""
    me = me or st.process_user()
    session = st.session_user() if session is None else session
    if session and not st.same_account(me, session):
        return "다른 사용자의 관리자 권한으로 실행되었습니다. 옵저버를 설치한 사용자로 로그인 하신 후, 관리자 권한으로 실행하여 주십시오."
    return None


def setup_problem(load=None):
    """오토파일럿 설정(이 PC 의 에이전트 계정)을 마쳤나 - 안 했거나 깨졌으면 사람에게 보일 문장, 됐으면 None.
    설정 없이 옵저버만 다른 용도로 쓰지 못하게 (사용자 2026-10-14). 설정 내용은 보지도 찍지도 않는다. load 는 시험용."""
    try:
        (load or (lambda: otp_relay._agent_modules()[1].load_config()))()
        return None
    except Exception:
        return "오토파일럿 설정이 되어 있지 않습니다. 오토파일럿 설정을 먼저 해 주십시오."


def busy_problem():
    """다른 옵저버·RPA 와 부딪히면 사람에게 보일 문장, 아니면 None. 먼저 옵저버 잠금을 쥔다 - 쥔 동안 대시보드는
    RPA 를 안 띄우고 자동 실행은 닫힐 때까지 기다린다 (rpa_dashboard). 잠금은 이 프로세스가 끝나면 (죽어도) 윈도우가 푼다."""
    if not st.hold_lock(st.OBSERVER_LOCK):
        return "옵저버가 이미 켜져 있습니다."
    # ponytail: 예약이 RPA 를 띄우고 RPA 가 '도는 중' 을 적기까지 몇 초 틈은 못 막는다 (그 사이 켜면 둘 다 뜬다)
    running = [st.PROGRAMS.get(p, p) for p in st.running_programs()]
    if running:
        names = ", ".join(running)
        return f"{st.josa(names, ('이', '가'))} 돌고 있습니다. {names} 종료 후 다시 시도해 주십시오."
    return None


def show_error(text):
    ctypes.windll.user32.MessageBoxW(None, text, "옵저버", 0x10)


def fix_std_handles():
    """시작 메뉴로 켠 exe 는 표준 핸들 셋이 INVALID_HANDLE_VALUE 다 (Nuitka attach 가 붙을 콘솔이 없으면 그렇게 둔다).
    그대로면 Playwright 가 드라이버를 띄우다 subprocess 가 WinError 6 (2026-10-02 첫 실행). 못 쓰는 핸들은 NUL 로."""
    k = ctypes.WinDLL("kernel32")                       # windll.kernel32 의 restype 을 바꾸지 않게 따로
    k.GetStdHandle.restype = wintypes.HANDLE
    k.GetFileType.argtypes = (wintypes.HANDLE,)
    k.SetStdHandle.argtypes = (wintypes.DWORD, wintypes.HANDLE)
    for n in (-10, -11, -12):                           # STD_INPUT/OUTPUT/ERROR_HANDLE
        if not k.GetFileType(k.GetStdHandle(n)):        # FILE_TYPE_UNKNOWN - 없거나 못 쓰는 핸들
            k.SetStdHandle(n, msvcrt.get_osfhandle(os.open(os.devnull, os.O_RDWR)))    # 끝날 때까지 닫지 않는다


def check():
    """창 없이 확인하고 끝 줄 CHECK_DONE (빌드·샌드박스가 본다). 관리자 권한을 묻지 않는다."""
    print(f"설정 폴더: {os.path.dirname(st.user_config_path())}")
    try:
        ps = st.read_presets()
        print(f"프리셋 {len(ps)}개 (기록 있는 것 {sum(1 for p in ps if p['record'])}개)")
    except ValueError as e:
        print(f"문제: 프리셋 파일을 읽지 못했습니다. ({e})")
    try:                                                # 깔린 Edge 를 실제로 띄워 본다 (샌드박스가 이 줄을 본다)
        with sync_playwright() as p:
            b = rec.edge(p.chromium.launch, headless=True)
            print(f"브라우저: Microsoft Edge {b.version}")
            b.close()
    except Exception as e:
        print(f"문제: 브라우저를 실행하지 못했습니다. ({type(e).__name__}: {(str(e).splitlines() or [''])[0]})")
    try:
        root = tk.Tk()
        root.withdraw()
        print(f"Tcl/Tk: {root.tk.eval('info patchlevel')}")
        root.destroy()
    except Exception as e:
        print(f"문제: Tcl/Tk를 불러오지 못했습니다. ({type(e).__name__}: {e})")
    try:                                                # exe 에서 Pillow·PNG 가 빠지면 창이 안 뜬다 - 끝 줄을 안 찍어 빌드·샌드박스가 잡게
        assert w.self_check()
    except Exception as e:
        print(f"문제: 화면 그림을 만들지 못했습니다. ({type(e).__name__}: {e})")
        return 1
    print(otp_relay.check_line())
    print(CHECK_DONE, flush=True)
    return 0


def main(argv=None):
    fix_std_handles()                                   # 무엇보다 먼저 - 일꾼이 곧 Playwright(subprocess)를 띄운다
    argv = sys.argv[1:] if argv is None else list(argv)
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8")        # 콘솔 없는 exe 를 시작 메뉴로 켜면 stdout 이 없다
    ap = argparse.ArgumentParser(description="옵저버")
    ap.add_argument("--check", action="store_true", help="창 없이 확인 (빌드·샌드박스)")
    a = ap.parse_args(argv)
    if a.check:
        return check()
    if not st.is_admin():
        exe, params = self_command(argv)
        if st.run_as_admin(exe, params, os.path.dirname(exe)):
            return 0
        show_error("관리자 권한이 있어야 기록을 저장할 수 있습니다. 관리자 권한으로 실행하여 주십시오.")
        return 1
    problem = start_problem() or setup_problem() or busy_problem()
    if problem:
        show_error(problem)
        return 1
    sweep_profiles()                    # 잠금을 쥔 뒤 - 지난번에 못 지운 프로필 (로그인 쿠키)
    try:
        presets = load_presets()
    except ValueError as e:
        show_error("프리셋 파일에 문제가 있습니다. 관리자에게 문의해 주십시오.")
        return 1
    scale = dpi_scale()
    root = new_root()
    App(root, scale, presets)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
