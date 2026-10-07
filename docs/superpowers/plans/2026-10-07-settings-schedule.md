# 환경설정 메뉴 · 시각별 모듈 · 시간대 반복 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 대시보드 설정을 '관리 > 환경설정' 한 메뉴로 모으고, 자동 실행을 줄마다 모듈을 고르는 시각과 되풀이하는 시간대로 넓힌다 (업체마다 줄 수 한도).

**Architecture:** 웹은 RPA 화면에서 설정 카드 셋을 떼어 `rpa-settings.js` 로 옮기고, 껍데기 페이지 `settings.js` 가 앱마다 붙인다. 예약은 지금처럼 PC 의 `rpa_dashboard.Scheduler` (에이전트 안) 가 돈다 - `settings.json schedule` 이 `{days, times}` 에서 `{days, slots}` 로 바뀌고, 줄의 모듈은 띄울 때 환경 변수 `RPA_RUN_MODULES` 로 루틴에 넘긴다. 반복 시간대는 같은 예약기가 회차마다 루틴을 새로 띄우고 결과를 상태 파일(`status_routine.json`)에서 읽어 센다. 업체 한도는 `meta/companies/{cid}/apps/rpa/limits/schedule` - 에이전트가 10분마다 읽어 `schedule.policy` 에 적는다.

**Tech Stack:** Python 3.14 (`.venv`), 바닐라 JS ES 모듈 + Firebase JS SDK 10.14.1 (CDN 그대로), Node 24 + firebase-admin (관리 도구), 시험: 파이썬 시험 스크립트(`check()` 꼴), Playwright, Firebase 에뮬레이터 (`firebase\emu_env.ps1` 로 JDK 21).

**Spec:** `docs/superpowers/specs/2026-10-06-settings-schedule-design.md`

## Global Constraints

- 커밋·push 는 사용자가 말할 때만 - 계획의 커밋 단계는 '사용자에게 커밋할지 묻기' 로 읽는다. main push 는 사용자가 "메인 push" 라고 할 때만 (ALLOW_MAIN_PUSH 절차).
- Firebase 배포(hosting·database 규칙)·새 판 빌드·실제 ERPia 확인은 사용자 확인 뒤 (Task 9).
- 사용자에게 보이는 글(화면·로그·명령 결과·오류)은 모두 한국어.
- 비밀번호가 든 사용자 설정 파일(RPA_UserConfig.json)은 이 일에서 건드리지 않는다 - 줄의 모듈은 환경 변수로만 넘긴다.
- 시험은 격리: PC 쪽은 `RPA_STATUS_DIR` 임시 폴더 + `RPA_DASHBOARD_DRY_RUN=1` (실제 settings.json·RPA 실행 금지). 웹·관리 도구는 에뮬레이터만. 실서버에 쓰는 명령(setup.js·관리 화면)을 Claude 도구로 돌리지 않는다.
- `tests/test_import_step.py` 는 일괄 실행에 넣지 않는다 (실제 ERPia 를 누른다).
- 새 패키지 없음 (pip·npm·CDN).
- 값: 시각 5분 단위(`SCHEDULE_MINUTE_STEP`), 자동 실행 개수 0~12 정수·없으면 **2**, PC 절대 상한 **12** (`SCHEDULE_MAX_SLOTS`), 쉬는 시간 1~60분·기본 **2**, 반복은 자정을 넘기지 않는다(끝 ≤ 23:55), `on_fail` 은 `"stop"` 만.
- 줄 키: `Prepare`(쇼핑몰 받기) + 루틴 설정 키 `Login`·`Sales`·`Hold`·`Logistics`·`Output`. 환경 변수 `RPA_RUN_MODULES`(쉼표 목록), `RPA_RUN_TRIGGER`(`auto`·`repeat`).
- 화면·PC 의 줄 이름(짧은 말): 쇼핑몰 받기 · 주문매핑 · 물류대기 · 물류관리 · 운송장.
- 코드를 고친 뒤 `graphify update .`.
- 설계서와 다른 점 하나: 새 판 PC 를 알아보는 표시는 `live.schedule.slots` 가 아니라 **`live.schedule.version >= 2`** (Realtime DB 는 빈 목록을 지워서, 줄이 0개인 새 판 PC 를 옛 판으로 오인한다 - Review Focus 5).

## Review Focus

1. 반복 회차가 자정을 넘겨 끝남 (23:00~23:55 시간대, 23:50 에 띄운 회차가 00:03 에 끝남) → 어제 시간대에 세고, 새 회차는 안 띄우고, 오류 없음 (Task 5 시험 11절).
2. 시간대 중에 예약을 고쳐 적용 → 같은 시간대면 횟수·멈춤을 이어 가고, 끝 시각을 바꾸면 새로, 시간대를 지우면 돌던 회차만 끝나고 새 회차 없음 (Task 5 시험 9절).
3. 에이전트의 정책 쓰기(10분마다)·예약기·적용이 같은 settings.json 을 고침 → 셋 다 `_settings_lock` 안에서 다시 읽고-고치고-쓰기, 서로의 칸(줄·다음 실행·반복 상태)을 지우지 않는다 (Task 3 시험 9절, Task 5 시험 10절).
4. 옛 판·새 판이 섞임: 새 판 PC 가 옛 모양 명령(옛 8765 화면·옛 웹)을 받음, 새 웹이 옛 판 PC 에 보냄 → 새 판은 '전체' 줄로 받고, 새 웹은 옛 모양으로 보낸다 (Task 2 시험 4·5절, Task 4 화면 시험).
5. 줄이 0개인 새 판 PC → `version` 으로 새 판을 알아본다 (Task 2 시험 4절, Task 4 화면 시험).

## 시험 명령 (PowerShell)

```powershell
# PC 쪽 (D:\AX\RPA)
.venv\Scripts\python.exe tests\test_schedule_slots.py
.venv\Scripts\python.exe tests\test_schedule_repeat.py      # Task 5 에서 생김
.venv\Scripts\python.exe tests\test_routine_modules.py
.venv\Scripts\python.exe tests\test_dashboard_auth.py
.venv\Scripts\python.exe tests\check_schedule_ui.py          # 옛 8765 화면 (headless)
# 에이전트·Firebase (D:\AX\RPA\firebase, 먼저 . .\emu_env.ps1)
python tests\test_agent.py
cd tests; npm test                                            # 규칙
firebase emulators:exec --config ../firebase.json --only auth,database,firestore          --project rpa-test-f02e0 "node integration.js"
firebase emulators:exec --config ../firebase.json --only auth,database,firestore,hosting  --project rpa-test-f02e0 "python check_web.py"
firebase emulators:exec --config ../firebase.json --only auth,database,firestore          --project rpa-test-f02e0 "python check_setup.py"
firebase emulators:exec --config ../firebase.json --only auth,database,firestore          --project rpa-test-f02e0 "python check_admin.py"
```

---

### Task 1: 환경설정 메뉴 (웹만 - 설정 카드를 RPA 화면에서 옮김)

**Files:**
- Create: `firebase/web/rpa-common.js`, `firebase/web/rpa-settings.js`, `firebase/web/settings.js`
- Modify: `firebase/web/rpa.js`, `firebase/web/app.js`, `firebase/web/index.html`
- Test: `firebase/tests/check_web.py`

**Interfaces:**
- Produces (`rpa-common.js`): `P(kind, cid, pcId)`, `esc(s)`, `MODULES`, `LOCKED`, `NEEDS`, `DAYS`, `hhmm(iso)`, `when(iso)`, `isoDay(date)`, `dict(pairs)`, `josa(w)`, `switchText(text, why)`, `notify(kind, text, ttlMs)`, `sendCommand(c, type, args, label, alive) → Promise<void>` (던지지 않는다 - 오류도 토스트)
- Produces (`rpa-settings.js`): `title = "RPA"`, `mount(el, ctx)`, `unmount()`, `dirty() → boolean`
- Produces (`rpa.js`): `export * as settings from "./rpa-settings.js"`
- Produces (`settings.js`): 페이지 `key="settings"`, `label="환경설정"`, `icon="⚙"`, `perPc=true`, `adminOnly=true`, `mount`, `unmount`, `dirty`
- Produces (`app.js`): `ctx().apps` (= `APPS`), 바꾸기 전 `current.dirty?.()` 가 참이면 `confirm("적용하지 않은 변경이 있습니다. 버리고 나갈까요?")`

- [ ] **Step 1: 실패할 시험 - `firebase/tests/check_web.py`**

(a) `def cmds_of(kind):` 함수 바로 아래에 도움 함수 둘:

```python
def goto(page, key):
    """사이드바 메뉴로 페이지를 바꾼다 (rpa / settings / account). 적용 안 한 변경이 있으면 확인 창이 뜬다 - 그런 곳은 시험이 직접 다룬다"""
    page.click(f"{'#app-nav' if key == 'rpa' else '#admin-nav'} a[data-key='{key}']")
    page.wait_for_selector({"rpa": "#hero", "settings": "#mod-card", "account": "#pw-btn"}[key])


def reload_to(page, key):
    """새로고침하면 첫 앱(RPA)이 뜬다 - 그 뒤 key 페이지로"""
    page.reload(); page.wait_for_selector("#main:not(.hide)", timeout=15000); page.wait_for_selector("#hero")
    if key != "rpa":
        goto(page, key)
```

(b) 1절 `check(page.is_hidden("#pc-pick"), "PC 가 하나면 고르기 숨김")` 바로 아래:

```python
    check(page.evaluate("[...document.querySelectorAll('#admin-nav a')].map((a) => a.dataset.key).join()") == "settings,account"
          and page.text_content("#admin-nav a[data-key='settings']").strip().endswith("환경설정"), "관리 메뉴: 환경설정 · 계정 (환경설정이 위)")
    check(page.locator("#mod-card, #shop-card, #sch-card").count() == 0, "RPA 화면에는 설정 카드가 없다 (환경설정으로 옮김)")
```

(c) 5절 머리 두 줄을 바꾼다:

```python
    print("5절 실행 모듈 (관리 > 환경설정)")
    goto(page, "settings")
    check(page.text_content("#page-title") == "환경설정" and page.text_content(".app-settings .app-title") == "RPA",
          "환경설정 페이지: 제목과 앱 이름 머리")
    page.wait_for_function("document.getElementById('mod-meta')?.textContent === '4/5 켬'", timeout=10000)
```

(d) 5절 안의 새로고침 두 곳 `page.reload(); page.wait_for_selector("#main:not(.hide)", timeout=15000); page.wait_for_selector("#mod-list label")` 을 둘 다 `reload_to(page, "settings"); page.wait_for_selector("#mod-list label")` 로.

(e) `# RPA 가 도는 동안에는 실행 버튼을 잠근다` 주석 바로 위에 `goto(page, "rpa")` 한 줄.

(f) 토큰 묶음에서 예약 칸(`#sch-info`)을 보는 세 곳을 환경설정에서 본다:
- `check("다음 예약 실행에 6개 · 남은 3개 …` 줄을:
```python
    goto(page, "settings")
    page.wait_for_function("(document.getElementById('sch-info')?.textContent || '').includes('남은 3개')", timeout=10000)
    check("다음 예약 실행에 6개 · 남은 3개 - 마이너스로 떨어질 수 있습니다" in page.text_content("#sch-info")
          and "warn" in page.get_attribute("#sch-info", "class"), f"예약 칸에도 노란 글 ({page.text_content('#sch-info')})")
    goto(page, "rpa")
```
- `check("토큰이 없어 예약 실행을 건너뜁니다" …` 줄을:
```python
    goto(page, "settings")
    page.wait_for_function("(document.getElementById('sch-info')?.textContent || '').includes('토큰이 없어')", timeout=10000)
    check("토큰이 없어 예약 실행을 건너뜁니다" in page.text_content("#sch-info") and "bad" in page.get_attribute("#sch-info", "class"),
          f"예약 칸: 건너뛴다고 빨간 글 ({page.text_content('#sch-info')})")
    goto(page, "rpa")
```
- `check(not page.is_disabled("#run-all") and "토큰" not in page.text_content("#sch-info") and page.is_hidden("#usage-card"), …)` 를:
```python
    check(not page.is_disabled("#run-all") and page.is_hidden("#usage-card"), "통장이 사라지면 (옛 에이전트) 줄도 잠금도 사용량도 없다")
    goto(page, "settings")
    page.wait_for_function("document.getElementById('sch-meta')?.textContent !== ''", timeout=10000)
    check("토큰" not in page.text_content("#sch-info"), "예약 칸의 토큰 글도 없다")
```
(이 뒤 5-2절·6절은 환경설정 페이지에서 그대로 돈다.)

(g) 6절: `check("primary" in (page.get_attribute("#run-all", "class") …` 부터 `page.mouse.move(0, 0)` 까지(실행 단추 모양 시험)를 잘라 6절 끝 뒤로 옮긴다. 6절 마지막 줄 `check(page.is_disabled("#sch-apply"), "켠 채 시간이 없으면 적용 불가")` 바로 뒤에:

```python
    # 떠날 때 확인 (1부): 위에서 켬을 다시 켜고 줄을 지운 채 (적용 안 함) 다른 메뉴로 - '아니오' 면 남고, '예' 면 버리고 나간다
    asked = []
    page.once("dialog", lambda dlg: (asked.append(dlg.message), dlg.dismiss()))
    page.click("#app-nav a[data-key='rpa']")
    page.wait_for_timeout(300)
    check(asked == ["적용하지 않은 변경이 있습니다. 버리고 나갈까요?"] and page.text_content("#page-title") == "환경설정"
          and page.is_visible("#sch-card"), f"적용 안 한 변경이 있으면 묻고, 아니오면 남는다 ({asked})")
    page.once("dialog", lambda dlg: dlg.accept())
    page.click("#app-nav a[data-key='rpa']")
    page.wait_for_selector("#hero")
    check(page.text_content("#page-title") == "RPA", "예면 버리고 나간다")
    goto(page, "settings")
    page.wait_for_function("document.getElementById('sch-meta')?.textContent === '매일 09:05, 13:30'", timeout=10000)
    check(page.is_disabled("#sch-apply") and len(page.query_selector_all("#sch-times input")) == 2, "다시 열면 PC 값 그대로 (버린 변경은 없다)")
    goto(page, "rpa")

    print("6-2절 실행 단추 모양 (RPA 화면)")
```
그리고 잘라 둔 실행 단추 모양 시험을 이 바로 밑에 붙인다.

(h) 7-3절 첫 check (`"PC 가 둘이면 고르기가 보이고 지금 PC 가 적혀 있다"`) 바로 아래:

```python
    goto(page, "settings")
    check(page.is_visible("#pc-pick") and page.text_content("#page-title") == "환경설정", "환경설정도 PC 마다 - PC 고르기가 보인다")
    goto(page, "rpa")
```

(i) 8절 `check(page.is_hidden("#act-card") and page.is_hidden("#mod-card") and page.is_hidden("#sch-card"), …)` 를:

```python
    check(page.is_hidden("#act-card") and page.locator("#admin-nav a[data-key='settings']").count() == 0,
          "유저는 실행 카드도 환경설정 메뉴도 없다")
```

- [ ] **Step 2: 실패 확인** - check_web (시험 명령 표). 기대: `관리 메뉴: 환경설정 · 계정` 실패 뒤 `#mod-card` 를 못 찾아 멈춤.

- [ ] **Step 3: `firebase/web/rpa-common.js` (새)**

```js
// RPA 화면 둘이 같이 쓰는 것 - 현황(rpa.js)·환경설정(rpa-settings.js). 경로, 모듈 표, 글 도우미, 명령 보내기.
import { ref, onValue, push } from "https://www.gstatic.com/firebasejs/10.14.1/firebase-database.js";
import { COMMAND_TTL_SEC } from "./firebase-config.js";
import { toast } from "./toast.js";

export const P = (kind, cid, pcId) => `apps/rpa/${kind}/${cid}/${pcId}`;
// 에이전트·Firestore 에서 온 값은 innerHTML 에 넣기 전에 반드시 씌운다 (app.js 와 같은 구현)
export const esc = (s) => String(s).replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));
export const MODULES = [
  ["Login", "로그인"], ["Sales", "주문매핑 매출처리"], ["Hold", "물류대기 관리"],
  ["Logistics", "물류관리"], ["Output", "운송장 출력 / 엑셀 생성"],
];
export const LOCKED = new Set(["Login"]);   // 항상 켬. 관리자도 못 끈다 (에이전트도 파일에 Y 로 고정)
// 앞 모듈이 꺼지면 따라 꺼지는 모듈. 운송장 출력은 물류관리가 만든 화면에서 돌기 때문에 혼자 돌 수 없다 (에이전트도 못 박는다)
export const NEEDS = { Output: "Logistics" };
export const DAYS = ["월", "화", "수", "목", "금", "토", "일"];
export const hhmm = (iso) => iso ? iso.slice(11, 16) : "";
export const when = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.getMonth() + 1}월 ${d.getDate()}일 (${DAYS[(d.getDay() + 6) % 7]}) ${hhmm(iso)}`;
};
export const isoDay = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
export const dict = (pairs) => Object.fromEntries(pairs);
// 받침이 있으면 '을', 없으면 '를' (한글이 아니면 '를')
export const josa = (w) => {
  const code = (w || "").charCodeAt((w || "").length - 1) - 0xac00;
  return code >= 0 && code < 11172 && code % 28 ? "을" : "를";
};
/** 스위치 줄의 글자. why 가 있으면 그 아래 작은 글씨로 - 잠긴 까닭 (마우스 글(title)은 휴대폰에 안 보인다 - 2026-10-02) */
export function switchText(text, why) {
  const s = Object.assign(document.createElement("span"), { textContent: text });
  if (why) s.append(Object.assign(document.createElement("small"), { className: "why", textContent: why }));
  return s;
}
/** 명령·설정 안내는 토스트 하나를 이어서 고쳐 쓴다 (보냄 → 진행 중 → 결과) */
export const notify = (kind, text, ttlMs) => toast(kind, text, ttlMs, "act");

/** 명령을 넣고 PC 가 끝낼 때까지 토스트로 알린다. 실패도 토스트 - 던지지 않는다.
 *  alive() 가 거짓이면 (화면을 떠났다) 결과 안내를 하지 않는다 */
export async function sendCommand(c, type, args, label, alive = () => true) {
  notify("info", `${label} 명령을 보냈습니다. PC 응답을 기다립니다.`);
  try {
    const now = Math.floor(Date.now() / 1000);
    const node = await push(ref(c.db, P("commands", c.me.cid, c.pcId)), {
      type, args: args ?? null, by: c.me.uid, created_at: now, expires_at: now + COMMAND_TTL_SEC, state: "queued",
    });
    await watchCommand(c, node.key, label, alive);
  } catch (e) {
    notify("bad", e.code === "PERMISSION_DENIED" ? "권한이 없습니다" : `보내지 못했습니다 (${e.code || e})`);
  }
}

function watchCommand(c, cmdKey, label, alive) {
  return new Promise((resolve) => {
    const timer = setTimeout(() => { off(); if (alive()) notify("bad", "PC 가 응답하지 않습니다"); resolve(); }, 60000);
    const off = onValue(ref(c.db, `${P("commands", c.me.cid, c.pcId)}/${cmdKey}`), (snap) => {
      const v = snap.val();
      if (!v || !alive()) return;
      if (v.state === "running") notify("info", `${label} 진행 중`);
      if (["done", "failed", "expired"].includes(v.state)) {
        clearTimeout(timer); off();
        notify(v.state === "done" ? "ok" : "bad", v.result || v.state);
        resolve();
      }
    });
  });
}
```

- [ ] **Step 4: `firebase/web/rpa-settings.js` (새)** - 머리 부분은 아래 그대로 쓰고, 그 밑에 `rpa.js` 의 `// --- 실행 모듈` 절부터 파일 끝(`applySchedule` 까지)을 **그대로 옮긴다**.

