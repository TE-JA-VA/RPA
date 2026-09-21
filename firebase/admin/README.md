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
```

비밀번호는 명령 이력에 남는다. 등록한 뒤 PowerShell 기록(`Clear-History`)을 지우고, 사용자에게는 첫 로그인에서 바꾸게 한다.
