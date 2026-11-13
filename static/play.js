const app = document.getElementById('app');
const top_ = document.getElementById('top');
const offline = document.getElementById('offline');
const params = new URLSearchParams(location.search);

let pin = params.get('pin') || '';
let socket = null;
let renderedKey = null;
let retry = 0;
let finished = false;
let pendingName = null;

const tokenKey = () => `tralala:${pin}`;

/* Telefonun daimi ID-si: reytinq və turnir oyunçunu bununla tanıyır, adla yox.
   Yerli şəbəkədə (http) crypto.randomUUID işləmir, ona görə getRandomValues işlənir. */
function playerId() {
  let id = localStorage.getItem('tralala:pid');
  if (!/^[0-9a-f]{32}$/.test(id || '')) {
    id = [...crypto.getRandomValues(new Uint8Array(16))].map(b => b.toString(16).padStart(2, '0')).join('');
    localStorage.setItem('tralala:pid', id);
  }
  return id;
}

const savedName = () => localStorage.getItem('tralala:name') || '';

function showPinForm(error = '') {
  top_.hidden = true;
  renderedKey = null;
  app.innerHTML = `
    <div class="center">
      <h1 class="logo hero">tra<i>la</i>la</h1>
      <div class="staff"></div>
      <form class="join-box" id="pinForm">
        <input class="field" id="pin" inputmode="numeric" autocomplete="off" maxlength="6"
               placeholder="Oyun kodu" aria-label="Oyun kodu" value="${esc(pin)}">
        <button class="btn primary">Davam et</button>
        <div class="err" role="alert">${esc(error)}</div>
      </form>
    </div>`;
  document.getElementById('pinForm').onsubmit = async event => {
    event.preventDefault();
    pin = document.getElementById('pin').value.trim();
    checkRoom();
  };
}

function showNameForm(title, error = '') {
  top_.hidden = true;
  renderedKey = null;
  app.innerHTML = `
    <div class="center">
      <h1 class="logo" style="font-size:2.6rem">tra<i>la</i>la</h1>
      <p class="muted">${esc(title)}</p>
      <form class="join-box" id="nameForm">
        <input class="field" id="name" maxlength="20" autocomplete="nickname" placeholder="Adın" aria-label="Adın"
               value="${esc(localStorage.getItem('tralala:name') || '')}">
        <button class="btn primary">Oyuna qoşul</button>
        <div class="err" role="alert">${esc(error)}</div>
      </form>
      <p class="muted">Telefonun yadda qalır: növbəti dəfə QR kodu oxudanda ad yazmadan qoşulacaqsan, xalların reytinqə yığılacaq.</p>
    </div>`;
  document.getElementById('nameForm').onsubmit = event => {
    event.preventDefault();
    const name = document.getElementById('name').value.trim();
    if (!name) return;
    localStorage.setItem('tralala:name', name);
    pendingName = name;
    connect();
  };
}

async function checkRoom() {
  if (!/^\d{6}$/.test(pin)) return showPinForm(pin ? 'Kod 6 rəqəmdən ibarətdir' : '');
  try {
    const room = await api(`/api/rooms/${pin}`);
    if (localStorage.getItem(tokenKey()) || savedName()) return connect();
    showNameForm(room.title);
  } catch (error) {
    localStorage.removeItem(tokenKey());
    showPinForm(error.message);
  }
}

function connect() {
  socket?.close();
  const ws = new WebSocket(wsUrl(`/ws/play/${pin}`));
  socket = ws;
  ws.onopen = () => {
    ws.send(JSON.stringify({ name: pendingName || savedName(), token: localStorage.getItem(tokenKey()), pid: playerId() }));
  };
  ws.onmessage = event => {
    retry = 0;
    offline.hidden = true;
    const data = JSON.parse(event.data);
    if (data.toast) return toast(data.toast, data.bad !== false);
    if (data.ai) return askReply(data.ai);
    if (data.quip) return showQuip(data.quip);
    if (data.finale) return showFinale(data.finale);
    render(data);
  };
  ws.onclose = () => {
    if (socket !== ws || finished || !localStorage.getItem(tokenKey())) return;
    offline.hidden = false;
    setTimeout(connect, Math.min(4000, 500 * 2 ** retry++));
  };
}

function send(answer) {
  socket?.send(JSON.stringify({ answer }));
}

