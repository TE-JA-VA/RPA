"""빌드 스크립트 시험 - exe 는 만들지 않고 가짜 입력으로 판 번호·모으기·판 목록·압축·검사를 돌린다.

    .venv\\Scripts\\python.exe tests\\test_build_release.py
"""
import datetime
import hashlib
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.stdout.reconfigure(encoding="utf-8")

import build_release as br  # noqa: E402
import rpa_status as st  # noqa: E402

fails = []
_no = [0]


def check(name, cond, detail=""):
    _no[0] += 1
    mark = "통과" if cond else "실패"
    print(f"  {_no[0]:2d}. [{mark}] {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(f"{_no[0]}. {name} {detail}")


def finish():
    print()
    print(f"실패: {'없음' if not fails else fails}")
    sys.exit(1 if fails else 0)


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode("utf-8"))


tmp = tempfile.mkdtemp(prefix="rpa_build_")
repo, runtime = os.path.join(tmp, "repo"), os.path.join(tmp, "runtime")
exe_dir, out_root = os.path.join(tmp, "exe"), os.path.join(tmp, "out")
BLANK = {"LogIn": {"AdminCode": "", "ID": "", "PW": ""}, "Sites": {"SITE1": {"URL": "https://x", "ID": "", "PW": ""}}}
for rel, src in br.PROGRAM_FILES + br.OTHER_FILES:
    body = json.dumps(BLANK) if src.endswith(".json") else f"{rel} 내용\r\n".encode("cp949")
    write(os.path.join(repo, *src.split("/")), body)
for exe in br.EXES:
    write(os.path.join(exe_dir, exe), b"MZ fake " + exe.encode())
write(os.path.join(runtime, "python", "Lib", "__pycache__", "os.cpython-314.pyc"), b"pyc")   # 내장 파이썬엔 원래 있다
for exe in ("python.exe", "pythonw.exe"):   # 이름 바꾼 사본을 만들려면 진짜 exe 여야 한다 (버전 정보를 고친다)
    shutil.copy2(os.path.join(br.RUNTIME_ROOT, "python", exe), os.path.join(runtime, "python", exe))
ICO = (ROOT / "release" / "AFTER_MARKET.ico").read_bytes()   # 사본의 아이콘으로도 쓰니 진짜여야 한다
write(os.path.join(repo, "release", "AFTER_MARKET.ico"), ICO)
write(os.path.join(runtime, "ms-playwright", "chromium-1234", "chrome.exe"), b"chrome")   # 옛 판의 브라우저가 runtime 에 남아 있어도
write(os.path.join(runtime, "ms-playwright", ".links", "x"), b"")                         # 판에는 안 들어간다 (2026-10-06 부터 Edge)
others = [rel for rel, _ in br.OTHER_FILES]

# ---------------------------------------------------------------------------
print("=== 1. 판 번호 ===")
day = datetime.date(2026, 9, 29)
check("첫 판은 -1", br.next_version(out_root, day) == "2026.09.29-1")
os.makedirs(os.path.join(out_root, "배포_2026.09.29-1"))
write(os.path.join(out_root, "배포_2026.09.29-2.zip"), b"")
check("그날 있는 폴더·압축의 다음 번호", br.next_version(out_root, day) == "2026.09.29-3")
check("날이 바뀌면 다시 1", br.next_version(out_root, datetime.date(2026, 9, 30)) == "2026.09.30-1")

# ---------------------------------------------------------------------------
print("=== 2. 모으기와 판 목록 ===")
out_dir = os.path.join(out_root, "배포_2026.09.29-3")
program = br.collect(out_dir, exe_dir, repo=repo, runtime_root=runtime, version="2026.9.29.3")
branded = {f"python/{name}" for name in br.BRANDED}
check("판 목록 대상은 exe 둘과 프로그램 파일, AFTER MARKET 이름의 파이썬 둘",
      set(program) == set(br.EXES) | {rel for rel, _ in br.PROGRAM_FILES} | branded and len(branded) == 2, str(program))
import win32api  # noqa: E402
import win32con  # noqa: E402


def version_info(path):
    h = win32api.LoadLibraryEx(path, 0, win32con.LOAD_LIBRARY_AS_DATAFILE)
    try:
        langs = win32api.EnumResourceLanguages(h, 16, 1)
    finally:
        win32api.FreeLibrary(h)
    lang, cp = win32api.GetFileVersionInfo(path, "\\VarFileInfo\\Translation")[0]
    get = lambda k: win32api.GetFileVersionInfo(path, f"\\StringFileInfo\\{lang:04x}{cp:04x}\\{k}")  # noqa: E731
    return langs, get("FileDescription"), get("CompanyName")


