# -*- coding: utf-8 -*-
"""빌드 도구의 버전 종류 시험 (스탠드얼론 계획 ③ Task 1·3) - 빌드는 하지 않고 재료 목록·이름·모으기·검사만 본다.
일반(cloud) 버전의 값은 지금과 같아야 한다 (기본 인자).

    D:/AX/RPA/.venv/Scripts/python.exe tests/test_build_edition.py
"""
import datetime
import importlib.machinery
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.stdout.reconfigure(encoding="utf-8")

import build_release as br  # noqa: E402
import server_info  # noqa: E402

fails = []
_no = [0]


def check(name, cond, detail=""):
    _no[0] += 1
    print(f"  {_no[0]:2d}. [{'통과' if cond else '실패'}] {name}" + (f"  {detail}" if detail and not cond else ""))
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


SUFFIX = importlib.machinery.EXTENSION_SUFFIXES[0]
tmp = tempfile.mkdtemp(prefix="rpa_edition_")

# ---------------------------------------------------------------------------
print("=== 1. 일반 버전은 그대로 ===")
check("program_files('cloud') == PROGRAM_FILES", br.program_files("cloud") == br.PROGRAM_FILES)
check("other_files('cloud') == OTHER_FILES", br.other_files("cloud") == br.OTHER_FILES)
check("lib_names('cloud') == LIB_NAMES (순서까지)", br.lib_names("cloud") == br.LIB_NAMES)
check("AI 라이브러리 18개를 갈라 두었다 (anthropic … annotated_types)",
      len(br.LIB_NAMES_AI) == 18 and br.LIB_NAMES_AI[0] == "anthropic" and br.LIB_NAMES_AI[-1] == "annotated_types"
      and br.LIB_NAMES[-18:] == br.LIB_NAMES_AI, str(br.LIB_NAMES_AI))
cloud_mods = br.module_sources()
check("module_sources() == module_sources('cloud') 이고 ai_rescue.py 가 있다",
      cloud_mods == br.module_sources("cloud") and any(os.path.basename(p) == "ai_rescue.py" for p in cloud_mods))
check("설치 파일 이름", br.setup_name("2026.11.24-1") == "AUTOPILOT_Setup_2026.11.24-1.exe")
check("ISCC 명령이 지금 코드와 같다 (기본 인자)", br.iscc_command("I", "D", "2026.11.24-1") == [
    "I", "/Qp", "/DAppVersion=2026.11.24-1", "/DNumVersion=2026.11.24.1", "/DSourceDir=D",
    f"/DDashboardURL={server_info.DASHBOARD_URL}", r"/OD:\AX", "/FAUTOPILOT_Setup_2026.11.24-1", br.ISS_PATH],
      str(br.iscc_command("I", "D", "2026.11.24-1")))
check("배포 폴더 접두사", (br.release_prefix("cloud"), br.release_prefix("standalone"), br.release_prefix("standalone", test=True))
      == ("배포_", "배포_SA_", "배포_SA_TEST_"))
check("스탠드얼론 설치 파일 이름", br.setup_name("2026.11.24-1", "standalone") == "AUTOPILOT_Standalone_Setup_2026.11.24-1.exe"
      and br.setup_name("2026.11.24-1", "standalone", test=True) == "AUTOPILOT_Standalone_TEST_Setup_2026.11.24-1.exe")
sa_cmd = br.iscc_command("I", "D", "2026.11.24-1", edition="standalone", test=True)
check("스탠드얼론 ISCC: 로컬 주소·버전 종류·시험용 표시·이름",
      "/DDashboardURL=http://127.0.0.1:8781/" in sa_cmd and "/DEdition=standalone" in sa_cmd and "/DTestBuild=1" in sa_cmd
      and "/FAUTOPILOT_Standalone_TEST_Setup_2026.11.24-1" in sa_cmd and sa_cmd[-1] == br.ISS_PATH
      and not any(server_info.PROJECT_ID in a for a in sa_cmd), str(sa_cmd))
check("진짜 스탠드얼론 ISCC 에는 시험용 표시가 없다",
      "/DTestBuild=1" not in br.iscc_command("I", "D", "2026.11.24-1", edition="standalone"))

