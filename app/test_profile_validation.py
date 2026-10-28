from django.test import TestCase
from django.urls import reverse

from .models import AuditLog, User


class EditProfileValidationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='profile-validation', email='profile@example.com',
            password='ExistingPassword!25', role='customer', email_verified=True,
            first_name='Jamie', last_name='Rivera', phone_number='09170000000')
        self.client.force_login(self.user)
        self.data = {'first_name': 'Jamie', 'last_name': 'Rivera', 'phone_number': '09170000000'}

    def test_required_fields_reject_missing_empty_and_whitespace_without_saving(self):
        for field in self.data:
            for value in (None, '', '   '):
                with self.subTest(field=field, value=value):
                    data = {**self.data, 'first_name': 'Changed'}
                    if value is None:
                        data.pop(field)
                    else:
                        data[field] = value
                    response = self.client.post(reverse('update_my_profile'), data)
                    self.assertEqual(response.status_code, 400)
                    self.assertIn(field, response.context['profile_form'].errors)
                    self.user.refresh_from_db()
                    self.assertEqual(self.user.first_name, 'Jamie')
                    self.assertEqual(self.user.last_name, 'Rivera')
                    self.assertEqual(self.user.phone_number, '09170000000')
        self.assertFalse(AuditLog.objects.filter(user=self.user, action='Updated their profile information.').exists())

    def test_rejects_bad_phone_and_values_exceeding_storage_limits(self):
        for field, value in (('phone_number', 'abc12345678'), ('phone_number', '123'),
                ('phone_number', '1' * 16), ('phone_number', '1' * 21),
                ('first_name', 'A' * 151), ('last_name', 'B' * 151)):
            with self.subTest(field=field, value=value):
                response = self.client.post(reverse('update_my_profile'), {**self.data, field: value})
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.context['profile_form'].errors)

    def test_error_keeps_submitted_values_and_success_trims_all_required_fields(self):
        response = self.client.post(reverse('update_my_profile'), {**self.data, 'first_name': 'Updated', 'last_name': ''})
        self.assertEqual(response.context['profile_form']['first_name'].value(), 'Updated')
        self.assertEqual(response.context['profile_form']['last_name'].value(), '')
        response = self.client.post(reverse('update_my_profile'), {
            'first_name': ' Jamie Updated ', 'last_name': ' Rivera ', 'phone_number': ' +63 917 000 0000 '})
        self.assertRedirects(response, reverse('my_profile'))
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Jamie Updated')
        self.assertEqual(self.user.last_name, 'Rivera')
        self.assertEqual(self.user.phone_number, '+63 917 000 0000')
