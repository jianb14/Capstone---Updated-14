from django.contrib import admin
from .models import User

@admin.register(User)
class AccountAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self,request):
        # Retired transaction owners are not restorable customer accounts.
        return super().get_queryset(request).filter(deleted_at__isnull=True)
