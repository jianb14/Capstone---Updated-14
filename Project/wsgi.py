"""
WSGI config for Project project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Project.settings')

application = get_wsgi_application()

# Auto-migrate and Collect Static on Vercel startup
from django.core.management import call_command
try:
    # Run database migrations
    call_command('migrate', '--noinput')
    # Collect static files
    call_command('collectstatic', '--noinput')
except Exception as e:
    print(f"Startup error: {e}")