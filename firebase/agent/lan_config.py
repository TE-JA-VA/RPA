# -*- coding: utf-8 -*-
"""사내 서버 설정 server.json 읽기·검사 (계획 2026-11-24-lan-2-network Task 1, 설계 6.3).

- server.json 꼴: {"listen": "192.168.1.230", "names": ["nt.corp.local"],"ports": {"web": 8443, "agent": 8444, "phone": 8782},
  "allow": ["192.168.1.0/24"], "trusted_proxies": [], "proxy_only": false, "web_plain": false,
  "public_web": [], "bind_session_ip": true, "backup_hour": 3, "proxy_secret": null}. listen 만 꼭 있어야 하고 나머지는 이 기본값 -
  단 listen 이 루프백이 아니면 allow 도 꼭 적는다 (②검-3), web_plain 이면 proxy_secret(32자 이상)도 (Codex 검토 13).
- names 는 인증서 발급(lan_ca._dns)과 같은 규칙, 점 없는 이름은 localhost 만, IP 는 사설·루프백만 (②검-9).
  proxy_only 면 믿을 프록시가 allow 안이나 루프백이어야 한다 (②검-10).
- 서버는 사설·루프백 주소에만 듣는다. 사설은 Python 의 is_private 에 맡기지 않고 아래 PRIVATE_NETS 로 못박는다
  (is_private 는 0.0.0.0/8·문서용 대역까지 참이라 '사설' 의 뜻과 다르다). 링크 로컬은 듣기·대역 모두 안 된다.
- 허용 대역 밖 연결은 서버가 TLS 악수 전에 닫는다 (Task 3). 루프백은 늘 허용.
- 믿을 프록시 목록이 비면 X-Forwarded-* 를 읽지 않는다 (Task 5). web_plain(프록시가 TLS 를 끝내고 평문으로 넘기는 모양)은
  같은 장비의 프록시(127.0.0.1)만 - 장비 사이에 평문 구간을 만들지 않는다.
- 모르는 칸은 거절한다 (오타를 조용히 넘기지 않게). 이름 풀이(DNS)는 하지 않는다 - 주소는 모두 IP 글자.
표준 라이브러리만.
"""
import ipaddress
import json
import re
from dataclasses import dataclass, field

import lan_ca                    # 이름 규칙은 인증서 발급과 같은 것 (②검-9 - lan_ca._dns)

DEFAULT_PORTS = {"web": 8443, "agent": 8444, "phone": 8782}
PORT_MIN = 1024                  # 1024 아래 포트는 특권이 필요하다 - 쓰지 않는다
PORT_MAX = 65535
KEYS = ("listen", "names", "ports", "allow", "trusted_proxies", "proxy_only", "web_plain", "public_web", "bind_session_ip",
        "backup_hour", "proxy_secret")
BACKUP_HOUR = 3                  # 하루 한 번 서비스 안 백업을 뜨는 시 (서버 시각, 사내 서버 ④ Task 5)
SINGLE_LABEL_OK = ("localhost",)  # 점 없는 이름 가운데 받는 것 - 이름 제한 'localhost' 는 루프백 이름만 연다 (RFC 6761)
SECRET_RE = re.compile(r"[A-Za-z0-9._~+/=-]{32,256}")      # 평문 프록시 비밀 값 (머리글에 그대로 싣는 글자만)
PROXY_HEADER = "X-Autopilot-Proxy"                         # 같은 장비 평문 프록시가 proxy_secret 을 싣는 머리글 (Codex 검토 13)
PUBLIC_RE = re.compile(r"[A-Za-z0-9.-]{1,253}(:\d{1,5})?")   # 프록시가 내건 이름 (포트 붙여도 됨)

# 사설·루프백 대역 (RFC 1918, IPv6 ULA fc00::/7, 루프백). 이 밖은 공인·링크 로컬·특수 대역으로 본다.
PRIVATE_NETS = tuple(ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8",
    "fc00::/7", "::1/128",
))


class ConfigError(ValueError):
    """server.json 이 없거나 틀렸다. 까닭은 한국어로 - 관리자가 그대로 읽는다."""


def _ip(text):
    """IP 글자 → 주소 객체 (IPv4 를 담은 IPv6 는 IPv4 로). 주소가 아니면 None."""
    if not isinstance(text, str):
        return None
    try:
        a = ipaddress.ip_address(text)
    except ValueError:
        return None
    if a.version == 6 and a.ipv4_mapped is not None:
        return a.ipv4_mapped
    return a


def _private_ip(a):
    return any(a.version == n.version and a in n for n in PRIVATE_NETS)


def _private_net(net):
    return any(net.version == n.version and net.subnet_of(n) for n in PRIVATE_NETS)


def _host(name, port):
    """Host 머리글 꼴. IPv6 글자는 대괄호."""
    return f"[{name}]:{port}" if ":" in name else f"{name}:{port}"


