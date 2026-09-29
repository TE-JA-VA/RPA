# -*- coding: utf-8 -*-
"""띄운 RPA 가 기록을 시작하기도 전에 끝나면 '시작하지 못함' 이력을 남기는지 (2026-09-29 노트북: exe 가 켜지자마자
ImportError 로 죽었는데 대시보드 기록 탭에 아무것도 없었다). 프로세스는 가짜, 기록 폴더는 임시.

    .venv\\Scripts\\python.exe tests\\test_start_failure.py
"""
import io
import json
import os
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
tmp = tempfile.mkdtemp(prefix="rpa_nostart_")
os.environ["RPA_STATUS_DIR"] = tmp
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rpa_status as st  # noqa: E402
import rpa_dashboard as d  # noqa: E402

fails = []


def check(cond, what, detail=""):
    print(("PASS " if cond else "FAIL ") + what + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(what)


class Fake:
    def __init__(self):
        self.code = None

    def poll(self):
        return self.code


procs = []
d.subprocess.Popen = lambda *a, **k: procs.append(Fake()) or procs[-1]
d.target_path = lambda target: os.path.join(tmp, d.TARGETS[target][1])   # 파일이 있어야 띄운다
for name in ("Run_All.bat", "ERPia_RPA.exe", "Prepare_RPA.exe"):
    open(os.path.join(tmp, name), "w").close()
TRACE = ('Traceback (most recent call last):\n  File "run_routine.py", line 108, in <module>\n'
         'ImportError: Typelib different than module\n')


def stderr(target, text):
    with open(os.path.join(tmp, f"stderr_{target}.txt"), "w", encoding="utf-8") as f:
        f.write(text)


def written():
    """이력을 쓴 순서대로 (read_history 는 시작 시각 순이라 같은 초에 남긴 것끼리는 순서가 섞인다)."""
    with open(os.path.join(tmp, st.HISTORY_NAME), encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]


def ended(code=1):
    procs[-1].code = code
    return d.launch_state()


# 1. 켜지자마자 죽은 루틴
d.launch("routine", "cloud")
stderr("routine", TRACE)
check(d.launch_state() is not None and st.read_history() == [], "도는 동안에는 아무것도 남기지 않는다")
check(ended() is None, "끝나면 잠금이 풀린다")
h = st.read_history()
r = h[0] if h else {}
check(len(h) == 1 and r.get("program") == "routine" and r.get("state") == "crashed", "루틴 '비정상 종료' 이력 한 건", json.dumps(h, ensure_ascii=False)[:300])
check("시작하지 못했습니다" in (r.get("reason") or "") and "ImportError: Typelib different than module" in r["reason"],
      "까닭에 오류 출력 마지막 줄", r.get("reason"))
check("line 108" in " ".join(r.get("log_tail") or []), "오류 출력을 로그 꼬리로", r.get("log_tail"))
check(r.get("run_id") and r.get("started_at") and r.get("finished_at") and r.get("program_label") == "루틴 RPA", "이력 필수 칸", r)
d.launch_state()
check(len(st.read_history()) == 1, "다시 물어도 한 번만 남긴다")

# 2. 제대로 시작한 실행 (띄운 뒤 상태 파일을 썼다) - 끝나고 나면 건드리지 않는다
d.launch("routine", "cloud")
with open(st.status_path("routine"), "w", encoding="utf-8") as f:
    json.dump({"program": "routine", "state": "done", "started_at": st.now_iso()}, f)
stderr("routine", "")
ended(0)
check(len(st.read_history()) == 1, "시작한 실행은 이력을 더하지 않는다 (그 프로그램이 스스로 남긴다)")

# 3. 전체 실행 (bat 은 늘 0 으로 끝난다): 둘 다 시작 못 했으면 둘 다 남긴다
os.remove(st.status_path("routine"))
d.launch("all", "auto")
stderr("all", "ImportError: DLL load failed while importing win32ui\n")
ended(0)
h = written()[-2:]
check(sorted(x["program"] for x in h) == ["prepare", "routine"] and all("win32ui" in x["reason"] for x in h),
      "전체 실행: 프리페어·루틴 각각 '시작하지 못함'", [(x["program"], x["reason"]) for x in h])

# 4. 오류 출력도 없이 끝난 경우
d.launch("prepare", "cloud")
stderr("prepare", "")
ended(3)
r = written()[-1]
check(len(written()) == 4 and r["program"] == "prepare" and "종료 코드 3" in r["reason"], "오류 출력이 없으면 종료 코드를 까닭으로", r["reason"])

shutil.rmtree(tmp, ignore_errors=True)
print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
