# 스탠드얼론 ④ 휴대폰 창구 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 스탠드얼론 PC 에서 직원 휴대폰 앱이 사내 와이파이로 그 PC 의 로컬 서버에 인증번호(숫자만)를 직접 보내고, 휴대폰이 없거나 답이 없으면 사람이 Edge 의 인증 칸에 넣기를 5분 기다린다 - Firebase 를 거치지 않는다.

**Architecture:** 새 `local_phone.py` 가 짝지은 휴대폰 표(`phones.json`)·짝짓기·요청 서명·인증번호 자리 검사와 2분 만료를 맡고, 같은 파일의 `PhoneServer` 가 사내망(0.0.0.0:8782)에 HTTPS 포트 하나를 연다 - 이 포트의 처리기는 `/phone/v1/*` 세 주소만 알고 웹·`/api`·`/db`·`/fs` 코드를 부르지 않는다 (127.0.0.1:8781 의 처리기와 다른 클래스). 인증서는 새 `local_cert.py` 가 그 PC 에서 한 번 만든다. PC 쪽(`otp_relay.PhoneRelay`)은 지금처럼 `apps/otp` 자리를 중계 열쇠로 읽고, 스탠드얼론에서만 새 `otp_relay.FallbackOtp` 가 '휴대폰 2분 → 사람 5분' 을 잇는다.

**Tech Stack:** Python 3.14 표준 라이브러리(ssl·http.server·hmac·hashlib·ctypes·ipaddress·subprocess). 인증서는 **내장 파이썬에 이미 실린 OpenSSL 3.5(`DLLs\libcrypto-3.dll`)를 ctypes 로 불러** 만든다 - 내장 파이썬에는 `cryptography` 가 없고(site-packages 자체가 없다) 새 패키지를 넣지 않는다. 윈도우 `netsh advfirewall`·PowerShell `Get-NetIPAddress`/`Get-NetConnectionProfile`. 브라우저 쪽은 ES 모듈 + QR 생성 코드(MIT `qrcode-generator` 파일 하나를 저장소에 넣는다). 화면 시험은 Playwright(`tests/check_web_local.py`).

**Spec:** `docs/superpowers/specs/2026-11-23-standalone-local-server-design.md` (5·6.2·6.7·7·8·9절). 일반 버전의 약속은 `docs/superpowers/specs/2026-10-12-phone-otp-relay-design.md` 4·5·13절 (같은 뜻을 지킨다). 앞 계획 ①·② 의 이름을 쓴다.

**시작 조건:** 계획 ② 가 끝난 뒤 시작한다 (`data-local.js`·`tests/check_web_local.py`·`local_web.Web` 이 있어야 한다). 시작할 때 `firebase/agent/local_server.py`·`local_web.py` 를 다시 읽는다 - 이 계획서는 2026-11-23 의 코드를 보고 썼고 그 뒤 계획 ②·③ 작업으로 줄 번호·작은 이름이 달라졌을 수 있다.

## Global Constraints

- 일반(cloud) 버전 동작은 바뀌지 않는다. 각 작업 끝에 `firebase\tests\test_agent.py`·`tests\test_fb_backoff.py`·`tests\test_cloud_scrub.py`·`tests\test_dev_env.py`·`tests\test_otp_replay.py`·`tests\test_mail_otp_replay.py` 와 스탠드얼론 시험(계획 ① 여섯 파일·`tests\test_local_web_api.py`)이 통과해야 한다. Task 3·4 뒤에는 에뮬레이터 `firebase/tests/check_web.py`·`check_phone_relay.py` 도 (에뮬레이터에만 붙는다 - 실서버 금지).
- 휴대폰 포트는 `8782` 하나. 그 포트에서 답하는 주소는 `POST /phone/v1/pair`·`GET /phone/v1/request`·`POST /phone/v1/code` 셋뿐이다. 웹·`/api`·`/db`·`/fs` 는 127.0.0.1:8781 에서만 (계획 ①·② 그대로).
- **짝지은 휴대폰도 없고 짝짓기 중도 아니면 포트를 열지 않고 방화벽 규칙도 두지 않는다** (Claude 판단 - 쓰지 않는 PC 는 사내망에 여는 것이 0).
- 휴대폰이 서버로 보내는 것은 인증번호 숫자·발신번호·받은 시각뿐이다. 서버는 정해진 칸 밖의 칸이 있으면 거절한다 (문자 본문을 실수로 보내는 앱을 서버가 막는다).
- 비밀 값(짝 열쇠·서명 열쇠·인증서 개인 열쇠·인증번호)은 로그·예외 글·실행 기록·`store.json` 에 싣지 않는다. QR 내용은 `POST /api/phone-pair` 응답에 한 번만 나간다.
- 휴대폰 포트를 열어도 프로그램이 **스스로 밖으로 거는 연결은 없다** (받기만 한다). `local_phone.py`·`local_cert.py` 는 `urllib`·`http.client`·`socket.create_connection` 을 쓰지 않는다.
- 시험은 휴대폰 포트를 `127.0.0.1` 의 빈 포트에만 묶고, 진짜 방화벽 규칙을 만들지 않는다 (`run` 을 가짜로 넣거나 `RPA_PHONE_NO_FIREWALL=1`). 시험용 덮어쓰기는 `rpa_status.dev_env` 로만: `RPA_PHONE_PORT`·`RPA_PHONE_HOST`·`RPA_PHONE_NO_FIREWALL`.
- 화면(휴대폰 칸)은 지금 업체 웹의 카드·표·단추 class(`card`·`h2`·`msg`·`lbl`·`seg`·`tbl`·`apply`)를 그대로 쓴다. 따로 뜨는 창(모달)을 새로 만들지 않고 QR 은 카드 안에 보인다. 다 만든 뒤 사용자에게 화면을 보여 준다.
- 휴대폰 앱 코드(비공개 저장소 `TE-JA-VA/RPA-PhoneRelay`)는 여기서 고치지 않는다. 약속이 바뀌면 이 저장소의 시험·약속 문서를 먼저 고친다.
- 글은 한국어, 화면·로그 문장은 지금 말투 ("…하여 주십시오"). 파이썬 실행은 `D:/AX/RPA/.venv/Scripts/python.exe`. 패치는 Write 도구 파일로. 코드를 고친 뒤 `graphify update .`. 커밋은 작업마다 (`git commit -F`), 끝에 `Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>`. push 는 사용자 지시가 있을 때만.

**보안 값 (모두 Claude 판단 - 바꾸려면 이 표와 약속 문서·시험을 같이 고친다)**

| 값 | 정한 것 | 까닭 |
|---|---|---|
| 인증서 | P-256(ECDSA) 자체 서명, SHA-256, 유효 3650일, CN `AUTOPILOT Phone Gate` | 안드로이드·아이폰 모두 받는다. 다시 만들면 지문이 바뀌어 모든 휴대폰을 다시 짝짓는다 |
| TLS | 1.2 이상, 1.2 는 `ECDHE+AESGCM:ECDHE+CHACHA20` 만, 재협상 끔 | 옛 안드로이드(1.2)까지 |
| 지문 | 인증서 DER 의 SHA-256, 소문자 hex 64자 | 앱이 이 값과 같은 인증서에만 요청을 보낸다 (이름·기관 확인 대신) |
| 짝 열쇠 | 무작위 32바이트, QR 에 base64url 43자. 유효 **300초**, **한 번** | 서버는 메모리에만 둔다 (파일에 안 남는다) |
| 서명 열쇠 | `sha256("ap1 phone key\n" + 짝 열쇠 + 휴대폰이 만든 32바이트)` hex 64자 - 서버는 이 해시만 `phones.json` 에 둔다 | 휴대폰 쪽 무작위가 섞여, 짝지은 뒤에는 QR 사진만으로 열쇠를 못 만든다. 단, 저장한 해시가 곧 서명 열쇠다 - `phones.json` 이 새면 그 휴대폰을 흉내 낼 수 있으므로 파일은 관리자·SYSTEM 만 읽는다 (같은 폴더의 `agent.key` 와 같은 급) |
| 요청 시각 | 서버 시각과 ±120초, nonce 300초 기억 | 닫힌 망의 PC 는 시계가 틀릴 수 있다 → 서명은 맞고 시각만 틀리면 서버 시각을 알려 준다(`clock`) |
| 시도 제한 | 한 주소(IP)에서 서명 틀림 10번/600초 → 그 주소 600초 거절(429). 짝짓기 서명 틀림 5번 → 그 짝짓기 취소 | 휴대폰 번호로 잠그지 않는다 (남이 틀린 요청으로 진짜 휴대폰을 잠그지 못하게) |
| 연결 제한 | 동시 16개·주소마다 4개·주소마다 60요청/분, TLS 악수 5초, 요청 읽기 5초, 본문 2048바이트, 늘 `Connection: close` | 느린 연결·큰 본문으로 서버를 묶지 못하게. 127.0.0.1 서버의 연결 상한(64)과 따로 센다 |
| 보낸 쪽 | 사설·이 PC 주소(`ipaddress.is_private`·loopback)가 아니면 응답 없이 닫는다 | 방화벽 프로필이 틀어져도 한 겹 더 |
| 방화벽 | 규칙 이름 `AUTOPILOT Phone OTP`, TCP 8782 들어오는 것, 프로필 `private,domain`, 프로그램 = 서버를 돌리는 python | 공용 망에서는 열리지 않는다 |

