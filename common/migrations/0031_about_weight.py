# Generated by Django 4.2.14 on 2025-04-05 17:50

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('common', '0030_chat_last_message_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='about',
            name='weight',
            field=models.IntegerField(default=0),
        ),
    ]
