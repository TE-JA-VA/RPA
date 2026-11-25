# -*- coding: utf-8 -*-
"""사내 서버 ② Task 1 - server.json 읽기·검사 lan_config (계획 2026-11-24-lan-2-network).
사설 주소에만 듣기·포트·허용 대역·믿을 프록시·평문 프록시 모양·모르는 칸 거절. 포트는 열지 않는다.
    D:/AX/RPA/.venv/Scripts/python.exe tests/test_lan_config.py
"""
import json
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
import lan_config  # noqa: E402

fails = []
TMP = tempfile.mkdtemp(prefix="rpa_lan_config_")


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def raises_config(fn):
    """fn 이 ConfigError 를 내면 참 (다른 예외·통과는 거짓)."""
    try:
        fn()
    except lan_config.ConfigError:
        return True
    except Exception:
        return False
    return False


def write(name, text):
    path = os.path.join(TMP, name)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path


def test_minimal():
    print("[최소 설정]")
    # 사내 서버 ④ ②검-3: listen 이 루프백이 아니면 allow 를 꼭 적는다 (비우면 ConfigError - test_lan_polish)
    c = lan_config.parse({"listen": "192.168.1.230", "allow": ["192.168.1.0/24"]})
    check("기본 포트", (c.web_port, c.agent_port, c.phone_port) == (8443, 8444, 8782))
    check("listen 은 names 에 들어간다", "192.168.1.230" in c.names)
    check("웹 Host 목록", c.web_hosts() == frozenset({"192.168.1.230:8443"}), c.web_hosts())
    check("에이전트 Host 목록", c.agent_hosts() == frozenset({"192.168.1.230:8444"}), c.agent_hosts())
    loop = lan_config.parse({"listen": "127.0.0.1"})
    check("루프백 listen 은 허용 대역이 비어도 되고, 그러면 루프백만", loop.allowed("127.0.0.1") and not loop.allowed("192.168.1.5"))
    check("IPv6 루프백도 늘 허용", c.allowed("::1"))
    check("기본값 - 믿을 프록시 없음", c.trusted_proxies == () and not c.is_proxy("127.0.0.1"))
    check("기본값 - proxy_only·web_plain 꺼짐, 세션 주소 묶기 켜짐",
          (c.proxy_only, c.web_plain, c.bind_session_ip) == (False, False, True))
    check("기본값 - 공개 이름 없음", c.public_web == ())
    check("평문 모양이 아니면 웹도 listen 에서", c.web_listen == "192.168.1.230")
    check("LanConfig 는 바꿀 수 없다", raises_any(lambda: setattr(c, "web_port", 1)))
    check("칸들은 튜플", isinstance(c.names, tuple) and isinstance(c.allow, tuple))


def raises_any(fn):
    try:
        fn()
    except Exception:
        return True
    return False


def test_full():
    print("[모든 칸]")
    c = lan_config.parse({"listen": "192.168.1.230", "names": ["AP.Corp.Local", "nt.corp.local", "192.168.1.230"],
                          "ports": {"web": 9443, "agent": 9444, "phone": 9782},
                          "allow": ["192.168.1.0/24", "10.1.2.3/16"], "trusted_proxies": [], "proxy_only": False,
                          "web_plain": False, "public_web": [], "bind_session_ip": False})
    check("포트 바꾸기", (c.web_port, c.agent_port, c.phone_port) == (9443, 9444, 9782))
    check("listen 이 이미 있으면 한 번만", c.names.count("192.168.1.230") == 1, c.names)
    check("웹 Host 목록은 소문자·이름마다",
          c.web_hosts() == frozenset({"ap.corp.local:9443", "nt.corp.local:9443", "192.168.1.230:9443"}), c.web_hosts())
    check("에이전트 Host 목록",
          c.agent_hosts() == frozenset({"ap.corp.local:9444", "nt.corp.local:9444", "192.168.1.230:9444"}), c.agent_hosts())
    check("허용 대역 안", c.allowed("192.168.1.5") and c.allowed("10.1.200.7"))
    check("허용 대역 밖", not c.allowed("192.168.2.5") and not c.allowed("10.2.0.1") and not c.allowed("8.8.8.8"))
    check("strict=False - 10.1.2.3/16 은 10.1.0.0/16", str(c.allow[1]) == "10.1.0.0/16", c.allow)
    check("주소가 아니면 허용 아님", not c.allowed("nt") and not c.allowed("") and not c.allowed(None))
    check("IPv4 를 담은 IPv6 주소도 IPv4 로 본다", c.allowed("::ffff:192.168.1.5") and not c.allowed("::ffff:8.8.8.8"))
    check("bind_session_ip 끄기", c.bind_session_ip is False)


