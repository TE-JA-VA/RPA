"""ERPia RPA 클라우드 에이전트.

PC 에서만 할 수 있는 일을 맡는다: 상태 올리기, heartbeat, 클라우드 명령 수행.
화면과 로그인은 Firebase 가 맡는다.

기존 코드를 고치지 않고 가져다 쓴다:
  rpa_status.dashboard_snapshot()  현황
  rpa_dashboard.launch()/stop_erpia()  실행·종료 (1PC 1프로그램 잠금 포함)
  rpa_status.write_routine_modules()  실행 모듈
"""
import datetime
import json
import os
import sys
import time

RPA_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if RPA_DIR not in sys.path:
    sys.path.insert(0, RPA_DIR)

import fb   # noqa: E402

APP = "rpa"                      # 이 에이전트가 맡는 앱. 경로는 apps/<앱>/... (플랫폼 AFTER MARKET 은 여러 앱을 담는다)
BAD_KEY_CHARS = ".$#[]/"


def app_path(kind, cid, pc_id, app=APP):
    """apps/<앱>/<live|commands|settings>/<회사>/<PC>"""
    return f"apps/{app}/{kind}/{cid}/{pc_id}"
LOG_LINES = 80
QUEUE_PATH = os.environ.get("RPA_AGENT_QUEUE") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "queue.jsonl")
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


RECENT_DAYS = 20      # 화면은 폭에 맞춰 5~20일을 보여 준다


def recent_summary(rows, today, days=RECENT_DAYS):
    """이력에서 최근 N일 요약: [{date, success, failed}] (오래된 날부터). 화면의 10일 격자·도넛용."""
    import datetime as dt
    first = today - dt.timedelta(days=days - 1)
    per = {(first + dt.timedelta(days=i)).isoformat(): {"success": 0, "failed": 0} for i in range(days)}
    for r in rows or []:
        d = (r.get("started_at") or "")[:10]
        if d in per:
            per[d]["success" if r.get("state") == "success" else "failed"] += 1
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
        """서버가 내용을 거부한 것(권한 없음 등). 다시 보내도 똑같으니 큐에 두면 뒤 항목까지 영원히 막는다."""
        return isinstance(e, fb.HttpError) and 400 <= e.status < 500 and e.status not in (401, 429)

    def _send(self, path, value, method="put"):
        try:
            self._call(method, path, value)
            return True
        except Exception as e:
            if self._rejected(e):
                return False
            self._queue.append({"path": path, "value": value, "method": method})
            del self._queue[:-QUEUE_MAX]
            self._write_queue()
            return False

    def push_live(self, snapshot):
        # PATCH 로 최상위 키만 갈아끼운다. PUT 이면 heartbeat 까지 지워진다.
        return self._send(self._base, clean_for_rtdb(trim_logs(snapshot)) or {}, method="patch")

    def push_heartbeat(self, info):
        return self._send(f"{self._base}/heartbeat", clean_for_rtdb(info))

    def flush(self):
        """쌓인 것을 순서대로 보낸다. 끊겨서 실패하면 거기서 멈추고, 거부된 것은 버리고 계속 간다."""
        while self._queue:
            row = self._queue[0]
            try:
                self._call(row.get("method", "put"), row["path"], row["value"])
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
        try:
            self._client.patch(f"{self._base}/{cmd_id}", fields)
        except Exception:
            pass      # 상태를 못 써도 에이전트는 계속 돈다

    def handle(self, cmd_id, cmd, now=None):
        now = time.time() if now is None else now
        verdict, reason = decide(cmd, now)
        if verdict == "bad":
            return verdict
        if verdict == "expired":
            self._mark(cmd_id, state="expired", result=reason, ended_at=int(now))
            return verdict

        self._mark(cmd_id, state="running", started_at=int(now))
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
def real_actions():
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
        wanted["Login"] = True           # 로그인은 항상 켬 (관리자도 못 끈다)
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


def first_run(path, email, password, client=None):
    """설정 파일이 없을 때 한 번. 기계 계정으로 로그인해 보고 회사·PC 를 토큰에서 읽어 저장한다."""
    import secret
    cfg = dict(secret.PUBLIC, email=email.strip(), password=password, cid="", pc_id="")
    c = fb.claims((client or fb.Client(cfg)).token())
    if c.get("role") != "agent" or not c.get("cid") or not c.get("pcId"):
        raise ValueError("기계 계정(agent-…)이 아닙니다. 사람 계정으로는 에이전트를 띄울 수 없습니다")
    cfg.update(cid=c["cid"], pc_id=c["pcId"])
    secret.write_config(path, cfg, password)
    return secret.load_config(path)


