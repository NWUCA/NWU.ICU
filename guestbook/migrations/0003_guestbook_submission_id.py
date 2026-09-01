from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('guestbook', '0002_remove_notification_snapshots')]
    operations = [
        migrations.AddField(
            model_name='guestbookentry', name='submission_id',
            field=models.UUIDField(blank=True, editable=False, null=True),
        ),
        migrations.AddConstraint(
            model_name='guestbookentry',
            constraint=models.UniqueConstraint(fields=('author', 'submission_id'), name='unique_guestbook_submission'),
        ),
    ]
