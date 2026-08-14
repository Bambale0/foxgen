const root = document.getElementById('app');
const picker = document.getElementById('media-picker');
const tg = window.Telegram?.WebApp ?? null;

const TERMINAL = new Set(['succeeded', 'failed', 'cancelled']);
const state = {
  token: null,
  demo: false,
  busy: false,
  uploadBusy: false,
  screen: 'home',
  stack: [],
  galleryFilter: 'all',
  bootstrap: null,
  activeGeneration: null,
  imageDraft: freshImageDraft(),
  videoDraft: freshVideoDraft(),
};

function freshImageDraft() {
  return {
    model: 'seedream-5-pro',
    prompt: '',
    aspectRatio: '16:9',
    quality: 'high',
    resolution: '1K',
    outputFormat: 'png',
    style: 'Фотореализм',
    media: [],
    idempotencyKey: randomId(),
  };
}

function freshVideoDraft() {
  return {
    model: 'seedance-2',
    type: 'text',
    prompt: '',
    aspectRatio: '16:9',
    duration: 10,
    resolution: '720p',
    generateAudio: true,
    returnLastFrame: false,
    webSearch: false,
    media: [],
    idempotencyKey: randomId(),
  };
}

const DEMO = {
  brand: 'Happy Fox',
  user: { id: 1, display_name: 'Алексей', username: 'alex_fox', photo_url: null, is_premium: true },
  balance: { available_units: 2450, reserved_units: 0, total_units: 2450, currency: 'CREDIT' },
  prices: [
    { model_slug: 'seedream-5-pro', amount_units: 10, currency: 'CREDIT' },
    { model_slug: 'seedream-5-pro-edit', amount_units: 12, currency: 'CREDIT' },
    { model_slug: 'nano-banana-2', amount_units: 7, currency: 'CREDIT' },
    { model_slug: 'nano-banana-pro', amount_units: 12, currency: 'CREDIT' },
    { model_slug: 'seedance-2', amount_units: 20, currency: 'CREDIT' },
    { model_slug: 'seedance-2-mini', amount_units: 12, currency: 'CREDIT' },
  ],
  ledger: [
    { entry_type: 'credit', available_delta: 1000, reason: 'Пополнение баланса', created_at: new Date().toISOString() },
    { entry_type: 'capture', available_delta: 0, reserved_delta: -20, reason: 'Генерация видео', created_at: new Date(Date.now() - 3600000).toISOString() },
    { entry_type: 'reserve', available_delta: -10, reserved_delta: 10, reason: 'Генерация изображения', created_at: new Date(Date.now() - 7200000).toISOString() },
  ],
  models: [
    { slug: 'seedream-5-pro', ui_key: 'seedream-5-pro', variant: 'default', title: 'Seedream 5 Pro', media_kind: 'image', enabled: true },
    { slug: 'seedream-5-pro-edit', ui_key: 'seedream-5-pro', variant: 'edit', title: 'Seedream 5 Pro Edit', media_kind: 'image', enabled: true },
    { slug: 'nano-banana-2', ui_key: 'nano-banana-2', variant: 'default', title: 'Nano Banana 2', media_kind: 'image', enabled: true },
    { slug: 'nano-banana-pro', ui_key: 'nano-banana-pro', variant: 'default', title: 'Nano Banana Pro', media_kind: 'image', enabled: true },
    { slug: 'seedance-2', ui_key: 'seedance-2', variant: 'default', title: 'Seedance 2', media_kind: 'video', enabled: true },
    { slug: 'seedance-2-mini', ui_key: 'seedance-2-mini', variant: 'default', title: 'Seedance 2 Mini', media_kind: 'video', enabled: true },
  ],
  recent: [
    demoGeneration('image', 'seedream-5-pro', 'Футуристический город на закате', 5),
    demoGeneration('video', 'seedance-2', 'Неоновая улица и спортивный автомобиль', 18),
    demoGeneration('image', 'nano-banana-pro', 'Кинематографичный портрет', 63),
    demoGeneration('image', 'nano-banana-2', 'Горный пейзаж на рассвете', 95),
  ],
};

function demoGeneration(kind, model, prompt, minutesAgo) {
  return {
    id: randomId(),
    model_slug: model,
    media_kind: kind,
    status: 'succeeded',
    prompt,
    created_at: new Date(Date.now() - minutesAgo * 60000).toISOString(),
    completed_at: new Date(Date.now() - (minutesAgo - 1) * 60000).toISOString(),
    media: [],
  };
}

