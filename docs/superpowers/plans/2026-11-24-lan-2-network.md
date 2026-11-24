# 사내 서버 ② 사내망 창구 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사내 서버가 사내 주소에서 브라우저 창구(8443)와 에이전트 창구(8444)를 TLS 로 따로 열고, 허용 대역·Host·Origin·주소별 제한·로그인 잠금·믿을 프록시 주소로 사내망 밖과 남용을 막는다. 에이전트는 우리 인증 기관 하나만 믿고 붙는다.

**Architecture:** ① 의 `Store`·`Runs`·`Registry`·`Handler`·`Web` 을 그대로 쓰고, 새 모듈 셋이 사내망 겉을 씌운다: `lan_config`(server.json 읽기·검사), `lan_ca`(openssl 명령으로 인증 기관·서버 인증서), `lan_server`(허용 대역·연결 수·TLS 악수를 받기 전에 거르는 `LanServer` 와 두 포트를 만드는 `make_lan_servers`). `Handler` 는 서버의 `side`("both"·"web"·"agent")로 길을 막고, 보낸 쪽 주소는 `Handler.client_ip()` 한 곳에서 읽는다. 단독(나)은 `side="both"`·http·127.0.0.1 그대로.

**Tech Stack:** 파이썬 3.14 표준 라이브러리(`ssl`, `ipaddress`, `socketserver`), 인증서는 `openssl` 명령 (리눅스 서버의 것, 개발 PC 시험은 Git 의 `C:\Program Files\Git\usr\bin\openssl.exe`), 시험은 저장소 관례 plain python + WSL(Ubuntu, 파이썬 3.14.4, OpenSSL 3.5.5) 하나.

**Spec:** `docs/superpowers/specs/2026-11-24-standalone-linux-server-design.md` 6.3 (HTTPS·포트·방화벽·프록시), 6.4 끝줄(주소별 제한), 6.6 '사내망으로 넓어지며 더 막는 것', 13절 4·8·11. ① 검토에서 ② 로 넘긴 것: `docs/superpowers/plans/2026-11-24-lan-index.md` 의 M-3·M-4·M-6·M-7·M-9·M-10·M-11·보류 2.

## Global Constraints

- 작업 폴더 `D:\AX\RPA_StandAlone`, 브랜치 `StandAlone`. 파이썬 `D:\AX\RPA\.venv\Scripts\python.exe`. `D:\AX\RPA` 의 파일은 절대 고치지 않는다 - 경로는 늘 `D:\AX\RPA_StandAlone\...` 절대 경로로.
- 단독(나)은 그대로: `make_server(...)`(registry 없음)의 응답·상수·검사가 지금과 같고 시험 전체가 통과해야 한다. 이 PC 의 방화벽·레지스트리·인증서 저장소는 건드리지 않는다 (시험 서버는 127.0.0.1 에서만).
- 서버 코드는 표준 라이브러리만, 바깥 연결을 여는 코드 없음, 이름 풀이(DNS)를 하지 않는다 (설계 8절). `openssl` 은 자식 프로세스로만 부르고 인자는 목록으로 (셸 없음), 30초 제한.
- 숫자 (설계·Claude 판단): 포트 기본 웹 8443·에이전트 8444·휴대폰 8782, 1024 아래 포트 거절. TLS 1.2 이상, 악수 5초. 인증 기관 3650일, 서버 인증서 397일(브라우저 상한 398일 안). 주소마다 동시 연결 16, 분당 요청 600, 서명 틀림 60초에 20번이면 그 주소 300초 거절. 로그인: 주소마다 10분에 10번 틀리면 그 주소 10분 거절, 같은 아이디가 잇따라 잠기면 60초 → 300초 → 900초 (성공하면 처음으로). 등록부 번호 상한 `pc_9999`.
- 기록에 열쇠·토큰·서명·인증 기관 열쇠·비밀번호를 싣지 않는다. 인증 기관 열쇠 파일은 서버 인증서와 다른 폴더(`ca_dir`)에 둔다 (④ 가 root 전용 폴더로 옮긴다).
- 화면 글은 한국어 업무 말투, '버전', '묶음' 금지. 커밋은 작업마다 `git commit -F <새 파일 이름>` (메시지 파일 이름은 작업마다 새로 - 지난 파일을 덮어 쓰다 실패하면 옛 메시지가 붙는다), BOM 없이, 끝줄 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. push 는 사용자 말이 있을 때만.
- 끝나면 `graphify update .` (작업 폴더에서).

## Review Focus

1. 프록시를 거치지 않은 연결이 `X-Forwarded-For` 를 지어 보내 잠금·이력·세션 주소를 속이는 경우 - 믿을 프록시 목록 밖이면 머리글을 버린다 (Task 5 `test_forged_xff_ignored`).
2. 허용 대역 밖 주소의 연결 - TLS 악수 전에 닫혀 서버 인증서도 받지 못한다 (Task 3 `test_outside_allow_closed_before_tls`).
3. 악수를 끝내지 않거나 한 바이트씩 보내는 연결이 받기 고리·스레드를 잡는 경우 - 5초에 끊기고 다른 연결은 계속 된다 (Task 3 `test_slow_handshake_cut`).
4. 인증 기관의 이름 제한 밖 이름으로 만든 인증서 - 에이전트 클라이언트가 거절한다 (Task 2 `test_name_constraints_enforced`).
5. 웹 포트에 에이전트 주소(/db·/enroll)를, 에이전트 포트에 /api·웹 파일을 보내는 경우 - 둘 다 404, 서로의 길이 섞이지 않는다 (Task 4 `test_ports_do_not_mix`).

