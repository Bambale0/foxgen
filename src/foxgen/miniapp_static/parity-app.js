const root = document.getElementById('app');
const picker = document.getElementById('media-picker');
const tg = window.Telegram?.WebApp ?? null;

const TERMINAL = new Set(['succeeded', 'failed', 'cancelled']);
const ACTIVE = new Set(['queued','submitting','submitted','processing','submission_unknown','result_ready','storing_media','delivery_pending']);
const MEDIA_FIELDS = new Set(['image_url','image_urls','image_input','input_urls','video_url','video_urls','audio_url','first_frame_url','last_frame_url','reference_image_urls','reference_video_urls','reference_audio_urls']);
const FIELD_LABELS = {prompt:'Промпт',aspect_ratio:'Соотношение сторон',quality:'Качество',output_format:'Формат',resolution:'Разрешение',nsfw_checker:'Проверка безопасности',return_last_frame:'Вернуть последний кадр',generate_audio:'Сгенерировать аудио',duration:'Длительность',web_search:'Веб-поиск'};
const VALUE_LABELS = {basic:'Стандарт',high:'Высокое',png:'PNG',jpg:'JPG',true:'Да',false:'Нет'};

const state = {
  token:null, initData:tg?.initData ?? '', demo:false, busy:false, uploadBusy:false,
  screen:'feed', stack:[], bootstrap:null, models:[], works:[], ledger:[],
  feed:[], feedSort:'recent', feedNext:null, feedBusy:false,
  publication:null, comments:[], publicProfile:null, profilePublications:[],
  ownProfile:null, ownPublications:[], references:null, referenceSelection:[],
  referenceReturn:null, generation:null, draft:null, pickerPolicy:null,
  tariff:null, supportTickets:[], supportTicket:null, partner:null, portalBusy:false,
  filters:{kind:'all',status:'all'}, toast:null,
};

const DEMO = {
  brand:'Happy Fox',
  user:{id:1,display_name:'Happy Fox',username:'happy_fox',photo_url:null,is_premium:true},
  balance:{available_units:2450,reserved_units:20,total_units:2470,currency:'CREDIT'},
  prices:[], ledger:[], recent:[], models:[],
  features:{task_submission:false,input_media:false,feed:false,reference_memory:false},
  limits:{input_media_max_bytes:50*1024*1024,generation_history_max:100,ledger_history_max:200},
};

function esc(v){return String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#039;');}
function randomId(){return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;}
function fmtCredits(v){return Number(v??0).toLocaleString('ru-RU');}
function fmtBytes(v){const n=Number(v??0);if(n<1024)return `${n} Б`;if(n<1024**2)return `${(n/1024).toFixed(1)} КБ`;return `${(n/1024**2).toFixed(1)} МБ`;}
function fmtDate(v){if(!v)return '';try{return new Intl.DateTimeFormat('ru-RU',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}).format(new Date(v));}catch{return String(v);}}
function human(v){return String(v??'').replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase());}
function user(){return state.bootstrap?.user ?? DEMO.user;}
function balance(){return state.bootstrap?.balance ?? DEMO.balance;}
function prices(){return state.bootstrap?.prices ?? [];}
function priceFor(slug){return Number(prices().find(x=>x.model_slug===slug)?.amount_units ?? 0);}
function modelBySlug(slug){return state.models.find(x=>x.slug===slug) ?? null;}
function modelTitle(slug){return modelBySlug(slug)?.title ?? slug ?? 'AI';}
function feature(name){return Boolean(state.bootstrap?.features?.[name]);}
function mediaKind(contentType){if(String(contentType).startsWith('video/'))return 'video';if(String(contentType).startsWith('audio/'))return 'audio';return 'image';}
function statusLabel(s){return {queued:'В очереди',submitting:'Запуск',submitted:'Отправлено',processing:'Генерация',submission_unknown:'Проверяем запуск',result_ready:'Получаем результат',storing_media:'Сохраняем',delivery_pending:'Готовим',succeeded:'Готово',failed:'Ошибка',cancelled:'Отменено'}[s]??s;}
function toast(message,type='ok'){state.toast={message,type};render();setTimeout(()=>{if(state.toast?.message===message){state.toast=null;render();}},2200);}
function haptic(type='light'){try{tg?.HapticFeedback?.impactOccurred?.(type);}catch{}}
function confirmAction(message){return new Promise(resolve=>{if(tg?.showConfirm){tg.showConfirm(message,resolve);}else resolve(window.confirm(message));});}

function setupTelegram(){
  if(!tg)return;
  try{
    tg.ready();tg.expand();tg.setHeaderColor?.('#080808');tg.setBackgroundColor?.('#070707');tg.setBottomBarColor?.('#080808');
    tg.BackButton?.onClick(goBack);tg.onEvent?.('themeChanged',syncChrome);tg.onEvent?.('safeAreaChanged',syncChrome);tg.onEvent?.('contentSafeAreaChanged',syncChrome);
  }catch{}
}
function syncChrome(){try{tg?.setHeaderColor?.('#080808');tg?.setBackgroundColor?.('#070707');tg?.setBottomBarColor?.('#080808');}catch{}}
function syncBack(){try{state.stack.length?tg?.BackButton?.show?.():tg?.BackButton?.hide?.();}catch{}}

async function authenticate(){
  if(!state.initData)throw new Error('Откройте Happy Fox внутри Telegram.');
  const auth=await rawApi('/auth',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({init_data:state.initData})});
  state.token=auth.access_token;
}
async function rawApi(path,options={}){
  const response=await fetch(`/v1/miniapp${path}`,options);
  if(response.status===204)return null;
  const ct=response.headers.get('content-type')??'';
  const data=ct.includes('application/json')?await response.json():await response.text();
  if(!response.ok){const detail=typeof data==='object'?(data?.detail??data?.message??data?.error):data;const err=new Error(formatDetail(detail)||`HTTP ${response.status}`);err.status=response.status;err.payload=data;throw err;}
  return data;
}
async function api(path,options={},retryAuth=true){
  if(!state.token)throw new Error('Требуется авторизация Telegram.');
  const headers=new Headers(options.headers??{});headers.set('Authorization',`Bearer ${state.token}`);
  try{return await rawApi(path,{...options,headers});}catch(error){if(error.status===401&&retryAuth&&state.initData){await authenticate();return api(path,options,false);}throw error;}
}
function formatDetail(detail){if(!detail)return '';if(typeof detail==='string')return detail;if(Array.isArray(detail))return detail.map(x=>x?.msg??x?.message??JSON.stringify(x)).join(' · ');return detail.message??JSON.stringify(detail);}

