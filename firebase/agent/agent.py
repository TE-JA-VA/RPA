"""ERPia RPA 클라우드 에이전트.

PC 에서만 할 수 있는 일을 맡는다: 상태 올리기, heartbeat, 클라우드 명령 수행.
화면과 로그인은 Firebase 가 맡는다.

기존 코드를 고치지 않고 가져다 쓴다:
  rpa_status.dashboard_snapshot()  현황
  rpa_dashboard.launch()/stop_erpia()  실행·종료 (1PC 1프로그램 잠금 포함)
  rpa_status.write_routine_modules()  실행 모듈
"""
import json
import os
import sys
import time

RPA_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if RPA_DIR not in sys.path:
    sys.path.insert(0, RPA_DIR)

import fb   # noqa: E402

BAD_KEY_CHARS = ".$#[]/"
LOG_LINES = 80
QUEUE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "queue.jsonl")
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


def trim_logs(snapshot, lines=LOG_LINES):
    """로그 꼬리만 남긴 사본을 돌려준다 (원본은 건드리지 않는다)."""
    out = json.loads(json.dumps(snapshot, ensure_ascii=False, default=str))
    for view in (out.get("programs") or {}).values():
        if isinstance(view, dict) and isinstance(view.get("log"), list):
            view["log"] = view["log"][-lines:]
    return out


class Uploader:
    """올리기. 실패하면 파일 큐에 쌓아 두고 연결되면 순서대로 다시 보낸다.

    RPA 는 절대 막지 않는다 - 올리기가 실패해도 예외를 밖으로 내보내지 않는다.
    """

    def __init__(self, client, cid, pc_id, queue_path=QUEUE_PATH):
        self._client = client
        self._base = f"live/{cid}/{pc_id}"
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

    def _send(self, path, value):
        try:
            self._client.put(path, value)
            return True
        except Exception:
            self._queue.append({"path": path, "value": value})
            del self._queue[:-QUEUE_MAX]
            self._write_queue()
            return False

    def push_live(self, snapshot):
        return self._send(self._base, clean_for_rtdb(trim_logs(snapshot)))

    def push_heartbeat(self, info):
        return self._send(f"{self._base}/heartbeat", clean_for_rtdb(info))

    def flush(self):
        """쌓인 것을 순서대로 보낸다. 하나라도 실패하면 거기서 멈춘다."""
        while self._queue:
            row = self._queue[0]
            try:
                self._client.put(row["path"], row["value"])
            except Exception:
                self._write_queue()
                return False
            self._queue.pop(0)
        self._write_queue()
        return True
