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

  function supportsCurrentBaseline() {
    try {
      new Function('var a = null; var f = async function () { return a?.x ?? 1; }; return f;');
      return true;
    } catch (_) {
      return false;
    }
  }

  function transpileLogicalAssignments(source) {
    var output = String(source || '');

    output = output.replace(
      /([A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*)\?\?=([^;]+);/g,
      function (_, target, expression) {
        return target + ' = (' + target + ' == null ? (' + expression + ') : ' + target + ');';
      }
    );
    output = output.replace(
      /([A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*)&&=([^;]+);/g,
      function (_, target, expression) {
        return target + ' = ' + target + ' && (' + expression + ');';
      }
    );

    return output;
  }

  function loadCurrentSource(source, marker, done) {
    fetch(source, { cache: 'no-store' })
      .then(function (response) {
        if (!response.ok) throw new Error('HTTP ' + response.status);
        return response.text();
      })
      .then(function (text) {
        var compiled = transpileLogicalAssignments(text);
        if (compiled.indexOf('??=') >= 0 || compiled.indexOf('&&=') >= 0) {
          throw new Error('unsupported logical assignment remained after compatibility transform');
        }
        try {
          new Function(compiled)();
        } catch (error) {
          throw new Error('parse/execute ' + marker + ': ' + (error && error.message ? error.message : String(error)));
        }
        if (typeof done === 'function') done();
      })
      .catch(function (error) {
        fatal(
          'Не загрузился обязательный файл Happy Fox: ' +
            source.split('/').pop() +
            '. ' +
            (error && error.message ? error.message : String(error))
        );
      });
  }

  installCompatibility();

  var manifest = document.getElementById('foxgen-runtime-manifest');
  if (!manifest) {
    fatal('Не найден runtime manifest Happy Fox.');
    return;
  }

  if (!supportsCurrentBaseline()) {
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

  loadCurrentSource(paritySource, 'parity', function () {
    window.__FOXGEN_CORE_LOADED__ = true;
    setPhase('Подключаем каталог моделей…');

    loadCurrentSource(catalogSource, 'catalog', function () {
      window.__FOXGEN_CATALOG_RUNTIME_LOADED__ = true;
      setPhase('Подключаем аккаунт…');
    });
  });
})();
