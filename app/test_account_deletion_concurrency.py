"""Run these row lock tests against an isolated PostgreSQL test database."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Event

from django.contrib.sessions.backends.db import SessionStore
from django.db import close_old_connections, connections, transaction
from django.http import HttpResponse
from django.test import RequestFactory, TransactionTestCase, skipUnlessDBFeature

from .account_deletion import deletion_blockers, remove_account
from .account_lifecycle import CustomerAccountLifecycleMiddleware
from .ai_jobs import complete_request
from .models import AiRequest, Booking, ChatMessage, User


@skipUnlessDBFeature('has_select_for_update')
class AccountDeletionConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user=User.objects.create_user(username='deletion-concurrent',role='customer',
            password='Password!25',email='concurrent@example.com',email_verified=True)

    def in_thread(self, operation):
        close_old_connections()
        try:
            return operation()
        finally:
            connections.close_all()

    def test_authenticated_write_waits_for_removal_and_cannot_recreate_booking(self):
        locked,release,started=Event(),Event(),Event()
        def deletion():
            with transaction.atomic():
                user=User.objects.select_for_update().get(pk=self.user.pk)
                self.assertFalse(deletion_blockers(user,lock=True))
                locked.set(); self.assertTrue(release.wait(10)); remove_account(user)
        def stale_write():
            request=RequestFactory().post('/booking/',HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            request.user=self.user; request.session=SessionStore(); started.set()
            def create(request):
                Booking.objects.create(user=request.user,event_date=date(2026,1,1),event_type='Birthday',event_location='Private',total_price=0)
                return HttpResponse(status=200)
            return CustomerAccountLifecycleMiddleware(create)(request).status_code
        with ThreadPoolExecutor(max_workers=2) as executor:
            first=executor.submit(self.in_thread,deletion)
            self.assertTrue(locked.wait(10))
            second=executor.submit(self.in_thread,stale_write)
            self.assertTrue(started.wait(10)); release.set()
            first.result(timeout=15); self.assertEqual(second.result(timeout=15),401)
        self.assertFalse(Booking.objects.filter(user=self.user).exists())

    def test_booking_committed_before_removal_is_seen_by_final_check(self):
        locked,release,started=Event(),Event(),Event()
        def create():
            with transaction.atomic():
                user=User.objects.select_for_update().get(pk=self.user.pk)
                Booking.objects.create(user=user,event_date=date(2026,1,1),event_type='Birthday',event_location='Private',total_price=0)
                locked.set(); self.assertTrue(release.wait(10))
        def eligibility():
            started.set()
            with transaction.atomic():
                user=User.objects.select_for_update().get(pk=self.user.pk)
                return bool(deletion_blockers(user,lock=True))
        with ThreadPoolExecutor(max_workers=2) as executor:
            first=executor.submit(self.in_thread,create); self.assertTrue(locked.wait(10))
            second=executor.submit(self.in_thread,eligibility)
            self.assertTrue(started.wait(10)); release.set()
            first.result(timeout=15); self.assertTrue(second.result(timeout=15))
        self.user.refresh_from_db(); self.assertIsNone(self.user.deleted_at)

    def test_late_ai_completion_and_removal_share_lock_order(self):
        import uuid
        locked,release,started=Event(),Event(),Event()
        job=AiRequest.objects.create(user=self.user,fingerprint='race',input_text='private',state='running',lease_token=uuid.uuid4())
        def deletion():
            with transaction.atomic():
                user=User.objects.select_for_update().get(pk=self.user.pk)
                locked.set(); self.assertTrue(release.wait(10)); remove_account(user)
        def completion():
            started.set(); return complete_request(job.pk,job.lease_token,{'text':'late'})
        with ThreadPoolExecutor(max_workers=2) as executor:
            first=executor.submit(self.in_thread,deletion); self.assertTrue(locked.wait(10))
            second=executor.submit(self.in_thread,completion)
            self.assertTrue(started.wait(10)); release.set()
            first.result(timeout=15); self.assertFalse(second.result(timeout=15))
        self.assertFalse(ChatMessage.objects.filter(receiver=self.user).exists())
