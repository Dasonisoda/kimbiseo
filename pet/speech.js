'use strict';
/* 말하기: 윈도우 내장 한국어 음성(tts.ps1, 켜 둔 PowerShell 1개) → wav + 음소 시각 → 입 모양 시간표.
   김비서 목소리 서버(본체가 켠 것)가 있으면 그쪽(/tts_lip)을 먼저 씀.
   PowerShell 은 처음 말할 때 켜고, 2분 동안 일이 없으면 끔(가만히 있을 때 메모리 아끼기). */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const FPS = 100, LEAD = 0.04, MIN_HOLD = 0.045;
const VOWEL = { a: ['아', 1.0], 'ʌ': ['오', 0.8], o: ['오', 0.95], u: ['우', 0.9], 'ɯ': ['이', 0.55], i: ['이', 0.75],
  e: ['에', 0.9], 'ɛ': ['에', 0.95], 'ø': ['오', 0.8], y: ['우', 0.8], 'ɐ': ['아', 0.9], 'ə': ['오', 0.7] };
const GLIDE = { j: ['이', 0.45], w: ['우', 0.55], 'ɰ': ['이', 0.4] };
const LIPS = new Set(['m', 'p', 'b']);
const TONGUE = new Set(['l', 'ɾ', 'r']);
const SIBIL = new Set(['s', 'z', 'ɕ', 'ʑ']);
const MARKS = new Set(['͡', 'ʰ', 'ʼ', 'ː']);
const printable = p => !!p && p.codePointAt(0) >= 32;
const r3 = v => Math.round(v * 1000) / 1000;

function phoneGroups(tsv) {
  const groups = [];
  for (const line of tsv.split(/\r?\n/)) {
    const f = line.split('\t');
    if (f[0] !== 'P') continue;
    const t = +f[1] / 1000, d = +f[2] / 1000, ph = f.length > 3 ? f[3] : '';
    if (groups.length && Math.abs(groups[groups.length - 1].t - t) < 1e-6) groups[groups.length - 1].ph.push(ph);
    else groups.push({ t, d, ph: [ph] });
  }
  // 이벤트 길이값은 음소 사이에 빈틈이 생김 → 끝 = 다음 음소 시작(말 도중 입이 잠깐 닫히는 것 방지)
  for (let i = 0; i + 1 < groups.length; i++) {
    const a = groups[i], b = groups[i + 1];
    if (a.ph.some(printable)) a.d = Math.max(a.d, b.t - a.t);
  }
  return groups;
}

function nextVowel(groups, i) {
  for (const g of groups.slice(i + 1, i + 4)) {
    for (const p of g.ph) if (VOWEL[p]) return VOWEL[p];
    if (!g.ph.some(printable)) break;
  }
  return ['다문', 0.0];
}

function segments(groups) {
  const seg = [];
  groups.forEach((g, i) => {
    const t0 = g.t, t1 = g.t + g.d;
    const phs = g.ph.filter(p => printable(p) && !MARKS.has(p));
    const label = g.ph.filter(printable).join('');
    if (!phs.length) { seg.push([t0, t1, '다문', 0.0, '·']); return; }
    const vow = phs.filter(p => VOWEL[p]), gl = phs.filter(p => GLIDE[p]);
    if (vow.length && gl.length) {
      const tm = t0 + (t1 - t0) * 0.35;
      seg.push([t0, tm, ...GLIDE[gl[0]], label]); seg.push([tm, t1, ...VOWEL[vow[0]], label]); return;
    }
    if (vow.length) { seg.push([t0, t1, ...VOWEL[vow[0]], label]); return; }
    if (gl.length) { seg.push([t0, t1, ...GLIDE[gl[0]], label]); return; }
    const c = phs[0];
    if (LIPS.has(c)) seg.push([t0, t1, 'ㅁ', 0.0, label]);
    else if (TONGUE.has(c)) seg.push([t0, t1, 'ㄹ', 0.55, label]);
    else if (SIBIL.has(c) || (c === 't' && phs.includes('ɕ'))) seg.push([t0, t1, '이', 0.32, label]);
    else { const [sh, op] = nextVowel(groups, i); seg.push([t0, t1, sh, sh !== '다문' ? op * 0.4 : 0.15, label]); }
  });
  const out = [];
  for (const s of seg) {
    const dur = s[1] - s[0];
    if (s[2] === 'ㅁ' && dur < 0.06) s[1] = s[0] + 0.06;
    if (out.length && dur < MIN_HOLD && s[2] !== 'ㅁ' && s[3] < 0.6) { out[out.length - 1][1] = s[1]; continue; }
    if (out.length && out[out.length - 1][1] > s[0]) s[0] = out[out.length - 1][1];
    if (s[1] > s[0]) out.push(s);
  }
  return out;
}

