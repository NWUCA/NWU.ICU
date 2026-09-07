from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('common', '0041_resource_upload_directory_blacklist')]
    operations = [
        migrations.AlterModelOptions(
            name='resourceuploadrequest',
            options={
                'ordering': ('-created_at',),
                'permissions': [
                    ('review_resource_uploads', 'Can review resource uploads'),
                    ('manage_resource_files', 'Can manage published resource files'),
                ],
            },
        ),
    ]
