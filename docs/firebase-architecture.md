# ERPia RPA 대시보드를 Firebase 로 옮기는 구조 (구상, 2026-09-19)

**목적 (사용자):** 여러 회사에 서비스로 제공하고, PC 를 꺼도 이력을 볼 수 있어야 한다.
**전제:** ERPia 자동화(pywinauto)는 각 회사의 PC 에서만 돈다. Firebase 는 그 PC 의 손을 대신하지 못한다.
**결론 한 줄:** *Firebase 는 "화면 + 저장소 + 로그인" 을 맡고, 각 PC 에는 작은 에이전트가 남아 "실행·종료·설정 파일 쓰기" 를 맡는다.*

---

## 1. 전체 그림

```
   회사 A PC                                Firebase (구글)                     사용자 (어디서든)
 ┌──────────────────────┐              ┌────────────────────────┐          ┌──────────────────┐
 │ ERPia_RPA.exe         │  상태/이력   │ Realtime DB            │  실시간   │ 브라우저          │
 │ Prepare_RPA.exe       │ ──────────▶ │   live/{회사}/{pc}      │ ◀──────▶ │  (Hosting 의      │
 │        │ 상태 파일      │             │   commands/{회사}/{pc}  │          │   dashboard.html) │
 │        ▼              │  명령 구독   │ Firestore              │  조회    │                  │
 │ 에이전트 (파이썬, exe) │ ◀────────── │   companies/{회사}/runs │ ◀─────── │  Firebase Auth   │
 │   · 상태 → 클라우드     │             │   companies/{회사}/users│          │  (구글/이메일)    │
 │   · 명령 → 로컬 실행    │             │ Hosting  (정적 화면)    │          └──────────────────┘
 │   · ERPIA_AI.txt 쓰기  │             └────────────────────────┘
 └──────────────────────┘
   회사 B PC  (같은 에이전트, 다른 회사 키) ──▶  같은 프로젝트, 다른 경로
```

- **에이전트** = 지금 `rpa_dashboard.py` 에서 "PC 에서만 할 수 있는 일" 만 떼어낸 것: `launch()`(Run_All.bat / exe 실행), ERPia 종료, `write_routine_modules()`(ERPIA_AI.txt), 자동 예약. 여기에 "상태 파일을 클라우드로 올리기" 와 "명령 문서 구독" 이 붙는다.
- **화면** = 지금 `dashboard.html` 의 데이터 층(`fetch("/api/...")`)만 Firebase SDK 로 바꾼다. 카드·단계·모듈·이력 화면 코드는 대부분 그대로.
- **ERPIA_AI.txt (ERPia 비밀번호) 는 PC 밖으로 나가지 않는다.** 클라우드에는 모듈 켬/끔 값만 오간다.

## 2. 왜 DB 를 둘로 나누나 (Realtime DB + Firestore)

| | Realtime Database | Firestore |
|---|---|---|
| 모양 | JSON 트리 하나 | 문서/컬렉션 (쿼리 가능) |
| 실시간 스트리밍 | **HTTP SSE 로 표준 라이브러리만으로 구독 가능** (에이전트가 pywinauto 처럼 무거운 SDK 없이 붙는다) | 파이썬 클라이언트는 구글 계정(서비스 계정) 전제 - 고객 PC 에 두기 싫다 |
| 과금 | 전송량 기준 (2초 폴링 같은 게 없다) | 읽기 1건당 과금 (5초 폴링 × PC 수 = 무료 한도 금방 넘음) |
| 이력 조회 | 키 순서 정도만 | 회사·기간·프로그램·결과로 필터 |

→ **살아 있는 것(현재 상태, 명령)은 Realtime DB, 쌓이는 것(실행 이력)은 Firestore.**
처음엔 Realtime DB 하나로 시작해도 된다(이력도 `runs/{회사}/{run_id}` 로 넣고 날짜 키로 자르면 이 규모엔 충분). 회사가 늘어 조회가 복잡해지면 그때 Firestore 로 이력을 옮긴다. 단계별로 가는 걸 권한다.

## 3. 데이터 모양

