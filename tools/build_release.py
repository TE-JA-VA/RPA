r"""배포판을 만든다 (배포판 구조 1부 8절, docs/superpowers/specs/2026-09-29-release-layout-design.md).

    .venv\Scripts\python.exe tools\build_release.py [--builder nuitka|pyinstaller] [--to-dist]

1. 두 exe 를 만든다 (build\release 에)
2. 정해 둔 파일만 D:\AX\배포_<판 번호>\ 에 모은다
3. 판 목록(manifest.json)을 쓴다
4. D:\AX\배포_<판 번호>.zip 으로 압축한다 (맨 위 폴더도 같은 이름 - D:\AX 에 풀면 바로 가기가 맞는다)
5. 스스로 확인한다: 압축 목록·지문·들어가면 안 되는 파일·빈 배포 틀, 풀어서 두 exe --check
비밀번호·쿠키·서비스 계정 키는 어떤 경우에도 배포판에 들어가지 않는다 (5번이 막는다).
"""
import argparse
import datetime
import fnmatch
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
import rpa_status as st  # noqa: E402

OUT_ROOT = r"D:\AX"
RUNTIME_ROOT = r"D:\AX\runtime"           # python\·ms-playwright\ (처음 한 번 배포_20260928_3 에서 복사)
RUNTIME_DIRS = ("python", "ms-playwright")
EXES = {"ERPia_RPA.exe": "run_routine.py", "Prepare_RPA.exe": "web_runner.py"}
# (배포판 안 자리, 저장소 안 원본). exe 와 함께 판 목록에 지문으로 들어간다
PROGRAM_FILES = [
    ("Run_All.bat", "Run_All.bat"),
    ("rpa_status.py", "rpa_status.py"),
    ("rpa_dashboard.py", "rpa_dashboard.py"),
    ("firebase/agent/agent.py", "firebase/agent/agent.py"),
    ("firebase/agent/fb.py", "firebase/agent/fb.py"),
    ("firebase/agent/secret.py", "firebase/agent/secret.py"),
    ("firebase/agent/에이전트_시작.bat", "firebase/agent/에이전트_시작.bat"),
]
# 판 목록에 넣지 않는 것 (문서·빈 배포 틀). 업데이트가 건드리지 않는다
OTHER_FILES = [
    ("배포안내.txt", "release/배포안내.txt"),
    ("클라우드_안내.txt", "release/클라우드_안내.txt"),
    ("RPA_UserConfig.json", "release/RPA_UserConfig.template.json"),
]
# 런타임 폴더 밖에서 나오면 안 되는 것 (경로 조각마다 맞춰 본다). 내장 파이썬 안의 __pycache__ 는 원래 있다
FORBIDDEN = ["__pycache__", "*.pyc", "*_result.txt", "sms_watch_log.txt", "web_*.png", "sessions",
             "agent_config.json", "queue.jsonl", "history_pos.txt", "에이전트_기록.txt", "*.old", "*.bak",
             "serviceAccountKey.json"]
MARKERS = {"ERPia_RPA.exe": "=== 점검 끝", "Prepare_RPA.exe": "쓸 수 있는 Action"}   # --check 의 끝 줄
EXCLUDE = ["numpy", "yaml", "scipy", "pandas", "torch", "cv2", "matplotlib", "networkx", "graphify"]
# 1단계 시험(2026-09-29)에서 쓴 옵션 그대로 - 설계 문서 7절 '시험 결과'
NUITKA_COMMON = (["--onefile", "--assume-yes-for-downloads", "--windows-console-mode=force", "--remove-output",
                  "--include-package=comtypes", "--include-package=pywinauto", "--include-module=win32timezone"]
                 + [f"--nofollow-import-to={m}" for m in EXCLUDE])
NUITKA_EXTRA = {"ERPia_RPA.exe": [], "Prepare_RPA.exe": ["--include-package=playwright", "--include-package-data=playwright"]}


def next_version(out_root, today):
    """YYYY.MM.DD-N. 그날 이미 있는 배포_<날짜>-N 폴더·압축의 다음 번호."""
    day = today.strftime("%Y.%m.%d")
    used = [int(m.group(1)) for name in (os.listdir(out_root) if os.path.isdir(out_root) else [])
            if (m := re.fullmatch(rf"배포_{re.escape(day)}-(\d+)(\.zip)?", name))]
    return f"{day}-{max(used, default=0) + 1}"


def _copy(src, out_dir, rel):
    dst = os.path.join(out_dir, *rel.split("/"))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)