def test_ipv6():
    print("[IPv6]")
    c = lan_config.parse({"listen": "fd12:3456::1", "allow": ["fd12:3456::/64"]})
    check("ULA 에 듣기", c.names == ("fd12:3456::1",), c.names)
    check("IPv6 이름은 Host 에서 대괄호", c.web_hosts() == frozenset({"[fd12:3456::1]:8443"}), c.web_hosts())
    check("ULA 허용 대역", c.allowed("fd12:3456::99") and not c.allowed("fd12:3457::1"))
    check("::1 에 듣기", lan_config.parse({"listen": "::1"}).listen == "::1")
    check("listen 은 줄인 꼴로", lan_config.parse({"listen": "FD12:3456:0:0::1", "allow": ["fd12:3456::/64"]}).listen == "fd12:3456::1")


def test_rejects():
    print("[거절]")
    A = {"listen": "192.168.1.2", "allow": ["192.168.1.0/24"]}       # 허용 대역은 늘 적는다 - 다른 까닭으로 거절되는지 본다
    for bad in ({"listen": "0.0.0.0"}, {"listen": "8.8.8.8"}, {"listen": "nt.local"}, {"listen": "192.168.1.2", "allow": ["0.0.0.0/0"]},
                dict(A, ports={"web": 443}), dict(A, ports={"web": 8444}),
                dict(A, web_plain=True), dict(A, proxy_only=True),
                dict(A, lisen=1), dict(A, names=["a b"]), {"listen": "192.168.1.2"}):
        check(f"거절 {bad}", raises_config(lambda: lan_config.parse(bad)))