function readWav(buf) {
  if (buf.toString('ascii', 0, 4) !== 'RIFF' || buf.toString('ascii', 8, 12) !== 'WAVE') throw new Error('wav 아님');
  let off = 12, sr = 16000, bits = 16, ch = 1, data = null;
  while (off + 8 <= buf.length) {
    const id = buf.toString('ascii', off, off + 4), size = buf.readUInt32LE(off + 4);
    if (id === 'fmt ') { ch = buf.readUInt16LE(off + 10); sr = buf.readUInt32LE(off + 12); bits = buf.readUInt16LE(off + 22); }
    if (id === 'data') { data = buf.subarray(off + 8, Math.min(buf.length, off + 8 + size)); break; }
    off += 8 + size + (size & 1);
  }
  if (!data || bits !== 16) throw new Error('지원 안 하는 wav');
  const n = Math.floor(data.length / 2 / ch), x = new Float32Array(n);
  for (let i = 0; i < n; i++) x[i] = data.readInt16LE(i * 2 * ch) / 32768;
  return { sr, x };
}

function percentile(arr, q) {   // numpy 기본(선형 보간)과 같음
  const a = Float64Array.from(arr).sort();
  if (!a.length) return 0;
  const pos = (a.length - 1) * q / 100, lo = Math.floor(pos), hi = Math.ceil(pos);
  return a[lo] + (a[hi] - a[lo]) * (pos - lo);
}

function rmsEnv(x, sr) {
  const hop = Math.floor(sr / FPS), win = Math.floor(sr * 0.02);
  const n = Math.floor(x.length / hop), e = new Float32Array(n);
  let mx = 0;
  for (let i = 0; i < n; i++) {
    const c = i * hop + Math.floor(hop / 2);
    const a = Math.max(0, c - Math.floor(win / 2)), b = Math.min(x.length, c + Math.floor(win / 2));
    let s = 0; for (let k = a; k < b; k++) s += x[k] * x[k];
    e[i] = Math.sqrt(s / Math.max(1, b - a) + 1e-12); mx = Math.max(mx, e[i]);
  }
  const big = Array.from(e).filter(v => v > mx * 0.05);
  const ref = big.length ? percentile(big, 95) : mx || 1;
  for (let i = 0; i < n; i++) e[i] = Math.min(1.3, Math.max(0, e[i] / ref));
  return e;
}

function framesFromSegments(seg, env, dur) {
  const fr = [], n = Math.ceil(dur * FPS);
  let j = 0;
  for (let i = 0; i <= n; i++) {
    const t = i / FPS, tq = t + LEAD;
    while (j < seg.length - 1 && seg[j][1] <= tq) j++;
    const s = seg.length && seg[j][0] <= tq && tq < seg[j][1] ? seg[j] : null;
    let shape, op;
    if (!s || s[2] === '다문') { shape = '다문'; op = 0; }
    else {
      const ei = Math.min(env.length - 1, Math.floor(tq * FPS));
      const k = 0.5 + 0.65 * Math.pow(env[Math.max(0, ei)] || 0, 0.6);
      shape = s[2]; op = s[2] === 'ㅁ' ? 0 : Math.min(1.15, s[3] * k);
    }
    if (fr.length && fr[fr.length - 1][1] === shape && Math.abs(fr[fr.length - 1][2] - op) < 0.04) continue;
    fr.push([r3(t), shape, r3(op)]);
  }
  return fr;
}

/** wav 버퍼 + 시각 tsv → {dur, frames:[[t, 입모양, 벌림]...]} */
function lipsync(wavBuf, tsv) {
  const { sr, x } = readWav(wavBuf);
  const dur = x.length / sr;
  const frames = framesFromSegments(segments(phoneGroups(tsv)), rmsEnv(x, sr), dur);
  return { dur: r3(dur), fps: FPS, lead: LEAD, frames };
}

