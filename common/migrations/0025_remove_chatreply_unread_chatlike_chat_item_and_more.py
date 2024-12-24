# Generated by Django 4.2.14 on 2024-11-08 18:14

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('common', '0024_chatlike_read_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='chatreply',
            name='unread',
        ),
        migrations.AddField(
            model_name='chatlike',
            name='chat_item',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='like_messages', to='common.chat'),
        ),
        migrations.AddField(
            model_name='chatreply',
            name='chat_item',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='reply_messages', to='common.chat'),
        ),
        migrations.AddField(
            model_name='chatreply',
            name='read',
            field=models.BooleanField(default=False),
        ),
    ]