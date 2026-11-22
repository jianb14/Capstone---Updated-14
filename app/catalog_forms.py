"""Validated forms for gallery and canvas catalog dialogs."""
from django import forms

from .models import CanvasAsset, CanvasCategory, GalleryCategory, GalleryImage, Package

KINDS = (('package', 'Packages'), ('entrance', 'Entrance arches'), ('stand', 'Welcome stands'))
MAX_INTEGER = 2147483647


class MultipleImagesInput(forms.FileInput):
    allow_multiple_selected = True


class ImageUpload(forms.ImageField):
    def clean(self, data, initial=None):
        result = super().clean(data, initial)
        if result and hasattr(result, 'size') and result.size > 10 * 1024 * 1024:
            raise forms.ValidationError('Choose an image smaller than 10 MB.')
        return result


class MultipleImages(ImageUpload):
    widget = MultipleImagesInput

    def clean(self, data, initial=None):
        values = list(data) if isinstance(data, (list, tuple)) else [data] if data else []
        if not values:
            raise forms.ValidationError('Choose at least one image.')
        if len(values) > 4:
            raise forms.ValidationError('Choose up to 4 images at a time.')
        return [super(MultipleImages, self).clean(value, initial) for value in values]


class CatalogForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.prefix = None
        for name, field in self.fields.items():
            field.widget.attrs.update({'id': f'catalog_{name}', 'aria-describedby': f'catalog_error_{name}'})
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.update({'data-admin-select': '', 'aria-label': field.label})
                if hasattr(field, 'empty_label'):
                    field.empty_label = 'Choose a category'
            if isinstance(field, forms.IntegerField):
                field.min_value = 0 if name in ('order', 'sort_order') else 1
                field.max_value = MAX_INTEGER
                field.widget.attrs.update(min=field.min_value, max=MAX_INTEGER)
                if name in ('order', 'sort_order'):
                    field.required = False
            if isinstance(field.widget, forms.Textarea):
                field.widget.attrs['rows'] = 3
            if field.required:
                field.error_messages['required'] = f'{field.label} is required.'

    def clean(self):
        values = super().clean()
        for name in ('order', 'sort_order', 'width', 'height'):
            value = values.get(name)
            if name in self.fields and name in ('order', 'sort_order') and value is None and name not in self.errors:
                value = values[name] = getattr(self.instance, name, 0)
            minimum = 0 if name in ('order', 'sort_order') else 1
            if value is not None and not minimum <= value <= MAX_INTEGER:
                self.add_error(name, f'Enter a whole number between {minimum} and {MAX_INTEGER}.')
        return values


class GalleryCategoryForm(CatalogForm):
    class Meta:
        model = GalleryCategory
        fields = ('name', 'order')
        labels = {'name': 'Category name', 'order': 'Display order'}

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if GalleryCategory.objects.filter(name__iexact=name).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('A gallery category with this name already exists.')
        return name


class GalleryPackageChoiceField(forms.ModelChoiceField):
    def to_python(self, value):
        if isinstance(value, Package):
            value = value.pk
        if value not in self.empty_values:
            text = str(value)
            if not text.isdecimal() or len(text) > 19 or int(text) > 2**63 - 1:
                raise forms.ValidationError(self.error_messages['invalid_choice'], code='invalid_choice', params={'value':value})
        return super().to_python(value)

    def label_from_instance(self, obj):
        return obj.name + (' (inactive)' if not obj.is_active else '')


class GalleryImageForm(CatalogForm):
    image = ImageUpload(required=False, widget=forms.FileInput(attrs={'accept': 'image/*'}))
    package = GalleryPackageChoiceField(label='Package', queryset=Package.objects.none(), required=False)

    class Meta:
        model = GalleryImage
        fields = ('category', 'package', 'caption', 'image', 'is_active')
        widgets = {'caption': forms.Textarea(attrs={'maxlength': 255})}
        labels = {'category': 'Category', 'caption': 'Caption', 'is_active': 'Visible in gallery'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            del self.fields['image']
            self.fields['images'] = MultipleImages(label='Photos', widget=MultipleImagesInput(attrs={
                'accept': 'image/*', 'id': 'catalog_images', 'aria-describedby': 'catalog_error_images'}))
        self.fields['category'].queryset = GalleryCategory.objects.order_by('order', 'name')
        from django.db.models import Q
        self.fields['package'].queryset = Package.objects.filter(
            Q(is_active=True) | Q(pk=self.instance.package_id)).order_by('name', 'pk')
        self.fields['package'].empty_label = 'No specific package'
        self.fields['package'].help_text = 'Optional. Applies to every photo in this upload.' if not self.instance.pk else 'Optional. Photos without a package appear under All Projects.'


class AvailabilityForm(CatalogForm):
    available_for = forms.MultipleChoiceField(label='Available for', choices=KINDS,
        widget=forms.CheckboxSelectMultiple, error_messages={'required': 'Select at least one design type.'})

    def __init__(self, *args, kind='package', **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['available_for'].initial = [key for key, _ in KINDS if getattr(self.instance, 'available_' + key)] if self.instance.pk else [kind]

    def save(self, commit=True):
        instance = super().save(commit=False)
        for key, _ in KINDS:
            setattr(instance, 'available_' + key, key in self.cleaned_data['available_for'])
        if commit:
            instance.save()
        return instance


class CanvasCategoryForm(AvailabilityForm):
    class Meta:
        model = CanvasCategory
        fields = ('name', 'order', 'is_active', 'is_balloon')
        labels = {'name': 'Category name', 'order': 'Display order', 'is_active': 'Active category',
            'is_balloon': 'Uses the shared balloon color limit'}

    def clean(self):
        values = super().clean()
        if self.instance.pk:
            for key, label in KINDS:
                if key not in values.get('available_for', []) and self.instance.assets.filter(**{'available_' + key: True}).exists():
                    self.add_error('available_for', f'Remove {label.lower()} availability from this category’s assets first.')
        return values


class CanvasAssetForm(AvailabilityForm):
    image = ImageUpload(required=False, widget=forms.FileInput(attrs={'accept': 'image/*'}))

    class Meta:
        model = CanvasAsset
        fields = ('label', 'category', 'image', 'width', 'height', 'sort_order', 'is_active')
        labels = {'label': 'Asset name', 'category': 'Category', 'width': 'Default width (px)',
            'height': 'Default height (px)', 'sort_order': 'Display order', 'is_active': 'Active asset'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['image'].required = not self.instance.pk

    def clean(self):
        values = super().clean()
        category = values.get('category')
        if category:
            for key in values.get('available_for', []):
                if not getattr(category, 'available_' + key):
                    self.add_error('available_for', 'Choose a category available for every selected design type.')
                    break
        return values


FORMS = {'gallery-category': GalleryCategoryForm, 'gallery-image': GalleryImageForm,
    'canvas-category': CanvasCategoryForm, 'canvas-asset': CanvasAssetForm}
