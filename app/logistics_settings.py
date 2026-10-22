"""Validation for global logistics rates; the business form owns the shop pin."""
from decimal import Decimal
from django import forms
from .models import ServiceChargeConfig


class LogisticsSettingsForm(forms.ModelForm):
    class Meta:
        model = ServiceChargeConfig
        fields = ('amount', 'free_radius_km', 'per_km_rate', 'max_fee_cap', 'notes')
        labels = {
            'amount': 'Cavite base fee (PHP)',
            'free_radius_km': 'Included distance outside Cavite (km)',
            'per_km_rate': 'Outside-Cavite rate per additional km (PHP)',
            'max_fee_cap': 'Maximum total fee (PHP)',
            'notes': 'What the fee includes',
        }
        help_texts = {
            'amount': 'Venues within Cavite pay this base fee.',
            'free_radius_km': 'Measured from the business address and shop pin below, in a straight line.',
            'per_km_rate': 'Outside Cavite: add this rate for each km beyond the included distance, rounded up, with a minimum of 1 billable km.',
            'max_fee_cap': 'Enter 0 for no cap. The base fee is always retained.',
            'notes': 'Shown to customers alongside the distance and pricing explanation.',
        }
        widgets = {'notes': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.required = True
            field.widget.attrs.update({'id': f'ss_logistics_{name}', 'aria-describedby': f'ss_logistics_{name}_help ss_logistics_{name}_error'})
            if name != 'notes':
                field.min_value = Decimal('0')
                field.max_value = Decimal('1000') if name == 'free_radius_km' else Decimal('99999999.99')
                field.widget.attrs.update({'min': '0', 'max': str(field.max_value), 'step': '0.01'})

    def clean(self):
        data = super().clean()
        for name in ('amount', 'free_radius_km', 'per_km_rate', 'max_fee_cap'):
            value = data.get(name)
            maximum = Decimal('1000') if name == 'free_radius_km' else Decimal('99999999.99')
            if value is not None and (not value.is_finite() or value < 0 or value > maximum):
                self.add_error(name, f'Enter an amount between 0 and {maximum}.')
        return data
