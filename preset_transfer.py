"""프리셋 파일(autopilot-preset)·받는 PC 가 바꾸는 법·되돌리기 - 에이전트(export/import/restore_preset 명령)와
옵저버([파일에서 불러오기]·[파일로 내보내기])가 같이 쓴다. 설계 docs/superpowers/specs/2026-10-19-preset-transfer-design.md 4.4·6절.

지키는 선: 파일에는 이름·사이트코드·기록만. 아이디·비밀번호·로그인 세션은 어떤 경로로도 PC 밖으로 안 나간다.
인증 휴대폰(phone·senders)은 업체 안 PC 끼리 복사(with_phone)에서만 따라간다.
"""
import datetime
import json
import os
import re

import rpa_status as st

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
    if not re.fullmatch(r"\d{3}", obj["code"]):      # 옵저버 validate_presets 와 같은 규칙 (빈 코드는 read_presets 가 빈 칸과 겹친다고 본다)
        raise ValueError("사이트코드는 숫자 세 자리여야 합니다.")
    rec = obj.get("record")
    if not isinstance(rec, dict) or not isinstance(rec.get("steps"), list):
        raise ValueError("기록 형식이 올바르지 않습니다.")
    if rec.get("version") != st.RECORD_VERSION:
        raise ValueError(f"기록 버전이 다릅니다. (파일 {rec.get('version')}, 이 PC {st.RECORD_VERSION})")
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


def _code_clash(presets, no, code):
    """칸 no 에 code 를 넣으면 read_presets 가 거절하는 상태가 되는지. 겹치면 사유 글, 아니면 None."""
    k = next((p["no"] for p in presets if p["no"] != no and p.get("record") and p["code"] == code), None)
    return None if k is None else f"프리셋 {k}와(과) 같은 사이트코드 {code}를 사용합니다."


def _write_backup(no, preset, site):
    """보관 파일을 쓴다 → 됐나. 못 쓰면 그 칸은 바꾸지 않는다 (되돌릴 수 없는 변경을 만들지 않게)."""
    path = backup_path(no)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except OSError:
        return False
    return st.write_json_atomic(path, {"preset": preset, "site": site})


def _drop_backup(no):
    _remove(backup_path(no))


def _bad_slots(nos, limit):
    """칸 번호 검사 → 칸마다 사유 또는 None (nos 와 같은 순서). 정수(bool 제외)·1~limit, 한 번에 같은 칸이 둘이면 둘 다 거절."""
    dup = [n for n in nos if nos.count(n) > 1]
    out = []
    for no in nos:
        if type(no) is not int:
            out.append("프리셋 번호가 올바르지 않습니다.")
        elif no in dup:
            out.append("받을 프리셋 번호가 중복되어 있습니다.")
        elif no < 1 or no > limit:
            out.append(f"프리셋 수({limit}개)를 넘는 칸입니다.")
        else:
            out.append(None)
    return out


def _ordered(sites):
    """PRESETn 칸을 번호 순으로 뒤에 (save_preset_sites 와 같은 순서 - ACTOR 는 dict 순서대로 돈다)."""
    others = {k: v for k, v in sites.items() if not st.is_preset_site(k)}
    mine = sorted((k for k in sites if st.is_preset_site(k)), key=lambda k: int(k[len("PRESET"):]))
    return {**others, **{k: sites[k] for k in mine}}


