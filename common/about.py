"""The public site's single editable About page."""

from django.db.models import F

from common.file.models import UploadedFile
from common.file.references import (
    ensure_file_references,
    ensure_owned_rich_content_references,
    file_lifecycle,
    file_reference_ids,
)
from guestbook.serializers import announcement_image_ids

from .models import About


def current_about():
    # Older Django admin entries may contain multiple About rows. The newest
    # row is the page shown to visitors and the one edited from Manage.
    return About.objects.filter(type='about').order_by('-update_time', '-pk').first()


@file_lifecycle()
def save_about(*, editor, content):
    about = (
        About.objects.select_for_update()
        .filter(type='about')
        .order_by('-update_time', '-pk')
        .first()
    )
    previous_content = about.content if about else ''
    if about and content == previous_content:
        return about

    ensure_file_references(content, previous_content=previous_content)
    previous_references = file_reference_ids(previous_content)
    current_references = file_reference_ids(content)
    previous_images = announcement_image_ids(previous_content)
    current_images = announcement_image_ids(content)
    ensure_owned_rich_content_references(
        owner=editor,
        reference_ids=(current_references - previous_references)
        | (current_images - previous_images),
        image_ids=current_images - previous_images,
        label='关于本站',
    )

    if about is None:
        about = About.objects.create(title='关于本站', content=content, type='about')
    else:
        about.content = content
        about.save(update_fields=('content', 'update_time'))

    added = current_references - previous_references
    removed = previous_references - current_references
    if added:
        UploadedFile.objects.filter(pk__in=added).update(ref_count=F('ref_count') + 1)
    if removed:
        UploadedFile.objects.filter(pk__in=removed, ref_count__gt=0).update(
            ref_count=F('ref_count') - 1,
        )
    return about
