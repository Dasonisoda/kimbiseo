'use strict';
/* 펫 자리·크기 계산 단위 시험 — 가짜 화면 구성으로(Electron 없이).   node tests/unit/test_pet_geometry.js
   배율이 섞인 화면 · 음수 좌표(왼쪽·위 화면) · 세로 화면 · 기억한 화면이 사라짐·옮겨짐·배율 바뀜 · 0.1.12 까지의 기억(좌표만) · 크기 퍼센트 */
const path = require('path');
const G = require(path.join(__dirname, '..', '..', 'pet', 'geometry.js'));

let pass = 0, fail = 0;
function ok(name, cond, info) {
  if (cond) pass++; else fail++;
  console.log((cond ? '됨   ' : '실패 ') + name + (cond || info === undefined ? '' : ' — ' + JSON.stringify(info)));
}
// 작업 영역(작업 표시줄 40 뺌). Electron 논리 좌표(DIP)
const scr = (id, x, y, w, h, scale, primary) => ({ id, x, y, width: w, height: h - 40, scale: scale || 1, primary: !!primary });
const MAIN = scr(1, 0, 0, 1920, 1080, 1, true);
const RIGHT = scr(2, 1920, 0, 1707, 960, 1.5);          // 2560x1440 @150% → 논리 1707x960
const LEFT = scr(3, -864, -240, 864, 1536, 1.25);       // 세로 1080x1920 @125%, 왼쪽(음수 좌표)
const TOP = scr(4, 200, -1080, 1920, 1080, 1);
const ALL = [RIGHT, MAIN, LEFT, TOP];                    // 일부러 주 화면이 첫째가 아님
const SZ = { w: 500, h: 500 };

// ---- 기본 자리
let p = G.defaultPos(SZ, ALL);
ok('기본 자리는 주 화면 오른쪽 아래(목록 첫 화면이 주 화면이 아니어도)', p.x === 1920 - 500 - 40 && p.y === 1040 - 500, p);
ok('주 화면을 맨 앞으로', G.primaryFirst(ALL)[0] === MAIN && G.primaryFirst(ALL).length === 4);

// ---- 보이는지·가두기
ok('몸통이 어느 화면 안에 있으면 보이는 것(음수 좌표 화면 포함)', G.visibleEnough(-700, 300, SZ, ALL) && G.visibleEnough(2500, 300, SZ, ALL) && G.visibleEnough(600, -800, SZ, ALL));
ok('어느 화면에도 없으면 안 보이는 것', !G.visibleEnough(5000, 300, SZ, ALL) && !G.visibleEnough(-3000, 0, SZ, ALL) && !G.visibleEnough(2500, 1200, SZ, ALL));
p = G.clampPos(9000, 300, SZ, ALL);
ok('화면 밖 좌표는 가장 가까운 화면 안으로(1/3 은 보이게)', p.x <= RIGHT.x + RIGHT.width - 500 / 3 + 1 && G.visibleEnough(p.x - 100, p.y, SZ, ALL), p);
p = G.clampPos(-5000, 5000, SZ, ALL);
ok('왼쪽 세로 화면(음수) 쪽으로도 가둠', p.x >= LEFT.x - 500 + 500 / 3 - 1 && p.y <= LEFT.y + LEFT.height - 500 / 3 + 1, p);

