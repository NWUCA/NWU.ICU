# Generated by Django 4.2.14 on 2024-08-23 17:27

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course_assessment', '0015_review_deleted_at_review_is_deleted_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='course',
            name='last_review_time',
            field=models.DateTimeField(null=True),
        ),
    ]