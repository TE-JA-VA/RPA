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
import unicodedata
import urllib.parse
import zipfile

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

EDGE_MISSING = "Microsoft Edge가 설치되어 있지 않습니다. Edge를 설치한 뒤 다시 실행하여 주십시오."


def edge(launch, *args, **kw):
    """PC 에 깔린 Edge 로 띄운다 - 기록·재생·옵저버·프리페어가 모두 여기로 (2026-10-06 부터. 그 전에는 Playwright 의
    Chromium 713MB 를 배포판에 같이 실었다). launch 는 p.chromium.launch 나 launch_persistent_context.
    Edge 가 없으면 사람 말로 멈춘다 (Playwright 는 'playwright install msedge' 하라는 개발자 말을 한다).
    navigator.webdriver 를 끈다 - 켜져 있으면 봇을 막는 사이트가 접근을 막는다 (2026-10-12 옵저버 기록 중 실측).
    --test-type 은 그 옵션이 띄우는 '지원되지 않는 명령줄 플래그' 띠를 끈다 (기록 화면을 가린다)."""
    kw["args"] = [*kw.get("args", []), "--disable-blink-features=AutomationControlled", "--test-type"]
    try:
        return launch(*args, channel="msedge", **kw)
    except Exception as e:
        if "'msedge' is not found" in str(e):        # Chromium distribution 'msedge' is not found at C:\...\msedge.exe
            raise RuntimeError(EDGE_MISSING) from None
        raise


