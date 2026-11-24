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
finally:
    for s in (srv, srv1):
        if s is not None:
            try:
                s.shutdown()
                s.server_close()
            except Exception:
                pass
    for r in (runs, runs1):
        try:
            r.close()
        except Exception:
            pass
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n실패: {len(fails)}" + (f" ({', '.join(fails)})" if fails else ""))
sys.exit(1 if fails else 0)
