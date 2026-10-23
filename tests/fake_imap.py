# -*- coding: utf-8 -*-
"""시험용 가짜 IMAP 서버 - 실제 메일함에 접속하지 않고 mail_imap 을 시험한다 (설계 11절).

TLS 자체 서명 인증서(openssl 로 그때그때 만든다)로 993 처럼 바로 TLS, 또 하나는 평문으로 열어 STARTTLS.
CAPABILITY·STARTTLS·LOGIN·SELECT/EXAMINE·UID SEARCH·UID FETCH·UID STORE·NOOP·LOGOUT 만 안다.
받은 명령은 모두 commands 에 남는다 (금지 명령·플래그 변경 확인용). stall 을 켜면 메일함 고르기에서 답하지 않는다.
"""
import datetime as dt
import imaplib
import os
import re
import shutil
import socketserver
import ssl
import subprocess
import tempfile
import threading

USER, PASSWORD = "tester@example.com", "pw-1234"
UIDVALIDITY = 777
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _openssl():
    for p in (shutil.which("openssl"), r"C:\Program Files\Git\mingw64\bin\openssl.exe",
              r"C:\Program Files\Git\usr\bin\openssl.exe"):
        if p and os.path.exists(p):
            return p
    raise RuntimeError("openssl 을 찾지 못했습니다.")


def _tokens(s):
    """IMAP 인자 → 글 목록 (따옴표 풀기)."""
    return [re.sub(r"\\(.)", r"\1", q) if q or not w else w
            for q, w in re.findall(r'"((?:[^"\\]|\\.)*)"|(\S+)', s)]


def _header_fields(raw, names):
    head = raw.split(b"\r\n\r\n", 1)[0]
    keep = [h for h in re.split(rb"\r\n(?![ \t])", head) if h.split(b":", 1)[0].strip().upper().decode() in names]
    return b"\r\n".join(keep) + b"\r\n\r\n"