JS = r"""
(() => {
  // 문서마다 한 번. window 에 표시하면 안 된다: 새 창은 빈 페이지(about:blank)의 window 를 진짜 주소에서도 그대로 써서
  // 진짜 페이지에 귀를 달지 않고 넘어간다 (2026-09-30 시험에서 새 창의 조작이 통째로 빠졌다)
  if (document.__recOn) return; document.__recOn = true;
  // 사이트가 기본 기능을 바꿔치기해도 (비즈메카 메일 jsmap.js 의 Map, 2026-10-14) 옵저버가 쓰는 것은 처음 것 그대로.
  // 보고는 JSON 글자 하나로 보낸다 - Playwright 가 묶음 값을 옮길 때 쓰는 Map.set 이 바꿔치기된 Map 에 없어 보고가 모두 사라졌다.
  // 이 스크립트는 사이트 스크립트보다 먼저 돈다 (add_init_script). 나중에 심을 때(_inject)는 이미 바뀐 뒤일 수 있다
  const J = JSON.stringify, NoProto = () => Object.create(null);
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
    const near = nearLabel(el);
    return near ? [near, 0, 'near'] : ['', 0, ''];
  }
  function nearLabel(el) {        // 칸 바로 위·왼쪽에 따로 놓인 글자 (Nexacro 의 Static - <label> 로 이어져 있지 않다, 농협몰 2026-10-15). 이름 보이기·인증번호 단서용
    const r = el.getBoundingClientRect(), mid = r.top + r.height / 2;
    for (const [x, y] of [[r.left + 6, r.top - 10], [r.left + 6, r.top - 18], [r.left - 12, mid], [r.left - 40, mid], [r.left - 80, mid]]) {
      if (x < 0 || y < 0) continue;
      const e = document.elementFromPoint(x, y);
      if (!e || e.contains(el) || el.contains(e) || ['INPUT', 'SELECT', 'TEXTAREA', 'BUTTON'].includes(e.tagName)) continue;
      const t = norm(e.textContent);
      if (t && t.length <= 30) return t;
    }
    return '';
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
  // 목록 줄(li·tr)을 눌렀으면 그 목록 - 메일 고르기가 쓴다 (사용자 2026-10-14). sel = 같은 모양의 줄, inner = 줄 안의 누른 칸,
  // key = 줄의 고유 표시 (data-key 등, 없으면 빈 칸 - 제목 글자로 기억), list = 그때 보이던 줄 (저장하면 '이미 처리' 로)
  const STATE = /^(on|off|active|selected?|hover|focus|read|unread|new|checked|current|open|show|odd|even)$|(^is-|-active$|-selected$|_on$|_over$)/i;
  const clsOf = e => [...e.classList].filter(c => /^[A-Za-z_][\w-]*$/.test(c) && !STATE.test(c)).map(c => '.' + c).join('');
  const rowKey = r => r.getAttribute('data-key') || r.getAttribute('data-id') || r.getAttribute('data-uid') || r.id || '';
  function rowInfo(el) {
    const row = el.closest('li,tr'), par = row && row.parentElement;
    if (!par) return null;
    const own = clsOf(row), tag = row.tagName.toLowerCase();
    const sel = own ? tag + own : (par.id ? '#' + CSS.escape(par.id) : par.tagName.toLowerCase() + clsOf(par)) + ' > ' + tag;
    let rows; try { rows = [...document.querySelectorAll(sel)]; } catch (e) { return null; }
    if (rows.length < 2 || rows.indexOf(row) < 0) return null;
    const segs = []; for (let e = el; e && e !== row; e = e.parentElement) segs.unshift(e.tagName.toLowerCase() + clsOf(e));
    const inner = segs.join(' ');
    __SEEN__
    const cell = r => (inner ? r.querySelector(inner) : null) || r;
    return {sel, inner, key: rowKey(row), list: rows.slice(0, 200).map(r => ({k: rowKey(r), t: norm(cell(r).textContent).slice(0, 120), s: seenText(cell(r))}))};
  }
  function send(kind, el, extra) {
    pend = null;                  // 다른 조작이 먼저 왔다 - 손가락 커서 아닌 누르기는 그 사이 아무것도 안 바뀌었다
    try { window.__rec(J(Object.assign({kind, url: location.href, target: describe(el), t: Date.now()}, extra || {}))); } catch (e) {}
  }
  // 누를 것마다 이 문서에 처음 나타난 시각. 재생은 '몇 단계 뒤에 나타난 것' 을 새로 생긴 것 중에서 고른다
  // (요청한 파일이 목록에 새 줄로 올라오는 것 - 그 사이 다른 곳을 눌러도 흔들리지 않게 '직전 조작' 이 아니라 나타난 시각으로)
  // appeared: 안 보이다가 보이게 된 가장 최근 시각 - 하위 메뉴 감지. 마우스를 올리면 새로 만들어지는 메뉴도, 처음부터 숨겨
  // 두었다가 보여 주는 메뉴(CSS :hover, class 'show' - 대부분의 쇼핑몰)도 알아챈다 (2026-10-13: 전에는 새로 만들어진 것만 봐서
  // 숨겨 둔 메뉴는 마우스 올리기를 적지 않았고, 재생이 짐작으로 위 칸에 마우스를 올렸다).
  // 1초마다 innerHTML 로 다시 그리는 목록은 훑을 때마다 늘 보여서 appeared 가 바뀌지 않는다
  const firstSeen = NoProto(), appeared = NoProto();       // Map·Set 대신 (사이트가 바꿔치기한다)
  let shown = NoProto(), base = false;    // base: 화면이 다 그려진 때의 보이는 것들을 적었다 - 그 뒤 보이게 된 것만 '나타남'
  const visible = el => el.checkVisibility ? el.checkVisibility({opacityProperty: true, visibilityProperty: true})
                                           : el.getClientRects().length > 0;
  function scan() {
    const now = Date.now(), cur = NoProto();
    for (const el of document.querySelectorAll(CLICKABLE)) {
      const g = sig(el);
      if (!(g in firstSeen)) firstSeen[g] = now;
      if (!visible(el)) continue;
      cur[g] = 1;
      if (!(g in shown) && base) appeared[g] = now;
    }
    shown = cur;
  }
  const ready = () => { scan(); base = true; };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready); else ready();
  let soon = 0, settle = 0;
  function rescan() {             // 곧 한 번, 펼침 움직임이 끝난 뒤 한 번
    if (!soon) soon = setTimeout(() => { soon = 0; scan(); }, 50);
    clearTimeout(settle); settle = setTimeout(scan, 350);
  }
  // 마우스가 올라간 누를 만한 것들 (최근 20개) - 올리자마자 새로 나타난 것을 누르면 그 올린 것을 '마우스 올리기' 단계로
  const hovers = [];
  document.addEventListener('mouseover', e => {
    if (!e.isTrusted) return;
    rescan();                     // CSS :hover 로 열리는 메뉴는 화면 글이 안 바뀌어 아래 MutationObserver 가 모른다
    const h = e.target.closest(ACT + ',li,[role=menuitem]') || (getComputedStyle(e.target).cursor === 'pointer' ? e.target : null);
    if (!h || (hovers.length && hovers[hovers.length - 1].el === h)) return;
    hovers.push({el: h, t: Date.now()});
    if (hovers.length > 20) hovers.shift();
  }, true);
  function hoverBefore(el, ap) {
    if (!ap) return null;         // 처음부터 보이던 것 (화면이 뜰 때 마우스가 지나간 칸을 적지 않는다)
    for (let i = hovers.length - 1; i >= 0; i--) {
      const hv = hovers[i];
      if (hv.el === el || el.contains(hv.el) || hv.el.contains(el) || !hv.el.isConnected) continue;
      if (hv.t <= ap && ap - hv.t < 1500) return {el: hv.el, target: describe(hv.el), t: hv.t};
      if (hv.t < ap - 1500) break;
    }
    return null;
  }
  function hoverChain(el) {       // 누른 것을 보이게 한 마우스 올리기, 그것을 보이게 한 것 … (두 단·세 단 메뉴), 위 단부터
    const out = [];
    for (let cur = el; out.length < 3;) {
      const c = cur.matches(CLICKABLE) ? cur : cur.closest(CLICKABLE);
      const h = c && hoverBefore(cur, appeared[sig(c)]);
      if (!h || out.some(o => o.el === h.el)) break;
      out.unshift(h); cur = h.el;
    }
    return out.map(h => ({target: h.target, t: h.t}));
  }
  // 손가락 커서가 아닌 곳을 누른 것: 그 직후(PEND_MS) 누른 부품 안이 바뀌거나(체크 그림), 누른 것을 품은 칸이 바뀌거나(목록이 닫힘),
  // 누른 자리 가까이에 새로 보이는 것이 생기면(목록이 펼쳐짐) 누르기로 적는다 - div 로 그린 체크박스·라디오·드롭다운 (Nexacro, 농협몰 2026-10-15).
  // 이름표·빈 곳을 누른 것은 아무것도 안 바뀌어 지금처럼 버려진다. 부품 = tabindex 가 달린 가장 가까운 칸 (Nexacro 의 컴포넌트)
  const PEND_MS = 600;
  let pend = null;
  function watchClick(el, e) {
    const comp = el.closest('[tabindex]') || el, target = comp.id ? comp : el, t = Date.now();
    pend = {comp, el: target, x: e.clientX, y: e.clientY, t,
            extra: {detail: e.detail, firstSeen: null, hovers: hoverChain(target), row: rowInfo(e.target), t}};
    setTimeout(() => { if (pend && pend.t === t) pend = null; }, PEND_MS);
  }
  function pendHit(m) {
    const n = m.target.nodeType === 1 ? m.target : m.target.parentElement;
    if (!n || !n.isConnected) return false;
    if (pend.comp.contains(n) || (m.type === 'attributes' && n.contains(pend.comp))) return true;
    const near = x => { if (x.nodeType !== 1 || !visible(x)) return false; const r = x.getBoundingClientRect();
      return r.width > 0 && Math.abs(r.top - pend.y) < 300 && Math.abs(r.left - pend.x) < 300; };
    return m.type === 'childList' ? [...m.addedNodes].some(near) : near(n);
  }
  new MutationObserver(ms => {
    rescan();
    if (pend && ms.some(pendHit)) { const p = pend; send('click', p.el, p.extra); }
  }).observe(document, {childList: true, subtree: true, attributes: true, characterData: true,
                        attributeFilter: ['class', 'style', 'hidden', 'open', 'aria-expanded', 'src', 'aria-checked', 'aria-selected']});
  scan();
  let lastEnter = 0;
  document.addEventListener('click', e => {
    if (!e.isTrusted) return;
    if (e.detail === 0 && Date.now() - lastEnter < 500) return;          // Enter 가 만든 단추 눌림
    const act = e.target.closest(ACT), el = act || e.target;
    if (!act && getComputedStyle(el).cursor !== 'pointer') { watchClick(el, e); return; }   // 글자·표 칸·빈 곳은 버리고, 누른 뒤 바뀌면 적는다 (watchClick)
    const tag = el.tagName, type = (el.type || '').toLowerCase();
    if (tag === 'SELECT' || tag === 'OPTION' || tag === 'TEXTAREA') return;   // 값 바뀜으로 적는다
    if (tag === 'INPUT' && !BTN.includes(type) && type !== 'image') return;  // 글자 칸·체크 상자도
    let seen = null;
    if (el.matches(CLICKABLE)) { scan(); seen = firstSeen[sig(el)] || null; }
    send('click', el, {detail: e.detail, firstSeen: seen, hovers: hoverChain(el), row: rowInfo(e.target)});   // 줄 안에서 실제로 누른 칸 (onclick 은 줄에 달려 있어도 - 제목 칸)
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

# 보이는 글자만 - 숨은 글자(span.blind 등 화면 낭독용·숨김)와 아이콘은 뺀다. 메일 제목 칸 앞의 중요·전달 표시 (2026-10-14).
# 옵저버(JS 의 rowInfo)와 재생(ROWS_JS)이 같은 것을 쓴다
SEEN_JS = r"""const seenText = (top) => {   // 보이는 글자만 - 숨은 글자(span.blind 등 화면 낭독용·숨김)와 아이콘은 뺀다 (중요·전달 표시, 2026-10-14)
  const out = [], hid = e => { if (/(^|[\s_-])(blind|sr-only|screen-?reader|hidden|hide|a11y|ir)([\s_-]|$)/i.test(e.className || '')) return true;
    const cs = getComputedStyle(e); if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.fontSize) === 0) return true;
    const r = e.getBoundingClientRect(); return cs.position === 'absolute' && (r.width <= 1 || r.height <= 1); };
  const w = document.createTreeWalker(top, NodeFilter.SHOW_TEXT);
  for (let n; (n = w.nextNode());) { let ok = true; for (let e = n.parentElement; e && ok; e = e === top ? null : e.parentElement) if (hid(e)) ok = false;
    if (ok) out.push(n.textContent); }
  return out.join(' ').replace(/\s+/g, ' ').trim().slice(0, 120); };"""
# '새로 생긴 것' 을 가리는 표시: 주소(또는 onclick) + 그 줄의 글자. 옵저버와 재생기가 같은 것을 쓴다
CLICKABLE = "a,button,input[type=button],input[type=submit],[onclick],[role=button],[role=link]"
SIG = ("el => (el.getAttribute('href') || el.getAttribute('onclick') || '') + '|' + "
       "(((el.closest('tr,li') || el).textContent) || '').replace(/\\s+/g, ' ').trim().slice(0, 120)")
JS = JS.replace("__CLICKABLE__", json.dumps(CLICKABLE)).replace("__SIG__", SIG).replace("__SEEN__", SEEN_JS)
# 목록은 JSON 글자로 돌려받는다 - 묶음 값은 사이트가 Map 을 바꿔치기하면 Playwright 가 못 옮긴다 (2026-10-14 비즈메카 메일, 옵저버의 send 와 같다)
SNAP_JS = f"() => JSON.stringify([...document.querySelectorAll({json.dumps(CLICKABLE)})].map({SIG}))"
SIGS_JS = f"els => JSON.stringify(els.map({SIG}))"
# 화면이 0.4초 동안 안 바뀔 때까지 (최대 2.5초) - 늦게 그려지는 목록을 기다린다
QUIET_JS = """() => new Promise(res => {
  let t, hard;
  const mo = new MutationObserver(() => { clearTimeout(t); t = setTimeout(done, 400); });
  function done() { mo.disconnect(); clearTimeout(t); clearTimeout(hard); res(true); }
  mo.observe(document, {subtree: true, childList: true, characterData: true});
  t = setTimeout(done, 400); hard = setTimeout(done, 2500);
})"""

NO_DIGITS = lambda x: re.sub(r"\d+", "0", re.sub(r"\s+", "", x))     # '메일 11' == '메일 10' (숫자 뺀 글자 단서)
KINDS_MERGE = ("fill", "secret", "select")        # 같은 칸에 잇달아 온 것은 마지막 값 하나로
# 2차인증 (휴대폰 중계 설계 13절): 숫자 4~8자리를 친 칸이고 단서에 이런 말이 있으면 '인증번호 칸' - 값은 남기지 않는다 (한 번 쓰는 번호)
OTP_VALUE = re.compile(r"^\d{4,8}$")
OTP_HINT = re.compile(r"인증|otp|auth|cert|verif", re.I)
# '일치' 만 보면 '인증번호가 일치합니다' (비즈메카 성공 알림창, 2026-10-14) 까지 거절로 읽는다
OTP_REJECT = re.compile(r"인증.*(틀|일치하지|불일치|잘못|만료|다시|실패)|(틀|일치하지|불일치|잘못|만료).*인증")
OTP_TRIES = 3                # 모두 합쳐 (처음 + 2번 더, 사용자 2026-10-13)
OTP_WAIT = 120               # 번호 하나를 기다리는 초 (요청이 열려 있는 2분)
# 메일 고르기 (사용자 2026-10-14): 목록 줄 누르기를 '제목이 이 글자로 시작하는 메일마다' 로. 그 아래 받기 단계까지가 메일마다 되풀이할 묶음
MAIL_PICK_DEFAULT = ">>>"
MAIL_PICK_MAX = 20           # 한 번에 처리하는 메일 수 (나머지는 다음 실행)
MAIL_MEMORY_DAYS = 90        # 처리한 메일을 기억하는 날 수
MAIL_BACK_WAIT = 10          # 메일을 연 뒤 목록으로 돌아와 줄이 다시 보이기까지 기다리는 초
CLOSE_TEXTS = ("닫기", "오늘 하루 보지 않기", "오늘하루 보지않기", "오늘 하루 열지 않기", "x", "×", "close")
DATE_FORMATS = ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d", "%Y%m%d")
OPTIONAL_WAIT = 3.0
STEP_WAIT, STEP_TRIES = 20.0, 6  # 못 찾으면 20초씩 6번(최대 2분) 다시 찾고 포기 - 미리보기·ACTOR 같이 (사용자 2026-10-15)
RECORD_VERSION = 1           # 기록 모양. 다르면 재생하지 않는다 (옛 프리페어가 새 기록을 잘못 따라 하지 않게)
DOWNLOAD_TIMEOUT_MS = 300000  # 파일이 오기 시작할 때까지 기다리는 시간 (안 오면 그 단계 실패). 쇼핑몰이 엑셀을 만드는 데 오래 걸려 60초 → 5분,
                              # 기다리는 동안 로그를 남긴다 (2026-10-15 메모 5). 오기 시작한 뒤에는 다 받을 때까지 기다린다 (느려도)
OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"     # 옛 엑셀(xls)·암호 건 엑셀
CUT = 20                     # 대시보드로 가는 설명에서 누른 것의 글자 길이
SETTLE_MAX_MS = 3000        # 단계 사이 기다림 상한 (사람이 기다린 시간의 절반). 시험에서 0 으로도 돌려 본다
TEXT_OF = """e => { const n = s => (s || '').replace(/\\s+/g, ' ').trim(); const t = e.tagName;
  if (t === 'INPUT') return ['button','submit','reset'].includes((e.type||'').toLowerCase()) ? n(e.value) : '';
  if (t === 'TEXTAREA' || t === 'SELECT') return ''; return n(e.textContent).slice(0, 80); }"""


EDGE_NEW_TAB = "https://ntp.msn.com/edge/ntp"  # 사람이 Ctrl+T·+ 로 연 Edge 새 탭은 edge:// 가 아니라 이 주소로 바로 생긴다 (2026-10-06 실측)
BROWSER_PAGES = ("chrome://", "edge://", EDGE_NEW_TAB)   # 브라우저 자체 페이지 (새 탭·Edge 다운로드 창) - 사이트가 연 창이 아니다


def user_tab(page):
    """사람이 Ctrl+T·+ 로 연 탭 (페이지가 연 창이 아니다)."""
    try:
        return page.opener() is None and page.url.startswith(BROWSER_PAGES)
    except Exception:
        return False


NAV_KINDS = ("goto", "back", "newtab")
SESSION_Q = re.compile(r"(?i)[?&](sid|sess\w*|jsessionid|token|auth\w*)=")
URL_QUERY = re.compile(r"(https?://[^\s?#'\"]*)[?#][^\s'\"]*")   # 실패 사유의 주소에서 ? 뒤 (대시보드로 갈 때 뺀다)


def _text_head(path, limit):
    """파일 앞부분을 소문자 글로 (UTF-16 웹 화면·표도 읽게). 태그 이름만 보므로 한글 인코딩은 상관없다."""
    with open(path, "rb") as f:
        raw = f.read(limit)
    return raw.decode("utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8", "ignore").lower()


def download_problem(path):
    """받은 파일을 쓸 수 있나 - 문제면 사람에게 보일 까닭, 괜찮으면 None (2026-10-15 메모 5: 다 받았나·진짜 엑셀인가).
    xlsx 는 압축이 온전하고 통합 문서(xl/)가 들어 있어야, 옛 엑셀 xls 는 512바이트 단위로 끝나야 (잘림),
    웹 화면(HTML·XML)은 표가 있어야 한다 - 쇼핑몰이 HTML 표를 .xls 로 주기도 하고, 로그인 만료·오류 화면은 표가 없다.
    CSV 같은 그 밖의 것은 비어 있지만 않으면 된다 (모양으로 못 가린다)."""
    if os.path.getsize(path) == 0:
        return "빈 파일입니다."
    with open(path, "rb") as f:
        head = f.read(8)
    ext = os.path.splitext(path)[1].lower()
    if head.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(path) as z:
                broken, names = z.testzip(), z.namelist()
        except NotImplementedError:                 # 파이썬이 모르는 압축 방식 (deflate64 등) - 깨졌다고 단정하지 않는다
            return None
        except (zipfile.BadZipFile, OSError, EOFError, ValueError):
            broken, names = True, []
        if broken:
            return "다운로드가 완료되지 않았거나 손상된 엑셀 파일입니다."
        if ext in (".xlsx", ".xlsm") and not any(n.startswith("xl/") for n in names):
            return "엑셀 파일이 아닙니다. (통합 문서가 없는 압축 파일)"
        return None
    if head.startswith(OLE_SIGNATURE):
        return None     # 옛 엑셀(xls) - 마지막 칸을 안 채우는 생성기가 있어 크기로는 잘림을 못 가린다. 잘림은 브라우저가 알린다 (dl.failure, 검토 2026-10-16)
    text = _text_head(path, 4_000_000)
    if text.lstrip("\ufeff \t\r\n").startswith("<"):
        if "<table" in text or "<workbook" in text or "urn:schemas-microsoft-com:office:spreadsheet" in text:
            return None
        return "엑셀 형식이 아닌 웹 화면입니다. 로그인 만료 또는 오류 화면일 수 있습니다."
    if ext in (".xlsx", ".xlsm"):
        return "엑셀 파일 형식이 아닙니다."
    return None


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
        step = self.steps[-1] if self.steps else None
        if no and step is not None and not user_tab(page):
            step.setdefault("opens", no)                 # 앞 동작이 새 창을 열었다 (사람이 연 새 탭은 아니다)

        def became_browser_page(frame):                  # Edge 다운로드 창은 주소 없이 생겼다가 곧 edge:// 주소가 붙는다
            if frame is page.main_frame and frame.url.startswith(BROWSER_PAGES):
                page.remove_listener("framenavigated", became_browser_page)
                self._browser_page(page, no, step)
        if no:
            page.on("framenavigated", became_browser_page)
        page.on("dialog", self._dialog)
        page.on("download", self._download)
        # add_init_script 만 믿으면 안 된다: window.open 새 창은 빈 페이지에만 심기고 진짜 주소의 문서에는 안 심긴다
        # (2026-09-30 시험). 문서가 바뀔 때마다 한 번 더 심는다 - 문서마다 표시가 있어 두 번 붙지는 않는다
        page.on("framenavigated", self._inject)
        page.on("domcontentloaded", lambda pg: [self._inject(f) for f in pg.frames])

    def _browser_page(self, page, no, step):
        """새 창이 나중에 브라우저 자체 페이지로 밝혀졌다 - 앞 동작이 연 창으로 적은 것을 되돌린다 (2026-10-06: Edge 는 파일을
        받으면 다운로드 창 edge://downloads-hub 을 페이지로 열어, 재생이 오지 않을 새 창을 15초 기다리다 실패했다)."""
        if step is not None and step.get("opens") == no:
            del step["opens"]

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
        if isinstance(ev, str):
            ev = json.loads(ev)         # 페이지는 JSON 글자로 보낸다 (JS 의 send)
        step = {"kind": ev["kind"], "page": self._no(source["page"]), "frame": frame_info(source["frame"]),
                "url": url_path(ev["url"]), "target": ev["target"], "t": ev["t"]}
        for k in ("value", "option", "checked", "firstSeen"):
            if k in ev:
                step[k] = ev[k]
        if ev.get("row"):
            step["row"] = ev["row"]        # 목록 줄을 눌렀다 - 메일 고르기 (set_pick)
        last = self.steps[-1] if self.steps else None
        if (step["kind"] == "click" and ev.get("detail", 1) >= 2 and last and last["kind"] == "click"
                and same_target(last, step) and step["t"] - last["t"] < 600):
            last["double"] = True           # 더블클릭은 한 단계 (재생이 두 번 요청하지 않게)
            return
        if last and step["kind"] in KINDS_MERGE and last["kind"] == step["kind"] and same_target(last, step):
            last.update({k: step[k] for k in ("value", "option", "t") if k in step})
            return
        for hv in (ev.get("hovers") or []) if step["kind"] == "click" else []:
            if last is None or last["t"] < hv["t"]:
                # 마우스를 올리자 보이게 된 것을 눌렀다 (그 사이 다른 조작 없음) - 재생 때 먼저 올려 메뉴를 열게 한다 (두 단이면 차례로)
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


def navigated(before, s):
    """before 단계가 s 의 창(같은 틀)을 다른 주소로 넘겼다 (로그인 → 메인). 그러면 s 의 화면 것은 모두 그 뒤에 '새로 생긴 것' 이라
    그것으로 거르면 안 된다 - 재생은 before 앞의 화면을 적어 두는데, 머리 띠 아이콘처럼 두 화면에 같은 것이 있으면 '원래 있던 것' 으로
    빠져 못 찾는다 (2026-10-02 erpia.net 로그인 뒤 글자 없는 'a', 2026-10-13 찾음)."""
    fid = lambda st: ((st.get("frame") or {}).get("main", True), (st.get("frame") or {}).get("name", ""))   # noqa: E731 - 틀 주소는 넘어가며 바뀐다
    same_frame = before["kind"] in NAV_KINDS or fid(before) == fid(s)
    return before.get("page") == s.get("page") and same_frame and before.get("url") != s.get("url")


def auth_start(steps):
    """인증 차례를 잡는 단계 번호(1부터) - 인증번호 단계 앞의 첫 칸 넣기(아이디). 그 앞의 검색·이동은 차례를 기다리지 않는다
    (사용자 2026-10-16: 빙 검색으로 들어가는 사이트가 앞 사이트의 인증이 끝난 뒤에야 검색부터 시작해 오래 걸렸다)."""
    last = max((i for i, s in enumerate(steps) if s["kind"] == "otp"), default=0)
    return next((i for i in range(last) if steps[i]["kind"] in ("fill", "secret")), 0) + 1


def auth_end(steps):
    """2차 인증이 끝나는 단계 번호(1부터) - 인증번호 단계 다음의 누르기·엔터([확인])까지. 인증번호 단계가 없으면 None.
    병렬 수집(사용자 2026-10-15): 인증 사이트는 첫 단계(로그인)부터 여기까지를 한 번에 하나씩 - 앞 사이트가 인증 중이면
    뒤 인증 사이트는 로그인 앞에서 기다린다. 인증 없는 사이트는 기다리지 않는다."""
    last = max((i for i, s in enumerate(steps) if s["kind"] == "otp"), default=None)
    if last is None:
        return None
    return next((i for i in range(last + 1, len(steps)) if steps[i]["kind"] in ("click", "enter")), last) + 1


def appears_after(steps, j):
    """j 단계가 '몇 단계 뒤에 새로 생긴 것' 으로 골라야 하면 그 단계 번호, 아니면 None (옛 기록도 navigated 로 거른다)."""
    s, k = steps[j], steps[j].get("appearsAfter")
    if k is None or not ambiguous(s) or navigated(steps[k], s):
        return None
    return k


def loose_new(steps, j):
    """j 의 '새로 생긴 것' 이 화면이 넘어간(또는 그 창이 새로 열린) 바로 뒤의 마우스 올리기 뒤로 적혔나 - 사람이 지나가며 마우스를
    올리는 동안 늦게 그려진 것이 새로 생긴 것으로 적힌다 (비즈메카 포털 메일 카드: 카드 안 메일 미리보기가 로그인 뒤 늦게 와서
    '9단계 뒤에 새로 생긴 것'. 네이버 메일: [메일] 로 연 새 창의 메일 목록이 마우스 올리기 뒤로 적혔다, 2026-10-16).
    그러면 새로 생긴 것 중에 없을 때 원래 있던 것에서도 찾는다 - 새로 생긴 것에서 찾던 기록은 그대로."""
    k = appears_after(steps, j)
    if k is None or steps[k]["kind"] != "hover":
        return False
    i = k
    while i > 0 and steps[i]["kind"] == "hover":
        i -= 1
    return navigated(steps[i], steps[j]) or steps[i].get("opens") == steps[j].get("page")


def set_pick(steps, i, prefix):
    """i 단계(목록 줄 누르기)를 '제목이 prefix 로 시작하는 메일마다' 로, prefix 가 None·빈 글자면 되돌린다. steps 를 고친다."""
    if prefix:
        steps[i]["pick"] = {"prefix": prefix}
    else:
        steps[i].pop("pick", None)
    return steps


def pick_body(steps, i):
    """메일 고르기 i 단계 뒤 메일마다 되풀이할 묶음의 끝 (마지막 받기 단계 번호). 받기 단계가 없으면 None."""
    return next((j for j in range(len(steps) - 1, i, -1) if steps[j].get("download")), None)


def mail_key(key, title):
    """처리한 메일을 기억하는 표시 - 줄의 고유 표시 (data-key 등), 없으면 제목 글자."""
    return key or "제목:" + title


def title_starts(prefix, *titles):
    """제목이 prefix 로 시작하나 - 보이는 제목·칸 글자 전체 중 하나라도. 전각 ＞ 처럼 모양만 다른 글자는 같게 본다 (NFKC)."""
    want = unicodedata.normalize("NFKC", prefix or "").strip()
    return bool(want) and any(unicodedata.normalize("NFKC", t or "").strip().startswith(want) for t in titles)


def auto_pick(steps, prefix):
    """메일 시작 문구(프리셋 칸)로 '메일마다' 로 바꿀 단계 - 목록 줄 누르기 중 연 메일의 제목이 prefix 로 시작하는 마지막 것.
    없으면 None (옵저버가 저장을 막는다). 연 줄의 제목은 기록 때 목록에서 그 줄(key)의 보이는 제목, 아니면 누른 글자."""
    for i in range(len(steps) - 1, -1, -1):
        s = steps[i]
        row = s.get("row") if s["kind"] == "click" else None
        if not row:
            continue
        mine = [x for x in row.get("list", []) if row.get("key") and x["k"] == row["key"]]
        titles = [t for x in mine for t in (x.get("s"), x["t"])] + [(s.get("target") or {}).get("text")]
        if title_starts(prefix, *titles):
            return i
    return None


def pick_seed(s):
    """기록할 때 목록에 보이던 메일 중 제목이 정한 글자로 시작하는 것 (저장하면 '이미 처리' 로 - 사용자 2026-10-14 (나)).
    목록의 s = 보이는 제목 (중요·전달 같은 숨은 표시를 뺀 것, 옛 기록에는 없다), t = 칸 글자 전체."""
    prefix = (s.get("pick") or {}).get("prefix") or ""
    return [mail_key(x["k"], x.get("s") or x["t"]) for x in (s.get("row") or {}).get("list", [])
            if title_starts(prefix, x.get("s"), x["t"])]


class MailMemory:
    """프리셋 하나가 처리한 메일 {표시: 날짜} - 같은 메일의 첨부를 두 번 받지 않게. MAIL_MEMORY_DAYS 지난 것은 저장할 때 버린다."""

    def __init__(self, path):
        self.path = path
        try:
            with open(path, encoding="utf-8") as f:
                self.keys = dict(json.load(f).get("keys") or {})
        except (OSError, ValueError, AttributeError):
            self.keys = {}

    def add_all(self, keys):
        today = datetime.date.today().isoformat()
        for k in keys:
            self.keys[k] = today

    def save(self):
        cut = (datetime.date.today() - datetime.timedelta(days=MAIL_MEMORY_DAYS)).isoformat()
        self.keys = {k: d for k, d in self.keys.items() if d >= cut}
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"keys": self.keys}, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    def clear(self):
        self.keys = {}
        self.save()


