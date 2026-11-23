# -*- coding: utf-8 -*-
"""휴대폰 앱 흉내 - 스탠드얼론 PC 의 휴대폰 포트(HTTPS 8782)에 붙는 쪽 (약속 docs/phone-local-contract.md).

앱 만드는 사람의 본보기로 쓰려고 표준 라이브러리만 쓰고, 서버 코드(local_phone)를 불러오지 않는다 - 열쇠·서명 식을 여기서 따로 계산한다
(시험이 두 계산이 같은지 본다). 차례:
  1. QR 글을 읽는다 (parse_qr) - 주소들·포트·휴대폰 번호·짝 열쇠·인증서 지문
  2. 연결하면 **요청을 보내기 전에** 서버 인증서(DER)의 SHA-256 을 QR 의 fp 와 견준다 - 다르면 PinError, 아무것도 보내지 않는다
  3. 요청마다 서명 머리글 넷 (X-AP-Phone·X-AP-Time·X-AP-Nonce·X-AP-Sign), 응답의 X-AP-Sign 을 확인한다 (틀리면 SignError)
  4. 401 clock 이면 서버 시각(now_ms)과의 차이를 맞추고 한 번만 다시 보낸다
    python tests/fake_phone_local.py --vectors     약속 문서의 예시 값을 찍는다
"""
import base64
import hashlib
import hmac
import http.client
import json
import os as _os
import re
import secrets
import ssl
import sys
import time
import urllib.parse

PAIR, REQUEST, CODE = "/phone/v1/pair", "/phone/v1/request", "/phone/v1/code"
CONNECT_SEC = 3                      # 주소가 여럿이면 차례로 이만큼씩 해 본다


class PinError(Exception):
    """서버 인증서의 지문이 QR 의 fp 와 다르다 - 같은 망의 다른 기기가 PC 를 흉내 낸다. 아무것도 보내지 않았다."""


class SignError(Exception):
    """응답 서명이 없거나 틀리다 - 우리 PC 의 답이 아니다."""


# --- 열쇠 · 서명 (약속 4·5절) ---------------------------------------------------------------------
def _mac(key_hex, parts):
    return hmac.new(key_hex.encode("utf-8"), "\n".join(parts).encode("utf-8"), hashlib.sha256).hexdigest()


def _sha(body):
    return hashlib.sha256(body or b"").hexdigest()


def pair_key(secret):
    return hashlib.sha256(b"ap1 phone pair\n" + secret).hexdigest()


def sign_key(secret, rand):
    return hashlib.sha256(b"ap1 phone key\n" + secret + rand).hexdigest()


def request_mac(key, phone_id, method, target, ts, nonce, body):
    return _mac(key, ["ap1", "phone-req", phone_id, method, target, str(ts), nonce, _sha(body)])


def response_mac(key, nonce, status, body):
    return _mac(key, ["ap1", "phone-res", nonce, str(status), _sha(body)])


def b64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def parse_qr(text):
    """autopilot-phone://pair?v=1&h=<주소,주소>&p=<포트>&id=<휴대폰 번호>&k=<짝 열쇠 base64url 43자>&fp=<지문 hex 64자>"""
    u = urllib.parse.urlsplit(text)
    if u.scheme != "autopilot-phone" or u.netloc != "pair":
        raise ValueError("오토파일럿 QR 이 아닙니다")
    q = dict(urllib.parse.parse_qsl(u.query, keep_blank_values=True))
    if q.get("v") != "1" or not re.fullmatch(r"ph_[0-9a-f]{8}", q.get("id", "")) or not re.fullmatch(r"[0-9a-f]{64}", q.get("fp", "")) \
            or not re.fullmatch(r"[A-Za-z0-9_-]{43}", q.get("k", "")) or not q.get("p", "").isdigit():
        raise ValueError("QR 내용이 올바르지 않습니다")
    return {"hosts": [h for h in q.get("h", "").split(",") if h], "port": int(q["p"]), "phone_id": q["id"],
            "secret": base64.urlsafe_b64decode(q["k"] + "="), "fp": q["fp"]}


