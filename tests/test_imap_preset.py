"""메일 받기(IMAP) 프리셋 - 옵저버 저장 → 사용자 설정 Sites → 프리셋 옮기기 → ACTOR 실행까지 (설계 2026-10-14 14절).
메일 서버는 가짜(tests/fake_imap.py)만 쓴다. 실제 설정은 건드리지 않는다 (RPA_USER_CONFIG·RPA_PROGRAMDATA·RPA_STATUS_DIR 를 임시 폴더로).
    .venv\\Scripts\\python.exe tests\\test_imap_preset.py
"""
import datetime
import email.message
import os
import ssl
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

TMP = tempfile.mkdtemp(prefix="rpa_imap_preset_")
os.environ["RPA_USER_CONFIG"] = os.path.join(TMP, "config", "RPA_UserConfig.json")
os.environ["RPA_PROGRAMDATA"] = os.path.join(TMP, "programdata")
os.environ["RPA_STATUS_DIR"] = os.path.join(TMP, "status")
os.environ["RPA_OBSERVER_LOCK"] = rf"Local\AFTER_MARKET_RPA_OBSERVER_IMAP_TEST_{os.getpid()}"
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(TMP, "no_browsers")
os.makedirs(os.path.join(TMP, "config"))
os.makedirs(os.path.join(TMP, "programdata", "config"))
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.stdout.reconfigure(encoding="utf-8")

