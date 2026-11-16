# ACTOR 재생: 기록과 다른 창에서 대상 찾아 이어 가기 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 팝업이 기록과 다르게 뜬 날(끼어든 창·순서 바뀜·같은 창으로 열림·한 클릭에 창 둘)에도, 대상이 열린 창 어딘가에 있으면 재생이 그 창을 고쳐 잡고 이어 가게 한다.

**Architecture:**
- `web_replay.py` 의 `Replayer` 만 고친다.
- `_find` 에 '짧게 한 번 훑기'(quick)와 '못 찾은 회차 끝에 다른 곳 보기'(elsewhere)를 더한다.
- `_step` 이 그 결과로 창 번호(`self.pages`)를 고쳐 잡는다.
- 기록 모양·옵저버·웹은 그대로다.

**Tech Stack:** Python 3.14, Playwright (깔린 Edge, headless), 평범한 파이썬 시험 스크립트

**Spec:** docs/superpowers/specs/2026-11-16-replay-window-relocate-design.md

## Global Constraints

- 성공하는 날은 느려지지 않는다. 새 동작은 두 때에만 돈다:
  - 새로 뜬 창에 처음 손대는데 주소가 기록과 다를 때
  - 못 찾은 회차(`step_timeout`)가 끝났을 때
- 주소가 다르다는 이유만으로 누르기를 막지 않는다.
- 고쳐 잡는 단계는 `MOVE_KINDS = ("click", "fill", "secret", "select", "check", "enter")` 이고 `target` 이 있는 것이다. 아래는 뺀다:
  - `optional` 단계
  - 메일함 창(`self.mail_page`)의 단계
  - `pick` · `loose` · `mailOpen` · `mailLink` · `mailSend` · `otpSend` 단계
- `download` 단계는 그 단계의 기준(`self.baseline[i]`)이 비어 있지 않으면 고쳐 잡지 않는다 (옛 파일 위험).
- 같은 컨텍스트(`self.context.pages`)의 창만 본다. 메일함 창과 브라우저 자체 페이지(`BROWSER_PAGES`)는 뺀다.
- 값: 다른 창·틀 훑기는 기다리지 않고 한 번 (최종 검토에서 `PROBE_WAIT` 를 없앰), `URL_WAIT = 3.0` (주소가 맞는 창 기다림), `FRAME_PROBE_MAX = 8` (창 하나에서 보는 안쪽 틀 수).
- 결과 글에 붙이는 말: `다른 창에서 찾음` · `안쪽 틀에서 찾음` · `새 창 대신 같은 창` · `주소 다름`.
- 커밋은 사용자가 시킬 때만 한다.

### 계획에서 정한 것 (설계에 없던 결정 - 끝 보고에 올린다)

1. **'주소가 맞는 창으로'(설계 1번)는 새로 뜬 창에 처음 손대는 단계에서만 한다.**
   - 주소가 원래 날마다 다른 사이트에서 단계마다 3초씩 늦어지지 않게 하려는 것이다.
   - 창 번호가 어긋나는 때는 창이 뜨는 순간뿐이다.
2. **주소가 달라도 고쳐 잡는 것은 '단계가 연 창'(번호가 `opens` 로 붙은 창, 또는 번호가 아직 없는 창)의 단계만이다.**
   - 처음 창(0)·새 탭의 단계는 주소(경로)가 기록과 같은 창으로만 옮긴다.
   - 처음 창의 [확인]을 못 찾았다고 공지 창의 [확인]을 누르는 일을 막으려는 것이다.
3. **`optional` 단계와 `hover` 는 고쳐 잡지 않는다.** 지금처럼 없으면 건너뛴다.

## Review Focus

1. 고쳐 잡기가 없던 잘못 누름을 새로 만들면 안 된다.
   - 예: 처음 창의 단계가 화면에 없는 날, 열려 있는 공지 창의 같은 이름 단추로 옮겨 누르는 것.
   - Task 1 시험 'A12b'.
2. 창을 고쳐 잡은 뒤 '새로 생긴 것' 기준이 옛 창의 것이면 옛 파일을 받는다.
   - Task 1 시험 'D3·D4' (새 파일만 받는다).
