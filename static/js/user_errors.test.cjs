const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function api() {
    const context = vm.createContext({console: {warn() {}}});
    vm.runInContext(fs.readFileSync(__dirname + '/user_errors.js', 'utf8'), context);
    return context.AppErrors;
}

test('unexpected exceptions use the action-specific fallback', () => {
    const errors = api();
    const fallback = "We couldn't load your booking. Please try again.";
    for (const error of [new TypeError('Failed to fetch'), new SyntaxError('Unexpected token <'),
        new Error('database is locked'), new Error('Cannot read properties of undefined'), null]) {
        assert.equal(errors.message(error, fallback), fallback);
    }
});

test('deliberate readable field, permission and session errors are retained', () => {
    const errors = api();
    for (const message of ['Passwords do not match.', 'Choose your event date.',
        'Your session has ended. Sign in again to continue.',
        "You don't have permission to change this booking.",
        'The amount for your selected payment option is PHP 1,500.00.']) {
        assert.equal(errors.message(errors.create(message), 'Fallback'), message);
    }
});

test('technical server messages never become trusted user errors', () => {
    const errors = api();
    const fallback = "We couldn't confirm your submission. Check My Concerns before trying again.";
    for (const message of ['Failed to fetch', 'Load failed', 'NetworkError when attempting to fetch resource.',
        'Unexpected end of JSON input', 'Unexpected token < in JSON at position 0',
        'SyntaxError: invalid syntax', 'TypeError: x is not a function',
        'OperationalError: database is locked', 'UNIQUE constraint failed: app_user.email',
        '<!doctype html><html>Internal Server Error</html>', 'HUGGINGFACE_API_KEY is missing in .env',
        'Invalid JSON body', 'session_id required', 'message_id required',
        'The server returned an incomplete response.', 'Request protection is temporarily unavailable.',
        'HTTP 500', 'Traceback (most recent call last):', null, {message: 'Failed to fetch'}]) {
        assert.equal(errors.message(errors.create(message), fallback), fallback, String(message));
        assert.equal(errors.text(message, fallback), fallback, String(message));
    }
});

test('server validation text is trimmed and preserves useful punctuation', () => {
    const errors = api();
    assert.equal(errors.text('  Each image must be 5MB or smaller.  ', 'Fallback'), 'Each image must be 5MB or smaller.');
    assert.equal(errors.text('', 'Fallback'), 'Fallback');
    assert.equal(errors.message(new Error('Passwords do not match.'), 'Fallback'), 'Fallback');
});