day = datetime.date(2026, 11, 24)
vr = os.path.join(tmp, "ver")
os.makedirs(os.path.join(vr, "배포_SA_2026.11.24-3"))
os.makedirs(os.path.join(vr, "배포_SA_TEST_2026.11.24-5"))
os.makedirs(os.path.join(vr, "배포_2026.11.24-1"))
check("일반 버전 번호는 배포_SA_* 를 세지 않는다", br.next_version(vr, day) == "2026.11.24-2", br.next_version(vr, day))
check("스탠드얼론 번호는 자기 접두사만", br.next_version(vr, day, "배포_SA_") == "2026.11.24-4"
      and br.next_version(vr, day, "배포_SA_TEST_") == "2026.11.24-6")

pr = os.path.join(tmp, "prune")
vs = ["2026.11.20-1", "2026.11.21-1", "2026.11.22-1", "2026.11.23-1", "2026.11.24-1"]
for v in vs:
    for pre, setup in (("배포_", br.setup_name(v)), ("배포_SA_", br.setup_name(v, "standalone")),
                       ("배포_SA_TEST_", br.setup_name(v, "standalone", True))):
        os.makedirs(os.path.join(pr, pre + v))
        write(os.path.join(pr, pre + v + ".zip"), b"")
        write(os.path.join(pr, setup), b"")
    write(os.path.join(pr, f"배포_SA_TEST_{v}.testkey.txt"), b"k")
removed = br.prune_local(pr, keep=4)
left = set(os.listdir(pr))
check("일반 정리는 일반 것만 지운다 (스탠드얼론 폴더·설치 파일은 남는다)",
      removed == ["2026.11.20-1"] and "배포_SA_2026.11.20-1" in left and "AUTOPILOT_Standalone_Setup_2026.11.20-1.exe" in left
      and "배포_2026.11.20-1" not in left and "AUTOPILOT_Setup_2026.11.20-1.exe" not in left, f"{removed}")
removed = br.prune_local(pr, keep=4, edition="standalone")
left = set(os.listdir(pr))
check("스탠드얼론 정리는 스탠드얼론 것만 (시험용·일반은 남는다)",
      removed == ["2026.11.20-1"] and "배포_SA_2026.11.20-1" not in left and "배포_SA_2026.11.20-1.zip" not in left
      and "AUTOPILOT_Standalone_Setup_2026.11.20-1.exe" not in left and "배포_SA_TEST_2026.11.20-1" in left
      and "배포_2026.11.21-1" in left, f"{removed}")
removed = br.prune_local(pr, keep=4, edition="standalone", test=True)
left = set(os.listdir(pr))
check("시험용 정리는 시험용 것만 (열쇠 파일까지)",
      removed == ["2026.11.20-1"] and not any("TEST_2026.11.20-1" in n for n in left) and "배포_SA_2026.11.21-1" in left,
      f"{removed} {sorted(n for n in left if '11.20' in n)}")
check("다시 돌려도 지울 것이 없다", br.prune_local(pr, keep=4) == [] and br.prune_local(pr, keep=4, edition="standalone") == [])

# 폴더 나누기 (사용자 2026-11-23): 이 개발 PC 의 스탠드얼론 빌드 결과는 D:\AX\스탠드얼론\ 에 (일반은 D:\AX 그대로)
check("기본 결과 자리: 일반 D:\\AX (예전 그대로), 스탠드얼론 D:\\AX\\스탠드얼론",
      br.OUT_ROOT == r"D:\AX" and getattr(br, "STANDALONE_OUT_ROOT", None) == r"D:\AX\스탠드얼론"
      and getattr(br, "default_out_root", lambda e: None)("cloud") == r"D:\AX"
      and getattr(br, "default_out_root", lambda e: None)("standalone") == r"D:\AX\스탠드얼론")
src = open(br.__file__, encoding="utf-8").read()
check("main 은 --out-root 가 없으면 버전 종류의 기본 자리", "out_root = args.out_root or default_out_root(edition)" in src)
check("ISCC 명령의 기본 결과 자리도 버전 종류마다 (일반 /OD:\\AX, 스탠드얼론 /OD:\\AX\\스탠드얼론)",
      r"/OD:\AX" in br.iscc_command("I", "D", "2026.11.24-1")
      and r"/OD:\AX\스탠드얼론" in br.iscc_command("I", "D", "2026.11.24-1", edition="standalone", test=True))
