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

let starsToken = null;
let starsBusy = false;

function esc(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

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
      subtitle: 'Откройте раздел кошелька для актуальных условий',
    });
  }
  if (!text.includes('Пополнить баланс')) {
    addProfileRow(settings, {
      title: 'Пополнить баланс',
      subtitle: 'Оплата Telegram Stars доступна в кошельке',
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
    <button type="button" class="is-ready" data-stars-topup>
      ＋ Пополнить баланс
      <small>Telegram Stars · безопасное зачисление</small>
    </button>
    <button type="button" class="is-ready" data-nav="tariff">
      Тарифы
      <small>Актуальные условия и пакеты</small>
    </button>
  `;
  hero.insertAdjacentElement('afterend', actions);
}

function starsPanel() {
  let panel = root?.querySelector('[data-stars-panel]');
  if (panel) return panel;
  const actions = root?.querySelector('[data-complete-wallet-actions]');
  if (!actions) return null;
  panel = document.createElement('section');
  panel.className = 'complete-stars-panel';
  panel.dataset.starsPanel = '1';
  actions.insertAdjacentElement('afterend', panel);
  return panel;
}

function starsStatus(message, kind = 'info') {
  const panel = starsPanel();
  if (!panel) return;
  panel.className = `complete-stars-panel ${kind}`;
  panel.innerHTML = `<p>${esc(message)}</p>`;
}

async function starsAuth(force = false) {
  if (starsToken && !force) return starsToken;
  if (!tg?.initData) throw new Error('Откройте Happy Fox внутри Telegram для оплаты.');
  const response = await fetch('/v1/miniapp/auth', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ init_data: tg.initData }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || !data?.access_token) {
    throw new Error(data?.detail || data?.message || 'Не удалось подтвердить Telegram-профиль.');
  }
  starsToken = data.access_token;
  return starsToken;
}

async function starsApi(path, options = {}, retryAuth = true) {
  const token = await starsAuth(false);
  const headers = new Headers(options.headers ?? {});
  headers.set('Authorization', `Bearer ${token}`);
  const response = await fetch(`/v1/miniapp${path}`, { ...options, headers });
  const data = await response.json().catch(() => ({}));
  if (response.status === 401 && retryAuth) {
    await starsAuth(true);
    return starsApi(path, options, false);
  }
  if (!response.ok) {
    throw new Error(data?.detail || data?.message || data?.error || `HTTP ${response.status}`);
  }
  return data;
}

function invoiceKey(packageCode) {
  const storageKey = `foxgen:stars:invoice:${packageCode}`;
  try {
    let value = sessionStorage.getItem(storageKey);
    if (!value) {
      value = `stars:miniapp:${crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`}`;
      sessionStorage.setItem(storageKey, value);
    }
    return { storageKey, value };
  } catch {
    return {
      storageKey: null,
      value: `stars:miniapp:${crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`}`,
    };
  }
}

function clearInvoiceKey(storageKey) {
  if (!storageKey) return;
  try {
    sessionStorage.removeItem(storageKey);
  } catch {
    // Storage is an optimization; backend idempotency remains authoritative.
  }
}

async function showStarPackages() {
  if (starsBusy) return;
  starsBusy = true;
  starsStatus('Загружаю доступные пакеты…');
  try {
    const data = await starsApi('/payments/stars/packages');
    const items = Array.isArray(data?.items) ? data.items : [];
    const panel = starsPanel();
    if (!panel) return;
    if (!items.length) {
      starsStatus('Пакеты Telegram Stars пока не опубликованы администратором.', 'warning');
      return;
    }
    panel.className = 'complete-stars-panel';
    panel.innerHTML = `
      <div class="complete-stars-head">
        <strong>Пополнение Telegram Stars</strong>
        <small>Кредиты зачисляются только после подтверждённой оплаты Telegram</small>
      </div>
      <div class="complete-stars-grid">
        ${items.map((item) => `
          <button type="button" data-stars-package="${esc(item.code)}">
            <strong>${esc(item.title)}</strong>
            <span>${Number(item.total_credits_units ?? item.credits_units).toLocaleString('ru-RU')} CREDIT</span>
            ${Number(item.bonus_units || 0) > 0
              ? `<small>+${Number(item.bonus_units).toLocaleString('ru-RU')} бонус CREDIT</small>`
              : ''}
            <small>⭐ ${Number(item.stars_amount).toLocaleString('ru-RU')}</small>
          </button>
        `).join('')}
      </div>
    `;
  } catch (error) {
    starsStatus(error?.message ?? error, 'error');
  } finally {
    starsBusy = false;
  }
}

async function createStarInvoice(packageCode) {
  if (starsBusy) return;
  starsBusy = true;
  const pending = invoiceKey(packageCode);
  starsStatus('Создаю защищённый счёт Telegram Stars…');
  try {
    const invoice = await starsApi('/payments/stars/invoices', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': pending.value,
      },
      body: JSON.stringify({ package_code: packageCode }),
    });
    if (!invoice?.invoice_url) throw new Error('Сервер не вернул ссылку оплаты.');
    starsStatus('Счёт готов. Подтвердите оплату в Telegram.');
    if (tg?.openInvoice) {
      tg.openInvoice(invoice.invoice_url, (status) => {
        if (status === 'paid') {
          clearInvoiceKey(pending.storageKey);
          starsStatus('Оплата подтверждена Telegram. Обновляю баланс…', 'success');
          window.setTimeout(() => window.location.reload(), 1200);
        } else if (status === 'failed') {
          starsStatus('Telegram не завершил оплату. Повторное списание не выполнялось.', 'error');
        } else if (status === 'cancelled') {
          starsStatus('Оплата отменена. Этот же счёт можно открыть повторно.', 'warning');
        }
      });
      return;
    }
    window.open(invoice.invoice_url, '_blank', 'noopener,noreferrer');
  } catch (error) {
    starsStatus(error?.message ?? error, 'error');
  } finally {
    starsBusy = false;
  }
}

function injectGenerationDownload() {
  const actions = root?.querySelector('.action-grid');
  if (!actions || actions.querySelector('[data-open-result]')) return;

  const media = root.querySelector(
    '.generation-media img[src], .generation-media video[src], .generation-media audio[src]',
  );
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

  const topup = target.closest('[data-stars-topup]');
  if (topup instanceof HTMLButtonElement) {
    event.preventDefault();
    void showStarPackages();
    return;
  }

  const starsPackage = target.closest('[data-stars-package]');
  if (starsPackage instanceof HTMLButtonElement) {
    event.preventDefault();
    const packageCode = starsPackage.dataset.starsPackage;
    if (packageCode) void createStarInvoice(packageCode);
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
