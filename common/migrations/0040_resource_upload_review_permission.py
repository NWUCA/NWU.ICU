from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('common', '0039_resource_upload_workflow')]

    operations = [
        migrations.AlterModelOptions(
            name='resourceuploadrequest',
            options={
                'ordering': ('-created_at',),
                'permissions': [('review_resource_uploads', 'Can review resource uploads')],
            },
        ),
    ]

