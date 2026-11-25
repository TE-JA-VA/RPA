# -*- coding: utf-8 -*-
"""사내 서버(리눅스)의 기록 파일 - /var/log/autopilot/server.log·audit.log (설계 6.2, 사내 서버 ④ Task 1).
RotatingFile: 한 파일이 max_bytes(10MB)를 넘으려 하면 path.1 … path.(keep-1) 로 밀고 가장 오래된 것을 지운다 (다섯 개).
configure(server_path, audit_path) 로 자리를 정하면 local_server.log 는 server.log 로, local_server.audit 은 audit.log 로 간다.
정하지 않으면(단독 - 윈도우 한 PC) 아무것도 바뀌지 않는다: local_server.log 가 지금처럼 자료 폴더의 기록 파일에 쓴다.
기록에 열쇠·비밀번호·세션 토큰·인증번호·2단계 비밀 값을 싣지 않는 것은 부르는 쪽의 몫이다. 표준 라이브러리만 쓴다.
"""
import os
import threading
import time

MAX_BYTES = 10 * 1024 * 1024
KEEP = 5
SERVER_LOG = "server.log"
AUDIT_LOG = "audit.log"


class RotatingFile:
    """돌려 쓰는 기록 파일 하나. write 는 스레드 안전하고 예외를 내지 않는다 (기록 때문에 서버가 멈추면 안 된다).
    새로 만드는 파일은 posix 에서 0600 (기록에 사람 아이디·주소가 든다). 쓸 때마다 열고 닫는다 - 다른 프로세스(관리 명령)가
    같은 파일에 덧붙여도 줄이 섞이지 않고, 밀어낸 뒤에는 새 파일에 쓴다."""

    def __init__(self, path, max_bytes=MAX_BYTES, keep=KEEP):
        self.path = os.path.abspath(path)
        self.max_bytes = max(1, int(max_bytes))
        self.keep = max(1, int(keep))
        self._lock = threading.Lock()

    def _rotate(self):
        """path → path.1 → … → path.(keep-1), 가장 오래된 것은 지운다. keep 이 1 이면 지금 파일을 지운다."""
        last = self.keep - 1
        if last < 1:
            os.remove(self.path)
            return
        try:
            os.remove(f"{self.path}.{last}")
        except FileNotFoundError:
            pass
        for i in range(last - 1, 0, -1):
            try:
                os.replace(f"{self.path}.{i}", f"{self.path}.{i + 1}")
            except FileNotFoundError:
                pass
        os.replace(self.path, f"{self.path}.1")

    def write(self, line):
        """줄 하나 (앞에 'YYYY-MM-DD HH:MM:SS  '). 줄바꿈은 붙여 준다."""
        data = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {line}\n".encode("utf-8")
        with self._lock:
            try:
                try:
                    size = os.path.getsize(self.path)
                except OSError:
                    size = 0
                if size and size + len(data) > self.max_bytes:
                    self._rotate()
                fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o600)
                try:
                    os.write(fd, data)
                finally:
                    os.close(fd)
            except OSError:
                pass


_server = None
_audit = None


def configure(server_path, audit_path):
    """기록 자리를 정한다 (사내 서버 입구 server_main 이 켤 때 한 번). 둘 다 None 이면 처음 상태 (단독 그대로).
    audit_path 만 None 이면 감사 줄도 server.log 로 간다."""
    global _server, _audit
    _server = RotatingFile(server_path) if server_path else None
    _audit = RotatingFile(audit_path) if audit_path else None


def active():
    """server.log 자리가 정해져 있는가."""
    return _server is not None


def write_server(text):
    """server.log 에 한 줄. 정해져 있지 않으면 False (부르는 쪽이 옛 길로)."""
    f = _server
    if f is None:
        return False
    f.write(text)
    return True


def write_audit(text):
    """audit.log 에 한 줄 (계정·보안 설정·PC·명령 - 누가 무엇을 바꾸었나). 자리가 없으면 server.log, 그것도 없으면 False."""
    f = _audit or _server
    if f is None:
        return False
    f.write(text)
    return True
