# -*- coding: utf-8 -*-
"""사내 서버 PC 등록부 (계획 2026-11-24-lan-1-server-multi-pc Task 2, 설계 6.4).

- pcs.json = {"v": 1, "next": N, "pcs": {<pc_01>: {label, guid, host, agent_key, relay_key, state, created_at, enrolled_at, removed_at?}}}.
  agent_key·relay_key 는 저장한 이 값이 곧 열쇠다 - 그래서 파일은 관리자·SYSTEM 만 (local_server.LOCKED_FILES).
- 등록 토큰은 디스크에 쓰지 않는다. 대기 중인 등록(번호·이름·토큰·만료·틀린 횟수)은 메모리에만 10분.
  틀린 증명은 세기만 하고 대기를 취소하지 않는다 (검토 I-3).
- PC 번호는 next 로 매기고 하나씩 올린다. 대기만 했던 번호·지운 번호도 다시 쓰지 않는다.
- 열쇠는 토큰과 PC 가 만든 난수로 양쪽이 따로 만든다 (휴대폰 짝짓기와 같은 방식) - 등록 글만 주운 사람은 열쇠를 만들지 못한다.
표준 라이브러리만. 기록(local_server.log)에 토큰·열쇠·증명을 싣지 않는다.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
import threading
import time

PC_RE = re.compile(r"pc_\d{2,4}")
PC_MAX = 9999                    # 번호 상한 - PC_RE 가 받는 가장 큰 번호 (검토 M-9)
ENROLL_SEC = 600                 # 등록 토큰 유효 시간
REMOVED_KEEP_MS = 3 * 24 * 3600 * 1000   # 지운 PC 의 열쇠를 두는 시간 - 그동안만 '지워짐' 답에 서명한다. 지나면 열쇠만 지우고 번호·이름 기록은 남긴다 (사용자 2026-11-24 "3일 뒤에 지우자")
LABEL_MAX = 40
PREFIX = "APE1."                 # 등록 글(한 줄) 머리
PCS_NAME = "pcs.json"

RAND_RE = re.compile(r"[0-9a-f]{64}")
GUID_RE = re.compile(r"[0-9A-Fa-f-]{36}")
HOST_MAX = 63
ENROLL_KEYS = ("v", "url", "pc", "token", "exp")
STATES = ("active", "disabled", "removed")


class SeatsFull(Exception):
    """등록할 수 있는 PC 수를 모두 썼다 (active + disabled + 살아 있는 대기)."""


class NumbersFull(ValueError):
    """PC 번호를 pc_9999 까지 모두 썼다 (번호는 다시 쓰지 않는다). 웹은 409."""


class EnrollError(Exception):
    """등록 거절. code ∈ unknown(대기 중 아님) | expired(10분 지남) | bad_proof(증명·꼴 틀림) | duplicate(같은 윈도우 PC) | seats(자리 없음)."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


# ----------------------------------------------------------------------------------------------------
# 증명 · 열쇠 (클라이언트 local_store 와 같은 함수 - 바꾸면 양쪽 시험을 같이 고친다)
# ----------------------------------------------------------------------------------------------------

def _hmac_hex(token, text):
    return hmac.new(token.encode("utf-8"), text.encode("utf-8"), hashlib.sha256).hexdigest()


def enroll_proof(token, pc_id, rand_hex, guid, host):
    """등록 요청 증명 = HMAC-SHA256(열쇠 토큰, "ap2 enroll\\n{pc_id}\\n{rand_hex}\\n{guid}\\n{host}") 소문자 hex."""
    return _hmac_hex(token, f"ap2 enroll\n{pc_id}\n{rand_hex}\n{guid}\n{host}")


def derive_keys(token, rand_hex):
    """(에이전트 열쇠, 중계 열쇠) = HMAC-SHA256(토큰, "ap2 pc agent\\n"+난수), HMAC-SHA256(토큰, "ap2 pc relay\\n"+난수) hex."""
    return _hmac_hex(token, "ap2 pc agent\n" + rand_hex), _hmac_hex(token, "ap2 pc relay\n" + rand_hex)


# ----------------------------------------------------------------------------------------------------
# 등록 글 한 줄 (APE1.<base64url JSON>)
# ----------------------------------------------------------------------------------------------------

