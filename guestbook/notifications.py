from django.utils import timezone

from common.models import Notification
from utils.utils import get_user_avatar_info

from .models import GuestbookLike


def notification_author(user):
    info = get_user_avatar_info(user)
    return {
        'id': user.id,
        'nickname': user.nickname,
        **{key: str(value) if value is not None else None for key, value in info.items()},
    }


def notify_guestbook_reply(entry):
    """Notify only the author of the direct parent, never the author replying to themself."""
    parent = entry.parent
    if parent is None or parent.author_id == entry.author_id:
        return
    Notification.objects.update_or_create(
        dedupe_key=f'guestbook:reply:{entry.id}:{parent.author_id}',
        defaults={
            'recipient': parent.author,
            'actor': entry.author,
            'kind': Notification.KIND_REPLY,
            'read_at': None,
            'payload': {
                'source': 'guestbook',
                'guestbook': {
                    'root_id': entry.root_id or entry.id,
                    'entry_id': entry.id,
                    'target_id': parent.id,
                },
                'reply': {'id': entry.id, 'content': entry.content},
                'created_by': notification_author(entry.author),
                'datetime': entry.created_at.isoformat(),
            },
        },
    )


def notify_guestbook_like(entry):
    """Keep one aggregate notification per entry and omit any user-written content."""
    dedupe_key = f'guestbook:like:{entry.id}:{entry.author_id}'
    has_external_likes = GuestbookLike.objects.filter(entry=entry).exclude(user_id=entry.author_id).exists()
    if not has_external_likes:
        Notification.objects.filter(dedupe_key=dedupe_key).delete()
        return
    Notification.objects.update_or_create(
        dedupe_key=dedupe_key,
        defaults={
            'recipient': entry.author,
            'actor': None,
            'kind': Notification.KIND_LIKE,
            'read_at': None,
            'payload': {
                'source': 'guestbook',
                'guestbook': {
                    'root_id': entry.root_id or entry.id,
                    'entry_id': entry.id,
                },
                'like': {'like': entry.like_count, 'dislike': 0},
                'datetime': timezone.now().isoformat(),
            },
        },
    )


def notify_guestbook_report(report):
    if report.status == report.STATUS_PENDING:
        return
    Notification.objects.update_or_create(
        dedupe_key=f'guestbook:report:{report.id}',
        defaults={
            'recipient': report.reporter,
            'actor': report.handled_by,
            'kind': Notification.KIND_SYSTEM,
            'read_at': None,
            'payload': {
                'title': '留言板举报处理结果',
                'content': report.handling_note or (
                    '管理员已移除你举报的内容。' if report.status == report.STATUS_REMOVED else '管理员已处理你的举报。'
                ),
                'datetime': timezone.now().isoformat(),
            },
        },
    )
