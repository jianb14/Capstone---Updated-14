"""Trusted-console permission management; never grants superuser or framework-admin access."""
from django.contrib.auth.models import Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from app.models import AuditLog, User


class Command(BaseCommand):
    help = 'Grant or revoke invitation permission for an existing verified administrator.'

    def add_arguments(self, parser):
        parser.add_argument('email')
        parser.add_argument('--revoke', action='store_true')

    @transaction.atomic
    def handle(self, *args, **options):
        accounts = list(User.objects.select_for_update().filter(email__iexact=options['email'].strip(), deleted_at__isnull=True))
        if len(accounts) != 1:
            raise CommandError('Exactly one matching account is required.')
        user = accounts[0]
        if user.role != 'admin' or (not options['revoke'] and (not user.is_active or not user.email_verified)):
            raise CommandError('Granting permission requires an active, verified admin.')
        if user.is_superuser:
            raise CommandError('Superusers already have this permission. Manage their privileges through your trusted deployment console.')
        permission = Permission.objects.get(content_type__app_label='app', codename='invite_administrator')
        if options['revoke']:
            user.user_permissions.remove(permission)
            # Revoke explicitly granted group membership only through the trusted console.
            if user.groups.filter(permissions=permission).exists():
                raise CommandError('This permission also comes from a group. Remove that group assignment first; no changes were applied.')
        else:
            user.user_permissions.add(permission)
        AuditLog.objects.create(user=user, action=f'Admin invitation permission {"revoked" if options["revoke"] else "granted"} through trusted console.')
        self.stdout.write(self.style.SUCCESS('Admin invitation permission updated.'))
