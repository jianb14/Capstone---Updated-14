"""Shared validation for QR settings and customer proofs."""
from io import BytesIO
from pathlib import Path
import re
from uuid import uuid4

from PIL import Image
from django import forms
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import Q
from django.db import IntegrityError, transaction
from django.utils import timezone


def normalize_gcash_reference(value):
    return re.sub(r'[\s-]', '', value or '').upper()


def active_reference_payments(reference):
    from .models import Payment
    active = Payment.objects.exclude(payment_status='rejected')
    legacy_ids = [pk for pk, value in active.filter(gcash_reference_key__isnull=True)
        .exclude(gcash_reference_number='').values_list('pk', 'gcash_reference_number').iterator()
        if normalize_gcash_reference(value) == reference]
    return active.filter(Q(gcash_reference_key=reference) | Q(pk__in=legacy_ids))


def recipient_token(config):
    return signing.dumps({'id':config.pk, 'name':config.gcash_name, 'number':config.gcash_number,
        'qr':config.qr_code_image.name, 'instructions':config.instructions}, salt='gcash-recipient', compress=True)


def clean_payment_image(upload):
    if upload.size > 5 * 1024 * 1024:
        raise forms.ValidationError('Upload a PNG or JPEG image no larger than 5 MB.')
    try:
        upload.seek(0)
        image = Image.open(upload)
        if image.format not in ('PNG', 'JPEG') or image.width * image.height > 12000000:
            raise ValueError()
        image.load()
        output = BytesIO()
        fmt = image.format
        image.save(output, format=fmt)
        if output.tell() > 5 * 1024 * 1024:
            raise ValueError()
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise forms.ValidationError('Upload a valid PNG or JPEG image, up to 5 MB and 12 megapixels.') from error
    suffix = 'png' if fmt == 'PNG' else 'jpg'
    # Re-encoding strips metadata and trailing file content from customer uploads.
    stem = re.sub(r'[^a-zA-Z0-9_-]', '', Path(upload.name).stem)[:32] or 'payment'
    return SimpleUploadedFile(f'{stem}-{uuid4().hex[:12]}.{suffix}', output.getvalue(), content_type=f'image/{"jpeg" if suffix == "jpg" else "png"}')


