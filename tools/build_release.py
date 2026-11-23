r"""배포판을 만든다 (배포판 구조 1부 8절·2부 6절 - docs/superpowers/specs/2026-09-29-release-layout-design.md,
2026-09-29-installer-design.md).

    .venv\Scripts\python.exe tools\build_release.py [--exes-from <판 폴더>] [--rebuild-all] [--no-setup] [--to-dist]
    .venv\Scripts\python.exe tools\build_release.py --modules [--rebuild-all] [--no-setup]      조각 방식 (아래)

1. exe 셋을 만든다 (build\release 에). 재료(소스·옵션·패키지)가 지난번과 같은 exe 는 build\exe_cache 의 것을 그대로 쓴다 -
   같은 파일이라 PC 가 업데이트 때 다시 받지 않는다. --rebuild-all 이면 모두 새로. --exes-from 이면 그 판 폴더의 exe 를 가져온다
2. 정해 둔 파일만 D:\AX\배포_<판 번호>\ 에 모은다
3. 판 목록(manifest.json)을 쓴다
4. D:\AX\배포_<판 번호>.zip 으로 압축한다 (맨 위 폴더도 같은 이름 - 손으로 넘기는 대비책)
5. 스스로 확인한다: 압축 목록·지문·들어가면 안 되는 파일·빈 배포 틀, 풀어서 exe 셋 --check, 내장 파이썬 tkinter
6. 설치 파일 D:\AX\AFTER_MARKET_RPA_Setup_<판 번호>.exe 를 만든다 (Inno Setup, release/installer.iss). --no-setup 이면 건너뛴다
조각 방식 (--modules, docs/superpowers/specs/2026-11-11-module-build-design.md): 1번 대신 우리 파일을 하나씩 조각(app\*.pyd)으로
만들고 (고친 파일만 다시 - 파일 하나에 30초 안쪽), 라이브러리는 컴파일 없이 lib.zip 하나로 싣고 (설치 마무리 rpa_settings.unpack_lib 가
lib\ 에 푼다), exe 셋은 내장 Python 을 켜는 작은 시작 파일(tools/launcher.c)이다. 기본은 옛 방식(--onefile 과 같다)이다.
스탠드얼론 (--edition standalone [--test-build], 계획 docs/superpowers/plans/2026-11-23-standalone-3-install-build.md): 조각 방식으로만,
배포_SA_<버전>·AUTOPILOT_Standalone_Setup_<버전>.exe. --out-root 로 D:\AX 밖에 만들 수 있다 (옛 버전 정리도 그 폴더에서만).
보관 폴더 셋은 지우지 말 것 - 지우면 전부 새로 만들어 PC 가 다 다시 받는다: build\exe_cache (옛 방식 exe), build\pyd_cache (조각),
build\launcher_cache (시작 파일).
비밀번호·쿠키·서비스 계정 키는 어떤 경우에도 배포판에 들어가지 않는다 (5번이 막는다. 설치 파일은 5번을 통과한 판 폴더로만 만든다).
"""
import argparse
import ast
import datetime
import fnmatch
import glob
import hashlib
import importlib.machinery
import importlib.metadata
import importlib.util
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
import server_info  # noqa: E402
import update_sign  # noqa: E402

OUT_ROOT = r"D:\AX"
RUNTIME_ROOT = r"D:\AX\runtime"           # python\ (처음 한 번 배포_20260928_3 에서 복사)
RUNTIME_DIRS = ("python",)                # 브라우저(ms-playwright 713MB)는 안 싣는다 - 깔린 Edge 를 쓴다 (2026-10-06, web_replay.edge)
EXES = {"ERPia_RPA.exe": "run_routine.py", "Prepare_RPA.exe": "web_runner.py", "Prepare_Observer.exe": "rpa_observer.py"}
# (배포판 안 자리, 저장소 안 원본). exe 와 함께 판 목록에 지문으로 들어간다
PROGRAM_FILES = [
    ("Run_All.bat", "Run_All.bat"),
    ("rpa_status.py", "rpa_status.py"),
    ("server_info.py", "server_info.py"),                                     # 서버 주소 한 곳 - 에이전트·업데이트가 부른다 (2026-10-21)
    ("rpa_dashboard.py", "rpa_dashboard.py"),
    ("kr_holidays.py", "kr_holidays.py"),                                     # 공휴일 표 - rpa_dashboard 가 부른다 (2026-10-15 자동 실행 쉬기)
    ("rpa_settings.py", "rpa_settings.py"),                                   # 설정 창 (2부)
    ("preset_transfer.py", "preset_transfer.py"),                             # 프리셋 파일·넣기·되돌리기 (에이전트·옵저버, 2026-10-19)
    ("AFTER_MARKET.ico", "release/AFTER_MARKET.ico"),                         # 오토파일럿: 설정 창·바로 가기·에이전트 (tools/make_icon.py)
    ("AUTOPILOT_PROCESS.ico", "release/AUTOPILOT_PROCESS.ico"),               # PROCESS 오토파일럿 exe (샌드박스가 exe 와 견준다)
    ("AUTOPILOT_ACTOR.ico", "release/AUTOPILOT_ACTOR.ico"),                   # ACTOR 오토파일럿 exe (Prepare_RPA)
    ("AFTER_MARKET_PREPARE.ico", "release/AFTER_MARKET_PREPARE.ico"),         # 옵저버 exe·창·바로 가기 (Prepare_Observer)
    ("firebase/agent/agent.py", "firebase/agent/agent.py"),
    ("firebase/agent/fb.py", "firebase/agent/fb.py"),
    ("firebase/agent/local_store.py", "firebase/agent/local_store.py"),       # 스탠드얼론의 서버 연결 - agent.py 가 늘 불러온다 (일반 버전에도 실어야 켜진다)
    ("firebase/agent/local_server.py", "firebase/agent/local_server.py"),     # 스탠드얼론의 로컬 서버 (일반 버전에서는 돌지 않는다)
    ("firebase/agent/local_web.py", "firebase/agent/local_web.py"),           # 로컬 서버의 웹 창구 - local_server.main 이 불러온다 (웹 파일 firebase/web 은 뒤 계획이 싣는다)
    ("firebase/agent/local_phone.py", "firebase/agent/local_phone.py"),       # 로컬 서버의 휴대폰 창구 (사내망 HTTPS 8782 - 쓸 때만 연다, 계획 ④)
    ("firebase/agent/local_cert.py", "firebase/agent/local_cert.py"),         # 휴대폰 포트의 자체 서명 인증서 - 내장 OpenSSL(libcrypto-3.dll)을 ctypes 로, 자식 프로세스에서
    ("edition.py", "edition.py"),                                             # 버전 종류 (일반·스탠드얼론) - agent·secret·background 가 본다
    ("license_check.py", "license_check.py"),                                 # 스탠드얼론 라이선스 확인
    ("firebase/agent/secret.py", "firebase/agent/secret.py"),
    ("firebase/agent/background.py", "firebase/agent/background.py"),         # 에이전트 감독 (2부)
    ("firebase/agent/에이전트_시작.bat", "firebase/agent/에이전트_시작.bat"),
    ("rpa_update.py", "rpa_update.py"),                                       # 자동 업데이트 (3부)
    ("update_helper.py", "update_helper.py"),
    ("update_sign.py", "update_sign.py"),
    ("playwright/node.exe", ".venv/Lib/site-packages/playwright/driver/node.exe"),   # ACTOR·옵저버가 같이 쓰는 Playwright node (NODE_EXCLUDE)
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
EXCLUDE = ["numpy", "yaml", "scipy", "pandas", "torch", "cv2", "matplotlib", "networkx", "graphify",
           "comtypes.test"]     # --include-package=comtypes 가 시험 코드까지 컴파일했다 (exe 2MB 작아짐, 2026-11-11)
# pywinauto 가 부르는 win32ui 는 MFC DLL 을 쓰는데, 이 PC 에는 System32 에만 있고 Nuitka 는 System32 를 안 뒤져
# 말없이 뺀다 → VC++ 재배포 패키지가 없는 PC 에서 exe 가 켜지자마자 ImportError (2026-09-29 노트북). 직접 넣는다
MFC_DLL = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "mfc140u.dll")
NUITKA_YML = os.path.join(REPO, "tools", "nuitka-package.config.yml")   # comtypes typelib 시각 비교 끄기 (파일 안 설명)
# 작업 관리자에 'Python' 대신 AFTER MARKET 으로 보이게 (2026-09-29 요청): 내장 파이썬 exe 를 이 이름으로 복사하고
# 설명 칸(작업 관리자 '프로세스' 탭이 보여 주는 글자)을 바꾼다. 사본은 파이썬 재단 서명이 빠진다 (Defender 는 통과)
BRANDED = {bg.SUPERVISOR_EXE: ("pythonw.exe", "오토파일럿 에이전트 감독"),
           bg.AGENT_EXE: ("python.exe", "오토파일럿 에이전트")}
