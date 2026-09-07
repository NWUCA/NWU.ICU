from django.conf import settings
from django.db import models
from django.db.models import Q

from user.models import User


class Announcement(models.Model):
    TYPE_CHOICES = [
        ('all', '全局'),
        ('course', '课程评价'),
    ]

    content = models.TextField()
    type = models.TextField(choices=TYPE_CHOICES)
    create_time = models.DateTimeField(auto_now_add=True)
    update_time = models.DateTimeField(auto_now=True)
    enabled = models.BooleanField(default=True)


class Bulletin(models.Model):
    title = models.TextField()
    content = models.TextField()
    create_time = models.DateTimeField(auto_now_add=True)
    update_time = models.DateTimeField(auto_now=True)
    enabled = models.BooleanField(default=True)
    publisher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)


class WebPushSubscription(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    update_time = models.DateTimeField(auto_now=True)
    subscription = models.JSONField()


class About(models.Model):
    TYPE_CHOICES = [
        ('about', '关于'),
        ('blogs', '博文'),
    ]
    title = models.TextField(default='')
    content = models.TextField()
    create_time = models.DateTimeField(auto_now_add=True)
    update_time = models.DateTimeField(auto_now=True)
    weight = models.IntegerField(default=0)
    type = models.TextField(choices=TYPE_CHOICES, default='about')


class Conversation(models.Model):
    """Canonical one-to-one conversation.

    ``user_low`` and ``user_high`` are ordered by primary key so the database,
    rather than application convention alone, guarantees one row per user pair.
    """

    user_low = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='conversations_as_low_user',
    )
    user_high = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='conversations_as_high_user',
    )
    last_message = models.ForeignKey(
        'DirectMessage',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=Q(user_low_id__lt=models.F('user_high_id')),
                name='conversation_users_canonical_order',
            ),
            models.UniqueConstraint(
                fields=('user_low', 'user_high'),
                name='unique_conversation_user_pair',
            ),
        ]

    @staticmethod
    def canonical_user_ids(first_user, second_user):
        first_id = first_user.pk if isinstance(first_user, User) else int(first_user)
        second_id = second_user.pk if isinstance(second_user, User) else int(second_user)
        if first_id == second_id:
            raise ValueError('A conversation requires two different users.')
        return min(first_id, second_id), max(first_id, second_id)

    def other_user(self, user):
        if user.pk == self.user_low_id:
            return self.user_high
        if user.pk == self.user_high_id:
            return self.user_low
        raise ValueError('User is not a participant in this conversation.')


class ConversationParticipant(models.Model):
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='participants',
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='conversation_participations',
    )
    # A monotonic global message-id watermark. Keeping this as an integer makes
    # it survive future message retention/deletion without moving backwards.
    last_read_message_id = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('conversation', 'user'),
                name='unique_conversation_participant',
            ),
        ]
        indexes = [
            models.Index(fields=('user', 'conversation'), name='common_cp_user_conv_idx'),
        ]


class DirectMessage(models.Model):
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='direct_messages',
    )
    sender = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='direct_messages_sent',
    )
    content = models.TextField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=('conversation', 'id'), name='common_dm_conv_id_idx'),
            models.Index(fields=('conversation', 'sender', 'id'), name='common_dm_conv_sender_idx'),
        ]
        ordering = ('id',)


class ResourceAccessRule(models.Model):
    path = models.CharField(max_length=2048, unique=True)
    mode = models.CharField(max_length=16, choices=[('login', '登录用户'), ('admin', '资料管理员')])


class ResourceAuditEvent(models.Model):
    actor = models.CharField(max_length=150)
    action = models.CharField(max_length=32, db_index=True)
    path = models.TextField(blank=True)
    destination = models.TextField(blank=True)
    detail = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)


class ResourceDownloadEvent(models.Model):
    dedupe_key = models.CharField(max_length=64, unique=True)
    path = models.TextField()
    authenticated = models.BooleanField(default=False)
    ip_address = models.GenericIPAddressField(null=True, blank=True, db_index=True)
    # Snapshots preserve historical attribution when an account is renamed/deleted.
    user_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    username = models.CharField(max_length=150, blank=True)
    user_agent = models.CharField(max_length=2048, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)


class Notification(models.Model):
    KIND_LIKE = 'like'
    KIND_REPLY = 'reply'
    KIND_SYSTEM = 'system'
    KIND_CHOICES = (
        (KIND_LIKE, '点赞提醒'),
        (KIND_REPLY, '回复提醒'),
        (KIND_SYSTEM, '系统通知'),
    )

    recipient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notifications_received',
    )
    actor = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='notifications_created',
    )
    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    payload = models.JSONField(default=dict)
    dedupe_key = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=('recipient', 'kind', 'read_at'), name='common_notif_unread_idx'),
            models.Index(fields=('recipient', 'kind', '-updated_at'), name='common_notif_recent_idx'),
        ]
