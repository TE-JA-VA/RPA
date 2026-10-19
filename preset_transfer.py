"""프리셋 파일(autopilot-preset)·받는 PC 가 바꾸는 법·되돌리기 - 에이전트(export/import/restore_preset 명령)와
옵저버([파일에서 불러오기]·[파일로 내보내기])가 같이 쓴다. 설계 docs/superpowers/specs/2026-10-19-preset-transfer-design.md 4.4·6절.

지키는 선: 파일에는 이름·사이트코드·기록만. 아이디·비밀번호·로그인 세션은 어떤 경로로도 PC 밖으로 안 나간다.
인증 휴대폰(phone·senders)은 업체 안 PC 끼리 복사(with_phone)에서만 따라간다.
"""
import datetime
import json
import os

import rpa_status as st
import web_replay

FILE_KIND = "autopilot-preset"
FILE_VERSION = 1
LOGIN_KEYS = ("id", "pw", "ID", "PW")        # 파일에 있으면 안 되는 칸
backup_path = st.preset_backup_path


def export_item(no, with_phone=False, source=None):
    """프리셋 no 를 파일 모양 dict 로. 빈 칸이면 ValueError. with_phone 이면 Sites 의 Phone·SmsSenders 를 phone·senders 로."""
    p = next((p for p in st.read_presets() if p["no"] == no), None)
    if not p or not p.get("record"):
        raise ValueError(f"프리셋 {no}에 기록이 없습니다.")
    item = {"kind": FILE_KIND, "version": FILE_VERSION, "exported_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "from": source or {}, "no": no, "name": p["name"], "code": p["code"], "record": p["record"]}
    if with_phone:
        site = _sites().get(st.preset_site_key(no))
        site = site if isinstance(site, dict) else {}
        item["phone"] = site.get("Phone") or ""
        item["senders"] = list(site.get("SmsSenders") or [])
    return item


def check_file(obj):
    """파일 모양 검사. 통과하면 obj 그대로, 틀리면 ValueError(한국어 사유).
    값이 든 비밀번호 단계·아이디·비밀번호 칸이 있으면 받지 않는다 (손으로 고친 파일이 비밀번호를 실어 오지 않게)."""
    if not isinstance(obj, dict):
        raise ValueError("프리셋 파일 형식이 아닙니다.")
    if obj.get("kind") != FILE_KIND or obj.get("version") != FILE_VERSION:
        raise ValueError("오토파일럿 프리셋 파일이 아니거나 버전이 다릅니다.")
    if any(k in obj for k in LOGIN_KEYS):
        raise ValueError("아이디·비밀번호가 든 파일은 받지 않습니다.")
    if not isinstance(obj.get("name"), str) or not isinstance(obj.get("code"), str):
        raise ValueError("프리셋 이름·사이트코드가 올바르지 않습니다.")
    rec = obj.get("record")
    if not isinstance(rec, dict) or not isinstance(rec.get("steps"), list):
        raise ValueError("기록 형식이 올바르지 않습니다.")
    if rec.get("version") != web_replay.RECORD_VERSION:
        raise ValueError(f"기록 버전이 다릅니다. ({rec.get('version')} - 이 버전은 {web_replay.RECORD_VERSION})")
    for s in rec["steps"]:
        if not isinstance(s, dict):
            raise ValueError("기록 단계 형식이 올바르지 않습니다.")
        if (s.get("kind") == "secret" or s.get("credential") == "PW") and s.get("value"):
            raise ValueError("비밀번호 값이 든 기록은 받지 않습니다.")
    return obj


def _sites():
    cfg = st.read_user_config()
    sites = cfg.get(st.SITES_SECTION) if isinstance(cfg.get(st.SITES_SECTION), dict) else {}
    return sites


def _write_backup(no, preset, site):
    path = backup_path(no)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    st.write_json_atomic(path, {"preset": preset, "site": site})


def apply(items):
    """[(파일 dict, 칸 번호)] 를 넣는다. 칸마다 따로 성공/거절 → (넣은 칸들, [(칸, 사유)]).
    바꾸기 전 것(기록이 있던 칸)은 backup_path(칸) 에 하나 보관. 같은 사이트코드면 그 칸의 아이디·비밀번호·휴대폰·켬/끔 그대로,
    다르면(빈 칸 포함) 지우고 꺼짐. 파일·설정은 끝에 한 번씩 쓴다 (st.save_preset_sites 는 빈 비밀번호로 지울 수 없어 안 쓴다)."""
    presets = st.read_presets()
    cfg = st.read_user_config()
    if not cfg:
        raise FileNotFoundError(st.user_config_path())
    sites = cfg.get(st.SITES_SECTION) if isinstance(cfg.get(st.SITES_SECTION), dict) else {}
    limit = st.preset_limit()
    done, rejected = [], []
    now = datetime.datetime.now().isoformat(timespec="seconds")
    for obj, no in items:
        try:
            check_file(obj)
        except ValueError as e:
            rejected.append((no, str(e)))
            continue
        if not isinstance(no, int) or no < 1 or no > limit:
            rejected.append((no, f"프리셋 수({limit}개)를 넘는 칸입니다."))
            continue
        clash = next((p["no"] for p in presets if p["no"] != no and p.get("record") and p["code"] == obj["code"]), None)
        if clash is not None:
            rejected.append((no, f"프리셋 {clash}와(과) 같은 사이트코드 {obj['code']}를 사용합니다."))
            continue
        while len(presets) < no:
            presets.append(st.blank_preset(len(presets) + 1))
        old = presets[no - 1]
        key = st.preset_site_key(no)
        old_site = sites.get(key) if isinstance(sites.get(key), dict) else None
        if old.get("record"):
            _write_backup(no, old, old_site)
        presets[no - 1] = {"no": no, "name": obj["name"], "code": obj["code"], "saved_at": now, "record": obj["record"]}
        url = obj["record"].get("start_url") or ""
        if old.get("record") and old_site and old["code"] == obj["code"]:
            sites[key] = dict(old_site, URL=url or old_site.get("URL", ""), note=obj["name"], Preset=no)
        else:
            sites[key] = {"URL": url, "ID": "", "PW": "", "Action": [st.REPLAY_ACTION], "Stts": 9, "Preset": no, "note": obj["name"]}
            if obj.get("phone") and obj.get("senders"):
                sites[key].update(Phone=obj["phone"], SmsSenders=list(obj["senders"]))
        done.append(no)
    if done:
        st.write_presets(presets)
        cfg[st.SITES_SECTION] = sites
        st.write_user_config(cfg)
    return done, rejected


def restore(slots):
    """보관된 이전 기록으로 돌린다 → (돌린 칸들, [(칸, 사유)]). 돌린 보관은 지운다 (되풀이 되돌리기 없음)."""
    presets = st.read_presets()
    cfg = st.read_user_config()
    if not cfg:
        raise FileNotFoundError(st.user_config_path())
    sites = cfg.get(st.SITES_SECTION) if isinstance(cfg.get(st.SITES_SECTION), dict) else {}
    done, rejected, used = [], [], []
    for no in slots:
        path = backup_path(no)
        bk = st.read_json(path) if os.path.isfile(path) else None
        if not isinstance(bk, dict) or not isinstance(bk.get("preset"), dict):
            rejected.append((no, "보관된 이전 기록이 없습니다."))
            continue
        while len(presets) < no:
            presets.append(st.blank_preset(len(presets) + 1))
        presets[no - 1] = dict(bk["preset"], no=no)
        key = st.preset_site_key(no)
        if isinstance(bk.get("site"), dict):
            sites[key] = bk["site"]
        else:
            sites.pop(key, None)
        done.append(no)
        used.append(path)
    if done:
        st.write_presets(presets)
        cfg[st.SITES_SECTION] = sites
        st.write_user_config(cfg)
        for path in used:
            try:
                os.remove(path)
            except OSError:
                pass
    return done, rejected
