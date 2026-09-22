from django.conf import settings
from django.db import models


class AdminPasskeyState(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='admin_passkey_state',
    )
    revision = models.PositiveBigIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)


class AdminPasskeyCredential(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='admin_passkeys',
    )
    name = models.CharField(max_length=100)
    credential_id = models.BinaryField(unique=True, editable=False)
    public_key = models.BinaryField(editable=False)
    sign_count = models.PositiveBigIntegerField(default=0)
    transports = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at', '-id')
        indexes = [models.Index(fields=('user', 'revoked_at'), name='admin_passkey_active_idx')]


class AdminPasskeyEnrollment(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='admin_passkey_enrollments',
    )
    token_digest = models.CharField(max_length=64, unique=True, editable=False)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at', '-id')
        indexes = [models.Index(fields=('user', 'expires_at'), name='admin_enroll_expiry_idx')]


class TelegramNotificationSettings(models.Model):
    """Singleton switches for administrator-facing Telegram event alerts."""

    user_registration_enabled = models.BooleanField(default=True, verbose_name='用户注册')
    guestbook_entry_enabled = models.BooleanField(default=True, verbose_name='发表留言')
    course_review_enabled = models.BooleanField(default=True, verbose_name='发表课程评价')
    reply_enabled = models.BooleanField(default=True, verbose_name='发表回复')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Telegram 通知设置'
        verbose_name_plural = 'Telegram 通知设置'

    def save(self, *args, **kwargs):
        # This table is deliberately a singleton so all web/worker processes
        # observe the same switches without environment changes or restarts.
        self.pk = 1
        return super().save(*args, **kwargs)
