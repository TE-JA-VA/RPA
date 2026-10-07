// 회사·PC·사용자·에이전트·토큰을 다룬다. 우리 PC 에서만 돈다. 같은 일을 화면으로: 바탕화면 'AFTER MARKET 관리' (node admin.js)
//
//   node setup.js company  <cid> <회사 이름>
//   node setup.js pc       <cid> <pcId> <PC 이름>                  (company 먼저)
//   node setup.js user     <cid|-> <아이디|이메일> <super|admin|viewer> <이름>
//   node setup.js agent    <cid> <pcId>                            (pc 먼저)
//   node setup.js passwd   <cid|-> <아이디|이메일>                  새 비밀번호 발급, 옛 토큰 무효
//   node setup.js disable  <cid|-> <아이디|이메일>                  사용중지 (enable 로 다시 사용)
//   node setup.js enable   <cid|-> <아이디|이메일>
//   node setup.js show     <cid|-> <아이디|이메일>
//   node setup.js list     [cid]
//   node setup.js modules  <cid> Hold=off Output=on   (업체가 안 쓰는 모듈. off 면 화면에서 숨고 에이전트가 강제로 끈다)
//   node setup.js slots    <cid> [개수]                            자동 실행 개수 (시각·반복 시간대를 합친 줄 수, 기본 2, 0~12). 개수가 없으면 보기
//   node setup.js remove   <cid>                                   업체 비활성화: stts=9, 그 업체 계정 전부 사용중지. 데이터는 남는다
//   node setup.js restore  <cid>                                   다시 활성화: stts=0, 계정 다시 사용
//   node setup.js tokens   <cid> [+1000|-50] [메모]                토큰 넣기·빼기 (처음 넣으면 토큰 정보를 만든다), 금액 없으면 보기
//   node setup.js price    [<모듈 키> <배율>]                       토큰 배율 보기·바꾸기 (예: price logistics 2)
//   node setup.js usage    [cid]                                   업체마다 남은 토큰·이번 달 쓴 토큰
//
// 업체 상태 stts: 0(또는 없음) 사용중, 9 비활성. 비활성화된 업체엔 pc·user·agent 를 못 만든다.
// 비밀번호는 명령줄로 받지 않는다. 무작위로 만들어 딱 한 번 찍고, 잃으면 passwd 로 다시 발급한다.
// 일은 ops.js 가 한다 (관리 화면과 같은 코드). 이메일 조립 규칙도 거기에.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

// 인수 개수 [최소, 최대]. 옛 꼴(user <이메일> <비밀번호> …, agent <이메일> <비밀번호> …)은 받지 않는다.
const ARGC = { company: [2], pc: [3], user: [4], agent: [2, 2], passwd: [2, 2], disable: [2, 2], enable: [2, 2], show: [2, 2], list: [0, 1], modules: [2], slots: [1, 2], remove: [1, 1], restore: [1, 1],
  tokens: [1], price: [0, 2], usage: [0, 1] };

const [, , cmdName, ...rest] = process.argv;
const [min, max = Infinity] = ARGC[cmdName] ?? [];
if (!ARGC[cmdName] || rest.length < min || rest.length > max) {
  const src = readFileSync(fileURLToPath(import.meta.url), "utf8").split("\n");
  console.log(src.slice(1, src.findIndex((l) => !l.startsWith("//"))).join("\n"));
  process.exit(1);
}
const ops = await import("./ops.js");     // 인수를 본 뒤에 연다 - 도움말은 서비스 계정 키 없이도 나온다

