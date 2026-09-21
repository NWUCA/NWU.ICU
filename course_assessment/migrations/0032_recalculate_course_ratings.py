from django.db import migrations
from django.db.models import Count, Sum


def rebuild_ratings(apps, schema_editor):
    # Frozen calculation deliberately uses historical models, not live signals.
    Course = apps.get_model('course_assessment', 'Course')
    Review = apps.get_model('course_assessment', 'Review')
    alias = schema_editor.connection.alias
    rows = list(
        Review.objects.using(alias).filter(is_deleted=False).order_by().values('course_id')
        .annotate(rating_sum=Sum('rating'), rating_count=Count('pk'))
    )
    count = len(rows)
    prior_sum = sum(row['rating_sum'] for row in rows) / count if count else 0.0
    prior_count = sum(row['rating_count'] for row in rows) / count if count else 0.0
    scores = {row['course_id']: row for row in rows}
    courses = list(Course.objects.using(alias).only('pk', 'average_rating', 'normalized_rating').order_by('pk'))
    for course in courses:
        score = scores.get(course.pk)
        course.average_rating = score['rating_sum'] / score['rating_count'] if score else 0.0
        course.normalized_rating = (
            (score['rating_sum'] + prior_sum) / (score['rating_count'] + prior_count) if score else 0.0
        )
    Course.objects.using(alias).bulk_update(courses, ('average_rating', 'normalized_rating'), batch_size=500)


class Migration(migrations.Migration):
    dependencies = [('course_assessment', '0031_expand_review_metric_scale')]

    operations = [migrations.RunPython(rebuild_ratings, migrations.RunPython.noop)]
