const root = document.getElementById('app');
const tg = window.Telegram?.WebApp ?? null;
const MODEL = 'suno-v5-upload-cover';

let token = null;
let busy = false;
let uploadedKey = null;
let submittedKey = null;

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
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({init_data: tg.initData}),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || !data?.access_token) throw new Error(data?.detail || 'Не удалось подтвердить Telegram-профиль.');
  token = data.access_token;
  return token;
}

async function api(path, options = {}, retry = true) {
  const accessToken = await auth(false);
  const headers = new Headers(options.headers ?? {});
  headers.set('Authorization', `Bearer ${accessToken}`);
  const response = await fetch(`/v1/miniapp${path}`, {...options, headers});
  const data = await response.json().catch(() => ({}));
  if (response.status === 401 && retry) {
    await auth(true);
    return api(path, options, false);
  }
  if (!response.ok) throw new Error(data?.detail || data?.message || `HTTP ${response.status}`);
  return data;
}

function storagePath(key) {
  return String(key).split('/').map(encodeURIComponent).join('/');
}

async function cleanupUploaded() {
  if (!uploadedKey || uploadedKey === submittedKey) return;
  const key = uploadedKey;
  uploadedKey = null;
  try {
    await api(`/input-media/${storagePath(key)}`, {method: 'DELETE'});
  } catch {
    // Temporary-input retention is still authoritative cleanup.
  }
}

