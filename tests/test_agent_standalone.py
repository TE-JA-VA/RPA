# -*- coding: utf-8 -*-
"""스탠드얼론: 에이전트·감독 프로그램의 분기 (계획 ① Task 5) - 정책은 라이선스에서, 토큰·업데이트·프리셋 옮기기 없음,
감독이 로컬 서버를 함께 띄우고 지킨다. 일반 버전 동작은 그대로다.
    .venv\\Scripts\\python.exe tests\\test_agent_standalone.py
"""
import os
import shutil
import sys
import tempfile
import threading
import time

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
TMP = tempfile.mkdtemp(prefix="rpa_sagent_")
PD = os.path.join(TMP, "pd")
os.makedirs(PD)
ENV = ("RPA_PROGRAMDATA", "RPA_EDITION", "RPA_MACHINE_GUID", "RPA_STATUS_DIR", "RPA_AGENT_QUEUE", "RPA_USER_CONFIG")
saved_env = {k: os.environ.get(k) for k in ENV}
os.environ.update(RPA_PROGRAMDATA=PD, RPA_MACHINE_GUID="p1", RPA_STATUS_DIR=os.path.join(TMP, "status"),
                  RPA_AGENT_QUEUE=os.path.join(TMP, "queue.jsonl"))       # 실제 설정·기록을 건드리지 않게 (가져오기 전에)
os.environ.pop("RPA_EDITION", None)

import update_sign  # noqa: E402
import rpa_status as st  # noqa: E402
import rpa_update  # noqa: E402
import agent  # noqa: E402
import background as bg  # noqa: E402

fails = []
PY = sys.executable


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


class FakeClient:
    """patch 를 기록하는 가짜 서버 연결."""

    def __init__(self):
        self.patches = []

    def patch(self, path, value):
        self.patches.append((path, value))

    def server_now(self):
        return 1000.0


