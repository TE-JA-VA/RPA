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
from tkinter import messagebox

import rpa_status as st

st.setup_playwright_browsers()                     # playwright 를 부르기 전에 (exe 로 묶이면 브라우저 자리를 알려 줘야 한다)

from playwright.sync_api import sync_playwright    # noqa: E402

import web_replay as rec                           # noqa: E402


REC_DIR = os.path.join(st.data_dir(), "옵저버")          # 기록·미리보기로 받은 파일 (루틴이 읽는 ERPIA_AI_EXCEL 이 아니다)
RECORD_DL = os.path.join(REC_DIR, "기록")
PREVIEW_DL = os.path.join(REC_DIR, "미리보기")
MIN_PRESETS, MAX_PRESETS = st.PRESET_MIN, st.PRESET_MAX
APP_ID = "AFTERMARKET.RPA.Observer"                     # 작업 표시줄 묶음 이름. 시작 메뉴 바로 가기(installer.iss)와 같아야 한다
ICON_NAME = "AFTER_MARKET_PREPARE.ico"                  # 주황 A (tools/make_icon.py)
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
GUIDE = """<!doctype html><meta charset="utf-8"><title>AFTER MARKET 기록</title>
<body style="margin:0;font-family:'Malgun Gothic',sans-serif;background:#f3f4f6;color:#111827">
<div style="padding:28px 40px"><div style="font-size:40px;line-height:1">⬆</div>
<h2 style="margin:10px 0 6px">위쪽 주소줄에 쇼핑몰 주소를 치고 Enter 를 누르세요</h2>
<p style="margin:0 0 18px;font-size:15px">여기부터 하는 일이 모두 오른쪽 목록에 기록됩니다. 로그인하고 엑셀 파일을 받을 때까지 평소처럼 하세요.</p>
<p style="margin:0;color:#6b7280;font-size:14px">{hint}</p></div>"""


def circled(n):
    return chr(0x2460 + n - 1)          # ① ~ ⑩


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
        self.notify, self.next_id, self.context = notify, 0, context
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
            self._add({"kind": "newtab", "page": no, "url": ""})
        self._track_nav(page, no)
        self._ids()

    def _track_nav(self, page, no):
        """크롬 이력의 이동 종류로 가른다: typed = 사람이 주소줄에 친 것, 번호가 줄면 뒤로 가기 (2026-09-30 실험)."""
        try:
            cdp = self.context.new_cdp_session(page)
        except Exception:
            return
        last = {"i": None}

        def on_nav(frame):
            if frame is not page.main_frame:
                return                      # iframe 안 이동은 누른 것의 결과
            try:
                h = cdp.send("Page.getNavigationHistory")
            except Exception:
                return
            i, e = h["currentIndex"], h["entries"][h["currentIndex"]]
            prev, last["i"] = last["i"], i
            if prev is not None and i < prev:
                self._add({"kind": "back", "page": no, "url": rec.url_path(e["url"])})
            elif (prev is None or i > prev) and e["transitionType"] in ("typed", "generated", "auto_bookmark"):
                href = e.get("userTypedURL") or e["url"]
                if not href.startswith(("http://", "https://")):
                    href = e["url"]
                if href.startswith(("http://", "https://")):
                    self._add({"kind": "goto", "page": no, "url": rec.url_path(href), "href": href})
        page.on("framenavigated", on_nav)

    def _dialog(self, d):
        super()._dialog(d)
        self._ids()

    def _download(self, d):
        super()._download(d)
        self._ids()


