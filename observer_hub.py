# -*- coding: utf-8 -*-
r"""옵저버 단독 관제 (설계 docs/superpowers/specs/2026-11-03-observer-standalone-design.md 4.3).

ERPia 없이 옵저버(기록) + ACTOR(재생)만 쓰는 PC 의 로컬 서버 + 예약기. rpa_dashboard 의 예약기·띄우기·기록 함수를 그대로 쓰고
화면(hub/)과 API 만 따로 둔다. 127.0.0.1 에만 열리며 로그인은 없다 - 다른 PC 에서 못 열고, 쓰기 요청은 Host·Origin 을 본다
(다른 웹 페이지가 이 서버를 부르지 못하게).

    Observer_Hub.exe observer_hub.py [--port N] [--open] [--install-task | --remove-task]

--open 은 떠 있는 서버를 포트 8775~8784 의 /healthz 로 찾아 기본 브라우저로 연다 (없으면 작업 스케줄러 작업을 켠 뒤).
--install-task 는 작업 스케줄러 '오토파일럿 옵저버 관제' 를 로그온 시·현재 사용자·대화형·가장 높은 권한으로 등록한다 (설치 파일이 부른다).
"""
import argparse
import datetime
import http.server
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import rpa_dashboard as d  # noqa: E402
import rpa_status as st  # noqa: E402

PORTS = tuple(range(8775, 8785))      # 오토파일럿(8765)과 다른 번호. 8775 를 쓰고 있으면 다음 빈 것
SIGNATURE = "AUTOPILOT_OBSERVER_HUB"
MAX_BODY = 64 * 1024
NO_SERVER = "관제 서버가 실행되고 있지 않습니다. PC 를 다시 시작하거나 담당자에게 문의하여 주십시오."
HISTORY_PERIODS = ("7", "30", "90")   # 기록 탭의 기간 (일)
TASK_NAME = "오토파일럿 옵저버 관제"
HUB_EXE = "Observer_Hub.exe"          # 내장 pythonw 의 브랜딩 사본 (tools/build_release.py BRANDED)
OBSERVER_EXE = "Prepare_Observer.exe"
HUB_DIR = os.path.join(HERE, "hub")
PAGES = {"/": ("index.html", "text/html; charset=utf-8"), "/hub.js": ("hub.js", "text/javascript; charset=utf-8"),
         "/hub.css": ("hub.css", "text/css; charset=utf-8")}
HTML_CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
CREATE_NO_WINDOW = 0x08000000
OBSERVER_RUNNING = "옵저버가 이미 실행 중입니다."
NOT_STANDALONE = "옵저버 단독 버전이 아닙니다. (설치 폴더에 OBSERVER_STANDALONE 표시 파일이 없습니다)"


def find_port(ports=None):
    """떠 있는 관제 서버의 포트 - PORTS 를 차례로 /healthz 서명으로 찾는다 (포트 파일은 관리자 전용 ProgramData 에 있어 승격 안 한
    바로가기가 못 읽는다 - 검토 2026-11-03). 없으면 None."""
    return next((p for p in (PORTS if ports is None else ports) if alive(p)), None)


