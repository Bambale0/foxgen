(function () {
  'use strict';

  var BOOT_TIMEOUT_MS = 15000;
  var root = document.getElementById('app');
  var failed = false;
  var fallbackStarted = false;

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

  function hasLegacyFlag() {
    return /(?:[?&])legacy=1(?:&|$)/.test(window.location.search || '');
  }

  function legacyUrl(url) {
    var value = String(url || '');
    var hash = '';
    var hashIndex = value.indexOf('#');
    var separator;

    if (hasLegacyFlag()) return value;
    if (hashIndex >= 0) {
      hash = value.slice(hashIndex);
      value = value.slice(0, hashIndex);
    }
    separator = value.indexOf('?') >= 0 ? '&' : '?';
    return value + separator + 'legacy=1' + hash;
  }

  function showFailure(message) {
    var main;
    var errorText;
    var retry;

    if (failed || !root || !bootScreen()) return;
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

  function failOrFallback(message) {
    if (!bootScreen()) return;

    if (!hasLegacyFlag() && window.__FOXGEN_RUNTIME_KIND__ !== 'legacy') {
      if (fallbackStarted) return;
      fallbackStarted = true;
      setPhase('Переключаем совместимый режим…');
      window.setTimeout(function () {
        window.location.replace(legacyUrl(window.location.href));
      }, 250);
      return;
    }

    showFailure(message);
  }

  window.__FOXGEN_BOOT_PHASE__ = setPhase;
  window.__FOXGEN_BOOT_FAIL__ = failOrFallback;

  window.addEventListener(
    'error',
    function (event) {
      var asset = assetName(event && event.target);
      if (asset && asset.indexOf('/mini-app/') >= 0) {
        failOrFallback('Не загрузился файл интерфейса: ' + asset.split('/').pop());
        return;
      }
      if (bootScreen() && event && event.message) {
        failOrFallback('Ошибка запуска: ' + event.message);
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
    failOrFallback('Ошибка запуска: ' + String(reason));
  });

  window.setTimeout(function () {
    if (bootScreen()) {
      failOrFallback('Запуск занял больше 15 секунд. Проверь соединение и попробуй ещё раз.');
    }
  }, BOOT_TIMEOUT_MS);
})();
