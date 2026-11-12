'use strict';
/* 김비서 펫 옷 꾸러미(.hipcpet)
   꾸러미 = zip 파일 1개: pack.json(이름·버전·체형·성별·미리보기·클립·파일 목록) + signature.json(선택, ed25519) + preview + clips/ + music/(선택)
   설치 = <프로필>\옷\<id>\ 에 풀어 둠. 펫은 그 폴더들만 읽어 옷 목록을 만듦(프로그램 안에는 클립이 없음).
   지키는 것: 받는 확장자 webm·mp4·png·webp·jpg·jpeg·mp3·json·txt 만 / ../·절대경로·드라이브·역슬래시·숨은 이름 거부 /
     파일 하나 100MB·전체 1.2GB·3000개까지 / 암호·zip64·이상한 압축 거부 / 압축 풀린 크기·CRC 확인 /
     서명 '정품'(공개판 공개키로 pack.json 서명이 맞고, 파일마다 크기·sha256 까지 맞아야), 서명 없음 = 경고 후 허용, 서명이 있는데 틀림 = 거부.
   내려받기 = https 만(127.0.0.1·localhost 는 http 도 — 시험·내 PC 거울용), 넘겨주기(redirect)는 허용 목록 호스트로만, 옷 목록의 sha256 과 맞아야.
   지우기 = 그 옷 폴더만(경로가 <프로필>\옷\ 바로 아래인지 확인 후). */
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');
const crypto = require('crypto');

// 김비서 공개판 옷 꾸러미 공개키(비밀키는 저장소 밖에만 둠)
const PUBKEYS = { 'kimbiseo-pack-1': 'Ut4XUf5sy9m+GnTwcEDoTxsa3p6x4AiMlfUkh7wdJEs=' };
const EXT_OK = /\.(webm|mp4|png|webp|jpg|jpeg|mp3|json|txt)$/i;
const CLIP_EXT = /\.(webm|mp4)$/i, IMG_EXT = /\.(png|webp|jpg|jpeg)$/i;
const ID_RE = /^[0-9A-Za-z가-힣_-]{1,40}$/;
const LIM = { zip: 1.5e9, file: 100e6, total: 1.2e9, count: 3000, json: 2e6, ratio: 200 };

class PackError extends Error { constructor(msg, code) { super(msg); this.code = code || 'bad'; } }

// ---------------------------------------------------------------- zip 읽기(가운데 목록 기준)
let CRC_T = null;
function crc32(buf) {
  if (zlib.crc32) return zlib.crc32(buf) >>> 0;
  if (!CRC_T) { CRC_T = new Int32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; CRC_T[n] = c; } }
  let c = -1; for (let i = 0; i < buf.length; i++) c = CRC_T[(c ^ buf[i]) & 0xff] ^ (c >>> 8); return (c ^ -1) >>> 0;
}
function readAt(fd, pos, len) { const b = Buffer.alloc(len); let got = 0; while (got < len) { const n = fs.readSync(fd, b, got, len - got, pos + got); if (!n) break; got += n; } if (got !== len) throw new PackError('파일이 잘렸어요(zip 끝을 못 읽음)'); return b; }

