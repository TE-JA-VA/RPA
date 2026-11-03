r"""설치 파일을 윈도우 샌드박스에서 시험한다 (설계 9절). 이 PC 에는 설치하지 않는다.

    .venv\Scripts\python.exe tools\sandbox_test.py [--update] [--from <옛 판 설치 파일>] D:\AX\AFTER_MARKET_RPA_Setup_<판>.exe

윈도우 샌드박스 기능이 켜져 있어야 한다 (관리자 PowerShell: Enable-WindowsOptionalFeature -Online
-FeatureName Containers-DisposableClientVM -All, 재부팅). 샌드박스 안에서 tools\sandbox_inner.ps1 이 조용한 설치 →
확인 → 가짜 설정으로 에이전트 → 다시 설치 → 설정 창 사진 → 조용한 제거를 하고 결과를 적은 뒤 샌드박스를 끈다.
결과는 임시 폴더의 out\results.txt·settings.png·setup*.log·agent_log1.txt. 샌드박스 안의 인터넷을 쓴다
(에이전트가 가짜 에이전트 계정으로 로그인을 한 번 시도해 거부당한다).

--update: 같은 판의 배포 폴더(D:\AX\배포_<판>)로 판 B(rpa_dashboard.py 한 줄 더)·판 C(켜지지 않는 에이전트)를 만들어
시험용 열쇠로 서명해 작업 폴더의 site\ 에 넣는다. 샌드박스 안에서 가짜 호스팅으로 업데이트·되돌리기·켜지지 않는 판·
도중 끊김을 시험한다 (설계 12절). 시험용 비밀 열쇠는 서명 뒤 지우고 공개 열쇠만 site\pub.txt 에 둔다.
--from <옛 판 설치 파일>: 그 옛 판을 깔고 판 B = 새 판 그대로로 업데이트한다 (구조가 바뀐 판으로 넘어가는 전환 시험).
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


def build_site(version_a, release_dir, work, a_manifest=None):
    """release_dir 배포 폴더로 판 B·C 를 만들어 시험용 열쇠로 서명해 work\\site 에 넣는다. (B 판 번호, C 판 번호, 공개 열쇠).
    a_manifest 를 주면 (--from 전환 시험) 설치된 판 A 는 그 옛 판이고, 판 B 는 release_dir 그대로 (파일을 안 바꾼다)."""
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

    def make(version, bodies):
        m = json.loads(json.dumps(man))
        m["version"] = version
        origs = {}
        for rel, body in bodies.items():
            full = os.path.join(scratch, *rel.split("/"))
            origs[full] = open(full, "rb").read()
            with open(full, "wb") as f:
                f.write(body(origs[full]))
            m["files"][rel] = rpa_status.file_digest(full)
            changed.add(m["files"][rel]["sha256"])
        with open(os.path.join(scratch, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)
        publish_release.publish(version, scratch, site, key, memo="샌드박스 시험", deploy=None, set_releases=None)
        for full, orig in origs.items():
            with open(full, "wb") as f:
                f.write(orig)                           # 다음 판도 판 A 에서 출발

    # 판 B 는 감독 exe 도 바꾼다 (끝에 몇 바이트 - 그대로 켜진다): 업데이트 도중 끊기면 새 판 감독이 그 exe 를 쥔 채로
    # 되돌리기가 돈다 (2026-10-16 전환 시험에서 PermissionError - 도우미가 남은 감독을 끝내고 잠긴 파일은 기다려 다시)
    make(vb, {"rpa_dashboard.py": lambda b: b} if a_manifest else
         {"rpa_dashboard.py": lambda b: b.rstrip(b"\r\n") + b"\n# update test B\n",
          "python/AFTER_MARKET_RPA_Supervisor.exe": lambda b: b + b"\0update-test-B"})
    make(vc, {"firebase/agent/agent.py": lambda b: b"import sys; sys.exit(1)\n"})
    have = {f["sha256"] for f in json.load(open(a_manifest, encoding="utf-8"))["files"].values()} if a_manifest else None
    for name in os.listdir(os.path.join(site, "blobs")):    # 판 A 와 같은 파일은 받을 일이 없다 - 작업 폴더를 작게
        if (name in have) if have is not None else (name not in changed):
            os.remove(os.path.join(site, "blobs", name))
    os.remove(key)                                      # 시험용 비밀 열쇠는 남기지 않는다
    shutil.rmtree(scratch)
    with open(os.path.join(site, "pub.txt"), "w", encoding="ascii") as f:
        f.write(pub + "\n")
    with open(os.path.join(site, "versions.txt"), "w", encoding="ascii") as f:
        f.write(f"{vb}\n{vc}\n")
    if a_manifest:
        open(os.path.join(site, "transition.txt"), "w").close()   # sandbox_inner.ps1 이 전환 확인을 더 한다
    return vb, vc, pub


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    update = "--update" in args
    args = [a for a in args if a != "--update"]
    old = None
    if "--from" in args:                                # 전환 시험: 옛 판 설치 파일을 깔고 새 판으로 업데이트 (2026-10-16)
        i = args.index("--from")
        old = args[i + 1] if i + 1 < len(args) else ""
        del args[i:i + 2]
        update = True
        if not os.path.isfile(old):
            print(f"옛 판 설치 파일이 없습니다: {old}")
            return 2
    if len(args) != 1 or not os.path.isfile(args[0]):
        print(__doc__)
        return 2
    if not os.path.isfile(SANDBOX):
        print("윈도우 샌드박스가 꺼져 있습니다 (위 설명의 명령으로 켜고 재부팅)")
        return 2
    work = tempfile.mkdtemp(prefix="rpa_sbx_")          # 영문 경로 (샌드박스에 그대로 붙는다)
    shutil.copy2(old or args[0], os.path.join(work, "setup.exe"))
    shutil.copy2(os.path.join(HERE, "sandbox_inner.ps1"), os.path.join(work, "inner.ps1"))
    if update:
        m = re.search(r"Setup_(.+)\.exe$", os.path.basename(args[0]))
        release = os.path.join(r"D:\AX", f"배포_{m.group(1)}") if m else ""
        if not os.path.isfile(os.path.join(release, "manifest.json")):
            print(f"배포 폴더를 찾지 못했습니다: {release}")
            return 2
        a_man = None
        if old:
            mo = re.search(r"Setup_(.+)\.exe$", os.path.basename(old))
            a_man = os.path.join(r"D:\AX", f"배포_{mo.group(1)}", "manifest.json") if mo else ""
            if not os.path.isfile(a_man):
                print(f"옛 판 배포 폴더를 찾지 못했습니다: {a_man}")
                return 2
        vb, vc, _ = build_site(m.group(1), release, work, a_manifest=a_man)
        print(f"업데이트 시험: {'옛 판 ' + os.path.basename(old) + ' 설치 → ' if old else ''}판 B {vb}, 판 C(켜지지 않음) {vc}")
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
