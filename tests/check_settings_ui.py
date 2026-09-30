"""설정 창(rpa_settings.SettingsWindow)을 진짜로 띄워 본다 - 첫 모습, 빈 칸 저장의 빨간 안내, 채워서 저장,
옛 폴더 가져오기 → 저장 → 이름 바꾸기, 없는 프린터, 옛 에이전트. 저장 뒤 화면 사진을 남긴다.

    .venv\\Scripts\\python.exe tests\\check_settings_ui.py [사진.png]

로그인·작업 등록·알림 창은 가짜라 관리자 권한도 인터넷도 필요 없다. 창이 몇 초 동안 화면에 뜬다.
새 구조 자리는 RPA_PROGRAMDATA 임시 폴더다.
"""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = tempfile.mkdtemp(prefix="rpa_settings_ui_")
PD = os.path.join(TMP, "programdata", "AFTER MARKET", "RPA")
os.makedirs(os.path.join(PD, "config"))
os.makedirs(os.path.join(TMP, "agentdata"))
for _k in ("RPA_USER_CONFIG", "RPA_CRED_FILE", "RPA_AGENT_CONFIG"):
    os.environ.pop(_k, None)
os.environ["RPA_PROGRAMDATA"] = PD
os.environ["RPA_AGENT_QUEUE"] = os.path.join(TMP, "agentdata", "queue.jsonl")
os.environ["RPA_AGENT_MUTEX"] = rf"Local\AFTER_MARKET_RPA_AGENT_UI_TEST_{os.getpid()}"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "firebase" / "agent"))
sys.stdout.reconfigure(encoding="utf-8")

import tkinter as tk  # noqa: E402
from tkinter import font as tkfont  # noqa: E402
from PIL import ImageGrab  # noqa: E402
import agent  # noqa: E402
import rpa_settings as rs  # noqa: E402
import rpa_status as st  # noqa: E402
import secret  # noqa: E402

SHOT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(TMP, "settings.png")
fails = []
_no = [0]


