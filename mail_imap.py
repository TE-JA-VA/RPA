# -*- coding: utf-8 -*-
"""메일에서 엑셀 받기 (IMAP) - 설계 docs/superpowers/specs/2026-10-14-mail-imap-design.md 4·5·6·7·10·11절.

화면·Playwright 와 상관없는 순수 모듈 (파이썬 기본 imaplib·email 만).
- 연결은 IMAPS(993) 또는 STARTTLS 만. 암호화 없는 연결·인증서 검증 끄기는 두지 않는다.
- 서버에서 바꾸는 것은 '받은 뒤 읽음 표시'(켠 경우) 뿐. 지우기·옮기기 명령은 두지 않는다.
- 한글 제목·보낸 사람 비교는 서버에 맡기지 않고 PC 에서 한다.
- 로그에 비밀번호·본문·전체 주소를 싣지 않는다 (보낸 사람은 앞 2글자, 제목은 30자까지).
"""
import base64
import contextlib
import datetime as dt
import email
import email.policy
import email.utils
import imaplib
import json
import mimetypes
import os
import re
import ssl
import unicodedata

KNOWN_SERVERS = {   # 실제 접속 확인 전
    "naver.com": ("imap.naver.com", 993, "ssl"),
    "daum.net": ("imap.daum.net", 993, "ssl"),
    "hanmail.net": ("imap.daum.net", 993, "ssl"),
    "gmail.com": ("imap.gmail.com", 993, "ssl"),
    "nate.com": ("imap.nate.com", 993, "ssl"),
}
BLOCKED_EXT = {"exe", "js", "vbs", "bat", "cmd", "ps1", "scr", "xlsm"}
DEFAULT_RULES = {"mailbox": "INBOX", "senders": [], "subject_prefix": "", "subject_has": [], "subject_not": [],
                 "unseen_only": False, "days": 0, "exts": ["xlsx", "xls", "csv"], "name_has": "", "max": 20,
                 "mark_seen": False}
# days 0 = 오늘 받은 것만 (PC 시각 00:00 부터), 1~30 = 최근 N일

CONNECT_TIMEOUT = 30            # 초
CMD_TIMEOUT = 60                # 명령마다 초
MAX_SIZE = 50 * 1024 * 1024     # 이보다 큰 메일은 건너뛴다
KEEP_DAYS = 90                  # 기억 보관 날 수
HEADER_ITEMS = "(UID FLAGS RFC822.SIZE INTERNALDATE BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)])"
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
NAMELESS_EXT = {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
                "application/vnd.ms-excel": "xls", "text/csv": "csv"}

CONNECT_FAIL = "메일 서버에 연결하지 못했습니다. (주소·포트를 확인하여 주십시오)"
LOGIN_FAIL = "로그인을 거부하였습니다. (비밀번호·IMAP 사용 설정·앱 비밀번호를 확인하여 주십시오)"
NO_RESPONSE = "메일 서버가 응답하지 않습니다."


class MailError(Exception):
    """사람 말로 된 실패 까닭."""


def guess_server(address):
    """메일 주소(또는 도메인)로 알려진 서버를 찾는다. 모르면 None."""
    return KNOWN_SERVERS.get((address or "").rsplit("@", 1)[-1].strip().lower())


def check_rules(rules):
    """기본값을 채우고 다듬은 사본을 돌려준다. 잘못이면 ValueError (사람 말)."""
    r = dict(DEFAULT_RULES)
    r.update({k: v for k, v in (rules or {}).items() if v is not None})
    for k in ("senders", "subject_has", "subject_not", "exts"):
        v = r[k].split(",") if isinstance(r[k], str) else r[k]
        r[k] = [str(s).strip() for s in v if str(s).strip()]
    r["exts"] = [e.lower().lstrip(".") for e in r["exts"]]
    for k in ("mailbox", "subject_prefix", "name_has"):
        r[k] = str(r[k] or "").strip()
    r["mailbox"] = r["mailbox"] or "INBOX"
    r["unseen_only"], r["mark_seen"] = bool(r["unseen_only"]), bool(r["mark_seen"])
    try:
        r["days"], r["max"] = int(r["days"]), int(r["max"])
    except (TypeError, ValueError):
        raise ValueError("기간과 한 번에 최대는 숫자로 넣어 주십시오.") from None
    if not (r["senders"] or r["subject_prefix"] or r["subject_has"]):
        raise ValueError("보낸 사람이나 제목 칸 중 하나는 꼭 채워 주십시오.")
    bad = [e for e in r["exts"] if e in BLOCKED_EXT]
    if bad:
        raise ValueError(f"받을 수 없는 첨부 종류입니다: {', '.join(bad)}")
    if not r["exts"]:
        raise ValueError("첨부 종류를 하나 이상 넣어 주십시오.")
    if not 0 <= r["days"] <= 30:
        raise ValueError("기간은 0(오늘)부터 30일까지입니다.")
    if not 1 <= r["max"] <= 50:
        raise ValueError("한 번에 최대는 1부터 50통까지입니다.")
    return r


