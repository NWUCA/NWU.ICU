from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.db.models.functions import Greatest

from common.models import (
    Conversation,
    ConversationParticipant,
    DirectMessage,
)


def get_conversation(first_user, second_user):
    low_id, high_id = Conversation.canonical_user_ids(first_user, second_user)
    return (
        Conversation.objects.select_related('user_low', 'user_high', 'last_message')
        .get(user_low_id=low_id, user_high_id=high_id)
    )


def get_or_create_conversation(first_user, second_user):
    low_id, high_id = Conversation.canonical_user_ids(first_user, second_user)
    try:
        with transaction.atomic():
            conversation, created = Conversation.objects.get_or_create(
                user_low_id=low_id,
                user_high_id=high_id,
            )
    except IntegrityError:
        # A concurrent request may have committed the canonical pair first.
        conversation = Conversation.objects.get(
            user_low_id=low_id,
            user_high_id=high_id,
        )
        created = False

    ConversationParticipant.objects.bulk_create(
        (
            ConversationParticipant(conversation=conversation, user_id=low_id),
            ConversationParticipant(conversation=conversation, user_id=high_id),
        ),
        ignore_conflicts=True,
    )
    return conversation, created


def send_direct_message(sender, recipient, content):
    with transaction.atomic():
        conversation, _ = get_or_create_conversation(sender, recipient)
        message = DirectMessage.objects.create(
            conversation=conversation,
            sender=sender,
            content=content,
        )
        # Message ids are monotonic. The condition prevents a delayed concurrent
        # transaction from moving the conversation preview backwards.
        Conversation.objects.filter(pk=conversation.pk).filter(
            Q(last_message_id__isnull=True) | Q(last_message_id__lt=message.pk)
        ).update(last_message_id=message.pk)
    return message


def mark_conversation_read(conversation, user, through_message_id):
    if user.pk not in (conversation.user_low_id, conversation.user_high_id):
        raise PermissionError('User is not a participant in this conversation.')
    if through_message_id < 0:
        raise ValueError('Message watermark cannot be negative.')
    if through_message_id and not DirectMessage.objects.filter(
        conversation=conversation,
        pk=through_message_id,
    ).exists():
        raise ValueError('Message does not belong to this conversation.')

    participant, _ = ConversationParticipant.objects.get_or_create(
        conversation=conversation,
        user=user,
    )
    ConversationParticipant.objects.filter(pk=participant.pk).update(
        last_read_message_id=Greatest(
            F('last_read_message_id'),
            through_message_id,
        )
    )


def get_unread_message_count(conversation, user, last_read_message_id=None):
    if last_read_message_id is None:
        last_read_message_id = ConversationParticipant.objects.filter(
            conversation=conversation,
            user=user,
        ).values_list('last_read_message_id', flat=True).first() or 0
    return DirectMessage.objects.filter(
        conversation=conversation,
        id__gt=last_read_message_id,
    ).exclude(sender=user).count()