# 목록 줄들 (key, 제목) - JSON 글자로 주고받는다 (사이트가 Map 을 바꿔치기해도, SNAP_JS 와 같다)
ROWS_JS = r"""a => { const o = JSON.parse(a), n = s => (s || '').replace(/\s+/g, ' ').trim();
  const key = r => r.getAttribute('data-key') || r.getAttribute('data-id') || r.getAttribute('data-uid') || r.id || '';
  __SEEN__
  return JSON.stringify([...document.querySelectorAll(o.sel)].map(r => { const c = (o.inner ? r.querySelector(o.inner) : null) || r;
    return [key(r), n(c.textContent).slice(0, 120), seenText(c)]; })); }""".replace("__SEEN__", SEEN_JS)


def otp_like(s, nxt=None):
    """사람이 문자로 받은 인증번호를 친 칸으로 보인다 (숫자 4~8자리 + 칸 단서에 '인증'·OTP 같은 말, 또는 바로 다음 단계의
    알림창에 '인증' - 단서 없는 칸 edtAttcInput 뒤 '인증되었습니다.', 농협몰 2026-10-15)."""
    t = s.get("target") or {}
    hints = " ".join(str(t.get(k) or "") for k in ("placeholder", "label", "name", "id", "aria", "title"))
    told = any("인증" in d for d in (nxt or {}).get("dialogs", []))
    return s["kind"] == "fill" and bool(OTP_VALUE.match(str(s.get("value", "")).strip())) and (bool(OTP_HINT.search(hints)) or told)


