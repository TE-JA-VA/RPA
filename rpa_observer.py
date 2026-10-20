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
from ctypes import wintypes
from tkinter import filedialog, messagebox, ttk

from playwright.sync_api import sync_playwright

import otp_relay
import preset_transfer as pt
import rpa_status as st
import web_replay as rec


REC_DIR = os.path.join(st.data_dir(), "옵저버")          # 기록·미리보기로 받은 파일 (루틴이 읽는 ERPIA_AI_EXCEL 이 아니다)
RECORD_DL = os.path.join(REC_DIR, "기록")
PREVIEW_DL = os.path.join(REC_DIR, "미리보기")
MAIL_HINT = "엑셀파일을 받으려는 메일이 '메일 시작 문구'로 시작하는 경우, 그 글자로 시작하는 메일이 처리대상이 됩니다."   # 메일 첨부파일일 때 안내 (사용자 2026-10-14 검수)
PICK_NOTE = "# 알림 : 미리보기 중에는 가장 적절한 메일 1통으로 테스트합니다. (이미 받은 메일도 포함)"   # 메일 고르기 미리보기 알림 (사용자 2026-10-14 검수)
MIN_PRESETS = st.PRESET_MIN             # 최대는 업체마다 (st.preset_limit - App.max_presets)
PRESETS_PER_ROW = 10                    # 프리셋 단추 한 줄에 10개, 11개부터 줄을 더한다 (사용자 2026-10-14)
APP_ID = "AFTERMARKET.RPA.Observer"                     # 작업 표시줄 묶음 이름. 시작 메뉴 바로 가기(installer.iss)와 같아야 한다
ICON_NAME = "AFTER_MARKET_PREPARE.ico"                  # 옵저버 회색 AP (tools/make_icon.py)
CHECK_DONE = "옵저버 점검 끝"                              # --check 끝 줄 (build_release.MARKERS·sandbox_inner.ps1)
PROFILE_PREFIX = "rec_prof_"                            # 기록·미리보기 브라우저의 새 프로필 (로그인 쿠키가 든다 - 끝나면 지운다)
UI = "맑은 고딕"
F = (UI, 10)
F_SMALL = (UI, 9)
F_BOLD = (UI, 10, "bold")
BG, CARD, LINE = "#f3f4f6", "#ffffff", "#e5e7eb"
INK, MUTED = "#111827", "#6b7280"
BLUE, BLUE_D, BLUE_L = "#2563eb", "#1d4ed8", "#dbeafe"
GREEN, GREEN_D = "#16a34a", "#15803d"
RED, RED_D, RED_L = "#dc2626", "#b91c1c", "#fee2e2"
GRAY_BTN = "#d1d5db"
GUIDE = """<!doctype html><meta charset="utf-8"><title>오토파일럿 기록</title>
<body style="margin:0;font-family:'Malgun Gothic',sans-serif;background:#f3f4f6;color:#111827">
<div style="padding:28px 40px"><div style="font-size:40px;line-height:1">⬆</div>
<h2 style="margin:10px 0 6px">주소 표시줄에 쇼핑몰 주소를 입력해주십시오.</h2>
<p style="margin:0 0 18px;font-size:15px">먼저 프리셋에 쇼핑몰 아이디와 비밀번호를 설정해 주십시오.<br>로그인부터 엑셀 파일을 받을 때까지의 행위를 기록하게 됩니다.</p>
<p style="margin:0;color:#6b7280;font-size:14px">{hint}</p></div>"""


def circled(n):
    """① ~ ㊿ - 유니코드 동그라미 숫자는 세 줄로 나뉘어 있다 (1~20, 21~35, 36~50). 웰라이프 업체 40개 (2026-10-15)."""
    return chr(0x2460 + n - 1) if n <= 20 else chr(0x3251 + n - 21) if n <= 35 else chr(0x32B1 + n - 36)


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
            if any(s["kind"] == "otp" for s in steps):
                rp.otp = self._otp_relay(creds, label, stamp)
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
            "source": "shop", "prefix": "",              # 주문 수집용 엑셀파일 경로 (shop 쇼핑몰 / mail 메일 첨부파일), 메일 시작 문구
            "orig": None,       # 불러올 때의 번호 (새 칸은 None) - 프리셋을 지워 번호가 당겨지면 저장할 때 이 번호의 옛 값을 쓴다 (이슈 #13)
            "fresh": False}     # fresh = 이번에 기록하고 아직 저장 안 함 (저장하면 그 프리셋은 꺼진 채로)