def check(name, cond, detail=""):
    _no[0] += 1
    mark = "통과" if cond else "실패"
    print(f"  {_no[0]:2d}. [{mark}] {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(f"{_no[0]}. {name} {detail}")


class FakeDialogs:
    def __init__(self):
        self.said, self.folder_result = [], None

    def info(self, text):
        self.said.append(("info", text))

    def error(self, text):
        self.said.append(("error", text))

    def yesno(self, text):
        self.said.append(("yesno", text))
        return True

    def retry(self, text):
        self.said.append(("retry", text))
        return False

    def folder(self, title):
        return self.folder_result

    def exe(self, start):
        return None


def fake_login(path, cid, pc_id, password):
    secret.write_config(path, dict(secret.PUBLIC, email=agent.email_for(cid, pc_id), cid=cid, pc_id=pc_id), password)


calls = []


def fake_run(args, timeout=60):
    calls.append(args[1])
    return 0, ""


prog = os.path.join(TMP, "설치 폴더")
os.makedirs(os.path.join(prog, "firebase", "agent"))
shutil.copyfile(ROOT / "release" / "RPA_UserConfig.template.json", os.path.join(prog, rs.TEMPLATE_NAME))
cfg = os.path.join(PD, "config")
paths = {"program_dir": prog, "config_dir": cfg, "user_config": os.path.join(cfg, st.USER_CONFIG_NAME),
         "agent_config": os.path.join(cfg, rs.AGENT_CONFIG_NAME), "template": os.path.join(prog, rs.TEMPLATE_NAME),
         "agent_py": os.path.join(prog, "firebase", "agent", "agent.py"),
         "stop_file": os.path.join(st.data_dir(), "에이전트_멈춤.json")}


def wait_idle(sec=15):
    end = time.time() + sec
    while time.time() < end:
        root.update()
        if not win.busy_now:
            return True
        time.sleep(0.05)
    return False


rs.warm_roots = lambda: None       # 인증서 채우기(PowerShell·인터넷)는 test_settings·test_background 가 본다
rs.dpi_aware()
root = tk.Tk()
dlg = FakeDialogs()
win = rs.SettingsWindow(root, paths, login=fake_login, run=fake_run, running=lambda: False, procs=lambda: [],
                        printers=["사무실 프린터", "Microsoft Print to PDF"], dialogs=dlg)
root.update()

print("=== 1. 첫 모습 ===")


def all_widgets(w):
    for c in w.winfo_children():
        yield c
        yield from all_widgets(c)


def shown(key):
    """칸 안 흐린 안내가 보이면 그 글자, 안 보이면 None."""
    root.update()
    label = win.hints[key][0]
    return label.cget("text") if label.winfo_ismapped() else None


check("처음 비밀번호 칸은 아무 글도 없다 ('*필수' 없앰 - 빠지면 저장할 때 빨간 글씨로 알린다)",
      rs.PW_HINTS["none"] == "" and all(shown(k) is None for k in rs.PASSWORD_KEYS), [shown(k) for k in rs.PASSWORD_KEYS])
check("상태 줄: 버전 없음·에이전트 꺼짐", "버전 없음" in win.status.get() and "꺼져 있음" in win.status.get(), win.status.get())
check("메일 칸이 없다 (다른 프로그램이 맡는다 - 2026-09-30)", "mail_id" not in win.entries and "mail_pw" not in win.entries)
check("프린터 목록: 맨 위 '(기본 프린터)', 안 골랐으면 그것이 보인다",
      list(win.entries["printer"].cget("values")) == [rs.DEFAULT_PRINTER, "사무실 프린터", "Microsoft Print to PDF"]
      and win.vars["printer"].get() == rs.DEFAULT_PRINTER, (win.entries["printer"].cget("values"), win.vars["printer"].get()))
check("단추 이름 '기존 설정값 가져오기'", win.import_btn.cget("text") == "기존 설정값 가져오기", win.import_btn.cget("text"))
check(f"창 폭 {root.winfo_width()} ≤ 520 (오른쪽 설명 열을 없애고 설명은 빈 칸 안으로 - 2026-09-30)", root.winfo_width() <= 520)
check("빈 칸 안 흐린 안내: 택배사·박스·운임", all(shown(k) == win.hints[k][1] != "" and win.hints[k][0].cget("fg") == rs.PLACEHOLDER
                                          for k in ("carrier", "box", "fare")), [shown(k) for k in ("carrier", "box", "fare")])
face_now = tkfont.nametofont("TkDefaultFont")
candidates = ([(k, win.hints[k][1]) for k in win.hints if win.hints[k][1]]
              + [(k, t) for k in rs.PASSWORD_KEYS for t in rs.PW_HINTS.values() if t] + [("erpia_path", rs.ERPIA_MISSING)])
fits = [(k, t) for k, t in candidates if face_now.measure(t) + 8 > win.entries[k].winfo_width()]
check("흐린 안내는 칸 안에 다 들어간다 (잘리지 않는다)", not fits, fits)
win.vars["carrier"].set("한진")
gone = shown("carrier")
win.vars["carrier"].set("")
check("값을 넣으면 흐린 안내가 사라지고, 지우면 다시 보인다", gone is None and shown("carrier") == win.hints["carrier"][1])
check("흐린 안내·'(기본 프린터)' 는 값이 아니다 (저장할 값은 빈 칸)", win.form()["carrier"] == "" and win.form()["printer"] == "",
      (win.form()["carrier"], win.form()["printer"]))
check("업체코드·PC코드·ERPia 업체코드 칸은 안내가 없다", all(win.hints[k][1] == "" for k in ("cid", "pc_id", "admin_code")))

names = {label for _, fields in rs.ROWS for _, label, _, _ in fields}
face = tkfont.nametofont("TkDefaultFont")
cut = [w.cget("text") for w in all_widgets(root) if w.winfo_class() == "TLabel" and w.cget("text") in names
       and face.measure(w.cget("text")) > w.winfo_width()]
check("칸 이름이 잘리지 않는다 (글자 폭 ≤ 칸 폭)", not cut, cut)
check("출력 방식: 두 가지에서만 고르고, 새 설치는 수동", list(win.entries["print_mode"].cget("values")) == list(rs.PRINT_MODES)
      and win.vars["print_mode"].get() == rs.PRINT_MANUAL and str(win.entries["print_mode"].cget("state")) == "readonly",
      (win.entries["print_mode"].cget("values"), win.vars["print_mode"].get()))
notes = [w for w in all_widgets(root) if w.winfo_class() == "TLabel" and "물류관리에서 저장할 수 없습니다" in str(w.cget("text"))]
check("물류 경고 한 줄: 늘 보이는 주황 글씨 (2026-09-30 사용자 문구)", len(notes) == 1
      and str(notes[0].cget("foreground")) == rs.AMBER and notes[0].winfo_ismapped()
      and "실제 ERPia 에 등록한 택배사·박스·운임과 다를 경우" in notes[0].cget("text"), [n.cget("text") for n in notes])
check(f"창 높이 {root.winfo_height()} ≤ 690 (768 높이 노트북에서 작업 표시줄·제목 줄을 빼고 들어간다)",
      root.winfo_height() <= 690)
texts = [str(w.cget("text")) for w in all_widgets(root) if w.winfo_class() in ("TLabel", "TLabelframe")]
check("맨 위 긴 안내는 없고 대시보드 연결 묶음 맨 위에 '담당자로부터 받은 정보를 입력해주세요.' (2026-09-30)",
      "담당자로부터 받은 정보를 입력해주세요." in texts and not any("[저장] 을 누르세요" in t for t in texts), texts[:6])
check("칸 이름: ERPia 로그인의 '업체코드', 'ERPia 설치 위치', 묶음 '물류 처리 옵션'",
      "업체코드" in [label for key, label, _, _ in rs.ROWS[1][1] if key == "admin_code"]
      and "ERPia 설치 위치" in texts and "물류 처리 옵션" in texts, texts)


def printer_view():
    """(프린터 칸 상태, 없는 프린터 주황 줄이 보이나)"""
    root.update()
    return str(win.entries["printer"].cget("state")), bool(win.printer_warn.winfo_ismapped())


check("수동이면 프린터 칸이 꺼진다", printer_view() == ("disabled", False), printer_view())
win.vars["print_mode"].set(rs.PRINT_AUTO)
check("자동으로 바꾸면 고를 수 있다 (안 고르면 기본 프린터)", printer_view() == ("readonly", False)
      and win.vars["printer"].get() == rs.DEFAULT_PRINTER, printer_view())
win.vars["print_mode"].set(rs.PRINT_MANUAL)
check("다시 수동이면 다시 꺼진다", printer_view() == ("disabled", False), printer_view())

print("=== 2. 빈 칸으로 저장 ===")
win.on_save()
wait_idle()
check("빨간 글씨로 무엇이 틀렸는지", "업체코드를 넣으세요" in win.msg.get() and win.msg_label.cget("fg") == rs.RED, win.msg.get())
check("저장 안 됨", not win.saved and not os.path.exists(paths["user_config"]))

print("=== 3. 채우고 저장 ===")
for k, v in dict(cid="net", pc_id="test", agent_pw="Agent-Pw-5555!", admin_code="AM001", erp_id="rpa",
                 erp_pw="Erp-Pw-1234!", printer="사무실 프린터",
                 print_mode=rs.PRINT_AUTO, carrier="한진연동", box="대", fare="신용").items():
    win.vars[k].set(v)
win.on_save()
ok = wait_idle()
check("저장됨 (초록 안내)", ok and win.saved and "에이전트를 켰습니다" in win.msg.get() and win.msg_label.cget("fg") == rs.GREEN,
      win.msg.get())
check("설정 파일 두 개", os.path.isfile(paths["user_config"]) and os.path.isfile(paths["agent_config"]))
saved_logistic = st.read_user_config(paths["user_config"])["Logistic"]
check("물류 칸이 설정 파일에 (자동 = Y)", saved_logistic == {"cboBS_Auto_YN": "Y", "Printer": "사무실 프린터", "cboTag": "한진연동",
                                                    "cboTagAmt": "대", "cboBeasong_Gu_Apply": "신용"}, saved_logistic)
check("작업 등록 → 켜기", calls == ["/Create", "/End", "/Run"], calls)
check("막 켰으면 상태 줄은 '켜는 중' (감독이 인증서를 채우고 켜기까지 1분쯤)", "켜는 중" in win.status.get(), win.status.get())
check("저장 뒤 비밀번호 칸은 비고, 칸 안에 흐린 '저장됨 - 바꿀 때만 입력'", all(win.vars[k].get() == "" for k in rs.PASSWORD_KEYS)
      and rs.PW_HINTS["ok"] == "저장됨 - 바꿀 때만 입력" and all(shown(k) == rs.PW_HINTS["ok"] for k in rs.PASSWORD_KEYS),
      [shown(k) for k in rs.PASSWORD_KEYS])
root.update()
time.sleep(0.3)
root.update()
x, y, w, h = root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height()
ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).save(SHOT)
check(f"화면 사진 {SHOT} ({w}x{h})", os.path.isfile(SHOT))

