# 스탠드얼론 휴대폰 창구 약속 (앱 ↔ PC 로컬 서버)

- 대상: 휴대폰 앱 '오토파일럿 컨트롤타워' (비공개 저장소 `TE-JA-VA/RPA-PhoneRelay`) 를 만드는 사람
- 원본: 이 파일 (`docs/phone-local-contract.md`, 오토파일럿 저장소). 휴대폰 저장소의 `CONTRACT.md` 에 옮겨 적는다. 바꿀 때는 이 파일과 서버 코드·시험을 먼저 고친다.
- 서버 코드: `firebase/agent/local_phone.py` (창구·규칙), `firebase/agent/local_cert.py` (인증서)
- 본보기 코드: `tests/fake_phone_local.py` (표준 라이브러리만 쓰는 앱 흉내 - 서버 코드를 불러오지 않고 열쇠·서명을 따로 계산한다)
- 끝에서 끝까지 시험: `tests/check_phone_local.py`, `tests/test_phone_gate.py`

## 1. 한눈에

| | 일반 버전 (클라우드) | 스탠드얼론 (이 문서) |
|---|---|---|
| 휴대폰이 붙는 곳 | Firebase RTDB `apps/otp` | 그 업체 PC 의 로컬 서버, 사내 와이파이로 HTTPS `8782` |
| 휴대폰 확인 | 휴대폰 계정 로그인 (Firebase Auth) | QR 로 한 번 짝짓기 → 서명 열쇠로 요청마다 HMAC 서명 |
| 서버 확인 | 구글 인증서 | PC 가 처음 만든 자체 서명 인증서 - QR 의 지문(`fp`)과 같을 때만 |
| 열린 요청 보기 | `apps/otp/requests/<cid>/<phoneId>/current` 읽기 | `GET /phone/v1/request` |
| 번호 보내기 | `apps/otp/codes/<cid>/<phoneId>/current` 쓰기 | `POST /phone/v1/code` |

뜻은 같다: 휴대폰은 **자기 몫의 열린 요청**만 보고, 문자가 오면 **인증번호 숫자·발신번호·받은 시각만** 보낸다. 요청은 2분 동안만 열려 있고, 요청의 발신번호 목록에 있는 번호에서 온 문자만 보낼 수 있다. PC 는 번호를 쓰면 지운다. 문자 본문은 어디에도 보내지 않는다.

## 2. QR (짝짓기)

PC 의 업체 웹 → 환경설정 → '휴대폰 인증' → [휴대폰 추가] 를 누르면 카드 안에 QR 이 뜬다. QR 의 글은 한 줄이고 조각 여섯이 이 차례로 온다:

```
autopilot-phone://pair?v=1&h=<주소,주소>&p=<포트>&id=<휴대폰 번호>&k=<짝 열쇠>&fp=<지문>
```

| 조각 | 꼴 | 뜻 |
|---|---|---|
| `v` | `1` | 약속 버전. 1 이 아니면 읽지 않는다 |
| `h` | IPv4 주소를 쉼표로, 1~4개 | 그 PC 의 사내망 주소 ('개인'·'도메인' 네트워크의 것만). 여럿이면 **차례로 3초씩** 연결해 보고, 닿은 주소를 기억해 다음부터 먼저 쓴다 |
| `p` | 숫자 | 포트 (보통 `8782`) |
| `id` | `ph_` + 소문자 hex 8자 (`^ph_[0-9a-f]{8}$`) | 이 휴대폰의 번호 (서버가 정한다) |
| `k` | base64url (채움 `=` 없음) 43자 = 32바이트 | 짝 열쇠. **5분 동안 한 번만** 쓸 수 있다. 짝지은 뒤 버린다 |
| `fp` | 소문자 hex 64자 | PC 인증서 DER 의 SHA-256 (3절) |

예: `autopilot-phone://pair?v=1&h=192.168.0.12&p=8782&id=ph_0a1b2c3d&k=AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8&fp=<64자>`

PC 주소가 바뀌면 (공유기가 다른 주소를 주면) 다시 짝짓는다 - 앱이 스스로 PC 를 찾지 않는다 (9절).

## 3. 지문 고정 (반드시)