class GCashProofForm(forms.Form):
    recipient_token = forms.CharField(widget=forms.HiddenInput)
    gcash_reference_number = forms.CharField(max_length=100, label='GCash transaction reference')
    gcash_sender_name = forms.CharField(max_length=255, label='Sender name on the transaction')
    gcash_paid_at = forms.DateTimeField(label='Transaction date and time', widget=forms.DateTimeInput(attrs={'type':'datetime-local'}))
    receipt_image = forms.ImageField(label='Payment screenshot (PNG or JPEG, up to 5 MB)',
        widget=forms.ClearableFileInput(attrs={'accept':'image/png,image/jpeg'}))
    refund_ack = forms.BooleanField(label='Payment terms')

    def __init__(self, *args, config=None, **kwargs):
        self.config = config
        super().__init__(*args, **kwargs)
        if config and config.is_ready:
            self.initial['recipient_token'] = recipient_token(config)
        self.fields['gcash_reference_number'].widget.attrs.update({'placeholder':'Enter your GCash reference', 'autocomplete':'off'})
        self.fields['gcash_sender_name'].widget.attrs.update({'placeholder':'Name on the transaction', 'autocomplete':'name'})
        for name in ('gcash_reference_number', 'gcash_sender_name', 'gcash_paid_at'):
            if self.is_bound and self[name].errors:
                self.fields[name].widget.attrs['aria-describedby'] = f'{self[name].auto_id}_errors'

    def clean_recipient_token(self):
        return self._recipient(self.cleaned_data['recipient_token'])

    def _recipient(self, token):
        try:
            recipient = signing.loads(token or '', salt='gcash-recipient', max_age=48*60*60)
            if not self.config or recipient.get('id') != self.config.pk or not recipient.get('name') or not recipient.get('qr'):
                raise signing.BadSignature()
        except signing.BadSignature as error:
            raise forms.ValidationError('Payment details changed or expired. Contact our team if you have already paid; otherwise refresh before paying.') from error
        return recipient

    @property
    def payment_recipient(self):
        try:
            return self._recipient(self['recipient_token'].value())
        except forms.ValidationError:
            return None

    @property
    def payment_qr_url(self):
        recipient = self.payment_recipient
        return self.config.qr_code_image.storage.url(recipient['qr']) if recipient else ''

    def clean_gcash_reference_number(self):
        reference = normalize_gcash_reference(self.cleaned_data['gcash_reference_number'])
        if not re.fullmatch(r'[A-Z0-9]{6,100}', reference):
            raise forms.ValidationError('Enter the transaction reference shown in GCash (6–100 letters or numbers).')
        if active_reference_payments(reference).exists():
            raise forms.ValidationError('This GCash reference has already been submitted. Contact our team if you need help.')
        return reference

    def clean_gcash_paid_at(self):
        paid_at = self.cleaned_data['gcash_paid_at']
        if paid_at > timezone.now():
            raise forms.ValidationError('The transaction time cannot be in the future.')
        return paid_at

    def clean_receipt_image(self):
        return clean_payment_image(self.cleaned_data['receipt_image'])

    def save(self, *, booking, amount, payment_type, change_request=None):
        from .models import Payment
        data = self.cleaned_data
        recipient = data['recipient_token']
        try:
            with transaction.atomic():
                return Payment.objects.create(booking=booking, change_request=change_request,
                    applied_to_booking=change_request is None, amount=amount, payment_type=payment_type,
                    payment_method='gcash', payment_status='pending', transaction_ref=uuid4().hex[:16].upper(),
                    gcash_reference_number=data['gcash_reference_number'], gcash_reference_key=data['gcash_reference_number'],
                    gcash_sender_name=data['gcash_sender_name'], gcash_paid_at=data['gcash_paid_at'],
                    gcash_recipient_name=recipient['name'], gcash_recipient_number=recipient['number'],
                    receipt_image=data['receipt_image'], received_at=timezone.now())
        except IntegrityError as error:
            raise ValidationError('This GCash reference has already been submitted. Contact our team before paying again.') from error
        except OSError as error:
            raise ValidationError('We could not save your proof. Keep your transaction reference and try uploading again; do not make another payment.') from error


class PaymentSettingsForm(forms.Form):
    gcash_name = forms.CharField(max_length=255, required=False, label='Recipient / merchant name')
    gcash_number = forms.CharField(max_length=100, required=False, label='Account number (if applicable)')
    instructions = forms.CharField(max_length=2000, required=False,
        widget=forms.Textarea(attrs={'rows':3, 'placeholder':'Add any instructions customers should follow when paying.'}), label='Payment instructions')
    qr_code_image = forms.ImageField(required=False, label='Official merchant QR (PNG or JPEG, up to 5 MB)')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, placeholder, error_id in (
            ('gcash_name', 'Name shown in GCash', 'pmNameError'),
            ('gcash_number', 'Account number, if used', 'pmAccountError'),
            ('instructions', '', 'pmInstructionsError'),
        ):
            if placeholder:
                self.fields[name].widget.attrs['placeholder'] = placeholder
            if self.is_bound and self[name].errors:
                self.fields[name].widget.attrs.update({'aria-invalid':'true', 'aria-describedby':error_id})

    def clean_qr_code_image(self):
        image = self.cleaned_data.get('qr_code_image')
        return clean_payment_image(image) if image else None

    downpayment_percent = forms.IntegerField(
        min_value=1, max_value=100,
        error_messages={
            'required': 'Enter the required downpayment percentage.',
            'invalid': 'Enter a whole number from 1 to 100.',
            'min_value': 'Enter a whole number from 1 to 100.',
            'max_value': 'Enter a whole number from 1 to 100.',
        },
    )