---

## 파일

| 파일 | 맡는 일 |
|---|---|
| 새 `firebase/agent/lan_config.py` | `server.json` 읽기·검사 → `LanConfig` |
| 새 `firebase/agent/lan_ca.py` | openssl 찾기, 인증 기관(이름 제한) 만들기, 서버 인증서 발급, 만료일 읽기 |
| 새 `firebase/agent/lan_server.py` | `LanServer`(허용 대역·주소별 연결·분당 요청·TLS 악수를 일하는 스레드에서·서명 틀림 거절), `client_ip`, `make_lan_servers` |
| `firebase/agent/local_server.py` | `Handler` 의 `side` 막기, `client_ip()`, Host 검사 자리, 서명 없는 답의 `Date` 빼기, ① 미룬 것 |
| `firebase/agent/local_web.py` | Host·Origin 을 설정 목록으로, 주소별 로그인 잠금·아이디 잠금 늘리기, 세션 주소 묶기, HSTS, 프록시 평문 모양 검사, 등록 글에 인증 기관 |
| `firebase/agent/local_store.py` | https + 우리 인증 기관만 믿는 연결, 사설 주소 규칙, `enroll` 의 인증 기관 |
| `firebase/agent/pc_registry.py` | 등록 글의 `ca` 칸, 번호 상한 |
| `tools/build_release.py` | 배포 목록에 새 모듈 셋 (한 줄씩) |
| 새 `tests/test_lan_config.py`, `tests/test_lan_ca.py`, `tests/test_lan_net.py`, `tests/test_lan_tls.py`, `tests/wsl_lan_smoke.py` | 이 계획의 시험 |

---

### Task 1: `lan_config` - server.json

**Files:**
- Create: `firebase/agent/lan_config.py`, `tests/test_lan_config.py`

**Interfaces:**
- Produces:
  - `class ConfigError(ValueError)` (한국어 까닭)
  - `@dataclass(frozen=True) class LanConfig: listen: str; names: tuple[str, ...]; web_port: int; agent_port: int; phone_port: int; allow: tuple[ipaddress.IPv4Network | IPv6Network, ...]; trusted_proxies: tuple[...]; proxy_only: bool; web_plain: bool; public_web: tuple[str, ...]; bind_session_ip: bool`
  - `LanConfig.web_listen -> str` (`web_plain` 이면 `"127.0.0.1"`, 아니면 `listen`), `web_hosts() -> frozenset[str]` (`f"{n}:{web_port}"` 모두 + `public_web`, 소문자), `agent_hosts() -> frozenset[str]` (`f"{n}:{agent_port}"`), `allowed(ip: str) -> bool` (허용 대역 안, 루프백은 늘 허용), `is_proxy(ip: str) -> bool`
  - `parse(data: dict) -> LanConfig`, `load(path: str) -> LanConfig` (파일이 없거나 JSON 이 아니면 `ConfigError`)
  - server.json 꼴: `{"listen": "192.168.1.230", "names": ["nt"], "ports": {"web": 8443, "agent": 8444, "phone": 8782}, "allow": ["192.168.1.0/24"], "trusted_proxies": [], "proxy_only": false, "web_plain": false, "public_web": [], "bind_session_ip": true}` - `listen` 만 꼭 있어야 하고 나머지는 이 기본값.
  - 검사: `listen` 은 IP 글자(이름 아님)이고 사설·루프백 (`0.0.0.0`·`::`·공인 주소 거절). `names` 는 `[A-Za-z0-9.-]{1,253}` 또는 IP 글자, `listen` 은 늘 들어간다. 포트는 1024~65535 이고 셋이 서로 다르다. `allow` 는 사설·루프백 대역만 (공인 대역 거절, `strict=False`). `trusted_proxies` 는 IP·대역 글자. `web_plain` 은 `trusted_proxies` 에 `127.0.0.1` 이 있어야 한다. `proxy_only` 는 `trusted_proxies` 가 비어 있으면 거절. 모르는 칸은 거절 (오타를 조용히 넘기지 않게).

- [ ] **Step 1: 실패하는 시험** `tests/test_lan_config.py`

