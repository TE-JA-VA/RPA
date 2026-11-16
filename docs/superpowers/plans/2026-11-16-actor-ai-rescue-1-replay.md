# ACTOR AI 살리기 ① 재생기 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ACTOR 재생이 실패하기 직전에 AI가 막힌 단계를 풀어(대신 누를 것 고르기·끼어든 화면 미루기) 기록의 다음 단계로 이어 가게 한다.

**Architecture:**
- 새 파일 `ai_rescue.py`: AI에게 묻기(Anthropic SDK), 개인정보 가리기, AI 고름 거르기를 맡는다. 브라우저를 모른다.
- `web_replay.py` 의 `Replayer`:
  - 후보 모으기
  - `_find` 의 첫 회차 끝에 살리기 끼우기
  - 누른 뒤 이어졌는지 보기
- `web_runner.py`: ACTOR에서만 AI를 붙이고 횟수를 지표로 남긴다.
- `rpa_status.py`: PC에 둔 AI 설정(켬·키)을 읽고 쓴다. 웹에서 내려 주는 일은 계획 ②가 한다.

**Tech Stack:** Python 3.14, Playwright(깔린 Edge, headless), Anthropic Python SDK(`anthropic`), 평범한 파이썬 시험 스크립트

**Spec:** docs/superpowers/specs/2026-11-16-actor-ai-rescue-design.md

## Global Constraints

- **꺼져 있거나 AI를 못 쓰면 지금과 똑같이 돈다.** 기존 재생 시험과 `tests/test_popup_relocate.py` 가 그대로 통과해야 한다.
- AI 모델 `AI_MODEL = "claude-haiku-5-5"` (사용자 결정 2026-11-16: Opus는 이 일에 지나치다).
  - 번호 하나를 고르는 좁은 판단이고, 위험은 우리 코드가 거른다.
  - 손 시험(Task 5)에서 Sonnet 5.5(`claude-sonnet-5-5`)와 비교하고, 틀리면 상수만 바꾼다.
  - 답 모양은 `output_config.format`(json_schema)으로 받는다. `tool_choice` 강제는 쓰지 않는다.
  - Haiku 5.5는 서버 쪽 거절 대체가 없다. 거절(`stop_reason == "refusal"`)은 `AiUnavailable("AI가 답하지 않음")` 이다.
- 상수 (모두 `ai_rescue.py`):
  - `AI_TIMEOUT_SEC = 60`, SDK `max_retries=1`
  - `STEP_ACTS_MAX = 3` (한 단계에 AI가 누르는 수)
  - `RUN_CALLS_MAX = 5` (사이트 한 번 재생에 AI를 부르는 수)
  - `CANDIDATES_MAX = 150`, `CAND_TEXT_MAX = 40`, `SCREEN_TEXT_MAX = 2000` (창마다), `FOLLOW_WAIT = 5.0`
- 미루기 낱말 `DEFER_WORDS`:
  - 한국어: 닫기, 다음에, 나중에, 일 후에 보기, 일간 보지 않기, 오늘 하루 보지 않기, 오늘하루 보지않기, 오늘 하루 열지 않기, 다시 보지 않기, 건너뛰기
  - 영어: close, later, skip, not now, x, ×
- [확인]류 `CONFIRM_WORDS`: 확인, ok
- 위험 낱말 `RISK_WORDS`: 동의, 결제, 구매, 주문하기, 삭제, 변경, 신청, 전송, 발송, 등록, 저장, 승인, 해지, 탈퇴, 취소, 출고, 확정
- 결과 글:
  - `AI가 고름: '{고른 글}' (기록: '{기록 글}')`
  - `AI가 닫음: '{고른 글}'`
- 실패 글:
  - `AI가 고른 것을 눌렀지만 이어지지 않음`
  - 못 찾음 끝에 ` (AI: {AI가 본 화면 한 줄})` 또는 ` (AI 도움을 쓰지 못함: {까닭})`
- 비밀번호·입력 칸 값·화면 사진은 AI에게 보내지 않는다. 키는 로그·결과 글·실패 사진 이름 어디에도 쓰지 않는다.
- 옵저버 미리보기에서는 AI를 붙이지 않는다 (`rpa_observer.py` 는 손대지 않는다).
- 화면 글은 `docs/ui-wording.md` 의 업무 서식 말투를 따른다.
- 커밋은 사용자가 시킬 때만 한다.

