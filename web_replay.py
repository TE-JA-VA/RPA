# -*- coding: utf-8 -*-
"""사이트를 가리지 않는 조작 기록·재생 엔진 (옵저버 rpa_observer 와 프리페어 web_runner 의 replay 가 쓴다).

기록: 누른 것마다 단서를 여러 개 적는다 (id·글자·name·안내 글·칸 이름·위치·같은 글자 중 몇 번째).
      비밀번호 칸은 값을 아예 받지 않는다. 아이디는 '설정의 아이디' 로 바꿔 적는다. 사람이 한 것만 적는다 (isTrusted).
재생: 단서를 차례로 써서 하나로 정해지고 모양이 같은 것을 누른다. 가려진 메뉴는 마우스를 올려 열고,
      예상 밖 공지는 닫고, '있을 때만' 단계는 없으면 건너뛰고, 날짜는 오늘 기준으로 바꾼다.
설계: docs/superpowers/specs/2026-09-30-shop-record-replay-design.md 3절. 시험: tests/test_web_replay.py
"""
import datetime
import json
import os
import re
import time
import urllib.parse

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

JS = r"""
(() => {
  // 문서마다 한 번. window 에 표시하면 안 된다: 새 창은 빈 페이지(about:blank)의 window 를 진짜 주소에서도 그대로 써서
  // 진짜 페이지에 귀를 달지 않고 넘어간다 (2026-09-30 시험에서 새 창의 조작이 통째로 빠졌다)
  if (document.__recOn) return; document.__recOn = true;
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const ACT = 'a,button,input,select,textarea,label,summary,[role=button],[role=link],[role=menuitem],[role=tab],[role=option],[onclick]';
  const BTN = ['button', 'submit', 'reset'];
  const CLICKABLE = __CLICKABLE__;
  const sig = __SIG__;
  function textOf(el) {           // 칸의 값은 절대 담지 않는다 (아이디·비밀번호가 단서에 들어간다)
    const tag = el.tagName;
    if (tag === 'INPUT') return BTN.includes((el.type || '').toLowerCase()) ? norm(el.value) : '';
    if (tag === 'TEXTAREA' || tag === 'SELECT') return '';
    return norm(el.textContent).slice(0, 80);
  }
  function labelOf(el) {          // 칸 이름: <label for>, 아니면 같은 줄의 th (그 줄에서 몇 번째 칸인지도)
    if (!['INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName)) return ['', 0, ''];
    if (el.labels && el.labels.length) return [norm(el.labels[0].textContent), 0, 'for'];
    const tr = el.closest('tr'), th = tr && tr.querySelector('th');
    if (th) return [norm(th.textContent), [...tr.querySelectorAll(el.tagName)].indexOf(el) + 1, 'th'];
    return ['', 0, ''];
  }
  function cssPath(el) {
    const parts = [];
    for (; el && el.nodeType === 1 && el !== document.body && el !== document.documentElement; el = el.parentElement) {
      let i = 1; for (let s = el; (s = s.previousElementSibling);) if (s.tagName === el.tagName) i++;
      parts.unshift(el.tagName.toLowerCase() + ':nth-of-type(' + i + ')');
    }
    return 'body > ' + parts.join(' > ');
  }
  function inOverlay(el) {
    for (let e = el; e && e !== document.body; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if ((cs.position === 'fixed' || cs.position === 'absolute') && +cs.zIndex >= 10 && e.offsetWidth > 150) return true;
    }
    return false;
  }
  function describe(el) {
    const t = textOf(el), tag = el.tagName.toLowerCase();
    const same = t ? [...document.querySelectorAll(tag)].filter(e => textOf(e) === t) : [];
    const [label, labelIndex, labelKind] = labelOf(el);
    return {tag, id: el.id || '', name: el.getAttribute('name') || '', type: (el.getAttribute('type') || '').toLowerCase(),
            text: t, textIndex: same.indexOf(el), textCount: same.length,
            aria: el.getAttribute('aria-label') || '', title: el.getAttribute('title') || '',
            placeholder: el.getAttribute('placeholder') || '', label, labelIndex, labelKind,
            href: el.getAttribute('href') || '', css: cssPath(el), inOverlay: inOverlay(el)};
  }
  function send(kind, el, extra) {
    try { window.__rec(Object.assign({kind, url: location.href, target: describe(el), t: Date.now()}, extra || {})); } catch (e) {}
  }
  // 누를 것마다 이 문서에 처음 나타난 시각. 재생은 '몇 단계 뒤에 나타난 것' 을 새로 생긴 것 중에서 고른다
  // (요청한 파일이 목록에 새 줄로 올라오는 것 - 그 사이 다른 곳을 눌러도 흔들리지 않게 '직전 조작' 이 아니라 나타난 시각으로)
  // appeared: 없다가 나타난 가장 최근 시각 (마우스를 올리면 만들어졌다 떼면 지워지는 메뉴를 알아챈다).
  // 1초마다 innerHTML 로 다시 그리는 목록은 훑을 때마다 늘 있어서 appeared 가 바뀌지 않는다
  const firstSeen = new Map(), appeared = new Map();
  let present = new Set();
  function scan() {
    const now = Date.now(), cur = new Set();
    for (const el of document.querySelectorAll(CLICKABLE)) {
      const g = sig(el); cur.add(g);
      if (!firstSeen.has(g)) firstSeen.set(g, now);
      if (!present.has(g)) appeared.set(g, now);
    }
    present = cur;
  }
  // 마우스가 올라간 누를 만한 것들 (최근 20개) - 올리자마자 새로 나타난 것을 누르면 그 올린 것을 '마우스 올리기' 단계로
  const hovers = [];
  document.addEventListener('mouseover', e => {
    if (!e.isTrusted) return;
    const h = e.target.closest(ACT + ',li,[role=menuitem]') || (getComputedStyle(e.target).cursor === 'pointer' ? e.target : null);
    if (!h || (hovers.length && hovers[hovers.length - 1].el === h)) return;
    hovers.push({el: h, t: Date.now()});
    if (hovers.length > 20) hovers.shift();
  }, true);
  function hoverBefore(el, ap) {
    for (let i = hovers.length - 1; ap && i >= 0; i--) {
      const hv = hovers[i];
      if (hv.el === el || el.contains(hv.el) || !hv.el.isConnected) continue;
      if (hv.t <= ap && ap - hv.t < 1500) return {target: describe(hv.el), t: hv.t};
      if (hv.t < ap - 1500) break;
    }
    return null;
  }
  let pending = 0;
  new MutationObserver(() => { if (!pending) pending = setTimeout(() => { pending = 0; scan(); }, 50); })
    .observe(document, {childList: true, subtree: true});
  scan();
  let lastEnter = 0;
  document.addEventListener('click', e => {
    if (!e.isTrusted) return;
    if (e.detail === 0 && Date.now() - lastEnter < 500) return;          // Enter 가 만든 단추 눌림
    const act = e.target.closest(ACT), el = act || e.target;
    if (!act && getComputedStyle(el).cursor !== 'pointer') return;       // 글자·표 칸·빈 곳 (사람은 기다리며 여기저기 누른다)
    const tag = el.tagName, type = (el.type || '').toLowerCase();
    if (tag === 'SELECT' || tag === 'OPTION' || tag === 'TEXTAREA') return;   // 값 바뀜으로 적는다
    if (tag === 'INPUT' && !BTN.includes(type) && type !== 'image') return;  // 글자 칸·체크 상자도
    let seen = null, hover = null;
    if (el.matches(CLICKABLE)) { scan(); const g = sig(el); seen = firstSeen.get(g) || null; hover = hoverBefore(el, appeared.get(g)); }
    send('click', el, {detail: e.detail, firstSeen: seen, hover});
  }, true);
  document.addEventListener('input', e => {
    const el = e.target;
    if (!e.isTrusted || !['INPUT', 'TEXTAREA'].includes(el.tagName) || ['checkbox', 'radio'].includes(el.type)) return;
    if (el.type === 'password') send('secret', el); else send('fill', el, {value: el.value});
  }, true);
  document.addEventListener('change', e => {
    const el = e.target;
    if (!e.isTrusted) return;
    if (el.tagName === 'SELECT') { const o = el.options[el.selectedIndex]; send('select', el, {value: el.value, option: norm(o && o.text)}); }
    else if (['checkbox', 'radio'].includes(el.type)) send('check', el, {checked: el.checked});
  }, true);
  document.addEventListener('keydown', e => {
    if (e.isTrusted && e.key === 'Enter' && e.target.tagName === 'INPUT') { lastEnter = Date.now(); send('enter', e.target); }
  }, true);
})();
"""

