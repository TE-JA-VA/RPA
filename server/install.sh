#!/bin/sh
# install.sh - 오토파일럿 사내 서버(리눅스) 설치, 활성화, 업그레이드 (POSIX sh)
#
# 처음 설치 (root):
#   1. 공급사가 다른 길(메일과 전화 등)로 알려 준 SHA-256 을 먼저 맞춘다:
#        sha256sum AUTOPILOT_Server_<버전>_linux-x86_64.tar.gz
#   2. tar -xzf AUTOPILOT_Server_<버전>_linux-x86_64.tar.gz        (같은 폴더에 autopilot-server-<버전>/ 이 생긴다)
#   3. sh autopilot-server-<버전>/server/install.sh install --expect-sha256 <값> --listen <서버 사내 IP> --allow <PC 대역>[,<대역>]
#           [--names <이름>[,<이름>]] [--bundle <tar.gz 자리>] [--apply-firewall] [--yes]
#      라이선스 없이 끝난다. 화면에 나온 요청 파일(/var/lib/autopilot/server_request.json)을 공급사에 보낸다.
#   4. sh autopilot-server-<버전>/server/install.sh activate <받은 라이선스 파일>
#      서비스를 켜고 실제로 도는 버전을 확인한다. 관리자 계정이 없으면 만드는 순서를 보여 준다.
# 업그레이드 (root): autopilot-server upgrade <새 tar.gz>
#      깔린 도구가 새 파일의 서명을 먼저 확인한 뒤 그 안의 이 파일을 'upgrade --verified-version <버전>' 으로 부른다.
#
# 어느 단계에서 끊겨도(오류, Ctrl+C, kill) 그 단계까지 한 일을 되돌린다 (trap). 업그레이드는 current 링크를 바꾼 뒤 끊기거나
# 새 버전이 30초 안에 돌지 않으면 링크와 단위 파일을 되돌리고 옛 버전을 다시 켠다.
#
# 시험 전용 (WSL, tests/wsl_install.py):
#   --root <PREFIX>        모든 자리를 PREFIX 아래로. root 확인을 건너뛰고, systemctl·useradd·userdel·ufw·firewall-cmd 는
#                          AP_FAKE_BIN 의 가짜에서만 찾는다 (이 장비의 진짜 명령을 부르지 않는다)
#   --no-systemd           systemctl 을 부르지 않는다
#   --service-user <계정>  서비스 계정 (--root 와 함께만)
#   환경 변수 AP_START_WAIT(초, 기본 30), AP_MIN_FREE_MB(기본 2048), AP_TEST_DIE_AFTER_LINK=1(--root 에서만)
set -eu
umask 022
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

say() { printf '%s\n' "$*"; }
err() { printf 'install.sh: %s\n' "$*" >&2; }
die() { err "$*"; exit 1; }

SVC_DEFAULT=autopilotd
UNITS="autopilot.service autopilot-cert.service autopilot-cert.timer autopilot-config-backup.service autopilot-config-backup.timer"
KEEP_RELEASES=3
SYSTEMD_MIN=235
OPT_MIN_MB=500
PYMAIN='import sys; sys.path.insert(0, sys.argv.pop(1)); import server_main; sys.exit(server_main.main(sys.argv[1:]))'

usage() {
    sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'
}

HERE=$(cd "$(dirname "$0")" && pwd -P)
BUNDLE=$(dirname "$HERE")
BNAME=$(basename "$BUNDLE")
case "$BNAME" in
    autopilot-server-?*) V=${BNAME#autopilot-server-} ;;
    *) die "풀어 놓은 설치 파일 안(autopilot-server-<버전>/server/install.sh)에서 실행하여 주십시오." ;;
esac
case "$V" in
    *[!0-9A-Za-z._-]*) die "설치 파일 폴더 이름의 버전이 올바르지 않습니다: $V" ;;
esac

# ----------------------------------------------------------------------------------------------------
# 인자
# ----------------------------------------------------------------------------------------------------
CMD=${1:-}
if [ $# -gt 0 ]; then shift; fi
EXPECT=""; LISTEN=""; ALLOW=""; NAMES=""; BUNDLE_FILE=""; APPLY_FW=0; YES=0
ROOT=""; NOSD=0; SVC=$SVC_DEFAULT; SVC_SET=0; VERIFIED=""; LICENSE=""
needv() { if [ "$1" -lt 2 ]; then die "$2 에 값이 필요합니다."; fi; }
while [ $# -gt 0 ]; do
    case "$1" in
        --expect-sha256) needv $# "$1"; EXPECT=$2; shift 2 ;;
        --listen) needv $# "$1"; LISTEN=$2; shift 2 ;;
        --allow) needv $# "$1"; ALLOW=$2; shift 2 ;;
        --names) needv $# "$1"; NAMES=$2; shift 2 ;;
        --bundle) needv $# "$1"; BUNDLE_FILE=$2; shift 2 ;;
        --apply-firewall) APPLY_FW=1; shift ;;
        --yes) YES=1; shift ;;
        --root) needv $# "$1"; ROOT=$2; shift 2 ;;
        --no-systemd) NOSD=1; shift ;;
        --service-user) needv $# "$1"; SVC=$2; SVC_SET=1; shift 2 ;;
        --verified-version) needv $# "$1"; VERIFIED=$2; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        -*) die "모르는 인자입니다: $1 (sh install.sh --help)" ;;
        *)
            if [ "$CMD" = activate ] && [ -z "$LICENSE" ]; then LICENSE=$1; shift
            else die "모르는 인자입니다: $1 (sh install.sh --help)"; fi ;;
    esac
