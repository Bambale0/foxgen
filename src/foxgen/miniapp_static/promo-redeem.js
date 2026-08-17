import './user-parity-hardening.js';

const root = document.getElementById('app');
const tg = window.Telegram?.WebApp ?? null;

let promoToken = null;
let promoBusy = false;

async function promoAuth(force = false) {
  if (promoToken && !force) return promoToken;
  if (!tg?.initData) throw new Error('Откройте Happy Fox внутри Telegram для активации промокода.');

  const response = await fetch('/v1/miniapp/auth', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ init_data: tg.initData }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || !data?.access_token) {
    throw new Error(data?.detail || data?.message || 'Не удалось подтвердить Telegram-профиль.');
  }
  promoToken = data.access_token;
  return promoToken;
}

async function promoApi(code, retryAuth = true) {
  const token = await promoAuth(false);
  const response = await fetch('/v1/miniapp/promos/redeem', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ code }),
  });
  const data = await response.json().catch(() => ({}));
  if (response.status === 401 && retryAuth) {
    await promoAuth(true);
    return promoApi(code, false);
  }
  if (!response.ok) {
    throw new Error(data?.message || data?.detail || data?.error || `HTTP ${response.status}`);
  }
  return data;
}

function setStatus(panel, message, kind = 'info') {
  const status = panel.querySelector('[data-promo-status]');
  if (!(status instanceof HTMLElement)) return;
  status.className = `promo-redeem__status ${kind}`;
  status.textContent = message;
}

async function redeemPromo(panel, code) {
  if (promoBusy) return;
  const normalized = code.trim();
  if (!normalized) {
    setStatus(panel, 'Введите промокод.', 'error');
    return;
  }

  promoBusy = true;
  const button = panel.querySelector('[data-promo-submit]');
  if (button instanceof HTMLButtonElement) button.disabled = true;
  setStatus(panel, 'Проверяю промокод…');

  try {
    const result = await promoApi(normalized);
    const reward = Number(result.reward_units || 0).toLocaleString('ru-RU');
    const balance = Number(result.available_units || 0).toLocaleString('ru-RU');
    const prefix = result.replayed ? 'Промокод уже был активирован.' : 'Промокод активирован.';
    setStatus(panel, `${prefix} +${reward} CREDIT · баланс ${balance} CREDIT`, 'success');
    window.setTimeout(() => window.location.reload(), 1100);
  } catch (error) {
    setStatus(panel, error?.message ?? String(error), 'error');
  } finally {
    promoBusy = false;
    if (button instanceof HTMLButtonElement) button.disabled = false;
  }
}

function injectPromoRedeem() {
  if (!root || root.querySelector('[data-promo-redeem]')) return;
  const anchor = root.querySelector('[data-complete-wallet-actions]') || root.querySelector('.wallet-hero');
  if (!(anchor instanceof HTMLElement)) return;

  const panel = document.createElement('section');
  panel.className = 'promo-redeem';
  panel.dataset.promoRedeem = '1';
  panel.innerHTML = `
    <div class="promo-redeem__head">
      <strong>Промокод</strong>
      <small>Бонус зачисляется в CREDIT один раз</small>
    </div>
    <form class="promo-redeem__form" data-promo-form>
      <input
        type="text"
        name="promo-code"
        maxlength="64"
        autocomplete="off"
        spellcheck="false"
        placeholder="Введите код"
        aria-label="Промокод"
        required
      >
      <button type="submit" data-promo-submit>Активировать</button>
    </form>
    <p class="promo-redeem__status" data-promo-status aria-live="polite"></p>
  `;
  anchor.insertAdjacentElement('afterend', panel);
}

root?.addEventListener('submit', (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || !form.matches('[data-promo-form]')) return;
  event.preventDefault();
  const panel = form.closest('[data-promo-redeem]');
  const input = form.querySelector('input[name="promo-code"]');
  if (!(panel instanceof HTMLElement) || !(input instanceof HTMLInputElement)) return;
  void redeemPromo(panel, input.value);
});

const observer = new MutationObserver(() => queueMicrotask(injectPromoRedeem));
if (root) {
  observer.observe(root, { childList: true, subtree: true });
  injectPromoRedeem();
}
