const root = document.getElementById('app');
const picker = document.getElementById('media-picker');
const tg = window.Telegram?.WebApp ?? null;

const TERMINAL = new Set(['succeeded', 'failed', 'cancelled']);
const ACTIVE = new Set([
  'queued', 'submitting', 'submitted', 'processing', 'submission_unknown',
  'result_ready', 'storing_media', 'delivery_pending',
]);
const MEDIA_FIELDS = new Set([
  'image_url', 'image_urls', 'image_input', 'input_urls',
  'video_url', 'video_urls', 'audio_url',
  'first_frame_url', 'last_frame_url',
  'reference_image_urls', 'reference_video_urls', 'reference_audio_urls',
]);

const FIELD_LABELS = {
  prompt: 'Промпт',
  aspect_ratio: 'Соотношение сторон',
  quality: 'Качество',
  output_format: 'Формат',
  resolution: 'Разрешение',
  nsfw_checker: 'Проверка безопасности',
  return_last_frame: 'Вернуть последний кадр',
  generate_audio: 'Сгенерировать аудио',
  duration: 'Длительность',
  web_search: 'Веб-поиск',
};

const VALUE_LABELS = {
  basic: 'Стандарт',
  high: 'Высокое',
  png: 'PNG',
  jpg: 'JPG',
  true: 'Да',
  false: 'Нет',
};

const CAPABILITY_LABELS = {
  text_to_image: 'Текст → изображение',
  image_to_image: 'Изображение → изображение',
  image_edit: 'Редактирование',
  text_to_video: 'Текст → видео',
  image_to_video: 'Кадр → видео',
  reference_images: 'Фото-референсы',
  reference_video: 'Видео-референсы',
  reference_audio: 'Аудио-референсы',
  audio_generation: 'Генерация аудио',
};

const ERROR_LABELS = {
  insufficient_credits: 'Недостаточно кредитов для запуска.',
  pricing_unavailable: 'Цена модели временно недоступна.',
  rate_limited: 'Слишком много запросов. Повторите чуть позже.',
  concurrency_limited: 'Уже выполняется максимум одновременных задач.',
  provider_unavailable: 'Провайдер модели временно недоступен.',
  provider_rejected: 'Модель отклонила параметры задачи.',
  provider_protocol: 'Провайдер вернул некорректный ответ.',
  submission_disabled: 'Запуск генераций временно отключён.',
  validation: 'Проверьте параметры генерации.',
};

const state = {
  token: null,
  demo: false,
  busy: false,
  uploadBusy: false,
  galleryBusy: false,
  walletBusy: false,
  screen: 'home',
  stack: [],
  bootstrap: null,
  gallery: [],
  ledger: [],
  activeGeneration: null,
  draft: null,
  validationErrors: {},
  filters: { kind: 'all', status: 'all', model: 'all' },
  modelKind: 'all',
  modelSearch: '',
  pickerPolicy: null,
};

const DEMO = createDemo();

function createDemo() {
  const schemaImage = {
    type: 'object', required: ['prompt'], properties: {
      prompt: { type: 'string', minLength: 1, maxLength: 10000 },
      image_input: { type: 'array', items: { type: 'string', format: 'uri' }, maxItems: 14, default: [] },
      aspect_ratio: { enum: ['auto','1:1','16:9','9:16','4:3','3:4','3:2','2:3','21:9'], default: 'auto' },
      resolution: { enum: ['1K','2K','4K'], default: '1K' },
      output_format: { enum: ['png','jpg'], default: 'png' },
    },
  };
  const schemaVideo = {
    type: 'object', required: ['prompt'], properties: {
      prompt: { type: 'string', minLength: 1, maxLength: 10000 },
      first_frame_url: { anyOf: [{ type: 'string', format: 'uri' }, { type: 'null' }], default: null },
      last_frame_url: { anyOf: [{ type: 'string', format: 'uri' }, { type: 'null' }], default: null },
      reference_image_urls: { type: 'array', maxItems: 6, default: [] },
      reference_video_urls: { type: 'array', maxItems: 3, default: [] },
      reference_audio_urls: { type: 'array', maxItems: 3, default: [] },
      return_last_frame: { type: 'boolean', default: false },
      generate_audio: { type: 'boolean', default: false },
      resolution: { enum: ['720p'], default: '720p' },
      aspect_ratio: { enum: ['16:9','9:16','1:1'], default: '16:9' },
      duration: { enum: [5,10,15], default: 5 },
      web_search: { type: 'boolean', default: false },
    },
  };
  return {
    brand: 'Happy Fox',
    user: { id: 1, display_name: 'Алексей', username: 'alex_fox', photo_url: null, is_premium: true },
    balance: { available_units: 2450, reserved_units: 20, total_units: 2470, currency: 'CREDIT' },
    prices: [
      { model_slug: 'nano-banana-2', amount_units: 7, currency: 'CREDIT' },
      { model_slug: 'nano-banana-pro', amount_units: 12, currency: 'CREDIT' },
      { model_slug: 'seedance-2', amount_units: 20, currency: 'CREDIT' },
      { model_slug: 'seedance-2-mini', amount_units: 12, currency: 'CREDIT' },
    ],
    ledger: [
      { entry_type: 'credit', available_delta: 1000, reserved_delta: 0, reason: 'Пополнение', created_at: new Date().toISOString() },
      { entry_type: 'capture', available_delta: 0, reserved_delta: -20, reason: 'Генерация видео', created_at: new Date(Date.now()-3600000).toISOString() },
    ],
    models: [
      { slug:'nano-banana-2', ui_key:'nano-banana-2', variant:'default', title:'Nano Banana 2', family:'Nano Banana', media_kind:'image', capabilities:['text_to_image','image_to_image'], defaults:{aspect_ratio:'auto',resolution:'1K',output_format:'png'}, recommended_for:['fast production','editing'], tier:'standard', rank:1, enabled:true, input_schema:schemaImage },
      { slug:'nano-banana-pro', ui_key:'nano-banana-pro', variant:'default', title:'Nano Banana Pro', family:'Nano Banana', media_kind:'image', capabilities:['text_to_image','image_to_image'], defaults:{aspect_ratio:'auto',resolution:'1K',output_format:'png'}, recommended_for:['detail','commercial visuals'], tier:'premium', rank:2, enabled:true, input_schema:schemaImage },
      { slug:'seedance-2', ui_key:'seedance-2', variant:'default', title:'Seedance 2', family:'Seedance', media_kind:'video', capabilities:['text_to_video','image_to_video','reference_images','reference_video','reference_audio','audio_generation'], defaults:{resolution:'720p',aspect_ratio:'16:9',duration:5}, recommended_for:['cinematic video','multimodal references'], tier:'premium', rank:1, enabled:true, input_schema:schemaVideo },
      { slug:'seedance-2-mini', ui_key:'seedance-2-mini', variant:'default', title:'Seedance 2 Mini', family:'Seedance', media_kind:'video', capabilities:['text_to_video','image_to_video'], defaults:{resolution:'720p',aspect_ratio:'16:9',duration:5}, recommended_for:['fast video'], tier:'standard', rank:2, enabled:true, input_schema:schemaVideo },
    ],
    recent: [
      demoGeneration('image','nano-banana-pro','Кинематографичный портрет',5),
      demoGeneration('video','seedance-2','Неоновая улица и спортивный автомобиль',24),
      demoGeneration('image','nano-banana-2','Горный пейзаж на рассвете',61),
    ],
    features: { task_submission: true, input_media: true },
    limits: { input_media_max_bytes: 50*1024*1024, generation_history_max:100, ledger_history_max:200 },
  };
}

function demoGeneration(kind, model, prompt, minutesAgo) {
  return {
    id: randomId(), model_slug:model, media_kind:kind, status:'succeeded', prompt,
    created_at:new Date(Date.now()-minutesAgo*60000).toISOString(), completed_at:new Date().toISOString(),
    error_code:null, media:[],
  };
}