function randomId() {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function esc(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function icon(name) {
  const paths = {
    home: '<path d="M3 11.5 12 4l9 7.5v8a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1v-8Z"/><path d="M9 20.5h6"/>',
    grid: '<rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><rect x="14" y="14" width="6" height="6" rx="1"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4.5 21a7.5 7.5 0 0 1 15 0"/>',
    image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m5 18 5-5 3.5 3.5L16 14l3 4"/>',
    video: '<rect x="3" y="5" width="14" height="14" rx="2"/><path d="m17 10 4-2v8l-4-2v-4Z"/>',
    wallet: '<path d="M4 7.5h14a2 2 0 0 1 2 2V18H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h12"/><path d="M16 11h5v4h-5a2 2 0 1 1 0-4Z"/>',
    spark: '<path d="m12 2 1.5 5.5L19 9l-5.5 1.5L12 16l-1.5-5.5L5 9l5.5-1.5L12 2Z"/><path d="m19 15 .7 2.3L22 18l-2.3.7L19 21l-.7-2.3L16 18l2.3-.7L19 15Z"/>',
    upload: '<path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5"/><path d="M5 14v5h14v-5"/>',
    trash: '<path d="M4 7h16M9 7V4h6v3m-9 0 1 14h10l1-14M10 11v6m4-6v6"/>',
    text: '<path d="M5 5h14M12 5v14M8 19h8"/>',
    frames: '<rect x="3" y="5" width="12" height="14" rx="2"/><path d="M9 9h12v10a2 2 0 0 1-2 2H9"/>',
    folder: '<path d="M3 7h7l2 2h9v10H3V7Z"/>',
    download: '<path d="M12 3v12m0 0-4-4m4 4 4-4"/><path d="M5 19h14"/>',
    remix: '<path d="M7 7h8a4 4 0 0 1 4 4v1"/><path d="m16 9 3 3 3-3"/><path d="M17 17H9a4 4 0 0 1-4-4v-1"/><path d="m8 15-3-3-3 3"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    back: '<path d="m15 5-7 7 7 7"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M19 13.5v-3l-2-.7-.7-1.7.9-1.9-2.1-2.1-1.9.9-1.7-.7L10.5 2h-3l-.7 2-1.7.7-1.9-.9-2.1 2.1.9 1.9-.7 1.7-2 .7v3l2 .7.7 1.7-.9 1.9 2.1 2.1 1.9-.9 1.7.7.7 2h3l.7-2 1.7-.7 1.9.9 2.1-2.1-.9-1.9.7-1.7 2-.7Z" transform="scale(.8) translate(3 3)"/>',
  };
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] ?? paths.spark}</svg>`;
}

function setupTelegram() {
  if (!tg) return;
  try {
    tg.ready();
    tg.expand();
    tg.setHeaderColor?.('#080808');
    tg.setBackgroundColor?.('#070707');
    tg.setBottomBarColor?.('#080808');
    tg.disableVerticalSwipes?.();
  } catch (_) {
    // Older Telegram clients may not expose every optional method.
  }
  tg.BackButton?.onClick(goBack);
  tg.onEvent?.('themeChanged', syncTelegramChrome);
  tg.onEvent?.('safeAreaChanged', syncTelegramChrome);
  tg.onEvent?.('contentSafeAreaChanged', syncTelegramChrome);
}

function syncTelegramChrome() {
  try {
    tg?.setHeaderColor?.('#080808');
    tg?.setBackgroundColor?.('#070707');
    tg?.setBottomBarColor?.('#080808');
  } catch (_) {}
}

function haptic(type = 'light') {
  try { tg?.HapticFeedback?.impactOccurred?.(type); } catch (_) {}
}

function notify(type = 'success') {
  try { tg?.HapticFeedback?.notificationOccurred?.(type); } catch (_) {}
}

async function init() {
  setupTelegram();
  if (tg?.initData) {
    try {
      const auth = await rawApi('/auth', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ init_data: tg.initData }),
      });
      state.token = auth.access_token;
      state.bootstrap = await api('/bootstrap');
    } catch (error) {
      renderFatal(error);
      return;
    }
  } else {
    state.demo = true;
    state.bootstrap = structuredClone(DEMO);
  }
  render();
}

async function rawApi(path, options = {}) {
  const response = await fetch(`/v1/miniapp${path}`, options);
  if (response.status === 204) return null;
  const contentType = response.headers.get('content-type') ?? '';
  const data = contentType.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) {
    const message = typeof data === 'object' && data?.detail
      ? (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail))
      : `HTTP ${response.status}`;
    throw new Error(message);
  }
  return data;
}

async function api(path, options = {}) {
  if (!state.token) throw new Error('Откройте Happy Fox внутри Telegram.');
  const headers = new Headers(options.headers ?? {});
  headers.set('Authorization', `Bearer ${state.token}`);
  return rawApi(path, { ...options, headers });
}

function renderFatal(error) {
  root.innerHTML = `<main class="page"><div class="brand-lockup" style="margin-top:22px">${brandMark()}</div><div class="notice error-card" style="margin-top:28px"><strong>Не удалось открыть Happy Fox</strong><br>${esc(error?.message ?? error)}</div><button class="primary-button" data-action="reload">Повторить</button></main>`;
}

function brandMark() {
  return `<div class="fox-mark" aria-hidden="true"><svg viewBox="0 0 64 64"><path d="M8 10 23 18 32 12l9 6 15-8-4 27-20 17L12 37 8 10Z" fill="currentColor"/><path d="m19 27 9 5-6 4-3-9Zm26 0-9 5 6 4 3-9Z" fill="#090909"/><path d="m25 40 7 4 7-4-7 10-7-10Z" fill="#090909"/></svg></div><div><strong>Happy <span>Fox</span></strong><small>AI-студия в Telegram</small></div>`;
}

function topbar(action = '') {
  return `<header class="topbar"><button class="topbar__close" data-action="close">Закрыть</button><div class="topbar__brand"><strong>Happy <span style="color:var(--orange)">Fox</span></strong><small>мини-приложение</small></div><div class="topbar__action">${action}</div></header>`;
}

function bottomNav() {
  const active = state.screen.startsWith('create') ? 'create' : state.screen === 'generation' ? 'gallery' : state.screen;
  return `<nav class="bottom-nav" aria-label="Основная навигация"><div class="bottom-nav__inner">
    ${navButton('home', 'Главная', icon('home'), active === 'home')}
    ${navButton('gallery', 'Галерея', icon('grid'), active === 'gallery')}
    <button class="nav-button nav-button--create ${active === 'create' ? 'active' : ''}" data-action="open-create"><span class="nav-icon-wrap">${icon('plus')}</span><span>Создать</span></button>
    ${navButton('profile', 'Профиль', icon('user'), active === 'profile')}
  </div></nav>`;
}

function navButton(screen, label, svg, active) {
  return `<button class="nav-button ${active ? 'active' : ''}" data-nav="${screen}">${svg}<span>${label}</span></button>`;
}

function render() {
  if (!state.bootstrap) return;
  updateBackButton();
  const screen = {
    home: renderHome,
    'create-image': renderImageCreate,
    'create-video': renderVideoCreate,
    gallery: renderGallery,
    profile: renderProfile,
    generation: renderGeneration,
  }[state.screen] ?? renderHome;
  root.innerHTML = `<div class="toast-stack" id="toast-stack"></div>${screen()}${bottomNav()}`;
}

function updateBackButton() {
  const visible = state.screen !== 'home';
  try {
    if (visible) tg?.BackButton?.show(); else tg?.BackButton?.hide();
    const dirty = (state.screen === 'create-image' && (state.imageDraft.prompt || state.imageDraft.media.length)) ||
      (state.screen === 'create-video' && (state.videoDraft.prompt || state.videoDraft.media.length));
    if (dirty) tg?.enableClosingConfirmation?.(); else tg?.disableClosingConfirmation?.();
  } catch (_) {}
}

function user() { return state.bootstrap?.user ?? DEMO.user; }
function balance() { return state.bootstrap?.balance ?? DEMO.balance; }
function recent() { return state.bootstrap?.recent ?? []; }
function models() { return state.bootstrap?.models ?? []; }
function prices() { return state.bootstrap?.prices ?? []; }

function displayName() {
  return user().display_name || user().username || 'друг';
}

function avatarHtml() {
  const url = user().photo_url;
  return url ? `<img class="avatar" src="${esc(url)}" alt="Аватар">` : '<div class="avatar" aria-hidden="true"></div>';
}

function balanceCompact() {
  return `<div class="balance-card"><div class="balance-card__copy"><small>Баланс</small><strong>${formatCredits(balance().available_units)} <span class="coin">●</span></strong></div><button class="balance-plus" data-action="topup" aria-label="Пополнить">+</button></div>`;
}

function renderHome() {
  const works = recent().slice(0, 6);
  return `<main class="page">${topbar('•••')}
    ${state.demo ? '<div class="notice">Демо-режим интерфейса. Для запуска генераций откройте Happy Fox внутри Telegram.</div>' : ''}
    <section class="hero-user"><div class="user-chip">${avatarHtml()}<div class="user-copy"><strong>${esc(displayName())}${user().is_premium ? '<span class="badge-pro">PRO</span>' : ''}</strong><small>${user().username ? '@' + esc(user().username) : 'Happy Fox'}</small></div></div>${balanceCompact()}</section>
    <section class="section"><div class="section-head"><h1>Что создаём сегодня?</h1></div><div class="create-grid">
      <button class="create-card create-card--image" data-action="open-image"><span class="sparkles">✦ ·</span><span class="create-card__title">Создать изображение</span><span class="create-card__icon">${icon('image')}</span></button>
      <button class="create-card create-card--video" data-action="open-video"><span class="sparkles">· ✦</span><span class="create-card__title">Создать видео</span><span class="create-card__icon">${icon('video')}</span></button>
    </div></section>
    <section class="section"><div class="section-head"><h2>Быстрый доступ</h2></div><div class="quick-grid">
      <button class="quick-card" data-nav="gallery">${icon('grid')}<span>Мои работы</span></button>
      <button class="quick-card" data-action="open-image">${icon('spark')}<span>Новая идея</span></button>
      <button class="quick-card" data-nav="profile">${icon('wallet')}<span>Баланс</span></button>
    </div></section>
    <section class="section"><div class="section-head"><h2>Популярные модели</h2><button class="section-link" data-action="open-create">Все модели ›</button></div>${renderPopularModels()}</section>
    <section class="section"><div class="section-head"><h2>Недавние работы</h2><button class="section-link" data-nav="gallery">Смотреть все ›</button></div>${works.length ? `<div class="media-grid">${works.map(renderMediaTile).join('')}</div>` : emptyState('grid','Пока пусто','Первая генерация появится здесь сразу после запуска.')}</section>
  </main>`;
}

function renderPopularModels() {
  const wanted = ['seedream-5-pro', 'seedance-2', 'nano-banana-2'];
  return `<div class="model-strip">${wanted.map(key => {
    const item = models().find(m => m.ui_key === key && m.variant !== 'edit') || { ui_key:key, title:modelTitle(key), media_kind:key.startsWith('seedance')?'video':'image' };
    const action = item.media_kind === 'video' ? 'open-video' : 'open-image';
    const iconClass = key.includes('banana') ? 'banana' : item.media_kind === 'video' ? 'video' : '';
    return `<button class="model-tile" data-action="${action}" data-prefill-model="${esc(key)}"><span class="model-icon ${iconClass}">${key.includes('banana') ? '🍌' : '◉'}</span><span class="model-copy"><strong>${esc(item.title)}</strong><small>${item.media_kind === 'video' ? 'Видео' : 'Изображения'}</small></span></button>`;
  }).join('')}</div>`;
}

function renderMediaTile(item) {
  const media = item.media?.[0];
  const isVideo = item.media_kind === 'video';
  const preview = media?.url
    ? (isVideo ? `<video src="${esc(media.url)}" muted playsinline preload="metadata"></video>` : `<img src="${esc(media.url)}" alt="${esc(item.prompt || 'Результат')}">`)
    : '<div class="media-card__fallback"></div>';
  return `<button class="media-card" data-action="open-generation" data-generation-id="${esc(item.id)}">${preview}<span class="media-card__status ${item.status === 'succeeded' ? 'ok' : ''}">${statusLabel(item.status)}</span><span class="media-card__meta"><span>${isVideo ? 'Видео' : 'Изображение'}</span><span>${relativeTime(item.created_at)}</span></span></button>`;
}

function renderImageCreate() {
  const d = state.imageDraft;
  const imageModels = ['seedream-5-pro', 'nano-banana-2', 'nano-banana-pro'];
  const cost = currentImagePrice();
  return `<main class="page">${topbar('<button class="topbar__action" data-action="reset-image">Сбросить</button>')}
    <div class="section-head"><div><h1 class="screen-title">Создание изображения</h1><p class="screen-subtitle">Модель, референс и точные настройки в одном экране</p></div><span class="step-label">Шаг 1 из 3</span></div>
    <div class="stepper"><span class="stepper__dot active"></span><span class="stepper__dot"></span><span class="stepper__dot"></span></div>
    <section class="section"><div class="section-head"><h2>Выберите модель</h2><span class="section-link">Лучшие для фото</span></div><div class="model-strip">${imageModels.map(key => renderModelSelector(key, d.model === key, 'image')).join('')}</div></section>
    <section class="section"><div class="form-label"><strong>Референс <span class="subtle">(необязательно)</span></strong><small>${d.media.length}/6</small></div>${renderUploadZone('image')}${renderReferences(d.media)}</section>
    <section class="section"><div class="form-label"><strong>Промпт</strong><small>${d.prompt.length} / 3500</small></div><textarea class="prompt-box" data-input="image-prompt" maxlength="3500" placeholder="Опишите изображение: сюжет, свет, стиль, детали…">${esc(d.prompt)}</textarea></section>
    <section class="section"><div class="form-label"><strong>Настройки</strong><small>Под вашу задачу</small></div><div class="field-row field-row--3">
      ${selectField('Соотношение','image-aspect',['1:1','16:9','9:16','4:3','3:4','3:2','2:3','21:9'],d.aspectRatio)}
      ${selectField('Качество','image-quality',['basic','high'],d.quality,{basic:'Стандарт',high:'Высокое'})}
      ${selectField('Стиль','image-style',['Фотореализм','Кино','Арт','3D','Аниме'],d.style)}
    </div>${d.model.includes('banana') ? `<div class="field-row" style="margin-top:8px">${selectField('Разрешение','image-resolution',['1K','2K','4K'],d.resolution)}${selectField('Формат','image-format',['png','jpg'],d.outputFormat,{png:'PNG',jpg:'JPG'})}</div>` : ''}</section>
    <div class="sticky-cta"><button class="primary-button" data-action="submit-image" ${state.busy ? 'disabled' : ''}>${state.busy ? 'Запускаем…' : `Создать изображение · ${cost} ●`}</button><div class="cost-line">Баланс: <strong>${formatCredits(balance().available_units)} ●</strong></div></div>
  </main>`;
}

function renderVideoCreate() {
  const d = state.videoDraft;
  const cost = priceFor(d.model);
  return `<main class="page">${topbar('<button class="topbar__action" data-action="reset-video">Сбросить</button>')}
    <div class="section-head"><div><h1 class="screen-title">Создание видео</h1><p class="screen-subtitle">Выберите сценарий — настройки меняются под него</p></div><span class="step-label">Шаг 1 из 3</span></div>
    <div class="stepper"><span class="stepper__dot active"></span><span class="stepper__dot"></span><span class="stepper__dot"></span></div>
    <section class="section"><div class="section-head"><h2>Выберите модель</h2></div><div class="model-strip">${['seedance-2','seedance-2-mini'].map(key => renderModelSelector(key,d.model===key,'video')).join('')}</div></section>
    <section class="section"><div class="form-label"><strong>Тип генерации</strong><small>4 сценария</small></div><div class="type-grid">
      ${videoTypeCard('text','Текст','Только описание',icon('text'))}
      ${videoTypeCard('first_frame','Первый кадр','Старт из изображения',icon('image'))}
      ${videoTypeCard('first_last','Первый + последний','Контроль начала и финала',icon('frames'))}
      ${videoTypeCard('references','Референсы','Фото, видео или аудио',icon('folder'))}
    </div></section>
    ${d.type !== 'text' ? `<section class="section"><div class="form-label"><strong>${d.type === 'references' ? 'Референсы' : 'Кадры'}</strong><small>${d.media.length}/${d.type === 'first_frame' ? 1 : d.type === 'first_last' ? 2 : 6}</small></div>${renderUploadZone('video')}${renderReferences(d.media)}</section>` : ''}
    <section class="section"><div class="form-label"><strong>Промпт</strong><small>${d.prompt.length} / 3500</small></div><textarea class="prompt-box" data-input="video-prompt" maxlength="3500" placeholder="Опишите сцену, движение камеры, атмосферу…">${esc(d.prompt)}</textarea></section>
    <section class="section"><div class="form-label"><strong>Настройки</strong><small>Seedance</small></div><div class="field-row">${selectField('Длительность','video-duration',[5,10,15],d.duration,Object.fromEntries([5,10,15].map(v=>[v,`${v} сек`])))}${selectField('Соотношение','video-aspect',['16:9','9:16','1:1'],d.aspectRatio)}</div>
      <div class="toggle-list">${toggleRow('video-audio','Аудио','Сгенерировать звук',d.generateAudio)}${toggleRow('video-last','Последний кадр','Вернуть финальный кадр',d.returnLastFrame)}${toggleRow('video-web','Веб-поиск','Использовать актуальные данные',d.webSearch)}</div>
    </section>
    <div class="sticky-cta"><button class="primary-button" data-action="submit-video" ${state.busy ? 'disabled' : ''}>${state.busy ? 'Запускаем…' : `Создать видео · ${cost} ●`}</button><div class="cost-line">Баланс: <strong>${formatCredits(balance().available_units)} ●</strong></div></div>
  </main>`;
}

function renderModelSelector(key, selected, kind) {
  const item = models().find(m => m.ui_key === key && m.variant !== 'edit') || { title:modelTitle(key) };
  const summary = {
    'seedream-5-pro':'Лучшее качество',
    'nano-banana-2':'Быстро и точно',
    'nano-banana-pro':'Максимальная детализация',
    'seedance-2':'Максимальное качество',
    'seedance-2-mini':'Быстрее генерация',
  }[key] ?? 'AI-модель';
  const cls = key.includes('banana') ? 'banana' : kind === 'video' ? 'video' : '';
  return `<button class="model-tile ${selected ? 'selected' : ''}" data-action="select-${kind}-model" data-model="${esc(key)}"><span class="model-icon ${cls}">${key.includes('banana') ? '🍌' : '◉'}</span><span class="model-copy"><strong>${esc(item.title)}</strong><small>${summary}</small></span></button>`;
}

function videoTypeCard(type,title,summary,svg) {
  return `<button class="type-card ${state.videoDraft.type === type ? 'active' : ''}" data-action="video-type" data-video-type="${type}">${svg}<strong>${title}</strong><small>${summary}</small></button>`;
}

function selectField(label,key,options,value,labels={}) {
  return `<div class="field"><label>${label}</label><select data-select="${key}">${options.map(option => `<option value="${esc(option)}" ${String(option) === String(value) ? 'selected' : ''}>${esc(labels[option] ?? option)}</option>`).join('')}</select></div>`;
}

function toggleRow(action,title,summary,on) {
  return `<div class="toggle-row"><div class="toggle-copy"><strong>${title}</strong><small>${summary}</small></div><button class="switch ${on ? 'on' : ''}" data-action="${action}" role="switch" aria-checked="${on}"></button></div>`;
}

function renderUploadZone(kind) {
  const d = kind === 'image' ? state.imageDraft : state.videoDraft;
  let accept = 'PNG, JPG, WEBP';
  if (kind === 'video') {
    accept = d.type === 'references' ? 'Фото, MP4/WEBM или аудио' : 'PNG, JPG, WEBP';
  }
  return `<button class="upload-zone ${state.uploadBusy ? 'loading' : ''}" data-action="pick-media" data-upload-kind="${kind}" ${state.uploadBusy ? 'disabled' : ''}>${icon('upload')}<span><strong>${state.uploadBusy ? 'Загружаем…' : 'Загрузить файл'}</strong><small>${accept} · до 50 МБ</small></span></button>`;
}

function renderReferences(items) {
  if (!items.length) return '';
  return `<div class="reference-list">${items.map((item,index)=>`<div class="reference-item"><div class="reference-thumb">${item.url && item.kind === 'image' ? `<img src="${esc(item.url)}" alt="Референс">` : item.kind === 'video' && item.url ? `<video src="${esc(item.url)}" muted preload="metadata"></video>` : ''}</div><div class="reference-copy"><strong>${referenceLabel(item.kind,index)}</strong><small>${item.source === 'generation' ? 'Из вашей галереи' : 'Загружено приватно'}</small></div><button class="icon-button danger" data-action="remove-reference" data-reference-index="${index}">${icon('trash')}</button></div>`).join('')}</div>`;
}

function referenceLabel(kind,index) {
  if (state.screen === 'create-video' && state.videoDraft.type === 'first_last') return index === 0 ? 'Первый кадр' : 'Последний кадр';
  return kind === 'image' ? 'Изображение' : kind === 'video' ? 'Видео' : 'Аудио';
}

function renderGallery() {
  const all = recent();
  const filtered = state.galleryFilter === 'all' ? all : all.filter(item => item.media_kind === state.galleryFilter);
  return `<main class="page">${topbar('⌕')}<div class="section-head"><h1 class="screen-title">Галерея</h1><span class="section-link">${all.length} работ</span></div>
    <div class="tabs"><button class="tab ${state.galleryFilter==='all'?'active':''}" data-action="gallery-filter" data-filter="all">Все</button><button class="tab ${state.galleryFilter==='image'?'active':''}" data-action="gallery-filter" data-filter="image">Изображения</button><button class="tab ${state.galleryFilter==='video'?'active':''}" data-action="gallery-filter" data-filter="video">Видео</button></div>
    ${filtered.length ? `<div class="gallery-list">${filtered.map(renderGalleryCard).join('')}</div>` : emptyState('grid','Ничего не найдено','Попробуйте другой фильтр или создайте новую работу.')}
  </main>`;
}

function renderGalleryCard(item) {
  const media = item.media?.[0];
  const isVideo = item.media_kind === 'video';
  const preview = media?.url ? (isVideo ? `<video src="${esc(media.url)}" controls playsinline preload="metadata"></video>` : `<img src="${esc(media.url)}" alt="${esc(item.prompt || 'Результат')}">`) : '<div class="gallery-preview__fallback"></div>';
  const actions = item.status === 'succeeded' ? `<div class="gallery-actions"><button class="gallery-action" data-action="remix" data-generation-id="${esc(item.id)}">Ремикс</button><button class="gallery-action accent" data-action="open-generation" data-generation-id="${esc(item.id)}">Открыть</button><button class="gallery-action" data-action="download" data-generation-id="${esc(item.id)}">Скачать</button></div>` : `<div class="gallery-actions"><button class="gallery-action accent" data-action="open-generation" data-generation-id="${esc(item.id)}">Статус</button></div>`;
  return `<article class="gallery-card"><div class="gallery-preview">${preview}<span class="gallery-status">${statusLabel(item.status)}</span><span class="gallery-kind">${isVideo ? 'Видео' : 'Изображение'}</span></div><div class="gallery-body"><div class="gallery-title">${esc(item.prompt || modelTitle(item.model_slug))}</div><div class="gallery-meta">${esc(modelTitle(item.model_slug))} · ${relativeTime(item.created_at)}</div>${actions}</div></article>`;
}

function renderProfile() {
  const ledger = state.bootstrap?.ledger ?? [];
  return `<main class="page">${topbar('✎')}<section class="profile-card"><div class="profile-header">${avatarHtml()}<div class="profile-header__copy"><strong>${esc(displayName())}${user().is_premium ? '<span class="badge-pro">PRO</span>' : ''}</strong><small>${user().username ? '@'+esc(user().username) : 'Пользователь Happy Fox'}</small></div></div></section>
    <section class="wallet-panel"><div><small>Ваш баланс</small><strong>${formatCredits(balance().available_units)} <span class="coin">●</span></strong></div><button class="small-orange-button" data-action="topup">+ Пополнить</button></section>
    <section class="section"><div class="section-head"><h2>История операций</h2><span class="section-link">Последние</span></div>${ledger.length ? `<div class="ledger">${ledger.map(renderLedger).join('')}</div>` : emptyState('wallet','Операций пока нет','Пополнения и списания появятся здесь.')}</section>
    <section class="section"><div class="section-head"><h2>Настройки аккаунта</h2></div><div class="settings-list"><div class="settings-row"><span>Личные данные</span><span>›</span></div><div class="settings-row"><span>Безопасность</span><span>›</span></div><div class="settings-row"><span>Уведомления</span><span>›</span></div><div class="settings-row"><span>Язык</span><span>Русский</span></div></div></section>
  </main>`;
}

function renderLedger(item) {
  const delta = Number(item.available_delta ?? 0);
  const captured = item.entry_type === 'capture' ? Number(item.reserved_delta ?? 0) : 0;
  const amount = delta || captured;
  const positive = amount > 0;
  const label = {
    credit:'Пополнение', debit:'Списание', reserve:'Резерв генерации', capture:'Генерация оплачена', release:'Возврат резерва', refund:'Возврат средств', adjustment:'Корректировка'
  }[item.entry_type] ?? 'Операция';
  return `<div class="ledger-row"><span class="ledger-icon">${positive ? '+' : '●'}</span><span class="ledger-copy"><strong>${label}</strong><small>${relativeTime(item.created_at)}</small></span><span class="ledger-amount ${positive ? 'plus':'minus'}">${amount > 0 ? '+' : ''}${formatCredits(amount)} ●</span></div>`;
}

function renderGeneration() {
  const item = state.activeGeneration;
  if (!item) return `<main class="page">${topbar()}${emptyState('clock','Загрузка статуса','Получаем данные генерации…')}</main>`;
  const media = item.media?.[0];
  const done = item.status === 'succeeded';
  const failed = item.status === 'failed' || item.status === 'cancelled';
  return `<main class="page">${topbar()}<div class="section-head"><div><h1 class="screen-title">${done ? 'Готово!' : failed ? 'Генерация остановлена' : 'Создаём…'}</h1><p class="screen-subtitle">${statusDescription(item.status)}</p></div><span class="media-card__status ${done ? 'ok':''}">${statusLabel(item.status)}</span></div>
    <section class="gallery-card" style="margin-top:18px"><div class="gallery-preview">${media?.url ? (item.media_kind === 'video' ? `<video src="${esc(media.url)}" controls playsinline></video>` : `<img src="${esc(media.url)}" alt="Результат">`) : '<div class="gallery-preview__fallback"></div>'}</div><div class="gallery-body"><div class="gallery-title">${esc(item.prompt || modelTitle(item.model_slug))}</div><div class="gallery-meta">${esc(modelTitle(item.model_slug))}</div></div></section>
    ${done ? `<div class="button-row"><button class="secondary-button" data-action="remix" data-generation-id="${esc(item.id)}">Ремикс</button><button class="primary-button" data-action="download" data-generation-id="${esc(item.id)}">Скачать</button></div><button class="secondary-button" style="margin-top:8px" data-action="open-create">Создать ещё</button>` : failed ? `<button class="primary-button" style="margin-top:16px" data-action="open-create">Создать заново</button>` : `<div class="form-card" style="margin-top:14px"><div class="form-label"><strong>Задача в обработке</strong><small>${statusLabel(item.status)}</small></div><div class="stepper"><span class="stepper__dot active"></span><span class="stepper__dot active"></span><span class="stepper__dot"></span></div></div><button class="secondary-button" style="margin-top:12px" data-action="cancel-generation">Отменить, если ещё можно</button>`}
  </main>`;
}

function emptyState(iconName,title,text) {
  return `<div class="empty-state">${icon(iconName)}<strong>${title}</strong><p>${text}</p></div>`;
}

function currentImagePrice() {
  const refs = state.imageDraft.media.length > 0;
  const slug = state.imageDraft.model === 'seedream-5-pro' && refs ? 'seedream-5-pro-edit' : state.imageDraft.model;
  return priceFor(slug);
}

function priceFor(slug) {
  return Number(prices().find(p => p.model_slug === slug)?.amount_units ?? 0);
}

function formatCredits(value) {
  return new Intl.NumberFormat('ru-RU').format(Number(value ?? 0));
}

function relativeTime(value) {
  if (!value) return '';
  const delta = Math.max(0, Date.now() - new Date(value).getTime());
  const mins = Math.floor(delta / 60000);
  if (mins < 1) return 'только что';
  if (mins < 60) return `${mins} мин назад`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} ч назад`;
  return `${Math.floor(hours / 24)} дн назад`;
}

