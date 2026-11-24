# -*- coding: utf-8 -*-
"""사내 서버 ① 검토 고침 (2026-11-24 검토 I-1·I-2·I-3·M-5, 계획 2026-11-24-lan-1-server-multi-pc).
  I-1  다른 PC 가 만료된 요청의 req_id 로 다시 열어 옛 번호를 읽던 것 - 요청을 열 때 번호 자리를 같이 지우고, 번호는 요청보다
       늦게 쓴 것만 읽히고, 남의 요청은 pcId·created_at 만 보인다
  I-2  /fs-sum 이 PC 를 가리지 않던 것 - 사내 서버는 자기 PC 문서만 더한다
  I-3  쓰레기 /enroll 다섯 번으로 남의 등록 대기를 취소하던 것 - 틀린 증명은 세기만 하고, 거절 기록은 60초에 10줄까지
  M-5  ASCII 가 아닌 서명 머리글로 500·오류 기록이 나던 것 - 서명 없는 401
TLS·사내 주소 없이 127.0.0.1 서버(port=0)에 PC 등록부를 달고 가짜 PC 둘로 본다. 임시 폴더에만 쓴다.
    D:/AX/RPA/.venv/Scripts/python.exe tests/test_lan_review_fixes.py
"""
import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
import local_phone  # noqa: E402
import local_server  # noqa: E402
import local_store  # noqa: E402
import pc_registry  # noqa: E402

fails = []
TMP = tempfile.mkdtemp(prefix="rpa_lan_fix_")
LIC = {"edition": "standalone", "company": "시험상사", "cid": "c1", "pc_id": "srv", "issued": "2026-11-24",
       "modules": {}, "features": {}, "limits": {}}
NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))
H_PC = local_store.H_PC


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def until(fn, sec):
    """fn() 이 참이 될 때까지 (시간이 아니라 조건으로 기다린다) → 참이 됐으면 True."""
    end = time.time() + sec
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.02)
    return bool(fn())


class Got:
    def __init__(self, status, raw, headers, signed):
        self.status, self.raw, self.headers, self.signed = status, raw, headers, signed

    def json(self):
        try:
            return json.loads(self.raw) if self.raw else None
        except ValueError:
            return None


def ap2_headers(key, pc, role, method, target, body=b""):
    ts = str(int(time.time() * 1000))
    nonce = os.urandom(16).hex()
    return {local_store.H_ROLE: role, local_store.H_TIME: ts, local_store.H_NONCE: nonce, H_PC: pc,
            local_store.H_SIGN: local_store._mac(key, ["ap2", "req", pc, role, method, target, ts, nonce, local_store._digest(body)])}


def send(base, method, path, data, hs, verify_key):
    hs = dict(hs)
    hs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(base + path, data=data or None, method=method, headers=hs)
    nonce = hs.get(local_store.H_NONCE, "")
    try:
        with NO_PROXY.open(req, timeout=10) as r:
            got, status, rh = r.read(), r.status, r.headers
    except urllib.error.HTTPError as e:
        got, status, rh = e.read(), e.code, e.headers
    signed = bool(verify_key) and (rh.get(local_store.H_SIGN) or "") == local_store.response_mac(verify_key, nonce, status, got)
    return Got(status, got.decode("utf-8", "replace"), rh, signed)


def body_of(method, body):
    return b"" if body is None and method in ("GET", "DELETE") else json.dumps(body, ensure_ascii=False).encode("utf-8")


def call2(method, path, body=None, pc="pc_01", role="agent"):
    """PC 하나의 ap2 요청. 응답 서명은 그 역할의 열쇠로 본다."""
    key = PCS[pc][local_store.ROLES.index(role)]
    data = body_of(method, body)
    return send(BASE, method, path, data, ap2_headers(key, pc, role, method, path, data), key)


def call1(base, method, path, key, body=None):
    """단독(ap1) 서명 요청."""
    data = body_of(method, body)
    return send(base, method, path, data, local_store.sign_headers(key, "agent", method, path, data), key)


