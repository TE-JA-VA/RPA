# 관리 스크립트

우리 PC 에서만 돈다. `serviceAccountKey.json` 이 있어야 하고, 그 파일은 **고객 PC 에 절대 복사하지 않는다**.
서비스 계정 키는 보안 규칙을 우회하는 만능 열쇠다. 유출되면 모든 회사 데이터가 열린다.

```
node setup.js company c_demo 시연 회사
node setup.js pc      c_demo pc_office 사무실 PC
node setup.js user    super@rpa-test-f02e0.firebaseapp.com <비밀번호> - super 총괄
node setup.js user    admin@c-demo.rpa-test-f02e0.firebaseapp.com <비밀번호> c_demo admin 시연 회사 관리자
node setup.js agent   agent-pc-office@c-demo.rpa-test-f02e0.firebaseapp.com <비밀번호> c_demo pc_office
node setup.js show    admin@c-demo.rpa-test-f02e0.firebaseapp.com
node setup.js modules c_demo Hold=off
```

**새 업체를 등록할 때는 물류대기 관리를 쓰는지 반드시 물어본다.** 안 쓰는 업체면 `modules <cid> Hold=off` 로 꺼 둔다.
그러면 그 업체 화면에서는 그 스위치가 아예 안 보이고, 에이전트도 명령을 받을 때 강제로 끈다. 다시 열려면 `Hold=on`.

한 업체에 사용자는 여러 명 둘 수 있다. `user` 를 사람 수만큼 부르고 같은 cid 를 주면 된다 (역할은 admin 또는 viewer).

비밀번호는 명령 이력에 남는다. 등록한 뒤 PowerShell 기록(`Clear-History`)을 지우고, 사용자에게는 첫 로그인에서 바꾸게 한다.
