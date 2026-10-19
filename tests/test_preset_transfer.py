"""프리셋 파일·넣기·되돌리기 시험 (preset_transfer) - 설계 2026-10-19 4.4·6절. 창은 뜨지 않는다.

실제 설정은 건드리지 않는다. RPA_USER_CONFIG·RPA_PROGRAMDATA·RPA_STATUS_DIR 를 임시 폴더로.
    .venv\\Scripts\\python.exe tests\\test_preset_transfer.py
"""
import copy
import json
import os
import sys
import tempfile
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="rpa_ptransfer_")
os.environ["RPA_USER_CONFIG"] = os.path.join(TMP, "config", "RPA_UserConfig.json")
os.environ["RPA_PROGRAMDATA"] = os.path.join(TMP, "programdata")
os.environ["RPA_STATUS_DIR"] = os.path.join(TMP, "status")
os.environ["RPA_OBSERVER_LOCK"] = rf"Local\AFTER_MARKET_RPA_OBSERVER_PTRANSFER_TEST_{os.getpid()}"
os.makedirs(os.path.join(TMP, "config"))
os.makedirs(os.path.join(TMP, "programdata", "config"))
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

import rpa_status as st  # noqa: E402
import web_replay  # noqa: E402
import preset_transfer as pt  # noqa: E402

fails = []
_no = [0]


