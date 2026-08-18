(function () {
  'use strict';

  var started = false;

  function loadEnhancements() {
    var manifest;
    var nodes;
    var index;
    var source;
    var script;

    if (started) return;
    if (window.__FOXGEN_RUNTIME_KIND__ === 'legacy') return;

    manifest = document.getElementById('foxgen-enhancement-manifest');
    if (!manifest) return;

    started = true;
    nodes = manifest.querySelectorAll('[data-module-src]');

    for (index = 0; index < nodes.length; index += 1) {
      source = nodes[index].getAttribute('data-module-src');
      if (!source) continue;

      script = document.createElement('script');
      script.type = 'module';
      script.src = source;
      script.setAttribute('data-foxgen-enhancement', source);
      script.onerror = (function (url) {
        return function () {
          if (window.console && typeof window.console.error === 'function') {
            window.console.error('Happy Fox enhancement failed to load:', url);
          }
        };
      })(source);
      document.body.appendChild(script);
    }
  }

  window.addEventListener('foxgen:bootstrap', loadEnhancements);

  if (window.__FOXGEN_BOOTSTRAP__) {
    loadEnhancements();
  }
})();
