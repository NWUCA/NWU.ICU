# Generated by Django 4.2.14 on 2025-01-08 23:13

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('common', '0027_uploadedfile_file_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='uploadedfile',
            name='ref_count',
            field=models.IntegerField(default=0),
        ),
    ]
