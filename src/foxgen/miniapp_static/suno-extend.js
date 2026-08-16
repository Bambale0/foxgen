const root = document.getElementById('app');
const tg = window.Telegram?.WebApp ?? null;
const EXTEND_SLUG = 'suno-v5-extend';

let token = null;
let sources = [];
let selected = null;
let bootstrap = null;
let busy = false;

function esc(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

async function auth(force = false) {
  if (token && !force) return token;
  if (!tg?.initData) throw new Error('Откройте Happy Fox внутри Telegram.');
  const response = await fetch('/v1/miniapp/auth', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ init_data: tg.initData }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || !data?.access_token) {
    throw new Error(data?.detail || 'Не удалось подтвердить Telegram-профиль.');
  }
  token = data.access_token;
  return token;
}

async function api(path, options = {}, retry = true) {
  const bearer = await auth(false);
  const headers = new Headers(options.headers ?? {});
  headers.set('Authorization', `Bearer ${bearer}`);
  const response = await fetch(`/v1/miniapp${path}`, { ...options, headers });
  const data = await response.json().catch(() => ({}));
  if (response.status === 401 && retry) {
    await auth(true);
    return api(path, options, false);
  }
  if (!response.ok) {
    throw new Error(data?.detail || data?.message || `HTTP ${response.status}`);
  }
  return data;
}

function price() {
  const models = Array.isArray(bootstrap?.models) ? bootstrap.models : [];
  return models.find((item) => item?.slug === EXTEND_SLUG)?.price ?? null;
}

function availableBalance() {
  return Number(bootstrap?.balance?.available_units ?? 0);
}

function panel() {
  let element = root?.querySelector('[data-suno-extend-panel]');
  if (element) return element;
  const musicList = root?.querySelector('[data-suno-product-list]');
  if (!musicList) return null;
  element = document.createElement('section');
  element.className = 'section complete-stars-panel';
  element.dataset.sunoExtendPanel = '1';
  element.hidden = true;
  musicList.insertAdjacentElement('afterend', element);
  return element;
}

function ensureLauncher() {
  if (!root || root.querySelector('[data-suno-extend-open]')) return;
  const musicList = root.querySelector('[data-suno-product-list]');
  if (!musicList) return;
  root.querySelector('[data-model="suno-v5-extend"]')?.remove();
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'model-row grunge-lite';
  button.dataset.sunoExtendOpen = '1';
  button.innerHTML = `
    <span class="model-glyph">↗</span>
    <div>
      <strong>Продолжить свой трек</strong>
      <small>Suno V5 Extend · только сохранённые варианты</small>
      <p>Выберите свой трек, режим продолжения и точку перехода</p>
    </div>
    <span>›</span>
  `;
  musicList.append(button);
  panel();
}

function status(message, kind = '') {
  const element = panel();
  if (!element) return;
  element.hidden = false;
  element.className = `section complete-stars-panel ${kind}`.trim();
  element.innerHTML = `<p>${esc(message)}</p>`;
}

async function loadSources() {
  if (busy) return;
  busy = true;
  status('Загружаю ваши сохранённые Suno-треки…');
  try {
    const [sourceData, bootstrapData] = await Promise.all([
      api('/music/suno/sources'),
      api('/bootstrap'),
    ]);
    sources = Array.isArray(sourceData?.items) ? sourceData.items : [];
    bootstrap = bootstrapData;
    if (!sources.length) {
      status('Сначала создайте Suno-трек. Продолжать можно только свои завершённые и сохранённые варианты.', 'warning');
      return;
    }
    renderSources();
  } catch (error) {
    status(error?.message ?? error, 'error');
  } finally {
    busy = false;
  }
}