# 사본의 파일 버전은 고정 - 판 번호를 찍으면 판마다 바이트가 달라 업데이트 때마다 바뀌었고, 감독이 쥔 채로 끊긴 업데이트를
# 되돌리다 PermissionError 가 났다 (2026-10-16 전환 시험). 같은 파이썬·아이콘이면 판이 바뀌어도 같은 파일이라 PC 가 안 받는다
BRAND_VERSION = "1.0.0.0"
# 1단계 시험(2026-09-29)에서 쓴 옵션 그대로 - 설계 문서 7절 '시험 결과'
ICON = os.path.join(REPO, "release", "AFTER_MARKET.ico")
ICON_PROCESS = os.path.join(REPO, "release", "AUTOPILOT_PROCESS.ico")       # 프로그램마다 날개 색이 다르다 (tools/make_icon.py 의 ICONS)
ICON_ACTOR = os.path.join(REPO, "release", "AUTOPILOT_ACTOR.ico")          # ACTOR 오토파일럿 (Prepare_RPA)
ICON_PREPARE = os.path.join(REPO, "release", "AFTER_MARKET_PREPARE.ico")    # 옵저버 = Prepare_Observer (옛 파일 이름 그대로 - 설치된 바로 가기가 본다)
NUITKA_COMMON = (["--onefile", "--assume-yes-for-downloads", "--remove-output",
                  "--include-package=comtypes", "--include-package=pywinauto", "--include-module=win32timezone",
                  f"--include-data-files={MFC_DLL}=mfc140u.dll", f"--user-package-configuration-file={NUITKA_YML}"]
                 + [f"--nofollow-import-to={m}" for m in EXCLUDE])
# Nuitka 는 Zig 에 일반 x86-64 CPU(-march)를 컴파일 때만 준다. 링크 때 Zig 가 붙이는 C 런타임(memcpy 등)은 이 PC 의
# CPU(Ryzen 9700X)에 맞춰 AVX-512 를 써서, AVX-512 가 없는 인텔 노트북에서 exe 가 켜지자마자 0xC000001D 로 죽었다
# (2026-10-02 시연 노트북. 샌드박스는 이 PC 의 CPU 를 그대로 써서 못 잡는다). Nuitka 가 LDFLAGS 를 링크에 붙인다
NUITKA_ENV = {"LDFLAGS": "-march=x86_64"}
# Playwright 의 node.exe(89MB, 압축해도 exe 마다 30MB 안팎)는 exe 에 싣지 않고 프로그램 폴더 playwright/node.exe 에 한 벌 -
# ACTOR·옵저버가 같이 쓰고 playwright 를 올리기 전엔 지문이 그대로라 업데이트 때 다시 안 받는다 (2026-10-16, web_replay.shared_node).
# Nuitka 는 node 를 데이터가 아니라 DLL 로 싣는다 (standard.nuitka-package.config.yml 'playwright' dlls)
NODE_EXCLUDE = "--noinclude-dlls=playwright/driver/node.exe"
NODE_REL = ("playwright", "node.exe")   # 배포판 안 자리 (web_replay.NODE_REL 과 같게 - PROGRAM_FILES 의 "playwright/node.exe")
PLAYWRIGHT = ["--include-package=playwright", "--include-package-data=playwright", NODE_EXCLUDE]
# 문자 2차인증 중계(otp_relay)가 쓰는 에이전트 모듈 - firebase/agent 에 있어 빌드 때 PYTHONPATH 로 찾게 한다 (설계 13절)
AGENT_DIR = os.path.join(REPO, "firebase", "agent")
EXE_CACHE = os.path.join(REPO, "build", "exe_cache")   # 지난번에 만든 exe 와 재료 지문 (exe_fingerprint) - 재료가 같으면 다시 만들지 않는다
AGENT_MODULES = ["--include-module=fb", "--include-module=secret", "--include-module=local_store"]
TK_PLUGIN = "--enable-plugin=tk-inter"
# 콘솔은 exe 마다: 루틴·프리페어는 로그를 보여 주는 콘솔, 옵저버는 창 프로그램 (attach - 시작 메뉴로 켜면 검은 창이 없고,
# --check 는 부른 쪽이 출력을 받는다)
NUITKA_EXTRA = {"ERPia_RPA.exe": ["--windows-console-mode=force", f"--windows-icon-from-ico={ICON_PROCESS}"],
                "Prepare_RPA.exe": ["--windows-console-mode=force", f"--windows-icon-from-ico={ICON_ACTOR}", *PLAYWRIGHT,
                                    *AGENT_MODULES],
                "Prepare_Observer.exe": ["--windows-console-mode=attach", f"--windows-icon-from-ico={ICON_PREPARE}",
                                         *PLAYWRIGHT, TK_PLUGIN, *AGENT_MODULES]}
# --- 조각 방식 (--modules, 설계 2026-11-11): exe 셋은 내장 Python 을 켜는 작은 시작 파일, 우리 코드는 app\\*.pyd ---
START_MODULES = {exe: os.path.splitext(src)[0] for exe, src in EXES.items()}      # exe → run_main() 을 가진 모듈
MODULE_CACHE = os.path.join(REPO, "build", "pyd_cache")     # 지난번에 만든 조각과 재료 지문 - 지우면 모든 조각을 새로 만들고 PC 가 다 다시 받는다
MODULE_OPTIONS = ["--module", "--assume-yes-for-downloads", "--remove-output", "--no-pyi-file"]

# 라이브러리 묶음(lib.zip)에 실을 것 - 옛 onefile exe 가 싣던 것과 같아야 한다. 빠지면 --check 가 ModuleNotFoundError 로 알려 준다
# ACTOR AI 어시스트 (ai_rescue, 2026-11-16) - Anthropic SDK 와 그 의존성. httpx2·httpcore2 는 불러올 때 자기 dist-info 로 버전을 읽고
# opentelemetry 는 entry_points 로 context 를 찾는다 (dist-info 이름에 버전 번호 - SDK 를 올리면 같이 고칠 것, 없으면 빌드가 멈춘다).
# 스탠드얼론은 AI 를 싣지 않는다 (lib_names)
LIB_NAMES_AI = ["anthropic", "anyio", "docstring_parser", "h11", "httpcore2", "httpx2", "httpx2-2.16.0.dist-info", "httpcore2-2.16.0.dist-info",
                "opentelemetry_api-1.45.2.dist-info", "idna", "jiter",
                "opentelemetry", "pydantic", "pydantic_core", "sniffio", "truststore", "typing_inspection", "annotated_types"]
LIB_NAMES = ["playwright", "pywinauto", "comtypes", "win32", "win32com", "win32comext", "pythonwin", "pywin32_system32",
             "pywin32.pth", "pywin32.version.txt", "pythoncom.py", "greenlet", "pyee", "typing_extensions.py", "PIL", "six.py",
             # 운송장 엑셀 비밀번호 풀기 (PR #43, wellife.unlock_excel) - msoffcrypto 와 그 의존성
             "msoffcrypto", "cryptography", "cffi", "_cffi_backend.cp314-win_amd64.pyd", "olefile", "pycparser",
             *LIB_NAMES_AI]
LIB_SKIP = ("playwright/driver/node.exe",)       # 프로그램 폴더 playwright\\node.exe 한 벌을 쓴다 (NODE_REL)
LIB_SKIP_DIRS = ("comtypes/test",)
LIB_TIME = (2026, 1, 1, 0, 0, 0)                 # 묶음 안 파일 시각 - 고정해야 같은 재료에서 같은 묶음이 나온다 (PC 가 다시 안 받는다)
COMTYPES_CHECK = ("comtypes/_tlib_version_checker.py", b'if not hasattr(sys, "frozen"):', b"if False:")   # nuitka-package.config.yml 과 같은 바꿈
LAUNCHER_SRC = os.path.join(REPO, "tools", "launcher.c")
LAUNCHER_CACHE = os.path.join(REPO, "build", "launcher_cache")   # 시작 파일은 버전이 바뀌어도 같은 파일이어야 한다 - 지우지 말 것
LAUNCHERS = {"ERPia_RPA.exe": (ICON_PROCESS, "PROCESS 오토파일럿", False),        # (아이콘, 작업 관리자 설명, 창 프로그램인가)
             "Prepare_RPA.exe": (ICON_ACTOR, "ACTOR 오토파일럿", False),
             "Prepare_Observer.exe": (ICON_PREPARE, "옵저버", True)}
ISS_PATH = os.path.join(REPO, "release", "installer.iss")
# Inno Setup 6 의 ISCC.exe 를 찾는 자리 (이 PC 는 winget 사용자 설치 → LOCALAPPDATA)
ISCC_DIRS = (os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6"),
             os.path.join(os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)", "Inno Setup 6"),
             os.path.join(os.environ.get("ProgramFiles") or r"C:\Program Files", "Inno Setup 6"))

