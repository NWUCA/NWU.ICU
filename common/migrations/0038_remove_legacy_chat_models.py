from django.db import migrations


BATCH_SIZE = 1000
MAX_REPORTED_ERRORS = 20


def validate_legacy_chat_migration(apps, schema_editor):
    """Refuse to drop legacy tables unless every legacy record is represented.

    This operation and the DeleteModel operations below run in one transaction.
    Raising an exception here leaves all four legacy tables untouched.
    """

    Chat = apps.get_model('common', 'Chat')
    ChatMessage = apps.get_model('common', 'ChatMessage')
    ChatLike = apps.get_model('common', 'ChatLike')
    ChatReply = apps.get_model('common', 'ChatReply')
    Conversation = apps.get_model('common', 'Conversation')
    Participant = apps.get_model('common', 'ConversationParticipant')
    DirectMessage = apps.get_model('common', 'DirectMessage')
    Notification = apps.get_model('common', 'Notification')

    errors = []

    def add_error(message):
        if len(errors) < MAX_REPORTED_ERRORS:
            errors.append(message)

    legacy_chats = {}
    for chat in Chat.objects.all().only('id', 'sender_id', 'receiver_id', 'classify').iterator(
        chunk_size=BATCH_SIZE
    ):
        if chat.classify not in {'user', 'system', 'like', 'reply'}:
            add_error(f'Chat {chat.id} has unsupported classify={chat.classify!r}.')
        if chat.classify == 'user':
            if chat.sender_id is None or chat.sender_id == chat.receiver_id:
                add_error(f'User Chat {chat.id} does not contain two distinct users.')
            else:
                legacy_chats[chat.id] = tuple(sorted((chat.sender_id, chat.receiver_id)))

    conversations = {
        (row['user_low_id'], row['user_high_id']): row['id']
        for row in Conversation.objects.values('id', 'user_low_id', 'user_high_id').iterator(
            chunk_size=BATCH_SIZE
        )
    }
    participant_watermarks = {
        (row['conversation_id'], row['user_id']): row['last_read_message_id']
        for row in Participant.objects.values(
            'conversation_id', 'user_id', 'last_read_message_id'
        ).iterator(chunk_size=BATCH_SIZE)
    }
    expected_watermarks = {}
    for pair in set(legacy_chats.values()):
        conversation_id = conversations.get(pair)
        if conversation_id is None:
            add_error(f'No Conversation exists for legacy user pair {pair}.')
            continue
        for user_id in pair:
            if (conversation_id, user_id) not in participant_watermarks:
                add_error(f'Conversation {conversation_id} has no participant row for user {user_id}.')

    orphan_message_ids = list(
        ChatMessage.objects.filter(chat_item_id__isnull=True).values_list('id', flat=True)[:MAX_REPORTED_ERRORS]
    )
    for message_id in orphan_message_ids:
        add_error(f'ChatMessage {message_id} has no Chat and was not migrated.')

    unsupported_message_ids = list(
        ChatMessage.objects.filter(chat_item__classify__in=('like', 'reply')).values_list(
            'id', flat=True
        )[:MAX_REPORTED_ERRORS]
    )
    for message_id in unsupported_message_ids:
        add_error(f'ChatMessage {message_id} belongs to a legacy like/reply Chat and was not migrated.')

    message_batch = []

    def validate_message_batch(batch):
        migrated = {
            row['id']: row
            for row in DirectMessage.objects.filter(id__in=[message.id for message in batch]).values(
                'id', 'conversation_id', 'sender_id', 'content'
            )
        }
        for message in batch:
            pair = legacy_chats.get(message.chat_item_id)
            if pair is None:
                add_error(f'ChatMessage {message.id} has no valid legacy user conversation.')
                continue
            if message.created_by_id not in pair:
                add_error(f'ChatMessage {message.id} sender is not a conversation participant.')
            conversation_id = conversations.get(pair)
            actual = migrated.get(message.id)
            if actual is None:
                add_error(f'ChatMessage {message.id} has no DirectMessage with the same ID.')
                continue
            if (
                actual['conversation_id'] != conversation_id
                or actual['sender_id'] != message.created_by_id
                or actual['content'] != message.content
            ):
                add_error(f'ChatMessage {message.id} differs from its DirectMessage copy.')
            if message.read and message.created_by_id in pair and conversation_id is not None:
                reader_id = pair[0] if message.created_by_id == pair[1] else pair[1]
                key = (conversation_id, reader_id)
                expected_watermarks[key] = max(expected_watermarks.get(key, 0), message.id)

    user_messages = ChatMessage.objects.filter(chat_item__classify='user').only(
        'id', 'chat_item_id', 'created_by_id', 'content', 'read'
    ).order_by('id')
    for message in user_messages.iterator(chunk_size=BATCH_SIZE):
        if message.created_by_id is None:
            add_error(f'User ChatMessage {message.id} has no sender and was not migrated.')
        message_batch.append(message)
        if len(message_batch) == BATCH_SIZE:
            validate_message_batch(message_batch)
            message_batch = []
    if message_batch:
        validate_message_batch(message_batch)

    for key, expected in expected_watermarks.items():
        actual = participant_watermarks.get(key)
        if actual is None or actual < expected:
            add_error(
                f'Participant {key} read watermark {actual!r} is below migrated value {expected}.'
            )

    def validate_notification_entries(entries):
        actual_by_key = {
            row['dedupe_key']: row
            for row in Notification.objects.filter(
                dedupe_key__in=[entry[0] for entry in entries]
            ).values('dedupe_key', 'recipient_id', 'kind', 'payload')
        }
        for key, recipient_id, kind, expected_content in entries:
            actual = actual_by_key.get(key)
            if actual is None:
                add_error(f'Legacy notification {key!r} was not migrated.')
                continue
            if actual['recipient_id'] != recipient_id or actual['kind'] != kind:
                add_error(f'Legacy notification {key!r} has the wrong recipient or kind.')
                continue
            if expected_content is not None and actual['payload'].get('content') != expected_content:
                add_error(f'Legacy system notification {key!r} has different content.')

    notification_batch = []
    for like in ChatLike.objects.only(
        'id', 'raw_post_classify', 'raw_post_id', 'receiver_id'
    ).iterator(chunk_size=BATCH_SIZE):
        if like.receiver_id is None:
            add_error(f'ChatLike {like.id} has no recipient and was not migrated.')
            continue
        notification_batch.append((
            f'like:{like.raw_post_classify}:{like.raw_post_id}:{like.receiver_id}',
            like.receiver_id,
            'like',
            None,
        ))
        if len(notification_batch) == BATCH_SIZE:
            validate_notification_entries(notification_batch)
            notification_batch = []

    for reply in ChatReply.objects.only('reply_content_id', 'receiver_id').iterator(
        chunk_size=BATCH_SIZE
    ):
        notification_batch.append((
            f'reply:{reply.reply_content_id}:{reply.receiver_id}',
            reply.receiver_id,
            'reply',
            None,
        ))
        if len(notification_batch) == BATCH_SIZE:
            validate_notification_entries(notification_batch)
            notification_batch = []

    system_messages = ChatMessage.objects.filter(chat_item__classify='system').select_related(
        'chat_item'
    ).only('id', 'content', 'chat_item__receiver_id')
    for message in system_messages.iterator(chunk_size=BATCH_SIZE):
        notification_batch.append((
            f'legacy-system-message:{message.id}',
            message.chat_item.receiver_id,
            'system',
            message.content,
        ))
        if len(notification_batch) == BATCH_SIZE:
            validate_notification_entries(notification_batch)
            notification_batch = []
    if notification_batch:
        validate_notification_entries(notification_batch)

    if errors:
        details = '\n - '.join(errors)
        raise RuntimeError(
            'Legacy chat migration verification failed. No legacy table was removed.\n'
            f' - {details}'
        )


class Migration(migrations.Migration):
    # PostgreSQL supports transactional DDL. Validation and all four drops are
    # deliberately one atomic unit, so any exception restores every old table.
    atomic = True

    dependencies = [
        ('common', '0037_conversation_notification_models'),
    ]

    operations = [
        migrations.RunPython(validate_legacy_chat_migration, migrations.RunPython.noop),
        migrations.DeleteModel(name='ChatLike'),
        migrations.DeleteModel(name='ChatReply'),
        migrations.DeleteModel(name='ChatMessage'),
        migrations.DeleteModel(name='Chat'),
    ]