async function init(){
  setupTelegram();
  try{
    if(state.initData){await authenticate();state.bootstrap=await api('/bootstrap');state.models=state.bootstrap.models??[];state.works=[...(state.bootstrap.recent??[])];state.ledger=[...(state.bootstrap.ledger??[])];}
    else{state.demo=true;state.bootstrap=structuredClone(DEMO);state.models=[];}
    await handleStartParam();
    if(state.screen==='feed'&&!state.demo)await loadFeed(true);
    render();
  }catch(error){renderFatal(error);}
}

async function handleStartParam(){
  const payload=tg?.initDataUnsafe?.start_param || new URLSearchParams(location.search).get('tgWebAppStartParam') || '';
  if(!payload)return;
  if(payload.startsWith('post_')){await openPublication(payload.slice(5),false);return;}
  if(payload.startsWith('profile_')){await openPublicProfile(payload.slice(8),false);return;}
  if(payload.startsWith('remix_')){await startRemix(payload.slice(6),false);return;}
  if(payload.startsWith('generation_')){await openGeneration(payload.slice(11),false);return;}
  if(payload.startsWith('model_')){openStudio(payload.slice(6),false);}
}

function nav(screen,push=true){if(push&&state.screen!==screen)state.stack.push(state.screen);state.screen=screen;syncBack();render();void ensureScreenData(screen);}
function goBack(){const previous=state.stack.pop();if(previous){state.screen=previous;syncBack();render();void ensureScreenData(previous);}else nav('feed',false);}
async function ensureScreenData(screen){try{if(screen==='feed')await loadFeed(false);if(screen==='works')await loadWorks(false);if(screen==='profile')await loadOwnProfile();if(screen==='references')await loadReferences();if(screen==='wallet')await loadWallet();if(screen==='tariff')await loadTariff();if(screen==='support')await loadSupport();if(screen==='partner')await loadPartner();render();}catch(e){toast(e.message,'error');}}

async function loadFeed(reset=false){if(state.demo||state.feedBusy)return;if(!reset&&state.feed.length)return;state.feedBusy=true;try{const data=await api(`/feed?sort=${encodeURIComponent(state.feedSort)}&limit=20&offset=0`);state.feed=data.items??[];state.feedNext=data.next_offset;}finally{state.feedBusy=false;}}
async function loadWorks(force=false){if(state.demo)return;if(!force&&state.works.length>=20)return;state.works=await api('/generations?limit=100');}
async function loadWallet(){if(state.demo)return;const [b,p,l]=await Promise.all([api('/balance'),api('/prices'),api('/ledger?limit=200')]);state.bootstrap.balance=b;state.bootstrap.prices=p;state.ledger=l;}
async function loadOwnProfile(){if(state.demo)return;const [profile,pubs]=await Promise.all([api('/me/profile'),api('/me/publications?limit=50')]);state.ownProfile=profile;state.ownPublications=pubs.items??[];}
async function loadReferences(){if(state.demo)return;state.references=await api('/reference-memory?limit=100');}
async function loadTariff(){if(state.demo)return;state.portalBusy=true;try{state.tariff=await api('/tariff');}finally{state.portalBusy=false;}}
async function loadSupport(){if(state.demo)return;state.portalBusy=true;try{const data=await api('/support');state.supportTickets=data?.items??[];}finally{state.portalBusy=false;}}
async function loadSupportTicket(id){if(state.demo)return;state.portalBusy=true;try{state.supportTicket=await api(`/support/${encodeURIComponent(id)}`);nav('supportTicket');}finally{state.portalBusy=false;render();}}
async function loadPartner(){if(state.demo)return;state.portalBusy=true;try{state.partner=await api('/partner');}finally{state.portalBusy=false;}}

function brand(){return `<div class="hf-brand"><span class="hf-logo">🦊</span><div><strong>Happy <em>Fox</em></strong><small>AI CREATIVE STUDIO</small></div></div>`;}
function topbar(extra=''){return `<header class="hf-top">${brand()}<div class="hf-top-actions">${extra}<button class="credit-pill" data-nav="wallet">${fmtCredits(balance().available_units)} <b>●</b></button></div></header>`;}
function bottomNav(){const items=[['feed','Лента','◫'],['create','Создать','✦'],['works','Работы','▦'],['profile','Профиль','◎']];return `<nav class="hf-nav">${items.map(([s,t,i])=>`<button class="${(['studio','references'].includes(state.screen)&&s==='create')||state.screen===s?'active':''}" data-nav="${s}"><span>${i}</span><small>${t}</small></button>`).join('')}</nav>`;}
function shell(content,{navBar=true}={}){return `${content}${navBar?bottomNav():''}${state.toast?`<div class="hf-toast ${state.toast.type==='error'?'error':''}">${esc(state.toast.message)}</div>`:''}`;}
function empty(title,text,action=''){return `<div class="hf-empty"><span>✦</span><strong>${esc(title)}</strong><p>${esc(text)}</p>${action}</div>`;}
function spinner(){return '<div class="hf-spinner"></div>';}
function avatar(profile){const name=profile?.display_name||profile?.slug||'?';return `<span class="hf-avatar">${esc(name.slice(0,1).toUpperCase())}</span>`;}
function renderMedia(media){if(!media?.url)return '<div class="hf-media-placeholder">HAPPY FOX</div>';const type=mediaKind(media.content_type);if(type==='video')return `<video src="${esc(media.url)}" playsinline muted loop preload="metadata"></video>`;if(type==='audio')return `<div class="hf-audio">♫</div>`;return `<img src="${esc(media.url)}" alt="AI result" loading="lazy">`;}

function render(){
  syncBack();
  const screens={feed:renderFeed,create:renderCreate,studio:renderStudio,works:renderWorks,profile:renderProfile,wallet:renderWallet,references:renderReferencesScreen,publication:renderPublication,publicProfile:renderPublicProfile,generation:renderGeneration,tariff:renderTariff,support:renderSupport,supportTicket:renderSupportTicket,partner:renderPartner};
  const fn=screens[state.screen]??renderFeed;root.innerHTML=shell(fn(),{navBar:!['publication','publicProfile','generation'].includes(state.screen)});bindForms();
}

