# Generated by Django 4.2.14 on 2024-08-01 15:41

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course_assessment', '0012_review_modify_time_reviewhistory'),
    ]

    operations = [
        migrations.RenameField(
            model_name='course',
            old_name='course_id',
            new_name='course_code',
        ),
    ]