def load_file_into(p, obj):
    """프리셋 파일(pt.check_file 을 지난 dict)을 화면 칸 p 에 넣는다 - 저장 전까지 새로 기록한 것과 같게 (fresh).
    사이트코드가 칸의 것과 다르면 아이디·비밀번호·인증 휴대폰을 비운다 (같으면 그대로). 같은 dict 를 돌려준다."""
    r = json.loads(json.dumps(obj["record"]))
    for k, s in enumerate(r["steps"]):
        s["id"] = k
    if obj["code"] != p["code"]:
        p.update(id="", pw="", has_pw=False, phone="", senders="")
    pick = next((s["pick"] for s in r["steps"] if s.get("pick")), None)
    p.update(name=obj["name"], code=obj["code"], loaded=r, raw=[], head=None, start_url=None, viewport=r.get("viewport"),
             enabled={}, deleted=set(), otp={}, fresh=True,
             source="mail" if pick else "shop", prefix=pick["prefix"] if pick else "")
    return p


def export_name(no, name):
    """내보내기 파일 이름 - 파일에 못 쓰는 글자는 _ 로."""
    return f"프리셋_{no}_{re.sub(r'[\\/:*?\"<>|]', '_', name)}.json"


def load_presets():
    """저장된 프리셋과 그 아이디 (비밀번호는 있는지만). 설정이나 프리셋 파일이 깨졌으면 ValueError - 덮어쓰지 않게 열지 않는다."""
    sites = st.read_user_config().get(st.SITES_SECTION) or {}
    out = []
    for p in st.read_presets():
        q = new_preset(p["no"], p["name"], p["code"])
        q["saved_at"], q["orig"] = p["saved_at"], p["no"]
        r = p["record"]
        if r and r.get("steps"):
            for k, s in enumerate(r["steps"]):
                s["id"] = k
            q["loaded"], q["viewport"] = r, r.get("viewport")
            pick = next((s["pick"] for s in r["steps"] if s.get("pick")), None)
            if pick:
                q["source"], q["prefix"] = "mail", pick["prefix"]
        site = sites.get(st.preset_site_key(p["no"])) if isinstance(sites, dict) else None
        if isinstance(site, dict):
            if not st.login_mismatch(site, p["code"]):     # 다른 사이트의 계정이면 비워 둔다 - 다시 저장해도 잘못된 짝이 굳지 않게 (이슈 #13 검토)
                q["id"], q["has_pw"] = site.get("ID") or "", bool(site.get("PW"))
            q["phone"], q["senders"] = site.get("Phone") or "", ", ".join(site.get("SmsSenders") or [])
        out.append(q)
    return out


def senders_list(text):
    """'1588-1234, 02 123 4567, +82 90-258-0002' → ['15881234', '021234567', '0902580002'] (숫자만, +82 는 0 으로 - 휴대폰과 같은 꼴)."""
    return [d for d in (otp_relay.sender_number(x) for x in re.split(r"[,;/]+", text or "")) if d]


def has_otp(record):
    return any(s.get("kind") == "otp" for s in (record or {}).get("steps") or [])


def stored_password(no):
    """저장된 비밀번호 (미리보기·저장 전 확인용, 화면에는 안 보인다). 없으면 빈 글자."""
    site = (st.read_user_config().get(st.SITES_SECTION) or {}).get(st.preset_site_key(no)) or {}
    return st.unseal(site.get("PW") or "") or ""


def scrub_login(record, login_id):
    """아이디를 친 칸을 '설정의 아이디' 로 바꾸고 값을 지운다. 기록 때는 비밀번호 바로 앞 칸만 알아보므로 두 쪽 로그인
    (아이디 → 다음 → 비밀번호)·비밀번호 먼저 치기 등은 아이디가 글자로 남았다 (2026-10-01 검토). 같은 dict 를 돌려준다."""
    login_id = (login_id or "").strip()
    for s in (record or {}).get("steps", []):
        if login_id and s.get("kind") == "fill" and not s.get("credential") and (s.get("value") or "").strip() == login_id:
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
                and all(o.get(k) == f[k] for k in ("name", "code", "record")))
        f["saved_at"] = o["saved_at"] if same else (now if f["record"] else None)
    return files


def store(files, logins, fresh=(), phones=None, origs=None, dropped=()):
    """프리셋 파일과 Sites 의 PRESETn 을 쓴다. 못 쓰면 화면에 보일 문장 (콘솔 없는 exe 라 조용히 넘어가면 안 된다), 되면 None.
    origs: {번호: 불러올 때 번호}·dropped: 지운 옛 번호 - 프리셋을 지워 번호가 당겨졌을 때 (이슈 #13) Sites 의 옛 값은 옛 번호에서 찾고,
    메일 기억·로그인 세션·보관 파일도 따라 옮긴다. 순서는 프리셋 → 설정 → 파일: 설정 쓰기가 실패해도 Sites 는 옛 번호 그대로라
    다시 저장하면 같은 옛 번호로 다시 찾는다 (반대 순서면 두 번 당겨진다)."""
    try:
        st.write_presets(files)
        st.save_preset_sites(files, logins, fresh=fresh, phones=phones, origs=origs)
    except (OSError, ValueError, RuntimeError) as e:
        return f"저장하지 못했습니다. ({e}) 잠시 후 다시 저장하여 주십시오."
    pt.move_preset_files(origs or {}, dropped)
    return None


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


