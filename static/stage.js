const body = document.getElementById('body');
const titleBox = document.getElementById('title');
const pin = new URLSearchParams(location.search).get('pin');
let view = null;
let socket = null;
let drawnKey = null;
let closed = false;

/* --- səs: bütün melodiyalar brauzerdə sintez olunur, heç bir səs faylı yoxdur --- */
const sound = {
  on: localStorage.getItem('tralala:sound') !== 'off',
  ctx: null,
  loop: null,
  wake() {
    this.ctx ??= new AudioContext();
    this.ctx.resume();
  },
  tone(freq, at = 0, length = .18, volume = .08, shape = 'triangle') {
    if (!this.on || !this.ctx || this.ctx.state !== 'running') return;
    const start = this.ctx.currentTime + at;
    const osc = this.ctx.createOscillator();
    const gain = this.ctx.createGain();
    osc.type = shape;
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(volume, start);
    gain.gain.exponentialRampToValueAtTime(.0001, start + length);
    osc.connect(gain).connect(this.ctx.destination);
    osc.start(start);
    osc.stop(start + length);
  },
  phrase(notes, gap = .13) {
    notes.forEach((note, i) => note && this.tone(note, i * gap, gap * 1.6));
  },
  lobby(active) {
    clearInterval(this.loop);
    this.loop = null;
    if (!active) return;
    const lines = [[262, 330, 392, 330], [294, 349, 440, 349], [247, 330, 392, 330], [262, 392, 523, 392]];
    let bar = 0;
    this.loop = setInterval(() => this.phrase(lines[bar++ % lines.length], .24), 1000);
  },
  tick() { this.tone(880, 0, .05, .05, 'square'); },
  reveal() { this.phrase([392, 494, 587, 784]); },
  fanfare() { this.phrase([392, 392, 523, 0, 392, 523, 659, 784, 1047], .15); },
};

document.addEventListener('click', () => {
  sound.wake();
  if (view?.phase === 'lobby' && !sound.loop) sound.lobby(true);
});

document.getElementById('sound').onclick = event => {
  sound.on = !sound.on;
  localStorage.setItem('tralala:sound', sound.on ? 'on' : 'off');
  event.target.textContent = `Səs: ${sound.on ? 'açıq' : 'bağlı'}`;
};
document.getElementById('sound').textContent = `Səs: ${sound.on ? 'açıq' : 'bağlı'}`;
document.getElementById('finish').onclick = () => {
  if (view.phase === 'lobby') return (location.href = '/admin');
  if (view.phase === 'podium' || confirm('Oyun indi bitirilsin? Nəticələr saxlanacaq.')) act('finish');
};

/* --- Aparıcının xal düzəlişi: ədalətsizlik olanda istənilən oyunçunun xalını silmək və ya qaytarmaq --- */
const scorePanel = {
  box: null,
  build() {
    this.box = document.createElement('div');
    this.box.className = 'scores-panel';
    this.box.hidden = true;
    this.box.innerHTML = `
      <div class="row spread"><h2>Xal düzəlişi</h2><button class="btn ghost small" data-close>Bağla</button></div>
      <p class="s-note" style="text-align:left;margin:0">Dəyişiklik dərhal sıralamaya düşür, oyunçunun telefonuna bildiriş gedir, hesabatda qeyd olunur.</p>
      <div class="grid2">
        <div><label class="lbl" for="adjAmount">Miqdar</label>
          <input class="field" id="adjAmount" type="number" min="1" step="50" value="500"></div>
        <div><label class="lbl" for="adjReason">Səbəb (istəyə bağlı)</label>
          <input class="field" id="adjReason" maxlength="100" placeholder="Məs: telefona baxıb köçürdü"></div>
      </div>
      <div class="scores-list" id="adjList"></div>`;
    document.body.append(this.box);
    this.box.addEventListener('click', event => {
      if (event.target.closest('[data-close]')) return this.close();
      const button = event.target.closest('[data-adj]');
      if (!button) return;
      const amount = Math.abs(parseInt(document.getElementById('adjAmount').value, 10));
      const reason = document.getElementById('adjReason').value.trim();
      const { adj, token, name } = button.dataset;
      if (adj === 'zero') {
        if (confirm(`${name} adlı oyunçunun bütün xalı silinsin?`)) act('adjust', { token, zero: true, reason });
        return;
      }
      if (!amount) return toast('Miqdarı yazın', true);
      act('adjust', { token, delta: adj === 'minus' ? -amount : amount, reason });
    });
  },
  open() { this.box.hidden = false; this.refresh(); },
  close() { this.box.hidden = true; },
  refresh() {
    const live = view && view.phase !== 'lobby' && view.players?.length;
    document.getElementById('scores').hidden = !live;
    if (!live) return this.close();
    if (this.box.hidden) return;
    // Ada görə sabit sıra: düzəlişdən sonra sətirlər yer dəyişməsin, səhv adama basılmasın.
    const rows = [...view.players].sort((a, b) => a.name.localeCompare(b.name, 'az'));
    document.getElementById('adjList').innerHTML = rows.map(p => `<div class="adj-row">
      <span class="grow"><b>${esc(p.name)}</b>${p.online ? '' : ' <small class="muted">offline</small>'}</span>
      <span class="adj-score">${p.score}</span>
      <button class="btn danger small" data-adj="minus" data-token="${esc(p.token)}" data-name="${esc(p.name)}">− sil</button>
      <button class="btn ghost small" data-adj="plus" data-token="${esc(p.token)}" data-name="${esc(p.name)}">+ qaytar</button>
      <button class="btn danger small" data-adj="zero" data-token="${esc(p.token)}" data-name="${esc(p.name)}">Sıfırla</button>
    </div>`).join('');
  },
};
scorePanel.build();
document.getElementById('scores').onclick = () => (scorePanel.box.hidden ? scorePanel.open() : scorePanel.close());