## Review Focus

1. AI가 고른 것이 거르기를 지나도 엉뚱한 일을 하는 경우.
   - 예: 표 줄 링크가 '삭제'인데 글이 '선택'인 경우. 위험 낱말 거르기는 글만 본다.
   - Task 3 시험 'R6'은 고른 요소가 든 레이어 글까지 보는지 확인한다. 표 줄은 레이어가 아니라 못 막는다. 이 한계는 알려진 한계로 끝 보고에 올린다.
2. 후보에 붙인 표시(`data-ap-ai`)가 사이트 화면에 남아 사이트 스크립트를 깨뜨리는 것.
   - Task 2 시험 'C3': 살리기가 끝나면 표시가 하나도 남지 않는다.
3. AI 응답이 늦을 때 병렬 수집의 인증 차례(`gate`)를 오래 쥐는 것.
   - 인증 구간(`auth_start`~`auth_end`) 안의 단계는 AI를 부르지 않는다 (Task 3).
   - 시험 'R12'.
4. 보내는 글에 고객 비밀번호·전화·이메일·입력 값이 섞이는 것.
   - Task 1 시험 'M1~M5', Task 3 시험 'R11'(실제 재생에서 가짜 AI가 받은 글을 검사).
5. AI가 같은 미루기 단추를 계속 골라 헤매는 것.
   - 같은 요소를 두 번 고르면 그만한다 (Task 3).
   - 시험 'R8'.

---

### Task 0: Anthropic SDK 들이기 (빌드 파일 고침 - 사용자에게 먼저 알림)

**Files:**
- Modify: `tools/build_release.py:142-146` (라이브러리 묶음 목록 `lib.zip`) 와 옛 onefile 방식의 포함 목록
- 시험: `tools/build_release.py --modules` 의 `--check`

- [ ] **Step 1:** 사용자에게 알린다: "Anthropic SDK와 딸린 라이브러리를 .venv에 새로 깔고 빌드 목록에 더합니다. 업데이트 크기가 몇 MB 늘어납니다." 기존 패키지는 올리지 않는다.
- [ ] **Step 2:** `.venv\Scripts\python.exe -m pip install anthropic`
  - 깔린 판을 적는다.
  - `importlib.metadata.requires("anthropic")` 로 딸린 패키지의 최상위 모듈 이름을 모은다 (httpx2·pydantic·pydantic_core·anyio·jiter·distro·certifi·idna 등).
- [ ] **Step 3:** 그 이름들을 라이브러리 묶음 목록에 더한다. 옛 onefile 방식에도 같은 포함을 더한다.
- [ ] **Step 4:** `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe tools/build_release.py --modules --no-setup` 를 돌린다.
  - 기대: `--check` 가 `ModuleNotFoundError` 없이 끝 줄을 찍는다.
  - 빠진 모듈이 나오면 목록에 더하고 다시 돌린다.
- [ ] **Step 5:** 깔린 판·더한 목록을 장부(`.superpowers/sdd/2026-11-16-actor-ai-rescue-1-replay/progress.md`)에 적는다.

### Task 1: `ai_rescue.py` - 가리기·거르기·묻기

**Files:**
- Create: `ai_rescue.py`
- Create: `tests/test_ai_rescue.py` (이 Task는 브라우저 없는 절)

**Interfaces (Produces):**
- `mask(text: str, secrets: Iterable[str] = ()) -> str`
  - 전화(`0\d{1,2}[-. ]?\d{3,4}[-. ]?\d{4}`), 이메일, 6자리 넘는 숫자 줄(하이픈 섞임 포함), `secrets` 의 비지 않은 값 → `***`
- `classify(text: str) -> str`
  - `"defer"`: `DEFER_WORDS` 가운데 하나를 포함. `x`·`×` 는 글 전체가 그것일 때만.
  - `"confirm"`: 글 전체(공백·대소문자 무시)가 `CONFIRM_WORDS` 가운데 하나.
  - `"substitute"`: 그 밖
