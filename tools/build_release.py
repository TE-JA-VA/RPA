r"""배포판을 만든다 (배포판 구조 1부 8절·2부 6절 - docs/superpowers/specs/2026-09-29-release-layout-design.md,
2026-09-29-installer-design.md).

    .venv\Scripts\python.exe tools\build_release.py [--exes-from <판 폴더>] [--no-setup] [--to-dist]

1. exe 셋을 만든다 (build\release 에). --exes-from 이면 그 판 폴더의 exe 를 가져온다 (exe 소스가 안 바뀐 판)
2. 정해 둔 파일만 D:\AX\배포_<판 번호>\ 에 모은다
3. 판 목록(manifest.json)을 쓴다
4. D:\AX\배포_<판 번호>.zip 으로 압축한다 (맨 위 폴더도 같은 이름 - 손으로 넘기는 대비책)
5. 스스로 확인한다: 압축 목록·지문·들어가면 안 되는 파일·빈 배포 틀, 풀어서 exe 셋 --check, 내장 파이썬 tkinter
6. 설치 파일 D:\AX\AFTER_MARKET_RPA_Setup_<판 번호>.exe 를 만든다 (Inno Setup, release/installer.iss). --no-setup 이면 건너뛴다
비밀번호·쿠키·서비스 계정 키는 어떤 경우에도 배포판에 들어가지 않는다 (5번이 막는다. 설치 파일은 5번을 통과한 판 폴더로만 만든다).
"""
import argparse
import datetime
import fnmatch
import hashlib
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile

