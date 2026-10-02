from itertools import islice

from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


BATCH_SIZE = 1000


def backfill_announcement_notifications(apps, schema_editor):
    Notification = apps.get_model('common', 'Notification')
    Bulletin = apps.get_model('common', 'Bulletin')
    GuestbookEntry = apps.get_model('guestbook', 'GuestbookEntry')
    user_app, user_model = settings.AUTH_USER_MODEL.split('.')
    User = apps.get_model(user_app, user_model)
    database = schema_editor.connection.alias
    read_at = timezone.now()

    sources = (
        ('announcement', GuestbookEntry._base_manager.using(database).filter(
            board='announcement', parent__isnull=True, root__isnull=True,
            is_visible=True, is_deleted=False,
        ), 'created_at'),
        ('bulletin', Bulletin.objects.using(database).filter(enabled=True), 'create_time'),
    )
    for source, queryset, time_field in sources:
        for entry in queryset.order_by('pk').iterator(chunk_size=BATCH_SIZE):
            published_at = getattr(entry, time_field)
            payload = {'source': source, 'datetime': published_at.isoformat()}
            if source == 'announcement':
                payload['guestbook'] = {'root_id': entry.pk}
            else:
                payload['bulletin'] = {'id': entry.pk}
            recipient_ids = User.objects.using(database).order_by('pk').values_list(
                'pk', flat=True,
            ).iterator(chunk_size=BATCH_SIZE)
            while user_ids := list(islice(recipient_ids, BATCH_SIZE)):
                keys = {user_id: f'{source}:publish:{entry.pk}:{user_id}' for user_id in user_ids}
                existing_keys = set(Notification.objects.using(database).filter(
                    dedupe_key__in=keys.values(),
                ).values_list('dedupe_key', flat=True))
                notices = [Notification(
                    recipient_id=user_id,
                    actor_id=None,
                    kind='system',
                    dedupe_key=key,
                    payload=payload,
                    read_at=read_at,
                ) for user_id, key in keys.items() if key not in existing_keys]
                if not notices:
                    continue
                Notification.objects.using(database).bulk_create(notices, batch_size=BATCH_SIZE)
                for notice in notices:
                    notice.created_at = published_at
                    notice.updated_at = published_at
                Notification.objects.using(database).bulk_update(
                    notices, ('created_at', 'updated_at'), batch_size=BATCH_SIZE,
                )
    # A previously hidden bulletin may already have been published. Treat all
    # existing rows as handled so showing them again cannot trigger a broadcast.
    Bulletin.objects.using(database).update(system_notification_sent=True)


class Migration(migrations.Migration):
    dependencies = [
        ('common', '0047_resource_archives'),
        ('guestbook', '0007_announcement_management_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='bulletin',
            name='system_notification_sent',
            field=models.BooleanField(default=False, editable=False),
        ),
        migrations.RunPython(backfill_announcement_notifications, migrations.RunPython.noop),
    ]