- `risk_words(text: str) -> set[str]`
- `allowed(kind: str, text: str, container: str, target_text: str, info_only: bool, step_kind: str, el: dict) -> tuple[bool, str]`
  - 규칙 (설계 '우리 코드가 AI의 고름을 다시 거른다'):
    - `container` (레이어·대화상자·기록에 없던 창의 글)와 `text` 의 위험 낱말 가운데 `target_text` 에 없는 것이 있으면 거절한다.
    - `"confirm"` 은 위 조건에 더해 `info_only` 가 참이어야 한다.
    - `"substitute"` 는 `el` 의 종류가 단계에 맞아야 한다:
      - `fill`: input(text·search·email·tel·number·없음)·textarea. password는 안 됨.
      - `select`: select
      - `check`: checkbox·radio
      - `click`·`enter`: 아무 요소
    - `"defer"`·`"confirm"` 은 누를 수 있는 요소일 때만 된다 (a·button·[role=button]·input[type=button|submit]).
  - 거절 까닭(사람 말)을 돌려준다.
- `class AiUnavailable(Exception)` - `str(e)` 는 까닭 한 마디: "키 없음", "키가 끊김", "사용 한도", "시간 초과", "인터넷 오류", "AI 서버 오류", "AI가 답하지 않음", "답 모양 틀림"
- `class Answer(NamedTuple)`: `choice: int | None`, `info_only: bool`, `reason: str`, `screen: str`
- `ANSWER_SCHEMA: dict`
  - 속성: `choice`(integer, -1 = 없음), `info_only`(boolean), `reason`(string), `screen`(string)
  - 모두 required, `additionalProperties: false`
- `SYSTEM_PROMPT: str` (고정 글). 지시할 것:
  - 후보 번호 가운데서만 고른다.
  - 기록한 단계의 뜻과 같은 것을 고른다.
  - 끼어든 화면은 미루는 단추를 고른다.
  - 동의·결제·신청·삭제는 고르지 않는다.
  - 모르면 -1을 고른다.
  - `info_only` 는 그 레이어가 순수한 안내일 때만 참이다.
  - `reason`·`screen` 은 한국어 한 줄(60자 안)로 쓴다.
- `build_prompt(step: dict, before: list[str], after: list[str], windows: list[dict], cands: list[dict]) -> str`
  - `windows`: `{"no", "title", "path", "screen"}`
  - `cands`: `{"n", "tag", "role", "type", "text", "label", "where", "overlay"}`
  - 이미 가린 글만 받는다. 이 함수는 가리지 않는다.
- `class Claude`:
  - `__init__(self, key: str, model: str = AI_MODEL, timeout: float = AI_TIMEOUT_SEC)`
  - `choose(self, system: str, user: str) -> Answer`
  - `client.messages.create(model, max_tokens=2000, system, messages=[user], output_config={"format": {"type": "json_schema", "schema": ANSWER_SCHEMA}})`
    - 응답의 첫 text 블록을 `json.loads` 한다.
    - 쓴 토큰(`usage.input_tokens`·`output_tokens`)은 `Answer` 와 함께 로그 한 줄로 남긴다 (비용 대조용).
  - SDK 오류를 위 `AiUnavailable` 까닭으로 바꾼다:
    - `AuthenticationError`·`PermissionDeniedError` → 키가 끊김
    - `RateLimitError` → 사용 한도
    - `APITimeoutError` → 시간 초과
    - `APIConnectionError` → 인터넷 오류
    - 5xx `APIStatusError` → AI 서버 오류
    - `refusal` → AI가 답하지 않음
    - JSON·범위 오류 → 답 모양 틀림
  - `choice == -1` 은 `None` 으로 바꾼다.
- `from_settings(cfg: dict | None) -> Claude | None` - `cfg` 가 `{"on": True, "key": "…"}` 이고 키가 비지 않았을 때만 만든다.

