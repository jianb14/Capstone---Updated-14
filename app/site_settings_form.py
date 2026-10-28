"""Validation for the single Site Settings save action."""
from django import forms
from django.core.validators import URLValidator, validate_email
from .models import SiteSettings


class SiteSettingsForm(forms.ModelForm):
    contact_email = forms.EmailField(required=False, max_length=255)
    shop_lat = forms.DecimalField(required=False, min_value=-90, max_value=90, max_digits=9, decimal_places=6)
    shop_lng = forms.DecimalField(required=False, min_value=-180, max_value=180, max_digits=9, decimal_places=6)

    class Meta:
        model = SiteSettings
        fields = ('site_name', 'contact_email', 'contact_phone', 'address', 'facebook_link', 'instagram_link',
                  'booking_lead_time_days', 'booking_payment_window_hours', 'booking_design_lead_hours',
                  'booking_change_cutoff_hours', 'booking_min_duration_hours', 'booking_included_hours',
                  'booking_max_duration_hours', 'booking_overtime_rate', 'email_notifications_enabled',
                  'admin_emails_for_notifications')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        definitions = {
            'site_name': ('ss_site_name', 'Business name', 'The business name shown on your website.'),
            'contact_email': ('ss_contact_email', 'Contact email', 'The public email customers can use to contact you.'),
            'contact_phone': ('ss_contact_phone', 'Contact phone', ''),
            'address': ('ss_address', 'Business address', 'Choose a suggestion or pin the shop on the map for distance estimates.'),
            'facebook_link': ('ss_facebook', 'Facebook URL', ''),
            'instagram_link': ('ss_instagram', 'Instagram URL', ''),
            'booking_lead_time_days': ('ss_lead_time', 'Minimum advance notice (days)', 'Enter 0 to allow same-day booking requests.'),
            'booking_payment_window_hours': ('ss_payment_window', 'Initial payment window (hours)', 'Time allowed after approval, capped at the event start.'),
            'booking_design_lead_hours': ('ss_design_lead', 'Design reminder threshold (hours)', 'A missing design becomes urgent this many hours before the event.'),
            'booking_change_cutoff_hours': ('ss_change_cutoff', 'Change request cutoff (hours)', 'Minimum notice before the event for a customer change request.'),
            'booking_min_duration_hours': ('ss_min_duration', 'Minimum duration (hours)', 'The shortest event duration a customer can book.'),
            'booking_included_hours': ('ss_included_hours', 'Included duration (hours)', 'Hours included in the package price before overtime starts.'),
            'booking_max_duration_hours': ('ss_max_duration', 'Maximum duration (hours)', 'The longest event duration a customer can book.'),
            'booking_overtime_rate': ('ss_overtime_rate', 'Overtime rate (PHP / hour)', 'Charged for each extra hour or fraction beyond the included duration.'),
            'admin_emails_for_notifications': ('ss_admin_emails', 'Alert recipients', 'Press Enter or comma to add an email. Leave empty to send no admin alert emails.'),
            'email_notifications_enabled': ('ss_notif_toggle', 'Email notifications', ''),
        }
        for name, (field_id, label, hint) in definitions.items():
            field = self.fields[name]
            field.label, field.help_text = label, hint
            field.widget.attrs.update({'id': field_id, 'aria-describedby': f'{field_id}_error {field_id}_help'})
        for name in ('shop_lat', 'shop_lng'):
            self.fields[name].widget = forms.HiddenInput(attrs={'id': f'ss_{name}'})
        self.fields['address'].widget.attrs['autocomplete'] = 'off'
        self.fields['admin_emails_for_notifications'].widget = forms.EmailInput(attrs={
            'id': 'ss_admin_emails', 'multiple': True, 'maxlength': 500,
            'autocomplete': 'off', 'autocapitalize': 'none', 'spellcheck': 'false',
            'placeholder': 'Add an email address',
            'aria-describedby': 'ss_admin_emails_error ss_admin_emails_help'})
        for name in ('booking_payment_window_hours', 'booking_design_lead_hours', 'booking_change_cutoff_hours'):
            self.fields[name].widget.attrs.update({'min': 1, 'max': 720})
        for name in ('booking_min_duration_hours', 'booking_included_hours', 'booking_max_duration_hours'):
            self.fields[name].widget.attrs.update({'min': 1, 'max': 168})
        self.fields['booking_overtime_rate'].widget.attrs['min'] = 0
        for name in ('facebook_link','instagram_link'):
            self.fields[name].validators.append(URLValidator(schemes=['http','https']))

    def clean_admin_emails_for_notifications(self):
        emails = [email.strip() for email in self.cleaned_data['admin_emails_for_notifications'].split(',') if email.strip()]
        for email in emails:
            try:
                validate_email(email)
            except forms.ValidationError:
                raise forms.ValidationError('Enter valid email addresses separated by commas.')
        unique = {}
        for email in emails:
            unique.setdefault(email.casefold(), email)
        result = ', '.join(unique.values())
        if len(result) > 500:
            raise forms.ValidationError('Keep the recipient list within 500 characters.')
        return result

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
