"""State transitions and durable side effects for resource upload reviews."""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import ResourcePublishJob, ResourceUploadRequest
from .resource_directories import normalize_directory_path
from .resource_notifications import queue_resource_upload_notifications


class ResourceReviewError(Exception):
    pass


def normalize_review_target_path(path):
    try:
        normalized = normalize_directory_path(path)
    except (TypeError, ValueError) as error:
        raise ResourceReviewError('目标目录不合法') from error
    if normalized == '/':
        raise ResourceReviewError('不能发布到资料根目录')
    if any(ord(character) < 32 for character in normalized):
        raise ResourceReviewError('目标目录不能包含控制字符')
    return normalized


def approve_resource_upload(*, upload_request_id, reviewer, expected_revision, target_path):
    """Queue a publish job after verifying the review page is still current."""
    target_path = normalize_review_target_path(target_path)
    with transaction.atomic():
        upload_request = ResourceUploadRequest.objects.select_for_update().get(pk=upload_request_id)
        if upload_request.status != ResourceUploadRequest.STATUS_PENDING:
            raise ResourceReviewError('只有待审核投稿可以通过')
        if upload_request.revision != expected_revision:
            raise ResourceReviewError('投稿内容已被用户更新，请刷新后重新审核')
        now = timezone.now()
        upload_request.target_path = target_path
        upload_request.creates_new_folder = False
        upload_request.status = ResourceUploadRequest.STATUS_PUBLISHING
        upload_request.reviewed_by = reviewer
        upload_request.reviewed_at = now
        upload_request.rejection_reason = ''
        upload_request.publish_error = ''
        upload_request.save(update_fields=(
            'target_path', 'creates_new_folder', 'status', 'reviewed_by', 'reviewed_at',
            'rejection_reason', 'publish_error', 'updated_at',
        ))
        ResourcePublishJob.objects.create(
            upload_request=upload_request,
            revision=upload_request.revision,
            target_path=target_path,
            available_at=now,
        )
    return upload_request


def reject_resource_upload(*, upload_request_id, reviewer, expected_revision, reason):
    reason = reason.strip()
    if not reason:
        raise ResourceReviewError('拒绝投稿时必须填写理由')
    with transaction.atomic():
        upload_request = ResourceUploadRequest.objects.select_for_update().get(pk=upload_request_id)
        if upload_request.status not in {
            ResourceUploadRequest.STATUS_PENDING,
            ResourceUploadRequest.STATUS_PUBLISH_FAILED,
        }:
            raise ResourceReviewError('只有待审核或发布异常的投稿可以拒绝')
        if upload_request.revision != expected_revision:
            raise ResourceReviewError('投稿内容已被用户更新，请刷新后重新审核')
        upload_request.status = ResourceUploadRequest.STATUS_REJECTED
        upload_request.reviewed_by = reviewer
        upload_request.reviewed_at = timezone.now()
        upload_request.rejection_reason = reason
        upload_request.publish_error = ''
        upload_request.save(update_fields=(
            'status', 'reviewed_by', 'reviewed_at', 'rejection_reason', 'publish_error', 'updated_at',
        ))
        queue_resource_upload_notifications(upload_request, event='rejected', reviewer=reviewer)
    return upload_request


def retry_resource_publish(*, upload_request_id, reviewer, expected_revision, target_path):
    target_path = normalize_review_target_path(target_path)
    with transaction.atomic():
        upload_request = ResourceUploadRequest.objects.select_for_update().get(pk=upload_request_id)
        if upload_request.status != ResourceUploadRequest.STATUS_PUBLISH_FAILED:
            raise ResourceReviewError('当前投稿不需要重新发布')
        if upload_request.revision != expected_revision:
            raise ResourceReviewError('投稿内容已被更新，请刷新后重试')
        now = timezone.now()
        upload_request.target_path = target_path
        upload_request.creates_new_folder = False
        upload_request.status = ResourceUploadRequest.STATUS_PUBLISHING
        upload_request.reviewed_by = reviewer
        upload_request.reviewed_at = now
        upload_request.publish_error = ''
        upload_request.save(update_fields=(
            'target_path', 'creates_new_folder', 'status', 'reviewed_by', 'reviewed_at',
            'publish_error', 'updated_at',
        ))
        ResourcePublishJob.objects.update_or_create(
            upload_request=upload_request,
            revision=upload_request.revision,
            defaults={
                'target_path': target_path,
                'status': ResourcePublishJob.STATUS_PENDING,
                'attempts': 0,
                'available_at': now,
                'locked_at': None,
                'last_error': '',
            },
        )
    return upload_request


def resource_upload_files_expire_at(upload_request):
    if (
        upload_request.status == ResourceUploadRequest.STATUS_REJECTED
        and upload_request.reviewed_at
        and not upload_request.files_deleted_at
    ):
        return upload_request.reviewed_at + timedelta(days=30)
    return None
