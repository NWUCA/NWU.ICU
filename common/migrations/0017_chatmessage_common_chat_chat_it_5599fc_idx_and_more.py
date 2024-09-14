# Generated by Django 4.2.14 on 2024-09-15 02:57

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('common', '0016_chat_unread_count'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='chatmessage',
            index=models.Index(fields=['chat_item'], name='common_chat_chat_it_5599fc_idx'),
        ),
        migrations.AddIndex(
            model_name='chatmessage',
            index=models.Index(fields=['create_time'], name='common_chat_create__849983_idx'),
        ),
    ]
