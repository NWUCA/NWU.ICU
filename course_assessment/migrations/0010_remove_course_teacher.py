# Generated by Django 4.0.3 on 2022-03-28 23:16

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course_assessment', '0009_semeseter_course_course_id_review_difficulty_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='course',
            name='teacher',
        ),
    ]