from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('management_panel', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='TelegramNotificationSettings',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('user_registration_enabled', models.BooleanField(default=True, verbose_name='用户注册')),
                ('guestbook_entry_enabled', models.BooleanField(default=True, verbose_name='发表留言')),
                ('course_review_enabled', models.BooleanField(default=True, verbose_name='发表课程评价')),
                ('reply_enabled', models.BooleanField(default=True, verbose_name='发表回复')),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Telegram 通知设置',
                'verbose_name_plural': 'Telegram 通知设置',
            },
        ),
    ]