function modelTitle(slug) {
  const key = slug === 'seedream-5-pro-edit' ? 'seedream-5-pro' : slug;
  return models().find(m => m.ui_key === key && m.variant !== 'edit')?.title || {
    'seedream-5-pro':'Seedream 5 Pro','nano-banana-2':'Nano Banana 2','nano-banana-pro':'Nano Banana Pro','seedance-2':'Seedance 2','seedance-2-mini':'Seedance 2 Mini'
  }[key] || key;
}

function statusLabel(status) {
  return {
    draft:'Черновик',queued:'В очереди',submitting:'Запускаем',submitted:'Отправлено',processing:'Генерация',submission_unknown:'Проверяем',result_ready:'Результат',storing_media:'Сохраняем',delivery_pending:'Доставляем',succeeded:'Готово',failed:'Ошибка',cancelled:'Отменено'
  }[status] ?? status;
}

function statusDescription(status) {
  return {
    queued:'Задача принята и ждёт запуска.',submitting:'Передаём задачу модели.',submitted:'Модель приняла задачу.',processing:'Нейросеть создаёт результат.',submission_unknown:'Уточняем статус без повторного списания.',result_ready:'Получили результат, готовим медиа.',storing_media:'Сохраняем результат приватно.',delivery_pending:'Финализируем задачу.',succeeded:'Результат сохранён в вашей галерее.',failed:'Задача завершилась ошибкой.',cancelled:'Задача отменена до безопасной границы.'
  }[status] ?? 'Обновляем состояние задачи.';
}

