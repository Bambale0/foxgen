const root = document.getElementById('app');
const tg = window.Telegram?.WebApp ?? null;

const STORAGE_KEY = 'happy-fox:studio-draft:v1';
const DRAFT_TTL_MS = 12 * 60 * 60 * 1000;

let activeModelSlug = startParamModelSlug();
let pendingRestore = null;
let restoring = false;
let submissionPending = false;

function startParamModelSlug() {
  const payload = tg?.initDataUnsafe?.start_param
    || new URLSearchParams(window.location.search).get('tgWebAppStartParam')
    || '';
  return payload.startsWith('model_') ? payload.slice(6) : null;
}

function safeStorageGet() {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function safeStorageSet(value) {
  try {
    window.localStorage.setItem(STORAGE_KEY, value);
  } catch {
    // Draft recovery is best effort; storage can be disabled by the WebView.
  }
}

function safeStorageRemove() {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Nothing else to clean when WebView storage is unavailable.
  }
}

function readDraft() {
  const raw = safeStorageGet();
  if (!raw) return null;
  try {
    const draft = JSON.parse(raw);
    const createdAt = Number(draft?.updated_at ?? 0);
    if (
      draft?.version !== 1
      || typeof draft?.model_slug !== 'string'
      || !draft.model_slug
      || !Number.isFinite(createdAt)
      || Date.now() - createdAt > DRAFT_TTL_MS
    ) {
      safeStorageRemove();
      return null;
    }
    return draft;
  } catch {
    safeStorageRemove();
    return null;
  }
}

function clearDraft() {
  safeStorageRemove();
  pendingRestore = null;
}

function modelButton(slug) {
  return [...(root?.querySelectorAll('[data-model]') ?? [])].find(
    (button) => button instanceof HTMLElement && button.dataset.model === slug,
  ) ?? null;
}

function fieldValue(control) {
  if (control instanceof HTMLInputElement && control.type === 'checkbox') {
    return control.checked;
  }
  if (
    control instanceof HTMLInputElement
    || control instanceof HTMLTextAreaElement
    || control instanceof HTMLSelectElement
  ) {
    return control.value;
  }
  return null;
}

function collectFields() {
  const values = {};
  for (const control of root?.querySelectorAll('.studio-page [data-field]') ?? []) {
    if (!(control instanceof HTMLElement)) continue;
    const name = control.dataset.field;
    if (!name) continue;
    const value = fieldValue(control);
    if (value !== null) values[name] = value;
  }
  return values;
}

function currentMediaMode() {
  const active = root?.querySelector('.studio-page .mode-switch [data-media-mode].active');
  return active instanceof HTMLElement ? active.dataset.mediaMode ?? null : null;
}

function persistCurrentDraft() {
  const studio = root?.querySelector('.studio-page');
  if (!(studio instanceof HTMLElement)) return;

  const slug = activeModelSlug;
  if (!slug) return;

  const title = studio.querySelector('.studio-header h1')?.textContent?.trim() || slug;
  safeStorageSet(JSON.stringify({
    version: 1,
    model_slug: slug,
    model_title: title,
    values: collectFields(),
    media_mode: currentMediaMode(),
    media_restore_required: Boolean(
      studio.querySelector('.draft-media-item, [data-pick-studio]'),
    ),
    updated_at: Date.now(),
  }));
}

function dispatchFieldChange(control) {
  control.dispatchEvent(new Event('input', { bubbles: true }));
  control.dispatchEvent(new Event('change', { bubbles: true }));
}

function applyPendingRestore() {
  const draft = pendingRestore;
  const studio = root?.querySelector('.studio-page');
  if (!draft || !(studio instanceof HTMLElement)) return;

  pendingRestore = null;
  activeModelSlug = draft.model_slug;

  const values = draft.values && typeof draft.values === 'object' ? draft.values : {};
  for (const control of studio.querySelectorAll('[data-field]')) {
    if (!(control instanceof HTMLElement)) continue;
    const name = control.dataset.field;
    if (!name || !(name in values)) continue;
    const value = values[name];

    if (control instanceof HTMLInputElement && control.type === 'checkbox') {
      control.checked = Boolean(value);
      dispatchFieldChange(control);
      continue;
    }
    if (
      control instanceof HTMLInputElement
      || control instanceof HTMLTextAreaElement
      || control instanceof HTMLSelectElement
    ) {
      control.value = String(value ?? '');
      dispatchFieldChange(control);
    }
  }

  if (draft.media_mode) {
    const mode = [...studio.querySelectorAll('[data-media-mode]')].find(
      (button) => button instanceof HTMLElement && button.dataset.mediaMode === draft.media_mode,
    );
    if (mode instanceof HTMLButtonElement && !mode.classList.contains('active')) mode.click();
  }

  persistCurrentDraft();
  showRestoredNotice(Boolean(draft.media_restore_required));
}