def _norm(s):
    """대소문자·전각/반각·공백을 가리지 않게."""
    return "".join(unicodedata.normalize("NFKC", s or "").casefold().split())


def _since(now, days):
    return dt.datetime.combine(now.date() - dt.timedelta(days=days), dt.time())


def matches(rules, sender, subject, date, now):
    """규칙에 맞는 메일인가 (rules 는 check_rules 를 거친 것). date·now 는 PC 시각."""
    s, subj = _norm(sender), _norm(subject)
    if rules["senders"] and not any(_norm(x) in s for x in rules["senders"]):
        return False
    if not subj.startswith(_norm(rules["subject_prefix"])):
        return False
    if not all(_norm(x) in subj for x in rules["subject_has"]):
        return False
    if any(_norm(x) in subj for x in rules["subject_not"]):
        return False
    if date.tzinfo:
        date = date.astimezone().replace(tzinfo=None)
    return date >= _since(now, rules["days"])


def mask_sender(addr):
    """'ab***@naver.com' - 로그에는 앞 2글자만."""
    a = email.utils.parseaddr(addr or "")[1] or addr or ""
    local, at, dom = a.partition("@")
    return f"{local[:2]}***{at}{dom}"


def unique_path(path):
    """같은 이름이 있으면 뒤에 (1), (2) 를 붙인다. 기존 파일을 덮지 않는다 (web_runner.unique_path 와 같음)."""
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    for i in range(1, 1000):
        cand = f"{stem} ({i}){ext}"
        if not os.path.exists(cand):
            return cand
    return path


def forget(memory_path):
    """[기억 지우기] - 처리한 메일 기억 파일을 지운다."""
    with contextlib.suppress(FileNotFoundError):
        os.remove(memory_path)


# ---- 서버 ----

def _mutf7(name):
    """메일함 이름을 IMAP 의 modified UTF-7 로 (한글 메일함)."""
    def enc(m):
        if m[0] == "&":
            return "&-"
        return "&" + base64.b64encode(m[0].encode("utf-16-be")).decode().rstrip("=").replace("/", ",") + "-"
    return re.sub(r"[^\x20-\x7e]+|&", enc, name)


