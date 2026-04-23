from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from .models import ChatModerationState, User
from .services import analyze_text_for_moderation, evaluate_chat_moderation, get_current_ban_status


class ChatModerationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="moderation_user",
            password="testpass123",
            role="customer",
            email="moderation@example.com",
        )

    def test_detects_obfuscated_profanity(self):
        result = analyze_text_for_moderation("t4ngina ka")
        self.assertTrue(result["is_violation"])
        self.assertEqual(result["violation_type"], "profanity")

    def test_does_not_flag_harmless_substring(self):
        result = analyze_text_for_moderation("competition is healthy")
        self.assertFalse(result["is_violation"])

    def test_educational_context_is_not_flagged(self):
        result = analyze_text_for_moderation("What is the meaning of 'gago'?")
        self.assertFalse(result["is_violation"])

    def test_strike_escalation_to_one_hour_ban(self):
        first = evaluate_chat_moderation(self.user, "g4go ka")
        self.assertIsNotNone(first)
        self.assertTrue(first["is_warning"])
        self.assertEqual(first["strike_count"], 1)
        self.assertFalse(first["is_banned"])

        second = evaluate_chat_moderation(self.user, "b0b0 ka")
        self.assertIsNotNone(second)
        self.assertTrue(second["is_warning"])
        self.assertEqual(second["strike_count"], 2)
        self.assertFalse(second["is_banned"])

        third = evaluate_chat_moderation(self.user, "t4ngina mo")
        self.assertIsNotNone(third)
        self.assertTrue(third["is_warning"])
        self.assertTrue(third["is_banned"])
        self.assertGreaterEqual(third["ban_remaining_seconds"], 3590)

    def test_active_ban_blocks_next_message(self):
        evaluate_chat_moderation(self.user, "gago ka")
        evaluate_chat_moderation(self.user, "bobo ka")
        evaluate_chat_moderation(self.user, "tanga ka")

        blocked = evaluate_chat_moderation(self.user, "hello there")
        self.assertIsNotNone(blocked)
        self.assertTrue(blocked["is_banned"])
        self.assertEqual(blocked["moderation_action"], "ban_active")

    def test_ban_expiry_resets_user(self):
        evaluate_chat_moderation(self.user, "gago ka")
        evaluate_chat_moderation(self.user, "bobo ka")
        evaluate_chat_moderation(self.user, "tanga ka")

        state = ChatModerationState.objects.get(user=self.user)
        state.banned_until = timezone.now() - timedelta(seconds=1)
        state.save(update_fields=["banned_until"])

        post_expiry = evaluate_chat_moderation(self.user, "hello")
        self.assertIsNone(post_expiry)

        state.refresh_from_db()
        self.assertIsNone(state.banned_until)
        self.assertIsNotNone(state.last_ban_ended_at)

    def test_get_current_ban_status_clears_expired_ban(self):
        evaluate_chat_moderation(self.user, "gago ka")
        evaluate_chat_moderation(self.user, "bobo ka")
        evaluate_chat_moderation(self.user, "tanga ka")

        state = ChatModerationState.objects.get(user=self.user)
        state.banned_until = timezone.now() - timedelta(seconds=1)
        state.last_ban_ended_at = None
        state.save(update_fields=["banned_until", "last_ban_ended_at"])

        status = get_current_ban_status(self.user)
        self.assertFalse(status["is_banned"])
        self.assertEqual(status["ban_remaining_seconds"], 0)

        state.refresh_from_db()
        self.assertIsNone(state.banned_until)
        self.assertIsNotNone(state.last_ban_ended_at)
