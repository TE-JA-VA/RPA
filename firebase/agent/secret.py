"""에이전트 설정과 비밀번호 보관.

비밀번호는 윈도우 DPAPI(현재 사용자 범위)로 감싸 설정 파일에 넣는다.
파일을 그대로 복사해 가도 다른 사용자 계정에서는 풀 수 없다.
ERPia 자격증명(ERPIA_AI.txt)과 같은 성격이므로 화면·기록·응답에 절대 싣지 않는다.
"""
import base64
import ctypes
import json
import os
import sys
from ctypes import wintypes

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))     # 저장소·배포 폴더 뿌리 (rpa_status·server_info 자리)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import server_info  # noqa: E402  서버 주소 한 곳 (2026-10-21)


def _default_config_path():
    """새 구조(설치 마법사가 %ProgramData%\\AFTER MARKET\\RPA\\config 를 만든 PC)면 거기, 아니면 이 파일 옆 (옛 자리).
    rpa_status 는 두 단계 위(저장소·배포 폴더 뿌리)에 있다 - agent.py 의 RPA_DIR 과 같은 자리. 단위 시험처럼
    agent.py 보다 먼저 불려도 찾게 여기서도 sys.path 에 넣는다."""
    root = os.path.abspath(os.path.join(_HERE, "..", ".."))
    if root not in sys.path:
        sys.path.insert(0, root)
    import rpa_status
    return os.path.join(rpa_status.config_dir() if rpa_status.new_layout() else _HERE, "agent_config.json")


def _dev_env(name):
    """시험용 RPA_* 환경 변수 - 설치본은 무시한다 (rpa_status.dev_env, 보안 진단 2026-11-23 E-1)."""
    root = os.path.abspath(os.path.join(_HERE, "..", ".."))
    if root not in sys.path:
        sys.path.insert(0, root)
    import rpa_status
    return rpa_status.dev_env(name)


# RPA_AGENT_CONFIG 는 시험용 - 통합 시험이 실제 설정을 덮어쓰지 않게 다른 파일을 가리킨다 (설치본은 무시)
CONFIG_PATH = _dev_env("RPA_AGENT_CONFIG") or _default_config_path()
REQUIRED = ("project_id", "api_key", "database_url", "cid", "pc_id", "email")
# 공개 값 (server_info - web/firebase-config.js 와 같다). 첫 실행 때 이메일·비밀번호만 물으면 되게 여기 둔다
PUBLIC = {"project_id": server_info.PROJECT_ID, "api_key": server_info.API_KEY, "database_url": server_info.DATABASE_URL}


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
    # 누가 만들었나 - DPAPI 는 이 윈도우 계정에서만 풀리니, 못 풀 때 안내에 쓴다 (선택 항목, 옛 설정에는 없다)
    data["windows_user"] = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}"
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _standalone_config(role):
    """스탠드얼론: 라이선스(업체·PC)와 로컬 서버 열쇠로 만든 설정 - 에이전트 계정·비밀번호가 없다 (설계 2026-11-23-standalone 6.2).
    role 'agent' = 에이전트 열쇠, 'relay' = 인증번호 중계 열쇠 (ACTOR 실행·옵저버). 라이선스가 틀리면 LicenseError(ValueError),
    열쇠 파일이 아직 없으면 FileNotFoundError (로컬 서버가 처음 켜질 때 만든다). 열쇠는 로그에 싣지 않는다."""
    import license_check
    import local_store
    mode, lic = license_check.load_any()
    if mode == license_check.MODE_LAN:
        # 사내 서버 (사내 서버 ⑤): 연결 파일의 주소·인증 기관·PC 번호·열쇠. 정책은 서버 라이선스 body (LicensePolicy 가 그대로 쓴다)
        key = lic["relay_key"] if role == "relay" else lic["agent_key"]
        return {"standalone": True, "lan": True, "server_url": lic["server_url"], "ca_pem": lic["ca_pem"], "key": key,
                "role": "relay" if role == "relay" else "agent", "cid": lic["license"]["cid"], "pc_id": lic["pc_id"],
                "license": dict(lic["license"], pc_id=lic["pc_id"])}
    name = "relay.key" if role == "relay" else "agent.key"
    with open(os.path.join(local_store.keys_dir(), name), encoding="ascii") as f:
        key = f.read().strip()
    if len(key) < 32:
        raise ValueError(f"로컬 서버 열쇠 파일이 올바르지 않습니다. ({name})")
    try:
        port = int(_dev_env("RPA_LOCAL_PORT") or local_store.PORT)
    except ValueError:
        port = local_store.PORT
    return {"standalone": True, "server_url": f"http://127.0.0.1:{port}", "key": key, "role": "relay" if role == "relay" else "agent",
            "cid": lic["cid"], "pc_id": lic["pc_id"], "license": lic}


def load_config(path=None, role="agent"):
    """설정을 읽고 비밀번호를 푼 dict 를 돌려준다. 스탠드얼론 버전이면 (path 를 따로 주지 않았을 때) 로컬 서버 설정 - role 은 그때만 쓴다."""
    if path is None:
        import edition
        if edition.is_standalone():
            return _standalone_config(role)
    path = path or CONFIG_PATH
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    missing = [k for k in REQUIRED if not data.get(k)]
    if missing:
        raise ValueError(f"설정에 빠진 항목: {', '.join(missing)}  ({path})")
    if not data.get("password_dpapi"):
        raise ValueError(f"설정에 password_dpapi 가 없습니다 ({path})")
    out = {k: data[k] for k in REQUIRED}
    if data.get("windows_user"):
        out["windows_user"] = data["windows_user"]
    try:
        out["password"] = unprotect(data["password_dpapi"])
    except OSError:
        raise OSError(f"비밀번호를 풀지 못했습니다. 이 설정은 {data.get('windows_user') or '다른 윈도우'} 계정으로 만들었습니다. "
                      "같은 윈도우 계정(UAC 에 넣는 계정)으로 띄우거나, agent_config.json 을 지우고 다시 띄우면 "
                      "에이전트 계정을 다시 묻습니다") from None
    return out