# --- 버전 종류 (스탠드얼론 계획 ③ Task 1, 설계 2026-11-23-standalone 8절). 인자 edition 의 기본은 모두 "cloud" -
# 그때 재료 목록·명령 줄·파일 이름은 지금 값 그대로다 (tests/test_build_edition.py 가 못박는다) ---
EDITIONS = ("cloud", "standalone")
STANDALONE_URL = "http://127.0.0.1:8781/"        # 스탠드얼론 바로 가기 주소 (local_server.PORT)
# 스탠드얼론에서 빼는 프로그램 파일: 업데이트 도우미(새 설치 파일로 업데이트한다), 라이선스 확인 원본(조각으로만 싣는다 - Task 3)
STANDALONE_DROP = ("update_helper.py", "license_check.py")
WEB_DIR = "firebase/web"
WEB_SKIP = ("firebase-config.js", "data-firebase.js", "edition.js")   # edition.js 는 로컬 서버가 파일 없이 만들어 낸다 (local_web.EDITION_JS)
STANDALONE_OTHER_FILES = [
    ("배포안내_스탠드얼론.txt", "release/배포안내_스탠드얼론.txt"),
    ("PC번호_확인.bat", "release/PC번호_확인.bat"),
    ("RPA_UserConfig.json", "release/RPA_UserConfig.template.json"),
]
MODULE_SKIP = {"standalone": ("ai_rescue",)}     # 스탠드얼론에 싣지 않는 조각 (AI 어시스트 - 없으면 끈다, Task 2)
# 스탠드얼론 설치본(내장 파이썬 밖)에서 나오면 안 되는 것 (경로 조각마다 맞춰 본다)
STANDALONE_FORBIDDEN = ["ai_rescue*", "update_helper.py", "firebase-config.js", "data-firebase.js", "license_check.py", "anthropic",
                        "*signing_key*", "*.testkey.txt"]
EDITION_FILE = "edition.json"                    # edition.FILE_NAME
SIG_FILE = "manifest.sig"                        # rpa_update.SHIPPED_SIG_NAME - 버전 목록 서명 (스탠드얼론만, 목록에는 넣지 않는다)
NO_AI_LINE = "AI 어시스트: 이 버전에는 없습니다"   # ACTOR --check 가 ai_rescue 가 없을 때 찍는 줄 (web_runner.cmd_check) - 일반 버전 smoke_check 는 문제로 본다


def venv_root():
    """빌드에 쓰는 가상 환경 폴더: 저장소의 .venv, 없으면(워크트리) 지금 돌고 있는 가상 환경. 접합(junction)은 만들지 않는다 -
    워크트리를 지우거나 git clean 이 접합을 타고 진짜 .venv 를 지울 수 있다."""
    own = os.path.join(REPO, ".venv")
    if os.path.isdir(own):
        return own
    if sys.prefix != getattr(sys, "base_prefix", sys.prefix):
        return sys.prefix
    raise RuntimeError(".venv 를 찾지 못했습니다 - D:\\AX\\RPA\\.venv\\Scripts\\python.exe 로 돌리십시오")


def site_packages():
    return os.path.join(venv_root(), "Lib", "site-packages")


def _src_path(repo, src):
    """재료 원본의 실제 자리. '.venv/' 로 시작하는데 저장소에 없으면 venv_root() 아래 (워크트리에는 .venv 가 없다)."""
    path = os.path.join(repo, *src.split("/"))
    if src.startswith(".venv/") and not os.path.exists(path):
        return os.path.join(venv_root(), *src.split("/")[1:])
    return path


def blank_server_info(text):
    """server_info.py 의 빈 값 사본 - 맨 위 대입문 이름마다 '이름 = ""' (튜플은 ()). 스탠드얼론은 바깥 서버 주소를 싣지 않는다.
    대입문·문서 글 말고 다른 실행 코드가 있으면 RuntimeError (그 코드가 무엇을 하는지 모른 채 비울 수 없다)."""
    out = ["# 스탠드얼론 - 바깥 서버 주소가 없다 (tools/build_release.py 가 만든다)"]
    for node in ast.parse(text).body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if all(isinstance(t, ast.Name) for t in targets):
                empty = "()" if isinstance(node.value, ast.Tuple) else '""'
                out += [f"{t.id} = {empty}" for t in targets]
                continue
        raise RuntimeError(f"server_info.py {node.lineno}행: 대입문이 아닌 코드가 있어 빈 값 사본을 만들 수 없습니다")
    return "\n".join(out) + "\n"


GENERATED = {"server_info.py": blank_server_info}   # 스탠드얼론: 원본 대신 만든 글을 싣는 자리 → 만드는 함수 (원본 글을 받는다)


def web_files(repo=REPO):
    """업체 웹 파일 [(자리, 원본)] - firebase/web 아래 모든 파일 (글꼴·그림 포함, 이름순), WEB_SKIP 은 뺀다."""
    base = os.path.join(repo, *WEB_DIR.split("/"))
    out = []
    for folder, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            if name not in WEB_SKIP:
                out.append(os.path.relpath(os.path.join(folder, name), repo).replace(os.sep, "/"))
    return [(rel, rel) for rel in sorted(out)]


def program_files(edition="cloud"):
    """버전 목록에 지문으로 드는 프로그램 파일 [(자리, 원본)]. 일반은 PROGRAM_FILES 그대로."""
    if edition == "cloud":
        return PROGRAM_FILES
    return [(rel, src) for rel, src in PROGRAM_FILES if rel not in STANDALONE_DROP] + web_files()


def other_files(edition="cloud"):
    return OTHER_FILES if edition == "cloud" else STANDALONE_OTHER_FILES


def lib_names(edition="cloud"):
    return LIB_NAMES if edition == "cloud" else [n for n in LIB_NAMES if n not in LIB_NAMES_AI]


def release_prefix(edition="cloud", test=False):
    return "배포_" if edition == "cloud" else "배포_SA_TEST_" if test else "배포_SA_"


def next_version(out_root, today, prefix="배포_"):
    """YYYY.MM.DD-N. 그날 이미 있는 <prefix><날짜>-N 폴더·압축의 다음 번호 (버전 종류마다 따로 센다)."""
    day = today.strftime("%Y.%m.%d")
    used = [int(m.group(1)) for name in (os.listdir(out_root) if os.path.isdir(out_root) else [])
            if (m := re.fullmatch(rf"{re.escape(prefix)}{re.escape(day)}-(\d+)(\.zip)?", name))]
    return f"{day}-{max(used, default=0) + 1}"


LOCAL_KEEP = 4   # D:\AX 에 남길 판 - 최신 + 이전 3개 (사용자 2026-10-12, publish_release.KEEP 과 같다)
_VER = r"(\d{4}\.\d\d\.\d\d)-(\d+)"


def prune_local(out_root, keep=LOCAL_KEEP, protect=(), edition="cloud", test=False):
    """out_root 의 판 묶음(배포_<판> 폴더·zip·설치 파일)을 최신 keep 개만 남기고 지운다. protect 는 남길 판 폴더
    (--exes-from 이 가져온 판). 지운 판 목록 (오래된 것부터). 판이 아닌 파일·폴더는 안 건드린다.
    버전 종류마다 자기 접두사의 것만 세고 지운다 (일반 빌드가 스탠드얼론 폴더를, 그 반대도 지우지 않는다)."""
    prefix = release_prefix(edition, test)
    setup_re = re.escape(setup_name("@", edition, test)).replace("@", _VER)
    found = {}
    for name in os.listdir(out_root) if os.path.isdir(out_root) else []:
        m = (re.fullmatch(rf"{re.escape(prefix)}{_VER}(?:\.zip|\.testkey\.txt)?", name) if test else
             re.fullmatch(rf"{re.escape(prefix)}{_VER}(?:\.zip)?", name)) or re.fullmatch(setup_re, name)
        if m:
            found[f"{m.group(1)}-{m.group(2)}"] = (m.group(1), int(m.group(2)))
    order = sorted(found, key=found.get)
    kept = set(order[-keep:]) | {os.path.basename(os.path.normpath(p)).removeprefix(prefix) for p in protect if p}
    removed = [v for v in order if v not in kept]
    for v in removed:
        shutil.rmtree(os.path.join(out_root, f"{prefix}{v}"), ignore_errors=True)
        for f in (f"{prefix}{v}.zip", setup_name(v, edition, test)) + ((f"{prefix}{v}.testkey.txt",) if test else ()):
            if os.path.exists(os.path.join(out_root, f)):
                os.remove(os.path.join(out_root, f))
    return removed


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
    text = {"CompanyName": "오토파일럿", "FileDescription": description, "ProductName": "오토파일럿",
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


def zig_exe():
    """Nuitka 가 받아 둔 zig (C 컴파일러). 없으면 RuntimeError - Nuitka 로 exe 를 한 번 만들면 받아진다."""
    found = sorted(glob.glob(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Nuitka", "Nuitka", "Cache", "downloads", "pip",
                                          "*", "Lib", "site-packages", "ziglang", "zig.exe")))
    if not found:
        raise RuntimeError("zig 를 찾지 못했습니다 (Nuitka 가 받아 두는 C 컴파일러). 옛 방식으로 exe 를 한 번 만들면 받아집니다")
    return found[-1]