function safeName(n) {
  if (!n || n.length > 200 || /[\\:\u0000-\u001f\u007f<>"|?*]/.test(n) || n.startsWith('/')) return false;
  const seg = n.split('/');
  // 윈도우 장치 이름(con·nul·com1 … — 확장자가 붙어도 장치로 열림)도 거부
  return seg.every(s => s && s !== '.' && s !== '..' && !s.startsWith('.') && !/[ .]$/.test(s) && !/^(con|prn|aux|nul|com\d|lpt\d)(\.|$)/i.test(s));
}

function openZip(file) {
  let st;
  try { st = fs.statSync(file); } catch (e) { throw new PackError(e.code === 'ENOENT' ? '파일을 찾을 수 없어요' : '파일을 열 수 없어요(' + (e.code || '') + ')'); }
  if (!st.isFile()) throw new PackError('파일이 아니에요');
  if (st.size > LIM.zip) throw new PackError('꾸러미가 너무 커요(1.5GB 까지)');
  if (st.size < 22) throw new PackError('옷 꾸러미 파일이 아니에요');
  const fd = fs.openSync(file, 'r');
  try {
    const tailLen = Math.min(st.size, 65557), tail = readAt(fd, st.size - tailLen, tailLen);
    let eo = -1;
    for (let i = tailLen - 22; i >= 0; i--) if (tail.readUInt32LE(i) === 0x06054b50) { eo = i; break; }
    if (eo < 0) throw new PackError('옷 꾸러미 파일이 아니에요(zip 아님)');
    const count = tail.readUInt16LE(eo + 10), cdSize = tail.readUInt32LE(eo + 12), cdOff = tail.readUInt32LE(eo + 16);
    if (count === 0xffff || cdOff === 0xffffffff || cdSize === 0xffffffff) throw new PackError('zip64 꾸러미는 받지 않아요');
    if (count > LIM.count) throw new PackError('파일이 너무 많아요(3000개까지)');
    if (cdOff + cdSize > st.size) throw new PackError('zip 목록이 깨졌어요');
    const cd = readAt(fd, cdOff, cdSize);
    const entries = new Map();
    let p = 0, total = 0;
    for (let k = 0; k < count; k++) {
      if (p + 46 > cd.length || cd.readUInt32LE(p) !== 0x02014b50) throw new PackError('zip 목록이 깨졌어요');
      const flags = cd.readUInt16LE(p + 8), method = cd.readUInt16LE(p + 10), crc = cd.readUInt32LE(p + 16);
      const csize = cd.readUInt32LE(p + 20), usize = cd.readUInt32LE(p + 24);
      const nl = cd.readUInt16LE(p + 28), xl = cd.readUInt16LE(p + 30), cl = cd.readUInt16LE(p + 32), lho = cd.readUInt32LE(p + 42);
      const name = cd.slice(p + 46, p + 46 + nl).toString(flags & 0x800 ? 'utf8' : 'latin1');
      p += 46 + nl + xl + cl;
      if (name.endsWith('/')) continue;                         // 폴더 표시
      if (!safeName(name)) throw new PackError('위험한 파일 이름이 들어 있어요: ' + name.slice(0, 60));
      if (!EXT_OK.test(name)) throw new PackError('받지 않는 종류의 파일이 들어 있어요: ' + name.slice(0, 60));
      if (flags & 0x1) throw new PackError('암호 걸린 꾸러미는 받지 않아요');
      if (method !== 0 && method !== 8) throw new PackError('모르는 압축 방식이에요: ' + name.slice(0, 60));
      if (usize > LIM.file) throw new PackError('파일 하나가 너무 커요(100MB 까지): ' + name.slice(0, 60));
      if (method === 0 && csize !== usize) throw new PackError('zip 크기가 맞지 않아요: ' + name.slice(0, 60));
      if (method === 8 && usize > Math.max(1e6, csize * LIM.ratio)) throw new PackError('압축 비율이 이상해요(압축 폭탄 의심): ' + name.slice(0, 60));
      const key = name.toLowerCase();
      if (entries.has(key)) throw new PackError('같은 이름 파일이 두 번 들어 있어요: ' + name.slice(0, 60));
      total += usize;
      if (total > LIM.total) throw new PackError('꾸러미 안 파일이 너무 커요(합 1.2GB 까지)');
      if (lho + 30 > st.size) throw new PackError('zip 목록이 깨졌어요');
      entries.set(key, { name, method, crc, csize, usize, lho });
    }
    return { fd, entries, size: st.size };
  } catch (e) { fs.closeSync(fd); throw e; }
}

function readEntry(z, e) {
  const lh = readAt(z.fd, e.lho, 30);
  if (lh.readUInt32LE(0) !== 0x04034b50) throw new PackError('zip 파일 머리가 깨졌어요: ' + e.name);
  const start = e.lho + 30 + lh.readUInt16LE(26) + lh.readUInt16LE(28);
  const raw = readAt(z.fd, start, e.csize);
  let b = raw;
  if (e.method === 8) {
    try { b = zlib.inflateRawSync(raw, { maxOutputLength: e.usize + 1 }); }
    catch (err) { throw new PackError('압축이 깨졌거나 크기가 맞지 않아요: ' + e.name); }
  }
  if (b.length !== e.usize) throw new PackError('풀린 크기가 맞지 않아요: ' + e.name);
  if (crc32(b) !== e.crc) throw new PackError('파일이 깨졌어요(CRC): ' + e.name);
  return b;
}

// ---------------------------------------------------------------- 꾸러미 살펴보기(설치 전 검사)
const num = v => typeof v === 'number' && Number.isFinite(v);
function checkPack(pj, z) {
  if (!pj || typeof pj !== 'object' || Array.isArray(pj)) throw new PackError('pack.json 이 이상해요');
  if (pj.format !== 'hipcpet/1') throw new PackError('모르는 꾸러미 형식이에요(' + String(pj.format).slice(0, 20) + ')');
  if (typeof pj.id !== 'string' || !ID_RE.test(pj.id)) throw new PackError('옷 id 가 이상해요');
  if (typeof pj.name !== 'string' || !pj.name.trim() || pj.name.length > 60) throw new PackError('옷 이름이 이상해요');
  if ((pj.character || '실사') !== '실사') throw new PackError('실사 펫 옷만 받아요');
  if (!pj.clips || typeof pj.clips !== 'object' || !pj.clips.idle) throw new PackError('클립 목록(idle 포함)이 없어요');
  const has = n => typeof n === 'string' && z.entries.has(n.toLowerCase());
  for (const [n, c] of Object.entries(pj.clips)) {
    if (!/^[A-Za-z0-9_]{1,40}$/.test(n) || !c || typeof c !== 'object') throw new PackError('클립 이름이 이상해요: ' + n.slice(0, 40));
    if (!has(c.file) || !CLIP_EXT.test(c.file)) throw new PackError('클립 파일이 없어요: ' + n);
    for (const k of ['w', 'h', 'x', 'y', 'frames', 'dur']) if (!num(c[k])) throw new PackError('클립 값이 이상해요: ' + n + '.' + k);
    // 있을 수도 있는 값(걷기·유지·춤): 모양이 다르면 화면이 동작 중 멈추므로 여기서 거부
    for (const k of ['headX', 'headY', 'loops', 'enter', 'cycle', 'stopAt']) if (c[k] !== undefined && c[k] !== null && !num(c[k])) throw new PackError('클립 값이 이상해요: ' + n + '.' + k);
    for (const k of ['seamOut', 'oneVideo', 'music']) if (c[k] !== undefined && typeof c[k] !== 'boolean') throw new PackError('클립 값이 이상해요: ' + n + '.' + k);
    if (c.rootDx !== undefined && !(Array.isArray(c.rootDx) && c.rootDx.length <= 5000 && c.rootDx.every(num))) throw new PackError('클립 값이 이상해요: ' + n + '.rootDx');
    if (c.motion !== undefined && c.motion !== null && (typeof c.motion !== 'object' || Array.isArray(c.motion) || JSON.stringify(c.motion).length > 2000)) throw new PackError('클립 값이 이상해요: ' + n + '.motion');
    if (c.frames < 1 || c.frames > 20000 || c.w < 1 || c.h < 1 || c.w > 4096 || c.h > 4096) throw new PackError('클립 크기가 이상해요: ' + n);
  }
  if (!has(pj.preview) || !IMG_EXT.test(pj.preview)) throw new PackError('미리보기 그림이 없어요');
  if (pj.music !== undefined && !Array.isArray(pj.music)) throw new PackError('노래 목록이 이상해요');
  for (const m of pj.music || []) if (!m || !has(m.file) || !/\.mp3$/i.test(m.file)) throw new PackError('노래 파일이 없어요');
  if (pj.stage && !(num(pj.stage.w) && num(pj.stage.h))) throw new PackError('무대 크기가 이상해요');
}

function inspect(file) {
  const z = openZip(file);
  try {
    const pe = z.entries.get('pack.json');
    if (!pe) throw new PackError('pack.json 이 없어요(옷 꾸러미가 아님)');
    if (pe.usize > LIM.json) throw new PackError('pack.json 이 너무 커요');
    const pjBytes = readEntry(z, pe);
    let pj;
    try { pj = JSON.parse(pjBytes.toString('utf8')); } catch (e) { throw new PackError('pack.json 을 읽을 수 없어요'); }
    checkPack(pj, z);
    let sig = '없음';
    const se = z.entries.get('signature.json');
    if (se) {
      let s = null;
      try { s = JSON.parse(readEntry(z, se).toString('utf8')); } catch (e) { /* 아래에서 틀림 */ }
      const pub = s && PUBKEYS[s.key];
      let ok = false;
      if (pub && s.alg === 'ed25519' && typeof s.sig === 'string') {
        try {
          const k = crypto.createPublicKey({ key: { kty: 'OKP', crv: 'Ed25519', x: Buffer.from(pub, 'base64').toString('base64url') }, format: 'jwk' });
          ok = crypto.verify(null, pjBytes, k, Buffer.from(s.sig, 'base64'));
        } catch (e) { ok = false; }
      }
      sig = ok ? '정품' : '틀림';
    }
    const files = pj.files && typeof pj.files === 'object' ? pj.files : null;
    if (sig === '정품') {   // 정품 = 파일마다 목록(크기·sha256)과 맞아야 하고, 목록 밖 파일 없음
      if (!files) throw new PackError('정품 꾸러미에 파일 목록이 없어요');
      for (const [k, e] of z.entries) if (k !== 'pack.json' && k !== 'signature.json' && !Object.keys(files).some(f => f.toLowerCase() === k)) throw new PackError('목록에 없는 파일이 들어 있어요: ' + e.name);
      for (const f of Object.keys(files)) if (!z.entries.has(f.toLowerCase())) throw new PackError('목록의 파일이 빠졌어요: ' + f);
    }
    return { pack: pj, sig, z, files };
  } catch (e) { fs.closeSync(z.fd); throw e; }
}

// ---------------------------------------------------------------- 설치·목록·지우기
function packsDir(user) { const d = path.join(user, '옷'); fs.mkdirSync(d, { recursive: true }); return d; }
function insideDir(dir, id) {   // <프로필>\옷\<id> 가 정말 그 바로 아래(이름 규칙·링크 아님)인지
  if (typeof id !== 'string' || !ID_RE.test(id)) return null;
  const base = path.resolve(dir), p = path.resolve(base, id);
  if (path.dirname(p) !== base || path.basename(p) !== id) return null;
  try { if (fs.lstatSync(p).isSymbolicLink()) return null; } catch (e) { /* 없음 = 새로 */ }
  return p;
}

/** 꾸러미 파일 → <user>\옷\<id>. opts.requireSigned 면 정품만. opts.allowUnsigned 가 아니면 서명 없는 꾸러미는 code 'unsigned' 로 멈춤(화면이 경고 후 다시 부름) */
function install(user, file, opts = {}) {
  const info = inspect(file);
  const { pack, sig, z, files } = info;
  try {
    if (sig === '틀림') throw new PackError('서명이 맞지 않아요 — 파일이 바뀌었을 수 있어 넣지 않았어요', 'badsig');
    if (sig !== '정품' && opts.requireSigned) throw new PackError('옷 목록에는 정품이라고 돼 있는데 받은 파일에 정품 서명이 없어요 — 넣지 않았어요', 'needsig');
    if (sig === '없음' && !opts.allowUnsigned) throw Object.assign(new PackError('정품 서명이 없는 꾸러미예요', 'unsigned'), { pack: { id: pack.id, name: pack.name } });
    const dir = packsDir(user);
    const final = insideDir(dir, pack.id);
    if (!final) throw new PackError('옷 id 가 이상해요');
    const tmp = path.join(dir, '_받는중_' + process.pid + '_' + Date.now());
    fs.mkdirSync(tmp);
    try {
      for (const [, e] of z.entries) {
        const b = readEntry(z, e);
        if (files) {
          const meta = Object.entries(files).find(([f]) => f.toLowerCase() === e.name.toLowerCase());
          if (meta && (meta[1].size !== b.length || meta[1].sha256 !== crypto.createHash('sha256').update(b).digest('hex'))) throw new PackError('파일 내용이 목록과 달라요: ' + e.name);
          if (!meta && sig === '정품' && !['pack.json', 'signature.json'].includes(e.name.toLowerCase())) throw new PackError('목록에 없는 파일: ' + e.name);
        }
        const out = path.resolve(tmp, ...e.name.split('/'));
        if (!out.startsWith(tmp + path.sep)) throw new PackError('위험한 파일 이름: ' + e.name);
        fs.mkdirSync(path.dirname(out), { recursive: true });
        fs.writeFileSync(out, b, { flag: 'wx' });
      }
      fs.writeFileSync(path.join(tmp, '_설치정보.json'), JSON.stringify({ sig, from: path.basename(file), installed: new Date().toISOString(),
        sha256: opts.sha256 || null, version: pack.version || '' }, null, 1), 'utf8');
      let replaced = false;
      if (fs.existsSync(final)) {   // 같은 옷 다시 넣기 = 옛 폴더를 치우고 새것으로
        const old = path.join(dir, '_지울것_' + pack.id + '_' + Date.now());
        fs.renameSync(final, old); replaced = true;
        try { fs.rmSync(old, { recursive: true, force: true }); } catch (e) { /* 다음 켤 때 치움 */ }
      }
      fs.renameSync(tmp, final);
      return { ok: true, id: pack.id, name: pack.name, version: pack.version || '', signed: sig === '정품', replaced };
    } catch (e) { try { fs.rmSync(tmp, { recursive: true, force: true }); } catch (e2) { /* 무시 */ } throw e; }
  } finally { fs.closeSync(z.fd); }
}

const fileUrl = f => 'file:///' + f.replace(/\\/g, '/').split('/').map(encodeURIComponent).join('/').replace(/^([A-Za-z])%3A/, '$1:');

/** 입 맞추기 메타(클립 장별 입 벌림): ①pack.json 클립의 "mouth" 그대로 ②옷 폴더 mouth.json(장 수·클립 파일 크기가 같을 때만). 돌려줌: 메타가 붙은 클립 수 */
function attachMouth(dir, id, clips, files) {
  let meta = null;
  for (const f of [path.join(dir, 'mouth.json')]) {
    try {
      const m = JSON.parse(fs.readFileSync(f, 'utf8'));
      if (m && m.format === 'hipcpet-mouth/1' && m.clips && typeof m.clips === 'object') { meta = m; break; }
    } catch (e) { /* 없음 */ }
  }
  let n = 0;
  for (const [k, c] of Object.entries(clips)) {
    if (typeof c.mouth === 'string') { if (c.mouth.length === c.frames * 2) n++; else delete c.mouth; continue; }
    const m = meta && meta.clips[k];
    if (!m || m.frames !== c.frames || typeof m.hex !== 'string' || m.hex.length !== c.frames * 2) continue;
    try { if (fs.statSync(files[k]).size !== m.size) continue; } catch (e) { continue; }
    c.mouth = m.hex; n++;
  }
  return n;
}

/** 설치된 옷 목록. 반쯤 남은 _받는중·_지울것 폴더는 치움 */
function list(user) {
  const dir = packsDir(user), out = [];
  for (const n of fs.readdirSync(dir)) {
    const p = path.join(dir, n);
    if (n.startsWith('_')) { if (/^_(받는중|지울것)_/.test(n)) try { fs.rmSync(p, { recursive: true, force: true }); } catch (e) { /* 쓰는 중 */ } continue; }
    if (!insideDir(dir, n)) continue;
    try {
      const pj = JSON.parse(fs.readFileSync(path.join(p, 'pack.json'), 'utf8'));
      if (pj.id !== n || !pj.clips || !pj.clips.idle) continue;
      let meta = {}; try { meta = JSON.parse(fs.readFileSync(path.join(p, '_설치정보.json'), 'utf8')); } catch (e) { /* 없음 */ }
      const clips = {}, files = {};
      for (const [k, c] of Object.entries(pj.clips)) {
        const f = path.resolve(p, ...String(c.file).split('/'));
        if (!f.startsWith(p + path.sep) || !fs.existsSync(f)) continue;
        clips[k] = { ...c, url: fileUrl(f) };
        files[k] = f;
      }
      if (!clips.idle) continue;
      const mouthN = attachMouth(p, pj.id, clips, files);
      const prev = pj.preview ? path.resolve(p, ...String(pj.preview).split('/')) : null;
      out.push({ id: pj.id, name: pj.name, version: pj.version || '', body: pj.body || '', gender: pj.gender || '',
        signed: meta.sig === '정품', dir: p, img: prev && prev.startsWith(p + path.sep) && fs.existsSync(prev) ? fileUrl(prev) : null,
        stage: pj.stage, fps: pj.fps, walkSpeed: pj.walkSpeed, clips,
        music: (pj.music || []).map(m => ({ ...m, path: path.resolve(p, ...String(m.file).split('/')) })).filter(m => m.path.startsWith(p + path.sep) && fs.existsSync(m.path)),
        installed: meta.installed || null, mouth: mouthN, from: meta.from || '' });
    } catch (e) { /* 깨진 폴더는 건너뜀 */ }
  }
  out.sort((a, b) => (a.installed || '').localeCompare(b.installed || '') || a.id.localeCompare(b.id));
  return out;
}

/** 옷 폴더 지우기: <user>\옷\<id> 바로 그 폴더만 */
function remove(user, id) {
  const dir = packsDir(user), p = insideDir(dir, id);
  if (!p || !fs.existsSync(path.join(p, 'pack.json'))) throw new PackError('그 옷이 없어요');
  const old = path.join(dir, '_지울것_' + id + '_' + Date.now());
  fs.renameSync(p, old);   // 먼저 이름을 바꿔 목록에서 바로 빠지게(쓰던 영상이 잠겨 있어도)
  try { fs.rmSync(old, { recursive: true, force: true }); } catch (e) { /* 다음 켤 때 list 가 치움 */ }
  return { ok: true, id };
}

// ---------------------------------------------------------------- 내려받기(옷 목록 packs.json·꾸러미 파일)
const http = require('http');
const https = require('https');
const LOOP = new Set(['127.0.0.1', 'localhost', '[::1]']);
/** 받아도 되는 주소인지: https + 허용 목록 호스트, 또는 이 PC(127.0.0.1·localhost, http 도). 아니면 PackError */
function checkUrl(u, allowed) {
  let url;
  try { url = u instanceof URL ? u : new URL(String(u)); } catch (e) { throw new PackError('주소가 이상해요', 'net'); }
  if (url.username || url.password) throw new PackError('주소에 아이디·비밀번호를 넣을 수 없어요', 'net');
  const host = url.hostname.toLowerCase();
  if (LOOP.has(host)) { if (url.protocol === 'http:' || url.protocol === 'https:') return url; }
  else if (url.protocol === 'https:' && (allowed || []).some(h => host === h || host.endsWith('.' + h))) return url;
  throw new PackError('허용하지 않은 주소예요(' + url.protocol + '//' + host + ')', 'net');
}
/** GET 하나: 넘겨주기 최대 5번(매번 주소 검사). onRes(res, req) 는 200 응답에서 부름 */
function request(u, allowed, opts, onRes, reject, hops = 0) {
  let url;
  try { url = checkUrl(u, allowed); } catch (e) { return reject(e); }
  const lib = url.protocol === 'https:' ? https : http;
  const req = lib.get(url, { timeout: opts.timeout || 15000, headers: { Accept: opts.accept || '*/*', 'User-Agent': 'KimBiseoPet' } }, res => {
    if ([301, 302, 303, 307, 308].includes(res.statusCode) && res.headers.location) {
      res.resume();
      if (hops >= 5) return reject(new PackError('넘겨주기가 너무 많아요', 'net'));
      let next;
      try { next = new URL(res.headers.location, url); } catch (e) { return reject(new PackError('넘겨준 주소가 이상해요', 'net')); }
      return request(next, allowed, opts, onRes, reject, hops + 1);
    }
    if (res.statusCode !== 200) { res.resume(); return reject(new PackError('응답 ' + res.statusCode, 'net')); }
    onRes(res, req);
  });
  req.on('timeout', () => req.destroy(new Error('시간 초과')));
  req.on('error', e => reject(e instanceof PackError ? e : new PackError('연결 안 됨(' + e.message + ')', 'net')));
  return req;
}
function getJson(u, allowed, max = 2e6) {
  return new Promise((resolve, reject) => {
    request(u, allowed, { accept: 'application/json' }, (res, req) => {
      const ch = []; let n = 0;
      res.on('data', c => { n += c.length; if (n > max) req.destroy(new Error('응답이 너무 큼')); else ch.push(c); });
      res.on('end', () => { try { resolve(JSON.parse(Buffer.concat(ch).toString('utf8'))); } catch (e) { reject(new PackError('옷 목록을 못 읽음', 'net')); } });
    }, reject);
  });
}
function getBytes(u, allowed, max = 2e6) {
  return new Promise((resolve, reject) => {
    request(u, allowed, {}, (res, req) => {
      const ch = []; let n = 0;
      res.on('data', c => { n += c.length; if (n > max) req.destroy(new Error('너무 큼')); else ch.push(c); });
      res.on('end', () => resolve({ b: Buffer.concat(ch), t: String(res.headers['content-type'] || '') }));
    }, reject);
  });
}
/** 꾸러미 파일 받기 → dest. expectSha(목록의 sha256)가 있으면 맞아야 함. 받는 중에는 dest + '.받는중' */
function download(u, allowed, dest, onProgress, expectSha) {
  return new Promise((resolve, reject) => {
    const tmp = dest + '.받는중';
    const fail = e => { try { fs.rmSync(tmp, { force: true }); } catch (e2) { /* 없음 */ } reject(e); };
    request(u, allowed, { timeout: 60000 }, (res, req) => {
      const total = +res.headers['content-length'] || 0;
      if (total > LIM.zip) { req.destroy(); return fail(new PackError('꾸러미가 너무 커요')); }
      const h = crypto.createHash('sha256'), out = fs.createWriteStream(tmp);
      let got = 0, last = 0;
      res.on('data', c => {
        got += c.length; h.update(c);
        if (got > LIM.zip) { req.destroy(new Error('너무 큼')); return; }
        if (onProgress && Date.now() - last > 300) { last = Date.now(); onProgress(got, total); }
      });
      res.pipe(out);
      out.on('finish', () => {
        if (total && got !== total) return fail(new PackError('받다가 끊겼어요', 'net'));
        const sha = h.digest('hex');
        if (expectSha && sha !== expectSha) return fail(new PackError('받은 파일이 옷 목록과 달라요(sha256) — 넣지 않았어요', 'sha'));
        fs.renameSync(tmp, dest); if (onProgress) onProgress(got, total || got); resolve({ path: dest, size: got, sha256: sha });
      });
      out.on('error', fail);
      res.on('error', e => { out.destroy(); fail(new PackError('받다가 끊겼어요(' + e.message + ')', 'net')); });
    }, fail);
  });
}

// ---------------------------------------------------------------- 파일 연결(.hipcpet 두 번 누르기 → 이 펫이 받음). 현재 사용자(HKCU)만.
// 저절로 하지 않음(같은 PC 의 다른 프로그램 연결을 덮지 않게) — 설정 "assoc": true 또는 --assoc 로 켤 때만.
function registerAssoc(exe, profile, log, appDir) {   // appDir = 묶지 않은 펫(electron.exe + pet 폴더)일 때 그 폴더
  const { spawnSync } = require('child_process');
  const cmd = `"${exe}"` + (appDir ? ` "${appDir}"` : '') + (profile ? ` --profile="${profile}"` : '') + ' --add-pack="%1"';
  const K = (...parts) => parts.join(String.fromCharCode(92));   // 레지스트리 경로(역슬래시로 이음)
  const base = K('HKCU', 'Software', 'Classes');
  const PROG = K(base, 'KimBiseo.PetPack');
  const runs = [
    [K(base, '.hipcpet'), 'KimBiseo.PetPack'],
    [PROG, '김비서 펫 옷 꾸러미'],
    [K(PROG, 'DefaultIcon'), `"${exe}",0`],
    [K(PROG, 'shell', 'open', 'command'), cmd],
  ];
  //   (reg 출력은 한글 윈도우에서 cp949 → 그대로 utf8 로 읽으면 한글 경로가 깨져 매번 다시 씀)
  const q = spawnSync('reg', ['query', K(PROG, 'shell', 'open', 'command'), '/ve'], { windowsHide: true });
  let cur = '';
  try { cur = new TextDecoder('euc-kr').decode(q.stdout || Buffer.alloc(0)); } catch (e) { cur = String(q.stdout || ''); }
  if (q.status === 0 && (cur.includes(cmd) || String(q.stdout || '').includes(cmd))) return false;
  for (const [k, v] of runs) {
    const r = spawnSync('reg', ['add', k, '/ve', '/d', v, '/f'], { encoding: 'utf8', windowsHide: true });
    if (r.status !== 0) { if (log) log('파일 연결 실패 ' + k + ' ' + (r.stderr || '').trim().slice(0, 120)); return false; }
  }
  if (log) log('파일 연결(.hipcpet) → ' + cmd);
  return true;
}

module.exports = { inspect, install, list, remove, getJson, getBytes, download, checkUrl, registerAssoc, insideDir, PackError, fileUrl, ID_RE, PUBKEYS };