## Review Focus

사내망에 열리는 유일한 창구다. **같은 망의 다른 기기가 할 수 있는 일**을 빠짐없이 본다.

1. 포트 훑기 → 휴대폰을 쓰지 않는 PC 는 열린 포트가 없다. 쓰는 PC 도 8782 하나뿐이고 8781 은 127.0.0.1 에만 묶여 있다 (Task 2 시험).
2. 8782 에서 다른 창구 찔러 보기 (`/`·`/api/login`·`/db/…`·`/fs/…`·`/index.html`·`/phone/v1/../api/session`·질의 붙이기·PUT·OPTIONS·TLS 없는 HTTP) → 모두 같은 404 이거나 응답 없이 닫힘. 처리기가 `local_web`·`Store` 의 다른 자리를 부를 길이 코드에 없다 (Task 2 시험).
3. 짝 열쇠·서명 추측 → 없는 휴대폰과 틀린 서명이 같은 401, 견주기는 `hmac.compare_digest`, 10번 틀리면 그 주소 10분 거절 (Task 2 시험).
4. 요청 되풀이 → 같은 nonce 401, 지난 시각 401, 지운 휴대폰의 옛 열쇠 401 (Task 2·5 시험).
5. 큰 본문·느린 연결 → 2048바이트 넘는 본문은 읽지 않고 413, 악수·머리글을 끄는 연결은 5초에 끊김, 그동안 다른 휴대폰과 127.0.0.1 의 웹은 답한다 (Task 2 시험).
6. QR 사진 유출 → 5분·한 번뿐이고, 짝지은 뒤의 서명 열쇠는 QR 만으로 못 만든다. 남은 틈: 5분 안에 사진을 찍은 사람이 **먼저** 짝짓는 것 - 그때 진짜 휴대폰은 실패하고 화면에 연결된 기기 이름이 뜬다 (관리자가 지운다). 얻는 것은 그 휴대폰 몫의 '열린 요청 보기'·'틀린 번호 넣기' 뿐, 진짜 인증번호는 못 본다 (받아들이는 위험 - Task 3 시험이 한 번만·5분을 본다).
7. PC 흉내 (같은 주소·포트에 가짜 서버) → 앱은 지문이 다른 인증서에 아무것도 보내지 않는다, 응답 서명도 확인한다 (Task 5 휴대폰 흉내 시험).
8. 짝지은 휴대폰이 나쁜 마음을 먹음 → 자기 몫의 요청만 보고 번호만 쓸 수 있다. 번호를 읽거나 남의 휴대폰 자리를 건드리지 못하고, 요청의 발신번호가 아니면 못 쓴다 (Task 1·2 시험).

---

### Task 1: 짝지은 휴대폰 표 · 서명 · 인증번호 자리 검사와 2분 만료

**Files:**
- Create: `firebase/agent/local_phone.py` (이 작업은 `Phones`·`Pairing`·`Desk`·서명 함수·`Service` 의 뼈대 - 포트는 Task 2)
- Modify: `firebase/agent/local_server.py` (`make_server(..., phone=None)`, `_db` 의 `phones`·`otp_requests`·`otp_codes`, `otp_request_ok`, `main`), `tests/test_local_server_http.py`·`tests/test_local_store_client.py` (인증번호 시험이 `Store` 의 `phones/<cid>` 대신 짝지은 휴대폰을 먼저 만든다)
- Test: `tests/test_phone_core.py`

**Interfaces:**
- Consumes: 계획 ① `Store`(VOLATILE `apps/otp`)·`classify`·`allowed`·`log`·`data_dir`·`local_store._mac`·머리글 이름 `H_TIME`("X-AP-Time")·`H_NONCE`("X-AP-Nonce")·`H_SIGN`("X-AP-Sign").
- Produces (`local_phone`):
  - 값: `PHONE_PORT = 8782`, `OPEN_MS = 120000`, `PAIR_SEC = 300`, `SIGN_WINDOW_MS = 120000`, `NONCE_KEEP_SEC = 300`, `PHONES_NAME = "phones.json"`, `PHONES_MAX = 20`, `SENDERS_MAX = 20`, `CODE_PUTS_MAX = 5`, `H_PHONE = "X-AP-Phone"`. 휴대폰 번호(phoneId) = `"ph_" + secrets.token_hex(4)` (`^ph_[0-9a-f]{8}$`), 발신번호 `^[0-9]{3,15}$`, 인증번호 `^[0-9]{4,8}$`, 이름·담당자 40자까지.
  - 열쇠: `pair_key(secret: bytes) -> str` = `sha256(b"ap1 phone pair\n" + secret).hexdigest()` (짝짓기 요청 하나만 서명), `sign_key(secret: bytes, rand: bytes) -> str` = `sha256(b"ap1 phone key\n" + secret + rand).hexdigest()` (그 뒤 모든 요청).
  - 서명: `request_mac(key, phone_id, method, target, ts, nonce, body) -> str` = `local_store._mac(key, ["ap1", "phone-req", phone_id, method, target, str(ts), nonce, sha256hex(body)])`, `response_mac(key, nonce, status, body)` = `_mac(key, ["ap1", "phone-res", nonce, str(status), sha256hex(body)])`. (`_mac` = HMAC-SHA256, 열쇠는 hex 글의 UTF-8 바이트, 조각은 `\n` 으로 이음, 결과 소문자 hex - 계획 ① 의 에이전트 서명과 같은 함수.) `target` = 보낸 그대로의 경로, `ts` = ms 글자, `nonce` = `[0-9a-f]{16,64}`.
  - `parse_senders(value) -> list[str]` - 글(쉼표·빈칸·`;`)이나 목록을 받아 `-`·`(`·`)` 를 빼고 겹친 것을 없앤다. `ValueError`: "발신번호는 숫자 3~15자리여야 합니다: …", "발신번호는 20개까지 입력할 수 있습니다." (관리 화면 `ops.js parseSenders` 와 같은 글).
  - `class Phones(path)` - `phones.json` = `{"v": 1, "phones": {<id>: {label, owner, senders: [..], key, fp, paired_at, os, app_version, device}}}` (임시 파일 → `os.replace`, 깨진 파일은 `.broken` 으로 옮기고 빈 표 + 로그). `add(id, label, owner, senders, key, fp, os, app_version, device)`, `get(id) -> dict|None`(열쇠 포함 - 서버 안에서만), `list(fp_now=None) -> [{id, label, owner, senders, paired_at, last_seen, os, app_version, device, stale}]` (열쇠 없음, `stale` = 짝지을 때의 지문 ≠ 지금 지문), `public() -> {<id>: {"label", "owner", "senders": {<번호>: True}}} | None` (일반 버전 `meta/companies/<cid>/phones` 와 같은 꼴 - `otp_relay.phone_list` 가 그대로 읽는다. `senders` 가 비면 칸을 뺀다 = 제한 없음), `update(id, label=None, owner=None, senders=None)`, `remove(id) -> bool`, `seen(id)`(마지막 연결 시각 - 메모리에만), `count()`. 20대를 넘기면 `ValueError("휴대폰은 20대까지 등록할 수 있습니다.")`.
  - `class Pairing(clock=time.time)` - 한 번에 하나. `start(label, owner, senders) -> {"phone_id", "secret": bytes, "expires_at"}` (앞의 것은 버린다), `claim(phone_id) -> dict|None`(살아 있는 것만), `fail()`(5번이면 취소), `done(phone)`, `cancel()`, `state() -> {"state": "none"|"waiting"|"paired"|"expired", "left_sec", "phone"?: {id, label, os, device}}` (`paired`·`expired` 는 60초 동안 보여 주고 `none`).
  - `class Desk(store, phones, lic, clock=time.time)` - 인증번호 자리의 규칙 (일반 버전 RTDB 규칙과 같은 뜻):
    - `open_request(phone_id) -> dict|None` - `apps/otp/requests/<cid>/<phone_id>/current` 가 있고 `created_at + OPEN_MS > 지금(ms)` 일 때만.
    - `submit(phone_id, body) -> (status, error|None)` - 본문은 정확히 `{req_id, code, sender, sms_at}` 네 칸. 차례대로: 칸이 더 있거나 모자람·꼴 틀림 → `(400, "bad_request")`, 열린 요청 없음 → `(409, "no_request")`, `req_id` 다름 → `(409, "req_mismatch")`, `sender` 가 그 요청의 `senders` 에 없음 → `(403, "sender_not_allowed")`, 같은 요청에 6번째 → `(429, "too_many")`. 맞으면 `apps/otp/codes/<cid>/<phone_id>/current` = `{req_id, code, sender, sms_at, written_at: 서버 ms}` 를 쓰고 `(200, None)`.
    - `read_code(phone_id) -> dict|None` - 열린 요청이 있고 `req_id` 가 같을 때만 (요청이 닫히면 번호는 아무도 못 읽는다).
    - `sweep() -> int` - 2분 지난 요청과 그 번호, 요청 없는 번호, 지운 휴대폰의 자리를 지운다. `Service` 가 5초마다 부른다 (계획 ① 이 넘긴 '서버 쪽 2분 만료 지우기').
  - `class Service(folder, store, lic, clock=time.time, run=None)` - `phones`·`pairing`·`desk` 를 묶는다 (`gate` 는 Task 2). `start()`(5초 고리 스레드), `stop()`.