def validate_presets(presets):
    """저장 전에 막을 것: (프리셋 번호, 사람에게 보일 문장) 또는 None.
    presets: [{no, name, code, id, pw, has_pw, record}] - 기록이 있는 것만 본다."""
    codes = {}
    for p in presets:
        if not p.get("record"):
            continue
        tag = f"{circled(p['no'])} {p['name']}"
        if not re.fullmatch(r"\d{3}", p.get("code") or ""):
            return p["no"], f"{tag}: 사이트코드는 숫자 세 자리여야 합니다 (받은 엑셀파일 이름 앞에 붙어, 주문매핑 매출처리 단계에서 자동으로 처리하게 됩니다.)"
        if p["code"] in codes:
            return p["no"], (f"{tag}: 사이트코드 {p['code']}을(를) {codes[p['code']]}에서도 사용하고 있습니다. "
                             "다른 사이트코드를 입력하여 주십시오.")
        codes[p["code"]] = tag
        if has_otp(p["record"]) and not (p.get("phone") and senders_list(p.get("senders"))):
            return p["no"], f"{tag}: 인증번호 단계가 있습니다. 인증 휴대폰과 발신번호를 정해 주십시오."
        if not (p.get("id") or "").strip():
            return p["no"], f"{tag}: 아이디가 필요합니다."
        if not (p.get("pw") or p.get("has_pw")):
            return p["no"], f"{tag}: 비밀번호가 필요합니다."
    return None


def button(parent, text, color, dark, command, **kw):
    b = tk.Button(parent, text=text, command=command, bg=color, fg="white", activebackground=dark, activeforeground="white",
                  disabledforeground="#f9fafb", relief="flat", bd=0, cursor="hand2", font=F_BOLD, padx=16, pady=7, **kw)
    b.colors = (color, dark)
    return b


def enable(b, on):
    b.config(state="normal" if on else "disabled", bg=b.colors[0] if on else GRAY_BTN, cursor="hand2" if on else "arrow")


def skin(b, text, color, dark, command):
    """같은 단추를 다른 일에 (미리보기 중에는 [▶ 미리보기]·[저장] 자리가 [Ⅱ 일시정지]·[■ 중단]). 색은 enable 이 칠한다."""
    b.config(text=text, command=command, activebackground=dark)
    b.colors = (color, dark)