```js
// RPA 의 환경설정 - 관리 > 환경설정 (settings.js) 이 붙인다. 실행 모듈 · 쇼핑몰 프리셋 · 자동 실행 (PC 마다).
// 값의 기준은 PC 가 올린 live. 적용 = settings 에 쓰고 명령을 넣는다 - PC 가 반영해 live 로 돌려준다
import { ref, onValue, set } from "https://www.gstatic.com/firebasejs/10.14.1/firebase-database.js";
import { P, MODULES, LOCKED, NEEDS, DAYS, when, dict, josa, switchText, notify, sendCommand } from "./rpa-common.js";

export const title = "RPA";

const PRESETS = [["평일", [0, 1, 2, 3, 4]], ["매일", [0, 1, 2, 3, 4, 5, 6]], ["주말", [5, 6]]];
const MAX_TIMES = 2;      // 하루 실행 시각 개수 - 2부(Task 4)에서 업체 한도로 바뀐다

const HTML = `
  <div class="settings-grid" id="settings-grid">
    <div>
      <div class="card" id="mod-card">
        <h2>실행 모듈 <span class="muted" id="mod-meta"></span></h2>
        <div id="mod-list"></div>
        <button class="apply" id="mod-apply" disabled>적용</button>
      </div>
      <div class="card hide" id="shop-card">
        <h2>쇼핑몰 프리셋 <span class="muted" id="shop-meta"></span></h2>
        <div id="shop-list"></div>
        <div class="msg" id="shop-info"></div>
        <button class="apply" id="shop-apply" disabled>적용</button>
      </div>
    </div>
    <div>
      <div class="card" id="sch-card">
        <h2>자동 실행 <span class="muted" id="sch-meta"></span></h2>
        <label class="switch first"><span>켬</span><input type="checkbox" id="sch-enabled"><span class="knob"></span></label>
        <div id="sch-form">
          <div class="lbl">요일</div>
          <div class="seg" id="sch-presets"></div>
          <div class="seg" id="sch-days"></div>
          <div class="lbl">시간</div>
          <div class="times" id="sch-times"></div>
          <div class="seg"><button id="sch-add">+ 시간</button></div>
        </div>
        <div class="msg" id="sch-info"></div>
        <button class="apply" id="sch-apply" disabled>적용</button>
      </div>
    </div>
  </div>
  <p class="muted hide" id="no-pc">등록된 PC 가 없습니다</p>`;

let root = null, c = null, stopLive = null, busy = false, live = null;
let form = { modules: {}, shops: {}, sch: { enabled: false, days: [], times: [] } };
const $ = (id) => root.querySelector(`#${id}`);
const show = (el, on) => el.classList.toggle("hide", !on);

export function mount(el, context) {
  root = el; c = context; busy = false; live = null;
  root.innerHTML = HTML;
  if (!c.pcId) { show($("settings-grid"), false); show($("no-pc"), true); return; }
  $("mod-apply").onclick = applyModules;
  $("shop-apply").onclick = applyShops;
  $("sch-apply").onclick = applySchedule;
  $("sch-enabled").onchange = (e) => { form.sch.enabled = e.target.checked; paintScheduleMeta(); };
  $("sch-add").onclick = () => { if (form.sch.times.length >= MAX_TIMES) return; form.sch.times.push("09:00"); paintTimes(); paintScheduleMeta(); };
  $("sch-presets").replaceChildren(...PRESETS.map(([t, days]) => {
    const b = document.createElement("button"); b.textContent = t;
    b.onclick = () => { form.sch.days = [...days]; paintDays(); paintScheduleMeta(); };
    return b;
  }));
  stopLive = onValue(ref(c.db, P("live", c.me.cid, c.pcId)), (snap) => {
    const first = live == null;
    live = snap.val() || {};
    // 편집 중이 아닐 때만 폼을 PC 값으로 맞춘다 (적용 뒤 돌아온 값으로 갱신)
    if (first || !modulesDirty()) resetModules();
    if (first || !shopsDirty()) resetShops();
    if (first || !scheduleDirty()) resetSchedule();
    paintAll();
  }, (e) => notify("bad", e.code === "PERMISSION_DENIED" ? "권한이 없습니다" : `읽지 못했습니다 (${e.code || e})`));
}

export function unmount() {
  if (stopLive) { stopLive(); stopLive = null; }
  root = null; c = null;
}

/** 적용 안 한 변경이 있나 (떠날 때 확인 - app.js) */
export function dirty() {
  return !!root && !!live && (modulesDirty() || shopsDirty() || scheduleDirty());
}

function paintAll() { paintModuleMeta(); paintShopMeta(); paintScheduleMeta(); }

/** 명령을 넣는 동안 카드 단추를 잠근다 */
async function send(type, args, label) {
  busy = true; paintAll();
  try { await sendCommand(c, type, args, label, () => !!root); }
  finally { busy = false; if (root) paintAll(); }
}
```

옮긴 코드에서 고칠 것:
- `const LOCKED = …`, `const NEEDS = …`, `const dict = …`, `function switchText …`, `const josa = …` 는 지운다 (rpa-common 에서 가져온다).
- `applyModules`·`applyShops`·`applySchedule` 의 `await sendCommand("…", …, "…")` 셋을 `await send("…", …, "…")` 로.

- [ ] **Step 5: `firebase/web/rpa.js` 고치기**
- 가져오기: database 줄을 `import { ref, onValue } from "https://www.gstatic.com/firebasejs/10.14.1/firebase-database.js";` 로, config 줄을 `import { HEARTBEAT_EVERY_DEFAULT, HEARTBEAT_MISS } from "./firebase-config.js";` 로. 그 밑에:
```js
import { P, esc, MODULES, hhmm, when, isoDay, sendCommand } from "./rpa-common.js";
export * as settings from "./rpa-settings.js";   // 관리 > 환경설정 이 이 앱의 설정 화면을 붙인다 (settings.js)
```
- 지울 것: `const P = …`, `const MODULES = […]`, `const DAYS = …`, `const PRESETS = …`, `const MAX_TIMES = …`, `const esc = …`, `const hhmm = …`, `const when = …`, `const isoDay = …`, `let form = …`.
- HTML: `<div class="card" id="mod-card">…</div>`, `<div class="card hide" id="shop-card">…</div>`, `<div class="card" id="sch-card">…</div>` 세 덩어리를 지운다 (`#sidecol` 에는 `act-card`·`usage-card` 만 남는다).
- `mount()`: `$("mod-apply").onclick`, `$("shop-apply").onclick`, `$("sch-apply").onclick`, `$("sch-enabled").onchange`, `$("sch-add").onclick`, `$("sch-presets")…` 줄들을 지우고, live 콜백의 `resetModules`·`resetShops`·`resetSchedule` 세 줄과 그 위 주석도 지운다. 실행 단추 넷을 `send(…)` 로:
```js
  $("run-routine").onclick = () => send("launch", { target: "routine" }, "루틴 RPA");
  $("run-prepare").onclick = () => send("launch", { target: "prepare" }, "프리페어 RPA");
  $("run-all").onclick = () => send("launch", { target: "all" }, "전체 실행");
  $("stop-erpia").onclick = () => { if (confirm("ERPia 를 종료할까요?")) send("stop_erpia", null, "ERPia 종료"); };
```
- `// --- 명령` 절의 `const notify`, `async function sendCommand`, `function watchCommand` 를 지우고 대신:
```js
/** 실행 단추의 명령. 응답을 기다리는 동안 단추를 잠근다 */
async function send(type, args, label) {
  if (busy || !c.pcId) return;
  busy = true; paintButtons();
  try { await sendCommand(c, type, args, label, () => !!root); }
  finally { busy = false; if (root) paintButtons(); }
}
```
- `paintButtons()` 끝줄 `paintTokens(); paintModuleMeta(); paintShopMeta(); paintScheduleMeta();` → `paintTokens();`
- `// --- 실행 모듈` 절부터 파일 끝까지 지운다 (Step 4 에서 옮겼다).

- [ ] **Step 6: `firebase/web/settings.js` (새)**

```js
// 관리 > 환경설정: 앱마다 설정 화면을 붙인다 (앱 모듈이 settings 를 내보내면). 관리자·총괄만. PC 마다 (위쪽 PC 고르기).
// 앱이 둘이 되면 위에 앱 탭을 붙인다 - 지금은 앱 이름 머리 아래 그대로.
export const key = "settings";
export const label = "환경설정";
export const icon = "⚙";
export const perPc = true;
export const adminOnly = true;

let mounted = [];

export function mount(el, c) {
  if (!c.isAdmin) { el.innerHTML = `<p class="muted">관리자만 볼 수 있습니다</p>`; return; }
  mounted = c.apps.filter((a) => a.settings).map((a) => {
    const sec = document.createElement("section");
    sec.className = "app-settings";
    const h = Object.assign(document.createElement("h2"), { className: "app-title", textContent: a.settings.title || a.label });
    const body = document.createElement("div");
    sec.append(h, body);
    el.append(sec);
    a.settings.mount(body, c);
    return a.settings;
  });
}

export function unmount() {
  for (const s of mounted) s.unmount();
  mounted = [];
}

export function dirty() {
  return mounted.some((s) => s.dirty?.());
}
```

- [ ] **Step 7: `firebase/web/app.js` 고치기**
- `import * as account from "./account.js";` 아래 `import * as settings from "./settings.js";`, `const PAGES = [account];` → `const PAGES = [settings, account];`
- `ctx()` 가 돌려주는 객체 끝에 `, apps: APPS` (주석: `// 환경설정 페이지가 앱마다 설정 화면을 붙인다`).
- `navLink` 의 `a.onclick` 을 `a.onclick = (e) => { e.preventDefault(); if (leaveOk()) mount(mod); };` 로, 그 위에:
```js
/** 적용 안 한 변경이 있는 페이지(환경설정)를 떠나기 전에 묻는다 - 메뉴·PC 바꾸기 모두 */
function leaveOk() {
  return !current?.dirty?.() || confirm("적용하지 않은 변경이 있습니다. 버리고 나갈까요?");
}
```
- `paintNav()` 둘째 줄: `$("admin-nav").replaceChildren(...PAGES.filter((p) => !p.adminOnly || ctx().isAdmin).map(navLink));   // 유저는 환경설정 링크가 없다`
- `paintPcPick()` 의 `b.onclick = () => {` 다음 첫 줄: `if (!leaveOk()) { box.classList.remove("open"); b.blur(); return; }`

- [ ] **Step 8: `firebase/web/index.html` - `.lbl { … }` 줄 아래**

```css
  /* 관리 > 환경설정: 앱 이름 머리 아래 카드들. 넓으면 두 칸 (왼쪽 실행 모듈·쇼핑몰 프리셋, 오른쪽 자동 실행 - 반복으로 길어진다) */
  .app-settings + .app-settings { margin-top:22px; }
  .app-title { margin:0 0 10px; font-size:15px; letter-spacing:.04em; }
  .settings-grid { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1.25fr); gap:14px; align-items:start; }
  @media (max-width:1000px) { .settings-grid { grid-template-columns:minmax(0,1fr); } }
```

- [ ] **Step 9: 통과 확인** - check_web. 기대: 실패 0 (건수는 전 262 보다 는다), `페이지 오류 없음` 통과.
- [ ] **Step 10:** `graphify update .` → 커밋은 사용자에게 묻는다 (hosting 배포는 Task 9 에서 사용자 확인 뒤).

---

### Task 2: PC 예약 모양 - 줄(slots)과 이번 실행 모듈

**Files:**
- Modify: `rpa_status.py` (예약 상수·`DEFAULT_SETTINGS`·`read_settings`)
- Modify: `rpa_dashboard.py` (`NOW`·`LAUNCHED_ENV`·`launch`, `launch_run_all` 뒤 예약 절 전부, `settings_view` 한 줄)
- Modify: `run_routine.py` (`run_modules_from_env`, `main`)
- Test: `tests/test_schedule_slots.py`, `tests/test_routine_modules.py`, `firebase/tests/integration.js`, `tests/check_schedule_ui.py`

**Interfaces:**
- Produces (`rpa_status`): `SCHEDULE_MAX_SLOTS = 12`, `SCHEDULE_VERSION = 2`; `read_settings()["schedule"]` 에는 늘 `slots`·`version` (`times` 는 없다)
- Produces (`rpa_dashboard`): `NOW()`, `ROUTINE_KEYS`, `RUN_KEYS`, `SLOT_NAMES`, `normalize_run(run) → list|None`, `normalize_slots(slots) → list[dict]`, `sorted_slots(sch)`, `active_slots(sch)`, `next_due(sch, after) → (datetime|None, dict|None)`, `advance(sch, now)` (next_run_at·next_slot), `slot_of(sch) → dict|None`, `slot_target(slot, off=()) → (target|None, env)`, `launch(target, by, env=None)`, `launch_slot(slot, by="auto", trigger="auto")`, `LAUNCHED_ENV: list[dict]`, `slot_text(slot)`, `schedule_view()` (`version`·`slots`·`next_slot`·`policy`, 옛 화면용 `times`), `apply_schedule({enabled, days, slots})` - 옛 `{enabled, days, times}` 도 받는다
- Produces (`run_routine`): `run_modules_from_env(keys) → (dict|None, list)`

- [ ] **Step 1: 실패할 시험 - `tests/test_schedule_slots.py`**
- 2절: 거부 목록의 `[f"{h:02d}:00" for h in range(4)]` → `range(13)`, 그 아래 `check(len(d.normalize_times([f"{h:02d}:00" for h in range(3)])) == 3, "3개까지는 받음")` → `check(len(d.normalize_times([f"{h:02d}:00" for h in range(12)])) == 12, "12개까지는 받음 (PC 상한 - 업체 한도는 에이전트가)")`.
- 3절의 `schedule_label` 두 check 를:
```python
check(d.schedule_label({"days": WK, "slots": [{"at": "09:00"}, {"at": "13:00"}]}) == "평일 09:00, 13:00", "평일 09:00, 13:00")
check(d.schedule_label({"days": WK, "slots": [{"at": t} for t in ("08:00", "10:00", "12:00", "14:00", "16:00")]}) == "평일 08:00, 10:00, 12:00 외 2개", "많으면 앞 3개 + 외 N개")
check(d.schedule_label({"days": WK, "slots": [{"at": "10:00"}, {"at": "11:00", "run": ["Login", "Logistics"]}]}) == "평일 10:00, 11:00 물류관리",
      "고르기 줄은 시각 뒤에 모듈 (로그인은 안 적는다)")
```
- 4절 첫 check 를 바꾸고 끝에 둘을 더한다:
```python
check(cfg["schedule"]["enabled"] is False and cfg["schedule"]["days"] == WK and cfg["schedule"]["slots"] == [{"at": "09:00"}]
      and "times" not in cfg["schedule"] and cfg["schedule"]["version"] == 2, "기본: 꺼짐, 평일 09:00 '전체' 한 줄, 판 2")
```
```python
st.write_settings({"schedule": {"enabled": False, "days": WK, "times": ["13:30", "09:05"]}})
conv = st.read_settings()["schedule"]
check(conv["slots"] == [{"at": "13:30"}, {"at": "09:05"}] and "times" not in conv and conv["version"] == 2,
      "옛 모양 {days, times} 는 '전체' 줄로 읽힌다 (Review Focus 4)")
sv = d.schedule_view()
check(sv["times"] == ["09:05", "13:30"] and sv["slots"][0] == {"at": "09:05"} and sv["version"] == 2,
      "화면 값: 줄은 시각 순, 옛 8765 화면용 times 도, 판 2 (줄이 0개여도 판으로 새 판을 안다 - Review Focus 5)")
```
- 5절: `sch["times"] == ["00:00", "12:00", "23:55"]` → `[s["at"] for s in sch["slots"]] == ["00:00", "12:00", "23:55"]`, `d.next_slot(sch["days"], sch["times"], …)` 두 곳 → `d.next_slot(sch["days"], [s["at"] for s in sch["slots"]], …)`.
- 5절 끝(`schedule_view 이름표` check 뒤)에 새 절:
```python
print("\n=== 5-2. 줄마다 모듈 (2026-10-07 시각별 모듈) ===")
check(d.normalize_run(None) is None, "run 이 없으면 '전체'")
check(d.normalize_run(["Logistics"]) == ["Login", "Logistics"], "루틴 모듈을 고르면 로그인은 늘 붙는다")
check(d.normalize_run(["Output", "Logistics", "Prepare"]) == ["Prepare", "Login", "Logistics", "Output"], "정한 순서로 (쇼핑몰 받기 → 루틴)")
check(d.normalize_run(["Prepare", "Login"]) == ["Prepare"], "쇼핑몰 받기만이면 로그인은 뺀다")
for bad, why in ((["Output"], "물류관리와 같이"), (["Login"], "하나 이상"), ([], "하나 이상"), (["Nope"], "모르는 모듈"),
                 (["Sales", "Sales"], "두 번"), ("Sales", "잘못")):
    try:
        d.normalize_run(bad); check(False, f"run 거부 {bad!r}")
    except ValueError as e:
        check(why in str(e), f"run 거부 {bad!r} ({e})")
slots = d.normalize_slots([{"at": "11:00", "run": ["Logistics"]}, {"at": "10:00"}])
check(slots == [{"at": "10:00"}, {"at": "11:00", "run": ["Login", "Logistics"]}], f"줄은 시각 순, '전체' 줄엔 run 이 없다 ({slots})")
for bad, why in (([{"at": "10:00"}, {"at": "10:00", "run": ["Hold"]}], "같은 시각"), ([{"at": "10:03"}], "5분"),
                 ([{"at": f"{h:02d}:00"} for h in range(13)], "12개"), ([], "하나 이상"), (["10:00"], "줄이 잘못")):
    try:
        d.normalize_slots(bad); check(False, f"줄 거부 {why}")
    except ValueError as e:
        check(why in str(e), f"줄 거부 {why} ({e})")
check(d.slot_target({"at": "10:00"}) == ("all", {}), "'전체' 줄 → 전체 실행, 넘길 모듈 없음")
check(d.slot_target({"at": "11:00", "run": ["Login", "Logistics"]}) == ("routine", {"RPA_RUN_MODULES": "Login,Logistics"}), "쇼핑몰 받기 없음 → 루틴만")
check(d.slot_target({"at": "12:00", "run": ["Prepare"]}) == ("prepare", {}), "쇼핑몰 받기만 → 프리페어")
check(d.slot_target({"at": "13:00", "run": ["Prepare", "Login", "Sales"]}) == ("all", {"RPA_RUN_MODULES": "Login,Sales"}), "둘 다 → 전체 실행 + 루틴 모듈")
check(d.slot_target({"at": "14:00", "run": ["Login", "Hold"]}, off=["Hold"]) == (None, {}), "업체가 안 쓰는 모듈을 빼면 돌릴 게 없다 → 안 띄움")
check(d.slot_target({"at": "14:00", "run": ["Login", "Logistics", "Output"]}, off=["Logistics"]) == (None, {}), "물류관리를 빼면 출력도 빠진다")
d.apply_schedule({"enabled": True, "days": list(range(7)), "slots": [{"at": "10:00"}, {"at": "11:00", "run": ["Logistics"]}]})
sch = st.read_settings()["schedule"]
check(sch["slots"] == [{"at": "10:00"}, {"at": "11:00", "run": ["Login", "Logistics"]}] and sch["next_slot"] in ("10:00", "11:00"),
      f"줄 적용 → 저장·다음 줄 ({sch['next_slot']})")
check(d.apply_schedule({"enabled": False, "days": [], "slots": []}) is True and st.read_settings()["schedule"]["slots"] == [],
      "끌 때는 요일·줄이 비어도 된다")
d.apply_schedule({"enabled": True, "days": list(range(7)), "times": ["23:55", "00:00", "12:00"]})   # 6절이 기대하는 상태로 되돌린다
```
- 6절: `check(nxt.strftime("%H:%M") in sch["times"], …)` → `in [s["at"] for s in sch["slots"]]`.
- 6-3절 끝(`d._active["proc"] = None` 다음, 7절 앞)에 새 절:
```python
print("\n=== 6-4. 고르기 줄은 그 모듈만 넘긴다 ===")
saved = list(d.LAUNCHED)
d.apply_schedule({"enabled": True, "days": list(range(7)), "slots": [{"at": "11:00", "run": ["Logistics"]}]})
c = st.read_settings(); c["schedule"]["next_run_at"] = (dt.datetime.now() - dt.timedelta(seconds=3)).isoformat(timespec="seconds"); st.write_settings(c)
sched.tick()
check(d.LAUNCHED == saved + ["routine:auto"] and d.LAUNCHED_ENV[-1] == {"RPA_RUN_MODULES": "Login,Logistics", "RPA_RUN_TRIGGER": "auto"},
      f"next_slot 의 줄대로 루틴만 + 이번 실행 모듈 ({d.LAUNCHED_ENV[-1:]})")
d.LAUNCHED[:] = saved; d._active["until"] = 0; d._active["proc"] = None
```

- [ ] **Step 2: 실패할 시험 - `tests/test_routine_modules.py`** (끝의 `finish()` 바로 위):

```python
print()
print("=== 11. 예약이 넘긴 이번 실행 모듈 (RPA_RUN_MODULES, 2026-10-07) ===")
os.environ.pop("RPA_RUN_MODULES", None)
check("변수가 없으면 None (설정 파일을 쓴다)", rr.run_modules_from_env(KEYS) == (None, []))
os.environ["RPA_RUN_MODULES"] = "Logistics"
sel, unknown = rr.run_modules_from_env(KEYS)
check("물류관리만 → 로그인은 늘 켬, 나머지 끔", sel == {"Login": True, "Sales": False, "Hold": False, "Logistics": True, "Output": False} and unknown == [], f"{sel}")
os.environ["RPA_RUN_MODULES"] = "Login,Output"
sel, _ = rr.run_modules_from_env(KEYS)
check("물류관리 없이 출력만 → 출력도 빠져 돌릴 게 없다", not any(sel.values()), f"{sel}")
os.environ["RPA_RUN_MODULES"] = "Sales,Nope"
sel, unknown = rr.run_modules_from_env(KEYS)
check("모르는 키는 돌려주고 무시", unknown == ["Nope"] and sel["Sales"] and sel["Login"], f"{sel} {unknown}")
rec = StatusRec(); rr.status = rec
rr.pl.load_routine_modules = lambda keys: check("변수가 있으면 설정 파일을 안 읽는다", False) or ({k: True for k in keys}, [])
ran = []
rr.run_modules = lambda selected: ran.append(selected) or ("success", None)
os.environ["RPA_RUN_MODULES"] = "Hold"
rr.main()
check("main 이 넘긴 모듈로 돈다", ran and ran[-1] == {"Login": True, "Sales": False, "Hold": True, "Logistics": False, "Output": False}, f"{ran}")
os.environ["RPA_RUN_MODULES"] = "Login"
rec = StatusRec(); rr.status = rec; ran.clear()
rr.main()
check("돌릴 게 없으면 run_modules 없이 중단 + 사유", not ran and rec.of("finish")[-1] == ("stopped", "이번 실행 모듈이 비었습니다"), f"{rec.of('finish')}")
os.environ.pop("RPA_RUN_MODULES", None)
```

