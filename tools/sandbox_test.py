r"""설치 파일을 윈도우 샌드박스에서 시험한다 (설계 9절). 이 PC 에는 설치하지 않는다.

    .venv\Scripts\python.exe tools\sandbox_test.py [--update] D:\AX\AFTER_MARKET_RPA_Setup_<판>.exe

윈도우 샌드박스 기능이 켜져 있어야 한다 (관리자 PowerShell: Enable-WindowsOptionalFeature -Online
-FeatureName Containers-DisposableClientVM -All, 재부팅). 샌드박스 안에서 tools\sandbox_inner.ps1 이 조용한 설치 →
확인 → 가짜 설정으로 에이전트 → 다시 설치 → 설정 창 사진 → 조용한 제거를 하고 결과를 적은 뒤 샌드박스를 끈다.
결과는 임시 폴더의 out\results.txt·settings.png·setup*.log·agent_log1.txt. 샌드박스 안의 인터넷을 쓴다
(에이전트가 가짜 에이전트 계정으로 로그인을 한 번 시도해 거부당한다).

--update: 같은 판의 배포 폴더(D:\AX\배포_<판>)로 판 B(rpa_dashboard.py 한 줄 더)·판 C(켜지지 않는 에이전트)를 만들어
시험용 열쇠로 서명해 작업 폴더의 site\ 에 넣는다. 샌드박스 안에서 가짜 호스팅으로 업데이트·되돌리기·켜지지 않는 판·
도중 끊김을 시험한다 (설계 12절). 시험용 비밀 열쇠는 서명 뒤 지우고 공개 열쇠만 site\pub.txt 에 둔다.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
for _p in (REPO, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)
SANDBOX = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsSandbox.exe")
WSB = """<Configuration>
  <MappedFolders><MappedFolder><HostFolder>{work}</HostFolder><SandboxFolder>C:\\test</SandboxFolder><ReadOnly>false</ReadOnly></MappedFolder></MappedFolders>
  <LogonCommand><Command>powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\\test\\inner.ps1</Command></LogonCommand>
  <MemoryInMB>4096</MemoryInMB>
</Configuration>
"""


def build_site(version_a, release_dir, work):
    """판 A 의 배포 폴더로 판 B·C 를 만들어 시험용 열쇠로 서명해 work\\site 에 넣는다. (B 판 번호, C 판 번호, 공개 열쇠)."""
    import publish_release
    import rpa_status
    day = version_a.split("-")[0]
    vb, vc = f"{day}-9001", f"{day}-9002"               # VERSION_RE 가 -b/-c 를 받지 않는다
    site = os.path.join(work, "site")
    scratch = os.path.join(work, "rel")                 # 판 A 사본 (영문 경로) - 파일 하나를 바꿔 판 B·C 를 만든다
    shutil.copytree(release_dir, scratch)
    key = os.path.join(work, "test_key.txt")
    pub = publish_release.keygen(key)
    man = json.load(open(os.path.join(scratch, "manifest.json"), encoding="utf-8"))
    changed = set()

    def make(version, rel, body):
        full = os.path.join(scratch, *rel.split("/"))
        orig = open(full, "rb").read()
        with open(full, "wb") as f:
            f.write(body(orig))
        m = json.loads(json.dumps(man))
        m["version"] = version
        m["files"][rel] = rpa_status.file_digest(full)
        changed.add(m["files"][rel]["sha256"])
        with open(os.path.join(scratch, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)
        publish_release.publish(version, scratch, site, key, memo="샌드박스 시험", deploy=None, set_releases=None)
        with open(full, "wb") as f:
            f.write(orig)                               # 다음 판도 판 A 에서 출발

    make(vb, "rpa_dashboard.py", lambda b: b.rstrip(b"\r\n") + b"\n# update test B\n")
    make(vc, "firebase/agent/agent.py", lambda b: b"import sys; sys.exit(1)\n")
    for name in os.listdir(os.path.join(site, "blobs")):    # 판 A 와 같은 파일은 받을 일이 없다 - 작업 폴더를 작게
        if name not in changed:
            os.remove(os.path.join(site, "blobs", name))
    os.remove(key)                                      # 시험용 비밀 열쇠는 남기지 않는다
    shutil.rmtree(scratch)
    with open(os.path.join(site, "pub.txt"), "w", encoding="ascii") as f:
        f.write(pub + "\n")
    with open(os.path.join(site, "versions.txt"), "w", encoding="ascii") as f:
        f.write(f"{vb}\n{vc}\n")
    return vb, vc, pub


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    update = "--update" in args
    args = [a for a in args if a != "--update"]
    if len(args) != 1 or not os.path.isfile(args[0]):
        print(__doc__)
        return 2
    if not os.path.isfile(SANDBOX):
        print("윈도우 샌드박스가 꺼져 있습니다 (위 설명의 명령으로 켜고 재부팅)")
        return 2
    work = tempfile.mkdtemp(prefix="rpa_sbx_")          # 영문 경로 (샌드박스에 그대로 붙는다)
    shutil.copy2(args[0], os.path.join(work, "setup.exe"))
    shutil.copy2(os.path.join(HERE, "sandbox_inner.ps1"), os.path.join(work, "inner.ps1"))
    if update:
        m = re.search(r"Setup_(.+)\.exe$", os.path.basename(args[0]))
        release = os.path.join(r"D:\AX", f"배포_{m.group(1)}") if m else ""
        if not os.path.isfile(os.path.join(release, "manifest.json")):
            print(f"배포 폴더를 찾지 못했습니다: {release}")
            return 2
        vb, vc, _ = build_site(m.group(1), release, work)
        print(f"업데이트 시험: 판 B {vb}, 판 C(켜지지 않음) {vc}")
    wsb = os.path.join(work, "test.wsb")
    with open(wsb, "w", encoding="utf-8") as f:
        f.write(WSB.format(work=work))
    print(f"샌드박스를 띄웁니다. 결과 폴더: {work}\\out (창을 건드리지 마세요, 끝나면 저절로 닫힙니다)")
    subprocess.Popen([SANDBOX, wsb])
    done = os.path.join(work, "done.txt")
    results = os.path.join(work, "out", "results.txt")
    until = time.time() + 45 * 60                       # 업데이트 시험은 3분 점검이 세 번 더 든다
    while time.time() < until and not os.path.exists(done):
        time.sleep(5)
    text = open(results, encoding="utf-8-sig").read() if os.path.exists(results) else "(결과 없음)"
    print(text)
    return 0 if os.path.exists(done) and text.rstrip().endswith("실패: 0") else 1


if __name__ == "__main__":
    sys.exit(main())
