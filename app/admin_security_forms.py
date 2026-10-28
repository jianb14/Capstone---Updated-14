from django import forms
from .profile_forms import EditProfileForm


class AdminEmailForm(forms.Form):
    email = forms.EmailField(max_length=254)
    current_password = forms.CharField(strip=False, max_length=1024, widget=forms.PasswordInput)


class AdminInviteForm(EditProfileForm):
    email = forms.EmailField(max_length=254)
    current_password = forms.CharField(strip=False, max_length=1024, widget=forms.PasswordInput)
    resend_id = forms.UUIDField(required=False)


class AdminAcceptForm(forms.Form):
    password = forms.CharField(strip=False, min_length=8, max_length=1024, widget=forms.PasswordInput,
                              error_messages={'required': 'Create a password.', 'min_length': 'Use at least 8 characters.'})
    confirm_password = forms.CharField(strip=False, max_length=1024, widget=forms.PasswordInput,
                                      error_messages={'required': 'Confirm your password.'})

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('password') and cleaned.get('confirm_password') and cleaned['password'] != cleaned['confirm_password']:
            self.add_error('confirm_password', 'Passwords do not match.')
        return cleaned
