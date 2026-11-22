from datetime import date, time

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from .models import (AddOn, Booking, CanvasCategory, DesignOffer, DesignRequirement,
                     OfferInclusion, Package, ServiceChargeConfig, User)
from .test_booking_design_step import _base_payload


class BookingThemeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='theme-owner', role='customer')
        self.client.force_login(self.user)
        ServiceChargeConfig.objects.create(pk=1, shop_lat='14.414', shop_lng='120.982')
        self.plain = Package.objects.create(name='Package 1-A', price=5000)
        self.themed = Package.objects.create(name='Package 1-B', price=6000)
        self.theme, _ = CanvasCategory.objects.get_or_create(
            builtin_key='theme_decor', defaults={'name': 'Theme Decor'})
        self.plain_offer = DesignOffer.objects.create(kind='package', package=self.plain)
        self.themed_offer = DesignOffer.objects.create(kind='package', package=self.themed)
        DesignRequirement.objects.create(offer=self.themed_offer, category=self.theme)

    def booking(self, **updates):
        fields = dict(user=self.user, event_date=date(2030, 1, 15), event_time=time(9),
            event_end_time=time(11), event_end_date=date(2030, 1, 15), event_type='Birthday',
            event_location='Molino Bacoor Cavite venue', package_type=self.plain.name,
            total_price=5000, design_theme='Old theme', color_palette='Pink', status='pending')
        fields.update(updates)
        return Booking.objects.create(**fields)

    def test_capabilities_match_optional_inclusions_and_composite_selections(self):
        from .booking_themes import theme_decor_capabilities, allows_booking_theme
        arch = AddOn.objects.create(name='Arch', price=1000, solo_price=2000)
        offer = DesignOffer.objects.create(kind='entrance', entrance=arch)
        OfferInclusion.objects.create(offer=offer, name='Theme Decor', category=self.theme)
        capabilities = theme_decor_capabilities()
        self.assertFalse(allows_booking_theme(' Package 1-A ', capabilities))
        self.assertTrue(allows_booking_theme('Package 1-B', capabilities))
        self.assertTrue(allows_booking_theme('Package 1-A + Arch (Add-on)', capabilities))
        self.assertTrue(allows_booking_theme('Arch (Solo)', capabilities))
        self.assertTrue(allows_booking_theme('Legacy package', capabilities))
        self.assertFalse(allows_booking_theme('Package 1-A + Legacy extra', capabilities))

    def test_create_without_theme_keeps_palette_required_and_discards_stale_theme(self):
        for value in ('', 'Princess'):
            with self.subTest(theme=value):
                response = self.client.post(reverse('create_booking'), _base_payload(
                    package_type=self.plain.name, design_theme=value),
                    HTTP_X_REQUESTED_WITH='XMLHttpRequest')
                self.assertTrue(response.json()['success'], response.content)
                booking = Booking.objects.filter(user=self.user).latest('pk')
                self.assertEqual(booking.design_theme, '')
                self.assertEqual(booking.color_palette, 'Pink, Gold')
                booking.delete()
        response = self.client.post(reverse('create_booking'), _base_payload(
            package_type=self.plain.name, design_theme='', color_palette=''),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertFalse(response.json()['success'])
        self.assertIn('color', response.json()['message'])

    def test_included_theme_is_still_required(self):
        response = self.client.post(reverse('create_booking'), _base_payload(
            package_type=self.themed.name, design_theme=''), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertFalse(response.json()['success'])
        self.assertIn('theme', response.json()['message'])

    def test_edit_switch_to_package_without_theme_clears_old_theme(self):
        booking = self.booking(package_type=self.themed.name)
        response = self.client.post(reverse('edit_booking', args=[booking.pk]),
            _base_payload(package_type=self.plain.name, design_theme=''),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTrue(response.json()['success'], response.content)
        booking.refresh_from_db()
        self.assertEqual(booking.design_theme, '')
        self.assertEqual(booking.package_type, self.plain.name)

    def test_change_proposal_uses_the_same_theme_rule(self):
        from .booking_changes import prepare_proposal
        booking = self.booking()
        data = _base_payload(package_type=self.plain.name, design_theme='', map_available='0')
        proposed = prepare_proposal(booking, data)
        self.assertEqual(proposed.design_theme, '')
        proposed = prepare_proposal(booking, {**data, 'design_theme': 'Princess'})
        self.assertEqual(proposed.design_theme, '')
        with self.assertRaisesMessage(ValidationError, 'choose a theme'):
            prepare_proposal(booking, {**data, 'package_type': self.themed.name})

    def test_partial_edit_switch_clears_only_excluded_theme(self):
        booking = self.booking(package_type=self.themed.name)
        data = _base_payload(package_type=self.plain.name)
        del data['design_theme']
        del data['color_palette']
        response = self.client.post(reverse('edit_booking', args=[booking.pk]), data,
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTrue(response.json()['success'], response.content)
        booking.refresh_from_db()
        self.assertEqual(booking.design_theme, '')
        self.assertEqual(booking.color_palette, 'Pink')

    def test_form_contexts_share_authoritative_capabilities(self):
        for url in ('booking_page', 'customer_profile'):
            with self.subTest(url=url):
                response = self.client.get(reverse(url))
                self.assertEqual(response.context['theme_decor_capabilities']['package 1-a'], False)
                self.assertEqual(response.context['theme_decor_capabilities']['package 1-b'], True)
