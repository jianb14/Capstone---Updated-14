(function (root) {
    'use strict';
    function allows(selection, capabilities) {
        const configured = String(selection || '').split('+').map(part => part
            .replace(/\s*\((add-on|additional|solo)\)\s*$/i, '').replace(/\s+/g, ' ').trim().toLowerCase())
            .filter(key => Object.prototype.hasOwnProperty.call(capabilities, key));
        return configured.length ? configured.some(key => capabilities[key]) : true;
    }
    const rules = { allows };
    if (typeof module === 'object' && module.exports) module.exports = rules;
    else root.BookingThemeRules = rules;
})(typeof window === 'undefined' ? globalThis : window);