def move_preset_files(origs, dropped):
    """프리셋 번호에 묶인 파일(메일 기억·로그인 세션·보관)을 옵저버가 지워 당겨진 번호에 맞춘다 (이슈 #13).
    origs: {새 번호: 옛 번호}, dropped: 지운 옛 번호들. 지울 것을 먼저 지우고 새 번호 오름차순으로 옮긴다 - 당기기만 하므로
    (새 ≤ 옛) 늘 비운 자리로만 간다. 설정·프리셋 파일을 쓴 뒤에 부른다 (못 옮기면 옛 번호 것을 지운다 - 다른 프리셋 것이 섞이지 않게)."""
    def paths(no):
        return st.mail_memory_path(no), st.session_path(st.preset_site_key(no)), backup_path(no)

    for no in dropped:
        for p in paths(no):
            _remove(p)
    for new, old in sorted(origs.items()):
        if old is None or new == old:        # None = 새 칸
            continue
        for src, dst in zip(paths(old), paths(new)):
            if os.path.isfile(src):
                try:
                    os.replace(src, dst)
                except OSError:
                    _remove(src)


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _write_all(cfg, sites, presets):
    """설정 먼저, 프리셋 뒤 - 설정 쓰기가 실패해도 '새 기록 + 옛 아이디·비밀번호' 가 남지 않게."""
    cfg[st.SITES_SECTION] = _ordered(sites)
    st.write_user_config(cfg)
    st.write_presets(presets)


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
    for (obj, no), bad in zip(items, _bad_slots([no for _, no in items], limit)):
        if bad:
            rejected.append((no, bad))
            continue
        try:
            check_file(obj)
        except ValueError as e:
            rejected.append((no, str(e)))
            continue
        clash = _code_clash(presets, no, obj["code"])
        if clash:
            rejected.append((no, clash))
            continue
        old = presets[no - 1] if no <= len(presets) else st.blank_preset(no)
        key = st.preset_site_key(no)
        old_site = sites.get(key) if isinstance(sites.get(key), dict) else None
        if old.get("record"):
            if not _write_backup(no, old, old_site):
                rejected.append((no, "이전 기록을 보관하지 못해 변경하지 않았습니다."))
                continue
        else:
            _drop_backup(no)            # 남아 있던 옛 보관 - [되돌리기]가 방금 넣은 것을 버리고 옛 계정을 되살리지 않게
        while len(presets) < no:
            presets.append(st.blank_preset(len(presets) + 1))
        presets[no - 1] = {"no": no, "name": obj["name"], "code": obj["code"], "saved_at": now, "record": obj["record"]}
        url = obj["record"].get("start_url") or ""
        # 같은 사이트라도 짝이 이미 깨진 칸(계정 Code 가 다름)은 계정을 두지 않는다 - 새 Code 로 덮어 세탁하지 않게 (이슈 #13 다시 검토)
        if old.get("record") and old_site and old["code"] == obj["code"] and not st.login_mismatch(old_site, old["code"]):
            sites[key] = dict(old_site, URL=url or old_site.get("URL", ""), note=obj["name"], Preset=no, Code=obj["code"])
        else:
            sites[key] = {"URL": url, "ID": "", "PW": "", "Action": [st.REPLAY_ACTION], "Stts": 9, "Preset": no, "Code": obj["code"], "note": obj["name"]}
            if obj.get("phone") and obj.get("senders"):
                sites[key].update(Phone=obj["phone"], SmsSenders=list(obj["senders"]))
        done.append(no)
    if done:
        _write_all(cfg, sites, presets)
    return done, rejected


def restore(slots):
    """보관된 이전 기록으로 돌린다 → (돌린 칸들, [(칸, 사유)]). 돌린 보관은 지운다 (되풀이 되돌리기 없음)."""
    presets = st.read_presets()
    cfg = st.read_user_config()
    if not cfg:
        raise FileNotFoundError(st.user_config_path())
    sites = cfg.get(st.SITES_SECTION) if isinstance(cfg.get(st.SITES_SECTION), dict) else {}
    done, rejected, used = [], [], []
    for no, bad in zip(slots, _bad_slots(list(slots), st.PRESET_MAX)):
        if bad:
            rejected.append((no, bad))
            continue
        path = backup_path(no)
        bk = st.read_json(path) if os.path.isfile(path) else None
        if not isinstance(bk, dict) or not isinstance(bk.get("preset"), dict):
            rejected.append((no, "보관된 이전 기록이 없습니다."))
            continue
        clash = _code_clash(presets, no, bk["preset"].get("code")) if bk["preset"].get("record") else None
        if clash:                     # 다른 칸으로 옮긴 뒤 되돌리면 겹친다 - 보관은 남겨 둔다
            rejected.append((no, clash))
            continue
        while len(presets) < no:
            presets.append(st.blank_preset(len(presets) + 1))
        presets[no - 1] = dict(bk["preset"], no=no)
        key = st.preset_site_key(no)
        if isinstance(bk.get("site"), dict):     # 번호는 돌린 칸 기준 - 옵저버가 보관 파일을 다른 번호로 옮겼을 수 있다 (이슈 #13 검토).
            # Code 는 보관본에 적힌 것 그대로 (보관할 때 함께 담은 짝) - 깨진 짝을 되살려도 짝 확인에 걸린다. 없는 옛 보관만 보관 프리셋 code
            sites[key] = {"Code": str(bk["preset"].get("code") or ""), **bk["site"], "Preset": no}
        else:
            sites.pop(key, None)
        done.append(no)
        used.append(path)
    if done:
        _write_all(cfg, sites, presets)
        for path in used:
            try:
                os.remove(path)
            except OSError:
                pass
    return done, rejected