done
case "$CMD" in
    install|activate|upgrade) ;;
    -h|--help) usage; exit 0 ;;
    "") usage; exit 1 ;;
    *) die "모르는 명령입니다: $CMD (install, activate - 업그레이드는 autopilot-server upgrade)" ;;
esac
if [ -n "$ROOT" ]; then
    case "$ROOT" in
        /*) ;;
        *) die "--root 는 / 로 시작하는 시험 폴더여야 합니다." ;;
    esac
    case "$ROOT" in
        *[!A-Za-z0-9/._-]*) die "--root 의 폴더 이름에는 영문·숫자와 / . _ - 만 씁니다." ;;
    esac
    ROOT=${ROOT%/}
    if [ -z "$ROOT" ] || [ ! -d "$ROOT" ]; then die "--root 는 있는 시험 폴더여야 합니다 (/ 는 안 됩니다)."; fi
fi
if [ "$SVC_SET" = 1 ] && [ -z "$ROOT" ]; then die "--service-user 는 시험(--root)에서만 씁니다."; fi
case "$SVC" in
    ''|*[!a-z0-9_-]*) die "서비스 계정 이름이 올바르지 않습니다: $SVC" ;;
esac
WAIT=${AP_START_WAIT:-30}
MIN_FREE_MB=${AP_MIN_FREE_MB:-2048}
case "$WAIT" in ''|*[!0-9]*) die "AP_START_WAIT 은 초(숫자)입니다." ;; esac
case "$MIN_FREE_MB" in ''|*[!0-9]*) die "AP_MIN_FREE_MB 는 숫자입니다." ;; esac

OPT=$ROOT/opt/autopilot
REL=$OPT/releases
CUR=$OPT/current
ETC=$ROOT/etc/autopilot
DATA=$ROOT/var/lib/autopilot
LOGS=$ROOT/var/log/autopilot
BKP=$ROOT/var/backups/autopilot
UNITDIR=$ROOT/etc/systemd/system
SBIN=$ROOT/usr/local/sbin
AP=$SBIN/autopilot-server

if [ -n "$ROOT" ]; then
    AUTOPILOT_ROOT=$ROOT AUTOPILOT_ETC=$ETC AUTOPILOT_DATA=$DATA AUTOPILOT_LOGS=$LOGS AUTOPILOT_SERVICE_USER=$SVC
    export AUTOPILOT_ROOT AUTOPILOT_ETC AUTOPILOT_DATA AUTOPILOT_LOGS AUTOPILOT_SERVICE_USER
else
    unset AUTOPILOT_ROOT AUTOPILOT_ETC AUTOPILOT_DATA AUTOPILOT_LOGS AUTOPILOT_SERVICE_USER AUTOPILOT_NO_SYSTEMD
fi

# ----------------------------------------------------------------------------------------------------
# 도구
# ----------------------------------------------------------------------------------------------------
tool() {        # 바꾸는 시스템 명령의 자리 (없으면 빈 글). 시험(--root)에서는 AP_FAKE_BIN 의 가짜만
    if [ -n "$ROOT" ]; then
        if [ -n "${AP_FAKE_BIN:-}" ] && [ -x "$AP_FAKE_BIN/$1" ]; then printf '%s\n' "$AP_FAKE_BIN/$1"; fi
    else
        command -v "$1" 2>/dev/null || true
    fi
}
tool_ro() {     # 읽기만 하는 명령 (getent, openssl) - 시험에서도 가짜가 없으면 진짜
    if [ -n "$ROOT" ] && [ -n "${AP_FAKE_BIN:-}" ] && [ -x "$AP_FAKE_BIN/$1" ]; then
        printf '%s\n' "$AP_FAKE_BIN/$1"
    else
        command -v "$1" 2>/dev/null || true
    fi
}
sysd() {        # systemctl (--no-systemd 면 부르지 않는다)
    if [ "$NOSD" = 1 ]; then return 0; fi
    _s=$(tool systemctl)
    if [ -z "$_s" ]; then err "systemctl 을 찾지 못했습니다."; return 1; fi
    "$_s" "$@"
}
need_root() {
    if [ -z "$ROOT" ] && [ "$(id -u)" != 0 ]; then die "root 로 실행하여 주십시오 (sudo sh $0 $CMD ...)."; fi
}
HX=$BUNDLE      # 도우미·파이썬을 꺼낼 버전 폴더 (설치 파일 → 풀어 놓은 새 버전 → 설치된 버전)
H() {           # install_helper.py
    "$HX/python/bin/python3" -I -B "$HX/server/install_helper.py" "$@"
}
ap_rel() {      # 버전 폴더의 server_main (current 링크 전) - 실행 글과 같은 줄
    _r=$1; shift
    "$_r/python/bin/python3" -I -B -c "$PYMAIN" "$_r/app" "$@"
}

# ----------------------------------------------------------------------------------------------------
# 되돌리기 (trap)
# ----------------------------------------------------------------------------------------------------
UNDO=""         # 이번에 새로 만든 자리 (줄마다 하나) - 실패하면 지운다
MADE_USER=0
LINK_PREV=""    # 업그레이드: 바꾸기 전 current 링크 (비면 링크를 바꾸지 않았다)
UNITS_SAVED=""  # 업그레이드: 옛 단위 파일 사본 폴더
DONE=0
track() {
    for _p in "$@"; do
        if [ ! -e "$_p" ] && [ ! -L "$_p" ]; then
            UNDO="$_p
$UNDO"
        fi
    done
}
safe_rm() {     # 정해진 자리 안만 지운다
    case "$1" in
        "$OPT"|"$OPT"/*|"$ETC"|"$ETC"/*|"$DATA"|"$DATA"/*|"$LOGS"|"$LOGS"/*|"$BKP"|"$UNITDIR"/autopilot*|"$UNITDIR"/.autopilot*|"$AP"|"$SBIN"/.autopilot-server*)
            rm -rf "$1" ;;
        *) err "되돌리기: 정해진 자리 밖이라 지우지 않습니다 ($1)" ;;
    esac
}
write_launcher() {  # /usr/local/sbin/autopilot-server - 진짜는 current 의 실행 글에 링크, 시험(--root)은 자리를 바꾼 사본
    _tmp=$SBIN/.autopilot-server.new
    rm -f "$_tmp"
    if [ -z "$ROOT" ]; then
        ln -s /opt/autopilot/current/server/autopilot-server "$_tmp" || return 1
    else
        _exp="export AUTOPILOT_ROOT='$ROOT' AUTOPILOT_ETC='$ETC' AUTOPILOT_DATA='$DATA' AUTOPILOT_LOGS='$LOGS' AUTOPILOT_SERVICE_USER='$SVC'"
        sed -e "s#/opt/autopilot/current#$OPT/current#g" -e "s#^unset AUTOPILOT_.*\$#$_exp#" "$CUR/server/autopilot-server" > "$_tmp" || return 1
        grep -q "^export AUTOPILOT_ROOT=" "$_tmp" || return 1
        chmod 0755 "$_tmp" || return 1
    fi
    mv -f "$_tmp" "$AP"
}
restore_link() {
    rm -f "$OPT/.current.undo"
    ln -s "$LINK_PREV" "$OPT/.current.undo" && mv -T "$OPT/.current.undo" "$CUR"
}
undo() {
    set +e
    if [ -n "$LINK_PREV" ]; then
        if restore_link; then say "  current 를 ${LINK_PREV#releases/} 로 되돌렸습니다."
        else err "current 링크를 되돌리지 못했습니다 - $CUR 가 $LINK_PREV 를 가리키게 손으로 맞추어 주십시오."; fi
        if [ -n "$ROOT" ]; then write_launcher >/dev/null 2>&1; fi
    fi
    if [ -n "$UNITS_SAVED" ] && [ -d "$UNITS_SAVED" ]; then
        for _u in $UNITS; do
            if [ -f "$UNITS_SAVED/$_u" ]; then cp -p "$UNITS_SAVED/$_u" "$UNITDIR/$_u"; else rm -f "$UNITDIR/$_u"; fi
        done
        sysd daemon-reload >/dev/null 2>&1
        say "  systemd 단위 파일을 되돌렸습니다."
    fi
    if [ -n "$LINK_PREV" ] && [ "$NOSD" != 1 ]; then
        if sysd restart autopilot.service; then say "  옛 버전(${LINK_PREV#releases/})으로 서비스를 다시 켰습니다."
        else err "서비스를 다시 켜지 못했습니다: systemctl status autopilot"; fi
    fi
    printf '%s\n' "$UNDO" | while IFS= read -r _p; do
        if [ -n "$_p" ]; then safe_rm "$_p"; fi
    done
    if [ "$MADE_USER" = 1 ]; then
        _d=$(tool userdel)
        if [ -n "$_d" ]; then "$_d" "$SVC" && say "  만들었던 서비스 계정 $SVC 을(를) 지웠습니다."; fi
    fi
}
on_exit() {
    _rc=$?
    trap - EXIT INT TERM HUP
    if [ "$DONE" != 1 ]; then
        if [ "$_rc" = 0 ]; then _rc=1; fi
        err "멈췄습니다. 이 단계까지 한 일을 되돌립니다."
        undo
    fi
    exit "$_rc"
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

# ----------------------------------------------------------------------------------------------------
# 단계
# ----------------------------------------------------------------------------------------------------
check_sha() {
    _f=${BUNDLE_FILE:-$(dirname "$BUNDLE")/AUTOPILOT_Server_${V}_linux-x86_64.tar.gz}
    if [ ! -f "$_f" ]; then
        die "설치 파일을 찾지 못했습니다 ($_f) - 아무것도 하지 않았습니다. 받은 tar.gz 의 자리를 --bundle <파일> 로 알려 주십시오."
    fi
    _want=$(printf '%s' "$EXPECT" | tr 'A-F' 'a-f')
    case "$_want" in
        *[!0-9a-f]*|"") die "--expect-sha256 은 64자리 16진수입니다 - 아무것도 하지 않았습니다." ;;
    esac
    if [ "${#_want}" -ne 64 ]; then die "--expect-sha256 은 64자리 16진수입니다 - 아무것도 하지 않았습니다."; fi
    _got=$(sha256sum "$_f" | cut -d' ' -f1)
    if [ "$_got" != "$_want" ]; then
        die "설치 파일의 SHA-256 이 알려 준 값과 다릅니다 - 아무것도 하지 않았습니다. 파일을 다시 받고 공급사에 값을 다시 확인하여 주십시오. (이 파일: $_got)"
    fi
    BUNDLE_TAR=$_f
    say "설치 파일의 SHA-256 이 알려 준 값과 같습니다."
}

free_mb() {     # 자리(없으면 있는 위 폴더)의 남은 공간 MB
    _d=$1
    while [ ! -d "$_d" ]; do _d=$(dirname "$_d"); done
    df -Pk "$_d" | awk 'NR == 2 { print int($4 / 1024) }'
}

preflight() {   # 설치 전 점검 - 하나라도 안 되면 무엇이 모자란지 모두 적고 멈춘다
    _bad=""
    _a=$(uname -m)
    if [ "$_a" != x86_64 ]; then _bad="$_bad
  - CPU 종류가 x86_64 가 아닙니다 ($_a)."; fi
    if ! "$HX/python/bin/python3" -I -B -c pass >/dev/null 2>&1; then _bad="$_bad
  - 내장 파이썬이 이 서버에서 돌지 않습니다 (glibc 2.17 이상, x86-64 CPU 가 필요합니다)."; fi
    _o=$(tool_ro openssl)
    if [ -z "$_o" ] || ! "$_o" version >/dev/null 2>&1; then _bad="$_bad
  - openssl 명령이 없거나 돌지 않습니다 (배포판 설치 매체로 openssl 을 깔아 주십시오)."; fi
    _f=$(free_mb "$ROOT/var/lib")
    if [ "${_f:-0}" -lt "$MIN_FREE_MB" ]; then _bad="$_bad
  - /var 의 남은 공간이 ${_f:-?}MB 입니다 (${MIN_FREE_MB}MB 이상 - 자료, 백업 7개, 업그레이드 때 사본)."; fi
    _f=$(free_mb "$ROOT/opt")
    if [ "${_f:-0}" -lt "$OPT_MIN_MB" ]; then _bad="$_bad
  - /opt 의 남은 공간이 ${_f:-?}MB 입니다 (${OPT_MIN_MB}MB 이상 - 프로그램 최근 버전 셋)."; fi
    if [ "$NOSD" != 1 ]; then
        _s=$(tool systemctl)
        if [ -z "$_s" ]; then _bad="$_bad
  - systemd(systemctl)가 없습니다."
        else
            _sv=$("$_s" --version 2>/dev/null | sed -n '1s/^systemd \([0-9][0-9]*\).*/\1/p')
            if [ -z "$_sv" ] || [ "$_sv" -lt "$SYSTEMD_MIN" ]; then _bad="$_bad
  - systemd 버전이 낮습니다 (${_sv:-알 수 없음}, $SYSTEMD_MIN 이상 - 주소 제한 IPAddressDeny 등 보호 설정)."; fi
        fi
    fi
    if [ -n "$_bad" ]; then die "설치 전 점검에서 멈췄습니다 - 아무것도 하지 않았습니다.$_bad"; fi
}