def launch(p, **kw):
    """새 프로필 브라우저 (주소줄·탭 보임). 자동화 안내 띠·비밀번호 저장 제안·다운로드 알림은 끈다 (기록 중 화면을 가린다).
    못 띄우면 만든 프로필 폴더를 지우고 오류를 그대로 올린다."""
    prof = tempfile.mkdtemp(prefix=PROFILE_PREFIX)
    try:
        os.makedirs(os.path.join(prof, "Default"))
        with open(os.path.join(prof, "Default", "Preferences"), "w", encoding="utf-8") as f:
            json.dump({"credentials_enable_service": False, "profile": {"password_manager_enabled": False},
                       "download_bubble": {"partial_view_enabled": False}}, f)
        ctx = p.chromium.launch_persistent_context(prof, headless=False, no_viewport=True, accept_downloads=True,
                                                   ignore_default_args=["--enable-automation"], **kw)
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
        self.human = None                 # 시험: 사람 대신 조작할 함수

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
                    self.ui.put(("status", "브라우저를 닫아 기록을 끝냈습니다", MUTED))
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
        self.ui.put(("status", f"● {circled(no + 1)} {name} 기록 중 - 왼쪽 브라우저에서 평소처럼 하세요", RED))

    def _send_viewport(self):
        """기록 창 브라우저의 안쪽 크기 - 기록에 넣어 프리페어가 같은 크기로 연다."""
        try:
            self.page.wait_for_timeout(200)          # 창 크기를 바꾼 뒤 그려질 틈
            vp = self.page.evaluate("() => ({width: innerWidth, height: innerHeight})")
            self.ui.put(("viewport", self.rec_no, vp))
        except Exception:
            pass

    def _do_stop(self):
        self._close()
        self.ui.put(("status", "기록을 끝냈습니다 - 목록을 다듬고 [미리보기] 로 확인하세요", MUTED))
        self.ui.put(("recording_stopped",))

    def _do_dock(self, b):
        self.bounds = b
        if self.page and not self.page.is_closed():
            self._set_bounds(self.page, b)
            self._send_viewport()

    def _do_human(self):
        self.human(self.page)
        self.ui.put(("human_done",))

    def _do_preview(self, record, ids, creds, code, label):
        """새 프로필 브라우저로 켜 둔 단계를 따라 한다. 한 번 할 때마다 상태 기록 'observer' 한 건 (대시보드 '기록').
        로그에는 칸에 친 값·주소 ? 뒤를 싣지 않는다. 끝나면 (못 띄웠어도·중단해도) 늘 preview_done 과 프로필 지우기."""
        where = self._rec_bounds()
        stamp = lambda: datetime.datetime.now().strftime("[%H:%M:%S]")   # noqa: E731
        steps = record["steps"]
        st.start("observer", [(f"s{i}", rec.describe(s, hide_values=True)) for i, s in enumerate(steps, 1)], title=label)
        st.log_line(f"{stamp()} === 미리보기: {label} ({len(steps)}단계) ===")
        ok, why, note, saved, sec = False, "미리보기가 끝까지 가지 못했습니다", None, [], 0.0
        ctx = prof = None
        try:
            try:
                ctx, prof = launch(self.p, slow_mo=120)     # 새 프로필 = RPA 가 혼자 돌 때처럼 로그아웃 상태
            except Exception as e:
                why = note = f"미리보기 브라우저를 띄우지 못했습니다: {type(e).__name__}: {str(e).splitlines()[0]}"
                st.log_line(f"{stamp()} {why}")
                return
            rp = rec.Replayer(ctx, record, creds, PREVIEW_DL, code, review=True, hide_values=True,
                              log=lambda m: st.log_line(f"{stamp()} {m}"), step_timeout=20)
            rp.first_page = ctx.pages[0] if ctx.pages else None
            rp.page_hook = lambda pg: self._set_bounds(pg, where)               # 기록 창 자리에 겹쳐 띄운다
            rp.cancel, rp.pause = self.cancel, self.pause

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
            ok = rp.run()
            saved, sec = [os.path.basename(x) for x in rp.saved], rp.elapsed
            if not ok and self.cancel.is_set():
                why = note = "미리보기를 중단했습니다"
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
            self.ui.put(("preview_done", ok, saved, sec, note))


def new_preset(no, name=None, code=""):
    """화면이 들고 있는 프리셋 하나. raw = 이번에 기록한 단계, loaded = 저장돼 있던 기록 (둘 중 하나)."""
    return {"name": name or f"프리셋 {no}", "code": code, "raw": [], "loaded": None, "start_url": None,
            "enabled": {}, "deleted": set(), "id": "", "pw": "", "has_pw": False, "saved_at": None, "viewport": None,
            "fresh": False}     # fresh = 이번에 기록하고 아직 저장 안 함 (저장하면 그 프리셋은 꺼진 채로)


