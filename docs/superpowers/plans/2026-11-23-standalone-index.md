# 스탠드얼론 계획 목록

설계: `docs/superpowers/specs/2026-11-23-standalone-local-server-design.md` (사용자 승인 2026-11-23). 브랜치 `StandAlone`, 작업 폴더 `D:\AX\RPA_StandAlone`.

설계 13절의 7단계를 서로 따로 시험할 수 있는 계획 다섯으로 나눈다. 앞 계획이 만든 이름(Interfaces)을 뒤 계획이 쓰므로,
**계획은 앞 것이 끝난 뒤에 자세히 쓴다** (지금 자세히 쓰면 앞 계획을 하며 바뀐 이름이 어긋난다). 지금 자세한 것은 ① 하나.

| 계획 | 설계 13절 | 끝나면 되는 것 | 상태 |
|---|---|---|---|
| ① 서버 핵심 `2026-11-23-standalone-1-server-core.md` | 2·3 | 버전 종류·라이선스·로컬 서버(저장소·에이전트 창구)·`local_store`, 에이전트가 Firebase 없이 로컬 서버로 명령을 받아 돈다 | 구현 끝 (fd16ed6~157d20e, 검토 고침 e46fc06) |
| ② 업체 웹 `2026-11-23-standalone-2-web.md` | 1·4 | 웹 데이터 자리를 `data.js` 로 모으기(일반 버전 그대로) → 로컬 계정·로그인·`/api/*`·`data-local.js`·숨기기·로컬 글꼴·계정 칸 | 구현 끝 (6b399ce·99fc143·190f4a5·Task 5) - 전체 검토 남음 |
| ③ 설치·빌드 `2026-11-23-standalone-3-install-build.md` | 5 | `--edition standalone` 빌드(AI·anthropic 뺌, 라이선스 확인·변조 감지 컴파일 조각), 설치 마법사(라이선스·관리자 계정·일반 버전 있으면 멈춤), 키 파일 권한, 샌드박스 `--standalone`·바깥 연결 0 시험, 관리자 비밀번호 다시 정하기 | 자세히 씀, Task 1~5 구현 중 |
| ④ 휴대폰 창구 `2026-11-23-standalone-4-phone.md` | 6 | 사내망 HTTPS 포트·자체 서명 인증서·QR 짝짓기·인증번호 창구, 약속 문서·휴대폰 흉내 시험, ACTOR 실행의 5분 사람 입력 → 맥 세션에 앱 고침 부탁 | Task 1~5 구현 (2026-11-23, 커밋 전). 약속 문서 `docs/phone-local-contract.md`·앱 흉내 `tests/fake_phone_local.py` 를 맥 세션에 넘길 것. 실제 휴대폰·사내망 확인은 앱이 나온 뒤 |
| ⑤ 문서 | 7 | 스탠드얼론 사용설명서·보안 자료 (`D:\AX_보고용 문서 모음`, 작성 : 원제로소프트) | 목록만 |

develop 의 고침은 각 계획을 시작하기 전에 StandAlone 으로 합쳐 받는다 (`git merge develop`, 한 방향).
