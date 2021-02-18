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
