# Generated by Django 4.2.14 on 2024-10-14 11:38

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('course_assessment', '0026_alter_review_pinyin'),
        ('common', '0018_uploadedfile_file_hash'),
    ]

    operations = [
        migrations.RenameField(
            model_name='chatlike',
            old_name='raw_post',
            new_name='raw_post_id',
        ),
        migrations.AddField(
            model_name='chatlike',
            name='raw_post_content',
            field=models.TextField(null=True),
        ),
        migrations.AddField(
            model_name='chatlike',
            name='raw_post_course',
            field=models.ForeignKey(default='123', on_delete=django.db.models.deletion.CASCADE, to='course_assessment.course'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='chatlike',
            name='receiver',
            field=models.ForeignKey(default='123', on_delete=django.db.models.deletion.CASCADE, related_name='receiver', to=settings.AUTH_USER_MODEL),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='chat',
            name='classify',
            field=models.CharField(choices=[('user', '站内信'), ('system', '系统通知'), ('like', '点赞提醒'), ('reply', '回复提醒')], default='system'),
        ),
    ]