PEM_HEAD = "-----BEGIN CERTIFICATE-----"
CA_MAX = 16 * 1024               # 등록 글의 인증 기관 글 상한 (우리 것은 1KB 안팎)


def _check_ca(info):
    """선택 칸 ca (사내 서버 ② Task 4 - 에이전트가 믿을 우리 인증 기관 PEM 글). url 이 https 면 꼭 있어야 한다.
    있으면 인증서 PEM 글이어야 한다. 틀리면 ValueError."""
    https = isinstance(info.get("url"), str) and info["url"].lower().startswith("https://")
    if "ca" not in info:
        if https:
            raise ValueError("등록 글에 서버 인증 기관이 없습니다.")
        return
    ca = info["ca"]
    if not (isinstance(ca, str) and PEM_HEAD in ca and len(ca) <= CA_MAX):
        raise ValueError("등록 글의 서버 인증 기관 형식이 올바르지 않습니다.")


def encode_enrollment(info):
    """등록 정보 → 붙여 넣을 수 있는 한 줄 = PREFIX + base64url(JSON, 채움 없음).
    url 이 https 면 ca(인증 기관 PEM 글)가 꼭 있어야 한다 (ValueError)."""
    _check_ca(info)
    raw = json.dumps(info, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return PREFIX + base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_enrollment(text):
    """한 줄 → 등록 정보 dict (앞뒤 빈칸 무시). 꼴이 틀리거나 v(=1)·url·pc·token·exp 가 하나라도 없으면 ValueError.
    선택 칸 ca: url 이 https 면 꼭 있어야 하고, 있으면 인증서 PEM 글 (_check_ca)."""
    if not isinstance(text, str):
        raise ValueError("등록 글이 아닙니다.")
    text = text.strip()
    if not text.startswith(PREFIX):
        raise ValueError("등록 글의 형식이 올바르지 않습니다.")
    body = text[len(PREFIX):]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", body):
        raise ValueError("등록 글의 형식이 올바르지 않습니다.")
    try:
        info = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode("utf-8"))
    except ValueError as e:                     # binascii.Error·UnicodeDecodeError·JSONDecodeError 모두 ValueError
        raise ValueError("등록 글의 형식이 올바르지 않습니다.") from e
    if not isinstance(info, dict) or any(k not in info for k in ENROLL_KEYS):
        raise ValueError("등록 글에 빠진 내용이 있습니다.")
    if info["v"] != 1 or isinstance(info["v"], bool):
        raise ValueError("지원하지 않는 등록 글 버전입니다.")
    if not all(isinstance(info[k], str) and info[k] for k in ("url", "pc", "token")):
        raise ValueError("등록 글의 형식이 올바르지 않습니다.")
    if not isinstance(info["exp"], (int, float)) or isinstance(info["exp"], bool):
        raise ValueError("등록 글의 형식이 올바르지 않습니다.")
    _check_ca(info)
    return info


def clean_label(value):
    """PC 이름 (앞뒤 빈칸 없이 1~LABEL_MAX 자, 줄바꿈 등 제어 글자 없이). 아니면 ValueError."""
    if not isinstance(value, str):
        raise ValueError("PC 이름의 형식이 올바르지 않습니다.")
    text = value.strip()
    if not text:
        raise ValueError("PC 이름을 입력하여 주십시오.")
    if len(text) > LABEL_MAX:
        raise ValueError(f"PC 이름은 {LABEL_MAX}자까지 입력할 수 있습니다.")
    if any(ord(c) < 32 or ord(c) == 127 for c in text):
        raise ValueError("PC 이름에 쓸 수 없는 글자가 있습니다.")
    return text


def _pc_num(pc_id):
    return int(pc_id[3:])


# ----------------------------------------------------------------------------------------------------
# Registry - PC 등록부
# ----------------------------------------------------------------------------------------------------

