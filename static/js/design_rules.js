/* Pure quantity evaluation shared by the canvas UI and its behavior tests. */
(function (root) {
    function evaluate(objects, offer, catalog) {
        const counts = {}, invalid = [], missing = [];
        if (!offer) return {can_book: false, rows: [], invalid_items: ['Choose an offer before booking.'], missing_requirements: []};
        const rules = new Map(offer.requirements.map(rule => [Number(rule.category_id), rule]));
        for (const obj of objects) {
            if (obj._isArtboard || obj._isBgImage || obj._designSource === 'reference') continue;
            const asset = catalog[String(obj._assetId)];
            if (!asset || obj._assetToken !== asset.token) {
                if (obj._assetId || obj._designSource === 'catalog' || !['custom', '', undefined, null].includes(obj._packageCategory)) invalid.push('Re-add unrecognized catalog items so they can be counted.');
                continue;
            }
            const rule = rules.get(Number(asset.category_id));
            if (!rule) { invalid.push(`${asset.label} is not included in this offer.`); continue; }
            if (obj.visible === false || obj.opacity === 0 || obj.scaleX === 0 || obj.scaleY === 0) continue;
            if (asset.type === 'i-text' && !String(obj.text || '').trim()) continue;
            counts[rule.category_id] = (counts[rule.category_id] || 0) + 1;
        }
        const rows = offer.requirements.map(rule => {
            const used = counts[rule.category_id] || 0;
            const row = {...rule, used, missing: Math.max(0, rule.minimum - used), over_limit: rule.maximum !== null && used > rule.maximum};
            if (row.missing) missing.push(row);
            if (row.over_limit) invalid.push(`${rule.name}: maximum ${rule.maximum}, currently ${used}.`);
            return row;
        });
        if (!offer.enabled) invalid.push('This design offer is temporarily unavailable.');
        return {rows, counts, invalid_items: [...new Set(invalid)], missing_requirements: missing, can_book: offer.enabled && rows.length > 0 && !missing.length && !invalid.length};
    }
    const api = {evaluate};
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    else root.DesignRules = api;
})(typeof window !== 'undefined' ? window : globalThis);