def set_otp(steps, i, on):
    """i 단계를 인증번호 칸으로 (값을 지우고, 바로 앞 같은 창 누르기를 '인증번호 받기' 로) 또는 되돌린다 (되돌리면 값은 빈 칸).
    ACTOR 단계 목록의 [인증번호 칸] 단추와 기록 다듬기가 쓴다. steps 를 고친다."""
    s = steps[i]
    send = next((j for j in range(i - 1, -1, -1) if steps[j]["kind"] == "click" and steps[j].get("page") == s.get("page")), None)
    if on:
        s["kind"] = "otp"
        s.pop("value", None)
        s.pop("date", None)
        if send is not None:
            steps[send]["otpSend"] = True
    else:
        s["kind"] = "fill"
        s.setdefault("value", "")
        if send is not None and not any(x["kind"] == "otp" for x in steps[send + 1:i] + steps[i + 1:]):
            steps[send].pop("otpSend", None)
    return steps


def finalize(steps, record_date, start_url, viewport=None):
    """기록을 다듬는다: 기다린 시간, 날짜는 오늘 기준, 공지 닫기는 '있을 때만', 아이디·비밀번호는 설정 값."""
    out, prev = [], None
    ts = [s["t"] for s in steps]
    for i, s in enumerate(steps):
        s = dict(s)
        seen = s.pop("firstSeen", None)
        if seen is not None:              # 몇 번째 단계를 한 뒤에 나타났나 (그 단계 전에는 없었다)
            k = max((j for j in range(i) if ts[j] < seen), default=None)
            if k is not None and not navigated(steps[k], s):
                s["appearsAfter"] = k
        s["gap"] = s["t"] - prev if prev else 0
        prev = s.pop("t")
        if otp_like(s, steps[i + 1] if i + 1 < len(steps) else None):
            set_otp(out + [s], len(out), True)
            out.append(s)
            continue
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
        browser = edge(p.chromium.launch, headless=headless)
        context = browser.new_context(accept_downloads=True)
        rec = Recorder(context, sample_dir)
        page = context.new_page()
        page.goto(start_url)
        if human:
            human(page)
        else:
            print("창에서 평소처럼 조작하여 주십시오. 파일을 다운로드한 뒤 브라우저 창을 닫으면 기록이 끝납니다.")
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
        d = f"{href}로 이동"
        if SESSION_Q.search(s["href"]):
            d += " (주소에 로그인 세션 값을 감지했습니다. 다음 회차부터 실행에 문제가 발생할 수 있습니다.)"
    elif k == "back":
        d = "뒤로 가기"
    elif k == "newtab":
        d = "새 탭 열기"
    elif k == "click" and s.get("pick"):
        d = f"제목이 '{s['pick']['prefix']}' 로 시작하는 메일마다 ↓"
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
    elif k == "otp":
        d = f"'{n}' 칸에 문자로 받은 인증번호 넣기"
    else:
        d = k
    if s.get("otpSend"):
        d += " (인증번호 문자 요청)"
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


