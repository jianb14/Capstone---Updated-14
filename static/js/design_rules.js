/* Pure quantity evaluation shared by the canvas UI and its behavior tests. */
(function (root) {
    function resolveItem(obj, catalog, uploads = {}) {
        if (obj._isArtboard || obj._isBgImage || obj._designSource === 'reference') return null;
        if (obj._designSource === 'upload' || obj._uploadId) {
            const upload = uploads[String(obj._uploadId)];
            if (!upload || obj._designSource !== 'upload' || obj._assetId || obj._uploadToken !== upload.token || obj.type !== 'image' || Number(obj._categoryId) !== Number(upload.category_id)) return null;
            try {
                const origin = root.location?.origin || 'http://localhost';
                const source = typeof obj.getSrc === 'function' ? obj.getSrc() : obj.src;
                const actual = new URL(source, origin), expected = new URL(upload.src, origin);
                if (!source || !upload.src || actual.origin !== origin || actual.href !== expected.href) return null;
            } catch (error) { return null; }
            return {...upload, type: 'image', source: 'upload'};
        }
        const asset = catalog[String(obj._assetId)];
        return asset && obj._assetToken === asset.token ? asset : null;
    }
    function visible(obj) {
        return obj.visible !== false && obj.opacity !== 0 && obj.scaleX !== 0 && obj.scaleY !== 0;
    }
    function* placements(objects) {
        for (const obj of objects) {
            if (!obj || !visible(obj) || obj._isArtboard || obj._isBgImage || obj._designSource === 'reference') continue;
            const children = typeof obj.getObjects === 'function' ? obj.getObjects() : obj._objects || obj.objects;
            if (obj.type === 'group' && Array.isArray(children) && !obj._assetId && !obj._uploadId && !obj._designSource && !obj._isColorableSVG) yield* placements(children);
            else yield obj;
        }
    }
    function balloonColors(objects, offer, catalog, uploads = {}) {
        const ids = new Set((offer?.requirements || []).filter(rule => rule.is_balloon).map(rule => Number(rule.category_id)));
        const colors = new Set();
        for (const obj of placements(objects)) {
            const item = resolveItem(obj, catalog, uploads);
            if (!item || !ids.has(Number(item.category_id))) continue;
            const values = item.source === 'upload' ? item.colors || [] : [obj._currentColor || obj.fill];
            values.forEach(value => {
                if (typeof value === 'string' && value && !['transparent', 'rgba(255, 255, 255, 0.2)'].includes(value.toLowerCase())) colors.add(value.toLowerCase());
            });
        }
        return colors.size;
    }
    function evaluate(objects, offer, catalog, uploads = {}) {
        const counts = {}, invalid = [], missing = [];
        if (!offer) return {can_book: false, rows: [], invalid_items: ['Choose an offer before booking.'], missing_requirements: []};
        const rules = new Map(offer.requirements.map(rule => [Number(rule.category_id), rule]));
        for (const obj of placements(objects)) {
            if (obj._isArtboard || obj._isBgImage || obj._designSource === 'reference') continue;
            const asset = resolveItem(obj, catalog, uploads);
            if (!asset) {
                if (obj._assetId || obj._uploadId || ['catalog', 'upload'].includes(obj._designSource) || !['custom', '', undefined, null].includes(obj._packageCategory)) invalid.push("Some items in this design are no longer recognized. Remove and add them again from the item list.");
                continue;
            }
            const rule = rules.get(Number(asset.category_id));
            if (!rule) { invalid.push(`${asset.label} is not included in this offer.`); continue; }
            if (!visible(obj)) continue;
            if (asset.type === 'i-text' && !String(obj.text || '').trim()) continue;
            if (asset.source === 'upload' && rule.is_balloon && offer.max_balloon_colors && !asset.colors?.length) {
                invalid.push('Choose the intended colors for your uploaded balloon image.');
                continue;
            }
            counts[rule.category_id] = (counts[rule.category_id] || 0) + 1;
        }
        const rows = offer.requirements.map(rule => {
            const used = counts[rule.category_id] || 0;
            const row = {...rule, used, missing: Math.max(0, rule.minimum - used), over_limit: rule.maximum !== null && used > rule.maximum};
            if (row.missing) missing.push(row);
            if (row.over_limit) invalid.push(`${rule.name}: maximum ${rule.maximum}, currently ${used}.`);
            return row;
        });
        if (offer.max_balloon_colors && balloonColors(objects, offer, catalog, uploads) > offer.max_balloon_colors) invalid.push(`Use no more than ${offer.max_balloon_colors} balloon colors.`);
        if (!offer.enabled) invalid.push('This design offer is temporarily unavailable.');
        return {rows, counts, invalid_items: [...new Set(invalid)], missing_requirements: missing, can_book: offer.enabled && rows.length > 0 && !missing.length && !invalid.length};
    }
    const api = {evaluate, resolveItem, balloonColors};
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    else root.DesignRules = api;
})(typeof window !== 'undefined' ? window : globalThis);
