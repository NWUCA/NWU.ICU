"""Reference checks and transaction ordering for ordinary uploaded attachments."""

import re
from collections import Counter
from contextlib import contextmanager
from uuid import UUID

from django.apps import apps
from django.conf import settings
from django.db import connection, transaction
from rest_framework.exceptions import ValidationError


# The two-key advisory-lock namespace is separate from the content-hash locks.
FILE_LIFECYCLE_LOCK = (0x4E575549, 0x46494C45)
FILE_URL = re.compile(
    r'/api/download/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})'
    r'(?=[/?#\s\"\'<>\)\]]|$)',
    re.IGNORECASE,
)
CONTENT_MODELS = (
    ('course_assessment', 'Review'),
    ('course_assessment', 'ReviewHistory'),
    ('guestbook', 'GuestbookEntry'),
    ('common', 'Announcement'),
    ('common', 'Bulletin'),
    ('common', 'About'),
)


@contextmanager
def file_lifecycle():
    """Take this lock before user, content, hash, or uploaded-file row locks."""
    with transaction.atomic():
        if connection.vendor == 'postgresql':
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_xact_lock(%s, %s)', FILE_LIFECYCLE_LOCK)
        yield


def file_reference_ids(content):
    """Accept current relative URLs and legacy absolute/Markdown attachment URLs."""
    return {UUID(value) for value in FILE_URL.findall(content or '')}


def missing_file_references(content, previous_content=''):
    from .models import UploadedFile

    added = file_reference_ids(content) - file_reference_ids(previous_content)
    if not added:
        return set()
    return added - set(UploadedFile.objects.filter(pk__in=added).values_list('pk', flat=True))


def ensure_file_references(content, previous_content=''):
    """Call inside file_lifecycle, before saving new attachment references."""
    if missing_file_references(content, previous_content):
        raise ValidationError({'content': '引用的附件已不存在，请重新上传后提交。'})


def ensure_owned_rich_content_references(*, owner, reference_ids, image_ids=(), label='公告'):
    """Require newly introduced attachments to belong to the current editor."""
    from .models import UploadedFile

    reference_ids = {str(value) for value in reference_ids}
    if reference_ids:
        owned_ids = {
            str(value) for value in UploadedFile.objects.filter(
                id__in=reference_ids,
                created_by=owner,
            ).values_list('id', flat=True)
        }
        if owned_ids != reference_ids:
            raise ValidationError({'content': f'{label}只能引用当前管理员上传的有效文件。'})
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
            raise ValidationError({'content': f'{label}只能使用当前管理员上传的有效图片。'})


def _content_querysets():
    for app_label, model_name in CONTENT_MODELS:
        model = apps.get_model(app_label, model_name)
        # Preserved and recoverable content must keep its attachments as well.
        manager = getattr(model, 'all_objects', model._default_manager)
        yield manager.all()


def _system_avatar_ids():
    return {
        UUID(str(settings.DEFAULT_USER_AVATAR_UUID)),
        UUID(str(settings.ANONYMOUS_USER_AVATAR_UUID)),
    }


def file_is_referenced(file_id):
    file_id = UUID(str(file_id))
    if file_id in _system_avatar_ids():
        return True
    for app_label, model_name in (('user', 'User'), ('course_assessment', 'Teacher')):
        if apps.get_model(app_label, model_name).objects.filter(avatar_uuid=file_id).exists():
            return True
    for queryset in _content_querysets():
        for content in queryset.filter(content__icontains=str(file_id)).values_list('content', flat=True).iterator():
            if file_id in file_reference_ids(content):
                return True
    return False


def collect_file_reference_counts():
    """Rebuild the compatibility counter from sources, never from its old value."""
    counts = Counter(_system_avatar_ids())
    for app_label, model_name in (('user', 'User'), ('course_assessment', 'Teacher')):
        counts.update(
            file_id for file_id in apps.get_model(app_label, model_name).objects
            .values_list('avatar_uuid', flat=True).iterator() if file_id
        )
    for queryset in _content_querysets():
        for content in queryset.filter(content__icontains='/api/download/').values_list('content', flat=True).iterator():
            counts.update(file_reference_ids(content))
    return counts
