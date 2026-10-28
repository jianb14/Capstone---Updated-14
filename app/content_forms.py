"""Field validation shared by the public-page content editors."""
from django import forms
from django.core.validators import URLValidator

from .catalog_forms import ImageUpload, MAX_INTEGER


LABELS = {
    'hero_label': 'Eyebrow label', 'hero_title': 'Main heading',
    'hero_subheadline': 'Introduction', 'hero_subtitle': 'Introduction',
    'occasion_chips': 'Occasions', 'why_choose_title': 'Section heading',
    'why_choose_subtitle': 'Section introduction', 'how_it_works_label': 'Eyebrow label',
    'how_it_works_title': 'Section heading', 'how_it_works_title_accent': 'Highlighted heading text',
    'faq_title': 'Section heading', 'faq_subtitle': 'Section introduction',
    'cta_title': 'Call to action heading', 'cta_subtitle': 'Call to action introduction',
    'support_hours': 'Support hours per day', 'story_label': 'Eyebrow label',
    'story_title': 'Story heading', 'story_paragraph_1': 'First paragraph',
    'story_paragraph_2': 'Second paragraph', 'story_points': 'Story highlights',
    'story_image': 'Story photo', 'mission_label': 'Eyebrow label',
    'mission_title': 'Mission heading', 'mission_paragraph_1': 'First paragraph',
    'mission_paragraph_2': 'Second paragraph', 'mission_image': 'Mission photo',
    'values_title': 'Section heading', 'values_subtitle': 'Section introduction',
    'journey_title': 'Section heading', 'journey_subtitle': 'Section introduction',
    'display_order': 'Display order', 'is_active': 'Visible on the website',
    'icon_class': 'Icon', 'caption': 'Date or milestone label',
    'features': 'Service inclusions', 'best_for': 'Best suited for',
    'attachment_label': 'Attachment link text', 'attachment_url': 'Attachment URL',
    'intro': 'Introduction', 'heading': 'Heading', 'body': 'Content',
}
ICONS = (
    ('fas fa-star', 'Star'), ('fas fa-gem', 'Diamond'), ('fas fa-palette', 'Palette'),
    ('fas fa-clock', 'Clock'), ('far fa-clock', 'Clock outline'),
    ('fas fa-wand-magic-sparkles', 'Magic wand'), ('fas fa-comments', 'Conversation'),
    ('fas fa-leaf', 'Leaf'), ('fas fa-box', 'Package'), ('fas fa-mobile-alt', 'Phone'),
    ('fas fa-calendar-alt', 'Calendar'), ('fas fa-trophy', 'Trophy'),
    ('fas fa-shield-alt', 'Shield'), ('fas fa-heart', 'Heart'),
    ('fas fa-check-circle', 'Check circle'), ('fas fa-users', 'People'),
    ('fas fa-lightbulb', 'Light bulb'), ('fas fa-bolt', 'Lightning'),
)


class ContentForm(forms.ModelForm):
    def __init__(self, *args, policy=False, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in list(self.fields.items()):
            field.label = LABELS.get(name, field.label)
            if isinstance(field, forms.ImageField):
                self.fields[name] = field = ImageUpload(label=field.label, required=False,
                    widget=forms.FileInput(attrs={'accept': 'image/*'}))
                if getattr(self.instance, name, None):
                    self.fields['remove_' + name] = forms.BooleanField(
                        label='Remove current photo', required=False)
            if name == 'attachment_url':
                self.fields[name] = field = forms.URLField(label=field.label, required=False,
                    max_length=255, widget=forms.URLInput, validators=[URLValidator(schemes=['http', 'https'])])
            if name == 'icon_class':
                choices = list(ICONS)
                current = getattr(self.instance, name, '')
                if current and current not in dict(choices):
                    choices.append((current, 'Current icon'))
                self.fields[name] = field = forms.ChoiceField(label='Icon', choices=choices,
                    required=False, initial=current or 'fas fa-star')
            if name == 'display_order':
                self.fields[name] = field = forms.IntegerField(label=field.label, min_value=0,
                    max_value=MAX_INTEGER, initial=0)
            if name in ('title', 'hero_title', 'question', 'answer', 'body'):
                field.required = True
            if name == 'support_hours':
                field.help_text = 'Between 1 and 24 hours per day. Other statistics update automatically.'
            if name == 'occasion_chips':
                field.help_text = 'Separate occasions with commas.'
            if name in ('features', 'story_points'):
                field.help_text = 'Use one item per line.'
            if name == 'display_order':
                field.help_text = 'Lower numbers appear first on the website.'
            if name == 'attachment_url':
                field.help_text = 'Use a complete https:// or http:// address.'
            if isinstance(field.widget, forms.Textarea):
                field.widget.attrs['rows'] = 3
            field.widget.attrs.update(id='content_' + name,
                **{'aria-describedby': 'content_error_' + name})
            if isinstance(field.widget, forms.Select):
                field.widget.attrs['data-admin-select'] = ''
            if field.required:
                field.error_messages['required'] = f'{field.label} is required.'
        # Add after iteration: image removal controls are not model fields.
        if policy:
            self.fields['notify_clients'] = forms.BooleanField(label='Email active customers about this update',
                required=False, help_text='Send a notice only when the policy content changes.')
        for name, field in self.fields.items():
            field.widget.attrs.setdefault('id', 'content_' + name)
            field.widget.attrs.setdefault('aria-describedby', 'content_error_' + name)

    def save(self, commit=True):
        instance = super().save(commit=False)
        for name in tuple(self.fields):
            if name.startswith('remove_') and self.cleaned_data.get(name):
                image_name = name.removeprefix('remove_')
                if not self.files.get(image_name):
                    setattr(instance, image_name, '')
        if commit:
            instance.save()
        return instance


def content_form_class(model, fields):
    return forms.modelform_factory(model, form=ContentForm, fields=fields)
