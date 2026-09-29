r"""설치 파일을 윈도우 샌드박스에서 시험한다 (설계 9절). 이 PC 에는 설치하지 않는다.

    .venv\Scripts\python.exe tools\sandbox_test.py D:\AX\AFTER_MARKET_RPA_Setup_<판>.exe

윈도우 샌드박스 기능이 켜져 있어야 한다 (관리자 PowerShell: Enable-WindowsOptionalFeature -Online
-FeatureName Containers-DisposableClientVM -All, 재부팅). 샌드박스 안에서 tools\sandbox_inner.ps1 이 조용한 설치 →
확인 → 가짜 설정으로 에이전트 → 다시 설치 → 설정 창 사진 → 조용한 제거를 하고 결과를 적은 뒤 샌드박스를 끈다.
결과는 임시 폴더의 out\results.txt·settings.png·setup*.log·agent_log1.txt. 샌드박스 안의 인터넷을 쓴다
(에이전트가 가짜 기계 계정으로 로그인을 한 번 시도해 거부당한다).
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SANDBOX = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsSandbox.exe")
WSB = """<Configuration>
  <MappedFolders><MappedFolder><HostFolder>{work}</HostFolder><SandboxFolder>C:\\test</SandboxFolder><ReadOnly>false</ReadOnly></MappedFolder></MappedFolders>
  <LogonCommand><Command>powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\\test\\inner.ps1</Command></LogonCommand>
  <MemoryInMB>4096</MemoryInMB>
</Configuration>
"""


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or not os.path.isfile(args[0]):
        print(__doc__)
        return 2
    if not os.path.isfile(SANDBOX):
        print("윈도우 샌드박스가 꺼져 있습니다 (위 설명의 명령으로 켜고 재부팅)")
        return 2
    work = tempfile.mkdtemp(prefix="rpa_sbx_")          # 영문 경로 (샌드박스에 그대로 붙는다)
    shutil.copy2(args[0], os.path.join(work, "setup.exe"))
    shutil.copy2(os.path.join(HERE, "sandbox_inner.ps1"), os.path.join(work, "inner.ps1"))
    wsb = os.path.join(work, "test.wsb")
    with open(wsb, "w", encoding="utf-8") as f:
        f.write(WSB.format(work=work))
    print(f"샌드박스를 띄웁니다. 결과 폴더: {work}\\out (창을 건드리지 마세요, 끝나면 저절로 닫힙니다)")
    subprocess.Popen([SANDBOX, wsb])
    done = os.path.join(work, "done.txt")
    results = os.path.join(work, "out", "results.txt")
    until = time.time() + 30 * 60
    while time.time() < until and not os.path.exists(done):
        time.sleep(5)
    text = open(results, encoding="utf-8-sig").read() if os.path.exists(results) else "(결과 없음)"
    print(text)
    return 0 if os.path.exists(done) and text.rstrip().endswith("실패: 0") else 1


if __name__ == "__main__":
    sys.exit(main())
