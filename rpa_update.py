# rpa_update.py
# -*- coding: utf-8 -*-
"""자동 업데이트 PC 쪽 (설계 docs/superpowers/specs/2026-10-07-auto-update-design.md 6·7절).
에이전트(받기·대기·넘기기)와 도우미(update_helper.py, 바꾸기·되돌리기)가 같이 쓴다. 표준 라이브러리 + rpa_status 만.

폴더 %ProgramData%\\AFTER MARKET\\RPA\\update\\
  state.json        지금 상태 {state, target, from, mode, program_dir, staging, started_at, at, reason}
  alive.json        새 에이전트가 켜져 판 점검을 넘겼다 {version, state, at, pid} - 도우미의 3분 점검이 본다
  staging\\          받은 새 판 (manifest.json·plan.json·files\\…)
  backup\\           직전 판 (manifest.json·files\\…) - 늘 하나
  backup_new\\       바꾸는 동안의 보관 (성공하면 backup 이 된다, 되돌리면 지운다)
  runner\\           도우미와 그 파이썬 (프로그램 폴더 밖이라 새 판이 깨져도 돈다)
  업데이트_기록.txt  단계마다 한 줄
"""
import datetime
import hashlib
import json
import os
import shutil
import urllib.request

import rpa_status as st
import update_sign

UPDATE_BASE_URL = os.environ.get("RPA_UPDATE_BASE_URL") or "https://rpa-test-f02e0-releases.web.app"   # SFTP 로 옮기면 받기만 바꾼다
HEALTH_WAIT_SEC = 180
DISK_MARGIN = 200 * 1024 * 1024
BUSY_STATES = ("waiting", "ready", "applying", "rolling_back")
ACTIVE_STATES = ("downloading",) + BUSY_STATES
BUSY_TEXT = "업데이트 중이라 잠시 실행할 수 없습니다"


class UpdateError(Exception):
    """사람에게 보일 까닭 (한국어)."""


def update_dir():
    return os.path.join(st.install_root(), "update")


def path(*parts):
    return os.path.join(update_dir(), *parts)


def now_text():
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def read_state():
    v = st.read_json(path("state.json"))
    return v if isinstance(v, dict) else {}


def write_state(state):
    os.makedirs(update_dir(), exist_ok=True)
    st.write_json_atomic(path("state.json"), state)


def log(msg):
    try:
        os.makedirs(update_dir(), exist_ok=True)
        with open(path("업데이트_기록.txt"), "a", encoding="utf-8") as f:
            f.write(f"[{now_text()}] {msg}\n")
    except OSError:
        pass                                    # 기록 때문에 업데이트가 멈추면 안 된다


def busy_reason():
    return BUSY_TEXT if read_state().get("state") in BUSY_STATES else None


def plan_files(cur, new):
    """(받을 것, 치울 것, 새로 생기는 것) - 받을 것 = 지문이 다르거나 새로 생긴 파일."""
    fetch = sorted(r for r, d in new.items() if (cur.get(r) or {}).get("sha256") != d.get("sha256"))
    remove = sorted(r for r in cur if r not in new)
    return fetch, remove, sorted(r for r in fetch if r not in cur)


def http_get(url, timeout=60):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.read()
    except Exception as e:
        code = getattr(e, "code", None)
        raise UpdateError(f"받지 못했습니다: {url.rsplit('/', 1)[-1]} ({code or type(e).__name__})") from None


def _read_manifest(root):
    with open(os.path.join(root, st.MANIFEST_NAME), encoding="utf-8") as f:
        return json.load(f)


def _check_manifest(man, version=None):
    files = man.get("files") if isinstance(man, dict) else None
    if man.get("format") != st.MANIFEST_FORMAT or not isinstance(files, dict):
        raise UpdateError("판 목록 형식이 다릅니다")
    if version is not None and man.get("version") != version:
        raise UpdateError(f"요청한 판({version})과 판 목록의 판({man.get('version')})이 다릅니다")
    for rel, d in files.items():
        if not st.manifest_path_ok(rel) or not isinstance(d, dict):
            raise UpdateError(f"판 목록의 경로가 잘못되었습니다: {rel!r}")