function setScreen(screen, { replace = false } = {}) {
  if (screen === state.screen) return;
  if (!replace) state.stack.push(state.screen);
  state.screen = screen;
  window.scrollTo({ top: 0, behavior: 'instant' });
  haptic('light');
  render();
}

function goBack() {
  if (state.stack.length) {
    state.screen = state.stack.pop();
    window.scrollTo({ top: 0, behavior: 'instant' });
    render();
    return;
  }
  if (state.screen !== 'home') {
    state.screen = 'home';
    render();
  }
}

function showToast(message, type = '') {
  const stack = document.getElementById('toast-stack');
  if (!stack) return;
  const node = document.createElement('div');
  node.className = `toast ${type}`;
  node.textContent = message;
  stack.append(node);
  setTimeout(() => node.remove(), 3200);
}

function showPopup(title, message) {
  if (tg?.showPopup) {
    tg.showPopup({ title, message, buttons: [{ type: 'ok' }] });
  } else {
    showToast(`${title}: ${message}`);
  }
}

async function refreshBootstrap() {
  if (state.demo) return;
  state.bootstrap = await api('/bootstrap');
}

async function uploadFile(file, kind) {
  if (state.demo) {
    showPopup('Откройте в Telegram', 'Загрузка и генерация доступны только после безопасной авторизации Telegram.');
    return;
  }
  if (!file?.type) return;
  state.uploadBusy = true;
  render();
  try {
    const result = await api('/input-media', { method:'POST', headers:{'Content-Type':file.type}, body:file });
    result.source = 'upload';
    if (kind === 'image') {
      if (result.kind !== 'image') throw new Error('Для изображения нужен графический файл.');
      if (state.imageDraft.media.length >= 6) throw new Error('Можно добавить не больше 6 референсов в этом интерфейсе.');
      state.imageDraft.media.push(result);
    } else {
      validateVideoUploadKind(result.kind);
      const limit = state.videoDraft.type === 'first_frame' ? 1 : state.videoDraft.type === 'first_last' ? 2 : 6;
      if (state.videoDraft.media.length >= limit) throw new Error(`Лимит файлов для этого сценария: ${limit}.`);
      state.videoDraft.media.push(result);
    }
    notify('success');
  } catch (error) {
    notify('error');
    showToast(error.message, 'error');
  } finally {
    state.uploadBusy = false;
    render();
  }
}

