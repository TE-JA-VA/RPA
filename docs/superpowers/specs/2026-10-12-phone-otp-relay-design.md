# 휴대폰 인증번호 중계 (OTP 릴레이) - 설계

**상태:** 2026-10-12 설계 초안 (사용자와 문답으로 방향만 정함). 이 문서를 받은 전담 세션이 0절 확인 → 3절 순서로 만든다.
**작업 자리 (2026-10-13 바꿈):**
- **이 저장소 (윈도우 PC):** 서버 규칙 `firebase/rules`, 약속 시험 `firebase/tests/check_phone_relay.py` (휴대폰 흉내), RPA 쪽 `web_runner.py` (2단계).
- **새 저장소 (맥에서):** 휴대폰 쪽 - 아이폰 단축어 안내서(3단계), 안드로이드 앱(4단계). 12절.

---

## 0. 왜 하나

쇼핑몰 로그인에 **문자 2차인증**이 붙는다. 지금은 `web_runner.action_sms_2fa` 가 **Phone Link**(PC와 연결) 창을 UIA 로 읽어 인증번호를 얻는다 (`sms_watch.PhoneLinkReader`).

그런데 **PC 한 대가 여러 사이트에 로그인하고, 사이트마다 인증 문자를 받는 휴대폰이 다르다** (직원 개인 휴대폰 여러 대). Phone Link 는 PC 한 대에 휴대폰 한 대만 붙는다 → 이 길로는 안 된다.

그래서 **각 휴대폰이 인증번호를 서버로 보내고, RPA 가 서버에서 받아 쓰는** 중계를 만든다.

## 1. 정한 것 (사용자 2026-10-12)

| 항목 | 결정 |
|---|---|
| 휴대폰 기종 | **섞여 있음/모름** → 안드로이드 앱 + 아이폰 단축어 **둘 다**. 서버 약속은 하나 |
| 휴대폰 주인 | **직원 개인 휴대폰** → 개인 문자가 새지 않는 것이 최우선 (4절) |
| 작업 위치 | 이 저장소 (규칙·약속 시험·RPA) + 휴대폰 쪽 새 저장소 (**맥에서**, 12절) |
| 서버 | 기존 Firebase 프로젝트 `rpa-test-f02e0` 의 Realtime Database (`apps/otp/…`) - 새 서버·새 요금제 없음 |
| 대기 시간 | 요청 하나는 **2분** 열려 있다 (사용자 원안 "2분 동안 오는 문자") |

### 사용자 원안과 달라진 점 (꼭 사용자에게 다시 설명할 것)

사용자 원안: *휴대폰이 20초~1분마다 서버에 묻고, 자기 차례면 STAND BY → 2분 동안 문자를 기다려 보낸다.*

이 설계: **휴대폰은 묻지 않는다(폴링 없음). 문자가 오는 순간 "지금 나에게 열린 요청이 있나" 를 한 번 보고, 있으면 보낸다.**

- 까닭 1 - 아이폰은 앱이 문자를 못 읽는다. 단축어는 "문자가 왔을 때" 에만 돈다. 폴링 자체가 불가능하다.
- 까닭 2 - 안드로이드는 화면이 꺼지면 절전(Doze)이 20초 폴링을 재운다. 막으려면 상시 알림 + 배터리 예외가 필요하고 배터리를 먹는다. 개인 휴대폰에 그걸 깔게 하기 어렵다.
- 까닭 3 - 폴링이면 최대 1분 늦게 STAND BY 가 된다. 그사이 온 문자는 놓친다.
- **STAND BY 의 뜻은 남긴다:** "그 휴대폰에 2분짜리 요청이 열려 있음" = STAND BY. 대시보드에 보인다 (3절 5단계). 휴대폰은 STAND BY 일 때만 보내고, 서버 규칙도 STAND BY 가 아니면 받지 않는다 (2중).

## 2. 한눈에