def test_rejects_more():
    print("[거절 - 더]")
    L = {"listen": "192.168.1.2", "allow": ["192.168.1.0/24"]}       # 허용 대역은 늘 적는다 (사내 서버 ④ ②검-3)
    cases = [
        ("listen 없음", {}),
        ("dict 아님", ["listen"]),
        ("listen 숫자", {"listen": 1}),
        ("listen ::", {"listen": "::"}),
        ("listen 링크 로컬 IPv4", {"listen": "169.254.1.2"}),
        ("listen 링크 로컬 IPv6", {"listen": "fe80::1"}),
        ("listen 링크 로컬 IPv6 범위 붙임", {"listen": "fe80::1%eth0"}),
        ("listen 공인 IPv6", {"listen": "2001:4860:4860::8888"}),
        ("listen CGNAT 100.64", {"listen": "100.64.0.1"}),
        ("listen 문서용 대역", {"listen": "192.0.2.1"}),
        ("listen 대역 글자", {"listen": "192.168.1.0/24"}),
        ("listen 멀티캐스트", {"listen": "224.0.0.1"}),
        ("listen 앞뒤 빈칸", {"listen": " 192.168.1.2"}),
        ("names 목록 아님", dict(L, names="nt")),
        ("names 빈 글자", dict(L, names=[""])),
        ("names 254 글자", dict(L, names=["a" * 254])),
        ("names 밑줄", dict(L, names=["nt_1"])),
        ("names 숫자", dict(L, names=[1])),
        ("names 콜론 붙은 이름", dict(L, names=["nt:8443"])),
        ("ports dict 아님", dict(L, ports=[8443])),
        ("ports 모르는 칸", dict(L, ports={"admin": 9000})),
        ("ports 1023", dict(L, ports={"phone": 1023})),
        ("ports 65536", dict(L, ports={"agent": 65536})),
        ("ports 글자", dict(L, ports={"web": "8443"})),
        ("ports 참거짓", dict(L, ports={"web": True})),
        ("ports 소수", dict(L, ports={"web": 8443.0})),
        ("ports 에이전트=휴대폰", dict(L, ports={"agent": 8782})),
        ("allow 목록 아님", dict(L, allow="192.168.1.0/24")),
        ("allow 공인 대역", dict(L, allow=["8.8.8.0/24"])),
        ("allow 사설을 넘는 대역", dict(L, allow=["192.168.0.0/15"])),
        ("allow 링크 로컬", dict(L, allow=["169.254.0.0/16"])),
        ("allow IPv6 전체", dict(L, allow=["::/0"])),
        ("allow 글자 아님", dict(L, allow=[10])),
        ("allow 이름", dict(L, allow=["nt.local"])),
        ("trusted_proxies 이름", dict(L, trusted_proxies=["proxy.local"])),
        ("trusted_proxies 전체", dict(L, trusted_proxies=["0.0.0.0/0"])),
        ("trusted_proxies 공인", dict(L, trusted_proxies=["8.8.8.8"])),
        ("trusted_proxies 목록 아님", dict(L, trusted_proxies="127.0.0.1")),
        ("web_plain 인데 127.0.0.1 이 프록시 아님", dict(L, trusted_proxies=["192.168.1.9"], web_plain=True)),
        ("web_plain 글자", dict(L, trusted_proxies=["127.0.0.1"], web_plain="true")),
        ("proxy_only 숫자", dict(L, trusted_proxies=["192.168.1.9"], proxy_only=1)),
        ("bind_session_ip 글자", dict(L, bind_session_ip="yes")),
        ("public_web 목록 아님", dict(L, public_web="autopilot.corp.local")),
        ("public_web 빈칸", dict(L, public_web=["auto pilot"])),
        ("public_web 포트 글자", dict(L, public_web=["autopilot:abc"])),
        ("public_web 경로", dict(L, public_web=["autopilot/x"])),
    ]
    for name, bad in cases:
        check(f"거절 - {name}", raises_config(lambda: lan_config.parse(bad)))
    try:
        lan_config.parse({"listen": "8.8.8.8"})
        msg = ""
    except lan_config.ConfigError as e:
        msg = str(e)
    check("까닭은 한국어로", any("\uac00" <= ch <= "\ud7a3" for ch in msg), msg)
    check("ConfigError 는 ValueError", issubclass(lan_config.ConfigError, ValueError))


def test_private_ranges():
    print("[사설·루프백 대역]")
    for ok in ("10.0.0.1", "172.16.0.1", "172.31.255.254", "192.168.0.1", "127.0.0.1", "127.1.2.3", "fd00::1", "fc00::1", "::1"):
        check(f"듣기 허용 {ok}", not raises_config(lambda: lan_config.parse({"listen": ok, "allow": [ok]})))
    for bad in ("172.32.0.1", "172.15.255.255", "11.0.0.1", "192.169.0.1", "fe80::1", "2001:db8::1", "255.255.255.255"):
        check(f"듣기 거절 {bad}", raises_config(lambda: lan_config.parse({"listen": bad})))
    c = lan_config.parse({"listen": "127.0.0.1", "allow": ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8",
                                                         "fc00::/7", "::1/128"]})
    check("사설 대역 넷과 루프백 대역", len(c.allow) == 6, c.allow)


