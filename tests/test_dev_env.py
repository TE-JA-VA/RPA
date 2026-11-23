# -*- coding: utf-8 -*-
"""설치본은 시험용 RPA_* 경로·이름 환경 변수를 무시한다 (보안 진단 2026-11-23 E-1·C-02).
같은 윈도우 계정의 다른 프로그램이 환경 변수로 설정·기록 자리를 사용자 폴더로 옮기면, 관리자 권한 에이전트가 거기에 AI 키·비밀번호를 썼다.
빌드 점검·샌드박스는 프로그램 폴더(관리자만 쓰는 곳)에 시험 표시 파일을 두고 그때만 따른다.
    .venv\\Scripts\\python.exe tests\\test_dev_env.py
"""
import importlib
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
import rpa_status as st  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


NAMES = ("RPA_PROGRAMDATA", "RPA_USER_CONFIG", "RPA_CRED_FILE", "RPA_STATUS_DIR", "RPA_AGENT_CONFIG", "RPA_AGENT_QUEUE",
         "RPA_AGENT_MUTEX", "RPA_SETTINGS_LOCK", "RPA_OBSERVER_LOCK")


def main():
    prog = tempfile.mkdtemp(prefix="rpa_prog_")
    evil = tempfile.mkdtemp(prefix="rpa_user_")
    keep = {n: os.environ.get(n) for n in NAMES}
    keep_pd = st.program_dir
    st.program_dir = lambda: prog
    try:
        for n in NAMES:
            os.environ[n] = os.path.join(evil, n)
        print("소스(설치본 아님) - 시험용 변수를 따른다")
        check("D1 소스에서는 따른다", st.dev_env("RPA_PROGRAMDATA") == os.path.join(evil, "RPA_PROGRAMDATA")
              and st.install_root() == os.path.join(evil, "RPA_PROGRAMDATA"))

        open(os.path.join(prog, st.MANIFEST_NAME), "w").close()      # 설치본 표시
        print("설치본 - 무시한다")
        check("D2 설치본은 dev_env 가 None", all(st.dev_env(n) is None for n in NAMES))
        check("D3 설정·기록 자리가 사용자 폴더로 옮겨지지 않는다",
              not any(p.startswith(evil) for p in (st.install_root(), st.user_config_path(), st.status_dir(create=False),
                                                   st.cred_file_path())), (st.install_root(), st.user_config_path()))
        import secret
        import agent
        importlib.reload(secret)
        importlib.reload(agent)
        check("D4 에이전트 설정·큐·잠금 이름도 무시한다", not secret.CONFIG_PATH.startswith(evil) and not agent.QUEUE_PATH.startswith(evil)
              and agent.MUTEX_NAME == r"Local\AFTER_MARKET_RPA_AGENT", (secret.CONFIG_PATH, agent.QUEUE_PATH, agent.MUTEX_NAME))

        open(os.path.join(prog, st.TEST_ENV_MARK), "w").close()      # 빌드 점검·샌드박스가 둔다
        print("설치본 + 시험 표시 파일 - 따른다")
        check("D5 프로그램 폴더에 시험 표시가 있으면 따른다", st.dev_env("RPA_USER_CONFIG") == os.path.join(evil, "RPA_USER_CONFIG")
              and st.user_config_path() == os.path.join(evil, "RPA_USER_CONFIG"))
    finally:
        st.program_dir = keep_pd
        for n, v in keep.items():
            if v is None:
                os.environ.pop(n, None)
            else:
                os.environ[n] = v

    print("실행 명령 - 사용자 쪽 파이썬 설정을 따르지 않게 (-E -s)")
    import background as bg
    import rpa_settings as rs
    cmd = bg.agent_command()
    check("D6 에이전트 명령에 -E -s, UTF-8 은 -X utf8 로", cmd[1:5] == ["-E", "-s", "-X", "utf8"], cmd)
    x = rs.task_xml("PC\\me", prog)
    check("D7 에이전트 작업 인자에 -E -s", "<Arguments>-E -s \"" in x, x[x.find("<Arguments>"):][:120])
    x = rs.helper_task_xml("PC\\me", r"C:\r")
    check("D8 업데이트 도우미 작업 인자에 -E -s", "<Arguments>-E -s \"" in x, x[x.find("<Arguments>"):][:120])
    src = open(os.path.join(ROOT, "tools", "launcher.c"), encoding="utf-8").read()
    check("D9 시작 파일이 PYTHON 으로 시작하는 환경 변수를 모두 지운다 (PYTHONPYCACHEPREFIX 등)", "_wenviron" in src and "PYTHON" in src)
    print("\n실패:", fails if fails else "없음")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
