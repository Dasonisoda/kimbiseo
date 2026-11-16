'use strict';
/* 펫 옷 꾸러미 받기(pet/packs.js download) 단위 시험 — 끊겨도 이어 받기·다시 시도·깨진 파일 다시 받기·실패 때 받은 만큼 남기기.
   실행: node tests/unit/test_pet_download.js      (electron 없이 node 만 · 이 PC 안 임시 서버 · 끝나면 닫음)
   서버는 일부러 고장 난 짓을 한다: 1MB 마다 끊기 · 이어 받기 안 받기 · 처음 한 번 깨진 파일 · 거절 · 무응답. */
const fs = require('fs');
const os = require('os');
const path = require('path');
const http = require('http');
const crypto = require('crypto');
const packs = require(path.join(__dirname, '..', '..', 'pet', 'packs.js'));

const SIZE = 3 * 1024 * 1024;
const GOOD = crypto.createHash('sha512').update('kimbiseo-test').digest();
const FILE = Buffer.concat(Array.from({ length: SIZE / 64 }, () => GOOD));
const BAD = Buffer.from(FILE); BAD[10] ^= 0x5a;
const SHA = crypto.createHash('sha256').update(FILE).digest('hex');
const hits = {};
let pass = 0, fail = 0;
const ok = (name, cond, extra) => { if (cond) { pass++; console.log('됨   ' + name); } else { fail++; console.log('안 됨 ' + name + ' ' + (extra === undefined ? '' : JSON.stringify(extra))); } };

const srv = http.createServer((req, res) => {
  const p = req.url.split('?')[0];
  const n = hits[p] = (hits[p] || 0) + 1;
  if (p === '/403') { res.writeHead(403); return res.end(); }
  if (p === '/404') { res.writeHead(404); return res.end(); }
  if (p === '/429-then-ok' && n <= 2) { res.writeHead(429, { 'Retry-After': '0' }); return res.end(); }
  let start = 0;
  const m = /bytes=(\d+)-/.exec(req.headers.range || '');
  if (m && p !== '/norange-cut') start = +m[1];
  if (p === '/416' && m) { res.writeHead(416); return res.end(); }
  const data = (p === '/corrupt' || (p === '/corrupt-once' && n === 1)) ? BAD : FILE;
  const body = data.subarray(start);
  res.writeHead(start ? 206 : 200, { 'Content-Length': body.length, ...(start ? { 'Content-Range': `bytes ${start}-${SIZE - 1}/${SIZE}` } : {}) });
  const limit = { '/cut': 1024 * 1024, '/norange-cut': 1024 * 1024, '/cut-small': 50 * 1024, '/stall': 50 * 1024 }[p];
  if (limit === undefined) return res.end(body);
  res.write(body.subarray(0, limit), () => { if (p !== '/stall') res.destroy(); });      // 뚝 끊음(/stall 은 아무것도 더 안 보냄)
});

