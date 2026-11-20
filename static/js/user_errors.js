/* Only deliberate, readable request feedback may cross into the interface. */
((global) => {
    'use strict';
    const publicErrors = new WeakSet();
    const technical = /failed to fetch|fetch failed|load failed|networkerror|network request failed|unexpected (?:token|end)|\b(?:syntaxerror|typeerror|referenceerror|operationalerror|integrityerror|traceback)\b|\b(?:json|csrf|session_id|message_id|request_id)\b|\b(?:database|sqlstate|sqlite|postgres|constraint failed)\b|cannot read propert|is not a function|<!doctype|<\/?(?:html|body|script)\b|huggingface|api[_ ]key|\.env\b|\bHTTP\s*\d{3}\b|server returned|request protection|system misconfiguration/i;
    const text = (value, fallback) => typeof value === 'string' && value.trim() && !technical.test(value)
        ? value.trim() : fallback;
    function create(value) {
        const error = new Error(typeof value === 'string' ? value : '');
        if (text(value, '')) publicErrors.add(error);
        return error;
    }
    function message(error, fallback) {
        if (error && publicErrors.has(error)) return text(error.message, fallback);
        if (error) console.warn('Request could not be completed:', error);
        return fallback;
    }
    global.AppErrors = Object.freeze({create, message, text});
})(globalThis);
