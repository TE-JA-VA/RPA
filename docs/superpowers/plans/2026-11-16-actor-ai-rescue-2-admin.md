# ACTOR AI 살리기 ② 관리 화면·업체 웹·키·과금 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 우리가 관리 화면에서 업체마다 AI 도움을 켜고 키를 넣으면 그 업체 PC에 닿고, 월정액·포함 횟수·누진 구간으로 이번 달 추가 금액을 미리 보여 준다.

**Architecture:**
- **켬·끔**: `meta/companies/{cid}/apps/rpa/features/ai` (RTDB, 웰라이프 켬과 같은 자리)
- **키**: 그 업체 에이전트만 읽는 `apps/rpa/aikey/{cid}` (RTDB)
- **에이전트**: 10분 정책 읽기에서 둘을 읽어 PC에 둔다 (계획 ①의 `rpa_status.set_ai`).
- **사용 기록**: 실행 기록 문서(Firestore `runs/{cid}/items`)에 `ai: {saved, called}` 를 싣는다.
- **요금표**: Firestore `aiPlans/default`·`aiPlans/{cid}`
- **보이는 곳**: 관리 화면이 월 합계와 금액을, 업체 웹이 이번 달 살린 횟수를 보여 준다.

**Tech Stack:** Node(관리 화면 `firebase/admin` - admin.js·routes.js·ops.js·AFTERMARKET_SETUP.html), Firebase RTDB·Firestore 규칙, 업체 웹(`firebase/web`), 에이전트(`firebase/agent/agent.py`), 에뮬레이터 시험

**Spec:** docs/superpowers/specs/2026-11-16-actor-ai-rescue-design.md

**선행:** 계획 ① (`docs/superpowers/plans/2026-11-16-actor-ai-rescue-1-replay.md`). 아래를 쓴다:
- Task 4의 `rpa_status.ai_settings()`·`set_ai(on, key)`
- 지표 `"{사이트}:ai"` (value = 살린 수, total = 부른 수)

## Global Constraints

- **키는 어디에도 글로 남기지 않는다.**
  - 관리 기록(`관리_기록.txt`)·응답 본문·로그·업체 웹 모두 해당한다.
  - 관리 화면은 `…` + 끝 4글자만 보여 준다.
- 키 모양: `sk-ant-` 로 시작하고 공백이 없다. 아니면 거절: "Anthropic API 키는 sk-ant-로 시작합니다."
- 켜는 곳의 안내 글 (관리 화면·업체 웹 같은 글): "막힌 단계의 화면 글을 개인정보를 가린 뒤 AI(Anthropic)가 처리합니다."
- **업체는 웹에서 끄지 못한다.** 업체 웹은 보여 주기만 한다.
- 세는 단위는 'AI가 살린 단계'(`ai.saved`)다. 부른 수(`ai.called`)는 함께 보여 주기만 한다.
- 요금표 모양 `{"monthly": 원, "included": 횟수, "tiers": [{"to": 횟수 | null, "price": 원}, …]}`.
  - `tiers` 는 `to` 가 커지는 차례이고, 첫 `to` 는 `included` 보다 크며, 마지막 `to` 는 `null` 이다.
  - 업체 요금표는 칸마다 기본값을 덮는다 (비운 칸은 기본값). 업체별 토큰 배율과 같은 방식이다.
- 금액 계산 `aiCharge(plan, saved)`:
  - `monthly + Σ 구간마다 max(0, min(saved, to ?? ∞) − 앞 구간 끝) × price`
  - 첫 구간의 앞 끝은 `included` 다.
- 실제 Anthropic 비용 대조는 이번에 자동으로 하지 않는다. 관리 화면에 키 끝 4글자를 보여 주어 콘솔에서 사람이 맞춰 본다. Admin API 연동은 나중이다.
- 화면 글은 `docs/ui-wording.md` 업무 서식 말투를 따른다.
- 커밋은 사용자가 시킬 때만 한다.

## Review Focus

1. **옛 버전 PC가 있는 업체에서 AI를 켜는 경우.** 웹은 "사용 중"인데 PC는 AI를 모른다.
   - `setAi` 는 업체의 모든 PC가 `live.ai_ready` 를 올린 뒤에만 켜게 한다. 프리셋 수 41개 이상과 같은 방식이다.
   - Task 2 시험 'AD5'.
2. **끄고 나서도 PC에 키가 남는 경우.**
   - 에이전트가 꺼짐을 읽으면 `set_ai(False, None)` 으로 PC의 키를 지운다.
   - Task 1 시험 'AG3'.
3. **비활성화한 업체(stts 9)의 에이전트가 키를 읽는 경우.**
   - 규칙에서 막는다.
   - Task 1 시험 'RU3'.
