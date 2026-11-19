# 보안 보완 1차 묶음 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task (native - 이 세션에서 직접).

**Goal:** 고객사 보안성 검토 의견 1차(2026-11-19) 가운데 서버 구조와 상관없이 바로 고칠 수 있는 것을 고쳐 새 버전으로 내보낸다.

**Architecture:** PC 프로그램(설정 파일·에이전트·옵저버·설치 파일)과 업체 웹 화면만 고친다. Firebase 규칙·요금제·서버 구조는 건드리지 않는다 (업체 서버 이전 여부와 무관하게 남는 일만).

**Tech Stack:** Python 3.14 (ctypes DPAPI, tkinter 옵저버), Firebase 웹(정적 JS), Inno Setup, Nuitka 조각 빌드.

**Spec:** `D:\AX\오토파일럿 보안, 소개자료\내부용_검증결과_2026-11-13\고칠_목록_2번작업.md` (C2·C5·C6·C11·C12·C13·C16·C17·D3) + 고객사 의견 1차 (메모리 `security-review-customer-1st`). 저장소 밖 대외비 자료라 여기 옮겨 적지 않는다.

## Global Constraints

- 엑셀 비밀번호는 PC(옵저버)에서만 입력하고 DPAPI 로 잠가 저장한다. 클라우드(현황·명령)로 보내지 않는다 (사용자 2026-11-19).
- 비밀번호 값은 로그·사유·화면·시험 출력에 싣지 않는다. 비밀 파일(RPA_UserConfig.json 실물·서명 열쇠·서비스 계정 키)은 읽지 않는다.
- 화면 글은 `docs/ui-wording.md` (중단·실행합니다·~하여 주십시오, '삭제' 는 관리 화면에서 안 씀).
- 커밋·push·내보내기는 사용자가 말할 때만. `docs/TODO.md` 의 다른 세션 변경은 건드리지 않는다.
- 옛 버전 PC·옛 웹 탭과 섞여도 죽지 않는다 (모르는 키는 무시).
- `.venv` 패키지 버전은 그대로. Python 만 3.14.10 으로 (Task 9).

## Review Focus

1. 옛 버전에서 올라온 PC 의 설정 파일에 평문 `ExcelPW` 가 있다 → 에이전트가 켤 때 잠그고, 잠긴 값으로도 엑셀 업로드 비밀번호 창에 원래 글자가 들어간다.
2. 다른 PC·다른 윈도우 계정에서 잠근 `ExcelPW` (설정 파일 복사) → 실행이 죽지 않고 그 파일만 '비밀번호를 넣지 못함' 으로 남는다.
3. 옛 웹 탭이 `set_presets` 에 `excel_pw` 를 실어 보냄 → 켬/끔은 그대로 적용, 비밀번호는 쓰지 않고 기록에 한 줄.
4. 이미 클라우드에 남은 값: 현황의 `presets[i].excel_pw`, 끝난 `set_presets` 명령의 `args.excel_pw` → 새 에이전트가 켜지면 없어진다.
5. 미사용 자동 로그아웃이 실행 중인 작업(명령 전송 직후)이나 총괄의 업체 대시보드 열기(1시간)와 부딪히지 않는다.

---

### Task 1: 엑셀 비밀번호 2종 DPAPI 저장·읽기

**Files:** Modify `rpa_status.py`, `wellife.py`, `run_routine.py`(글만) · Test `tests/test_presets.py`, `tests/test_wellife.py`, `tests/test_excel_upload_order.py`

**Interfaces — Produces:**
- `rpa_status._pw_slots(data)` 가 `Sites.<칸>.ExcelPW` 와 `InvoiceExcel.Password` 도 낸다 (write_user_config·migrate_user_config 가 잠근다).
- `rpa_status.excel_password(code) -> str | None` 은 푼 값을 돌려준다. 못 풀면 RuntimeError (unseal 그대로).
- `rpa_status.preset_summary()` 는 `excel_pw` 를 내지 않고 `xl_set: bool` 을 낸다.
- `rpa_status.save_preset_sites(..., excel_pws=None)`: `{번호: 새 값 | "" (지움) | None (그대로)}`.
- `wellife.export_password(rr)` 는 잠긴 값을 풀어 쓴다.

