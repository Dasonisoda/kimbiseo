'use strict';
const http = require('http');

const MAX_BODY = 8192;
const EXPRS = ['보통', '기쁨', '놀람', '졸림', '생각', '부끄러움', '화남'];
const EXPR_ALIAS = { 걱정: '생각', 기본: '보통', 말하기: '보통', neutral: '보통', listening: '보통', happy: '기쁨', surprised: '놀람', sleepy: '졸림',
  thinking: '생각', worried: '생각', shy: '부끄러움', angry: '화남', 웃음: '기쁨', 윙크: '기쁨', laugh: '기쁨', wink: '기쁨' };   // 웃음·윙크 등 원래 이름은 화면에 따로 넘김(raw)
const exprOf = n => (typeof n !== 'string' ? null : EXPRS.includes(n.trim()) ? n.trim() : EXPR_ALIAS[n.trim()] || EXPR_ALIAS[n.trim().toLowerCase()] || null);

function send(res, code, obj) {
  const b = Buffer.from(JSON.stringify(obj), 'utf8');
  res.writeHead(code, { 'Content-Type': 'application/json; charset=utf-8', 'Content-Length': b.length, 'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff' });
  res.end(b);
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    let n = 0; const chunks = [];
    req.on('data', c => {
      n += c.length;
      if (n > MAX_BODY) {   // 더 받지 않고 버림(응답은 보낸 뒤 연결을 닫음)
        req.removeAllListeners('data'); req.resume();
        reject(Object.assign(new Error('본문이 너무 큼(8KB 까지)'), { code: 413 })); return;
      }
      chunks.push(c);
    });
    req.on('end', () => {
      try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}')); }
      catch (e) { reject(Object.assign(new Error('JSON 이 아님'), { code: 400 })); }
    });
    req.on('error', reject);
  });
}

/* 펫 신호 HTTP 입구 — 이 컴퓨터 안(127.0.0.1)에서만 받음. 김비서 본체(app/pet_link/face.py)가 여기로 표정·입·동작을 보냄.
   POST /speak {"text","rate","wait","expr"}  /expr {"name","seconds"}  /mouth {"level","shape"}  /talk {"on"}  /bubble {"text","seconds"}
        /motion {"name"}  /emotion {"name"}  /skin {"id","temp"}  /size {"percent"}  /packs/auto {}(옷 받기 동의)       GET /status /emotions /outfits /extras /dances
   지키는 것: 127.0.0.1 에만 열기 · Host 머리글이 127.0.0.1/localhost(:포트) 가 아니면 거절(DNS 리바인딩 막기) ·
             Origin 머리글이 있으면 거절(웹페이지가 몰래 부르는 것 막기) · JSON 만 · 본문 8KB · 문장 1~300자
   포트 = 17961(쓰는 중이면 +1~+9, 실제 번호는 프로필 폴더 speak_port.txt) */