function renderFeed(){return `<main class="hf-page">${topbar()}<section class="hf-hero grunge-card"><span class="stamp">COMMUNITY / LIVE</span><h1>Лента <i>Happy Fox</i></h1><p>Смотри работы сообщества, поддерживай авторов и запускай ремикс в один переход.</p></section><div class="hf-tabs">${[['recent','Новое'],['top_day','Топ дня'],['top','Топ']].map(([v,t])=>`<button class="${state.feedSort===v?'active':''}" data-feed-sort="${v}">${t}</button>`).join('')}</div>${state.feedBusy&&!state.feed.length?spinner():state.feed.length?`<section class="feed-grid">${state.feed.map(feedCard).join('')}</section>`:empty('Лента пока пустая','Опубликуй первую готовую работу из раздела «Работы».')}</main>`;}
function feedCard(p){const media=p.media?.[0];return `<article class="feed-card grunge-lite" data-open-publication="${esc(p.id)}"><div class="feed-author" data-open-profile="${esc(p.author?.slug)}">${avatar(p.author)}<div><strong>${esc(p.author?.display_name||p.author?.slug)}</strong><small>${fmtDate(p.created_at)}</small></div><span class="model-tag">${esc(modelTitle(p.model_slug))}</span></div><div class="feed-media">${renderMedia(media)}</div>${p.prompt?`<p class="feed-prompt">${esc(p.prompt)}</p>`:''}<div class="feed-actions"><button data-like="${esc(p.id)}" data-liked="${p.liked_by_viewer?'1':'0'}">${p.liked_by_viewer?'♥':'♡'} ${p.likes_count??0}</button><button data-comments="${esc(p.id)}">◌ ${p.comments_count??0}</button>${p.prompt_actions_allowed?`<button class="accent" data-remix="${esc(p.id)}">↻ Ремикс</button>`:''}</div></article>`;}

function renderCreate(){const grouped=visibleUiModels();return `<main class="hf-page">${topbar()}<section class="hf-hero compact grunge-card"><span class="stamp">CREATE / ALL MODELS</span><h1>Что создаём?</h1><p>Параметры и лимиты приходят из backend-схемы модели.</p><button class="hf-primary" data-quick-start>⚡ Быстрый запуск по файлу</button></section><div class="product-head"><h2>Изображения</h2><small>${grouped.filter(x=>x.media_kind==='image').length}</small></div><div class="model-list">${grouped.filter(x=>x.media_kind==='image').map(modelCard).join('')}</div><div class="product-head"><h2>Видео</h2><small>${grouped.filter(x=>x.media_kind==='video').length}</small></div><div class="model-list">${grouped.filter(x=>x.media_kind==='video').map(modelCard).join('')}</div>${!grouped.length?empty('Нет активных моделей','Backend пока не разрешил модели для запуска.'):''}</main>`;}
function visibleUiModels(){const seen=new Set();return [...state.models].filter(m=>{const key=m.ui_key||m.slug;if(seen.has(key))return false;seen.add(key);return true;}).sort((a,b)=>(a.rank??99)-(b.rank??99));}
function modelCard(m){return `<button class="model-row grunge-lite" data-model="${esc(m.slug)}"><span class="model-glyph">${m.media_kind==='video'?'▶':'◉'}</span><div><strong>${esc(m.title)}</strong><small>${esc(m.family||'AI')} · ${fmtCredits(priceFor(m.slug))} ●</small><p>${esc((m.recommended_for??[]).slice(0,2).map(human).join(' · '))}</p></div><span>›</span></button>`;}

function newDraft(model){const props=model?.input_schema?.properties??{};const values={};for(const [name,schema] of Object.entries(props)){if(MEDIA_FIELDS.has(name))continue;if(schema.default!==undefined&&schema.default!==null)values[name]=schema.default;else if(model.defaults?.[name]!==undefined)values[name]=model.defaults[name];else if(schema.type==='boolean')values[name]=false;else if(name==='prompt')values[name]='';}return {modelSlug:model.slug,values,uploads:[],referenceIds:[],mediaMode:hasFrameMode(model)?'text':'references',idempotencyKey:randomId(),sourcePublicationId:null,sourcePublication:null};}
function hasFrameMode(m){const p=m?.input_schema?.properties??{};return Boolean(p.first_frame_url||p.last_frame_url||p.reference_image_urls);}
function openStudio(slug,push=true){const model=modelBySlug(slug)||visibleUiModels()[0];if(!model)return;state.draft=newDraft(model);nav('studio',push);}
function effectiveModel(){if(!state.draft)return null;let m=modelBySlug(state.draft.modelSlug);const hasImages=state.draft.uploads.some(x=>x.kind==='image')||state.draft.referenceIds.length>0;if(m?.slug==='seedream-5-pro'&&hasImages&&modelBySlug('seedream-5-pro-edit'))m=modelBySlug('seedream-5-pro-edit');return m;}
function referenceCapacity(model,draft){const p=model?.input_schema?.properties??{};if(draft.mediaMode==='first_frame')return 1;if(draft.mediaMode==='first_last')return 2;for(const name of ['image_input','image_urls','reference_image_urls']){if(p[name])return Number(p[name].maxItems??14);}return 0;}
function renderStudio(){const model=effectiveModel()||modelBySlug(state.draft?.modelSlug);if(!state.draft||!model)return `<main class="hf-page">${topbar()}${empty('Выбери модель','Вернись в «Создать».')}</main>`;const base=modelBySlug(state.draft.modelSlug)||model;const cost=priceFor(model.slug);return `<main class="hf-page studio-page">${topbar('<button class="ghost-mini" data-reset-draft>Сбросить</button>')}<section class="studio-header"><span class="stamp">MODEL / LIVE SCHEMA</span><h1>${esc(base.title)}</h1><p>${esc(base.family)} · ${fmtCredits(cost)} ●</p></section>${renderMediaStudio(base)}${renderFields(model)}<section class="launch-card grunge-card"><div><small>К запуску</small><strong>${fmtCredits(cost)} ●</strong><span>Баланс ${fmtCredits(balance().available_units)} ●</span></div><button class="hf-primary" data-submit ${state.busy?'disabled':''}>${state.busy?'Проверяем…':'Запустить'}</button></section></main>`;}
function renderMediaStudio(model){const props=model.input_schema?.properties??{};const mediaFields=Object.keys(props).filter(x=>MEDIA_FIELDS.has(x));if(!mediaFields.length)return '';const draft=state.draft;let mode='';if(hasFrameMode(model)){mode=`<div class="mode-switch">${[['text','Текст'],['first_frame','Первый кадр'],['first_last','Первый + последний'],['references','Референсы']].filter(([m])=>m!=='references'||props.reference_image_urls).map(([m,t])=>`<button class="${draft.mediaMode===m?'active':''}" data-media-mode="${m}">${t}</button>`).join('')}</div>`;}const cap=referenceCapacity(model,draft);const canFiles=draft.mediaMode!=='text';return `<section class="studio-block grunge-lite"><div class="block-head"><div><strong>Референсы</strong><small>${draft.uploads.length+draft.referenceIds.length}/${cap||'—'}</small></div>${feature('reference_memory')&&canFiles?'<button class="text-link" data-open-memory>Память реф ›</button>':''}</div>${mode}${canFiles?`<button class="upload-box" data-pick-studio>＋ Добавить файл<small>Фото / видео / аудио — только если принимает модель</small></button>`:''}${renderDraftMedia()}</section>`;}
function renderDraftMedia(){const items=[...state.draft.uploads.map(x=>({...x,source:'upload'})),...state.draft.referenceIds.map(id=>({kind:'image',reference_id:id,source:'memory',url:referenceItem(id)?.preview_url}))];if(!items.length)return '';return `<div class="draft-media">${items.map((x,i)=>`<div class="draft-media-item">${x.kind==='image'&&x.url?`<img src="${esc(x.url)}" alt="reference">`:`<span>${x.kind==='video'?'▶':x.kind==='audio'?'♫':'◉'}</span>`}<small>${x.source==='memory'?'Память':'Файл'} ${i+1}</small><button data-remove-draft-media="${i}">×</button></div>`).join('')}</div>`;}
function referenceItem(id){return state.references?.items?.find(x=>x.id===id)??null;}
function renderFields(model){const props=model.input_schema?.properties??{};return `<section class="studio-block">${Object.entries(props).filter(([name])=>!MEDIA_FIELDS.has(name)).map(([name,schema])=>fieldControl(name,schema)).join('')}</section>`;}
function fieldControl(name,schema){const value=state.draft.values[name]??'';const label=FIELD_LABELS[name]??human(name);const required=(effectiveModel()?.input_schema?.required??[]).includes(name);if(schema.type==='boolean')return `<label class="switch-row"><div><strong>${esc(label)}</strong><small>${required?'Обязательно':'Опционально'}</small></div><input type="checkbox" data-field="${esc(name)}" ${value?'checked':''}><span class="switch"></span></label>`;const values=schema.enum??schema.anyOf?.find(x=>Array.isArray(x.enum))?.enum;if(Array.isArray(values))return `<label class="field"><span>${esc(label)}</span><select data-field="${esc(name)}">${values.map(v=>`<option value="${esc(v)}" ${String(v)===String(value)?'selected':''}>${esc(VALUE_LABELS[String(v)]??v)}</option>`).join('')}</select></label>`;if(name==='prompt'||Number(schema.maxLength??0)>300)return `<label class="field"><span>${esc(label)}${required?' *':''}</span><textarea data-field="${esc(name)}" maxlength="${Number(schema.maxLength??10000)}" placeholder="Опиши результат…">${esc(value)}</textarea></label>`;if(schema.type==='number'||schema.type==='integer')return `<label class="field"><span>${esc(label)}</span><input type="number" data-field="${esc(name)}" value="${esc(value)}" ${schema.minimum!==undefined?`min="${schema.minimum}"`:''} ${schema.maximum!==undefined?`max="${schema.maximum}"`:''}></label>`;return `<label class="field"><span>${esc(label)}${required?' *':''}</span><input data-field="${esc(name)}" value="${esc(value)}" maxlength="${Number(schema.maxLength??5000)}"></label>`;}