class FakeIMAP:
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="fake_imap_")
        cert, key = os.path.join(self.dir, "cert.pem"), os.path.join(self.dir, "key.pem")
        subprocess.run([_openssl(), "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
                        "-nodes", "-keyout", key, "-out", cert, "-days", "2", "-subj", "/CN=127.0.0.1",
                        "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"], check=True, capture_output=True)
        self.server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.server_ctx.load_cert_chain(cert, key)
        self.client_ctx = ssl.create_default_context(cafile=cert)     # 이 인증서만 믿는 쪽
        self.boxes = {"INBOX": []}
        self.commands = []
        self.stall = False
        self.readonly = set()       # SELECT 해도 읽기 전용으로 여는 메일함 (진짜 서버의 공유·보관 메일함처럼)
        self.wake = threading.Event()
        self.servers = [self._listen(True), self._listen(False)]

    def _listen(self, implicit):
        srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Handler)
        srv.daemon_threads = True
        srv.handle_error = lambda *a: None      # 일부러 끊는 시험(인증서 거절·시간 넘김)의 오류 출력 숨김
        srv.fake, srv.implicit = self, implicit
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv

    def add(self, raw, date, seen=False, box="INBOX", idate=None):
        """메일 하나 (raw: CRLF bytes, date: PC 시각 = 서버가 받은 시각). uid 를 돌려준다.
        idate: INTERNALDATE 로 보낼 글 그대로 (규격을 어긴 서버 흉내)."""
        msgs = self.boxes.setdefault(box, [])
        msgs.append({"uid": len(msgs) + 1, "raw": raw, "date": date.astimezone(), "flags": {"\\Seen"} if seen else set(),
                     "idate": idate})
        return len(msgs)

    def server(self, security="ssl", **kw):
        port = self.servers[0 if security == "ssl" else 1].server_address[1]
        return {"host": "127.0.0.1", "port": port, "security": security, "user": USER, "password": PASSWORD,
                "context": self.client_ctx, **kw}

    def flags(self, box="INBOX"):
        return {m["uid"]: sorted(m["flags"]) for m in self.boxes[box]}

    def close(self):
        self.wake.set()
        for s in self.servers:
            s.shutdown()
            s.server_close()
        shutil.rmtree(self.dir, ignore_errors=True)


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        fake = self.server.fake
        self.conn = fake.server_ctx.wrap_socket(self.request, server_side=True) if self.server.implicit else self.request
        tls, box, readonly = self.server.implicit, None, True
        f = self.conn.makefile("rb")
        self.send("* OK fake IMAP ready")
        while True:
            line = f.readline()
            if not line:
                return
            line = line.decode("utf-8", "replace").rstrip("\r\n")
            fake.commands.append(line)
            tag, _, rest = line.partition(" ")
            cmd, _, args = rest.partition(" ")
            cmd = cmd.upper()
            if cmd == "UID":
                sub, _, args = args.partition(" ")
                cmd += " " + sub.upper()
            ok = f"{tag} OK {cmd} completed"
            if cmd == "CAPABILITY":
                self.send("* CAPABILITY IMAP4rev1" + ("" if tls else " STARTTLS LOGINDISABLED"))
                self.send(ok)
            elif cmd == "STARTTLS" and not tls:
                self.send(ok)
                self.conn = fake.server_ctx.wrap_socket(self.conn, server_side=True)
                f, tls = self.conn.makefile("rb"), True
            elif cmd == "LOGIN":
                t = _tokens(args)
                self.send(ok if tls and t == [USER, PASSWORD] else f"{tag} NO [AUTHENTICATIONFAILED] Invalid credentials")
            elif cmd in ("SELECT", "EXAMINE"):
                if fake.stall:
                    fake.wake.wait(10)
                    return
                name = (_tokens(args) or [""])[0]
                if name not in fake.boxes:
                    self.send(f"{tag} NO Mailbox does not exist")
                    continue
                box, readonly = fake.boxes[name], cmd == "EXAMINE" or name in fake.readonly
                self.send(f"* {len(box)} EXISTS")
                self.send(f"* OK [UIDVALIDITY {UIDVALIDITY}] UIDs valid")
                self.send(f"{tag} OK [{'READ-ONLY' if readonly else 'READ-WRITE'}] {cmd} completed")
            elif cmd == "UID SEARCH" and box is not None:
                t, found = [x.upper() for x in _tokens(args)], list(box)
                for i, x in enumerate(t):
                    if x == "UNSEEN":
                        found = [m for m in found if "\\Seen" not in m["flags"]]
                    elif x == "SINCE":
                        d, mon, y = t[i + 1].split("-")
                        since = dt.date(int(y), [m.upper() for m in MONTHS].index(mon) + 1, int(d))
                        found = [m for m in found if m["date"].date() >= since]
                self.send("* SEARCH " + " ".join(str(m["uid"]) for m in found))
                self.send(ok)
            elif cmd == "UID FETCH" and box is not None:
                uidset, _, items = args.partition(" ")
                self.fetch(box, uidset, items, readonly)
                self.send(ok)
            elif cmd == "UID STORE" and box is not None:
                if readonly:
                    self.send(f"{tag} NO Mailbox is read-only")
                    continue
                uid, op, flags = args.split(" ", 2)
                for seq, m in enumerate(box, 1):
                    if str(m["uid"]) == uid and op.upper() == "+FLAGS":
                        m["flags"] |= set(flags.strip("()").split())
                        self.send(f"* {seq} FETCH (UID {m['uid']} FLAGS ({' '.join(sorted(m['flags']))}))")
                self.send(ok)
            elif cmd == "NOOP":
                self.send(ok)
            elif cmd == "LOGOUT":
                self.send("* BYE logging out")
                self.send(ok)
                return
            else:
                self.send(f"{tag} BAD unknown command")

    def send(self, s):
        self.conn.sendall(s if isinstance(s, bytes) else s.encode() + b"\r\n")

    def fetch(self, box, uidset, items, readonly):
        wanted = set()
        for part in uidset.split(","):
            a, _, b = part.partition(":")
            top = max([m["uid"] for m in box] or [0])
            lo, hi = (top if a == "*" else int(a)), (top if b == "*" else int(b or a))
            wanted |= set(range(min(lo, hi), max(lo, hi) + 1))
        up = items.upper()
        sec = re.search(r"BODY(\.PEEK)?\[([^\]]*)\]", up)
        for seq, m in enumerate(box, 1):
            if m["uid"] not in wanted:
                continue
            if sec and not sec.group(1) and not readonly:
                m["flags"].add("\\Seen")       # PEEK 없는 BODY[] 는 읽음으로 바꾼다 (진짜 서버처럼)
            out = [f"UID {m['uid']}"]
            if "FLAGS" in up:
                out.append(f"FLAGS ({' '.join(sorted(m['flags']))})")
            if "RFC822.SIZE" in up:
                out.append(f"RFC822.SIZE {len(m['raw'])}")
            if "INTERNALDATE" in up:
                out.append("INTERNALDATE " + (m["idate"] or imaplib.Time2Internaldate(m["date"])))
            if not sec:
                self.send(f"* {seq} FETCH ({' '.join(out)})")
                continue
            if sec.group(2).startswith("HEADER.FIELDS"):
                lit = _header_fields(m["raw"], set(re.search(r"\(([^)]*)\)", sec.group(2))[1].split()))
            else:
                lit = m["raw"]
            self.send(f"* {seq} FETCH ({' '.join(out)} BODY[{sec.group(2)}] {{{len(lit)}}}\r\n".encode() + lit + b")\r\n")
