# -*- coding: utf-8 -*-
"""사내 서버 ③ Task 2 - 계정 파일 버전 2 (계획 2026-11-25-lan-3-web-auth).
버전 1 파일 읽기·버전 2 로 쓰기, 2단계 칸(비밀 값·마지막 칸·복구 번호 해시·켠 시각), 비밀번호를 바꿔도 2단계가 남는지,
사내 서버 관리자 비밀번호 10자. 포트는 열지 않는다. 시계는 가짜 값.
    D:/AX/RPA/.venv/Scripts/python.exe tests/test_accounts_v2.py
"""
import json
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
import local_web  # noqa: E402
import totp  # noqa: E402

fails = []
TMP = tempfile.mkdtemp(prefix="rpa_accounts_v2_")
NOW = 1795000005.0


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def fresh(name):
    """새 폴더의 Accounts."""
    folder = os.path.join(TMP, name)
    os.makedirs(folder, exist_ok=True)
    return local_web.Accounts(os.path.join(folder, local_web.ACCOUNTS_NAME))


def raw(acc):
    with open(acc.path, encoding="utf-8") as f:
        return json.load(f)


def raises(fn, cls):
    try:
        fn()
    except cls:
        return True
    except Exception:
        return False
    return False


def enabled(acc, uid, now=NOW):
    """2단계를 켠다 → (비밀 값, 복구 번호 글 목록)."""
    s = totp.new_secret()
    codes = acc.mfa_enable(uid, s, totp.code_at(s, totp.step_of(now)), now)
    return s, codes


def test_v1_reads_v2_writes():
    print("test_v1_reads_v2_writes")
    acc = fresh("v1")
    rec_a = local_web.Accounts._record("boss-pw-12345", "admin", False, False)
    rec_b = local_web.Accounts._record("staff-pw-0001", "viewer", False, True)
    with open(acc.path, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "accounts": {"boss": rec_a, "staff": rec_b}}, f)
    got = acc.list()
    check("버전 1 파일의 계정 둘", [a["id"] for a in got] == ["boss", "staff"], repr(got))
    check("버전 1 계정 mfa 꺼짐", all(a["mfa"] is False for a in got), repr(got))
    check("버전 1 비밀번호 그대로", acc.verify("boss", "boss-pw-12345") is not None)
    acc.disable("staff", True)
    data = raw(acc)
    check("저장하면 version 2", data.get("version") == 2, repr(data.get("version")))
    check("boss 칸 그대로", data["accounts"]["boss"] == rec_a, repr(data["accounts"]["boss"]))
    check("staff 칸 그대로 (중지만 바뀜)", data["accounts"]["staff"] == dict(rec_b, disabled=True), repr(data["accounts"]["staff"]))
    # 버전 2 파일을 다른 Accounts 가 그대로 읽는다
    check("버전 2 다시 읽기", [a["id"] for a in local_web.Accounts(acc.path).list()] == ["boss", "staff"])