try:
    print("업체 정책 계산 나누기")
    check("policy_from - 한도·안 쓰는 모듈", agent.policy_from("c1", {"limits": {"schedule": 3}, "modules": {"Hold": False}, "features": {}})
          == (3, ["Hold"], False, None, None))
    check("policy_from - 웰라이프 (업체코드)", agent.policy_from("wellife_x", {})[2] is True)
    check("policy_from - 웰라이프 (기능 칸)", agent.policy_from("c1", {"features": {"wellife": True}})[2] is True
          and set(agent.WELLIFE_BLOCKED) <= set(agent.policy_from("c1", {"features": {"wellife": True}})[1]))
    check("policy_from - 한도가 없으면 기본", agent.policy_from("c1", {})[0] == agent.SCHEDULE_LIMIT_DEFAULT)

    class Got:
        def get(self, path):
            return {"limits": {"schedule": 4}, "modules": {"Sales": False}}
    cp = agent.company_policy(Got(), "c1")
    check("company_policy 는 같은 계산 (일반 버전 그대로)", cp == agent.policy_from("c1", {"limits": {"schedule": 4}, "modules": {"Sales": False}})
          and cp[0] == 4 and "Sales" in cp[1])

    print("라이선스 정책")
    applied, ai = [], []
    real_apply, real_set_ai = agent.apply_policy, st.set_ai
    agent.apply_policy = applied.append
    st.set_ai = lambda on, key: ai.append((on, key))
    try:
        lp = agent.LicensePolicy({"cid": "c1", "limits": {"schedule": 2, "presets": None, "parallel": None},
                                  "modules": {"Hold": False}, "features": {"wellife": False}})
        got = lp.refresh(force=True)
        check("라이선스 값이 같은 길로 적힌다", got == (2, ["Hold"], False, None, None) and applied == [got])
        check("AI 어시스트는 늘 끈다 (남은 키도 지움)", ai == [(False, None)])
        check("때가 안 됐으면 다시 안 적는다", lp.refresh() is None and len(applied) == 1)
    finally:
        agent.apply_policy, st.set_ai = real_apply, real_set_ai

    print("명령 - 스탠드얼론에서 안 쓰는 것")
    acts = agent.real_actions(standalone=True)
    off = ("update", "rollback", "export_preset", "import_preset", "restore_preset")
    check("명령 종류는 그대로 있다 (launch 등)", {"launch", "stop_rpa", "set_schedule", "set_modules", "set_presets"} <= set(acts))
    said = []
    for k in off:
        try:
            acts[k]({}, {}) if k in agent.META_TYPES else acts[k]({})
            said.append("(예외 없음)")
        except RuntimeError as e:
            said.append(str(e))
    check("업데이트·되돌리기·프리셋 옮기기는 거절 글", all("스탠드얼론 버전에서는 사용하지 않는 기능입니다" in s for s in said), repr(said))
    fake = FakeClient()
    cmds = agent.Commands(fake, "c1", "p1", acts)
    verdict = cmds.handle("k1", {"state": "queued", "type": "update", "by": agent.ADMIN_TOOL_BY, "expires_at": 9e9, "args": {"version": "x"}}, now=1)
    end = time.time() + 5
    while time.time() < end and not any(v.get("state") == "failed" for _, v in fake.patches):
        time.sleep(0.05)
    last = [v for _, v in fake.patches if v.get("state") == "failed"]
    check("그 명령은 실패로 닫힌다", bool(last) and "스탠드얼론 버전에서는" in last[-1]["result"], f"{verdict} {fake.patches}")
    check("일반 버전은 그대로 (update 는 진짜 동작)", agent.real_actions()["update"].__name__ == "do_update"
          and agent.real_actions()["export_preset"].__name__ == "do_export")

    print("토큰 없음")
    nt = agent.NoTokens()
    check("늘 통장 없음 - 막지 않고 화면도 숨긴다", nt.refresh(force=True) is None and nt.view() is None and nt.balance is None)

    print("에이전트 main")
    os.environ["RPA_EDITION"] = "standalone"
    logs = []
    real_log, real_single, real_run = agent.log, agent.single_instance, agent.run
    agent.log = logs.append
    agent.single_instance = lambda *a: True
    try:
        check("라이선스 없음 → 2 (다시 켜지 않는다), 까닭을 기록에", agent.main() == 2 and any("라이선스 파일이 없습니다" in x for x in logs), repr(logs))
        import license_check
        import json
        lic_secret, lic_public = update_sign.keygen()
        saved_pub = license_check.LICENSE_PUBLIC_KEY_HEX
        license_check.LICENSE_PUBLIC_KEY_HEX = lic_public.hex()
        body = {"edition": "standalone", "company": "시험상사", "cid": "c1", "pc_id": "p1", "issued": "2026-11-23",
                "modules": {}, "features": {"wellife": False}, "limits": {"schedule": 2, "presets": None, "parallel": None}}
        with open(os.path.join(PD, "license.json"), "w", encoding="utf-8") as f:
            json.dump(license_check.sign_body(lic_secret, body), f, ensure_ascii=False)
        try:
            del logs[:]
            check("열쇠가 아직 없음 → 1 (감독이 다시 켠다)", agent.main() == 1 and any("로컬 서버" in x for x in logs), repr(logs))
            os.makedirs(os.path.join(PD, "standalone"))
            with open(os.path.join(PD, "standalone", "agent.key"), "w", encoding="ascii") as f:
                f.write("k" * 43 + "\n")
            ran = []
            import fb
            agent.run = lambda cfg: ran.append(cfg) or fb.AuthError(401, "INVALID_KEY")
            del logs[:]
            code = agent.main()
            check("설정이 라이선스·열쇠에서 온다", len(ran) == 1 and ran[0]["standalone"] and ran[0]["cid"] == "c1" and ran[0]["key"] == "k" * 43)
            check("서버가 열쇠를 거절 → 1 (묻지 않고 다시)", code == 1 and not any("k" * 43 in x for x in logs), f"{code} {logs}")
            agent.run = lambda cfg: None
            check("정상 끝 → 0", agent.main() == 0)

            print("사내 서버 연결 (사내 서버 ⑤ Task 5)")
            import local_store
            import secret
            import seat
            seat_secret, seat_public = update_sign.keygen()
            import lan_ca
            lan_ca.make_ca(os.path.join(TMP, "ca"), ["nt"], ["192.168.1.230"])
            ca_text = lan_ca.ca_pem(os.path.join(TMP, "ca"))          # Client 가 TLS 컨텍스트로 읽을 수 있는 진짜 인증 기관
            srv_body = {"edition": "standalone", "kind": "server", "company": "시험상사", "cid": "c1", "server_id": "0" * 32,
                        "seat_pub": seat_public.hex(), "seats": 5, "modules": {"Hold": False}, "features": {}, "limits": {"schedule": 3}}
            out = {"server_url": "https://192.168.1.230:8444", "pc_id": "pc_01", "agent_key": "a" * 64, "relay_key": "b" * 64,
                   "ca_pem": ca_text}
            link = license_check.link_path()

            def put_link():
                doc = license_check.link_doc(out, seat.issue(seat_secret, "c1", "pc_01", "p1", 1,
                                                             ca=license_check.ca_fingerprint(ca_text)),
                                             license_check.sign_body(lic_secret, srv_body))
                with open(link, "w", encoding="utf-8") as f:
                    json.dump(doc, f, ensure_ascii=False)
            os.remove(os.path.join(PD, "license.json"))
            put_link()
            cfg = secret.load_config()
            check("연결 파일만 → lan 설정 (https 주소·pc_01·agent 열쇠·인증 기관)",
                  cfg.get("lan") is True and cfg["standalone"] and cfg["server_url"] == out["server_url"] and cfg["pc_id"] == "pc_01"
                  and cfg["key"] == "a" * 64 and cfg["ca_pem"] == ca_text and cfg["cid"] == "c1" and cfg["role"] == "agent", cfg)
            check("정책은 서버 라이선스 body (pc_id 덧붙임)", cfg["license"]["limits"] == {"schedule": 3} and cfg["license"]["pc_id"] == "pc_01")
            check("relay 역할은 relay 열쇠", secret.load_config(role="relay")["key"] == "b" * 64)
            check("이 설정으로 lan Client 를 만들 수 있다", isinstance(local_store.client_for(cfg), local_store.Client))
            agent.run = lambda cfg: fb.AuthError(403, local_store.PC_DISABLED)
            del logs[:]
            check("사용 중지 → 6 (다시 켜지 않는다), 연결 파일은 남는다", agent.main() == agent.LAN_DISABLED_CODE == 6 and os.path.isfile(link))
            agent.run = lambda cfg: fb.AuthError(0, local_store.NOT_VERIFIED)
            del logs[:]
            check("서버를 확인하지 못함 → 1 (다시), 파일 남음, 기록에 까닭·열쇠 없음",
                  agent.main() == 1 and os.path.isfile(link) and any("사내 서버를 확인하지 못했습니다" in x for x in logs)
                  and not any("a" * 64 in x for x in logs), repr(logs))
            agent.run = lambda cfg: fb.AuthError(403, local_store.PC_REMOVED)
            check("지워짐 → 7, 연결 파일을 지운다", agent.main() == agent.LAN_REMOVED_CODE == 7 and not os.path.exists(link))
            check("감독의 멈춤 까닭 6·7", "사용 중지" in bg.STOP_CODES.get(6, "") and "다시 등록" in bg.STOP_CODES.get(7, ""))
            with open(os.path.join(PD, "license.json"), "w", encoding="utf-8") as f:
                json.dump(license_check.sign_body(lic_secret, body), f, ensure_ascii=False)
            agent.run = lambda cfg: fb.AuthError(403, local_store.PC_DISABLED)
            check("단독 설정에 같은 오류면 지금처럼 1", agent.main() == 1)
        finally:
            license_check.LICENSE_PUBLIC_KEY_HEX = saved_pub
    finally:
        agent.log, agent.single_instance, agent.run = real_log, real_single, real_run

    print("변조 감지 서명 - 망에 나가지 않는다")
    prog = os.path.join(TMP, "prog")
    os.makedirs(prog)
    man = b'{"version": "2026.11.23-9", "files": {}}'
    with open(os.path.join(prog, st.MANIFEST_NAME), "wb") as f:
        f.write(man)
    upd_secret, upd_public = update_sign.keygen()
    called = []

    def no_net(url):
        called.append(url)
        raise rpa_update.FetchError("시험: 망을 쓰면 안 된다")
    check("실린 서명이 없으면 모름 (None)", rpa_update.ensure_installed_sig(prog, get=no_net, pub=upd_public) is None and not called)
    with open(os.path.join(prog, "manifest.sig"), "w", encoding="ascii") as f:
        f.write(update_sign.sign(upd_secret, man).hex() + "\n")
    check("설치 파일이 실어 둔 서명을 쓴다", rpa_update.ensure_installed_sig(prog, get=no_net, pub=upd_public) == "saved" and not called)
    check("이미 맞는 서명이면 그대로", rpa_update.ensure_installed_sig(prog, get=no_net, pub=upd_public) == "kept" and not called)
    with open(os.path.join(prog, "manifest.sig"), "w", encoding="ascii") as f:
        f.write("00" * 64 + "\n")
    os.remove(st.installed_sig_path())
    check("틀린 서명은 저장하지 않는다", rpa_update.ensure_installed_sig(prog, get=no_net, pub=upd_public) is None
          and not os.path.exists(st.installed_sig_path()) and not called)
    os.environ["RPA_EDITION"] = "cloud"
    rpa_update.ensure_installed_sig(prog, get=no_net, pub=upd_public)
    check("일반 버전은 업데이트 사이트에서 받는다 (그대로)", len(called) >= 1)

    print("감독 - 로컬 서버를 함께 띄우고 지킨다")
    os.environ["RPA_EDITION"] = "standalone"
    marks = os.path.join(TMP, "marks.txt")
    server_code = f"import sys,time; open(r'{marks}','a').write('server\\n'); time.sleep(0.2); sys.exit(1)"
    # 가짜 에이전트: 서버가 두 번 켜진 것을 볼 때까지 (길어야 30초) 살아 있다가 '다시 켜지 않는 코드' 2 로 끝난다
    # (시간으로 기다리면 안 된다 - 이 PC 는 새 프로세스를 처음 띄울 때 몇 초 걸린다)
    agent_code = (f"import sys,time; p=r'{marks}'; open(p,'a').write('agent\\n'); e=time.time()+30\n"
                  f"while time.time()<e and open(p).read().split().count('server')<2: time.sleep(0.1)\n"
                  f"sys.exit(2)")
    quick_agent = f"import sys,time; open(r'{marks}','a').write('agent\\n'); time.sleep(1.0); sys.exit(2)"
    warmed = []
    real_warm = bg.warm_windows_roots
    bg.warm_windows_roots = lambda *a, **k: warmed.append(1)
    try:
        check("서버 명령은 같은 파이썬·같은 깃발로 local_server.py", bg.server_command()[-1].endswith("local_server.py")
              and bg.server_command()[:-1] == bg.agent_command()[:-1])
        code = bg.main(cmd=[PY, "-c", agent_code], backoff=(0.01,), sleep=lambda s: None,
                       server_cmd=[PY, "-c", server_code], server_backoff=(0.05,), keys_wait=0.3)
        got = open(marks, encoding="utf-8").read().split()
        check("서버 먼저, 그다음 에이전트", got[0] == "server" and "agent" in got, repr(got))
        check("죽은 서버는 다시 켠다", got.count("server") >= 2, repr(got))
        check("에이전트가 '다시 켜지 않는 코드' 로 끝나면 감독도 끝", code == 2)
        time.sleep(1.0)                    # 끝내는 중에 막 띄운 것이 있으면 적히게 둔 뒤
        n = len(open(marks, encoding="utf-8").read().split())
        time.sleep(1.5)
        check("감독이 끝나면 서버도 더 켜지 않는다", len(open(marks, encoding="utf-8").read().split()) == n)
        os.remove(marks)
        lic_stop = f"import sys; open(r'{marks}','a').write('server\\n'); sys.exit(2)"
        bg.main(cmd=[PY, "-c", quick_agent], backoff=(0.01,), sleep=lambda s: None,
                server_cmd=[PY, "-c", lic_stop], server_backoff=(0.05,), keys_wait=0.1)
        time.sleep(1.0)
        check("라이선스로 끝난 서버(2)는 다시 켜지 않는다", open(marks, encoding="utf-8").read().split().count("server") == 1)
        # 포트를 다른 프로그램이 쓰고 있어 서버가 3 으로 끝남 (검토 2026-11-23 8번): 계속 다시 켜 보되 기록은 가끔만, 에이전트는 띄운다
        # (에이전트는 가짜 서버의 답을 믿지 않는다 - test_local_store_client)
        os.remove(marks)
        port_busy = f"import sys; open(r'{marks}','a').write('server\\n'); sys.exit(3)"
        slow_agent = (f"import sys,time; p=r'{marks}'; open(p,'a').write('agent\\n'); e=time.time()+30\n"
                      f"while time.time()<e and open(p).read().split().count('server')<6: time.sleep(0.1)\n"
                      f"sys.exit(2)")
        log_file = os.path.join(bg.log_dir(), bg.LOG_NAME)
        size = os.path.getsize(log_file) if os.path.exists(log_file) else 0
        real_every = bg.SERVER_LOG_EVERY
        bg.SERVER_LOG_EVERY = 4
        try:
            bg.main(cmd=[PY, "-c", slow_agent], backoff=(0.01,), sleep=lambda s: None,
                    server_cmd=[PY, "-c", port_busy], server_backoff=(0.05,), keys_wait=0.1)
        finally:
            bg.SERVER_LOG_EVERY = real_every
        got = open(marks, encoding="utf-8").read().split()
        with open(log_file, encoding="utf-8") as f:
            f.seek(size)
            lines = [x for x in f.read().splitlines() if "로컬 서버가 멈췄습니다" in x]
        check("포트를 못 열어도 계속 다시 켜 본다", got.count("server") >= 6 and "agent" in got, repr(got))
        check("까닭(포트를 다른 프로그램이 씀)을 기록에", any("포트를 다른 프로그램이 쓰고 있습니다" in x for x in lines), repr(lines[:2]))
        check("같은 까닭은 가끔만 기록 (끝없이 쌓이지 않는다)", 1 <= len(lines) <= got.count("server") // 2, f"{len(lines)}줄 / {got.count('server')}번")

        print("감독 - 사내 서버 연결이면 로컬 서버를 띄우지 않는다 (사내 서버 ⑤ Task 5)")
        import license_check
        os.remove(marks)
        lic_file = os.path.join(PD, "license.json")
        if os.path.exists(lic_file):
            os.remove(lic_file)
        os.makedirs(os.path.dirname(license_check.link_path()), exist_ok=True)
        with open(license_check.link_path(), "w", encoding="utf-8") as f:
            f.write("{}")                                  # 감독은 파일이 있는지만 본다 (확인은 에이전트·exe 가)
        check("_lan(): 연결 파일만 있으면 참", bg._lan() is True)
        lan_agent = f"import sys,time; open(r'{marks}','a').write('agent\\n'); time.sleep(0.3); sys.exit(6)"
        server_mark = f"import sys; open(r'{marks}','a').write('server\\n'); sys.exit(1)"
        code = bg.main(cmd=[PY, "-c", lan_agent], backoff=(0.01,), sleep=lambda s: None,
                       server_cmd=[PY, "-c", server_mark], server_backoff=(0.05,), keys_wait=0.3)
        time.sleep(0.5)
        got = open(marks, encoding="utf-8").read().split()
        check("로컬 서버 명령을 부르지 않고 에이전트만", got == ["agent"], repr(got))
        stop = json.load(open(os.path.join(bg.log_dir(), bg.STOP_NAME), encoding="utf-8"))
        check("에이전트가 6 으로 끝나면 감독도 끝, 멈춤 까닭은 STOP_CODES[6]", code == 6 and stop.get("reason") == bg.STOP_CODES[6], stop)
        os.remove(license_check.link_path())
        check("_lan(): 연결 파일이 없으면 거짓 (지금 길)", bg._lan() is False)
        box = []
        bg.main = lambda *a, **k: box.append("main") or 0
        bg.run()
        check("스탠드얼론은 Google 인증서 데우기를 하지 않는다", box == ["main"] and not warmed)
        os.environ["RPA_EDITION"] = "cloud"
        bg.run()
        check("일반 버전은 그대로 데운다", len(warmed) == 1)
    finally:
        bg.warm_windows_roots = real_warm
finally:
    for k, v in saved_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n실패: {len(fails)}" + (f" ({', '.join(fails)})" if fails else ""))
sys.exit(1 if fails else 0)
