import logging
from urllib.parse import quote

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone

from .models import ResourceNotificationOutbox
from common.messaging import send_direct_message


logger = logging.getLogger(__name__)

RESULT_APPROVED = 'approved'
RESULT_REJECTED = 'rejected'
RESULT_PUBLISH_FAILED = 'publish_failed'


def get_resource_public_url(target_path):
    encoded_path = quote(str(target_path).strip(), safe='/')
    return f'{settings.FRONTEND_URL.rstrip("/")}/disk/{encoded_path.lstrip("/")}'


def get_resource_review_url(upload_request):
    path = reverse('admin:common_resourceuploadrequest_review', args=(upload_request.pk,))
    return f'{settings.ADMIN_PUBLIC_URL.rstrip("/")}{path}'


def build_resource_upload_result_message(upload_request, result):
    if result == RESULT_APPROVED:
        resource_url = get_resource_public_url(upload_request.target_path)
        return (
            f'你的资料投稿 #{upload_request.pk} 已审核通过并成功发布到 '
            f'{upload_request.target_path}。\n查看资料：{resource_url}'
        )
    if result == RESULT_PUBLISH_FAILED:
        return (
            f'你的资料投稿 #{upload_request.pk} 发布失败，已退回修改。'
            f'原因：{upload_request.rejection_reason}'
        )
    return (
        f'你的资料投稿 #{upload_request.pk} 未通过审核，已退回修改。'
        f'理由：{upload_request.rejection_reason}'
    )


def get_resource_upload_result_subject(result):
    labels = {
        RESULT_APPROVED: '资料投稿已发布',
        RESULT_REJECTED: '资料投稿已退回',
        RESULT_PUBLISH_FAILED: '资料投稿发布失败',
    }
    return f'{settings.WEBSITE_NAME} {labels[result]}'


def _create_outbox(*, event_key, upload_request, channel, body, reviewer=None, subject=''):
    ResourceNotificationOutbox.objects.get_or_create(
        event_key=event_key,
        defaults={
            'upload_request': upload_request,
            'recipient': upload_request.uploaded_by if channel != ResourceNotificationOutbox.CHANNEL_TELEGRAM else None,
            'sender': reviewer if channel != ResourceNotificationOutbox.CHANNEL_TELEGRAM else None,
            'channel': channel,
            'subject': subject,
            'body': body,
            'available_at': timezone.now(),
        },
    )


def queue_resource_upload_notifications(upload_request, *, event, reviewer=None):
    """Persist notifications in the outbox; delivery happens in the task worker."""
    base_key = f'resource-upload:{upload_request.pk}:revision:{upload_request.revision}:{event}'
    if event in {'created', 'updated'}:
        message = (
            f'{"收到新的" if event == "created" else "资料投稿已更新"}资料上传请求 #{upload_request.pk}\n'
            f'用户: {upload_request.uploaded_by.username} (ID: {upload_request.uploaded_by_id})\n'
            f'目标路径: {upload_request.target_path}\n'
            f'总大小: {upload_request.total_size_display if hasattr(upload_request, "total_size_display") else upload_request.total_size}\n'
            f'审核链接: {get_resource_review_url(upload_request)}'
        )
        _create_outbox(
            event_key=f'{base_key}:telegram', upload_request=upload_request,
            channel=ResourceNotificationOutbox.CHANNEL_TELEGRAM, body=message,
        )
        return
    if event == 'publish_failed':
        _create_outbox(
            event_key=f'{base_key}:telegram', upload_request=upload_request,
            channel=ResourceNotificationOutbox.CHANNEL_TELEGRAM,
            body=(
                f'资料投稿 #{upload_request.pk} 发布失败，请在后台处理。\n'
                f'错误：{upload_request.publish_error}\n审核链接: {get_resource_review_url(upload_request)}'
            ),
        )
        return

    result = RESULT_APPROVED if event == 'approved' else RESULT_REJECTED
    body = build_resource_upload_result_message(upload_request, result)
    subject = get_resource_upload_result_subject(result)
    for channel in (ResourceNotificationOutbox.CHANNEL_SITE_MESSAGE, ResourceNotificationOutbox.CHANNEL_EMAIL):
        _create_outbox(
            event_key=f'{base_key}:{channel}', upload_request=upload_request,
            channel=channel, body=body, subject=subject, reviewer=reviewer,
        )


def notify_resource_upload_result(reviewer, upload_request, result):
    """Legacy synchronous notifier retained for integrations outside the task workflow."""
    content = build_resource_upload_result_message(upload_request, result)
    if reviewer != upload_request.uploaded_by:
        send_direct_message(sender=reviewer, recipient=upload_request.uploaded_by, content=content)
    recipient = upload_request.uploaded_by.email or upload_request.uploaded_by.college_email
    if recipient:
        send_mail(
            get_resource_upload_result_subject(result), content, settings.EMAIL_HOST_USER,
            [recipient], fail_silently=False,
        )
