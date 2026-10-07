# AFTER MARKET RPA

ERPia 업무 자동화(RPA)와 업체 대시보드(Firebase). 구조 안내는 [docs/firebase-architecture.md](docs/firebase-architecture.md).

## 작업 방법

- `main` 은 잠겨 있다. `main` 을 받아 자기 브랜치에서 작업한 뒤 **PR** 로 보낸다.
- 비밀 파일은 저장소에 없다 (git 이 빼도록 막혀 있다): `firebase/admin/serviceAccountKey.json`, `firebase/admin/update_signing_key.txt`, `firebase/agent/agent_config.json`, 사용자 설정·자격증명 파일. PR 에도 넣지 않는다.

## 버전 업데이트 (자동 업데이트) - 저장소 관리자만

업체 PC 에 새 버전을 보내는 일(**버전 빌드 → 내보내기 → 관리 화면 [업데이트]**)은 **저장소 관리자만** 한다.
버전 목록에 서명하는 비밀 열쇠(`firebase/admin/update_signing_key.txt`)가 저장소 관리자 PC 에만 있기 때문이다.
이 열쇠를 가진 사람은 모든 업체 PC 에 프로그램을 '정식 업데이트'로 보낼 수 있으므로 나누어 주지 않는다.

**버전 업데이트가 필요하면 코드를 PR 로 보내고 저장소 관리자에게 요청한다.** 열쇠가 없는 PC 에서 `tools/publish_release.py` 를 돌리면 이 안내를 띄우고 멈춘다.