- [ ] **Step 1: 시험을 쓴다** (`tests/test_ai_rescue.py`, 이 절은 브라우저 없음. 기존 시험처럼 `check(name, cond)` 와 끝의 `실패: 없음`)
  - M1: `mask("주문자 010-1234-5678 / a@b.co.kr")` 에 `010`·`@` 가 없다
  - M2: `mask("주문번호 2026111612345")` 에 그 숫자가 없다. `mask("3건")` 은 그대로다
  - M3: `mask("pw는 Abc!234", ["Abc!234"])` 에 `Abc!234` 가 없다
  - M4: `mask("02 345 6789")` 는 가린다
  - M5: `mask("", ["x"])` 는 `""` 이다
  - K1: `classify("오늘 하루 보지 않기") == "defer"`, `classify("90일 후에 보기") == "defer"`, `classify("×") == "defer"`, `classify("Excel") == "substitute"`
  - K2: `classify("확인") == "confirm"`, `classify(" OK ") == "confirm"`, `classify("확인하기") == "substitute"`
  - A1: `allowed("defer", "닫기", "", "엑셀받기", False, "click", {"tag": "button"})[0]` 이 참
  - A2: `allowed("confirm", "확인", "공지사항 점검 안내", "엑셀받기", True, "click", BTN)[0]` 이 참이고, `info_only=False` 면 거짓
  - A3: `allowed("confirm", "확인", "서비스를 신청하시겠습니까?", "엑셀받기", True, "click", BTN)[0]` 이 거짓
  - A4: `allowed("substitute", "확인", "서비스를 신청하시겠습니까?", "확인", False, "click", BTN)[0]` 이 거짓 (레이어 글의 '신청')
  - A5: `allowed("substitute", "주문취소", "", "주문조회", False, "click", BTN)[0]` 이 거짓. `allowed("substitute", "저장하기", "", "저장", False, "click", BTN)[0]` 은 참
  - A6: `allowed("defer", "동의하고 닫기", "", "엑셀받기", False, "click", BTN)[0]` 이 거짓 ('동의')
  - A7: `allowed("substitute", "", "", "검색어", False, "fill", {"tag": "input", "type": "password"})[0]` 이 거짓, type `text` 면 참
  - S1: `ANSWER_SCHEMA` 의 required 가 네 칸 모두, `additionalProperties is False`
  - U1: 가짜 SDK 클라이언트로 `Claude.choose`:
    - `RateLimitError` → `AiUnavailable("사용 한도")`
    - `refusal` → "AI가 답하지 않음"
    - 글 `'{"choice": -1, …}'` → `Answer(None, …)`
    - 글 `'{"choice": "a"}'` → "답 모양 틀림"
    - `Claude` 가 클라이언트를 바꿔 끼울 수 있게 `client` 인자(기본 None → `anthropic.Anthropic(api_key=key, timeout=…, max_retries=1)`)를 둔다.
  - U2: `from_settings(None) is None`, `from_settings({"on": True, "key": ""}) is None`, `from_settings({"on": False, "key": "k"}) is None`
- [ ] **Step 2:** `.venv\Scripts\python.exe tests\test_ai_rescue.py` → 모듈이 없어 실패하는지 본다.
- [ ] **Step 3:** 위 Interfaces대로 `ai_rescue.py` 를 쓴다. Playwright를 가져오지 않는다 (에이전트도 가져올 수 있게).
- [ ] **Step 4:** 다시 돌린다. 기대: `실패: 없음`.

### Task 2: 후보 모으기 (`Replayer._ai_candidates`)

**Files:**
- Modify: `web_replay.py` (`Replayer` 에 메서드, 상수 근처에 JS 한 덩이)
- Test: `tests/test_ai_rescue.py` (브라우저 절 시작 - 가짜 쇼핑몰 서버)

