from django.db.models import Avg, Sum, Count
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Review, Course


@receiver([post_save, post_delete], sender=Review)
def update_course_average_rating(sender, instance, **kwargs):
    course = instance.course
    reviews = Review.objects.filter(course=course)
    average_rating = reviews.aggregate(Avg('rating'))['rating__avg'] or 0.0
    course.average_rating = average_rating
    course.save()


@receiver([post_save, post_delete], sender=Review)
def update_course_normalized_avg_rating(sender, instance, **kwargs):
    course = instance.course
    reviews = Review.objects.filter(course=course)
    average_rating = reviews.aggregate(Avg('rating'))['rating__avg'] or 0.0

    # 计算归一化平均分
    total_courses = Course.objects.filter(review__isnull=False).distinct().count()
    site_avg_rating = Review.objects.aggregate(Avg('rating'))['rating__avg'] or 0.0
    site_avg_reviews_count = Review.objects.values('course').annotate(count=Count('id')).aggregate(Avg('count'))[
                                 'count__avg'] or 0.0

    if total_courses > 0 and site_avg_reviews_count > 0:
        normalized_rating = (((reviews.aggregate(Sum('rating'))['rating__sum'] or 0) +
                              (site_avg_rating * site_avg_reviews_count)) /
                             (reviews.count() + site_avg_reviews_count))
    else:
        normalized_rating = average_rating  # 如果没有全站数据，用课程自身平均分

    course.average_rating = average_rating
    course.normalized_rating = normalized_rating
    course.save()