```
 RPA (PC, web_runner)                  Firebase RTDB                         휴대폰 (직원)
 ─────────────────────                 ─────────────                         ────────────
 ① 요청 열기 ───────────────▶  apps/otp/requests/{cid}/{phoneId}/current
    { req_id, site, senders, created_at=서버시각 }  (열림 = created_at + 120초)
 ② 사이트의 [인증번호 받기] 클릭
                                                                       ③ 문자 도착 (OS 가 앱/단축어를 깨움)
                                                                          - '인증번호' 낱말 + 숫자 뽑기
                                         ◀──────────── ④ current 읽기 (열렸나? 발신번호 맞나?)
                                         ◀──────────── ⑤ 맞으면 번호만 쓰기
                               apps/otp/codes/{cid}/{phoneId}/current
                                  { req_id, code, sender, sms_at }
 ⑥ 2초마다 codes 확인 ◀────────
 ⑦ 받으면 입력 → 요청·번호 지우기
```

- 휴대폰이 서버로 보내는 것: **인증번호 숫자, 발신번호, 받은 시각, 자기 phoneId** 뿐. **문자 본문은 절대 안 보낸다.**
- 휴대폰 한 대에 열린 요청은 **하나**(`current`). 같은 휴대폰을 두 PC 가 동시에 쓰려 하면 뒤에 온 쪽이 기다린다.

## 3. 만드는 순서 (단계마다 사용자 확인)

| 단계 | 내용 | 실제 휴대폰 필요 |
|---|---|---|
| 1 | 서버 약속 + RTDB 규칙 + 에뮬레이터 시험 (가짜 휴대폰 = 파이썬 스크립트) | 아니오 |
| 2 | RPA 쪽: `action_sms_2fa` 가 사이트 설정에 휴대폰이 있으면 중계로 받기 | 아니오 (가짜 휴대폰) |
| 3 | 아이폰 단축어 - 만드는 안내서 + 사용자와 실기 | 예 (아이폰) |
| 4 | 안드로이드 앱 (Kotlin, 최소) + APK + 실기 | 예 (안드로이드) |
| 5 | 관리 화면: 휴대폰 등록(계정 발급) / 업체 대시보드: 휴대폰 목록·STAND BY 표시 | 아니오 |

1·2 를 먼저 끝내면 휴대폰 없이 끝에서 끝까지 시험이 된다. 3·4 는 서로 무관하니 사용자가 가진 휴대폰 쪽부터.

**3·4단계는 맥에서 한다** (2026-10-13 사용자 결정 - 휴대폰 쪽 새 저장소, 12절). 1·2·5단계는 이 저장소(윈도우 PC).

> 골드디스크 1차 목표(2026-10-14 수, 옵저버→대시보드→루틴 실제 테스트런)가 진행 중이다. 그쪽 파일을 건드리는 2단계는 **사용자가 정한 때에** 한다. 1단계는 `firebase/rules`·`firebase/tests` 만, 3·4단계는 맥의 새 저장소라 겹치지 않는다.

## 4. 개인 휴대폰 보호 (가장 중요)

1. **본문 안 보냄.** 휴대폰에서 숫자만 뽑아 보낸다. 뽑는 규칙은 `sms_watch.extract_auth_code` 와 같게 ('인증번호' 낱말 주변만, 전화번호·금액 오인 방지). 안드로이드는 Kotlin 으로 옮기고 같은 시험 문장으로 맞춘다.
2. **열린 요청이 있을 때만.** 요청이 없거나 2분이 지났으면 휴대폰은 아무것도 안 보낸다. 서버 규칙도 거절한다.
3. **발신번호 일치 필수.** 요청에 `senders`(그 사이트가 인증 문자를 보내는 번호 목록)가 들어 있고, 휴대폰은 발신번호가 그 안에 있을 때만 보낸다. 은행·카드 인증번호가 열린 2분 안에 와도 새지 않게. **사이트 설정에 발신번호가 없으면 RPA 가 요청을 열지 않고 멈춘다** (번호를 모르면 처음 한 번은 사람이 확인해 넣는다).
4. **휴대폰 계정은 자기 것만.** phone 계정은 자기 `{cid}/{phoneId}` 의 요청 읽기 + 번호 쓰기만 된다. 다른 휴대폰·다른 업체·RPA 기록은 못 본다.
5. **쓰고 나면 지운다.** RPA 가 번호를 받으면 요청·번호를 지운다. 로그에는 번호를 가린다 (`web_runner.mask_digits` 처럼).
6. 직원에게 줄 **한 장짜리 안내**(무엇이 언제 서버로 가는지)를 3·4단계 끝에 만든다.