### Realtime DB (실시간)
```
live/{companyId}/{pcId}/
    prepare : { ...status_prepare.json 그대로... , updated_at }
    routine : { ...status_routine.json 그대로 (modules, module_flags, steps, metrics, log_tail 80줄) }
    heartbeat : { at, agent_version, erpia_running, rpa_running }      ← 30초마다
commands/{companyId}/{pcId}/{cmdId}/
    { type: "run"|"stop_erpia"|"set_modules", args, by: uid, created_at, expires_at, state: "pending"|"done"|"failed"|"expired", result }
settings/{companyId}/{pcId}/
    modules  : { Login: true, Sales: false, ... }     ← 화면이 쓰고 에이전트가 ERPIA_AI.txt 에 반영
    schedule : { enabled, days, times }
```
### Firestore (이력)
```
companies/{companyId}                       { name, plan, created_at }
companies/{companyId}/pcs/{pcId}            { label, hostname, last_seen }
companies/{companyId}/runs/{run_id}         history_record 그대로 (schema 2: steps, metrics, modules, module_flags, log_tail)
companies/{companyId}/users/{uid}           { role: "admin"|"viewer", email }
```
지금 `rpa_status.history_record()` 가 만드는 JSON 이 그대로 문서가 된다. 바꿀 것이 없다.

## 4. 로그인과 권한 (여러 회사)

- **사용자**: Firebase Auth (구글 로그인 권장 - 비밀번호 관리가 없어진다). 가입 뒤 관리자(우리)가 `companies/{c}/users/{uid}` 에 역할을 넣고 **custom claim** `{ companyId, role }` 을 심는다(우리 PC 에서 도는 작은 관리 스크립트 - Admin SDK, 서비스 계정은 우리 손에만).
- **에이전트**: PC 마다 **기계 계정**(이메일/비밀번호) 하나 + claim `{ companyId, pcId, role: "agent" }`. 에이전트는 Firebase Auth REST 로 로그인해 ID 토큰을 받고, Realtime DB/Firestore REST 를 `?auth=토큰` / `Authorization: Bearer` 로 부른다. **고객 PC 에 서비스 계정 키를 두지 않는다** (서비스 계정은 규칙을 우회하는 만능 키라 유출되면 전 회사 데이터가 열린다).
- **보안 규칙**이 회사 경계를 강제한다:
  ```
  live/{c}/{pc}     읽기: token.companyId == c || token.role == "super"
                    쓰기: token.role == "agent" && token.companyId == c && token.pcId == pc
  commands/{c}/{pc} 쓰기(생성): token.companyId == c && token.role == "admin"
                    갱신(state/result): agent 만
  settings/{c}/{pc} 쓰기: admin,  읽기: 그 회사
  runs               읽기: 그 회사,  쓰기: agent 만
  ```
- 우리(컨설턴트)는 `role: "super"` 로 전 회사를 본다.

## 5. 에이전트 (PC 쪽)

- 파이썬, **표준 라이브러리 + `urllib`** 만으로 REST/SSE 를 쓴다 → 지금처럼 PyInstaller 로 작은 exe. pywinauto 는 필요 없다(실행은 exe 를 띄우는 것뿐).
- 하는 일
  1. `rpa_status` 의 상태 파일이 바뀌면(지금은 0.5초 묶음 쓰기) `live/...` 에 PUT. 로그 꼬리는 80줄로 자른다(전송량).
  2. 30초 heartbeat. 화면은 heartbeat 가 2분 넘게 없으면 "PC 연결 끊김" 으로 표시 - PC 를 꺼도 이력은 Firestore 에 남아 있다.
  3. `commands/.../` 를 SSE 로 구독. `run` → 지금의 `launch()` 그대로(잠금·중복 방지 포함). `set_modules` → `write_routine_modules()` 로 ERPIA_AI.txt 에 반영. **`expires_at` 이 지난 명령은 실행하지 않고 expired 로 닫는다** (PC 가 꺼져 있던 동안 쌓인 "실행" 이 켜자마자 우르르 도는 사고 방지).
  4. 실행이 끝나면 `history_record` 를 Firestore `runs/` 에 올린다. (지금의 `append_history` 옆에 한 줄)
  5. 자동 예약: PC 에서 그대로 돈다(`settings/.../schedule` 을 구독해 갱신).