for name, (src, desc) in br.BRANDED.items():
    langs, got, company = version_info(os.path.join(out_dir, "python", name))
    check(f"{name}: 작업 관리자 설명 '{desc}', 회사 AFTER MARKET, 버전 정보는 한 벌 (옛 'Python' 이 안 남는다)",
          desc.startswith("AFTER MARKET") and got == desc and company == "AFTER MARKET" and len(langs) == 1,
          (langs, got, company))


def icons(path):
    """exe 의 아이콘 자원: (아이콘 묶음 이름들, 첫 묶음이 가리키는 그림 번호들, [(그림 번호, 자료)])."""
    h = win32api.LoadLibraryEx(path, 0, win32con.LOAD_LIBRARY_AS_DATAFILE)
    try:
        imgs = [(n, win32api.LoadResource(h, win32con.RT_ICON, n, lang))
                for n in win32api.EnumResourceNames(h, win32con.RT_ICON)
                for lang in win32api.EnumResourceLanguages(h, win32con.RT_ICON, n)]
        groups = win32api.EnumResourceNames(h, win32con.RT_GROUP_ICON)
        g = win32api.LoadResource(h, win32con.RT_GROUP_ICON, groups[0],
                                  win32api.EnumResourceLanguages(h, win32con.RT_GROUP_ICON, groups[0])[0])
        ids = [struct.unpack_from("<H", g, 6 + 14 * i + 12)[0] for i in range(struct.unpack_from("<H", g, 4)[0])]
        return groups, ids, imgs
    finally:
        win32api.FreeLibrary(h)


for name in br.BRANDED:
    groups, ids, imgs = icons(os.path.join(out_dir, "python", name))
    check(f"{name}: 아이콘은 AFTER MARKET 한 벌 (작업 관리자·탐색기에 보이는 것, 파이썬 아이콘은 안 남는다)",
          len(groups) == 1 and len(imgs) == int.from_bytes(ICO[4:6], "little")
          and all(data in ICO for _, data in imgs) and sorted(ids) == sorted(n for n, _ in imgs),
          (groups, ids, [n for n, _ in imgs]))
man = br.write_manifest(out_dir, "2026.09.29-3", "nuitka 4.2.2 · python 3.14.7", program)
check("형식·판 번호·빌더", man["format"] == st.MANIFEST_FORMAT and man["version"] == "2026.09.29-3"
      and man["builder"] == "nuitka 4.2.2 · python 3.14.7")
check("문서·배포 틀은 판 목록에 없다", not set(others) & set(man["files"]))
bat = "firebase/agent/에이전트_시작.bat"
check("한글 파일 이름도 지문", man["files"][bat]["sha256"]
      == hashlib.sha256(f"{bat} 내용\r\n".encode("cp949")).hexdigest())
check("같이 싣는 브라우저(ms-playwright 713MB)는 판에 없다 - 깔린 Edge 를 쓴다 (runtime 에 남아 있어도)",
      not os.path.exists(os.path.join(out_dir, "ms-playwright")) and list(man["runtime"]) == ["python"], str(man["runtime"]))
check("만든 판은 에이전트의 판 점검에서 ok", st.check_install(out_dir)["state"] == "ok", str(st.check_install(out_dir)))
try:
    br.collect(out_dir, exe_dir, repo=repo, runtime_root=runtime)
    ok = False
except FileExistsError:
    ok = True
check("이미 있는 판 폴더는 덮어쓰지 않는다", ok)

# ---------------------------------------------------------------------------
print("=== 3. 압축과 검사 ===")
zip_path = out_dir + ".zip"
br.make_zip(out_dir, zip_path)
with zipfile.ZipFile(zip_path) as z:
    names = z.namelist()
check("압축 맨 위 폴더는 판 폴더 이름", all(n.startswith("배포_2026.09.29-3/") for n in names))
check("한글 이름이 압축에서 깨지지 않는다", f"배포_2026.09.29-3/{bat}" in names)
check("깨끗한 판은 문제 없음 (런타임 안 __pycache__ 는 괜찮다)", br.verify_zip(zip_path, man, program, others) == [],
      str(br.verify_zip(zip_path, man, program, others)))


