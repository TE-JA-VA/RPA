# -*- coding: utf-8 -*-
"""사내 서버 ① Task 2 - PC 등록부 pc_registry (계획 2026-11-24-lan-1-server-multi-pc).
번호 pc_01 꼴·한 번만 쓰는 10분 등록 토큰·PC 난수로 열쇠 만들기·자리 수·등록 글 한 줄. 포트는 열지 않는다. 시계는 가짜.
    D:/AX/RPA/.venv/Scripts/python.exe tests/test_pc_registry.py
"""
import base64
import json
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
import pc_registry  # noqa: E402

fails = []
TMP = tempfile.mkdtemp(prefix="rpa_pc_registry_")
T = [1795000000.0]
GUID = "4c4c4544-0042-3510-8052-b4c04f4e3332"
GUID2 = "9f1b2c3d-1111-2222-3333-444455556666"
RAND = "ab" * 32
RAND2 = "0123456789abcdef" * 4


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def p(name):
    return os.path.join(TMP, name)


def clock():
    return T[0]


def raises(fn, code):
    """fn 이 EnrollError(code) 를 내면 참."""
    try:
        fn()
    except pc_registry.EnrollError as e:
        return e.code == code
    except Exception:
        return False
    return False


def raises_value(fn):
    try:
        fn()
    except ValueError:
        return True
    except Exception:
        return False
    return False


def raises_seats(fn):
    try:
        fn()
    except pc_registry.SeatsFull:
        return True
    except Exception:
        return False
    return False


def enroll(reg, s, guid=GUID, host="OFFICE-1", rand=RAND):
    proof = pc_registry.enroll_proof(s["token"], s["pc_id"], rand, guid, host)
    return reg.enroll(s["pc_id"], rand, guid, host, proof)


def test_enroll_once():
    print("등록은 한 번만")
    reg = pc_registry.Registry(p("a.json"), seats=2, clock=clock)
    s = reg.start("1층 PC")
    check("첫 번호는 pc_01", s["pc_id"] == "pc_01" and bool(pc_registry.PC_RE.fullmatch(s["pc_id"])), s)
    check("등록 유효 시각은 지금부터 600초 (ms)", s["expires_at"] == int((T[0] + pc_registry.ENROLL_SEC) * 1000), s["expires_at"])
    rand = "ab" * 32
    proof = pc_registry.enroll_proof(s["token"], "pc_01", rand, GUID, "OFFICE-1")
    keys = reg.enroll("pc_01", rand, GUID, "OFFICE-1", proof)
    check("열쇠는 토큰과 PC 난수로 양쪽이 같게 만든다", keys == pc_registry.derive_keys(s["token"], rand))
    check("열쇠 둘은 서로 다르다", keys[0] != keys[1])
    check("다른 PC 난수면 다른 열쇠", pc_registry.derive_keys(s["token"], RAND2) != keys)
    check("등록되면 active", reg.state("pc_01") == "active")
    check("keys() 가 같은 열쇠", reg.keys("pc_01") == keys)
    check("label() 이 등록 이름", reg.label("pc_01") == "1층 PC")
    check("두 번째 등록은 unknown", raises(lambda: reg.enroll("pc_01", rand, GUID, "OFFICE-1", proof), "unknown"))
    check("없는 번호 등록은 unknown", raises(lambda: reg.enroll("pc_09", rand, GUID, "OFFICE-1", proof), "unknown"))
    text = open(p("a.json"), encoding="utf-8").read()
    check("파일에 토큰이 없다", s["token"] not in text)
    data = json.loads(text)
    rec = data["pcs"]["pc_01"]
    check("파일 꼴 v·next·pcs", data["v"] == 1 and data["next"] == 2 and set(data["pcs"]) == {"pc_01"}, data)
    check("기록 칸", {"label", "guid", "host", "agent_key", "relay_key", "state", "created_at", "enrolled_at"} <= set(rec)
          and rec["state"] == "active" and rec["guid"] == GUID and rec["host"] == "OFFICE-1", rec)
    check("이름이 비면 ValueError", raises_value(lambda: reg.start("   ")))
    check("이름이 40자 넘으면 ValueError", raises_value(lambda: reg.start("가" * (pc_registry.LABEL_MAX + 1))))
    check("이름에 줄바꿈이면 ValueError", raises_value(lambda: reg.start("1층\nPC")))
    check("이름이 글이 아니면 ValueError", raises_value(lambda: reg.start(None)))
    check("틀린 이름은 번호를 쓰지 않는다", reg.start("2층 PC")["pc_id"] == "pc_02")