```python
def test_minimal():
    c = lan_config.parse({"listen": "192.168.1.230"})
    check("기본 포트", (c.web_port, c.agent_port, c.phone_port) == (8443, 8444, 8782))
    check("listen 은 names 에 들어간다", "192.168.1.230" in c.names)
    check("웹 Host 목록", c.web_hosts() == frozenset({"192.168.1.230:8443"}))
    check("허용 대역이 비면 루프백만", c.allowed("127.0.0.1") and not c.allowed("192.168.1.5"))
def test_rejects():
    for bad in ({"listen": "0.0.0.0"}, {"listen": "8.8.8.8"}, {"listen": "nt.local"}, {"listen": "192.168.1.2", "allow": ["0.0.0.0/0"]},
                {"listen": "192.168.1.2", "ports": {"web": 443}}, {"listen": "192.168.1.2", "ports": {"web": 8444}},
                {"listen": "192.168.1.2", "web_plain": True}, {"listen": "192.168.1.2", "proxy_only": True},
                {"listen": "192.168.1.2", "lisen": 1}, {"listen": "192.168.1.2", "names": ["a b"]}):
        check(f"거절 {bad}", raises_config(lambda: lan_config.parse(bad)))
def test_proxy_fields():
    c = lan_config.parse({"listen": "10.0.0.5", "allow": ["10.0.0.0/8"], "trusted_proxies": ["10.0.0.9"], "public_web": ["Autopilot.corp.local"]})
    check("믿을 프록시", c.is_proxy("10.0.0.9") and not c.is_proxy("10.0.0.10"))
    check("공개 이름은 소문자로 웹 Host 목록에", "autopilot.corp.local" in c.web_hosts())
    p = lan_config.parse({"listen": "10.0.0.5", "trusted_proxies": ["127.0.0.1"], "web_plain": True})
    check("평문 모양이면 웹은 127.0.0.1 에서", p.web_listen == "127.0.0.1")
def test_load_file():
    # 없는 파일·JSON 아님 → ConfigError, 맞는 파일 → LanConfig
```
- [ ] **Step 2:** `D:\AX\RPA\.venv\Scripts\python.exe tests\test_lan_config.py` → `ModuleNotFoundError`.
- [ ] **Step 3:** 위 Interfaces 대로 쓴다.
- [ ] **Step 4:** 같은 명령 → 통과.
- [ ] **Step 5: 커밋** - `사내 서버 ② Task 1 - server.json 읽기·검사 lan_config (사설 주소에만 듣기, 포트·허용 대역·믿을 프록시·평문 프록시 모양)`

---

### Task 2: `lan_ca` - 우리 인증 기관과 서버 인증서

**Files:**
- Create: `firebase/agent/lan_ca.py`, `tests/test_lan_ca.py`

**Interfaces:**
- Produces:
  - `class CaError(Exception)`, 파일 이름 `CA_CERT = "ca_cert.pem"`, `CA_KEY = "ca_key.pem"`, `SERVER_CERT = "server_cert.pem"`, `SERVER_KEY = "server_key.pem"`, `CA_DAYS = 3650`, `SERVER_DAYS = 397`
  - `find_openssl() -> str` - `shutil.which("openssl")`, 없으면 윈도우에서 `C:\Program Files\Git\usr\bin\openssl.exe`·`C:\Program Files\Git\mingw64\bin\openssl.exe`. 없으면 `CaError`. 환경 변수로 길을 바꾸지 않는다 (설치본은 시험용 환경 변수를 무시한다).
  - `make_ca(ca_dir, names, ips, openssl=None) -> str` - 이미 `ca_cert.pem`·`ca_key.pem` 이 있고 쓸 수 있으면 그대로 (자리를 돌려줌). 없으면 P-256 열쇠, CN "AUTOPILOT LAN CA", `basicConstraints=critical,CA:TRUE,pathlen:0`, `keyUsage=critical,keyCertSign,cRLSign`, **`nameConstraints=critical,permitted;DNS:<이름>…,permitted;IP:<ip>/255.255.255.255…`** (IPv6 는 /128). 리눅스에서는 열쇠 파일을 0600 으로.
  - `issue_server(ca_dir, out_dir, names, ips, days=SERVER_DAYS, openssl=None) -> tuple[str, str]` - 새 P-256 열쇠와 인증서 (SAN = DNS 이름들 + IP 들, `extendedKeyUsage=serverAuth`, `basicConstraints=critical,CA:FALSE`), 임시 이름으로 쓰고 `os.replace`. 리눅스에서 열쇠 0600.
  - `ca_pem(ca_dir) -> str`, `days_left(cert_path, now=None) -> int` (`ssl._ssl._test_decode_cert` 대신 `openssl x509 -enddate -noout` 을 읽는다)
  - openssl 설정은 임시 폴더의 설정 파일로 넘긴다 (`-config`, `-extfile`), 셸 없이 목록 인자, 30초.

