# tests/test_sandbox_site.py
# -*- coding: utf-8 -*-
"""샌드박스 업데이트 시험의 가짜 호스팅 만들기 (tools/sandbox_test.build_site) - 내장 파이썬이 바뀐 판 R·RC (설계 2026-11-20).
샌드박스는 띄우지 않는다. 만든 사이트에서 rpa_update.fetch_release 가 계획대로 받는지까지 본다 (가짜 배포 폴더·가짜 파이썬 폴더)."""
import io
import json
import os
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
tmp = tempfile.mkdtemp(prefix="rpa_sbsite_")
os.environ["RPA_PROGRAMDATA"] = os.path.join(tmp, "pd")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [REPO, os.path.join(REPO, "tools")]
import build_release as br  # noqa: E402
import rpa_status as st  # noqa: E402
import rpa_update as up  # noqa: E402
import sandbox_test as sb  # noqa: E402

fails = []


def check(cond, what):
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        fails.append(what)


def put(root, rel, text):
    full = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as f:
        f.write(text.encode("utf-8"))


def sha(text):
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


VER = "2026.11.20-1"
PROGRAM = ["a.py", "rpa_dashboard.py", "firebase/agent/agent.py", "python/AFTER_MARKET_RPA_Supervisor.exe"]
REL = os.path.join(tmp, f"배포_{VER}")
for rel, text in (("a.py", "A"), ("rpa_dashboard.py", "DASH\r\n"), ("firebase/agent/agent.py", "AGENT"), ("python/AFTER_MARKET_RPA_Supervisor.exe", "SUP"),
                  ("python/python.exe", "PY7"), ("python/python314.dll", "DLL7"), ("python/Lib/os.py", "OS"), ("python/Lib/gone.py", "GONE"),
                  ("python/Lib/__pycache__/os.cpython-314.pyc", "PYC7")):
    put(REL, rel, text)
MAN = {"format": 1, "version": VER, "built_at": "x", "builder": "t", "runtime": {"python": "3.14.7"},
       "files": {r: st.file_digest(os.path.join(REL, *r.split("/"))) for r in PROGRAM}, "runtime_files": br.runtime_file_list(REL, PROGRAM)}
with open(os.path.join(REL, "manifest.json"), "w", encoding="utf-8") as f:
    json.dump(MAN, f)
NEWPY = os.path.join(tmp, "newpy")
for rel, text in (("python.exe", "PY10"), ("python314.dll", "DLL10"), ("Lib/os.py", "OS"), ("Lib/new.py", "NEW"), ("Lib/__pycache__/os.cpython-314.pyc", "PYC10")):
    put(NEWPY, rel, text)
sb.python_info = lambda d: "3.14.10 OpenSSL 3.5.9" if os.path.normpath(d) == os.path.normpath(NEWPY) else "3.14.7 OpenSSL 3.5.7"
BASE = "https://example.test"


def getter(site):
    def get(url):
        full = os.path.join(site, *url[len(BASE) + 1:].split("/"))
        if not os.path.isfile(full):
            raise up.FetchError(f"받지 못했습니다: {url.rsplit('/', 1)[-1]} (404)")
        return open(full, "rb").read()
    return get


def plan_of(version, site, pub):
    prog, stg = os.path.join(tmp, "prog"), os.path.join(tmp, "stg")
    shutil.rmtree(prog, ignore_errors=True)
    shutil.copytree(REL, prog)
    up.fetch_release(version, prog, stg, base_url=BASE, get=getter(site), pub=bytes.fromhex(pub))
    return json.load(open(os.path.join(stg, "plan.json"), encoding="utf-8")), stg


print("=== 1. --update --runtime: 판 B·C 와 내장 파이썬이 바뀐 판 R·RC ===")
work = os.path.join(tmp, "work")
os.makedirs(work)
vb, vc, pub = sb.build_site(VER, REL, work, runtime=NEWPY)
site = os.path.join(work, "site")
vers = open(os.path.join(site, "versions.txt")).read().split()
check(vers == ["2026.11.20-9001", "2026.11.20-9002", "2026.11.20-9003", "2026.11.20-9004"] and (vb, vc) == tuple(vers[:2]), f"versions.txt 에 B·C·R·RC ({vers})")
check(open(os.path.join(site, "runtime.txt")).read().splitlines() == ["3.14.7 OpenSSL 3.5.7", "3.14.10 OpenSSL 3.5.9"], "runtime.txt 에 판 A 의 파이썬과 새 파이썬")
mr = json.load(open(os.path.join(site, "releases", vers[2], "manifest.json"), encoding="utf-8"))
check(mr["runtime"] == {"python": "3.14.10"} and set(mr["runtime_files"]) == {"python/python.exe", "python/python314.dll", "python/Lib/os.py", "python/Lib/new.py"}
      and mr["runtime_files"]["python/python314.dll"]["sha256"] == sha("DLL10") and set(mr["files"]) == set(PROGRAM)
      and mr["files"]["python/AFTER_MARKET_RPA_Supervisor.exe"] == MAN["files"]["python/AFTER_MARKET_RPA_Supervisor.exe"],
      f"판 R 의 목록: 파이썬 표기와 runtime_files 가 새 파이썬 것, 이름 붙인 exe 는 그대로 ({mr['runtime']} {sorted(mr['runtime_files'])})")
mb = json.load(open(os.path.join(site, "releases", vb, "manifest.json"), encoding="utf-8"))
check(mb["runtime"] == MAN["runtime"] and mb["runtime_files"] == MAN["runtime_files"], "판 B 는 파이썬이 판 A 와 같다")
blobs = set(os.listdir(os.path.join(site, "blobs")))
check({sha("PY10"), sha("DLL10"), sha("NEW")} <= blobs and not {sha("OS"), sha("GONE"), sha("PY7"), sha("DLL7"), sha("A")} & blobs,
      "사이트에는 판 A 와 다른 파일만 남긴다 (같은 파이썬 파일을 받으려 들면 404 로 드러난다)")
