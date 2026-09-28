# -*- coding: utf-8 -*-
r"""사용자 설정(RPA_UserConfig.json)의 Sites 를 읽어 사이트별 웹 작업을 실행한다.

ERPia 루틴(run_routine.py), 문자 감시(sms_watch.py) 와 별개로 도는 독립 프로그램이다.

브라우저는 Playwright 가 들고 있는 전용 Chromium 을 쓴다.
그래서 사용자 PC 에 어떤 브라우저가 깔려 있는지, 기본 브라우저가 무엇인지
전혀 신경 쓸 필요가 없다.

사용법
    python web_runner.py --check            설정 파일 점검 (비밀번호는 가림)
    python web_runner.py --selftest         내장 테스트 폼으로 동작 확인 (사이트 불필요)
    python web_runner.py --site SITE1       한 사이트만 실행
    python web_runner.py --all              Stts=0 인 사이트를 모두 실행
    python web_runner.py --site SITE1 --headless   창을 띄우지 않고 실행

새 작업을 추가하려면
    아래 ACTIONS 에 이름과 함수를 등록하고, 설정 파일의 Action 에 그 이름을 적는다.
"""
import argparse
import datetime
import json
import os
import sys
import time

import rpa_status as status


def _setup_playwright_browsers():
    """exe 로 묶였을 때 브라우저가 어디 있는지 알려준다.

    Chromium 은 압축을 풀면 700MB 가 넘어 exe 안에 넣을 수 없다.
    exe 옆에 ms-playwright 폴더를 두고 그걸 쓰게 한다.
    (개발 중에는 %LOCALAPPDATA%\\ms-playwright 를 그대로 쓴다)
    playwright 를 import 하기 전에 정해 두어야 한다.
    """
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return
    here = (os.path.dirname(os.path.abspath(sys.executable))
            if getattr(sys, "frozen", False)
            else os.path.dirname(os.path.abspath(__file__)))

    # 1) exe(또는 스크립트) 옆에 ms-playwright 폴더가 있으면 그걸 쓴다 (배포용)
    candidate = os.path.join(here, "ms-playwright")
    if os.path.isdir(candidate):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = candidate
        return

    # 2) exe 로 묶이면 playwright 가 임시 압축해제 폴더 안의 .local-browsers 를
    #    브라우저 위치로 착각해서 "Executable doesn't exist" 로 죽는다.
    #    이 PC 에 이미 받아둔 기본 위치를 직접 알려준다.
    if getattr(sys, "frozen", False):
        default = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright")
        if os.path.isdir(default):
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = default


_setup_playwright_browsers()

from playwright.sync_api import TimeoutError as PWTimeout   # noqa: E402
from playwright.sync_api import sync_playwright             # noqa: E402

# 문자 인증번호는 sms_watch 가 'PC와 연결'(Phone Link) 에서 읽어온다.
# 같은 로직을 두 벌 두지 않으려고 그대로 가져다 쓴다.
# 이 모듈은 import 만으로는 아무 일도 하지 않는다.
try:
    import sms_watch
    _SMS_IMPORT_ERROR = None
except Exception as e:                              # pragma: no cover
    sms_watch = None
    _SMS_IMPORT_ERROR = e

# 바탕화면 경로는 ERPia 루틴과 같은 방식으로 찾는다.
# 회사 PC는 OneDrive 로 바탕화면이 옮겨져 있는 경우가 있어 '~/Desktop' 으로 단정하면 안 된다.
import perform_login as pl

# ---------------------------------------------------------------------------
# 설정값
# ---------------------------------------------------------------------------
REQUIRED_KEYS = ("URL", "ID", "PW", "Action", "Stts")

# Stts(Status): 사이트별 실행 여부.
#   "0" 이면 실행하고, "9" 면 어떤 작업도 하지 않는다(정보만 보관).
# 9 는 --site 로 콕 집어 지정해도 실행하지 않는다. '실행 안 함'이 절대 조건이다.
STTS_RUN = "0"
STTS_SKIP = "9"
STTS_VALUES = (STTS_RUN, STTS_SKIP)

# 로그인 칸을 못 찾았을 때 기다리는 시간
FIELD_TIMEOUT_MS = 15000
PAGE_TIMEOUT_MS = 30000

# '로그인' 버튼으로 볼 만한 글자들
SUBMIT_TEXTS = ("로그인", "login", "log in", "sign in", "signin", "확인", "접속")

# --- 문자 2차인증 ---
# 인증번호 입력칸
CERT_INPUT_SELECTORS = (
    "input[name='certKey']",
    "#inputCertKey",
    "input[placeholder*='인증번호']",
    "input[id*='cert' i]",
)
# '문자로 인증번호 받기' 버튼
SEND_SMS_TEXTS = ("핸드폰으로 인증번호 받기", "휴대폰으로 인증번호 받기",
                  "휴대폰 인증번호 받기", "인증번호 받기", "인증번호 발송", "인증번호 전송")
# 인증번호를 넣고 누르는 버튼
VERIFY_TEXTS = ("인증번호 확인", "인증확인", "확인")
# 발송 후 뜨는 안내 토스트를 닫는 버튼
TOAST_OK_TEXTS = ("확인", "닫기", "OK")

# 문자가 올 때까지 기다리는 시간. 이 사이트의 인증번호 유효시간이 2분이라
# 그보다 넉넉하게 잡을 이유가 없다.
SMS_WAIT_SECONDS = 90
SMS_POLL_SECONDS = 2.0


