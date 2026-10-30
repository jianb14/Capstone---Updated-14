from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def account_page_url(context, key, number, tab=''):
    query = context['request'].GET.copy()
    for transient in ('open_edit', 'booking_id', 'payment_id', 'concern_id', 'modal', 'from_notif'):
        if transient == 'booking_id' and key == 'request_page' and tab == 'requests':
            continue
        query.pop(transient, None)
    query[key] = str(number)
    if tab:
        query['tab'] = tab
    return '?' + query.urlencode()


@register.simple_tag
def account_page_range(page):
    return list(page.paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1))