def load_presets():
    """저장된 프리셋과 그 아이디 (비밀번호는 있는지만). 설정이나 프리셋 파일이 깨졌으면 ValueError - 덮어쓰지 않게 열지 않는다."""
    sites = st.read_user_config().get(st.SITES_SECTION) or {}
    out = []
    for p in st.read_presets():
        q = new_preset(p["no"], p["name"], p["code"])
        q["saved_at"] = p["saved_at"]
        r = p["record"]
        if r and r.get("steps"):
            for k, s in enumerate(r["steps"]):
                s["id"] = k
            q["loaded"], q["viewport"] = r, r.get("viewport")
        site = sites.get(st.preset_site_key(p["no"])) if isinstance(sites, dict) else None
        if isinstance(site, dict):
            q["id"], q["has_pw"] = site.get("ID") or "", bool(site.get("PW"))
        out.append(q)
    return out


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


def store(files, logins, fresh=()):
    """프리셋 파일과 Sites 의 PRESETn 을 쓴다. 못 쓰면 화면에 보일 문장 (콘솔 없는 exe 라 조용히 넘어가면 안 된다), 되면 None."""
    try:
        st.write_presets(files)
        st.save_preset_sites(files, logins, fresh=fresh)
    except (OSError, ValueError, RuntimeError) as e:
        return f"저장하지 못했습니다: {e} - 잠시 뒤 다시 저장하세요"
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
            return p["no"], f"{tag}: 사이트코드는 숫자 세 자리여야 합니다 (받은 파일 이름 앞에 붙어 루틴이 알아봅니다)"
        if p["code"] in codes:
            return p["no"], (f"{tag}: 사이트코드 {p['code']} 를 {codes[p['code']]} 도 씁니다 - "
                             "루틴은 한 사이트코드에 파일 하나만 올립니다")
        codes[p["code"]] = tag
        if not (p.get("id") or "").strip():
            return p["no"], f"{tag}: 아이디를 넣으세요 (프리페어가 이 아이디로 로그인합니다)"
        if not (p.get("pw") or p.get("has_pw")):
            return p["no"], f"{tag}: 비밀번호를 넣으세요"
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
        if fake_creds and not any(p["loaded"] for p in self.presets):      # 시험: 가짜 쇼핑몰 계정
            self.presets[0].update(name="가짜 쇼핑몰", code="012", id=fake_creds[0], pw=fake_creds[1])
        self.cur, self.recording, self.previewing = 0, None, False
        self.paused = self.stopping = self.closing = False      # 미리보기 [Ⅱ 일시정지]·[■ 중단]·일시정지 중 창 닫기
        self.tell, self.ask = messagebox.showinfo, messagebox.askyesno     # 시험이 갈아 끼운다
        self.labels, self.base, self.shown, self._dock_job = {}, {}, 0, None
        self.start_url = None           # 시험: 주소를 치지 않고 바로 연다
        self.ui = queue.Queue()
        L, T, R, B = work_area()
        m = int(10 * scale)
        L, T, R, B = L + m, T + m, R - m, B - m
        self.panel_w = max(int((R - L) * 0.30), int(460 * scale))
        self.browser_w = (R - L) - self.panel_w
        root.title("AFTER MARKET - 옵저버")
        root.configure(bg=BG)
        root.geometry(f"{self.panel_w}x{B - T - int(32 * scale)}+{L + self.browser_w}+{T}")
        self.name_var, self.code_var = tk.StringVar(root), tk.StringVar(root)
        self.id_var, self.pw_var = tk.StringVar(root), tk.StringVar(root)
        self._build()
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
        tk.Label(head, text="쇼핑몰마다 프리셋 하나 - 로그인부터 엑셀 받기까지 한 번 해 보이면 RPA 가 따라 합니다",
                 font=F_SMALL, bg=BG, fg=MUTED, anchor="w", justify="left", wraplength=self.panel_w - 2 * pad).pack(fill="x")

        # 프리셋 줄
        card = tk.Frame(root, bg=CARD, highlightthickness=1, highlightbackground=LINE)
        card.pack(fill="x", padx=pad, pady=6)
        inner = tk.Frame(card, bg=CARD)
        inner.pack(fill="x", padx=12, pady=10)
        tk.Label(inner, text="프리셋", font=F_BOLD, bg=CARD, fg=INK).pack(anchor="w")
        self.preset_bar = tk.Frame(inner, bg=CARD)
        self.preset_bar.pack(fill="x", pady=(6, 8))
        form = tk.Frame(inner, bg=CARD)
        form.pack(fill="x")
        tk.Label(form, text="이름", font=F, bg=CARD, fg=MUTED).grid(row=0, column=0, sticky="w")
        self._entry(form, self.name_var, 18).grid(row=0, column=1, sticky="we", padx=(6, 12), ipady=3)
        tk.Label(form, text="사이트코드", font=F, bg=CARD, fg=MUTED).grid(row=0, column=2, sticky="w")
        self._entry(form, self.code_var, 5).grid(row=0, column=3, sticky="w", padx=(6, 0), ipady=3)
        form.columnconfigure(1, weight=1)
        self.name_var.trace_add("write", lambda *a: self._field_changed())
        self.code_var.trace_add("write", lambda *a: self._field_changed())

        # 상태 + 기록 단추
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

        # 미리보기용 계정 + 단추
        bot = tk.Frame(root, bg=BG)
        bot.pack(fill="x", padx=pad, pady=(6, pad))
        acc = tk.Frame(bot, bg=BG)
        acc.pack(fill="x")
        tk.Label(acc, text="아이디", font=F, bg=BG, fg=MUTED).grid(row=0, column=0, sticky="w")
        self._entry(acc, self.id_var, 13).grid(row=0, column=1, sticky="we", padx=(6, 12), ipady=3)
        tk.Label(acc, text="비밀번호", font=F, bg=BG, fg=MUTED).grid(row=0, column=2, sticky="w")
        self._entry(acc, self.pw_var, 13, show="•").grid(row=0, column=3, sticky="we", padx=(6, 0), ipady=3)
        acc.columnconfigure(1, weight=1)
        acc.columnconfigure(3, weight=1)
        self.pw_hint = tk.Label(bot, text="", font=F_SMALL, bg=BG, fg=MUTED, anchor="w", justify="left",
                                wraplength=self.panel_w - 2 * pad)
        self.pw_hint.pack(fill="x", pady=(3, 8))
        self.msg = tk.Label(bot, text="", font=F, bg=BG, fg=MUTED, anchor="w", justify="left",
                            wraplength=self.panel_w - 2 * pad)
        self.msg.pack(fill="x", pady=(0, 8))
        btns = tk.Frame(bot, bg=BG)
        btns.pack(fill="x")
        self.save_btn = button(btns, "저장", GREEN, GREEN_D, self.save, width=8)
        self.save_btn.pack(side="right")
        self.prev_btn = button(btns, "▶  미리보기", BLUE, BLUE_D, self.preview, width=12)
        self.prev_btn.pack(side="right", padx=8)

    def paint_presets(self):
        for c in self.preset_bar.winfo_children():
            c.destroy()
        busy = self.recording is not None or self.previewing
        for i, p in enumerate(self.presets):
            has = bool(p["raw"] or p["loaded"])
            sel = i == self.cur
            bg, fg = (BLUE, "white") if sel else ((BLUE_L, BLUE_D) if has else ("#f3f4f6", MUTED))
            if self.recording == i:
                bg, fg = RED, "white"
            b = tk.Button(self.preset_bar, text=circled(i + 1), font=(UI, 14, "bold"), bg=bg, fg=fg, activebackground=bg,
                          activeforeground=fg, relief="flat", bd=0, width=3, pady=2, cursor="hand2" if not busy else "arrow",
                          disabledforeground=fg, command=lambda i=i: self.select(i))
            b.config(state="disabled" if busy and not sel else "normal")
            b.pack(side="left", padx=(0, 4))
        small = dict(font=(UI, 13, "bold"), relief="flat", bd=0, width=3, pady=1, bg=CARD, fg=MUTED, activebackground=LINE,
                     highlightthickness=1, highlightbackground=LINE)
        if len(self.presets) < MAX_PRESETS:
            tk.Button(self.preset_bar, text="+", command=self.add_preset, state="disabled" if busy else "normal",
                      cursor="hand2", **small).pack(side="left", padx=(6, 2))
        if len(self.presets) > MIN_PRESETS:
            tk.Button(self.preset_bar, text="−", command=self.remove_preset, state="disabled" if busy else "normal",
                      cursor="hand2", **small).pack(side="left", padx=2)
        tk.Label(self.preset_bar, text=f"{len(self.presets)}/{MAX_PRESETS}", font=F_SMALL, bg=CARD, fg=MUTED).pack(side="right")

    def paint_buttons(self):
        rec_on = self.recording is not None
        self.rec_btn.config(text="■  기록 끝" if rec_on else "●  기록 시작")
        enable(self.rec_btn, not self.previewing and (not rec_on or self.recording == self.cur))
        if self.previewing:         # 창을 닫는 대신 멈추는 단추 (2026-10-02 - 미리보기 중에는 창이 안 닫힌다)
            skin(self.prev_btn, "▶  계속" if self.paused else "Ⅱ  일시정지", BLUE, BLUE_D, self.toggle_pause)
            skin(self.save_btn, "■  중단", RED, RED_D, self.stop_preview)
            enable(self.prev_btn, not (self.stopping or self.closing))
            enable(self.save_btn, not (self.stopping or self.closing))
        else:
            p = self.presets[self.cur]
            final = None if rec_on else self._final(p)
            kept = bool(final) and bool(self._kept(p, final))
            skin(self.prev_btn, "▶  미리보기", BLUE, BLUE_D, self.preview)
            skin(self.save_btn, "저장", GREEN, GREEN_D, self.save)
            enable(self.prev_btn, kept)
            enable(self.save_btn, kept)     # 기록이 끝나 있고 켜 둔 단계가 한 줄은 있어야 (2026-10-02)
        self.paint_presets()

    def _load_fields(self):
        p = self.presets[self.cur]
        self._loading = True
        self.name_var.set(p["name"])
        self.code_var.set(p["code"])
        self.id_var.set(p["id"])
        self.pw_var.set(p["pw"])
        self._loading = False
        self.pw_hint.config(text=("저장된 비밀번호가 있습니다 - 바꿀 때만 넣으세요. " if p["has_pw"] else "")
                            + "아이디·비밀번호는 저장하면 이 PC 의 설정에 잠가서 넣습니다. 기록 파일·대시보드에는 안 갑니다.")

    def _store_fields(self):
        p = self.presets[self.cur]
        p.update(name=self.name_var.get().strip() or p["name"], code=self.code_var.get().strip(),
                 id=self.id_var.get(), pw=self.pw_var.get())

    def _field_changed(self):
        if not getattr(self, "_loading", False) and hasattr(self, "list_title"):
            self._store_fields()
            self._title()

    def _title(self):
        p = self.presets[self.cur]
        self.list_title.config(text=f"{circled(self.cur + 1)} {p['name']} - 기록한 단계")

    def select(self, i):
        if i == self.cur:
            return
        self._store_fields()
        self.cur, self.shown = i, 0
        self._load_fields()
        self.msg.config(text="")
        self.render()

    def add_preset(self):
        self._store_fields()
        self.presets.append(new_preset(len(self.presets) + 1))
        self.select(len(self.presets) - 1)

    def remove_preset(self):
        p = self.presets[-1]
        if (p["raw"] or p["loaded"]) and not messagebox.askyesno(
                "프리셋 지우기", f"{circled(len(self.presets))} {p['name']} 에 기록이 있습니다. 지울까요?"):
            return
        self._store_fields()
        self.presets.pop()
        if self.cur >= len(self.presets):
            self.cur = len(self.presets) - 1
            self._load_fields()
        self.render()

    # --- 기록 목록 ---
    def _final(self, p):
        if p["raw"]:
            start = p["start_url"] or next((s["href"] for s in p["raw"] if s["kind"] == "goto"), "")
            return rec.finalize(json.loads(json.dumps(p["raw"])), datetime.date.today(), start, viewport=p["viewport"])
        return p["loaded"]

    def _var(self, p, sid):
        return p["enabled"].setdefault(sid, tk.BooleanVar(self.root, value=True))

    def _kept(self, p, final):
        return [i for i, s in enumerate(final["steps"]) if s["id"] not in p["deleted"] and self._var(p, s["id"]).get()]

    def render(self):
        for c in self.inner.winfo_children():
            c.destroy()
        self.labels, self.base = {}, {}
        p = self.presets[self.cur]
        final = self._final(p)
        n = 0
        for s in final["steps"] if final else []:
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
            tk.Label(row, text=f"{n:2d}", font=F_SMALL, bg=CARD, fg=MUTED, width=3, anchor="e").pack(side="left", anchor="n", pady=6)
            text = re.sub(r" \(\d+단계 뒤에 새로 생긴 것\)", " (새로 생긴 것)", rec.describe(s))
            warn = s["kind"] == "goto" and "깨질 수" in text
            lab = tk.Label(row, text=text, font=F, bg=CARD, anchor="w", justify="left",
                           fg=(RED_D if warn else INK) if on else "#9ca3af",
                           wraplength=self.panel_w - int(170 * self.scale))
            lab.pack(side="left", fill="x", expand=True, padx=(6, 0), pady=6)
            self.labels[sid], self.base[sid] = lab, text
        if not n:
            tip = ("위 [● 기록 시작] 을 누르고, 왼쪽 브라우저 주소줄에 쇼핑몰 주소를 치세요.\n"
                   "로그인부터 엑셀 받기까지 평소처럼 하면 여기에 단계가 쌓입니다.") if self.recording is None else \
                "왼쪽 브라우저 주소줄에 쇼핑몰 주소를 치고 Enter 를 누르세요."
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
        if (p["raw"] or p["loaded"]) and not messagebox.askyesno(
                "다시 기록", f"{circled(self.cur + 1)} {p['name']} 의 기록을 지우고 처음부터 다시 기록할까요?"):
            return
        p.update(raw=[], loaded=None, start_url=self.start_url, enabled={}, deleted=set())
        self.recording, self.shown = self.cur, 0
        self.msg.config(text="")
        self.status.config(text="브라우저를 여는 중…", fg=MUTED)
        self.render()
        self.worker.cmd.put(("record", self.cur, p["name"], self.start_url))

    def preview(self):
        self._store_fields()
        p = self.presets[self.cur]
        final = self._final(p)
        if not final:
            return self.msg.config(text="미리보기할 기록이 없습니다", fg=RED)
        kept = self._kept(p, final)
        if not kept:
            return self.msg.config(text="켜 둔 단계가 없습니다", fg=RED)
        pw = p["pw"] or (stored_password(self.cur + 1) if p["has_pw"] else "")
        if not p["id"].strip() or not pw:
            return self.msg.config(text="아이디·비밀번호를 넣어야 미리보기를 할 수 있습니다", fg=RED)
        r = rec.keep_steps(final, kept)
        ids = [s["id"] for s in r["steps"]]
        self.render()
        self.worker.cancel.clear()          # 명령보다 먼저 - 일꾼이 받기 전에 누른 [■ 중단] 을 지우지 않게
        self.worker.pause.clear()
        self.previewing, self.paused, self.stopping = True, False, False
        self.paint_buttons()
        self.msg.config(text="미리보기 중 - 새 브라우저가 같은 자리에서 따라 합니다. 보기만 하세요", fg=BLUE)
        self.worker.cmd.put(("preview", r, ids, {"ID": p["id"].strip(), "PW": pw}, p["code"] or "000",
                             f"{circled(self.cur + 1)} {p['name']}"))

    def toggle_pause(self):
        """[Ⅱ 일시정지]: 지금 단계를 마치고 다음 단계 앞에서 기다린다. [▶ 계속] 이면 이어 간다."""
        self.paused = not self.paused
        (self.worker.pause.set if self.paused else self.worker.pause.clear)()
        self.msg.config(text="일시정지 - 지금 단계를 마치고 멈춥니다" if self.paused else
                        "미리보기 중 - 새 브라우저가 같은 자리에서 따라 합니다. 보기만 하세요", fg=BLUE)
        self.paint_buttons()

    def stop_preview(self):
        """[■ 중단]: 찾거나 기다리던 것을 그만두고 브라우저를 닫는다 (대개 1초 안). 끝나면 preview_done."""
        self.stopping = True
        self.worker.cancel.set()
        self.msg.config(text="중단하는 중…", fg=MUTED)
        self.paint_buttons()

    def save(self):
        if self.recording is not None or self.previewing:
            return None                     # 단추가 잠겨 있다 - 기록·미리보기가 끝난 뒤에만 (2026-10-02)
        self._store_fields()
        try:
            cfg = st.read_user_config()
        except ValueError as e:
            return self.msg.config(text=f"사용자 설정을 읽지 못했습니다: {e}", fg=RED)
        if not cfg:
            return self.msg.config(text="이 PC 의 사용자 설정이 없습니다 - 시작 메뉴 'RPA 설정' 에서 먼저 저장하세요", fg=RED)
        now = datetime.datetime.now().isoformat(timespec="seconds")
        out = []
        for no, p in enumerate(self.presets, 1):
            final, r = self._final(p), None
            if final and final["steps"]:
                r = rec.keep_steps(final, self._kept(p, final))
                for s in r["steps"]:
                    s.pop("id", None)
            out.append({"no": no, "name": p["name"], "code": p["code"], "record": r,
                        "id": p["id"], "pw": p["pw"], "has_pw": p["has_pw"]})
        problem = validate_presets(out)
        if problem:
            self.select(problem[0] - 1)
            return self.msg.config(text=problem[1], fg=RED)
        for o in out:
            if o["record"]:
                scrub_login(o["record"], o["id"])      # 아이디는 기록에 글자로 안 남긴다 (설정의 아이디로 친다)
        try:
            old = {p["no"]: p for p in st.read_presets()}
        except ValueError:
            old = {}                                   # 예전 파일을 못 읽으면 기록 있는 것은 모두 오늘 날짜
        sites = cfg.get(st.SITES_SECTION)
        sites = sites if isinstance(sites, dict) else {}
        logins_changed = {o["no"] for o in out if o["pw"] or o["id"].strip() != (
            (sites.get(st.preset_site_key(o["no"])) or {}).get("ID") or "")}
        files = keep_dates([{k: o[k] for k in ("no", "name", "code", "record")} for o in out], old, logins_changed, now)
        for o in out:
            try:
                pw = o["pw"] or (stored_password(o["no"]) if o["has_pw"] else "")
            except RuntimeError as e:
                return self.msg.config(text=f"{circled(o['no'])} 저장된 비밀번호를 풀지 못했습니다 ({e}) - 비밀번호를 다시 넣고 "
                                            "저장하세요", fg=RED)
            if any(password_in_record(f["record"], pw) for f in files):    # 비밀번호 칸이 아닌 곳에 비밀번호를 친 경우
                self.select(o["no"] - 1)
                return self.msg.config(text=f"{circled(o['no'])} 기록에 비밀번호로 보이는 글자가 있어 저장하지 않았습니다 - "
                                            "그 단계를 지우세요", fg=RED)
        fresh = {o["no"] for p, o in zip(self.presets, out) if o["record"] and p.get("fresh")}
        problem = store(files, {o["no"]: (o["id"].strip(), o["pw"] or None) for o in out if o["record"]}, fresh)
        if problem:
            return self.msg.config(text=problem, fg=RED)
        for p, f in zip(self.presets, files):
            if f["record"]:
                p.update(pw="", has_pw=True, saved_at=f["saved_at"], fresh=False)
        self._load_fields()
        n = sum(1 for o in out if o["record"])
        self.msg.config(text=f"저장했습니다 - 기록 있는 프리셋 {n}개. 새로 기록한 프리셋은 꺼진 채입니다: 대시보드 환경설정 "
                             "'쇼핑몰 프리셋' 에서 켜면 다음 프리페어부터 돕니다.", fg=GREEN_D)
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
                elif m[0] == "status":
                    self.status.config(text=m[1], fg=m[2])
                elif m[0] == "ready":
                    self.status.config(text="프리셋을 고르고 [● 기록 시작] 을 누르세요", fg=MUTED)
                    self.render()
                    self.on_ready()
                elif m[0] == "recording":
                    self.on_recording()
                elif m[0] == "recording_stopped":
                    self.recording = None
                    dirty = True
                    self.on_stopped()
                elif m[0] == "progress":
                    self._progress(*m[1:])
                elif m[0] == "paused":
                    self.msg.config(text="일시정지했습니다 - [▶ 계속] 으로 이어 가거나 [■ 중단] 하세요. 지금은 창을 닫아도 됩니다",
                                    fg=BLUE)
                    self.on_paused()
                elif m[0] == "preview_done":
                    ok, saved, sec, note = m[1:]
                    stopped = self.stopping
                    self.previewing = self.paused = self.stopping = False
                    if self.closing:            # 일시정지 중에 창을 닫았다 - 브라우저·프로필 정리가 끝났다
                        return self._close_now()
                    self.paint_buttons()
                    if ok:
                        self.msg.config(text=f"미리보기 성공 ({sec:.0f}초) - 받은 파일: {', '.join(saved) or '없음'}", fg=GREEN_D)
                    elif stopped:
                        self.msg.config(text="미리보기를 중단했습니다", fg=MUTED)
                    else:
                        self.msg.config(text=note or "미리보기가 멈췄습니다 - 빨간 단계를 끄거나 지운 뒤 다시 해 보세요", fg=RED)
                    self.on_preview_done(ok)
                elif m[0] == "human_done":
                    self.on_human_done()
        except queue.Empty:
            pass
        if dirty and not self.previewing:
            self.render()
        self.root.after(80, self._poll)

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
        if self.previewing and not (self.paused or self.stopping):
            return self.tell("미리보기 중", "미리보기 중에는 창을 닫을 수 없습니다.\n[Ⅱ 일시정지] 나 [■ 중단] 을 누른 뒤 닫으세요.")
        if any(p.get("fresh") for p in self.presets) and not self.ask(
                "저장하지 않은 기록", "저장하지 않은 기록이 있습니다. 저장하지 않고 닫을까요?"):
            return
        if self.previewing:
            self.closing = True
            self.worker.cancel.set()
            self.msg.config(text="미리보기를 멈추고 닫는 중…", fg=MUTED)
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
        return (f"이 PC 에 로그인한 윈도우 계정({session})이 아니라 다른 계정({me})의 관리자 권한으로 옵저버가 떴습니다.\n"
                f"비밀번호는 윈도우 계정마다 잠겨서 다른 계정으로 저장하면 RPA 가 풀지 못합니다. {session} 계정으로 다시 여세요.")
    return None