function validateVideoUploadKind(kind) {
  const type = state.videoDraft.type;
  if ((type === 'first_frame' || type === 'first_last') && kind !== 'image') {
    throw new Error('Для первого/последнего кадра выберите изображение.');
  }
  if (type === 'text') throw new Error('Текстовому сценарию референсы не нужны.');
}

async function removeReference(index) {
  const draft = state.screen === 'create-video' ? state.videoDraft : state.imageDraft;
  const [item] = draft.media.splice(index, 1);
  render();
  if (!item?.storage_key || item.source === 'generation' || state.demo) return;
  try { await api(`/input-media/${encodePath(item.storage_key)}`, { method:'DELETE' }); } catch (_) {}
}

function encodePath(path) {
  return path.split('/').map(encodeURIComponent).join('/');
}

async function clearDraftMedia(draft) {
  const items = [...draft.media];
  draft.media = [];
  if (state.demo) return;
  await Promise.allSettled(items.filter(i => i.storage_key && i.source !== 'generation').map(i => api(`/input-media/${encodePath(i.storage_key)}`, {method:'DELETE'})));
}

function decoratedPrompt(prompt, style) {
  const clean = prompt.trim();
  if (!clean || !style) return clean;
  return `${clean}\nСтиль: ${style}.`;
}