def test_mfa_enable_and_check():
    print("test_mfa_enable_and_check")
    acc = fresh("enable")
    acc.set("boss", "boss-pw-12345", "admin")
    acc.set("staff", "staff-pw-0001", "viewer")
    check("켜기 전 mfa 거짓", acc.get("boss")["mfa"] is False and acc.mfa_secret("boss") is None)
    check("켜기 전 mfa_info", acc.mfa_info("boss") == {"enabled": False, "enabled_at": None, "recovery_left": 0},
          repr(acc.mfa_info("boss")))
    s = totp.new_secret()
    step = totp.step_of(NOW)
    bad = "000000" if totp.code_at(s, step) != "000000" else "111111"
    check("틀린 번호로 켜기 → None", acc.mfa_enable("boss", s, bad, NOW) is None and acc.get("boss")["mfa"] is False)
    check("없는 계정 켜기 → NoAccount",
          raises(lambda: acc.mfa_enable("nobody", s, totp.code_at(s, step), NOW), local_web.NoAccount))
    codes = acc.mfa_enable("boss", s, totp.code_at(s, step), NOW)
    check("켜기 → 복구 번호 8개", isinstance(codes, list) and len(codes) == 8, repr(codes))
    text = open(acc.path, encoding="utf-8").read()
    check("파일에 복구 번호 글이 없다", not any(c in text or c.replace("-", "") in text for c in codes or []))
    m = raw(acc)["accounts"]["boss"].get("mfa") or {}
    check("파일에 해시 8개", isinstance(m.get("recovery"), list) and len(m["recovery"]) == 8
          and all(isinstance(x, str) and len(x) == 64 for x in m["recovery"]), repr(m.get("recovery")))
    check("파일 칸: secret·last_step·salt·enabled_at", m.get("secret") == s and m.get("last_step") == step
          and isinstance(m.get("salt"), str) and m.get("enabled_at") == int(NOW * 1000), repr({k: m.get(k) for k in ("last_step", "enabled_at")}))
    check("같은 번호 다시 → False (쓴 칸)", acc.mfa_check("boss", totp.code_at(s, step), NOW) is False)
    check("다음 칸 번호 → True", acc.mfa_check("boss", totp.code_at(s, step + 1), NOW + 30) is True)
    check("그 번호 다시 → False", acc.mfa_check("boss", totp.code_at(s, step + 1), NOW + 30) is False)
    check("틀린 번호 → False", acc.mfa_check("boss", bad, NOW + 60) is False)
    check("2단계 없는 계정 mfa_check → False", acc.mfa_check("staff", totp.code_at(s, step + 2), NOW + 60) is False)
    check("없는 계정 mfa_check → False", acc.mfa_check("nobody", "123456", NOW) is False)
    check("get mfa 참", acc.get("boss")["mfa"] is True and acc.get("staff")["mfa"] is False)
    check("verify 에도 mfa", (acc.verify("boss", "boss-pw-12345") or {}).get("mfa") is True)
    check("mfa_secret 은 그 비밀 값", acc.mfa_secret("boss") == s)
    lst = acc.list()
    check("list 에 secret·recovery·salt·hash 키 없음",
          all(not ({"secret", "recovery", "salt", "hash", "last_step"} & set(a)) for a in lst), repr(lst))
    check("list 의 mfa 칸 bool", [a["mfa"] for a in lst] == [True, False], repr(lst))
    check("get 에 비밀 값 없음", s not in json.dumps(acc.get("boss")))
    info = acc.mfa_info("boss")
    check("mfa_info", info == {"enabled": True, "enabled_at": int(NOW * 1000), "recovery_left": 8}, repr(info))
    check("rev 는 2단계로 안 바뀜", acc.get("boss")["rev"] == local_web.Accounts._public(
        "boss", raw(acc)["accounts"]["boss"], rev=True)["rev"])


def test_recovery_once():
    print("test_recovery_once")
    acc = fresh("recovery")
    acc.set("boss", "boss-pw-12345", "admin")
    _, codes = enabled(acc, "boss")
    check("첫 복구 번호 → 7", acc.mfa_use_recovery("boss", codes[0]) == 7)
    check("같은 것 다시 → None", acc.mfa_use_recovery("boss", codes[0]) is None)
    check("대문자·- 없이 다른 것 → 6", acc.mfa_use_recovery("boss", codes[1].replace("-", "").upper()) == 6)
    check("모르는 번호 → None", acc.mfa_use_recovery("boss", "aaaaa-aaaaa") is None)
    check("꼴이 틀린 글 → None", acc.mfa_use_recovery("boss", "abc") is None and acc.mfa_use_recovery("boss", None) is None)
    check("2단계 없는 계정 → None", acc.mfa_use_recovery("nobody", codes[2]) is None)
    check("mfa_info 남은 수 6", acc.mfa_info("boss")["recovery_left"] == 6)


def test_mfa_survives_writes():
    print("test_mfa_survives_writes")
    acc = fresh("survive")
    acc.set("boss", "boss-pw-12345", "admin")
    acc.set("boss2", "boss2-pw-1234", "admin")      # 마지막 관리자 막기에 걸리지 않게 하나 더
    s, _ = enabled(acc, "boss")
    rev0 = acc.get("boss")["rev"]
    steps = (
        ("change_password", lambda: acc.change_password("boss", "boss-pw-12345", "boss-pw-67890")),
        ("set (관리자가 다시 정함)", lambda: acc.set("boss", "boss-pw-reset-1", "admin", must_change=True)),
        ("disable 중지", lambda: acc.disable("boss", True)),
        ("disable 다시 사용", lambda: acc.disable("boss", False)),
    )
    for name, fn in steps:
        fn()
        check(f"{name} 뒤 enabled", acc.mfa_info("boss")["enabled"] is True, repr(acc.mfa_info("boss")))
        check(f"{name} 뒤 같은 비밀 값", acc.mfa_secret("boss") == s)
    check("복구 번호도 그대로 8", acc.mfa_info("boss")["recovery_left"] == 8)
    check("비밀번호는 바뀌었다 (rev 다름)", acc.get("boss")["rev"] != rev0)
    check("must_change 는 set 대로", acc.get("boss")["must_change"] is True)
    # 쓴 칸 기록도 남는다 - 켤 때 쓴 번호는 비밀번호를 바꾼 뒤에도 다시 받지 않는다
    check("쓴 칸 기록도 남음", acc.mfa_check("boss", totp.code_at(s, totp.step_of(NOW)), NOW) is False)