- [ ] **Step 3: 실패 확인** - 두 시험. 기대: `기본: 꺼짐, 평일 09:00 '전체' 한 줄` 실패, `AttributeError: … run_modules_from_env`.

- [ ] **Step 4: `rpa_status.py`** - `# 자동 실행 예약: 요일…` 주석부터 `DEFAULT_SETTINGS` 의 `"schedule": {…},` 까지를:

```python
# 자동 실행 예약: 요일(월=0 … 일=6, 모든 줄이 같이 씀) + 줄(slots). 줄 = {at:"HH:MM", run?:[모듈 키]} - run 이 없으면 '전체'.
# (2026-10-07 시각별 모듈 - 설계 docs/superpowers/specs/2026-10-06-settings-schedule-design.md 5절. 옛 모양 {days, times} 는 read_settings 가 바꾼다)
SCHEDULE_MINUTE_STEP = 5
SCHEDULE_MAX_SLOTS = 12     # PC 쪽 절대 상한. 업체 한도(자동 실행 개수, 기본 2)는 에이전트가 schedule.policy 에 적는다
SCHEDULE_VERSION = 2        # live.schedule.version - 화면이 새 판 PC 를 알아본다 (없으면 옛 판: 시각만). 빈 줄 목록은 Realtime DB 에서 사라져 표시로 못 쓴다
DEFAULT_SETTINGS = {
    "schedule": {
        "version": SCHEDULE_VERSION,
        "enabled": False,
        "days": [0, 1, 2, 3, 4],    # 평일
        "slots": [{"at": "09:00"}],
        "next_run_at": None,
        "next_slot": None,          # next_run_at 이 가리키는 줄의 at
        "last_launch_at": None,
        "last_launch_by": None,     # "auto" / "manual:<아이디>" / "cloud"
        "last_error": None,
    },
```
`read_settings` 를:
```python
def read_settings():
    """대시보드 환경설정. 없거나 깨졌으면 기본값으로 채운다. 옛 예약 {days, times} 는 줄(slots, 모두 '전체')로 바꿔 읽는다."""
    data = read_json(settings_path())
    out = json.loads(json.dumps(DEFAULT_SETTINGS))
    if isinstance(data, dict):
        for section, values in data.items():
            if isinstance(values, dict) and isinstance(out.get(section), dict):
                out[section].update(values)
        old = data.get("schedule")
        if isinstance(old, dict) and "slots" not in old:
            out["schedule"]["slots"] = [{"at": t} for t in old.get("times") or [] if isinstance(t, str)]
    out["schedule"].pop("times", None)
    out["schedule"]["version"] = SCHEDULE_VERSION
    return out
```

- [ ] **Step 5: `rpa_dashboard.py`**
- `MISSED_GRACE_SEC = 120` 아래: `NOW = datetime.datetime.now   # 예약 계산의 지금 - 시험이 가짜 시계로 바꾼다 (tests/test_schedule_repeat.py)`
- `LAUNCHED = []` 아래: `LAUNCHED_ENV = []   # 시험용(DRY_RUN): 띄울 때 더한 환경 변수 (LAUNCHED 와 같은 순서)`
- `launch()`: 머리를 `def launch(target, by, env=None):` 로, docstring 에 `env: 자식에게 더할 환경 변수 - 예약 줄의 이번 실행 모듈(RPA_RUN_MODULES)·띄운 까닭(RPA_RUN_TRIGGER)` 줄. DRY_RUN 갈래에 `LAUNCHED_ENV.append(dict(env or {}))`. Popen 의 `env=dict(os.environ, RPA_UNATTENDED="1")` → `env={**os.environ, "RPA_UNATTENDED": "1", **(env or {})}`. 끝 기록 묶음의 `now = datetime.datetime.now()` → `now = NOW()`, `sch["next_run_at"] = next_run_iso(sch, now)` → `advance(sch, now)`.
- `def launch_run_all(by):` 다음 줄부터 `def apply_schedule` 함수 끝까지를 아래로 바꾼다 (`normalize_days`·`next_slot`·`days_label` 은 내용 그대로):

```python
def launch_run_all(by):
    return launch("all", by)


# ---------------------------------------------------------------------------
# 자동 실행 예약 (2026-10-07 시각별 모듈, 설계 2026-10-06-settings-schedule 5절)
#   schedule = {enabled, days(월=0, 모든 줄이 같이 씀), slots:[{at, run?}], next_run_at, next_slot, policy?, last_*}
#   run 이 없는 줄은 '전체' (쇼핑몰 받기 + 실행 모듈 카드), 있으면 그 모듈만 - 띄울 때 RPA_RUN_MODULES 로 넘긴다
# ---------------------------------------------------------------------------
ROUTINE_KEYS = tuple(k for k, _ in st.ROUTINE_CONFIG_MODULES)      # Login, Sales, Hold, Logistics, Output
RUN_KEYS = ("Prepare",) + ROUTINE_KEYS                             # 줄의 run 에 쓰는 키. 이 순서로 저장한다
SLOT_NAMES = {"Prepare": "쇼핑몰 받기", "Sales": "주문매핑", "Hold": "물류대기", "Logistics": "물류관리", "Output": "운송장"}   # 화면 단추와 같은 말


def normalize_days(days):
    (지금 내용 그대로)


def _check_time(t):
    """"HH:MM" 5분 단위 → 고친 글. 틀리면 ValueError (사람에게 보일 글)."""
    if not isinstance(t, str) or len(t) != 5 or t[2] != ":" or not (t[:2] + t[3:]).isdigit():
        raise ValueError(f"시간 형식이 잘못되었습니다: {t!r}")
    hh, mm = int(t[:2]), int(t[3:])
    if hh > 23 or mm > 59 or mm % st.SCHEDULE_MINUTE_STEP:
        raise ValueError(f"시간은 00:00~23:55 사이 {st.SCHEDULE_MINUTE_STEP}분 단위여야 합니다: {t}")
    return f"{hh:02d}:{mm:02d}"


def normalize_times(times):
    """옛 모양의 시각 목록 ["HH:MM", ...] (옛 8765 화면·옛 웹이 보낸다) 을 검증해 중복 없이 정렬한다."""
    if not isinstance(times, list) or not times:
        raise ValueError("실행 시간을 하나 이상 넣으세요")
    out = sorted({_check_time(t) for t in times})
    if len(out) > st.SCHEDULE_MAX_SLOTS:
        raise ValueError(f"실행 시간은 {st.SCHEDULE_MAX_SLOTS}개까지 넣을 수 있습니다")
    return out


def normalize_run(run):
    """줄의 run (돌릴 모듈 키 목록). None 이면 '전체'. 고친 목록 (RUN_KEYS 순서). 틀리면 ValueError."""
    if run is None:
        return None
    if not isinstance(run, list) or not all(isinstance(k, str) for k in run):
        raise ValueError("모듈 목록이 잘못되었습니다")
    bad = [k for k in run if k not in RUN_KEYS]
    if bad:
        raise ValueError(f"모르는 모듈입니다: {', '.join(bad)}")
    if len(set(run)) != len(run):
        raise ValueError("같은 모듈이 두 번 있습니다")
    picked = set(run)
    if picked & {k for k in ROUTINE_KEYS if k != "Login"}:
        picked.add("Login")          # 루틴을 돌리면 로그인은 늘 (실행 모듈 카드처럼 못 끈다)
    else:
        picked.discard("Login")      # 루틴 모듈이 없으면 로그인만 돌릴 까닭이 없다
    if "Output" in picked and "Logistics" not in picked:
        raise ValueError("운송장 출력은 물류관리와 같이 골라야 합니다")
    if not picked:
        raise ValueError("모듈을 하나 이상 고르세요")
    return [k for k in RUN_KEYS if k in picked]


def normalize_slots(slots):
    """줄 목록 검사 → 시각 순으로 정렬한 새 목록. 틀리면 ValueError (사람에게 보일 글)."""
    if not isinstance(slots, list) or not slots:
        raise ValueError("실행 시간을 하나 이상 넣으세요")
    if len(slots) > st.SCHEDULE_MAX_SLOTS:
        raise ValueError(f"자동 실행은 {st.SCHEDULE_MAX_SLOTS}개까지 넣을 수 있습니다")
    out = []
    for s in slots:
        if not isinstance(s, dict):
            raise ValueError("자동 실행 줄이 잘못되었습니다")
        item = {"at": _check_time(s.get("at"))}
        run = normalize_run(s.get("run"))
        if run is not None:
            item["run"] = run
        out.append(item)
    out.sort(key=lambda x: x["at"])
    ats = [x["at"] for x in out]
    dup = sorted({a for a in ats if ats.count(a) > 1})
    if dup:
        raise ValueError(f"같은 시각이 두 번 있습니다: {', '.join(dup)}")
    return out


def next_slot(days, times, after):
    (지금 내용 그대로)


def sorted_slots(sch):
    """적힌 줄 (시각 순). 잘못 적힌 줄은 건너뛴다."""
    return sorted((s for s in sch.get("slots") or [] if isinstance(s, dict) and isinstance(s.get("at"), str)),
                  key=lambda s: s["at"])


def active_slots(sch):
    """도는 줄 (시각 순)."""
    return sorted_slots(sch)


def next_due(sch, after):
    """after 뒤 가장 가까운 예약 (시각, 그 줄). 없으면 (None, None)."""
    slots = active_slots(sch)
    when = next_slot(sch.get("days"), [s["at"] for s in slots], after)
    if when is None:
        return None, None
    at = when.strftime("%H:%M")
    return when, next(s for s in slots if s["at"] == at)


def advance(sch, now):
    """다음 예약 (next_run_at·next_slot) 을 now 뒤로 잡는다. 꺼져 있으면 비운다."""
    when, slot = next_due(sch, now) if sch.get("enabled") else (None, None)
    sch["next_run_at"] = when.isoformat(timespec="seconds") if when else None
    sch["next_slot"] = slot["at"] if slot else None


def next_run_iso(sch, after):
    when, _ = next_due(sch, after)
    return when.isoformat(timespec="seconds") if when else None


def slot_of(sch):
    """next_run_at 이 가리키는 줄 (next_slot, 없으면 next_run_at 의 시각으로 찾는다). 도는 줄에 없으면 None."""
    at = sch.get("next_slot") or (sch.get("next_run_at") or "")[11:16]
    return next((s for s in active_slots(sch) if s["at"] == at), None)


def slot_target(slot, off=()):
    """줄 하나 → (띄울 target, 자식 환경). '전체' 줄은 ('all', {}). 업체가 안 쓰는 모듈(off)을 빼고 나서 돌릴 게 없으면 (None, {})."""
    run = slot.get("run")
    if run is None:
        return "all", {}
    keys = [k for k in run if k not in set(off)]
    routine = [k for k in keys if k in ROUTINE_KEYS]
    if "Output" in routine and "Logistics" not in routine:
        routine.remove("Output")            # 물류관리가 빠지면 출력도 (루틴과 같은 규칙)
    if not set(routine) - {"Login"}:
        routine = []                         # 로그인만 남으면 루틴은 안 돈다
    prepare = "Prepare" in keys
    if not routine:
        return ("prepare", {}) if prepare else (None, {})
    return ("all" if prepare else "routine"), {"RPA_RUN_MODULES": ",".join(routine)}


def launch_slot(slot, by="auto", trigger="auto"):
    """예약 줄 하나를 띄운다. 업체가 안 쓰는 모듈만 남으면 RuntimeError (사람에게 보일 글 - 예약 칸의 까닭이 된다)."""
    off = (st.read_settings()["schedule"].get("policy") or {}).get("off") or []
    target, env = slot_target(slot, off)
    if target is None:
        raise RuntimeError("업체가 쓰지 않는 모듈만 남아 건너뜁니다")
    return launch(target, by, dict(env, RPA_RUN_TRIGGER=trigger))


def days_label(days):
    (지금 내용 그대로)


def slot_text(s):
    """줄 한 칸 글: '10:00' / '11:00 물류관리' / '11:00~12:00 반복 물류관리' (로그인은 안 적는다)."""
    head = f"{s['at']}~{s['until']} 반복" if s.get("until") else s["at"]
    if s.get("run") is None:
        return head
    return f"{head} {'·'.join(SLOT_NAMES[k] for k in s['run'] if k != 'Login')}".strip()


def schedule_label(sch):
    """'평일 09:00, 11:00 물류관리' 처럼 한 줄로. 줄이 많으면 앞 3개만."""
    parts = [slot_text(s) for s in sorted_slots(sch)]
    shown = ", ".join(parts[:3]) + (f" 외 {len(parts) - 3}개" if len(parts) > 3 else "")
    return f"{days_label(sch.get('days'))} {shown}".strip()


class Scheduler(threading.Thread):
    """settings.json 의 schedule (요일 + 줄) 대로 띄운다. 줄마다 무엇을 띄울지는 slot_target.

    - 이 프로그램(에이전트)이 떠 있는 동안만 돈다.
    - 꺼져 있던 동안 지난 예약은 켤 때 건너뛴다 (resync). 켜자마자 갑자기 돌지 않게.
    - RPA 가 이미 돌고 있으면 끝날 때까지 미룬다 (건너뛰지 않는다). 그 사이 지난 예약들은 한 번으로 합쳐진다.
    - 옵저버가 떠 있어도 닫힐 때까지 미룬다 (기록하던 사람과 RPA 가 화면·마우스를 두고 부딪히지 않게).
    - 띄운 뒤에는 다음 예약으로 옮긴다 (advance).
    """

    def __init__(self):
        super().__init__(name="rpa-scheduler", daemon=True)
        self.stop = threading.Event()
        self.waiting_reason = None
        self.skipped_at = None   # resync 가 건너뛴 예약 시각 (시작 안내용)

    def resync(self):
        """저장된 다음 실행 시각이 오래전에 지났으면 지금 이후의 예약으로 다시 잡는다."""
        with _settings_lock:
            cfg = st.read_settings()
            sch = cfg["schedule"]
            if not sch.get("enabled"):
                return
            now = NOW()
            nxt = st.parse_iso(sch.get("next_run_at"))
            if nxt is not None and (now - nxt).total_seconds() <= MISSED_GRACE_SEC:
                return
            if nxt is not None:
                self.skipped_at = nxt
            advance(sch, now)
            st.write_settings(cfg)

    def run(self):
        while not self.stop.wait(SCHEDULER_TICK):
            self.tick_safe()

    def tick_safe(self):
        try:
            self.tick()
        except RuntimeError as e:          # launch 의 거절 (토큰이 없음 등) - 사람에게 보일 글 그대로
            self._record_error(str(e))
        except Exception as e:
            self._record_error(f"{type(e).__name__}: {e}")

    def _record_error(self, text):
        with _settings_lock:
            cfg = st.read_settings()
            sch = cfg["schedule"]
            sch["last_error"] = text
            advance(sch, NOW())             # 같은 오류로 5초마다 되풀이하지 않게 다음 예약으로
            st.write_settings(cfg)

    def _advance_now(self, now):
        with _settings_lock:
            cfg = st.read_settings()
            advance(cfg["schedule"], now)
            st.write_settings(cfg)
        return cfg["schedule"]

    def busy(self):
        """지금 띄우면 안 되는 까닭 (없으면 None)."""
        if any_rpa_running():
            return "RPA 가 아직 돌고 있어 끝나기를 기다립니다"
        if launch_state() is not None:
            return "대시보드가 띄운 실행이 끝나기를 기다립니다"
        if st.observer_open():
            return "옵저버가 켜져 있어 닫히기를 기다립니다"
        return None

    def tick(self):
        sch = st.read_settings()["schedule"]
        if not sch.get("enabled"):
            self.waiting_reason = None
            return
        now = NOW()
        next_run = st.parse_iso(sch.get("next_run_at"))
        if next_run is None:
            sch = self._advance_now(now)
            self.waiting_reason = None if sch["next_run_at"] else "요일·시간 설정이 비어 있습니다"
            return
        if now < next_run:
            self.waiting_reason = None
            return
        slot = slot_of(sch)
        if slot is None:                   # 가리키던 줄이 없어졌다 (줄을 고쳤거나 한도가 줄었다) - 띄우지 않고 다음 줄로
            self._advance_now(now)
            return
        self.waiting_reason = self.busy()
        if self.waiting_reason is None:
            self.launch(slot)

    def launch(self, slot):
        launch_slot(slot)


SCHEDULER = Scheduler()


def schedule_view():
    sch = st.read_settings()["schedule"]
    now = NOW()
    nxt = st.parse_iso(sch.get("next_run_at")) if sch.get("enabled") else None
    slots = sorted_slots(sch)
    return {
        "version": st.SCHEDULE_VERSION,
        "enabled": bool(sch.get("enabled")),
        "days": list(sch.get("days") or []),
        "slots": slots,
        "times": [s["at"] for s in slots if not s.get("until")],   # 옛 8765 화면 (dashboard.html) 은 시각 목록만 안다
        "label": schedule_label(sch),
        "next_run_at": nxt.isoformat(timespec="seconds") if nxt else None,
        "next_slot": sch.get("next_slot") if nxt else None,
        "next_run_in_sec": max(0, int((nxt - now).total_seconds())) if nxt else None,
        "policy": sch.get("policy"),
        "last_launch_at": sch.get("last_launch_at"),
        "last_launch_by": sch.get("last_launch_by"),
        "last_error": sch.get("last_error"),
        "waiting_reason": SCHEDULER.waiting_reason,
        "last_launch_target": sch.get("last_launch_target"),
        "launch": launch_state(),            # 대시보드가 띄운 실행이 살아 있으면 {target, by, sec}
        "launching_sec": launching_sec(),    # 살아 있는데 아직 기록이 없으면 몇 초째
    }


def apply_schedule(payload):
    """'적용'. 요일·줄을 검증해 저장하고, 바뀐 것이 있으면 다음 시각을 다시 잡는다.
    payload: {enabled, days, slots} - 옛 화면(8765·옛 웹)이 보내는 {enabled, days, times} 도 받는다 (모두 '전체' 줄).
    끌 때는 요일·줄이 비어도 된다."""
    if not isinstance(payload, dict):
        raise ValueError("잘못된 요청입니다")
    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        raise ValueError("enabled 는 true/false 여야 합니다")
    raw_days = payload.get("days")
    days = [] if not enabled and raw_days in (None, []) else normalize_days(raw_days)
    raw = payload.get("slots") if "slots" in payload else payload.get("times")
    if not enabled and raw in (None, []):
        slots = []
    elif "slots" in payload:
        slots = normalize_slots(raw)
    else:
        slots = [{"at": t} for t in normalize_times(raw)]
    with _settings_lock:
        cfg = st.read_settings()
        sch = cfg["schedule"]
        changed = bool(sch.get("enabled")) != enabled or sch.get("days") != days or sch.get("slots") != slots
        sch.pop("interval_min", None)   # 예전 '실행 주기' 방식의 값
        sch.update(enabled=enabled, days=days, slots=slots)
        if changed:
            sch["last_error"] = None
            advance(sch, NOW())
        if not st.write_settings(cfg):
            raise RuntimeError("설정 파일을 쓰지 못했습니다")
    return changed
```
- `settings_view` 의 `"schedule_limits": {"max_times": st.SCHEDULE_MAX_TIMES, …}` → `st.SCHEDULE_MAX_SLOTS`.

- [ ] **Step 6: `run_routine.py`** - `ROUTINE_MODULES = (…)` 정의 아래:

```python
RUN_MODULES_ENV = "RPA_RUN_MODULES"   # 예약 줄이 고른 이번 실행 모듈 (rpa_dashboard.launch_slot) - 있으면 설정 파일 대신


def run_modules_from_env(keys):
    """예약이 넘긴 이번 실행 모듈. ({설정 키: True/False}, 모르는 키) - 변수가 없으면 (None, []).
    로그인은 늘 켬, 물류관리가 없으면 출력은 뺀다 (설정 파일 규칙과 같다). 돌릴 게 없으면 전부 False."""
    raw = os.environ.get(RUN_MODULES_ENV)
    if raw is None:
        return None, []
    wanted = [k.strip() for k in raw.split(",") if k.strip()]
    unknown = [k for k in wanted if k not in keys]
    on = {k for k in wanted if k in keys}
    if "Logistics" not in on:
        on.discard("Output")
    if not on - {"Login"}:
        return {k: False for k in keys}, unknown
    on.add("Login")
    return {k: k in on for k in keys}, unknown
```
`main()` 의 모듈 읽기 부분(`try: selected, unknown = pl.load_routine_modules(...)` 부터 `log("실행할 모듈: " …)` 까지)을:

```python
    keys = [m[1] for m in ROUTINE_MODULES]
    selected, unknown = run_modules_from_env(keys)
    from_env = selected is not None
    if not from_env:
        try:
            selected, unknown = pl.load_routine_modules(keys)
        except Exception as e:
            log(f"설정 오류: {e}")
            status.finish("stopped", f"설정 파일 오류: {e}")
            log(f"=== 루틴 종료 {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
            return
    for k in unknown:
        log(f"경고: 예약에서 넘긴 '{k}' 는 모르는 모듈이라 무시합니다." if from_env
            else f"경고: '{pl.ROUTINE_SECTION}' 섹션의 '{k}' 는 모르는 키라 무시합니다.")
    if from_env and not any(selected.values()):
        log("이번 실행 모듈이 비었습니다 (예약에서 넘긴 값)")
        status.finish("stopped", "이번 실행 모듈이 비었습니다")
        log(f"=== 루틴 종료 {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
        return
    if from_env:
        log("이번 실행 모듈 (예약): " + " / ".join(label for _, cfg, label, _, _ in ROUTINE_MODULES if selected[cfg]))
    else:
        log("실행할 모듈: " + " / ".join(
            f"{label} {'켬' if selected[cfg] else '끔'}" for _, cfg, label, _, _ in ROUTINE_MODULES))
```
(`os` 가 이미 import 되어 있는지 확인 - 없으면 맨 위 import 에 더한다.)

- [ ] **Step 7: 다른 시험 맞추기**
- `firebase/tests/integration.js`: `saved.times.join() === "09:05,13:30"` → `saved.slots.map((s) => s.at).join() === "09:05,13:30" && !("times" in saved)`, 문구 `"PC 의 settings.json 에 저장 (옛 모양으로 보내도 '전체' 줄로)"`. `live.schedule 로 올라온다` 의 경로·비교를 `((await db.ref("apps/rpa/live/c_demo/pc_office/schedule/slots").get()).val() || []).map((s) => s.at).join() === "09:05,13:30"` 로. 그 `waitFor` 바로 뒤에:
```js
const slotRef = await db.ref("apps/rpa/commands/c_demo/pc_office").push({
  type: "set_schedule", args: { enabled: true, days: [0, 2, 4], slots: [{ at: "10:00" }, { at: "11:00", run: ["Logistics"] }] }, by: adminUser.uid,
  created_at: now, expires_at: now + 600, state: "queued",
});
await waitFor("줄 모양 set_schedule 도 done", async () => (await slotRef.child("state").get()).val() === "done");
check(/월·수·금 10:00, 11:00 물류관리/.test(((await slotRef.get()).val().result) || ""), "결과 글에 줄의 모듈");
```
- `tests/check_schedule_ui.py`: 거부 목록의 `(b'{"schedule":{"enabled":true,"days":[0],"times":["08:00","09:00","10:00","11:00"]}}', "시간 4개")` → `(json.dumps({"schedule": {"enabled": True, "days": [0], "times": [f"{h:02d}:00" for h in range(13)]}}).encode(), "시간 13개")` (`json` import 확인).

- [ ] **Step 8: 통과 확인** - test_schedule_slots, test_routine_modules, test_dashboard_auth, check_schedule_ui, `python tests\test_agent.py`, integration. 기대: 모두 실패 0.
- [ ] **Step 9:** `graphify update .` → 커밋은 사용자에게 묻는다.

---

### Task 3: 업체 한도 '자동 실행 개수' (예약기·에이전트·관리 도구)

**Files:**
- Modify: `rpa_dashboard.py` (`active_slots` 자르기, `set_policy`)
- Modify: `firebase/agent/agent.py` (`company_policy`, `Policy`, `next_plan`, `Tokens`, `real_actions`, `run`)
- Modify: `firebase/admin/ops.js`, `firebase/admin/admin.js`, `firebase/admin/setup.js`, `firebase/admin/AFTERMARKET_SETUP.html`, `firebase/admin/README.md`
- Test: `tests/test_schedule_slots.py`, `firebase/tests/test_agent.py`, `firebase/tests/check_admin.py`, `firebase/tests/check_setup.py`

**Interfaces:**
- Consumes: Task 2 의 `sorted_slots`, `advance`, `slot_of`, `apply_schedule`, `schedule_label`, `NOW`
- Produces (`rpa_dashboard`): `active_slots(sch)` (policy.limit 으로 자른다), `set_policy(limit, off) → bool`
- Produces (`agent`): `SCHEDULE_LIMIT_DEFAULT = 2`, `company_policy(client, cid) → (limit, off)`, `Policy(client, cid).refresh(force=False) → (limit, off)|None`, `next_plan() → (mods, with_prepare)|None`, `Tokens(..., next_plan=None)` (`costs()` 에 `next`), `real_actions(policy=None, limits=None)`
- Produces (`ops.js`): `SCHEDULE_LIMIT_DEFAULT`, `SCHEDULE_LIMIT_MAX`, `setScheduleLimit(cid, n) → {cid, schedule}`, `scheduleLimitOf(cid) → number|null`, `companyDetail(cid).scheduleLimit`
- Produces (`admin.js`): `POST /api/companies/:cid/limits {schedule}`; (`setup.js`): `slots <cid> [개수]`

- [ ] **Step 1: 실패할 시험 - `tests/test_schedule_slots.py`** (8절 앞에 새 절):

```python
print("\n=== 9. 업체 한도·안 쓰는 모듈 (에이전트가 policy 를 적는다) ===")
d.apply_schedule({"enabled": True, "days": list(range(7)), "slots": [{"at": "10:00"}, {"at": "11:00", "run": ["Hold"]}, {"at": "12:00"}]})
check([s["at"] for s in d.active_slots(st.read_settings()["schedule"])] == ["10:00", "11:00", "12:00"], "한도를 모르면 자르지 않는다")
check(d.set_policy(2, ["Hold"]) is True and d.set_policy(2, ["Hold"]) is False, "정책을 적고, 같으면 다시 안 쓴다")
sch = st.read_settings()["schedule"]
check([s["at"] for s in d.active_slots(sch)] == ["10:00", "11:00"] and len(d.schedule_view()["slots"]) == 3
      and sch["slots"][2] == {"at": "12:00"} and sch["next_slot"] in ("10:00", "11:00"),
      "한도 2 → 시각 순 앞 2줄만 돈다 (줄은 지우지 않는다 - Review Focus 3)")
saved = list(d.LAUNCHED)
c = st.read_settings(); c["schedule"]["next_slot"] = "12:00"; c["schedule"]["next_run_at"] = (dt.datetime.now() - dt.timedelta(seconds=3)).isoformat(timespec="seconds"); st.write_settings(c)
sched.tick()
check(d.LAUNCHED == saved and st.read_settings()["schedule"]["next_slot"] in ("10:00", "11:00"), "가리키던 줄이 한도로 빠졌으면 띄우지 않고 다음 줄로")
c = st.read_settings(); c["schedule"]["next_slot"] = "11:00"; c["schedule"]["next_run_at"] = (dt.datetime.now() - dt.timedelta(seconds=3)).isoformat(timespec="seconds"); st.write_settings(c)
sched.tick_safe()
check(d.LAUNCHED == saved and st.read_settings()["schedule"]["last_error"] == "업체가 쓰지 않는 모듈만 남아 건너뜁니다",
      f"줄의 모듈이 모두 업체가 안 쓰는 것 → 건너뛰고 까닭 ({st.read_settings()['schedule']['last_error']})")
d.set_policy(0, [])
check(d.active_slots(st.read_settings()["schedule"]) == [] and d.schedule_view()["next_run_at"] is None, "한도 0 → 아무것도 안 돈다")
d._active["until"] = 0; d._active["proc"] = None
```

- [ ] **Step 2: 실패할 시험 - `firebase/tests/test_agent.py`** (5-2절 끝, 8절 앞):

```python
print("\n5-3절 업체 정책: 자동 실행 개수 (2026-10-07)")


class AppClient:
    def __init__(self, value):
        self.value, self.asked = value, []

    def get(self, path):
        self.asked.append(path)
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


ac = AppClient({"modules": {"Hold": False, "Sales": True}, "limits": {"schedule": 3}})
check(ag.company_policy(ac, "c_x") == (3, ["Hold"]) and ac.asked == ["meta/companies/c_x/apps/rpa"], "한 번 읽어 한도와 안 쓰는 모듈")
check(ag.company_policy(AppClient(None), "c_x") == (2, []), "정책이 없으면 기본 2개·안 쓰는 모듈 없음")
check(ag.company_policy(AppClient({"limits": {"schedule": "9"}}), "c_x")[0] == 2 and ag.company_policy(AppClient({"limits": {"schedule": 0}}), "c_x")[0] == 0,
      "이상한 값은 기본 2, 0 은 0 (자동 실행을 못 쓴다)")
with tempfile.TemporaryDirectory() as d:
    os.environ["RPA_STATUS_DIR"] = d              # 실제 settings.json 을 건드리지 않게
    os.environ["RPA_DASHBOARD_DRY_RUN"] = "1"
    try:
        import rpa_status as st
        import rpa_dashboard as dash
        three = {"enabled": True, "days": [0], "slots": [{"at": "09:00"}, {"at": "10:00"}, {"at": "11:00"}]}
        acts = ag.real_actions(limits=lambda: (2, ["Hold"]))
        try:
            acts["set_schedule"](three); check(False, "한도를 넘는 줄 수는 거절")
        except RuntimeError as e:
            check(str(e) == "자동 실행은 2개까지입니다" and st.read_settings()["schedule"]["slots"] == [{"at": "09:00"}], f"한도를 넘으면 저장 전에 거절 ({e})")
        msg = acts["set_schedule"]({"enabled": True, "days": [0], "slots": [{"at": "09:00"}, {"at": "11:00", "run": ["Logistics"]}]})
        check("월 09:00, 11:00 물류관리" in msg, f"한도 안이면 저장 ({msg})")
        dash.set_policy(1, [])
        try:
            ag.real_actions(limits=lambda: None)["set_schedule"](three); check(False, "못 읽어도 적힌 한도로 거절")
        except RuntimeError as e:
            check("1개까지" in str(e), "못 읽으면 PC 에 적힌 마지막 한도로")
        st.write_settings({"schedule": {}})       # policy 없음 = 한 번도 못 읽음
        ag.real_actions(limits=lambda: None)["set_schedule"](three)
        check(len(st.read_settings()["schedule"]["slots"]) == 3, "한 번도 못 읽었으면 자르지 않는다 (PC 상한 12 까지만)")
        pol = ag.Policy(AppClient({"limits": {"schedule": 3}, "modules": {"Hold": False}}), "c_x")
        check(pol.refresh() == (3, ["Hold"]) and st.read_settings()["schedule"]["policy"]["limit"] == 3
              and st.read_settings()["schedule"]["policy"]["off"] == ["Hold"], "정책을 읽어 PC 설정에 적는다")
        check(pol.refresh() is None, "10분 안에는 다시 안 읽는다")
        check(ag.Policy(AppClient(fb.HttpError(503, "끊김")), "c_x").refresh(force=True) is None
              and st.read_settings()["schedule"]["policy"]["limit"] == 3, "못 읽으면 적힌 값 그대로")
        dash.apply_schedule({"enabled": True, "days": list(range(7)), "slots": [{"at": "11:00", "run": ["Prepare", "Logistics"]}]})
        tc = TokenClient(9, 0)
        tk = ag.Tokens(tc, "c_demo", ag.Prices(tc), plan, next_plan=ag.next_plan)
        tk.refresh(force=True)
        check(tk.view()["cost"]["next"] == 3, f"다음 예약 줄의 토큰 = 그 줄의 모듈 (물류관리 1·로그인 0) + 쇼핑몰 받기 (사이트 2) ({tk.view()['cost']})")
        dash.apply_schedule({"enabled": True, "days": list(range(7)), "slots": [{"at": "11:00"}]})
        check("next" not in tk.costs(), "'전체' 줄이면 next 없음 (화면은 전체 실행 토큰을 쓴다)")
    finally:
        os.environ.pop("RPA_STATUS_DIR", None)
```

- [ ] **Step 3: 실패할 시험 - 관리 도구**

`firebase/tests/check_admin.py` 3절 `"모듈 정책 켜기 (정책을 지운다 = 그 업체가 쓴다)"` check 바로 아래:
```python
code, d = api("GET", "/api/companies/t_new")
check(code == 200 and d.get("scheduleLimit") is None, "자동 실행 개수: 값이 없으면 null (화면은 기본 2)", str(d.get("scheduleLimit")))
code, r = api("POST", "/api/companies/t_new/limits", {"schedule": "3"})
check(code == 200 and r == {"cid": "t_new", "schedule": 3} and db_get("meta/companies/t_new/apps/rpa/limits/schedule") == 3, "자동 실행 개수 3", r)
for bad in ("13", "-1", "2.5", "", "셋"):
    code, r = api("POST", "/api/companies/t_new/limits", {"schedule": bad})
    check(code == 400 and "0~12" in r.get("error", "") and db_get("meta/companies/t_new/apps/rpa/limits/schedule") == 3, f"자동 실행 개수 거절 {bad!r}", r)
```
4절(화면)에서 t_new 상세를 연 뒤 토큰 넣기 시험 다음에:
```python
    page.fill("#detail input[aria-label='자동 실행 개수']", "4")
    page.click("#detail .row:has(input[aria-label='자동 실행 개수']) button")
    page.wait_for_function("document.querySelector(\"#detail input[aria-label='자동 실행 개수']\")?.value === '4'", timeout=10000)
    check(db_get("meta/companies/t_new/apps/rpa/limits/schedule") == 4, "화면: 업체 상세에서 자동 실행 개수 저장")
```
`firebase/tests/check_setup.py` 마지막 절 뒤(결과 출력 앞):
```python
print("=== 5. 자동 실행 개수 (slots, 2026-10-07) ===")
rc, out = setup("slots", CID)
check(rc == 0 and "2 (기본)" in out, "값이 없으면 기본 2", out[-200:])
rc, out = setup("slots", CID, "3")
check(rc == 0 and db_get(f"meta/companies/{CID}/apps/rpa/limits/schedule") == 3 and "= 3" in out, "slots 3", out[-200:])
rc, out = setup("slots", CID, "13")
check(rc != 0 and out.strip().startswith("오류:") and db_get(f"meta/companies/{CID}/apps/rpa/limits/schedule") == 3, "13 은 거절 (0~12)", out[-200:])
rc, out = setup("slots", "t_none", "3")
check(rc != 0 and "먼저 company" in out, "없는 업체는 거절", out[-200:])
```

- [ ] **Step 4: 실패 확인** - test_schedule_slots (`set_policy` 없음), test_agent (`company_policy` 없음), check_admin·check_setup (404·도움말).

- [ ] **Step 5: `rpa_dashboard.py`** - `active_slots` 를 바꾸고 `set_policy` 를 더한다:

```python
def active_slots(sch):
    """도는 줄 (시각 순). 업체 한도(policy.limit - 에이전트가 적는다)를 넘는 줄은 뺀다: 시각 순으로 앞 N줄만 (설계 5-3).
    한도를 모르면 (에이전트가 한 번도 못 읽었으면) 자르지 않는다 - PC 상한 12 는 저장할 때 지킨다."""
    out = sorted_slots(sch)
    limit = (sch.get("policy") or {}).get("limit")
    if isinstance(limit, int) and not isinstance(limit, bool) and limit >= 0:
        return out[:limit]
    return out


def set_policy(limit, off):
    """에이전트가 읽은 업체 정책(자동 실행 개수·안 쓰는 모듈)을 settings.json 에 적는다 - 껐다 켜도·끊겨도 마지막 값.
    같으면 안 쓴다 (False). 가리키던 다음 줄이 한도로 빠졌으면 다음 줄을 다시 잡는다. 다른 칸(줄·반복 상태)은 그대로."""
    new = {"limit": limit, "off": sorted(off)}
    with _settings_lock:
        cfg = st.read_settings()
        sch = cfg["schedule"]
        old = sch.get("policy") or {}
        if (old.get("limit"), old.get("off")) == (new["limit"], new["off"]):
            return False
        sch["policy"] = dict(new, read_at=now_text())
        if sch.get("next_slot") and sch["next_slot"] not in [s["at"] for s in active_slots(sch)]:
            advance(sch, NOW())
        st.write_settings(cfg)
        return True
```

- [ ] **Step 6: `firebase/agent/agent.py`**
- `PRICES_EVERY_SEC = 600` 아래:
```python
SCHEDULE_LIMIT_DEFAULT = 2      # 업체 한도 '자동 실행 개수' 가 없을 때 (설계 5-3, ops.js 와 같다)
SCHEDULE_LIMIT_MAX = 12         # rpa_status.SCHEDULE_MAX_SLOTS 와 같다
```
- `local_plan()` 아래:
```python
def next_plan():
    """다음 예약 줄이 '고르기' 면 그 계획 (루틴 모듈 키 소문자 목록, 쇼핑몰 받기 여부) - 업체가 안 쓰는 모듈은 뺀다.
    '전체' 거나 다음 예약이 없으면 None (화면은 전체 실행 토큰을 쓴다)."""
    import rpa_dashboard as dash
    import rpa_status as st
    sch = st.read_settings()["schedule"]
    slot = dash.slot_of(sch) if sch.get("enabled") and sch.get("next_run_at") else None
    if not slot or slot.get("run") is None:
        return None
    off = set((sch.get("policy") or {}).get("off") or [])
    run = [k for k in slot["run"] if k not in off]
    return [k.lower() for k in run if k != "Prepare"], "Prepare" in run
```
- `Tokens.__init__` 머리를 `def __init__(self, client, cid, prices, plan=local_plan, every=PRICES_EVERY_SEC, next_plan=None):`, 본문에 `self._next_plan = next_plan` (기본 None - 시험이 costs 를 그대로 비교한다). `costs()` 를:
```python
    def costs(self):
        """실행 1번에 드는 토큰 = 켠 모듈·사이트 × 값표 (실패한 것은 안 빠지니 많아야 이만큼). 다음 예약 줄이 '고르기' 면 next 도."""
        mods, sites = self._plan()
        table = self._prices.get()
        routine = run_cost({m: 1 for m in mods}, table)
        prepare = run_cost({"sites": sites}, table) if sites else 0
        out = {"routine": routine, "prepare": prepare, "all": routine + prepare}
        nxt = self._next_plan() if self._next_plan else None
        if nxt is not None:
            out["next"] = run_cost({m: 1 for m in nxt[0]}, table) + (prepare if nxt[1] else 0)
        return out
```
- `company_modules` 아래:
```python
def company_policy(client, cid, app=APP):
    """업체 정책 한 번에 - (자동 실행 개수, 안 쓰는 모듈 키 목록). 자리 meta/companies/{cid}/apps/{app} (총괄·Admin SDK 만 쓴다).
    한도가 없거나 이상하면 기본 2. 못 읽으면 예외 - 부르는 쪽이 지난 값을 쓴다."""
    got = client.get(f"meta/companies/{cid}/apps/{app}") or {}
    raw = (got.get("limits") or {}).get("schedule")
    ok = isinstance(raw, int) and not isinstance(raw, bool) and 0 <= raw <= SCHEDULE_LIMIT_MAX
    return (raw if ok else SCHEDULE_LIMIT_DEFAULT), sorted(k for k, v in (got.get("modules") or {}).items() if v is False)


class Policy:
    """업체 정책을 10분마다 읽어 PC 설정(settings.json schedule.policy)에 적는다 - 예약기가 그 값으로 줄을 자르고 모듈을 뺀다.
    못 읽으면 적힌 값 그대로 (지난 값)."""

    def __init__(self, client, cid, every=PRICES_EVERY_SEC):
        self._client, self._cid, self._every, self._at = client, cid, every, None

    def refresh(self, force=False):
        """읽었으면 (limit, off), 아직 때가 아니거나 못 읽었으면 None."""
        if not force and self._at is not None and time.time() - self._at < self._every:
            return None
        self._at = time.time()
        try:
            got = company_policy(self._client, self._cid)
        except fb.AuthError:
            raise
        except Exception:
            return None
        import rpa_dashboard as dash
        dash.set_policy(*got)
        return got
```
- `real_actions` 머리를 `def real_actions(policy=None, limits=None):`, docstring 에 `limits: 업체 정책을 지금 읽어 (limit, off) 를 돌려주는 함수 - 못 읽으면 None (PC 에 적힌 마지막 값을 쓴다)` 줄. `do_schedule` 을:
```python
    def do_schedule(args):
        # 업체 한도 '자동 실행 개수' - 화면을 거치지 않은 명령도 여기서 막힌다 (설계 5-3). 못 읽으면 PC 에 적힌 마지막 값,
        # 한 번도 못 읽었으면 자르지 않는다. 검증·저장·다음 시각 계산은 apply_schedule (요일 0~6, 5분 단위, PC 상한 12)
        got = limits() if limits else None
        limit = got[0] if got else (st.read_settings()["schedule"].get("policy") or {}).get("limit")
        rows = (args.get("slots") if "slots" in args else args.get("times")) if isinstance(args, dict) else None
        if isinstance(limit, int) and isinstance(rows, list) and len(rows) > limit:
            raise RuntimeError(f"자동 실행은 {limit}개까지입니다")
        changed = dash.apply_schedule(args)
        sch = st.read_settings()["schedule"]
        if not sch.get("enabled"):
            return "자동 실행을 껐습니다"
        return f"자동 실행: {dash.schedule_label(sch)}" + ("" if changed else " (변경 없음)")
```
- `run()`: `tokens = Tokens(...)` 앞에 `policy = Policy(client, cfg["cid"])         # 업체 정책 (자동 실행 개수·안 쓰는 모듈) - 10분마다 PC 설정에 적는다`, `tokens = Tokens(client, cfg["cid"], prices, next_plan=next_plan)`, `cmds = Commands(..., real_actions(lambda: company_modules(client, cfg["cid"]), limits=lambda: policy.refresh(force=True)))`. `pump()` 의 `snap["schedule"] = …` 줄 바로 위에 `policy.refresh()`.

