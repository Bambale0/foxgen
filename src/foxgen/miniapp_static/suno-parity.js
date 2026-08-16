const root = document.getElementById('app');

const SUNO_SLUG = 'suno-v5';
const SUNO_TITLE = 'Suno V5';

function ensureMusicLauncher() {
  const button = root?.querySelector('[data-complete-tool="music"]');
  if (!(button instanceof HTMLButtonElement)) return;
  button.disabled = false;
  button.removeAttribute('aria-disabled');
  button.classList.remove('is-planned');
  button.classList.add('is-ready');
  const status = button.querySelector('.complete-tool__status');
  if (status) status.textContent = 'Доступно';
}

function insertionAnchor() {
  const ttsList = root?.querySelector('[data-tts-product-list]');
  if (ttsList) return ttsList;
  const headings = [...(root?.querySelectorAll('.product-head h2') ?? [])];
  const videoHeading = headings.find((item) => item.textContent?.trim() === 'Видео');
  const videoHead = videoHeading?.closest('.product-head');
  const videoList = videoHead?.nextElementSibling;
  return videoList?.classList.contains('model-list') ? videoList : null;
}

function ensureMusicProduct() {
  if (!root || root.querySelector(`[data-model="${SUNO_SLUG}"]`)) return;
  const anchor = insertionAnchor();
  if (!anchor) return;

  const head = document.createElement('div');
  head.className = 'product-head';
  head.dataset.sunoProductHead = '1';
  head.innerHTML = '<h2>Музыка</h2><small>1</small>';

  const list = document.createElement('div');
  list.className = 'model-list';
  list.dataset.sunoProductList = '1';
  list.innerHTML = `
    <button class="model-row grunge-lite" data-model="${SUNO_SLUG}">
      <span class="model-glyph">♫</span>
      <div>
        <strong>${SUNO_TITLE}</strong>
        <small>Suno · цена из backend</small>
        <p>Песни и инструменталы · simple / custom</p>
      </div>
      <span>›</span>
    </button>
  `;
  anchor.insertAdjacentElement('afterend', head);
  head.insertAdjacentElement('afterend', list);
}

function fieldContainer(name) {
  const control = root?.querySelector(`[data-field="${name}"]`);
  return control?.closest('label') ?? null;
}

function renameField(name, title) {
  const container = fieldContainer(name);
  if (!container) return;
  const label = container.querySelector(':scope > span, :scope > div > strong');
  if (!label) return;
  const required = label.textContent?.includes('*') ? ' *' : '';
  label.textContent = `${title}${required}`;
}

function setVisible(name, visible) {
  const container = fieldContainer(name);
  if (container) container.hidden = !visible;
}

function currentBoolean(name) {
  const control = root?.querySelector(`[data-field="${name}"]`);
  return control instanceof HTMLInputElement ? control.checked : false;
}

function hardenSunoStudio() {
  const title = root?.querySelector('.studio-header h1')?.textContent?.trim();
  if (title !== SUNO_TITLE) return;

  const launch = root?.querySelector('.launch-card');
  const submit = launch?.querySelector('[data-submit]');
  const costText = launch?.querySelector('strong')?.textContent?.trim() ?? '';
  const amount = Number(costText.replace(/[^0-9.-]/g, ''));
  if (submit instanceof HTMLButtonElement && (!Number.isFinite(amount) || amount <= 0)) {
    submit.disabled = true;
    submit.textContent = 'Цена не опубликована';
    if (!launch?.querySelector('[data-suno-price-warning]')) {
      const warning = document.createElement('p');
      warning.dataset.sunoPriceWarning = '1';
      warning.textContent = 'Запуск появится после публикации активной цены администратором.';
      launch?.append(warning);
    }
  }

  const labels = {
    custom_mode: 'Кастомный режим',
    instrumental: 'Инструментал',
    prompt: 'Prompt / текст песни',
    style: 'Стиль',
    title: 'Название трека',
    negative_tags: 'Исключить стили / теги',
    vocal_gender: 'Пол вокала',
    style_weight: 'Вес стиля',
    weirdness_constraint: 'Экспериментальность',
    audio_weight: 'Вес аудио',
  };
  for (const [name, label] of Object.entries(labels)) renameField(name, label);

  const custom = currentBoolean('custom_mode');
  const instrumental = currentBoolean('instrumental');
  setVisible('custom_mode', true);
  setVisible('instrumental', true);
  setVisible('prompt', !custom || !instrumental);
  for (const name of [
    'style',
    'title',
    'negative_tags',
    'vocal_gender',
    'style_weight',
    'weirdness_constraint',
    'audio_weight',
  ]) {
    setVisible(name, custom);
  }
}

function enhance() {
  ensureMusicLauncher();
  ensureMusicProduct();
  hardenSunoStudio();
}

root?.addEventListener(
  'click',
  (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const music = target.closest('[data-complete-tool="music"]');
    if (!(music instanceof HTMLButtonElement)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    root.querySelector('[data-nav="create"]')?.click();
    queueMicrotask(() => {
      enhance();
      root.querySelector('[data-suno-product-head]')?.scrollIntoView({
        behavior: 'smooth',
        block: 'start',
      });
    });
  },
  true,
);

root?.addEventListener(
  'change',
  (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement)) return;
    if (!['custom_mode', 'instrumental'].includes(target.dataset.field ?? '')) return;
    queueMicrotask(hardenSunoStudio);
  },
  true,
);

const observer = new MutationObserver(() => queueMicrotask(enhance));
if (root) {
  observer.observe(root, { childList: true, subtree: true });
  enhance();
}
