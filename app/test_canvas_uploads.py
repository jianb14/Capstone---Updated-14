import io
import json
from datetime import timedelta
from tempfile import TemporaryDirectory

from PIL import Image
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from .design_validation import asset_payload, evaluate_design, offer_is_ready
from .models import CanvasAsset, CanvasCategory, DesignOffer, DesignRequirement, Package, User, UserDesign


def photo(fmt='PNG', size=(12, 6)):
    data = io.BytesIO()
    Image.new('RGBA', size, (20, 60, 120, 42)).convert('RGB' if fmt == 'JPEG' else 'RGBA').save(data, fmt)
    return SimpleUploadedFile(f'my-panel.{fmt.lower()}', data.getvalue())


def placement(upload, **changes):
    return {'type': 'image', 'src': upload['src'], '_uploadId': upload['id'],
            '_uploadToken': upload['token'], '_categoryId': upload['category_id'],
            '_designSource': 'upload', **changes}


class TemporaryCanvasStorage:
    def setUp(self):
        super().setUp()
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        storage = override_settings(PAYMENT_PROOF_ROOT=temporary.name, PAYMENT_PROOF_USE_CLOUDINARY=False)
        storage.enable()
        self.addCleanup(storage.disable)


class CanvasUploadTests(TemporaryCanvasStorage, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(username='custom-client', role='customer')
        cls.other = User.objects.create_user(username='different-client', role='customer')
        cls.category = CanvasCategory.objects.create(name='Uploaded panels')
        cls.asset = CanvasAsset.objects.create(category=cls.category, label='Catalog panel', static_path='panel.svg')
        cls.offer = DesignOffer.objects.create(kind='package', package=Package.objects.create(name='Custom offer', price=100), is_enabled=True)
        cls.rule = DesignRequirement.objects.create(offer=cls.offer, category=cls.category, required=True, minimum=1, maximum=2)

    def setUp(self):
        super().setUp()
        self.client.force_login(self.owner)

    def submit(self, **fields):
        return self.client.post('/my-designs/uploads/', {'image': photo(), 'category_id': self.category.pk,
                                'design_offer_id': self.offer.pk, **fields})

    def upload(self, **fields):
        response = self.submit(**fields)
        self.assertEqual(response.status_code, 201)
        return response.json()['upload']

    def test_owner_can_read_normalized_transparent_image(self):
        upload = self.upload(image=photo(size=(2400, 1200)))
        self.assertEqual((upload['width'], upload['height']), (2048, 1024))
        response = self.client.get(upload['src'])
        self.assertEqual(response.status_code, 200)
        decoded = Image.open(io.BytesIO(b''.join(response.streaming_content)))
        self.assertEqual(decoded.size, (2048, 1024))
        self.assertEqual(decoded.convert('RGBA').getpixel((50, 50))[3], 42)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(upload['src']).status_code, 404)
        admin = User.objects.create_user(username='canvas-admin', role='admin')
        self.client.force_login(admin)
        self.assertEqual(self.client.get(upload['src']).status_code, 404)

    def test_bad_file_color_and_foreign_library_rejected(self):
        foreign = UserDesign.objects.create(user=self.other, canvas_json='{}')
        for fields, status in [
            ({'image': SimpleUploadedFile('fake.png', b'abc')}, 400),
            ({'image': photo('GIF')}, 400),
            ({'image': SimpleUploadedFile('large.jpg', b'0' * (10 * 1024 ** 2 + 1))}, 413),
            ({'colors': '["red"]'}, 400),
            ({'design_id': foreign.pk}, 404),
        ]:
            with self.subTest(fields=list(fields)):
                self.assertEqual(self.submit(**fields).status_code, status)

    def test_visible_group_children_share_catalog_allowance(self):
        upload = self.upload()
        asset = asset_payload(self.asset)
        catalog = {'type': 'image', '_assetId': asset['id'], '_assetToken': asset['token'],
                   'src': asset['src'], '_designSource': 'catalog'}
        group = {'type': 'group', 'objects': [catalog, placement(upload)]}
        def evaluate(*items):
            return evaluate_design({'objects': list(items)}, self.offer, owner=self.owner)
        self.assertTrue(evaluate(group)['can_book'])
        self.assertEqual(evaluate(group)['counts'], {self.category.pk: 2})
        self.assertFalse(evaluate(group, placement(upload))['can_book'])
        self.assertFalse(evaluate({**group, 'opacity': 0})['can_book'])
        self.assertFalse(evaluate()['can_book'])

    def test_foreign_tampered_and_disallowed_uploads_do_not_count(self):
        upload = self.upload()
        for owner, fields in [(self.other, {}), (None, {}), (self.owner, {'src': 'https://other.invalid' + upload['src']}),
                              (self.owner, {'type': 'rect'}), (self.owner, {'_uploadToken': 'bad'}),
                              (self.owner, {'_categoryId': self.category.pk + 1})]:
            evaluated = evaluate_design({'objects': [placement(upload, **fields)]}, self.offer, owner=owner)
            self.assertFalse(evaluated['can_book'])
            self.assertTrue(evaluated['invalid_items'])
        self.rule.delete()
        result = evaluate_design({'objects': [placement(upload)]}, self.offer, owner=self.owner)
        self.assertTrue(any(self.category.name in message for message in result['invalid_items']))

    def test_custom_balloon_colors_share_the_catalog_limit(self):
        self.category.is_balloon = True
        self.category.save()
        self.offer.max_balloon_colors = 1
        self.offer.save()
        self.assertEqual(self.submit().status_code, 400)
        upload = self.upload(colors=json.dumps(['#FF0000', '#ff0000']))
        self.assertEqual(upload['colors'], ['#ff0000'])
        asset = asset_payload(self.asset)
        catalog = {'type': 'image', '_assetId': asset['id'], '_assetToken': asset['token'], 'src': asset['src']}
        for color, expected in [('#FF0000', True), ('#00ff00', False)]:
            result = evaluate_design({'objects': [placement(upload), {**catalog, '_currentColor': color}]}, self.offer, owner=self.owner)
            self.assertEqual(result['can_book'], expected)

    def test_color_edit_creates_independent_revision_without_changing_saved_photo(self):
        self.category.is_balloon = True
        self.category.save()
        self.offer.max_balloon_colors = 2
        self.offer.save()
        original = self.upload(colors='["#ff0000"]')
        saved = UserDesign.objects.create(user=self.owner, canvas_json=json.dumps({'objects': [placement(original)]}))
        saved.uploads.add(original['id'])
        from .models import CanvasUpload
        old = CanvasUpload.objects.get(pk=original['id'])
        response = self.client.post(f'/my-designs/uploads/{old.pk}/colors/', {
            'design_offer_id': self.offer.pk, 'colors': '["#00FF00", "#00ff00"]'})
        self.assertEqual(response.status_code, 201)
        revised = response.json()['upload']
        self.assertNotEqual(revised['id'], original['id'])
        self.assertEqual(revised['colors'], ['#00ff00'])
        old.refresh_from_db()
        self.assertEqual(old.colors, ['#ff0000'])
        self.assertIsNotNone(old.library_removed_at)
        new = CanvasUpload.objects.get(pk=revised['id'])
        self.assertIsNone(new.library_removed_at)
        self.assertNotEqual(new.image.name, old.image.name)
        with old.image.open('rb') as a, new.image.open('rb') as b:
            self.assertEqual(a.read(), b.read())
        self.assertEqual(list(saved.uploads.values_list('pk', flat=True)), [old.pk])
        self.assertTrue(evaluate_design({'objects': [placement(revised)]}, self.offer, owner=self.owner)['can_book'])
        same = self.client.post(f'/my-designs/uploads/{new.pk}/colors/', {
            'design_offer_id': self.offer.pk, 'colors': '["#00ff00"]'})
        self.assertEqual(same.status_code, 200)
        self.assertEqual(same.json()['upload']['id'], new.pk)

    def test_color_revision_rejects_foreign_invalid_and_excluded_photos(self):
        self.category.is_balloon = True
        self.category.save()
        original = self.upload(colors='["#ff0000"]')
        url = f'/my-designs/uploads/{original["id"]}/colors/'
        data = {'design_offer_id': self.offer.pk, 'colors': '["#ffffff"]'}
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(url, data).status_code, 404)
        self.client.force_login(self.owner)
        for colors in ('[]', '["red"]', '{}', 'bad json'):
            self.assertEqual(self.client.post(url, {**data, 'colors': colors}).status_code, 400)
        foreign = UserDesign.objects.create(user=self.other, canvas_json='{}')
        self.assertEqual(self.client.post(url, {**data, 'design_id': foreign.pk}).status_code, 404)
        self.category.is_balloon = False
        self.category.save()
        self.assertEqual(self.client.post(url, data).status_code, 400)
        self.category.is_balloon = True
        self.category.save()
        self.rule.delete()
        self.assertEqual(self.client.post(url, data).status_code, 400)

    def test_theme_decor_is_protected_and_ready_without_defaults(self):
        category = CanvasCategory.objects.filter(builtin_key='theme_decor').first()
        self.assertIsNotNone(category)
        self.assertTrue(all((category.available_package, category.available_entrance, category.available_stand)))
        self.assertEqual(self.submit(category_id=category.pk).status_code, 400)
        self.rule.category = category
        self.rule.save()
        self.assertTrue(offer_is_ready(self.offer))
        self.upload(category_id=category.pk)
        with self.assertRaises(ValidationError):
            CanvasAsset.objects.create(category=category, label='Default', static_path='dummy.svg')
        category.name = 'Changed'
        with self.assertRaises(ValidationError):
            category.save()
        self.rule.category = self.category
        self.rule.save()
        self.asset.delete()
        self.assertFalse(offer_is_ready(self.offer))

    def test_cleanup_retains_saved_and_recent_uploads(self):
        saved = UserDesign.objects.create(user=self.owner, canvas_json='{}')
        old = self.upload()
        linked = self.upload(design_id=saved.pk)
        saved.uploads.add(linked['id'])
        recent = self.upload()
        from .models import CanvasUpload
        from .canvas_uploads import purge_orphan_uploads
        CanvasUpload.objects.filter(pk__in=[old['id'], linked['id']]).update(created_at=timezone.now() - timedelta(days=2))
        CanvasUpload.objects.filter(pk__in=[old['id'], linked['id']]).update(library_removed_at=timezone.now() - timedelta(days=2))
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(purge_orphan_uploads(), 1)
        self.assertEqual(set(CanvasUpload.objects.values_list('pk', flat=True)), {linked['id'], recent['id']})
        self.assertEqual(list(saved.uploads.values_list('pk', flat=True)), [linked['id']])

    def test_upload_does_not_change_saved_library_until_save(self):
        saved = UserDesign.objects.create(user=self.owner, canvas_json='{}')
        self.upload(design_id=saved.pk)
        self.assertFalse(saved.uploads.exists())

    def test_personal_library_is_reused_in_fresh_designs_and_private(self):
        original = self.upload()
        response = self.client.get('/design/', {'design_offer_id': self.offer.pk})
        self.assertEqual(response.status_code, 200)
        self.assertIn(str(original['id']), response.context['canvas_uploads_payload'])
        self.assertIn(original['id'], response.context['canvas_upload_library_ids'])
        self.client.force_login(self.other)
        response = self.client.get('/design/', {'design_offer_id': self.offer.pk})
        self.assertNotIn(str(original['id']), response.context['canvas_uploads_payload'])

    def test_removing_library_entry_preserves_saved_reference_and_is_owner_only(self):
        original = self.upload()
        saved = UserDesign.objects.create(user=self.owner, canvas_json=json.dumps({'objects': [placement(original)]}), design_offer=self.offer)
        saved.uploads.add(original['id'])
        url = f'/my-designs/uploads/{original["id"]}/remove/'
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(url).status_code, 404)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(url).status_code, 200)
        self.assertEqual(self.client.get(original['src']).status_code, 200)
        response = self.client.get('/design/', {'id': saved.pk})
        self.assertNotIn(original['id'], response.context['canvas_upload_library_ids'])
        self.assertIn(str(original['id']), response.context['canvas_uploads_payload'])

    def test_old_visible_library_uploads_are_not_purged(self):
        from .models import CanvasUpload
        from .canvas_uploads import purge_orphan_uploads
        upload = self.upload()
        CanvasUpload.objects.filter(pk=upload['id']).update(created_at=timezone.now() - timedelta(days=10))
        self.assertEqual(purge_orphan_uploads(), 0)
        self.assertEqual(self.client.post(f'/my-designs/uploads/{upload["id"]}/remove/').status_code, 200)
        self.assertEqual(purge_orphan_uploads(), 0)

    def test_builtin_migration_stops_before_hiding_existing_defaults(self):
        import importlib
        from django.apps import apps
        from django.db import connection
        from types import SimpleNamespace
        category = CanvasCategory.objects.get(builtin_key='theme_decor')
        CanvasAsset.objects.bulk_create([CanvasAsset(category=category, label='Existing theme prop', static_path='prop.svg')])
        migration = importlib.import_module('app.migrations.0122_category_uploads')
        with self.assertRaisesRegex(RuntimeError, 'Theme Decor'):
            migration.register_theme_decor(apps, SimpleNamespace(connection=connection))