# '새로 생긴 것' 을 가리는 표시: 주소(또는 onclick) + 그 줄의 글자. 옵저버와 재생기가 같은 것을 쓴다
CLICKABLE = "a,button,input[type=button],input[type=submit],[onclick],[role=button],[role=link]"
SIG = ("el => (el.getAttribute('href') || el.getAttribute('onclick') || '') + '|' + "
       "(((el.closest('tr,li') || el).textContent) || '').replace(/\\s+/g, ' ').trim().slice(0, 120)")
JS = JS.replace("__CLICKABLE__", json.dumps(CLICKABLE)).replace("__SIG__", SIG)
SNAP_JS = f"() => [...document.querySelectorAll({json.dumps(CLICKABLE)})].map({SIG})"
SIGS_JS = f"els => els.map({SIG})"
# 화면이 0.4초 동안 안 바뀔 때까지 (최대 2.5초) - 늦게 그려지는 목록을 기다린다
QUIET_JS = """() => new Promise(res => {
  let t, hard;
  const mo = new MutationObserver(() => { clearTimeout(t); t = setTimeout(done, 400); });
  function done() { mo.disconnect(); clearTimeout(t); clearTimeout(hard); res(true); }
  mo.observe(document, {subtree: true, childList: true, characterData: true});
  t = setTimeout(done, 400); hard = setTimeout(done, 2500);
})"""

