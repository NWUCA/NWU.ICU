import logging
from urllib.parse import quote

from django.conf import settings
from django.core.mail import send_mail

from common.messaging import send_direct_message


logger = logging.getLogger(__name__)

RESULT_APPROVED = 'approved'
RESULT_REJECTED = 'rejected'
RESULT_PUBLISH_FAILED = 'publish_failed'


def get_resource_public_url(target_path):
    encoded_path = quote(str(target_path).strip(), safe='/')
    return f'{settings.RESOURCES_WEBSITE_URL.rstrip("/")}/{encoded_path.lstrip("/")}'


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


def notify_resource_upload_result(reviewer, upload_request, result):
    """Send both an in-site message and an email without breaking the review action."""
    content = build_resource_upload_result_message(upload_request, result)
    if reviewer != upload_request.uploaded_by:
        try:
            send_direct_message(
                sender=reviewer,
                recipient=upload_request.uploaded_by,
                content=content,
            )
        except Exception:
            logger.exception(
                'Failed to send resource upload %s site message to user %s',
                result,
                upload_request.uploaded_by_id,
            )

    recipient = upload_request.uploaded_by.email or upload_request.uploaded_by.college_email
    if not recipient:
        logger.warning(
            'Skipped resource upload %s email for user %s: no email address',
            result,
            upload_request.uploaded_by_id,
        )
        return
    try:
        send_mail(
            get_resource_upload_result_subject(result),
            content,
            settings.EMAIL_HOST_USER,
            [recipient],
            fail_silently=False,
        )
    except Exception:
        logger.exception(
            'Failed to send resource upload %s email to user %s',
            result,
            upload_request.uploaded_by_id,
        )
