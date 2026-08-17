const root = document.getElementById('app');
const tg = window.Telegram?.WebApp ?? null;

let parityToken = null;
let generationRequest = null;
let publicationRequest = null;
const unpublishBusy = new Set();

function esc(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function ensureStyles() {
  if (document.getElementById('hf-user-parity-hardening')) return;
  const style = document.createElement('style');
  style.id = 'hf-user-parity-hardening';
  style.textContent = `
    .generation-media.parity-results {
      display: grid;
      gap: 12px;
      background: transparent;
      overflow: visible;
    }
    .parity-result {
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: var(--card);
      box-shadow: var(--shadow);
    }
    .parity-result__media {
      min-height: 88px;
      background: #0b0b0b;
    }
    .parity-result__media img,
    .parity-result__media video {
      width: 100%;
      height: auto;
      max-height: 68vh;
      object-fit: contain;
      background: #050505;
    }
    .parity-result__media audio {
      width: calc(100% - 24px);
      margin: 18px 12px;
    }
    .parity-result__meta {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 11px 13px;
      color: var(--muted);
      font-size: 12px;
    }
    .parity-result__meta strong {
      color: var(--text);
      font-size: 13px;
    }
    .parity-result-count {
      margin: 0 0 10px;
      color: var(--muted);
      font-size: 12px;
    }
    .publication-media.parity-publication-results {
      display: grid;
      gap: 10px;
    }
    .publication-media.parity-publication-results audio,
    .publication-media.parity-publication-results video,
    .publication-media.parity-publication-results img {
      width: 100%;
      border-radius: 14px;
    }
    .publication-media.parity-publication-results audio {
      padding: 12px 0;
    }
  `;
  document.head.append(style);
}

async function parityAuth(force = false) {
  if (parityToken && !force) return parityToken;
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
  parityToken = data.access_token;
  return parityToken;
}

async function parityApi(path, options = {}, retryAuth = true) {
  const token = await parityAuth(false);
  const headers = new Headers(options.headers ?? {});
  headers.set('Authorization', `Bearer ${token}`);
  const response = await fetch(`/v1/miniapp${path}`, { ...options, headers });
  if (response.status === 204) return null;
  const data = await response.json().catch(() => ({}));
  if (response.status === 401 && retryAuth) {
    await parityAuth(true);
    return parityApi(path, options, false);
  }
  if (!response.ok) {
    throw new Error(data?.detail || data?.message || data?.error || `HTTP ${response.status}`);
  }
  return data;
}

function mediaKind(contentType) {
  const value = String(contentType ?? '');
  if (value.startsWith('video/')) return 'video';
  if (value.startsWith('audio/')) return 'audio';
  return 'image';
}

function formatBytes(value) {
  const bytes = Number(value ?? 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return '';
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} КБ`;
  return `${(bytes / 1024 ** 2).toFixed(1)} МБ`;
}

function renderResultMedia(media, index, total) {
  const url = esc(media?.url);
  const contentType = String(media?.content_type ?? '');
  const kind = mediaKind(contentType);
  const number = total > 1 ? `Результат ${index + 1}` : 'Результат';
  const size = formatBytes(media?.size_bytes);
  let preview = '';

  if (kind === 'video') {
    preview = `<video src="${url}" controls playsinline preload="metadata"></video>`;
  } else if (kind === 'audio') {
    preview = `<audio src="${url}" controls preload="metadata"></audio>`;
  } else {
    preview = `<img src="${url}" alt="${esc(number)}" loading="eager">`;
  }

  return `
    <article class="parity-result" data-parity-result="${index}">
      <div class="parity-result__media">${preview}</div>
      <div class="parity-result__meta">
        <strong>${esc(number)}</strong>
        <span>${esc(contentType || kind)}${size ? ` · ${esc(size)}` : ''}</span>
      </div>
    </article>
  `;
}

function generationIdFromScreen() {
  const action = root?.querySelector(
    '[data-repeat-generation],[data-publish],[data-cancel-generation],[data-parity-unpublish]',
  );
  if (!(action instanceof HTMLElement)) return null;
  return (
    action.dataset.repeatGeneration
    || action.dataset.publish
    || action.dataset.cancelGeneration
    || action.dataset.parityUnpublish
    || null
  );
}

function publicationIdFromScreen() {
  const like = root?.querySelector('.publication-full [data-like]');
  return like instanceof HTMLElement ? like.dataset.like ?? null : null;
}

function replaceResultActions(items) {
  const actions = root?.querySelector('.action-grid');
  if (!(actions instanceof HTMLElement)) return;

  for (const item of actions.querySelectorAll('[data-open-result]')) item.remove();
  const html = items
    .filter((item) => item?.url)
    .map((item, index) => `
      <button
        type="button"
        class="${index === 0 ? 'accent' : ''}"
        data-open-result="${esc(item.url)}"
        data-parity-result-action="${index}"
      >
        ${items.length > 1 ? `Открыть результат ${index + 1}` : 'Скачать / открыть результат'}
      </button>
    `)
    .join('');
  actions.insertAdjacentHTML('afterbegin', html);
}

async function enhanceGenerationResults() {
  const container = root?.querySelector('.generation-media');
  const succeededAction = root?.querySelector('[data-repeat-generation]');
  const id = generationIdFromScreen();
  if (
    !(container instanceof HTMLElement)
    || !(succeededAction instanceof HTMLElement)
    || !id
    || !tg?.initData
  ) {
    return;
  }
  if (container.dataset.parityGenerationId === id || generationRequest === id) return;

  generationRequest = id;
  try {
    const generation = await parityApi(`/generations/${encodeURIComponent(id)}`);
    if (generationIdFromScreen() !== id) return;

    const items = Array.isArray(generation?.media)
      ? generation.media.filter((item) => item?.url)
      : [];
    if (!items.length) return;

    container.dataset.parityGenerationId = id;
    container.classList.add('parity-results');
    container.innerHTML = `
      ${items.length > 1 ? `<p class="parity-result-count">${items.length} результата</p>` : ''}
      ${items.map((item, index) => renderResultMedia(item, index, items.length)).join('')}
    `;
    replaceResultActions(items);
    await enhancePublicationActions(id);
  } catch {
    // The canonical Mini App rendering remains usable if this progressive enhancement fails.
  } finally {
    if (generationRequest === id) generationRequest = null;
  }
}

function publicationForGeneration(items, generationId, scope) {
  return items.find(
    (item) => item?.generation_id === generationId
      && item?.scope === scope
      && item?.active !== false,
  );
}

function turnPublishIntoUnpublish(button, generationId, scope) {
  if (!(button instanceof HTMLButtonElement)) return;
  button.removeAttribute('data-publish');
  button.dataset.parityUnpublish = generationId;
  button.dataset.scope = scope;
  button.textContent = scope === 'feed' ? 'Убрать из ленты' : 'Убрать из профиля';
  button.classList.remove('accent');
}

async function enhancePublicationActions(generationId) {
  const actions = root?.querySelector('.action-grid');
  if (!(actions instanceof HTMLElement) || !tg?.initData) return;

  const publishButtons = [...actions.querySelectorAll('[data-publish][data-scope]')];
  if (!publishButtons.length) return;

  const data = await parityApi('/me/publications?limit=50');
  if (generationIdFromScreen() !== generationId) return;
  const items = Array.isArray(data?.items) ? data.items : [];

  for (const button of publishButtons) {
    if (!(button instanceof HTMLButtonElement)) continue;
    const scope = button.dataset.scope;
    if (!scope) continue;
    if (publicationForGeneration(items, generationId, scope)) {
      turnPublishIntoUnpublish(button, generationId, scope);
    }
  }
}

async function unpublish(button) {
  if (!(button instanceof HTMLButtonElement)) return;
  const generationId = button.dataset.parityUnpublish;
  const scope = button.dataset.scope;
  if (!generationId || !scope) return;

  const key = `${generationId}:${scope}`;
  if (unpublishBusy.has(key)) return;
  unpublishBusy.add(key);
  button.disabled = true;

  try {
    await parityApi(
      `/generations/${encodeURIComponent(generationId)}/publications/${encodeURIComponent(scope)}`,
      { method: 'DELETE' },
    );
    if (generationIdFromScreen() !== generationId) return;

    button.removeAttribute('data-parity-unpublish');
    button.dataset.publish = generationId;
    button.dataset.scope = scope;
    button.textContent = scope === 'feed' ? 'В ленту' : 'В профиль';
    if (scope === 'feed') button.classList.add('accent');
  } finally {
    button.disabled = false;
    unpublishBusy.delete(key);
  }
}

function enhanceProfilePayments() {
  const settings = root?.querySelector('.settings-list');
  if (!(settings instanceof HTMLElement)) return;

  const buttons = [...settings.querySelectorAll('button')];
  let topup = buttons.find((button) => button.textContent?.includes('Пополнить баланс'));
  const stale = buttons.find((button) => button.textContent?.includes('Платежи'));

  if (!topup && stale instanceof HTMLButtonElement) topup = stale;
  if (!(topup instanceof HTMLButtonElement)) return;
  if (topup.dataset.userParityTopup === '1') return;

  topup.disabled = false;
  topup.removeAttribute('aria-disabled');
  topup.dataset.starsTopup = '1';
  topup.dataset.userParityTopup = '1';
  topup.innerHTML = 'Пополнить баланс <small>Telegram Stars</small><span>›</span>';
}

function enhanceWalletCopy() {
  const notices = root?.querySelectorAll('.wallet-hero ~ .notice.grunge-lite') ?? [];
  for (const notice of notices) {
    if (!(notice instanceof HTMLElement)) continue;
    if (!notice.textContent?.includes('Пополнение не имитируется')) continue;
    notice.textContent = 'Пополнение работает через нативный Telegram Stars checkout; CREDIT зачисляется только после подтверждённой оплаты Telegram.';
  }
}

async function enhancePublicationMedia() {
  const container = root?.querySelector('.publication-full .publication-media');
  const id = publicationIdFromScreen();
  if (!(container instanceof HTMLElement) || !id || !tg?.initData) return;
  if (container.dataset.parityPublicationId === id || publicationRequest === id) return;

  publicationRequest = id;
  try {
    const publication = await parityApi(`/publications/${encodeURIComponent(id)}`);
    if (publicationIdFromScreen() !== id) return;

    const items = Array.isArray(publication?.media)
      ? publication.media.filter((item) => item?.url)
      : [];
    if (!items.length) return;

    container.dataset.parityPublicationId = id;
    container.classList.add('parity-publication-results');
    container.innerHTML = items.map((item, index) => {
      const url = esc(item.url);
      const kind = mediaKind(item.content_type);
      if (kind === 'video') {
        return `<video src="${url}" controls playsinline preload="metadata"></video>`;
      }
      if (kind === 'audio') {
        return `<audio src="${url}" controls preload="metadata"></audio>`;
      }
      return `<img src="${url}" alt="AI result ${index + 1}" loading="eager">`;
    }).join('');
  } catch {
    // Leave the base publication renderer intact on an enhancement-only failure.
  } finally {
    if (publicationRequest === id) publicationRequest = null;
  }
}

function enhance() {
  ensureStyles();
  enhanceProfilePayments();
  enhanceWalletCopy();
  void enhanceGenerationResults();
  void enhancePublicationMedia();
}

root?.addEventListener(
  'click',
  (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;

    const unpublishButton = target.closest('[data-parity-unpublish]');
    if (unpublishButton instanceof HTMLButtonElement) {
      event.preventDefault();
      event.stopImmediatePropagation();
      void unpublish(unpublishButton).catch((error) => {
        unpublishButton.disabled = false;
        try {
          tg?.showAlert?.(error?.message ?? String(error));
        } catch {
          // Telegram alert is optional.
        }
      });
      return;
    }

    const ownPublications = target.closest('[data-own-publications]');
    if (ownPublications instanceof HTMLButtonElement) {
      event.preventDefault();
      const targetSection = root.querySelector('.mini-pub-grid')?.closest('.section')
        ?? [...root.querySelectorAll('.section')].find(
          (section) => section.querySelector('.section-head h2')?.textContent?.trim() === 'Мои публикации',
        );
      targetSection?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  },
  true,
);

const observer = new MutationObserver(() => queueMicrotask(enhance));
if (root) {
  observer.observe(root, { childList: true, subtree: true });
  enhance();
}