def collect(out_dir, exe_dir, repo=REPO, runtime_root=RUNTIME_ROOT):
    """배포판 폴더를 모은다. 판 목록에 들어갈 상대 경로('/')를 돌려준다. 이미 있으면 멈춘다 (덮어쓰지 않는다)."""
    if os.path.exists(out_dir):
        raise FileExistsError(out_dir)
    os.makedirs(out_dir)
    program = []
    for name in EXES:
        _copy(os.path.join(exe_dir, name), out_dir, name)
        program.append(name)
    for rel, src in PROGRAM_FILES:
        _copy(os.path.join(repo, *src.split("/")), out_dir, rel)
        program.append(rel)
    for rel, src in OTHER_FILES:
        _copy(os.path.join(repo, *src.split("/")), out_dir, rel)
    for d in RUNTIME_DIRS:
        shutil.copytree(os.path.join(runtime_root, d), os.path.join(out_dir, d))
    return program


def _runtime_python(out_dir):
    """배포판 내장 파이썬 판 ("3.14.7"). 못 알아내면 "?"."""
    try:
        r = subprocess.run([os.path.join(out_dir, "python", "python.exe"), "-c",
                            "import platform; print(platform.python_version())"],
                           capture_output=True, text=True, timeout=30)
        return r.stdout.strip() or "?"
    except Exception:
        return "?"


def write_manifest(out_dir, version, builder, program):
    """manifest.json 을 쓰고 그 내용을 돌려준다."""
    browsers = sorted(n for n in os.listdir(os.path.join(out_dir, "ms-playwright")) if not n.startswith("."))
    man = {
        "format": st.MANIFEST_FORMAT,
        "version": version,
        "built_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "builder": builder,
        "runtime": {"python": _runtime_python(out_dir), "ms-playwright": browsers},
        "files": {rel: st.file_digest(os.path.join(out_dir, *rel.split("/"))) for rel in program},
    }
    with open(os.path.join(out_dir, st.MANIFEST_NAME), "w", encoding="utf-8", newline="\n") as f:
        json.dump(man, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return man


def make_zip(out_dir, zip_path):
    """out_dir 를 압축한다. 맨 위 폴더는 out_dir 이름. 한글 이름은 UTF-8 표시로 들어간다 (zipfile 이 알아서)."""
    top = os.path.basename(os.path.normpath(out_dir))
    tmp = zip_path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for base, dirs, files in os.walk(out_dir):
            dirs.sort()
            for name in sorted(files):
                full = os.path.join(base, name)
                z.write(full, f"{top}/{os.path.relpath(full, out_dir).replace(os.sep, '/')}")
    os.replace(tmp, zip_path)


def template_problems(cfg):
    """배포 틀에 비밀이 있으면 문제. 로그인(AdminCode·ID·PW)과 사이트 ID·PW 는 비어야 한다. 값은 찍지 않는다."""
    out = []
    login = cfg.get("LogIn") if isinstance(cfg.get("LogIn"), dict) else {}
    out += [f"배포 틀의 LogIn.{k} 가 비어 있지 않습니다" for k in ("AdminCode", "ID", "PW") if login.get(k)]
    for name, site in (cfg.get("Sites") or {}).items():
        if isinstance(site, dict):
            out += [f"배포 틀의 Sites.{name}.{k} 가 비어 있지 않습니다" for k in ("ID", "PW") if site.get(k)]
    return out


def verify_zip(zip_path, man, program, others):
    """압축 자체를 본다. 문제 목록 (빈 목록이면 통과)."""
    problems = []
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        top = names[0].split("/", 1)[0] if names else ""
        inside = {n.split("/", 1)[1] for n in names if "/" in n}
        for rel in program:
            if rel not in inside:
                problems.append(f"없음: {rel}")
            elif hashlib.sha256(z.read(f"{top}/{rel}")).hexdigest() != man["files"][rel]["sha256"]:
                problems.append(f"지문 다름: {rel}")
        ours = {rel for rel in inside if rel.split("/")[0] not in RUNTIME_DIRS}
        for rel in sorted(ours):
            if any(fnmatch.fnmatch(part, pat) for part in rel.split("/") for pat in FORBIDDEN):
                problems.append(f"들어가면 안 되는 파일: {rel}")
        extra = ours - set(program) - set(others) - {st.MANIFEST_NAME}
        problems += [f"모은 목록에 없는 파일: {rel}" for rel in sorted(extra)]
        if "RPA_UserConfig.json" in inside:
            problems += template_problems(json.loads(z.read(f"{top}/RPA_UserConfig.json").decode("utf-8-sig")))
        else:
            problems.append("없음: RPA_UserConfig.json")
    return problems


def found_marker(out, marker):
    """exe 출력(bytes)에 끝 줄 표지가 있나. PyInstaller exe 는 CP949 로 찍고 Nuitka 는 UTF-8 로 찍어 둘 다 본다."""
    return marker.encode("utf-8") in out or marker.encode("cp949") in out


def smoke_check(zip_path, timeout=180):
    """압축을 임시 폴더에 풀고 두 exe 를 임시 설정으로 --check 한다. 끝 줄이 찍히면 통과
    (빈 설정이라 나오는 '문제' 줄과 종료 코드는 보지 않는다)."""
    problems = []
    with tempfile.TemporaryDirectory(prefix="rpa_release_", ignore_cleanup_errors=True) as tmp:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)
        top = os.path.join(tmp, os.listdir(tmp)[0])
        cfg = os.path.join(tmp, "cfg", "RPA_UserConfig.json")
        os.makedirs(os.path.dirname(cfg))
        shutil.copy2(os.path.join(top, "RPA_UserConfig.json"), cfg)
        env = dict(os.environ, RPA_USER_CONFIG=cfg, RPA_PROGRAMDATA=os.path.join(tmp, "programdata"),
                   RPA_STATUS_DIR=os.path.join(tmp, "status"), RPA_UNATTENDED="1")
        for exe, marker in MARKERS.items():
            try:
                r = subprocess.run([os.path.join(top, exe), "--check"], cwd=top, env=env,
                                   capture_output=True, timeout=timeout)
                out = r.stdout + r.stderr
                if not found_marker(out, marker):
                    problems.append(f"{exe} --check 가 끝까지 가지 않았습니다: {out[-300:].decode('utf-8', 'replace')}")
            except subprocess.TimeoutExpired:
                problems.append(f"{exe} --check 가 {timeout}초 안에 끝나지 않았습니다")
            except OSError as e:   # 보안 프로그램이 격리·차단했거나 실행 파일이 깨짐 - 오류 추적 대신 판정으로 끝낸다
                problems.append(f"{exe} 를 실행하지 못했습니다 ({type(e).__name__}: {e})")
    return problems