print("=== 4. 옛 폴더 가져오기 → 저장 → 이름 바꾸기 ===")
old = os.path.join(TMP, "배포_옛")
os.makedirs(os.path.join(old, "firebase", "agent"))
open(os.path.join(old, "Run_All.bat"), "wb").close()
shutil.copyfile(paths["user_config"], os.path.join(old, st.USER_CONFIG_NAME))
shutil.copyfile(paths["agent_config"], os.path.join(old, "firebase", "agent", rs.AGENT_CONFIG_NAME))
dlg.folder_result = old
win.on_import()
root.update()
check("이미 있으면 바꿀지 묻고 가져온다", any(k == "yesno" and "바꿀까요" in t for k, t in dlg.said)
      and "가져왔습니다" in win.msg.get(), win.msg.get())
win.on_save()
wait_idle()
check("저장 뒤 옛 폴더 이름을 바꾼다", os.path.isdir(old + "_옮김") and not os.path.exists(old), dlg.said[-2:])

print("=== 5. 없는 프린터 ===")
data = st.read_user_config(paths["user_config"])
data["Logistic"]["Printer"] = "없는 프린터"
st.write_user_config(data, paths["user_config"])
win.reload()
root.update()
check("이 PC 에 없는 프린터면 프린터 줄 아래 주황 한 줄, 목록에도 넣어 둔다 (자동)", printer_view() == ("readonly", True)
      and win.printer_warn.cget("text") == rs.MISSING_PRINTER and str(win.printer_warn.cget("foreground")) == rs.AMBER
      and "없는 프린터" in list(win.entries["printer"].cget("values")) and win.vars["printer"].get() == "없는 프린터",
      printer_view())