sp = os.path.join(tmp, "split")
sub = os.path.join(sp, "스탠드얼론")
for v in vs:
    os.makedirs(os.path.join(sp, "배포_" + v))
    write(os.path.join(sp, br.setup_name(v)), b"")
    os.makedirs(os.path.join(sub, "배포_SA_TEST_" + v))
    write(os.path.join(sub, br.setup_name(v, "standalone", True)), b"")
    write(os.path.join(sub, f"배포_SA_TEST_{v}.testkey.txt"), b"k")
before_sub = sorted(os.listdir(sub))
r1 = br.prune_local(sp, keep=4)
check("일반 정리(D:\\AX 흉내)는 아래 스탠드얼론 폴더를 보지 않는다", r1 == ["2026.11.20-1"] and sorted(os.listdir(sub)) == before_sub
      and os.path.isdir(sub), str(r1))
before_top = sorted(os.listdir(sp))
r2 = br.prune_local(sub, keep=4, edition="standalone", test=True)
check("스탠드얼론 정리(D:\\AX\\스탠드얼론 흉내)는 위 일반 폴더를 보지 않는다", r2 == ["2026.11.20-1"] and sorted(os.listdir(sp)) == before_top
      and not any("2026.11.20-1" in n for n in os.listdir(sub)), str(r2))

# ---------------------------------------------------------------------------
print("=== 2. 스탠드얼론 재료 목록 ===")
sa = br.program_files("standalone")
sa_rel = {rel for rel, _ in sa}
check("뺀 것: update_helper.py·license_check.py·firebase-config.js·data-firebase.js·edition.js",
      not sa_rel & {"update_helper.py", "license_check.py", "firebase/web/firebase-config.js", "firebase/web/data-firebase.js",
                    "firebase/web/edition.js"}, str(sorted(sa_rel & {"update_helper.py", "license_check.py"})))
check("더한 것: local_web.py·웹 파일 (글꼴·그림 포함)",
      {"firebase/agent/local_web.py", "firebase/web/index.html", "firebase/web/fonts/PretendardVariable.woff2",
       "firebase/web/img/login.webp", "firebase/web/data.js"} <= sa_rel, str(sorted(r for r in sa_rel if r.startswith("firebase/web"))))
check("같은 자리가 두 번 들어가지 않는다", len(sa_rel) == len(sa))
check("나머지 일반 파일은 그대로 (server_info.py 는 빈 값 사본으로)",
      {rel for rel, _ in br.PROGRAM_FILES} - {"update_helper.py", "license_check.py"} <= sa_rel and "server_info.py" in br.GENERATED)
web = br.web_files()
check("web_files: firebase/web 아래 이름순, 뺄 파일은 없다",
      [r for r, _ in web] == sorted(r for r, _ in web) and all(r == s and r.startswith("firebase/web/") for r, s in web)
      and not any(os.path.basename(r) in br.WEB_SKIP for r, _ in web), str(web[:3]))
others_sa = [rel for rel, _ in br.other_files("standalone")]
check("스탠드얼론 안내 파일: 배포안내_스탠드얼론.txt·PC번호_확인.bat·빈 설정 틀, 클라우드 안내 없음",
      others_sa == ["배포안내_스탠드얼론.txt", "PC번호_확인.bat", "RPA_UserConfig.json"], str(others_sa))
libs = br.lib_names("standalone")
check("스탠드얼론 라이브러리: AI 쪽(anthropic·httpx2·pydantic) 없음, playwright·pywinauto·msoffcrypto·cryptography·typing_extensions 있음",
      not {"anthropic", "httpx2", "pydantic"} & set(libs)
      and {"playwright", "pywinauto", "msoffcrypto", "cryptography", "typing_extensions.py"} <= set(libs), str(libs))
sa_mods = {os.path.basename(p) for p in br.module_sources("standalone")}
check("스탠드얼론 조각에 ai_rescue.py 가 없다 (나머지는 일반과 같다)",
      "ai_rescue.py" not in sa_mods and sa_mods == {os.path.basename(p) for p in cloud_mods} - {"ai_rescue.py"} | (
          {"ap_guard.py"} if (ROOT / "ap_guard.py").exists() else set()), str(sorted(sa_mods)))

