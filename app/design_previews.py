"""Small card images cached separately from the original downloadable image."""
import hashlib
import io

from django.core.cache import cache
from PIL import Image, ImageOps


def preview_version(name):
    # Saved thumbnails receive a new UUID filename whenever their image changes.
    return hashlib.sha256(('card-webp-640-v1:' + name).encode()).hexdigest()[:24]


def preview_bytes(thumbnail):
    key = 'design-preview:' + preview_version(thumbnail.name)
    data = cache.get(key)
    if data is None:
        with thumbnail.open('rb') as source, Image.open(source) as original:
            image = ImageOps.exif_transpose(original)
            image.thumbnail((640, 640), Image.Resampling.LANCZOS)
            image = image.convert('RGBA' if 'A' in image.getbands() or 'transparency' in image.info else 'RGB')
            output = io.BytesIO()
            image.save(output, 'WEBP', quality=82, method=4)
            data = output.getvalue()
        cache.set(key, data, 86400)
    return data
