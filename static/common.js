const NOTES = ['Do', 'Re', 'Mi', 'Fa', 'Sol', 'La'];

const TYPE_LABELS = {
  choice: 'Tək seçim', multi: 'Çox seçim', truefalse: 'Doğru / Yanlış', text: 'Yazılı cavab',
  slider: 'Şkala', order: 'Ardıcıllıq', poll: 'Sorğu', cloud: 'Söz buludu',
};

/* Azərbaycanca sıra sayı (otaqda ən çox 30 nəfər olur): 1-ci, 3-cü, 6-cı, 9-cu, 10-cu. */
function ordinal(number) {
  const suffixes = ['cu', 'ci', 'ci', 'cü', 'cü', 'ci', 'cı', 'ci', 'ci', 'cu'];
  return `${number}-${number === 20 ? 'ci' : suffixes[number % 10]}`;
}

/* Sualın şəkli və ya videosu. Video səhnədə səsli oynayır, başqa yerlərdə səssiz önizləmədir. */
function mediaHtml(media, className, { play = false } = {}) {
  if (!media) return '';
  if (media.kind === 'video') {
    return play
      ? `<video class="${className}" src="${esc(media.url)}" playsinline autoplay preload="auto"></video>`
      : `<video class="${className}" src="${esc(media.url)}" playsinline muted controls preload="metadata"></video>`;
  }
  return `<img class="${className}" src="${esc(media.url)}" alt="">`;
}

/* Pley-off cədvəli. `highlight` növbəti duelin [raund, matç] yeridir. */
function bracketHtml(rounds, highlight, extraClass = '') {
  const side = (match, key) => {
    const name = match[key];
    if (!name) return `<div class="b-side empty">${match.status === 'bye' ? 'rəqibsiz' : '?'}</div>`;
    const won = match.winner === name;
    const lost = match.winner && !won;
    const score = match.status === 'done' && match.note !== 'Texniki qələbə' ? `<b>${match.score[key === 'a' ? 0 : 1]}</b>` : '';
    return `<div class="b-side ${won ? 'won' : ''} ${lost ? 'lost' : ''}"><span>${esc(name)}</span>${score}</div>`;
  };
  return `<div class="bracket ${extraClass}">${rounds.map((round, r) => `<div class="b-round">
    <h3>${esc(round.name)}</h3>
    <div class="b-matches">${round.matches.map((match, m) => {
      const next = highlight && highlight[0] === r && highlight[1] === m;
      return `<div class="b-match ${match.status}${next ? ' next' : ''}">${side(match, 'a')}${side(match, 'b')}</div>`;
    }).join('')}</div></div>`).join('')}</div>`;
}

/* Ekran keçidi: yeni ekran yumşaq görünür. Eyni ekran yenilənəndə (xal, siyahı) animasiya təkrarlanmır. */
function swapIn(box, screen) {
  if (box.dataset.screen === screen) return;
  box.dataset.screen = screen;
  box.classList.remove('swap-in');
  void box.offsetWidth;  // animasiyanı yenidən başlatmaq üçün
  box.classList.add('swap-in');
  // Sinif qalsa, eyni ekranın sonrakı yenilənmələri də (məs. lobbi siyahısı) animasiya ilə çəkilərdi.
  clearTimeout(box.swapTimer);
  box.swapTimer = setTimeout(() => box.classList.remove('swap-in'), 650);
}

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function toast(message, bad = false) {
  document.querySelector('.toast')?.remove();
  const box = document.createElement('div');
  box.className = 'toast' + (bad ? ' bad' : '');
  box.textContent = message;
  box.setAttribute('role', 'status');
  document.body.append(box);
  setTimeout(() => box.remove(), 4000);
}

async function api(path, options = {}) {
  const init = { ...options };
  if (init.json !== undefined) {
    init.method ??= 'POST';
    init.headers = { 'Content-Type': 'application/json' };
    init.body = JSON.stringify(init.json);
    delete init.json;
  }
  const response = await fetch(path, init);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || 'Xəta baş verdi');
  return data;
}

function wsUrl(path) {
  return `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}${path}`;
}

/* Vaxt zolağı: serverdən gələn qalan vaxta görə brauzerdə hamar azalır. */
function runTimebar(bar, remainingMs, totalMs, onTick) {
  const end = performance.now() + remainingMs;
  let frame;
  const step = () => {
    if (!bar.isConnected) return;  // ekran dəyişib: köhnə zolaq artıq yoxdur
    const left = Math.max(0, end - performance.now());
    bar.style.transform = `scaleX(${left / totalMs})`;
    onTick?.(left);
    if (left > 0 && bar.isConnected) frame = requestAnimationFrame(step);
  };
  step();
  return () => cancelAnimationFrame(frame);
}
