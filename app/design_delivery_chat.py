"""Post a booking design in support chat without copying its uploaded image."""
from .models import ChatMessage, ChatSession, User


def post_design_delivery(delivery, *, revised=False):
    """Called inside the delivery transaction, after locking the booking."""
    existing = ChatMessage.objects.filter(design_delivery=delivery).first()
    if existing:
        return existing
    booking = delivery.booking
    # Serialize first-chat creation without blocking concurrent message foreign keys.
    customer = User.objects.select_for_update(no_key=True).get(pk=booking.user_id)
    session = (ChatSession.objects.select_for_update()
        .filter(user=customer, is_admin_support=True).exclude(status='ai')
        .order_by('-updated_at', '-pk').first())
    if session is None:
        session = ChatSession(user=customer, is_admin_support=True, title='Admin support')
    session.status = 'active_admin'
    session.assigned_admin = delivery.uploaded_by
    session.save()
    name = customer.first_name or customer.username
    text = (f'Hi {name}! Your {"updated design" if revised else "design"} for booking #{booking.pk} is ready. '
        'Please review the preview and reply here with any feedback or changes.')
    if delivery.caption:
        text += f'\n\nMessage from admin:\n{delivery.caption}'
    return ChatMessage.objects.create(session=session, sender=delivery.uploaded_by, receiver=customer,
        message=text, design_delivery=delivery, design_booking=booking, design_is_revision=revised)