4. **업체 웹이 5초마다 오는 상태(heartbeat)에 맞춰 Firestore 합계를 다시 읽어 사용량이 느는 경우.**
   - 환경설정을 열 때 한 번만 읽는다.
   - Task 4 시험 'W4'.
5. **요금표를 잘못 넣는 경우.** 구간 차례가 틀리거나, 음수이거나, 마지막이 null이 아닌 경우.
   - 저장을 거절한다. 계산이 틀린 금액을 보여 주지 않게 하려는 것이다.
   - Task 2 시험 'AD7'.

---

### Task 1: 규칙·에이전트·실행 기록

**Files:**
- Modify: `firebase/rules/database.rules.json`
  - 새 자리 `apps/rpa/aikey/$cid`
    - `.read`: `auth.token.role === 'agent' && auth.token.cid === $cid && root.child('meta/companies/'+$cid+'/stts').val() !== 9`
    - `.write`: false (Admin SDK만)
- Modify: `firebase/rules/firestore.rules`
  - `validUsage` 에 더한다: `&& (!('ai' in d) || (d.ai is map && d.ai.saved is int && d.ai.called is int && d.ai.saved >= 0 && d.ai.called >= d.ai.saved))`
  - 새 `match /aiPlans/{doc}` 의 `read`:
    - `doc == 'default'` 이면 로그인했고 role이 phone이 아님
    - 그 밖이면 `sameCompany(doc)`
  - `write`: false
- Modify: `firebase/rules/firestore.indexes.json`
  - `runs` 의 `items` 컬렉션에 (`started_at` ASC, `ai.saved` ASC), (`started_at` ASC, `ai.called` ASC)
- Modify: `firebase/agent/agent.py`
  - `ai_policy(client, cid) -> tuple[bool, str | None]`
    - `features.ai is True` 면 `apps/rpa/aikey/{cid}/key` 를 읽는다.
    - 못 읽으면 예외. 부르는 쪽이 지난 값을 둔다.
  - `Policy.refresh` 가 `company_policy` 다음에 `ai_policy` 를 불러 `st.set_ai(on, key)` 한다.
    - 실패는 로그 한 줄로 남긴다. 키는 쓰지 않는다.
  - 에이전트가 올리는 live에 `ai_ready: True` 를 싣는다 (`preset_max` 와 같은 자리).
  - `run_doc`: `rec["metrics"]` 에서 key가 `:ai` 로 끝나는 것들을 더한다.
    - `saved` = value 합, `called` = total 합
    - `called > 0` 이면 `doc["ai"] = {"saved", "called"}`
- Test:
  - `firebase/tests/rules.test.js`
  - `firebase/tests/test_agent.py`
  - `firebase/tests/check_indexes.py`

- [ ] **Step 1: 시험을 쓴다**
  - RU1: 같은 업체 에이전트는 `apps/rpa/aikey/c1` 을 읽는다
  - RU2: 같은 업체 관리자·유저·다른 업체 에이전트는 못 읽는다. 아무도 못 쓴다
  - RU3: stts 9 업체의 에이전트는 못 읽는다 (Review Focus 3)
  - RU4: 실행 문서 `ai: {saved: 1, called: 2}` 는 만들어지고, `{saved: 3, called: 2}`·`{saved: "1"}` 는 거절된다
  - RU5: `aiPlans/default` 는 업체 관리자가 읽고, `aiPlans/c2` 는 c1 관리자가 못 읽는다
  - AG1: `ai_policy` - features.ai 참 + 키 있음 → `(True, "sk-ant-x")`. features 없음 → `(False, None)`
  - AG2: `Policy.refresh` 가 가짜 클라이언트로 `st.set_ai(True, "sk-ant-x")` 를 부른다 (가짜 `st`)
  - AG3: 꺼짐을 읽으면 `set_ai(False, None)` (Review Focus 2)
  - AG4: `run_doc` 이 지표 `[{key: "PRESET1:ai", value: 1, total: 2}, {key: "PRESET2:ai", value: 0, total: 1}]` → `ai == {"saved": 1, "called": 3}`. 지표가 없으면 `ai` 칸 없음
  - AG5: live 올리기에 `ai_ready` 가 참
  - IX1: `check_indexes.py` 가 새 색인 둘을 찾는다
- [ ] **Step 2:** 에뮬레이터로 돌려 실패하는지 본다.
  - 규칙: `firebase/tests` 의 기존 실행 방법(`run_integration.md`)대로
  - 에이전트: `.venv\Scripts\python.exe firebase\tests\test_agent.py`
- [ ] **Step 3:** 구현.
- [ ] **Step 4:** 다시 돌린다. 기대: 모두 통과, 기존 항목도 통과.

### Task 2: 관리 작업 (ops·routes)

**Files:**
- Modify: `firebase/admin/ops.js`, `firebase/admin/routes.js`
- Test: `firebase/tests/check_admin.py`

