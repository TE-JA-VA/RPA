r"""판 내보내기 (자동 업데이트 설계 4절). 판을 빌드·샌드박스 시험한 뒤:

    .venv\Scripts\python.exe tools\publish_release.py --keygen                  (처음 한 번 - 비밀 열쇠 파일을 만들고 공개 열쇠를 알려 준다)
    .venv\Scripts\python.exe tools\publish_release.py 2026.10.07-5 "메모"        (서명·사이트 폴더·DB 목록·배포)
    .venv\Scripts\python.exe tools\publish_release.py 2026.10.07-5 --stable     (그 판을 안정본으로도)

배포(firebase deploy)는 사람이 확인한 뒤에 돈다 - 묻고 '예' 여야 한다. 비밀 열쇠는 firebase/admin/update_signing_key.txt 에만.
"""
import datetime
import json
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
import update_sign  # noqa: E402

KEY_PATH = os.path.join(REPO, "firebase", "admin", "update_signing_key.txt")
SITE_DIR = os.path.join(REPO, "firebase", "releases_site")
OUT_ROOT = r"D:\AX"
KEEP = 5


def keygen(key_path=KEY_PATH):
    if os.path.exists(key_path):
        raise FileExistsError(key_path)
    secret, public = update_sign.keygen()
    with open(key_path, "w", encoding="ascii") as f:
        f.write(secret.hex() + "\n")
    return public.hex()


def _secret(key_path):
    with open(key_path, encoding="ascii") as f:
        return bytes.fromhex(f.read().strip())


def publish(version, release_dir, site_dir, key_path, memo="", stable=None, deploy=None, set_releases=None,
            get_stable=None, set_stable=None):
    with open(os.path.join(release_dir, "manifest.json"), "rb") as f:
        man_bytes = f.read()
    man = json.loads(man_bytes.decode("utf-8"))
    if man.get("version") != version:
        raise ValueError(f"판 번호({version})와 배포 폴더의 판({man.get('version')})이 다릅니다")
    rel_dir = os.path.join(site_dir, "releases", version)
    os.makedirs(rel_dir, exist_ok=True)
    os.makedirs(os.path.join(site_dir, "blobs"), exist_ok=True)
    total = 0
    for rel, d in man["files"].items():
        dst = os.path.join(site_dir, "blobs", d["sha256"])
        if not os.path.isfile(dst) or os.path.getsize(dst) != int(d.get("size") or 0):   # 끊긴 복사가 남긴 잘린 파일도 다시
            shutil.copy2(os.path.join(release_dir, *rel.split("/")), dst + ".tmp")
            os.replace(dst + ".tmp", dst)
        total += int(d.get("size") or 0)
    with open(os.path.join(rel_dir, "manifest.json"), "wb") as f:
        f.write(man_bytes)                                       # 서명한 바이트 그대로
    with open(os.path.join(rel_dir, "manifest.sig"), "w", encoding="ascii") as f:
        f.write(update_sign.sign(_secret(key_path), man_bytes).hex() + "\n")
    info_path = os.path.join(site_dir, "published.json")         # 판마다 내보낸 시각·크기·메모 (releases.json 호스팅이 무시해 사이트에는 안 올라간다)
    info = json.load(open(info_path, encoding="utf-8")) if os.path.isfile(info_path) else {}
    info[version] = {"version": version, "published_at": datetime.datetime.now().isoformat(timespec="seconds"),
                     "bytes": total, "memo": memo}
    order = sorted(info, key=lambda v: (info[v]["published_at"], v))
    db_stable = get_stable() if get_stable else None                # 안정본은 DB 가 기준 (오래돼도 안 지운다)
    keep = set(order[-KEEP:]) | {x for x in (stable, db_stable) if x}
    removed = [v for v in order if v not in keep]
    for v in removed:
        shutil.rmtree(os.path.join(site_dir, "releases", v), ignore_errors=True)
        info.pop(v, None)
    used = set()
    for v in info:
        with open(os.path.join(site_dir, "releases", v, "manifest.json"), encoding="utf-8") as f:
            used |= {d["sha256"] for d in json.load(f)["files"].values()}
    for name in os.listdir(os.path.join(site_dir, "blobs")):
        if name not in used:
            os.remove(os.path.join(site_dir, "blobs", name))
    with open(info_path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=1)
    listing = [info[v] for v in sorted(info, key=lambda v: (info[v]["published_at"], v))]
    if deploy:
        deploy()                                                 # 배포가 먼저 - 실패하면 DB 목록은 그대로
    if set_releases:
        set_releases(listing)
    if stable and set_stable:
        set_stable(stable)
    return {"version": version, "kept": [x["version"] for x in listing], "removed": removed, "bytes": total}


def _node(*args):
    r = subprocess.run(["node", "setup.js", *args], cwd=os.path.join(REPO, "firebase", "admin"), capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(r.stdout + r.stderr)
    return r.stdout


def _set_releases(listing):
    path = os.path.join(SITE_DIR, "..", "releases_list.tmp.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(listing, f, ensure_ascii=False)
    try:
        _node("release-set", path)
    finally:
        os.remove(path)


def _get_stable():
    return json.loads(_node("releases").strip().splitlines()[-1]).get("stable")


def _set_stable(version):
    _node("stable", version)


def _deploy():
    if input("업데이트 전용 호스팅에 배포할까요? (예/아니오) ").strip() != "예":
        raise SystemExit("배포하지 않았습니다 (사이트 폴더만 바뀌었고 DB 목록은 그대로입니다 - 다음에 다시 내보내면 같이 올라갑니다)")
    subprocess.run(["firebase", "deploy", "--only", "hosting", "--config", "releases.json"], cwd=os.path.join(REPO, "firebase"), check=True, shell=True)


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args == ["--keygen"]:
        print("공개 열쇠 (update_sign.PUBLIC_KEY_HEX 에 넣는다):", keygen())
        print(f"비밀 열쇠는 {KEY_PATH} 에만 있습니다 - USB 등에 사본을 직접 보관하세요")
        return 0
    if not args:
        print(__doc__)
        return 2
    version, rest = args[0], args[1:]
    stable = version if "--stable" in rest else None
    memo = " ".join(x for x in rest if x != "--stable")
    r = publish(version, os.path.join(OUT_ROOT, f"배포_{version}"), SITE_DIR, KEY_PATH, memo=memo, stable=stable,
                deploy=_deploy, set_releases=_set_releases, get_stable=_get_stable, set_stable=_set_stable)
    print(f"내보냄 {r['version']} ({r['bytes'] // (1 << 20)}MB) · 남은 판 {', '.join(r['kept'])}" + (f" · 지운 판 {', '.join(r['removed'])}" if r["removed"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
