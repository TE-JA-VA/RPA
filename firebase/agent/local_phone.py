# -*- coding: utf-8 -*-
"""스탠드얼론 휴대폰 창구 - 직원 휴대폰 앱이 사내 와이파이로 이 PC 의 로컬 서버에 인증번호(숫자만)를 보낸다
(설계 2026-11-23-standalone 7절, 계획 2026-11-23-standalone-4-phone, 앱 쪽 약속은 docs/phone-local-contract.md).

이 파일이 맡는 것:
  Phones   짝지은 휴대폰 표 (자료 폴더 phones.json - 서명 열쇠가 들어 있어 관리자·SYSTEM 만 읽는다)
  Pairing  짝짓기 하나 (QR 의 짝 열쇠는 메모리에만, 5분·한 번)
  Desk     인증번호 자리의 규칙 (일반 버전 RTDB 규칙과 같은 뜻 - 요청은 2분, 번호는 열린 요청의 발신번호만, 쓰면 지움)
  Service  위 셋과 휴대폰 포트(Gate)를 묶고 5초마다 지난 자리를 지운다
  Gate·PhoneServer  사내망 HTTPS 포트 하나 (8782) - /phone/v1/pair·request·code 세 주소만 안다. 웹·/api·/db·/fs 를 부르지 않는다
휴대폰 포트를 열어도 이 파일은 밖으로 연결을 걸지 않는다 (받기만 한다).
비밀 값(짝 열쇠·서명 열쇠·인증서 개인 열쇠·인증번호)은 기록·예외 글·저장 파일(store.json)에 싣지 않는다.
표준 라이브러리만 쓴다.
"""
import base64
import hashlib
import hmac
import ipaddress
import json
import math
import os
import re
import secrets
import socket
import socketserver
import ssl
import subprocess
import sys
import tempfile
import threading
import time

import local_cert
import local_server
import local_store

PHONE_PORT = 8782
OPEN_MS = 120000                     # 요청이 열려 있는 시간 (otp_relay.OPEN_MS 와 같다)
PAIR_SEC = 300                       # QR(짝 열쇠)을 쓸 수 있는 시간
PAIR_FAIL_MAX = 5                    # 짝짓기 서명이 이만큼 틀리면 그 짝짓기를 취소한다
SHOW_SEC = 60                        # 짝짓기 결과(연결됨·시간 지남)를 화면에 보여 주는 시간
SIGN_WINDOW_MS = 120000              # 요청 시각과 서버 시각의 차이 (닫힌 망의 PC 는 시계가 틀릴 수 있다 - 넘으면 clock 으로 알려 준다)
NONCE_KEEP_SEC = 300
PHONES_NAME = "phones.json"
PHONES_MAX = 20
SENDERS_MAX = 20
CODE_PUTS_MAX = 5                    # 같은 요청에 번호를 쓸 수 있는 횟수
SMS_EARLY_MS = 30000                 # 요청이 열린 시각보다 이만큼 넘게 이른 문자는 받지 않는다 (지난 문자의 번호, 시계 오차는 이 안)
SWEEP_SEC = 5
NAME_MAX = 40
H_PHONE = "X-AP-Phone"
H_TIME, H_NONCE, H_SIGN = local_store.H_TIME, local_store.H_NONCE, local_store.H_SIGN
PHONE_ID_RE = re.compile(r"ph_[0-9a-f]{8}")
SENDER_RE = re.compile(r"[0-9]{3,15}")
CODE_RE = re.compile(r"[0-9]{4,8}")
REQ_ID_RE = re.compile(r"[A-Za-z0-9_-]{8,64}")
CODE_KEYS = ("req_id", "code", "sender", "sms_at")


def _now_ms(clock):
    return int(clock() * 1000)


def _sha256hex(body):
    return hashlib.sha256(body or b"").hexdigest()


# ----------------------------------------------------------------------------------------------------
# 열쇠 · 서명 (앱 쪽 약속 docs/phone-local-contract.md 4·5절 - 바꾸면 약속 문서·시험을 같이 고친다)
# ----------------------------------------------------------------------------------------------------

def pair_key(secret):
    """짝짓기 요청 하나만 서명하는 열쇠 = sha256("ap1 phone pair\\n" + 짝 열쇠 32바이트) 소문자 hex."""
    return hashlib.sha256(b"ap1 phone pair\n" + bytes(secret)).hexdigest()


def sign_key(secret, rand):
    """짝지은 뒤 모든 요청의 서명 열쇠 = sha256("ap1 phone key\\n" + 짝 열쇠 + 휴대폰이 만든 32바이트) 소문자 hex.
    휴대폰 쪽 무작위(rand)가 섞여 QR 사진만으로는 이 열쇠를 만들지 못한다."""
    return hashlib.sha256(b"ap1 phone key\n" + bytes(secret) + bytes(rand)).hexdigest()


def request_mac(key, phone_id, method, target, ts, nonce, body):
    """휴대폰 요청 서명 = HMAC-SHA256(열쇠 hex 글의 UTF-8, 조각을 \\n 으로 이은 글) 소문자 hex.
    조각: ap1 · phone-req · 휴대폰 번호 · 방법 · 보낸 그대로의 경로 · 시각(ms 글자) · nonce · 본문 sha256 hex."""
    return local_store._mac(key, ["ap1", "phone-req", phone_id, method, target, str(ts), nonce, _sha256hex(body)])


def response_mac(key, nonce, status, body):
    """서버 응답 서명 - 그 요청의 nonce 에 묶인다. 조각: ap1 · phone-res · nonce · 상태 번호 · 본문 sha256 hex."""
    return local_store._mac(key, ["ap1", "phone-res", nonce, str(status), _sha256hex(body)])