import rpa_status as st  # noqa: E402
from fake_imap import PASSWORD, USER, FakeIMAP  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(f"  [{'통과' if cond else '실패'}] {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


st.write_user_config({"LogIn": {"AdminCode": "t", "ID": "erp", "PW": "erp-pw"}, "Routine": {"Login": "Y"}, "Sites": {}})
import mail_imap  # noqa: E402
import preset_transfer as pt  # noqa: E402
import rpa_observer as ob  # noqa: E402
import web_runner as wr  # noqa: E402

srv = FakeIMAP()
NOW = datetime.datetime.now()


def mail(subject, sender="주문팀 <orders@shop.example.com>", files=(("주문.xlsx", b"PK-excel"),)):
    m = email.message.EmailMessage()
    m["From"], m["To"], m["Subject"] = sender, USER, subject
    m["Message-ID"] = f"<{abs(hash((subject, sender)))}@shop.example.com>"
    m.set_content("본문 - 저장하지 않는다")
    for name, data in files:
        m.add_attachment(data, maintype="application", subtype="octet-stream", filename=name)
    return m.as_bytes().replace(b"\n", b"\r\n")


srv.add(mail("[주문] 오늘 주문서"), NOW)
srv.add(mail("[주문] 엑셀 없음", files=()), NOW)
srv.add(mail("광고 메일", sender="ad@spam.example.com"), NOW)

print("=== 1. 기록 안의 imap 단계 (rpa_status.imap_step) ===")
check("imap 단계 하나인 기록만 메일 받기", st.imap_step({"steps": [{"kind": "imap", "host": "h"}]}) == {"kind": "imap", "host": "h"}
      and st.imap_step({"steps": [{"kind": "goto"}]}) is None and st.imap_step(None) is None
      and st.imap_step({"steps": [{"kind": "imap"}, {"kind": "click"}]}) is None)

print("=== 2. 옵저버 칸 ===")
b = ob.blank_imap("someone@naver.com")
check("네이버 주소면 서버를 채운다, 모르는 주소는 비움", (b["host"], b["port"], b["security"]) == ("imap.naver.com", 993, "ssl")
      and ob.blank_imap("a@unknown.example")["host"] == "" and b["rules"] == mail_imap.DEFAULT_RULES)
cfg = {"host": "127.0.0.1", "port": srv.servers[0].server_address[1], "security": "ssl",
       "rules": dict(mail_imap.DEFAULT_RULES, subject_prefix="[주문]")}
r = ob.imap_record(cfg)
check("기록 = imap 단계 하나, 시작 주소 imap://서버", st.imap_step(r) and r["start_url"] == "imap://127.0.0.1" and r["version"] == st.RECORD_VERSION)
check("문제 없음", ob.imap_problem(r["steps"][0]) is None, ob.imap_problem(r["steps"][0]))
check("서버 주소 없음·포트 글자·조건 없음은 문제", ob.imap_problem(dict(r["steps"][0], host=" ")) == "메일 서버 주소를 넣어 주십시오."
      and "포트" in ob.imap_problem(dict(r["steps"][0], port="99x"))
      and "보낸 사람이나 제목" in ob.imap_problem(dict(r["steps"][0], rules=dict(mail_imap.DEFAULT_RULES))))
check("저장 전 확인: 조건이 비면 막는다", ob.validate_presets([{"no": 1, "name": "메일", "code": "012", "id": USER, "pw": "x",
                                                 "record": ob.imap_record(dict(cfg, rules=dict(mail_imap.DEFAULT_RULES)))}]) is not None)
check("저장 전 확인: 다 있으면 통과", ob.validate_presets([{"no": 1, "name": "메일", "code": "012", "id": USER, "pw": "x", "record": r}]) is None)

p = ob.new_preset(1, "메일", "012")
p.update(source="imap", imap=cfg)
fake = SimpleNamespace()
check("메일 서버 칸의 _final 은 imap 기록", st.imap_step(ob.App._final(fake, p)) is not None)
q = ob.new_preset(1, "메일", "012")
q.update(loaded=dict(r, steps=[dict(r["steps"][0], id=0)]), source="shop")
check("메일 서버에서 쇼핑몰로 바꾼 칸은 기록 없음 (imap 단계를 단계 목록에 보이지 않는다)", ob.App._final(fake, q) is None)
asked, said = [], []
rec_p = ob.new_preset(1, "지마켓", "013")
rec_p.update(loaded={"version": 1, "start_url": "https://x", "steps": [{"id": 0, "kind": "goto", "href": "https://x"}]})
app = SimpleNamespace(presets=[rec_p], cur=0, source_var=SimpleNamespace(get=lambda: "imap", set=lambda v: said.append(v)),
                      ask=lambda *a: asked.append(a) or False, id_var=SimpleNamespace(get=lambda: ""))
ob.App._source_changed(app)
check("기록이 있는 칸을 메일 서버로 바꾸면 묻고, 아니요면 되돌린다", len(asked) == 1 and said == ["shop"] and rec_p["source"] == "shop"
      and rec_p["imap"] is None, str((asked, said)))

print("=== 3. 저장 → 사용자 설정 Sites (옵저버 store) ===")
files = [{"no": 1, "name": "주문 메일", "code": "012", "saved_at": "2026-10-22T09:00:00", "record": r}, st.blank_preset(2)]
check("저장 성공", ob.store(files, {1: (USER, PASSWORD)}) is None)
site = st.read_user_config()["Sites"]["PRESET1"]
check("Sites 칸: replay·imap 주소·Code·잠근 비밀번호 (평문 아님)", site["Action"] == [st.REPLAY_ACTION] and site["URL"] == "imap://127.0.0.1"
      and site["Code"] == "012" and site["ID"] == USER and PASSWORD not in str(site["PW"]), str(site))
back = ob.load_presets()[0]
check("다시 열면 메일 서버 칸으로 (서버·조건 그대로)", back["source"] == "imap" and back["imap"]["host"] == "127.0.0.1"
      and back["imap"]["rules"]["subject_prefix"] == "[주문]" and back["has_pw"])

print("=== 4. 프리셋 옮기기 - 기록 내용만 (아이디·비밀번호 없이) ===")
item = pt.export_item(1)
check("파일로 내보내기·검사 통과, 아이디·비밀번호 없음", pt.check_file(item) is item and st.imap_step(item["record"])
      and USER not in str(item) and PASSWORD not in str(item))
q = ob.new_preset(2)
ob.load_file_into(q, item)
check("파일에서 불러오면 메일 서버 칸", q["source"] == "imap" and q["imap"]["host"] == "127.0.0.1")

print("=== 5. ACTOR 실행 (가짜 메일 서버) ===")
DL = os.path.join(TMP, "ERPIA_AI_EXCEL")
wr.download_dir = lambda: DL
real_ctx = ssl.create_default_context
ssl.create_default_context = lambda *a, **k: srv.client_ctx     # 가짜 서버의 자체 서명 인증서만 믿는다 (시험에서만)
st.set_preset_switches({"PRESET1": True})
lines, real_log = [], wr.log
wr.log = lambda m="": lines.append(str(m))
try:
    code = wr.cmd_run(["PRESET1"], headless=True)
    got = sorted(os.listdir(DL)) if os.path.isdir(DL) else []
    row = st.read_history(program="prepare")[0]
    check("[주문] 메일의 엑셀만 (사이트코드)이름 으로 받는다 - 광고·엑셀 없는 메일은 안 받음", code == 0 and got == ["(012)주문.xlsx"], str((code, got)))
    check("단계는 완료", [s["state"] for s in row["steps"]] == ["done"], str(row["steps"]))
    check("기록에 비밀번호·본문·보낸 사람 전체 주소가 없다", not any(PASSWORD in x or "본문" in x or "orders@shop" in x for x in lines),
          "\n".join(lines))
    check("가짜 서버에 지우기·옮기기·읽음 표시가 오지 않았다", not any(w in c.upper() for c in srv.commands
                                                       for w in ("EXPUNGE", "DELETE", "MOVE", "COPY", "STORE")))
    lines.clear()
    time.sleep(1.1)       # 기록 줄은 시작 시각(초)으로 줄 세운다 - 같은 초면 앞 실행 줄을 읽는다
    code = wr.cmd_run(["PRESET1"], headless=True)
    row = st.read_history(program="prepare")[0]
    check("다시 돌리면 이미 받은 메일은 건너뛰어 '대상 없음' (토큰을 쓰지 않는다)", code == 0 and sorted(os.listdir(DL)) == ["(012)주문.xlsx"]
          and row["steps"][0]["state"] == "skipped", str(row["steps"]))
    check("메일이 없던 날은 '대상 없음'", row["steps"][0].get("note") == "대상 없음", str(row["steps"]))

    srv.add(mail("[주문] 첨부 없음 둘째", files=()), NOW)
    srv.add(mail("[주문] 큰 메일", files=(("큰.xlsx", b"z" * 4000),)), NOW)
    real_max, mail_imap.MAX_SIZE = mail_imap.MAX_SIZE, 3000
    time.sleep(1.1)
    code = wr.cmd_run(["PRESET1"], headless=True)
    mail_imap.MAX_SIZE = real_max
    row = st.read_history(program="prepare")[0]
    note = row["steps"][0].get("note") or ""
    check("받을 첨부 없는 메일·50MB 넘는 메일뿐이면 실패가 아니라 건너뜀, 까닭을 갈라 보인다 (BugBuster I9·M15)",
          code == 0 and row["steps"][0]["state"] == "skipped" and "메일 1통 - 받을 첨부 없음" in note and "50MB" in note
          and any("50MB" in x and "!" in x for x in lines), str((code, row["steps"])))

    real_cfg, real_limit = wr.load_config, st.preset_limit
    wr.load_config = lambda: dict(real_cfg(), PRESET3={**real_cfg()["PRESET1"], "Preset": 3})
    st.preset_limit = lambda: 2
    lines.clear()
    time.sleep(1.1)
    try:
        code_all, log_all = wr.cmd_run([], headless=True), list(lines)
        code_one = wr.cmd_run(["PRESET3"], headless=True)
    finally:
        wr.load_config, st.preset_limit = real_cfg, real_limit
    check("프리셋 수 한도 밖 칸은 로그만 남기고 건너뛰고 나머지는 실행 (BugBuster M10)",
          code_all == 0 and any("PRESET3" in x and "넘어 건너뜁니다" in x for x in log_all), "\n".join(log_all))
    check("한도 밖 칸을 --site 로 콕 집으면 지금처럼 거부", code_one == 1)
    st.save_preset_sites(st.read_presets(), {1: (USER, "틀린-비밀번호")})
    st.set_preset_switches({"PRESET1": True})
    lines.clear()
    time.sleep(1.1)       # 기록 줄은 시작 시각(초)으로 줄 세운다 - 같은 초면 앞 실행 줄을 읽는다
    code = wr.cmd_run(["PRESET1"], headless=True)
    row = st.read_history(program="prepare")[0]
    check("비밀번호가 틀리면 실패하고 까닭을 사람 말로", code != 0 and row["steps"][0]["state"] == "failed"
          and "로그인을 거부" in (row["steps"][0].get("note") or ""), str(row["steps"]))
    check("틀린 비밀번호도 기록에 없다", not any("틀린-비밀번호" in x for x in lines))
finally:
    wr.log = real_log
    ssl.create_default_context = real_ctx
    srv.close()

print("=== 6. BugBuster H2·L6·I10·K13·I3·I5·I6·I8 (옵저버) ===")


class FakeApp(ob.App):
    """화면 없이 App 메서드만 - tk 칸·일꾼은 안 쓴다."""

    def __init__(self, presets, cur=0):
        self.presets, self.cur, self.said, self.told, self.picked = presets, cur, [], [], []
        self.recording, self.previewing = None, False
        self.status = SimpleNamespace(config=lambda **k: self.said.append(k.get("text")))

    def _store_fields(self):
        pass

    def _kept(self, p, final):
        return list(range(len(final["steps"])))

    def select(self, i):
        self.picked.append(i)

    def tell(self, *a):
        self.told.append(a)

    def ask(self, *a):
        return True


pw_calls, real_pw = [], ob.stored_password
ob.stored_password = lambda no: pw_calls.append(no) or "저장된-비번"
shop = {"version": 1, "start_url": "https://x", "steps": [{"id": 0, "kind": "goto", "href": "https://x"}]}
try:
    moved = ob.new_preset(1, "옮겨진 칸", "013")     # ① 을 지워 ② 가 ① 자리로 당겨진 채 저장 전 (orig = 2)
    moved.update(loaded=dict(shop), orig=2, has_pw=True, id="u", source="imap", imap=cfg)
    a = FakeApp([moved])
    os.makedirs(os.path.dirname(st.imap_memory_path(1)), exist_ok=True)
    for path in (st.imap_memory_path(1), st.mail_memory_path(1)):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{}")
    a.preview()
    a.imap_find()
    a.clear_imap_memory()
    a.clear_mail_memory()
    a.export_file()
    check("H2: 당겨진 칸은 미리보기·찾아보기·기억 지우기 모두 '저장한 뒤에' 로 막고 다른 프리셋 비밀번호를 꺼내지 않는다",
          a.said == [ob.App.SAVE_FIRST] * 4 and pw_calls == [], str((a.said, pw_calls)))
    check("H2: 당겨진 칸의 내보내기도 막는다", len(a.told) == 1 and "저장한 뒤" in a.told[0][1], str(a.told))
    check("H2: 막혔을 때 ① 번호의 메일 기억은 그대로", os.path.isfile(st.imap_memory_path(1)) and os.path.isfile(st.mail_memory_path(1)))
    same = dict(moved, orig=1)
    b2 = FakeApp([same])
    check("H2: 저장된 번호 그대로인 칸은 그 번호로 찾는다", ob.saved_no(same, 0) == 1 and ob.saved_no(dict(moved, orig=None), 0) is None)
    b2.clear_imap_memory()
    check("H2: 번호가 맞으면 메일 기억을 지운다", not os.path.isfile(st.imap_memory_path(1)) and b2.said == ["받은 메일 기억을 지웠습니다."], str(b2.said))

    p1 = ob.new_preset(1, "가", "021")
    p1.update(loaded=dict(shop), orig=1, id="u1", pw="pw-one-1234")
    p2 = ob.new_preset(2, "나", "022")
    p2.update(loaded={"version": 1, "start_url": "https://y", "steps": [{"id": 0, "kind": "goto", "href": "https://y/?q=pw-one-1234"}]},
              orig=2, id="u2", pw="pw-two-5678")
    c = FakeApp([p1, p2])
    c.save()
    check("L6: ① 비밀번호가 ② 기록에 있으면 ② 를 고르고 ② 로 안내한다", c.picked == [1] and c.said and c.said[-1].startswith(ob.circled(2)),
          str((c.picked, c.said)))
    check("I10: 보낸 사람 안내에 이름은 흉내 낼 수 있다·주소(@) 권함", "흉내" in ob.App.SENDER_NOTE and "@" in ob.App.SENDER_NOTE)

    for path in (st.imap_memory_path(1), st.mail_memory_path(1)):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{}")
    keep = [dict(f) for f in st.read_presets()]
    check("K13: 같은 사이트코드로 다시 저장하면 메일 기억은 그대로", ob.store(keep, {1: (USER, PASSWORD)}) is None
          and os.path.isfile(st.imap_memory_path(1)) and os.path.isfile(st.mail_memory_path(1)))
    keep[0]["code"] = "019"
    check("K13: 같은 칸에 다른 사이트코드를 저장하면 그 칸의 웹메일·IMAP 기억을 지운다", ob.store(keep, {1: (USER, PASSWORD)}) is None
          and not os.path.isfile(st.imap_memory_path(1)) and not os.path.isfile(st.mail_memory_path(1)))

    d1 = ob.new_preset(1, "날짜몰", "031")
    d1.update(orig=1, id="u1", pw="pw-a-111", deleted={1},
              loaded={"version": 1, "start_url": "https://x", "steps": [
                  {"id": 0, "kind": "goto", "href": "https://x"}, {"id": 1, "kind": "click", "page": 0},
                  {"id": 2, "kind": "fill", "page": 0, "value": "기간 2026. 10. 21 부터"}]})
    d2 = ob.new_preset(2, "csv 메일", "032")
    d2.update(orig=2, id=USER, pw="pw-b-222", source="imap", imap=dict(cfg, rules=dict(cfg["rules"], exts=["xlsx", "csv"])))
    e = FakeApp([d1, d2])
    e._load_fields = lambda: None
    e.save()
    msg = e.said[-1] if e.said else ""
    check("I3: 저장은 되고, 날짜로 못 바꾼 날짜 값은 보이는 단계 번호(지운 단계 뺌)로 알린다",
          msg.startswith("저장했습니다.") and f"{ob.circled(1)} 2단계 값 '기간 2026. 10. 21 부터'" in msg, msg)
    check("I6: 메일 서버 조건의 경고(csv)도 저장 때 보인다 (막지 않음)", f"{ob.circled(2)} " in msg and "csv" in msg, msg)
    e.said.clear()
    e.render = lambda: None
    e._imap_found(1, [])
    check("I6: [찾아보기] 결과에도 경고", e.said and "csv" in e.said[-1], str(e.said))
    check("I8·I5: 기간 칸·안내, 메일마다 안내 글", "처음 받을 때" in dict((k, t) for t, k in ob.App.IMAP_TEXT)["days"]
          and "지난번 받은 날부터" in ob.App.DAYS_NOTE and "제목으로 검색" in ob.MAIL_HINT)

    f1 = ob.new_preset(1, "날짜몰", "039")          # ① 칸(031)을 다른 사이트로 다시 녹화, 비밀번호는 비움
    f1.update(orig=1, id="u1", pw="", has_pw=True,
              loaded={"version": 1, "start_url": "https://x", "steps": [
                  {"id": 0, "kind": "goto", "href": "https://x"},
                  {"id": 1, "kind": "secret", "page": 0, "host": "nid.naver.com"},
                  {"id": 2, "kind": "secret", "page": 0, "host": "login.coupang.com"}]})
    g = FakeApp([f1, dict(d2, pw="", has_pw=True, orig=2)])
    g._load_fields = lambda: None
    g.save()
    msg = g.said[-1] if g.said else ""
    check("I1: 저장은 되고, 비밀번호 단계가 다른 사이트에 섞였으면 알린다",
          msg.startswith("저장했습니다.") and f"{ob.circled(1)} 비밀번호 단계가 서로 다른 사이트(coupang.com, naver.com)" in msg, msg)
    check("I1: 사이트코드가 바뀌었는데 비밀번호를 비웠으면 이전 사이트 비밀번호를 쓴다고 알린다 (② 는 그대로라 안 알림)",
          f"{ob.circled(1)} 사이트코드가 바뀌었지만" in msg and f"{ob.circled(2)} 사이트코드" not in msg, msg)
finally:
    ob.stored_password = real_pw

print()
print(f"실패: {'없음' if not fails else fails}")
sys.exit(1 if fails else 0)
