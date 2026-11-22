import json
import logging
from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import DatabaseError, transaction
from django.http import FileResponse, Http404, JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST
from django.utils import timezone

from ..canvas_uploads import category_accepts_uploads, normalize_image, normalized_colors, positive_id, upload_payload
from ..design_validation import offer_is_ready
from ..models import CanvasUpload, DesignOffer, UserDesign
from ..background_removal import remove_image_background, BackgroundRemovalUnavailable

logger = logging.getLogger(__name__)


@login_required
@require_POST
def canvas_upload_preview(request):
    if request.user.role != 'customer':
        return JsonResponse({'message':'Sign in with a customer account to preview uploads.'}, status=403)
    offer = DesignOffer.objects.filter(pk=positive_id(request.POST.get('design_offer_id'))).first()
    if not offer or not offer_is_ready(offer):
        return JsonResponse({'message':'Choose an available design offer before uploading.'}, status=400)
    rule = offer.requirements.select_related('category').filter(category_id=positive_id(request.POST.get('category_id'))).first()
    if not rule or not category_accepts_uploads(rule.category, offer.kind):
        return JsonResponse({'message':'This category does not accept uploads in the selected offer.'}, status=400)
    file = request.FILES.get('image')
    if file and file.size > 10 * 1024**2:
        return JsonResponse({'message':'Choose an image no larger than 10 MB.'}, status=413)
    try:
        content, _ = normalize_image(file)
        png = remove_image_background(content.read())
    except ValidationError as error:
        return JsonResponse({'message':error.messages[0]}, status=400)
    except BackgroundRemovalUnavailable:
        return JsonResponse({'message':"We couldn't remove this background. Try again or use the original photo."}, status=503)
    response = HttpResponse(png, content_type='image/png')
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def _save_upload(upload, content, user, *, replaces=None):
    try:
        upload.image.save(content.name, content, save=False)
        with transaction.atomic():
            upload.save()
            if replaces is not None:
                CanvasUpload.objects.filter(pk=replaces.pk, owner=user, library_removed_at__isnull=True).update(library_removed_at=timezone.now())
    except (DatabaseError, OSError):
        if upload.image and upload.image._committed:
            from ..account_deletion import queue_account_media
            queue_account_media([upload.image.name])
        logger.exception('Canvas image upload failed for customer %s', user.pk)
        return JsonResponse({'message': "We couldn't save this image. Keep the designer open and try again."}, status=503)
    return JsonResponse({'upload': upload_payload(upload)}, status=201)


@login_required
@require_POST
def canvas_upload_create(request):
    if request.user.role != 'customer':
        return JsonResponse({'message': 'Sign in with a customer account to upload design items.'}, status=403)
    offer = DesignOffer.objects.filter(pk=positive_id(request.POST.get('design_offer_id'))).first()
    if not offer or not offer_is_ready(offer):
        return JsonResponse({'message': 'Choose an available design offer before uploading.'}, status=400)
    rule = offer.requirements.select_related('category').filter(category_id=positive_id(request.POST.get('category_id'))).first()
    if not rule or not category_accepts_uploads(rule.category, offer.kind):
        return JsonResponse({'message': 'This category does not accept uploads in the selected offer.'}, status=400)
    design_id = request.POST.get('design_id')
    if design_id:
        get_object_or_404(UserDesign, pk=positive_id(design_id), user=request.user)
    file = request.FILES.get('image')
    if file and file.size > 10 * 1024**2:
        return JsonResponse({'message': 'Choose an image no larger than 10 MB.'}, status=413)
    try:
        colors = normalized_colors(json.loads(request.POST.get('colors', '[]')))
        if rule.category.is_balloon and offer.max_balloon_colors and not colors:
            raise ValidationError('Choose the intended balloon colors before uploading.')
        content, (width, height) = normalize_image(file)
    except (ValueError, RecursionError):
        return JsonResponse({'message': 'Choose balloon colors from the palette.'}, status=400)
    except ValidationError as exc:
        return JsonResponse({'message': exc.messages[0]}, status=400)

    label = request.POST.get('label', '').strip() or Path(file.name).stem or 'Custom upload'
    upload = CanvasUpload(owner=request.user, category=rule.category, label=label[:150], colors=colors if rule.category.is_balloon else [],
                          width=width, height=height)
    return _save_upload(upload, content, request.user)


@login_required
@require_POST
def canvas_upload_colors(request, id):
    if request.user.role != 'customer':
        return JsonResponse({'message': 'Sign in with a customer account to edit balloon colors.'}, status=403)
    original = get_object_or_404(CanvasUpload.objects.select_related('category'), pk=id, owner=request.user)
    offer = DesignOffer.objects.filter(pk=positive_id(request.POST.get('design_offer_id'))).first()
    if not offer or not offer_is_ready(offer):
        return JsonResponse({'message': 'Choose an available design offer before editing colors.'}, status=400)
    if (not original.category.is_balloon or not offer.requirements.filter(category=original.category).exists()
            or not category_accepts_uploads(original.category, offer.kind)):
        return JsonResponse({'message': 'This photo is not a balloon item in the selected offer.'}, status=400)
    if request.POST.get('design_id'):
        get_object_or_404(UserDesign, pk=positive_id(request.POST['design_id']), user=request.user)
    try:
        colors = normalized_colors(json.loads(request.POST.get('colors', '[]')))
        if not colors:
            raise ValidationError('Choose at least 1 balloon color.')
    except (ValueError, RecursionError):
        return JsonResponse({'message': 'Choose balloon colors from the palette.'}, status=400)
    except ValidationError as exc:
        return JsonResponse({'message': exc.messages[0]}, status=400)
    if colors == original.colors:
        return JsonResponse({'upload': upload_payload(original)})
    try:
        with original.image.open('rb') as image:
            content = ContentFile(image.read(), name=Path(original.image.name).name)
    except OSError:
        return JsonResponse({'message': "We couldn't load this photo. Keep your design open and try again."}, status=503)
    # Independent bytes and metadata keep other saved designs and booking references unchanged.
    revised = CanvasUpload(owner=request.user, category=original.category, label=original.label,
                          colors=colors, width=original.width, height=original.height)
    return _save_upload(revised, content, request.user, replaces=original)


@login_required
@require_POST
def canvas_upload_remove(request, id):
    if request.user.role != 'customer':
        return JsonResponse({'message': 'Sign in with a customer account to manage uploads.'}, status=403)
    upload = get_object_or_404(CanvasUpload, pk=id, owner=request.user)
    CanvasUpload.objects.filter(pk=upload.pk, library_removed_at__isnull=True).update(library_removed_at=timezone.now())
    return JsonResponse({'removed': upload.pk})


@login_required
@require_GET
def canvas_upload_image(request, id):
    permitted = CanvasUpload.objects.filter(owner=request.user)
    if request.user.role == 'admin':
        permitted = CanvasUpload.objects.filter(booking_designs__isnull=False)
    upload = get_object_or_404(permitted.distinct(), pk=id)
    try:
        image = upload.image.open('rb')
    except FileNotFoundError:
        raise Http404
    except OSError:
        return JsonResponse({'message': "We couldn't load this image. Please try again."}, status=503)
    response = FileResponse(image, content_type='image/png' if upload.image.name.lower().endswith('.png') else 'image/jpeg')
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
