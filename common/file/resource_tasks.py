"""Database-backed task processing for resource publishing and notifications."""
import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from common.messaging import send_direct_message
from management_panel.telegram_notifications import send_mail_with_telegram_alert
from settings.log import TelegramBotHandler
from user.models import User

from .models import ResourceNotificationOutbox, ResourcePublishJob, ResourceUploadRequest
from .resource_locks import lock_resource_upload_request
from .resource_notifications import build_resource_upload_result_batch, queue_resource_upload_notifications
from .resource_publish import (
    ResourcePublishError,
    delete_resource_upload_staging_files,
    publish_resource_upload,
)


logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5
RETRY_DELAYS = (1, 5, 15, 60, 360)


def _next_retry(attempts):
    return timezone.now() + timedelta(minutes=RETRY_DELAYS[min(attempts - 1, len(RETRY_DELAYS) - 1)])


def claim_publish_job():
    with transaction.atomic():
        stale_before = timezone.now() - timedelta(minutes=15)
        ResourcePublishJob.objects.filter(
            status=ResourcePublishJob.STATUS_PROCESSING,
            locked_at__lt=stale_before,
        ).update(
            status=ResourcePublishJob.STATUS_RETRY,
            locked_at=None,
            available_at=timezone.now(),
        )
        job = (
            ResourcePublishJob.objects.select_for_update(skip_locked=True)
            .filter(
                status__in=(ResourcePublishJob.STATUS_PENDING, ResourcePublishJob.STATUS_RETRY),
                available_at__lte=timezone.now(),
            )
            .order_by('available_at', 'pk')
            .first()
        )
        if not job:
            return None
        job.status = ResourcePublishJob.STATUS_PROCESSING
        job.locked_at = timezone.now()
        job.save(update_fields=('status', 'locked_at', 'updated_at'))
        return job.pk


def process_one_publish_job():
    job_id = claim_publish_job()
    if not job_id:
        return False
    job = ResourcePublishJob.objects.select_related('upload_request', 'upload_request__reviewed_by').get(pk=job_id)
    upload_request = job.upload_request
    try:
        if upload_request.status != ResourceUploadRequest.STATUS_PUBLISHING:
            raise ResourcePublishError('投稿已不处于发布状态')
        if upload_request.revision != job.revision:
            raise ResourcePublishError('投稿版本已变化')
        publish_resource_upload(upload_request)
    except Exception as error:
        message = str(error)
        with transaction.atomic():
            upload_request = lock_resource_upload_request(job.upload_request_id)
            job = ResourcePublishJob.objects.select_for_update().get(pk=job_id)
            job.attempts += 1
            job.last_error = message
            job.locked_at = None
            if job.attempts >= MAX_ATTEMPTS:
                job.status = ResourcePublishJob.STATUS_FAILED
                upload_request.status = ResourceUploadRequest.STATUS_PUBLISH_FAILED
                upload_request.publish_error = message
                upload_request.save(update_fields=('status', 'publish_error', 'updated_at'))
                queue_resource_upload_notifications(upload_request, event='publish_failed', reviewer=upload_request.reviewed_by)
            else:
                job.status = ResourcePublishJob.STATUS_RETRY
                job.available_at = _next_retry(job.attempts)
                upload_request.publish_error = message
                upload_request.save(update_fields=('publish_error', 'updated_at'))
            job.save(update_fields=('attempts', 'last_error', 'locked_at', 'status', 'available_at', 'updated_at'))
        logger.exception('Resource publish job %s failed', job_id)
        return True

    staging_files_deleted = delete_resource_upload_staging_files(upload_request)
    with transaction.atomic():
        upload_request = lock_resource_upload_request(job.upload_request_id)
        job = ResourcePublishJob.objects.select_for_update().get(pk=job_id)
        now = timezone.now()
        job.status = ResourcePublishJob.STATUS_SUCCEEDED
        job.locked_at = None
        job.last_error = ''
        job.save(update_fields=('status', 'locked_at', 'last_error', 'updated_at'))
        upload_request.status = ResourceUploadRequest.STATUS_APPROVED
        upload_request.publish_error = ''
        upload_request.files_deleted_at = now if staging_files_deleted else None
        upload_request.save(update_fields=('status', 'publish_error', 'files_deleted_at', 'updated_at'))
        queue_resource_upload_notifications(upload_request, event='approved', reviewer=upload_request.reviewed_by)
    return True


