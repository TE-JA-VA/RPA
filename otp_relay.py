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
DENIED = "인증번호 요청이 거절되었습니다. 허용 발신번호가 아니거나 업체 사용이 정지되었을 수 있습니다."
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
        # '설치본' 은 fb 가 프로그램 폴더를 제대로 알아보는가 - 틀리면 시험용 환경 변수 무시(보안 감사 C2)가 exe 에서 안 걸린다 (샌드박스가 본다)
        return f"인증번호 중계: 준비됨 (fb {'있음' if hasattr(fb, 'Client') else '없음'}, 설치본 {'예' if fb._shipped() else '아니오'})"
    except Exception as e:
        return f"문제: 인증번호 중계를 불러오지 못했습니다. ({type(e).__name__}: {e})"


CLOSE_TRIES, CLOSE_RETRY_SEC = 3, 1.0     # 끝날 때 번호·요청 지우기: 몇 번까지, 사이 쉬는 초 (PhoneRelay.close)
CLOSE_BUDGET_SEC = 10.0                   # 한 바퀴가 이보다 오래 걸렸으면 다시 하지 않는다


class PhoneRelay:
    """한 휴대폰(phone_id)으로 한 사이트의 인증번호를 받는다. client = 에이전트 계정 fb.Client."""

    def __init__(self, client, cid, pc_id, phone_id, senders, site):
        self.client, self.cid, self.pc_id, self.phone_id, self.site = client, cid, pc_id, phone_id, site
        self.senders = {sender_number(x): True for x in senders if sender_number(x)}
        self.req_path = f"apps/otp/requests/{cid}/{phone_id}/current"
        self.code_path = f"apps/otp/codes/{cid}/{phone_id}/current"

    def open(self, tick=time.sleep):
        """요청을 연다 (그 휴대폰이 2분 동안 STAND BY). req_id 를 돌려준다.
        다른 PC 가 요청을 쥐고 있으면 (규칙이 put 을 막는다) 빌 때까지 - 길어야 만료 2분 - 기다렸다 차지한다 (설계 2절 '뒤에 온 쪽이 기다린다').
        지난번에 남은 번호는 요청을 차지한 뒤에만 지운다 - 먼저 지우면 남의 PC 가 받아 둔 번호가 사라진다 (BugBuster M7)."""
        req_id = "req_" + secrets.token_hex(8)
        end = time.time() + OPEN_MS / 1000 + 10
        retried = False                       # 자리가 비었는데 거절된 뒤 한 번 더 해 봤나
        while True:
            try:
                self.client.put(self.req_path, {"req_id": req_id, "site": self.site, "senders": self.senders,
                                                "pcId": self.pc_id, "created_at": {".sv": "timestamp"}})
                break
            except Exception as e:
                if getattr(e, "status", None) not in (401, 403) or time.time() >= end:
                    raise
                if self._free():              # 남의 요청이 없는데 거절 - 막 비었을 수 있어 한 번만 다시. 또 거절이면 규칙 거절
                    if retried:               # (허용 발신번호 밖·업체 정지) - 남의 요청을 기다리듯 2분을 쓰지 않는다 (검토 2026-11-16)
                        raise RuntimeError(DENIED) from e
                    retried = True
                    tick(POLL)                # 막 비운 자리가 서버 규칙에 반영될 틈을 두고 다시 (검토 2026-11-17)
                    continue
            retried = False
            while time.time() < end:          # 남의 요청 - 비거나 만료될 때까지 읽어 보며 기다린다 (거부된 put 을 되풀이하면 매번 토큰 갱신)
                tick(POLL)
                if self._free():
                    break
        self._quiet_delete(self.code_path)
        return req_id

    def _free(self):
        """요청 자리가 비었나 - 없음·내 요청·만료. 못 읽으면 False (남의 요청이 있다고 보고 기다린다)."""
        try:
            cur = self.client.get(self.req_path)
        except Exception:
            return False
        now_ms = getattr(self.client, "server_now", time.time)() * 1000
        return not isinstance(cur, dict) or cur.get("pcId") == self.pc_id or (cur.get("created_at") or 0) + OPEN_MS < now_ms

    def wait(self, req_id, seconds, tick, field=None):
        """req_id 가 맞는 번호가 오면 그 번호, seconds 안에 안 오면 None. tick(초) 로 쉰다 (재생기의 [■ 중단] 을 본다)."""
        end = time.time() + seconds
        while True:
            try:
                got = self.client.get(self.code_path)
            except Exception as e:            # (BugBuster M8) 망 오류·서버 5xx 는 다음 폴링에 다시, 권한 거부만 새 요청으로
                st = getattr(e, "status", None)
                if st in (401, 403):
                    return None               # 요청이 남에게 넘어가 읽기 거부 → 재생기가 OtpRetry 로 새 요청
                if not (isinstance(e, OSError) or (isinstance(st, int) and st >= 500)):
                    raise
                got = None
            if isinstance(got, dict) and got.get("req_id") == req_id and re.fullmatch(r"\d{4,8}", str(got.get("code") or "")):
                return str(got["code"])
            if time.time() >= end:
                return None
            tick(min(POLL, max(0.1, end - time.time())))

    def close(self, req_id, tick=time.sleep, clock=time.monotonic):
        """번호와 요청을 지운다 (성공·실패·중단 모두). 망이 잠깐 끊겨 못 지우면 CLOSE_TRIES 번까지 다시 지운다 - 그 전에는 한 번
        실패하면 같은 휴대폰의 다음 요청 때까지 서버에 남았다 (보안 감사 2026-11-13 C17, 고객사 보안 검토 2026-11-19).
        끝내 못 지우면 RuntimeError (부른 쪽이 기록에 남긴다 - 다음 요청을 열 때 지워진다). 규칙이 막은 것(401·403 - 남의 요청이
        2분 안)은 우리 것이 아니라 다시 하지 않는다."""
        left, err, started = [self.code_path, self.req_path], None, clock()
        for i in range(CLOSE_TRIES):
            still = []
            for path in left:
                try:
                    self.client.delete(path)
                except Exception as e:
                    if getattr(e, "status", None) not in (401, 403):
                        still.append(path)
                        err = e
            left = still
            if not left:
                return
            if i < CLOSE_TRIES - 1:
                if clock() - started > CLOSE_BUDGET_SEC:     # 망이 먹통 (요청마다 30초씩 걸린다) - 실행 끝을 몇 분씩 붙잡지 않는다
                    break
                tick(CLOSE_RETRY_SEC)
        raise RuntimeError(f"인증번호 중계 항목을 지우지 못했습니다. ({type(err).__name__}) 다음 인증번호 요청 때 지워집니다.")

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

    def open(self, tick=None):
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


