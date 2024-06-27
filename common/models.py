from django.conf import settings
from django.db import models


class Announcement(models.Model):
    TYPE_CHOICES = [
        ('all', '全局'),
        ('course', '课程评价'),
        ('report', '自动填报'),
    ]

    content = models.TextField()
    type = models.TextField(choices=TYPE_CHOICES)
    create_time = models.DateTimeField(auto_now_add=True)
    update_time = models.DateTimeField(auto_now=True)
    enabled = models.BooleanField(default=True)


class Bulletins(models.Model):
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
