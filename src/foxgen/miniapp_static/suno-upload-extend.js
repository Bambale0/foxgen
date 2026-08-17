const root = document.getElementById('app');
const tg = window.Telegram?.WebApp ?? null;
const MODEL = 'suno-v5-upload-extend';

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
  if (!response.ok || !data?.access_token) {
    throw new Error(data?.detail || 'Не удалось подтвердить Telegram-профиль.');
  }
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
  const storageKey = 'foxgen:suno-upload-extend:idempotency';
  let value = sessionStorage.getItem(storageKey);
  if (!value) {
    value = `suno-upload-extend:${crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`}`;
    sessionStorage.setItem(storageKey, value);
  }
  return {storageKey, value};
}

function panel() {
  return root?.querySelector('[data-suno-upload-extend-panel]') ?? null;
}

function status(message, kind = '') {
  const node = panel()?.querySelector('[data-suno-upload-extend-status]');
  if (!node) return;
  node.className = `complete-stars-panel ${kind}`;
  node.textContent = message;
}

function numericValue(form, name) {
  const raw = form.querySelector(`[name="${name}"]`)?.value?.trim() ?? '';
  if (!raw) return null;
  const value = Number(raw.replace(',', '.'));
  if (!Number.isFinite(value)) throw new Error(`${name}: введите число.`);
  return value;
}

function syncFields() {
  const host = panel();
  if (!host) return;
  const custom = host.querySelector('[name="suno-upload-extend-mode"]:checked')?.value === 'custom';
  const instrumental = host.querySelector('[name="suno-upload-extend-instrumental"]')?.checked === true;
  for (const item of host.querySelectorAll('[data-suno-upload-extend-custom]')) item.hidden = !custom;
  const instrumentalRow = host.querySelector('[data-suno-upload-extend-instrumental-row]');
  if (instrumentalRow) instrumentalRow.hidden = !custom;
  const prompt = host.querySelector('[name="suno-upload-extend-prompt"]');
  if (prompt) {
    prompt.maxLength = 5000;
    prompt.required = !custom || !instrumental;
    prompt.placeholder = custom && instrumental
      ? 'Необязательно для кастомного инструментала'
      : 'Опишите, как продолжить исходное аудио';
  }
}

async function quote() {
  const data = await api('/bootstrap');
  const model = (data?.models ?? []).find((item) => item?.slug === MODEL);
  const price = model?.price ?? (data?.prices ?? []).find((item) => item?.model_slug === MODEL);
  const available = Number(data?.balance?.available_units ?? 0);
  if (!price || Number(price.amount_units) <= 0) {
    return {ok: false, text: 'Цена Suno V5 Upload & Extend не опубликована.'};
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

function boundedWeight(form, name) {
  const value = numericValue(form, name);
  if (value === null) return null;
  if (value < 0 || value > 1) throw new Error(`${name}: значение должно быть от 0 до 1.`);
  return value;
}

async function submitUploadExtend(event) {
  event.preventDefault();
  if (busy) return;
  busy = true;
  const form = event.currentTarget;
  const submit = form.querySelector('button[type="submit"]');
  if (submit) submit.disabled = true;
  try {
    const file = form.querySelector('[name="suno-upload-extend-file"]')?.files?.[0];
    if (!file) throw new Error('Сначала выберите аудиофайл.');
    status('Проверяю цену и загружаю приватный аудиофайл…');
    const pricing = await quote();
    if (!pricing.ok) throw new Error(pricing.text);
    if (!uploadedKey) await uploadAudio(file);

    const custom = form.querySelector('[name="suno-upload-extend-mode"]:checked')?.value === 'custom';
    const instrumental = custom && form.querySelector('[name="suno-upload-extend-instrumental"]')?.checked === true;
    const prompt = form.querySelector('[name="suno-upload-extend-prompt"]')?.value?.trim() ?? '';
    const style = form.querySelector('[name="suno-upload-extend-style"]')?.value?.trim() ?? '';
    const title = form.querySelector('[name="suno-upload-extend-title"]')?.value?.trim() ?? '';
    const continueAt = custom ? numericValue(form, 'suno-upload-extend-continue-at') : null;
    const negativeTags = form.querySelector('[name="suno-upload-extend-negative-tags"]')?.value?.trim() ?? '';
    const vocalGender = form.querySelector('[name="suno-upload-extend-vocal-gender"]')?.value ?? '';
    const personaId = form.querySelector('[name="suno-upload-extend-persona"]')?.value?.trim() ?? '';
    const styleWeight = custom ? boundedWeight(form, 'suno-upload-extend-style-weight') : null;
    const weirdness = custom ? boundedWeight(form, 'suno-upload-extend-weirdness') : null;
    const audioWeight = custom ? boundedWeight(form, 'suno-upload-extend-audio-weight') : null;

    if (!prompt && (!custom || !instrumental)) throw new Error('Prompt обязателен в выбранном режиме.');
    if (custom && !style) throw new Error('Для кастомного продолжения укажите стиль.');
    if (custom && !title) throw new Error('Для кастомного продолжения укажите название.');
    if (custom && (!continueAt || continueAt <= 0)) {
      throw new Error('Точка продолжения должна быть больше 0 секунд.');
    }

    const body = {
      input_storage_key: uploadedKey,
      default_param_flag: custom,
      instrumental: custom ? instrumental : false,
      prompt,
      style: custom ? style : '',
      title: custom ? title : '',
      negative_tags: custom ? negativeTags : '',
    };
    if (custom) {
      body.continue_at = continueAt;
      if (vocalGender) body.vocal_gender = vocalGender;
      if (personaId) body.persona_id = personaId;
      if (styleWeight !== null) body.style_weight = styleWeight;
      if (weirdness !== null) body.weirdness_constraint = weirdness;
      if (audioWeight !== null) body.audio_weight = audioWeight;
    }

    const pending = idempotencyKey();
    status(`Создаю продолжение · ${pricing.text}`);
    const result = await api('/music/suno/upload-extend', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': pending.value,
      },
      body: JSON.stringify(body),
    });
    submittedKey = uploadedKey;
    sessionStorage.removeItem(pending.storageKey);
    status(`Upload & Extend поставлен в очередь · ${result.generation_id}`, 'success');
  } catch (error) {
    status(error?.message ?? String(error), 'error');
  } finally {
    busy = false;
    if (submit) submit.disabled = false;
  }
}

function removeRawModelRow() {
  root?.querySelector('[data-model="suno-v5-upload-extend"]')?.remove();
}

function ensureAction() {
  if (!root || root.querySelector('[data-suno-upload-extend-action]')) return;
  const headings = [...root.querySelectorAll('.product-head h2')];
  const musicHeading = headings.find((item) => item.textContent?.trim() === 'Музыка');
  const list = musicHeading?.closest('.product-head')?.nextElementSibling;
  if (!list?.classList.contains('model-list')) return;
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'model-row grunge-lite';
  button.dataset.sunoUploadExtendAction = '1';
  button.innerHTML = `
    <span class="model-glyph">⏩</span>
    <div><strong>Продолжить своё аудио</strong><small>Suno V5 · приватный upload</small><p>Загрузите аудио и достройте продолжение</p></div>
    <span>›</span>
  `;
  list.append(button);
}

function openPanel() {
  let host = panel();
  if (!host) {
    host = document.createElement('section');
    host.className = 'section schema-card';
    host.dataset.sunoUploadExtendPanel = '1';
    host.innerHTML = `
      <div class="section-head"><div><span class="stamp">SUNO V5</span><h2>Продолжить своё аудио</h2></div></div>
      <form data-suno-upload-extend-form>
        <label><strong>Исходное аудио</strong><input name="suno-upload-extend-file" type="file" accept="audio/*" required></label>
        <fieldset>
          <legend>Режим</legend>
          <label><input type="radio" name="suno-upload-extend-mode" value="simple" checked> Быстро</label>
          <label><input type="radio" name="suno-upload-extend-mode" value="custom"> Кастомный</label>
        </fieldset>
        <label data-suno-upload-extend-instrumental-row hidden><input type="checkbox" name="suno-upload-extend-instrumental"> Инструментал</label>
        <label><strong>Prompt</strong><textarea name="suno-upload-extend-prompt" maxlength="5000" required></textarea></label>
        <label data-suno-upload-extend-custom hidden><strong>Стиль</strong><input name="suno-upload-extend-style" maxlength="1000"></label>
        <label data-suno-upload-extend-custom hidden><strong>Название</strong><input name="suno-upload-extend-title" maxlength="100"></label>
        <label data-suno-upload-extend-custom hidden><strong>Продолжить с, сек</strong><input name="suno-upload-extend-continue-at" type="number" min="0.01" step="0.01"></label>
        <details data-suno-upload-extend-custom hidden>
          <summary>Расширенные настройки</summary>
          <label><strong>Исключить стили</strong><input name="suno-upload-extend-negative-tags" maxlength="1000"></label>
          <label><strong>Вокал</strong><select name="suno-upload-extend-vocal-gender"><option value="">Авто</option><option value="f">Женский</option><option value="m">Мужской</option></select></label>
          <label><strong>Style weight</strong><input name="suno-upload-extend-style-weight" type="number" min="0" max="1" step="0.05"></label>
          <label><strong>Weirdness</strong><input name="suno-upload-extend-weirdness" type="number" min="0" max="1" step="0.05"></label>
          <label><strong>Audio weight</strong><input name="suno-upload-extend-audio-weight" type="number" min="0" max="1" step="0.05"></label>
          <label><strong>Persona ID</strong><input name="suno-upload-extend-persona" maxlength="128"></label>
        </details>
        <button type="submit" class="accent">Продолжить аудио</button>
        <button type="button" data-suno-upload-extend-close>Закрыть</button>
      </form>
      <p data-suno-upload-extend-status></p>
    `;
    root.prepend(host);
    host.querySelector('[data-suno-upload-extend-form]')?.addEventListener('submit', submitUploadExtend);
    host.addEventListener('change', (event) => {
      if (event.target?.matches?.('[name="suno-upload-extend-mode"], [name="suno-upload-extend-instrumental"]')) syncFields();
      if (event.target?.matches?.('[name="suno-upload-extend-file"]')) void cleanupUploaded();
    });
    host.querySelector('[data-suno-upload-extend-close]')?.addEventListener('click', () => {
      void cleanupUploaded();
      host.remove();
    });
  }
  syncFields();
  host.scrollIntoView({behavior: 'smooth', block: 'start'});
  void quote()
    .then((value) => status(value.text, value.ok ? 'success' : 'warning'))
    .catch((error) => status(error?.message ?? error, 'error'));
}

function enhance() {
  removeRawModelRow();
  ensureAction();
}

root?.addEventListener('click', (event) => {
  const target = event.target;
  if (!(target instanceof Element)) return;
  if (target.closest('[data-suno-upload-extend-action]')) {
    event.preventDefault();
    openPanel();
  }
});

const observer = new MutationObserver(() => queueMicrotask(enhance));
if (root) {
  observer.observe(root, {childList: true, subtree: true});
  enhance();
}
