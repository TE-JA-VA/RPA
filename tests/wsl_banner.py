# -*- coding: utf-8 -*-
"""install.sh 시작 배너 (AUTO PILOT 큰 글자) - 사람이 터미널에서 돌릴 때만, 색은 터미널이 되는 만큼.

    wsl.exe -d Ubuntu -e python3 /mnt/d/AX/RPA_StandAlone/tests/wsl_banner.py

가짜 터미널은 script(util-linux). 세 명령 모두 인자 없이 불러 아무것도 바꾸기 전에 멈추는 길만 쓴다 (root 여도 안전).
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), "server", "install.sh")
VER = "2099.01.01-7"
ESC = "\x1b["
fails = []
_no = [0]


def check(name, ok, detail=""):
    _no[0] += 1
    print(f"  {_no[0]:2d}. [{'통과' if ok else '실패'}] {name}" + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def tty(cmd, env, cols=100):
    """가짜 터미널에서 sh install.sh <cmd> - 화면 글 (\\r 뺌)."""
    line = f"stty cols {cols} rows 40; sh {SCRIPT} {cmd}"
    r = subprocess.run(["script", "-qec", line, "/dev/null"], env=env, capture_output=True, timeout=60)
    return r.stdout.decode("utf-8", "replace").replace("\r", "")


def env(**kw):
    e = {"PATH": "/usr/bin:/bin", "HOME": "/tmp", "TERM": "xterm", "LANG": "C.UTF-8"}
    e.update(kw)
    return {k: v for k, v in e.items() if v is not None}


tmp = tempfile.mkdtemp(prefix="ap_banner_")
try:
    d = os.path.join(tmp, f"autopilot-server-{VER}", "server")
    os.makedirs(d)
    SCRIPT = os.path.join(d, "install.sh")
    shutil.copy(SRC, SCRIPT)

    out = tty("install", env(COLORTERM="truecolor"))
    check("1,600만 색: 첫 줄 하늘색 █, 그림자 선은 남색", f"{ESC}38;2;34;195;230m█" in out and f"{ESC}38;2;22;32;127m╗" in out, out[:300])
    check("다섯째 줄은 짙은 파랑 (아래로 갈수록 짙게), 줄 끝에서 색을 되돌린다",
          f"{ESC}38;2;44;81;216m█" in out and f"{ESC}0m" in out)
    check("같은 글자가 이어지면 색은 한 번만 (████ 앞에 하나)", f"{ESC}38;2;34;195;230m█████" in out, out[:200])
    plain = re.sub(r"\x1b\[[0-9;]*m", "", out)
    check("색을 빼면 글자 모양 그대로 (첫 줄)",
          " █████╗ ██╗   ██╗████████╗ ██████╗     ██████╗ ██╗██╗      ██████╗ ████████╗" in plain, plain[:300])
    check("명령에 맞는 글과 버전 (install → 사내 서버 설치)", f"사내 서버 설치  {VER}" in out, out[-400:])
    check("배너 뒤에 원래 안내가 그대로 (인자 없으면 멈춤)", "install.sh:" in out and "█" in out
          and out.index("█") < out.index("install.sh:"))
    out = tty("install", env(TERM="xterm-256color"))
    check("256색 터미널: 38;5;38 (첫 줄)", f"{ESC}38;5;38m█" in out and "38;2;" not in out, out[:300])
    out = tty("install", env(TERM="xterm"))
    check("색 8개뿐인 터미널: 기본 색 번호", f"{ESC}96m█" in out and "38;5;" not in out, out[:300])
    out = tty("install", env(COLORTERM="truecolor", NO_COLOR="1"))
    check("NO_COLOR 면 색 없이 글자만", "█" in out and ESC + "3" not in out and ESC + "9" not in out, out[:300])
    out = re.sub(r"\x1b\[[0-9;]*m", "", tty("install", env(LANG="C", COLORTERM="truecolor")))
    check("UTF-8 이 아닌 터미널: # 로 그린 글자", "##### #   #   #" in out and "█" not in out, out[:300])
    out = re.sub(r"\x1b\[[0-9;]*m", "", tty("install", env(COLORTERM="truecolor"), cols=60))
    check("폭 60칸: # 로 그린 작은 글자 (줄 넘김 없게)", "##### #   #   #" in out and "█" not in out, out[:300])
    out = tty("install", env(COLORTERM="truecolor"), cols=40)
    check("폭 40칸: 배너 없음", "█" not in out and "#####" not in out and "install.sh:" in out, out[:300])
    check("activate → 사내 서버 활성화", f"사내 서버 활성화  {VER}" in tty("activate", env()))
    check("upgrade → 사내 서버 업그레이드", f"사내 서버 업그레이드  {VER}" in tty("upgrade", env()))
    r = subprocess.run(["sh", SCRIPT, "install"], env=env(COLORTERM="truecolor"), capture_output=True, timeout=60)
    both = (r.stdout + r.stderr).decode("utf-8", "replace")
    check("터미널이 아니면 (기록·시험·파이프) 배너를 싣지 않는다", "█" not in both and "#####" not in both and ESC not in both
          and "install.sh:" in both, both[:300])
    check("--help 에는 배너 없음", "█" not in tty("--help", env(COLORTERM="truecolor")))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\n실패: {len(fails)}" + ("" if not fails else " - " + ", ".join(fails)))
sys.exit(1 if fails else 0)
