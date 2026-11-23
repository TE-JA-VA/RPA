# -*- coding: utf-8 -*-
"""스탠드얼론 복사 막기 - exe 셋(PROCESS·ACTOR·옵저버)이 켤 때 라이선스와 프로그램 파일을 확인한다
(계획 docs/superpowers/plans/2026-11-23-standalone-3-install-build.md Task 3, 설계 2026-11-23-standalone 6.4·6.5).

설치본에는 조각(app\\ap_guard.pyd)으로만 실린다 - 컴파일된 코드가 컴파일된 코드를 부른다. 일반 버전에서는 아무것도 하지 않는다
(startup_problem → None, check_line → ""). 맨 위에서는 edition 만 불러온다 - 나머지는 스탠드얼론일 때 함수 안에서 (일반 버전의 켜는 시간).
확인하는 것: ① 라이선스(이 PC 번호·서명) ② 버전 목록 서명(manifest.sig, 설치 파일이 싣는다) ③ 목록의 파일 지문
④ app\\ 에 끼운 .py·.pyc 와 .pyd 가 아닌 곳에서 불린 가드 조각.
한계: 가드 조각 자체를 직접 컴파일한 가짜로 바꾸는 것까지는 막지 못한다 - .py 한 줄 고치기를 막는 단계다.
"""
import os

import edition

EXIT_BLOCKED = 2
GUARD_PIECES = ("license_check", "ap_guard", "rpa_status", "update_sign", "edition")
SIG_NAME = "manifest.sig"                 # rpa_update.SHIPPED_SIG_NAME 과 같다 (버전 목록 서명, 16진수)
REINSTALL = "같은 버전 설치 파일로 다시 설치하여 주십시오."
SIG_TEXT = "프로그램 파일의 서명을 확인하지 못했습니다. " + REINSTALL
LOOSE_TEXT = "프로그램 파일이 설치된 버전과 달라 실행하지 않습니다. ({}) " + REINSTALL


def manifest_signed(root):
    """root\\manifest.sig 가 root\\manifest.json 바이트에 대한 맞는 서명인가 (실린 업데이트 공개 열쇠로)."""
    import update_sign
    try:
        with open(os.path.join(root, SIG_NAME), encoding="ascii") as f:
            sig = bytes.fromhex(f.read().strip())
        with open(os.path.join(root, "manifest.json"), "rb") as f:
            man = f.read()
    except (OSError, ValueError, UnicodeDecodeError):
        return False
    key = update_sign.public_key()
    return bool(key) and update_sign.verify(key, man, sig)


def _compiled(mod):
    """조각(.pyd)에서 불린 모듈인가 - Nuitka 가 넣는 __compiled__ 나 확장 모듈 자리."""
    import importlib.machinery
    if "__compiled__" in vars(mod):
        return True
    spec = getattr(mod, "__spec__", None)
    places = [getattr(mod, "__file__", None), getattr(spec, "origin", None)]
    return any(isinstance(p, str) and p.lower().endswith(tuple(s.lower() for s in importlib.machinery.EXTENSION_SUFFIXES))
               for p in places)


def loose_sources(root, modules=None):
    """설치본에 있으면 안 되는 것: root\\app 의 .py·.pyc (_start.py 말고), 그리고 GUARD_PIECES 가운데 .pyd 가 아닌 곳에서 불린 것.
    modules 는 시험용 (기본 sys.modules)."""
    import sys
    out = []
    try:
        names = sorted(os.listdir(os.path.join(root, "app")))
    except OSError:
        names = []
    for name in names:
        low = name.lower()
        if low != "_start.py" and low.endswith((".py", ".pyc")):
            out.append(f"app\\{name}")
    modules = sys.modules if modules is None else modules
    for piece in GUARD_PIECES:
        mod = modules.get(piece)
        if mod is not None and not _compiled(mod):
            out.append(str(getattr(mod, "__file__", None) or piece))
    return out


def startup_problem():
    """켜면 안 되는 까닭 (사람에게 보일 글), 문제가 없으면 None. 일반 버전은 늘 None (라이선스를 읽지 않는다)."""
    if not edition.is_standalone():
        return None
    import license_check
    try:
        license_check.load()
    except license_check.LicenseError as e:
        return str(e)
    import rpa_status as st
    if not st.shipped():                  # 소스로 도는 개발 PC - 라이선스만 본다
        return None
    root = st.program_dir()
    if not manifest_signed(root):
        return SIG_TEXT
    install = st.check_install(root)
    if install.get("state") == "tampered":
        return st.tamper_text(install)
    if install.get("state") == "error":
        return SIG_TEXT
    loose = loose_sources(root)
    if loose:
        return LOOSE_TEXT.format(loose[0])
    return None


def check_line():
    """--check 에 찍는 줄: '라이선스: 확인됨 (<업체 이름>, PC 번호 <…>)' 또는 '라이선스: <문제 글>'. 일반 버전은 "" (찍지 않는다)."""
    if not edition.is_standalone():
        return ""
    import license_check
    try:
        body = license_check.load()
    except license_check.LicenseError as e:
        return f"라이선스: {e}"
    return f"라이선스: 확인됨 ({body.get('company') or '?'}, PC 번호 {license_check.machine_guid()})"
