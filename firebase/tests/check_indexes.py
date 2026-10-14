# -*- coding: utf-8 -*-
"""웹 '이번 달 사용량' 이 모듈마다 더하는 칸(used.<모듈>)에 Firestore 색인이 다 있나 (서버 없이).

색인이 없으면 그 질의만 늘 실패하고, 화면이 현황마다(1초) 다시 읽어 하루 읽기 한도를 다 쓴다
(2026-10-14 운송장번호 전송 used.invoicesend - Spark 'Quota exceeded'). 에뮬레이터는 색인을 안 따져 check_web 으로는 못 잡는다.
    .venv\\Scripts\\python.exe firebase\\tests\\check_indexes.py
"""
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
common = open(os.path.join(ROOT, "web", "rpa-common.js"), encoding="utf-8").read()
block = re.search(r"export const MODULES = \[(.*?)\];", common, re.S).group(1)
need = {"used." + k.lower() for k in re.findall(r'\["(\w+)",', block) if k != "Login"} | {"used.sites"}
idx = json.load(open(os.path.join(ROOT, "rules", "firestore.indexes.json"), encoding="utf-8"))
have = {f["fieldPath"] for i in idx["indexes"] if [x["fieldPath"] for x in i["fields"]][:1] == ["started_at"] for f in i["fields"][1:]}
missing = sorted(need - have)
print(("통과" if not missing else "실패") + " 사용량 칸마다 started_at 색인이 있다" + (f"  없음: {missing}" if missing else ""))
sys.exit(1 if missing else 0)