@dataclass(frozen=True)
class LanConfig:
    listen: str
    names: tuple
    web_port: int
    agent_port: int
    phone_port: int
    allow: tuple
    trusted_proxies: tuple
    proxy_only: bool
    web_plain: bool
    public_web: tuple
    bind_session_ip: bool
    backup_hour: int = BACKUP_HOUR
    proxy_secret: str = field(default=None, repr=False)     # 평문 프록시 비밀 값 - repr·기록에 싣지 않는다

    @property
    def web_listen(self):
        """웹 포트가 들을 주소 - 평문 프록시 모양이면 같은 장비의 프록시만 붙게 127.0.0.1."""
        return "127.0.0.1" if self.web_plain else self.listen

    def web_hosts(self):
        """웹 포트가 받을 Host 머리글 (소문자) - 이름마다 '이름:웹 포트' + 프록시가 내건 공개 이름."""
        return frozenset([_host(n, self.web_port).lower() for n in self.names] + [p.lower() for p in self.public_web])

    def agent_hosts(self):
        """에이전트 포트가 받을 Host 머리글 (소문자)."""
        return frozenset(_host(n, self.agent_port).lower() for n in self.names)

    def allowed(self, ip):
        """이 주소에서 온 연결을 받나 - 루프백은 늘, 그 밖은 허용 대역 안일 때만. 주소가 아니면 거짓."""
        a = _ip(ip)
        if a is None:
            return False
        if a.is_loopback:
            return True
        return any(a.version == n.version and a in n for n in self.allow)

    def is_proxy(self, ip):
        """믿을 프록시 주소인가. 주소가 아니면 거짓."""
        a = _ip(ip)
        if a is None:
            return False
        return any(a.version == n.version and a in n for n in self.trusted_proxies)


# ----------------------------------------------------------------------------------------------------
# 검사
# ----------------------------------------------------------------------------------------------------

def _list(data, key):
    v = data.get(key, [])
    if not isinstance(v, list):
        raise ConfigError(f"{key} 는 목록이어야 합니다")
    return v


def _bool(data, key, default):
    v = data.get(key, default)
    if not isinstance(v, bool):
        raise ConfigError(f"{key} 는 true 나 false 여야 합니다")
    return v


def _listen(v):
    if not isinstance(v, str) or not v:
        raise ConfigError("listen 에 서버가 들을 사내 IP 주소를 적어야 합니다")
    a = _ip(v)
    if a is None or "%" in v:
        raise ConfigError(f"listen 은 IP 주소여야 합니다 (이름·대역 안 됨): {v}")
    if not _private_ip(a):
        raise ConfigError(f"listen 은 사설 주소나 127.0.0.1 이어야 합니다 (0.0.0.0·공인·링크 로컬 주소 안 됨): {v}")
    return str(a)


def _names(raw, listen):
    """서버 인증서 이름. 인증서 발급(lan_ca._dns)과 같은 규칙 - 조각마다 영문·숫자·하이픈(앞뒤 하이픈 없음), 빈 조각 없음.
    점 없는 이름(nt·kr)은 받지 않는다 - 인증 기관의 이름 제한이 그 아래 모든 이름에 걸린다 (localhost 만 예외).
    IP 는 사설·루프백만 (②검-9)."""
    out = [listen]
    for n in raw:
        if not isinstance(n, str):
            raise ConfigError(f"names 의 값은 글자여야 합니다: {n!r}")
        a = _ip(n)
        if a is not None and "%" not in n:
            if not _private_ip(a):
                raise ConfigError(f"names 의 IP 는 사설·루프백 주소만 적을 수 있습니다: {n}")
            n = str(a)
        else:
            d = lan_ca._dns(n)
            if d is None:
                raise ConfigError(f"names 의 이름은 영문·숫자·하이픈 조각을 점으로 이은 253자 이내나 IP 주소여야 합니다: {n!r}")
            if "." not in d and d not in SINGLE_LABEL_OK:
                raise ConfigError(f"names 에는 점이 든 이름을 적어 주십시오 (예: autopilot.corp.local). 점 없는 이름은 받지 않습니다: {n!r}")
            n = d
        n = n.lower()
        if n not in out:
            out.append(n)
    return tuple(out)


def _ports(v):
    if v is None:
        v = {}
    if not isinstance(v, dict):
        raise ConfigError("ports 는 {\"web\": 8443, \"agent\": 8444, \"phone\": 8782} 꼴이어야 합니다")
    extra = sorted(set(v) - set(DEFAULT_PORTS))
    if extra:
        raise ConfigError(f"ports 에 모르는 칸이 있습니다: {', '.join(map(str, extra))}")
    out = {}
    for k, d in DEFAULT_PORTS.items():
        p = v.get(k, d)
        if type(p) is not int or not PORT_MIN <= p <= PORT_MAX:
            raise ConfigError(f"ports.{k} 는 {PORT_MIN}~{PORT_MAX} 사이 숫자여야 합니다: {p!r}")
        out[k] = p
    if len(set(out.values())) != len(out):
        raise ConfigError("ports 의 웹·에이전트·휴대폰 포트는 서로 달라야 합니다")
    return out


