"""Theme selection follows the selected offers' Theme Decor inclusions."""
from .models import DesignOffer


def theme_decor_capabilities():
    from .views.common import normalize_package_part

    capabilities = {}
    offers = DesignOffer.objects.select_related('package', 'entrance', 'stand').prefetch_related(
        'requirements__category', 'inclusions__category')
    for offer in offers:
        allowed = any(row.category and row.category.builtin_key == 'theme_decor'
                      for row in (*offer.requirements.all(), *offer.inclusions.all()))
        key = normalize_package_part(offer.name)
        capabilities[key] = capabilities.get(key, False) or allowed
    return capabilities


def allows_booking_theme(package_type, capabilities=None):
    from .views.common import normalize_package_part

    if capabilities is None:
        capabilities = theme_decor_capabilities()
    configured = [capabilities[key] for part in (package_type or '').split('+')
                  if (key := normalize_package_part(part)) in capabilities]
    # Legacy bookings without a structured offer keep their existing theme rule.
    return any(configured) if configured else True