function renderSources() {
  const element = panel();
  if (!element) return;
  element.hidden = false;
  const quote = price();
  element.innerHTML = `
    <div class="complete-stars-head">
      <strong>Продолжить свой Suno-трек</strong>
      <small>${quote ? `Цена Extend: ${Number(quote.amount_units).toLocaleString('ru-RU')} CREDIT` : 'Цена Extend ещё не опубликована'}</small>
    </div>
    <div class="complete-stars-grid">
      ${sources.map((item, index) => `
        <div class="model-row" data-suno-source-row="${index}">
          <div style="min-width:0;flex:1">
            <strong>${esc(item.title || 'Suno track')}</strong>
            <small>${item.duration_seconds ? `${Number(item.duration_seconds).toFixed(1)} сек` : 'длительность неизвестна'}</small>
            <audio controls preload="none" src="${esc(item.preview_url)}" style="width:100%;margin-top:8px"></audio>
            <button type="button" data-suno-extend-source="${index}" style="margin-top:8px">Продолжить этот вариант</button>
          </div>
        </div>
      `).join('')}
    </div>
  `;
}

function renderModes(index) {
  selected = sources[index] ?? null;
  if (!selected) {
    status('Источник устарел. Обновите список.', 'error');
    return;
  }
  const element = panel();
  if (!element) return;
  const duration = selected.duration_seconds
    ? ` · ${Number(selected.duration_seconds).toFixed(1)} сек`
    : '';
  element.innerHTML = `
    <div class="complete-stars-head">
      <strong>${esc(selected.title || 'Suno track')}</strong>
      <small>${esc(selected.audio_id)}${duration}</small>
    </div>
    <div class="complete-stars-grid">
      <button type="button" data-suno-extend-mode="inherit">
        <strong>Продолжить как есть</strong>
        <small>Наследовать параметры исходного трека</small>
      </button>
      <button type="button" data-suno-extend-mode="custom">
        <strong>Кастомное продолжение</strong>
        <small>Новый prompt, стиль, название и точка продолжения</small>
      </button>
    </div>
    <button type="button" data-suno-extend-back>← К списку треков</button>
  `;
}

function quoteBlock() {
  const quote = price();
  if (!quote) {
    return '<p>⚠️ Цена Suno V5 Extend не опубликована. Запуск заблокирован.</p>';
  }
  const amount = Number(quote.amount_units);
  const enough = availableBalance() >= amount;
  return `
    <p>Стоимость: <strong>${amount.toLocaleString('ru-RU')} ${esc(quote.currency || 'CREDIT')}</strong><br>
    ${enough ? `Доступно: ${availableBalance().toLocaleString('ru-RU')} CREDIT` : `⚠️ Недостаточно средств: ${availableBalance().toLocaleString('ru-RU')} CREDIT`}</p>
  `;
}

function renderInherited() {
  const element = panel();
  if (!element || !selected) return;
  const quote = price();
  const canSubmit = quote && availableBalance() >= Number(quote.amount_units);
  element.innerHTML = `
    <div class="complete-stars-head">
      <strong>Продолжить как есть</strong>
      <small>${esc(selected.title)}</small>
    </div>
    ${quoteBlock()}
    <button type="button" data-suno-extend-submit="inherit" ${canSubmit ? '' : 'disabled'}>Запустить Extend</button>
    <button type="button" data-suno-extend-source-back>← Режим продолжения</button>
  `;
}

function renderCustom() {
  const element = panel();
  if (!element || !selected) return;
  const max = selected.duration_seconds ? Number(selected.duration_seconds) : '';
  const quote = price();
  const canSubmit = quote && availableBalance() >= Number(quote.amount_units);
  element.innerHTML = `
    <div class="complete-stars-head">
      <strong>Кастомное продолжение</strong>
      <small>${esc(selected.title)}</small>
    </div>
    <label>Prompt / текст продолжения
      <textarea data-suno-extend-prompt maxlength="5000" rows="4" required></textarea>
    </label>
    <label>Стиль
      <input data-suno-extend-style maxlength="1000" required>
    </label>
    <label>Название
      <input data-suno-extend-title maxlength="100" required>
    </label>
    <label>Продолжить с секунды
      <input data-suno-extend-at type="number" min="0.01" ${max ? `max="${max}"` : ''} step="0.1" required>
    </label>
    ${quoteBlock()}
    <button type="button" data-suno-extend-submit="custom" ${canSubmit ? '' : 'disabled'}>Запустить Extend</button>
    <button type="button" data-suno-extend-source-back>← Режим продолжения</button>
  `;
}

