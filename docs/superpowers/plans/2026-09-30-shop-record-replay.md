# 쇼핑몰 조작 기록·재생 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 어느 쇼핑몰에나 쓰는 기록기(`Prepare_Recorder.exe`)로 '로그인 ~ 엑셀 받기' 를 프리셋 ①~⑩ 에 기록하고, 프리페어 RPA 가 켜진 프리셋을 재생해 `(사이트코드)이름.xlsx` 를 `ERPIA_AI_EXCEL` 에 넣으며, 대시보드에서 프리셋을 켜고 끄고 기록기 미리보기 기록을 본다.

**Architecture:** spike 엔진(`rec.py`)을 `web_replay.py` 로, 한 화면 기록기(`rec_app.py`)를 `rpa_recorder.py` 로 옮긴다. 프리셋 파일·`Sites` 칸·요약·켬끔은 모든 프로그램이 이미 쓰는 `rpa_status.py` 에 두고, 프리페어(`web_runner.py`)에는 Action `replay` 하나, 에이전트에는 명령 `set_presets` 하나, 대시보드에는 '실행 모듈' 과 같은 스위치 카드 하나를 더한다. 빌드는 세 번째 Nuitka exe(tk-inter, 콘솔 attach)를 만든다.

**Tech Stack:** Python 3.14 (`D:\AX\RPA\.venv`), Playwright sync API + Chromium, tkinter (Tcl/Tk 9), Nuitka 4.2.2 onefile, Inno Setup 6, Firebase RTDB·Firestore·Hosting (에뮬레이터, Java 21), 순수 JS 모듈 화면, pywinauto (화면 시험의 주소줄 치기).

**Spec:** `docs/superpowers/specs/2026-09-30-shop-record-replay-design.md`

## Global Constraints

- **커밋·push 는 사용자가 요청할 때만** (사용자 규칙). 각 작업 끝의 '변경 확인' 단계는 파일 목록과 제안 커밋 문장까지. 사용자가 "커밋" 하면 작업별로 커밋한다. `--no-verify` 금지. develop 에서. main push 는 정해진 절차로만.
- 비밀번호는 기록·프리셋 파일·로그·대시보드 어디에도 없다. 사용자 설정에만, 잠가서 (`rpa_status.write_user_config` 가 `LogIn.PW` 와 `Sites.*.PW` 를 쓰는 순간 잠근다).
- 로그인 아이디도 기록에는 없다 (`credential: "ID"`). 사용자 설정 `Sites.PRESETn.ID` 에만.
- 대시보드로 가는 로그 줄(상태 기록 `log_line`)에는 칸에 친 값·주소의 `?` 뒤가 없고 누른 글자는 20자까지 (`web_replay.describe(s, hide_values=True)`).
- 새로 저장한 프리셋은 `Stts` 9 (꺼짐). 켬/끔은 대시보드 → 명령 `set_presets` `{"PRESET1": true}` → `Stts` 0/9.
- 프리셋 수 2~10. 사이트코드 숫자 세 자리, 프리셋끼리 겹치지 않는다.
- 미리보기·기록 때 받은 파일은 `data\기록기\미리보기`·`data\기록기\기록` (`ERPIA_AI_EXCEL` 아님).
- 개발 PC: 진짜 `C:\ProgramData\AFTER MARKET\RPA\config` 를 만들지 않는다. `dist\RPA_UserConfig.json` 을 건드리지 않는다. setup.exe 를 돌리지 않는다. 시험은 `RPA_USER_CONFIG`·`RPA_PROGRAMDATA`·`RPA_STATUS_DIR` 를 임시 폴더로.
- `setup.js` 의 `user`·`agent`·`passwd` 는 Claude 도구로 돌리지 않는다 (이 계획에는 필요 없다).
- 인코딩: `.iss`·`.ps1` 은 BOM 있는 UTF-8 그대로 (편집 뒤 `tests\test_encoding.py`). 파이썬·문서는 BOM 없는 UTF-8. 작업 폴더는 CRLF (git autocrlf=true).
- 코드를 고친 작업 끝마다 `graphify update .` (CLAUDE.md).
- 밖으로 나가는 배포(`firebase deploy`)는 사용자 확인 뒤.
- spike 원본: `D:\AX\spike_rec_2026-09-30\` (`rec.py`·`rec_app.py`·`fake_mall.py`·`spike_test.py`·`stress.py`). 버리는 코드지만 옮길 원본이다.
- 파이썬은 `D:\AX\RPA\.venv\Scripts\python.exe` (시스템 python 에는 Playwright 가 없다). 명령은 `D:\AX\RPA` 에서.
- 파이썬 패치를 bash heredoc 로 넘기면 백슬래시가 반으로 준다 - 파일은 편집 도구로 고친다.

## Review Focus

1. **사람이 `RPA_Presets.json` 을 손으로 고쳐 깨뜨림** → 기록기는 덮어쓰지 않고 알리고 열지 않는다, 프리페어 `--check` 는 문제로 적는다, 대시보드는 카드를 숨긴다 (빈 목록으로 속이지 않는다). 시험: Task 2 (`read_presets`·`preset_summary`), Task 3 (`validate_site`), Task 4 (`load_presets`).
2. **두 프리셋이 같은 사이트코드** → 저장 거부 (루틴은 한 코드에 최신 파일 하나만 올리고 나머지는 오류 폴더로 보낸다). 시험: Task 4 `validate_presets`.
3. **눌러도 파일이 안 받아짐** (사이트가 확인 창을 하나 더 넣은 날) → 정해진 시간 뒤 그 단계 실패로 끝난다. 시험: Task 1 시험 I.
4. **미리보기 도중 기록기 창을 닫음** → 다음 단계 전에 멈추고 브라우저를 닫는다, 대시보드 기록은 '실패' 한 줄 ('진행 중' 으로 남지 않음). 시험: Task 1 시험 J (`cancel`), Task 4 (`quit` → `cancel`, `finally` 의 `finish`).
5. **프리셋 이름에 `<b>` 같은 꺾쇠** → 대시보드에 글자 그대로 (태그로 해석되지 않는다). 시험: Task 7.

## 파일 지도

| 파일 | 새로/고침 | 맡는 일 |
|---|---|---|
| `web_replay.py` | 새로 (spike `rec.py`) | 기록 스크립트·`Recorder`·`finalize`·`keep_steps`·`describe`·`Replayer` |
| `tests/fake_mall.py` | 새로 (spike 그대로) | 시험용 가짜 쇼핑몰 |
| `tests/test_web_replay.py` | 새로 (spike `spike_test.py` + F~J) | 엔진 시험 |
| `tests/stress_web_replay.py` | 새로 | CPU 부하 반복 재생 (따로 돌린다) |
| `rpa_status.py` | 고침 | 프리셋 파일·`Sites` 칸·요약·켬끔, `LABELS`, 브라우저 자리, 관리자·계정 확인 |
| `rpa_settings.py` | 고침 | 관리자·계정 확인을 `rpa_status` 것으로 |
| `tests/test_presets.py` | 새로 | 프리셋·설정·프리페어 replay·기록기 저장 전 확인 |
| `web_runner.py` | 고침 | Action `replay`, 점검, 단계 이름 |
| `rpa_recorder.py` | 새로 (spike `rec_app.py`) | 기록기 창 → `Prepare_Recorder.exe` |
| `tests/check_recorder_ui.py` | 새로 | 기록기 창을 진짜로 띄워 한 바퀴 |
| `tools/build_release.py` | 고침 | 세 번째 exe, 콘솔은 exe 마다, Tcl/Tk 꺼내기, 없는 exe 거부 |
| `tests/test_build_release.py` | 고침 | 위를 확인 |
| `release/installer.iss` | 고침 | 시작 메뉴 '쇼핑몰 기록기' |
| `tools/sandbox_inner.ps1` | 고침 | 기록기 `--check`·바로 가기·아이콘 |
| `firebase/agent/agent.py` | 고침 | 현황 `presets`, 명령 `set_presets`, 도넛에서 기록기 빼기 |
| `firebase/tests/test_agent.py` | 고침 | 위를 확인 |
| `firebase/rules/database.rules.json`, `firebase/tests/rules.test.js` | 고침 | 명령 종류 `set_presets` |
| `firebase/web/rpa.js`, `firebase/tests/check_web.py` | 고침 | '쇼핑몰 프리셋' 카드, 기록 표 '기록기' |
| `docs/firebase-architecture.md`, 스펙 상태 줄 | 고침 | 파일 지도·데이터 경로·시험 표 |

## 걸리는 시간 (어림, 한 세션이 직접 할 때 - 2026-09-30 실측으로 고침)

| 작업 | 분 | 대부분 무엇에 |
|---|---|---|
| 0 아이콘 확인 | 2 | |
| 1 엔진 | 20 | 가짜 쇼핑몰 시험 한 바퀴 3~4분 × 3 |
| 2 프리셋·설정 | 10 | |
| 3 프리페어 replay | 10 | 끝까지 도는 시험 1~2분 |
| 4 기록기 창 | 25 | 옮길 코드가 가장 많다, 창 시험 한 바퀴 3분 |
| 5 빌드·설치·샌드박스 스크립트 | 15 | 기록기 exe 한 번 빌드 3분 |
| 6 에이전트·규칙 | 10 | 규칙 시험은 에뮬레이터 |
| 7 대시보드 | 15 | 화면 시험 한 바퀴 2~5분 |
| 8 문서·판 빌드·샌드박스 | 20 | 판 빌드 10분쯤, 샌드박스 3분쯤 (기다림) |
| **합계** | **약 130분 (2시간 안팎, 막히면 3시간)** | |

처음 어림(400분)은 사람 기준 단계 시간이었다. 실측: 설치 마법사 계획(2026-09-29)은 7시간으로 어림했는데 계획 저장부터 커밋까지 1시간 10분, 판 빌드 9분·샌드박스 2분(2026-09-30 판 -3). 오래 걸릴 수 있는 곳은 작업 4 창 시험(마우스·키보드를 쓴다)과 작업 5 콘솔 붙이기(--check 출력).

---

### Task 0: 이미 끝난 것 확인 (아이콘, 2026-09-30)

**Files:** 이미 고친 것 - `tools/make_icon.py`, `release/AFTER_MARKET_PREPARE.ico` (새로), `tools/build_release.py` (`ICON_PREPARE`, exe 마다 아이콘, `PROGRAM_FILES` 에 주황 ico), `tests/test_build_release.py` (49), `tools/sandbox_inner.ps1` (프리페어만 주황), `docs/firebase-architecture.md` (시험 표). 커밋 안 됨.

- [ ] **Step 1: 빌드 시험이 그대로 통과하는지**

Run: `.venv\Scripts\python.exe tests\test_build_release.py`
Expected: 마지막 줄 `실패: 없음` (49개).

- [ ] **Step 2: 인코딩 시험**

Run: `.venv\Scripts\python.exe tests\test_encoding.py`
Expected: `실패: 없음` (`sandbox_inner.ps1` BOM 유지).

---

### Task 1: 기록·재생 엔진 `web_replay.py`

**Files:**
- Create: `web_replay.py` (spike `rec.py` 를 옮기고 고친다)
- Create: `tests/fake_mall.py` (spike 그대로)
- Create: `tests/test_web_replay.py` (spike `spike_test.py` 를 옮기고 시험 F~J 를 더한다)
- Create: `tests/stress_web_replay.py`

**Interfaces:**
- Consumes: 없음 (spike 원본만)
- Produces:
  - `web_replay.RECORD_VERSION = 1`, `DOWNLOAD_TIMEOUT_MS = 60000`, `CUT = 20`, `SETTLE_MAX_MS`, `OPTIONAL_WAIT`, `NAV_KINDS`, `SESSION_Q`
  - `web_replay.Recorder(context, sample_dir=None)` - `.steps: list[dict]`, `.pages`, `.samples`, `._page(page)`, `._event(source, ev)`, `._dialog(d)`, `._download(d)` (기록기가 상속한다)
  - `web_replay.user_tab(page) -> bool`, `web_replay.url_path(url) -> str`
  - `web_replay.finalize(steps, record_date: datetime.date, start_url: str, viewport: dict | None = None) -> dict` → `{"version", "start_url", "record_date", "steps"[, "viewport"]}`
  - `web_replay.keep_steps(rec: dict, keep: list[int]) -> dict`
  - `web_replay.describe(step: dict, hide_values: bool = False) -> str`
  - `web_replay.Replayer(context, rec, creds: dict, out_dir, code, today=None, review=False, log=print, step_timeout=30.0, hide_values=False, shot_dir=None)`; 속성 `progress(i, state, how)` (state: `run`/`ok`/`skip`/`fail`), `page_hook(page)`, `first_page`, `fit_viewport: bool`, `cancel: threading.Event | None`, `download_timeout_ms: int`; `run() -> bool` (모르는 `version` 이면 `ValueError`); 끝나면 `results: list[tuple[int, str, str]]`, `saved: list[str]`, `elapsed: float`
  - `web_replay.record(start_url, out_path, headless=False, human=None, record_date=None, sample_dir=None) -> dict`, `web_replay.replay(rec, creds, out_dir, code, today=None, review=False, headless=True, log=print, step_timeout=30.0) -> (bool, Replayer)` (시험용)
  - `tests/fake_mall.py`: `start(today=None, notice="random", port=0) -> (srv, url, Mall)`, `Mall(today, notice)`, `USER = "seller01"`, `PASSWORD = "pw1234"`. 서버의 가게는 `srv.mall = Mall(...)` 로 바꿔 끼운다. `Mall` 은 `logins`, `searches`, `requests`, `downloads`, `ship_downloads`, `notice`, `list_delay` 를 기록한다.
  - `tests/test_web_replay.py`: `hclick(page, loc)`, `human(mall, notice, dates=False, enter_login=False, noise=False)`, `DAY` (다른 시험이 가져다 쓴다)

- [ ] **Step 1: 옮기기**

```powershell
Copy-Item D:\AX\spike_rec_2026-09-30\rec.py D:\AX\RPA\web_replay.py
Copy-Item D:\AX\spike_rec_2026-09-30\fake_mall.py D:\AX\RPA\tests\fake_mall.py
Copy-Item D:\AX\spike_rec_2026-09-30\spike_test.py D:\AX\RPA\tests\test_web_replay.py
```

- [ ] **Step 2: 시험을 저장소 자리에 맞춘다**

`tests/test_web_replay.py` 맨 위 (첫 줄부터 `OUT = …` 줄까지) 를 통째로 바꾼다. 원래:

```python
# -*- coding: utf-8 -*-
"""[시험용 · 버리는 코드] 가짜 쇼핑몰에서 기록 → (다음 날) 재생 → 서버 기록으로 결과를 확인한다.

사람 역할은 화면 위치를 마우스로 누르고 키보드로 친다 (기록기는 사람이 한 것만 받는다).
    python spike_test.py
"""
import datetime
import json
import os
import shutil
import sys

