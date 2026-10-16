# 관리 화면 웹 전환 - 옮기는 날 할 일

2026-10-15 밑작업 끝. Blaze 를 켜기 전까지는 지금처럼 **이 PC 의 로컬 관리 화면**(바탕화면 '오토파일럿 관리')으로 관리한다.
웹 관리는 코드만 저장소에 있고, 서버에는 아무것도 올라가 있지 않다.

## 무엇이 준비돼 있나

| 파일 | 하는 일 |
|---|---|
| `firebase/admin/routes.js` | 관리 작업 목록. 로컬 관리 화면과 웹 관리 함수가 **같이** 쓴다 (작업을 늘릴 때는 여기 한 줄) |
| `firebase/admin/ops.js` | 실제 작업 코드 (그대로). Cloud Functions 안에서는 키 파일 없이 기본 자격으로 돈다 |
| `firebase/admin/AFTERMARKET_SETUP.html` | 같은 화면. `const WEB = false;` 한 줄로 로컬/웹을 가른다 (웹은 총괄 로그인 → 함수로 요청) |
| `firebase/functions/index.js` | 웹 관리 함수 `admin` (서울 asia-northeast3). 총괄(super) 계정만, 부를 때마다 계정을 다시 읽어 사용중지·권한 회수를 바로 막는다 |
| `firebase/functions/sync.mjs` | admin/ 에서 세 파일만 복사 (ops.js·routes.js → functions/shared/, 화면 → admin_web/index.html). **admin/ 폴더째로는 절대 올리지 않는다** - 서비스 계정 키·서명 열쇠가 있다 |
| `firebase/firebase.admin-web.json` | 웹 관리 전용 배포 설정 (함수 + 관리 화면 사이트). 보통 `firebase.json` 과 따로라 지금 배포에 섞이지 않는다 |
| `firebase/tests/check_admin_web.py` | 에뮬레이터 시험 46건 (권한·같은 작업·총괄 계정 보호·관리 기록·사용중지·브라우저 로그인) |

관리 기록은 이미 지금부터 `관리_기록.txt` 와 함께 Firestore `admin_log` 에도 남는다 ({at, line, by, via}). 웹으로 옮겨도 기록이 이어진다.

## 옮기는 날 순서 (30분 안쪽)

1. **Blaze 켜기 + 예산 알림** (콘솔, 팀장님 - 결제 정보는 Claude 가 다루지 않는다)
2. **실사용 프로젝트로 먼저 옮기는 경우**: 골드디스크 4번(프로젝트 이름 한 곳에서 읽기)을 먼저 한다. 웹 화면은 Hosting 의 `/__/firebase/init.json` 으로 프로젝트 값을 읽어서 고칠 곳이 없고, `ops.js` 의 `PROJECT`·`databaseURL` 과 `firebase.admin-web.json` 의 `site` 만 바꾸면 된다.
3. **관리 화면 사이트 만들기** (한 번)
   `cd D:\AX\RPA\firebase` → `firebase hosting:sites:create rpa-test-f02e0-admin`
   (이름을 바꾸면 `firebase.admin-web.json` 의 `site` 도 같이)
4. **시험 한 번 더** (에뮬레이터, 실제 서버 안 건드림)
   `. .\emu_env.ps1; node functions\sync.mjs`
   `firebase emulators:exec --config firebase.admin-web.json --only auth,database,firestore,functions,hosting --project rpa-test-f02e0 "D:\AX\RPA\.venv\Scripts\python.exe tests\check_admin_web.py"` → 46/46
5. **배포** (함수와 관리 화면만 - `--only` 를 꼭 붙인다. 올리기 전에 sync.mjs 가 저절로 돈다)
   `firebase deploy --config firebase.admin-web.json --only functions:admin,hosting:rpa-test-f02e0-admin`
   처음이면 Cloud Functions·Cloud Build·Artifact Registry API 를 켜겠냐고 묻는다 → 예
6. **총괄 계정** - 웹 관리는 총괄(super)만 들어온다. 웹 화면에서는 총괄을 만들 수 없다 (로컬에서만):
   `node admin\setup.js user - <아이디> super <이름>` → 나온 비밀번호를 전달 (이메일은 `<아이디>@rpa-test-f02e0.firebaseapp.com`)
   비밀번호 재발급·사용중지도 로컬 setup.js 로.
7. **확인**: `https://rpa-test-f02e0-admin.web.app` → 총괄 아이디로 로그인 → 업체 표가 뜨는지, 업체 하나 열어 보기, 토큰 한 번 넣어 보기 → Firestore `admin_log` 에 `via: 웹` 줄이 생겼는지
   - 업체 표에서 "권한" 오류가 나면: 함수가 쓰는 서비스 계정(콘솔 → 함수 → admin → 서비스 계정)에 `Firebase Admin` 역할을 준다 (새 프로젝트는 기본 계정에 권한을 자동으로 안 줄 때가 있다)
   - 업체 상세의 **[대시보드 보기]** 를 눌러 그 업체 화면이 노란 띠와 함께 열리는지. "권한"·"signBlob" 오류가 나면: 같은 서비스 계정에 `서비스 계정 토큰 생성자`(Service Account Token Creator) 역할을 준다 - 총괄 로그인 열쇠(ops.dashboardToken)를 만드는 데 필요하다

## 옮긴 뒤에도 이 PC 에만 두는 것

- **버전 내보내기** (`tools/publish_release.py`) - 서명 비밀 열쇠(`update_signing_key.txt`)는 이 PC 밖으로 나가지 않는다. 웹은 버전 목록·안정본 지정·업데이트 보내기까지.
- **서비스 계정 키** (`serviceAccountKey.json`) - 로컬 관리 화면·setup.js 만 쓴다. 웹은 함수의 기본 자격으로.
- 로컬 관리 화면은 옮긴 뒤에도 그대로 쓸 수 있다 (같은 작업 코드).

## 옮기는 날 정할 것

- **총괄 2단계 인증**: Firebase Authentication 을 Identity Platform 으로 올려야 문자·OTP 2단계 인증을 붙일 수 있다 (Blaze 필요). 웹 관리는 토큰·계정을 만지는 곳이라 붙이기를 권한다.
- **App Check** (선택): 관리 함수를 우리 웹 화면에서만 부르게. 총괄 확인이 이미 있어 필수는 아니다.

## 알아 둘 것

- 웹 관리 함수는 고치는 요청을 로컬처럼 하나씩 줄 세우지 못한다 (인스턴스가 여럿). 화면이 누르는 동안 단추를 잠그고, 만들기는 '이미 있다' 를 건너뛰어 겹쳐도 반쪽이 남지 않는다. 총괄 여러 명이 동시에 같은 업체를 고치는 일이 잦아지면 트랜잭션으로 바꾼다.
- 웹에서 화면 테마는 그 브라우저에 남는다 (로컬은 `admin_prefs.json`).
- 웹 로그인 화면은 아이디만 치면 `<아이디>@<프로젝트 authDomain>` 으로 이메일을 만든다. 콘솔에서 authDomain 을 바꾸면 `ops.js` 의 `DOMAIN`(계정 이메일)과 어긋나니, 그때는 이메일 전체를 치거나 둘을 같이 맞춘다.
- 업체 비활성화·다시 활성화는 총괄 계정을 건드리지 않는다 (업체코드가 붙은 총괄이라도).
- `functions/shared/`·`admin_web/` 은 복사본이라 저장소에 안 올린다 (`.gitignore`). 고칠 곳은 언제나 `firebase/admin/`.
