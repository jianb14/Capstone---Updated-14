"""Expose only public business settings, cached for one rendered request."""
from django import template
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator, validate_email

from app.models import SiteSettings

register = template.Library()
PUBLIC_FIELDS = ('site_name','contact_email','contact_phone','address','facebook_link','instagram_link')


@register.simple_tag(takes_context=True)
def public_site_settings(context):
    request = context.get('request')
    if request is not None and hasattr(request,'_public_business_settings'):
        return request._public_business_settings
    site = SiteSettings.load()
    data = {name:getattr(site,name) for name in PUBLIC_FIELDS}
    # Older saves bypassed form validation. Never render an unsafe URL as a link.
    for name in ('facebook_link','instagram_link'):
        try:
            URLValidator(schemes=['http','https'])(data[name])
        except ValidationError:
            data[name] = ''
    if data['contact_email']:
        try:
            validate_email(data['contact_email'])
        except ValidationError:
            data['contact_email'] = ''
    if request is not None:
        request._public_business_settings = data
    return data