CFG_JSON=""
check_config() {    # 설정 파일이 없으면 인자를 미리 검사해 글만 만들어 둔다 (아직 아무것도 쓰지 않는다)
    if [ -f "$ETC/server.json" ]; then
        H config-check "$ETC/server.json" || die "있는 설정 파일($ETC/server.json)이 올바르지 않습니다 - 아무것도 하지 않았습니다."
        say "있는 설정 파일을 그대로 씁니다 ($ETC/server.json)."
        return 0
    fi
    if [ -z "$LISTEN" ]; then die "--listen <서버의 사내 IP> 가 필요합니다."; fi
    if [ -z "$ALLOW" ]; then die "--allow <PC 들의 사내 대역> 이 필요합니다 (예: 192.168.1.0/24, 여럿이면 쉼표로)."; fi
    CFG_JSON=$(H config "$LISTEN" "$ALLOW" "$NAMES") || die "아무것도 하지 않았습니다."
}

SVC_UID=""; SVC_GID=""
svc_line() {
    _g=$(tool_ro getent)
    if [ -z "$_g" ]; then die "getent 를 찾지 못했습니다."; fi
    "$_g" passwd "$SVC" 2>/dev/null || true
}
set_ids() {
    SVC_UID=$(printf '%s' "$1" | cut -d: -f3)
    SVC_GID=$(printf '%s' "$1" | cut -d: -f4)
    case "$SVC_UID$SVC_GID" in ''|*[!0-9]*) die "서비스 계정 $SVC 의 번호를 읽지 못했습니다." ;; esac
}
ensure_account() {  # 서비스 계정 - 없으면 시스템 계정(로그인 불가, 집 없음)으로 만든다. 같은 이름의 사람 계정이 있으면 멈춘다
    _line=$(svc_line)
    if [ -n "$_line" ]; then
        _sh=${_line##*:}
        case "$_sh" in
            */nologin|*/false) ;;
            *) die "계정 $SVC 이(가) 이미 있는데 로그인할 수 있는 계정입니다 (셸 $_sh). 서비스 계정은 로그인할 수 없는 시스템 계정이어야 합니다 - 아무것도 하지 않았습니다." ;;
        esac
        say "서비스 계정 $SVC 이(가) 이미 있습니다 (로그인 불가 시스템 계정)."
    else
        _ua=$(tool useradd)
        if [ -z "$_ua" ]; then die "useradd 를 찾지 못했습니다 - 서비스 계정 $SVC 을(를) 만들 수 없습니다."; fi
        _nl=/sbin/nologin
        for _c in /usr/sbin/nologin /sbin/nologin; do
            if [ -x "$_c" ]; then _nl=$_c; break; fi
        done
        "$_ua" --system --no-create-home --home-dir /nonexistent --shell "$_nl" --user-group "$SVC" \
            || die "서비스 계정 $SVC 을(를) 만들지 못했습니다."
        MADE_USER=1
        _line=$(svc_line)
        if [ -z "$_line" ]; then die "만든 서비스 계정 $SVC 을(를) 찾지 못했습니다."; fi
        say "서비스 계정 $SVC 을(를) 만들었습니다 (로그인 불가 시스템 계정)."
    fi
    set_ids "$_line"
}
need_account() {    # 활성화·업그레이드 - 계정이 있어야 한다
    _line=$(svc_line)
    if [ -z "$_line" ]; then die "서비스 계정 $SVC 이(가) 없습니다 - 먼저 install.sh install 로 설치하여 주십시오."; fi
    set_ids "$_line"
}

