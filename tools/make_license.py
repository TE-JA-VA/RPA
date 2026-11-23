# -*- coding: utf-8 -*-
"""스탠드얼론 라이선스 발급 (우리 PC 에서만 돌린다 - 설계 2026-11-23-standalone 6.4).

    .venv\\Scripts\\python.exe tools\\make_license.py --keygen
        처음 한 번. 서명 열쇠 파일(firebase/admin/license_signing_key.txt, 커밋 금지)을 만들고 공개 열쇠를 알려 준다.
        그 값을 license_check.LICENSE_PUBLIC_KEY_HEX 에 넣는다. 업데이트 서명 열쇠와 따로다.
    .venv\\Scripts\\python.exe tools\\make_license.py <PC번호> <업체 정보.json> [--key 열쇠 파일] [--out license.json]
        PC 번호 = 고객 PC 의 MachineGuid (release\\PC번호_확인.bat). 업체 정보.json 예:
        {"company": "○○상사", "cid": "c_abc", "modules": {"Hold": false}, "features": {"wellife": false},
         "limits": {"schedule": 2, "presets": null, "parallel": null}}
        modules 는 안 쓰는 모듈만 false 로. 없는 칸은 기본값 (모듈 다 씀, 웰라이프 아님, 자동 실행 2줄).

열쇠 파일의 내용은 화면에 찍지 않는다.
"""
import datetime
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import license_check  # noqa: E402
import update_sign  # noqa: E402

KEY_PATH = os.path.join(REPO, "firebase", "admin", "license_signing_key.txt")
SCHEDULE_DEFAULT = 2          # agent.SCHEDULE_LIMIT_DEFAULT 와 같다
PC_ID = re.compile(r"^[0-9a-f-]{8,64}$")
CID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def keygen(key_path=KEY_PATH):
    """서명 열쇠 파일을 만들고 공개 열쇠(16진수)를 돌려준다. 이미 있으면 FileExistsError (덮으면 발급한 라이선스가 모두 죽는다)."""
    if os.path.exists(key_path):
        raise FileExistsError(key_path)
    secret, public = update_sign.keygen()
    with open(key_path, "w", encoding="ascii") as f:
        f.write(secret.hex() + "\n")
    return public.hex()


def _secret(key_path):
    with open(key_path, encoding="ascii") as f:
        return bytes.fromhex(f.read().strip())


def build_body(pc_id, info, today=None):
    """업체 정보 dict 를 라이선스 body 로. 모양이 틀리면 ValueError (사람 말)."""
    pc_id = str(pc_id or "").strip().lower()
    if not PC_ID.match(pc_id):
        raise ValueError("PC 번호가 올바르지 않습니다. (MachineGuid - 숫자·a~f·- 로 8자 이상)")
    if not isinstance(info, dict):
        raise ValueError("업체 정보는 { } 꼴이어야 합니다.")
    company, cid = info.get("company"), info.get("cid")
    if not isinstance(company, str) or not company.strip():
        raise ValueError("업체 이름(company)이 없습니다.")
    if not isinstance(cid, str) or not CID.match(cid):
        raise ValueError("업체 코드(cid)가 없거나 올바르지 않습니다. (영문·숫자·_·- 만)")
    modules = info.get("modules") or {}
    if not isinstance(modules, dict) or any(v is not False for v in modules.values()):
        raise ValueError("modules 는 안 쓰는 모듈만 false 로 적습니다.")
    features = info.get("features") or {}
    if not isinstance(features, dict):
        raise ValueError("features 는 { } 꼴이어야 합니다.")
    limits = info.get("limits") or {}
    if not isinstance(limits, dict):
        raise ValueError("limits 는 { } 꼴이어야 합니다.")
    for k in ("schedule", "presets", "parallel"):
        v = limits.get(k)
        if v is not None and (not isinstance(v, int) or isinstance(v, bool) or v < 0):
            raise ValueError(f"limits.{k} 는 0 이상의 정수여야 합니다.")
    return {"edition": license_check.EDITION, "company": company.strip(), "cid": cid, "pc_id": pc_id,
            "issued": (today or datetime.date.today()).isoformat(),
            "modules": dict(modules),
            "features": {"wellife": features.get("wellife") is True},
            "limits": {"schedule": SCHEDULE_DEFAULT if limits.get("schedule") is None else limits["schedule"],
                       "presets": limits.get("presets"), "parallel": limits.get("parallel")}}


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--keygen"]:
        try:
            public = keygen(*args[1:2])
        except FileExistsError as e:
            print(f"열쇠 파일이 이미 있습니다: {e}  (덮으면 발급한 라이선스가 모두 죽습니다 - 그대로 둡니다)")
            return 1
        print("공개 열쇠 (license_check.LICENSE_PUBLIC_KEY_HEX 에 넣으십시오):", public)
        return 0
    key_path, out = KEY_PATH, None
    rest = []
    it = iter(args)
    for a in it:
        if a == "--key":
            key_path = next(it, None)
        elif a == "--out":
            out = next(it, None)
        else:
            rest.append(a)
    if len(rest) != 2 or not key_path:
        print(__doc__)
        return 2
    try:
        with open(rest[1], encoding="utf-8-sig") as f:
            info = json.load(f)
        body = build_body(rest[0], info)
    except (OSError, ValueError) as e:
        print(f"발급하지 못했습니다: {e}")
        return 1
    if not os.path.isfile(key_path):
        print(f"서명 열쇠 파일이 없습니다: {key_path}  (처음이면 --keygen)")
        return 1
    out = out or os.path.join(os.getcwd(), f"license_{body['cid']}_{body['pc_id'][-4:]}.json")
    doc = license_check.sign_body(_secret(key_path), body)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f"발급: {out}  업체 {body['company']} ({body['cid']})  PC 번호 {body['pc_id']}  발급일 {body['issued']}")
    print(f"고객 PC 의 설정 폴더에 {license_check.FILE_NAME} 이름으로 넣습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
