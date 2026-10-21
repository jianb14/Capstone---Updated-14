/* Same Cavite coverage and configurable tariff as compute_logistics_quote(). */
(function (global) {
    'use strict';
    function inRing(lat, lng, ring) {
        var inside = false;
        for (var i = 0, j = ring.length - 1; i < ring.length; j = i++) {
            var x1 = ring[j][0], y1 = ring[j][1], x2 = ring[i][0], y2 = ring[i][1];
            var cross = (lng - x1) * (y2 - y1) - (lat - y1) * (x2 - x1);
            if (Math.abs(cross) < 1e-12 && lng >= Math.min(x1, x2) && lng <= Math.max(x1, x2)
                && lat >= Math.min(y1, y2) && lat <= Math.max(y1, y2)) return true;
            if ((y1 > lat) !== (y2 > lat) && lng < (x2 - x1) * (lat - y1) / (y2 - y1) + x1) inside = !inside;
        }
        return inside;
    }
    function inCavite(lat, lng, geometry) {
        var polygons = geometry.type === 'MultiPolygon' ? geometry.coordinates : [geometry.coordinates];
        return polygons.some(function (polygon) {
            return inRing(lat, lng, polygon[0]) && !polygon.slice(1).some(function (hole) { return inRing(lat, lng, hole); });
        });
    }
    function quote(config, lat, lng, geometry) {
        var out = { distanceKm: null, extra: 0, total: config.base, capped: false, inCavite: null, configured: false };
        if (!Number.isFinite(lat) || !Number.isFinite(lng)) return out;
        out.inCavite = inCavite(lat, lng, geometry);
        if (!Number.isFinite(config.shopLat) || !Number.isFinite(config.shopLng)) {
            out.configured = out.inCavite;
            return out;
        }
        var rad = Math.PI / 180;
        var a = Math.sin((lat - config.shopLat) * rad / 2) ** 2
            + Math.cos(config.shopLat * rad) * Math.cos(lat * rad) * Math.sin((lng - config.shopLng) * rad / 2) ** 2;
        a = Math.max(0, Math.min(1, a));
        var km = 6371.0088 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
        out.distanceKm = Math.round(km * 100) / 100;
        out.configured = true;
        if (!out.inCavite) out.extra = Math.max(1, Math.ceil(km - config.freeRadius)) * config.perKm;
        out.total = config.base + out.extra;
        if (config.maxCap > 0 && out.total > config.maxCap) {
            out.capped = true;
            out.extra = Math.max(0, config.maxCap - config.base);
            out.total = config.base + out.extra;
        }
        return out;
    }
    function describeQuote(config, result) {
        var money = function (value) { return '₱' + Number(value).toLocaleString('en-PH', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); };
        if (result.overridden) return 'Logistics fee: ' + money(result.total) + ' · Confirmed by our team.';
        if (!result.configured) return 'Choose your venue or pin its exact location to calculate logistics.';
        var note;
        if (result.extra > 0) {
            note = 'Logistics fee: ' + money(result.total) + ' · ' + money(config.base) + ' base + '
                + money(result.extra) + ' outside-Cavite distance fee.';
        } else if (result.inCavite) {
            note = 'Logistics fee: ' + money(result.total) + ' · Within Cavite, base fee only.';
        } else {
            note = 'Logistics fee: ' + money(result.total) + ' · ' + money(config.base) + ' base; no additional distance fee.';
        }
        return note + (result.capped ? ' Maximum logistics fee applied.' : '');
    }
    global.BookingLogistics = { quote: quote, inCavite: inCavite, describeQuote: describeQuote };
})(window);
