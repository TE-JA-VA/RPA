# -*- coding: utf-8 -*-
"""install.sh 의 도우미 - 같은 설치 파일(또는 설치된 버전) 안의 내장 파이썬으로 `python3 -I -B install_helper.py ...` 로 돈다.
표준 라이브러리와 옆 폴더 app/ 의 서버 모듈만 쓴다. 틀리면 'install.sh: <까닭>' 을 표준 오류에 쓰고 1.

    config LISTEN ALLOW NAMES      인자로 server.json 글을 만든다 (lan_config.parse 로 검사, 쉼표로 여럿)
    config-check PATH              있는 server.json 검사
    config-get PATH FIELD          listen, web_port, agent_port, allow(빈칸으로 이음), loopback(1/0)
    verify-tree TOP VERSION        manifest.json 의 서명·버전과 풀린 파일(지문·크기·링크, 목록에 없는 파일) 대조
    format                         이 버전이 아는 자료 형식 번호 (app/server_main.py 의 FORMAT - 불러오지 않고 글에서)
    license LICENSE DATA           서버 라이선스 미리 확인 (서버 번호, 서명, 자리 서명 열쇠가 자료 폴더의 seat.key 와 짝인지)
    admin-missing ACCOUNTS         켜진 관리자 계정이 없으면 0, 있으면 1
    running-version                표준 입력의 'autopilot-server status --json' → 도는 버전 (안 돌면 빈 줄)
"""
import hashlib
import ipaddress
import json
import os
import re
import sys

TOP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(TOP, "app")


def fail(msg):
    print("install.sh: " + msg, file=sys.stderr)
    sys.exit(1)


def mod(name):
    if APP not in sys.path:
        sys.path.insert(0, APP)
    return __import__(name)


def _split(text):
    return [t.strip() for t in text.split(",") if t.strip()]


def cmd_config(listen, allow, names):
    lan_config = mod("lan_config")
    data = {"listen": listen.strip(), "names": _split(names),
            "ports": {"web": lan_config.DEFAULT_PORTS["web"], "agent": lan_config.DEFAULT_PORTS["agent"]},
            "allow": _split(allow)}
    try:
        lan_config.parse(data)
    except lan_config.ConfigError as e:
        fail("설정 값이 올바르지 않습니다 - " + str(e))
    print(json.dumps(data, ensure_ascii=False, indent=1))


def _load(path):
    lan_config = mod("lan_config")
    try:
        return lan_config.load(path)
    except lan_config.ConfigError as e:
        fail(str(e))


def cmd_config_check(path):
    _load(path)


def cmd_config_get(path, field):
    c = _load(path)
    if field == "listen":
        print(c.listen)
    elif field == "web_port":
        print(c.web_port)
    elif field == "agent_port":
        print(c.agent_port)
    elif field == "allow":
        print(" ".join(str(n) for n in c.allow))
    elif field == "loopback":
        print("1" if ipaddress.ip_address(c.listen).is_loopback else "0")
    else:
        fail(f"모르는 칸입니다: {field}")


def _safe(rel):
    parts = rel.split("/")
    return bool(rel) and not rel.startswith("/") and "\\" not in rel and ".." not in parts and "" not in parts