- [ ] **Step 7: `firebase/admin/ops.js`** - `PRICE_BASE` 줄 아래 상수 둘, `setModules` 아래 함수 둘:

```js
export const SCHEDULE_LIMIT_DEFAULT = 2;   // 자동 실행 개수 - 값이 없을 때 (agent.SCHEDULE_LIMIT_DEFAULT 와 같다)
export const SCHEDULE_LIMIT_MAX = 12;      // PC 쪽 절대 상한 (rpa_status.SCHEDULE_MAX_SLOTS)
```
```js
// 자동 실행 개수 = 시각·반복 시간대를 합친 줄 수 (설계 5-3). 유료 옵션 자리 - 업체마다 우리가 정한다. PC 에는 10분 안에 닿는다
export async function setScheduleLimit(cid, n) {
  checkKey("cid", cid);
  await companyOf(cid, { removed: true });
  const s = String(n ?? "").trim();
  if (!/^\d+$/.test(s) || Number(s) > SCHEDULE_LIMIT_MAX) throw new Refused(`자동 실행 개수는 0~${SCHEDULE_LIMIT_MAX} 정수 (받은 값: ${s})`);
  await rtdb.ref(`meta/companies/${cid}/apps/rpa/limits/schedule`).set(Number(s));
  return { cid, schedule: Number(s) };
}
export async function scheduleLimitOf(cid) {
  checkKey("cid", cid);
  return (await companyOf(cid, { removed: true })).apps?.rpa?.limits?.schedule ?? null;
}
```
`companyDetail` 돌려주는 객체의 `modules: …,` 다음에 `scheduleLimit: v.apps?.rpa?.limits?.schedule ?? null,`.

- [ ] **Step 8: `firebase/admin/admin.js`** - ROUTES 의 `/modules` 줄 아래:
```js
  ["POST", "/api/companies/:cid/limits", (b, p) => ops.setScheduleLimit(p.cid, b.schedule), (b, r, p) => `자동 실행 개수 ${p.cid} = ${r.schedule}`],
```

- [ ] **Step 9: `firebase/admin/setup.js`**
- 도움말 `modules` 줄 아래: `//   node setup.js slots    <cid> [개수]                            자동 실행 개수 (시각·반복 시간대를 합친 줄 수, 기본 2, 0~12). 개수가 없으면 보기`
- `ARGC` 에 `slots: [1, 2],`
- `modules` 갈래 아래:
```js
  } else if (cmdName === "slots") {
    const [cid, n] = rest;
    if (n === undefined) {
      const v = await ops.scheduleLimitOf(cid);
      console.log(`자동 실행 개수: ${cid}  ${v ?? `${ops.SCHEDULE_LIMIT_DEFAULT} (기본)`}`);
    } else {
      const r = await ops.setScheduleLimit(cid, n);
      console.log(`자동 실행 개수: ${r.cid} = ${r.schedule} (PC 에는 10분 안에 닿는다)`);
    }
```

- [ ] **Step 10: `firebase/admin/AFTERMARKET_SETUP.html`** - `moduleSection` 아래에 함수, `openDetail` 의 `moduleSection(d), dangerSection(d)` → `moduleSection(d), limitSection(d), dangerSection(d)`:
```js
function limitSection(d) {
  const n = el("input", { value: d.scheduleLimit ?? 2, size: 4, inputmode: "numeric", "aria-label": "자동 실행 개수" });
  const save = el("button", { onclick: () => act(save, async () => {
    const r = await api("POST", `/api/companies/${d.cid}/limits`, { schedule: n.value.trim() });
    flash(`자동 실행 개수: ${r.schedule} (PC 에는 10분 안에 닿습니다)`);
    openDetail(d.cid);
  }) }, "저장");
  return el("div", {}, el("h3", {}, "자동 실행 개수"),
    el("p", { class: "muted" }, `기본 2. 시각과 반복 시간대를 합친 줄 수 (0~12)${d.scheduleLimit == null ? " - 지금은 기본값" : ""}`),
    el("div", { class: "row" }, n, save));
}
```
- `firebase/admin/README.md` 터미널 명령 목록의 `modules` 줄 아래에 `node setup.js slots c_demo 3        # 자동 실행 개수 (기본 2, 시각·반복 시간대 합친 줄 수)` 한 줄.

- [ ] **Step 11: 통과 확인** - test_schedule_slots, test_agent, check_admin, check_setup. 기대: 모두 실패 0 (관리 화면 서버 출력·`관리_기록.txt` 에 비밀번호 없음 시험도 그대로).
- [ ] **Step 12:** `graphify update .` → 커밋은 사용자에게 묻는다.

---

### Task 4: 웹 자동 실행 카드 - 줄마다 모듈·업체 한도·옛 판 모드

**Files:**
- Modify: `firebase/web/rpa-common.js` (줄 이름 도우미), `firebase/web/rpa-settings.js` (자동 실행 절), `firebase/web/rpa.js` (상태 띠 다음 실행 글), `firebase/web/index.html` (줄 CSS)
- Test: `firebase/tests/check_web.py`

**Interfaces:**
- Consumes: Task 1 의 rpa-settings 구조, Task 2 의 live.schedule (`version`·`slots`·`next_slot`), Task 3 의 `live.tokens.cost.next`·`meta…limits.schedule`
- Produces (`rpa-common.js`): `RUN_CHIPS`, `RUN_NAMES`, `slotNames(slot) → string`, `slotText(slot) → string`
- Produces (`rpa-settings.js`): `limitOf()`, `isV2()`, `savedSlots()`, `runChips(slot, withPrepare)`, `timeInput(value, label, apply)`, `scheduleProblem() → string`, `payloadOf()` (Task 7 이 넓힌다)

- [ ] **Step 1: 실패할 시험 - `firebase/tests/check_web.py`**
- 6절 `check(page.is_disabled("#sch-apply"), "PC 값이 돌아오면 요약 갱신·적용 비활성")` 바로 아래에:
```python
    check(page.is_visible("#sch-old") and page.locator("#sch-times select").count() == 0,
          "옛 판 PC (live.schedule 에 version 없음): 시각만, 새 판 안내가 보인다 (Review Focus 4)")
    # 새 판 PC (2부): 줄마다 전체/고르기
    db_patch(f"{LIVE}/schedule", {"version": 2, "slots": [{"at": "09:05"}, {"at": "13:30"}], "times": None, "next_slot": "13:30",
                                  "next_run_at": "2026-09-22T13:30:00"})
    page.wait_for_function("document.querySelectorAll('#sch-times select').length === 2", timeout=10000)
    check(page.is_hidden("#sch-old") and page.text_content("#sch-count") == "2/2 사용", "새 판 PC: 줄마다 고르기, 한도 2 중 2 사용")
    check("자동 실행은 2개까지입니다" in page.text_content("#sch-limit") and page.is_disabled("#sch-add"), "한도에 닿으면 추가 잠김 + 문의 안내")
    check("전체 실행과 '전체' 예약이 이 모듈을 돌립니다" in page.text_content("#mod-card"), "실행 모듈 카드: '전체' 의 뜻")
    page.select_option("#sch-times .t:nth-child(2) select", "pick")
    chips = "#sch-times .t:nth-child(2) .chips button"
    check(page.locator(chips).count() == 5 and page.is_disabled("#sch-apply") and "모듈을 하나 이상" in page.text_content("#sch-limit"),
          "고르기: 모듈 단추 다섯, 하나도 안 고르면 적용 안 됨")
    check(page.is_disabled(f"{chips}[data-k='Output']"), "운송장은 물류관리를 고르기 전엔 잠김")
    page.click(f"{chips}[data-k='Logistics']")
    check(not page.is_disabled("#sch-apply") and not page.is_disabled(f"{chips}[data-k='Output']"), "물류관리를 고르면 적용 가능·운송장 풀림")
    page.click("#sch-apply"); time.sleep(1.5)
    saved = db_get(f"{SETTINGS}/schedule") or {}
    check(saved.get("slots") == [{"at": "09:05"}, {"at": "13:30", "run": ["Logistics"]}] and "times" not in saved,
          f"새 모양으로 저장 - '전체' 줄엔 run 없음 ({saved.get('slots')})")
    key = [k for k, v in (db_get(CMDS) or {}).items() if v.get("type") == "set_schedule"][-1]
    db_patch(f"{CMDS}/{key}", {"state": "done", "result": "자동 실행: 매일 09:05, 13:30 물류관리", "started_at": 1, "ended_at": 2})
    db_patch(f"{LIVE}/schedule", {"slots": [{"at": "09:05"}, {"at": "13:30", "run": ["Login", "Logistics"]}]})
    page.wait_for_function("document.getElementById('sch-meta')?.textContent === '매일 09:05, 13:30 물류관리'", timeout=10000)
    check(page.is_disabled("#sch-apply"), "PC 가 로그인을 붙여 돌려줘도 같은 값 (바뀜 없음)")
    check("(물류관리)" in page.text_content("#sch-info"), f"다음 실행 글에 그 줄의 모듈 ({page.text_content('#sch-info')})")
    db_patch("meta/companies/c_demo/apps/rpa", {"limits": {"schedule": 3}})   # 업체 한도는 총괄·관리 도구가 쓴다
    reload_to(page, "settings"); page.wait_for_function("document.querySelectorAll('#sch-times select').length === 2", timeout=10000)
    check(page.text_content("#sch-count") == "2/3 사용" and not page.is_disabled("#sch-add"), "한도 3: 2/3 사용, 추가 가능")
    db_patch("meta/companies/c_demo/apps/rpa", {"limits": {"schedule": 1}})
    reload_to(page, "settings"); page.wait_for_function("document.querySelectorAll('#sch-times .t.over').length === 1", timeout=10000)
    page.click("#sch-days button:nth-child(7)")
    check("한도를 넘어 쉬는 중" in page.text_content("#sch-times .t:nth-child(2)") and page.is_disabled("#sch-apply")
          and "1개까지" in page.text_content("#sch-limit"), "한도를 낮추면 넘는 줄은 '쉬는 중', 그 상태로는 적용 안 됨")
    db_patch("meta/companies/c_demo/apps/rpa", {"limits": None})
    reload_to(page, "settings")
    db_patch(f"{LIVE}/schedule", {"slots": None})       # 줄이 0개인 새 판 PC - Realtime DB 에선 빈 목록이 사라진다
    page.wait_for_function("document.getElementById('sch-count')?.textContent === '0/2 사용'", timeout=10000)
    check(page.is_hidden("#sch-old"), "줄이 0개여도 version 2 면 새 판으로 본다 (Review Focus 5)")
    db_patch(f"{LIVE}/schedule", {"slots": [{"at": "09:05"}, {"at": "13:30", "run": ["Login", "Logistics"]}]})
    page.wait_for_function("document.querySelectorAll('#sch-times select').length === 2", timeout=10000)
```
- 그 아래 줄 지우기 두 곳 `page.click("#sch-times .t:nth-child(1) button")` → `page.click("#sch-times .t:nth-child(1) button.del")`.
- 떠날 때 확인 묶음의 `'매일 09:05, 13:30'` → `'매일 09:05, 13:30 물류관리'`.
- 6-2절 머리(`print("6-2절 …")`) 바로 아래:
```python
    check("13:30 · 물류관리" in page.text_content("#hero .stats"), f"상태 띠 다음 자동 실행에 그 줄의 모듈 ({page.text_content('#hero .stats')})")
```

- [ ] **Step 2: 실패 확인** - check_web. 기대: `#sch-old` 없음으로 실패.

- [ ] **Step 3: `firebase/web/rpa-common.js`** 끝에:

```js
// 예약 줄 (2부). 단추 글은 PC 의 rpa_dashboard.SLOT_NAMES 와 같은 말
export const RUN_CHIPS = [["Prepare", "쇼핑몰 받기"], ["Sales", "주문매핑"], ["Hold", "물류대기"], ["Logistics", "물류관리"], ["Output", "운송장"]];
export const RUN_NAMES = dict(RUN_CHIPS);
/** '고르기' 줄의 모듈 이름 (로그인은 늘 붙으니 안 적는다). '전체' 거나 줄이 없으면 "" */
export const slotNames = (slot) => (slot?.run ? slot.run.filter((k) => k !== "Login").map((k) => RUN_NAMES[k] || k).join("·") : "");
/** 줄 한 칸 글: '10:00' / '11:00 물류관리' / '11:00~12:00 반복 물류관리' (PC 의 slot_text 와 같다) */
export const slotText = (s) => (s.until ? `${s.at}~${s.until} 반복` : s.at) + (s.run ? ` ${slotNames(s)}` : "");
```

- [ ] **Step 4: `firebase/web/rpa-settings.js`**
- 가져오기에 `RUN_CHIPS, slotNames, slotText` 를 더하고 `const MAX_TIMES = 2;` 줄을 지운다.
- HTML: 실행 모듈 카드 `<h2>` 아래에 `<div class="msg">전체 실행과 '전체' 예약이 이 모듈을 돌립니다</div>`. 자동 실행 카드의 `sch-form` 안 `<div class="lbl">시간</div>` 부터 끝까지와 카드 아래쪽을:
```html
          <div class="lbl">시간 · <span id="sch-count"></span></div>
          <div class="times" id="sch-times"></div>
          <div class="seg"><button id="sch-add">+ 시각</button></div>
          <div class="msg" id="sch-limit"></div>
        </div>
        <div class="msg" id="sch-old" hidden>이 PC 는 새 판을 깔아야 시각별 모듈·반복을 쓸 수 있습니다</div>
        <div class="msg" id="sch-info"></div>
        <button class="apply" id="sch-apply" disabled>적용</button>
```
- `let form` 의 `sch` 를 `{ enabled: false, days: [], slots: [] }` 로.
- `mount()` 의 `$("sch-add").onclick` 을:
```js
  $("sch-add").onclick = () => { if (form.sch.slots.length >= limitOf()) return; form.sch.slots.push({ at: "09:00", run: null }); paintTimes(); paintScheduleMeta(); };
```
- `// --- 자동 실행` 절 전체(`savedSch` 부터 `applySchedule` 끝까지)를 아래로 바꾼다:

```js
// --- 자동 실행 (2부: 줄마다 전체/고르기, 업체 한도) ----------------------------------------
// 새 판 PC 는 live.schedule.version 2 와 줄(slots)을 올린다. 없으면 옛 판 - 시각만 넣고 옛 모양 {enabled, days, times} 로 보낸다
const isV2 = () => (live?.schedule?.version ?? 0) >= 2;
/** 업체 한도 '자동 실행 개수' (meta/companies/{cid}/apps/rpa/limits/schedule, 없으면 2). 옛 판 PC 는 3개까지밖에 못 받는다 */
function limitOf() {
  const n = c?.policy?.rpa?.limits?.schedule;
  const lim = Number.isInteger(n) && n >= 0 ? n : 2;
  return isV2() ? lim : Math.min(lim, 3);
}
const savedSch = () => live?.schedule || { enabled: false, days: [] };
/** PC 가 올린 줄 → 폼 줄. run 에서 로그인은 뺀다 (늘 붙으니 화면엔 안 보인다). 옛 판은 times 를 '전체' 줄로 */
function savedSlots() {
  const s = savedSch();
  if (!isV2()) return (s.times || []).map((t) => ({ at: t, run: null }));
  return (Array.isArray(s.slots) ? s.slots : []).filter((x) => x && typeof x.at === "string").map((x) => ({
    at: x.at, run: Array.isArray(x.run) ? x.run.filter((k) => k !== "Login") : null,
    ...(x.until ? { until: x.until, rest_min: x.rest_min ?? 2 } : {}),
  }));
}
function resetSchedule() {
  const s = savedSch();
  form.sch = { enabled: !!s.enabled, days: [...(s.days || [])], slots: savedSlots() };
  $("sch-enabled").checked = form.sch.enabled;
  paintDays(); paintTimes(); paintScheduleMeta();
}
const runKey = (run) => (run ? [...run].filter((k) => k !== "Login").sort().join() : "*");
const slotKey = (s) => `${s.at}${s.until ? `~${s.until}/${s.rest_min}` : ""}=${runKey(s.run)}`;
const slotsKey = (slots) => slots.map(slotKey).sort().join("|");
function scheduleDirty() {
  const s = savedSch();
  return form.sch.enabled !== !!s.enabled
    || [...form.sch.days].sort().join() !== [...(s.days || [])].sort().join()
    || slotsKey(form.sch.slots) !== slotsKey(savedSlots());
}
function paintDays() {
  $("sch-days").replaceChildren(...DAYS.map((d, i) => {
    const b = document.createElement("button"); b.textContent = d;
    b.setAttribute("aria-pressed", form.sch.days.includes(i));
    b.onclick = () => {
      form.sch.days = form.sch.days.includes(i) ? form.sch.days.filter((x) => x !== i) : [...form.sch.days, i];
      paintDays(); paintScheduleMeta();
    };
    return b;
  }));
}
const sortedForm = () => [...form.sch.slots].sort((a, b) => a.at.localeCompare(b.at));
function timeInput(value, label, apply) {
  const inp = document.createElement("input"); inp.type = "time"; inp.step = 300; inp.value = value; inp.className = "num";
  inp.setAttribute("aria-label", label);
  inp.onchange = () => { apply(inp.value); paintTimes(); paintScheduleMeta(); };
  return inp;
}
/** 줄의 모듈 단추. 업체가 안 쓰는 모듈은 없다. 운송장은 물류관리를 고르기 전엔 잠김 (실행 모듈 카드와 같은 규칙) */
function runChips(s, withPrepare) {
  const box = document.createElement("span"); box.className = "seg chips";
  for (const [k, text] of RUN_CHIPS) {
    if (k === "Prepare" ? !withPrepare : offByCompany(k)) continue;
    const b = document.createElement("button"); b.type = "button"; b.textContent = text; b.dataset.k = k;
    b.setAttribute("aria-pressed", s.run.includes(k));
    const locked = k === "Output" && !s.run.includes("Logistics");
    b.disabled = !c.isAdmin || busy || locked;
    if (locked) b.title = "물류관리를 켜야 쓸 수 있습니다";
    b.onclick = () => {
      s.run = s.run.includes(k) ? s.run.filter((x) => x !== k) : [...s.run, k];
      if (!s.run.includes("Logistics")) s.run = s.run.filter((x) => x !== "Output");
      paintTimes(); paintScheduleMeta();
    };
    box.append(b);
  }
  return box;
}
function paintTimes() {
  const over = new Set(sortedForm().slice(limitOf()));      // 시각 순으로 한도를 넘는 줄 (PC 도 이 줄은 안 돌린다)
  $("sch-times").replaceChildren(...form.sch.slots.map((s, i) => {
    const row = document.createElement("div"); row.className = "t" + (over.has(s) ? " over" : "");
    row.append(timeInput(s.at, "시각", (v) => { s.at = v; }));
    if (isV2()) {
      const mode = document.createElement("select"); mode.className = "mode"; mode.setAttribute("aria-label", "돌릴 모듈");
      mode.append(new Option("전체", "all"), new Option("고르기", "pick"));
      mode.value = s.run ? "pick" : "all";
      mode.onchange = () => { s.run = mode.value === "pick" ? [] : null; paintTimes(); paintScheduleMeta(); };
      row.append(mode);
      if (s.run) row.append(runChips(s, true));
    }
    const del = document.createElement("button"); del.className = "del"; del.textContent = "빼기";
    del.onclick = () => { form.sch.slots.splice(i, 1); paintTimes(); paintScheduleMeta(); };
    row.append(del);
    if (over.has(s)) row.append(Object.assign(document.createElement("span"), { className: "rest", textContent: "한도를 넘어 쉬는 중" }));
    return row;
  }));
}
/** 적용을 막는 까닭 (없으면 ""). 한도·줄 모양은 꺼도 지킨다 - 에이전트도 줄 수를, PC 도 줄 모양을 본다 */
function scheduleProblem() {
  const lim = limitOf(), slots = form.sch.slots;
  if (slots.length > lim) return lim ? `자동 실행은 ${lim}개까지입니다 - 줄을 줄여야 적용할 수 있습니다` : "자동 실행을 쓰려면 담당자에게 문의하세요";
  if (slots.some((s) => !/^\d\d:\d\d$/.test(s.at))) return "시간을 확인하세요";
  const ats = slots.map((s) => s.at);
  if (new Set(ats).size !== ats.length) return "같은 시각이 두 번 있습니다";
  if (slots.some((s) => s.run && !s.run.length)) return "고르기 줄에 모듈을 하나 이상 고르세요";
  if (!form.sch.enabled) return "";
  if (!form.sch.days.length) return "요일을 하나 이상 고르세요";
  if (!slots.length) return "시간을 하나 이상 넣으세요";
  return "";
}
function paintScheduleMeta() {
  const s = savedSch(), lim = limitOf(), n = form.sch.slots.length;
  const dis = !c.isAdmin || busy;
  $("sch-enabled").disabled = dis;
  for (const el of $("sch-form").querySelectorAll("button, input, select")) if (!el.closest(".chips")) el.disabled = dis;
  $("sch-add").disabled = dis || n >= lim;
  $("sch-count").textContent = `${n}/${lim} 사용`;
  const problem = scheduleProblem();
  const full = n >= lim ? (lim ? `자동 실행은 ${lim}개까지입니다. 더 필요하면 담당자에게 문의하세요` : "자동 실행을 쓰려면 담당자에게 문의하세요") : "";
  $("sch-limit").textContent = problem || full;
  $("sch-limit").className = "msg" + (problem ? " bad" : "");
  $("sch-old").hidden = !live || isV2();
  $("sch-meta").textContent = !live ? "" : s.enabled ? `${labelDays(s.days)} ${savedSlots().map(slotText).join(", ")}` : "꺼짐";
  const info = [];
  if (s.enabled && s.next_run_at) {
    const names = slotNames((Array.isArray(s.slots) ? s.slots : []).find((x) => x && x.at === s.next_slot));
    info.push(`다음 ${when(s.next_run_at)}${names ? ` (${names})` : ""}`);
  }
  if (s.last_launch_at) info.push(`마지막 ${when(s.last_launch_at)}${s.last_launch_by === "auto" ? " (자동)" : ""}`);
  if (s.last_error) info.push(`오류: ${s.last_error}`);
  let cls = s.last_error ? " bad" : "";
  const t = live?.tokens;                                // 예약 실행은 지켜볼 사람이 없다 - 토큰이 모자라면 여기에도 (토큰 2부)
  if (s.enabled && typeof t?.balance === "number") {
    const need = t.cost?.next ?? t.cost?.all ?? 0;       // 다음 줄이 '고르기' 면 그 줄의 토큰 (에이전트가 cost.next)
    if (t.balance <= 0) { info.push("토큰이 없어 예약 실행을 건너뜁니다"); cls = " bad"; }
    else if (t.balance < need) { info.push(`다음 예약 실행에 ${need}개 · 남은 ${t.balance}개 - 마이너스로 떨어질 수 있습니다`); cls = cls || " warn"; }
  }
  $("sch-info").textContent = info.join(" · ");
  $("sch-info").className = "msg" + cls;
  $("sch-apply").disabled = dis || !scheduleDirty() || !!problem;
}
function labelDays(days) {
  const d = [...new Set(days || [])].sort();
  if (d.join() === "0,1,2,3,4,5,6") return "매일";
  if (d.join() === "0,1,2,3,4") return "평일";
  if (d.join() === "5,6") return "주말";
  return d.map((i) => DAYS[i]).join("·") || "요일 없음";
}
/** 보낼 값. 옛 판 PC 는 옛 모양, 새 판은 줄 (로그인은 PC 가 붙인다) */
function payloadOf() {
  const base = { enabled: form.sch.enabled, days: [...new Set(form.sch.days)].sort() };
  if (!isV2()) return { ...base, times: [...new Set(form.sch.slots.map((s) => s.at))].sort() };
  return { ...base, slots: sortedForm().map((s) => ({ at: s.at, ...(s.until ? { until: s.until, rest_min: s.rest_min } : {}), ...(s.run ? { run: [...s.run] } : {}) })) };
}
async function applySchedule() {
  const payload = payloadOf();
  try {
    await set(ref(c.db, `${P("settings", c.me.cid, c.pcId)}/schedule`), payload);
  } catch (e) { notify("bad", e.code === "PERMISSION_DENIED" ? "권한이 없습니다" : `저장하지 못했습니다 (${e.code || e})`); return; }
  await send("set_schedule", payload, "자동 실행");
}
```

