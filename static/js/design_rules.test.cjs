const assert = require('node:assert/strict');
const {evaluate} = require('./design_rules.js');
const offer = {enabled: true, requirements: [
    {category_id: 1, name: 'Panels', required: true, minimum: 2, maximum: 3},
    {category_id: 2, name: 'Balloons', is_balloon: true, required: true, minimum: 1, maximum: null},
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
const uploads = {
    7: {id: 7, token: 'custom-panel', category_id: 1, label: 'Custom panel', src: '/uploads/7/image/'},
    8: {id: 8, token: 'custom-balloon', category_id: 2, label: 'Printed balloon', src: '/uploads/8/image/', colors: ['#ff0000', '#0000ff']},
    9: {id: 9, token: 'custom-theme', category_id: 4, label: 'Themed ball', src: '/uploads/9/image/'},
};
const custom = (id, extra = {}) => ({type: 'image', src: uploads[id].src, _categoryId: uploads[id].category_id, _uploadId: id, _uploadToken: uploads[id].token, _designSource: 'upload', ...extra});
const mixed = objects => evaluate(objects, offer, catalog, uploads);
assert.equal(mixed([panel, custom(7, {src: undefined, getSrc: () => uploads[7].src}), balloon]).can_book, true, 'live Fabric images expose their source through getSrc');
assert.equal(mixed([panel, custom(7, {src: '/stale/image/', getSrc: () => uploads[7].src}), balloon]).can_book, true, 'the current image element wins over a stale serialized source');
assert.equal(mixed([panel, custom(7, {getSrc: () => 'https://foreign.invalid/uploads/7/image/'}), balloon]).can_book, false, 'getSrc cannot bless foreign image pixels');
assert.equal(mixed([panel, custom(7), balloon]).can_book, true, 'custom and catalog placements share an allowance');
assert.equal(mixed([{type: 'group', objects: [panel, custom(7)]}, balloon]).can_book, true, 'grouped placements retain individual identities');
assert.equal(mixed([{type: 'group', getObjects: () => [panel, custom(7)]}, balloon]).can_book, true, 'live Fabric groups count like serialized groups');
assert.equal(mixed([panel, custom(7), custom(7), custom(7), balloon]).rows[0].over_limit, true, 'copies cannot bypass the shared maximum');
assert.equal(mixed([panel, custom(7, {_categoryId: 2}), balloon]).can_book, false, 'a forged category cannot count');
assert.equal(mixed([panel, custom(7, {src: 'https://foreign.invalid/uploads/7/image/'}), balloon]).can_book, false, 'a token cannot count different pixels');
assert.equal(mixed([panel, custom(7, {_assetId: 1}), balloon]).can_book, false, 'mixed catalog and upload identity is rejected');
assert.equal(mixed([panel, custom(7, {_uploadToken: 'forged'}), balloon]).can_book, false);
assert.equal(mixed([panel, custom(7, {visible: false}), balloon]).rows[0].used, 1);
assert.equal(mixed([panel, custom(7), balloon, custom(9)]).can_book, false, 'switching to an offer without Theme Decor flags the existing item');
assert.equal(evaluate([panel, custom(7), balloon], offer, catalog, {}).can_book, false, 'an unknown upload cannot supply a required item');
assert.equal(evaluate([panel, custom(7), custom(8)], {...offer, max_balloon_colors: 1}, catalog, uploads).can_book, false, 'declared upload colors respect the existing color limit');
assert.equal(evaluate([panel, custom(7), custom(8)], {...offer, max_balloon_colors: 2}, catalog, uploads).can_book, true);
assert.equal(evaluate([panel, custom(7), custom(8)], {...offer, max_balloon_colors: 2}, catalog, {...uploads, 8: {...uploads[8], colors: []}}).can_book, false, 'limited balloon uploads need a color declaration');
console.log('Design rule behavior checks passed.');
