from django.db import migrations, models
from django.db.models import Count, Min, Q


def clean_duplicate_and_invalid_likes(apps, schema_editor):
    Like = apps.get_model('course_assessment', 'ReviewAndReplyLike')
    Like.objects.exclude(like__in=(-1, 1)).delete()

    duplicate_reviews = (
        Like.objects.filter(review_reply__isnull=True)
        .values('review_id', 'created_by_id')
        .annotate(keep_id=Min('id'), row_count=Count('id'))
        .filter(row_count__gt=1)
    )
    for duplicate in duplicate_reviews.iterator():
        Like.objects.filter(
            review_id=duplicate['review_id'],
            created_by_id=duplicate['created_by_id'],
            review_reply__isnull=True,
        ).exclude(pk=duplicate['keep_id']).delete()

    duplicate_replies = (
        Like.objects.filter(review_reply__isnull=False)
        .values('review_reply_id', 'created_by_id')
        .annotate(keep_id=Min('id'), row_count=Count('id'))
        .filter(row_count__gt=1)
    )
    for duplicate in duplicate_replies.iterator():
        Like.objects.filter(
            review_reply_id=duplicate['review_reply_id'],
            created_by_id=duplicate['created_by_id'],
        ).exclude(pk=duplicate['keep_id']).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('course_assessment', '0029_alter_course_average_rating_and_more'),
    ]

    operations = [
        migrations.RunPython(clean_duplicate_and_invalid_likes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='reviewandreplylike',
            name='like',
            field=models.SmallIntegerField(default=1),
        ),
        migrations.AddConstraint(
            model_name='reviewandreplylike',
            constraint=models.UniqueConstraint(
                fields=('review', 'created_by'),
                condition=Q(review_reply__isnull=True),
                name='unique_review_like_per_user',
            ),
        ),
        migrations.AddConstraint(
            model_name='reviewandreplylike',
            constraint=models.UniqueConstraint(
                fields=('review_reply', 'created_by'),
                condition=Q(review_reply__isnull=False),
                name='unique_reply_like_per_user',
            ),
        ),
        migrations.AddConstraint(
            model_name='reviewandreplylike',
            constraint=models.CheckConstraint(
                check=Q(like__in=(-1, 1)),
                name='valid_review_reply_like_value',
            ),
        ),
    ]