def test_expired_and_bad_proof():
    print("10분 지남·증명 틀림")
    reg = pc_registry.Registry(p("b.json"), seats=5, clock=clock)
    s = reg.start("만료 PC")
    T[0] += pc_registry.ENROLL_SEC - 1
    check("599초에는 대기 중", any(x["pcId"] == s["pc_id"] and x["state"] == "pending" for x in reg.list()))
    T[0] += 1
    check("600초 지나면 expired", raises(lambda: enroll(reg, s), "expired"))
    check("만료된 대기는 지워져 다음은 unknown", raises(lambda: enroll(reg, s), "unknown"))
    check("만료된 대기는 자리를 쓰지 않는다", reg.used() == 0)

    s = reg.start("증명 PC")
    bad =pc_registry.enroll_proof("x" * 43, s["pc_id"], RAND, GUID, "OFFICE-1")
    # 틀린 증명은 세기만 하고 대기를 취소하지 않는다 (검토 I-3 - PC 번호만 아는 누구나 남의 등록을 막지 못하게)
    check("틀린 증명 10번 모두 bad_proof", all(raises(lambda: reg.enroll(s["pc_id"], RAND, GUID2, "OFFICE-1", bad), "bad_proof")
                                          for _ in range(10)))
    check("10번 틀려도 아직 대기 중", any(x["pcId"] == s["pc_id"] and x["state"] == "pending" for x in reg.list()))
    check("10번 틀린 뒤에도 맞는 증명이면 등록된다",
          reg.enroll(s["pc_id"], RAND, GUID2, "OFFICE-1", pc_registry.enroll_proof(s["token"], s["pc_id"], RAND, GUID2, "OFFICE-1"))
          == pc_registry.derive_keys(s["token"], RAND))

    s = reg.start("꼴 PC")
    tok = s["token"]

    def try_with(rand, guid, host, proof=None):
        return lambda: reg.enroll(s["pc_id"], rand, guid, host,
                                  proof if proof is not None else pc_registry.enroll_proof(tok, s["pc_id"], rand, guid, host))
    check("PC 난수 대문자 hex 는 bad_proof", raises(try_with("AB" * 32, GUID, "OFFICE-1"), "bad_proof"))
    check("PC 난수 길이 틀림은 bad_proof", raises(try_with("ab" * 31, GUID, "OFFICE-1"), "bad_proof"))
    check("GUID 꼴 틀림은 bad_proof", raises(try_with(RAND, "not-a-guid", "OFFICE-1"), "bad_proof"))
    check("컴퓨터 이름 64자는 bad_proof", raises(try_with(RAND, GUID, "H" * 64), "bad_proof"))
    check("꼴이 틀린 것도 같은 셈 - 5번째(한글 증명)에도 취소하지 않는다",
          raises(try_with(RAND, GUID, "OFFICE-1", proof="가나다"), "bad_proof")
          and any(x["pcId"] == s["pc_id"] and x["state"] == "pending" for x in reg.list()))
    reg.cancel(s["pc_id"])

    s = reg.start("글 아닌 증명 PC")
    tok = s["token"]
    check("증명이 글이 아니면 bad_proof", raises(try_with(RAND, GUID, "OFFICE-1", proof=12345), "bad_proof"))
    check("컴퓨터 이름이 비면 bad_proof", raises(try_with(RAND, GUID, ""), "bad_proof"))
    check("컴퓨터 이름에 제어 글자면 bad_proof", raises(try_with(RAND, GUID, "A\tB"), "bad_proof"))
    check("그래도 맞는 증명이면 등록된다", isinstance(reg.enroll(s["pc_id"], RAND, GUID, "OFFICE-1",
                                                           pc_registry.enroll_proof(tok, s["pc_id"], RAND, GUID, "OFFICE-1")), tuple))

    s = reg.start("취소 PC")
    check("cancel 은 대기를 지운다", reg.cancel(s["pc_id"]) is True and raises(lambda: enroll(reg, s), "unknown"))
    check("없는 대기 cancel 은 False", reg.cancel(s["pc_id"]) is False)


