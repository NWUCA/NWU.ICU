from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    name = models.TextField(null=True)
    password = models.CharField(max_length=255)  # A RequestsCookieJar object in requests
    nickname = models.CharField(max_length=30)
    nwu_email = models.CharField(max_length=255, null=True)
    REQUIRED_FIELDS = []


class VerificationCode(models.Model):
    email = models.EmailField(unique=True)
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.email