function act(action, extra = {}) {
  socket?.send(JSON.stringify({ action, ...extra }));
}

function connect() {
  socket = new WebSocket(wsUrl(`/ws/host/${pin}`));
  socket.onmessage = event => {
    const data = JSON.parse(event.data);
    if (data.keep) return toast(data.error, true);
    if (data.phase === 'closed') {
      closed = true;
      body.innerHTML = `<div class="center"><h1>Bu otaq artıq yoxdur</h1><a class="btn primary" href="/admin">Panelə qayıt</a></div>`;
      return;
    }
    view = data;
    draw();
  };
  socket.onclose = () => { if (!closed) setTimeout(connect, 1000); };
}

function draw() {
  titleBox.textContent = view.phase === 'lobby' ? view.title
    : view.index >= 0 && view.phase !== 'podium' ? `Sual ${view.index + 1} / ${view.total}` : view.title;
  document.getElementById('finish').textContent = view.phase === 'lobby' ? 'Panelə qayıt'
    : view.phase === 'podium' ? 'Bağlı' : 'Oyunu bitir';
  document.getElementById('finish').hidden = view.phase === 'podium';
  sound.lobby(view.phase === 'lobby' && sound.ctx?.state === 'running');
  scorePanel.refresh();

  if (view.phase === 'lobby') { lobby(); return swapIn(body, 'lobby'); }
  if (view.phase === 'question' && drawnKey === `question:${view.index}:`) return updateAnswered();
  const scoreKey = (view.standings || []).map(row => row.score).join(',');
  const key = `${view.phase}:${view.index}:${['board', 'podium'].includes(view.phase) ? scoreKey : ''}`;
  if (key === drawnKey) return;
  drawnKey = key;
  ({ media, intro, question, reveal, board, podium })[view.phase]();
  swapIn(body, `${view.phase}:${view.index}`);
}

function lobby() {
  const fresh = drawnKey !== 'lobby';
  drawnKey = 'lobby';
  if (fresh) {
    body.innerHTML = `<div class="lobby">
      <div class="joincard">
        <b>Telefonla skan et</b>
        <img src="/api/rooms/${esc(pin)}/qr.svg" alt="Qoşulma QR kodu">
        <span class="muted">və ya kodu yaz</span>
        <div class="pin">${esc(pin)}</div>
        <div class="url" id="url"></div>
      </div>
      <div class="lobby-side">
        <h2 id="count"></h2>
        <div class="chips" id="chips"></div>
        <div class="controls" id="controls"></div>
      </div></div>`;
    document.getElementById('chips').onclick = event => {
      const chip = event.target.closest('.chip');
      if (chip && confirm(`${chip.textContent} oyundan çıxarılsın?`)) act('kick', { token: chip.dataset.token });
    };
    document.getElementById('controls').onclick = event => {
      const button = event.target.closest('[data-config]');
      if (button) act('config', JSON.parse(button.dataset.config));
      if (event.target.id === 'start') act('start');
    };
  }
  document.getElementById('url').textContent = view.join_url.split('?')[0];
  document.getElementById('count').textContent = view.players.length
    ? `${view.players.length} oyunçu səhnədədir` : 'Oyunçular gözlənilir…';
  document.getElementById('chips').innerHTML = view.players.map(p =>
    `<button class="chip${p.online ? '' : ' off'}" data-token="${esc(p.token)}" title="Çıxarmaq üçün klikləyin">${esc(p.name)}</button>`).join('');
  const seg = (items) => `<span class="seg">${items.map(([label, config, on]) =>
    `<button class="${on ? 'on' : ''}" data-config='${JSON.stringify(config)}'>${label}</button>`).join('')}</span>`;
  document.getElementById('controls').innerHTML =
    seg([['Fərdi', { mode: 'solo' }, view.mode === 'solo'], ['Komanda', { mode: 'team' }, view.mode === 'team']]) +
    (view.mode === 'team' ? seg([2, 3, 4].map(n => [`${n} komanda`, { team_count: n }, view.team_count === n])) : '') +
    seg([['Əl ilə', { auto: false }, !view.auto], ['Avtomatik', { auto: true }, view.auto]]) +
    (view.ai_ready ? seg([['AI zarafatı', { jokes: true }, view.jokes], ['Zarafatsız', { jokes: false }, !view.jokes]]) : '') +
    `<button class="btn primary start" id="start" ${view.players.length ? '' : 'disabled'}>Başla</button>`;
}