def test_seats():
    print("자리 수")
    reg = pc_registry.Registry(p("c.json"), seats=2, clock=clock)
    a = reg.start("가")
    b = reg.start("나")
    check("대기 둘이면 used 2", reg.used() == 2)
    check("seats=2 에서 세 번째 start 는 SeatsFull", raises_seats(lambda: reg.start("다")))
    check("대기 하나 remove", reg.remove(a["pc_id"]) is True)
    c = reg.start("다")
    check("remove 하면 다시 start 가능", c["pc_id"] == "pc_03", c)
    enroll(reg, c)
    check("등록한 PC 도 자리를 쓴다", reg.used() == 2 and raises_seats(lambda: reg.start("라")))
    reg.disable(c["pc_id"], True)
    check("사용 중지한 PC 도 자리를 쓴다", reg.used() == 2 and raises_seats(lambda: reg.start("라")))
    reg.remove(c["pc_id"])
    d = reg.start("라")
    check("등록한 PC 를 지우면 자리를 돌려준다", d["pc_id"] == "pc_04" and reg.used() == 2, d)
    T[0] += pc_registry.ENROLL_SEC
    check("만료된 대기는 자리를 돌려준다", reg.used() == 0)
    reg3 = pc_registry.Registry(p("c3.json"), seats=2, clock=clock)
    g = reg3.start("사")
    h = reg3.start("아")
    enroll(reg3, g, guid=GUID)
    reg3.seats = 1
    check("등록 때 자리가 없으면 seats", raises(lambda: enroll(reg3, h, guid=GUID2), "seats"))


def test_duplicate_guid():
    print("같은 윈도우 PC 번호")
    reg = pc_registry.Registry(p("d.json"), seats=5, clock=clock)
    a = reg.start("가")
    enroll(reg, a, guid=GUID)
    b = reg.start("나")
    check("같은 GUID 로 두 번째 PC 등록 → duplicate", raises(lambda: enroll(reg, b, guid=GUID), "duplicate"))
    check("대소문자만 다른 같은 GUID 도 duplicate", raises(lambda: enroll(reg, b, guid=GUID.upper()), "duplicate"))
    reg.disable(a["pc_id"], True)
    check("사용 중지한 PC 의 GUID 도 duplicate", raises(lambda: enroll(reg, b, guid=GUID), "duplicate"))
    reg.remove(a["pc_id"])
    check("지운 PC 의 GUID 로는 등록할 수 있다", enroll(reg, b, guid=GUID) == reg.keys(b["pc_id"]) and reg.state(b["pc_id"]) == "active")


def test_numbers_not_reused():
    print("번호는 다시 쓰지 않는다")
    reg = pc_registry.Registry(p("e.json"), seats=5, clock=clock)
    a = reg.start("가")
    b = reg.start("나")
    enroll(reg, a)
    reg.remove(a["pc_id"])
    c = reg.start("다")
    check("pc_01 remove 뒤 새 start 는 pc_03 (pc_02 가 대기)", c["pc_id"] == "pc_03" and b["pc_id"] == "pc_02", (b, c))
    reg.cancel(c["pc_id"])
    d = reg.start("라")
    check("취소한 대기 번호도 다시 쓰지 않는다", d["pc_id"] == "pc_04", d)
    reg2 = pc_registry.Registry(p("e.json"), seats=5, clock=clock)
    e = reg2.start("마")
    check("다시 읽어도 pc_05 (대기만 했던 번호도 건너뜀)", e["pc_id"] == "pc_05", e)
    check("어떤 경우에도 pc_01 이 아니다", "pc_01" not in {c["pc_id"], d["pc_id"], e["pc_id"]})


