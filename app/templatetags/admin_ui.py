from django import template

from ..admin_navigation import admin_breadcrumbs as build_breadcrumbs

register = template.Library()


@register.simple_tag(takes_context=True)
def admin_breadcrumbs(context):
    return build_breadcrumbs(context['request'])
