"""Offer inclusions and required quantities appear before opening the editor."""
from html.parser import HTMLParser
from django.test import TestCase
from django.urls import reverse
from .models import CanvasAsset, CanvasCategory, DesignOffer, DesignRequirement, Package, User


class DesignLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_details = False
        self.canvas_links = []

    def handle_starttag(self, tag, attrs):
        if tag == 'template':
            self.in_details = True
        attrs = dict(attrs)
        if tag == 'a' and attrs.get('href', '').startswith(reverse('design_canvas')):
            self.canvas_links.append((attrs['href'], self.in_details))

    def handle_endtag(self, tag):
        if tag == 'template':
            self.in_details = False


class SelectDesignConfirmTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='offer_picker_customer', role='customer')
        category = CanvasCategory.objects.create(name='Picker panels')
        CanvasAsset.objects.create(category=category, label='Picker panel', static_path='images/picker-panel.svg')
        package = Package.objects.create(name='Picker package', features='Two styling panels', price=5000)
        cls.offer = DesignOffer.objects.create(kind='package', package=package, is_enabled=True)
        DesignRequirement.objects.create(offer=cls.offer, category=category, required=True, minimum=2, maximum=2)

    def setUp(self):
        self.client.force_login(self.user)

    def test_both_entry_points_show_inclusions_before_continue(self):
        for url in ('my_designs', 'select_design_type'):
            response = self.client.get(reverse(url))
            self.assertContains(response, 'Two styling panels')
            self.assertContains(response, '2 required')
            self.assertContains(response, '<dialog class="dl-offer-dialog"')
            self.assertNotContains(response, '<details class="design-offer-details"')
            self.assertContains(response, 'Required before booking')
            parser = DesignLinks()
            parser.feed(response.content.decode())
            self.assertEqual(parser.canvas_links, [(reverse('design_canvas') + f'?design_offer_id={self.offer.pk}&fresh=1', True)])

    def test_unconfigured_offer_cannot_be_selected_or_opened(self):
        self.offer.is_enabled = False
        self.offer.save()
        self.assertNotContains(self.client.get(reverse('select_design_type')), 'Picker package')
        response = self.client.get(reverse('design_canvas'), {'design_offer_id': self.offer.pk})
        self.assertRedirects(response, reverse('select_design_type'), fetch_redirect_response=False)

    def test_all_three_design_tabs_are_present(self):
        response = self.client.get(reverse('select_design_type'))
        for label in ('Package', 'Entrance Arch', 'Welcome Stand'):
            self.assertContains(response, label)