function idempotencyKey() {
  const storageKey = 'foxgen:suno-cover:idempotency';
  let value = sessionStorage.getItem(storageKey);
  if (!value) {
    value = `suno-cover:${crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`}`;
    sessionStorage.setItem(storageKey, value);
  }
  return {storageKey, value};
}

function panel() {
  return root?.querySelector('[data-suno-cover-panel]') ?? null;
}

function status(message, kind = '') {
  const node = panel()?.querySelector('[data-suno-cover-status]');
  if (!node) return;
  node.className = `complete-stars-panel ${kind}`;
  node.textContent = message;
}

function syncFields() {
  const host = panel();
  if (!host) return;
  const custom = host.querySelector('[name="suno-cover-mode"]:checked')?.value === 'custom';
  const instrumentalToggle = host.querySelector('[name="suno-cover-instrumental"]');
  if (!custom && instrumentalToggle) instrumentalToggle.checked = false;
  for (const item of host.querySelectorAll('[data-suno-cover-custom]')) item.hidden = !custom;
  const prompt = host.querySelector('[name="suno-cover-prompt"]');
  const instrumental = custom && instrumentalToggle?.checked === true;
  if (prompt) {
    prompt.maxLength = custom ? 5000 : 500;
    prompt.required = !instrumental;
    prompt.placeholder = custom && instrumental
      ? 'Необязательно для кастомного инструментала'
      : 'Опишите, как переработать исходное аудио';
  }
}

async function quote() {
  const data = await api('/bootstrap');
  const price = (data?.prices ?? []).find(
    (item) => item?.model_slug === MODEL && item?.enabled !== false,
  );
  const available = Number(data?.balance?.available_units ?? 0);
  if (!price || Number(price.amount_units) <= 0) {
    return {ok: false, text: 'Цена Suno V5 Cover не опубликована.'};
  }
  const amount = Number(price.amount_units);
  if (available < amount) {
    return {ok: false, text: `Недостаточно средств: нужно ${amount} CREDIT, доступно ${available}.`};
  }
  return {ok: true, text: `${amount} CREDIT · доступно ${available}`};
}

async function uploadAudio(file) {
  if (!file?.type?.startsWith('audio/')) throw new Error('Выберите аудиофайл.');
  await cleanupUploaded();
  const result = await api('/input-media', {
    method: 'POST',
    headers: {'Content-Type': file.type},
    body: file,
  });
  if (!result?.storage_key) throw new Error('Сервер не вернул storage_key загруженного аудио.');
  uploadedKey = result.storage_key;
  return result;
}

async function submitCover(event) {
  event.preventDefault();
  if (busy) return;
  busy = true;
  const host = panel();
  const form = event.currentTarget;
  const submit = form.querySelector('button[type="submit"]');
  if (submit) submit.disabled = true;
  try {
    const file = form.querySelector('[name="suno-cover-file"]')?.files?.[0];
    if (!file) throw new Error('Сначала выберите аудиофайл.');
    status('Проверяю цену и загружаю приватный аудиофайл…');
    const pricing = await quote();
    if (!pricing.ok) throw new Error(pricing.text);
    if (!uploadedKey) await uploadAudio(file);

    const custom = form.querySelector('[name="suno-cover-mode"]:checked')?.value === 'custom';
    const instrumental = custom && form.querySelector('[name="suno-cover-instrumental"]')?.checked === true;
    const prompt = form.querySelector('[name="suno-cover-prompt"]')?.value?.trim() ?? '';
    const style = form.querySelector('[name="suno-cover-style"]')?.value?.trim() ?? '';
    const title = form.querySelector('[name="suno-cover-title"]')?.value?.trim() ?? '';
    if (!prompt && (!custom || !instrumental)) throw new Error('Prompt обязателен в выбранном режиме.');
    if (custom && !style) throw new Error('Для кастомного Cover укажите стиль.');
    if (custom && !title) throw new Error('Для кастомного Cover укажите название.');

    const pending = idempotencyKey();
    status(`Создаю Cover · ${pricing.text}`);
    const result = await api('/music/suno/upload-cover', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': pending.value,
      },
      body: JSON.stringify({
        input_storage_key: uploadedKey,
        custom_mode: custom,
        instrumental,
        prompt,
        style: custom ? style : '',
        title: custom ? title : '',
        negative_tags: '',
      }),
    });
    submittedKey = uploadedKey;
    sessionStorage.removeItem(pending.storageKey);
    status(`Suno Cover поставлен в очередь · ${result.generation_id}`, 'success');
  } catch (error) {
    status(error?.message ?? String(error), 'error');
  } finally {
    busy = false;
    if (submit) submit.disabled = false;
  }
}

function removeRawModelRow() {
  root?.querySelector('[data-model="suno-v5-upload-cover"]')?.remove();
}

function ensureAction() {
  if (!root || root.querySelector('[data-suno-cover-action]')) return;
  const headings = [...root.querySelectorAll('.product-head h2')];
  const musicHeading = headings.find((item) => item.textContent?.trim() === 'Музыка');
  const list = musicHeading?.closest('.product-head')?.nextElementSibling;
  if (!list?.classList.contains('model-list')) return;
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'model-row grunge-lite';
  button.dataset.sunoCoverAction = '1';
  button.innerHTML = `
    <span class="model-glyph">🎧</span>
    <div><strong>Suno Cover из аудио</strong><small>V5 · приватный upload</small><p>Загрузите своё аудио и переработайте стиль</p></div>
    <span>›</span>
  `;
  list.append(button);
}

function openPanel() {
  let host = panel();
  if (!host) {
    host = document.createElement('section');
    host.className = 'section schema-card';
    host.dataset.sunoCoverPanel = '1';
    host.innerHTML = `
      <div class="section-head"><div><span class="stamp">SUNO V5</span><h2>Cover из аудио</h2></div></div>
      <form data-suno-cover-form>
        <label><strong>Исходное аудио</strong><input name="suno-cover-file" type="file" accept="audio/*" required></label>
        <fieldset>
          <legend>Режим</legend>
          <label><input type="radio" name="suno-cover-mode" value="simple" checked> Быстрый</label>
          <label><input type="radio" name="suno-cover-mode" value="custom"> Кастомный</label>
        </fieldset>
        <label data-suno-cover-custom hidden><input type="checkbox" name="suno-cover-instrumental"> Инструментал</label>
        <label><strong>Prompt</strong><textarea name="suno-cover-prompt" maxlength="500" required></textarea></label>
        <label data-suno-cover-custom hidden><strong>Стиль</strong><input name="suno-cover-style" maxlength="1000"></label>
        <label data-suno-cover-custom hidden><strong>Название</strong><input name="suno-cover-title" maxlength="100"></label>
        <button type="submit" class="accent">Создать Cover</button>
        <button type="button" data-suno-cover-close>Закрыть</button>
      </form>
      <p data-suno-cover-status></p>
    `;
    root.prepend(host);
    host.querySelector('[data-suno-cover-form]')?.addEventListener('submit', submitCover);
    host.addEventListener('change', (event) => {
      if (event.target?.matches?.('[name="suno-cover-mode"], [name="suno-cover-instrumental"]')) syncFields();
      if (event.target?.matches?.('[name="suno-cover-file"]')) {
        void cleanupUploaded();
      }
    });
    host.querySelector('[data-suno-cover-close]')?.addEventListener('click', () => {
      void cleanupUploaded();
      host.remove();
    });
  }
  syncFields();
  host.scrollIntoView({behavior: 'smooth', block: 'start'});
  void quote().then((value) => status(value.text, value.ok ? 'success' : 'warning')).catch((error) => status(error?.message ?? error, 'error'));
}

function enhance() {
  removeRawModelRow();
  ensureAction();
}

root?.addEventListener('click', (event) => {
  const target = event.target;
  if (!(target instanceof Element)) return;
  if (target.closest('[data-suno-cover-action]')) {
    event.preventDefault();
    openPanel();
  }
});

const observer = new MutationObserver(() => queueMicrotask(enhance));
if (root) {
  observer.observe(root, {childList: true, subtree: true});
  enhance();
}