import fake_mall
import rec

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out", "시험")        # 이 폴더만 비운다 (기록기 앱의 out\앱 은 건드리지 않는다)
```

새로:

```python
# -*- coding: utf-8 -*-
"""기록·재생 엔진(web_replay) 시험 - 가짜 쇼핑몰(tests/fake_mall.py)에서 기록 → (다음 날) 재생 → 서버 기록으로 확인한다.

사람 역할은 화면 위치를 마우스로 누르고 키보드로 친다 (기록기는 사람이 한 것만 받는다). 창은 뜨지 않는다.
    .venv\\Scripts\\python.exe tests\\test_web_replay.py
"""
import datetime
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import fake_mall  # noqa: E402
import web_replay as rec  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
OUT = tempfile.mkdtemp(prefix="rpa_replay_")   # 받은 파일·실패 사진 (저장소 밖)
```

- [ ] **Step 3: `web_replay.py` 를 제품 모양으로**

1. 맨 위 설명(`"""[시험용 · 버리는 코드] …` 부터 닫는 `"""` 까지)을 이것으로:

```python
"""사이트를 가리지 않는 조작 기록·재생 엔진 (기록기 rpa_recorder 와 프리페어 web_runner 의 replay 가 쓴다).

기록: 누른 것마다 단서를 여러 개 적는다 (id·글자·name·안내 글·칸 이름·위치·같은 글자 중 몇 번째).
      비밀번호 칸은 값을 아예 받지 않는다. 아이디는 '설정의 아이디' 로 바꿔 적는다. 사람이 한 것만 적는다 (isTrusted).
재생: 단서를 차례로 써서 하나로 정해지고 모양이 같은 것을 누른다. 가려진 메뉴는 마우스를 올려 열고,
      예상 밖 공지는 닫고, '있을 때만' 단계는 없으면 건너뛰고, 날짜는 오늘 기준으로 바꾼다.
설계: docs/superpowers/specs/2026-09-30-shop-record-replay-design.md 3절. 시험: tests/test_web_replay.py
"""
```

2. `import argparse` 줄을 지운다.
3. 파일 끝의 `def main():` 부터 `if __name__ == "__main__":` 와 그 아래 `main()` 까지 지운다 (명령줄은 기록기와 프리페어가 맡는다).
4. `Replayer._pick` 안의 디버그 세 줄을 지운다:

```python
            if os.environ.get("REC_DEBUG") and fresh:
                print(f"      [DEBUG] {time.strftime('%H:%M:%S')} nth={nth} fresh={fresh} sigs={sigs} "
                      f"기준의 다운로드={sorted(g for g in prev if g.startswith('/file/'))}", file=sys.stderr)
```

5. `Replayer._snapshot` 끝의 `try:` 부터 함수 끝까지를 이것으로:

```python
        try:
            fr.evaluate(QUIET_JS)
            return set(fr.evaluate(SNAP_JS))
        except Exception:
            return set()
```

- [ ] **Step 4: 옮긴 시험이 그대로 통과하는지**

Run: `.venv\Scripts\python.exe tests\test_web_replay.py`
Expected: `[통과]` 44줄, 마지막 `실패: 없음` (3~4분).

- [ ] **Step 5: 새 시험 F~J 를 쓴다**

`tests/test_web_replay.py` 의 `main()` 안, C 시험(`check("C: 비밀번호가 틀리면 …")`) 바로 뒤, `finally:` 앞에 넣는다:

```python
        # ---------------- F: 주소줄 단계 (goto·back·newtab) 와 기록 때 창 크기 ----------------
        print("=== F. 주소줄 단계와 창 크기")
        srv.mall = fake_mall.Mall(DAY, False)
        f = {"version": 1, "start_url": "", "record_date": DAY.isoformat(), "viewport": {"width": 900, "height": 640},
             "steps": [{"kind": "goto", "page": 0, "url": "/login", "href": url + "/login", "gap": 0},
                       {"kind": "newtab", "page": 1, "url": "", "gap": 0},
                       {"kind": "goto", "page": 1, "url": "/login", "href": url + "/login?tab=2", "gap": 0},
                       {"kind": "goto", "page": 0, "url": "/login", "href": url + "/login?b=1", "gap": 0},
                       {"kind": "back", "page": 0, "url": "/login", "gap": 0}]}
        with rec.sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context()
            r = rec.Replayer(ctx, f, {"ID": "", "PW": ""}, os.path.join(OUT, "F"), "012", log=print)
            r.fit_viewport = True
            ok = r.run()
            urls = [pg.url for pg in ctx.pages]
            size = ctx.pages[0].viewport_size
            browser.close()
        check("F: 주소 치기·새 탭·뒤로 가기를 따라 한다", ok and len(urls) == 2 and urls[0] == url + "/login"
              and urls[1].endswith("/login?tab=2"), str((ok, urls, r.results)))
        check("F: 기록 때 창 안쪽 크기로 연다 (반응형 사이트의 메뉴 모양)", size == {"width": 900, "height": 640}, str(size))

        # ---------------- G: 대시보드로 가는 설명에는 값이 없다 ----------------
        T = {"tag": "input", "text": "", "label": "", "placeholder": "사유를 입력하세요", "aria": "", "title": "", "name": "",
             "textCount": 1}
        g = [{"kind": "fill", "target": T, "value": "주문 처리 - 비밀아님"},
             {"kind": "goto", "href": "https://shop.example.com/main?sid=abc123&x=1"},
             {"kind": "click", "target": dict(T, tag="a", text="아주아주긴글자가스무자를넘어가는링크이름입니다정말로")}]
        full, hidden = [rec.describe(s) for s in g], [rec.describe(s, hide_values=True) for s in g]
        check("G: 평소 설명에는 친 값·주소가 다 보인다 (기록기 목록)", "주문 처리 - 비밀아님" in full[0] and "sid=abc123" in full[1])
        check("G: 대시보드용 설명에는 친 값·주소 ? 뒤가 없고 누른 글자는 20자까지", "비밀아님" not in hidden[0]
              and "글자" in hidden[0] and "abc123" not in hidden[1] and "https://shop.example.com/main" in hidden[1]
              and "정말로" not in hidden[2] and "…" in hidden[2], str(hidden))
        check("G: 주소에 세션 값이 있으면 경고 (다음에 깨질 수 있음)", "세션" in full[1])

        # ---------------- H: 모르는 기록 형식 ----------------
        try:
            rec.Replayer(None, {"version": 99, "steps": []}, {}, OUT, "012").run()
            check("H: 모르는 기록 형식은 재생하지 않는다", False)
        except ValueError as e:
            check("H: 모르는 기록 형식은 재생하지 않는다", "형식" in str(e), str(e))

        # ---------------- I: 눌러도 파일이 안 온다 (Review Focus 3) ----------------
        bad = json.loads(json.dumps(a))
        bad["steps"][7]["download"] = "안 오는 파일.xlsx"            # '검색' 을 눌러도 파일은 안 온다 (사이트가 바뀐 날)
        day = DAY + datetime.timedelta(days=1)
        srv.mall = m = fake_mall.Mall(day, False)
        t0 = time.time()
        with rec.sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(accept_downloads=True)
            r = rec.Replayer(ctx, bad, {"ID": fake_mall.USER, "PW": fake_mall.PASSWORD}, os.path.join(OUT, "I"), "012",
                             today=day, log=print)
            r.download_timeout_ms = 3000
            ok = r.run()
            browser.close()
        check("I: 파일이 안 오면 정해진 시간 뒤 그 단계 실패 (끝없이 기다리지 않는다)", not ok and r.results[-1][0] == 8
              and "Timeout" in r.results[-1][2] and time.time() - t0 < 60, str(r.results[-1]))

        # ---------------- J: 미리보기 중 창을 닫음 (Review Focus 4) ----------------
        ev = threading.Event()
        srv.mall = m = fake_mall.Mall(day, False)
        with rec.sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(accept_downloads=True)
            r = rec.Replayer(ctx, a, {"ID": fake_mall.USER, "PW": fake_mall.PASSWORD}, os.path.join(OUT, "J"), "012",
                             today=day, log=print)
            r.cancel = ev
            r.progress = lambda i, state, how: ev.set() if (i, state) == (3, "ok") else None
            ok = r.run()
            browser.close()
        check("J: 멈춤(cancel)이 켜지면 다음 단계 전에 멈춘다", not ok and r.results[-1][:2] == (4, "fail")
              and "멈춤" in r.results[-1][2] and m.downloads == [], str(r.results[-2:]))
```

- [ ] **Step 6: 실패를 확인한다**

Run: `.venv\Scripts\python.exe tests\test_web_replay.py`
Expected: F 의 창 크기, G 둘(`describe() got an unexpected keyword argument 'hide_values'` 로 멈추거나 실패), H, I, J 가 `[실패]` 또는 예외. (I 는 기본 60초를 다 기다린다.)

- [ ] **Step 7: 구현**

1. `OPTIONAL_WAIT = 3.0` 줄 아래에 더한다:

```python
RECORD_VERSION = 1           # 기록 모양. 다르면 재생하지 않는다 (옛 프리페어가 새 기록을 잘못 따라 하지 않게)
DOWNLOAD_TIMEOUT_MS = 60000  # 파일 받기를 기다리는 시간 (안 오면 그 단계 실패)
CUT = 20                     # 대시보드로 가는 설명에서 누른 것의 글자 길이
```

2. `def finalize(steps, record_date, start_url):` 를 `def finalize(steps, record_date, start_url, viewport=None):` 로, 끝의 `return {"version": 1, "start_url": start_url, "record_date": record_date.isoformat(), "steps": out}` 를:

```python
    rec_obj = {"version": RECORD_VERSION, "start_url": start_url, "record_date": record_date.isoformat(), "steps": out}
    if viewport:
        rec_obj["viewport"] = viewport       # 기록 때 창 안쪽 크기 - 프리페어가 같은 크기로 연다
    return rec_obj
```

3. `def describe(s):` 함수를 통째로 바꾼다 (바로 앞에 `_cut` 을 둔다):

```python
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
```

4. `class Replayer:` 의 `__init__` 을 통째로:

```python
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
        self.first_page = None      # 이미 있는 창에서 시작 (기록기·프리페어가 연 창)
        self.fit_viewport = False   # 기록 때 창 안쪽 크기로 (프리페어. 기록기 미리보기는 창 자리를 맞춘다)
        self.cancel = None          # threading.Event - 켜지면 다음 단계 전에 멈춘다 (기록기 창을 닫음)
        self.download_timeout_ms = DOWNLOAD_TIMEOUT_MS
        self.elapsed = 0.0
```

5. `_step` 안의 `with page.expect_download(timeout=60000) as di:` 를 `with page.expect_download(timeout=self.download_timeout_ms) as di:` 로.

6. `def run(self):` 를 통째로:

```python
    def run(self):
        if self.rec.get("version") != RECORD_VERSION:
            raise ValueError(f"모르는 기록 형식입니다 (version {self.rec.get('version')!r}) - "
                             "기록기와 프리페어를 같은 판으로 맞추세요")
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
                self.results.append((i, "fail", "멈춤 - 기록기 창을 닫았습니다"))
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
```

- [ ] **Step 8: 통과를 확인한다**

Run: `.venv\Scripts\python.exe tests\test_web_replay.py`
Expected: `[통과]` 52줄 (44 + F 2 + G 3 + H·I·J), 마지막 `실패: 없음`.

- [ ] **Step 9: 부하 시험을 옮긴다** (오래 걸려 따로 돌린다)

Create `tests/stress_web_replay.py`:

```python
# -*- coding: utf-8 -*-
"""부하 시험 (오래 걸린다, 따로 돌린다) - CPU 를 바쁘게 해 두고 A 기록을 다음 날·기다림 없이 번갈아 22번 재생한다.
옛 파일을 한 번이라도 받으면 실패. PC 가 바쁠 때 innerText 가 표 칸 사이 띄어쓰기를 빼먹어 옛 줄이 새것처럼 보였던 일
(2026-09-30, 그래서 글자는 textContent 로 읽는다)을 잡는다.
    .venv\\Scripts\\python.exe tests\\stress_web_replay.py
"""
import datetime
import multiprocessing
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake_mall  # noqa: E402
import web_replay as rec  # noqa: E402
from test_web_replay import DAY, human  # noqa: E402


def burn(stop):
    while not stop.is_set():
        sum(i * i for i in range(20000))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    out = tempfile.mkdtemp(prefix="rpa_stress_")
    srv, url, _ = fake_mall.start(DAY, True)
    srv.mall = mall = fake_mall.Mall(DAY, True)
    a = rec.record(url + "/login", os.path.join(out, "rec_a.json"), headless=True, human=human(mall, True, noise=True),
                   record_date=DAY)
    stop = multiprocessing.Event()
    burners = [multiprocessing.Process(target=burn, args=(stop,)) for _ in range(max(2, (os.cpu_count() or 4) - 2))]
    for b in burners:
        b.start()
    bad = 0
    try:
        for rnd in range(11):
            for off, settle in ((1, 3000), (3, 0)):
                day = DAY + datetime.timedelta(days=off)
                srv.mall = m = fake_mall.Mall(day, False)
                rec.SETTLE_MAX_MS = settle
                ok, r = rec.replay(a, {"ID": fake_mall.USER, "PW": fake_mall.PASSWORD}, os.path.join(out, "dl"), "012",
                                   today=day, log=lambda x: None)
                good = ok and m.downloads == [m.requests[-1]["id"]]
                print(rnd, off, settle, "OK" if good else "XXXX 옛 파일 또는 멈춤", m.downloads, r.results[-1][2][:40], flush=True)
                bad += not good
    finally:
        stop.set()
        for b in burners:
            b.join()
        srv.shutdown()
    print("실패:", bad or "없음")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
```

Run (선택, 약 5분): `.venv\Scripts\python.exe tests\stress_web_replay.py`
Expected: `OK` 22줄, `실패: 없음`.

- [ ] **Step 10: graphify·변경 확인**

Run: `graphify update .` 과 `git status --short`
Expected: `web_replay.py`, `tests/fake_mall.py`, `tests/test_web_replay.py`, `tests/stress_web_replay.py` 가 새로. 제안 커밋: `기록·재생 엔진 web_replay (spike 를 옮김) - 주소줄 단계·창 크기·값 없는 설명·받기 시간·멈춤, 시험 52`.

---

### Task 2: 프리셋 파일·`Sites` 칸·요약·켬끔 (`rpa_status`)

**Files:**
- Modify: `rpa_status.py` (상수 `PROGRAMS` 바로 아래, `program_dir()` 뒤, import 줄, `write_routine_modules()` 뒤)
- Modify: `rpa_settings.py` (`is_admin`·`relaunch_as_admin`·`process_user`·`session_user`·`same_account`, 75~128줄쯤)
- Create: `tests/test_presets.py`

**Interfaces:**
- Consumes: 없음 (`web_replay` 의 기록 dict 모양만: `record["steps"]`, `record["start_url"]`)
- Produces (`rpa_status`):
  - `HISTORY_ONLY = {"recorder": "기록기"}`, `LABELS = {**PROGRAMS, **HISTORY_ONLY}`
  - `PRESETS_NAME = "RPA_Presets.json"`, `PRESET_MIN = 2`, `PRESET_MAX = 10`, `REPLAY_ACTION = "replay"`
  - `presets_path() -> str`, `blank_preset(no) -> dict`, `read_presets() -> list[dict]` (`{no, name, code, saved_at, record}`, 깨졌으면 `ValueError`), `write_presets(presets) -> list[dict]` (2~10 아니면 `ValueError`)
  - `preset_site_key(no) -> "PRESETn"`, `save_preset_sites(presets, logins: {no: (id, pw 또는 None)}) -> None` (설정 없으면 `FileNotFoundError`)
  - `preset_summary() -> list[dict] | None` (`{no, name, code, steps, saved_at, has_login, on}`)
  - `set_preset_switches(wanted: {"PRESET1"|"1"|1: bool}) -> {int: bool}` (`ValueError`·`FileNotFoundError`)
  - `setup_playwright_browsers() -> None`
  - `is_admin()`, `run_as_admin(exe, args, cwd) -> bool`, `process_user()`, `session_user()`, `same_account(a, b)`

- [ ] **Step 1: 실패하는 시험을 쓴다**

Create `tests/test_presets.py`:

```python
"""쇼핑몰 프리셋 시험 - 프리셋 파일·사용자 설정 Sites 의 PRESETn 칸·대시보드 요약·켬끔 (rpa_status),
프리페어의 replay (web_runner), 기록기의 저장 전 확인 (rpa_recorder). 창은 뜨지 않는다.

실제 설정은 건드리지 않는다. RPA_USER_CONFIG·RPA_PROGRAMDATA·RPA_STATUS_DIR 를 임시 폴더로.
    .venv\\Scripts\\python.exe tests\\test_presets.py
"""
import datetime
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="rpa_presets_")
os.environ["RPA_USER_CONFIG"] = os.path.join(TMP, "config", "RPA_UserConfig.json")
os.environ["RPA_PROGRAMDATA"] = os.path.join(TMP, "programdata")
os.environ["RPA_STATUS_DIR"] = os.path.join(TMP, "status")
os.makedirs(os.path.join(TMP, "config"))
os.makedirs(os.path.join(TMP, "programdata", "config"))    # 새 구조로 보이게 (기록 폴더가 programdata\data 가 된다)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.stdout.reconfigure(encoding="utf-8")