def _write_plan(staging, version, cur_man, new_man, man_bytes):
    fetch, remove, new = plan_files(cur_man["files"], new_man["files"])
    with open(os.path.join(staging, "manifest.json"), "wb") as f:
        f.write(man_bytes)
    with open(os.path.join(staging, "plan.json"), "w", encoding="utf-8") as f:
        json.dump({"version": version, "from": cur_man.get("version"), "fetch": fetch, "remove": remove, "new": new}, f, ensure_ascii=False)
    return fetch, remove


def _need_bytes(cur_man, new_man, fetch, remove):
    new_sz = sum(int(new_man["files"][r].get("size") or 0) for r in fetch)
    old_sz = sum(int((cur_man["files"].get(r) or {}).get("size") or 0) for r in fetch + remove)
    return new_sz + old_sz + DISK_MARGIN


def fetch_release(version, program_root, staging, base_url=None, get=http_get, pub=None):
    """새 판의 manifest·서명을 받아 확인하고, 바뀐 파일만 staging 에 받는다. 틀리면 staging 을 지우고 UpdateError."""
    base = (base_url or UPDATE_BASE_URL).rstrip("/")
    shutil.rmtree(staging, ignore_errors=True)
    try:
        man_bytes = get(f"{base}/releases/{version}/manifest.json")
        sig = get(f"{base}/releases/{version}/manifest.sig")
        key = update_sign.public_key() if pub is None else pub
        try:
            sig_bytes = bytes.fromhex(sig.decode("ascii").strip())
        except Exception:
            sig_bytes = b""
        if not key or not update_sign.verify(key, man_bytes, sig_bytes):
            raise UpdateError("판 서명이 맞지 않습니다 - 받지 않습니다")
        new_man = json.loads(man_bytes.decode("utf-8"))
        _check_manifest(new_man, version)
        cur_man = _read_manifest(program_root)
        if (new_man.get("runtime") or {}) != (cur_man.get("runtime") or {}):
            raise UpdateError("파이썬이 바뀐 판입니다 - 설치 파일로 깔아야 합니다")
        fetch, remove, _ = plan_files(cur_man["files"], new_man["files"])
        os.makedirs(update_dir(), exist_ok=True)
        need = _need_bytes(cur_man, new_man, fetch, remove)
        free = shutil.disk_usage(update_dir()).free
        if free < need:
            raise UpdateError(f"디스크 여유가 모자랍니다 ({need // (1 << 20)}MB 필요, {free // (1 << 20)}MB 남음)")
        os.makedirs(os.path.join(staging, "files"), exist_ok=True)
        for rel in fetch:
            want = new_man["files"][rel]
            data = get(f"{base}/blobs/{want['sha256']}")
            size = want.get("size")
            if not isinstance(size, int) or len(data) != size or hashlib.sha256(data).hexdigest() != want["sha256"]:
                raise UpdateError(f"받은 파일이 판 목록과 다릅니다: {rel}")
            full = os.path.join(staging, "files", *rel.split("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "wb") as f:
                f.write(data)
        _write_plan(staging, version, cur_man, new_man, man_bytes)
        return new_man
    except UpdateError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateError(f"받기 실패 ({type(e).__name__}: {e})"[:200]) from None


def backup_version():
    try:
        return str(_read_manifest(path("backup")).get("version") or "") or None
    except Exception:
        return None


def stage_rollback(program_root, staging):
    """[이전 판으로 되돌리기]: 보관본을 staging 으로 복사한다 (보관본은 그대로 - 실패해도 남는다)."""
    shutil.rmtree(staging, ignore_errors=True)
    try:
        bman_path = path("backup", st.MANIFEST_NAME)
        with open(bman_path, "rb") as f:
            man_bytes = f.read()
        bman = json.loads(man_bytes.decode("utf-8"))
        _check_manifest(bman)
        cur_man = _read_manifest(program_root)
        fetch, remove, _ = plan_files(cur_man["files"], bman["files"])
        os.makedirs(os.path.join(staging, "files"), exist_ok=True)
        for rel in fetch:
            src = path("backup", "files", *rel.split("/"))
            if not os.path.isfile(src) or st.file_digest(src)["sha256"] != bman["files"][rel]["sha256"]:
                raise UpdateError(f"보관본에 {rel} 이(가) 없거나 다릅니다 - 되돌릴 수 없습니다")
            dst = os.path.join(staging, "files", *rel.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
        _write_plan(staging, bman.get("version"), cur_man, bman, man_bytes)
        return bman
    except UpdateError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateError(f"보관본을 읽지 못했습니다 ({type(e).__name__})") from None


def live_view():
    s, b = read_state(), backup_version()
    if not s and not b:
        return None
    return {"state": s.get("state"), "target": s.get("target"), "from": s.get("from"), "at": s.get("at"),
            "reason": s.get("reason"), "backup": b}


def health_local():
    """샌드박스 시험용: 로그인 없이 판 점검만으로 '살아 있음' - 표시 파일 update\\health_local (관리자·SYSTEM 만 쓰는 폴더).
    환경 변수가 아니라 파일인 까닭: 작업 스케줄러가 띄우는 에이전트는 새 기계 환경 변수를 늦게 받는다."""
    return os.path.isfile(path("health_local"))


def mark_alive(install):
    """새로 켜진 에이전트가 판 점검(과 첫 로그인)을 넘겼을 때 부른다. 업데이트 중이 아니면 아무것도 안 한다."""
    if read_state().get("state") not in ("applying", "rolling_back"):
        return False
    st.write_json_atomic(path("alive.json"), {"version": install.get("version"), "state": install.get("state"),
                                              "at": now_text(), "pid": os.getpid()})
    return True


import time  # noqa: E402  (run_update 의 sleep 기본값)

RUNNER_FILES = ("update_helper.py", "rpa_update.py", "rpa_status.py", "update_sign.py")


def handoff(program_root, state, register, run_task):
    """도우미와 파이썬을 runner 로 복사하고 state 를 ready 로 적은 뒤 도우미 작업을 등록·실행한다.
    파이썬(python\\)은 업데이트가 바꾸지 않는다 (판 목록 밖) - 그래서 지금 것을 복사해 써도 된다."""
    runner = path("runner")
    shutil.rmtree(runner, ignore_errors=True)
    shutil.copytree(os.path.join(program_root, "python"), os.path.join(runner, "python"))
    for name in RUNNER_FILES:
        shutil.copy2(os.path.join(program_root, name), os.path.join(runner, name))
    write_state({**state, "state": "ready", "at": now_text()})
    register(runner)
    run_task()


def run_update(version, mode, program_root, idle, register, run_task, fetch=fetch_release, sleep=time.sleep):
    """에이전트의 업데이트 스레드. idle(): RPA·옵저버가 쉬나 (에이전트가 실행 잠금 안에서 본다)."""
    staging = path("staging")
    try:
        cur = _read_manifest(program_root).get("version")
        write_state({"state": "downloading", "mode": mode, "target": version, "from": cur, "at": now_text()})
        log(f"{'받기' if mode == 'update' else '되돌리기 준비'} {cur} → {version}")
        if mode == "rollback":
            stage_rollback(program_root, staging)
        else:
            fetch(version, program_root, staging)
        write_state({"state": "waiting", "mode": mode, "target": version, "from": cur, "at": now_text()})
        while not idle():
            sleep(2)
        handoff(program_root, {"mode": mode, "target": version, "from": cur, "program_dir": program_root, "staging": staging},
                register, run_task)
        log("도우미에게 넘김")
    except Exception as e:
        reason = str(e) if isinstance(e, UpdateError) else f"도우미에게 넘기지 못했습니다 - 다시 [업데이트] 하세요"
        shutil.rmtree(staging, ignore_errors=True)
        write_state({"state": "failed", "mode": mode, "target": version, "from": read_state().get("from"),
                     "at": now_text(), "reason": reason})
        log(f"실패: {reason} [{type(e).__name__}: {e}]"[:300])


def clear_stale():
    """에이전트가 (다시) 켜질 때 부른다. 받기·대기는 에이전트 스레드만 이어 가므로, 에이전트가 끝났다면 영영 멈춘 것이다.
    도우미는 이 두 상태를 쓰지 않으니 정리해도 안전하다 (ready 이후는 도우미 몫이라 건드리지 않는다)."""
    s = read_state()
    if s.get("state") not in ("downloading", "waiting"):
        return False
    shutil.rmtree(path("staging"), ignore_errors=True)
    write_state({"state": "failed", "mode": s.get("mode"), "target": s.get("target"), "from": s.get("from"), "at": now_text(),
                 "reason": "에이전트가 다시 켜져 업데이트를 멈췄습니다 - 다시 [업데이트] 하세요"})
    log("다시 켜져 멈춘 업데이트를 정리")
    return True
