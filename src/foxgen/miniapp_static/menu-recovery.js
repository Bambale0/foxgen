(function () {
  'use strict';

  var root = document.getElementById('app');
  var scheduled = false;

  function bootstrap() {
    return window.__FOXGEN_BOOTSTRAP__ || null;
  }

  function modelEnabled(slug) {
    var data = bootstrap();
    var models = data && Array.isArray(data.models) ? data.models : [];
    var index;
    var item;
    for (index = 0; index < models.length; index += 1) {
      item = models[index];
      if (
        item &&
        item.slug === slug &&
        item.enabled !== false &&
        item.enabled_for_submission !== false
      ) {
        return true;
      }
    }
    return false;
  }

  function promoteLauncher(key) {
    var button = root && root.querySelector('[data-complete-tool="' + key + '"]');
    var status;
    if (!(button instanceof HTMLButtonElement)) return;
    button.disabled = false;
    button.removeAttribute('aria-disabled');
    button.classList.remove('is-planned');
    button.classList.add('is-ready');
    status = button.querySelector('.complete-tool__status');
    if (status) status.textContent = 'Доступно';
  }

  function productAnchor() {
    var headings;
    var index;
    var heading;
    var head;
    var list;
    if (!root) return null;
    headings = root.querySelectorAll('.product-head h2');
    for (index = 0; index < headings.length; index += 1) {
      heading = headings[index];
      if (String(heading.textContent || '').trim() !== 'Видео') continue;
      head = heading.closest('.product-head');
      list = head && head.nextElementSibling;
      if (list && list.classList.contains('model-list')) return list;
    }
    return null;
  }

  function ensureGenericProduct(
    slug,
    title,
    sectionTitle,
    glyph,
    description,
    headMarker,
    listMarker
  ) {
    var anchor;
    var head;
    var list;
    if (!root || !modelEnabled(slug)) return;
    if (root.querySelector('[data-model="' + slug + '"]')) return;
    if (root.querySelector('[' + headMarker + ']')) return;

    anchor = productAnchor();
    if (!anchor) return;

    head = document.createElement('div');
    head.className = 'product-head';
    head.setAttribute(headMarker, '1');
    head.setAttribute('data-menu-recovery-head', slug);
    head.innerHTML = '<h2>' + sectionTitle + '</h2><small>1</small>';

    list = document.createElement('div');
    list.className = 'model-list';
    list.setAttribute(listMarker, '1');
    list.setAttribute('data-menu-recovery-list', slug);
    list.innerHTML =
      '<button class="model-row grunge-lite" type="button" data-model="' + slug + '">' +
      '<span class="model-glyph">' + glyph + '</span>' +
      '<div><strong>' + title + '</strong>' +
      '<small>Активная модель · цена из backend</small>' +
      '<p>' + description + '</p></div><span>›</span></button>';

    anchor.insertAdjacentElement('afterend', head);
    head.insertAdjacentElement('afterend', list);
  }

  function enhance() {
    scheduled = false;
    if (!root) return;

    if (modelEnabled('elevenlabs-turbo-2-5')) {
      promoteLauncher('voice');
      ensureGenericProduct(
        'elevenlabs-turbo-2-5',
        'ElevenLabs Turbo 2.5',
        'Аудио',
        '♫',
        'Озвучка и multilingual TTS',
        'data-tts-product-head',
        'data-tts-product-list'
      );
    }

    if (modelEnabled('suno-v5')) {
      promoteLauncher('music');
      ensureGenericProduct(
        'suno-v5',
        'Suno V5',
        'Музыка',
        '♫',
        'Песни и инструменталы · simple / custom',
        'data-suno-product-head',
        'data-suno-product-list'
      );
    }

    if (modelEnabled('kling-3-motion-control') && root.querySelector('[data-motion-open]')) {
      promoteLauncher('motion');
    }
  }

  function schedule() {
    if (scheduled) return;
    scheduled = true;
    window.setTimeout(enhance, 0);
  }

  window.addEventListener('foxgen:bootstrap', schedule);
  if (root && window.MutationObserver) {
    new MutationObserver(schedule).observe(root, { childList: true, subtree: true });
  }
  schedule();
})();