function buildImageTask() {
  const d = state.imageDraft;
  if (d.prompt.trim().length < 3) throw new Error('Добавьте промпт — минимум 3 символа.');
  const refs = d.media.filter(item => item.kind === 'image');
  if (refs.length !== d.media.length) throw new Error('В фото-референсах допустимы только изображения.');
  let slug = d.model;
  const prompt = decoratedPrompt(d.prompt, d.style);
  if (d.model === 'seedream-5-pro' && refs.length) slug = 'seedream-5-pro-edit';
  if (slug.startsWith('seedream-5-pro')) {
    const input = { prompt, aspect_ratio:d.aspectRatio, quality:d.quality, output_format:d.outputFormat, nsfw_checker:false };
    if (refs.length) input.image_urls = refs.map(item => item.url);
    return { model_slug:slug, input };
  }
  return { model_slug:slug, input:{ prompt, image_input:refs.map(item=>item.url), aspect_ratio:d.aspectRatio, resolution:d.resolution, output_format:d.outputFormat } };
}

function buildVideoTask() {
  const d = state.videoDraft;
  if (d.prompt.trim().length < 3) throw new Error('Добавьте промпт — минимум 3 символа.');
  if (d.type === 'first_frame' && (d.media.length !== 1 || d.media[0].kind !== 'image')) throw new Error('Нужен ровно один первый кадр.');
  if (d.type === 'first_last' && (d.media.length !== 2 || d.media.some(item => item.kind !== 'image'))) throw new Error('Нужны два изображения: первый и последний кадр.');
  if (d.type === 'references' && !d.media.length) throw new Error('Добавьте хотя бы один референс.');
  const input = {
    prompt:d.prompt.trim(),
    return_last_frame:d.returnLastFrame,
    generate_audio:d.generateAudio,
    resolution:d.resolution,
    aspect_ratio:d.aspectRatio,
    duration:Number(d.duration),
    web_search:d.webSearch,
  };
  if (d.type === 'first_frame') input.first_frame_url = d.media[0].url;
  if (d.type === 'first_last') { input.first_frame_url=d.media[0].url; input.last_frame_url=d.media[1].url; }
  if (d.type === 'references') {
    input.reference_image_urls=d.media.filter(i=>i.kind==='image').map(i=>i.url);
    input.reference_video_urls=d.media.filter(i=>i.kind==='video').map(i=>i.url);
    input.reference_audio_urls=d.media.filter(i=>i.kind==='audio').map(i=>i.url);
  }
  return { model_slug:d.model, input };
}