- [ ] **Step 5: `firebase/web/rpa.js`** - 가져오기에 `slotNames` 를 더하고, `paintTiles()` 의 `["다음 자동 실행", sch?.enabled && sch.next_run_at ? when(sch.next_run_at) : "꺼짐", ""],` 를 `["다음 자동 실행", nextRunText(sch), ""],` 로, `paintTiles` 위에:
```js
/** 상태 띠 '다음 자동 실행'. 다음 줄이 '고르기' 면 모듈 이름까지 (예: 10월 7일 (화) 11:00 · 물류관리). 옛 판 PC 는 줄이 없어 시각만 */
function nextRunText(sch) {
  if (!(sch?.enabled && sch.next_run_at)) return "꺼짐";
  const names = slotNames((Array.isArray(sch.slots) ? sch.slots : []).find((s) => s && s.at === sch.next_slot));
  return when(sch.next_run_at) + (names ? ` · ${names}` : "");
}
```

- [ ] **Step 6: `firebase/web/index.html`** - Task 1 에서 넣은 환경설정 CSS 아래:
```css
  /* 자동 실행 줄: 시각 · 전체/고르기 · 모듈 단추 · 빼기. 좁으면 다음 줄로 넘어간다. 한도를 넘는 줄은 흐리게 */
  .times .t { flex-wrap:wrap; }
  .times .t select.mode { width:auto; padding:5px 8px; font-size:13px; }
  .times .t .chips { margin-top:0; }
  .times .t .chips button { padding:4px 8px; font-size:12px; }
  .times .t.over { opacity:.6; }
  .times .t .rest { font-size:12px; color:var(--warn); }
```

- [ ] **Step 7: 통과 확인** - check_web. 기대: 실패 0.
- [ ] **Step 8:** `graphify update .` → 커밋은 사용자에게 묻는다.

---

### Task 5: 시간대 반복 - PC 예약기·상태 기록·루틴

**Files:**
- Modify: `rpa_dashboard.py` (`normalize_slots` 반복 줄, `REST_MIN_*`, `open_window`·`last_finished`·`processed`·`stop_reason`·`repeat_state`·`resume_repeat`, `Scheduler.tick`·`check_repeat_result`·`tick_repeat`·`mark_repeat`, `schedule_view` 의 `repeat`)
- Modify: `rpa_status.py` (`start` 의 `trigger`, `history_record`, `finish(record)`, `done_modules`)
- Modify: `run_routine.py` (빈 반복 회차 → `finish(record=False)`)
- Create: `tests/test_schedule_repeat.py`
- Test: `tests/test_routine_modules.py`

**Interfaces:**
- Consumes: Task 2·3 의 줄·`active_slots`·`launch_slot(slot, by, trigger)`·`advance`·`NOW`·`set_policy`
- Produces (`rpa_dashboard`): `REST_MIN_DEFAULT = 2`, `open_window(sch, now) → slot|None`, `last_finished() → datetime|None`, `resume_repeat() → str` (멈춘 반복이 없으면 `RuntimeError("지금은 멈춘 반복이 없습니다")`), `schedule.repeat = {date, at, until, runs, done, stopped: {at, reason}|None, pending: iso|None, last_launch_at, next_at}`
- Produces (`rpa_status`): 상태·이력의 `trigger` (`RPA_RUN_TRIGGER`), `finish(result, reason=None, record=True)`, `done_modules() → list[str]`

- [ ] **Step 1: 실패할 시험 - `tests/test_schedule_repeat.py` (새)**

```python
# -*- coding: utf-8 -*-
"""시간대 반복 시험 (설계 6절). 가짜 시계(rpa_dashboard.NOW) + DRY_RUN + 격리 폴더 - 실제 RPA 는 안 띄운다.
루틴이 도는 것은 상태 파일(status_routine.json)을 직접 써서 흉내 낸다."""
import datetime as dt
import io
import os
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
tmp = tempfile.mkdtemp(prefix="rpa_repeat_")
os.environ["RPA_STATUS_DIR"] = tmp
os.environ["RPA_DASHBOARD_DRY_RUN"] = "1"
os.environ["RPA_OBSERVER_LOCK"] = rf"Local\AFTER_MARKET_RPA_OBSERVER_REPEAT_TEST_{os.getpid()}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rpa_status as st  # noqa: E402
import rpa_dashboard as d  # noqa: E402

fails = []


def check(cond, what):
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        fails.append(what)


CLOCK = [dt.datetime(2026, 9, 14, 10, 58)]          # 2026-09-14 월요일
d.NOW = lambda: CLOCK[0]
PID, CREATED = os.getpid(), st.process_created(os.getpid())


def at(hhmm, day=0, sec=0):
    h, m = map(int, hhmm.split(":"))
    return dt.datetime(2026, 9, 14 + day, h, m, sec)


def iso(t):
    return t.isoformat(timespec="seconds")


def put_status(program, state, started, finished=None, modules=(), reason=None):
    """상태 파일을 흉내 낸다 (running 이면 이 프로세스가 살아 있는 것으로 보인다)."""
    st.write_json_atomic(st.status_path(program), {
        "schema": 2, "run_id": f"{program}_{started:%Y%m%d_%H%M%S}_{PID}", "program": program, "program_label": st.LABELS[program],
        "state": state, "reason": reason, "pid": PID, "pid_created": CREATED, "started_at": iso(started),
        "updated_at": iso(finished or started), "finished_at": iso(finished) if finished else None,
        "steps": [], "metrics": [], "modules": [dict(m) for m in modules], "module_flags": 0, "log_tail": []})


def ended():
    """띄운 프로세스가 끝난 것으로 (DRY_RUN 은 손잡이가 없어 유예 시간을 쓴다)"""
    d._active["until"] = 0
    d._active["proc"] = None


def rep():
    return st.read_settings()["schedule"].get("repeat") or {}


LOGIN = {"key": "login", "label": "로그인", "state": "done"}
NO_TARGET = {"key": "logistics", "label": "물류관리", "state": "no_target"}
DONE = {"key": "logistics", "label": "물류관리", "state": "done"}
WIN = {"at": "11:00", "until": "12:00", "rest_min": 2, "run": ["Logistics"]}
ALL = list(range(7))

print("\n=== 1. 줄 검사 ===")
ok = d.normalize_slots([{"at": "10:00"}, dict(WIN)])
check(ok[1] == {"at": "11:00", "until": "12:00", "rest_min": 2, "on_fail": "stop", "run": ["Login", "Logistics"]},
      f"반복 줄: 쉬는 시간·실패하면 멈춤·로그인 붙음 ({ok[1]})")
check(d.normalize_slots([{"at": "11:00", "until": "12:00", "run": ["Hold"]}])[0]["rest_min"] == 2, "쉬는 시간을 안 주면 2분")
for bad, why in (
        ([{"at": "11:00", "until": "11:00", "run": ["Hold"]}], "늦어야"),
        ([{"at": "11:00", "until": "12:00", "run": ["Hold"], "rest_min": 0}], "1~60"),
        ([{"at": "11:00", "until": "12:00", "run": ["Hold"], "rest_min": 61}], "1~60"),
        ([{"at": "11:00", "until": "12:00", "run": ["Hold"], "on_fail": "retry"}], "멈춤"),
        ([{"at": "11:00", "until": "12:00"}], "전체"),
        ([{"at": "11:00", "until": "12:00", "run": ["Prepare", "Hold"]}], "쇼핑몰 받기"),
        ([dict(WIN), {"at": "11:30", "until": "12:30", "run": ["Hold"]}], "겹칩니다"),
        ([dict(WIN), {"at": "11:30"}], "반복 안에는"),
        ([dict(WIN), {"at": "11:00"}], "반복 안에는"),
        ([{"at": "23:00", "until": "24:00", "run": ["Hold"]}], "23:55")):
    try:
        d.normalize_slots(bad); check(False, f"거부: {why}")
    except ValueError as e:
        check(why in str(e), f"거부: {why} ({e})")
check(len(d.normalize_slots([dict(WIN), {"at": "12:00"}])) == 2, "끝 시각과 같은 시각(12:00)은 된다")

print("\n=== 2. 시간대가 열리면 첫 회차 ===")
d.apply_schedule({"enabled": True, "days": ALL, "slots": [dict(WIN)]})
sched = d.Scheduler()
sched.tick()
check(d.LAUNCHED == [] and st.read_settings()["schedule"]["next_slot"] == "11:00", "10:58: 아직 (다음 실행은 시간대 시작)")
CLOCK[0] = at("11:00")
sched.tick()
check(d.LAUNCHED == ["routine:auto"] and d.LAUNCHED_ENV[-1] == {"RPA_RUN_MODULES": "Login,Logistics", "RPA_RUN_TRIGGER": "repeat"},
      f"11:00: 루틴만 + 그 모듈 + 반복 표시 ({d.LAUNCHED_ENV[-1:]})")
check(rep().get("pending") == iso(at("11:00")) and rep().get("runs") == 0 and rep().get("date") == "2026-09-14", "띄운 회차를 기다리는 중으로 적는다")
put_status("routine", "running", at("11:00", sec=5))
CLOCK[0] = at("11:00", sec=30)
sched.tick()
check(d.LAUNCHED == ["routine:auto"] and "끝나기를" in (sched.waiting_reason or ""), f"띄운 회차가 안 끝났으면 기다린다 ({sched.waiting_reason})")

print("\n=== 3. 성공하면 쉬었다가 다음 회차 ===")
put_status("routine", "success", at("11:00", sec=5), at("11:01"), [LOGIN, NO_TARGET]); ended()
CLOCK[0] = at("11:01", sec=30)
sched.tick()
r = rep()
check(r.get("runs") == 1 and r.get("done") == 0 and r.get("pending") is None and r.get("next_at") == iso(at("11:03")),
      f"대상 없음도 성공 - 회차 1·처리 0, 끝난 시각 + 2분에 다음 ({r})")
check(d.LAUNCHED == ["routine:auto"], "쉬는 동안은 안 띄운다")
CLOCK[0] = at("11:03")
sched.tick()
check(d.LAUNCHED == ["routine:auto"] * 2, "쉬는 시간이 지나면 다음 회차")
put_status("routine", "success", at("11:03", sec=5), at("11:04"), [LOGIN, DONE]); ended()
CLOCK[0] = at("11:05")
sched.tick()
check(rep().get("runs") == 2 and rep().get("done") == 1, f"처리한 회차는 처리 +1 ({rep()})")

print("\n=== 4. 실패하면 그 시간대 반복을 멈춘다 ===")
CLOCK[0] = at("11:06")
sched.tick()
check(len(d.LAUNCHED) == 3, "세 번째 회차")
put_status("routine", "stopped", at("11:06", sec=5), at("11:10"),
           [LOGIN, {"key": "logistics", "label": "물류관리", "state": "failed", "reason": "저장 실패"}], reason="저장 실패"); ended()
CLOCK[0] = at("11:15")
sched.tick()
check((rep().get("stopped") or {}).get("reason") == "11:10 물류관리 실패로 반복을 멈췄습니다: 저장 실패" and len(d.LAUNCHED) == 3,
      f"까닭을 남기고 멈춘다 ({rep().get('stopped')})")
check("멈췄습니다" in (sched.waiting_reason or ""), "예약기도 멈춤으로 안다")

print("\n=== 5. [반복 다시 시작] ===")
CLOCK[0] = at("11:16")
check(d.resume_repeat() == "반복을 다시 시작했습니다 (12:00까지)" and rep().get("stopped") is None, "멈춤을 푼다")
try:
    d.resume_repeat(); check(False, "멈추지 않았는데 다시 시작")
except RuntimeError as e:
    check(str(e) == "지금은 멈춘 반복이 없습니다", "두 번 눌러도 한 번만 (두 번째는 '멈춘 반복이 없습니다')")
sched.tick()
check(len(d.LAUNCHED) == 4, "바로 다음 회차 (11:10 + 2분이 지났다)")

print("\n=== 6. 토큰이 없으면 멈춘다 ===")
put_status("routine", "success", at("11:16", sec=5), at("11:17"), [LOGIN, NO_TARGET]); ended()
d.TOKEN_GATE = lambda target: (_ for _ in ()).throw(RuntimeError("토큰이 없습니다 (남은 0개). 충전한 뒤 실행하세요"))
try:
    CLOCK[0] = at("11:20")
    sched.tick()
    check(len(d.LAUNCHED) == 4 and "토큰이 없습니다" in (rep().get("stopped") or {}).get("reason", ""), f"까닭과 함께 멈춤 ({rep().get('stopped')})")
finally:
    d.TOKEN_GATE = None
d.resume_repeat()

print("\n=== 7. 단추로 누른 실행 - 끝나면 쉬고 이어 가고, 그 실패는 반복을 안 멈춘다 ===")
put_status("prepare", "stopped", at("11:19"), at("11:21"), reason="사이트 실패")
CLOCK[0] = at("11:22")
sched.tick()
check(len(d.LAUNCHED) == 4 and rep().get("stopped") is None, "사람이 띄운 실행이 11:21 에 끝났으면 11:23 까지 쉰다 (실패해도 반복은 그대로)")
CLOCK[0] = at("11:23")
sched.tick()
check(len(d.LAUNCHED) == 5, "11:23 에 다음 회차")

print("\n=== 8. 끝 시각 - 돌던 회차는 끝까지, 새 회차는 없다 ===")
put_status("routine", "running", at("11:23", sec=5))
CLOCK[0] = at("12:00", sec=30)
sched.tick()
check(len(d.LAUNCHED) == 5, "12:00 이 되면 새 회차는 없다")
put_status("routine", "success", at("11:23", sec=5), at("12:02"), [LOGIN, DONE]); ended()
runs = rep().get("runs")
CLOCK[0] = at("12:03")
sched.tick()
check(rep().get("runs") == runs + 1 and len(d.LAUNCHED) == 5, "끝 시각 뒤에 끝난 회차도 센다, 새 회차는 없다")

print("\n=== 9. 다음 날·시간대 중에 예약을 고치면 (Review Focus 2) ===")
CLOCK[0] = at("11:00", day=1)
sched.tick()
check(rep().get("date") == "2026-09-15" and rep().get("runs") == 0 and len(d.LAUNCHED) == 6, "다음 날 같은 시간대: 새 상태로 첫 회차")
put_status("routine", "success", at("11:00", 1, 5), at("11:01", 1), [LOGIN, NO_TARGET]); ended()
CLOCK[0] = at("11:01", 1, 30); sched.tick()
d.apply_schedule({"enabled": True, "days": ALL, "slots": [dict(WIN, rest_min=5)]})
CLOCK[0] = at("11:02", 1); sched.tick()
check(rep().get("runs") == 1 and len(d.LAUNCHED) == 6, "같은 시간대(시작·끝 같음)는 쉬는 시간만 바꾸면 횟수를 이어 가고 바꾼 쉬는 시간(5분)대로 기다린다")
d.apply_schedule({"enabled": True, "days": ALL, "slots": [dict(WIN, until="11:30")]})
CLOCK[0] = at("11:06", 1); sched.tick()
check(rep().get("until") == "11:30" and rep().get("runs") == 0 and len(d.LAUNCHED) == 7, "끝 시각을 바꾸면 새 상태")
put_status("routine", "running", at("11:06", 1, 5))
d.apply_schedule({"enabled": True, "days": ALL, "slots": [{"at": "15:00"}]})
put_status("routine", "success", at("11:06", 1, 5), at("11:08", 1), [LOGIN, NO_TARGET]); ended()
CLOCK[0] = at("11:20", 1); sched.tick()
check(len(d.LAUNCHED) == 7 and rep().get("runs") == 1, "시간대를 지우면 돌던 회차만 끝나고(센다) 새 회차는 없다")

print("\n=== 10. 정책 쓰기가 반복 상태를 지우지 않는다 (Review Focus 3) ===")
d.apply_schedule({"enabled": True, "days": ALL, "slots": [dict(WIN)]})
CLOCK[0] = at("11:00", day=2)
sched.tick()
d.set_policy(3, ["Hold"])
check(rep().get("pending") == iso(at("11:00", day=2)) and st.read_settings()["schedule"]["slots"][0]["until"] == "12:00", "정책을 적어도 줄·반복 상태는 그대로")
put_status("routine", "success", at("11:00", 2, 5), at("11:01", 2), [LOGIN, DONE]); ended()
CLOCK[0] = at("11:02", 2); sched.tick()
check(rep().get("runs") == 1, "그 회차를 그대로 센다")

print("\n=== 11. 자정을 넘겨 끝난 회차 (Review Focus 1) ===")
d.set_policy(5, [])
d.apply_schedule({"enabled": True, "days": ALL, "slots": [{"at": "23:00", "until": "23:55", "rest_min": 2, "run": ["Hold"]}]})
CLOCK[0] = at("23:50", day=3)
sched.tick()
n = len(d.LAUNCHED)
check(rep().get("date") == "2026-09-17" and rep().get("pending"), "23:50 에 띄운 회차")
put_status("routine", "success", at("23:50", 3, 5), at("00:03", 4), [LOGIN, {"key": "hold", "label": "물류대기 관리", "state": "done"}]); ended()
CLOCK[0] = at("00:05", day=4)
sched.tick()
check(rep().get("date") == "2026-09-17" and rep().get("runs") == 1 and rep().get("done") == 1 and len(d.LAUNCHED) == n,
      "어제 시간대에 세고, 오늘은 시간대 밖이라 안 띄운다")

print("\n=== 12. 꺼져 있거나 한도 밖이면 안 돈다 ===")
d.apply_schedule({"enabled": False, "days": ALL, "slots": [dict(WIN)]})
CLOCK[0] = at("11:10", day=5); n = len(d.LAUNCHED); sched.tick()
check(len(d.LAUNCHED) == n, "자동 실행을 끄면 시간대여도 안 돈다")
d.set_policy(1, [])
d.apply_schedule({"enabled": True, "days": ALL, "slots": [{"at": "10:00"}, dict(WIN)]})
sched.tick()
check(len(d.LAUNCHED) == n, "한도 1 이면 시각 순 앞 줄(10:00)만 - 11:00 시간대는 쉰다")

print("\n=== 13. 화면 값·이름표 ===")
d.set_policy(5, [])
sv = d.schedule_view()
check(sv["times"] == ["10:00"] and sv["repeat"] is not None and sv["slots"][1]["until"] == "12:00", "옛 8765 화면엔 시각 줄만, 반복 상태도 싣는다")
label = d.schedule_label(st.read_settings()["schedule"])
check(label == "매일 10:00, 11:00~12:00 반복 물류관리", label)

shutil.rmtree(tmp, ignore_errors=True)
print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
```

