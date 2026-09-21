from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('common', '0045_resourcenotificationoutbox_aggregation_key')]

    operations = [
        migrations.AddField(
            model_name='resourcenotificationoutbox',
            name='result_snapshot',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