- [ ] **Step 1: 실패하는 시험** `tests/test_lan_ca.py` - 임시 폴더, `ssl` 로 실제 연결해 본다 (127.0.0.1 에 `ssl.SSLContext(PROTOCOL_TLS_SERVER)` 하나 띄우는 작은 도우미).
  - `test_make_ca_and_server` - CA 와 서버 인증서(이름 `nt`, IP `127.0.0.1`)를 만들고, `ssl.create_default_context(cadata=ca_pem)` 클라이언트가 `server_hostname="127.0.0.1"` 로 붙으면 악수 성공. 윈도우 신뢰 저장소를 쓰지 않는 기본 컨텍스트(`ssl.create_default_context()`)는 실패.
  - `test_name_constraints_enforced` - 같은 CA 열쇠로 이름 제한 밖 SAN(`DNS:evil.example`)의 인증서를 openssl 로 직접 서명해 서버에 걸면 `cadata=ca_pem` 클라이언트가 `ssl.SSLCertVerificationError`.
  - `test_make_ca_keeps_existing` - 두 번 부르면 같은 `ca_cert.pem` 내용.
  - `test_days_left` - 새 서버 인증서는 396~397.
  - `test_key_never_in_cert_dir` - `issue_server` 의 out_dir 에 `ca_key.pem` 이 없다.
- [ ] **Step 2:** `D:\AX\RPA\.venv\Scripts\python.exe tests\test_lan_ca.py` → 실패.
- [ ] **Step 3:** 구현.
- [ ] **Step 4:** 통과.
- [ ] **Step 5: 커밋** - `사내 서버 ② Task 2 - 우리 인증 기관 lan_ca (openssl 명령, 이 서버 이름·주소만 서명하게 이름 제한, 서버 인증서 397일)`

---

### Task 3: `LanServer` - 받기 전에 거르기와 TLS 악수

**Files:**
- Create: `firebase/agent/lan_server.py`, `tests/test_lan_net.py`

**Interfaces:**
- Consumes: Task 1 `LanConfig`, Task 2 인증서 파일, ① `local_server.LocalServer`·`Handler`
- Produces:
  - 상수 `PER_IP_CONN = 16`, `PER_IP_MIN = 600`, `HANDSHAKE_SEC = 5`, `BAD_LIMIT = 20`, `BAD_WINDOW = 60`, `BAD_BLOCK = 300`, `TRACK_MAX = 5000`
  - `tls_context(cert, key) -> ssl.SSLContext` - 서버, 1.2 이상, 1.2 는 `ECDHE+AESGCM:ECDHE+CHACHA20`, 재협상 끔 (`local_phone.tls_context` 와 같은 꼴)
  - `class LanServer(local_server.LocalServer)` - 생성 인자는 부모와 같고 만든 뒤 `srv.cfg`, `srv.tls`(None 이면 평문 - `web_plain` 의 웹 포트뿐), `srv.side` 를 단다. `process_request` 가 **받기 고리에서** 보낸 쪽 소켓 주소로 ① `cfg.allowed` (+ `side=="web" and cfg.proxy_only` 면 `cfg.is_proxy`) ② 서버 전체 `deploy.max_conn` ③ 주소별 동시 연결 ④ 주소별 분당 요청 ⑤ `blocked(ip)` 을 보고, 하나라도 걸리면 응답 없이 닫는다. 통과하면 일하는 스레드에서 `HANDSHAKE_SEC` 타이머와 함께 `tls.wrap_socket(server_side=True)` 뒤 부모의 처리로. 표 정리는 `local_phone.PhoneServer._trim` 과 같은 방식.
  - `LanServer.peer_ip(client_address) -> str` (시험이 바꿔 끼운다), `note_bad(ip)`, `blocked(ip) -> bool` (시계는 `time.monotonic`)
  - `client_ip(peer: str, xff: str | None, cfg: LanConfig) -> str` - `peer` 가 믿을 프록시가 아니면 `peer`. 믿을 프록시면 `X-Forwarded-For` 를 쉼표로 나눠 오른쪽부터 읽어 믿을 프록시가 아닌 첫 IP 글자 (글자가 IP 가 아니면 `peer`). 머리글이 없으면 `peer`.

- [ ] **Step 1: 실패하는 시험** `tests/test_lan_net.py` (Task 2 의 CA 로 127.0.0.1 서버 인증서를 만들어 `LanServer` 를 `side="agent"`·registry 하나로 띄운다)
  - `test_outside_allow_closed_before_tls` - `peer_ip` 를 `"203.0.113.9"` 로 바꿔 끼우면 TLS 악수가 실패하고(`ssl.SSLError`·`ConnectionError`) 서버 인증서를 받지 못한다. 허용 주소면 악수 성공.
  - `test_slow_handshake_cut` - 원시 소켓으로 붙어 아무것도 보내지 않으면 6초 안에 서버가 닫고, 그동안 다른 클라이언트의 요청은 2초 안에 답을 받는다.
  - `test_per_ip_conn_cap` - 같은 주소로 열어 둔 연결 16개 뒤 17번째는 바로 닫힌다, 하나 닫으면 다시 된다 (`until` 로).
  - `test_bad_signature_block` - 서명 틀린 요청 20번 뒤 그 주소의 새 연결은 닫힌다 (Task 4 가 `note_bad` 를 부르기 전이므로 여기서는 `srv.note_bad` 를 직접 20번 불러 본다).
  - `test_client_ip` - 프록시 없음: 머리글 무시. 프록시 `10.0.0.9`: `"1.2.3.4, 10.0.0.7"` 에서 `10.0.0.7` (믿을 프록시 아님), 프록시 둘 `10.0.0.9,10.0.0.8`: `"10.0.0.7, 10.0.0.8"` → `10.0.0.7`, 글자가 IP 아님 → peer.
