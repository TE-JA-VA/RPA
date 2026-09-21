# 에뮬레이터 통합 시험

에뮬레이터는 실제 프로젝트를 건드리지 않는다. 실제 RPA 도 띄우지 않는다 (DRY_RUN).
`integration.js` 가 시험 계정·claim 을 만들고, 명령을 넣고, 에이전트를 띄워 결과를 확인한 뒤 끈다.

```powershell
cd D:\AX\RPA\firebase
. .\emu_env.ps1
cd tests
firebase emulators:exec --config ../firebase.json --only auth,database,firestore --project rpa-test-f02e0 "node integration.js"
```

확인하는 것: 명령 queued→running→done 과 결과 문장, 만료 명령 expired, live 현황·heartbeat·모듈·예약·10일 요약 올라옴,
로그 80줄 이하, 연달아 실행 시 잠금 거절(failed), 자동 실행 설정 저장·거부, 계정 해시 미전송,
이력(history.jsonl 26건)이 Firestore runs/{cid}/items 로 올라옴.

에이전트 설정·큐는 임시 폴더(`RPA_AGENT_CONFIG`, `RPA_AGENT_QUEUE`)를 써서 실제 `agent_config.json` 을 건드리지 않는다.
`set_modules` 는 실제 `ERPIA_AI.txt` 를 써야 해서 여기서 안 본다 - 실기(Task 12)에서 본다.

끊김·재접속(지수 백오프)은 손으로 본다: 위 명령 대신 `firebase emulators:start --only auth,database` 로 띄우고
다른 창에서 에이전트를 띄운 뒤 에뮬레이터를 Ctrl+C 로 끄면 `구독이 끊겼습니다 … 1초 뒤` 가 찍히고 간격이 2, 4, 8 로 는다.