# ---------------------------------------------------------------------------
print("=== 3. 빈 server_info ===")
real_text = (ROOT / "server_info.py").read_text(encoding="utf-8")
blank = br.blank_server_info(real_text)
real_ns, blank_ns = {}, {}
exec(real_text, real_ns)
exec(blank, blank_ns)
names = lambda ns: {k for k in ns if not k.startswith("__")}  # noqa: E731
check("진짜와 같은 이름이 모두 있다", names(real_ns) == names(blank_ns), f"{names(real_ns) ^ names(blank_ns)}")
check("값은 빈 글·빈 튜플뿐 (튜플은 튜플로)",
      all(blank_ns[k] == ("" if not isinstance(real_ns[k], tuple) else ()) for k in names(real_ns)),
      str({k: blank_ns[k] for k in names(blank_ns)}))
check("글에 http·AIza·프로젝트 이름이 없다", "http" not in blank and "AIza" not in blank and server_info.PROJECT_ID not in blank, blank)
check("첫 줄 표시", blank.splitlines()[0] == "# 스탠드얼론 - 바깥 서버 주소가 없다 (tools/build_release.py 가 만든다)")
try:
    br.blank_server_info('X = "a"\n\ndef f():\n    return "https://x"\n')
    ok = False
except RuntimeError:
    ok = True
check("함수 정의가 든 글은 RuntimeError (빈 값으로 만들 수 없는 실행 코드)", ok)
try:
    br.blank_server_info('X = "a"\nprint(X)\n')
    ok = False
except RuntimeError:
    ok = True
check("대입문·문서 글 말고 다른 줄도 RuntimeError", ok)

# ---------------------------------------------------------------------------
print("=== 4. 스탠드얼론 모으기·검사 ===")
repo, runtime = os.path.join(tmp, "repo"), os.path.join(tmp, "runtime")
work, out_root = os.path.join(tmp, "work"), os.path.join(tmp, "out")
BLANK = {"LogIn": {"AdminCode": "", "ID": "", "PW": ""}, "Sites": {}}
for rel, src in br.program_files("standalone") + br.other_files("standalone") + br.PROGRAM_FILES:
    body = json.dumps(BLANK) if src.endswith(".json") else f"{rel} 내용\n"
    write(os.path.join(repo, *src.split("/")), body)
write(os.path.join(repo, "server_info.py"), real_text)
write(os.path.join(repo, "release", "AFTER_MARKET.ico"), (ROOT / "release" / "AFTER_MARKET.ico").read_bytes())
write(os.path.join(repo, "app_start.py"), "print('start')\n")
for exe in ("python.exe", "pythonw.exe"):
    os.makedirs(os.path.join(runtime, "python"), exist_ok=True)
    shutil.copy2(os.path.join(br.RUNTIME_ROOT, "python", exe), os.path.join(runtime, "python", exe))
for exe in br.EXES:
    write(os.path.join(work, exe), b"MZ launcher " + exe.encode())
for mod in ("web_runner", "rpa_status", "license_check"):
    write(os.path.join(work, "app", mod + SUFFIX), b"pyd " + mod.encode())
write(os.path.join(work, "lib.zip"), b"PK fake")
out_sa = os.path.join(out_root, "배포_SA_TEST_2026.11.24-1")
program = br.collect(out_sa, work, repo=repo, runtime_root=runtime, modules=True, edition="standalone", test=True)
ed = json.loads(Path(out_sa, "edition.json").read_text(encoding="utf-8"))
check("edition.json = 스탠드얼론·시험용, 버전 목록에 든다", ed == {"edition": "standalone", "test_build": True} and "edition.json" in program, str(ed))
si = Path(out_sa, "server_info.py").read_text(encoding="utf-8")
check("server_info.py 는 빈 값 사본", si == blank, si[:200])
check("웹 파일이 firebase/web/ 에", Path(out_sa, "firebase", "web", "index.html").is_file()
      and "firebase/web/index.html" in program and not Path(out_sa, "firebase", "web", "firebase-config.js").exists())
check("update_helper.py·license_check.py 원본·클라우드 안내는 없다",
      not any(Path(out_sa, n).exists() for n in ("update_helper.py", "license_check.py", "클라우드_안내.txt")))
