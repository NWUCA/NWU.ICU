from django.db import migrations


def clean_notifications(apps, schema_editor):
    Entry = apps.get_model('guestbook', 'GuestbookEntry')
    Notification = apps.get_model('common', 'Notification')
    deleted = set(Entry.objects.filter(is_deleted=True).values_list('id', flat=True))
    for note in Notification.objects.filter(payload__source='guestbook').iterator():
        target = note.payload.get('guestbook', {})
        if target.get('entry_id') in deleted or target.get('target_id') in deleted:
            note.delete()
        elif 'reply' in note.payload:
            note.payload['reply'].pop('content', None)
            note.save(update_fields=['payload'])


class Migration(migrations.Migration):
    dependencies = [
        ('guestbook', '0001_initial'),
        ('common', '0038_remove_legacy_chat_models'),
    ]
    operations = [migrations.RunPython(clean_notifications, migrations.RunPython.noop)]
