# -*- coding: utf-8 -*-
"""휴대폰 인증번호 중계 - PC 쪽 (설계 docs/superpowers/specs/2026-10-12-phone-otp-relay-design.md 5·13절).

재생기(web_replay.Replayer.otp)에 넘기는 중계 둘:
  PhoneRelay  서버(RTDB apps/otp)로 - 요청 열기 → 휴대폰 앱이 쓴 번호 기다리기 → 지우기. 옵저버(web_runner)·ACTOR 미리보기
  ManualOtp   사람이 미리보기 창의 칸에 번호를 칠 때까지 기다린다 (인증 휴대폰을 정하지 않은 ACTOR 미리보기)
서버에는 이 PC 의 에이전트 계정으로 로그인한다 (secret.load_config - 같은 윈도우 사용자라 풀린다, 사용자 2026-10-13).
비밀번호·토큰·인증번호는 로그에 싣지 않는다.
"""
import os
import re
import secrets
import sys
import time

OPEN_MS = 120000          # 요청이 열려 있는 시간 (서버 규칙과 같은 값)
POLL = 2.0                # 번호를 보러 가는 간격 (초)
_AGENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "firebase", "agent")


def digits(s):
    return re.sub(r"\D", "", str(s or ""))


def sender_number(s):
    """발신번호를 휴대폰 앱·단축어와 같은 꼴로: 숫자만, '+82' 로 시작하면 국내식 '0…' (+82 90-258-0002 → 0902580002).
    휴대폰은 받은 문자의 발신번호를 이렇게 바꿔 요청의 senders 와 견준다 - 다르면 번호를 보내지 않는다 (2026-10-13 실서버 시험 준비)."""
    d = digits(s)
    if str(s or "").strip().startswith("+82") and len(d) > 2:
        rest = d[2:]
        return rest if rest.startswith("0") else "0" + rest     # +82 090-… 도 090… (단축어 ^\+820? → 0, 안드로이드와 같다)
    return d


def _agent_modules():
    """에이전트의 fb(서버 REST)·secret(잠근 설정). exe 에는 빌드가 넣어 두고 (build_release AGENT_MODULES), 소스로 돌 때는 firebase/agent 에서."""
    try:
        import fb
        import secret
    except ImportError:
        import rpa_status
        for d in (_AGENT_DIR, os.path.join(rpa_status.program_dir(), "firebase", "agent")):
            if d not in sys.path:
                sys.path.insert(0, d)
        import fb
        import secret
    return fb, secret


def check_line():
    """--check 한 줄 (빌드·샌드박스가 본다): exe 안에서 서버 모듈을 불러오나."""
    try:
        fb, secret = _agent_modules()
        return f"인증번호 중계: 준비됨 (fb {'있음' if hasattr(fb, 'Client') else '없음'})"
    except Exception as e:
        return f"문제: 인증번호 중계를 불러오지 못했습니다 ({type(e).__name__}: {e})"


class PhoneRelay:
    """한 휴대폰(phone_id)으로 한 사이트의 인증번호를 받는다. client = 에이전트 계정 fb.Client."""

    def __init__(self, client, cid, pc_id, phone_id, senders, site):
        self.client, self.cid, self.pc_id, self.phone_id, self.site = client, cid, pc_id, phone_id, site
        self.senders = {sender_number(x): True for x in senders if sender_number(x)}
        self.req_path = f"apps/otp/requests/{cid}/{phone_id}/current"
        self.code_path = f"apps/otp/codes/{cid}/{phone_id}/current"

    def open(self):
        """요청을 연다 (그 휴대폰이 2분 동안 STAND BY). 지난번에 남은 번호는 먼저 지운다. req_id 를 돌려준다."""
        self._quiet_delete(self.code_path)
        req_id = "req_" + secrets.token_hex(8)
        self.client.put(self.req_path, {"req_id": req_id, "site": self.site, "senders": self.senders,
                                        "pcId": self.pc_id, "created_at": {".sv": "timestamp"}})
        return req_id

    def wait(self, req_id, seconds, tick, field=None):
        """req_id 가 맞는 번호가 오면 그 번호, seconds 안에 안 오면 None. tick(초) 로 쉰다 (재생기의 [■ 중단] 을 본다)."""
        end = time.time() + seconds
        while True:
            got = self.client.get(self.code_path)
            if isinstance(got, dict) and got.get("req_id") == req_id and re.fullmatch(r"\d{4,8}", str(got.get("code") or "")):
                return str(got["code"])
            if time.time() >= end:
                return None
            tick(min(POLL, max(0.1, end - time.time())))

    def close(self, req_id):
        """번호와 요청을 지운다 (성공·실패·중단 모두)."""
        self._quiet_delete(self.code_path)
        self._quiet_delete(self.req_path)

    def _quiet_delete(self, path):
        try:
            self.client.delete(path)
        except Exception:
            pass                # 이미 없거나 (남의 요청이 2분 안이면 규칙이 막는다) - 다음 열기에서 다시


class ManualOtp:
    """사람이 칸에 번호를 칠 때까지 (숫자 4~8자리가 1초 그대로면) 기다린다 - 휴대폰 없이 하는 ACTOR 미리보기.
    on_wait: 기다리기 시작할 때 (화면에 '칸에 넣어 주십시오' 를 띄운다)."""

    def __init__(self, on_wait=None):
        self.on_wait = on_wait

    def open(self):
        return "manual"

    def wait(self, req_id, seconds, tick, field=None):
        if self.on_wait:
            self.on_wait()
        end, last, since = time.time() + seconds, "", 0.0
        while time.time() < end:
            try:
                v = (field.input_value() or "").strip() if field is not None else ""
            except Exception:
                v = ""
            if re.fullmatch(r"\d{4,8}", v):
                if v != last:
                    last, since = v, time.time()
                elif time.time() - since >= 1.0:
                    return v
            else:
                last = ""
            tick(0.3)
        return None

    def close(self, req_id):
        pass


def phone_list():
    """이 업체의 휴대폰 [(phoneId, 이름)] - 관리 화면 '휴대폰 추가' 로 등록한 것 (ACTOR 저장 화면이 고르게). 못 읽으면 예외."""
    fb, secret = _agent_modules()
    cfg = secret.load_config()
    got = fb.Client(cfg).get(f"meta/companies/{cfg['cid']}/phones") or {}
    return sorted(((k, (v or {}).get("label") or k) for k, v in got.items()), key=lambda x: x[1])


def agent_relay(phone_id, senders, site):
    """이 PC 의 에이전트 계정으로 PhoneRelay. 설정이 없거나 깨졌으면 사람 말로 RuntimeError."""
    fb, secret = _agent_modules()
    try:
        cfg = secret.load_config()
    except (OSError, ValueError) as e:
        raise RuntimeError(f"에이전트 설정을 읽지 못해 인증번호를 받을 수 없습니다 ({type(e).__name__}) - '오토파일럿 설정' 을 확인하세요") from None
    return PhoneRelay(fb.Client(cfg), cfg["cid"], cfg["pc_id"], phone_id, senders, site)
