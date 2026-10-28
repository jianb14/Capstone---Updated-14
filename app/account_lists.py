"""Shared bounded page sizes for customer account tables."""


def account_page_size(request):
    # Keep account tables compact, including when a query string is edited manually.
    return 4 if request.GET.get('per_page') == '4' else 8
