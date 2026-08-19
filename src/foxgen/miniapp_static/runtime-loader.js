(function () {
  'use strict';

  function setPhase(message) {
    if (typeof window.__FOXGEN_BOOT_PHASE__ === 'function') {
      window.__FOXGEN_BOOT_PHASE__(message);
      return;
    }
    var node = document.getElementById('boot-message');
    if (node) node.textContent = message;
  }

  function fail(message) {
    if (typeof window.__FOXGEN_BOOT_FAIL__ === 'function') {
      window.__FOXGEN_BOOT_FAIL__(message);
      return;
    }
    var node = document.getElementById('boot-message');
    if (node) node.textContent = message;
  }

  function installCompatibility() {
    if (!String.prototype.replaceAll) {
      Object.defineProperty(String.prototype, 'replaceAll', {
        configurable: true,
        writable: true,
        value: function (search, replacement) {
          if (search instanceof RegExp) {
            if (!search.global) throw new TypeError('replaceAll regex must be global');
            return String(this).replace(search, replacement);
          }
          return String(this).split(String(search)).join(String(replacement));
        },
      });
    }

    if (typeof window.structuredClone !== 'function') {
      window.structuredClone = function (value) {
        return JSON.parse(JSON.stringify(value));
      };
    }
  }

  function supportsParitySyntax() {
    try {
      new Function('var a = null; a ??= 1; var b = true; b &&= false; return a === 1 && b === false;');
      return true;
    } catch (_) {
      return false;
    }
  }

  function requestedLegacyMode() {
    return /(?:[?&])legacy=1(?:&|$)/.test(window.location.search || '');
  }

  installCompatibility();

  var manifest = document.getElementById('foxgen-runtime-manifest');
  if (!manifest) {
    fail('Не найден runtime manifest Happy Fox.');
    return;
  }

  var paritySupported = supportsParitySyntax();
  var legacy = requestedLegacyMode() || !paritySupported;
  var source = manifest.getAttribute(legacy ? 'data-legacy-src' : 'data-parity-src');
  if (!source) {
    fail('Не найден файл интерфейса Happy Fox.');
    return;
  }

  window.__FOXGEN_RUNTIME_KIND__ = legacy ? 'legacy' : 'parity';
  document.documentElement.setAttribute('data-foxgen-runtime', window.__FOXGEN_RUNTIME_KIND__);
  setPhase(legacy ? 'Запускаем совместимый режим…' : 'Запускаем интерфейс…');

  var script = document.createElement('script');
  script.src = source;
  script.async = false;
  script.setAttribute('data-foxgen-core-runtime', window.__FOXGEN_RUNTIME_KIND__);
  script.onload = function () {
    window.__FOXGEN_CORE_LOADED__ = true;
    setPhase('Подключаем аккаунт…');
  };
  script.onerror = function () {
    fail('Не загрузился основной файл интерфейса: ' + source.split('/').pop());
  };
  document.body.appendChild(script);
})();
