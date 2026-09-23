from django.db import migrations, models
import django.core.validators
import django.utils.timezone


def backfill_updated_at(apps, schema_editor):
    entry = apps.get_model('guestbook', 'GuestbookEntry')
    entry._base_manager.update(updated_at=models.F('created_at'))


class Migration(migrations.Migration):
    dependencies = [('guestbook', '0006_management_permissions')]

    operations = [
        migrations.AddField(
            model_name='guestbookentry',
            name='is_visible',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='guestbookentry',
            name='priority',
            field=models.SmallIntegerField(
                default=0,
                validators=[
                    django.core.validators.MinValueValidator(-100),
                    django.core.validators.MaxValueValidator(100),
                ],
            ),
        ),
        migrations.AddField(
            model_name='guestbookentry',
            name='updated_at',
            field=models.DateTimeField(null=True),
        ),
        migrations.RunPython(backfill_updated_at, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='guestbookentry',
            name='updated_at',
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        migrations.AddConstraint(
            model_name='guestbookentry',
            constraint=models.CheckConstraint(
                check=models.Q(priority__gte=-100, priority__lte=100),
                name='guestbook_priority_range',
            ),
        ),
        migrations.AddIndex(
            model_name='guestbookentry',
            index=models.Index(
                fields=['board', 'parent', 'root', '-priority', '-updated_at', '-id'],
                name='guestbook_announce_sort_idx',
            ),
        ),
    ]
