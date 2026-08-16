const root = document.getElementById('app');

const TTS_SLUG = 'elevenlabs-turbo-2-5';
const TTS_TITLE = 'ElevenLabs Turbo 2.5';

function ensureVoiceLauncher() {
  const button = root?.querySelector('[data-complete-tool="voice"]');
  if (!(button instanceof HTMLButtonElement)) return;
  button.disabled = false;
  button.removeAttribute('aria-disabled');
  button.classList.remove('is-planned');
  button.classList.add('is-ready');
  const status = button.querySelector('.complete-tool__status');
  if (status) status.textContent = 'Доступно';
}

function ensureAudioProduct() {
  if (!root || root.querySelector('[data-tts-product-head]')) return;
  const headings = [...root.querySelectorAll('.product-head h2')];
  const videoHeading = headings.find((item) => item.textContent?.trim() === 'Видео');
  const videoHead = videoHeading?.closest('.product-head');
  const videoList = videoHead?.nextElementSibling;
  if (!videoHead || !videoList?.classList.contains('model-list')) return;

  const head = document.createElement('div');
  head.className = 'product-head';
  head.dataset.ttsProductHead = '1';
  head.innerHTML = '<h2>Аудио</h2><small>1</small>';

  const list = document.createElement('div');
  list.className = 'model-list';
  list.dataset.ttsProductList = '1';
  list.innerHTML = `
    <button class="model-row grunge-lite" data-model="${TTS_SLUG}">
      <span class="model-glyph">♫</span>
      <div>
        <strong>${TTS_TITLE}</strong>
        <small>ElevenLabs · цена из backend</small>
        <p>Озвучка · быстрый multilingual TTS</p>
      </div>
      <span>›</span>
    </button>
  `;
  videoList.insertAdjacentElement('afterend', head);
  head.insertAdjacentElement('afterend', list);
}

function hardenTtsStudio() {
  const title = root?.querySelector('.studio-header h1')?.textContent?.trim();
  if (title !== TTS_TITLE) return;
  const launch = root?.querySelector('.launch-card');
  const submit = launch?.querySelector('[data-submit]');
  const costText = launch?.querySelector('strong')?.textContent?.trim() ?? '';
  const amount = Number(costText.replace(/[^0-9.-]/g, ''));
  if (submit instanceof HTMLButtonElement && (!Number.isFinite(amount) || amount <= 0)) {
    submit.disabled = true;
    submit.textContent = 'Цена не опубликована';
    if (!launch?.querySelector('[data-tts-price-warning]')) {
      const warning = document.createElement('p');
      warning.dataset.ttsPriceWarning = '1';
      warning.textContent = 'Запуск появится после публикации активной цены администратором.';
      launch?.append(warning);
    }
  }

  const labelMap = new Map([
    ['Text', 'Текст'],
    ['Voice', 'Голос / Voice ID'],
    ['Stability', 'Стабильность'],
    ['Similarity Boost', 'Сходство голоса'],
    ['Style', 'Стиль'],
    ['Speed', 'Скорость'],
    ['Timestamps', 'Таймкоды'],
    ['Previous Text', 'Предыдущий контекст'],
    ['Next Text', 'Следующий контекст'],
    ['Language Code', 'Код языка'],
  ]);
  for (const label of root?.querySelectorAll('.schema-card label') ?? []) {
    const first = label.firstElementChild;
    if (!first) continue;
    const current = first.textContent?.replace('*', '').trim() ?? '';
    const replacement = labelMap.get(current);
    if (replacement) {
      const required = first.querySelector('.required-mark')?.outerHTML ?? '';
      first.innerHTML = `${replacement}${required}`;
    }
  }
}

function enhance() {
  ensureVoiceLauncher();
  ensureAudioProduct();
  hardenTtsStudio();
}

root?.addEventListener(
  'click',
  (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const voice = target.closest('[data-complete-tool="voice"]');
    if (!(voice instanceof HTMLButtonElement)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    root.querySelector('[data-nav="create"]')?.click();
    queueMicrotask(() => {
      enhance();
      root.querySelector('[data-tts-product-head]')?.scrollIntoView({
        behavior: 'smooth',
        block: 'start',
      });
    });
  },
  true,
);

const observer = new MutationObserver(() => queueMicrotask(enhance));
if (root) {
  observer.observe(root, { childList: true, subtree: true });
  enhance();
}
