"""Private category images, stable placement identity and draft cleanup."""
import io
import re
from datetime import timedelta

from django.core import signing
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from PIL import Image, ImageOps, UnidentifiedImageError

from .payment_storage import PaymentProofStorage


class CanvasUploadStorage(PaymentProofStorage):
    # Paths remain recognizable to the durable private-media deletion queue.
    cloud_folder = 'private_canvas_uploads'
    local_folder = 'canvas_uploads/'
    file_label = 'canvas image'

    def url(self, name):
        raise ValueError('Canvas images are served through canvas_upload_image.')


def category_accepts_uploads(category, kind=None):
    from .canvas_builtins import STYRO_NAME, THEME_DECOR
    if not category.is_active or category.builtin_key == STYRO_NAME:
        return False
    if category.builtin_key == THEME_DECOR:
        return True
    assets = category.assets.filter(is_active=True).exclude(item_type='i-text')
    if kind:
        from .design_validation import eligible_assets
        from .models import DesignOffer
        assets = eligible_assets(DesignOffer(kind=kind)).filter(category=category).exclude(item_type='i-text')
    return assets.exists()


def normalized_colors(colors):
    if not isinstance(colors, list):
        raise ValidationError('Choose balloon colors from the palette.')
    result = []
    for value in colors:
        if not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
            raise ValidationError('Choose balloon colors from the palette.')
        result.append(value.lower())
    return list(dict.fromkeys(result))


def normalize_image(file):
    if not file:
        raise ValidationError('Choose a JPEG, PNG, or WebP image.')
    try:
        with Image.open(file) as original:
            if original.format not in ('JPEG', 'PNG', 'WEBP'):
                raise ValidationError('Choose a JPEG, PNG, or WebP image.')
            if original.width * original.height > 32_000_000:
                raise ValidationError('Choose an image with no more than 32 megapixels.')
            original.load()
            image = ImageOps.exif_transpose(original)
            transparent = 'A' in image.getbands() or 'transparency' in image.info
            image = image.convert('RGBA' if transparent else 'RGB')
            image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
            image.info.clear()
            result = io.BytesIO()
            fmt = 'PNG' if transparent else 'JPEG'
            image.save(result, format=fmt, quality=90)
            return ContentFile(result.getvalue(), name='image.' + fmt.lower()), image.size
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValidationError("We couldn't read this image. Choose a valid JPEG, PNG, or WebP file.") from exc


def upload_token(upload):
    return signing.Signer(salt='canvas-upload-v1').sign_object(
        [upload.pk, upload.owner_id, upload.category_id, upload.image.name])


def upload_payload(upload):
    return {'id': upload.pk, 'token': upload_token(upload),
            'src': reverse('canvas_upload_image', args=[upload.pk]),
            'category_id': upload.category_id, 'category': upload.category.name,
            'label': upload.label, 'colors': upload.colors, 'width': upload.width, 'height': upload.height,
            'in_library': upload.library_removed_at is None}


def positive_id(value):
    if isinstance(value, (str, int)) and str(value).isascii() and str(value).isdigit() and len(str(value)) <= 19:
        parsed = int(value)
        if 0 < parsed < 2**63:
            return parsed
    return None


def owned_uploads(ids, owner):
    from .models import CanvasUpload
    valid_ids = {pk for value in ids if (pk := positive_id(value)) is not None}
    return CanvasUpload.objects.filter(owner_id=getattr(owner, 'pk', owner), pk__in=valid_ids).select_related('category')


def visible_placements(objects, *, include_hidden=False):
    """Flatten ordinary Fabric groups while retaining single signed SVG placements."""
    stack = list(reversed(objects))
    while stack:
        obj = stack.pop()
        if isinstance(obj, dict):
            if obj.get('_isArtboard') or obj.get('_isBgImage') or obj.get('_designSource') == 'reference':
                continue
            if not include_hidden and (obj.get('visible') is False or any(obj.get(field, 1) == 0 for field in ('opacity', 'scaleX', 'scaleY'))):
                continue
            if (obj.get('type') == 'group' and isinstance(obj.get('objects'), list)
                    and not any(obj.get(key) for key in ('_assetId', '_uploadId', '_designSource', '_isColorableSVG'))):
                stack.extend(reversed(obj['objects']))
                continue
        yield obj


def resolve_upload_object(obj, uploads_by_id):
    if not isinstance(obj, dict) or obj.get('_designSource') != 'upload' or obj.get('type') != 'image':
        return None
    upload = uploads_by_id.get(positive_id(obj.get('_uploadId')))
    if not upload or positive_id(obj.get('_categoryId')) != upload.category_id or obj.get('_assetId'):
        return None
    token = obj.get('_uploadToken')
    if (isinstance(token, str) and constant_time_compare(token, upload_token(upload))
            and obj.get('src') == reverse('canvas_upload_image', args=[upload.pk])):
        return upload
    return None


def purge_orphan_uploads(limit=100):
    from .models import CanvasUpload
    expired = CanvasUpload.objects.filter(library_removed_at__lt=timezone.now() - timedelta(hours=24))
    candidates = list(expired.filter(designs__isnull=True, booking_designs__isnull=True)
                      .order_by('pk').values_list('pk', flat=True)[:limit])
    removed = 0
    for pk in candidates:
        with transaction.atomic():
            upload = expired.select_for_update().filter(pk=pk).first()
            if upload and not upload.designs.exists() and not upload.booking_designs.exists():
                upload.delete()
                removed += 1
    return removed