function renderWorks(){const rows=state.works.filter(x=>(state.filters.kind==='all'||x.media_kind===state.filters.kind)&&(state.filters.status==='all'||x.status===state.filters.status));return `<main class="hf-page">${topbar('<button class="ghost-mini" data-refresh-works>↻</button>')}<section class="page-title"><span class="stamp">LIBRARY</span><h1>Мои работы</h1></section><div class="hf-tabs"><button class="${state.filters.status==='all'?'active':''}" data-work-status="all">Все</button><button class="${state.filters.status==='succeeded'?'active':''}" data-work-status="succeeded">Готово</button><button class="${state.filters.status==='processing'?'active':''}" data-work-status="processing">В работе</button><button class="${state.filters.status==='failed'?'active':''}" data-work-status="failed">Ошибки</button></div>${rows.length?`<div class="works-grid">${rows.map(workCard).join('')}</div>`:empty('Работ пока нет','Создай первую генерацию.')}</main>`;}
function workCard(g){const media=g.media?.[0];return `<button class="work-card" data-generation="${esc(g.id)}"><div class="work-media">${renderMedia(media)}</div><div class="work-meta"><strong>${esc(modelTitle(g.model_slug))}</strong><small>${statusLabel(g.status)} · ${fmtDate(g.created_at)}</small></div></button>`;}

function renderGeneration(){const g=state.generation;if(!g)return `<main class="hf-page">${topbar()}${spinner()}</main>`;const media=g.media?.[0];return `<main class="hf-page">${topbar()}<section class="generation-media">${renderMedia(media)}</section><section class="detail-card grunge-lite"><span class="status-badge ${esc(g.status)}">${esc(statusLabel(g.status))}</span><h1>${esc(modelTitle(g.model_slug))}</h1>${g.prompt?`<p>${esc(g.prompt)}</p>`:''}<dl><div><dt>ID</dt><dd>${esc(g.id)}</dd></div><div><dt>Создано</dt><dd>${fmtDate(g.created_at)}</dd></div></dl></section><div class="action-grid">${ACTIVE.has(g.status)?`<button class="danger-button" data-cancel-generation="${esc(g.id)}">Отменить</button>`:''}${g.status==='succeeded'?`<button data-repeat-generation="${esc(g.id)}">Повторить</button><button data-publish="${esc(g.id)}" data-scope="profile">В профиль</button><button class="accent" data-publish="${esc(g.id)}" data-scope="feed">В ленту</button>`:''}</div>${g.error_code?`<div class="error-box">${esc(g.error_code)}</div>`:''}</main>`;}

function renderProfile(){const p=state.ownProfile;return `<main class="hf-page">${topbar()}<section class="profile-hero grunge-card">${avatar(p||user())}<div><span class="stamp">CREATOR</span><h1>${esc(p?.display_name||user().display_name||'Мой профиль')}</h1><p>${p?.slug?'@'+esc(p.slug):'Публичный профиль создастся автоматически'}</p></div><button class="ghost-mini" data-edit-profile>Изменить</button></section><section class="profile-grid"><button data-nav="wallet"><span>●</span><strong>${fmtCredits(balance().available_units)}</strong><small>Кредиты</small></button><button data-nav="references"><span>▧</span><strong>${state.references?.total??'—'}</strong><small>Референсы</small></button><button data-own-publications><span>◫</span><strong>${state.ownPublications.length||'—'}</strong><small>Публикации</small></button></section><section class="section"><div class="section-head"><h2>Мои публикации</h2></div>${state.ownPublications.length?`<div class="mini-pub-grid">${state.ownPublications.slice(0,8).map(p=>`<button data-open-publication="${esc(p.id)}">${renderMedia(p.media?.[0])}<small>${p.scope==='feed'?'Лента':'Профиль'}</small></button>`).join('')}</div>`:empty('Нет публикаций','Готовую работу можно опубликовать из «Работы».')}</section><section class="settings-list"><button data-nav="wallet">Баланс и операции <span>›</span></button><button data-nav="references">Память референсов <span>›</span></button><button disabled>Платежи <small>Backend invoice flow в разработке</small></button><button data-nav="tariff">Тарифы <span>›</span></button><button data-nav="partner">Партнёры <span>›</span></button><button data-nav="support">Поддержка <span>›</span></button></section></main>`;}