// ---- 기억·되찾기
const at = { x: 2400, y: 400 };                           // 오른쪽(150%) 화면 위
const rec = G.remember(at.x, at.y, SZ, ALL);
ok('기억: 좌표 + 어느 화면(id 2)의 어디쯤(가로 비율·바닥에서의 높이 비율)', rec.disp.id === 2 && rec.disp.rx > 0.4 && rec.disp.rx < 0.5 && rec.disp.ry >= 0 && rec.x === 2400, rec);
let r = G.restore(rec, SZ, ALL);
ok('화면 구성이 그대로면 기억한 자리 그대로', r.x === 2400 && r.y === 400 && /그대로/.test(r.why), r);
r = G.restore(rec, SZ, [MAIN, LEFT, TOP]);
ok('기억한 화면을 뺐으면 주 화면 기본 자리(화면 밖에 남지 않음)', r.x === 1380 && r.y === 540 && /없음/.test(r.why) && G.visibleEnough(r.x, r.y, SZ, [MAIN, LEFT, TOP]), r);
const moved = scr(2, -1707, 100, 1707, 960, 1.5);        // 같은 화면을 왼쪽(음수 좌표)으로 옮김
r = G.restore(rec, SZ, [MAIN, moved]);
ok('기억한 화면의 배치를 바꿨으면 그 화면 안 같은 비율 자리', G.areaAt(r.x + 250, r.y + 275, [MAIN, moved]) === moved && Math.abs((r.x + 250 - moved.x) / moved.width - rec.disp.rx) < 0.01, r);
const rescaled = scr(2, 1920, 0, 2560, 1440, 1);         // 같은 화면의 배율을 150% → 100% (논리 크기가 커짐)
r = G.restore(rec, SZ, [MAIN, rescaled]);
ok('기억한 화면의 배율이 바뀌었으면 그 화면 안 같은 비율 자리(발 높이 비율도)', G.areaAt(r.x + 250, r.y + 275, [MAIN, rescaled]) === rescaled
  && Math.abs((r.x + 250 - rescaled.x) / rescaled.width - rec.disp.rx) < 0.01 && Math.abs((rescaled.y + rescaled.height - (r.y + 500)) / rescaled.height - rec.disp.ry) < 0.01, r);
r = G.restore({ x: 2400, y: 400 }, SZ, ALL);
ok('0.1.12 까지의 기억(좌표만): 보이면 그대로', r.x === 2400 && r.y === 400, r);
r = G.restore({ x: 2400, y: 400 }, SZ, [MAIN]);
ok('0.1.12 까지의 기억(좌표만): 화면 밖이면 주 화면 기본 자리', r.x === 1380 && r.y === 540, r);
r = G.restore({ x: null, y: null }, SZ, ALL);
ok('기억이 없으면 주 화면 기본 자리', r.x === 1380 && r.y === 540 && /기억 없음/.test(r.why), r);
r = G.restore({ x: 'a', y: 3, disp: { id: 9 } }, SZ, ALL);
ok('기억이 깨졌어도 기본 자리', r.x === 1380 && r.y === 540, r);
const recL = G.remember(-700, 600, SZ, ALL);
r = G.restore(recL, SZ, ALL);
ok('왼쪽 세로 화면(음수 좌표)에 둔 자리도 그대로 되찾음', recL.disp.id === 3 && r.x === -700 && r.y === 600, [recL, r]);

// ---- 크기
ok('크기 퍼센트 ↔ 픽셀(100% = 500)', G.pctToPx(100) === 500 && G.pctToPx(50) === 250 && G.pctToPx(200) === 1000 && G.pxToPct(660) === 132 && G.pxToPct(380) === 76);
ok('범위 밖 퍼센트는 50~200 으로', G.clampPct(10) === 50 && G.clampPct(999) === 200 && G.clampPct('x') === 100 && G.pctToPx(1000) === 1000);
ok('화면보다 큰 크기는 화면 높이까지만', G.sizeIn(1000, RIGHT).h === RIGHT.height && G.sizeIn(400, RIGHT).w === 400);
p = G.resizeKeepFeet(1000, 400, { w: 500, h: 500 }, { w: 700, h: 700 }, ALL);
ok('크기를 바꿔도 발(아래 가운데)은 그 자리', p.x + 350 === 1000 + 250 && p.y + 700 === 400 + 500, p);

console.log(`\n펫 자리·크기 단위 시험: ${pass}/${pass + fail} 됨`);
process.exit(fail ? 1 : 0);