/* Sualdan əvvəl yalnız şəkil və ya video göstərilir. */
function media() {
  const m = view.question.media;
  body.innerHTML = `
    <div class="s-media">${mediaHtml(m, 's-media-item', { play: true })}</div>
    <div class="s-timebar" ${m.kind === 'image' ? '' : 'hidden'}><b id="bar"></b></div>
    <div class="s-foot"><span>${m.kind === 'video' ? 'Video bitəndə sual açılacaq' : 'Diqqətlə bax'}</span>
      <button class="btn primary" id="toQuestion">Suala keç</button></div>`;
  document.getElementById('toQuestion').onclick = () => act('media_done');
  if (m.kind === 'image') {
    runTimebar(document.getElementById('bar'), view.image_seconds * 1000, view.image_seconds * 1000);
    return;
  }
  const video = body.querySelector('video');
  video.onended = () => act('media_done');
  video.onerror = () => toast('Video oynadılmadı. “Suala keç” düyməsini basın.', true);
  video.play().catch(() => {
    /* Brauzer səsli avtomatik oynatmanı bloklayıbsa, aparıcı özü başladır. */
    video.controls = true;
    toast('Videonu başlatmaq üçün üzərinə basın');
  });
}

function intro() {
  const q = view.question;
  sound.phrase([523, 659]);
  body.innerHTML = `<div class="center">
    <p class="s-note">${esc(TYPE_LABELS[q.type])}${q.points === 2 ? ' · 2× xal' : ''}</p>
    <div class="s-question">${esc(q.text)}</div>
    <div class="s-timebar" style="width:60%"><b id="bar"></b></div></div>`;
  runTimebar(document.getElementById('bar'), view.intro_seconds * 1000, view.intro_seconds * 1000);
}

function optionCards(q, extra = () => '', classes = () => '') {
  return `<div class="s-opts">${q.options.map((text, i) => `<div class="s-opt o${i % 6} ${classes(i)}">
    <span class="tag">${NOTES[i]}</span><span>${esc(text)}</span>${extra(i)}</div>`).join('')}</div>`;
}

function question() {
  const q = view.question;
  let middle = '';
  if (q.options) middle = optionCards(q);
  if (q.type === 'text') middle = '<p class="s-note center">Oyunçular cavabı telefonda yazır</p>';
  if (q.type === 'cloud') middle = '<p class="s-note center">Oyunçular sözlərini yazır</p>';
  if (q.type === 'slider') middle = `<p class="s-note center">${q.min} ilə ${q.max} arasında seçim</p>`;
  body.innerHTML = `
    <div class="s-question">${esc(q.text)}</div>
    ${mediaHtml(q.media, 's-img')}
    ${middle}
    <div class="s-timebar"><b id="bar"></b></div>
    <div class="s-foot"><span id="left"></span><span id="answered"></span>
      <button class="btn ghost small" id="skip">Vaxtı bitir</button></div>`;
  document.getElementById('skip').onclick = () => act('next');
  let lastSecond = null;
  runTimebar(document.getElementById('bar'), q.remaining_ms, q.time * 1000, left => {
    const second = Math.ceil(left / 1000);
    if (second !== lastSecond) {
      lastSecond = second;
      document.getElementById('left').textContent = `${second} san`;
      if (second > 0 && second <= 5) sound.tick();
    }
  });
  updateAnswered();
}

function updateAnswered() {
  const box = document.getElementById('answered');
  if (box) box.textContent = `${view.answered} / ${view.players.length} cavab`;
}

function nextButton(label = 'Növbəti') {
  return view.auto ? '<span class="muted">Avtomatik davam edir…</span>'
    : `<button class="btn primary" id="next">${label}</button>`;
}