**Interfaces (Produces):**
- `Replayer._ai_candidates(self, i: int, s: dict, here) -> tuple[list[dict], list[dict]]` → `(cands, windows)`
  - `cands` 항목:
    - 공개 칸: `n`, `tag`, `role`, `type`, `text`, `label`, `where`("창 N·틀 이름"), `overlay`(bool)
    - 안쪽 칸 (AI에게 안 감): `page`, `frame`, `loc`(`frame.locator('[data-ap-ai="n"]')`), `container`(레이어 글 300자), `sig`
  - 모으는 곳:
    - `here` 를 먼저, 그다음 `_other_pages(here)`
    - 창마다 틀은 `FRAME_PROBE_MAX + 1` 개까지
    - 합쳐서 `CANDIDATES_MAX` 개까지. 레이어 안 요소와 `here` 의 요소를 앞에 둔다.
  - 요소 고르기 (JS 한 번에, 틀마다):
    - 선택자: `a[href], a[onclick], button, input:not([type=hidden]), select, textarea, [role=button], [role=link], [role=menuitem], [role=tab], [onclick]`
    - 보이는 것만 (크기 > 0, `visibility`·`display`)
    - 글은 `TEXT_OF` 와 같은 규칙. 입력 칸은 값을 읽지 않고 placeholder·aria-label·연결된 label 글만 읽는다.
    - `overlay`: 조상에 `[role=dialog]`·`[aria-modal=true]`·`<dialog>`, 또는 `position: fixed|absolute` 이면서 화면 넓이 30% 넘는 상자가 있음. 또는 그 창이 기록에 없던 창.
    - `container`: 그 상자의 글 앞 300자. 레이어가 아니면 빈 글.
    - 표 본문 안 요소는 자기 글만 싣고, 둘레 칸 글은 싣지 않는다.
  - 파일 받기 단계이고 기준(`self.baseline.get(i)`)이 비지 않았으면, 기준에 있던 `sig` 의 요소는 뺀다. `sig` 는 `_snapshot` 과 같은 `SIGS_JS` 규칙이다.
  - `windows`: 창마다 `{"no", "title", "path", "screen"}`. `screen` 은 제목(h1~h3)과 레이어 글을 이어 `SCREEN_TEXT_MAX` 까지.
  - 공개 칸의 글과 `screen` 은 모두 `ai_rescue.mask(…, self.creds.values())` 를 거친다. 글은 `CAND_TEXT_MAX` 로 자른다.
- `Replayer._ai_clear(self)`: 모든 창·틀에서 `data-ap-ai` 속성을 지운다 (오류는 삼킴).

- [ ] **Step 1: 시험을 쓴다** (가짜 쇼핑몰 `ThreadingHTTPServer` - `test_popup_relocate.py` 의 서버 모양을 따른다)
  - 화면:
    - 주문 화면: [엑셀받기] 버튼 한 개, 검색 칸(값 '홍길동'), 표 한 줄(주문자 '김철수 010-1111-2222', 링크 [다운로드])
    - 공지 레이어(`role=dialog`, '점검 안내', [오늘 하루 보지 않기])
  - C1: 후보에 [엑셀받기]·[다운로드]·검색 칸·[오늘 하루 보지 않기] 가 있다. 레이어 단추만 `overlay` 가 참이다.
  - C2: 공개 칸·`windows` 를 JSON으로 바꾼 글에 `홍길동`·`010-1111-2222`·`김철수` 가 없다. 표 둘레 칸 글은 싣지 않는다.
  - C3: `_ai_clear()` 뒤 `document.querySelectorAll('[data-ap-ai]').length == 0` (Review Focus 2)
  - C4: 파일 받기 단계에서 기준에 [다운로드] 의 `sig` 를 넣으면 후보에서 빠진다
- [ ] **Step 2:** 돌려서 실패하는지 본다.
- [ ] **Step 3:** 구현.
- [ ] **Step 4:** 돌린다. 기대: C1~C4 통과.

### Task 3: 살리기 (`_ai_rescue`) 와 `_find`·`_step` 끼우기

**Files:**
- Modify: `web_replay.py`
  - `Replayer.__init__`
  - `_find`
  - `_step`
  - 새 메서드 `_ai_ok`, `_ai_rescue`, `_ai_followed`
  - 새 예외 `Rescued`
- Test: `tests/test_ai_rescue.py` (재생 절)