function renderWallet(){return `<main class="hf-page">${topbar('<button class="ghost-mini" data-refresh-wallet>↻</button>')}<section class="wallet-hero grunge-card"><span class="stamp">WALLET</span><small>Доступно</small><h1>${fmtCredits(balance().available_units)} <b>●</b></h1><p>В резерве ${fmtCredits(balance().reserved_units)} ●</p></section><section class="section"><h2>Цены моделей</h2><div class="price-list">${state.models.filter((m,i,a)=>a.findIndex(x=>x.ui_key===m.ui_key)===i).map(m=>`<div><span>${esc(m.title)}</span><strong>${fmtCredits(priceFor(m.slug))} ●</strong></div>`).join('')}</div></section><section class="section"><h2>Операции</h2>${state.ledger.length?`<div class="ledger-list">${state.ledger.map(x=>`<div><span><strong>${esc(x.reason||x.entry_type)}</strong><small>${fmtDate(x.created_at)}</small></span><b class="${Number(x.available_delta??0)>=0?'plus':'minus'}">${Number(x.available_delta??0)>0?'+':''}${fmtCredits(x.available_delta??0)}</b></div>`).join('')}</div>`:empty('Операций пока нет','История баланса появится здесь.')}</section><div class="notice grunge-lite">Пополнение не имитируется: кнопка появится только вместе с user-safe payment API.</div></main>`;}

function renderReferencesScreen(){const page=state.references;const items=page?.items??[];const selected=new Set(state.referenceSelection);return `<main class="hf-page">${topbar()}<section class="page-title"><span class="stamp">REFERENCE MEMORY</span><h1>Память референсов</h1><p>${page?`${page.total}/${page.max_items} · ${fmtBytes(page.used_bytes)} / ${fmtBytes(page.max_bytes)}`:'Загружаем…'}</p></section><button class="hf-primary" data-upload-memory>＋ Добавить изображение</button>${state.referenceReturn?`<div class="selection-bar"><span>Выбрано ${selected.size}/${referenceSelectionMax()}</span><button data-apply-memory>Использовать</button></div>`:''}${items.length?`<div class="reference-grid">${items.map(r=>`<article class="memory-card ${selected.has(r.id)?'selected':''}"><button class="memory-preview" data-toggle-reference="${esc(r.id)}"><img src="${esc(r.preview_url)}" alt="reference"><span>${selected.has(r.id)?'✓':''}</span></button><footer><small>${fmtDate(r.created_at)} · ${fmtBytes(r.size_bytes)}</small><button class="danger-text" data-delete-reference="${esc(r.id)}">Удалить</button></footer></article>`).join('')}</div>`:empty('Память пустая','Сохраняй изображения и повторно используй их в совместимых моделях.')}</main>`;}
function referenceSelectionMax(){const m=effectiveModel()||modelBySlug(state.draft?.modelSlug);return Math.max(0,referenceCapacity(m,state.draft)-state.draft.uploads.filter(x=>x.kind==='image').length);}

function renderPublication(){const p=state.publication;if(!p)return `<main class="hf-page">${topbar()}${spinner()}</main>`;return `<main class="hf-page">${topbar()}<article class="publication-full"><div class="feed-author" data-open-profile="${esc(p.author?.slug)}">${avatar(p.author)}<div><strong>${esc(p.author?.display_name||p.author?.slug)}</strong><small>${fmtDate(p.created_at)}</small></div></div><div class="publication-media">${renderMedia(p.media?.[0])}</div>${p.prompt?`<p class="publication-prompt">${esc(p.prompt)}</p>`:''}<div class="feed-actions"><button data-like="${esc(p.id)}" data-liked="${p.liked_by_viewer?'1':'0'}">${p.liked_by_viewer?'♥':'♡'} ${p.likes_count??0}</button>${p.prompt_actions_allowed?`<button class="accent" data-remix="${esc(p.id)}">↻ Ремикс</button>`:''}</div></article><section class="comments"><div class="section-head"><h2>Комментарии</h2><small>${state.comments.length}</small></div><form id="comment-form"><input name="body" maxlength="1000" placeholder="Написать комментарий…"><button>Отправить</button></form>${state.comments.length?state.comments.map(c=>`<div class="comment">${avatar(c.author)}<div><strong>${esc(c.author?.display_name||c.author?.slug)}</strong><p>${esc(c.body)}</p><small>${fmtDate(c.created_at)}</small></div></div>`).join(''):empty('Комментариев нет','Будь первым.')}</section></main>`;}
function renderPublicProfile(){const p=state.publicProfile;return `<main class="hf-page">${topbar()}${p?`<section class="profile-hero grunge-card">${avatar(p)}<div><span class="stamp">PUBLIC PROFILE</span><h1>${esc(p.display_name||p.slug)}</h1><p>@${esc(p.slug)}</p><small>${esc(p.bio||'')}</small></div></section><div class="profile-publications">${state.profilePublications.map(x=>`<button data-open-publication="${esc(x.id)}">${renderMedia(x.media?.[0])}</button>`).join('')}</div>`:spinner()}</main>`;}

async function openPublication(id,push=true){if(state.demo)return;state.publication=await api(`/publications/${id}`);state.comments=(await api(`/publications/${id}/comments?surface=${state.publication.scope}&limit=100`)).items??[];nav('publication',push);}
async function openPublicProfile(slug,push=true){if(state.demo)return;const [p,pubs]=await Promise.all([api(`/profiles/${encodeURIComponent(slug)}`),api(`/profiles/${encodeURIComponent(slug)}/publications?limit=30`)]);state.publicProfile=p;state.profilePublications=pubs.items??[];nav('publicProfile',push);}
async function openGeneration(id,push=true){if(state.demo)return;state.generation=await api(`/generations/${id}`);nav('generation',push);if(ACTIVE.has(state.generation.status))pollGeneration(id);}
async function pollGeneration(id){for(let i=0;i<60;i++){await new Promise(r=>setTimeout(r,3000));if(state.screen!=='generation'||state.generation?.id!==id)return;try{state.generation=await api(`/generations/${id}`);render();if(TERMINAL.has(state.generation.status))return;}catch{return;}}}