- [ ] **Step 2:** 실행 → 실패.
- [ ] **Step 3:** 구현.
- [ ] **Step 4:** 통과.
- [ ] **Step 5: 커밋** - `사내 서버 ② Task 3 - LanServer: 허용 대역·주소별 연결·분당 요청·서명 틀림 거절을 받기 전에, TLS 악수는 일하는 스레드에서 5초, 믿을 프록시로 보낸 쪽 주소`

---

### Task 4: 두 포트 - 웹 8443·에이전트 8444

**Files:**
- Modify: `firebase/agent/local_server.py` (`Handler._route`·`_role`·`_role_lan`·`_reply`, `local_host`), `firebase/agent/lan_server.py` (`make_lan_servers`), `firebase/agent/pc_registry.py` (등록 글 `ca`), `tools/build_release.py`
- Test: 새 `tests/test_lan_tls.py`

**Interfaces:**
- Consumes: Task 1~3
- Produces:
  - `local_server.Handler.client_ip() -> str` - 서버에 `cfg` 가 있으면 `lan_server.client_ip(소켓 주소, X-Forwarded-For, cfg)` (웹 쪽만 프록시를 믿는다, 에이전트 쪽은 늘 소켓 주소), 없으면 소켓 주소.
  - `local_server.host_ok(headers, server) -> bool` - `server.cfg` 가 있으면 Host 가 `side` 에 맞는 목록(`web_hosts()`·`agent_hosts()`)에 있어야 한다 (소문자로 견줌), 없으면 지금 `local_host`. 단독은 지금 함수 그대로.
  - `Handler._route`: `srv.side == "web"` 이면 웹 창구만 (`/db`·`/fs`·`/fs-sum`·`/enroll` 은 404), `"agent"` 면 에이전트 길만 (`/api/*`·웹 파일 GET 은 404 - `web.handle` 을 부르지 않는다), `"both"` 는 지금 그대로.
  - 에이전트 포트에서 서명이 틀린 요청(서명 없는 401)과 `/enroll` 의 `bad_proof` 는 `srv.note_bad(client_ip)` 를 부른다 (Task 3 의 거절로 이어진다).
  - ① 미룬 M-4: 서명 없는 답(401·403·404 등 `self._auth` 가 없을 때)에는 `Date` 머리글을 싣지 않는다 (`send_response` 대신 `send_response_only` + 필요한 머리글). 서명된 답은 지금처럼 `Date` 를 싣는다 (`local_store.Client._seen` 이 쓴다).
  - `pc_registry.encode_enrollment`·`decode_enrollment`: 선택 칸 `"ca"`(인증 기관 PEM 글). `url` 이 `https://` 면 `ca` 가 꼭 있어야 한다 (`ValueError`).
  - `lan_server.make_lan_servers(store, runs, lic, registry, web, cfg, cert, key, ca_pem, phone=None) -> tuple[LanServer, LanServer]` - (웹, 에이전트). 둘 다 같은 `store`·`runs`·`registry`, 각각 `side`. 웹: `cfg.web_listen:cfg.web_port`, `tls=None if cfg.web_plain else tls_context(cert, key)`. 에이전트: `cfg.listen:cfg.agent_port`, 늘 TLS. `web.public_url = f"https://{cfg.listen}:{cfg.agent_port}"` (이름이 아니라 IP - 사내 PC 가 이름을 못 풀어도 붙고, 서버 인증서 SAN 에 늘 있다), `web.lan_ca_pem = ca_pem` (등록 글에 싣는다), `web.cfg = cfg`. `LocalServer` 의 `make_server` 가 하던 `deploy=LAN`·`conn_lock`·`nonces`·`streams` 준비는 같은 도우미로 (중복 없이 - `local_server._prepare(srv, ...)` 로 빼낸다).
  - `local_web.Web` 의 PC 추가 처리(`POST /api/pcs`)는 등록 글에 `"ca": self.lan_ca_pem` 을 싣는다 (`lan_ca_pem` 은 `Web.__init__` 에서 None, None 이면 칸 없음 - ① 의 시험 그대로).
  - `tools/build_release.py` 배포 목록에 `lan_config.py`·`lan_ca.py`·`lan_server.py` 세 줄.

