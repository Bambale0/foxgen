const root = document.getElementById('app');

let desiredSurface = root?.querySelector('[data-backend-surface="models"]')
  ? 'models'
  : root?.querySelector('[data-backend-surface="home"]')
    ? 'home'
    : null;
let recoveryScheduled = false;

function requestSurface(surface) {
  if (!root || !surface) return;
  const button = document.createElement('button');
  button.type = 'button';
  button.hidden = true;
  button.dataset.backendNav = surface;
  root.append(button);
  button.click();
  button.remove();
}

function recoverSurface() {
  recoveryScheduled = false;
  if (!root || !desiredSurface) return;
  if (root.querySelector(`[data-backend-surface="${desiredSurface}"]`)) return;
  requestSurface(desiredSurface);
}

function scheduleRecovery() {
  if (!desiredSurface || recoveryScheduled) return;
  recoveryScheduled = true;
  queueMicrotask(recoverSurface);
}

root?.addEventListener(
  'click',
  (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;

    const custom = target.closest('[data-backend-nav]');
    if (custom) {
      const surface = custom.dataset.backendNav;
      if (surface === 'home' || surface === 'models') desiredSurface = surface;
      return;
    }

    if (target.closest('[data-nav]')) desiredSurface = null;
  },
  true,
);

if (root && window.MutationObserver) {
  new MutationObserver(scheduleRecovery).observe(root, {childList: true, subtree: true});
}

scheduleRecovery();