async function startRemix(id,push=true){if(state.demo)return;const source=await api(`/publications/${id}/remix`);const model=modelBySlug(source.model_slug)||visibleUiModels().find(x=>x.media_kind===source.media_kind)||visibleUiModels()[0];if(!model)throw new Error('Для ремикса сейчас нет совместимой модели.');state.draft=newDraft(model);state.draft.values.prompt=source.prompt??'';state.draft.sourcePublicationId=source.publication_id;state.draft.sourcePublication=source;state.draft.uploads=(source.media??[]).map(x=>({kind:mediaKind(x.content_type),url:x.url,content_type:x.content_type,source:'remix'}));nav('studio',push);}
async function buildPayload(){const model=effectiveModel();const draft=state.draft;if(!model||!draft)throw new Error('Черновик не готов.');let remote=draft.uploads.filter(x=>x.source==='remix');if(draft.sourcePublicationId){const fresh=await api(`/publications/${draft.sourcePublicationId}/remix`);remote=(fresh.media??[]).map(x=>({kind:mediaKind(x.content_type),url:x.url,content_type:x.content_type,source:'remix'}));}let saved=[];if(draft.referenceIds.length){const resolved=await api('/reference-memory/resolve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reference_ids:draft.referenceIds})});saved=(resolved.items??[]).map(x=>({kind:'image',url:x.preview_url,content_type:x.content_type,source:'memory'}));}const media=[...draft.uploads.filter(x=>x.source!=='remix'),...remote,...saved];const input={...draft.values};const props=model.input_schema?.properties??{};if(hasFrameMode(model)){if(draft.mediaMode==='first_frame'){input.first_frame_url=media.filter(x=>x.kind==='image')[0]?.url??null;input.last_frame_url=null;input.reference_image_urls=[];input.reference_video_urls=[];input.reference_audio_urls=[];}else if(draft.mediaMode==='first_last'){const imgs=media.filter(x=>x.kind==='image');input.first_frame_url=imgs[0]?.url??null;input.last_frame_url=imgs[1]?.url??null;input.reference_image_urls=[];input.reference_video_urls=[];input.reference_audio_urls=[];}else if(draft.mediaMode==='references'){input.first_frame_url=null;input.last_frame_url=null;input.reference_image_urls=media.filter(x=>x.kind==='image').map(x=>x.url);input.reference_video_urls=media.filter(x=>x.kind==='video').map(x=>x.url);input.reference_audio_urls=media.filter(x=>x.kind==='audio').map(x=>x.url);}else{input.first_frame_url=null;input.last_frame_url=null;input.reference_image_urls=[];input.reference_video_urls=[];input.reference_audio_urls=[];}}else{const images=media.filter(x=>x.kind==='image').map(x=>x.url);if(props.image_input)input.image_input=images;if(props.image_urls)input.image_urls=images;if(props.image_url)input.image_url=images[0]??null;}return {model,input};}
async function submitDraft(){if(state.demo)return;state.busy=true;render();try{const built=await buildPayload();const validated=await api(`/models/${encodeURIComponent(built.model.slug)}/validate`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({input:built.input})});const body={model_slug:built.model.slug,input:validated.input};if(state.draft.sourcePublicationId)body.source_publication_id=state.draft.sourcePublicationId;const result=await api('/tasks',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':state.draft.idempotencyKey},body:JSON.stringify(body)});toast('Генерация поставлена в очередь');await loadWorks(true);state.draft=null;await openGeneration(result.generation_id,false);}catch(e){toast(e.message,'error');}finally{state.busy=false;render();}}

async function uploadFile(file,context){if(!file||state.demo)return null;const max=Number(state.bootstrap?.limits?.input_media_max_bytes??0);if(max&&file.size>max)throw new Error(`Файл больше ${fmtBytes(max)}.`);state.uploadBusy=true;render();try{return await api('/input-media',{method:'POST',headers:{'Content-Type':file.type||'application/octet-stream'},body:file});}finally{state.uploadBusy=false;render();}}
async function deleteUpload(item){if(item.storage_key&&!state.demo){try{await api(`/input-media/${encodeURIComponent(item.storage_key)}`,{method:'DELETE'});}catch{}}}
function bindForms(){
  const comment=document.getElementById('comment-form');if(comment)comment.addEventListener('submit',async e=>{e.preventDefault();const body=new FormData(comment).get('body')?.toString().trim();if(!body)return;try{const c=await api(`/publications/${state.publication.id}/comments`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({surface:state.publication.scope,body})});state.comments.push(c);comment.reset();render();}catch(err){toast(err.message,'error');}});
  const create=document.getElementById('support-create-form');if(create)create.addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(create);const subject=f.get('subject')?.toString().trim();const body=f.get('body')?.toString().trim();if(!subject||!body)return;try{state.portalBusy=true;const item=await api('/support',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({subject,body})});state.supportTicket=item;await loadSupport();nav('supportTicket');toast('Обращение создано');}catch(err){toast(err.message,'error');}finally{state.portalBusy=false;render();}});
  const reply=document.getElementById('support-reply-form');if(reply)reply.addEventListener('submit',async e=>{e.preventDefault();const body=new FormData(reply).get('body')?.toString().trim();if(!body||!state.supportTicket)return;try{state.supportTicket=await api(`/support/${state.supportTicket.id}/messages`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({body})});render();toast('Ответ отправлен');}catch(err){toast(err.message,'error');}});
  const withdrawal=document.getElementById('partner-withdraw-form');if(withdrawal)withdrawal.addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(withdrawal);const amount_units=Number(f.get('amount_units'));const destination=f.get('destination')?.toString().trim();if(!Number.isInteger(amount_units)||amount_units<=0||!destination)return;try{await api('/partner/withdrawals',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({amount_units,destination})});await loadPartner();render();toast('Заявка на выплату создана');}catch(err){toast(err.message,'error');}});
}

