"""Design library guidance, bounded metadata queries, and private card previews."""
import io
import json
from unittest.mock import patch

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from .design_validation import (EvaluationCatalog, asset_payload, design_card_status,
                                evaluate_saved_design, selection_groups)
from .models import (AddOn, AdditionalOnly, CanvasAsset, CanvasCategory, DesignOffer,
                     DesignRequirement, Package, User, UserDesign)


class DesignLibraryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='library_customer', role='customer')
        cls.other = User.objects.create_user(username='library_other', role='customer')
        category = CanvasCategory.objects.create(name='Library panels', available_entrance=True, available_stand=True)
        cls.asset = CanvasAsset.objects.create(category=category, label='Library panel', static_path='images/library-panel.svg', available_entrance=True, available_stand=True)
        cls.offers = []
        owners = [('package', 'package', Package.objects.create(name='Library package', price=5000)),
                  ('entrance', 'entrance', AddOn.objects.create(name='Library entrance', price=1000, solo_price=2000)),
                  ('stand', 'stand', AdditionalOnly.objects.create(name='Library stand', price=1500))]
        for kind, field, owner in owners:
            offer = DesignOffer.objects.create(kind=kind, is_enabled=True, **{field: owner})
            DesignRequirement.objects.create(offer=offer, category=category, required=True, minimum=2, maximum=2)
            cls.offers.append(offer)
        payload = asset_payload(cls.asset)
        obj = {'type': 'image', 'src': payload['src'], '_assetId': cls.asset.pk, '_assetToken': payload['token'], '_designSource': 'catalog'}
        cls.complete = json.dumps({'objects': [obj, obj]})
        cls.ready = UserDesign.objects.create(user=cls.user, name='Ready design', design_offer=cls.offers[0], canvas_json=cls.complete)
        cls.draft = UserDesign.objects.create(user=cls.user, name='Draft design', design_offer=cls.offers[0], canvas_json='{"objects": []}')

    def setUp(self):
        self.client.force_login(self.user)
        cache.clear()

    def test_shared_catalog_matches_authoritative_evaluator_without_per_card_queries(self):
        designs = [self.ready, self.draft]
        expected = [evaluate_saved_design(design) for design in designs]
        with self.assertNumQueries(6):  # offers, rules, inclusions, assets for each of 3 types
            catalog = EvaluationCatalog(designs)
            actual = [evaluate_saved_design(design, catalog) for design in designs * 4]
            groups = selection_groups(catalog)
        self.assertEqual(actual, expected * 4)
        self.assertEqual([len(group['offers']) for group in groups], [1, 1, 1])
        self.assertEqual(groups[1]['offers'][0].price, 2000)
        # A new request must see admin changes; eligibility is never globally cached.
        self.offers[0].requirements.update(minimum=1, maximum=1)
        fresh = EvaluationCatalog(designs)
        self.assertFalse(evaluate_saved_design(self.ready, fresh)['can_book'])

    def test_card_copy_and_links_distinguish_ready_from_draft(self):
        response = self.client.get(reverse('my_designs'))
        self.assertContains(response, 'Add 2 more: Library panels')
        self.assertContains(response, 'Required items complete. Your design is ready to book.')
        self.assertNotContains(response, 'Package: Library package')
        self.assertContains(response, reverse('booking_page') + f'?design_id={self.ready.pk}')
        self.assertNotContains(response, reverse('booking_page') + f'?design_id={self.draft.pk}')
        self.assertContains(response, 'Continue Editing')

    def test_admin_style_page_sizes_remain_bounded_and_preserve_filters(self):
        for index in range(9):
            UserDesign.objects.create(user=self.user, name=f'Paged design {index:02}', canvas_json='{"objects": []}')
        for size, expected in (('4',4), ('8',8), ('1000',8)):
            with self.subTest(size=size):
                response = self.client.get(reverse('my_designs'), {'q':'Paged design', 'sort':'name', 'per_page':size})
                self.assertEqual(response.context['designs'].paginator.per_page, expected)
                self.assertEqual(len(response.context['designs']), expected)
                self.assertEqual(response.context['designs'].paginator.count, 9)
                self.assertContains(response, 'aria-label="Rows per page"')
                self.assertContains(response, 'sort=name')
                self.assertContains(response, 'q=Paged+design')
        response = self.client.get(reverse('my_designs'), {'q':'Paged design', 'sort':'name', 'per_page':4, 'page':2})
        self.assertEqual(response.context['designs'].start_index(), 5)
        self.assertEqual(response.context['designs'][0].name, 'Paged design 04')

    def test_search_matches_design_and_starting_point_names_without_other_users(self):
        legacy = UserDesign.objects.create(user=self.user, name='Legacy setup', base_package=self.offers[0].package, canvas_json='{}')
        entrance = UserDesign.objects.create(user=self.user, name='Doorway setup', design_offer=self.offers[1], canvas_json='{}')
        stand = UserDesign.objects.create(user=self.user, name='Greeting setup', design_offer=self.offers[2], canvas_json='{}')
        UserDesign.objects.create(user=self.other, name='Private setup', design_offer=self.offers[0], canvas_json='{}')
        for query, expected in (
            ('Library package', {self.ready.pk,self.draft.pk,legacy.pk}),
            ('Library entrance', {entrance.pk}), ('welcome stand', {stand.pk}),
            ('Ready package', {self.ready.pk}), ('DOORWAY', {entrance.pk}), ('not-found', set()),
        ):
            response = self.client.get(reverse('my_designs'), {'q':query})
            self.assertEqual({item.pk for item in response.context['designs']}, expected, query)

    def test_empty_states_offer_relevant_actions(self):
        response = self.client.get(reverse('my_designs'), {'q':'not-found'})
        self.assertContains(response, 'No matching designs')
        self.assertContains(response, 'data-clear-design-search')
        self.client.force_login(self.other)
        response = self.client.get(reverse('my_designs'))
        self.assertContains(response, 'Your designs start here')
        self.assertContains(response, 'Create a design')

    def test_card_hides_raw_validator_messages_and_bounds_guidance(self):
        result = evaluate_saved_design(self.draft)
        result['invalid_items'] = ['Internal catalog metadata detail']
        result['missing_requirements'] *= 4
        status = design_card_status(result)
        self.assertEqual(len(status['items']), 2)
        self.assertTrue(status['more'])
        self.assertNotIn('metadata', str(status))

    def add_preview(self):
        output = io.BytesIO()
        Image.new('RGB', (3840, 2160), '#eeeeee').save(output, 'PNG')
        self.ready.thumbnail.save('library-large.png', ContentFile(output.getvalue()))
        return reverse('user_design_preview', args=[self.ready.pk])

    def test_preview_is_small_cached_and_preserves_original(self):
        url = self.add_preview()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/webp')
        self.assertIn('private', response['Cache-Control'])
        with Image.open(io.BytesIO(response.content)) as image:
            self.assertEqual(image.size, (640, 360))
        with self.ready.thumbnail.open('rb') as source, Image.open(source) as image:
            self.assertEqual(image.size, (3840, 2160))
        with patch.object(self.ready.thumbnail.storage, 'open', side_effect=AssertionError('cached preview reopened original')):
            self.assertEqual(self.client.get(url).content, response.content)
            self.assertEqual(self.client.get(url, HTTP_IF_NONE_MATCH=response['ETag']).status_code, 304)
        page = self.client.get(reverse('my_designs'))
        self.assertContains(page, f'src="{url}?v=')
        self.assertContains(page, f'href="{self.ready.thumbnail.url}" download=')

    def test_previews_require_owner_and_valid_image(self):
        url = self.add_preview()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('user_design_preview', args=[self.draft.pk])).status_code, 404)
        self.ready.thumbnail.save('invalid.png', ContentFile(b'invalid image'))
        self.assertEqual(self.client.get(url).status_code, 404)
