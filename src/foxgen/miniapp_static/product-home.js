const root = document.getElementById('app');
const tg = window.Telegram?.WebApp ?? null;
const API_TIMEOUT_MS = 10000;

const SPECIAL_OPENERS = {
  'kling-3-motion-control': '[data-motion-open]',
  'suno-v5-extend': '[data-suno-extend-open]',
  'suno-v5-upload-cover': '[data-suno-cover-action]',
  'suno-v5-upload-extend': '[data-suno-upload-extend-action]',
};

const CATEGORY_META = {
  all: { title: 'Все', icon: '✦' },
  image: { title: 'Фото', icon: '◉' },
  video: { title: 'Видео', icon: '▶' },
  voice: { title: 'Голос', icon: '◖' },
  music: { title: 'Музыка', icon: '♫' },
  motion: { title: 'Motion', icon: '◆' },
};

const state = {
  token: null,
  bootstrap: globalThis.__FOXGEN_BOOTSTRAP__ ?? null,
  loading: false,
  error: null,
  filter: 'all',
  query: '',
  community: false,
};

function esc(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function formatCredits(value) {
  return Number(value ?? 0).toLocaleString('ru-RU');
}

async function fetchBounded(input, options = {}) {
  const controller = options.signal ? null : new AbortController();
  const timeoutId = controller ? setTimeout(() => controller.abort(), API_TIMEOUT_MS) : null;
  try {
    return await fetch(input, controller ? { ...options, signal: controller.signal } : options);
  } catch (error) {
    if (error?.name === 'AbortError') {
      throw new Error('Сервер Happy Fox отвечает слишком долго. Повтори попытку.');
    }
    throw error;
  } finally {
    if (timeoutId !== null) clearTimeout(timeoutId);
  }
}

function priceMap() {
  return new Map(
    (state.bootstrap?.prices ?? []).map((item) => [item.model_slug, Number(item.amount_units ?? 0)]),
  );
}

function categoryFor(model) {
  const slug = String(model?.slug ?? '');
  const family = String(model?.family ?? '').toLowerCase();
  if (slug === 'kling-3-motion-control') return 'motion';
  if (slug.startsWith('suno-') || family === 'suno') return 'music';
  if (model?.media_kind === 'audio') return 'voice';
  if (model?.media_kind === 'video') return 'video';
  if (model?.media_kind === 'image') return 'image';
  return 'all';
}

function visibleModels() {
  const seen = new Set();
  return [...(state.bootstrap?.models ?? [])]
    .filter((model) => model && model.enabled !== false && model.enabled_for_submission !== false)
    .filter((model) => {
      const key = model.ui_key || model.slug;
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .sort((a, b) => Number(a.rank ?? 99) - Number(b.rank ?? 99));
}

function categoryCount(category) {
  if (category === 'all') return visibleModels().length;
  return visibleModels().filter((model) => categoryFor(model) === category).length;
}

function minCategoryPrice(category) {
  const prices = priceMap();
  const values = visibleModels()
    .filter((model) => category === 'all' || categoryFor(model) === category)
    .map((model) => prices.get(model.slug) ?? 0)
    .filter((value) => Number.isFinite(value) && value > 0);
  return values.length ? Math.min(...values) : null;
}

async function authenticate(force = false) {
  if (state.token && !force) return state.token;
  if (!tg?.initData) throw new Error('Откройте Happy Fox внутри Telegram.');
  const response = await fetchBounded('/v1/miniapp/auth', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ init_data: tg.initData }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || !data?.access_token) {
    throw new Error(data?.detail || data?.message || 'Не удалось подтвердить Telegram-профиль.');
  }
  state.token = data.access_token;
  return state.token;
}

async function api(path, options = {}, retry = true) {
  const token = await authenticate(false);
  const headers = new Headers(options.headers ?? {});
  headers.set('Authorization', `Bearer ${token}`);
  const response = await fetchBounded(`/v1/miniapp${path}`, { ...options, headers });
  const data = response.status === 204 ? null : await response.json().catch(() => ({}));
  if (response.status === 401 && retry) {
    await authenticate(true);
    return api(path, options, false);
  }
  if (!response.ok) {
    throw new Error(data?.detail || data?.message || data?.error || `HTTP ${response.status}`);
  }
  return data;
}

async function loadBootstrap() {
  if (state.bootstrap || state.loading || !tg?.initData) return;
  state.loading = true;
  state.error = null;
  try {
    state.bootstrap = await api('/bootstrap');
  } catch (error) {
    state.error = error?.message ?? String(error);
  } finally {
    state.loading = false;
    renderCatalog(true);
  }
}

function navButton(screen) {
  return root?.querySelector(`.hf-nav button[data-nav="${screen}"]`) ?? null;
}

function enhanceBottomNav() {
  const catalog = navButton('feed');
  if (!(catalog instanceof HTMLButtonElement)) return;
  const icon = catalog.querySelector('span');
  const label = catalog.querySelector('small');
  if (icon) icon.textContent = '▦';
  if (label) label.textContent = 'Каталог';
  catalog.dataset.productCatalogNav = '1';
}

function topbarHtml(main) {
  return main?.querySelector('.hf-top')?.outerHTML ?? '';
}

function categoryButton(category) {
  const meta = CATEGORY_META[category];
  const count = categoryCount(category);
  const price = minCategoryPrice(category);
  return `
    <button class="product-home-category ${state.filter === category ? 'active' : ''}" type="button" data-home-filter="${category}">
      <span class="product-home-category__icon">${meta.icon}</span>
      <span>
        <strong>${meta.title}</strong>
        <small>${count} ${count === 1 ? 'модель' : 'моделей'}${price ? ` · от ${formatCredits(price)} ●` : ''}</small>
      </span>
    </button>
  `;
}

function modelCard(model) {
  const category = categoryFor(model);
  const price = priceMap().get(model.slug) ?? 0;
  const meta = CATEGORY_META[category] ?? CATEGORY_META.all;
  const recommendations = (model.recommended_for ?? []).slice(0, 2).join(' · ');
  const special = SPECIAL_OPENERS[model.slug];
  const action = special
    ? `data-home-special="${esc(model.slug)}"`
    : `data-model="${esc(model.slug)}"`;
  const searchable = `${model.title ?? ''} ${model.family ?? ''} ${model.slug ?? ''} ${recommendations}`.toLowerCase();
  return `
    <button
      class="product-home-model"
      type="button"
      ${action}
      data-home-model-card
      data-home-category="${category}"
      data-home-search="${esc(searchable)}"
    >
      <span class="product-home-model__icon">${meta.icon}</span>
      <span class="product-home-model__body">
        <strong>${esc(model.title || model.slug)}</strong>
        <small>${esc(model.family || 'AI')}${price > 0 ? ` · ${formatCredits(price)} ●` : ' · цена не опубликована'}</small>
        <em>${esc(recommendations || (special ? 'Специализированный сценарий' : 'Динамические параметры из backend'))}</em>
      </span>
      <span class="product-home-model__arrow">›</span>
    </button>
  `;
}

function loadingBlock() {
  return `
    <div class="product-home-loading" aria-live="polite">
      <span></span><span></span><span></span>
      <p>Загружаю доступные модели и цены…</p>
    </div>
  `;
}

function catalogBody() {
  if (state.loading && !state.bootstrap) return loadingBlock();
  if (state.error && !state.bootstrap) {
    return `
      <div class="product-home-error">
        <strong>Каталог временно не загрузился</strong>
        <p>${esc(state.error)}</p>
        <button type="button" data-home-retry>Повторить</button>
      </div>
    `;
  }

  const models = visibleModels();
  const available = Number(state.bootstrap?.balance?.available_units ?? 0);
  return `
    <section class="product-home-hero grunge-card">
      <div class="product-home-hero__copy">
        <span class="stamp">AI CATALOG / LIVE</span>
        <h1>Что создаём <i>сегодня?</i></h1>
        <p>Фото, видео, голос, музыка и Motion Control — реальные активные сценарии из backend, без фейковых кнопок.</p>
      </div>
      <div class="product-home-balance">
        <small>Баланс</small>
        <strong>${formatCredits(available)} <b>●</b></strong>
      </div>
      <button class="hf-primary product-home-quick" type="button" data-quick-start>⚡ Быстрый запуск по файлу</button>
      <div class="product-home-hero__links">
        <button type="button" data-nav="create">Все инструменты</button>
        <button type="button" data-home-community>Сообщество</button>
      </div>
    </section>

    <section class="product-home-section">
      <div class="section-head product-home-section__head">
        <div>
          <span class="stamp">DIRECTIONS</span>
          <h2>Категории</h2>
        </div>
        <small>${models.length} доступно</small>
      </div>
      <div class="product-home-categories">
        ${['image', 'video', 'voice', 'music', 'motion'].map(categoryButton).join('')}
      </div>
    </section>

    <section class="product-home-section">
      <div class="section-head product-home-section__head">
        <div>
          <span class="stamp">MODELS / LIVE</span>
          <h2>Модели</h2>
        </div>
        <button class="product-home-reset" type="button" data-home-filter="all">Все</button>
      </div>
      <label class="product-home-search">
        <span>⌕</span>
        <input type="search" data-home-search-input placeholder="Найти модель или задачу" value="${esc(state.query)}">
      </label>
      <div class="product-home-models">
        ${models.length ? models.map(modelCard).join('') : '<p class="product-home-empty">Backend пока не опубликовал модели для запуска.</p>'}
      </div>
      <p class="product-home-filter-empty" data-home-filter-empty hidden>По этому фильтру ничего не найдено.</p>
    </section>

    <section class="product-home-shortcuts">
      <button type="button" data-nav="works"><span>▦</span><strong>Мои работы</strong><small>Результаты и генерации</small></button>
      <button type="button" data-nav="wallet"><span>●</span><strong>Баланс</strong><small>Пополнение и операции</small></button>
      <button type="button" data-nav="profile"><span>◎</span><strong>Профиль</strong><small>Публикации и настройки</small></button>
    </section>
  `;
}

function applyFilters() {
  const main = root?.querySelector('main[data-product-catalog="1"]');
  if (!main) return;
  const query = state.query.trim().toLowerCase();
  let shown = 0;
  for (const card of main.querySelectorAll('[data-home-model-card]')) {
    const category = card.dataset.homeCategory || 'all';
    const searchable = card.dataset.homeSearch || '';
    const visibleByCategory = state.filter === 'all' || category === state.filter;
    const visibleByQuery = !query || searchable.includes(query);
    card.hidden = !(visibleByCategory && visibleByQuery);
    if (!card.hidden) shown += 1;
  }
  for (const button of main.querySelectorAll('[data-home-filter]')) {
    button.classList.toggle('active', button.dataset.homeFilter === state.filter);
  }
  const empty = main.querySelector('[data-home-filter-empty]');
  if (empty) empty.hidden = shown !== 0 || visibleModels().length === 0;
}

function renderCatalog(force = false) {
  if (state.community) return;
  const main = root?.querySelector('main.hf-page');
  if (!main) return;
  const stamp = main.querySelector('.hf-hero .stamp')?.textContent?.trim() ?? '';
  const isFeed = stamp === 'COMMUNITY / LIVE';
  const alreadyCatalog = main.dataset.productCatalog === '1';
  if (!isFeed && !alreadyCatalog) return;
  if (alreadyCatalog && !force) {
    applyFilters();
    return;
  }

  const topbar = topbarHtml(main);
  main.dataset.productCatalog = '1';
  main.innerHTML = `${topbar}${catalogBody()}`;
  applyFilters();
  if (!state.bootstrap && !state.loading && tg?.initData) void loadBootstrap();
}

function injectCommunityBack() {
  const hero = root?.querySelector('main.hf-page .hf-hero');
  const stamp = hero?.querySelector('.stamp')?.textContent?.trim();
  if (!hero || stamp !== 'COMMUNITY / LIVE' || hero.querySelector('[data-home-back-catalog]')) return;
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'product-home-community-back';
  button.dataset.homeBackCatalog = '1';
  button.textContent = '← В каталог';
  hero.append(button);
}

function waitFor(selector, timeoutMs = 1600) {
  return new Promise((resolve) => {
    const start = performance.now();
    const check = () => {
      const node = root?.querySelector(selector);
      if (node) {
        resolve(node);
        return;
      }
      if (performance.now() - start >= timeoutMs) {
        resolve(null);
        return;
      }
      requestAnimationFrame(check);
    };
    check();
  });
}

async function openSpecial(slug) {
  const selector = SPECIAL_OPENERS[slug];
  if (!selector) return;
  navButton('create')?.click();
  const target = await waitFor(selector);
  if (target instanceof HTMLElement) {
    target.click();
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    return;
  }
  try {
    tg?.showAlert?.('Сценарий сейчас недоступен. Откройте раздел «Создать» и повторите попытку.');
  } catch {
    window.alert('Сценарий сейчас недоступен.');
  }
}

function showCommunity() {
  const button = navButton('feed');
  if (!button) return;
  button.click();
  state.community = true;
  queueMicrotask(() => {
    injectCommunityBack();
  });
}

function showCatalog() {
  state.community = false;
  const button = navButton('feed');
  if (!button) return;
  button.click();
  queueMicrotask(() => renderCatalog(true));
}

function syncSharedBootstrap(value = globalThis.__FOXGEN_BOOTSTRAP__) {
  if (!value || value === state.bootstrap) return;
  state.bootstrap = value;
  state.loading = false;
  state.error = null;
}

function enhance() {
  syncSharedBootstrap();
  enhanceBottomNav();
  if (state.community) {
    injectCommunityBack();
    return;
  }
  renderCatalog(false);
}

window.addEventListener('foxgen:bootstrap', (event) => {
  syncSharedBootstrap(event.detail);
  renderCatalog(true);
});

root?.addEventListener(
  'click',
  (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;

    const catalogNav = target.closest('[data-product-catalog-nav]');
    if (catalogNav) {
      state.community = false;
      return;
    }

    const community = target.closest('[data-home-community]');
    if (community) {
      event.preventDefault();
      event.stopImmediatePropagation();
      showCommunity();
      return;
    }

    const back = target.closest('[data-home-back-catalog]');
    if (back) {
      event.preventDefault();
      event.stopImmediatePropagation();
      showCatalog();
      return;
    }

    const retry = target.closest('[data-home-retry]');
    if (retry) {
      event.preventDefault();
      state.bootstrap = null;
      state.error = null;
      void loadBootstrap();
      return;
    }

    const filter = target.closest('[data-home-filter]');
    if (filter) {
      event.preventDefault();
      event.stopImmediatePropagation();
      state.filter = filter.dataset.homeFilter || 'all';
      applyFilters();
      return;
    }

    const special = target.closest('[data-home-special]');
    if (special) {
      event.preventDefault();
      event.stopImmediatePropagation();
      void openSpecial(special.dataset.homeSpecial);
    }
  },
  true,
);

root?.addEventListener('input', (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement) || !target.hasAttribute('data-home-search-input')) return;
  state.query = target.value;
  applyFilters();
});

const observer = new MutationObserver(() => queueMicrotask(enhance));
if (root) {
  observer.observe(root, { childList: true, subtree: true });
  queueMicrotask(enhance);
}
