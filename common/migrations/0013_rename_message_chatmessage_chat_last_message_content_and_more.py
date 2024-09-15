# Generated by Django 4.2.14 on 2024-09-14 22:53

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('course_assessment', '0023_course_review_count'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('common', '0012_rename_type_chat_classify'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='Message',
            new_name='ChatMessage',
        ),
        migrations.AddField(
            model_name='chat',
            name='last_message_content',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='chat',
            name='last_message_datetime',
            field=models.DateTimeField(null=True),
        ),
        migrations.AlterField(
            model_name='chat',
            name='classify',
            field=models.CharField(choices=[('user', '站内信'), ('system', '系统通知')], default='system'),
        ),
        migrations.CreateModel(
            name='ChatReply',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('raw_post_classify', models.CharField(choices=[('review', '评价'), ('reply', '评论回复')])),
                ('raw_post', models.IntegerField()),
                ('content', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='course_assessment.reviewreply')),
            ],
        ),
        migrations.CreateModel(
            name='ChatLike',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('raw_post_classify', models.CharField(choices=[('review', '评价'), ('reply', '评论回复')])),
                ('raw_post', models.IntegerField()),
                ('like_count', models.IntegerField(default=0)),
                ('dislike_count', models.IntegerField(default=0)),
                ('dislike_latest_user', models.ManyToManyField(related_name='dislike_latest_user', to=settings.AUTH_USER_MODEL)),
                ('like_latest_user', models.ManyToManyField(related_name='like_latest_user', to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]