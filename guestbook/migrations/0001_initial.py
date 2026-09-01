# Generated manually for the guestbook application.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='GuestbookEntry',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('is_deleted', models.BooleanField(default=False)),
                ('deleted_at', models.DateTimeField(blank=True, null=True)),
                ('content', models.TextField()),
                ('anonymous', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('like_count', models.PositiveIntegerField(default=0)),
                ('author', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
                ('parent', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='replies', to='guestbook.guestbookentry')),
                ('root', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='descendants', to='guestbook.guestbookentry')),
            ],
            options={'ordering': ('-created_at', '-id')},
        ),
        migrations.CreateModel(
            name='GuestbookReport',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('reason', models.CharField(choices=[('spam', '垃圾广告'), ('abuse', '攻击辱骂'), ('privacy', '泄露隐私'), ('other', '其他')], max_length=16)),
                ('detail', models.CharField(blank=True, max_length=500)),
                ('status', models.CharField(choices=[('pending', '待处理'), ('dismissed', '已驳回'), ('removed', '已移除内容')], default='pending', max_length=16)),
                ('handling_note', models.CharField(blank=True, max_length=500)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('handled_at', models.DateTimeField(blank=True, null=True)),
                ('entry', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reports', to='guestbook.guestbookentry')),
                ('handled_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='handled_guestbook_reports', to=settings.AUTH_USER_MODEL)),
                ('reporter', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='GuestbookLike',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('entry', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='likes', to='guestbook.guestbookentry')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddIndex(model_name='guestbookentry', index=models.Index(fields=['root', 'parent', 'created_at'], name='guestbook_reply_tree_idx')),
        migrations.AddIndex(model_name='guestbookentry', index=models.Index(fields=['-created_at', '-id'], name='guestbook_recent_idx')),
        migrations.AddConstraint(model_name='guestbooklike', constraint=models.UniqueConstraint(fields=('entry', 'user'), name='unique_guestbook_like_per_user')),
        migrations.AddConstraint(model_name='guestbookreport', constraint=models.UniqueConstraint(fields=('entry', 'reporter'), name='unique_guestbook_report_per_user')),
        migrations.AddIndex(model_name='guestbookreport', index=models.Index(fields=['status', '-created_at'], name='guestbook_report_status_idx')),
    ]
