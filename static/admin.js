const view = document.getElementById('view');
const tabs = document.getElementById('tabs');

function setTab(name) {
  tabs.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.tab === name));
}

function dateText(seconds) {
  const date = new Date(seconds * 1000);
  const two = number => String(number).padStart(2, '0');
  return `${two(date.getDate())}.${two(date.getMonth() + 1)}.${date.getFullYear()} ${two(date.getHours())}:${two(date.getMinutes())}`;
}

/* --- viktorinalar --- */
async function showQuizzes() {
  setTab('quizzes');
  const quizzes = await api('/api/quizzes');
  view.innerHTML = `
    <div class="row spread"><h1>Viktorinalar</h1>
      <div class="row"><button class="btn ghost" id="import" title="Hazır viktorina faylını (.json) əlavə edir">Fayldan əlavə et</button>
        <input type="file" id="importFile" accept=".json,application/json" hidden>
        <button class="btn" id="new">Yeni viktorina</button></div></div>
    ${quizzes.length ? '' : '<p class="empty">Hələ viktorina yoxdur. Birini yaradın.</p>'}
    <div class="cards">${quizzes.map(q => `<div class="card" data-id="${q.id}">
      <h3>${esc(q.title)}</h3>
      <span class="muted">${q.count} sual${q.description ? ' · ' + esc(q.description) : ''}</span>
      <div class="row" style="margin-top:auto">
        <button class="btn primary" data-act="play">Oyna</button>
        <button class="btn ghost small" data-act="edit">Redaktə</button>
        <a class="btn ghost small" href="/api/quizzes/${q.id}/export" download>JSON</a>
        <button class="btn danger small" data-act="delete">Sil</button>
      </div></div>`).join('')}</div>`;
  document.getElementById('new').onclick = () => { location.hash = 'edit/new'; };
  const importFile = document.getElementById('importFile');
  document.getElementById('import').onclick = () => importFile.click();
  importFile.onchange = async () => {
    const form = new FormData();
    form.append('file', importFile.files[0]);
    try {
      const result = await api('/api/quizzes/import', { method: 'POST', body: form });
      toast(`${result.ids.length} viktorina, ${result.count} sual əlavə olundu`);
      showQuizzes();
    } catch (error) { toast(error.message, true); }
    importFile.value = '';
  };
  view.querySelector('.cards').onclick = async event => {
    const button = event.target.closest('[data-act]');
    if (!button) return;
    const id = button.closest('.card').dataset.id;
    try {
      if (button.dataset.act === 'play') {
        const room = await api('/api/rooms', { json: { quiz_id: Number(id) } });
        location.href = `/stage?pin=${room.pin}`;
      } else if (button.dataset.act === 'edit') {
        location.hash = `edit/${id}`;
      } else if (confirm('Viktorina silinsin? Keçmiş oyunların nəticələri qalacaq.')) {
        await api(`/api/quizzes/${id}`, { method: 'DELETE' });
        showQuizzes();
      }
    } catch (error) { toast(error.message, true); }
  };
}

/* --- redaktor --- */
let draft = null;

function blankQuestion(type = 'choice') {
  return { type, text: '', time: 20, points: 1, media: null, explanation: '', options: ['', '', '', ''],
           correct: [], accepted: [''], min: 0, max: 100, step: 1, answer: 50, tolerance: 0 };
}

function completeQuestion(q) {
  const { image, ...rest } = q;
  return { ...blankQuestion(q.type), ...rest, media: q.media || image || null,
           options: q.options?.length ? q.options : ['', ''] };
}

async function showEditor(id) {
  setTab('quizzes');
  if (id === 'new') {
    draft = { title: '', description: '', questions: [blankQuestion()] };
  } else {
    const quiz = await api(`/api/quizzes/${id}`);
    draft = { ...quiz, questions: quiz.questions.map(completeQuestion) };
  }
  drawEditor();
}

