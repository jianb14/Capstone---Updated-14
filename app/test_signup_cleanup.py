"""Abandoned signup retention never cascades through account activity."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
from threading import Barrier, Event
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections, transaction
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone

from . import signup_lifecycle
from .models import AuditLog, Booking, EmailOTPChallenge, Payment, User


def pending_user(username='unused', **overrides):
    return User.objects.create_user(username=username, email=username + '@gmail.com', password='PendingPassword!123',
        **dict({'role': 'customer', 'email_verified': False,
            'pending_signup_expires_at': timezone.now() - timedelta(days=1)}, **overrides))


class SignupCleanupTests(TestCase):
    def test_cleanup_deletes_only_expired_marked_unused_customers(self):
        expired = pending_user()
        legacy = pending_user('legacy', pending_signup_expires_at=None)
        fresh = pending_user('fresh', pending_signup_expires_at=timezone.now() + timedelta(days=1))
        verified = pending_user('verified', email_verified=True)
        admin = pending_user('admin', role='admin')
        staff = pending_user('staff', role='staff')
        flagged = pending_user('flagged', is_staff=True)
        superuser = pending_user('superuser', is_superuser=True)
        disabled = pending_user('disabled', is_active=False)
        used = pending_user('used', last_login=timezone.now())
        result = signup_lifecycle.prune_pending_signups()
        self.assertEqual(result['deleted'], 1)
        self.assertFalse(User.objects.filter(pk=expired.pk).exists())
        for user in (legacy, fresh, verified, admin, staff, flagged, superuser, disabled, used):
            self.assertTrue(User.objects.filter(pk=user.pk).exists())

    def test_booking_and_payment_records_protect_expired_signup(self):
        user = pending_user()
        booking = Booking.objects.create(user=user, event_date=timezone.localdate() + timedelta(days=10),
            event_type='Birthday', event_location='Test venue', total_price=5000)
        payment = Payment.objects.create(booking=booking, amount=5000, payment_method='gcash', transaction_ref='preserved')
        self.assertEqual(signup_lifecycle.prune_pending_signups()['protected'], 1)
        self.assertTrue(User.objects.filter(pk=user.pk).exists())
        self.assertTrue(Booking.objects.filter(pk=booking.pk).exists())
        self.assertTrue(Payment.objects.filter(pk=payment.pk).exists())
        user.refresh_from_db()
        self.assertIsNone(user.pending_signup_expires_at)

    def test_even_non_financial_activity_and_assigned_groups_are_preserved(self):
        logged = pending_user('audit')
        AuditLog.objects.create(user=logged, action='Existing account activity')
        grouped = pending_user('grouped')
        grouped.groups.add(Group.objects.create(name='Assigned group'))
        result = signup_lifecycle.prune_pending_signups()
        self.assertEqual(result['deleted'], 0)
        self.assertEqual(result['protected'], 2)
        self.assertTrue(AuditLog.objects.filter(user=logged).exists())
        self.assertTrue(grouped.groups.exists())

    def test_dry_run_is_read_only_then_apply_cleans_the_otp_rows(self):
        user = pending_user()
        challenge = EmailOTPChallenge.objects.create(user=user, purpose=EmailOTPChallenge.SIGNUP,
            code_digest='digest', session_digest='binding', password_digest='password', expires_at=timezone.now())
        output = StringIO()
        call_command('prune_pending_signups', dry_run=True, stdout=output)
        self.assertIn('Eligible: 1; deleted: 0', output.getvalue())
        self.assertTrue(User.objects.filter(pk=user.pk).exists())
        call_command('prune_pending_signups', stdout=StringIO())
        self.assertFalse(User.objects.filter(pk=user.pk).exists())
        self.assertFalse(EmailOTPChallenge.objects.filter(pk=challenge.pk).exists())

    def test_batch_size_and_explicit_user_filter_are_respected(self):
        first, second = pending_user('first'), pending_user('second')
        result = signup_lifecycle.prune_pending_signups(user_ids=[second.pk], limit=1)
        self.assertEqual(result['deleted'], 1)
        self.assertTrue(User.objects.filter(pk=first.pk).exists())
        self.assertFalse(User.objects.filter(pk=second.pk).exists())

    def test_invalid_command_limit_does_not_delete_any_account(self):
        user = pending_user()
        for limit in (0, -1):
            with self.assertRaises(CommandError):
                call_command('prune_pending_signups', limit=limit, stdout=StringIO())
        self.assertTrue(User.objects.filter(pk=user.pk).exists())

    def test_periodic_cleanup_shares_a_database_budget_and_does_not_run_every_request(self):
        first = pending_user('first')
        self.assertEqual(signup_lifecycle.process_signup_cleanup()['deleted'], 1)
        second = pending_user('second')
        self.assertIsNone(signup_lifecycle.process_signup_cleanup())
        self.assertFalse(User.objects.filter(pk=first.pk).exists())
        self.assertTrue(User.objects.filter(pk=second.pk).exists())

    def test_failed_email_rollback_preserves_a_concurrently_verified_or_used_account(self):
        user = pending_user(pending_signup_expires_at=timezone.now() + timedelta(days=7), email_verified=True)
        signup_lifecycle.discard_failed_signup(user.pk)
        self.assertTrue(User.objects.filter(pk=user.pk).exists())
        user.email_verified = False
        user.save(update_fields=['email_verified'])
        AuditLog.objects.create(user=user, action='Account activity during mail submission')
        signup_lifecycle.discard_failed_signup(user.pk)
        self.assertTrue(User.objects.filter(pk=user.pk).exists())


class SignupCleanupConcurrencyTests(TransactionTestCase):
    @skipUnlessDBFeature('has_select_for_update')
    def test_simultaneous_cleanup_workers_delete_account_once(self):
        user = pending_user()
        barrier = Barrier(2)
        def operation(index):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return signup_lifecycle.prune_pending_signups()['deleted']
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            counts = list(pool.map(operation, range(2)))
        self.assertEqual(sum(counts), 1)
        self.assertFalse(User.objects.filter(pk=user.pk).exists())

    @skipUnlessDBFeature('has_select_for_update')
    def test_cleanup_rechecks_verified_state_after_waiting_for_user_lock(self):
        user = pending_user()
        selected = Event()
        manager = User.objects
        original = manager.select_for_update
        def mark_selection(*args, **kwargs):
            selected.set()
            return original(*args, **kwargs)
        def clean():
            close_old_connections()
            try:
                return signup_lifecycle.prune_pending_signups()
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                locked = User.objects.select_for_update().get(pk=user.pk)
                with patch.object(manager, 'select_for_update', side_effect=mark_selection):
                    future = pool.submit(clean)
                    self.assertTrue(selected.wait(timeout=10))
                    locked.email_verified = True
                    locked.pending_signup_expires_at = None
                    locked.save(update_fields=['email_verified', 'pending_signup_expires_at'])
            self.assertEqual(future.result(timeout=15)['deleted'], 0)
        user.refresh_from_db()
        self.assertTrue(user.email_verified)
