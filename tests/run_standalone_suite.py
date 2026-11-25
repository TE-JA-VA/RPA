# -*- coding: utf-8 -*-
"""스탠드얼론 브랜치의 시험을 한꺼번에 돌린다 (종료 코드와 통과·실패 수).
    .venv\\Scripts\\python.exe tests\\run_standalone_suite.py [all|sa|cloud|wsl]
'sa' 는 스탠드얼론 시험만, 'cloud' 는 일반 버전 시험만. 없는 파일은 건너뛴다.
'wsl' 은 WSL(Ubuntu) 의 python3 으로 WSL_TESTS (tests/wsl_lan_smoke.py 와 리눅스 갈래가 있는 ④ 시험) (WSL 이 없으면 건너뜀).
화면 시험(에뮬레이터, scratchpad 의 run_check_web.sh)과 실제 ERPia 를 누르는 시험은 여기 없다."""
import os
import shutil
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
SA = ["tests/test_license.py", "tests/test_local_store_core.py", "tests/test_local_server_http.py", "tests/test_local_store_client.py",
      "tests/test_agent_standalone.py", "tests/test_standalone_e2e.py", "tests/test_program_files_imports.py",
      "tests/test_local_web_api.py", "tests/check_web_local.py",
      # 계획 ③ (설치·빌드)
      "tests/test_build_edition.py", "tests/test_standalone_offline.py", "tests/test_ap_guard.py", "tests/test_settings_standalone.py",
      "tests/test_installer_edition.py", "tests/test_folder_split.py", "tests/test_sandbox_standalone.py", "tests/test_layout.py",
      # 계획 ④ (휴대폰 창구)
      "tests/test_phone_core.py", "tests/test_phone_gate.py", "tests/test_otp_fallback.py", "tests/check_phone_local.py",
      # 사내 서버 ① (여러 PC)
      "tests/test_pc_registry.py", "tests/test_lan_server.py", "tests/test_lan_web.py", "tests/test_lan_e2e.py",
      "tests/test_lan_review_fixes.py", "tests/test_lan_web_tls.py",
      # 사내 서버 ② (사내망·TLS)
      "tests/test_lan_config.py", "tests/test_lan_ca.py", "tests/test_lan_net.py", "tests/test_lan_tls.py", "tests/test_lan_review2.py",
      # 사내 서버 ③ (웹 인증 - 2단계·보안 설정·로그인 이력)
      "tests/test_totp.py", "tests/test_accounts_v2.py", "tests/test_lan_mfa.py", "tests/test_login_log.py",
      "tests/test_lan_mfa_review.py",
      # 사내 서버 ④ (리눅스에 싣기)
      "tests/test_server_log.py", "tests/test_server_license.py", "tests/test_seat.py", "tests/test_server_main.py",
      "tests/test_server_admin.py"]
WSL_DIR = "/mnt/d/AX/RPA_StandAlone/tests/"
# 'wsl' - 리눅스에서 사내 서버 한 번 (사내 서버 ② Task 8) + 리눅스에서만 도는 부분이 있는 ④ 시험
WSL_TESTS = ["wsl_lan_smoke.py", "test_server_log.py", "test_server_license.py", "test_seat.py", "test_server_main.py",
             "test_server_admin.py"]
CLOUD = ["firebase/tests/test_agent.py", "tests/test_fb_backoff.py", "tests/test_cloud_scrub.py", "tests/test_dev_env.py",
         "tests/test_background.py", "tests/test_rpa_update.py", "tests/test_otp_replay.py", "tests/test_build_release.py",
         "tests/test_server_info.py", "tests/test_settings.py", "tests/test_update_helper.py", "tests/test_observer_notes.py",
         "tests/test_module_build.py", "tests/test_encoding.py", "tests/test_ai_rescue.py"]


def wsl():
    """WSL(Ubuntu)의 python3 으로 WSL_TESTS 를 차례로 돈다. WSL·Ubuntu·python3 이 없으면 '건너뜀' (종료 코드 0)."""
    exe = shutil.which("wsl.exe") or os.path.join(os.environ.get("SystemRoot") or r"C:\Windows", "System32", "wsl.exe")
    rel = "tests/" + ", ".join(WSL_TESTS) + " (WSL)"
    probe = None
    if os.name == "nt" and os.path.isfile(exe):
        try:
            probe = subprocess.run([exe, "-d", "Ubuntu", "-e", "python3", "-c", "print('ok')"], capture_output=True, timeout=120)
        except (OSError, subprocess.SubprocessError):
            probe = None
    if probe is None or probe.returncode != 0 or probe.stdout.strip() != b"ok":
        print(f"건너뜀 {rel}  (WSL Ubuntu 의 python3 을 찾지 못했습니다)")
        print("실패한 파일: 0")
        return 0
    bad = 0
    for name in WSL_TESTS:
        r = subprocess.run([exe, "-d", "Ubuntu", "-e", "python3", WSL_DIR + name], capture_output=True, timeout=300)
        out = r.stdout.decode("utf-8", "replace")
        print(f"{'OK  ' if r.returncode == 0 else 'FAIL'} tests/{name} (WSL)  (통과 표시 {out.count('통과]')}개)")
        for ln in [ln.strip() for ln in out.splitlines() if "[실패]" in ln][:8]:
            print("      " + ln[:300])
        if r.returncode != 0:
            bad += 1
            for ln in (out + r.stderr.decode("utf-8", "replace")).strip().splitlines()[-6:]:
                print("      | " + ln[:300])
    print("실패한 파일:", bad)
    return 1 if bad else 0


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which == "wsl":
        return wsl()
    files =(SA if which in ("sa", "all") else []) + (CLOUD if which in ("cloud", "all") else [])
    bad = 0
    for rel in files:
        if not os.path.isfile(os.path.join(ROOT, *rel.split("/"))):
            continue
        r = subprocess.run([PY, rel], cwd=ROOT, capture_output=True, env=dict(os.environ, PYTHONUTF8="1"))
        out = r.stdout.decode("utf-8", "replace")
        failed = [ln.strip() for ln in out.splitlines() if "[실패]" in ln]
        print(f"{'OK  ' if r.returncode == 0 else 'FAIL'} {rel}  (통과 표시 {out.count('통과]')}개)")
        for ln in failed[:8]:
            print("      " + ln[:300])
        if r.returncode != 0:
            bad += 1
            for ln in (out + r.stderr.decode("utf-8", "replace")).strip().splitlines()[-6:]:
                print("      | " + ln[:300])
    try:
        os.remove(os.path.join(ROOT, "ai.json"))      # 시험이 남긴 것 (읽지 않고 지운다)
    except OSError:
        pass
    print("실패한 파일:", bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
