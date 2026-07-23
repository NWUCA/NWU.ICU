from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0010_user_private_reply_user_private_review'),
        ('common', '0033_alter_about_type'),
    ]

    operations = [
        migrations.CreateModel(
            name='ResourceUploadRequest',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('target_path', models.TextField()),
                ('status', models.CharField(choices=[('pending', '未审核'), ('approved', '审核通过'), ('rejected', '审核拒绝')], db_index=True, default='pending', max_length=16)),
                ('total_size', models.BigIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('rejection_reason', models.TextField(blank=True)),
                ('files_deleted_at', models.DateTimeField(blank=True, null=True)),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reviewed_resource_upload_requests', to='user.user')),
                ('uploaded_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='resource_upload_requests', to='user.user')),
            ],
            options={'ordering': ('-created_at',)},
        ),
        migrations.CreateModel(
            name='ResourceUploadFile',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file', models.FileField(upload_to='resource_uploads/%Y/%m/%d/')),
                ('original_name', models.CharField(max_length=512)),
                ('relative_path', models.TextField()),
                ('size', models.BigIntegerField()),
                ('upload_request', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='files', to='common.resourceuploadrequest')),
            ],
        ),
    ]