function optionRows(q, i) {
  const usesCorrect = q.type === 'choice' || q.type === 'multi';
  const inputType = q.type === 'multi' ? 'checkbox' : 'radio';
  const hint = { choice: 'Düzgün variantı işarələyin', multi: 'Bütün düzgün variantları işarələyin',
                 order: 'Düzgün ardıcıllıqla yazın, oyunda qarışdırılacaq', poll: 'Düzgün cavab yoxdur' }[q.type];
  return `<div><span class="lbl">${hint}</span>
    ${q.options.map((text, o) => `<div class="optrow">
      ${usesCorrect ? `<input type="${inputType}" name="c${i}" aria-label="Düzgün cavab" data-f="correct" data-o="${o}" ${q.correct.includes(o) ? 'checked' : ''}>`
                    : q.type === 'order' ? `<b>${o + 1}.</b>` : ''}
      <input class="field" maxlength="120" aria-label="Variant ${o + 1}" data-f="option" data-o="${o}" value="${esc(text)}">
      ${q.options.length > 2 ? `<button type="button" class="btn ghost small" data-act="delopt" data-o="${o}" aria-label="Variantı sil">×</button>` : ''}
    </div>`).join('')}
    ${q.options.length < 6 ? `<button type="button" class="btn ghost small" data-act="addopt" style="margin-top:8px">Variant əlavə et</button>` : ''}</div>`;
}

function typeFields(q, i) {
  if (['choice', 'multi', 'order', 'poll'].includes(q.type)) return optionRows(q, i);
  if (q.type === 'truefalse') {
    return `<div class="row"><span class="lbl" style="margin:0">Düzgün cavab:</span>
      <label><input type="radio" name="c${i}" data-f="correct" data-o="0" ${q.correct[0] === 0 ? 'checked' : ''}> Doğru</label>
      <label><input type="radio" name="c${i}" data-f="correct" data-o="1" ${q.correct[0] === 1 ? 'checked' : ''}> Yanlış</label></div>`;
  }
  if (q.type === 'text') {
    return `<div><label class="lbl">Qəbul olunan cavablar (vergüllə). Hərf fərqi və kiçik yazı səhvi bağışlanır.</label>
      <input class="field" data-f="accepted" value="${esc(q.accepted.join(', '))}"></div>`;
  }
  if (q.type === 'slider') {
    const number = (field, label) => `<div><label class="lbl">${label}</label>
      <input class="field" type="number" step="any" data-f="${field}" value="${q[field]}"></div>`;
    return `<div class="grid2">${number('min', 'Minimum')}${number('max', 'Maksimum')}${number('step', 'Addım')}
      ${number('answer', 'Düzgün cavab')}${number('tolerance', 'Dözüm (±)')}</div>`;
  }
  return '<p class="muted">Oyunçular sərbəst söz yazır, nəticə söz buludu kimi göstərilir.</p>';
}

function questionCard(q, i) {
  const unscored = q.type === 'poll' || q.type === 'cloud';
  return `<div class="card qcard" data-q="${i}">
    <div class="qhead">
      <span class="qnum">${i + 1}</span>
      <select class="field" style="width:auto" data-f="type" aria-label="Sual tipi">
        ${Object.entries(TYPE_LABELS).map(([k, v]) => `<option value="${k}" ${k === q.type ? 'selected' : ''}>${v}</option>`).join('')}
      </select>
      <span class="grow"></span>
      <button type="button" class="btn ghost small" data-act="up" ${i ? '' : 'disabled'} aria-label="Yuxarı">↑</button>
      <button type="button" class="btn ghost small" data-act="down" ${i < draft.questions.length - 1 ? '' : 'disabled'} aria-label="Aşağı">↓</button>
      <button type="button" class="btn danger small" data-act="delq">Sil</button>
    </div>
    <textarea class="field" rows="2" maxlength="300" placeholder="Sualın mətni" aria-label="Sualın mətni" data-f="text">${esc(q.text)}</textarea>
    ${typeFields(q, i)}
    <div class="grid2">
      <div><label class="lbl">Vaxt (saniyə)</label>
        <input class="field" type="number" min="5" max="120" data-f="time" value="${q.time}"></div>
      ${unscored ? '' : `<div><label class="lbl">Xal</label>
        <select class="field" data-f="points">
          <option value="0" ${q.points === 0 ? 'selected' : ''}>Xalsız</option>
          <option value="1" ${q.points === 1 ? 'selected' : ''}>Standart</option>
          <option value="2" ${q.points === 2 ? 'selected' : ''}>2× xal</option>
        </select></div>`}
      <div><label class="lbl">Şəkil və ya video (sualdan əvvəl göstərilir)</label>
        <input class="field" type="file" accept="image/png,image/jpeg,image/gif,image/webp,video/mp4,video/webm" data-f="media"></div>
    </div>
    ${q.media ? `<div class="row">${mediaHtml({ kind: /\.(mp4|webm)$/.test(q.media) ? 'video' : 'image', url: q.media }, 'thumb')}
      <button type="button" class="btn ghost small" data-act="noimg">Sil</button></div>` : ''}
    ${unscored ? '' : `<div><label class="lbl">İzah (cavabdan sonra göstərilir)</label>
      <input class="field" maxlength="300" data-f="explanation" value="${esc(q.explanation)}"></div>`}
  </div>`;
}