def test_list_has_no_secrets():
    print("목록에 비밀 없음")
    reg = pc_registry.Registry(p("f.json"), seats=5, clock=clock)
    a = reg.start("가")
    ka = enroll(reg, a, guid=GUID)
    b = reg.start("나")
    c = reg.start("다")
    kc = enroll(reg, c, guid=GUID2, rand=RAND2)
    reg.remove(c["pc_id"])
    reg.seen(a["pc_id"])
    rows = reg.list()
    text = json.dumps(rows, ensure_ascii=False)
    secrets_ = [ka[0], ka[1], kc[0], kc[1], a["token"], b["token"], c["token"], GUID, GUID2]
    check("list() 의 어떤 칸에도 열쇠·토큰·guid 글이 없다", not any(x in text for x in secrets_), text)
    check("removed 는 빠진다", [r["pcId"] for r in rows] == [a["pc_id"], b["pc_id"]], rows)
    keys = {"pcId", "label", "host", "state", "enrolledAt", "expiresAt", "lastSeen"}
    check("칸은 pcId·label·host·state·enrolledAt·expiresAt·lastSeen", all(set(r) == keys for r in rows), rows)
    ra, rb = rows
    check("등록한 PC 는 active·컴퓨터 이름·등록 시각·마지막 연결", ra["state"] == "active" and ra["host"] == "OFFICE-1"
          and ra["enrolledAt"] == int(T[0] * 1000) and ra["lastSeen"] == int(T[0] * 1000) and ra["expiresAt"] is None, ra)
    check("대기는 pending·만료 시각", rb["state"] == "pending" and rb["expiresAt"] == b["expires_at"] and rb["enrolledAt"] is None
          and rb["label"] == "나", rb)


def test_disable_remove_keys():
    print("사용 중지·지우기와 열쇠")
    reg = pc_registry.Registry(p("g.json"), seats=5, clock=clock)
    a = reg.start("가")
    keys = enroll(reg, a)
    n = reg.used()
    check("disable → state disabled", reg.disable(a["pc_id"], True) is True and reg.state(a["pc_id"]) == "disabled")
    check("disabled 도 keys 그대로", reg.keys(a["pc_id"]) == keys)
    check("목록에 disabled", reg.list()[0]["state"] == "disabled")
    check("disable(False) → 다시 active", reg.disable(a["pc_id"], False) is True and reg.state(a["pc_id"]) == "active")
    check("rename", reg.rename(a["pc_id"], "  새 이름 ") is True and reg.label(a["pc_id"]) == "새 이름")
    check("rename 틀린 이름은 ValueError", raises_value(lambda: reg.rename(a["pc_id"], "")))
    check("없는 PC 는 rename·disable False", reg.rename("pc_77", "x") is False and reg.disable("pc_77", True) is False)
    check("remove → True", reg.remove(a["pc_id"]) is True)
    check("remove → state removed", reg.state(a["pc_id"]) == "removed")
    check("removed 도 keys 그대로 ('지워짐' 답에 서명)", reg.keys(a["pc_id"]) == keys)
    check("used() 가 하나 준다", reg.used() == n - 1)
    rec = json.load(open(p("g.json"), encoding="utf-8"))["pcs"][a["pc_id"]]
    check("파일에 removed_at", rec["state"] == "removed" and rec.get("removed_at") == int(T[0] * 1000), rec)
    check("지운 PC 는 다시 disable·rename·remove 못 한다", reg.disable(a["pc_id"], True) is False
          and reg.rename(a["pc_id"], "x") is False and reg.remove(a["pc_id"]) is False)
    check("모르는 번호는 state·keys·label None", reg.state("pc_99") is None and reg.keys("pc_99") is None and reg.label("pc_99") is None)
    check("대기 번호의 state·keys 는 None", (lambda s: reg.state(s["pc_id"]) is None and reg.keys(s["pc_id"]) is None)(reg.start("대기")))


