# -*- coding: utf-8 -*-
"""스탠드얼론 라이선스 확인 - 구매한 PC 에서만 켜지게 한다 (설계 2026-11-23-standalone 6.4).

라이선스 파일(license.json) = {"body": {...}, "sig": "<16진수>"}. body 는 업체 이름·업체 코드·PC 번호(윈도우 MachineGuid)·
발급일·모듈·기능·한도이고, sig 는 body 를 정해진 글 순서(canonical)로 적은 것에 우리가 한 서명(Ed25519)이다.
서명 열쇠는 업데이트 서명 열쇠와 따로다 - 개인 열쇠는 우리 PC 에만 (tools/make_license.py 가 만든다), 공개 열쇠만 여기 싣는다.
업체 정책(안 쓰는 모듈·웰라이프·한도)도 여기서 온다 - 일반 버전의 관리 화면 자리.
윈도우를 다시 깔면 PC 번호가 바뀐다 → 새 라이선스를 발급한다.
"""
import json
import os

import update_sign

LICENSE_PUBLIC_KEY_HEX = "482bc5c2367953d22c9e5ba138865c3e9dec6f8fee78606ec521e141349a9a80"     # tools/make_license.py --keygen 이 알려 준 값 (사용자 2026-11-24). 비어 있으면 어떤 라이선스도 통과하지 못한다
FILE_NAME = "license.json"
EDITION = "standalone"


class LicenseError(ValueError):
    """라이선스가 없거나 맞지 않는다. 글은 사람에게 그대로 보여 준다.
    ValueError 의 하나다 - 설정을 읽는 쪽(에이전트 main·인증번호 중계)이 '설정 문제' 로 받아 같은 길로 안내한다."""


def machine_guid():
    """이 PC 의 번호 (윈도우 MachineGuid, 소문자). 시험은 RPA_MACHINE_GUID 로 바꾼다 - **소스로 돌 때만**.
    설치본은 시험 표시(test_env.ok)가 있어도 따르지 않는다: 표시 파일 하나와 환경 변수로 다른 PC 의 라이선스가 통과했다 (검토 2026-11-23 6번)."""
    import rpa_status as st
    forced = "" if st.shipped() else (st.dev_env("RPA_MACHINE_GUID") or "").strip()
    if forced:
        return forced.lower()
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                        winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
        return str(winreg.QueryValueEx(key, "MachineGuid")[0]).strip().lower()


def license_path():
    import rpa_status as st
    return os.path.join(st.install_root(), FILE_NAME)


def canonical(body):
    """서명하는 글 - 칸 이름 순서로, 빈칸 없이, 한글 그대로."""
    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_body(secret, body):
    """발급 도구·시험용: 서명을 붙인 라이선스 파일 내용."""
    return {"body": body, "sig": update_sign.sign(secret, canonical(body)).hex()}


def load(path=None, guid=None, public_key=None):
    """라이선스를 읽어 맞으면 body 를 돌려준다. 아니면 LicenseError (사람 말).
    path·guid·public_key 는 시험이 바꿔 끼운다 - 없으면 license_path()·이 PC 번호·실린 공개 열쇠."""
    path = path or license_path()
    guid = (guid or machine_guid()).strip().lower()
    key = LICENSE_PUBLIC_KEY_HEX if public_key is None else public_key
    if not os.path.isfile(path):
        raise LicenseError(f"라이선스 파일이 없습니다. 공급사에서 받은 {FILE_NAME} 을 넣어 주십시오. (자리 {path}, PC 번호 {guid})")
    try:
        with open(path, encoding="utf-8-sig") as f:
            doc = json.load(f)
        body, sig = doc["body"], doc["sig"]
        if not isinstance(body, dict) or not isinstance(sig, str):
            raise ValueError("모양")
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise LicenseError(f"라이선스 파일을 읽지 못했습니다. ({type(e).__name__}) 공급사에서 받은 파일을 다시 넣어 주십시오.") from None
    if not key:
        raise LicenseError("라이선스 확인 열쇠가 없습니다. 프로그램을 다시 설치하여 주십시오.")
    try:
        ok = update_sign.verify(bytes.fromhex(key), canonical(body), bytes.fromhex(sig))
    except ValueError:
        ok = False
    if not ok:
        raise LicenseError("라이선스 서명이 맞지 않습니다. 공급사에서 받은 파일을 고치지 말고 그대로 넣어 주십시오.")
    if body.get("edition") != EDITION:
        raise LicenseError("스탠드얼론 라이선스가 아닙니다. 공급사에 문의하여 주십시오.")
    if str(body.get("pc_id") or "").strip().lower() != guid:
        raise LicenseError(f"이 PC 의 라이선스가 아닙니다. (PC 번호 {guid}) 이 PC 번호로 라이선스를 다시 받아 주십시오.")
    return body