try {
  if (cmdName === "company") {
    const r = await ops.addCompany(rest[0], rest.slice(1).join(" "));
    console.log(`회사 등록: ${r.cid}`);
    console.log(`  이 업체가 안 쓰는 모듈이 있으면: node setup.js modules ${r.cid} Hold=off`);
  } else if (cmdName === "pc") {
    const r = await ops.addPc(rest[0], rest[1], rest.slice(2).join(" "));
    console.log(`PC 등록: ${r.cid}/${r.pcId}`);
  } else if (cmdName === "user") {
    const r = await ops.addUser(rest[0], rest[1], rest[2], rest.slice(3).join(" "));
    console.log(`사용자 등록: ${r.email}  uid=${r.uid}  role=${r.role}  cid=${r.cid ?? "-"}`);
    console.log(`  비밀번호: ${r.password}   (다시 볼 수 없다. 잃으면 passwd)`);
  } else if (cmdName === "agent") {
    const r = await ops.addAgent(rest[0], rest[1]);
    console.log(`에이전트 등록: ${r.email}  uid=${r.uid}`);
    console.log(`  PC 설정 창에 그대로 넣는다 →  업체코드: ${r.cid}   PC코드: ${r.pcId}   비밀번호: ${r.password}`);
    console.log(`  다시 볼 수 없다. 잃으면 passwd`);
  } else if (cmdName === "passwd") {
    const r = await ops.resetPassword(rest[0], rest[1]);
    console.log(`비밀번호 교체: ${r.email}`);
    console.log(`  비밀번호: ${r.password}   (다시 볼 수 없다. 잃으면 다시 passwd. 이미 받은 토큰은 최대 1시간 산다)`);
    if (r.agent) console.log(`  PC 에서 에이전트가 1시간 안에 멈추고 새 비밀번호를 묻는다`);
  } else if (cmdName === "disable" || cmdName === "enable") {
    const r = await ops.setDisabled(rest[0], rest[1], cmdName === "disable");
    console.log(r.disabled ? `사용중지: ${r.email}  (이미 받은 토큰은 최대 1시간 산다)` : `다시 사용: ${r.email}`);
  } else if (cmdName === "show") {
    console.log(await ops.showUser(rest[0], rest[1]));
  } else if (cmdName === "list") {
    const { companies, users } = await ops.listAll(rest[0]);
    if (!rest[0]) console.table(Object.entries(companies).map(([k, v]) => ({ cid: k, name: v.name ?? "-", stts: v.stts ?? 0, pcs: Object.keys(v.pcs ?? {}).join(" ") || "-" })));
    console.table(users);
  } else if (cmdName === "remove" || cmdName === "restore") {
    const removing = cmdName === "remove";
    const r = await ops.setCompanyRemoved(rest[0], removing);
    if (!removing && r.already) {
      console.log("이미 사용중인 업체입니다.");
    } else {
      if (removing && r.already) console.log("이미 비활성화된 업체입니다.");   // 그래도 다시 사용중지했다 (중간에 멈췄거나 누가 enable 했을 때)
      console.log(removing
        ? `업체 비활성화: ${r.cid} ${r.name}  stts=9, 계정 ${r.users.length}개 사용중지 (이미 받은 토큰은 최대 1시간 산다. 에이전트는 그 안에 멈춘다)`
        : `업체 다시 활성화: ${r.cid} ${r.name}  stts=0, 계정 ${r.users.length}개 다시 사용`);
      for (const e of r.users) console.log(`  ${e}`);
    }
  } else if (cmdName === "modules") {
    const [cid, ...pairs] = rest;
    const p = await ops.setModules(cid, Object.fromEntries(pairs.map((x) => x.split("="))));
    console.log(`모듈 정책: ${cid}`, Object.keys(p).length ? p : "(없음 - 전부 사용)");
  } else if (cmdName === "slots") {
    const [cid, n] = rest;
    if (n === undefined) {
      const v = await ops.scheduleLimitOf(cid);
      console.log(`자동 실행 개수: ${cid}  ${v ?? `${ops.SCHEDULE_LIMIT_DEFAULT} (기본)`}`);
    } else {
      const r = await ops.setScheduleLimit(cid, n);
      console.log(`자동 실행 개수: ${r.cid} = ${r.schedule} (PC 에는 10분 안에 닿는다)`);
    }
  } else if (cmdName === "tokens") {
    const [cid, amount, ...memoParts] = rest;
    const s = amount === undefined ? await ops.tokenStatus(cid) : await ops.grantTokens(cid, amount, memoParts.join(" "));
    if (s.created) console.log(`토큰 정보를 만들었습니다: ${s.cid} ${s.name} - 지금부터 토큰이 0 이하면 모듈 실행을 막습니다 (그 전에 쓴 것은 안 뺀다)`);
    if (!s.wallet) {
      console.log(`${s.cid} ${s.name} 는 토큰 정보가 없다 (토큰 제도 밖 - 세기만 한다). 넣으려면: node setup.js tokens ${s.cid} +1000 "메모"`);
    } else {
      const w = s.wallet;
      console.log(`토큰: ${s.cid} ${s.name}  넣은 합계 ${w.granted} · 쓴 ${w.spent} · 남은 ${w.left}  (${w.since} 부터)`);
      console.table(w.grants.map((g) => ({ 언제: g.at, 얼마: g.amount, 메모: g.memo || "-" })));
    }
  } else if (cmdName === "price") {
    const t = rest.length ? await ops.setPrice(rest[0], rest[1]) : await ops.getPrices();
    console.log("토큰 배율 (모듈을 한 번 쓸 때 빠지는 토큰 - 여기 없는 모듈은 default):", t);
  } else if (cmdName === "usage") {
    console.table((await ops.usageRows(rest[0])).map((r) => ({ cid: r.cid, 이름: r.name, 남은: r.left ?? "-", 이번달: r.month, "토큰 정보": r.since ? `${r.since} 부터` : "없음" })));
  }
} catch (e) {
  if (!(e instanceof ops.Refused)) throw e;
  console.error(`오류: ${e.message}`);
  process.exit(1);
}
process.exit(0);
