"""System announcement alerts retain a reference to their current source content."""

from itertools import islice

from django.db import transaction
from django.utils import timezone

from user.models import User

from .models import Bulletin, Notification


NOTIFICATION_BATCH_SIZE = 1000


def _broadcast(source, source_id, published_at):
    payload = {'source': source, 'datetime': published_at.isoformat()}
    if source == 'announcement':
        payload['guestbook'] = {'root_id': source_id}
    else:
        payload['bulletin'] = {'id': source_id}

    recipients = User.objects.order_by('pk').values_list('pk', flat=True).iterator(
        chunk_size=NOTIFICATION_BATCH_SIZE,
    )
    while recipient_ids := list(islice(recipients, NOTIFICATION_BATCH_SIZE)):
        keys = {user_id: f'{source}:publish:{source_id}:{user_id}' for user_id in recipient_ids}
        existing_keys = set(Notification.objects.filter(
            dedupe_key__in=keys.values(),
        ).values_list('dedupe_key', flat=True))
        notices = [Notification(
            recipient_id=user_id,
            actor=None,
            kind=Notification.KIND_SYSTEM,
            payload=payload,
            dedupe_key=key,
        ) for user_id, key in keys.items() if key not in existing_keys]
        if not notices:
            continue
        Notification.objects.bulk_create(notices, batch_size=NOTIFICATION_BATCH_SIZE)
        # auto_now fields are populated by bulk_create; restore the publication
        # time so announcements interleave with other alerts chronologically.
        for notice in notices:
            notice.created_at = published_at
            notice.updated_at = published_at
        Notification.objects.bulk_update(
            notices, ('created_at', 'updated_at'), batch_size=NOTIFICATION_BATCH_SIZE,
        )


@transaction.atomic
def notify_announcement_published(entry):
    from guestbook.models import GuestbookEntry

    current = GuestbookEntry.objects.select_for_update().get(pk=entry.pk)
    if current.board != GuestbookEntry.BOARD_ANNOUNCEMENT or not current.is_root or not current.is_visible:
        return
    _broadcast('announcement', current.pk, current.created_at)


@transaction.atomic
def notify_bulletin_published(bulletin):
    current = Bulletin.objects.select_for_update().get(pk=bulletin.pk)
    if not current.enabled or current.system_notification_sent:
        return
    _broadcast('bulletin', current.pk, timezone.now())
    Bulletin.objects.filter(pk=current.pk).update(system_notification_sent=True)
    bulletin.system_notification_sent = True


def hydrate_announcement_notifications(notifications):
    from guestbook.models import GuestbookEntry

    announcement_ids = []
    bulletin_ids = []
    for notice in notifications:
        if notice.kind != Notification.KIND_SYSTEM:
            continue
        if notice.payload.get('source') == 'announcement':
            announcement_ids.append(notice.payload.get('guestbook', {}).get('root_id'))
        elif notice.payload.get('source') == 'bulletin':
            bulletin_ids.append(notice.payload.get('bulletin', {}).get('id'))
    announcements = GuestbookEntry.all_objects.filter(
        board=GuestbookEntry.BOARD_ANNOUNCEMENT,
        parent__isnull=True,
        root__isnull=True,
    ).in_bulk(announcement_ids)
    bulletins = Bulletin.objects.in_bulk(bulletin_ids)

    for notice in notifications:
        if notice.kind != Notification.KIND_SYSTEM:
            continue
        source = notice.payload.get('source')
        if source == 'announcement':
            entry_id = notice.payload.get('guestbook', {}).get('root_id')
            entry = announcements.get(entry_id)
            deleted = entry is None or entry.is_deleted
            visible = not deleted and entry.is_visible
            target_url = f'/announcements/{entry_id}' if visible else None
        elif source == 'bulletin':
            entry = bulletins.get(notice.payload.get('bulletin', {}).get('id'))
            deleted = entry is None
            visible = not deleted and entry.enabled
            target_url = None
        else:
            continue
        payload = {**notice.payload}
        payload.pop('target_url', None)
        # Announcement alerts always appear as system notifications, including
        # any records that previously carried an account attribution snapshot.
        payload.pop('created_by', None)
        if visible:
            payload.update(title=entry.title, content=entry.content)
            if target_url:
                payload['target_url'] = target_url
        else:
            payload.update(
                title='系统通知',
                content='[公告已删除]' if deleted else '[公告已隐藏]',
            )
        notice.payload = payload
