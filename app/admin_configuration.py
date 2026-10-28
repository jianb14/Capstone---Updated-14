"""Presentation and async responses for the single, atomic settings form."""
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from .site_settings_form import SiteSettingsForm


def settings_saved(request, settings_obj, message):
    if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
        return None
    return JsonResponse({'success': True, 'message': message,
        'updated_at': timezone.localtime(settings_obj.updated_at).strftime('%b %d, %Y · %I:%M %p'),
        'updated_by': request.user.get_full_name() or request.user.username})


def render_settings(request, context, *, status=200):
    origin = context.get('shop_origin') or ('', '')
    site = context.get('site_form') or SiteSettingsForm(instance=context['settings'], initial={
        'shop_lat': origin[0], 'shop_lng': origin[1]})
    context['site_form'] = site
    forms = (site, context['design_settings_form'], context['logistics_settings_form'])
    if status == 400 and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        errors = {name: list(messages) for form in forms for name, messages in form.errors.items()}
        return JsonResponse({'success': False, 'message': 'Check the highlighted fields. Nothing has been saved.',
                             'errors': errors}, status=400)
    design = context['design_settings_form']['max_saved_designs']
    design.field.widget.attrs.update({'id': 'ss_max_saved_designs', 'min': 1,
        'aria-describedby': 'ss_max_saved_designs_error ss_max_saved_designs_help'})
    context['settings_sections'] = [
        {'id': 'business-settings', 'title': 'Business Profile', 'icon': 'user',
         'description': 'Your public contact details and the starting point for delivery estimates.',
         'fields': [site[n] for n in ('site_name', 'contact_email', 'contact_phone', 'address')], 'map': True},
        {'id': 'logistics-settings', 'title': 'Logistics & Delivery', 'icon': 'logistics',
         'description': 'Set the service fee and distance charges for new booking quotes.',
         'fields': list(context['logistics_settings_form'])},
        {'id': 'design-settings', 'title': 'Design Settings', 'icon': 'design',
         'description': 'Control how many designs each customer can keep in their library.', 'fields': [design]},
        {'id': 'social-settings', 'title': 'Social Links', 'icon': 'link',
         'description': 'Help customers find your official social pages.',
         'fields': [site[n] for n in ('facebook_link', 'instagram_link')]},
        {'id': 'booking-settings', 'title': 'Booking Rules', 'icon': 'calendar',
         'description': 'Set booking deadlines and the notice customers need to give.',
         'fields': [site[n] for n in ('booking_lead_time_days', 'booking_payment_window_hours',
                                     'booking_design_lead_hours', 'booking_change_cutoff_hours')]},
        {'id': 'email-settings', 'title': 'Email Notifications', 'icon': 'mail',
         'description': 'Choose where new booking, payment and concern alerts are sent.',
         'fields': [site['admin_emails_for_notifications']], 'notifications': True},
        {'id': 'duration-settings', 'title': 'Booking Duration & Overtime', 'icon': 'clock',
         'description': 'Define the allowed event duration and any additional hourly charge.',
         'fields': [site[n] for n in ('booking_min_duration_hours', 'booking_included_hours',
                                     'booking_overtime_rate', 'booking_max_duration_hours')]},
    ]
    return render(request, 'admin/settings/admin_site_settings.html', context, status=status)