function randomId() {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function esc(value) {
  return String(value ?? '')
    .replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')
    .replaceAll('"','&quot;').replaceAll("'",'&#039;');
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
    tg.BackButton?.onClick(goBack);
    tg.onEvent?.('themeChanged', syncTelegramChrome);
    tg.onEvent?.('safeAreaChanged', syncTelegramChrome);
    tg.onEvent?.('contentSafeAreaChanged', syncTelegramChrome);
  } catch (_) {}
}

function syncTelegramChrome() {
  try {
    tg?.setHeaderColor?.('#080808');
    tg?.setBackgroundColor?.('#070707');
    tg?.setBottomBarColor?.('#080808');
  } catch (_) {}
}

function haptic(type='light') {
  try { tg?.HapticFeedback?.impactOccurred?.(type); } catch (_) {}
}

function notify(type='success') {
  try { tg?.HapticFeedback?.notificationOccurred?.(type); } catch (_) {}
}

async function init() {
  setupTelegram();
  try {
    if (tg?.initData) {
      const auth = await rawApi('/auth', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({ init_data:tg.initData }),
      });
      state.token = auth.access_token;
      state.bootstrap = await api('/bootstrap');
    } else {
      state.demo = true;
      state.bootstrap = structuredClone(DEMO);
    }
    state.gallery = [...(state.bootstrap.recent ?? [])];
    state.ledger = [...(state.bootstrap.ledger ?? [])];
    ensureDraft(firstModel()?.slug);
    render();
  } catch (error) {
    renderFatal(error);
  }
}

async function rawApi(path, options={}) {
  const response = await fetch(`/v1/miniapp${path}`, options);
  if (response.status === 204) return null;
  const contentType = response.headers.get('content-type') ?? '';
  const data = contentType.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = typeof data === 'object' ? (data?.detail ?? data?.message ?? data?.error) : data;
    const error = new Error(formatApiDetail(detail) || `HTTP ${response.status}`);
    error.status = response.status;
    error.payload = data;
    error.retryable = Boolean(data?.retryable) || response.status >= 500 || response.status === 429;
    throw error;
  }
  return data;
}

async function api(path, options={}) {
  if (!state.token) throw new Error('Откройте Happy Fox внутри Telegram.');
  const headers = new Headers(options.headers ?? {});
  headers.set('Authorization', `Bearer ${state.token}`);
  return rawApi(path, { ...options, headers });
}

function formatApiDetail(detail) {
  if (!detail) return '';
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map(row => row?.msg || row?.message || JSON.stringify(row)).join(' · ');
  }
  return detail.message || JSON.stringify(detail);
}

function renderFatal(error) {
  root.innerHTML = `<main class="page fatal-page">
    <div class="brand-lockup" style="margin-top:24px">${brandMark()}</div>
    <section class="notice error-card grunge-card" style="margin-top:28px">
      <span class="stamp stamp--danger">OFFLINE</span>
      <strong>Не удалось открыть Happy Fox</strong>
      <p>${esc(error?.message ?? error)}</p>
    </section>
    <button class="primary-button" data-action="reload">Повторить</button>
  </main>`;
}

function brandMark() {
  return `<div class="fox-mark" aria-hidden="true"><svg viewBox="0 0 64 64"><path d="M8 10 23 18 32 12l9 6 15-8-4 27-20 17L12 37 8 10Z" fill="currentColor"/><path d="m19 27 9 5-6 4-3-9Zm26 0-9 5 6 4 3-9Z" fill="#090909"/><path d="m25 40 7 4 7-4-7 10-7-10Z" fill="#090909"/></svg></div><div><strong>Happy <span>Fox</span></strong><small>AI-студия в Telegram</small></div>`;
}

