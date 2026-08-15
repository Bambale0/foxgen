const root = document.getElementById('app');
const tg = window.Telegram?.WebApp ?? null;

const PRODUCT_BUTTONS = [
  {
    key: 'quick',
    title: 'Быстрый запуск',
    subtitle: 'Файл → подходящая модель',
    icon: '⚡',
    ready: true,
  },
  {
    key: 'image',
    title: 'Создать фото',
    subtitle: 'Все активные image-модели',
    icon: '◉',
    ready: true,
  },
  {
    key: 'video',
    title: 'Создать видео',
    subtitle: 'Все активные video-модели',
    icon: '▶',
    ready: true,
  },
  {
    key: 'voice',
    title: 'Озвучка / голос',
    subtitle: 'TTS, диалоги, обработка аудио',
    icon: '◖',
    ready: false,
  },
  {
    key: 'music',
    title: 'Музыка / Suno',
    subtitle: 'Песни, lyrics, extend, stems, MIDI',
    icon: '♫',
    ready: false,
  },
  {
    key: 'motion',
    title: 'Motion Control',
    subtitle: 'Движение, avatar, talking avatar',
    icon: '◆',
    ready: false,
  },
  {
    key: 'prompt',
    title: 'Промпты AI',
    subtitle: 'Улучшение и сборка промпта',
    icon: '✦',
    ready: false,
  },
  {
    key: 'gemini-omni',
    title: 'Gemini Omni',
    subtitle: 'Мультимодальные сценарии',
    icon: '◇',
    ready: false,
  },
  {
    key: 'assistant',
    title: 'AI-помощник',
    subtitle: 'Диалог, память и работа с черновиками',
    icon: '◎',
    ready: false,
  },
  {
    key: 'boring-work',
    title: 'Скучная работа',
    subtitle: 'Пакетные и рутинные задачи',
    icon: '▦',
    ready: false,
  },
];

function productButton(item) {
  const status = item.ready ? 'Доступно' : 'В реализации';
  return `
    <button
      class="complete-tool ${item.ready ? 'is-ready' : 'is-planned'}"
      type="button"
      data-complete-tool="${item.key}"
      ${item.ready ? '' : 'disabled aria-disabled="true"'}
    >
      <span class="complete-tool__icon" aria-hidden="true">${item.icon}</span>
      <span class="complete-tool__copy">
        <strong>${item.title}</strong>
        <small>${item.subtitle}</small>
      </span>
      <span class="complete-tool__status">${status}</span>
    </button>
  `;
}

function injectCreateLauncher() {
  const quickStart = root?.querySelector('[data-quick-start]');
  if (!quickStart || root.querySelector('[data-complete-launcher]')) return;

  const hero = quickStart.closest('.hf-hero');
  if (!hero) return;

  const section = document.createElement('section');
  section.className = 'complete-launcher section';
  section.dataset.completeLauncher = '1';
  section.innerHTML = `
    <div class="section-head complete-launcher__head">
      <div>
        <span class="stamp">ALL TOOLS</span>
        <h2>Все инструменты</h2>
      </div>
      <small>Незавершённые функции не запускаются и не списывают кредиты</small>
    </div>
    <div class="complete-tool-grid">
      ${PRODUCT_BUTTONS.map(productButton).join('')}
    </div>
  `;
  hero.insertAdjacentElement('afterend', section);
}

function addProfileRow(container, { title, subtitle }) {
  const button = document.createElement('button');
  button.type = 'button';
  button.disabled = true;
  button.setAttribute('aria-disabled', 'true');
  button.className = 'complete-settings-planned';
  button.innerHTML = `${title} <small>${subtitle}</small>`;
  container.append(button);
}

function injectProfileActions() {
  const settings = root?.querySelector('.settings-list');
  if (!settings || settings.dataset.completeMenu === '1') return;
  settings.dataset.completeMenu = '1';

  const text = settings.textContent ?? '';
  if (!text.includes('Тарифы')) {
    addProfileRow(settings, {
      title: 'Тарифы',
      subtitle: 'User-safe тарифный API ещё не подключён',
    });
  }
  if (!text.includes('Пополнить баланс')) {
    addProfileRow(settings, {
      title: 'Пополнить баланс',
      subtitle: 'Появится вместе с безопасным invoice flow',
    });
  }
}

function injectWalletActions() {
  const hero = root?.querySelector('.wallet-hero');
  if (!hero || root.querySelector('[data-complete-wallet-actions]')) return;

  const actions = document.createElement('div');
  actions.className = 'complete-wallet-actions';
  actions.dataset.completeWalletActions = '1';
  actions.innerHTML = `
    <button type="button" disabled aria-disabled="true">
      ＋ Пополнить баланс
      <small>Invoice flow в реализации</small>
    </button>
    <button type="button" disabled aria-disabled="true">
      Тарифы
      <small>Тарифный API в реализации</small>
    </button>
  `;
  hero.insertAdjacentElement('afterend', actions);
}

function injectGenerationDownload() {
  const actions = root?.querySelector('.action-grid');
  if (!actions || actions.querySelector('[data-open-result]')) return;

  const media = root.querySelector('.generation-media img[src], .generation-media video[src], .generation-media audio[src]');
  const src = media?.getAttribute('src');
  if (!src) return;

  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'accent';
  button.dataset.openResult = src;
  button.textContent = 'Скачать / открыть результат';
  actions.prepend(button);
}

function scrollToProduct(title) {
  const headings = [...root.querySelectorAll('.product-head h2')];
  const target = headings.find((heading) => heading.textContent?.trim() === title);
  target?.closest('.product-head')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function handleToolClick(button) {
  const key = button.dataset.completeTool;
  if (key === 'quick') {
    root.querySelector('[data-quick-start]')?.click();
    return;
  }
  if (key === 'image') {
    scrollToProduct('Изображения');
    return;
  }
  if (key === 'video') {
    scrollToProduct('Видео');
  }
}

function openResult(url) {
  try {
    if (tg?.openLink) {
      tg.openLink(url, { try_instant_view: false });
      return;
    }
  } catch {
    // Browser fallback below.
  }
  window.open(url, '_blank', 'noopener,noreferrer');
}

function enhance() {
  injectCreateLauncher();
  injectProfileActions();
  injectWalletActions();
  injectGenerationDownload();
}

root?.addEventListener('click', (event) => {
  const target = event.target;
  if (!(target instanceof Element)) return;

  const tool = target.closest('[data-complete-tool]');
  if (tool instanceof HTMLButtonElement && !tool.disabled) {
    event.preventDefault();
    handleToolClick(tool);
    return;
  }

  const result = target.closest('[data-open-result]');
  if (result instanceof HTMLButtonElement) {
    event.preventDefault();
    const url = result.dataset.openResult;
    if (url) openResult(url);
  }
});

const observer = new MutationObserver(() => queueMicrotask(enhance));
if (root) {
  observer.observe(root, { childList: true, subtree: true });
  enhance();
}
