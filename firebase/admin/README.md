# 관리 스크립트

## 관리 화면 (먼저 이것)

바탕화면 **'AFTER MARKET 관리'** 를 두 번 누르면 검은 창(서버)이 뜨고 기본 브라우저로 관리 화면이 열린다. 이 PC 에서만 열린다
(127.0.0.1, 켤 때마다 새 비밀 값). 할 수 있는 일: 업체 목록·상세 (PC 추가·계정 추가·비밀번호 재발급·사용중지/사용·토큰 넣기/빼기·
모듈 정책·업체 비활성화/다시 활성화), **신규 업체** 한 흐름 (업체 → PC → 관리자·유저 → 에이전트 계정 → 물류대기 관리 메뉴 사용 여부 → 최초 토큰량 →
'고객에게 보낼 정보' 복사), **토큰 배율** (전 이름 '값표')·통계.
화면 이름 (2026-10-06 사용자가 고름): 에이전트(전 '기계') 계정, 유저(전 '열람자'), 사용중지/사용(전 '막기/열기'),
토큰 정보(전 '통장'), 업체 비활성화(전 '업체 삭제'). 터미널 명령(setup.js)과 업체 대시보드(웹)의 글도 같은 이름이다. PC 쪽 프로그램(설정 창·에이전트 안내·배포 안내문)도 '에이전트 계정'.

- 맨 위 띠: **실제 서버 (rpa-test-f02e0)** 주황 / **에뮬레이터 (시험)** 회색.
- 비밀번호는 만들 때 화면 결과 칸에 **한 번만** 보인다. 화면을 떠나면 다시 볼 수 없다 (잃으면 재발급). 서버 창·기록에는 안 남는다.
- 한 일은 `관리_기록.txt` 에 한 줄씩 (언제·무엇을·업체·대상, 비밀번호 없이).
- 다 쓰면 화면의 **[끄기]** 또는 검은 창을 닫는다. 서버를 다시 켜면 옛 화면은 "다시 켜세요" 가 뜬다 - 새로 열린 화면을 쓴다.
- 바로 가기를 다시 만들려면: `cd D:\AX\RPA\firebase\admin; node admin.js --shortcut`

## 터미널 명령 (setup.js - 화면과 같은 일)

우리 PC 에서만 돈다. `serviceAccountKey.json` 이 있어야 하고, 그 파일은 **고객 PC 에 절대 복사하지 않는다**.
서비스 계정 키는 보안 규칙을 우회하는 만능 열쇠다. 유출되면 모든 회사 데이터가 열린다.

비밀번호는 명령줄로 받지 않는다. `user`·`agent`·`passwd` 가 무작위로 만들어 **딱 한 번** 찍는다. 잃으면 `passwd` 로 다시 발급한다.
그 셋은 **우리 터미널에서 직접 친다.** Claude Code 도구·스크립트·`Start-Transcript`·파일 리다이렉트(`>`, `Tee-Object`)로 돌리지 않는다 — 출력에 비밀번호가 남는다.
이메일은 프로그램이 조립한다: `<아이디>@<회사 코드>.rpa-test-f02e0.firebaseapp.com` (밑줄은 하이픈으로, 회사가 `-` 면 도메인만, 에이전트 계정은 `agent-<pcId>`).
아이디에 `@` 가 있으면 그대로 이메일로 쓴다(외부 메일 계정). 같은 규칙이 `agent.py` 와 `web/app.js` 에도 있다.

```
node setup.js company c_demo 시연 회사
node setup.js pc      c_demo pc_office 사무실 PC            # company 먼저
node setup.js user    -      super super 총괄                # → super@rpa-test-f02e0.firebaseapp.com
node setup.js user    c_demo admin admin 시연 회사 관리자     # → admin@c-demo.rpa-test-f02e0.firebaseapp.com
node setup.js agent   c_demo pc_office                      # → agent-pc-office@c-demo.… 회사 코드·PC 이름·비밀번호 세 값을 PC 에 그대로 넣는다
node setup.js passwd  c_demo admin                          # 새 비밀번호, 옛 토큰 무효
node setup.js disable c_demo agent-pc-office                # 사용중지. enable 로 다시 사용
node setup.js show    c_demo admin
node setup.js list    c_demo                                # cid 를 빼면 전부
node setup.js modules c_demo Hold=off
node setup.js slots c_demo 3        # 자동 실행 개수 (기본 2, 시각·반복 시간대 합친 줄 수)
```

**새 업체를 등록할 때는 물류대기 관리를 쓰는지 반드시 물어본다.** 안 쓰는 업체면 `modules <cid> Hold=off` 로 꺼 둔다.
그러면 그 업체 화면에서는 그 스위치가 아예 안 보이고, 에이전트도 명령을 받을 때 강제로 끈다. 다시 열려면 `Hold=on`.

한 업체에 사용자는 여러 명 둘 수 있다. `user` 를 사람 수만큼 부르고 같은 cid 를 주면 된다 (역할은 admin 또는 viewer).
이미 있는 계정에 `user`·`agent` 를 다시 돌리면 오류다. 비밀번호를 바꾸려면 `passwd`, 사용중지하려면 `disable`.
만드는 도중(claim 심기, users 문서)에 실패하면 계정을 도로 지우니 같은 명령을 다시 돌리면 된다.

PC 를 빼거나 담당자가 바뀌면 `disable` 또는 `passwd`. 이미 받은 토큰은 최대 1시간 산다.
에이전트 계정 비밀번호를 바꾸면 그 PC 의 에이전트가 1시간 안에 멈추고 새 비밀번호를 묻는다.

이제 비밀번호는 명령줄에 없다. 예전 기록에 남은 것은 PowerShell 저장 파일을 지워야 한다 — `Clear-History` 는 세션 버퍼만 비운다.
```powershell
Remove-Item (Get-PSReadLineOption).HistorySavePath
```
