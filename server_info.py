"""오토파일럿이 붙는 서버 주소 - 한 곳 (2026-10-21). 회사 서버나 새 Firebase 프로젝트로 옮길 때 여기를 바꾼다.

자바스크립트 쪽은 따로 한 곳씩 있다: 업체 웹 firebase/web/firebase-config.js, 관리 화면 firebase/admin/ops.js 맨 위
(tests/test_server_info.py 가 셋이 같은지, 다른 실행 코드에 프로젝트 이름이 박히지 않았는지 본다).
Firebase 배포 설정(firebase/.firebaserc, firebase*.json·releases.json 의 site)은 Firebase 도구가 읽는 파일이라 따로 바꾼다.
주의: 설치된 PC 는 처음 설정할 때 PROJECT_ID·API_KEY·DATABASE_URL 을 agent_config.json 에 적어 둔다 (secret.PUBLIC) -
서버를 옮길 때는 그 값까지 바꾸는 건너가기 버전이 필요하다.
"""
PROJECT_ID = "rpa-test-f02e0"
API_KEY = "AIzaSyCFbHQjWVxzi38IAYIhQX9wyiGIs1VcZuA"                    # 공개 값 - 브라우저에도 그대로 나간다 (보안은 DB 규칙)
DATABASE_URL = f"https://{PROJECT_ID}-default-rtdb.asia-southeast1.firebasedatabase.app"
AUTH_DOMAIN = f"{PROJECT_ID}.firebaseapp.com"                           # 로그인 이메일 도메인 (계정 이메일을 조립한다)
DASHBOARD_URL = f"https://{PROJECT_ID}.web.app"                         # 업체 웹
UPDATE_BASE_URL = f"https://{PROJECT_ID}-releases.web.app"              # 업데이트 전용 호스팅