def build_exes(builder, work_dir):
    """두 exe 를 work_dir 에 만든다. 판 목록의 builder 칸 글자를 돌려준다 ("nuitka 4.2.2 · python 3.14.7")."""
    os.makedirs(work_dir, exist_ok=True)
    py = sys.executable
    if builder == "nuitka":
        for exe, entry in EXES.items():
            subprocess.run([py, "-m", "nuitka", *NUITKA_COMMON, *NUITKA_EXTRA[exe], f"--output-dir={work_dir}",
                            f"--output-filename={exe}", os.path.join(REPO, entry)], cwd=REPO, check=True)
        ver = subprocess.run([py, "-m", "nuitka", "--version"], capture_output=True, text=True,
                             check=True).stdout.split()[0]
    else:
        for spec in ("ERPia_RPA.spec", "Prepare_RPA.spec"):
            subprocess.run([py, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", work_dir,
                            "--workpath", os.path.join(work_dir, "pyi_work"), spec], cwd=REPO, check=True)
        ver = importlib.metadata.version("pyinstaller")
    return f"{builder} {ver} · python {platform.python_version()}"


def main(argv=None):
    ap = argparse.ArgumentParser(description="배포판을 만든다")
    ap.add_argument("--builder", choices=("nuitka", "pyinstaller"), default="nuitka")
    ap.add_argument("--to-dist", action="store_true",
                    help="두 exe 를 이 PC 의 dist 에도 복사한다 (설정 파일은 건드리지 않는다)")
    args = ap.parse_args(argv)
    version = next_version(OUT_ROOT, datetime.date.today())
    work = os.path.join(REPO, "build", "release")
    print(f"판 {version} 을 만듭니다 ({args.builder})")
    builder = build_exes(args.builder, work)
    out_dir = os.path.join(OUT_ROOT, f"배포_{version}")
    program = collect(out_dir, work)
    man = write_manifest(out_dir, version, builder, program)
    zip_path = out_dir + ".zip"
    make_zip(out_dir, zip_path)
    problems = verify_zip(zip_path, man, program, [rel for rel, _ in OTHER_FILES]) + smoke_check(zip_path)
    for p in problems:
        print("  문제:", p)
    if problems:
        print(f"배포판에 문제가 {len(problems)}건 있습니다. {zip_path} 를 쓰지 마세요")
        return 1
    if args.to_dist:
        for exe in EXES:
            shutil.copy2(os.path.join(out_dir, exe), os.path.join(REPO, "dist", exe))
        print("  dist 에 두 exe 를 복사했습니다 (설정 파일은 그대로)")
    print(f"판 {version}  {zip_path}  ({os.path.getsize(zip_path) // 2 ** 20}MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