def _stamp_launcher(path, icon, description):
    """zig 가 만든 exe 에 아이콘 한 벌과 버전 정보(작업 관리자 설명)를 넣는다. 원래 자원이 없는 exe 라 새로 넣는다."""
    name = os.path.basename(path)
    text = {"CompanyName": "오토파일럿", "FileDescription": description, "ProductName": "오토파일럿",
            "FileVersion": BRAND_VERSION, "ProductVersion": BRAND_VERSION, "InternalName": name, "OriginalFilename": name}
    vs = win32verstamp.VS_VERSION_INFO(*[int(x) for x in BRAND_VERSION.split(".")], text,
                                       {"Translation": struct.pack("hh", 0x409, 1252)}, 0, 0)
    group, images = icon_resources(icon)
    u = win32api.BeginUpdateResource(path, 0)
    win32api.UpdateResource(u, 16, 1, vs, 0x409)
    for i, img in enumerate(images, 1):
        win32api.UpdateResource(u, win32con.RT_ICON, i, img, 0x409)
    win32api.UpdateResource(u, win32con.RT_GROUP_ICON, 1, group, 0x409)
    win32api.EndUpdateResource(u, 0)


def build_launchers(work_dir, cache=LAUNCHER_CACHE):
    """시작 파일 셋(EXES 의 이름)을 work_dir 에 둔다. 재료(launcher.c·아이콘·설명·zig·Python 버전)가 같으면 cache 의 것을
    그대로 쓴다 - 시작 파일은 버전마다 같은 바이트여야 PC 가 다시 받지 않는다."""
    os.makedirs(work_dir, exist_ok=True)
    os.makedirs(cache, exist_ok=True)
    zig = pyver = None
    bases = {}
    for exe, (icon, description, windowed) in LAUNCHERS.items():
        if zig is None:
            zig = zig_exe()
            pyver = f"{sys.version_info.major}{sys.version_info.minor}"
            tool = subprocess.run([zig, "version"], capture_output=True, text=True, check=True).stdout.strip()
        h = hashlib.sha256()
        for part in (open(LAUNCHER_SRC, "rb").read(), open(icon, "rb").read(),
                     f"{description}|{windowed}|{BRAND_VERSION}|{tool}|{pyver}".encode("utf-8")):
            h.update(part + b"\0")
        fp, keep = h.hexdigest(), os.path.join(cache, exe)
        try:
            same = os.path.isfile(keep) and open(keep + ".inputs", encoding="utf-8").read().split() == [fp, _sha(keep)]
        except OSError:
            same = False
        if not same:
            if windowed not in bases:
                tmp = tempfile.mkdtemp(prefix="rpa_launcher_")
                base = os.path.join(tmp, "launcher.exe")
                cmd = [zig, "cc", LAUNCHER_SRC, "-o", base, "-target", "x86_64-windows-gnu", "-mcpu=x86_64", "-O2", "-municode",
                       f"-DPYVER={pyver}"] + (["-DWINDOWED", "-Wl,--subsystem,windows"] if windowed else [])
                r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
                if r.returncode != 0 or not os.path.isfile(base):
                    raise RuntimeError(f"시작 파일을 만들지 못했습니다: {(r.stderr or r.stdout)[-800:]}")
                bases[windowed] = base
            shutil.copy2(bases[windowed], keep)
            _stamp_launcher(keep, icon, description)
            with open(keep + ".inputs", "w", encoding="utf-8") as f:
                f.write(f"{fp}\n{_sha(keep)}\n")
            print(f"  {exe}: 시작 파일을 새로 만들었습니다")
        shutil.copy2(keep, os.path.join(work_dir, exe))
    for base in bases.values():
        shutil.rmtree(os.path.dirname(base), ignore_errors=True)


def collect(out_dir, exe_dir, repo=REPO, runtime_root=RUNTIME_ROOT, version="0.0.0.0", modules=False, edition="cloud", test=False,
            replace=None):
    """배포판 폴더를 모은다. 판 목록에 들어갈 상대 경로('/')를 돌려준다. 이미 있으면 멈춘다 (덮어쓰지 않는다).
    version 은 AFTER MARKET 파이썬 사본의 파일 버전 (num_version 모양).
    스탠드얼론: 프로그램 파일·안내 파일은 그 버전 종류의 목록, server_info.py 는 빈 값 사본(GENERATED), edition.json 을 더 쓰고,
    app\\license_check 조각을 뿌리에도 한 벌 싣는다 (에이전트·로컬 서버가 부른다 - .py 는 싣지 않는다).
    replace {자리: 글} 은 원본 대신 쓸 글 (시험용 빌드의 열쇠를 바꿔 끼운 update_sign.py)."""
    replace = replace or {}
    if os.path.exists(out_dir):
        raise FileExistsError(out_dir)
    os.makedirs(out_dir)
    program = []
    for name in EXES:
        _copy(os.path.join(exe_dir, name), out_dir, name)
        program.append(name)
    if modules:                                         # 조각 방식: 위 exe 는 시작 파일, 우리 코드는 app\\ 의 조각, 라이브러리는 묶음 하나
        suffix = importlib.machinery.EXTENSION_SUFFIXES[0]
        for name in sorted(n for n in os.listdir(os.path.join(exe_dir, "app")) if n.endswith(suffix)):
            _copy(os.path.join(exe_dir, "app", name), out_dir, f"app/{name}")
            program.append(f"app/{name}")
        _copy(os.path.join(repo, "app_start.py"), out_dir, "app/_start.py")
        _copy(os.path.join(exe_dir, "lib.zip"), out_dir, "lib.zip")
        program += ["app/_start.py", "lib.zip"]
        if edition != "cloud":
            guard = "license_check" + suffix
            _copy(os.path.join(exe_dir, "app", guard), out_dir, guard)
            program.append(guard)
    for rel, src in program_files(edition):
        if rel in replace or (edition != "cloud" and rel in GENERATED):
            if rel in replace:
                made = replace[rel]
            else:
                with open(_src_path(repo, src), encoding="utf-8") as f:
                    made = GENERATED[rel](f.read())
            with open(os.path.join(out_dir, *rel.split("/")), "w", encoding="utf-8", newline="\n") as f:
                f.write(made)
        else:
            _copy(_src_path(repo, src), out_dir, rel)
        program.append(rel)
    if edition != "cloud":
        with open(os.path.join(out_dir, EDITION_FILE), "w", encoding="utf-8", newline="\n") as f:
            json.dump({"edition": edition, **({"test_build": True} if test else {})}, f, ensure_ascii=False)
        program.append(EDITION_FILE)
    for rel, src in other_files(edition):
        _copy(_src_path(repo, src), out_dir, rel)
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


def runtime_file_list(out_dir, program):
    """배포판의 내장 파이썬 파일 {"python/…": {"sha256", "size"}} - RUNTIME_DIRS 안의 파일에서 __pycache__ (파이썬이 스스로 쓴다)와
    program 에 이미 있는 것(이름 붙인 exe 둘)을 뺀 것. 내장 파이썬이 바뀐 버전으로 업데이트할 때 쓴다 (rpa_update.runtime_files,
    설계 docs/superpowers/specs/2026-11-20-runtime-update-design.md). 판 점검(파일 변조 감지)은 이 칸을 보지 않는다."""
    have, out = set(program), {}
    for d in RUNTIME_DIRS:
        for base, dirs, files in os.walk(os.path.join(out_dir, d)):
            dirs[:] = sorted(x for x in dirs if x != "__pycache__")
            for name in sorted(files):
                full = os.path.join(base, name)
                rel = os.path.relpath(full, out_dir).replace(os.sep, "/")
                if rel not in have:
                    out[rel] = st.file_digest(full)
    return out