import win32api
import win32con
import win32verstamp

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (REPO, os.path.join(REPO, "firebase", "agent")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import background as bg  # noqa: E402
import rpa_status as st  # noqa: E402

OUT_ROOT = r"D:\AX"
RUNTIME_ROOT = r"D:\AX\runtime"           # python\ (처음 한 번 배포_20260928_3 에서 복사)
RUNTIME_DIRS = ("python",)                # 브라우저(ms-playwright 713MB)는 안 싣는다 - 깔린 Edge 를 쓴다 (2026-10-06, web_replay.edge)
EXES = {"ERPia_RPA.exe": "run_routine.py", "Prepare_RPA.exe": "web_runner.py", "Prepare_Observer.exe": "rpa_observer.py"}
# (배포판 안 자리, 저장소 안 원본). exe 와 함께 판 목록에 지문으로 들어간다
PROGRAM_FILES = [
    ("Run_All.bat", "Run_All.bat"),
    ("rpa_status.py", "rpa_status.py"),
    ("rpa_dashboard.py", "rpa_dashboard.py"),
    ("rpa_settings.py", "rpa_settings.py"),                                   # 설정 창 (2부)
    ("AFTER_MARKET.ico", "release/AFTER_MARKET.ico"),                         # 설정 창·바로 가기 아이콘 (tools/make_icon.py)
    ("AFTER_MARKET_PREPARE.ico", "release/AFTER_MARKET_PREPARE.ico"),         # 프리페어·옵저버 창의 주황 A (샌드박스가 exe 와 견준다)
    ("firebase/agent/agent.py", "firebase/agent/agent.py"),
    ("firebase/agent/fb.py", "firebase/agent/fb.py"),
    ("firebase/agent/secret.py", "firebase/agent/secret.py"),
    ("firebase/agent/background.py", "firebase/agent/background.py"),         # 에이전트 감독 (2부)
    ("firebase/agent/에이전트_시작.bat", "firebase/agent/에이전트_시작.bat"),
    ("rpa_update.py", "rpa_update.py"),                                       # 자동 업데이트 (3부)
    ("update_helper.py", "update_helper.py"),
    ("update_sign.py", "update_sign.py"),
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
MARKERS = {"ERPia_RPA.exe": "=== 점검 끝", "Prepare_RPA.exe": "쓸 수 있는 Action",
           "Prepare_Observer.exe": "옵저버 점검 끝"}   # --check 의 끝 줄
EXCLUDE = ["numpy", "yaml", "scipy", "pandas", "torch", "cv2", "matplotlib", "networkx", "graphify"]
# pywinauto 가 부르는 win32ui 는 MFC DLL 을 쓰는데, 이 PC 에는 System32 에만 있고 Nuitka 는 System32 를 안 뒤져
# 말없이 뺀다 → VC++ 재배포 패키지가 없는 PC 에서 exe 가 켜지자마자 ImportError (2026-09-29 노트북). 직접 넣는다
MFC_DLL = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "mfc140u.dll")
NUITKA_YML = os.path.join(REPO, "tools", "nuitka-package.config.yml")   # comtypes typelib 시각 비교 끄기 (파일 안 설명)
# 작업 관리자에 'Python' 대신 AFTER MARKET 으로 보이게 (2026-09-29 요청): 내장 파이썬 exe 를 이 이름으로 복사하고
# 설명 칸(작업 관리자 '프로세스' 탭이 보여 주는 글자)을 바꾼다. 사본은 파이썬 재단 서명이 빠진다 (Defender 는 통과)
BRANDED = {bg.SUPERVISOR_EXE: ("pythonw.exe", "AFTER MARKET RPA 에이전트 감독"),
           bg.AGENT_EXE: ("python.exe", "AFTER MARKET RPA 에이전트")}
# 1단계 시험(2026-09-29)에서 쓴 옵션 그대로 - 설계 문서 7절 '시험 결과'
ICON = os.path.join(REPO, "release", "AFTER_MARKET.ico")
ICON_PREPARE = os.path.join(REPO, "release", "AFTER_MARKET_PREPARE.ico")    # 작업 표시줄에서 루틴과 가르는 주황 A (2026-09-30)
NUITKA_COMMON = (["--onefile", "--assume-yes-for-downloads", "--remove-output",
                  "--include-package=comtypes", "--include-package=pywinauto", "--include-module=win32timezone",
                  f"--include-data-files={MFC_DLL}=mfc140u.dll", f"--user-package-configuration-file={NUITKA_YML}"]
                 + [f"--nofollow-import-to={m}" for m in EXCLUDE])
# Nuitka 는 Zig 에 일반 x86-64 CPU(-march)를 컴파일 때만 준다. 링크 때 Zig 가 붙이는 C 런타임(memcpy 등)은 이 PC 의
# CPU(Ryzen 9700X)에 맞춰 AVX-512 를 써서, AVX-512 가 없는 인텔 노트북에서 exe 가 켜지자마자 0xC000001D 로 죽었다
# (2026-10-02 시연 노트북. 샌드박스는 이 PC 의 CPU 를 그대로 써서 못 잡는다). Nuitka 가 LDFLAGS 를 링크에 붙인다
NUITKA_ENV = {"LDFLAGS": "-march=x86_64"}
PLAYWRIGHT = ["--include-package=playwright", "--include-package-data=playwright"]
TK_PLUGIN = "--enable-plugin=tk-inter"
# 콘솔은 exe 마다: 루틴·프리페어는 로그를 보여 주는 콘솔, 옵저버는 창 프로그램 (attach - 시작 메뉴로 켜면 검은 창이 없고,
# --check 는 부른 쪽이 출력을 받는다)
NUITKA_EXTRA = {"ERPia_RPA.exe": ["--windows-console-mode=force", f"--windows-icon-from-ico={ICON}"],
                "Prepare_RPA.exe": ["--windows-console-mode=force", f"--windows-icon-from-ico={ICON_PREPARE}", *PLAYWRIGHT],
                "Prepare_Observer.exe": ["--windows-console-mode=attach", f"--windows-icon-from-ico={ICON_PREPARE}",
                                         *PLAYWRIGHT, TK_PLUGIN]}
ISS_PATH = os.path.join(REPO, "release", "installer.iss")
# Inno Setup 6 의 ISCC.exe 를 찾는 자리 (이 PC 는 winget 사용자 설치 → LOCALAPPDATA)
ISCC_DIRS = (os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6"),
             os.path.join(os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)", "Inno Setup 6"),
             os.path.join(os.environ.get("ProgramFiles") or r"C:\Program Files", "Inno Setup 6"))


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


def icon_resources(ico_path):
    """.ico 를 exe 자원 모양으로 바꾼다: (RT_GROUP_ICON 자료, 번호 1 부터의 RT_ICON 자료들)."""
    with open(ico_path, "rb") as f:
        data = f.read()
    if data[:4] != b"\0\0\1\0":
        raise ValueError(f"아이콘 파일이 아닙니다: {ico_path}")
    count = struct.unpack_from("<H", data, 4)[0]
    group, images = struct.pack("<HHH", 0, 1, count), []
    for i in range(count):
        w, h, colors, _, planes, bits, size, offset = struct.unpack_from("<BBBBHHII", data, 6 + 16 * i)
        group += struct.pack("<BBBBHHIH", w, h, colors, 0, planes or 1, bits, size, i + 1)   # 파일 속 위치 대신 그림 번호
        images.append(data[offset:offset + size])
    return group, images


def brand_exe(src, dst, description, version, icon=None):
    """src 를 dst 로 복사하고 버전 정보(설명·회사·제품)를 바꾼다. 원래 있던 언어 자리에 덮어써 한 벌만 남긴다
    (win32verstamp.stamp 를 그대로 쓰면 중립 언어로 한 벌이 더 생겨 옛 'Python' 이 남는다).
    icon(.ico)을 주면 파이썬 아이콘을 모두 지우고 그 아이콘 한 벌을 넣는다 (작업 관리자·탐색기에 보이는 것)."""
    shutil.copy2(src, dst)
    h = win32api.LoadLibraryEx(dst, 0, win32con.LOAD_LIBRARY_AS_DATAFILE)
    try:
        langs = win32api.EnumResourceLanguages(h, 16, 1)          # RT_VERSION, 이름 1
        old_icons = [(rt, n, lang) for rt in (win32con.RT_GROUP_ICON, win32con.RT_ICON) if icon
                     for n in win32api.EnumResourceNames(h, rt) for lang in win32api.EnumResourceLanguages(h, rt, n)]
    finally:
        win32api.FreeLibrary(h)
    text = {"CompanyName": "AFTER MARKET", "FileDescription": description, "ProductName": "AFTER MARKET RPA",
            "FileVersion": version, "ProductVersion": version,
            "InternalName": os.path.basename(dst), "OriginalFilename": os.path.basename(dst)}
    vs = win32verstamp.VS_VERSION_INFO(*[int(x) for x in version.split(".")], text,
                                       {"Translation": struct.pack("hh", 0x409, 1252)}, 0, 0)
    u = win32api.BeginUpdateResource(dst, 0)
    for lang in langs:
        win32api.UpdateResource(u, 16, 1, vs, lang)
    if icon:
        for rt, n, lang in old_icons:
            win32api.UpdateResource(u, rt, n, None, lang)          # 자료 없이 쓰면 지워진다
        group, images = icon_resources(icon)
        for i, img in enumerate(images, 1):
            win32api.UpdateResource(u, win32con.RT_ICON, i, img, langs[0])
        win32api.UpdateResource(u, win32con.RT_GROUP_ICON, 1, group, langs[0])
    win32api.EndUpdateResource(u, 0)


def collect(out_dir, exe_dir, repo=REPO, runtime_root=RUNTIME_ROOT, version="0.0.0.0"):
    """배포판 폴더를 모은다. 판 목록에 들어갈 상대 경로('/')를 돌려준다. 이미 있으면 멈춘다 (덮어쓰지 않는다).
    version 은 AFTER MARKET 파이썬 사본의 파일 버전 (num_version 모양)."""
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
    for name, (src, desc) in BRANDED.items():           # 아이콘은 위 PROGRAM_FILES 가 판 폴더에 넣은 사본
        brand_exe(os.path.join(out_dir, "python", src), os.path.join(out_dir, "python", name), desc, version,
                  icon=os.path.join(out_dir, "AFTER_MARKET.ico"))
        program.append(f"python/{name}")
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
    man = {
        "format": st.MANIFEST_FORMAT,
        "version": version,
        "built_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "builder": builder,
        "runtime": {"python": _runtime_python(out_dir)},
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
    """배포 틀에 비밀이나 우리 회사 값이 있으면 문제. 로그인(AdminCode·ID·PW)·사이트 ID·PW 와 물류 택배사·박스·운임은
    비어야 한다 (물류 값은 업체마다 설정 창에서 넣는다 - 2026-09-30). 값은 찍지 않는다."""
    out = []
    login = cfg.get("LogIn") if isinstance(cfg.get("LogIn"), dict) else {}
    out += [f"배포 틀의 LogIn.{k} 가 비어 있지 않습니다" for k in ("AdminCode", "ID", "PW") if login.get(k)]
    logistic = cfg.get("Logistic") if isinstance(cfg.get("Logistic"), dict) else {}
    out += [f"배포 틀의 Logistic.{k} 가 비어 있지 않습니다 (업체마다 설정 창에서 넣는다)"
            for k in ("cboTag", "cboTagAmt", "cboBeasong_Gu_Apply") if logistic.get(k)]
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
    """압축을 임시 폴더에 풀고 exe 셋을 임시 설정으로 --check 한다. 끝 줄이 찍히면 통과
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


def tcl_tk_dirs(dest):
    """tkinter 가 쓰는 Tcl·Tk 라이브러리 폴더 (Nuitka tk-inter 에 넘길 것). 파이썬 3.14 의 Tcl/Tk 9 는 라이브러리가
    tcl90.dll·tcl9tk90.dll 안 zipfs 에 있어 Nuitka 가 못 찾는다 (2026-09-30) → dest\\tcltk 에 꺼내 그 자리를 돌려준다.
    진짜 폴더면 그대로 쓴다."""
    import tkinter
    root = tkinter.Tk()
    try:
        root.withdraw()
        out = []
        for name, src in (("tcl", root.tk.eval("info library")), ("tk", root.tk.eval("set tk_library"))):
            if os.path.isdir(src):
                out.append(src)
                continue
            dst = os.path.join(dest, "tcltk", name)
            shutil.rmtree(dst, ignore_errors=True)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            root.tk.eval(f"file copy -force {{{src}}} {{{dst.replace(os.sep, '/')}}}")
            out.append(dst)
        return tuple(out)
    finally:
        root.destroy()


def nuitka_command(py, exe, work_dir, tk_dirs=None):
    """exe 하나를 만드는 Nuitka 명령. tk-inter 를 쓰는 exe 는 tk_dirs (tcl_tk_dirs 의 결과) 가 있어야 한다."""
    extra = list(NUITKA_EXTRA[exe])
    if TK_PLUGIN in extra:
        extra += [f"--tcl-library-dir={tk_dirs[0]}", f"--tk-library-dir={tk_dirs[1]}"]
    return [py, "-m", "nuitka", *NUITKA_COMMON, *extra, f"--output-dir={work_dir}", f"--output-filename={exe}",
            os.path.join(REPO, EXES[exe])]


def build_exes(work_dir, only=None):
    """exe 들(only 를 주면 그것만)을 Nuitka 로 work_dir 에 만든다. 판 목록의 builder 칸 글자를 돌려준다
    ("nuitka 4.2.2 · python 3.14.7"). 옵저버(tk-inter)가 Nuitka 로만 돼서 PyInstaller 선택지는 뺐다 (2026-10-02)."""
    os.makedirs(work_dir, exist_ok=True)
    py = sys.executable
    tk_dirs = None
    for exe in (only or EXES):
        if TK_PLUGIN in NUITKA_EXTRA[exe] and tk_dirs is None:
            tk_dirs = tcl_tk_dirs(work_dir)
        subprocess.run(nuitka_command(py, exe, work_dir, tk_dirs), cwd=REPO, check=True, env=dict(os.environ, **NUITKA_ENV))
    ver = subprocess.run([py, "-m", "nuitka", "--version"], capture_output=True, text=True, check=True).stdout.split()[0]
    return f"nuitka {ver} · python {platform.python_version()}"


def reuse_exes(src_dir, work_dir):
    """exe 들을 새로 만들지 않고 src_dir(판 폴더)에서 work_dir 로 복사한다. 판 목록 builder 칸 글자를 돌려준다."""
    missing = [exe for exe in EXES if not os.path.isfile(os.path.join(src_dir, exe))]
    if missing:
        raise FileNotFoundError(f"{src_dir} 에 {', '.join(missing)} 가 없습니다 (옵저버가 없던 옛 판) - "
                                "--exes-from 없이 새로 빌드하세요")
    os.makedirs(work_dir, exist_ok=True)
    for exe in EXES:
        shutil.copy2(os.path.join(src_dir, exe), os.path.join(work_dir, exe))
    try:
        with open(os.path.join(src_dir, st.MANIFEST_NAME), encoding="utf-8") as f:
            man = json.load(f)
        return f"{man.get('builder') or '?'} (판 {man.get('version') or '?'} 에서 가져옴)"
    except (OSError, ValueError):
        return f"? ({os.path.basename(os.path.normpath(src_dir))} 에서 가져옴)"


def runtime_has_tkinter(root):
    """root\\python 의 내장 파이썬이 tkinter 를 불러오나 (설정 창이 쓴다)."""
    try:
        r = subprocess.run([os.path.join(root, "python", "python.exe"), "-c", "import tkinter"],
                           capture_output=True, timeout=60)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def find_iscc(dirs=ISCC_DIRS):
    """ISCC.exe 경로, 없으면 None."""
    for d in dirs:
        path = os.path.join(d, "ISCC.exe")
        if os.path.isfile(path):
            return path
    return None


def num_version(version):
    """파일 속성용 판 번호: 2026.09.29-5 → 2026.9.29.5 (숫자 넷)."""
    day, n = version.split("-")
    return ".".join(str(int(p)) for p in day.split(".") + [n])


def setup_name(version):
    return f"AFTER_MARKET_RPA_Setup_{version}.exe"


def iscc_command(iscc, out_dir, version, out_root=OUT_ROOT, iss=ISS_PATH):
    return [iscc, "/Qp", f"/DAppVersion={version}", f"/DNumVersion={num_version(version)}", f"/DSourceDir={out_dir}",
            f"/O{out_root}", f"/F{setup_name(version)[:-4]}", iss]


def build_setup(out_dir, version, out_root=OUT_ROOT):
    """판 폴더로 설치 파일을 만든다. 경로를 돌려준다. ISCC 가 없거나 컴파일이 안 되면 RuntimeError."""
    iscc = find_iscc()
    if not iscc:
        raise RuntimeError("Inno Setup(ISCC.exe) 이 없습니다. winget install JRSoftware.InnoSetup --scope user 로 설치하거나 "
                           "--no-setup 으로 건너뛰세요")
    r = subprocess.run(iscc_command(iscc, out_dir, version, out_root), capture_output=True)
    path = os.path.join(out_root, setup_name(version))
    if r.returncode != 0 or not os.path.isfile(path):
        raise RuntimeError(f"설치 파일을 만들지 못했습니다 (ISCC {r.returncode}): "
                           f"{(r.stdout + r.stderr)[-500:].decode('utf-8', 'replace')}")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="배포판을 만든다")
    ap.add_argument("--to-dist", action="store_true",
                    help="exe 셋을 이 PC 의 dist 에도 복사한다 (설정 파일은 건드리지 않는다)")
    ap.add_argument("--exes-from", metavar="판폴더", help="exe 셋을 만들지 않고 이 판 폴더에서 가져온다 (exe 소스가 안 바뀐 판)")
    ap.add_argument("--no-setup", action="store_true", help="설치 파일(setup.exe)을 만들지 않는다")
    args = ap.parse_args(argv)
    version = next_version(OUT_ROOT, datetime.date.today())
    work = os.path.join(REPO, "build", "release")
    print(f"판 {version} 을 만듭니다 ({f'exe 는 {args.exes_from} 에서' if args.exes_from else 'Nuitka'})")
    try:
        builder = reuse_exes(args.exes_from, work) if args.exes_from else build_exes(work)
    except (FileNotFoundError, RuntimeError) as e:
        print("  문제:", e)
        return 1
    out_dir = os.path.join(OUT_ROOT, f"배포_{version}")
    program = collect(out_dir, work, version=num_version(version))
    man = write_manifest(out_dir, version, builder, program)
    zip_path = out_dir + ".zip"
    make_zip(out_dir, zip_path)
    problems = verify_zip(zip_path, man, program, [rel for rel, _ in OTHER_FILES]) + smoke_check(zip_path)
    if not runtime_has_tkinter(out_dir):
        problems.append("내장 파이썬에 tkinter 가 없습니다 - 설정 창이 뜨지 않습니다 (2부 6절)")
    for p in problems:
        print("  문제:", p)
    if problems:
        print(f"배포판에 문제가 {len(problems)}건 있습니다. {zip_path} 를 쓰지 마세요")
        return 1
    if not args.no_setup:
        try:
            setup = build_setup(out_dir, version)
        except RuntimeError as e:
            print("  문제:", e)
            return 1
        print(f"  설치 파일 {setup}  ({os.path.getsize(setup) // 2 ** 20}MB)")
    if args.to_dist:
        for exe in EXES:
            shutil.copy2(os.path.join(out_dir, exe), os.path.join(REPO, "dist", exe))
        print("  dist 에 exe 셋을 복사했습니다 (설정 파일은 그대로)")
    print(f"판 {version}  {zip_path}  ({os.path.getsize(zip_path) // 2 ** 20}MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