async function submit(kind) {
  if (state.demo) {
    showPopup('Откройте в Telegram', 'В демо можно пройти весь интерфейс, но списание и реальная генерация отключены.');
    return;
  }
  if (state.busy) return;
  try {
    const body = kind === 'image' ? buildImageTask() : buildVideoTask();
    const draft = kind === 'image' ? state.imageDraft : state.videoDraft;
    const cost = priceFor(body.model_slug);
    if (cost > Number(balance().available_units ?? 0)) throw new Error(`Недостаточно кредитов: нужно ${cost}.`);
    state.busy = true;
    render();
    const result = await api('/tasks', {
      method:'POST',
      headers:{'Content-Type':'application/json','Idempotency-Key':draft.idempotencyKey},
      body:JSON.stringify(body),
    });
    notify('success');
    state.activeGeneration = {
      id:result.generation_id,
      model_slug:result.model,
      media_kind:kind,
      status:result.status,
      prompt:draft.prompt,
      media:[],
      created_at:new Date().toISOString(),
    };
    if (kind === 'image') state.imageDraft = freshImageDraft(); else state.videoDraft = freshVideoDraft();
    setScreen('generation');
    pollGeneration(result.generation_id);
  } catch (error) {
    notify('error');
    showToast(error.message, 'error');
  } finally {
    state.busy = false;
    render();
  }
}

async function pollGeneration(id) {
  if (state.demo) return;
  for (let attempt=0; attempt<180; attempt += 1) {
    try {
      const item = await api(`/generations/${encodeURIComponent(id)}`);
      if (state.activeGeneration?.id === id) state.activeGeneration = item;
      const index = state.bootstrap.recent.findIndex(row => row.id === id);
      if (index >= 0) state.bootstrap.recent[index] = item; else state.bootstrap.recent.unshift(item);
      if (state.screen === 'generation') render();
      if (TERMINAL.has(item.status)) {
        await refreshBootstrap();
        if (state.screen === 'generation') {
          state.activeGeneration = state.bootstrap.recent.find(row => row.id === id) ?? item;
          render();
        }
        if (item.status === 'succeeded') notify('success');
        return;
      }
    } catch (_) {}
    await new Promise(resolve => setTimeout(resolve, 3500));
  }
}

