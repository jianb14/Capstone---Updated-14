/* ==========================================================================
   HERO FLOATING OBJECTS - image decorative layer (HOME PAGE)
   --------------------------------------------------------------------------
   - Gumagamit ng mga party image mula sa static/images/*-float.png.
   - Data-driven: lahat ng balloon ay object sa BALLOONS config array.
   - Bawat balloon ay may apat na magkakahiwalay na animation (Web
     Animations API + CSS):
       1. FLOATING + REPOSITION (A->B->C->D waypoints, smooth interpolation)
       2. FADE IN / FADE OUT life cycle
       3. SOFT BLINK (CSS keyframes, kanya-kanyang timing)
       4. ROTATION + SCALE habang naglalakbay
   - Walang JS intervals - puro compositor-driven (transform/opacity lang).
   - Nirerespeto ang prefers-reduced-motion (static balloons).
   ========================================================================== */

(function () {
    'use strict';

    var heroSection = document.querySelector('.hero');
    if (!heroSection || heroSection.dataset.balloonsInitialized) return;
    heroSection.dataset.balloonsInitialized = 'true';

    var reducedMotionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    var tabletQuery = window.matchMedia('(max-width: 968px)');
    var mobileQuery = window.matchMedia('(max-width: 640px)');

    /* Lakas ng galaw ayon sa depth: maliliit (bg) = pinakamalakas na galaw; malalaki (fg) = mabagal lang para hindi nagpapatong. */
    var DEPTH_SPEED = { fg: 0.65, mg: 1, bg: 1.35 };

    /* Mga party image (mula sa data-img-0..N attributes ng layer) */
    var BALLOON_IMGS = [];

    /* Multiplier ng layo ng galaw ayon sa screen size */
    function currentMoveScale() {
        if (mobileQuery.matches) return 0.35;
        if (tabletQuery.matches) return 0.6;
        return 1;
    }

    /*
     * Floating item config:
     *   img    -> index ng party image (0=doubleballoon, 1=giftbox,
     *             2=partyhat [naayos na - tinanggal ang egg-shaped dome],
     *             3=partyhorn, 4=ribon, 5=balloon)
     *   tint   -> 0 (buong tindig) | 1 (medyo malabo) | 2 (pinakamalabo) -
     *             opacity variations para may depth
     *   size   -> lapad ng item sa px
     *   x, y   -> position (% ng hero)
     *   rot0   -> static na rotation (deg)
     *   depth  -> 'fg' | 'mg' | 'bg' (lakas ng galaw + layering)
     *   mX, mY -> posisyon sa MOBILE (% ng hero) - apat na sulok
     *
     * LAYOUT RULES (para hindi magkatabi/nagpapatong at walang napuputol):
     *   - Bawat item ay may sariling "puwesto" - malayo ang mga ito sa isat isa, at maliit lang ang drift ng
     *     malalaking item.
     *   - Lahat ng item, KASAMA ang drift range nito, ay nakapasok sa hero
     *     (may margin sa gilid) para walang object na napuputol sa edge -
     *     iyon ang dating hati na nakikita sa hero.
     *   - Sa MOBILE, apat lang ang kita at naka-pwesto sa apat na SULOK
     *     (top-left, top-right, bottom-left, bottom-right) gamit ang mX/mY -
     *     para hindi nagdidikit sa gitna at hindi tumatabla sa text/CTA.
     */
    var BALLOONS = [
        /* ============ KALIWA (malalaki, desktop lang, mabagal ang galaw) ============ */
        { img: 0, tint: 0, size: 120, x: 9,  y: 12, rot0: -8, depth: 'fg', opacity: 0.85,
          drift: { dur: 44, delay: -3,  wps: [[28, -22, -6, 1.03], [-24, 26, 5, 0.97], [16, -18, -3, 1.02]] },
          life: { mode: 'cycle', dur: 50, delay: 0 },
          blink: true,  blinkDur: 9,   blinkDelay: 1.5, blinkMin: 0.55,
          hideTablet: true,  hideMobile: true },

        { img: 5, tint: 1, size: 80,  x: 17, y: 38, rot0: 6,  depth: 'mg', opacity: 0.75,
          drift: { dur: 34, delay: -11, wps: [[40, -34, 8, 1.03], [-36, 40, -7, 0.97], [24, -28, 4, 1]] },
          life: { mode: 'soft',  dur: 30, delay: -6 },
          blink: false,
          hideTablet: false, hideMobile: true },

        { img: 3, tint: 0, size: 62,  x: 8,  y: 66, rot0: -9, depth: 'mg', opacity: 0.7,
          drift: { dur: 32, delay: -22, wps: [[42, -30, -6, 1], [36, 34, 5, 0.95], [22, -24, -2, 1]] },
          life: { mode: 'soft',  dur: 33, delay: -4 },
          blink: true,  blinkDur: 9.5, blinkDelay: 6,   blinkMin: 0.4,
          hideTablet: false, hideMobile: true },

        { img: 4, tint: 1, size: 44,  x: 20, y: 78, rot0: -4, depth: 'bg', opacity: 0.58,
          drift: { dur: 27, delay: -6,  wps: [[52, 26, 6, 1], [-46, -30, -5, 0.96], [30, 20, 3, 1]] },
          life: { mode: 'cycle', dur: 36, delay: -12 },
          blink: true,  blinkDur: 6.5, blinkDelay: 1,   blinkMin: 0.38,
          hideTablet: false, hideMobile: true },

        /* ============ GITNA (maliit at malalabo, hindi tumatabla sa text) ============ */
        { img: 1, tint: 2, size: 52,  x: 40, y: 10, rot0: 0,  depth: 'bg', opacity: 0.5, mX: 14, mY: 8,
          drift: { dur: 29, delay: -20, wps: [[56, -26, -5, 1], [-48, 30, 4, 0.95], [30, -20, -2, 1]] },
          life: { mode: 'soft',  dur: 27, delay: -3 },
          blink: false,
          hideTablet: false, hideMobile: false },

        { img: 5, tint: 2, size: 44,  x: 55, y: 14, rot0: 0,  depth: 'bg', opacity: 0.55, mX: 86, mY: 9,
          drift: { dur: 31, delay: -9,  wps: [[-50, 28, 5, 1], [44, -32, -4, 0.95], [26, 20, 2, 1]] },
          life: { mode: 'cycle', dur: 34, delay: -15 },
          blink: true,  blinkDur: 7.8, blinkDelay: 2.2, blinkMin: 0.38,
          hideTablet: false, hideMobile: false },

        { img: 2, tint: 2, size: 48,  x: 46, y: 80, rot0: 8,  depth: 'bg', opacity: 0.55, mX: 13, mY: 79,
          drift: { dur: 28, delay: -14, wps: [[48, -24, -6, 1], [-42, 24, 4, 0.96], [26, -18, -2, 1]] },
          life: { mode: 'cycle', dur: 32, delay: -8 },
          blink: true,  blinkDur: 6.8, blinkDelay: 4.5, blinkMin: 0.35,
          hideTablet: false, hideMobile: false },

        { img: 4, tint: 2, size: 40,  x: 60, y: 76, rot0: 12, depth: 'bg', opacity: 0.5, mX: 87, mY: 77,
          drift: { dur: 26, delay: -2,  wps: [[-52, 22, 5, 1], [44, -26, -4, 0.95], [28, 18, 2, 1]] },
          life: { mode: 'soft',  dur: 30, delay: -6 },
          blink: true,  blinkDur: 8.5, blinkDelay: 6.2, blinkMin: 0.38,
          hideTablet: false, hideMobile: false },

        /* ============ KANAN (halo ng malaki at maliit) ============ */
        { img: 0, tint: 0, size: 100, x: 89, y: 20, rot0: 7,  depth: 'mg', opacity: 0.8,
          drift: { dur: 40, delay: -18, wps: [[-30, -24, 6, 1.03], [26, 28, -5, 0.96], [18, -20, 3, 1.01]] },
          life: { mode: 'cycle', dur: 46, delay: -8 },
          blink: true,  blinkDur: 8,   blinkDelay: 2,   blinkMin: 0.45,
          hideTablet: true,  hideMobile: true },

        { img: 5, tint: 1, size: 72,  x: 84, y: 46, rot0: -6, depth: 'mg', opacity: 0.75,
          drift: { dur: 33, delay: -16, wps: [[-44, -30, 7, 1.01], [38, 36, -6, 0.96], [24, -24, 3, 1]] },
          life: { mode: 'cycle', dur: 40, delay: -20 },
          blink: true,  blinkDur: 10,  blinkDelay: 4,   blinkMin: 0.5,
          hideTablet: false, hideMobile: true },

        { img: 3, tint: 1, size: 58,  x: 91, y: 68, rot0: 9,  depth: 'mg', opacity: 0.68,
          drift: { dur: 30, delay: -25, wps: [[-40, -28, -6, 1], [34, 30, 5, 0.95], [20, -22, -2, 1]] },
          life: { mode: 'soft',  dur: 31, delay: -10 },
          blink: true,  blinkDur: 9,   blinkDelay: 3.5, blinkMin: 0.4,
          hideTablet: false, hideMobile: true },

        { img: 2, tint: 1, size: 40,  x: 95, y: 40, rot0: -10, depth: 'bg', opacity: 0.52,
          drift: { dur: 27, delay: -7,  wps: [[-26, 24, 5, 1], [22, -28, -4, 0.95], [14, 18, 2, 1]] },
          life: { mode: 'cycle', dur: 35, delay: -13 },
          blink: true,  blinkDur: 6.2, blinkDelay: 1.8, blinkMin: 0.38,
          hideTablet: false, hideMobile: true },

        { img: 1, tint: 2, size: 46,  x: 82, y: 80, rot0: -5, depth: 'bg', opacity: 0.55,
          drift: { dur: 29, delay: -17, wps: [[-46, -24, 5, 1], [40, 26, -4, 0.96], [24, -18, 2, 1]] },
          life: { mode: 'soft',  dur: 33, delay: -6 },
          blink: true,  blinkDur: 8.5, blinkDelay: 6.2, blinkMin: 0.38,
          hideTablet: false, hideMobile: true },

        { img: 4, tint: 1, size: 34,  x: 68, y: 8,  rot0: -12, depth: 'bg', opacity: 0.5,
          drift: { dur: 25, delay: -11, wps: [[56, 18, 6, 1], [-48, -22, -5, 0.96], [30, 16, 3, 1]] },
          life: { mode: 'cycle', dur: 30, delay: -9 },
          blink: true,  blinkDur: 7,   blinkDelay: 3,   blinkMin: 0.36,
          hideTablet: false, hideMobile: true },

        /* ============ DAGDAG (scatter sa mga bakante, maliliit at malalabo;
             karamihan desktop lang para malinis pa rin sa tablet/mobile) ============ */
        { img: 1, tint: 2, size: 36,  x: 28, y: 9,  rot0: 4,  depth: 'bg', opacity: 0.5,
          drift: { dur: 26, delay: -2,  wps: [[28, -16, 4, 1], [-24, 20, -3, 0.97], [16, -12, 2, 1]] },
          life: { mode: 'soft',  dur: 28, delay: -2 },
          blink: true,  blinkDur: 7.4, blinkDelay: 2.6, blinkMin: 0.4,
          hideTablet: false, hideMobile: true },

        { img: 3, tint: 2, size: 34,  x: 30, y: 24, rot0: -7, depth: 'bg', opacity: 0.45,
          drift: { dur: 24, delay: -14, wps: [[30, 18, 5, 1], [-26, -22, -4, 0.97], [18, 14, 3, 1]] },
          life: { mode: 'cycle', dur: 31, delay: -14 },
          blink: true,  blinkDur: 6.6, blinkDelay: 4.8, blinkMin: 0.36,
          hideTablet: true,  hideMobile: true },

        { img: 5, tint: 2, size: 36,  x: 26, y: 56, rot0: -5, depth: 'bg', opacity: 0.48,
          drift: { dur: 27, delay: -7,  wps: [[26, -20, 4, 1], [-30, 24, -3, 0.97], [18, -14, 2, 1]] },
          life: { mode: 'soft',  dur: 32, delay: -7 },
          blink: false,
          hideTablet: true,  hideMobile: true },

        { img: 2, tint: 2, size: 34,  x: 33, y: 79, rot0: -6, depth: 'bg', opacity: 0.48,
          drift: { dur: 25, delay: -18, wps: [[24, -18, -4, 1], [-28, 22, 3, 0.97], [18, -14, -2, 1]] },
          life: { mode: 'cycle', dur: 33, delay: -18 },
          blink: true,  blinkDur: 7.2, blinkDelay: 5.4, blinkMin: 0.36,
          hideTablet: false, hideMobile: true },

        { img: 4, tint: 2, size: 32,  x: 76, y: 14, rot0: 10, depth: 'bg', opacity: 0.48,
          drift: { dur: 23, delay: -11, wps: [[24, 14, 5, 1], [-20, -16, -4, 0.96], [14, 10, 3, 1]] },
          life: { mode: 'cycle', dur: 29, delay: -11 },
          blink: true,  blinkDur: 6.4, blinkDelay: 3.2, blinkMin: 0.36,
          hideTablet: true,  hideMobile: true },

        { img: 1, tint: 2, size: 36,  x: 70, y: 60, rot0: -8, depth: 'bg', opacity: 0.45,
          drift: { dur: 26, delay: -4,  wps: [[24, 18, -4, 1], [-28, -22, 3, 0.97], [18, 14, -2, 1]] },
          life: { mode: 'soft',  dur: 34, delay: -4 },
          blink: true,  blinkDur: 8.2, blinkDelay: 2.4, blinkMin: 0.4,
          hideTablet: true,  hideMobile: true },

        { img: 4, tint: 1, size: 32,  x: 80, y: 29, rot0: -10, depth: 'bg', opacity: 0.5,
          drift: { dur: 24, delay: -21, wps: [[20, 14, 4, 1], [-18, -14, -3, 0.96], [12, 10, 2, 1]] },
          life: { mode: 'cycle', dur: 30, delay: -21 },
          blink: true,  blinkDur: 6.8, blinkDelay: 1.6, blinkMin: 0.38,
          hideTablet: true,  hideMobile: true },

        { img: 3, tint: 2, size: 36,  x: 73, y: 76, rot0: 6,  depth: 'bg', opacity: 0.45,
          drift: { dur: 25, delay: -9,  wps: [[20, 14, -5, 1], [-18, -14, 4, 0.96], [12, 10, -2, 1]] },
          life: { mode: 'soft',  dur: 31, delay: -9 },
          blink: true,  blinkDur: 7.6, blinkDelay: 4.2, blinkMin: 0.38,
          hideTablet: true,  hideMobile: true },

        { img: 5, tint: 2, size: 34,  x: 8,  y: 45, rot0: 8,  depth: 'bg', opacity: 0.45,
          drift: { dur: 28, delay: -15, wps: [[20, -16, 4, 1], [-22, 18, -3, 0.97], [14, -12, 2, 1]] },
          life: { mode: 'cycle', dur: 35, delay: -15 },
          blink: true,  blinkDur: 7,   blinkDelay: 5.8, blinkMin: 0.36,
          hideTablet: false, hideMobile: true }
    ];

    /* Buong balloon visual - gumagamit ng mga party image mula sa
       static/images. Ang cfg.img ang pumipili kung aling image ang gagamitin:
       0=doubleballoon, 1=giftbox, 2=partyhat (naayos na ang crop), 3=partyhorn,
       4=ribon, 5=balloon. */
    function balloonVisualMarkup(cfg) {
        var src = BALLOON_IMGS[cfg.img % BALLOON_IMGS.length];
        return '<img src="' + src + '" alt="" draggable="false">';
    }

    /* ======================================================================
       ANIMATIONS - Web Animations API (compositor-driven, walang intervals)
       ====================================================================== */

    /* Bubuuin ang drift element kada balloon */
    function createBalloon(cfg) {
        /* Sa MOBILE: gumagamit ng corner position (mX/mY) kung mayroon */
        var isMobile = mobileQuery.matches;
        var px = (isMobile && cfg.mX != null) ? cfg.mX : cfg.x;
        var py = (isMobile && cfg.mY != null) ? cfg.mY : cfg.y;
        var el = document.createElement('div');
        el.className = [
            'balloon',
            'balloon--' + cfg.depth,
            cfg.blink ? 'balloon--blink' : '',
            cfg.tint > 0 ? 'hb-t' + cfg.tint : '',
            cfg.hideTablet ? 'balloon--hide-tablet' : '',
            cfg.hideMobile ? 'balloon--hide-mobile' : ''
        ].filter(Boolean).join(' ');

        el.style.setProperty('--x', px + '%');
        el.style.setProperty('--y', py + '%');
        el.style.setProperty('--size', cfg.size + 'px');
        el.style.setProperty('--opacity', cfg.opacity);
        el.style.setProperty('--blink-dur', (cfg.blinkDur || 8) + 's');
        el.style.setProperty('--blink-delay', (cfg.blinkDelay || 0) + 's');
        el.style.setProperty('--blink-min', cfg.blinkMin != null ? cfg.blinkMin : 0.5);
        /* Static na tindig ng balloon (hiwalay sa drift rotation) */
        el.style.transform = 'rotate(' + (cfg.rot0 || 0) + 'deg)';

        var drift = document.createElement('div');
        drift.className = 'balloon-drift';

        var shape = document.createElement('div');
        shape.className = 'balloon-shape';
        shape.innerHTML = balloonVisualMarkup(cfg);

        drift.appendChild(shape);
        el.appendChild(drift);
        return { el: el, cfg: cfg };
    }

    /* Drift keyframes: home -> wp1 -> wp2 -> wp3 -> home (seamless loop).
       Ito ang ACTUAL na paglipat ng balloon sa ibang pwesto - smooth na
       interpolation sa pagitan ng waypoints, walang teleport. */
    function driftKeyframes(cfg, moveScale) {
        var speed = DEPTH_SPEED[cfg.depth] || 0.7;
        var kfs = [{
            transform: 'translate3d(0, 0, 0) rotate(0deg) scale(1)',
            offset: 0
        }];
        cfg.drift.wps.forEach(function (wp, i) {
            kfs.push({
                transform: 'translate3d(' + (wp[0] * moveScale * speed).toFixed(1) + 'px, ' +
                    (wp[1] * moveScale * speed).toFixed(1) + 'px, 0) ' +
                    'rotate(' + wp[2] + 'deg) scale(' + wp[3] + ')',
                offset: (i + 1) / (cfg.drift.wps.length + 1)
            });
        });
        kfs.push({
            transform: 'translate3d(0, 0, 0) rotate(0deg) scale(1)',
            offset: 1
        });
        return kfs;
    }

    /* Life cycle: 'cycle' = fade in -> out -> in (umaabot sa 0 = disappears);
       'soft' = nagiging faint lang, hindi mawawala tuluyan */
    function lifeKeyframes(cfg) {
        var o = cfg.opacity;
        if (cfg.life.mode === 'soft') {
            return [
                { opacity: o, offset: 0 },
                { opacity: o * 0.55, offset: 0.3 },
                { opacity: o * 0.85, offset: 0.55 },
                { opacity: o * 0.4, offset: 0.8 },
                { opacity: o, offset: 1 }
            ];
        }
        return [
            { opacity: 0, offset: 0 },
            { opacity: o * 0.45, offset: 0.14 },
            { opacity: o, offset: 0.32 },
            { opacity: o * 0.7, offset: 0.52 },
            { opacity: o * 0.3, offset: 0.72 },
            { opacity: o * 0.08, offset: 0.88 },
            { opacity: 0, offset: 1 }
        ];
    }

    function startAnimations(items) {
        var moveScale = currentMoveScale();
        items.forEach(function (item) {
            var cfg = item.cfg;

            /* 1) Float + repositioning (punta sa ibang pwesto, palog-loop).
               Negatibong delay para nasa gitna na ng cycle sa simula pa lang
               (hindi naghihintay ang mga balloon na lumitaw). */
            item.el.firstChild.animate(driftKeyframes(cfg, moveScale), {
                duration: cfg.drift.dur * 1000,
                delay: cfg.drift.delay * 1000,
                iterations: Infinity,
                easing: 'ease-in-out'
            });

            /* 2) Fade in / fade out life cycle */
            item.el.animate(lifeKeyframes(cfg), {
                duration: cfg.life.dur * 1000,
                delay: cfg.life.delay * 1000,
                iterations: Infinity,
                easing: 'ease-in-out'
            });

            /* 3) Soft blink = CSS animation sa .balloon-shape (tingnan ang CSS) */
        });
    }

    /* ======================================================================
       BUILD - gumawa ng balloons at pagsimulan ang animations
       ====================================================================== */

    var layer = heroSection.querySelector('.hero-balloons');
    if (!layer) {
        layer = document.createElement('div');
        layer.className = 'hero-balloons';
        layer.setAttribute('aria-hidden', 'true');
        heroSection.insertBefore(layer, heroSection.firstChild);
    }

    /* Kunin ang mga party image URL mula sa template (data-img-0..N) */
    var imgIdx = 0;
    while (layer.hasAttribute('data-img-' + imgIdx)) {
        BALLOON_IMGS.push(layer.getAttribute('data-img-' + imgIdx));
        imgIdx++;
    }

    var items = [];

    function build() {
        /* I-cancel ang mga running animations bago mag-rebuild */
        items.forEach(function (item) {
            item.el.getAnimations().forEach(function (anim) {
                anim.cancel();
            });
        });
        layer.innerHTML = '';

        items = BALLOONS.map(createBalloon);
        var frag = document.createDocumentFragment();
        items.forEach(function (item) {
            frag.appendChild(item.el);
        });
        layer.appendChild(frag);

        /* Reduced motion: static balloons lang - walang galaw, blink, fade */
        if (!reducedMotionQuery.matches) {
            startAnimations(items);
        }
    }

    /* Rebuild kapag nagbago ang breakpoint o reduced-motion setting */
    function onSettingChange() {
        build();
    }
    if (typeof reducedMotionQuery.addEventListener === 'function') {
        reducedMotionQuery.addEventListener('change', onSettingChange);
        tabletQuery.addEventListener('change', onSettingChange);
        mobileQuery.addEventListener('change', onSettingChange);
    } else if (typeof reducedMotionQuery.addListener === 'function') {
        reducedMotionQuery.addListener(onSettingChange);
        tabletQuery.addListener(onSettingChange);
        mobileQuery.addListener(onSettingChange);
    }

    build();
})();