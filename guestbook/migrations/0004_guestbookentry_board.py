from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('guestbook', '0003_guestbook_submission_id')]

    operations = [
        migrations.AddField(
            model_name='guestbookentry',
            name='board',
            field=models.CharField(
                choices=[('guestbook', '留言板'), ('announcement', '公告栏')],
                default='guestbook',
                max_length=16,
            ),
        ),
        migrations.AddIndex(
            model_name='guestbookentry',
            index=models.Index(fields=['board', '-created_at', '-id'], name='guestbook_board_recent_idx'),
        ),
    ]