- [ ] **Step 2: 실패할 시험 - `tests/test_routine_modules.py`**
- `StatusRec.__getattr__` 안의 `self.calls.append((name,) + a)` → `self.calls.append((name,) + a + ((k,) if k else ()))` (키워드 인수도 남긴다 - 없으면 지금과 같다).
- 2절 끝(`check("last_problem() 이 있다", …)` 아래):
```python
os.environ["RPA_RUN_TRIGGER"] = "repeat"
st.start("routine", [("login", "로그인")])
check("시작할 때 RPA_RUN_TRIGGER 를 trigger 로", st._state["trigger"] == "repeat" and st.history_record(st._state)["trigger"] == "repeat")
os.environ.pop("RPA_RUN_TRIGGER")
hist = os.path.join(_tmp, "history.jsonl")
lines = lambda: len(open(hist, encoding="utf-8").read().splitlines()) if os.path.exists(hist) else 0
n0 = lines()
st.set_modules(MODS); st.module_start("login"); st.module_done("login", "done")
check("done_modules: 완료 모듈 키", st.done_modules() == ["login"])
st.finish("success", record=False)
check("record=False 면 이력에 안 쓴다 (상태 파일은 끝남)", lines() == n0 and st.read_json(st.status_path("routine"))["state"] == "success")
st.start("routine", [("login", "로그인")]); st.finish("success")
check("평소엔 이력에 쓴다 (사람이 띄우면 trigger 없음)", lines() == n0 + 1 and st.read_history()[-1].get("trigger") is None)
```
(`st.read_history()` 가 최신을 끝에 두는지 확인 - 반대면 `[0]`.)
- Task 2 의 11절 아래:
```python
print()
print("=== 12. 반복 회차 - 처리한 게 없으면 기록에 안 남긴다 (RPA_RUN_TRIGGER=repeat) ===")


class DoneRec(StatusRec):
    def __init__(self, done):
        super().__init__()
        self._done = done

    def done_modules(self):
        return self._done


rr.pl.load_routine_modules = lambda keys: ({k: True for k in keys}, [])
rr.run_modules = lambda selected: ("success", None)
os.environ["RPA_RUN_TRIGGER"] = "repeat"
for done, keep, what in ((["login"], False, "로그인만 완료 (대상 없음) → 기록 안 남김"), (["login", "logistics"], True, "처리한 모듈이 있으면 남김")):
    rec = DoneRec(done); rr.status = rec
    rr.main()
    fin = rec.of("finish")[-1]
    check(what, fin == (("success", None) if keep else ("success", None, {"record": False})), str(fin))
rr.run_modules = lambda selected: ("stopped", "물류관리 실패")
rec = DoneRec(["login"]); rr.status = rec; rr.main()
check("실패한 반복 회차는 늘 남긴다", rec.of("finish")[-1] == ("stopped", "물류관리 실패"), str(rec.of("finish")))
os.environ["RPA_RUN_TRIGGER"] = "auto"
rr.run_modules = lambda selected: ("success", None)
rec = DoneRec(["login"]); rr.status = rec; rr.main()
check("정한 시각 실행은 대상 없음이어도 남긴다", rec.of("finish")[-1] == ("success", None), str(rec.of("finish")))
os.environ.pop("RPA_RUN_TRIGGER", None)
```

- [ ] **Step 3: 실패 확인** - 두 시험. 기대: 반복 줄 검사부터 실패, `KeyError: 'trigger'`.

- [ ] **Step 4: `rpa_status.py`**
- `start()` 의 `_state` 에 `"pid_created": …` 다음 줄로: `"trigger": os.environ.get("RPA_RUN_TRIGGER") or None,   # 예약이 띄웠으면 auto / repeat (rpa_dashboard.launch_slot). 사람이 띄우면 None`
- `history_record` 의 `"account": …,` 다음에 `"trigger": state.get("trigger"),`
- `finish` 머리를 `def finish(result, reason=None, record=True):`, docstring 끝에 `record=False 면 이력에 안 남긴다 (처리한 게 없는 반복 회차 - 설계 6-3, 상태 파일은 그대로 쓴다)`, `append_history(history_record(_state))` → `if record:` 아래로.
- `finish` 아래에:
```python
def done_modules():
    """지금 실행에서 '완료' 로 끝난 모듈 키 (반복 회차가 처리한 게 있는지 본다 - 설계 6-3)."""
    with _lock:
        return [m.get("key") for m in ((_state or {}).get("modules") or []) if m.get("state") == "done"]
```

- [ ] **Step 5: `run_routine.py`** - `main()` 의 `result, reason = run_modules(selected)` 다음 `status.finish(result, reason)` 을:
```python
    if os.environ.get("RPA_RUN_TRIGGER") == "repeat" and result == "success" \
            and not [k for k in (status.done_modules() or []) if k != "login"]:
        log("반복 회차 - 처리한 것이 없어 기록에 남기지 않습니다")
        status.finish(result, reason, record=False)
    else:
        status.finish(result, reason)
```

- [ ] **Step 6: `rpa_dashboard.py`**
- `SLOT_NAMES` 아래: `REST_MIN_DEFAULT = 2` 와 `REST_MIN_RANGE = (1, 60)   # 반복 시간대 쉬는 시간 (분)`.
- `normalize_slots` 의 줄마다 부분(`item = {"at": …}` ~ `out.append(item)`)을:
```python
        item = {"at": _check_time(s.get("at"))}
        run = normalize_run(s.get("run"))
        if s.get("until") is not None:                 # 반복 시간대 (설계 6-1)
            item["until"] = _check_time(s.get("until"))
            if item["until"] <= item["at"]:
                raise ValueError(f"반복 끝 시각은 시작({item['at']})보다 늦어야 합니다")
            rest = s.get("rest_min", REST_MIN_DEFAULT)
            if not isinstance(rest, int) or isinstance(rest, bool) or not REST_MIN_RANGE[0] <= rest <= REST_MIN_RANGE[1]:
                raise ValueError("쉬는 시간은 1~60분 정수여야 합니다")
            if s.get("on_fail", "stop") != "stop":
                raise ValueError("실패하면 '멈춤' 만 됩니다")
            if run is None:
                raise ValueError("반복에는 '전체' 를 쓸 수 없습니다 - 모듈을 고르세요")
            if "Prepare" in run:
                raise ValueError("반복에는 쇼핑몰 받기를 넣을 수 없습니다")
            item.update(rest_min=rest, on_fail="stop")
        if run is not None:
            item["run"] = run
        out.append(item)
```
그리고 `out.sort(...)` 바로 뒤, 같은 시각 검사 **앞**에:
```python
    for w in (x for x in out if "until" in x):
        for x in out:
            if x is w:
                continue
            if "until" in x and x["at"] < w["until"] and w["at"] < x["until"]:
                raise ValueError(f"반복 시간대가 겹칩니다: {w['at']}~{w['until']}, {x['at']}~{x['until']}")
            if "until" not in x and w["at"] <= x["at"] < w["until"]:
                raise ValueError(f"{w['at']}~{w['until']} 반복 안에는 시각을 넣을 수 없습니다")
```
- `days_label` 앞에:
```python
def open_window(sch, now):
    """지금 열려 있는 반복 시간대 (그날 요일 + 시작 ≤ 지금 < 끝, 한도 안의 줄). 없으면 None."""
    if not sch.get("enabled") or now.weekday() not in (sch.get("days") or []):
        return None
    hm = now.strftime("%H:%M")
    return next((s for s in active_slots(sch) if s.get("until") and s["at"] <= hm < s["until"]), None)


def last_finished():
    """루틴·프리페어 상태 파일에서 가장 늦게 끝난 시각 (누가 띄웠든). 쉬는 시간은 여기서부터 센다 (설계 6-2)."""
    ends = []
    for program in st.PROGRAMS:
        v = st.read_json(st.status_path(program)) or {}
        t = st.parse_iso(v.get("finished_at")) if v.get("state") != "running" else None
        if t is not None:
            ends.append(t)
    return max(ends) if ends else None


def processed(status):
    """반복 회차가 처리한 게 있나 - 로그인 말고 '완료' 로 끝난 모듈 (대상 없음은 처리가 아니다)."""
    return any(m.get("state") == "done" and m.get("key") != "login" for m in status.get("modules") or [])


def stop_reason(status):
    """멈춘 회차의 까닭 한 줄: '10:23 물류관리 실패로 반복을 멈췄습니다: <사유>'."""
    bad = next((m for m in status.get("modules") or [] if m.get("state") in ("failed", "stopped")), None) or {}
    word = "오류" if status.get("state") == "crashed" else "실패"
    why = status.get("reason") or bad.get("reason") or "까닭 없음"
    return f"{(status.get('finished_at') or '')[11:16]} {bad.get('label') or '루틴'} {word}로 반복을 멈췄습니다: {why}".strip()


def repeat_state(sch, win, now):
    """오늘 열린 시간대 win 의 상태 (sch["repeat"]). 날이 바뀌었거나 다른 시간대면 새로 만든다. (상태, 새로 만들었나)
    지난 시간대에 띄운 회차가 아직 안 끝났으면(pending) 이어서 기다린다."""
    rep = sch.get("repeat")
    key = (now.date().isoformat(), win["at"], win["until"])
    if isinstance(rep, dict) and (rep.get("date"), rep.get("at"), rep.get("until")) == key:
        return rep, False
    rep = {"date": key[0], "at": key[1], "until": key[2], "runs": 0, "done": 0, "stopped": None,
           "pending": rep.get("pending") if isinstance(rep, dict) else None, "last_launch_at": None, "next_at": None}
    sch["repeat"] = rep
    return rep, True


def resume_repeat():
    """[반복 다시 시작] (명령 resume_repeat). 열린 시간대의 멈춤을 풀어 바로 다음 회차. 멈춘 반복이 없으면 RuntimeError."""
    now = NOW()
    with _settings_lock:
        cfg = st.read_settings()
        sch = cfg["schedule"]
        win = open_window(sch, now)
        rep = sch.get("repeat") or {}
        if win is None or not rep.get("stopped") or (rep.get("date"), rep.get("at")) != (now.date().isoformat(), win["at"]):
            raise RuntimeError("지금은 멈춘 반복이 없습니다")
        rep.update(stopped=None, next_at=None)
        st.write_settings(cfg)
    return f"반복을 다시 시작했습니다 ({win['until']}까지)"
```
- `Scheduler.tick` 을 바꾸고 아래 셋을 더한다:
```python
    def tick(self):
        sch = st.read_settings()["schedule"]
        if not sch.get("enabled"):
            self.waiting_reason = None
            return
        now = NOW()
        self.check_repeat_result(now)            # 띄운 반복 회차가 끝났으면 센다 (시간대가 끝났어도)
        next_run = st.parse_iso(sch.get("next_run_at"))
        if next_run is None:
            if not self._advance_now(now)["next_run_at"]:
                self.waiting_reason = "요일·시간 설정이 비어 있습니다"
                return
        elif now >= next_run:
            slot = slot_of(sch)
            if slot is not None and not slot.get("until"):
                self.waiting_reason = self.busy()
                if self.waiting_reason is None:
                    self.launch(slot)
                return
            self._advance_now(now)               # 가리키던 줄이 없어졌거나 반복 시간대 - 다음 줄로 (시간대는 아래 반복이 맡는다)
        win = open_window(st.read_settings()["schedule"], now)
        if win is None:
            self.waiting_reason = None
            return
        self.tick_repeat(win, now)

    def tick_repeat(self, win, now):
        """열린 반복 시간대: 멈췄거나 띄운 회차가 아직이면 기다리고, 쉬는 시간이 지났으면 다음 회차를 띄운다."""
        with _settings_lock:
            cfg = st.read_settings()
            rep, new = repeat_state(cfg["schedule"], win, now)
            if new:
                st.write_settings(cfg)
        if rep.get("stopped"):
            self.waiting_reason = "반복을 멈췄습니다 - [반복 다시 시작] 을 누르면 이어 돕니다"
            return
        if rep.get("pending"):
            self.waiting_reason = "반복 회차가 끝나기를 기다립니다"
            return
        end = last_finished()
        if end is not None and now < end + datetime.timedelta(minutes=win.get("rest_min", REST_MIN_DEFAULT)):
            self.waiting_reason = None
            return
        self.waiting_reason = self.busy()
        if self.waiting_reason is not None:
            return
        stamp = now.isoformat(timespec="seconds")
        try:
            launch_slot(win, trigger="repeat")
        except RuntimeError as e:                # 토큰이 없음·업체가 안 쓰는 모듈만 - 시각 줄처럼 넘기지 않고 멈춘다
            self.mark_repeat(stopped={"at": stamp, "reason": f"{now:%H:%M} {e}"})
            return
        self.mark_repeat(pending=stamp, last_launch_at=stamp)

    def check_repeat_result(self, now):
        """띄운 반복 회차가 끝났으면 센다. 성공 → 회차 +1 (처리했으면 처리 +1), 실패·중단·오류 → 그 시간대 반복 멈춤 + 까닭."""
        since = st.parse_iso((st.read_settings()["schedule"].get("repeat") or {}).get("pending"))
        if since is None or launch_state() is not None:
            return
        v = st.read_json(st.status_path("routine")) or {}
        if v.get("state") == "running":
            return
        started = st.parse_iso(v.get("started_at"))
        with _settings_lock:
            cfg = st.read_settings()
            sch = cfg["schedule"]
            rep = sch.get("repeat")
            if not isinstance(rep, dict) or rep.get("pending") is None:
                return
            rep["pending"] = None
            stamp = now.isoformat(timespec="seconds")
            if started is None or started < since:   # 띄운 회차가 기록도 못 남기고 끝났다 ('시작하지 못함' 이력은 launch_state 가 남긴다)
                rep["stopped"] = {"at": stamp, "reason": f"{now:%H:%M} 반복 회차가 시작하지 못했습니다"}
            elif v.get("state") == "success":
                rep["runs"] = int(rep.get("runs") or 0) + 1
                rep["done"] = int(rep.get("done") or 0) + (1 if processed(v) else 0)
                rest = next((s.get("rest_min", REST_MIN_DEFAULT) for s in active_slots(sch)
                             if s.get("until") and s["at"] == rep.get("at")), REST_MIN_DEFAULT)
                end = st.parse_iso(v.get("finished_at")) or now
                rep["next_at"] = (end + datetime.timedelta(minutes=rest)).isoformat(timespec="seconds")
            else:
                rep["stopped"] = {"at": stamp, "reason": stop_reason(v)}
            st.write_settings(cfg)

    def mark_repeat(self, **fields):
        with _settings_lock:
            cfg = st.read_settings()
            rep = cfg["schedule"].get("repeat")
            if isinstance(rep, dict):
                rep.update(fields)
                st.write_settings(cfg)
```
- `schedule_view` 에 `"repeat": sch.get("repeat"),` 를 `"policy"` 다음에.

- [ ] **Step 7: 통과 확인** - test_schedule_repeat, test_schedule_slots, test_routine_modules, test_dashboard_auth, check_schedule_ui. 기대: 모두 실패 0.
- [ ] **Step 8:** `graphify update .` → 커밋은 사용자에게 묻는다.

---

### Task 6: 에이전트 - 토큰 규칙('완료' 만)·반복 다시 시작 명령·규칙

**Files:**
- Modify: `firebase/agent/agent.py` (`USED_STATES`, `KNOWN_TYPES`, `real_actions`)
- Modify: `firebase/rules/database.rules.json`
- Modify: `docs/superpowers/specs/2026-10-06-tokens-design.md`
- Test: `firebase/tests/test_agent.py`, `firebase/tests/rules.test.js`

**Interfaces:**
- Consumes: Task 5 의 `rpa_dashboard.resume_repeat()`
- Produces: 명령 `resume_repeat` (args 없음) → 결과 글 `반복을 다시 시작했습니다 (HH:MM까지)` / 실패 `지금은 멈춘 반복이 없습니다`

- [ ] **Step 1: 실패할 시험 - `firebase/tests/test_agent.py`**
- 토큰 절 머리·첫 check 를:
```python
print("토큰: 실행 기록 한 건이 쓴 것·쓴 토큰 (2026-10-07 바꿈 - '완료' 만 쓰고 대상 없음·실패·건너뜀·중단은 안 쓴다)")
mods = [{"key": "login", "state": "done"}, {"key": "sales", "state": "done"}, {"key": "hold", "state": "no_target"},
        {"key": "logistics", "state": "failed"}, {"key": "output", "state": "skipped"}]
check(ag.usage({"program": "routine", "modules": mods}) == {"login": 1, "sales": 1},
      "루틴: 완료인 모듈만 (대상 없음·실패·건너뜀은 안 씀 - 반복이 빈 회차로 토큰을 먹지 않게)")
```
- `doc2` 두 check 를 `doc2["used"] == {"login": 1, "sales": 1} and doc2["cost"] == 1` 과 `…{"default": 5, "login": 0})["cost"] == 5` 로, 올리기 시험의 `sent["cost"] == {"integerValue": "2"} and set(sent["used"]["mapValue"]["fields"]) == {"login", "sales", "hold"}` → `{"integerValue": "1"}` 과 `{"login", "sales"}`.
- 4절 `decide` check 들 아래: `check(ag.decide(dict(ok_cmd, type="resume_repeat"), NOW)[0] == "run", "resume_repeat (반복 다시 시작) 은 아는 종류")`
- Task 3 의 5-3절 `with` 블록 안, `finally` 앞에:
```python
        try:
            ag.real_actions()["resume_repeat"](None); check(False, "멈춘 반복이 없는데 다시 시작")
        except RuntimeError as e:
            check(str(e) == "지금은 멈춘 반복이 없습니다", "resume_repeat: 멈춘 반복이 없으면 그 글로 실패")
```
- `firebase/tests/rules.test.js` 의 set_presets 시험 아래:
```js
test("commands: resume_repeat 는 관리자가 만들 수 있다 (반복 다시 시작)", async () => {
  await assertSucceeds(set(ref(asAdminA(), "apps/rpa/commands/ca/pc1/c1"), cmd({ type: "resume_repeat", args: null })));
});
```

- [ ] **Step 2: 실패 확인** - test_agent (`usage` 가 hold 를 셈), `npm test` (resume_repeat 거부).

- [ ] **Step 3: 구현**
- `agent.py`: `USED_STATES = ("done",)     # 토큰을 쓰는 모듈 결과 - '완료' 만 (2026-10-07 사용자: 대상 없음도 안 셈 - 시간대 반복의 빈 회차가 토큰을 먹지 않게). 실패·건너뜀·중단도 안 쓴다`. `KNOWN_TYPES` 끝에 `"resume_repeat"`. `real_actions` 안에:
```python
    def do_resume(args):
        return dash.resume_repeat()          # [반복 다시 시작] - 멈춘 반복이 없으면 RuntimeError (사람에게 보일 글)
```
돌려주는 사전에 `"resume_repeat": do_resume`.
- `database.rules.json` 명령 type 검사에 `|| newData.val() === 'resume_repeat'` (set_presets 다음).
- 토큰 설계서: 상태 줄 끝에 `2026-10-07: '대상 없음' 은 안 뺀다 - 시간대 반복 설계(2026-10-06-settings-schedule-design.md) 6-5.` / 2절 '언제 빠지나' 칸을 `모듈이 돌아서 **완료**했으면 (2026-10-07 바꿈 - 전엔 대상 없음도. 시간대 반복의 빈 회차가 토큰을 먹지 않게). 대상 없음·실패·건너뜀·중단은 안 빠진다` / 4절 `usage` 설명의 `` `done`·`no_target` 인 키 `` → `` `done` 인 키 (2026-10-07 전 기록은 대상 없음도 세어 올라갔다 - 기록은 고치지 않는다) ``.