function endScreen(title, text) {
  finished = true;
  top_.hidden = true;
  offline.hidden = true;
  app.innerHTML = `<div class="center"><h1>${esc(title)}</h1><p class="muted">${esc(text)}</p>
    <a class="btn" href="/">Başqa oyuna qoşul</a></div>`;
  swapIn(app, 'end');
}

function render(view) {
  if (view.phase === 'refused') {
    localStorage.removeItem(tokenKey());
    pendingName = null;
    return showNameForm('', view.error);
  }
  if (view.phase === 'kicked') {
    localStorage.removeItem(tokenKey());
    return endScreen('Oyundan çıxarıldın', 'Aparıcı səni otaqdan çıxardı.');
  }
  if (view.phase === 'closed') {
    localStorage.removeItem(tokenKey());
    return endScreen('Oyun bağlandı', 'Bu otaq artıq açıq deyil.');
  }
  if (view.phase === 'replaced') return endScreen('Başqa pəncərədə açıldı', 'Oyun indi digər pəncərədə davam edir.');

  localStorage.setItem(tokenKey(), view.me.token);
  const me = view.me;
  top_.hidden = false;
  top_.innerHTML = `<span>${esc(me.name)}${me.team ? ` · ${esc(me.team)}` : ''}</span>
    <span class="score">${me.score}</span>`;

  /* Eyni ekran yenidən çəkilmir, yoxsa yarımçıq yazılan cavab itər. */
  const live = ['reveal', 'board', 'podium'].includes(view.phase) ? `${me.score}:${me.rank}:${JSON.stringify(view.standings || '')}` : '';
  const key = `${view.phase}:${view.index}:${view.answered ?? ''}:${live}`;
  if (key === renderedKey && view.phase !== 'lobby' && !view.phase.startsWith('t_')) return;
  if (document.activeElement?.id === 'newName') return;  // ad dəyişdirilərkən ekranı yeniləmə
  renderedKey = key;
  ({ lobby, media, intro, question, reveal, board, podium, ...TOURNAMENT_SCREENS })[view.phase](view);
  swapIn(app, `${view.phase}:${view.index ?? ''}:${view.answered ?? ''}`);
  askPanel.note(view.phase === 'question' && !view.answered);
}

function lobby(view) {
  app.innerHTML = `<div class="center">
    <h2 style="font-size:2rem">Sən içəridəsən!</h2>
    <div class="staff"></div>
    <p>Aparıcı başladanda sual burada açılacaq.</p>
    <p class="muted">${view.me.players} nəfər qoşulub</p>
    <div class="roster">${(view.roster || []).map(name =>
      `<span class="${name === view.me.name ? 'me' : ''}">${esc(name)}</span>`).join('')}</div>
    ${renameBox(view)}</div>`;
  bindRename();
}

/* Sual zamanı şəkil təkrar görünür, video isə səssiz önizləmə kimi (yenidən baxmaq olar). */
function imageHtml(question) {
  return mediaHtml(question.media, 'q-img');
}

/* Sualdan əvvəl şəkil və ya video hər kəsin öz telefonunda göstərilir. */
function media(view) {
  const m = view.question.media;
  const video = m.kind === 'video';
  app.innerHTML = `<div class="center">
    <p class="muted">Sual ${view.index + 1} / ${view.total} · diqqətlə bax</p>
    <div class="phone-media">${mediaHtml(m, 'phone-media-item', { play: true })}</div>
    ${video ? '<button class="btn primary" id="unmute" hidden>Səsi aç</button>' : ''}
    <p class="muted">${video ? 'Video bitəndə sual açılacaq.' : 'Bir neçə saniyədən sonra sual açılacaq.'}</p></div>`;
  if (!video) return;
  const player = app.querySelector('video');
  const unmute = document.getElementById('unmute');
  /* Telefon brauzeri səsli avtomatik oynatmanı bloklaya bilər: onda səssiz oynayır, oyunçu səsi özü açır. */
  player.play().catch(() => {
    player.muted = true;
    unmute.hidden = false;
    player.play().catch(() => { player.controls = true; });
  });
  unmute.onclick = () => {
    player.muted = false;
    player.play();
    unmute.hidden = true;
  };
}

function intro(view) {
  const q = view.question;
  app.innerHTML = `<div class="center">
    <p class="muted">Sual ${view.index + 1} / ${view.total} · ${esc(TYPE_LABELS[q.type])}${q.points === 2 ? ' · 2× xal' : ''}</p>
    <div class="q-text">${esc(q.text)}</div>
    <h2>Hazır ol…</h2></div>`;
}