function drawEditor() {
  view.innerHTML = `
    <div class="row spread"><h1>${draft.id ? 'Viktorinanı redaktə et' : 'Yeni viktorina'}</h1>
      <a class="btn ghost small" href="#quizzes">Geri</a></div>
    <div class="card" style="margin-top:14px">
      <div><label class="lbl" for="qTitle">Ad</label>
        <input class="field" id="qTitle" maxlength="80" value="${esc(draft.title)}"></div>
      <div><label class="lbl" for="qDesc">Qısa təsvir</label>
        <input class="field" id="qDesc" maxlength="200" value="${esc(draft.description || '')}"></div>
    </div>
    <div id="questions">${draft.questions.map(questionCard).join('')}</div>
    <div class="row spread sticky">
      <button class="btn ghost" id="addq">Sual əlavə et</button>
      <button class="btn primary" id="save">Saxla</button>
    </div>`;
  document.getElementById('qTitle').oninput = event => { draft.title = event.target.value; };
  document.getElementById('qDesc').oninput = event => { draft.description = event.target.value; };
  document.getElementById('addq').onclick = () => { draft.questions.push(blankQuestion()); drawEditor(); };
  document.getElementById('save').onclick = saveDraft;
  const list = document.getElementById('questions');
  list.oninput = onFieldInput;
  list.onchange = onFieldChange;
  list.onclick = onEditorClick;
}

function onFieldInput(event) {
  const f = event.target.dataset.f;
  if (!f || ['type', 'correct', 'media'].includes(f)) return;
  const q = draft.questions[Number(event.target.closest('[data-q]').dataset.q)];
  const value = event.target.value;
  if (f === 'option') q.options[Number(event.target.dataset.o)] = value;
  else if (f === 'accepted') q.accepted = value.split(',').map(s => s.trim()).filter(Boolean);
  else if (['time', 'points', 'min', 'max', 'step', 'answer', 'tolerance'].includes(f)) q[f] = Number(value);
  else q[f] = value;
}

async function onFieldChange(event) {
  const f = event.target.dataset.f;
  if (!f) return;
  const q = draft.questions[Number(event.target.closest('[data-q]').dataset.q)];
  if (f === 'type') {
    q.type = event.target.value;
    q.correct = [];
    if (q.options.length < 2) q.options = ['', ''];
    if ((q.type === 'multi' || q.type === 'order') && q.options.length < 3) q.options.push('');
    if (q.type === 'poll' || q.type === 'cloud') q.points = 0;
    else if (q.points === 0) q.points = 1;
    drawEditor();
  } else if (f === 'correct') {
    const o = Number(event.target.dataset.o);
    if (q.type === 'multi') {
      q.correct = event.target.checked ? [...q.correct, o] : q.correct.filter(c => c !== o);
    } else {
      q.correct = [o];
    }
  } else if (f === 'media' && event.target.files[0]) {
    const file = event.target.files[0];
    const form = new FormData();
    form.append('file', file);
    event.target.disabled = true;
    toast(file.size > 5e6 ? 'Yüklənir… böyük video bir az çəkə bilər' : 'Yüklənir…');
    try {
      q.media = (await api('/api/upload', { method: 'POST', body: form })).url;
      toast('Yükləndi');
      drawEditor();
    } catch (error) {
      toast(error.message, true);
      event.target.disabled = false;
    }
  }
}

