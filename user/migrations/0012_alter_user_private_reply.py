# Generated by Django 4.2.14 on 2025-01-10 18:40

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0011_alter_user_private_reply_alter_user_private_review'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='private_reply',
            field=models.IntegerField(choices=[(0, '允许所有人'), (1, '允许登录用户'), (2, '禁止所有人')], default=0),
        ),
    ]