mkd() {         # 자리 모드 소유자
    track "$1"
    mkdir -p "$1"
    chmod "$2" "$1"
    chown "$3" "$1"
}

finish_stage() {    # STAGE(풀어 놓은 새 버전)를 버전 목록과 대조하고 미리 컴파일한 뒤 releases/<버전> 으로
    HX=$STAGE
    H verify-tree "$STAGE" "$V" || die "설치 파일 안의 파일이 버전 목록과 맞지 않습니다."
    # -B: 컴파일하는 동안 불러온 표준 라이브러리의 .pyc 를 다시 쓰지 않는다 (app/ 의 .pyc 는 compileall 이 직접 쓴다).
    # 대조한 뒤의 프로그램 파일을 root 명령이 바꾸지 않게 - 풀어 놓은 설치 파일에서 파이썬을 부를 때는 늘 -B
    "$STAGE/python/bin/python3" -I -B -m compileall -q "$STAGE/app" >/dev/null || die "프로그램 파일을 미리 컴파일하지 못했습니다."
    chmod 0755 "$STAGE"
    track "$NEW"
    mv "$STAGE" "$NEW"
    touch "$NEW"
    HX=$NEW
}

write_config() {
    if [ -n "$CFG_JSON" ]; then
        track "$ETC/server.json" "$ETC/.server.json.new"
        printf '%s\n' "$CFG_JSON" > "$ETC/.server.json.new"
        chmod 0640 "$ETC/.server.json.new"
        chown "0:$SVC_GID" "$ETC/.server.json.new"
        mv -f "$ETC/.server.json.new" "$ETC/server.json"
        say "설정 파일을 만들었습니다 ($ETC/server.json)."
    fi
    chmod 0640 "$ETC/server.json"           # 비밀 값(proxy_secret)이 들어갈 수 있다 - root 와 서비스 계정 그룹만
    chown "0:$SVC_GID" "$ETC/server.json"
    if [ -f "$ETC/license.json" ]; then
        chmod 0640 "$ETC/license.json"
        chown "0:$SVC_GID" "$ETC/license.json"
    fi
}

