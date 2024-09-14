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
        ('system', '系统通知')
    ]
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='messages_sender')
    receiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name='messages_receiver')
    classify = models.CharField(choices=classify_MESSAGE, default='system')
    last_message_content = models.TextField(null=True, blank=True)
    last_message_datetime = models.DateTimeField(null=True)
    unread_count = models.IntegerField(default=0)

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
            models.Index(fields=['chat_item']),  # 添加索引到 chat_item 字段
            models.Index(fields=['create_time']),  # 添加索引到 create_time 字段，如果你经常按时间查询
        ]


class ChatReply(models.Model):
    content = models.ForeignKey('course_assessment.ReviewReply', on_delete=models.CASCADE)
    reply_classify = [
        ('review', '评价'),
        ('reply', '评论回复'),
    ]
    raw_post_classify = CharField(choices=reply_classify)
    raw_post = models.IntegerField()


class ChatLike(models.Model):
    reply_classify = [
        ('review', '评价'),
        ('reply', '评论回复'),
    ]
    raw_post_classify = CharField(choices=reply_classify)
    raw_post = models.IntegerField()
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
