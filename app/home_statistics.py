"""Public statistics shared by client pages and their admin previews."""
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Avg, Count, Q

from .models import Booking, Review


def get_customers_served():
    """Count each customer once, after at least one completed booking."""
    return Booking.objects.filter(status='completed').values('user_id').distinct().count()


def get_home_statistics():
    # Every valid review counts, including those not featured as testimonials.
    reviews = Review.objects.filter(rating__range=(1, 5)).aggregate(
        total=Count('pk'), average=Avg('rating'), positive=Count('pk', filter=Q(rating__gte=4)),
    )
    total = reviews['total']
    return {
        'events_styled': Booking.objects.filter(status='completed').count(),
        'review_count': total,
        'customer_rating': Decimal(str(reviews['average'])).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP) if total else None,
        'positive_reviews': (Decimal(reviews['positive']) * 100 / total).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP) if total else None,
    }