**Interfaces:**
- Consumes: Task 1 `mask`·`classify`·`allowed`·`build_prompt`·`SYSTEM_PROMPT`·`Answer`·`AiUnavailable`, Task 2 `_ai_candidates`·`_ai_clear`
- Produces:
  - `Replayer.ai` (기본 `None`): `choose(system, user) -> Answer` 를 가진 것
  - `Replayer.ai_calls: int`, `Replayer.ai_saved: int` (살린 단계 수), `Replayer.ai_down: str | None` (못 쓰게 된 까닭)
  - `class Rescued(Exception)`: `args = (page, frame, loc, how, sub)`. `sub` 는 대신 누르기면 참.
  - `_find(self, page, s, prev, loose=False, quick=False, elsewhere=None, rescue=None)`
    - `rescue`: 인자 없는 함수. 첫 회차(`tries == 1`) 끝에서 `elsewhere()` 가 아무것도 못 준 뒤 한 번 부른다.
    - `(page, frame, loc, how, sub)` 를 돌려주면 `Rescued` 를 던진다.
    - `None` 이면 지금처럼 남은 회차를 돈다.
  - `_ai_ok(self, i, s) -> bool`
    - `self.ai` 가 있고, `ai_down` 이 없고, `ai_calls < RUN_CALLS_MAX`
    - `s["kind"] in ("click", "fill", "select", "check", "enter")`, `target` 있음
    - `optional`·`credential`·`pick`·`loose`·`mailOpen`·`mailLink`·`mailSend`·`otpSend` 아님, 메일함 창 단계 아님
    - 인증 구간 안이 아님 (`auth_start(steps) <= i+1 <= auth_end(steps)` 이면 거짓, Review Focus 3)
  - `_ai_rescue(self, i, s, here) -> tuple | None` (아래 알고리즘)
  - `_ai_followed(self, i, s, page, before) -> bool`
    - 대신 누른 뒤 `FOLLOW_WAIT` 초 안에 넷 가운데 하나가 일어났나:
      - 다음 단계 대상이 어느 창에 보임 (`_probe`)
      - `url_path(page.url)` 바뀜
      - 창 수 늘어남
      - 고른 요소가 든 레이어가 사라짐
    - `before = (경로, 창 수, 레이어 요소 핸들 | None)`

`_ai_rescue` 알고리즘 (signature·테스트로 정해지지 않는 부분):

```
picked = set()
for _ in range(STEP_ACTS_MAX):
    if not self._ai_ok(i, s): return None
    cands, windows = self._ai_candidates(i, s, here)
    try:
        ans = self.ai.choose(SYSTEM_PROMPT, build_prompt(step_info, before_texts, after_texts, windows, public(cands)))
    except AiUnavailable as e:
        self.ai_down = str(e); self.log(f"      AI 도움을 쓰지 못함: {e}"); return None
    finally:
        self.ai_calls += 1
    # 표시(data-ap-ai)는 고른 요소를 누를 때까지 남긴다: 미루기는 아래에서 누른 뒤 _ai_clear(),
    # 대신 누르기는 _step 이 행동한 뒤 _ai_clear(), 그 밖에 None 을 돌려주는 모든 길에서는 돌려주기 전에 _ai_clear()
    self.log(f"      AI: {ans.reason}")
    if ans.choice is None or not 0 <= ans.choice < len(cands):
        self.ai_note = ans.screen; return None
    c = cands[ans.choice]
    if c["sig"] in picked: self.ai_note = "같은 것을 다시 고름"; return None        # Review Focus 5
    picked.add(c["sig"])
    kind = classify(c["text"])
    ok, why = allowed(kind, c["text"], c["container"], s["target"]["text"], ans.info_only, s["kind"], c)
    if not ok: self.ai_note = f"'{c['text']}' 은(는) 누르지 않음 - {why}"; return None
    if kind == "substitute":
        return c["page"], c["frame"], c["loc"], f"AI가 고름: '{c['text']}' (기록: '{s['target']['text']}')", True
    c["loc"].click(timeout=4000); 누른 글을 closed 목록에 더함; wait 500ms
    기록대로 다시 찾기: here 와 _other_pages 에서 _probe(pg, s, prev, loose) → 찾으면
        frame, loc, how = self._find(pg, v, prev, loose, quick=True)
        return pg, frame, loc, how + ", " + ", ".join(f"AI가 닫음: '{t}'" for t in closed), False
return None
```