man = br.write_manifest(out_sa, "2026.11.24-1", "시험", program)
br.make_zip(out_sa, out_sa + ".zip")
others = [rel for rel, _ in br.other_files("standalone")]
p = br.verify_zip(out_sa + ".zip", man, program, others, edition="standalone")
check("깨끗한 스탠드얼론 압축은 검사를 통과", p == [], str(p))
d2 = os.path.join(out_root, "배포_SA_bad")
shutil.copytree(out_sa, d2)
write(os.path.join(d2, "ai_rescue.py"), b"x")
write(os.path.join(d2, "app", "ai_rescue" + SUFFIX), b"x")
br.make_zip(d2, d2 + ".zip")
p = br.verify_zip(d2 + ".zip", man, program, others, edition="standalone")
check("ai_rescue 를 끼우면 들어가면 안 되는 파일", any("들어가면 안 되는 파일: ai_rescue.py" in x for x in p)
      and any(f"들어가면 안 되는 파일: app/ai_rescue{SUFFIX}" in x for x in p), str(p))
p = br.verify_zip(d2 + ".zip", man, program, others)
check("일반 검사는 ai_rescue 를 문제 삼지 않는다 (모은 목록에 없는 파일로만)",
      not any("들어가면 안 되는 파일" in x for x in p) and any("모은 목록에 없는 파일: ai_rescue.py" in x for x in p), str(p))
d3 = os.path.join(out_root, "배포_SA_sig")
shutil.copytree(out_sa, d3)
write(os.path.join(d3, "manifest.sig"), b"ab" * 64)
br.make_zip(d3, d3 + ".zip")
p = br.verify_zip(d3 + ".zip", man, program, others, edition="standalone")
check("manifest.sig 는 모은 목록에 없어도 봐준다", p == [], str(p))
for bad in ("license_check.py", "firebase/web/data-firebase.js", "x.testkey.txt", "update_signing_key.txt"):
    d4 = os.path.join(out_root, "배포_SA_f")
    shutil.rmtree(d4, ignore_errors=True)
    shutil.copytree(out_sa, d4)
    write(os.path.join(d4, *bad.split("/")), b"x")
    br.make_zip(d4, d4 + ".zip")
    p = br.verify_zip(d4 + ".zip", man, program, others, edition="standalone")
    check(f"{bad} 는 들어가면 안 되는 파일", any(f"들어가면 안 되는 파일: {bad}" in x for x in p), str(p))

# 조각: 빈 server_info 를 컴파일하고 ai_rescue 는 만들지 않는다 (가짜 컴파일)
compiled = {}


def fake_compile(src, out_dir):
    name = os.path.splitext(os.path.basename(src))[0]
    compiled[name] = Path(src).read_text(encoding="utf-8")
    path = os.path.join(out_dir, name + SUFFIX)
    write(path, f"pyd {name} {len(compiled[name])}")
    return path


cache = os.path.join(tmp, "pyd_cache")
br.build_modules(os.path.join(tmp, "wm"), cache=cache, compile=fake_compile, edition="standalone")
check("스탠드얼론 조각: server_info 는 빈 값 사본을 컴파일, ai_rescue 는 만들지 않는다",
      compiled.get("server_info") == blank and "ai_rescue" not in compiled, str(sorted(compiled)))
cloud_si = os.path.join(cache, "server_info" + SUFFIX)
check("빈 server_info 조각은 일반 것과 다른 보관 자리 (일반 조각을 덮지 않는다)",
      not os.path.exists(cloud_si) and os.path.isfile(os.path.join(cache, "standalone", "server_info" + SUFFIX)))
compiled.clear()
br.build_modules(os.path.join(tmp, "wm"), cache=cache, compile=fake_compile, edition="standalone")
check("두 번째는 하나도 다시 만들지 않는다 (빈 server_info 도 보관)", compiled == {}, str(sorted(compiled)))
compiled.clear()
br.build_modules(os.path.join(tmp, "wc"), cache=cache, compile=fake_compile)
check("일반 조각: 진짜 server_info·ai_rescue 를 컴파일", compiled.get("server_info") == real_text and "ai_rescue" in compiled)

# ---------------------------------------------------------------------------
print("=== 5. 워크트리의 .venv · 옵션 ===")
real_repo = br.REPO
try:
    br.REPO = os.path.join(tmp, "no_venv_repo")
    os.makedirs(br.REPO, exist_ok=True)
    check(".venv 가 없는 저장소에서는 지금 가상 환경(sys.prefix)", br.venv_root() == sys.prefix, br.venv_root())
    check("site_packages 는 그 아래", br.site_packages() == os.path.join(sys.prefix, "Lib", "site-packages"))
    os.makedirs(os.path.join(br.REPO, ".venv"))
    check("저장소에 .venv 가 있으면 그것", br.venv_root() == os.path.join(br.REPO, ".venv"))