function question(view) {
  if (view.answered) {
    app.innerHTML = `<div class="center"><div class="hero">♪</div><h2>Cavabın qəbul olundu</h2>
      <p class="muted">Digərləri gözlənilir…</p></div>`;
    return;
  }
  const q = view.question;
  app.innerHTML = `
    <div class="timebar"><b id="bar"></b></div>
    <div class="q-text">${esc(q.text)}</div>${imageHtml(q)}
    <div class="answers" id="answers"></div>`;
  runTimebar(document.getElementById('bar'), q.remaining_ms, q.time * 1000);
  ({ choice: pickOne, truefalse: pickOne, poll: pickOne, multi: pickMany, order: pickOrder,
     text: typeAnswer, cloud: typeAnswer, slider: slide })[q.type](q, document.getElementById('answers'));
}

function optionButton(text, index) {
  return `<button class="answer o${index % 6}" data-i="${index}">
    <span class="tag">${NOTES[index]}</span><span>${esc(text)}</span></button>`;
}

function pickOne(q, box) {
  box.innerHTML = q.options.map(optionButton).join('');
  box.onclick = event => {
    const button = event.target.closest('.answer');
    if (button) send(Number(button.dataset.i));
  };
}

function pickMany(q, box) {
  const picked = new Set();
  box.innerHTML = q.options.map(optionButton).join('') + '<button class="btn primary" id="go" disabled>Göndər</button>';
  const go = document.getElementById('go');
  box.onclick = event => {
    const button = event.target.closest('.answer');
    if (!button) return;
    const index = Number(button.dataset.i);
    picked.has(index) ? picked.delete(index) : picked.add(index);
    button.classList.toggle('on', picked.has(index));
    button.setAttribute('aria-pressed', picked.has(index));
    go.disabled = picked.size === 0;
  };
  go.onclick = event => {
    event.stopPropagation();
    send([...picked]);
  };
}

function pickOrder(q, box) {
  const sequence = [];
  box.innerHTML = `<p class="muted" style="margin:0">Düzgün sıra ilə toxun. Geri almaq üçün yenidən toxun.</p>` +
    q.options.map((text, i) => `<button class="answer plain" data-i="${i}">
      <span class="tag" data-slot>–</span><span>${esc(text)}</span></button>`).join('') +
    '<button class="btn primary" id="go" disabled>Göndər</button>';
  const go = document.getElementById('go');
  const draw = () => {
    box.querySelectorAll('.answer').forEach(button => {
      const place = sequence.indexOf(Number(button.dataset.i));
      button.classList.toggle('on', place >= 0);
      button.querySelector('[data-slot]').textContent = place >= 0 ? place + 1 : '–';
    });
    go.disabled = sequence.length !== q.options.length;
  };
  box.onclick = event => {
    const button = event.target.closest('.answer');
    if (!button) return;
    const index = Number(button.dataset.i);
    const place = sequence.indexOf(index);
    place >= 0 ? sequence.splice(place, 1) : sequence.push(index);
    draw();
  };
  go.onclick = event => {
    event.stopPropagation();
    send(sequence);
  };
}

function typeAnswer(q, box) {
  box.innerHTML = `<form class="join-box" id="typed">
    <input class="field" id="typedValue" maxlength="40" autocomplete="off" autofocus
           placeholder="${q.type === 'cloud' ? 'Bir söz yaz' : 'Cavabını yaz'}" aria-label="Cavab">
    <button class="btn primary">Göndər</button></form>`;
  document.getElementById('typed').onsubmit = event => {
    event.preventDefault();
    const value = document.getElementById('typedValue').value.trim();
    if (value) send(value);
  };
}

function slide(q, box) {
  const start = q.min + Math.round((q.max - q.min) / 2 / q.step) * q.step;
  box.innerHTML = `<div class="center">
    <div class="big-value" id="value">${start}</div>
    <input type="range" id="range" min="${q.min}" max="${q.max}" step="${q.step}" value="${start}" aria-label="Cavab">
    <div class="range-ends" style="width:100%"><span>${q.min}</span><span>${q.max}</span></div>
    <button class="btn primary" id="go" style="width:100%">Göndər</button></div>`;
  const range = document.getElementById('range');
  range.oninput = () => { document.getElementById('value').textContent = range.value; };
  document.getElementById('go').onclick = () => send(Number(range.value));
}