- `_step` 에서 바뀌는 것:
  - `_find(…, rescue=(lambda: self._ai_rescue(i, s, page)) if self._ai_ok(i, s) else None)`
  - `except Rescued as r`: `page, frame, loc, how = r.args[:4]`
    - 다른 창이면 `_move` 로 번호를 고쳐 잡는다. `_take` 와 같은 규칙으로, 기준도 다시 잡는다.
    - `sub` 면 행동 전에 `before` 를 잡는다.
    - 행동 뒤(새 창·파일 받기가 아닌 단계) `_ai_followed` 가 거짓이면 `NotFound("AI가 고른 것을 눌렀지만 이어지지 않음")`.
  - 창이 없을 때 (`got is None`, 공지 Skip 앞): `_ai_ok` 면 `_ai_rescue(i, s, None)` 를 한 번 부른다.
    - 결과가 있으면 그 `page/frame/loc` 로 바로 행동으로 간다. `_find` 를 건너뛰도록 흐름을 나눈다.
  - `except NoTarget as e` 와 창 없음 `NotFound` 에 덧붙임:
    - `self.ai_note` 가 있으면 글 끝에 ` (AI: {note})`
    - `self.ai_down` 이면 ` (AI 도움을 쓰지 못함: {ai_down})`
    - 덧붙인 뒤 `ai_note` 를 비운다.
  - 단계가 성공으로 끝나고 이 단계에서 `Rescued` 가 있었으면 `self.ai_saved += 1`.

- [ ] **Step 1: 시험을 쓴다** (실제 `Recorder` 로 옛 화면을 기록하고, 서버 모드를 바꿔 재생. 가짜 AI는 `FakeAi(answers)`: `choose` 가 차례로 `Answer` 를 돌려주고 받은 `user` 글을 모은다. `answers` 가 다 떨어지면 `Answer(None, False, "", "")`. 재생 설정 `step_timeout=3, step_tries=2`. 서버가 진짜·엉뚱한 누르기를 센다.)
  - R1 단추 글 바뀜 ('엑셀받기' → '엑셀 다운로드'), AI가 그 번호 → 성공. 결과 글에 `AI가 고름: '엑셀 다운로드' (기록: '엑셀받기')`. `ai_saved == 1`
  - R2 공지 레이어 [오늘 하루 보지 않기] 가 [엑셀받기] 를 덮어 못 찾음 → AI가 닫기 번호 → 성공. `AI가 닫음: '오늘 하루 보지 않기'`
    - 가림 판정이 아니라 못 찾음이 되도록, 레이어가 대상 위에 있고 대상이 `display:none` 으로 숨는 화면으로 만든다.
  - R3 약관 동의 레이어 [동의] 만, AI가 [동의] 번호 → 눌리지 않음(엉뚱한 누르기 0), 실패. 사유에 `(AI:` 가 있다
  - R4 안내 레이어('점검 안내') [확인] 만, AI `info_only=True` → 누르고 성공
  - R5 '신청하시겠습니까?' 레이어 [확인], AI `info_only=True` → 안 누름, 실패
  - R6 R5 와 같은데 AI가 [확인] 을 대신 누르기로 답해도 (기록 대상이 '확인'인 기록) → 안 누름 (Review Focus 1)
  - R7 AI가 [주문취소] (기록 [주문조회]) → 안 누름, 실패
  - R8 AI가 같은 미루기 단추를 두 번 → 두 번째에 그만, 실패 (Review Focus 5)
  - R9 대신 누른 뒤 아무 일도 안 일어남 → `AI가 고른 것을 눌렀지만 이어지지 않음`
  - R10 두 단계가 연달아 바뀜 (메뉴 글·단추 글 둘 다) → 둘 다 살리고 성공, `ai_saved == 2`, `ai_calls == 2`
  - R11 R1 재생에서 가짜 AI가 받은 `user` 글에 아이디·비밀번호 값, 검색 칸 값, 전화·이메일이 없다 (Review Focus 4)
  - R12 인증 구간 안 단계(otp 앞 [인증번호 받기] 글 바뀜) → AI를 부르지 않음 (`ai_calls == 0`), 지금과 같은 실패 (Review Focus 3)
  - R13 `ai` 가 `AiUnavailable("시간 초과")` 를 던짐 → 실패 사유 끝에 `(AI 도움을 쓰지 못함: 시간 초과)`, 다음 단계부터 AI를 부르지 않음
  - R14 파일 받기 단계, 기준이 있고 AI가 옛 줄 [다운로드] 를 고르려 해도 후보 번호에 없음 → 새 줄만 후보
  - R15 `ai is None` 이면 R1 화면에서 지금과 같은 실패 글(`초씩 2번 찾았으나`)이고, 덧붙인 말이 없다
  - R16 `RUN_CALLS_MAX` 를 넘으면 더 부르지 않음 (가짜 AI가 6번째 호출을 받지 않음)
