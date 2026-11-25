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
    .venv\\Scripts\\python.exe tools\\make_license.py --server <server_request.json> <업체 정보.json> [--key 열쇠 파일] [-o license.json]
        사내 서버(리눅스) 라이선스. 요청 파일은 서버에서 `autopilot-server request` 가 만든 것
        ({"server_id", "seat_pub", "version"} - 비밀 값 없음). 업체 정보는 위 꼴에 "seats"(PC 자리 수, 1~9999)를 더한다.

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
# 발급하는 한도의 범위 - PC 쪽이 받는 범위와 같다 (밖이면 PC 가 조용히 기본값으로 바꿔 업체가 산 것과 다르게 돈다, 전1-5).
# 시험(test_lan_polish)이 PC 쪽 상수와 같은지 본다
PRESETS_RANGE = (2, 50)       # rpa_status.PRESET_MIN, PRESET_MAX
PARALLEL_RANGE = (1, 16)      # rpa_status.PARALLEL_MIN, PARALLEL_MAX
SCHEDULE_RANGE = (0, 12)      # 0 ~ agent.SCHEDULE_LIMIT_MAX
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
    return _policy(info, {"pc_id": pc_id}, today)


def build_server_body(request, info, today=None):
    """사내 서버 요청 파일 dict(server_id·seat_pub)와 업체 정보 dict(+ seats)를 서버 라이선스 body 로 (사내 서버 ④ Task 2).
    모양이 틀리면 ValueError (사람 말). 만든 body 는 license_check.load_server 를 통과하는 꼴이다."""
    if not isinstance(request, dict):
        raise ValueError("요청 파일은 { } 꼴이어야 합니다.")
    sid = str(request.get("server_id") or "").strip().lower()
    if not license_check.SERVER_ID_RE.fullmatch(sid):
        raise ValueError("요청 파일의 서버 번호(server_id)가 올바르지 않습니다. (32자 16진수)")
    seat_pub = str(request.get("seat_pub") or "").strip().lower()
    if not license_check.HEX64.fullmatch(seat_pub):
        raise ValueError("요청 파일의 자리 서명 공개 열쇠(seat_pub)가 올바르지 않습니다. (64자 16진수)")
    seats = info.get("seats") if isinstance(info, dict) else None
    if not isinstance(seats, int) or isinstance(seats, bool) or not 1 <= seats <= license_check.SEATS_MAX:
        raise ValueError(f"업체 정보의 PC 자리 수(seats)는 1~{license_check.SEATS_MAX} 의 정수여야 합니다.")
    return _policy(info, {"kind": license_check.SERVER_KIND, "server_id": sid, "seat_pub": seat_pub, "seats": seats}, today)


def _policy(info, who, today=None):
    """업체 정보 dict 의 공통 칸(업체·모듈·기능·한도) + who(PC 번호 또는 서버 칸) → body. 모양이 틀리면 ValueError."""
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
    for k, (lo, hi) in (("schedule", SCHEDULE_RANGE), ("presets", PRESETS_RANGE), ("parallel", PARALLEL_RANGE)):
        v = limits.get(k)
        if v is not None and (not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi):
            raise ValueError(f"limits.{k} 는 {lo}~{hi} 의 정수여야 합니다 (비우면 기본값).")
    return {"edition": license_check.EDITION, "company": company.strip(), "cid": cid, **who,
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
    key_path, out, server = KEY_PATH, None, False
    rest = []
    it = iter(args)
    for a in it:
        if a == "--key":
            key_path = next(it, None)
        elif a in ("--out", "-o"):
            out = next(it, None)
        elif a == "--server":
            server = True
        else:
            rest.append(a)
    if len(rest) != 2 or not key_path:
        print(__doc__)
        return 2
    try:
        with open(rest[1], encoding="utf-8-sig") as f:
            info = json.load(f)
        if server:
            with open(rest[0], encoding="utf-8-sig") as f:
                request = json.load(f)
            body = build_server_body(request, info)
        else:
            body = build_body(rest[0], info)
    except (OSError, ValueError) as e:
        print(f"발급하지 못했습니다: {e}")
        return 1
    if not os.path.isfile(key_path):
        print(f"서명 열쇠 파일이 없습니다: {key_path}  (처음이면 --keygen)")
        return 1
    who = body["server_id"] if server else body["pc_id"]
    out = out or os.path.join(os.getcwd(), f"license_{body['cid']}_{'server_' if server else ''}{who[-4:]}.json")
    doc = license_check.sign_body(_secret(key_path), body)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    if server:
        print(f"발급: {out}  업체 {body['company']} ({body['cid']})  서버 번호 {who}  PC 자리 {body['seats']}  발급일 {body['issued']}")
        print("업체 서버에서 install.sh activate <이 파일> 로 넣습니다.")
    else:
        print(f"발급: {out}  업체 {body['company']} ({body['cid']})  PC 번호 {body['pc_id']}  발급일 {body['issued']}")
        print(f"고객 PC 의 설정 폴더에 {license_check.FILE_NAME} 이름으로 넣습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
