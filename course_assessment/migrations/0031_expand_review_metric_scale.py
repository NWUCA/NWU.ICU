from django.db import migrations, models


FORWARD_VALUES = {1: 1, 2: 3, 3: 5}
REVERSE_VALUES = {1: 1, 2: 1, 3: 2, 4: 3, 5: 3}
METRIC_FIELDS = ('difficulty', 'grade', 'homework', 'reward')


def migrate_to_five_levels(apps, schema_editor):
    Review = apps.get_model('course_assessment', 'Review')
    for review in Review._base_manager.all().iterator():
        for field in METRIC_FIELDS:
            setattr(review, field, FORWARD_VALUES[getattr(review, field)])
        review.save(update_fields=METRIC_FIELDS)


def migrate_to_three_levels(apps, schema_editor):
    Review = apps.get_model('course_assessment', 'Review')
    for review in Review._base_manager.all().iterator():
        for field in METRIC_FIELDS:
            setattr(review, field, REVERSE_VALUES[getattr(review, field)])
        review.save(update_fields=METRIC_FIELDS)


class Migration(migrations.Migration):
    dependencies = [
        ('course_assessment', '0030_secure_review_reply_likes'),
    ]

    operations = [
        migrations.AlterField(
            model_name='review',
            name='difficulty',
            field=models.PositiveSmallIntegerField(choices=[(1, '很简单'), (2, '较简单'), (3, '适中'), (4, '较难'), (5, '很难')], verbose_name='课程难度'),
        ),
        migrations.AlterField(
            model_name='review',
            name='grade',
            field=models.PositiveSmallIntegerField(choices=[(1, '很严'), (2, '偏严'), (3, '一般'), (4, '偏宽'), (5, '很宽')], verbose_name='给分高低'),
        ),
        migrations.AlterField(
            model_name='review',
            name='homework',
            field=models.PositiveSmallIntegerField(choices=[(1, '很少'), (2, '较少'), (3, '适中'), (4, '较多'), (5, '很多')], verbose_name='作业负担'),
        ),
        migrations.AlterField(
            model_name='review',
            name='reward',
            field=models.PositiveSmallIntegerField(choices=[(1, '很少'), (2, '较少'), (3, '一般'), (4, '较多'), (5, '很多')], verbose_name='收获多少'),
        ),
        migrations.RunPython(migrate_to_five_levels, migrate_to_three_levels),
    ]
