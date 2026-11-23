# -*- coding: utf-8 -*-
"""스탠드얼론 끝에서 끝까지 (계획 ① Task 6): 진짜 에이전트(agent.run)가 Firebase 없이 이 PC 의 로컬 서버로
현황을 올리고 명령을 받아 돌며, 그동안 이 PC 밖으로 연결을 시도하지 않는다.
RPA 는 띄우지 않는다 (RPA_DASHBOARD_DRY_RUN), 설정·기록은 임시 폴더만 쓴다.
    .venv\\Scripts\\python.exe tests\\test_standalone_e2e.py
"""
import io
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
TMP = tempfile.mkdtemp(prefix="rpa_se2e_")
PD = os.path.join(TMP, "pd")
os.makedirs(os.path.join(PD, "config"))          # 새 구조로 보이게 - 큐·기록이 소스 폴더가 아니라 여기 생긴다
os.makedirs(os.path.join(PD, "standalone"))
os.makedirs(os.path.join(TMP, "status"))
os.environ.update(RPA_PROGRAMDATA=PD, RPA_EDITION="standalone", RPA_MACHINE_GUID="p1",
                  RPA_STATUS_DIR=os.path.join(TMP, "status"), RPA_AGENT_QUEUE=os.path.join(TMP, "queue.jsonl"),
                  RPA_USER_CONFIG=os.path.join(TMP, "RPA_UserConfig.json"), RPA_DASHBOARD_DRY_RUN="1",
                  RPA_AGENT_MUTEX="RPA_AGENT_E2E_" + os.path.basename(TMP))
sys.stdin = io.StringIO("")                       # 사람이 없는 실행 - ERPia 고르기 같은 창을 띄우지 않는다

# --- 이 PC 밖으로 나가는 연결을 모은다 (가져오기 전에 감싼다) ---
OUT = []
_connect, _connect_ex, _create = socket.socket.connect, socket.socket.connect_ex, socket.create_connection


def _note(addr):
    try:
        OUT.append(str(addr[0]))
    except Exception:
        OUT.append(repr(addr))


def _wrap(fn):
    def inner(self, addr, *a, **k):
        _note(addr)
        return fn(self, addr, *a, **k)
    return inner


def _wrap_create(addr, *a, **k):
    _note(addr)
    return _create(addr, *a, **k)


socket.socket.connect, socket.socket.connect_ex, socket.create_connection = _wrap(_connect), _wrap(_connect_ex), _wrap_create

import update_sign  # noqa: E402
import license_check  # noqa: E402
import rpa_status as st  # noqa: E402
import local_server  # noqa: E402
import secret  # noqa: E402
import agent  # noqa: E402

fails = []
LOCAL = {"127.0.0.1", "localhost", "::1"}
CMD = "apps/rpa/commands/c1/p1"


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def wait_until(fn, seconds=30):
    end = time.time() + seconds
    while time.time() < end:
        try:
            if fn():
                return True
        except Exception:
            pass
        time.sleep(0.1)
    return False


def command(key, kind, args, ttl=600, by="web"):
    now = int(time.time())
    store.put(f"{CMD}/{key}", {"state": "queued", "type": kind, "args": args, "by": by, "created_at": now, "expires_at": now + ttl})


def state(key):
    return (store.get(f"{CMD}/{key}") or {}).get("state")