- `local_server` 바뀌는 것:
  - `make_server(..., web=None, phone=None)` → `srv.phone`. `main()` 이 `local_phone.Service(folder, store, lic)` 를 만들어 넘기고 `start()`.
  - `otp_request_ok(body, lic, phone=None)` - `phone`(= `srv.phone.phones.get(<phoneId>)`)이 None 이면 False (짝짓지 않은 휴대폰으로는 요청을 못 연다). 더하는 검사: `req_id` 는 `^[A-Za-z0-9_-]{8,64}$`, `site` 100자까지, `senders` 는 비어 있지 않고, 그 휴대폰에 허용 발신번호가 있으면 모두 그 안.
  - `GET /db/meta/companies/<cid>/phones.json` → `srv.phone.phones.public()` (계획 ① 이 비워 둔 `Store` 의 `phones/<cid>` 는 쓰지 않는다 - 서명 열쇠가 든 표를 일반 나무와 섞지 않는다). `GET /db/apps/otp/codes/<cid>/<id>/current.json` → `desk.read_code(<id>)`. `srv.phone` 이 None 이면 요청 열기는 403, 목록·번호는 null.
- 설계 6.2 는 휴대폰 표를 SQLite 로 적었으나 **JSON 파일**로 둔다 (20줄 안쪽, 계획 ② `accounts.json` 과 같은 방식 - Claude 판단).

- [ ] **Step 1: 실패하는 시험** `tests/test_phone_core.py` (가짜 시계, 임시 폴더). 넣을 검사:
  - 열쇠·서명: `pair_key`·`sign_key` 가 같은 입력에 같은 값·`rand` 가 다르면 다른 값, `request_mac` 이 조각 하나(방법·경로·시각·nonce·본문)만 달라도 달라진다.
  - `parse_senders`: `"1588-1234, 0212345678"` → 두 개, 글자 섞인 것·21개 → 각 글의 `ValueError`.
  - `Phones`: 넣고 다시 열어도 남음, `list()`·`public()` 어디에도 `key` 가 없음, `public()` 의 `senders` 는 `{번호: True}`·비면 칸 없음, 21번째 `ValueError`, 깨진 파일 → 빈 표 + `.broken`, `stale` (지문이 다르면 True).
  - `Pairing`: 시작 → `waiting`·`left_sec` 300, 301초 뒤 `claim` None·`expired`, 다시 시작하면 앞의 것 못 씀, `fail()` 다섯 번이면 취소, `done` 뒤 `paired` 60초.
  - `otp_request_ok`: 짝지은 휴대폰 True / `phone=None` False / 빈 `senders` False / 허용 밖 발신번호 False / `req_id` 7자 False.
  - `Desk`: 요청 없음 `no_request`, 열고 119.9초 뒤 열려 있음·120초 뒤 닫힘, `req_id` 다름, 요청에 없는 발신번호, `code` 가 `12a456`·3자리·9자리 `bad_request`, 칸 하나 더(`"body": "문자 전체"`) `bad_request`, 여섯 번째 `too_many`, 성공하면 쓴 값의 칸이 정확히 다섯, `read_code` 는 요청이 열려 있고 `req_id` 가 같을 때만, `sweep` 뒤 지난 요청·그 번호·요청 없는 번호가 없다, 다른 휴대폰의 요청은 못 본다 (Review Focus 8).
  - HTTP (계획 ① 서버 + `Service`): 중계 열쇠의 `GET …/phones.json` 에 `key`·`fp` 없음, 짝짓지 않은 `ph_x` 로 요청 PUT 403, 짝지은 것 200, `otp_relay.PhoneRelay.open` 이 짝짓지 않은 휴대폰에 `RuntimeError(otp_relay.DENIED)` 를 5초 안에, 열기 → `desk.submit` → `relay.wait` 가 그 번호 → `close` 뒤 두 자리 없음, `store.json` 에 번호·열쇠가 없다.
- [ ] **Step 2: 실패 확인** → `ModuleNotFoundError: local_phone`.
- [ ] **Step 3: 구현.** `Desk` 의 읽고 쓰기는 `Store.put/delete(..., guard=)` 로 확인과 쓰기를 한 잠금 안에서 (계획 ① 검토 뒤 방식). 고친 두 시험 파일은 `Service` 에 `ph1` 을 넣고 시작하게 바꾼다.
- [ ] **Step 4: 통과 확인** + Global Constraints 의 시험.
- [ ] **Step 5: 커밋** - "스탠드얼론 ④ Task 1 - 짝지은 휴대폰 표·요청 서명·인증번호 자리 검사와 2분 만료".

### Task 2: 인증서 · 휴대폰 포트 · 방화벽

**Files:**
- Create: `firebase/agent/local_cert.py`, `tests/fake_phone_local.py` (휴대폰 흉내 - 이 작업은 연결·서명·지문 확인까지, Task 5 가 넓힌다)
- Modify: `firebase/agent/local_phone.py` (`PhoneServer`·`PhoneHandler`·`Gate`), `firebase/agent/local_server.py` (`main` 이 `service.gate.sync()`, 끌 때 `service.stop()`)
- Test: `tests/test_phone_gate.py`