def b64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def unb64url(text):
    """base64url(채움 없음) → bytes. 꼴이 틀리면 ValueError."""
    if not isinstance(text, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", text):
        raise ValueError("base64url 이 아님")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def parse_senders(value):
    """허용 발신번호: 글(쉼표·빈칸·; 로 나눔)이나 목록 → 숫자 글 목록 (-·(·) 는 뺀다, 겹친 것은 하나로).
    관리 화면 ops.js parseSenders 와 같은 글로 ValueError."""
    if value is None:
        items = []
    elif isinstance(value, (list, tuple)):
        items = [str(x) for x in value]
    elif isinstance(value, str):
        items = re.split(r"[\s,;]+", value)
    else:
        raise ValueError("발신번호의 형식이 올바르지 않습니다.")
    out = []
    for raw in items:
        n = re.sub(r"[-()]", "", raw.strip())
        if n and n not in out:
            out.append(n)
    bad = [n for n in out if not SENDER_RE.fullmatch(n)]
    if bad:
        raise ValueError(f"발신번호는 숫자 3~15자리여야 합니다: {', '.join(bad)}")
    if len(out) > SENDERS_MAX:
        raise ValueError(f"발신번호는 {SENDERS_MAX}개까지 입력할 수 있습니다.")
    return out


def clean_name(value, what="이름"):
    """이름·담당자 칸 (앞뒤 빈칸 없이 NAME_MAX 자까지, 줄바꿈 등 제어 글자 없이). 아니면 ValueError."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{what}의 형식이 올바르지 않습니다.")
    text = value.strip()
    if len(text) > NAME_MAX:
        raise ValueError(f"{what}은(는) {NAME_MAX}자까지 입력할 수 있습니다.")
    if any(ord(c) < 32 for c in text):
        raise ValueError(f"{what}에 쓸 수 없는 글자가 있습니다.")
    return text


def new_phone_id():
    return "ph_" + secrets.token_hex(4)


# ----------------------------------------------------------------------------------------------------
# Phones - 짝지은 휴대폰 표 (phones.json)
# ----------------------------------------------------------------------------------------------------

class Phones:
    """phones.json = {"v": 1, "phones": {<번호>: {label, owner, senders: [..], key, fp, paired_at, os, app_version, device}}}.
    key = 서명 열쇠 (sign_key - 저장한 이 값이 곧 열쇠다, 그래서 파일은 관리자·SYSTEM 만), fp = 짝지을 때의 인증서 지문.
    쓸 때마다 임시 파일 → os.replace. 깨진 파일은 .broken 으로 옮기고 빈 표 (+ 서버 기록). 마지막 연결 시각은 메모리에만.
    on_save: 파일을 쓴 뒤 부른다 (설치본은 파일 권한을 다시 잠근다 - Service)."""

    def __init__(self, path, on_save=None):
        self.path = os.path.abspath(path)
        self.on_save = on_save
        self._lock = threading.RLock()
        self._seen = {}
        self._data = self._load()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
            rows = raw.get("phones") if isinstance(raw, dict) else None
            if not isinstance(rows, dict):
                raise ValueError("휴대폰 표 꼴이 아님")
        except FileNotFoundError:
            return {}
        except (ValueError, UnicodeDecodeError):
            try:
                os.replace(self.path, self.path + ".broken")
            except OSError:
                pass
            local_server.log(os.path.dirname(self.path), "휴대폰 표 파일이 깨져 비우고 시작합니다 (옛 파일은 phones.json.broken).")
            return {}
        return {k: v for k, v in rows.items() if isinstance(k, str) and PHONE_ID_RE.fullmatch(k) and isinstance(v, dict)
                and isinstance(v.get("key"), str)}

    def _save(self, data):
        folder = os.path.dirname(self.path)
        os.makedirs(folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=PHONES_NAME + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"v": 1, "phones": data}, f, ensure_ascii=False, indent=1)
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
        self._data = data
        if self.on_save:
            try:
                self.on_save()
            except Exception:
                pass

    def add(self, id, label, owner, senders, key, fp, os, app_version, device):
        with self._lock:
            data = dict(self._data)
            if id not in data and len(data) >= PHONES_MAX:
                raise ValueError(f"휴대폰은 {PHONES_MAX}대까지 등록할 수 있습니다.")
            data[id] = {"label": label, "owner": owner or "", "senders": list(senders or []), "key": key, "fp": fp,
                        "paired_at": int(time.time() * 1000), "os": os, "app_version": app_version, "device": device}
            self._save(data)

    def get(self, id):
        """휴대폰 하나 (열쇠 포함 - 서버 안에서만 쓴다). 없으면 None."""
        rec = self._data.get(id) if isinstance(id, str) else None
        return dict(rec) if rec is not None else None

    def list(self, fp_now=None):
        """[{id, label, owner, senders, paired_at, last_seen, os, app_version, device, stale}] 이름 순 - 열쇠·지문 없음.
        stale = 짝지을 때의 인증서 지문이 지금 지문과 다르다 (인증서를 다시 만들었다 → 다시 짝지어야 한다)."""
        out = []
        for pid, rec in self._data.items():
            out.append({"id": pid, "label": rec.get("label") or "", "owner": rec.get("owner") or "", "senders": list(rec.get("senders") or []),
                        "paired_at": rec.get("paired_at"), "last_seen": self._seen.get(pid), "os": rec.get("os") or "",
                        "app_version": rec.get("app_version") or "", "device": rec.get("device") or "",
                        "stale": bool(fp_now) and rec.get("fp") != fp_now})
        return sorted(out, key=lambda p: (p["label"], p["id"]))

    def public(self):
        """일반 버전 meta/companies/<cid>/phones 와 같은 꼴 {<번호>: {label, owner, senders?: {<번호>: true}}} (otp_relay.phone_list 가
        그대로 읽는다). 허용 발신번호가 없으면 senders 칸을 뺀다 (= 제한 없음). 휴대폰이 없으면 None."""
        out = {}
        for pid, rec in self._data.items():
            one = {"label": rec.get("label") or "", "owner": rec.get("owner") or ""}
            if rec.get("senders"):
                one["senders"] = {n: True for n in rec["senders"]}
            out[pid] = one
        return out or None

    def update(self, id, label=None, owner=None, senders=None):
        with self._lock:
            if id not in self._data:
                return False
            rec = dict(self._data[id])
            if label is not None:
                rec["label"] = label
            if owner is not None:
                rec["owner"] = owner
            if senders is not None:
                rec["senders"] = list(senders)
            self._save(dict(self._data, **{id: rec}))
            return True

    def remove(self, id):
        with self._lock:
            if id not in self._data:
                return False
            data = {k: v for k, v in self._data.items() if k != id}
            self._save(data)
            self._seen.pop(id, None)
            return True

    def seen(self, id):
        self._seen[id] = int(time.time() * 1000)

    def count(self):
        return len(self._data)


# ----------------------------------------------------------------------------------------------------
# Pairing - 짝짓기 하나
# ----------------------------------------------------------------------------------------------------

class Pairing:
    """한 번에 하나. 짝 열쇠는 메모리에만 있고 5분·한 번 (짝지으면·취소하면·5번 틀리면 버린다).
    화면은 state() 를 2초마다 묻는다 - 결과(paired·expired)는 SHOW_SEC 동안 보여 주고 none."""

    def __init__(self, clock=time.time):
        self._clock = clock
        self._lock = threading.Lock()
        self._cur = None             # {phone_id, secret, label, owner, senders, expires_at, fails}
        self._last = None            # {state, at, phone?}

    def start(self, label, owner, senders):
        with self._lock:
            now = self._clock()
            self._cur = {"phone_id": new_phone_id(), "secret": secrets.token_bytes(32), "label": label, "owner": owner or "",
                         "senders": list(senders or []), "expires_at": now + PAIR_SEC, "fails": 0}
            self._last = None
            return {"phone_id": self._cur["phone_id"], "secret": self._cur["secret"], "expires_at": self._cur["expires_at"]}

    def _tick(self, now):
        cur = self._cur
        if cur is not None and now >= cur["expires_at"]:
            self._cur = None
            self._last = {"state": "expired", "at": cur["expires_at"]}

    def claim(self, phone_id):
        """살아 있는 짝짓기가 phone_id 이면 그 사본 (짝 열쇠 포함), 아니면 None."""
        with self._lock:
            self._tick(self._clock())
            cur = self._cur
            if cur is None or not isinstance(phone_id, str) or phone_id != cur["phone_id"]:
                return None
            return dict(cur)

    def consume(self, phone_id):
        """살아 있는 짝짓기가 phone_id 이면 꺼내고(다시 못 쓴다) 그 사본, 아니면 None - 같은 QR 로 동시에 온 둘 가운데 하나만."""
        with self._lock:
            self._tick(self._clock())
            cur = self._cur
            if cur is None or not isinstance(phone_id, str) or phone_id != cur["phone_id"]:
                return None
            self._cur = None
            return dict(cur)

    def fail(self):
        """짝짓기 서명이 틀렸다 - PAIR_FAIL_MAX 번이면 취소한다."""
        with self._lock:
            if self._cur is not None:
                self._cur["fails"] += 1
                if self._cur["fails"] >= PAIR_FAIL_MAX:
                    self._cur = None

    def done(self, phone):
        """짝지었다 - 짝 열쇠를 버리고 phone({id, label, os, device})을 SHOW_SEC 동안 보여 준다."""
        with self._lock:
            self._cur = None
            self._last = {"state": "paired", "at": self._clock(), "phone": dict(phone)}

    def cancel(self):
        with self._lock:
            self._cur = None
            self._last = None

    def waiting(self):
        with self._lock:
            self._tick(self._clock())
            return self._cur is not None

    def state(self):
        """{"state": "none"|"waiting"|"paired"|"expired", "left_sec"?, "phone"?} - 짝 열쇠·QR 은 싣지 않는다."""
        with self._lock:
            now = self._clock()
            self._tick(now)
            if self._cur is not None:
                return {"state": "waiting", "left_sec": max(0, math.ceil(self._cur["expires_at"] - now - 1e-9))}
            last = self._last
            if last is not None and now - last["at"] < SHOW_SEC:
                out = {"state": last["state"]}
                if "phone" in last:
                    out["phone"] = dict(last["phone"])
                return out
            self._last = None
            return {"state": "none"}


# ----------------------------------------------------------------------------------------------------
# Desk - 인증번호 자리의 규칙 (apps/otp/requests·codes, Store 의 VOLATILE 자리 - 파일에 남지 않는다)
# ----------------------------------------------------------------------------------------------------

class Desk:
    """일반 버전 RTDB 규칙(설계 2026-10-12 4절)과 같은 뜻: 휴대폰은 자기 자리의 열린 요청만 보고, 요청의 발신번호로 온 번호만
    그 요청의 req_id 로 쓴다. 요청은 2분, 번호는 요청이 열려 있고 req_id 가 같을 때만 읽힌다. 확인과 쓰기는 Store 잠금 하나 안에서."""

    def __init__(self, store, phones, lic, clock=time.time):
        self.store, self.phones, self.cid, self._clock = store, phones, lic["cid"], clock
        self._lock = threading.Lock()
        self._puts = {}              # (휴대폰, req_id) → 번호를 쓴 횟수

    def req_path(self, phone_id):
        return f"apps/otp/requests/{self.cid}/{phone_id}/current"

    def code_path(self, phone_id):
        return f"apps/otp/codes/{self.cid}/{phone_id}/current"

    def _alive(self, req, now_ms):
        return isinstance(req, dict) and isinstance(req.get("created_at"), (int, float)) and not isinstance(req.get("created_at"), bool) \
            and req["created_at"] + OPEN_MS > now_ms

    def open_request(self, phone_id):
        """그 휴대폰의 열린 요청 (2분 안) - 없으면 None."""
        req = self.store.get(self.req_path(phone_id))
        return req if self._alive(req, _now_ms(self._clock)) else None

    def _others(self, req, pc_id, now_ms):
        """다른 PC 의 살아 있는 요청인가 (사내 서버 ① Task 5 - 휴대폰 하나에 요청 하나, 설계 7절)."""
        return self._alive(req, now_ms) and req.get("pcId") != pc_id

    def open(self, phone_id, body, pc_id):
        """요청 열기 (모양은 local_server.otp_request_ok 가 이미 봤다) → 열었으면 True. 시각은 이 창구의 시계.
        다른 PC 의 살아 있는 요청이 있으면 쓰지 않고 False - 뒤에 온 PC 는 비거나 2분이 지날 때까지 기다린다 (otp_relay.PhoneRelay.open).
        같은 PC 는 덮어쓴다. 확인과 쓰기는 Store 잠금 하나 안에서 (거의 동시에 연 둘 가운데 하나만)."""
        now_ms = _now_ms(self._clock)
        try:
            self.store.put(self.req_path(phone_id), dict(body, created_at=now_ms),
                           guard=lambda get: not self._others(get(self.req_path(phone_id)), pc_id, now_ms))
        except local_server.Refused:
            return False
        return True

    def close_ok(self, get, phone_id, pc_id):
        """요청·번호 자리 지우기의 guard (Store 잠금 안에서 부른다) - 다른 PC 의 살아 있는 요청이면 False (남이 받는 번호를 지우지 못하게)."""
        return not self._others(get(self.req_path(phone_id)), pc_id, _now_ms(self._clock))

    @staticmethod
    def _well_formed(body):
        if not isinstance(body, dict) or set(body) != set(CODE_KEYS):
            return False
        req_id, code, sender, sms_at = (body.get(k) for k in CODE_KEYS)
        return (isinstance(req_id, str) and REQ_ID_RE.fullmatch(req_id) is not None and isinstance(code, str) and CODE_RE.fullmatch(code) is not None
                and isinstance(sender, str) and SENDER_RE.fullmatch(sender) is not None
                and isinstance(sms_at, int) and not isinstance(sms_at, bool) and sms_at >= 0)

    def submit(self, phone_id, body, sent_ms=None):
        """휴대폰이 보낸 번호 → (상태, 오류 코드|None). 본문은 정확히 {req_id, code, sender, sms_at} - 칸이 더 있으면(문자 본문 등) 거절.
        요청이 열린 시각보다 SMS_EARLY_MS 넘게 이른 문자(지난 문자)는 409 old_sms (검토 2026-11-23, 약속 7절).
        sent_ms = 그 요청의 X-AP-Time (휴대폰 시계) - 있으면 문자 시각을 '보낸 때보다 얼마 전' 으로 바꿔 서버 시계로 견준다
        (닫힌 망의 PC·휴대폰 시계가 틀려도 같은 시계끼리 뺀다)."""
        if not self._well_formed(body):
            return 400, "bad_request"
        now_ms = _now_ms(self._clock)
        sms_ms = body["sms_at"] if sent_ms is None else now_ms - max(0, int(sent_ms) - body["sms_at"])
        why = []
        key = (phone_id, body["req_id"])

        def guard(get):
            req = get(self.req_path(phone_id))
            if not self._alive(req, now_ms):
                why.append((409, "no_request"))
            elif req.get("req_id") != body["req_id"]:
                why.append((409, "req_mismatch"))
            elif body["sender"] not in (req.get("senders") or {}):
                why.append((403, "sender_not_allowed"))
            elif sms_ms < req["created_at"] - SMS_EARLY_MS:
                why.append((409, "old_sms"))
            else:
                with self._lock:
                    n = self._puts.get(key, 0)
                    if n >= CODE_PUTS_MAX:
                        why.append((429, "too_many"))
                    else:
                        self._puts[key] = n + 1
            return not why

        value = {"req_id": body["req_id"], "code": body["code"], "sender": body["sender"], "sms_at": body["sms_at"], "written_at": now_ms}
        try:
            self.store.put(self.code_path(phone_id), value, guard=guard)
        except local_server.Refused:
            return why[0] if why else (409, "no_request")
        return 200, None

    def read_code(self, phone_id, pc_id=None):
        """번호 - 그 휴대폰의 요청이 열려 있고 req_id 가 같을 때만 (요청이 닫히면 아무도 못 읽는다).
        pc_id 가 있으면 그 요청을 연 PC(pcId)일 때만 (사내 서버 ① Task 5 - 다른 PC 는 null)."""
        req = self.open_request(phone_id)
        code = self.store.get(self.code_path(phone_id))
        if req is None or not isinstance(code, dict) or code.get("req_id") != req.get("req_id"):
            return None
        if pc_id is not None and req.get("pcId") != pc_id:
            return None
        return code

    def forget(self, phone_id):
        """그 휴대폰의 요청·번호 자리를 지운다 (휴대폰을 지울 때)."""
        for path in (self.code_path(phone_id), self.req_path(phone_id)):
            self.store.delete(path)
        with self._lock:
            self._puts = {k: v for k, v in self._puts.items() if k[0] != phone_id}

    def sweep(self):
        """2분 지난 요청과 그 번호, 요청 없는(다른 req_id) 번호, 지운 휴대폰의 자리를 지운다 → 지운 자리 수. Service 가 5초마다."""
        now_ms = _now_ms(self._clock)
        gone = 0
        reqs = self.store.get(f"apps/otp/requests/{self.cid}") or {}
        codes = self.store.get(f"apps/otp/codes/{self.cid}") or {}
        live = {}
        for pid, node in (reqs.items() if isinstance(reqs, dict) else []):
            req = node.get("current") if isinstance(node, dict) else None
            if self.phones.get(pid) is not None and self._alive(req, now_ms):
                live[pid] = req.get("req_id")
                continue
            self.store.delete(f"apps/otp/requests/{self.cid}/{pid}",
                              guard=lambda get, p=pid: not (self.phones.get(p) is not None and self._alive(get(self.req_path(p)), _now_ms(self._clock))))
            gone += 1
        for pid, node in (codes.items() if isinstance(codes, dict) else []):
            code = node.get("current") if isinstance(node, dict) else None
            if pid in live and isinstance(code, dict) and code.get("req_id") == live[pid]:
                continue
            try:
                self.store.delete(f"apps/otp/codes/{self.cid}/{pid}", guard=lambda get, p=pid: self._stale_code(get, p))
                gone += 1
            except local_server.Refused:
                pass
        with self._lock:
            self._puts = {k: v for k, v in self._puts.items() if live.get(k[0]) == k[1]}
        return gone

    def _stale_code(self, get, pid):
        """지우기 직전에 다시 본다 - 그 사이 새 요청이 열리고 번호가 들어왔으면 두고 간다."""
        req, code = get(self.req_path(pid)), get(self.code_path(pid))
        keep = (self.phones.get(pid) is not None and self._alive(req, _now_ms(self._clock)) and isinstance(code, dict)
                and code.get("req_id") == req.get("req_id"))
        return not keep


# ----------------------------------------------------------------------------------------------------
# 휴대폰 포트 - 사내망 HTTPS 하나 (PhoneServer·PhoneHandler) 와 그것을 쓸 때만 여는 Gate
# ----------------------------------------------------------------------------------------------------
# 이 포트가 아는 것은 아래 세 주소뿐이다. 처리기는 local_web·/api·/db·/fs 코드를 부르지 않는다 (127.0.0.1:8781 의 Handler 와 다른 클래스).
ROUTES = {("POST", "/phone/v1/pair"): "pair", ("GET", "/phone/v1/request"): "request", ("POST", "/phone/v1/code"): "code"}
MAX_CONN = 16                        # 동시 연결 (127.0.0.1 서버의 상한과 따로 센다)
MAX_PER_IP = 4                       # 주소마다 동시 연결
REQ_PER_MIN = 60                     # 주소마다 분당 연결(= 요청 - 늘 Connection: close)
HANDSHAKE_SEC = 5                    # TLS 악수
READ_SEC = 5                         # 요청 줄·머리글·본문을 이 안에 다 읽어야 한다
HEAD_MAX = 8192
BODY_MAX = 2048
DRAIN_SEC, DRAIN_MAX = 0.3, 16384    # 응답 뒤 읽지 않은 것 비우기 (PhoneHandler._drain)
BAD_LIMIT = 10                       # 한 주소에서 서명 틀림 이만큼이면 (BAD_SEC 안에)
BAD_SEC = 600                        # 그 주소를 이만큼 거절 (429)
TRACK_MAX = 1000                     # 주소·요청 수 표에 기억하는 주소 수
RETRY_SEC = 60                       # 포트를 못 열었으면 5초 고리가 이만큼 뒤에 다시 해 본다 (PowerShell·netsh 를 5초마다 띄우지 않게)
RULE_NAME = "AUTOPILOT Phone OTP"
CREATE_NO_WINDOW = 0x08000000
REASONS = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found", 409: "Conflict",
           413: "Payload Too Large", 429: "Too Many Requests", 500: "Internal Server Error"}
NONCE_RE = re.compile(r"[0-9a-f]{16,64}")
SIGN_RE = re.compile(r"[0-9a-f]{64}")
PAIR_KEYS = ("rand", "os", "app_version", "device")
PUBLIC_MSG = ("이 PC의 네트워크가 '공용'으로 설정되어 있어 휴대폰을 연결할 수 없습니다. 윈도우 설정 → 네트워크 및 인터넷에서 "
              "네트워크 프로필을 '개인'으로 변경한 뒤 다시 시도하여 주십시오.")
NO_LAN_MSG = "이 PC의 사내 네트워크 주소를 찾지 못했습니다. 사내 와이파이·유선 네트워크 연결을 확인한 뒤 다시 시도하여 주십시오."
_DUMMY_KEY = secrets.token_hex(32)   # 없는 휴대폰도 같은 계산을 하게 (걸리는 시간으로 번호가 있는지 알 수 없게)


def tls_context(cert, key):
    """휴대폰 포트의 TLS: 1.2 이상, 1.2 는 ECDHE+AESGCM·ECDHE+CHACHA20 만, 재협상 끔 (옛 안드로이드 1.2 까지)."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.set_ciphers("ECDHE+AESGCM:ECDHE+CHACHA20")
    ctx.options |= getattr(ssl, "OP_NO_RENEGOTIATION", 0)
    ctx.load_cert_chain(cert, key)
    return ctx


def qr_text(hosts, port, phone_id, secret, fingerprint):
    """QR 에 싣는 한 줄 (약속 2절, 이 차례 그대로):
    autopilot-phone://pair?v=1&h=<주소,주소>&p=<포트>&id=<휴대폰 번호>&k=<짝 열쇠 base64url 43자>&fp=<지문 hex 64자>"""
    return f"autopilot-phone://pair?v=1&h={','.join(hosts)}&p={int(port)}&id={phone_id}&k={b64url(secret)}&fp={fingerprint}"


class _Close(Exception):
    """응답 없이 연결을 닫는다."""


class PhoneServer(socketserver.TCPServer):
    """휴대폰 포트. 듣는 소켓은 TLS 로 감싸지 않는다 - 악수는 연결마다 일하는 스레드에서 (악수를 끄는 연결 하나가 받기 고리를 세우지 못하게).
    보낸 쪽 주소·연결 수·분당 요청 수는 받자마자(받기 고리에서) 보고, 넘으면 응답 없이 닫는다. 연결마다 데몬 스레드 하나."""
    allow_reuse_address = False
    request_queue_size = 32

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        socketserver.TCPServer.server_bind(self)        # getfqdn(이름 풀이)을 하지 않는다

    def peer_ip(self, client_address):
        """보낸 쪽 주소를 읽는 한 곳 (시험이 바꿔 끼워 여러 주소를 흉내 낸다)."""
        return client_address[0]

    def _trim(self, table, keep):
        if len(table) > TRACK_MAX:
            for k in [k for k, v in table.items() if not keep(v)]:
                del table[k]
            if len(table) > TRACK_MAX:
                table.clear()

    def process_request(self, request, client_address):
        ip = self.peer_ip(client_address)
        try:
            ok_ip = ipaddress.ip_address(ip)
            ok_ip = ok_ip.is_private or ok_ip.is_loopback       # 방화벽 프로필이 틀어져도 한 겹 더 - 사설·이 PC 주소만
        except ValueError:
            ok_ip = False
        now = time.monotonic()
        with self.lock:
            minute = self.minute.get(ip)
            if minute is None or now - minute[0] >= 60:
                minute = self.minute[ip] = [now, 0]
            minute[1] += 1
            self._trim(self.minute, lambda v: now - v[0] < 60)
            busy = (not ok_ip or self.conns >= MAX_CONN or self.per_ip.get(ip, 0) >= MAX_PER_IP or minute[1] > REQ_PER_MIN)
            if not busy:
                self.conns += 1
                self.per_ip[ip] = self.per_ip.get(ip, 0) + 1
        if busy:
            self.shutdown_request(request)
            return
        try:
            t = threading.Thread(target=self.process_request_thread, args=(request, client_address, ip), daemon=True)
            t.start()
        except Exception:
            self._release(ip)
            self.shutdown_request(request)

    def _release(self, ip):
        with self.lock:
            self.conns -= 1
            n = self.per_ip.get(ip, 1) - 1
            if n > 0:
                self.per_ip[ip] = n
            else:
                self.per_ip.pop(ip, None)

    def process_request_thread(self, request, client_address, ip=None):
        ip = ip if ip is not None else self.peer_ip(client_address)
        tls = None
        timer = threading.Timer(HANDSHAKE_SEC, self._kill, args=(request,))      # 한 바이트씩 끄는 악수도 HANDSHAKE_SEC 에 끊는다
        try:
            request.settimeout(HANDSHAKE_SEC)
            timer.start()
            try:
                tls = self.tls.wrap_socket(request, server_side=True)
            finally:
                timer.cancel()
            PhoneHandler(self, tls, ip).run()
        except Exception:
            pass                     # 악수 실패(TLS 없이 온 HTTP 등)·끊김 - 응답 없이 닫는다
        finally:
            self._release(ip)
            for s in (tls, request):
                try:
                    if s is not None:
                        s.close()
                except OSError:
                    pass

    @staticmethod
    def _kill(sock):
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    # --- 시도 제한 (서명 틀림) - 서비스 시계로 센다 ---
    def blocked(self, ip):
        now = self.service.clock()
        with self.lock:
            e = self.bad.get(ip)
            return bool(e and e[2] > now)

    def note_bad(self, ip):
        """서명 틀림 한 번 - 그 주소에서 BAD_SEC 안에 BAD_LIMIT 번이면 BAD_SEC 동안 거절. 표 = 주소 → [틀린 수, 세기 시작, 거절 끝]."""
        now = self.service.clock()
        with self.lock:
            e = self.bad.get(ip)
            if e is None or now - e[1] > BAD_SEC:
                e = self.bad[ip] = [0, now, e[2] if e else 0]
            e[0] += 1
            if e[0] >= BAD_LIMIT:
                e[0], e[1], e[2] = 0, now, now + BAD_SEC
            self._trim(self.bad, lambda v: v[2] > now or now - v[1] <= BAD_SEC)

    def fresh_nonce(self, phone_id, nonce):
        now = time.monotonic()
        key = phone_id + ":" + nonce
        with self.lock:
            if len(self.nonces) > 5000:
                for k in [k for k, t in self.nonces.items() if t < now]:
                    del self.nonces[k]
            if self.nonces.get(key, 0) >= now:
                return False
            self.nonces[key] = now + NONCE_KEEP_SEC
            return True


class PhoneHandler:
    """연결 하나 = 요청 하나 (늘 Connection: close). 요청 줄·머리글·본문을 READ_SEC 안에 다 읽어야 한다 (느린 연결로 묶지 못하게).
    확인 차례: 경로·방법 → Content-Length → 막힌 주소 → 서명 머리글 → 서명 → nonce → 시각. 없는 휴대폰·틀린 서명·다시 온 nonce 는
    같은 401 unauthorized (서명 없음). 서명을 확인한 뒤의 응답에는 X-AP-Sign. 모든 응답 본문에 now_ms."""
    server_version = "AP"

    def __init__(self, server, sock, ip):
        self.server, self.sock, self.ip = server, sock, ip
        self.service = server.service
        self.deadline = time.monotonic() + READ_SEC

    # --- 읽기 ---
    def _recv(self):
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise _Close()
        self.sock.settimeout(left)
        chunk = self.sock.recv(4096)
        if not chunk:
            raise _Close()
        return chunk

    def _head(self):
        buf = b""
        while b"\r\n\r\n" not in buf:
            if len(buf) > HEAD_MAX:
                raise _Close()
            buf += self._recv()
        head, rest = buf.split(b"\r\n\r\n", 1)
        lines = head.decode("latin-1").split("\r\n")
        parts = lines[0].split(" ")
        if len(parts) != 3 or parts[2] not in ("HTTP/1.1", "HTTP/1.0"):
            raise _Close()
        headers = {}
        for line in lines[1:]:
            name, sep, value = line.partition(":")
            name = name.strip().lower()
            if not sep or not name:
                raise _Close()
            if name in headers and name == "content-length":
                headers[name] = None                     # 길이가 둘 - 틀린 요청
            else:
                headers.setdefault(name, value.strip())
        return parts[0], parts[1], headers, rest

    # --- 쓰기 ---
    def _send(self, status, value, key=None, nonce=None):
        out = dict(value)
        out["now_ms"] = _now_ms(self.service.clock)
        body = json.dumps(out, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        head = [f"HTTP/1.1 {status} {REASONS.get(status, 'Error')}", f"Server: {self.server_version}",
                "Content-Type: application/json; charset=utf-8", f"Content-Length: {len(body)}", "Cache-Control: no-store",
                "Connection: close"]
        if key:
            head.append(f"{H_SIGN}: {response_mac(key, nonce, status, body)}")
        self.sock.settimeout(READ_SEC)
        self.sock.sendall(("\r\n".join(head) + "\r\n\r\n").encode("ascii") + body)

    def run(self):
        try:
            self._handle()
            self._drain()
        except (_Close, OSError, ssl.SSLError, ValueError, UnicodeDecodeError):
            pass
        except Exception as e:                           # 서버가 죽지 않게 - 까닭의 종류만
            local_server.log(self.service.folder, f"휴대폰 요청 처리 오류: {type(e).__name__}")
            try:
                self._send(500, {"error": "server_error"})
            except Exception:
                pass

    def _drain(self):
        """응답을 보낸 뒤 상대가 보내 둔 것(읽지 않은 본문)을 잠깐만 비운다 - 읽지 않은 채 닫으면 윈도우가 RST 를 보내 상대가 응답을
        받기 전에 끊긴다. 응답은 이미 나갔으므로 본문을 '읽고 처리' 하는 것이 아니다 (최대 DRAIN_MAX 바이트·DRAIN_SEC 초)."""
        end, got = time.monotonic() + DRAIN_SEC, 0
        try:
            while got < DRAIN_MAX:
                left = end - time.monotonic()
                if left <= 0:
                    break
                self.sock.settimeout(left)
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                got += len(chunk)
        except (OSError, ssl.SSLError, ValueError):
            pass

    def _handle(self):
        method, target, headers, rest = self._head()
        route = ROUTES.get((method, target))             # 보낸 그대로의 경로 - 질의·%xx·.. 가 붙으면 없는 주소
        if route is None:
            return self._send(404, {"error": "not_found"})
        raw_len = headers.get("content-length")
        if raw_len is None and "content-length" in headers or (raw_len is not None and not raw_len.isdigit()):
            return self._send(400, {"error": "bad_request"})
        length = int(raw_len) if raw_len else 0
        if method == "POST" and raw_len is None:
            return self._send(400, {"error": "bad_request"})
        if method == "GET" and length:
            return self._send(400, {"error": "bad_request"})
        if length > BODY_MAX:
            return self._send(413, {"error": "too_large"})   # 읽지 않는다
        if self.server.blocked(self.ip):
            return self._send(429, {"error": "too_many"})
        body = rest[:length]
        while len(body) < length:
            body += self._recv()
        body = body[:length]
        phone_id, ts = headers.get(H_PHONE.lower(), ""), headers.get(H_TIME.lower(), "")
        nonce, sign = headers.get(H_NONCE.lower(), ""), headers.get(H_SIGN.lower(), "")
        if not (PHONE_ID_RE.fullmatch(phone_id) and ts.isdigit() and len(ts) <= 15 and NONCE_RE.fullmatch(nonce) and SIGN_RE.fullmatch(sign)):
            return self._send(401, {"error": "unauthorized"})
        if route == "pair":
            return self._pair(phone_id, method, target, ts, nonce, sign, body)
        rec = self.service.phones.get(phone_id)
        key = rec["key"] if rec else _DUMMY_KEY
        good = hmac.compare_digest(sign, request_mac(key, phone_id, method, target, ts, nonce, body))
        if not (good and rec):
            self.server.note_bad(self.ip)
            return self._send(401, {"error": "unauthorized"})
        if not self.server.fresh_nonce(phone_id, nonce):
            return self._send(401, {"error": "unauthorized"})
        if abs(_now_ms(self.service.clock) - int(ts)) > SIGN_WINDOW_MS:
            return self._send(401, {"error": "clock"}, key, nonce)       # 서명은 맞다 - 앱이 now_ms 로 시계를 맞추고 한 번 다시
        self.service.phones.seen(phone_id)
        if route == "request":
            req = self.service.desk.open_request(phone_id)
            if req is None:
                return self._send(200, {"open": False}, key, nonce)
            left = int(req["created_at"] + OPEN_MS - _now_ms(self.service.clock))
            return self._send(200, {"open": True, "req_id": req.get("req_id"), "site": req.get("site") or "",
                                    "senders": sorted(req.get("senders") or {}), "left_ms": max(0, left)}, key, nonce)
        try:
            data = json.loads(body.decode("utf-8")) if body else None
        except (ValueError, UnicodeDecodeError):
            data = None
        status, err = self.service.desk.submit(phone_id, data, sent_ms=int(ts))
        return self._send(status, {"ok": True} if status == 200 else {"error": err}, key, nonce)

    def _pair(self, phone_id, method, target, ts, nonce, sign, body):
        """짝짓기: 서명 열쇠 = pair_key(짝 열쇠), 시각은 보지 않는다 (한 번·5분이 지킨다). 맞으면 sign_key 로 표에 넣고 짝 열쇠를 버린다 -
        성공 응답은 **새 서명 열쇠**로 서명한다 (서버가 같은 열쇠를 만들었다는 증거)."""
        pairing = self.service.pairing
        cur = pairing.claim(phone_id)
        key = pair_key(cur["secret"]) if cur else _DUMMY_KEY
        good = hmac.compare_digest(sign, request_mac(key, phone_id, method, target, ts, nonce, body))
        if not (good and cur):
            if cur:                                      # 번호가 맞는 짝짓기에서 서명이 틀렸을 때만 센다 - 번호를 모르는 기기는
                pairing.fail()                           # 주소별 거절(note_bad)로만 (같은 망의 아무 기기나 짝짓기를 취소시키지 못하게, 검토 2026-11-23 I-2)
            self.server.note_bad(self.ip)
            return self._send(401, {"error": "unauthorized"})
        if not self.server.fresh_nonce(phone_id, nonce):
            return self._send(401, {"error": "unauthorized"})
        try:
            data = json.loads(body.decode("utf-8"))
            ok = isinstance(data, dict) and set(data) == set(PAIR_KEYS)
            rand = unb64url(data["rand"]) if ok and isinstance(data.get("rand"), str) and len(data["rand"]) == 43 else b""
            ok = (ok and len(rand) == 32 and data["os"] in ("android", "ios") and isinstance(data["app_version"], str)
                  and 0 < len(data["app_version"]) <= 20 and isinstance(data["device"], str) and 0 < len(data["device"]) <= NAME_MAX
                  and not any(ord(c) < 32 for c in data["app_version"] + data["device"]))
        except (ValueError, UnicodeDecodeError, KeyError):
            ok = False
        if not ok:
            return self._send(400, {"error": "bad_request"}, key, nonce)
        cur = pairing.consume(phone_id)
        if cur is None:                                  # 그 사이 다른 요청이 같은 QR 로 짝지었거나 취소됐다
            return self._send(401, {"error": "unauthorized"})
        new_key = sign_key(cur["secret"], rand)
        try:
            self.service.phones.add(phone_id, cur["label"], cur["owner"], cur["senders"], key=new_key, fp=self.server.fingerprint,
                                    os=data["os"], app_version=data["app_version"], device=data["device"])
        except ValueError:
            return self._send(409, {"error": "phones_full"}, key, nonce)
        self.service.phones.seen(phone_id)
        pairing.done({"id": phone_id, "label": cur["label"], "os": data["os"], "device": data["device"]})
        local_server.log(self.service.folder, f"휴대폰 연결됨  번호={phone_id}  이름={cur['label']}  기기={data['device']} ({data['os']})")
        return self._send(200, {"ok": True, "phone_id": phone_id, "label": cur["label"], "senders": list(cur["senders"])}, new_key, nonce)


def make_phone_server(service, tls, host="0.0.0.0", port=PHONE_PORT):
    """휴대폰 포트를 연다 (serve_forever 는 부르는 쪽이). 쓰는 중인 포트면 OSError (SO_EXCLUSIVEADDRUSE - 두 번째가 조용히 뜨지 않는다)."""
    srv = PhoneServer((host, port), None, bind_and_activate=False)
    srv.service, srv.tls, srv.fingerprint = service, tls, None
    srv.lock = threading.Lock()
    srv.conns, srv.per_ip, srv.minute, srv.bad, srv.nonces = 0, {}, {}, {}, {}
    try:
        srv.server_bind()
        srv.server_activate()
    except BaseException:
        srv.server_close()
        raise
    return srv


# --- 이 PC 의 사내망 주소 (PowerShell 한 번 - 이름 풀이(DNS)를 쓰지 않는다) ---
LAN_SCRIPT = ("[Console]::OutputEncoding = [Text.Encoding]::UTF8; $p = @{}; "
              "Get-NetConnectionProfile -ErrorAction SilentlyContinue | ForEach-Object { $p[[int]$_.InterfaceIndex] = [string]$_.NetworkCategory }; "
              "ConvertTo-Json -Compress -InputObject @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | "
              "ForEach-Object { [pscustomobject]@{ip = [string]$_.IPAddress; category = [string]$p[[int]$_.InterfaceIndex]} })")
CATEGORIES = {"private": "private", "domainauthenticated": "domain", "public": "public"}


def parse_lan(text):
    """LAN_SCRIPT 출력 → [{"ip", "category": private|domain|public|unknown}] (127·169.254·IPv4 가 아닌 것은 뺀다)."""
    try:
        data = json.loads(text) if text and text.strip() else []
    except ValueError:
        return []
    if isinstance(data, dict):
        data = [data]
    out = []
    for x in data if isinstance(data, list) else []:
        if not isinstance(x, dict):
            continue
        ip = str(x.get("ip") or "")
        try:
            addr = ipaddress.IPv4Address(ip)
        except ValueError:
            continue
        if addr.is_loopback or addr.is_link_local:
            continue
        out.append({"ip": ip, "category": CATEGORIES.get(str(x.get("category") or "").lower(), "unknown")})
    return out


LAN_PROBES = ("10.255.255.254", "172.31.255.254", "192.168.255.254")   # 사설 망 셋 - 그쪽으로 나갈 때 윈도우가 고르는 이 PC 주소를 본다


def socket_lan():
    """PowerShell 을 못 쓸 때의 대안 (검토 2026-11-23): UDP 소켓을 사설 주소 쪽으로 connect 만 하고 (아무것도 보내지 않는다 -
    이름 풀이도 없다) 고른 이 PC 주소를 읽는다 → [{"ip", "category": "unknown"}] (사설 IPv4 만, 겹친 것은 하나로). 망의 종류는 모른다."""
    out = []
    for probe in LAN_PROBES:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((probe, 9))
            ip = s.getsockname()[0]
        except OSError:
            continue
        finally:
            s.close()
        try:
            addr = ipaddress.IPv4Address(ip)
        except ValueError:
            continue
        if addr.is_private and not (addr.is_loopback or addr.is_link_local or addr.is_unspecified) and ip not in [x["ip"] for x in out]:
            out.append({"ip": ip, "category": "unknown"})
    return out


def lan_info():
    """이 PC 의 IPv4 주소와 그 망의 종류 [{"ip", "category"}]. PowerShell 로 못 읽으면 socket_lan (종류 unknown), 그것도 없으면 []."""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand",
                            base64.b64encode(LAN_SCRIPT.encode("utf-16-le")).decode("ascii")],
                           capture_output=True, timeout=30, creationflags=CREATE_NO_WINDOW)
        got = parse_lan(r.stdout.decode("utf-8-sig", "replace"))
    except (OSError, subprocess.SubprocessError):
        got = []
    return got or socket_lan()


