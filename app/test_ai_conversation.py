import json
import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .ai_conversation import CLARIFY, DATE_QUESTION, IMAGE_QUESTION, validate_plan, extract_details, requested_dates
from .ai_jobs import claim_request, complete_request
from .ai_worker import run_once
from .models import AiRequest, BlockedDate, Booking, ChatMessage, ChatSession, GalleryCategory, GalleryImage, Package, Payment, SiteSettings, User
from .test_ai_jobs import image_bytes


LIMITS = {**settings.REQUEST_RATE_LIMITS, 'ai_chat_cooldown': (1, 0), 'ai_image_cooldown': (1, 0)}


@override_settings(AI_SMART_ROUTING_ENABLED=True, AI_RELEVANCE_CHECK_ENABLED=True,
    HUGGINGFACE_API_KEY='hf_test', AI_WORKER_AUTOSTART=False, REQUEST_RATE_LIMITS=LIMITS)
class ConversationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='smart-customer', role='customer')
        self.other = User.objects.create_user(username='other-customer', role='customer')
        self.admin = User.objects.create_user(username='smart-admin', role='admin')
        self.client.force_login(self.user)
        self.package = Package.objects.create(name='Package 1-A', price=4799,
            features='1 Panel\nBalloon (max 2 colors)\n1 Celebrant Chair')
        self.second = Package.objects.create(name='Package 2', price=7799, features='2 Panels\nBalloon (max 3 colors)')
        self.plan = {'actions': ['answer'], 'updates': {}, 'args': {}}
        self.answer = 'Sage green and ivory work well for an elegant wedding backdrop.'
        self.repaired = 'Use sage green and ivory for a soft wedding palette.'
        self.verdicts = [True]
        self.memory_updates = {}
        self.calls = []
        self.provider_patch = patch('app.services.InferenceClient')
        self.provider = self.provider_patch.start()
        self.addCleanup(self.provider_patch.stop)
        self.provider.return_value.chat_completion.side_effect = self.chat
        self.provider.return_value.text_to_image.return_value = image_bytes()
        self.provider.return_value.image_to_image.return_value = image_bytes()

    def chat(self, **kwargs):
        system = kwargs['messages'][0]['content']
        self.calls.append(kwargs)
        if kwargs.get('stream'):
            return iter([SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=self.answer), finish_reason='stop')])])
        if system.startswith('Write a direct'):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({'text': self.answer})))])
        if system.startswith('Classify'):
            value = self.plan
        elif system.startswith('Extract only'):
            value = {'updates': self.memory_updates}
        elif system.startswith('Check whether'):
            value = {'relevant': self.verdicts.pop(0) if len(self.verdicts) > 1 else self.verdicts[0], 'issue': 'Wrong topic'}
        else:
            value = {'text': self.repaired}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(value)))],
            usage={'prompt_tokens': 20, 'completion_tokens': 10})

    def post(self, message, **kwargs):
        return self.client.post(reverse('ai_request_create'), json.dumps({
            'request_id': str(uuid.uuid4()), 'message': message, **kwargs}), content_type='application/json')

    def process(self, message, **kwargs):
        response = self.post(message, **kwargs)
        self.assertEqual(response.status_code, 202, response.content)
        self.assertTrue(run_once(heartbeat=False))
        job = AiRequest.objects.get(pk=response.json()['id'])
        self.assertEqual(job.state, 'succeeded', job.result)
        return job

    def previous_reply(self, question, reply, *, followup=None, age=None, version=0):
        session = ChatSession.objects.create(user=self.user)
        message = ChatMessage.objects.create(session=session, sender=self.user, receiver=self.admin, message=question)
        answer = ChatMessage.objects.create(session=session, sender=self.admin, receiver=self.user, message=reply)
        plan = {'actions': ['clarify'], 'brief_version': version, 'memory': {}}
        if followup:
            plan['followup'] = followup
        return AiRequest.objects.create(user=self.user, session=session, user_message=message,
            assistant_message=answer, input_text=question, fingerprint=uuid.uuid4().hex,
            state='succeeded', plan=plan, result={'response': reply}, finished_at=timezone.now()-(age or timedelta()))

    def test_catalog_facts_bypass_model_and_accept_a_common_typo(self):
        job = self.process('ano ano yung mga pcakage niyo?')
        self.assertIn('4,799.00', job.result['response'])
        self.assertEqual(job.plan['actions'], ['packages'])
        self.assertEqual(job.metrics['calls'], [])
        self.provider.assert_not_called()

    def test_form_filling_request_is_explained_even_when_planner_only_selects_booking_help(self):
        self.plan = {'actions': ['booking_help'], 'args': {}}
        self.answer = ('In Event Details, choose Event Type, check Event Date, enter Start and End under Event Duration, '
            'and enter the venue address in Location. In Design Preferences, choose Theme / Decor Style and Color Palette. '
            'Motto, Design Notes and up to four Reference Pictures are optional. Then review the details before submitting.')
        job = self.process('paano fill upan yung mga booking form ninyo nalilito kasi ako pwede mo ba akong turuan?')
        self.assertEqual(job.result['response'], self.answer)
        self.assertEqual(job.plan['actions'], ['booking_help'])
        self.assertEqual(job.plan['answer_mode'], 'focused')
        self.assertTrue(job.metrics['quality']['checked'])
        judge = json.loads([call for call in self.calls if call['messages'][0]['content'].startswith('Check whether')][-1]['messages'][1]['content'])
        self.assertIn('Booking Form Field Guide', judge['facts'])
        self.assertIn('Color Palette', judge['facts'])

    def test_followup_about_one_step_does_not_restart_the_booking_overview(self):
        first = self.process('How to book?')
        self.assertEqual(first.plan['answer_mode'], 'overview')
        self.provider.assert_not_called()
        self.plan = {'actions': ['booking_help'], 'args': {}}
        self.answer = 'For Location (Venue Address), enter your actual event venue, choose a search suggestion, and check the map pin.'
        job = self.process('Sa step 3, paano ilalagay yung location?', session_id=first.session_id)
        self.assertEqual(job.result['response'], self.answer)
        self.assertNotIn('To book a setup', job.result['response'])
        judge = json.loads([call for call in self.calls if call['messages'][0]['content'].startswith('Check whether')][-1]['messages'][1]['content'])
        self.assertTrue(any('3. Fill in the event details' in item['content'] for item in judge['recent_conversation']))

    @override_settings(PAYMONGO_SECRET_KEY='test_checkout')
    def test_specific_questions_across_topics_use_tool_facts_without_copying_the_overview(self):
        future = timezone.localdate()+timedelta(days=14)
        BlockedDate.objects.create(date=future, reason='Private scheduling note')
        cases = (
            ('payment_help', 'My GCash checkout failed. Should I pay again?',
                'Check My Payments for a pending or received payment before retrying. A failed checkout alone does not show whether funds were received.'),
            ('packages', 'What does max 2 colors mean in Package 1-A?',
                'It means that Package 1-A allows at most two balloon colors.'),
            ('availability', f'Why is {future.isoformat()} unavailable?',
                'That date is marked Unavailable. The exact scheduling reason is not provided here; please choose another date or ask our team.'),
            ('booking_status', 'Why is my booking still pending after submission?',
                'Pending means your request is waiting for admin approval; submitting the form does not itself confirm it.'),
            ('packages', 'Will Package 2 fit a small venue?',
                'Compare the two-panel layout with the space at your venue; the exact dimensions are not listed here.'),
            ('booking_status', 'Can I reschedule my booking after approval?',
                'Approved bookings use Request changes, subject to eligibility and team review.'),
        )
        for action, question, answer in cases:
            with self.subTest(action=action):
                self.plan = {'actions': [action], 'args': {}}
                self.answer = answer
                job = self.process(question)
                self.assertEqual(job.result['response'], answer)
                self.assertEqual(job.plan['answer_mode'], 'focused')
                self.assertTrue(job.metrics['quality']['checked'])
                self.assertNotIn('Private scheduling note', job.result['response'])
        self.provider.return_value.text_to_image.assert_not_called()

    def test_explanation_of_availability_status_does_not_request_an_unneeded_date(self):
        self.plan = {'actions': ['availability'], 'args': {}}
        self.answer = 'Fully booked means the available slots for that day have been taken.'
        job = self.process('What does Fully Booked mean?')
        self.assertEqual(job.result['response'], self.answer)
        self.assertNotIn('followup', job.plan)

    def test_specific_gallery_question_retains_real_cards_and_gets_a_text_explanation(self):
        category = GalleryCategory.objects.create(name='Wedding')
        image = GalleryImage.objects.create(category=category, image='gallery/real.png', caption='Wedding setup')
        self.answer = 'Gallery photos show actual setups. A newly generated AI image is a concept, not a photo of a previous event.'
        job = self.process('Are these actual setup photos or AI concepts?')
        self.assertEqual(job.result['response'], self.answer)
        self.assertEqual([card['id'] for card in job.result['gallery']], [image.pk])
        self.assertTrue(job.metrics['quality']['checked'])
        self.provider.return_value.text_to_image.assert_not_called()

    def test_wrong_topic_tool_label_does_not_override_a_specific_current_question(self):
        self.plan = {'actions': ['booking_help'], 'args': {}}
        self.answer = 'Received payments awaiting review must not be treated as unsubmitted payments or charged again.'
        job = self.process('My payment is still pending. Should I submit another payment?')
        self.assertEqual(job.result['response'], self.answer)
        self.assertTrue(job.metrics['quality']['checked'])
        judge = json.loads([call for call in self.calls if call['messages'][0]['content'].startswith('Check whether')][-1]['messages'][1]['content'])
        self.assertIn('The booking status pending_payment is a DIFFERENT field', judge['facts'])

    def test_multi_part_question_keeps_evidence_for_each_requested_topic(self):
        self.plan = {'actions': ['booking_help', 'payment_help'], 'args': {}}
        self.answer = 'Enter the event type, date, start/end times and venue address. After approval, follow the GCash checkout instructions in My Payments.'
        job = self.process('How do I fill the booking form and then pay through GCash?')
        self.assertEqual(job.result['response'], self.answer)
        judge = json.loads([call for call in self.calls if call['messages'][0]['content'].startswith('Check whether')][-1]['messages'][1]['content'])
        self.assertIn('Booking Form Field Guide', judge['facts'])
        self.assertIn('GCash through online checkout', judge['facts'])

    def test_generic_overview_for_a_specific_form_question_is_repaired_before_saving(self):
        self.plan = {'actions': ['booking_help'], 'args': {}}
        self.answer = 'To book a setup, open the calendar, choose a package, fill event details and submit.'
        self.repaired = 'In Location (Venue Address), enter the event venue address. The optional landmark helps the crew find the correct gate or floor.'
        self.verdicts = [False, True]
        job = self.process('Paano ilalagay yung venue address at landmark sa booking form?')
        self.assertEqual(job.assistant_message.message, self.repaired)
        self.assertEqual(job.metrics['quality']['repairs'], 1)

    def test_concrete_scope_and_payment_guards_override_an_overly_permissive_judge(self):
        cases = (
            ('booking_help', 'How do I fill the booking form?',
                'Start with Package 1-A for PHP 4799.',
                'Choose Event Type and Event Date, enter Start and End times and your venue address, then complete the theme and palette.'),
            ('payment_help', 'My payment is pending. Should I pay again?',
                'Send a screenshot of your payment to Messenger to verify it.',
                'Check My Payments for a received payment awaiting review. Avoid paying twice.'),
            ('packages', 'Explain the maximum balloon colors in Package 1-A.',
                'White, gold and silver can be accent colors without counting toward the maximum.',
                'Every distinct balloon color counts, including white, gold and silver.'),
        )
        for action, question, draft, corrected in cases:
            with self.subTest(action=action):
                self.plan = {'actions': [action], 'args': {}}
                self.answer, self.repaired = draft, corrected
                self.verdicts = [True]
                job = self.process(question)
                self.assertEqual(job.result['response'], corrected)
                self.assertEqual(job.metrics['quality']['repairs'], 1)

    def test_specific_package_question_can_use_all_requested_features(self):
        self.answer = 'Package 1-A has one panel and allows up to two balloon colors.'
        job = self.process('Explain both the panel count and color limit in Package 1-A.')
        self.assertEqual(job.result['response'], self.answer)
        judge = json.loads([call for call in self.calls if call['messages'][0]['content'].startswith('Check whether')][-1]['messages'][1]['content'])
        self.assertIn('1 Panel', judge['facts'])
        self.assertIn('max 2 colors', judge['facts'])

    def test_live_policy_facts_follow_admin_settings_and_current_change_flow(self):
        from .ai_support_knowledge import runtime_policy_facts
        config = SiteSettings.load()
        config.booking_min_duration_hours = 4
        config.booking_change_cutoff_hours = 72
        config.save(update_fields=['booking_min_duration_hours', 'booking_change_cutoff_hours'])
        facts = runtime_policy_facts()
        self.assertIn('Minimum event duration: 4 hour(s)', facts)
        self.assertIn('within 72 hours', facts)
        self.assertIn('Request changes', facts)

    def test_current_question_is_checked_and_wrong_topic_is_repaired_before_saving(self):
        self.answer = 'Your booking is confirmed and paid.'
        self.verdicts = [False, True]
        job = self.process('Which colors work for a wedding?')
        self.assertEqual(job.result['response'], self.repaired)
        self.assertNotIn('confirmed and paid', job.assistant_message.message)
        self.assertEqual(job.metrics['quality'], {'checked': True, 'passed': True, 'repairs': 1})
        self.assertEqual([call['purpose'] for call in job.metrics['calls']], ['plan', 'answer', 'relevance', 'repair', 'relevance'])
        self.assertEqual(job.partial_text, '')

    def test_unverified_repair_requests_clarification_instead_of_showing_an_unrelated_answer(self):
        self.verdicts = [False, False]
        job = self.process('Which colors work for a wedding?')
        self.assertIn('Could you rephrase', job.result['response'])
        self.assertFalse(job.metrics['quality']['passed'])
        self.assertEqual(len([call for call in job.metrics['calls'] if call['purpose'] == 'repair']), 1)

    def test_previous_topic_does_not_replace_the_current_question(self):
        session = ChatSession.objects.create(user=self.user, design_brief={'theme': 'Garden'})
        ChatMessage.objects.create(session=session, sender=self.user, receiver=self.admin, message='How do I book?')
        job = self.process('Which colors work for a wedding?', session_id=session.pk)
        checking = [call for call in self.calls if call['messages'][0]['content'].startswith('Check whether')][0]
        payload = json.loads(checking['messages'][1]['content'])
        self.assertEqual(payload['question'], job.input_text)
        self.assertEqual(payload['brief']['theme'], 'Garden')
        self.assertIn('sage', job.result['response'].lower())

    def test_general_advice_does_not_overwrite_a_confirmed_design_brief(self):
        session = ChatSession.objects.create(user=self.user, design_brief={'occasion': 'Birthday', 'colors': 'pink'})
        self.process('Which colors work for a wedding?', session_id=session.pk)
        session.refresh_from_db()
        self.assertEqual(session.design_brief, {'occasion': 'Birthday', 'colors': 'pink'})

    def test_memory_survives_more_than_eight_messages_and_preserves_short_edit_context(self):
        original = self.process('Create a balloon backdrop design for a wedding with a Garden theme in sage and white. Display "Sofia" on the backdrop.')
        for n in range(12):
            ChatMessage.objects.create(session=original.session, sender=self.user, receiver=self.admin, message=f'Follow-up {n}')
        edited = self.process('same design, pink naman', session_id=original.session_id)
        self.assertEqual(edited.kind, 'revise')
        self.assertEqual(edited.images.get().parent_id, original.images.get().pk)
        prompt = self.provider.return_value.image_to_image.call_args.kwargs['prompt']
        self.assertIn('Garden', prompt)
        self.assertIn('Sofia', prompt)
        self.assertIn('pink', prompt)
        edited.session.refresh_from_db()
        self.assertEqual(edited.session.design_brief['name'], 'Sofia')
        self.assertEqual(edited.session.design_brief['colors'], 'pink')

    def test_polite_explicit_edit_requests_still_edit_the_owned_image(self):
        original = self.process('Create a balloon backdrop design for a birthday in blue.')
        edited = self.process('Can you change the balloons to pink?', session_id=original.session_id)
        self.assertEqual(edited.kind, 'revise')
        self.assertEqual(edited.images.get().parent_id, original.images.get().pk)
        self.provider.return_value.image_to_image.assert_called_once()

    def test_generated_preferences_require_literal_evidence_and_do_not_leak_between_chats(self):
        self.plan['updates'] = {'name': {'value': 'Invented', 'evidence': 'Invented'},
            'theme': {'value': 'Garden', 'evidence': 'Garden'}}
        first = self.process('I like the Garden theme. What colors suit it?')
        first.session.refresh_from_db()
        self.assertEqual(first.session.design_brief['theme'], 'Garden')
        self.assertNotIn('name', first.session.design_brief)
        self.process('Which colors work for a wedding?')
        payload = json.loads([call for call in self.calls if call['messages'][0]['content'].startswith('Classify')][-1]['messages'][1]['content'])
        self.assertEqual(payload['brief'], {})

    def test_selected_package_panel_and_color_limits_are_checked_before_image_budget(self):
        for description in ('with 4 panels in blue', 'in red, blue and gold'):
            with self.subTest(description=description):
                job = self.process('Create a balloon backdrop design for a birthday using Package 1-A '+description)
                self.assertEqual(job.plan['actions'], ['clarify'])
                self.assertFalse(job.images.exists())
        self.provider.return_value.text_to_image.assert_not_called()

    def test_package_constraints_and_confirmed_details_reach_image_prompt(self):
        job = self.process('Create a balloon backdrop design for a birthday using Package 1-A in navy blue and silver.')
        self.assertTrue(job.images.exists())
        prompt = self.provider.return_value.text_to_image.call_args.kwargs['prompt']
        self.assertIn('PACKAGE CONSTRAINTS', prompt)
        self.assertIn('1 Panel', prompt)
        self.assertIn('max 2 colors', prompt)
        self.assertIn('navy blue', prompt)

    def test_customer_can_resolve_a_color_limit_without_retyping_the_image_request(self):
        original = self.process('Create a balloon backdrop design for a birthday using Package 1-A in red, blue and gold.')
        self.assertFalse(original.images.exists())
        resolved = self.process('blue and gold', session_id=original.session_id)
        self.assertTrue(resolved.images.exists())
        resolved.session.refresh_from_db()
        self.assertNotIn('pending_action', resolved.session.design_brief)

    def test_photo_advice_is_checked_after_the_vision_analysis(self):
        from .test_ai_jobs import upload
        with patch('app.services.analyze_inspiration_image', return_value='Blue and white balloons suit the arch.'):
            response = self.client.post(reverse('ai_request_create'), {'request_id': str(uuid.uuid4()),
                'message': 'Which colors would suit this setup?', 'intent': 'advice', 'image': upload()})
            self.assertEqual(response.status_code, 202)
            self.assertTrue(run_once(heartbeat=False))
        job = AiRequest.objects.get(pk=response.json()['id'])
        self.assertEqual(job.state, 'succeeded', job.result)
        self.assertEqual(job.kind, 'photo_advice')
        self.assertTrue(job.metrics['quality']['checked'])
        self.provider.return_value.text_to_image.assert_not_called()

    def photo(self, message='', **kwargs):
        from .test_ai_jobs import upload
        response = self.client.post(reverse('ai_request_create'), {'request_id': str(uuid.uuid4()),
            'message': message, 'image': upload(), **kwargs})
        self.assertEqual(response.status_code, 202, response.content)
        self.assertTrue(run_once(heartbeat=False))
        job = AiRequest.objects.get(pk=response.json()['id'])
        self.assertEqual(job.state, 'succeeded', job.result)
        return job

    def test_uploaded_photo_is_an_editable_reference_without_an_older_ai_image(self):
        with patch('app.services.analyze_inspiration_image') as analyze:
            job = self.photo('Lagyan ng gold balloons sa kanan, huwag baguhin ang backdrop at pangalan.')
        self.assertEqual(job.kind, 'photo_edit')
        self.assertEqual(job.plan['actions'], ['edit'])
        call = self.provider.return_value.image_to_image.call_args
        self.assertEqual(call.args[0], image_bytes())
        self.assertIn('gold balloons sa kanan', call.kwargs['prompt'])
        self.assertIn('huwag baguhin ang backdrop at pangalan', call.kwargs['prompt'])
        self.assertIn('Preserve everything outside', call.kwargs['prompt'])
        self.assertTrue(job.plan['image_operation']['preserve_unmentioned'])
        self.assertEqual(job.plan['source_photo_id'], job.user_message_id)
        analyze.assert_not_called()
        self.provider.return_value.text_to_image.assert_not_called()

    def test_new_photo_overrides_an_old_selected_generated_image_and_its_preferences(self):
        import io
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        old = self.process('Create a balloon backdrop design for a birthday in blue. Display "Sofia" on the backdrop.')
        uploaded = io.BytesIO()
        Image.new('RGB', (21, 17), 'red').save(uploaded, 'PNG')
        response = self.client.post(reverse('ai_request_create'), {'request_id': str(uuid.uuid4()),
            'session_id': old.session_id, 'reference_id': str(old.images.get().pk),
            'message': 'Add white flowers on the left. Keep the rest.',
            'image': SimpleUploadedFile('new.png', uploaded.getvalue(), content_type='image/png')})
        self.assertEqual(response.status_code, 202)
        self.assertTrue(run_once(heartbeat=False))
        job = AiRequest.objects.get(pk=response.json()['id'])
        self.assertEqual(job.state, 'succeeded', job.result)
        self.assertEqual(self.provider.return_value.image_to_image.call_args.args[0], uploaded.getvalue())
        self.assertIsNone(job.reference_id)
        self.assertIsNone(job.images.get().parent_id)
        self.assertNotIn('Sofia', self.provider.return_value.image_to_image.call_args.kwargs['prompt'])

    def test_photo_alone_asks_for_changes_then_continues_on_that_photo(self):
        from .ai_photo_edits import PHOTO_QUESTION
        old = self.process('Create a balloon backdrop design for a birthday in blue.')
        self.provider.reset_mock()
        pending = self.photo(session_id=old.session_id)
        self.assertEqual(pending.result['response'], PHOTO_QUESTION)
        self.assertFalse(pending.images.exists())
        self.provider.assert_not_called()
        revised = self.process('Add gold balloons on the right.', session_id=pending.session_id)
        self.assertEqual(revised.kind, 'photo_edit')
        self.assertEqual(revised.plan['source_photo_id'], pending.user_message_id)
        self.assertIsNone(revised.reference_id)
        self.provider.return_value.image_to_image.assert_called_once()

    def test_incomplete_edit_shortcut_does_not_start_a_paid_edit(self):
        pending = self.photo('Add ')
        self.assertIn('What would you like to add', pending.result['response'])
        self.assertFalse(pending.images.exists())
        self.provider.return_value.image_to_image.assert_not_called()
        completed = self.process('Add gold balloons on the right.', session_id=pending.session_id)
        self.assertEqual(completed.kind, 'photo_edit')

    def test_inspiration_is_a_new_concept_and_not_a_local_edit(self):
        with patch('app.services.analyze_inspiration_image',
                return_value='Use this palette. [PROMPT]A blue butterfly balloon backdrop[/PROMPT]'):
            job = self.photo('Create a new birthday backdrop inspired by this photo.')
        self.assertEqual(job.kind, 'photo_inspire')
        self.assertEqual(job.plan['image_operation']['action'], 'inspire')
        self.provider.return_value.text_to_image.assert_called_once()
        self.provider.return_value.image_to_image.assert_not_called()

    def test_retry_of_an_original_photo_edit_keeps_the_saved_input_and_source(self):
        from .test_ai_jobs import upload
        self.provider.return_value.image_to_image.side_effect = RuntimeError('Temporary service problem')
        response = self.client.post(reverse('ai_request_create'), {'request_id': str(uuid.uuid4()),
            'message': 'Add gold balloons on the right.', 'image': upload()})
        self.assertEqual(response.status_code, 202)
        self.assertTrue(run_once(heartbeat=False))
        failed = AiRequest.objects.get(pk=response.json()['id'])
        self.assertEqual(failed.state, 'failed')
        self.provider.return_value.image_to_image.side_effect = None
        AiRequest.objects.filter(pk=failed.pk).update(result={**failed.result, 'retry_at': 0})
        retried = self.process('', retry_of=str(failed.pk))
        self.assertEqual(retried.kind, 'photo_edit')
        self.assertEqual(retried.user_message_id, failed.user_message_id)
        self.assertEqual(retried.plan['source_photo_id'], failed.user_message_id)
        self.assertEqual(self.provider.return_value.image_to_image.call_args.args[0], image_bytes())

    def test_photo_question_gives_advice_without_generating_then_can_be_edited(self):
        with patch('app.services.analyze_inspiration_image', return_value='The photo has blue and white balloons.'):
            question = self.photo('What colors are in this photo?')
        self.assertEqual(question.kind, 'photo_advice')
        self.provider.return_value.image_to_image.assert_not_called()
        edited = self.process('Palitan ang balloons ng pink.', session_id=question.session_id)
        self.assertEqual(edited.kind, 'photo_edit')
        self.assertEqual(edited.plan['source_photo_id'], question.user_message_id)

    def test_edits_continue_from_latest_result_and_original_upload_remains_selectable(self):
        first = self.photo('Add gold balloons on the right.')
        second = self.process('Change only the gold balloons to pink.', session_id=first.session_id)
        self.assertEqual(second.kind, 'revise')
        self.assertEqual(second.images.get().parent_id, first.images.get().pk)
        original = self.process('Remove the flowers.', session_id=first.session_id, intent='revise',
            source_photo_id=first.user_message_id)
        self.assertEqual(original.kind, 'photo_edit')
        self.assertEqual(original.plan['source_photo_id'], first.user_message_id)
        self.assertIsNone(original.images.get().parent_id)
        first.user_message.refresh_from_db()
        with first.user_message.image.open('rb') as image:
            self.assertEqual(image.read(), image_bytes())

    def test_photo_reference_is_scoped_to_its_owner_and_chat(self):
        first = self.photo()
        other_chat = ChatSession.objects.create(user=self.user)
        for source in (first.user_message_id, 10**50, True, 'not-a-number'):
            with self.subTest(source=source):
                response = self.post('Add gold balloons.', source_photo_id=source, session_id=other_chat.pk)
                self.assertEqual(response.status_code, 404)
        self.client.force_login(self.other)
        other_session = ChatSession.objects.create(user=self.other)
        self.assertEqual(self.post('Add gold balloons.', source_photo_id=first.user_message_id,
            session_id=other_session.pk).status_code, 404)

    def test_advice_intent_and_negative_instruction_do_not_spend_image_credits(self):
        for message, intent in (
                ('Can you explain how to add balloons?', 'auto'),
                ('Do not generate an image. Which flowers would suit this photo?', 'auto'),
                ('Add gold balloons on the right.', 'advice')):
            with self.subTest(message=message):
                with patch('app.services.analyze_inspiration_image', return_value='Gold accents would suit this setup.'):
                    job = self.photo(message, intent=intent)
                self.assertFalse(job.images.exists())
        self.provider.return_value.image_to_image.assert_not_called()

    def test_deleted_source_photo_never_falls_back_to_a_different_image(self):
        first = self.photo()
        response = self.post('Add gold balloons.', source_photo_id=first.user_message_id,
            session_id=first.session_id, intent='revise')
        self.assertEqual(response.status_code, 202)
        ChatMessage.objects.filter(pk=first.user_message_id).update(is_deleted=True)
        self.assertTrue(run_once(heartbeat=False))
        job = AiRequest.objects.get(pk=response.json()['id'])
        self.assertEqual(job.state, 'failed')
        self.assertFalse(job.images.exists())
        self.provider.return_value.image_to_image.assert_not_called()

    def test_actual_photos_are_filtered_and_never_call_image_generation(self):
        wedding = GalleryCategory.objects.create(name='Wedding')
        birthday = GalleryCategory.objects.create(name='Birthday')
        image = GalleryImage.objects.create(category=wedding, image='gallery/wedding.png', caption='Garden wedding')
        GalleryImage.objects.create(category=birthday, image='gallery/birthday.png', caption='Birthday setup')
        GalleryImage.objects.create(category=wedding, image='gallery/hidden.png', caption='Hidden wedding', is_active=False)
        job = self.process('Show me actual wedding setups')
        self.assertEqual([card['id'] for card in job.result['gallery']], [image.pk])
        self.assertEqual(job.result['gallery'][0]['label'], 'Actual setup')
        self.provider.assert_not_called()
        history = self.client.get(reverse('chat_history'), {'session_id': job.session_id}).json()
        self.assertEqual(history['messages'][-1]['ai_gallery'][0]['id'], image.pk)
        image.is_active = False
        image.save(update_fields=['is_active'])
        self.assertEqual(self.client.get(reverse('ai_request_status', args=[job.pk])).json()['result']['gallery'], [])

    def test_real_gallery_and_ai_concept_remain_separate_in_a_mixed_request(self):
        category = GalleryCategory.objects.create(name='Birthday')
        GalleryImage.objects.create(category=category, image='gallery/real.png', caption='Actual birthday')
        job = self.process('Show actual setups and generate a birthday image')
        self.assertEqual(len(job.result['gallery']), 1)
        self.assertEqual(job.images.count(), 1)
        self.assertIn('Sample AI backdrop concept', job.result['response'])

    def test_budget_and_unknown_package_answers_do_not_invent_an_offer(self):
        budget = self.process('What packages are below PHP 3000?')
        self.assertIn('No active package matches', budget.result['response'])
        unknown = self.process('What is included in Package 99?')
        self.assertIn('not currently listed as active', unknown.result['response'])

    def test_specific_package_question_gets_the_requested_fact_first(self):
        price = self.process('Magkano ang Package 1-A?')
        self.assertEqual(price.result['response'], 'Package 1-A: PHP 4,799.00.')
        chair = self.process('Does Package 1-A include a chair?')
        self.assertIn('1 Celebrant Chair', chair.result['response'])
        self.assertNotIn('PHP', chair.result['response'])

    def test_explicit_date_wins_over_model_arguments_and_ambiguous_date_is_clarified(self):
        tomorrow = timezone.localdate()+timedelta(days=1)
        BlockedDate.objects.create(date=tomorrow, reason='Unavailable')
        self.plan = {'actions': ['availability'], 'args': {'start_date': '2099-01-01'}, 'updates': {}}
        job = self.process(f'Are you available on {tomorrow.isoformat()}?')
        self.assertIn('Unavailable', job.result['response'])
        self.assertNotIn('2099', job.result['response'])
        ambiguous = self.process('Available ba sa 5?')
        self.assertEqual(ambiguous.plan['actions'], ['clarify'])
        self.assertNotIn('Available**', ambiguous.result['response'])

    def test_date_answer_continues_the_requested_availability_check_and_handles_a_past_date(self):
        first = self.process('Check date availability')
        self.assertEqual(first.result['response'], DATE_QUESTION)
        self.assertEqual(first.plan['followup']['kind'], 'availability_date')
        past = (timezone.localdate()-timedelta(days=9)).strftime('%B %d %Y')
        second = self.process(past, session_id=first.session_id)
        self.assertEqual(second.plan['actions'], ['availability'])
        self.assertIn('has already passed', second.result['response'])
        self.assertNotIn(CLARIFY, second.result['response'])
        future = timezone.localdate()+timedelta(days=14)
        third = self.process(future.strftime('%B %d %Y'), session_id=first.session_id)
        self.assertIn(future.strftime('%B %d, %Y'), third.result['response'])
        self.assertNotIn('followup', third.plan)
        self.provider.assert_not_called()

    def test_ambiguous_date_reply_keeps_a_specific_question_until_the_date_is_complete(self):
        first = self.process('Available ba sa 5?')
        second = self.process('sa 5', session_id=first.session_id)
        self.assertEqual(second.result['response'], DATE_QUESTION)
        self.assertNotIn(CLARIFY, second.result['response'])
        third = self.process('December 5 2026', session_id=first.session_id)
        self.assertIn('December 05, 2026', third.result['response'])

    def test_legacy_generic_menu_accepts_ai_image_and_generates_only_after_details(self):
        old = self.previous_reply('october 14 2026', CLARIFY)
        selected = self.process('ai image', session_id=old.session_id)
        self.assertEqual(selected.result['response'], IMAGE_QUESTION)
        self.assertEqual(selected.plan['followup']['kind'], 'image_details')
        self.provider.return_value.text_to_image.assert_not_called()
        generated = self.process('Birthday with blue and silver balloons', session_id=old.session_id)
        self.assertEqual(generated.images.count(), 1)
        self.assertNotIn('followup', generated.plan)
        self.assertIn('Birthday', generated.plan['memory']['occasion'])
        self.assertIn('blue', self.provider.return_value.text_to_image.call_args.kwargs['prompt'])

    def test_short_date_answer_recovers_an_existing_stateless_date_question(self):
        old = self.previous_reply('Check date availability', DATE_QUESTION)
        job = self.process('December 14 2026', session_id=old.session_id)
        self.assertEqual(job.plan['actions'], ['availability'])
        self.assertIn('December 14, 2026', job.result['response'])
        self.provider.assert_not_called()

    def test_existing_generic_reply_after_a_date_does_not_lose_the_availability_context(self):
        old = self.previous_reply('Check date availability', DATE_QUESTION)
        message = ChatMessage.objects.create(session=old.session, sender=self.user, receiver=self.admin, message='october 14 2026')
        answer = ChatMessage.objects.create(session=old.session, sender=self.admin, receiver=self.user, message=CLARIFY)
        AiRequest.objects.create(user=self.user, session=old.session, user_message=message, assistant_message=answer,
            input_text=message.message, fingerprint=uuid.uuid4().hex, state='succeeded',
            plan={'actions': ['clarify'], 'brief_version': 0}, result={'response': CLARIFY}, finished_at=timezone.now())
        # Low-resolution clocks can give several messages the same timestamp.
        ChatMessage.objects.filter(session=old.session).update(sent_at=timezone.now())
        history = self.client.get(reverse('chat_history'), {'session_id': old.session_id}).json()['messages']
        self.assertEqual([item['id'] for item in history], list(
            ChatMessage.objects.filter(session=old.session).order_by('pk').values_list('pk', flat=True)))
        job = self.process('December 14 2026', session_id=old.session_id)
        self.assertEqual(job.plan['actions'], ['availability'])
        self.provider.assert_not_called()

    @override_settings(PAYMONGO_SECRET_KEY='test_checkout')
    def test_payment_methods_and_how_to_pay_are_answered_without_classifier_uncertainty(self):
        for question in ('Anong payment methods ang pwede?', 'How can I pay for my booking?'):
            with self.subTest(question=question):
                job = self.process(question)
                self.assertEqual(job.plan['actions'], ['payment_help'])
                self.assertIn('GCash', job.result['response'])
        self.provider.assert_not_called()

    def test_availability_of_a_payment_method_is_not_treated_as_a_calendar_question(self):
        self.answer = 'GCash is the enabled online payment method.'
        job = self.process('Is GCash available?')
        self.assertEqual(job.result['response'], self.answer)
        self.assertNotIn('availability', job.plan['actions'])
        self.assertNotIn('followup', job.plan)

    def test_generic_menu_in_a_text_draft_is_repaired_before_it_reaches_the_customer(self):
        self.answer = CLARIFY
        self.repaired = 'Service outside Cavite has additional distance charges.'
        self.verdicts = [False, True]
        job = self.process('Sa Cavite lang ba kayo nagse-service?')
        self.assertEqual(job.result['response'], self.repaired)
        self.assertEqual(job.metrics['quality']['repairs'], 1)
        self.assertNotIn(CLARIFY, job.assistant_message.message)

    def test_clear_service_questions_do_not_receive_a_menu_when_classifier_is_uncertain(self):
        self.plan = {'actions': ['clarify'], 'args': {}, 'updates': {}}
        for question, answer in (
            ('Sa Cavite lang ba kayo nagse-service?', 'Service outside Cavite has additional distance charges.'),
            ('What happens after I submit my booking?', 'Your request awaits admin approval before payment.')):
            with self.subTest(question=question):
                self.answer = answer
                job = self.process(question)
                self.assertEqual(job.result['response'], answer)
                self.assertTrue(job.metrics['quality']['checked'])
                self.assertNotIn(CLARIFY, job.assistant_message.message)
        self.provider.return_value.text_to_image.assert_not_called()

    def test_booking_hours_answer_uses_the_real_start_window_without_inventing_an_online_cutoff(self):
        job = self.process('hanggang anong oras kayo pwede tumanggap ng booking?')
        self.assertEqual(job.plan['actions'], ['booking_hours'])
        self.assertIn('before 6:00 PM', job.result['response'])
        self.assertIn('daily cutoff for submitting booking requests online is not specified', job.result['response'])
        self.assertNotIn('24', job.result['response'])
        self.assertNotIn(CLARIFY, job.result['response'])
        self.provider.assert_not_called()

    def test_malformed_classifier_output_still_gets_a_grounded_text_answer(self):
        self.plan = None
        self.answer = 'Event start times must be before 6:00 PM.'
        job = self.process('Can I change my event location after confirmation?')
        self.assertEqual(job.result['response'], self.answer)
        self.assertTrue(job.metrics['quality']['passed'])
        self.provider.return_value.text_to_image.assert_not_called()

    def test_topic_switch_clears_the_pending_date_instead_of_reinterpreting_the_question(self):
        first = self.process('Check date availability')
        self.plan = {'actions': ['clarify'], 'args': {}}
        self.answer = 'The online payment method is GCash.'
        second = self.process('meron ba kayong PayMaya?', session_id=first.session_id)
        self.assertEqual(second.result['response'], self.answer)
        self.assertNotIn('followup', second.plan)
        third = self.process('December 14 2026', session_id=first.session_id)
        self.assertNotIn('availability', third.plan['actions'])

    def test_asking_a_question_while_image_details_are_pending_never_spends_image_credits(self):
        for question, answer in (
                ('How many panels should a birthday backdrop have?', 'One panel can suit a compact birthday backdrop.'),
                ('Would blue work for a birthday?', 'Blue works well with silver for a birthday.'),
                ('Would blue work for a birthday', 'Blue works well with silver for a birthday.'),
                ('Birthday in blue?', 'Blue is a suitable birthday color. Would you like an image with that palette?')):
            with self.subTest(question=question):
                self.answer = answer
                first = self.process('ai image')
                second = self.process(question, session_id=first.session_id)
                self.assertEqual(second.result['response'], self.answer)
                self.assertNotIn('followup', second.plan)
        self.provider.return_value.text_to_image.assert_not_called()

    def test_acknowledgements_keep_the_specific_pending_question_without_generating(self):
        first = self.process('ai image')
        second = self.process('okay', session_id=first.session_id)
        self.assertEqual(second.result['response'], IMAGE_QUESTION)
        self.provider.return_value.text_to_image.assert_not_called()
        generated = self.process('Birthday in blue', session_id=first.session_id)
        self.assertEqual(generated.images.count(), 1)
        date = self.process('Check date availability')
        acknowledged = self.process('yes', session_id=date.session_id)
        self.assertEqual(acknowledged.result['response'], DATE_QUESTION)
        checked = self.process('December 14 2026', session_id=date.session_id)
        self.assertEqual(checked.plan['actions'], ['availability'])

    def test_image_opt_out_cancels_the_pending_generation(self):
        first = self.process('ai image')
        self.process("Don't generate an image. Suggest birthday colors instead.", session_id=first.session_id)
        self.plan = {'actions': ['generate']}
        last = self.process('Birthday', session_id=first.session_id)
        self.assertFalse(last.images.exists())
        self.provider.return_value.text_to_image.assert_not_called()

    def test_pending_image_choice_is_not_reused_after_reset_expiry_or_in_another_chat(self):
        for setup in ('reset', 'expired', 'other_chat'):
            with self.subTest(setup=setup):
                old = self.previous_reply('ai image', IMAGE_QUESTION, followup={'kind': 'image_details'},
                    age=timedelta(days=2) if setup == 'expired' else None)
                if setup == 'reset':
                    self.client.delete(reverse('ai_design_brief', args=[old.session_id]))
                job = self.process('Birthday', **({} if setup == 'other_chat' else {'session_id': old.session_id}))
                self.assertFalse(job.images.exists())
        self.provider.return_value.text_to_image.assert_not_called()

    def test_availability_respects_the_same_minimum_notice_as_the_booking_api(self):
        config = SiteSettings.load()
        config.booking_lead_time_days = 5
        config.save(update_fields=['booking_lead_time_days'])
        tomorrow = timezone.localdate()+timedelta(days=1)
        job = self.process('Available ba bukas?')
        self.assertIn('Unavailable', job.result['response'])
        self.assertIn('5 day(s)', job.result['response'])
        check = self.client.get(reverse('check_date_availability'), {'date': tomorrow.isoformat()})
        self.assertFalse(check.json()['available'])

    def test_customer_cannot_read_other_booking_or_payment_through_tools(self):
        foreign = Booking.objects.create(user=self.other, event_date=timezone.localdate()+timedelta(days=2),
            event_location='Private venue', total_price=12345, status='confirmed')
        Payment.objects.create(booking=foreign, amount=12345, transaction_ref='private', payment_method='gcash', payment_status='verified')
        for action in ('booking_status', 'payment_status'):
            self.plan = {'actions': [action], 'args': {'user_id': self.other.pk}, 'updates': {}}
            job = self.process(f'Check my booking #{foreign.pk} status')
            self.assertNotIn('12,345', job.result['response'])
            self.assertNotIn('confirmed', job.result['response'].lower())
            self.assertIn('No ', job.result['response'])

    def test_memory_reset_is_owned_and_fences_pending_updates(self):
        session = ChatSession.objects.create(user=self.user, design_brief={'theme': 'Garden'})
        response = self.post('Which colors work?', session_id=session.pk)
        job_id, token = claim_request()
        AiRequest.objects.filter(pk=job_id).update(plan={'memory': {'theme': 'Old'}, 'brief_version': 0})
        endpoint = reverse('ai_design_brief', args=[session.pk])
        self.assertEqual(self.client.delete(endpoint).status_code, 200)
        complete_request(job_id, token, {'text': 'Done'})
        session.refresh_from_db()
        self.assertEqual(session.design_brief, {})
        self.assertEqual(session.design_brief_version, 1)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(endpoint).status_code, 404)
        self.assertEqual(self.client.delete(endpoint).status_code, 404)

    def test_unapproved_actions_and_image_requests_are_not_executed(self):
        self.plan = {'actions': ['cancel_booking', 'execute_sql', 'generate'], 'args': {'url': 'http://example.invalid'}, 'updates': {}}
        job = self.process('What colors suit a wedding? Text only please.')
        self.assertEqual(job.plan['actions'], ['answer'])
        self.assertFalse(job.images.exists())
        self.provider.return_value.text_to_image.assert_not_called()

    def test_admin_metrics_are_private_and_do_not_claim_unreported_usage(self):
        job = self.process('Which colors work for a wedding?')
        response = self.client.get(reverse('ai_health'))
        self.assertEqual(response.status_code, 403)
        self.client.force_login(self.admin)
        response = self.client.get(reverse('ai_health'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'AI health')
        self.assertNotContains(response, job.input_text)
        self.assertContains(response, 'This is not the provider invoice')
        self.assertGreater(response.context['known_calls'], 0)
        self.assertIsNone(response.context['estimate'])
        self.assertLess(response.context['known_calls'], response.context['calls_count'])

    def test_literal_parsing_does_not_treat_a_question_as_the_customers_name(self):
        self.assertNotIn('name', extract_details('What does the name on the backdrop mean?'))
        self.assertEqual(extract_details('Display "Sofia" on the backdrop')['name'], 'Sofia')
        self.assertEqual(extract_details('navy blue and silver')['colors'], 'navy blue, silver')
        self.assertIsNone(requested_dates('Available ba sa 5?'))
