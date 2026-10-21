/* ============================================================================
 * Booking Location Map (booking forms and Site Settings, vanilla JS)
 * ---------------------------------------------------------------------------- 
 * Leaflet + Esri tiles + cached, same-origin Photon geocoding. Hiwalay na file para
 * madeploy nang hiwalay sa 2000+ line inline script ng booking page.
 *
 * Graceful degradation: ang text location (event_location) ay MANANATILING
 * required at bine-validate nang hiwalay — kahit mag-fail ang Leaflet CDN o
 * ang place lookup, puwedeng mag-pin nang direkta sa mapa.
 *
 * Public API (window.BookingLocationMap):
 *   .init(opts)        → bubuo ng editable map sa booking/create + edit forms
 *   .initReadOnly(opts)→ static pin para sa detail/admin view templates
 *   .collapse()        → isasara ang naka-fullscreen na read-only map
 *
 * opts (editable):
 *   {
 *     mapId, latId, lngId,            // DOM ids (lat/lng = hidden inputs)
 *     searchId, suggestionsId,        // search input + dropdown container
 *     useLocationId,                  // "Use my location" button
 *     statusId,                       // optional status/hint <small> element
 *     landmarkId,                     // optional landmark text input
 *     addressId,                      // text location input (reverse geocode target)
 *     initialLat, initialLng          // optional prefill (edit mode)
 *   }
 * ========================================================================== */
