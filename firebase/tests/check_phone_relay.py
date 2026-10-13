"""휴대폰 중계 약속 시험 - 인증번호 중계(설계 docs/superpowers/specs/2026-10-12-phone-otp-relay-design.md)의 휴대폰 쪽을 흉내 낸다.
(2026-10-13 phone_relay/fake_phone.py 에서 옮김. 진짜 휴대폰 앱·단축어는 맥에서 따로 만든다 - 설계 12절)

안드로이드 앱·아이폰 단축어가 할 일을 그대로 한다 (REST 만):
  문자가 오면 → 숫자만 뽑고 → 자기 requests/.../current 를 한 번 읽고 →
  열려 있고(2분 안) 발신번호가 senders 안이면 → codes/.../current 에 번호만 쓴다. 본문은 안 보낸다.

에뮬레이터 끝에서 끝까지 시험 (firebase/tests 폴더, emu_env.ps1 을 읽은 창):
  firebase emulators:exec --config ../firebase.json --only auth,database --project rpa-test-f02e0 "python check_phone_relay.py"
"""
import json
import os
import re
import secrets
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "agent"))
sys.path.insert(0, os.path.join(HERE, "..", ".."))
import fb                                      # noqa: E402  에이전트의 REST 클라이언트 (SDK 없음 - 휴대폰과 같은 길)
from sms_watch import extract_auth_code        # noqa: E402  안드로이드·단축어도 이 규칙과 같은 답을 내야 한다

OPEN_MS = 120000          # 요청 하나가 열려 있는 시간 (규칙과 같은 값)


def digits(s):
    return re.sub(r"\D", "", s or "")


def on_sms(client, cid, phone_id, sender, body, now_ms=None):
    """문자 한 통. 보냈으면 번호, 아니면 None. 서버로 가는 것은 번호·발신번호·시각뿐."""
    code = extract_auth_code(body)
    if not code:
        return None
    req = client.get(f"apps/otp/requests/{cid}/{phone_id}/current")
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    sender = digits(sender)
    if not req or req.get("created_at", 0) + OPEN_MS <= now_ms or sender not in (req.get("senders") or {}):
        return None                            # STAND BY 아님 / 다른 발신번호(은행·카드) - 아무것도 안 보낸다
    client.put(f"apps/otp/codes/{cid}/{phone_id}/current", {
        "req_id": req["req_id"], "code": code, "sender": sender,
        "sms_at": now_ms, "written_at": {".sv": "timestamp"}})
    return code


def beat(client, cid, phone_id, os_name="android", app_version="fake"):
    client.put(f"apps/otp/phones/{cid}/{phone_id}",
               {"os": os_name, "app_version": app_version, "last_seen": {".sv": "timestamp"}})


# ---------------------------------------------------------------------------
# 에뮬레이터 시험 - RPA 쪽(요청 열기·번호 기다리기·지우기)은 2단계에서 web_runner 로 옮긴다
# ---------------------------------------------------------------------------
PROJECT = "rpa-test-f02e0"
DB_URL = f"http://127.0.0.1:9000/?ns={PROJECT}-default-rtdb"


def _emu_user(email, claims):
    host = os.environ["FIREBASE_AUTH_EMULATOR_HOST"]
    base = f"http://{host}/identitytoolkit.googleapis.com/v1"

    def post(url, body, headers=None):
        req = urllib.request.Request(url, json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", **(headers or {})})
        return json.loads(urllib.request.urlopen(req).read())

    uid = post(f"{base}/accounts:signUp?key=x", {"email": email, "password": "pw123456"})["localId"]
    post(f"{base}/projects/{PROJECT}/accounts:update", {"localId": uid, "customAttributes": json.dumps(claims)},
         {"Authorization": "Bearer owner"})
    return fb.Client({"api_key": "x", "email": email, "password": "pw123456", "database_url": DB_URL})


def _denied(fn):
    try:
        fn()
    except fb.HttpError as e:
        return e.status in (401, 403)
    return False


def demo():
    assert os.environ.get("FIREBASE_AUTH_EMULATOR_HOST"), "에뮬레이터 안에서만 돈다 (emulators:exec)"
    agent = _emu_user("agent-pc1@t.local", {"cid": "ca", "pcId": "pc1", "role": "agent"})
    phone = _emu_user("phone-ph1@t.local", {"cid": "ca", "phoneId": "ph1", "role": "phone"})
    other = _emu_user("phone-ph2@t.local", {"cid": "ca", "phoneId": "ph2", "role": "phone"})
    req_path, code_path = "apps/otp/requests/ca/ph1/current", "apps/otp/codes/ca/ph1/current"
    sms = "[Web발신] 가나몰 인증번호 [482913] 를 입력하세요"

    beat(phone, "ca", "ph1")
    assert agent.get("apps/otp/phones/ca/ph1")["last_seen"] > 0

    # 요청 없음 → 휴대폰은 아무것도 안 보낸다
    assert on_sms(phone, "ca", "ph1", "1588-1234", sms) is None
    # ① RPA 가 요청을 연다 (STAND BY)
    req_id = "req_" + secrets.token_hex(8)
    agent.put(req_path, {"req_id": req_id, "site": "가나몰", "senders": {"15881234": True},
                         "pcId": "pc1", "created_at": {".sv": "timestamp"}})
    # 은행 문자·인증번호 없는 문자·다른 휴대폰 → 안 간다
    assert on_sms(phone, "ca", "ph1", "1599-0000", "[국민] 인증번호 [111111]") is None
    assert on_sms(phone, "ca", "ph1", "1588-1234", "주문이 접수되었습니다") is None
    assert _denied(lambda: on_sms(other, "ca", "ph1", "1588-1234", sms))      # 남의 요청은 읽지도 못한다
    assert agent.get(code_path) is None
    # ③~⑤ 맞는 문자 → 번호만 간다
    assert on_sms(phone, "ca", "ph1", "1588-1234", sms) == "482913"
    # ⑥ RPA 가 받는다 - req_id 가 맞는 것만
    got = agent.get(code_path)
    assert got["req_id"] == req_id and got["code"] == "482913" and got["sender"] == "15881234"
    assert set(got) == {"req_id", "code", "sender", "sms_at", "written_at"}, got    # 본문 없음
    # ⑦ 쓰고 지운다
    agent.delete(code_path)
    assert agent.get(code_path) is None
    agent.delete(req_path)
    assert agent.get(req_path) is None
    assert _denied(lambda: agent.get(code_path))     # 요청이 닫히면 번호 자리는 아무도 못 읽는다
    assert on_sms(phone, "ca", "ph1", "1588-1234", sms) is None             # 닫힌 뒤엔 다시 안 보낸다
    # 휴대폰이 확인을 건너뛰고 억지로 써도 서버가 막는다 (2분 지남은 rules.test.js 에서)
    assert _denied(lambda: phone.put(code_path, {"req_id": req_id, "code": "482913", "sender": "15881234",
                                                 "sms_at": 1, "written_at": {".sv": "timestamp"}}))
    print("통과: 휴대폰 중계 끝에서 끝까지 (에뮬레이터)")


if __name__ == "__main__":
    demo()