- [ ] **Step 1: 실패하는 시험** `tests/test_lan_tls.py` - Task 2 로 CA·서버 인증서(이름 `localhost`, IP `127.0.0.1`), `LanConfig(listen="127.0.0.1", allow=["127.0.0.0/8"])`, 포트 0 둘. 클라이언트는 `ssl.create_default_context(cadata=ca_pem)` + `urllib` (프록시 없이).
  - `test_ports_do_not_mix` - 웹 포트의 `GET /db/apps/rpa/live/c1/pc_01.json`·`POST /enroll` → 404, 에이전트 포트의 `GET /api/session`·`GET /index.html` → 404.
  - `test_https_only` - 두 포트에 평문 http 로 보내면 답 없이 끊긴다.
  - `test_host_checked` - 웹 포트에 `Host: evil.example:8443` → 403, 맞는 Host 는 로그인 화면 파일 200. 에이전트 포트에 웹 포트 번호의 Host → 401/403 (서명 확인 전 Host 거절).
  - `test_enroll_over_tls_with_ca` - 관리자가 `/api/pcs` 로 추가한 등록 글에 `ca` 가 있고 `url` 이 `https://127.0.0.1:<에이전트 포트>`, 그 글로 등록 → 현황 PATCH 200 (Task 5 의 클라이언트가 아직이면 이 시험은 `[보류]` 로 찍고 넘어간다 - Task 5 에서 켠다).
  - `test_unsigned_reply_has_no_date` - 서명 없는 401 에 `Date` 머리글이 없다, 서명된 200 에는 있다 (단독 서버에서도 같은 결과).
  - `test_bad_signature_blocks_ip` - 에이전트 포트에 서명 틀린 요청 20번 → 21번째 연결은 끊긴다.
- [ ] **Step 2:** 실행 → 실패.
- [ ] **Step 3:** 구현.
- [ ] **Step 4:** `tests\test_lan_tls.py`, `tests\test_lan_server.py`, `tests\test_lan_web.py`, `tests\test_lan_e2e.py`, `tests\test_local_server_http.py`, `tests\test_program_files_imports.py`, `tests\test_build_release.py` 통과.
- [ ] **Step 5: 커밋** - `사내 서버 ② Task 4 - 두 포트(웹 8443·에이전트 8444) TLS, 서로의 길 막기, Host 를 설정 목록으로, 서명 틀림·등록 증명 틀림은 주소 거절로, 서명 없는 답엔 서버 시각 없음, 등록 글에 인증 기관`

---

### Task 5: 에이전트 클라이언트 - 우리 인증 기관만 믿기

**Files:**
- Modify: `firebase/agent/local_store.py`
- Test: `tests/test_local_store_client.py` (끝에 더함), `tests/test_lan_tls.py` (보류 켜기)

**Interfaces:**
- Consumes: Task 4 의 등록 글 `ca`, 서버
- Produces:
  - `Client(cfg)`: `cfg["lan"]` 이고 `server_url` 이 `https://` 면 `cfg["ca_pem"]` 이 꼭 있어야 하고 (없으면 `ValueError`), `ssl.create_default_context(cadata=cfg["ca_pem"])` (윈도우 신뢰 저장소를 읽지 않는다, 이름 확인 켬) 를 `urllib.request.HTTPSHandler(context=…)` 로, 프록시는 지금처럼 따르지 않는다. 주소의 호스트가 IP 글자면 사설·루프백이어야 하고, 이름이면 받는다 (PC 가 풀어 본 주소 확인은 ⑤). `http://` 는 지금처럼 127.0.0.1 만.
  - `enroll(text, guid, host, opener=None, rand_hex=None, nonce=None)` - 등록 글의 `url` 이 https 면 글의 `ca` 로 같은 컨텍스트를 만들어 보낸다. 돌려주는 dict 에 `"ca_pem"` 을 더한다. https 인데 `ca` 가 없으면 `ValueError`.
  - `CERT_FAILED = "SERVER_CERT_FAILED"` - 인증서 확인이 실패하면 `fb.AuthError(0, CERT_FAILED)` (에이전트가 '다른 서버' 로 본다).

- [ ] **Step 1: 실패하는 시험**
  - `tests/test_local_store_client.py`: `test_lan_https_needs_ca` (ca_pem 없으면 ValueError), `test_lan_public_ip_refused` (`https://8.8.8.8:8444` → ValueError, `https://10.1.2.3:8444`·`https://nt:8444` → 만들어짐).
  - `tests/test_lan_tls.py`: `test_enroll_over_tls_with_ca` 의 보류를 풀고, `test_other_ca_refused` (다른 CA 로 만든 서버에 붙으면 `AuthError(…, CERT_FAILED)`), `test_three_pcs_over_tls` (① `test_lan_e2e` 의 흐름 1~3단계를 TLS 두 포트로: 셋 등록, 한 PC 에만 명령).
- [ ] **Step 2:** 실행 → 실패.
- [ ] **Step 3:** 구현.
- [ ] **Step 4:** `tests\test_local_store_client.py`, `tests\test_lan_tls.py`, `tests\test_agent_standalone.py`, `tests\test_standalone_e2e.py` 통과.
- [ ] **Step 5: 커밋** - `사내 서버 ② Task 5 - 에이전트 클라이언트는 https 에서 우리 인증 기관만 믿음, 공인 IP 서버 거절, 등록 글의 인증 기관`

---

### Task 6: 웹 - 주소 기준 잠금·Origin·세션 주소·프록시 모양

**Files:**
- Modify: `firebase/agent/local_web.py`
- Test: `tests/test_lan_tls.py` (더함), `tests/test_local_web_api.py` 는 그대로 통과