import rpa_status as st  # noqa: E402

fails = []
_no = [0]


def check(name, cond, detail=""):
    _no[0] += 1
    print(f"  {_no[0]:2d}. [{'통과' if cond else '실패'}] {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(f"{_no[0]}. {name} {detail}")


def raw_config():
    with open(st.user_config_path(), encoding="utf-8") as f:
        return f.read()


def raises(exc, fn, *args):
    try:
        fn(*args)
        return None
    except exc as e:
        return e


PW = "프리셋-비밀번호-유출금지"
REC = {"version": 1, "start_url": "https://shop.example.com/login", "record_date": "2026-09-30",
       "steps": [{"kind": "goto", "page": 0, "url": "/login", "href": "https://shop.example.com/login", "gap": 0}]}
BASE = {"LogIn": {"AdminCode": "t", "ID": "erp", "PW": "erp-pw"}, "Routine": {"Login": "Y"},
        "Sites": {"SITE1": {"URL": "https://mail.example.com", "ID": "m", "PW": "mail-pw", "Action": "login", "Stts": 9}}}

print("=== 1. 프리셋 파일과 Sites 칸 (rpa_status) ===")
check("프리셋 파일 자리는 사용자 설정 옆", st.presets_path() == os.path.join(TMP, "config", "RPA_Presets.json"))
ps = st.read_presets()
check("파일이 없으면 빈 프리셋 둘", [p["no"] for p in ps] == [1, 2] and all(p["record"] is None for p in ps), str(ps))
st.write_presets([{"no": 7, "name": "지마켓", "code": "012", "saved_at": "2026-09-30T18:20:00", "record": REC},
                  st.blank_preset(2), {"no": 9, "name": "쿠팡", "code": "", "saved_at": None, "record": None}])
ps = st.read_presets()
check("쓰고 읽기 - 번호는 순서대로 다시 매긴다, 기록은 그대로", [p["no"] for p in ps] == [1, 2, 3]
      and ps[0]["name"] == "지마켓" and ps[0]["record"] == REC and ps[2]["name"] == "쿠팡", str(ps))
check("1개·11개는 거부 (2~10)", all(raises(ValueError, st.write_presets, [st.blank_preset(i + 1) for i in range(n)])
                                  for n in (1, 11)))
check("사용자 설정이 없으면 Sites 를 새로 만들지 않는다", raises(FileNotFoundError, st.save_preset_sites, ps, {1: ("s", PW)}))
check("설정이 없으면 요약도 없음 (대시보드는 카드를 숨긴다)", st.preset_summary() is None)
st.write_user_config(BASE)
st.save_preset_sites(ps, {1: ("seller01", PW)})
cfg = st.read_user_config()
site = cfg["Sites"].get("PRESET1") or {}
check("기록 있는 프리셋만 칸이 생긴다, 처음엔 꺼짐 (Stts 9)", [k for k in cfg["Sites"] if k.startswith("PRESET")] == ["PRESET1"]
      and site.get("Stts") == 9 and site.get("Action") == ["replay"] and site.get("Preset") == 1 and site.get("note") == "지마켓"
      and site.get("URL") == REC["start_url"] and site.get("ID") == "seller01", str(site))
check("비밀번호는 잠겨서 들어가고 풀면 같다", PW not in raw_config() and st.unseal(site.get("PW")) == PW)
check("다른 섹션·다른 사이트는 그대로", cfg["LogIn"]["ID"] == "erp" and cfg["Routine"] == {"Login": "Y"}
      and st.unseal(cfg["Sites"]["SITE1"]["PW"]) == "mail-pw" and cfg["Sites"]["SITE1"]["Stts"] == 9)
cfg["Sites"]["PRESET1"]["Stts"] = 0
st.write_user_config(cfg)
ps[0]["name"] = "지마켓 판매자"
st.save_preset_sites(ps, {1: ("seller02", None)})
site = st.read_user_config()["Sites"]["PRESET1"]
check("다시 저장: 비밀번호를 안 주면 그대로, 켬/끔도 그대로, 이름·아이디는 새 값", st.unseal(site["PW"]) == PW
      and site["Stts"] == 0 and site["note"] == "지마켓 판매자" and site["ID"] == "seller02", str(site))
summary = st.preset_summary()
check("요약: 번호·이름·코드·단계 수·저장 시각·아이디 여부·켬", summary[0] == {
      "no": 1, "name": "지마켓", "code": "012", "steps": 1, "saved_at": "2026-09-30T18:20:00", "has_login": True, "on": True}
      and summary[1]["steps"] == 0 and summary[1]["has_login"] is False, str(summary))
check("요약에는 기록 내용·아이디·비밀번호가 없다", all(set(s) == {"no", "name", "code", "steps", "saved_at", "has_login", "on"}
                                                  for s in summary) and "seller" not in json.dumps(summary, ensure_ascii=False))
check("켜기·끄기는 Stts 0/9 (키는 PRESET1·'1'·1 모두)",
      st.set_preset_switches({"PRESET1": False}) == {1: False} and st.read_user_config()["Sites"]["PRESET1"]["Stts"] == 9
      and st.set_preset_switches({"1": True}) == {1: True} and st.read_user_config()["Sites"]["PRESET1"]["Stts"] == 0
      and st.set_preset_switches({1: False}) == {1: False})
check("모르는 번호·번호가 아닌 키만 있으면 거부", raises(ValueError, st.set_preset_switches, {"PRESET7": True})
      and raises(ValueError, st.set_preset_switches, {"x": True}))
cfg = st.read_user_config()
cfg["Sites"]["PRESET1"]["PW"] = ""
st.write_user_config(cfg)
e = raises(ValueError, st.set_preset_switches, {"PRESET1": True})
check("비밀번호가 없는 프리셋은 켜지 않는다", e is not None and "켤 수 없" in str(e), str(e))
check("끄기는 비밀번호가 없어도 된다", st.set_preset_switches({"PRESET1": False}) == {1: False})
st.save_preset_sites([dict(ps[0], record=None), ps[1], ps[2]], {})
check("기록을 지운 프리셋의 칸은 지운다", "PRESET1" not in st.read_user_config()["Sites"])
st.save_preset_sites(ps, {1: ("seller01", PW)})
with open(st.presets_path(), "w", encoding="utf-8") as f:
    f.write("{깨진")
check("깨진 프리셋 파일은 ValueError (덮어쓰지 않게)", raises(ValueError, st.read_presets))
check("깨진 파일이면 요약은 없음 (빈 목록으로 속이지 않는다)", st.preset_summary() is None)
st.write_presets(ps)

print("=== 2. 기록기 미리보기는 이력에만 ===")
st.start("recorder", [("s1", "하나")], title="① 지마켓")
st.step("s1")
st.log_line("[10:00:00] 미리보기 성공")
st.finish("success")
rows = st.read_history(program="recorder")
check("기록기 미리보기는 이력에 '기록기' 로 남는다", bool(rows) and rows[0]["program_label"] == "기록기", str(rows[:1]))
check("현황 카드(프로그램 목록)에는 안 나온다", "recorder" not in st.dashboard_snapshot()["programs"])

print("=== 3. 관리자·계정 확인 (설정 창과 같이 쓴다) ===")
import rpa_settings as rs  # noqa: E402
check("계정 비교는 대소문자 무시", st.same_account("PC\\Me", "pc\\me") and not st.same_account("PC\\a", None))
check("설정 창은 같은 함수를 쓴다", rs.same_account is st.same_account and rs.session_user is st.session_user
      and rs.process_user is st.process_user and rs.is_admin is st.is_admin)

print()
print(f"실패: {'없음' if not fails else fails}")
sys.exit(1 if fails else 0)
```

- [ ] **Step 2: 실패를 확인한다**

Run: `.venv\Scripts\python.exe tests\test_presets.py`
Expected: `AttributeError: module 'rpa_status' has no attribute 'presets_path'` 로 멈춘다.

- [ ] **Step 3: 구현 (`rpa_status.py`)**

1. import 줄에 `import subprocess` 를 더한다 (`import socket` 다음).
2. `PROGRAMS = {"prepare": "프리페어 RPA", "routine": "루틴 RPA"}` 바로 아래:

```python
# 이력(대시보드 '기록' 표)에만 남는 프로그램. 현황 카드·실행 단추·날짜별 도넛은 PROGRAMS 만 본다 (2026-09-30 기록기 미리보기)
HISTORY_ONLY = {"recorder": "기록기"}
LABELS = {**PROGRAMS, **HISTORY_ONLY}
```

3. 파일 전체에서 `PROGRAMS.get(program, program)` 두 곳(`record_start_failure`, `start`)을 `LABELS.get(program, program)` 으로.
4. `def program_dir():` 함수 바로 뒤(`def install_root():` 앞)에 - `web_runner._setup_playwright_browsers` 를 옮긴 것:

```python
def setup_playwright_browsers():
    """exe 로 묶였을 때 브라우저가 어디 있는지 알려준다. playwright 를 import 하기 전에 부른다 (프리페어·기록기).

    Chromium 은 압축을 풀면 700MB 가 넘어 exe 안에 넣을 수 없다. exe 옆에 ms-playwright 폴더를 두고 그걸 쓴다
    (개발 중에는 %LOCALAPPDATA%\\ms-playwright). exe 로 묶이면 playwright 가 임시 압축해제 폴더 안의
    .local-browsers 를 브라우저 위치로 착각해 "Executable doesn't exist" 로 죽으니 기본 위치를 직접 알려준다.
    """
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return
    candidate = os.path.join(program_dir(), "ms-playwright")
    if os.path.isdir(candidate):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = candidate
        return
    if packaged():
        default = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright")
        if os.path.isdir(default):
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = default
```

5. `def write_routine_modules(...)` 함수 뒤, `# 프로세스가 살아 있는지 (강제 종료 감지용)` 절 앞에 두 절을 넣는다:

```python
# ---------------------------------------------------------------------------
# 쇼핑몰 프리셋 (기록기가 쓰고, 프리페어가 재생하고, 대시보드가 켠다 - 2026-09-30 설계 5절)
# ---------------------------------------------------------------------------
PRESETS_NAME = "RPA_Presets.json"
PRESET_MIN, PRESET_MAX = 2, 10
REPLAY_ACTION = "replay"                  # web_runner 의 Action 이름
_PRESET_KEY = re.compile(r"(?:PRESET)?(\d+)")


def presets_path():
    """프리셋 파일 자리 - 사용자 설정과 같은 폴더 (시험은 RPA_USER_CONFIG 를 따라온다)."""
    return os.path.join(os.path.dirname(user_config_path()), PRESETS_NAME)


def blank_preset(no):
    return {"no": no, "name": f"프리셋 {no}", "code": "", "saved_at": None, "record": None}


def read_presets():
    """[{no, name, code, saved_at, record}] - 번호는 1부터 빈틈없이, 최소 PRESET_MIN 개. 파일이 없으면 빈 프리셋 둘.
    깨졌으면 ValueError (기록기가 덮어쓰지 않게 - 사람이 고쳐야 한다)."""
    path = presets_path()
    if not os.path.isfile(path):
        return [blank_preset(i + 1) for i in range(PRESET_MIN)]
    data = _read_json(path)
    if not isinstance(data, list):
        raise ValueError(f"{PRESETS_NAME} 가 목록이 아닙니다")
    out = []
    for i, d in enumerate(data[:PRESET_MAX], 1):
        d = d if isinstance(d, dict) else {}
        p = blank_preset(i)
        p.update(name=str(d.get("name") or p["name"]), code=str(d.get("code") or ""), saved_at=d.get("saved_at"),
                 record=d.get("record") if isinstance(d.get("record"), dict) else None)
        out.append(p)
    while len(out) < PRESET_MIN:
        out.append(blank_preset(len(out) + 1))
    return out


def write_presets(presets):
    """프리셋 목록을 통째로 쓴다 (번호는 순서대로 다시 매긴다). PRESET_MIN~PRESET_MAX 개가 아니면 ValueError.
    임시 파일에 다 쓴 뒤 바꿔치기한다 (반쯤 쓴 파일이 남지 않게). 쓴 목록을 돌려준다."""
    if not PRESET_MIN <= len(presets) <= PRESET_MAX:
        raise ValueError(f"프리셋은 {PRESET_MIN}~{PRESET_MAX}개입니다 ({len(presets)}개)")
    data = [{"no": i, "name": str(p.get("name") or f"프리셋 {i}"), "code": str(p.get("code") or ""),
             "saved_at": p.get("saved_at"), "record": p.get("record")} for i, p in enumerate(presets, 1)]
    path = presets_path()
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=1))
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return data


def preset_site_key(no):
    """사용자 설정 Sites 에서 프리셋 no 의 칸 이름."""
    return f"PRESET{no}"


def save_preset_sites(presets, logins):
    """Sites 의 PRESETn 칸을 프리셋에 맞춘다. 다른 섹션·다른 사이트는 그대로 (설정 창·에이전트가 쓴 것).
    presets: read_presets 모양. logins: {번호: (아이디, 비밀번호 또는 None = 저장된 것 그대로)}.
    기록이 있는 프리셋만 칸을 둔다 - 새 칸은 꺼짐(Stts 9), 있던 칸의 켬/끔은 그대로. 기록이 없거나 빠진 번호의 칸은 지운다.
    사용자 설정이 아예 없으면 FileNotFoundError (자격증명 없는 설정을 새로 만들지 않는다 - write_routine_modules 와 같다)."""
    data = read_user_config()
    if not data:
        raise FileNotFoundError(user_config_path())
    sites = data.get(SITES_SECTION) if isinstance(data.get(SITES_SECTION), dict) else {}
    others = {k: v for k, v in sites.items() if not re.fullmatch(r"PRESET\d+", k)}
    mine = {}
    for p in presets:
        if not p.get("record"):
            continue
        key = preset_site_key(p["no"])
        old = sites.get(key) if isinstance(sites.get(key), dict) else {}
        login_id, pw = logins.get(p["no"], (old.get("ID", ""), None))
        mine[key] = {"URL": p["record"].get("start_url") or old.get("URL", ""), "ID": (login_id or "").strip(),
                     "PW": pw or old.get("PW", ""), "Action": [REPLAY_ACTION],
                     "Stts": old.get("Stts", 9) if old else 9, "Preset": p["no"], "note": p["name"]}
    data[SITES_SECTION] = {**others, **mine}       # 프리페어는 이 순서로 돈다 (번호 순)
    write_user_config(data)


def preset_summary():
    """대시보드용 [{no, name, code, steps, saved_at, has_login, on}] - 기록 내용·아이디·비밀번호는 싣지 않는다.
    사용자 설정이 없거나 프리셋 파일이 깨졌으면 None (화면이 카드를 숨긴다 - 빈 목록으로 속이지 않는다)."""
    try:
        cfg = read_user_config()
        if not cfg:
            return None
        presets = read_presets()
    except (ValueError, OSError):
        return None
    sites = cfg.get(SITES_SECTION) if isinstance(cfg.get(SITES_SECTION), dict) else {}
    out = []
    for p in presets:
        site = sites.get(preset_site_key(p["no"]))
        site = site if isinstance(site, dict) else {}
        out.append({"no": p["no"], "name": p["name"], "code": p["code"],
                    "steps": len((p["record"] or {}).get("steps") or []), "saved_at": p["saved_at"],
                    "has_login": bool(site.get("ID")) and bool(site.get("PW")),
                    "on": str(site.get("Stts", "")).strip() == "0"})
    return out


def set_preset_switches(wanted):
    """{키: 켬} 대로 Sites 의 PRESETn 을 켠다(Stts 0)·끈다(9). 키는 "PRESET1"·"1"·1 (대시보드는 "PRESET1" -
    숫자 키는 Realtime DB 가 배열로 바꿔 읽는다). 칸이 있는 번호만 다루고, 바꾼 {번호: 켬} 을 돌려준다.
    아는 번호가 하나도 없으면 ValueError. 켜기는 기록·아이디·비밀번호가 다 있는 것만 (아니면 ValueError, 아무것도 안 바꿈)."""
    data = read_user_config()
    if not data:
        raise FileNotFoundError(user_config_path())
    sites = data.get(SITES_SECTION) if isinstance(data.get(SITES_SECTION), dict) else {}
    final = {}
    for k, v in (wanted or {}).items():
        m = _PRESET_KEY.fullmatch(str(k))
        if m and isinstance(sites.get(preset_site_key(int(m.group(1)))), dict):
            final[int(m.group(1))] = bool(v)
    if not final:
        raise ValueError("아는 프리셋이 없습니다")
    ready = {s["no"] for s in (preset_summary() or []) if s["steps"] and s["has_login"]}
    blocked = sorted(no for no, on in final.items() if on and no not in ready)
    if blocked:
        raise ValueError(f"기록이나 아이디·비밀번호가 없어 켤 수 없습니다: {', '.join(str(n) for n in blocked)}번")
    for no, on in final.items():
        sites[preset_site_key(no)]["Stts"] = 0 if on else 9
    write_user_config(data)
    return final


# ---------------------------------------------------------------------------
# 관리자 권한과 윈도우 계정 (설정 창·기록기가 같이 쓴다)
# ---------------------------------------------------------------------------
def is_admin():
    try:
        return bool(ctypes.WinDLL("shell32").IsUserAnAdmin())
    except Exception:
        return False


def run_as_admin(exe, args, cwd):
    """exe 를 관리자 권한으로 띄운다 (UAC 요청). 띄웠으면 True, 사용자가 거절하면 False."""
    sh = ctypes.WinDLL("shell32")
    sh.ShellExecuteW.restype = ctypes.c_void_p
    sh.ShellExecuteW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
                                 ctypes.c_wchar_p, ctypes.c_int)
    return (sh.ShellExecuteW(None, "runas", exe, subprocess.list2cmdline(list(args)), cwd, 1) or 0) > 32
```

그리고 `rpa_settings.py` 의 `def process_user():`, `def session_user():`, `def same_account(a, b):` 세 함수를 **본문 그대로 복사해** 위 `run_as_admin` 아래에 붙인다 (설명 글도 그대로. 설정 창 쪽 원본은 다음 단계에서 통째로 바꾼다).

- [ ] **Step 4: 설정 창이 옮긴 함수를 쓰게 (`rpa_settings.py`)**

`def is_admin():` 부터 `def same_account(a, b): return …` 까지(`relaunch_as_admin` 포함)를 이것으로 바꾼다:

```python
# 관리자·계정 확인은 기록기도 쓴다 - rpa_status 에 있다 (시험은 이 모듈의 이름을 바꿔 끼운다)
is_admin, process_user, session_user, same_account = st.is_admin, st.process_user, st.session_user, st.same_account


def relaunch_as_admin(args):
    """관리자 권한으로 자기를 다시 띄운다 (UAC 요청). 띄웠으면 True, 사용자가 거절하면 False."""
    return st.run_as_admin(sys.executable, [os.path.abspath(__file__), *args], HERE)
```

(이 줄은 `import rpa_status as st` 보다 뒤여야 한다. 그 import 는 파일 윗부분에 있다.)

- [ ] **Step 5: 통과를 확인한다**

Run: `.venv\Scripts\python.exe tests\test_presets.py`
Expected: `실패: 없음` (1·2·3절).
Run: `.venv\Scripts\python.exe tests\test_settings.py` 와 `.venv\Scripts\python.exe tests\check_settings_ui.py`
Expected: 둘 다 `실패: 없음` (옮긴 함수를 설정 창 이름으로 바꿔 끼우는 시험이 그대로 통한다).
Run: `.venv\Scripts\python.exe tests\test_layout.py` 와 `.venv\Scripts\python.exe tests\test_dashboard_modules.py`
Expected: `실패: 없음`.

- [ ] **Step 6: graphify·변경 확인**

Run: `graphify update .`, `git status --short`
제안 커밋: `프리셋: 파일·Sites 칸·요약·켬끔을 rpa_status 에, 기록기 이력 이름, 관리자·계정 확인을 설정 창과 같이`.

---

### Task 3: 프리페어 `replay` (`web_runner.py`)

**Files:**
- Modify: `web_runner.py` (29~57줄 `_setup_playwright_browsers`, import, `validate_site`, `ACTION_LABELS`·`ACTIONS`, `prepare_steps`)
- Modify: `tests/test_presets.py` (4절)

**Interfaces:**
- Consumes: Task 1 `web_replay.Replayer(…, hide_values=True, shot_dir=…)` + `first_page`·`fit_viewport`; Task 2 `status.read_presets()`, `status.REPLAY_ACTION`, `status.setup_playwright_browsers()`, `status.save_preset_sites`, `status.set_preset_switches`
- Produces: `web_runner.action_replay(page, name, site) -> True`, `web_runner._replay_problems(name, site) -> list[str]`, `ACTION_LABELS["replay"] = "엑셀 받기"`, `prepare_steps` 의 replay 단계 이름 `"<note> 엑셀 받기"`

- [ ] **Step 1: 실패하는 시험을 쓴다**

`tests/test_presets.py` 끝의 `print()` / `print(f"실패: …")` / `sys.exit(…)` 세 줄 **앞에** 넣는다:

```python
print("=== 4. 프리페어 replay (web_runner) ===")
import fake_mall  # noqa: E402
import web_replay  # noqa: E402
import web_runner as wr  # noqa: E402
from test_web_replay import hclick  # noqa: E402

TODAY = datetime.date.today()
site = dict(st.read_user_config()["Sites"]["PRESET1"])
check("점검: 기록·코드가 있으면 문제 없음", wr.validate_site("PRESET1", site) == [], str(wr.validate_site("PRESET1", site)))
check("점검: 없는 프리셋 번호는 문제", any("기록이 없습니다" in x for x in wr.validate_site("PRESET1", dict(site, Preset=5))))
bad = st.read_presets()
bad[0]["code"] = "12"
st.write_presets(bad)
check("점검: 사이트코드가 세 자리가 아니면 문제", any("세 자리" in x for x in wr.validate_site("PRESET1", site)))
with open(st.presets_path(), "w", encoding="utf-8") as f:
    f.write("[깨진")
check("점검: 프리셋 파일이 깨졌으면 문제로 적는다", any("읽지 못했습니다" in x for x in wr.validate_site("PRESET1", site)))
check("대시보드 단계 이름은 '<프리셋 이름> 엑셀 받기'",
      wr.prepare_steps([("PRESET1", dict(site, note="지마켓"))]) == [("PRESET1:replay", "지마켓 엑셀 받기")])

srv, url, _ = fake_mall.start(TODAY, False)
srv.mall = mall = fake_mall.Mall(TODAY, False)


def human_e(page):
    hclick(page, page.get_by_placeholder("아이디"))
    page.keyboard.type(fake_mall.USER, delay=15)
    hclick(page, page.get_by_placeholder("비밀번호"))
    page.keyboard.type(fake_mall.PASSWORD, delay=15)
    hclick(page, page.get_by_role("button", name="로그인", exact=True))
    page.wait_for_url("**/main**")
    page.get_by_role("link", name="배송관리", exact=True).hover()
    hclick(page, page.get_by_role("link", name="송장전송", exact=True))
    fl = page.frame_locator("iframe[name=content]")
    with page.expect_download() as di:
        hclick(page, fl.get_by_role("button", name="송장 엑셀 받기", exact=True))
    di.value.path()


rec_e = web_replay.record(url + "/login", os.path.join(TMP, "rec_e.json"), headless=True, human=human_e, record_date=TODAY)
st.write_presets([{"no": 1, "name": "가짜몰", "code": "012", "saved_at": None, "record": rec_e}, st.blank_preset(2)])
st.save_preset_sites(st.read_presets(), {1: (fake_mall.USER, fake_mall.PASSWORD)})
st.set_preset_switches({"PRESET1": True})
DL = os.path.join(TMP, "ERPIA_AI_EXCEL")
wr.download_dir = lambda: DL           # 진짜 바탕화면 ERPIA_AI_EXCEL 대신
srv.mall = mall = fake_mall.Mall(TODAY, False)
code = wr.cmd_run(["PRESET1"], headless=True)
files = sorted(os.listdir(DL)) if os.path.isdir(DL) else []
check("프리페어가 켜진 프리셋을 재생해 (012)… 를 받는다", code == 0 and files == [f"(012)송장목록_{TODAY.isoformat()}.xlsx"]
      and mall.ship_downloads == [TODAY.isoformat()], str((code, files)))
row = st.read_history(program="prepare")[0]
check("이력: 단계 '가짜몰 엑셀 받기' 성공", [(s["label"], s["state"]) for s in row["steps"]] == [("가짜몰 엑셀 받기", "done")],
      str(row["steps"]))
logs = "\n".join(row["log_tail"])
check("이력 로그에 아이디·비밀번호가 없다", fake_mall.USER not in logs and fake_mall.PASSWORD not in logs, logs[-400:])
srv.mall = mall = fake_mall.Mall(TODAY, False)
cfg = st.read_user_config()
cfg["Sites"]["PRESET1"]["PW"] = "wrong-pw"
st.write_user_config(cfg)
code = wr.cmd_run(["PRESET1"], headless=True)
row = st.read_history(program="prepare")[0]
check("비밀번호가 틀리면 그 단계 실패로 끝나고 사유가 남는다", code == 1 and row["state"] != "success"
      and "단계에서 멈췄습니다" in (row["steps"][0].get("note") or ""), str(row["steps"]))
check("실패 사진은 받은 파일 폴더가 아니라 기록 폴더", not any(n.endswith(".png") for n in os.listdir(DL))
      and any(n.startswith("실패_") for n in os.listdir(wr.BASE_DIR)), str(os.listdir(DL)))
srv.shutdown()
```

- [ ] **Step 2: 실패를 확인한다**

Run: `.venv\Scripts\python.exe tests\test_presets.py`
Expected: 4절 첫 줄들이 `[실패]` (`모르는 Action 'replay'` 가 문제로 나온다), 끝까지 가면 cmd_run 이 1.

- [ ] **Step 3: 구현 (`web_runner.py`)**

1. import 줄에 `import re` 를 더한다 (`import os` 다음).
2. `def _setup_playwright_browsers():` 부터 그 아래 호출 줄 `_setup_playwright_browsers()` 까지(29~57줄)를 이것으로:

```python
# exe 로 묶였을 때 브라우저 자리 (playwright 를 import 하기 전에). 기록기와 같이 쓴다 - rpa_status 에 있다
status.setup_playwright_browsers()
```

3. `validate_site` 안, `for a in acts:` 로 모르는 Action 을 거르는 두 줄 바로 뒤에:

```python
    if status.REPLAY_ACTION in acts:
        problems += _replay_problems(name, site)
```

그리고 `validate_site` 바로 앞에 이 함수를 둔다:

```python
def _replay_problems(name, site):
    """replay 칸의 프리셋이 재생할 수 있는 것인가 (기록기에서 기록·저장했나, 사이트코드)."""
    no = site.get("Preset")
    try:
        p = next((x for x in status.read_presets() if x["no"] == no), None)
    except ValueError as e:
        return [f"{name}: 프리셋 파일을 읽지 못했습니다 ({e})"]
    if p is None or not p.get("record"):
        return [f"{name}: 프리셋 {no} 의 기록이 없습니다 (기록기에서 기록하고 저장하세요)"]
    if not re.fullmatch(r"\d{3}", p.get("code") or ""):
        return [f"{name}: 프리셋 {no} 의 사이트코드가 숫자 세 자리가 아닙니다 ({p.get('code')!r})"]
    return []
```

4. `# 대시보드에 보여줄 Action 이름` 주석 바로 앞에:

```python
def action_replay(page, name, site):
    """기록기로 기록한 프리셋을 재생해 엑셀을 받는다. 받은 파일은 (사이트코드)원래이름 으로 ERPIA_AI_EXCEL 에.
    로그에는 칸에 친 값·주소 ? 뒤를 싣지 않는다 (대시보드로 간다). 실패 사진은 기록 폴더에 (받은 파일 폴더가 아니라)."""
    import web_replay
    problems = _replay_problems(name, site)
    if problems:
        raise RuntimeError(problems[0])
    p = next(x for x in status.read_presets() if x["no"] == site.get("Preset"))
    dest = download_dir()
    log(f"  [{name}] 프리셋 {p['no']} '{p['name']}' 재생 ({len(p['record']['steps'])}단계) → {dest}")
    rp = web_replay.Replayer(page.context, p["record"], {"ID": site["ID"], "PW": site["PW"]}, dest, p["code"],
                             log=log, hide_values=True, shot_dir=BASE_DIR)
    rp.first_page = page
    rp.fit_viewport = True
    ok = rp.run()
    status.metric(f"{name}:files", "받은 엑셀", len(rp.saved), unit="개")
    if not ok:
        i, _, why = rp.results[-1] if rp.results else (0, "fail", "알 수 없음")
        raise RuntimeError(f"{i}단계에서 멈췄습니다: {why}")
    log(f"  [{name}] 받은 파일: {', '.join(os.path.basename(x) for x in rp.saved) or '없음'}")
    return True
```

5. `ACTION_LABELS` 에 `"replay": "엑셀 받기",`, `ACTIONS` 에 `"replay": action_replay,` 를 더한다.
6. `prepare_steps` 의 반복 안을 이것으로:

```python
    for name, site in chosen:
        for act in site_actions(site):
            label = ACTION_LABELS.get(act, act)
            if act == status.REPLAY_ACTION:     # 칸 이름(PRESET1) 대신 프리셋 이름
                out.append((step_key(name, act), f"{site.get('note') or name} {label}"))
            else:
                out.append((step_key(name, act), f"{name} {label}" if many else label))
    return out
```

- [ ] **Step 4: 통과를 확인한다**

Run: `.venv\Scripts\python.exe tests\test_presets.py`
Expected: `실패: 없음` (4절 포함, 틀린 비밀번호 줄에서 30초쯤 기다린다).
Run: `.venv\Scripts\python.exe web_runner.py --selftest --headless`
Expected: `자체 테스트 통과`.
Run: `.venv\Scripts\python.exe tests\test_layout.py`
Expected: `실패: 없음` (web_runner 를 부르는 자리 찾기 시험).

- [ ] **Step 5: graphify·변경 확인**

제안 커밋: `프리페어: Action replay - 켜진 프리셋을 재생해 (사이트코드)이름 으로 ERPIA_AI_EXCEL, 로그에 값 없음, 점검`.

---

### Task 4: 기록기 창 `rpa_recorder.py`

**Files:**
- Create: `rpa_recorder.py` (spike `rec_app.py` 를 옮기고 고친다)
- Create: `tests/check_recorder_ui.py`
- Modify: `tests/test_presets.py` (5절)

**Interfaces:**
- Consumes: Task 1 `web_replay` 전부 (`Recorder`, `finalize(…, viewport=)`, `keep_steps`, `describe(…, hide_values=True)`, `Replayer` + `cancel`); Task 2 `st.read_presets`, `st.write_presets`, `st.save_preset_sites`, `st.presets_path`, `st.preset_site_key`, `st.read_user_config`, `st.SITES_SECTION`, `st.unseal`, `st.data_dir`, `st.program_dir`, `st.packaged`, `st.setup_playwright_browsers`, `st.is_admin`, `st.run_as_admin`, `st.process_user`, `st.session_user`, `st.same_account`, `st.start`/`step`/`note`/`fail_step`/`log_line`/`finish`
- Produces: `rpa_recorder.main(argv=None) -> int`, `check() -> 0`, `CHECK_DONE = "기록기 점검 끝"`, `APP_ID = "AFTERMARKET.RPA.Recorder"`, `ICON_NAME = "AFTER_MARKET_PREPARE.ico"`, `load_presets() -> list[dict]` (`ValueError`), `validate_presets(presets) -> (no, 문장) | None`, `start_problem(me=None, session=None) -> str | None`, `self_command(args) -> (exe, list)`, `stored_password(no) -> str`, `new_root()`, `dpi_scale()`, `frame_rect(hwnd)`, `App(root, scale, presets, hint="", fake_creds=None)` (시험 고리 `on_ready`·`on_recording`·`on_stopped`·`on_human_done`·`on_preview_done`), 모듈 이름 `rec` (= `web_replay`)

- [ ] **Step 1: 옮기기**

```powershell
Copy-Item D:\AX\spike_rec_2026-09-30\rec_app.py D:\AX\RPA\rpa_recorder.py
```

- [ ] **Step 2: 실패하는 시험을 쓴다 (`tests/test_presets.py` 5절)**

끝의 세 줄 앞에 넣는다:

```python
print("=== 5. 기록기 저장 전 확인 (rpa_recorder) ===")
import rpa_recorder as rr  # noqa: E402

R = {"steps": [{"kind": "goto"}]}


def P(no, code="012", login="seller01", pw="", has_pw=True, record=R):
    return {"no": no, "name": f"몰{no}", "code": code, "id": login, "pw": pw, "has_pw": has_pw, "record": record}


check("문제 없으면 None", rr.validate_presets([P(1), P(2, code="013"), P(3, code="", record=None)]) is None)
check("사이트코드가 세 자리가 아니면 그 프리셋에서 막는다", (rr.validate_presets([P(1), P(2, code="13")]) or (0, ""))[0] == 2)
dup = rr.validate_presets([P(1), P(2, code="012")])
check("두 프리셋이 같은 사이트코드면 막는다 (루틴은 한 코드에 파일 하나 - Review Focus 2)", bool(dup) and dup[0] == 2
      and "012" in dup[1], str(dup))
check("아이디가 없으면 막는다", (rr.validate_presets([P(1, login=" ")]) or (0, ""))[0] == 1)
check("비밀번호가 저장돼 있지도 않고 치지도 않았으면 막는다", (rr.validate_presets([P(1, has_pw=False)]) or (0, ""))[0] == 1
      and rr.validate_presets([P(1, has_pw=False, pw="x")]) is None)
check("다른 계정의 관리자 권한이면 멈춘다 (비밀번호가 그 계정으로 잠긴다)",
      "PC\\b" in (rr.start_problem(me="PC\\a", session="PC\\b") or "") and rr.start_problem(me="PC\\a", session="pc\\A") is None)
exe, params = rr.self_command(["--x"])
check("소스로 돌 때 다시 띄우기는 파이썬 + 이 파일", exe == sys.executable and params[0].endswith("rpa_recorder.py")
      and params[1:] == ["--x"])
r = subprocess.run([sys.executable, str(ROOT / "rpa_recorder.py"), "--check"], capture_output=True, env=dict(os.environ),
                   timeout=120)
out = (r.stdout + r.stderr).decode("utf-8", "replace")
check("--check 는 창 없이 끝 줄을 찍고 관리자 권한을 묻지 않는다", r.returncode == 0 and rr.CHECK_DONE in out, out[-400:])
with open(st.presets_path(), "w", encoding="utf-8") as f:
    f.write("{깨진")
check("깨진 프리셋 파일이면 기록기는 열지 않는다 (덮어쓰지 않게 - Review Focus 1)", raises(ValueError, rr.load_presets))
```

Run: `.venv\Scripts\python.exe tests\test_presets.py`
Expected: 5절에서 `ModuleNotFoundError: No module named 'rec'` (복사한 spike 파일이 아직 spike 엔진 이름을 부른다) 로 멈춘다.

- [ ] **Step 3: 머리·상수 (`rpa_recorder.py`)**

1. 맨 위 설명을 이것으로:

```python
# -*- coding: utf-8 -*-
r"""쇼핑몰 기록기 - 왼쪽 브라우저(주소줄 있음), 오른쪽 프리셋 ①~⑩ 과 사람이 한 조작 목록, 아래 미리보기·저장.

    시작 메뉴 '쇼핑몰 기록기' (Prepare_Recorder.exe). 켤 때 관리자 권한을 묻는다 (설정 폴더는 관리자만 고칠 수 있다).
    Prepare_Recorder.exe --check      창 없이 확인하고 끝 줄 '기록기 점검 끝' (빌드·샌드박스)
    .venv\Scripts\python.exe rpa_recorder.py   개발 PC 에서는 RPA_USER_CONFIG·RPA_PROGRAMDATA 로 시험 폴더를 가리킨 채로만

프리셋마다 '로그인 ~ 엑셀 받기' 기록 하나 → 사용자 설정 옆 RPA_Presets.json (rpa_status.read_presets/write_presets).
아이디·비밀번호는 사용자 설정 Sites 의 PRESETn 칸에 (비밀번호는 쓰는 순간 잠긴다, rpa_status.save_preset_sites).
설계: docs/superpowers/specs/2026-09-30-shop-record-replay-design.md 4절. 화면 시험: tests/check_recorder_ui.py
브라우저를 이 창 속에 끼우지 않는다 (SetParent 로 끼우면 한글 입력·포커스가 흔들린다). 기록 창 왼쪽에 붙여 두고 같이 옮긴다.
Playwright 는 한 스레드에서만 부를 수 있어 일꾼 스레드가 브라우저를 모두 맡고, 화면(tkinter)과는 큐로만 주고받는다.
"""
```

2. import 에서 `from playwright.sync_api import sync_playwright`, `import fake_mall`, `import rec` 세 줄을 지우고 `from tkinter import messagebox` 아래에:

```python
import rpa_status as st

st.setup_playwright_browsers()                     # playwright 를 부르기 전에 (exe 로 묶이면 브라우저 자리를 알려 줘야 한다)

from playwright.sync_api import sync_playwright    # noqa: E402

import web_replay as rec                           # noqa: E402
```

3. 상수 `HERE`·`OUT`·`PRESET_FILE`·`MIN_PRESETS, MAX_PRESETS = 2, 10` 네 줄을 이것으로:

```python
REC_DIR = os.path.join(st.data_dir(), "기록기")          # 기록·미리보기로 받은 파일 (루틴이 읽는 ERPIA_AI_EXCEL 이 아니다)
RECORD_DL = os.path.join(REC_DIR, "기록")
PREVIEW_DL = os.path.join(REC_DIR, "미리보기")
MIN_PRESETS, MAX_PRESETS = st.PRESET_MIN, st.PRESET_MAX
APP_ID = "AFTERMARKET.RPA.Recorder"                     # 작업 표시줄 묶음 이름. 시작 메뉴 바로 가기(installer.iss)와 같아야 한다
ICON_NAME = "AFTER_MARKET_PREPARE.ico"                  # 주황 A (tools/make_icon.py)
CHECK_DONE = "기록기 점검 끝"                              # --check 끝 줄 (build_release.MARKERS·sandbox_inner.ps1)
```

- [ ] **Step 4: 일꾼 (`class Worker`)**

1. `__init__` 을:

```python
    def __init__(self, bounds, ui, hint):
        super().__init__(daemon=True)
        self.bounds, self.ui, self.hint, self.cmd = bounds, ui, hint, queue.Queue()
        self.ctx = self.prof = self.page = self.recorder = None
        self.rec_no = None
        self.cancel = threading.Event()   # 기록기 창을 닫으면 켠다 - 미리보기가 다음 단계 전에 멈춘다
        self.human = None                 # 시험: 사람 대신 조작할 함수
```

2. `_do_record` 안 `os.path.join(OUT, "기록때_받은파일")` 을 `RECORD_DL` 로, `self._set_bounds(self.page, self.bounds)` 다음 줄에 `self.rec_no = no` 를, `self.ui.put(("recording", no))` 앞에 `self._send_viewport()` 를 넣는다. 그리고 `_do_record` 아래에:

```python
    def _send_viewport(self):
        """기록 창 브라우저의 안쪽 크기 - 기록에 넣어 프리페어가 같은 크기로 연다."""
        try:
            self.page.wait_for_timeout(200)          # 창 크기를 바꾼 뒤 그려질 틈
            vp = self.page.evaluate("() => ({width: innerWidth, height: innerHeight})")
            self.ui.put(("viewport", self.rec_no, vp))
        except Exception:
            pass
```

3. `_do_dock` 을:

```python
    def _do_dock(self, b):
        self.bounds = b
        if self.page and not self.page.is_closed():
            self._set_bounds(self.page, b)
            self._send_viewport()
```

4. `_do_preview` 를 통째로:

```python
    def _do_preview(self, record, ids, creds, code, label):
        """새 프로필 브라우저로 켜 둔 단계를 따라 한다. 한 번 할 때마다 상태 기록 'recorder' 한 건 (대시보드 '기록').
        로그에는 칸에 친 값·주소 ? 뒤를 싣지 않는다."""
        where = self._rec_bounds()
        self.cancel.clear()
        stamp = lambda: datetime.datetime.now().strftime("[%H:%M:%S]")   # noqa: E731
        steps = record["steps"]
        st.start("recorder", [(f"s{i}", rec.describe(s, hide_values=True)) for i, s in enumerate(steps, 1)], title=label)
        st.log_line(f"{stamp()} === 미리보기: {label} ({len(steps)}단계) ===")
        ok, why, saved, sec = False, "미리보기가 끝까지 가지 못했습니다", [], 0.0
        ctx, prof = launch(self.p, slow_mo=120)     # 새 프로필 = RPA 가 혼자 돌 때처럼 로그아웃 상태
        try:
            rp = rec.Replayer(ctx, record, creds, PREVIEW_DL, code, review=True, hide_values=True,
                              log=lambda m: st.log_line(f"{stamp()} {m}"), step_timeout=20)
            rp.first_page = ctx.pages[0] if ctx.pages else None
            rp.page_hook = lambda pg: self._set_bounds(pg, where)               # 기록 창 자리에 겹쳐 띄운다
            rp.cancel = self.cancel

            def progress(i, state, how):
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
            if not ok and rp.results:
                i, _, how = rp.results[-1]
                why = f"{i}단계에서 멈췄습니다: {how}"
            st.log_line(f"{stamp()} {'미리보기 성공' if ok else '미리보기 멈춤'} ({sec:.0f}초) - 받은 파일: "
                        f"{', '.join(saved) or '없음'}")
            if ctx.pages and not self.cancel.is_set():
                ctx.pages[0].wait_for_timeout(1500)
        except Exception as e:
            why = f"{type(e).__name__}: {str(e).splitlines()[0]}"
            st.log_line(f"{stamp()} 미리보기 오류: {why}")
        finally:
            st.finish("success" if ok else "stopped", None if ok else why)
            try:
                ctx.close()
            except Exception:
                pass
            shutil.rmtree(prof, ignore_errors=True)
            self.ui.put(("preview_done", ok, saved, sec))
```

- [ ] **Step 5: 프리셋 불러오기·저장 전 확인 (모듈 함수)**

`def new_preset(…)` 과 `def load_presets():` 를 통째로 바꾸고, 그 아래에 둘을 더한다:

```python
def new_preset(no, name=None, code=""):
    """화면이 들고 있는 프리셋 하나. raw = 이번에 기록한 단계, loaded = 저장돼 있던 기록 (둘 중 하나)."""
    return {"name": name or f"프리셋 {no}", "code": code, "raw": [], "loaded": None, "start_url": None,
            "enabled": {}, "deleted": set(), "id": "", "pw": "", "has_pw": False, "saved_at": None, "viewport": None}


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
```

- [ ] **Step 6: 화면 (`class App`)**

1. `__init__` 머리를:

```python
class App:
    def __init__(self, root, scale, presets, hint="", fake_creds=None):
        self.root, self.scale = root, scale
        self.presets = presets
        if fake_creds and not any(p["loaded"] for p in self.presets):      # 시험: 가짜 쇼핑몰 계정
            self.presets[0].update(name="가짜 쇼핑몰", code="012", id=fake_creds[0], pw=fake_creds[1])
```

(그 아래 `self.cur, self.recording, …` 부터는 그대로.) `root.title("AFTER MARKET - 사용자 행위 기록 (시험판)")` 은 `root.title("AFTER MARKET - 쇼핑몰 기록기")` 로.

2. `_build` 안의 안내 글 두 줄

```python
        tk.Label(bot, text="아이디·비밀번호는 미리보기에만 씁니다. 기록 파일에는 넣지 않습니다.", font=F_SMALL, bg=BG,
                 fg=MUTED).pack(anchor="w", pady=(3, 8))
```

을:

```python
        self.pw_hint = tk.Label(bot, text="", font=F_SMALL, bg=BG, fg=MUTED, anchor="w", justify="left",
                                wraplength=self.panel_w - 2 * pad)
        self.pw_hint.pack(fill="x", pady=(3, 8))
```

3. `_load_fields` 끝(`self._loading = False` 다음)에:

```python
        self.pw_hint.config(text=("저장된 비밀번호가 있습니다 - 바꿀 때만 넣으세요. " if p["has_pw"] else "")
                            + "아이디·비밀번호는 저장하면 이 PC 의 설정에 잠가서 넣습니다. 기록 파일·대시보드에는 안 갑니다.")
```

4. `_final` 의 `return rec.finalize(json.loads(json.dumps(p["raw"])), datetime.date.today(), start)` 를 `return rec.finalize(json.loads(json.dumps(p["raw"])), datetime.date.today(), start, viewport=p["viewport"])` 로.

5. `preview` 를 통째로:

```python
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
        self.previewing = True
        self.paint_buttons()
        self.msg.config(text="미리보기 중 - 새 브라우저가 같은 자리에서 따라 합니다. 보기만 하세요", fg=BLUE)
        self.worker.cmd.put(("preview", r, ids, {"ID": p["id"].strip(), "PW": pw}, p["code"] or "000",
                             f"{circled(self.cur + 1)} {p['name']}"))
```

6. `save` 를 통째로:

```python
    def save(self):
        self._store_fields()
        try:
            has_config = bool(st.read_user_config())
        except ValueError as e:
            return self.msg.config(text=f"사용자 설정을 읽지 못했습니다: {e}", fg=RED)
        if not has_config:
            return self.msg.config(text="이 PC 의 사용자 설정이 없습니다 - 시작 메뉴 'RPA 설정' 에서 먼저 저장하세요", fg=RED)
        now = datetime.datetime.now().isoformat(timespec="seconds")
        out = []
        for no, p in enumerate(self.presets, 1):
            final, r = self._final(p), None
            if final and final["steps"]:
                r = rec.keep_steps(final, self._kept(p, final))
                for s in r["steps"]:
                    s.pop("id", None)
            out.append({"no": no, "name": p["name"], "code": p["code"], "saved_at": now if r else None, "record": r,
                        "id": p["id"], "pw": p["pw"], "has_pw": p["has_pw"]})
        problem = validate_presets(out)
        if problem:
            self.select(problem[0] - 1)
            return self.msg.config(text=problem[1], fg=RED)
        files = [{k: o[k] for k in ("no", "name", "code", "saved_at", "record")} for o in out]
        text = json.dumps(files, ensure_ascii=False)
        for o in out:
            pw = o["pw"] or (stored_password(o["no"]) if o["has_pw"] else "")
            if pw and pw in text:        # 비밀번호 칸이 아닌 곳에 비밀번호를 친 경우
                self.select(o["no"] - 1)
                return self.msg.config(text=f"{circled(o['no'])} 기록에 비밀번호로 보이는 글자가 있어 저장하지 않았습니다 - "
                                            "그 단계를 지우세요", fg=RED)
        st.write_presets(files)
        st.save_preset_sites(files, {o["no"]: (o["id"].strip(), o["pw"] or None) for o in out if o["record"]})
        for p, o in zip(self.presets, out):
            if o["record"]:
                p.update(pw="", has_pw=True, saved_at=o["saved_at"])
        self._load_fields()
        n = sum(1 for o in out if o["record"])
        self.msg.config(text=f"저장했습니다 - 기록 있는 프리셋 {n}개. 새 프리셋은 꺼진 채입니다: 대시보드 환경설정 "
                             "'쇼핑몰 프리셋' 에서 켜면 다음 프리페어부터 돕니다.", fg=GREEN_D)
        return st.presets_path()
```

7. `_poll` 의 `elif m[0] == "status":` 앞에:

```python
                elif m[0] == "viewport":
                    self.presets[m[1]]["viewport"] = m[2]
```

8. `quit` 을:

```python
    def quit(self):
        self.worker.cancel.set()           # 미리보기 중이면 다음 단계 전에 멈춘다 (Review Focus 4)
        self.worker.cmd.put(("quit",))
        self.worker.join(timeout=30)       # 지금 단계가 끝나기를 (단계 기다림 최대 20초)
        self.root.destroy()
```

- [ ] **Step 7: 시작·확인·창 없는 모드 (모듈 끝)**

`def selftest(app, mall, host):` 부터 파일 끝까지를 지우고 이것으로:

```python
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
        return (f"이 PC 에 로그인한 윈도우 계정({session})이 아니라 다른 계정({me})의 관리자 권한으로 기록기가 떴습니다.\n"
                f"비밀번호는 윈도우 계정마다 잠겨서 다른 계정으로 저장하면 RPA 가 풀지 못합니다. {session} 계정으로 다시 여세요.")
    return None


def show_error(text):
    ctypes.windll.user32.MessageBoxW(None, text, "쇼핑몰 기록기", 0x10)


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
    argv = sys.argv[1:] if argv is None else list(argv)
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8")        # 콘솔 없는 exe 를 시작 메뉴로 켜면 stdout 이 없다
    ap = argparse.ArgumentParser(description="쇼핑몰 기록기")
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
    problem = start_problem()
    if problem:
        show_error(problem)
        return 1
    try:
        presets = load_presets()
    except ValueError as e:
        show_error(f"설정을 읽지 못해 기록기를 열지 않습니다 (덮어쓰지 않게).\n{st.presets_path()}\n{e}\n"
                   "고치거나 지운 뒤 다시 여세요.")
        return 1
    scale = dpi_scale()
    root = new_root()
    App(root, scale, presets)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 8: 시험 5절 통과**

Run: `.venv\Scripts\python.exe tests\test_presets.py`
Expected: `실패: 없음`.
Run: `.venv\Scripts\python.exe -m py_compile rpa_recorder.py` 와 `Select-String -Path rpa_recorder.py -Pattern "\bOUT\b|PRESET_FILE|fake_mall|selftest"`
Expected: 컴파일 오류 없음, 남은 spike 이름 없음 (찾기 결과 빈 줄).

- [ ] **Step 9: 화면 시험을 쓴다**

Create `tests/check_recorder_ui.py`:

```python
# -*- coding: utf-8 -*-
"""기록기 화면 시험 - 진짜 창을 띄워 혼자 주소 치기 → 기록 → 단계 지우기·끄기 → 기록 끝 → 미리보기 → 저장을 하고 사진을 남긴다.
2~3분 동안 마우스·키보드를 쓴다 (주소줄은 pywinauto 로 친다). 임시 설정으로만 돈다 (진짜 설정은 안 건드린다).
    .venv\\Scripts\\python.exe tests\\check_recorder_ui.py [사진 폴더]
"""
import datetime
import json
import os
import sys
import tempfile
import time
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="rpa_recorder_ui_")
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
import rpa_recorder as rr  # noqa: E402
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
    row = (st.read_history(program="recorder") or [{}])[0]
    logs = "\n".join(row.get("log_tail") or [])
    check("대시보드 기록에 '기록기' 미리보기 한 줄 (성공)", row.get("program_label") == "기록기" and row.get("state") == "success",
          str(row)[:300])
    check("그 로그에는 칸에 친 값·아이디·비밀번호가 없다", "주문 처리" not in logs and fake_mall.USER not in logs
          and fake_mall.PASSWORD not in logs, logs[-500:])
    pv = os.path.join(st.data_dir(), "기록기", "미리보기")
    check("미리보기로 받은 파일은 기록 폴더 (ERPIA_AI_EXCEL 아님)", os.path.isdir(pv) and any(n.startswith("(012)") for n in os.listdir(pv)))
    check("프리셋은 10개까지 - 10개면 [+] 가 없다", result.get("ten") == (10, False), str(result.get("ten")))
    print(f"사진: {SHOTS}")
    print("실패:", fails or "없음")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 10: 화면 시험을 돌린다**