**Interfaces:**
- Consumes: Task 1 전부.
- Produces (`local_cert`):
  - `CERT_NAME = "phone_cert.pem"`, `KEY_NAME = "phone_key.pem"` (둘 다 `local_server.data_dir()` 에. 그 폴더는 `install_root()` 의 관리자·SYSTEM 전용 권한을 물려받고(`rpa_settings.lock_data_acl`), 계획 ③ 의 `local_server.lock_key_files` 가 잠그는 파일 목록에 `phone_key.pem`·`phones.json` 을 더한다 - 그 함수가 아직 없으면 물려받기만 두고 '계획 ③에 기대는 것' 3번으로 넘긴다), `VALID_DAYS = 3650`, `CN = "AUTOPILOT Phone Gate"`, `class CertError(Exception)`.
  - `make(folder)` - `os.path.dirname(_ssl.__file__)` 옆의 `libcrypto-3.dll` 을 `ctypes.CDLL` 로 열어 P-256 열쇠와 v3 자체 서명 인증서를 만든다. 쓰는 함수 (2026-11-23 내장 파이썬 3.14.10·OpenSSL 3.5.9 에서 실측 - 0.02초, TLS 1.3 악수 됨): `EVP_PKEY_CTX_new_id(408)`·`EVP_PKEY_keygen_init`·`EVP_PKEY_CTX_set_ec_paramgen_curve_nid(ctx, 415)`·`EVP_PKEY_keygen`·`X509_new`·`X509_set_version(x, 2)`·`X509_get_serialNumber`+`ASN1_INTEGER_set_uint64`(무작위 63비트)·`X509_getm_notBefore/After`+`X509_gmtime_adj`(-86400 / 3650×86400)·`X509_set_pubkey`·`X509_get_subject_name`+`X509_NAME_add_entry_by_txt("CN", 0x1001, …)`·`X509_set_issuer_name`·`X509_sign(x, pkey, EVP_sha256())`·`BIO_new(BIO_s_mem())`·`PEM_write_bio_PrivateKey`·`PEM_write_bio_X509`·`BIO_ctrl(bio, 3, 0, &ptr)`. 모든 함수에 `restype`·`argtypes` 를 적는다 (포인터는 `c_void_p`). 열쇠 파일을 먼저 임시 이름으로 쓰고 둘을 `os.replace`.
  - `ensure(folder, run=subprocess.run) -> (cert_path, key_path, fingerprint)` - 두 파일이 있고 `ssl.SSLContext.load_cert_chain` 이 받으면 그대로. 아니면 **자식 프로세스**로 만든다: `[sys.executable, "-E", "-s", <local_cert.py>, "--make", folder]`, 30초, 창 없음. (ctypes 를 잘못 부르면 예외가 아니라 프로세스가 죽는다 - 서버가 같이 죽지 않게.) 그래도 안 되면 `CertError("휴대폰 포트의 인증서를 만들지 못했습니다.")`.
  - `fingerprint(cert_path) -> str` - DER 의 SHA-256 소문자 hex.
- Produces (`local_phone`):
  - `tls_context(cert, key) -> ssl.SSLContext` - `PROTOCOL_TLS_SERVER`, `minimum_version = TLSv1_2`, `set_ciphers("ECDHE+AESGCM:ECDHE+CHACHA20")`, `OP_NO_RENEGOTIATION`.
  - `qr_text(hosts, port, phone_id, secret: bytes, fingerprint) -> str` - QR 에 싣는 한 줄 (꼴은 Task 3). 시험과 웹 창구가 같이 쓴다.
  - `make_phone_server(service, tls, host="0.0.0.0", port=PHONE_PORT) -> PhoneServer` - `SO_EXCLUSIVEADDRUSE`·`getfqdn` 없는 bind (계획 ① `LocalServer` 와 같다). 값: `MAX_CONN = 16`, `MAX_PER_IP = 4`, `REQ_PER_MIN = 60`, `HANDSHAKE_SEC = 5`, `READ_SEC = 5`, `BODY_MAX = 2048`, `BAD_LIMIT = 10`, `BAD_SEC = 600`. **TLS 악수는 연결마다 일하는 스레드에서** 한다 (듣는 소켓을 감싸지 않는다 - 악수를 끄는 연결 하나가 받기 고리를 세운다). 보낸 쪽 주소는 `PhoneServer.peer_ip(client_address) -> str` 한 곳에서 읽는다 (시험이 바꿔 끼워 여러 주소를 흉내 낸다).
  - `PhoneHandler` - `server_version = "AP"`, `sys_version = ""`, 요청마다 로그 안 찍음. 모든 응답 `Content-Type: application/json; charset=utf-8`·`Cache-Control: no-store`·`Connection: close`, 본문에 `now_ms`. 확인 차례: 보낸 쪽 주소 → 연결·요청 수 → 경로·방법(셋 아니면 404 `{"error": "not_found"}`, 질의가 붙어도 404) → `Content-Length`(POST 에 없으면 400 `bad_request`, 2048 넘으면 읽지 않고 413 `too_large`) → 막힌 주소 429 `too_many` → 머리글 `X-AP-Phone`·`X-AP-Time`·`X-AP-Nonce`·`X-AP-Sign` → 서명 → nonce → 시각. 없는 휴대폰·틀린 서명·다시 온 nonce 는 같은 401 `{"error": "unauthorized"}` (서명 없음), **서명은 맞고 시각만 ±120초 밖**이면 401 `{"error": "clock", "now_ms"}` (응답 서명 있음 - 앱이 차이를 맞추고 한 번 다시 보낸다). 서명을 확인한 뒤의 응답에는 `X-AP-Sign: response_mac(…)`.
    - `POST /phone/v1/pair` 본문 `{rand(base64url 43자 = 32바이트), os("android"|"ios"), app_version(20자까지), device(40자까지)}`, 서명 열쇠 = `pair_key(짝 열쇠)`, 시각은 보지 않는다 (한 번·5분이 지킨다). 맞으면 `sign_key(짝 열쇠, rand)` 로 `Phones.add`, 짝 열쇠를 버리고 200 `{ok: true, phone_id, label, senders: [..], now_ms}` - 이 응답은 **새 서명 열쇠**로 서명한다 (서버가 같은 열쇠를 만들었다는 증거). 살아 있는 짝짓기가 없거나 번호가 다르거나 서명이 틀리면 401 `unauthorized` (`Pairing.fail()`).
    - `GET /phone/v1/request` → 200 `{open: false, now_ms}` 또는 `{open: true, req_id, site, senders: [..], left_ms, now_ms}`. `Phones.seen(id)`.
    - `POST /phone/v1/code` 본문 `{req_id, code, sender, sms_at}` → `Desk.submit` 의 결과 그대로: 200 `{ok: true, now_ms}` 또는 `{error: <코드>, now_ms}`.
  - `class Gate(service, folder, run=None, host=None, port=None)` - `service.gate`.
    - `sync()` - `phones.count() > 0` 이거나 짝짓기가 `waiting` 이면 `open()`, 아니면 `close()`. 서버 시작·짝짓기 시작/취소/만료(5초 고리)·휴대폰 지우기 뒤에 부른다.
    - `open()` 차례: `local_cert.ensure` → 방화벽 규칙 확인·만들기 → bind → 스레드. 이미 열려 있으면 아무것도 안 한다. 규칙을 못 만들면 **bind 하지 않는다** (규칙 없이 들으면 윈도우가 '액세스 허용' 창을 띄우고, 누르면 python 전체가 공용 망까지 열린다). 실패는 `GateError(code, 사람 말)`: `cert`, `firewall`, `port-in-use`("휴대폰 포트 8782 을(를) 다른 프로그램이 사용하고 있습니다."), `public-network`.
    - `close()` - 듣기를 끝내고, 휴대폰이 0대면 규칙도 지운다.
    - 방화벽 (모두 `run(args)` 로, 결과는 종료 코드만 본다): `firewall_has()` = `netsh advfirewall firewall show rule name="AUTOPILOT Phone OTP"`, `firewall_add()` = `netsh advfirewall firewall add rule name="AUTOPILOT Phone OTP" dir=in action=allow protocol=TCP localport=8782 profile=private,domain program="<sys.executable>" enable=yes`, `firewall_remove()` = `… delete rule name="AUTOPILOT Phone OTP"`. `dev_env("RPA_PHONE_NO_FIREWALL") == "1"` 이면 건너뛴다 (`firewall: "skipped"`).
    - `lan_info() -> [{"ip", "category": "private"|"domain"|"public"|"unknown"}]` - PowerShell 한 번(`Get-NetIPAddress -AddressFamily IPv4` + `Get-NetConnectionProfile`, 인코딩한 명령·창 없음 - `rpa_settings.list_processes` 와 같은 방식)으로 이 PC 의 IPv4 주소와 그 망의 종류. 127·169.254 는 뺀다. 이름 풀이(DNS)를 쓰지 않는다. QR 에는 `private`·`domain` 인 주소만 넷까지 싣고, 주소가 모두 `public` 이면 `GateError("public-network", "이 PC의 네트워크가 '공용'으로 설정되어 있어 휴대폰을 연결할 수 없습니다. 윈도우 설정 → 네트워크 및 인터넷에서 네트워크 프로필을 '개인'으로 변경한 뒤 다시 시도하여 주십시오.")`.
    - `status() -> {"open", "port", "firewall": "ok"|"failed"|"skipped"|"none", "hosts": [..], "fingerprint"|None}`.
  - **방화벽 규칙은 로컬 서버가 만든다** (설계 7절 조건 2 는 '설치 마법사가' 라고 적었다 - 바꿈, Claude 판단: 마법사는 휴대폰을 쓸지 모르고, 서버는 감독이 관리자 권한 작업(`HighestAvailable`)으로 띄워 `netsh` 를 부를 수 있다). 관리자 권한이 아니어서 실패하면 화면에 까닭과 위 `add rule` 명령 한 줄을 보여 준다 (PC 관리자가 한 번 실행하면 다음부터 `firewall_has()` 가 참).
