/* Turnir səhnəsi. Duel zamanı adi səhnənin (stage.js) ekranları işlənir, qalan vaxt cədvəl göstərilir. */
const duelBox = document.getElementById('duel');
const finishButton = document.getElementById('finish');
let tview = null;
let tKey = null;

finishButton.onclick = () => {
  if (tview?.phase !== 'match') return (location.href = '/admin#tournaments');
  if (confirm('Duel indiki hesabla bitirilsin?')) act('finish');
};

function tconnect() {
  socket = new WebSocket(wsUrl(`/ws/host/${pin}`));
  socket.onmessage = event => {
    const data = JSON.parse(event.data);
    if (data.keep) return toast(data.error, true);
    if (data.phase === 'closed') {
      closed = true;
      body.innerHTML = `<div class="center"><h1>Bu turnir otağı bağlanıb</h1><a class="btn primary" href="/admin#tournaments">Panelə qayıt</a></div>`;
      return;
    }
    tview = data;
    tdraw();
  };
  socket.onclose = () => { if (!closed) setTimeout(tconnect, 1000); };
}

function tdraw() {
  const phase = tview.phase;
  duelBox.hidden = phase !== 'match';
  if (phase === 'match') {
    if (tKey !== 'match') { drawnKey = null; body.onclick = null; }
    tKey = 'match';
    view = tview.match;
    duelHeader();
    draw();
    finishButton.hidden = false;
    finishButton.textContent = 'Dueli bitir';
    return;
  }
  view = null;
  scorePanel.refresh();
  titleBox.textContent = tview.title;
  finishButton.hidden = false;
  finishButton.textContent = 'Panelə qayıt';
  sound.lobby(phase === 'lobby' && sound.ctx?.state === 'running');
  ({ lobby: tLobby, bracket: tBracket, result: tResult, champion: tChampion })[phase]();
  swapIn(body, `t:${phase}`);
}

function duelHeader() {
  const d = tview.duel;
  duelBox.innerHTML = `<span class="d-name">${esc(d.a)}</span>
    <span class="d-mid"><small>${esc(d.round)}${d.sudden ? ' · əlavə sual' : ''}</small>
      <b>${d.score[0]} : ${d.score[1]}</b></span>
    <span class="d-name">${esc(d.b)}</span>`;
}

function seg(items) {
  return `<span class="seg">${items.map(([label, config, on]) =>
    `<button class="${on ? 'on' : ''}" data-config='${JSON.stringify(config)}'>${label}</button>`).join('')}</span>`;
}

function tLobby() {
  if (tKey !== 'lobby') {
    tKey = 'lobby';
    body.innerHTML = `<div class="lobby">
      <div class="joincard">
        <b>Turnirə yazıl</b>
        <img src="/api/rooms/${esc(pin)}/qr.svg" alt="Qoşulma QR kodu">
        <span class="muted">və ya kodu yaz</span>
        <div class="pin">${esc(pin)}</div>
        <div class="url">${esc(tview.join_url.split('?')[0])}</div>
      </div>
      <div class="lobby-side">
        <h2 id="count"></h2>
        <p class="s-note" style="text-align:left;margin:0">Püşkdən sonra hər kəs cüt-cüt qarşılaşır. Uduzan turnirdən çıxır, qalib növbəti raunda keçir.</p>
        <div class="chips" id="chips"></div>
        <div class="controls" id="controls"></div>
      </div></div>`;
    document.getElementById('chips').onclick = event => {
      const chip = event.target.closest('.chip');
      if (chip && confirm(`${chip.textContent} turnirdən çıxarılsın?`)) act('kick', { name: chip.dataset.name });
    };
    document.getElementById('controls').onclick = event => {
      const button = event.target.closest('[data-config]');
      if (button) act('config', JSON.parse(button.dataset.config));
      if (event.target.id === 'draw') act('draw');
    };
  }
  const n = tview.entrants.length;
  document.getElementById('count').textContent = n ? `${n} iştirakçı yazılıb` : 'İştirakçılar gözlənilir…';
  document.getElementById('chips').innerHTML = tview.entrants.map(e =>
    `<button class="chip${e.online ? '' : ' off'}" data-name="${esc(e.name)}" title="Çıxarmaq üçün klikləyin">${esc(e.name)}</button>`).join('');
  document.getElementById('controls').innerHTML =
    `<span>Hər duel:</span>` +
    seg(tview.lengths.filter(n => n <= tview.pool).map(len => [`${len} sual`, { per_match: len }, tview.per_match === len])) +
    seg([['Əl ilə', { auto: false }, !tview.auto], ['Avtomatik', { auto: true }, tview.auto]]) +
    (tview.ai_ready ? seg([['AI zarafatı', { jokes: true }, tview.jokes], ['Zarafatsız', { jokes: false }, !tview.jokes]]) : '') +
    `<button class="btn primary start" id="draw" ${n >= 2 ? '' : 'disabled'}>Püşk at</button>`;
}