def _quote(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _connect(server):
    sec = server.get("security")
    if sec not in ("ssl", "starttls"):
        raise MailError("연결 방식은 ssl 또는 starttls 만 씁니다. (암호화 없는 연결은 쓰지 않습니다)")
    ctx = server.get("context") or ssl.create_default_context()
    M = None
    try:
        if sec == "ssl":
            M = imaplib.IMAP4_SSL(server["host"], int(server["port"]), ssl_context=ctx, timeout=CONNECT_TIMEOUT)
        else:
            M = imaplib.IMAP4(server["host"], int(server["port"]), timeout=CONNECT_TIMEOUT)
            M.starttls(ctx)
        M.sock.settimeout(CMD_TIMEOUT)
        return M
    except (OSError, imaplib.IMAP4.error) as e:
        if M:
            with contextlib.suppress(Exception):
                M.shutdown()
        raise MailError(CONNECT_FAIL) from e


@contextlib.contextmanager
def _session(server, mailbox, readonly):
    """연결 → 로그인 → 메일함 고르기 (readonly 면 EXAMINE). (M, UIDVALIDITY) 를 준다. 끝나면 늘 끊는다."""
    M = _connect(server)
    ok = False
    try:
        try:
            M.login(server["user"], server["password"])
        except imaplib.IMAP4.abort:
            raise
        except (imaplib.IMAP4.error, UnicodeEncodeError):
            raise MailError(LOGIN_FAIL) from None
        typ, _ = M.select(_quote(_mutf7(mailbox)), readonly=readonly)
        if typ != "OK":
            raise MailError(f"메일함 '{mailbox}'이(가) 없습니다.")
        uidvalidity = (M.response("UIDVALIDITY")[1] or [b""])[0] or b""
        yield M, uidvalidity.decode()
        ok = True
    except (TimeoutError, ConnectionError, ssl.SSLError, imaplib.IMAP4.abort):
        raise MailError(NO_RESPONSE) from None
    except imaplib.IMAP4.error as e:
        raise MailError(f"메일 서버가 명령을 거부하였습니다. ({e})") from None
    finally:
        with contextlib.suppress(Exception):
            M.logout() if ok else M.shutdown()


def _records(data):
    """UID FETCH 응답 → [[머리 bytes, 글 bytes], ...]. 글 뒤에 오는 조각은 머리에 붙인다."""
    recs = []
    for d in data or []:
        if isinstance(d, tuple):
            recs.append([d[0], d[1]])
        elif recs and isinstance(d, bytes):
            recs[-1][0] += d
    return recs


def _text(b):
    """머리글 bytes → 글. UTF-8 이 아니면 EUC-KR/CP949 로 본다."""
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("cp949", "replace")


def _hdr(msg, name):
    try:
        return str(msg.get(name) or "")
    except Exception:       # 깨진 머리글
        return ""


def _candidates(M, rules, uidvalidity, now):
    """서버에 SINCE(+UNSEEN)만 묻고, 머리글을 받아 PC 에서 규칙으로 거른다. 최근 것부터."""
    day = _since(now, rules["days"]) - dt.timedelta(days=1)     # 서버 시간대가 달라도 빠지지 않게 하루 앞부터
    crit = ["SINCE", f"{day.day:02d}-{MONTHS[day.month - 1]}-{day.year}"] + (["UNSEEN"] if rules["unseen_only"] else [])
    _, data = M.uid("SEARCH", *crit)
    uids = (data[0] or b"").split() if data else []
    out = []
    for i in range(0, len(uids), 200):
        _, data = M.uid("FETCH", b",".join(uids[i:i + 200]).decode(), HEADER_ITEMS)
        for meta, raw in _records(data):
            uid = re.search(rb"UID (\d+)", meta)
            if not uid:
                continue
            size = re.search(rb"RFC822\.SIZE (\d+)", meta)
            t = imaplib.Internaldate2tuple(meta)        # 서버가 받은 시각 → PC 시각
            hdr = email.message_from_string(_text(raw), policy=email.policy.default)
            m = {"uid": int(uid[1]), "size": int(size[1]) if size else 0, "date": dt.datetime(*t[:6]) if t else now,
                 "sender": _hdr(hdr, "From"), "subject": _hdr(hdr, "Subject")}
            m["key"] = _hdr(hdr, "Message-ID").strip() or f"{uidvalidity}:{m['uid']}"
            if matches(rules, m["sender"], m["subject"], m["date"], now):
                out.append(m)
    return sorted(out, key=lambda m: (m["date"], m["uid"]), reverse=True)


def _message(M, uid):
    """메일 전체를 받는다 (BODY.PEEK[] - 읽음 표시가 바뀌지 않는다)."""
    _, data = M.uid("FETCH", str(uid), "(BODY.PEEK[])")
    recs = _records(data)
    return email.message_from_bytes(recs[0][1], policy=email.policy.default) if recs else None


def _filename(part):
    """첨부 이름. 8비트 그대로 온 이름(EUC-KR 등)은 깨져 나오므로 머리글 원문에서 다시 푼다."""
    name = part.get_filename() or ""
    if "�" in name:
        for k, v in part.raw_items():
            m = re.search(r'name="?([^";\r\n]+)', v) if k.lower() in ("content-type", "content-disposition") else None
            if m:
                return _text(m[1].encode("utf-8", "surrogateescape"))
    return name


def _safe_name(name):
    """경로·위험한 글자를 뺀 파일 이름."""
    name = re.sub(r'[\x00-\x1f<>:"|?*]', "_", re.split(r"[\\/]", name)[-1]).strip(" .")
    stem, ext = os.path.splitext(name)
    return stem[:150] + ext


def _attachments(msg, rules, uid):
    """확장자·이름 규칙에 맞는 첨부 [(이름, 부분)]. 이름 없는 첨부는 첨부_<uid>_<n>.<ext>."""
    out, n = [], 0
    for part in msg.walk():
        if part.is_multipart() or (part.get_content_disposition() != "attachment" and not part.get_filename()):
            continue
        n += 1
        name = _safe_name(_filename(part))
        if not name:
            ctype = part.get_content_type()
            ext = NAMELESS_EXT.get(ctype) or (mimetypes.guess_extension(ctype) or "").lstrip(".")
            name = f"첨부_{uid}_{n}" + (f".{ext}" if ext else "")
        ext = os.path.splitext(name)[1].lower().lstrip(".")
        if ext in rules["exts"] and ext not in BLOCKED_EXT and _norm(rules["name_has"]) in _norm(name):
            out.append((name, part))
    return out


# ---- 기억 ----

def _load(memory_path):
    try:
        with open(memory_path, encoding="utf-8") as f:
            mem = json.load(f)
        return mem if isinstance(mem, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write(memory_path, mem, now):
    cut = (now.date() - dt.timedelta(days=KEEP_DAYS)).isoformat()
    mem = {k: v for k, v in mem.items() if isinstance(v, str) and v >= cut}
    os.makedirs(os.path.dirname(os.path.abspath(memory_path)), exist_ok=True)
    tmp = memory_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(mem, f, ensure_ascii=False, indent=1)
    os.replace(tmp, memory_path)


def _save(path, data):
    with open(path, "xb") as f:     # x: 있는 파일은 절대 덮지 않는다
        f.write(data)


# ---- 공개 ----

def find(server, rules, memory_path=None, now=None):
    """[찾아보기] - 규칙에 맞는 메일 목록 (EXAMINE, 받지 않고 표시도 안 바꾼다). 최근 것부터 최대 rules max 통."""
    rules = check_rules(rules)
    now = now or dt.datetime.now()
    memory = _load(memory_path) if memory_path else {}
    items = []
    with _session(server, rules["mailbox"], readonly=True) as (M, uv):
        for m in _candidates(M, rules, uv, now)[:rules["max"]]:
            msg = _message(M, m["uid"]) if m["size"] <= MAX_SIZE else None
            items.append({"key": m["key"], "uid": m["uid"], "date": m["date"], "sender": m["sender"],
                          "subject": m["subject"], "done": m["key"] in memory,
                          "attachments": [n for n, _ in _attachments(msg, rules, m["uid"])] if msg else []})
    return items


def fetch(server, rules, dest_dir, code, memory_path, log=print, now=None):
    """규칙에 맞고 기억에 없는 메일의 첨부를 dest_dir 에 (code)이름 으로 받는다.
    첨부를 모두 받은 메일만 기억한다 (읽음 표시를 켰으면 그 메일만 \\Seen)."""
    rules = check_rules(rules)
    now = now or dt.datetime.now()
    memory = _load(memory_path)
    result = {"mails": 0, "saved": [], "skipped": []}
    done = []
    os.makedirs(dest_dir, exist_ok=True)
    try:
        with _session(server, rules["mailbox"], readonly=not rules["mark_seen"]) as (M, uv):
            mails = [m for m in _candidates(M, rules, uv, now) if m["key"] not in memory][:rules["max"]]
            log(f"대상 메일 {len(mails)}통")
            for m in mails:
                result["mails"] += 1
                subj = m["subject"][:30]
                log(f"메일: {mask_sender(m['sender'])} / {subj}")
                if m["size"] > MAX_SIZE:
                    result["skipped"].append((subj, "50MB 를 넘는 메일이라 건너뜁니다."))
                    log("  50MB 를 넘는 메일이라 건너뜁니다.")
                    continue
                msg = _message(M, m["uid"])
                ok = msg is not None
                atts = _attachments(msg, rules, m["uid"]) if ok else []
                if ok and not atts:     # 받을 것이 없을 뿐 실패가 아니다 - skipped 에 넣지 않는다 (ACTOR 가 skipped 만 있으면 실패로 본다)
                    log("  맞는 첨부가 없습니다.")
                for name, part in atts:
                    path = unique_path(os.path.join(dest_dir, f"({code}){name}"))
                    try:
                        _save(path, part.get_payload(decode=True) or b"")
                    except OSError as e:
                        ok = False
                        result["skipped"].append((name, f"저장하지 못했습니다. ({e.strerror or e})"))
                        log(f"  저장 실패: {name}")
                        continue
                    result["saved"].append(path)
                    log(f"  받음: {os.path.basename(path)}")
                if ok:
                    done.append(m["key"])
                    if rules["mark_seen"]:
                        M.uid("STORE", str(m["uid"]), "+FLAGS", "(\\Seen)")
    finally:        # 중간에 끊겨도 다 받은 메일은 기억한다 (다음에 또 받지 않게)
        if done:
            memory.update({k: now.date().isoformat() for k in done})
            _write(memory_path, memory, now)
    log(f"메일 {result['mails']}통, 첨부 {len(result['saved'])}개를 받았습니다."
        + (f" (건너뜀 {len(result['skipped'])}건)" if result["skipped"] else ""))
    return result