3. 못 찾는 날의 실패가 지금보다 눈에 띄게 늦어지면 안 된다.
   - 창·틀 훑기가 회차마다 수 초를 넘지 않아야 한다.
   - Task 1 시험 'A7' 의 걸린 시간 상한.
4. 메일 2차인증 흐름(메일함 창·인증번호 단계)이 창 고쳐 잡기에 끌려가면 안 된다.
   - Task 2 의 기존 시험 `test_mail_otp_replay.py` · `test_otp_replay.py` 통과.
5. 옵저버 미리보기의 [수정](`EditHere` → `Recorder.adopt(r.pages)`)이 고쳐 잡은 번호 그대로 이어 기록되어야 한다.
   - Task 2 의 기존 시험 `test_web_replay.py` 'N' 절 통과.

---

### Task 1: 시험 `tests/test_popup_relocate.py` 와 `Replayer` 의 창 고쳐 잡기

**Files:**
- Create: `tests/test_popup_relocate.py`
  - 시험판 `spike2.py` 의 가짜 쇼핑몰 서버·실제 `Recorder` 기록·판정(`judge`)을 옮긴다.
  - `step_timeout=3, step_tries=2`.
- Modify: `web_replay.py`
  - `_find` (1703~)
  - `_step` (2167~)
  - 상수 (392~ 근처)
  - `Replayer.__init__` 에 `self.opened = set()` (단계가 연 창 번호), `self.fresh = set()` (아직 손대지 않은 새 창), `self.folded = set()` (같은 창으로 잡은 번호)

**Interfaces (Produces):**
- `Replayer._find(page, s, prev, loose=False, quick=False, elsewhere=None)`
  - `quick=True`: 기다리지 않고 한 번만 훑는다. 처음부터 늦은 단서까지 쓰고, 못 찾으면 `NoTarget`.
  - `elsewhere`: 못 찾은 회차 끝마다 부르는 인자 없는 함수. `(page, 단계 모양, 붙일 말)` 을 돌려주면 `Moved` 를 던진다.
- `class Moved(Exception)`: `args = (page, step, note)`
- `Replayer._movable(s) -> bool`
- `Replayer._probe(pg, s, prev, loose, frames=True) -> dict | None`
  - 찾은 모양의 단계를 돌려준다. 틀이 다르면 `frame` 을 고친 사본이다.
- `Replayer._elsewhere(i, s, here) -> (page, step, note) | None`
  - 같은 창의 다른 틀을 먼저, 그다음 열린 다른 창을 본다.
  - 여러 창에서 찾으면 주소가 기록과 같은 하나일 때만 돌려준다.
  - '계획에서 정한 것 2'를 지킨다.
- `Replayer._url_window(i, s)`: 설계 1번 (`s["page"] in self.fresh` 일 때만. 끝나면 `fresh` 에서 뺀다).
- `Replayer._same_window(i, s, page) -> bool`: 설계 5번.

