# Generated by Django 4.2.14 on 2024-12-31 19:44

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0008_rename_nwu_email_user_college_email'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='college_email_verified',
            field=models.BooleanField(default=False),
        ),
    ]