## 5. 서버 약속 (RTDB `apps/otp/…`)

```
apps/otp/
  requests/{cid}/{phoneId}/current   RPA(에이전트 계정)가 쓰고 지움
    req_id      string   (RPA 가 만든 무작위 값)
    site        string   (화면 표시용 사이트 이름)
    senders     { "15881234": true, … }  (숫자만, 하이픈 없이. 목록이 아니라 맵 - 규칙이 발신번호를 직접 찾는다)
    pcId        string   (= 자기 PC, 규칙)
    created_at  number   = 서버 시각 (규칙: == now). 열림 = created_at + 120000 > now
                (expires_at 칸은 없앴다 - 서버 시각 + 120초를 쓰는 방법이 REST 에 없다. 2026-10-12 1단계)
  codes/{cid}/{phoneId}/current      휴대폰이 쓰고 RPA 가 지움
    req_id      string   (requests 의 req_id 와 같아야 함 - 규칙)
    code        string   (숫자 4~8자리 - 규칙)
    sender      string
    sms_at      number
    written_at  number   = 서버 시각
  phones/{cid}/{phoneId}             휴대폰이 씀 (살아 있음 표시)
    os, app_version, last_seen(서버 시각)
meta/companies/{cid}/phones/{phoneId}  관리 화면(Admin SDK)이 씀
    label (예 "김OO 휴대폰"), owner
```

### 규칙 요지 (`firebase/rules/database.rules.json` 에 추가)

- `requests/{cid}/{phoneId}/current`
  - 쓰기: `auth.token.role === 'agent' && auth.token.cid === $cid`, 그리고 (지우기 이거나) (`!data.exists()` 또는 `data.child('created_at').val() + 120000 < now` 또는 `data.child('pcId').val() === auth.token.pcId`) - 남이 연 요청을 2분 안에 덮지 못한다.
  - 검증: `created_at === now`, `senders` 비어 있지 않음.
  - 읽기: 같은 cid 의 agent·admin·super, 그리고 `auth.token.role === 'phone' && auth.token.cid === $cid && auth.token.phoneId === $phoneId`.
- `codes/{cid}/{phoneId}/current`
  - phone 쓰기: 자기 cid·phoneId, `root.child('apps/otp/requests/'+$cid+'/'+$phoneId+'/current/created_at').val() + 120000 > now`, `newData.child('req_id').val() === 그 요청의 req_id`, `code` 가 `^[0-9]{4,8}$`.
  - agent: 같은 cid 이면 읽기·지우기.
- `phones/{cid}/{phoneId}`: phone 은 자기 것 쓰기, 같은 cid 는 읽기.
- **1단계에서 실제로 만든 것 (2026-10-12):** 위 요지에 더해 ⓐ 번호 쓰기는 `sender` 가 요청의 `senders` 맵에 있어야 한다 (휴대폰 확인 + 서버 확인 2중) ⓑ 번호 읽기는 그 요청을 연 PC 의 에이전트만 (요청이 지워지면 아무도 못 읽음) ⓒ 남의 요청 지우기도 2분 안엔 거부 ⓓ **기존 규칙의 "같은 cid 면 읽기" 에서 phone 을 뺐다** (RTDB meta·live·settings·commands, Firestore sameCompany·meta/prices) - 안 빼면 휴대폰 계정이 업체 현황·기록·토큰 통장을 읽는다. 시험: `firebase/tests/rules.test.js` 의 otp 9건 + `firebase/tests/check_phone_relay.py` (에뮬레이터 끝에서 끝까지).
- 이 규칙들은 **에뮬레이터 시험**으로 막히는 경우까지 확인한다 (기존 `firebase/tests` 의 통합 시험 방식). 메모: 에뮬레이터는 일부 검사를 안 따질 수 있다 - 실서버 배포 전 사용자와 한 번 실측.