install_units() {   # $1 = 새 버전의 server/ - @ALLOW@ 는 server.json 의 allow 로
    _allow=$(H config-get "$ETC/server.json" allow) || die "설정 파일에서 허용 대역을 읽지 못했습니다."
    for _u in $UNITS; do
        if [ ! -f "$1/$_u" ]; then die "설치 파일에 $_u 이(가) 없습니다."; fi
        track "$UNITDIR/$_u" "$UNITDIR/.$_u.new"
        sed -e "s#@ALLOW@#$_allow#g" -e "s#autopilotd#$SVC#g" "$1/$_u" > "$UNITDIR/.$_u.new"
        chmod 0644 "$UNITDIR/.$_u.new"
        mv -f "$UNITDIR/.$_u.new" "$UNITDIR/$_u"
    done
}

running_version() {     # 실제로 도는 프로세스가 알리는 버전 (run.json + 서비스 잠금 - autopilot-server status --json)
    "$AP" status --json 2>/dev/null | H running-version 2>/dev/null || true
}
wait_version() {        # $1 이 WAIT 초 안에 돌면 0
    _i=0
    while [ "$_i" -lt "$WAIT" ]; do
        if [ "$(running_version)" = "$1" ]; then return 0; fi
        sleep 1
        _i=$((_i + 1))
    done
    [ "$(running_version)" = "$1" ]
}

