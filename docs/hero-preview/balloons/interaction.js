(() => {
  'use strict';

  const root = document.documentElement;
  const hero = document.querySelector('.hero');
  const copy = document.querySelector('.hero-copy');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const finePointer = matchMedia('(hover: hover) and (pointer: fine)');
  const motionButton = document.querySelector('.motion-toggle');
  const themeButton = document.querySelector('.theme-toggle');
  const dialog = document.querySelector('.preview-dialog');
  const pointer = { x: 0, y: 0, active: false };
  const items = [...document.querySelectorAll('.floater')].map(el => ({
    el,
    motion: el.querySelector('.floater-motion'),
    depth: Number(el.dataset.depth),
    phase: Number(el.dataset.phase),
    tilt: Number(el.dataset.tilt),
    x: 0, y: 0, vx: 0, vy: 0,
  }));
  let layout = null;
  let frame = 0;
  let resizeFrame = 0;
  let previousTime = 0;
  let animationTime = 0;
  let userPaused = false;
  let heroVisible = true;
  let scrollY = window.scrollY;

  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  const motionEnabled = () => !reduced.matches && !userPaused;

  function measure() {
    resizeFrame = 0;
    // Measure the resting composition, independent of current scroll transforms.
    copy.style.removeProperty('--copy-y');
    copy.style.removeProperty('--copy-opacity');
    const heroRect = hero.getBoundingClientRect();
    const ranges = [];
    const walker = document.createTreeWalker(copy, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      if (!node.textContent.trim()) continue;
      const range = document.createRange();
      range.selectNodeContents(node);
      for (const rect of range.getClientRects()) {
        if (rect.width && rect.height) ranges.push(rect);
      }
    }
    copy.querySelectorAll('.button').forEach(el => ranges.push(el.getBoundingClientRect()));
    layout = {
      left: heroRect.left,
      top: heroRect.top + window.scrollY,
      width: hero.clientWidth,
      height: hero.clientHeight,
      safe: {
        left: Math.min(...ranges.map(r => r.left)) - heroRect.left - 16,
        right: Math.max(...ranges.map(r => r.right)) - heroRect.left + 16,
        top: Math.min(...ranges.map(r => r.top)) - heroRect.top - 14,
        bottom: Math.max(...ranges.map(r => r.bottom)) - heroRect.top + 14,
      },
    };
    items.forEach(item => {
      item.visible = getComputedStyle(item.el).display !== 'none';
      item.baseX = item.el.offsetLeft;
      item.baseY = item.el.offsetTop;
      item.width = item.el.offsetWidth;
      item.height = item.el.offsetHeight;
      item.x = item.y = item.vx = item.vy = 0;
    });
    if (motionEnabled()) {
      render(0);
      start();
    } else renderRest();
  }

  function fitDecoration(item, x, y, angle) {
    const radians = Math.abs(angle) * Math.PI / 180;
    // Include a small allowance for the rotation origin, which is above center.
    const fullWidth = item.width * Math.cos(radians) + item.height * Math.sin(radians) + 12;
    const fullHeight = item.height * Math.cos(radians) + item.width * Math.sin(radians) + 12;
    let scale = 1;
    const safe = layout.safe;
    const progress = motionEnabled() ? scrollProgress() : 0;
    const safeTop = safe.top - progress * 24;
    const safeBottom = safe.bottom - progress * 24;
    let centerX = item.baseX + x;
    let centerY = item.baseY + y;

    if (centerY + fullHeight / 2 > safeTop && centerY - fullHeight / 2 < safeBottom && centerX + fullWidth / 2 > safe.left && centerX - fullWidth / 2 < safe.right) {
      if (item.baseY < safe.top) {
        // Top accents stay above the copy instead of jumping sideways when
        // a cursor approaches them. Bottom accents use the same principle.
        centerY = Math.min(centerY, safeTop - fullHeight / 2 - 4);
      } else if (item.baseY > safe.bottom) {
        centerY = Math.max(centerY, safeBottom + fullHeight / 2 + 4);
      } else {
        const leftSide = item.baseX < layout.width / 2;
        const corridor = leftSide ? safe.left : layout.width - safe.right;
        scale = Math.min(1, Math.max(0.3, (corridor - 24) / fullWidth));
        const half = fullWidth * scale / 2;
        centerX = leftSide ? Math.min(centerX, safe.left - half - 4) : Math.max(centerX, safe.right + half + 4);
      }
    }
    const half = fullWidth * scale / 2;
    centerX = clamp(centerX, half + 8, layout.width - half - 8);
    return { x: centerX - item.baseX, y: centerY - item.baseY, scale };
  }

  function scrollProgress() {
    return clamp(scrollY / Math.max(1, layout.height), 0, 1);
  }

  function render(dt) {
    if (!layout) return;
    const progress = scrollProgress();
    copy.style.setProperty('--copy-y', `${-progress * 24}px`);
    copy.style.setProperty('--copy-opacity', 1 - progress * .16);
    const localPointerX = pointer.x - layout.left;
    const localPointerY = pointer.y + scrollY - layout.top;

    items.forEach(item => {
      if (!item.visible) return;
      const floatX = Math.sin(animationTime * .42 + item.phase) * (3 + item.depth * 3);
      const floatY = Math.sin(animationTime * .65 + item.phase) * (5 + item.depth * 6);
      const direction = item.baseX < layout.width / 2 ? -1 : 1;
      const scrollX = direction * progress * (25 + item.depth * 35);
      const scrollLift = -progress * (38 + item.depth * 65);
      let targetX = 0;
      let targetY = 0;

      if (pointer.active && finePointer.matches) {
        targetX = (localPointerX / layout.width - .5) * 2 * item.depth * 12;
        targetY = (localPointerY / layout.height - .5) * 2 * item.depth * 8;
        const dx = item.baseX + floatX + scrollX - localPointerX;
        const dy = item.baseY + floatY + scrollLift - localPointerY;
        const distance = Math.hypot(dx, dy);
        const radius = Math.max(130, item.width * .8);
        if (distance < radius) {
          const strength = Math.pow(1 - distance / radius, 1.5) * (40 + item.depth * 28);
          targetX += (distance > 1 ? dx / distance : direction) * strength;
          targetY += (distance > 1 ? dy / distance : -.4) * strength;
        }
      }

      // Damped spring: immediate enough to feel responsive, with a soft return.
      item.vx += ((targetX - item.x) * 88 - item.vx * 15) * dt;
      item.vy += ((targetY - item.y) * 88 - item.vy * 15) * dt;
      item.x += item.vx * dt;
      item.y += item.vy * dt;
      const angle = item.tilt + Math.sin(animationTime * .4 + item.phase) * 1.8 + clamp(item.vx * .025, -2, 2);
      const position = fitDecoration(item, item.x + floatX + scrollX, item.y + floatY + scrollLift, angle);
      item.motion.style.transform = `translate3d(${position.x.toFixed(3)}px, ${position.y.toFixed(3)}px, 0) rotate(${angle.toFixed(3)}deg) scale(${position.scale.toFixed(4)})`;
    });
  }

  function renderRest() {
    if (!layout) return;
    copy.style.removeProperty('--copy-y');
    copy.style.removeProperty('--copy-opacity');
    items.forEach(item => {
      if (!item.visible) return;
      item.x = item.y = item.vx = item.vy = 0;
      const position = fitDecoration(item, 0, 0, item.tilt);
      item.motion.style.transform = `translate3d(${position.x}px, ${position.y}px, 0) rotate(${item.tilt}deg) scale(${position.scale})`;
    });
  }

  function tick(now) {
    frame = 0;
    if (!motionEnabled() || !heroVisible || document.hidden) return;
    const dt = previousTime ? Math.min((now - previousTime) / 1000, .032) : 1 / 60;
    previousTime = now;
    animationTime += dt;
    render(dt);
    frame = requestAnimationFrame(tick);
  }

  function start() {
    if (!frame && motionEnabled() && heroVisible && !document.hidden) {
      previousTime = 0;
      frame = requestAnimationFrame(tick);
    }
  }

  function stop() {
    cancelAnimationFrame(frame);
    frame = 0;
    previousTime = 0;
  }

  function syncMotion() {
    const paused = !motionEnabled();
    root.classList.toggle('is-paused', paused);
    motionButton.setAttribute('aria-pressed', String(paused));
    motionButton.disabled = reduced.matches;
    motionButton.querySelector('span').textContent = reduced.matches ? 'Reduced motion' : userPaused ? 'Resume motion' : 'Pause motion';
    motionButton.setAttribute('aria-label', motionButton.querySelector('span').textContent);
    motionButton.title = reduced.matches ? 'Your device prefers reduced motion' : motionButton.querySelector('span').textContent;
    if (paused) {
      root.classList.add('entrance-complete');
      stop();
      pointer.active = false;
      renderRest();
      document.querySelectorAll('.reveal').forEach(el => el.classList.add('is-visible'));
    } else start();
  }

  hero.addEventListener('pointermove', event => {
    if (event.pointerType !== 'mouse' || !finePointer.matches || !motionEnabled()) return;
    pointer.x = event.clientX;
    pointer.y = event.clientY;
    pointer.active = true;
  }, { passive: true });
  hero.addEventListener('pointerleave', () => { pointer.active = false; }, { passive: true });
  window.addEventListener('blur', () => { pointer.active = false; });
  document.addEventListener('visibilitychange', () => {
    pointer.active = false;
    if (document.hidden) stop(); else start();
  });
  window.addEventListener('scroll', () => {
    scrollY = window.scrollY;
    root.classList.toggle('is-scrolled', scrollY > 8);
  }, { passive: true });
  function scheduleMeasure() {
    if (!resizeFrame) resizeFrame = requestAnimationFrame(measure);
  }
  window.addEventListener('resize', scheduleMeasure, { passive: true });
  window.addEventListener('pageshow', () => {
    scrollY = window.scrollY;
    if (scrollY > 20) root.classList.add('restore-position');
    root.classList.toggle('is-scrolled', scrollY > 8);
    scheduleMeasure();
  });
  reduced.addEventListener('change', () => { syncMotion(); scheduleMeasure(); });
  finePointer.addEventListener('change', () => { pointer.active = false; });
  motionButton.addEventListener('click', () => { userPaused = !userPaused; syncMotion(); });
  motionButton.hidden = false;

  function setTheme(theme) {
    root.dataset.theme = theme;
    const label = theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme';
    themeButton.setAttribute('aria-label', label);
    themeButton.title = label;
    document.querySelector('meta[name="theme-color"]').content = theme === 'dark' ? '#101010' : '#f7f7f4';
    try { localStorage.setItem('balloorina-balloon-preview-theme', theme); } catch (_) { /* File previews can disable storage. */ }
  }
  let savedTheme = 'dark';
  try { savedTheme = localStorage.getItem('balloorina-balloon-preview-theme') === 'light' ? 'light' : 'dark'; } catch (_) { /* Default to the current site's dark palette. */ }
  setTheme(savedTheme);
  themeButton.hidden = false;
  themeButton.addEventListener('click', () => setTheme(root.dataset.theme === 'dark' ? 'light' : 'dark'));

  document.querySelectorAll('[data-preview]').forEach(link => {
    link.addEventListener('click', event => {
      if (typeof dialog.showModal !== 'function') return;
      event.preventDefault();
      dialog.querySelector('h2').textContent = link.dataset.preview;
      dialog.showModal();
    });
  });
  dialog.addEventListener('click', event => {
    const r = dialog.getBoundingClientRect();
    if (event.target === dialog && (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom)) dialog.close();
  });

  if ('IntersectionObserver' in window) {
    const heroObserver = new IntersectionObserver(entries => {
      heroVisible = entries[0].isIntersecting;
      if (heroVisible) start(); else stop();
    });
    heroObserver.observe(hero);
    if (motionEnabled()) {
      root.classList.add('has-reveals');
      const revealObserver = new IntersectionObserver(entries => {
        entries.forEach(entry => {
          if (!entry.isIntersecting) return;
          entry.target.classList.add('is-visible');
          revealObserver.unobserve(entry.target);
        });
      }, { threshold: .08, rootMargin: '0px 0px -20px 0px' });
      document.querySelectorAll('.reveal').forEach(el => revealObserver.observe(el));
    }
  }

  // Read text bounds before entrance animations hide their lines. Local font
  // metrics are refreshed once loaded, after the entrance has completed.
  measure();
  if (scrollY > 20) root.classList.add('restore-position');
  if (motionEnabled()) root.classList.add('motion-ready');
  syncMotion();
  document.fonts.ready.then(() => {
    // Ensure the protected text region uses final glyph positions, not an
    // intermediate entrance transform. Re-measure again after the reveal.
    setTimeout(() => {
      root.classList.add('entrance-complete');
      scheduleMeasure();
    }, 1450);
  });
})();