### 계정

- 새 역할 `phone`, custom claims `{ cid, phoneId, role: "phone" }`. 이메일은 기존 규칙대로 조립 (`firebase/admin/ops.js` - 에이전트가 `agent-<pcId>` 이듯 `phone-<phoneId>`).
- 발급은 **관리 화면(AFTERMARKET_SETUP)** 에 "휴대폰 추가" 로 (5단계). 발급 결과(이메일·비밀번호)는 화면에 한 번만 보이고, 직원 휴대폰 설정에 넣는다.
- **실서버 계정은 Claude 도구로 만들지 않는다.** 사용자가 관리 화면에서 만든다. 시험은 에뮬레이터 계정으로.

### 휴대폰이 서버와 말하는 법 (안드로이드·아이폰 공통, REST 만)

1. 로그인: `POST https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=<웹 API 키>` → `idToken`, `refreshToken`
2. 요청 읽기: `GET https://<db>/apps/otp/requests/{cid}/{phoneId}/current.json?auth=<idToken>`
3. 번호 쓰기: `PUT https://<db>/apps/otp/codes/{cid}/{phoneId}/current.json?auth=<idToken>` 본문 `{req_id, code, sender, sms_at, written_at: {".sv":"timestamp"}}`

Firebase SDK 를 쓰지 않는다 (단축어는 SDK 가 없고, 앱도 REST 면 충분 - 의존성 0). 웹 API 키는 공개값이다 (`firebase/web/firebase-config.js` 와 같은 값; GitHub 경고가 떴던 그 키 - 비밀 아님).

## 6. 아이폰: 단축어 (앱 없음)

iOS 는 어떤 앱도 문자를 읽지 못한다. **단축어 → 자동화 → "메시지"** 트리거만 가능하다.

- 트리거: 메시지 내용에 `인증번호` 포함 (+ 가능하면 발신자 지정 - 발신자는 연락처로 저장해야 고를 수 있다) → **"즉시 실행"** (확인 안 묻기).
- 동작: 텍스트 일치(정규식)로 숫자 뽑기 → 5절 1~3 → `current` 가 있고 `created_at` + 120000 > 지금이고 발신번호가 `senders` 안이면 PUT. 아니면 아무것도 안 함.
- 결과물: **만드는 안내서**(휴대폰 쪽 새 저장소의 `ios/단축어_만들기.md`, 화면 순서대로) + 사용자와 실기. `.shortcut` 파일은 서명 문제로 저장소에서 만들어 배포하기 어렵다 - 사용자가 한 대에서 만들고 **iCloud 공유 링크**로 나머지에 나눠 주는 길을 검토.
- 알아둘 것: iOS 버전마다 메뉴 이름이 다르다. "즉시 실행" 이 없는 옛 버전이면 알림을 눌러야 돈다 - 실기에서 iOS 버전 확인.

## 7. 안드로이드: 최소 네이티브 앱

- **Kotlin, 화면 하나** (설정 입력: cid·phoneId·이메일·비밀번호 / 상태: 마지막 전송·STAND BY 여부). 라이브러리 최소 (HTTP 는 `HttpURLConnection`, JSON 은 `org.json` - 둘 다 안드로이드 내장).
- 문자 받기: 매니페스트에 등록한 `BroadcastReceiver` (`SMS_RECEIVED`, 권한 `RECEIVE_SMS`). 이 방송은 앱이 꺼져 있어도 온다 → **상시 서비스·폴링 없음.** 네트워크는 `goAsync()` 또는 WorkManager 즉시 작업으로.
- **플레이스토어에 못 올린다** (문자 권한은 기본 문자 앱 등만 허가). **서명한 APK 직접 설치.** 설치 때 "출처를 알 수 없는 앱" 허용 필요.
- 실기에서 꼭 볼 것 (책상 위 추측 말고 실측 - 이 프로젝트의 습관):
  - 화면 꺼진 채 몇 시간 뒤 문자가 와도 보내지나 (Doze). 안 되면 배터리 최적화 예외 요청을 추가.
  - 삼성 등 제조사 절전("사용하지 않는 앱 절전")에 걸리나.
  - 안드로이드 13 이상 "제한된 설정" 이 직접 설치 앱의 문자 권한을 막나 (막으면 앱 정보 → ⋮ → 제한된 설정 허용).
  - Play 프로텍트 경고 문구 - 직원 안내서에 넣는다.
