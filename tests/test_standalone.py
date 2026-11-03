"""옵저버 단독 버전 (설계 2026-11-03) - 단독 표시·단독 폴더·잠금 (rpa_status), ACTOR 단독 실행 (web_runner). 창은 뜨지 않는다.

실제 설정은 건드리지 않는다. ProgramData 를 임시 폴더로 바꿔 켬/끔 두 경우를 본다.
    .venv\\Scripts\\python.exe tests\\test_standalone.py
"""
import os
import sys
import tempfile
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="rpa_standalone_")
os.environ["ProgramData"] = os.path.join(TMP, "ProgramData")      # install_root 가 보는 뿌리 - 진짜 ProgramData 를 안 건드린다
for _k in ("RPA_PROGRAMDATA", "RPA_STATUS_DIR", "RPA_STANDALONE", "RPA_OBSERVER_LOCK"):
    os.environ.pop(_k, None)
os.environ["RPA_USER_CONFIG"] = os.path.join(TMP, "config", "RPA_UserConfig.json")
os.makedirs(os.path.join(TMP, "config"))
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

import rpa_status as st  # noqa: E402

fails = []
_no = [0]


def check(name, cond, detail=""):
    _no[0] += 1
    print(f"  {_no[0]:2d}. [{'통과' if cond else '실패'}] {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(f"{_no[0]}. {name} {detail}")


def raises(exc, fn, *args):
    try:
        fn(*args)
        return None
    except exc as e:
        return e


def on(flag):
    if flag:
        os.environ["RPA_STANDALONE"] = "1"
    else:
        os.environ.pop("RPA_STANDALONE", None)


print("=== 1. 단독 표시와 단독 폴더 (rpa_status) ===")
on(False)
check("flag_off_same: 표시가 없으면 단독이 아니다", st.standalone() is False)
check("flag_off_same: install_root 는 AFTER MARKET\\RPA", st.install_root().endswith(os.path.join("AFTER MARKET", "RPA")), st.install_root())
off_config, off_status = st.config_dir(), st.status_dir(create=False)
os.environ["RPA_STATUS_DIR"] = os.path.join(TMP, "status_off")      # 이 PC 의 진짜 settings.json 을 안 본다
check("flag_off_same: preset_limit 는 PRESET_DEFAULT", st.preset_limit() == st.PRESET_DEFAULT)
os.environ.pop("RPA_STATUS_DIR", None)

on(True)
check("flag_on: RPA_STANDALONE=1 이면 단독", st.standalone() is True)
check("flag_on: install_root 는 AFTER MARKET\\Observer", st.install_root().endswith(os.path.join(*st.STANDALONE_DIRS)), st.install_root())
check("flag_on: status_dir 는 data_dir\\status", st.status_dir() == os.path.join(st.data_dir(), "status"), st.status_dir())
check("flag_on: preset_limit == PRESET_MAX, parallel_limit == PARALLEL_MAX",
      st.preset_limit() == st.PRESET_MAX and st.parallel_limit() == st.PARALLEL_MAX)
check("flag_on: 잠금 이름이 단독용", st.observer_lock_name() == r"Local\AFTER_MARKET_OBSERVER_SA", st.observer_lock_name())
on_config, on_status = st.config_dir(), st.status_dir(create=False)
check("two_products_apart: 켬/끔의 설정 폴더·기록 폴더가 다르다 (Review Focus 1)",
      off_config != on_config and off_status != on_status, (off_config, on_config, off_status, on_status))
check("two_products_apart: 단독 설정은 Observer 아래", on_config.startswith(st.install_root()) and on_status.startswith(st.install_root()),
      (on_config, on_status))

on(False)
check("flag_off_same: 끄면 잠금 이름은 지금 것", st.observer_lock_name() == st.OBSERVER_LOCK)
_orig = st.program_dir
_flag_dir = os.path.join(TMP, "prog")
os.makedirs(_flag_dir)
st.program_dir = lambda: _flag_dir
check("flag_file: 설치 폴더에 표시 파일이 없으면 단독이 아니다", st.standalone() is False)
open(os.path.join(_flag_dir, st.STANDALONE_FLAG), "w").close()
check("flag_file: 설치 폴더의 OBSERVER_STANDALONE 파일로 단독", st.standalone() is True)
st.program_dir = _orig
check("flag_file: 되돌리면 꺼짐", st.standalone() is False)

on(True)
os.environ["RPA_STATUS_DIR"] = os.path.join(TMP, "status_sa")
check("download_default: 설정에 값이 없으면 바탕화면\\AI", st.download_dir_choice() == os.path.join(st.find_desktop_dir(), "AI"), st.download_dir_choice())
cfg = st.read_settings()
cfg["prepare"]["download_dir"] = os.path.join(TMP, "받은것")
st.write_settings(cfg)
check("download_default: 값이 있으면 그 값", st.download_dir_choice() == os.path.join(TMP, "받은것"), st.download_dir_choice())
check("no_tamper_block: 판 목록·서명이 없는 설치 폴더는 막지 않는다", st.install_block_reason(_flag_dir) is None, st.install_block_reason(_flag_dir))
os.environ.pop("RPA_STATUS_DIR", None)
on(False)

print("\n=== 1-2. 그 PC 에서만 (Task 10) ===")
_guid = st.machine_guid
st.machine_guid = lambda: "0f1e2d3c-4b5a-4968-8776-655443329f1c"
st.program_dir = lambda: _flag_dir
on(True)
check("빈 표시 파일(개발·시험)이면 묻지 않는다", st.standalone_pc_problem() is None)
with open(os.path.join(_flag_dir, st.STANDALONE_FLAG), "w", encoding="utf-8") as f:
    f.write("0F1E2D3C-4B5A-4968-8776-655443329F1C\r\n")
check("같은 번호(대소문자·공백 무시)면 None", st.standalone_pc_problem() is None)
with open(os.path.join(_flag_dir, st.STANDALONE_FLAG), "w", encoding="utf-8") as f:
    f.write("11111111-2222-3333-4444-555555555555")
check("다른 번호면 글", st.standalone_pc_problem() == "이 PC 에 설치된 옵저버 단독 버전이 아닙니다. 담당자에게 문의하여 주십시오.")
on(False)
st.program_dir = _orig           # 표시 파일이 없는 폴더
check("단독이 아니면 None", st.standalone_pc_problem() is None)
open(os.path.join(_flag_dir, st.STANDALONE_FLAG), "w").close()
st.machine_guid = _guid
check("진짜 MachineGuid 는 GUID 꼴 소문자", bool(__import__("re").fullmatch(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}", st.machine_guid())), st.machine_guid())

print("\n=== 2. ACTOR 단독 실행 (web_runner) ===")
import web_runner as wr  # noqa: E402

check("run_targets_env: env 의 번호 순서대로 PRESETn", wr.run_targets(True, None, {wr.RUN_PRESETS_ENV: "3,1"}) == [st.preset_site_key(3), st.preset_site_key(1)])
check("run_targets_env: env 가 없으면 sites 그대로", wr.run_targets(True, None, {}) is None and wr.run_targets(True, ["PRESET2"], {}) == ["PRESET2"])
check("run_targets_env: --all 이 아니면 env 를 안 본다", wr.run_targets(False, ["PRESET2"], {wr.RUN_PRESETS_ENV: "1"}) == ["PRESET2"])
check("run_targets_env: 숫자가 아니면 ValueError", isinstance(raises(ValueError, wr.run_targets, True, None, {wr.RUN_PRESETS_ENV: "a"}), ValueError))
on(False)
check("download_dir_standalone: 꺼지면 ERPIA_AI_EXCEL", wr.download_dir().endswith(wr.DOWNLOAD_DIR_NAME), wr.download_dir())
on(True)
os.environ["RPA_STATUS_DIR"] = os.path.join(TMP, "status_sa")
check("download_dir_standalone: 단독이면 설정의 받은 파일 폴더", wr.download_dir() == st.download_dir_choice() == os.path.join(TMP, "받은것"), wr.download_dir())
cfg = st.read_settings()
cfg["prepare"]["download_dir"] = "Q:\\없는드라이브\\x"
st.write_settings(cfg)
e = raises(RuntimeError, wr.download_dir)
check("download_dir_bad: 만들 수 없는 폴더면 RuntimeError (Review Focus 5)", e is not None and str(e).startswith("받은 파일 폴더를 만들 수 없습니다: "), e)
st.write_user_config({"LogIn": {"AdminCode": "", "ID": "", "PW": ""}, "Sites": {}})
rc = wr.cmd_run(None, True)
rows = st.read_history()
check("download_dir_bad: 실행은 트레이스백 없이 '중단' 으로 기록되고 끝난다 (관제 기록에 글이 보인다)", rc == 1 and rows and rows[0]["state"] == "stopped"
      and rows[0]["reason"].startswith("받은 파일 폴더를 만들 수 없습니다: "), (rc, [r.get("reason") for r in rows[:1]]))
cfg = st.read_settings()
cfg["prepare"]["download_dir"] = os.path.join(TMP, "받은것")
st.write_settings(cfg)
os.environ.pop("RPA_STATUS_DIR", None)

OTP_SITE ={"URL": "https://shop.example.com", "ID": "a", "PW": "b", "Action": ["replay"], "Stts": 0, "Preset": 1, "Code": "012"}
_read = st.read_presets
st.read_presets = lambda: [{"no": 1, "name": "인증몰", "code": "012", "saved_at": None,
                            "record": {"version": 1, "start_url": "https://shop.example.com", "steps": [
                                {"kind": "click", "page": 0, "otpSend": True}, {"kind": "otp", "page": 0}, {"kind": "click", "page": 0}]}},
                           st.blank_preset(2)]
on(False)
probs = wr._replay_problems("PRESET1", OTP_SITE)
check("no_phone_needed: 꺼지면 휴대폰 문제 글 그대로", len(probs) == 1 and "인증 휴대폰·발신번호" in probs[0], probs)
on(True)
probs = wr._replay_problems("PRESET1", OTP_SITE)
check("no_phone_needed: 단독이면 휴대폰 없이도 통과", probs == [], probs)
st.read_presets = _read
on(False)

print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
