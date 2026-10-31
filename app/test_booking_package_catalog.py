"""Customer booking pickers share catalog order and the admin's popular flag."""
from django.test import TestCase
from django.urls import reverse

from .models import Package, User


def seed_booking_packages():
    return {name: Package.objects.create(name=name, price=10000 - index * 500,
                                        features='Backdrop\nBalloons', is_active=True)
            for index, name in enumerate(('Package 3', 'Package 1-B', 'Package 10',
                                          'Package 1-A', 'Package 2', 'Package 1'))}


class BookingPackageCatalogTests(TestCase):
    def setUp(self):
        self.packages = seed_booking_packages()
        self.hidden = Package.objects.create(name='Package 0', price=100,
                                             is_active=False, is_featured=True)
        self.client.force_login(User.objects.create_user(username='package-picker', role='customer'))

    def assert_pickers(self, expected, badge_count):
        for route in ('booking_page', 'customer_profile'):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 200)
                self.assertEqual([package.name for package in response.context['packages']], expected)
                self.assertContains(response, 'class="booking-popular-badge"', count=badge_count)
                self.assertNotContains(response, 'data-package="Package 0"')

    def test_without_popular_packages_numbers_and_letters_are_in_order(self):
        self.assert_pickers(['Package 1', 'Package 1-A', 'Package 1-B',
                             'Package 2', 'Package 3', 'Package 10'], 0)

    def test_one_popular_package_comes_first_then_the_rest_stay_in_order(self):
        Package.objects.filter(name='Package 2').update(is_featured=True)
        self.assert_pickers(['Package 2', 'Package 1', 'Package 1-A',
                             'Package 1-B', 'Package 3', 'Package 10'], 1)

    def test_multiple_popular_packages_keep_number_and_letter_order_in_both_groups(self):
        Package.objects.filter(name__in=['Package 3', 'Package 1-B', 'Package 1-A']).update(is_featured=True)
        self.assert_pickers(['Package 1-A', 'Package 1-B', 'Package 3',
                             'Package 1', 'Package 2', 'Package 10'], 3)

    def test_changing_popular_flag_is_reflected_on_the_next_booking_form(self):
        Package.objects.filter(name='Package 10').update(is_featured=True)
        self.assert_pickers(['Package 10', 'Package 1', 'Package 1-A',
                             'Package 1-B', 'Package 2', 'Package 3'], 1)
        Package.objects.filter(name='Package 10').update(is_featured=False)
        self.assert_pickers(['Package 1', 'Package 1-A', 'Package 1-B',
                             'Package 2', 'Package 3', 'Package 10'], 0)