def test_proxy_fields():
    print("[프록시 칸]")
    c = lan_config.parse({"listen": "10.0.0.5", "allow": ["10.0.0.0/8"], "trusted_proxies": ["10.0.0.9"], "public_web": ["Autopilot.corp.local"]})
    check("믿을 프록시", c.is_proxy("10.0.0.9") and not c.is_proxy("10.0.0.10"))
    check("프록시 판단 - 주소가 아니면 거짓", not c.is_proxy("proxy") and not c.is_proxy(None))
    check("공개 이름은 소문자로 웹 Host 목록에", "autopilot.corp.local" in c.web_hosts())
    check("공개 이름은 에이전트 Host 목록에 없다", not any(h.startswith("autopilot") for h in c.agent_hosts()))
    check("공개 이름 보관도 소문자", c.public_web == ("autopilot.corp.local",), c.public_web)
    secret = "s" * 40                    # 평문 모양은 proxy_secret 이 있어야 한다 (사내 서버 ④ Codex 검토 13 - test_lan_polish)
    p = lan_config.parse({"listen": "10.0.0.5", "allow": ["10.0.0.0/8"], "trusted_proxies": ["127.0.0.1"], "web_plain": True,
                          "proxy_secret": secret})
    check("평문 모양이면 웹은 127.0.0.1 에서", p.web_listen == "127.0.0.1")
    check("평문 모양이어도 listen 은 그대로", p.listen == "10.0.0.5")
    q = lan_config.parse({"listen": "10.0.0.5", "allow": ["10.0.0.0/8"], "trusted_proxies": ["127.0.0.0/8"], "web_plain": True,
                          "proxy_secret": secret})
    check("127.0.0.0/8 대역도 127.0.0.1 을 품는다", q.web_plain and q.is_proxy("127.0.0.1"))
    r = lan_config.parse({"listen": "10.0.0.5", "allow": ["10.0.0.0/8"], "trusted_proxies": ["10.0.0.0/30"], "proxy_only": True,
                          "public_web": ["autopilot.corp.local:443"]})
    check("proxy_only 는 프록시가 있으면 켜진다", r.proxy_only and r.is_proxy("10.0.0.2"))
    check("공개 이름에 포트를 붙일 수 있다", "autopilot.corp.local:443" in r.web_hosts())


def test_load_file():
    print("[파일 읽기]")
    check("없는 파일", raises_config(lambda: lan_config.load(os.path.join(TMP, "none.json"))))
    check("JSON 아님", raises_config(lambda: lan_config.load(write("bad.json", "{listen: 1"))))
    check("JSON 이지만 dict 아님", raises_config(lambda: lan_config.load(write("list.json", "[1, 2]"))))
    check("UTF-8 아님", raises_config(lambda: lan_config.load(write_bytes("cp.json", b'{"listen": "\xb3\xaa"}'))))
    check("폴더를 주면", raises_config(lambda: lan_config.load(TMP)))
    good = {"listen": "192.168.1.230", "names": ["nt.corp.local"], "ports": {"web": 8443, "agent": 8444, "phone": 8782},
            "allow": ["192.168.1.0/24"], "trusted_proxies": [], "proxy_only": False, "web_plain": False,
            "public_web": [], "bind_session_ip": True}
    c = lan_config.load(write("server.json", json.dumps(good, ensure_ascii=False, indent=2)))
    check("맞는 파일 → LanConfig", isinstance(c, lan_config.LanConfig))
    check("파일 값", c.names == ("192.168.1.230", "nt.corp.local") and c.allowed("192.168.1.77"), c.names)
    c2 = lan_config.load(write_bytes("bom.json", b"\xef\xbb\xbf" + json.dumps(good).encode("utf-8")))
    check("BOM 붙은 파일도 읽는다", c2 == c)
    check("파일의 검사 실패도 ConfigError",
          raises_config(lambda: lan_config.load(write("pub.json", '{"listen": "8.8.8.8"}'))))


def write_bytes(name, data):
    path = os.path.join(TMP, name)
    with open(path, "wb") as f:
        f.write(data)
    return path


if __name__ == "__main__":
    try:
        test_minimal()
        test_full()
        test_ipv6()
        test_rejects()
        test_rejects_more()
        test_private_ranges()
        test_proxy_fields()
        test_load_file()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n실패 {len(fails)}건" + (": " + ", ".join(fails) if fails else ""))
    sys.exit(1 if fails else 0)