- [ ] 시험 먼저: 평문 ExcelPW 가 든 설정을 `migrate_user_config()` 하면 파일에 `dpapi:` 로 바뀌고 `excel_password` 는 원래 글자 / `preset_summary` 에 값이 없고 `xl_set` 만 / `save_preset_sites(excel_pws=)` 세 경우 / InvoiceExcel.Password 잠김·풀림 / 못 푸는 값은 fill_excel_password 가 False 와 기록 한 줄.
- [ ] 실패 확인 → 구현 → 통과 확인 (test_presets, test_wellife, test_excel_upload_order)

### Task 2: 에이전트 - 클라우드에서 엑셀 비밀번호 빼기

**Files:** Modify `firebase/agent/agent.py` · Test `firebase/tests/test_agent.py`

- `do_presets`: `excel_pw` 인자는 쓰지 않는다. 있으면 결과 글 끝에 "엑셀 비밀번호는 PC의 옵저버에서 입력하여 주십시오." 를 붙인다.
- 켤 때 한 번 `purge_excel_pw_commands(client, cid, pc_id)`: 끝난 `set_presets` 명령 중 `args.excel_pw` 가 있는 것을 나이와 상관없이 지운다 → 지운 수.
- 현황은 `preset_summary()` 를 통째로 올리므로 Task 1 로 값이 빠진다 - 시험으로 확인.

### Task 3: 옵저버 - 엑셀 비밀번호 칸

**Files:** Modify `rpa_observer.py` · Test `tests/test_observer_widgets.py` 또는 `tests/test_presets.py` (칸 값 → save_preset_sites 인자)

- 프리셋 칸에 `xl_pw`(새로 친 글자)·`has_xl_pw` (mail_pw 와 같은 방식, 가려서 `show="•"`). 저장하면 비우고 has 만.
- 저장된 값이 있을 때 [엑셀 비밀번호 지우기] 로 비운다.
- '저장하지 않은 변경' 판정에 포함.

### Task 4: 업체 웹 - 엑셀 비밀번호 칸 없애기

**Files:** Modify `firebase/web/rpa-settings.js`, `firebase/web/index.html` · Test `firebase/tests/check_web.py` 5-2-0절

- 입력 칸·[엑셀 비밀번호 설정] 단추·`excel_pw` 전송을 없앤다. `xl_set` 이 참인 줄에 '엑셀 비밀번호 설정됨' 만 보인다.
- 옛 PC 가 올린 `excel_pw` 값은 화면에 쓰지 않는다.

### Task 5: 업체 웹 - 탭 단위 로그인·미사용 자동 로그아웃 (D3)

**Files:** Modify `firebase/web/` 로그인·공통 스크립트 · Test `firebase/tests/check_web.py`

- 로그인 유지를 탭 단위(browserSessionPersistence)로. 입력(마우스·키보드·터치)이 30분 없으면 로그아웃하고 로그인 화면에 까닭 한 줄.

### Task 6: 시험용 환경 변수 무시 (C2)

**Files:** `server_info.py`, `firebase/agent/fb.py`, `rpa_update.py` 등 · 해당 시험

- 설치본(프로그램 폴더에서 실행)에서는 에뮬레이터·업데이트 주소 환경 변수를 무시. 클라우드·업데이트 주소는 https 만.

### Task 7: 옛 설정 파일 정리·제거 기본값 (C11)

**Files:** `rpa_status.py`(migrate), `release/installer.iss` · `tests/test_settings.py`, 샌드박스

- 새 설정으로 잘 읽히면 `.old`·`.broken` 평문 파일을 지운다. 제거할 때 설정·기록 삭제 물음의 기본값을 '예'로.

### Task 8: 인증번호 삭제 재시도 (C17) · http 주소 경고 (C12) · 옛 로컬 화면 코드 제거 (C13) · 설치 폴더 권한 (C16)

**Files:** `otp_relay.py`, `rpa_observer.py`/`web_runner.py`, `rpa_dashboard.py`, `release/installer.iss` · 해당 시험·샌드박스

### Task 9: Python 3.14.10 · 전체 빌드 · 샌드박스

- 개발 PC Python 3.14 를 최신으로, `ssl.OPENSSL_VERSION` 이 3.5.9 인지 확인. `requirements.txt` 머리글의 버전 고침.
- 전체 시험 → `build_release.py --modules` → 샌드박스. 내보내기·hosting 배포·커밋은 사용자 확인 뒤.