KINDS_MERGE = ("fill", "secret", "select")        # 같은 칸에 잇달아 온 것은 마지막 값 하나로
CLOSE_TEXTS = ("닫기", "오늘 하루 보지 않기", "오늘하루 보지않기", "오늘 하루 열지 않기", "x", "×", "close")
DATE_FORMATS = ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d", "%Y%m%d")
OPTIONAL_WAIT = 3.0
RECORD_VERSION = 1           # 기록 모양. 다르면 재생하지 않는다 (옛 프리페어가 새 기록을 잘못 따라 하지 않게)
DOWNLOAD_TIMEOUT_MS = 60000  # 파일 받기를 기다리는 시간 (안 오면 그 단계 실패)
CUT = 20                     # 대시보드로 가는 설명에서 누른 것의 글자 길이
SETTLE_MAX_MS = 3000        # 단계 사이 기다림 상한 (사람이 기다린 시간의 절반). 시험에서 0 으로도 돌려 본다
TEXT_OF = """e => { const n = s => (s || '').replace(/\\s+/g, ' ').trim(); const t = e.tagName;
  if (t === 'INPUT') return ['button','submit','reset'].includes((e.type||'').toLowerCase()) ? n(e.value) : '';
  if (t === 'TEXTAREA' || t === 'SELECT') return ''; return n(e.textContent).slice(0, 80); }"""


def user_tab(page):
    """사람이 Ctrl+T·+ 로 연 탭 (페이지가 연 창이 아니다)."""
    try:
        return page.opener() is None and page.url.startswith("chrome://")
    except Exception:
        return False


NAV_KINDS = ("goto", "back", "newtab")
SESSION_Q = re.compile(r"(?i)[?&](sid|sess\w*|jsessionid|token|auth\w*)=")
URL_QUERY = re.compile(r"(https?://[^\s?#'\"]*)[?#][^\s'\"]*")   # 실패 사유의 주소에서 ? 뒤 (대시보드로 갈 때 뺀다)


def url_path(url):
    return urllib.parse.urlparse(url).path


def frame_info(frame):
    return {"main": frame.parent_frame is None, "name": frame.name or "", "path": url_path(frame.url)}


def same_target(a, b):
    return a["page"] == b["page"] and a["frame"] == b["frame"] and a["target"]["css"] == b["target"]["css"]


# ---------------------------------------------------------------------------
# 기록
# ---------------------------------------------------------------------------
class Recorder:
    def __init__(self, context, sample_dir=None):
        self.steps, self.pages, self.sample_dir = [], [], sample_dir
        self.samples = []
        context.add_init_script(script=JS)
        context.expose_binding("__rec", self._event)
        context.on("page", self._page)

    def _no(self, page):
        if page not in self.pages:
            self.pages.append(page)
        return self.pages.index(page)

    def _page(self, page):
        no = self._no(page)
        if no and self.steps and not user_tab(page):
            self.steps[-1].setdefault("opens", no)       # 앞 동작이 새 창을 열었다 (사람이 연 새 탭은 아니다)
        page.on("dialog", self._dialog)
        page.on("download", self._download)
        # add_init_script 만 믿으면 안 된다: window.open 새 창은 빈 페이지에만 심기고 진짜 주소의 문서에는 안 심긴다
        # (2026-09-30 시험). 문서가 바뀔 때마다 한 번 더 심는다 - 문서마다 표시가 있어 두 번 붙지는 않는다
        page.on("framenavigated", self._inject)
        page.on("domcontentloaded", lambda pg: [self._inject(f) for f in pg.frames])

    def _inject(self, frame):
        try:
            frame.evaluate("() => {" + JS + "}")
        except Exception:
            pass                    # 그 사이 또 넘어간 문서

    def _dialog(self, d):
        if self.steps:
            self.steps[-1].setdefault("dialogs", []).append(d.message)
        d.accept()

    def _download(self, d):
        if self.steps:
            self.steps[-1]["download"] = d.suggested_filename
        if self.sample_dir:
            os.makedirs(self.sample_dir, exist_ok=True)
            path = os.path.join(self.sample_dir, d.suggested_filename)
            d.save_as(path)
            self.samples.append(path)

    def _event(self, source, ev):
        step = {"kind": ev["kind"], "page": self._no(source["page"]), "frame": frame_info(source["frame"]),
                "url": url_path(ev["url"]), "target": ev["target"], "t": ev["t"]}
        for k in ("value", "option", "checked", "firstSeen"):
            if k in ev:
                step[k] = ev[k]
        last = self.steps[-1] if self.steps else None
        if (step["kind"] == "click" and ev.get("detail", 1) >= 2 and last and last["kind"] == "click"
                and same_target(last, step) and step["t"] - last["t"] < 600):
            last["double"] = True           # 더블클릭은 한 단계 (재생이 두 번 요청하지 않게)
            return
        if last and step["kind"] in KINDS_MERGE and last["kind"] == step["kind"] and same_target(last, step):
            last.update({k: step[k] for k in ("value", "option", "t") if k in step})
            return
        hv = ev.get("hover")
        if step["kind"] == "click" and hv and (last is None or last["t"] < hv["t"]):
            # 마우스를 올리자 새로 나타난 것을 눌렀다 (그 사이 다른 조작 없음) - 재생 때 먼저 올려 메뉴를 만들게 한다
            self.steps.append({"kind": "hover", "page": step["page"], "frame": step["frame"], "url": step["url"],
                               "target": hv["target"], "t": hv["t"]})
        self.steps.append(step)


