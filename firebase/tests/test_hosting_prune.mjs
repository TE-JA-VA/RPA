// 업데이트 전용 호스팅의 옛 배포 기록 지우기 (ops.pruneReleaseHosting). 서버 없이 가짜 call 로 - node test_hosting_prune.mjs
import assert from "node:assert/strict";
import { pruneReleaseHosting, HOSTING_KEEP, Refused } from "../admin/ops.js";

const base = "sites/rpa-test-f02e0-releases";
const ver = (n, status = "FINALIZED") => ({ name: `${base}/versions/v${n}`, status, createTime: `2026-11-${String(n).padStart(2, "0")}T00:00:00Z` });

function fake(versions, live, failOn = []) {
  const gone = [];
  const call = async (path, method = "GET") => {
    if (method === "DELETE") {
      if (failOn.includes(path)) throw new Error("Hosting DELETE 500");
      gone.push(path);
      return {};
    }
    if (path.startsWith(`${base}/channels?`)) return { channels: [{ name: `${base}/channels/live`, ...(live ? { release: { version: { name: live } } } : {}) }] };
    // 두 쪽으로 나눠 준다 - 다음 쪽을 안 읽으면 뒤쪽 배포가 남는다
    if (path.includes("pageToken=2")) return { versions: versions.slice(3) };
    if (path.startsWith(`${base}/versions?`)) return { versions: versions.slice(0, 3), nextPageToken: "2" };
    throw new Error(`모르는 주소 ${path}`);
  };
  return { call, gone };
}
const name = (n) => `${base}/versions/v${n}`;

assert.equal(HOSTING_KEEP, 4);

// 최신 4개만 남긴다 (FINALIZED 만 세고, 이미 지워진 것은 건드리지 않는다)
let f = fake([ver(1), ver(2), ver(3, "DELETED"), ver(4), ver(5), ver(6), ver(7)], name(7));
let r = await pruneReleaseHosting(f.call);
assert.deepEqual(f.gone.sort(), [name(1), name(2)]);
assert.deepEqual(r, { kept: 4, removed: 2, failed: 0 });

// 되돌려서 옛 배포가 사용 중이면 오래됐어도 안 지운다
f = fake([1, 2, 3, 4, 5, 6].map((n) => ver(n)), name(1));
r = await pruneReleaseHosting(f.call);
assert.deepEqual(f.gone, [name(2)]);
assert.deepEqual(r, { kept: 5, removed: 1, failed: 0 });

// 사용 중인 배포를 모르면 하나도 안 지운다
f = fake([1, 2, 3, 4, 5, 6].map((n) => ver(n)), null);
await assert.rejects(pruneReleaseHosting(f.call), Refused);
assert.deepEqual(f.gone, []);

// 일부를 못 지워도 나머지는 지우고 알린다
f = fake([1, 2, 3, 4, 5, 6].map((n) => ver(n)), name(6), [name(1)]);
r = await pruneReleaseHosting(f.call);
assert.deepEqual(f.gone, [name(2)]);
assert.deepEqual(r, { kept: 5, removed: 1, failed: 1 });

// 남길 수 이하면 할 일 없음
f = fake([1, 2, 3].map((n) => ver(n)), name(3));
r = await pruneReleaseHosting(f.call);
assert.deepEqual(f.gone, []);

console.log("PASS 옛 배포 기록 지우기");
process.exit(0);
