// 김비서 펫 동작 이름·대체 규칙. 본체(main.js, require)와 화면(real.js, <script>)이 같이 씀 → HTTP /motion 응답의 missing·fallback 과 실제 펫 행동이 늘 같음.
(function (root) {
  const ALIAS = { 하트챌린지춤: 'dance1', '하트 챌린지 춤': 'dance1', '하트 챌린지': 'dance1', '하트 춤': 'dance1', 하트춤: 'dance1', '챌린지 춤': 'dance1', 챌린지춤: 'dance1', '릴스 춤': 'dance1', '1번 춤': 'dance1', '첫 번째 춤': 'dance1',
    '신나는 응원 춤': 'dance2', '응원 춤': 'dance2', 응원춤: 'dance2', '신나는 춤': 'dance2', '케이팝 춤': 'dance2', '2번 춤': 'dance2', '두 번째 춤': 'dance2',
    '귀여운 애교 춤': 'dance3', '애교 춤': 'dance3', 애교춤: 'dance3', '귀여운 춤': 'dance3', '3번 춤': 'dance3', '세 번째 춤': 'dance3',
    '제로투 춤': 'dance_zerotwo', 'BAD 춤': 'dance_bad', 'bad 춤': 'dance_bad', BAD: 'dance_bad', bad: 'dance_bad', 배드: 'dance_bad', '배드 춤': 'dance_bad', 제로투: 'dance_zerotwo', 제로투춤: 'dance_zerotwo', '에스텔라 춤': 'dance_estella', 에스텔라: 'dance_estella', 에스텔라춤: 'dance_estella', 대기: 'idle', 서기: 'stand', 일어나기: 'stand', 일어나: 'stand', 말하기: 'talk', 인사: 'wave', 안녕: 'wave', 손흔들기: 'wave', '손 흔들기': 'wave',
    절: 'bow', 왼쪽걷기: 'walk_left', 오른쪽걷기: 'walk_right', 걷기: 'walk_left', 뒤돌기: 'turn_back', 대각선: 'diag', 앉기: 'sit', 앉아: 'sit', 눕기: 'lie',
    검색: 'search_start', 검색시작: 'search_start', 검색끝: 'search_end', 고개들기: 'search_look', 춤: 'dance',
    손하트: 'heart_hand', 볼하트: 'heart_cheek', 큰하트: 'heart_big', 하트: 'heart_hand', 브이: 'v_cheek', 양손브이: 'v_double', 윙크브이: 'v_wink',
    갸웃: 'tilt', 턱괴기: 'chin_think', 기지개: 'stretch', 웃음터짐: 'laugh_burst', 깜짝: 'surprise_jump', 뾰로통: 'pout', 박수: 'clap', 엄지척: 'thumbs',
    머리넘기기: 'hair_flip' };
  const DANCES = [
    { name: 'dance1', ko: '하트 챌린지 춤' },   // 손하트·브이·꽃받침·박수·카메라 가리키기, 숏폼 챌린지 느낌
    { name: 'dance2', ko: '신나는 응원 춤' },   // 작게 폴짝·팔 위아래 응원·주먹 번갈아·머리 위 큰 하트로 끝
    { name: 'dance3', ko: '귀여운 애교 춤' },   // 무릎 살랑·볼 옆 손가락 동그라미·턱 밑 주먹 애교·콘서트처럼 손 흔들기
    { name: 'dance_zerotwo', ko: '제로투 춤' },
    { name: 'dance_bad', ko: 'BAD 춤' },
    { name: 'dance_estella', ko: '에스텔라 춤' },
  ];
  const GESTURES = ['heart_hand', 'heart_cheek', 'heart_big', 'v_cheek', 'v_double', 'v_wink', 'tilt', 'chin_think', 'stretch',
    'laugh_burst', 'surprise_jump', 'pout', 'clap', 'thumbs', 'hair_flip',
    'sad_slump', 'comfort_pat', 'excited_hop', 'nod', 'head_shake', 'shrug', 'fighting'];
  Object.assign(ALIAS, { 시무룩: 'sad_slump', 축처짐: 'sad_slump', '축 처짐': 'sad_slump', 토닥토닥: 'comfort_pat', 토닥: 'comfort_pat', 위로: 'comfort_pat',
    폴짝: 'excited_hop', 신나서폴짝: 'excited_hop', '신나서 폴짝': 'excited_hop', 끄덕: 'nod', 끄덕끄덕: 'nod', 고개끄덕: 'nod', '고개 끄덕': 'nod',
    도리도리: 'head_shake', 고개젓기: 'head_shake', '고개 젓기': 'head_shake', 으쓱: 'shrug', 어깨으쓱: 'shrug', '어깨 으쓱': 'shrug',
    화이팅: 'fighting', 파이팅: 'fighting' });
  const EMOTIONS = [
    { name: 'smile', ko: '미소' }, { name: 'happy', ko: '기쁨' }, { name: 'cry', ko: '울먹' }, { name: 'sad', ko: '슬픔' },
    { name: 'shy', ko: '부끄러움' }, { name: 'surprised', ko: '놀람' }, { name: 'worried', ko: '걱정' }, { name: 'warm', ko: '다정' },
    { name: 'sorry', ko: '미안' }, { name: 'confident', ko: '당당' }, { name: 'think', ko: '생각' }, { name: 'playful', ko: '장난' },
    { name: 'pout', ko: '삐짐' }, { name: 'sleepy', ko: '졸림' }, { name: 'touched', ko: '감동' }, { name: 'flustered', ko: '머쓱' },
  ];
  const EMO_ALIAS = { 미소: 'smile', 웃는얼굴: 'smile', 기쁨: 'happy', 기뻐: 'happy', 기쁘게: 'happy', 신남: 'happy', 웃음: 'happy', joy: 'happy',
    울먹: 'cry', 울먹임: 'cry', 울음: 'cry', 눈물: 'cry', crying: 'cry', 슬픔: 'sad', 슬퍼: 'sad', 슬프게: 'sad', 아쉬움: 'sad',
    부끄러움: 'shy', 부끄럼: 'shy', 수줍음: 'shy', 놀람: 'surprised', 놀라서: 'surprised', surprise: 'surprised', 걱정: 'worried', worry: 'worried',
    다정: 'warm', 다정하게: 'warm', 따뜻하게: 'warm', 미안: 'sorry', 미안함: 'sorry', 사과: 'sorry', apologetic: 'sorry', 당당: 'confident', 당당하게: 'confident', 자신감: 'confident',
    생각: 'think', 고민: 'think', thinking: 'think', 장난: 'playful', 장난스럽게: 'playful', 윙크: 'playful', 삐짐: 'pout', 삐침: 'pout', 뾰로통: 'pout',
    졸림: 'sleepy', 졸려: 'sleepy', 감동: 'touched', moved: 'touched', 머쓱: 'flustered', 당황: 'flustered', 민망: 'flustered', embarrassed: 'flustered' };
  const EMO_NEUTRAL = new Set(['보통', '기본', '평소', 'neutral', 'normal', 'none', 'calm', 'listening', '말하기']);
  function emotionOf(n) {
    if (typeof n !== 'string') return null;
    const s = n.trim(), lo = s.toLowerCase(), bare = lo.replace(/^((sit|lie)_)?talk_/, '');
    if (EMOTIONS.some(e => e.name === bare)) return bare;
    if (EMO_NEUTRAL.has(s) || EMO_NEUTRAL.has(lo)) return 'neutral';
    return EMO_ALIAS[s] || EMO_ALIAS[lo] || EMO_ALIAS[s.replace(/\s+/g, '')] || null;
  }
  // 그 동작에 필요한 클립: any = 하나만 있어도 됨, all = 다 있어야 함. 없는 이름(idle·stand·talk·걷기 등)은 늘 됨
  const NEED = {
    dance: { any: ['dance1', 'dance2', 'dance3'] }, dance1: { all: ['dance1'] }, dance2: { all: ['dance2'] }, dance3: { all: ['dance3'] }, dance_zerotwo: { all: ['dance_zerotwo'] }, dance_bad: { all: ['dance_bad'] }, dance_estella: { all: ['dance_estella'] },
    bow: { all: ['bow'] }, wave: { any: ['hello', 'wave'] }, turn_back: { all: ['back_in'] }, diag: { all: ['diag_in'] },
    sit: { all: ['sit_in', 'sit_loop'] }, lie: { all: ['lie_in', 'lie_loop'] },
    search_start: { all: ['search_in', 'search_loop'] }, search_look: { all: ['search_up'] },
  };
  for (const g of GESTURES) NEED[g] = { all: [g] };
  const DANCE_LIKE = ['clap', 'heart_big', 'laugh_burst', 'heart_hand', 'wave'];
  const GESTURE_LIKE = ['heart_hand', 'clap', 'thumbs', 'v_cheek', 'wave'];
  const FALLBACK = { dance_zerotwo: ['dance1', 'dance2', 'dance3', ...DANCE_LIKE], dance_bad: ['dance2', 'dance1', 'dance3', ...DANCE_LIKE], dance_estella: ['dance3', 'dance1', 'dance2', ...DANCE_LIKE], dance: DANCE_LIKE, dance1: DANCE_LIKE, dance2: DANCE_LIKE, dance3: DANCE_LIKE };
  for (const g of GESTURES) FALLBACK[g] = GESTURE_LIKE.filter(x => x !== g);
  // 감정 동작은 비슷한 것만(시무룩·끄덕·도리도리를 하트로 대신하면 더 이상함 → 대신할 것 없으면 가만히 + missing)
  Object.assign(FALLBACK, { sad_slump: [], nod: [], head_shake: [], comfort_pat: ['heart_hand', 'wave'], excited_hop: ['clap', 'laugh_burst', 'heart_big'],
    shrug: ['tilt'], fighting: ['thumbs', 'clap'] });
  const ok = (k, has) => {
    const n = NEED[k];
    if (!n) return true;
    return n.any ? n.any.some(has) : n.all.every(has);
  };
  // name(영문·한국어) → { name: 실제로 할 동작 | null, asked: 정식 이름, missing: 그 옷에 없었나, fallback: 대신한 동작 | null, unknown }
  function resolve(name, has, known) {
    const k = known(name) ? name : ALIAS[name];
    if (!k) return { name: null, asked: name, unknown: true, missing: false, fallback: null };
    if (ok(k, has)) return { name: k, asked: k, missing: false, fallback: null };
    const f = (FALLBACK[k] || []).find(x => ok(x, has)) || null;
    return { name: f, asked: k, missing: true, fallback: f };
  }
  //   clips.<클립 이름>.motion = { "kind": "once"|"dance", "ko": "표시 이름", "calls": ["부르는 말", …], "pose": "stand"|"sit"|"lie"(once), "loops": 1~8·"music": "춤노래 파일 이름 머리글"(dance), "phone": false(폰 화면 제외) }
  //   지키는 것: 클립 이름 = 소문자·숫자·밑줄 2~40자 · 춤은 dance_ 로 시작 · 앱에 원래 있는 동작 이름(thumbs·dance1 …)과 엔진이 쓰는 클립(idle·talk·…_in/_hold/_out 등)은 무시(기존 것이 우선)
  //            · 표시 이름 20자·부르는 말 2~20자 8개까지(한글·영문·숫자·빈칸만) · 동작 100개·춤 30개까지. 모양이 틀린 것은 그 항목만 버림.
  const EX_NAME = /^[a-z][a-z0-9_]{1,39}$/;
  const EX_TEXT = /^[0-9A-Za-z가-힣 ]+$/;
  const EX_CORE = ['idle', 'stand', 'talk', 'wave', 'hello', 'walk_left', 'walk_right', 'dance', 'think', 'joy', 'laugh', 'shy', 'sleepy', 'surprise', 'worry', 'wink'];
  const EX_ENGINE = /^(idle|talk|sit_talk|lie_talk|sit_loop|lie_loop|search_|w3[LR]?_|side[LR]?_|back_|diag_)|_(in|hold|out|loop|walk|wstart|wstop|turn)$/;
  const EX_MAX = { once: 100, dance: 30, calls: 8 };   // 동작 60 → 100(운영 펫 0.6.14 와 같게 — 자세별 감정이 66개인 꾸러미)
  const exText = (s, max) => { if (typeof s !== 'string') return null; const t = s.replace(/\s+/g, ' ').trim(); return t.length >= 1 && t.length <= max && EX_TEXT.test(t) ? t : null; };
  const isBuiltin = n => n in NEED || GESTURES.indexOf(n) >= 0 || EX_CORE.indexOf(n) >= 0 || DANCES.some(d => d.name === n) || Object.prototype.hasOwnProperty.call(ALIAS, n);
  // 자세별 동작: 서서 하는 동작 g 의 앉기·눕기·책상 판. 클립 이름이 <sit|lie|desk>_<g> 이거나, 클립 motion 칸에 of: g 와 pose: sit|lie|desk 가 있으면 그 판.
  //   g = 앱 몸짓(GESTURES)·인사(hello·wave)·절(bow), 또는 이 옷의 서서 하는 추가 동작. 엔진이 쓰는 이름(sit_in·sit_talk_*·sit_joy_* 등)은 g 가 아니라 해당 없음.
  //   돌려줌: { g: { sit: 클립 이름, lie: …, desk: … } } — 화면(real.js gestureAt)이 지금 자세 판이 있으면 그것, 없으면 일어나서 서서 함.
  const VAR_POSES = ['sit', 'lie', 'desk'];
  const VAR_RE = /^(sit|lie|desk)_([a-z][a-z0-9_]{1,39})$/;
  function variants(clips) {
    const out = {};
    if (!clips || typeof clips !== 'object') return out;
    const obj = m => (m && typeof m === 'object' && !Array.isArray(m) ? m : null);
    const bases = new Set(GESTURES.concat(['hello', 'wave', 'bow']));
    for (const n of Object.keys(clips)) {
      const m = obj(clips[n] && clips[n].motion);
      if (m && (m.kind === undefined || m.kind === 'once') && EX_NAME.test(n) && !VAR_RE.test(n) && !m.of && (m.pose === undefined || m.pose === 'stand')) bases.add(n);
    }
    for (const n of Object.keys(clips).sort()) {
      const m = obj(clips[n] && clips[n].motion), hit = VAR_RE.exec(n);
      let base = null, pose = null;
      if (m && typeof m.of === 'string') { base = m.of; pose = m.pose; } else if (hit) { base = hit[2]; pose = hit[1]; }
      if (!base || VAR_POSES.indexOf(pose) < 0 || !bases.has(base) || base === n) continue;
      (out[base] || (out[base] = {}))[pose] = n;
    }
    return out;
  }
  function extras(clips) {
    const out = { motions: [], dances: [], skipped: [], variants: {} };
    if (!clips || typeof clips !== 'object') return out;
    out.variants = variants(clips);
    const vset = new Set();
    for (const b of Object.keys(out.variants)) for (const p of Object.keys(out.variants[b])) vset.add(out.variants[b][p]);
    for (const name of Object.keys(clips).sort()) {
      const c = clips[name], m = c && c.motion;
      if (m === undefined || m === null) continue;
      if (vset.has(name)) continue;   // 자세별 판은 따로 부르는 동작이 아님(위 variants)
      const skip = why => { if (out.skipped.length < 50) out.skipped.push([String(name).slice(0, 40), why]); };
      if (typeof m !== 'object' || Array.isArray(m)) { skip('motion 칸이 물건({…})이 아님'); continue; }
      if (!EX_NAME.test(name)) { skip('클립 이름 형식'); continue; }
      if (isBuiltin(name) || EX_ENGINE.test(name)) { skip('앱에 원래 있는 이름'); continue; }
      const kind = m.kind === 'dance' ? 'dance' : m.kind === 'once' || m.kind === undefined ? 'once' : null;
      if (!kind) { skip('kind 는 once 또는 dance'); continue; }
      if ((kind === 'dance') !== /^dance_/.test(name)) { skip(kind === 'dance' ? '춤 이름은 dance_ 로 시작' : 'dance_ 로 시작하는 이름은 춤(kind dance)만'); continue; }
      const ko = exText(m.ko, 20) || name;
      const calls = [];
      for (const x of Array.isArray(m.calls) ? m.calls : Array.isArray(m.say) ? m.say : []) {
        const t = exText(x, 20);
        if (t && t.replace(/ /g, '').length >= 2 && calls.indexOf(t) < 0 && calls.length < EX_MAX.calls) calls.push(t);
      }
      if (kind === 'once') {
        if (out.motions.length >= EX_MAX.once) { skip('동작이 너무 많음(100개까지)'); continue; }
        const p0 = m.pose !== undefined ? m.pose : m.pose_at;
        const pose = p0 === 'sit' || p0 === 'lie' || p0 === 'stand' ? p0 : p0 === undefined ? (/^sit_/.test(name) ? 'sit' : /^lie_/.test(name) ? 'lie' : 'stand') : null;
        if (!pose) { skip('pose 는 stand·sit·lie'); continue; }
        out.motions.push({ name, ko, calls, pose, phone: m.phone !== false });
      } else {
        if (out.dances.length >= EX_MAX.dance) { skip('춤이 너무 많음(30개까지)'); continue; }
        const lp = Number.isInteger(m.loops) && m.loops >= 1 && m.loops <= 8 ? m.loops : null;
        const mu = typeof m.music === 'string' && m.music.trim().length >= 1 && m.music.trim().length <= 40 && !/[\\/:*?"<>|\u0000-\u001f]/.test(m.music) ? m.music.trim() : null;
        out.dances.push({ name, ko, calls, loops: lp, music: mu });
      }
    }
    return out;
  }
  const api = { ALIAS, DANCES, GESTURES, NEED, FALLBACK, resolve, EMOTIONS, emotionOf, extras, variants, isBuiltin };
  if (typeof module === 'object' && module.exports) module.exports = api; else root.MOTION_NAMES = api;
})(typeof window !== 'undefined' ? window : this);
