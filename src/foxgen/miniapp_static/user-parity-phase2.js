const root = document.getElementById('app');

function parseCredit(text) {
  const normalized = String(text ?? '')
    .replaceAll('\u00a0', '')
    .replaceAll(' ', '')
    .replace(',', '.');
  const match = normalized.match(/-?\d+(?:\.\d+)?/);
  return match ? Number(match[0]) : Number.NaN;
}

function generationIdFromDetail() {
  const terms = [...(root?.querySelectorAll('.detail-card dt') ?? [])];
  const idTerm = terms.find((term) => term.textContent?.trim() === 'ID');
  const value = idTerm?.parentElement?.querySelector('dd')?.textContent?.trim();
  return value || null;
}

function enhanceRetryAction() {
  const badge = root?.querySelector('.status-badge.failed, .status-badge.cancelled');
  const actions = root?.querySelector('.action-grid');
  if (!(badge instanceof HTMLElement) || !(actions instanceof HTMLElement)) return;
  if (actions.querySelector('[data-repeat-generation],[data-parity-retry]')) return;

  const generationId = generationIdFromDetail();
  if (!generationId) return;

  const button = document.createElement('button');
  button.type = 'button';
  button.dataset.repeatGeneration = generationId;
  button.dataset.parityRetry = '1';
  button.textContent = badge.classList.contains('failed') ? 'Повторить после ошибки' : 'Повторить';
  actions.prepend(button);
}

function admissionNotice(card, kind, message, { topup = false } = {}) {
  let notice = card.querySelector('[data-parity-admission-notice]');
  if (!(notice instanceof HTMLElement)) {
    notice = document.createElement('div');
    notice.className = 'notice grunge-lite';
    notice.dataset.parityAdmissionNotice = '1';
    card.insertAdjacentElement('afterend', notice);
  }
  notice.dataset.kind = kind;
  notice.innerHTML = topup
    ? `<span>${message}</span><button type="button" class="text-link" data-stars-topup>Пополнить баланс</button>`
    : `<span>${message}</span>`;
}

function enhanceAdmissionCard() {
  const card = root?.querySelector('.launch-card');
  if (!(card instanceof HTMLElement)) return;

  const submit = card.querySelector('[data-submit]');
  if (!(submit instanceof HTMLButtonElement)) return;
  if (submit.textContent?.includes('Проверяем')) return;

  const cost = parseCredit(card.querySelector('strong')?.textContent);
  const available = parseCredit(card.querySelector('span')?.textContent);
  let state = 'ready';

  if (!Number.isFinite(cost) || cost <= 0) state = 'no-price';
  else if (Number.isFinite(available) && available < cost) state = 'insufficient';

  if (card.dataset.parityAdmissionState === state) return;
  card.dataset.parityAdmissionState = state;

  const previous = card.nextElementSibling;
  if (
    previous instanceof HTMLElement
    && previous.hasAttribute('data-parity-admission-notice')
    && state === 'ready'
  ) {
    previous.remove();
  }

  if (state === 'no-price') {
    submit.disabled = true;
    submit.textContent = 'Цена не опубликована';
    admissionNotice(
      card,
      state,
      'Запуск станет доступен после публикации активной серверной цены.',
    );
    return;
  }

  if (state === 'insufficient') {
    submit.disabled = true;
    submit.textContent = 'Недостаточно CREDIT';
    admissionNotice(
      card,
      state,
      `Нужно ${cost.toLocaleString('ru-RU')} CREDIT, доступно ${available.toLocaleString('ru-RU')}.`,
      { topup: true },
    );
  }
}

function enhance() {
  enhanceRetryAction();
  enhanceAdmissionCard();
}

const observer = new MutationObserver(() => queueMicrotask(enhance));
if (root) {
  observer.observe(root, { childList: true, subtree: true });
  enhance();
}
