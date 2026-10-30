"""Validation for the editable payment setting shown in the admin workspace."""
from django import forms


class PaymentSettingsForm(forms.Form):
    downpayment_percent = forms.IntegerField(
        min_value=1, max_value=100,
        error_messages={
            'required': 'Enter the required downpayment percentage.',
            'invalid': 'Enter a whole number from 1 to 100.',
            'min_value': 'Enter a whole number from 1 to 100.',
            'max_value': 'Enter a whole number from 1 to 100.',
        },
    )
