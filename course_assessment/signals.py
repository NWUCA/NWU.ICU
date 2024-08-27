from django.contrib.postgres.search import SearchVector
from django.db.models import Avg, Sum, Count
from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from pypinyin import lazy_pinyin

from common.signals import soft_delete_signal
from .models import Review, Course, ReviewAndReplyLike, CourseLike, Teacher


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


def update_review_reply_like_dislike_counts(instance):
    if instance.review and not instance.review_reply:
        review = instance.review
        review.like_count = ReviewAndReplyLike.objects.filter(review=review, like=1).count()
        review.dislike_count = ReviewAndReplyLike.objects.filter(review=review, like=-1).count()
        review.save()

    if instance.review_reply:
        review_reply = instance.review_reply
        review_reply.like_count = ReviewAndReplyLike.objects.filter(review_reply=review_reply, like=1).count()
        review_reply.dislike_count = ReviewAndReplyLike.objects.filter(review_reply=review_reply, like=-1).count()
        review_reply.save()


def update_course_like_dislike_counts(instance):
    course = instance.course
    course.like_count = CourseLike.objects.filter(course=course, like=1).count()
    course.dislike_count = CourseLike.objects.filter(course=course, like=-1).count()
    course.save()


@receiver(post_save, sender=ReviewAndReplyLike)
@receiver(post_delete, sender=ReviewAndReplyLike)
def review_and_reply_like_changed(sender, instance, **kwargs):
    update_review_reply_like_dislike_counts(instance)


@receiver(post_save, sender=CourseLike)
@receiver(post_delete, sender=CourseLike)
def course_like_changed(sender, instance, **kwargs):
    update_course_like_dislike_counts(instance)


@receiver(post_save, sender=Review)
@receiver(soft_delete_signal, sender=Review)
def review_created(sender, instance, **kwargs):
    course = instance.course
    reviews_of_courses = Review.objects.filter(course=course)
    semesters = {review.semester for review in reviews_of_courses}
    course.semester.set(semesters)
    course.last_review_time = instance.modify_time
    course.save()


@receiver(pre_save, sender=Teacher)
def update_teacher_pinyin_and_vector(sender, instance, **kwargs):
    instance.pinyin = ''.join(lazy_pinyin(instance.name))


@receiver(post_save, sender=Teacher)
def update_search_vector(sender, instance, **kwargs):
    Teacher.objects.filter(pk=instance.pk).update(
        search_vector=SearchVector('name', weight='A') + SearchVector('pinyin', weight='B')
    )
