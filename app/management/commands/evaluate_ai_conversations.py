"""Synthetic routing regression cases; --live performs text inference only."""
import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from app.ai_conversation import choose_plan
from app.ai_answering import answer_mode
from app.ai_conversation import normalize
from app.ai_intent import wants_generation


class NeedsLive(Exception):
    pass


class Command(BaseCommand):
    help = 'Check synthetic English/Taglish conversations and follow-ups. --live uses text credits; never generates images.'

    def add_arguments(self, parser):
        parser.add_argument('--live', action='store_true')
        parser.add_argument('--offset', type=int, default=0)
        parser.add_argument('--limit', type=int, default=None)

    def handle(self, *args, **options):
        from app import ai_conversation
        cases = json.loads((Path(settings.BASE_DIR)/'app/ai_conversation_cases.json').read_text(encoding='utf-8'))
        start = max(0, options['offset'])
        cases = cases[start:] if options['limit'] is None else cases[start:start+max(0, options['limit'])]
        actual_json = ai_conversation._json_call
        def inference(*args, **kwargs):
            if kwargs.get('purpose') == 'memory':
                return {}  # Routing-only evaluation; memory extraction has its own tests.
            if not options['live']:
                raise NeedsLive()
            return actual_json(*args, **kwargs)
        passed = failed = deferred = 0
        with patch('app.ai_conversation._json_call', side_effect=inference):
            for case in cases:
                reference = bool(case.get('reference'))
                generated = wants_generation(case['message'], has_reference=reference)
                job = SimpleNamespace(input_text=case['message'], plan={'requested_intent': 'auto'},
                    kind='generate' if generated else 'advice')
                try:
                    plan = choose_plan(job, case.get('history', []), case.get('brief', {}), has_reference=reference,
                        followup=case.get('followup', {}), deadline=time.monotonic()+settings.AI_TEXT_RESPONSE_TIMEOUT_SECONDS)
                except NeedsLive:
                    deferred += 1
                    continue
                ok = 'actions' not in case or set(plan['actions']) == set(case['actions'])
                mode = answer_mode(normalize(case['message']), plan['actions'])
                ok = ok and ('answer_mode' not in case or mode == case['answer_mode'])
                passed += ok
                failed += not ok
                if not ok:
                    self.stdout.write(f"FAIL {case['id']}: actions={plan['actions']}, answer_mode={mode}; expected {case.get('actions', 'any safe action')}, {case.get('answer_mode', 'any mode')}")
        self.stdout.write(f'Passed: {passed}; failed: {failed}; requires --live: {deferred}. No images generated.')
        if failed:
            raise CommandError('Conversation routing regression detected.')
