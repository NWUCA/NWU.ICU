# Generated by Django 4.2.14 on 2024-08-22 21:15

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course_assessment', '0015_review_deleted_at_review_is_deleted_and_more'),
        ('user', '0006_user_bio_alter_user_nwu_email'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='followed_courses',
            field=models.ManyToManyField(blank=True, related_name='followCourse', to='course_assessment.course'),
        ),
        migrations.AddField(
            model_name='user',
            name='following',
            field=models.ManyToManyField(related_name='followers', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='user',
            name='name',
            field=models.CharField(max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name='user',
            name='password',
            field=models.CharField(max_length=128, verbose_name='password'),
        ),
    ]