def test_removed_keys_purged_after_3_days():
    print("지운 PC 의 열쇠는 3일 뒤에 지운다 (사용자 2026-11-24)")
    T[0] = 1795100000.0
    reg = pc_registry.Registry(p("purge.json"), seats=5, clock=clock)
    a = reg.start("가")
    keys = enroll(reg, a)
    b = reg.start("나")
    enroll(reg, b, guid=GUID2)
    reg.remove(a["pc_id"])
    check("3일 상수", pc_registry.REMOVED_KEEP_MS == 3 * 24 * 3600 * 1000)
    T[0] += 3 * 24 * 3600 - 1
    check("3일 안에는 열쇠가 있다 ('지워짐' 답에 서명)", reg.keys(a["pc_id"]) == keys)
    T[0] += 2
    check("3일이 지나면 keys None", reg.keys(a["pc_id"]) is None)
    check("state 는 removed 그대로", reg.state(a["pc_id"]) == "removed")
    text = open(p("purge.json"), encoding="utf-8").read()
    check("파일에서도 열쇠가 지워졌다", keys[0] not in text and keys[1] not in text)
    rec = json.loads(text)["pcs"][a["pc_id"]]
    check("번호·이름·지운 시각은 남는다", rec["label"] == "가" and rec["state"] == "removed" and isinstance(rec.get("removed_at"), int), rec)
    check("다른 PC 는 그대로", reg.state(b["pc_id"]) == "active" and reg.keys(b["pc_id"]) is not None)
    reg2 = pc_registry.Registry(p("purge.json"), seats=5, clock=clock)
    check("다시 읽어도 지운 PC 기록이 남고 번호를 다시 쓰지 않는다", reg2.state(a["pc_id"]) == "removed" and reg2.keys(a["pc_id"]) is None
          and reg2.start("다")["pc_id"] == "pc_03")
    # 서버가 꺼져 있다 켜진 경우 - 읽을 때 지난 것을 지운다
    T[0] = 1795200000.0
    reg3 = pc_registry.Registry(p("purge2.json"), seats=5, clock=clock)
    c = reg3.start("라")
    k3 = enroll(reg3, c)
    reg3.remove(c["pc_id"])
    T[0] += 4 * 24 * 3600
    pc_registry.Registry(p("purge2.json"), seats=5, clock=clock)
    check("켤 때 3일 지난 열쇠를 파일에서 지운다", k3[0] not in open(p("purge2.json"), encoding="utf-8").read())


def test_enrollment_text_roundtrip():
    print("등록 글 한 줄")
    info = {"v": 1, "url": "http://127.0.0.1:8781", "pc": "pc_01", "token": "t" * 43, "exp": 1}
    t = pc_registry.encode_enrollment(info)
    check("APE1. 로 시작하고 한 줄", t.startswith("APE1.") and "\n" not in t)
    check("다시 풀면 같다", pc_registry.decode_enrollment("  " + t + "\n") == info)
    check("꼴이 틀리면 ValueError", raises_value(lambda: pc_registry.decode_enrollment("APE1.@@@")))
    check("머리가 다르면 ValueError", raises_value(lambda: pc_registry.decode_enrollment(t.replace("APE1.", "APE2.", 1))))
    check("빈 글이면 ValueError", raises_value(lambda: pc_registry.decode_enrollment("")))
    check("글이 아니면 ValueError", raises_value(lambda: pc_registry.decode_enrollment(None)))
    no_tok = {k: v for k, v in info.items() if k != "token"}
    check("칸이 빠지면 ValueError", raises_value(lambda: pc_registry.decode_enrollment(pc_registry.encode_enrollment(no_tok))))
    check("v 가 1 이 아니면 ValueError", raises_value(lambda: pc_registry.decode_enrollment(pc_registry.encode_enrollment(dict(info, v=2)))))
    check("JSON 목록이면 ValueError", raises_value(lambda: pc_registry.decode_enrollment("APE1.WzFd")))   # "[1]"
    check("JSON 이 아니면 ValueError", raises_value(lambda: pc_registry.decode_enrollment("APE1.YWJj")))  # "abc"