function showRestoredNotice(mediaRequired) {
  const studio = root?.querySelector('.studio-page');
  if (!(studio instanceof HTMLElement) || studio.querySelector('[data-draft-restored]')) return;

  const notice = document.createElement('div');
  notice.className = 'notice grunge-lite draft-recovery__notice';
  notice.dataset.draftRestored = '1';
  notice.textContent = mediaRequired
    ? 'Черновик восстановлен. Файлы и референсы нужно прикрепить заново.'
    : 'Черновик восстановлен.';
  const header = studio.querySelector('.studio-header');
  header?.insertAdjacentElement('afterend', notice);
}

function ensureStyles() {
  if (document.getElementById('hf-draft-recovery-style')) return;
  const style = document.createElement('style');
  style.id = 'hf-draft-recovery-style';
  style.textContent = `
    .draft-recovery {
      margin: 12px 0 18px;
      padding: 14px;
      display: grid;
      gap: 10px;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: var(--card);
    }
    .draft-recovery__copy { display: grid; gap: 4px; }
    .draft-recovery__copy small { color: var(--muted); }
    .draft-recovery__actions { display: grid; grid-template-columns: 1fr auto; gap: 8px; }
    .draft-recovery__actions button { min-height: 42px; }
    .draft-recovery__notice { margin: 0 0 14px; }
  `;
  document.head.append(style);
}

function injectRecoveryCard() {
  const hero = root?.querySelector('.hf-hero [data-quick-start]')?.closest('.hf-hero');
  if (!(hero instanceof HTMLElement)) return;
  if (root.querySelector('[data-draft-recovery]')) return;

  const draft = readDraft();
  if (!draft) return;
  if (!(modelButton(draft.model_slug) instanceof HTMLElement)) return;

  const panel = document.createElement('section');
  panel.className = 'draft-recovery grunge-lite';
  panel.dataset.draftRecovery = '1';
  panel.innerHTML = `
    <div class="draft-recovery__copy">
      <strong>Продолжить черновик</strong>
      <small>${escapeText(draft.model_title || draft.model_slug)} · настройки сохранены локально</small>
    </div>
    <div class="draft-recovery__actions">
      <button type="button" class="hf-primary" data-recover-draft>Продолжить</button>
      <button type="button" class="ghost-mini" data-discard-draft>Удалить</button>
    </div>
  `;
  hero.insertAdjacentElement('afterend', panel);
}

function escapeText(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function recoverDraft() {
  const draft = readDraft();
  if (!draft) return;
  const button = modelButton(draft.model_slug);
  if (!(button instanceof HTMLButtonElement)) return;

  pendingRestore = draft;
  restoring = true;
  button.click();
  restoring = false;
  queueMicrotask(applyPendingRestore);
}

function observeSuccessfulSubmission() {
  if (!submissionPending) return;
  if (!(root?.querySelector('.generation-media') instanceof HTMLElement)) return;
  submissionPending = false;
  clearDraft();
}

function enhance() {
  ensureStyles();
  observeSuccessfulSubmission();
  applyPendingRestore();
  injectRecoveryCard();
}

root?.addEventListener(
  'click',
  (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;

    const recover = target.closest('[data-recover-draft]');
    if (recover instanceof HTMLButtonElement) {
      event.preventDefault();
      recoverDraft();
      return;
    }

    const discard = target.closest('[data-discard-draft]');
    if (discard instanceof HTMLButtonElement) {
      event.preventDefault();
      clearDraft();
      discard.closest('[data-draft-recovery]')?.remove();
      return;
    }

    const reset = target.closest('[data-reset-draft]');
    if (reset instanceof HTMLButtonElement) {
      clearDraft();
      return;
    }

    const submit = target.closest('[data-submit]');
    if (submit instanceof HTMLButtonElement && !submit.disabled) {
      submissionPending = true;
      return;
    }

    const model = target.closest('[data-model]');
    if (model instanceof HTMLButtonElement && model.dataset.model) {
      if (!restoring) {
        const existing = readDraft();
        if (existing && existing.model_slug !== model.dataset.model) clearDraft();
      }
      activeModelSlug = model.dataset.model;
      queueMicrotask(persistCurrentDraft);
    }
  },
  true,
);

root?.addEventListener('input', (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement) || !target.dataset.field) return;
  queueMicrotask(persistCurrentDraft);
});

root?.addEventListener('change', (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement) || !target.dataset.field) return;
  queueMicrotask(persistCurrentDraft);
});

const observer = new MutationObserver(() => queueMicrotask(enhance));
if (root) {
  observer.observe(root, { childList: true, subtree: true });
  enhance();
}