admin_hint() {
    if H admin-missing "$DATA/accounts.json"; then
        say ""
        say "관리자 계정이 아직 없습니다. 서비스를 멈춘 뒤 만들고 다시 켜 주십시오 (계정 파일은 서비스가 멈춘 동안에만 고칩니다):"
        say "  systemctl stop autopilot"
        say "  autopilot-server admin-reset admin --create        (새 비밀번호를 두 번 묻습니다 - 10자 이상)"
        say "  systemctl start autopilot"
    fi
    return 0
}
tz_notice() {
    if [ "$(date +%z)" = "+0000" ]; then
        say ""
        say "알림: 서버 시간대가 UTC 입니다. 로그인 이력의 날짜가 UTC 기준으로 나뉩니다. timedatectl set-timezone Asia/Seoul 로 맞추기를 추천합니다."
    fi
    return 0
}

firewall() {    # 넣을 규칙을 보여 주고, --apply-firewall 이나 --yes 일 때만 넣는다. 서비스 자신은 방화벽을 바꾸지 못한다
    _lo=$(H config-get "$ETC/server.json" loopback) || return 0
    _listen=$(H config-get "$ETC/server.json" listen)
    if [ "$_lo" = 1 ]; then
        say ""
        say "방화벽: 서버가 루프백($_listen)에만 듣습니다 - 열 포트가 없습니다."
        return 0
    fi
    _w=$(H config-get "$ETC/server.json" web_port)
    _ag=$(H config-get "$ETC/server.json" agent_port)
    _allow=$(H config-get "$ETC/server.json" allow)
    _ufw=$(tool ufw)
    _fwc=$(tool firewall-cmd)
    _kind=""
    if [ -n "$_ufw" ] && "$_ufw" status 2>/dev/null | grep -q "Status: active"; then
        _kind=ufw
    elif [ -n "$_fwc" ] && [ "$("$_fwc" --state 2>/dev/null || true)" = running ]; then
        _kind=firewalld
    fi
    say ""
    say "방화벽 - 사내 대역에서 이 서버의 TCP $_w(웹)·$_ag(에이전트) 로 들어오는 연결만 엽니다:"
    for _c in $_allow; do
        _fam=ipv4
        case "$_c" in *:*) _fam=ipv6 ;; esac
        case "$_kind" in
            ufw) say "  ufw allow proto tcp from $_c to any port $_w,$_ag comment autopilot" ;;
            firewalld)
                for _p in $_w $_ag; do
                    say "  firewall-cmd --permanent --add-rich-rule='rule family=\"$_fam\" source address=\"$_c\" port port=\"$_p\" protocol=\"tcp\" accept'"
                done ;;
            *) say "  출발지 $_c → 이 서버 TCP $_w, $_ag" ;;
        esac
    done
    if [ "$_kind" = firewalld ]; then say "  firewall-cmd --reload"; fi
    if [ -z "$_kind" ]; then
        say "  켜진 방화벽(ufw, firewalld)을 찾지 못했습니다. 업체 방화벽에서 위 연결만 열어 주십시오."
        return 0
    fi
    if [ "$APPLY_FW" != 1 ] && [ "$YES" != 1 ]; then
        say "  아직 넣지 않았습니다. 위 명령을 root 로 실행하여 주십시오 (설치 때 --apply-firewall 을 주면 넣습니다)."
        return 0
    fi
    _ok=1
    for _c in $_allow; do
        _fam=ipv4
        case "$_c" in *:*) _fam=ipv6 ;; esac
        if [ "$_kind" = ufw ]; then
            "$_ufw" allow proto tcp from "$_c" to any port "$_w,$_ag" comment autopilot >/dev/null || _ok=0
        else
            for _p in $_w $_ag; do
                "$_fwc" --permanent "--add-rich-rule=rule family=\"$_fam\" source address=\"$_c\" port port=\"$_p\" protocol=\"tcp\" accept" >/dev/null || _ok=0
            done
        fi
    done
    if [ "$_kind" = firewalld ]; then "$_fwc" --reload >/dev/null || _ok=0; fi
    if [ "$_ok" = 1 ]; then say "  방화벽 규칙을 넣었습니다 ($_kind)."
    else err "방화벽 규칙 일부를 넣지 못했습니다 - 위 명령을 손으로 확인하여 주십시오."; fi
    return 0
}

prune_releases() {  # 최근 KEEP_RELEASES 개만 (current 와 바로 전 버전은 늘 둔다)
    _n=0
    _cur=$(readlink "$CUR")
    for _d in $(ls -1dt "$REL"/*/ 2>/dev/null); do
        _d=${_d%/}
        _b=${_d##*/}
        _n=$((_n + 1))
        if [ "$_n" -le "$KEEP_RELEASES" ] || [ "releases/$_b" = "$_cur" ] || [ "releases/$_b" = "$1" ]; then continue; fi
        rm -rf "$_d"
        say "옛 버전 $_b 을(를) 지웠습니다 (최근 $KEEP_RELEASES 개만 둡니다)."
    done
    return 0
}