class Cancelled(Exception):
    """[■ 중단] (옵저버 미리보기) - 찾거나 기다리던 것을 그만둔다."""


STOPPED = "[■ 중단]을 눌러 중단하였습니다."


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
    href = t.get("href") or ""
    if tag == "a" and href not in ("", "#") and not href.lower().startswith("javascript:"):
        out.append(("링크 주소", f"a[href={q(href)}]", None))     # 글자 없는 아이콘 링크 (2026-10-13). 세션 값이 든 주소면 안 맞아 다음 단서로
    if tag != "input" and re.search(r"\d", t["text"]) and re.search(r"[^\d\s]", t["text"]) and len(t["text"]) < 80:   # '메일 11' → '메일 10': 안 읽은 수가 바뀌는 메뉴 (비즈메카 2026-10-14). 쪽 번호 '2' 처럼 숫자뿐인 글자는 빼고
        pat = "".join(r"\d+" if p.isdigit() else r"\s*" if p.isspace() else re.escape(p) for p in re.split(r"(\d+|\s+)", t["text"]) if p)
        out.append(("숫자 뺀 글자", f"{tag}:text-matches({q('^' + pat + '$')})", t["textIndex"] if t["textCount"] > 1 else None))
    out.append(("위치", t["css"], None))
    if t["text"] and t["textCount"] > 1:
        sel = f"input[value={q(t['text'])}]" if tag == "input" else f"{tag}:text-is({q(t['text'])})"
        out.append((f"글자 {t['textIndex'] + 1}번째", sel, t["textIndex"]))
    # 글자가 안쪽 칸(div·span)에 들었거나 나뉘어 든 것은 :text-is·:text-matches 가 못 잡는다 (빙 광고 제목, 비즈메카 메일 카드 '메일 5',
    # 2026-10-16). 기록기처럼 하위까지 합친 글자로 본다. 앞 단서가 모두 못 찾을 때만 쓰이게 맨 뒤에 (예전 기록이 찾던 것은 그대로)
    if tag != "input" and t["text"]:
        whole = "normalize-space(translate(., '\u00a0', ' '))"
        nth = t["textIndex"] if t["textCount"] > 1 else None
        if len(t["text"]) < 80:
            out.append(("글자(안쪽 포함)", f"xpath=//{tag}[{whole}={xq(t['text'])}]", nth))
        if re.search(r"\d", t["text"]) and re.search(r"[^\d\s]", t["text"]) and len(t["text"]) < 80:
            bare = re.sub(r"[\d\s]", "", t["text"])
            out.append(("숫자 뺀 글자(안쪽 포함)", f"xpath=//{tag}[translate({whole}, '0123456789 ', '')={xq(bare)} "
                                              f"and translate(., '0123456789', '') != .]", nth))
    return out


def xq(s):
    """XPath 글자 값 (따옴표가 섞여도)."""
    if '"' not in s:
        return f'"{s}"'
    if "'" not in s:
        return f"'{s}'"
    return "concat(" + ", '\"', ".join(f'"{p}"' for p in s.split('"')) + ")"


class OtpRetry(Exception):
    """인증번호를 못 받았거나 사이트가 거절했다 - '인증번호 받기' 부터 다시 (모두 OTP_TRIES 번)."""

    def __init__(self, why, rejected=False):
        super().__init__(why)
        self.rejected = rejected


