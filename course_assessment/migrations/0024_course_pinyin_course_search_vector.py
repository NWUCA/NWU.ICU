# Generated by Django 4.2.14 on 2024-09-29 17:52

import django.contrib.postgres.search
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course_assessment', '0023_course_review_count'),
    ]

    operations = [
        migrations.AddField(
            model_name='course',
            name='pinyin',
            field=models.CharField(blank=True, max_length=100, verbose_name='拼音'),
        ),
        migrations.AddField(
            model_name='course',
            name='search_vector',
            field=django.contrib.postgres.search.SearchVectorField(null=True),
        ),
    ]
