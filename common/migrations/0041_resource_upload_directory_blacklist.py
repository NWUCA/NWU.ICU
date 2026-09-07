from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('common', '0040_resource_upload_review_permission')]

    operations = [
        migrations.CreateModel(
            name='ResourceUploadDirectoryBlacklist',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('path', models.CharField(max_length=2048, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ('path',),
                'verbose_name': '投稿文件夹黑名单',
                'verbose_name_plural': '投稿文件夹黑名单',
            },
        ),
    ]
