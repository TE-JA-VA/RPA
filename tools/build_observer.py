r"""옵저버 단독 설치 파일을 PC 한 대 용으로 만든다 (설계 2026-11-03 Task 10 - 사용자: 미리 받은 PC 한 대에만 설치된다).

    .venv\Scripts\python.exe tools\build_observer.py <PC번호> [--version <버전>]

PC번호 = 그 PC 의 윈도우 MachineGuid (release/PC번호_확인.bat 이 보여 준다, 8-4-4-4-12 16진수). 가장 새(또는 --version 의)
D:\AX\배포_옵저버_<버전> 폴더로 D:\AX\AUTOPILOT_Observer_Setup_<버전>_<PC번호 끝 4글자>.exe 를 만든다.
표시 파일 OBSERVER_STANDALONE 은 PC번호를 채운 사본을 넣는다 (원본 판 폴더는 안 바꾼다). ISCC 에 /DBoundPC 로 넘겨
설치 파일이 그 PC 의 MachineGuid 와 견준다 (release/observer.iss InitializeSetup).
알려진 한계: 설치 파일을 풀어 고치면 우회할 수 있다 - 사내용이라 받아들임.
"""
import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.dirname(HERE), HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import build_release as br  # noqa: E402

GUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_VER_DIR = re.compile(r"배포_옵저버_(\d{4}\.\d\d\.\d\d)-(\d+)")


def valid_pc(text):
    """GUID 꼴(8-4-4-4-12 16진수)이면 소문자로, 아니면 None."""
    pc = (text or "").strip().lower()
    return pc if GUID_RE.fullmatch(pc) else None


def latest_release(out_root=br.OUT_ROOT):
    """가장 새 배포_옵저버_<버전> 폴더 경로, 없으면 None."""
    found = {}
    for name in os.listdir(out_root) if os.path.isdir(out_root) else []:
        m = _VER_DIR.fullmatch(name)
        if m and os.path.isdir(os.path.join(out_root, name)):
            found[os.path.join(out_root, name)] = (m.group(1), int(m.group(2)))
    return max(found, key=found.get) if found else None


def make(pc, version=None, out_root=br.OUT_ROOT, run=subprocess.run, iscc=None):
    """설치 파일을 만들고 경로를 돌려준다. 번호가 틀리거나 판 폴더가 없으면 ValueError, ISCC 가 안 되면 RuntimeError."""
    bound = valid_pc(pc)
    if not bound:
        raise ValueError(f"PC번호가 GUID 꼴(8-4-4-4-12 16진수)이 아닙니다: {pc!r}")
    if version:
        release = os.path.join(out_root, f"배포_옵저버_{version}")
        if not os.path.isdir(release):
            raise ValueError(f"단독 판 폴더가 없습니다: {release}")
    else:
        release = latest_release(out_root)
        if not release:
            raise ValueError(f"{out_root} 에 배포_옵저버_<버전> 폴더가 없습니다 - tools/build_release.py 를 먼저 돌리세요")
        version = os.path.basename(release).removeprefix("배포_옵저버_")
    return br.build_observer_setup(release, version, bound, out_root=out_root, run=run, iscc=iscc)


def main(argv=None):
    ap = argparse.ArgumentParser(description="옵저버 단독 설치 파일 (PC 한 대 용)")
    ap.add_argument("pc", metavar="PC번호", help="그 PC 의 MachineGuid (PC번호_확인.bat)")
    ap.add_argument("--version", metavar="버전", help="배포_옵저버_<버전> 폴더 (없으면 가장 새 것)")
    args = ap.parse_args(argv)
    try:
        path = make(args.pc, args.version)
    except ValueError as e:
        print("  문제:", e)
        return 2
    except RuntimeError as e:
        print("  문제:", e)
        return 1
    print(f"  단독 설치 파일 {path}  ({os.path.getsize(path) // 2 ** 20}MB) - PC {valid_pc(args.pc)} 에서만 설치됩니다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