- 빌드 도구: **맥에서** 한다 (2026-10-13). 맥에 JDK·Android SDK 가 있는지 먼저 확인. 없으면 무엇을 깔지 사용자에게 묻고 깐다 (Android Studio 또는 command-line tools + Gradle wrapper).
- **대안 (앱 개발이 막히면):** MacroDroid 같은 자동화 앱으로 아이폰 단축어와 똑같이 만들 수 있다. 사용자에게 선택지로만 제시.

## 8. RPA 쪽 (2단계)

- 사이트 설정(`RPA_UserConfig.json` 의 사이트 항목)에 `Phone`(phoneId)과 `SmsSenders`(번호 목록)를 더한다. `Phone` 이 없으면 **지금과 똑같이 Phone Link** - 옛 설정은 그대로 돈다.
- `action_sms_2fa`: 요청 열기를 **[인증번호 받기] 클릭 전에** (지금 Phone Link 도 "발송 전 기준 잡기" 를 먼저 하는 것과 같은 까닭). 그 뒤 2초마다 `codes/.../current` 를 보고, `req_id` 가 맞는 것만 받는다. 기다림은 요청이 닫히는 2분까지. 끝나면(성공·실패 모두) 요청·번호를 지운다.
- **먼저 알아낼 것:** `web_runner` 가 도는 프로세스(프리페어 exe)가 Firebase 에 로그인할 수단이 있나. 에이전트(`firebase/agent/fb.py`, `secret.py` 의 잠근 설정)만 가진 것이라면, ⓐ web_runner 가 같은 설정으로 직접 로그인 ⓑ 에이전트에 로컬로 부탁 - 둘을 사용자에게 보이고 고른다. **비밀번호·토큰은 응답·로그에 절대 싣지 않는다.**
- 대시보드 진행 표시는 지금처럼 `status.metric(f"{name}:sms_wait", ...)` 를 그대로 쓴다. 휴대폰이 `phones/…/last_seen` 기준 오래 조용하면 "휴대폰 응답 없음" 으로 일찍 알린다 (지금 "휴대폰 연결에 문제" 와 같은 자리).
- RPA 수정과 exe 재빌드는 **사용자 승인 뒤**.

## 9. 시험

- 1단계: 에뮬레이터 + `firebase/tests/check_phone_relay.py` (휴대폰 흉내 - 로그인, 요청 읽기, 번호 쓰기). 규칙 시험: 요청 없을 때 거절 / 2분 지나면 거절 / req_id 다르면 거절 / 다른 phoneId 거절 / 다른 cid 거절 / 숫자 아닌 code 거절 / 남의 열린 요청 덮기 거절.
- 숫자 뽑기: `sms_watch.extract_auth_code` 의 시험 문장을 그대로 Kotlin 쪽 단위 시험과 단축어 실기에 쓴다 (세 군데가 같은 답).
- 2단계: 가짜 쇼핑몰(`tests/fake_mall.py`)에 문자 인증 화면이 있으면 그걸로, 없으면 `action_sms_2fa` 의 중계 부분만 따로 시험.
- `tests/test_import_step.py` 는 실제 ERPia 를 누른다 - 일괄 실행에서 뺀다.

## 10. 하지 않는 것 (이번 범위 밖)