def _run(cmd):
    """방화벽 명령 한 줄 (창 없음) → 종료 코드."""
    try:
        return subprocess.run(cmd, capture_output=True, timeout=30, creationflags=CREATE_NO_WINDOW).returncode
    except (OSError, subprocess.SubprocessError):
        return -1


class GateError(Exception):
    """휴대폰 포트를 열지 못했다. code: cert·firewall·port-in-use·public-network·no-network, message: 화면에 보일 사람 말."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


class Gate:
    """휴대폰 포트를 쓸 때만 연다 - 짝지은 휴대폰이 있거나 짝짓기 중일 때. 아니면 듣지 않고 방화벽 규칙도 두지 않는다.
    방화벽 규칙은 로컬 서버가 만든다 (감독이 관리자 권한 작업으로 띄운다 - 계획 ④ 사용자 확인 1). 규칙을 못 만들면 듣지 않는다
    (규칙 없이 들으면 윈도우가 '액세스 허용' 창을 띄우고, 누르면 python 전체가 공용 망까지 열린다).
    시험용 덮어쓰기 (rpa_status.dev_env - 소스로 돌 때만): RPA_PHONE_HOST·RPA_PHONE_PORT·RPA_PHONE_NO_FIREWALL=1."""

    def __init__(self, service, folder, run=None, host=None, port=None):
        import rpa_status
        self.service, self.folder = service, folder
        self.run = run or _run
        env_host, env_port = rpa_status.dev_env("RPA_PHONE_HOST"), rpa_status.dev_env("RPA_PHONE_PORT")
        self.host = host or env_host or "0.0.0.0"
        try:
            self.port = int(port if port is not None else (env_port or PHONE_PORT))
        except ValueError:
            self.port = PHONE_PORT
        self.rule_port = self.port or PHONE_PORT
        self.no_firewall = rpa_status.dev_env("RPA_PHONE_NO_FIREWALL") == "1"
        fixed = self.host
        self.lan_info = lan_info if self.host == "0.0.0.0" else (lambda: [{"ip": fixed, "category": "private"}])
        self.netsh = os.path.join(os.environ.get("SystemRoot") or r"C:\Windows", "System32", "netsh.exe")
        self._lock = threading.RLock()
        self.server, self._thread, self._hosts, self._fp = None, None, [], None
        self._fw = "skipped" if self.no_firewall else "none"
        self._checked = False                    # 처음 닫을 때 남은 규칙이 있는지 한 번 본다
        self._fail_at = 0.0
        self._unsure = False                     # 마지막 hosts() 가 종류를 모르는 주소로 정했나
        self.last_error = None

    # --- 방화벽 (결과는 종료 코드만 본다) ---
    def rule_args(self):
        return (f'advfirewall firewall add rule name="{RULE_NAME}" dir=in action=allow protocol=TCP localport={self.rule_port} '
                f'remoteip=localsubnet profile=private,domain program="{sys.executable}" enable=yes')

    def add_command(self):
        """PC 관리자가 직접 실행할 한 줄 (화면의 방화벽 실패 글 끝에 붙는다)."""
        return "netsh " + self.rule_args()

    def _netsh(self, args):
        code = self.run(f'"{self.netsh}" {args}')
        return (code if isinstance(code, int) else getattr(code, "returncode", 1)) == 0

    def firewall_has(self):
        return self._netsh(f'advfirewall firewall show rule name="{RULE_NAME}"')

    def firewall_add(self):
        return self._netsh(self.rule_args())

    def firewall_remove(self):
        return self._netsh(f'advfirewall firewall delete rule name="{RULE_NAME}"')

    # --- 주소 ---
    def hosts(self):
        """QR 에 싣는 주소 - 개인·도메인 망의 것만 넷까지. 모두 공용이면 GateError(public-network)."""
        try:
            info = list(self.lan_info() or [])
        except Exception:
            info = []
        good = [x["ip"] for x in info if x.get("category") in ("private", "domain")][:4]
        self._unsure = False
        if good:
            return good
        if info and all(x.get("category") == "unknown" for x in info):
            # 망 종류를 하나도 모른다 (PowerShell 을 못 써 소켓으로 찾았다) - 그 주소로 연다. 규칙은 개인·도메인 프로필에만 있어
            # 공용 망이면 어차피 닿지 않는다 - 화면이 status 의 network: unknown 을 보고 안내한다
            self._unsure = True
            return [x["ip"] for x in info][:4]
        if info and all(x.get("category") == "public" for x in info):
            raise GateError("public-network", PUBLIC_MSG)
        raise GateError("no-network", NO_LAN_MSG)

    def fingerprint(self):
        if self._fp:
            return self._fp
        path = os.path.join(self.folder, local_cert.CERT_NAME)
        try:
            return local_cert.fingerprint(path) if os.path.isfile(path) else None
        except (OSError, ValueError):
            return None

    # --- 열고 닫기 (잠금 하나) ---
    def open(self):
        """인증서 → 방화벽 규칙 확인·만들기 → bind → 스레드. 이미 열려 있으면 아무것도 안 한다. 실패는 GateError."""
        with self._lock:
            if self.server is not None:
                return self.status()
            hosts = self.hosts()
            try:
                cert, key, fp = local_cert.ensure(self.folder)
            except local_cert.CertError as e:
                raise GateError("cert", str(e)) from None
            self.service.lock_files()
            if not self.no_firewall:
                # 이름만 보고 옛 규칙(다른 프로그램 경로·포트, remoteip 없음)을 그대로 쓰지 않게 늘 지우고 지금 값으로 다시 만든다
                # (같은 이름이 여럿이어도 delete 가 모두 지운다 - 검토 2026-11-23). 권한이 없어 둘 다 못 하면 관리자가 직접 만든 규칙을 쓴다.
                self.firewall_remove()
                if not self.firewall_add() and not self.firewall_has():
                    self._fw = "failed"
                    raise GateError("firewall", "휴대폰 포트의 방화벽 규칙을 만들지 못했습니다. 오토파일럿이 관리자 권한으로 실행 중인지 "
                                                "확인하거나, PC 관리자가 명령 프롬프트(관리자)에서 다음 명령을 한 번 실행한 뒤 다시 시도하여 "
                                                f"주십시오.\n{self.add_command()}")
                self._fw = "ok"
            try:
                srv = make_phone_server(self.service, tls_context(cert, key), self.host, self.port)
            except OSError:
                raise GateError("port-in-use", f"휴대폰 포트 {self.rule_port} 을(를) 다른 프로그램이 사용하고 있습니다.") from None
            srv.fingerprint = fp
            self._thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True, name="phone-port")
            self._thread.start()
            self.server, self._hosts, self._fp, self.last_error = srv, hosts, fp, None
            local_server.log(self.folder, f"휴대폰 포트 열림  포트={srv.server_address[1]}  주소={','.join(hosts)}  방화벽={self._fw}")
            return self.status()

    def close(self):
        """듣기를 끝내고, 휴대폰이 0대면 방화벽 규칙도 지운다."""
        with self._lock:
            if self.server is not None:
                srv, self.server = self.server, None
                srv.shutdown()
                srv.server_close()
                self._hosts = []
                local_server.log(self.folder, "휴대폰 포트 닫힘")
            if self.service.phones.count() == 0 and not self.no_firewall:
                if self._fw in ("ok", "failed") or (not self._checked and self.firewall_has()):
                    self.firewall_remove()
                    self._fw = "none"
            self._checked = True
            return self.status()

    def sync(self, auto=False):
        """짝지은 휴대폰이 있거나 짝짓기 중이면 열고, 아니면 닫는다 → status(). 못 열면 기록만 남긴다 (auto - 5초 고리 - 는
        RETRY_SEC 동안 다시 하지 않는다). 서버 시작·짝짓기 시작/취소/만료·휴대폰 지우기 뒤에 부른다."""
        with self._lock:
            want = self.service.phones.count() > 0 or self.service.pairing.waiting()
            if want and self.server is None:
                if auto and time.monotonic() - self._fail_at < RETRY_SEC and self._fail_at:
                    return self.status()
                try:
                    self.open()
                except GateError as e:
                    self._fail_at, self.last_error = time.monotonic(), e
                    local_server.log(self.folder, f"휴대폰 포트를 열지 못했습니다 ({e.code})")
            elif not want and (self.server is not None or not self._checked):
                self.close()
            return self.status()

    def status(self):
        srv = self.server
        out = {"open": srv is not None, "port": srv.server_address[1] if srv is not None else self.rule_port, "firewall": self._fw,
               "hosts": list(self._hosts) if srv is not None else [], "fingerprint": self.fingerprint()}
        if self._unsure:
            out["network"] = "unknown"           # 망 종류(공용·개인)를 모른다 - 화면 안내 (phone-card.js)
        return out


# ----------------------------------------------------------------------------------------------------
# Service - 표·짝짓기·자리·포트를 묶는다
# ----------------------------------------------------------------------------------------------------

class Service:
    """로컬 서버 하나에 하나 (local_server.main 이 만들어 make_server(phone=)·Web.phone 에 넘긴다).
    start() 의 고리가 5초마다 지난 인증번호 자리를 지우고 휴대폰 포트를 맞춘다(Gate.sync - 쓸 때만 연다)."""

    def __init__(self, folder, store, lic, clock=time.time, run=None, host=None, port=None):
        self.folder, self.store, self.lic, self.clock = folder, store, lic, clock
        self._lock_mu = threading.Lock()
        self._lock_busy = self._lock_again = False
        self.phones = Phones(os.path.join(folder, PHONES_NAME), on_save=self.lock_files_soon)
        self.pairing = Pairing(clock=clock)
        self.desk = Desk(store, self.phones, lic, clock=clock)
        self.gate = Gate(self, folder, run=run, host=host, port=port)
        self._stop = threading.Event()
        self._thread = None

    def lock_files(self):
        """설치본이면 열쇠 파일(phones.json·phone_key.pem 포함) 권한을 관리자·SYSTEM 만 남게 다시 잠근다 (local_server.lock_key_files)."""
        try:
            import rpa_status
            if rpa_status.shipped():
                local_server.lock_key_files(self.folder)
        except Exception:
            pass

    def lock_files_soon(self):
        """휴대폰 표를 쓴 뒤 (Phones.on_save) - lock_files(icacls 여러 번)를 따로 스레드에서 돌린다. 짝짓기 성공 응답이 그것을 기다리지
        않게 (검토 2026-11-23). 도는 중에 또 쓰면 끝난 뒤 한 번 더 돈다. 프로세스가 그 사이 꺼져도 서버가 켤 때 다시 잠근다."""
        with self._lock_mu:
            if self._lock_busy:
                self._lock_again = True
                return
            self._lock_busy = True

        def work():
            while True:
                self.lock_files()
                with self._lock_mu:
                    if not self._lock_again:
                        self._lock_busy = False
                        return
                    self._lock_again = False
        try:
            threading.Thread(target=work, daemon=True, name="phone-lock").start()
        except Exception:
            with self._lock_mu:
                self._lock_busy = self._lock_again = False
            self.lock_files()

    def tick(self):
        """고리 한 번: 지난 자리 지우기 + 포트 맞추기. 예외를 내지 않는다."""
        try:
            self.desk.sweep()
        except Exception as e:
            local_server.log(self.folder, f"인증번호 자리 정리 오류: {type(e).__name__}")
        if self.gate is not None:
            try:
                self.gate.sync(auto=True)
            except Exception as e:
                local_server.log(self.folder, f"휴대폰 포트 확인 오류: {type(e).__name__}")

    def _loop(self):
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(SWEEP_SEC)

    def start(self):
        if self._thread is None:
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True, name="phone-service")
            self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(10)
            self._thread = None
        if self.gate is not None:
            try:
                self.gate.close()
            except Exception:
                pass