Run: `.venv\Scripts\python.exe tests\check_recorder_ui.py`
Expected: `실패: 없음` (2~3분, 그동안 마우스·키보드를 건드리지 않는다). 사진 넷(`0_안내`·`1_기록`·`2_미리보기`·`3_끝`)을 열어 창 모양·주황 아이콘(제목 줄)·기록 목록을 눈으로 본다.

- [ ] **Step 11: graphify·변경 확인**

제안 커밋: `기록기 rpa_recorder - 프리셋을 설정 폴더·Sites 에, 미리보기는 대시보드 기록 '기록기', 관리자·계정 확인, --check`.

---

### Task 5: 빌드·설치·샌드박스

**Files:**
- Modify: `tools/build_release.py` (`EXES`, `MARKERS`, `NUITKA_COMMON`, `NUITKA_EXTRA`, `build_exes`, `reuse_exes`, `main`)
- Modify: `tests/test_build_release.py`
- Modify: `release/installer.iss` (`[Icons]`)
- Modify: `tools/sandbox_inner.ps1`

**Interfaces:**
- Consumes: Task 4 `rpa_recorder.py` (`--check` → `기록기 점검 끝`, `APP_ID = "AFTERMARKET.RPA.Recorder"`), Task 0 `ICON_PREPARE`
- Produces: `build_release.EXES["Prepare_Recorder.exe"] = "rpa_recorder.py"`, `MARKERS["Prepare_Recorder.exe"] = "기록기 점검 끝"`, `TK_PLUGIN = "--enable-plugin=tk-inter"`, `PLAYWRIGHT = [...]`, `tcl_tk_dirs(dest) -> (tcl, tk)`, `nuitka_command(py, exe, work_dir, tk_dirs=None) -> list[str]`, `build_exes(builder, work_dir, only=None) -> str`