def enroll_raw(start, rand, guid, host, proof=None):
    """등록 요청 한 번 (서명 머리글 없음) → Got. 응답 서명은 새 agent 열쇠와 본문 nonce 로 본다."""
    nonce = os.urandom(16).hex()
    pc = start["pc_id"]
    keys = pc_registry.derive_keys(start["token"], rand)
    body = {"v": 1, "pc": pc, "rand": rand, "guid": guid, "host": host, "nonce": nonce,
            "proof": proof or pc_registry.enroll_proof(start["token"], pc, rand, guid, host)}
    req = urllib.request.Request(BASE + "/enroll", data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with NO_PROXY.open(req, timeout=10) as r:
            got, status, rh = r.read(), r.status, r.headers
    except urllib.error.HTTPError as e:
        got, status, rh = e.read(), e.code, e.headers
    signed = (rh.get(local_store.H_SIGN) or "") == local_store.response_mac(keys[0], nonce, status, got)
    return Got(status, got.decode("utf-8", "replace"), rh, signed)


def raw_sign(port, path, pc=None):
    """X-AP-Sign 에 ASCII 가 아닌 바이트(é 64개)를 실은 GET (열쇠 없이) → (상태, 본문, 서명 머리글)."""
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        c.putrequest("GET", path)
        heads = [(local_store.H_ROLE, "agent"), (local_store.H_TIME, str(int(time.time() * 1000))), (local_store.H_NONCE, "n" * 32)]
        if pc:
            heads.append((H_PC, pc))
        for k, v in heads:
            c.putheader(k, v)
        c.putheader(local_store.H_SIGN, b"\xe9" * 64)
        c.endheaders()
        r = c.getresponse()
        return r.status, r.read(), r.getheader(local_store.H_SIGN)
    finally:
        c.close()


def log_text(folder):
    try:
        return open(os.path.join(folder, local_server.LOG_NAME), encoding="utf-8").read()
    except FileNotFoundError:
        return ""


def reject_lines(folder):
    return [x for x in log_text(folder).splitlines() if "PC 등록 거절" in x]


class Clock:                       # 지금 시각 + 밀어 둔 초 (요청 만료를 기다리지 않고 본다)
    def __init__(self):
        self.ahead = 0.0

    def __call__(self):
        return time.time() + self.ahead


GUIDS = ["11111111-2222-3333-4444-5555555555%02d" % i for i in range(10)]
RANDS = [("%02x" % i) * 32 for i in range(1, 10)]
PCS = {}
srv = srv1 = runs = runs1 = None
try:
    store = local_server.Store(os.path.join(TMP, "store.json"), volatile=local_server.VOLATILE)
    runs = local_server.Runs(os.path.join(TMP, "runs.db"))
    reg = pc_registry.Registry(os.path.join(TMP, "pcs.json"), seats=5)
    clk = Clock()
    PFOLD = os.path.join(TMP, "phone")
    os.makedirs(PFOLD)
    svc = local_phone.Service(PFOLD, store, LIC, clock=clk)
    PH = "ph_5a5a5a5a"
    svc.phones.add(PH, "총무 휴대폰", "", ["01012345678"], key="s" * 64, fp="f" * 64, os="android", app_version="1", device="Fake")
    srv = local_server.make_server(store, runs, LIC, None, port=0, folder=TMP, registry=reg, phone=svc)
    PORT = srv.server_address[1]
    BASE = f"http://127.0.0.1:{PORT}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    TMP1 = os.path.join(TMP, "single")
    os.makedirs(TMP1)
    store1 = local_server.Store(os.path.join(TMP1, "store.json"), volatile=local_server.VOLATILE)
    runs1 = local_server.Runs(os.path.join(TMP1, "runs.db"))
    AGENT1, RELAY1 = local_server.ensure_keys(TMP1)
    LIC1 = dict(LIC, pc_id="p1")
    srv1 = local_server.make_server(store1, runs1, LIC1, (AGENT1, RELAY1), port=0, folder=TMP1)
    BASE1 = f"http://127.0.0.1:{srv1.server_address[1]}"
    threading.Thread(target=srv1.serve_forever, daemon=True).start()

    for i, label in ((1, "1층 PC"), (2, "2층 PC")):
        s = reg.start(label)
        PCS[s["pc_id"]] = reg.enroll(s["pc_id"], RANDS[i], GUIDS[i], f"OFFICE-{i}",
                                     pc_registry.enroll_proof(s["token"], s["pc_id"], RANDS[i], GUIDS[i], f"OFFICE-{i}"))
    check("준비 - PC 둘 등록", sorted(PCS) == ["pc_01", "pc_02"], repr(sorted(PCS)))

    # ------------------------------------------------------------------------------------------
    RQ, CD = f"apps/otp/requests/c1/{PH}/current", f"apps/otp/codes/c1/{PH}/current"
    RQP, CDP = f"/db/{RQ}.json", f"/db/{CD}.json"

    def otp_body(pc, req_id):
        return {"req_id": req_id, "site": "시험몰", "pcId": pc, "senders": {"01012345678": True}, "created_at": {".sv": "timestamp"}}

    def code_of(req_id, code):
        return {"req_id": req_id, "code": code, "sender": "01012345678", "sms_at": int(clk() * 1000)}

    print("test_otp_other_pc_sees_only_owner - I-1 c: 남의 요청은 pcId·created_at 만")
    r = call2("PUT", RQP, otp_body("pc_01", "req_rev_a0000001"), role="relay")
    check("pc_01 이 요청 PUT 200", r.status == 200, f"{r.status} {r.raw}")
    r = call2("GET", RQP, pc="pc_02", role="relay")
    got = r.json()
    check("pc_02 GET 남의 살아 있는 요청 → pcId·created_at 만 (req_id 가 안 보인다)",
          r.status == 200 and isinstance(got, dict) and set(got) == {"pcId", "created_at"} and got["pcId"] == "pc_01"
          and "req_rev_a0000001" not in r.raw, f"{r.status} {r.raw}")
    r = call2("GET", RQP, pc="pc_02", role="agent")
    check("… pc_02 의 agent 열쇠로도 같다", r.status == 200 and set(r.json() or {}) == {"pcId", "created_at"}, f"{r.status} {r.raw}")
    r = call2("GET", RQP, role="relay")
    check("pc_01 은 자기 요청을 다 본다", r.status == 200 and (r.json() or {}).get("req_id") == "req_rev_a0000001"
          and (r.json() or {}).get("site") == "시험몰", f"{r.status} {r.raw}")

    print("test_otp_reopen_same_req_id_after_expiry - I-1 검토 재현: 만료 뒤 같은 req_id 로 다시 열면")
    check("휴대폰이 pc_01 요청에 번호를 넣는다", svc.desk.submit(PH, code_of("req_rev_a0000001", "654321")) == (200, None))
    clk.ahead += 121                   # pc_01 의 요청이 만료 - 정리 고리(sweep) 전
    r = call2("PUT", RQP, otp_body("pc_02", "req_rev_a0000001"), pc="pc_02", role="relay")
    check("pc_02 가 같은 req_id 로 PUT 200", r.status == 200, f"{r.status} {r.raw}")
    r = call2("GET", CDP, pc="pc_02", role="relay")
    check("pc_02 GET codes → null (pc_01 의 옛 번호를 못 읽는다)", r.status == 200 and r.json() is None and "654321" not in r.raw,
          f"{r.status} {r.raw}")
    check("… 번호 자리 자체가 지워졌다", store.get(CD) is None, repr(store.get(CD)))
    call2("DELETE", RQP, pc="pc_02", role="relay")

    print("test_desk_open_clears_code - I-1 a: 요청 열기와 번호 지우기는 한 번의 쓰기")
    desk = svc.desk
    check("pc_01 이 연다", desk.open(PH, {"req_id": "req_rev_b0000001", "site": "시험몰", "pcId": "pc_01",
                                       "senders": {"01012345678": True}}, "pc_01") is True)
    check("번호를 넣는다", desk.submit(PH, code_of("req_rev_b0000001", "111222")) == (200, None) and store.get(CD) is not None)
    check("다른 PC 의 열기는 거절되고 번호도 그대로", desk.open(PH, {"req_id": "req_rev_c0000001", "site": "시험몰", "pcId": "pc_02",
                                                       "senders": {"01012345678": True}}, "pc_02") is False
          and (store.get(CD) or {}).get("code") == "111222")
    check("같은 PC 가 같은 req_id 로 다시 열면 번호 자리가 지워진다", desk.open(PH, {"req_id": "req_rev_b0000001", "site": "시험몰",
                                                                          "pcId": "pc_01", "senders": {"01012345678": True}}, "pc_01") is True
          and store.get(CD) is None and (store.get(RQ) or {}).get("req_id") == "req_rev_b0000001", repr(store.get(CD)))
    store.patch("apps/otp", {f"codes/c1/{PH}/current": {"req_id": "x" * 8, "code": "1"}})
    store.patch("apps/otp", {f"codes/c1/{PH}/current": None})
    check("Store.patch 의 None 은 그 자리를 지운다", store.get(CD) is None)

    print("test_read_code_written_after_request - I-1 b: 번호는 요청보다 늦게 쓴 것만")
    created = store.get(RQ)["created_at"]
    base = {"req_id": "req_rev_b0000001", "code": "333444", "sender": "01012345678", "sms_at": created}
    store.put(CD, dict(base, written_at=created - 1))
    check("요청보다 먼저 쓴 번호 → None", desk.read_code(PH, "pc_01") is None)
    store.put(CD, base)
    check("written_at 없는 번호 → None", desk.read_code(PH, "pc_01") is None)
    store.put(CD, dict(base, written_at=True))
    check("written_at 이 불리언 → None", desk.read_code(PH, "pc_01") is None)
    store.put(CD, dict(base, written_at=float(created)))
    check("written_at 이 정수가 아님 → None", desk.read_code(PH, "pc_01") is None)
    store.put(CD, dict(base, written_at=created))
    check("요청과 같은 시각에 쓴 번호 → 읽힌다", (desk.read_code(PH, "pc_01") or {}).get("code") == "333444")
    check("… 남의 PC 는 여전히 None", desk.read_code(PH, "pc_02") is None)
    desk.forget(PH)
    check("기록에 인증번호가 없다", all(c not in log_text(TMP) for c in ("654321", "111222", "333444")))

    # ------------------------------------------------------------------------------------------
    print("test_fs_sum_own_pc - I-2: 사내 서버의 합은 자기 PC 문서만")
    da = {"pcId": "pc_01", "date": "2026-11-24", "started_at": "2026-11-24T10:00:00", "cost": 7, "count": 123}
    db = {"pcId": "pc_02", "date": "2026-11-24", "started_at": "2026-11-24T11:00:00", "cost": 2, "count": 5}
    check("pc_01·pc_02 가 각자 기록을 올린다", call2("POST", "/fs/runs/c1/items?id=runA1", da).status == 200
          and call2("POST", "/fs/runs/c1/items?id=runB1", db, pc="pc_02").status == 200)
    SUM = "/fs-sum?parent=runs%2Fc1&collection=items&field=count"
    r1, r2 = call2("GET", SUM), call2("GET", SUM, pc="pc_02")
    check("pc_01 의 합은 자기 것만 (123)", r1.status == 200 and r1.signed and r1.json() == {"sum": 123}, f"{r1.status} {r1.raw}")
    check("pc_02 의 합은 자기 것만 (5)", r2.status == 200 and r2.json() == {"sum": 5}, f"{r2.status} {r2.raw}")
    r = call2("GET", "/fs-sum?parent=runs%2Fc1&collection=items&field=cost&since=2026-11-24T10%3A30%3A00", pc="pc_02")
    check("since 와 함께도 자기 것만", r.json() == {"sum": 2}, r.raw)
    r = call2("GET", "/fs-sum?parent=runs%2Fc1&collection=items&field=cost&since=2026-11-24T10%3A30%3A00")
    check("… pc_01 은 since 뒤 자기 문서가 없어 0", r.json() == {"sum": 0}, r.raw)
    try:
        sums = (runs.sum("runs/c1", "items", "count", pc_id="pc_01"), runs.sum("runs/c1", "items", "count", pc_id="pc_02"),
                runs.sum("runs/c1", "items", "count"))
    except TypeError as e:
        sums = repr(e)
    check("Runs.sum(pc_id=) - 거르기", sums == (123, 5, 128), repr(sums))
    runs1.create("runs/c1", "items", "s1", {"pcId": "p1", "started_at": "2026-11-24T09:00:00", "count": 3})
    runs1.create("runs/c1", "items", "s2", {"pcId": "p9", "started_at": "2026-11-24T09:00:00", "count": 4})
    r = call1(BASE1, "GET", SUM, AGENT1)
    check("단독은 그대로 - 업체 전체 합 (7)", r.status == 200 and r.json() == {"sum": 7}, f"{r.status} {r.raw}")

    # ------------------------------------------------------------------------------------------
    print("test_enroll_junk_does_not_cancel - I-3: 틀린 증명은 대기를 취소하지 않는다")
    LT = [1000.0]
    srv.log_clock = lambda: LT[0]      # 거절 기록 창(60초)을 시험 시계로
    sa = reg.start("3층 PC")
    junk = [enroll_raw(sa, RANDS[3], GUIDS[3], "OFFICE-3", proof="0" * 64) for _ in range(10)]
    check("쓰레기 등록 10번은 모두 403 bad_proof", all(j.status == 403 and j.json() == {"error": "bad_proof"} for j in junk),
          repr([(j.status, j.raw) for j in junk[-2:]]))
    check("… 대기는 그대로", any(x["pcId"] == sa["pc_id"] and x["state"] == "pending" for x in reg.list()))
    r = enroll_raw(sa, RANDS[3], GUIDS[3], "OFFICE-3")
    check("그 뒤 진짜 PC 의 등록 200 (서명된 답)", r.status == 200 and r.signed and r.json() == {"pc": sa["pc_id"]}, f"{r.status} {r.raw}")
    check("10번까지는 거절을 모두 기록한다", len(reject_lines(TMP)) == 10, len(reject_lines(TMP)))

    print("test_enroll_reject_log_limited - I-3: 거절 기록은 60초에 10줄까지")
    sb = reg.start("4층 PC")
    for _ in range(40):
        enroll_raw(sb, RANDS[4], GUIDS[4], "OFFICE-4", proof="0" * 64)
    lines = reject_lines(TMP)
    check("쓰레기 50번에 거절 기록은 11줄 이하", len(lines) <= 11, f"{len(lines)}줄")
    check("… 4층 PC 대기도 그대로", any(x["pcId"] == sb["pc_id"] and x["state"] == "pending" for x in reg.list()))
    LT[0] += 61
    enroll_raw(sb, RANDS[4], GUIDS[4], "OFFICE-4", proof="0" * 64)
    lines = reject_lines(TMP)
    check("창이 넘어가면 생략한 수를 한 줄로 남긴다", any("PC 등록 거절 40건 더 (기록 생략)" in x for x in lines), "\n".join(lines[-3:]))
    check("… 그리고 새 거절 한 줄", len(lines) == 12 and "까닭=bad_proof" in lines[-1], "\n".join(lines[-3:]))
    r = enroll_raw(sb, RANDS[4], GUIDS[4], "OFFICE-4")
    check("쓰레기 41번 뒤에도 진짜 등록 200", r.status == 200 and r.signed, f"{r.status} {r.raw}")
    text = log_text(TMP)
    check("기록에 토큰·증명이 없다", all(x not in text for x in (sa["token"], sb["token"], "0" * 64,
                                                            pc_registry.enroll_proof(sa["token"], sa["pc_id"], RANDS[3], GUIDS[3], "OFFICE-3"))))

    # ------------------------------------------------------------------------------------------
    print("test_non_ascii_sign - M-5: ASCII 가 아닌 서명 머리글")
    before = log_text(TMP).count("요청 처리 오류")
    st, raw, sg = raw_sign(PORT, "/db/apps/rpa/live/c1/pc_01.json", pc="pc_01")
    check("사내 서버 → 서명 없는 401", st == 401 and sg is None and json.loads(raw or b"null") == {"error": "Unauthorized"}, f"{st} {raw!r}")
    check("… '요청 처리 오류' 기록이 없다", log_text(TMP).count("요청 처리 오류") == before, log_text(TMP)[-200:])
    st, raw, sg = raw_sign(srv1.server_address[1], "/db/apps/rpa/live/c1/p1.json")
    check("단독 서버 → 서명 없는 401", st == 401 and sg is None and json.loads(raw or b"null") == {"error": "Unauthorized"}, f"{st} {raw!r}")
    check("… '요청 처리 오류' 기록이 없다", "요청 처리 오류" not in log_text(TMP1), log_text(TMP1)[-200:])
    check("단독은 맞는 서명이면 그대로 200", call1(BASE1, "GET", "/db/apps/rpa/live/c1/p1.json", AGENT1).status == 200)

    # ==========================================================================================
    # 사내 서버 ② Task 7 - ① 검토에서 넘긴 정리 (M-3·M-6·M-7·M-9·M-10·M-11·②-T3b)
    # ==========================================================================================
    def enroll_direct(r, label, i):
        s = r.start(label)
        keys = r.enroll(s["pc_id"], RANDS[i], GUIDS[i], f"OFFICE-{i}",
                        pc_registry.enroll_proof(s["token"], s["pc_id"], RANDS[i], GUIDS[i], f"OFFICE-{i}"))
        return s["pc_id"], keys

    def api(base, method, path, body=None, token=None):
        """웹 API 한 번 (서명 없음) → Got."""
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        hs = {"Content-Type": "application/json"} if data is not None else {}
        if token:
            hs["Authorization"] = "Bearer " + token
        req = urllib.request.Request(base + path, data=data, method=method, headers=hs)
        try:
            with NO_PROXY.open(req, timeout=10) as r:
                got, status, rh = r.read(), r.status, r.headers
        except urllib.error.HTTPError as e:
            got, status, rh = e.read(), e.code, e.headers
        return Got(status, got.decode("utf-8", "replace"), rh, False)

    # ------------------------------------------------------------------------------------------
    print("test_live_write_after_remove_refused - M-3: 검사를 통과한 뒤 지운·중지한 PC 의 현황 쓰기")
    PC5, K5 = enroll_direct(reg, "5층 PC", 5)
    PCS[PC5] = K5
    LIVE5 = f"/db/apps/rpa/live/c1/{PC5}.json"
    real_seen = reg.seen

    def seen_then(action):
        """서명·상태 검사를 통과한 바로 뒤(seen)에 관리자가 PC 를 중지·삭제한 모양."""
        def hook(pc):
            if pc == PC5:
                action(pc)
            return real_seen(pc)
        return hook

    reg.seen = seen_then(lambda pc: reg.disable(pc, True))
    try:
        r = call2("PUT", LIVE5, {"state": "idle", "pcId": PC5}, pc=PC5)
    finally:
        del reg.seen
    check("중지된 직후의 현황 PUT → 서명된 403 pc_disabled", r.status == 403 and r.signed and r.json() == {"error": "pc_disabled"},
          f"{r.status} {r.raw} signed={r.signed}")
    check("… 현황 자리가 생기지 않았다", store.get(f"apps/rpa/live/c1/{PC5}") is None, repr(store.get(f"apps/rpa/live/c1/{PC5}")))
    reg.disable(PC5, False)
    check("다시 사용하면 현황 PUT 200", call2("PUT", LIVE5, {"state": "idle"}, pc=PC5).status == 200)
    store.delete(f"apps/rpa/live/c1/{PC5}")
    reg.seen = seen_then(reg.remove)
    try:
        r = call2("PATCH", LIVE5, {"state": "busy"}, pc=PC5)
    finally:
        del reg.seen
    check("지운 직후의 현황 PATCH → 서명된 403 pc_removed", r.status == 403 and r.signed and r.json() == {"error": "pc_removed"},
          f"{r.status} {r.raw} signed={r.signed}")
    check("… 지운 PC 의 현황 자리가 다시 생기지 않았다", store.get(f"apps/rpa/live/c1/{PC5}") is None,
          repr(store.get(f"apps/rpa/live/c1/{PC5}")))
    check("살아 있는 PC 의 현황 쓰기는 그대로 200", call2("PATCH", "/db/apps/rpa/live/c1/pc_01.json", {"state": "idle"}).status == 200)

    # ------------------------------------------------------------------------------------------
    print("test_runs_doc_keys_per_pc - M-6: 실행 기록 문서 키에 PC 번호")
    d1 = {"pcId": "pc_01", "date": "2026-11-24", "started_at": "2026-11-24T12:00:00", "count": 1}
    d2 = {"pcId": "pc_02", "date": "2026-11-24", "started_at": "2026-11-24T12:00:00", "count": 2}
    r1 = call2("POST", "/fs/runs/c1/items?id=same1", d1)
    r2 = call2("POST", "/fs/runs/c1/items?id=same1", d2, pc="pc_02")
    check("같은 id 를 두 PC 가 따로 만든다 (둘 다 200)", r1.status == 200 and r2.status == 200 and r2.json() == {"id": "same1"},
          f"{r1.status} {r1.raw} / {r2.status} {r2.raw}")
    g1, g2 = call2("GET", "/fs/runs/c1/items/same1"), call2("GET", "/fs/runs/c1/items/same1", pc="pc_02")
    check("GET 은 각자 자기 문서", g1.status == 200 and (g1.json() or {}).get("count") == 1
          and g2.status == 200 and (g2.json() or {}).get("count") == 2, f"{g1.raw} / {g2.raw}")
    call2("POST", "/fs/runs/c1/items?id=only2", d2, pc="pc_02")
    r = call2("GET", "/fs/runs/c1/items/only2")
    check("남의 문서 GET → 404 (403 아님, 서명된 답)", r.status == 404 and r.signed, f"{r.status} {r.raw}")
    r = call2("POST", "/fs/runs/c1/items?id=same1", d1)
    check("자기 것 다시 만들기 → 409", r.status == 409, f"{r.status} {r.raw}")
    r = call2("POST", "/fs/runs/c1/items?id=pc_02%3Aonly2", d1)
    check("남의 키 모양 id 도 자기 칸 안 (200, 남의 문서는 그대로)", r.status == 200
          and (call2("GET", "/fs/runs/c1/items/only2", pc="pc_02").json() or {}).get("pcId") == "pc_02", f"{r.status} {r.raw}")
    check("합은 그대로 자기 것만", call2("GET", "/fs-sum?parent=runs%2Fc1&collection=items&field=count", pc="pc_02").json() == {"sum": 2 + 2 + 5},
          call2("GET", "/fs-sum?parent=runs%2Fc1&collection=items&field=count", pc="pc_02").raw)
    runs1.create("runs/c1", "items", "legacy1", {"pcId": "p1", "started_at": "2026-11-24T08:00:00", "count": 9})
    r = call1(BASE1, "GET", "/fs/runs/c1/items/legacy1", AGENT1)
    check("단독 - 옛 runs.db 문서를 그대로 읽는다", r.status == 200 and (r.json() or {}).get("count") == 9, f"{r.status} {r.raw}")
    r = call1(BASE1, "POST", "/fs/runs/c1/items?id=legacy1", AGENT1, {"pcId": "p1"})
    check("단독 - 같은 id 는 409 (그대로)", r.status == 409, f"{r.status} {r.raw}")

    # ------------------------------------------------------------------------------------------
    print("test_nonce_table_time_sweep - M-7: nonce 표는 10초마다 시간으로 정리, PC 별 분당 1200")
    now = time.time()
    with srv.conn_lock:
        srv.nonces.clear()
        for i in range(100):
            srv.nonces[f"old{i}"] = now - 1
    srv.fresh_nonce("new-a", now + 11)
    check("표가 작아도 10초가 지나면 지난 nonce 를 지운다", set(srv.nonces) == {"new-a"}, f"{len(srv.nonces)}개")
    srv.nonces["old-x"] = now - 1
    srv.fresh_nonce("new-b", now + 12)
    check("… 10초 안에는 요청마다 훑지 않는다", "old-x" in srv.nonces, f"{len(srv.nonces)}개")
    srv.fresh_nonce("new-c", now + 22)
    check("… 다음 10초에 지운다", "old-x" not in srv.nonces and "new-c" in srv.nonces, f"{sorted(srv.nonces)[:5]}")
    check("다시 보낸 nonce 는 여전히 거절", srv.fresh_nonce("new-c", now + 22) is False)

    LIMIT = getattr(local_server, "PC_REQ_MIN", 1200)
    RC = [1000.0]
    srv.rate_clock = lambda: RC[0]
    srv.pc_reqs = {"pc_01": [RC[0], LIMIT - 1]}
    r = call2("GET", "/db/apps/rpa/live/c1/pc_01.json")
    check(f"분당 {LIMIT}번째 서명 요청은 200", r.status == 200, f"{r.status} {r.raw}")
    r = call2("GET", "/db/apps/rpa/live/c1/pc_01.json")
    check("그 다음은 서명된 429 Too many requests", r.status == 429 and r.signed and r.json() == {"error": "Too many requests"},
          f"{r.status} {r.raw} signed={r.signed}")
    check("… 다른 PC 는 그대로 200", call2("GET", "/db/apps/rpa/live/c1/pc_02.json", pc="pc_02").status == 200)
    RC[0] += 61
    check("1분이 지나면 다시 200", call2("GET", "/db/apps/rpa/live/c1/pc_01.json").status == 200)
    check("상수 PC_REQ_MIN = 1200", getattr(local_server, "PC_REQ_MIN", None) == 1200)
    r = call1(BASE1, "GET", "/db/apps/rpa/live/c1/p1.json", AGENT1)
    check("단독은 세지 않는다 (200)", r.status == 200 and not getattr(srv1, "pc_reqs", {}), f"{r.status} {getattr(srv1, 'pc_reqs', None)}")

    # ------------------------------------------------------------------------------------------
    import dataclasses
    import lan_server
    import local_web
    BOSS_PW = "pw-12345678"
    WD = os.path.join(TMP, "web")
    os.makedirs(WD)
    with open(os.path.join(WD, "pcs.json"), "w", encoding="utf-8") as f:
        json.dump({"v": 1, "next": 9996, "pcs": {}}, f)
    storeW = local_server.Store(os.path.join(WD, "store.json"), volatile=local_server.VOLATILE)
    runsW = local_server.Runs(os.path.join(WD, "runs.db"))
    regW = pc_registry.Registry(os.path.join(WD, "pcs.json"), seats=20)
    webW = local_web.Web(storeW, runsW, LIC, WD, None, registry=regW)
    webW.accounts.set("boss", BOSS_PW, "admin")
    srvW = local_server.make_server(storeW, runsW, LIC, None, port=0, folder=WD, web=webW, registry=regW)
    BASEW = f"http://127.0.0.1:{srvW.server_address[1]}"
    threading.Thread(target=srvW.serve_forever, daemon=True).start()
    BOSSW = api(BASEW, "POST", "/api/login", {"id": "boss", "password": BOSS_PW}).json()["token"]

    print("test_number_cap - M-9: 번호 상한 pc_9999")
    capf = os.path.join(TMP, "cap.json")
    with open(capf, "w", encoding="utf-8") as f:
        json.dump({"v": 1, "next": 9999, "pcs": {}}, f)
    rc = pc_registry.Registry(capf, seats=5)
    check("pc_9999 까지는 만든다", rc.start("마지막")["pc_id"] == "pc_9999")
    try:
        rc.start("넘침")
        err = None
    except Exception as e:                       # noqa: BLE001
        err = e
    check("그 다음은 ValueError (SeatsFull 아님)", isinstance(err, ValueError) and not isinstance(err, pc_registry.SeatsFull)
          and str(err) == "더 이상 PC 번호를 만들 수 없습니다.", repr(err))
    check("… 번호를 올리지 않았다 (파일 next 그대로)", json.load(open(capf, encoding="utf-8"))["next"] == 10000)
    PCW, KW = enroll_direct(regW, "웹 시험 PC", 6)            # pc_9996
    got = [api(BASEW, "POST", "/api/pcs", {"label": f"추가 {i}"}, BOSSW) for i in range(4)]
    check("웹 - pc_9997·pc_9998·pc_9999 까지 200", [g.status for g in got[:3]] == [200, 200, 200]
          and [(g.json() or {}).get("pcId") for g in got[:3]] == ["pc_9997", "pc_9998", "pc_9999"], repr([(g.status, g.raw[:80]) for g in got]))
    check("웹 - 그 다음 POST /api/pcs → 409", got[3].status == 409 and "더 이상 PC 번호" in got[3].raw, f"{got[3].status} {got[3].raw}")

    print("test_pc_remove_concurrent_enroll - M-11: 지우기와 같은 때 끝난 등록이 자리를 남기지 않는다")
    pend = "pc_9999"                             # 위에서 웹으로 만든 대기 (토큰은 등록 글 안에)
    info = pc_registry.decode_enrollment(got[2].json()["enrollment"])
    real_remove = regW.remove
    side = {}

    def racing_enroll():
        try:
            regW.enroll(pend, RANDS[7], GUIDS[7], "OFFICE-7",
                        pc_registry.enroll_proof(info["token"], pend, RANDS[7], GUIDS[7], "OFFICE-7"))
        except pc_registry.EnrollError as e:
            side["enroll"] = e.code
            return
        side["enroll"] = "ok"
        storeW.put(f"apps/rpa/live/c1/{pend}", {"state": "idle"})      # 등록을 마친 PC 의 첫 현황

    def remove_with_race(pc):
        t = threading.Thread(target=racing_enroll, daemon=True)
        side["t"] = t
        t.start()
        t.join(0.5)                              # 등록부 잠금이 없으면 그 사이에 등록이 끝난다
        return real_remove(pc)

    regW.remove = remove_with_race
    try:
        r = api(BASEW, "DELETE", f"/api/pcs/{pend}", None, BOSSW)
    finally:
        del regW.remove
    side["t"].join(5)
    check("DELETE /api/pcs → 200", r.status == 200, f"{r.status} {r.raw}")
    check("… 남은 현황 자리가 없다", storeW.get(f"apps/rpa/live/c1/{pend}") is None,
          f"enroll={side.get('enroll')} live={storeW.get(f'apps/rpa/live/c1/{pend}')!r}")
    check("… 그 번호는 active 가 아니다", regW.state(pend) != "active", repr(regW.state(pend)))

    print("test_web_streams_from_deploy - M-11: 웹 구독 상한은 서버 배치를 따른다")
    check("붙은 사내 서버 웹 창구 → LAN.web_streams", webW.max_streams == local_server.LAN.web_streams, repr(webW.max_streams))
    srvW.deploy = dataclasses.replace(srvW.deploy, web_streams=0)
    check("배치를 바꾸면 따라간다", webW.max_streams == 0, repr(webW.max_streams))
    c = http.client.HTTPConnection("127.0.0.1", srvW.server_address[1], timeout=10)
    try:                                         # 상태 줄만 본다 (열린 스트림은 끝나지 않는다)
        c.request("GET", f"/api/stream?pcId={PCW}", headers={"Authorization": "Bearer " + BOSSW, "Host": "127.0.0.1"})
        st = c.getresponse().status
    finally:
        c.close()
    check("… 상한 0 이면 스트림 503", st == 503, repr(st))
    srvW.deploy = local_server.LAN
    check("붙지 않은 창구 - 사내 서버는 LAN.web_streams, 단독은 MAX_STREAMS",
          local_web.Web(storeW, runsW, LIC, WD, None, registry=regW).max_streams == local_server.LAN.web_streams
          and local_web.Web(store1, runs1, LIC1, TMP1, None).max_streams == local_web.MAX_STREAMS)

    print("test_registry_same_object - M-11: 웹 창구의 등록부와 서버의 등록부가 같은 것")
    other = pc_registry.Registry(os.path.join(TMP, "other.json"), seats=2)

    def raises(fn):
        try:
            s = fn()
        except ValueError:
            return True
        except Exception as e:                   # noqa: BLE001
            return f"{type(e).__name__}: {e}"
        try:
            s.server_close()
        except Exception:
            pass
        return False

    w_none = local_web.Web(storeW, runsW, LIC, WD, None)
    w_other = local_web.Web(storeW, runsW, LIC, WD, None, registry=other)
    check("make_server(LAN) + 등록부 없는 웹 → ValueError", raises(lambda: local_server.make_server(
        storeW, runsW, LIC, None, port=0, folder=WD, web=w_none, registry=regW)) is True)
    check("make_server(LAN) + 다른 등록부 웹 → ValueError", raises(lambda: local_server.make_server(
        storeW, runsW, LIC, None, port=0, folder=WD, web=w_other, registry=regW)) is True)
    check("make_server(단독) + 등록부 있는 웹 → ValueError", raises(lambda: local_server.make_server(
        store1, runs1, LIC1, (AGENT1, RELAY1), port=0, folder=TMP1, web=w_other)) is True)
    res = raises(lambda: lan_server.make_lan_servers(storeW, runsW, LIC, regW, w_other, None, None, None, None))
    check("make_lan_servers + 다른 등록부 웹 → ValueError (포트를 열기 전에)", res is True, repr(res))

    # ------------------------------------------------------------------------------------------
    print("test_single_needs_keys - M-10: 단독 make_server 는 열쇠가 꼭 있어야 한다")
    res = raises(lambda: local_server.make_server(store1, runs1, LIC1, None, port=0, folder=TMP1))
    check("단독 make_server(keys=None) → ValueError", res is True, repr(res))

    print("test_single_other_pcid_403 - M-10: 단독 웹 API 에 다른 pcId 를 실으면 403 (그대로 둔다)")
    SD = os.path.join(TMP, "single_web")
    os.makedirs(SD)
    webS = local_web.Web(store1, runs1, LIC1, SD, None)
    webS.accounts.set("boss", BOSS_PW, "admin")
    srvS = local_server.make_server(store1, runs1, LIC1, (AGENT1, RELAY1), port=0, folder=SD, web=webS)
    BASES = f"http://127.0.0.1:{srvS.server_address[1]}"
    threading.Thread(target=srvS.serve_forever, daemon=True).start()
    BOSSS = api(BASES, "POST", "/api/login", {"id": "boss", "password": BOSS_PW}).json()["token"]
    check("GET /api/runs?pcId=다른 PC → 403", api(BASES, "GET", "/api/runs?pcId=p9", None, BOSSS).status == 403)
    check("POST /api/commands pcId=다른 PC → 403", api(BASES, "POST", "/api/commands", {"pcId": "p9", "type": "run"}, BOSSS).status == 403)
    check("GET /api/stream?pcId=다른 PC → 403", api(BASES, "GET", "/api/stream?pcId=p9", None, BOSSS).status == 403)
    check("자기 pcId 나 없으면 200", api(BASES, "GET", "/api/runs?pcId=p1", None, BOSSS).status == 200
          and api(BASES, "GET", "/api/runs", None, BOSSS).status == 200)

    # ------------------------------------------------------------------------------------------
    print("test_single_thread_start_fail_releases - ②-T3b: 단독 서버가 스레드를 못 띄우면 센 연결을 돌려준다")
    import socket
    real_start = threading.Thread.start

    def failing_start(self):
        if getattr(self, "_target", None) == srvS.process_request_thread:
            raise RuntimeError("스레드를 못 띄움 (시험)")
        return real_start(self)

    threading.Thread.start = failing_start
    try:
        c = socket.create_connection(("127.0.0.1", srvS.server_address[1]), timeout=5)
        c.sendall(b"GET /api/session HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
        try:
            back = c.recv(100)
        except OSError:
            back = b""
        c.close()
        released = until(lambda: srvS.conns == 0, 3)
    finally:
        threading.Thread.start = real_start
    check("스레드를 못 띄우면 답 없이 닫는다", back == b"", repr(back[:60]))
    check("그때 센 연결을 돌려준다 (conns 0)", released, repr(srvS.conns))
    check("그 뒤 정상 요청은 된다", api(BASES, "GET", "/api/runs", None, BOSSS).status == 200)
    check("… 연결 수가 돌아온다", until(lambda: srvS.conns == 0, 3), repr(srvS.conns))
finally:
    for s in (srv, srv1, globals().get("srvW"), globals().get("srvS")):
        if s is not None:
            try:
                s.shutdown()
                s.server_close()
            except Exception:
                pass
    for r in (runs, runs1, globals().get("runsW")):
        try:
            r.close()
        except Exception:
            pass
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n실패: {len(fails)}" + (f" ({', '.join(fails)})" if fails else ""))
sys.exit(1 if fails else 0)