function onEditorClick(event) {
  const button = event.target.closest('[data-act]');
  if (!button) return;
  const i = Number(button.closest('[data-q]').dataset.q);
  const q = draft.questions[i];
  const list = draft.questions;
  const act = button.dataset.act;
  if (act === 'delq') list.splice(i, 1);
  if (act === 'up') [list[i - 1], list[i]] = [list[i], list[i - 1]];
  if (act === 'down') [list[i + 1], list[i]] = [list[i], list[i + 1]];
  if (act === 'addopt') q.options.push('');
  if (act === 'noimg') q.media = null;
  if (act === 'delopt') {
    const o = Number(button.dataset.o);
    q.options.splice(o, 1);
    q.correct = q.correct.filter(c => c !== o).map(c => (c > o ? c - 1 : c));
  }
  if (!list.length) list.push(blankQuestion());
  drawEditor();
}

async function saveDraft() {
  try {
    const body = { title: draft.title, description: draft.description, questions: draft.questions };
    if (draft.id) await api(`/api/quizzes/${draft.id}`, { method: 'PUT', json: body });
    else await api('/api/quizzes', { json: body });
    draft = null;
    toast('Saxlanıldı');
    location.hash = 'quizzes';
  } catch (error) { toast(error.message, true); }
}

/* --- turnirlər --- */
const PHASE_LABELS = { lobby: 'Qeydiyyat', bracket: 'Davam edir', match: 'Davam edir', result: 'Davam edir', champion: 'Bitib' };

async function showTournaments() {
  setTab('tournaments');
  const [list, quizzes] = await Promise.all([api('/api/tournaments'), api('/api/quizzes')]);
  view.innerHTML = `
    <div class="row spread"><h1>Turnirlər</h1></div>
    <p class="muted">İştirakçılar cüt-cüt qarşılaşır: qalib növbəti raunda keçir, uduzan çıxır. Duellər səhnədə bir-bir oynanılır.</p>
    <form class="card" id="newTournament" style="margin-top:14px">
      <h3>Yeni turnir</h3>
      <div class="grid2">
        <div><label class="lbl" for="tTitle">Ad</label><input class="field" id="tTitle" maxlength="80" placeholder="Məs: Payız kuboku" required></div>
        <div><label class="lbl" for="tQuiz">Suallar hansı viktorinadan</label>
          <select class="field" id="tQuiz">${quizzes.map(q => `<option value="${q.id}">${esc(q.title)} (${q.count})</option>`).join('')}</select></div>
        <div><label class="lbl" for="tLen">Hər dueldə sual</label>
          <select class="field" id="tLen"><option value="3">3</option><option value="5" selected>5</option><option value="7">7</option></select></div>
      </div>
      <div class="row"><button class="btn primary">Yarat və səhnəni aç</button>
        <span class="muted">Sorğu və söz buludu sualları duellərə düşmür.</span></div>
    </form>
    ${list.length ? `<table style="margin-top:14px"><thead><tr><th>Turnir</th><th>Vəziyyət</th><th class="num">İştirakçı</th>
      <th>Çempion</th><th></th></tr></thead><tbody>
      ${list.map(t => `<tr data-id="${t.id}"><td><a href="#tournaments/${t.id}"><b>${esc(t.title)}</b></a></td>
        <td>${PHASE_LABELS[t.phase] || t.phase}${t.pin ? ' · canlı' : ''}</td><td class="num">${t.entrants}</td>
        <td>${t.champion ? `<b>♛ ${esc(t.champion)}</b>` : '—'}</td>
        <td class="row" style="justify-content:flex-end">
          ${t.phase === 'champion' ? '' : `<button class="btn teal small" data-act="open">Səhnəni aç</button>`}
          <button class="btn danger small" data-act="delete">Sil</button></td></tr>`).join('')}
      </tbody></table>` : ''}`;
  document.getElementById('newTournament').onsubmit = async event => {
    event.preventDefault();
    try {
      const created = await api('/api/tournaments', { json: {
        title: document.getElementById('tTitle').value, quiz_id: Number(document.getElementById('tQuiz').value),
        per_match: Number(document.getElementById('tLen').value) } });
      location.href = `/tournament?pin=${created.pin}`;
    } catch (error) { toast(error.message, true); }
  };
  view.querySelector('tbody')?.addEventListener('click', async event => {
    const button = event.target.closest('[data-act]');
    if (!button) return;
    const id = button.closest('[data-id]').dataset.id;
    try {
      if (button.dataset.act === 'open') {
        location.href = `/tournament?pin=${(await api(`/api/tournaments/${id}/open`, { method: 'POST' })).pin}`;
      } else if (confirm('Turnir silinsin? Cədvəl və çempion qeydi itəcək.')) {
        await api(`/api/tournaments/${id}`, { method: 'DELETE' });
        showTournaments();
      }
    } catch (error) { toast(error.message, true); }
  });
}

