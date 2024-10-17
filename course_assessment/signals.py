from Tools.demo.mcast import sender
from django.contrib.postgres.search import SearchVector
from django.db.models import Avg, Sum, Count
from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from pypinyin import lazy_pinyin

from common.models import ChatLike, ChatReply, Chat
from common.signals import soft_delete_signal
from user.models import User
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
        review.like_count = ReviewAndReplyLike.objects.filter(review=review, review_reply=None, like=1).count()
        review.dislike_count = ReviewAndReplyLike.objects.filter(review=review, review_reply=None, like=-1).count()
        review.save()

    if instance.review_reply is not None:
        review_reply = instance.review_reply
        review_reply.like_count = ReviewAndReplyLike.objects.filter(review_reply=review_reply, like=1).count()
        review_reply.dislike_count = ReviewAndReplyLike.objects.filter(review_reply=review_reply, like=-1).count()
        review_reply.save()


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
        chat_like, created = ChatLike.objects.get_or_create(raw_post_classify=raw_post_classify, raw_post_id=post.id)
        chat_like.like_count = post.like_count
        chat_like.dislike_count = post.dislike_count
        if chat_like.like_count == 0 and chat_like.dislike_count == 0:
            chat_like.delete()
            return
        chat_like.raw_post_id = post.id
        chat_like.raw_post_classify = raw_post_classify
        chat_like.raw_post_content = post.content
        chat_like.raw_post_course = post.course
        chat_like.latest_like_datetime = instance.create_time
        chat_like.receiver = post.created_by
        chat_like.save()


def update_chat_reply(instance: ReviewReply, created: bool):
    if created:
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
            ChatReply.objects.create(reply_content=instance, receiver=receiver_user,
                                     raw_post_classify=raw_post_classify,
                                     raw_post_id=raw_post_id, raw_post_content=raw_post_content,
                                     raw_post_course=raw_post_course, unread=True)
    else:
        if instance.parent is not None:
            receiver_user = instance.parent.created_by
        else:
            receiver_user = instance.review.created_by
    reply_notices_count = ChatReply.objects.filter(reply_content=instance, receiver=receiver_user).count()
    Chat.objects.update_or_create(receiver=receiver_user, classify='reply', sender=User.objects.get(id=1),
                                  unread_count=reply_notices_count)


@receiver(post_save, sender=ReviewReply)
def reply_saved(sender, instance, **kwargs):
    update_chat_reply(instance, created=True)


@receiver(post_delete, sender=ReviewReply)
def reply_deleted(sender, instance, **kwargs):
    update_chat_reply(instance, created=False)


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
