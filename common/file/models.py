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


class ResourceUploadRequest(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [
        (STATUS_PENDING, '未审核'),
        (STATUS_APPROVED, '审核通过'),
        (STATUS_REJECTED, '审核拒绝'),
    ]

    uploaded_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='resource_upload_requests')
    target_path = models.TextField()
    creates_new_folder = models.BooleanField(default=False)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    total_size = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_resource_upload_requests'
    )
    rejection_reason = models.TextField(blank=True)
    files_deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at',)

    def __str__(self):
        return f'#{self.pk} {self.uploaded_by.username} -> {self.target_path}'


class ResourceUploadFile(models.Model):
    upload_request = models.ForeignKey(ResourceUploadRequest, on_delete=models.CASCADE, related_name='files')
    file = models.FileField(upload_to='resource_uploads/%Y/%m/%d/')
    original_name = models.CharField(max_length=512)
    relative_path = models.TextField()
    size = models.BigIntegerField()

    def __str__(self):
        return self.relative_path
