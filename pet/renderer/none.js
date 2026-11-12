/* 옷이 하나도 없을 때 펫 자리: 안내 카드(누르면 옷 받기 창) · 말풍선(옷 받는 중 % 등) */
(function () {
  'use strict';
  const api = window.petApi || { send() {}, on() {} };
  const card = document.getElementById('card'), bubble = document.getElementById('bubble');
  let over = false, bubbleTimer = null;
  api.on('cursor', c => {   // 카드 위에서만 클릭을 받음(나머지는 아래 창으로 통과)
    const r = card.getBoundingClientRect();
    const o = !!c.inside && c.x >= r.left && c.x < r.right && c.y >= r.top && c.y < r.bottom;
    if (o === over) return;
    over = o; card.classList.toggle('over', o); api.send('hit', o);
  });
  card.addEventListener('click', () => api.send('none-click'));
  window.addEventListener('contextmenu', e => { e.preventDefault(); api.send('context-menu'); });
  api.on('bubble', m => {
    clearTimeout(bubbleTimer);
    if (!m || !m.text) { bubble.classList.remove('show'); return; }
    bubble.textContent = m.text; bubble.classList.add('show');
    bubbleTimer = setTimeout(() => bubble.classList.remove('show'), Math.max(500, (m.sec || 4) * 1000));
  });
  window.petFadeOut = () => new Promise(res => { document.body.style.transition = 'opacity 0.2s'; document.body.style.opacity = '0'; setTimeout(res, 220); });
  api.send('pet-log', '옷 없음 안내 화면');
})();