- [ ] **Step 1: 실패하는 시험을 쓴다 (`tests/test_build_release.py`)**

1. Task 0 에서 넣은 아이콘 확인의 기대값을 셋으로:

```python
check("아이콘: 루틴 exe 는 크림 A, 프리페어·기록기 exe 는 주황 A 한 벌씩, 주황 ico 도 판에 들어간다 (2026-09-30 사용자가 고른 '나')",
      icon_opts == {"ERPia_RPA.exe": [f"--windows-icon-from-ico={br.ICON}"],
                    "Prepare_RPA.exe": [f"--windows-icon-from-ico={prep}"],
                    "Prepare_Recorder.exe": [f"--windows-icon-from-ico={prep}"]}
      and os.path.isfile(prep) and br.icon_resources(prep)[1]
      and open(prep, "rb").read() != open(br.ICON, "rb").read()
      and ("AFTER_MARKET_PREPARE.ico", "release/AFTER_MARKET_PREPARE.ico") in br.PROGRAM_FILES, icon_opts)
```

2. `--exes-from` 시험 안 `for rel in ("ERPia_RPA.exe", "Prepare_RPA.exe"):` 를 `for rel in br.EXES:` 로, 그 check 이름의 "두 exe" 를 "세 exe" 로.
3. 그 아이콘 확인 바로 뒤에:

```python
console = {exe: [o for o in br.NUITKA_COMMON + br.NUITKA_EXTRA[exe] if o.startswith("--windows-console-mode=")]
           for exe in br.EXES}
check("콘솔: 루틴·프리페어는 늘 콘솔, 기록기는 창 프로그램 (attach - 시작 메뉴로 켜면 검은 창 없음)",
      console == {"ERPia_RPA.exe": ["--windows-console-mode=force"], "Prepare_RPA.exe": ["--windows-console-mode=force"],
                  "Prepare_Recorder.exe": ["--windows-console-mode=attach"]}, str(console))
rex = br.NUITKA_EXTRA.get("Prepare_Recorder.exe", [])
check("기록기 exe: rpa_recorder.py, tk-inter, Playwright, --check 끝 줄, 작업 표시줄 ID",
      br.EXES.get("Prepare_Recorder.exe") == "rpa_recorder.py" and br.TK_PLUGIN in rex
      and "--include-package=playwright" in rex and br.MARKERS.get("Prepare_Recorder.exe") == "기록기 점검 끝"
      and 'APP_ID = "AFTERMARKET.RPA.Recorder"' in (ROOT / "rpa_recorder.py").read_text(encoding="utf-8"))
with tempfile.TemporaryDirectory() as d:
    tcl, tkd = br.tcl_tk_dirs(d)
    cmd = br.nuitka_command("py", "Prepare_Recorder.exe", d, (tcl, tkd))
    check("Tcl/Tk 를 폴더로 꺼내 Nuitka 에 넘긴다 (3.14 는 DLL 안 zipfs - 2026-09-30)",
          os.path.isfile(os.path.join(tcl, "init.tcl")) and os.path.isfile(os.path.join(tkd, "tk.tcl"))
          and f"--tcl-library-dir={tcl}" in cmd and f"--tk-library-dir={tkd}" in cmd and cmd[-1].endswith("rpa_recorder.py"),
          str(cmd[-4:]))
    check("tk-inter 를 안 쓰는 exe 에는 Tcl 옵션이 없다",
          not any("library-dir" in o for o in br.nuitka_command("py", "Prepare_RPA.exe", d)))
try:
    br.build_exes("pyinstaller", tempfile.mkdtemp())
    check("PyInstaller 로는 만들지 않는다 (기록기는 tk-inter)", False)
except RuntimeError:
    check("PyInstaller 로는 만들지 않는다 (기록기는 tk-inter)", True)
with tempfile.TemporaryDirectory() as d:
    for rel in ("ERPia_RPA.exe", "Prepare_RPA.exe"):
        write(os.path.join(d, rel), rel.encode())
    try:
        br.reuse_exes(d, os.path.join(d, "work"))
        check("--exes-from: 기록기 exe 가 없는 옛 판이면 무엇이 없는지 말하고 멈춘다", False)
    except FileNotFoundError as e:
        check("--exes-from: 기록기 exe 가 없는 옛 판이면 무엇이 없는지 말하고 멈춘다", "Prepare_Recorder.exe" in str(e), str(e))
check("설치 파일: 시작 메뉴 '쇼핑몰 기록기' (주황 아이콘, 작업 표시줄 ID 가 기록기와 같다)",
      '"{group}\\쇼핑몰 기록기"' in iss and 'Filename: "{app}\\Prepare_Recorder.exe"' in iss
      and 'IconFilename: "{app}\\AFTER_MARKET_PREPARE.ico"' in iss and 'AppUserModelID: "AFTERMARKET.RPA.Recorder"' in iss)
```

(아이콘 확인은 `iss = …` 를 읽은 뒤, `iscc = br.find_iscc()` 바로 앞에 있다 - 이 블록도 그 자리라 `iss` 를 쓸 수 있다.)

Run: `.venv\Scripts\python.exe tests\test_build_release.py`
Expected: 새 확인들이 `[실패]` 또는 `AttributeError: … 'tcl_tk_dirs'`.

- [ ] **Step 2: 구현 (`tools/build_release.py`)**

1. `EXES` 와 `MARKERS`:

```python
EXES = {"ERPia_RPA.exe": "run_routine.py", "Prepare_RPA.exe": "web_runner.py", "Prepare_Recorder.exe": "rpa_recorder.py"}
```

```python
MARKERS = {"ERPia_RPA.exe": "=== 점검 끝", "Prepare_RPA.exe": "쓸 수 있는 Action",
           "Prepare_Recorder.exe": "기록기 점검 끝"}   # --check 의 끝 줄
```

2. `NUITKA_COMMON` 에서 `"--windows-console-mode=force", ` 를 빼고, `NUITKA_EXTRA` 를:

```python
PLAYWRIGHT = ["--include-package=playwright", "--include-package-data=playwright"]
TK_PLUGIN = "--enable-plugin=tk-inter"
# 콘솔은 exe 마다: 루틴·프리페어는 로그를 보여 주는 콘솔, 기록기는 창 프로그램 (attach - 시작 메뉴로 켜면 검은 창이 없고,
# --check 는 부른 쪽이 출력을 받는다)
NUITKA_EXTRA = {"ERPia_RPA.exe": ["--windows-console-mode=force", f"--windows-icon-from-ico={ICON}"],
                "Prepare_RPA.exe": ["--windows-console-mode=force", f"--windows-icon-from-ico={ICON_PREPARE}", *PLAYWRIGHT],
                "Prepare_Recorder.exe": ["--windows-console-mode=attach", f"--windows-icon-from-ico={ICON_PREPARE}",
                                         *PLAYWRIGHT, TK_PLUGIN]}
```