- Produces (`tests/fake_phone_local.py`): `class FakePhone(qr_text)` - `pair(os="android", app_version="test", device="Fake") -> dict`, `request() -> dict`, `send_code(req_id, code, sender, sms_at=None) -> (status, dict)`, `call(method, path, body=None, key=None, ts=None, nonce=None, headers=None, sign=True) -> (status, headers, dict)`(틀린 요청을 만드는 데 쓴다), `class PinError(Exception)`. 연결하면 **요청을 보내기 전에** 서버 인증서 DER 의 SHA-256 을 QR 의 `fp` 와 견주고, 다르면 `PinError`. 응답 서명이 틀려도 예외. 표준 라이브러리만 쓴다 (앱 만드는 사람의 본보기).

- [ ] **Step 1: 실패하는 시험** `tests/test_phone_gate.py` (포트는 `127.0.0.1:0`, `run` 은 인자를 모으는 가짜):
  - 인증서: `ensure` 가 두 파일을 만들고 지문이 hex 64자, 다시 부르면 같은 지문(다시 만들지 않음), 열쇠 파일을 깨뜨리면 새로 만들고 지문이 바뀜, 자식이 실패하면 `CertError`, `D:\AX\runtime\python\python.exe` 가 있으면 그것으로도 `--make` 한 번 (없으면 건너뜀 - 그 폴더에는 쓰지 않는다).
  - 열고 닫기 (Review Focus 1): 휴대폰 0대·짝짓기 없음 → `sync()` 뒤 `status()["open"]` False 이고 `run` 에 `add rule` 이 없다. 짝짓기 시작 → 열림·`add rule` 인자가 위 글자 그대로. 짝짓기 취소 → 닫힘·`delete rule`. `add rule` 이 실패(종료 코드 1) → `GateError("firewall")` 이고 그 포트에 연결이 안 된다. 주소가 모두 `public` → `GateError("public-network")`.
  - 창구 (Review Focus 2): `FakePhone` 으로 짝지은 뒤 `request()` 200. 같은 포트에 `/`·`/api/login`·`/api/session`·`/db/apps/otp/codes/c1/<id>/current.json`·`/fs/runs/c1/items`·`/index.html`·`/phone/v1/request?x=1`·`/phone/v1/%2e%2e/api/session`·`PUT /phone/v1/code`·`OPTIONS /phone/v1/request` → 모두 404 `not_found`·서명 머리글 없음. TLS 없이 보낸 `GET / HTTP/1.1` → 응답 없이 닫힘. 127.0.0.1:8781 쪽 서버 소켓의 주소가 `127.0.0.1` 이다.
  - 인증 (Review Focus 3·4): 틀린 서명·없는 휴대폰 번호가 같은 401 본문, 같은 nonce 두 번째 401, 5분 전 시각 + 맞는 서명 → 401 `clock` 과 `now_ms`·응답 서명 있음, 휴대폰을 지운 뒤 옛 열쇠 401, 틀린 서명 10번 뒤 맞는 요청도 429 → 가짜 시계 601초 뒤 200, 다른 주소로 센 것은 영향 없음(가짜 주소 주입).
  - 짝짓기: 맞는 QR 로 한 번 200, 같은 QR 두 번째 401, 301초 뒤 401, 틀린 서명 5번 뒤 맞는 것도 401(취소됨), 짝지은 뒤 `pair_key` 로 서명한 `request` 는 401 (QR 만으로는 그 뒤 요청을 못 만든다 - Review Focus 6).
  - 묶기 (Review Focus 5): `Content-Length: 5000` → 413 이고 서버가 본문을 읽지 않음, 길이 없는 POST 400, 연결만 하고 아무것도 안 보냄 → 6초 안에 끊김, 악수 뒤 머리글을 한 바이트씩 → 6초 안에 끊김, 그 사이 다른 `FakePhone` 의 `request()` 는 1초 안에 답, 같은 주소 다섯 번째 동시 연결은 바로 닫힘, 주소를 바꿔 가며(`peer_ip` 바꿔 끼움) 열일곱 번째도 바로 닫힘, 휴대폰 포트에 빈 연결을 상한까지 걸어 두어도 8781 의 `GET /api/session` 은 답한다.
  - 기록: 서버 기록 파일에 짝 열쇠·서명 열쇠·인증번호·`rand` 가 없다.
- [ ] **Step 2: 실패 확인.**
- [ ] **Step 3: 구현.** 주소·요청 수 표는 1000개까지만 기억한다. `Gate` 의 열고 닫기는 잠금 하나로.
- [ ] **Step 4: 통과 확인** + Global Constraints 의 시험.
- [ ] **Step 5: 커밋** - "스탠드얼론 ④ Task 2 - 휴대폰 포트(HTTPS·자체 서명 인증서·지문), 방화벽 규칙, 쓸 때만 열기".

### Task 3: 업체 웹 '휴대폰' 칸 · QR 짝짓기

**Files:**
- Create: `firebase/web/qr.js`, `firebase/web/vendor/qrcode.js` (+ `firebase/web/vendor/LICENSE-qrcode-generator.txt`)
- Modify: `firebase/agent/local_web.py` (`web.phone = service`, 길 셋), `firebase/web/data-local.js`, `firebase/web/rpa-settings.js` (카드), `tests/test_local_web_api.py`, `tests/check_web_local.py`
- Test: 위 두 시험 파일

**Interfaces:**
- Consumes: Task 1 `Phones`·`Pairing`·`parse_senders`, Task 2 `Gate`·`GateError`, 계획 ② `Web._routes`·`_auth(h, touch, admin)`·`_Fail`·오류 꼴 `{"code", "message"}`.
- Produces (`/api`, 모두 admin 만 - viewer 는 403 `PERMISSION_DENIED`):

| 주소 | 하는 일 |
|---|---|
| `GET /api/phones` | `{phones: Phones.list(지금 지문), gate: Gate.status()}` |
| `POST /api/phone-pair` `{label, owner?, senders?}` | `Gate.open()`(주소·방화벽·인증서) → `Pairing.start` → `{qr, phone_id, expires_in: 300, hosts, port, fingerprint}`. 이름이 비었거나 발신번호 꼴이 틀리면 400 `invalid-argument`, 20대면 400, `GateError` 는 409 `phone/<code>` 와 그 글 (`phone/firewall` 은 글 끝에 `add rule` 명령) |
| `GET /api/phone-pair` | `Pairing.state()` - 화면이 2초마다 묻는다. **미사용 시계를 되돌리지 않는다** (계획 ② 의 '사람이 한 일' 이 아니다) |
| `DELETE /api/phone-pair` | 취소 → `Gate.sync()` |
| `POST /api/phones/<id>` `{label?, owner?, senders?}` | 이름·담당자·허용 발신번호 고치기 (`senders` 가 빈 글이면 제한 없음) |
| `DELETE /api/phones/<id>` | 지우기 → 그 휴대폰의 요청·번호 자리 지움 → `Gate.sync()` → `{gate}` |

  - QR 글 (한 줄, 이 차례 그대로): `autopilot-phone://pair?v=1&h=<주소,주소>&p=8782&id=<phone_id>&k=<짝 열쇠 base64url 43자>&fp=<지문 hex 64자>`. `GET /api/phone-pair` 는 QR 을 다시 주지 않는다 (**한 번만** - 화면을 새로 고치면 다시 [휴대폰 추가]).
  - 짝짓기 시작·취소·연결됨·휴대폰 지움은 `local_server.log` 에 휴대폰 번호·이름만 남긴다.
