from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('common', '0044_resource_download_dimensions'),
    ]

    operations = [
        migrations.AddField(
            model_name='resourcenotificationoutbox',
            name='aggregation_key',
            field=models.CharField(blank=True, db_index=True, max_length=255),
        ),
    ]
