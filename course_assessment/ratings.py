"""Rebuild persisted course scores from one consistent set of active reviews."""
from django.db import connections, transaction
from django.db.models import Count, Sum

from .models import Course, Review


def recalculate_course_ratings(*, using='default'):
    with transaction.atomic(using=using):
        connection = connections[using]
        if connection.vendor == 'postgresql':
            # Two-key namespace keeps this lock separate from file hash locks.
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_xact_lock(%s, %s)', [1129270867, 1380013129])
        # A single aggregate statement supplies both per-course and site totals.
        aggregates = list(
            Review.objects.using(using).order_by().values('course_id')
            .annotate(rating_sum=Sum('rating'), rating_count=Count('pk'))
        )
        course_count = len(aggregates)
        prior_sum = sum(row['rating_sum'] for row in aggregates) / course_count if course_count else 0.0
        prior_count = sum(row['rating_count'] for row in aggregates) / course_count if course_count else 0.0
        scores = {row['course_id']: row for row in aggregates}
        changed = []
        for course in Course.objects.using(using).only('pk', 'average_rating', 'normalized_rating').order_by('pk'):
            score = scores.get(course.pk)
            average = score['rating_sum'] / score['rating_count'] if score else 0.0
            normalized = (
                (score['rating_sum'] + prior_sum) / (score['rating_count'] + prior_count)
                if score else 0.0
            )
            if course.average_rating != average or course.normalized_rating != normalized:
                course.average_rating = average
                course.normalized_rating = normalized
                changed.append(course)
        Course.objects.using(using).bulk_update(changed, ('average_rating', 'normalized_rating'), batch_size=500)
        return len(changed)
