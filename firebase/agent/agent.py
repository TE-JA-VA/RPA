"""ERPia RPA 클라우드 에이전트.

PC 에서만 할 수 있는 일을 맡는다: 상태 올리기, heartbeat, 클라우드 명령 수행.
화면과 로그인은 Firebase 가 맡는다.

기존 코드를 고치지 않고 가져다 쓴다:
  rpa_status.dashboard_snapshot()  현황
  rpa_dashboard.launch()/stop_erpia()  실행·종료 (1PC 1프로그램 잠금 포함)
  rpa_status.write_routine_modules()  실행 모듈
  rpa_status.migrate_user_config()  사용자 설정 한 파일로 옮기기·비밀번호 잠금 (켤 때)
"""
import datetime
import json
import os
import re
import sys
import time

RPA_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if RPA_DIR not in sys.path:
    sys.path.insert(0, RPA_DIR)

import fb   # noqa: E402

APP = "rpa"                      # 이 에이전트가 맡는 앱. 경로는 apps/<앱>/... (플랫폼 AFTER MARKET 은 여러 앱을 담는다)
BAD_KEY_CHARS = ".$#[]/"
PROJECT_DOMAIN = "rpa-test-f02e0.firebaseapp.com"


def app_path(kind, cid, pc_id, app=APP):
    """apps/<앱>/<live|commands|settings>/<회사>/<PC>"""
    return f"apps/{app}/{kind}/{cid}/{pc_id}"


def email_for(cid, pc_id):
    """기계 계정 이메일. setup.js·app.js 의 같은 규칙과 똑같아야 한다 (밑줄→하이픈, 회사가 없으면 프로젝트 도메인)."""
    return f"agent-{pc_id.replace('_', '-')}@{cid.replace('_', '-') + '.' if cid else ''}{PROJECT_DOMAIN}"


def auth_message(code):
    """Identity Toolkit 의 거부 code → 사람이 할 일. 첫 실행과 운영 중 둘 다 이 문구를 쓴다."""
    if code in ("INVALID_LOGIN_CREDENTIALS", "INVALID_PASSWORD", "EMAIL_NOT_FOUND"):
        return "비밀번호가 맞지 않습니다 (바뀌었으면 새 비밀번호를 넣으세요)"
    if code == "USER_DISABLED":
        return "이 기계 계정은 막혀 있습니다. 관리자에게 물어보세요"
    if code == "TOO_MANY_ATTEMPTS_TRY_LATER":
        return "시도가 너무 많아 잠시 막혔습니다. 10분쯤 뒤에 다시 띄우세요"
    return f"로그인 거부: {code}"
LOG_LINES = 80


def _data_dir():
    """에이전트 큐·위치·기록을 둘 폴더. 새 구조면 %ProgramData%\\AFTER MARKET\\RPA\\data, 아니면 이 파일 옆 (옛 자리).
    옛 구조에서 rpa_status.data_dir() 을 쓰지 않는 까닭: 개발 PC 는 그 값이 dist 라 큐가 엉뚱한 곳에 생긴다."""
    import rpa_status as st
    return st.data_dir() if st.new_layout() else os.path.dirname(os.path.abspath(__file__))


QUEUE_PATH = os.environ.get("RPA_AGENT_QUEUE") or os.path.join(_data_dir(), "queue.jsonl")
QUEUE_MAX = 500


