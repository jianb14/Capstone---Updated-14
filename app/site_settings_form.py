"""Validation for the single Site Settings save action."""
from django import forms
from .models import SiteSettings


class SiteSettingsForm(forms.ModelForm):
    shop_lat = forms.DecimalField(required=False, min_value=-90, max_value=90, max_digits=9, decimal_places=6)
    shop_lng = forms.DecimalField(required=False, min_value=-180, max_value=180, max_digits=9, decimal_places=6)

    class Meta:
        model = SiteSettings
        fields = ('site_name', 'contact_email', 'contact_phone', 'address', 'facebook_link', 'instagram_link',
                  'booking_lead_time_days', 'booking_payment_window_hours', 'booking_design_lead_hours',
                  'booking_change_cutoff_hours', 'booking_min_duration_hours', 'booking_included_hours',
                  'booking_max_duration_hours', 'booking_overtime_rate', 'email_notifications_enabled',
                  'admin_emails_for_notifications')

    def clean(self):
        data = super().clean()
        if (data.get('shop_lat') is None) != (data.get('shop_lng') is None):
            self.add_error('shop_lat', 'Select a complete shop pin on the map.')
        for name in ('booking_payment_window_hours', 'booking_design_lead_hours', 'booking_change_cutoff_hours'):
            value = data.get(name)
            if value is not None and not 1 <= value <= 720:
                self.add_error(name, 'Enter between 1 and 720 hours.')
        for name in ('booking_min_duration_hours', 'booking_included_hours', 'booking_max_duration_hours'):
            value = data.get(name)
            if value is not None and not 1 <= value <= 168:
                self.add_error(name, 'Enter between 1 and 168 hours.')
        maximum = data.get('booking_max_duration_hours')
        for name in ('booking_min_duration_hours', 'booking_included_hours'):
            if maximum is not None and data.get(name) is not None and data[name] > maximum:
                self.add_error(name, 'This cannot exceed the maximum duration.')
        rate = data.get('booking_overtime_rate')
        if rate is not None and rate < 0:
            self.add_error('booking_overtime_rate', 'Enter a rate of 0 or more.')
        return data
