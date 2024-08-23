from django.conf import settings
from django.db import models
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
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='messages_sender')
    receiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name='messages_receiver')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['sender', 'receiver'],
                name='unique_chat_pair',
            ),
            models.UniqueConstraint(
                fields=['receiver', 'sender'],
                name='unique_chat_pair_reverse',
            ),
        ]

    def save(self, *args, **kwargs):
        if self.sender_id > self.receiver_id:
            self.sender, self.receiver = self.receiver, self.sender
        super().save(*args, **kwargs)


class Message(models.Model):
    TYPE_MESSAGE = [
        ('user', '站内信'),
        ('reply', '评论回复'),
        ('mention', '提及我的'),
        ('like', '收到的赞'),
        ('system', '系统通知')
    ]
    content = models.TextField()
    create_time = models.DateTimeField(auto_now_add=True)
    chat_item = models.ForeignKey(Chat, null=True, on_delete=models.CASCADE, related_name='messages')
    type = models.TextField(choices=TYPE_MESSAGE, default='system')
    read = models.BooleanField(default=False)


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
