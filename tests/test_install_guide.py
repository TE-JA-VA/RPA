# -*- coding: utf-8 -*-
"""install.sh 의 업체용 안내 글 (NT 깨끗한 설치 2026-11-26 - 업체 안내만으로 막힌 곳).
--help 로 보이는 머리 주석과 설치·activate 가 찍는 안내를 글자로 본다 (실제 실행은 wsl_install.py)."""
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SH = open(os.path.join(ROOT, "server", "install.sh"), encoding="utf-8").read()
LINES = SH.split("\n")
fails = []


def check(name, ok, detail=""):
    print(("[통과] " if ok else "[실패] ") + name + ("" if ok else f"  ({str(detail)[:200]})"))
    if not ok:
        fails.append(name)


def help_text():
    """usage() 가 보여 주는 부분 - 둘째 줄부터 '# ---' 표시 줄 앞까지 (없으면 set -eu 앞까지)."""
    out = []
    for ln in LINES[1:]:
        if ln.startswith("# ---") or ln == "set -eu":
            break
        out.append(re.sub(r"^# ?", "", ln))
    return "\n".join(out)


H = help_text()
check("usage() 는 '# ---' 표시 줄에서 멈춘다", "sed -n '2,/^# ---/p'" in SH, re.findall(r"usage\(\) \{.*?\n.*?\n", SH, re.S)[:1])
check("고객용 --help 에 시험 전용 옵션·환경 변수가 없다 (④ NT 발견 4)",
      not any(x in H for x in ("AP_TEST", "--root", "AP_FAKE_BIN", "--service-user", "wsl_install")), [x for x in ("AP_TEST", "--root") if x in H])
check("시험 전용 설명은 파일에 그대로 남는다 (표시 줄 뒤)", "AP_TEST_SWAP_TAR" in SH and "--root <PREFIX>" in SH)
check(".sig 를 처음 설치 때 어떻게 하는지 (발견 3)", ".sig" in H and "upgrade" in H, "")
for opt in ("--names", "--bundle", "--yes", "--apply-firewall"):
    m = re.search(rf"^\s*{re.escape(opt)}\b.*\S", H, re.M)
    check(f"{opt} 뜻을 따로 한 줄로 설명 (발견 5)", bool(m), opt)
check("--names 는 설치 때만 정해지고 나중에 못 바꾼다고 알림", re.search(r"--names.*(나중|뒤)", H) is not None, "")
cmd = [ln for ln in H.split("\n") if "install.sh install" in ln]
check("--help 의 install 명령은 줄 끝 \\ 로 이어진다 (발견 6)", bool(cmd) and cmd[0].rstrip().endswith("\\"), cmd[:1])
cont = H.split("install.sh install", 1)[1].split("\n")[:3] if cmd else []
check("이어지는 줄도 마지막 줄 말고는 \\ 로 끝난다", len(cont) >= 3 and cont[0].rstrip().endswith("\\") and cont[1].rstrip().endswith("\\"), cont)

body = SH[SH.index("set -eu"):]
check("설치 끝 안내가 요청 파일을 꺼내는 명령을 보여 준다 (발견 7)",
      re.search(r'say ".*sudo install -m 0644 -o .*server_request', body) is not None, "")
check("헷갈리던 '다음 버전도 같은 순서' 를 없앰 (발견 8)", "다음 버전도 같은 순서" not in SH)
check("다음 버전 안내는 풀지 않고 sudo autopilot-server upgrade", re.search(r'say "[^\n]*풀지 않고[^\n]*\n[^\n]*say "[^\n]*sudo /usr/local/sbin/autopilot-server upgrade', body) is not None, "")
hint = body[body.index("admin_hint() {"):body.index("tz_notice() {")]
for c in ("sudo systemctl stop autopilot", "sudo /usr/local/sbin/autopilot-server admin-reset admin --create", "sudo systemctl start autopilot"):
    check(f"관리자 안내 '{c}' (발견 9)", f'"  {c}' in hint, c)
# 끝 검토 Fable 6: RHEL 계열 sudo secure_path 에 /usr/local/sbin 이 없다 → sudo 로 안내하는 autopilot-server 는 전체 경로
bare = [ln.strip() for ln in SH.split("\n") if re.search(r"sudo autopilot-server", ln)]
check("sudo 안내의 autopilot-server 는 모두 /usr/local/sbin/ 전체 경로", not bare, bare)
check("--help 업그레이드도 전체 경로", "sudo /usr/local/sbin/autopilot-server upgrade" in H, "")
# 끝 검토 Codex 2: activate 는 라이선스를 root 전용 사본으로 옮긴 뒤 그 사본을 검사하고 그 사본을 넣는다 (검사 뒤 바꿔치기 막기)
act = body[body.index("cmd_activate() {"):]
act = act[:act.index("\n}\n")]
check("activate 는 받은 경로를 검사·복사에 다시 쓰지 않는다 (H license \"$LICENSE\" 없음)", 'H license "$LICENSE"' not in act and 'cp "$LICENSE" "$ETC' not in act, "")
check("activate 는 사본을 먼저 만든 뒤 그 사본을 검사한다",
      re.search(r'cp "\$LICENSE" "\$_lic"[\s\S]*H license "\$_lic"', act) is not None, "")
print("실패:", len(fails) or 0)
sys.exit(1 if fails else 0)