def write_manifest(out_dir, version, builder, program):
    """manifest.json 을 쓰고 그 내용을 돌려준다."""
    man = {
        "format": st.MANIFEST_FORMAT,
        "version": version,
        "built_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "builder": builder,
        "runtime": {"python": _runtime_python(out_dir)},
        "files": {rel: st.file_digest(os.path.join(out_dir, *rel.split("/"))) for rel in program},
        "runtime_files": runtime_file_list(out_dir, program),
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


def verify_zip(zip_path, man, program, others, edition="cloud"):
    """압축 자체를 본다. 문제 목록 (빈 목록이면 통과). 스탠드얼론은 STANDALONE_FORBIDDEN 도 보고, manifest.sig 를 봐준다."""
    forbidden = FORBIDDEN + (STANDALONE_FORBIDDEN if edition != "cloud" else [])
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
        for rel, d in (man.get("runtime_files") or {}).items():      # 내장 파이썬 파일 - 업데이트가 이 지문으로 받는다
            if rel not in inside:
                problems.append(f"없음: {rel}")
            elif hashlib.sha256(z.read(f"{top}/{rel}")).hexdigest() != d["sha256"]:
                problems.append(f"지문 다름: {rel}")
        ours ={rel for rel in inside if rel.split("/")[0] not in RUNTIME_DIRS}
        for rel in sorted(ours):
            if any(fnmatch.fnmatch(part, pat) for part in rel.split("/") for pat in forbidden):
                problems.append(f"들어가면 안 되는 파일: {rel}")
        extra = ours - set(program) - set(others) - {st.MANIFEST_NAME} - ({SIG_FILE} if edition != "cloud" else set())
        problems += [f"모은 목록에 없는 파일: {rel}" for rel in sorted(extra)]
        # 일반 버전 조각 방식은 AI 어시스트 조각을 꼭 싣는다 - 빠지면 web_runner 가 ImportError 를 '이 버전에는 없다' 로 보고
        # 말없이 AI 를 끈다 (검토 2026-11-23). 옛 방식(exe 하나)은 smoke_check 가 --check 출력으로 본다
        if edition == "cloud" and "app/_start.py" in inside and not any(
                rel.startswith("app/") and rel[4:].split(".")[0] == "ai_rescue" and rel.lower().endswith(".pyd") for rel in inside):
            problems.append("없음: app/ai_rescue 조각 (일반 버전은 AI 어시스트를 싣는다)")
        if "RPA_UserConfig.json" in inside:
            problems += template_problems(json.loads(z.read(f"{top}/RPA_UserConfig.json").decode("utf-8-sig")))
        else:
            problems.append("없음: RPA_UserConfig.json")
    return problems


def found_marker(out, marker):
    """exe 출력(bytes)에 끝 줄 표지가 있나. PyInstaller exe 는 CP949 로 찍고 Nuitka 는 UTF-8 로 찍어 둘 다 본다."""
    return marker.encode("utf-8") in out or marker.encode("cp949") in out


def smoke_check(zip_path, timeout=180, edition="cloud"):
    """압축을 임시 폴더에 풀고 exe 셋을 임시 설정으로 --check 한다. 끝 줄이 찍히면 통과
    (빈 설정이라 나오는 '문제' 줄과 종료 코드는 보지 않는다).
    스탠드얼론은 더: exe 셋의 출력에 '라이선스:' 줄, 내장 파이썬으로 agent·local_server·local_web 이 불러와지고,
    lib 를 길에 넣어도 anthropic 이 없다 (AI 를 싣지 않았다)."""
    problems = []
    with tempfile.TemporaryDirectory(prefix="rpa_release_", ignore_cleanup_errors=True) as tmp:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)
        top = os.path.join(tmp, os.listdir(tmp)[0])
        if os.path.isfile(os.path.join(top, "lib.zip")):   # 조각 방식: 설치 마무리가 하는 일 (라이브러리 묶음 풀기)
            import rpa_settings
            try:
                rpa_settings.unpack_lib(top)
            except RuntimeError as e:
                return [str(e)]
        cfg = os.path.join(tmp, "cfg", "RPA_UserConfig.json")
        os.makedirs(os.path.dirname(cfg))
        shutil.copy2(os.path.join(top, "RPA_UserConfig.json"), cfg)
        env = dict(os.environ, RPA_USER_CONFIG=cfg, RPA_PROGRAMDATA=os.path.join(tmp, "programdata"),
                   RPA_STATUS_DIR=os.path.join(tmp, "status"), RPA_UNATTENDED="1")
        # 설치본은 시험 표시가 있어야 위 시험용 자리를 따른다 (rpa_status.TEST_ENV_MARK, 보안 진단 2026-11-23 E-1) - 없으면 이 PC 의 진짜 설정을 본다
        open(os.path.join(top, "test_env.ok"), "w").close()
        for exe, marker in MARKERS.items():
            try:
                r = subprocess.run([os.path.join(top, exe), "--check"], cwd=top, env=env,
                                   capture_output=True, timeout=timeout)
                out = r.stdout + r.stderr
                if not found_marker(out, marker):
                    problems.append(f"{exe} --check 가 끝까지 가지 않았습니다: {out[-300:].decode('utf-8', 'replace')}")
                elif exe == "Prepare_Observer.exe" and not found_marker(out, "브라우저: Microsoft Edge"):   # 따로 둔 node.exe 로 Playwright 가 도는지
                    problems.append(f"{exe} --check 가 브라우저를 띄우지 못했습니다: {out[-300:].decode('utf-8', 'replace')}")
                elif edition != "cloud" and not found_marker(out, "라이선스:"):
                    problems.append(f"{exe} --check 에 라이선스 줄이 없습니다: {out[-300:].decode('utf-8', 'replace')}")
                elif edition == "cloud" and exe == "Prepare_RPA.exe" and found_marker(out, NO_AI_LINE):
                    problems.append(f"{exe} --check: 일반 버전인데 AI 어시스트(ai_rescue)가 실리지 않았습니다")
            except subprocess.TimeoutExpired:
                problems.append(f"{exe} --check 가 {timeout}초 안에 끝나지 않았습니다")
            except OSError as e:   # 보안 프로그램이 격리·차단했거나 실행 파일이 깨짐 - 오류 추적 대신 판정으로 끝낸다
                problems.append(f"{exe} 를 실행하지 못했습니다 ({type(e).__name__}: {e})")
        if edition != "cloud":
            py = os.path.join(top, "python", "python.exe")
            agent_dir = os.path.join(top, "firebase", "agent")
            checks = (("import sys; sys.path[:0] = [sys.argv[1], sys.argv[2]]; import agent, local_server, local_web; print('불러옴')",
                       [agent_dir, top], "불러옴", "내장 파이썬으로 agent·local_server·local_web 을 불러오지 못했습니다"),
                      ("import sys; sys.path.insert(0, sys.argv[1])\ntry:\n    import anthropic\nexcept ModuleNotFoundError:\n    print('없음')",
                       [os.path.join(top, "lib")], "없음", "lib 에 anthropic 이 있습니다 (스탠드얼론은 AI 를 싣지 않는다)"))
            for code, args, want, why in checks:
                try:
                    r = subprocess.run([py, "-I", "-c", code, *args], cwd=top, env=env, capture_output=True, timeout=timeout)
                    if not found_marker(r.stdout, want):
                        problems.append(f"{why}: {(r.stdout + r.stderr)[-300:].decode('utf-8', 'replace')}")
                except (OSError, subprocess.TimeoutExpired) as e:
                    problems.append(f"{why} ({type(e).__name__})")
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


def local_imports(entry, roots=(REPO, AGENT_DIR)):
    """entry 가 차례로 import 하는 저장소 안 .py 파일들 (자기 포함, 함수 안 import 도). exe 재료 지문에 쓴다."""
    seen, todo = set(), [os.path.abspath(entry)]
    while todo:
        path = todo.pop()
        if path in seen:
            continue
        seen.add(path)
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                names = [node.module]
            else:
                continue
            for name in names:
                hit = next((p for p in (os.path.join(r, *name.split(".")) + ".py" for r in roots) if os.path.isfile(p)), None)
                if hit:
                    todo.append(os.path.abspath(hit))
    return sorted(seen)


def exe_sources(exe):
    """exe 에 들어가는 저장소 파이썬 파일: 시작 파일 + --include-module 로 넣는 에이전트 모듈과 그것들이 부르는 것."""
    roots = [os.path.join(REPO, EXES[exe])] + [os.path.join(AGENT_DIR, a.split("=", 1)[1] + ".py")
                                               for a in NUITKA_EXTRA[exe] if a.startswith("--include-module=")]
    return sorted({p for r in roots if os.path.isfile(r) for p in local_imports(r)})


def exe_fingerprint(exe, tool):
    """exe 재료 지문 - 같으면 지난번 exe 를 그대로 쓴다 (Nuitka 는 같은 소스에서도 매번 다른 exe 를 만들어, 안 바뀐 exe 까지
    PC 가 다시 받았다 - 2026-10-16). 재료: 저장소 파이썬 파일, Nuitka 옵션과 옵션이 가리키는 파일(아이콘·DLL·설정),
    빌드 환경 변수, Nuitka·파이썬 버전(tool), 깔린 패키지 버전 전부."""
    h = hashlib.sha256()
    put = lambda *parts: [h.update(str(p).encode("utf-8") + b"\0") for p in parts]
    put(tool, json.dumps(NUITKA_ENV, sort_keys=True))
    cmd = nuitka_command("python", exe, "OUT", ("TCL", "TK"))       # 자리 값 - tcl/tk 폴더는 파이썬 버전을 따른다
    put(*cmd)
    for arg in cmd:
        p = arg.split("=", 1)[-1].split("=", 1)[0]                   # --include-data-files=원본=대상 → 원본
        if os.path.isfile(p):
            put(p)
            h.update(open(p, "rb").read())
    for p in exe_sources(exe):
        put(os.path.relpath(p, REPO) if p.startswith(REPO) else p)
        h.update(open(p, "rb").read())
    put(*sorted(f"{d.metadata['Name']}=={d.version}" for d in importlib.metadata.distributions()))
    # comtypes 가 PC 의 UIA 형식 라이브러리로 만들어 둔 모듈 (--include-package=comtypes 로 exe 셋에 들어간다).
    # 패키지 버전이 같아도 다시 만들어질 수 있다 (검토 2026-10-16 - 이 PC 는 10-15 에 다시 만들어졌다)
    gen = os.path.join(importlib.util.find_spec("comtypes").submodule_search_locations[0], "gen")
    for p in sorted(glob.glob(os.path.join(gen, "*.py"))):
        put(os.path.basename(p))
        h.update(open(p, "rb").read())
    return h.hexdigest()