def main():
    import threading
    import rpa_status as st
    import secret

    try:
        cfg = secret.load_config()
    except FileNotFoundError:
        if not sys.stdin.isatty():
            log(f"설정 파일이 없습니다: {secret.CONFIG_PATH}")
            return 2
        import getpass
        print("처음 실행입니다. 이 PC 의 기계 계정(agent-…@…)을 넣으세요. 비밀번호는 이 PC 에만 잠가서 저장합니다.")
        try:
            cfg = first_run(secret.CONFIG_PATH, input("이메일: "), getpass.getpass("비밀번호 (화면에 안 보임): "))
        except (EOFError, KeyboardInterrupt):
            log("입력을 취소했습니다")
            return 2
        except Exception as e:
            if getattr(e, "code", None) == 400:
                log("로그인 실패: 이메일 또는 비밀번호가 맞지 않습니다")
            else:
                log(f"설정을 만들지 못했습니다: {type(e).__name__}: {e}")
            return 2
        log(f"설정을 저장했습니다: {secret.CONFIG_PATH}")
    except (ValueError, OSError) as e:
        log(f"설정을 읽지 못했습니다: {e}")
        return 2
    client = fb.Client(cfg)
    up = Uploader(client, cfg["cid"], cfg["pc_id"])
    cmds = Commands(client, cfg["cid"], cfg["pc_id"], real_actions())
    log(f"에이전트 시작  회사={cfg['cid']}  PC={cfg['pc_id']}  밀린 기록={up.pending()}건")

    # 자동 실행 예약은 PC 에서 돈다. 기존 대시보드의 Scheduler 그대로 (꺼져 있던 동안 지난 예약은 건너뛴다).
    # 8765 대시보드와 같이 띄우면 예약이 둘이 되어 두 번 실행될 수 있다 - 하나만 띄운다.
    import rpa_dashboard as dash
    dash.SCHEDULER.resync()
    dash.SCHEDULER.start()
    sch = st.read_settings()["schedule"]
    log("자동 실행: " + (dash.schedule_label(sch) + f"  다음 {sch.get('next_run_at') or '(곧 계산)'}" if sch.get("enabled") else "꺼짐"))

    stop = threading.Event()

    def pump():
        """상태와 heartbeat. 1초마다 상태 파일을 보고 바뀌었을 때만 올린다."""
        last = None
        last_beat = 0.0
        recent_key = [None, []]   # (이력 파일 mtime, 오늘) 과 그때 센 요약
        while not stop.is_set():
            try:
                snap = st.dashboard_snapshot()
                try:
                    snap["modules"] = st.read_routine_modules()[0]   # PC 의 실제 실행 모듈 (ERPIA_AI.txt)
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
                # 새 이력 줄은 Firestore 로 (읽은 위치를 파일에 남겨 다시 켜도 이어서 올린다)
                upload_new_history(hist_path, up, cfg)
                body = json.dumps([snap.get("programs"), snap.get("modules"), snap.get("schedule"), snap.get("recent")],
                                  ensure_ascii=False, default=str)
                if body != last:
                    up.push_live(snap)
                    last = body
                if time.time() - last_beat >= HEARTBEAT_SEC:
                    up.push_heartbeat({
                        "at": int(time.time()),
                        "host": snap.get("host"),
                        "rpa_running": bool([p for p, v in (snap.get("programs") or {}).items()
                                             if v and v.get("state") == "running"]),
                    })
                    last_beat = time.time()
                up.flush()
            except Exception as e:
                log(f"상태 올리기 실패: {type(e).__name__}")
            stop.wait(1.0)

    threading.Thread(target=pump, daemon=True).start()

    backoff = 1
    while not stop.is_set():
        try:
            for event, data in client.stream(app_path("commands", cfg["cid"], cfg["pc_id"])):
                backoff = 1
                if event not in ("put", "patch") or not isinstance(data, dict):
                    continue
                path, payload = data.get("path") or "/", data.get("data")
                items = {}
                if path == "/" and isinstance(payload, dict):
                    items = payload
                elif path.count("/") == 1 and isinstance(payload, dict):
                    items = {path.strip("/"): payload}
                for cmd_id, cmd in items.items():
                    verdict = decide(cmd, time.time())[0]
                    if verdict == "bad":
                        continue
                    log(f"명령 {cmd.get('type')} ({cmd_id[:8]}) 처리")
                    log(f"  → {cmds.handle(cmd_id, cmd)}")
        except KeyboardInterrupt:
            break
        except Exception as e:
            log(f"구독이 끊겼습니다 ({type(e).__name__}). {backoff}초 뒤 다시 붙습니다")
            stop.wait(backoff)
            backoff = min(backoff * 2, 60)
    stop.set()
    dash.SCHEDULER.stop.set()
    return 0


if __name__ == "__main__":
    sys.exit(main())
