from django.conf import settings
from django.db import models
from django.db.models import CharField
from django.utils import timezone

from user.models import User
from .signals import soft_delete_signal


class Announcement(models.Model):
    TYPE_CHOICES = [
        ('all', '全局'),
        ('course', '课程评价'),
    ]

    content = models.TextField()
    type = models.TextField(choices=TYPE_CHOICES)
    create_time = models.DateTimeField(auto_now_add=True)
    update_time = models.DateTimeField(auto_now=True)
    enabled = models.BooleanField(default=True)


class Bulletin(models.Model):
    title = models.TextField()
    content = models.TextField()
    create_time = models.DateTimeField(auto_now_add=True)
    update_time = models.DateTimeField(auto_now=True)
    enabled = models.BooleanField(default=True)
    publisher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)


class WebPushSubscription(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    update_time = models.DateTimeField(auto_now=True)
    subscription = models.JSONField()


class About(models.Model):
    TYPE_CHOICES = [
        ('about', '关于'),
        ('tos', '服务条款'),
    ]
    content = models.TextField()
    create_time = models.DateTimeField(auto_now_add=True)
    update_time = models.DateTimeField(auto_now=True)
    type = models.TextField(choices=TYPE_CHOICES, default='about')


class Chat(models.Model):
    classify_MESSAGE = [
        ('user', '站内信'),
        ('system', '系统通知'),
        ('like', '点赞提醒'),
        ('reply', '回复提醒')
    ]
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='messages_sender', null=True)
    receiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name='messages_receiver')
    classify = models.CharField(choices=classify_MESSAGE, default='system')
    last_message_content = models.TextField(null=True, blank=True)
    last_message_datetime = models.DateTimeField(null=True)
    receiver_unread_count = models.IntegerField(default=0)
    sender_unread_count = models.IntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['sender', 'receiver', 'classify'],
                name='unique_chat_pair',
            ),
            models.UniqueConstraint(
                fields=['receiver', 'sender', 'classify'],
                name='unique_chat_pair_reverse',
            ),
        ]

    def save(self, *args, **kwargs):
        if self.sender_id > self.receiver_id:
            self.sender, self.receiver = self.receiver, self.sender
            self.sender_unread_count, self.receiver_unread_count = self.receiver_unread_count, self.sender_unread_count
        super().save(*args, **kwargs)

    @classmethod
    def get_or_create_chat(cls, sender, receiver, classify):
        if sender.id > receiver.id:
            sender, receiver = receiver, sender
        return cls.objects.get_or_create(sender=sender, receiver=receiver, classify=classify)


class ChatMessage(models.Model):
    content = models.TextField()
    create_time = models.DateTimeField(auto_now_add=True)
    chat_item = models.ForeignKey(Chat, null=True, on_delete=models.CASCADE, related_name='messages')
    read = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=['chat_item']),
            models.Index(fields=['create_time']),
        ]


class ChatReply(models.Model):
    unread = models.BooleanField(default=True)
    reply_content = models.ForeignKey('course_assessment.ReviewReply', on_delete=models.CASCADE)
    reply_classify = [
        ('review', '关于评价的回复'),
        ('reply', '楼中楼的回复'),
    ]
    receiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reply_notice_receiver')
    raw_post_classify = CharField(choices=reply_classify)
    raw_post_id = models.IntegerField()
    raw_post_content = models.TextField()
    raw_post_course = models.ForeignKey('course_assessment.Course', on_delete=models.CASCADE)


class ChatLike(models.Model):
    reply_classify = [
        ('review', '评价'),
        ('reply', '评论回复'),
    ]
    raw_post_classify = CharField(choices=reply_classify)
    raw_post_id = models.IntegerField(null=True)
    raw_post_course = models.ForeignKey('course_assessment.Course', on_delete=models.CASCADE, null=True)
    raw_post_content = models.TextField(null=True)
    receiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name='like_notice_receiver', null=True)
    like_count = models.IntegerField(default=0)
    dislike_count = models.IntegerField(default=0)
    latest_like_datetime = models.DateTimeField(null=True)


class SoftDeleteManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class SoftDeleteModel(models.Model):
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    def soft_delete(self):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save()
        soft_delete_signal.send(sender=self.__class__, instance=self)

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.save()

    class Meta:
        abstract = True