def _sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


NODE_IN_EXE_MB = 40   # node.exe 를 뺀 ACTOR·옵저버는 25MB 안팎 - 이보다 크면 --noinclude-dlls 가 안 맞은 것 (Nuitka·playwright 를 올린 뒤)


def build_exes(work_dir, only=None, cache=EXE_CACHE, force=False):
    """exe 들(only 를 주면 그것만)을 Nuitka 로 work_dir 에 만든다. 재료 지문(exe_fingerprint)이 cache 에 보관한
    지난번 exe 와 같으면 다시 만들지 않고 그 exe 를 쓴다 (force 면 늘 새로). 판 목록의 builder 칸 글자를 돌려준다
    ("nuitka 4.2.2 · python 3.14.7 (새로 1: …, 그대로 2)"). 옵저버(tk-inter)가 Nuitka 로만 돼서 PyInstaller 선택지는 뺐다 (2026-10-02)."""
    os.makedirs(work_dir, exist_ok=True)
    os.makedirs(cache, exist_ok=True)
    py = sys.executable
    ver = subprocess.run([py, "-m", "nuitka", "--version"], capture_output=True, text=True, check=True).stdout.split()[0]
    tool = f"nuitka {ver} · python {platform.python_version()}"
    tk_dirs = None
    made, kept = [], []
    for exe in (only or EXES):
        fp, keep = exe_fingerprint(exe, tool), os.path.join(cache, exe)
        try:   # .inputs = 재료 지문 + 보관한 exe 의 지문 (보관한 exe 가 깨지거나 바뀌었으면 다시 만든다)
            same = not force and os.path.isfile(keep) and open(keep + ".inputs", encoding="utf-8").read().split() == [fp, _sha(keep)]
        except OSError:
            same = False
        if same:
            shutil.copy2(keep, os.path.join(work_dir, exe))
            kept.append(exe)
            print(f"  {exe}: 재료가 지난번과 같아 그대로 씁니다")
            continue
        if TK_PLUGIN in NUITKA_EXTRA[exe] and tk_dirs is None:
            tk_dirs = tcl_tk_dirs(work_dir)
        env = dict(os.environ, **NUITKA_ENV, PYTHONPATH=os.pathsep.join(filter(None, [AGENT_DIR, os.environ.get("PYTHONPATH")])))
        subprocess.run(nuitka_command(py, exe, work_dir, tk_dirs), cwd=REPO, check=True, env=env)
        built = os.path.join(work_dir, exe)
        if NODE_EXCLUDE in NUITKA_EXTRA[exe] and os.path.getsize(built) > NODE_IN_EXE_MB * 2 ** 20:
            raise RuntimeError(f"{exe} 가 {os.path.getsize(built) // 2 ** 20}MB 입니다 - node.exe 가 다시 들어갔습니다 "
                               f"({NODE_EXCLUDE} 가 안 맞음: Nuitka·playwright 가 node 를 싣는 자리를 확인하세요)")
        shutil.copy2(built, keep)
        with open(keep + ".inputs", "w", encoding="utf-8") as f:              # exe 를 다 보관한 뒤에 지문 - 중간에 죽으면 다음에 다시 만든다
            f.write(f"{fp}\n{_sha(keep)}\n")
        made.append(exe)
    return f"{tool} (새로 {len(made)}{': ' + ', '.join(made) if made else ''}, 그대로 {len(kept)})"


def module_sources(edition="cloud"):
    """조각으로 만들 우리 파이썬 파일 - exe 셋에 들어가던 것 모두 (정렬, 겹치지 않게). 스탠드얼론은 MODULE_SKIP 을 뺀다."""
    skip = MODULE_SKIP.get(edition, ())
    return sorted({p for exe in EXES for p in exe_sources(exe) if os.path.splitext(os.path.basename(p))[0] not in skip})


def _repo_text(rel):
    with open(os.path.join(REPO, *rel.split("/")), encoding="utf-8") as f:
        return f.read()


def swap_key(text, name, hex_value):
    """'<name> = "…"' 줄이 정확히 하나일 때만 그 값을 hex_value 로 바꾼 글. 아니면 RuntimeError (엉뚱한 줄을 바꾸지 않게)."""
    pat = re.compile(rf'^({re.escape(name)} = ")[0-9A-Fa-f]*(")', re.M)
    if len(pat.findall(text)) != 1:
        raise RuntimeError(f"{name} 줄이 정확히 하나가 아닙니다 - 시험용 열쇠를 끼울 수 없습니다")
    return pat.sub(lambda m: m.group(1) + hex_value + m.group(2), text)


def module_overrides(edition="cloud", test_keys=None):
    """원본 대신 컴파일할 글 {조각 이름: (글, 보관하나)}. 스탠드얼론의 server_info 는 빈 값 사본 (보관은 cache\\<버전 종류>).
    test_keys {"update": 공개 열쇠 16진수, "license": …} (시험용 빌드)면 update_sign·license_check 는 그 열쇠를 끼운 사본 -
    매번 새 열쇠라 보관하지 않는다."""
    if edition == "cloud":
        return {}
    out = {"server_info": (blank_server_info(_repo_text("server_info.py")), True)}
    if test_keys:
        out["update_sign"] = (swap_key(_repo_text("update_sign.py"), "PUBLIC_KEY_HEX", test_keys["update"]), False)
        out["license_check"] = (swap_key(_repo_text("license_check.py"), "LICENSE_PUBLIC_KEY_HEX", test_keys["license"]), False)
    return out


def standalone_materials():
    """스탠드얼론 설치본에 실리는 우리 코드·웹 파일의 내용 [(자리, 바이트)] - 프로그램 파일(만든 server_info 적용), 조각의 원본,
    시작 스크립트, 안내 파일. 내장 파이썬·남의 라이브러리(.venv 에서 오는 것, lib.zip)는 뺀다 (tests/test_standalone_offline.py ①)."""
    out, seen = [], set()

    def put(rel, data):
        if rel not in seen:
            seen.add(rel)
            out.append((rel, data))
    for rel, src in program_files("standalone"):
        if src.startswith(".venv/"):
            continue
        with open(_src_path(REPO, src), "rb") as f:
            data = f.read()
        put(rel, GENERATED[rel](data.decode("utf-8")).encode("utf-8") if rel in GENERATED else data)
    overrides = module_overrides("standalone")
    for src in module_sources("standalone"):
        name = os.path.splitext(os.path.basename(src))[0]
        rel = os.path.relpath(src, REPO).replace(os.sep, "/")
        if name in overrides:
            put(rel, overrides[name][0].encode("utf-8"))
        else:
            with open(src, "rb") as f:
                put(rel, f.read())
    with open(os.path.join(REPO, "app_start.py"), "rb") as f:
        put("app/_start.py", f.read())
    for rel, src in other_files("standalone"):
        path = _src_path(REPO, src)
        if os.path.isfile(path):          # 안내 파일은 계획 ③ Task 5 가 만든다
            with open(path, "rb") as f:
                put(rel, f.read())
    return out


def module_fingerprint(src, tool):
    """조각 하나의 재료 지문: 그 파일 내용 + 도구 버전 + 옵션. 다른 우리 파일이 바뀌어도 그대로다 (조각은 서로를 실행 때 import 한다)."""
    h = hashlib.sha256()
    for part in (open(src, "rb").read(), tool.encode("utf-8"), json.dumps([MODULE_OPTIONS, NUITKA_ENV], sort_keys=True).encode("utf-8")):
        h.update(part + b"\0")
    return h.hexdigest()


def compile_module(src, out_dir):
    """src 를 Nuitka 로 조각(.pyd) 하나로 만들어 out_dir 에 두고 그 경로를 돌려준다."""
    env = dict(os.environ, **NUITKA_ENV, PYTHONPATH=os.pathsep.join(filter(None, [AGENT_DIR, os.environ.get("PYTHONPATH")])))
    subprocess.run([sys.executable, "-m", "nuitka", *MODULE_OPTIONS, f"--output-dir={out_dir}", src], cwd=REPO, check=True, env=env)
    return os.path.join(out_dir, os.path.splitext(os.path.basename(src))[0] + importlib.machinery.EXTENSION_SUFFIXES[0])


