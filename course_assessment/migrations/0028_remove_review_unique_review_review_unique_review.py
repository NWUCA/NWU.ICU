# Generated by Django 4.2.14 on 2024-12-10 02:00

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course_assessment', '0027_teacher_avatar_uuid'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='review',
            name='unique_review',
        ),
        migrations.AddConstraint(
            model_name='review',
            constraint=models.UniqueConstraint(condition=models.Q(('is_deleted', False)), fields=('course', 'created_by'), name='unique_review'),
        ),
    ]