def variant(name, change):
    """out_dir 사본을 고쳐 압축하고 검사 결과를 돌려준다."""
    d = os.path.join(out_root, name)
    shutil.copytree(out_dir, d)
    change(d)
    br.make_zip(d, d + ".zip")
    return br.verify_zip(d + ".zip", man, program, others)


p = variant("배포_junk", lambda d: [write(os.path.join(d, "firebase", "agent", "queue.jsonl"), b""),
                                     write(os.path.join(d, "__pycache__", "rpa_status.cpython-314.pyc"), b""),
                                     write(os.path.join(d, "run_routine_result.txt"), b""),
                                     write(os.path.join(d, "sessions", "SITE1.json"), b"{}")])
check("찌꺼기(큐·__pycache__·결과 로그·세션)는 문제로 잡는다",
      all(any(k in x for x in p) for k in ("queue.jsonl", "__pycache__", "run_routine_result.txt", "sessions")), str(p))
p = variant("배포_leak", lambda d: write(os.path.join(d, "RPA_UserConfig.json"),
                                          json.dumps({"LogIn": {"AdminCode": "a", "ID": "b", "PW": "진짜비번"}})))
check("로그인이 든 배포 틀은 문제로 잡고, 값은 찍지 않는다",
      any("LogIn.PW" in x for x in p) and not any("진짜비번" in x for x in p), str(p))
p = br.template_problems({"Logistic": {"cboBS_Auto_YN": "N", "Printer": "", "cboTag": "한진연동", "cboTagAmt": "대",
                                       "cboBeasong_Gu_Apply": ""}})
check("우리 회사 물류 값(택배사·박스·운임)이 든 배포 틀은 문제로 잡는다 - 업체마다 설정 창에서 넣는다 (2026-09-30)",
      any("Logistic.cboTag " in x for x in p) and any("Logistic.cboTagAmt" in x for x in p)
      and not any("cboBeasong" in x for x in p), str(p))
real = json.loads((ROOT / "release" / "RPA_UserConfig.template.json").read_text(encoding="utf-8-sig"))
check("저장소의 배포 틀은 통과 (출력 방식 수동, 택배사·박스·운임 빈 값)",
      br.template_problems(real) == [] and real["Logistic"]["cboBS_Auto_YN"] == "N", str(br.template_problems(real)))
p = variant("배포_tamper", lambda d: write(os.path.join(d, "rpa_status.py"), b"changed"))
check("지문이 다른 파일은 문제로 잡는다", any("지문 다름: rpa_status.py" in x for x in p), str(p))
p = variant("배포_extra", lambda d: write(os.path.join(d, "memo.txt"), b"x"))
check("모은 목록에 없는 파일은 문제로 잡는다", any("memo.txt" in x for x in p), str(p))

# ---------------------------------------------------------------------------
print("=== 4. exe 출력의 끝 줄 표지 ===")
check("UTF-8 출력에서 찾는다", br.found_marker("… === 점검 끝 (루틴은 …) ===\n".encode("utf-8"), "=== 점검 끝"))
check("CP949 출력에서 찾는다", br.found_marker("  쓸 수 있는 Action: login\r\n".encode("cp949"), "쓸 수 있는 Action"))
check("없으면 못 찾는다", not br.found_marker(b"Traceback ...", "=== 점검 끝"))

# ---------------------------------------------------------------------------
print("=== 5. exe 를 실행조차 못 해도 판정으로 끝난다 ===")
# 가짜 exe(윈도우 실행 파일이 아님)는 보안 프로그램이 격리해 실행을 못 하는 경우와 같다 - 오류 추적 대신 '문제' 로
try:
    p = br.smoke_check(zip_path, timeout=30)
    ok = len(p) == len(br.EXES) and all("실행하지 못했습니다" in x for x in p)
except OSError as e:
    p, ok = repr(e), False
check("실행 못 하는 exe 는 문제 한 줄씩 (예외로 빠져나가지 않는다)", ok, str(p))

print("=== 6. 설치 파일 (2부) ===")
import subprocess  # noqa: E402
import rpa_settings as rs  # noqa: E402

