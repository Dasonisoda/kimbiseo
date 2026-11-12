/* 옷 관리 창: 내 옷(미리보기·입기·지우기 — "정말 지울까요?") · 옷 더 받기(옷 저장소 목록 outfits.json → 고른 옷만 받기·설명·미리보기, 준비 중인 옷은 보여만 줌) · 파일로 옷 추가 · 서명 없는 꾸러미 경고 */
(function () {
  'use strict';
  const api = window.petApi;
  const $ = id => document.getElementById(id);
  let tab = new URLSearchParams(location.search).get('tab') === 'get' ? 'get' : 'mine';
  let st = null, remote = null, remoteErr = null, confirmId = null, busy = {}, msgTimer = null, askToken = null;

  function el(tag, cls, kids) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    for (const k of kids || []) if (k != null) e.appendChild(typeof k === 'string' ? document.createTextNode(k) : k);
    return e;
  }
  function pic(src) {
    if (!src) return el('div', 'noimg');
    const i = document.createElement('img'); i.src = src; i.alt = ''; i.draggable = false; return i;
  }
  function btn(label, cls, fn, dis) { const b = el('button', 'btn small ' + (cls || ''), [label]); b.onclick = fn; if (dis) b.disabled = true; return b; }
  function msg(t) { $('msg').textContent = t || ''; clearTimeout(msgTimer); if (t) msgTimer = setTimeout(() => { $('msg').textContent = ''; }, 6000); }
  const mb = n => (n / 1e6 >= 10 ? Math.round(n / 1e6) : (n / 1e6).toFixed(1)) + 'MB';

  function renderMine() {
    const L = $('list'); L.textContent = '';
    const list = (st && st.packs) || [];
    if (!list.length) { L.appendChild(el('div', 'empty', ['넣은 옷이 없어요.', el('br'), '「옷 더 받기」나 「파일로 옷 추가」로 넣어 주세요.'])); return; }
    const last = list.length <= 1;
    for (const p of list) {
      const worn = st.worn === p.id;
      const meta = el('div', 'meta', [
        [p.body, p.gender].filter(Boolean).join(' · ') || null, p.body || p.gender ? el('br') : null,
        '버전 ' + (p.version || '-') + ' · 동작 ' + p.clips + '개 · ' + (p.music ? '춤 노래 ' + p.music + '곡' : '춤 노래 없음'), el('br'),
        p.signed ? el('span', 'ok', ['정품']) : el('span', 'warn', ['서명 없음']),
        worn ? ' · 입는 중' : '',
      ]);
      const acts = el('div', 'acts', [
        btn(worn ? '입는 중' : '입기', worn ? 'on' : '', () => api.invoke('ward-wear', { id: p.id }), worn),
        btn('삭제', 'del', () => { confirmId = p.id; render(); }, last || busy[p.id]),
      ]);
      const row = el('div', 'row' + (worn ? ' on' : ''), [pic(p.img), el('div', '', [el('div', 'name', [p.name]), meta]), acts]);
      row.dataset.id = p.id;
      if (confirmId === p.id) {
        row.appendChild(el('div', 'confirm', ['정말 지울까요? 「' + p.name + '」', el('div', '', [
          btn('그만두기', '', () => { confirmId = null; render(); }),
          btn('지우기', 'del go', async () => {
            confirmId = null; busy[p.id] = true; render(); msg('지우는 중…');
            const r = await api.invoke('ward-delete', { id: p.id });
            busy[p.id] = false;
            msg(r && r.ok ? '「' + p.name + '」 옷을 지웠어요' + (r.switched ? ' (다른 옷으로 갈아입음)' : '') : '못 지웠어요: ' + ((r && r.error) || ''));
            render();
          }),
        ])]));
      }
      L.appendChild(row);
    }
    if (last) L.appendChild(el('div', 'note', ['마지막 한 벌은 지울 수 없어요. 다른 옷을 넣은 뒤 지울 수 있어요.']));
  }

  function renderGet() {
    const L = $('list'); L.textContent = '';
    if (remoteErr) {
      L.appendChild(el('div', 'empty', [remoteErr.code === 'nosource' ? '' : '옷 목록에 연결이 안 돼요.', remoteErr.code === 'nosource' ? null : el('br'), remoteErr.text, el('br'), el('br')]));
      if (remoteErr.code !== 'nosource') L.lastChild.appendChild(btn('다시 보기', '', loadRemote));
      return;
    }
    if (!remote) { L.appendChild(el('div', 'empty', ['옷 목록을 받는 중…'])); return; }
    if (!remote.length) { L.appendChild(el('div', 'empty', ['받을 수 있는 옷이 없어요.'])); return; }
    L.appendChild(el('div', 'note', ['입고 싶은 옷만 골라 받아요(옷 하나가 크니까요). 새 옷이 나오면 이 목록에 생겨요.']));
    for (const p of remote) {
      const b = busy['get:' + p.key];
      const label = p.soon ? '준비 중' : b ? '받는 중' : p.installed ? (p.sameVersion ? '넣음' : '이 판 받기') : '받기';
      const meta = el('div', 'meta', [
        [p.body, p.gender].filter(Boolean).join(' · ') || null, p.body || p.gender ? el('br') : null,
        p.soon ? el('span', 'soon', ['준비 중이에요']) : '버전 ' + (p.version || '-') + ' · ' + mb(p.size) + ' · ' + (p.songs ? '춤 노래 포함' : '춤 노래 없음'),
        p.soon ? null : el('br'),
        p.soon ? null : (p.signed ? el('span', 'ok', ['정품']) : el('span', 'warn', ['서명 없음'])),
        p.def && !p.soon ? ' · 기본 옷' : '',
        p.note ? el('br') : null, p.note || null,
      ]);
      const bar = el('div', 'bar', [el('i')]); bar.style.display = b ? 'block' : 'none'; bar.dataset.key = p.key;
      const acts = el('div', 'acts', [btn(label, p.soon || (p.installed && p.sameVersion) ? '' : 'go', async () => {
        busy['get:' + p.key] = true; render(); msg('「' + p.name + '」 받는 중…');
        const r = await api.invoke('ward-get', { key: p.key });
        busy['get:' + p.key] = false;
        if (r && r.ok) msg('「' + p.name + '」 옷을 넣었어요');
        else if (r && r.asked) msg('');
        else msg('못 받았어요: ' + ((r && r.error) || ''));
        await loadRemote();
      }, p.soon || b || (p.installed && p.sameVersion))]);
      const row = el('div', 'row' + (p.soon ? ' soon' : ''), [pic(p.img), el('div', '', [el('div', 'name', [p.name]), meta, bar]), acts]);
      row.dataset.id = p.id; row.dataset.key = p.key;
      L.appendChild(row);
    }
  }

  function render() {
    $('tabMine').className = 'btn' + (tab === 'mine' ? ' on' : '');
    $('tabGet').className = 'btn' + (tab === 'get' ? ' on' : '');
    if (tab === 'mine') renderMine(); else renderGet();
  }
  async function loadRemote() {
    remoteErr = null;
    if (!remote) render();
    const r = await api.invoke('ward-remote');
    if (r && r.ok) remote = r.packs; else { remote = null; remoteErr = { text: (r && r.error) || '알 수 없음', code: (r && r.code) || '' }; }
    render();
  }
  async function loadState() { st = await api.invoke('ward-state'); render(); }

  $('tabMine').onclick = () => { tab = 'mine'; confirmId = null; render(); };
  $('tabGet').onclick = () => { tab = 'get'; confirmId = null; render(); loadRemote(); };
  $('x').onclick = () => api.send('ward-close');
  $('file').onclick = async () => { const r = await api.invoke('ward-file'); if (r && r.length) loadState(); };
  $('askNo').onclick = async () => { $('ask').className = ''; const t = askToken; askToken = null; await api.invoke('ward-answer', { token: t, yes: false }); };
  $('askYes').onclick = async () => { $('ask').className = ''; const t = askToken; askToken = null; msg('넣는 중…'); await api.invoke('ward-answer', { token: t, yes: true }); loadState(); };
  window.addEventListener('keydown', e => { if (e.key === 'Escape') { if (askToken) $('askNo').onclick(); else api.send('ward-close'); } });
  window.addEventListener('contextmenu', e => e.preventDefault());
  api.on('packs-changed', s => { st = s; if (tab === 'get' && remote) loadRemote(); else render(); });
  api.on('ward-tab', t => { tab = t === 'get' ? 'get' : 'mine'; render(); if (tab === 'get') loadRemote(); });
  api.on('ward-msg', t => msg(t));
  api.on('ward-progress', d => { const b = [...document.querySelectorAll('.bar')].find(x => x.dataset.key === d.key); if (b) { b.style.display = 'block'; b.firstChild.style.width = (d.pct || 0) + '%'; } });
  api.on('ward-ask', d => {
    askToken = d.token;
    $('askText').textContent = '「' + d.name + '」(' + d.file + ')은 김비서 공식 꾸러미가 아니거나 서명이 빠졌어요. 직접 만들었거나 믿을 수 있는 파일일 때만 넣으세요.';
    $('ask').className = 'show';
  });
  loadState();
  if (tab === 'get') loadRemote();
})();