def alive(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as r:
            return r.read().decode("utf-8", "replace").strip() == SIGNATURE
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 화면이 읽는 것
# ---------------------------------------------------------------------------
def presets_view():
    """프리셋 표 - preset_summary 에 '사람 입력 필요'(문자 인증 단계가 있다) 를 더한다 (설계 4.4). 기록 내용은 싣지 않는다."""
    rows = st.preset_summary()
    if rows is None:
        return None
    try:
        manual = {p["no"] for p in st.read_presets()
                  if any(s.get("kind") == "otp" and s.get("source") != "copy" for s in (p["record"] or {}).get("steps") or [])}
    except (ValueError, OSError):
        manual = set()
    return [dict(r, manual=r["no"] in manual) for r in rows]


def state_view():
    cfg = st.read_settings()
    return {"snapshot": st.dashboard_snapshot(), "schedule": d.schedule_view(), "presets": presets_view(),
            "running": bool(d.any_rpa_running()), "launch": d.launch_state(), "observer_open": st.observer_open(),
            "settings": {"download_dir": st.download_dir_choice(), "parallel": st.parallel_choice()},
            "limits": {"presets": st.preset_limit(), "parallel_max": st.PARALLEL_MAX},
            "pc_problem": st.standalone_pc_problem(), "last_error": cfg["schedule"].get("last_error")}


def run_presets(presets):
    """[지금 실행] - 번호 검사는 예약 줄과 같다 (normalize_presets·slot_presets). ValueError 400 / RuntimeError 409."""
    nos = d.normalize_presets(presets)
    return d.launch_slot({"presets": nos} if nos else {}, by="manual:hub", trigger="manual")


def save_settings(body):
    """받은 파일 폴더·동시 실행 창 수. 폴더는 만들어 보고 못 만들면 ValueError (그 글이 400 으로 간다)."""
    folder = body.get("download_dir")
    if folder is not None:
        if not isinstance(folder, str) or not folder.strip():
            raise ValueError("받은 파일 폴더를 입력하여 주십시오.")
        folder = os.path.normpath(folder.strip())
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError:
            raise ValueError(f"받은 파일 폴더를 만들 수 없습니다: {folder}") from None
        with d._settings_lock:
            cfg = st.read_settings()
            cfg["prepare"]["download_dir"] = folder
            if not st.write_settings(cfg):
                raise RuntimeError("설정 파일을 저장하지 못했습니다.")
    n = body.get("parallel")
    if n is not None:
        if not isinstance(n, int) or isinstance(n, bool) or not st.PARALLEL_MIN <= n <= st.PARALLEL_MAX:
            raise ValueError(f"동시 실행 창 수는 {st.PARALLEL_MIN}~{st.PARALLEL_MAX} 사이여야 합니다.")
        d.set_parallel(n)


def open_observer():
    """설치 폴더의 옵저버를 띄운다 (시험 DRY_RUN 은 띄우지 않는다). 떠 있으면 RuntimeError."""
    if st.observer_open():
        raise RuntimeError(OBSERVER_RUNNING)
    exe = os.path.join(st.program_dir(), OBSERVER_EXE)
    if not os.path.isfile(exe):
        raise FileNotFoundError(f"{OBSERVER_EXE} 이(가) 없습니다: {exe}")
    if not d.DRY_RUN:
        subprocess.Popen([exe], cwd=os.path.dirname(exe), close_fds=True)
    return exe


def open_shots(run_id):
    """그 기록의 화면 사진 폴더 (ACTOR 는 실패 사진을 data_dir 에 둔다 - web_runner.BASE_DIR). 경로는 요청에서 받지 않는다. 모르는 기록이면 None."""
    if not any(r.get("run_id") == run_id for r in st.read_history()):
        return None
    folder = st.data_dir()
    if not d.DRY_RUN:
        try:
            os.startfile(folder)
        except OSError:
            pass
    return folder


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "Observer-Hub/1.0"
    sys_version = ""

    def log_message(self, fmt, *args):
        return

    def _send(self, code, body, ctype, extra=None):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def _local(self):
        """이 서버의 주소로 온 요청인가 - Host 가 127.0.0.1:<포트>/localhost:<포트> (다른 이름으로 끌어다 부른 요청은 거절)."""
        port = self.server.server_address[1]
        return (self.headers.get("Host") or "").lower() in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _same_origin(self):
        """Origin 이 없거나 (브라우저 밖·같은 문서) 이 서버 주소 - 다른 페이지의 fetch 는 거절 (관리 화면 AFTERMARKET_SETUP 과 같은 방식).
        'null'(sandbox iframe·file:// 페이지)도 거절 (검토 2026-11-03)."""
        origin = (self.headers.get("Origin") or "").lower().rstrip("/")
        port = self.server.server_address[1]
        return origin == "" or origin in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")

    def _read_body(self):
        if not (self.headers.get("Content-Type") or "").lower().startswith("application/json"):   # no-cors 단순 요청(text/plain)은 거절
            return None, (415, {"ok": False, "error": "JSON 요청만 받습니다."})
        length = int(self.headers.get("Content-Length") or 0)
        if length < 0 or length > MAX_BODY:
            return None, (413, {"ok": False, "error": "요청이 너무 큽니다."})
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            return None, (400, {"ok": False, "error": "JSON 이 아닙니다."})
        if not isinstance(body, dict):
            return None, (400, {"ok": False, "error": "JSON 객체가 아닙니다."})
        return body, None

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        try:
            parts = urllib.parse.urlsplit(self.path)
            query = urllib.parse.parse_qs(parts.query)
            path = parts.path
            if path == "/healthz":
                return self._send(200, SIGNATURE, "text/plain; charset=utf-8")
            if path in PAGES:
                name, ctype = PAGES[path]
                with open(os.path.join(HUB_DIR, name), "rb") as f:
                    return self._send(200, f.read(), ctype, {"Content-Security-Policy": HTML_CSP} if name.endswith(".html") else None)
            if not path.startswith("/api/"):
                return self._send(404, "not found", "text/plain; charset=utf-8")
            if not self._local():
                return self._json({"ok": False, "error": "허용되지 않은 요청입니다."}, 403)
            if path == "/api/state":
                self._json(state_view())
            elif path == "/api/history":
                period = query.get("period", ["7"])[0]
                days = int(period) if period in HISTORY_PERIODS else 7
                limit = d._int_arg(query, "limit", 300, 1, 2000)
                since = (datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - datetime.timedelta(days=days - 1))
                rows = st.read_history(since=since.isoformat())
                self._json({"summary": d.history_stats(rows), "runs": [d.run_summary(r) for r in rows[:limit]]})
            elif path.startswith("/api/history/"):
                run_id = urllib.parse.unquote(path[len("/api/history/"):])
                rec = next((r for r in st.read_history() if r.get("run_id") == run_id), None)
                self._json(rec if rec is not None else {"ok": False, "error": "not found"}, 200 if rec is not None else 404)
            else:
                self._json({"ok": False, "error": "not found"}, 404)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as e:
            try:
                self._json({"ok": False, "error": type(e).__name__}, 500)
            except Exception:
                pass

    def do_POST(self):
        try:
            path = urllib.parse.urlsplit(self.path).path
            if not self._local() or not self._same_origin():
                return self._json({"ok": False, "error": "허용되지 않은 요청입니다."}, 403)
            body, err = self._read_body()
            if err:
                return self._json(err[1], err[0])
            try:
                if path == "/api/run":
                    run_presets(body.get("presets"))
                    self._json({"ok": True, "message": "ACTOR 를 띄웠습니다. 잠시 뒤 현황에 나타납니다.", "schedule": d.schedule_view()})
                elif path == "/api/stop":
                    code, result = d.stop_rpa()
                    self._json(result, code)
                elif path == "/api/schedule":
                    changed = d.apply_schedule(body)
                    self._json({"ok": True, "changed": changed, "schedule": d.schedule_view()})
                elif path == "/api/settings":
                    save_settings(body)
                    self._json({"ok": True, "settings": state_view()["settings"]})
                elif path == "/api/observer":
                    open_observer()
                    self._json({"ok": True, "message": "옵저버를 열었습니다."})
                elif path == "/api/open":
                    folder = open_shots(str(body.get("run_id") or ""))
                    if folder is None:
                        self._json({"ok": False, "error": "그 기록이 없습니다."}, 404)
                    else:
                        self._json({"ok": True, "folder": folder})
                else:
                    self._json({"ok": False, "error": "not found"}, 404)
            except ValueError as e:
                self._json({"ok": False, "error": str(e)}, 400)
            except RuntimeError as e:
                self._json({"ok": False, "error": str(e)}, 409)
            except FileNotFoundError as e:
                self._json({"ok": False, "error": str(e)}, 500)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as e:
            try:
                self._json({"ok": False, "error": type(e).__name__}, 500)
            except Exception:
                pass


def start(ports=PORTS):
    """빈 포트에 서버를 연다 (127.0.0.1 에만, 독점 - rpa_dashboard.DashboardServer 와 같다). 찾는 쪽은 find_port (/healthz)."""
    for port in ports:
        try:
            httpd = d.DashboardServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    else:
        raise OSError(f"포트 {ports[0]}~{ports[-1]} 를 모두 쓰고 있습니다.")
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.5}, name="observer-hub", daemon=True).start()
    return httpd