- 인증서의 이름·발급 기관·날짜는 **믿지 않는다**. 연결하자마자, **요청을 보내기 전에** 서버 인증서 DER 의 SHA-256 을 소문자 hex 로 만들어 QR 의 `fp` 와 견준다. 같을 때만 요청을 보낸다.
- 다르면 아무것도 보내지 않고 연결을 닫고 사용자에게: **"PC 를 확인할 수 없습니다. 다시 연결(QR)하여 주십시오."**
- 안드로이드: `X509TrustManager` 를 직접 만들어 `checkServerTrusted` 에서 체인의 첫 인증서(`chain[0].encoded`)의 SHA-256 을 견주고, `HostnameVerifier` 는 통과시킨다 (이름 확인은 지문이 대신한다). 시스템 기본 신뢰 목록으로 검사하지 않는다.
- TLS 1.2 이상. 서버는 1.2 에서 `ECDHE+AESGCM`·`ECDHE+CHACHA20` 만 받는다 (1.3 은 기본 암호 목록). 인증서는 P-256(ECDSA)·SHA-256·유효 10년, CN `AUTOPILOT Phone Gate`.
- PC 가 인증서를 다시 만들면 지문이 바뀐다 - 그 PC 의 모든 휴대폰을 다시 짝짓는다 (화면에 '다시 연결 필요').

## 4. 열쇠

```
pair_key = lowercase_hex( SHA-256( "ap1 phone pair\n" + 짝 열쇠 32바이트 ) )
sign_key = lowercase_hex( SHA-256( "ap1 phone key\n" + 짝 열쇠 32바이트 + rand 32바이트 ) )
```

- 문자열 부분은 UTF-8 바이트, `\n` 은 줄바꿈 한 바이트(0x0A). 짝 열쇠는 QR 의 `k` 를 base64url 로 푼 32바이트.
- `rand` 는 휴대폰이 짝지을 때 안전한 난수로 새로 만든 32바이트 (`SecureRandom`).
- `pair_key` 는 짝짓기 요청 하나에만 쓴다. 짝지은 뒤에는 `sign_key` 만 기기의 안전한 저장소(안드로이드 Keystore 로 암호화한 저장소)에 두고 **짝 열쇠·`pair_key`·`rand` 는 버린다**. `rand` 가 섞여 있어 QR 사진만으로는 `sign_key` 를 만들 수 없다.
- 열쇠는 64자 hex **글** 이다. HMAC 의 열쇠로 쓸 때는 그 글의 UTF-8 바이트(64바이트)를 쓴다 (hex 를 풀지 않는다).

## 5. 주소 셋

이 포트가 아는 주소는 셋뿐이다. 경로는 글자 그대로 (질의 `?…`·`%xx`·`..` 를 붙이면 404).

| 방법·경로 | 서명 열쇠 | 본문 |
|---|---|---|
| `POST /phone/v1/pair` | `pair_key` | `{"rand", "os", "app_version", "device"}` |
| `GET /phone/v1/request` | `sign_key` | 없음 (빈 본문) |
| `POST /phone/v1/code` | `sign_key` | `{"req_id", "code", "sender", "sms_at"}` |

### 5.1 머리글 (요청마다 넷)

| 머리글 | 값 |
|---|---|
| `X-AP-Phone` | 휴대폰 번호 (`ph_…`) |
| `X-AP-Time` | 보내는 시각, 1970-01-01 UTC 부터 ms, 십진 숫자 글 (`now_ms` 로 맞춘 시각 - 5.4) |
| `X-AP-Nonce` | 요청마다 새 난수, 소문자 hex 16~64자 (권장 32자 = 16바이트). 같은 값을 두 번 쓰지 않는다 |
| `X-AP-Sign` | 아래 서명, 소문자 hex 64자 |

POST 는 `Content-Type: application/json` 과 `Content-Length` 를 꼭 싣는다 (없으면 400). 본문은 2048바이트까지 (넘으면 413). 서버는 늘 `Connection: close` 로 답한다 - 요청마다 새 연결.

### 5.2 요청 서명

```
X-AP-Sign = lowercase_hex( HMAC-SHA256( key = 열쇠 hex 글의 UTF-8,
            msg = "ap1" \n "phone-req" \n 휴대폰번호 \n 방법 \n 경로 \n 시각 \n nonce \n 본문SHA256 ) )
```

