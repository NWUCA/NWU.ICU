from enum import Enum

from django.contrib.postgres.search import SearchVector
from django.core.cache import cache
from django.db.models import Avg, Sum, Count
from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from pypinyin import lazy_pinyin

from common.models import Notification
from common.signals import soft_delete_signal
from utils.utils import get_cache_key, get_user_avatar_info
from .models import Review, Course, ReviewAndReplyLike, CourseLike, Teacher, ReviewReply


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
    if instance.review and instance.review_reply is None:
        review = instance.review
        like_count = ReviewAndReplyLike.objects.filter(review=review, review_reply=None, like=1).count()
        dislike_count = ReviewAndReplyLike.objects.filter(review=review, review_reply=None, like=-1).count()
        Review.all_objects.filter(pk=review.pk).update(
            like_count=like_count,
            dislike_count=dislike_count,
        )
        review.like_count = like_count
        review.dislike_count = dislike_count

    if instance.review_reply is not None:
        review_reply = instance.review_reply
        like_count = ReviewAndReplyLike.objects.filter(review_reply=review_reply, like=1).count()
        dislike_count = ReviewAndReplyLike.objects.filter(review_reply=review_reply, like=-1).count()
        ReviewReply.all_objects.filter(pk=review_reply.pk).update(
            like_count=like_count,
            dislike_count=dislike_count,
        )
        review_reply.like_count = like_count
        review_reply.dislike_count = dislike_count


def update_course_like_dislike_counts(instance):
    course = instance.course
    course.like_count = CourseLike.objects.filter(course=course, like=1).count()
    course.dislike_count = CourseLike.objects.filter(course=course, like=-1).count()
    course.save()


def update_chat_like_counts(instance: ReviewAndReplyLike, sender):
    like_create_by = instance.created_by
    if instance.review or instance.review_reply:
        post = instance.review_reply if instance.review_reply is not None else instance.review
        raw_post_classify = 'reply' if instance.review_reply is not None else 'review'
        if post.created_by == like_create_by:
            return
        dedupe_key = f'like:{raw_post_classify}:{post.id}:{post.created_by_id}'
        if post.like_count == 0 and post.dislike_count == 0:
            Notification.objects.filter(dedupe_key=dedupe_key).delete()
            return
        course = post.review.course if instance.review_reply is not None else post.course
        Notification.objects.update_or_create(
            dedupe_key=dedupe_key,
            defaults={
                'recipient': post.created_by,
                'actor': None,
                'kind': Notification.KIND_LIKE,
                'read_at': None,
                'payload': {
                    'raw_info': {
                        'raw_post': {
                            'classify': raw_post_classify,
                            'id': post.id,
                            'content': post.content,
                        },
                        'course': {'id': course.id, 'name': course.name},
                    },
                    'like': {'like': post.like_count, 'dislike': post.dislike_count},
                    'datetime': instance.create_time.isoformat(),
                },
            },
        )


class Operate(Enum):
    ADD = 'add'
    DELETE = 'delete'


