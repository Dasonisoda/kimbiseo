'use strict';
/* 김비서 펫 자리·크기 계산 — 화면(모니터) 목록만 받아 계산한다(Electron 없이 시험: tests/unit/test_pet_geometry.js).
   화면 = { id, x, y, width, height, scale, primary } — 작업 영역(작업 표시줄 뺀 곳), 좌표는 Electron 이 쓰는 논리 좌표(DIP).
   왜 따로 뒀나(0.1.13 — '다른 모니터로 옮기면 좌표가 틀어진다'):
     · 자리를 좌표 두 개(x, y)로만 기억해서, 모니터를 빼거나 배치·배율을 바꾸면(논리 좌표계가 통째로 바뀜) 엉뚱한 곳·화면 밖에 떴다.
       → 어느 화면의 어디쯤(가로 비율 · 바닥에서의 높이 비율)인지도 같이 기억하고, 켤 때 그 화면이 있으면 그 안 같은 자리로, 없으면 주 화면 기본 자리로.
     · 기본 자리가 '화면 목록의 첫 화면'이라 주 화면이 아닌 곳에 뜰 수 있었다 → 주 화면 먼저.
     · 윈도우가 창을 옮겨 놓은 뒤(모니터 빼기 등)에도 펫이 기억한 자리(pos)는 옛 값이라 누르는 자리·말풍선이 어긋났다 → main.js 가 화면이 바뀌면 진짜 창 자리를 다시 읽음. */

const PCT_MIN = 50, PCT_MAX = 200, BASE_PX = 500;      // 크기 100% = '보통'(500)

function primaryFirst(areas) {
  const p = areas.findIndex(a => a.primary);
  return p > 0 ? [areas[p], ...areas.slice(0, p), ...areas.slice(p + 1)] : areas.slice();
}
function areaAt(cx, cy, areas) {
  return areas.find(a => cx >= a.x && cx < a.x + a.width && cy >= a.y && cy < a.y + a.height) || null;
}
function nearestArea(cx, cy, areas) {
  let best = null, bd = Infinity;
  for (const a of areas) {
    const dx = Math.max(a.x - cx, 0, cx - (a.x + a.width)), dy = Math.max(a.y - cy, 0, cy - (a.y + a.height));
    if (dx * dx + dy * dy < bd) { bd = dx * dx + dy * dy; best = a; }
  }
  return best;
}
// 캐릭터 몸통(창 가운데 조금 아래)이 어느 화면 안에 있나
function visibleEnough(x, y, sz, areas) {
  return !!areaAt(x + sz.w / 2, y + sz.h * 0.55, areas);
}
// 어느 화면에서든 캐릭터가 적어도 1/3 은 보이게
function clampPos(x, y, sz, areas) {
  const best = nearestArea(x + sz.w / 2, y + sz.h / 2, areas);
  const mx = sz.w / 3, my = sz.h / 3;
  return {
    x: Math.round(Math.min(Math.max(x, best.x - sz.w + mx), best.x + best.width - mx)),
    y: Math.round(Math.min(Math.max(y, best.y - sz.h * 0.25), best.y + best.height - my)),
  };
}
// 기본 자리: 주 화면 오른쪽 아래
function defaultPos(sz, areas) {
  const a = primaryFirst(areas)[0];
  return { x: Math.round(a.x + a.width - sz.w - 40), y: Math.round(a.y + a.height - sz.h) };
}
// 기억할 값: 좌표 + 어느 화면의 어디쯤(발 = 아래 가운데 기준)
function remember(x, y, sz, areas) {
  const fx = x + sz.w / 2, fy = y + sz.h;
  const a = areaAt(fx, y + sz.h * 0.55, areas) || nearestArea(fx, y + sz.h / 2, areas);
  return { x: Math.round(x), y: Math.round(y),
    disp: { id: a.id, x: a.x, y: a.y, width: a.width, height: a.height, scale: a.scale || 1,
      rx: +((fx - a.x) / a.width).toFixed(4), ry: +((a.y + a.height - fy) / a.height).toFixed(4) } };
}
// 기억한 값 → 이번에 놓을 자리와 까닭
function restore(saved, sz, areas) {
  const sx = saved && saved.x, sy = saved && saved.y, d = saved && saved.disp;
  const dflt = why => ({ ...defaultPos(sz, areas), why });
  if (!Number.isFinite(sx) || !Number.isFinite(sy)) return dflt('기억 없음 → 주 화면 기본 자리');
  if (!d || !Number.isFinite(d.rx)) {                       // 0.1.12 까지의 기억(좌표만)
    if (!visibleEnough(sx, sy, sz, areas)) return dflt('기억한 자리가 화면 밖 → 주 화면 기본 자리');
    return { ...clampPos(sx, sy, sz, areas), why: '기억한 좌표 그대로' };
  }
  const same = a => a.x === d.x && a.y === d.y && a.width === d.width && a.height === d.height;
  let a = areas.find(z => z.id === d.id && same(z));
  if (a && visibleEnough(sx, sy, sz, areas)) return { ...clampPos(sx, sy, sz, areas), why: '기억한 화면 그대로' };
  a = areas.find(z => z.id === d.id) || areas.find(same);
  if (!a) return dflt('기억한 화면이 없음 → 주 화면 기본 자리');
  // 같은 화면인데 자리·크기·배율이 바뀜 → 그 화면 안 같은 비율 자리(발 기준)
  const x = a.x + d.rx * a.width - sz.w / 2, y = a.y + a.height - d.ry * a.height - sz.h;
  const p = clampPos(x, y, sz, [a]);
  return { ...p, why: '기억한 화면이 옮겨졌거나 배율이 바뀜 → 그 화면 안 같은 자리' };
}
// 크기: 퍼센트(50~200, 100 = 보통) ↔ 픽셀 · 화면보다 크지 않게
function clampPct(p) { return Math.max(PCT_MIN, Math.min(PCT_MAX, Math.round(Number(p) || 100))); }
function pctToPx(p) { return Math.round(BASE_PX * clampPct(p) / 100); }
function pxToPct(px) { return Math.round(100 * px / BASE_PX); }
function sizeIn(px, area) { const h = Math.min(px, area.height); return { w: h, h }; }
// 크기를 바꿀 때: 발 위치(아래 가운데)를 그대로 둔 새 자리
function resizeKeepFeet(x, y, oldSz, newSz, areas) {
  return clampPos(Math.round(x + oldSz.w / 2 - newSz.w / 2), Math.round(y + oldSz.h - newSz.h), newSz, areas);
}

module.exports = { PCT_MIN, PCT_MAX, BASE_PX, primaryFirst, areaAt, nearestArea, visibleEnough, clampPos, defaultPos, remember, restore,
  clampPct, pctToPx, pxToPct, sizeIn, resizeKeepFeet };
