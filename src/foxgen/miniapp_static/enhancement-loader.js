(function () {
  'use strict';

  var started = false;
  var catalogReady = false;
  var CATALOG_RENDER_TIMEOUT_MS = 3000;

  function logError(message, detail) {
    if (window.console && typeof window.console.error === 'function') {
      window.console.error(message, detail || '');
    }
  }

  function showCriticalFailure(detail) {
    var message = 'Не удалось запустить актуальный каталог Happy Fox.';
    document.documentElement.setAttribute('data-foxgen-catalog', 'failed');
    logError(message, detail);

    if (typeof window.__FOXGEN_BOOT_FATAL__ === 'function') {
      window.__FOXGEN_BOOT_FATAL__(message + ' Перезапустите Mini App.');
      return;
    }

    var main = document.querySelector('#app main.hf-page');
    if (!main) return;
    main.innerHTML = '<section class="product-home-error" data-catalog-load-failure="1">' +
      '<strong>Каталог временно не загрузился</strong>' +
      '<p>Старая версия интерфейса не используется. Перезапустите Mini App.</p>' +
      '<button type="button" data-catalog-reload>Перезапустить</button></section>';
    var reload = main.querySelector('[data-catalog-reload]');
    if (reload) reload.addEventListener('click', function () { window.location.reload(); });
  }

  function appendModule(source) {
    var script = document.createElement('script');
    script.type = 'module';
    script.src = source;
    script.setAttribute('data-foxgen-enhancement', source);
    script.onerror = function () {
      logError('Happy Fox enhancement failed to load:', source);
    };
    document.body.appendChild(script);
  }

  function loadOptionalModules(nodes) {
    var index;
    var source;
    for (index = 0; index < nodes.length; index += 1) {
      source = nodes[index].getAttribute('data-module-src');
      if (!source) continue;
      appendModule(source);
    }
  }

  function waitForCatalog(nodes) {
    var deadline = Date.now() + CATALOG_RENDER_TIMEOUT_MS;

    function check() {
      var main = document.querySelector('#app main[data-product-catalog="1"]');
      if (main) {
        catalogReady = true;
        document.documentElement.setAttribute('data-foxgen-catalog', 'ready');
        loadOptionalModules(nodes);
        return;
      }
      if (Date.now() >= deadline) {
        showCriticalFailure('product-home.js render timeout');
        return;
      }
      window.setTimeout(check, 50);
    }

    check();
  }

  function loadEnhancements() {
    var manifest;
    var nodes;

    if (started) return;
    manifest = document.getElementById('foxgen-enhancement-manifest');
    if (!manifest) return;

    started = true;
    document.documentElement.setAttribute('data-foxgen-catalog', 'loading');
    nodes = manifest.querySelectorAll('[data-module-src]');
    waitForCatalog(nodes);
  }

  window.addEventListener('foxgen:bootstrap', loadEnhancements);

  if (window.__FOXGEN_BOOTSTRAP__) {
    loadEnhancements();
  }

  window.setTimeout(function () {
    var status = document.documentElement.getAttribute('data-foxgen-catalog');
    if (started && !catalogReady && status !== 'failed') {
      showCriticalFailure('catalog readiness timeout');
    }
  }, 12000);
})();
