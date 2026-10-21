# -*- coding: utf-8 -*-
"""서버 주소 한 곳 (2026-10-21): server_info.py · 업체 웹 firebase-config.js · 관리 화면 ops.js 가 같은 값인지,
그 밖의 실행 코드에 Firebase 프로젝트 이름이 다시 박히지 않았는지 본다.

    .venv\\Scripts\\python.exe tests\\test_server_info.py
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")
import server_info as srv  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


web = read("firebase/web/firebase-config.js")
pick = lambda key: (re.search(rf'{key}:\s*"([^"]+)"', web) or [None, None])[1]   # noqa: E731
check("업체 웹 firebase-config.js 의 프로젝트·공개 키·DB 주소·로그인 도메인이 server_info 와 같다",
      (pick("projectId"), pick("apiKey"), pick("databaseURL"), pick("authDomain"))
      == (srv.PROJECT_ID, srv.API_KEY, srv.DATABASE_URL, srv.AUTH_DOMAIN),
      str((pick("projectId"), pick("databaseURL"), pick("authDomain"))))
ops = read("firebase/admin/ops.js")
m = re.search(r'export const PROJECT = "([^"]+)"', ops)
check("관리 화면 ops.js 의 PROJECT 가 server_info.PROJECT_ID 와 같다", bool(m) and m.group(1) == srv.PROJECT_ID, m and m.group(1))
check("ops.js 의 DB 주소는 PROJECT 로 만든다 (따로 박지 않는다)", ops.count(srv.PROJECT_ID) == 1 and "${PROJECT}-default-rtdb" in ops)
d = re.search(r"export const DASHBOARD_URL = [`\"]([^`\"]+)[`\"]", ops)
dash = d and d.group(1).replace("${PROJECT}", m.group(1) if m else "")
check("ops.js 의 업체 웹 주소(DASHBOARD_URL)가 server_info.DASHBOARD_URL 과 같다", dash == srv.DASHBOARD_URL, dash)
check("업체 웹 app.js 의 계정 이메일 도메인은 firebaseConfig.authDomain", "${firebaseConfig.authDomain}" in read("firebase/web/app.js"))

sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
import secret  # noqa: E402
check("에이전트 첫 설정 값(secret.PUBLIC)이 server_info", secret.PUBLIC == {
    "project_id": srv.PROJECT_ID, "api_key": srv.API_KEY, "database_url": srv.DATABASE_URL}, str(secret.PUBLIC))

# 실행 코드(문서·시험·Firebase 배포 설정 빼고)에 프로젝트 이름이 박힌 곳은 server_info 와 위 두 JS 뿐
ALLOWED = {"server_info.py", "firebase/web/firebase-config.js", "firebase/admin/ops.js",
           "firebase/.firebaserc", "firebase/releases.json", "firebase/firebase.admin-web.json"}
files = subprocess.run(["git", "grep", "-l", "-I", srv.PROJECT_ID, "--", "*.py", "*.js", "*.mjs", "*.html", "*.iss", "*.json", "*.bat",
                        ":!docs", ":!tests", ":!firebase/tests", ":!graphify-out", ":!firebase/functions/shared", ":!firebase/admin_web",
                        ":!release/*사용설명서*"],   # 사용 설명서는 문서
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8").stdout.split()
extra = sorted(set(files) - ALLOWED)
check("실행 코드에 프로젝트 이름이 박힌 곳은 server_info·firebase-config.js·ops.js (와 Firebase 배포 설정) 뿐", not extra, str(extra))

print("실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
