# -*- coding: utf-8 -*-
"""버전 종류 - 일반(cloud, Firebase)인가 스탠드얼론(standalone, 그 PC 의 로컬 서버)인가 (설계 2026-11-23-standalone 6.1).

값은 빌드 때 정해진다: 스탠드얼론 설치 파일이 프로그램 폴더에 edition.json = {"edition": "standalone"} 을 싣는다.
그 파일이 없으면 일반 버전. 화면에서 바꾸는 곳은 없다 (프로그램 폴더는 관리자만 쓴다).
시험은 RPA_EDITION 환경 변수로 바꾼다 - 소스로 돌 때만 (설치본은 따르지 않는다).

설치본은 edition.json 하나만 믿지 않는다 (검토 2026-11-23 I-1 - 그 파일만 지우면 라이선스·복사 막기를 건너뛰었다).
스탠드얼론 표시가 하나라도 있으면 스탠드얼론이다 (fail-closed):
  ① edition.json 이 standalone  ② 컴파일 조각 server_info 가 빈 값 사본 (스탠드얼론 빌드만 싣는다 - 지우거나 고치기 어렵다)
  ③ 목록 서명 파일 manifest.sig (스탠드얼론 설치 파일만 싣는다)  ④ 버전 목록(manifest.json)에 edition.json 이 있다
일반 버전 설치본은 넷 다 없다 (server_info 에 주소가 차 있다) - 지금 동작 그대로 'cloud'.
표시가 서로 어긋나면 ap_guard 가 막는다 (install_mismatch).
"""
import json
import os

CLOUD = "cloud"
STANDALONE = "standalone"
FILE_NAME = "edition.json"
SIG_NAME = "manifest.sig"                  # rpa_update.SHIPPED_SIG_NAME·ap_guard.SIG_NAME 과 같다
_LISTED = {}                               # 목록 경로 → ((mtime_ns, size), edition.json 이 있나) - 일반 버전이 부를 때마다 목록을 읽지 않게


def _read_file(root):
    """edition.json 의 내용 (dict) - 없거나 못 읽으면 None."""
    try:
        with open(os.path.join(root, FILE_NAME), encoding="utf-8") as f:
            got = json.load(f)
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return None


def built_standalone():
    """컴파일 조각 server_info 가 스탠드얼론 빌드의 빈 값 사본인가 (주소가 없다). 못 불러오면 참 (fail-closed - 설치본에서만 묻는다).
    칸이 '있는데 비어 있을' 때만 빈 값 사본으로 본다 - AUTH_HOST 는 2026-11-23 에 생긴 칸이라 옛 일반 버전 조각에는 없다
    (업데이트가 일부만 된 일반 PC 를 스탠드얼론으로 잘못 보고 막지 않게). PROJECT_ID 는 처음부터 있던 칸."""
    try:
        import server_info
    except ImportError:
        return True
    return getattr(server_info, "PROJECT_ID", None) == "" or getattr(server_info, "AUTH_HOST", None) == ""


def _listed(root):
    """버전 목록(manifest.json)에 edition.json 이 있나. 목록이 바뀌지 않았으면 다시 읽지 않는다."""
    path = os.path.join(root, "manifest.json")
    try:
        s = os.stat(path)
    except OSError:
        return False
    stamp = (s.st_mtime_ns, s.st_size)
    hit = _LISTED.get(path)
    if hit and hit[0] == stamp:
        return hit[1]
    try:
        with open(path, encoding="utf-8") as f:
            man = json.load(f)
        files = man.get("files") if isinstance(man, dict) else None
        found = isinstance(files, dict) and FILE_NAME in files
    except (OSError, ValueError):
        found = False
    _LISTED[path] = (stamp, found)
    return found


def _shipped_signs(root):
    """설치본에서 edition.json 말고 스탠드얼론이라는 표시가 있나 (②③④)."""
    return built_standalone() or os.path.isfile(os.path.join(root, SIG_NAME)) or _listed(root)


def edition():
    """'cloud' 또는 'standalone'. 소스로 돌 때 못 읽거나 모르는 값이면 'cloud' (일반 버전 동작이 바뀌지 않게).
    설치본은 위 표시 가운데 하나라도 있으면 'standalone' (edition.json 을 지우거나 바꿔도)."""
    import rpa_status as st
    # 설치본은 환경 변수로 버전 종류를 바꾸지 못한다 (시험 표시가 있어도 - 프로그램 폴더의 파일·조각만 본다, 검토 2026-11-23 6번)
    shipped = st.shipped()
    forced = "" if shipped else (st.dev_env("RPA_EDITION") or "").strip().lower()
    if forced in (CLOUD, STANDALONE):
        return forced
    root = st.program_dir()
    got = _read_file(root)
    if got and got.get("edition") == STANDALONE:
        return STANDALONE
    if shipped and _shipped_signs(root):
        return STANDALONE
    return CLOUD


def is_standalone():
    return edition() == STANDALONE


def install_mismatch():
    """스탠드얼론 설치본에서 버전 종류 표시가 어긋난 자리 이름 ('edition.json' 또는 'server_info'), 맞거나 설치본이 아니면 None.
    ap_guard.startup_problem 이 이것으로 막는다 - edition.json 을 지우거나 바꿨거나, 일반 버전 server_info 조각을 끼웠다."""
    import rpa_status as st
    if not st.shipped():
        return None
    got = _read_file(st.program_dir())
    if not got or got.get("edition") != STANDALONE:
        return FILE_NAME
    if not built_standalone():
        return "server_info"
    return None


def test_build():
    """시험용 빌드인가 - 스탠드얼론이고 edition.json 이 standalone 이며 test_build 가 true (설정 창 제목·웹 띠가 본다). 일반 버전은 False."""
    if not is_standalone():
        return False
    import rpa_status as st
    got = _read_file(st.program_dir())
    return bool(got) and got.get("edition") == STANDALONE and got.get("test_build") is True
