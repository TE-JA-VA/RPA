# -*- coding: utf-8 -*-
"""버전 종류 - 일반(cloud, Firebase)인가 스탠드얼론(standalone, 그 PC 의 로컬 서버)인가 (설계 2026-11-23-standalone 6.1).

값은 빌드 때 정해진다: 스탠드얼론 설치 파일이 프로그램 폴더에 edition.json = {"edition": "standalone"} 을 싣는다.
그 파일이 없으면 일반 버전. 화면에서 바꾸는 곳은 없다 (프로그램 폴더는 관리자만 쓴다).
시험은 RPA_EDITION 환경 변수로 바꾼다 - 설치본은 프로그램 폴더에 시험 표시가 있을 때만 따른다 (rpa_status.dev_env).
"""
import json
import os

CLOUD = "cloud"
STANDALONE = "standalone"
FILE_NAME = "edition.json"


def edition():
    """'cloud' 또는 'standalone'. 못 읽거나 모르는 값이면 'cloud' (일반 버전 동작이 바뀌지 않게)."""
    import rpa_status as st
    forced = (st.dev_env("RPA_EDITION") or "").strip().lower()
    if forced in (CLOUD, STANDALONE):
        return forced
    try:
        with open(os.path.join(st.program_dir(), FILE_NAME), encoding="utf-8") as f:
            got = json.load(f)
        if isinstance(got, dict) and got.get("edition") == STANDALONE:
            return STANDALONE
    except (OSError, ValueError):
        pass
    return CLOUD


def is_standalone():
    return edition() == STANDALONE
