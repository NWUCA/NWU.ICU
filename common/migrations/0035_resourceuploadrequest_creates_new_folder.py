from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('common', '0034_resourceuploadrequest_resourceuploadfile'),
    ]

    operations = [
        migrations.AddField(
            model_name='resourceuploadrequest',
            name='creates_new_folder',
            field=models.BooleanField(default=False),
        ),
    ]