async function showTournament(id) {
  setTab('tournaments');
  const t = await api(`/api/tournaments/${id}`);
  view.innerHTML = `
    <div class="row spread"><div><h1>${esc(t.title)}</h1>
      <span class="muted">${PHASE_LABELS[t.phase]} · ${t.entrants.length} iştirakçı</span></div>
      <a class="btn ghost small" href="#tournaments">Geri</a></div>
    ${t.champion ? `<div class="champion"><div><span>Çempion</span><br><strong>♛ ${esc(t.champion)}</strong></div></div>` : ''}
    ${t.bracket.length ? bracketHtml(t.bracket, null, 'light')
                       : '<p class="empty">Püşk hələ atılmayıb.</p>'}`;
}

/* --- reytinq --- */
let boardScope = 'week';

async function showBoard() {
  setTab('board');
  const data = await api('/api/leaderboard');
  const rows = data[boardScope];
  const leader = data.week[0];
  view.innerHTML = `
    <div class="row spread"><h1>Reytinq</h1>
      <span class="seg" style="background:var(--line)">
        <button class="${boardScope === 'week' ? 'on' : ''}" data-scope="week">Bu həftə</button>
        <button class="${boardScope === 'all' ? 'on' : ''}" data-scope="all">Bütün zamanlar</button>
      </span></div>
    ${leader ? `<div class="champion"><div><span>Həftənin lideri</span><br><strong>${esc(leader.name)}</strong></div>
      <div>${leader.score} xal · ${leader.wins} qələbə</div></div>` : ''}
    ${rows.length ? `<table><thead><tr><th>#</th><th>Ad</th><th class="num">Xal</th><th class="num">Oyun</th>
      <th class="num">Qələbə</th><th class="num">Düzgünlük</th><th class="num">Orta sürət</th><th>Nişanlar</th></tr></thead><tbody>
      ${rows.map(r => `<tr><td>${r.rank}</td><td><b>${esc(r.name)}</b></td><td class="num">${r.score}</td>
        <td class="num">${r.games}</td><td class="num">${r.wins}</td><td class="num">${r.accuracy}%</td>
        <td class="num">${(r.avg_ms / 1000).toFixed(1)} san</td>
        <td>${r.badges.map(b => `<span class="badge">${esc(b.label)}</span>`).join('')}</td></tr>`).join('')}
      </tbody></table>` : '<p class="empty">Bu dövrdə hələ oyun olmayıb.</p>'}`;
  view.querySelectorAll('[data-scope]').forEach(button => {
    button.onclick = () => { boardScope = button.dataset.scope; showBoard(); };
  });
}

/* --- hesabatlar --- */
async function showGames() {
  setTab('games');
  const games = await api('/api/games');
  view.innerHTML = `<h1>Hesabatlar</h1>
    ${games.length ? `<table style="margin-top:14px"><thead><tr><th>Oyun</th><th>Tarix</th><th class="num">Oyunçu</th>
      <th class="num">Sual</th><th>Qalib</th></tr></thead><tbody>
      ${games.map(g => `<tr><td><a href="#games/${g.id}"><b>${esc(g.title)}</b></a></td><td>${dateText(g.ended_at)}</td>
        <td class="num">${g.player_count}</td><td class="num">${g.played}</td><td>${esc(g.winner)}</td></tr>`).join('')}
      </tbody></table>` : '<p class="empty">Bitmiş oyun yoxdur.</p>'}`;
}

