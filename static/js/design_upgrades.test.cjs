const assert = require('node:assert/strict');
const {find, fits, colors, isPanel} = require('./design_upgrades.js');
const requirements = [
    {category_id: 1, name: 'Backdrop', category_name: 'Panels', required: true, minimum: 1, maximum: 1},
    {category_id: 2, name: 'Balloons', is_balloon: true, required: true, minimum: 1, maximum: null},
    {category_id: 3, name: 'Chair', required: false, minimum: 0, maximum: 1},
];
const current = {id: 1, kind: 'package', enabled: true, price: '1000', max_balloon_colors: 2, requirements};
const next = {...current, id: 20, price: '2000', max_balloon_colors: 3, requirements: requirements.map(rule => rule.category_id === 1 ? {...rule, maximum: 2} : rule)};
const catalog = {1: {id: 1, category_id: 1, token: 'panel'}, 2: {id: 2, category_id: 2, token: 'balloon'}, 3: {id: 3, category_id: 3, token: 'chair'}};
const object = (id, extra = {}) => ({_assetId: id, _assetToken: catalog[id].token, _designSource: 'catalog', ...extra});
const panel = {type: 'panel', categoryId: 1, needed: 2};
const state = [object(1), object(1), object(2, {_currentColor: '#ff0000'}), object(3)];
const incompatible = {...next, id: 3, price: '1500', requirements: next.requirements.filter(rule => rule.category_id !== 3)};
assert.equal(find({1: current, 3: incompatible, 200: next}, current, state, catalog, panel).packageId, '200', 'skip a cheaper offer that excludes an existing item; package and offer IDs differ');
assert.equal(find({200: {...next, enabled: false}}, current, state, catalog, panel), null);
assert.equal(find({200: {...next, kind: 'entrance'}}, current, state, catalog, panel), null);
assert.equal(find({200: {...next, price: '999'}}, current, state, catalog, panel), null);
assert.equal(find({200: next}, {...current, kind: 'stand'}, state, catalog, panel), null);
assert.equal(find({200: next}, current, [object(1), object(1), object(1)], catalog, panel), null, 'recheck pending additions against all current counts');
assert.equal(find({200: {...next, requirements: next.requirements.map(rule => rule.category_id === 1 ? {...rule, maximum: null} : rule)}}, current, state, catalog, panel).id, next.id, 'unlimited destination is valid');
assert.equal(fits(next, current, state, catalog, {type: 'panel', categoryId: 3, needed: 2}), false, 'chairs never trigger upgrades');
assert.equal(isPanel({category_name: 'Chair', name: 'Panel'}), false, 'use category identity rather than the inclusion display name');
assert.equal(isPanel({name: 'Balloon panels', is_balloon: true}), false, 'balloon quantities do not trigger panel upgrades');
const colored = [object(2, {_currentColor: '#ff0000'}), object(2, {_currentColor: '#0000ff'}), object(2, {_currentColor: '#00ff00'})];
assert.equal(colors(colored, current, catalog), 3);
assert.equal(find({200: next}, current, colored, catalog, {type: 'colors', needed: 3}).id, next.id);
assert.equal(find({200: {...next, max_balloon_colors: 2}}, current, colored, catalog, {type: 'colors', needed: 3}), null);
assert.equal(colors([...colored, object(2, {_currentColor: '#abcdef', visible: false}), object(3, {_currentColor: '#abcdef'})], current, catalog), 3);
assert.equal(colors([object(2, {fill: 'rgba(255, 255, 255, 0.2)'})], current, catalog), 0);
console.log('Panel and balloon upgrade compatibility checks passed.');