def _nets(raw, key):
    out = []
    for t in raw:
        if not isinstance(t, str) or "%" in t:
            raise ConfigError(f"{key} 의 값은 IP 주소나 대역 글자여야 합니다: {t!r}")
        try:
            net = ipaddress.ip_network(t, strict=False)
        except ValueError:
            raise ConfigError(f"{key} 의 값은 IP 주소나 대역 글자여야 합니다: {t!r}") from None
        if not _private_net(net):
            raise ConfigError(f"{key} 에는 사설·루프백 대역만 적을 수 있습니다: {t}")
        out.append(net)
    return tuple(out)


def _public(raw):
    out = []
    for p in raw:
        if not isinstance(p, str) or not PUBLIC_RE.fullmatch(p):
            raise ConfigError(f"public_web 의 값은 '이름' 이나 '이름:포트' 꼴이어야 합니다: {p!r}")
        out.append(p.lower())
    return tuple(out)


def parse(data):
    """server.json 의 내용(dict) → LanConfig. 틀리면 ConfigError."""
    if not isinstance(data, dict):
        raise ConfigError("server.json 은 { } 로 묶인 설정이어야 합니다")
    extra = sorted(set(data) - set(KEYS))
    if extra:
        raise ConfigError(f"server.json 에 모르는 칸이 있습니다 (오타인지 보세요): {', '.join(map(str, extra))}")
    if "listen" not in data:
        raise ConfigError("server.json 에 listen(서버가 들을 사내 IP 주소)이 없습니다")
    listen = _listen(data["listen"])
    names = _names(_list(data, "names"), listen)
    ports = _ports(data.get("ports"))
    allow = _nets(_list(data, "allow"), "allow")
    proxies = _nets(_list(data, "trusted_proxies"), "trusted_proxies")
    proxy_only = _bool(data, "proxy_only", False)
    web_plain = _bool(data, "web_plain", False)
    bind = _bool(data, "bind_session_ip", True)
    public = _public(_list(data, "public_web"))
    hour = data.get("backup_hour", BACKUP_HOUR)
    if type(hour) is not int or not 0 <= hour <= 23:
        raise ConfigError(f"backup_hour 는 0~23 사이 숫자여야 합니다 (하루 한 번 백업을 뜨는 시): {hour!r}")
    secret = data.get("proxy_secret")
    if secret is not None and (not isinstance(secret, str) or not SECRET_RE.fullmatch(secret)):
        raise ConfigError("proxy_secret 은 32~256자의 영문·숫자(그리고 . _ ~ + / = -)여야 합니다")
    if not _ip(listen).is_loopback and not allow:
        # 비우면 루프백만 붙어 아무 PC 도 못 붙는다 - 조용히 넘기지 않는다 (②검-3)
        raise ConfigError("허용 대역(allow)을 적어 주십시오 - 서버에 붙을 PC 들의 사내 대역 (예: [\"192.168.1.0/24\"])")
    c = LanConfig(listen=listen, names=names, web_port=ports["web"], agent_port=ports["agent"], phone_port=ports["phone"],
                  allow=allow, trusted_proxies=proxies, proxy_only=proxy_only, web_plain=web_plain,
                  public_web=public, bind_session_ip=bind, backup_hour=hour, proxy_secret=secret)
    if proxy_only and not proxies:
        raise ConfigError("proxy_only 를 켜려면 trusted_proxies 에 프록시 주소를 적어야 합니다")
    if proxy_only:
        loop = [n for n in PRIVATE_NETS if n.network_address.is_loopback]
        for p in proxies:
            if not any(p.version == n.version and p.subnet_of(n) for n in tuple(allow) + tuple(loop)):
                # 받기 고리가 allow 밖 주소를 닫으므로 그 프록시도, 그 뒤의 누구도 붙지 못한다 (②검-10)
                raise ConfigError(f"proxy_only 의 trusted_proxies 는 허용 대역(allow) 안이나 루프백이어야 합니다: {p}")
    if web_plain and not c.is_proxy("127.0.0.1"):
        raise ConfigError("web_plain 은 같은 장비의 프록시만 됩니다 - trusted_proxies 에 127.0.0.1 을 적어야 합니다")
    if web_plain and not secret:
        # 같은 장비의 다른 리눅스 계정이 프록시 행세를 하지 못하게 (Codex 검토 13)
        raise ConfigError(f"web_plain 을 켜려면 proxy_secret(32자 이상의 비밀 값)을 적고, 프록시가 {PROXY_HEADER} 머리글로 "
                          "그 값을 보내게 하여 주십시오")
    return c


def load(path):
    """server.json 파일 → LanConfig. 파일이 없거나 JSON 이 아니거나 검사에 걸리면 ConfigError."""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            text = f.read()
    except FileNotFoundError:
        raise ConfigError(f"설정 파일이 없습니다: {path}") from None
    except UnicodeDecodeError:
        raise ConfigError(f"설정 파일이 UTF-8 이 아닙니다: {path}") from None
    except OSError as e:
        raise ConfigError(f"설정 파일을 읽지 못했습니다: {path} ({e.strerror or e})") from None
    try:
        data = json.loads(text)
    except ValueError as e:
        raise ConfigError(f"설정 파일이 JSON 꼴이 아닙니다: {path} ({getattr(e, 'lineno', '?')}번째 줄)") from None
    return parse(data)
