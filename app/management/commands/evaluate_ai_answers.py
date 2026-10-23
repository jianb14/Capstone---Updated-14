"""End-to-end text quality checks; routing alone cannot test answer specificity."""
import json
import re
import time
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from app.ai_answering import answer_mode
from app.ai_conversation import choose_plan, normalize, relevant_reply, run_tools


class Command(BaseCommand):
    help = 'Evaluate synthetic specific questions with real text inference; no images, account reads or saved messages.'

    def add_arguments(self, parser):
        parser.add_argument('--live', action='store_true')
        parser.add_argument('--offset', type=int, default=0)
        parser.add_argument('--limit', type=int, default=None)
        parser.add_argument('--show-replies', action='store_true')

    def handle(self, *args, **options):
        if not options['live']:
            raise CommandError('Use --live to evaluate replies. This uses text inference credits and never generates images.')
        cases = json.loads((Path(settings.BASE_DIR)/'app/ai_answer_cases.json').read_text(encoding='utf-8'))
        start = max(0, options['offset'])
        cases = cases[start:] if options['limit'] is None else cases[start:start+max(0, options['limit'])]
        passed = failed = 0
        for case in cases:
            # No authenticated actor, real customer input, job or chat is used.
            job = SimpleNamespace(input_text=case['message'], plan={'requested_intent': 'advice'},
                kind='advice', user=None, user_id=None)
            history = case.get('history', [])
            deadline = time.monotonic()+settings.AI_TEXT_RESPONSE_TIMEOUT_SECONDS
            plan = choose_plan(job, history, {}, has_reference=False, deadline=deadline)
            mode = answer_mode(normalize(job.input_text), plan['actions'])
            if any(action in plan['actions'] for action in ('generate', 'edit')):
                # A diagnostic run must never perform paid images or read accounts.
                failed += 1
                self.stdout.write(f'FAIL {case["id"]}: unexpected action; no tool executed.')
                continue
            plan['actions'] = [action for action in plan['actions'] if action not in ('booking_status', 'payment_status')]
            plan['answer_mode'] = mode
            facts, _cards = run_tools(plan, job, {})
            reply, quality = (facts, {'passed': False})
            if mode == 'focused':
                reply, quality = relevant_reply(job, history, {}, facts, lambda *a, **kw: None, deadline, actions=plan['actions'])
            matches = sum(bool(re.search(pattern, reply, re.I | re.S)) for pattern in case['patterns'])
            forbidden = any(re.search(pattern, reply, re.I | re.S) for pattern in case.get('forbidden', []))
            ok = quality.get('passed') is True and matches >= case['minimum_matches'] and not forbidden
            passed += ok
            failed += not ok
            self.stdout.write(f'{"PASS" if ok else "FAIL"} {case["id"]}: {matches}/{len(case["patterns"])} detail checks; mode={mode}.')
            if options['show_replies']:
                self.stdout.write(json.dumps({'reply': reply}, ensure_ascii=True))
            self.stdout.flush()
        self.stdout.write(f'Passed: {passed}; failed: {failed}. No images generated or chat messages saved.')
        if failed:
            raise CommandError('Answer specificity regression detected.')