- [ ] **Step 4: 통과 확인** - test_agent, `npm test`, integration (토큰 기대값은 기록에서 다시 세므로 그대로 통과해야 한다).
- [ ] **Step 5:** `graphify update .` → 커밋은 사용자에게 묻는다.

---

### Task 7: 웹 - 반복 시간대 줄·반복 상태·[반복 다시 시작]

**Files:**
- Modify: `firebase/web/rpa-common.js`, `firebase/web/rpa-settings.js`, `firebase/web/rpa.js`, `firebase/web/index.html`
- Test: `firebase/tests/check_web.py`

**Interfaces:**
- Consumes: Task 4 의 `timeInput`·`runChips`·`scheduleProblem`·`payloadOf`, Task 5 의 `live.schedule.repeat`, Task 6 의 명령 `resume_repeat`
- Produces (`rpa-common.js`): `activeSlots(sch)`, `openWindow(sch, now=new Date())`, `repeatOf(sch, win, now=new Date())`

- [ ] **Step 1: 실패할 시험 - `firebase/tests/check_web.py`**
- `seed_run` 에 인수 `trigger=None` 을 더하고 payload 에 `"trigger": trigger` 를 넣는다.
- 6-2절 끝(실행 단추 모양 시험 뒤, 7절 앞)에:
```python
    print("6-3절 시간대 반복 (3부)")
    db_patch("meta/companies/c_demo/apps/rpa", {"limits": {"schedule": 3}})
    reload_to(page, "settings")
    page.wait_for_function("document.querySelectorAll('#sch-times select').length === 2", timeout=10000)
    page.click("#sch-add-win")
    win = "#sch-times .t:nth-child(3)"
    check(page.locator(f"{win} select").count() == 0 and page.locator(f"{win} .chips button[data-k='Prepare']").count() == 0
          and page.locator(f"{win} .chips button").count() == 4, "반복 줄: 전체/고르기 없음, 쇼핑몰 받기 단추 없음")
    check(page.is_disabled("#sch-apply") and "반복 줄에 모듈을" in page.text_content("#sch-limit"), "모듈을 안 고르면 적용 안 됨")
    page.click(f"{win} .chips button[data-k='Logistics']")

    def set_win(a, b):
        for i, v in ((0, a), (1, b)):
            el = page.query_selector_all(f"{win} input[type=time]")[i]
            el.fill(v); el.dispatch_event("change")

    set_win("13:00", "14:00")
    check("13:00~14:00 반복 안에는 시각을 넣을 수 없습니다" in page.text_content("#sch-limit") and page.is_disabled("#sch-apply"),
          f"시각 줄(13:30)이 반복 안에 있으면 거절 ({page.text_content('#sch-limit')})")
    set_win("10:00", "11:00")
    page.fill(f"{win} input.rest-min", "3"); page.dispatch_event(f"{win} input.rest-min", "change")
    check(not page.is_disabled("#sch-apply"), "겹침이 없으면 적용 가능")
    page.click("#sch-apply"); time.sleep(1.5)
    slots = (db_get(f"{SETTINGS}/schedule") or {}).get("slots")
    check(slots == [{"at": "09:05"}, {"at": "10:00", "until": "11:00", "rest_min": 3, "run": ["Logistics"]}, {"at": "13:30", "run": ["Logistics"]}],
          f"반복 줄 저장 ({slots})")
    key = [k for k, v in (db_get(CMDS) or {}).items() if v.get("type") == "set_schedule"][-1]
    db_patch(f"{CMDS}/{key}", {"state": "done", "result": "자동 실행: 매일 09:05, 10:00~11:00 반복 물류관리, 13:30 물류관리", "started_at": 1, "ended_at": 2})
    db_patch(f"{LIVE}/schedule", {"slots": [{"at": "09:05"}, {"at": "10:00", "until": "11:00", "rest_min": 3, "on_fail": "stop", "run": ["Login", "Logistics"]},
                                            {"at": "13:30", "run": ["Login", "Logistics"]}],
                                  "repeat": {"date": TODAY, "at": "10:00", "until": "11:00", "runs": 24, "done": 2, "stopped": None}})
    page.wait_for_function("(document.getElementById('sch-info')?.textContent || '').includes('오늘 반복 24회')", timeout=10000)
    check("오늘 반복 24회 · 처리 2회" in page.text_content("#sch-info") and page.is_disabled("#sch-apply"),
          "PC 가 돌려준 반복 상태: 오늘 횟수·처리 (on_fail·로그인이 붙어도 바뀜 없음)")
    db_patch(f"{LIVE}/schedule/repeat", {"stopped": {"at": f"{TODAY}T10:23:00", "reason": "10:23 물류관리 실패로 반복을 멈췄습니다: 저장 실패"}})
    page.wait_for_function("(document.getElementById('sch-info')?.textContent || '').includes('멈췄습니다')", timeout=10000)
    check("bad" in page.get_attribute("#sch-info", "class"), "멈췄으면 그 까닭을 빨간 글로")
    db_patch("meta/companies/c_demo/apps/rpa", {"limits": None})
    # RPA 화면: 지금 열린 시간대가 멈췄으면 까닭과 [반복 다시 시작]. 시간대를 지금 시각 둘레로 (23시 뒤면 건너뜀)
    nw = datetime.datetime.now()
    start = nw.replace(minute=nw.minute - nw.minute % 5, second=0, microsecond=0)
    if start.hour < 23:
        w_at, w_until = start.strftime("%H:%M"), (start + datetime.timedelta(minutes=55)).strftime("%H:%M")
        db_patch(f"{LIVE}/schedule", {"enabled": True, "days": list(range(7)),
                                      "slots": [{"at": w_at, "until": w_until, "rest_min": 2, "on_fail": "stop", "run": ["Login", "Logistics"]}],
                                      "repeat": {"date": TODAY, "at": w_at, "until": w_until, "runs": 3, "done": 1, "stopped": None}})
        goto(page, "rpa")
        page.wait_for_function(f"(document.querySelector('#hero .stats')?.textContent || '').includes('반복 중 · {w_until}까지')", timeout=10000)
        check(page.is_hidden("#repeat-resume"), "반복 중: 상태 띠 '반복 중 · 끝 시각까지', 다시 시작 단추는 없다")
        db_patch(f"{LIVE}/schedule/repeat", {"stopped": {"at": f"{TODAY}T{w_at}:00", "reason": f"{w_at} 물류관리 실패로 반복을 멈췄습니다: 저장 실패"}})
        page.wait_for_selector("#repeat-resume:not([hidden])", timeout=10000)
        check("반복 멈춤" in page.text_content("#hero .stats") and "저장 실패" in page.text_content("#repeat-line"),
              "멈췄으면 상태 띠 '반복 멈춤' + 실행 칸에 까닭")
        page.click("#repeat-resume"); time.sleep(1.0)
        check(len(cmds_of("resume_repeat")) == 1, "[반복 다시 시작] → resume_repeat 명령")
        key = [k for k, v in (db_get(CMDS) or {}).items() if v.get("type") == "resume_repeat"][-1]
        db_patch(f"{CMDS}/{key}", {"state": "done", "result": f"반복을 다시 시작했습니다 ({w_until}까지)", "started_at": 1, "ended_at": 2})
        db_patch(f"{LIVE}/schedule/repeat", {"stopped": None})
        page.wait_for_selector("#repeat-resume[hidden]", state="attached", timeout=10000)
        check(True, "멈춤이 풀리면 단추가 사라진다")
    else:
        print("  (23시 뒤라 지금 열린 시간대 화면 시험은 건너뜀)")
        goto(page, "rpa")
    db_patch(f"{LIVE}/schedule", {"slots": [{"at": "09:05"}, {"at": "13:30", "run": ["Login", "Logistics"]}], "repeat": None})
```
- 11절 옵저버 check 다음(로그아웃 앞)에:
```python
    seed_run("r_rep_0908", "routine", "success", "2026-09-08T10:24:00", 40, trigger="repeat")
    page.fill("#hist-date", "2026-09-08"); page.dispatch_event("#hist-date", "change")
    page.wait_for_function("document.getElementById('hist-title')?.textContent === '기록 · 2026-09-08'", timeout=15000)
    page.wait_for_function("(document.getElementById('hist-msg')?.textContent || '').endsWith('건')", timeout=15000)
    check(page.text_content("#hist-rows tr.hist td:nth-child(2)") == "루틴 · 반복", "처리한 반복 회차는 기록 표에 '루틴 · 반복'")
```

- [ ] **Step 2: 실패 확인** - check_web. 기대: `#sch-add-win` 없음.

- [ ] **Step 3: `firebase/web/rpa-common.js`** 끝에:
```js
// 반복 시간대 (3부)
/** 도는 줄 (시각 순, 업체 한도로 자른 것 - PC 의 rpa_dashboard.active_slots 와 같은 규칙) */
export function activeSlots(sch) {
  const all = (Array.isArray(sch?.slots) ? sch.slots : []).filter((s) => s && typeof s.at === "string").sort((a, b) => a.at.localeCompare(b.at));
  const lim = sch?.policy?.limit;
  return Number.isInteger(lim) && lim >= 0 ? all.slice(0, lim) : all;
}
/** 지금 열려 있는 반복 시간대 (그날 요일 + 시작 ≤ 지금 < 끝). 이 브라우저 시각으로 본다 */
export function openWindow(sch, now = new Date()) {
  if (!sch?.enabled || !(sch.days || []).includes((now.getDay() + 6) % 7)) return null;
  const hm = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
  return activeSlots(sch).find((s) => s.until && s.at <= hm && hm < s.until) || null;
}
/** 오늘 그 시간대의 반복 상태 (PC 가 schedule.repeat 에 적는다). 다른 날·다른 시간대 것이면 null */
export function repeatOf(sch, win, now = new Date()) {
  const r = sch?.repeat;
  return r && win && r.date === isoDay(now) && r.at === win.at ? r : null;
}
```

- [ ] **Step 4: `firebase/web/rpa-settings.js`**
- 가져오기에 `isoDay`. HTML 의 `<div class="seg"><button id="sch-add">+ 시각</button></div>` → `<div class="seg"><button id="sch-add">+ 시각</button><button id="sch-add-win" class="hide">+ 반복 시간대</button></div>`.
- `mount()` 의 `sch-add` 줄 아래:
```js
  $("sch-add-win").onclick = () => {
    if (form.sch.slots.length >= limitOf()) return;
    form.sch.slots.push({ at: "10:00", until: "11:00", rest_min: 2, run: [] });
    paintTimes(); paintScheduleMeta();
  };
```
- `paintTimes()` 의 `row.append(timeInput(s.at, …));` 다음 `if (isV2()) {` 를 `if (s.until) { … } else if (isV2()) {` 로, 앞 갈래:
```js
    if (s.until) {                                   // 반복 시간대 줄: 시작 ~ 끝 · 모듈 (쇼핑몰 받기 없음) · 쉬는 시간
      const rest = document.createElement("input");
      Object.assign(rest, { type: "number", min: 1, max: 60, value: s.rest_min, className: "num rest-min" });
      rest.setAttribute("aria-label", "쉬는 시간 (분)");
      rest.onchange = () => { s.rest_min = Number(rest.value); paintScheduleMeta(); };
      row.append(Object.assign(document.createElement("span"), { textContent: "~" }), timeInput(s.until, "끝 시각", (v) => { s.until = v; }),
        Object.assign(document.createElement("span"), { className: "muted", textContent: "반복" }), runChips(s, false),
        rest, Object.assign(document.createElement("span"), { className: "muted", textContent: "분 쉬고" }));
    } else if (isV2()) {
```
- `scheduleProblem()` 의 `if (slots.some((s) => !/^\d\d:\d\d$/.test(s.at))) return "시간을 확인하세요";` 바로 아래(같은 시각 검사 **앞**):
```js
  for (const w of slots.filter((s) => s.until)) {
    if (!/^\d\d:\d\d$/.test(w.until) || w.until <= w.at) return `반복 끝 시각은 시작(${w.at})보다 늦어야 합니다`;
    if (!(Number.isInteger(w.rest_min) && w.rest_min >= 1 && w.rest_min <= 60)) return "쉬는 시간은 1~60분입니다";
    if (!w.run.length) return "반복 줄에 모듈을 하나 이상 고르세요";
    for (const x of slots) {
      if (x === w) continue;
      if (x.until && x.at < w.until && w.at < x.until) return `반복 시간대가 겹칩니다: ${w.at}~${w.until}, ${x.at}~${x.until}`;
      if (!x.until && w.at <= x.at && x.at < w.until) return `${w.at}~${w.until} 반복 안에는 시각을 넣을 수 없습니다`;
    }
  }
```
- `paintScheduleMeta()`: `$("sch-add").disabled = …` 아래 `show($("sch-add-win"), isV2()); $("sch-add-win").disabled = dis || n >= lim;`. `if (s.last_error) info.push(…)` 와 `let cls` 줄 다음에:
```js
  const rep = s.repeat;                                  // 반복 상태 (PC 가 적는다) - 오늘 것만
  if (rep && rep.date === isoDay(new Date())) {
    info.push(`오늘 반복 ${rep.runs || 0}회 · 처리 ${rep.done || 0}회`);
    if (rep.stopped) { info.push(rep.stopped.reason || "반복을 멈췄습니다"); cls = " bad"; }
  }
```

- [ ] **Step 5: `firebase/web/rpa.js`**
- 가져오기에 `openWindow, repeatOf`.
- HTML `act-card` 의 `<div class="msg" id="token-line" hidden></div>` 아래:
```html
          <div class="msg bad" id="repeat-line" hidden></div>
          <button class="apply" id="repeat-resume" hidden>반복 다시 시작</button>
```
- `mount()`: 실행 단추 줄들 아래 `$("repeat-resume").onclick = () => send("resume_repeat", null, "반복 다시 시작");`, `tick = setInterval(…)` 안을 `{ paintHero(); paintTiles(); paintRepeat(); }` 로 (시간대가 열리고 닫히는 것은 시각이 정한다).
- `paintButtons()` 끝 `paintTokens();` → `paintTokens(); paintRepeat();`
- `nextRunText` 를:
```js
/** 상태 띠 '다음 자동 실행'. 열린 반복 시간대면 '반복 중 · 12:00까지' (다음 회차) / '반복 멈춤'.
 *  아니면 다음 줄 - '고르기' 면 모듈 이름까지 (예: 10월 7일 (화) 11:00 · 물류관리). 옛 판 PC 는 줄이 없어 시각만 */
function nextRunText(sch) {
  const win = openWindow(sch), rep = repeatOf(sch, win);
  if (win) {
    if (rep?.stopped) return "반복 멈춤";
    const soon = rep?.next_at && Date.parse(rep.next_at) > Date.now() ? ` · 다음 ${hhmm(rep.next_at)}` : "";
    return `반복 중 · ${win.until}까지${soon}`;
  }
  if (!(sch?.enabled && sch.next_run_at)) return "꺼짐";
  const slot = (Array.isArray(sch.slots) ? sch.slots : []).find((s) => s && s.at === sch.next_slot);
  const names = slotNames(slot);
  return when(sch.next_run_at) + (slot?.until ? " 반복" : "") + (names ? ` · ${names}` : "");
}
```
- `paintTokens` 아래:
```js
// --- 반복 (3부): 지금 열린 시간대가 멈췄으면 까닭과 [반복 다시 시작] (관리자만) ------------------------------
function paintRepeat() {
  const sch = live?.schedule, rep = repeatOf(sch, openWindow(sch));
  const stopped = !!rep?.stopped;
  $("repeat-line").hidden = !stopped;
  $("repeat-line").textContent = stopped ? `반복 멈춤: ${rep.stopped.reason || ""}`.trim() : "";
  $("repeat-resume").hidden = !stopped || !c.isAdmin;
  $("repeat-resume").disabled = busy || !c.pcId;
}
```
- `histRow` 의 `const prog = …;` 를 `const prog = (PROGRAM_SHORT[r.program] || r.program_label || r.program || "") + (payload.trigger === "repeat" ? " · 반복" : "");   // 처리한 반복 회차 (빈 회차는 기록에 없다)` 로.

- [ ] **Step 6: `firebase/web/index.html`** - Task 4 CSS 아래: `.times .t input.rest-min { width:64px; }`
- [ ] **Step 7: 통과 확인** - check_web. 기대: 실패 0.
- [ ] **Step 8:** `graphify update .` → 커밋은 사용자에게 묻는다.

---

### Task 8: 문서·전체 시험

**Files:**
- Modify: `docs/firebase-architecture.md`, `docs/superpowers/specs/2026-10-06-settings-schedule-design.md` (상태 줄)

- [ ] **Step 1: `docs/firebase-architecture.md`**
- 2절 파일 지도 `rpa.js` 줄을 `rpa.js             RPA 앱 화면 (현황/기록 탭, 실행 단추·이번 달 사용량·반복 다시 시작)` 로, 그 아래 `rpa-settings.js    RPA 의 환경설정 (실행 모듈·쇼핑몰 프리셋·자동 실행 - 관리 > 환경설정 이 붙인다)`, `rpa-common.js      RPA 화면 둘이 같이 쓰는 것 (경로·모듈 표·명령 보내기)`, `settings.js        관리 > 환경설정 껍데기 (앱마다 설정 화면, 관리자만)` 세 줄.
- 3절 데이터 경로: `meta/companies/{cid}` 줄 아래 `meta/companies/{cid}/apps/rpa/limits/schedule   자동 실행 개수 (0~12, 없으면 2) - 총괄·관리 도구만`. `apps/rpa/settings` 줄의 schedule 을 `schedule {enabled, days, slots: [{at, run?, until?, rest_min?}]}` 로. live.schedule 설명에 `version 2·slots·next_slot·policy{limit, off}·repeat{date, at, until, runs, done, stopped, pending, next_at}` 를 적는다. 명령 종류 문장을 여섯으로 (`resume_repeat` = 반복 다시 시작).
- 5절 에이전트: `- 업체 정책(자동 실행 개수·안 쓰는 모듈)을 10분마다 읽어 settings.json schedule.policy 에 적는다 - 예약기가 줄을 자르고 모듈을 뺀다.` / `- 예약 줄의 모듈은 띄울 때 RPA_RUN_MODULES, 띄운 까닭은 RPA_RUN_TRIGGER(auto·repeat). 반복 시간대는 예약기가 회차마다 루틴을 새로 띄우고, 처리한 게 없는 반복 회차는 이력에 안 남긴다.`
- 8절 시험 명령에 `.venv\Scripts\python.exe tests\test_schedule_repeat.py  # 시간대 반복 (가짜 시계)` 줄. 시험 표: 자동 실행 줄을 '줄마다 모듈·한도·옛 모양 바꾸기' 로 넓히고 `시간대 반복` 줄을 더하고, 화면·에이전트·관리 도구·관리 화면·규칙 건수를 이번 실행 값으로 고친다.
- [ ] **Step 2:** 설계서 상태 줄을 `2026-10-07 구현 (계획 docs/superpowers/plans/2026-10-07-settings-schedule.md)` 로.
- [ ] **Step 3: 전체 시험** - 시험 명령 표 전부 + `tests\test_settings.py`·`tests\test_background.py`·`tests\test_dashboard_modules.py`·`tests\check_modules_ui.py`·`tests\test_encoding.py`·`tests\test_start_failure.py`. 실패가 있으면 이름과 출력을 그대로 보고한다 (`test_settings` #104 는 관리자 셸에서만 나는 알려진 환경 문제).
- [ ] **Step 4:** `graphify update .` → 커밋은 사용자에게 묻는다.

---

### Task 9: 끝 검토·배포·새 판·실기 (하나씩 사용자 확인 뒤)

- [ ] **Step 1: 끝 검토** - 가장 강한 모델의 검토자 한 명이 브랜치 전체(이번 커밋들)를 설계서·계획서와 대조. Critical·Important 는 TDD 로 고친다.
- [ ] **Step 2: 사용자에게 묻고 배포** - `cd D:\AX\RPA\firebase; firebase deploy --only "hosting,database" --config firebase.json --project rpa-test-f02e0` (화면 + 명령 종류 규칙). 옛 판 PC 는 웹이 옛 모양으로 보내므로 먼저 배포해도 된다.
- [ ] **Step 3: 사용자에게 묻고 새 판** - `.venv\Scripts\python.exe tools\build_release.py` → `tools\sandbox_test.py D:\AX\AFTER_MARKET_RPA_Setup_<판>.exe` → 옛 판 정리는 사용자 지시대로.
- [ ] **Step 4: 사용자에게 묻고 실기** - 떠 있는 ERPia 에서 '물류관리만' 을 연달아 두 번 (물류 관리 화면이 열린 채 다시 들어가기). 실제 자료가 저장되므로 어느 PC 에서 할지 사용자가 정한다. 결과를 메모(`next-steps`)에 남긴다.
