
import os
import django
from pathlib import Path

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Project.settings')
django.setup()

from app.views import build_dashboard_context
from django.test import RequestFactory
from django.contrib.auth import get_user_model

User = get_user_model()
request = RequestFactory().get('/dashboard/')

admin_user = User.objects.filter(role='admin').first()
if not admin_user:
    admin_user = User.objects.create_superuser('admin', 'admin@test.com', 'password123')
    admin_user.role = 'admin'
    admin_user.save()

request.user = admin_user

print("Testing dashboard context...")
context = build_dashboard_context(request)
print("✓ Dashboard context built!")
print(f"- Total bookings: {context.get('total_bookings')}")
print(f"- Total revenue: {context.get('total_revenue')}")
print(f"- Action queue total: {context.get('action_queue_total')}")
print(f"- Dashboard trend labels: {context.get('dashboard_trend_labels')}")
print("All tests passed!")