(function (global) {
    'use strict';

    var SEARCH_URL = '/booking/places/search/';
    // 📍 Smart-required pin state — tinatanong ng booking/edit forms.
    var mapReady = false;
    var REVERSE_URL = '/booking/places/reverse/';
    var SEARCH_DEBOUNCE_MS = 450;
    var PH_DEFAULT = { lat: 14.5995, lng: 120.9842, zoom: 11 }; // Metro Manila

    /* Tile provider: Esri World Street Map (corporate CDN, libre, walang API
       key, hindi nagba-block ng localhost/dev tulad ng
       tile.openstreetmap.org volunteer servers na nag-403 "Access blocked"
       (osm.wiki/Blocked) — at hindi tulad ng CARTO na nagre-require na ng
       API key kahit free tier. Fallback = OSM France HOT (libre, walang key).
       Ang Photon place lookup ay magkaibang service — hindi
       aapektuhan. */
    var TILE_URL = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}';
    var TILE_OPTIONS = {
        maxZoom: 19,
        // Short-form credit (ToS-compliant, hindi full paragraph) + prefix
        // disabled sa map init para hindi madoble ang "Leaflet" text.
        attribution: 'Tiles &copy; Esri &mdash; Source: Esri, TomTom, Garmin, FAO, NOAA, USGS'
    };
    var FALLBACK_TILE_URL = 'https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png';
    var FALLBACK_TILE_OPTIONS = {
        maxZoom: 19,
        subdomains: 'abc',
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, Tiles style by <a href="https://www.hotosm.org/" target="_blank">Humanitarian OpenStreetMap Team</a> hosted by <a href="https://openstreetmap.fr/" target="_blank">OpenStreetMap France</a>'
    };

    function roundCoord(value) {
        var num = parseFloat(value);
        return isNaN(num) ? null : Math.round(num * 1000000) / 1000000;
    }

    /* 📍 Smart-required pin state — may pin kapag may laman ang hidden lat/lng.
       NASA MODULE SCOPE ito (hindi sa loob ng init) dahil expose ito rin sa
       public API (window.BookingLocationMap.hasPin) — kung nasa loob ng init,
       ReferenceError ang mahahabol pag-load ng script at hindi na gagana yung
       buong mapa (search, "use my location", at mga button).
       Args: (latEl, lngEl) — dalawang input element o raw string values. */
    function hasPin(latEl, lngEl) {
        var latVal = (latEl && latEl.value !== undefined) ? latEl.value : latEl;
        var lngVal = (lngEl && lngEl.value !== undefined) ? lngEl.value : lngEl;
        var latOk = latVal !== null && latVal !== undefined && String(latVal).trim() !== '';
        var lngOk = lngVal !== null && lngVal !== undefined && String(lngVal).trim() !== '';
        return !!(latOk && lngOk && Number.isFinite(Number(latVal)) && Number.isFinite(Number(lngVal))
            && Math.abs(Number(latVal)) <= 90 && Math.abs(Number(lngVal)) <= 180);
    }

    function setStatus(statusEl, message, isError) {
        if (!statusEl) return;
        statusEl.textContent = message || '';
        statusEl.style.display = message ? 'block' : 'none';
        statusEl.classList.toggle('is-error', !!isError);
    }

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text == null ? '' : String(text);
        return div.innerHTML;
    }

    /* -------------------------------------------------------------------------
     * Editable map (create booking Step 3 + customer edit modal)
     * ---------------------------------------------------------------------- */
    function init(opts) {
        if (!opts || !opts.mapId) return null;
        if (typeof global.L === 'undefined') {
            // Leaflet CDN failed → huwag sirain ang form; text input na lang.
            mapReady = false;
            var rawMap = document.getElementById(opts.mapId);
            if (rawMap) rawMap.style.display = 'none';
            return null;
        }

        var mapEl = document.getElementById(opts.mapId);
        var latInput = opts.latId ? document.getElementById(opts.latId) : null;
        var lngInput = opts.lngId ? document.getElementById(opts.lngId) : null;
        var searchInput = opts.searchId ? document.getElementById(opts.searchId) : null;
        var suggestionsEl = opts.suggestionsId ? document.getElementById(opts.suggestionsId) : null;
        var useLocationBtn = opts.useLocationId ? document.getElementById(opts.useLocationId) : null;
        var statusEl = opts.statusId ? document.getElementById(opts.statusId) : null;
        // 📍 Optional callback kapag nagbago ang pin (booking page: refresh quote + clear error).
        var onPinChange = (opts && typeof opts.onPinChange === 'function') ? opts.onPinChange : null;
        function notifyPinChange() {
            if (onPinChange) { try { onPinChange(); } catch (e) { /* noop */ } }
        }
        var addressInput = document.getElementById(opts.addressId || 'event_location');
        var activeSearchInput = searchInput || addressInput;
        var applyingAddress = false;
        var searchSeq = 0;
        var searchTimer = null;
        var searchController = null;
        var reverseRequestToken = 0;
        if (!mapEl) return null;

        var startLat = roundCoord(opts.initialLat);
        var startLng = roundCoord(opts.initialLng);
        if (startLat === null || startLng === null) {
            startLat = PH_DEFAULT.lat;
            startLng = PH_DEFAULT.lng;
        }

        var map = global.L.map(mapEl, { scrollWheelZoom: false, attributionControl: true }).setView(
            [startLat, startLng],
            (startLat === PH_DEFAULT.lat && startLng === PH_DEFAULT.lng) ? PH_DEFAULT.zoom : 15
        );
        // Extra "Leaflet" prefix text tanggalin (attribution ng provider, buhay).
        try { map.attributionControl.setPrefix(false); } catch (e) { /* noop */ }
        mapReady = true;

        var editableTiles = global.L.tileLayer(TILE_URL, TILE_OPTIONS);
        /* Fallback: kung bumagsak man ang Esri, awtomatikong lumipat sa
           OSM France HOT (libre rin, walang key) — buong layer ang pinapalitan
           (hindi lang URL) para sumama ang tamang attribution. */
        editableTiles.on('tileerror', function onEditableTileError() {
            editableTiles.off('tileerror', onEditableTileError);
            try { map.removeLayer(editableTiles); } catch (e) { /* noop */ }
            editableTiles = global.L.tileLayer(FALLBACK_TILE_URL, FALLBACK_TILE_OPTIONS).addTo(map);
        });
        editableTiles.addTo(map);

        var hasSavedPin = (roundCoord(opts.initialLat) !== null && roundCoord(opts.initialLng) !== null);
        // Custom dot — pareho ng read-only map (walang default flag/image pin).
        var editableIcon = global.L.divIcon({
            className: 'booking-map-div-icon',
            html: '<span class="map-pin-dot"></span>',
            iconSize: [22, 22],
            iconAnchor: [11, 11]
        });
        var marker = global.L.marker([startLat, startLng], { draggable: true, opacity: hasSavedPin ? 1 : 0, icon: editableIcon })
            .addTo(map);

        function writeCoords(lat, lng) {
            // Write both coordinates before notifying any quote/validation listener.
            if (latInput) latInput.value = lat == null ? '' : lat;
            if (lngInput) lngInput.value = lng == null ? '' : lng;
            if (latInput) {
                try { latInput.dispatchEvent(new Event('change', { bubbles: true })); } catch (e) { /* noop */ }
            }
            if (lngInput) {
                try { lngInput.dispatchEvent(new Event('change', { bubbles: true })); } catch (e) { /* noop */ }
            }
        }

        function placePin(lat, lng, zoom, reverseGeocode) {
            var cleanLat = roundCoord(lat);
            var cleanLng = roundCoord(lng);
            if (cleanLat === null || cleanLng === null || Math.abs(cleanLat) > 90 || Math.abs(cleanLng) > 180) return;
            cancelSearch();
            reverseRequestToken++;
            marker.setLatLng([cleanLat, cleanLng]);
            marker.setOpacity(1);
            map.setView([cleanLat, cleanLng], zoom || map.getZoom() || 15);
            writeCoords(cleanLat, cleanLng);
            notifyPinChange();
            if (reverseGeocode) reverseGeocodeIntoFields(cleanLat, cleanLng);
        }

        /* Reverse geocode: pin → address field (kapag walang laman pa o
           galing mismo sa pin drag). Landmark field ay HINDI ina-overwrite —
           manual yun ng customer. */
        function applyAddress(value) {
            applyingAddress = true;
            [addressInput, searchInput].forEach(function (field, idx, fields) {
                if (!field || fields.indexOf(field) !== idx) return;
                field.value = value;
                field.dispatchEvent(new Event('input', { bubbles: true }));
                field.dispatchEvent(new Event('change', { bubbles: true }));
            });
            applyingAddress = false;
        }
        function reverseGeocodeIntoFields(lat, lng) {
            var token = ++reverseRequestToken;
            setStatus(statusEl, 'Finding address for the pinned location…', false);
            var params = new URLSearchParams({ lat: lat, lng: lng });
            fetch((opts.reverseUrl || REVERSE_URL) + '?' + params.toString())
                .then(function (res) { return res.ok ? res.json() : Promise.reject(new Error('reverse failed')); })
                .then(function (rows) {
                    if (token !== reverseRequestToken) return; // stale response
                    var hit = rows && rows.results && rows.results[0];
                    if (!hit || !hit.display_name) {
                        setStatus(statusEl, 'Pin saved, but no address found. Please type the venue address.', true);
                        return;
                    }
                    applyAddress(hit.display_name);
                    setStatus(statusEl, 'Location pinned. Drag the pin to adjust if needed. Search another place or drop a new pin to change it.', false);
                })
                .catch(function () {
                    if (token !== reverseRequestToken) return;
                    setStatus(statusEl, 'Pin saved. Address lookup is unavailable right now.', true);
                });
        }

        marker.on('dragend', function () {
            var pos = marker.getLatLng();
            placePin(pos.lat, pos.lng, map.getZoom(), true);
        });

        map.on('click', function (e) {
            placePin(e.latlng.lat, e.latlng.lng, map.getZoom(), true);
        });

        /* --- Address search (debounced) + suggestions ---------------------- */
        function hideSuggestions() {
            if (suggestionsEl) { suggestionsEl.hidden = true; suggestionsEl.innerHTML = ''; }
            [addressInput, searchInput].forEach(function (field) {
                if (field) field.setAttribute('aria-expanded', 'false');
            });
        }
        function cancelSearch() {
            clearTimeout(searchTimer);
            searchSeq++;
            if (searchController) searchController.abort();
            hideSuggestions();
        }
        function clearPin() {
            reverseRequestToken++;
            marker.setOpacity(0);
            writeCoords(null, null);
            notifyPinChange();
        }
        function renderSuggestions(results) {
            if (!suggestionsEl) return;
            if (activeSearchInput && activeSearchInput.parentElement) {
                activeSearchInput.parentElement.appendChild(suggestionsEl);
                activeSearchInput.setAttribute('aria-expanded', 'true');
            }
            if (!results || results.length === 0) {
                suggestionsEl.innerHTML = '<div class="map-suggestion-empty" role="status">No matching place found. Add the city or pin the venue on the map.</div>';
                suggestionsEl.hidden = false;
                return;
            }
            suggestionsEl.innerHTML = results.map(function (row, idx) {
                return '<button type="button" role="option" class="map-suggestion-item" data-idx="' + idx + '">' +
                    escapeHtml(row.display_name) + '</button>';
            }).join('');
            suggestionsEl.hidden = false;

            suggestionsEl.querySelectorAll('.map-suggestion-item').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    var picked = results[parseInt(btn.getAttribute('data-idx'), 10)];
                    if (!picked) return;
                    applyAddress(picked.display_name);
                    placePin(parseFloat(picked.lat), parseFloat(picked.lon), 16, false);
                    setStatus(statusEl, 'Location pinned from search. Drag the pin to adjust — exact pin is required for the logistics fee.', false);
                });
            });
        }

        function runSearch(query) {
            var q = (query || '').trim();
            if (q.length < 3) {
                hideSuggestions();
                return;
            }
            var seq = ++searchSeq;
            if (searchController) searchController.abort();
            searchController = new AbortController();
            setStatus(statusEl, 'Searching places…', false);
            var params = new URLSearchParams({ q: q });
            fetch((opts.searchUrl || SEARCH_URL) + '?' + params.toString(), { signal: searchController.signal })
                .then(function (res) { return res.ok ? res.json() : Promise.reject(new Error('search failed')); })
                .then(function (rows) {
                    if (seq !== searchSeq) return; // outdated request
                    setStatus(statusEl, '', false);
                    renderSuggestions(rows.results || []);
                })
                .catch(function () {
                    if (seq !== searchSeq) return;
                    if (suggestionsEl) {
                        renderSuggestions([]);
                        suggestionsEl.querySelector('.map-suggestion-empty').textContent = 'Search unavailable. Pin the venue on the map or try again.';
                    }
                    setStatus(statusEl, 'Place search is unavailable right now. You can drop a pin on the map instead.', true);
                });
        }

        var searchFields = [addressInput, searchInput].filter(function (field, idx, fields) {
            return field && fields.indexOf(field) === idx;
        });
        searchFields.forEach(function (field) {
            field.setAttribute('role', 'combobox');
            field.setAttribute('aria-autocomplete', 'list');
            field.setAttribute('aria-expanded', 'false');
            if (suggestionsEl) {
                field.setAttribute('aria-controls', suggestionsEl.id);
                suggestionsEl.setAttribute('role', 'listbox');
            }
            field.parentElement.classList.add('location-address-wrap');
            field.addEventListener('input', function () {
                if (applyingAddress) return;
                cancelSearch();
                activeSearchInput = field;
                clearPin();
                if (field.value.trim().length < 3) {
                    setStatus(statusEl, 'Type at least 3 characters, then choose a suggested place or pin the venue.', false);
                    return;
                }
                setStatus(statusEl, 'Searching places…', false);
                searchTimer = setTimeout(function () { runSearch(field.value); }, SEARCH_DEBOUNCE_MS);
            });
            field.addEventListener('keydown', function (e) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    clearTimeout(searchTimer);
                    activeSearchInput = field;
                    runSearch(field.value);
                } else if (e.key === 'ArrowDown' && suggestionsEl && !suggestionsEl.hidden) {
                    e.preventDefault();
                    var first = suggestionsEl.querySelector('button');
                    if (first) first.focus();
                } else if (e.key === 'Escape') {
                    cancelSearch();
                }
            });
        });
        if (suggestionsEl) {
            suggestionsEl.addEventListener('keydown', function (e) {
                var buttons = Array.prototype.slice.call(suggestionsEl.querySelectorAll('button'));
                var idx = buttons.indexOf(document.activeElement);
                if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                    e.preventDefault();
                    if (buttons.length) buttons[(idx + (e.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length].focus();
                } else if (e.key === 'Escape') {
                    cancelSearch();
                    if (activeSearchInput) activeSearchInput.focus();
                }
            });
        }
        document.addEventListener('click', function (e) {
            if (!suggestionsEl) return;
            if (suggestionsEl.contains(e.target)) return;
            if (searchFields.indexOf(e.target) !== -1) return;
            cancelSearch();
        });

        /* --- "Use my location" ------------------------------------------- */
        if (useLocationBtn) {
            useLocationBtn.addEventListener('click', function () {
                if (!navigator.geolocation) {
                    setStatus(statusEl, 'Geolocation is not supported by this browser.', true);
                    return;
                }
                setStatus(statusEl, 'Finding your current location…', false);
                cancelSearch();
                var locationToken = ++reverseRequestToken;
                useLocationBtn.disabled = true;
                navigator.geolocation.getCurrentPosition(
                    function (pos) {
                        useLocationBtn.disabled = false;
                        if (locationToken !== reverseRequestToken) return;
                        placePin(pos.coords.latitude, pos.coords.longitude, 16, true);
                    },
                    function () {
                        useLocationBtn.disabled = false;
                        setStatus(statusEl, 'Could not get your location. Search for a place or drop a pin instead.', true);
                    },
                    { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
                );
            });
        }

        // I-layout ulit kapag unang beses na lumitaw ang modal/tab ang resize
        setTimeout(function () { try { map.invalidateSize(); } catch (e) { /* noop */ } }, 250);
        global.addEventListener('resize', function () {
            try { map.invalidateSize(); } catch (e) { /* noop */ }
        });

        // Inedit mode na may laman: huwag nang itago ang pin
        if (hasSavedPin) writeCoords(startLat, startLng);
        if (addressInput && addressInput.form) {
            addressInput.form.addEventListener('reset', function () {
                cancelSearch();
                reverseRequestToken++;
                setTimeout(function () {
                    clearPin();
                    setStatus(statusEl, '', false);
                }, 0);
            });
        }

        return {
            map: map,
            marker: marker,
            placePin: placePin,
            clear: function () { cancelSearch(); clearPin(); },
            invalidate: function () { try { map.invalidateSize(); } catch (e) { /* noop */ } }
        };
    }

    /* -------------------------------------------------------------------------
     * Read-only mini map (booking detail, admin detail, booking modal)
     * ----------------------------------------------------------------------
     * Expandable: bawat read-only map ay may maliit na expand button na
     * nililipat ang map sa fullscreen stage (.booking-map-stage) sa <body>.
     * Hiwalay na element sa body ang stage para hindi na-aapektuhan ng
     * transformed ancestors (hal. .modal-card) o stacking contexts ng page.
     * Nabubuksan din ito gamit ang Esc at ang click sa dark backdrop.
     * Opt-out sa pamamagitan ng opts.expandable = false. */

    var expandedCtx = null;   // ctx na kasalukuyang naka-fullscreen
    var stageEl = null;
    var escBound = false;

    var EXPAND_ICON_SVG =
        '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">' +
        '<path d="M9 3H4v5M15 3h5v5M21 15v5h-5M3 15v5h5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>' +
        '</svg>';

    function bindStageEsc() {
        if (escBound) return;
        escBound = true;
        // Capture phase + stopPropagation: habang naka-fullscreen ang mapa,
        // ang Esc ay dapat magsara lang ng stage — hindi ng modal/page sa ilalim.
        document.addEventListener('keydown', function (e) {
            if (!expandedCtx || e.key !== 'Escape') return;
            e.preventDefault();
            e.stopPropagation();
            if (e.stopImmediatePropagation) e.stopImmediatePropagation();
            collapseMap();
        }, true);
    }

    function ensureStage() {
        if (stageEl) return stageEl;
        bindStageEsc();
        stageEl = document.createElement('div');
        stageEl.id = 'booking_map_stage';
        stageEl.className = 'booking-map-stage';
        stageEl.hidden = true;
        stageEl.innerHTML =
            '<div class="booking-map-stage-head">' +
            '<span class="booking-map-stage-title">Venue Map</span>' +
            '<button type="button" class="booking-map-stage-close" aria-label="Close full-screen map">&times;</button>' +
            '</div>' +
            '<div class="booking-map-stage-slot"></div>';
        document.body.appendChild(stageEl);
        stageEl.querySelector('.booking-map-stage-close').addEventListener('click', collapseMap);
        // Click sa dark backdrop (hindi sa mismong mapa) = close.
        stageEl.addEventListener('click', function (e) {
            if (e.target === stageEl) collapseMap();
        });
        return stageEl;
    }

    function setStageInteractivity(ctx, enabled) {
        try {
            if (enabled) {
                // Sa fullscreen: payagang i-pan/zoom para makita ang buong area.
                ctx.map.dragging.enable();
                ctx.map.scrollWheelZoom.enable();
                ctx.map.doubleClickZoom.enable();
            } else {
                // Bumalik sa read-only mini map (zoom buttons lang).
                ctx.map.dragging.disable();
                ctx.map.scrollWheelZoom.disable();
                ctx.map.doubleClickZoom.disable();
            }
        } catch (e) { /* noop */ }
    }

    function invalidateLater(ctx) {
        setTimeout(function () { try { ctx.map.invalidateSize(); } catch (e) { /* noop */ } }, 0);
        setTimeout(function () { try { ctx.map.invalidateSize(); } catch (e) { /* noop */ } }, 250);
    }

    function expandMap(ctx) {
        if (!ctx || expandedCtx === ctx) return;
        if (expandedCtx) collapseMap();
        var stage = ensureStage();
        var slot = stage.querySelector('.booking-map-stage-slot');
        var title = stage.querySelector('.booking-map-stage-title');
        slot.appendChild(ctx.mapEl);   // DOM move — kasunod ang invalidateSize
        stage.hidden = false;
        stage.classList.add('is-open');
        document.body.classList.add('booking-map-stage-open');
        expandedCtx = ctx;
        if (ctx.frame) ctx.frame.classList.add('is-expanded');
        if (title) title.textContent = ctx.title || 'Venue Map';
        setStageInteractivity(ctx, true);
        invalidateLater(ctx);
    }

    function collapseMap() {
        var ctx = expandedCtx;
        if (!ctx) return;
        expandedCtx = null;
        if (ctx.frame && ctx.mapEl.parentNode !== ctx.frame) {
            ctx.frame.appendChild(ctx.mapEl);
        }
        if (ctx.frame) ctx.frame.classList.remove('is-expanded');
        if (stageEl) {
            stageEl.classList.remove('is-open');
            stageEl.hidden = true;
        }
        document.body.classList.remove('booking-map-stage-open');
        setStageInteractivity(ctx, false);
        invalidateLater(ctx);
    }

    function attachExpandControl(ctx, opts) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'booking-map-expand-btn';
        btn.setAttribute('aria-label', 'Open map full screen');
        btn.setAttribute('title', 'Open map full screen');
        btn.innerHTML = EXPAND_ICON_SVG;
        btn.addEventListener('click', function () {
            if (expandedCtx === ctx) collapseMap();
            else expandMap(ctx);
        });
        ctx.frame.appendChild(btn);
        ctx.expandBtn = btn;
        ctx.title = opts.title || opts.label || 'Venue Map';
    }

    function initReadOnly(opts) {
        if (!opts || !opts.mapId) return null;
        if (typeof global.L === 'undefined') {
            var rawMap = document.getElementById(opts.mapId);
            if (rawMap) {
                rawMap.classList.add('booking-map-unavailable');
                rawMap.innerHTML = '<p class="map-unavailable-note">Map unavailable — see venue address above.</p>';
            }
            return null;
        }
        var mapEl = document.getElementById(opts.mapId);
        var lat = roundCoord(opts.lat);
        var lng = roundCoord(opts.lng);
        if (!mapEl || lat === null || lng === null) {
            if (mapEl) mapEl.style.display = 'none';
            return null;
        }
        // Dating naka-hide (walang pin) → ibalik kapag may laman na.
        mapEl.style.display = '';

        // Reuse: kapag nabuksan na ito dati (hal. View Booking modal na
        // paulit-ulit binubuksan), huwag uliting L.map() — mag-e-error sa
        // "Map container is already initialized". Ilipat lang ang view/marker.
        var existing = mapEl.__bookingMapCtx || null;
        if (existing) {
            try {
                existing.map.setView([lat, lng], 16);
                if (existing.marker) existing.marker.setLatLng([lat, lng]);
                existing.title = opts.title || opts.label || existing.title;
            } catch (e) { /* noop */ }
            invalidateLater(existing);
            return existing;
        }

        // I-wrap sa relative frame BAGO ang Leaflet init para hindi na
        // kailangang i-move ang initialized container (at may pinagtatapunan
        // ang expand button).
        var frame = null;
        if (opts.expandable !== false) {
            frame = document.createElement('div');
            frame.className = 'booking-map-frame';
            mapEl.parentNode.insertBefore(frame, mapEl);
            frame.appendChild(mapEl);
        }

        var map = global.L.map(mapEl, {
            scrollWheelZoom: false,
            dragging: false,
            doubleClickZoom: false,
            zoomControl: true
        }).setView([lat, lng], 16);
        // Extra "Leaflet" prefix text tanggalin (attribution ng provider, buhay).
        try { map.attributionControl.setPrefix(false); } catch (e) { /* noop */ }

        var readOnlyTiles = global.L.tileLayer(TILE_URL, TILE_OPTIONS);
        readOnlyTiles.on('tileerror', function onReadOnlyTileError() {
            readOnlyTiles.off('tileerror', onReadOnlyTileError);
            try { map.removeLayer(readOnlyTiles); } catch (e) { /* noop */ }
            readOnlyTiles = global.L.tileLayer(FALLBACK_TILE_URL, FALLBACK_TILE_OPTIONS).addTo(map);
        });
        readOnlyTiles.addTo(map);

        var icon = global.L.divIcon({
            className: 'booking-map-div-icon',
            html: '<span class="map-pin-dot" title="' + escapeHtml(opts.label || 'Event venue') + '"></span>',
            iconSize: [22, 22],
            iconAnchor: [11, 11]
        });
        var marker = global.L.marker([lat, lng], { icon: icon }).addTo(map);

        var ctx = {
            mapId: opts.mapId,
            mapEl: mapEl,
            frame: frame,
            map: map,
            marker: marker,
            title: opts.title || opts.label || 'Venue Map',
            expandBtn: null
        };
        mapEl.__bookingMapCtx = ctx;
        if (frame) attachExpandControl(ctx, opts);

        invalidateLater(ctx);
        return ctx;
    }

    global.BookingLocationMap = {
        init: init,
        initReadOnly: initReadOnly,
        // Para sa mga caller na nagbu-close ng modal (View Booking) —
        // siguraduhing hindi manatiling naka-fullscreen ang mapa.
        collapse: collapseMap,
        // 📍 Smart-required pin: tinatanong ng booking/edit forms kung buhay
        // ang map (Leaflet loaded + initialized) at kung may pin na.
        isMapReady: function () { return mapReady; },
        hasPin: hasPin
    };
})(window);