# ---------------------------------------------------------------------------
# 작업 스케줄러 (rpa_settings.task_xml 과 같은 모양 - 단독 설치에는 rpa_settings 가 없다)
# ---------------------------------------------------------------------------
def hub_command(program_dir):
    """관제를 켜는 (실행 파일, 인자) - 내장 python\\Observer_Hub.exe (없으면 pythonw.exe) 로 이 파일."""
    exe = os.path.join(program_dir, "python", HUB_EXE)
    if not os.path.isfile(exe):
        exe = os.path.join(program_dir, "python", "pythonw.exe")
    return exe, os.path.join(program_dir, "observer_hub.py")


def task_xml(user, program_dir):
    exe, script = hub_command(program_dir)
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>오토파일럿 옵저버 관제 - 윈도우 로그인 때 창 없이 켠다 (설치 마법사가 등록)</Description></RegistrationInfo>
  <Triggers><LogonTrigger><Enabled>true</Enabled><UserId>{escape(user)}</UserId></LogonTrigger></Triggers>
  <Principals>
    <Principal id="Author"><UserId>{escape(user)}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>HighestAvailable</RunLevel></Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>false</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>5</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec><Command>{escape(exe)}</Command><Arguments>"{escape(script)}"</Arguments><WorkingDirectory>{escape(program_dir)}</WorkingDirectory></Exec>
  </Actions>
