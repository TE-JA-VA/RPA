# -*- coding: utf-8 -*-
"""로컬 서버·사내 서버와 그 클라이언트가 같이 쓰는 요청·응답·구독 서명 (설계 2026-11-23-standalone 6.2, 2026-11-24 lan 6.4).

표준 라이브러리(hashlib·hmac)만 쓴다. 서버(local_server)는 이 모듈만 불러오고, PC 쪽 클라이언트 local_store 는 같은 이름을
그대로 내보낸다 - 서버 설치 파일에 PC 클라이언트(local_store·fb·server_info)가 딸려 들어가지 않게 (계획 2026-11-25-lan-4-linux
Task 7, 설계 8절 바깥 연결 0). 열쇠는 주고받지 않는다 - 요청마다 열쇠로 만든 HMAC 만 싣는다.
"""
import hashlib
import hmac

ROLES = ("agent", "relay")
H_ROLE, H_TIME, H_NONCE, H_SIGN = "X-AP-Role", "X-AP-Time", "X-AP-Nonce", "X-AP-Sign"
H_PC = "X-AP-PC"                         # 사내 서버(ap2): 서명한 PC 번호 - 서버가 이 번호로 등록부에서 열쇠를 찾는다


def _mac(key, parts):
    return hmac.new(key.encode("utf-8"), "\n".join(parts).encode("utf-8"), hashlib.sha256).hexdigest()


def _digest(body):
    return hashlib.sha256(body or b"").hexdigest()


def request_mac(key, role, method, target, ts, nonce, body, digest=None):
    """요청 서명. target 은 보낸 그대로의 경로+질의, ts 는 보낸 시각(ms 글자), nonce 는 요청마다 새 값.
    digest: 본문의 sha256 글을 이미 알면 (서버가 읽으며 계산) body 대신 준다."""
    return _mac(key, ["ap1", "req", role, method, target, str(ts), nonce, digest or _digest(body)])


def request_mac2(key, pc_id, role, method, target, ts, nonce, body, digest=None):
    """사내 서버(ap2) 요청 서명 - ap1 에 PC 번호가 더 묶인다 (열쇠가 PC 마다 다르다). 응답·이벤트 서명은 ap1 그대로."""
    return _mac(key, ["ap2", "req", pc_id, role, method, target, str(ts), nonce, digest or _digest(body)])


def response_mac(key, nonce, status, body):
    """응답 서명 - 그 요청의 nonce 에 묶인다 (다른 요청의 응답을 돌려쓰지 못한다)."""
    return _mac(key, ["ap1", "res", nonce, str(status), _digest(body)])


def event_mac(key, nonce, seq, event, raw):
    """구독 이벤트 서명 - 그 구독의 nonce 와 차례(seq, 1부터)에 묶인다."""
    return _mac(key, ["ap1", "sse", nonce, str(seq), event, raw])