root.addEventListener('click',async event=>{
  const el=event.target.closest('button,[data-open-publication],[data-open-profile]');if(!el)return;
  try{
    if(el.dataset.nav){nav(el.dataset.nav);return;}
    if(el.dataset.supportTicket){await loadSupportTicket(el.dataset.supportTicket);return;}
    if(el.hasAttribute('data-refresh-support')){await loadSupport();render();return;}
    if(el.dataset.closeTicket){if(await confirmAction('Закрыть это обращение?')){state.supportTicket=await api(`/support/${el.dataset.closeTicket}/close`,{method:'POST'});await loadSupport();render();toast('Обращение закрыто');}return;}
    if(el.hasAttribute('data-partner-join')){await api('/partner/join',{method:'POST'});await loadPartner();render();toast('Партнёрская программа подключена');return;}
    if(el.dataset.model){openStudio(el.dataset.model);return;}
    if(el.dataset.feedSort){state.feedSort=el.dataset.feedSort;state.feed=[];await loadFeed(true);render();return;}
    if(el.dataset.openPublication){await openPublication(el.dataset.openPublication);return;}
    if(el.dataset.openProfile){await openPublicProfile(el.dataset.openProfile);return;}
    if(el.dataset.generation){await openGeneration(el.dataset.generation);return;}
    if(el.hasAttribute('data-refresh-works')){await loadWorks(true);render();return;}
    if(el.hasAttribute('data-refresh-wallet')){await loadWallet();render();return;}
    if(el.dataset.workStatus){state.filters.status=el.dataset.workStatus;render();return;}
    if(el.dataset.like){const liked=el.dataset.liked!=='1';const result=await api(`/publications/${el.dataset.like}/like`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({liked})});for(const p of [...state.feed,state.publication].filter(Boolean)){if(p.id===el.dataset.like){p.liked_by_viewer=result.liked;p.likes_count=result.likes_count;}}render();return;}
    if(el.dataset.comments){await openPublication(el.dataset.comments);return;}
    if(el.dataset.remix){await startRemix(el.dataset.remix);return;}
    if(el.dataset.mediaMode){for(const x of state.draft.uploads)if(x.storage_key)await deleteUpload(x);state.draft.uploads=[];state.draft.referenceIds=[];state.draft.mediaMode=el.dataset.mediaMode;render();return;}
    if(el.hasAttribute('data-pick-studio')){state.pickerPolicy={context:'studio'};picker.accept='image/*,video/mp4,video/webm,audio/mpeg,audio/mp4,audio/wav';picker.click();return;}
    if(el.hasAttribute('data-quick-start')){state.pickerPolicy={context:'quick'};picker.accept='image/*,video/mp4,video/webm';picker.click();return;}
    if(el.hasAttribute('data-upload-memory')){state.pickerPolicy={context:'memory'};picker.accept='image/jpeg,image/png,image/webp';picker.click();return;}
    if(el.hasAttribute('data-open-memory')){state.referenceReturn='studio';state.referenceSelection=[...state.draft.referenceIds];nav('references');return;}
    if(el.dataset.toggleReference){const id=el.dataset.toggleReference;const set=new Set(state.referenceSelection);if(set.has(id))set.delete(id);else{if(set.size>=referenceSelectionMax()){toast('Достигнут лимит референсов модели','error');return;}set.add(id);}state.referenceSelection=[...set];render();return;}
    if(el.hasAttribute('data-apply-memory')){state.draft.referenceIds=[...state.referenceSelection];state.referenceReturn=null;goBack();return;}
    if(el.dataset.deleteReference){if(await confirmAction('Удалить этот референс из памяти?')){await api(`/reference-memory/${el.dataset.deleteReference}`,{method:'DELETE'});state.referenceSelection=state.referenceSelection.filter(x=>x!==el.dataset.deleteReference);state.draft&&=state.draft;await loadReferences();render();}return;}
    if(el.dataset.removeDraftMedia!==undefined){const index=Number(el.dataset.removeDraftMedia);const combined=[...state.draft.uploads.map((x,i)=>({type:'upload',i,x})),...state.draft.referenceIds.map((x,i)=>({type:'ref',i,x}))];const target=combined[index];if(target?.type==='upload'){await deleteUpload(target.x);state.draft.uploads.splice(target.i,1);}if(target?.type==='ref')state.draft.referenceIds.splice(target.i,1);render();return;}
    if(el.hasAttribute('data-reset-draft')){for(const x of state.draft.uploads)if(x.storage_key)await deleteUpload(x);const m=modelBySlug(state.draft.modelSlug);state.draft=newDraft(m);render();return;}
    if(el.hasAttribute('data-submit')){await submitDraft();return;}
    if(el.dataset.cancelGeneration){if(await confirmAction('Отменить генерацию?')){state.generation=await api(`/generations/${el.dataset.cancelGeneration}/cancel`,{method:'POST'});await loadWorks(true);render();}return;}
    if(el.dataset.repeatGeneration){const g=state.generation;const m=modelBySlug(g.model_slug)||visibleUiModels()[0];state.draft=newDraft(m);state.draft.values.prompt=g.prompt??'';nav('studio');return;}
    if(el.dataset.publish){const p=await api(`/generations/${el.dataset.publish}/publications`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scope:el.dataset.scope})});toast(el.dataset.scope==='feed'?'Опубликовано в ленте':'Опубликовано в профиле');state.ownPublications.unshift(p);return;}
    if(el.hasAttribute('data-edit-profile')){const p=state.ownProfile;const slug=prompt('Slug профиля',p?.slug??user().username??'')?.trim();if(!slug)return;const display=prompt('Имя',p?.display_name??user().display_name??'')?.trim()||null;const bio=prompt('О себе',p?.bio??'')?.trim()||null;state.ownProfile=await api('/me/profile',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({slug,display_name:display,bio})});render();return;}
  }catch(e){toast(e.message,'error');}
});

root.addEventListener('input',event=>{const el=event.target;if(!el?.dataset?.field||!state.draft)return;let value=el.type==='checkbox'?el.checked:el.value;const schema=effectiveModel()?.input_schema?.properties?.[el.dataset.field];if(schema?.type==='number')value=value===''?null:Number(value);if(schema?.type==='integer')value=value===''?null:parseInt(value,10);state.draft.values[el.dataset.field]=value;});

picker.addEventListener('change',async()=>{const file=picker.files?.[0];picker.value='';if(!file||!state.pickerPolicy)return;const policy=state.pickerPolicy;state.pickerPolicy=null;try{const uploaded=await uploadFile(file,policy.context);if(!uploaded)return;if(policy.context==='studio'){state.draft.uploads.push({...uploaded,source:'upload'});render();return;}if(policy.context==='memory'){if(uploaded.kind!=='image')throw new Error('В память можно сохранять только изображения.');await api('/reference-memory',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({storage_key:uploaded.storage_key})});await deleteUpload(uploaded);await loadReferences();toast('Референс сохранён');render();return;}if(policy.context==='quick'){const compatible=visibleUiModels().filter(m=>m.media_kind===(uploaded.kind==='image'?'image':'video')||m.media_kind==='video');const model=compatible[0]??visibleUiModels()[0];if(!model)throw new Error('Нет совместимой модели.');state.draft=newDraft(model);state.draft.uploads=[{...uploaded,source:'upload'}];if(model.media_kind==='video')state.draft.mediaMode=uploaded.kind==='image'?'first_frame':'references';nav('studio');}}catch(e){toast(e.message,'error');}});