check(not os.path.exists(os.path.join(work, "test_key.txt")) and not os.path.exists(os.path.join(work, "rel")), "시험용 비밀 열쇠와 작업 사본은 지운다")
plan, stg = plan_of(vers[2], site, pub)
check(plan["fetch"] == ["python/Lib/new.py", "python/python.exe", "python/python314.dll", "rpa_dashboard.py"] and plan["remove"] == ["python/Lib/gone.py"]
      and plan["new"] == ["python/Lib/new.py"], f"판 A 에서 판 R 로: 바뀐 파이썬 파일을 받고 없어진 것은 치운다 ({plan})")
check(open(os.path.join(stg, "files", "python", "python314.dll"), "rb").read() == b"DLL10", "받은 파이썬 파일은 새 버전 것")
plan, _ = plan_of(vers[3], site, pub)
check("firebase/agent/agent.py" in plan["fetch"] and "python/python314.dll" in plan["fetch"], f"판 RC 는 파이썬도 바뀌고 에이전트도 켜지지 않는 것 ({plan['fetch']})")
plan, _ = plan_of(vb, site, pub)
check(plan["fetch"] == ["python/AFTER_MARKET_RPA_Supervisor.exe", "rpa_dashboard.py"] and plan["remove"] == [], f"판 B 로는 python 폴더의 파이썬 파일을 안 받는다 ({plan})")

print("\n=== 2. --from: 파이썬 표기가 같은 옛 판에서 올라올 때는 파이썬 파일을 사이트에 두지 않는다 ===")
OLD = os.path.join(tmp, "배포_2026.11.19-1")
os.makedirs(OLD)
old_man = {k: v for k, v in MAN.items() if k != "runtime_files"}
old_man["version"] = "2026.11.19-1"
# 옛 판의 다른 경로(old_copy.py)에 새 rpa_dashboard.py 와 같은 내용이 있다 - 옛 코드는 경로로 견줘 rpa_dashboard.py 를 받으므로 사이트에 남겨야 한다
# (검토 2026-11-20: 지문만 보고 지워 2026-11-19 의 아이콘 넷(같은 바이트)이 --from 2026.11.18-2 에서 404 가 됐을 것)
old_man["files"] = dict(MAN["files"], **{"rpa_dashboard.py": {"sha256": sha("OLD DASH"), "size": 8},
                                          "old_copy.py": {"sha256": sha("DASH\r\n"), "size": 6}})
with open(os.path.join(OLD, "manifest.json"), "w", encoding="utf-8") as f:
    json.dump(old_man, f)
work2 = os.path.join(tmp, "work2")
os.makedirs(work2)
sb.build_site(VER, REL, work2, a_manifest=os.path.join(OLD, "manifest.json"))
blobs2 = set(os.listdir(os.path.join(work2, "site", "blobs")))
check(sha("DASH\r\n") in blobs2 and not {sha("PY7"), sha("DLL7"), sha("OS"), sha("GONE")} & blobs2 and os.path.isfile(os.path.join(work2, "site", "transition.txt")),
      "옛 판이 받을 것(바뀐 프로그램 파일)만 남고 내장 파이썬 파일은 없다 - 옛 업데이트 코드가 받으려 들면 404 로 드러난다")
check(len(open(os.path.join(work2, "site", "versions.txt")).read().split()) == 2, "--runtime 이 없으면 판은 B·C 둘")
check(not os.path.exists(os.path.join(work2, "site", "runtime.txt")), "파이썬 표기가 같은 전환에는 runtime.txt 가 없다")

print("\n=== 3. --from: 파이썬이 다른 옛 판(다리 버전)에서 올라오는 실제 전환 - 파이썬 파일을 남기고 runtime.txt 를 쓴다 ===")
OLD3 = os.path.join(tmp, "배포_2026.11.18-1")
shutil.copytree(REL, OLD3)
for rel, text in (("python/python.exe", "PY5"), ("python/python314.dll", "DLL5")):
    put(OLD3, rel, text)
old3 = json.loads(json.dumps(MAN))
old3.update(version="2026.11.18-1", runtime={"python": "3.14.5"}, runtime_files=br.runtime_file_list(OLD3, PROGRAM))
with open(os.path.join(OLD3, "manifest.json"), "w", encoding="utf-8") as f:
    json.dump(old3, f)
sb.python_info = lambda d: "3.14.5 OpenSSL 3.5.5" if os.path.normpath(d).startswith(os.path.normpath(OLD3)) else "3.14.7 OpenSSL 3.5.7"
work3 = os.path.join(tmp, "work3")
os.makedirs(work3)
sb.build_site(VER, REL, work3, a_manifest=os.path.join(OLD3, "manifest.json"))
blobs3 = set(os.listdir(os.path.join(work3, "site", "blobs")))
check({sha("PY7"), sha("DLL7")} <= blobs3 and not {sha("OS"), sha("GONE")} & blobs3,
      "옛 판과 지문이 다른 파이썬 파일은 사이트에 남기고, 같은 것은 두지 않는다")
check(open(os.path.join(work3, "site", "runtime.txt")).read().splitlines() == ["3.14.5 OpenSSL 3.5.5", "3.14.7 OpenSSL 3.5.7"],
      "runtime.txt 에 옛 판의 파이썬과 새 판의 파이썬 - 샌드박스가 업데이트·되돌리기 뒤 python 폴더를 견준다")

shutil.rmtree(tmp, ignore_errors=True)
print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
