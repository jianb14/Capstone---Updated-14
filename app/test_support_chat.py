"""Support-specific isolation, validation, retries, read boundaries and history."""
import io
import json
import uuid
from datetime import timedelta
from unittest.mock import patch

from PIL import Image
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AdminNotification, ChatMessage, ChatSession, ChatNotification, SubmissionReceipt, User


def photo(name='photo.png'):
    stream = io.BytesIO()
    Image.new('RGB', (12, 12), 'gold').save(stream, 'PNG')
    return SimpleUploadedFile(name, stream.getvalue(), content_type='image/png')


@override_settings(REQUEST_RATE_LIMITING_ENABLED=False, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class SupportChatTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='support-admin', email='support@example.com', role='admin', email_verified=True)
        self.customer = User.objects.create_user(username='customer', first_name='Jamie', last_name='Rivera', role='customer', email='jamie@example.com', email_verified=True)
        self.other = User.objects.create_user(username='other', role='customer', email_verified=True)
        self.session = ChatSession.objects.create(user=self.customer, is_admin_support=True, status='active_admin', assigned_admin=self.admin)
        self.client.force_login(self.customer)

    def send(self, **data):
        values = {'message': 'Hello support', 'session_id': self.session.pk, 'request_id': str(uuid.uuid4())}
        values.update(data)
        return self.client.post(reverse('support_send'), values)

    def action(self, action, **data):
        return self.client.post(reverse('support_action'), json.dumps({'action': action, 'session_id': self.session.pk, **data}), content_type='application/json')

    def test_all_endpoints_require_login_and_customer_cannot_read_admin_inbox(self):
        self.assertEqual(self.client.get(reverse('support_inbox')).status_code, 403)
        self.client.logout()
        for route in ('support_state', 'support_inbox', 'support_send', 'support_action'):
            response = self.client.post(reverse(route)) if route in ('support_send', 'support_action') else self.client.get(reverse(route))
            self.assertEqual(response.status_code, 401)
            self.assertIn('no-store', response['Cache-Control'])

    def test_state_does_not_create_empty_conversations_or_mark_unseen_messages_read(self):
        self.session.delete()
        self.assertIsNone(self.client.get(reverse('support_state')).json()['session'])
        self.assertFalse(ChatSession.objects.filter(user=self.customer).exists())
        self.session = ChatSession.objects.create(user=self.customer, is_admin_support=True, status='active_admin')
        message = ChatMessage.objects.create(session=self.session, sender=self.admin, receiver=self.customer, message='Hi')
        self.client.get(reverse('support_state'), {'session_id': self.session.pk})
        message.refresh_from_db(); self.assertFalse(message.is_read)

    def test_customer_cannot_access_other_or_ai_conversations(self):
        alien = ChatSession.objects.create(user=self.other, is_admin_support=True, status='active_admin')
        ai = ChatSession.objects.create(user=self.customer, status='ai')
        for target in (alien, ai):
            self.assertEqual(self.client.get(reverse('support_state'), {'session_id': target.pk}).status_code, 404)
            self.assertEqual(self.send(session_id=target.pk).status_code, 404)
            self.assertEqual(self.client.post(reverse('support_action'), json.dumps({'session_id': target.pk, 'action': 'close'}), content_type='application/json').status_code, 404)

    def test_empty_long_malformed_requests_are_inline_validation_errors(self):
        for values in ({'message': ''}, {'message': ' '}, {'message': 'x' * 4001}, {'request_id': 'bad'}):
            self.assertEqual(self.send(**values).status_code, 400)
        self.assertEqual(self.client.post(reverse('support_action'), 'not-json', content_type='application/json').status_code, 400)
        self.assertEqual(self.client.post(reverse('support_action'), '[]', content_type='application/json').status_code, 400)
        self.assertFalse(ChatMessage.objects.exists())

    def test_upload_limits_and_actual_image_validation_happen_before_save(self):
        bad = SimpleUploadedFile('wrong.png', b'not an image', content_type='image/png')
        response = self.send(image=[photo(), bad]); self.assertEqual(response.status_code, 400)
        self.assertFalse(ChatMessage.objects.exists())
        self.assertEqual(self.send(image=[photo(f'{n}.png') for n in range(5)]).status_code, 400)
        self.assertEqual(self.send(image=SimpleUploadedFile('large.png', b'x' * (5 * 1024 * 1024 + 1), content_type='image/png')).status_code, 400)
        self.assertEqual(self.send(image=SimpleUploadedFile('a.svg', b'<svg/>', content_type='image/svg+xml')).status_code, 400)
        self.assertFalse(ChatMessage.objects.exists())

    def test_image_only_message_and_reply_image_supported(self):
        original = ChatMessage.objects.create(session=self.session, sender=self.admin, receiver=self.customer, message='Send a reference')
        response = self.send(message='', image=photo(), reply_to_id=original.pk)
        self.assertEqual(response.status_code, 200)
        sent = response.json()['messages'][0]
        self.assertTrue(sent['image_url']); self.assertEqual(sent['reply_to']['id'], original.pk)

    def test_first_message_reuses_conversation_and_notifies_admin_only_once(self):
        self.session.delete()
        token = str(uuid.uuid4())
        first = self.send(session_id='', request_id=token)
        second = self.send(session_id='', request_id=token)
        self.assertEqual(first.status_code, 200); self.assertEqual(second.json(), first.json())
        self.assertEqual(ChatSession.objects.filter(user=self.customer).count(), 1)
        self.assertEqual(ChatMessage.objects.count(), 1)
        self.assertEqual(AdminNotification.objects.filter(user=self.customer, message__icontains='support').count(), 1)
        self.send(session_id='')
        self.assertEqual(ChatSession.objects.filter(user=self.customer).count(), 1)

    def test_retry_is_durable_and_different_payload_cannot_reuse_receipt(self):
        token = str(uuid.uuid4())
        self.assertEqual(self.send(request_id=token).status_code, 200)
        self.assertEqual(self.send(request_id=token).status_code, 200)
        self.assertEqual(ChatMessage.objects.count(), 1)
        self.assertTrue(SubmissionReceipt.objects.exists())
        self.assertEqual(self.send(request_id=token, message='Different').status_code, 409)

    def test_invalid_reply_does_not_create_or_modify_conversation(self):
        self.session.delete()
        self.assertEqual(self.send(session_id='', reply_to_id=999).status_code, 400)
        self.assertFalse(ChatSession.objects.filter(user=self.customer).exists())

    def test_inactive_admin_is_not_assigned_new_customer_messages(self):
        self.admin.is_active = False; self.admin.save(update_fields=['is_active'])
        self.assertEqual(self.send().status_code, 503)
        fallback = User.objects.create_user(username='newadmin', role='admin', email_verified=True)
        self.assertEqual(self.send().status_code, 200)
        self.assertEqual(ChatMessage.objects.get().receiver_id, fallback.pk)

    def test_admin_sends_async_reply_reopens_and_notifies_offline_customer(self):
        self.session.status = 'closed'; self.session.save()
        self.client.force_login(self.admin)
        response = self.send()
        self.assertEqual(response.status_code, 200)
        self.session.refresh_from_db(); self.assertEqual(self.session.status, 'active_admin')
        self.assertEqual(self.session.assigned_admin_id, self.admin.pk)
        self.assertEqual(ChatNotification.objects.filter(user=self.customer).count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.customer.email])

    def test_email_failure_does_not_lose_or_duplicate_successful_reply(self):
        self.client.force_login(self.admin)
        token = str(uuid.uuid4())
        with patch('app.views.support_chat.send_mail', side_effect=RuntimeError('mail unavailable')), self.assertLogs('app.views.support_chat', level='ERROR'):
            self.assertEqual(self.send(request_id=token).status_code, 200)
        self.assertEqual(self.send(request_id=token).status_code, 200)
        self.assertEqual(ChatMessage.objects.count(), 1)
        self.assertEqual(ChatNotification.objects.count(), 1)

    def test_read_only_marks_incoming_messages_up_to_visible_boundary(self):
        first = ChatMessage.objects.create(session=self.session, sender=self.admin, receiver=self.customer, message='first')
        last = ChatMessage.objects.create(session=self.session, sender=self.admin, receiver=self.customer, message='last')
        self.action('activity', read=True, last_id=first.pk)
        first.refresh_from_db(); last.refresh_from_db()
        self.assertTrue(first.is_read); self.assertFalse(last.is_read)
        self.assertEqual(self.client.get(reverse('support_state'), {'summary': 1}).json()['unread'], 1)

    def test_received_messages_can_be_delivered_without_marking_them_seen(self):
        message = ChatMessage.objects.create(session=self.session, sender=self.admin, receiver=self.customer, message='Hello')
        self.action('activity', read=False, last_id=message.pk)
        message.refresh_from_db()
        self.assertTrue(message.is_delivered); self.assertFalse(message.is_read)

    def test_another_admin_viewing_thread_does_not_mark_team_reply_seen_by_customer(self):
        teammate = User.objects.create_user(username='teammate', role='admin', email_verified=True)
        message = ChatMessage.objects.create(session=self.session, sender=teammate, receiver=self.customer, message='Team reply')
        self.client.force_login(self.admin)
        self.action('activity', read=True, last_id=message.pk)
        message.refresh_from_db()
        self.assertFalse(message.is_read); self.assertFalse(message.is_delivered)
        self.client.force_login(self.customer)
        self.action('activity', read=True, last_id=message.pk)
        message.refresh_from_db()
        self.assertTrue(message.is_read)

    def test_sidebar_and_inbox_unread_counts_clear_after_opening_actual_sent_messages(self):
        response = self.send()
        last_id = response.json()['messages'][-1]['id']
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('admin_chat_unread_poll')).json()['unread_total'], 1)
        self.action('activity', read=True, last_id=last_id)
        self.assertEqual(self.client.get(reverse('admin_chat_unread_poll')).json()['unread_total'], 0)
        self.assertEqual(self.client.get(reverse('support_inbox')).json()['stats']['unread'], 0)
        page = self.client.get(reverse('admin_chat_inbox'))
        self.assertEqual(page.context['admin_chat_unread_count'], 0)

    def test_read_boundary_does_not_mark_newer_customer_message_as_seen(self):
        first = ChatMessage.objects.create(session=self.session, sender=self.customer, receiver=self.admin, message='first')
        last = ChatMessage.objects.create(session=self.session, sender=self.customer, receiver=self.admin, message='last')
        self.client.force_login(self.admin); self.action('activity', read=True, last_id=first.pk)
        self.client.force_login(self.customer)
        messages = self.client.get(reverse('support_state'), {'session_id': self.session.pk}).json()['messages']
        self.assertTrue(messages[0]['seen']); self.assertFalse(messages[1]['seen'])

    def test_edit_delete_require_ownership_and_deleted_messages_cannot_be_edited(self):
        own = ChatMessage.objects.create(session=self.session, sender=self.customer, receiver=self.admin, message='original')
        other = ChatMessage.objects.create(session=self.session, sender=self.admin, receiver=self.customer, message='admin reply')
        self.assertEqual(self.action('edit', message_id=other.pk, message='attack').status_code, 403)
        self.assertEqual(self.action('delete', message_id=other.pk).status_code, 403)
        self.assertEqual(self.action('edit', message_id=own.pk, message=' ').status_code, 400)
        self.assertEqual(self.action('edit', message_id=own.pk, message='updated').json()['updated']['content'], 'updated')
        self.action('pin', message_id=own.pk); self.action('react', message_id=own.pk, emoji='👍')
        self.assertEqual(self.action('delete', message_id=own.pk).status_code, 200)
        own.refresh_from_db(); self.assertFalse(own.is_pinned); self.assertFalse(own.reactions.exists())
        self.assertEqual(self.action('edit', message_id=own.pk, message='revived').status_code, 400)

    def test_pins_capped_at_three_and_reactions_toggle_and_replace(self):
        rows = [ChatMessage.objects.create(session=self.session, sender=self.customer, receiver=self.admin, message=str(n)) for n in range(4)]
        for row in rows:
            self.assertEqual(self.action('pin', message_id=row.pk).status_code, 200)
        self.assertEqual(self.session.messages.filter(is_pinned=True).count(), 3)
        self.assertFalse(self.session.messages.get(pk=rows[0].pk).is_pinned)
        for emoji in ('👍', '❤️'):
            self.assertEqual(self.action('react', message_id=rows[0].pk, emoji=emoji).status_code, 200)
        self.assertEqual(rows[0].reactions.count(), 1)
        self.action('react', message_id=rows[0].pk, emoji='❤️')
        self.assertEqual(rows[0].reactions.count(), 0)
        self.client.force_login(self.admin)
        self.assertEqual(self.action('pin', message_id=rows[-1].pk).status_code, 403)

    def test_history_search_pagination_local_time_and_media(self):
        ChatMessage.objects.bulk_create([ChatMessage(session=self.session, sender=self.customer, receiver=self.admin, message=f'Message {n}') for n in range(65)])
        response = self.client.get(reverse('support_state'), {'session_id': self.session.pk}).json()
        self.assertEqual(len(response['messages']), 50); self.assertTrue(response['has_more'])
        earlier = self.client.get(reverse('support_state'), {'session_id': self.session.pk, 'before': response['oldest_id']}).json()
        self.assertEqual(len(earlier['messages']), 15); self.assertFalse(earlier['has_more'])
        self.assertLess(earlier['messages'][-1]['id'], response['messages'][0]['id'])
        self.assertIn('+08:00', response['messages'][0]['sent_iso'])
        searched = self.client.get(reverse('support_state'), {'session_id': self.session.pk, 'q': 'Message 0'}).json()
        self.assertEqual(len(searched['messages']), 1)
        self.assertEqual(self.client.get(reverse('support_state'), {'before': 'bad'}).status_code, 400)

    def test_visible_older_messages_refresh_after_edit_without_losing_latest_page(self):
        old = ChatMessage.objects.create(session=self.session, sender=self.customer, receiver=self.admin, message='old original')
        ChatMessage.objects.bulk_create([ChatMessage(session=self.session, sender=self.customer, receiver=self.admin, message=str(n)) for n in range(55)])
        self.action('edit', message_id=old.pk, message='old edited')
        data = self.client.get(reverse('support_state'), {'session_id': self.session.pk, 'watch': str(old.pk)}).json()
        self.assertEqual(len(data['messages']), 50)
        self.assertEqual(data['updates'][0]['content'], 'old edited')
        self.assertEqual(self.client.get(reverse('support_state'), {'session_id': self.session.pk, 'watch': 'bad'}).status_code, 400)

    def test_admin_read_position_never_moves_backwards(self):
        first = ChatMessage.objects.create(session=self.session, sender=self.customer, receiver=self.admin, message='first')
        last = ChatMessage.objects.create(session=self.session, sender=self.customer, receiver=self.admin, message='last')
        self.client.force_login(self.admin)
        self.action('activity', read=True, last_id=last.pk)
        self.action('activity', read=True, last_id=first.pk)
        self.session.refresh_from_db()
        self.assertEqual(self.session.admin_last_read_at, last.sent_at)

    def test_reconnect_catches_up_in_order_without_skipping_message_bursts(self):
        first = ChatMessage.objects.create(session=self.session, sender=self.customer, receiver=self.admin, message='first')
        ChatMessage.objects.bulk_create([ChatMessage(session=self.session, sender=self.admin, receiver=self.customer, message=str(n)) for n in range(120)])
        cursor = first.pk; collected = []
        for expected in (50, 50, 20):
            data = self.client.get(reverse('support_state'), {'session_id': self.session.pk, 'after': cursor}).json()
            self.assertEqual(len(data['messages']), expected)
            self.assertEqual(data['more_new'], expected == 50)
            ids = [message['id'] for message in data['messages']]
            self.assertEqual(ids, sorted(ids)); self.assertGreater(ids[0], cursor)
            collected.extend(ids); cursor = ids[-1]
        self.assertEqual(len(set(collected)), 120)

    def test_inbox_counts_search_unread_and_close_filter_are_consistent(self):
        ChatMessage.objects.create(session=self.session, sender=self.customer, receiver=self.admin, message='find this old message')
        self.client.force_login(self.admin)
        data = self.client.get(reverse('support_inbox'), {'q': 'find this old'}).json()
        self.assertEqual(len(data['sessions']), 1); self.assertEqual(data['stats']['unread'], 1)
        self.assertEqual(self.action('close').status_code, 200)
        self.assertEqual(len(self.client.get(reverse('support_inbox'), {'status': 'closed'}).json()['sessions']), 1)
        self.client.force_login(self.customer); self.assertEqual(self.action('close').status_code, 403)
        self.assertEqual(self.send().status_code, 200)

    def test_inbox_and_thread_render_shared_async_workspace(self):
        self.client.force_login(self.admin)
        for route, args in (('admin_chat_inbox', []), ('admin_chat_thread', [self.session.pk])):
            response = self.client.get(reverse(route, args=args))
            self.assertContains(response, 'data-support-chat')
            self.assertContains(response, 'js/support_chat.js')
            self.assertNotContains(response, 'window.location.reload()')