check("판 목록에 설정 창·감독", {"rpa_settings.py", "firebase/agent/background.py"} <= {rel for rel, _ in br.PROGRAM_FILES})
check("파일 속성용 판 번호", br.num_version("2026.09.29-5") == "2026.9.29.5" and br.num_version("2026.10.01-12") == "2026.10.1.12")
check("설치 파일 이름", br.setup_name("2026.09.29-5") == "AFTER_MARKET_RPA_Setup_2026.09.29-5.exe")
with tempfile.TemporaryDirectory() as d:
    a, b = os.path.join(d, "a"), os.path.join(d, "b")
    os.makedirs(a)
    os.makedirs(b)
    open(os.path.join(b, "ISCC.exe"), "wb").close()
    check("ISCC 찾기: 있는 첫 자리, 없으면 None", br.find_iscc([a, b]) == os.path.join(b, "ISCC.exe") and br.find_iscc([a]) is None)
cmd = br.iscc_command("ISCC.exe", r"D:\AX\배포_2026.09.29-5", "2026.09.29-5", out_root=r"D:\AX")
check("ISCC 명령", cmd[0] == "ISCC.exe" and "/DAppVersion=2026.09.29-5" in cmd and "/DNumVersion=2026.9.29.5" in cmd
      and r"/DSourceDir=D:\AX\배포_2026.09.29-5" in cmd and r"/OD:\AX" in cmd
      and "/FAFTER_MARKET_RPA_Setup_2026.09.29-5" in cmd and cmd[-1] == br.ISS_PATH, cmd)
iss = Path(br.ISS_PATH).read_bytes().decode("utf-8-sig")
root_rel = "\\".join(st.PRODUCT_DIRS)
check("설치 자리 = 1부 자리 규칙", f"DefaultDirName={{commonpf64}}\\{root_rel}" in iss)
check("새 자리 config·data", all(f"{{commonappdata}}\\{root_rel}\\{d}" in iss for d in ("config", "data")))
check("빈 틀 이름 바꾸기 = 설정 창이 찾는 이름", f'DestName: "{rs.TEMPLATE_NAME}"' in iss)
check("안내 문서·빈 틀은 통째 복사에서 뺀다", all(f"\\{n}" in iss for n in ("RPA_UserConfig.json", "배포안내.txt", "클라우드_안내.txt")))
check("권한은 SID 로 (관리자·SYSTEM), 상속 끊기", "*S-1-5-32-544:(OI)(CI)F" in iss and "*S-1-5-18:(OI)(CI)F" in iss
      and "/inheritance:r" in iss)
check("설정 창 모드 이름", all(m in iss for m in ("--after-install", "--no-window", "--stop", "--remove-task", "--check-rpa")))
check("제거 시작 때는 확인만 한다 (제거를 그만두면 에이전트가 꺼진 채 남지 않게) - 멈추기는 파일을 지우기 직전",
      "RunSettings('--check-rpa') = EXIT_RPA_RUNNING" in iss and "InitializeUninstall" in iss
      and "RunSettings('--remove-task')" in iss)
check("판을 올릴 때 --stop 의 뜻밖의 코드(오류로 죽음 등)도 '멈추지 못함' 으로 다룬다", "(Code <> 0) and (Code <> -1)" in iss)
check("미리 만들어진 폴더도 막는다: 주인을 Administrators 로, 아래 폴더·파일 권한을 물려받게",
      "/setowner *S-1-5-32-544" in iss and "\\*\"\" /reset /T" in iss)
check("종료 코드 = 설정 창과 같다", f"EXIT_RPA_RUNNING = {rs.EXIT_RPA_RUNNING};" in iss
      and f"EXIT_STOP_FAILED = {rs.EXIT_STOP_FAILED};" in iss)
check("내장 파이썬에 tkinter (D:\\AX\\runtime)", br.runtime_has_tkinter(br.RUNTIME_ROOT))
with tempfile.TemporaryDirectory() as d:
    src = os.path.join(d, "src")
    for rel in br.EXES:
        write(os.path.join(src, rel), rel.encode())
    write(os.path.join(src, st.MANIFEST_NAME), json.dumps({"version": "2026.09.29-4", "builder": "nuitka 4.2.2 · python 3.14.7"}).encode())
    label = br.reuse_exes(src, os.path.join(d, "work"))
    check("--exes-from: 세 exe 를 가져오고 builder 칸에 적는다", label == "nuitka 4.2.2 · python 3.14.7 (판 2026.09.29-4 에서 가져옴)"
          and all(os.path.isfile(os.path.join(d, "work", n)) for n in br.EXES), label)