def build_modules(work_dir, cache=MODULE_CACHE, force=False, compile=compile_module, edition="cloud", overrides=None):
    """우리 파일을 하나씩 조각으로 만들어 work_dir\\app 에 둔다. 재료 지문이 cache 에 보관한 것과 같으면 다시 만들지 않는다
    (force 면 늘 새로). 조각은 차례로 만든다 - 동시에 만들지 않는다 (exe 동시 빌드의 원인 모를 고장, 2026-10-21).
    판 목록의 builder 칸 글자를 돌려준다 ("nuitka 4.2.2 · python 3.14.7 (조각 새로 1: web_replay, 그대로 16)").
    edition 의 조각 목록(module_sources)을 쓰고, overrides {이름: (글, 보관하나)} (기본 module_overrides(edition))의 조각은 그 글을
    임시 파일로 컴파일한다 - 보관은 cache\\<버전 종류> (일반 조각을 덮지 않는다), 보관하지 않는 것은 늘 새로 만든다."""
    app = os.path.join(work_dir, "app")
    os.makedirs(app, exist_ok=True)
    os.makedirs(cache, exist_ok=True)
    overrides = module_overrides(edition) if overrides is None else overrides
    ver = subprocess.run([sys.executable, "-m", "nuitka", "--version"], capture_output=True, text=True, check=True).stdout.split()[0]
    tool = f"nuitka {ver} · python {platform.python_version()}"
    suffix = importlib.machinery.EXTENSION_SUFFIXES[0]
    made, kept, wanted = [], [], set()
    for src in module_sources(edition):
        name = os.path.splitext(os.path.basename(src))[0]
        with tempfile.TemporaryDirectory(prefix="rpa_pyd_", ignore_cleanup_errors=True) as tmp:
            store = cache
            if name in overrides:
                text, keep_it = overrides[name]
                gen = os.path.join(tmp, "src")
                os.makedirs(gen)
                src = os.path.join(gen, name + ".py")
                with open(src, "w", encoding="utf-8", newline="\n") as f:
                    f.write(text)
                store = os.path.join(cache, edition) if keep_it else os.path.join(tmp, "nokeep")
                os.makedirs(store, exist_ok=True)
            fp, keep = module_fingerprint(src, tool), os.path.join(store, name + suffix)
            try:
                same = not force and os.path.isfile(keep) and open(keep + ".inputs", encoding="utf-8").read().split() == [fp, _sha(keep)]
            except OSError:
                same = False
            if same:
                kept.append(name)
            else:
                out = os.path.join(tmp, "out")
                os.makedirs(out)
                shutil.copy2(compile(src, out), keep)
                with open(keep + ".inputs", "w", encoding="utf-8") as f:      # 조각을 다 보관한 뒤에 지문 - 중간에 죽으면 다음에 다시 만든다
                    f.write(f"{fp}\n{_sha(keep)}\n")
                made.append(name)
                print(f"  {name}: 조각을 새로 만들었습니다", flush=True)
            shutil.copy2(keep, os.path.join(app, name + suffix))
        wanted.add(name + suffix)
    for old in os.listdir(app):
        if old.endswith(suffix) and old not in wanted:
            os.remove(os.path.join(app, old))
    return f"{tool} (조각 새로 {len(made)}{': ' + ', '.join(made) if made else ''}, 그대로 {len(kept)})"