3. `def build_exes(builder, work_dir):` 를 통째로 바꾸고 앞에 둘을 둔다:

```python
def tcl_tk_dirs(dest):
    """tkinter 가 쓰는 Tcl·Tk 라이브러리 폴더 (Nuitka tk-inter 에 넘길 것). 파이썬 3.14 의 Tcl/Tk 9 는 라이브러리가
    tcl90.dll·tcl9tk90.dll 안 zipfs 에 있어 Nuitka 가 못 찾는다 (2026-09-30) → dest\\tcltk 에 꺼내 그 자리를 돌려준다.
    진짜 폴더면 그대로 쓴다."""
    import tkinter
    root = tkinter.Tk()
    try:
        root.withdraw()
        out = []
        for name, src in (("tcl", root.tk.eval("info library")), ("tk", root.tk.eval("set tk_library"))):
            if os.path.isdir(src):
                out.append(src)
                continue
            dst = os.path.join(dest, "tcltk", name)
            shutil.rmtree(dst, ignore_errors=True)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            root.tk.eval(f"file copy -force {{{src}}} {{{dst.replace(os.sep, '/')}}}")
            out.append(dst)
        return tuple(out)
    finally:
        root.destroy()


def nuitka_command(py, exe, work_dir, tk_dirs=None):
    """exe 하나를 만드는 Nuitka 명령. tk-inter 를 쓰는 exe 는 tk_dirs (tcl_tk_dirs 의 결과) 가 있어야 한다."""
    extra = list(NUITKA_EXTRA[exe])
    if TK_PLUGIN in extra:
        extra += [f"--tcl-library-dir={tk_dirs[0]}", f"--tk-library-dir={tk_dirs[1]}"]
    return [py, "-m", "nuitka", *NUITKA_COMMON, *extra, f"--output-dir={work_dir}", f"--output-filename={exe}",
            os.path.join(REPO, EXES[exe])]


def build_exes(builder, work_dir, only=None):
    """exe 들(only 를 주면 그것만)을 work_dir 에 만든다. 판 목록의 builder 칸 글자를 돌려준다 ("nuitka 4.2.2 · python 3.14.7")."""
    if builder != "nuitka":
        raise RuntimeError("기록기 exe 는 Nuitka 로만 만든다 (tk-inter) - --builder nuitka 를 쓰세요")
    os.makedirs(work_dir, exist_ok=True)
    py = sys.executable
    tk_dirs = None
    for exe in (only or EXES):
        if TK_PLUGIN in NUITKA_EXTRA[exe] and tk_dirs is None:
            tk_dirs = tcl_tk_dirs(work_dir)
        subprocess.run(nuitka_command(py, exe, work_dir, tk_dirs), cwd=REPO, check=True)
    ver = subprocess.run([py, "-m", "nuitka", "--version"], capture_output=True, text=True, check=True).stdout.split()[0]
    return f"nuitka {ver} · python {platform.python_version()}"
```

(PyInstaller 가지가 없어지면 `importlib` 을 쓰는 곳이 없어진다 - 다른 곳에서도 안 쓰면 `import importlib.metadata` 줄을 지운다. `grep -n importlib tools/build_release.py` 로 확인.)

4. `reuse_exes` 맨 앞(설명 글 다음)에:

```python
    missing = [exe for exe in EXES if not os.path.isfile(os.path.join(src_dir, exe))]
    if missing:
        raise FileNotFoundError(f"{src_dir} 에 {', '.join(missing)} 가 없습니다 (기록기가 없던 옛 판) - "
                                "--exes-from 없이 새로 빌드하세요")
```

5. `main` 의 `builder = reuse_exes(…) if args.exes_from else build_exes(…)` 줄을:

```python
    try:
        builder = reuse_exes(args.exes_from, work) if args.exes_from else build_exes(args.builder, work)
    except (FileNotFoundError, RuntimeError) as e:
        print("  문제:", e)
        return 1
```

그리고 `--to-dist` 안내 글 "두 exe" 를 "exe 셋" 으로 (`ap.add_argument` 의 help 두 곳, 끝의 `print`).

- [ ] **Step 3: 설치 파일 바로 가기 (`release/installer.iss`)**

`[Icons]` 의 `Name: "{group}\RPA 설정"; …` 줄 바로 아래에 (편집 도구로 - BOM 유지):

```
Name: "{group}\쇼핑몰 기록기"; Filename: "{app}\Prepare_Recorder.exe"; WorkingDir: "{app}"; Comment: "쇼핑몰 조작 기록기 (관리자 권한 요청이 뜹니다)"; IconFilename: "{app}\AFTER_MARKET_PREPARE.ico"; AppUserModelID: "AFTERMARKET.RPA.Recorder"
```

- [ ] **Step 4: 샌드박스 확인 (`tools/sandbox_inner.ps1`, BOM 유지)**

1. exe `--check` 줄:

```powershell
foreach ($e in @(@("ERPia_RPA.exe", "=== 점검 끝"), @("Prepare_RPA.exe", "쓸 수 있는 Action"), @("Prepare_Recorder.exe", "기록기 점검 끝"))) {
```

2. `Check "아이콘: 설정·대시보드 바로 가기, 앱 및 기능 목록" …` 줄 바로 아래에:

```powershell
$recLnk = (New-Object -ComObject WScript.Shell).CreateShortcut("$SM\쇼핑몰 기록기.lnk")
Check "시작 메뉴 '쇼핑몰 기록기' (기록기 exe, 주황 아이콘)" (($recLnk.TargetPath -eq "$App\Prepare_Recorder.exe") -and ($recLnk.IconLocation -like "$App\AFTER_MARKET_PREPARE.ico*")) "target=$($recLnk.TargetPath) icon=$($recLnk.IconLocation)"
```

3. 아이콘 확인의 `$want = @{ "ERPia_RPA.exe" = $Ico; "Prepare_RPA.exe" = $IcoPrep }` 를 `$want = @{ "ERPia_RPA.exe" = $Ico; "Prepare_RPA.exe" = $IcoPrep; "Prepare_Recorder.exe" = $IcoPrep }` 로, 그 `Check` 이름을 `"exe 다섯의 아이콘: 루틴·감독·에이전트는 크림 A, 프리페어·기록기는 주황 A"` 로.

- [ ] **Step 5: 시험 통과**

Run: `.venv\Scripts\python.exe tests\test_build_release.py`
Expected: `실패: 없음` (55개 안팎 - 끝에 찍히는 수를 문서에 적는다).
Run: `.venv\Scripts\python.exe tests\test_encoding.py`
Expected: `실패: 없음`.
Run: `powershell -NoProfile -Command "$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile('D:\AX\RPA\tools\sandbox_inner.ps1',[ref]$null,[ref]$e); $e.Count"`
Expected: `0`.

- [ ] **Step 6: 기록기 exe 를 한 번 빌드해 콘솔·--check 를 확인한다**

Run (3분쯤):

```powershell
.venv\Scripts\python.exe -c "import sys; sys.path.insert(0, 'tools'); import build_release as br; print(br.build_exes('nuitka', r'build\rec_try', only=['Prepare_Recorder.exe']))"
.venv\Scripts\python.exe -c "import struct; d = open(r'build\rec_try\Prepare_Recorder.exe', 'rb').read(4096); o = struct.unpack_from('<I', d, 0x3C)[0]; print('subsystem', struct.unpack_from('<H', d, o + 92)[0])"
.venv\Scripts\python.exe -c "import os, subprocess, tempfile; t = tempfile.mkdtemp(); env = dict(os.environ, RPA_USER_CONFIG=os.path.join(t, 'RPA_UserConfig.json'), RPA_PROGRAMDATA=os.path.join(t, 'pd'), RPA_STATUS_DIR=os.path.join(t, 'st'), RPA_UNATTENDED='1'); r = subprocess.run([r'build\rec_try\Prepare_Recorder.exe', '--check'], capture_output=True, env=env, timeout=180); print(r.returncode); print((r.stdout + r.stderr).decode('utf-8', 'replace')[-400:])"
```

Expected: `subsystem 2` (창 프로그램 - 시작 메뉴로 켜면 콘솔이 안 뜬다), 그리고 `0` 과 끝 줄 `기록기 점검 끝`, `Tcl/Tk: 9.0.…`.

**끝 줄이 안 찍히면** (attach 가 출력을 못 넘김 - 스펙 11절 위험): `rpa_recorder.check()` 끝에 `path = os.environ.get("RPA_CHECK_FILE")` 가 있으면 그 파일에 `CHECK_DONE` 을 쓰게 하고, `build_release.smoke_check` 와 `sandbox_inner.ps1` 의 exe 줄이 기록기일 때 `RPA_CHECK_FILE` 을 주고 그 파일 내용도 보게 고친 뒤 이 단계를 다시 돌린다.

Run: `Remove-Item -Recurse -Force build\rec_try`

- [ ] **Step 7: graphify·변경 확인**

제안 커밋: `빌드: 세 번째 exe Prepare_Recorder (tk-inter·콘솔 attach·주황 아이콘), Tcl/Tk 꺼내기, 시작 메뉴 '쇼핑몰 기록기', 샌드박스 확인`.

---

### Task 6: 에이전트·규칙

**Files:**
- Modify: `firebase/agent/agent.py` (`KNOWN_TYPES`, `recent_summary`, `real_actions`, `pump`)
- Modify: `firebase/tests/test_agent.py`
- Modify: `firebase/rules/database.rules.json` (명령 `type` 검사 한 줄)
- Modify: `firebase/tests/rules.test.js`

**Interfaces:**
- Consumes: Task 2 `st.preset_summary()`, `st.set_preset_switches()`, `st.HISTORY_ONLY`
- Produces: 현황 `live/{cid}/{pc}.presets = [{no, name, code, steps, saved_at, has_login, on}] | null`, 명령 `set_presets` (args `{"PRESET1": true, …}`, 결과 `프리셋을 바꿨습니다 (켬: ① 지마켓)`)

- [ ] **Step 1: 실패하는 시험을 쓴다 (`firebase/tests/test_agent.py`)**

맨 끝 `print(f"\n{COUNT - len(FAIL)}/{COUNT} 통과")` 줄 앞에:

```python
print("\n5-2절 실제 동작 - 쇼핑몰 프리셋 (가짜 사용자 설정)")
with tempfile.TemporaryDirectory() as d:
    os.environ["RPA_USER_CONFIG"] = os.path.join(d, "RPA_UserConfig.json")
    try:
        import rpa_status as st
        st.write_user_config({"LogIn": {"AdminCode": "x", "ID": "a", "PW": "비밀-시험"}, "Sites": {
            "PRESET1": {"URL": "https://x/login", "ID": "seller", "PW": "몰-비밀", "Action": ["replay"], "Stts": 9, "Preset": 1,
                        "note": "지마켓"},
            "PRESET2": {"URL": "https://y/login", "ID": "seller", "PW": "", "Action": ["replay"], "Stts": 9, "Preset": 2,
                        "note": "쿠팡"}}})
        rec1 = {"version": 1, "start_url": "https://x/login", "steps": [{"kind": "goto", "page": 0, "href": "https://x/login"}]}
        st.write_presets([{"no": 1, "name": "지마켓", "code": "012", "saved_at": None, "record": rec1},
                          {"no": 2, "name": "쿠팡", "code": "013", "saved_at": None, "record": rec1}])
        acts = ag.real_actions()
        msg = acts["set_presets"]({"PRESET1": True})
        check(st.read_user_config()["Sites"]["PRESET1"]["Stts"] == 0 and "① 지마켓" in msg, f"켜면 Stts 0, 결과에 이름 ({msg})")
        acts["set_presets"]({"PRESET1": False})
        check(st.read_user_config()["Sites"]["PRESET1"]["Stts"] == 9, "끄면 Stts 9")
        for args, why in (({"PRESET7": True}, "아는 프리셋"), ({"PRESET2": True}, "켤 수 없")):
            try:
                acts["set_presets"](args)
                check(False, f"거부: {why}")
            except RuntimeError as e:
                check(why in str(e), f"거부: {why} ({e})")
        check(ag.decide({"type": "set_presets", "state": "queued", "expires_at": NOW + 60}, NOW)[0] == "run", "set_presets 는 아는 명령")
        rows2 = [{"started_at": "2026-09-14T13:55:00", "state": "success", "program": "recorder"},
                 {"started_at": "2026-09-14T13:56:00", "state": "stopped", "program": "prepare"}]
        check(ag.recent_summary(rows2, _dt.date(2026, 9, 14))[-1] == {"date": "2026-09-14", "success": 0, "failed": 1, "crashed": 0},
              "기록기 미리보기는 날짜별 도넛에 안 센다")
    finally:
        os.environ.pop("RPA_USER_CONFIG", None)
```

`firebase/tests/rules.test.js` 의 `test("commands: 모르는 type 은 거부", …)` 바로 앞에:

```js
test("commands: set_presets 는 관리자가 만들 수 있다 (쇼핑몰 프리셋 켬/끔)", async () => {
  await assertSucceeds(set(ref(asAdminA(), "apps/rpa/commands/ca/pc1/c1"), cmd({ type: "set_presets", args: { PRESET1: true } })));
});
```

Run: `cd firebase; ..\.venv\Scripts\python.exe tests\test_agent.py`
Expected: 5-2절이 `KeyError: 'set_presets'` 로 멈춘다.
Run: `cd firebase; . .\emu_env.ps1; cd tests; npm test`
Expected: 새 규칙 시험 하나 실패.

- [ ] **Step 2: 구현**

`firebase/agent/agent.py`:

1. `KNOWN_TYPES = ("launch", "stop_erpia", "set_modules", "set_schedule")` → `KNOWN_TYPES = ("launch", "stop_erpia", "set_modules", "set_schedule", "set_presets")`.
2. `recent_summary` 의 `for r in rows or []:` 바로 위에 `import rpa_status as st` 를, 반복 안 첫 줄에:

```python
        if r.get("program") in st.HISTORY_ONLY:
            continue     # 기록기 미리보기는 RPA 실행이 아니다 - 날짜별 도넛에 안 센다
```

3. `real_actions` 의 `def do_schedule(args):` 앞에:

```python
    def do_presets(args):
        if not isinstance(args, dict) or not args:
            raise RuntimeError("프리셋 값이 없습니다")
        try:
            final = st.set_preset_switches(args)
        except FileNotFoundError:
            raise RuntimeError("이 PC 의 사용자 설정이 없습니다") from None
        except ValueError as e:
            raise RuntimeError(str(e)) from None
        names = {p["no"]: p["name"] for p in (st.preset_summary() or [])}
        on = [f"{chr(0x2460 + no - 1)} {names.get(no, no)}" for no, v in sorted(final.items()) if v]
        return f"프리셋을 바꿨습니다 (켬: {', '.join(on) or '없음'})"
```

그리고 끝의 `return {…, "set_schedule": do_schedule}` 에 `"set_presets": do_presets` 를 더한다.
4. `pump` 의 `snap["modules"] = …` try 블록 바로 아래:

```python
                try:
                    snap["presets"] = st.preset_summary()   # 이름·코드·단계 수·켬 (기록 내용·아이디·비밀번호는 안 싣는다)
                except Exception:
                    snap["presets"] = None
```

