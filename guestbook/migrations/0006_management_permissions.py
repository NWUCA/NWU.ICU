from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('guestbook', '0005_guestbookentry_title')]

    operations = [
        migrations.AlterModelOptions(
            name='guestbookentry',
            options={
                'ordering': ('-created_at', '-id'),
                'permissions': [('publish_announcements', 'Can publish announcements from the management panel')],
            },
        ),
        migrations.AlterModelOptions(
            name='guestbookreport',
            options={'permissions': [('moderate_reports', 'Can moderate guestbook reports')]},
        ),
    ]