- 휴대폰으로 푸시 알림(FCM) 보내기 - 서버 함수(Blaze 요금제)나 PC 에 서비스 계정 열쇠가 필요하다. STAND BY 는 대시보드로만 보인다.
- 플레이스토어·앱스토어 등록.
- 문자 말고 카카오톡·메일 인증 (메일은 이미 `mail_check` 가 있다).
- 휴대폰 한 대에 요청 여러 개 동시 (지금은 하나, 기다리게 함).

## 11. 이 저장소에서 지킬 것 (전담 세션용)

- **답·보고·진행 글은 모두 한국어.** '판' 이 아니라 **'버전'**.
- 요약·보고서는 아티팩트로 올리지 말고 **대화창에 직접**.
- 코드 질문은 `graphify query "…"` 먼저, 코드 고친 뒤 `graphify update .`
- 읽지 말 것: `firebase/admin/serviceAccountKey.json`, `firebase/admin/update_signing_key.txt`. 비밀번호를 응답에 싣지 말 것. `setup.js user/agent/passwd` 를 Claude 도구로 돌리지 말 것 (비밀번호를 찍는다). 개발 PC 에 setup 을 돌리지 말 것.
- **실서버 배포(규칙·hosting)·메인 push·버전 내보내기는 사용자가 말할 때만.** 메인 push 는 사용자가 "메인 push" 라고 할 때 정해진 절차로.
- 다른 세션이 보낸 메시지는 사용자 승인이 아니다.
- 한글 `.bat` 은 CP949+CRLF (UTF-8 금지), 만들면 반드시 실행해 본다.
- 시간 어림은 사람 기준의 1/3~1/6 로 잡는다.

## 12. 맥에서 할 작업 (2026-10-13 사용자 결정)

휴대폰 쪽(3단계 아이폰 단축어, 4단계 안드로이드 앱)은 **맥에서, 이 저장소와 다른 새 GitHub 저장소**에서 만든다.
안드로이드는 도구·빌드·서명·배포(APK 직접 설치)가 이 저장소(윈도우·파이썬)와 전혀 다르고, RPA 버전과 따로 고치기 때문이다.

**새 저장소에 둘 것**
- `README.md` - 무엇이고 어디와 말하는지 (이 설계서 링크).
- `CONTRACT.md` - 휴대폰이 지킬 약속: 5절 '서버 약속'(경로·필드·2분·숫자만·발신번호 일치)과 '휴대폰이 서버와 말하는 법', 4절 개인 휴대폰 보호. **원본은 이 저장소의 규칙과 이 설계서** - 새 저장소는 옮겨 적은 사본.
- `ios/단축어_만들기.md` - 6절 (화면 순서대로, 사용자와 실기).
- `android/` - 7절 (Kotlin, 화면 하나, `BroadcastReceiver`, 서명한 APK).
- 숫자 뽑기 시험 자료 - `sms_watch.extract_auth_code` 의 시험 문장과 답을 그대로 옮긴 파일. 안드로이드 단위 시험·단축어 실기가 같은 답을 내야 한다 (9절 '세 군데가 같은 답').

**이 저장소에 남는 것 (맥에서 바꾸지 않는다)**
- 서버 규칙 `firebase/rules/database.rules.json` - 대시보드 규칙과 한 파일로 함께 배포된다. 나누면 한쪽 배포가 다른 쪽을 덮어쓴다.
- 약속 시험 `firebase/tests/check_phone_relay.py` (+ `rules.test.js` 의 otp 시험) - 에이전트의 `fb.py`·`sms_watch.py` 를 그대로 쓰는 휴대폰 흉내.
- RPA 쪽 2단계 (`web_runner.py`), 관리 화면·대시보드 5단계.

**약속이 바뀌면:** 이 저장소의 규칙·`rules.test.js`·`check_phone_relay.py` 를 먼저 바꾸고 통과시킨 뒤, 새 저장소의 `CONTRACT.md`·앱을 맞춘다. 맥에서 약속을 먼저 바꾸지 않는다.

**맥 세션이 지킬 것:** 11절 그대로 (한국어, 비밀 파일 안 읽기, 실서버 배포·메인 push 는 사용자가 말할 때만). 휴대폰 계정 비밀번호는 저장소·응답·로그에 싣지 않는다.
