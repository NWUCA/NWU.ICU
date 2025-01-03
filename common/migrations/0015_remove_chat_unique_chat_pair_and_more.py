# Generated by Django 4.2.14 on 2024-09-15 00:23

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('common', '0014_remove_chatlike_dislike_latest_user_and_more'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='chat',
            name='unique_chat_pair',
        ),
        migrations.RemoveConstraint(
            model_name='chat',
            name='unique_chat_pair_reverse',
        ),
        migrations.AddConstraint(
            model_name='chat',
            constraint=models.UniqueConstraint(fields=('sender', 'receiver', 'classify'), name='unique_chat_pair'),
        ),
        migrations.AddConstraint(
            model_name='chat',
            constraint=models.UniqueConstraint(fields=('receiver', 'sender', 'classify'), name='unique_chat_pair_reverse'),
        ),
    ]