(async () => {
  await new Promise(r => srv.listen(0, '127.0.0.1', r));
  const base = 'http://127.0.0.1:' + srv.address().port;
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), '김비서 펫 받기 시험 '));       // 한글·빈칸 든 경로
  const fast = { wait: () => Promise.resolve(), timeout: 1500 };
  const get = (p, name, opts) => packs.download(base + p, [], path.join(dir, name), null, SHA, { ...fast, ...(opts || {}) });
  const sizeOf = f => { try { return fs.statSync(f).size; } catch (e) { return -1; } };

  let r = await get('/ok', 'ok.hipcpet');
  ok('정상: 한 번에 받고 sha256 맞음', r.sha256 === SHA && r.attempts === 1 && sizeOf(r.path) === SIZE, r);

  const retries = [];
  r = await get('/cut', 'cut.hipcpet', { onRetry: (n, e, got) => retries.push(got) });
  ok('1MB 마다 끊겨도 이어 받아 끝까지(받은 만큼에서 이어짐)', r.sha256 === SHA && r.attempts >= 3 && r.attempts <= 5 && retries.length === r.attempts - 1
    && retries.every((x, i) => x > 900000 * (i + 1) && (i === 0 || x > retries[i - 1])), { r, retries });
  ok('다 받으면 .받는중 파일이 남지 않음', sizeOf(path.join(dir, 'cut.hipcpet.받는중')) === -1);

  r = await get('/corrupt-once', 'c1.hipcpet');
  ok('처음 받은 파일이 깨졌으면 저절로 새로 받음', r.sha256 === SHA && r.attempts === 2, r);

  let err = null;
  try { await get('/corrupt', 'c2.hipcpet'); } catch (e) { err = e; }
  ok('두 번 다 깨진 파일이면 넣지 않고 알림(sha) · 깨진 파일은 지움', !!err && err.code === 'sha' && sizeOf(path.join(dir, 'c2.hipcpet')) === -1
    && sizeOf(path.join(dir, 'c2.hipcpet.받는중')) === -1, err && err.message);

  err = null;
  try { await get('/norange-cut', 'nr.hipcpet'); } catch (e) { err = e; }
  ok('이어 받기를 안 받는 서버가 계속 끊으면 5번 뒤 그만둠(끝없이 돌지 않음)', !!err && err.code === 'net' && hits['/norange-cut'] === 6, { hits: hits['/norange-cut'], m: err && err.message });

  err = null;
  try { await get('/cut-small', 'cs.hipcpet'); } catch (e) { err = e; }
  ok('50KB 씩만 오는 회선(사실상 못 받음)은 5번 뒤 그만두고 받은 만큼은 남김', !!err && err.code === 'net' && sizeOf(path.join(dir, 'cs.hipcpet.받는중')) > 4 * 40 * 1024,
    { size: sizeOf(path.join(dir, 'cs.hipcpet.받는중')), hits: hits['/cut-small'] });

  err = null;
  try { await get('/403', 'f.hipcpet'); } catch (e) { err = e; }
  ok('거절(403)은 쉬운 말로 알리고 빨리 그만둠', !!err && err.status === 403 && /거절/.test(err.message) && hits['/403'] <= 3, err && err.message);

  err = null;
  try { await get('/404', 'n.hipcpet'); } catch (e) { err = e; }
  ok('없는 파일(404)은 다시 하지 않음', !!err && err.status === 404 && hits['/404'] === 1, err && err.message);

  r = await get('/429-then-ok', 'r.hipcpet');
  ok("'잠시 뒤 다시'(429) 뒤에는 받음", r.sha256 === SHA && r.attempts === 3, r);

  err = null;
  const t0 = Date.now();
  try { await get('/stall', 'st.hipcpet', { timeout: 400 }); } catch (e) { err = e; }
  ok('멈춘 회선은 기다리다 끊고(시간 초과) 5번 뒤 그만둠', !!err && err.code === 'net' && Date.now() - t0 < 15000, { ms: Date.now() - t0, m: err && err.message });

  fs.writeFileSync(path.join(dir, 'x.hipcpet.받는중'), FILE.subarray(0, 100));
  hits['/416'] = 0;
  r = await get('/416', 'x.hipcpet');
  ok('이어 받을 자리가 안 맞으면(416) 처음부터 다시 받음', r.sha256 === SHA, r);

  err = null;
  try { await packs.download('https://not-allowed.example/x.hipcpet', ['github.com'], path.join(dir, 'h.hipcpet'), null, SHA, fast); } catch (e) { err = e; }
  ok('허용 목록에 없는 주소는 받지 않음', !!err && /허용하지 않은 주소/.test(err.message), err && err.message);

  ok('까닭 말: 인증서', /인증서/.test(packs.netWhy({ code: 'UNABLE_TO_GET_ISSUER_CERT_LOCALLY', message: 'unable to get local issuer certificate' })));
  ok('까닭 말: PC 시계가 틀림', /시계/.test(packs.netWhy({ code: 'CERT_NOT_YET_VALID', message: 'certificate is not yet valid' })));
  {
    const tls = require('tls');
    const can = typeof tls.getCACertificates === 'function' && typeof tls.setDefaultCACertificates === 'function';
    const base = can ? tls.getCACertificates('bundled').length : 0;
    ok('보안 연결: 프로그램에 든 뿌리 + 윈도우 저장소의 뿌리를 둘 다 믿음(이 노드가 못 하면 건너뜀)', !can || (packs.ROOTS >= base && base > 100), { roots: packs.ROOTS, base });
  }
  ok('까닭 말: 주소 못 찾음', /주소를 찾지/.test(packs.netWhy({ code: 'ENOTFOUND', message: 'getaddrinfo ENOTFOUND x' })));
  ok('까닭 말: 끊김', /끊겼/.test(packs.netWhy({ code: 'ECONNRESET', message: 'aborted' })));

  srv.closeAllConnections && srv.closeAllConnections();
  srv.close();
  fs.rmSync(dir, { recursive: true, force: true });
  console.log(`펫 옷 받기 단위 시험: ${pass}/${pass + fail} 됨`);
  process.exit(fail ? 1 : 0);
})().catch(e => { console.log('시험 오류', e); process.exit(2); });