class FakePhone:
    def __init__(self, qr_text, key=None):
        self.qr = parse_qr(qr_text)
        self.phone_id = self.qr["phone_id"]
        self.key = key                   # 서명 열쇠 (짝지은 뒤) - 진짜 앱은 기기의 안전한 저장소에 둔다
        self.offset_ms = 0               # 서버 시각 - 휴대폰 시각
        self.host = None                 # 지난번에 닿은 주소
        self.connects = 0                # 연결한 횟수 (지문이 틀린 것 포함)

    # --- 연결 (지문 고정) ---
    def _connect(self):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False       # 이름·기관·날짜는 믿지 않는다 - 지문이 그 일을 한다
        ctx.verify_mode = ssl.CERT_NONE
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        last = None
        hosts = ([self.host] if self.host else []) + [h for h in self.qr["hosts"] if h != self.host]
        for host in hosts:
            conn = http.client.HTTPSConnection(host, self.qr["port"], context=ctx, timeout=CONNECT_SEC)
            try:
                conn.connect()
            except OSError as e:
                last = e
                conn.close()
                continue
            self.connects += 1
            der = conn.sock.getpeercert(binary_form=True)
            if not hmac.compare_digest(hashlib.sha256(der).hexdigest(), self.qr["fp"]):
                conn.close()
                raise PinError("PC 를 확인할 수 없습니다. 다시 연결(QR)하여 주십시오.")
            self.host = host
            return conn
        raise ConnectionError(f"PC 에 연결하지 못했습니다 ({type(last).__name__ if last else '주소 없음'})")

    def now_ms(self):
        return int(time.time() * 1000) + self.offset_ms

    def call(self, method, path, body=None, key=None, ts=None, nonce=None, headers=None, sign=True, verify_key=None, raw=None):
        """요청 한 번 → (상태, 머리글 dict(소문자 이름), 본문 dict). 틀린 요청을 만드는 데도 쓴다 (key·ts·nonce·headers·sign·raw).
        응답에 서명이 있으면 확인한다 (verify_key, 없으면 key) - 틀리면 SignError. 200 인데 서명이 없어도 SignError."""
        key = key or self.key or ""
        data = raw if raw is not None else (b"" if body is None else json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        ts = self.now_ms() if ts is None else ts
        nonce = nonce or secrets.token_hex(16)
        hs = {}
        if sign:
            hs = {"X-AP-Phone": self.phone_id, "X-AP-Time": str(ts), "X-AP-Nonce": nonce,
                  "X-AP-Sign": request_mac(key, self.phone_id, method, path, ts, nonce, data)}
        if data or method == "POST":
            hs["Content-Type"] = "application/json"
        hs.update(headers or {})
        conn = self._connect()
        try:
            conn.request(method, path, body=data if (data or method == "POST") else None, headers=hs)
            resp = conn.getresponse()
            got = resp.read()
            status, rh = resp.status, {k.lower(): v for k, v in resp.getheaders()}
        finally:
            conn.close()
        sig = rh.get("x-ap-sign")
        check_key = verify_key if (verify_key and status == 200) else key
        if sig is not None and not hmac.compare_digest(sig, response_mac(check_key, nonce, status, got)):
            raise SignError("응답 서명이 틀립니다")
        if status == 200 and sig is None:
            raise SignError("응답에 서명이 없습니다")
        try:
            value = json.loads(got.decode("utf-8")) if got else None
        except ValueError:
            value = None
        return status, rh, value

    def _again_on_clock(self, method, path, body=None):
        status, rh, value = self.call(method, path, body)
        if status == 401 and isinstance(value, dict) and value.get("error") == "clock" and "x-ap-sign" in rh:
            delta = int(value["now_ms"]) - self.now_ms()
            self.offset_ms += delta                                      # 서버 시각에 맞추고 한 번만 다시
            if isinstance(body, dict) and isinstance(body.get("sms_at"), int):
                body = dict(body, sms_at=body["sms_at"] + delta)         # 받은 시각도 X-AP-Time 과 같은 시계로 (약속 5.4·5.7)
            status, rh, value = self.call(method, path, body)
        return status, rh, value

    # --- 앱이 하는 일 ---
    def pair(self, os="android", app_version="test", device="Fake", rand=None):
        """QR 로 짝짓는다 → 응답 본문. 성공하면 self.key = 서명 열쇠 (응답이 그 열쇠로 서명돼 왔는지 확인한 뒤). 짝 열쇠는 버린다."""
        rand = rand if rand is not None else _os.urandom(32)
        secret = self.qr["secret"]
        new_key = sign_key(secret, rand)
        status, _, value = self.call("POST", PAIR, {"rand": b64url(rand), "os": os, "app_version": app_version, "device": device},
                                     key=pair_key(secret), verify_key=new_key)
        self.pair_status = status
        if status == 200:
            self.key = new_key
        return value

    def request(self):
        """열린 요청 보기 → {open: false} 또는 {open: true, req_id, site, senders, left_ms}."""
        return self._again_on_clock("GET", REQUEST)[2]

    def send_code(self, req_id, code, sender, sms_at=None):
        """번호 보내기 → (상태, 본문). 보내는 것은 번호·발신번호·받은 시각뿐 (문자 본문은 보내지 않는다)."""
        body = {"req_id": req_id, "code": code, "sender": sender, "sms_at": self.now_ms() if sms_at is None else sms_at}
        status, _, value = self._again_on_clock("POST", CODE, body)
        return status, value

    def on_sms(self, sender, body):
        """문자가 왔을 때 앱이 할 일 그대로 → 보낸 번호 (안 보냈으면 None). 문자가 온 순간에만 묻는다 (폴링 없음).
        ① 본문에서 인증번호 숫자만 (sms_watch.extract_auth_code) ② 열린 요청 보기 ③ 발신번호(+82 → 0, 숫자만)가 요청의 senders 에
        있을 때만 번호를 보낸다."""
        root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        if root not in sys.path:
            sys.path.insert(0, root)
        import otp_relay
        import sms_watch
        code = sms_watch.extract_auth_code(body)
        if not code:
            return None
        req = self.request()
        if not isinstance(req, dict) or not req.get("open"):
            return None
        number = otp_relay.sender_number(sender)
        if number not in (req.get("senders") or []):
            return None
        status, _ = self.send_code(req["req_id"], code, number)
        return code if status == 200 else None


# --- 약속 문서의 예시 값 (--vectors) ---------------------------------------------------------------
VECTOR_SECRET = bytes(range(32))
VECTOR_RAND = bytes(range(32, 64))
VECTOR_PHONE = "ph_0a1b2c3d"
VECTOR_TS = 1795000000000
VECTOR_NONCE = "000102030405060708090a0b0c0d0e0f"


def vectors():
    """정해 둔 입력으로 계산한 값 [(이름, 값)] - docs/phone-local-contract.md 8절에 그대로 붙어 있어야 한다 (시험이 본다)."""
    pk = pair_key(VECTOR_SECRET)
    sk = sign_key(VECTOR_SECRET, VECTOR_RAND)
    pair_body = json.dumps({"rand": b64url(VECTOR_RAND), "os": "android", "app_version": "1.0.0", "device": "SM-S918N"},
                           separators=(",", ":")).encode("utf-8")
    code_body = json.dumps({"req_id": "req_0123456789abcdef", "code": "482913", "sender": "15881234", "sms_at": VECTOR_TS},
                           separators=(",", ":")).encode("utf-8")
    res_body = b'{"ok":true,"now_ms":1795000000000}'
    return [
        ("secret (hex)", VECTOR_SECRET.hex()),
        ("k (QR, base64url)", b64url(VECTOR_SECRET)),
        ("rand (hex)", VECTOR_RAND.hex()),
        ("rand (base64url)", b64url(VECTOR_RAND)),
        ("pair_key", pk),
        ("sign_key", sk),
        ("pair body", pair_body.decode("utf-8")),
        ("pair body sha256", _sha(pair_body)),
        ("X-AP-Sign POST /phone/v1/pair (pair_key)", request_mac(pk, VECTOR_PHONE, "POST", PAIR, VECTOR_TS, VECTOR_NONCE, pair_body)),
        ("X-AP-Sign GET /phone/v1/request (sign_key, 빈 본문)", request_mac(sk, VECTOR_PHONE, "GET", REQUEST, VECTOR_TS, VECTOR_NONCE, b"")),
        ("code body", code_body.decode("utf-8")),
        ("X-AP-Sign POST /phone/v1/code (sign_key)", request_mac(sk, VECTOR_PHONE, "POST", CODE, VECTOR_TS, VECTOR_NONCE, code_body)),
        ("response body", res_body.decode("utf-8")),
        ("response X-AP-Sign (sign_key, 200)", response_mac(sk, VECTOR_NONCE, 200, res_body)),
    ]


if __name__ == "__main__":
    if "--vectors" in sys.argv:
        sys.stdout.reconfigure(encoding="utf-8")
        print(f"입력: 짝 열쇠 bytes(range(32)), rand bytes(range(32, 64)), 휴대폰 번호 {VECTOR_PHONE}, 시각 {VECTOR_TS}, nonce {VECTOR_NONCE}")
        for name, value in vectors():
            print(f"{name}: {value}")
    else:
        print(__doc__)