- [ ] **Step 1: 시험을 쓴다.** 경우와 맞는 결과:
  - 지금도 되는 것 (그대로 성공): A1 기록대로, A2 공지 없음, A3 공지 둘, A9 같은 창 중복, A13·A14 가리는 레이어, A15 알림창.
  - 고쳐져야 하는 것 (성공. 서버가 센 진짜 누르기 1회, 엉뚱한 누르기 0회):
    - A4 끼어듦, A5 같은 이름 단추, A6 5초 뒤, A8 둘 끼어듦
    - A10 레이어, A11 안쪽 틀
    - B1 한 클릭 창 둘 기록대로, B2 순서 바뀜, B3 공지 없음, B4 이벤트 추가
    - 결과 글에 `다른 창에서 찾음` · `새 창 대신 같은 창` · `안쪽 틀에서 찾음` 이 들어 있는지도 본다.
  - 실패가 맞는 것:
    - A7 일하는 창 없음 (걸린 시간 < 20초)
    - A12 같은 창이 넘어감
    - B5 공지만 뜸
    - A12b: A12 + 공지 창이 열려 있고 거기 [확인]이 있다. **엉뚱한 누르기 0회**여야 한다 (Review Focus 1).
  - 알려진 한계 (지금과 같음): A16·A17 은 엉뚱한 누르기가 생긴다. '지금 재생기와 같은 결과'로 적어 둔다.
  - 파일 받기:
    - D1: 일하는 창의 [엑셀받기]가 진짜 파일을 내려 준다 + 끼어든 창 → 파일 1개 저장.
    - D2: 끼어든 창에 같은 이름 단추만 있고 일하는 창이 없다 → **실패** (`download_timeout_ms=4000`, '파일 다운로드가 시작되지 않았습니다').
    - D3: 일하는 창에서 [요청]을 누르면 새 [다운로드] 줄이 생긴다 (옛 줄도 있다) + 끼어든 창 → 받은 파일이 새 파일.
    - D4: D3 + 일하는 창이 5초 뒤에 뜬다 (못 찾은 뒤 고쳐 잡는 길) → 새 파일.
    - D5: `_elsewhere` 에 `download` 단계와 비어 있지 않은 기준을 주면 `None`.
- [ ] **Step 2:** `.venv\Scripts\python.exe tests\test_popup_relocate.py` 를 돌려 '고쳐져야 하는 것'과 A12b·D1·D3·D4 가 실패하는지 본다.
- [ ] **Step 3: 구현.** 위 Interfaces 대로 한다.
  - `_step` 순서: ① `_url_window` → ② 기준 잡기(지금 코드) → ③ 창 고르기 → ④ 찾기 → ⑤ 하기.
  - ③ 창 고르기:
    - 번호가 `None` 이면 지금처럼 Skip.
    - 창이 없거나 닫혔으면 `URL_WAIT` 까지 `_elsewhere` 를 기다린다.
    - 그래도 없으면: 공지 창(`notice_popup`)이면 Skip, 아니면 지금의 `NotFound`.
  - ④ 찾기:
    - `Moved` 가 오면 `self.pages` 를 고친다.
    - 그 번호 창의 기준 (`needs[i]` 가운데 같은 창 것)을 다시 잡는다.
    - 그다음 그 창에서 찾는다.
    - `NoTarget` 인데 공지 창의 단계면 Skip.
  - 새 창을 여는 단계가 `self.pages[s["opens"]]` 에 창을 넣을 때마다 `opened` · `fresh` 에 번호를 더한다.
  - `expect_popup` 이 시간 초과이고 `acted` 이며 공지가 아니면 `_same_window` 를 본다.
  - `folded` 번호의 단계는 찾기 전에 `_probe` 로 틀을 먼저 맞춘다 (안쪽 틀로 열린 날 20초를 기다리지 않게).
  - `url_path(frame.url) != s["url"]` 이면 결과 글에 `주소 다름` 을 붙인다.
- [ ] **Step 4:** 같은 시험을 돌린다. 기대: `실패: 없음`.

### Task 2: 기존 재생 시험 통과·문서

- [ ] 아래를 돌린다. 기대: 모두 실패 없음. 결과 글에 `주소 다름` 이 붙어 깨지는 확인은 그 뜻을 보고 시험이나 코드를 고친다 (Ruling 으로 남긴다).
  - `tests/test_web_replay.py`
  - `tests/test_notice_popup.py`
  - `tests/test_popup_rule.py`
  - `tests/test_otp_replay.py`
  - `tests/test_mail_otp_replay.py`
  - `tests/stress_web_replay.py`
- [ ] 그 밖에 `web_replay` 를 쓰는 시험을 돌린다 (`grep -l web_replay tests/*.py`. `test_import_step.py` 는 빼고, 창을 띄우는 화면 시험은 사용자에게 먼저 알린다).
- [ ] `graphify update .`
- [ ] `docs/TODO.md` 에는 손대지 않는다 (다른 세션). 알려진 한계 2가지는 설계 문서에 이미 있다.
- [ ] 사용자에게 보고하고, 커밋·새 버전은 지시를 기다린다.