- `data-local.js`: `listPhones()`, `startPhonePair({label, owner, senders})`, `phonePairState()`, `cancelPhonePair()`, `updatePhone(id, {label, owner, senders})`, `removePhone(id)`.
- `qr.js`: `export function qrSvg(text) -> SVGElement` (오류 정정 M, 여백 4칸, 검정·흰색 고정 - 어두운 바탕에서도 읽히게). `vendor/qrcode.js` = MIT `qrcode-generator`(Kazuhiko Arase) 의 `qrcode.js` 한 파일을 그대로 넣고 끝에 `export default qrcode;` 한 줄만 더한다 (받은 버전·받은 날·고친 줄을 파일 머리에 적는다). **바깥 CDN 을 부르지 않는다** - 계획 ② 의 CSP(`default-src 'self'`) 그대로 통과해야 한다 (canvas·`data:` 그림 없이 SVG 요소로 그린다). 스탠드얼론에서만 `import("./qr.js")` (일반 버전 화면은 이 파일을 받지 않는다).
- 화면 - 환경설정의 왼쪽 열 끝에 `<h3 class="grp">휴대폰 인증</h3>` + `<div class="card hide" id="phone-card">` (`c.edition === "standalone"` 일 때만 보인다. 환경설정 메뉴가 이미 관리자 전용이다):
  - 머리 `휴대폰` + `#phone-meta` ("2대 · 포트 8782 열림" / "등록된 휴대폰 없음 · 포트 닫힘").
  - 안내 `msg`: "쇼핑몰 로그인 인증번호(문자)를 사내 와이파이에 연결된 휴대폰에서 이 PC로 전달합니다. 문자 내용은 전달하지 않으며 인증번호 숫자만 전달합니다."
  - 표 `tbl`: 이름 · 담당자 · 허용 발신번호(없으면 "제한 없음") · 상태("연결됨 · 3분 전" / "연결 기록 없음" / `stale` 이면 "다시 연결 필요") · [수정]·[삭제].
  - 없을 때 `msg`: "등록된 휴대폰이 없습니다. 휴대폰을 등록하지 않으면 인증번호를 PC의 Edge 창에 직접 입력하여야 합니다."
  - 추가 줄 `seg`: 이름(예: 김OO 휴대폰)·담당자·허용 발신번호(쉼표로 구분) 칸 + `<button id="phone-add">휴대폰 추가</button>`.
  - 짝짓기 중(`#phone-pair`): QR + "휴대폰의 '오토파일럿 컨트롤타워' 앱에서 QR 코드를 스캔하여 주십시오. QR 코드는 5분 동안 한 번만 사용할 수 있습니다. (남은 시간 4:32)" + "QR 코드를 촬영하여 다른 사람에게 전달하지 마십시오." + [취소]. 화면을 떠나면 취소한다.
  - 결과 글: 연결 "휴대폰 '김OO 휴대폰'이(가) 연결되었습니다. (Fake · android)", 시간 지남 "QR 코드의 사용 시간이 지났습니다. [휴대폰 추가]를 다시 눌러 주십시오.", 삭제 확인 "휴대폰 '김OO 휴대폰'을(를) 삭제하시겠습니까? 삭제하면 이 휴대폰은 인증번호를 전달할 수 없습니다.", 마지막 휴대폰 삭제 "휴대폰을 삭제하였습니다. 등록된 휴대폰이 없어 휴대폰 포트를 닫았습니다."

- [ ] **Step 1: 실패하는 시험.**
  - `tests/test_local_web_api.py` 에 더하기: viewer 는 여섯 길 모두 403. `POST /api/phone-pair` → `qr` 이 위 꼴(조각 여섯·`k` 43자·`fp` 64자)이고 저장소 파일·기록 파일에 `k` 값이 없다. `GET /api/phone-pair` 에 `qr`·`k` 없음·`waiting`·세션의 미사용 시계가 그대로. `FakePhone(qr).pair()` 뒤 `paired` 와 기기 이름, `GET /api/phones` 에 한 대(열쇠 없음). 이름 없음·발신번호 `12ab` 400. 방화벽 실패(가짜 `run`) → 409 `phone/firewall` 이고 글에 `add rule` 명령. `DELETE /api/phones/<id>` 뒤 그 휴대폰의 `request()` 401·포트 닫힘·`delete rule`. `DELETE /api/phone-pair` 뒤 그 QR 로 `pair()` 401.
  - `tests/check_web_local.py` 에 더하기 (서버와 같은 프로세스에서 `FakePhone` 을 돌린다): 환경설정에 '휴대폰' 카드, [휴대폰 추가] → 카드 안에 `svg`(모듈 수가 `4×버전+17` 꼴, 세 귀퉁이에 찾기 무늬)와 남은 시간, `FakePhone` 이 짝지으면 2~4초 안에 표에 한 줄과 연결 글, 새로 고치면 QR 이 없다, [삭제] 확인 뒤 줄이 없어지고 '포트 닫힘', viewer 로 로그인하면 카드가 없다, **바깥 요청 0·콘솔 오류 0**(CSP 위반 포함)이 그대로.
  - 에뮬레이터 `check_web.py`(일반 버전): 휴대폰 카드가 없고 `qr.js`·`vendor/qrcode.js` 를 받지 않는다 (요청 목록).
- [ ] **Step 2: 실패 확인.**
- [ ] **Step 3: 구현.** `vendor/qrcode.js` 는 npm 의 `qrcode-generator` 꾸러미에서 그 파일 하나만 스크래치 폴더로 받아 훑어본 뒤 옮긴다 (설치 스크립트를 돌리지 않는다, 받은 버전과 sha256 을 커밋 글에).
- [ ] **Step 4: 통과 확인** + Global Constraints 의 시험.
- [ ] **Step 5: 화면 사진을 사용자에게 보인다** (카드·QR 이 뜬 모습 - 사진은 스크래치 폴더에, QR 은 시험용 값).
- [ ] **Step 6: 커밋** - "스탠드얼론 ④ Task 3 - 업체 웹 '휴대폰' 칸·QR 짝짓기 (관리자, 짝 열쇠는 한 번만)".

### Task 4: PC 쪽 - 휴대폰이 없거나 답이 없으면 사람이 5분

**Files:**
- Modify: `otp_relay.py` (`FallbackOtp`·`standalone_relay`), `web_replay.py` (`OtpRetry`·`_otp_code`·`_run_steps`), `web_runner.py` (`_replay_problems`·`action_replay`), `rpa_observer.py` (`_otp_relay`·저장 확인 781행·안내 글)
- Test: `tests/test_otp_fallback.py`

**Interfaces:**
- 지금 코드에서 이미 되는 것 (계획 ① Task 4): `otp_relay.relay_config`·`_client` 가 중계 열쇠로 로컬 서버에 붙고, `phone_list`·`agent_relay`·`PhoneRelay` 는 그대로 돈다. **남은 것**은 ① 서버가 짝지은 휴대폰 표를 내주고 검사하기 (Task 1 에서 끝남) ② 아래의 '안 될 때'.
- Produces (`otp_relay`):
  - `MANUAL_SEC = 300`, `GIVE_UP = "인증번호를 받지 못함"`.
  - `class FallbackOtp(phone=None, manual_sec=MANUAL_SEC, on_manual=None, log=None)` - 재생기에 넘기는 중계 (`open`·`wait`·`close` 는 지금 중계와 같은 꼴). `once = True`, `give_up = GIVE_UP` (재생기가 본다).
    - `open(tick=None)` - `phone` 이 있으면 `phone.open(tick)`. `RuntimeError`·`OSError`·`fb.HttpError` 면 그 까닭을 `log` 로 한 줄 남기고 (`"휴대폰으로 인증번호를 받을 수 없어 직접 입력을 기다립니다. (…)"`) 이번 실행은 사람 입력만. 예외를 올리지 않는다.
    - `wait(req, seconds, tick, field=None)` - 휴대폰이 살아 있으면 `seconds`(재생기의 120초) 동안 휴대폰 번호를 기다리되 **그동안에도 칸에 사람이 넣은 번호(숫자 4~8자리가 1초 그대로)를 받는다** (둘 중 먼저). 그 뒤 `on_manual()` 을 한 번 부르고 `manual_sec` 동안 칸만 본다 (`ManualOtp` 와 같은 판단). 끝내 없으면 None. 재발송하지 않는다.
    - `close(req)` - 휴대폰 요청을 열었으면 `phone.close(req)`.
  - `standalone_relay(phone_id, senders, site, on_manual=None, log=None) -> FallbackOtp` - `phone_id` 와 `senders` 가 있으면 `agent_relay` 를 시도하고 (`RuntimeError` 면 사람 입력만), 없으면 바로 사람 입력만.
