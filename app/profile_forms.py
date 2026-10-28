import re

from django import forms

from .models import User


class EditProfileForm(forms.Form):
    first_name = forms.CharField(max_length=User._meta.get_field('first_name').max_length,
        error_messages={'required': 'First name is required.'})
    last_name = forms.CharField(max_length=User._meta.get_field('last_name').max_length,
        error_messages={'required': 'Last name is required.'})
    phone_number = forms.CharField(max_length=User._meta.get_field('phone_number').max_length,
        error_messages={'required': 'Phone number is required.'})

    def clean_phone_number(self):
        phone = self.cleaned_data['phone_number']
        digits = re.sub(r'[\s\-\(\)\+]', '', phone)
        if not digits.isdigit():
            raise forms.ValidationError('Phone number must contain only digits.')
        if not 10 <= len(digits) <= 15:
            raise forms.ValidationError('Phone number must be between 10 and 15 digits.')
        return phone