mfc = [o for o in br.NUITKA_COMMON if o.endswith("mfc140u.dll=mfc140u.dll")]
check("두 exe 에 mfc140u.dll 을 넣는다 (win32ui 가 쓰는데 Nuitka 는 System32 를 안 뒤진다 - 2026-09-29 노트북)",
      len(mfc) == 1 and mfc[0].startswith("--include-data-files=")
      and os.path.isfile(mfc[0][len("--include-data-files="):-len("=mfc140u.dll")]), mfc)
import comtypes._tlib_version_checker as tvc  # noqa: E402
FROZEN_LINE = 'if not hasattr(sys, "frozen"):'   # Nuitka 는 바꿀 글자가 없어도 말없이 넘어간다 → comtypes 를 올리면 여기서 잡는다
yml = open(br.NUITKA_YML, encoding="utf-8").read() if os.path.isfile(br.NUITKA_YML) else ""
check("두 exe 가 comtypes 의 typelib 시각 비교를 건너뛴다 (PyInstaller 처럼. 윈도우 판이 다른 PC 에서 죽었다 - 2026-09-29 노트북)",
      f"--user-package-configuration-file={br.NUITKA_YML}" in br.NUITKA_COMMON and FROZEN_LINE in yml
      and FROZEN_LINE in open(tvc.__file__, encoding="utf-8").read())
icon_opts = {exe: [o for o in br.NUITKA_COMMON + br.NUITKA_EXTRA[exe] if o.startswith("--windows-icon-from-ico=")]
             for exe in br.EXES}
prep = getattr(br, "ICON_PREPARE", "")
check("아이콘: 루틴 exe 는 크림 A, 프리페어·옵저버 exe 는 주황 A 한 벌씩, 주황 ico 도 판에 들어간다 (2026-09-30 사용자가 고른 '나')",
      icon_opts == {"ERPia_RPA.exe": [f"--windows-icon-from-ico={br.ICON}"],
                    "Prepare_RPA.exe": [f"--windows-icon-from-ico={prep}"],
                    "Prepare_Observer.exe": [f"--windows-icon-from-ico={prep}"]}
      and os.path.isfile(prep) and br.icon_resources(prep)[1]
      and open(prep, "rb").read() != open(br.ICON, "rb").read()
      and ("AFTER_MARKET_PREPARE.ico", "release/AFTER_MARKET_PREPARE.ico") in br.PROGRAM_FILES, icon_opts)
console = {exe: [o for o in br.NUITKA_COMMON + br.NUITKA_EXTRA[exe] if o.startswith("--windows-console-mode=")]
           for exe in br.EXES}
check("콘솔: 루틴·프리페어는 늘 콘솔, 옵저버는 창 프로그램 (attach - 시작 메뉴로 켜면 검은 창 없음)",
      console == {"ERPia_RPA.exe": ["--windows-console-mode=force"], "Prepare_RPA.exe": ["--windows-console-mode=force"],
                  "Prepare_Observer.exe": ["--windows-console-mode=attach"]}, str(console))
rex = br.NUITKA_EXTRA.get("Prepare_Observer.exe", [])
check("옵저버 exe: rpa_observer.py, tk-inter, Playwright, --check 끝 줄, 작업 표시줄 ID",
      br.EXES.get("Prepare_Observer.exe") == "rpa_observer.py" and br.TK_PLUGIN in rex
      and "--include-package=playwright" in rex and br.MARKERS.get("Prepare_Observer.exe") == "옵저버 점검 끝"
      and 'APP_ID = "AFTERMARKET.RPA.Observer"' in (ROOT / "rpa_observer.py").read_text(encoding="utf-8"))
with tempfile.TemporaryDirectory() as d:
    tcl, tkd = br.tcl_tk_dirs(d)
    cmd = br.nuitka_command("py", "Prepare_Observer.exe", d, (tcl, tkd))
    check("Tcl/Tk 를 폴더로 꺼내 Nuitka 에 넘긴다 (3.14 는 DLL 안 zipfs - 2026-09-30)",
          os.path.isfile(os.path.join(tcl, "init.tcl")) and os.path.isfile(os.path.join(tkd, "tk.tcl"))
          and f"--tcl-library-dir={tcl}" in cmd and f"--tk-library-dir={tkd}" in cmd and cmd[-1].endswith("rpa_observer.py"),
          str(cmd[-4:]))
    check("tk-inter 를 안 쓰는 exe 에는 Tcl 옵션이 없다",
          not any("library-dir" in o for o in br.nuitka_command("py", "Prepare_RPA.exe", d)))
