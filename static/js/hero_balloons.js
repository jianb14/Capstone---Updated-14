/* ==========================================================================
   HERO FLOATING OBJECTS - shared public-page decorative layer
   --------------------------------------------------------------------------
   - Gumagamit ng mga party image mula sa static/images/*-float.png.
   - Data-driven: lahat ng balloon ay object sa BALLOONS config array.
   - Bawat balloon ay may apat na magkakahiwalay na animation (Web
     Animations API + CSS):
       1. FLOATING + REPOSITION (A->B->C->D waypoints, smooth interpolation)
       2. FADE IN / FADE OUT life cycle
       3. SOFT BLINK (CSS keyframes, kanya-kanyang timing)
       4. ROTATION + SCALE habang naglalakbay
   - Mouse interaction uses a separate spring wrapper so the existing floating
     paths, fades, and layout remain independent. No JS intervals.
   - Nirerespeto ang prefers-reduced-motion (static balloons).
   ========================================================================== */

(function () {
    'use strict';

    var heroSection = document.querySelector('.hero, [data-floating-hero]');
    if (!heroSection || heroSection.dataset.balloonsInitialized) return;
    heroSection.dataset.balloonsInitialized = 'true';
    var isInnerHero = heroSection.hasAttribute('data-floating-hero');
    var isAuthHero = heroSection.hasAttribute('data-floating-auth');

    var reducedMotionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    var tabletQuery = window.matchMedia('(max-width: 968px)');
    var mobileQuery = window.matchMedia('(max-width: 640px)');
    var pointerQuery = window.matchMedia('(hover: hover) and (pointer: fine)');

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
     *   mX, mY -> legacy mobile corner positions; mobile now has its own layout.
     *
     * LAYOUT RULES (para hindi magkatabi/nagpapatong at walang napuputol):
     *   - Bawat item ay may sariling "puwesto" - malayo ang mga ito sa isat isa, at maliit lang ang drift ng
     *     malalaking item.
     *   - Lahat ng item, KASAMA ang drift range nito, ay nakapasok sa hero
     *     (may margin sa gilid) para walang object na napuputol sa edge -
     *     iyon ang dating hati na nakikita sa hero.
     *   - Mobile uses eight decorations in reserved top/bottom space, with
     *     larger balloons, small accents, and a bounded drift around each slot.
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

    // Dedicated mobile composition. Positions are centers; y is the distance
    // from the top/bottom edge. The matching CSS reserves room for both rows.
    var MOBILE_BALLOONS = [
        { img: 0, size: 68, x: 16, y: 70, rot0: -4, depth: 'fg', opacity: 0.82 },
        { img: 1, size: 30, x: 40, y: 44, rot0: 5, depth: 'bg', opacity: 0.62 },
        { img: 4, size: 36, x: 63, y: 86, rot0: -5, depth: 'bg', opacity: 0.60 },
        { img: 5, size: 56, x: 87, y: 64, rot0: 4, depth: 'mg', opacity: 0.76 },
        { img: 5, size: 52, x: 13, y: 65, rot0: -4, depth: 'mg', opacity: 0.74, bottom: true },
        { img: 3, size: 38, x: 38, y: 89, rot0: 5, depth: 'bg', opacity: 0.62, bottom: true },
        { img: 1, size: 30, x: 61, y: 45, rot0: -5, depth: 'bg', opacity: 0.60, bottom: true },
        { img: 0, size: 65, x: 86, y: 64, rot0: 4, depth: 'fg', opacity: 0.78, bottom: true }
    ].map(function (cfg, index) {
        cfg.mobileLayout = true;
        cfg.tint = cfg.depth === 'bg' ? 1 : 0;
        cfg.drift = {
            dur: 26 + index * 2,
            delay: -(index * 3 + 4),
            wps: [[12, -8, 2, 1.02], [-10, 10, -2, 0.99], [8, -6, 1, 1]]
        };
        cfg.life = { mode: 'soft', dur: 28 + index * 2, delay: -index * 4 };
        return cfg;
    });

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
        var size = cfg.size;
        var positionX = px + '%';
        var positionY = py + '%';
        if (cfg.mobileLayout) {
            var width = heroSection.clientWidth;
            size *= Math.max(0.82, Math.min(1.15, width / 390));
            // Reserve room for rotation, scale and the full drift path.
            var angle = (Math.abs(cfg.rot0) + 2) * Math.PI / 180;
            var halfWidth = (size * Math.cos(angle) + size * 1.35 * Math.sin(angle)) * 0.51;
            var margin = halfWidth + 10;
            positionX = Math.max(margin, Math.min(width - margin, width * cfg.x / 100)) + 'px';
            var edgeOffset = cfg.y;
            // Keep small bottom accents above the centered inner-page scroll cue.
            if (isInnerHero && !isAuthHero && cfg.bottom && cfg.depth === 'bg') edgeOffset = cfg.img === 3 ? 122 : 115;
            positionY = cfg.bottom ? 'calc(100% - ' + edgeOffset + 'px)' : edgeOffset + 'px';
        }
        var el = document.createElement('div');
        el.className = [
            'balloon',
            'balloon--' + cfg.depth,
            cfg.blink ? 'balloon--blink' : '',
            cfg.tint > 0 ? 'hb-t' + cfg.tint : '',
            cfg.hideTablet ? 'balloon--hide-tablet' : '',
            cfg.hideMobile ? 'balloon--hide-mobile' : '',
            cfg.authEdge ? 'balloon--auth-edge' : ''
        ].filter(Boolean).join(' ');

        el.style.setProperty('--x', positionX);
        el.style.setProperty('--y', positionY);
        el.style.setProperty('--size', size + 'px');
        el.style.setProperty('--opacity', cfg.opacity);
        el.style.setProperty('--blink-dur', (cfg.blinkDur || 8) + 's');
        el.style.setProperty('--blink-delay', (cfg.blinkDelay || 0) + 's');
        el.style.setProperty('--blink-min', cfg.blinkMin != null ? cfg.blinkMin : 0.5);
        /* Static na tindig ng balloon (hiwalay sa drift rotation) */
        el.style.transform = (cfg.mobileLayout ? 'translate(-50%, -50%) ' : '') + 'rotate(' + (cfg.rot0 || 0) + 'deg)';

        var drift = document.createElement('div');
        drift.className = 'balloon-drift';

        var shape = document.createElement('div');
        shape.className = 'balloon-shape';
        shape.innerHTML = balloonVisualMarkup(cfg);

        var interaction = document.createElement('div');
        interaction.className = 'balloon-interaction';
        interaction.appendChild(shape);
        drift.appendChild(interaction);
        el.appendChild(drift);
        return { el: el, cfg: cfg, interaction: interaction, x: 0, y: 0, vx: 0, vy: 0 };
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
        if (cfg.mobileLayout) {
            // Mobile decorations stay present throughout the animation.
            return [{ opacity: o }, { opacity: o * 0.86 }, { opacity: o }];
        }
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
    var pointer = { active: false, x: 0, y: 0 };
    var interactionFrame = 0;
    var previousInteractionTime = 0;
    var heroInView = true;

    function resetInteraction() {
        window.cancelAnimationFrame(interactionFrame);
        interactionFrame = 0;
        previousInteractionTime = 0;
        pointer.active = false;
        items.forEach(function (item) {
            item.x = item.y = item.vx = item.vy = 0;
            item.interaction.style.removeProperty('transform');
        });
    }

    function canInteract() {
        return pointerQuery.matches && !reducedMotionQuery.matches &&
            !document.hidden && heroInView && heroSection.isConnected;
    }

    function animateInteraction(now) {
        interactionFrame = 0;
        if (!canInteract()) {
            resetInteraction();
            return;
        }
        var dt = previousInteractionTime ? Math.min((now - previousInteractionTime) / 1000, 0.032) : 1 / 60;
        previousInteractionTime = now;
        var heroRect = heroSection.getBoundingClientRect();
        if (pointer.y < heroRect.top || pointer.y > heroRect.bottom) pointer.active = false;
        var px = ((pointer.x - heroRect.left) / heroRect.width - 0.5) * 2;
        var py = ((pointer.y - heroRect.top) / heroRect.height - 0.5) * 2;
        // Batch geometry reads before writing transforms. Read the drift parent
        // so interaction offsets do not feed back into their own hit positions.
        var visible = items.filter(function (item) { return item.el.offsetWidth > 0; });
        var bounds = visible.map(function (item) { return item.el.firstChild.getBoundingClientRect(); });
        var settling = false;
        visible.forEach(function (item, index) {
            var rect = bounds[index];
            var depth = item.cfg.depth === 'fg' ? 1 : item.cfg.depth === 'mg' ? 0.75 : 0.45;
            var tx = 0;
            var ty = 0;
            if (pointer.active) {
                tx = px * 7 * depth;
                ty = py * 5 * depth;
                var dx = rect.left + rect.width / 2 - pointer.x;
                var dy = rect.top + rect.height * 0.4 - pointer.y;
                var distance = Math.sqrt(dx * dx + dy * dy);
                var radius = Math.max(100, Math.min(165, rect.width + 65));
                if (distance < radius) {
                    var force = Math.pow(1 - distance / radius, 1.5) * (32 + depth * 20);
                    tx += (distance > 1 ? dx / distance : (px < 0 ? -1 : 1)) * force;
                    ty += (distance > 1 ? dy / distance : -0.5) * force;
                }
                // Limit only the extra mouse displacement at the hero's edges.
                tx = Math.max(Math.min(0, heroRect.left + 6 - rect.left), Math.min(tx, Math.max(0, heroRect.right - 6 - rect.right)));
                ty = Math.max(Math.min(0, heroRect.top + 6 - rect.top), Math.min(ty, Math.max(0, heroRect.bottom - 6 - rect.bottom)));
            }
            item.vx += ((tx - item.x) * 90 - item.vx * 16) * dt;
            item.vy += ((ty - item.y) * 90 - item.vy * 16) * dt;
            item.x += item.vx * dt;
            item.y += item.vy * dt;
            if (Math.abs(item.x) + Math.abs(item.y) + Math.abs(item.vx) + Math.abs(item.vy) > 0.08) settling = true;
            item.interaction.style.transform = 'translate3d(' + item.x.toFixed(3) + 'px, ' + item.y.toFixed(3) + 'px, 0)';
        });
        if (pointer.active || settling) interactionFrame = window.requestAnimationFrame(animateInteraction);
        else resetInteraction();
    }

    heroSection.addEventListener('pointermove', function (event) {
        if (event.pointerType !== 'mouse' || !canInteract()) return;
        pointer.active = true;
        pointer.x = event.clientX;
        pointer.y = event.clientY;
        if (!interactionFrame) {
            previousInteractionTime = 0;
            interactionFrame = window.requestAnimationFrame(animateInteraction);
        }
    }, { passive: true });
    heroSection.addEventListener('pointerleave', function () { pointer.active = false; }, { passive: true });
    window.addEventListener('blur', resetInteraction);
    window.addEventListener('resize', resetInteraction, { passive: true });
    document.addEventListener('visibilitychange', function () { if (document.hidden) resetInteraction(); });
    if (typeof pointerQuery.addEventListener === 'function') pointerQuery.addEventListener('change', resetInteraction);
    else if (typeof pointerQuery.addListener === 'function') pointerQuery.addListener(resetInteraction);
    if ('IntersectionObserver' in window) {
        new IntersectionObserver(function (entries) {
            heroInView = entries[0].isIntersecting;
            if (!heroInView) resetInteraction();
        }).observe(heroSection);
    }

    function positionAuthEdges() {
        if (!isAuthHero || mobileQuery.matches) return;
        var container = heroSection.querySelector('.auth-container');
        if (!container) return;
        var content = container.getBoundingClientRect();
        var scene = heroSection.getBoundingClientRect();
        items.forEach(function (item) {
            if (!item.cfg.authEdge) return;
            var space = item.cfg.bottom ? scene.bottom - content.bottom : content.top - scene.top;
            var offset = Math.max(0, space / 2);
            var size = Math.max(12, Math.min(item.cfg.size, (space - 26) / 1.35));
            item.el.style.setProperty('--x', item.cfg.x + '%');
            item.el.style.setProperty('--y', item.cfg.bottom ? 'calc(100% - ' + offset + 'px)' : offset + 'px');
            item.el.style.setProperty('--size', size + 'px');
        });
    }

    function build() {
        resetInteraction();
        /* I-cancel ang mga running animations bago mag-rebuild */
        items.forEach(function (item) {
            item.el.getAnimations({ subtree: true }).forEach(function (anim) {
                anim.cancel();
            });
        });
        layer.innerHTML = '';

        var composition = mobileQuery.matches ? MOBILE_BALLOONS : BALLOONS;
        if (isAuthHero) {
            // Use the full home collection, arranged in the form's side lanes.
            var authSlots = [[8,14],[22,10],[17,34],[6,46],[24,52],[12,68],
                [25,76],[7,87],[19,91],[27,28],[18,56],[28,86]];
            composition = mobileQuery.matches
                ? MOBILE_BALLOONS.map(function (cfg, index) {
                    return Object.assign({}, cfg, { img: index === 6 ? 2 : cfg.img });
                })
                : BALLOONS.map(function (cfg, index) {
                    var slot = authSlots[Math.floor(index / 2)];
                    var size = Math.min(cfg.size, index < 2 ? 92 : 62);
                    return Object.assign({}, cfg, {
                        x: index % 2 ? 100 - slot[0] - 4 : slot[0],
                        y: slot[1], size: size, hideTablet: false,
                        opacity: Math.max(cfg.opacity, .6),
                        life: Object.assign({}, cfg.life, { mode: 'soft' }),
                        drift: Object.assign({}, cfg.drift, {
                            wps: cfg.drift.wps.map(function (wp) { return [wp[0] * .55, wp[1] * .55, wp[2], wp[3]]; })
                        })
                    });
                });
            if (!mobileQuery.matches) {
                composition = composition.concat([
                    { img:1, x:42, bottom:false }, { img:4, x:52, bottom:false }, { img:2, x:62, bottom:false },
                    { img:3, x:40, bottom:true }, { img:1, x:51, bottom:true }, { img:4, x:62, bottom:true }
                ].map(function (cfg, index) {
                    return Object.assign({}, cfg, { authEdge:true, mobileLayout:true,
                        y:40, size:30, depth:'bg', tint:1, opacity:.65,
                        drift:{dur:32 + index * 2, delay:-index * 4, wps:[[4,-3,2,1],[-4,3,-2,1],[2,-2,1,1]]},
                        life:{mode:'soft',dur:34 + index * 2, delay:-index * 3}
                    });
                }));
            }
        }
        items = composition.map(createBalloon);
        var frag = document.createDocumentFragment();
        var sideLayer = isAuthHero ? document.createElement('div') : null;
        if (sideLayer) { sideLayer.className = 'auth-side-decorations'; frag.appendChild(sideLayer); }
        items.forEach(function (item) {
            (sideLayer && !item.cfg.authEdge ? sideLayer : frag).appendChild(item.el);
        });
        layer.appendChild(frag);
        positionAuthEdges();

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

    var mobileResizeFrame = 0;
    window.addEventListener('resize', function () {
        if (!mobileQuery.matches && !isAuthHero) return;
        window.cancelAnimationFrame(mobileResizeFrame);
        mobileResizeFrame = window.requestAnimationFrame(function () {
            mobileResizeFrame = 0;
            if (mobileQuery.matches || isAuthHero) build();
        });
    }, { passive: true });

    build();
    if (isAuthHero && window.ResizeObserver) {
        var authContainer = heroSection.querySelector('.auth-container');
        if (authContainer) new ResizeObserver(positionAuthEdges).observe(authContainer);
    }
})();