def claim_notification():
    with transaction.atomic():
        now = timezone.now()
        claimable = Q(
            status__in=(ResourceNotificationOutbox.STATUS_PENDING, ResourceNotificationOutbox.STATUS_RETRY),
            available_at__lte=now,
        ) | Q(
            status=ResourceNotificationOutbox.STATUS_PROCESSING,
            locked_at__lt=now - timedelta(minutes=15),
        )
        notification = (
            ResourceNotificationOutbox.objects
            .filter(claimable)
            .order_by('available_at', 'pk')
            .first()
        )
        if not notification:
            return None
        if notification.aggregation_key:
            # Serialize claims for a recipient before locking any outbox rows.
            # This prevents two workers from each locking one row in the same
            # batch and then deadlocking (or sending two partial batches).
            User.objects.select_for_update().get(pk=notification.recipient_id)
            claimed = ResourceNotificationOutbox.objects.select_for_update().filter(
                claimable,
                aggregation_key=notification.aggregation_key,
            )
        else:
            claimed = ResourceNotificationOutbox.objects.select_for_update(skip_locked=True).filter(
                claimable,
                pk=notification.pk,
            )
        notification_ids = tuple(claimed.order_by('pk').values_list('pk', flat=True))
        if not notification_ids:
            return None
        ResourceNotificationOutbox.objects.filter(pk__in=notification_ids).update(
            status=ResourceNotificationOutbox.STATUS_PROCESSING,
            locked_at=timezone.now(),
        )
        return notification_ids


def _deliver(notifications):
    notification = notifications[0]
    subject = notification.subject
    body = notification.body
    html_body = None
    if notification.aggregation_key:
        subject, body, html_body = build_resource_upload_result_batch(notifications)
    if notification.channel == ResourceNotificationOutbox.CHANNEL_TELEGRAM:
        if not settings.TELEGRAM_BOT_API_TOKEN or not settings.TELEGRAM_CHAT_ID:
            raise RuntimeError('Telegram bot token or chat id is not configured')
        handler = TelegramBotHandler(send_timeout=10)
        handler.setFormatter(logging.Formatter('%(message)s'))
        handler.handle(logging.LogRecord(__name__, logging.INFO, '', 0, body, (), None))
        return
    if notification.channel == ResourceNotificationOutbox.CHANNEL_SITE_MESSAGE:
        if not notification.sender or not notification.recipient:
            raise ValueError('站内信缺少发送者或接收者')
        send_direct_message(notification.sender, notification.recipient, body)
        return
    if notification.channel == ResourceNotificationOutbox.CHANNEL_EMAIL:
        if not notification.recipient:
            raise ValueError('邮件缺少接收者')
        recipient = notification.recipient.email or notification.recipient.college_email
        if not recipient:
            raise ValueError('用户没有可用邮箱')
        send_mail_with_telegram_alert(
            send_mail,
            subject, body, settings.EMAIL_HOST_USER, [recipient],
            fail_silently=False, html_message=html_body,
            alert_context=f'资料投稿审核结果邮件（通知 {notification.pk}）',
            alert_on_failure=notification.attempts == 0,
        )
        return
    raise ValueError('未知通知渠道')


def process_one_notification():
    notification_ids = claim_notification()
    if not notification_ids:
        return False
    notifications = list(
        ResourceNotificationOutbox.objects
        .select_related('recipient', 'sender', 'upload_request')
        .filter(pk__in=notification_ids)
        .order_by('pk')
    )
    try:
        _deliver(notifications)
    except Exception as error:
        with transaction.atomic():
            claimed_notifications = ResourceNotificationOutbox.objects.select_for_update().filter(pk__in=notification_ids)
            retry_at = _next_retry(max(notification.attempts for notification in claimed_notifications) + 1)
            for notification in claimed_notifications:
                notification.attempts += 1
                notification.last_error = str(error)
                notification.locked_at = None
                if notification.attempts >= MAX_ATTEMPTS:
                    notification.status = ResourceNotificationOutbox.STATUS_FAILED
                else:
                    notification.status = ResourceNotificationOutbox.STATUS_RETRY
                    notification.available_at = retry_at
                notification.save(update_fields=(
                    'attempts', 'last_error', 'locked_at', 'status', 'available_at', 'updated_at',
                ))
        logger.exception('Resource notifications %s failed', notification_ids)
        return True
    ResourceNotificationOutbox.objects.filter(pk__in=notification_ids).update(
        status=ResourceNotificationOutbox.STATUS_SENT,
        sent_at=timezone.now(),
        locked_at=None,
        last_error='',
    )
    return True