def cmd_verify_tree(top, version):
    try:
        with open(os.path.join(top, "manifest.json"), "rb") as f:
            raw = f.read()
        man = json.loads(raw)
    except (OSError, ValueError):
        fail("버전 목록(manifest.json)을 읽지 못했습니다.")
    if not isinstance(man, dict) or man.get("version") != version or man.get("edition") != "standalone" or man.get("kind") != "server":
        fail(f"버전 목록이 이 설치 파일(버전 {version})의 것이 아닙니다.")
    update_sign = mod("update_sign")
    try:
        with open(os.path.join(top, "manifest.sig"), encoding="ascii") as f:
            sig = bytes.fromhex(f.read().strip())
        ok = update_sign.verify(update_sign.public_key(), raw, sig)
    except (OSError, ValueError, UnicodeDecodeError):
        ok = False
    if not ok:
        fail("버전 목록(manifest.json)의 서명이 맞지 않습니다.")
    files, links = man.get("files"), man.get("links", {})
    if not isinstance(files, dict) or not isinstance(links, dict):
        fail("버전 목록의 꼴이 올바르지 않습니다.")
    bad, seen = [], set()
    for rel, info in files.items():
        p = os.path.join(top, *rel.split("/")) if _safe(rel) else None
        if p is None or not isinstance(info, dict):
            bad.append(f"{rel} (이름)")
            continue
        seen.add(rel)
        if os.path.islink(p) or not os.path.isfile(p):
            bad.append(f"{rel} (없음)")
            continue
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        if os.path.getsize(p) != info.get("size") or h.hexdigest() != info.get("sha256"):
            bad.append(f"{rel} (지문 다름)")
    for rel, target in links.items():
        p = os.path.join(top, *rel.split("/")) if _safe(rel) else None
        seen.add(rel)
        if p is None or not os.path.islink(p) or os.readlink(p) != target:
            bad.append(f"{rel} (링크 다름)")
    for d, dirs, names in os.walk(top):
        extra = names + [x for x in dirs if os.path.islink(os.path.join(d, x))]
        dirs[:] = [x for x in dirs if x != "__pycache__" and not os.path.islink(os.path.join(d, x))]
        for n in extra:
            rel = os.path.relpath(os.path.join(d, n), top).replace(os.sep, "/")
            if rel not in seen and rel not in ("manifest.json", "manifest.sig"):
                bad.append(f"{rel} (목록에 없음)")
    if bad:
        more = f" 외 {len(bad) - 5}개" if len(bad) > 5 else ""
        fail("설치 파일 안의 파일이 버전 목록의 지문과 다릅니다: " + ", ".join(bad[:5]) + more)


def cmd_format():
    try:
        with open(os.path.join(APP, "server_main.py"), encoding="utf-8") as f:
            m = re.search(r"^FORMAT = (\d+)\b", f.read(), re.M)
    except OSError:
        m = None
    if not m:
        fail("자료 형식 번호(FORMAT)를 찾지 못했습니다.")
    print(int(m.group(1)))


def cmd_license(path, data):
    license_check, seat, update_sign = mod("license_check"), mod("seat"), mod("update_sign")
    try:
        sid = license_check.server_id()
        body = license_check.load_server(path, sid)
    except license_check.LicenseError as e:
        fail(str(e))
    try:
        secret = seat._read_secret(os.path.join(data, seat.SEAT_KEY))
    except (ValueError, OSError) as e:
        fail(str(e))
    if secret is None:
        fail("자리 서명 열쇠(seat.key)가 없습니다. autopilot-server request 로 요청 파일을 다시 만들어 라이선스를 받아 주십시오.")
    if update_sign.secret_to_public(secret).hex() != str(body.get("seat_pub") or "").lower():
        fail("이 서버의 요청 파일로 받은 라이선스가 아닙니다 (자리 서명 열쇠가 다릅니다). 지금 요청 파일로 라이선스를 다시 받아 주십시오.")
    print(f"업체 {body.get('company')} ({body.get('cid')}), PC 자리 {body.get('seats')}, 서버 번호 {sid}")


def cmd_admin_missing(path):
    try:
        with open(path, encoding="utf-8") as f:
            rows = json.load(f).get("accounts") or {}
    except (OSError, ValueError, AttributeError):
        rows = {}
    have = isinstance(rows, dict) and any(isinstance(r, dict) and r.get("role") == "admin" and not r.get("disabled")
                                          for r in rows.values())
    sys.exit(1 if have else 0)


def cmd_running_version():
    try:
        d = json.load(sys.stdin)
    except ValueError:
        d = {}
    print((d.get("running_version") or "") if isinstance(d, dict) and d.get("running") else "")


CMDS = {"config": (cmd_config, 3), "config-check": (cmd_config_check, 1), "config-get": (cmd_config_get, 2),
        "verify-tree": (cmd_verify_tree, 2), "format": (cmd_format, 0), "license": (cmd_license, 2),
        "admin-missing": (cmd_admin_missing, 1), "running-version": (cmd_running_version, 0)}


def main(argv):
    if not argv or argv[0] not in CMDS or len(argv) - 1 != CMDS[argv[0]][1]:
        fail("install_helper.py 를 잘못 불렀습니다: " + " ".join(argv[:1]))
    CMDS[argv[0]][0](*argv[1:])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