code = 1
try:
    lic_secret, lic_public = update_sign.keygen()
    license_check.LICENSE_PUBLIC_KEY_HEX = lic_public.hex()
    body = {"edition": "standalone", "company": "시험상사", "cid": "c1", "pc_id": "p1", "issued": "2026-11-23",
            "modules": {"Hold": False}, "features": {"wellife": False}, "limits": {"schedule": 3, "presets": None, "parallel": None}}
    with open(os.path.join(PD, "license.json"), "w", encoding="utf-8") as f:
        json.dump(license_check.sign_body(lic_secret, body), f, ensure_ascii=False)

    folder = local_server.data_dir()
    store = local_server.Store(os.path.join(folder, "store.json"), volatile=local_server.VOLATILE)
    runs = local_server.Runs(os.path.join(folder, "runs.db"))
    keys = local_server.ensure_keys(folder)
    srv = local_server.make_server(store, runs, license_check.load(), keys, port=0, folder=folder)
    os.environ["RPA_LOCAL_PORT"] = str(srv.server_address[1])
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    cfg = secret.load_config()
    ended = []
    threading.Thread(target=lambda: ended.append(agent.run(cfg)), daemon=True, name="agent").start()

    print("현황")
    check("에이전트가 현황을 올린다", wait_until(lambda: store.get("apps/rpa/live/c1/p1") is not None))
    check("살아 있다는 신호(heartbeat)", wait_until(lambda: isinstance((store.get("apps/rpa/live/c1/p1/heartbeat") or {}).get("at"), int)))
    live = store.get("apps/rpa/live/c1/p1") or {}
    check("토큰 줄은 없다 (1회 구매)", live.get("tokens") is None)
    check("라이선스 정책이 PC 설정에 적힌다", wait_until(lambda: (st.read_settings()["schedule"].get("policy") or {}).get("limit") == 3)
          and "Hold" in (st.read_settings()["schedule"]["policy"].get("off") or []), repr(st.read_settings()["schedule"].get("policy")))

    print("명령")
    command("k1", "set_schedule", {"enabled": False, "days": [0], "slots": [{"at": "09:00", "run": ["Sales"]}]})
    check("명령을 받아 끝낸다", wait_until(lambda: state("k1") in ("done", "failed")) and state("k1") == "done", repr(store.get(f"{CMD}/k1")))
    check("결과 글이 적힌다", "비활성화" in ((store.get(f"{CMD}/k1") or {}).get("result") or ""))
    command("k2", "set_schedule", {"enabled": True, "days": [0], "slots": [{"at": "09:00", "run": ["Sales"]}, {"at": "10:00", "run": ["Sales"]},
                                                                           {"at": "11:00", "run": ["Sales"]}, {"at": "12:00", "run": ["Sales"]}]})
    check("라이선스 한도(3줄)를 넘으면 거절", wait_until(lambda: state("k2") in ("done", "failed")) and state("k2") == "failed"
          and "3" in (store.get(f"{CMD}/k2") or {}).get("result", ""), repr(store.get(f"{CMD}/k2")))
    command("k3", "export_preset", {"nos": [1]})
    check("스탠드얼론에서 안 쓰는 명령은 거절 글로 닫힌다", wait_until(lambda: state("k3") in ("done", "failed")) and state("k3") == "failed"
          and "스탠드얼론 버전에서는" in (store.get(f"{CMD}/k3") or {}).get("result", ""), repr(store.get(f"{CMD}/k3")))
    command("k4", "launch", {"target": "routine"}, ttl=-5)
    check("만료된 명령은 만료로", wait_until(lambda: state("k4") in ("expired", "done", "failed")) and state("k4") == "expired")
    command("k5", "update", {"version": "9999.01.01-1"}, by="web")
    time.sleep(2.0)
    check("관리 화면 전용 명령을 웹이 보내면 손대지 않는다", state("k5") == "queued")

    print("서버가 다시 켜져도")
    port = srv.server_address[1]
    srv.shutdown()
    srv.server_close()
    time.sleep(1.5)
    command("k6", "set_schedule", {"enabled": False, "days": [0], "slots": []})      # 서버가 꺼진 동안 들어온 명령 (파일에는 적힌다)
    srv = local_server.make_server(store, runs, license_check.load(), keys, port=port, folder=folder)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    check("에이전트가 다시 붙어 밀린 명령을 받는다", wait_until(lambda: state("k6") in ("done", "failed"), 90) and state("k6") == "done",
          repr(store.get(f"{CMD}/k6")))

    print("밖으로 나가지 않는다")
    out = sorted(set(OUT) - LOCAL)
    check("이 PC 밖으로 연결을 시도하지 않았다", not out, repr(out))
    check("이 PC 안의 연결은 있었다 (검사가 살아 있다)", "127.0.0.1" in OUT)
    check("에이전트가 죽지 않았다", not ended, repr(ended))
    log_path = os.path.join(TMP, "에이전트_기록.txt")
    log_text = open(log_path, encoding="utf-8").read() if os.path.isfile(log_path) else ""
    check("열쇠는 기록에 없다", keys[0] not in log_text and keys[1] not in log_text and "에이전트 시작" in log_text)
    code = 1 if fails else 0
except Exception as e:
    import traceback
    traceback.print_exc()
    fails.append(f"예외 {type(e).__name__}")
finally:
    print(f"\n실패: {len(fails)}" + (f" ({', '.join(fails)})" if fails else ""))
    sys.stdout.flush()
    shutil.rmtree(TMP, ignore_errors=True)
    os._exit(1 if fails else 0)                    # 에이전트·예약기 스레드가 남아 있어 바로 끝낸다