그리고 바뀜 비교 `body = json.dumps([snap.get("programs"), snap.get("modules"), …` 목록에 `snap.get("presets")` 를 더한다.

`firebase/rules/database.rules.json` 의 `"type"` 검사에서 `newData.val() === 'set_schedule')` 를 `newData.val() === 'set_schedule' || newData.val() === 'set_presets')` 로.

- [ ] **Step 3: 통과를 확인한다**

Run: `cd firebase; ..\.venv\Scripts\python.exe tests\test_agent.py`
Expected: 마지막 `N/N 통과` (실패 없음).
Run: `cd firebase; . .\emu_env.ps1; cd tests; npm test`
Expected: 전부 통과 (규칙 25).
Run: `cd firebase\tests; firebase emulators:exec --config ../firebase.json --only auth,database,firestore --project rpa-test-f02e0 "node integration.js"`
Expected: 통합 시험 그대로 통과 (명령 왕복).

- [ ] **Step 4: graphify·변경 확인**

제안 커밋: `에이전트: 현황에 쇼핑몰 프리셋 요약, 명령 set_presets, 날짜별 도넛에서 기록기 빼기 / 규칙: set_presets`.

---

### Task 7: 대시보드 '쇼핑몰 프리셋' 카드·기록 표 '기록기'

**Files:**
- Modify: `firebase/web/rpa.js` (`PROGRAM_SHORT`, 화면 틀의 `mod-card` 뒤, `mount` 의 연결, `onValue`, `paintButtons`, 실행 모듈 절 뒤)
- Modify: `firebase/tests/check_web.py` (5-2절, 11절)

**Interfaces:**
- Consumes: Task 6 `live.presets`, 명령 `set_presets` `{"PRESET1": true}`
- Produces: 화면 `#shop-card`·`#shop-list`·`#shop-meta`·`#shop-info`·`#shop-apply`, `settings/{cid}/{pc}/presets = {"PRESET1": bool, …}`

- [ ] **Step 1: 실패하는 화면 시험을 쓴다 (`firebase/tests/check_web.py`)**

`print("6절 자동 실행")` 바로 앞에:

```python
    print("5-2절 쇼핑몰 프리셋")
    SHOPS = [{"no": 1, "name": "지마켓", "code": "012", "steps": 12, "saved_at": "2026-09-30T18:20:00", "has_login": True, "on": False},
             {"no": 2, "name": "<b>몰</b>", "code": "", "steps": 0, "has_login": False, "on": False}]
    check(page.is_hidden("#shop-card"), "옛 에이전트(프리셋을 안 올림)면 카드가 없다")
    db_patch(LIVE, {"presets": SHOPS})
    page.wait_for_function("document.querySelectorAll('#shop-list label').length === 2", timeout=10000)
    first = page.text_content("#shop-list label:nth-child(1)")
    check("① 지마켓 (012) · 12단계 · 9/30 저장" in first, f"줄 글자 ({first})")
    check(page.text_content("#shop-list label:nth-child(2)").startswith("② <b>몰</b>")
          and page.locator("#shop-list b").count() == 0, "이름의 꺾쇠는 글자 그대로 (태그가 아니다 - Review Focus 5)")
    check(page.locator("#shop-list label:nth-child(2) input").is_disabled()
          and "기록기" in (page.get_attribute("#shop-list label:nth-child(2)", "title") or ""), "기록이 없는 줄은 스위치가 잠기고 까닭이 보인다")
    check(page.is_disabled("#shop-apply") and "0/2 켬" in page.text_content("#shop-meta"), "바뀐 게 없으면 적용 비활성")
    page.click("#shop-list label:nth-child(1)")
    check(not page.is_disabled("#shop-apply") and "1/2 켬" in page.text_content("#shop-meta"), "켜면 요약·적용 활성")
    page.click("#shop-apply")
    time.sleep(1.5)
    check(db_get(f"{SETTINGS}/presets") == {"PRESET1": True, "PRESET2": False}, f"settings.presets 에 저장 ({db_get(f'{SETTINGS}/presets')})")
    sent = cmds_of("set_presets")
    check(len(sent) == 1 and sent[0]["args"] == {"PRESET1": True, "PRESET2": False}, f"set_presets 명령 ({sent})")
    key = next(k for k, v in (db_get(CMDS) or {}).items() if v.get("type") == "set_presets")
    db_patch(f"{CMDS}/{key}", {"state": "done", "result": "프리셋을 바꿨습니다 (켬: ① 지마켓)", "started_at": 1, "ended_at": 2})
    db_put(f"{LIVE}/presets/0/on", True)
    page.wait_for_function("document.getElementById('shop-apply')?.disabled === true", timeout=10000)
    check("1/2 켬" in page.text_content("#shop-meta"), "PC 값이 돌아오면 기준값 갱신")
```

`print("10절 버전 표시")` 절이 끝나는 곳(파일의 `browser.close()` 앞, 마지막 절 뒤)에:

```python
    print("11절 기록기 미리보기 기록")
    seed_run("r_rec_0909", "recorder", "success", "2026-09-09T08:00:00", 27,
             log=["[08:00:00] === 미리보기: ① 지마켓 (12단계) ==="])
    page.click("#tab-history")
    page.fill("#hist-date", "2026-09-09"); page.dispatch_event("#hist-date", "change")
    page.wait_for_function("document.getElementById('hist-title')?.textContent === '기록 · 2026-09-09'", timeout=15000)
    page.wait_for_function("(document.getElementById('hist-msg')?.textContent || '').endsWith('건')", timeout=15000)
    check(page.text_content("#hist-rows tr.hist td:nth-child(2)") == "기록기", "기록 표의 프로그램 칸이 '기록기'")
```

Run: `cd firebase\tests; firebase emulators:exec --config ../firebase.json --only auth,database,firestore,hosting --project rpa-test-f02e0 "python check_web.py"`
Expected: 5-2절이 `#shop-card` 를 못 찾아 실패, 11절 '기록기' 가 아니라 '프리페어 RPA'.

- [ ] **Step 2: 구현 (`firebase/web/rpa.js`)**

1. `const PROGRAM_SHORT = { routine: "루틴", prepare: "프리페어" };` → `const PROGRAM_SHORT = { routine: "루틴", prepare: "프리페어", recorder: "기록기" };`
2. 화면 틀의 `mod-card` 블록(`<button class="apply" id="mod-apply" disabled>적용</button>` 다음 `</div>`) 뒤에:

```html
        <div class="card hide" id="shop-card">
          <h2>쇼핑몰 프리셋 <span class="muted" id="shop-meta"></span></h2>
          <div id="shop-list"></div>
          <div class="msg" id="shop-info"></div>
          <button class="apply" id="shop-apply" disabled>적용</button>
        </div>
```

3. `mount` 의 `$("mod-apply").onclick = applyModules;` 아래에 `$("shop-apply").onclick = applyShops;`
4. `onValue` 안 `if (first || !modulesDirty()) resetModules();` 아래에 `if (first || !shopsDirty()) resetShops();`
5. `paintButtons` 의 `paintModuleMeta(); paintScheduleMeta();` 를 `paintModuleMeta(); paintShopMeta(); paintScheduleMeta();` 로.
6. `// --- 자동 실행 ---` 줄 바로 앞에:

```js
// --- 쇼핑몰 프리셋 --------------------------------------------------
// PC 의 기록기가 저장한 프리셋 (에이전트가 이름·코드·단계 수·켬만 올린다). 켜면 다음 프리페어부터 그 쇼핑몰에서 엑셀을 받는다.
// 명령 키는 "PRESET1" - 숫자 키는 Realtime DB 가 배열로 바꿔 읽는다
const circled = (n) => String.fromCharCode(0x2460 + n - 1);
const savedShops = () => (Array.isArray(live?.presets) ? live.presets : []);
const shopReady = (p) => p.steps > 0 && p.has_login;
function resetShops() {
  form.shops = Object.fromEntries(savedShops().map((p) => [p.no, !!p.on]));
  paintShops();
}
function shopsDirty() {
  return savedShops().some((p) => !!form.shops?.[p.no] !== !!p.on);
}
function shopLine(p) {
  const saved = p.saved_at ? ` · ${Number(p.saved_at.slice(5, 7))}/${Number(p.saved_at.slice(8, 10))} 저장` : "";
  return `${circled(p.no)} ${p.name}${p.code ? ` (${p.code})` : ""} · ${p.steps}단계${saved}`;
}
function paintShops() {
  show($("shop-card"), Array.isArray(live?.presets));   // 옛 에이전트·설정이 깨진 PC 는 카드를 숨긴다
  const list = savedShops();
  $("shop-list").replaceChildren(...list.map((p, i) => {
    const row = document.createElement("label"); row.className = "switch" + (i === 0 ? " first" : "");
    const cb = document.createElement("input");
    const ready = shopReady(p);
    cb.type = "checkbox"; cb.checked = !!form.shops[p.no];
    cb.disabled = !c.isAdmin || busy || (!ready && !cb.checked);   // 켜진 것은 준비가 안 됐어도 끌 수는 있다
    cb.setAttribute("aria-label", `${circled(p.no)} ${p.name}`);
    if (!ready) row.title = p.steps ? "쇼핑몰 기록기에서 아이디·비밀번호를 넣고 저장하세요" : "쇼핑몰 기록기에서 기록하고 저장하세요";
    cb.onchange = () => { form.shops[p.no] = cb.checked; paintShopMeta(); };
    row.append(Object.assign(document.createElement("span"), { textContent: shopLine(p) }), cb,
      Object.assign(document.createElement("span"), { className: "knob" }));
    return row;
  }));
  $("shop-info").textContent = list.some((p) => p.steps > 0) ? "" : "기록한 프리셋이 없습니다. 이 PC 의 '쇼핑몰 기록기' 에서 기록하세요";
  paintShopMeta();
}
function paintShopMeta() {
  const list = savedShops();
  const on = list.filter((p) => form.shops?.[p.no]).length;
  $("shop-meta").textContent = list.length ? `${on}/${list.length} 켬` : "";
  $("shop-apply").disabled = !c.isAdmin || busy || !shopsDirty();
}
async function applyShops() {
  const wanted = Object.fromEntries(savedShops().map((p) => [`PRESET${p.no}`, !!form.shops[p.no]]));
  try {
    await set(ref(c.db, `${P("settings", c.me.cid, c.pcId)}/presets`), wanted);
  } catch (e) { notify("bad", e.code === "PERMISSION_DENIED" ? "권한이 없습니다" : `저장하지 못했습니다 (${e.code || e})`); return; }
  await sendCommand("set_presets", wanted, "쇼핑몰 프리셋");
}
```

7. `let form = { modules: {}, sch: … };` 에 `shops: {}` 를 더한다: `let form = { modules: {}, shops: {}, sch: { enabled: false, days: [], times: [] } };`

- [ ] **Step 3: 통과를 확인한다**

Run: `cd firebase\tests; firebase emulators:exec --config ../firebase.json --only auth,database,firestore,hosting --project rpa-test-f02e0 "python check_web.py"`
Expected: 전부 통과 (예전 239 + 5-2절 10 + 11절 1). 브라우저 콘솔 오류 없음 (시험이 `pageerror` 를 모은다).

- [ ] **Step 4: graphify·변경 확인**

제안 커밋: `대시보드: 환경설정 '쇼핑몰 프리셋' 스위치 (set_presets), 기록 표 '기록기'`.

---

### Task 8: 문서·판 빌드·샌드박스 (배포는 사용자 확인 뒤)

**Files:**
- Modify: `docs/firebase-architecture.md`, `docs/superpowers/specs/2026-09-30-shop-record-replay-design.md` (상태 줄)

- [ ] **Step 1: 전체 시험을 한 번 더**

```powershell
.venv\Scripts\python.exe tests\test_web_replay.py
.venv\Scripts\python.exe tests\test_presets.py
.venv\Scripts\python.exe tests\test_build_release.py
.venv\Scripts\python.exe tests\test_settings.py
.venv\Scripts\python.exe tests\test_layout.py
.venv\Scripts\python.exe tests\test_encoding.py
.venv\Scripts\python.exe tests\test_dashboard_modules.py
cd firebase; ..\.venv\Scripts\python.exe tests\test_agent.py
```

Expected: 모두 `실패: 없음` / `N/N 통과`. 각 스크립트가 찍은 건수를 적어 둔다 (다음 단계 표).

- [ ] **Step 2: 문서**

`docs/firebase-architecture.md`:
- 파일 지도에 세 줄: `web_replay.py` (쇼핑몰 조작 기록·재생 엔진), `rpa_recorder.py` → `Prepare_Recorder.exe` (쇼핑몰 기록기, 시작 메뉴 '쇼핑몰 기록기', 주황 A), 설정 폴더의 `RPA_Presets.json` (프리셋 ①~⑩ 기록, 비밀 없음).
- 데이터 경로에: 현황 `live/{cid}/{pc}.presets` (이름·코드·단계 수·켬), `settings/{cid}/{pc}/presets` (`{"PRESET1": true}`), 명령 `set_presets` → 에이전트가 `Sites.PRESETn.Stts` 0/9.
- 에이전트가 하는 일에: 프리셋 요약 올리기, `set_presets`, 도넛은 프리페어·루틴만.
- 시험 표에 줄 셋 - `기록·재생 엔진` (`tests/test_web_replay.py`, 건수), `프리셋` (`tests/test_presets.py`, 건수), `기록기 화면` (`tests/check_recorder_ui.py`, 건수) - 과 빌드 스크립트·샌드박스·에이전트·규칙·화면 건수 고침.
- 비밀 취급에 한 줄: 프리셋 파일에는 비밀이 없고, 대시보드로는 이름·코드·단계 수·켬과 값을 뺀 로그만 간다.

스펙 상태 줄을 `**상태:** 구현됨 (2026-MM-DD, 판 <판> - 샌드박스 N/N). 설계는 2026-09-30 사용자 승인` 으로 (실제 날짜·판·수).

- [ ] **Step 3: 판 빌드 (10분쯤)**

Run: `.venv\Scripts\python.exe tools\build_release.py`
Expected: `판 2026.MM.DD-N` 과 설치 파일 `D:\AX\AFTER_MARKET_RPA_Setup_<판>.exe`, `문제` 없음 (기록기 `--check` 포함 exe 셋의 표지).

- [ ] **Step 4: 샌드박스 (3분쯤)**

Run: `.venv\Scripts\python.exe tools\sandbox_test.py D:\AX\AFTER_MARKET_RPA_Setup_<판>.exe`
Expected: `34/34` (32 + 기록기 `--check` + 시작 메뉴 '쇼핑몰 기록기').

- [ ] **Step 5: 배포 - 사용자에게 묻고 나서만**

사용자에게: "대시보드 규칙(명령 set_presets)과 화면('쇼핑몰 프리셋' 카드)을 Firebase 에 올릴까요?" 승인하면:

```powershell
cd D:\AX\RPA\firebase
firebase deploy --only database,hosting --config firebase.json
```

- [ ] **Step 6: 기억·안내**

- 기억 `web-record-replay.md`·`next-steps.md`: 구현됨, 판 번호, 샌드박스 수, 노트북에서 할 실기 (기록기로 실제 쇼핑몰 한 곳 = spike 2).
- 사용자에게: 새 판 설치 파일, 시작 메뉴 '쇼핑몰 기록기', 새 프리셋은 대시보드에서 켜야 돈다는 것.
- 제안 커밋: `문서: 쇼핑몰 기록·재생 - 파일 지도·데이터 경로·시험 표, 스펙 구현됨 (판 …)`.