function reveal(view) {
  const r = view.result;
  const rv = view.reveal;
  let verdict;
  if (!r.scored) {
    verdict = `<div class="verdict none"><h2>${r.answered ? 'Təşəkkürlər!' : 'Cavab vermədin'}</h2>
      <p>Bu sual xal gətirmir.</p></div>`;
  } else if (!r.answered) {
    verdict = `<div class="verdict none"><h2>Vaxt bitdi</h2></div>`;
  } else if (r.correct) {
    verdict = `<div class="verdict good"><h2>Düzdür!</h2><div class="pts">+${r.points + r.bonus}</div>
      ${r.bonus ? `<p>Seriya bonusu +${r.bonus} · ${view.me.streak} ardıcıl</p>` : ''}</div>`;
  } else if (r.partial && r.points) {
    verdict = `<div class="verdict half"><h2>Qismən düzdür</h2><div class="pts">+${r.points}</div></div>`;
  } else {
    verdict = `<div class="verdict bad"><h2>Səhvdir</h2></div>`;
  }
  const askable = rv.answer && view.question.type !== 'poll' && view.question.type !== 'cloud';
  app.innerHTML = `<div class="center">${verdict}
    ${rv.answer ? `<p><span class="muted">Düzgün cavab</span><br><b>${esc(rv.answer)}</b></p>` : ''}
    ${askable ? `<button class="btn teal" data-ask="${view.index}" data-text="${esc(view.question.text)}">Niyə belədir? AI-dan soruş</button>` : ''}
    ${rv.explanation ? `<p class="muted">${esc(rv.explanation)}</p>` : ''}
    ${quipHtml(view.index)}
    ${resultsHtml(view.question, rv)}
    <p class="muted">${ordinal(view.me.rank)} yerdəsən</p></div>`;
}

/* --- AI zarafatları: cavabdan bir neçə saniyə sonra gəlir, gəlməsə heç nə göstərilmir --- */
const quips = {};
let finaleLine = null;

function quipHtml(index) {
  const text = quips[index];
  return `<div class="quip" data-quip="${index}" ${text ? '' : 'hidden'}>${text ? esc(text) : ''}</div>`;
}

function showQuip(quip) {
  quips[quip.index] = quip.text;
  document.querySelectorAll(`[data-quip="${quip.index}"]`).forEach(box => {
    box.textContent = quip.text;
    box.hidden = false;
  });
}

function finaleHtml() {
  return `<div class="quip finale" id="finale" ${finaleLine ? '' : 'hidden'}>${finaleLine
    ? `<b>${esc(finaleLine.title)}</b><span>${esc(finaleLine.text)}</span>` : ''}</div>`;
}

function showFinale(line) {
  finaleLine = line;
  const box = document.getElementById('finale');
  if (box) box.outerHTML = finaleHtml();
}

/* Hamı nə seçdi: variantlar üzrə say, yazılı cavablar, şkalanın ortalaması. */
function resultsHtml(q, rv) {
  if (rv.counts) {
    const most = Math.max(1, ...rv.counts);
    return `<div class="results"><small class="muted">${q.type === 'poll' ? 'Sorğunun nəticəsi' : 'Kim nə seçdi'}</small>
      ${q.options.map((text, i) => `<div class="res-row o${i % 6} ${rv.correct.includes(i) ? 'hit' : ''}">
        <i style="width:${(100 * rv.counts[i]) / most}%"></i>
        <span>${rv.correct.includes(i) ? '✓ ' : ''}${esc(text)}</span><b>${rv.counts[i]}</b></div>`).join('')}</div>`;
  }
  if (rv.words?.length) {
    return `<div class="results"><small class="muted">Yazılan cavablar</small><div class="roster">${rv.words.slice(0, 15)
      .map(w => `<span>${esc(w.text)}${w.count > 1 ? ` · ${w.count}` : ''}</span>`).join('')}</div></div>`;
  }
  if (q.type === 'slider' && rv.average !== null) return `<p class="muted">Hamının ortalaması: <b>${rv.average}</b></p>`;
  return '';
}

