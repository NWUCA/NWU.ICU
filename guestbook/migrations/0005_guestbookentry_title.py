from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('guestbook', '0004_guestbookentry_board')]

    operations = [
        migrations.AddField(
            model_name='guestbookentry',
            name='title',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
    ]