function portalValue(value){
  if(value===null||value===undefined||value==='')return '—';
  if(typeof value==='boolean')return value?'Да':'Нет';
  if(Array.isArray(value))return value.map(portalValue).join(' · ');
  if(typeof value==='object')return Object.entries(value).map(([k,v])=>`${human(k)}: ${portalValue(v)}`).join(' · ');
  return String(value);
}
function renderTariffPayload(payload){
  if(!payload||typeof payload!=='object')return empty('Тариф пока не опубликован','Администратор ещё не опубликовал пользовательский тариф.');
  const rows=Object.entries(payload);
  if(!rows.length)return empty('Тариф пока пуст','Опубликованная версия не содержит пользовательских параметров.');
  return `<div class="portal-kv">${rows.map(([key,value])=>`<div><span>${esc(human(key))}</span><strong>${esc(portalValue(value))}</strong></div>`).join('')}</div>`;
}
function renderTariff(){
  const item=state.tariff;
  return `<main class="hf-page">${topbar()}<section class="hf-hero compact grunge-card"><span class="stamp">TARIFF / LIVE</span><h1>Тарифы</h1><p>Только опубликованные сервером условия — без захардкоженных цен.</p></section>${state.portalBusy?spinner():item?`<section class="portal-card"><div class="section-head"><div><h2>Версия ${esc(item.version)}</h2><small>Опубликовано ${fmtDate(item.published_at)}</small></div></div>${renderTariffPayload(item.payload)}</section>`:empty('Тариф не опубликован','Когда появится активная версия, она автоматически отобразится здесь.')}</main>`;
}
function supportStatus(value){return {open:'Открыт',pending:'Ждёт ответа',closed:'Закрыт',resolved:'Решён'}[value]??human(value);}
function renderSupport(){
  return `<main class="hf-page">${topbar()}<section class="hf-hero compact grunge-card"><span class="stamp">SUPPORT</span><h1>Поддержка</h1><p>Обращения привязаны к аккаунту и сохраняют историю ответов.</p></section><section class="portal-card"><h2>Новое обращение</h2><form id="support-create-form" class="portal-form"><label>Тема<input name="subject" maxlength="255" required placeholder="Коротко опиши вопрос"></label><label>Сообщение<textarea name="body" maxlength="4096" required placeholder="Что произошло?"></textarea></label><button class="hf-primary" ${state.portalBusy?'disabled':''}>Отправить</button></form></section><section class="section"><div class="section-head"><h2>Мои обращения</h2><button class="ghost-mini" data-refresh-support>↻</button></div>${state.portalBusy&&!state.supportTickets.length?spinner():state.supportTickets.length?`<div class="ticket-list">${state.supportTickets.map(t=>`<button data-support-ticket="${esc(t.id)}"><span><strong>${esc(t.subject)}</strong><small>${fmtDate(t.updated_at)} · ${esc(supportStatus(t.status))}</small></span><b>›</b></button>`).join('')}</div>`:empty('Обращений нет','Если возникнет проблема, создай тикет выше.')}</section></main>`;
}
function renderSupportTicket(){
  const t=state.supportTicket;
  if(!t)return `<main class="hf-page">${topbar()}${spinner()}</main>`;
  const closed=['closed','resolved'].includes(t.status);
  return `<main class="hf-page">${topbar()}<section class="portal-card ticket-head"><span class="stamp">${esc(supportStatus(t.status))}</span><h1>${esc(t.subject)}</h1><p>${fmtDate(t.created_at)} · ${esc(human(t.priority))}</p></section><section class="support-thread">${(t.messages??[]).map(m=>`<article class="support-message ${m.sender_kind==='user'?'mine':'staff'}"><strong>${m.sender_kind==='user'?'Вы':'Happy Fox'}</strong><p>${esc(m.body)}</p><small>${fmtDate(m.created_at)}</small></article>`).join('')}</section>${!closed?`<section class="portal-card"><form id="support-reply-form" class="portal-form"><label>Ответ<textarea name="body" maxlength="4096" required placeholder="Дополнить обращение…"></textarea></label><button class="hf-primary">Отправить</button></form><button class="danger-button portal-close" data-close-ticket="${esc(t.id)}">Закрыть обращение</button></section>`:'<div class="notice grunge-lite">Обращение закрыто. История остаётся доступной.</div>'}</main>`;
}
function renderPartner(){
  const data=state.partner;const p=data?.profile;const withdrawals=data?.withdrawals??[];
  if(state.portalBusy&&!data)return `<main class="hf-page">${topbar()}${spinner()}</main>`;
  return `<main class="hf-page">${topbar()}<section class="hf-hero compact grunge-card"><span class="stamp">PARTNERS</span><h1>Партнёрская программа</h1><p>Доходы и выплаты берутся из серверного партнёрского контура.</p></section>${p?.joined?`<section class="partner-stats"><div><small>Заработано</small><strong>${fmtCredits(p.earned_units)} ●</strong></div><div><small>Доступно</small><strong>${fmtCredits(p.available_units)} ●</strong></div><div><small>В ожидании</small><strong>${fmtCredits(p.pending_units)} ●</strong></div><div><small>Рефералы</small><strong>${fmtCredits(p.referrals_count)}</strong></div></section><section class="portal-card"><h2>Запросить выплату</h2><form id="partner-withdraw-form" class="portal-form"><label>Сумма<input name="amount_units" type="number" min="1" max="${Math.max(1,Number(p.available_units||1))}" required></label><label>Реквизиты<input name="destination" minlength="3" maxlength="255" required placeholder="Куда отправить выплату"></label><button class="hf-primary" ${Number(p.available_units||0)<=0?'disabled':''}>Создать заявку</button></form></section>`:`<section class="portal-card join-partner"><h2>Стать партнёром</h2><p>После подключения появится статистика приглашённых пользователей, заработка и заявок на выплату.</p><button class="hf-primary" data-partner-join>Подключиться</button></section>`}<section class="section"><h2>Выплаты</h2>${withdrawals.length?`<div class="withdraw-list">${withdrawals.map(w=>`<div><span><strong>${fmtCredits(w.amount_units)} ●</strong><small>${fmtDate(w.created_at)} · ${esc(human(w.status))}</small></span><small>${esc(w.destination||'')}</small></div>`).join('')}</div>`:empty('Заявок нет','История выплат появится здесь.')}</section></main>`;
}

function renderFatal(error){root.innerHTML=`<main class="hf-page fatal">${brand()}<div class="error-box"><span class="stamp">OFFLINE</span><h1>Не удалось открыть Happy Fox</h1><p>${esc(error?.message??error)}</p><button class="hf-primary" onclick="location.reload()">Повторить</button></div></main>`;}

init();
