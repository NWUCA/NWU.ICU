import logging
from datetime import timedelta
from html import escape
from urllib.parse import quote

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .models import ResourceNotificationOutbox
from common.messaging import send_direct_message
from user.models import User


logger = logging.getLogger(__name__)

RESULT_NOTIFICATION_DELAY = timedelta(minutes=10)

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
            f'{upload_request.target_path}。 查看资料：{resource_url}'
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


def _create_outbox(
        *, event_key, upload_request, channel, body, reviewer=None, subject='',
        available_at=None, aggregation_key=''):
    notification, _ = ResourceNotificationOutbox.objects.get_or_create(
        event_key=event_key,
        defaults={
            'upload_request': upload_request,
            'recipient': upload_request.uploaded_by if channel != ResourceNotificationOutbox.CHANNEL_TELEGRAM else None,
            'sender': reviewer if channel != ResourceNotificationOutbox.CHANNEL_TELEGRAM else None,
            'channel': channel,
            'subject': subject,
            'body': body,
            'available_at': available_at or timezone.now(),
            'aggregation_key': aggregation_key,
        },
    )
    return notification


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
    with transaction.atomic():
        # Serializing per recipient makes the first review result define a
        # stable ten-minute collection window even with multiple workers.
        User.objects.select_for_update().get(pk=upload_request.uploaded_by_id)
        batch_now = timezone.now()
        for channel in (ResourceNotificationOutbox.CHANNEL_SITE_MESSAGE, ResourceNotificationOutbox.CHANNEL_EMAIL):
            aggregation_key = f'resource-upload:result:{upload_request.uploaded_by_id}:{channel}'
            available_at = (
                ResourceNotificationOutbox.objects.filter(
                    aggregation_key=aggregation_key,
                    status=ResourceNotificationOutbox.STATUS_PENDING,
                    available_at__gt=batch_now,
                )
                .order_by('available_at')
                .values_list('available_at', flat=True)
                .first()
                or batch_now + RESULT_NOTIFICATION_DELAY
            )
            _create_outbox(
                event_key=f'{base_key}:{channel}', upload_request=upload_request,
                channel=channel, body=body, subject=subject, reviewer=reviewer,
                available_at=available_at, aggregation_key=aggregation_key,
            )


def build_resource_upload_result_batch(notifications):
    rejected = []
    approved = []
    for notification in notifications:
        if ':rejected:' in notification.event_key:
            rejected.append(notification.upload_request)
        elif ':approved:' in notification.event_key:
            approved.append(notification.upload_request)

    plain_sections = []
    html_sections = []
    if rejected:
        plain_sections.append('[审核拒绝]\n' + '\n'.join(
            build_resource_upload_result_message(upload_request, RESULT_REJECTED)
            for upload_request in rejected
        ))
        html_sections.append(
            '<h2 style="font-size: 20px; margin: 24px 0 12px;">[审核拒绝]</h2>'
            + ''.join(
                '<p style="font-size: 14px; line-height: 1.7; margin: 8px 0;">'
                f'你的资料投稿 #{upload_request.pk} 未通过审核，已退回修改。'
                f'理由：{escape(upload_request.rejection_reason)}</p>'
                for upload_request in rejected
            )
        )
    if approved:
        plain_sections.append('[审核通过]\n' + '\n'.join(
            build_resource_upload_result_message(upload_request, RESULT_APPROVED)
            for upload_request in approved
        ))
        html_sections.append(
            '<h2 style="font-size: 20px; margin: 24px 0 12px;">[审核通过]</h2>'
            + ''.join(
                '<p style="font-size: 14px; line-height: 1.7; margin: 8px 0;">'
                f'你的资料投稿 #{upload_request.pk} 已审核通过并成功发布到 '
                f'{escape(upload_request.target_path)}。 查看资料：'
                f'<a href="{escape(get_resource_public_url(upload_request.target_path), quote=True)}">'
                f'{escape(get_resource_public_url(upload_request.target_path))}</a></p>'
                for upload_request in approved
            )
        )
    return (
        f'{settings.WEBSITE_NAME} 资料投稿审核结果',
        '\n\n'.join(plain_sections),
        ''.join(html_sections),
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
