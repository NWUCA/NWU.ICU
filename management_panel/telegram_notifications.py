import logging
import re
from concurrent.futures import ThreadPoolExecutor
from html import unescape

from django.conf import settings
from django.db import close_old_connections, transaction

from settings.log import TelegramBotHandler

from .models import TelegramNotificationSettings


logger = logging.getLogger(__name__)
telegram_notification_executor = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix='site-event-telegram-notification',
)

EVENT_SETTING_FIELDS = {
    'user_registration': 'user_registration_enabled',
    'guestbook_entry': 'guestbook_entry_enabled',
    'course_review': 'course_review_enabled',
    'reply': 'reply_enabled',
}


def _plain_text(value, limit=800):
    text = re.sub(r'<[^>]*>', ' ', value or '')
    text = re.sub(r'\s+', ' ', unescape(text)).strip()
    return text if len(text) <= limit else f'{text[:limit]}…'


def _user_label(user):
    nickname = (user.nickname or '').strip()
    return f'{nickname} (@{user.username}, ID {user.pk})' if nickname else f'@{user.username} (ID {user.pk})'


def _send_message(message):
    close_old_connections()
    try:
        handler = TelegramBotHandler(send_timeout=10)
        handler.setFormatter(logging.Formatter('%(message)s'))
        handler.handle(logging.LogRecord(__name__, logging.INFO, '', 0, message, (), None))
    except Exception:
        logger.exception('telegram_site_event_notification_failed')
    finally:
        close_old_connections()


def notify_email_delivery_failure(*, subject, recipients, error, context=''):
    """Alert operators without depending on the failing email transport."""
    if not settings.TELEGRAM_BOT_API_TOKEN or not settings.TELEGRAM_CHAT_ID:
        return
    recipient_text = ', '.join(str(value) for value in recipients) or '(无收件人)'
    message = '\n'.join(filter(None, (
        '邮件发送失败',
        f'场景: {context}' if context else '',
        f'主题: {_plain_text(subject, limit=300)}',
        f'收件人: {_plain_text(recipient_text, limit=500)}',
        f'错误: {_plain_text(str(error), limit=1000)}',
    )))
    try:
        telegram_notification_executor.submit(_send_message, message)
    except Exception:
        logger.exception('telegram_email_failure_notification_enqueue_failed')


def send_mail_with_telegram_alert(
        send_function, *args, alert_context='', alert_on_failure=True, **kwargs):
    """Call Django's send_mail and alert Telegram on exceptions or zero delivery."""
    subject = kwargs.get('subject', args[0] if args else '')
    recipients = kwargs.get('recipient_list', args[3] if len(args) > 3 else ())
    try:
        delivered = send_function(*args, **kwargs)
    except Exception as error:
        if alert_on_failure:
            notify_email_delivery_failure(
                subject=subject,
                recipients=recipients,
                error=error,
                context=alert_context,
            )
        raise
    if delivered == 0 and alert_on_failure:
        notify_email_delivery_failure(
            subject=subject,
            recipients=recipients,
            error='邮件后端返回 0，未接受任何邮件',
            context=alert_context,
        )
    return delivered


def _enqueue(event, message):
    if not settings.TELEGRAM_BOT_API_TOKEN or not settings.TELEGRAM_CHAT_ID:
        return
    try:
        field = EVENT_SETTING_FIELDS[event]
        enabled = (
            TelegramNotificationSettings.objects.filter(pk=1)
            .values_list(field, flat=True)
            .first()
        )
        # No row means a fresh deployment that has not opened the settings UI
        # yet. Model defaults intentionally make all four alerts enabled.
        if enabled is False:
            return
        telegram_notification_executor.submit(_send_message, message)
    except Exception:
        # Observability must never turn a successful user action into a 500.
        logger.exception('telegram_site_event_notification_enqueue_failed event=%s', event)


def schedule_telegram_notification(event, message):
    transaction.on_commit(lambda: _enqueue(event, message))


def notify_user_registered(user):
    schedule_telegram_notification(
        'user_registration',
        '\n'.join((
            '新用户注册',
            f'用户: {_user_label(user)}',
            f'邮箱: {user.email}',
        )),
    )


def notify_guestbook_entry(entry):
    schedule_telegram_notification(
        'guestbook_entry',
        '\n'.join((
            f'新留言 #{entry.pk}',
            f'用户: {_user_label(entry.author)}',
            f'匿名发布: {"是" if entry.anonymous else "否"}',
            f'内容: {_plain_text(entry.content)}',
            f'链接: {settings.FRONTEND_URL.rstrip("/")}/guestbook/{entry.pk}',
        )),
    )


def notify_guestbook_reply(entry):
    root_id = entry.root_id or entry.pk
    board_path = 'announcements' if entry.board == 'announcement' else 'guestbook'
    schedule_telegram_notification(
        'reply',
        '\n'.join((
            f'新{("公告" if entry.board == "announcement" else "留言")}回复 #{entry.pk}',
            f'用户: {_user_label(entry.author)}',
            f'匿名发布: {"是" if entry.anonymous else "否"}',
            f'内容: {_plain_text(entry.content)}',
            f'链接: {settings.FRONTEND_URL.rstrip("/")}/{board_path}/{root_id}?focus={entry.pk}',
        )),
    )


def notify_course_review(review):
    schedule_telegram_notification(
        'course_review',
        '\n'.join((
            f'新课程评价 #{review.pk}',
            f'用户: {_user_label(review.created_by)}',
            f'课程: {review.course.get_name()} (ID {review.course_id})',
            f'匿名发布: {"是" if review.anonymous else "否"}',
            f'评分: {review.rating}/5',
            f'内容: {_plain_text(review.content)}',
            f'链接: {settings.FRONTEND_URL.rstrip("/")}/review/course/{review.course_id}',
        )),
    )


def notify_course_review_reply(reply):
    schedule_telegram_notification(
        'reply',
        '\n'.join((
            f'新课程评价回复 #{reply.pk}',
            f'用户: {_user_label(reply.created_by)}',
            f'课程: {reply.review.course.get_name()} (ID {reply.review.course_id})',
            f'评价: #{reply.review_id}',
            f'内容: {_plain_text(reply.content)}',
            f'链接: {settings.FRONTEND_URL.rstrip("/")}/review/course/{reply.review.course_id}',
        )),
    )