class Tts {
  constructor(dir, ps1, log) {
    this.dir = dir; this.ps1 = ps1; this.log = log || (() => {});
    this.proc = null; this.ready = null; this.wait = new Map(); this.seq = 0; this.idleTimer = null; this.voice = '';
  }
  start() {
    if (this.ready) return this.ready;
    fs.mkdirSync(this.dir, { recursive: true });
    const p = spawn('powershell.exe', ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', this.ps1, '-Dir', this.dir],
      { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
    this.proc = p;
    let buf = '';
    this.ready = new Promise((resolve, reject) => {
      const fail = e => { reject(e); };
      p.on('error', fail);
      p.stdout.setEncoding('utf8');
      p.stdout.on('data', d => {
        buf += d;
        let k;
        while ((k = buf.indexOf('\n')) >= 0) {
          const line = buf.slice(0, k).replace(/\r$/, ''); buf = buf.slice(k + 1);
          const f = line.split('\t');
          if (f[0] === 'READY') { this.voice = f[1] || ''; this.log('음성 준비: ' + (this.voice || '(한국어 음성 없음 — 기본 음성)')); resolve(); }
          else if ((f[0] === 'OK' || f[0] === 'ERR') && this.wait.has(f[1])) {
            const w = this.wait.get(f[1]); this.wait.delete(f[1]);
            if (f[0] === 'OK') w.resolve(); else w.reject(new Error(f[2] || '음성 실패'));
          }
        }
      });
      p.stderr.setEncoding('utf8');
      p.stderr.on('data', d => this.log('음성 stderr: ' + String(d).trim().slice(0, 300)));
      p.on('exit', code => {
        this.log('음성 도우미 끝남 ' + code);
        if (this.proc === p) { this.proc = null; this.ready = null; }
        for (const w of this.wait.values()) w.reject(new Error('음성 도우미가 끝남'));
        this.wait.clear();
        fail(new Error('음성 도우미 시작 실패'));
      });
    });
    return this.ready;
  }
  stop() {
    if (this.proc) { try { this.proc.stdin.write('QUIT\n'); this.proc.stdin.end(); } catch (e) { /* 이미 끝남 */ } }
    const p = this.proc; this.proc = null; this.ready = null;
    if (p) setTimeout(() => { if (p.exitCode === null) { try { p.kill(); } catch (e) { /* 무시 */ } } }, 3000);
  }
  /** 문장 → {wav(Buffer), data:{dur, frames}} */
  async synth(text, rate) {
    clearTimeout(this.idleTimer);
    await this.start();
    const id = String(++this.seq);
    const base = path.join(this.dir, id);
    fs.writeFileSync(base + '.txt', text, 'utf8');
    const done = new Promise((resolve, reject) => this.wait.set(id, { resolve, reject }));
    this.proc.stdin.write(id + '\t' + (rate | 0) + '\n');
    try {
      await done;
      const wav = fs.readFileSync(base + '.wav');
      const tsv = fs.readFileSync(base + '.tsv', 'utf8');
      return { wav, data: lipsync(wav, tsv), voice: this.voice };
    } finally {
      for (const ext of ['.txt', '.wav', '.tsv']) { try { fs.unlinkSync(base + ext); } catch (e) { /* 없음 */ } }
      this.idleTimer = setTimeout(() => this.stop(), 120000);
    }
  }
}



// ---------------------------------------------------------------- 김비서 목소리 서버(본체가 켠 voice/tts_server.py, 기본 http://127.0.0.1:8871)
// 펫은 서버를 직접 켜지 않음(본체가 켜고 끔). 서버가 없거나 준비 전이면 윈도우 음성(Tts)으로 말함.
const http = require('http');
const EXPR2EMO = { '기쁨': '기쁨', '놀람': '놀람', '졸림': '졸림', '걱정': '걱정' };   // 그 밖의 표정 = 기본 목소리

class VoiceServer {
  /** voicesFile = 목소리 목록·옷→목소리 대응표(voice/voices.json) 경로 — 없으면 voiceFor 는 늘 null */
  constructor(url, log, voicesFile) {
    this.vfile = voicesFile || null; this._vmap = null; this._badVoice = {};
    let u = null;
    try { u = new URL(String(url || 'http://127.0.0.1:8871')); } catch (e) { u = null; }
    // 이 PC 안 주소만(목소리 서버도 127.0.0.1 만 받음)
    this.url = u && u.protocol === 'http:' && ['127.0.0.1', 'localhost'].includes(u.hostname) ? u : new URL('http://127.0.0.1:8871');
    this.log = log || (() => {});
    this.down = false; this.voiceName = null; this.emotions = null; this.checked = 0;
  }
  _req(method, p, body, timeout) {
    return new Promise((resolve, reject) => {
      const req = http.request({ host: this.url.hostname, port: +this.url.port || 80, path: p, method, timeout: timeout || 60000,
        headers: body ? { 'Content-Type': 'application/json', 'Content-Length': body.length } : {} }, res => {
        const bufs = []; res.on('data', d => bufs.push(d));
        res.on('end', () => {
          try { resolve({ code: res.statusCode, json: JSON.parse(Buffer.concat(bufs).toString('utf8')) }); } catch (e) { reject(e); }
        });
      });
      req.on('timeout', () => req.destroy(new Error('목소리 서버 시간 넘김')));
      req.on('error', reject);
      req.end(body);
    });
  }
  async status() { try { return (await this._req('GET', '/status', null, 3000)).json; } catch (e) { return null; } }
  /** 지금 입은 옷(꾸러미) → 목소리 이름 또는 null(= 서버 기본 목소리).
      대응표는 한 곳 = voice/voices.json 의 "옷목소리" {"성별": {"남성": "kimbiseo_m", …}, "옷": {"<옷 id>": "<목소리>"}} (본체 core/voice_choice.py 와 같은 파일·같은 순서).
      고르는 순서 = 꾸러미 pack.json "voice"(선택) → "옷"[id] → "성별"[gender]. 그 이름이 "목록" 에 없거나 참고음성(참고목록.json)이 없으면 건너뜀.
      대응표 파일이 없거나 못 읽으면 늘 null = 예전과 똑같은 요청. */
  voiceFor(pack) {
    if (!pack || !this.vfile) return null;
    try {
      const st = fs.statSync(this.vfile), key = st.size + ':' + st.mtimeMs;
      if (!this._vmap || this._vmap.key !== key) {
        const j = JSON.parse(fs.readFileSync(this.vfile, 'utf8').replace(/^﻿/, ''));
        const om = (j && typeof j['옷목소리'] === 'object' && j['옷목소리']) || {};
        this._vmap = { key, gender: om['성별'] || {}, skin: om['옷'] || {}, list: (j && j['목록']) || {}, root: path.dirname(path.dirname(this.vfile)) };
      }
      const m = this._vmap, now = Date.now(), g = String(pack.gender || '');
      const byGender = m.gender[g] || m.gender[g + '성'] || m.gender[g.replace(/성$/, '')];
      for (const name of [pack.voice, m.skin[pack.id], byGender]) {
        if (typeof name !== 'string' || !name || !m.list[name] || this._badVoice[name] > now) continue;
        const folder = String(m.list[name]['폴더'] || '');
        if (folder && fs.existsSync(path.join(path.isAbsolute(folder) ? folder : path.join(m.root, folder), '참고목록.json'))) return name;
      }
    } catch (e) { /* 대응표를 못 읽으면 기본 목소리 */ }
    return null;
  }
  /** 문장 → {wav, data, yawn, voice}. 서버가 없거나 준비 전이면 실패(→ 윈도우 음성). voiceName = voiceFor() 결과 — 없으면 요청에 안 넣음 */
  async synth(text, rate, expr, voiceName) {
    if (!this.emotions || Date.now() - this.checked > 60000) {
      const st = await this.status();
      this.checked = Date.now();
      if (!st || !st.ok) { this.down = true; throw new Error(st ? '목소리 서버 준비 중' : '목소리 서버 없음'); }
      this.down = false;
      if (Array.isArray(st.emotions)) this.emotions = st.emotions;
      if (st.voice) this.voiceName = String(st.voice).slice(0, 40);
    }
    let emo = EXPR2EMO[expr] || '기본';
    if (this.emotions && !this.emotions.includes(emo)) emo = '기본';
    const mk = v => Buffer.from(JSON.stringify(v ? { text, emotion: emo, voice: v } : { text, emotion: emo }), 'utf8');
    let r;
    try {
      r = await this._req('POST', '/tts_lip', mk(voiceName));
      if (voiceName && (r.code === 400 || r.code === 500) && !/읽을 글/.test(String(r.json.error || ''))) {
        // 서버가 그 목소리를 모르거나 못 올림 → 그 이름은 5분 쉬고 이 문장은 기본 목소리로 다시(말이 빠지지 않게)
        this._badVoice[voiceName] = Date.now() + 300000;
        this.log('목소리 서버가 voice ' + voiceName + ' 거절(' + r.code + ' ' + String(r.json.error || '').slice(0, 80) + ') → 기본 목소리로 다시');
        r = await this._req('POST', '/tts_lip', mk(null));
      }
    }
    catch (e) { this.down = true; this.emotions = null; throw e; }
    if (r.code !== 200) throw Object.assign(new Error(r.json.error || ('목소리 서버 ' + r.code)), { code: r.code });
    if (r.json.voice) this.voiceName = String(r.json.voice).slice(0, 40);
    return { wav: Buffer.from(r.json.wav_base64, 'base64'), data: r.json.lip, yawn: !!r.json.yawn, voice: this.voiceName || '김비서 목소리' };
  }
  stop() { /* 펫이 켠 서버가 없음 */ }
}

module.exports = { Tts, VoiceServer, lipsync, phoneGroups, segments };
