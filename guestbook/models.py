from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.utils import timezone

from utils.models import SoftDeleteModel


class VisibleAnnouncementDeleteError(ValueError):
    pass


class GuestbookEntry(SoftDeleteModel):
    """A top-level guestbook post or one node in its reply tree."""

    BOARD_GUESTBOOK = 'guestbook'
    BOARD_ANNOUNCEMENT = 'announcement'
    BOARD_CHOICES = (
        (BOARD_GUESTBOOK, '留言板'),
        (BOARD_ANNOUNCEMENT, '公告栏'),
    )

    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=100, blank=True, default='')
    content = models.TextField()
    anonymous = models.BooleanField(default=False)
    board = models.CharField(max_length=16, choices=BOARD_CHOICES, default=BOARD_GUESTBOOK)
    parent = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL, related_name='replies'
    )
    root = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL, related_name='descendants'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(default=timezone.now)
    priority = models.SmallIntegerField(
        default=0,
        validators=[MinValueValidator(-100), MaxValueValidator(100)],
    )
    is_visible = models.BooleanField(default=True)
    like_count = models.PositiveIntegerField(default=0)
    submission_id = models.UUIDField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ('-created_at', '-id')
        permissions = [('publish_announcements', 'Can publish announcements from the management panel')]
        constraints = [
            models.UniqueConstraint(fields=('author', 'submission_id'), name='unique_guestbook_submission'),
            models.CheckConstraint(
                check=models.Q(priority__gte=-100, priority__lte=100),
                name='guestbook_priority_range',
            ),
        ]
        indexes = [
            models.Index(fields=('board', '-created_at', '-id'), name='guestbook_board_recent_idx'),
            models.Index(
                fields=('board', 'parent', 'root', '-priority', '-updated_at', '-id'),
                name='guestbook_announce_sort_idx',
            ),
            models.Index(fields=('root', 'parent', 'created_at'), name='guestbook_reply_tree_idx'),
            models.Index(fields=('-created_at', '-id'), name='guestbook_recent_idx'),
        ]

    @property
    def is_root(self):
        return self.parent_id is None and self.root_id is None

    @transaction.atomic
    def soft_delete(self):
        # Serialize deletion with replies and likes, including their notifications.
        current = type(self).all_objects.select_for_update().get(pk=self.pk)
        if (
            current.board == self.BOARD_ANNOUNCEMENT
            and current.is_root
            and current.is_visible
        ):
            raise VisibleAnnouncementDeleteError('请先隐藏公告再删除。')
        if not current.is_deleted:
            super(GuestbookEntry, current).soft_delete()
        self.is_deleted, self.deleted_at = current.is_deleted, current.deleted_at
        if current.board == self.BOARD_ANNOUNCEMENT and current.is_root:
            from .notifications import remove_announcement_notifications
            remove_announcement_notifications(self.pk)
        else:
            from .notifications import remove_entry_notifications
            remove_entry_notifications(self.pk)

    def delete(self, using=None, keep_parents=False):
        self.soft_delete()


class GuestbookLike(models.Model):
    entry = models.ForeignKey(GuestbookEntry, on_delete=models.CASCADE, related_name='likes')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=('entry', 'user'), name='unique_guestbook_like_per_user'),
        ]


class GuestbookReport(models.Model):
    REASON_SPAM = 'spam'
    REASON_ABUSE = 'abuse'
    REASON_PRIVACY = 'privacy'
    REASON_OTHER = 'other'
    REASON_CHOICES = (
        (REASON_SPAM, '垃圾广告'),
        (REASON_ABUSE, '攻击辱骂'),
        (REASON_PRIVACY, '泄露隐私'),
        (REASON_OTHER, '其他'),
    )
    STATUS_PENDING = 'pending'
    STATUS_DISMISSED = 'dismissed'
    STATUS_REMOVED = 'removed'
    STATUS_CHOICES = (
        (STATUS_PENDING, '待处理'),
        (STATUS_DISMISSED, '已驳回'),
        (STATUS_REMOVED, '已移除内容'),
    )

    entry = models.ForeignKey(GuestbookEntry, on_delete=models.CASCADE, related_name='reports')
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    reason = models.CharField(max_length=16, choices=REASON_CHOICES)
    detail = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='handled_guestbook_reports',
    )
    handling_note = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    handled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        permissions = [('moderate_reports', 'Can moderate guestbook reports')]
        constraints = [
            models.UniqueConstraint(fields=('entry', 'reporter'), name='unique_guestbook_report_per_user'),
        ]
        indexes = [models.Index(fields=('status', '-created_at'), name='guestbook_report_status_idx')]
