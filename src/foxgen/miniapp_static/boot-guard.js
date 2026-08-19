(function () {
  'use strict';

  var BOOT_TIMEOUT_MS = 15000;
  var root = document.getElementById('app');
  var failed = false;

  function bootScreen() {
    if (!root || !root.querySelector) return null;
    return root.querySelector('.boot-screen');
  }

  function setPhase(message) {
    var node = document.getElementById('boot-message');
    if (node) node.textContent = String(message || '');
  }

  function assetName(target) {
    if (!target || !target.tagName) return '';
    if (target.tagName === 'SCRIPT') return target.src || 'JavaScript';
    if (target.tagName === 'LINK') return target.href || 'CSS';
    return '';
  }

  function showFailure(message, force) {
    var main;
    var errorText;
    var retry;

    if (failed || !root) return;
    if (!force && !bootScreen()) return;
    failed = true;
    root.innerHTML = '';

    main = document.createElement('main');
    main.className = 'hf-page fatal boot-fallback';
    main.innerHTML = [
      '<div class="brand-lockup brand-lockup--center">',
      '<div class="fox-mark" aria-hidden="true">🦊</div>',
      '<div><strong>Happy <span>Fox</span></strong><small>AI-студия в Telegram</small></div>',
      '</div>',
      '<div class="error-box">',
      '<span class="stamp">STARTUP ERROR</span>',
      '<h1>Happy Fox не запустился</h1>',
      '<p data-boot-error></p>',
      '<button class="hf-primary" type="button" data-boot-retry>Перезагрузить</button>',
      '</div>'
    ].join('');
    root.appendChild(main);

    errorText = root.querySelector('[data-boot-error]');
    if (errorText) errorText.textContent = String(message || 'Не удалось загрузить интерфейс.');

    retry = root.querySelector('[data-boot-retry]');
    if (retry) {
      retry.addEventListener('click', function () {
        window.location.reload();
      });
    }
  }

  function fail(message) {
    showFailure(message, false);
  }

  function fatal(message) {
    showFailure(message, true);
  }

  window.__FOXGEN_BOOT_PHASE__ = setPhase;
  window.__FOXGEN_BOOT_FAIL__ = fail;
  window.__FOXGEN_BOOT_FATAL__ = fatal;

  window.addEventListener(
    'error',
    function (event) {
      var asset = assetName(event && event.target);
      if (asset && asset.indexOf('/mini-app/') >= 0) {
        fail('Не загрузился файл интерфейса: ' + asset.split('/').pop());
        return;
      }
      if (bootScreen() && event && event.message) {
        fail('Ошибка запуска: ' + event.message);
      }
    },
    true
  );

  window.addEventListener('unhandledrejection', function (event) {
    var reason;
    if (!bootScreen()) return;
    reason = event && event.reason;
    if (reason && reason.message) reason = reason.message;
    if (reason === undefined || reason === null || reason === '') reason = 'неизвестная ошибка';
    fail('Ошибка запуска: ' + String(reason));
  });

  window.setTimeout(function () {
    if (bootScreen()) {
      fail('Запуск занял больше 15 секунд. Проверь соединение и попробуй ещё раз.');
    }
  }, BOOT_TIMEOUT_MS);
})();
