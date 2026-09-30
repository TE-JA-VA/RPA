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
check("비밀번호 칸 안내: 처음", all(win.hints[k][0].cget("text") == rs.PW_HINTS["none"] for k in rs.PASSWORD_KEYS))
check("상태 줄: 버전 없음·에이전트 꺼짐", "버전 없음" in win.status.get() and "꺼져 있음" in win.status.get(), win.status.get())
check("메일 칸이 켜져 있다 (빈 틀에 SITE1)", str(win.entries["mail_id"].cget("state")) == "normal")
check("프린터 목록", list(win.entries["printer"].cget("values")) == ["", "사무실 프린터", "Microsoft Print to PDF"],
      win.entries["printer"].cget("values"))


def all_widgets(w):
    for c in w.winfo_children():
        yield c
        yield from all_widgets(c)


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

print("=== 2. 빈 칸으로 저장 ===")
win.on_save()
wait_idle()
check("빨간 글씨로 무엇이 틀렸는지", "업체코드를 넣으세요" in win.msg.get() and win.msg_label.cget("fg") == rs.RED, win.msg.get())
check("저장 안 됨", not win.saved and not os.path.exists(paths["user_config"]))

print("=== 3. 채우고 저장 ===")
for k, v in dict(cid="net", pc_id="test", agent_pw="Agent-Pw-5555!", admin_code="AM001", erp_id="rpa",
                 erp_pw="Erp-Pw-1234!", mail_id="mail@x.com", mail_pw="Mail-Pw-9876!", printer="사무실 프린터",
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
check("저장 뒤 비밀번호 칸은 비고 안내는 '저장됨'", all(win.vars[k].get() == "" for k in rs.PASSWORD_KEYS)
      and all(win.hints[k][0].cget("text") == rs.PW_HINTS["ok"] for k in rs.PASSWORD_KEYS))
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
check("이 PC 에 없는 프린터면 알리고 목록에 넣어 둔다", "이 PC 에 없는 프린터" in win.hints["printer"][0].cget("text")
      and "없는 프린터" in list(win.entries["printer"].cget("values")))

print("=== 5-2. 에이전트가 멈춘 까닭 ===")
with open(paths["stop_file"], "w", encoding="utf-8") as f:
    f.write('{"code": 3, "reason": "로그인이 막혔습니다 (기계 계정 비밀번호가 바뀌었거나 계정이 막힘)", "at": "2026-09-29 15:00:00"}')
win.reload()
root.update()
check("멈춘 까닭을 상태 줄에 노란 글씨로", "멈춤" in win.status.get() and "로그인이 막혔습니다" in win.status.get()
      and str(win.status_label.cget("foreground")) == rs.AMBER, win.status.get())
check("로그인 거부로 멈췄으면 기계 계정 비밀번호 칸이 '다시 넣으세요'", win.hints["agent_pw"][0].cget("text") == rs.PW_HINTS["refused"])
os.remove(paths["stop_file"])

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