function bindNext() {
  const button = document.getElementById('next');
  if (button) button.onclick = () => act('next');
}

function reveal() {
  sound.reveal();
  const q = view.question;
  const r = view.reveal;
  let middle = '';
  if (q.options && q.type !== 'order') {
    const scored = r.correct.length > 0;
    middle = optionCards(q,
      i => `<span class="n">${r.counts[i]}</span>`,
      i => !scored ? '' : r.correct.includes(i) ? 'hit' : 'dim');
  } else if (q.type === 'order') {
    middle = `<div class="s-answer center">${esc(r.answer)}</div>`;
  } else if (q.type === 'text' || q.type === 'cloud') {
    const most = Math.max(1, ...r.words.map(w => w.count));
    const colors = ['#FFB627', '#7FE0D6', '#FF9C94', '#FFF7EA', '#F2A6CF'];
    middle = `${q.type === 'text' ? `<div class="s-answer">${esc(r.answer)}</div>` : ''}
      <div class="cloud">${r.words.map((w, i) => `<span style="font-size:${1.2 + 2.6 * w.count / most}rem;color:${colors[i % 5]}">${esc(w.text)}</span>`).join('') || '<span>Cavab gəlmədi</span>'}</div>`;
  } else if (q.type === 'slider') {
    const place = value => 100 * (value - q.min) / (q.max - q.min);
    middle = `<div class="s-answer">${esc(r.answer)}</div>
      <div class="dots">${r.values.map(v => `<i style="left:${place(v)}%"></i>`).join('')}
        <b style="left:${place(Number(r.answer))}%"></b></div>
      <p class="s-note">${r.average === null ? 'Cavab gəlmədi' : `Ortalama: ${r.average}`}</p>`;
  }
  const scoredLine = q.points ? `${r.right} / ${view.players.length} düz` : `${r.answered} cavab`;
  body.innerHTML = `
    <div class="s-question">${esc(q.text)}</div>
    ${middle}
    ${r.explanation ? `<p class="s-note">${esc(r.explanation)}</p>` : ''}
    <div class="s-foot"><span>${scoredLine}</span>${nextButton()}</div>`;
  bindNext();
}

function board() {
  const rows = view.standings.slice(0, 5).map(row => `<div class="board-row">
    <span class="pos">${row.rank}</span><span>${esc(row.name)}</span>
    ${row.streak > 1 ? `<span class="sub">${row.streak} ardıcıl</span>` : ''}
    <span class="pts">${row.score}</span></div>`).join('');
  const teams = view.teams.map(team => `<div class="board-row">
    <span>${esc(team.name)} komandası</span><span class="sub">${team.members} nəfər</span>
    <span class="pts">${team.score}</span></div>`).join('');
  const last = view.index + 1 >= view.total;
  body.innerHTML = `
    ${teams ? `<div class="board"><h2>Komandalar</h2>${teams}</div>` : ''}
    <div class="board"><h2>Ən yaxşı beşlik</h2>${rows}</div>
    <div class="s-foot" style="margin-top:auto"><span></span>${nextButton(last ? 'Nəticələr' : 'Növbəti sual')}</div>`;
  bindNext();
}

function podium() {
  sound.fanfare();
  const [first, second, third] = view.standings;
  const step = (row, place) => !row ? '' : `<div class="step p${place}">
    <div class="name">${esc(row.name)}</div>
    <div class="block">${place}<small>${row.score} xal</small></div></div>`;
  const team = view.teams[0];
  body.innerHTML = `
    ${team ? `<h2 style="text-align:center">Qalib komanda: ${esc(team.name)} · ${team.score} xal</h2>` : ''}
    <div class="podium">${step(second, 2)}${step(first, 1)}${step(third, 3)}</div>
    <div class="s-foot"><a class="btn ghost" href="/admin#games${view.game_id ? '/' + view.game_id : ''}">Hesabat</a>
      <a class="btn primary" href="/admin">Panelə qayıt</a></div>`;
  for (let i = 0; i < 26; i++) {
    const note = document.createElement('span');
    note.className = 'fall';
    note.textContent = i % 2 ? '♪' : '♫';
    note.style.left = `${Math.random() * 100}vw`;
    note.style.color = ['#FFB627', '#F4483C', '#7FE0D6'][i % 3];
    note.style.animationDuration = `${3 + Math.random() * 3}s`;
    note.style.animationDelay = `${Math.random() * 2}s`;
    document.body.append(note);
    note.onanimationend = () => note.remove();
  }
}

if (!window.TOURNAMENT) {
  if (pin) connect(); else location.href = '/admin';
}