**Interfaces (Produces - Task 3 화면이 부른다):**
- `ops.setAi(cid, on, key)`
  - 켤 때:
    - 키가 없고 이미 둔 키도 없으면 거절: "AI 도움을 켜려면 API 키를 입력하여 주십시오."
    - 업데이트 안 된 PC(`live/{cid}/{pc}/ai_ready` 가 참이 아님)가 있으면 거절: "업데이트되지 않은 PC가 있어 AI 도움을 켤 수 없습니다. 먼저 업데이트하여 주십시오. (PC코드들)" (Review Focus 1)
    - `features/ai = true`. 키가 오면 `apps/rpa/aikey/{cid} = {key, hint: 끝 4글자, at: now}`
  - 끌 때: `features/ai` 와 `aikey/{cid}` 를 지운다.
  - 돌려주는 값: `{on, hint}`. 키는 돌려주지 않는다.
- `ops.aiInfo(cid, month?)`
  - `{on, hint, plan(합친 것), own(업체 요금표), saved, called, charge}`
  - `month` 기본값은 이번 달 1일 (KST)
  - `saved`·`called` 는 `runs/{cid}/items` 에서 `started_at >= month` 로 칸마다 따로 sum한다 (Firestore 합 함정 - 한 질의에 칸 하나)
- `ops.aiCharge(plan, saved) -> {monthly, extra, total, rows: [{from, to, count, price, amount}]}`: 순수 함수. Global Constraints 계산식.
- `ops.getAiPlan()` / `ops.setAiPlan(values)` (기본값), `ops.setCompanyAiPlan(cid, values)` (비운 칸은 지움)
  - 검사는 Global Constraints. 틀리면 `Refused` (Review Focus 5)
- `setupCompany(plan)` 에 `plan.ai` (boolean, 필수)와 `plan.aiKey` (켰으면 필수)를 더한다.
  - 없으면 거절: "AI 도움 사용 여부를 선택하여 주십시오. (업체마다 다릅니다)"
  - 단계 이름: "AI 도움"
  - 새 업체는 PC가 아직 안 켜졌으므로, 마법사에서는 `ai_ready` 검사를 하지 않는다. 켬만 적어 두고, PC가 켜지면 정책 읽기로 닿는다.
- routes 줄 (기록 글에 키를 넣지 않는다):
  - `["POST", "/api/companies/:cid/ai", (b,p) => ops.setAi(p.cid, b.on === true, b.key), (b,r,p) => \`AI 도움 ${p.cid} = ${r.on ? "켬" : "끔"}${b.key ? " (키 바꿈)" : ""}\`]`
  - `["GET", "/api/companies/:cid/ai", (b,p) => ops.aiInfo(p.cid, b.month)]`
  - `["GET", "/api/ai-plan", () => ops.getAiPlan()]`, `["POST", "/api/ai-plan", (b) => ops.setAiPlan(b.values), …]`
  - `["POST", "/api/companies/:cid/ai-plan", (b,p) => ops.setCompanyAiPlan(p.cid, b.values), …]`

- [ ] **Step 1: 시험을 쓴다** (`check_admin.py`, 에뮬레이터)
  - AD1: 키 없이 켜기 → 거절 글
  - AD2: 모든 PC `ai_ready` 참으로 넣고 `{on: true, key: "sk-ant-abcd1234"}` →
    - `features/ai` 가 참
    - `aikey/t_new/key` 가 그 값
    - 응답에 키가 없음 (`hint == "1234"`)
    - `관리_기록.txt` 새 줄에 `sk-ant` 이 없음
  - AD3: `key: "abc"` → "sk-ant-로 시작합니다" 거절
  - AD4: 끄기 → `features/ai`·`aikey/t_new` 둘 다 없음
  - AD5: PC 하나가 `ai_ready` 없음 → 거절 글에 그 PC코드 (Review Focus 1)
  - AD6: `aiCharge({monthly: 30000, included: 100, tiers: [{to: 300, price: 200}, {to: 600, price: 150}, {to: null, price: 100}]}, 650)`
    - `extra == 200*200 + 300*150 + 50*100 == 90000`, `total == 120000`
    - `saved=80` 이면 `extra == 0`
    - API로 확인: 실행 문서에 `ai.saved` 를 심고 `GET /api/companies/t_new/ai` 의 `charge`
  - AD7: `tiers` 의 `to` 가 줄어듦·`price` 음수·마지막 `to` 가 숫자 → 각각 거절 (Review Focus 5)
  - AD8: 업체 요금표 `{included: 200}` 만 넣으면 `aiInfo.plan.included == 200`, 나머지는 기본값
  - AD9: `aiInfo` 의 `saved`·`called` 가 이번 달 문서만 더한다 (지난달 문서를 심어도 빠짐)
  - AD10: `setupCompany` 에 `ai` 가 빠지면 거절. `ai: true, aiKey` 면 단계 "AI 도움" 이 ✓