function keyForSelected() {
  const suffix = selected ? `${selected.generation_id}:${selected.audio_id}` : 'unknown';
  const storageKey = `foxgen:suno-extend:${suffix}`;
  try {
    let value = sessionStorage.getItem(storageKey);
    if (!value) {
      value = `suno-extend:${crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`}`;
      sessionStorage.setItem(storageKey, value);
    }
    return { storageKey, value };
  } catch {
    return { storageKey: null, value: `suno-extend:${Date.now()}-${Math.random()}` };
  }
}

function clearKey(storageKey) {
  if (!storageKey) return;
  try {
    sessionStorage.removeItem(storageKey);
  } catch {
    // Backend idempotency remains authoritative.
  }
}

async function submit(mode) {
  if (busy || !selected) return;
  const quote = price();
  if (!quote || availableBalance() < Number(quote.amount_units)) {
    status('Цена недоступна или на балансе недостаточно CREDIT.', 'error');
    return;
  }
  const body = {
    source_generation_id: selected.generation_id,
    audio_id: selected.audio_id,
    default_param_flag: mode === 'custom',
  };
  if (mode === 'custom') {
    const prompt = root.querySelector('[data-suno-extend-prompt]')?.value?.trim() ?? '';
    const style = root.querySelector('[data-suno-extend-style]')?.value?.trim() ?? '';
    const title = root.querySelector('[data-suno-extend-title]')?.value?.trim() ?? '';
    const rawAt = root.querySelector('[data-suno-extend-at]')?.value ?? '';
    const continueAt = Number(rawAt);
    if (!prompt || !style || !title || !Number.isFinite(continueAt) || continueAt <= 0) {
      status('Заполните prompt, стиль, название и корректную точку продолжения.', 'error');
      return;
    }
    if (selected.duration_seconds && continueAt >= Number(selected.duration_seconds)) {
      status('Точка продолжения должна быть раньше конца исходного трека.', 'error');
      return;
    }
    Object.assign(body, {
      prompt,
      style,
      title,
      continue_at: continueAt,
    });
  }

  const pending = keyForSelected();
  busy = true;
  status('Ставлю продолжение в очередь…');
  try {
    const result = await api('/music/suno/extend', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': pending.value,
      },
      body: JSON.stringify(body),
    });
    clearKey(pending.storageKey);
    status(`✅ Продолжение поставлено в очередь. ID: ${result.generation_id}`, 'success');
    window.setTimeout(() => window.location.reload(), 1400);
  } catch (error) {
    status(error?.message ?? error, 'error');
  } finally {
    busy = false;
  }
}

function enhance() {
  root?.querySelector('[data-model="suno-v5-extend"]')?.remove();
  ensureLauncher();
}

root?.addEventListener('click', (event) => {
  const target = event.target;
  if (!(target instanceof Element)) return;

  if (target.closest('[data-suno-extend-open]')) {
    event.preventDefault();
    void loadSources();
    return;
  }
  const source = target.closest('[data-suno-extend-source]');
  if (source instanceof HTMLButtonElement) {
    event.preventDefault();
    renderModes(Number(source.dataset.sunoExtendSource));
    return;
  }
  const mode = target.closest('[data-suno-extend-mode]');
  if (mode instanceof HTMLButtonElement) {
    event.preventDefault();
    if (mode.dataset.sunoExtendMode === 'custom') renderCustom();
    else renderInherited();
    return;
  }
  if (target.closest('[data-suno-extend-back]')) {
    event.preventDefault();
    renderSources();
    return;
  }
  if (target.closest('[data-suno-extend-source-back]')) {
    event.preventDefault();
    const index = sources.indexOf(selected);
    renderModes(index >= 0 ? index : 0);
    return;
  }
  const submitButton = target.closest('[data-suno-extend-submit]');
  if (submitButton instanceof HTMLButtonElement && !submitButton.disabled) {
    event.preventDefault();
    void submit(submitButton.dataset.sunoExtendSubmit || 'inherit');
  }
});

const observer = new MutationObserver(() => queueMicrotask(enhance));
if (root) {
  observer.observe(root, { childList: true, subtree: true });
  enhance();
}
