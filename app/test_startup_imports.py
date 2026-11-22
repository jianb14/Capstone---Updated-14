"""Development workers must not race URL imports during Django startup."""
import subprocess
import sys

from django.conf import settings
from django.test import SimpleTestCase


class StartupImportTests(SimpleTestCase):
    def test_background_view_import_does_not_break_runserver_urls(self):
        probe = r'''
import importlib, os, sys, threading, time
from unittest.mock import patch
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Project.settings')
sys.argv = ['manage.py', 'runserver', '--noreload']
workers, errors = [], []
def import_views():
    try:
        importlib.import_module('app.views.common')
    except Exception as error:
        errors.append(str(error))
def start_import_only_worker():
    worker = threading.Thread(target=import_views, daemon=True)
    workers.append(worker)
    worker.start()
    deadline = time.monotonic() + 3
    while 'app.views' not in sys.modules and time.monotonic() < deadline:
        time.sleep(.001)
with patch('app.deadline_worker.start_deadline_worker', side_effect=start_import_only_worker), patch('app.ai_worker.start_ai_worker'):
    import django
    django.setup()
    try:
        importlib.import_module('app.urls')
    except Exception as error:
        errors.append(str(error))
    for worker in workers:
        worker.join(timeout=10)
        if worker.is_alive():
            errors.append('View imports did not complete.')
assert not errors, errors
from app.views import chat_api
assert callable(chat_api)
print('Concurrent runserver URL imports passed.')
'''
        result = subprocess.run([sys.executable, '-c', probe], cwd=settings.BASE_DIR,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Concurrent runserver URL imports passed.', result.stdout)
