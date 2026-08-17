const root = document.getElementById('app');
const tg = window.Telegram?.WebApp ?? null;

const MODEL = 'kling-3-motion-control';
const IMAGE_MAX_BYTES = 10 * 1024 * 1024;
const VIDEO_MAX_BYTES = 100 * 1024 * 1024;
const MIN_SIDE = 341;
const MIN_RATIO = 2 / 5;
const MAX_RATIO = 5 / 2;
const MIN_DURATION = 3;
const MAX_DURATION = 30;

let token = null;
let busy = false;
let imageFile = null;
let videoFile = null;
let imageKey = null;
let videoKey = null;
let submitted = false;

function esc(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function formatBytes(value) {
  const bytes = Number(value ?? 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
  if (bytes < 1024 * 1024) return `${Math.ceil(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
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
    throw new Error(data?.detail || data?.message || 'Не удалось подтвердить Telegram-профиль.');
  }
  token = data.access_token;
  return token;
}

async function api(path, options = {}, retryAuth = true) {
  const bearer = await auth(false);
  const headers = new Headers(options.headers ?? {});
  headers.set('Authorization', `Bearer ${bearer}`);
  const response = await fetch(`/v1/miniapp${path}`, { ...options, headers });
  const data = response.status === 204 ? null : await response.json().catch(() => ({}));
  if (response.status === 401 && retryAuth) {
    await auth(true);
    return api(path, options, false);
  }
  if (!response.ok) {
    const detail = data?.detail;
    const message = typeof detail === 'string' ? detail : data?.message;
    throw new Error(message || `HTTP ${response.status}`);
  }
  return data;
}

function storagePath(key) {
  return String(key).split('/').map(encodeURIComponent).join('/');
}

async function deleteKey(key) {
  if (!key || submitted) return;
  try {
    await api(`/input-media/${storagePath(key)}`, { method: 'DELETE' });
  } catch {
    // Server-side input retention remains the authoritative cleanup fallback.
  }
}

async function resetInputs() {
  const oldImage = imageKey;
  const oldVideo = videoKey;
  imageKey = null;
  videoKey = null;
  imageFile = null;
  videoFile = null;
  if (!submitted) await Promise.all([deleteKey(oldImage), deleteKey(oldVideo)]);
}

function quoteFromBootstrap(data) {
  const model = (data?.models ?? []).find((item) => item?.slug === MODEL && item?.enabled !== false);
  const price = (data?.prices ?? []).find(
    (item) => item?.model_slug === MODEL && item?.enabled !== false,
  );
  const available = Number(data?.balance?.available_units ?? 0);
  const amount = Number(price?.amount_units ?? 0);
  if (!model) return { ok: false, reason: 'Модель Motion Control сейчас недоступна.' };
  if (data?.features?.task_submission !== true) {
    return { ok: false, reason: 'Запуск генераций сейчас отключён на сервере.' };
  }
  if (!Number.isFinite(amount) || amount <= 0) {
    return { ok: false, reason: 'Цена Motion Control ещё не опубликована.' };
  }
  if (available < amount) {
    return {
      ok: false,
      insufficient: true,
      amount,
      available,
      reason: `Недостаточно CREDIT: нужно ${amount.toLocaleString('ru-RU')}, доступно ${available.toLocaleString('ru-RU')}.`,
    };
  }
  return { ok: true, amount, available };
}

async function quote() {
  return quoteFromBootstrap(await api('/bootstrap'));
}

function panel() {
  return root?.querySelector('[data-motion-panel]') ?? null;
}

function status(message, kind = '') {
  const node = panel()?.querySelector('[data-motion-status]');
  if (!node) return;
  node.className = `complete-stars-panel ${kind}`.trim();
  node.textContent = message;
}

function ensureMotionLauncher() {
  const button = root?.querySelector('[data-complete-tool="motion"]');
  if (!(button instanceof HTMLButtonElement)) return;
  button.disabled = false;
  button.removeAttribute('aria-disabled');
  button.classList.remove('is-planned');
  button.classList.add('is-ready');
  const statusNode = button.querySelector('.complete-tool__status');
  if (statusNode) statusNode.textContent = 'Доступно';
  const subtitle = button.querySelector('.complete-tool__copy small');
  if (subtitle) subtitle.textContent = 'Перенос движения на персонажа · Kling 3.0';
}

function removeRawModelRow() {
  const row = root?.querySelector(`[data-model="${MODEL}"]`);
  const list = row?.closest('.model-list');
  row?.remove();
  if (!list) return;
  const head = list.previousElementSibling;
  const count = head?.querySelector('small');
  if (count) count.textContent = String(list.querySelectorAll('.model-row').length);
}

function ensureMotionProduct() {
  if (!root || root.querySelector('[data-motion-product-list]')) return;
  const headings = [...root.querySelectorAll('.product-head h2')];
  const videoHeading = headings.find((item) => item.textContent?.trim() === 'Видео');
  const videoHead = videoHeading?.closest('.product-head');
  const videoList = videoHead?.nextElementSibling;
  if (!videoList?.classList.contains('model-list')) return;

  const head = document.createElement('div');
  head.className = 'product-head';
  head.dataset.motionProductHead = '1';
  head.innerHTML = '<h2>Motion Control</h2><small>1</small>';

  const list = document.createElement('div');
  list.className = 'model-list';
  list.dataset.motionProductList = '1';
  list.innerHTML = `
    <button class="model-row grunge-lite" type="button" data-motion-open>
      <span class="model-glyph">◆</span>
      <div>
        <strong>Kling 3.0 Motion Control</strong>
        <small>Фото персонажа + видео движения · цена из backend</small>
        <p>Перенос позы и движения без технических настроек провайдера</p>
      </div>
      <span>›</span>
    </button>
  `;
  videoList.insertAdjacentElement('afterend', head);
  head.insertAdjacentElement('afterend', list);
}

function selectedFile(name, file, hint) {
  if (!file) return `<small>${hint}</small>`;
  return `<small><strong>${esc(file.name)}</strong> · ${formatBytes(file.size)}</small>`;
}

function renderPanel() {
  let host = panel();
  if (!host) {
    host = document.createElement('section');
    host.className = 'section schema-card motion-control-card';
    host.dataset.motionPanel = '1';
    const list = root?.querySelector('[data-motion-product-list]');
    if (!list) return null;
    list.insertAdjacentElement('afterend', host);
  }

  host.innerHTML = `
    <div class="section-head">
      <div>
        <span class="stamp">KLING 3.0 / MOTION</span>
        <h2>Перенос движения</h2>
        <small>1 фото персонажа + 1 видео движения</small>
      </div>
      <button type="button" class="ghost-mini" data-motion-close>Закрыть</button>
    </div>
    <div class="motion-input-grid">
      <label class="upload-box motion-file-box">
        <strong>1. Фото персонажа</strong>
        ${selectedFile('image', imageFile, 'JPEG / PNG · до 10 MB · обе стороны > 340 px')}
        <input name="motion-image" type="file" accept="image/jpeg,image/png" hidden>
      </label>
      <label class="upload-box motion-file-box">
        <strong>2. Видео движения</strong>
        ${selectedFile('video', videoFile, 'MP4 / MOV · 3–30 сек · до 100 MB')}
        <input name="motion-video" type="file" accept="video/mp4,video/quicktime,.mov" hidden>
      </label>
    </div>
    <label class="field motion-prompt-field">
      <span>3. Что должно происходить</span>
      <textarea name="motion-prompt" maxlength="10000" placeholder="Например: персонаж повторяет танец из видео, движения естественные, лицо стабильно"></textarea>
    </label>
    <div class="notice grunge-lite motion-settings-note">
      <strong>Настройки</strong>
      <span>720p · движение берём из видео · внешний вид персонажа из фото · фон из motion video</span>
    </div>
    <div class="launch-card grunge-card motion-launch">
      <div data-motion-quote><small>Цена</small><strong>Проверяем…</strong><span>Из backend</span></div>
      <button type="button" class="hf-primary" data-motion-submit disabled>Создать видео</button>
    </div>
    <p data-motion-status class="complete-stars-panel"></p>
  `;
  bindPanel(host);
  void refreshQuote();
  return host;
}

async function refreshQuote() {
  const host = panel();
  if (!host) return;
  const submit = host.querySelector('[data-motion-submit]');
  const quoteNode = host.querySelector('[data-motion-quote]');
  try {
    const value = await quote();
    if (quoteNode) {
      quoteNode.innerHTML = value.ok
        ? `<small>Цена</small><strong>${Number(value.amount).toLocaleString('ru-RU')} CREDIT</strong><span>Баланс ${Number(value.available).toLocaleString('ru-RU')} CREDIT</span>`
        : `<small>Запуск недоступен</small><strong>—</strong><span>${esc(value.reason)}</span>`;
    }
    if (submit instanceof HTMLButtonElement) submit.disabled = !value.ok || busy;
    if (!value.ok) {
      status(value.reason, value.insufficient ? 'warning' : 'error');
      if (value.insufficient && !host.querySelector('[data-motion-wallet]')) {
        const wallet = document.createElement('button');
        wallet.type = 'button';
        wallet.dataset.motionWallet = '1';
        wallet.textContent = 'Пополнить баланс';
        host.querySelector('[data-motion-status]')?.insertAdjacentElement('afterend', wallet);
      }
    } else {
      status('Файлы проверятся локально и ещё раз на backend до списания CREDIT.', 'success');
    }
  } catch (error) {
    if (submit instanceof HTMLButtonElement) submit.disabled = true;
    status(error?.message ?? String(error), 'error');
  }
}

function bindPanel(host) {
  const image = host.querySelector('[name="motion-image"]');
  const video = host.querySelector('[name="motion-video"]');
  image?.addEventListener('change', async () => {
    const file = image.files?.[0] ?? null;
    if (!file) return;
    try {
      await validateImage(file);
      const oldKey = imageKey;
      imageKey = null;
      imageFile = file;
      await deleteKey(oldKey);
      renderPanel()?.scrollIntoView({ block: 'start' });
      status('Фото подходит. Добавьте видео движения.', 'success');
    } catch (error) {
      image.value = '';
      status(error?.message ?? String(error), 'error');
    }
  });
  video?.addEventListener('change', async () => {
    const file = video.files?.[0] ?? null;
    if (!file) return;
    try {
      await validateVideo(file);
      const oldKey = videoKey;
      videoKey = null;
      videoFile = file;
      await deleteKey(oldKey);
      renderPanel()?.scrollIntoView({ block: 'start' });
      status('Видео подходит. Добавьте описание движения и запускайте.', 'success');
    } catch (error) {
      video.value = '';
      status(error?.message ?? String(error), 'error');
    }
  });
  host.querySelector('[data-motion-close]')?.addEventListener('click', async () => {
    await resetInputs();
    host.remove();
  });
  host.querySelector('[data-motion-submit]')?.addEventListener('click', submitMotion);
  host.querySelector('[data-motion-wallet]')?.addEventListener('click', openWallet);
}

async function imageDimensions(file) {
  if ('createImageBitmap' in window) {
    const bitmap = await createImageBitmap(file);
    try {
      return { width: bitmap.width, height: bitmap.height };
    } finally {
      bitmap.close();
    }
  }
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => {
      URL.revokeObjectURL(url);
      resolve({ width: image.naturalWidth, height: image.naturalHeight });
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('Не удалось прочитать изображение.'));
    };
    image.src = url;
  });
}

async function videoMetadata(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const video = document.createElement('video');
    video.preload = 'metadata';
    video.onloadedmetadata = () => {
      const result = {
        width: video.videoWidth,
        height: video.videoHeight,
        duration: video.duration,
      };
      video.removeAttribute('src');
      video.load();
      URL.revokeObjectURL(url);
      resolve(result);
    };
    video.onerror = () => {
      video.removeAttribute('src');
      URL.revokeObjectURL(url);
      reject(new Error('Не удалось прочитать параметры видео.'));
    };
    video.src = url;
  });
}

function validateGeometry({ width, height }, label) {
  if (Number(width) < MIN_SIDE || Number(height) < MIN_SIDE) {
    throw new Error(`${label}: каждая сторона должна быть больше 340 px.`);
  }
  const ratio = Number(width) / Number(height);
  if (!Number.isFinite(ratio) || ratio < MIN_RATIO || ratio > MAX_RATIO) {
    throw new Error(`${label}: соотношение сторон должно быть от 2:5 до 5:2.`);
  }
}

async function validateImage(file) {
  if (!['image/jpeg', 'image/png'].includes(file.type)) {
    throw new Error('Фото должно быть JPEG или PNG.');
  }
  if (file.size <= 0 || file.size > IMAGE_MAX_BYTES) {
    throw new Error('Фото должно быть не больше 10 MB.');
  }
  validateGeometry(await imageDimensions(file), 'Фото');
}

async function validateVideo(file) {
  const allowed = ['video/mp4', 'video/quicktime'];
  const movByName = file.name.toLowerCase().endsWith('.mov');
  if (!allowed.includes(file.type) && !movByName) {
    throw new Error('Видео должно быть MP4 или MOV.');
  }
  if (file.size <= 0 || file.size > VIDEO_MAX_BYTES) {
    throw new Error('Видео должно быть не больше 100 MB.');
  }
  const metadata = await videoMetadata(file);
  validateGeometry(metadata, 'Видео');
  if (
    !Number.isFinite(metadata.duration)
    || metadata.duration < MIN_DURATION
    || metadata.duration > MAX_DURATION
  ) {
    throw new Error('Видео движения должно длиться от 3 до 30 секунд.');
  }
}

async function upload(kind, file) {
  return api(`/motion/kling/inputs/${kind}`, {
    method: 'POST',
    headers: { 'Content-Type': file.type || (kind === 'video' ? 'video/quicktime' : '') },
    body: file,
  });
}

function idempotencyKey() {
  const key = 'foxgen:kling-motion:idempotency';
  let value = sessionStorage.getItem(key);
  if (!value) {
    value = `kling-motion:${crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`}`;
    sessionStorage.setItem(key, value);
  }
  return { key, value };
}

async function submitMotion() {
  if (busy) return;
  const host = panel();
  const prompt = host?.querySelector('[name="motion-prompt"]')?.value?.trim() ?? '';
  if (!imageFile) return status('Добавьте фото персонажа.', 'error');
  if (!videoFile) return status('Добавьте видео движения.', 'error');
  if (!prompt) return status('Опишите, что должно происходить.', 'error');

  busy = true;
  const submit = host?.querySelector('[data-motion-submit]');
  if (submit instanceof HTMLButtonElement) submit.disabled = true;
  try {
    const pricing = await quote();
    if (!pricing.ok) throw new Error(pricing.reason);
    status('Проверяю и загружаю приватные исходники…');
    if (!imageKey) imageKey = (await upload('image', imageFile))?.storage_key ?? null;
    if (!imageKey) throw new Error('Backend не вернул ключ изображения.');
    if (!videoKey) videoKey = (await upload('video', videoFile))?.storage_key ?? null;
    if (!videoKey) throw new Error('Backend не вернул ключ видео.');

    const pending = idempotencyKey();
    status(`Запускаю Motion Control · ${Number(pricing.amount).toLocaleString('ru-RU')} CREDIT…`);
    const result = await api('/motion/kling', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': pending.value,
      },
      body: JSON.stringify({
        prompt,
        image_storage_key: imageKey,
        video_storage_key: videoKey,
        mode: '720p',
        character_orientation: 'image',
        background_source: 'input_video',
      }),
    });
    submitted = true;
    sessionStorage.removeItem(pending.key);
    status(`Генерация поставлена в очередь · ${result.generation_id}`, 'success');
    const actions = document.createElement('div');
    actions.className = 'action-grid';
    actions.innerHTML = '<button type="button" data-motion-works>Открыть мои работы</button>';
    host?.append(actions);
    actions.querySelector('[data-motion-works]')?.addEventListener('click', () => {
      root?.querySelector('[data-nav="works"]')?.click();
    });
  } catch (error) {
    status(error?.message ?? String(error), 'error');
  } finally {
    busy = false;
    if (submit instanceof HTMLButtonElement) submit.disabled = false;
  }
}

function openWallet() {
  root?.querySelector('[data-nav="wallet"]')?.click();
}

function openPanel() {
  const host = renderPanel();
  host?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function enhance() {
  ensureMotionLauncher();
  removeRawModelRow();
  ensureMotionProduct();
}

root?.addEventListener(
  'click',
  (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const launcher = target.closest('[data-complete-tool="motion"]');
    if (launcher instanceof HTMLButtonElement) {
      event.preventDefault();
      event.stopImmediatePropagation();
      root.querySelector('[data-nav="create"]')?.click();
      queueMicrotask(() => {
        enhance();
        root.querySelector('[data-motion-product-head]')?.scrollIntoView({
          behavior: 'smooth',
          block: 'start',
        });
      });
      return;
    }
    if (target.closest('[data-motion-open]')) {
      event.preventDefault();
      event.stopImmediatePropagation();
      openPanel();
    }
  },
  true,
);

const observer = new MutationObserver(() => queueMicrotask(enhance));
if (root) {
  observer.observe(root, { childList: true, subtree: true });
  enhance();
}