async function showGame(id) {
  setTab('games');
  const game = await api(`/api/games/${id}`);
  const scored = game.questions.filter(q => !['poll', 'cloud'].includes(q.type));
  const hardest = [...scored].sort((a, b) => a.accuracy - b.accuracy)[0];
  view.innerHTML = `
    <div class="row spread"><div><h1>${esc(game.title)}</h1>
      <span class="muted">${dateText(game.ended_at)} · ${game.player_count} oyunçu</span></div>
      <div class="row"><a class="btn ghost small" href="#games">Geri</a>
        <a class="btn teal small" href="/api/games/${game.id}/csv">Excel üçün yüklə</a>
        <button class="btn danger small" id="del">Sil</button></div></div>
    ${hardest ? `<div class="champion"><div><span>Ən çətin sual</span><br><b>${esc(hardest.text)}</b></div>
      <strong>${hardest.accuracy}%</strong></div>` : ''}
    ${game.adjustments?.length ? `<div class="section"><h2>Aparıcının xal düzəlişləri</h2><table style="margin-top:8px">
      <thead><tr><th>Oyunçu</th><th class="num">Düzəliş</th><th>Nə vaxt</th><th>Səbəb</th></tr></thead><tbody>
      ${game.adjustments.map(a => `<tr><td><b>${esc(a.name)}</b></td>
        <td class="num" style="color:${a.delta < 0 ? 'var(--bad)' : 'var(--good)'}">${a.delta > 0 ? '+' : ''}${a.delta}</td>
        <td>${a.question ? `${a.question}-ci sualda` : '—'}</td><td>${esc(a.reason) || '—'}</td></tr>`).join('')}
      </tbody></table></div>` : ''}
    ${game.teams.length ? `<div class="section"><h2>Komandalar</h2><table style="margin-top:8px"><tbody>
      ${game.teams.map(t => `<tr><td><b>${esc(t.name)}</b></td><td>${t.members} nəfər</td><td class="num">${t.score}</td></tr>`).join('')}</tbody></table></div>` : ''}
    <div class="section"><h2>Oyunçular</h2><table style="margin-top:8px"><thead><tr><th>#</th><th>Ad</th>
      ${game.teams.length ? '<th>Komanda</th>' : ''}<th class="num">Xal</th><th class="num">Düz</th><th class="num">Ən uzun seriya</th></tr></thead><tbody>
      ${game.players.map(p => `<tr><td>${p.rank}</td><td><b>${esc(p.name)}</b></td>${game.teams.length ? `<td>${esc(p.team)}</td>` : ''}
        <td class="num">${p.score}</td><td class="num">${p.correct} / ${p.scored_total}</td><td class="num">${p.best_streak}</td></tr>`).join('')}
      </tbody></table></div>
    <div class="section"><h2>Suallar</h2><table style="margin-top:8px"><thead><tr><th>#</th><th>Sual</th><th>Cavab</th>
      <th>Düzgünlük</th><th class="num">Orta vaxt</th></tr></thead><tbody>
      ${game.questions.map(q => {
        const open = ['poll', 'cloud'].includes(q.type);
        return `<tr><td>${q.index + 1}</td><td>${esc(q.text)}</td><td>${esc(q.answer) || '—'}</td>
          <td>${open ? `${q.answered} cavab` : `<div class="meter ${q.accuracy < 40 ? 'low' : ''}"><b style="width:${q.accuracy}%"></b></div> ${q.accuracy}%`}</td>
          <td class="num">${(q.avg_ms / 1000).toFixed(1)} san</td></tr>`;
      }).join('')}</tbody></table></div>`;
  document.getElementById('del').onclick = async () => {
    if (!confirm('Bu oyun silinsin? Xalları reytinqdən də çıxacaq.')) return;
    await api(`/api/games/${id}`, { method: 'DELETE' });
    location.hash = 'games';
  };
}

/* --- yönləndirmə --- */
tabs.onclick = event => {
  const tab = event.target.dataset.tab;
  if (tab) location.hash = tab;
};

async function route() {
  const [page, id] = location.hash.slice(1).split('/');
  view.classList.add('leaving');  // köhnə bölmə məlumat yüklənənə qədər solur
  try {
    if (page === 'edit') await showEditor(id);
    else if (page === 'board') await showBoard();
    else if (page === 'tournaments') await (id ? showTournament(id) : showTournaments());
    else if (page === 'games') await (id ? showGame(id) : showGames());
    else await showQuizzes();
  } catch (error) {
    view.innerHTML = `<p class="empty">${esc(error.message)}</p>`;
  }
  view.classList.remove('leaving');
  view.dataset.screen = '';
  swapIn(view, location.hash);
}

window.addEventListener('hashchange', route);
route();