function icon(name) {
  const paths = {
    home:'<path d="M3 11.5 12 4l9 7.5v8a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1v-8Z"/>',
    spark:'<path d="m12 2 1.5 5.5L19 9l-5.5 1.5L12 16l-1.5-5.5L5 9l5.5-1.5L12 2Z"/>',
    grid:'<rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><rect x="14" y="14" width="6" height="6" rx="1"/>',
    wallet:'<path d="M4 7.5h14a2 2 0 0 1 2 2V18H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h12"/><path d="M16 11h5v4h-5a2 2 0 1 1 0-4Z"/>',
    image:'<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m5 18 5-5 3.5 3.5L16 14l3 4"/>',
    video:'<rect x="3" y="5" width="14" height="14" rx="2"/><path d="m17 10 4-2v8l-4-2v-4Z"/>',
    upload:'<path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5"/><path d="M5 14v5h14v-5"/>',
    trash:'<path d="M4 7h16M9 7V4h6v3m-9 0 1 14h10l1-14M10 11v6m4-6v6"/>',
    clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    refresh:'<path d="M20 7v5h-5"/><path d="M19 12a7 7 0 1 0-2 5"/>',
    check:'<path d="m5 12 4 4L19 6"/>',
    close:'<path d="M6 6l12 12M18 6 6 18"/>',
    search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
    download:'<path d="M12 3v12m0 0-4-4m4 4 4-4"/><path d="M5 19h14"/>',
    remix:'<path d="M7 7h8a4 4 0 0 1 4 4v1"/><path d="m16 9 3 3 3-3"/><path d="M17 17H9a4 4 0 0 1-4-4v-1"/><path d="m8 15-3-3-3 3"/>',
    info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/>',
  };
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] ?? paths.spark}</svg>`;
}

function topbar(action='') {
  return `<header class="topbar"><button class="topbar__close" data-action="close">Закрыть</button><div class="topbar__brand"><strong>Happy <span>Fox</span></strong><small>AI STUDIO</small></div><div class="topbar__action">${action}</div></header>`;
}

function bottomNav() {
  const active = state.screen === 'generation' ? 'gallery' : state.screen;
  const item = (screen,label,svg) => `<button class="nav-button ${active===screen?'active':''}" data-nav="${screen}"><span class="nav-icon-wrap">${svg}</span><span>${label}</span></button>`;
  return `<nav class="bottom-nav"><div class="bottom-nav__inner">
    ${item('home','Главная',icon('home'))}
    ${item('models','Модели',icon('spark'))}
    ${item('studio','Создать',icon('image'))}
    ${item('gallery','Работы',icon('grid'))}
    ${item('wallet','Баланс',icon('wallet'))}
  </div></nav>`;
}

function render() {
  updateBackButton();
  const renderer = {
    home:renderHome, models:renderModels, studio:renderStudio,
    gallery:renderGallery, wallet:renderWallet, generation:renderGeneration,
  }[state.screen] ?? renderHome;
  root.innerHTML = `<div class="toast-stack" id="toast-stack"></div>${renderer()}${bottomNav()}`;
}

function updateBackButton() {
  try {
    if (state.screen !== 'home') tg?.BackButton?.show(); else tg?.BackButton?.hide();
    const dirty = state.screen === 'studio' && draftHasChanges();
    if (dirty) tg?.enableClosingConfirmation?.(); else tg?.disableClosingConfirmation?.();
  } catch (_) {}
}

function user() { return state.bootstrap?.user ?? DEMO.user; }
function balance() { return state.bootstrap?.balance ?? DEMO.balance; }
function models() { return state.bootstrap?.models ?? []; }
function prices() { return state.bootstrap?.prices ?? []; }
function limits() { return state.bootstrap?.limits ?? DEMO.limits; }
function features() { return state.bootstrap?.features ?? DEMO.features; }
function firstModel() { return [...models()].sort((a,b)=>(a.rank??99)-(b.rank??99))[0] ?? null; }
function modelBySlug(slug) { return models().find(item => item.slug === slug) ?? null; }
function priceFor(slug) { return Number(prices().find(row => row.model_slug === slug)?.amount_units ?? 0); }

function displayName() { return user().display_name || user().username || 'друг'; }
function avatarHtml() {
  return user().photo_url ? `<img class="avatar" src="${esc(user().photo_url)}" alt="Аватар">` : '<div class="avatar" aria-hidden="true"></div>';
}

function renderHome() {
  const recent = (state.bootstrap?.recent ?? []).slice(0,6);
  const active = recent.filter(item => ACTIVE.has(item.status));
  const modelCount = models().length;
  return `<main class="page">${topbar('<span class="micro-stamp">LIVE</span>')}
    ${state.demo ? '<div class="notice grunge-note">Демо-режим: интерфейс интерактивен, реальные запросы отключены.</div>' : ''}
    <section class="hero-user"><div class="user-chip">${avatarHtml()}<div class="user-copy"><strong>${esc(displayName())}${user().is_premium?'<span class="badge-pro">PRO</span>':''}</strong><small>${user().username?'@'+esc(user().username):'Happy Fox'}</small></div></div>${balanceCompact()}</section>
    <section class="studio-hero grunge-card">
      <span class="stamp">CREATE / 01</span>
      <div class="studio-hero__copy"><small>ВСЕ МОДЕЛИ. ОДНА СТУДИЯ.</small><h1>Создавай без лишних экранов</h1><p>Параметры приходят прямо из backend-схем. Фронт показывает только то, что реально принимает выбранная модель.</p></div>
      <button class="primary-button" data-action="open-studio">Открыть студию ${icon('spark')}</button>
      <div class="scrape-line" aria-hidden="true"></div>
    </section>
    ${active.length ? `<section class="section"><div class="section-head"><h2>Сейчас в работе</h2><button class="section-link" data-nav="gallery">Все задачи</button></div><div class="active-strip">${active.map(renderActiveTask).join('')}</div></section>` : ''}
    <section class="section"><div class="section-head"><h2>Быстрый старт</h2><button class="section-link" data-nav="models">${modelCount} моделей</button></div><div class="model-strip">${recommendedModels().map(renderCompactModel).join('')}</div></section>
    <section class="section"><div class="section-head"><h2>Недавние работы</h2><button class="section-link" data-action="refresh-gallery">Обновить</button></div>${recent.length?`<div class="media-grid">${recent.map(renderMediaTile).join('')}</div>`:emptyState('grid','Пока пусто','Первая генерация появится здесь после запуска.')}</section>
  </main>`;
}

function balanceCompact() {
  return `<button class="balance-card" data-nav="wallet"><div class="balance-card__copy"><small>Доступно</small><strong>${formatCredits(balance().available_units)} <span class="coin">●</span></strong></div><span class="balance-arrow">›</span></button>`;
}

function recommendedModels() {
  return [...models()].sort((a,b)=>(a.rank??99)-(b.rank??99)).slice(0,4);
}

function renderCompactModel(item) {
  return `<button class="model-tile" data-action="choose-model" data-model="${esc(item.slug)}"><span class="model-icon ${item.media_kind==='video'?'video':item.family?.toLowerCase().includes('banana')?'banana':''}">${item.media_kind==='video'?'▶':item.family?.toLowerCase().includes('banana')?'🍌':'◉'}</span><span class="model-copy"><strong>${esc(item.title)}</strong><small>${formatCredits(priceFor(item.slug))} ● · ${item.media_kind==='video'?'Видео':'Изображение'}</small></span></button>`;
}

function renderActiveTask(item) {
  return `<button class="active-task" data-action="open-generation" data-generation-id="${esc(item.id)}"><span class="pulse-dot"></span><div><strong>${esc(modelTitle(item.model_slug))}</strong><small>${statusLabel(item.status)}</small></div><span>›</span></button>`;
}

function renderModels() {
  const query = state.modelSearch.trim().toLowerCase();
  const rows = models().filter(item => {
    if (state.modelKind !== 'all' && item.media_kind !== state.modelKind) return false;
    if (!query) return true;
    return [item.title,item.family,item.slug,...(item.recommended_for??[])].join(' ').toLowerCase().includes(query);
  }).sort((a,b)=>(a.rank??99)-(b.rank??99));
  return `<main class="page">${topbar()}
    <div class="section-head"><div><h1 class="screen-title">Модели</h1><p class="screen-subtitle">Каталог формируется backend-реестром — только реально разрешённые для запуска модели.</p></div><span class="stamp">${models().length} LIVE</span></div>
    <label class="search-box">${icon('search')}<input type="search" data-input="model-search" value="${esc(state.modelSearch)}" placeholder="Найти модель или задачу"></label>
    <div class="tabs model-tabs"><button class="tab ${state.modelKind==='all'?'active':''}" data-action="model-kind" data-kind="all">Все</button><button class="tab ${state.modelKind==='image'?'active':''}" data-action="model-kind" data-kind="image">Изображения</button><button class="tab ${state.modelKind==='video'?'active':''}" data-action="model-kind" data-kind="video">Видео</button></div>
    <div class="model-catalog">${rows.length?rows.map(renderModelCard).join(''):emptyState('search','Ничего не нашли','Сбросьте фильтр или поисковую строку.')}</div>
  </main>`;
}

function renderModelCard(item) {
  const caps = (item.capabilities??[]).slice(0,4).map(cap => `<span class="cap-chip">${esc(CAPABILITY_LABELS[cap]??humanize(cap))}</span>`).join('');
  const recommended = (item.recommended_for??[]).slice(0,3).map(value => `<span>${esc(humanize(value))}</span>`).join('');
  return `<article class="model-card grunge-card"><div class="model-card__top"><div class="model-card__identity"><span class="model-icon ${item.media_kind==='video'?'video':item.family?.toLowerCase().includes('banana')?'banana':''}">${item.media_kind==='video'?'▶':item.family?.toLowerCase().includes('banana')?'🍌':'◉'}</span><div><small>${esc(item.family||'AI')}</small><h3>${esc(item.title)}</h3></div></div><span class="tier-badge">${esc(item.tier||'standard')}</span></div>
    <div class="cap-list">${caps}</div>
    ${recommended?`<div class="recommended-line">${recommended}</div>`:''}
    <div class="model-card__footer"><div><small>Цена запуска</small><strong>${formatCredits(priceFor(item.slug))} ●</strong></div><button class="small-orange-button" data-action="choose-model" data-model="${esc(item.slug)}">Создать</button></div></article>`;
}

function ensureDraft(slug) {
  const item = modelBySlug(slug) ?? firstModel();
  if (!item) return null;
  if (state.draft?.modelSlug === item.slug) return state.draft;
  state.draft = createDraft(item);
  state.validationErrors = {};
  return state.draft;
}

function createDraft(item) {
  const properties = item.input_schema?.properties ?? {};
  const values = {};
  for (const [name,schema] of Object.entries(properties)) {
    if (MEDIA_FIELDS.has(name)) continue;
    if (schema.default !== undefined && schema.default !== null) values[name] = schema.default;
    else if (item.defaults?.[name] !== undefined) values[name] = item.defaults[name];
    else if (schema.type === 'boolean') values[name] = false;
    else if (name === 'prompt') values[name] = '';
  }
  for (const [name,value] of Object.entries(item.defaults??{})) {
    if (!MEDIA_FIELDS.has(name) && values[name] === undefined) values[name] = value;
  }
  return {
    modelSlug:item.slug,
    values,
    media:[],
    mediaMode:hasFrameMode(item)?'text':'references',
    idempotencyKey:randomId(),
  };
}

function draftHasChanges() {
  if (!state.draft) return false;
  return Boolean(String(state.draft.values?.prompt??'').trim() || state.draft.media.length);
}

function hasFrameMode(item) {
  const props = item?.input_schema?.properties ?? {};
  return Boolean(props.first_frame_url || props.last_frame_url || props.reference_image_urls || props.reference_video_urls || props.reference_audio_urls);
}

function renderStudio() {
  const draft = ensureDraft(state.draft?.modelSlug ?? firstModel()?.slug);
  const item = modelBySlug(draft?.modelSlug);
  if (!draft || !item) return `<main class="page">${topbar()}${emptyState('spark','Нет доступных моделей','Backend пока не разрешил ни одной модели для запуска.')}</main>`;
  const schema = item.input_schema ?? { properties:{} };
  const cost = priceFor(item.slug);
  const canSubmit = features().task_submission !== false && !state.busy;
  return `<main class="page studio-page">${topbar('<button class="topbar__action" data-action="reset-draft">Сбросить</button>')}
    <section class="studio-title"><div><span class="stamp">SCHEMA DRIVEN</span><h1>${esc(item.title)}</h1><p>${esc(item.family||'AI')} · ${item.media_kind==='video'?'Видео':'Изображение'} · ${formatCredits(cost)} ●</p></div><button class="model-switch" data-nav="models">Сменить ›</button></section>
    ${features().task_submission===false?'<div class="notice error-card">Запуск задач временно отключён на backend.</div>':''}
    ${renderMediaControls(item,draft)}
    ${renderSchemaForm(item,schema,draft)}
    ${renderValidationSummary()}
    <section class="submit-panel grunge-card"><div class="submit-panel__price"><small>Стоимость запуска</small><strong>${formatCredits(cost)} <span class="coin">●</span></strong><span>Баланс ${formatCredits(balance().available_units)} ●</span></div><button class="primary-button" data-action="submit-task" ${canSubmit?'':'disabled'}>${state.busy?'Проверяем и запускаем…':'Создать'}</button></section>
    <p class="backend-trust">Перед запуском payload ещё раз валидируется сервером. Списание и idempotency выполняются backend-контуром.</p>
  </main>`;
}

function renderMediaControls(item,draft) {
  const props = item.input_schema?.properties ?? {};
  const mediaFields = Object.keys(props).filter(name => MEDIA_FIELDS.has(name));
  if (!mediaFields.length) return '';
  if (hasFrameMode(item)) return renderSeedanceMedia(item,draft);

  const target = mediaFields.includes('image_urls') ? 'image_urls' : mediaFields.includes('image_input') ? 'image_input' : mediaFields[0];
  const schema = props[target] ?? {};
  const required = (item.input_schema?.required??[]).includes(target);
  const maxItems = Number(schema.maxItems ?? (target.endsWith('_url')?1:6));
  return `<section class="section form-card media-form grunge-lite"><div class="form-label"><div><strong>${required?'Референс':'Референс, если нужен'}</strong><small>${esc(FIELD_LABELS[target]??humanize(target))}</small></div><span>${draft.media.length}/${maxItems}</span></div>${renderUploadZone({ kinds:['image'], maxItems, label:required?'Добавьте изображение':'Добавить изображение' })}${renderReferences(draft.media)}</section>`;
}

function renderSeedanceMedia(item,draft) {
  const props = item.input_schema?.properties ?? {};
  const modes = [
    ['text','Текст','Без файлов'],
    ['first_frame','Первый кадр','1 изображение'],
    ['first_last','Первый + последний','2 изображения'],
    ['references','Референсы','Фото / видео / аудио'],
  ];
  const showRefs = props.reference_image_urls || props.reference_video_urls || props.reference_audio_urls;
  const available = modes.filter(([mode]) => mode!=='references' || showRefs);
  let upload = '';
  if (draft.mediaMode === 'first_frame') upload = renderUploadZone({ kinds:['image'],maxItems:1,label:'Загрузить первый кадр' });
  if (draft.mediaMode === 'first_last') upload = renderUploadZone({ kinds:['image'],maxItems:2,label:draft.media.length?'Добавить второй кадр':'Загрузить первый кадр' });
  if (draft.mediaMode === 'references') upload = renderUploadZone({ kinds:['image','video','audio'],maxItems:6,label:'Добавить референс' });
  return `<section class="section form-card media-form grunge-lite"><div class="form-label"><div><strong>Режим генерации</strong><small>Backend-контракт не смешивает frame и reference mode</small></div></div><div class="mode-grid">${available.map(([mode,title,summary])=>`<button class="mode-card ${draft.mediaMode===mode?'active':''}" data-action="media-mode" data-mode="${mode}"><strong>${title}</strong><small>${summary}</small></button>`).join('')}</div>${upload}${renderReferences(draft.media)}</section>`;
}

function renderUploadZone(policy) {
  if (features().input_media===false) return '<div class="notice">Загрузка файлов сейчас недоступна на backend.</div>';
  const disabled = state.uploadBusy || state.draft.media.length >= policy.maxItems;
  const maxMb = Math.max(1,Math.round(Number(limits().input_media_max_bytes??0)/1024/1024));
  return `<button class="upload-zone ${state.uploadBusy?'loading':''}" data-action="pick-media" data-kinds="${esc(policy.kinds.join(','))}" data-max-items="${policy.maxItems}" ${disabled?'disabled':''}>${icon('upload')}<span><strong>${state.uploadBusy?'Загружаем…':esc(policy.label)}</strong><small>${policy.kinds.map(kind=>({image:'PNG/JPG/WEBP',video:'MP4/WEBM',audio:'MP3/M4A/WAV'}[kind])).join(' · ')} · до ${maxMb} МБ</small></span></button>`;
}

function renderReferences(items) {
  if (!items.length) return '';
  return `<div class="reference-list">${items.map((item,index)=>`<div class="reference-item"><div class="reference-thumb">${mediaPreview(item,'reference')}</div><div class="reference-copy"><strong>${referenceLabel(item,index)}</strong><small>${item.source==='generation'?'Из готовой работы':'Приватная загрузка'} · ${formatBytes(item.size_bytes)}</small></div><button class="icon-button danger" data-action="remove-reference" data-reference-index="${index}">${icon('trash')}</button></div>`).join('')}</div>`;
}

function referenceLabel(item,index) {
  if (state.draft?.mediaMode==='first_last') return index===0?'Первый кадр':'Последний кадр';
  return item.kind==='video'?'Видео':item.kind==='audio'?'Аудио':'Изображение';
}

function renderSchemaForm(item,schema,draft) {
  const properties = schema.properties ?? {};
  const required = new Set(schema.required ?? []);
  const entries = Object.entries(properties).filter(([name]) => !MEDIA_FIELDS.has(name));
  const prompt = entries.find(([name]) => name==='prompt');
  const rest = entries.filter(([name]) => name!=='prompt');
  return `<section class="section form-card schema-card"><div class="form-label"><div><strong>Параметры модели</strong><small>${esc(item.contract||'validated contract')}</small></div><span class="micro-stamp">BACKEND</span></div>${prompt?renderSchemaField(prompt[0],prompt[1],draft,required.has(prompt[0]),true):''}<div class="schema-grid">${rest.map(([name,field])=>renderSchemaField(name,field,draft,required.has(name),false)).join('')}</div></section>`;
}

function renderSchemaField(name,field,draft,required,isPrompt) {
  const value = draft.values[name];
  const error = state.validationErrors[name];
  const label = FIELD_LABELS[name] ?? humanize(name);
  const requiredMark = required?'<span class="required-mark">*</span>':'';
  const description = schemaHint(field);
  if (field.type==='boolean') {
    return `<div class="schema-field schema-field--toggle ${error?'invalid':''}"><div><label>${esc(label)} ${requiredMark}</label><small>${esc(description)}</small></div><button class="switch ${value?'on':''}" data-action="toggle-field" data-field="${esc(name)}" role="switch" aria-checked="${Boolean(value)}"></button>${fieldError(error)}</div>`;
  }
  const choices = schemaEnum(field);
  if (choices?.length) {
    if (choices.length <= 4) {
      return `<div class="schema-field ${error?'invalid':''}"><label>${esc(label)} ${requiredMark}</label><div class="segmented">${choices.map(option=>`<button data-action="enum-field" data-field="${esc(name)}" data-value="${esc(String(option))}" class="${String(value)===String(option)?'active':''}">${esc(VALUE_LABELS[String(option)]??String(option))}</button>`).join('')}</div><small>${esc(description)}</small>${fieldError(error)}</div>`;
    }
    return `<div class="schema-field ${error?'invalid':''}"><label>${esc(label)} ${requiredMark}</label><select data-field-select="${esc(name)}">${choices.map(option=>`<option value="${esc(String(option))}" ${String(value)===String(option)?'selected':''}>${esc(VALUE_LABELS[String(option)]??String(option))}</option>`).join('')}</select><small>${esc(description)}</small>${fieldError(error)}</div>`;
  }
  if (isPrompt || (field.type==='string' && Number(field.maxLength??0)>300)) {
    return `<div class="schema-field schema-field--wide ${error?'invalid':''}"><div class="field-counter"><label>${esc(label)} ${requiredMark}</label><span>${String(value??'').length}${field.maxLength?` / ${field.maxLength}`:''}</span></div><textarea data-field-input="${esc(name)}" maxlength="${Number(field.maxLength??10000)}" placeholder="${esc(promptPlaceholder(modelBySlug(draft.modelSlug) ?? {}))}">${esc(value??'')}</textarea><small>${esc(description)}</small>${fieldError(error)}</div>`;
  }
  const type = field.type==='integer'||field.type==='number'?'number':'text';
  const step = field.type==='integer'?'1':'any';
  return `<div class="schema-field ${error?'invalid':''}"><label>${esc(label)} ${requiredMark}</label><input type="${type}" step="${step}" data-field-input="${esc(name)}" value="${esc(value??'')}" ${field.minimum!==undefined?`min="${field.minimum}"`:''} ${field.maximum!==undefined?`max="${field.maximum}"`:''}><small>${esc(description)}</small>${fieldError(error)}</div>`;
}

function schemaEnum(field) {
  if (Array.isArray(field.enum)) return field.enum;
  for (const branch of field.anyOf??[]) if (Array.isArray(branch.enum)) return branch.enum.filter(value=>value!==null);
  return null;
}

function schemaHint(field) {
  const chunks=[];
  if (field.minLength) chunks.push(`мин. ${field.minLength} симв.`);
  if (field.maxLength) chunks.push(`до ${field.maxLength} симв.`);
  if (field.minimum!==undefined) chunks.push(`от ${field.minimum}`);
  if (field.maximum!==undefined) chunks.push(`до ${field.maximum}`);
  if (field.default!==undefined && field.default!==null) chunks.push(`по умолчанию: ${VALUE_LABELS[String(field.default)]??field.default}`);
  return chunks.join(' · ') || 'Параметр проверяется backend-контрактом';
}

function fieldError(error) { return error?`<em class="field-error">${esc(error)}</em>`:''; }
function promptPlaceholder(item) { return item.media_kind==='video'?'Опишите сцену, движение, свет, камеру и атмосферу…':'Опишите сюжет, композицию, свет, стиль и детали…'; }

function renderValidationSummary() {
  const errors = Object.entries(state.validationErrors);
  if (!errors.length) return '';
  return `<div class="notice error-card validation-summary"><strong>Нужно поправить параметры</strong><p>${errors.map(([name,msg])=>`${esc(FIELD_LABELS[name]??humanize(name))}: ${esc(msg)}`).join('<br>')}</p></div>`;
}

function renderGallery() {
  const rows = filteredGallery();
  const modelsInGallery = [...new Set(state.gallery.map(item=>item.model_slug))];
  return `<main class="page">${topbar('<button class="icon-top" data-action="refresh-gallery">'+icon('refresh')+'</button>')}
    <div class="section-head"><div><h1 class="screen-title">Мои работы</h1><p class="screen-subtitle">До ${limits().generation_history_max??100} последних задач из backend.</p></div><span class="stamp">${state.gallery.length}</span></div>
    <div class="gallery-filters"><select data-gallery-filter="kind"><option value="all">Все типы</option><option value="image" ${state.filters.kind==='image'?'selected':''}>Изображения</option><option value="video" ${state.filters.kind==='video'?'selected':''}>Видео</option></select><select data-gallery-filter="status"><option value="all">Все статусы</option><option value="active" ${state.filters.status==='active'?'selected':''}>В работе</option><option value="succeeded" ${state.filters.status==='succeeded'?'selected':''}>Готово</option><option value="failed" ${state.filters.status==='failed'?'selected':''}>Ошибки</option><option value="cancelled" ${state.filters.status==='cancelled'?'selected':''}>Отменено</option></select><select data-gallery-filter="model"><option value="all">Все модели</option>${modelsInGallery.map(slug=>`<option value="${esc(slug)}" ${state.filters.model===slug?'selected':''}>${esc(modelTitle(slug))}</option>`).join('')}</select></div>
    ${state.galleryBusy?loadingState('Обновляем историю…'):rows.length?`<div class="gallery-list">${rows.map(renderGalleryCard).join('')}</div>`:emptyState('grid','Здесь пока пусто','Создайте первую работу или поменяйте фильтры.')}
  </main>`;
}

function filteredGallery() {
  return state.gallery.filter(item => {
    if (state.filters.kind!=='all' && item.media_kind!==state.filters.kind) return false;
    if (state.filters.model!=='all' && item.model_slug!==state.filters.model) return false;
    if (state.filters.status==='active' && !ACTIVE.has(item.status)) return false;
    if (!['all','active'].includes(state.filters.status) && item.status!==state.filters.status) return false;
    return true;
  });
}

function renderGalleryCard(item) {
  const done = item.status==='succeeded';
  const preview = item.media?.[0] ? mediaPreview({kind:item.media_kind,url:item.media[0].url},'gallery') : '<div class="gallery-preview__fallback"></div>';
  return `<article class="gallery-card"><button class="gallery-preview" data-action="open-generation" data-generation-id="${esc(item.id)}">${preview}<span class="gallery-status ${done?'ok':''}">${statusLabel(item.status)}</span><span class="gallery-kind">${item.media_kind==='video'?'Видео':'Изображение'}</span></button><div class="gallery-body"><div class="gallery-title">${esc(item.prompt||modelTitle(item.model_slug))}</div><div class="gallery-meta">${esc(modelTitle(item.model_slug))} · ${relativeTime(item.created_at)}</div><div class="gallery-actions">${done?`<button class="gallery-action" data-action="remix" data-generation-id="${esc(item.id)}">${icon('remix')} Ремикс</button><button class="gallery-action" data-action="download" data-generation-id="${esc(item.id)}">${icon('download')} Скачать</button>`:''}<button class="gallery-action accent" data-action="open-generation" data-generation-id="${esc(item.id)}">Открыть</button></div></div></article>`;
}

function renderMediaTile(item) {
  const media=item.media?.[0];
  return `<button class="media-card" data-action="open-generation" data-generation-id="${esc(item.id)}">${media?mediaPreview({kind:item.media_kind,url:media.url},'tile'):'<div class="media-card__fallback"></div>'}<span class="media-card__status ${item.status==='succeeded'?'ok':''}">${statusLabel(item.status)}</span><span class="media-card__meta"><span>${item.media_kind==='video'?'Видео':'Фото'}</span><span>${relativeTime(item.created_at)}</span></span></button>`;
}

function mediaPreview(item,context) {
  if (!item?.url) return '';
  if (item.kind==='video') return `<video src="${esc(item.url)}" ${context==='gallery'?'controls':''} muted playsinline preload="metadata"></video>`;
  if (item.kind==='audio') return `<div class="audio-preview">♫</div>`;
  return `<img src="${esc(item.url)}" alt="Референс" loading="lazy">`;
}

function renderWallet() {
  const rows = state.ledger;
  return `<main class="page">${topbar('<button class="icon-top" data-action="refresh-wallet">'+icon('refresh')+'</button>')}
    <div class="section-head"><div><h1 class="screen-title">Баланс</h1><p class="screen-subtitle">Реальные доступные, зарезервированные и списанные кредиты.</p></div><span class="micro-stamp">LEDGER</span></div>
    <section class="wallet-hero grunge-card"><small>Доступно</small><strong>${formatCredits(balance().available_units)} <span class="coin">●</span></strong><div class="wallet-stats"><span><small>В резерве</small><b>${formatCredits(balance().reserved_units)} ●</b></span><span><small>Всего</small><b>${formatCredits(balance().total_units)} ●</b></span></div></section>
    <section class="section"><div class="section-head"><h2>Цены моделей</h2><span class="section-link">за запуск</span></div><div class="price-list">${models().map(item=>`<button data-action="choose-model" data-model="${esc(item.slug)}"><span>${esc(item.title)}</span><strong>${formatCredits(priceFor(item.slug))} ●</strong></button>`).join('')}</div></section>
    <section class="section"><div class="section-head"><h2>История операций</h2><span class="section-link">до ${limits().ledger_history_max??200}</span></div>${state.walletBusy?loadingState('Получаем ledger…'):rows.length?`<div class="ledger">${rows.map(renderLedger).join('')}</div>`:emptyState('wallet','Операций пока нет','Резервы, списания и возвраты появятся здесь автоматически.')}</section>
    <div class="notice grunge-note"><strong>Пополнение</strong><br>В Mini App backend сейчас нет пользовательского payment endpoint, поэтому интерфейс не показывает фальшивую кнопку оплаты. Баланс, резервы, списания и возвраты — реальные.</div>
  </main>`;
}

function renderLedger(item) {
  const available=Number(item.available_delta??0);
  const reserved=Number(item.reserved_delta??0);
  const amount=available!==0?available:reserved;
  const positive=amount>0;
  const label={credit:'Пополнение',debit:'Списание',reserve:'Резерв',capture:'Оплата генерации',release:'Снятие резерва',refund:'Возврат',adjustment:'Корректировка'}[item.entry_type]??humanize(item.entry_type);
  return `<button class="ledger-row" ${item.generation_id?`data-action="open-generation" data-generation-id="${esc(item.generation_id)}"`:''}><span class="ledger-icon ${positive?'plus':''}">${positive?'+':'●'}</span><span class="ledger-copy"><strong>${esc(label)}</strong><small>${esc(item.reason||'')} · ${relativeTime(item.created_at)}</small></span><span class="ledger-amount ${positive?'plus':'minus'}">${amount>0?'+':''}${formatCredits(amount)} ●</span></button>`;
}

function renderGeneration() {
  const item=state.activeGeneration;
  if (!item) return `<main class="page">${topbar()}${loadingState('Получаем статус…')}</main>`;
  const media=item.media?.[0];
  const done=item.status==='succeeded';
  const failed=item.status==='failed'||item.status==='cancelled';
  const canCancel=ACTIVE.has(item.status) && !state.demo;
  return `<main class="page">${topbar('<span class="micro-stamp">'+esc(statusLabel(item.status))+'</span>')}
    <section class="generation-head ${failed?'generation-head--failed':''}"><span class="stamp ${failed?'stamp--danger':''}">${done?'DONE':failed?'STOP':'PROCESS'}</span><h1>${done?'Готово':failed?'Задача остановлена':'Создаём результат'}</h1><p>${esc(statusDescription(item.status))}</p></section>
    <section class="gallery-card generation-card">${media?`<div class="gallery-preview">${mediaPreview({kind:item.media_kind,url:media.url},'gallery')}</div>`:'<div class="generation-placeholder"><div class="generating-orbit"></div>'+icon('clock')+'</div>'}<div class="gallery-body"><div class="gallery-title">${esc(item.prompt||modelTitle(item.model_slug))}</div><div class="gallery-meta">${esc(modelTitle(item.model_slug))} · ${relativeTime(item.created_at)}</div>${item.error_code?`<div class="notice error-card generation-error"><strong>${esc(ERROR_LABELS[item.error_code]??humanize(item.error_code))}</strong><small>Код: ${esc(item.error_code)}</small></div>`:''}</div></section>
    ${renderProgress(item.status)}
    <div class="button-row generation-actions">${done?`<button class="secondary-button" data-action="remix" data-generation-id="${esc(item.id)}">${icon('remix')} Ремикс</button><button class="primary-button" data-action="download" data-generation-id="${esc(item.id)}">${icon('download')} Скачать</button>`:failed?`<button class="primary-button" data-action="retry-generation" data-generation-id="${esc(item.id)}">Создать заново</button>`:canCancel?'<button class="secondary-button danger-outline" data-action="cancel-generation">Отменить задачу</button>':''}</div>
  </main>`;
}

function renderProgress(status) {
  if (TERMINAL.has(status)) return '';
  const order=['queued','submitting','submitted','processing','submission_unknown','result_ready','storing_media','delivery_pending'];
  const index=Math.max(0,order.indexOf(status));
  const percent=Math.min(92,12+index*11);
  return `<section class="progress-card grunge-lite"><div class="progress-copy"><strong>${statusLabel(status)}</strong><span>${percent}%</span></div><div class="progress-track"><i style="width:${percent}%"></i></div><small>Статус обновляется автоматически. Повторная отправка задачи не выполняется.</small></section>`;
}

function renderActiveGenerationFromReceipt(receipt,item,draft) {
  return { id:receipt.generation_id, model_slug:receipt.model||item.slug, media_kind:item.media_kind, status:receipt.status, prompt:draft.values.prompt??'', created_at:new Date().toISOString(), completed_at:null, error_code:null, media:[] };
}

function emptyState(iconName,title,text) { return `<div class="empty-state">${icon(iconName)}<strong>${title}</strong><p>${text}</p></div>`; }
function loadingState(text) { return `<div class="empty-state loading-state"><span class="boot-spinner"></span><strong>${esc(text)}</strong></div>`; }

function setScreen(screen,{replace=false}={}) {
  if (screen===state.screen) return;
  if (!replace) state.stack.push(state.screen);
  state.screen=screen;
  window.scrollTo({top:0,behavior:'instant'});
  haptic('light');
  render();
  if (screen==='gallery') void loadGallery();
  if (screen==='wallet') void loadWallet();
}

function goBack() {
  if (state.stack.length) {
    state.screen=state.stack.pop();
    window.scrollTo({top:0,behavior:'instant'});
    render();
    return;
  }
  if (state.screen!=='home') { state.screen='home'; render(); }
}

async function refreshBootstrap() {
  if (state.demo) return;
  state.bootstrap=await api('/bootstrap');
}

async function loadGallery(force=false) {
  if (state.demo) { state.gallery=[...(state.bootstrap.recent??[])]; render(); return; }
  if (state.galleryBusy && !force) return;
  state.galleryBusy=true;
  render();
  try {
    const max=Math.min(100,Number(limits().generation_history_max??100));
    state.gallery=await api(`/generations?limit=${max}`);
    state.bootstrap.recent=state.gallery.slice(0,12);
  } catch (error) { showToast(error.message,'error'); }
  finally { state.galleryBusy=false; render(); }
}

async function loadWallet() {
  if (state.demo) { state.ledger=[...(state.bootstrap.ledger??[])]; render(); return; }
  if (state.walletBusy) return;
  state.walletBusy=true;
  render();
  try {
    const max=Math.min(200,Number(limits().ledger_history_max??200));
    const [freshBalance,freshPrices,ledger]=await Promise.all([api('/balance'),api('/prices'),api(`/ledger?limit=${max}`)]);
    state.bootstrap.balance=freshBalance;
    state.bootstrap.prices=freshPrices;
    state.bootstrap.ledger=ledger.slice(0,8);
    state.ledger=ledger;
  } catch (error) { showToast(error.message,'error'); }
  finally { state.walletBusy=false; render(); }
}

function openStudio(slug) {
  const model=modelBySlug(slug)??firstModel();
  if (!model) return;
  if (state.draft?.modelSlug!==model.slug) state.draft=createDraft(model);
  state.validationErrors={};
  setScreen('studio');
}

async function switchModel(slug) {
  const model=modelBySlug(slug);
  if (!model || state.draft?.modelSlug===slug) return;
  if (draftHasChanges()) await clearDraftMedia();
  state.draft=createDraft(model);
  state.validationErrors={};
  setScreen('studio');
}

function mediaPolicyFromButton(target) {
  const kinds=(target.dataset.kinds??'image').split(',').filter(Boolean);
  const maxItems=Number(target.dataset.maxItems??1);
  return { kinds,maxItems };
}

function configurePicker(policy) {
  const map={ image:['image/jpeg','image/png','image/webp'], video:['video/mp4','video/webm'], audio:['audio/mpeg','audio/mp4','audio/wav','audio/x-wav'] };
  picker.accept=policy.kinds.flatMap(kind=>map[kind]??[]).join(',');
  picker.multiple=policy.maxItems-state.draft.media.length>1;
  picker.value='';
  state.pickerPolicy=policy;
}

async function uploadFiles(files) {
  const policy=state.pickerPolicy;
  if (!policy || !files.length) return;
  if (state.demo) { showPopup('Демо-режим','Загрузка доступна после Telegram-авторизации.'); return; }
  const slots=Math.max(0,policy.maxItems-state.draft.media.length);
  const selected=[...files].slice(0,slots);
  if (!selected.length) return;
  state.uploadBusy=true; render();
  try {
    for (const file of selected) {
      if (file.size>Number(limits().input_media_max_bytes??Infinity)) throw new Error(`Файл ${file.name} превышает лимит backend.`);
      const result=await api('/input-media',{method:'POST',headers:{'Content-Type':file.type},body:file});
      if (!policy.kinds.includes(result.kind)) {
        await api(`/input-media/${encodePath(result.storage_key)}`,{method:'DELETE'}).catch(()=>{});
        throw new Error(`Тип ${result.kind} не подходит для выбранного режима.`);
      }
      state.draft.media.push({...result,source:'upload'});
    }
    notify('success');
  } catch (error) { notify('error'); showToast(error.message,'error'); }
  finally { state.uploadBusy=false; render(); }
}

async function removeReference(index) {
  const [item]=state.draft.media.splice(index,1);
  render();
  if (!item?.storage_key || item.source==='generation' || state.demo) return;
  await api(`/input-media/${encodePath(item.storage_key)}`,{method:'DELETE'}).catch(()=>{});
}

async function clearDraftMedia() {
  if (!state.draft) return;
  const items=[...state.draft.media];
  state.draft.media=[];
  if (state.demo) return;
  await Promise.allSettled(items.filter(item=>item.storage_key&&item.source!=='generation').map(item=>api(`/input-media/${encodePath(item.storage_key)}`,{method:'DELETE'})));
}

function encodePath(path) { return path.split('/').map(encodeURIComponent).join('/'); }

function buildPayload(item,draft) {
  const props=item.input_schema?.properties??{};
  const payload={};
  for (const [name,value] of Object.entries(draft.values)) {
    if (MEDIA_FIELDS.has(name)) continue;
    if (value===undefined || value===null || value==='') {
      if ((item.input_schema?.required??[]).includes(name)) payload[name]=value;
      continue;
    }
    payload[name]=value;
  }
  const urls=kind => draft.media.filter(row=>row.kind===kind).map(row=>row.url);
  if (hasFrameMode(item)) {
    if (draft.mediaMode==='first_frame' && draft.media[0]) payload.first_frame_url=draft.media[0].url;
    if (draft.mediaMode==='first_last') {
      if (draft.media[0]) payload.first_frame_url=draft.media[0].url;
      if (draft.media[1]) payload.last_frame_url=draft.media[1].url;
    }
    if (draft.mediaMode==='references') {
      if (props.reference_image_urls) payload.reference_image_urls=urls('image');
      if (props.reference_video_urls) payload.reference_video_urls=urls('video');
      if (props.reference_audio_urls) payload.reference_audio_urls=urls('audio');
    }
  } else {
    if (props.image_urls) payload.image_urls=urls('image');
    if (props.image_input) payload.image_input=urls('image');
    if (props.input_urls) payload.input_urls=urls('image');
    if (props.image_url && draft.media[0]) payload.image_url=draft.media[0].url;
    if (props.video_url && draft.media[0]) payload.video_url=draft.media[0].url;
    if (props.audio_url && draft.media[0]) payload.audio_url=draft.media[0].url;
  }
  return payload;
}

async function validatePayload(item,payload) {
  if (state.demo) return payload;
  try {
    const response=await api(`/models/${encodeURIComponent(item.slug)}/validate`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({input:payload})});
    state.validationErrors={};
    return response.input;
  } catch (error) {
    state.validationErrors=validationErrorsFrom(error);
    render();
    throw error;
  }
}

function validationErrorsFrom(error) {
  const detail=error?.payload?.detail;
  if (!Array.isArray(detail)) return { _form:error.message };
  const result={};
  for (const row of detail) {
    const path=(row.loc??[]).filter(part=>part!=='body'&&part!=='input');
    const name=String(path[0]??'_form');
    result[name]=row.msg??'Некорректное значение';
  }
  return result;
}

async function submitTask() {
  if (state.demo) { showPopup('Демо-режим','Реальная генерация доступна после Telegram-авторизации.'); return; }
  if (state.busy || !state.draft) return;
  const item=modelBySlug(state.draft.modelSlug);
  if (!item) return;
  const cost=priceFor(item.slug);
  if (cost>Number(balance().available_units??0)) { showToast(`Недостаточно кредитов: нужно ${formatCredits(cost)} ●`,'error'); setScreen('wallet'); return; }
  state.busy=true; state.validationErrors={}; render();
  const draft=state.draft;
  try {
    const payload=buildPayload(item,draft);
    const normalized=await validatePayload(item,payload);
    const receipt=await api('/tasks',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':draft.idempotencyKey},body:JSON.stringify({model_slug:item.slug,input:normalized})});
    notify('success');
    state.activeGeneration=renderActiveGenerationFromReceipt(receipt,item,draft);
    state.gallery=[state.activeGeneration,...state.gallery.filter(row=>row.id!==state.activeGeneration.id)];
    state.bootstrap.recent=[state.activeGeneration,...(state.bootstrap.recent??[]).filter(row=>row.id!==state.activeGeneration.id)].slice(0,12);
    state.draft=createDraft(item);
    await refreshBalanceOnly();
    setScreen('generation');
    void pollGeneration(receipt.generation_id);
  } catch (error) {
    notify('error');
    if (!Object.keys(state.validationErrors).length) showToast(error.message,'error');
  } finally { state.busy=false; render(); }
}

async function refreshBalanceOnly() {
  if (state.demo) return;
  try { state.bootstrap.balance=await api('/balance'); } catch (_) {}
}

async function openGeneration(id) {
  let item=state.gallery.find(row=>row.id===id)??state.bootstrap.recent?.find(row=>row.id===id);
  if (!state.demo) {
    try { item=await api(`/generations/${encodeURIComponent(id)}`); }
    catch (error) { showToast(error.message,'error'); return; }
  }
  state.activeGeneration=item;
  setScreen('generation');
  if (item && !TERMINAL.has(item.status)) void pollGeneration(id);
}

async function pollGeneration(id) {
  if (state.demo) return;
  for (let attempt=0;attempt<180;attempt+=1) {
    try {
      const item=await api(`/generations/${encodeURIComponent(id)}`);
      upsertGeneration(item);
      if (state.activeGeneration?.id===id) state.activeGeneration=item;
      if (state.screen==='generation') render();
      if (TERMINAL.has(item.status)) {
        await refreshBalanceOnly();
        if (item.status==='succeeded') notify('success');
        return;
      }
    } catch (error) {
      if (error.status===404) return;
    }
    await sleep(3500);
  }
}

function upsertGeneration(item) {
  const replace=list => {
    const index=list.findIndex(row=>row.id===item.id);
    if (index>=0) list[index]=item; else list.unshift(item);
  };
  replace(state.gallery);
  state.bootstrap.recent=state.bootstrap.recent??[];
  replace(state.bootstrap.recent);
  state.bootstrap.recent=state.bootstrap.recent.slice(0,12);
}

async function cancelActive() {
  const id=state.activeGeneration?.id;
  if (!id || state.demo || state.busy) return;
  state.busy=true; render();
  try {
    const item=await api(`/generations/${encodeURIComponent(id)}/cancel`,{method:'POST'});
    state.activeGeneration=item; upsertGeneration(item); await refreshBalanceOnly(); notify('success');
  } catch (error) { showToast(error.message,'error'); }
  finally { state.busy=false; render(); }
}

function remix(id) {
  const item=state.gallery.find(row=>row.id===id)??state.activeGeneration;
  const model=modelBySlug(item?.model_slug)??models().find(row=>row.media_kind===item?.media_kind)??firstModel();
  const media=item?.media?.[0];
  if (!item || !model || item.status!=='succeeded') { showToast('Для ремикса нужен готовый результат.','error'); return; }
  state.draft=createDraft(model);
  state.draft.values.prompt=item.prompt??'';
  if (media?.url) {
    const kind=item.media_kind==='video'?'video':'image';
    state.draft.media=[{kind,url:media.url,source:'generation',storage_key:null,size_bytes:media.size_bytes??0}];
    if (hasFrameMode(model)) state.draft.mediaMode=kind==='image'?'first_frame':'references';
  }
  setScreen('studio');
}

function retryGeneration(id) {
  const item=state.gallery.find(row=>row.id===id)??state.activeGeneration;
  const model=modelBySlug(item?.model_slug)??firstModel();
  if (!model) return;
  state.draft=createDraft(model);
  state.draft.values.prompt=item?.prompt??'';
  setScreen('studio');
}

async function downloadGeneration(id) {
  const item=state.gallery.find(row=>row.id===id)??state.activeGeneration;
  const media=item?.media?.[0];
  if (!media?.url) { showToast('Файл ещё недоступен.','error'); return; }
  const ext=item.media_kind==='video'?'mp4':'png';
  const filename=`happy-fox-${id.slice(0,8)}.${ext}`;
  try { if (tg?.downloadFile) tg.downloadFile({url:media.url,file_name:filename}); else window.open(media.url,'_blank','noopener,noreferrer'); }
  catch (_) { window.open(media.url,'_blank','noopener,noreferrer'); }
}

function setMediaMode(mode) {
  if (state.draft.mediaMode===mode) return;
  void clearDraftMedia().then(()=>{ state.draft.mediaMode=mode; render(); });
}

function setDraftField(name,value) {
  if (!state.draft) return;
  const field=modelBySlug(state.draft.modelSlug)?.input_schema?.properties?.[name]??{};
  if (field.type==='integer') value=value===''?'':Number.parseInt(value,10);
  if (field.type==='number') value=value===''?'':Number(value);
  state.draft.values[name]=value;
  delete state.validationErrors[name];
}

function resetDraft() {
  const item=modelBySlug(state.draft?.modelSlug);
  if (!item) return;
  void clearDraftMedia().then(()=>{ state.draft=createDraft(item); state.validationErrors={}; render(); });
}

function showToast(message,type='') {
  const stack=document.getElementById('toast-stack');
  if (!stack) return;
  const node=document.createElement('div'); node.className=`toast ${type}`; node.textContent=message; stack.append(node);
  setTimeout(()=>node.remove(),3400);
}

function showPopup(title,message) {
  if (tg?.showPopup) tg.showPopup({title,message,buttons:[{type:'ok'}]}); else showToast(`${title}: ${message}`);
}

function modelTitle(slug) { return modelBySlug(slug)?.title || slug || 'AI-модель'; }
function humanize(value) { return String(value??'').replaceAll('_',' ').replaceAll('-',' ').replace(/\b\w/g,ch=>ch.toUpperCase()); }
function formatCredits(value) { return new Intl.NumberFormat('ru-RU').format(Number(value??0)); }
function formatBytes(value) { const bytes=Number(value??0); if (!bytes) return 'файл'; if (bytes<1024*1024) return `${Math.max(1,Math.round(bytes/1024))} КБ`; return `${(bytes/1024/1024).toFixed(1)} МБ`; }
function relativeTime(value) { if (!value) return ''; const delta=Math.max(0,Date.now()-new Date(value).getTime()); const mins=Math.floor(delta/60000); if (mins<1) return 'только что'; if (mins<60) return `${mins} мин назад`; const hours=Math.floor(mins/60); if (hours<24) return `${hours} ч назад`; return `${Math.floor(hours/24)} дн назад`; }
function sleep(ms) { return new Promise(resolve=>setTimeout(resolve,ms)); }

function statusLabel(status) {
  return {draft:'Черновик',queued:'В очереди',submitting:'Запускаем',submitted:'Отправлено',processing:'Генерация',submission_unknown:'Проверяем',result_ready:'Результат готов',storing_media:'Сохраняем',delivery_pending:'Финализируем',succeeded:'Готово',failed:'Ошибка',cancelled:'Отменено'}[status]??humanize(status);
}
function statusDescription(status) {
  return {queued:'Задача принята и ждёт запуска.',submitting:'Безопасно передаём задачу провайдеру.',submitted:'Провайдер принял задачу.',processing:'Нейросеть создаёт результат.',submission_unknown:'Уточняем состояние без повторной отправки и списания.',result_ready:'Результат получен, готовим медиа.',storing_media:'Сохраняем файл в приватное хранилище.',delivery_pending:'Финализируем результат.',succeeded:'Результат сохранён и доступен в галерее.',failed:'Генерация завершилась ошибкой.',cancelled:'Задача отменена в безопасной точке.'}[status]??'Состояние задачи обновляется.';
}

root.addEventListener('click',async event=>{
  const nav=event.target.closest('[data-nav]');
  if (nav) { setScreen(nav.dataset.nav); return; }
  const target=event.target.closest('[data-action]');
  if (!target) return;
  const action=target.dataset.action; haptic('light');
  if (action==='reload') { location.reload(); return; }
  if (action==='close') { if (tg?.close) tg.close(); else goBack(); return; }
  if (action==='open-studio') { openStudio(state.draft?.modelSlug??firstModel()?.slug); return; }
  if (action==='choose-model') { await switchModel(target.dataset.model); return; }
  if (action==='model-kind') { state.modelKind=target.dataset.kind; render(); return; }
  if (action==='toggle-field') { const name=target.dataset.field; setDraftField(name,!Boolean(state.draft.values[name])); render(); return; }
  if (action==='enum-field') { const name=target.dataset.field; const field=modelBySlug(state.draft.modelSlug)?.input_schema?.properties?.[name]??{}; const choices=schemaEnum(field)??[]; const raw=target.dataset.value; const typed=choices.find(option=>String(option)===raw)??raw; setDraftField(name,typed); render(); return; }
  if (action==='media-mode') { setMediaMode(target.dataset.mode); return; }
  if (action==='pick-media') { const policy=mediaPolicyFromButton(target); configurePicker(policy); picker.click(); return; }
  if (action==='remove-reference') { await removeReference(Number(target.dataset.referenceIndex)); return; }
  if (action==='reset-draft') { resetDraft(); return; }
  if (action==='submit-task') { await submitTask(); return; }
  if (action==='refresh-gallery') { await loadGallery(true); return; }
  if (action==='refresh-wallet') { await loadWallet(); return; }
  if (action==='open-generation') { await openGeneration(target.dataset.generationId); return; }
  if (action==='cancel-generation') { await cancelActive(); return; }
  if (action==='remix') { remix(target.dataset.generationId); return; }
  if (action==='retry-generation') { retryGeneration(target.dataset.generationId); return; }
  if (action==='download') { await downloadGeneration(target.dataset.generationId); return; }
});

root.addEventListener('input',event=>{
  if (event.target.matches('[data-input="model-search"]')) { state.modelSearch=event.target.value; render(); return; }
  const name=event.target.dataset.fieldInput;
  if (name) setDraftField(name,event.target.value);
});

root.addEventListener('change',event=>{
  const name=event.target.dataset.fieldSelect;
  if (name) {
    const field=modelBySlug(state.draft.modelSlug)?.input_schema?.properties?.[name]??{};
    const choices=schemaEnum(field)??[];
    const typed=choices.find(option=>String(option)===event.target.value)??event.target.value;
    setDraftField(name,typed); render(); return;
  }
  const filter=event.target.dataset.galleryFilter;
  if (filter) { state.filters[filter]=event.target.value; render(); }
});

picker.addEventListener('change',async()=>{
  const files=picker.files ? [...picker.files] : [];
  if (files.length) await uploadFiles(files);
});

init();
