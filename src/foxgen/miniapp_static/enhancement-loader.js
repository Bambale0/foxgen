(function () {
  'use strict';

  var started = false;
  var surfaceReady = false;
  var CURRENT_SURFACE_TIMEOUT_MS = 3000;

  function logError(message, detail) {
    if (window.console && typeof window.console.error === 'function') {
      window.console.error(message, detail || '');
    }
  }

  function showCriticalFailure(detail) {
    var message = 'Не удалось запустить актуальный интерфейс Happy Fox.';
    document.documentElement.setAttribute('data-foxgen-catalog', 'failed');
    logError(message, detail);

    if (typeof window.__FOXGEN_BOOT_FATAL__ === 'function') {
      window.__FOXGEN_BOOT_FATAL__(message + ' Перезапустите Mini App.');
      return;
    }

    var main = document.querySelector('#app main.hf-page');
    if (!main) return;
    main.innerHTML = '<section class="product-home-error" data-catalog-load-failure="1">' +
      '<strong>Интерфейс временно не загрузился</strong>' +
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

  function isCurrentSurfaceReady() {
    var main = document.querySelector('#app main.hf-page');
    var stamp;

    if (!main || main.classList.contains('boot-fallback')) return false;
    if (main.getAttribute('data-product-catalog') === '1') return true;

    stamp = main.querySelector('.hf-hero .stamp');
    if (stamp && String(stamp.textContent || '').trim() === 'COMMUNITY / LIVE') {
      return false;
    }

    return true;
  }

  function waitForCurrentSurface(nodes) {
    var deadline = Date.now() + CURRENT_SURFACE_TIMEOUT_MS;

    function check() {
      if (isCurrentSurfaceReady()) {
        surfaceReady = true;
        document.documentElement.setAttribute('data-foxgen-catalog', 'ready');
        loadOptionalModules(nodes);
        return;
      }
      if (Date.now() >= deadline) {
        showCriticalFailure('current product surface readiness timeout');
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
    waitForCurrentSurface(nodes);
  }

  window.addEventListener('foxgen:bootstrap', loadEnhancements);

  if (window.__FOXGEN_BOOTSTRAP__) {
    loadEnhancements();
  }

  window.setTimeout(function () {
    var status = document.documentElement.getAttribute('data-foxgen-catalog');
    if (started && !surfaceReady && status !== 'failed') {
      showCriticalFailure('current product surface timeout');
    }
  }, 12000);
})();
