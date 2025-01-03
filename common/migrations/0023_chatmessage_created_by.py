# Generated by Django 4.2.14 on 2024-10-19 01:47

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('common', '0022_rename_unread_count_chat_receiver_unread_count_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='chatmessage',
            name='created_by',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='messages_create_by', to=settings.AUTH_USER_MODEL),
        ),
    ]
