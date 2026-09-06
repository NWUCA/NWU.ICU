from uuid import UUID

from django.db.models import Q
from django.utils import timezone

from common.models import Notification
from utils.utils import get_user_avatar_info

from .models import GuestbookEntry, GuestbookLike


def entry_source(entry):
    return 'announcement' if entry.board == GuestbookEntry.BOARD_ANNOUNCEMENT else 'guestbook'


def notification_author(user):
    info = get_user_avatar_info(user)
    return {
        'id': user.id,
        'nickname': user.nickname,
        **{key: str(value) if isinstance(value, UUID) else value for key, value in info.items()},
    }


def notify_guestbook_reply(entry):
    """Notify only the author of the direct parent, never the author replying to themself."""
    parent = entry.parent
    if entry.is_deleted or parent is None or parent.is_deleted or parent.author_id == entry.author_id:
        return
    Notification.objects.update_or_create(
        dedupe_key=f'guestbook:reply:{entry.id}:{parent.author_id}',
        defaults={
            'recipient': parent.author,
            'actor': entry.author,
            'kind': Notification.KIND_REPLY,
            'read_at': None,
            'payload': {
                'source': entry_source(entry),
                'guestbook': {
                    'root_id': entry.root_id or entry.id,
                    'entry_id': entry.id,
                    'target_id': parent.id,
                },
                'reply': {'id': entry.id},
                'created_by': notification_author(entry.author),
                'datetime': entry.created_at.isoformat(),
            },
        },
    )


def notify_guestbook_like(entry, *, mark_unread=True):
    """Keep one aggregate notification per entry and omit any user-written content."""
    dedupe_key = f'guestbook:like:{entry.id}:{entry.author_id}'
    has_external_likes = GuestbookLike.objects.filter(entry=entry).exclude(user_id=entry.author_id).exists()
    if entry.is_deleted or not has_external_likes:
        Notification.objects.filter(dedupe_key=dedupe_key).delete()
        return
    defaults = {
        'recipient': entry.author,
        'actor': None,
        'kind': Notification.KIND_LIKE,
        'payload': {
            'source': entry_source(entry),
            'guestbook': {
                'root_id': entry.root_id or entry.id,
                'entry_id': entry.id,
            },
            'like': {'like': entry.like_count, 'dislike': 0},
            'datetime': timezone.now().isoformat(),
        },
    }
    if mark_unread:
        defaults['read_at'] = None
        Notification.objects.update_or_create(dedupe_key=dedupe_key, defaults=defaults)
    else:
        # Removing a like updates an existing total without generating a new alert.
        Notification.objects.filter(dedupe_key=dedupe_key).update(payload=defaults['payload'])


def remove_entry_notifications(entry_id):
    Notification.objects.filter(payload__source__in=('guestbook', 'announcement')).filter(
        Q(payload__guestbook__entry_id=entry_id) | Q(payload__guestbook__target_id=entry_id)
    ).delete()


def hydrate_guestbook_notifications(notifications):
    """Resolve text at read time, including notifications written before this change."""
    from .models import GuestbookEntry
    ids = [note.payload.get('guestbook', {}).get('entry_id') for note in notifications
           if note.payload.get('source') in ('guestbook', 'announcement') and note.kind == Notification.KIND_REPLY]
    entries = GuestbookEntry.all_objects.select_related('author').in_bulk(ids)
    for note in notifications:
        if note.payload.get('source') not in ('guestbook', 'announcement') or note.kind != Notification.KIND_REPLY:
            continue
        entry_id = note.payload.get('guestbook', {}).get('entry_id')
        entry = entries.get(entry_id)
        note.payload = {**note.payload, 'reply': {
            'id': entry_id,
            'content': entry.content if entry and not entry.is_deleted else '[内容已删除]',
        }}
        if entry:
            note.payload['created_by'] = notification_author(entry.author)


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
                'title': f'{"公告栏" if report.entry.board == GuestbookEntry.BOARD_ANNOUNCEMENT else "留言板"}举报处理结果',
                'content': report.handling_note or (
                    '管理员已移除你举报的内容。' if report.status == report.STATUS_REMOVED else '管理员已处理你的举报。'
                ),
                'datetime': timezone.now().isoformat(),
            },
        },
    )
