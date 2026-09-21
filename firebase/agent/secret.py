"""에이전트 설정과 비밀번호 보관.

비밀번호는 윈도우 DPAPI(현재 사용자 범위)로 감싸 설정 파일에 넣는다.
파일을 그대로 복사해 가도 다른 사용자 계정에서는 풀 수 없다.
ERPia 자격증명(ERPIA_AI.txt)과 같은 성격이므로 화면·기록·응답에 절대 싣지 않는다.
"""
import base64
import ctypes
import json
import os
from ctypes import wintypes

# RPA_AGENT_CONFIG 는 시험용 - 통합 시험이 실제 설정을 덮어쓰지 않게 다른 파일을 가리킨다
CONFIG_PATH = os.environ.get("RPA_AGENT_CONFIG") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "agent_config.json")
REQUIRED = ("project_id", "api_key", "database_url", "cid", "pc_id", "email")
# 공개 값 (web/firebase-config.js 와 같다). 첫 실행 때 이메일·비밀번호만 물으면 되게 여기 둔다
PUBLIC = {
    "project_id": "rpa-test-f02e0",
    "api_key": "AIzaSyCFbHQjWVxzi38IAYIhQX9wyiGIs1VcZuA",
    "database_url": "https://rpa-test-f02e0-default-rtdb.asia-southeast1.firebasedatabase.app",
}


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _Blob:
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _take(blob: _Blob) -> bytes:
    out = ctypes.string_at(blob.pbData, blob.cbData)
    ctypes.windll.kernel32.LocalFree(blob.pbData)
    return out


def protect(text: str) -> str:
    """평문을 DPAPI 로 감싸 base64 문자열로 돌려준다."""
    out = _Blob()
    src = _blob(text.encode("utf-8"))
    if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(src), "rpa-agent", None, None, None, 0, ctypes.byref(out)):
        raise OSError("비밀번호를 감싸지 못했습니다 (CryptProtectData)")
    return base64.b64encode(_take(out)).decode("ascii")


def unprotect(blob: str) -> str:
    """감싼 값을 평문으로 되돌린다."""
    out = _Blob()
    src = _blob(base64.b64decode(blob))
    if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("비밀번호를 풀지 못했습니다. 이 PC·이 사용자 계정에서 만든 설정인지 확인하세요.")
    return _take(out).decode("utf-8")


def write_config(path, values, password):
    """설정을 쓴다. password 는 감싸서 password_dpapi 로만 들어간다."""
    data = {k: values[k] for k in REQUIRED}
    data["password_dpapi"] = protect(password)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_config(path=None):
    """설정을 읽고 비밀번호를 푼 dict 를 돌려준다."""
    path = path or CONFIG_PATH
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    missing = [k for k in REQUIRED if not data.get(k)]
    if missing:
        raise ValueError(f"설정에 빠진 항목: {', '.join(missing)}  ({path})")
    if not data.get("password_dpapi"):
        raise ValueError(f"설정에 password_dpapi 가 없습니다 ({path})")
    out = {k: data[k] for k in REQUIRED}
    out["password"] = unprotect(data["password_dpapi"])
    return out
