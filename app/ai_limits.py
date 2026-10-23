"""Shared AI budgets used at admission and immediately before image generation."""
from .request_protection import configured_rule, consume_rules


def reserve_admission(user, *, photo=False):
    subject = f'user:{user.pk}'
    rules = [configured_rule('ai_chat', subject), configured_rule('ai_chat_cooldown', subject)]
    if photo:
        rules.append(configured_rule('ai_analysis', subject))
    consume_rules(rules)


def reserve_images(user, count=1):
    subject = f'user:{user.pk}'
    consume_rules([configured_rule('ai_image_cooldown', subject),
                   configured_rule('ai_image_daily', subject, weight=count)])