- `web_replay`:
  - `OtpRetry(why, rejected=False, final=None, mail=False, once=False)`. `_otp_code` 가 번호를 못 받았을 때 중계에 `once` 가 있으면 `OtpRetry(GIVE_UP 글, final=self.otp.give_up, once=True)`. `_run_steps` 는 `e.once` 면 횟수가 남아도 다시 하지 않고 그 단계를 `fail`·사유 `final` 로 끝낸다 (요청은 지운다).
  - 사이트가 번호를 **거절**한 경우(`rejected=True`)는 두 버전 모두 지금 규칙(모두 3번, '인증번호 받기' 부터) 그대로 둔다 (Claude 판단 - 사람이 잘못 친 번호를 다시 넣을 기회).
- `web_runner` (스탠드얼론일 때만 - `otp_relay._standalone()`):
  - `_replay_problems`: 인증번호 단계가 있는데 `Phone`·`SmsSenders` 가 없어도 문제로 보지 않는다 (일반 버전은 지금 글 그대로 막는다).
  - `action_replay`: `rp.otp = otp_relay.standalone_relay(site.get("Phone"), site.get("SmsSenders"), p["name"], on_manual=…, log=…)`. `on_manual` 은 로그 `  [<이름>] Edge 창의 인증번호 칸에 인증번호를 직접 입력하여 주십시오. (5분 안)` 과 `status.metric(f"{name}:otp_manual", "인증번호 직접 입력 대기", 300, unit="초")`. 휴대폰이 있으면 지금 로그 "인증번호는 휴대폰 …(으)로 수신합니다." 그대로.
  - 실패하면 지금 길 그대로 `RuntimeError(f"{i}단계에서 멈췄습니다: 인증번호를 받지 못함")` → `run_site` 가 그 사이트만 `step_fail` 하고 다음 사이트로 간다 (실행 기록·현황에 사유가 남는다 - 새 코드 없음, 시험으로 확인).
  - 병렬 수집의 인증 차례: 휴대폰 없는 사이트는 지금도 `gates.lock("")` 하나를 같이 쓴다 → 사람에게 한 번에 한 사이트만 묻는다 (바꾸지 않는다).
- `rpa_observer` (스탠드얼론일 때만): 미리보기 `_otp_relay` 가 `standalone_relay` 를 쓴다 (`on_manual` 글 "미리보기 창의 인증번호 칸에 휴대폰으로 받은 번호를 넣어 주십시오 (5분 안)."). 저장 확인(781행)은 인증 휴대폰이 없어도 통과. 안내 글 `SMS_HINT` 대신 "문자 인증 사이트는 인증 휴대폰과 발신번호를 정해 주십시오. 정하지 않으면 실행할 때 Edge 창의 인증번호 칸에 직접 입력하여야 합니다. (여러 개는 쉼표로)". 휴대폰 목록 안내의 '관리 화면' 은 '업체 웹 환경설정의 휴대폰' 으로.

- [ ] **Step 1: 실패하는 시험** `tests/test_otp_fallback.py` (`tests/test_otp_replay.py` 의 가짜 사이트·`FakeRelay` 방식 그대로, 기다림 값은 시험에서 짧게 넣는다):
  - 휴대폰이 번호를 줌 → 통과, `on_manual` 안 불림.
  - 휴대폰이 조용함 → `seconds` 뒤 `on_manual` 한 번 → 다른 스레드가 칸에 번호를 넣음 → 통과.
  - 휴대폰을 기다리는 중에 칸에 넣음 → `seconds` 를 다 기다리지 않고 통과.
  - 휴대폰 없음(`standalone_relay(None, [], …)`) → 바로 사람 입력.
  - `phone.open` 이 `RuntimeError(otp_relay.DENIED)` → 예외 없이 사람 입력, 로그 한 줄.
  - 아무도 안 넣음 → 재생 결과 마지막이 `fail`·"인증번호를 받지 못함", '인증번호 받기' 단계는 **한 번만** 눌림(사이트가 보낸 번호 수 1), `close` 불림.
  - 사이트가 거절 → 지금처럼 다시 (모두 3번).
  - `web_runner._replay_problems`: 스탠드얼론 + 인증번호 단계 + 휴대폰 없음 → `[]`, 일반 → 지금 글.
  - 일반 버전: `action_replay` 가 `agent_relay` 를 부르고 `FallbackOtp` 를 만들지 않는다 (`_standalone` 을 거짓으로).
  - 로그·결과 글에 인증번호 숫자가 없다.
- [ ] **Step 2: 실패 확인.**
- [ ] **Step 3: 구현.**
- [ ] **Step 4: 통과 확인** + Global Constraints 의 시험 + `tests\test_web_replay.py`·`tests\test_parallel_collect.py`·`tests\test_observer_edit.py`.
- [ ] **Step 5: 커밋** - "스탠드얼론 ④ Task 4 - 휴대폰이 없거나 답이 없으면 Edge 인증 칸에 사람이 5분 (그 사이트만 실패)".

### Task 5: 약속 문서 · 휴대폰 흉내 끝에서 끝까지 · 바깥 연결 0

**Files:**
- Create: `docs/phone-local-contract.md`, `tests/check_phone_local.py`
- Modify: `tests/fake_phone_local.py` (`on_sms`·`--vectors`), `docs/superpowers/plans/2026-11-23-standalone-index.md` (상태), `docs/server-move-handoff.md` (휴대폰 줄에 스탠드얼론 약속 문서 자리 한 줄)
- Test: `tests/check_phone_local.py`

**Interfaces:**
- Consumes: 위 모두. 새 실행 코드 없음 (고칠 것이 나오면 해당 작업 파일을 고친다).
- `tests/fake_phone_local.py` 에 더하기: `FakePhone.on_sms(sender, body) -> str|None` - 앱이 할 일 그대로: `sms_watch.extract_auth_code(body)` 로 숫자만 → 없으면 끝 → `request()` → `open` 이 아니거나 `otp_relay.sender_number(sender)` 가 `senders` 에 없으면 끝 → `send_code`. `python tests/fake_phone_local.py --vectors` = 정해 둔 입력(짝 열쇠 `bytes(range(32))`, `rand` `bytes(range(32, 64))`, 번호 `ph_0a1b2c3d`, 시각 `1795000000000`, nonce `000102030405060708090a0b0c0d0e0f`)으로 `pair_key`·`sign_key`·세 요청의 서명·응답 서명을 찍는다.
- `docs/phone-local-contract.md` (앱 만드는 사람에게 넘기는 약속 - 원본은 이 저장소, 휴대폰 저장소의 `CONTRACT.md` 에 옮겨 적는다). 넣을 것:
  1. 한눈에 (일반 버전과 무엇이 같고 다른가 - 뜻은 같고 길만 Firebase 대신 PC).
  2. QR 글의 꼴과 조각 여섯, 주소가 여럿이면 차례로 3초씩 해 본다.
  3. 지문 고정: 인증서 이름·기관·날짜를 믿지 않고 **DER 의 SHA-256 이 QR 의 `fp` 와 같을 때만** 요청을 보낸다 (안드로이드 `X509TrustManager` 를 직접 만들고 `HostnameVerifier` 는 통과 - 지문이 그 일을 한다). 다르면 아무것도 보내지 않고 "PC 를 확인할 수 없습니다. 다시 연결(QR)하여 주십시오." TLS 1.2 이상.
  4. 열쇠 만들기 (`pair_key`·`sign_key` 의 식), 짝 열쇠는 짝지은 뒤 버리고 서명 열쇠만 기기의 안전한 저장소에.
  5. 주소 셋 - 머리글 넷, 본문 칸·꼴·길이, 응답, 서명 식(조각 차례·줄바꿈·hex 소문자), 응답 서명 확인, `now_ms` 로 시계 차이 맞추기.
  6. 오류 표: 400 `bad_request`, 401 `unauthorized`(다시 연결 안내)·`clock`(시계 맞추고 한 번 다시), 403 `sender_not_allowed`, 404 `not_found`, 409 `no_request`·`req_mismatch`, 413 `too_large`, 429 `too_many`(10분 뒤).
  7. 지킬 것: 문자가 온 순간에만 묻는다(폴링 없음), 본문을 보내지 않는다, 발신번호는 `+82` → `0`·숫자만, 열린 요청이 없거나 발신번호가 다르면 아무것도 보내지 않는다, 2분.
  8. 예시 값 (`--vectors` 가 찍은 것을 그대로 붙인다) 과 `tests/fake_phone_local.py` 를 본보기로 쓰는 법.
  9. 이번에 하지 않는 것: 아이폰 단축어 (자체 서명 인증서의 지문 확인과 HMAC 서명을 단축어로 할 수 없다 - 설계 7절대로 범위 밖), 푸시, PC 주소가 바뀌었을 때 스스로 찾기 (다시 짝짓는다).

