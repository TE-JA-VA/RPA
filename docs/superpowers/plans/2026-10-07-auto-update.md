# 자동 업데이트 (설치 마법사 3부) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 우리 관리 화면에서 업체·PC·판을 골라 [업데이트] 를 누르면, 그 PC 가 RPA 가 쉴 때 바뀐 파일만 받아(서명 확인) 바꾸고, 3분 점검에 실패하거나 도중에 꺼지면 반드시 옛 판으로 되돌린다. 직전 판 하나를 보관해 [이전 판으로 되돌리기] 도 된다.

**Architecture:** PC 쪽은 새 모듈 셋 - `update_sign.py`(표준 라이브러리 ed25519), `rpa_update.py`(상태·받기·확인·넘기기, 에이전트와 도우미가 같이 씀), `update_helper.py`(프로그램 폴더 밖에서 도는 도우미: 보관·바꾸기·3분 점검·되돌리기·재부팅 복구). 에이전트는 명령 `update`/`rollback` 을 받아 스레드로 받기→대기→넘기기를 하고, 도우미는 일회용 예약 작업 `\AFTER MARKET\RPA Update` 로 띄운다. 우리 쪽은 `tools/publish_release.py`(서명·업데이트 전용 호스팅 사이트 폴더·5개+안정본 유지·배포), `setup.js release-*`, 관리 화면(PC 줄 상태·[업데이트]·[되돌리기]·판 목록·[안정본으로 지정]), 업체 웹(판 옆 상태·실행 단추 잠금).

**Tech Stack:** Python 3.14 (내장 파이썬, 표준 라이브러리만), Windows 작업 스케줄러(schtasks), Firebase Realtime DB / Hosting (업데이트 전용 사이트), Node(firebase-admin) 관리 도구, Playwright 시험, 윈도우 샌드박스.

**Spec:** `docs/superpowers/specs/2026-10-07-auto-update-design.md`

## Global Constraints