function board(view) {
  const me = view.me;
  const inTop = view.standings.some(row => row.name === me.name);
  const row = r => `<div class="lb-row ${r.name === me.name ? 'me' : ''}"><span class="pos">${r.rank}</span>
    <span class="grow">${esc(r.name)}</span><b>${r.score}</b></div>`;
  app.innerHTML = `<div class="center">
    ${view.teams.length ? `<div class="leaderboard"><small class="muted">Komandalar</small>${view.teams.map(t =>
      `<div class="lb-row ${t.name === me.team ? 'me' : ''}"><span class="grow">${esc(t.name)} komandası</span><b>${t.score}</b></div>`).join('')}</div>` : ''}
    <div class="leaderboard"><small class="muted">Ən yaxşı beşlik</small>${view.standings.map(row).join('')}
      ${inTop ? '' : `<div class="lb-gap">…</div>${row({ rank: me.rank, name: me.name, score: me.score })}`}</div>
    <p class="muted">${me.players} nəfər arasında ${ordinal(me.rank)} yerdəsən${me.streak > 1 ? ` · ${me.streak} ardıcıl düz` : ''}</p>
    ${quipHtml(view.index)}</div>`;
}

function podium(view) {
  const me = view.me;
  const place = me.rank === 1 ? 'Qalib sənsən!' : `${ordinal(me.rank)} yer`;
  const teams = view.teams.length
    ? `<p>Qalib komanda: <b>${esc(view.teams[0].name)}</b></p>` : '';
  app.innerHTML = `<div class="center"><div class="hero">♫</div><h1 style="font-size:2.2rem">${esc(place)}</h1>
    ${finaleHtml()}
    <p>${me.score} xal</p>${teams}
    <ol style="text-align:left;font-weight:800">${view.top.map(p => `<li>${esc(p.name)} — ${p.score}</li>`).join('')}</ol>
    ${view.review?.length ? `<div class="review"><h3>Suallara bax, AI-dan soruş</h3>${view.review.map(q => `
      <button class="review-item" data-ask="${q.index}" data-text="${esc(q.text)}">
        <span>${q.correct ? '✓' : '✗'} ${esc(q.text)}</span><small>${esc(q.answer)} · soruş</small></button>`).join('')}</div>` : ''}
    <a class="btn ghost" href="/">Başqa oyuna qoşul</a></div>`;
}

/* Ad oyun başlamazdan əvvəl dəyişdirilə bilər. Reytinq ID ilə getdiyi üçün xallar itmir. */
function renameBox(view) {
  return `<details class="rename"><summary>Adın: <b>${esc(view.me.name)}</b> · dəyiş</summary>
    <form class="join-box" id="renameForm" style="margin-top:8px">
      <input class="field" id="newName" maxlength="20" value="${esc(view.me.name)}" aria-label="Yeni ad">
      <button class="btn">Saxla</button></form></details>`;
}

function bindRename() {
  const form = document.getElementById('renameForm');
  if (!form) return;
  form.onsubmit = event => {
    event.preventDefault();
    const name = document.getElementById('newName').value.trim();
    if (!name) return;
    localStorage.setItem('tralala:name', name);
    document.activeElement?.blur();
    socket?.send(JSON.stringify({ rename: name }));
  };
}

/* --- turnir: telefon duel olmayanda vəziyyəti göstərir --- */
/* Duel oynanarkən izləyici sualı və sonra düzgün cavabı görür. */
function watchHtml(watch) {
  if (!watch?.question) return '';
  const q = watch.question;
  const answer = watch.reveal?.answer;
  return `<div class="watch"><small class="muted">${watch.phase === 'reveal' ? 'Cavab' : 'İndiki sual'}</small>
    <div class="q-text" style="font-size:1.1rem">${esc(q.text)}</div>
    ${q.options && watch.phase !== 'reveal' ? `<div class="roster">${q.options.map(o => `<span>${esc(o)}</span>`).join('')}</div>` : ''}
    ${answer ? `<p>Düzgün cavab: <b>${esc(answer)}</b></p>` : ''}</div>`;
}

function duelLine(duel) {
  if (!duel) return '';
  return `<div class="verdict none" style="padding:14px"><small>${esc(duel.round)} · indi oynanılır</small>
    <h2 style="font-size:1.3rem">${esc(duel.a)} ${duel.score[0]} : ${duel.score[1]} ${esc(duel.b)}</h2></div>`;
}

function myStatus(view) {
  if (view.out) return `<div class="hero">♪</div><h2>Turnirdən çıxdın</h2><p class="muted">Yaxşı mübarizə idi! Qalan duelləri burada izləyə bilərsən.</p>`;
  if (view.opponent) return `<div class="hero">⚔</div><h2>Növbəti rəqibin</h2><h1 style="font-size:2.2rem">${esc(view.opponent)}</h1><p class="muted">Sıran gələndə sual burada açılacaq.</p>`;
  return `<div class="hero">⏳</div><h2>Hələ yarışdasan</h2><p class="muted">Rəqibin o biri duelin qalibi olacaq.</p>`;
}

