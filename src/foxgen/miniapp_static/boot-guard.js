(() => {
  'use strict';

  const BOOT_TIMEOUT_MS = 15000;
  const root = document.getElementById('app');
  let failed = false;

  function bootScreen() {
    return root?.querySelector('.boot-screen') ?? null;
  }

  function assetName(target) {
    if (target instanceof HTMLScriptElement) return target.src || 'JavaScript';
    if (target instanceof HTMLLinkElement) return target.href || 'CSS';
    return '';
  }

  function showFailure(message) {
    if (failed || !bootScreen() || !root) return;
    failed = true;
    root.innerHTML = `
      <main class="hf-page fatal boot-fallback">
        <div class="brand-lockup brand-lockup--center">
          <div class="fox-mark" aria-hidden="true">🦊</div>
          <div><strong>Happy <span>Fox</span></strong><small>AI-студия в Telegram</small></div>
        </div>
        <div class="error-box">
          <span class="stamp">STARTUP ERROR</span>
          <h1>Happy Fox не запустился</h1>
          <p>${String(message || 'Не удалось загрузить интерфейс.').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')}</p>
          <button class="hf-primary" type="button" data-boot-retry>Перезагрузить</button>
        </div>
      </main>`;
    root.querySelector('[data-boot-retry]')?.addEventListener('click', () => location.reload());
  }

  window.addEventListener(
    'error',
    (event) => {
      const target = event.target;
      const asset = assetName(target);
      if (asset && asset.includes('/mini-app/')) {
        showFailure(`Не загрузился файл интерфейса: ${asset.split('/').pop()}`);
        return;
      }
      if (bootScreen() && event.message) {
        showFailure(`Ошибка запуска: ${event.message}`);
      }
    },
    true,
  );

  window.addEventListener('unhandledrejection', (event) => {
    if (!bootScreen()) return;
    const reason = event.reason?.message || event.reason || 'неизвестная ошибка';
    showFailure(`Ошибка запуска: ${reason}`);
  });

  window.setTimeout(() => {
    if (bootScreen()) {
      showFailure('Запуск занял больше 15 секунд. Проверь соединение и попробуй ещё раз.');
    }
  }, BOOT_TIMEOUT_MS);
})();