**Interfaces:**
- Consumes: Task 4 `Handler.client_ip()`, `web.cfg`
- Produces:
  - `class AddrLock(limit=10, window=600, block=600, clock=time.time)`: `blocked(ip) -> bool`, `fail(ip) -> bool` (이번에 막히면 True), `ok(ip)`. 표 상한 `LOCK_TRACK_MAX`.
  - `Lockout(..., steps=(LOCK_SEC,))` - 사내 서버의 `Web` 은 `steps=(60, 300, 900)`: 같은 아이디가 잠길 때마다 다음 칸 (성공하면 처음으로). 단독은 지금과 같은 `(LOCK_SEC,)`. 잠김 안내 글은 남은 분을 말한다.
  - `_login`: `cfg` 가 있으면 비밀번호 계산 **전에** `addr_lock.blocked(client_ip)` → 429 `auth/too-many-requests` "이 PC 에서 로그인 시도가 많아 잠시 막았습니다. 10분 뒤 다시 시도하여 주십시오." 틀리면 아이디 잠금과 주소 잠금을 둘 다 센다. `_password`(비밀번호 바꾸기)도 같은 주소 잠금.
  - `Sessions.open(account, ip=None)`, `Sessions.get(token, touch=False, ip=None)` - 세션에 주소가 있고 `ip` 가 다르면 None (`cfg.bind_session_ip` 일 때만 주소를 묶는다). `_auth` 가 `h.client_ip()` 를 넘긴다.
  - Origin: `cfg` 가 있으면 `Origin` 은 `"https://" + (web_hosts() 의 하나)` 여야 한다 (`web_plain` 이어도 브라우저는 프록시의 https 주소를 본다). 단독은 지금 그대로.
  - `web_plain` 모양: 웹 포트 요청은 소켓 주소가 믿을 프록시여야 하고 `X-Forwarded-Proto` 가 `https` 여야 한다 (아니면 403 "프록시를 거쳐 접속하여 주십시오.").
  - 보안 머리글: `cfg` 가 있으면 `Strict-Transport-Security: max-age=31536000` 을 더한다 (`_send`).
  - 기록의 로그인 줄에 보낸 쪽 주소를 붙인다 (`주소=<ip>`, 사내 서버만).

- [ ] **Step 1: 실패하는 시험** (`tests/test_lan_tls.py`, `peer_ip` 를 바꿔 끼워 여러 주소를 흉내 낸다)
  - `test_addr_lock` - 주소 A 가 서로 다른 아이디로 10번 틀리면 A 는 맞는 비밀번호도 429, 주소 B 의 관리자 로그인은 된다.
  - `test_id_lock_grows` - 같은 아이디가 5번 틀려 잠기고(60초), 시계를 밀어 풀린 뒤 다시 5번 → 300초, 그다음 900초, 맞게 로그인하면 다시 60초부터.
  - `test_forged_xff_ignored` - 프록시 목록 밖 소켓 주소가 `X-Forwarded-For: 10.9.9.9` 를 보내도 잠금·기록은 소켓 주소로. 믿을 프록시에서 온 것은 머리글의 주소로.
  - `test_session_bound_to_ip` - 주소 A 에서 받은 토큰을 주소 B 에서 쓰면 401, `bind_session_ip=False` 면 된다.
  - `test_origin_https_list` - Origin `http://127.0.0.1:<웹>` → 403, `https://127.0.0.1:<웹>` → 통과.
  - `test_plain_proxy_mode` - `web_plain` 설정으로 웹을 평문 127.0.0.1 에 띄우고: `X-Forwarded-Proto: https` 없는 요청 403, 있으면 200. HSTS 머리글이 있다.
- [ ] **Step 2:** 실행 → 실패.
- [ ] **Step 3:** 구현.
- [ ] **Step 4:** `tests\test_lan_tls.py`, `tests\test_local_web_api.py`, `tests\check_web_local.py`, `tests\test_lan_web.py` 통과.
- [ ] **Step 5: 커밋** - `사내 서버 ② Task 6 - 웹: 주소별 로그인 잠금(비밀번호 계산 전에), 아이디 잠금 60·300·900초, 믿을 프록시만 X-Forwarded-For, 세션을 주소에 묶기, https Origin 목록, 평문 프록시 모양, HSTS`

---

### Task 7: ① 에서 넘긴 정리

**Files:**
- Modify: `firebase/agent/local_server.py`, `firebase/agent/local_web.py`, `firebase/agent/pc_registry.py`
- Test: `tests/test_lan_review_fixes.py` (더함)

