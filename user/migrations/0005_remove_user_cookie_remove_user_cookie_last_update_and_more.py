# Generated by Django 4.2.14 on 2024-07-17 01:38

from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0004_user_nickname'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='user',
            name='cookie',
        ),
        migrations.RemoveField(
            model_name='user',
            name='cookie_last_update',
        ),
        migrations.AddField(
            model_name='user',
            name='avatar_uuid',
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
        migrations.AddField(
            model_name='user',
            name='nwu_email',
            field=models.CharField(max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name='user',
            name='name',
            field=models.TextField(null=True),
        ),
        migrations.AlterField(
            model_name='user',
            name='password',
            field=models.CharField(max_length=255),
        ),
    ]
