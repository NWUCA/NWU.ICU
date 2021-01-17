from django.db import models
from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    name = models.TextField()
    cookie = models.JSONField()
    cookie_last_update = models.DateTimeField()

    REQUIRED_FIELDS = []
