const root = document.getElementById('app');
const tg = window.Telegram?.WebApp ?? null;

const SPECIAL_MODEL_OPENERS = {
  'suno-v5-extend': '[data-suno-extend-open]',
  'suno-v5-upload-cover': '[data-suno-cover-action]',
  'suno-v5-upload-extend': '[data-suno-upload-extend-action]',
  'kling-3-motion-control': '[data-motion-open]',
};

const TERMINAL = new Set(['succeeded', 'failed', 'cancelled']);
let customScreen = null;
let modelFilter = 'all';
let modelQuery = '';
let initialSurfaceResolved = false;
let token = null;
let publications = null;
let publicationsBusy = false;
let scheduled = false;

function bootstrap() {
  return globalThis.__FOXGEN_BOOTSTRAP__ ?? null;
}

function esc(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function fmt(value) {
  return Number(value ?? 0).toLocaleString('ru-RU');
}

function activeModels() {
  return [...(bootstrap()?.models ?? [])]
    .filter((item) => item && item.enabled !== false)
    .sort((a, b) => Number(a.rank ?? 99) - Number(b.rank ?? 99) || String(a.title).localeCompare(String(b.title), 'ru'));
}

function priceFor(slug) {
  const item = (bootstrap()?.prices ?? []).find((row) => row?.model_slug === slug && row?.enabled !== false);
  return Number(item?.amount_units ?? 0);
}

function modelCategory(model) {
  const slug = String(model?.slug ?? '');
  const family = String(model?.family ?? '').toLowerCase();
  if (slug === 'kling-3-motion-control') return 'motion';
  if (slug.startsWith('suno-') || family === 'suno') return 'music';
  if (model?.media_kind === 'audio') return 'voice';
  if (model?.media_kind === 'video') return 'video';
  return 'image';
}

function modelGlyph(model) {
  return {image: '◉', video: '▶', voice: '◖', music: '♫', motion: '◆'}[modelCategory(model)] ?? '✦';
}

function categoryTitle(category) {
  return {all: 'Все', image: 'Фото', video: 'Видео', voice: 'Голос', music: 'Музыка', motion: 'Motion'}[category] ?? 'Все';
}

function user() {
  return bootstrap()?.user ?? {};
}

function balance() {
  return bootstrap()?.balance ?? {available_units: 0};
}

function avatarHtml() {
  const value = user();
  if (value.photo_url) return `<img class="avatar" src="${esc(value.photo_url)}" alt="Аватар">`;
  return '<div class="avatar" aria-hidden="true"></div>';
}

function topbar() {
  return `<header class="topbar"><button class="topbar__close" type="button" data-backend-close>Закрыть</button><div class="topbar__brand"><strong>Happy <span>Fox</span></strong><small>AI STUDIO</small></div><div class="topbar__action"></div></header>`;
}

function navButton({key, label, glyph, parity, active}) {
  const action = parity ? `data-nav="${key}"` : `data-backend-nav="${key}"`;
  return `<button class="nav-button ${active === key ? 'active' : ''}" type="button" ${action}><span>${glyph}</span><span>${label}</span></button>`;
}

function bottomNav(active = currentParityScreen()) {
  const items = [
    {key: 'home', label: 'Главная', glyph: '⌂'},
    {key: 'models', label: 'Модели', glyph: '✦'},
    {key: 'create', label: 'Создать', glyph: '＋', parity: true},
    {key: 'works', label: 'Работы', glyph: '▦', parity: true},
    {key: 'wallet', label: 'Баланс', glyph: '●', parity: true},
    {key: 'profile', label: 'Профиль', glyph: '◎', parity: true},
  ];
  return `<nav class="bottom-nav backend-parity-nav"><div class="bottom-nav__inner">${items.map((item) => navButton({...item, active})).join('')}</div></nav>`;
}

function currentParityScreen() {
  if (customScreen) return customScreen;
  const current = root?.querySelector('.hf-nav button.active[data-nav], .backend-parity-nav .nav-button.active[data-nav]');
  return current?.dataset.nav ?? 'home';
}

function shortcut({screen, title, subtitle, glyph, custom = false}) {
  const action = custom ? `data-backend-nav="${screen}"` : `data-nav="${screen}"`;
  return `<button class="backend-shortcut" type="button" ${action}><span>${glyph}</span><strong>${title}</strong><small>${subtitle}</small></button>`;
}

function modelTile(model) {
  const price = priceFor(model.slug);
  return `<button class="backend-model-tile" type="button" data-backend-model="${esc(model.slug)}"><span class="backend-model-icon">${modelGlyph(model)}</span><strong>${esc(model.title || model.slug)}</strong><small>${esc(model.family || 'AI')} · ${price > 0 ? `${fmt(price)} ●` : 'цена не опубликована'}</small></button>`;
}

function renderHome() {
  if (!root) return;
  customScreen = 'home';
  const models = activeModels();
  const recent = bootstrap()?.recent ?? [];
  const active = recent.filter((item) => !TERMINAL.has(item?.status)).length;
  const value = user();
  root.innerHTML = `
    <main class="backend-parity-page page" data-backend-surface="home">
      ${topbar()}
      <section class="hero-user">
        <div class="user-chip">${avatarHtml()}<div class="user-copy"><strong>${esc(value.display_name || value.username || 'Happy Fox')}${value.is_premium ? '<span class="badge-pro">PRO</span>' : ''}</strong><small>${value.username ? `@${esc(value.username)}` : 'Happy Fox'}</small></div></div>
        <button class="balance-card" type="button" data-nav="wallet"><div class="balance-card__copy"><small>Доступно</small><strong>${fmt(balance().available_units)} <span class="coin">●</span></strong></div><span>›</span></button>
      </section>
      <section class="backend-home-hero">
        <span class="backend-parity-stamp">CREATE / BACKEND LIVE</span>
        <h1>Все модели. <i>Одна студия.</i></h1>
        <p>Каталог, параметры, цены и доступность приходят из backend. Здесь нет отдельной старой Mini App и нет фейковых генераторов.</p>
        <button class="primary-button" type="button" data-backend-nav="models">Выбрать модель · ${models.length}</button>
      </section>
      ${active ? `<div class="notice">Сейчас выполняется задач: <strong>${active}</strong>. Статус доступен в «Работы».</div>` : ''}
      <section class="section">
        <div class="section-head"><h2>Быстрый старт</h2><button class="section-link" type="button" data-backend-nav="models">Все ${models.length}</button></div>
        <div class="backend-model-strip">${models.slice(0, 7).map(modelTile).join('')}</div>
      </section>
      <section class="section">
        <div class="section-head"><h2>Весь функционал</h2><small>backend</small></div>
        <div class="backend-home-grid">
          ${shortcut({screen: 'create', title: 'Создать', subtitle: 'Все генераторы и schema-driven параметры', glyph: '✦'})}
          ${shortcut({screen: 'feed', title: 'Сообщество', subtitle: 'Лента, лайки, комментарии и Remix', glyph: '◫'})}
          ${shortcut({screen: 'works', title: 'Работы', subtitle: 'История, статусы, отмена и публикация', glyph: '▦'})}
          ${shortcut({screen: 'wallet', title: 'Баланс', subtitle: 'CREDIT, Stars, цены, история и промокод', glyph: '●'})}
          ${shortcut({screen: 'profile', title: 'Профиль', subtitle: 'Публичный профиль и публикации', glyph: '◎'})}
          ${shortcut({screen: 'references', title: 'Референсы', subtitle: 'Память изображений для генераций', glyph: '▧'})}
          ${shortcut({screen: 'tariff', title: 'Тарифы', subtitle: 'Опубликованные сервером условия', glyph: '₽'})}
          ${shortcut({screen: 'partner', title: 'Партнёры', subtitle: 'Рефералы, доход и заявки на выплату', glyph: '↗'})}
          ${shortcut({screen: 'support', title: 'Поддержка', subtitle: 'Тикеты, ответы и история', glyph: '?'})}
          ${shortcut({screen: 'models', title: 'Все модели', subtitle: 'Фото, видео, голос, музыка и Motion', glyph: '◇', custom: true})}
        </div>
      </section>
    </main>
    ${bottomNav('home')}
  `;
}

function modelSearchText(model) {
  return `${model.title ?? ''} ${model.family ?? ''} ${model.slug ?? ''} ${(model.recommended_for ?? []).join(' ')}`.toLowerCase();
}

function filteredModels() {
  const query = modelQuery.trim().toLowerCase();
  return activeModels().filter((model) => {
    if (modelFilter !== 'all' && modelCategory(model) !== modelFilter) return false;
    return !query || modelSearchText(model).includes(query);
  });
}

function modelCard(model) {
  const price = priceFor(model.slug);
  const category = modelCategory(model);
  const recommendations = (model.recommended_for ?? []).slice(0, 2).join(' · ');
  const special = SPECIAL_MODEL_OPENERS[model.slug] ? 'спец. сценарий' : categoryTitle(category);
  return `<button class="backend-model-card" type="button" data-backend-model="${esc(model.slug)}"><span class="backend-model-card__icon">${modelGlyph(model)}</span><span><strong>${esc(model.title || model.slug)}</strong><small>${esc(model.family || 'AI')} · ${esc(special)}</small><em>${esc(recommendations || model.slug)}</em></span><span class="backend-model-card__price"><b>${price > 0 ? `${fmt(price)} ●` : '—'}</b><small>${esc(model.tier || 'standard')}</small></span></button>`;
}

function renderModels() {
  if (!root) return;
  customScreen = 'models';
  const all = activeModels();
  const rows = filteredModels();
  const categories = ['all', 'image', 'video', 'voice', 'music', 'motion'];
  root.innerHTML = `
    <main class="backend-parity-page page" data-backend-surface="models">
      ${topbar()}
      <div class="backend-model-page-head"><div><span class="backend-parity-stamp">MODELS / LIVE</span><h1>Все модели</h1><p>${all.length} активных backend-сценариев. Нажатие ведёт либо в schema-driven студию, либо в специализированный безопасный workflow.</p></div></div>
      <label class="backend-model-search"><span>⌕</span><input type="search" data-backend-model-search value="${esc(modelQuery)}" placeholder="Модель, семейство или задача"></label>
      <div class="backend-model-tabs">${categories.map((category) => `<button class="${modelFilter === category ? 'active' : ''}" type="button" data-backend-filter="${category}">${categoryTitle(category)} · ${category === 'all' ? all.length : all.filter((item) => modelCategory(item) === category).length}</button>`).join('')}</div>
      <div class="backend-model-catalog">${rows.length ? rows.map(modelCard).join('') : '<div class="backend-pub-empty">По этому фильтру моделей нет.</div>'}</div>
    </main>
    ${bottomNav('models')}
  `;
  root.querySelector('[data-backend-model-search]')?.focus({preventScroll: true});
}

function invokeParityNav(screen) {
  if (!root) return;
  customScreen = null;
  const button = document.createElement('button');
  button.type = 'button';
  button.hidden = true;
  button.dataset.nav = screen;
  root.append(button);
  button.click();
  button.remove();
}

function invokeParityModel(slug) {
  if (!root) return;
  const button = document.createElement('button');
  button.type = 'button';
  button.hidden = true;
  button.dataset.model = slug;
  root.append(button);
  button.click();
  button.remove();
}

function waitFor(selector, timeoutMs = 5000) {
  return new Promise((resolve) => {
    const deadline = Date.now() + timeoutMs;
    const check = () => {
      const node = root?.querySelector(selector);
      if (node) {
        resolve(node);
        return;
      }
      if (Date.now() >= deadline) {
        resolve(null);
        return;
      }
      window.setTimeout(check, 50);
    };
    check();
  });
}

function notify(message) {
  try {
    if (tg?.showAlert) {
      tg.showAlert(message);
      return;
    }
  } catch {}
  window.alert(message);
}

async function openBackendModel(slug) {
  customScreen = null;
  invokeParityNav('create');
  await waitFor('main.hf-page', 1800);
  const specialSelector = SPECIAL_MODEL_OPENERS[slug];
  if (specialSelector) {
    const special = await waitFor(specialSelector, 5000);
    if (special instanceof HTMLElement) {
      special.click();
      return;
    }
    notify('Специализированный сценарий не успел загрузиться. Закройте и снова откройте раздел «Создать».');
    return;
  }
  invokeParityModel(slug);
}

function startParam() {
  return tg?.initDataUnsafe?.start_param || new URLSearchParams(location.search).get('tgWebAppStartParam') || '';
}

function decorateNav() {
  if (!root || customScreen) return;
  if (root.querySelector('.backend-parity-nav')) return;
  const old = root.querySelector('.hf-nav');
  if (!old) return;
  const current = old.querySelector('button.active[data-nav]')?.dataset.nav ?? 'create';
  old.outerHTML = bottomNav(current);
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
  if (!response.ok || !data?.access_token) throw new Error(data?.detail || data?.message || 'Не удалось подтвердить Telegram-профиль.');
  token = data.access_token;
  return token;
}

async function api(path, options = {}, retry = true) {
  const bearer = await auth(false);
  const headers = new Headers(options.headers ?? {});
  headers.set('Authorization', `Bearer ${bearer}`);
  const response = await fetch(`/v1/miniapp${path}`, {...options, headers});
  const data = response.status === 204 ? null : await response.json().catch(() => ({}));
  if (response.status === 401 && retry) {
    await auth(true);
    return api(path, options, false);
  }
  if (!response.ok) throw new Error(data?.detail || data?.message || data?.error || `HTTP ${response.status}`);
  return data;
}

function publicationManagerHtml() {
  const items = Array.isArray(publications) ? publications : [];
  return `<section class="backend-pub-manager" data-backend-pub-manager><h2>Управление публикациями</h2><p>Backend поддерживает публикацию и снятие с ленты/профиля. Здесь доступны оба действия.</p><div class="backend-pub-list">${items.length ? items.map((item) => `<div class="backend-pub-row" data-backend-publication="${esc(item.id)}"><div><strong>${esc(item.model_slug || 'AI')} · ${item.scope === 'feed' ? 'Лента' : 'Профиль'}</strong><small>${esc(item.generation_id)}</small></div><button type="button" data-backend-unpublish="${esc(item.generation_id)}" data-backend-scope="${esc(item.scope)}">Снять</button></div>`).join('') : '<div class="backend-pub-empty">Активных публикаций нет.</div>'}</div></section>`;
}

function paintPublicationManager() {
  const existing = root?.querySelector('[data-backend-pub-manager]');
  if (existing && publications) existing.outerHTML = publicationManagerHtml();
}

async function injectPublicationManager() {
  if (!root || customScreen || !tg?.initData) return;
  const profile = root.querySelector('.profile-hero');
  if (!profile || root.querySelector('[data-backend-pub-manager]')) return;
  const anchor = root.querySelector('.profile-grid') || profile;
  const host = document.createElement('section');
  host.className = 'backend-pub-manager';
  host.dataset.backendPubManager = '1';
  host.innerHTML = '<h2>Управление публикациями</h2><p>Загружаю публикации…</p>';
  anchor.insertAdjacentElement('afterend', host);
  if (publications) {
    paintPublicationManager();
    return;
  }
  if (publicationsBusy) return;
  publicationsBusy = true;
  try {
    const data = await api('/me/publications?limit=50');
    publications = Array.isArray(data?.items) ? data.items : [];
    paintPublicationManager();
  } catch (error) {
    const current = root.querySelector('[data-backend-pub-manager]');
    if (current) current.innerHTML = `<h2>Управление публикациями</h2><p>${esc(error?.message ?? error)}</p>`;
  } finally {
    publicationsBusy = false;
  }
}

async function unpublish(button) {
  const generation = button.dataset.backendUnpublish;
  const scope = button.dataset.backendScope;
  if (!generation || !scope) return;
  button.disabled = true;
  try {
    await api(`/generations/${encodeURIComponent(generation)}/publications/${encodeURIComponent(scope)}`, {method: 'DELETE'});
    publications = (publications ?? []).filter((item) => !(String(item.generation_id) === generation && item.scope === scope));
    paintPublicationManager();
  } catch (error) {
    button.disabled = false;
    notify(error?.message ?? String(error));
  }
}

function scheduleEnhance() {
  if (scheduled) return;
  scheduled = true;
  queueMicrotask(() => {
    scheduled = false;
    decorateNav();
    void injectPublicationManager();
  });
}

root?.addEventListener('click', (event) => {
  const target = event.target;
  if (!(target instanceof Element)) return;

  const close = target.closest('[data-backend-close]');
  if (close) {
    event.preventDefault();
    event.stopImmediatePropagation();
    try { tg?.close?.(); } catch {}
    return;
  }

  const custom = target.closest('[data-backend-nav]');
  if (custom) {
    event.preventDefault();
    event.stopImmediatePropagation();
    if (custom.dataset.backendNav === 'home') renderHome();
    if (custom.dataset.backendNav === 'models') renderModels();
    return;
  }

  const model = target.closest('[data-backend-model]');
  if (model) {
    event.preventDefault();
    event.stopImmediatePropagation();
    const slug = model.dataset.backendModel;
    if (slug) void openBackendModel(slug);
    return;
  }

  const filter = target.closest('[data-backend-filter]');
  if (filter) {
    event.preventDefault();
    event.stopImmediatePropagation();
    modelFilter = filter.dataset.backendFilter || 'all';
    renderModels();
    return;
  }

  const remove = target.closest('[data-backend-unpublish]');
  if (remove instanceof HTMLButtonElement) {
    event.preventDefault();
    event.stopImmediatePropagation();
    void unpublish(remove);
    return;
  }

  if (target.closest('[data-nav]')) customScreen = null;
}, true);

root?.addEventListener('input', (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement) || !target.hasAttribute('data-backend-model-search')) return;
  modelQuery = target.value;
  const cursor = target.selectionStart;
  renderModels();
  const input = root.querySelector('[data-backend-model-search]');
  if (input instanceof HTMLInputElement) {
    input.focus({preventScroll: true});
    if (cursor !== null) input.setSelectionRange(cursor, cursor);
  }
});

window.addEventListener('foxgen:bootstrap', () => {
  if (!initialSurfaceResolved) {
    initialSurfaceResolved = true;
    if (!startParam()) renderHome();
  }
  scheduleEnhance();
});

if (root && window.MutationObserver) {
  new MutationObserver(scheduleEnhance).observe(root, {childList: true, subtree: true});
}

if (bootstrap()) {
  initialSurfaceResolved = true;
  if (!startParam()) renderHome();
  scheduleEnhance();
}