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


class ResourceUploadDirectoryBlacklist(models.Model):
    path = models.CharField(max_length=2048, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('path',)
        verbose_name = '投稿文件夹黑名单'
        verbose_name_plural = verbose_name


class ResourceUploadRequest(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_PUBLISHING = 'publishing'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_PUBLISH_FAILED = 'publish_failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, '未审核'),
        (STATUS_PUBLISHING, '发布中'),
        (STATUS_APPROVED, '审核通过'),
        (STATUS_REJECTED, '审核拒绝'),
        (STATUS_PUBLISH_FAILED, '发布异常'),
    ]

    uploaded_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='resource_upload_requests')
    target_path = models.TextField()
    creates_new_folder = models.BooleanField(default=False)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    total_size = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    revision = models.PositiveIntegerField(default=1)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_resource_upload_requests'
    )
    rejection_reason = models.TextField(blank=True)
    publish_error = models.TextField(blank=True)
    files_deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at',)
        permissions = [
            ('review_resource_uploads', 'Can review resource uploads'),
            ('manage_resource_files', 'Can manage published resource files'),
        ]

    def __str__(self):
        return f'#{self.pk} {self.uploaded_by.username} -> {self.target_path}'


class ResourceUploadFile(models.Model):
    upload_request = models.ForeignKey(ResourceUploadRequest, on_delete=models.CASCADE, related_name='files')
    file = models.FileField(upload_to='resource_uploads/%Y/%m/%d/')
    original_name = models.CharField(max_length=512)
    relative_path = models.TextField()
    size = models.BigIntegerField()
    content_hash = models.CharField(max_length=64, blank=True)
    published_path = models.TextField(blank=True)
    published_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.relative_path


class ResourcePublishJob(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_PROCESSING = 'processing'
    STATUS_RETRY = 'retry'
    STATUS_SUCCEEDED = 'succeeded'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, '待处理'),
        (STATUS_PROCESSING, '处理中'),
        (STATUS_RETRY, '等待重试'),
        (STATUS_SUCCEEDED, '已完成'),
        (STATUS_FAILED, '失败'),
    ]

    upload_request = models.ForeignKey(ResourceUploadRequest, on_delete=models.CASCADE, related_name='publish_jobs')
    revision = models.PositiveIntegerField()
    target_path = models.TextField()
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    available_at = models.DateTimeField()
    locked_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=('upload_request', 'revision'), name='unique_resource_publish_job_revision'),
        ]


class ResourceNotificationOutbox(models.Model):
    CHANNEL_TELEGRAM = 'telegram'
    CHANNEL_SITE_MESSAGE = 'site_message'
    CHANNEL_EMAIL = 'email'
    CHANNEL_CHOICES = [
        (CHANNEL_TELEGRAM, 'Telegram'),
        (CHANNEL_SITE_MESSAGE, '站内信'),
        (CHANNEL_EMAIL, '邮件'),
    ]
    STATUS_PENDING = 'pending'
    STATUS_PROCESSING = 'processing'
    STATUS_RETRY = 'retry'
    STATUS_SENT = 'sent'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, '待发送'),
        (STATUS_PROCESSING, '发送中'),
        (STATUS_RETRY, '等待重试'),
        (STATUS_SENT, '已发送'),
        (STATUS_FAILED, '失败'),
    ]

    event_key = models.CharField(max_length=255, unique=True)
    upload_request = models.ForeignKey(
        ResourceUploadRequest, on_delete=models.CASCADE, null=True, blank=True, related_name='notification_outbox'
    )
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='+')
    sender = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    channel = models.CharField(max_length=24, choices=CHANNEL_CHOICES)
    subject = models.CharField(max_length=255, blank=True)
    body = models.TextField()
    aggregation_key = models.CharField(max_length=255, blank=True, db_index=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    available_at = models.DateTimeField()
    locked_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