MANUAL_SEC = 300                          # 스탠드얼론: 휴대폰이 없거나 답이 없으면 사람이 Edge 칸에 넣기를 기다리는 시간 (설계 7절)
GIVE_UP = "인증번호를 받지 못함"            # 그때 그 사이트의 실패 사유 (재생기 결과·실행 기록)
TYPED_STABLE_SEC = 1.0                    # 칸의 숫자가 이만큼 그대로면 사람이 다 친 것으로 본다 (ManualOtp 와 같다)


class _Typed:
    """칸에 사람이 친 번호 (숫자 4~8자리가 1초 그대로) 를 본다 - ManualOtp 와 같은 판단."""

    def __init__(self, field):
        self.field, self.last, self.since = field, "", 0.0

    def code(self):
        try:
            v = (self.field.input_value() or "").strip() if self.field is not None else ""
        except Exception:
            v = ""
        if not re.fullmatch(r"\d{4,8}", v):
            self.last = ""
            return None
        if v != self.last:
            self.last, self.since = v, time.time()
            return None
        return v if time.time() - self.since >= TYPED_STABLE_SEC else None


class FallbackOtp:
    """스탠드얼론 재생기의 인증번호 (계획 ④ Task 4, 설계 7절 '안 될 때'): 휴대폰이 있으면 재생기의 시간(2분) 동안 휴대폰 번호를 기다리되
    그동안에도 Edge 칸에 사람이 넣은 번호를 받는다 (먼저 온 것). 그 뒤 on_manual() 을 한 번 부르고 manual_sec(5분) 동안 칸만 본다.
    끝내 없으면 None → 재생기는 다시 하지 않고(once - 재발송 없음) 그 단계를 give_up 사유로 끝낸다 (그 사이트만 실패).
    휴대폰 요청을 못 열면(짝짓지 않음·발신번호 거절·서버 없음) 까닭을 log 로 한 줄 남기고 이번 실행은 사람 입력만. 예외를 올리지 않는다.
    인증번호 숫자는 log 에 싣지 않는다."""
    once = True
    give_up = GIVE_UP

    def __init__(self, phone=None, manual_sec=MANUAL_SEC, on_manual=None, log=None):
        self.phone, self.manual_sec, self.on_manual, self.log = phone, manual_sec, on_manual, log
        self._req = None                  # 휴대폰 요청 (열었으면)

    def _say(self, text):
        if self.log:
            try:
                self.log(text)
            except Exception:
                pass

    def open(self, tick=None):
        self._req = None
        if self.phone is not None:
            try:
                self._req = self.phone.open(tick) if tick is not None else self.phone.open()
            except Exception as e:          # RuntimeError(DENIED)·OSError·fb.HttpError·AuthError - 사람 입력만
                why = str(e) if isinstance(e, RuntimeError) else f"{type(e).__name__}{' ' + str(e.status) if getattr(e, 'status', None) else ''}"
                self._say(f"휴대폰으로 인증번호를 받을 수 없어 직접 입력을 기다립니다. ({why})")
        return self._req or "manual"

    def wait(self, req_id, seconds, tick, field=None):
        typed = _Typed(field)
        if self.phone is not None and self._req is not None:
            end = time.time() + seconds
            while time.time() < end:
                try:
                    code = self.phone.wait(self._req, min(1.0, max(0.1, end - time.time())), tick, field)
                except Exception as e:      # 휴대폰 쪽이 끊겼다 - 사람 입력으로
                    self._say(f"휴대폰으로 인증번호를 받을 수 없어 직접 입력을 기다립니다. ({type(e).__name__})")
                    break
                if code:
                    return code
                got = typed.code()
                if got:
                    return got
        if self.on_manual:
            self.on_manual()
        end = time.time() + self.manual_sec
        while time.time() < end:
            got = typed.code()
            if got:
                return got
            tick(0.3)
        return None

    def close(self, req_id):
        if self.phone is not None and self._req is not None:
            req, self._req = self._req, None
            self.phone.close(req)


