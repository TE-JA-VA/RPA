# update_helper.py
# -*- coding: utf-8 -*-
"""자동 업데이트 도우미 (설계 7절). 프로그램 폴더 밖 %ProgramData%\\AFTER MARKET\\RPA\\update\\runner 에서
복사한 파이썬으로 돈다 - 일회용 예약 작업 '\\AFTER MARKET\\RPA Update' 가 띄운다 (지금 한 번 + 로그온 때마다).

    state.json  ready          → apply  (보관 → 바꾸기 → 에이전트 켜기 → 3분 점검 → 성공 / 되돌리기)
                applying       → rollback (바꾸는 도중 끊겼다 - 정전·재부팅)
                rolling_back   → rollback (되돌리는 도중 끊겼다 - 이어서)
                그 밖           → 할 일 없음
    끝나면 예약 작업을 지운다.

되돌리기는 몇 번을 다시 해도 같은 결과다 (옮기기 하나하나가 끊겨도 된다):
  보관(backup_new)에 있는 파일 → 제자리로, 새로 생긴 파일(plan.new) 중 보관에 없는 것 → 지운다."""
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rpa_status as st  # noqa: E402
import rpa_update as up  # noqa: E402

HEALTH_WAIT_SEC = up.HEALTH_WAIT_SEC
HEALTH_POLL_SEC = 2
AGENT_TASK = r"AFTER MARKET\RPA Agent"
HELPER_TASK = r"AFTER MARKET\RPA Update"
AGENT_MUTEX = r"Local\AFTER_MARKET_RPA_AGENT"
UNINSTALL_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{C3F7A2B4-5E81-4D2A-9B6C-7A1E0F3D8B52}_is1"
CREATE_NO_WINDOW = 0x08000000


def _move(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    os.replace(src, dst)


def _full(root, rel):
    return os.path.join(root, *rel.split("/"))


class Ops:
    """진짜 동작 - 시험은 같은 이름의 가짜를 넘긴다."""

    def _run(self, args, timeout=120):
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout, creationflags=CREATE_NO_WINDOW).returncode

    def end_agent(self):
        self._run(["schtasks", "/End", "/TN", AGENT_TASK])
        until = time.monotonic() + 30
        while st.lock_held(AGENT_MUTEX) and time.monotonic() < until:
            time.sleep(0.5)

    def after_install(self, program_dir):
        py = os.path.join(program_dir, "python", "pythonw.exe")
        return self._run([py, os.path.join(program_dir, "rpa_settings.py"), "--after-install", "--no-window"], timeout=300)

    def set_display_version(self, version):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, UNINSTALL_KEY, 0, winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
                winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ, version)
        except OSError:
            pass                                 # 제거 목록 글자일 뿐 - 업데이트를 막지 않는다

    def delete_helper_task(self):
        self._run(["schtasks", "/Delete", "/TN", HELPER_TASK, "/F"])

    def sleep(self, sec):
        time.sleep(sec)


def _plan(state):
    with open(os.path.join(state["staging"], "plan.json"), encoding="utf-8") as f:
        return json.load(f)


def wait_alive(version, since, ops):
    until = time.monotonic() + HEALTH_WAIT_SEC
    while True:
        a = st.read_json(up.path("alive.json")) or {}
        if a.get("version") == version and a.get("state") == "ok" and str(a.get("at") or "") >= since:
            return True
        if time.monotonic() >= until:
            return False
        ops.sleep(HEALTH_POLL_SEC)


def _copy_atomic(src, dst):
    """임시 파일에 복사한 뒤 바꿔 놓는다 - 끊겨도 dst 는 옛 것 아니면 온전한 새 것."""
    tmp = dst + ".tmp"
    shutil.copy2(src, tmp)
    os.replace(tmp, dst)


def restore(program_dir, backup_new, plan):
    for rel in plan["fetch"] + plan["remove"]:
        b = _full(os.path.join(backup_new, "files"), rel)
        if os.path.isfile(b):
            _move(b, _full(program_dir, rel))
        elif rel in plan["new"] and os.path.isfile(_full(program_dir, rel)):
            os.remove(_full(program_dir, rel))
    old_man = os.path.join(backup_new, st.MANIFEST_NAME)
    if os.path.isfile(old_man):
        _copy_atomic(old_man, os.path.join(program_dir, st.MANIFEST_NAME))


def finish_cleanup(state):
    """성공(done) 뒤 정리 - 몇 번을 다시 해도 같다. done 을 먼저 적은 뒤 하므로 끊겨도 다음 실행이 마저 한다."""
    bnew = up.path("backup_new")
    if os.path.isdir(bnew):
        shutil.rmtree(up.path("backup"), ignore_errors=True)
        os.replace(bnew, up.path("backup"))
    shutil.rmtree(state.get("staging") or up.path("staging"), ignore_errors=True)
    try:
        os.remove(up.path("alive.json"))
    except OSError:
        pass