- 조각 여덟을 이 차례로 `\n`(0x0A) 하나로 잇는다 (끝에 `\n` 없음). 방법은 대문자 (`GET`·`POST`).
- 경로는 보낸 그대로 (`/phone/v1/code`). 시각은 `X-AP-Time` 과 같은 글.
- 본문SHA256 = 보내는 본문 **바이트 그대로** 의 SHA-256 소문자 hex. 빈 본문은 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`. 서명한 뒤 본문을 다시 만들지 않는다 (JSON 직렬화를 한 번 하고 그 바이트로 서명하고 그 바이트를 보낸다).

### 5.3 응답과 응답 서명

- 모든 응답 본문은 JSON 이고 `now_ms` (서버 시각 ms) 가 들어 있다.
- 서버가 요청 서명을 확인한 뒤의 응답에는 `X-AP-Sign` 이 붙는다:

```
X-AP-Sign = lowercase_hex( HMAC-SHA256( key = 열쇠 hex 글의 UTF-8,
            msg = "ap1" \n "phone-res" \n 요청의nonce \n 상태번호 \n 응답본문SHA256 ) )
```

- 앱은 200 응답에 서명이 없거나 틀리면 그 응답을 버린다 (우리 PC 의 답이 아니다). 서명은 그 요청의 nonce 에 묶여 있어 다른 응답을 돌려쓸 수 없다.
- 짝짓기 성공(200) 응답은 **새 `sign_key`** 로 서명돼 온다 - 앱은 자기가 만든 `sign_key` 로 확인해 서버가 같은 열쇠를 만들었는지 본다. 짝짓기의 다른 서명된 응답(400)은 `pair_key` 로.
- 401 `unauthorized`·404·413·429 는 서명 없이 온다 (서버가 요청을 확인하지 못했다).

### 5.4 시계 맞추기

닫힌 망의 PC 는 시계가 틀릴 수 있다. 서버는 `X-AP-Time` 이 서버 시각과 **±120초** 를 넘으면, 서명은 맞을 때 `401 {"error": "clock", "now_ms": …}` (서명 있음) 로 답한다. 앱은 `차이 = now_ms - 휴대폰 시각` 을 기억하고 시각에 더해 **한 번만** 다시 보낸다 (새 nonce). 번호(`POST /phone/v1/code`)를 다시 보낼 때는 본문의 `sms_at` 에도 같은 차이를 더한다 (5.7 - `X-AP-Time` 과 같은 시계). 짝짓기 요청은 시각을 보지 않는다.

### 5.5 `POST /phone/v1/pair`

본문은 정확히 네 칸 (더 있거나 모자라면 400):

| 칸 | 꼴 |
|---|---|
| `rand` | base64url (채움 없음) 43자 = 32바이트 |
| `os` | `"android"` 또는 `"ios"` |
| `app_version` | 1~20자 |
| `device` | 기기 이름 1~40자 (화면에 '연결되었습니다. (기기 · os)' 로 보인다) |

성공: `200 {"ok": true, "phone_id", "label", "senders": [허용 발신번호…], "now_ms"}` (새 `sign_key` 로 서명). 살아 있는 짝짓기가 없거나(5분 지남·이미 씀·취소) 번호가 다르거나 서명이 틀리면 `401 unauthorized` - 사용자에게 "QR 코드를 다시 받아 주십시오." 그 짝짓기의 번호(`id`)로 온 요청의 서명이 다섯 번 틀리면 그 짝짓기는 취소된다 (번호가 다른 요청은 세지 않는다 - 6절의 주소별 거절만).

### 5.6 `GET /phone/v1/request`

- 열린 요청 없음: `200 {"open": false, "now_ms"}`
- 있음: `200 {"open": true, "req_id", "site", "senders": ["15881234", …], "left_ms", "now_ms"}` - `senders` 는 숫자 글 목록, `left_ms` 는 남은 시간.

### 5.7 `POST /phone/v1/code`

본문은 정확히 네 칸 (**문자 본문을 실수로 실으면 칸이 늘어 400** - 서버가 막는다):

| 칸 | 꼴 |
|---|---|
| `req_id` | 열린 요청의 `req_id` 그대로 (`[A-Za-z0-9_-]` 8~64자) |
| `code` | 인증번호 숫자 글 4~8자리 (`"482913"`, 숫자 값이 아니라 글) |
| `sender` | 문자의 발신번호를 7절 규칙으로 바꾼 숫자 글 3~15자리 |
| `sms_at` | 문자를 받은 시각 ms (정수) - `X-AP-Time` 과 같은 시계로 (5.4 의 차이를 더했으면 여기에도 더한다) |

성공 `200 {"ok": true, "now_ms"}`. 실패는 6절 표 (서명 있음).

서버는 `X-AP-Time - sms_at` (보내기 몇 ms 전에 받았나) 을 서버 시각으로 옮겨 요청이 열린 시각과 견준다 - 요청이 열린 시각보다 **30초 넘게 이른 문자**는 `409 old_sms` (지난 문자의 번호). 휴대폰·PC 시계가 틀려도 같은 시계끼리 빼므로 상관없다.

## 6. 오류

| 상태 | `error` | 언제 | 앱이 할 일 |
|---|---|---|---|
| 400 | `bad_request` | 본문 꼴·칸이 틀림, POST 에 Content-Length 없음, JSON 이 아님 | 고칠 때까지 다시 보내지 않는다 (앱 버그) |
| 401 | `unauthorized` | 없는 휴대폰·틀린 서명·다시 쓴 nonce·지운 휴대폰 | 짝짓기가 풀렸다 - "PC 와 연결이 끊겼습니다. 다시 연결(QR)하여 주십시오." |
| 401 | `clock` | 서명은 맞고 시각만 ±120초 밖 (서명 있음) | 5.4 대로 시계를 맞추고 한 번만 다시 |
| 403 | `sender_not_allowed` | 발신번호가 그 요청의 `senders` 에 없음 | 보내지 않는다 (애초에 7절에서 걸러야 한다) |
| 404 | `not_found` | 모르는 경로·방법 | 앱 버그 |
| 409 | `no_request` | 열린 요청이 없음 (2분 지남·PC 가 닫음) | 끝. 다시 보내지 않는다 |
| 409 | `old_sms` | 문자를 받은 시각이 요청이 열린 시각보다 30초 넘게 이름 (요청 전에 온 지난 문자 - 5.7) | 보내지 않는다 (애초에 7절에서 걸러야 한다) |
| 409 | `req_mismatch` | `req_id` 가 지금 요청과 다름 (새 요청이 열림) | `GET /phone/v1/request` 로 다시 보고 그 요청에 맞는 문자가 오면 그때 |
| 413 | `too_large` | 본문이 2048바이트를 넘음 | 앱 버그 |
| 429 | `too_many` | 같은 요청에 번호를 다섯 번 넘게 보냄, 또는 그 주소에서 서명이 10분 안에 10번 틀려 10분 동안 거절 | 10분 뒤에 다시 |

서버는 같은 망의 주소마다 동시 연결 4개·분당 60번, 모두 16개까지 받고, 넘거나 사설·이 PC 주소가 아닌 곳에서 오면 응답 없이 닫는다. TLS 악수와 요청 읽기는 각각 5초 안에 끝나야 한다.

## 7. 지킬 것

1. **문자가 온 순간에만** 묻는다 (`GET /phone/v1/request`). 주기적으로 묻지 않는다 (폴링 없음).
2. 문자 본문을 보내지 않는다. 앱 안에서 인증번호 숫자만 뽑는다 ('인증번호' 낱말 주변의 4~8자리 - 일반 버전 앱과 같은 규칙, 서버 쪽 본보기 `sms_watch.extract_auth_code`).
3. 발신번호: 숫자만 남기고, `+82` 로 시작하면 `+82` 를 떼고 국내식 `0…` 으로 (`+82 10-1234-5678` → `01012345678`, `+82 090-…` 도 `090…`). 본보기 `otp_relay.sender_number`.
4. 열린 요청이 없거나 (`open: false`), 바꾼 발신번호가 요청의 `senders` 에 없으면 **아무것도 보내지 않는다**.
5. 요청은 2분 동안만 열려 있다 (`left_ms`). 번호는 그 요청에 한 번 보내면 끝 (다섯 번까지 받지만 다시 보낼 까닭이 없다).
6. **요청보다 오래된 문자는 보내지 않는다.** 요청이 열린 시각 = 응답의 `now_ms - (120000 - left_ms)` (서버 시각 - 5.4 의 차이를 빼 휴대폰 시각으로). 그보다 먼저 받은 문자는 지난 문자다 (서버도 30초 넘게 이르면 `409 old_sms`).
7. 응답 서명을 확인하고, 지문이 다르면 연결 자체를 쓰지 않는다 (3절).

## 8. 예시 값과 본보기

`python tests/fake_phone_local.py --vectors` 가 찍는 값이다. 입력: 짝 열쇠 `bytes(range(32))` (0x00…0x1f), `rand` `bytes(range(32, 64))` (0x20…0x3f), 휴대폰 번호 `ph_0a1b2c3d`, 시각 `1795000000000`, nonce `000102030405060708090a0b0c0d0e0f`. 본문 JSON 은 빈칸 없이 (`separators=(",", ":")`) 만든 바이트. (`tests/check_phone_local.py` 가 아래 값이 지금 코드의 계산과 같은지 본다.)

| 이름 | 값 |
|---|---|
| secret (hex) | `000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f` |
| k (QR, base64url) | `AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8` |
| rand (hex) | `202122232425262728292a2b2c2d2e2f303132333435363738393a3b3c3d3e3f` |
| rand (base64url) | `ICEiIyQlJicoKSorLC0uLzAxMjM0NTY3ODk6Ozw9Pj8` |
| pair_key | `a82211464f6c86d9ac838cb5c57030cad6fb22c6ba2b094ac1b23af6505a293c` |
| sign_key | `8254713485b8a538efe70c61af90a26016feefd54de2e2ca93cab8052614c838` |
| pair body | `{"rand":"ICEiIyQlJicoKSorLC0uLzAxMjM0NTY3ODk6Ozw9Pj8","os":"android","app_version":"1.0.0","device":"SM-S918N"}` |
| pair body sha256 | `44bfe208c61e160f52f396ee386f1cbf5512cedf9659c78c562145ff87a0e0a7` |
| X-AP-Sign `POST /phone/v1/pair` (pair_key) | `18a19c3b0faa5cb0c3bf5b2432df45cd2a3370bfb65364b1a413d6c828503433` |
| X-AP-Sign `GET /phone/v1/request` (sign_key, 빈 본문) | `afcf56a65d559f7678687c685d0211fd329fea91b9a8238befff1676066e313b` |
| code body | `{"req_id":"req_0123456789abcdef","code":"482913","sender":"15881234","sms_at":1795000000000}` |
| X-AP-Sign `POST /phone/v1/code` (sign_key) | `0fdd42f7b5a8ee7ebffce02b49d8ed12b2bf83fa544a9973ce29645d76ec77ab` |
| response body | `{"ok":true,"now_ms":1795000000000}` |
| 응답 X-AP-Sign (sign_key, 상태 200, 위 nonce) | `ab53c19588bccad3b80e674826b020b1775ebeede4c3f39ff6883070f4875d4a` |

**본보기로 쓰는 법**: `tests/fake_phone_local.py` 의 `FakePhone` 이 앱이 할 일 그대로다 - `parse_qr` (2절), `_connect` (주소 차례·지문 고정, 3절), `pair` (4·5.5절), `call` (머리글·서명·응답 서명 확인, 5.1~5.3절), `_again_on_clock` (5.4절), `on_sms` (7절). 앱의 열쇠·서명 함수를 만든 뒤 위 표의 값과 같은지 단위 시험으로 견준다.

## 9. 이번에 하지 않는 것

- **아이폰 단축어**: 단축어로는 자체 서명 인증서의 지문 확인과 HMAC 서명을 할 수 없다 (설계 7절 범위 밖). 아이폰을 쓰는 직원은 PC 의 Edge 창 인증번호 칸에 직접 넣는다 (5분 기다림).
- **푸시**: PC 가 휴대폰을 깨우지 않는다. 문자가 온 순간에 앱이 묻는다.
- **PC 주소가 바뀌었을 때 스스로 찾기**: 하지 않는다 - 다시 짝짓는다 (PC 주소 고정을 추천).
- 휴대폰이 없거나 2분 안에 번호가 오지 않으면 PC 는 Edge 칸에 사람이 넣기를 5분 기다리고, 그래도 없으면 그 사이트만 '인증번호를 받지 못함' 으로 실패한다 (앱이 할 일은 없다).
