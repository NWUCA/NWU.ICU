from django.conf import settings
from django.core.management.color import no_style
from django.db import migrations, models
from django.utils import timezone
import django.db.models.deletion


def migrate_legacy_messages(apps, schema_editor):
    Chat = apps.get_model('common', 'Chat')
    ChatMessage = apps.get_model('common', 'ChatMessage')
    ChatLike = apps.get_model('common', 'ChatLike')
    ChatReply = apps.get_model('common', 'ChatReply')
    Conversation = apps.get_model('common', 'Conversation')
    Participant = apps.get_model('common', 'ConversationParticipant')
    DirectMessage = apps.get_model('common', 'DirectMessage')
    Notification = apps.get_model('common', 'Notification')

    chat_to_conversation = {}
    pair_to_conversation = {}
    user_chats = Chat.objects.filter(classify='user', sender_id__isnull=False).order_by('id')
    for chat in user_chats.iterator():
        low_id, high_id = sorted((chat.sender_id, chat.receiver_id))
        pair = (low_id, high_id)
        conversation = pair_to_conversation.get(pair)
        if conversation is None:
            conversation, _ = Conversation.objects.get_or_create(
                user_low_id=low_id,
                user_high_id=high_id,
            )
            pair_to_conversation[pair] = conversation
            Participant.objects.bulk_create((
                Participant(conversation_id=conversation.id, user_id=low_id),
                Participant(conversation_id=conversation.id, user_id=high_id),
            ), ignore_conflicts=True)
        chat_to_conversation[chat.id] = conversation.id

    migrated_messages = []
    if chat_to_conversation:
        for message in ChatMessage.objects.filter(
            chat_item_id__in=chat_to_conversation,
            created_by_id__isnull=False,
        ).order_by('id').iterator():
            migrated_messages.append(DirectMessage(
                id=message.id,
                conversation_id=chat_to_conversation[message.chat_item_id],
                sender_id=message.created_by_id,
                content=message.content,
                created_at=message.create_time,
            ))
            if len(migrated_messages) >= 1000:
                DirectMessage.objects.bulk_create(migrated_messages, batch_size=1000)
                migrated_messages = []
        if migrated_messages:
            DirectMessage.objects.bulk_create(migrated_messages, batch_size=1000)

    for pair, conversation in pair_to_conversation.items():
        latest_id = DirectMessage.objects.filter(
            conversation_id=conversation.id
        ).order_by('-id').values_list('id', flat=True).first()
        if latest_id:
            Conversation.objects.filter(pk=conversation.id).update(last_message_id=latest_id)
        low_id, high_id = pair
        for user_id, other_id in ((low_id, high_id), (high_id, low_id)):
            read_through = ChatMessage.objects.filter(
                chat_item_id__in=[
                    chat_id for chat_id, conversation_id in chat_to_conversation.items()
                    if conversation_id == conversation.id
                ],
                created_by_id=other_id,
                read=True,
            ).order_by('-id').values_list('id', flat=True).first() or 0
            Participant.objects.filter(
                conversation_id=conversation.id,
                user_id=user_id,
            ).update(last_read_message_id=read_through)

    notifications = {}
    for like in ChatLike.objects.filter(receiver_id__isnull=False).select_related('raw_post_course').iterator():
        key = f'like:{like.raw_post_classify}:{like.raw_post_id}:{like.receiver_id}'
        course = like.raw_post_course
        event_time = like.latest_like_datetime or timezone.now()
        notifications[key] = Notification(
            recipient_id=like.receiver_id,
            actor_id=None,
            kind='like',
            dedupe_key=key,
            created_at=event_time,
            updated_at=event_time,
            read_at=event_time if like.read else None,
            payload={
                'raw_info': {
                    'raw_post': {
                        'classify': like.raw_post_classify,
                        'id': like.raw_post_id,
                        'content': like.raw_post_content or '',
                    },
                    'course': {
                        'id': course.id if course else None,
                        'name': course.name if course else '',
                    },
                },
                'like': {'like': like.like_count, 'dislike': like.dislike_count},
                'datetime': event_time.isoformat() if event_time else None,
            },
        )

    for reply in ChatReply.objects.filter(receiver_id__isnull=False).select_related(
        'reply_content', 'reply_content__created_by', 'raw_post_course'
    ).order_by('id').iterator():
        content = reply.reply_content
        actor = content.created_by
        course = reply.raw_post_course
        event_time = content.create_time
        key = f'reply:{content.id}:{reply.receiver_id}'
        notifications[key] = Notification(
            recipient_id=reply.receiver_id,
            actor_id=actor.id,
            kind='reply',
            dedupe_key=key,
            created_at=event_time,
            updated_at=event_time,
            read_at=event_time if reply.read else None,
            payload={
                'reply': {'id': content.id, 'content': content.content},
                'created_by': {
                    'id': actor.id,
                    'nickname': actor.nickname,
                    'uuid': str(actor.uuid),
                    'avatar': str(actor.avatar_uuid),
                    'has_avatar': True,
                },
                'course': {'id': course.id, 'name': course.name},
                'raw_post': {
                    'id': reply.raw_post_id,
                    'classify': reply.raw_post_classify,
                    'content': reply.raw_post_content,
                },
                'datetime': event_time.isoformat(),
            },
        )

    system_chats = Chat.objects.filter(classify='system')
    for message in ChatMessage.objects.filter(chat_item__in=system_chats).select_related('chat_item').iterator():
        key = f'legacy-system-message:{message.id}'
        event_time = message.create_time
        notifications[key] = Notification(
            recipient_id=message.chat_item.receiver_id,
            actor_id=message.created_by_id,
            kind='system',
            dedupe_key=key,
            created_at=event_time,
            updated_at=event_time,
            read_at=event_time if message.read else None,
            payload={
                'title': '系统通知',
                'content': message.content,
                'datetime': event_time.isoformat(),
            },
        )
    Notification.objects.bulk_create(notifications.values(), batch_size=1000, ignore_conflicts=True)

    for statement in schema_editor.connection.ops.sequence_reset_sql(no_style(), [DirectMessage, Notification]):
        schema_editor.execute(statement)


