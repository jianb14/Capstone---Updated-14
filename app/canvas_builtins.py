"""Persistent catalog identities for protected, built-in canvas tools."""
from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError
from django.db.models.signals import post_delete, pre_delete, pre_save
from django.dispatch import receiver

from .models import CanvasAsset, CanvasCategory, CanvasUpload

STYRO_NAME = 'styrofoam_name'
THEME_DECOR = 'theme_decor'
THEME_MESSAGE = 'Theme Decor is a built-in category for customer uploads. Manage its inclusion and quantity in the offer editor.'
BUILTIN_MESSAGE = 'Styrofoam Name is a built-in preset. Its asset and counting category cannot be edited, hidden, or deleted. Manage its inclusion and quantity in the offer editor.'


def builtin_message(key):
    return THEME_MESSAGE if key == THEME_DECOR else BUILTIN_MESSAGE


@receiver(post_delete, sender=CanvasUpload)
def queue_deleted_upload(sender, instance, **kwargs):
    from .account_deletion import queue_account_media
    if instance.image:
        queue_account_media([instance.image.name])


@receiver(pre_delete, sender=CanvasAsset)
@receiver(pre_delete, sender=CanvasCategory)
def protect_builtin_deletion(sender, instance, **kwargs):
    if instance.builtin_key:
        raise ProtectedError(builtin_message(instance.builtin_key), [instance])


@receiver(pre_save, sender=CanvasAsset)
@receiver(pre_save, sender=CanvasCategory)
def protect_builtin_identity(sender, instance, using, **kwargs):
    if sender is CanvasAsset and instance.category_id and instance.category.builtin_key == THEME_DECOR:
        raise ValidationError(THEME_MESSAGE)
    if not instance.pk:
        return
    stored = sender.objects.using(using).filter(pk=instance.pk).first()
    if not stored or not stored.builtin_key:
        return
    fields = ['builtin_key', 'is_active', 'available_package', 'available_entrance', 'available_stand']
    fields += ['category_id', 'item_type', 'label', 'image', 'static_path'] if sender is CanvasAsset else ['name', 'is_balloon']
    if any(getattr(instance, field) != getattr(stored, field) for field in fields):
        raise ValidationError(builtin_message(stored.builtin_key))
