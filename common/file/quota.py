from django.conf import settings
from django.db.models import BigIntegerField, Sum
from django.db.models.functions import Coalesce

from user.models import User

from .models import ResourceUploadRequest, UploadedFile


def upload_quota_limit():
    return getattr(settings, 'USER_UPLOAD_QUOTA_BYTES', 1024 ** 3)


def lock_upload_quota(user):
    """Serialize quota-changing operations for one user."""
    return User.objects.select_for_update().get(pk=user.pk)


def get_upload_usage(user):
    ordinary = UploadedFile.objects.filter(created_by=user).aggregate(
        total=Coalesce(Sum('file_size'), 0, output_field=BigIntegerField()),
    )['total']
    staged_resources = (
        ResourceUploadRequest.objects
        .filter(uploaded_by=user, files_deleted_at__isnull=True)
        .exclude(status=ResourceUploadRequest.STATUS_APPROVED)
        .aggregate(total=Coalesce(Sum('total_size'), 0, output_field=BigIntegerField()))
    )['total']
    return ordinary + staged_resources


def get_upload_quota(user):
    limit = upload_quota_limit()
    used = get_upload_usage(user)
    return {'limit': limit, 'used': used, 'remaining': max(0, limit - used)}


def quota_would_be_exceeded(user, delta):
    if delta <= 0:
        return False
    return get_upload_usage(user) + delta > upload_quota_limit()


def quota_error_response_data():
    return {
        'quota': {
            'err_code': 'upload_quota_exceeded',
            'err_msg': '上传内容将超过 1 GiB 的个人上传额度',
        },
    }