def update_chat_reply(instance: ReviewReply, operate: Operate):
    # if operate == Operate.ADD:
    if instance.parent is not None:
        parent = instance.parent
        raw_post_id = parent.id
        raw_post_classify = 'reply'
        raw_post_content = parent.content
        raw_post_course = parent.review.course
        receiver_user = parent.created_by
    else:
        raw_post_id = instance.review_id
        raw_post_classify = 'review'
        raw_post_content = instance.review.content
        raw_post_course = instance.review.course
        receiver_user = instance.review.created_by
    if instance.created_by != receiver_user:
        if operate == Operate.ADD:
            dedupe_key = f'reply:{instance.id}:{receiver_user.id}'
            notification, created = Notification.objects.get_or_create(
                dedupe_key=dedupe_key,
                defaults={
                    'recipient': receiver_user,
                    'actor': instance.created_by,
                    'kind': Notification.KIND_REPLY,
                    'payload': {},
                },
            )
            notification.recipient = receiver_user
            notification.actor = instance.created_by
            notification.kind = Notification.KIND_REPLY
            notification.payload = {
                'reply': {'id': instance.id, 'content': instance.content},
                'created_by': {
                    'id': instance.created_by.id,
                    'nickname': instance.created_by.nickname,
                    **get_user_avatar_info(instance.created_by),
                },
                'course': {'id': raw_post_course.id, 'name': raw_post_course.name},
                'raw_post': {
                    'id': raw_post_id,
                    'classify': raw_post_classify,
                    'content': raw_post_content,
                },
                'datetime': instance.create_time.isoformat(),
            }
            notification.save(update_fields=(
                'recipient', 'actor', 'kind', 'payload', 'updated_at',
            ))
        elif operate == Operate.DELETE:
            Notification.objects.filter(
                dedupe_key=f'reply:{instance.id}:{receiver_user.id}'
            ).delete()


@receiver(post_save, sender=ReviewReply)
def reply_saved(sender, instance, **kwargs):
    update_chat_reply(
        instance,
        operate=Operate.DELETE if instance.is_deleted else Operate.ADD,
    )


# @receiver(post_delete, sender=ReviewReply)
# def reply_deleted(sender, instance, **kwargs):
#     update_chat_reply(instance, operate=Operate.DELETE)


@receiver(post_save, sender=ReviewAndReplyLike)
@receiver(post_delete, sender=ReviewAndReplyLike)
def review_and_reply_like_changed(sender, instance, **kwargs):
    update_review_reply_like_dislike_counts(instance)
    update_chat_like_counts(instance, sender)


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
    course.review_count = Review.objects.filter(course=course).count()
    course.last_review_time = instance.modify_time
    course.save()


@receiver(pre_save, sender=Teacher)
def update_teacher_pinyin_and_vector(sender, instance, **kwargs):
    instance.pinyin = ''.join(lazy_pinyin(instance.name))


@receiver(pre_save, sender=Course)
def update_course_pinyin_and_vector(sender, instance, **kwargs):
    instance.pinyin = ''.join(lazy_pinyin(instance.name))


@receiver(post_save, sender=Course)
@receiver(post_delete, sender=Course)
def update_course_count(sender, instance, **kwargs):
    course_classification = instance.classification
    course_total_key = get_cache_key('total_courses_count')
    course_classify_total_key = course_total_key + course_classification
    course_classify_total = Course.objects.filter(classification=course_classification).count()
    cache.set(course_classify_total_key, course_classify_total, timeout=None)
    course_total = Course.objects.count()
    cache.set(course_total_key, course_total, timeout=None)


@receiver(post_save, sender=Review)
@receiver(soft_delete_signal, sender=Review)
def update_review_count(sender, instance, **kwargs):
    review_total_key = get_cache_key('total_review_count')
    review_total = Review.objects.count()
    cache.set(review_total_key, review_total, timeout=None)


@receiver(pre_save, sender=Review)
def update_review_pinyin_and_vector(sender, instance, **kwargs):
    instance.pinyin = ''.join(lazy_pinyin(instance.content))


@receiver(post_save, sender=Teacher)
def update_teacher_search_vector(sender, instance, **kwargs):
    Teacher.objects.filter(pk=instance.pk).update(
        search_vector=SearchVector('name', weight='A') + SearchVector('pinyin', weight='B')
    )


@receiver(post_save, sender=Course)
def update_course_search_vector(sender, instance, **kwargs):
    Course.objects.filter(pk=instance.pk).update(
        search_vector=SearchVector('name', weight='A') + SearchVector('pinyin', weight='B')
    )


@receiver(post_save, sender=Review)
def update_review_search_vector(sender, instance, **kwargs):
    Review.objects.filter(pk=instance.pk).update(
        search_vector=SearchVector('content', weight='A') + SearchVector('pinyin', weight='B')
    )