check("--builder 선택지는 없다 (옵저버 exe 는 Nuitka 로만 - 고르면 늘 실패하던 pyinstaller 를 뺐다, 2026-10-02)",
      "--builder" not in Path(br.__file__).read_text(encoding="utf-8"))
calls = []


class _Done:
    stdout = "4.2.2\n"


real_run, br.subprocess.run = br.subprocess.run, lambda cmd, **kw: calls.append(kw) or _Done()
try:
    with tempfile.TemporaryDirectory() as d:
        br.build_exes(d, only=["Prepare_RPA.exe"])
finally:
    br.subprocess.run = real_run
env = calls[0].get("env") or {}
check("Nuitka 는 링크에도 일반 x86-64 CPU 를 준다 (LDFLAGS) - 안 주면 Zig 가 이 PC(Ryzen 9700X)에 맞춘 AVX-512 memcpy 를 "
      "붙여 인텔 노트북에서 exe 가 켜지자마자 0xC000001D (2026-10-02)",
      env.get("LDFLAGS") == "-march=x86_64" and env.get("PATH") == os.environ.get("PATH"), str(env.get("LDFLAGS")))
lock = re.search(r'OBSERVER_LOCK = os\.environ\.get\("RPA_OBSERVER_LOCK"\) or r"([^"]+)"', (ROOT / "rpa_status.py").read_text(encoding="utf-8"))
prep_code = iss[iss.find("function PrepareToInstall"):iss.find("function InitializeUninstall")]
check("옵저버가 켜져 있으면 판 올림·지우기를 시작 전에 멈춘다 (켜진 exe 는 덮지 못한다) - 잠금 이름은 rpa_status 와 같고, "
      "판 올림은 에이전트를 멈추기 전에 본다",
      bool(lock) and f"OBSERVER_LOCK = '{lock.group(1)}';" in iss and "CheckForMutexes(OBSERVER_LOCK)" in prep_code
      and prep_code.find("CheckForMutexes") < prep_code.find("RunSettings('--stop')")
      and "CheckForMutexes(OBSERVER_LOCK)" in iss[iss.find("function InitializeUninstall"):], prep_code[:400])
with tempfile.TemporaryDirectory() as d:
    for rel in ("ERPia_RPA.exe", "Prepare_RPA.exe"):
        write(os.path.join(d, rel), rel.encode())
    try:
        br.reuse_exes(d, os.path.join(d, "work"))
        check("--exes-from: 옵저버 exe 가 없는 옛 판이면 무엇이 없는지 말하고 멈춘다", False)
    except FileNotFoundError as e:
        check("--exes-from: 옵저버 exe 가 없는 옛 판이면 무엇이 없는지 말하고 멈춘다", "Prepare_Observer.exe" in str(e), str(e))
check("설치 파일: 시작 메뉴 'RPA 옵저버' (주황 아이콘, 작업 표시줄 ID 가 옵저버와 같다)",
      '"{group}\\RPA 옵저버"' in iss and 'Filename: "{app}\\Prepare_Observer.exe"' in iss
      and 'IconFilename: "{app}\\AFTER_MARKET_PREPARE.ico"' in iss and 'AppUserModelID: "AFTERMARKET.RPA.Observer"' in iss)
iscc = br.find_iscc()
check("이 PC 에 Inno Setup (ISCC.exe)", iscc is not None)
if iscc:
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "배포_시험")                       # 한글 판 폴더 이름
        for rel in ("RPA_UserConfig.json", "배포안내.txt", "클라우드_안내.txt", "rpa_settings.py", "manifest.json",
                    "python/python.exe", "python/pythonw.exe", "firebase/agent/background.py"):
            write(os.path.join(src, *rel.split("/")), b"x")
        r = subprocess.run(br.iscc_command(iscc, src, "2026.09.29-99", out_root=d), capture_output=True, timeout=300)
        out = os.path.join(d, br.setup_name("2026.09.29-99"))
        check("installer.iss 가 컴파일된다 (가짜 판 폴더)", r.returncode == 0 and os.path.isfile(out),
              (r.stdout + r.stderr)[-600:].decode("utf-8", "replace"))

finish()
