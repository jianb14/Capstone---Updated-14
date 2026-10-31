(() => {
  'use strict';

  const root = document.documentElement;
  const stage = document.querySelector('.hero-stage');
  const scene = document.querySelector('.hero-scene');
  const copy = document.querySelector('.hero-copy');
  const gallery = document.querySelector('.hero-gallery');
  const cards = [...document.querySelectorAll('.gallery-item')];
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const desktop = window.matchMedia('(min-width: 1100px) and (min-height: 760px)');
  const dialog = document.querySelector('.preview-dialog');
  const scrollCopy = document.querySelector('.scroll-copy');
  let metrics = null;
  let scrollFrame = 0;
  let resizeFrame = 0;

  const clamp = (value, min = 0, max = 1) => Math.min(max, Math.max(min, value));
  const smooth = value => value * value * (3 - 2 * value);

  function render() {
    scrollFrame = 0;
    if (!metrics) return;
    if (metrics.pinned) {
      const progress = clamp((window.scrollY - metrics.top) / metrics.travel);
      const cue = progress > .88 ? 'KEEP SCROLLING TO EXPLORE' : 'SCROLL TO BRING IT TOGETHER';
      if (scrollCopy.textContent !== cue) scrollCopy.textContent = cue;
      const copyProgress = smooth(clamp(progress / .8));
      copy.style.setProperty('--copy-y', `${-30 * copyProgress}px`);
      copy.style.setProperty('--copy-scale', 1 - .2 * copyProgress);
      stage.style.setProperty('--label-opacity', clamp((progress - .55) / .3));
      cards.forEach((card, index) => {
        // Each photograph settles on its own curve. All reach the same row.
        const finish = [0.9, 1, 0.95][index];
        const remaining = 1 - smooth(clamp(progress / finish));
        const start = metrics.starts[index];
        const scale = 1 + (start.scale - 1) * remaining;
        card.style.transform = `translate3d(${start.dx * remaining}px, ${start.dy * remaining}px, 0) rotate(${start.rotation * remaining}deg) scale(${scale})`;
      });
    } else {
      scrollCopy.textContent = 'SCROLL TO EXPLORE';
      // Normal document scrolling on smaller screens; only a small visual lift.
      const progress = reducedMotion.matches ? 0 : clamp((window.scrollY - metrics.top) / 600);
      cards.forEach((card, index) => {
        card.style.setProperty('--mobile-y', `${-progress * [8, 16, 11][index]}px`);
      });
    }
  }

  function measure() {
    resizeFrame = 0;
    const pinned = desktop.matches && !reducedMotion.matches;
    stage.classList.toggle('is-pinned', pinned);
    cards.forEach(card => {
      card.style.removeProperty('transform');
      card.style.removeProperty('--mobile-y');
    });
    copy.style.removeProperty('--copy-y');
    copy.style.removeProperty('--copy-scale');
    stage.style.removeProperty('--label-opacity');

    const stageRect = stage.getBoundingClientRect();
    const sceneRect = scene.getBoundingClientRect();
    metrics = {
      pinned,
      top: stageRect.top + window.scrollY,
      travel: Math.max(1, stage.offsetHeight - scene.offsetHeight),
      starts: [],
    };
    if (pinned) {
      const points = [
        { x: .115, y: .50, scale: .84, rotation: -10 },
        { x: .50, y: .805, scale: .70, rotation: -5 },
        { x: .885, y: .475, scale: .82, rotation: 9 },
      ];
      metrics.starts = cards.map((card, index) => {
        const rect = card.getBoundingClientRect();
        const point = points[index];
        const angle = Math.abs(point.rotation) * Math.PI / 180;
        const rotatedWidth = rect.width * Math.cos(angle) + rect.height * Math.sin(angle);
        const rotatedHeight = rect.height * Math.cos(angle) + rect.width * Math.sin(angle);
        let scale = point.scale;
        let centerY = sceneRect.top + sceneRect.height * point.y;
        if (index === 1) {
          // Fit the middle photo between the buttons and scroll cue, even on
          // short desktop windows. This also accounts for the rotated corners.
          const top = copy.getBoundingClientRect().bottom + 22;
          const bottom = sceneRect.bottom - 66;
          scale = Math.min(scale, Math.max(0, bottom - top) / rotatedHeight);
          centerY = clamp(centerY, top + rotatedHeight * scale / 2, bottom - rotatedHeight * scale / 2);
        }
        const halfWidth = rotatedWidth * scale / 2;
        const centerX = clamp(sceneRect.width * point.x, halfWidth + 18, sceneRect.width - halfWidth - 18);
        return {
          dx: sceneRect.left + centerX - (rect.left + rect.width / 2),
          dy: centerY - (rect.top + rect.height / 2),
          scale,
          rotation: point.rotation,
        };
      });
    }
    render();
  }

  function scheduleMeasure() {
    if (!resizeFrame) resizeFrame = requestAnimationFrame(measure);
  }

  function scrollToPosition(top) {
    window.scrollTo({ top, behavior: reducedMotion.matches ? 'instant' : 'smooth' });
  }

  // The gallery anchor should land on the completed composition, not halfway
  // through the sticky scene. Explicit links also work with JavaScript disabled.
  document.querySelectorAll('[data-gallery-link]').forEach(link => {
    link.addEventListener('click', event => {
      if (!metrics) return;
      event.preventDefault();
      scrollToPosition(metrics.pinned ? metrics.top + metrics.travel : gallery.getBoundingClientRect().top + window.scrollY - 120);
    });
  });

  document.querySelectorAll('[data-replay], .brand, .site-nav a[href="#top"]').forEach(link => {
    link.addEventListener('click', event => {
      event.preventDefault();
      scrollToPosition(0);
    });
  });

  document.querySelectorAll('[data-preview-action]').forEach(link => {
    link.addEventListener('click', event => {
      if (typeof dialog.showModal !== 'function') return;
      event.preventDefault();
      const isBooking = link.dataset.previewAction === 'booking';
      dialog.querySelector('h2').textContent = isBooking ? 'Book Your Event Now' : 'View Our Packages';
      dialog.querySelector('#dialog-description').textContent = isBooking
        ? 'This is a design preview. Event booking is available on the main Balloorina website.'
        : 'This is a design preview. Explore event packages on the main Balloorina website.';
      dialog.showModal();
    });
  });
  dialog.addEventListener('click', event => {
    const rect = dialog.getBoundingClientRect();
    if (event.target === dialog && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) dialog.close();
  });

  window.addEventListener('scroll', () => {
    if (!scrollFrame) scrollFrame = requestAnimationFrame(render);
  }, { passive: true });
  window.addEventListener('resize', scheduleMeasure, { passive: true });
  reducedMotion.addEventListener('change', scheduleMeasure);
  desktop.addEventListener('change', scheduleMeasure);
  window.addEventListener('pageshow', () => {
    if (window.scrollY > 20) root.classList.add('restore-position');
    scheduleMeasure();
  });

  // Re-measure after the local font resolves, including restored scroll positions.
  measure();
  if (window.scrollY > 20) root.classList.add('restore-position');
  root.classList.add('has-js');
  document.fonts.ready.then(scheduleMeasure);
})();
