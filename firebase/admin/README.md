# 관리 스크립트

우리 PC 에서만 돈다. `serviceAccountKey.json` 이 있어야 하고, 그 파일은 **고객 PC 에 절대 복사하지 않는다**.
서비스 계정 키는 보안 규칙을 우회하는 만능 열쇠다. 유출되면 모든 회사 데이터가 열린다.

비밀번호는 명령줄로 받지 않는다. `user`·`agent`·`passwd` 가 무작위로 만들어 **딱 한 번** 찍는다. 잃으면 `passwd` 로 다시 발급한다.
그 셋은 **우리 터미널에서 직접 친다.** Claude Code 도구·스크립트·`Start-Transcript`·파일 리다이렉트(`>`, `Tee-Object`)로 돌리지 않는다 — 출력에 비밀번호가 남는다.
이메일은 프로그램이 조립한다: `<아이디>@<회사 코드>.rpa-test-f02e0.firebaseapp.com` (밑줄은 하이픈으로, 회사가 `-` 면 도메인만, 기계 계정은 `agent-<pcId>`).
아이디에 `@` 가 있으면 그대로 이메일로 쓴다(외부 메일 계정). 같은 규칙이 `agent.py` 와 `web/app.js` 에도 있다.

```
node setup.js company c_demo 시연 회사
node setup.js pc      c_demo pc_office 사무실 PC            # company 먼저
node setup.js user    -      super super 총괄                # → super@rpa-test-f02e0.firebaseapp.com
node setup.js user    c_demo admin admin 시연 회사 관리자     # → admin@c-demo.rpa-test-f02e0.firebaseapp.com
node setup.js agent   c_demo pc_office                      # → agent-pc-office@c-demo.… 회사 코드·PC 이름·비밀번호 세 값을 PC 에 그대로 넣는다
node setup.js passwd  c_demo admin                          # 새 비밀번호, 옛 토큰 무효
node setup.js disable c_demo agent-pc-office                # 막기. enable 로 다시 연다
node setup.js show    c_demo admin
node setup.js list    c_demo                                # cid 를 빼면 전부
node setup.js modules c_demo Hold=off
```

**새 업체를 등록할 때는 물류대기 관리를 쓰는지 반드시 물어본다.** 안 쓰는 업체면 `modules <cid> Hold=off` 로 꺼 둔다.
그러면 그 업체 화면에서는 그 스위치가 아예 안 보이고, 에이전트도 명령을 받을 때 강제로 끈다. 다시 열려면 `Hold=on`.

한 업체에 사용자는 여러 명 둘 수 있다. `user` 를 사람 수만큼 부르고 같은 cid 를 주면 된다 (역할은 admin 또는 viewer).
이미 있는 계정에 `user`·`agent` 를 다시 돌리면 오류다. 비밀번호를 바꾸려면 `passwd`, 막으려면 `disable`.
만드는 도중(claim 심기, users 문서)에 실패하면 계정을 도로 지우니 같은 명령을 다시 돌리면 된다.

PC 를 빼거나 담당자가 바뀌면 `disable` 또는 `passwd`. 이미 받은 토큰은 최대 1시간 산다.
기계 계정 비밀번호를 바꾸면 그 PC 의 에이전트가 1시간 안에 멈추고 새 비밀번호를 묻는다.

이제 비밀번호는 명령줄에 없다. 예전 기록에 남은 것은 PowerShell 저장 파일을 지워야 한다 — `Clear-History` 는 세션 버퍼만 비운다.
```powershell
Remove-Item (Get-PSReadLineOption).HistorySavePath
```
