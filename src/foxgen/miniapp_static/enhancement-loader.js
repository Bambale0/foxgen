(function () {
  'use strict';

  var started = false;
  var catalogReady = false;

  function logError(message, detail) {
    if (window.console && typeof window.console.error === 'function') {
      window.console.error(message, detail || '');
    }
  }

  function showCriticalFailure(url) {
    var main = document.querySelector('#app main.hf-page');
    var message = 'Не удалось загрузить каталог Happy Fox.';
    var block;

    document.documentElement.setAttribute('data-foxgen-catalog', 'failed');
    logError(message, url);

    if (!main) {
      if (typeof window.__FOXGEN_BOOT_FAIL__ === 'function') {
        window.__FOXGEN_BOOT_FAIL__(message);
      }
      return;
    }

    if (main.querySelector('[data-catalog-load-failure]')) return;

    block = document.createElement('section');
    block.className = 'product-home-error';
    block.setAttribute('data-catalog-load-failure', '1');
    block.innerHTML = '<strong>Каталог временно не загрузился</strong>' +
      '<p>Основной интерфейс запущен, но каталог моделей не подключился. Перезапусти Mini App.</p>' +
      '<button type="button" data-catalog-reload>Перезапустить</button>';
    main.insertBefore(block, main.firstChild);

    block.querySelector('[data-catalog-reload]').addEventListener('click', function () {
      window.location.reload();
    });
  }

  function appendModule(source, critical, done) {
    var script = document.createElement('script');
    script.type = 'module';
    script.src = source;
    script.setAttribute('data-foxgen-enhancement', source);
    if (critical) script.setAttribute('data-foxgen-critical-enhancement', 'catalog');

    script.onload = function () {
      if (critical) {
        catalogReady = true;
        document.documentElement.setAttribute('data-foxgen-catalog', 'ready');
      }
      if (typeof done === 'function') done(true);
    };

    script.onerror = function () {
      if (critical) showCriticalFailure(source);
      else logError('Happy Fox enhancement failed to load:', source);
      if (typeof done === 'function') done(false);
    };

    document.body.appendChild(script);
  }

  function loadOptionalModules(nodes) {
    var index;
    var source;
    for (index = 0; index < nodes.length; index += 1) {
      if (nodes[index].hasAttribute('data-critical-module')) continue;
      source = nodes[index].getAttribute('data-module-src');
      if (!source) continue;
      appendModule(source, false, null);
    }
  }

  function loadEnhancements() {
    var manifest;
    var nodes;
    var critical;
    var source;

    if (started) return;

    manifest = document.getElementById('foxgen-enhancement-manifest');
    if (!manifest) return;

    started = true;
    nodes = manifest.querySelectorAll('[data-module-src]');
    critical = manifest.querySelector('[data-critical-module="catalog"]');

    if (!critical) {
      showCriticalFailure('product-home.js');
      loadOptionalModules(nodes);
      return;
    }

    source = critical.getAttribute('data-module-src');
    if (!source) {
      showCriticalFailure('product-home.js');
      loadOptionalModules(nodes);
      return;
    }

    appendModule(source, true, function () {
      loadOptionalModules(nodes);
    });
  }

  window.addEventListener('foxgen:bootstrap', loadEnhancements);

  if (window.__FOXGEN_BOOTSTRAP__) {
    loadEnhancements();
  }

  window.setTimeout(function () {
    if (started && !catalogReady && document.documentElement.getAttribute('data-foxgen-catalog') !== 'failed') {
      showCriticalFailure('product-home.js timeout');
    }
  }, 12000);
})();