- [ ] **Step 2:** 돌려서 R1~R16 이 실패하는지 본다 (R15 는 이미 통과할 수 있다).
- [ ] **Step 3:** 구현.
- [ ] **Step 4:** 돌린다. 기대: `실패: 없음`.

### Task 4: ACTOR에 붙이기·PC 설정·지표

**Files:**
- Modify: `rpa_status.py` (설정 읽기·쓰기)
- Modify: `web_runner.py:1434` 근처 (Replayer 만든 뒤, `rp.run()` 뒤)
- Test: `tests/test_ai_rescue.py` (설정 절), 기존 `tests/test_presets.py`

**Interfaces (Produces - 계획 ②의 에이전트가 쓴다):**
- `rpa_status.AI_NAME = "ai.json"`, 자리는 `os.path.join(data_dir(), AI_NAME)`
- `rpa_status.ai_settings() -> dict | None`
  - `{"on": bool, "key": str}`. 키는 `unseal` 한 평문이다.
  - 파일이 없거나 깨졌거나 풀 수 없으면 `None`. 예외를 내지 않는다.
- `rpa_status.set_ai(on: bool, key: str | None) -> None`
  - `key` 는 `seal` 해서 적는다. `on` 이 거짓이거나 `key` 가 None·빈 글이면 키를 지운다.
  - 같은 값이면 파일을 다시 쓰지 않는다.
- ACTOR:
  - `rp.ai = ai_rescue.from_settings(status.ai_settings())`
  - 재생 뒤 `rp.ai_calls` 가 1 이상이면 `status.metric(f"{name}:ai", "AI 도움", rp.ai_saved, total=rp.ai_calls, unit="번")`
  - 켜졌으면 시작 로그 한 줄: `  [{name}] AI 도움 사용` (키는 쓰지 않음)

- [ ] **Step 1: 시험을 쓴다**
  - P1: 임시 데이터 폴더로 `set_ai(True, "sk-test")` → 파일 글에 `sk-test` 가 없다 (`dpapi:` 로 시작). `ai_settings() == {"on": True, "key": "sk-test"}`
  - P2: `set_ai(False, None)` → `ai_settings()["on"] is False`, 키 칸 없음
  - P3: 깨진 JSON 파일 → `ai_settings() is None`
  - P4: `web_runner` 의 재생기 만들기를 가짜 설정으로 돌려 `rp.ai` 가 `Claude` 인지 본다. 설정이 없으면 None. 실제 API는 부르지 않는다.
- [ ] **Step 2:** 실패 확인 → **Step 3:** 구현 → **Step 4:** 통과 확인 (`실패: 없음`).

### Task 5: 기존 시험·손 시험·문서

- [ ] AI를 붙이지 않은 상태(기본)에서 기존 재생 시험을 모두 돌린다. 기대: 모두 실패 없음.
  - `tests/test_popup_relocate.py`, `test_notice_popup`, `test_popup_rule`, `test_step_tries`, `test_web_replay`, `test_otp_replay`, `test_mail_otp_replay`, `test_mail_otp_record`, `test_mail_pick`, `test_download_check`, `test_edge`, `test_excel_upload`, `test_find_nested_text`, `test_hover_menu`, `test_nexacro_record`, `test_page_tamper`, `test_parallel_collect`, `test_presets`, `test_same_dropdowns`, `test_step_wait`, `test_typed_nav`, `stress_web_replay`
  - `test_import_step.py` 는 뺀다.
  - `tests/test_observer_edit.py` 는 Edge 창이 뜨므로 사용자에게 먼저 알린다.
- [ ] **손 시험 (실제 API, 사용자 승인 뒤에만)**: 사용자가 준 시험용 키로 R1~R10 화면을 Haiku 5.5와 Sonnet 5.5로 한 번씩 돌린다.
  - 모델마다 고른 번호(맞음·틀림), 걸린 초, 쓴 토큰(`usage`)을 표로 장부에 적고 사용자에게 보고한다.
  - Haiku가 틀린 경우가 있으면 그 화면과 Sonnet 결과를 함께 보여 주고, 모델은 사용자가 정한다.
  - 키는 환경 변수로만 넘기고 파일·로그에 남기지 않는다.
- [ ] `graphify update .`
- [ ] 사용자에게 보고한다. 커밋·새 버전은 지시를 기다린다.