def apply(state, ops):
    prog, stg, bnew = state["program_dir"], state["staging"], up.path("backup_new")
    plan = _plan(state)
    shutil.rmtree(bnew, ignore_errors=True)                   # 'applying' 을 적기 전에 - 끊긴 뒤 되돌리기가 남의 보관을 쓰지 않게
    try:
        os.remove(up.path("alive.json"))
    except OSError:
        pass
    started = up.now_text()
    state = {**state, "state": "applying", "started_at": started, "at": started}
    up.write_state(state)
    up.log(f"바꾸기 시작 {state['from']} → {state['target']} ({state.get('mode')}) 받을 {len(plan['fetch'])}·치울 {len(plan['remove'])}")
    try:
        ops.end_agent()
        os.makedirs(os.path.join(bnew, "files"), exist_ok=True)
        _copy_atomic(os.path.join(prog, st.MANIFEST_NAME), os.path.join(bnew, st.MANIFEST_NAME))
        for rel in plan["fetch"] + plan["remove"]:
            if os.path.isfile(_full(prog, rel)):
                _move(_full(prog, rel), _full(os.path.join(bnew, "files"), rel))
        for rel in plan["fetch"]:
            _move(_full(os.path.join(stg, "files"), rel), _full(prog, rel))
        _copy_atomic(os.path.join(stg, "manifest.json"), os.path.join(prog, st.MANIFEST_NAME))
        ops.set_display_version(state["target"])
        ops.after_install(prog)
        alive = wait_alive(state["target"], started, ops)
    except Exception as e:                                    # 잠긴 파일·디스크 가득 등 - 끊김(BaseException)이 아닌 보통 오류
        up.log(f"바꾸는 중 오류 {type(e).__name__}: {e}"[:300])
        return rollback(state, ops, f"바꾸는 중 오류 ({type(e).__name__})")
    if not alive:
        return rollback(state, ops, f"새 판이 3분 안에 정상으로 켜지지 않았습니다 ({state['target']})")
    done = {"state": "done", "mode": state.get("mode"), "target": state["target"], "from": state["from"],
            "at": up.now_text(), "reason": None, "staging": stg}
    up.write_state(done)                                      # 확정 - 여기부터 끊겨도 되돌리지 않고 정리만 마저 한다
    finish_cleanup(done)
    up.write_state({**done, "staging": None})
    up.log(f"성공 {state['target']}")
    return 0


def rollback(state, ops, reason):
    prog, bnew = state["program_dir"], up.path("backup_new")
    started = up.now_text()
    state = {**state, "state": "rolling_back", "reason": reason, "at": started}
    up.write_state(state)
    up.log(f"되돌리기: {reason}")
    err = None
    try:
        ops.end_agent()
        try:
            plan = _plan(state)
        except Exception:
            plan = None                          # staging 이 없다 = 아직 아무것도 안 옮겼다
        if plan is not None:
            restore(prog, bnew, plan)
        ops.set_display_version(state["from"])
        ops.after_install(prog)
        ok = wait_alive(state["from"], started, ops)
    except Exception as e:                       # 되돌리기도 실패 - 되풀이하지 말고 남기고 멈춘다
        up.log(f"되돌리기 오류 {type(e).__name__}: {e}"[:300])
        ok, err = False, e
    if err is None:
        shutil.rmtree(bnew, ignore_errors=True)
        shutil.rmtree(state.get("staging") or up.path("staging"), ignore_errors=True)
    final = reason if ok else f"{reason} / 옛 판도 정상으로 켜지지 않았습니다 - 설치 파일로 다시 설치하세요"
    up.write_state({"state": "rolled_back", "mode": state.get("mode"), "target": state["target"], "from": state["from"],
                    "at": up.now_text(), "reason": final})
    up.log(f"되돌림 끝 ({'옛 판 정상' if ok else '옛 판도 점검 실패'})")
    return 0


def main(ops=None):
    ops = ops or Ops()
    state = up.read_state()
    errored = False
    try:
        if state.get("state") == "ready":
            apply(state, ops)
        elif state.get("state") == "applying":
            rollback(state, ops, "업데이트 도중 끊겼습니다 (정전·재부팅 등)")
        elif state.get("state") == "rolling_back":
            rollback(state, ops, state.get("reason") or "되돌리는 도중 끊겼습니다")
        elif state.get("state") == "done":
            finish_cleanup(state)                # 성공을 적은 뒤 정리가 끊겼다면 마저 한다
            if state.get("staging"):
                up.write_state({**state, "staging": None})
    except Exception as e:                       # 시작도 못 한 보통 오류 (staging 없음 등) - 매 로그온마다 되풀이하지 않는다
        errored = True
        up.log(f"도우미 오류 {type(e).__name__}: {e}"[:300])
        if up.read_state().get("state") == "ready":
            try:
                up.write_state({**state, "state": "rolled_back", "at": up.now_text(), "reason": f"업데이트를 시작하지 못했습니다 ({type(e).__name__})"})
            except Exception as e2:
                up.log(f"상태를 못 적음: {e2}")  # ready 로 남는다 - 작업을 지우지 않고 다음 로그온에 다시 해 본다
    now = up.read_state().get("state")
    # 끊긴 상태 · 정리가 덜 끝난 done · 못 적고 남은 ready 는 작업을 남겨 다음 로그온에 마저 한다
    if now not in ("applying", "rolling_back") and not (errored and now in ("done", "ready")):
        ops.delete_helper_task()                 # 끊김(BaseException)은 여기까지 안 온다 - 작업이 남아 다음 로그온에 다시 뜬다
    return 0


if __name__ == "__main__":
    sys.exit(main())