class Migration(migrations.Migration):
    dependencies = [
        ('common', '0036_unique_system_chat'),
        ('user', '0012_user_uuid'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Conversation',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('user_high', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='conversations_as_high_user', to=settings.AUTH_USER_MODEL)),
                ('user_low', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='conversations_as_low_user', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'constraints': [
                    models.CheckConstraint(check=models.Q(('user_low_id__lt', models.F('user_high_id'))), name='conversation_users_canonical_order'),
                    models.UniqueConstraint(fields=('user_low', 'user_high'), name='unique_conversation_user_pair'),
                ],
            },
        ),
        migrations.CreateModel(
            name='DirectMessage',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('content', models.TextField(max_length=500)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('conversation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='direct_messages', to='common.conversation')),
                ('sender', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='direct_messages_sent', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ('id',),
                'indexes': [
                    models.Index(fields=['conversation', 'id'], name='common_dm_conv_id_idx'),
                    models.Index(fields=['conversation', 'sender', 'id'], name='common_dm_conv_sender_idx'),
                ],
            },
        ),
        migrations.AddField(
            model_name='conversation',
            name='last_message',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='common.directmessage'),
        ),
        migrations.CreateModel(
            name='ConversationParticipant',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('last_read_message_id', models.PositiveBigIntegerField(default=0)),
                ('conversation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='participants', to='common.conversation')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='conversation_participations', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'indexes': [models.Index(fields=['user', 'conversation'], name='common_cp_user_conv_idx')],
                'constraints': [models.UniqueConstraint(fields=('conversation', 'user'), name='unique_conversation_participant')],
            },
        ),
        migrations.CreateModel(
            name='Notification',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('like', '点赞提醒'), ('reply', '回复提醒'), ('system', '系统通知')], max_length=16)),
                ('payload', models.JSONField(default=dict)),
                ('dedupe_key', models.CharField(max_length=255, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('read_at', models.DateTimeField(blank=True, null=True)),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='notifications_created', to=settings.AUTH_USER_MODEL)),
                ('recipient', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='notifications_received', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'indexes': [
                    models.Index(fields=['recipient', 'kind', 'read_at'], name='common_notif_unread_idx'),
                    models.Index(fields=['recipient', 'kind', '-updated_at'], name='common_notif_recent_idx'),
                ],
            },
        ),
        migrations.RunPython(migrate_legacy_messages, migrations.RunPython.noop),
    ]
