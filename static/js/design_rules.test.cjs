const assert = require('node:assert/strict');
const {evaluate} = require('./design_rules.js');
const offer = {enabled: true, requirements: [
    {category_id: 1, name: 'Panels', required: true, minimum: 2, maximum: 3},
    {category_id: 2, name: 'Balloons', required: true, minimum: 1, maximum: null},
    {category_id: 3, name: 'Chair', required: false, minimum: 0, maximum: 1},
]};
const catalog = {1: {category_id: 1, token: 'panel'}, 2: {category_id: 2, token: 'balloon'}};
const panel = {_assetId: 1, _assetToken: 'panel', _designSource: 'catalog'};
const balloon = {_assetId: 2, _assetToken: 'balloon', _designSource: 'catalog'};
const run = objects => evaluate(objects, offer, catalog);
const initial = [panel, balloon];
assert.equal(run(initial).can_book, false);
assert.equal(run(initial).rows[0].missing, 1);
const duplicated = [...initial, {...panel}];
assert.equal(run(duplicated).can_book, true);
assert.equal(run(JSON.parse(JSON.stringify(duplicated))).can_book, true, 'save/reopen keeps identities');
assert.equal(run(initial).can_book, false, 'undo/delete restores missing state');
assert.equal(run(duplicated).can_book, true, 'redo restores completion');
assert.equal(run([panel, panel, {...balloon, _designSource: 'reference'}]).can_book, false);
assert.equal(run([panel, panel, balloon, panel, panel]).can_book, false, 'over maximum is blocked');
assert.equal(run([panel, panel, {...balloon, visible: false}]).can_book, false);
assert.equal(run([panel, panel, {...balloon, _categoryId: 1}]).rows[1].used, 1, 'category comes from catalog');
assert.equal(run([panel, panel, {...balloon, _assetToken: 'forged'}]).can_book, false);
assert.equal(evaluate(duplicated, {...offer, enabled: false}, catalog).can_book, false);
console.log('Design rule behavior checks passed.');