async function openGeneration(id) {
  let item = recent().find(row => row.id === id);
  if (!state.demo) {
    try { item = await api(`/generations/${encodeURIComponent(id)}`); } catch (error) { showToast(error.message,'error'); return; }
  }
  state.activeGeneration = item;
  setScreen('generation');
  if (item && !TERMINAL.has(item.status)) pollGeneration(id);
}

function generationById(id) {
  if (state.activeGeneration?.id === id) return state.activeGeneration;
  return recent().find(row => row.id === id);
}

function remix(id) {
  const item = generationById(id);
  const media = item?.media?.[0];
  if (!item || !media?.url || item.status !== 'succeeded') {
    showToast('Для ремикса нужен готовый сохранённый результат.', 'error');
    return;
  }
  if (item.media_kind === 'image') {
    state.imageDraft = freshImageDraft();
    state.imageDraft.media = [{ kind:'image', url:media.url, source:'generation', storage_key:null }];
    state.imageDraft.prompt = item.prompt ?? '';
    setScreen('create-image');
  } else {
    state.videoDraft = freshVideoDraft();
    state.videoDraft.type = 'references';
    state.videoDraft.media = [{ kind:'video', url:media.url, source:'generation', storage_key:null }];
    state.videoDraft.prompt = item.prompt ?? '';
    setScreen('create-video');
  }
}

async function downloadGeneration(id) {
  const item = generationById(id);
  const media = item?.media?.[0];
  if (!media?.url) { showToast('Файл ещё недоступен.', 'error'); return; }
  const ext = item.media_kind === 'video' ? 'mp4' : 'png';
  const filename = `happy-fox-${id.slice(0,8)}.${ext}`;
  try {
    if (tg?.downloadFile) tg.downloadFile({ url:media.url, file_name:filename });
    else window.open(media.url, '_blank', 'noopener,noreferrer');
  } catch (_) {
    window.open(media.url, '_blank', 'noopener,noreferrer');
  }
}

async function cancelActive() {
  const id = state.activeGeneration?.id;
  if (!id || state.demo) return;
  try {
    const item = await api(`/generations/${encodeURIComponent(id)}/cancel`, {method:'POST'});
    state.activeGeneration = item;
    await refreshBootstrap();
    render();
  } catch (error) { showToast(error.message,'error'); }
}

root.addEventListener('click', async event => {
  const nav = event.target.closest('[data-nav]');
  if (nav) { setScreen(nav.dataset.nav); return; }
  const target = event.target.closest('[data-action]');
  if (!target) return;
  const action = target.dataset.action;
  haptic('light');
  if (action === 'reload') { location.reload(); return; }
  if (action === 'close') { if (tg?.close) tg.close(); else goBack(); return; }
  if (action === 'open-create') { setScreen('create-image'); return; }
  if (action === 'open-image') { if (target.dataset.prefillModel) state.imageDraft.model=target.dataset.prefillModel; setScreen('create-image'); return; }
  if (action === 'open-video') { if (target.dataset.prefillModel) state.videoDraft.model=target.dataset.prefillModel; setScreen('create-video'); return; }
  if (action === 'select-image-model') { state.imageDraft.model=target.dataset.model; render(); return; }
  if (action === 'select-video-model') { state.videoDraft.model=target.dataset.model; render(); return; }
  if (action === 'video-type') { await clearDraftMedia(state.videoDraft); state.videoDraft.type=target.dataset.videoType; render(); return; }
  if (action === 'video-audio') { state.videoDraft.generateAudio=!state.videoDraft.generateAudio; render(); return; }
  if (action === 'video-last') { state.videoDraft.returnLastFrame=!state.videoDraft.returnLastFrame; render(); return; }
  if (action === 'video-web') { state.videoDraft.webSearch=!state.videoDraft.webSearch; render(); return; }
  if (action === 'pick-media') {
    picker.dataset.uploadKind=target.dataset.uploadKind;
    if (target.dataset.uploadKind === 'image' || state.videoDraft.type !== 'references') picker.accept='image/jpeg,image/png,image/webp';
    else picker.accept='image/jpeg,image/png,image/webp,video/mp4,video/webm,audio/mpeg,audio/mp4,audio/wav';
    picker.value=''; picker.click(); return;
  }
  if (action === 'remove-reference') { await removeReference(Number(target.dataset.referenceIndex)); return; }
  if (action === 'submit-image') { await submit('image'); return; }
  if (action === 'submit-video') { await submit('video'); return; }
  if (action === 'reset-image') { await clearDraftMedia(state.imageDraft); state.imageDraft=freshImageDraft(); render(); return; }
  if (action === 'reset-video') { await clearDraftMedia(state.videoDraft); state.videoDraft=freshVideoDraft(); render(); return; }
  if (action === 'gallery-filter') { state.galleryFilter=target.dataset.filter; render(); return; }
  if (action === 'open-generation') { await openGeneration(target.dataset.generationId); return; }
  if (action === 'remix') { remix(target.dataset.generationId); return; }
  if (action === 'download') { await downloadGeneration(target.dataset.generationId); return; }
  if (action === 'cancel-generation') { await cancelActive(); return; }
  if (action === 'topup') { showPopup('Пополнение баланса', 'Способ оплаты появится здесь после подключения пользовательского payment-flow. Текущий баланс и списания уже реальные.'); return; }
});

root.addEventListener('input', event => {
  if (event.target.matches('[data-input="image-prompt"]')) state.imageDraft.prompt=event.target.value;
  if (event.target.matches('[data-input="video-prompt"]')) state.videoDraft.prompt=event.target.value;
});

root.addEventListener('change', event => {
  const key = event.target.dataset.select;
  if (!key) return;
  const value = event.target.value;
  if (key === 'image-aspect') state.imageDraft.aspectRatio=value;
  if (key === 'image-quality') state.imageDraft.quality=value;
  if (key === 'image-style') state.imageDraft.style=value;
  if (key === 'image-resolution') state.imageDraft.resolution=value;
  if (key === 'image-format') state.imageDraft.outputFormat=value;
  if (key === 'video-duration') state.videoDraft.duration=Number(value);
  if (key === 'video-aspect') state.videoDraft.aspectRatio=value;
});

picker.addEventListener('change', async () => {
  const file = picker.files?.[0];
  if (file) await uploadFile(file, picker.dataset.uploadKind || 'image');
});

init();
