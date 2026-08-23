import uuid

from django.db import migrations, models


def populate_user_uuids(apps, schema_editor):
    user_model = apps.get_model('user', 'User')
    for user in user_model.objects.filter(uuid__isnull=True).iterator():
        user.uuid = uuid.uuid4()
        user.save(update_fields=('uuid',))


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0011_unique_verified_college_email'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='uuid',
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.RunPython(populate_user_uuids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='user',
            name='uuid',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