def parse_date(s):
    for fmt in DATE_FORMATS:
        try:
            return datetime.datetime.strptime(s.strip(), fmt).date(), fmt
        except (ValueError, AttributeError):
            pass
    return None


def finalize(steps, record_date, start_url, viewport=None):
    """기록을 다듬는다: 기다린 시간, 날짜는 오늘 기준, 공지 닫기는 '있을 때만', 아이디·비밀번호는 설정 값."""
    out, prev = [], None
    ts = [s["t"] for s in steps]
    for i, s in enumerate(steps):
        s = dict(s)
        seen = s.pop("firstSeen", None)
        if seen is not None:              # 몇 번째 단계를 한 뒤에 나타났나 (그 단계 전에는 없었다)
            k = max((j for j in range(i) if ts[j] < seen), default=None)
            if k is not None:
                s["appearsAfter"] = k
        s["gap"] = s["t"] - prev if prev else 0
        prev = s.pop("t")
        if s["kind"] == "fill" and parse_date(s.get("value", "")):
            d, fmt = parse_date(s["value"])
            s["date"] = {"offset": (d - record_date).days, "fmt": fmt}
        if s["kind"] == "click" and s["target"]["inOverlay"] and s["target"]["text"].lower() in CLOSE_TEXTS:
            s["optional"] = True
        out.append(s)
    for i, s in enumerate(out):
        if s["kind"] != "secret":
            continue
        s["credential"] = "PW"
        for p in reversed(out[max(0, i - 3):i]):         # 비밀번호 바로 앞 같은 화면의 글자 칸 = 아이디
            if p["kind"] == "fill" and p["page"] == s["page"] and p["frame"] == s["frame"]:
                p["credential"] = "ID"
                p.pop("value", None)
                break
    rec_obj = {"version": RECORD_VERSION, "start_url": start_url, "record_date": record_date.isoformat(), "steps": out}
    if viewport:
        rec_obj["viewport"] = viewport       # 기록 때 창 안쪽 크기 - 프리페어가 같은 크기로 연다
    return rec_obj


def keep_steps(rec_obj, keep):
    """keep(원래 번호들)만 남긴 기록. '몇 단계 뒤에 나타남' 번호는 남은 것 가운데 그 단계나 그 앞의 가장 가까운 것으로."""
    keep = sorted(keep)
    new_no = {old: new for new, old in enumerate(keep)}
    steps = []
    for old in keep:
        s = dict(rec_obj["steps"][old])
        k = s.pop("appearsAfter", None)
        if k is not None:
            before = [o for o in keep if o <= k]
            if before:
                s["appearsAfter"] = new_no[before[-1]]
        steps.append(s)
    return dict(rec_obj, steps=steps)