def standalone_relay(phone_id, senders, site, on_manual=None, log=None):
    """스탠드얼론 ACTOR 실행·옵저버 미리보기의 인증번호: 인증 휴대폰과 발신번호를 정했으면 휴대폰 중계를 시도하고 (설정을 못 읽으면
    사람 입력만), 아니면 바로 사람 입력만 → FallbackOtp."""
    phone = None
    if phone_id and senders:
        try:
            phone = agent_relay(phone_id, senders, site)
        except RuntimeError as e:
            if log:
                log(f"휴대폰으로 인증번호를 받을 수 없어 직접 입력을 기다립니다. ({e})")
    return FallbackOtp(phone=phone, on_manual=on_manual, log=log)


def phone_list():
    """이 업체의 휴대폰 [(phoneId, 이름)] - 관리 화면 '휴대폰 추가' 로 등록한 것 (ACTOR 저장 화면이 고르게). 못 읽으면 예외."""
    cfg = relay_config()
    got = _client(cfg).get(f"meta/companies/{cfg['cid']}/phones") or {}
    return sorted(((k, (v or {}).get("label") or k) for k, v in got.items()), key=lambda x: x[1])


def _standalone():
    """스탠드얼론 버전인가 (edition 모듈이 없는 옛 exe 는 일반 버전)."""
    try:
        import edition
        return edition.is_standalone()
    except ImportError:
        return False


def relay_config():
    """인증번호 중계가 서버에 붙을 설정. 일반 버전은 이 PC 의 에이전트 계정, 스탠드얼론은 로컬 서버의 중계 열쇠
    (에이전트 열쇠보다 할 수 있는 일이 적다 - 인증번호 자리만). 못 읽으면 예외 (OSError·ValueError)."""
    _, secret = _agent_modules()
    return secret.load_config(role="relay") if _standalone() else secret.load_config()


def _client(cfg):
    """설정에 맞는 서버 연결 - 스탠드얼론 설정이면 로컬 서버(local_store), 아니면 Firebase(fb)."""
    fb, _ = _agent_modules()
    if cfg.get("standalone"):
        import local_store
        return local_store.Client(cfg)
    return fb.Client(cfg)


def agent_relay(phone_id, senders, site):
    """이 PC 의 에이전트 계정(스탠드얼론은 로컬 서버 열쇠)으로 PhoneRelay. 설정이 없거나 깨졌으면 사람 말로 RuntimeError."""
    try:
        cfg = relay_config()
    except (OSError, ValueError) as e:
        raise RuntimeError(f"에이전트 설정을 읽지 못해 인증번호를 수신할 수 없습니다. ({type(e).__name__}) '오토파일럿 설정'을 확인하여 주십시오.") from None
    return PhoneRelay(_client(cfg), cfg["cid"], cfg["pc_id"], phone_id, senders, site)