class App:
    def __init__(self, root, scale, presets, hint="", fake_creds=None):
        self.root, self.scale = root, scale
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
        self.senders_var, self.phones, self.phone_ids = tk.StringVar(root), None, [""]
        self.source_var, self.prefix_var = tk.StringVar(root, value="shop"), tk.StringVar(root)
        self._build()
        threading.Thread(target=self._load_phones, daemon=True).start()
        self._load_fields()
        root.update()
        self.worker = Worker(self.browser_bounds(), self.ui, hint)
        self.worker.start()
        root.bind("<Configure>", self._on_configure)
        root.protocol("WM_DELETE_WINDOW", self.quit)
        root.after(80, self._poll)

    # --- 화면 ---
    def _entry(self, parent, var, width, show=""):
        return tk.Entry(parent, textvariable=var, width=width, show=show, font=F, relief="flat", bg=CARD, fg=INK,
                        highlightthickness=1, highlightbackground=LINE, highlightcolor=BLUE, insertbackground=INK)

    def _build(self):
        root, s = self.root, self.scale
        pad = int(14 * s)
        head = tk.Frame(root, bg=BG)
        head.pack(fill="x", padx=pad, pady=(pad, 6))
        tk.Label(head, text="사용자 행위 기록", font=(UI, 14, "bold"), bg=BG, fg=INK).pack(anchor="w")
        tk.Label(head, text="각 프리셋마다 로그인부터 엑셀 파일 다운로드까지 보여주시면 다음 번부터 자동으로 엑셀파일을 수집합니다.",
                 font=F_SMALL, bg=BG, fg=MUTED, anchor="w", justify="left", wraplength=self.panel_w - 2 * pad).pack(fill="x")

        # 프리셋 줄
        card = tk.Frame(root, bg=CARD, highlightthickness=1, highlightbackground=LINE)
        card.pack(fill="x", padx=pad, pady=6)
        inner = tk.Frame(card, bg=CARD)
        inner.pack(fill="x", padx=12, pady=10)
        head = tk.Frame(inner, bg=CARD)              # 제목 줄 오른쪽에 개수·[+][−] - 단추 줄에는 번호 단추 10개만 (2026-10-15)
        head.pack(fill="x")
        tk.Label(head, text="프리셋", font=F_BOLD, bg=CARD, fg=INK).pack(side="left")
        self.preset_tools = tk.Frame(head, bg=CARD)
        self.preset_tools.pack(side="right")
        self.preset_bar = tk.Frame(inner, bg=CARD)
        self.preset_bar.pack(fill="x", pady=(6, 8))
        form = tk.Frame(inner, bg=CARD)          # 프리셋마다 따로인 칸은 모두 여기 (아이디·비밀번호도 - 2026-10-02)
        form.pack(fill="x")
        for r, (left, lvar, right, rvar, show) in enumerate((("이름", self.name_var, "사이트코드", self.code_var, ""),
                                                             ("아이디", self.id_var, "비밀번호", self.pw_var, "•"))):
            y = (6 if r else 0, 0)
            tk.Label(form, text=left, font=F, bg=CARD, fg=MUTED).grid(row=r, column=0, sticky="w", pady=y)
            self._entry(form, lvar, 12).grid(row=r, column=1, sticky="we", padx=(6, 0), pady=y, ipady=3)
            tk.Label(form, text=right, font=F, bg=CARD, fg=MUTED).grid(row=r, column=2, sticky="w", padx=(12, 0), pady=y)
            self._entry(form, rvar, 12, show=show).grid(row=r, column=3, sticky="we", padx=(6, 0), pady=y, ipady=3)
        tk.Label(form, text="인증 휴대폰", font=F, bg=CARD, fg=MUTED).grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.phone_box = ttk.Combobox(form, state="readonly", width=10, font=F, values=["(없음)"])
        self.phone_box.grid(row=2, column=1, sticky="we", padx=(6, 0), pady=(6, 0))
        self.phone_box.bind("<<ComboboxSelected>>", lambda e: self._field_changed())
        tk.Label(form, text="발신번호", font=F, bg=CARD, fg=MUTED).grid(row=2, column=2, sticky="w", padx=(12, 0), pady=(6, 0))
        self._entry(form, self.senders_var, 12).grid(row=2, column=3, sticky="we", padx=(6, 0), pady=(6, 0), ipady=3)
        self.senders_var.trace_add("write", lambda *a: self._field_changed())
        src = tk.Frame(form, bg=CARD)               # 주문 수집용 엑셀파일 경로 (사용자 2026-10-14)
        src.grid(row=3, column=0, columnspan=4, sticky="we", pady=(8, 0))
        tk.Label(src, text="주문 수집용 엑셀파일 경로", font=F, bg=CARD, fg=MUTED).pack(side="left")
        for value, label in (("shop", "쇼핑몰"), ("mail", "메일 첨부파일")):
            tk.Radiobutton(src, text=label, value=value, variable=self.source_var, font=F, bg=CARD, activebackground=CARD,
                           cursor="hand2", command=self._source_changed).pack(side="left", padx=(12, 0))
        self.del_btn = button(src, "프리셋 삭제", RED, RED_D, self.remove_preset)
        self.del_btn.config(font=F_SMALL, padx=10, pady=2)   # 제목 줄 [−] 와 같은 일 - 찾기 쉬운 자리에 빨간 단추로 하나 더 (사용자 2026-10-20)
        self.del_btn.pack(side="right")
        self.prefix_label = tk.Label(form, text="메일 시작 문구", font=F, bg=CARD, fg=MUTED)
        self.prefix_entry = self._entry(form, self.prefix_var, 12)
        self.prefix_var.trace_add("write", lambda *a: self._field_changed())
        form.columnconfigure(0, minsize=self.prefix_label.winfo_reqwidth())    # '메일 시작 문구' 가 나타나도 칸이 옆으로 밀리지 않게 (사용자 2026-10-20)
        for col in (1, 3):              # 왼쪽(이름·아이디·인증 휴대폰)·오른쪽(사이트코드·비밀번호·발신번호) 칸을 같은 너비로 (사용자 2026-10-13)
            form.columnconfigure(col, weight=1, uniform="field")
        self.pw_hint = tk.Label(inner, text="", font=F_SMALL, bg=CARD, fg=MUTED, anchor="w", justify="left",
                                wraplength=self.panel_w - 2 * pad - 26)
        self.pw_hint.pack(fill="x", pady=(6, 0))
        self.name_var.trace_add("write", lambda *a: self._field_changed())
        self.code_var.trace_add("write", lambda *a: self._field_changed())

        # 안내 한 줄 (기록·미리보기·저장 모두 여기 - 두 곳이면 지난 일이 남는다, 2026-10-02) + 기록 단추
        bar = tk.Frame(root, bg=BG)
        bar.pack(fill="x", padx=pad, pady=(6, 4))
        self.rec_btn = button(bar, "●  기록 시작", RED, RED_D, self.toggle_record)
        self.rec_btn.pack(side="right")
        self.status = tk.Label(bar, text="브라우저 준비 중…", font=F, bg=BG, fg=MUTED, anchor="w", justify="left",
                               wraplength=self.panel_w - int(190 * s))
        self.status.pack(side="left", fill="x", expand=True)

        # 기록 목록
        mid = tk.Frame(root, bg=CARD, highlightthickness=1, highlightbackground=LINE)
        mid.pack(fill="both", expand=True, padx=pad, pady=4)
        self.list_title = tk.Label(mid, text="", font=F_BOLD, bg=CARD, fg=INK, anchor="w")
        self.list_title.pack(fill="x", padx=12, pady=(8, 4))
        tk.Frame(mid, bg=LINE, height=1).pack(fill="x")
        body = tk.Frame(mid, bg=CARD)
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(body, highlightthickness=0, bg=CARD)
        sb = tk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=CARD)
        self.win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.win, width=e.width))
        self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))

        # 단추
        btns = tk.Frame(root, bg=BG)
        btns.pack(fill="x", padx=pad, pady=(8, pad))
        self.save_btn = button(btns, "저장", GREEN, GREEN_D, self.save, width=8)
        self.save_btn.pack(side="right")
        self.prev_btn = button(btns, "▶  미리보기", BLUE, BLUE_D, self.preview, width=12)
        self.prev_btn.pack(side="right", padx=8)
        self.edit_btn = button(btns, "수정", BLUE, BLUE_D, self.edit_preview, width=8)      # 미리보기가 멈춰 있을 때만 보인다
        self.import_btn, self.export_btn = (tk.Button(btns, text=t, command=c, font=F_SMALL, fg=MUTED, bg=BG, activebackground=LINE,
                                                      relief="flat", bd=0, cursor="hand2")
                                            for t, c in (("파일에서 불러오기", self.import_file), ("파일로 내보내기", self.export_file)))
        self.import_btn.pack(side="left")
        self.export_btn.pack(side="left", padx=(8, 0))

    def paint_presets(self):
        for c in self.preset_bar.winfo_children() + self.preset_tools.winfo_children():
            c.destroy()
        busy = self.recording is not None or self.previewing
        rows = [tk.Frame(self.preset_bar, bg=CARD) for _ in range(max(1, -(-len(self.presets) // PRESETS_PER_ROW)))]
        for r, row in enumerate(rows):
            row.pack(fill="x", pady=(0 if r == 0 else 4, 0))
            for c in range(PRESETS_PER_ROW):      # 한 줄 10칸을 같은 폭으로 나눠 창 폭에 맞춘다 (40개 - 4줄, 2026-10-15)
                row.columnconfigure(c, weight=1, uniform="preset")
        for i, p in enumerate(self.presets):
            has = bool(p["raw"] or p["loaded"])
            sel = i == self.cur
            bg, fg = (BLUE, "white") if sel else ((BLUE_L, BLUE_D) if has else ("#f3f4f6", MUTED))
            if self.recording == i:
                bg, fg = RED, "white"
            b = tk.Button(rows[i // PRESETS_PER_ROW], text=circled(i + 1), font=(UI, 14, "bold"), bg=bg, fg=fg, activebackground=bg,
                          activeforeground=fg, relief="flat", bd=0, padx=0, pady=2, cursor="hand2" if not busy else "arrow",
                          disabledforeground=fg, command=lambda i=i: self.select(i))
            b.config(state="disabled" if busy and not sel else "normal")
            b.grid(row=0, column=i % PRESETS_PER_ROW, sticky="we", padx=(0, 4))
        small = dict(font=(UI, 13, "bold"), relief="flat", bd=0, width=3, pady=1, bg=CARD, fg=MUTED, activebackground=LINE,
                     highlightthickness=1, highlightbackground=LINE)
        can_del = len(self.presets) > MIN_PRESETS and not busy
        enable(self.del_btn, can_del)
        if len(self.presets) > MIN_PRESETS:
            tk.Button(self.preset_tools, text="−", command=self.remove_preset, state="disabled" if busy else "normal",
                      cursor="hand2", **small).pack(side="right", padx=(2, 0))
        if len(self.presets) < self.max_presets:
            tk.Button(self.preset_tools, text="+", command=self.add_preset, state="disabled" if busy else "normal",
                      cursor="hand2", **small).pack(side="right", padx=2)
        tk.Label(self.preset_tools, text=f"{len(self.presets)}/{self.max_presets}", font=F_SMALL, bg=CARD, fg=MUTED).pack(side="right", padx=(0, 6))

    def paint_buttons(self):
        rec_on = self.recording is not None
        self.rec_btn.config(text="■  기록 완료" if rec_on else "●  기록 시작")
        enable(self.rec_btn, not self.previewing and (not rec_on or self.recording == self.cur))
        if self.previewing:         # 창을 닫는 대신 멈추는 단추 (2026-10-02 - 미리보기 중에는 창이 안 닫힌다)
            idle = not (self.stopping or self.closing or self.editing)
            skin(self.prev_btn, "▶  계속" if self.paused else "Ⅱ  일시정지", BLUE, BLUE_D, self.toggle_pause)
            skin(self.save_btn, "■  중단", RED, RED_D, self.stop_preview)
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
            skin(self.prev_btn, "▶  미리보기", BLUE, BLUE_D, self.preview)
            skin(self.save_btn, "저장", GREEN, GREEN_D, self.save)
            enable(self.prev_btn, kept)
            enable(self.save_btn, kept)     # 기록이 끝나 있고 켜 둔 단계가 한 줄은 있어야 (2026-10-02)
        for b in (self.import_btn, self.export_btn):
            b.config(state="disabled" if rec_on or self.previewing else "normal", cursor="arrow" if rec_on or self.previewing else "hand2")
        self.paint_presets()

    def _load_fields(self):
        p = self.presets[self.cur]
        self._loading = True
        self.name_var.set(p["name"])
        self.code_var.set(p["code"])
        self.id_var.set(p["id"])
        self.pw_var.set(p["pw"])
        self.senders_var.set(p["senders"])
        self.source_var.set(p["source"])
        self.prefix_var.set(p["prefix"])
        self._fill_phone_box()
        self._loading = False
        self._show_prefix()
        self.pw_hint.config(text=("저장된 비밀번호가 있습니다. " if p["has_pw"] else "")
                            + "아이디·비밀번호는 암호화하여 이 PC 설정에 저장합니다. 사이트 로그인 외 다른 용도로 사용하지 않습니다.\n"
                            + "문자 인증번호를 받는 사이트면 인증 휴대폰과 발신번호(여러 개면 쉼표로)를 정해 주십시오."
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
        p.update(name=self.name_var.get().strip() or p["name"], code=self.code_var.get().strip(),
                 id=self.id_var.get(), pw=self.pw_var.get(), senders=self.senders_var.get(),
                 phone=self.phone_ids[i] if 0 <= i < len(self.phone_ids) else p["phone"], source=source, prefix=prefix)

    def _field_changed(self):
        if not getattr(self, "_loading", False) and hasattr(self, "list_title"):
            p = self.presets[self.cur]
            before = (p["source"], p["prefix"])
            self._store_fields()
            self._title()
            if (p["source"], p["prefix"]) != before:
                self.render()                       # '메일마다' 단계가 바뀐다

    def _show_prefix(self):
        """메일 첨부파일일 때만 '메일 시작 문구' 칸 (쇼핑몰이면 감춘다)."""
        if self.source_var.get() == "mail":
            self.prefix_label.grid(row=4, column=0, sticky="w", pady=(6, 0))
            self.prefix_entry.grid(row=4, column=1, sticky="we", padx=(6, 0), pady=(6, 0), ipady=3)
        else:
            self.prefix_label.grid_remove()
            self.prefix_entry.grid_remove()

    def _source_changed(self):
        """라디오: 메일 첨부파일로 처음 바꾸면 시작 문구는 '>>>' 부터."""
        if self.source_var.get() == "mail" and not self.prefix_var.get().strip():
            self._loading = True
            self.prefix_var.set(rec.MAIL_PICK_DEFAULT)
            self._loading = False
        self._field_changed()
        self._load_fields()                 # 칸 보이기·안내 줄

    def _title(self):
        p = self.presets[self.cur]
        self.list_title.config(text=f"{circled(self.cur + 1)} {p['name']} - 기록한 단계")

    def select(self, i):
        if i == self.cur:
            return
        self._store_fields()
        self.cur, self.shown = i, 0
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
        self._load_fields()
        self.status.config(text="")
        self.render()

    # --- 기록 목록 ---
    def _final(self, p):
        if p["head"]:                             # [수정] - 남긴 앞부분 뒤에 이어 기록한 단계 (설계 2026-10-19 4.2절)
            final = rec.continue_record(p["head"], json.loads(json.dumps(p["raw"])), datetime.date.today())
        elif p["raw"]:
            start = p["start_url"] or next((s["href"] for s in p["raw"] if s["kind"] == "goto"), "")
            final = rec.finalize(json.loads(json.dumps(p["raw"])), datetime.date.today(), start, viewport=p["viewport"])
        else:
            final = p["loaded"]
        for sid, on in p["otp"].items():          # 단계 목록에서 바꾼 인증번호 칸 (기록이 못 알아본 것·잘못 알아본 것)
            i = next((k for k, s in enumerate(final["steps"]) if s["id"] == sid), None) if final else None
            if i is not None and (final["steps"][i]["kind"] == "otp") != on:
                rec.set_otp(final["steps"], i, on)
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

    def clear_mail_memory(self):
        """[받은 메일 기억 지우기]: 다음 실행 때 메일함의 맞는 메일을 다시 받는다."""
        mem = rec.MailMemory(st.mail_memory_path(self.cur + 1))
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
        self.labels, self.base = {}, {}
        p = self.presets[self.cur]
        final = self._final(p)
        n, body = 0, set()
        for k, s in enumerate(final["steps"] if final else []):
            end = rec.pick_body(final["steps"], k) if s.get("pick") else None
            body |= set(range(k + 1, end + 1)) if end is not None else set()
        for k, s in enumerate(final["steps"] if final else []):
            sid = s["id"]
            if sid in p["deleted"]:
                continue
            n += 1
            var = self._var(p, sid)
            on = var.get()
            row = tk.Frame(self.inner, bg=CARD)
            row.pack(fill="x")
            tk.Frame(self.inner, bg="#f3f4f6", height=1).pack(fill="x")
            tk.Checkbutton(row, variable=var, bg=CARD, activebackground=CARD, cursor="hand2",
                           command=self.render).pack(side="left", anchor="n", padx=(6, 0), pady=4)
            tk.Button(row, text="✕", font=(UI, 10), fg="#9ca3af", bg=CARD, activebackground=RED_L, activeforeground=RED,
                      relief="flat", bd=0, cursor="hand2", command=lambda sid=sid: self.delete(sid)
                      ).pack(side="right", anchor="n", padx=6, pady=4)
            if s["kind"] in ("fill", "otp"):        # 글자 칸 - 문자로 받는 인증번호 칸인지 사람이 바꿀 수 있다
                is_otp = s["kind"] == "otp"
                tk.Button(row, text="인증번호 칸 해제" if is_otp else "인증번호 칸", font=F_SMALL, fg=BLUE if is_otp else MUTED,
                          bg=CARD, activebackground=BLUE_L, relief="flat", bd=0, cursor="hand2",
                          command=lambda sid=sid, on=not is_otp: self.toggle_otp(sid, on)).pack(side="right", anchor="n", padx=2, pady=4)
            tk.Label(row, text=f"{n:2d}", font=F_SMALL, bg=CARD, fg=MUTED, width=3, anchor="e").pack(side="left", anchor="n", pady=6)
            text = ("↳ " if k in body else "") + re.sub(r" \(\d+단계 뒤에 새로 생긴 것\)", " (새로 생긴 것)", rec.describe(s))
            warn = s["kind"] == "goto" and "로그인 세션 값을 감지" in text
            lab = tk.Label(row, text=text, font=F, bg=CARD, anchor="w", justify="left",
                           fg=(RED_D if warn else INK) if on else "#9ca3af",
                           wraplength=self.panel_w - int(170 * self.scale))
            lab.pack(side="left", fill="x", expand=True, padx=(6, 0), pady=6)
            self.labels[sid], self.base[sid] = lab, text
        if final and any(s.get("pick") for s in final["steps"]):
            tk.Button(self.inner, text="받은 메일 기억 지우기", font=F_SMALL, fg=MUTED, bg=CARD, activebackground=LINE,
                      relief="flat", bd=0, cursor="hand2", command=self.clear_mail_memory).pack(anchor="e", padx=8, pady=6)
        if not n:
            tip = ("[● 기록 시작] 을 누르고 쇼핑몰 사이트 주소를 입력하는 것부터 시작해주세요.\n"
                   "모두 완료하였다면 [■ 기록 완료] 버튼을 누른 다음 저장해주세요.") if self.recording is None else \
                "주소 표시줄에 쇼핑몰 주소를 입력해주십시오."
            tk.Label(self.inner, text=tip, font=F, bg=CARD, fg=MUTED, justify="left", anchor="w",
                     wraplength=self.panel_w - int(90 * self.scale)).pack(fill="x", padx=14, pady=14)
        self._title()
        self.canvas.update_idletasks()
        if n > self.shown:
            self.canvas.yview_moveto(1.0)       # 새 단계가 생기면 맨 아래로
        self.shown = n
        self.paint_buttons()

    def delete(self, sid):
        self.presets[self.cur]["deleted"].add(sid)
        self.render()

    def _progress(self, sid, st, how):
        lab = self.labels.get(sid)
        if lab is None:
            return
        mark, color = {"run": ("▶ ", BLUE), "ok": ("✓ ", GREEN_D), "skip": ("– ", MUTED), "fail": ("✗ ", RED)}[st]
        tail = {"ok": f"  [{how}]", "skip": "  (건너뜀 - 화면에 없음)", "fail": f"\n    {how}"}.get(st, "")
        if st == "fail" and self.worker.cancel.is_set():
            mark, color, tail = "■ ", MUTED, "  (중단)"      # 사람이 멈춘 것 - 고칠 단계가 아니다
        lab.config(text=mark + self.base[sid] + tail, fg=color)
        y = lab.winfo_y() + lab.master.winfo_y()
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
        p.update(raw=[], loaded=None, head=None, start_url=self.start_url, enabled={}, deleted=set())
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
        pw = p["pw"] or (stored_password(self.cur + 1) if p["has_pw"] else "")
        if not p["id"].strip() or not pw:
            return self.status.config(text="프리셋에 아이디·비밀번호를 설정하신 후 미리보기를 진행해 주십시오.", fg=RED)
        r = rec.keep_steps(final, kept)
        ids = [s["id"] for s in r["steps"]]
        self.render()
        self.worker.cancel.clear()          # 명령보다 먼저 - 일꾼이 받기 전에 누른 [■ 중단] 을 지우지 않게
        self.worker.pause.clear()
        self.worker.edit.clear()
        self.previewing, self.paused, self.stopping = True, False, False
        self.failed_at, self.editing = None, False
        self.paint_buttons()
        self.status.config(text=PICK_NOTE if any(s.get("pick") for s in r["steps"]) else "미리보기 중", fg=BLUE)
        self.worker.cmd.put(("preview", self.cur, r, ids, {"ID": p["id"].strip(), "PW": pw, "Phone": p["phone"],
                                                            "SmsSenders": senders_list(p["senders"])}, p["code"] or "000",
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
                 otp={d: v for d, v in p["otp"].items() if d < cut})
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
        if p.get("fresh") or not (p["loaded"] or p["raw"] or p["head"]):      # 기록한 칸은 저장 뒤에도 loaded 가 없다 (raw·head)
            return self.tell("파일로 내보내기", "저장한 뒤 내보내 주십시오.")
        no = self.cur + 1
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
        out = []
        for no, p in enumerate(self.presets, 1):
            final, r = self._final(p), None
            if final and final["steps"]:
                r = rec.keep_steps(final, self._kept(p, final))
                for s in r["steps"]:
                    s.pop("id", None)
            out.append({"no": no, "name": p["name"], "code": p["code"], "record": r, "source": p["source"], "prefix": p["prefix"],
                        "id": p["id"], "pw": p["pw"], "has_pw": p["has_pw"], "phone": p["phone"], "senders": p["senders"]})
        problem = validate_presets(out) or pick_problem(out)
        if problem:
            self.select(problem[0] - 1)
            return self.status.config(text=problem[1], fg=RED)
        for o in out:
            if o["record"]:
                scrub_login(o["record"], o["id"])      # 아이디는 기록에 글자로 안 남긴다 (설정의 아이디로 친다)
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
        sites = cfg.get(st.SITES_SECTION)
        sites = sites if isinstance(sites, dict) else {}
        logins_changed = {o["no"] for o in out if o["pw"] or o["id"].strip() != (
            (sites.get(st.preset_site_key(origs.get(o["no"]))) or {}).get("ID") or "")}
        files = keep_dates([{k: o[k] for k in ("no", "name", "code", "record")} for o in out], old, logins_changed, now)
        for o in out:
            try:
                pw = o["pw"] or (stored_password(origs.get(o["no"])) if o["has_pw"] and origs.get(o["no"]) else "")
            except RuntimeError as e:
                return self.status.config(text=f"{circled(o['no'])} 저장된 비밀번호가 일치하지 않습니다. ({e}) - 비밀번호를 다시 "
                                            "설정해 주십시오.", fg=RED)
            if any(password_in_record(f["record"], pw) for f in files):    # 비밀번호 칸이 아닌 곳에 비밀번호를 친 경우
                self.select(o["no"] - 1)
                return self.status.config(text=f"{circled(o['no'])} 기록에 비밀번호로 보이는 글자가 있어 저장하지 않았습니다. "
                                            "해당 단계를 수정해주십시오.", fg=RED)
        fresh = {o["no"] for p, o in zip(self.presets, out) if o["record"] and p.get("fresh")}
        problem = store(files, {o["no"]: (o["id"].strip(), o["pw"] or None) for o in out if o["record"]}, fresh,
                        phones={o["no"]: (o["phone"], senders_list(o["senders"])) for o in out if o["record"]}, origs=origs, dropped=dropped)
        if problem:
            return self.status.config(text=problem, fg=RED)
        self.unsaved_drop = False
        for p, f in zip(self.presets, files):
            p["orig"] = f["no"]                  # 이제부터는 이 번호가 옛 번호
            if f["record"]:
                p.update(pw="", has_pw=True, saved_at=f["saved_at"], fresh=False)
        self._load_fields()
        self.status.config(text="저장했습니다.", fg=GREEN_D)     # 기록 때 보이던 메일도 실행 때 받는다 - '이미 처리' 로 미리 채우지 않는다 (사용자 2026-10-20, 중복은 주문번호로 막힌다)
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
            self.status.config(text=("마지막 단계까지 끝나 수정할 자리가 없습니다. " if was_editing else "")
                               + f"미리보기 성공 ({sec:.0f}초) - 받은 파일: {', '.join(saved) or '없음'}", fg=GREEN_D)
        elif stopped:
            self.status.config(text="미리보기를 중단하였습니다.", fg=MUTED)
        else:
            self.status.config(text=note or "미리보기 중 오류가 발생했습니다. - 문제의 단계를 확인하여 주십시오.", fg=RED)
        self.on_preview_done(ok)
        return False

    # 시험 모드가 갈아 끼운다
    def on_ready(self):
        p = self.presets[self.cur]
        if not (p["raw"] or p["loaded"]):
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
        if (any(p.get("fresh") for p in self.presets) or self.unsaved_drop) and not self.ask(
                "저장하지 않은 변경", "저장하지 않은 변경이 있습니다. 저장하지 않고 닫으시겠습니까?"):
            return
        if self.previewing:
            self.closing = True
            self.worker.cancel.set()
            self.status.config(text="미리보기를 멈추고 닫는 중…", fg=MUTED)
            self.paint_buttons()
            return
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