def busy_problem():
    """다른 옵저버·RPA 와 부딪히면 사람에게 보일 문장, 아니면 None. 먼저 옵저버 잠금을 쥔다 - 쥔 동안 대시보드는
    RPA 를 안 띄우고 자동 실행은 닫힐 때까지 기다린다 (rpa_dashboard). 잠금은 이 프로세스가 끝나면 (죽어도) 윈도우가 푼다."""
    if not st.hold_lock(st.OBSERVER_LOCK):
        return "옵저버가 이미 켜져 있습니다. 작업 표시줄에서 그 창을 쓰세요."
    # ponytail: 예약이 RPA 를 띄우고 RPA 가 '도는 중' 을 적기까지 몇 초 틈은 못 막는다 (그 사이 켜면 둘 다 뜬다)
    running = [st.PROGRAMS.get(p, p) for p in st.running_programs()]
    if running:
        return (f"{', '.join(running)} 가 돌고 있습니다. 끝난 뒤 옵저버를 여세요.\n"
                "RPA 가 화면·마우스를 쓰는 동안 기록하면 서로 부딪힙니다.")
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
        print(f"문제: 프리셋 파일을 읽지 못했습니다 ({e})")
    browsers = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright")
    print(f"브라우저: {browsers} ({'있음' if os.path.isdir(browsers) else '없음'})")
    try:
        root = tk.Tk()
        root.withdraw()
        print(f"Tcl/Tk: {root.tk.eval('info patchlevel')}")
        root.destroy()
    except Exception as e:
        print(f"문제: Tcl/Tk 를 불러오지 못했습니다 ({type(e).__name__}: {e})")
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
        show_error("관리자 권한이 있어야 기록을 저장할 수 있습니다. 다시 열고 '예' 를 누르세요.")
        return 1
    problem = start_problem() or busy_problem()
    if problem:
        show_error(problem)
        return 1
    sweep_profiles()                    # 잠금을 쥔 뒤 - 지난번에 못 지운 프로필 (로그인 쿠키)
    try:
        presets = load_presets()
    except ValueError as e:
        show_error(f"설정을 읽지 못해 옵저버를 열지 않습니다 (덮어쓰지 않게).\n{st.presets_path()}\n{e}\n"
                   "고치거나 지운 뒤 다시 여세요.")
        return 1
    scale = dpi_scale()
    root = new_root()
    App(root, scale, presets)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