# ----------------------------------------------------------------------------------------------------
# install - 1단계 (라이선스 없이 끝난다)
# ----------------------------------------------------------------------------------------------------
cmd_install() {
    need_root
    if [ -z "$EXPECT" ]; then die "--expect-sha256 <공급사가 다른 길로 알려 준 SHA-256> 이 필요합니다 - 아무것도 하지 않았습니다."; fi
    check_sha
    if [ -e "$CUR" ] || [ -L "$CUR" ]; then
        die "이미 설치되어 있습니다 ($CUR). 업그레이드는 autopilot-server upgrade <새 설치 파일> 로 하여 주십시오."
    fi
    HX=$BUNDLE
    preflight
    check_config
    ensure_account

    say "폴더를 만듭니다."
    mkd "$OPT" 0755 0:0
    mkd "$REL" 0755 0:0
    mkd "$ETC" 0750 "0:$SVC_GID"
    mkd "$DATA" 0700 "$SVC_UID:$SVC_GID"
    mkd "$LOGS" 0700 "$SVC_UID:$SVC_GID"
    mkd "$BKP" 0700 0:0
    mkdir -p "$UNITDIR" "$SBIN"

    NEW=$REL/$V
    STAGE=$REL/.new-$V
    if [ -e "$NEW" ]; then die "이미 $NEW 이(가) 있습니다. 치운 뒤 다시 하여 주십시오."; fi
    say "프로그램을 풉니다 ($NEW)."
    rm -rf "$STAGE"
    track "$STAGE"
    mkdir -m 0755 "$STAGE"
    tar -xzf "$BUNDLE_TAR" -C "$STAGE" --strip-components=1 --no-same-owner
    finish_stage

    write_config
    say "서버 인증서를 만듭니다 (사내 인증 기관 $ETC/ca - root 만)."
    track "$ETC/ca" "$DATA/tls"
    ap_rel "$NEW" cert --renew --owner "$SVC" >/dev/null

    track "$CUR" "$OPT/.current.new"
    rm -f "$OPT/.current.new"
    ln -s "releases/$V" "$OPT/.current.new"
    mv -T "$OPT/.current.new" "$CUR"
    track "$AP"
    write_launcher || die "관리 명령 $AP 을(를) 만들지 못했습니다."

    say "systemd 단위 파일을 넣습니다 (켜지는 않습니다)."
    install_units "$NEW/server"
    sysd daemon-reload

    track "$DATA/seat.key" "$DATA/server_request.json"
    _req=$("$AP" request --user "$SVC") || die "라이선스 요청 파일을 만들지 못했습니다."
    DONE=1

    firewall || true
    tz_notice
    say ""
    say "설치를 마쳤습니다 (버전 $V). 서비스는 아직 켜지 않았습니다."
    say ""
    say "라이선스 요청 파일: $_req"
    say "  공급사에 이 파일을 보내 라이선스를 받은 뒤 install.sh activate 를 실행하여 주십시오:"
    say "    sh $HERE/install.sh activate <받은 라이선스 파일>"
    say "  (요청 파일에는 서버 번호와 자리 서명 공개 열쇠만 들어 있습니다 - 비밀 값은 없습니다. root 로 복사하여 보내 주십시오.)"
}