function startServer(h, basePort = 17961) {
  const tryPort = port => new Promise((resolve, reject) => {
    const srv = http.createServer(async (req, res) => {
      try {
        const hm = /^(?:127\.0\.0\.1|localhost)(?::(\d+))?$/i.exec(req.headers.host || '');
        const hostOk = !!hm && (!hm[1] || Number(hm[1]) === port);
        if (!hostOk) { if (h.log) h.log('HTTP 거절(Host) ' + String(req.headers.host).slice(0, 60) + ' ' + String(req.url).slice(0, 30)); return send(res, 403, { ok: false, error: 'Host 가 127.0.0.1 이 아님' }); }
        if (req.headers.origin !== undefined) return send(res, 403, { ok: false, error: '웹페이지에서 부르는 것은 막혀 있음' });
        const url = (req.url || '').split('?')[0];
        if (req.method === 'GET' && url === '/emotions') return send(res, 200, { ok: true, emotions: h.emotions ? h.emotions() : [] });
        if (req.method === 'GET' && url === '/outfits') return send(res, 200, { ok: true, ...(h.packs ? h.packs() : {}) });
        if (req.method === 'GET' && url === '/extras') return send(res, 200, { ok: true, ...(h.extras ? h.extras() : { motions: [], dances: [] }) });
        if (req.method === 'GET' && url === '/dances') return send(res, 200, { ok: true, dances: h.dances ? h.dances() : [] });
        if (req.method === 'GET' && url === '/status') return send(res, 200, { ok: true, ...h.status(), inputs: ['/speak', '/expr', '/mouth', '/lip', '/bubble', '/motion', '/skin', '/emotion', '/talk', '/packs/auto', '/size'] });
        if (!['/speak', '/expr', '/mouth', '/lip', '/bubble', '/motion', '/skin', '/emotion', '/talk', '/packs/auto', '/size'].includes(url)) return send(res, 404, { ok: false, error: '없는 주소' });
        if (req.method !== 'POST') return send(res, 405, { ok: false, error: 'POST 만' });
        if (!/^application\/json\s*(;|$)/i.test(req.headers['content-type'] || '')) return send(res, 415, { ok: false, error: 'Content-Type: application/json 만' });
        if (+(req.headers['content-length'] || 0) > MAX_BODY) { res.setHeader('Connection', 'close'); return send(res, 413, { ok: false, error: '본문이 너무 큼(8KB 까지)' }); }
        const body = await readJson(req);
        if (!body || typeof body !== 'object' || Array.isArray(body)) return send(res, 400, { ok: false, error: 'JSON 객체가 아님' });
        if (url === '/mouth' || url === '/lip') {
          if (!h.mouth) return send(res, 404, { ok: false, error: '없는 주소' });
          h.mouth(Math.max(0, Math.min(1, +body.level || 0)), typeof body.shape === 'string' ? body.shape : null);
          return send(res, 200, { ok: true });
        }
        if (url === '/talk') {
          if (!h.talk) return send(res, 404, { ok: false, error: '없는 주소' });
          h.talk(body.on !== false);
          return send(res, 200, { ok: true });
        }
        const emoOf = n => (h.emotionOf && typeof n === 'string' && n.trim() ? h.emotionOf(n.trim().slice(0, 30)) : null);
        if (url === '/emotion') {
          const em = emoOf(body.name);
          if (!em || !h.emotion) return send(res, 400, { ok: false, error: '감정 이름: ' + (h.emotions ? h.emotions().map(e => e.ko + '(' + e.name + ')').join(', ') : '') + ', 보통(끔)' });
          return send(res, 200, { ok: true, name: em, ...(h.emotion(em) || {}) });
        }
        if (url === '/bubble' || url === '/speak') { const em = emoOf(body.emotion); if (em && h.emotion) h.emotion(em); }
        if (url === '/bubble') {  // 말풍선만: {"text":"...", "seconds":선택}
          const t = typeof body.text === 'string' ? body.text.replace(/[\u0000-\u0008\u000b-\u001f\u007f]/g, ' ').trim().slice(0, 300) : '';
          if (!h.bubble) return send(res, 404, { ok: false, error: '없는 주소' });
          h.bubble(t, Math.max(0.5, Math.min(60, +body.seconds || 4)));
          return send(res, 200, { ok: true });
        }
        if (url === '/motion') {  // 실사 모드 동작: {"name":"인사|손흔들기|왼쪽걷기|오른쪽걷기|뒤돌기|대각선|앉기|눕기|일어나기|대기|말하기"}
          const name = typeof body.name === 'string' ? body.name.trim().slice(0, 30) : '';
          if (!name) return send(res, 400, { ok: false, error: '동작 이름(name)이 비었음' });
          const r = h.motion ? h.motion(name) : null;
          return send(res, 200, { ok: true, name, ...(r || {}) });
        }
        if (url === '/packs/auto') {   // 본체 처음 화면의 '옷 받기' 동의: {} → 옷이 없으면 기본 옷을 받기 시작
          if (!h.autoPack) return send(res, 404, { ok: false, error: '없는 주소' });
          const r = h.autoPack();
          return send(res, r.ok ? 200 : 409, r);
        }
        if (url === '/size') {   // 펫 크기(세밀): {"percent": 50~200} — 100 = '보통'
          const pct = Number(body.percent);
          if (!h.size || !Number.isFinite(pct) || pct < 50 || pct > 200) return send(res, 400, { ok: false, error: '크기는 50~200(퍼센트)' });
          return send(res, 200, h.size(Math.round(pct)));
        }
        if (url === '/skin') {
          const id = typeof body.id === 'string' ? body.id.trim().slice(0, 40) : '';
          if (!h.skin) return send(res, 404, { ok: false, error: '없는 주소' });
          const r = h.skin(id, body.temp === true);
          return send(res, r.ok ? 200 : 400, r);
        }
        if (url === '/expr') {
          const name = exprOf(body.name);
          const em0 = !name ? emoOf(body.name) : null;
          if (em0 && h.emotion) return send(res, 200, { ok: true, emotion: em0, ...(h.emotion(em0) || {}) });
          if (!name) return send(res, 400, { ok: false, error: '표정 이름: ' + EXPRS.join(', ') + ' (또는 ' + Object.keys(EXPR_ALIAS).join(', ') + ')' });
          const sec = Math.max(0.5, Math.min(30, +(body.seconds ?? body.sec) || 4));
          h.expr(name, sec, String(body.name).trim().slice(0, 30));   // 셋째 = 원래 이름(실사 모드는 웃음·윙크·걱정 등 따로 있음)
          return send(res, 200, { ok: true, name, seconds: sec });
        }
        const text = typeof body.text === 'string' ? body.text.replace(/[\u0000-\u0008\u000b-\u001f\u007f]/g, ' ').trim() : '';
        if (!text) return send(res, 400, { ok: false, error: 'text(말할 문장)가 비었음' });
        if ([...text].length > 300) return send(res, 400, { ok: false, error: '문장은 300자까지' });
        const rate = Math.max(-5, Math.min(5, Math.round(+body.rate || 0)));
        const expr = exprOf(body.expr);
        const r = await h.speak(text, rate, expr, !!body.wait);
        return send(res, 200, { ok: true, ...r });
      } catch (e) {
        h.log && h.log('HTTP 오류: ' + (e && e.message));
        if (!res.headersSent) {
          if (e.code === 413) res.setHeader('Connection', 'close');
          send(res, e.code >= 400 && e.code < 600 ? e.code : 500, { ok: false, error: String(e.message || e) });
        }
      }
    });
    srv.headersTimeout = 10000; srv.requestTimeout = 120000; srv.keepAliveTimeout = 2000;
    srv.once('error', reject);
    srv.listen(port, '127.0.0.1', () => { srv.removeListener('error', reject); resolve({ server: srv, port }); });
  });
  return (async () => {
    let last;
    for (let k = 0; k < 10; k++) {
      try { return await tryPort(basePort + k); } catch (e) { last = e; if (e.code !== 'EADDRINUSE') break; }
    }
    throw last;
  })();
}

module.exports = { startServer, EXPRS };