def record(start_url, out_path, headless=False, human=None, record_date=None, sample_dir=None):
    """브라우저를 띄워 기록한다. human(page) 를 주면 그 함수가 사람 대신 조작한다 (시험용)."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(accept_downloads=True)
        rec = Recorder(context, sample_dir)
        page = context.new_page()
        page.goto(start_url)
        if human:
            human(page)
        else:
            print("창에서 평소처럼 조작하세요. 파일을 받았으면 브라우저 창을 닫으면 끝납니다.")
            while context.pages:
                try:
                    context.pages[0].wait_for_timeout(500)
                except Exception:
                    pass
        result = finalize(rec.steps, record_date or datetime.date.today(), start_url)
        result["samples"] = [os.path.basename(x) for x in rec.samples]
        try:
            browser.close()
        except Exception:
            pass
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    return result


# ---------------------------------------------------------------------------
# 사람이 읽는 단계 설명 (검수용)
# ---------------------------------------------------------------------------
def name_of(s):
    t = s["target"]
    if s["kind"] in ("fill", "secret", "select", "check", "enter"):
        return t["label"] or t["placeholder"] or t["aria"] or t["title"] or t["name"] or t["tag"]
    return t["text"] or t["aria"] or t["title"] or t["placeholder"] or t["label"] or t["tag"]


def ambiguous(s):
    """글자로 하나로 정해지지 않는 누를 것 - 위치·순서로 고르니 '새로 생긴 것' 으로 거른다."""
    return s["kind"] == "click" and s["target"]["textCount"] != 1


def _cut(text, hide):
    return text if not hide or len(text) <= CUT else text[:CUT] + "…"


def describe(s, hide_values=False):
    """단계 한 줄 설명. hide_values 면 칸에 친 값과 주소의 ? 뒤를 빼고 누른 글자는 CUT 자까지 (대시보드로 가는 로그)."""
    k = s["kind"]
    n = _cut(name_of(s), hide_values) if "target" in s else ""
    if k == "goto":
        href = s["href"].split("?", 1)[0] if hide_values else s["href"]
        d = f"주소줄에 {href} 치고 이동"
        if SESSION_Q.search(s["href"]):
            d += " (주소에 로그인 세션 값이 있어 다음에 깨질 수 있음 - 메뉴로 가는 편이 안전)"
    elif k == "back":
        d = "뒤로 가기"
    elif k == "newtab":
        d = "새 탭 열기"
    elif k == "click":
        d = f"'{n}' 누르기"
    elif k == "fill":
        if s.get("credential") == "ID":
            v = "아이디 (설정 값)"
        elif s.get("date"):
            off = s["date"]["offset"]
            v = "오늘 날짜" if off == 0 else f"오늘{off:+d}일 날짜"
        else:
            v = "글자" if hide_values else f"'{s.get('value', '')}'"
        d = f"'{n}' 칸에 {v} 넣기"
    elif k == "secret":
        d = f"'{n}' 칸에 비밀번호 (설정 값) 넣기"
    elif k == "select":
        d = f"'{n}' 에서 '{_cut(str(s.get('option')), hide_values)}' 고르기"
    elif k == "check":
        d = f"'{n}' {'켜기' if s.get('checked') else '끄기'}"
    elif k == "enter":
        d = f"'{n}' 에서 Enter"
    elif k == "hover":
        d = f"'{n}' 에 마우스 올리기 (하위 메뉴 열기)"
    else:
        d = k
    if s.get("optional"):
        d += " (떠 있을 때만)"
    if s.get("double"):
        d = d.replace(" 누르기", " 두 번 누르기")
    if ambiguous(s) and s.get("appearsAfter") is not None:
        d += f" ({s['appearsAfter'] + 1}단계 뒤에 새로 생긴 것)"
    if s.get("opens"):
        d += " → 새 창"
    for m in s.get("dialogs", []):
        d += f" → 알림창 '{_cut(m, True) if hide_values else m[:30]}' 확인"
    if s.get("download"):
        d += f" → 파일 받기 (기록 때: {s['download']})"
    return d


class NotFound(Exception):
    pass


class Skip(Exception):
    pass


def q(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def candidates(t):
    """(설명, 셀렉터, 순번) - 앞의 것부터 써 본다. 순번이 None 이면 하나로 정해질 때만 쓴다."""
    tag, out = t["tag"], []
    if t["id"]:
        out.append(("id", f"[id={q(t['id'])}]", None))
    if t["text"] and t["textCount"] == 1:
        if tag == "input":
            out.append(("글자", f"input[value={q(t['text'])}]", None))
        else:
            out.append(("글자", f"{tag}:text-is({q(t['text'])})", None))
    if t["name"]:
        out.append(("name", f"{tag}[name={q(t['name'])}]", None))
    for key, attr in (("aria", "aria-label"), ("title", "title"), ("placeholder", "placeholder")):
        if t[key]:
            out.append((attr, f"{tag}[{attr}={q(t[key])}]", None))
    if t["label"] and t["labelKind"] == "th" and '"' not in t["label"]:
        out.append(("칸 이름", f'xpath=(//tr[th[normalize-space(.)="{t["label"]}"]]//{tag})[{t["labelIndex"]}]', None))
    out.append(("위치", t["css"], None))
    if t["text"] and t["textCount"] > 1:
        sel = f"input[value={q(t['text'])}]" if tag == "input" else f"{tag}:text-is({q(t['text'])})"
        out.append((f"글자 {t['textIndex'] + 1}번째", sel, t["textIndex"]))
    return out


class Replayer:
    def __init__(self, context, rec, creds, out_dir, code, today=None, review=False, log=print, step_timeout=30.0,
                 hide_values=False, shot_dir=None):
        self.context, self.rec, self.creds, self.out_dir, self.code = context, rec, creds, out_dir, code
        self.today = today or datetime.date.today()
        self.review, self.log, self.step_timeout = review, log, step_timeout
        self.hide_values = hide_values       # 로그에 칸에 친 값·주소 ? 뒤를 안 싣는다 (대시보드로 간다)
        self.shot_dir = shot_dir or out_dir  # 실패 사진 자리 (프리페어는 받은 파일 폴더에 사진을 두지 않는다)
        self.pages, self.watched, self.saved, self.results, self.baseline = {}, set(), [], [], {}
        self.progress = None        # (번호, run/ok/skip/fail, 설명) - 화면이 단계마다 표시
        self.page_hook = None       # 첫 창이 뜨면 (창 자리 맞추기)
        self.first_page = None      # 이미 있는 창에서 시작 (옵저버·프리페어가 연 창)
        self.fit_viewport = False   # 기록 때 창 안쪽 크기로 (프리페어. 옵저버 미리보기는 창 자리를 맞춘다)
        self.cancel = None          # threading.Event - 켜지면 다음 단계 전에 멈춘다 (옵저버 창을 닫음)
        self.download_timeout_ms = DOWNLOAD_TIMEOUT_MS
        self.elapsed = 0.0

    def _watch(self, page):
        if page in self.watched:
            return
        self.watched.add(page)

        def on_dialog(d):
            self.log(f"      알림창 '{d.message}' -> 확인")
            d.accept()
        page.on("dialog", on_dialog)

    # --- 찾기 ---
    def _frame(self, page, info):
        if info["main"]:
            return page.main_frame
        for f in page.frames:
            if info["name"] and f.name == info["name"]:
                return f
        for f in page.frames:
            if f.parent_frame is not None and url_path(f.url) == info["path"]:
                return f
        return None

    def _same(self, loc, t):
        """찾은 것이 기록한 것과 모양이 같은가 (id·위치가 다른 것을 가리키게 된 경우를 거른다)."""
        try:
            got = loc.evaluate("e => [e.tagName.toLowerCase(), (e.getAttribute('type') || '').toLowerCase()]")
            if got[0] != t["tag"] or (t["tag"] == "input" and got[1] != t["type"]):
                return False
            return not t["text"] or loc.evaluate(TEXT_OF) == t["text"]
        except Exception:
            return False

    def _pick(self, loc, n, nth, prev):
        """단서가 가리키는 것들 중 하나. prev 가 있으면 (기록 때 새로 생긴 것을 눌렀으면) 그 뒤 새로 생긴 것만."""
        if prev is not None:
            sigs = loc.evaluate_all(SIGS_JS)
            fresh = [i for i, g in enumerate(sigs) if g not in prev]
            if nth is not None:
                i = nth if nth in fresh else (fresh[0] if fresh else None)
            else:
                i = fresh[0] if len(fresh) == 1 else None
            return None if i is None else loc.nth(i)
        if n == 0 or (nth is None and n > 1) or (nth is not None and nth >= n):
            return None
        return loc.nth(nth or 0)

    def _snapshot(self, s):
        """s 가 누를 화면에 지금 있는 누를 것들의 표시 (없는 화면이면 빈 것). 화면이 다 뜬 뒤에 잡는다:
        목록이 늦게 그려지면 옛 줄이 기준에서 빠져 '새로 생긴 것' 으로 보이고, 옛 파일을 받는다 (2026-09-30 느린 목록으로 4/4 재현)."""
        pg = self.pages.get(s["page"])
        fr = self._frame(pg, s["frame"]) if pg is not None and not pg.is_closed() else None
        if fr is None:
            return set()
        try:
            pg.wait_for_load_state("networkidle", timeout=3000)     # 1초마다 묻는 목록이면 3초 다 기다린다
        except Exception:
            pass
        try:
            fr.evaluate(QUIET_JS)
            return set(fr.evaluate(SNAP_JS))
        except Exception:
            return set()

    def _find(self, page, s, prev):
        t = s["target"]
        cands = candidates(t)
        deadline = time.time() + (OPTIONAL_WAIT if s.get("optional") else self.step_timeout)
        while True:
            frame = self._frame(page, s["frame"])
            if frame is not None:
                for how, sel, nth in cands:
                    try:
                        loc = frame.locator(sel)
                        loc = self._pick(loc, loc.count(), nth, prev)
                    except Exception:
                        continue            # 화면이 바뀌는 중
                    if loc is not None and self._same(loc, t):
                        return frame, loc, how + (", 새로 생긴 것" if prev is not None else "")
            if time.time() > deadline:
                if s.get("optional"):
                    raise Skip("화면에 없음")
                raise NotFound(f"{self.step_timeout:.0f}초 안에 못 찾음 (단서: {', '.join(c[0] for c in cands)})")
            page.wait_for_timeout(250)

    # --- 하기 ---
    def _dismiss(self, page):
        """예상 밖으로 가린 공지를 닫는다 (단추 글자가 정확히 같은 것만)."""
        for f in page.frames:
            for text in CLOSE_TEXTS:
                for role in ("button", "link"):
                    loc = f.get_by_role(role, name=text, exact=True)
                    try:
                        if loc.count() and loc.first.is_visible():
                            loc.first.click(timeout=2000)
                            self.log(f"      가린 공지를 닫음 ('{text}')")
                            page.wait_for_timeout(300)
                            return True
                    except Exception:
                        pass
        return False

    def _reveal(self, page, loc):
        """마우스를 올려야 열리는 메뉴: 보이는 가장 가까운 위 칸에 마우스를 올린다."""
        h = loc.evaluate_handle("""e => { for (let a = e.parentElement; a; a = a.parentElement) {
              const r = a.getBoundingClientRect(), cs = getComputedStyle(a);
              if (r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden') return a; } return null; }""")
        el = h.as_element()
        if el is None:
            return False
        for _ in range(2):
            try:
                el.hover(timeout=3000)
                self.log("      가려진 메뉴를 마우스를 올려 열었음")
                return True
            except PWTimeout as e:
                if "intercepts pointer events" not in str(e) or not self._dismiss(page):
                    return False
        return False

    def _click(self, page, loc):
        for _ in range(4):
            try:
                loc.click(timeout=4000)
                return
            except PWTimeout as e:
                msg = str(e)
            if "intercepts pointer events" in msg and self._dismiss(page):
                continue
            if "not visible" in msg and self._reveal(page, loc):
                continue
            break
        self.log("      (눌리지 않아 스크립트로 누름)")
        loc.evaluate("e => e.click()")

    def _hover(self, page, loc):
        """마우스를 올려 둔다 (다음 단계가 누를 하위 메뉴가 그때 만들어진다). 가리면 닫고, 가려진 메뉴면 위 칸부터."""
        for _ in range(3):
            try:
                loc.hover(timeout=4000)
                return
            except PWTimeout as e:
                msg = str(e)
            if "intercepts pointer events" in msg and self._dismiss(page):
                continue
            if "not visible" in msg and self._reveal(page, loc):
                continue
            break
        raise NotFound("마우스를 올리지 못함")

    def _fill(self, loc, value):
        try:
            loc.fill(value, timeout=5000)
        except PWTimeout:          # 읽기 전용 칸 (달력으로만 넣는 칸)
            loc.evaluate("(e, v) => { e.value = v; e.dispatchEvent(new Event('input', {bubbles: true})); "
                         "e.dispatchEvent(new Event('change', {bubbles: true})); }", value)

    def _act(self, page, loc, s):
        k = s["kind"]
        if k == "hover":
            self._hover(page, loc)
        elif k == "click" and s.get("double"):
            loc.dblclick(timeout=5000)
        elif k == "click":
            self._click(page, loc)
        elif k == "fill":
            if s.get("credential") == "ID":
                v = self.creds["ID"]
            elif s.get("date"):
                v = (self.today + datetime.timedelta(days=s["date"]["offset"])).strftime(s["date"]["fmt"])
            else:
                v = s.get("value", "")
            self._fill(loc, v)
        elif k == "secret":
            self._fill(loc, self.creds["PW"])
        elif k == "select":
            try:
                loc.select_option(label=s["option"], timeout=5000)
            except Exception:
                loc.select_option(value=s["value"], timeout=5000)
        elif k == "check":
            loc.set_checked(bool(s["checked"]), timeout=5000)
        elif k == "enter":
            loc.press("Enter", timeout=5000)

    def _save(self, dl):
        os.makedirs(self.out_dir, exist_ok=True)
        path = os.path.join(self.out_dir, f"({self.code}){dl.suggested_filename}")
        stem, ext = os.path.splitext(path)
        i = 1
        while os.path.exists(path):
            path = f"{stem} ({i}){ext}"
            i += 1
        dl.save_as(path)
        self.saved.append(path)
        return path

    def _step(self, i, s):
        for j in self.needs.get(i, ()):   # 뒤 단계가 '이 단계 뒤에 나타난 것' 을 누른다 - 지금 있는 것들을 적어 둔다
            self.baseline[j] = self._snapshot(self.rec["steps"][j])
        if s["kind"] == "newtab":
            pg = self.context.new_page()
            self._watch(pg)
            self.pages[s["page"]] = pg
            return "새 탭"
        page = self.pages.get(s["page"])
        if page is None or page.is_closed():
            raise NotFound(f"창 {s['page']} 이 없음")
        # 사람이 기다린 시간의 절반 (0.3~3초): 화면이 따라올 틈
        page.wait_for_timeout(min(max(s.get("gap", 0) * 0.5, 300), SETTLE_MAX_MS))
        if s["kind"] == "goto":
            page.goto(s["href"], wait_until="domcontentloaded")
            return "주소로 이동"
        if s["kind"] == "back":
            page.go_back(wait_until="domcontentloaded")
            return "뒤로"
        frame, loc, how = self._find(page, s, self.baseline.get(i))
        if url_path(frame.url) != s["url"]:
            self.log(f"      (주소가 다름: 기록 {s['url']} / 지금 {url_path(frame.url)})")
        if self.review:             # 누를 곳에 잠깐 빨간 테두리 (Playwright highlight 는 글자 표가 화면에 쌓인다)
            try:
                loc.evaluate("e => { const o = e.style.outline, f = e.style.outlineOffset;"
                             " e.style.outline = '3px solid #dc2626'; e.style.outlineOffset = '2px';"
                             " setTimeout(() => { e.style.outline = o; e.style.outlineOffset = f; }, 900); }")
            except Exception:
                pass
            page.wait_for_timeout(900)
        if s.get("download"):
            with page.expect_download(timeout=self.download_timeout_ms) as di:
                self._act(page, loc, s)
            how += f", 받음 {os.path.basename(self._save(di.value))}"
        elif s.get("opens"):
            with page.expect_popup(timeout=15000) as pi:
                self._act(page, loc, s)
            self.pages[s["opens"]] = pi.value
            self._watch(pi.value)
            pi.value.wait_for_load_state("domcontentloaded")
        else:
            self._act(page, loc, s)
        return how

    def run(self):
        if self.rec.get("version") != RECORD_VERSION:
            raise ValueError(f"모르는 기록 형식입니다 (version {self.rec.get('version')!r}) - "
                             "옵저버와 프리페어를 같은 판으로 맞추세요")
        page = self.first_page or self.context.new_page()
        if self.page_hook:
            self.page_hook(page)
        if self.fit_viewport and self.rec.get("viewport"):
            page.set_viewport_size(self.rec["viewport"])        # 기록 때 창 안쪽 크기 (반응형 사이트의 메뉴 모양)
        self._watch(page)
        self.pages[0] = page
        steps = self.rec["steps"]
        if not (steps and steps[0]["kind"] == "goto"):         # 주소줄로 시작한 기록은 그 단계가 곧 시작 주소
            page.goto(self.rec["start_url"], wait_until="domcontentloaded")
        self.needs = {}
        for j, s in enumerate(steps):
            if ambiguous(s) and s.get("appearsAfter") is not None:
                self.needs.setdefault(s["appearsAfter"], []).append(j)
        started = time.time()
        for i, s in enumerate(steps, 1):
            text = describe(s, self.hide_values)
            if self.cancel is not None and self.cancel.is_set():
                self.results.append((i, "fail", "멈춤 - 옵저버 창을 닫았습니다"))
                self.log(f"  {i:2d}/{len(steps)} {text}  - 멈춤 (창을 닫았습니다)")
                if self.progress:
                    self.progress(*self.results[-1])
                break
            if self.progress:
                self.progress(i, "run", "")
            try:
                how = self._step(i - 1, s)
                self.results.append((i, "ok", how))
                self.log(f"  {i:2d}/{len(steps)} {text}  [{how}]")
            except Skip as e:
                self.results.append((i, "skip", str(e)))
                self.log(f"  {i:2d}/{len(steps)} {text}  - 건너뜀 ({e})")
            except Exception as e:
                why = f"{type(e).__name__}: {str(e).splitlines()[0]}"
                if self.hide_values:
                    why = URL_QUERY.sub(r"\1", why)       # Playwright 오류에 주소가 통째로 들어온다 (2026-10-01 검토)
                if "has been closed" in why:
                    why = "창이 닫혀 멈췄습니다 (검수 중에는 창을 누르거나 닫지 마세요)"
                self.results.append((i, "fail", why))
                self.log(f"  {i:2d}/{len(steps)} {text}  - 실패: {why}")
                if self.progress:
                    self.progress(*self.results[-1])
                try:
                    os.makedirs(self.shot_dir, exist_ok=True)
                    shot = os.path.join(self.shot_dir, f"실패_{i}단계.png")
                    self.pages.get(s["page"], page).screenshot(path=shot)
                    self.log(f"      화면 사진: {shot}")
                except Exception:
                    pass
                break
            if self.progress:
                self.progress(*self.results[-1])
        self.elapsed = time.time() - started
        return all(r[1] != "fail" for r in self.results) and len(self.results) == len(steps)


def replay(rec, creds, out_dir, code, today=None, review=False, headless=True, log=print, step_timeout=30.0):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, slow_mo=250 if review else 0)
        context = browser.new_context(accept_downloads=True)
        r = Replayer(context, rec, creds, out_dir, code, today=today, review=review, log=log, step_timeout=step_timeout)
        ok = r.run()
        if review and context.pages:
            log("검수가 끝났습니다. 3초 뒤 창을 닫습니다.")
            try:
                context.pages[0].wait_for_timeout(3000)
            except Exception:
                pass
        try:
            browser.close()
        except Exception:
            pass                    # 사람이 창을 먼저 닫았다
    return ok, r
