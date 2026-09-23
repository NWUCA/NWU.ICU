from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from common.file.models import UploadedFile
from common.file.references import ensure_file_references, file_lifecycle, file_reference_ids
from .models import GuestbookEntry
from .serializers import announcement_image_ids
from .submissions import create_submission


class AnnouncementNotFound(Exception):
    pass


class AnnouncementMustBeHidden(Exception):
    pass


def _announcement_for_update(entry_id):
    entry = (
        GuestbookEntry.objects.select_for_update()
        .filter(
            pk=entry_id,
            board=GuestbookEntry.BOARD_ANNOUNCEMENT,
            parent__isnull=True,
            root__isnull=True,
        )
        .first()
    )
    if entry is None:
        raise AnnouncementNotFound()
    return entry


def _ensure_owned_references(*, owner, reference_ids, image_ids=()):
    reference_ids = {str(value) for value in reference_ids}
    if reference_ids:
        owned_ids = {
            str(value) for value in UploadedFile.objects.filter(
                id__in=reference_ids,
                created_by=owner,
            ).values_list('id', flat=True)
        }
        if owned_ids != reference_ids:
            raise ValidationError({'content': '公告只能引用当前管理员上传的有效文件。'})
    image_ids = {str(value) for value in image_ids}
    if image_ids:
        valid_image_ids = {
            str(value) for value in UploadedFile.objects.filter(
                id__in=image_ids,
                created_by=owner,
                file_type='img',
            ).values_list('id', flat=True)
        }
        if valid_image_ids != image_ids:
            raise ValidationError({'content': '公告只能使用当前管理员上传的有效图片。'})


@file_lifecycle()
def publish_announcement(*, author, data):
    ensure_file_references(data['content'])
    references = file_reference_ids(data['content'])
    _ensure_owned_references(
        owner=author,
        reference_ids=references,
        image_ids=announcement_image_ids(data['content']),
    )
    with transaction.atomic():
        entry, created = create_submission(
            author,
            {**data, 'anonymous': False},
            board=GuestbookEntry.BOARD_ANNOUNCEMENT,
        )
        if created:
            UploadedFile.objects.filter(id__in=references).update(
                ref_count=F('ref_count') + 1,
            )
        return entry, created


@file_lifecycle()
def update_announcement(*, entry_id, editor, data):
    with transaction.atomic():
        entry = _announcement_for_update(entry_id)
        previous_content = entry.content
        changed = any(
            getattr(entry, field) != data[field]
            for field in ('title', 'content', 'priority')
        )
        if not changed:
            return entry

        ensure_file_references(data['content'], previous_content=previous_content)
        previous_references = file_reference_ids(previous_content)
        current_references = file_reference_ids(data['content'])
        previous_images = announcement_image_ids(previous_content)
        current_images = announcement_image_ids(data['content'])
        _ensure_owned_references(
            owner=editor,
            reference_ids=(current_references - previous_references)
            | (current_images - previous_images),
            image_ids=current_images - previous_images,
        )
        for field in ('title', 'content', 'priority'):
            setattr(entry, field, data[field])
        entry.updated_at = timezone.now()
        entry.save(update_fields=('title', 'content', 'priority', 'updated_at'))

        added = current_references - previous_references
        removed = previous_references - current_references
        if added:
            UploadedFile.objects.filter(id__in=added).update(ref_count=F('ref_count') + 1)
        if removed:
            UploadedFile.objects.filter(id__in=removed, ref_count__gt=0).update(
                ref_count=F('ref_count') - 1,
            )
        return entry


@transaction.atomic
def set_announcement_visibility(*, entry_id, visible):
    entry = _announcement_for_update(entry_id)
    if entry.is_visible != visible:
        entry.is_visible = visible
        entry.updated_at = timezone.now()
        entry.save(update_fields=('is_visible', 'updated_at'))
    return entry


@transaction.atomic
def delete_announcement(*, entry_id):
    entry = _announcement_for_update(entry_id)
    if entry.is_visible:
        raise AnnouncementMustBeHidden()
    entry.soft_delete()
    return entry