def build_lib_zip(zip_path, site_packages=None, names=None):
    """라이브러리 묶음을 만든다 (컴파일하지 않고 그대로). 같은 재료면 늘 같은 바이트다.
    comtypes 의 형식 라이브러리 시각 검사는 끄고 (빌드 PC 와 윈도우 버전이 다른 PC 에서 죽는다, 2026-09-29),
    win32ui 가 쓰는 MFC DLL 을 pythonwin 에 넣는다. site_packages 기본은 빌드 가상 환경(site_packages()), names 기본은 LIB_NAMES."""
    site_packages = site_packages or os.path.join(venv_root(), "Lib", "site-packages")   # = site_packages()
    files = {}
    for name in (LIB_NAMES if names is None else names):
        full = os.path.join(site_packages, name)
        if os.path.isfile(full):
            files[name] = full
        elif os.path.isdir(full):
            for base, dirs, names in os.walk(full):
                rel_dir = os.path.relpath(base, site_packages).replace(os.sep, "/")
                dirs[:] = [d for d in dirs if d != "__pycache__" and f"{rel_dir}/{d}" not in LIB_SKIP_DIRS]
                for n in names:
                    if f"{rel_dir}/{n}" not in LIB_SKIP:
                        files[f"{rel_dir}/{n}"] = os.path.join(base, n)
        else:
            raise RuntimeError(f"라이브러리가 없습니다: {full}")
    files["pythonwin/mfc140u.dll"] = MFC_DLL
    tmp = zip_path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in sorted(files):
            with open(files[rel], "rb") as f:
                data = f.read()
            if rel == COMTYPES_CHECK[0]:
                if COMTYPES_CHECK[1] not in data:
                    raise RuntimeError(f"comtypes 에 바꿀 줄이 없습니다 ({rel}) - comtypes 를 올렸으면 시각 검사 끄는 자리를 다시 찾으세요")
                data = data.replace(COMTYPES_CHECK[1], COMTYPES_CHECK[2])
            info = zipfile.ZipInfo(rel, LIB_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    os.replace(tmp, zip_path)


def reuse_exes(src_dir, work_dir):
    """exe 들을 새로 만들지 않고 src_dir(판 폴더)에서 work_dir 로 복사한다. 판 목록 builder 칸 글자를 돌려준다."""
    missing = [exe for exe in EXES if not os.path.isfile(os.path.join(src_dir, exe))]
    if missing:
        raise FileNotFoundError(f"{src_dir} 에 {', '.join(missing)} 가 없습니다 (옵저버가 없던 옛 버전) - "
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


def setup_name(version, edition="cloud", test=False):
    if edition == "cloud":
        return f"AUTOPILOT_Setup_{version}.exe"
    return f"AUTOPILOT_Standalone_{'TEST_' if test else ''}Setup_{version}.exe"


def iscc_command(iscc, out_dir, version, out_root=OUT_ROOT, iss=ISS_PATH, edition="cloud", test=False):
    if edition == "cloud":
        return [iscc, "/Qp", f"/DAppVersion={version}", f"/DNumVersion={num_version(version)}", f"/DSourceDir={out_dir}",
                f"/DDashboardURL={server_info.DASHBOARD_URL}",
                f"/O{out_root}", f"/F{setup_name(version)[:-4]}", iss]
    return [iscc, "/Qp", f"/DAppVersion={version}", f"/DNumVersion={num_version(version)}", f"/DSourceDir={out_dir}",
            f"/DDashboardURL={STANDALONE_URL}", f"/DEdition={edition}", *(["/DTestBuild=1"] if test else []),
            f"/O{out_root}", f"/F{setup_name(version, edition, test)[:-4]}", iss]


def build_setup(out_dir, version, out_root=OUT_ROOT, edition="cloud", test=False):
    """판 폴더로 설치 파일을 만든다. 경로를 돌려준다. ISCC 가 없거나 컴파일이 안 되면 RuntimeError."""
    iscc = find_iscc()
    if not iscc:
        raise RuntimeError("Inno Setup(ISCC.exe) 이 없습니다. winget install JRSoftware.InnoSetup --scope user 로 설치하거나 "
                           "--no-setup 으로 건너뛰세요")
    r = subprocess.run(iscc_command(iscc, out_dir, version, out_root, edition=edition, test=test), capture_output=True)
    path = os.path.join(out_root, setup_name(version, edition, test))
    if r.returncode != 0 or not os.path.isfile(path):
        raise RuntimeError(f"설치 파일을 만들지 못했습니다 (ISCC {r.returncode}): "
                           f"{(r.stdout + r.stderr)[-500:].decode('utf-8', 'replace')}")
    return path


def signing_key_problem():
    """공개 열쇠가 비어 있으면 이 판은 영영 자동 업데이트를 받지 못한다 (검증은 깔려 있는 옛 코드가 한다)."""
    if not update_sign.PUBLIC_KEY_HEX:
        return "업데이트 공개 열쇠(update_sign.PUBLIC_KEY_HEX)가 비어 있습니다 - 이 판은 자동 업데이트를 받을 수 없습니다 (tools/publish_release.py --keygen 으로 만든 값을 넣으세요)"
    return None


def license_key_problem(test):
    """진짜 스탠드얼론 빌드인데 라이선스 공개 열쇠가 비었으면 그 글 - 어떤 라이선스도 통하지 않는 설치 파일이 나온다."""
    import license_check
    if not test and not license_check.LICENSE_PUBLIC_KEY_HEX:
        return ("라이선스 공개 열쇠(license_check.LICENSE_PUBLIC_KEY_HEX)가 비어 있습니다 - tools/make_license.py --keygen 이 "
                "알려 준 값을 넣으십시오 (시험용이면 --test-build)")
    return None


def sign_manifest(out_dir, secret):
    """out_dir\\manifest.json 바이트에 서명해 out_dir\\manifest.sig (16진수 한 줄)를 쓰고 그 16진수를 돌려준다.
    스탠드얼론은 업데이트 사이트가 없어 설치 파일이 서명을 싣는다 (ap_guard·rpa_update.ensure_installed_sig 가 본다).
    버전 목록의 files 에는 넣지 않는다 (목록에 대한 서명이라)."""
    with open(os.path.join(out_dir, st.MANIFEST_NAME), "rb") as f:
        sig = update_sign.sign(secret, f.read()).hex()
    with open(os.path.join(out_dir, SIG_FILE), "w", encoding="ascii", newline="\n") as f:
        f.write(sig + "\n")
    return sig


def main(argv=None):
    ap = argparse.ArgumentParser(description="배포판을 만든다")
    ap.add_argument("--to-dist", action="store_true",
                    help="exe 셋을 이 PC 의 dist 에도 복사한다 (설정 파일은 건드리지 않는다)")
    ap.add_argument("--exes-from", metavar="판폴더", help="exe 셋을 만들지 않고 이 판 폴더에서 가져온다 (exe 소스가 안 바뀐 판)")
    ap.add_argument("--no-setup", action="store_true", help="설치 파일(setup.exe)을 만들지 않는다")
    ap.add_argument("--rebuild-all", action="store_true", help="재료가 지난번과 같아도 exe 셋(조각 방식이면 조각)을 모두 새로 만든다")
    ap.add_argument("--modules", action="store_true",
                    help="조각 방식: 우리 파일을 하나씩 .pyd 로, 라이브러리는 lib.zip 으로, exe 셋은 시작 파일 (설계 2026-11-11)")
    ap.add_argument("--onefile", action="store_true", help="옛 방식: exe 셋을 Nuitka onefile 로 (지금 기본과 같다)")
    ap.add_argument("--edition", choices=EDITIONS, default="cloud",
                    help="버전 종류: cloud(일반, 기본) / standalone(로컬 서버 - 조각 방식으로만, 설계 2026-11-23-standalone)")
    ap.add_argument("--out-root", metavar="폴더", default=None, help=f"배포 폴더·압축·설치 파일을 둘 곳 (기본 {OUT_ROOT})")
    ap.add_argument("--test-build", action="store_true",
                    help="스탠드얼론 시험용 빌드: 그 자리에서 만든 열쇠를 쓴다 (이름에 TEST, 고객 배포 금지)")
    ap.add_argument("--sign-key", metavar="파일", default=None,
                    help="진짜 스탠드얼론 빌드가 버전 목록을 서명하는 업데이트 비밀 열쇠 (기본 publish_release.KEY_PATH)")
    args = ap.parse_args(argv)
    edition, test = args.edition, args.test_build
    if edition == "standalone" and (args.onefile or args.exes_from or args.to_dist):
        print("  문제: 스탠드얼론은 조각 방식으로만 만듭니다 (--onefile·--exes-from·--to-dist 와 함께 쓸 수 없습니다)")
        return 1
    if test and edition != "standalone":
        print("  문제: --test-build 는 --edition standalone 과 함께만 씁니다")
        return 1
    if args.modules and (args.exes_from or args.to_dist or args.onefile):
        print("  문제: --modules 는 --exes-from·--to-dist·--onefile 과 함께 쓸 수 없습니다")
        return 1
    modules = args.modules or edition == "standalone"
    out_root = args.out_root or OUT_ROOT
    problem = signing_key_problem() or (license_key_problem(test) if edition == "standalone" else None)
    if problem:
        print("  문제:", problem)
        return 1
    sign_secret = sign_public = test_keys = lic_secret = None
    replace = {}
    if edition == "standalone":
        if test:            # 그 자리에서 열쇠 두 쌍 - 진짜 열쇠 파일은 열지 않는다. 진짜 라이선스는 이 빌드에서 통하지 않는다
            sign_secret, sign_public = update_sign.keygen()
            lic_secret, lic_public = update_sign.keygen()
            test_keys = {"update": sign_public.hex(), "license": lic_public.hex()}
            replace["update_sign.py"] = swap_key(_repo_text("update_sign.py"), "PUBLIC_KEY_HEX", test_keys["update"])
        else:
            import publish_release
            key_path = args.sign_key or publish_release.KEY_PATH
            if not os.path.isfile(key_path):
                print(f"  문제: 업데이트 서명 열쇠 파일이 없습니다 ({key_path}) - 스탠드얼론은 버전 목록의 서명을 설치 파일에 싣습니다")
                return 1
            sign_secret, sign_public = publish_release._secret(key_path), update_sign.public_key()
    prefix = release_prefix(edition, test)
    version = next_version(out_root, datetime.date.today(), prefix)
    work = os.path.join(REPO, "build", "release")
    kind = "" if edition == "cloud" else " - 스탠드얼론 시험용" if test else " - 스탠드얼론"
    print(f"판 {version}{kind} 을 만듭니다 ({'조각 방식' if modules else f'exe 는 {args.exes_from} 에서' if args.exes_from else 'Nuitka'})")
    try:
        if modules:
            work = os.path.join(REPO, "build", "release_modules" if edition == "cloud" else "release_standalone")
            build_launchers(work)
            builder = build_modules(work, force=args.rebuild_all, edition=edition, overrides=module_overrides(edition, test_keys))
            build_lib_zip(os.path.join(work, "lib.zip"), names=lib_names(edition))
        else:
            builder = reuse_exes(args.exes_from, work) if args.exes_from else build_exes(work, force=args.rebuild_all)
    except (FileNotFoundError, RuntimeError, subprocess.CalledProcessError) as e:
        print("  문제:", e)
        return 1
    out_dir = os.path.join(out_root, f"{prefix}{version}")
    program = collect(out_dir, work, version=BRAND_VERSION, modules=modules, edition=edition, test=test, replace=replace)
    man = write_manifest(out_dir, version, builder, program)
    sig_problem = []
    if edition == "standalone":
        sig = sign_manifest(out_dir, sign_secret)
        with open(os.path.join(out_dir, st.MANIFEST_NAME), "rb") as f:
            if not (sign_public and update_sign.verify(sign_public, f.read(), bytes.fromhex(sig))):   # 열쇠 짝이 틀리면 설치본이 모두 막힌다
                sig_problem.append("업데이트 서명 열쇠가 update_sign.PUBLIC_KEY_HEX 와 짝이 아닙니다 - 설치하면 exe 셋이 켜지지 않습니다")
        if test:            # make_license.py --key 가 읽는 꼴 (16진수 한 줄). 배포 폴더·압축 밖에 둔다
            with open(os.path.join(out_root, f"{prefix}{version}.testkey.txt"), "w", encoding="ascii") as f:
                f.write(lic_secret.hex() + "\n")
            print(f"  시험용 라이선스 열쇠: {os.path.join(out_root, f'{prefix}{version}.testkey.txt')} (고객에게 보내지 않는다)")
    zip_path = out_dir + ".zip"
    make_zip(out_dir, zip_path)
    problems = (sig_problem + verify_zip(zip_path, man, program, [rel for rel, _ in other_files(edition)], edition=edition)
                + smoke_check(zip_path, edition=edition))
    if not runtime_has_tkinter(out_dir):
        problems.append("내장 파이썬에 tkinter 가 없습니다 - 설정 창이 뜨지 않습니다 (2부 6절)")
    for p in problems:
        print("  문제:", p)
    if problems:
        print(f"배포판에 문제가 {len(problems)}건 있습니다. {zip_path} 를 쓰지 마세요")
        print("  exe 가 의심되면 --rebuild-all 로 다시 만드세요 (재료가 같으면 보관한 exe 를 또 씁니다 - 보관 폴더는 지우지 말 것: "
              "멀쩡한 exe 까지 새로 만들어 PC 가 다 다시 받는다)")
        return 1
    if not args.no_setup:
        try:
            setup = build_setup(out_dir, version, out_root, edition, test)
        except RuntimeError as e:
            print("  문제:", e)
            return 1
        print(f"  설치 파일 {setup}  ({os.path.getsize(setup) // 2 ** 20}MB)")
    if args.to_dist:
        for exe in EXES:
            shutil.copy2(os.path.join(out_dir, exe), os.path.join(REPO, "dist", exe))
        _copy(os.path.join(out_dir, *NODE_REL), os.path.join(REPO, "dist"), "/".join(NODE_REL))   # ACTOR·옵저버가 dist 옆에서 찾는다 (검토 2026-10-16)
        print("  dist 에 exe 셋과 playwright\\node.exe 를 복사했습니다 (설정 파일은 그대로)")
    print(f"판 {version}  {zip_path}  ({os.path.getsize(zip_path) // 2 ** 20}MB)")
    removed = prune_local(out_root, protect=[args.exes_from], edition=edition, test=test)   # 새 판이 다 만들어진 뒤에만 옛 판을 찾아 지운다
    print(f"  {out_root} 의 옛 판을 지웠습니다: {', '.join(removed)}" if removed else f"  {out_root} 에 지울 옛 판이 없습니다 (최신 {LOCAL_KEEP}개)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