def app_base_dir():
    """PyInstaller 로 묶이면 __file__ 이 임시폴더를 가리키므로 exe 위치를 쓴다."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = app_base_dir()

# 로그인 후 쿠키를 저장해 두는 곳.
# 기본값은 '쓰지 않음' 이다. 매번 새로 로그인하고 2차인증을 거치는 편이 한결같고,
# 로그인한 것과 같은 효력을 갖는 파일을 디스크에 남기지도 않는다.
# 설정에 "UseSession": true 를 넣거나 --session 을 주면 재사용한다(주로 점검용).
SESSION_DIR = os.path.join(BASE_DIR, "sessions")


RESULT_PATH = os.path.join(BASE_DIR, "prepare_result.txt")
_log_started = False


def log(msg):
    """화면에 찍고, 그때그때 파일에도 덧붙인다.

    예전에는 print 만 했다. 다른 PC 에서 돌린 뒤에는 창이 닫히면 아무것도
    남지 않아 무슨 일이 있었는지 확인할 수가 없었다.
    """
    global _log_started
    line = f"[{datetime.datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    status.log_line(line)
    try:
        mode = "a" if _log_started else "w"
        with open(RESULT_PATH, mode, encoding="utf-8") as f:
            f.write(line + "\n")
        _log_started = True
    except Exception:
        pass


def eval_json(page, js_fn):
    """페이지에서 자바스크립트를 돌려 결과를 JSON 으로 받아온다.

    page.evaluate 로 배열이나 객체를 그대로 돌려받으면 **어떤 페이지에서는 None** 이 된다.
    (bizmeka 메일함에서 실제로 그랬다. 숫자와 문자열은 멀쩡한데 구조체만 조용히 깨지고
     예외도 나지 않아서 원인을 찾기 어렵다.)
    JSON 문자열로 감싸 넘기면 페이지와 무관하게 안전하다.

    js_fn 은 '() => ...' 꼴의 함수식이어야 한다.
    """
    raw = page.evaluate(f"() => JSON.stringify(({js_fn})())")
    if raw is None:
        return None
    return json.loads(raw)


def session_path(name):
    return os.path.join(SESSION_DIR, f"{name}.json")


def strip_fragment(url):
    """주소에서 '#...' 을 떼어낸다.

    링크가 href='#' 이면 눌렀을 때 주소 끝에 '#' 만 붙는다.
    그걸 '주소가 바뀌었다'로 착각하면 실패를 성공으로 읽는다.
    """
    return (url or "").split("#", 1)[0]


def save_shot(page, name, tag):
    """결과가 애매할 때 화면을 남겨 둔다. 나중에 눈으로 확인하기 위한 것."""
    path = os.path.join(BASE_DIR, f"web_{name}_{tag}.png")
    try:
        page.screenshot(path=path, full_page=True)
        log(f"  [{name}] 화면을 저장했습니다: {path}")
    except Exception as e:
        log(f"  [{name}] 화면 저장 실패: {e}")


def mask_pw(pw):
    """비밀번호는 화면에도 로그에도 절대 그대로 찍지 않는다."""
    if not pw:
        return "(없음)"
    return f"({len(pw)}자)"


# ---------------------------------------------------------------------------
# 설정 읽기
# ---------------------------------------------------------------------------
def load_config(path=None):
    """사이트 설정 {이름: 사이트}. 사용자 설정의 Sites (파일이 아직 없으면 옛 WebManageConfig.json).
    잠긴 비밀번호는 여기서 푼다 - 이 뒤로는 예전처럼 평문을 다룬다 (로그에는 mask_pw 로만)."""
    try:
        sites = status.read_user_config(path).get(status.SITES_SECTION)
    except ValueError as e:
        raise RuntimeError(str(e)) from None
    if not isinstance(sites, dict):
        raise RuntimeError(f"사이트 설정이 없습니다: {path or status.user_config_path()} 의 '{status.SITES_SECTION}'")
    out = {}
    for name, site in sites.items():
        if name.startswith("_"):      # '_' 로 시작하는 키는 주석이므로 걷어낸다
            continue
        if isinstance(site, dict) and site.get("PW"):
            site = dict(site, PW=status.unseal(site["PW"]))
        out[name] = site
    return out


def site_actions(site):
    """Action 을 항상 리스트로 돌려준다 (문자열 하나여도 됨)."""
    a = site.get("Action")
    if a is None:
        return []
    if isinstance(a, str):
        return [a]
    if isinstance(a, list):
        return [str(x) for x in a]
    return []


def site_stts(site):
    """Stts 를 문자열로 정규화해 돌려준다. 숫자 0 으로 써도 "0" 으로 본다."""
    v = site.get("Stts")
    if v is None:
        return None
    return str(v).strip()


def site_will_run(site):
    """이 사이트의 작업을 실행해도 되는가."""
    return site_stts(site) == STTS_RUN


def validate_site(name, site):
    """설정 한 건을 검사해 문제 목록을 돌려준다."""
    problems = []
    if not isinstance(site, dict):
        return [f"{name}: 객체가 아닙니다."]

    for key in REQUIRED_KEYS:
        if key not in site:
            problems.append(f"{name}: '{key}' 항목이 없습니다.")
        elif site[key] is None or site[key] == "":
            # Stts 는 0 이 정상값이라 not 으로 판정하면 안 된다
            problems.append(f"{name}: '{key}' 가 비어 있습니다.")

    stts = site_stts(site)
    if stts is not None and stts not in STTS_VALUES:
        problems.append(f"{name}: Stts 는 {STTS_RUN} 또는 {STTS_SKIP} 이어야 합니다 "
                        f"(지금 값: {site.get('Stts')!r})")

    url = site.get("URL") or ""
    if url and not url.startswith(("http://", "https://")):
        problems.append(f"{name}: URL 이 http:// 또는 https:// 로 시작하지 않습니다.")

    acts = site_actions(site)
    if not acts:
        problems.append(f"{name}: Action 이 비어 있습니다.")
    for a in acts:
        if a not in ACTIONS:
            problems.append(f"{name}: 모르는 Action '{a}' "
                            f"(쓸 수 있는 값: {', '.join(sorted(ACTIONS))})")

    for placeholder in ("여기에_아이디", "여기에_비밀번호"):
        if site.get("ID") == placeholder or site.get("PW") == placeholder:
            problems.append(f"{name}: 예시 값이 그대로 남아 있습니다 ('{placeholder}').")

    return problems


# ---------------------------------------------------------------------------
# 로그인 폼 찾기
# ---------------------------------------------------------------------------
# 비밀번호 칸 바로 앞에 있는 '보이는 텍스트 입력칸'을 아이디 칸으로 본다.
# 사이트마다 name/id 가 제각각이라 이름으로 찾는 것보다 이 편이 잘 맞는다.
FIND_ID_FIELD_JS = """
() => {
  const pw = [...document.querySelectorAll('input[type=password]')]
             .find(e => e.offsetParent !== null);
  if (!pw) return -1;
  const all = [...document.querySelectorAll('input')];
  const i = all.indexOf(pw);
  for (let j = i - 1; j >= 0; j--) {
    const t = (all[j].getAttribute('type') || 'text').toLowerCase();
    if (['text', 'email', 'tel'].includes(t) && all[j].offsetParent !== null) return j;
  }
  return -1;
}
"""


def has_password_field(page, timeout=3000):
    """비밀번호 칸이 보이는가. 로그인 화면인지 판정하는 데 쓴다."""
    try:
        page.locator("input[type='password']:visible").first.wait_for(
            state="visible", timeout=timeout)
        return True
    except Exception:
        return False


def find_password_field(page, selectors):
    sel = (selectors or {}).get("pw")
    if sel:
        loc = page.locator(sel).first
        loc.wait_for(state="visible", timeout=FIELD_TIMEOUT_MS)
        return loc
    # ':visible' 을 반드시 붙인다. 화면 위쪽에 숨겨진 더미 로그인폼을 두는 사이트가
    # 흔한데, 그냥 first 를 쓰면 안 보이는 칸을 집어서 영영 기다리게 된다.
    loc = page.locator("input[type='password']:visible").first
    loc.wait_for(state="visible", timeout=FIELD_TIMEOUT_MS)
    return loc


def find_id_field(page, selectors):
    sel = (selectors or {}).get("id")
    if sel:
        loc = page.locator(sel).first
        loc.wait_for(state="visible", timeout=FIELD_TIMEOUT_MS)
        return loc

    idx = page.evaluate(FIND_ID_FIELD_JS)
    if idx is None or idx < 0:
        raise RuntimeError(
            "아이디 입력칸을 찾지 못했습니다. "
            "설정에 selectors.id 로 직접 지정해 주세요.")
    return page.locator("input").nth(idx)


def find_clickable_by_texts(page, texts):
    """글자로 누를 것을 찾아 (locator, 설명) 을 돌려준다. 못 찾으면 (None, 사유).

    '정확히 일치'를 먼저 본다. 부분 일치부터 하면 엉뚱한 것을 집는다.
    bizmeka 에서 '로그인' 을 부분 일치로 찾다가 '로그인 정책' 을 눌러
    안내 팝업이 뜬 적이 있다.
    """
    for exact in (True, False):
        for text in texts:
            for role in ("button", "link"):
                loc = page.get_by_role(role, name=text, exact=exact).first
                try:
                    if loc.count() and loc.is_visible():
                        return loc, f"{role} '{text}' (정확히일치={exact})"
                except Exception:
                    pass
            # <input type=button value="..."> 형태
            loc = page.locator(
                f"input[type='button'][value='{text}']:visible").first
            try:
                if loc.count():
                    return loc, f"input[value='{text}']"
            except Exception:
                pass
    return None, "찾지 못함"


def find_submit(page, selectors):
    """로그인 버튼을 찾아 (locator, 설명) 으로 돌려준다. 못 찾으면 (None, 사유).

    누르지 않고 찾기만 하므로, 실제로 누르기 전에 무엇이 잡히는지 확인할 수 있다.
    """
    sel = (selectors or {}).get("submit")
    if sel:
        return page.locator(sel).first, f"설정 셀렉터 {sel!r}"

    for candidate in ("input[type='submit']:visible", "button[type='submit']:visible"):
        loc = page.locator(candidate).first
        try:
            if loc.count():
                return loc, candidate
        except Exception:
            pass

    return find_clickable_by_texts(page, SUBMIT_TEXTS)


def click_submit(page, selectors, pw_field):
    """로그인 버튼을 누른다. 못 찾으면 비밀번호 칸에서 Enter 를 친다."""
    loc, how = find_submit(page, selectors)
    if loc is None:
        pw_field.press("Enter")
        return "Enter 키 (버튼을 못 찾음)"
    loc.click()
    return how


# ---------------------------------------------------------------------------
# 화면을 가리는 팝업/레이어 닫기
# ---------------------------------------------------------------------------
# 공지 레이어나 안내 팝업이 떠 있으면 그 아래 버튼이 눌리지 않는다.
# 닫기 버튼으로 볼 만한 것들을 좁게 잡는다. 너무 넓게 잡으면 엉뚱한 것을 누른다.
CLOSE_SELECTORS = (
    "[aria-label='닫기']",
    "[aria-label='Close']",
    "[aria-label='close']",
    "[title='닫기']",
    "button.close",
    "a.close",
    "button[class*='close']",
    "a[class*='close']",
    "span[class*='close']",
    "img[class*='close']",
    "[class*='layer'] [class*='close']",
    "[class*='modal'] [class*='close']",
    "[class*='popup'] [class*='close']",
)


def dismiss_overlays(page, rounds=3):
    """화면을 가리는 팝업을 닫는다. 닫은 방법들의 목록을 돌려준다.

    Esc 를 먼저 눌러본다. 그것만으로 닫히는 레이어가 많고, 무엇보다 안전하다.
    그래도 남아 있으면 닫기(X) 버튼을 찾아 누른다.
    """
    closed = []
    for _ in range(rounds):
        acted = False
        for sel in CLOSE_SELECTORS:
            loc = page.locator(f"{sel}:visible").first
            try:
                if loc.count() == 0:
                    continue
                loc.click(timeout=2000)
                closed.append(sel)
                acted = True
                page.wait_for_timeout(400)
                break
            except Exception:
                continue
        if not acted:
            break
    return closed


# ---------------------------------------------------------------------------
# Action: 실제로 하는 일
# ---------------------------------------------------------------------------
def action_login(page, name, site):
    """사이트에 로그인한다."""
    url = site["URL"]
    log(f"  [{name}] 이동: {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)

    # 공지/안내 레이어가 떠 있으면 그 아래 버튼이 눌리지 않는다.
    closed = dismiss_overlays(page)
    if closed:
        log(f"  [{name}] 가리고 있던 팝업 {len(closed)}개를 닫았습니다: {closed}")

    # 저장해 둔 쿠키로 이미 로그인되어 있으면 비밀번호 칸이 아예 없다.
    if not has_password_field(page):
        log(f"  [{name}] 이미 로그인되어 있습니다. 로그인을 건너뜁니다. ({page.url})")
        return True

    selectors = site.get("selectors") or {}

    pw_field = find_password_field(page, selectors)
    id_field = find_id_field(page, selectors)

    id_field.fill(site["ID"])
    log(f"  [{name}] 아이디 입력 완료")
    pw_field.fill(site["PW"])
    log(f"  [{name}] 비밀번호 입력 완료 {mask_pw(site['PW'])}")

    before = page.url
    how = click_submit(page, selectors, pw_field)
    log(f"  [{name}] 로그인 눌렀습니다 ({how})")

    # 주소가 바뀌거나 페이지가 조용해질 때까지 기다린다.
    # 주소가 그대로여도 실패라고 단정할 수는 없다(같은 주소에서 화면만 바뀌는 사이트도 있다).
    try:
        page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT_MS)
    except PWTimeout:
        log(f"  [{name}] 페이지가 계속 통신 중입니다. 그대로 진행합니다.")

    log(f"  [{name}] 이동 후 주소: {page.url}")
    if page.url == before:
        log(f"  [{name}] 주소가 그대로입니다. 로그인 결과를 확인해 주세요.")
    return True


# ---------------------------------------------------------------------------
# Action: 문자 2차인증
# ---------------------------------------------------------------------------
def find_cert_input(page):
    """인증번호 입력칸을 찾는다."""
    for sel in CERT_INPUT_SELECTORS:
        loc = page.locator(f"{sel}:visible").first
        try:
            if loc.count():
                return loc, sel
        except Exception:
            continue
    return None, "찾지 못함"


def dismiss_toast(page, name):
    """문자 발송 후 뜨는 안내 토스트를 닫는다.

    자바스크립트 alert() 는 prepare_page() 에서 자동으로 받아넘기므로
    여기서는 화면 안에 그려진 토스트만 상대한다.

    반드시 '정확히 일치'만 본다. 부분 일치를 허용하면 '확인' 으로 찾다가
    '인증번호 확인' 을 눌러버린다(실제로 그렇게 오작동했다).
    닫을 것이 없으면 아무것도 하지 않는 것이 옳다.
    """
    page.wait_for_timeout(800)
    for text in TOAST_OK_TEXTS:
        for role in ("button", "link"):
            loc = page.get_by_role(role, name=text, exact=True).first
            try:
                if loc.count() and loc.is_visible():
                    loc.click(timeout=3000)
                    log(f"  [{name}] 안내 토스트를 닫았습니다 ({role} '{text}')")
                    page.wait_for_timeout(500)
                    return text
            except Exception:
                continue
    return None


def mask_digits(text, keep=50):
    """로그에 남길 본문. 숫자는 가린다(인증번호가 평문으로 쌓이면 곤란하다)."""
    s = " ".join((text or "").split())
    s = "".join("*" if c.isdigit() else c for c in s)
    return s[:keep] + ("..." if len(s) > keep else "")


def wait_for_sms_code(reader, before, name, timeout=SMS_WAIT_SECONDS):
    """문자로 새 인증번호가 올 때까지 기다린다. 못 받으면 None.

    before 는 발송 버튼을 누르기 '직전'의 문자 목록이다.
    이걸 기준으로 잡아야 예전에 받아둔 인증번호를 잘못 집지 않는다.
    """
    deadline = time.time() + timeout
    seen = set(before)

    # 이미 받아둔 인증번호는 새 것으로 치지 않는다.
    # 문자를 읽음/안읽음 표시가 바뀌는 것만으로 목록 글자가 달라질 수 있어서,
    # 이 가드가 없으면 지난 인증번호를 새로 온 것으로 착각할 수 있다.
    known_codes = {sms_watch.extract_auth_code(b) for _, b in before}
    known_codes.discard(None)

    started = time.time()
    checked_conn = 0.0
    beat = 0.0
    last = None
    while time.time() < deadline:
        time.sleep(SMS_POLL_SECONDS)
        status.metric(f"{name}:sms_wait", "문자 대기", int(time.time() - started),
                      int(timeout), unit="초")

        # 15초마다 '지금 몇 건이 보이는지'를 남긴다. 못 받고 끝났을 때
        # 목록 자체가 굳어 있었는지, 문자가 안 온 것인지 구분하기 위해서다.
        if time.time() - beat > 15:
            beat = time.time()
            n = len(last) if last is not None else 0
            log(f"  [{name}] 대기 {int(time.time() - started)}초 (대화 {n}건, 새 문자 없음)")

        # 연결이 끊기면 아무리 기다려도 문자는 들어오지 않는다. 빨리 알려주는 편이 낫다.
        if time.time() - checked_conn > 10:
            checked_conn = time.time()
            problem = reader.connection_problem()
            if problem:
                raise RuntimeError(f"휴대폰 연결에 문제가 있습니다: {problem} "
                                   "(연결이 끊긴 동안 온 문자는 PC로 들어오지 않습니다)")

        convs = reader.read_conversations()
        if convs is None:
            log(f"  [{name}] 문자 목록을 읽지 못했습니다. 다시 붙습니다.")
            reader.attach(launch=False)
            continue
        last = convs
        for item in convs:
            if item in seen:
                continue
            seen.add(item)
            sender, body = item
            if sms_watch.KEYWORD not in body:
                log(f"  [{name}] 새 문자가 왔지만 인증번호가 아닙니다 (발신 {sender})")
                continue
            code = sms_watch.extract_auth_code(body)
            if code is None:
                log(f"  [{name}] 인증번호 문자인데 번호를 못 읽었습니다 (발신 {sender})")
                continue
            if code in known_codes:
                log(f"  [{name}] 전에 받아둔 인증번호와 같습니다. 새 문자를 더 기다립니다.")
                continue
            log(f"  [{name}] 인증번호 문자 도착 (발신 {sender})")
            # 다 받았으니 진행 막대로 보이지 않게 총량을 지우고 걸린 시간만 남긴다.
            status.metric(f"{name}:sms_wait", "문자 대기", int(time.time() - started),
                          unit="초", note="인증번호를 받았습니다")
            status.note("인증번호 문자를 받았습니다")
            return code

    # 못 받았다. 그 시점에 무엇이 보이고 있었는지 남긴다.
    # (숫자는 가린다. 인증번호가 로그에 평문으로 쌓이면 곤란하다)
    log(f"  [{name}] 문자를 받지 못했습니다. 마지막으로 보이던 대화 목록:")
    for sender, body in (last or [])[:6]:
        log(f"      - {sender}: {mask_digits(body)}")
    if not last:
        log("      (한 건도 읽히지 않았습니다. Phone Link 의 '메시지' 탭을 확인해 주세요)")
    return None


def action_sms_2fa(page, name, site):
    """문자로 인증번호를 받아 2차인증을 통과한다."""
    if sms_watch is None:
        raise RuntimeError(f"sms_watch 를 불러오지 못했습니다: {_SMS_IMPORT_ERROR}")

    cert, cert_how = find_cert_input(page)
    if cert is None:
        # 저장된 쿠키로 이미 통과했거나, 애초에 2차인증을 요구하지 않은 경우다.
        log(f"  [{name}] 2차인증 화면이 아닙니다. 건너뜁니다. ({page.url})")
        return True
    log(f"  [{name}] 인증번호 입력칸 확인 ({cert_how})")

    # 문자를 읽어올 준비를 '발송 전에' 끝내둔다.
    reader = sms_watch.PhoneLinkReader()
    if not reader.attach():
        raise RuntimeError("Phone Link 창을 확보하지 못했습니다.")
    problem = reader.connection_problem()
    if problem:
        raise RuntimeError(f"휴대폰 연결에 문제가 있습니다: {problem} "
                           "문자를 받을 수 없으니 연결부터 고쳐 주세요.")

    before = reader.read_conversations()
    if before is None:
        raise RuntimeError("문자 목록을 읽지 못했습니다.")
    before = set(before)
    log(f"  [{name}] 현재 문자 {len(before)}건을 기준으로 잡았습니다.")

    send_btn, how = find_clickable_by_texts(page, SEND_SMS_TEXTS)
    if send_btn is None:
        raise RuntimeError("'인증번호 받기' 버튼을 찾지 못했습니다.")
    send_btn.click()
    log(f"  [{name}] 문자 발송 요청 ({how})")

    dismiss_toast(page, name)

    log(f"  [{name}] 문자를 기다립니다 (최대 {SMS_WAIT_SECONDS}초)")
    code = wait_for_sms_code(reader, before, name)
    if code is None:
        raise RuntimeError(f"{SMS_WAIT_SECONDS}초 안에 인증번호 문자가 오지 않았습니다.")

    # 자동 입력이 실패해도 사람이 바로 붙여넣을 수 있도록 클립보드에도 넣는다.
    sms_watch.set_clipboard_text(code)

    cert.fill(code)
    log(f"  [{name}] 인증번호 입력 완료 ({len(code)}자리)")

    verify_btn, vhow = find_clickable_by_texts(page, VERIFY_TEXTS)
    if verify_btn is None:
        raise RuntimeError("'인증번호 확인' 버튼을 찾지 못했습니다.")
    before_url = page.url
    verify_btn.click()
    log(f"  [{name}] 인증번호 확인 눌렀습니다 ({vhow})")

    try:
        page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT_MS)
    except PWTimeout:
        pass

    # 이 사이트는 '인증번호 확인' 이 번호만 검사하고("인증번호가 일치합니다. 로그인 해주세요."),
    # 실제 로그인은 그 아래 '로그인' 버튼을 눌러야 끝난다.
    page.wait_for_timeout(1000)
    if strip_fragment(page.url) == strip_fragment(before_url):
        final, fhow = find_clickable_by_texts(page, ("로그인",))
        if final is not None:
            final.click()
            log(f"  [{name}] 마지막 '로그인' 을 눌렀습니다 ({fhow})")
            try:
                page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT_MS)
            except PWTimeout:
                pass
            page.wait_for_timeout(1500)

    # 주소만 보면 '#' 이 붙는 것만으로도 바뀐 것처럼 보인다.
    # 인증번호 입력칸이 사라졌는지로 판정하는 편이 사이트를 안 가리고 정확하다.
    log(f"  [{name}] 인증 후 주소: {page.url}")
    still, _ = find_cert_input(page)
    if still is not None:
        save_shot(page, name, "2fa")
        raise RuntimeError("아직 2차인증 화면에 머물러 있습니다. "
                           "저장된 화면을 확인해 주세요.")
    log(f"  [{name}] 2차인증을 통과했습니다.")
    return True


# ---------------------------------------------------------------------------
# Action: 메일함 - 안읽은 메일에서 키워드 찾기
# ---------------------------------------------------------------------------
# 메일 한 건은 li.m_data 이고, 읽은 것에는 클래스에 'read' 가 붙는다.
# 제목은 p.m_subject 안의 '맨 텍스트 노드'다. 같은 칸에 아이콘과 '전달'/'답장'
# 표시(span.blind)가 섞여 있어서, innerText 를 쓰면 그것들까지 딸려온다.
MAIL_ROWS_JS = """
() => [...document.querySelectorAll('li.m_data')].map(li => {
  const p = li.querySelector('.m_subject');
  const subject = p
    ? [...p.childNodes].filter(n => n.nodeType === 3)
        .map(n => n.textContent).join('').replace(/\\u00a0/g, ' ')
        .replace(/\\s+/g, ' ').trim()
    : '';
  const sender = li.querySelector('.m_write');
  const date = li.querySelector('.m_date');
  const cls = (li.className || '').toString();
  return {
    key: li.getAttribute('data-key') || '',
    subject: subject,
    sender: sender ? (sender.innerText || '').trim() : '',
    date: date ? (date.innerText || '').trim() : '',
    unread: /(^|\\s)unread(\\s|$)/.test(cls),
    read: /(^|\\s)read(\\s|$)/.test(cls)
  };
})
"""

# 행 하나의 제목만 다시 읽는다. 열기 직전에 대상이 맞는지 확인하는 데 쓴다.
MAIL_SUBJECT_BY_KEY_JS = """
(key) => {
  const li = document.querySelector('li.m_data[data-key="' + key + '"]');
  if (!li) return null;
  const p = li.querySelector('.m_subject');
  if (!p) return '';
  return [...p.childNodes].filter(n => n.nodeType === 3)
      .map(n => n.textContent).join('').replace(/\\u00a0/g, ' ')
      .replace(/\\s+/g, ' ').trim();
}
"""

# 화면 위쪽의 '안읽은 메일 N 통 / 전체메일 M 통'
MAIL_COUNT_JS = """
() => {
  const m = (document.body.innerText || '').match(/안읽은 메일\\s*([0-9,]+)\\s*통/);
  return {unread: m ? parseInt(m[1].replace(/,/g, ''), 10) : null};
}
"""

MAIL_KEYWORD = ">>>"
MAIL_MAX_PAGES = 20
# 목록이 그려질 때까지 기다리는 시간. locator.count() 는 기다려주지 않는다.
MAIL_ROW_WAIT_MS = 5000

# 첨부파일 내려받기.
# 파일 이름 링크와 '다운로드' 버튼 둘 다 onclick 에 attachDownload 를 갖는다.
# 바로 옆에 '삭제'(attachDelete)와 '모두삭제'(doAllDel)가 있으므로
# 절대 글자로 찾지 말고 이 onclick 으로만 집는다.
ATTACH_LINK_SELECTOR = "a[onclick*='attachDownload']"
DOWNLOAD_DIR_NAME = "ERPIA_AI_EXCEL"
DOWNLOAD_TIMEOUT_MS = 60000


def download_dir():
    r"""첨부파일을 받아둘 곳. ERPia 루틴의 엑셀업로드가 읽어가는 바로 그 폴더다.

    바탕화면\ERPIA_AI\ERPIA_AI_EXCEL 이다. 루틴과 같은 함수(pl.find_ai_dir)를 써서
    두 프로그램이 같은 폴더를 보도록 맞춘다.
    """
    return os.path.join(pl.find_ai_dir(), DOWNLOAD_DIR_NAME)


def unique_path(path):
    """같은 이름이 있으면 뒤에 (1), (2) 를 붙인다. 기존 파일을 덮지 않는다."""
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    for i in range(1, 1000):
        cand = f"{stem} ({i}){ext}"
        if not os.path.exists(cand):
            return cand
    return path


def goto_mailbox(page, name, site):
    """메일함으로 들어간다."""
    url = site.get("MailURL")
    if url:
        page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
    else:
        loc, how = find_clickable_by_texts(page, ("메일", "Mail"))
        if loc is None:
            raise RuntimeError("'메일' 링크를 찾지 못했습니다. "
                               "설정에 MailURL 을 넣어 주세요.")
        loc.click()
        log(f"  [{name}] 메일함으로 이동 ({how})")

    try:
        page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT_MS)
    except PWTimeout:
        pass
    dismiss_overlays(page)

    if page.locator("li.m_data").count() == 0 and eval_json(page, MAIL_COUNT_JS).get("unread") is None:
        raise RuntimeError(f"메일함 화면을 인식하지 못했습니다. (현재 주소: {page.url})")
    log(f"  [{name}] 메일함 도착: {page.url}")


def collect_unread_mails(page, name):
    """안읽은 메일을 모아서 목록으로 돌려준다.

    '안읽음' 걸러보기를 눌러 안읽은 것만 남긴 뒤 훑는다.
    메일을 열지 않으므로 읽음 상태를 건드리지 않는다.
    """
    counted = eval_json(page, MAIL_COUNT_JS) or {}
    total_unread = counted.get("unread")
    if total_unread is not None:
        log(f"  [{name}] 안읽은 메일 {total_unread}통")
        if total_unread == 0:
            return []

    # '안읽음' 만 남기고 본다. 없으면 전체 목록에서 클래스로 걸러낸다.
    loc, how = find_clickable_by_texts(page, ("안읽음",))
    if loc is not None:
        loc.click()
        try:
            page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT_MS)
        except PWTimeout:
            pass
        page.wait_for_timeout(800)
        log(f"  [{name}] '안읽음' 으로 걸렀습니다 ({how})")

    found = []
    seen_keys = set()
    for page_no in range(1, MAIL_MAX_PAGES + 1):
        rows = eval_json(page, MAIL_ROWS_JS) or []
        new = 0
        for r in rows:
            # 'unread' 클래스가 있으면 안읽음. 없더라도 'read' 가 안 붙어 있으면 안읽음으로 본다.
            if not r.get("unread") and r.get("read"):
                continue
            key = r.get("key") or (r.get("subject", ""), r.get("date", ""))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            found.append(r)
            new += 1
        log(f"  [{name}] {page_no}쪽: 안읽은 메일 {new}건")

        if total_unread is not None and len(found) >= total_unread:
            break
        nxt, _ = find_clickable_by_texts(page, ("다음", "다음 페이지", "Next"))
        if nxt is None or new == 0:
            break
        nxt.click()
        try:
            page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT_MS)
        except PWTimeout:
            pass
        page.wait_for_timeout(800)

    return found


def action_mail_check(page, name, site):
    """메일함에 들어가 '안읽은 메일' 중 특정 키워드로 시작하는 것이 있는지 확인한다."""
    keyword = site.get("MailKeyword", MAIL_KEYWORD)
    goto_mailbox(page, name, site)

    unread = collect_unread_mails(page, name)
    hits = [m for m in unread if m.get("subject", "").startswith(keyword)]
    status.metric(f"{name}:mail_hits", "대상 메일", len(hits),
                  note=f"안읽은 메일 {len(unread)}건 중 '{keyword}' 제목")

    log(f"  [{name}] 안읽은 메일 {len(unread)}건 중 "
        f"'{keyword}' 로 시작하는 것 {len(hits)}건")
    for m in hits:
        log(f"      - {m['subject']}  (보낸사람 {m['sender']}, {m['date']})")

    # 다음 단계에서 쓸 수 있도록 결과를 남겨 둔다.
    site["_mail_hits"] = hits
    return True


def find_mail_row(page, name, key):
    """목록에서 data-key 로 행을 찾는다. 없으면 '안읽음' 을 걸고 다음 쪽으로 넘기며 찾는다.

    collect_unread_mails 는 '안읽음' 으로 거른 목록을 여러 쪽 훑는다.
    그런데 메일을 열려고 MailURL 로 돌아오면 걸러보기가 풀린 1쪽이라,
    2쪽 이후에 있던 메일은 그 자리에 없다. 읽은 '>>>' 메일이 쌓인 메일함이면
    1쪽에조차 없다 (2026-09-18 시연 PC 에서 두 건 모두 이렇게 못 찾았다).
    """
    sel = f'li.m_data[data-key="{key}"]'

    def settle():
        try:
            page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT_MS)
        except PWTimeout:
            pass
        page.wait_for_timeout(800)

    def here():
        # count() 는 기다려주지 않는다. 목록이 그려질 때까지 먼저 기다린다.
        try:
            page.wait_for_selector("li.m_data", timeout=MAIL_ROW_WAIT_MS)
        except PWTimeout:
            return False
        return page.locator(sel).count() > 0

    if here():
        return True

    loc, how = find_clickable_by_texts(page, ("안읽음",))
    if loc is not None:
        loc.click()
        settle()
        log(f"  [{name}] 1쪽에 없어 '안읽음' 으로 걸렀습니다 ({how})")
        if here():
            return True

    for page_no in range(2, MAIL_MAX_PAGES + 1):
        nxt, _ = find_clickable_by_texts(page, ("다음", "다음 페이지", "Next"))
        if nxt is None:
            break
        nxt.click()
        settle()
        if here():
            log(f"  [{name}] {page_no}쪽에서 찾았습니다.")
            return True
    return False


def open_mail_by_key(page, name, site, key, expect_subject, keyword):
    """data-key 로 메일을 정확히 지목해서 연다.

    제목 글자로 행을 찾으면 비슷한 제목의 다른 메일을 열 수 있다.
    메일을 여는 순간 '읽음'이 되므로, 대상이 아닌 메일은 절대 열면 안 된다.
    그래서 여기서는 두 가지를 지킨다.
      1) data-key 로 행을 하나만 집는다
      2) 누르기 직전에 그 행의 제목이 정말 keyword 로 시작하는지 다시 확인한다
    """
    url = site.get("MailURL")
    if url:
        page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
        try:
            page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT_MS)
        except PWTimeout:
            pass
    dismiss_overlays(page)

    if not find_mail_row(page, name, key):
        raise RuntimeError(f"목록에서 메일을 찾지 못했습니다: {expect_subject!r} (key={key})")
    row = page.locator(f'li.m_data[data-key="{key}"]')

    # 열기 직전 재확인. 목록이 바뀌어 다른 메일이 그 자리에 왔을 수도 있다.
    actual = page.evaluate(MAIL_SUBJECT_BY_KEY_JS, key)
    if actual is None:
        raise RuntimeError(f"메일이 사라졌습니다: {expect_subject!r}")
    if not actual.startswith(keyword):
        raise RuntimeError(
            f"열려던 메일의 제목이 '{keyword}' 로 시작하지 않습니다: {actual!r}. "
            "대상이 아니므로 열지 않습니다.")
    if actual != expect_subject:
        log(f"  [{name}] 제목이 조금 다릅니다 (찾던 것 {expect_subject!r} / 실제 {actual!r})")

    row.first.locator(".m_title").first.click()
    try:
        page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT_MS)
    except PWTimeout:
        pass
    page.wait_for_timeout(1200)


def download_attachments(page, name, dest):
    """열려 있는 메일의 첨부파일을 모두 내려받는다. 저장한 경로 목록을 돌려준다."""
    links = page.locator(ATTACH_LINK_SELECTOR)
    count = links.count()
    if count == 0:
        log(f"  [{name}] 첨부파일이 없습니다.")
        return []

    saved = []
    for i in range(count):
        link = links.nth(i)
        try:
            label = link.inner_text().strip()
        except Exception:
            label = f"첨부 {i + 1}"
        try:
            with page.expect_download(timeout=DOWNLOAD_TIMEOUT_MS) as info:
                link.click()
            dl = info.value
            target = unique_path(os.path.join(dest, dl.suggested_filename))
            dl.save_as(target)
            saved.append(target)
            log(f"  [{name}] 받음: {os.path.basename(target)}")
        except PWTimeout:
            log(f"  [{name}] 내려받기가 시간 안에 끝나지 않았습니다: {label}")
        except Exception as e:
            log(f"  [{name}] 내려받기 실패 ({label}): {type(e).__name__}: {e}")
    return saved


def action_mail_download(page, name, site):
    """'>>>' 로 시작하는 안읽은 메일의 첨부파일을 바탕화면 폴더에 내려받는다."""
    keyword = site.get("MailKeyword", MAIL_KEYWORD)
    hits = site.get("_mail_hits")
    if hits is None:
        # mail_check 를 거치지 않고 단독으로 실행된 경우
        goto_mailbox(page, name, site)
        unread = collect_unread_mails(page, name)
        hits = [m for m in unread if m.get("subject", "").startswith(keyword)]
        log(f"  [{name}] '{keyword}' 로 시작하는 안읽은 메일 {len(hits)}건")

    if not hits:
        log(f"  [{name}] 내려받을 메일이 없습니다.")
        status.metric(f"{name}:mail_open", "메일 처리", 0, 0, note="대상 없음")
        return True

    dest = download_dir()
    os.makedirs(dest, exist_ok=True)
    log(f"  [{name}] 저장 위치: {dest}")

    total = []
    status.metric(f"{name}:mail_open", "메일 처리", 0, len(hits))
    status.metric(f"{name}:files", "받은 첨부", 0, unit="개")
    for i, m in enumerate(hits, 1):
        subject = m.get("subject", "")
        # 여기까지 온 것은 전부 keyword 로 시작하지만, 여는 쪽에서 한 번 더 검사한다.
        if not subject.startswith(keyword):
            log(f"  [{name}] 대상이 아니라 건너뜁니다: {subject!r}")
            continue
        log(f"  [{name}] [{i}/{len(hits)}] 메일 열기: {subject}")
        try:
            open_mail_by_key(page, name, site, m.get("key", ""), subject, keyword)
        except Exception as e:
            log(f"  [{name}] 메일을 열지 못했습니다: {e}")
            continue
        total += download_attachments(page, name, dest)
        status.metric(f"{name}:mail_open", "메일 처리", i, len(hits))
        status.metric(f"{name}:files", "받은 첨부", len(total), unit="개")

    log(f"  [{name}] 첨부파일 {len(total)}개를 내려받았습니다.")
    site["_downloaded"] = total
    return True


# 대시보드에 보여줄 Action 이름
ACTION_LABELS = {
    "login": "로그인",
    "sms_2fa": "문자 2차인증",
    "mail_check": "메일 확인",
    "mail_download": "첨부 내려받기",
}

ACTIONS = {
    "login": action_login,
    "sms_2fa": action_sms_2fa,
    "mail_check": action_mail_check,
    "mail_download": action_mail_download,
}


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------
def prepare_page(page):
    """페이지 공통 설정.

    자바스크립트 alert/confirm 이 뜨면 Playwright 는 기본적으로 '취소'로 닫는다.
    안내창은 '확인'을 눌러야 다음으로 넘어가는 경우가 있어 받아넘기도록 바꾼다.

    이때 내용을 반드시 기록한다. 조용히 넘기면 사이트가 무슨 말을 했는지 알 수 없어
    실패 원인을 찾지 못한다(실제로 '문자가 안 온다'의 이유를 놓친 적이 있다).
    """
    page.set_default_timeout(FIELD_TIMEOUT_MS)

    def on_dialog(d):
        log(f"  브라우저 알림({d.type}): {d.message}")
        try:
            d.accept()
        except Exception:
            pass

    page.on("dialog", on_dialog)
    return page


def step_key(name, act):
    return f"{name}:{act}"


def prepare_steps(chosen):
    """대시보드에 보여줄 단계 목록. 사이트가 하나뿐이면 이름을 앞에 붙이지 않는다."""
    many = len(chosen) > 1
    out = []
    for name, site in chosen:
        for act in site_actions(site):
            label = ACTION_LABELS.get(act, act)
            out.append((step_key(name, act), f"{name} {label}" if many else label))
    return out


def run_site(browser, name, site, use_session=True, keep_open=False):
    """사이트 하나에 대해 Action 을 순서대로 실행한다."""
    log(f"=== {name} ===")

    # Playwright 의 new_context 자체가 시크릿 창과 같다. 매번 빈 프로필로 시작한다.
    # 그래서 '매번 다시 로그인' 은 저장해 둔 쿠키를 쓰지 않는 것만으로 이뤄진다.
    # accept_downloads 는 첨부파일 내려받기에 필요하다.
    spath = session_path(name)
    if use_session and os.path.exists(spath):
        context = browser.new_context(storage_state=spath, accept_downloads=True)
        log(f"  [{name}] 저장된 세션을 불러왔습니다: {spath}")
    else:
        context = browser.new_context(accept_downloads=True)
        if not use_session:
            log(f"  [{name}] 빈 프로필로 시작합니다 (매번 새로 로그인 + 2차인증)")
            # 안 쓸 파일을 남겨두지 않는다. 로그인한 것과 같은 효력을 갖는 파일이다.
            if os.path.exists(spath):
                try:
                    os.remove(spath)
                    log(f"  [{name}] 쓰지 않는 세션 파일을 지웠습니다: {spath}")
                except Exception as e:
                    log(f"  [{name}] 세션 파일을 지우지 못했습니다: {e}")

    page = prepare_page(context.new_page())
    ok = True
    try:
        for act in site_actions(site):
            fn = ACTIONS.get(act)
            if fn is None:
                log(f"  [{name}] 모르는 Action '{act}' - 건너뜁니다.")
                status.skip(step_key(name, act), "모르는 Action")
                ok = False
                continue
            status.step(step_key(name, act))
            fn(page, name, site)

        wait_after = site.get("wait_after", 0)
        if wait_after:
            log(f"  [{name}] 확인용으로 {wait_after}초 열어둡니다.")
            time.sleep(wait_after)
    except PWTimeout as e:
        log(f"  [{name}] 시간 초과: {str(e).splitlines()[0]}")
        status.fail_step(f"시간 초과: {str(e).splitlines()[0]}")
        ok = False
    except Exception as e:
        log(f"  [{name}] 실패: {type(e).__name__}: {e}")
        status.fail_step(f"{type(e).__name__}: {e}")
        ok = False
    finally:
        # 성공했을 때만 세션을 남긴다. 실패한 상태를 저장하면 다음 실행까지 망가진다.
        if ok and use_session:
            try:
                os.makedirs(SESSION_DIR, exist_ok=True)
                context.storage_state(path=spath)
                log(f"  [{name}] 세션을 저장했습니다: {spath}")
            except Exception as e:
                log(f"  [{name}] 세션 저장 실패: {e}")
        # 창을 열어둔 채 두라고 했으면 닫지 않는다.
        if not keep_open:
            context.close()
    return ok


def cmd_check():
    log("=== 설정 점검 ===")
    log(f"  설정 파일: {status.user_config_path()}"
        + ("" if os.path.isfile(status.user_config_path()) else " (아직 없음 - 옛 WebManageConfig.json 을 읽는다)"))
    try:
        cfg = load_config()
    except Exception as e:
        log(f"  읽기 실패: {e}")
        return 1

    if not cfg:
        log("  등록된 사이트가 없습니다.")
        return 1

    all_problems = []
    for name, site in cfg.items():
        problems = validate_site(name, site)
        all_problems += problems
        if isinstance(site, dict):
            stts = site_stts(site)
            mark = {STTS_RUN: "실행", STTS_SKIP: "보관"}.get(stts, "?")
            log(f"  [{mark} Stts={stts}] {name}: {site.get('URL', '(URL 없음)')}")
            log(f"          ID={site.get('ID', '')!r} PW={mask_pw(site.get('PW'))} "
                f"Action={site_actions(site)}")
        for p in problems:
            log(f"          ! {p}")

    log(f"  사이트 {len(cfg)}건, 문제 {len(all_problems)}건")
    log(f"  쓸 수 있는 Action: {', '.join(sorted(ACTIONS))}")
    return 1 if all_problems else 0


SELFTEST_HTML = """
<!doctype html><meta charset="utf-8"><title>로그인 자체테스트</title>
<form onsubmit="event.preventDefault();
   document.getElementById('r').textContent =
     '로그인됨 id=' + document.getElementById('u').value +
     ' pwlen=' + document.getElementById('p').value.length;">
  <input id="u" type="text" placeholder="아이디">
  <input id="p" type="password" placeholder="비밀번호">
  <button type="submit">로그인</button>