def test_admin_min():
    print("test_admin_min")
    lan = fresh("admin_min_lan")
    check("기본 admin_min 8", fresh("admin_min_default").admin_min == local_web.PASSWORD_MIN == 8)
    lan.admin_min = 10
    try:
        lan.add("boss", "9chars-pw", "admin")
        got = None
    except local_web.WeakPassword as e:
        got = str(e)
    except Exception as e:  # noqa: BLE001
        got = repr(e)
    check("관리자 9자 → WeakPassword (관리자 10자 글)", got == "관리자 비밀번호는 10자 이상으로 입력하여 주십시오.", repr(got))
    check("관리자 10자 됨", lan.add("boss", "10chars-pw", "admin") == "boss")
    check("유저 8자 됨", lan.add("staff", "8chars-p", "viewer") == "staff")
    check("유저 7자 → WeakPassword (8자 글)", raises(lambda: lan.add("staff2", "7chars-", "viewer"), local_web.WeakPassword))
    check("set 관리자 9자 → WeakPassword", raises(lambda: lan.set("boss", "9chars-pw", "admin"), local_web.WeakPassword))
    check("유저를 관리자로 올리며 9자 → WeakPassword", raises(lambda: lan.set("staff", "9chars-pw", "admin"), local_web.WeakPassword))
    check("관리자 change_password 9자 → WeakPassword",
          raises(lambda: lan.change_password("boss", "10chars-pw", "9chars-pw"), local_web.WeakPassword))
    check("그대로 로그인 됨", lan.verify("boss", "10chars-pw") is not None)
    check("유저 change_password 8자 됨", lan.change_password("staff", "8chars-p", "8chars-q")["id"] == "staff")
    single = fresh("admin_min_single")
    check("기본(8) 관리자 8자 됨 (단독 그대로)", single.add("boss", "8chars-p", "admin") == "boss")
    try:
        single.add("boss2", "7chars-", "admin")
        msg = None
    except local_web.WeakPassword as e:
        msg = str(e)
    check("단독 관리자 7자 글 그대로", msg == "비밀번호는 8자 이상으로 입력하여 주십시오.", repr(msg))


def test_clear():
    print("test_clear")
    acc = fresh("clear")
    acc.set("boss", "boss-pw-12345", "admin")
    enabled(acc, "boss")
    check("mfa_clear → True", acc.mfa_clear("boss") is True)
    check("다시 → False", acc.mfa_clear("boss") is False)
    check("mfa_info enabled False", acc.mfa_info("boss")["enabled"] is False and acc.get("boss")["mfa"] is False)
    check("파일에 mfa 칸 없음", "mfa" not in raw(acc)["accounts"]["boss"])
    check("비밀번호 그대로", acc.verify("boss", "boss-pw-12345") is not None)


def test_lan_web_admin_min():
    print("test_lan_web_admin_min")
    check("상수 LAN_ADMIN_PASSWORD_MIN 10", getattr(local_web, "LAN_ADMIN_PASSWORD_MIN", None) == 10)
    folder = os.path.join(TMP, "web_single")
    os.makedirs(folder, exist_ok=True)
    web = local_web.Web(None, None, {"cid": "c_test"}, folder, None)
    check("단독 Web 관리자 최소 8", web.accounts.admin_min == 8)
    folder2 = os.path.join(TMP, "web_lan")
    os.makedirs(folder2, exist_ok=True)
    web2 = local_web.Web(None, None, {"cid": "c_test"}, folder2, None, registry=object())
    check("사내 서버 Web 관리자 최소 10", web2.accounts.admin_min == 10)


def main():
    try:
        for fn in (test_v1_reads_v2_writes, test_mfa_enable_and_check, test_recovery_once, test_mfa_survives_writes,
                   test_admin_min, test_clear, test_lan_web_admin_min):
            try:
                fn()
            except Exception as e:  # noqa: BLE001
                check(f"{fn.__name__} 예외", False, repr(e))
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print(f"실패: {len(fails)}")
    if fails:
        for n in fails:
            print("  -", n)
        sys.exit(1)


if __name__ == "__main__":
    main()
