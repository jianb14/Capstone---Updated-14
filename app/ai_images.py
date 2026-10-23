"""Resolve a customer's generated image to owned storage, never an arbitrary path."""
from html import escape
from pathlib import PurePosixPath
from urllib.parse import urlparse

from django.conf import settings
from django.core.files.storage import default_storage

from .models import AiGeneratedImage, ChatMessage


def owned_image_name(user, image_url):
    if not isinstance(image_url, str) or len(image_url) > 2000:
        raise ValueError('Invalid image reference')
    filename = PurePosixPath(urlparse(image_url).path).name
    if not filename:
        raise ValueError('Invalid image reference')
    for artifact in AiGeneratedImage.objects.filter(request__user=user, image__endswith=filename)[:5]:
        if artifact.image.url == image_url:
            return artifact.image.name
    # Old locally stored chat images have no artifact row. They must still be in
    # this customer's own chat and have a canonical ai_generated/ storage name.
    if image_url.startswith(settings.MEDIA_URL):
        name = image_url[len(settings.MEDIA_URL):]
        path = PurePosixPath(name)
        if (len(path.parts) == 2 and path.parts[0] == 'ai_generated' and '..' not in path.parts
                and '\\' not in name and not path.is_absolute() and default_storage.url(name) == image_url
                and ChatMessage.objects.filter(session__user=user, receiver=user,
                    message__contains=escape(image_url)).exists()):
            return name
    raise ValueError('This design is not available in your chats.')
