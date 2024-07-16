import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    name = models.TextField(null=True)
    password = models.CharField(max_length=255)  # A RequestsCookieJar object in requests
    nickname = models.CharField(max_length=30)
    nwu_email = models.CharField(max_length=255, null=True)
    avatar_uuid = models.UUIDField(default=uuid.uuid4, editable=False)
    REQUIRED_FIELDS = []
