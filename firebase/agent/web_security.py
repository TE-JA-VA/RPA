# -*- coding: utf-8 -*-
"""사내 서버 웹의 '보안' 설정 - <자료 폴더>/security.json (설계 2026-11-24 6.6, 계획 ③ Task 3·4).

    {"version": 1, "totp_scope": "off" | "admin" | "all", "show_own_history": bool}

totp_scope = 2단계 인증을 꼭 써야 하는 계정 - 끔 / 관리자 계정만 / 모든 계정. 기본은 '관리자 계정만' (설계 6.6, Claude 판단).
show_own_history = 유저에게 자기 로그인 이력 보이기 (관리자는 늘 본다). 기본 참.
파일이 없거나 깨졌으면 기본값으로 본다 (깨진 파일은 .broken 으로 치운다). 쓸 때는 임시 파일 → os.replace.
사내 서버(local_web.Web 에 registry 가 있을 때)만 쓴다 - 단독은 이 파일을 만들지 않는다. 표준 라이브러리만 쓴다.
"""
import json
import os
import tempfile
import threading
import time

SECURITY_NAME = "security.json"
SECURITY_VERSION = 1
SCOPES = ("off", "admin", "all")
DEFAULT = {"totp_scope": "admin", "show_own_history": True}


def needs_mfa(scope, role):
    """그 범위에서 그 권한의 계정이 2단계를 꼭 써야 하나 - all 은 모두, admin 은 관리자만, off 는 아무도."""
    if scope == "all":
        return True
    if scope == "admin":
        return role == "admin"
    return False


class Security:
    """security.json 읽기·쓰기. get() 은 부를 때마다 파일을 읽는다 (범위를 바꾼 순간 다음 요청부터 따른다 - 작은 파일이다)."""

    def __init__(self, path):
        self.path = os.path.abspath(path)
        self._lock = threading.Lock()

    def get(self):
        """{"totp_scope", "show_own_history"} 사본. 파일이 없으면 DEFAULT, 깨졌으면 .broken 으로 치우고 DEFAULT.
        잠깐 못 읽으면 (권한·잠김) DEFAULT - 기본값이 더 막는 쪽('관리자만')이다."""
        with self._lock:
            return dict(self._read())

    def _read(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
        except FileNotFoundError:
            return DEFAULT
        except (ValueError, UnicodeDecodeError, RecursionError):
            raw = None
        except OSError:
            return DEFAULT
        if not isinstance(raw, dict):
            try:
                os.replace(self.path, self.path + ".broken")
            except OSError:
                pass
            return DEFAULT
        scope, show = raw.get("totp_scope"), raw.get("show_own_history")
        return {"totp_scope": scope if scope in SCOPES else DEFAULT["totp_scope"],
                "show_own_history": show if isinstance(show, bool) else DEFAULT["show_own_history"]}

    def set(self, totp_scope=None, show_own_history=None):
        """바꿀 칸만 (None 은 그대로) → 바뀐 설정 사본. 틀린 값은 ValueError (사람 말)."""
        if totp_scope is not None and totp_scope not in SCOPES:
            raise ValueError("2단계 인증 범위는 끔(off)·관리자만(admin)·모든 계정(all) 가운데 하나여야 합니다.")
        if show_own_history is not None and not isinstance(show_own_history, bool):
            raise ValueError("유저 이력 보이기는 참·거짓 가운데 하나여야 합니다.")
        with self._lock:
            value = dict(self._read())
            if totp_scope is not None:
                value["totp_scope"] = totp_scope
            if show_own_history is not None:
                value["show_own_history"] = show_own_history
            self._save(value)
            return dict(value)

    def _save(self, value):
        folder = os.path.dirname(self.path)
        os.makedirs(folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=os.path.basename(self.path) + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"version": SECURITY_VERSION, **value}, f, ensure_ascii=False, indent=1)
                f.flush()
                os.fsync(f.fileno())
            for attempt in range(6):                  # 읽는 쪽·바이러스 검사가 잠깐 잡고 있으면 바꿔치기가 거절된다
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
