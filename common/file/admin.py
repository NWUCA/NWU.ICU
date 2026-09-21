from django import forms

from .models import UploadedFile
from .references import file_lifecycle, missing_file_references


class AttachmentReferenceForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'avatar_uuid' in self.fields:
            # Teacher's historical random UUID default means "no avatar". New
            # admin forms should show an empty optional avatar, not require an
            # uploaded file matching that generated placeholder.
            self.fields['avatar_uuid'].required = False
            if not self.instance.pk:
                self.initial['avatar_uuid'] = None

    def clean(self):
        cleaned = super().clean()
        if 'content' in cleaned and missing_file_references(
            cleaned['content'], getattr(self.instance, 'content', '') if self.instance.pk else '',
        ):
            self.add_error('content', '引用的附件已不存在，请重新上传后提交。')
        if 'avatar_uuid' in self.changed_data and cleaned.get('avatar_uuid'):
            if not UploadedFile.objects.filter(pk=cleaned['avatar_uuid']).exists():
                self.add_error('avatar_uuid', '引用的头像已不存在，请重新上传后提交。')
        return cleaned


class AttachmentReferenceAdminMixin:
    form = AttachmentReferenceForm

    @file_lifecycle()
    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        return super().changeform_view(request, object_id, form_url, extra_context)
