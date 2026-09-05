from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.utils import timezone


class Migration(migrations.Migration):
    dependencies = [
        ('common', '0038_remove_legacy_chat_models'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='resourceuploadrequest', name='publish_error', field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='resourceuploadrequest', name='revision', field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name='resourceuploadrequest',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, default=timezone.now),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='resourceuploadrequest', name='status',
            field=models.CharField(choices=[('pending', '未审核'), ('publishing', '发布中'), ('approved', '审核通过'), ('rejected', '审核拒绝'), ('publish_failed', '发布异常')], db_index=True, default='pending', max_length=16),
        ),
        migrations.AddField(
            model_name='resourceuploadfile', name='content_hash', field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name='resourceuploadfile', name='published_at', field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='resourceuploadfile', name='published_path', field=models.TextField(blank=True),
        ),
        migrations.CreateModel(
            name='ResourcePublishJob',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('revision', models.PositiveIntegerField()), ('target_path', models.TextField()),
                ('status', models.CharField(choices=[('pending', '待处理'), ('processing', '处理中'), ('retry', '等待重试'), ('succeeded', '已完成'), ('failed', '失败')], db_index=True, default='pending', max_length=16)),
                ('attempts', models.PositiveIntegerField(default=0)), ('available_at', models.DateTimeField()),
                ('locked_at', models.DateTimeField(blank=True, null=True)), ('last_error', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)), ('updated_at', models.DateTimeField(auto_now=True)),
                ('upload_request', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='publish_jobs', to='common.resourceuploadrequest')),
            ],
        ),
        migrations.AddConstraint(
            model_name='resourcepublishjob',
            constraint=models.UniqueConstraint(fields=('upload_request', 'revision'), name='unique_resource_publish_job_revision'),
        ),
        migrations.CreateModel(
            name='ResourceNotificationOutbox',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_key', models.CharField(max_length=255, unique=True)),
                ('channel', models.CharField(choices=[('telegram', 'Telegram'), ('site_message', '站内信'), ('email', '邮件')], max_length=24)),
                ('subject', models.CharField(blank=True, max_length=255)), ('body', models.TextField()),
                ('status', models.CharField(choices=[('pending', '待发送'), ('processing', '发送中'), ('retry', '等待重试'), ('sent', '已发送'), ('failed', '失败')], db_index=True, default='pending', max_length=16)),
                ('attempts', models.PositiveIntegerField(default=0)), ('available_at', models.DateTimeField()),
                ('locked_at', models.DateTimeField(blank=True, null=True)), ('sent_at', models.DateTimeField(blank=True, null=True)),
                ('last_error', models.TextField(blank=True)), ('created_at', models.DateTimeField(auto_now_add=True)), ('updated_at', models.DateTimeField(auto_now=True)),
                ('recipient', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('sender', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('upload_request', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='notification_outbox', to='common.resourceuploadrequest')),
            ],
        ),
    ]
