"""Read-only review reporting and validated filters for the admin workspace."""
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Q

from .models import Review

FEATURED_REVIEW_LIMIT = 4


def review_summary():
    reviews = Review.objects.all()
    valid = reviews.filter(rating__range=(1, 5))
    summary = valid.aggregate(average=Avg('rating'), rated_count=Count('pk'))
    total = reviews.count()
    counts = dict(valid.values_list('rating').annotate(count=Count('pk')))
    return {
        'total_reviews': total,
        'avg_rating': summary['average'],
        'rated_count': summary['rated_count'],
        'unrated_count': total - summary['rated_count'],
        'featured_count': reviews.filter(is_testimonial=True).count(),
        'featured_limit': FEATURED_REVIEW_LIMIT,
        'rating_distribution': [
            {'star': star, 'count': counts.get(star, 0),
             'pct': round(counts.get(star, 0) * 100 / summary['rated_count'], 1) if summary['rated_count'] else 0}
            for star in range(5, 0, -1)
        ],
    }


def build_review_context(params):
    search = (params.get('search') or '').strip()[:150]
    rating = params.get('rating', '')
    if rating not in ('', '1', '2', '3', '4', '5'):
        rating = ''
    sort = params.get('sort', '-created_at')
    if sort not in ('-created_at', 'created_at', '-rating', 'rating'):
        sort = '-created_at'
    featured = params.get('featured', '')
    if featured not in ('', 'featured', 'regular'):
        featured = ''
    per_page = 4 if params.get('per_page') == '4' else 8
    reviews = Review.objects.select_related('user', 'booking').prefetch_related('images')
    if search:
        # Separate words let a full name match first and last name fields together.
        for word in search.split():
            match = (Q(user__first_name__icontains=word) | Q(user__last_name__icontains=word)
                     | Q(user__username__icontains=word) | Q(user__email__icontains=word)
                     | Q(comment__icontains=word) | Q(booking__event_type__icontains=word)
                     | Q(booking__package_type__icontains=word))
            identifier = word.lstrip('#')
            if identifier.upper().startswith('REV-'):
                identifier = identifier[4:]
            if identifier.isascii() and identifier.isdigit() and len(identifier) <= 18:
                match |= Q(pk=int(identifier))
            reviews = reviews.filter(match)
    if rating:
        reviews = reviews.filter(rating=int(rating))
    if featured:
        reviews = reviews.filter(is_testimonial=featured == 'featured')
    tie_breaker = 'pk' if sort in ('created_at', 'rating') else '-pk'
    page = Paginator(reviews.order_by(sort, tie_breaker), per_page).get_page(params.get('page'))
    return {
        **review_summary(),
        'reviews': page, 'per_page': per_page,
        'search_query': search, 'rating_filter': rating,
        'sort_filter': sort, 'featured_filter': featured,
        'has_filters': bool(search or rating or featured),
    }