# ----------------------------------------------------------------------------------------------------
# activate - 2단계 (라이선스를 넣고 서비스를 켠다)
# ----------------------------------------------------------------------------------------------------
cmd_activate() {
    need_root
    if [ -z "$LICENSE" ]; then die "라이선스 파일을 알려 주십시오: sh install.sh activate <license.json>"; fi
    if [ ! -f "$LICENSE" ]; then die "라이선스 파일이 없습니다 ($LICENSE)."; fi
    if [ ! -L "$CUR" ]; then die "설치된 서버가 없습니다 - 먼저 install.sh install 로 설치하여 주십시오."; fi
    HX=$(cd "$CUR" && pwd -P)
    _iv=${HX##*/}
    need_account
    _info=$(H license "$LICENSE" "$DATA") || die "라이선스를 넣지 않았습니다."
    track "$ETC/.license.json.new"
    cp "$LICENSE" "$ETC/.license.json.new"
    chmod 0640 "$ETC/.license.json.new"
    chown "0:$SVC_GID" "$ETC/.license.json.new"
    if [ -f "$ETC/license.json" ]; then cp -p "$ETC/license.json" "$ETC/license.json.prev"; fi
    mv -f "$ETC/.license.json.new" "$ETC/license.json"
    DONE=1                                  # 이 뒤로는 되돌릴 것이 없다 (확인한 라이선스)
    say "라이선스를 넣었습니다: $_info"
    if [ "$NOSD" = 1 ]; then
        say "서비스를 켜지 않았습니다 (--no-systemd)."
        return 0
    fi
    sysd daemon-reload
    sysd enable autopilot.service
    sysd enable --now autopilot-cert.timer autopilot-config-backup.timer
    sysd restart autopilot.service
    say "서비스를 켰습니다. 실제로 도는 버전을 확인합니다 (최대 ${WAIT}초)."
    if ! wait_version "$_iv"; then
        die "서비스가 ${WAIT}초 안에 켜지지 않았습니다. journalctl -u autopilot -n 50 과 $LOGS/server.log 를 보아 주십시오."
    fi
    say "도는 버전: $_iv"
    say ""
    _rc=0
    "$AP" status || _rc=$?
    admin_hint
    tz_notice
    if [ "$_rc" != 0 ]; then
        err "서비스는 켜졌지만 위 '확인할 것' 이 있습니다."
        exit 1
    fi
}

# ----------------------------------------------------------------------------------------------------
# upgrade - autopilot-server upgrade 가 서명을 확인한 뒤에만 부른다
# ----------------------------------------------------------------------------------------------------
cmd_upgrade() {
    need_root
    if [ -z "$VERIFIED" ] || [ "$VERIFIED" != "$V" ]; then
        die "업그레이드는 autopilot-server upgrade <새 설치 파일> 로 하여 주십시오 (서명을 먼저 확인합니다)."
    fi
    if [ ! -L "$CUR" ]; then die "설치된 서버가 없습니다 - 처음 설치는 install.sh install 로 하여 주십시오."; fi
    _prev=$(readlink "$CUR")
    _oldv=${_prev##*/}
    if [ "$_oldv" = "$V" ]; then die "이미 이 버전($V)이 설치되어 있습니다 - 아무것도 바꾸지 않았습니다."; fi
    need_account
    HX=$BUNDLE
    _nf=$(H format) || die "새 버전의 자료 형식 번호를 읽지 못했습니다 - 아무것도 바꾸지 않았습니다."
    _df=1
    if [ -f "$DATA/FORMAT" ]; then _df=$(tr -d ' \r\n' < "$DATA/FORMAT"); fi
    case "$_df" in
        ''|*[!0-9]*) die "자료 형식 번호 파일($DATA/FORMAT)이 손상되었습니다 - 아무것도 바꾸지 않았습니다." ;;
    esac
    if [ "$_df" -gt "$_nf" ]; then
        die "자료 형식 번호($_df)가 새 버전($V)이 아는 것($_nf)보다 큽니다. 형식 번호가 낮은 옛 버전으로는 되돌릴 수 없습니다 - 아무것도 바꾸지 않았습니다."
    fi
    preflight

    say "자료를 백업합니다 (업그레이드 전)."
    "$AP" backup --user "$SVC" || die "백업을 만들지 못해 업그레이드를 멈췄습니다 - 아무것도 바꾸지 않았습니다."

    NEW=$REL/$V
    STAGE=$REL/.new-$V
    if [ -e "$NEW" ]; then rm -rf "$NEW"; fi          # 전에 실패하고 남은 것 (current 가 아니다)
    say "새 버전을 풉니다 ($NEW)."
    rm -rf "$STAGE"
    track "$STAGE"
    mkdir -m 0755 "$STAGE"
    cp -R -P -p "$BUNDLE/." "$STAGE/"
    finish_stage

    say "systemd 단위 파일을 바꿉니다."
    UNITS_SAVED=$OPT/.units-before-$V
    rm -rf "$UNITS_SAVED"
    track "$UNITS_SAVED"
    mkdir -m 0700 "$UNITS_SAVED"
    for _u in $UNITS; do
        if [ -f "$UNITDIR/$_u" ]; then cp -p "$UNITDIR/$_u" "$UNITS_SAVED/$_u"; fi
    done
    install_units "$NEW/server"
    sysd daemon-reload

    say "current 를 $V 로 바꿉니다."
    LINK_PREV=$_prev                            # 이 줄 뒤로는 끊기면 trap 이 링크를 되돌리고 옛 버전을 다시 켠다
    rm -f "$OPT/.current.new"
    track "$OPT/.current.new"
    ln -s "releases/$V" "$OPT/.current.new"
    mv -T "$OPT/.current.new" "$CUR"
    if [ -n "$ROOT" ]; then write_launcher || die "관리 명령 $AP 을(를) 바꾸지 못했습니다."; fi
    if [ -n "$ROOT" ] && [ "${AP_TEST_DIE_AFTER_LINK:-}" = 1 ]; then
        kill -TERM $$                           # 시험: 링크를 바꾼 다음 줄에서 끊김
        sleep 2
    fi
    if [ "$NOSD" = 1 ]; then
        say "서비스를 다시 켜지 않았습니다 (--no-systemd)."
    else
        sysd restart autopilot.service          # enable --now 가 아니다 - 도는 프로세스를 바꾼다
        say "새 버전이 도는지 확인합니다 (최대 ${WAIT}초)."
        wait_version "$V" || die "새 버전($V)이 ${WAIT}초 안에 돌지 않습니다 - 옛 버전($_oldv)으로 되돌립니다. journalctl -u autopilot -n 50 과 $LOGS/server.log 를 보아 주십시오."
    fi
    DONE=1
    rm -rf "$UNITS_SAVED"
    prune_releases "$_prev"
    say "업그레이드를 마쳤습니다: $_oldv → $V"
    say ""
    "$AP" status || true
    admin_hint
    tz_notice
}

case "$CMD" in
    install) cmd_install ;;
    activate) cmd_activate ;;
    upgrade) cmd_upgrade ;;
esac
DONE=1
exit 0