finally:
    br.REPO = real_repo
node = dict(br.PROGRAM_FILES)["playwright/node.exe"]
got = br._src_path(os.path.join(tmp, "empty"), node)
check(".venv/ 원본이 저장소에 없으면 가상 환경 아래에서 찾는다",
      got == os.path.join(br.venv_root(), "Lib", "site-packages", "playwright", "driver", "node.exe") and os.path.isfile(got), got)
check("저장소 안 원본은 그대로", br._src_path(repo, "server_info.py") == os.path.join(repo, "server_info.py"))
check("스탠드얼론은 조각 방식만 (--onefile·--exes-from·--to-dist 는 빌드 전에 1)",
      br.main(["--edition", "standalone", "--onefile"]) == 1 and br.main(["--edition", "standalone", "--exes-from", "x"]) == 1
      and br.main(["--edition", "standalone", "--to-dist"]) == 1)
check("--test-build 는 스탠드얼론에만", br.main(["--test-build"]) == 1)

# ---------------------------------------------------------------------------
print("=== 6. 열쇠와 서명 · 시험용 빌드 (Task 3) ===")
import contextlib  # noqa: E402
import io  # noqa: E402

import license_check  # noqa: E402
import update_sign  # noqa: E402

check("스탠드얼론 조각에 ap_guard.py 가 있다 (일반에도 - exe 셋이 부른다)",
      "ap_guard.py" in {os.path.basename(p) for p in br.module_sources("standalone")}
      and "ap_guard.py" in {os.path.basename(p) for p in br.module_sources()})
txt = 'A = 1\nPUBLIC_KEY_HEX = "abcd"     # 설명\nB = 2\n'
check("swap_key: 그 줄 하나의 값만 바꾼다 (설명은 그대로)",
      br.swap_key(txt, "PUBLIC_KEY_HEX", "ef01") == 'A = 1\nPUBLIC_KEY_HEX = "ef01"     # 설명\nB = 2\n')
for bad, why in (("A = 1\n", "줄이 없음"), ('PUBLIC_KEY_HEX = "a"\nPUBLIC_KEY_HEX = "b"\n', "둘"), ('X_PUBLIC_KEY_HEX = "a"\n', "다른 이름")):
    try:
        br.swap_key(bad, "PUBLIC_KEY_HEX", "ef")
        ok = False
    except RuntimeError:
        ok = True
    check(f"swap_key: {why} → RuntimeError", ok)
real_lc = (ROOT / "license_check.py").read_text(encoding="utf-8")
real_us = (ROOT / "update_sign.py").read_text(encoding="utf-8")
check("진짜 license_check.py·update_sign.py 에 바꿀 줄이 하나씩", br.swap_key(real_lc, "LICENSE_PUBLIC_KEY_HEX", "00") != real_lc
      and br.swap_key(real_us, "PUBLIC_KEY_HEX", "00") != real_us)

up_s, up_p = update_sign.keygen()
lic_s, lic_p = update_sign.keygen()
keys = {"update": up_p.hex(), "license": lic_p.hex()}
ov = br.module_overrides("standalone", keys)
check("시험용 조각: license_check·update_sign 은 시험 공개 열쇠를 끼운 사본 (보관하지 않는다), server_info 는 빈 값 (보관)",
      f'LICENSE_PUBLIC_KEY_HEX = "{lic_p.hex()}"' in ov["license_check"][0] and ov["license_check"][1] is False
      and f'PUBLIC_KEY_HEX = "{up_p.hex()}"' in ov["update_sign"][0] and ov["update_sign"][1] is False and ov["server_info"][1] is True)