def check(name, cond, detail=""):
    _no[0] += 1
    print(f"  {_no[0]:2d}. [{'통과' if cond else '실패'}] {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(f"{_no[0]}. {name} {detail}")


def raises(exc, fn, *args, **kw):
    try:
        fn(*args, **kw)
        return None
    except exc as e:
        return e


def step(kind, **extra):
    return {"kind": kind, "page": 0, "frame": [], "url": "/login", "gap": 0, **extra}


PW = "비밀번호-유출금지"
REC = {"version": web_replay.RECORD_VERSION, "start_url": "https://shop.example.com/login", "record_date": "2026-09-30",
       "steps": [step("goto", url="/login", href="https://shop.example.com/login"), step("fill", credential="ID"),
                 step("secret", credential="PW")]}
REC2 = dict(REC, start_url="https://other.example.com/", steps=REC["steps"][:1])
SITE1 = {"URL": REC["start_url"], "ID": "seller01", "PW": st.seal(PW), "Action": ["replay"], "Stts": 0, "Preset": 1,
         "note": "지마켓", "Phone": "kim", "SmsSenders": ["15881234"]}
st.write_user_config({"LogIn": {"ID": "erp", "PW": "erp-pw"}, "Sites": {"SITE1": {"URL": "https://mail.example.com", "ID": "m",
                      "PW": "mail-pw", "Action": "login", "Stts": 9}, "PRESET1": dict(SITE1)}})
st.write_presets([{"no": 1, "name": "지마켓", "code": "012", "saved_at": "2026-09-30T18:20:00", "record": REC}, st.blank_preset(2)])
os.makedirs(os.path.dirname(st.mail_memory_path(1)), exist_ok=True)
with open(st.mail_memory_path(1), "w", encoding="utf-8") as f:
    f.write('{"done": ["mail-1"]}')


def mail_memory():
    with open(st.mail_memory_path(1), encoding="utf-8") as f:
        return f.read()


def site(no):
    s = st.read_user_config()["Sites"].get(f"PRESET{no}")
    return s if isinstance(s, dict) else None


print("=== 1. 파일로 내보내기 (export_item) ===")
item = pt.export_item(1, source={"cid": "c_demo", "pcId": "pc_a", "no": 1})
check("키는 kind·version·exported_at·from·no·name·code·record 뿐", set(item) == {"kind", "version", "exported_at", "from", "no", "name", "code", "record"}, str(set(item)))
check("값: kind·version·from·이름·코드·기록", item["kind"] == "autopilot-preset" and item["version"] == 1 and item["from"] == {"cid": "c_demo", "pcId": "pc_a", "no": 1}
      and item["no"] == 1 and item["name"] == "지마켓" and item["code"] == "012" and item["record"] == REC, str(item))
dumped = json.dumps(item, ensure_ascii=False)
check("아이디·비밀번호·휴대폰이 없다", "seller01" not in dumped and PW not in dumped and "dpapi" not in dumped and "kim" not in dumped)
check("source 가 없으면 from 은 {}", pt.export_item(1)["from"] == {})
item_p = pt.export_item(1, with_phone=True)
check("with_phone 이면 phone·senders 가 Sites 값", item_p["phone"] == "kim" and item_p["senders"] == ["15881234"]
      and set(item_p) == {"kind", "version", "exported_at", "from", "no", "name", "code", "record", "phone", "senders"}, str(item_p))
e = raises(ValueError, pt.export_item, 2)
check("빈 칸은 ValueError", e is not None and str(e) == "프리셋 2에 기록이 없습니다.", str(e))

print("=== 2. 파일 검사 (check_file) ===")
good = pt.export_item(1)
check("내보낸 파일은 통과하고 그대로 돌려준다", pt.check_file(copy.deepcopy(good)) == good)
check("with_phone 파일도 통과", pt.check_file(copy.deepcopy(item_p)) == item_p)
bad_cases = {
    "kind 다름": dict(good, kind="other"),
    "version 2": dict(good, version=2),
    "steps 가 dict": dict(good, record=dict(REC, steps={})),
    "기록 모양(version) 다름": dict(good, record=dict(REC, version=web_replay.RECORD_VERSION + 1)),
    "비밀번호 값이 든 secret 단계": dict(good, record=dict(REC, steps=REC["steps"][:2] + [step("secret", credential="PW", value="x")])),
    "credential PW 인 fill 에 값": dict(good, record=dict(REC, steps=[step("fill", credential="PW", value="x")])),
    "PW 키": dict(good, PW="x"),
    "pw 키": dict(good, pw="x"),
    "ID 키": dict(good, ID="x"),
    "id 키": dict(good, id="x"),
    "name 이 문자열 아님": dict(good, name=3),
    "dict 아님": [good],
}
for label, obj in bad_cases.items():
    e = raises(ValueError, pt.check_file, obj)
    check(f"거절: {label}", e is not None and str(e).strip() != "", repr(e))

print("=== 3. 같은 사이트코드로 1번 칸에 넣기 (apply) ===")
new1 = dict(good, name="지마켓 고침", record=dict(REC, steps=REC["steps"] + [step("click", target={"text": "엑셀"})]))
done, rejected = pt.apply([(new1, 1)])
check("넣은 칸 [1], 거절 없음", done == [1] and rejected == [], f"{done} {rejected}")
p1 = st.read_presets()[0]
check("이름·기록이 바뀌고 saved_at 이 새로", p1["name"] == "지마켓 고침" and p1["record"] == new1["record"] and p1["code"] == "012"
      and p1["saved_at"] and p1["saved_at"] != "2026-09-30T18:20:00", str({k: v for k, v in p1.items() if k != "record"}))
s1 = site(1)
check("Sites PRESET1 의 ID·PW·Stts·Phone 은 그대로, note 만 새 이름", s1["ID"] == "seller01" and st.unseal(s1["PW"]) == PW and s1["Stts"] == 0
      and s1["Phone"] == "kim" and s1["SmsSenders"] == ["15881234"] and s1["note"] == "지마켓 고침" and s1["Preset"] == 1, str(s1))
check("다른 섹션·다른 사이트는 그대로", st.read_user_config()["LogIn"]["ID"] == "erp" and st.read_user_config()["Sites"]["SITE1"]["ID"] == "m")
check("backup_path(1) 에 이전 것이 보관된다", os.path.isfile(pt.backup_path(1))
      and pt.backup_path(1) == os.path.join(st.data_dir(), "프리셋보관", "PRESET1.json"), pt.backup_path(1))
with open(pt.backup_path(1), encoding="utf-8") as f:
    bk = json.load(f)
check("보관 내용 = 바꾸기 전 프리셋 + Sites 칸 (봉인된 PW 포함, PC 안)", bk["preset"]["name"] == "지마켓" and bk["preset"]["record"] == REC
      and bk["site"]["ID"] == "seller01" and bk["site"]["PW"] == SITE1["PW"] and PW not in json.dumps(bk), str(bk)[:300])
check("요약에 backup True", st.preset_summary()[0]["backup"] is True and st.preset_summary()[1]["backup"] is False, str(st.preset_summary()))
check("메일 기억은 그대로", mail_memory() == '{"done": ["mail-1"]}')

print("=== 4. 다른 사이트코드로 1번 칸에 넣기 ===")
other = dict(good, name="쿠팡", code="034", record=REC2)
done, rejected = pt.apply([(other, 1)])
check("넣음", done == [1] and rejected == [], f"{done} {rejected}")
s1 = site(1)
check("ID·PW 비움, Stts 9, Phone 없음, URL 은 새 기록 시작 주소", s1["ID"] == "" and s1["PW"] == "" and s1["Stts"] == 9 and "Phone" not in s1
      and "SmsSenders" not in s1 and s1["URL"] == REC2["start_url"] and s1["Action"] == ["replay"] and s1["Preset"] == 1 and s1["note"] == "쿠팡", str(s1))
check("요약 has_login False", st.preset_summary()[0]["has_login"] is False)
with open(pt.backup_path(1), encoding="utf-8") as f:
    bk = json.load(f)
check("보관은 바로 전 것 하나 (지마켓 고침)", bk["preset"]["name"] == "지마켓 고침" and bk["site"]["ID"] == "seller01")

print("=== 5. 되돌리기 (restore) ===")
before_p = copy.deepcopy(bk["preset"])
before_s = copy.deepcopy(bk["site"])
done, rejected = pt.restore([1, 2])
check("1 은 되돌리고 2 는 보관 없음", done == [1] and rejected == [(2, "보관된 이전 기록이 없습니다.")], f"{done} {rejected}")
check("칸 1 기록·Sites 가 바꾸기 전과 같음", st.read_presets()[0] == before_p and site(1) == before_s, str(site(1)))
check("되돌린 뒤 보관은 없어진다 (요약 backup False)", not os.path.isfile(pt.backup_path(1)) and st.preset_summary()[0]["backup"] is False)
check("메일 기억은 그대로", mail_memory() == '{"done": ["mail-1"]}')

print("=== 6. 칸 2개뿐인 PC 의 5번 칸·수를 넘는 칸 ===")
cfg = st.read_settings()
cfg["schedule"]["policy"] = dict(cfg["schedule"].get("policy") or {}, presets=10)
st.write_settings(cfg)
check("preset_limit 10", st.preset_limit() == 10)
five = dict(good, name="옥션", code="056", record=REC2)
eleven = dict(good, name="11번가", code="078", record=REC2)
done, rejected = pt.apply([(five, 5), (eleven, 11)])
check("5 는 성공, 11 은 거절", done == [5] and rejected == [(11, "프리셋 수(10개)를 넘는 칸입니다.")], f"{done} {rejected}")
ps = st.read_presets()
check("3·4 는 빈 칸, 5 에 들어감", [p["no"] for p in ps] == [1, 2, 3, 4, 5] and ps[2]["record"] is None and ps[3]["record"] is None
      and ps[4]["name"] == "옥션" and ps[4]["code"] == "056", str([(p["no"], p["name"]) for p in ps]))
s5 = site(5)
check("새 칸 Sites: ID·PW 비움, Stts 9, Preset 5", s5["ID"] == "" and s5["PW"] == "" and s5["Stts"] == 9 and s5["Preset"] == 5 and s5["note"] == "옥션"
      and site(3) is None and site(4) is None, str(s5))
check("새 칸(기록 없던 칸)은 보관이 없다", not os.path.isfile(pt.backup_path(5)) and not os.path.isfile(pt.backup_path(11)))

print("=== 7. 사이트코드 겹침·파일 검사 거절은 그 칸만 ===")
dup = dict(good, name="지마켓 복제", code="012", record=REC2)      # 1번 칸이 012
ok3 = dict(good, name="네이버", code="090", record=REC2)
done, rejected = pt.apply([(dup, 2), (ok3, 3), (dict(good, PW="x"), 4)])
check("3 만 성공, 2 는 코드 겹침, 4 는 파일 검사", done == [3] and len(rejected) == 2 and rejected[0][0] == 2
      and rejected[0][1] == "프리셋 1와(과) 같은 사이트코드 012를 사용합니다." and rejected[1][0] == 4, f"{done} {rejected}")
ps = st.read_presets()
check("2·4 는 그대로 빈 칸, 3 은 네이버", ps[1]["record"] is None and ps[3]["record"] is None and ps[2]["name"] == "네이버", str([(p["no"], p["name"]) for p in ps]))
check("거절된 칸에 보관이 남지 않는다", not os.path.isfile(pt.backup_path(2)) and not os.path.isfile(pt.backup_path(4)))
done, rejected = pt.apply([(dict(good, code="111", record=REC2), 6), (dict(good, code="111", record=REC2), 7)])
check("한 번에 넣는 두 칸이 같은 코드면 뒤의 것만 거절", done == [6] and rejected == [(7, "프리셋 6와(과) 같은 사이트코드 111를 사용합니다.")], f"{done} {rejected}")
check("프리셋 파일은 여전히 읽힌다 (코드 겹침 없음)", raises(ValueError, st.read_presets) is None)

print("=== 8. 같은 칸에 phone 이 든 파일 (업체 안 복사) ===")
with_phone = dict(good, name="쿠팡", code="034", record=REC2, phone="lee", senders=["0212345678"])
pt.apply([(with_phone, 2)])
s2 = site(2)
check("다른 사이트(빈 칸)인데 파일에 휴대폰이 있으면 그 값을 쓴다", s2["Phone"] == "lee" and s2["SmsSenders"] == ["0212345678"] and s2["ID"] == "" and s2["Stts"] == 9, str(s2))
pt.apply([(dict(with_phone, phone="park", senders=["1"]), 2)])
check("같은 사이트면 받는 PC 에 있던 휴대폰을 둔다", site(2)["Phone"] == "lee", str(site(2)))

print()
print("실패: " + (", ".join(fails) if fails else "없음"))
sys.exit(1 if fails else 0)