class Replayer:
    def __init__(self, context, rec, creds, out_dir, code, today=None, review=False, log=print, step_timeout=STEP_WAIT,
                 hide_values=False, shot_dir=None, step_tries=STEP_TRIES):
        self.context, self.rec, self.creds, self.out_dir, self.code = context, rec, creds, out_dir, code
        self.today = today or datetime.date.today()
        self.review, self.log, self.step_timeout, self.step_tries = review, log, step_timeout, step_tries
        self.hide_values = hide_values       # 로그에 칸에 친 값·주소 ? 뒤를 안 싣는다 (대시보드로 간다)
        self.shot_dir = shot_dir or out_dir  # 실패 사진 자리 (프리페어는 받은 파일 폴더에 사진을 두지 않는다)
        self.pages, self.watched, self.saved, self.results, self.baseline = {}, set(), [], [], {}
        self.progress = None        # (번호, run/ok/skip/fail, 설명) - 화면이 단계마다 표시
        self.page_hook = None       # 첫 창이 뜨면 (창 자리 맞추기)
        self.first_page = None      # 이미 있는 창에서 시작 (옵저버·프리페어가 연 창)
        self.fit_viewport = False   # 기록 때 창 안쪽 크기로 (프리페어. 옵저버 미리보기는 창 자리를 맞춘다)
        self.cancel = None          # threading.Event - 켜지면 곧 멈춘다 (찾기·기다리기 중에도. 옵저버 [■ 중단])
        self.pause = None           # threading.Event - 켜져 있으면 다음 단계 앞에서 기다린다 (옵저버 [Ⅱ 일시정지])
        self.download_timeout_ms = DOWNLOAD_TIMEOUT_MS
        self.downloads = []         # 지금 단계에서 온 파일 - 어느 창에서 왔든 (누른 창 말고 팝업이 내려 줄 때가 있다)
        self.elapsed = 0.0
        # 2차인증 (설계 13절): otp = 휴대폰 중계 (open() → 요청, wait(요청, 초, tick, field) → 번호|None, close(요청)). 없으면 인증번호 칸에서 멈춘다
        self.otp, self.otp_wait = None, OTP_WAIT
        self.otp_req, self.otp_try, self.otp_send, self.otp_check, self.otp_mark = None, 0, None, None, 0
        self.dialogs = []           # 재생 중 뜬 알림창 글 (사이트가 인증번호를 거절했나 본다)
        # 메일 고르기: mail_memory = MailMemory (ACTOR - 처리한 메일을 건너뛰고 기억), pick_preview = 기억과 상관없이 1통 (옵저버 미리보기)
        self.mail_memory, self.pick_preview, self.no_target = None, False, False
        # 인증 차례 (병렬 수집): (threading.Lock, 첫 단계, 끝 단계) - 첫 단계 앞에서 잡고 끝 단계를 지나면 놓는다 (auth_start·auth_end). 없으면 안 기다린다
        self.gate, self.gate_held = None, False

    def _watch(self, page):
        if page in self.watched:
            return
        self.watched.add(page)

        def on_dialog(d):
            self.dialogs.append(d.message)
            self.log(f"      알림창 '{_cut(d.message, self.hide_values)}' -> 확인")
            try:
                d.accept()
            except Exception:
                pass                # 그 사이 사이트가 닫았다
        page.on("dialog", on_dialog)
        page.on("download", lambda dl: self.downloads.append(dl))

    # --- 중단·일시정지 ---
    def _gate_release(self):
        if self.gate_held:
            self.gate_held = False
            self.gate[0].release()
            self.log("  다음 사이트에 인증 차례를 넘깁니다.")

    def _check_cancel(self):
        if self.cancel is not None and self.cancel.is_set():
            raise Cancelled()

    def _idle(self, ms, page=None):
        """ms 동안 쉰다 - 살아 있는 창에서 기다려야 Playwright 가 그동안 알림창·파일을 받는다."""
        for pg in ([page] if page is not None else []) + list(self.context.pages):
            try:
                if not pg.is_closed():
                    pg.wait_for_timeout(ms)
                    return
            except Exception:
                pass
        time.sleep(ms / 1000)

    def _wait(self, page, ms):
        """page.wait_for_timeout 대신 - 0.2초씩 쉬며 [■ 중단] 을 본다."""
        end = time.time() + ms / 1000
        while True:
            self._check_cancel()
            left = end - time.time()
            if left <= 0:
                return
            self._idle(min(200, left * 1000), page)

    def _hold(self, i):
        """다음 단계 앞: 중단이면 Cancelled, 일시정지면 풀릴 때까지 기다린다 (하던 단계는 끝까지 한다).
        인증 차례(gate)가 있으면 첫 단계부터 끝 단계까지는 차례를 잡고 간다 - 인증번호를 다시 받으러 앞 단계로 돌아가도 잡은 채로."""
        self._check_cancel()
        if self.gate is not None:
            lock, start, end = self.gate
            if not self.gate_held and start <= i <= end:
                if not lock.acquire(blocking=False):
                    self.log(f"  {i:2d}단계 앞: 다른 사이트가 인증하는 중입니다. 인증 차례를 기다립니다.")
                    while not lock.acquire(timeout=0.5):
                        self._check_cancel()
                self.gate_held = True
            elif self.gate_held and i > end:
                self._gate_release()
        if self.pause is None or not self.pause.is_set():
            return
        if self.progress:
            self.progress(i, "paused", "")
        self.log(f"  {i:2d}단계 앞에서 일시정지")
        while self.pause.is_set():
            self._check_cancel()
            self._idle(200)

    def _until_download(self, page, act):
        """act() 를 하고 파일이 올 때까지 기다린다 - 누른 창이든 그 단추가 연 새 창이든 (2026-10-02: 팝업이 내려 주는 파일을
        누른 창에서만 기다려 못 받았다). 안 오면 download_timeout_ms 뒤 그 단계 실패."""
        self.downloads = []
        start = time.time()             # 누르기 전부터 - 누르기가 느린 페이지를 기다린 시간도 센다
        act()
        end, note = start + self.download_timeout_ms / 1000, start + self.step_timeout
        while not self.downloads:
            self._check_cancel()
            now = time.time()
            if now > end:
                raise NotFound(f"{self.download_timeout_ms / 1000:.0f}초 동안 파일 다운로드가 시작되지 않았습니다.")
            if now > note:              # 쇼핑몰이 엑셀을 만드는 중일 수 있다 - 멈춘 줄 알지 않게 (2026-10-15)
                self.log(f"      파일 다운로드를 기다리는 중입니다. ({now - start:.0f}초 경과 / 최대 {self.download_timeout_ms / 1000:.0f}초)")
                note = now + self.step_timeout
            self._idle(200, page)
        return self.downloads[0]

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

    def _same(self, loc, t, digits=False):
        """찾은 것이 기록한 것과 모양이 같은가 (id·위치가 다른 것을 가리키게 된 경우를 거른다). digits = 숫자만 달라도 같다 (숫자 뺀 글자 단서)."""
        try:
            got = loc.evaluate("e => e.tagName.toLowerCase() + '|' + (e.getAttribute('type') || '').toLowerCase()").split("|", 1)
            if got[0] != t["tag"] or (t["tag"] == "input" and got[1] != t["type"]):
                return False
            if not t["text"]:
                return True
            got = loc.evaluate(TEXT_OF)
            return got == t["text"] or digits and NO_DIGITS(got) == NO_DIGITS(t["text"])
        except Exception:
            return False

    def _pick(self, loc, n, nth, prev):
        """단서가 가리키는 것들 중 하나. prev 가 있으면 (기록 때 새로 생긴 것을 눌렀으면) 그 뒤 새로 생긴 것만."""
        if prev is not None:
            sigs = json.loads(loc.evaluate_all(SIGS_JS))
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
            return set(json.loads(fr.evaluate(SNAP_JS)))
        except Exception:
            return set()

    def _find(self, page, s, prev, loose=False):
        """loose: 새로 생긴 것 중에 없으면 원래 있던 것에서도 (loose_new)."""
        t = s["target"]
        if s.get("loose"):          # 메일 고르기 묶음 - 메일마다 글자(첨부 이름 등)가 달라 글자 말고 자리·속성으로
            t = dict(t, text="", textCount=0)
        cands = candidates(t)
        optional = s.get("optional") or s["kind"] == "hover"     # 마우스 올리기는 거들 뿐 - 없으면 건너뛰고 다음 누르기가 연다
        deadline, tries = time.time() + (OPTIONAL_WAIT if optional else self.step_timeout), 1
        while True:
            self._check_cancel()
            frame = self._frame(page, s["frame"])
            for pv in ((prev, None) if loose and prev is not None else (prev,)) if frame is not None else ():
                for how, sel, nth in cands:
                    try:
                        loc = frame.locator(sel)
                        loc = self._pick(loc, loc.count(), nth, pv)
                    except Exception:
                        continue            # 화면이 바뀌는 중
                    if loc is not None and self._same(loc, t, how.startswith("숫자 뺀 글자")):
                        return frame, loc, how + (", 새로 생긴 것" if pv is not None else "")
            if time.time() > deadline:
                if optional:
                    raise Skip("화면에 없음")
                if tries >= self.step_tries:
                    raise NotFound(f"{self.step_timeout:.0f}초씩 {tries}번 찾았으나 대상을 찾지 못했습니다. (단서: {', '.join(c[0] for c in cands)})")
                tries += 1
                self.log(f"      {self.step_timeout:.0f}초 동안 대상을 찾지 못했습니다. 다시 찾습니다. ({tries}/{self.step_tries})")
                deadline = time.time() + self.step_timeout
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
                            self.log(f"      화면을 가리는 공지를 닫았습니다. ('{text}')")
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
                self.log("      가려진 메뉴를 마우스를 올려 열었습니다.")
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
            if "click action done" in msg:      # 눌렀는데 그 뒤 페이지가 늦게 오는 것 (느린 엑셀 받기) - 다시 누르면 두 번 요청된다 (2026-10-15)
                return
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
        raise Skip("마우스를 올리지 못했습니다.")

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
        elif k == "otp":
            self._fill(loc, self._otp_code(page, loc))
        elif k == "select":
            try:
                loc.select_option(label=s["option"], timeout=5000)
            except Exception:
                loc.select_option(value=s["value"], timeout=5000)
        elif k == "check":
            loc.set_checked(bool(s["checked"]), timeout=5000)
        elif k == "enter":
            loc.press("Enter", timeout=5000)

    # --- 2차인증 (설계 13절) ---
    def _otp_open(self):
        """요청을 연다 ('인증번호 받기' 누르기 전 - 문자가 요청보다 먼저 오면 휴대폰이 보내지 않는다)."""
        self._otp_close()
        self.otp_try += 1
        self.otp_req = self.otp.open()
        self.log(f"      인증번호 요청을 시작하였습니다. ({self.otp_try}/{OTP_TRIES})")

    def _otp_close(self):
        if self.otp is not None and self.otp_req is not None:
            try:
                self.otp.close(self.otp_req)
            except Exception as e:
                self.log(f"      (인증번호 요청을 지우지 못했습니다: {type(e).__name__})")
        self.otp_req = None

    def _otp_code(self, page, loc):
        if self.otp is None:
            raise NotFound("인증 휴대폰이 설정되지 않았습니다. 옵저버 저장 화면에서 인증 휴대폰을 선택하여 주십시오.")
        if self.otp_req is None:
            self._otp_open()            # '인증번호 받기' 를 못 알아본 기록 - 지금이라도 연다
        self.log(f"      인증번호 문자를 기다리는 중입니다. ({self.otp_try}/{OTP_TRIES}, 최대 {self.otp_wait:.0f}초)")
        code = self.otp.wait(self.otp_req, self.otp_wait, lambda sec: self._wait(page, sec * 1000), field=loc)
        if not code:
            raise OtpRetry("인증번호 문자가 수신되지 않았습니다.")
        self.otp_mark = len(self.dialogs)
        return code

    def _otp_rejected(self, page, otp_step, check_step):
        """인증번호를 넣고 [확인] 한 뒤: 사이트가 거절했나 - 알림창에 '인증 … 틀림·불일치·만료' 가 떴거나, 3초 뒤에도 같은 주소에 그 칸이 그대로.
        기록 때 사람이 통과하며 본 알림창(check_step 의 dialogs)과 같은 글이 뜨면 통과 - 사이트마다 성공 말투가 달라서."""
        passed = set(check_step.get("dialogs", ()))

        def said():                 # 알림창으로 답했나: False 통과 / True 거절 / None 아직 모름
            got = self.dialogs[self.otp_mark:]
            if passed & set(got):
                return False
            return True if any(OTP_REJECT.search(m) for m in got) else None
        if said() is None:
            self._wait(page, 3000)
        if said() is not None:
            return said()
        frame = self._frame(page, otp_step["frame"])
        if frame is None or url_path(frame.url) != otp_step["url"]:
            return False
        for how, sel, nth in candidates(otp_step["target"]):
            try:
                loc = frame.locator(sel)
                if loc.count() == 1 and loc.first.is_visible() and not (loc.first.input_value() or "").strip():
                    return True         # 칸이 비워진 채 그대로 (틀린 번호를 지우고 다시 받으라는 사이트)
            except Exception:
                continue
        return False

    def _save(self, dl):
        """받은 파일을 (사이트코드)이름 으로 둔다. 다 받을 때까지 기다리고 (느려도), 끊겼거나 쓸 수 없는 파일이면
        지우고 그 단계를 실패로 - PROCESS 가 반쪽 파일·로그인 화면을 ERPia 에 올리지 않게 (2026-10-15 메모 5).
        ponytail: Playwright 는 받는 중인 크기를 알려 주지 않아, 서버가 연결만 쥐고 아무것도 안 보내면 브라우저가 끊을 때까지 기다린다."""
        failure = dl.failure()          # 다 받거나 끊길 때까지 기다린다
        if failure:
            raise NotFound(f"파일 다운로드가 중간에 끊겼습니다. ({failure})")
        os.makedirs(self.out_dir, exist_ok=True)
        path = os.path.join(self.out_dir, f"({self.code}){dl.suggested_filename}")
        stem, ext = os.path.splitext(path)
        i = 1
        while os.path.exists(path):
            path = f"{stem} ({i}){ext}"
            i += 1
        dl.save_as(path)
        problem = download_problem(path)
        if problem:
            try:
                os.remove(path)
            except OSError:
                pass
            raise NotFound(f"다운로드한 파일({os.path.basename(path)})을 사용할 수 없어 삭제하였습니다. {problem}")
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
            raise NotFound(f"창 {s['page']}이(가) 없습니다.")
        # 사람이 기다린 시간의 절반 (0.3~3초): 화면이 따라올 틈
        self._wait(page, min(max(s.get("gap", 0) * 0.5, 300), SETTLE_MAX_MS))
        if s["kind"] == "goto":
            page.goto(s["href"], wait_until="domcontentloaded")
            return "주소로 이동"
        if s["kind"] == "back":
            page.go_back(wait_until="domcontentloaded")
            return "뒤로"
        frame, loc, how = self._find(page, s, self.baseline.get(i), i in self.loose)
        if url_path(frame.url) != s["url"]:
            self.log(f"      (주소가 다름: 기록 {s['url']} / 지금 {url_path(frame.url)})")
        if self.review:             # 누를 곳에 잠깐 빨간 테두리 (Playwright highlight 는 글자 표가 화면에 쌓인다)
            try:
                loc.evaluate("e => { const o = e.style.outline, f = e.style.outlineOffset;"
                             " e.style.outline = '3px solid #dc2626'; e.style.outlineOffset = '2px';"
                             " setTimeout(() => { e.style.outline = o; e.style.outlineOffset = f; }, 900); }")
            except Exception:
                pass
            self._wait(page, 900)

        def act():
            if not s.get("opens"):
                return self._act(page, loc, s)
            with page.expect_popup(timeout=15000) as pi:
                self._act(page, loc, s)
            self.pages[s["opens"]] = pi.value
            self._watch(pi.value)
            if not s.get("download"):       # 파일만 내려 주는 팝업은 곧 스스로 닫힌다
                pi.value.wait_for_load_state("domcontentloaded")
        if s.get("download"):
            how += f", 받음 {os.path.basename(self._save(self._until_download(page, act)))}"
        else:
            act()
        return how

    def run(self):
        if self.rec.get("version") != RECORD_VERSION:
            raise ValueError(f"알 수 없는 기록 형식입니다. (version {self.rec.get('version')!r}) "
                             "옵저버와 ACTOR 오토파일럿을 같은 버전으로 업데이트하여 주십시오.")
        page = self.first_page or self.context.new_page()
        if self.page_hook:
            self.page_hook(page)
        if self.fit_viewport and self.rec.get("viewport"):
            page.set_viewport_size(self.rec["viewport"])        # 기록 때 창 안쪽 크기 (반응형 사이트의 메뉴 모양)
        self._watch(page)
        self.context.on("page", self._watch)                    # 기록에 없던 새 창도 - 알림창을 받고 파일을 기다린다
        self.pages[0] = page
        steps = self.rec["steps"]
        if not (steps and steps[0]["kind"] == "goto"):         # 주소줄로 시작한 기록은 그 단계가 곧 시작 주소
            page.goto(self.rec["start_url"], wait_until="domcontentloaded")
        self.needs = {}
        for j in range(len(steps)):
            k = appears_after(steps, j)
            if k is not None:
                self.needs.setdefault(k, []).append(j)
        self.loose = {j for j in range(len(steps)) if loose_new(steps, j)}
        started = time.time()
        try:
            self._run_steps(steps)
        finally:
            self._otp_close()           # 성공·실패·중단 모두 - 요청·번호를 서버에 남기지 않는다
            self._gate_release()        # 인증 중에 멈춰도 뒤 사이트가 영영 기다리지 않게
        self.elapsed = time.time() - started
        return all(r[1] != "fail" for r in self.results) and len(self.results) == len(steps)

    # --- 메일 고르기 (사용자 2026-10-14) ---
    def _mail_rows(self, page, s, wait):
        """s 를 기록한 목록의 줄들 [(key, 제목)]. wait 초 안에 줄이 안 보이면 빈 목록."""
        row, end = s["row"], time.time() + wait
        while True:
            self._check_cancel()
            frame = self._frame(page, s["frame"])
            try:
                if frame is not None and frame.locator(row["sel"]).first.is_visible():
                    return frame, [tuple(x) for x in json.loads(frame.evaluate(ROWS_JS, json.dumps(row)))]
            except Exception:
                pass                # 화면이 바뀌는 중
            if time.time() > end:
                return frame, []
            page.wait_for_timeout(250)

    def _run_pick(self, i, steps):
        """i 단계(1부터) = 메일 고르기: 제목이 정한 글자로 시작하는 메일마다 열고 묶음 단계(받기까지)를 한다.
        결과는 고르기와 묶음 단계 모두 여기서 적는다. 돌려주는 값 = 묶음 마지막 단계 번호 (다음은 그 뒤부터)."""
        s, end = steps[i - 1], pick_body(steps, i - 1)
        if end is None:
            raise NotFound("메일 선택 단계 아래에 파일 다운로드 단계가 없습니다.")
        prefix, body = s["pick"]["prefix"], range(i, end + 1)
        page = self.pages.get(s["page"])
        if page is None or page.is_closed():
            raise NotFound(f"창 {s['page']}이(가) 없습니다.")
        self._wait(page, min(max(s.get("gap", 0) * 0.5, 300), SETTLE_MAX_MS))
        frame, rows = self._mail_rows(page, s, self.step_timeout * self.step_tries)
        if frame is None or not rows:
            raise NotFound(f"{self.step_timeout * self.step_tries:.0f}초 동안 메일 목록을 찾지 못했습니다.")
        hits = [(k, seen or t) for k, t, seen in rows if title_starts(prefix, seen, t)]   # 제목 = 보이는 글자 (중요·전달 표시 뺌)
        mem = None if self.pick_preview else self.mail_memory
        todo = hits[:1] if self.pick_preview else [h for h in hits if mem is None or mail_key(*h) not in mem.keys]
        self.log(f"      제목이 '{prefix}' 로 시작하는 메일 {len(hits)}통 중 새 메일 {len(todo)}통")
        if len(todo) > MAIL_PICK_MAX:
            self.log(f"      메일은 한 번에 최대 {MAIL_PICK_MAX}개까지 처리할 수 있습니다. 나머지는 다음 실행 때 처리됩니다.")
            todo = todo[:MAIL_PICK_MAX]
        if not todo:
            self.no_target = True
            self.log("      다운로드할 새 메일이 없습니다. (대상 없음)")
            self.results.append((i, "ok", "대상 없음"))
            self.results += [(j + 1, "skip", "대상 없음") for j in body]
            return end + 1
        for n, (k, t) in enumerate(todo, 1):
            if n > 1:               # 앞 메일을 연 채다 - 목록으로 (메일 화면이 주소 # 만 바꾸는 비즈메카도 뒤로 가기로 돌아온다)
                try:
                    page.go_back(timeout=MAIL_BACK_WAIT * 1000)
                except Exception:
                    pass
                frame, rows = self._mail_rows(page, s, MAIL_BACK_WAIT)
                if not rows:
                    raise NotFound("메일 목록으로 돌아가던 중 문제가 발생했습니다.")
            self.log(f"      [{n}/{len(todo)}] 메일 열기: {t[:CUT] if self.hide_values else t}")
            idx = next((x for x, r in enumerate(rows) if (r[0] == k if k else (r[2] or r[1]) == t)), None)
            if idx is None:
                raise NotFound(f"메일을 목록에서 다시 찾지 못함: {t[:40]}")
            loc = frame.locator(s["row"]["sel"]).nth(idx)
            if s["row"]["inner"]:
                loc = loc.locator(s["row"]["inner"]).first
            self._click(page, loc)
            for j in body:
                if self.progress:
                    self.progress(j + 1, "run", "")
                try:
                    how = self._step(j, dict(steps[j], loose=True))
                except Skip as e:
                    how = f"건너뜀 ({e})"
                self.log(f"  {j + 1:2d}/{len(steps)} {describe(steps[j], self.hide_values)}  [{how}]")
            if mem is not None:
                mem.add_all([mail_key(k, t)])   # 받기까지 다 한 메일만 - 실패한 메일은 다음 실행에서 다시
                mem.save()
        self.results.append((i, "ok", f"메일 {len(todo)}통"))
        self.results += [(j + 1, "ok", f"메일 {len(todo)}통") for j in body]
        self.log(f"  {i:2d}/{len(steps)} {describe(s, self.hide_values)}  [메일 {len(todo)}통]")
        return end + 1

    def _run_steps(self, steps):
        i = 0
        while i < len(steps):
            i += 1
            s = steps[i - 1]
            text = describe(s, self.hide_values)
            try:
                self._hold(i)
                if self.progress:
                    self.progress(i, "run", "")
                if s.get("otpSend") and self.otp is not None:
                    self.otp_send = i
                    self._otp_open()
                if s.get("pick"):
                    i = self._run_pick(i, steps)    # 메일마다 묶음 단계까지 - 결과도 거기서 적는다
                    continue
                how = self._step(i - 1, s)
                if s["kind"] == "otp":
                    self.otp_check = i + 1          # 다음 누르기([확인]) 뒤에 사이트가 받았나 본다
                elif self.otp_check == i:
                    self.otp_check = None
                    otp_i = next(j for j in range(i - 1, 0, -1) if steps[j - 1]["kind"] == "otp")
                    if self._otp_rejected(self.pages.get(s["page"]), steps[otp_i - 1], s):
                        raise OtpRetry("사이트에서 인증번호가 승인되지 않았습니다.", rejected=True)
                    self._otp_close()               # 통과 - 요청·번호를 지운다
                self.results.append((i, "ok", how))
                self.log(f"  {i:2d}/{len(steps)} {text}  [{how}]")
            except OtpRetry as e:
                self.results.append((i, "ok" if e.rejected else "fail", str(e)))
                if self.otp_try < OTP_TRIES:
                    back = self.otp_send or next(j for j in range(i, 0, -1) if steps[j - 1]["kind"] == "otp")
                    self.log(f"  {i:2d}/{len(steps)} {text}  - {e}. {back}단계부터 다시 ({self.otp_try + 1}/{OTP_TRIES})")
                    del self.results[back - 1:]
                    self.otp_check = None
                    self._otp_close()               # 다시 열 때 새 요청 (받기 단추가 없는 기록이면 인증번호 칸에서 연다)
                    i = back - 1
                    continue
                why = (f"사이트에서 인증번호가 {OTP_TRIES}번 거절되었습니다." if e.rejected
                       else f"인증번호를 {OTP_TRIES}번 수신하지 못했습니다. ({e})")
                self.results[-1] = (i, "fail", why)
                self.log(f"  {i:2d}/{len(steps)} {text}  - 실패: {why}")
                if self.progress:
                    self.progress(*self.results[-1])
                break
            except Cancelled:
                self.results.append((i, "fail", STOPPED))
                self.log(f"  {i:2d}/{len(steps)} {text}  - {STOPPED}")
                if self.progress:
                    self.progress(*self.results[-1])
                break
            except Skip as e:
                self.results.append((i, "skip", str(e)))
                self.log(f"  {i:2d}/{len(steps)} {text}  - 건너뜀 ({e})")
            except Exception as e:
                why = f"{type(e).__name__}: {str(e).splitlines()[0]}"
                if self.hide_values:
                    why = URL_QUERY.sub(r"\1", why)       # Playwright 오류에 주소가 통째로 들어온다 (2026-10-01 검토)
                if "has been closed" in why:
                    why = "창이 닫혀 중단되었습니다. 미리보기 중에는 창을 클릭하거나 닫지 마십시오."
                self.results.append((i, "fail", why))
                self.log(f"  {i:2d}/{len(steps)} {text}  - 실패: {why}")
                if self.progress:
                    self.progress(*self.results[-1])
                try:
                    os.makedirs(self.shot_dir, exist_ok=True)
                    shot = os.path.join(self.shot_dir, f"실패_{i}단계.png")
                    self.pages.get(s["page"], self.pages[0]).screenshot(path=shot)
                    self.log(f"      화면 사진: {shot}")
                except Exception:
                    pass
                break
            if self.progress:
                self.progress(*self.results[-1])


def replay(rec, creds, out_dir, code, today=None, review=False, headless=True, log=print, step_timeout=STEP_WAIT,
           step_tries=STEP_TRIES):
    with sync_playwright() as p:
        browser = edge(p.chromium.launch, headless=headless, slow_mo=250 if review else 0)
        context = browser.new_context(accept_downloads=True)
        r = Replayer(context, rec, creds, out_dir, code, today=today, review=review, log=log, step_timeout=step_timeout,
                     step_tries=step_tries)
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