check("진짜 스탠드얼론 조각은 원본 열쇠 그대로 (사본을 만들지 않는다)", set(br.module_overrides("standalone")) == {"server_info"})
compiled.clear()
cache2 = os.path.join(tmp, "pyd_cache2")
br.build_modules(os.path.join(tmp, "wt"), cache=cache2, compile=fake_compile, edition="standalone", overrides=ov)
first = dict(compiled)
compiled.clear()
br.build_modules(os.path.join(tmp, "wt"), cache=cache2, compile=fake_compile, edition="standalone", overrides=ov)
check("시험 열쇠 조각은 매번 새로 만들고 보관 폴더에 남기지 않는다",
      lic_p.hex() in first.get("license_check", "") and sorted(compiled) == ["license_check", "update_sign"]
      and not any("license_check" in n for _, _, ns in os.walk(cache2) for n in ns), str(sorted(compiled)))

with tempfile.TemporaryDirectory() as d:
    write(os.path.join(d, "manifest.json"), b'{"version": "x"}')
    sig = br.sign_manifest(d, up_s)
    check("sign_manifest: manifest.sig 를 쓰고 update_sign.verify 를 통과",
          Path(d, "manifest.sig").read_text(encoding="ascii").strip() == sig
          and update_sign.verify(up_p, b'{"version": "x"}', bytes.fromhex(sig)))

# 모으기: 뿌리에 license_check 조각 한 벌, 시험용이면 뿌리 update_sign.py 도 바꿔 끼운 사본
out_t = os.path.join(out_root, "배포_SA_TEST_2026.11.24-2")
swapped_us = br.swap_key(real_us, "PUBLIC_KEY_HEX", up_p.hex())
program_t = br.collect(out_t, work, repo=repo, runtime_root=runtime, modules=True, edition="standalone", test=True,
                       replace={"update_sign.py": swapped_us})
check("뿌리에 app\\license_check 조각 한 벌 (에이전트·로컬 서버가 부른다), 버전 목록에 든다",
      Path(out_t, "license_check" + SUFFIX).read_bytes() == Path(work, "app", "license_check" + SUFFIX).read_bytes()
      and "license_check" + SUFFIX in program_t and not Path(out_t, "license_check.py").exists())
check("뿌리 update_sign.py 는 바꿔 끼운 사본", Path(out_t, "update_sign.py").read_text(encoding="utf-8") == swapped_us)

out = io.StringIO()
real_hex = license_check.LICENSE_PUBLIC_KEY_HEX
launched = []
real_launchers = br.build_launchers


def stop_launchers(*a, **k):
    launched.append(a)
    raise RuntimeError("시험 멈춤 - 여기서 빌드를 시작한다")


try:
    br.build_launchers = stop_launchers
    license_check.LICENSE_PUBLIC_KEY_HEX = ""
    with contextlib.redirect_stdout(out):
        code = br.main(["--edition", "standalone", "--out-root", os.path.join(tmp, "o1"), "--no-setup"])
    check("라이선스 공개 열쇠가 빈 진짜 스탠드얼론 빌드는 빌드 전에 1 과 안내",
          code == 1 and not launched and "라이선스 공개 열쇠(license_check.LICENSE_PUBLIC_KEY_HEX)가 비어 있습니다" in out.getvalue()
          and "--test-build" in out.getvalue(), out.getvalue()[-300:])
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = br.main(["--edition", "standalone", "--test-build", "--out-root", os.path.join(tmp, "o2"), "--no-setup"])
    check("--test-build 는 열쇠 검사를 넘어 빌드를 시작한다 (진짜 열쇠 파일은 열지 않는다)",
          code == 1 and launched and "LICENSE_PUBLIC_KEY_HEX" not in out.getvalue() and "시험 멈춤" in out.getvalue()
          and "서명 열쇠 파일" not in out.getvalue(), out.getvalue()[-300:])
    license_check.LICENSE_PUBLIC_KEY_HEX = "ab" * 32
    launched.clear()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = br.main(["--edition", "standalone", "--sign-key", os.path.join(tmp, "없는_열쇠.txt"), "--out-root", os.path.join(tmp, "o3")])
    check("진짜 스탠드얼론: 업데이트 서명 열쇠 파일이 없으면 빌드 전에 1",
          code == 1 and not launched and "업데이트 서명 열쇠 파일이 없습니다" in out.getvalue(), out.getvalue()[-300:])
    check("license_key_problem: 시험용이면 없음", br.license_key_problem(True) is None and br.license_key_problem(False) is None)
finally:
    br.build_launchers = real_launchers
    license_check.LICENSE_PUBLIC_KEY_HEX = real_hex

if "--keep" not in sys.argv:
    shutil.rmtree(tmp, ignore_errors=True)
finish()
