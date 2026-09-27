"""Shared ZIP artifacts and private receipts (no public cache URLs)."""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class ResourceArchiveState(models.Model):
    # A singleton row serializes admission, reservations and cache eviction.
    id = models.PositiveSmallIntegerField(primary_key=True, default=1)


class ResourceArchive(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cache_key = models.CharField(max_length=64, db_index=True)
    manifest = models.JSONField(default=list)
    status = models.CharField(max_length=16, default='queued', db_index=True)
    source_bytes = models.BigIntegerField(default=0)
    reserved_bytes = models.BigIntegerField(default=0)
    zip_bytes = models.BigIntegerField(default=0)
    processed_bytes = models.BigIntegerField(default=0)
    processed_files = models.PositiveIntegerField(default=0)
    creator = models.CharField(max_length=64, db_index=True)
    ip_digest = models.CharField(max_length=64, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    started_at = models.DateTimeField(null=True)
    heartbeat_at = models.DateTimeField(null=True)
    completed_at = models.DateTimeField(null=True)
    last_used_at = models.DateTimeField(null=True)
    expires_at = models.DateTimeField(null=True, db_index=True)
    message = models.CharField(max_length=300, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['cache_key'], condition=Q(status__in=['queued', 'running', 'ready']),
            name='unique_live_resource_archive')]


class ResourceArchiveReceipt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    archive = models.ForeignKey(ResourceArchive, on_delete=models.CASCADE, related_name='receipts')
    actor = models.CharField(max_length=64, db_index=True)
    browser = models.CharField(max_length=64, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE)
    request_key = models.UUIDField()
    cancelled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['actor', 'request_key'], name='unique_archive_request')]


class ResourceArchiveNotice(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    count = models.PositiveIntegerField(default=0)
    freed_bytes = models.BigIntegerField(default=0)
    reason = models.CharField(max_length=300)
    available_at = models.DateTimeField()
    attempts = models.PositiveIntegerField(default=0)