</form>
<div id="r"></div>
"""


def cmd_selftest(headless):
    """실제 사이트 없이 로그인 자동 찾기가 되는지 확인한다."""
    log("=== 자체 테스트 (내장 로그인 폼) ===")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        page.set_content(SELFTEST_HTML)

        pw_field = find_password_field(page, {})
        id_field = find_id_field(page, {})
        id_field.fill("테스트아이디")
        pw_field.fill("secret123")
        how = click_submit(page, {}, pw_field)
        log(f"  로그인 눌렀습니다 ({how})")

        page.wait_for_selector("#r:not(:empty)", timeout=5000)
        result = page.inner_text("#r")
        log(f"  결과: {result}")
        browser.close()

    ok = result == "로그인됨 id=테스트아이디 pwlen=9"
    log("  자체 테스트 통과" if ok else f"  자체 테스트 실패: {result!r}")
    return 0 if ok else 1


def resolve_use_session(site, cli_override):
    """저장된 쿠키를 쓸지 정한다.

    기본은 '쓰지 않음' 이다. 매번 새로 로그인하고 2차인증을 거치는 편이
    동작이 한결같고, 로그인과 같은 효력을 갖는 파일을 디스크에 남기지도 않는다.
    설정에 "UseSession": true 를 넣으면 재사용한다.
    """
    if cli_override is not None:
        return cli_override
    return bool(site.get("UseSession", False))


def cmd_run(targets, headless, session_override=None, keep_open=False,
            force_close=False):
    # 대시보드 기록을 시작한다. 설정 오류로 바로 끝나도 '중단'과 사유가 남는다.
    status.start("prepare")
    try:
        cfg = load_config()
    except Exception as e:
        log(f"설정을 읽지 못했습니다: {e}")
        return 1

    if targets:
        missing = [t for t in targets if t not in cfg]
        if missing:
            log(f"설정에 없는 사이트입니다: {', '.join(missing)}")
            log(f"등록된 사이트: {', '.join(cfg)}")
            return 1

        # Stts=9 는 '어떤 작업도 하지 않는다'는 뜻이므로 콕 집어 지정해도 막는다.
        blocked = [t for t in targets
                   if isinstance(cfg[t], dict) and not site_will_run(cfg[t])]
        if blocked:
            for t in blocked:
                log(f"{t}: Stts={site_stts(cfg[t])} 이라 실행하지 않습니다. "
                    f"실행하려면 Stts 를 {STTS_RUN} 으로 바꾸세요.")
            return 1
        chosen = [(t, cfg[t]) for t in targets]
    else:
        chosen = [(n, s) for n, s in cfg.items()
                  if isinstance(s, dict) and site_will_run(s)]
        if not chosen:
            log(f"실행할 사이트가 없습니다 (Stts={STTS_RUN} 인 사이트가 없습니다).")
            return 1

    problems = []
    for name, site in chosen:
        problems += validate_site(name, site)
    if problems:
        log("설정에 문제가 있어 실행하지 않습니다:")
        for p in problems:
            log(f"  ! {p}")
        return 1

    # 설정에 KeepOpen 이 있으면 그것도 따른다. --no-keep-open 은 그보다 우선한다.
    keep_open = keep_open or any(
        s.get("KeepOpen") for _, s in chosen if isinstance(s, dict))
    if force_close:
        keep_open = False

    status.set_steps(prepare_steps(chosen))
    log(f"{len(chosen)}개 사이트를 실행합니다. (창 {'숨김' if headless else '표시'})")
    done = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            for name, site in chosen:
                if run_site(browser, name, site,
                            use_session=resolve_use_session(site, session_override),
                            keep_open=keep_open):
                    done += 1

            log(f"=== 완료: 성공 {done}건 / 전체 {len(chosen)}건 ===")
            # 창을 열어두고 기다리기 전에 닫는다. 기다리는 동안은 '끝난' 상태로 보여야 한다.
            status.finish("success" if done == len(chosen) else "stopped")
            if keep_open:
                log("창을 열어둔 채 대기합니다. 끝내려면 Ctrl+C 를 누르세요.")
                try:
                    while True:
                        time.sleep(1)
                except KeyboardInterrupt:
                    log("사용자가 종료했습니다.")
        finally:
            browser.close()

    return 0 if done == len(chosen) else 1


def main():
    ap = argparse.ArgumentParser(
        description="RPA_UserConfig.json 의 Sites 를 읽어 사이트별 웹 작업을 실행합니다.")
    ap.add_argument("--check", action="store_true", help="설정 파일 점검")
    ap.add_argument("--selftest", action="store_true", help="내장 폼으로 동작 확인")
    ap.add_argument("--site", action="append", metavar="이름",
                    help="실행할 사이트 이름 (여러 번 쓸 수 있음)")
    ap.add_argument("--all", action="store_true", help="Stts=0 인 사이트를 모두 실행")
    ap.add_argument("--headless", action="store_true", help="브라우저 창을 띄우지 않음")
    ap.add_argument("--fresh", action="store_true",
                    help="저장된 세션을 무시하고 처음부터 로그인 (기본 동작)")
    ap.add_argument("--session", action="store_true",
                    help="저장된 세션을 재사용해 로그인과 2차인증을 건너뛴다 (점검용)")
    ap.add_argument("--keep-open", action="store_true", dest="keep_open",
                    help="작업이 끝나도 브라우저 창을 닫지 않고 대기 (Ctrl+C 로 종료)")
    ap.add_argument("--no-keep-open", action="store_true", dest="no_keep_open",
                    help="설정의 KeepOpen 을 무시하고 끝나면 바로 닫는다 "
                         "(루틴 RPA 로 이어서 실행할 때 필요)")
    args = ap.parse_args()

    if args.check:
        return cmd_check()
    if args.selftest:
        return cmd_selftest(args.headless)
    if args.site or args.all:
        override = None
        if args.fresh:
            override = False
        elif args.session:
            override = True
        return cmd_run(args.site, args.headless,
                       session_override=override, keep_open=args.keep_open,
                       force_close=args.no_keep_open)

    ap.print_help()
    return 0


if __name__ == "__main__":
    try:
        exit_code = main()
    except BaseException as e:
        status.fail_exception(e)
        raise
    sys.exit(exit_code)
