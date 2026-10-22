/* Upgrade suggestions use catalog categories and the same quantity rules as booking. */
(function (root) {
    const rules = typeof module !== 'undefined' && module.exports ? require('./design_rules.js') : root.DesignRules;
    function isPanel(rule) {
        return !rule?.is_balloon && /(^|\s)(panels?|backdrops?)(\s|$)/.test(String(rule?.category_name || rule?.name || '').toLowerCase().replace(/[_/-]+/g, ' '));
    }
    function colors(objects, offer, catalog) {
        const balloonIds = new Set((offer?.requirements || []).filter(rule => rule.is_balloon).map(rule => Number(rule.category_id)));
        const values = new Set();
        objects.forEach(obj => {
            const asset = catalog[String(obj._assetId)];
            if (!asset || obj._isArtboard || obj._isBgImage || obj._designSource === 'reference' || !balloonIds.has(Number(asset.category_id))) return;
            if (obj.visible === false || obj.opacity === 0 || obj.scaleX === 0 || obj.scaleY === 0) return;
            const value = obj._currentColor || obj.fill;
            if (typeof value === 'string' && value && !['transparent', 'rgba(255, 255, 255, 0.2)'].includes(value.toLowerCase())) values.add(value.toLowerCase());
        });
        return values.size;
    }
    function fits(candidate, current, objects, catalog, request) {
        if (!current || current.kind !== 'package' || !candidate?.enabled || candidate.kind !== 'package' || candidate.id === current.id || Number(candidate.price) <= Number(current.price)) return false;
        if (request.type === 'panel') {
            const original = current.requirements.find(rule => Number(rule.category_id) === Number(request.categoryId));
            const target = candidate.requirements.find(rule => Number(rule.category_id) === Number(request.categoryId));
            if (!isPanel(original) || !target || (target.maximum !== null && target.maximum < request.needed)) return false;
        } else if (request.type !== 'colors') return false;
        if (request.type === 'colors' && candidate.max_balloon_colors !== null && candidate.max_balloon_colors < request.needed) return false;
        if (rules.evaluate(objects, candidate, catalog).invalid_items.length) return false;
        return candidate.max_balloon_colors === null || colors(objects, candidate, catalog) <= candidate.max_balloon_colors;
    }
    function find(offers, current, objects, catalog, request) {
        return Object.entries(offers || {}).map(([packageId, offer]) => ({packageId, ...offer}))
            .filter(offer => fits(offer, current, objects, catalog, request))
            .sort((a, b) => Number(a.price) - Number(b.price) || Number(a.id) - Number(b.id))[0] || null;
    }
    const api = {isPanel, colors, fits, find};
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    else root.DesignUpgrades = api;
})(typeof window !== 'undefined' ? window : globalThis);
