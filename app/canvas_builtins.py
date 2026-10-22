"""Persistent catalog identities for protected, built-in canvas tools."""
from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError
from django.db.models.signals import pre_delete, pre_save
from django.dispatch import receiver

from .models import CanvasAsset, CanvasCategory

STYRO_NAME = 'styrofoam_name'
BUILTIN_MESSAGE = 'Styrofoam Name is a built-in preset. Its asset and counting category cannot be edited, hidden, or deleted. Manage its inclusion and quantity in the offer editor.'


@receiver(pre_delete, sender=CanvasAsset)
@receiver(pre_delete, sender=CanvasCategory)
def protect_builtin_deletion(sender, instance, **kwargs):
    if instance.builtin_key:
        raise ProtectedError(BUILTIN_MESSAGE, [instance])


@receiver(pre_save, sender=CanvasAsset)
@receiver(pre_save, sender=CanvasCategory)
def protect_builtin_identity(sender, instance, using, **kwargs):
    if not instance.pk:
        return
    stored = sender.objects.using(using).filter(pk=instance.pk).first()
    if not stored or not stored.builtin_key:
        return
    fields = ['builtin_key', 'is_active', 'available_package', 'available_entrance', 'available_stand']
    fields += ['category_id', 'item_type', 'label', 'image', 'static_path'] if sender is CanvasAsset else ['name', 'is_balloon']
    if any(getattr(instance, field) != getattr(stored, field) for field in fields):
        raise ValidationError(BUILTIN_MESSAGE)
