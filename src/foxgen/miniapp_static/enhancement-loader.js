(function () {
  'use strict';

  var loaded = false;

  function logError(message, detail) {
    if (window.console && typeof window.console.error === 'function') {
      window.console.error(message, detail || '');
    }
  }

  function appendModule(source, done) {
    var script = document.createElement('script');
    script.type = 'module';
    script.src = source;
    script.setAttribute('data-foxgen-enhancement', source);
    script.onload = function () {
      if (typeof done === 'function') done();
    };
    script.onerror = function () {
      logError('Happy Fox optional enhancement failed to load:', source);
      if (typeof done === 'function') done();
    };
    document.body.appendChild(script);
  }

  function loadSequentially(nodes, index) {
    var source;
    if (index >= nodes.length) {
      document.documentElement.setAttribute('data-foxgen-enhancements', 'ready');
      return;
    }
    source = nodes[index].getAttribute('data-module-src');
    if (!source) {
      loadSequentially(nodes, index + 1);
      return;
    }
    appendModule(source, function () {
      loadSequentially(nodes, index + 1);
    });
  }

  function loadEnhancements() {
    var manifest;
    var nodes;
    if (loaded || !window.__FOXGEN_BOOTSTRAP__) return;
    manifest = document.getElementById('foxgen-enhancement-manifest');
    if (!manifest) return;
    loaded = true;
    nodes = manifest.querySelectorAll('[data-module-src]');
    document.documentElement.setAttribute('data-foxgen-enhancements', 'loading');
    loadSequentially(nodes, 0);
  }

  window.addEventListener('foxgen:bootstrap', loadEnhancements);
  if (window.__FOXGEN_BOOTSTRAP__) loadEnhancements();
})();
