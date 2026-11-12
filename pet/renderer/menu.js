/* 오른쪽 클릭 메뉴: 옷(바로 갈아입음, 메뉴는 열린 채) · 옷 관리·옷 받기·파일로 추가 · 크기 · 춤 노래 크기 · 항상 위 · 말하기 시험 · 끝내기 */
(function () {
  'use strict';
  const api = window.petApi;
  const $ = id => document.getElementById(id);
  const pick = (type, value) => api.send('menu-pick', { type, value });
  let S = null, toastTimer = null;

  function el(tag, cls, kids) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    for (const k of kids || []) e.appendChild(typeof k === 'string' ? document.createTextNode(k) : k);
    return e;
  }
  function img(src) { const i = document.createElement('img'); i.src = src; i.alt = ''; i.draggable = false; return i; }
  function toast(t) { $('toast').textContent = t; clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('toast').textContent = ''; }, 2600); }

  function render() {
    if (!S) return;
    const o = $('outfits'); o.textContent = ''; o.className = 'outfits' + (S.outfits.length === 1 ? ' one' : '');
    if (!S.outfits.length) o.appendChild(el('div', 'empty', ['넣은 옷이 없어요 — 아래 「옷 받기」를 눌러 주세요']));
    for (const f of S.outfits) {
      const b = el('button', 'outfit' + (S.skin === f.id ? ' on' : ''), [img(/^(file|data):/.test(f.img || '') ? f.img : 'img/icon.png'), el('span', '', [f.name + (f.songs || S.danceMusic === false ? '' : ' · 노래 없음')])]);
      b.dataset.skin = f.id;
      b.onclick = () => { pick('skin', f.id); toast(f.name + ' 입었어요'); };
      o.appendChild(b);
    }
    const s = $('sizes'); s.textContent = '';
    for (const z of S.sizes) {
      const b = el('button', 'btn' + (S.size === z ? ' on' : ''), [z]);
      b.dataset.size = z;
      b.onclick = () => pick('size', z);
      s.appendChild(b);
    }
    const mu = $('music'); mu.textContent = '';   // 춤 노래 크기(기본 보통 = 목소리보다 작게) — 춤 노래를 끈 판이면 칸째 숨김
    mu.style.display = $('music-h').style.display = (S.musicLevels || []).length ? '' : 'none';
    for (const z of S.musicLevels || []) {
      const b = el('button', 'btn' + (S.musicVolume === z ? ' on' : ''), [z]);
      b.dataset.music = z;
      b.onclick = () => { pick('music', z); toast('춤 노래 크기: ' + z); };
      mu.appendChild(b);
    }
    const t = $('ontop');
    t.textContent = S.onTop ? '켜짐' : '꺼짐';
    t.className = 'btn' + (S.onTop ? ' on' : '');
    $('ver').textContent = 'v' + S.version + (S.port ? ' · 펫 신호 입구 127.0.0.1:' + S.port : '');
    requestAnimationFrame(() => api.send('menu-height', Math.ceil(document.getElementById('card').getBoundingClientRect().height + 12)));
  }
  $('x').onclick = () => pick('close');
  $('ontop').onclick = () => pick('ontop', !S.onTop);
  $('speak').onclick = () => pick('speak-test');
  $('home').onclick = () => { pick('home'); toast('화면 오른쪽 아래로 옮겼어요'); };
  $('ward').onclick = () => pick('wardrobe', 'mine');
  $('wardget').onclick = () => pick('wardrobe', 'get');
  $('packfile').onclick = () => pick('pack-file');
  $('quit').onclick = () => pick('quit');
  window.addEventListener('keydown', e => { if (e.key === 'Escape') pick('close'); });
  window.addEventListener('contextmenu', e => e.preventDefault());
  api.on('state', s => { S = s; render(); });
  api.invoke('menu-state').then(s => { S = s; render(); });
})();
