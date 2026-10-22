"""Global saved-design allowance, enforced when creating a design."""
from django import forms
from django.db import transaction

from .models import SiteSettings, User, UserDesign


class DesignSettingsForm(forms.ModelForm):
    class Meta:
        model = SiteSettings
        fields = ['max_saved_designs']
        labels = {'max_saved_designs': 'Maximum saved designs per customer'}


def saved_design_usage(user, total=None):
    used = UserDesign.objects.filter(user=user).count() if total is None else total
    limit = SiteSettings.load().max_saved_designs
    return {'used': used, 'limit': limit, 'at_limit': used >= limit, 'remaining': max(0, limit - used)}


class DesignLimitReached(Exception):
    def __init__(self, usage):
        self.usage = usage
        super().__init__(
            f"You have reached the limit of {usage['limit']} saved designs. "
            "Remove unused designs in My Designs to make room. You can still edit your existing designs."
        )


def create_saved_design(*, user, **fields):
    # Serialize creates per customer, including requests from multiple browser tabs.
    # Count and insert must happen under the same lock; files are saved only after it passes.
    with transaction.atomic():
        User.objects.select_for_update().only('pk').get(pk=user.pk)
        usage = saved_design_usage(user)
        if usage['at_limit']:
            raise DesignLimitReached(usage)
        return UserDesign.objects.create(user=user, **fields)
