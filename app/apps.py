from django.apps import AppConfig


class AppConfig(AppConfig):
    name = 'app'

    def ready(self):
        import os
        import sys
        if 'runserver' in sys.argv and (os.environ.get('RUN_MAIN') == 'true' or '--noreload' in sys.argv):
            from .deadline_worker import start_deadline_worker
            start_deadline_worker()