- 지금 코드에서 옮겨 오는 것: `launch/launch_state/any_rpa_running`, `stop ERPia`, `apply_routine_modules`, `Scheduler`. 지금 코드에서 버리는 것: HTTP 서버, 세션/비밀번호 해시, 방화벽 규칙.

## 6. 화면 (Hosting)

- `dashboard.html` 을 그대로 두고 데이터 층만 교체: `pollStatus()` → RTDB `onValue(live/{c}/{pc})`, `/api/history` → Firestore 쿼리, 실행 버튼 → `commands` 에 문서 추가, 실행 모듈 스위치 → `settings/.../modules` 쓰기.
- 회사 선택(super), PC 선택(회사에 PC 가 둘 이상일 때) 이 위에 붙는다.
- 화면의 Firebase 설정값(apiKey 등)은 공개돼도 된다 - 보안은 규칙이 한다. 대신 **규칙을 잘못 쓰면 전부 열린다**는 뜻이므로 규칙 시험(에뮬레이터)을 둔다.

## 7. 지금 코드에서 이어지는 것 / 바뀌는 것

| 지금 | Firebase 뒤 |
|---|---|
| `rpa_status.py` (상태 파일 기록) | 그대로. 에이전트가 이 파일을 읽어 올린다 (RPA 코드는 손대지 않는다) |
| `rpa_dashboard.py` | 사라진다. PC 쪽 동작만 에이전트로 이사 |
| `dashboard.html` | 데이터 층 교체, 나머지 유지 |
| `ERPIA_AI.txt` | PC 에 그대로. 모듈 값만 클라우드에서 내려와 에이전트가 쓴다 |
| 이력 `history.jsonl` | PC 에도 남기고 Firestore 에도 올린다 (이중) |

## 8. 비용·운영

- 무료 등급(Spark)으로 시작 가능: Hosting, Auth, RTDB(1GB 저장/10GB 월 전송/동시 100 연결), Firestore(1GiB, 읽기 5만/일). PC 5대 × 하루 몇 번 실행 규모면 여유.
- Cloud Functions 는 카드 등록(Blaze) 필요 - 위 구조에선 **필요 없다** (claim 심기는 우리 PC 의 관리 스크립트로).
- 회사 EDR(SentinelOne)은 outbound HTTPS 를 막지 않는다. 에이전트 exe 가 지워지는 문제는 대시보드 exe 와 같을 수 있다 → 소스+파이썬 폴더로 배포하는 지금 방식 유지.
- 리전: 서울(asia-northeast3)에 Firestore/RTDB 를 만든다.

## 9. 위험과 결정 필요

1. **회사 데이터가 구글 클라우드에 올라간다.** 주문 건수·상품코드가 든 로그·중단 사유. 고객사 정책 확인이 먼저. 올릴 필드를 줄일 수는 있다(로그 꼬리 제외 등).
2. **명령 만료 시간** (기본 10분 제안) - 짧으면 PC 가 잠깐 끊겼을 때 실행이 누락되고, 길면 예상 밖 시각에 돈다.
3. **기계 계정 비밀번호가 고객 PC 에 파일로 남는다** (ERPia 비밀번호와 같은 성격). DPAPI 로 암호화해 두고, 유출 시 그 PC 계정만 폐기하면 되게 PC 마다 계정을 따로 둔다.
4. RTDB 하나로 시작할지, 처음부터 Firestore 를 이력에 쓸지 - 회사 2곳 이하면 RTDB 하나 권장.

## 10. 순서 (제안)

1. **1주:** Firebase 프로젝트 + Auth + RTDB 규칙. 에이전트 최소판(상태 올리기 + heartbeat). 화면은 현황 카드만 RTDB 로 바꿔 사내 PC 한 대로 확인.
2. **2주:** 명령(실행/ERPia 종료/모듈 설정) + 만료 + 잠금. 이력 올리기 + 이력 화면.
3. **3주:** 회사/PC 선택, super 역할, 두 번째 회사 붙여 보기. 규칙 시험.
4. 그 뒤: Firestore 이력 이전(필요해지면), 알림(실패 시 이메일/푸시 - 여기서만 Functions 가 필요해질 수 있음).