- [ ] **Step 2:** 실패 확인 → **Step 3:** 구현 → **Step 4:** 통과 확인 (기존 check_admin 항목 포함).

### Task 3: 관리 화면 (AFTERMARKET_SETUP.html)

**Files:**
- Modify: `firebase/admin/AFTERMARKET_SETUP.html`
- Test: `firebase/tests/check_admin.py` 의 화면 절. 이 HTML을 화면으로 시험하는 기존 시험을 먼저 찾아 그 방식을 따른다.

- [ ] **Step 1: 화면 시험을 쓴다**
  - S1: 업체 상세에 'AI 도움' 상자가 있다
    - [사용] 체크, 키 칸(`type=password`, 안내 "sk-ant-… (바꿀 때만 입력)")
    - 키 상태 "키 있음 (…1234)" 또는 "키 없음"
    - 안내 글(Global Constraints)
  - S2: 이번 달 줄 "AI가 살린 단계 n번 / AI를 부른 횟수 m번 / 포함 k번"과 구간별 금액 표 (`aiCharge.rows`), 합계 "추가 금액 ○원 · 합계 ○원"
  - S3: 이 업체 요금표 칸(비우면 기본값)과 [적용]
  - S4: 토큰 배율 화면 옆에 'AI 도움 기본 요금표' (월정액·포함 횟수·구간 표 줄 더하기/빼기·[적용])
  - S5: 신규 업체 등록 마법사에 "AI 도움 사용" 예/아니요 (고르지 않으면 진행 안 됨), 예면 키 칸
  - S6: 거절 글(AD1·AD5)이 화면에 그대로 보인다
- [ ] **Step 2:** 실패 확인 → **Step 3:** 구현 (기존 웰라이프 체크·토큰 배율 화면의 모양과 `api()` 호출을 따른다) → **Step 4:** 통과 확인.

### Task 4: 업체 웹 환경설정

**Files:**
- Modify: `firebase/web/rpa-settings.js`
  - 'AI 도움' 카드
  - `c.policy.rpa.features.ai` 는 이미 받고 있다 (features 구독).
- Modify: `firebase/web/index.html` (카드 CSS가 필요하면)
- Modify: `docs/ui-wording.md` ('AI 도움' 글)
- Test: `firebase/tests/check_web.py`

카드 내용:
- 켜짐:
  - "AI 도움 사용 중"
  - 안내 글
  - "이번 달 AI가 살린 단계: n번 (월 포함 k번)"
  - 포함을 넘었으면 "포함 횟수를 넘은 만큼은 별도로 청구됩니다."
- 꺼짐: "AI 도움을 사용하지 않습니다. 사이트 화면이 바뀌어 수집이 멈추는 날, AI가 대신 찾아 이어 가게 할 수 있습니다. 사용하려면 담당자에게 문의하여 주십시오."
- 금액은 업체 웹에 보여 주지 않는다.

- [ ] **Step 1: 시험을 쓴다**
  - W1: features.ai 참 + 이번 달 실행 문서 `ai.saved` 합 3 + `aiPlans/default.included` 100 → 카드에 "AI 도움 사용 중", "3번", "100번", 안내 글
  - W2: features.ai 없음 → 꺼짐 글, 숫자 없음
  - W3: 카드에 끄기·켜기 조작 요소가 없다
  - W4: 환경설정을 연 뒤 heartbeat(live 값 바꾸기)를 3번 보내도 Firestore 합계 읽기가 한 번뿐이다 (Review Focus 4)
    - 시험에서 읽기 횟수를 세는 방법은 만드는 사람이 정한다. 예: 합계 함수를 감싸 센다.
- [ ] **Step 2:** 실패 확인 → **Step 3:** 구현 → **Step 4:** 통과 확인. 화면 시험은 기존 방식으로 에뮬레이터에서 돈다 (약 4분).

### Task 5: 마무리

- [ ] 계획 ①·②의 시험과 기존 시험을 다시 돌린다.
  - `test_agent.py`, `rules.test.js`, `check_admin.py`, `check_web.py`, 재생 시험 묶음
- [ ] `graphify update .`
- [ ] 배포 순서를 끝 보고에 적는다 (실제 배포는 사용자 지시 때):
  1. 데이터베이스·Firestore 규칙·색인
  2. PC 새 버전 (빌드 → 샌드박스 → 내보내기)
  3. hosting
  4. 업체 PC가 업데이트되어 `ai_ready` 가 올라온 뒤 관리 화면에서 켠다
- [ ] 사용자에게 보고한다. 커밋·배포는 지시를 기다린다.