def clean_for_rtdb(value):
    """RTDB 가 거부하는 키를 버리고, 빈 dict/list 를 None 으로 바꾼다."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if not isinstance(k, str) or k == "" or any(c in k for c in BAD_KEY_CHARS):
                continue
            out[k] = clean_for_rtdb(v)
        return out or None
    if isinstance(value, (list, tuple)):
        return [clean_for_rtdb(v) for v in value] or None
    return value


RECENT_DAYS = 20      # 화면은 20일을 다 그리고 15칸까지만 보여 준다 (나머지는 가로 스크롤)


def recent_summary(rows, today, days=RECENT_DAYS):
    """이력에서 최근 N일 요약: [{date, success, failed, crashed}] (오래된 날부터). 화면의 날짜별 도넛용.
    failed = 중단·실패(업무 데이터 문제, 빨강), crashed = 비정상 종료(PC·ERPia 환경 문제, 노랑)."""
    import datetime as dt
    first = today - dt.timedelta(days=days - 1)
    per = {(first + dt.timedelta(days=i)).isoformat(): {"success": 0, "failed": 0, "crashed": 0} for i in range(days)}
    for r in rows or []:
        d = (r.get("started_at") or "")[:10]
        if d in per:
            st = r.get("state")
            per[d]["success" if st == "success" else "crashed" if st == "crashed" else "failed"] += 1
    return [{"date": d, **v} for d, v in per.items()]


def run_doc(rec, cid, pc_id):
    """history_record 한 건 → Firestore 문서 (조회용 필드 + payload JSON). 규칙이 cid·pcId 를 claim 과 대조한다."""
    rec = dict(rec)
    rec["log"] = (rec.get("log") or rec.get("log_tail") or [])[-LOG_LINES:]
    rec.pop("log_tail", None)
    doc = {
        "cid": cid, "pcId": pc_id,
        "run_id": rec.get("run_id"), "program": rec.get("program"), "program_label": rec.get("program_label"),
        "state": rec.get("state"), "reason": rec.get("reason"),
        "started_at": rec.get("started_at"), "finished_at": rec.get("finished_at"),
        "duration_sec": rec.get("duration_sec"), "date": (rec.get("started_at") or "")[:10],
        "payload": json.dumps(rec, ensure_ascii=False, default=str),
    }
    return doc


def trim_logs(snapshot, lines=LOG_LINES):
    """로그 꼬리만 남긴 사본을 돌려준다 (원본은 건드리지 않는다)."""
    out = json.loads(json.dumps(snapshot, ensure_ascii=False, default=str))
    for view in (out.get("programs") or {}).values():
        if isinstance(view, dict) and isinstance(view.get("log"), list):
            view["log"] = view["log"][-lines:]
    return out


HISTORY_POS_PATH = os.path.join(os.path.dirname(QUEUE_PATH), "history_pos.txt")


def upload_new_history(hist_path, up, cfg, pos_path=HISTORY_POS_PATH):
    """history.jsonl 에서 아직 안 올린 줄을 Firestore 로. 읽은 바이트 위치를 파일에 남긴다.

    파일이 줄었으면(회전) 처음부터 다시 본다 - 같은 run_id 는 Firestore 가 409 로 거절하니 겹쳐도 안전하다.
    """
    try:
        size = os.path.getsize(hist_path)
    except OSError:
        return 0
    try:
        with open(pos_path, encoding="utf-8") as f:
            pos = int(f.read().strip() or 0)
    except Exception:
        pos = 0
    if pos > size:
        pos = 0
    if pos == size:
        return 0
    sent = 0
    with open(hist_path, "rb") as f:
        f.seek(pos)
        chunk = f.read()
    lines = chunk.split(b"\n")
    tail = lines.pop()               # 마지막 조각은 아직 쓰는 중일 수 있다
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            rec = json.loads(raw.decode("utf-8"))
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("run_id"):
            up.push_run(run_doc(rec, cfg["cid"], cfg["pc_id"]))
            sent += 1
    new_pos = size - len(tail)
    try:
        with open(pos_path, "w", encoding="utf-8") as f:
            f.write(str(new_pos))
    except Exception:
        pass
    return sent


class Uploader:
    """올리기. 실패하면 파일 큐에 쌓아 두고 연결되면 순서대로 다시 보낸다.

    RPA 는 절대 막지 않는다 - 올리기가 실패해도 예외를 밖으로 내보내지 않는다.
    """

    def __init__(self, client, cid, pc_id, queue_path=QUEUE_PATH):
        self._client = client
        self._cid = cid
        self._base = app_path("live", cid, pc_id)
        self._queue_path = queue_path
        self._queue = self._read_queue()

    def _read_queue(self):
        rows = []
        try:
            with open(self._queue_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            rows.append(json.loads(line))
                        except ValueError:
                            continue
        except FileNotFoundError:
            pass
        except Exception:
            pass
        return rows

    def _write_queue(self):
        try:
            if not self._queue:
                if os.path.exists(self._queue_path):
                    os.remove(self._queue_path)
                return
            tmp = f"{self._queue_path}.{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                for row in self._queue[-QUEUE_MAX:]:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            os.replace(tmp, self._queue_path)
        except Exception:
            pass

    def pending(self):
        return len(self._queue)

    def _call(self, method, path, value):
        if method == "patch":
            self._client.patch(path, value)
        elif method == "fs":
            self._client.fs_create(path, fb.fs_fields(value), value["run_id"])
        else:
            self._client.put(path, value)

    def push_run(self, doc):
        """실행 이력 한 건을 Firestore runs/{cid}/items 에. 실패하면 큐에 쌓인다."""
        return self._send(f"runs/{self._cid}/items", doc, method="fs")

    @staticmethod
    def _rejected(e):
        """서버가 내용을 거부한 것. 다시 보내도 똑같으니 큐에 두면 뒤 항목까지 영원히 막는다.
        RTDB 는 규칙 거부를 401 로 돌려준다 (403 이 아니다). 클라이언트가 401 이면 토큰을 새로 받아 한 번 더 보낸 뒤에야
        HttpError 를 올리므로, 여기 오는 401 은 토큰 만료가 아니라 규칙 거부다. 429(너무 잦음)만 다시 보낸다."""
        return isinstance(e, fb.HttpError) and 400 <= e.status < 500 and e.status != 429

    def _send(self, path, value, method="put", queue=True):
        try:
            self._call(method, path, value)
            return True
        except fb.AuthError:
            raise         # 인증이 죽은 것 - 큐에 둘 일이 아니라 에이전트가 멈추고 비밀번호를 다시 물어야 한다
        except Exception as e:
            if not queue or self._rejected(e):
                return False
            self._queue.append({"path": path, "value": value, "method": method})
            del self._queue[:-QUEUE_MAX]
            self._write_queue()
            return False

    def push_live(self, snapshot):
        # PATCH 로 최상위 키만 갈아끼운다. PUT 이면 heartbeat 까지 지워진다.
        return self._send(self._base, clean_for_rtdb(trim_logs(snapshot)) or {}, method="patch")

    def push_heartbeat(self, info):
        # 큐에 넣지 않는다 - 지난 heartbeat 를 나중에 올려 봐야 의미 없고, 큐 500칸에서 이력을 밀어낸다
        return self._send(f"{self._base}/heartbeat", clean_for_rtdb(info), queue=False)

    def flush(self):
        """쌓인 것을 순서대로 보낸다. 끊겨서 실패하면 거기서 멈추고, 거부된 것은 버리고 계속 간다."""
        while self._queue:
            row = self._queue[0]
            try:
                self._call(row.get("method", "put"), row["path"], row["value"])
            except fb.AuthError:
                raise
            except Exception as e:
                if not self._rejected(e):
                    self._write_queue()
                    return False
            self._queue.pop(0)
        self._write_queue()
        return True


# ---------------------------------------------------------------------------
# 명령
# ---------------------------------------------------------------------------
KNOWN_TYPES = ("launch", "stop_erpia", "set_modules", "set_schedule")
HEARTBEAT_SEC = 5   # 화면은 HEARTBEAT_STALE_SEC(20초) 넘게 없으면 '끊김' - 네 번 놓쳐야 끊김이다


def decide(cmd, now):
    """명령을 실행할지 정한다. ('run'|'expired'|'bad', 사유)"""
    if not isinstance(cmd, dict):
        return "bad", "명령 모양이 아닙니다"
    if cmd.get("state") != "queued":
        return "bad", f"queued 가 아닙니다 ({cmd.get('state')})"
    if cmd.get("type") not in KNOWN_TYPES:
        return "bad", f"모르는 종류입니다 ({cmd.get('type')})"
    expires = cmd.get("expires_at")
    if not isinstance(expires, (int, float)):
        return "bad", "만료 시각이 없습니다"
    if expires < now:
        return "expired", "만료된 명령입니다 (PC 가 꺼져 있었을 수 있습니다)"
    return "run", None


class Commands:
    """명령 하나를 받아 상태를 옮긴다. 한 번에 하나씩만 부른다."""

    def __init__(self, client, cid, pc_id, actions):
        self._client = client
        self._base = app_path("commands", cid, pc_id)
        self._actions = actions

    def _mark(self, cmd_id, **fields):
        """상태를 쓴다. 못 쓰면 False (에이전트는 계속 돈다)."""
        try:
            self._client.patch(f"{self._base}/{cmd_id}", fields)
            return True
        except Exception:
            return False

    def handle(self, cmd_id, cmd, now=None):
        now = time.time() if now is None else now
        verdict, reason = decide(cmd, now)
        if verdict == "bad":
            return verdict
        if verdict == "expired":
            self._mark(cmd_id, state="expired", result=reason, ended_at=int(now))
            return verdict

        # running 표시가 안 되면 실행하지 않는다. 규칙이 queued→running 을 한 번만 허용하므로 같은 계정의 두 PC 중
        # 하나는 여기서 걸린다. 끊긴 경우엔 명령이 queued 로 남아 다음 접속 때 다시 오거나 만료된다.
        if not self._mark(cmd_id, state="running", started_at=int(now)):
            return "deferred"
        kind = cmd.get("type")
        action = self._actions.get(kind)
        try:
            if action is None:
                raise RuntimeError(f"이 에이전트는 '{kind}' 를 할 수 없습니다")
            message = action(cmd.get("args")) or "완료"
            self._mark(cmd_id, state="done", result=str(message)[:500], ended_at=int(time.time()))
            return "done"
        except Exception as e:
            self._mark(cmd_id, state="failed", result=f"{e}"[:500], ended_at=int(time.time()))
            return "failed"


# ---------------------------------------------------------------------------
# 실제 동작 (기존 코드를 그대로 쓴다)
# ---------------------------------------------------------------------------
def company_modules(client, cid, app=APP):
    """업체가 안 쓰는 모듈 정책 {키: False}. 총괄만 쓸 수 있는 자리라 화면을 우회한 명령도 여기서 막힌다.
    못 읽으면 빈 값 - 정책 조회 실패가 실행을 막지는 않는다."""
    try:
        return {k: v for k, v in (client.get(f"meta/companies/{cid}/apps/{app}/modules") or {}).items() if v is False}
    except Exception:
        return {}


def real_actions(policy=None):
    """policy: 업체 정책 {키: False} 를 돌려주는 함수 (없으면 정책 없음)"""
    import rpa_dashboard as dash
    import rpa_status as st

    def do_launch(args):
        target = (args or {}).get("target") if isinstance(args, dict) else None
        target = target or "routine"
        if target not in dash.TARGETS:
            raise RuntimeError(f"실행 대상이 잘못되었습니다 ({target})")
        dash.launch(target, "cloud")         # 1PC 1프로그램 잠금·중복 방지는 launch 안에 있다
        return f"{dash.TARGETS[target][0]} 을(를) 띄웠습니다"

    def do_stop(args):
        status, body = dash.stop_erpia()
        if status != 200:
            raise RuntimeError(body.get("error") or "ERPia 를 종료하지 못했습니다")
        return body.get("message") or "ERPia 를 종료했습니다"

    def do_modules(args):
        if not isinstance(args, dict) or not args:
            raise RuntimeError("모듈 값이 없습니다")
        wanted = {k: bool(v) for k, v in args.items()
                  if k in dict(st.ROUTINE_CONFIG_MODULES)}
        if not wanted:
            raise RuntimeError("아는 모듈이 없습니다")
        for k in (policy() if policy else {}):
            if k in dict(st.ROUTINE_CONFIG_MODULES):
                wanted[k] = False        # 이 업체가 안 쓰는 모듈 (총괄이 정한다)
        wanted["Login"] = True           # 로그인은 항상 켬 (관리자도 못 끈다)
        if wanted.get("Logistics") is False:
            wanted["Output"] = False     # 운송장 출력은 물류관리가 꺼져 있으면 돌 수 없다 (빠진 키는 Y 로 쓰이므로 여기서 못 박는다)
        st.write_routine_modules(wanted)
        on = [k for k, v in wanted.items() if v]
        return f"실행 모듈을 바꿨습니다 (켬: {', '.join(on)})"

    def do_schedule(args):
        # 검증·저장·다음 시각 계산은 기존 apply_schedule 이 다 한다 (요일 0~6, 5분 단위, 최대 개수)
        changed = dash.apply_schedule(args)
        sch = st.read_settings()["schedule"]
        if not sch.get("enabled"):
            return "자동 실행을 껐습니다"
        return f"자동 실행: {dash.schedule_label(sch)}" + ("" if changed else " (변경 없음)")

    return {"launch": do_launch, "stop_erpia": do_stop, "set_modules": do_modules, "set_schedule": do_schedule}


def watch_commands(client, path, on_command, stop=None):
    """명령함을 한 번 구독한다. 서버가 스트림을 닫으면 'ended', 토큰이 죽었다는 알림이면 'auth_revoked' 를 돌려준다.
    호출자가 곧바로 다시 붙인다. stop(Event)이 켜지면 다음 이벤트에서 'stopped' - pump 가 인증이 죽은 걸 먼저 봤을 때
    스트림에 실린 옛 토큰은 만료(최대 1시간)까지 살아 있으니, keep-alive(30초)마다 stop 을 봐야 그 안에 빠져나온다.

    로그인 토큰은 1시간마다 만료되고 그때 Firebase 가 auth_revoked 를 보낸다. 이걸 무시하면 heartbeat 는 계속
    올라가는데(다른 요청이라 토큰이 갱신된다) 명령만 영원히 못 받는 귀머거리가 된다. 2026-09-22 실기에서 두 번 겪었다."""
    gen = client.stream(path)
    try:
        for event, data in gen:
            if stop is not None and stop.is_set():
                return "stopped"
            if event in ("auth_revoked", "cancel"):
                client.renew()          # 다음 요청이 토큰을 새로 받게
                return event
            if event not in ("put", "patch") or not isinstance(data, dict):
                continue
            sub, payload = data.get("path") or "/", data.get("data")
            items = {}
            if sub == "/" and isinstance(payload, dict):
                items = payload                       # 처음 붙을 때: 대기 중인 명령 전부
            elif sub.count("/") == 1 and isinstance(payload, dict):
                items = {sub.strip("/"): payload}     # 새 명령 하나
            for cmd_id, cmd in items.items():
                on_command(cmd_id, cmd)
    finally:
        gen.close()
    return "ended"


def log(text):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {text}"
    print(line, flush=True)
    # 큐와 같은 폴더에 둔다 - 통합 시험(RPA_AGENT_QUEUE 가 임시 폴더)이 실제 기록을 어지럽히지 않게
    path = os.path.join(os.path.dirname(QUEUE_PATH), "에이전트_기록.txt")
    try:
        if os.path.exists(path) and os.path.getsize(path) > 1024 * 1024:
            os.replace(path, path + ".1")
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def first_run(path, cid, pc_id, password, client=None, email=None):
    """설정 파일이 없을 때 한 번 (비밀번호를 다시 물을 때도 쓴다). 회사 코드·PC 이름으로 이메일을 조립해 로그인해 보고,
    토큰의 회사·PC 가 친 값과 같아야 저장한다. email 은 옛 설정의 것을 그대로 쓸 때만 넘긴다 - 이때는 회사·PC 를 다시 물을
    칸이 없으니 토큰이 다르면 run() 처럼 토큰 값을 쓴다 (클레임을 옮기고 비밀번호도 바꾼 경우)."""
    import secret
    cfg = dict(secret.PUBLIC, email=email or email_for(cid, pc_id), password=password, cid=cid, pc_id=pc_id)
    c = fb.claims((client or fb.Client(cfg)).token())
    if c.get("role") != "agent":
        raise ValueError("기계 계정(agent-…)이 아닙니다. 사람 계정으로는 에이전트를 띄울 수 없습니다")
    if (c.get("cid"), c.get("pcId")) != (cid, pc_id):
        if email is None or not (c.get("cid") and c.get("pcId")):
            raise ValueError(f"이 계정은 {c.get('cid')}/{c.get('pcId')} 의 것입니다. 회사 코드·PC 이름을 확인하세요")
        log(f"토큰의 회사·PC({c['cid']}/{c['pcId']})가 설정({cid}/{pc_id})과 다릅니다. 토큰 값을 씁니다")
        cfg.update(cid=c["cid"], pc_id=c["pcId"])
    secret.write_config(path, cfg, password)
    return secret.load_config(path)


def ask_key(label):
    """회사 코드·PC 이름 - 소문자·숫자·밑줄만. 아니면 다시 묻는다."""
    while True:
        v = input(f"{label}: ").strip()
        if re.fullmatch(r"[a-z0-9_]+", v):
            return v
        print("  소문자·숫자·밑줄만 쓸 수 있습니다")


def ask_setup(known=None):
    """창에서 물어 설정을 만든다. known=(cid, pc_id, email) 이면 비밀번호만 묻는다 (운영 중 인증이 죽었을 때).
    로그인이 거부되면 이유를 찍고 다시 묻는다. 취소(Ctrl+C·EOF)나 망 오류면 None."""
    import getpass
    import secret
    while True:
        try:
            cid, pc_id, email = known or (ask_key("회사 코드"), ask_key("PC 이름"), None)
            return first_run(secret.CONFIG_PATH, cid, pc_id, getpass.getpass("비밀번호 (화면에 안 보임): "), email=email)
        except (EOFError, KeyboardInterrupt):
            log("입력을 취소했습니다")
            return None
        except fb.AuthError as e:
            log(f"로그인 실패: {auth_message(e.code)}")
        except ValueError as e:
            log(f"로그인 실패: {e}")
        except Exception as e:
            log(f"설정을 만들지 못했습니다: {type(e).__name__}: {e}")
            return None


# ---------------------------------------------------------------------------
# 에이전트 하나만 (설치 마법사 2부 5절). 설정 창(rpa_settings)이 같은 이름으로 '돌고 있음' 을 본다
# ---------------------------------------------------------------------------
MUTEX_NAME = os.environ.get("RPA_AGENT_MUTEX") or r"Local\AFTER_MARKET_RPA_AGENT"   # 시험은 RPA_AGENT_MUTEX 로 따로


def single_instance(name=None):
    """이 윈도우 로그인에서 에이전트가 하나만 돌게 이름 있는 잠금을 잡는다. 이미 있으면 False (rpa_status.hold_lock)."""
    import rpa_status as st
    return st.hold_lock(name or MUTEX_NAME)



def main():
    """감독자. 설정을 읽거나 처음 물어 만들고 run() 을 돈다. 인증이 죽어 run() 이 멈추면 이유를 찍고 (창이 있으면)
    비밀번호를 다시 물어 다시 돈다. 종료 코드: 0 정상, 2 설정 문제, 3 인증이 죽었는데 창이 없어 다시 물을 수 없음,
    4 이 PC 에서 에이전트가 이미 돌고 있음 (background.py 가 이 코드들을 보고 다시 켤지 정한다)."""
    import secret

    if not single_instance():
        log("이 PC 에서 에이전트가 이미 돌고 있습니다 (창 없이 도는 에이전트일 수 있습니다). 이 창은 닫아도 됩니다")
        return 4
    try:
        cfg = secret.load_config()
    except FileNotFoundError:
        if not sys.stdin.isatty():
            log(f"설정 파일이 없습니다: {secret.CONFIG_PATH}")
            return 2
        print("처음 실행입니다. 이 PC 의 회사 코드·PC 이름과 기계 계정 비밀번호를 넣으세요. 비밀번호는 이 PC 에만 잠가서 저장합니다.")
        cfg = ask_setup()
        if cfg is None:
            return 2
        log(f"설정을 저장했습니다: {secret.CONFIG_PATH}")
    except (ValueError, OSError) as e:
        log(f"설정을 읽지 못했습니다: {e}")
        return 2

    while True:
        dead = run(cfg)
        if dead is None:
            return 0
        log(f"인증이 죽어 멈췄습니다: {auth_message(dead.code)}")
        # 막힌 계정·시도 초과는 비밀번호를 다시 넣어도 소용없다 - 안내대로 나중에 다시 띄운다
        if not sys.stdin.isatty() or dead.code in ("USER_DISABLED", "TOO_MANY_ATTEMPTS_TRY_LATER"):
            return 3
        print(f"비밀번호가 바뀌었거나 계정이 막혔습니다: {auth_message(dead.code)}. "
              f"새 비밀번호를 넣으세요 (회사 {cfg['cid']} / PC {cfg['pc_id']}). "
              f"기계 계정 자체가 바뀌었으면 Ctrl+C 로 나가서 {os.path.basename(secret.CONFIG_PATH)} 을 지우고 다시 띄우세요")
        cfg = ask_setup((cfg["cid"], cfg["pc_id"], cfg["email"]))
        if cfg is None:
            return 3


def run(cfg):
    """설정 하나로 에이전트를 돈다. Ctrl+C 면 None, 인증이 죽어 멈췄으면 그 AuthError 를 돌려준다 (main 이 다시 묻는다).
    클레임을 옮긴 경우(토큰의 회사·PC 가 설정과 다름) cfg 를 토큰 값으로 고쳐 쓴다."""
    import threading
    import rpa_dashboard as dash
    import rpa_status as st

    client = fb.Client(cfg)
    try:
        c = fb.claims(client.token())
        if c.get("cid") and c.get("pcId") and (c["cid"], c["pcId"]) != (cfg["cid"], cfg["pc_id"]):
            log(f"토큰의 회사·PC({c['cid']}/{c['pcId']})가 설정({cfg['cid']}/{cfg['pc_id']})과 다릅니다. 토큰 값을 씁니다")
            cfg.update(cid=c["cid"], pc_id=c["pcId"])
    except fb.AuthError as e:
        return e
    except Exception as e:
        log(f"첫 로그인을 못 했습니다 ({type(e).__name__}). 설정 값으로 시작하고 이어서 시도합니다")
    up = Uploader(client, cfg["cid"], cfg["pc_id"])
    cmds = Commands(client, cfg["cid"], cfg["pc_id"], real_actions(lambda: company_modules(client, cfg["cid"])))
    log(f"에이전트 시작  회사={cfg['cid']}  PC={cfg['pc_id']}  밀린 기록={up.pending()}건")
    # 사용자 설정 한 파일로 옮기기 (옛 ERPIA_AI.txt·WebManageConfig.json·login_manager_config.json → RPA_UserConfig.json,
    # 비밀번호 잠금). 실패해도 에이전트는 계속 돈다 - RPA 는 옛 파일이나 평문으로도 돈다
    try:
        moved = st.migrate_user_config()
        if moved:
            log(moved)
    except Exception as e:
        log(f"사용자 설정을 옮기지 못했습니다 ({type(e).__name__}: {e}). 옛 파일 그대로 돕니다")
    # ERPia 위치: 적힌 값이 틀렸으면 찾아 고친다. 못 찾으면 사람이 띄운 창일 때만 고르는 창을 띄운다
    # (루틴 RPA 는 무인으로 돌 때 창을 못 띄우니 여기서 정해 둔다)
    try:
        exe = st.erpia_exe(ask=sys.stdin.isatty())
        log(f"ERPia 위치: {exe}" if exe else
            "ERPia 프로그램(ERPiaMain.exe)을 찾지 못했습니다. 루틴 RPA 가 ERPia 를 켜지 못합니다 - "
            "ERPia 를 설치했는지 보고 에이전트를 다시 켜서 위치를 고르세요")
    except Exception as e:
        log(f"ERPia 위치를 확인하지 못했습니다 ({type(e).__name__})")
    # 판: 프로그램 폴더를 판 목록(manifest.json)과 맞춰 PC 현황에 올린다 (배포판 구조 1부 5절).
    # 파일은 업데이트나 손으로 넣을 때만 바뀌고 둘 다 에이전트를 다시 켜므로 켤 때 한 번이면 된다. 예외를 내지 않는다
    install = st.check_install()
    detail = {"mixed": f", 다른 파일 {install['changed_count']}개: {', '.join(install['changed'])}",
              "error": f", {install.get('error')}"}.get(install["state"], "")
    log(f"버전: {install['version'] or '없음'} ({install['state']}{detail})")

    # 자동 실행 예약은 PC 에서 돈다. 기존 대시보드의 Scheduler 그대로 (꺼져 있던 동안 지난 예약은 건너뛴다).
    # 8765 대시보드와 같이 띄우면 예약이 둘이 되어 두 번 실행될 수 있다 - 하나만 띄운다.
    # 비밀번호를 다시 물은 뒤의 재시작에서는 이미 돌고 있다 - 프로세스에서 한 번만 start 한다.
    if not dash.SCHEDULER.is_alive():
        dash.SCHEDULER.resync()
        dash.SCHEDULER.start()
    sch = st.read_settings()["schedule"]
    log("자동 실행: " + (dash.schedule_label(sch) + f"  다음 {sch.get('next_run_at') or '(곧 계산)'}" if sch.get("enabled") else "꺼짐"))

    stop = threading.Event()
    dead = []     # 인증이 죽은 AuthError. pump 스레드와 구독 루프 어느 쪽이 먼저 만나든 여기 담고 둘 다 멈춘다

    def pump():
        """상태와 heartbeat. 1초마다 상태 파일을 보고 바뀌었을 때만 올린다."""
        last = None
        last_beat = 0.0
        recent_key = [None, []]   # (이력 파일 mtime, 오늘) 과 그때 센 요약
        while not stop.is_set():
            try:
                snap = st.dashboard_snapshot()
                try:
                    snap["modules"] = st.read_routine_modules()[0]   # PC 의 실제 실행 모듈 (RPA_UserConfig.json)
                except Exception:
                    snap["modules"] = None
                # settings.json 에서 schedule 절만. accounts(비밀번호 해시)는 절대 안 올린다
                snap["schedule"] = st.read_settings().get("schedule")
                # 최근 10일 요약은 이력 파일이 바뀌었을 때만 다시 센다
                hist_path = os.path.join(st.status_dir(create=False), st.HISTORY_NAME)
                try:
                    hist_key = (os.path.getmtime(hist_path), datetime.date.today())
                except OSError:
                    hist_key = (None, datetime.date.today())
                if hist_key != recent_key[0]:
                    recent_key[0] = hist_key
                    recent_key[1] = recent_summary(st.read_history(), datetime.date.today())
                snap["recent"] = recent_key[1]
                # 띄워 놓은 프로세스가 아직 살아 있나. 명령이 done 이 된 뒤 상태 파일에 'running' 이 찍히기까지의
                # 몇 초를 이 값이 메운다 (그 틈에 화면의 실행 버튼이 풀리면 두 번 실행될 수 있다)
                snap["launching"] = bool(dash.launch_state())
                snap["version"] = install      # 켤 때 한 번 잰 판 (바뀌지 않으니 비교 body 에는 안 넣는다)
                # 새 이력 줄은 Firestore 로 (읽은 위치를 파일에 남겨 다시 켜도 이어서 올린다)
                upload_new_history(hist_path, up, cfg)
                body = json.dumps([snap.get("programs"), snap.get("modules"), snap.get("schedule"), snap.get("recent"),
                                   snap.get("launching")], ensure_ascii=False, default=str)
                if body != last:
                    up.push_live(snap)
                    last = body
                if time.time() - last_beat >= HEARTBEAT_SEC:
                    up.push_heartbeat({
                        "at": int(time.time()),
                        "every": HEARTBEAT_SEC,   # 화면이 이 값으로 끊김 기준을 잡는다 (옛 에이전트는 없어서 30초로 본다)
                        "host": snap.get("host"),
                        "rpa_running": bool([p for p, v in (snap.get("programs") or {}).items()
                                             if v and v.get("state") == "running"]),
                    })
                    last_beat = time.time()
                up.flush()
            except fb.AuthError as e:
                dead.append(e)
                stop.set()
            except Exception as e:
                log(f"상태 올리기 실패: {type(e).__name__}")
            stop.wait(1.0)

    threading.Thread(target=pump, daemon=True).start()

    def on_command(cmd_id, cmd):
        if decide(cmd, time.time())[0] == "bad":
            return
        log(f"명령 {cmd.get('type')} ({cmd_id[:8]}) 처리")
        log(f"  → {cmds.handle(cmd_id, cmd)}")

    backoff = 1
    while not stop.is_set():
        try:
            why = watch_commands(client, app_path("commands", cfg["cid"], cfg["pc_id"]), on_command, stop)
            if why != "stopped":
                log(f"구독이 끝났습니다 ({why}). 바로 다시 붙습니다")   # auth_revoked 는 1시간마다 오는 정상 절차
            backoff = 1
        except KeyboardInterrupt:
            stop.set()
            dash.SCHEDULER.stop.set()
            return None
        except fb.AuthError as e:
            dead.append(e)
            stop.set()
        except Exception as e:
            code = getattr(e, "code", None)          # 날 HTTPError 면 상태코드도 - "(HTTPError 401)"
            log(f"구독이 끊겼습니다 ({type(e).__name__}{f' {code}' if code else ''}). {backoff}초 뒤 다시 붙습니다")
            stop.wait(backoff)
            backoff = min(backoff * 2, 60)
    return dead[0] if dead else None


if __name__ == "__main__":
    sys.exit(main())
