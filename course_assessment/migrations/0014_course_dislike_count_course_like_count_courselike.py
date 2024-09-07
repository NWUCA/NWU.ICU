# Generated by Django 4.2.14 on 2024-08-13 21:25

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('course_assessment', '0013_rename_course_id_course_course_code_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='course',
            name='dislike_count',
            field=models.IntegerField(default=0, verbose_name='不推荐'),
        ),
        migrations.AddField(
            model_name='course',
            name='like_count',
            field=models.IntegerField(default=0, verbose_name='推荐'),
        ),
        migrations.CreateModel(
            name='CourseLike',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('create_time', models.DateTimeField(auto_now_add=True)),
                ('like', models.SmallIntegerField(default=0, null=True)),
                ('course', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='course_assessment.course')),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]