- 화면·기록·명령 결과·진행 글은 모두 **한국어, 쉬운 말** (사용자 규칙).
- 업데이트는 **설정(`config\`)·기록(`data\`)을 절대 건드리지 않는다.** 프로그램 폴더 안에서도 판 목록(manifest)에 있는 파일만 바꾸거나 치운다.
- 받은 파일은 **서명 확인한 manifest 의 sha256·크기**와 하나하나 맞춘다. 하나라도 틀리면 아무것도 바꾸지 않는다.
- 서명 비밀 열쇠는 `firebase/admin/update_signing_key.txt` 에만 (git·대화·기록에 내용 금지). 공개 열쇠만 코드에.
- 명령 `update`·`rollback` 은 **관리 화면(Admin SDK, `by: "admin-tool"`)만**. DB 규칙의 명령 type 목록에 넣지 않는다.
- 3분 점검 = `HEALTH_WAIT_SEC = 180`. 보관은 **늘 직전 판 하나** (`update\backup\`).
- 업데이트 상태 글: `업데이트 받는 중` / `업데이트 대기 중` / `바꾸는 중` / `업데이트됨 (M/D HH:MM)` / `업데이트 실패` / `업데이트 실패 - 옛 판으로 되돌림`. 실행을 막는 글: `업데이트 중이라 잠시 실행할 수 없습니다`.
- 호스팅에 남길 판: 최근 **5개** + **안정본(Stable)**. 최신본(Newest)은 가장 최근에 내보낸 판 자동.
- Firebase 배포·사이트 만들기는 **사용자 확인 뒤** (기존 원칙). 개발 PC 에 setup.exe 를 돌리지 않는다. 실제 운영 첫 업데이트는 사용자가 시험 업체 PC 로.
- `.ps1`·`.iss`·안내 txt 는 UTF-8 BOM, `.bat` 은 CP949+CRLF 또는 영문만.
- 파이썬 패치는 Write 로 스크립트 파일을 만든 뒤 실행 (bash heredoc 은 한글을 깨뜨린다).
- 시험 파일은 저장소 방식: `check(cond, what)` 가 `PASS`/`FAIL` 을 찍고 끝에 `실패: 없음`, 실패면 종료 코드 1.
- 코드를 바꾼 뒤 `graphify update .`.

## Review Focus

1. **도우미가 에이전트 작업과 같이 죽지 않아야 한다** - 도우미는 에이전트의 자식이 아니라 따로 등록한 작업으로 뜬다 (`schtasks /End` 가 에이전트 작업만 끝낸다). Task 4 시험(작업 XML 이 별도 이름·별도 명령) + Task 9 샌드박스(실제로 바꾸기 끝까지).
2. **바꾸는 도중 어느 순간에 끊겨도 되돌리면 옛 판 그대로** - 옮기기 중간(파일 몇 개만 옮김)·manifest 놓기 전·`--after-install` 전후. Task 3 의 "N번째 옮기기에서 죽이기" 시험을 모든 N 에 대해.
3. **받는 도중 404·끊김·지문 틀림이면 프로그램 폴더가 1바이트도 안 바뀐다** - Task 2 시험 (프로그램 폴더 전체 지문을 앞뒤로 비교).
4. **대기에 들어간 뒤에는 어떤 실행도 새로 안 뜬다** - 단추·예약·반복 모두 같은 잠금 안에서 본다. Task 4 시험(대기 상태에서 `launch` 거절, `Scheduler.busy` 글).
5. **새 판과 옛 판이 모두 점검을 못 넘기면** 상태에 "설치 파일로 다시 설치" 를 남기고 멈춘다 (되풀이하지 않는다). Task 3 시험.

---

## 파일 지도

| 파일 | 할 일 |
|---|---|
| `update_sign.py` (새) | ed25519 서명·확인 (RFC 8032 참조 구현, 표준 라이브러리만), `PUBLIC_KEY_HEX` |
| `rpa_update.py` (새) | 업데이트 폴더·상태 파일, `plan_files`, `fetch_release`, `stage_rollback`, `run_update`, `handoff`, `busy_reason`, `live_view`, `mark_alive` |
| `update_helper.py` (새) | 도우미 `main()` - ready → apply, applying/rolling_back → rollback, 3분 점검 |
| `rpa_settings.py` | 도우미 작업 XML·등록·실행·지우기, `--after-install` 그대로 |
| `rpa_dashboard.py` | `launch`·`Scheduler.busy` 가 `rpa_update.busy_reason()` 을 본다 |
| `firebase/agent/agent.py` | `update`·`rollback` 명령, `by` 확인, 업데이트 스레드, `alive` 적기, `live.update` |
| `tools/build_release.py` | PROGRAM_FILES 에 새 모듈 셋 |
| `tools/publish_release.py` (새) | 열쇠 만들기, 서명, 업데이트 전용 사이트 폴더, 5개+안정본 유지, `setup.js release-set`, 배포 |
| `firebase/releases.json` (새) | 업데이트 전용 사이트 배포 설정 (기존 `firebase.json` 은 그대로) |
| `firebase/admin/ops.js`·`setup.js`·`admin.js`·`AFTERMARKET_SETUP.html` | 판 목록·안정본·업데이트/되돌리기 명령·PC 줄 상태 |
| `firebase/web/rpa.js`·`index.html` | 판 옆 업데이트 상태, 실행 단추 잠금 |
| `tools/sandbox_inner.ps1`·`tools/sandbox_test.py` | 판 B 업데이트·되돌리기·망가진 판 C·도중 끊김 |
| 시험 | `tests/test_update_sign.py`·`tests/test_rpa_update.py`·`tests/test_update_helper.py`·`tests/test_publish_release.py` (새), `tests/test_settings.py`·`tests/test_schedule_slots.py`·`firebase/tests/test_agent.py`·`check_setup.py`·`check_admin.py`·`check_web.py`·`rules.test.js` |

공통 시험 명령 (PC 묶음): `bash .superpowers/sdd/2026-10-07-auto-update/pc_tests.sh <이름…>` - Task 1 에서 2026-10-07-settings-schedule 의 같은 이름 스크립트를 이 계획 작업 폴더로 복사해 쓴다. 에뮬레이터 시험은 같은 폴더의 `emu.ps1 -Cmd '<명령>' -Only <에뮬레이터>` (역시 복사).

---

### Task 1: 서명 (`update_sign.py`)

**Files:**
- Create: `update_sign.py`
- Test: `tests/test_update_sign.py`

**Interfaces:**
- Produces: `update_sign.secret_to_public(secret: bytes) -> bytes` (32), `update_sign.sign(secret: bytes, msg: bytes) -> bytes` (64), `update_sign.verify(public: bytes, msg: bytes, sig: bytes) -> bool` (예외 없음, 틀리면 False), `update_sign.keygen() -> tuple[bytes, bytes]` (secret, public), `update_sign.PUBLIC_KEY_HEX: str` (Task 10 전까지 `""`), `update_sign.public_key() -> bytes | None` (`PUBLIC_KEY_HEX` 가 비면 None).

- [ ] **Step 1: 작업 폴더 준비** - `.superpowers/sdd/2026-10-07-settings-schedule/pc_tests.sh` 와 `emu.ps1` 을 `.superpowers/sdd/2026-10-07-auto-update/` 로 복사한다 (계획 작업 폴더는 `sdd-workspace` 가 만든다).

- [ ] **Step 2: 실패하는 시험**

```python
# tests/test_update_sign.py
# -*- coding: utf-8 -*-
"""업데이트 서명 (설계 5절). RFC 8032 7.1 의 시험 값 + 서명·확인 왕복 + 바꿔치기."""
import io
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import update_sign as us  # noqa: E402

fails = []


def check(cond, what):
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        fails.append(what)


h = bytes.fromhex
# RFC 8032 7.1 TEST 1 (빈 글) · TEST 2 (0x72 한 바이트)
V = [("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
      "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
      "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
     ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
      "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
      "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00")]
for i, (sk, pk, msg, sig) in enumerate(V, 1):
    check(us.secret_to_public(h(sk)) == h(pk), f"RFC 8032 TEST {i}: 공개 열쇠")
    check(us.sign(h(sk), h(msg)) == h(sig), f"RFC 8032 TEST {i}: 서명")
    check(us.verify(h(pk), h(msg), h(sig)) is True, f"RFC 8032 TEST {i}: 확인")

sk, pk = us.keygen()
msg = '{"version": "2026.10.07-5", "files": {"rpa_status.py": "…"}}'.encode("utf-8")
t = time.time(); sig = us.sign(sk, msg); ok = us.verify(pk, msg, sig); took = time.time() - t
check(len(sk) == 32 and len(pk) == 32 and len(sig) == 64 and ok, "새 열쇠로 서명·확인 왕복")
check(took < 2.0, f"서명+확인이 2초 안 ({took:.2f}초)")
check(us.verify(pk, msg + b" ", sig) is False, "글이 1바이트 바뀌면 거짓")
check(us.verify(pk, msg, sig[:-1] + bytes([sig[-1] ^ 1])) is False, "서명이 1비트 바뀌면 거짓")
check(us.verify(us.keygen()[1], msg, sig) is False, "다른 열쇠면 거짓")
check(us.verify(pk, msg, b"short") is False and us.verify(b"x", msg, sig) is False, "길이가 틀려도 예외 없이 거짓")
check(us.PUBLIC_KEY_HEX == "" or len(us.PUBLIC_KEY_HEX) == 64, "박힌 공개 열쇠는 비었거나 64자")
check((us.public_key() is None) == (us.PUBLIC_KEY_HEX == ""), "공개 열쇠가 비면 public_key() 는 None")

print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
```

- [ ] **Step 3: 실패 확인**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe tests/test_update_sign.py`
Expected: `ModuleNotFoundError: No module named 'update_sign'`

- [ ] **Step 4: 구현** (RFC 8032 6절 참조 구현을 그대로 옮긴 것. 확인은 예외를 삼켜 False)

```python
# update_sign.py
# -*- coding: utf-8 -*-
"""업데이트 판 서명 (자동 업데이트 설계 5절). ed25519 - RFC 8032 6절 참조 구현을 표준 라이브러리만으로 옮겼다.
업체 PC 의 내장 파이썬에는 cryptography 가 없어서 직접 넣는다. 느려도 판 하나에 한 번이라 괜찮다 (서명+확인 1초 안쪽).

비밀 열쇠는 우리 PC 의 firebase/admin/update_signing_key.txt 에만 있다 (tools/publish_release.py 가 쓴다).
여기 박힌 것은 공개 열쇠 - 이걸로 PC 가 판 목록(manifest.json)의 서명을 확인한다."""
import hashlib
import os

PUBLIC_KEY_HEX = ""     # tools/publish_release.py --keygen 이 알려 준 값 (비어 있으면 업데이트를 받지 않는다)

_p = 2 ** 255 - 19
_q = 2 ** 252 + 27742317777372353535851937790883648493


def _sha512(b):
    return hashlib.sha512(b).digest()


def _inv(x):
    return pow(x, _p - 2, _p)


_d = -121665 * _inv(121666) % _p
_sqrt_m1 = pow(2, (_p - 1) // 4, _p)


def _add(P, Q):
    A = (P[1] - P[0]) * (Q[1] - Q[0]) % _p
    B = (P[1] + P[0]) * (Q[1] + Q[0]) % _p
    C = 2 * P[3] * Q[3] * _d % _p
    D = 2 * P[2] * Q[2] % _p
    E, F, G, H = B - A, D - C, D + C, B + A
    return (E * F % _p, G * H % _p, F * G % _p, E * H % _p)


def _mul(s, P):
    Q = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            Q = _add(Q, P)
        P = _add(P, P)
        s >>= 1
    return Q


def _equal(P, Q):
    return (P[0] * Q[2] - Q[0] * P[2]) % _p == 0 and (P[1] * Q[2] - Q[1] * P[2]) % _p == 0


def _recover_x(y, sign):
    if y >= _p:
        return None
    x2 = (y * y - 1) * _inv(_d * y * y + 1)
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_p + 3) // 8, _p)
    if (x * x - x2) % _p != 0:
        x = x * _sqrt_m1 % _p
    if (x * x - x2) % _p != 0:
        return None
    if (x & 1) != sign:
        x = _p - x
    return x


_gy = 4 * _inv(5) % _p
_gx = _recover_x(_gy, 0)
_G = (_gx, _gy, 1, _gx * _gy % _p)


def _compress(P):
    zinv = _inv(P[2])
    x, y = P[0] * zinv % _p, P[1] * zinv % _p
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _decompress(s):
    if len(s) != 32:
        return None
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % _p)


def _expand(secret):
    if len(secret) != 32:
        raise ValueError("비밀 열쇠는 32바이트")
    h = _sha512(secret)
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def _hq(b):
    return int.from_bytes(_sha512(b), "little") % _q


def secret_to_public(secret):
    return _compress(_mul(_expand(secret)[0], _G))


def sign(secret, msg):
    a, prefix = _expand(secret)
    A = _compress(_mul(a, _G))
    r = _hq(prefix + msg)
    Rs = _compress(_mul(r, _G))
    s = (r + _hq(Rs + A + msg) * a) % _q
    return Rs + int.to_bytes(s, 32, "little")


def verify(public, msg, sig):
    """맞으면 True. 길이·모양이 틀려도 예외 없이 False."""
    try:
        if len(public) != 32 or len(sig) != 64:
            return False
        A, R = _decompress(public), _decompress(sig[:32])
        if not A or not R:
            return False
        s = int.from_bytes(sig[32:], "little")
        if s >= _q:
            return False
        return _equal(_mul(s, _G), _add(R, _mul(_hq(sig[:32] + public + msg), A)))
    except Exception:
        return False


def keygen():
    secret = os.urandom(32)
    return secret, secret_to_public(secret)


def public_key():
    return bytes.fromhex(PUBLIC_KEY_HEX) if PUBLIC_KEY_HEX else None
```

- [ ] **Step 5: 통과 확인**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe tests/test_update_sign.py`
Expected: 모두 PASS, `실패: 없음`. RFC 시험 값이 틀리면 코드를 고치기 전에 RFC 8032 7.1 원문(WebFetch https://www.rfc-editor.org/rfc/rfc8032#section-7.1)과 시험 값을 먼저 맞춰 본다.

- [ ] **Step 6: 커밋**

```bash
git add update_sign.py tests/test_update_sign.py
git commit -m "자동 업데이트 1: 판 서명 (표준 라이브러리 ed25519)"
```

---

### Task 2: PC 업데이트 핵심 (`rpa_update.py`) - 상태·받기·확인

**Files:**
- Create: `rpa_update.py`
- Test: `tests/test_rpa_update.py`

**Interfaces:**
- Consumes: `update_sign.verify/public_key` (Task 1), `rpa_status.install_root/write_json_atomic/read_json/file_digest/manifest_path_ok/MANIFEST_NAME/MANIFEST_FORMAT/check_install`.
- Produces (모두 `rpa_update.`):
  - `UPDATE_BASE_URL: str` (`RPA_UPDATE_BASE_URL` 로 덮을 수 있다), `HEALTH_WAIT_SEC = 180`, `DISK_MARGIN = 200 * 1024 * 1024`
  - `BUSY_STATES = ("waiting", "ready", "applying", "rolling_back")`, `ACTIVE_STATES = ("downloading",) + BUSY_STATES`, `BUSY_TEXT = "업데이트 중이라 잠시 실행할 수 없습니다"`
  - `class UpdateError(Exception)` - 사람에게 보일 글
  - `update_dir() -> str` (`install_root()\update`), `path(*parts) -> str`
  - `read_state() -> dict`, `write_state(state: dict) -> None`, `log(msg: str) -> None` (`업데이트_기록.txt`)
  - `busy_reason() -> str | None`
  - `plan_files(cur: dict, new: dict) -> tuple[list, list, list]` (fetch, remove, new_only) - 키는 manifest 상대 경로
  - `fetch_release(version, program_root, staging, base_url=None, get=http_get, pub=None) -> dict` (새 manifest)
  - `stage_rollback(program_root, staging) -> dict` (보관본 manifest)
  - `backup_version() -> str | None`
  - `live_view() -> dict | None` (`{state, target, from, at, reason, backup}`)
  - `mark_alive(install: dict) -> bool`, `health_local() -> bool`
- staging 폴더 모양 (Task 3 이 읽는다): `staging\manifest.json`(받은 바이트 그대로), `staging\plan.json` `{"version", "from", "fetch": [...], "remove": [...], "new": [...]}`, `staging\files\<상대 경로>`.

- [ ] **Step 1: 실패하는 시험**

```python
# tests/test_rpa_update.py
# -*- coding: utf-8 -*-
"""자동 업데이트 PC 핵심 (설계 6절). 가짜 Program Files·가짜 호스팅(사전) - 진짜 PC·인터넷은 안 쓴다."""
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
tmp = tempfile.mkdtemp(prefix="rpa_upd_")
os.environ["RPA_PROGRAMDATA"] = os.path.join(tmp, "pd")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rpa_status as st  # noqa: E402
import rpa_update as up  # noqa: E402
import update_sign as us  # noqa: E402

fails = []


def check(cond, what):
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        fails.append(what)


SK, PK = us.keygen()
PROG = os.path.join(tmp, "prog")


def put(root, rel, text):
    full = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(text)


def manifest_of(root, version, rels, runtime="3.14.7"):
    return {"format": 1, "version": version, "built_at": "x", "builder": "t", "runtime": {"python": runtime},
            "files": {r: st.file_digest(os.path.join(root, *r.split("/"))) for r in rels}}


def tree_digest(root):
    out = {}
    for base, _, files in os.walk(root):
        for n in files:
            p = os.path.join(base, n)
            out[os.path.relpath(p, root)] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    return out


# 지금 판 A: a.py, b.py, firebase/agent/agent.py
for rel, text in (("a.py", "A1"), ("b.py", "B1"), ("firebase/agent/agent.py", "G1")):
    put(PROG, rel, text)
MAN_A = manifest_of(PROG, "2026.10.07-1", ["a.py", "b.py", "firebase/agent/agent.py"])
with open(os.path.join(PROG, "manifest.json"), "w", encoding="utf-8") as f:
    json.dump(MAN_A, f)

# 새 판 B: a.py 바뀜, b.py 없어짐, c.py 새로, agent.py 그대로
SRC_B = os.path.join(tmp, "srcB")
for rel, text in (("a.py", "A2"), ("c.py", "C2"), ("firebase/agent/agent.py", "G1")):
    put(SRC_B, rel, text)
MAN_B = manifest_of(SRC_B, "2026.10.07-2", ["a.py", "c.py", "firebase/agent/agent.py"])
MB = json.dumps(MAN_B).encode("utf-8")
BASE = "https://example.test"
HOST = {f"{BASE}/releases/2026.10.07-2/manifest.json": MB,
        f"{BASE}/releases/2026.10.07-2/manifest.sig": us.sign(SK, MB).hex().encode()}
for rel in ("a.py", "c.py", "firebase/agent/agent.py"):
    HOST[f"{BASE}/blobs/{MAN_B['files'][rel]['sha256']}"] = open(os.path.join(SRC_B, *rel.split("/")), "rb").read()
GOT = []


def get(url, host=HOST):
    GOT.append(url)
    if url not in host:
        raise up.UpdateError(f"받지 못했습니다: {url.rsplit('/', 1)[-1]} (404)")
    return host[url]


print("=== 1. 바뀐 파일만 고르기 ===")
fetch, remove, new = up.plan_files(MAN_A["files"], MAN_B["files"])
check(fetch == ["a.py", "c.py"] and remove == ["b.py"] and new == ["c.py"], f"받을 것·치울 것·새 파일 ({fetch} {remove} {new})")

print("\n=== 2. 받기·확인 ===")
STG = up.path("staging")
before = tree_digest(PROG)
man = up.fetch_release("2026.10.07-2", PROG, STG, base_url=BASE, get=get, pub=PK)
plan = json.load(open(os.path.join(STG, "plan.json"), encoding="utf-8"))
check(man["version"] == "2026.10.07-2" and plan == {"version": "2026.10.07-2", "from": "2026.10.07-1", "fetch": ["a.py", "c.py"],
                                                  "remove": ["b.py"], "new": ["c.py"]}, f"plan.json ({plan})")
check(open(os.path.join(STG, "files", "a.py"), encoding="utf-8").read() == "A2"
      and not os.path.exists(os.path.join(STG, "files", "firebase", "agent", "agent.py")), "바뀐 파일만 받았다 (그대로인 agent.py 는 안 받음)")
check(open(os.path.join(STG, "manifest.json"), "rb").read() == MB, "받은 manifest 를 바이트 그대로 둔다")
check(not any(u.endswith(MAN_B["files"]["firebase/agent/agent.py"]["sha256"]) for u in GOT), "그대로인 파일은 내려받지도 않는다")
check(tree_digest(PROG) == before, "받기만으로는 프로그램 폴더가 안 바뀐다")


def refused(what, host=None, pub=PK, version="2026.10.07-2", contains=""):
    shutil.rmtree(STG, ignore_errors=True)
    b = tree_digest(PROG)
    try:
        up.fetch_release(version, PROG, STG, base_url=BASE, get=lambda u: get(u, host or HOST), pub=pub)
        check(False, what + " (거절 안 됨)")
    except up.UpdateError as e:
        check(contains in str(e) and tree_digest(PROG) == b and not os.path.exists(os.path.join(STG, "files")),
              f"{what} - 프로그램 폴더 그대로, 받은 것 지움 ({e})")


refused("서명이 다르면 거절", pub=us.keygen()[1], contains="서명")
refused("공개 열쇠가 없으면 거절", pub=b"", contains="서명")
bad = dict(HOST); bad[f"{BASE}/blobs/{MAN_B['files']['c.py']['sha256']}"] = b"tampered"
refused("파일 지문이 다르면 거절 (Review Focus 3)", host=bad, contains="c.py")
gone = dict(HOST); del gone[f"{BASE}/blobs/{MAN_B['files']['a.py']['sha256']}"]
refused("파일이 없으면(404) 거절 (Review Focus 3)", host=gone, contains="404")
refused("요청한 판과 manifest 판이 다르면 거절", version="2026.10.07-3", contains="판")
MAN_R = dict(MAN_B, runtime={"python": "3.15.0"}); MR = json.dumps(MAN_R).encode()
rt = dict(HOST); rt[f"{BASE}/releases/2026.10.07-2/manifest.json"] = MR; rt[f"{BASE}/releases/2026.10.07-2/manifest.sig"] = us.sign(SK, MR).hex().encode()
refused("파이썬이 바뀐 판은 거절 (설치 파일로)", host=rt, contains="설치 파일")
MAN_X = json.loads(MB); MAN_X["files"]["../evil.py"] = MAN_X["files"]["a.py"]; MX = json.dumps(MAN_X).encode()
ev = dict(HOST); ev[f"{BASE}/releases/2026.10.07-2/manifest.json"] = MX; ev[f"{BASE}/releases/2026.10.07-2/manifest.sig"] = us.sign(SK, MX).hex().encode()
refused("밖을 가리키는 경로는 서명이 맞아도 거절", host=ev, contains="경로")
real_usage = shutil.disk_usage
shutil.disk_usage = lambda p: real_usage(p)._replace(free=10)
try:
    refused("디스크 여유가 모자라면 시작 전 거절", contains="디스크")
finally:
    shutil.disk_usage = real_usage

print("\n=== 3. 상태·실행 막기·화면 값 ===")
check(up.read_state() == {} and up.busy_reason() is None and up.live_view() is None, "상태가 없으면 막지 않고 화면 값도 없다")
for s in ("downloading", "done", "failed", "rolled_back"):
    up.write_state({"state": s})
    check(up.busy_reason() is None, f"{s} 는 실행을 막지 않는다")
for s in up.BUSY_STATES:
    up.write_state({"state": s})
    check(up.busy_reason() == "업데이트 중이라 잠시 실행할 수 없습니다", f"{s} 는 실행을 막는다")
up.write_state({"state": "done", "target": "2026.10.07-2", "from": "2026.10.07-1", "at": "2026-10-07T14:03:00", "reason": None})
os.makedirs(up.path("backup"), exist_ok=True)
with open(up.path("backup", "manifest.json"), "w", encoding="utf-8") as f:
    json.dump(MAN_A, f)
check(up.backup_version() == "2026.10.07-1" and up.live_view() == {"state": "done", "target": "2026.10.07-2", "from": "2026.10.07-1",
                                                                 "at": "2026-10-07T14:03:00", "reason": None, "backup": "2026.10.07-1"},
      f"live_view 에 보관본 판 ({up.live_view()})")
up.log("시험 한 줄")
check("시험 한 줄" in open(up.path("업데이트_기록.txt"), encoding="utf-8").read(), "업데이트 기록 파일")

print("\n=== 4. 되돌리기 준비 (보관본 → staging, 받기 없음) ===")
# 보관본 = A 의 바뀐 파일들 (Task 3 의 apply 가 남기는 모양)
for rel, text in (("a.py", "A1"), ("b.py", "B1")):
    put(up.path("backup", "files"), rel, text)
# 지금 판을 B 로 바꿔 둔다
for rel, text in (("a.py", "A2"), ("c.py", "C2")):
    put(PROG, rel, text)
os.remove(os.path.join(PROG, "b.py"))
with open(os.path.join(PROG, "manifest.json"), "wb") as f:
    f.write(MB)
shutil.rmtree(STG, ignore_errors=True)
bman = up.stage_rollback(PROG, STG)
plan = json.load(open(os.path.join(STG, "plan.json"), encoding="utf-8"))
check(bman["version"] == "2026.10.07-1" and plan["fetch"] == ["a.py", "b.py"] and plan["remove"] == ["c.py"] and plan["new"] == ["b.py"],
      f"보관본으로 가는 plan ({plan})")
check(open(os.path.join(STG, "files", "b.py"), encoding="utf-8").read() == "B1" and os.path.isfile(up.path("backup", "files", "a.py")),
      "보관본은 복사만 한다 (되돌리기가 실패해도 보관본은 남는다)")
os.remove(up.path("backup", "files", "b.py"))
shutil.rmtree(STG, ignore_errors=True)
try:
    up.stage_rollback(PROG, STG); check(False, "보관본이 모자라는데 되돌리기 준비됨")
except up.UpdateError as e:
    check("보관본" in str(e), f"보관본 파일이 모자라면 거절 ({e})")

print("\n=== 5. 살아 있음 표시 (도우미 3분 점검이 본다) ===")
up.write_state({"state": "done"})
check(up.mark_alive({"version": "2026.10.07-2", "state": "ok"}) is False and not os.path.exists(up.path("alive.json")), "업데이트 중이 아니면 안 적는다")
for s in ("applying", "rolling_back"):
    up.write_state({"state": s})
    check(up.mark_alive({"version": "2026.10.07-2", "state": "ok"}) is True
          and st.read_json(up.path("alive.json"))["version"] == "2026.10.07-2", f"{s} 면 alive.json 을 적는다")
check(up.health_local() is False, "표시 파일이 없으면 로그인까지 봐야 '살아 있음'")
open(up.path("health_local"), "w").close()
check(up.health_local() is True, "샌드박스용 표시 파일 update\\health_local (관리자만 쓰는 폴더)")
os.remove(up.path("health_local"))

shutil.rmtree(tmp, ignore_errors=True)
print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe tests/test_rpa_update.py`
Expected: `ModuleNotFoundError: No module named 'rpa_update'`

- [ ] **Step 3: 구현**

```python
# rpa_update.py
# -*- coding: utf-8 -*-
"""자동 업데이트 PC 쪽 (설계 docs/superpowers/specs/2026-10-07-auto-update-design.md 6·7절).
에이전트(받기·대기·넘기기)와 도우미(update_helper.py, 바꾸기·되돌리기)가 같이 쓴다. 표준 라이브러리 + rpa_status 만.

폴더 %ProgramData%\\AFTER MARKET\\RPA\\update\\
  state.json        지금 상태 {state, target, from, mode, program_dir, staging, started_at, at, reason}
  alive.json        새 에이전트가 켜져 판 점검을 넘겼다 {version, state, at, pid} - 도우미의 3분 점검이 본다
  staging\\          받은 새 판 (manifest.json·plan.json·files\\…)
  backup\\           직전 판 (manifest.json·files\\…) - 늘 하나
  backup_new\\       바꾸는 동안의 보관 (성공하면 backup 이 된다, 되돌리면 지운다)
  runner\\           도우미와 그 파이썬 (프로그램 폴더 밖이라 새 판이 깨져도 돈다)
  업데이트_기록.txt  단계마다 한 줄
"""
import datetime
import hashlib
import json
import os
import shutil
import urllib.request

import rpa_status as st
import update_sign

UPDATE_BASE_URL = os.environ.get("RPA_UPDATE_BASE_URL") or "https://rpa-test-f02e0-releases.web.app"   # SFTP 로 옮기면 받기만 바꾼다
HEALTH_WAIT_SEC = 180
DISK_MARGIN = 200 * 1024 * 1024
BUSY_STATES = ("waiting", "ready", "applying", "rolling_back")
ACTIVE_STATES = ("downloading",) + BUSY_STATES
BUSY_TEXT = "업데이트 중이라 잠시 실행할 수 없습니다"


class UpdateError(Exception):
    """사람에게 보일 까닭 (한국어)."""


def update_dir():
    return os.path.join(st.install_root(), "update")


def path(*parts):
    return os.path.join(update_dir(), *parts)


def now_text():
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def read_state():
    v = st.read_json(path("state.json"))
    return v if isinstance(v, dict) else {}


def write_state(state):
    os.makedirs(update_dir(), exist_ok=True)
    st.write_json_atomic(path("state.json"), state)


def log(msg):
    try:
        os.makedirs(update_dir(), exist_ok=True)
        with open(path("업데이트_기록.txt"), "a", encoding="utf-8") as f:
            f.write(f"[{now_text()}] {msg}\n")
    except OSError:
        pass                                    # 기록 때문에 업데이트가 멈추면 안 된다


def busy_reason():
    return BUSY_TEXT if read_state().get("state") in BUSY_STATES else None


def plan_files(cur, new):
    """(받을 것, 치울 것, 새로 생기는 것) - 받을 것 = 지문이 다르거나 새로 생긴 파일."""
    fetch = sorted(r for r, d in new.items() if (cur.get(r) or {}).get("sha256") != d.get("sha256"))
    remove = sorted(r for r in cur if r not in new)
    return fetch, remove, sorted(r for r in fetch if r not in cur)


def http_get(url, timeout=60):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.read()
    except Exception as e:
        code = getattr(e, "code", None)
        raise UpdateError(f"받지 못했습니다: {url.rsplit('/', 1)[-1]} ({code or type(e).__name__})") from None


def _read_manifest(root):
    with open(os.path.join(root, st.MANIFEST_NAME), encoding="utf-8") as f:
        return json.load(f)


def _check_manifest(man, version=None):
    files = man.get("files") if isinstance(man, dict) else None
    if man.get("format") != st.MANIFEST_FORMAT or not isinstance(files, dict):
        raise UpdateError("판 목록 형식이 다릅니다")
    if version is not None and man.get("version") != version:
        raise UpdateError(f"요청한 판({version})과 판 목록의 판({man.get('version')})이 다릅니다")
    for rel, d in files.items():
        if not st.manifest_path_ok(rel) or not isinstance(d, dict):
            raise UpdateError(f"판 목록의 경로가 잘못되었습니다: {rel!r}")


def _write_plan(staging, version, cur_man, new_man, man_bytes):
    fetch, remove, new = plan_files(cur_man["files"], new_man["files"])
    with open(os.path.join(staging, "manifest.json"), "wb") as f:
        f.write(man_bytes)
    with open(os.path.join(staging, "plan.json"), "w", encoding="utf-8") as f:
        json.dump({"version": version, "from": cur_man.get("version"), "fetch": fetch, "remove": remove, "new": new}, f, ensure_ascii=False)
    return fetch, remove


def _need_bytes(cur_man, new_man, fetch, remove):
    new_sz = sum(int(new_man["files"][r].get("size") or 0) for r in fetch)
    old_sz = sum(int((cur_man["files"].get(r) or {}).get("size") or 0) for r in fetch + remove)
    return new_sz + old_sz + DISK_MARGIN


def fetch_release(version, program_root, staging, base_url=None, get=http_get, pub=None):
    """새 판의 manifest·서명을 받아 확인하고, 바뀐 파일만 staging 에 받는다. 틀리면 staging 을 지우고 UpdateError."""
    base = (base_url or UPDATE_BASE_URL).rstrip("/")
    shutil.rmtree(staging, ignore_errors=True)
    try:
        man_bytes = get(f"{base}/releases/{version}/manifest.json")
        sig = get(f"{base}/releases/{version}/manifest.sig")
        key = update_sign.public_key() if pub is None else pub
        try:
            sig_bytes = bytes.fromhex(sig.decode("ascii").strip())
        except Exception:
            sig_bytes = b""
        if not key or not update_sign.verify(key, man_bytes, sig_bytes):
            raise UpdateError("판 서명이 맞지 않습니다 - 받지 않습니다")
        new_man = json.loads(man_bytes.decode("utf-8"))
        _check_manifest(new_man, version)
        cur_man = _read_manifest(program_root)
        if (new_man.get("runtime") or {}) != (cur_man.get("runtime") or {}):
            raise UpdateError("파이썬이 바뀐 판입니다 - 설치 파일로 깔아야 합니다")
        fetch, remove, _ = plan_files(cur_man["files"], new_man["files"])
        os.makedirs(update_dir(), exist_ok=True)
        need = _need_bytes(cur_man, new_man, fetch, remove)
        free = shutil.disk_usage(update_dir()).free
        if free < need:
            raise UpdateError(f"디스크 여유가 모자랍니다 ({need // (1 << 20)}MB 필요, {free // (1 << 20)}MB 남음)")
        os.makedirs(os.path.join(staging, "files"), exist_ok=True)
        for rel in fetch:
            want = new_man["files"][rel]
            data = get(f"{base}/blobs/{want['sha256']}")
            if len(data) != int(want.get("size") or -1) or hashlib.sha256(data).hexdigest() != want["sha256"]:
                raise UpdateError(f"받은 파일이 판 목록과 다릅니다: {rel}")
            full = os.path.join(staging, "files", *rel.split("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "wb") as f:
                f.write(data)
        _write_plan(staging, version, cur_man, new_man, man_bytes)
        return new_man
    except UpdateError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateError(f"받기 실패 ({type(e).__name__}: {e})"[:200]) from None


def backup_version():
    try:
        return str(_read_manifest(path("backup")).get("version") or "") or None
    except Exception:
        return None


def stage_rollback(program_root, staging):
    """[이전 판으로 되돌리기]: 보관본을 staging 으로 복사한다 (보관본은 그대로 - 실패해도 남는다)."""
    shutil.rmtree(staging, ignore_errors=True)
    try:
        bman_path = path("backup", st.MANIFEST_NAME)
        with open(bman_path, "rb") as f:
            man_bytes = f.read()
        bman = json.loads(man_bytes.decode("utf-8"))
        _check_manifest(bman)
        cur_man = _read_manifest(program_root)
        fetch, remove, _ = plan_files(cur_man["files"], bman["files"])
        os.makedirs(os.path.join(staging, "files"), exist_ok=True)
        for rel in fetch:
            src = path("backup", "files", *rel.split("/"))
            if not os.path.isfile(src) or st.file_digest(src)["sha256"] != bman["files"][rel]["sha256"]:
                raise UpdateError(f"보관본에 {rel} 이(가) 없거나 다릅니다 - 되돌릴 수 없습니다")
            dst = os.path.join(staging, "files", *rel.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
        _write_plan(staging, bman.get("version"), cur_man, bman, man_bytes)
        return bman
    except UpdateError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateError(f"보관본을 읽지 못했습니다 ({type(e).__name__})") from None


def live_view():
    s, b = read_state(), backup_version()
    if not s and not b:
        return None
    return {"state": s.get("state"), "target": s.get("target"), "from": s.get("from"), "at": s.get("at"),
            "reason": s.get("reason"), "backup": b}


def health_local():
    """샌드박스 시험용: 로그인 없이 판 점검만으로 '살아 있음' - 표시 파일 update\\health_local (관리자·SYSTEM 만 쓰는 폴더).
    환경 변수가 아니라 파일인 까닭: 작업 스케줄러가 띄우는 에이전트는 새 기계 환경 변수를 늦게 받는다."""
    return os.path.isfile(path("health_local"))


def mark_alive(install):
    """새로 켜진 에이전트가 판 점검(과 첫 로그인)을 넘겼을 때 부른다. 업데이트 중이 아니면 아무것도 안 한다."""
    if read_state().get("state") not in ("applying", "rolling_back"):
        return False
    st.write_json_atomic(path("alive.json"), {"version": install.get("version"), "state": install.get("state"),
                                              "at": now_text(), "pid": os.getpid()})
    return True
```

- [ ] **Step 4: 통과 확인**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe tests/test_rpa_update.py`
Expected: 모두 PASS, `실패: 없음`

- [ ] **Step 5: 커밋**

```bash
git add rpa_update.py tests/test_rpa_update.py
git commit -m "자동 업데이트 2: PC 핵심 - 바뀐 파일만 받기·서명·지문 확인·상태·되돌리기 준비"
```

---

### Task 3: 도우미 (`update_helper.py`) - 바꾸기·3분 점검·되돌리기·재부팅 복구

**Files:**
- Create: `update_helper.py`
- Test: `tests/test_update_helper.py`

**Interfaces:**
- Consumes: `rpa_update.read_state/write_state/path/log/now_text/HEALTH_WAIT_SEC`, staging 모양 (Task 2).
- Produces: `update_helper.main(ops=None) -> int`, `update_helper.Ops` (진짜 동작: `end_agent()`, `after_install(program_dir) -> int`, `set_display_version(version)`, `delete_helper_task()`, `sleep(sec)`), `update_helper.apply(state, ops)`, `update_helper.rollback(state, ops, reason)`, `update_helper.restore(program_dir, backup_new, plan)`, `update_helper._move(src, dst)` (시험이 바꿔 끼운다).
- `state.json` 이 `ready` 일 때 필요한 칸 (Task 5 의 handoff 가 적는다): `{"state": "ready", "mode": "update"|"rollback", "target", "from", "program_dir", "staging", "at"}`.

- [ ] **Step 1: 실패하는 시험**

```python
# tests/test_update_helper.py
# -*- coding: utf-8 -*-
"""도우미 (설계 7절). 가짜 Program Files·가짜 작업(ops) - 진짜 예약 작업·레지스트리는 안 건드린다."""
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
tmp = tempfile.mkdtemp(prefix="rpa_helper_")
os.environ["RPA_PROGRAMDATA"] = os.path.join(tmp, "pd")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rpa_status as st  # noqa: E402
import rpa_update as up  # noqa: E402
import update_helper as uh  # noqa: E402

fails = []


def check(cond, what):
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        fails.append(what)


PROG = os.path.join(tmp, "prog")


def put(root, rel, text):
    full = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(text)


def read(root, rel):
    full = os.path.join(root, *rel.split("/"))
    return open(full, encoding="utf-8").read() if os.path.isfile(full) else None


def man(version, files):
    """진짜 지문 (7절의 stage_rollback 이 보관본 지문을 확인한다)."""
    return {"format": 1, "version": version, "runtime": {"python": "3.14.7"},
            "files": {r: {"sha256": hashlib.sha256(t.encode("utf-8")).hexdigest(), "size": len(t.encode("utf-8"))} for r, t in files.items()}}


A = {"a.py": "A1", "b.py": "B1", "keep.py": "K"}
B = {"a.py": "A2", "c.py": "C2", "keep.py": "K"}


def setup_a_and_staged_b(mode="update"):
    """프로그램 폴더 = 판 A, staging = 판 B (Task 2 가 남기는 모양), state = ready."""
    shutil.rmtree(PROG, ignore_errors=True); shutil.rmtree(up.update_dir(), ignore_errors=True)
    for r, t in A.items():
        put(PROG, r, t)
    put(PROG, "user_note.txt", "목록 밖 파일")
    with open(os.path.join(PROG, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(man("2026.10.07-1", A), f)
    stg = up.path("staging")
    for r in ("a.py", "c.py"):
        put(os.path.join(stg, "files"), r, B[r])
    with open(os.path.join(stg, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(man("2026.10.07-2", B), f)
    with open(os.path.join(stg, "plan.json"), "w", encoding="utf-8") as f:
        json.dump({"version": "2026.10.07-2", "from": "2026.10.07-1", "fetch": ["a.py", "c.py"], "remove": ["b.py"], "new": ["c.py"]}, f)
    up.write_state({"state": "ready", "mode": mode, "target": "2026.10.07-2", "from": "2026.10.07-1",
                    "program_dir": PROG, "staging": stg, "at": up.now_text()})


class FakeOps:
    """after_install 은 에이전트가 켜진 것을 흉내 낸다: good 이면 프로그램 폴더 manifest 의 판으로 alive.json 을 적는다."""

    def __init__(self, good=("2026.10.07-2", "2026.10.07-1")):
        self.good, self.calls = set(good), []

    def end_agent(self):
        self.calls.append("end")

    def after_install(self, program_dir):
        v = json.load(open(os.path.join(program_dir, "manifest.json"), encoding="utf-8"))["version"]
        self.calls.append(f"after:{v}")
        if v in self.good:
            up.mark_alive({"version": v, "state": "ok"})
        return 0

    def set_display_version(self, v):
        self.calls.append(f"ver:{v}")

    def delete_helper_task(self):
        self.calls.append("deltask")

    def sleep(self, sec):
        pass


uh.HEALTH_POLL_SEC = 0
uh.HEALTH_WAIT_SEC = 0.05

print("=== 1. 성공 ===")
setup_a_and_staged_b()
ops = FakeOps()
check(uh.main(ops) == 0, "도우미 끝 (0)")
s = up.read_state()
check(read(PROG, "a.py") == "A2" and read(PROG, "c.py") == "C2" and read(PROG, "b.py") is None and read(PROG, "keep.py") == "K",
      "새 판 파일로 바뀌고 없어진 파일은 치웠다")
check(read(PROG, "user_note.txt") == "목록 밖 파일", "목록 밖 파일은 그대로")
check(json.load(open(os.path.join(PROG, "manifest.json"), encoding="utf-8"))["version"] == "2026.10.07-2", "manifest 도 새 판")
check(s["state"] == "done" and s["target"] == "2026.10.07-2" and s["from"] == "2026.10.07-1", f"상태 done ({s})")
check(read(up.path("backup", "files"), "a.py") == "A1" and read(up.path("backup", "files"), "b.py") == "B1"
      and up.backup_version() == "2026.10.07-1" and not os.path.exists(up.path("backup_new")), "직전 판(A)의 바뀐·치운 파일을 보관")
check(not os.path.exists(up.path("staging")) and not os.path.exists(up.path("alive.json")), "staging·alive 정리")
check(ops.calls == ["end", "ver:2026.10.07-2", "after:2026.10.07-2", "deltask"], f"순서 ({ops.calls})")

print("\n=== 2. 3분 점검 실패 → 되돌리기 ===")
setup_a_and_staged_b()
ops = FakeOps(good=("2026.10.07-1",))
uh.main(ops)
s = up.read_state()
check(read(PROG, "a.py") == "A1" and read(PROG, "b.py") == "B1" and read(PROG, "c.py") is None, "옛 판 파일 그대로 돌아왔다")
check(json.load(open(os.path.join(PROG, "manifest.json"), encoding="utf-8"))["version"] == "2026.10.07-1", "manifest 도 옛 판")
check(s["state"] == "rolled_back" and "3분" in (s.get("reason") or "") and "설치 파일" not in s["reason"], f"rolled_back + 까닭 ({s.get('reason')})")
check(ops.calls == ["end", "ver:2026.10.07-2", "after:2026.10.07-2", "end", "ver:2026.10.07-1", "after:2026.10.07-1", "deltask"], f"순서 ({ops.calls})")
check(not os.path.exists(up.path("backup_new")) and not os.path.exists(up.path("staging")), "바꾸던 보관·staging 정리")

print("\n=== 3. 새 판·옛 판 모두 점검 실패 (Review Focus 5) ===")
setup_a_and_staged_b()
ops = FakeOps(good=())
uh.main(ops)
s = up.read_state()
check(s["state"] == "rolled_back" and "설치 파일로 다시 설치" in s["reason"] and read(PROG, "a.py") == "A1", f"파일은 옛 판, 까닭에 다시 설치 안내 ({s['reason']})")
check(ops.calls.count("after:2026.10.07-1") == 1, "되돌리기를 되풀이하지 않는다")

print("\n=== 4. 옮기는 도중 어디서 끊겨도 되돌리면 옛 판 (Review Focus 2) ===")


class Crash(BaseException):
    pass


real_move = uh._move
for n in range(1, 5):            # 옮기기 = 보관 2번(a·b, c 는 원래 없음) + 넣기 2번(a·c) - 그 모든 자리에서
    setup_a_and_staged_b()
    count = [0]

    def boom(src, dst, n=n):
        count[0] += 1
        if count[0] == n:
            raise Crash()
        real_move(src, dst)

    uh._move = boom
    try:
        uh.main(FakeOps())
    except Crash:
        pass
    finally:
        uh._move = real_move
    mid = up.read_state()["state"]
    uh.main(FakeOps(good=("2026.10.07-1",)))          # 다음 로그온 (--recover)
    s = up.read_state()
    check(read(PROG, "a.py") == "A1" and read(PROG, "b.py") == "B1" and read(PROG, "c.py") is None
          and read(PROG, "keep.py") == "K" and s["state"] == "rolled_back",
          f"{n}번째 옮기기에서 끊김({mid}) → 다음 로그온에 옛 판 ({s['state']})")
for where in ("ver", "after"):
    setup_a_and_staged_b()
    ops = FakeOps()
    setattr(ops, "set_display_version" if where == "ver" else "after_install", lambda *a: (_ for _ in ()).throw(Crash()))
    try:
        uh.main(ops)
    except Crash:
        pass
    uh.main(FakeOps(good=("2026.10.07-1",)))
    check(read(PROG, "a.py") == "A1" and up.read_state()["state"] == "rolled_back", f"{where} 단계에서 끊김 → 되돌림")

print("\n=== 5. 되돌리는 도중 끊겨도 이어서 되돌린다 ===")
setup_a_and_staged_b()
ops = FakeOps(good=())
calls = [0]
orig_after = ops.after_install


def after_then_crash(p):
    calls[0] += 1
    if calls[0] == 2:          # 첫 번째 = 새 판 점검, 두 번째 = 되돌린 옛 판 - 여기서 끊김
        raise Crash()
    return orig_after(p)


ops.after_install = after_then_crash
try:
    uh.main(ops)
except Crash:
    pass
check(up.read_state()["state"] == "rolling_back", "되돌리는 중 표시가 남았다")
uh.main(FakeOps(good=("2026.10.07-1",)))
check(read(PROG, "a.py") == "A1" and up.read_state()["state"] == "rolled_back", "다음 로그온에 되돌리기를 마친다")

print("\n=== 6. 할 일이 없으면 작업만 지운다 ===")
up.write_state({"state": "done"})
ops = FakeOps()
check(uh.main(ops) == 0 and ops.calls == ["deltask"], "done 이면 작업만 지움")

print("\n=== 7. [이전 판으로 되돌리기] 도 같은 길 - 보관본은 방금 판이 된다 ===")
setup_a_and_staged_b()
uh.main(FakeOps())                                    # A → B (보관 A)
up.stage_rollback(PROG, up.path("staging"))           # 보관 A → staging
up.write_state({"state": "ready", "mode": "rollback", "target": "2026.10.07-1", "from": "2026.10.07-2",
                "program_dir": PROG, "staging": up.path("staging"), "at": up.now_text()})
uh.main(FakeOps())
check(read(PROG, "a.py") == "A1" and read(PROG, "b.py") == "B1" and read(PROG, "c.py") is None and up.backup_version() == "2026.10.07-2",
      "B → A, 보관본은 B (다시 앞으로 갈 수 있다)")

shutil.rmtree(tmp, ignore_errors=True)
print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe tests/test_update_helper.py`
Expected: `ModuleNotFoundError: No module named 'update_helper'`

- [ ] **Step 3: 구현**

```python
# update_helper.py
# -*- coding: utf-8 -*-
"""자동 업데이트 도우미 (설계 7절). 프로그램 폴더 밖 %ProgramData%\\AFTER MARKET\\RPA\\update\\runner 에서
복사한 파이썬으로 돈다 - 일회용 예약 작업 '\\AFTER MARKET\\RPA Update' 가 띄운다 (지금 한 번 + 로그온 때마다).

    state.json  ready          → apply  (보관 → 바꾸기 → 에이전트 켜기 → 3분 점검 → 성공 / 되돌리기)
                applying       → rollback (바꾸는 도중 끊겼다 - 정전·재부팅)
                rolling_back   → rollback (되돌리는 도중 끊겼다 - 이어서)
                그 밖           → 할 일 없음
    끝나면 예약 작업을 지운다.

되돌리기는 몇 번을 다시 해도 같은 결과다 (옮기기 하나하나가 끊겨도 된다):
  보관(backup_new)에 있는 파일 → 제자리로, 새로 생긴 파일(plan.new) 중 보관에 없는 것 → 지운다."""
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rpa_status as st  # noqa: E402
import rpa_update as up  # noqa: E402

HEALTH_WAIT_SEC = up.HEALTH_WAIT_SEC
HEALTH_POLL_SEC = 2
AGENT_TASK = r"AFTER MARKET\RPA Agent"
HELPER_TASK = r"AFTER MARKET\RPA Update"
AGENT_MUTEX = r"Local\AFTER_MARKET_RPA_AGENT"
UNINSTALL_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{C3F7A2B4-5E81-4D2A-9B6C-7A1E0F3D8B52}_is1"
CREATE_NO_WINDOW = 0x08000000


def _move(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    os.replace(src, dst)


def _full(root, rel):
    return os.path.join(root, *rel.split("/"))


class Ops:
    """진짜 동작 - 시험은 같은 이름의 가짜를 넘긴다."""

    def _run(self, args, timeout=120):
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout, creationflags=CREATE_NO_WINDOW).returncode

    def end_agent(self):
        self._run(["schtasks", "/End", "/TN", AGENT_TASK])
        until = time.monotonic() + 30
        while st.lock_held(AGENT_MUTEX) and time.monotonic() < until:
            time.sleep(0.5)

    def after_install(self, program_dir):
        py = os.path.join(program_dir, "python", "pythonw.exe")
        return self._run([py, os.path.join(program_dir, "rpa_settings.py"), "--after-install", "--no-window"], timeout=300)

    def set_display_version(self, version):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, UNINSTALL_KEY, 0, winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
                winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ, version)
        except OSError:
            pass                                 # 제거 목록 글자일 뿐 - 업데이트를 막지 않는다

    def delete_helper_task(self):
        self._run(["schtasks", "/Delete", "/TN", HELPER_TASK, "/F"])

    def sleep(self, sec):
        time.sleep(sec)


def _plan(state):
    with open(os.path.join(state["staging"], "plan.json"), encoding="utf-8") as f:
        return json.load(f)


def wait_alive(version, since, ops):
    until = time.monotonic() + HEALTH_WAIT_SEC
    while True:
        a = st.read_json(up.path("alive.json")) or {}
        if a.get("version") == version and a.get("state") == "ok" and str(a.get("at") or "") >= since:
            return True
        if time.monotonic() >= until:
            return False
        ops.sleep(HEALTH_POLL_SEC)


def restore(program_dir, backup_new, plan):
    for rel in plan["fetch"] + plan["remove"]:
        b = _full(os.path.join(backup_new, "files"), rel)
        if os.path.isfile(b):
            _move(b, _full(program_dir, rel))
        elif rel in plan["new"] and os.path.isfile(_full(program_dir, rel)):
            os.remove(_full(program_dir, rel))
    old_man = os.path.join(backup_new, st.MANIFEST_NAME)
    if os.path.isfile(old_man):
        shutil.copy2(old_man, os.path.join(program_dir, st.MANIFEST_NAME))


def apply(state, ops):
    prog, stg, bnew = state["program_dir"], state["staging"], up.path("backup_new")
    plan = _plan(state)
    shutil.rmtree(bnew, ignore_errors=True)                   # 'applying' 을 적기 전에 - 끊긴 뒤 되돌리기가 남의 보관을 쓰지 않게
    try:
        os.remove(up.path("alive.json"))
    except OSError:
        pass
    started = up.now_text()
    state = {**state, "state": "applying", "started_at": started, "at": started}
    up.write_state(state)
    up.log(f"바꾸기 시작 {state['from']} → {state['target']} ({state.get('mode')}) 받을 {len(plan['fetch'])}·치울 {len(plan['remove'])}")
    ops.end_agent()
    os.makedirs(os.path.join(bnew, "files"), exist_ok=True)
    shutil.copy2(os.path.join(prog, st.MANIFEST_NAME), os.path.join(bnew, st.MANIFEST_NAME))
    for rel in plan["fetch"] + plan["remove"]:
        if os.path.isfile(_full(prog, rel)):
            _move(_full(prog, rel), _full(os.path.join(bnew, "files"), rel))
    for rel in plan["fetch"]:
        _move(_full(os.path.join(stg, "files"), rel), _full(prog, rel))
    shutil.copy2(os.path.join(stg, "manifest.json"), os.path.join(prog, st.MANIFEST_NAME))
    ops.set_display_version(state["target"])
    ops.after_install(prog)
    if not wait_alive(state["target"], started, ops):
        return rollback(state, ops, f"새 판이 3분 안에 정상으로 켜지지 않았습니다 ({state['target']})")
    shutil.rmtree(up.path("backup"), ignore_errors=True)
    os.replace(bnew, up.path("backup"))
    shutil.rmtree(stg, ignore_errors=True)
    try:
        os.remove(up.path("alive.json"))
    except OSError:
        pass
    up.write_state({"state": "done", "mode": state.get("mode"), "target": state["target"], "from": state["from"],
                    "at": up.now_text(), "reason": None})
    up.log(f"성공 {state['target']}")
    return 0


def rollback(state, ops, reason):
    prog, bnew = state["program_dir"], up.path("backup_new")
    started = up.now_text()
    state = {**state, "state": "rolling_back", "reason": reason, "at": started}
    up.write_state(state)
    up.log(f"되돌리기: {reason}")
    ops.end_agent()
    try:
        plan = _plan(state)
    except Exception:
        plan = None                              # staging 이 없다 = 아직 아무것도 안 옮겼다
    if plan is not None:
        restore(prog, bnew, plan)
    ops.set_display_version(state["from"])
    ops.after_install(prog)
    ok = wait_alive(state["from"], started, ops)
    shutil.rmtree(bnew, ignore_errors=True)
    shutil.rmtree(state.get("staging") or up.path("staging"), ignore_errors=True)
    final = reason if ok else f"{reason} / 옛 판도 정상으로 켜지지 않았습니다 - 설치 파일로 다시 설치하세요"
    up.write_state({"state": "rolled_back", "mode": state.get("mode"), "target": state["target"], "from": state["from"],
                    "at": up.now_text(), "reason": final})
    up.log(f"되돌림 끝 ({'옛 판 정상' if ok else '옛 판도 점검 실패'})")
    return 0


def main(ops=None):
    ops = ops or Ops()
    state = up.read_state()
    try:
        if state.get("state") == "ready":
            apply(state, ops)
        elif state.get("state") == "applying":
            rollback(state, ops, "업데이트 도중 끊겼습니다 (정전·재부팅 등)")
        elif state.get("state") == "rolling_back":
            rollback(state, ops, state.get("reason") or "되돌리는 도중 끊겼습니다")
    finally:
        if up.read_state().get("state") not in ("applying", "rolling_back"):
            ops.delete_helper_task()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

주의: `finally` 에서 작업을 지우는 조건 - 끊김(예외)으로 `applying`/`rolling_back` 이 남았으면 지우지 않는다 (다음 로그온에 다시 떠야 한다). 시험 4·5절이 이것을 본다.

- [ ] **Step 4: 통과 확인**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe tests/test_update_helper.py`
Expected: 모두 PASS, `실패: 없음`

- [ ] **Step 5: 커밋**

```bash
git add update_helper.py tests/test_update_helper.py
git commit -m "자동 업데이트 3: 도우미 - 보관·바꾸기·3분 점검·되돌리기·끊긴 뒤 복구"
```

---

### Task 4: 도우미 작업 등록 (`rpa_settings.py`) · 실행 막기 (`rpa_dashboard.py`)

**Files:**
- Modify: `rpa_settings.py` (자동 시작 작업 절, `task_xml` 아래)
- Modify: `rpa_dashboard.py` (`launch` 잠금 안, `Scheduler.busy`)
- Test: `tests/test_settings.py`, `tests/test_schedule_slots.py`

**Interfaces:**
- Consumes: `rpa_update.busy_reason/BUSY_TEXT` (Task 2).
- Produces: `rpa_settings.HELPER_TASK_NAME = r"AFTER MARKET\RPA Update"`, `rpa_settings.helper_task_xml(user, runner_dir) -> str`, `rpa_settings.register_helper_task(runner_dir, run=run_quiet, user=None)`, `rpa_settings.run_helper_task(run=run_quiet)`, `rpa_settings.delete_helper_task(run=run_quiet)`.

- [ ] **Step 1: 실패하는 시험** - `tests/test_settings.py` 끝(요약 줄 앞)에 붙인다:

```python
print("\n=== 자동 업데이트 도우미 작업 (설계 7절) ===")
x = rs.helper_task_xml("PC\\user", r"C:\ProgramData\AFTER MARKET\RPA\update\runner")
check(r"<Command>C:\ProgramData\AFTER MARKET\RPA\update\runner\python\pythonw.exe</Command>" in x
      and '"C:\\ProgramData\\AFTER MARKET\\RPA\\update\\runner\\update_helper.py"' in x, "도우미는 runner 의 파이썬으로 (프로그램 폴더 밖)")
check("<LogonTrigger>" in x and "<RunLevel>HighestAvailable</RunLevel>" in x and "<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>" in x,
      "로그온 때마다 · 가장 높은 권한 · 시간 제한 없음 (끊긴 업데이트를 다음 로그온에 되돌린다)")
check("background.py" not in x and rs.HELPER_TASK_NAME == r"AFTER MARKET\RPA Update" and rs.HELPER_TASK_NAME != rs.TASK_NAME,
      "에이전트 작업과 다른 이름·다른 명령 - /End 에 같이 안 죽는다 (Review Focus 1)")
ran = []
rs.register_helper_task(r"C:\r", run=lambda a: (ran.append(a), (0, ""))[1], user="PC\\user")
rs.run_helper_task(run=lambda a: (ran.append(a), (0, ""))[1])
rs.delete_helper_task(run=lambda a: (ran.append(a), (0, ""))[1])
check([a[:3] for a in ran] == [["schtasks", "/Create", "/TN"], ["schtasks", "/Run", "/TN"], ["schtasks", "/Delete", "/TN"]]
      and all(rs.HELPER_TASK_NAME in a for a in ran), f"등록·실행·지우기 ({[a[:4] for a in ran]})")
```

`tests/test_schedule_slots.py` 의 `=== 9.` 절 뒤에 붙인다:

```python
print("\n=== 10. 업데이트 대기 중이면 새 실행을 안 띄운다 (Review Focus 4) ===")
import rpa_update as up  # noqa: E402
d._active["until"] = 0; d._active["proc"] = None
os.environ["RPA_PROGRAMDATA"] = os.path.join(tmp, "pd")
for state in up.BUSY_STATES:
    up.write_state({"state": state})
    try:
        d.launch("routine", "manual:admin"); check(False, f"{state}: 띄움")
    except RuntimeError as e:
        check(str(e) == "업데이트 중이라 잠시 실행할 수 없습니다", f"{state}: 단추 실행 거절 ({e})")
    check(sched.busy() == "업데이트 중이라 잠시 실행할 수 없습니다", f"{state}: 예약·반복도 기다린다")
up.write_state({"state": "done"})
check(sched.busy() is None, "done 이면 다시 띄울 수 있다")
os.environ.pop("RPA_PROGRAMDATA")
```

(`tmp`·`sched`·`d` 는 그 파일에 이미 있는 이름이다 - 없으면 그 파일의 같은 뜻 이름으로 바꾸고 `Ruling:` 을 남긴다.)

- [ ] **Step 2: 실패 확인**

Run: `bash .superpowers/sdd/2026-10-07-auto-update/pc_tests.sh test_settings test_schedule_slots`
Expected: 둘 다 실패 (`AttributeError: module 'rpa_settings' has no attribute 'helper_task_xml'`, 거절 안 됨)

- [ ] **Step 3: 구현** - `rpa_settings.py` 의 `delete_task` 아래:

```python
HELPER_TASK_NAME = r"AFTER MARKET\RPA Update"   # 자동 업데이트 도우미 - 바꾸는 동안만 있다 (update_helper.py 가 끝나면 지운다)


def helper_task_xml(user, runner_dir):
    """도우미 작업: 프로그램 폴더 밖 runner 의 파이썬으로 update_helper.py. 지금 /Run 으로 한 번 + 로그온 때마다
    (바꾸는 도중 꺼지면 다음 로그온에 되돌린다). 에이전트 작업과 이름이 달라 그 /End 에 같이 죽지 않는다."""
    xml = task_xml(user, runner_dir)
    py = os.path.join(runner_dir, "python", "pythonw.exe")
    script = os.path.join(runner_dir, "update_helper.py")
    start = xml.index("<Actions")
    return (xml[:start].replace("AFTER MARKET RPA 에이전트 - 윈도우 로그인 때 창 없이 켠다 (설치 마법사가 등록)",
                                "AFTER MARKET RPA 업데이트 도우미 - 업데이트가 끝나면 스스로 지운다")
            + f"""<Actions Context="Author">
    <Exec><Command>{escape(py)}</Command><Arguments>"{escape(script)}"</Arguments><WorkingDirectory>{escape(runner_dir)}</WorkingDirectory></Exec>
  </Actions>
</Task>
""")


def register_helper_task(runner_dir, run=run_quiet, user=None):
    path = os.path.join(runner_dir, "helper_task.xml")
    os.makedirs(runner_dir, exist_ok=True)
    with open(path, "w", encoding="utf-16") as f:
        f.write(helper_task_xml(user or process_user(), runner_dir))
    try:
        code, out = run(["schtasks", "/Create", "/TN", HELPER_TASK_NAME, "/XML", path, "/F"])
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    if code != 0:
        raise RuntimeError(f"업데이트 도우미 작업을 등록하지 못했습니다: {out.strip()[-300:]}")


def run_helper_task(run=run_quiet):
    code, out = run(["schtasks", "/Run", "/TN", HELPER_TASK_NAME])
    if code != 0:
        raise RuntimeError(f"업데이트 도우미를 켜지 못했습니다: {out.strip()[-300:]}")


def delete_helper_task(run=run_quiet):
    run(["schtasks", "/Delete", "/TN", HELPER_TASK_NAME, "/F"])
```

(`task_xml(user, runner_dir)` 은 runner 에 `python\AFTER_MARKET_RPA_Supervisor.exe` 가 있으면 그걸 Command 로 쓰지만, Actions 부분을 통째로 갈아 끼우므로 상관없다.)

`rpa_dashboard.py` - 맨 위 import 에 `import rpa_update` 를 더하고, `launch` 의 잠금 안 `running = any_rpa_running()` 바로 앞에:

```python
        upd = rpa_update.busy_reason()     # 업데이트 대기·바꾸는 중 - 단추·예약·반복 모두 여기서 막힌다 (자동 업데이트 6절)
        if upd:
            raise RuntimeError(upd)
```

`Scheduler.busy` 의 첫 줄로:

```python
        upd = rpa_update.busy_reason()
        if upd:
            return upd
```

- [ ] **Step 4: 통과 확인**

Run: `bash .superpowers/sdd/2026-10-07-auto-update/pc_tests.sh test_settings test_schedule_slots test_schedule_repeat test_dashboard_auth test_start_failure`
Expected: 모두 `실패: 없음`

- [ ] **Step 5: 커밋**

```bash
git add rpa_settings.py rpa_dashboard.py tests/test_settings.py tests/test_schedule_slots.py
git commit -m "자동 업데이트 4: 도우미 예약 작업, 업데이트 중엔 새 실행을 안 띄운다"
```

---

### Task 5: 에이전트 - 명령·업데이트 스레드·넘기기·살아 있음

**Files:**
- Modify: `rpa_update.py` (`run_update`, `handoff` 추가)
- Modify: `firebase/agent/agent.py` (`KNOWN_TYPES`, `decide`, `real_actions`, `run`, `pump`)
- Test: `tests/test_rpa_update.py` (6절), `firebase/tests/test_agent.py`

**Interfaces:**
- Consumes: Task 2 (`fetch_release`, `stage_rollback`, `write_state`, `read_state`, `ACTIVE_STATES`, `backup_version`, `mark_alive`, `health_local`, `live_view`), Task 4 (`rpa_settings.register_helper_task/run_helper_task`), `rpa_dashboard._launch_lock/any_rpa_running/launch_state`, `rpa_status.observer_open/check_install/program_dir`.
- Produces:
  - `rpa_update.RUNNER_FILES = ("update_helper.py", "rpa_update.py", "rpa_status.py", "update_sign.py")`
  - `rpa_update.handoff(program_root, state: dict, register, run_task) -> None` - runner 복사, `state.json` 을 `ready` 로, 작업 등록·실행
  - `rpa_update.run_update(version, mode, program_root, idle, register, run_task, fetch=fetch_release, sleep=time.sleep) -> None` - 받기/준비 → `waiting` → `idle()` 이 참일 때까지 2초마다 → handoff. 실패는 `failed {reason}`
  - `agent.ADMIN_ONLY_TYPES = ("update", "rollback")`, `agent.ADMIN_TOOL_BY = "admin-tool"`, `agent.VERSION_RE`
  - `agent.real_actions(policy=None, limits=None, start_update=None)` - `start_update(version, mode)` 기본은 데몬 스레드로 `run_update`
  - `live.update` = `rpa_update.live_view()`

- [ ] **Step 1: 실패하는 시험** - `tests/test_rpa_update.py` 의 정리 줄(`shutil.rmtree(tmp…)`) 앞에 붙인다:

```python
print("\n=== 6. 받기 → 대기 → 넘기기 (run_update) ===")
for rel, text in (("a.py", "A1"), ("b.py", "B1")):
    put(PROG, rel, text)
for rel in ("c.py",):
    os.remove(os.path.join(PROG, rel)) if os.path.exists(os.path.join(PROG, rel)) else None
with open(os.path.join(PROG, "manifest.json"), "w", encoding="utf-8") as f:
    json.dump(MAN_A, f)
for rel in up.RUNNER_FILES:
    put(PROG, rel, f"# {rel}")
put(PROG, "python/pythonw.exe", "fake")
up.write_state({}); shutil.rmtree(up.path("backup"), ignore_errors=True)
seen, idle_calls, reg = [], [0], []


def idle():
    idle_calls[0] += 1
    seen.append(up.read_state()["state"])
    return idle_calls[0] >= 3          # 두 번은 RPA 가 돌고 있다


up.run_update("2026.10.07-2", "update", PROG, idle, register=lambda r: reg.append(("reg", r)), run_task=lambda: reg.append(("run",)),
              fetch=lambda v, p, s: up.fetch_release(v, p, s, base_url=BASE, get=get, pub=PK), sleep=lambda s: None)
s = up.read_state()
check(seen == ["waiting"] * 3, f"받은 뒤 RPA 가 쉴 때까지 waiting ({seen})")
check(s["state"] == "ready" and s["mode"] == "update" and s["target"] == "2026.10.07-2" and s["from"] == "2026.10.07-1"
      and s["program_dir"] == PROG and s["staging"] == up.path("staging"), f"넘길 때 ready + 도우미가 쓸 칸 ({s})")
check(all(os.path.isfile(up.path("runner", r)) for r in up.RUNNER_FILES) and os.path.isfile(up.path("runner", "python", "pythonw.exe")),
      "도우미와 파이썬을 runner 로 복사")
check(reg == [("reg", up.path("runner")), ("run",)], f"작업 등록 → 실행 ({reg})")
up.write_state({})
up.run_update("2026.10.07-2", "update", PROG, idle, register=lambda r: None, run_task=lambda: None,
              fetch=lambda v, p, s: (_ for _ in ()).throw(up.UpdateError("판 서명이 맞지 않습니다 - 받지 않습니다")), sleep=lambda s: None)
check(up.read_state()["state"] == "failed" and "서명" in up.read_state()["reason"], "받기 실패면 failed + 까닭 (대기도 안 한다)")
up.write_state({})
up.run_update("2026.10.07-2", "update", PROG, lambda: True, register=lambda r: (_ for _ in ()).throw(RuntimeError("등록 실패")),
              run_task=lambda: None, fetch=lambda v, p, s: up.fetch_release(v, p, s, base_url=BASE, get=get, pub=PK), sleep=lambda s: None)
check(up.read_state()["state"] == "failed" and "등록 실패" in up.read_state()["reason"], "도우미를 못 띄우면 failed (실행 막기가 풀린다)")
```

`firebase/tests/test_agent.py` 의 7절(업체 정책) `finally` 다음, `8절` 앞에 새 절:

```python
print("\n7-2절 자동 업데이트 명령 (설계 6절)")
check(ag.decide({"state": "queued", "type": "update", "expires_at": NOW + 60, "by": "uid-of-admin"}, NOW)[0] == "bad",
      "관리 화면이 아닌 곳에서 온 update 는 버린다")
check(ag.decide({"state": "queued", "type": "rollback", "expires_at": NOW + 60, "by": "admin-tool"}, NOW)[0] == "run", "관리 화면의 rollback 은 돈다")
with tempfile.TemporaryDirectory() as d:
    os.environ["RPA_PROGRAMDATA"] = d
    try:
        import rpa_update as upd
        started = []
        acts = ag.real_actions(start_update=lambda v, m: started.append((v, m)))
        import rpa_status as st
        orig = st.check_install
        st.check_install = lambda root=None: {"version": "2026.10.07-4", "state": "ok"}
        try:
            for bad, why in (({"version": "../x"}, "판 번호"), ({"version": "2026.10.07-4"}, "이미")):
                try:
                    acts["update"](bad); check(False, f"거절 안 됨 {bad}")
                except RuntimeError as e:
                    check(why in str(e), f"update 거절: {why} ({e})")
            msg = acts["update"]({"version": "2026.10.07-5"})
            check(started == [("2026.10.07-5", "update")] and "예약" in msg, f"update → 스레드 시작 ({msg})")
            upd.write_state({"state": "waiting"})
            try:
                acts["update"]({"version": "2026.10.07-6"}); check(False, "업데이트 중 두 번째")
            except RuntimeError as e:
                check("이미 업데이트" in str(e), f"업데이트 중이면 거절 ({e})")
            upd.write_state({"state": "done"})
            try:
                acts["rollback"](None); check(False, "보관본 없이 되돌리기")
            except RuntimeError as e:
                check("이전 판" in str(e), f"보관본이 없으면 거절 ({e})")
            st.check_install = lambda root=None: {"version": "2026.10.07-4", "state": "mixed"}
            try:
                acts["update"]({"version": "2026.10.07-5"}); check(False, "mixed 인데 업데이트")
            except RuntimeError as e:
                check("판 구조" in str(e), f"판 구조가 어긋난 PC 는 거절 ({e})")
        finally:
            st.check_install = orig
    finally:
        os.environ.pop("RPA_PROGRAMDATA", None)
check("update" in ag.KNOWN_TYPES and "rollback" in ag.KNOWN_TYPES, "명령 종류에 update·rollback")
```

(`NOW` 는 test_agent.py 위쪽에 이미 있는 시각 상수 - 이름이 다르면 그 이름으로.)

- [ ] **Step 2: 실패 확인**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe tests/test_rpa_update.py` 와 `bash .superpowers/sdd/2026-10-07-auto-update/pc_tests.sh agent`
Expected: `AttributeError: module 'rpa_update' has no attribute 'RUNNER_FILES'` / agent 시험 실패

- [ ] **Step 3: 구현** - `rpa_update.py` 끝에:

```python
import time  # noqa: E402  (run_update 의 sleep 기본값)

RUNNER_FILES = ("update_helper.py", "rpa_update.py", "rpa_status.py", "update_sign.py")


def handoff(program_root, state, register, run_task):
    """도우미와 파이썬을 runner 로 복사하고 state 를 ready 로 적은 뒤 도우미 작업을 등록·실행한다.
    파이썬(python\\)은 업데이트가 바꾸지 않는다 (판 목록 밖) - 그래서 지금 것을 복사해 써도 된다."""
    runner = path("runner")
    shutil.rmtree(runner, ignore_errors=True)
    shutil.copytree(os.path.join(program_root, "python"), os.path.join(runner, "python"))
    for name in RUNNER_FILES:
        shutil.copy2(os.path.join(program_root, name), os.path.join(runner, name))
    write_state({**state, "state": "ready", "at": now_text()})
    register(runner)
    run_task()


def run_update(version, mode, program_root, idle, register, run_task, fetch=fetch_release, sleep=time.sleep):
    """에이전트의 업데이트 스레드. idle(): RPA·옵저버가 쉬나 (에이전트가 실행 잠금 안에서 본다)."""
    staging = path("staging")
    try:
        cur = _read_manifest(program_root).get("version")
        write_state({"state": "downloading", "mode": mode, "target": version, "from": cur, "at": now_text()})
        log(f"{'받기' if mode == 'update' else '되돌리기 준비'} {cur} → {version}")
        if mode == "rollback":
            stage_rollback(program_root, staging)
        else:
            fetch(version, program_root, staging)
        write_state({"state": "waiting", "mode": mode, "target": version, "from": cur, "at": now_text()})
        while not idle():
            sleep(2)
        handoff(program_root, {"mode": mode, "target": version, "from": cur, "program_dir": program_root, "staging": staging},
                register, run_task)
        log("도우미에게 넘김")
    except Exception as e:
        reason = str(e) if isinstance(e, UpdateError) else f"{type(e).__name__}: {e}"[:200]
        shutil.rmtree(staging, ignore_errors=True)
        write_state({"state": "failed", "mode": mode, "target": version, "from": read_state().get("from"),
                     "at": now_text(), "reason": reason})
        log(f"실패: {reason}")
```

`firebase/agent/agent.py`:

```python
KNOWN_TYPES = ("launch", "stop_erpia", "set_modules", "set_schedule", "set_presets", "resume_repeat", "update", "rollback")
ADMIN_ONLY_TYPES = ("update", "rollback")   # 관리 화면(Admin SDK)만 - DB 규칙의 type 목록에도 없다 (자동 업데이트 10절)
ADMIN_TOOL_BY = "admin-tool"
VERSION_RE = re.compile(r"\d{4}\.\d{2}\.\d{2}-\d+")
```

`decide` 의 type 검사 다음 줄:

```python
    if cmd.get("type") in ADMIN_ONLY_TYPES and cmd.get("by") != ADMIN_TOOL_BY:
        return "bad", "관리 화면에서만 보낼 수 있는 명령입니다"
```

`real_actions(policy=None, limits=None, start_update=None)` - 안쪽에 (맨 위 `import rpa_update as upd` 함께):

```python
    def default_start(version, mode):
        import threading
        import rpa_settings as rs

        def idle():
            with dash._launch_lock:          # launch 와 같은 잠금 - 이 안에서 쉬면 그 뒤로는 waiting 이 새 실행을 막는다
                return not dash.any_rpa_running() and dash.launch_state() is None and not st.observer_open()

        threading.Thread(target=upd.run_update, daemon=True, name="update",
                         args=(version, mode, st.program_dir(), idle, rs.register_helper_task, rs.run_helper_task)).start()

    start = start_update or default_start

    def check_can_update():
        if upd.read_state().get("state") in upd.ACTIVE_STATES:
            raise RuntimeError("이미 업데이트가 진행 중입니다")
        install = st.check_install()
        if install.get("state") != "ok":
            raise RuntimeError(f"판 구조가 맞지 않아 업데이트하지 않습니다 ({install.get('state')}) - 설치 파일로 다시 설치하세요")
        return install

    def do_update(args):
        version = (args or {}).get("version") if isinstance(args, dict) else None
        if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
            raise RuntimeError(f"판 번호가 잘못되었습니다 ({version})")
        install = check_can_update()
        if install.get("version") == version:
            raise RuntimeError("이미 최신 업데이트를 사용하고 있습니다")
        start(version, "update")
        return f"업데이트를 예약했습니다 ({install.get('version')} → {version}) - RPA 가 끝나면 바로 바뀝니다"

    def do_rollback(args):
        back = upd.backup_version()
        if not back:
            raise RuntimeError("되돌릴 이전 판이 없습니다")
        check_can_update()
        start(back, "rollback")
        return f"이전 판으로 되돌리기를 예약했습니다 ({back}) - RPA 가 끝나면 바로 바뀝니다"
```

반환 사전에 `"update": do_update, "rollback": do_rollback` 를 더한다.

`run()` - 맨 위 `import rpa_status as st` 다음 줄 (첫 로그인보다 앞 - 샌드박스의 가짜 계정은 로그인이 거부되어 `run` 이 곧 끝난다):

```python
    import rpa_update as upd
    alive = [False]
    if upd.health_local():                     # 샌드박스 시험: 로그인 없이 판 점검만 (자동 업데이트 계획 Task 9)
        alive[0] = upd.mark_alive(st.check_install())
```

`pump()` 안 `snap["version"] = install` 다음 줄에 `snap["update"] = upd.live_view()`, `body = json.dumps([...])` 목록 끝에 `snap.get("update")` 를 더하고, `up.push_heartbeat({...})` 바로 다음 줄에:

```python
                    if not alive[0] and install.get("state") == "ok":
                        alive[0] = upd.mark_alive(install)    # 업데이트 뒤 첫 접속 - 도우미의 3분 점검 (설계 7절 6)
```

- [ ] **Step 4: 통과 확인**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe tests/test_rpa_update.py` 와 `bash .superpowers/sdd/2026-10-07-auto-update/pc_tests.sh agent test_schedule_slots test_schedule_repeat`
Expected: 모두 통과 (`agent: N/N 통과`)

- [ ] **Step 5: 커밋**

```bash
git add rpa_update.py firebase/agent/agent.py tests/test_rpa_update.py firebase/tests/test_agent.py
git commit -m "자동 업데이트 5: 에이전트 update·rollback 명령, 받기→대기→도우미에게 넘기기, 첫 접속 때 살아 있음"
```

---

### Task 6: 판에 싣기 · 내보내기 도구 · `setup.js release-*`

**Files:**
- Modify: `tools/build_release.py` (`PROGRAM_FILES`)
- Create: `tools/publish_release.py`, `firebase/releases.json`
- Modify: `firebase/admin/ops.js`, `firebase/admin/setup.js`, `.gitignore`, `.graphifyignore`
- Test: `tests/test_publish_release.py` (새), `firebase/tests/check_setup.py`

**Interfaces:**
- Consumes: `update_sign.sign/keygen/secret_to_public` (Task 1).
- Produces:
  - `publish_release.KEY_PATH = firebase/admin/update_signing_key.txt` (64자 hex 한 줄), `SITE_DIR = firebase/releases_site`, `KEEP = 5`
  - `publish_release.keygen(key_path) -> str` (공개 열쇠 hex - 비밀 열쇠는 파일에만)
  - `publish_release.publish(version, release_dir, site_dir, key_path, memo="", stable=None, deploy=None, set_releases=None) -> dict` - 사이트 폴더에 `releases/<판>/manifest.json`·`manifest.sig`, `blobs/<sha256>` 를 더하고, 최근 5개+안정본만 남기고, `set_releases(list)` 로 DB 목록을 쓰고 `deploy()` 를 부른다. 돌려주는 값 `{"version", "kept": [...], "removed": [...], "bytes": N}`
  - `ops.releasesOf() -> {list: [{version, published_at, bytes, memo}], stable, newest}`, `ops.setReleases(list)` (newest = 가장 최근 published_at, stable 은 남아 있으면 그대로), `ops.setStable(version)`
  - `node setup.js releases` (보기, JSON 한 줄), `node setup.js release-set <json 파일>`, `node setup.js stable <판>`
  - RTDB `meta/releases = {list: {<판 키>: {version, published_at, bytes, memo}}, stable, newest}` (판 키 = `.` → `_`)

- [ ] **Step 1: 실패하는 시험**

```python
# tests/test_publish_release.py
# -*- coding: utf-8 -*-
"""판 내보내기 (설계 4절). 임시 배포 폴더·임시 사이트 폴더 - 배포·DB 는 가짜 함수."""
import io
import json
import os
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [REPO, os.path.join(REPO, "tools")]
import publish_release as pr  # noqa: E402
import rpa_status as st  # noqa: E402
import update_sign as us  # noqa: E402

fails = []


def check(cond, what):
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        fails.append(what)


tmp = tempfile.mkdtemp(prefix="rpa_pub_")
KEY = os.path.join(tmp, "key.txt")
SITE = os.path.join(tmp, "site")
pub_hex = pr.keygen(KEY)
check(len(pub_hex) == 64 and len(open(KEY).read().strip()) == 64 and pub_hex not in open(KEY).read(), "열쇠 만들기: 비밀은 파일에만, 돌려주는 건 공개 열쇠")
try:
    pr.keygen(KEY); check(False, "열쇠를 덮어씀")
except FileExistsError:
    check(True, "있는 열쇠는 덮어쓰지 않는다 (잃으면 모든 PC 를 다시 설치해야)")


def make_release(n, changed):
    d = os.path.join(tmp, f"배포_2026.10.0{n}-1")
    files = {"a.py": f"A{n if changed else 0}", "python/AFTER_MARKET_RPA_Agent.exe": "EXE"}
    for rel, text in files.items():
        full = os.path.join(d, *rel.split("/")); os.makedirs(os.path.dirname(full), exist_ok=True)
        open(full, "w", encoding="utf-8").write(text)
    man = {"format": 1, "version": f"2026.10.0{n}-1", "runtime": {"python": "3.14.7"},
           "files": {r: st.file_digest(os.path.join(d, *r.split("/"))) for r in files}}
    open(os.path.join(d, "manifest.json"), "w", encoding="utf-8").write(json.dumps(man))
    return d, man


deployed, lists = [], []
d1, m1 = make_release(1, True)
r = pr.publish("2026.10.01-1", d1, SITE, KEY, memo="첫 판", deploy=lambda: deployed.append(1), set_releases=lambda l: lists.append(l))
mb = open(os.path.join(SITE, "releases", "2026.10.01-1", "manifest.json"), "rb").read()
sig = bytes.fromhex(open(os.path.join(SITE, "releases", "2026.10.01-1", "manifest.sig")).read().strip())
check(us.verify(bytes.fromhex(pub_hex), mb, sig), "올린 manifest 의 서명이 공개 열쇠로 맞는다")
check(all(os.path.isfile(os.path.join(SITE, "blobs", f["sha256"])) for f in m1["files"].values()), "파일은 지문 이름으로")
check(deployed == [1] and lists[-1][0]["version"] == "2026.10.01-1" and lists[-1][0]["memo"] == "첫 판", f"배포·DB 목록 ({lists[-1]})")
for n in range(2, 8):
    d, _ = make_release(n, True)
    pr.publish(f"2026.10.0{n}-1", d, SITE, KEY, deploy=lambda: None, set_releases=lambda l: lists.append(l),
               stable="2026.10.02-1" if n == 7 else None)
kept = sorted(os.listdir(os.path.join(SITE, "releases")))
check(kept == ["2026.10.02-1", "2026.10.03-1", "2026.10.04-1", "2026.10.05-1", "2026.10.06-1", "2026.10.07-1"],
      f"최근 5개 + 안정본(10.02-1)만 남는다 ({kept})")
blob_names = set(os.listdir(os.path.join(SITE, "blobs")))
used = set()
for v in kept:
    used |= {f["sha256"] for f in json.load(open(os.path.join(SITE, "releases", v, "manifest.json")))["files"].values()}
check(blob_names == used, "아무 판도 안 쓰는 파일은 지운다, 같은 파일(EXE)은 하나")
check([x["version"] for x in lists[-1]] == kept, "DB 목록도 남은 판만")
try:
    pr.publish("2026.10.09-1", d1, SITE, KEY, deploy=lambda: None, set_releases=lambda l: None)
    check(False, "판 번호와 폴더 manifest 가 다른데 올림")
except ValueError as e:
    check("판" in str(e), f"판 번호가 다르면 멈춘다 ({e})")

shutil.rmtree(tmp, ignore_errors=True)
print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
```

`firebase/tests/check_setup.py` 끝 쪽(정리 앞)에 (그 파일의 `run(...)`·`check(...)` 방식 그대로 - `run` 은 `node setup.js …` 를 돌려 (코드, 출력)을 준다):

```python
print("판 목록 (자동 업데이트 4절)")
lst = os.path.join(tempfile.gettempdir(), "rpa_releases_test.json")
with open(lst, "w", encoding="utf-8") as f:
    json.dump([{"version": "2026.10.07-4", "published_at": "2026-10-07T12:00:00", "bytes": 10, "memo": "a"},
               {"version": "2026.10.07-5", "published_at": "2026-10-07T13:00:00", "bytes": 20, "memo": "b"}], f, ensure_ascii=False)
code, out = run("release-set", lst)
check(code == 0, f"release-set ({out.strip()[-200:]})")
code, out = run("stable", "2026.10.07-4")
code, out = run("releases")
r = json.loads(out.strip().splitlines()[-1])
check(r["newest"] == "2026.10.07-5" and r["stable"] == "2026.10.07-4" and [x["version"] for x in r["list"]] == ["2026.10.07-5", "2026.10.07-4"],
      f"최신본 자동·안정본 지정·최근 판이 위 ({r})")
code, out = run("stable", "2026.10.07-9")
check(code == 1 and "올라가 있지 않은 판" in out, "목록에 없는 판은 안정본으로 못 한다")
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe tests/test_publish_release.py`
Expected: `ModuleNotFoundError: No module named 'publish_release'`
Run: `powershell -File .superpowers/sdd/2026-10-07-auto-update/emu.ps1 -Cmd 'python check_setup.py' -Only auth,database,firestore`
Expected: release-set 실패 (모르는 명령)

- [ ] **Step 3: 구현**

`tools/build_release.py` 의 `PROGRAM_FILES` 끝에:

```python
    ("rpa_update.py", "rpa_update.py"),                                       # 자동 업데이트 (3부)
    ("update_helper.py", "update_helper.py"),
    ("update_sign.py", "update_sign.py"),
```

`tools/publish_release.py`:

```python
r"""판 내보내기 (자동 업데이트 설계 4절). 판을 빌드·샌드박스 시험한 뒤:

    .venv\Scripts\python.exe tools\publish_release.py --keygen                  (처음 한 번 - 비밀 열쇠 파일을 만들고 공개 열쇠를 알려 준다)
    .venv\Scripts\python.exe tools\publish_release.py 2026.10.07-5 "메모"        (서명·사이트 폴더·DB 목록·배포)
    .venv\Scripts\python.exe tools\publish_release.py 2026.10.07-5 --stable     (그 판을 안정본으로도)

배포(firebase deploy)는 사람이 확인한 뒤에 돈다 - 묻고 '예' 여야 한다. 비밀 열쇠는 firebase/admin/update_signing_key.txt 에만.
"""
import datetime
import json
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
import update_sign  # noqa: E402

KEY_PATH = os.path.join(REPO, "firebase", "admin", "update_signing_key.txt")
SITE_DIR = os.path.join(REPO, "firebase", "releases_site")
OUT_ROOT = r"D:\AX"
KEEP = 5


def keygen(key_path=KEY_PATH):
    if os.path.exists(key_path):
        raise FileExistsError(key_path)
    secret, public = update_sign.keygen()
    with open(key_path, "w", encoding="ascii") as f:
        f.write(secret.hex() + "\n")
    return public.hex()


def _secret(key_path):
    with open(key_path, encoding="ascii") as f:
        return bytes.fromhex(f.read().strip())


def publish(version, release_dir, site_dir, key_path, memo="", stable=None, deploy=None, set_releases=None):
    with open(os.path.join(release_dir, "manifest.json"), "rb") as f:
        man_bytes = f.read()
    man = json.loads(man_bytes.decode("utf-8"))
    if man.get("version") != version:
        raise ValueError(f"판 번호({version})와 배포 폴더의 판({man.get('version')})이 다릅니다")
    rel_dir = os.path.join(site_dir, "releases", version)
    os.makedirs(rel_dir, exist_ok=True)
    os.makedirs(os.path.join(site_dir, "blobs"), exist_ok=True)
    total = 0
    for rel, d in man["files"].items():
        dst = os.path.join(site_dir, "blobs", d["sha256"])
        if not os.path.isfile(dst):
            shutil.copy2(os.path.join(release_dir, *rel.split("/")), dst)
        total += int(d.get("size") or 0)
    with open(os.path.join(rel_dir, "manifest.json"), "wb") as f:
        f.write(man_bytes)                                       # 서명한 바이트 그대로
    with open(os.path.join(rel_dir, "manifest.sig"), "w", encoding="ascii") as f:
        f.write(update_sign.sign(_secret(key_path), man_bytes).hex() + "\n")
    info_path = os.path.join(site_dir, "published.json")         # 판마다 내보낸 시각·크기·메모 (사이트에도 올라가지만 비밀은 없다)
    info = json.load(open(info_path, encoding="utf-8")) if os.path.isfile(info_path) else {}
    info[version] = {"version": version, "published_at": datetime.datetime.now().isoformat(timespec="seconds"),
                     "bytes": total, "memo": memo}
    order = sorted(info, key=lambda v: (info[v]["published_at"], v))
    keep = set(order[-KEEP:]) | {x for x in (stable, _stable_of(site_dir)) if x}
    removed = [v for v in order if v not in keep]
    for v in removed:
        shutil.rmtree(os.path.join(site_dir, "releases", v), ignore_errors=True)
        info.pop(v, None)
    used = set()
    for v in info:
        with open(os.path.join(site_dir, "releases", v, "manifest.json"), encoding="utf-8") as f:
            used |= {d["sha256"] for d in json.load(f)["files"].values()}
    for name in os.listdir(os.path.join(site_dir, "blobs")):
        if name not in used:
            os.remove(os.path.join(site_dir, "blobs", name))
    with open(info_path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=1)
    if stable:
        with open(os.path.join(site_dir, "stable.txt"), "w", encoding="ascii") as f:
            f.write(stable + "\n")
    listing = [info[v] for v in sorted(info, key=lambda v: (info[v]["published_at"], v))]
    if set_releases:
        set_releases(listing)
    if deploy:
        deploy()
    return {"version": version, "kept": [x["version"] for x in listing], "removed": removed, "bytes": total}


def _stable_of(site_dir):
    p = os.path.join(site_dir, "stable.txt")
    return open(p, encoding="ascii").read().strip() if os.path.isfile(p) else None


def _node(*args):
    r = subprocess.run(["node", "setup.js", *args], cwd=os.path.join(REPO, "firebase", "admin"), capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(r.stdout + r.stderr)
    return r.stdout


def _set_releases(listing):
    path = os.path.join(SITE_DIR, "..", "releases_list.tmp.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(listing, f, ensure_ascii=False)
    try:
        _node("release-set", path)
    finally:
        os.remove(path)


def _deploy():
    if input("업데이트 전용 호스팅에 배포할까요? (예/아니오) ").strip() != "예":
        raise SystemExit("배포하지 않았습니다 (사이트 폴더와 DB 목록은 바뀌었습니다 - 다음에 다시 내보내면 같이 올라갑니다)")
    subprocess.run(["firebase", "deploy", "--only", "hosting", "--config", "releases.json"], cwd=os.path.join(REPO, "firebase"), check=True, shell=True)


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args == ["--keygen"]:
        print("공개 열쇠 (update_sign.PUBLIC_KEY_HEX 에 넣는다):", keygen())
        print(f"비밀 열쇠는 {KEY_PATH} 에만 있습니다 - USB 등에 사본을 직접 보관하세요")
        return 0
    if not args:
        print(__doc__)
        return 2
    version, rest = args[0], args[1:]
    stable = version if "--stable" in rest else None
    memo = " ".join(x for x in rest if x != "--stable")
    r = publish(version, os.path.join(OUT_ROOT, f"배포_{version}"), SITE_DIR, KEY_PATH, memo=memo, stable=stable,
                deploy=_deploy, set_releases=_set_releases)
    print(f"내보냄 {r['version']} ({r['bytes'] // (1 << 20)}MB) · 남은 판 {', '.join(r['kept'])}" + (f" · 지운 판 {', '.join(r['removed'])}" if r["removed"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`firebase/releases.json`:

```json
{
  "hosting": {
    "site": "rpa-test-f02e0-releases",
    "public": "releases_site",
    "ignore": ["**/.*", "published.json", "stable.txt"],
    "headers": [{ "source": "**", "headers": [{ "key": "Cache-Control", "value": "no-cache" }] }]
  }
}
```

`.gitignore` 의 Firebase 절과 `.graphifyignore` 끝에 `firebase/releases_site/` 와 `firebase/admin/update_signing_key.txt` 를 더한다.

`firebase/admin/ops.js` (setScheduleLimit 아래):

```js
// 판 목록 (자동 업데이트 4절) - meta/releases. 판 키는 점을 _ 로 (RTDB 키에 . 을 못 쓴다)
const relKey = (v) => String(v).replaceAll(".", "_");
const VERSION_RE = /^\d{4}\.\d{2}\.\d{2}-\d+$/;
export async function releasesOf() {
  const v = (await rtdb.ref("meta/releases").get()).val() ?? {};
  const list = Object.values(v.list ?? {}).sort((a, b) => (b.published_at ?? "").localeCompare(a.published_at ?? ""));
  return { list, stable: v.stable ?? null, newest: v.newest ?? null };
}
export async function setReleases(list) {
  if (!Array.isArray(list) || list.some((x) => !VERSION_RE.test(x?.version ?? ""))) throw new Refused("판 목록 모양이 다릅니다");
  const cur = await releasesOf();
  const newest = [...list].sort((a, b) => (b.published_at ?? "").localeCompare(a.published_at ?? ""))[0]?.version ?? null;
  const stable = list.some((x) => x.version === cur.stable) ? cur.stable : null;
  await rtdb.ref("meta/releases").set({ list: Object.fromEntries(list.map((x) => [relKey(x.version),
    { version: x.version, published_at: x.published_at ?? null, bytes: Number(x.bytes) || 0, memo: x.memo ?? "" }])), stable, newest });
  return { count: list.length, newest, stable };
}
export async function setStable(version) {
  const cur = await releasesOf();
  if (!cur.list.some((x) => x.version === version)) throw new Refused(`올라가 있지 않은 판입니다: ${version}`);
  await rtdb.ref("meta/releases/stable").set(version);
  return { stable: version };
}
```

`firebase/admin/setup.js` - 맨 위 사용법 주석에 세 줄, `ARGC` 에 `releases: [0], "release-set": [1], stable: [1]`, 분기:

```js
  } else if (cmdName === "releases") {
    console.log(JSON.stringify(await ops.releasesOf()));
  } else if (cmdName === "release-set") {
    const r = await ops.setReleases(JSON.parse(readFileSync(rest[0], "utf8")));
    console.log(`판 목록 ${r.count}개 · 최신본 ${r.newest ?? "-"} · 안정본 ${r.stable ?? "-"}`);
  } else if (cmdName === "stable") {
    console.log(`안정본: ${(await ops.setStable(rest[0])).stable}`);
```

(`readFileSync` import 가 setup.js 에 없으면 `import { readFileSync } from "node:fs";` 를 더한다.)

- [ ] **Step 4: 통과 확인**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe tests/test_publish_release.py` → `실패: 없음`
Run: `powershell -File .superpowers/sdd/2026-10-07-auto-update/emu.ps1 -Cmd 'python check_setup.py' -Only auth,database,firestore` → 모두 통과
Run: `bash .superpowers/sdd/2026-10-07-auto-update/pc_tests.sh test_encoding` (새 .py 파일 인코딩 점검) → 통과

- [ ] **Step 5: 커밋**

```bash
git add tools/build_release.py tools/publish_release.py firebase/releases.json firebase/admin/ops.js firebase/admin/setup.js .gitignore .graphifyignore tests/test_publish_release.py firebase/tests/check_setup.py
git commit -m "자동 업데이트 6: 판에 새 모듈 싣기, 내보내기 도구(서명·5개+안정본), setup.js 판 목록"
```

---

### Task 7: 관리 화면 - PC 줄 상태·[업데이트]·[되돌리기]·판 목록·[안정본으로 지정]

**Files:**
- Modify: `firebase/admin/ops.js` (`companyDetail`, `sendUpdate`, `sendRollback`)
- Modify: `firebase/admin/admin.js` (경로 넷)
- Modify: `firebase/admin/AFTERMARKET_SETUP.html` (`pcSection`, 판 목록 칸)
- Test: `firebase/tests/check_admin.py`

**Interfaces:**
- Consumes: Task 6 `ops.releasesOf/setStable`, agent 명령 모양 (Task 5: `by: "admin-tool"`, `args.version`).
- Produces:
  - `ops.companyDetail(cid).pcs[] = {pcId, label, version: <live version 객체|null>, update: <live update 객체|null>}`
  - `ops.sendUpdate(cid, pcId, version) -> {key}`, `ops.sendRollback(cid, pcId) -> {key}` - `apps/rpa/commands/{cid}/{pcId}` 에 `{type, args, by: "admin-tool", created_at, expires_at: now+COMMAND_TTL, state: "queued"}`
  - 경로: `GET /api/releases`, `POST /api/releases/stable {version}`, `POST /api/companies/:cid/pcs/:pcId/update {version}`, `POST /api/companies/:cid/pcs/:pcId/rollback`
  - 화면 글: PC 줄 `사무실 PC · pc_a · 판 2026.10.07-4 (안정본) · 업데이트됨 10/7 14:03`, 확인 창 `c_demo / pc_a 를 2026.10.07-5 로 바꿉니다. RPA 가 끝나면 바로 바뀝니다.`

- [ ] **Step 1: 실패하는 시험** - `firebase/tests/check_admin.py` 의 업체 상세 시험 뒤에 (그 파일의 `page`·`check`·`db_put`/`db_get` 방식 - 없으면 같은 뜻 도우미를 그 파일에서 찾아 쓴다):

```python
print("자동 업데이트 (설계 8절)")
db_put("meta/releases", {"list": {"2026_10_07-4": {"version": "2026.10.07-4", "published_at": "2026-10-07T12:00:00", "bytes": 1, "memo": "안정"},
                                  "2026_10_07-5": {"version": "2026.10.07-5", "published_at": "2026-10-07T13:00:00", "bytes": 1, "memo": "새"}},
                         "stable": "2026.10.07-4", "newest": "2026.10.07-5"})
db_put(f"apps/rpa/live/{CID}/{PC}", {"version": {"version": "2026.10.07-4", "state": "ok"},
                                      "update": {"state": "done", "target": "2026.10.07-4", "from": "2026.10.07-3", "at": "2026-10-07T14:03:00", "backup": "2026.10.07-3"}})
open_company(page, CID)
row = page.text_content(f"#pc-{PC}")
check("판 2026.10.07-4 (안정본)" in row and "업데이트됨 10/7 14:03" in row, f"PC 줄: 판·표시·상태 ({row})")
check(page.input_value(f"#pc-{PC} select.upd-ver") == "2026.10.07-4"
      and "(최신본)" in page.text_content(f"#pc-{PC} select.upd-ver option[value='2026.10.07-5']"), "판 고르기: 처음은 안정본, 최신본 표시")
page.select_option(f"#pc-{PC} select.upd-ver", "2026.10.07-5")
asked = []
page.once("dialog", lambda d: (asked.append(d.message), d.accept()))
page.click(f"#pc-{PC} button.upd-go")
page.wait_for_timeout(800)
cmd = [v for v in (db_get(f"apps/rpa/commands/{CID}/{PC}") or {}).values() if v.get("type") == "update"]
check(asked == [f"{CID} / {PC} 를 2026.10.07-5 로 바꿉니다. RPA 가 끝나면 바로 바뀝니다."], f"확인 창 ({asked})")
check(len(cmd) == 1 and cmd[0]["args"] == {"version": "2026.10.07-5"} and cmd[0]["by"] == "admin-tool" and cmd[0]["state"] == "queued",
      f"update 명령 ({cmd})")
check(page.is_visible(f"#pc-{PC} button.upd-back") and "2026.10.07-3" in page.text_content(f"#pc-{PC} button.upd-back"), "보관본이 있으면 되돌리기 단추")
db_put(f"apps/rpa/live/{CID}/{PC}/update", {"state": "waiting", "target": "2026.10.07-5", "from": "2026.10.07-4", "at": "2026-10-07T15:00:00", "backup": "2026.10.07-3"})
open_company(page, CID)
check(page.is_disabled(f"#pc-{PC} button.upd-go") and page.is_disabled(f"#pc-{PC} button.upd-back")
      and "업데이트 대기 중" in page.text_content(f"#pc-{PC}"), "진행 중이면 두 단추 잠금")
page.click("#releases-open")
page.once("dialog", lambda d: d.accept())
page.click("#releases button[data-stable='2026.10.07-5']")
page.wait_for_timeout(800)
check(db_get("meta/releases/stable") == "2026.10.07-5", "판 목록에서 안정본으로 지정")
check("관리_기록" and "안정본" in open(LOG_PATH, encoding="utf-8").read(), "관리 기록에 남는다")
```

(`CID`·`PC`·`open_company`·`LOG_PATH` 는 check_admin.py 에 이미 있는 이름이거나, 그 파일의 업체 상세 시험이 쓰는 방식대로 만든다 - 이름을 맞춘 것은 `Ruling:` 으로 남긴다.)

- [ ] **Step 2: 실패 확인**

Run: `powershell -File .superpowers/sdd/2026-10-07-auto-update/emu.ps1 -Cmd 'python check_admin.py' -Only auth,database,firestore`
Expected: `#pc-…` 을 못 찾아 실패

- [ ] **Step 3: 구현** - `ops.js`:

```js
const COMMAND_TTL_SEC = 600;     // 웹 화면(firebase-config.js)과 같은 값 - PC 가 받자마자 '예약했습니다' 로 끝낸다
async function sendAdminCommand(cid, pcId, type, args) {
  checkKey("cid", cid); checkKey("pcId", pcId);
  const v = await companyOf(cid);
  if (!v.pcs?.[pcId]) throw new Refused(`없는 PC 입니다: ${pcId}`);
  const now = Math.floor(Date.now() / 1000);
  const ref = rtdb.ref(`apps/rpa/commands/${cid}/${pcId}`).push();
  await ref.set({ type, args: args ?? null, by: "admin-tool", created_at: now, expires_at: now + COMMAND_TTL_SEC, state: "queued" });
  return { key: ref.key };
}
export async function sendUpdate(cid, pcId, version) {
  if (!(await releasesOf()).list.some((x) => x.version === version)) throw new Refused(`올라가 있지 않은 판입니다: ${version}`);
  return sendAdminCommand(cid, pcId, "update", { version });
}
export const sendRollback = (cid, pcId) => sendAdminCommand(cid, pcId, "rollback", null);
```

(`COMMAND_TTL_SEC` 는 `firebase/web/firebase-config.js` 의 값과 같게 - 다르면 그 값으로.)

`companyDetail` 의 `pcs:` 를:

```js
    pcs: await Promise.all(Object.entries(v.pcs ?? {}).map(async ([pcId, p]) => {
      const live = (await rtdb.ref(`apps/rpa/live/${cid}/${pcId}`).get()).val() ?? {};
      return { pcId, label: p.label ?? "", version: live.version ?? null, update: live.update ?? null };
    })),
```

`admin.js` 경로 표에:

```js
  ["GET", "/api/releases", () => ops.releasesOf()],
  ["POST", "/api/releases/stable", (b) => ops.setStable(b.version), (b) => `안정본 지정 ${b.version}`],
  ["POST", "/api/companies/:cid/pcs/:pcId/update", (b, p) => ops.sendUpdate(p.cid, p.pcId, b.version), (b, r, p) => `업데이트 ${p.cid}/${p.pcId} → ${b.version}`],
  ["POST", "/api/companies/:cid/pcs/:pcId/rollback", (b, p) => ops.sendRollback(p.cid, p.pcId), (b, r, p) => `이전 판으로 되돌리기 ${p.cid}/${p.pcId}`],
```

(경로 맞추기 함수가 `:pcId` 처럼 둘째 이름 자리를 못 받으면 그 함수에 더한다.)

`AFTERMARKET_SETUP.html` - `pcSection(d)` 의 목록을 PC 줄로:

```js
const UPD_TEXT = { downloading: "업데이트 받는 중", waiting: "업데이트 대기 중", ready: "바꾸는 중", applying: "바꾸는 중", rolling_back: "바꾸는 중",
  failed: "업데이트 실패", rolled_back: "업데이트 실패 - 옛 판으로 되돌림" };
const md = (iso) => (iso ? `${Number(iso.slice(5, 7))}/${Number(iso.slice(8, 10))} ${iso.slice(11, 16)}` : "");
function updText(u) {
  if (!u?.state) return "";
  return u.state === "done" ? `업데이트됨 ${md(u.at)}` : UPD_TEXT[u.state] ?? u.state;
}
function pcRowEl(d, p, rel) {
  const tag = (v) => (v === rel.stable ? " (안정본)" : v === rel.newest ? " (최신본)" : "");
  const ver = p.version?.version ? `판 ${p.version.version}${tag(p.version.version)}` : "판 모름";
  const busy = ["downloading", "waiting", "ready", "applying", "rolling_back"].includes(p.update?.state);
  const sel = el("select", { class: "upd-ver" }, rel.list.map((x) => el("option", { value: x.version }, `${x.version}${tag(x.version)}${x.memo ? ` - ${x.memo}` : ""}`)));
  if (rel.stable) sel.value = rel.stable;
  const go = el("button", { class: "upd-go", disabled: busy || !rel.list.length, onclick: () => act(go, async () => {
    if (!confirm(`${d.cid} / ${p.pcId} 를 ${sel.value} 로 바꿉니다. RPA 가 끝나면 바로 바뀝니다.`)) return;
    await api("POST", `/api/companies/${d.cid}/pcs/${p.pcId}/update`, { version: sel.value });
    flash(`업데이트 명령을 보냈습니다 (${p.pcId} → ${sel.value})`); openDetail(d.cid);
  }) }, "업데이트");
  const back = p.update?.backup ? el("button", { class: "upd-back", disabled: busy, onclick: () => act(back, async () => {
    if (!confirm(`${d.cid} / ${p.pcId} 를 이전 판 ${p.update.backup} 로 되돌립니다. RPA 가 끝나면 바로 바뀝니다.`)) return;
    await api("POST", `/api/companies/${d.cid}/pcs/${p.pcId}/rollback`, {});
    flash(`되돌리기 명령을 보냈습니다 (${p.pcId} → ${p.update.backup})`); openDetail(d.cid);
  }) }, `이전 판으로 되돌리기 (${p.update.backup})`) : null;
  const status = updText(p.update);
  return el("li", { id: `pc-${p.pcId}`, title: p.update?.reason ?? "" },
    `${p.label || "(이름 없음)"} · ${p.pcId} · ${ver}${status ? ` · ${status}` : ""} `, sel, go, back ?? "");
}
```

`pcSection` 에서 `d.pcs.map((p) => el("li", {}, …))` 를 `d.pcs.map((p) => pcRowEl(d, p, d.releases))` 로, `openDetail` 이 상세를 받을 때 `d.releases = await api("GET", "/api/releases")` 를 같이 받는다.

판 목록 칸 (업체 표 위, 기존 첫 화면 구조에 맞춰): 단추 `#releases-open` 을 누르면 `#releases` 표가 펼쳐진다 - 줄마다 `판 · 내보낸 때 · 크기 MB · 메모 · 표시(안정본/최신본) · [안정본으로 지정]`(`data-stable="<판>"`, 이미 안정본이면 없음). 누르면 `confirm(`${v} 를 안정본으로 지정합니다.`)` → `POST /api/releases/stable` → 표 다시 그림.

- [ ] **Step 4: 통과 확인**

Run: `powershell -File .superpowers/sdd/2026-10-07-auto-update/emu.ps1 -Cmd 'python check_admin.py' -Only auth,database,firestore`
Expected: 모두 통과

- [ ] **Step 5: 커밋**

```bash
git add firebase/admin/ops.js firebase/admin/admin.js firebase/admin/AFTERMARKET_SETUP.html firebase/tests/check_admin.py
git commit -m "자동 업데이트 7: 관리 화면 - PC 줄 판·상태, [업데이트]·[이전 판으로 되돌리기], 판 목록·안정본 지정"
```

---

### Task 8: 업체 웹 - 판 옆 상태·실행 단추 잠금 · 규칙 시험

**Files:**
- Modify: `firebase/web/rpa.js` (`verStat`/`paintVer`, `paintButtons`)
- Test: `firebase/tests/check_web.py` (버전 절), `firebase/tests/rules.test.js`

**Interfaces:**
- Consumes: `live.update` (Task 5).
- Produces: `rpa.js updStat(u) -> {text, title} | null`, 실행 단추 `title`/잠금 글 `업데이트 중이라 잠시 실행할 수 없습니다`.

- [ ] **Step 1: 실패하는 시험** - `check_web.py` 의 버전 절(`확인 실패면 노란 글씨` 근처) 뒤에:

```python
db_patch(LIVE, {"update": {"state": "waiting", "target": "2026.10.07-5", "from": "2026.10.07-4", "at": "2026-10-07T15:00:00", "backup": None}})
page.wait_for_function("(document.getElementById('ver')?.textContent || '').includes('업데이트 대기 중')", timeout=10000)
check(page.is_disabled("#run-routine") and page.is_disabled("#run-all")
      and page.get_attribute("#run-routine", "title") == "업데이트 중이라 잠시 실행할 수 없습니다", "업데이트 대기 중: 판 옆 글 + 실행 단추 잠금")
db_patch(LIVE, {"update": {"state": "rolled_back", "target": "2026.10.07-5", "from": "2026.10.07-4", "at": "2026-10-07T15:10:00",
                           "reason": "새 판이 3분 안에 정상으로 켜지지 않았습니다", "backup": "2026.10.07-3"}})
page.wait_for_function("(document.getElementById('ver')?.textContent || '').includes('옛 판으로 되돌림')", timeout=10000)
check("3분" in (page.get_attribute("#ver", "title") or "") and not page.is_disabled("#run-routine"), "되돌림: 까닭은 마우스 글, 실행 단추는 풀린다")
db_patch(LIVE, {"update": {"state": "done", "target": "2026.10.07-5", "from": "2026.10.07-4", "at": "2026-10-07T14:03:00", "backup": "2026.10.07-4"}})
page.wait_for_function("(document.getElementById('ver')?.textContent || '').includes('업데이트됨 (10/7 14:03)')", timeout=10000)
check(True, "업데이트됨 (10/7 14:03)")
db_patch(LIVE, {"update": None})
```

(`LIVE`·`db_patch` 는 check_web.py 에 이미 있다. 그 절의 판 값이 `ok` 상태여야 `버전 …` 글이 보인다.)

`rules.test.js` 의 명령 type 시험 옆에 (그 파일의 `assertFails`/`assertSucceeds`·업체 관리자·총괄 컨텍스트 이름 그대로):

```js
  it("update·rollback 명령은 업체 관리자도 총괄도 못 넣는다 (관리 화면 Admin SDK 만 - 자동 업데이트 10절)", async () => {
    for (const ctx of [adminCtx, superCtx]) {
      for (const type of ["update", "rollback"]) {
        await assertFails(set(ref(ctx.database(), `apps/rpa/commands/c_demo/pc_a/x_${type}`),
          { type, args: null, by: ctx.uid, created_at: 1, expires_at: 9999999999, state: "queued" }));
      }
    }
  });
  it("meta/releases 는 업체 계정이 못 읽는다", async () => {
    await assertFails(get(ref(adminCtx.database(), "meta/releases")));
  });
```

- [ ] **Step 2: 실패 확인**

Run: `powershell -File .superpowers/sdd/2026-10-07-auto-update/emu.ps1 -Cmd 'python check_web.py' -Only auth,database,firestore,hosting`
Expected: `업데이트 대기 중` 을 기다리다 실패. (규칙 시험은 규칙을 안 바꾸므로 처음부터 통과해야 한다 - 통과하면 "규칙이 이미 막는다" 는 확인이다. 실패하면 규칙에 구멍이 있는 것이니 멈추고 알린다.)

- [ ] **Step 3: 구현** - `rpa.js` (`verStat` 아래):

```js
// live.update → 판 글 옆 업데이트 상태 (자동 업데이트 9절). 까닭은 마우스 글
const UPD_TEXT = { downloading: "업데이트 받는 중", waiting: "업데이트 대기 중", ready: "바꾸는 중", applying: "바꾸는 중", rolling_back: "바꾸는 중",
  failed: "업데이트 실패", rolled_back: "업데이트 실패 - 옛 판으로 되돌림" };
const UPD_BUSY = ["waiting", "ready", "applying", "rolling_back"];   // 에이전트도 이 동안 실행을 거절한다 (rpa_update.BUSY_STATES)
function updStat(u) {
  if (!u || typeof u !== "object" || typeof u.state !== "string") return null;
  if (u.state === "done") {
    const at = typeof u.at === "string" ? u.at : "";
    return { text: at ? `업데이트됨 (${Number(at.slice(5, 7))}/${Number(at.slice(8, 10))} ${at.slice(11, 16)})` : "업데이트됨", title: "" };
  }
  return UPD_TEXT[u.state] ? { text: UPD_TEXT[u.state], title: typeof u.reason === "string" ? u.reason : "" } : null;
}
const updBusy = () => UPD_BUSY.includes(live?.update?.state);
```

`paintVer` 를:

```js
function paintVer() {
  const v = verStat(live?.version), u = updStat(live?.update), el = $("ver");
  el.textContent = [v?.text, u?.text].filter(Boolean).join(" · ");
  el.title = [v?.title, u?.title].filter(Boolean).join(" / ");
  el.classList.toggle("warn", !!v?.warn || ["failed", "rolled_back"].includes(live?.update?.state));
}
```

`paintButtons` 의 반복을:

```js
  const upd = updBusy();
  for (const id of ["run-prepare", "run-routine", "run-all"]) {
    $(id).disabled = off || running || empty || upd;
    $(id).title = upd && !off ? "업데이트 중이라 잠시 실행할 수 없습니다" : running && !off ? "RPA 가 돌고 있어 실행할 수 없습니다" : "";
  }
```

`paintVer` 가 live 가 바뀔 때마다 불리는지 확인하고, 아니면 `paintButtons` 를 부르는 곳에서 같이 부른다.

- [ ] **Step 4: 통과 확인**

Run: `powershell -File .superpowers/sdd/2026-10-07-auto-update/emu.ps1 -Cmd 'python check_web.py' -Only auth,database,firestore,hosting` → 모두 통과
Run: `powershell -File .superpowers/sdd/2026-10-07-auto-update/emu.ps1 -Cmd 'npm test --prefix ..' -Only database` (rules.test.js 를 돌리는 그 저장소의 명령 - 2026-10-07-settings-schedule 장부의 규칙 시험 명령을 그대로) → 모두 통과

- [ ] **Step 5: 커밋**

```bash
git add firebase/web/rpa.js firebase/tests/check_web.py firebase/tests/rules.test.js
git commit -m "자동 업데이트 8: 업체 웹 판 옆 업데이트 상태·실행 단추 잠금, 규칙 시험(업체는 update 못 넣음)"
```

---

### Task 9: 샌드박스 시험 · 문서

**Files:**
- Modify: `tools/sandbox_test.py` (판 B·C 를 만들어 서명해 넘긴다), `tools/sandbox_inner.ps1` (업데이트 절)
- Modify: `docs/firebase-architecture.md` (시험 표·자동 업데이트 줄), `docs/superpowers/specs/2026-10-07-auto-update-design.md` (상태 줄)

**Interfaces:**
- Consumes: 빌드한 판 폴더 `D:\AX\배포_<판>` (manifest), `publish_release.publish`, `update_sign`, 비밀 열쇠 (Task 10 의 열쇠 - 없으면 시험용 열쇠를 임시로 만들고 `PUBLIC_KEY_HEX` 와 맞지 않으니 이 시험은 Task 10 의 열쇠 만들기 뒤에 돈다).
- Produces: 샌드박스 결과의 새 `통과` 줄들.

- [ ] **Step 1: `sandbox_test.py`** - 인자 `--update` 가 있으면 설치 파일과 같은 판의 배포 폴더(`D:\AX\배포_<판>`)를 바탕으로 작업 폴더에 `site\` 를 만든다:
  - 판 B = 판 A 와 같고 `rpa_dashboard.py` 끝에 `# update test B` 한 줄 (판 번호 `<판>-b`).
  - 판 C = 판 A 와 같고 `firebase/agent/agent.py` 를 `import sys; sys.exit(1)` 한 줄로 (판 번호 `<판>-c`) - 서명은 맞지만 켜지지 않는 판.
  - 둘 다 `publish_release.publish(..., deploy=None, set_releases=None)` 로 `site\` 에 서명해 넣는다 (진짜 비밀 열쇠).
  - `VERSION_RE` 가 `-b`/`-c` 를 받지 않으므로 판 번호는 `<날짜>-9001`·`<날짜>-9002` 로 한다.

- [ ] **Step 2: `sandbox_inner.ps1`** - 설치·에이전트 절 뒤, 제거 절 앞에 (UTF-8 BOM 유지, `Check` 함수 그대로):

```powershell
# 7. 자동 업데이트 (설계 12절): 샌드박스 안 가짜 호스팅 + 로그인 없는 3분 점검 (표시 파일 updatehealth_local)
if (Test-Path "$T\site") {
  New-Item -ItemType Directory -Force "$PD\update" | Out-Null
  Set-Content "$PD\update\health_local" ""                                                   # 가짜 계정 - 로그인 없이 판 점검만
  $web = Start-Process "$App\python\python.exe" -ArgumentList "-m http.server 8799 --directory `"$T\site`"" -PassThru -WindowStyle Hidden
  $B = (Get-Content "$T\site\versions.txt")[0]; $C = (Get-Content "$T\site\versions.txt")[1]; $A = (Get-Content "$App\manifest.json" -Raw | ConvertFrom-Json).version
  $py = "$App\python\python.exe"
  # 가짜 계정이라 명령이 안 온다 - 에이전트의 업데이트 스레드가 하는 일(run_update)을 직접 부른다 (받기 주소만 샌드박스 안)
  function Upd($mode, $ver) {
    & $py -c "import sys; sys.path[:0]=[r'$App', r'$App\firebase\agent']; import rpa_update as u, rpa_settings as rs; u.run_update('$ver' or u.backup_version(), '$mode', r'$App', lambda: True, rs.register_helper_task, rs.run_helper_task, fetch=lambda v, p, s: u.fetch_release(v, p, s, base_url='http://127.0.0.1:8799')); print(u.read_state())" 2>&1
  }
  function WaitState($want, $sec = 400) {
    for ($i = 0; $i -lt $sec; $i += 5) { $s = (Get-Content "$PD\update\state.json" -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json).state; if ($want -contains $s) { return $s }; Start-Sleep 5 }
    return $s
  }
  Upd "update" $B | Out-File "$O\upd_b.txt"
  $s = WaitState @("done", "rolled_back", "failed")
  Check "판 B 로 업데이트 → done" ($s -eq "done") "$s $(Get-Content "$PD\update\state.json" -Raw)"
  Check "판 점검 ok · 판 B" ((Get-Content "$App\manifest.json" -Raw | ConvertFrom-Json).version -eq $B)
  Check "제거 목록의 판 번호도 B" ((Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{C3F7A2B4-5E81-4D2A-9B6C-7A1E0F3D8B52}_is1").DisplayVersion -eq $B)
  schtasks /Query /TN "\AFTER MARKET\RPA Update" *> $null
  Check "도우미 작업은 끝나면 지운다" ($LASTEXITCODE -ne 0)
  Upd "rollback" "" | Out-File "$O\upd_back.txt"
  $s = WaitState @("done", "rolled_back", "failed")
  Check "[이전 판으로 되돌리기] → 판 A" (($s -eq "done") -and ((Get-Content "$App\manifest.json" -Raw | ConvertFrom-Json).version -eq $A)) "$s"
  Upd "update" $C | Out-File "$O\upd_c.txt"
  $s = WaitState @("rolled_back", "done", "failed")
  Check "켜지지 않는 판 C → 3분 점검 실패 → 되돌림 (판 A)" (($s -eq "rolled_back") -and ((Get-Content "$App\manifest.json" -Raw | ConvertFrom-Json).version -eq $A)) "$s"
  # 바꾸는 도중 끊김: 도우미가 applying 을 적자마자 죽이고, 도우미 작업을 다시 돌린다 (로그온 흉내)
  Upd "update" $B | Out-File "$O\upd_kill.txt"
  WaitState @("applying") 400 | Out-Null
  Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*update_helper.py*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
  Check "끊긴 뒤 applying 이 남았다" ((WaitState @("applying") 5) -eq "applying")
  schtasks /Run /TN "\AFTER MARKET\RPA Update" | Out-Null
  $s = WaitState @("rolled_back", "done")
  Check "다음 로그온(도우미 다시)에 되돌림 → 판 A (Review Focus 2)" (($s -eq "rolled_back") -and ((Get-Content "$App\manifest.json" -Raw | ConvertFrom-Json).version -eq $A)) "$s"
  Stop-Process -Id $web.Id -Force -ErrorAction SilentlyContinue
}
```

`sandbox_test.py` 는 `site\versions.txt` 에 B·C 판 번호를 한 줄씩 쓴다. 샌드박스의 기존 30분 대기는 45분으로 늘린다 (3분 점검이 세 번).

- [ ] **Step 3: 문서** - `docs/firebase-architecture.md` 시험 표에 새 시험 파일 넷과 샌드박스 줄(자동 업데이트), 구조 절에 "자동 업데이트: 관리 화면 → 명령 update/rollback → 에이전트 받기·대기 → 도우미(update\\runner) → 3분 점검·되돌리기, 업데이트 전용 호스팅 rpa-test-f02e0-releases (firebase/releases.json)". 설계서 상태 줄에 "2026-10-0X 구현 (계획 docs/superpowers/plans/2026-10-07-auto-update.md)".

- [ ] **Step 4: 빌드·샌드박스** (Task 10 의 열쇠 만들기와 공개 열쇠 넣기가 끝난 뒤)

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe tools/build_release.py > <작업폴더>/build.log 2>&1` 다음 `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe tools/sandbox_test.py --update D:\AX\AFTER_MARKET_RPA_Setup_<판>.exe > <작업폴더>/sandbox.log 2>&1` (배경으로, 끝나면 `실패: 0` 확인)
Expected: 기존 38 + 업데이트 9 줄 모두 `통과`, `실패: 0`

- [ ] **Step 5: 커밋**

```bash
git add tools/sandbox_test.py tools/sandbox_inner.ps1 docs/firebase-architecture.md docs/superpowers/specs/2026-10-07-auto-update-design.md
git commit -m "자동 업데이트 9: 샌드박스 - 판 B 업데이트·되돌리기·켜지지 않는 판 C·도중 끊김, 문서"
```

---

### Task 10: 운영 준비 (사용자 확인이 필요한 단계 - 하나씩 묻고)

**Files:**
- Modify: `update_sign.py` (`PUBLIC_KEY_HEX`)

- [ ] **Step 1: 열쇠 만들기** - 사용자에게 알리고 `.venv/Scripts/python.exe tools/publish_release.py --keygen`. 출력의 공개 열쇠만 `update_sign.PUBLIC_KEY_HEX` 에 넣는다. 비밀 열쇠 파일 내용은 읽지도 찍지도 않는다. 사용자에게 "firebase/admin/update_signing_key.txt 를 USB 등에 직접 복사해 두세요" 를 알린다. `PUBLIC_KEY_HEX` 를 넣은 뒤 `tests/test_update_sign.py` 를 다시 돌린다.

```bash
git add update_sign.py
git commit -m "자동 업데이트 10: 공개 열쇠"
```

- [ ] **Step 2: Task 9 Step 4 (빌드·샌드박스)** - 이 열쇠로.

- [ ] **Step 3: 업데이트 전용 호스팅 사이트 만들기** (사용자 확인 뒤): `firebase hosting:sites:create rpa-test-f02e0-releases --project rpa-test-f02e0` (이름이 이미 쓰이면 사용자와 다른 이름을 정해 `firebase/releases.json`·`rpa_update.UPDATE_BASE_URL` 을 같이 고치고 다시 빌드).

- [ ] **Step 4: 웹·DB 배포** (사용자 확인 뒤): `firebase deploy --only hosting --config firebase.json` (업체 웹 상태 글). 규칙은 안 바뀌었다.

- [ ] **Step 5: 첫 내보내기** (사용자 확인 뒤): `tools/publish_release.py <판> "첫 자동 업데이트 판" --stable` - 묻는 말에 사용자 확인을 받고 `예`.

- [ ] **Step 6: 실제 첫 업데이트는 사용자가** - 시험 업체 PC 에 이 판을 설치 파일로 깐 뒤, 다음 판을 내보내고 관리 화면에서 [업데이트]. 개발 PC 에는 깔지 않는다.

---

## 자체 점검 (계획 쓴 뒤)

- **설계서 덮기:** 2절 결정 - 관리 화면 [업데이트](T7)·호스팅 업데이트 전용 사이트(T6·T10)·끝나면 바로(T4·T5)·되돌리기(T3)·직전 판 보관과 [되돌리기](T3·T5·T7)·옵저버 안내 뺌(없음)·A 방식(T2·T3)·5개+안정본/최신본(T6·T7). 4절 내보내기(T6), 5절 서명(T1·T2·T10), 6절 에이전트(T5), 7절 도우미(T3·T4), 8절 관리 화면(T7), 9절 업체 웹(T8), 10절 규칙(T5 decide·T8), 11절 오류 표(T2·T3), 12절 시험(T1~T9).
- **설계서와 다르게 한 것 (실행 때 장부에 `Ruling:` 으로):**
  - 업데이트 전용 사이트를 `firebase.json` 대상 둘이 아니라 **별도 설정 `firebase/releases.json`** 으로 배포 - 기존 `--only hosting`·에뮬레이터 시험(5000번)을 안 바꾼다.
  - **파이썬(`runtime`)이 바뀐 판은 자동 업데이트를 거절**("설치 파일로") - 파이썬 실행 환경은 판 목록 밖이라 지문으로 비교할 수 없다.
  - 3분 점검의 "첫 로그인" 은 **첫 heartbeat 성공**으로 본다 (로그인과 쓰기가 다 된 것). 샌드박스는 표시 파일 `update\health_local` 로 로그인 없이 판 점검만 (가짜 계정이라 로그인이 거부된다).
  - 샌드박스는 명령을 받을 수 없어(가짜 계정) 에이전트 스레드가 하는 `run_update` 를 직접 부른다 - 명령 검사(`do_update`)는 test_agent 가 맡는다.
  - 판 목록(DB)은 내보내기 도구가 `setup.js release-set` 으로 쓴다 - 사이트 폴더의 `published.json` 이 원본.