**Interfaces:** (각 줄이 시험 하나)
- M-3 `test_live_write_after_remove_refused` - LAN 의 현황 PUT·PATCH 에 `guard=lambda get: registry.state(me) == "active"` (거절은 서명된 403 `pc_removed`·`pc_disabled` 와 같은 꼴).
- M-6 `test_runs_doc_keys_per_pc` - LAN 에서 실행 기록 문서 키를 `(PC 번호, id)` 로: `Runs.create` 에 `pc_id` 를 넣어 같은 id 를 두 PC 가 따로 만들 수 있고, 남의 문서 GET 은 404 (403 아님). 단독은 그대로.
- M-7 `test_nonce_table_time_sweep` - nonce 표 정리를 크기 기준에서 10초마다 지난 것 지우기로, PC 하나의 분당 서명 요청 1200 넘으면 서명된 429 `{"error": "Too many requests"}`.
- M-9 `test_number_cap` - `Registry.start` 가 `pc_9999` 다음에서 `SeatsFull` 이 아닌 `ValueError("더 이상 PC 번호를 만들 수 없습니다.")`, 웹은 409.
- M-10 `test_single_needs_keys` - 단독 `make_server(..., keys=None)` 은 `ValueError`.
- M-11 `test_web_streams_from_deploy`·`test_registry_same_object` - `Web.max_streams` 는 `srv.deploy.web_streams` 를 따른다 (서버에 붙은 뒤), `make_server`·`make_lan_servers` 는 `web.registry is not registry` 면 `ValueError`. `_pc_remove` 는 등록부 지우기와 자리 지우기를 같은 순서 잠금 안에서 (Registry 잠금 → Store 쓰기). 쓰지 않는 변수 정리.
- 판단: M-10 의 '단독 웹 API 에 다른 `pcId` 를 실으면 403' 은 그대로 둔다 (더 엄격하고 화면은 보내지 않는다) - 시험으로 남긴다 `test_single_other_pcid_403`.

- [ ] **Step 1:** 위 시험 여덟 개를 쓴다.
- [ ] **Step 2:** `tests\test_lan_review_fixes.py` → 새 시험 실패.
- [ ] **Step 3:** 고친다.
- [ ] **Step 4:** 통과 + `tests\test_lan_server.py`, `tests\test_lan_web.py`, `tests\test_lan_e2e.py`, `tests\test_pc_registry.py`, `tests\test_local_server_http.py`.
- [ ] **Step 5: 커밋** - `사내 서버 ② Task 7 - ① 검토에서 넘긴 정리 (지운 PC 현황 쓰기 거절, 실행 기록 키에 PC, nonce 시간 정리·PC 별 요청 상한, 번호 상한, 단독 열쇠 필수, 웹 구독 상한·등록부 같은 것 확인)`

---

### Task 8: WSL(리눅스)에서 한 번 + 회귀

**Files:**
- Create: `tests/wsl_lan_smoke.py`
- Modify: `tests/run_standalone_suite.py` (새 시험 넷을 SA 목록에, 인자 `wsl` 이면 `wsl.exe -d Ubuntu -e python3 /mnt/d/AX/RPA_StandAlone/tests/wsl_lan_smoke.py` 를 돈다 - WSL 이 없으면 '건너뜀'), `docs/superpowers/plans/2026-11-24-lan-index.md` (② 상태, 미룬 것 표에서 지운 줄)

**Interfaces:** Consumes Task 1~7.

- [ ] **Step 1: 시험** `tests/wsl_lan_smoke.py` - 리눅스 파이썬으로: `/tmp` 아래 임시 폴더, `lan_ca.find_openssl()` 이 리눅스 `openssl` 을 찾는다, CA·서버 인증서를 만들고 열쇠 파일 권한이 0600 이다, `make_lan_servers` 를 127.0.0.1 에 띄우고, 웹 로그인(https, Host·Origin) → `/api/pcs` 추가 → `local_store.enroll` → 현황 PATCH → 웹 스트림에 그 현황이 온다. 리눅스에서 `lock_key_files`(icacls)·`CREATE_NO_WINDOW` 를 부르는 길을 타면 실패로 본다 (13절 9 는 ④ 몫이지만 여기서 막히는 곳을 찾는다 - 막히면 그 자리를 보고서에 적고 이 시험은 그 부분만 건너뛴다).
- [ ] **Step 2:** `wsl.exe -d Ubuntu -e python3 /mnt/d/AX/RPA_StandAlone/tests/wsl_lan_smoke.py` → 통과 (막힌 곳은 ledger 에 Ruling 으로).
- [ ] **Step 3: 회귀** - `D:\AX\RPA\.venv\Scripts\python.exe tests\run_standalone_suite.py all` → '실패한 파일: 0'.
- [ ] **Step 4:** `graphify update .`, 목록 문서의 ② 상태를 '구현 끝 (커밋 범위)' 로, 미룬 것 표에서 끝낸 줄을 지운다.
- [ ] **Step 5: 커밋** - `사내 서버 ② Task 8 - WSL(리눅스)에서 TLS 두 포트·등록·현황 한 번, 시험 일괄 실행에 wsl, 계획 목록 상태`

---

## 이 계획 뒤에 사람이 볼 것 (계획 밖)

- 사내망의 다른 PC 가 실제로 붙는 첫 확인은 ④(NT 설치) 뒤에 한다. 이 PC 의 방화벽을 열지 않기 위해서다 (② 의 시험은 127.0.0.1 과 WSL 뿐).
- 브라우저가 인증 기관의 이름 제한을 지키는지는 NT 에서 사무실 PC 의 Edge 로 본다 (설계 6.3).
