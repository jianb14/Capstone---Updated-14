"""Private new payment proofs; historical default-storage files stay readable."""
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage, Storage, default_storage
from django.utils.deconstruct import deconstructible


@deconstructible
class PaymentProofStorage(Storage):
    def _local(self):
        return FileSystemStorage(location=settings.PAYMENT_PROOF_ROOT)

    def _cloud_options(self):
        config = settings.CLOUDINARY_STORAGE
        return {key.lower():config.get(key) for key in ('CLOUD_NAME', 'API_KEY', 'API_SECRET')}

    def _save(self, name, content):
        extension = Path(name).suffix.lower()
        if settings.PAYMENT_PROOF_USE_CLOUDINARY:
            import cloudinary.uploader
            from cloudinary.exceptions import Error
            try:
                result = cloudinary.uploader.upload(content, resource_type='image', type='authenticated',
                    public_id=f'private_payment_receipts/{uuid4().hex}', **self._cloud_options())
            except Error as error:
                raise OSError('Private payment storage is unavailable.') from error
            return f"private/cloudinary/{result['public_id']}.{result['format']}"
        filename = self._local().save(f'{uuid4().hex}{extension}', content)
        return 'private/local/'+filename

    def _open(self, name, mode='rb'):
        if name.startswith('private/local/'):
            return self._local().open(name.removeprefix('private/local/'), mode)
        if name.startswith('private/cloudinary/'):
            import cloudinary.utils
            import requests
            public_id = name.removeprefix('private/cloudinary/')
            url, _ = cloudinary.utils.cloudinary_url(public_id, type='authenticated', resource_type='image',
                sign_url=True, secure=True, **self._cloud_options())
            try:
                response = requests.get(url, timeout=20)
                response.raise_for_status()
            except requests.RequestException as error:
                raise OSError('Private payment proof is unavailable.') from error
            return ContentFile(response.content, name=name)
        return default_storage.open(name, mode)

    def url(self, name):
        raise ValueError('Payment proofs must be retrieved through the authorized payment_proof view.')

    def exists(self, name):
        if name.startswith('private/local/'):
            return self._local().exists(name.removeprefix('private/local/'))
        # New uploads always get a fresh UUID; do not probe public media/CDNs.
        return False

    def delete(self, name):
        if name.startswith('private/local/'):
            return self._local().delete(name.removeprefix('private/local/'))
        if name.startswith('private/cloudinary/'):
            import cloudinary.uploader
            public_id = str(Path(name.removeprefix('private/cloudinary/')).with_suffix('')).replace('\\', '/')
            return cloudinary.uploader.destroy(public_id, type='authenticated', resource_type='image', **self._cloud_options())
        return default_storage.delete(name)


def payment_proof_storage():
    return PaymentProofStorage()