</Task>
"""


def run_quiet(args, timeout=60):
    r = subprocess.run(args, capture_output=True, timeout=timeout, creationflags=CREATE_NO_WINDOW)
    return r.returncode, (r.stdout + r.stderr).decode("oem", "replace")


def install_task(run=run_quiet):
    """작업을 등록하고 바로 켠다. 안 되면 RuntimeError."""
    folder = st.data_dir()
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "hub_task.xml")
    with open(path, "w", encoding="utf-16") as f:
        f.write(task_xml(st.process_user(), st.program_dir()))
    try:
        code, out = run(["schtasks", "/Create", "/TN", TASK_NAME, "/XML", path, "/F"])
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    if code != 0:
        raise RuntimeError(f"자동 시작 작업을 등록하지 못했습니다: {out.strip()[-300:]}")
    run(["schtasks", "/Run", "/TN", TASK_NAME])


def remove_task(run=run_quiet):
    run(["schtasks", "/End", "/TN", TASK_NAME])
    run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])


def show_error(text):
    import ctypes
    ctypes.windll.user32.MessageBoxW(None, text, "옵저버 관제", 0x10)


def open_page(run=run_quiet, tell=show_error, wait_sec=10):
    """떠 있는 관제 서버(find_port)를 기본 브라우저로 연다. 없으면 작업 스케줄러 작업을 켜고(관리자 권한은 작업이 가진다 - 이 바로가기는
    승격 없이 돈다) 잠깐 기다렸다 다시 찾는다. 그래도 없으면 알림 창."""
    port = find_port()
    if port is None:
        run(["schtasks", "/Run", "/TN", TASK_NAME])
        end = time.time() + wait_sec
        while port is None and time.time() < end:
            time.sleep(0.5)
            port = find_port()
    if port is None:
        tell(NO_SERVER)
        return 1
    webbrowser.open(f"http://127.0.0.1:{port}/")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="오토파일럿 옵저버 관제")
    ap.add_argument("--port", type=int, help=f"포트 (기본 {PORTS[0]}, 쓰고 있으면 {PORTS[1]}~{PORTS[-1]} 중 빈 것)")
    ap.add_argument("--open", action="store_true", help="관제 화면을 브라우저로 연다 (서버가 없으면 띄운 뒤)")
    ap.add_argument("--install-task", action="store_true", help=f"작업 스케줄러 '{TASK_NAME}' 등록 (설치 파일이 부른다)")
    ap.add_argument("--remove-task", action="store_true", help="그 작업을 지운다 (제거 때)")
    args = ap.parse_args(argv)
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8")
    if not st.standalone():
        print(NOT_STANDALONE)
        return 2
    if args.remove_task:            # 제거는 이 PC 용이 아니어도 (검토 2026-11-03)
        remove_task()
        return 0
    problem = st.standalone_pc_problem()
    if problem:
        print(problem)
        return 3
    if args.install_task:
        try:
            install_task()
        except RuntimeError as e:
            print(e)
            return 1
        return 0
    if args.open:
        return open_page()
    port = find_port()
    if port is not None:
        print(f"관제가 이미 실행 중입니다: http://127.0.0.1:{port}")
        return 0
    try:
        httpd = start((args.port,) if args.port else PORTS)
    except OSError as e:
        print(e)
        return 2
    d.SCHEDULER.resync()
    d.SCHEDULER.start()
    print(f"옵저버 관제: http://127.0.0.1:{httpd.server_address[1]}  (이 PC 에서만)  기록 폴더: {st.status_dir()}", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        d.SCHEDULER.stop.set()
        httpd.shutdown()
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