- [ ] **Step 1: 시험 쓰기** `tests/check_phone_local.py` - 임시 `RPA_PROGRAMDATA`, `RPA_EDITION=standalone`, 시험 라이선스, `RPA_PHONE_HOST=127.0.0.1`·빈 포트·`RPA_PHONE_NO_FIREWALL=1`. 로컬 서버(웹 창구 포함)를 띄우고 관리자 계정으로:
  - 짝짓기: `POST /api/phone-pair` → `FakePhone(qr).pair()` → `GET /api/phones` 한 대.
  - 한 바퀴 (일반 버전 `check_phone_relay.py` 와 같은 차례): 요청 없음 → `on_sms` None. `otp_relay.agent_relay(<id>, ["1588-1234"], "가나몰")` 로 열기 → 은행 발신번호 문자 None, 인증번호 없는 문자 None, 맞는 문자 `"482913"` → `relay.wait` 가 그 번호 → 서버에 남은 값의 칸이 다섯(본문 없음) → `relay.close` 뒤 요청·번호 없음 → 닫힌 뒤 `on_sms` None, 억지 `send_code` 409 `no_request`.
  - 2분: 요청을 열고 서버 시계를 121초 뒤로 → `request()` 가 `open: false`, `send_code` 409, 5초 고리 뒤 자리가 비어 있다.
  - 허용 발신번호: 휴대폰에 `15881234` 만 허용 → `agent_relay(<id>, ["15990000"], …).open()` 이 `RuntimeError`.
  - 지문 (Review Focus 7): 다른 폴더(다른 인증서)로 띄운 두 번째 서버의 포트에 같은 QR 로 붙으면 `PinError` 이고 그 서버가 받은 요청이 0.
  - 거절: 틀린 서명·5분 전 시각·같은 nonce 다시·지운 휴대폰 (Review Focus 4).
  - 사람 입력으로 넘어감: 휴대폰을 지운 뒤 `standalone_relay(<옛 id>, …)` 의 `open` 이 예외 없이 사람 입력 쪽.
  - **바깥 연결 0**: 시험 동안 `socket.socket.connect`·`socket.create_connection` 을 감싸 모은 대상이 `127.0.0.1` 뿐이고, `local_phone.py`·`local_cert.py` 소스에 `urllib`·`http.client`·`create_connection` 낱말이 없다.
  - 약속 문서: `docs/phone-local-contract.md` 의 예시 값이 `--vectors` 의 지금 계산과 같다 (문서와 코드가 어긋나면 실패).
- [ ] **Step 2: 실행** → 드러난 것은 해당 작업 파일을 고친다 (시험을 고치지 않는다).
- [ ] **Step 3: 약속 문서 쓰기** → 시험 통과.
- [ ] **Step 4: 전체 시험** - 스탠드얼론 시험 모두, Global Constraints 의 일반 버전 시험, 에뮬레이터 `check_web.py`·`check_phone_relay.py`. `graphify update .`. 계획 목록의 ④ 상태를 고친다.
- [ ] **Step 5: 커밋** - "스탠드얼론 ④ Task 5 - 휴대폰 약속 문서·휴대폰 흉내 끝에서 끝까지·바깥 연결 0".
- [ ] **Step 6: 사용자에게 알린다** - 맥 세션(휴대폰 저장소)에 넘길 것: `docs/phone-local-contract.md`, `tests/fake_phone_local.py`, 예시 값. 다른 세션에 직접 보내지 않는다.

---

## 계획 ③(설치·빌드)에 기대는 것

1. 감독이 로컬 서버를 **관리자 권한**(자동 시작 작업 `HighestAvailable`)으로 띄운다 - 방화벽 규칙 만들기(Task 2)가 여기에 기댄다.
2. 스탠드얼론 설치본의 파일 목록·변조 감지 목록에 `firebase/agent/local_phone.py`·`local_cert.py`·`firebase/web/qr.js`·`firebase/web/vendor/qrcode.js`·`vendor/LICENSE-qrcode-generator.txt` 가 들어간다. 내장 파이썬의 `DLLs\libcrypto-3.dll`·`_ctypes.pyd`·`_ssl.pyd` 를 빼지 않는다.
3. 설치 마무리의 폴더 권한 잠금이 `install_root()\standalone\` 까지 닿고, 계획 ③ Task 의 `local_server.lock_key_files`(`agent.key`·`relay.key`·`accounts.json`) 가 `phone_key.pem`·`phones.json` 도 관리자·SYSTEM 만 남긴다 (중계 열쇠처럼 다른 계정에 읽기를 더하지 않는다). 샌드박스의 권한 확인 목록에도 두 파일을 더한다.
4. 덮어 설치가 `standalone\` 폴더를 남긴다 (지우면 인증서가 바뀌어 모든 휴대폰을 다시 짝짓는다). **제거** 때는 `netsh advfirewall firewall delete rule name="AUTOPILOT Phone OTP"` 를 부른다.
5. 샌드박스 `--standalone` 에 `tests/check_phone_local.py` 를 설치본으로 한 번 돌릴지는 계획 ③ 이 정한다 (내장 파이썬에서 인증서가 만들어지는지가 거기서 한 번 더 확인된다).

## 계획 ⑤(문서)에 넘길 것

- 사용설명서: 망 조건 셋(휴대폰과 PC 가 서로 닿는 사내 와이파이·무선 격리나 손님용 와이파이는 안 됨 / 방화벽 규칙은 프로그램이 [휴대폰 추가] 때 만든다·망이 '공용' 이면 '개인' 으로 / PC 주소가 바뀌면 다시 짝짓기 - 주소 고정을 추천), QR 을 촬영해 전달하지 않기, 휴대폰을 잃어버리거나 바꾸면 [삭제], 아이폰과 휴대폰 없는 사이트는 Edge 칸에 직접 입력(5분).
- 보안 자료: 사내망에 여는 것은 포트 하나·주소 셋, HTTPS·지문 고정, 번호만·2분·쓰면 지움, 서명·시도 제한, 쓰지 않으면 포트와 규칙이 없음, 공개 코드 `qrcode-generator`(MIT).

## 사용자 확인 (기본값으로 진행하고, 다르게 정하면 고친다)

1. **방화벽 규칙을 설치 마법사가 아니라 로컬 서버가 [휴대폰 추가] 때 만든다** (설계 7절 문장과 다름). 기본값: 서버가 만든다 - 휴대폰을 쓰지 않는 PC 에는 규칙이 없다.
2. **QR 생성 코드**로 공개 코드 `qrcode-generator`(MIT) 파일 하나를 저장소·설치본에 넣는다 (바깥에서 불러오지 않는다). 기본값: 넣는다 - 보안 자료의 공개 코드 목록에 한 줄 는다.
3. **공용(Public)으로 잡힌 망**에서는 휴대폰 포트를 열지 않고 '개인으로 바꿔 주십시오' 안내만 한다. 윈도우는 새 망을 흔히 공용으로 잡으므로 설치 때 업체 PC 담당자가 바꿔야 할 수 있다. 기본값: 열지 않는다.
4. **기다리는 시간**: 휴대폰 2분 + 사람 5분 = 한 사이트에 길면 7분 (휴대폰이 없으면 5분). 예약 실행이 그만큼 길어진다. 기본값: 설계대로.
5. **사이트가 번호를 거절**했을 때 다시 하기(모두 3번, '인증번호 받기' 다시 누름)는 일반 버전과 같게 둔다. '받지 못함' 만 재발송 없이 끝낸다. 기본값: 이대로.
6. **포트 8782 고정**, 인증서 유효 10년 (다시 만들면 모든 휴대폰 다시 짝짓기). 업체 망 정책으로 다른 포트가 필요하면 그때 설정 칸을 더한다.
7. **실제 휴대폰 확인**은 앱(맥 세션)이 나온 뒤 사용자와 한다: QR 이 실제로 읽히는지, 사내 와이파이에서 PC 에 닿는지, 안드로이드 버전별 TLS.
8. **아이폰**은 이번 창구를 쓸 수 없다 (단축어가 자체 서명 인증서·서명을 못 한다). 아이폰을 쓰는 직원은 Edge 칸에 직접 넣는다. 기본값: 범위 밖 (설계 7절).
