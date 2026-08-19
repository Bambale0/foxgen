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

  function fatal(message) {
    if (typeof window.__FOXGEN_BOOT_FATAL__ === 'function') {
      window.__FOXGEN_BOOT_FATAL__(message);
      return;
    }
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

  function supportsCurrentRuntime() {
    try {
      new Function('var a = null; a ??= 1; var b = true; b &&= false; return a === 1 && b === false;');
      return true;
    } catch (_) {
      return false;
    }
  }

  function appendCoreScript(source, marker, onload) {
    var script = document.createElement('script');
    script.src = source;
    script.async = false;
    script.setAttribute('data-foxgen-core-runtime', marker);
    script.onload = onload;
    script.onerror = function () {
      fatal('Не загрузился обязательный файл Happy Fox: ' + source.split('/').pop());
    };
    document.body.appendChild(script);
  }

  installCompatibility();

  var manifest = document.getElementById('foxgen-runtime-manifest');
  if (!manifest) {
    fatal('Не найден runtime manifest Happy Fox.');
    return;
  }

  if (!supportsCurrentRuntime()) {
    document.documentElement.setAttribute('data-foxgen-runtime', 'unsupported');
    fatal('Эта версия Telegram WebView слишком старая для актуального Happy Fox. Обновите Telegram и откройте Mini App снова.');
    return;
  }

  var paritySource = manifest.getAttribute('data-parity-src');
  var catalogSource = manifest.getAttribute('data-product-home-src');
  if (!paritySource || !catalogSource) {
    fatal('Не найден актуальный интерфейс Happy Fox.');
    return;
  }

  window.__FOXGEN_RUNTIME_KIND__ = 'parity';
  document.documentElement.setAttribute('data-foxgen-runtime', 'parity');
  setPhase('Запускаем актуальный интерфейс…');

  appendCoreScript(paritySource, 'parity', function () {
    window.__FOXGEN_CORE_LOADED__ = true;
    setPhase('Подключаем каталог моделей…');

    appendCoreScript(catalogSource, 'catalog', function () {
      window.__FOXGEN_CATALOG_RUNTIME_LOADED__ = true;
      setPhase('Подключаем аккаунт…');
    });
  });
})();