win.vars["print_mode"].set(rs.PRINT_MANUAL)
check("수동이면 그 줄도 숨긴다 (프린터를 안 쓴다)", printer_view() == ("disabled", False), printer_view())
win.vars["print_mode"].set(rs.PRINT_AUTO)
check("자동으로 돌아오면 다시 보인다", printer_view() == ("readonly", True), printer_view())

print("=== 5-2. 에이전트가 멈춘 까닭 ===")
with open(paths["stop_file"], "w", encoding="utf-8") as f:
    f.write('{"code": 3, "reason": "로그인이 막혔습니다 (기계 계정 비밀번호가 바뀌었거나 계정이 막힘)", "at": "2026-09-29 15:00:00"}')
win.reload()
root.update()
check("멈춘 까닭을 상태 줄에 노란 글씨로", "멈춤" in win.status.get() and "로그인이 막혔습니다" in win.status.get()
      and str(win.status_label.cget("foreground")) == rs.AMBER, win.status.get())
check("로그인 거부로 멈췄으면 기계 계정 비밀번호 칸 안에 주황 '새 비밀번호 입력'", shown("agent_pw") == rs.PW_HINTS["refused"]
      and str(win.hints["agent_pw"][0].cget("fg")) == rs.AMBER, shown("agent_pw"))
check(f"긴 까닭은 줄을 바꿔 창 폭을 늘리지 않는다 ({root.winfo_width()} ≤ 520 - 2026-09-29 샌드박스에서 1070 까지 늘었다)",
      root.winfo_width() <= 520)
os.remove(paths["stop_file"])

print("=== 5-3. ERPia 를 못 찾으면 ===")
data = st.read_user_config(paths["user_config"])
data["ERPia"] = {"ExePath": "C:/없는 폴더/ERPiaMain.exe"}
st.write_user_config(data, paths["user_config"])
saved_dirs, st._erpia_install_dirs = st._erpia_install_dirs, lambda: []
try:
    win.reload()
    check("ERPia 설치 위치 칸 안에 주황 '못 찾음 - [찾기]'", shown("erpia_path") == rs.ERPIA_MISSING
          and str(win.hints["erpia_path"][0].cget("fg")) == rs.AMBER, shown("erpia_path"))
finally:
    st._erpia_install_dirs = saved_dirs

print("=== 6. 옛 에이전트 ===")
win.procs = lambda: [(9, "python.exe", r"D:\old\python\python.exe", "python agent.py")]
check("옛 에이전트가 돌면 닫으라고 하고, 그만두면 저장하지 않는다", win.check_old_agents() is False and dlg.said[-1][0] == "retry")

print("=== 7. 단추 처리 중 뜻밖의 오류 ===")
root.after(0, lambda: 1 / 0)
for _ in range(20):
    root.update()
    if win.msg.get().startswith("뜻밖의"):
        break
    time.sleep(0.05)
check("창은 그대로 두고 빨간 글씨로 알리며 기록한다 (Tk 기본은 보이지 않는 stderr)",
      "ZeroDivisionError" in win.msg.get() and win.msg_label.cget("fg") == rs.RED
      and os.path.isfile(os.path.join(st.data_dir(), rs.CRASH_LOG_NAME)), win.msg.get())

root.destroy()
if len(sys.argv) > 1:
    shutil.rmtree(TMP, ignore_errors=True)
print()
print(f"실패: {'없음' if not fails else fails}")
sys.exit(1 if fails else 0)