def _raw_text(info):
    """encode_enrollment 의 검사를 거치지 않은 등록 글 (decode 쪽 검사를 따로 본다)."""
    raw = json.dumps(info, separators=(",", ":")).encode("utf-8")
    return "APE1." + base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def test_enrollment_ca_field():
    print("등록 글의 인증 기관 칸 ca (사내 서버 ② Task 4)")
    pem = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"
    info = {"v": 1, "url": "https://192.168.1.230:8444", "pc": "pc_01", "token": "t" * 43, "exp": 1, "ca": pem}
    t = pc_registry.encode_enrollment(info)
    check("https + ca 는 다시 풀면 같다", pc_registry.decode_enrollment(t) == info)
    no_ca = {k: v for k, v in info.items() if k != "ca"}
    check("https 인데 ca 가 없으면 만들 때 ValueError", raises_value(lambda: pc_registry.encode_enrollment(no_ca)))
    check("https 인데 ca 가 없으면 풀 때 ValueError", raises_value(lambda: pc_registry.decode_enrollment(_raw_text(no_ca))))
    check("HTTPS 대문자도 https 로 본다", raises_value(lambda: pc_registry.decode_enrollment(_raw_text(dict(no_ca, url="HTTPS://10.0.0.5:8444")))))
    for bad in ("", 5, None, "인증서 아님"):
        check(f"ca 가 인증서 글이 아니면 ValueError ({bad!r})",
              raises_value(lambda: pc_registry.decode_enrollment(_raw_text(dict(info, ca=bad)))))
    http = {"v": 1, "url": "http://127.0.0.1:8781", "pc": "pc_01", "token": "t" * 43, "exp": 1}
    check("http 는 ca 없이 된다 (① 그대로)", pc_registry.decode_enrollment(pc_registry.encode_enrollment(http)) == http)
    check("http 에 ca 가 있어도 된다", pc_registry.decode_enrollment(pc_registry.encode_enrollment(dict(http, ca=pem)))["ca"] == pem)


def test_reload_keeps_pcs():
    print("다시 읽기")
    reg = pc_registry.Registry(p("h.json"), seats=5, clock=clock)
    a = reg.start("가")
    keys = enroll(reg, a)
    b = reg.start("나")
    reg2 = pc_registry.Registry(p("h.json"), seats=5, clock=clock)
    check("새 Registry 로 같은 파일을 읽으면 active PC 가 남는다", reg2.state(a["pc_id"]) == "active" and reg2.keys(a["pc_id"]) == keys)
    check("대기는 없다", [r["pcId"] for r in reg2.list()] == [a["pc_id"]] and raises(lambda: enroll(reg2, b), "unknown"))
    check("next 가 남는다", reg2.start("다")["pc_id"] == "pc_03")

    with open(p("broken.json"), "w", encoding="utf-8") as f:
        f.write("{깨진 파일")
    reg3 = pc_registry.Registry(p("broken.json"), seats=5, clock=clock)
    check("깨진 파일은 .broken 으로 옮기고 빈 등록부", os.path.exists(p("broken.json.broken")) and reg3.list() == [] and reg3.used() == 0)
    check("빈 등록부의 첫 번호는 pc_01", reg3.start("가")["pc_id"] == "pc_01")
    with open(p("odd.json"), "w", encoding="utf-8") as f:
        json.dump({"v": 1, "next": 2, "pcs": {"pc_05": {"label": "x", "agent_key": "a", "relay_key": "r", "state": "active"},
                                              "nope": {"agent_key": "a", "relay_key": "r"}}}, f)
    reg4 = pc_registry.Registry(p("odd.json"), seats=9, clock=clock)
    check("꼴이 틀린 번호는 버리고 next 는 있는 번호보다 크게", reg4.state("nope") is None and reg4.start("y")["pc_id"] == "pc_06")
    leftovers = [n for n in os.listdir(TMP) if n.endswith(".tmp")]
    check("임시 파일이 남지 않는다", not leftovers, leftovers)


try:
    test_enroll_once()
    test_expired_and_bad_proof()
    test_seats()
    test_duplicate_guid()
    test_numbers_not_reused()
    test_list_has_no_secrets()
    test_disable_remove_keys()
    test_removed_keys_purged_after_3_days()
    test_enrollment_text_roundtrip()
    test_enrollment_ca_field()
    test_reload_keeps_pcs()
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n실패 {len(fails)}건" + (": " + ", ".join(fails) if fails else ""))
sys.exit(1 if fails else 0)