class Registry:
    """PC 등록부. 모든 읽기·쓰기는 잠금 하나 안에서. 쓸 때마다 임시 파일 → os.replace.
    깨진 파일은 .broken 으로 옮기고 빈 등록부 (+ 서버 기록). 대기 중인 등록·마지막 연결 시각은 메모리에만.
    틀린 증명은 세기만 하고 대기를 취소하지 않는다 (검토 I-3) - 대기는 10분이 지나거나 관리자가 취소해야 끝난다.
    seats 는 바꿔 끼울 수 있다 (라이선스의 자리 수). on_save: 파일을 쓴 뒤 부른다 (설치본은 파일 권한을 다시 잠근다)."""

    def __init__(self, path, seats, clock=time.time, on_save=None):
        self.path = os.path.abspath(path)
        self.seats = int(seats)
        self.on_save = on_save
        self._clock = clock
        self._lock = threading.RLock()
        self._pending = {}           # pc_id → {token, label, created_at(ms), expires_at(ms), fails(기록용 - 취소하지 않는다)}
        self._seen = {}              # pc_id → 마지막 연결 ms
        self._next, self._pcs = self._load()
        self.purge()                 # 꺼져 있던 사이에 3일이 지난 열쇠

    def _expired(self, rec, now_ms):
        """지운 지 REMOVED_KEEP_MS 가 지났는데 열쇠가 남아 있는 기록인가."""
        at = rec.get("removed_at")
        return (rec["state"] == "removed" and rec.get("agent_key") is not None
                and (not isinstance(at, int) or isinstance(at, bool) or now_ms - at >= REMOVED_KEEP_MS))

    def purge(self):
        """지운 지 3일 지난 PC 의 열쇠를 파일에서 지운다 → 지운 수. 번호·이름·지운 시각은 남긴다 (번호를 다시 쓰지 않고 실행 기록에 이름이 남게).
        켤 때, 지운 PC 의 열쇠를 찾을 때 부른다. 서버가 오래 켜져 있으면 하루 한 번 부르는 것은 ④ 의 몫."""
        with self._lock:
            now = self._now_ms()
            gone = [k for k, r in self._pcs.items() if self._expired(r, now)]
            if gone:
                pcs = dict(self._pcs)
                for k in gone:
                    pcs[k] = {n: v for n, v in pcs[k].items() if n not in ("agent_key", "relay_key")}
                self._save(self._next, pcs)
            return len(gone)

    @property
    def lock(self):
        """등록부 잠금 (RLock) - 여러 부르기를 한 번에 묶을 때 (local_web._pc_remove 의 상태 보기 + 지우기).
        쥔 채 Store 에 쓰지 않는다 - Store 잠금 안의 확인이 등록부를 읽는다 (Store → Registry 차례)."""
        return self._lock

    # -- 파일 ----------------------------------------------------------------------------------------

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
            rows = raw.get("pcs") if isinstance(raw, dict) else None
            if not isinstance(rows, dict):
                raise ValueError("PC 등록부 꼴이 아님")
        except FileNotFoundError:
            return 1, {}
        except (ValueError, UnicodeDecodeError):
            try:
                os.replace(self.path, self.path + ".broken")
            except OSError:
                pass
            try:
                import local_server
                local_server.log(os.path.dirname(self.path), f"PC 등록부 파일이 깨져 비우고 시작합니다 (옛 파일은 {PCS_NAME}.broken).")
            except Exception:
                pass
            return 1, {}
        pcs = {k: dict(v) for k, v in rows.items()
               if isinstance(k, str) and PC_RE.fullmatch(k) and isinstance(v, dict) and v.get("state") in STATES
               and (v["state"] == "removed" or (isinstance(v.get("agent_key"), str) and isinstance(v.get("relay_key"), str)))}   # 지운 PC 는 3일 뒤 열쇠가 없다
        nxt = raw.get("next")
        if not isinstance(nxt, int) or isinstance(nxt, bool) or nxt < 1:
            nxt = 1
        nxt = max([nxt] + [_pc_num(k) + 1 for k in pcs])         # 손으로 고친 파일이라도 있는 번호를 다시 쓰지 않는다
        return nxt, pcs

    def _save(self, nxt, pcs):
        folder = os.path.dirname(self.path)
        os.makedirs(folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=PCS_NAME + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"v": 1, "next": nxt, "pcs": pcs}, f, ensure_ascii=False, indent=1)
                f.flush()
                os.fsync(f.fileno())
            for attempt in range(6):
                try:
                    os.replace(tmp, self.path)
                    break
                except PermissionError:
                    if attempt == 5:
                        raise
                    time.sleep(0.05 * (attempt + 1))
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
        self._next, self._pcs = nxt, pcs
        if self.on_save:
            try:
                self.on_save()
            except Exception:
                pass

    # -- 안쪽 도움 -----------------------------------------------------------------------------------

    def _now_ms(self):
        return int(self._clock() * 1000)

    def _tick(self):
        """10분 지난 대기를 버린다."""
        now = self._now_ms()
        for pc_id in [k for k, v in self._pending.items() if now >= v["expires_at"]]:
            del self._pending[pc_id]

    def _used(self):
        return sum(1 for r in self._pcs.values() if r["state"] in ("active", "disabled")) + len(self._pending)

    def _fail(self, pc_id):
        """틀린 증명은 세기만 하고 대기를 취소하지 않는다 (검토 I-3) - 256비트 토큰의 HMAC 증명은 맞힐 수 없고, 취소하게 두면
        PC 번호만 아는 누구나 쓰레기 요청 몇 번으로 남의 등록을 막는다. 센 수는 기록용."""
        cur = self._pending.get(pc_id)
        if cur is not None:
            cur["fails"] += 1
        return EnrollError("bad_proof")

    # -- 등록 ----------------------------------------------------------------------------------------

    def start(self, label):
        """새 등록 대기 → {"pc_id", "token", "expires_at"(ms)}. 토큰은 메모리에만 (돌려준 뒤 등록 글로 한 번 보여 준다).
        이름이 틀리면 ValueError, 자리가 없으면 SeatsFull. 번호는 바로 올려 저장한다 (대기만 했던 번호도 다시 쓰지 않는다).
        다음 번호가 PC_MAX 를 넘으면 NumbersFull(ValueError) - 번호를 올리지 않는다."""
        label = clean_label(label)
        with self._lock:
            self._tick()
            if self._next > PC_MAX:
                raise NumbersFull("더 이상 PC 번호를 만들 수 없습니다.")
            if self._used() >= self.seats:
                raise SeatsFull(f"등록할 수 있는 PC 수({self.seats}대)를 모두 썼습니다.")
            pc_id = f"pc_{self._next:02d}"
            self._save(self._next + 1, self._pcs)
            now = self._now_ms()
            token = secrets.token_urlsafe(32)
            self._pending[pc_id] = {"token": token, "label": label, "created_at": now,
                                    "expires_at": now + ENROLL_SEC * 1000, "fails": 0}
            return {"pc_id": pc_id, "token": token, "expires_at": now + ENROLL_SEC * 1000}

    def enroll(self, pc_id, rand_hex, guid, host, proof):
        """PC 의 등록 요청 → (agent_key, relay_key). 거절은 EnrollError(code). 성공하면 기록을 저장하고 대기를 지운다."""
        with self._lock:
            now = self._now_ms()
            cur = self._pending.get(pc_id) if isinstance(pc_id, str) else None
            if cur is None:
                raise EnrollError("unknown")
            if now >= cur["expires_at"]:
                del self._pending[pc_id]
                raise EnrollError("expired")
            if not (isinstance(rand_hex, str) and RAND_RE.fullmatch(rand_hex)
                    and isinstance(guid, str) and GUID_RE.fullmatch(guid)
                    and isinstance(host, str) and 0 < len(host) <= HOST_MAX and host.isprintable()
                    and isinstance(proof, str)):
                raise self._fail(pc_id)
            want = enroll_proof(cur["token"], pc_id, rand_hex, guid, host)
            if not hmac.compare_digest(proof.encode("utf-8"), want.encode("ascii")):
                raise self._fail(pc_id)
            g = guid.lower()
            if any(r["state"] in ("active", "disabled") and str(r.get("guid", "")).lower() == g for r in self._pcs.values()):
                raise EnrollError("duplicate")
            if sum(1 for r in self._pcs.values() if r["state"] in ("active", "disabled")) >= self.seats:
                raise EnrollError("seats")
            agent_key, relay_key = derive_keys(cur["token"], rand_hex)
            rec = {"label": cur["label"], "guid": guid, "host": host, "agent_key": agent_key, "relay_key": relay_key,
                   "state": "active", "created_at": cur["created_at"], "enrolled_at": now}
            self._save(self._next, dict(self._pcs, **{pc_id: rec}))
            del self._pending[pc_id]
            return agent_key, relay_key

    def cancel(self, pc_id):
        """대기 중인 등록을 버린다. 대기가 없으면 False."""
        with self._lock:
            return self._pending.pop(pc_id, None) is not None

    # -- 읽기 ----------------------------------------------------------------------------------------

    def state(self, pc_id):
        """"active" | "disabled" | "removed" | None (모름·대기 중)."""
        with self._lock:
            rec = self._pcs.get(pc_id) if isinstance(pc_id, str) else None
            return rec["state"] if rec is not None else None

    def keys(self, pc_id):
        """(agent_key, relay_key) - 지운 PC 도 3일 동안은 돌려준다 (서버가 '지워짐' 답에 서명해야 해서). 3일이 지났으면 열쇠를 지우고 None.
        모르면 None. 서버 안에서만 쓴다."""
        with self._lock:
            rec = self._pcs.get(pc_id) if isinstance(pc_id, str) else None
            if rec is not None and self._expired(rec, self._now_ms()):
                self.purge()
                rec = self._pcs.get(pc_id)
            if rec is None or rec.get("agent_key") is None:
                return None
            return rec["agent_key"], rec["relay_key"]

    def label(self, pc_id):
        with self._lock:
            if not isinstance(pc_id, str):
                return None
            rec = self._pcs.get(pc_id)
            if rec is not None:
                return rec.get("label") or ""
            self._tick()
            cur = self._pending.get(pc_id)
            return cur["label"] if cur is not None else None

    def list(self):
        """[{pcId, label, host, state("pending"|"active"|"disabled"), enrolledAt, expiresAt, lastSeen}] 번호 순.
        지운 PC 는 뺀다. 열쇠·토큰·guid 는 싣지 않는다. 시각은 모두 ms (없으면 None)."""
        with self._lock:
            self._tick()
            out = []
            for pc_id, rec in self._pcs.items():
                if rec["state"] == "removed":
                    continue
                out.append({"pcId": pc_id, "label": rec.get("label") or "", "host": rec.get("host") or "", "state": rec["state"],
                            "enrolledAt": rec.get("enrolled_at"), "expiresAt": None, "lastSeen": self._seen.get(pc_id)})
            for pc_id, cur in self._pending.items():
                out.append({"pcId": pc_id, "label": cur["label"], "host": "", "state": "pending",
                            "enrolledAt": None, "expiresAt": cur["expires_at"], "lastSeen": None})
            return sorted(out, key=lambda r: _pc_num(r["pcId"]))

    def used(self):
        """쓴 자리 = active + disabled + 살아 있는 대기."""
        with self._lock:
            self._tick()
            return self._used()

    # -- 고치기 --------------------------------------------------------------------------------------

    def rename(self, pc_id, label):
        """이름 바꾸기 (대기 중인 등록도). 틀린 이름은 ValueError, 없는·지운 PC 는 False."""
        label = clean_label(label)
        with self._lock:
            self._tick()
            if isinstance(pc_id, str) and pc_id in self._pending:
                self._pending[pc_id]["label"] = label
                return True
            rec = self._pcs.get(pc_id) if isinstance(pc_id, str) else None
            if rec is None or rec["state"] == "removed":
                return False
            self._save(self._next, dict(self._pcs, **{pc_id: dict(rec, label=label)}))
            return True

    def disable(self, pc_id, on):
        """사용 중지(on=True) / 다시 사용(on=False). 없는·지운 PC 는 False."""
        with self._lock:
            rec = self._pcs.get(pc_id) if isinstance(pc_id, str) else None
            if rec is None or rec["state"] == "removed":
                return False
            want = "disabled" if on else "active"
            if rec["state"] != want:
                self._save(self._next, dict(self._pcs, **{pc_id: dict(rec, state=want)}))
            return True

    def remove(self, pc_id):
        """지우기 - state=removed, removed_at 을 남기고 자리를 돌려준다. 대기 중인 등록이면 그 대기를 버린다. 없거나 이미 지웠으면 False."""
        with self._lock:
            if isinstance(pc_id, str) and self._pending.pop(pc_id, None) is not None:
                return True
            rec = self._pcs.get(pc_id) if isinstance(pc_id, str) else None
            if rec is None or rec["state"] == "removed":
                return False
            self._save(self._next, dict(self._pcs, **{pc_id: dict(rec, state="removed", removed_at=self._now_ms())}))
            self._seen.pop(pc_id, None)
            return True

    def seen(self, pc_id):
        """마지막 연결 시각 (메모리에만, ms)."""
        with self._lock:
            self._seen[pc_id] = self._now_ms()
