from django.db import models

from user.models import User


class UploadedFile(models.Model):
    file_path = models.TextField()
    uploaded_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    file_name = models.CharField(max_length=256, null=True)
    file_size = models.IntegerField(null=True)
    check = models.BooleanField(default=True)