function tBracket() {
  tKey = 'bracket';
  const next = tview.next;
  let spotlight = '<p class="s-note">Bütün duellər oynanılıb.</p>';
  if (next) {
    const m = tview.bracket[next[0]].matches[next[1]];
    const online = name => tview.entrants.find(e => e.name === name)?.online;
    const who = name => `<span class="vs-name ${online(name) ? '' : 'away'}">${esc(name)}${online(name) ? '' : '<small>qoşulmayıb</small>'}</span>`;
    spotlight = `<div class="spot">
      <small>Növbəti duel · ${esc(tview.next_round)}</small>
      <div class="vs">${who(m.a)}<b>vs</b>${who(m.b)}</div>
      <div class="row" style="justify-content:center">
        <button class="btn primary start" id="startMatch">Dueli başlat</button>
      </div>
      <div class="row muted" style="justify-content:center;font-size:.9rem">Rəqib gəlməyibsə:
        <button class="btn ghost small" data-walkover="${esc(m.a)}">${esc(m.a)} keçsin</button>
        <button class="btn ghost small" data-walkover="${esc(m.b)}">${esc(m.b)} keçsin</button></div>
    </div>`;
  }
  body.innerHTML = `${spotlight}${bracketHtml(tview.bracket, next)}
    <div class="controls">${seg([['Əl ilə', { auto: false }, !tview.auto], ['Avtomatik', { auto: true }, tview.auto]])}</div>`;
  body.onclick = event => {
    if (event.target.id === 'startMatch') act('start_match');
    const walk = event.target.closest('[data-walkover]');
    if (walk && confirm(`${walk.dataset.walkover} rəqibsiz növbəti raunda keçsin?`)) act('walkover', { winner: walk.dataset.walkover });
    const button = event.target.closest('[data-config]');
    if (button) act('config', JSON.parse(button.dataset.config));
  };
}

function tResult() {
  if (tKey === 'result') return;
  tKey = 'result';
  body.onclick = null;
  const r = tview.result;
  sound.reveal();
  body.innerHTML = `<div class="center">
    <p class="s-note">${esc(r.round)}</p>
    <div class="s-answer" style="font-size:clamp(2.4rem,6vw,4.4rem)">${esc(r.winner)}</div>
    <h2>${r.final ? 'turnirin qalibidir!' : 'növbəti raunda keçdi'}</h2>
    ${r.note === 'Texniki qələbə' ? '' : `<div class="board-row" style="justify-content:center;gap:30px">
      <span>${esc(r.a)}</span><span class="pos" style="width:auto">${r.score[0]} : ${r.score[1]}</span><span>${esc(r.b)}</span></div>`}
    ${r.note ? `<p class="s-note">${esc(r.note)}</p>` : ''}
    <p class="s-note">${esc(r.loser)} turnirdən çıxdı.</p>
    ${tview.auto ? '<span class="muted">Cədvələ qayıdılır…</span>' : '<button class="btn primary" id="tnext">Davam</button>'}
  </div>`;
  document.getElementById('tnext')?.addEventListener('click', () => act('next'));
}

function tChampion() {
  if (tKey === 'champion') return;
  tKey = 'champion';
  body.onclick = null;
  sound.fanfare();
  body.innerHTML = `<div class="center" style="flex:none">
      <p class="s-note">${esc(tview.title)} · çempion</p>
      <div class="s-answer" style="font-size:clamp(3rem,8vw,6rem)">♛ ${esc(tview.champion)}</div>
    </div>
    ${bracketHtml(tview.bracket, null)}
    <div class="s-foot"><span></span><a class="btn primary" href="/admin#tournaments">Panelə qayıt</a></div>`;
  for (let i = 0; i < 30; i++) {
    const note = document.createElement('span');
    note.className = 'fall';
    note.textContent = i % 3 ? '♪' : '♛';
    note.style.left = `${Math.random() * 100}vw`;
    note.style.color = ['#FFB627', '#F4483C', '#7FE0D6'][i % 3];
    note.style.animationDuration = `${3 + Math.random() * 3}s`;
    note.style.animationDelay = `${Math.random() * 2}s`;
    document.body.append(note);
    note.onanimationend = () => note.remove();
  }
}

if (pin) tconnect(); else location.href = '/admin#tournaments';
