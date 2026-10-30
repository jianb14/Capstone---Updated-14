"""Customer design attachments sent through the application's email backend."""
import io
import logging

from django.conf import settings
from django.core.mail import EmailMessage
from PIL import Image

logger = logging.getLogger(__name__)


def send_design_delivery_email(delivery, image_content):
    """Send the validated upload bytes, without fetching a public storage URL."""
    booking = delivery.booking
    recipient = (booking.user.email or '').strip()
    if not recipient:
        logger.warning('Design email has no recipient for delivery %s.', delivery.pk)
        return False

    try:
        with Image.open(io.BytesIO(image_content)) as image:
            extension, content_type = {
                'JPEG': ('jpg', 'image/jpeg'),
                'PNG': ('png', 'image/png'),
                'WEBP': ('webp', 'image/webp'),
            }[image.format]
        name = booking.user.first_name.strip() or booking.user.username
        note = delivery.caption or (
            'Your event design is ready. Please see the attached file and let us '
            'know if you would like any changes.'
        )
        message = EmailMessage(
            subject=f'Your Design - Order #{booking.pk} | Balloorina',
            body=f'Hi {name},\n\nOrder #{booking.pk}\n\n{note}\n\nThank you,\nBalloorina',
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient],
        )
        message.attach(
            f'order-{booking.pk}-design-{delivery.pk}.{extension}',
            image_content,
            content_type,
        )
        if message.send(fail_silently=False) == 1:
            return True
    except Exception:
        # Provider exceptions can contain credentials, recipients or message data.
        logger.warning('Design email acceptance is unconfirmed for delivery %s.', delivery.pk)
        return False
    logger.warning('Design email was not accepted for delivery %s.', delivery.pk)
    return False
