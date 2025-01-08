import uuid

from django.db import models

from user.models import User


class UploadedFile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    file = models.FileField(upload_to='uploads/')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    file_hash = models.CharField(max_length=64, null=True)
    file_name = models.CharField(max_length=256, null=True)
    file_size = models.IntegerField(null=True)
    file_type = models.CharField(choices=[('avatar', 'Avatar'), ('file', 'File'), ('img', 'Image')], default='file')
    ref_count = models.IntegerField(default=0)