const TOURNAMENT_SCREENS = {
  t_lobby(view) {
    app.innerHTML = `<div class="center"><h2 style="font-size:2rem">Turnirə yazıldın!</h2><div class="staff"></div>
      <p>Püşk atılanda rəqibini burada görəcəksən.</p><p class="muted">${view.entrants} iştirakçı</p>${renameBox(view)}</div>`;
    bindRename();
  },
  t_bracket(view) {
    app.innerHTML = `<div class="center">${myStatus(view)}</div>${bracketHtml(view.bracket, null, 'light')}`;
  },
  t_match(view) {
    app.innerHTML = `<div class="center" style="flex:none">${duelLine(view.duel)}${watchHtml(view.watch)}</div>
      ${myStatus(view).replace('class="hero"', 'class="hero" style="font-size:2rem"')}
      ${bracketHtml(view.bracket, null, 'light')}`;
  },
  t_result(view) {
    const r = view.result;
    const me = view.me.name;
    const head = r.winner === me ? `<div class="verdict good"><h2>${r.final ? 'Çempion sənsən!' : 'Qalib gəldin!'}</h2></div>`
      : r.loser === me ? `<div class="verdict bad"><h2>Uduzdun</h2><p>${esc(r.winner)} növbəti raunda keçdi.</p></div>`
      : `<div class="verdict none"><h2>${esc(r.winner)} qalib gəldi</h2></div>`;
    app.innerHTML = `<div class="center">${head}
      ${r.note === 'Texniki qələbə' ? `<p class="muted">${esc(r.note)}</p>` : `<p><b>${esc(r.a)} ${r.score[0]} : ${r.score[1]} ${esc(r.b)}</b></p>`}</div>`;
  },
  t_champion(view) {
    const me = view.champion === view.me.name;
    app.innerHTML = `<div class="center"><div class="hero">♛</div>
      <h1 style="font-size:2.2rem">${me ? 'Turnirin çempionu sənsən!' : esc(view.champion)}</h1>
      <p class="muted">${me ? 'Təbriklər!' : 'turnirin çempionudur'}</p>
      <a class="btn ghost" href="/">Başqa oyuna qoşul</a></div>${bracketHtml(view.bracket, null, 'light')}`;
  },
};

/* --- AI izahçısı: cavab açılandan sonra “niyə belədir?” --- */
const askPanel = {
  box: document.getElementById('ask'),
  log: document.getElementById('askLog'),
  index: null,
  history: {},
  open(index, text) {
    this.index = index;
    document.getElementById('askTitle').textContent = text;
    this.history[index] ??= [];
    this.draw();
    this.box.hidden = false;
    if (!this.history[index].length) this.send('Niyə belədir?');
  },
  close() { this.box.hidden = true; },
  note(show) { document.getElementById('askNote').hidden = !(show && !this.box.hidden); },
  draw() {
    const items = this.history[this.index] || [];
    this.log.innerHTML = items.map(item => `<div class="bubble me">${esc(item.q)}</div>
      ${item.pending ? '<div class="bubble ai typing">AI yazır…</div>'
        : `<div class="bubble ai${item.error ? ' err' : ''}">${esc(item.a || item.error)}</div>`}`).join('');
    this.log.scrollTop = this.log.scrollHeight;
    const busy = items.some(item => item.pending);
    document.getElementById('askSend').disabled = busy;
  },
  send(text) {
    if (!text || !socket || socket.readyState !== 1) return;
    this.history[this.index].push({ q: text, pending: true });
    this.draw();
    socket.send(JSON.stringify({ ask: { index: this.index, text } }));
  },
};

function askReply(reply) {
  const items = askPanel.history[reply.index] || [];
  const item = items.find(entry => entry.pending);
  if (!item) return;
  item.pending = false;
  item.a = reply.answer;
  item.error = reply.error;
  if (askPanel.index === reply.index) askPanel.draw();
}

document.addEventListener('click', event => {
  const button = event.target.closest('[data-ask]');
  if (button) askPanel.open(Number(button.dataset.ask), button.dataset.text);
});
document.getElementById('askClose').onclick = () => askPanel.close();
document.getElementById('askBack').onclick = () => askPanel.close();
document.getElementById('askForm').onsubmit = event => {
  event.preventDefault();
  const input = document.getElementById('askText');
  askPanel.send(input.value.trim());
  input.value = '';
};

if (pin) checkRoom(); else showPinForm();
